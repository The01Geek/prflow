#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Consolidate pending ``.changeset/*.md`` files into a version bump + CHANGELOG entry.

PRFlow versions itself with changesets instead of editing ``.claude-plugin/plugin.json``
and ``CHANGELOG.md`` in every PR (see ``.changeset/README.md``). This helper runs at merge
time (push to ``main``) from the ``version-consolidate`` workflow at
``.github/workflows/version-consolidate.yml``:

  * globs every pending ``.changeset/*.md`` (ignoring ``README.md``),
  * parses each file's ``bump:`` (required) + optional ``type:`` frontmatter and prose body,
  * computes the single highest pending bump (``patch`` < ``minor`` < ``major``),
  * rewrites ``.claude-plugin/plugin.json``'s ``version`` by that increment,
  * rewrites ``CITATION.cff``'s ``version`` to the same value (when the file is present),
  * rewrites the ``marketplace.json`` plugin entry's ``version`` to the same value (when present),
  * rewrites every **derived** pinned-release-tag site (the installer download URL and
    ``DEVFLOW_REF=`` payload ref in the docs) to ``v<new version>`` — see
    ``scripts/version_pins.py``, which owns the derivation — so the tagged tree is
    self-consistent and the docs at tag ``vN`` say ``vN`` (issue #953),
  * prepends a dated, PR-cited Keep-a-Changelog entry assembled from all the prose,
  * for every changeset marked ``customer-visible: true`` (issue #2070), reuses its prose
    verbatim as an entry in ``docs/external/release-notes.md`` under the merge date's
    ``## Month Day, Year`` heading — so a customer-facing release note is written once, in
    the reviewed changeset, instead of by a second per-PR authoring pass; an unmarked set
    leaves that page byte-identical, and
  * deletes the consumed changeset files.

It writes nothing else into the repository — staging and the ``chore: bump version`` commit
are the workflow's job. (The two opt-in ``$RUNNER_TEMP`` side channels documented below live
outside the repository tree by design, so they are not exceptions to that.)

Three optional side-channel outputs exist for the workflow, all written **outside** the
repository (``$RUNNER_TEMP``) so they never enter the commit: ``--emit-entry-to`` writes
the assembled CHANGELOG entry body (the GitHub Release notes), ``--emit-write-set-to``
writes one repo-relative path per line for every file this run rewrote, and
``--emit-bump-to`` writes the single highest pending bump kind (``patch``/``minor``/
``major``). The write set is what lets the workflow stage a **derived** pin-rewrite set
explicitly, without resorting to ``git add -A``. The bump kind is what lets the workflow
tell ``scripts/publish-release.sh`` whether this bump warrants a *published* GitHub
Release (``minor``/``major``) or only its annotated tag (``patch``) — it is reported from
the value computed here rather than re-inferred downstream from a version diff.

Fail-closed contract: a malformed changeset (no frontmatter, missing/invalid ``bump``, an
unknown ``type``, or an empty prose body) aborts with exit 2 and a diagnostic naming the
offending file. Everything is **validated before any file is modified** — all changesets are
parsed *and* every output file (``plugin.json``, ``CHANGELOG.md``, plus ``CITATION.cff`` and
``.claude-plugin/marketplace.json`` when present) is read and its new
contents assembled in memory *before* the first write, so a malformed changeset or an
output-side read/parse fault never causes a silent skip or a partial bump — it aborts before
any write. (Those up to four writes are themselves sequential and non-atomic, so a *write*-side
fault can still leave some outputs rewritten and the rest not; the workflow commits from
a fresh ``git reset --hard origin/main`` checkout on each attempt, so a half-write is never
committed.) Every OS-level fault (a read, write, or delete)
is wrapped into the same name-the-file exit-2 path — a top-level ``except OSError`` backstop in
``main`` catches any site not individually wrapped — so the tool never exits 1 with a bare
``OSError`` traceback. Zero pending changesets is a clean no-op: nothing is written and the
exit code is 0.
"""

from __future__ import annotations

import argparse
import calendar
import os
import re
import sys
from datetime import datetime, timezone
from typing import NamedTuple

# version_pins owns the DERIVATION of the pinned-release-tag site set (no hardcoded file
# list). Python already puts this script's directory on sys.path[0], but be explicit so an
# invocation through a symlink or a wrapper still resolves the sibling module.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import version_pins

# Single source of the ordered bump domain: _BUMP_RANK is DERIVED from VALID_BUMPS (mirroring
# the CANONICAL_TYPES → _TYPE_BY_LOWER pattern below), so adding a bump value cannot desync the
# two into a KeyError at the `max(..., key=_BUMP_RANK.__getitem__)` lookup.
VALID_BUMPS = ("patch", "minor", "major")
_BUMP_RANK = {bump: rank for rank, bump in enumerate(VALID_BUMPS)}

# Keep-a-Changelog section names, in the canonical order they render within an entry.
CANONICAL_TYPES = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
_TYPE_BY_LOWER = {t.lower(): t for t in CANONICAL_TYPES}
DEFAULT_TYPE = "Changed"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ChangesetError(Exception):
    """A malformed changeset or manifest — the fail-closed, name-the-file path."""


class Frontmatter(NamedTuple):
    """A changeset split into its YAML frontmatter text and prose body."""

    frontmatter: str
    body: str


class Changeset(NamedTuple):
    """One parsed changeset: its bump kind, CHANGELOG section, prose body, and
    customer-visibility marker."""

    bump: str
    section: str
    prose: str
    customer_visible: bool


def _fatal(msg: str) -> int:
    sys.stderr.write(f"consolidate-changesets.py: {msg}\n")
    return 2


def _is_consumable(name: str) -> bool:
    """A ``.changeset/*.md`` file that is a real changeset (only ``README.md`` is exempt).

    Every other ``*.md`` here is treated as a changeset — an unexpected one with no valid
    frontmatter fails the run loudly (naming it) rather than being silently skipped, which
    is the fail-closed behavior this tool wants. (The npm ``@changesets`` ``config.json`` is
    not markdown, so it is already excluded by the ``.md`` filter — no ``config.*`` special
    case is needed, and a broad one would silently drop a legitimately-named changeset.)
    """
    return name.lower() != "readme.md" and name.lower().endswith(".md")


def _split_frontmatter(path: str) -> Frontmatter:
    """Return a ``Frontmatter(frontmatter, body)`` for a changeset, or raise ChangesetError.

    The file MUST start with a ``---`` fence (a leading BOM or any other prefix defeats
    detection and is rejected loudly rather than silently mis-parsed).
    """
    text = _read_text(path, "changeset")
    m = re.match(r"---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)\Z", text, re.DOTALL)
    if not m:
        raise ChangesetError(
            f"{path}: no YAML frontmatter found — a changeset must start with a "
            "'---' fenced block declaring 'bump:' (a leading BOM or blank line "
            "also trips this)"
        )
    return Frontmatter(m.group(1), m.group(2))


def _parse_changeset(path: str) -> Changeset:
    """Parse one changeset → ``Changeset(bump, section, prose)``; raise on malformed input."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ChangesetError(
            "PyYAML is required to parse changeset frontmatter but is not installed"
        ) from exc

    split = _split_frontmatter(path)
    fm_text, body = split.frontmatter, split.body
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise ChangesetError(f"{path}: frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(fm, dict):
        raise ChangesetError(
            f"{path}: frontmatter must be a YAML mapping with a 'bump:' key"
        )

    bump = fm.get("bump")
    if bump is None:
        raise ChangesetError(
            f"{path}: missing required 'bump:' key (expected one of {', '.join(VALID_BUMPS)})"
        )
    if not isinstance(bump, str) or bump.lower() not in VALID_BUMPS:
        raise ChangesetError(
            f"{path}: invalid bump value {bump!r} — expected one of {', '.join(VALID_BUMPS)}"
        )
    bump = bump.lower()

    raw_type = fm.get("type", DEFAULT_TYPE)
    if not isinstance(raw_type, str) or raw_type.lower() not in _TYPE_BY_LOWER:
        raise ChangesetError(
            f"{path}: invalid type value {raw_type!r} — expected one of "
            f"{', '.join(CANONICAL_TYPES)}"
        )
    section = _TYPE_BY_LOWER[raw_type.lower()]

    prose = body.strip()
    if not prose:
        raise ChangesetError(
            f"{path}: empty prose body — a changeset must describe the change "
            "(one or more '-' bullets, PR-cited)"
        )

    # customer-visible marker (issue #2070): only the parsed Python bool True marks; any
    # other PRESENT value raises. Detect key-PRESENCE (`in fm`, not `.get()`) so an explicit
    # null is caught here, never silently read as an absent (not-customer-visible) key.
    customer_visible = False
    if "customer-visible" in fm:
        marker = fm["customer-visible"]
        if marker is True:
            customer_visible = True
        else:
            raise ChangesetError(
                f"{path}: invalid customer-visible value {marker!r} — the only accepted "
                "value is the boolean true (spell it 'customer-visible: true'); omit the "
                "key entirely for a change with no customer-visible impact"
            )

    return Changeset(bump, section, prose, customer_visible)


def _bump_version(current: str, kind: str) -> str:
    if not VERSION_RE.match(current):
        raise ChangesetError(
            f".claude-plugin/plugin.json: version {current!r} is not an N.N.N string"
        )
    major, minor, patch = (int(p) for p in current.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# Read/write the version with a surgical regex rather than json.load/json.dump (or the
# repo's jq-based read): a full JSON round-trip would reserialize the whole manifest and
# churn unrelated formatting (key order, indentation) on every bump. The read uses the same
# regex as the write so the two stay symmetric and neither shells out to jq from Python.
def _read_manifest_version(manifest_path: str) -> str:
    text = _read_text(manifest_path, "manifest")
    m = re.search(r'"version"\s*:\s*"([^"]*)"', text)
    if not m:
        raise ChangesetError(f"{manifest_path}: no \"version\" key found")
    return m.group(1)


def _read_text(path: str, what: str) -> str:
    """Read ``path`` as UTF-8 text, wrapping any OS fault into the name-the-file exit-2 path.

    Mirror of ``_write_text`` so read and write share one wrap site — a new reader cannot
    diverge with a subtly different or missing diagnostic.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise ChangesetError(f"{path}: cannot read {what}: {exc}") from exc


def _write_text(path: str, text: str) -> None:
    """Write ``text`` to ``path``, wrapping any OS fault into the name-the-file exit-2 path."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        raise ChangesetError(f"{path}: cannot write: {exc}") from exc


def _render_manifest(manifest_path: str, new_version: str) -> str:
    """Read the manifest and return its new text with only the version string rewritten.

    Pure read + assemble (no write) so ``consolidate`` can prove both outputs are writable-in-
    memory before touching disk. Preserves the manifest's exact formatting.
    """
    text = _read_text(manifest_path, "manifest")
    new_text, n = re.subn(
        r'("version"\s*:\s*")[^"]*(")',
        lambda mo: mo.group(1) + new_version + mo.group(2),
        text,
        count=1,
    )
    if n != 1:
        raise ChangesetError(f"{manifest_path}: could not rewrite the version string")
    return new_text


def _render_citation(citation_path: str, new_version: str) -> str:
    """Read ``CITATION.cff`` and return its text with only the top-level ``version`` rewritten.

    Uses the same surgical-regex approach as ``_render_manifest`` (no YAML round-trip, so the
    file's exact formatting is preserved). The pattern is anchored to a line beginning exactly
    ``version:`` (``re.MULTILINE``), so the sibling ``cff-version:`` key is never matched.
    Pure read + assemble (no write) so ``consolidate`` can prove the output is writable-in-
    memory before touching disk.

    Deliberately carries no multi-match count guard (unlike ``_render_marketplace_version``,
    whose JSON ``"version"`` keys can legitimately recur at several depths): the column-0
    ``(?m)^version:`` anchor can only match a *top-level* CFF key, and a duplicate top-level
    key is invalid YAML, so a second real match is impossible for a valid CITATION.cff. Loosen
    that anchor (e.g. allowing leading whitespace, which would reach nested mapping keys) and
    the guard becomes necessary — add it in the same change.
    """
    text = _read_text(citation_path, "citation")
    new_text, n = re.subn(
        r"(?m)^(version:[ \t]*)\S.*$",
        lambda mo: mo.group(1) + new_version,
        text,
        count=1,
    )
    if n != 1:
        raise ChangesetError(f"{citation_path}: could not rewrite the version field")
    return new_text


def _render_marketplace_version(marketplace_path: str, new_version: str) -> str:
    """Read ``marketplace.json`` and return its text with the plugin entry's ``version`` rewritten.

    The marketplace manifest carries exactly one ``version`` key (its single ``plugins[0]``
    entry's — there is no marketplace-level ``version``), so the same surgical JSON regex
    ``_render_manifest`` uses, with ``count=1``, targets it and no other. Pure read + assemble
    (no write), so ``consolidate`` can prove the output is writable-in-memory before touching
    disk, and formatting is preserved. Keeps the marketplace listing's advertised plugin version
    in lockstep with the ``plugin.json`` the consolidator bumps.
    """
    text = _read_text(marketplace_path, "marketplace")
    # Guard the single-version-key assumption before the surgical count=1 rewrite. If a future
    # marketplace grows a marketplace-level version, or a second plugin entry, a first-match
    # rewrite would silently bump the wrong key and leave the others stale (n==1 would still
    # hold, so no error fires). Fail LOUD instead — a multi-version manifest needs a structural
    # rewrite, not this first-match regex — rather than silently ship a half-bumped listing.
    # The count is textual, not structural: a literal `"version": "` occurring *inside* a string
    # value would also be counted. That over-counts, never under-counts, so it fails in the safe
    # direction (a loud refusal to rewrite, never a silent wrong-key bump). A structural count
    # would need a json.loads walk, which this deliberately-formatting-preserving path avoids.
    total = len(re.findall(r'"version"\s*:\s*"', text))
    if total != 1:
        raise ChangesetError(
            f"{marketplace_path}: expected exactly one \"version\" key (the single plugin "
            f"entry's) but found {total} — the surgical single-key rewrite is unsafe here; a "
            "marketplace with a top-level version or multiple plugin entries needs a "
            "structural rewrite"
        )
    new_text, n = re.subn(
        r'("version"\s*:\s*")[^"]*(")',
        lambda mo: mo.group(1) + new_version + mo.group(2),
        text,
        count=1,
    )
    if n != 1:
        raise ChangesetError(
            f"{marketplace_path}: could not rewrite the plugin entry version"
        )
    return new_text


def _assemble_entry(version: str, date: str, sections: dict[str, list[str]]) -> str:
    """Build the ``## [version] — date`` Keep-a-Changelog block from grouped prose."""
    lines = [f"## [{version}] — {date}", ""]
    for section in CANONICAL_TYPES:
        proses = sections.get(section)
        if not proses:
            continue
        lines.append(f"### {section}")
        lines.extend(proses)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_changelog(changelog_path: str, entry: str) -> str:
    """Read the changelog and return its new text with ``entry`` prepended.

    Pure read + assemble (no write): ``entry`` is inserted immediately before the first
    existing ``## [`` version heading, or appended after the preamble when none exists.
    """
    lines = _read_text(changelog_path, "changelog").splitlines(keepends=True)
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("## ["):
            insert_at = i
            break
    block = entry.rstrip("\n") + "\n\n"
    if insert_at is None:
        # No prior versioned entry — append after the file's preamble.
        return "".join(lines).rstrip("\n") + "\n\n" + block
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def _render_release_notes(release_notes_path: str, proses: list[str], date: str) -> str:
    """Read the release-notes page and return its new text with one entry per marked
    changeset prose inserted under the merge-date heading (issue #2070).

    Pure read + assemble (no write), so ``consolidate`` can prove the output is
    writable-in-memory before touching disk. Reproduces the ``docs-release-notes`` skill's
    Step 4 placement — the shipped skill body stays byte-untouched, so this is a
    deliberate reproduction, not a shared call:

      * the merge date is formatted ``## Month Day, Year`` (built from the date parts via
        ``calendar`` to avoid the GNU-only ``%-d`` strftime directive),
      * when that heading is absent it is created at the top of the page's date sections —
        immediately before the most recent existing ``## Month Day, Year`` heading, so any
        page preamble between the H1 and the first date section is preserved — or directly
        below the file's first ``# `` H1 when the page has no date section yet (a
        ``# Release Notes`` H1 is created first when the file has none),
      * when the heading is already present each entry is appended under it, after any
        existing entries for that date.
    """
    # `date` is the already-validated YYYY-MM-DD. calendar.month_name (not strptime) avoids
    # both the naive-datetime lint and the GNU-only %-d directive for a leading-zero-free day.
    year, month, day = (int(part) for part in date.split("-"))
    heading = f"## {calendar.month_name[month]} {day}, {year}"
    entry_lines = [line for prose in proses for line in prose.split("\n")]

    text = _read_text(release_notes_path, "release notes")
    had_final_newline = text.endswith("\n")
    lines = text.split("\n")
    if had_final_newline and lines and lines[-1] == "":
        lines.pop()  # drop the empty tail split() leaves after a final newline

    existing = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
    if existing is not None:
        # Append under the existing same-date heading, after its current entries: find the
        # next heading (or EOF) and back up over trailing blank lines to the section's end.
        section_end = len(lines)
        for j in range(existing + 1, len(lines)):
            if lines[j].startswith("## ") or lines[j].startswith("# "):
                section_end = j
                break
        while section_end > existing + 1 and lines[section_end - 1].strip() == "":
            section_end -= 1
        new_lines = lines[:section_end] + entry_lines + lines[section_end:]
    else:
        block = [heading, "", *entry_lines]
        first_section = next(
            (i for i, ln in enumerate(lines) if ln.startswith("## ")), None
        )
        h1 = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
        if first_section is not None:
            # Deviates from issue #2070's literal "directly below the first H1": on a page
            # with preamble prose that would split; insert at the TOP of the date-section
            # list (before the most recent existing one) instead. See the workpad AC-rewrite.
            new_lines = lines[:first_section] + [*block, ""] + lines[first_section:]
        elif h1 is None:
            tail = lines[1:] if lines and lines[0].strip() == "" else lines
            new_lines = ["# Release Notes", "", *block, "", *tail]
        else:
            # No date section yet: fall back to directly below the H1. Drop one leading
            # blank from the remainder so the trailing blank we add is not doubled.
            rest = lines[h1 + 1 :]
            if rest and rest[0].strip() == "":
                rest = rest[1:]
            new_lines = lines[: h1 + 1] + ["", *block, "", *rest]

    out = "\n".join(new_lines)
    if had_final_newline:
        out += "\n"
    return out


def consolidate(
    root: str,
    date: str,
    entry_out: str | None = None,
    write_set_out: str | None = None,
    bump_out: str | None = None,
) -> int:
    changeset_dir = os.path.join(root, ".changeset")
    manifest_path = os.path.join(root, ".claude-plugin", "plugin.json")
    changelog_path = os.path.join(root, "CHANGELOG.md")
    citation_path = os.path.join(root, "CITATION.cff")
    marketplace_path = os.path.join(root, ".claude-plugin", "marketplace.json")
    release_notes_path = os.path.join(root, "docs", "external", "release-notes.md")

    if not os.path.isdir(changeset_dir):
        print("no .changeset/ directory — nothing to consolidate")
        return 0

    try:
        names = os.listdir(changeset_dir)
    except OSError as exc:
        raise ChangesetError(f"{changeset_dir}: cannot list changesets: {exc}") from exc
    pending = sorted(
        os.path.join(changeset_dir, n) for n in names if _is_consumable(n)
    )
    if not pending:
        print("no pending changesets — no version bump, no CHANGELOG entry")
        return 0

    # Parse ALL changesets first (fail-closed: no write happens until every file is valid).
    parsed = [_parse_changeset(p) for p in pending]

    highest = max((cs.bump for cs in parsed), key=_BUMP_RANK.__getitem__)
    current = _read_manifest_version(manifest_path)
    new_version = _bump_version(current, highest)

    sections: dict[str, list[str]] = {}
    for cs in parsed:
        sections.setdefault(cs.section, []).append(cs.prose)
    entry = _assemble_entry(new_version, date, sections)

    # Read-before-write: assemble BOTH output files' new contents in memory (each read here
    # can raise ChangesetError) before writing either — so an output-side read/parse fault
    # aborts before any write, leaving plugin.json and CHANGELOG.md byte-for-byte unchanged.
    # No os.access() check-then-write (TOCTOU): the render helpers do the real read.
    new_manifest = _render_manifest(manifest_path, new_version)
    new_changelog = _render_changelog(changelog_path, entry)
    # CITATION.cff tracks the manifest version. It is optional supplementary metadata: absent
    # → skipped (None); present-but-unrewritable → _render_citation raises before any write,
    # preserving the read-before-write atomicity guarantee above.
    new_citation = (
        _render_citation(citation_path, new_version)
        if os.path.exists(citation_path)
        else None
    )
    # The marketplace entry advertises the same plugin version; keep it in lockstep so the
    # listing never drifts behind the manifest. Same optional/read-before-write treatment as
    # CITATION.cff: absent → skipped; present-but-unrewritable → raises before any write.
    new_marketplace = (
        _render_marketplace_version(marketplace_path, new_version)
        if os.path.exists(marketplace_path)
        else None
    )
    # Pinned release-tag sites (issue #953). The site set is DERIVED by version_pins from
    # two machine-recognizable forms, so a documentation page added later cannot silently
    # escape the bump. Same read-before-write treatment: render_rewrites only reads and
    # assembles, so a read fault aborts before the first write rather than leaving the
    # tagged tree half-bumped — the docs at tag vN must say vN.
    try:
        pin_rewrites = version_pins.render_rewrites(root, new_version)
    except version_pins.VersionPinError as exc:
        raise ChangesetError(f"pinned release-tag sites: {exc}") from exc

    # Customer-visible release-note entries (issue #2070): a `customer-visible: true`
    # changeset's prose is reused verbatim, in pending order. Rendered only when at least one
    # is marked, so an unmarked consolidation leaves release-notes.md byte-identical (AC2).
    marked_proses = [cs.prose for cs in parsed if cs.customer_visible]
    new_release_notes = (
        _render_release_notes(release_notes_path, marked_proses, date)
        if marked_proses
        else None
    )

    _write_text(manifest_path, new_manifest)
    _write_text(changelog_path, new_changelog)
    if new_citation is not None:
        _write_text(citation_path, new_citation)
    if new_marketplace is not None:
        _write_text(marketplace_path, new_marketplace)
    if new_release_notes is not None:
        _write_text(release_notes_path, new_release_notes)
    for pin_path in sorted(pin_rewrites):
        _write_text(pin_path, pin_rewrites[pin_path])
    for path in pending:
        try:
            os.remove(path)
        except OSError as exc:
            raise ChangesetError(f"{path}: cannot delete consumed changeset: {exc}") from exc

    # Side channels for the workflow, written outside the repo so they never enter the
    # commit. Both are written LAST: they describe a consolidation that already happened,
    # and a fault here must not be mistaken for a half-applied bump.
    if entry_out:
        _write_text(entry_out, entry)
    if write_set_out:
        written = [manifest_path, changelog_path]
        if new_citation is not None:
            written.append(citation_path)
        if new_marketplace is not None:
            written.append(marketplace_path)
        if new_release_notes is not None:
            written.append(release_notes_path)
        written.extend(pin_rewrites)
        rels = sorted(os.path.relpath(p, root) for p in written)
        _write_text(write_set_out, "".join(f"{r}\n" for r in rels))
    # The bump kind the release decision reads. Written only on a run that actually bumped:
    # the no-pending-changesets early return leaves the file ABSENT rather than writing a
    # default, so a downstream reader can tell "no bump happened" from "a patch bump did".
    if bump_out:
        _write_text(bump_out, f"{highest}\n")

    print(
        f"consolidated {len(pending)} changeset(s): {current} -> {new_version} "
        f"(highest bump: {highest}); prepended CHANGELOG entry, rewrote "
        f"{len(pin_rewrites)} file(s) carrying pinned release-tag sites, and removed "
        "consumed files"
    )
    return 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Repository root (default: the PRFlow checkout containing this script)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Entry date as YYYY-MM-DD (default: today, UTC)",
    )
    parser.add_argument(
        "--emit-entry-to",
        default=None,
        metavar="PATH",
        help=(
            "Also write the assembled CHANGELOG entry body to PATH (the GitHub Release "
            "notes). Point it OUTSIDE the repository so it never enters the bump commit."
        ),
    )
    parser.add_argument(
        "--emit-write-set-to",
        default=None,
        metavar="PATH",
        help=(
            "Also write one repo-relative path per line for every file this run rewrote, "
            "so the workflow can stage a derived set explicitly instead of 'git add -A'. "
            "Point it OUTSIDE the repository."
        ),
    )
    parser.add_argument(
        "--emit-bump-to",
        default=None,
        metavar="PATH",
        help=(
            "Also write the single highest pending bump kind (patch/minor/major) to PATH, "
            "so the workflow can decide whether this bump warrants a published GitHub "
            "Release or only its tag. Point it OUTSIDE the repository."
        ),
    )
    args = parser.parse_args(argv)
    date = args.date or datetime.now(timezone.utc).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return _fatal(f"--date {date!r} is not YYYY-MM-DD")
    # Validate the calendar date, not just its digit shape: a bad month (13) would otherwise
    # raise an uncaught IndexError from calendar.month_name[month] in _render_release_notes,
    # and a bad day would render a garbage heading — both escaping the fail-loud exit-2
    # contract. monthrange raises IllegalMonthError (a ValueError) for a bad month.
    _y, _m, _d = (int(part) for part in date.split("-"))
    try:
        _, _days_in_month = calendar.monthrange(_y, _m)
    except calendar.IllegalMonthError:
        return _fatal(f"--date {date!r} names an invalid month")
    if not 1 <= _d <= _days_in_month:
        return _fatal(f"--date {date!r} names a day outside its month")
    try:
        return consolidate(
            args.root,
            date,
            args.emit_entry_to,
            args.emit_write_set_to,
            args.emit_bump_to,
        )
    except ChangesetError as exc:
        return _fatal(str(exc))
    except OSError as exc:
        # Removal-proof backstop: every OS site above is individually wrapped into a
        # ChangesetError, but a site added later (or missed) must still exit 2 with a
        # diagnostic rather than a bare OSError traceback / exit 1.
        return _fatal(f"unhandled OS error: {exc}")


if __name__ == "__main__":
    sys.exit(main())

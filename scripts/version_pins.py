#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Derive, enforce, and rewrite the repo's pinned release-tag sites.

The install documentation pins a **release tag** so a reader downloads and runs
reproducible bytes. Two independent pins carry that tag, and both are *executable*
text a user copy-pastes — a stale one silently installs an older PRFlow:

* the installer **download URL**, ``raw.githubusercontent.com/<owner>/<repo>/vN.N.N/…``
* the installer's **payload ref**, ``DEVFLOW_REF=vN.N.N``

Before issue #953 nothing coupled those to ``.claude-plugin/plugin.json``'s version,
so the merge-time bump (``scripts/consolidate-changesets.py``, run by
``.github/workflows/version-consolidate.yml``) moved the version and left the docs a
release behind. This module closes that loop from both ends:

* ``render_rewrites()`` is called by the consolidator inside its read-before-write
  assembly phase, so the pin rewrite lands **in the same commit as the bump** and the
  tagged tree is self-consistent — the docs at tag ``vN`` say ``vN``.
* ``--check`` is driven by ``lib/test/run.sh`` as an ordinary executable test: every
  derived pin site must agree with ``plugin.json``. It is **offline** — no network and
  no ``gh`` — so it runs in the network-free suite; its one subprocess is a local
  ``git ls-files`` (see *Scanned population* below), which reads the index and touches
  nothing remote. The complementary *tag-existence* assertion does need the network and
  therefore lives in ``version-consolidate.yml`` (``scripts/publish-release.sh``).

**The site set is DERIVED, never enumerated.** A new documentation page that pins the
installer is picked up because it matches one of the two patterns above — there is no
checked-in list of files to forget to extend. Two consequences worth knowing:

* A pin site must be written in one of those two **machine-recognizable** forms.
  Surrounding *prose* deliberately points at the pinned command rather than
  re-quoting the version (the repo's single-source-of-truth default), so no prose
  copy exists for this tool to miss.
* A version-shaped token that is **not** one of those two forms is not a release pin
  and is left alone — a vendored tool version (``SHELLCHECK v0.11.0``), an
  upstream runner version (``Copilot CLI v1.0.67``), a spec URL
  (``semver.org/spec/v2.0.0.html``) or a historical migration note (``v2.8.12``).

**Scanned population — two sources, chosen by ENTRY POINT, not by circumstance.**

*The CLI* (``--check``, ``--list``, ``--rewrite``) sources its population from an
**index-reading ``git ls-files``** — no ``--others`` — and fails closed (exit 2) when
that enumeration cannot be established. This is the repo's issue-#711 convention, and
it is a *structural* property rather than a blocklist: a checker whose answer depends
on untracked host state is a checker that goes red locally and green on a fresh CI
checkout, varying between runs on the same commit. A filesystem walk cannot have that
property — every exclusion list it carries is a blocklist that the next untracked
directory defeats. PRFlow's own review scratch (``.prflow/tmp/``, which holds a
cached ``diff.patch`` carrying both pin forms at arbitrary versions) is the instance
that proved it; the index population removes the whole class, scratch dirs that do
not exist yet included.

*The library* (``find_pin_sites``/``render_rewrites`` called with no explicit
population) falls back to a **filesystem walk** from ``root``. That is the path
``scripts/consolidate-changesets.py`` takes, and it is deliberate: the consolidator
makes no ``git`` calls (issue #290), so it stays unit-testable against a plain temp
directory. Soundness there rests on *where it runs* — the merge-time bump runs in a
fresh ``actions/checkout`` with no untracked scratch — not on the exclusion list. A
caller that wants the index population passes it explicitly.

Both populations then drop the same non-pin content:

* ``.git``, ``.claude``, ``node_modules``, ``__pycache__`` — VCS/tooling internals,
  plus (``.claude``) this repo's sibling-git-worktree root.
* ``.changeset/`` and ``CHANGELOG.md`` — release *history*. Past entries name past
  versions on purpose and must never be rewritten forward.
* ``.prflow/learnings/`` and ``.prflow/logs/`` — machine-appended corpora that quote
  historical text verbatim.
* ``.prflow/vendor/`` — a materialized copy of some *other* release of the plugin.
* ``lib/test/`` — the suite's own fixtures deliberately carry drifted pins (that is
  the negative control for this very guard).

Non-UTF-8 files are skipped as non-text rather than failing the scan.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Literal, NamedTuple

# The two machine-recognizable release-pin forms. Each pattern captures the semver in a
# `version` group and preserves everything else, so a rewrite is surgical.
PIN_PATTERNS = (
    (
        "raw-url",
        re.compile(
            r"raw\.githubusercontent\.com/[^/\s\"'<>]+/[^/\s\"'<>]+/v(?P<version>\d+\.\d+\.\d+)/"
        ),
    ),
    ("devflow-ref", re.compile(r"\bDEVFLOW_REF=v(?P<version>\d+\.\d+\.\d+)")),
)

# Directory names pruned wherever they occur in the walk. `.claude` is the issue-#711
# sibling-worktree guard; the rest are VCS/tooling internals.
PRUNED_DIR_NAMES = frozenset({".git", ".claude", "node_modules", "__pycache__"})

# Repo-relative path prefixes excluded from the scan. Each is release history or a
# machine-appended corpus that quotes past versions verbatim, except lib/test/, whose
# fixtures deliberately carry drifted pins so this guard has a negative control.
EXCLUDED_PREFIXES = (
    ".changeset/",
    ".prflow/learnings/",
    ".prflow/logs/",
    ".prflow/vendor/",
    "lib/test/",
)

# Repo-relative files excluded from the scan (release history).
EXCLUDED_FILES = frozenset({"CHANGELOG.md"})

MANIFEST_RELPATH = os.path.join(".claude-plugin", "plugin.json")

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VersionPinError(Exception):
    """A structural fault — an unreadable manifest, a malformed version, an OS error."""


# The closed vocabulary of PIN_PATTERNS' names, so a renamed/typo'd pattern label is a
# compile-visible break at the PinSite construction site rather than a silent cross-site
# mismatch (every consumer — the --list output, the drift diagnostic — reads this string).
PatternName = Literal["raw-url", "devflow-ref"]


class PinSite(NamedTuple):
    """One derived release-pin occurrence."""

    relpath: str
    lineno: int
    pattern: PatternName
    version: str


def _is_excluded(relpath: str) -> bool:
    posix = relpath.replace(os.sep, "/")
    if posix in EXCLUDED_FILES:
        return True
    return any(posix.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def iter_scanned_files(root: str) -> "list[str]":
    """Return the repo-relative paths of the WALK population, sorted.

    The library default (see the module docstring): git-free, so the consolidator that
    calls ``render_rewrites`` keeps its issue-#290 no-``git`` contract and its temp-dir
    unit tests. The CLI does **not** use this — it uses ``resolve_index_population``.
    """

    def _boom(exc: OSError) -> None:
        # os.walk's default onerror=None DISCARDS a directory-listing error and simply
        # omits that subtree, so a drifted pin under an unreadable directory would be
        # invisible and --check would print "all agree" over a tree it never fully read.
        # Mirror _read_text_or_none's file-level fail-closed handling instead.
        raise VersionPinError(f"{getattr(exc, 'filename', root)}: cannot list: {exc}")

    found: "list[str]" = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=_boom):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        # Prune during the walk rather than filtering after it, so the scan never even
        # descends into a sibling worktree or opens a machine-appended corpus.
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in PRUNED_DIR_NAMES
            and not _is_excluded((os.path.join(rel_dir, d) if rel_dir else d) + "/")
        )
        for name in sorted(filenames):
            rel = os.path.join(rel_dir, name) if rel_dir else name
            if _is_excluded(rel):
                continue
            found.append(rel)
    return found


def _is_pruned_path(relpath: str) -> bool:
    """True when any path component is a pruned directory name (the walk's prune rule,
    re-expressed for a flat path list so both populations drop the same content)."""
    return any(part in PRUNED_DIR_NAMES for part in relpath.replace(os.sep, "/").split("/"))


def resolve_index_population(root: str) -> "list[str]":
    """Return the repo-relative INDEX population — ``git ls-files``, no ``--others``.

    This is the issue-#711 contract and the CLI's only population. It fails **closed**:
    a missing ``git``, a ``root`` that is not a work tree, a non-zero ``git``, or an
    empty enumeration all raise ``VersionPinError`` (exit 2) rather than degrading to a
    filesystem walk. A silent fallback would restore exactly the untracked-host-state
    dependence this function exists to remove — the guard would go quiet in precisely
    the situation where it can no longer establish what it is guarding.
    """
    try:
        res = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached"],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise VersionPinError(
            f"{root}: cannot enumerate the tracked files with git ls-files: {exc}"
        ) from exc
    if res.returncode != 0:
        detail = res.stderr.decode("utf-8", "replace").strip() or f"rc {res.returncode}"
        raise VersionPinError(
            f"{root}: git ls-files failed ({detail}); the scanned population is "
            "index-derived and is never inferred from a filesystem walk"
        )
    raw = res.stdout.decode("utf-8", "replace")
    paths = sorted(p for p in raw.split("\0") if p)
    if not paths:
        raise VersionPinError(f"{root}: git ls-files reported no tracked files")
    # A path in the index but absent from the working tree (a staged delete, a submodule
    # gitlink, a dangling symlink) carries no pin text to read. Dropping it here keeps the
    # read path's OSError arm meaning "a file that IS there could not be read".
    return [
        p
        for p in paths
        if not _is_excluded(p)
        and not _is_pruned_path(p)
        and os.path.isfile(os.path.join(root, p))
    ]


def _read_text_or_none(path: str) -> "str | None":
    """Read ``path`` as UTF-8 text; return ``None`` when it is not decodable text.

    A binary asset is not a pin site, so it is skipped rather than failing the scan.
    A real OS fault (permissions, a vanished file) is a structural problem and raises.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return None
    except OSError as exc:
        raise VersionPinError(f"{path}: cannot read: {exc}") from exc


def find_pin_sites(root: str, files: "list[str] | None" = None) -> "list[PinSite]":
    """Derive every release-pin occurrence under ``root``, in stable scan order.

    ``files`` is the repo-relative population to scan; ``None`` selects the git-free
    walk (see the module docstring's entry-point split).
    """
    sites: "list[PinSite]" = []
    for rel in iter_scanned_files(root) if files is None else files:
        text = _read_text_or_none(os.path.join(root, rel))
        if text is None:
            continue
        # Cheap pre-filter: neither pattern can match without one of these substrings.
        if "raw.githubusercontent.com" not in text and "DEVFLOW_REF=" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PIN_PATTERNS:
                for match in pattern.finditer(line):
                    sites.append(PinSite(rel, lineno, name, match.group("version")))
    return sites


def read_manifest_version(root: str) -> str:
    """Return ``.claude-plugin/plugin.json``'s version string."""
    path = os.path.join(root, MANIFEST_RELPATH)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise VersionPinError(f"{path}: cannot read the plugin manifest: {exc}") from exc
    match = re.search(r'"version"\s*:\s*"([^"]*)"', text)
    if not match:
        raise VersionPinError(f'{path}: no "version" key found')
    version = match.group(1)
    if not VERSION_RE.match(version):
        raise VersionPinError(f"{path}: version {version!r} is not an N.N.N string")
    return version


def _rewrite_text(text: str, new_version: str) -> str:
    """Return ``text`` with every release-pin occurrence's version set to ``new_version``."""

    def _sub(mo: "re.Match[str]") -> str:
        whole = mo.group(0)
        head = whole[: mo.start("version") - mo.start()]
        tail = whole[mo.end("version") - mo.start() :]
        return head + new_version + tail

    for _name, pattern in PIN_PATTERNS:
        text = pattern.sub(_sub, text)
    return text


def render_rewrites(
    root: str, new_version: str, files: "list[str] | None" = None
) -> "dict[str, str]":
    """Return ``{absolute path: new text}`` for every file whose pins need moving.

    Pure read + assemble — **no writes**. This mirrors ``consolidate-changesets.py``'s
    read-before-write contract: the consolidator proves every output is assemblable in
    memory before it touches disk, so a read fault can never leave a half-bumped tree.
    Files already at ``new_version`` are omitted, so a no-op bump writes nothing.

    ``files`` defaults to the git-free walk, which is what the consolidator gets; the
    CLI's ``--rewrite`` passes the index population explicitly.
    """
    if not VERSION_RE.match(new_version):
        raise VersionPinError(f"{new_version!r} is not an N.N.N version string")
    rewrites: "dict[str, str]" = {}
    for rel in iter_scanned_files(root) if files is None else files:
        abspath = os.path.join(root, rel)
        text = _read_text_or_none(abspath)
        if text is None:
            continue
        if "raw.githubusercontent.com" not in text and "DEVFLOW_REF=" not in text:
            continue
        new_text = _rewrite_text(text, new_version)
        if new_text != text:
            rewrites[abspath] = new_text
    return rewrites


def _write_rewrites(rewrites: "dict[str, str]") -> None:
    for path, text in sorted(rewrites.items()):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            raise VersionPinError(f"{path}: cannot write: {exc}") from exc


def check(
    root: str, files: "list[str] | None" = None, out=sys.stdout, err=sys.stderr
) -> int:
    """Assert every derived pin site agrees with the manifest. 0 clean, 1 on drift.

    An **empty** site set is a fault, not a clean pass. ``drifted`` is empty both when
    every pin agrees and when the derivation found nothing at all, so a pattern
    regression, a docs restructure that reflows the pinned command, or an over-broadened
    exclusion set would silence this guard and the merge-time ``render_rewrites`` at the
    same moment — the guard passing loudest exactly where it has stopped working. The
    floor makes that state exit 2 instead.
    """
    expected = read_manifest_version(root)
    sites = find_pin_sites(root, files)
    if not sites:
        raise VersionPinError(
            "the derivation found NO pinned release-tag site — an empty site set is a "
            "fault, not a clean tree. Both derived patterns matching nothing means the "
            "merge-time bump would silently repin nothing either; check whether a pin "
            "was reworded out of the two machine-recognizable forms, or the scanned "
            "population was narrowed past the docs that carry them"
        )
    drifted = [s for s in sites if s.version != expected]
    if drifted:
        err.write(
            f"version_pins.py: {len(drifted)} pinned release-tag site(s) disagree with "
            f"{MANIFEST_RELPATH} (version {expected}):\n"
        )
        for site in drifted:
            err.write(
                f"  {site.relpath}:{site.lineno}: {site.pattern} pins v{site.version}, "
                f"expected v{expected}\n"
            )
        err.write(
            "version_pins.py: the merge-time bump rewrites these automatically; a drift "
            "here means a pin was authored in a form the two derived patterns do not "
            "match, or the tree was hand-edited.\n"
        )
        return 1
    out.write(
        f"version_pins.py: {len(sites)} pinned release-tag site(s) all agree with "
        f"{MANIFEST_RELPATH} (v{expected})\n"
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


def main(argv: "list[str] | None" = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description="Derive/enforce/rewrite release-tag pins.")
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Repository root (default: the PRFlow checkout containing this script)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Assert every derived pin site matches plugin.json's version (the default)",
    )
    mode.add_argument(
        "--list",
        action="store_true",
        help="Print every derived pin site as 'path:line<TAB>pattern<TAB>version'",
    )
    mode.add_argument(
        "--rewrite",
        metavar="VERSION",
        help="Rewrite every derived pin site to VERSION and print the files changed",
    )
    mode.add_argument(
        "--print-version",
        action="store_true",
        help="Print plugin.json's version (the value a release tag is derived from)",
    )
    args = parser.parse_args(argv)

    try:
        if args.print_version:
            # Reads the manifest only — no population to enumerate, so it stays usable
            # (and `git`-free) wherever a checkout's index is not the question.
            print(read_manifest_version(args.root))
            return 0
        # Every population-scanning CLI mode is index-sourced and fails closed (#711).
        files = resolve_index_population(args.root)
        if args.list:
            for site in find_pin_sites(args.root, files):
                print(f"{site.relpath}:{site.lineno}\t{site.pattern}\tv{site.version}")
            return 0
        if args.rewrite:
            rewrites = render_rewrites(args.root, args.rewrite, files)
            _write_rewrites(rewrites)
            for path in sorted(rewrites):
                print(os.path.relpath(path, args.root))
            return 0
        return check(args.root, files)
    except VersionPinError as exc:
        sys.stderr.write(f"version_pins.py: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

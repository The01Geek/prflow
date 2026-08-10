#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a prompt surface a cloud review run auto-loads names a bundled
verdict-post helper by a repo-relative `scripts/`/`lib/` spelling the cloud matcher does
not grant (issues #1248, #1526).

Why this exists: the cloud permission matcher grants each bundled helper ONLY as the
repo-relative vendored literal `.prflow/vendor/prflow/scripts/<name>` (and `…/lib/…`).
A shipped prompt sentence that spells the same helper `scripts/<name>` — either as an
invocation instruction or as a bare name a reader might copy — is a leading token no
profile grants: a cloud run that emits it is refused BEFORE it runs, producing no
output at all, and the review engine then takes its silence arm and finishes with no
verdict marker. That is exactly what happened on three completed review runs on
2026-08-03/04 (the verdict-post helper `post-review-verdict.sh` was invoked as
`scripts/post-review-verdict.sh` and silently denied).

`lib/test/extract-command-heads.py` cannot catch this by explicit design — it scans
only fenced `bash` blocks, and these spellings live in inline-backtick prose, out of
its reach (matching prose would resurrect the false-positive class it exists to
avoid). A repo-relative path to a bundled helper is not English text, though: it is an
unambiguous, closed shape that cannot occur by accident in prose, so it can be audited
without that hazard. This lint does exactly that, with the same declaration-marker escape
hatch as `lib/test/lint-shipped-pruned-path.py` (issue #1072), which is its structural
sibling.

AUDITED POPULATION, and where its boundary sits (issue #1526). The population is every
surface whose text reaches a cloud review run's context by the run's own machinery, not
by an agent choosing to open a file:

  * `skills/**` and `agents/**` — the shipped prompt bodies (the issue-#1248 population).
  * `.prflow/prompt-extensions/**` — consumer policy the loader ladder appends verbatim
    to a skill's prompt. The prefix also takes in the `*.md.example` templates, which no
    run loads; that over-inclusion is deliberate and fail-safe (a finding on one would be
    loud, never a missed surface).
  * `CLAUDE.md` — auto-loaded as project memory at the workspace root of every review
    run, and read on instruction by several `agents/*.md` reviewers besides.
  * `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` — in scope only because `CLAUDE.md` names
    it as the canonical statement of the verdict-marker contract, so a run following that
    pointer reads it with project-memory authority.

The boundary stops there deliberately, and the standing convention that documentation
names a helper by its canonical `scripts/<name>` source path is why. Auditing `docs/**`
or the tree at large would flag dozens of legitimate naming mentions on pages no run
loads — the same over-reach FORBIDDEN SET below rejects for the ~30 other vendored-only
helpers. What survives both narrowings is small by construction: the two verdict-post
basenames — one of which was OBSERVED causing a silent cloud denial, both of which are
in scope by the policy `IN_SCOPE_BASENAMES` records — on the surfaces a run reads without
being asked to.

The membership rule, stated so a maintainer can apply it rather than re-argue it: a
surface is audited when the run's own machinery loads it (a prefix above), or when it is
at **depth 1** from `CLAUDE.md` — a page `CLAUDE.md` designates as the *canonical*
statement of a rule whose non-authoritative summary it carries, so a run following the
pointer reads it with project-memory authority. Depth stops at 1: a page linked from a
depth-1 page is not audited, or the population would close over the whole documentation
graph. **Two disclosed residuals, both in the direction that fails silently.** First:
`CLAUDE.md` designates several `docs/internal/*.md` pages as canonical, and `AUDITED_PATHS`
is hand-maintained rather than derived from those pointers, so a canonical page not listed
below is unaudited and can teach a run the denied spelling while this lint reports clean —
a maintainer who moves a helper-invocation rule to a new canonical page adds that page here
in the same change. Second: the population is files the run loads, so the **machine-composed**
prompt text a run also receives — the rendered grounding block, and the workflows' inline
`prompt:` bodies — is loaded by the run's own machinery yet audited nowhere here. Both are
clean today; neither is guarded.

MATCHED SHAPE (the thing that FAILS the lint). For each forbidden helper, a repo-
relative path token whose first segment is exactly `scripts/` or `lib/` immediately
followed by that helper's basename — e.g. `scripts/post-review-verdict.sh` — where the
character before the segment is NOT one of `/`, `.`, `-`, or a word character. That
negative-lookbehind is what makes the shape closed and prose-safe:

EXCLUSIONS (each PASSES the lint), and why:
  * the granted vendored literal `.prflow/vendor/prflow/scripts/<name>` — the `/`
    before `scripts` fails the lookbehind, so the one spelling that IS granted is never
    flagged.
  * the portable source anchor `"${CLAUDE_SKILL_DIR:-…}"/../../scripts/<name>` — the
    `/` before `scripts` likewise fails the lookbehind (this is the #275 anchor form
    every legitimate skill fence writes in source).
  * a bare filename `<name>` with no `scripts/`/`lib/` segment — the PRESCRIBED form for
    a sentence that merely NAMES the helper (issue #1248 AC1); it carries no segment to
    match.
  * ordinary English prose containing the word "scripts" — it never contains the full
    `scripts/<forbidden-basename>` literal.
  * a line carrying the declaration marker `<!-- ungranted-helper-ok: <reason> -->`
    (prose) or `# ungranted-helper-ok: <reason>` (inside an emitted shell fence), reason
    non-empty — the sanctioned escape hatch for a line that must show the bad form.

FORBIDDEN SET (deliberately narrow, and derived). The forbidden basenames are the
INTERSECTION of two sets: (1) the helpers the capability manifest grants ONLY at the
vendored literal — parsed from `lib/capability-profiles.json` (a `Bash(.prflow/vendor/
prflow/(scripts|lib)/<name>:*)` grant with NO bare `Bash((scripts|lib)/<name>:*)`
grant), so the lint's premise (the repo-relative spelling is ungranted → denied) is
re-derived from the live manifest rather than assumed; and (2) the documented in-scope
basenames `IN_SCOPE_BASENAMES` below — the verdict-post helpers issue #1248 brought
under the "bare filename to name, vendored literal to invoke" discipline. The
intersection, not set (1) alone, is deliberate: ~30 other bundled helpers are also
vendored-only, but the shipped surface still NAMES many of them by their canonical
`scripts/<name>` source path in ordinary prose (the repo's documentation convention),
and those naming mentions are harmless — they are not invocation instructions and no
cloud run emits them as a leading token. Auditing all of them would flag dozens of
legitimate mentions and is a separate, larger cleanup out of this issue's scope. This
lint guards only the two helpers whose repo-relative spelling was OBSERVED causing
silent cloud denials with no verdict marker. If an in-scope basename is NOT vendored-
only in the manifest (a bare grant was added, or the vendored grant removed), the
premise no longer holds: the lint REFUSES non-zero naming the helper, so the scope is
revisited rather than silently mis-auditing.

Population is enumerated from the git index and filtered to the surfaces above
(`lib/test/lint_population.py`'s `enumerate_population` with the index-reading argv —
no `--others`, no repository-root-anchored recursive walk, per issue #711).

Usage:
    lint-ungranted-helper-spelling.py [--root DIR] [--files-from PATH]
                                      [--manifest PATH] [--print-forbidden-set]

Exit status is 0 only when the forbidden set was established, the enumeration selected
at least one audited file, every selected file was read, and none named a forbidden
helper by its repo-relative spelling without a marker. It is non-zero when a reference
is found, when the forbidden set cannot be established, when the enumeration is
unusable, when it selects no audited file at all, and when any selected path could not
be read.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Shared population enumeration / reader / fail-closed contract (issue #724), loaded by
# path exactly as the sibling lints do.
_POP_PATH = _REPO_ROOT / "lib" / "test" / "lint_population.py"
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
_pop_spec.loader.exec_module(_pop)
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_INDEX",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"lint-ungranted-helper-spelling: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

#: The audited population is markdown source; a NUL-carrying decode is reported as a
#: skip (never scanned) and fails the run closed, mirroring the sibling lints.
_SKIP_NUL = True

#: Path prefixes whose files make up the audited population.
AUDITED_PREFIXES = ("skills/", "agents/", ".prflow/prompt-extensions/")

#: Exact repo-relative paths that join the population without their whole directory
#: joining with them. Hand-maintained: see the module docstring's AUDITED POPULATION
#: section for the membership rule, the depth-1 boundary, and its disclosed residual.
#: Deriving this tuple from `CLAUDE.md`'s canonical-pointer set was considered and
#: deferred: those pointers are ordinary prose links with no machine-readable shape, so a
#: derivation would be a heuristic whose own miss is equally silent. Revisit if a canonical
#: pointer gains a parseable form, or if a real denial is ever traced to an unlisted page.
AUDITED_PATHS = (
    "CLAUDE.md",
    "docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md",
)

#: The default capability manifest, relative to the resolved root.
DEFAULT_MANIFEST_REL = "lib/capability-profiles.json"

#: The verdict-post helpers issue #1248 brought under the naming discipline. This is the
#: one deliberately hand-maintained value in the lint: which helpers are guarded is a
#: policy scope, not a fact derivable from the manifest (every bundled helper is
#: vendored-only). It is intersected with the manifest-derived vendored-only set so the
#: lint fails closed if the grant premise for one of these ever changes.
IN_SCOPE_BASENAMES = (
    "post-review-verdict.sh",
    "dismiss-stale-rejections.sh",
)


class ForbiddenSetError(Exception):
    """The forbidden set could not be established from the manifest. Fails closed."""


_GRANT_RE = re.compile(r"Bash\((?P<path>[^:()]+):\*\)$")
_VENDORED_RE = re.compile(r"^\.prflow/vendor/prflow/(scripts|lib)/(.+)$")
_BARE_RE = re.compile(r"^(scripts|lib)/(.+)$")


def _iter_grant_paths(obj) -> list[str]:
    """Every `Bash(<path>:*)` grant path anywhere in the manifest JSON."""
    out: list[str] = []
    if isinstance(obj, str):
        m = _GRANT_RE.match(obj)
        if m:
            out.append(m.group("path"))
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_iter_grant_paths(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_iter_grant_paths(value))
    return out


def establish_forbidden(manifest_text: str) -> list[str]:
    """Return the sorted forbidden repo-relative literals (`scripts/<name>`), or raise.

    A pair qualifies when its basename is in IN_SCOPE_BASENAMES AND the manifest grants
    it at the vendored literal AND grants no bare `scripts/`/`lib/` form of it. An
    in-scope basename that is NOT vendored-only (bare-granted, or not vendored at all)
    voids the lint's premise for it and raises — the scope is revisited rather than
    silently mis-audited.
    """
    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise ForbiddenSetError(f"manifest is not valid JSON: {exc}") from exc

    paths = _iter_grant_paths(manifest)
    vendored: set[tuple[str, str]] = set()
    bare: set[tuple[str, str]] = set()
    for path in paths:
        v = _VENDORED_RE.match(path)
        if v:
            vendored.add((v.group(1), v.group(2)))
        b = _BARE_RE.match(path)
        if b:
            bare.add((b.group(1), b.group(2)))

    forbidden: list[str] = []
    for basename in IN_SCOPE_BASENAMES:
        matching = [(seg, name) for (seg, name) in vendored if name == basename]
        if not matching:
            raise ForbiddenSetError(
                f"in-scope helper '{basename}' is not granted at any vendored literal "
                "in the manifest — its ungranted-spelling premise no longer holds; "
                "revisit IN_SCOPE_BASENAMES"
            )
        for seg, name in matching:
            if (seg, name) in bare:
                raise ForbiddenSetError(
                    f"in-scope helper '{seg}/{basename}' is ALSO granted at the bare "
                    f"'{seg}/' form in the manifest — the repo-relative spelling is no "
                    "longer ungranted; revisit IN_SCOPE_BASENAMES"
                )
            forbidden.append(f"{seg}/{name}")
    if not forbidden:
        raise ForbiddenSetError("no in-scope helper resolved to a forbidden spelling")
    return sorted(set(forbidden))


#: A recognized declaration marker, by fence context. Each requires a non-empty reason.
_MARKER_HTML = re.compile(r"<!--\s*ungranted-helper-ok:\s*(\S.*?)\s*-->")
_MARKER_SHELL = re.compile(r"#\s*ungranted-helper-ok:\s*(\S.*?)\s*$")

#: A line at column 0 opening/closing a fenced block (indented fences are not fences).
_FENCE = re.compile(r"^(`{3,}|~{3,})")


def _fence_states(lines: list[str]) -> list[bool]:
    """Return, per line, whether that content line is inside a fenced block.

    Mirrors scripts/load-prompt-extension.sh (the in-repo rule of record) and the
    sibling pruned-path lint: both fence characters tracked, a fence closes only on its
    own kind, an unclosed fence runs to end of file, an indented fence is not a fence.
    """
    states: list[bool] = []
    fence_char: str | None = None
    for line in lines:
        m = _FENCE.match(line)
        if m:
            char = line[0]
            if fence_char is None:
                fence_char = char
                states.append(False)  # opening delimiter
                continue
            if fence_char == char:
                fence_char = None
                states.append(False)  # closing delimiter
                continue
            states.append(True)  # a delimiter of the other kind is interior content
            continue
        states.append(fence_char is not None)
    return states


def _compile_forbidden(forbidden: list[str]) -> list[tuple[str, re.Pattern]]:
    """One regex per forbidden literal, matched only when NOT `/`/`.`/`-`/word-preceded."""
    return [
        (literal, re.compile(r"(?<![\w./-])" + re.escape(literal)))
        for literal in forbidden
    ]


def scan_text(text: str, patterns: list[tuple[str, re.Pattern]]) -> list[tuple[int, str]]:
    """Return (1-based line number, matched literal) for each unmarked reference."""
    lines = text.split("\n")
    states = _fence_states(lines)
    found: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        hit = next((lit for lit, pat in patterns if pat.search(line)), None)
        if hit is None:
            continue
        marker = _MARKER_SHELL if states[idx] else _MARKER_HTML
        if marker.search(line):
            continue
        found.append((idx + 1, hit))
    return found


def population_description() -> str:
    """One phrase naming the audited population, for the refusal message."""
    return " or ".join(AUDITED_PREFIXES + AUDITED_PATHS)


def is_audited(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in AUDITED_PATHS:
        return True
    return any(normalized.startswith(p) for p in AUDITED_PREFIXES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a prompt surface a cloud review run auto-loads names a bundled "
            "verdict-post helper by its ungranted repo-relative scripts/ or lib/ "
            "spelling without a declaration marker."
        )
    )
    _pop.add_population_arguments(parser)
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "the capability manifest to derive the vendored-only set from "
            "(default: <root>/" + DEFAULT_MANIFEST_REL + ")"
        ),
    )
    parser.add_argument(
        "--print-forbidden-set",
        action="store_true",
        help="print the derived forbidden set (one per line) and exit, auditing nothing",
    )
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-ungranted-helper-spelling")
    manifest_source = Path(args.manifest) if args.manifest else root / DEFAULT_MANIFEST_REL

    try:
        manifest_text = manifest_source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"lint-ungranted-helper-spelling: could not read manifest {manifest_source}: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    try:
        forbidden = establish_forbidden(manifest_text)
    except ForbiddenSetError as exc:
        print(
            f"lint-ungranted-helper-spelling: could not establish a forbidden set from "
            f"{manifest_source}: {exc}; auditing nothing",
            file=sys.stderr,
        )
        return 1

    literals = forbidden  # establish_forbidden already returns sorted repo-relative literals
    if args.print_forbidden_set:
        for literal in literals:
            print(literal)
        return 0

    patterns = _compile_forbidden(forbidden)

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except EnumerationError as exc:
        print(
            f"lint-ungranted-helper-spelling: enumeration unusable: {exc}",
            file=sys.stderr,
        )
        return 1

    audited = [path for path in population if is_audited(path)]
    if not audited:
        print(
            "lint-ungranted-helper-spelling: the enumeration selected no file under "
            f"{population_description()} — refusing to report clean over an "
            "unaudited prompt surface",
            file=sys.stderr,
        )
        return 1

    findings: list[str] = []
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=_SKIP_NUL)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        read_ok += 1
        for number, hit in scan_text(text, patterns):
            findings.append(
                f"{relative}:{number}: names bundled helper by ungranted repo-relative "
                f"spelling '{hit}' with no ungranted-helper-ok marker (use the bare "
                "filename to name it, or the vendored literal to invoke it)"
            )

    for finding in findings:
        print(finding)
    for relative, reason in skipped:
        print(
            f"lint-ungranted-helper-spelling: SKIPPED {relative}: {reason}",
            file=sys.stderr,
        )
    print(
        f"lint-ungranted-helper-spelling: audited {read_ok} of {len(audited)} files"
        + (f" ({len(skipped)} skipped)" if skipped else "")
        + f"; forbidden set: {' '.join(literals)}"
    )
    if skipped:
        print(
            f"lint-ungranted-helper-spelling: {len(skipped)} selected path(s) could not "
            "be audited — refusing to report clean; see the SKIPPED lines above",
            file=sys.stderr,
        )
        return 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

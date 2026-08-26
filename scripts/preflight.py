#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Run deterministic Phase 1 preflight checks for /devflow:implement.

The dependency subcommand owns the declared sequencing-dependency recognizer.
It prints one machine-readable outcome so the Phase 1 procedure can decide
before any branch setup begins.

The ignore-precondition subcommand (issue #693) reports whether a path is
covered by a gitignore rule, resolved through `git check-ignore` in-process (the
scripts/reception-record.py shape). It is the precondition of the §1.1 issue-body
cache write: the cache lives in-tree under .prflow/tmp/, so it must already be
ignored before it is written. Shipping it as a subcommand of this already-granted
helper — rather than a new bundled helper — keeps the precondition free of any
new matcher command head or vendored-literal token, so no install.sh-versus-
vendor-fetch skew window opens. It reuses the three-class one-token contract:
IGNORED / PROCEED_EXIT, NOT_IGNORED / BLOCKED_EXIT (a resolved 'not ignored' — the
degraded arm), UNAVAILABLE / UNAVAILABLE_EXIT (git could not answer). Both RESOLVED
arms carry the resolved ABSOLUTE target after the token, so a caller that passed
`--repo-relative` writes to the same path this subcommand checked rather than to a
cwd-relative one that a subdirectory-launched run would resolve elsewhere (#1633).

The branch-state subcommand (issue #576, "Verdict B") classifies the
adopted/working branch against the base and emits a one-token verdict + matching
exit code, mirroring scripts/update-branch-checkpoint.sh's one-token-stdout
contract. It closes the ahead-of-base blind spot the §1.4 freshness guard leaves:
the freshness guard derives only the *behind*-by count, so a branch forked from
an unpushed local-main commit reads "behind-by-0 / up to date" while carrying
unrelated *ahead-only* history that every downstream step then treats as the
run's own (the PR #524 incident). branch-state derives the ahead-of-base count
and refuses to proceed when ahead history cannot be validated as the run's own
prior work. It is READ-ONLY with respect to history: it derives via
`git rev-list` / `git rev-parse` / `git check-ref-format` / `git merge-base` and,
on a shallow repository, a single `git fetch --unshallow` to deepen history — it
never resets, rebases, checks out, commits, merges, pushes, or deletes a branch,
so a stop verdict moves no local branch tip and leaves the working tree
unchanged. (The shallow deepen's refspec +refs/heads/<base>:refs/remotes/origin/
<base> does force-update that remote-tracking ref, which can advance if origin's
base moved, and git's tag auto-following can additionally create refs/tags/*
entries for tags reachable from the newly-deepened history; both are ref changes
outside refs/heads — no local branch and no tracked file is touched.)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

# Running this file as a script already puts scripts/ on sys.path, but a consumer
# that loads it through importlib.util.spec_from_file_location (how
# lib/test/test_python_scripts.py loads this module) does not — so the
# lint_changed sibling import below would fail without this.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


GH = os.environ.get("DEVFLOW_GH") or "gh"
# The §1.3.5 gate reads exactly three exit codes: 0 PROCEED, 2 BLOCKED (named
# dependencies still open), 3 UNAVAILABLE (an unestablished measurement — bad
# input, a failed read, or any unanticipated error). Naming them here makes the
# "exit 2 is reserved for BLOCKED" invariant a single source of truth shared by
# _Parser (usage errors route to UNAVAILABLE, never masquerade as BLOCKED),
# dependencies() (its BLOCKED return), and main()'s top-level fail-closed catch.
PROCEED_EXIT = 0
BLOCKED_EXIT = 2
UNAVAILABLE_EXIT = 3
DEPENDENCY_HEADING = re.compile(r"^##\s+Dependencies\s*$", re.IGNORECASE)
HEADING = re.compile(r"^#{1,6}\s+")
# Group 1 is the heading level (the `#`-run), read by the reserved-leading
# malformed-heading detector below; group 2 is the heading text (whitespace-trimmed
# by the pattern; case-folded by the detector).
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
ISSUE_REF = re.compile(r"#(\d+)")
# Each declaration keyword may be followed by a run of additional numbers joined
# by "and" / "," / ", and" (Oxford) / ";" / "&", so a single declaration can name
# several dependencies: `blocked by #10 and #11`, `depends on #1, #2`,
# `blocked by #10, and #11`. The number run is captured by a uniform
# `re.findall(ISSUE_REF, match.group(0))` over the whole matched span rather than
# per-pattern capture groups (issue #547 Critical + Important #2), so no
# declaration form silently drops all but its first number. Each joiner still
# requires a following `#\d+`, so an unrelated trailing `#N` after a non-joiner
# word (`blocked by #10 — superseded by #999`) is not swept in.
_NUMBER_RUN = r"#\d+(?:\s*(?:,\s*and\s+|,\s*|;\s*|&\s*|and\s+)#\d+)*"
DECLARATIONS = tuple(
    re.compile(rf"\b{keyword}\s+{_NUMBER_RUN}", re.IGNORECASE)
    for keyword in (r"depends on", r"must merge after", r"blocked by", r"follow-up to")
)
# The bare `after #N` form is the weakest declaration: `cleanup after #5 was
# merged` / `renamed after #5` are provenance, not sequencing dependencies
# (issue #547 Important #3). Anchor it to the start of the line/bullet so an
# incidental mid-sentence "after #N" no longer spuriously BLOCKs; a genuine
# free-prose declaration ("After #5 lands, …") opens its line, and the
# `## Dependencies` section scan below still catches an in-section `after #N`
# regardless of position.
AFTER_DECLARATION = re.compile(rf"^[ \t>*\-]*after\s+{_NUMBER_RUN}", re.IGNORECASE)
# OUTBOUND direction words (issue #1197). Every keyword above declares an INBOUND
# relation — the named issue is a prerequisite OF THIS ONE. These declare the exact
# inverse: THIS issue is the prerequisite of the named one, so the named one is not a
# blocker and must not be reported as one. They are matched ONLY inside the
# `## Dependencies` section, where the old scan captured every `#N` with no keyword
# test at all and so read `Blocks #N` as its own opposite. The out-of-section limb
# needs no counterpart and gets none: it recognizes an inbound keyword or nothing, so
# an outbound line there already yields no number — and adding one of these words to
# DECLARATIONS (the inbound vocabulary) would make that limb wrong in exactly the way
# the section limb was.
#
# The vocabulary is deliberately TIGHT, because a false outbound match DROPS a real
# blocker (fail-open) while a miss only leaves today's fail-closed behaviour. Every
# entry is unambiguously outbound in English regardless of surrounding prose, and no
# entry is a prefix of an inbound one — `blocks`/`blocking` cannot match `blocked by`,
# and `required by` cannot match `requires`.
_OUTBOUND_KEYWORDS = (
    r"blocks",
    r"blocking",
    r"unblocks",
    r"unblocking",
    r"prerequisite for",
    r"required by",
    r"must merge before",
)
# An outbound keyword governs its line only when a NUMBER RUN follows it within the
# same clause (issue #1267). The shipped bare-keyword form matched the keyword
# ANYWHERE on the line — including inside the human reason prose of a template-shaped
# `Blocked by #N — <one-line reason it must land first>` line, where "must merge
# before" / "blocks" / "required by" / … routinely appear (the issue template's own
# reason prompt invites them) — so a correctly-drafted INBOUND prerequisite silently
# lost its number (fail-open: the early gate PROCEEDs, the native stamp registers
# nothing). Requiring a following number run keeps every outbound spelling the shipped
# recognizer treated as outbound — all of them place the number adjacent to, or a few
# characters after, the keyword (`Blocks #N`, `Blocks: #N`, `**Blocks:** #N`,
# `Blocks issue #N`, `| Blocks | #N |`) — while a keyword that introduces no number
# run (a reason-prose occurrence) now governs nothing.
#
# The separator is a BOUNDED CHARACTER WINDOW, deliberately NOT whitespace-only: a
# `\s+`-adjacency rule would fail to match `Blocks: #N` / `**Blocks:** #N` /
# `Blocks issue #N` and start RETURNING their numbers — a false BLOCKED, which is
# strictly worse than the fail-open bug because it ships a spurious stop to
# auto-updating consumers (issue #1267's reverse axis, and why the `\s+` prototype was
# rejected). The window bound (`_OUTBOUND_WINDOW`) is small enough that a reason-prose
# keyword far from an unrelated later number does not match, and large enough for the
# widest real separator (` issue ` / `| Blocks | `). Narrowing only ever REMOVES
# matches versus the shipped rule, so it cannot drop a number the old rule returned — it
# can only add numbers back. For the canonical outbound form (number adjacent to the
# keyword) and for the matrix separator shapes, adding numbers back is pure recovery.
#
# The ONE place it is not pure recovery — a disclosed residual, same family as the
# code-span residual pinned in lib/test/run.sh, because the scanner is not
# markdown/semantic-aware — is a genuinely-OUTBOUND free-prose line whose own number
# sits BEYOND the window: `- Blocks the whole downstream release train, see #10`. The
# shipped bare-keyword rule dropped #10 (correct: this issue blocks #10, so #10 is not a
# blocker of it); the narrowed rule no longer matches and returns #10 (a spurious
# blocker, and — via `dependency_section_numbers` — a persistent inverted stamp). This
# residual is accepted, not overlooked: it is the unavoidable cost of a bounded
# character window (any finite bound has it), the issue selected the bounded window with
# its reverse axis operationalized by the two lib/test/run.sh matrices (which this rule
# passes), and the canonical `Blocks #N` outbound form places the number adjacent to the
# keyword and is unaffected. It is pinned as a disclosed residual in lib/test/run.sh; the
# remedy for a real far-separated outbound line is to write the number adjacent to the
# keyword.
#
# Line-level governance is unchanged: when this matches, `_scan_dependencies` still drops
# EVERY number on the line, including one repeated later outside any number run.
_OUTBOUND_WINDOW = 30
OUTBOUND_DECLARATION = re.compile(
    rf"\b(?:{'|'.join(_OUTBOUND_KEYWORDS)})\b.{{0,{_OUTBOUND_WINDOW}}}?{_NUMBER_RUN}",
    re.IGNORECASE,
)
# Dependency-flavoured phrasings the fixed vocabulary does NOT recognize. When a
# `#N` sits next to one of these and no declaration matched the line, emit a
# stderr breadcrumb so a missed declaration is observable (issue #547 Important
# #6) — observability only, never a new BLOCK (the line still yields no number).
SOFT_KEYWORDS = re.compile(
    r"\b(?:requires|require|needs|need|waiting on|gated on|predicated on|"
    r"prerequisite|depends upon|built on top of|built upon|based on)\b",
    re.IGNORECASE,
)


def _scan_dependencies(body: str, *, section_only: bool) -> tuple[list[str], list[str]]:
    """Shared single-definition scanner for declared dependency numbers.

    Returns a two-element ``(found, skipped)`` tuple (issue #1268): ``found`` is
    the declared prerequisite numbers, ``skipped`` is the numbers dropped because
    their ``## Dependencies`` line reads as an OUTBOUND relation. Both lists are
    unique in source order, and ``skipped`` is disjoint from ``found`` — a number
    an inbound line also declared is registered, not reported as skipped. The two
    public wrappers unpack ``found`` and keep
    their historic ``list[str]`` shape; ``dependency_section_scan`` returns the
    pair so its section-only caller can name what direction dropped.

    This is the ONE definition of the declared-dependency vocabulary: the
    ``## Dependencies`` section boundary (every ``#N`` on a line under that heading
    whose direction is not OUTBOUND — see below) and the out-of-section declaration
    keywords.

    **Direction inside the section is governed at the LINE level** (issue #1197). A
    section line matching OUTBOUND_DECLARATION declares that THIS issue is the
    prerequisite of the numbers it names, so that line contributes NO numbers at all —
    not merely the number run adjacent to the outbound word. An outbound keyword matches
    only when a number run FOLLOWS it within a bounded same-clause window (issue #1267):
    a keyword appearing only in the human reason prose of a ``Blocked by #N — <reason>``
    line — with no number run it introduces — governs nothing, so a correctly-drafted
    inbound prerequisite whose reason happens to say "must merge before" / "blocks" / …
    keeps its number. Per-number governance was
    considered and rejected: it lets a mixed line partially contribute (more complex,
    harder to test, and the same ambiguity that produced the inversion this fixes), and
    it cannot handle the live case, whose outbound line repeats the same ``#N`` later in
    its prose, outside any number run. The accepted cost is stated rather than hidden:
    an INBOUND declaration sharing a line with an outbound word is dropped with the
    line, so that one shape is fail-open; the ``dependency_numbers`` breadcrumb below
    makes it observable, and the remedy is to declare each direction on its own line.

    A line carrying NEITHER an inbound nor an outbound word — a bare ``- #N`` bullet,
    ``Part of #N``, any unrecognised phrasing — keeps its pre-#1197 behaviour and is
    still returned, because the section heading itself is the author's inbound
    declaration and the template's sanctioned form lives under it. That is a decided
    disposition, not a fall-through: the one thing this function must never do is
    silently INVERT a direction it does not recognise.

    Both public entry points route through here — `dependency_section_numbers`
    with ``section_only=True`` (the section limb alone) and `dependency_numbers`
    with ``section_only=False`` (both limbs, plus the SOFT_KEYWORDS observability
    breadcrumb) — so the section vocabulary has a single source and cannot drift
    between the two.

    Numbers are returned unique in source order. Both stderr-writing paths — the
    outbound-skip breadcrumb and the out-of-section SOFT_KEYWORDS sweep — are gated
    on ``not section_only``, so when ``section_only`` is True neither is reached and
    a caller (the apply-issue-dependencies helper) that imports the section-only
    entry point never leaks a ``preflight.py:`` breadcrumb into its own
    caller-facing output.
    """
    found: list[str] = []
    skipped: list[str] = []

    def add(number: str) -> None:
        if number not in found:
            found.append(number)

    def add_skipped(number: str) -> None:
        if number not in skipped:
            skipped.append(number)

    in_dependencies = False
    for line in body.splitlines():
        if DEPENDENCY_HEADING.match(line):
            in_dependencies = True
            continue
        if in_dependencies and HEADING.match(line):
            in_dependencies = False
        if in_dependencies:
            numbers = ISSUE_REF.findall(line)
            if numbers and OUTBOUND_DECLARATION.search(line):
                # Line-level: the outbound word governs every number on the line.
                # Record every dropped number as `skipped` on BOTH entry points
                # (issue #1268) so a section-only caller can name what it lost;
                # the stderr breadcrumb still rides the stderr-carrying entry point
                # only, because `dependency_section_numbers` has a no-stderr
                # contract its caller (apply-issue-dependencies.py) depends on.
                for number in numbers:
                    add_skipped(number)
                if not section_only:
                    for number in dict.fromkeys(numbers):
                        print(
                            f"preflight.py: skipped #{number} under `## Dependencies` — "
                            f"the line declares an OUTBOUND relation (this issue is the "
                            f"prerequisite), not a blocker of this one; if #{number} must "
                            f"land first, restate it on its own line as "
                            f"`blocked by #{number}`",
                            file=sys.stderr,
                        )
                continue
            for number in numbers:
                add(number)
            continue
        if section_only:
            continue
        # Accumulate every declaration match on the line (no early `break`): a
        # line can carry more than one declaration — `depends on #1, blocked by
        # #2` names both (issue #547 Important #2).
        spans = [m.group(0) for pattern in DECLARATIONS for m in pattern.finditer(line)]
        after_match = AFTER_DECLARATION.match(line)
        if after_match:
            spans.append(after_match.group(0))
        for span in spans:
            for number in ISSUE_REF.findall(span):
                add(number)
        if not spans and SOFT_KEYWORDS.search(line):
            for number in dict.fromkeys(ISSUE_REF.findall(line)):
                print(
                    f"preflight.py: unrecognized dependency-flavoured reference to "
                    f"#{number} — not a declared sequencing dependency; if it is one, "
                    f"restate it as `depends on #{number}` / `blocked by #{number}` "
                    f"or list it under a `## Dependencies` section",
                    file=sys.stderr,
                )
    # A number governed OUTBOUND on one line but declared inbound on another lands
    # in both lists (each is deduped only against itself). Such a number IS
    # registered as a prerequisite, so reporting it as skipped-and-unregistered
    # would be a false breadcrumb (issue #1268): keep `skipped` disjoint from
    # `found`, so a caller only ever names numbers no inbound line rescued.
    skipped = [number for number in skipped if number not in found]
    return found, skipped


def dependency_section_numbers(body: str) -> list[str]:
    """Return unique numbers declared INSIDE a ``## Dependencies`` section only.

    Section-scoped extraction (issue #1011): the mutating GitHub-native
    dependency stamp consumes only the section the issue template reserves for
    cross-issue ordering — deliberately narrower than `dependency_numbers`, which
    also honours out-of-section declaration keywords because a false positive in
    the reversible implement gate costs only a human override, whereas a
    registered dependency is a persistent relationship. Emits no stderr of its own.

    Direction is honoured here exactly as `_scan_dependencies` describes it (issue
    #1197), and this is the entry point where it matters most: a persistent
    ``blocked_by`` write registering the INVERSE of what the author declared is not a
    stop a human can override away. The no-stderr contract survives that arm — the
    outbound-skip breadcrumb rides `dependency_numbers` only.

    Returns `found` only, unchanged (issue #1268); a section-only caller that
    also needs the outbound-skipped numbers uses `dependency_section_scan`.
    """
    return _scan_dependencies(body, section_only=True)[0]


def dependency_section_scan(body: str) -> tuple[list[str], list[str]]:
    """Section-only scan returning ``(found, skipped)`` (issue #1268).

    Same scope and direction handling as `dependency_section_numbers` — every
    ``#N`` on a ``## Dependencies`` line whose direction is not OUTBOUND — but it
    also returns the numbers dropped for outbound direction, so the section-only
    caller (`apply-issue-dependencies.py`) can name what it skipped instead of
    dropping it silently or misdescribing the body. Emits no stderr of its own;
    the no-stderr contract is unchanged, and the skip breadcrumb is the calling
    helper's responsibility under its own prefix.
    """
    return _scan_dependencies(body, section_only=True)


def dependency_numbers(body: str) -> list[str]:
    """Return unique declared dependency numbers in source order.

    In-section results are derived from the same single-definition scanner that
    backs `dependency_section_numbers`, so the section vocabulary has one source.
    Returns `found` only, unchanged (issue #1268).
    """
    return _scan_dependencies(body, section_only=False)[0]


def malformed_reserved_dependency_heading(body: str) -> str | None:
    """Return the offending `#`-marker of a reserved-leading dependency heading
    spelled at a Markdown level other than two, else None (issue #1695).

    The issue template renders the optional `## Dependencies` section FIRST, above
    `## Problem Statement`. A heading whose normalized text is `Dependencies` in
    that reserved leading position must be exactly level two; a different level
    (`# Dependencies`, `### Dependencies`) is an authoring mistake the level-2-only
    `DEPENDENCY_HEADING` recognizer would otherwise read as an EMPTY prerequisite
    set — "unknown, not zero". A canonical level-two heading returns None (the
    reserved section the existing recognizer already handles).

    Positional and bounded, NOT a general Markdown parser: only the reserved
    leading region — the run of content before the first level-≤2 section heading
    that is not itself a `Dependencies` heading — is inspected, so a later nested
    `Dependencies` heading (e.g. `### Dependencies` under `## Problem Statement`)
    is never promoted into the reserved section. Uses the same case/whitespace
    normalization as `DEPENDENCY_HEADING` (case-insensitive, whitespace-stripped).
    """
    for line in body.splitlines():
        match = _ATX_HEADING.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if match.group(2).strip().casefold() == "dependencies":
            return None if level == 2 else match.group(1)
        if level <= 2:
            return None
    return None


def _gh_issue_view(number: object, field: str) -> str:
    """Run `gh issue view <number> --json <field> -q .<field>` and return stdout.

    encoding="utf-8" with errors="replace" so non-ASCII issue bodies decode and a
    body carrying invalid UTF-8 bytes never raises UnicodeDecodeError (a ValueError
    subclass none of the callers' except-clauses catch). Left unreplaced, that error
    would propagate to main()'s catch-all handler and be converted to a spurious
    UNAVAILABLE/exit 3 — a contained WRONG verdict that would REPLACE the true
    BLOCKED/PROCEED result, not a crash or exit-1 escape (issue #547 review).
    The caller owns the error policy (issue_body raises, issue_state swallows).
    """
    result = subprocess.run(
        [GH, "issue", "view", str(number), "--json", field, "-q", f".{field}"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def issue_body(issue: int) -> str:
    try:
        return _gh_issue_view(issue, "body")
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise RuntimeError(f"could not read issue body: {detail}") from exc


def issue_state(number: str) -> str | None:
    try:
        state = _gh_issue_view(number, "state").strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return state if state in {"OPEN", "CLOSED", "MERGED"} else None


def dependencies(args: argparse.Namespace) -> int:
    # `is not None`, not truthiness: an explicit empty `--body-file ""` must read
    # the (empty) file path and fail closed on that path's own read error, not fall
    # through to the issue branch and call `issue_body(None)` — which would run
    # `gh issue view None` and misreport the failure as an issue-fetch problem
    # (PR #572 review). Both arms still fail closed to UNAVAILABLE; this keeps the
    # diagnostic pointed at the surface the caller actually named.
    if args.body_file is not None:
        body_file = args.body_file
        if getattr(args, "repo_relative", False) and body_file:
            # Anchoring mode (issue #1633): resolve the repo-relative --body-file so
            # the §1.3.5 fence does not compute the root. An unresolvable root fails
            # closed to UNAVAILABLE, matching this subcommand's contract.
            resolved = _anchor_repo_relative(body_file)
            if resolved is None:
                print(
                    f"preflight.py: could not resolve the repository root to anchor "
                    f"{body_file!r}",
                    file=sys.stderr,
                )
                print("UNAVAILABLE resolve", flush=True)
                return UNAVAILABLE_EXIT
            body_file = resolved
        try:
            # errors="replace": a body file with invalid UTF-8 bytes decodes to
            # replacement chars and is still scanned for real #N declarations,
            # rather than raising UnicodeDecodeError (a ValueError the `except
            # OSError` below does not catch) — which main()'s catch-all would then
            # convert to a spurious UNAVAILABLE/exit 3, REPLACING the true
            # BLOCKED/PROCEED verdict (a contained wrong verdict, issue #547 review).
            body = Path(body_file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"preflight.py: could not read dependency body: {exc}", file=sys.stderr)
            print("UNAVAILABLE body", flush=True)
            return UNAVAILABLE_EXIT
    else:
        try:
            body = issue_body(args.issue)
        except RuntimeError as exc:
            print(f"preflight.py: {exc}", file=sys.stderr)
            print("UNAVAILABLE issue", flush=True)
            return UNAVAILABLE_EXIT

    malformed = malformed_reserved_dependency_heading(body)
    if malformed is not None:
        # Fail closed BEFORE resolving any number: a malformed reserved heading is
        # unknown, not an empty prerequisite set, so it must not read as PROCEED.
        print(
            f"preflight.py: the reserved leading dependency section is spelled "
            f"`{malformed} Dependencies`, not the canonical `## Dependencies` "
            f"(Markdown level two); its prerequisites are unread — restate it as "
            f"`## Dependencies` and re-run",
            file=sys.stderr,
        )
        print("UNAVAILABLE malformed-dependency-heading", flush=True)
        return UNAVAILABLE_EXIT

    numbers = dependency_numbers(body)
    if not numbers:
        print("PROCEED")
        return PROCEED_EXIT

    open_numbers: list[str] = []
    for number in numbers:
        state = issue_state(number)
        if state is None:
            print(f"preflight.py: could not resolve declared dependency #{number}", file=sys.stderr)
            print(f"UNAVAILABLE {number}")
            return UNAVAILABLE_EXIT
        if state == "OPEN":
            open_numbers.append(number)

    if open_numbers:
        print(f"BLOCKED {','.join(open_numbers)}")
        return BLOCKED_EXIT

    print(f"PROCEED {','.join(numbers)}")
    return PROCEED_EXIT


# ── branch-state (Verdict B, issue #576) ─────────────────────────────────────
# Exit codes reuse the dependency contract's three classes so the §1.4 caller
# reads ONE exit vocabulary across both subcommands:
#   FRESH / VALIDATED_RESUME      → PROCEED_EXIT (0)   proceed to §1.4.1/§1.5
#   AMBIGUOUS / DECISION_BLOCKED  → BLOCKED_EXIT (2)   stop before push/checkpoint
#   UNAVAILABLE <reason>          → UNAVAILABLE_EXIT (3) unestablished measurement
# The two-payload verdicts (AMBIGUOUS/DECISION_BLOCKED) additionally print a
# `<verdict> <payload-file>` where the payload file captures the gathered +
# derived state and the classification reason for the human deciding the stop.
#
# Two provenance sources may vouch for ahead-of-base history (issue #780): the
# workpad (`provenance_established`), and the OPEN-PR LINKAGE — an open PR in THIS
# repository whose head branch is the working branch, which is not
# cross-repository, and which is tied to this issue either by closing
# it or by having been selected by the §1.4 pre-check's head-branch query
# (`open_pr_branch` / `open_pr_closes_issue` / `open_pr_cross_repository` /
# `open_pr_selected_by`). Operative rules, enforced below: every conjunct of the PR
# source fails CLOSED; a PARTIAL gather of those four operands is refused rather
# than read as a refutation; the workpad takes precedence when both vouch; and on a
# PR-vouched-only path the untrusted workpad is neutralized rather than consulted.
# The threat model this admission rests on — who can write each source, and the
# population overlap that bounds what it defends against — has its CANONICAL
# statement in the implement skill's "Two provenance sources for ahead history"
# section. This header states only the operative rules above; the skill body and the
# system overview carry coupled summaries. Edit those three together, and do not add
# a fourth copy of the rationale here — a security rationale copied further drifts.

# The workpad front-matter Branch line: `**Branch:** `<name>`` (a real branch)
# or `**Branch:** _(creating…)_` (the 1.3 placeholder, no backticks). Match the
# LABEL to enumerate every Branch line (duplicate detection), then extract the
# first fully-closed backtick span as the recorded name. A line with no closed
# backtick span (the placeholder, or a truncated body that lost its closing
# backtick) yields no recorded name — treated as absent, never as a partial name.
_BRANCH_LABEL = re.compile(r"^\s*\*\*Branch:\*\*", re.MULTILINE)
_BRANCH_BACKTICK = re.compile(r"`([^`]+)`")


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand on the current checkout, capturing text output.

    encoding/errors mirror _gh_issue_view so an exotic ref name or commit message
    never raises UnicodeDecodeError into main()'s catch-all (a spurious UNAVAILABLE
    that would REPLACE a real verdict). check=False: every caller inspects
    returncode explicitly — a non-zero git exit is data here (a ref that does not
    resolve, a non-ancestor), not an error to raise.
    """
    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def _ref_resolves(ref: str) -> bool:
    """True when `ref` names a resolvable commit."""
    return _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).returncode == 0


def parse_recorded_branch(body: str) -> tuple[str | None, bool]:
    """Parse the workpad Branch line. Returns (recorded_name_or_None, duplicate).

    A missing/placeholder/truncated Branch line yields (None, False) — absent.
    More than one Branch line yields (None, True) — the body is ambiguous and no
    single recorded name can be trusted (a marker-forged or corrupted workpad).
    """
    lines = [line for line in body.splitlines() if _BRANCH_LABEL.match(line)]
    if not lines:
        return (None, False)
    if len(lines) > 1:
        return (None, True)
    match = _BRANCH_BACKTICK.search(lines[0])
    if not match:
        return (None, False)  # placeholder or truncated — no closed backtick span
    name = match.group(1).strip()
    # A backtick span holding only a placeholder-shaped value is still "absent".
    if not name or name.startswith("_("):
        return (None, False)
    return (name, False)


def _is_shallow() -> bool | None:
    """Shallowness probe. True/False, or None when it could not be established.

    `git rev-parse --is-shallow-repository` is the only signal, and reading it as
    `stdout == "true"` alone fails OPEN: on git < 2.15 the option is unrecognized
    and on a subprocess failure stdout is empty, so a genuinely shallow repository
    would read as not-shallow and its unreliable pre-deepen count would be adopted
    — the exact spurious-PROCEED direction this subcommand exists to close. So a
    non-zero returncode, or any stdout outside {true,false}, is UNESTABLISHED
    (None) and the caller fails closed to UNAVAILABLE, never to not-shallow.
    """
    result = _run_git(["rev-parse", "--is-shallow-repository"])
    value = result.stdout.strip()
    if result.returncode != 0 or value not in ("true", "false"):
        return None
    return value == "true"


def _derive_ahead(base: str) -> tuple[int | None, str]:
    """Ahead-of-base count for HEAD, with shallow unshallow-once-then-rederive.

    Returns (ahead, "") on success, or (None, reason) on an unestablished
    measurement: reason "base" when origin/<base> does not resolve (the caller's
    fetch never landed it), "count" when rev-list cannot produce an integer,
    "shallow-probe" when the shallowness of the repository could not be
    established, or "shallow-undeepened" when the repository is shallow and could
    not be deepened.

    Shallow-miscount direction (do NOT copy update-branch-checkpoint.sh's wording
    here — it describes the OPPOSITE computation). This count is
    `rev-list --count refs/remotes/origin/<base>..HEAD`, which excludes everything
    reachable from the base. A shallow view truncates the base's history, so
    FEWER commits are reachable from it, so FEWER are excluded: the shallow count
    can only OVERcount ahead-of-base, never undercount it to 0. (The behind-by
    count in update-branch-checkpoint.sh is `HEAD..base`, whose operands are
    reversed — that one undercounts, which is why its wording does not transfer.)
    So on a shallow repository deepen the base ref exactly once and re-derive —
    the post-unshallow count is authoritative.

    A shallow view that CANNOT be deepened is fail-closed to UNAVAILABLE rather
    than trusted. The reason is that the count is simply unreliable, NOT that it
    could read 0: an overcount lands on the ahead>0 classification arms, which is
    the fail-closed direction, but it selects those arms on a fabricated count and
    can turn a genuinely-fresh branch into a spurious stop, and nothing in this
    function's contract bounds the error. So it joins the base/count arms as an
    unestablished measurement, not an authoritative shallow count.
    """
    base_ref = f"refs/remotes/origin/{base}"
    if not _ref_resolves(base_ref):
        return (None, "base")

    def count() -> int | None:
        result = _run_git(["rev-list", "--count", f"{base_ref}..HEAD"])
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit():
            return None
        return int(value)

    ahead = count()
    shallow = _is_shallow()
    if shallow is None:
        return (None, "shallow-probe")
    if shallow:
        # Deepen the base ref specifically (fetch-depth cloud checkouts download
        # only the feature ref's history), then re-derive.
        _run_git(["fetch", "--unshallow", "origin", f"+refs/heads/{base}:{base_ref}"])
        redeepened = _is_shallow()
        if redeepened is None:
            return (None, "shallow-probe")
        if redeepened:
            # The deepen did not take (offline/auth/remote failure). Trusting the
            # still-shallow count here would fail OPEN on exactly the ahead-only
            # case this feature guards, so treat it as unestablished.
            return (None, "shallow-undeepened")
        # Deepen took: the post-deepen count is authoritative — adopt it
        # UNCONDITIONALLY. Reverting to the pre-deepen `ahead` when the
        # re-derivation fails would fall back to the value the docstring declares
        # unreliable (a possible spurious 0 → FRESH); instead let a failed
        # re-count fall through to the (None → "count") fail-closed arm below.
        ahead = count()
    if ahead is None:
        return (None, "count")
    return (ahead, "")


def _published_tip_reachable(current_branch: str) -> bool:
    """True when HEAD is reachable from the branch's published tip.

    origin/<current_branch> reaching HEAD means the branch's ahead commits are
    published under this branch's own name — the strong "this is our own prior
    work" signal a validated resume needs. A branch not yet pushed (no such
    remote ref) is not reachable, so this stays False and the caller cannot reach
    VALIDATED_RESUME on it.
    """
    tip = f"refs/remotes/origin/{current_branch}"
    if not _ref_resolves(tip):
        return False
    return _run_git(["merge-base", "--is-ancestor", "HEAD", tip]).returncode == 0


def _branch_exists(name: str) -> bool | None:
    """Existence probe for a recorded branch name. True/False, or None on error.

    None distinguishes a PROBE FAILURE (git cannot evaluate the ref because the
    recorded NAME is malformed — a space, empty, or otherwise ref-invalid value a
    corrupted/forged workpad can carry) from a CLEAN-EMPTY result (a well-formed
    name that simply is not a ref → False). The caller routes a probe failure to
    UNAVAILABLE and a clean-empty divergent name to DECISION_BLOCKED, so the two
    must never collapse. `git check-ref-format` owns the name-validity contract
    (a malformed name → non-zero) and `git rev-parse` owns existence — because
    both `show-ref --verify` (with --quiet) and `rev-parse --verify` report a
    malformed name and a well-formed-but-absent name with the SAME exit code, so
    neither alone can make this distinction.
    """
    local, remote = f"refs/heads/{name}", f"refs/remotes/origin/{name}"
    for ref in (local, remote):
        if _run_git(["check-ref-format", ref]).returncode != 0:
            return None  # malformed name — existence is unestablishable, not "absent"
    for ref in (local, remote):
        if _ref_resolves(ref):
            return True
    return False


def _payload_dir() -> str | None:
    """The repo's `.prflow/tmp/` when resolvable/writable, else None (system temp).

    A cloud agent's Read tool is scoped to the workspace, so a stop-verdict payload
    under `.prflow/tmp/` stays readable (and consistent with where the caller
    writes the state file), whereas a system-`/tmp` path may not be. Falls back to
    None (NamedTemporaryFile's default temp dir) when the git root is unresolvable
    or the directory cannot be created — the payload still writes, just elsewhere.
    """
    def _fallback(cause: str) -> None:
        # One breadcrumb shape, two distinct cause clauses (issue #915): the payload
        # still writes, but to the system temp dir a cloud agent's Read tool cannot reach.
        print(
            f"preflight.py: {cause}; the stop-verdict payload will land in the system "
            "temp dir, OUTSIDE the workspace a cloud agent's Read tool can reach",
            file=sys.stderr,
        )
        return None

    top = _run_git(["rev-parse", "--show-toplevel"])
    if top.returncode == 0 and top.stdout.strip():
        candidate = os.path.join(top.stdout.strip(), ".prflow", "tmp")
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError as exc:
            return _fallback(f"could not create the repo-relative payload dir {candidate} ({exc})")
    return _fallback("could not resolve the git root for the payload dir")


def _write_payload(verdict: str, reason: str, state: dict, derived: dict) -> str:
    """Write the stop-verdict payload file and return its path.

    Captures the gathered state, the internally-derived values, and the
    classification reason so the human deciding the AMBIGUOUS/DECISION_BLOCKED
    stop has the full picture. delete=False: the file outlives this process for
    the caller/human to read; the caller owns its lifetime.
    """
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="devflow-branch-state-", suffix=".json",
        dir=_payload_dir(), delete=False,
    )
    with handle:
        json.dump({"verdict": verdict, "reason": reason, "state": state, "derived": derived}, handle, indent=2)
    return handle.name


def _classify_branch_state(state: dict) -> tuple[str, str, dict]:
    """Return (verdict, reason, derived). The branch-state decision orchestrator.

    Reads the caller-gathered `state` and derives the git-side facts it needs
    lazily (ahead-of-base count, published-tip reachability, recorded-branch
    existence) — each git helper is invoked only on the paths that consume it, so
    this is not a pure function of `state`; it touches the current checkout via
    git. Verdict vocabulary: FRESH, VALIDATED_RESUME, AMBIGUOUS, DECISION_BLOCKED,
    UNAVAILABLE. The reason is a stable slug (empty for the proceed verdicts).
    """
    base = state["base"]
    current_branch = state["current_branch"]
    ahead, ahead_err = _derive_ahead(base)
    derived: dict = {"ahead": ahead}
    if ahead is None:
        return ("UNAVAILABLE", ahead_err, derived)
    if ahead == 0:
        # No commits ahead of base: a fresh branch, or an adopted branch
        # fast-forwarded to base. Nothing unrelated to validate — proceed. This is
        # also the warm-start case (a gate-pre-created workpad, no work committed).
        return ("FRESH", "", derived)

    # ahead > 0: the branch carries commits not on the base. They are legitimate
    # only if they are this run's own prior work; otherwise §1.5 would publish
    # foreign history into the PR (the PR #524 incident). Validate before proceed.
    # Open-PR linkage — the second provenance source (issue #780), which is what
    # lets the landed-resume arm be classified at all: that arm's workpad
    # provenance is unestablished across two large populations (a cloud run whose
    # HANDOFF record is `unknown`, and a local resumed run that did not create its
    # own workpad), so a workpad-only gate would convert ordinarily-resumable runs
    # into terminal stops. Every conjunct fails CLOSED, and a caller that gathered
    # the PR operands only partially is refused upstream in `branch_state` rather
    # than silently reaching here — so an absent field is never read as an answer.
    #
    # ISSUE-LINKAGE IS A DISJUNCTION, and that is not a weakening — it mirrors the
    # §1.4 resume pre-check's own selection contract, which admits a PR found by the
    # HEAD-BRANCH query as "a resume target by construction" and applies the
    # closes-issue predicate only to a PR found *solely* by the body-reference query.
    # Requiring `open_pr_closes_issue` unconditionally would therefore hand a
    # terminal `DECISION_BLOCKED` to a run the pre-check had just blessed and landed
    # — a PR whose body reads "Part of #N" rather than "Closes #N" — which is the
    # very outcome admitting this source exists to remove. So the head-query
    # selection stands in for the linkage exactly where the pre-check says it does.
    # It is not forgeable by the wider issue-commenter population either: the
    # conjuncts below still require a same-repo PR whose head is the branch actually
    # in the tree.
    # The `is True` / `is False` identity reads below are equivalent to `!= False` /
    # `!= True` ONLY because of three upstream guards: the boolean type-guard (any
    # PRESENT non-bool operand is refused), the partial-gather refusal (an ABSENT one
    # is refused before this function runs), and the `isinstance(pr_branch, str)`
    # conjunct. Between them, `None` — the sole value the two spellings disagree on —
    # can never reach here. Relax any of the three and these identity reads stop being
    # equivalent and start needing their own arms; the tests below cover the guards,
    # not the identity spelling.
    pr_branch = state.get("open_pr_branch")
    wp_vouched = bool(state.get("provenance_established", False))
    pr_issue_linked = (
        state.get("open_pr_closes_issue") is True
        or state.get("open_pr_selected_by") == "head"
    )
    pr_vouched = (
        isinstance(pr_branch, str)
        and pr_branch == current_branch
        and pr_issue_linked
        and state.get("open_pr_cross_repository") is False
    )
    # `pr_linkage_vouches` records whether the PR source *could* vouch;
    # `provenance_source` records which source the operands below actually came
    # from. They differ when both vouch, so a human reading a stop payload is never
    # shown a PR-derived provenance that the classification did not in fact use.
    derived["pr_linkage_vouches"] = pr_vouched
    if not wp_vouched and not pr_vouched:
        # Neither source vouches. The workpad's recorded branch / verdict are then
        # the only remaining signals, and unestablished provenance means they may
        # be marker-forged — so they cannot be trusted to validate anything.
        derived["provenance_source"] = None
        return ("DECISION_BLOCKED", "unverified-provenance", derived)

    # PRECEDENCE — deliberate, and asymmetric: the workpad wins when both vouch.
    # The two sources are not interchangeable. The workpad carries a run's own
    # recorded branch and proceed verdict, which resolve a strictly finer set of
    # verdicts (`matching-without-verdict`, `divergent-*`) than the PR can; the PR
    # source collapses both onto one fact and therefore screens only through
    # published-tip reachability. Preferring the workpad where it is trusted keeps
    # an established-provenance run classifying exactly as it did before issue #780
    # — the PR source only ever *adds* a path where there was previously a terminal
    # stop, and never relaxes one that already had a finer answer.
    if wp_vouched:
        derived["provenance_source"] = "workpad"
        recorded, duplicate = parse_recorded_branch(state.get("workpad_body", ""))
        has_verdict = bool(state.get("has_proceed_verdict", False))
    else:
        # PR-vouched only. The workpad is untrusted here, so neither its Branch line
        # nor a workpad-derived proceed verdict may vouch for anything — consulting
        # them would let a forged comment steer the classification the PR was
        # admitted to decide. The PR supplies both operands instead. Reusing the
        # shared arms below rather than returning early is deliberate: it keeps ONE
        # published-tip-reachability call site and ONE reason slug for the
        # diverged-tip stop, so that screen cannot drift between the two sources.
        # Because `pr_vouched` already required `pr_branch == current_branch`, this
        # path lands on the matching-branch arm by construction.
        derived["provenance_source"] = "open-pr"
        recorded, duplicate = pr_branch, False
        has_verdict = True
    derived["recorded_branch"] = recorded
    if duplicate:
        return ("AMBIGUOUS", "duplicate-branch-line", derived)

    # Published-tip reachability is only consulted on the absent and matching
    # arms below; the divergent arm never reads it, so it is derived inside those
    # arms rather than eagerly (avoids a wasted rev-parse + merge-base pair on the
    # divergent path).
    if recorded is None:
        # Absent / placeholder / truncated Branch line. A prior proceed verdict
        # PLUS a published tip still vouches for the ahead history even without a
        # recorded name; anything less is a human decision.
        tip_reachable = _published_tip_reachable(current_branch)
        derived["published_tip_reachable"] = tip_reachable
        if has_verdict and tip_reachable:
            return ("VALIDATED_RESUME", "", derived)
        return ("AMBIGUOUS", "no-recorded-branch", derived)

    if recorded == current_branch:
        if has_verdict:
            tip_reachable = _published_tip_reachable(current_branch)
            derived["published_tip_reachable"] = tip_reachable
            if tip_reachable:
                return ("VALIDATED_RESUME", "", derived)
            return ("AMBIGUOUS", "matching-verdict-tip-unreachable", derived)
        return ("AMBIGUOUS", "matching-without-verdict", derived)

    # Divergent: the recorded branch is not the working branch.
    exists = _branch_exists(recorded)
    derived["recorded_branch_exists"] = exists
    if exists is None:
        return ("UNAVAILABLE", "existence-probe", derived)
    if not exists:
        # The workpad names a branch that does not exist — a corrupted or forged
        # record; refuse rather than adopt ahead history against a phantom.
        return ("DECISION_BLOCKED", "divergent-nonexistent", derived)
    if has_verdict:
        return ("AMBIGUOUS", "divergent-existing-with-verdict", derived)
    return ("DECISION_BLOCKED", "divergent-without-verdict", derived)


def _unavailable_state(message: str) -> int:
    """Emit a state-input UNAVAILABLE: a specific stderr cause + the fixed token.

    Every branch-state input-validation failure fails closed to the SAME contract
    — `UNAVAILABLE state` on stdout, `UNAVAILABLE_EXIT` — with only the stderr
    cause varying; routing them through one helper keeps that contract single-sited
    (the classify-path `UNAVAILABLE <reason>` emit stays separate: its token varies).
    """
    print(f"preflight.py: {message}", file=sys.stderr)
    print("UNAVAILABLE state", flush=True)
    return UNAVAILABLE_EXIT


def branch_state(args: argparse.Namespace) -> int:
    # `is not None`: an explicit `--state-file ""` reads the (empty) path and fails
    # closed on that read, never falls through to a phantom default (mirrors the
    # dependency subcommand's body-file discipline).
    if args.state_file is None:
        return _unavailable_state("branch-state requires --state-file")
    try:
        raw = Path(args.state_file).read_text(encoding="utf-8")
    except OSError as exc:
        return _unavailable_state(f"could not read branch-state file: {exc}")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _unavailable_state(f"branch-state file is not valid JSON: {exc}")
    if not isinstance(state, dict):
        return _unavailable_state("branch-state file must be a JSON object")
    base = state.get("base")
    current_branch = state.get("current_branch")
    if not isinstance(base, str) or not base or not isinstance(current_branch, str) or not current_branch:
        return _unavailable_state("branch-state requires non-empty string 'base' and 'current_branch'")
    # The two flags below GATE the ahead-history validation, so they get the same
    # type discipline as `base`/`current_branch` above — never raw truthiness.
    # Python truthiness on a JSON *string* fails OPEN on exactly the shape the
    # producer is most likely to emit: this state file is hand-composed by an LLM
    # agent (phase-1-setup.md §1.4.0.5) writing prose-to-JSON, and a quoted
    # `"false"` is truthy — `not "false"` is False, `bool("false")` is True. That
    # would skip the `unverified-provenance` DECISION_BLOCKED entirely and let a
    # forged workpad vouch for foreign ahead history (the PR #524 publish), or
    # manufacture a proceed verdict the run never earned. Both are silent: no
    # exception, no exit-code deviation, just the unsafe verdict. So a present
    # non-bool is refused here rather than coerced downstream.
    # `open_pr_closes_issue` / `open_pr_cross_repository` join the list for a
    # DIFFERENT reason than the two original flags, and the difference matters: the
    # originals are read through truthiness, so a quoted `"false"` genuinely fails
    # OPEN there. The two #780 flags are read through IDENTITY (`is True` / `is
    # False`), so a quoted `"false"` already fails closed on its own. They are
    # refused here anyway because failing closed with a *misleading*
    # `unverified-provenance` cause hides an encoding error behind a verdict that
    # reads as a real refutation — the caller is told the PR did not vouch when in
    # fact the operand was never legible. The refusal names the encoding error
    # instead.
    for _flag in (
        "provenance_established",
        "has_proceed_verdict",
        "open_pr_closes_issue",
        "open_pr_cross_repository",
    ):
        if _flag in state and not isinstance(state[_flag], bool):
            return _unavailable_state(
                f"branch-state '{_flag}' must be a JSON boolean (true/false), not "
                f"{type(state[_flag]).__name__} — a quoted \"false\" is truthy, so on a "
                f"truthiness-read flag it would VOUCH for history the caller never "
                f"vouched for, and on an identity-read flag it reads as a refutation "
                f"the caller never established"
            )
    # `open_pr_branch` / `open_pr_selected_by` are string operands, so they take a
    # string refusal rather than the boolean one above. Without it a malformed value
    # is the one gate operand whose failure is SILENT — it fails closed through the
    # `isinstance` conjunct, but into a generic `unverified-provenance` that names no
    # cause, so the caller reads a real refutation where an encoding error occurred.
    if "open_pr_branch" in state and not isinstance(state["open_pr_branch"], str):
        return _unavailable_state(
            "branch-state 'open_pr_branch' must be a JSON string (the PR's headRefName), not "
            f"{type(state['open_pr_branch']).__name__}"
        )
    if "open_pr_selected_by" in state and state["open_pr_selected_by"] not in ("head", "body"):
        return _unavailable_state(
            "branch-state 'open_pr_selected_by' must be the string 'head' or 'body' (which §1.4 "
            f"resume-pre-check query selected the PR), not {state['open_pr_selected_by']!r}"
        )
    # PARTIAL-GATHER REFUSAL — the mechanism behind §1.4.0.5's "gather all four or
    # none" rule, which is otherwise an unobservable prose instruction. Without it,
    # a caller that gathered a PR but omitted one field is INDISTINGUISHABLE from a
    # caller whose PR genuinely did not vouch: both emit `unverified-provenance`, so
    # a stop payload asserts "the linkage was evaluated and refuted" about an operand
    # that was never written (the repo's unknown-is-not-zero rule). Refusing names
    # the omission instead, and it is what makes the fail-closed-on-ungathered
    # behavior a decided contract rather than an accident of `dict.get`.
    _pr_keys = (
        "open_pr_branch",
        "open_pr_closes_issue",
        "open_pr_cross_repository",
        "open_pr_selected_by",
    )
    _present = [k for k in _pr_keys if k in state]
    if _present and len(_present) != len(_pr_keys):
        _missing = ", ".join(k for k in _pr_keys if k not in state)
        return _unavailable_state(
            "branch-state open-PR provenance operands must be gathered together or omitted "
            f"together; present: {', '.join(_present)}; missing: {_missing}"
        )

    verdict, reason, derived = _classify_branch_state(state)
    if verdict == "UNAVAILABLE":
        print(f"preflight.py: branch-state could not establish '{reason}' — no verdict", file=sys.stderr)
        print(f"UNAVAILABLE {reason}", flush=True)
        return UNAVAILABLE_EXIT
    if verdict in ("FRESH", "VALIDATED_RESUME"):
        print(verdict, flush=True)
        return PROCEED_EXIT
    # AMBIGUOUS / DECISION_BLOCKED — a stop with a payload for the human. The
    # classification is already established at this point, so a payload-write
    # failure must NOT reach main()'s catch-all: that would downgrade a computed
    # stop (exit 2, with its reason slug) to a bare UNAVAILABLE (exit 3), losing
    # the classification the caller acts on. Both are stops, so nothing fails
    # open — but the specific verdict survives, with the lost payload named.
    try:
        payload = _write_payload(verdict, reason, state, derived)
    except OSError as exc:
        print(
            f"preflight.py: branch-state {verdict} ({reason}); payload could not be written: {exc}",
            file=sys.stderr,
        )
        print(f"{verdict} {reason}", flush=True)
        return BLOCKED_EXIT
    print(f"preflight.py: branch-state {verdict} ({reason}); state written to {payload}", file=sys.stderr)
    print(f"{verdict} {payload}", flush=True)
    return BLOCKED_EXIT


# ── ignore-precondition (issue #693) ─────────────────────────────────────────
# A precondition of the §1.1 issue-body cache write: the cache lives IN-TREE under
# .prflow/tmp/, so an ignore rule covering it must already be in effect before it
# is written (the run never creates one — a new dotfile would itself be an
# untracked file the run's `git add -A` calls would stage). Resolving ignore state
# through git itself — the scripts/reception-record.py `_check_ignored` shape —
# means the precondition introduces NO new matcher command head and NO new
# vendored-literal token: the `git check-ignore` call is an in-process subprocess
# of the already-granted preflight.py, not a command the phase fence invokes. The
# one-token stdout reuses the three-class exit contract shared with the other
# subcommands, so the §1.1 fence reads one exit vocabulary:
#   IGNORED            exit 0  precondition satisfied — the caller may write
#   NOT_IGNORED        exit 2  a RESOLVED 'not ignored' answer — the degraded arm
#   UNAVAILABLE <why>  exit 3  git could not answer — an unestablished measurement
# The IGNORED/NOT_IGNORED split is the resolved answer; UNAVAILABLE (and, at the
# fence, a denied-or-no-output invocation that prints no recognized token) is the
# unestablished measurement the fence routes to the run's stop path rather than
# treating as an unsatisfied precondition — so a matcher refusal can never
# masquerade as a decided degraded arm.
def _repo_toplevel() -> "str | None":
    """The current checkout's top-level directory, or None when git cannot answer.

    Resolved with ``git rev-parse --show-toplevel`` so a caller passing a
    repository-relative path resolves the same absolute target whether it is run
    from the repository root, a repository subdirectory, or inside a linked git
    worktree (issue #1633) — the enrolled implement fences must NOT compute the
    root themselves, so the helper that consumes the path resolves it. Inside a
    linked worktree ``--show-toplevel`` returns that worktree's own root, which is
    the correct anchor for its own ``.prflow/tmp/`` scratch tree.
    """
    result = _run_git(["rev-parse", "--show-toplevel"])
    top = result.stdout.strip()
    if result.returncode != 0 or not top:
        return None
    return top


def _anchor_repo_relative(path: str) -> "str | None":
    """Resolve ``path`` against the checkout root when it is repository-relative.

    An absolute path is returned unchanged. A relative path is joined onto the
    ``git rev-parse --show-toplevel`` root; when that root cannot be established,
    None is returned so the caller fails closed to UNAVAILABLE rather than
    silently anchoring to the process's cwd.
    """
    if os.path.isabs(path):
        return path
    top = _repo_toplevel()
    if top is None:
        return None
    return os.path.join(top, path)


def _path_is_ignored(path: str) -> "bool | None":
    """True if `path` is gitignored, False if not, None if git could not answer.

    Mirrors scripts/reception-record.py's _check_ignored: git's own ignore
    resolution via `git check-ignore -q`, which answers for a path that need not
    yet exist. returncode 0 → ignored, 1 → not ignored; anything else (128
    not-a-repo / error, or an OSError launching git) is undecidable → None.
    """
    try:
        proc = _run_git(["check-ignore", "-q", path])
    except OSError:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def ignore_precondition(args: argparse.Namespace) -> int:
    if not args.path:
        print("preflight.py: ignore-precondition requires a non-empty --path", file=sys.stderr)
        print("UNAVAILABLE path", flush=True)
        return UNAVAILABLE_EXIT
    path = args.path
    if args.repo_relative:
        # Anchoring mode (issue #1633): the fence passes a repository-relative path
        # and this helper resolves the root, so no enrolled fence computes it. An
        # unresolvable root is an unestablished measurement, never a decided answer.
        path = _anchor_repo_relative(args.path)
        if path is None:
            print(
                f"preflight.py: could not resolve the repository root to anchor "
                f"{args.path!r}",
                file=sys.stderr,
            )
            print("UNAVAILABLE resolve", flush=True)
            return UNAVAILABLE_EXIT
    ignored = _path_is_ignored(path)
    if ignored is None:
        print(
            f"preflight.py: git check-ignore could not resolve ignore state for {args.path}",
            file=sys.stderr,
        )
        print("UNAVAILABLE resolve", flush=True)
        return UNAVAILABLE_EXIT
    if ignored:
        # The resolved absolute target is printed with the token so the caller writes
        # to the path that was checked. The enrolled §1.1 fences cannot capture it in a
        # shell variable (a worktree-isolated session refuses that shape, issue #1633),
        # so the agent substitutes this literal into the guarded write.
        print(f"IGNORED {os.path.abspath(path)}", flush=True)
        return PROCEED_EXIT
    print(
        f"preflight.py: {args.path} is not covered by a gitignore rule; the "
        f"in-tree cache write is preconditioned on one being in effect",
        file=sys.stderr,
    )
    # Both RESOLVED arms carry the absolute target, so a caller on either arm names
    # the same in-tree location this subcommand answered about rather than a
    # cwd-relative one a subdirectory-launched run would resolve elsewhere.
    print(f"NOT_IGNORED {os.path.abspath(path)}", flush=True)
    return BLOCKED_EXIT


def lint_changed(args: argparse.Namespace) -> int:
    # Delegated to the lint_changed sibling module (issue #1389): the changed-file
    # advisory lint layer, kept out of this file so its git-enumeration, base64url,
    # selection, and receipt machinery does not bloat the Phase 1 preflight surface.
    import lint_changed as _lint

    return _lint.cmd_lint_changed(args)


def lint_full(args: argparse.Namespace) -> int:
    import lint_changed as _lint

    return _lint.cmd_lint_full(args)


class _Parser(argparse.ArgumentParser):
    """Exit usage errors with UNAVAILABLE_EXIT, not argparse's default 2.

    BLOCKED_EXIT (2) is the contract code the Phase 1 §1.3.5 gate maps to "named
    dependencies are still open". A malformed invocation (bad/empty --issue,
    neither input flag) must not masquerade as that verdict — it is an
    unestablished measurement, so route it to the UNAVAILABLE class
    (UNAVAILABLE_EXIT). The override is scoped to error()-routed failures; every
    non-help exit today flows through error().
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(UNAVAILABLE_EXIT, f"{self.prog}: error: {message}\n")


def main() -> int:
    _force_utf8_streams()
    parser = _Parser(description=__doc__)
    # Make the exit-3 (UNAVAILABLE) contract explicit rather than relying on
    # add_subparsers() defaulting parser_class to type(self): the subparser is
    # what raises `--issue notanint` / both-flags usage errors, so its exit code
    # must route through _Parser.error() → exit 3, not argparse's default 2
    # (which is the BLOCKED contract code). Issue #547 Important #5.
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    dependency_parser = subparsers.add_parser("dependencies")
    input_group = dependency_parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--issue", type=int)
    input_group.add_argument("--body-file")
    dependency_parser.add_argument(
        "--repo-relative",
        action="store_true",
        help="Resolve --body-file against the checkout root (issue #1633 anchoring mode).",
    )
    dependency_parser.set_defaults(func=dependencies)
    branch_state_parser = subparsers.add_parser("branch-state")
    branch_state_parser.add_argument("--state-file")
    branch_state_parser.set_defaults(func=branch_state)
    ignore_parser = subparsers.add_parser("ignore-precondition")
    ignore_parser.add_argument("--path")
    ignore_parser.add_argument(
        "--repo-relative",
        action="store_true",
        help="Resolve --path against the checkout root (issue #1633 anchoring mode), "
        "so the enrolled fence need not compute the repository root itself.",
    )
    ignore_parser.set_defaults(func=ignore_precondition)

    # ── lint-changed / lint-full (issue #1389) ──────────────────────────────
    # Advisory changed-file and repository-wide lint, selected through the
    # trigger-time validated lint manifest. `--manifest` lets a caller pass the
    # validated artifact rather than the candidate-edited working-tree copy.
    for _name, _func in (("lint-changed", lint_changed), ("lint-full", lint_full)):
        _p = subparsers.add_parser(_name)
        _p.add_argument("--manifest", help="path to the validated lint manifest (default: repo .prflow/lint-manifest.json)")
        _p.add_argument("--base", help="base branch for the merge-base changed set (default: config base_branch or main)")
        _p.add_argument("--run-id", help="receipt run id (default: $GITHUB_RUN_ID or 'local')")
        _p.add_argument("--run-attempt", help="receipt run attempt (default: $GITHUB_RUN_ATTEMPT or '1')")
        _p.set_defaults(func=_func)

    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - fail closed: any unanticipated error
        # An unanticipated exception would otherwise exit 1 — a fourth code
        # outside the {0,2,3} contract the §1.3.5 gate reads, which enumerates no
        # "other exit code" arm. Route it to UNAVAILABLE (never a silent PROCEED)
        # so any failure stays inside the contract. A SystemExit raised inside the
        # try (argparse's own exits happen in parse_args() above it, and _Parser
        # maps usage errors to UNAVAILABLE_EXIT) is BaseException, not Exception,
        # so it would propagate untouched. Surface the exception TYPE, not just its
        # payload, so a contained programming bug stays debuggable from the one
        # stderr breadcrumb the gate leaves.
        print(f"preflight.py: unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("UNAVAILABLE", flush=True)
        return UNAVAILABLE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())

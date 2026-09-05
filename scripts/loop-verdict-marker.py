#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow review-and-fix loop-verdict marker helper (issue #1212).

The `/prflow:review-and-fix` fix loop and the `/prflow:implement` orchestrator
talk across a plugin-version boundary. When the loop finishes it prints a
one-line verdict headline to chat; the implement run reads that headline by
exact string match to decide whether the work was independently reviewed. That
contract is ordinary English prose grepped by exact words — reword one side and
a reader one version behind breaks silently, and in the dangerous direction (an
`APPROVE WITH UNRESOLVED SHADOW FINDINGS` run read as a clean approve and shipped
unreviewed).

This helper is the machine-readable half of the fix, modelled on the review
verdict marker (`scripts/post-review-verdict.sh`, issue #1030). It composes and
parses a single producer-emitted marker line:

    <!-- prflow:loop-verdict result=<result-token> coverage=<full|not-verified> -->

The marker is placed at a FIXED position — line 1 of the loop's chat output,
immediately before the human verdict headline — and the reader looks ONLY at
that line, so a marker a finding quotes deeper in the report is prose, not a
stamp. The explanatory headline prose stays exactly as it was and carries NO
new coverage: only this marker is tool-read (issues #843/#876).

NAMESPACE. `<!-- prflow:` per issue #1003, with NO superseded `devflow:` spelling
accepted anywhere: this marker postdates the rename, so no persisted artifact can
carry the old one.

RESULT tokens (closed vocabulary — the six loop-level results, space-free so a
`key=value` marker parses):

    APPROVE                                 -> approve
    APPROVE with notes                      -> approve-with-notes
    APPROVE WITH CAVEAT                     -> approve-with-caveat
    APPROVE WITH ADVISORY NOTES             -> approve-with-advisory-notes
    APPROVE WITH UNRESOLVED SHADOW FINDINGS -> approve-unresolved-shadow-findings
    REJECT                                  -> reject

COVERAGE tokens: `full` ONLY when the loop's `{shadow status}` phrase, after
case-folding and whitespace-collapse, equals `shadow agreed, full coverage`;
every other phrase (any `shadow agreement not verified …` variant, an empty
phrase, an unrecognized one) normalizes to `not-verified`. This direction is
deliberate and fail-safe: the marker never over-claims full coverage.

Two subcommands, both stdlib-only and needing no config / gh / network. The optional
`compose --run-root` mode (issue #193) is the one exception: it grades the run root through
review-evidence-gate.grade_run_root_offline, which shells out to `git apply --numstat` — so
`compose` reaches git only on that additive path, and `read` and a legacy `compose` do not:

  compose --result "<human result>" --coverage "<shadow-status phrase>" [--run-root DIR]
      Emits the marker line to stdout (exit 0). An unmappable result prints a
      stderr breadcrumb and exits 3 with NO marker — a caller that gets no line
      composes its headline prose without a marker rather than stamping a lie.
      When --run-root is supplied (issue #193), the run root is graded offline
      through review-evidence-gate.grade_run_root_offline FIRST, and a non-pass
      grade refuses identically (stderr breadcrumb, exit 3, no marker) so an
      approval headline is never stamped over missing execution evidence. A legacy
      caller that passes no --run-root keeps the existing contract unchanged.

  read [FILE|-]
      Reads the chat output from FILE (or stdin) and inspects LINE 1 ONLY. Prints
      exactly one closed-vocabulary routing line and exits:

        CLEAN-FULL <result-token>          0  approve-family clean result, coverage=full
        CLEAN-NOT-VERIFIED <result-token>  0  approve-family clean result, coverage=not-verified
        AWUSF <coverage-token>             0  result=approve-unresolved-shadow-findings
        REJECT                             0  result=reject
        NO-MARKER                          2  line 1 is not a loop-verdict marker (prose fallback)
        MALFORMED <reason>                 3  marker-shaped line 1 with a bad/unknown field

      SAFE DIRECTION (issue #1212 AC5): only `CLEAN-FULL` authorizes the
      clean-and-fully-covered completion path. NO-MARKER and MALFORMED never do —
      a missing, malformed, or out-of-vocabulary marker routes the caller to its
      existing exact-wording fallback, and if that cannot resolve the verdict
      either, to the caller's existing not-clean handling. It is never read as a
      clean approve.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


MARKER_PREFIX = "<!-- prflow:loop-verdict "

# Human result string -> result token. Keys compared after collapsing internal
# whitespace runs to single spaces and stripping ends, so a headline that carries
# odd spacing still maps.
_RESULT_TO_TOKEN = {
    "approve": "approve",
    "approve with notes": "approve-with-notes",
    "approve with caveat": "approve-with-caveat",
    "approve with advisory notes": "approve-with-advisory-notes",
    "approve with unresolved shadow findings": "approve-unresolved-shadow-findings",
    "reject": "reject",
}

_RESULT_TOKENS = frozenset(_RESULT_TO_TOKEN.values())
_COVERAGE_TOKENS = frozenset({"full", "not-verified"})
# The clean approve family: every result token EXCEPT the two known non-clean ones
# (`reject` and the unresolved-shadow one, which is emphatically not a clean approval).
# Derived from _RESULT_TOKENS so a genuinely-clean approve result added to
# _RESULT_TO_TOKEN joins this set automatically — no second literal list to keep in
# sync — while the read routing still fails CLOSED on any token that is somehow in
# neither bucket. The derivation runs the other way too, and that direction is NOT
# automatic: a NON-clean result added to _RESULT_TO_TOKEN must be added to the
# exclusion below in the same change, or it is classified clean and routed as an
# approval. The exclusion is named rather than inlined so the unit test can pin the
# resulting partition, which is what turns that hazard from prose into an assertion.
_NON_CLEAN_TOKENS = frozenset({"reject", "approve-unresolved-shadow-findings"})
_CLEAN_APPROVE_TOKENS = _RESULT_TOKENS - _NON_CLEAN_TOKENS

# The read subcommand's closed OUTPUT vocabulary — the routing tokens the reader in
# skills/implement/phases/phase-3-fix-loop.md §3.3 consumes. The consumer is agent prose
# and cannot import these, so the coupling is by contract + the unit test; naming them
# here keeps the producer's emitted vocabulary self-documenting and typo-resistant. The
# reader routes on this STDOUT token; the exit code is advisory (exit 0 spans CLEAN,
# AWUSF, and REJECT alike, so it cannot authorize on its own).
ROUTE_CLEAN_FULL = "CLEAN-FULL"
ROUTE_CLEAN_NOT_VERIFIED = "CLEAN-NOT-VERIFIED"
ROUTE_AWUSF = "AWUSF"
ROUTE_REJECT = "REJECT"
ROUTE_NO_MARKER = "NO-MARKER"
ROUTE_MALFORMED = "MALFORMED"

# `full` requires the loop's {shadow status} phrase to equal this after case-folding and
# whitespace-collapse (see _normalize_coverage); every other phrase → not-verified.
_FULL_COVERAGE_PHRASE = "shadow agreed, full coverage"

_MARKER_RE = re.compile(
    r"^<!-- prflow:loop-verdict result=(?P<result>\S+) coverage=(?P<coverage>\S+) -->$"
)


def _normalize_result(raw: str) -> str | None:
    key = " ".join(raw.split()).lower()
    return _RESULT_TO_TOKEN.get(key)


def _normalize_coverage(raw: str) -> str:
    # `full` ONLY on the exact full-coverage phrase; everything else is not-verified.
    if " ".join(raw.split()).lower() == _FULL_COVERAGE_PHRASE:
        return "full"
    return "not-verified"


def _load_review_evidence_gate():
    """Import scripts/review-evidence-gate.py install-relative (a sibling in this scripts/
    dir), mirroring how that gate imports scripts/workpad.py (issue #193). Returns
    (module, None) or (None, reason) — a vendored consumer checkout resolves it the same way,
    relative to this installed file. The hyphenated filename is why this uses
    spec_from_file_location rather than a plain import."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "review-evidence-gate.py")
    try:
        spec = importlib.util.spec_from_file_location("loop_review_evidence_gate", path)
        if spec is None or spec.loader is None:
            return None, "no import spec for review-evidence-gate.py"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except Exception as e:  # any import fault refuses, never a crash
        return None, f"{type(e).__name__}: {e}"


def _run_root_grade_passes(run_root: str) -> tuple[bool, str]:
    """Grade `run_root` offline through review-evidence-gate.grade_run_root_offline (issue
    #193 AC5). Returns (True, token) only on an explicit `pass ` result; (False, reason) on
    any non-pass grade or an unavailable grader — the fail-closed direction, so a marker is
    never composed on unverified evidence."""
    gate, err = _load_review_evidence_gate()
    if gate is None:
        return False, f"grader-unavailable ({err})"
    try:
        token, _detail = gate.grade_run_root_offline(run_root)
    except Exception as e:  # a grader fault refuses, never over-claims a pass
        return False, f"grader-error ({type(e).__name__}: {e})"
    if token.startswith("pass "):
        return True, token
    return False, token


def _cmd_compose(args: argparse.Namespace) -> int:
    # Run-root evidence gate (issue #193 AC5): when a run root is supplied, refuse to compose
    # a verdict marker on a non-pass grade — no marker, a stderr diagnostic, exit 3, the same
    # shape as the unmappable-result refusal below. Legacy callers pass no --run-root and are
    # unchanged.
    if getattr(args, "run_root", None):
        ok, detail = _run_root_grade_passes(args.run_root)
        if not ok:
            sys.stderr.write(
                f"loop-verdict-marker: run root '{args.run_root}' did not pass the "
                f"review-evidence grade ({detail}) — refusing to compose a verdict marker "
                "(no line emitted); the run is evidence-missing\n"
            )
            return 3
    token = _normalize_result(args.result)
    if token is None:
        sys.stderr.write(
            f"loop-verdict-marker: result '{args.result}' is not one of the six loop-level "
            "results (APPROVE / APPROVE with notes / APPROVE WITH CAVEAT / "
            "APPROVE WITH ADVISORY NOTES / APPROVE WITH UNRESOLVED SHADOW FINDINGS "
            "/ REJECT) — refusing to compose a marker (no line emitted)\n"
        )
        return 3
    coverage = _normalize_coverage(args.coverage)
    # Reuse MARKER_PREFIX so the producer and the reader's _MARKER_RE can never drift
    # on the marker's leading literal.
    sys.stdout.write(f"{MARKER_PREFIX}result={token} coverage={coverage} -->\n")
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    if args.file in (None, "-"):
        data = sys.stdin.read()
    else:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                data = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable/undecodable input is not a decided verdict: route to the
            # prose fallback, never to clean.
            print(ROUTE_NO_MARKER)
            sys.stderr.write(f"loop-verdict-marker: could not read input: {exc}\n")
            return 2

    # LINE 1 ONLY — the fixed position. splitlines()[0] is line 1; an empty input
    # has no line 1.
    lines = data.splitlines()
    line1 = lines[0] if lines else ""

    if not line1.startswith(MARKER_PREFIX):
        print(ROUTE_NO_MARKER)
        return 2

    m = _MARKER_RE.match(line1)
    if m is None:
        print(f"{ROUTE_MALFORMED} marker-shaped-line-1-does-not-match-the-marker-grammar")
        return 3

    result = m.group("result")
    coverage = m.group("coverage")
    if result not in _RESULT_TOKENS:
        print(f"{ROUTE_MALFORMED} unknown-result-token={result}")
        return 3
    if coverage not in _COVERAGE_TOKENS:
        print(f"{ROUTE_MALFORMED} unknown-coverage-token={coverage}")
        return 3

    if result == "reject":
        print(ROUTE_REJECT)
        return 0
    if result == "approve-unresolved-shadow-findings":
        print(f"{ROUTE_AWUSF} {coverage}")
        return 0
    # A clean approve-family result — decided against the single-source set, never by
    # exclusion, so a future result token that is in _RESULT_TOKENS but in none of the
    # buckets above fails CLOSED to MALFORMED rather than being classified CLEAN.
    if result in _CLEAN_APPROVE_TOKENS:
        if coverage == "full":
            print(f"{ROUTE_CLEAN_FULL} {result}")
        else:
            print(f"{ROUTE_CLEAN_NOT_VERIFIED} {result}")
        return 0
    print(f"{ROUTE_MALFORMED} unrouted-result-token={result}")
    return 3


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        prog="loop-verdict-marker.py",
        description="Compose or read the review-and-fix loop-verdict marker (issue #1212).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_compose = sub.add_parser("compose", help="emit the marker line for a verdict")
    p_compose.add_argument("--result", required=True, help="the loop's human result string")
    p_compose.add_argument(
        "--coverage",
        required=True,
        help="the loop's {shadow status} phrase (e.g. 'shadow agreed, full coverage')",
    )
    p_compose.add_argument(
        "--run-root",
        default=None,
        help="optional (issue #193): the loop's held review run root. When given, refuse to "
        "compose a marker unless the run root passes the offline review-evidence grade.",
    )
    p_compose.set_defaults(func=_cmd_compose)

    p_read = sub.add_parser("read", help="parse line 1 of a chat output for the marker")
    p_read.add_argument("file", nargs="?", default="-", help="input file, or - for stdin")
    p_read.set_defaults(func=_cmd_read)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

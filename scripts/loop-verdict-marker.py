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

Four subcommands, all stdlib-only and needing no config / gh / network. Only two reach git:
`compose --run-root` (issue #193) and `check-evidence` (issue #426) each grade the run root
through review-evidence-gate (grade_run_root_offline / grade_active_entry_offline), which shells
out to `git apply --numstat` on that read-only path. `write-active-entry-binding` (issue #516)
only writes its own binding file, and it — like `read` and a legacy `compose` — reaches no git
at all:

  compose --result "<human result>" --coverage "<shadow-status phrase>" [--run-root DIR]
          [--entry <step1|shadow> --iteration N --head <40-hex>]
      Emits the marker line to stdout (exit 0). An unmappable result prints a
      stderr breadcrumb and exits 3 with NO marker — a caller that gets no line
      composes its headline prose without a marker rather than stamping a lie.
      When --run-root is supplied (issue #193), the run root is graded offline
      through review-evidence-gate FIRST, and a non-pass grade refuses identically
      (stderr breadcrumb, exit 3, no marker) so an approval headline is never
      stamped over missing execution evidence. Supplying --entry/--iteration/--head
      together (issue #516) grades the named entry's OWN producer evidence rather
      than the run-wide any-iteration grade; supplying none keeps the legacy
      run-wide contract unchanged. A legacy caller that passes no --run-root at all
      composes with no grading.

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

  check-evidence --run-root DIR [--entry <step1|shadow> --iteration N --head <40-hex>]
      Grades DIR through the SAME offline authority `compose --run-root` uses and
      prints one structured line, emitting NO verdict marker (issue #426). The fix
      loop calls this after a well-formed engine return, before consuming its
      verdict, so a run root missing its native checklist/verification evidence is
      caught early rather than only at terminal compose. Supplying
      --entry/--iteration/--head together (issue #516) grades that entry's own
      producer evidence — an earlier iteration's evidence never satisfies it —
      while supplying none keeps the legacy run-wide grade; a partial set exits 2.
      Output:

        PASS <run-root> <grade>           0  the run root passes the evidence grade
        FAIL <run-root> <grade>           3  a graded evidence failure
        UNESTABLISHED <run-root> <detail> 3  ungradeable: an unavailable/faulty grader,
                                             an unestablished grade, or an unknown outcome

      FAIL and UNESTABLISHED are distinguished by the token, not the exit code;
      both are non-pass and exit 3. A grader import/read/parse/internal failure is
      UNESTABLISHED, never PASS (fail-closed). Malformed arguments keep argparse's
      exit-2 behavior.

  write-active-entry-binding --run-root DIR --entry <step1|shadow> --iteration N
                             --head <40-hex>
      Producer emission (issue #516): snapshots this entry's checklist/verification/
      verifier-file evidence into ENTRY-SCOPED copies and writes the binding tying
      the entry to them (by path, digest, reviewed head, and reuse set). The
      snapshot is what lets a primary and a shadow entry sharing one run root's
      iteration-scoped filenames be graded separately. Prints `WROTE <path>` (exit
      0); a bad entry/iteration/head refuses (stderr breadcrumb, exit 3, no binding).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
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


# Active-entry operands (issue #516): the entry kinds a fix loop grades, and the reviewed-head
# shape. The producer writes one binding per (entry, iteration); the grader requires the
# caller's operands to match it, so a primary binding never answers a shadow ask.
_ACTIVE_ENTRIES = frozenset({"step1", "shadow"})
_HEAD_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")


def _classify_grade_result(get_token) -> tuple[str, str]:
    """Load the grader and classify a `(token, detail)` grade three ways (issue #426): an
    unavailable grader, a grader fault, or an unrecognized grade token is `unestablished` —
    never `pass` and never `fail` — so an ungradeable run is told apart from a graded failure
    and a grader fault can never become a pass. `get_token(gate)` names which offline grade
    to run (run-wide or active-entry), so both share this one invocation/classification path."""
    gate, err = _load_review_evidence_gate()
    if gate is None:
        return "unestablished", f"grader-unavailable ({err})"
    try:
        token, _detail = get_token(gate)
    except Exception as e:  # a grader fault is unestablished, never over-claims a pass
        return "unestablished", f"grader-error ({type(e).__name__}: {e})"
    if token.startswith("pass "):
        return "pass", token
    if token.startswith("fail "):
        return "fail", token
    if token.startswith("unestablished "):
        return "unestablished", token
    return "unestablished", f"unexpected-grade ({token})"


def _classify_run_root_grade(run_root: str) -> tuple[str, str]:
    """Grade `run_root` offline through the legacy run-wide review-evidence boundary `compose
    --run-root` uses (review-evidence-gate.grade_run_root_offline) — issue #426, unchanged by
    #516."""
    return _classify_grade_result(lambda gate: gate.grade_run_root_offline(run_root))


def _classify_active_entry_grade(run_root: str, entry: str, iteration: int,
                                 head: str) -> tuple[str, str]:
    """Grade `run_root` offline against the named entry's OWN producer evidence through
    review-evidence-gate.grade_active_entry_offline (issue #516). Same three-way classification
    as the run-wide grade, so an earlier iteration's evidence never becomes this entry's pass."""
    return _classify_grade_result(
        lambda gate: gate.grade_active_entry_offline(run_root, entry, iteration, head))


def _active_entry_operands(args: argparse.Namespace):
    """Resolve the shared active-entry operands (issue #516). Returns (entry, iteration, head)
    when all three are supplied, the sentinel ('__partial__', None, None) when only some are
    (a caller wiring bug — refuse rather than silently grade legacy), or (None, None, None) for
    the legacy run-wide path when none are supplied."""
    provided = (getattr(args, "entry", None), getattr(args, "iteration", None),
                getattr(args, "head", None))
    if all(v is None for v in provided):
        return None, None, None
    if any(v is None for v in provided):
        return "__partial__", None, None
    return args.entry, args.iteration, args.head


def _sha256_of(path: str) -> str | None:
    """The sha256 hex of a file's bytes, or None when it cannot be read. Reads bytes so a
    non-UTF-8 artifact digests without raising."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _reuse_from_checklist(path: str, iteration: int) -> list[dict]:
    """Read this iteration's checklist and record a reuse entry for each item carrying a truthy
    `reused_from_iter_prev` flag (phase-2-verification.md §2.0.5 narrow-reuse). `from_iteration`
    is the item's own `reused_from_iter` when a positive int, else the immediately prior
    iteration. An unreadable or malformed checklist yields an empty reuse set — the grader then
    requires this entry's own producer evidence for every item (the fail-closed direction)."""
    try:
        with open(path, encoding="utf-8") as fh:
            items = json.loads(fh.read())
    except (OSError, ValueError, UnicodeError):
        return []
    if not isinstance(items, list):
        return []
    reuse = []
    for item in items:
        if not isinstance(item, dict) or not item.get("reused_from_iter_prev"):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue
        frm = item.get("reused_from_iter")
        if not (isinstance(frm, int) and not isinstance(frm, bool) and frm >= 1):
            frm = iteration - 1
        reuse.append({"item_id": item_id, "from_iteration": frm})
    return reuse


def _snapshot_file(src: str, dst: str) -> None:
    """Copy `src` to `dst` when `src` exists; do nothing when it does not (an absent source
    leaves no snapshot, and the grader then reports the named artifact missing — fail, never a
    spurious pass). Best-effort on a copy error, for the same reason."""
    try:
        shutil.copyfile(src, dst)
    except OSError:
        pass


def _snapshot_verdicts(src_dir: str, dst_dir: str) -> None:
    """Copy every `<item-id>-*.json` nonce verifier file from `src_dir` into `dst_dir`. An
    absent source directory leaves the snapshot empty, so the grader reports each agent item's
    verifier file missing rather than passing on unrelated evidence."""
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except OSError:
        return
    for src in glob.glob(os.path.join(src_dir, "*.json")):
        _snapshot_file(src, os.path.join(dst_dir, os.path.basename(src)))


def _cmd_write_active_entry_binding(args: argparse.Namespace) -> int:
    """Producer emission (issue #516): snapshot this entry's checklist, verification and
    verifier-file evidence into ENTRY-SCOPED copies and write a binding naming them (by path
    and digest), the reviewed head, and the reuse set. The snapshot is what makes a primary
    and a shadow entry sharing one run root's iteration-scoped filenames separately gradeable:
    the other entry's later overwrite of the shared `checklist-iter-<N>.json` /
    `verdicts/iter-<N>/` cannot disturb this entry's captured copy, so a terminal re-grade of
    this entry still reads its own evidence (AC4/AC6). Refuses on a bad entry/iteration/head —
    no binding written — the same stderr+exit-3 shape as compose's refusals, so a caller that
    gets no confirmation never assumes a binding it does not have."""
    if args.entry not in _ACTIVE_ENTRIES:
        sys.stderr.write(
            f"loop-verdict-marker: --entry must be one of {sorted(_ACTIVE_ENTRIES)} "
            f"(got {args.entry!r}) — no active-entry binding written\n")
        return 3
    if args.iteration < 1:
        sys.stderr.write(
            "loop-verdict-marker: --iteration must be a positive integer — "
            "no active-entry binding written\n")
        return 3
    if not _HEAD_RE.match(args.head or ""):
        sys.stderr.write(
            "loop-verdict-marker: --head must be a 40-character hex commit sha — "
            "no active-entry binding written\n")
        return 3
    n, entry, root = args.iteration, args.entry, args.run_root
    src_checklist = os.path.join(root, f"checklist-iter-{n}.json")
    src_verification = os.path.join(root, f"verification-iter-{n}.json")
    dst_checklist_name = f"checklist-{entry}-iter-{n}.json"
    dst_verification_name = f"verification-{entry}-iter-{n}.json"
    dst_verdicts_subdir = os.path.join(f"verdicts-{entry}", f"iter-{n}")
    _snapshot_file(src_checklist, os.path.join(root, dst_checklist_name))
    _snapshot_file(src_verification, os.path.join(root, dst_verification_name))
    _snapshot_verdicts(os.path.join(root, "verdicts", f"iter-{n}"),
                       os.path.join(root, dst_verdicts_subdir))
    binding = {
        "schema_version": 1,
        "entry": entry,
        "iteration": n,
        "reviewed_head": args.head.lower(),
        "checklist_artifact": dst_checklist_name,
        "checklist_sha256": _sha256_of(os.path.join(root, dst_checklist_name)),
        "verification_artifact": dst_verification_name,
        "verification_sha256": _sha256_of(os.path.join(root, dst_verification_name)),
        "verdicts_subdir": dst_verdicts_subdir,
        "reuse": _reuse_from_checklist(src_checklist, n),
    }
    out_path = os.path.join(root, f"active-entry-{entry}-iter-{n}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(binding, fh)
    except OSError as e:
        sys.stderr.write(
            f"loop-verdict-marker: could not write active-entry binding to {out_path}: {e}\n")
        return 3
    sys.stdout.write(f"WROTE {out_path}\n")
    return 0


def _run_root_grade_passes(run_root: str) -> tuple[bool, str]:
    """Grade `run_root` offline (issue #193 AC5). Returns (True, token) only on an explicit
    `pass ` result; (False, reason) on any non-pass grade or an unavailable grader — the
    fail-closed direction, so a marker is never composed on unverified evidence. Expressed
    over `_classify_run_root_grade` so `compose` and `check-evidence` share one
    grader-invocation path; `compose` only ever consumed the boolean, so its behavior is
    unchanged."""
    outcome, detail = _classify_run_root_grade(run_root)
    return outcome == "pass", detail


def _cmd_compose(args: argparse.Namespace) -> int:
    # Run-root evidence gate (issue #193 AC5): when a run root is supplied, refuse to compose
    # a verdict marker on a non-pass grade — no marker, a stderr diagnostic, exit 3, the same
    # shape as the unmappable-result refusal below. Legacy callers pass no --run-root and are
    # unchanged.
    if getattr(args, "run_root", None):
        entry, iteration, head = _active_entry_operands(args)
        if entry == "__partial__":
            sys.stderr.write(
                "loop-verdict-marker: --entry, --iteration and --head must be supplied "
                "together for an active-entry grade — no marker emitted\n")
            return 3
        if entry is not None:
            # Active-entry grade (issue #516): this entry's own producer evidence, not the
            # run-wide grade, gates whether the terminal marker may be stamped.
            outcome, detail = _classify_active_entry_grade(
                args.run_root, entry, iteration, head)
            ok = outcome == "pass"
        else:
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


CHECK_EVIDENCE_TOKENS = {"pass": "PASS", "fail": "FAIL", "unestablished": "UNESTABLISHED"}


def _cmd_check_evidence(args: argparse.Namespace) -> int:
    entry, iteration, head = _active_entry_operands(args)
    if entry == "__partial__":
        sys.stderr.write(
            "loop-verdict-marker: --entry, --iteration and --head must be supplied together "
            "for an active-entry grade\n")
        return 2
    if entry is not None:
        outcome, detail = _classify_active_entry_grade(args.run_root, entry, iteration, head)
    else:
        outcome, detail = _classify_run_root_grade(args.run_root)
    # `detail` can carry a grader exception message with embedded CR/LF; flatten it so the
    # docstring's "one structured line" holds and the reader's splitlines()[0] sees the whole
    # record, not a truncated first physical line.
    detail = detail.replace("\r", " ").replace("\n", " ")
    sys.stdout.write(f"{CHECK_EVIDENCE_TOKENS[outcome]} {args.run_root} {detail}\n")
    return 0 if outcome == "pass" else 3


def _add_active_entry_args(sub_parser: argparse.ArgumentParser) -> None:
    """Add the optional active-entry operands (issue #516) to a compose/check-evidence parser.
    All three together select the entry-bound grade; none selects the legacy run-wide grade;
    a partial set is refused by the command handler (a caller wiring bug)."""
    sub_parser.add_argument(
        "--entry", default=None,
        help="optional (issue #516): the fix-loop entry (step1|shadow) to grade against its "
        "own producer evidence. Supply --entry, --iteration and --head together.")
    sub_parser.add_argument(
        "--iteration", default=None, type=int,
        help="optional (issue #516): the engine iteration of the active entry.")
    sub_parser.add_argument(
        "--head", default=None,
        help="optional (issue #516): the reviewed head (40-char hex) of the active entry.")


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
    _add_active_entry_args(p_compose)
    p_compose.set_defaults(func=_cmd_compose)

    p_read = sub.add_parser("read", help="parse line 1 of a chat output for the marker")
    p_read.add_argument("file", nargs="?", default="-", help="input file, or - for stdin")
    p_read.set_defaults(func=_cmd_read)

    p_check = sub.add_parser(
        "check-evidence",
        help="grade a held review run root offline and print a non-publishing structured "
        "outcome (issue #426), emitting no verdict marker",
    )
    p_check.add_argument(
        "--run-root",
        required=True,
        help="the loop's held review run root to grade through the same offline evidence "
        "authority compose --run-root uses",
    )
    _add_active_entry_args(p_check)
    p_check.set_defaults(func=_cmd_check_evidence)

    p_bind = sub.add_parser(
        "write-active-entry-binding",
        help="producer emission (issue #516): write the active-entry binding tying an entry's "
        "verdict to its own checklist/verification/verifier-file evidence",
    )
    p_bind.add_argument("--run-root", required=True, help="the entry's held review run root")
    p_bind.add_argument("--entry", required=True,
                        help="the fix-loop entry kind: step1 (primary) or shadow")
    p_bind.add_argument("--iteration", required=True, type=int,
                        help="the engine iteration this entry produced")
    p_bind.add_argument("--head", required=True,
                        help="the reviewed head (40-char hex) this entry's diff was produced at")
    p_bind.set_defaults(func=_cmd_write_active_entry_binding)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

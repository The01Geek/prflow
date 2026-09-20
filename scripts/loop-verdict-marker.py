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

    <!-- prflow:loop-verdict result=<result-token> coverage=<full|skipped|not-verified> -->

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
`skipped` ONLY when it equals `shadow skipped, iteration 1 clean` (the loop's
clean-iteration-1 exit under /prflow:implement — no shadow was owed); every
other phrase (any `shadow agreement not verified …` variant, an empty phrase, an
unrecognized one) normalizes to `not-verified`. This direction is deliberate and
fail-safe: the marker never over-claims full coverage or a skip.

Four subcommands, all stdlib-only and needing no config / gh / network. Only two reach git:
`compose --run-root` (issue #193) and `check-evidence` (issue #426) each grade the run root
through review-evidence-gate (grade_run_root_offline / grade_active_entry_offline), which shells
out to `git apply --numstat` on that read-only path. `write-active-entry-binding` (issue #516)
only writes its own binding file, and it — like `read` — reaches no git
at all:

  compose --result "<human result>" --coverage "<shadow-status phrase>" --run-root DIR
          [--entry <step1|shadow> --iteration N --head <40-hex>]
      Emits the marker line to stdout (exit 0). An unmappable result prints a
      stderr breadcrumb and exits 3 with NO marker — a caller that gets no line
      composes its headline prose without a marker rather than stamping a lie.
      --run-root is REQUIRED (issue #727): the run root is graded offline through
      review-evidence-gate FIRST, and a non-pass grade refuses identically (stderr
      breadcrumb, exit 3, no marker) so an approval headline is never stamped over
      missing execution evidence. There is no ungraded form — a compose with no
      --run-root refuses (stderr breadcrumb, exit 3, no marker), naming the
      checklist/verification evidence it would have graded. Supplying
      --entry/--iteration/--head together (issue #516) grades the named entry's OWN
      producer evidence rather than the run-wide any-iteration grade; supplying none
      keeps the run-wide grade. `--entry latest --iteration N` (issue #676, no --head)
      lets the helper SELECT the binding to grade: the step1 binding at N when it
      exists; else, when the run-root diff authorizes an intentional checklist skip,
      it passes with no binding (AC10); else — when iter-<N>.json records a
      `shadow`/`park-calibration-post-shadow` promotion — the shadow binding at N
      (falling back to N-1), grading the selected binding with its own recorded head.
      Selecting no binding refuses (exit 3, no marker) unless the phase log carries the
      grader's blocker-recheck-hit/generator-failure record; it also refuses on an empty
      --run-root, a passed --head, an absent --iteration, an unusable iter-<N>.json, an
      unpromoted iteration, or a non-pass grade of the selected binding.

  read [FILE|-]
      Reads the chat output from FILE (or stdin) and inspects LINE 1 ONLY. Prints
      exactly one closed-vocabulary routing line and exits:

        CLEAN-FULL <result-token>          0  approve-family clean result, coverage=full
        CLEAN-SHADOW-SKIPPED <result-token> 0 approve-family clean result, coverage=skipped
        CLEAN-NOT-VERIFIED <result-token>  0  approve-family clean result, coverage=not-verified
        AWUSF <coverage-token>             0  result=approve-unresolved-shadow-findings
        REJECT                             0  result=reject
        NO-MARKER                          2  line 1 is not a loop-verdict marker (prose fallback)
        MALFORMED <reason>                 3  marker-shaped line 1 with a bad/unknown field

      SAFE DIRECTION (issue #1212 AC5): only `CLEAN-FULL` authorizes the
      clean-and-fully-covered completion path, and only `CLEAN-SHADOW-SKIPPED` the
      clean no-shadow-owed one. NO-MARKER and MALFORMED never do —
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
      both are non-pass and exit 3. With --entry (issue #673) each grade is recorded at
      evidence-grade-<entry>-iter-<N>.json, and while ANOTHER entry's last recorded grade is
      non-pass the command prints `UNESTABLISHED <run-root> unrecovered-evidence-gate: …`
      (exit 3) without grading; `write-active-entry-binding` and `compose --run-root` refuse
      on the same condition, so only a passing re-grade of that entry clears it. A grader import/read/parse/internal failure is
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
    """Force stdin/stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
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
_COVERAGE_TOKENS = frozenset({"full", "skipped", "not-verified"})
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
ROUTE_CLEAN_SHADOW_SKIPPED = "CLEAN-SHADOW-SKIPPED"
ROUTE_CLEAN_NOT_VERIFIED = "CLEAN-NOT-VERIFIED"
ROUTE_AWUSF = "AWUSF"
ROUTE_REJECT = "REJECT"
ROUTE_NO_MARKER = "NO-MARKER"
ROUTE_MALFORMED = "MALFORMED"

# `full` requires the loop's {shadow status} phrase to equal this after case-folding and
# whitespace-collapse (see _normalize_coverage); every other phrase → not-verified.
_FULL_COVERAGE_PHRASE = "shadow agreed, full coverage"
# `skipped` requires this exact phrase the same way: the loop's clean-iteration-1 exit.
_SKIPPED_COVERAGE_PHRASE = "shadow skipped, iteration 1 clean"

_MARKER_RE = re.compile(
    r"^<!-- prflow:loop-verdict result=(?P<result>\S+) coverage=(?P<coverage>\S+) -->$"
)


def _normalize_result(raw: str) -> str | None:
    key = " ".join(raw.split()).lower()
    return _RESULT_TO_TOKEN.get(key)


def _normalize_coverage(raw: str) -> str:
    # `full` / `skipped` ONLY on their exact phrases; everything else is not-verified.
    phrase = " ".join(raw.split()).lower()
    if phrase == _FULL_COVERAGE_PHRASE:
        return "full"
    if phrase == _SKIPPED_COVERAGE_PHRASE:
        return "skipped"
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


def _classify_active_entry_grade_raw(run_root: str, entry: str, iteration: int,
                                     head: str) -> tuple[str, str]:
    """Grade `run_root` offline against the named entry's OWN producer evidence through
    review-evidence-gate.grade_active_entry_offline (issue #516). Same three-way classification
    as the run-wide grade, so an earlier iteration's evidence never becomes this entry's pass."""
    return _classify_grade_result(
        lambda gate: gate.grade_active_entry_offline(run_root, entry, iteration, head))


def _classify_active_entry_grade(run_root: str, entry: str, iteration: int,
                                 head: str) -> tuple[str, str]:
    """Grade the named entry (issue #516) and, on a NON-PASS, append the entry's
    `evidence_recovery` state from iter-<N>.json as diagnostic detail (issue #673). The outcome
    and exit are unchanged; a PASS never reads the marker. Enforcement is `_unrecovered_gate`."""
    outcome, detail = _classify_active_entry_grade_raw(run_root, entry, iteration, head)
    if outcome == "pass":
        return outcome, detail
    return outcome, detail + _recovery_state_suffix(run_root, entry, iteration, head)


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
    `reused_from_iter_prev` flag (phase-1-checklist.md §1.0 carry-forward). `from_iteration`
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


def _snapshot_verdicts(src_dir: str, dst_dir: str, replace: bool = False) -> None:
    """Copy every `<item-id>-*.json` nonce verifier file from `src_dir` into `dst_dir`. An
    absent source directory leaves the snapshot empty, so the grader reports each agent item's
    verifier file missing rather than passing on unrelated evidence. With `replace`, the
    destination's own `*.json` files are removed first, so a re-bind during recovery captures
    what `src_dir` holds NOW and never retains a wider first-attempt claim set (issue #621).
    A removal that fails leaves a residue the grader may read as this entry's evidence, so it
    prints a named stderr breadcrumb — the diagnosable residue shape, not a silent retention —
    and the snapshot still proceeds."""
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except OSError:
        return
    if replace:
        for stale in glob.glob(os.path.join(dst_dir, "*.json")):
            try:
                os.remove(stale)
            except OSError as e:
                sys.stderr.write(
                    f"loop-verdict-marker: could not remove the prior snapshot file "
                    f"{stale}: {e} — it stays in the snapshot\n")
    for src in glob.glob(os.path.join(src_dir, "*.json")):
        _snapshot_file(src, os.path.join(dst_dir, os.path.basename(src)))


# Step 1.8 grade records (issue #673). `check-evidence --entry` records each entry's latest grade
# at evidence-grade-<entry>-iter-<N>.json. While any OTHER entry's last grade is non-pass,
# `write-active-entry-binding`, `check-evidence --entry` and `compose --run-root` refuse, so the
# loop cannot reach a later entry or loop exit past an unrecovered gate; only a passing re-grade of
# that entry (its bounded recovery) clears it. No record means that entry was never graded here.
_GRADE_RECORD_RE = re.compile(r"\Aevidence-grade-(step1|shadow)-iter-([1-9][0-9]*)\.json\Z")
_GRADE_OUTCOMES = frozenset({"pass", "fail", "unestablished"})


def _write_grade_record(run_root: str, entry: str, iteration: int, head: str, outcome: str,
                        detail: str) -> str | None:
    """Atomically record this entry's latest grade. Returns None, or the write error."""
    path = os.path.join(run_root, f"evidence-grade-{entry}-iter-{iteration}.json")
    record = {"entry": entry, "iteration": iteration, "reviewed_head": head,
              "outcome": outcome, "detail": detail}
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        os.replace(path + ".tmp", path)
    except OSError as e:
        return str(e)
    return None


def _read_grade_record(path: str) -> tuple[str, str]:
    """(outcome, detail) of one grade record, or ('malformed', reason). A guard: every shape it
    cannot read refuses rather than passing (CLAUDE.md matrix)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return "malformed", "is unreadable"
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return "malformed", "is not valid JSON"
    except RecursionError:
        return "malformed", "is nested too deeply to parse"
    if not isinstance(obj, dict):
        return "malformed", "is not a JSON object"
    outcome = obj.get("outcome")
    if not isinstance(outcome, str) or outcome not in _GRADE_OUTCOMES:
        return "malformed", "carries no valid outcome"
    detail = obj.get("detail")
    return outcome, detail if isinstance(detail, str) else ""


def _unrecovered_gate(run_root: str, exclude: tuple[str, int] | None = None) -> str | None:
    """None when no recorded entry other than `exclude` was last graded non-pass; else the
    `unrecovered-evidence-gate` refusal detail naming that entry, iteration and grade."""
    try:
        names = os.listdir(run_root)
    except FileNotFoundError:
        return None
    except OSError as e:
        return f"unrecovered-evidence-gate: the run root cannot be listed ({e})"
    keys = sorted((int(m.group(2)), m.group(1), name)
                  for name in names if (m := _GRADE_RECORD_RE.match(name)))
    for iteration, entry, name in keys:
        if (entry, iteration) == exclude:
            continue
        outcome, detail = _read_grade_record(os.path.join(run_root, name))
        if outcome == "malformed":
            return f"unrecovered-evidence-gate: {name} {detail}"
        if outcome != "pass":
            detail = detail.replace("\r", " ").replace("\n", " ")
            return (f"unrecovered-evidence-gate: {entry} iteration {iteration} was last graded "
                    f"{outcome} ({detail}) and no re-grade has passed")
    return None


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
    gate_detail = _unrecovered_gate(root, exclude=(entry, n))
    if gate_detail is not None:
        sys.stderr.write(
            f"loop-verdict-marker: {gate_detail} — refusing to bind {entry} iteration {n}; "
            "no active-entry binding written\n")
        return 3
    src_checklist = os.path.join(root, f"checklist-iter-{n}.json")
    src_verification = os.path.join(root, f"verification-iter-{n}.json")
    dst_checklist_name = f"checklist-{entry}-iter-{n}.json"
    dst_verification_name = f"verification-{entry}-iter-{n}.json"
    dst_verdicts_subdir = os.path.join(f"verdicts-{entry}", f"iter-{n}")
    _snapshot_file(src_checklist, os.path.join(root, dst_checklist_name))
    _snapshot_file(src_verification, os.path.join(root, dst_verification_name))
    # The shadow re-binds on recovery, and its snapshot must then hold exactly what
    # `verdicts/iter-<n>/` holds now — a retained first-attempt file would be graded as
    # evidence for a claim the recovered checklist no longer carries (issue #621).
    _snapshot_verdicts(os.path.join(root, "verdicts", f"iter-{n}"),
                       os.path.join(root, dst_verdicts_subdir), replace=(entry == "shadow"))
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


# `--entry latest` selection (issue #676): the loop-exit stamp passes `--entry latest
# --iteration N` and the helper picks which binding to grade, so a fix loop that exits after a
# shadow-promoted iteration (which runs no step1 engine, so has no step1 binding at N) stamps
# the shadow review that actually covered the final diff instead of refusing.
_PROMOTING_PROVENANCE = frozenset({"shadow", "park-calibration-post-shadow"})
# The iter-<N>.json reader's refusal reasons (issue #676; CLAUDE.md best-effort-parser matrix).
_ITER_REASON_TEXT = {
    "absent": "is absent",
    "unreadable": "is unreadable or not valid JSON",
    "not-object": "is not a JSON object",
    "too-deep": "is nested too deeply to parse",
    "non-string": "carries a non-string promotion_provenance",
}


def _evidence_missing_stderr(run_root: str, detail: str, *, selected: str = "") -> None:
    """Write the shared `evidence-missing` refusal breadcrumb — the run-wide grade, the
    active-entry grade, and the `--entry latest` selected-binding grade all refuse with this one
    sentence, so a single formatter keeps their wording from drifting apart. `selected` names the
    chosen binding when the refusal grades one."""
    where = f" for the selected {selected}" if selected else ""
    sys.stderr.write(
        f"loop-verdict-marker: run root '{run_root}' did not pass the review-evidence "
        f"grade{where} ({detail}) — refusing to compose a verdict marker (no line emitted); "
        "the run is evidence-missing\n")


def _binding_file_exists(run_root: str, entry: str, iteration: int) -> bool:
    """Whether this entry's active-entry binding FILE exists at (entry, iteration). Existence,
    not validity, decides selection: a present-but-corrupt binding is still selected, and the
    grader then refuses it with its own unreadable/malformed/mismatch reason rather than the
    selector silently falling through to a different binding."""
    return os.path.isfile(
        os.path.join(run_root, f"active-entry-{entry}-iter-{iteration}.json"))


def _binding_reviewed_head(gate, run_root: str, entry: str, iteration: int) -> str:
    """The reviewed_head recorded in the (entry, iteration) binding, or '' when it is
    absent/unreadable/malformed. `--entry latest` passes no --head, so the selected binding's
    OWN recorded head is what the grader is asked for — feeding a mislabeled binding its
    file-suffix iteration with the head it records is what still surfaces as binding-mismatch.
    A '' feeds a refusing grade, never a silent pass."""
    binding, _reason = gate._read_active_entry_binding(run_root, entry, iteration)
    if binding is None:
        return ""
    head = binding.get("reviewed_head")
    return head if isinstance(head, str) else ""


def _load_iter_object(run_root: str, iteration: int) -> tuple[dict | None, str | None]:
    """Load iter-<iteration>.json as a JSON object (issues #676, #673): the shared file-load and
    parse guard both iter-<N>.json readers use. Returns (obj, None) for a dict root, else
    (None, reason) with reason in absent|unreadable|too-deep|not-object. The loop writes this file and an
    agent can corrupt it, so every non-object shape refuses rather than being read (CLAUDE.md
    best-effort-parser matrix: object/array/scalar/valid-falsy/missing/wrong-type)."""
    path = os.path.join(run_root, f"iter-{iteration}.json")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return None, "unreadable"
    except RecursionError:
        return None, "too-deep"
    if not isinstance(obj, dict):
        return None, "not-object"
    return obj, None


def _read_promotion_provenance(run_root: str, iteration: int) -> tuple[str | None, str | None]:
    """Read iter-<N>.json's promotion_provenance (issue #676). Returns (provenance, None) for a
    JSON OBJECT carrying a string promotion_provenance, else (None, reason) with reason in
    absent|unreadable|not-object|non-string — every non-object/non-string shape refuses rather
    than being read as a promotion."""
    obj, reason = _load_iter_object(run_root, iteration)
    if reason is not None:
        return None, reason
    prov = obj.get("promotion_provenance")
    if not isinstance(prov, str):
        return None, "non-string"
    return prov, None


def _read_evidence_recovery_marker(run_root: str, entry: str, iteration: int,
                                   reviewed_head: str) -> tuple[str, str | None]:
    """Read this entry's evidence_recovery marker from iter-<iteration>.json (issue #673).
    Returns ('absent', None) — no recovery attempted for THIS {entry, iteration, reviewed_head}
    key: a normal state, and the state a stale/foreign key (a different head, iteration, or
    entry already recorded) also reads as, never laundered into a spent attempt; ('present',
    attempted_at) when a well-typed marker's key matches exactly; or a refusal kind with no
    value — 'iter-absent'/'iter-unreadable'/'iter-not-object' for the file itself (the
    `_load_iter_object` reason re-prefixed so the marker-'absent' state stays distinct from a
    file that is absent), 'recovery-malformed' for a non-object marker or a mistyped/missing
    field, or 'shadow-malformed' for a present, non-null shadow block that is not an object. A
    guard, not a best-effort parser (CLAUDE.md matrix: object/array/scalar/valid-falsy/
    missing/wrong-type): an unreadable shape refuses rather than resolving to 'absent', which
    would launder the unrecovered failure this reader exists to surface. The marker is top-level
    for the step1 entry and nested under `shadow` for the shadow entry (loop-control.md schema)."""
    obj, reason = _load_iter_object(run_root, iteration)
    if reason is not None:
        return f"iter-{reason}", None
    if entry == "shadow":
        container = obj.get("shadow")
        # A run with no shadow block yet (key absent or an explicit null) has no shadow
        # recovery — absent, not malformed. But a PRESENT, non-null shadow block that is not an
        # object is corruption (CLAUDE.md wrong-type / valid-falsy cells): refuse rather than
        # read it as absent, which would launder the reason of an already non-passing grade.
        if "shadow" not in obj or container is None:
            return "absent", None
        if not isinstance(container, dict):
            return "shadow-malformed", None
    else:
        container = obj
    if "evidence_recovery" not in container:
        return "absent", None
    rec = container.get("evidence_recovery")
    # An array, scalar, or valid-falsy value (false, 0, "") is not the object the schema
    # defines — malformed, never read as an absent-or-present marker.
    if not isinstance(rec, dict):
        return "recovery-malformed", None
    rec_entry = rec.get("entry")
    rec_iteration = rec.get("iteration")
    rec_head = rec.get("reviewed_head")
    if not isinstance(rec_entry, str) or not rec_entry:
        return "recovery-malformed", None
    # A bool is an int subclass (True == 1), so reject it explicitly — only a real int is an
    # iteration (mirrors review-evidence-gate._read_active_entry_binding's landmine).
    if not isinstance(rec_iteration, int) or isinstance(rec_iteration, bool):
        return "recovery-malformed", None
    if not isinstance(rec_head, str) or not rec_head:
        return "recovery-malformed", None
    # Key discrimination: a marker for another {entry, iteration, reviewed_head} is not this
    # key's recovery, so it reads as absent for THIS key — a HEAD change or a stale iteration's
    # marker cannot answer, nor consume, the current key's one-attempt allowance.
    if (rec_entry != entry or rec_iteration != iteration
            or rec_head.lower() != (reviewed_head or "").lower()):
        return "absent", None
    attempted_at = rec.get("attempted_at")
    return "present", attempted_at if isinstance(attempted_at, str) else None


def _recovery_state_suffix(run_root: str, entry: str, iteration: int, head: str) -> str:
    """The recovery-state clause appended to a non-passing active-entry grade's detail (issue
    #673): the file+reason on an unreadable shape, 'no recovery attempted' on an absent key, or
    the spent attempt on a present one."""
    kind, attempted_at = _read_evidence_recovery_marker(run_root, entry, iteration, head)
    if kind == "absent":
        return f"; no Step 1.8 recovery attempted for {entry} iteration {iteration}"
    if kind == "present":
        when = f" at {attempted_at}" if attempted_at else " (time unrecorded)"
        return (f"; a Step 1.8 recovery was attempted{when} for {entry} iteration "
                f"{iteration} but the entry is still non-passing")
    # kind is 'recovery-malformed', 'shadow-malformed' (a present, non-null shadow block that is
    # not an object), or an 'iter-absent'/'iter-unreadable'/'iter-not-object' iter-file state that
    # reuses the shared iter-file reason text (stripping the 'iter-' prefix that keeps it distinct
    # from a marker-absent).
    if kind == "recovery-malformed":
        tail = "carries a malformed evidence_recovery marker"
    elif kind == "shadow-malformed":
        tail = "shadow block is not an object"
    else:
        tail = _ITER_REASON_TEXT[kind[len("iter-"):]]
    return f"; the Step 1.8 recovery state is unreadable: iter-{iteration}.json {tail}"


def _grade_selected_latest(args: argparse.Namespace, gate, entry: str,
                           iteration: int) -> int | None:
    """Grade the selected (entry, iteration) binding with its OWN recorded head. Returns None
    when it passes (the caller emits the marker), or 3 after a stderr breadcrumb — no fallback
    to another binding, exactly as the loop refuses a failed active-entry grade today."""
    head = _binding_reviewed_head(gate, args.run_root, entry, iteration)
    outcome, detail = _classify_active_entry_grade(args.run_root, entry, iteration, head)
    if outcome == "pass":
        return None
    _evidence_missing_stderr(args.run_root, detail,
                             selected=f"{entry} binding at iteration {iteration}")
    return 3


def _refuse_no_binding(gate, run_root: str, message: str) -> int | None:
    """No binding was selected, so the grader's phase-log no-binding pass still applies (AC7):
    a `blocker-recheck-hit`/`generator-failure` record legitimately stands in for the checklist
    phases, exactly as `--entry step1` accepts it for a missing binding. Returns None on that
    pass, else 3 after a breadcrumb — the log's own unreadable/malformed reason when it has one,
    otherwise `message`."""
    grade = gate._special_record_grade(run_root)
    if grade is None:
        sys.stderr.write(message)
        return 3
    if grade[0] == "special":
        return None
    _evidence_missing_stderr(run_root, str(grade[1]))
    return 3


def _compose_latest_gate(args: argparse.Namespace) -> int | None:
    """Select and grade the binding a `--entry latest --iteration N` stamp covers (issue #676).
    Returns None when the run may be stamped (the caller emits the marker) or 3 after a stderr
    breadcrumb. Order matters: --head/-run-root/-iteration shape refusals fire first (AC7), then
    the step1-binding-at-N short-circuit, then the diff-authorized checklist skip (which needs no
    binding — AC10), then the iter-<N>.json shadow promotion that grades the shadow binding at N,
    else N-1; every arm that selects no binding ends at `_refuse_no_binding`, which admits the
    grader's remaining no-binding pass before refusing."""
    if getattr(args, "head", None) is not None:
        sys.stderr.write(
            "loop-verdict-marker: --head must not be supplied with --entry latest (the selected "
            "binding's own recorded head is graded) — no marker emitted\n")
        return 3
    root = getattr(args, "run_root", None)
    if not root:
        sys.stderr.write(
            "loop-verdict-marker: --entry latest requires a non-empty --run-root — no marker "
            "emitted\n")
        return 3
    if getattr(args, "iteration", None) is None:
        sys.stderr.write(
            "loop-verdict-marker: --entry latest requires --iteration — no marker emitted\n")
        return 3
    gate, err = _load_review_evidence_gate()
    if gate is None:
        sys.stderr.write(
            f"loop-verdict-marker: could not load the review-evidence grader ({err}) — no marker "
            "emitted\n")
        return 3
    n = args.iteration
    # 1. A step1 binding at N grades that binding, exactly as the loop stamps a non-shadow final
    #    iteration today (a diff-authorized skip inside the grade still passes with no evidence).
    if _binding_file_exists(root, "step1", n):
        return _grade_selected_latest(args, gate, "step1", n)
    # 2. No step1 binding at N. The grader's entry-independent owed precheck passes a
    #    diff-authorized checklist skip with no binding, so run it BEFORE reading iter-<N>.json —
    #    a skip run marks without ever consulting the promotion record (AC10). It settles only
    #    the skip arm; the other no-binding pass (the phase-log record) needs the selection to
    #    have failed first, so it is consulted in `_refuse_no_binding` at each refusal below.
    #    A binding graded below re-runs this precheck inside `grade_active_entry_offline`; the
    #    repeat is deliberate, because that public grader is also reached without this function
    #    (`check-evidence --entry …`) and must keep its own skip arm. Idempotent and offline.
    owed_token, owed_detail, _disproof = gate._offline_owed_check(root)
    if owed_token is not None:
        if owed_token.startswith("pass "):
            return None
        detail = "".join(owed_detail) if isinstance(owed_detail, list) else str(owed_detail)
        _evidence_missing_stderr(root, detail)
        return 3
    # 3. Checklist owed and no step1 binding at N: consult iter-<N>.json for a shadow promotion.
    prov, reason = _read_promotion_provenance(root, n)
    if reason is not None:
        return _refuse_no_binding(
            gate, root,
            f"loop-verdict-marker: iter-{n}.json {_ITER_REASON_TEXT[reason]} — the step1 binding "
            f"at iteration {n} is absent and no shadow promotion could be read; no marker "
            "emitted\n")
    if prov not in _PROMOTING_PROVENANCE:
        return _refuse_no_binding(
            gate, root,
            f"loop-verdict-marker: iter-{n}.json records promotion_provenance={prov!r}, not a "
            f"shadow promotion, and no step1 binding exists at iteration {n} — no marker "
            "emitted\n")
    # A shadow promotion: grade the shadow binding at N, else the shadow binding at N-1.
    if _binding_file_exists(root, "shadow", n):
        return _grade_selected_latest(args, gate, "shadow", n)
    if _binding_file_exists(root, "shadow", n - 1):
        return _grade_selected_latest(args, gate, "shadow", n - 1)
    return _refuse_no_binding(
        gate, root,
        f"loop-verdict-marker: iter-{n}.json records a shadow promotion but no shadow binding "
        f"exists at iteration {n} or {n - 1} — no marker emitted\n")


def _cmd_compose(args: argparse.Namespace) -> int:
    # `--entry latest` (issue #676): select and grade the binding this stamp covers before
    # composing. Handled ahead of the run-root guard below because its --run-root/-iteration/
    # --head shape refusals (AC7) must fire even when --run-root is absent or empty, rather than
    # being masked by the else-arm's generic no-run-root refusal below.
    if getattr(args, "entry", None) == "latest":
        rc = _compose_latest_gate(args)
        if rc is not None:
            return rc
    # Run-root evidence gate (issue #193 AC5): when a run root is supplied, refuse to compose
    # a verdict marker on a non-pass grade — no marker, a stderr diagnostic, exit 3, the same
    # shape as the unmappable-result refusal below.
    elif getattr(args, "run_root", None):
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
            _evidence_missing_stderr(args.run_root, detail)
            return 3
    else:
        # No --run-root and not `--entry latest` (issue #727): compose has no ungraded form.
        # Refuse before any result/coverage handling — the same shape as the refusals above
        # (stderr breadcrumb, exit 3, no marker) — so a review that owed the checklist/verification
        # phases but never ran them cannot be stamped clean. Checked ahead of _normalize_result so a
        # bad --result with no --run-root reports the run-root refusal, not the result one.
        sys.stderr.write(
            "loop-verdict-marker: compose requires --run-root (the loop's held review run "
            "root) so the checklist-artifact and verification-artifact evidence is graded "
            "before a marker is composed — no --run-root given, no marker emitted\n")
        return 3
    if getattr(args, "run_root", None):
        gate_detail = _unrecovered_gate(args.run_root)
        if gate_detail is not None:
            _evidence_missing_stderr(args.run_root, gate_detail)
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
        elif coverage == "skipped":
            print(f"{ROUTE_CLEAN_SHADOW_SKIPPED} {result}")
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
        gate_detail = _unrecovered_gate(args.run_root, exclude=(entry, iteration))
        if gate_detail is not None:
            outcome, detail = "unestablished", gate_detail
        else:
            outcome, detail = _classify_active_entry_grade(args.run_root, entry, iteration, head)
            if entry in _ACTIVE_ENTRIES and iteration >= 1:
                err = _write_grade_record(args.run_root, entry, iteration, head, outcome, detail)
                if err is not None:
                    # An unrecorded PASS cannot clear an earlier non-pass record of this entry.
                    detail += f"; grade record unwritable ({err})"
                    if outcome == "pass":
                        outcome = "unestablished"
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
        "own producer evidence. Supply --entry, --iteration and --head together. compose also "
        "accepts `latest` (issue #676): supply --iteration only (no --head) and the helper "
        "selects the binding to grade.")
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
        help="required (issue #727): the loop's held review run root. compose refuses "
        "(exit 3, no marker) unless the run root passes the offline review-evidence grade; "
        "there is no ungraded form.",
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

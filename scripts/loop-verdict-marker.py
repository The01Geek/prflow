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

Six subcommands, all stdlib-only and needing no config / gh. `check-evidence` and
`render-exit` grade a run directory through review-evidence-gate
(grade_run_root_offline / grade_iteration_offline), which shells out to `git apply --numstat`
on that read-only path, and `render-exit` also runs `git rev-parse HEAD`; `continue-run` (issue #893) runs `git rev-parse HEAD`, may reach origin
twice (`git ls-remote`, then `git fetch` of the telemetry branch), and writes `iter-<k>.json`
copies into the run root. `lib/iter-record.schema.json` defines the iteration record:
`install-record` checks its listed keywords, treating integer fields as JSON integer tokens;
`build-deferrals` and `continue-run`
warn on a top-level key outside it. `read`, `build-deferrals` and `install-record` reach no git:

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

  check-evidence --run-root DIR [--contract 2 --iteration N]
      Grades DIR through review-evidence-gate and prints one structured line. With
      --contract 2 --iteration N, it grades only iteration N's own evidence and requires no
      Phase 3 block file, as render-exit does. It emits NO verdict marker (issue #426).
      The fix loop's `entry-close` runs it after
      every engine entry, before the verdict is consumed. Output:

        PASS <run-root> <grade>           0  the run root passes the evidence grade
        FAIL <run-root> <grade>           3  a graded evidence failure
        UNESTABLISHED <run-root> <detail> 3  ungradeable: an unavailable/faulty grader,
                                             an unestablished grade, or an unknown outcome

      FAIL and UNESTABLISHED are distinguished by the token, not the exit code;
      both are non-pass and exit 3. A grader import/read/parse/internal failure is
      UNESTABLISHED, never PASS (fail-closed). Malformed arguments keep argparse's
      exit-2 behavior.

  continue-run --run-root DIR --max-iterations N --telemetry-branch NAME
      Mid-loop continuation for a resumed implement run (issue #893). Resolves HEAD
      itself, derives the slug from DIR's parent, and looks for a prior run of that slug
      whose highest well-formed `iter-<N>.json` binds HEAD. Its bound head is
      `iteration_head` when present (issue #1537), else `fix_commit_sha` when it is a
      40-hex string, else (absent or null) `diff_produced_at_head` under the same test;
      any other shape of the field consulted excludes the record, as does a record carrying
      `synthesized: true` or `source: "review"` (no loop state to resume), at any N. A bound head binds when it is a commit here and
      equals HEAD or is met by HEAD's first-parent chain through merge commits only (base
      merges). On-disk siblings under DIR's parent are
      consulted first (never DIR itself); only when none binds is `.prflow/logs/review/
      <slug>/` on NAME read, fetched from origin into `refs/remotes/origin/NAME`. A tie at
      the same N takes the run id that sorts last. It copies `iter-1.json`..`iter-<N>.json`
      from that run into DIR, each stamped `restored_from: "<run id>"`, never overwriting
      a file already present and never a record above N or any other artifact; each restored
      record's top-level key outside the schema is named on stderr. Prints exactly one line:

        continue-run: restored iteration=<N> source=<run-id> head=<bound head>   0
        continue-run: none reason=<token>                                 1
        continue-run: unestablished reason=<token>                        2

      `none` is an established absence (no prior run, no binding or well-formed record,
      N+1 above --max-iterations, no such branch on origin); `unestablished` is an
      unanswered question (git failed, HEAD unresolved, a telemetry query/fetch failure
      with no on-disk record binding, an unwritable run root, `ancestry-unreadable` when an
      ancestry read fails or prints an unparseable, empty or disconnected result). An argparse error also
      exits 2 with no `continue-run:` line. The loop continues at N+1 only on `restored`.

  build-deferrals --run-root DIR --iteration N
      Writes DIR/deferrals.json from the `fix_decisions` of iter-1..N.json: every
      `claim-quality` / `out-of-scope` / `already-tracked` row (a `criterion conflict:` row
      excluded) and every `settled-by-disclosure` row that no matching row in a later iteration
      supersedes. Within one iteration, only a later `applied`, `pushed_back` or deferral row
      supersedes it. Two rows match when their findings share
      `defect_signature` file and kind with overlapping line ranges (a missing range overlaps
      any), else when their checklist items (the Step 1 return's checklist, else the record's)
      share a `claim_signature`, else when their `source_file` and `claim_text` are equal; ids
      are per record and never compared. A row joins a finding of its own record by a
      string `finding_id`: a `phase3_findings` row carrying that id, else `F-<n>` by position n
      or `S-<n>` by position in `shadow.phase3_findings`; a joined row takes the finding's
      agent, severity, `defect_signature` file/line_range/kind, summary and symbol (the first
      backticked span of the description), any other its `source_file` and `claim_text`. Each
      entry and `rejected` row names its `iter`. The widens-surface guard uses match-deferrals.py's
      diff-hunk parser and ±10-line tolerance over DIR/diff.patch (absent: the newest retained
      `evidence-<entry>/iter-<k>/diff.patch`): a row whose file has a hunk
      overlapping its line range (no line range: any hunk in the file), any row when the guard
      cannot run (`guard-not-run`: no readable diff, no parser or a parser fault; the cause is a
      warning ending `not carried`), a
      row with no file, or a foreclosure without a `{path, phrase}` disclosure is left out and
      listed in `rejected` with its `reason`. No surviving row removes the manifest
      (omit-on-zero). An unreadable earlier record, a `fix_decisions` or record `checklist` that
      is not an array or a `fix_decisions` row that is not an object, an unusable Step 1 return (its record's checklist matched instead), a
      retained diff read in place of DIR/diff.patch, or a record's top-level key outside the schema
      (ending `not carried` when its object, or an object in its array, carries `skip_category`) is a
      `warnings` entry. Prints
      {"status":"ok","path":<manifest|null>,"written","rejected","warnings"} (exit 0); an
      unusable iter-N.json or a failed write is status "error" (exit 1) and removes an earlier
      manifest (one it cannot remove is named in the `reason`); a bad --iteration exit 2.

  render-exit --run-root DIR --iteration N --result "<loop result>"
              [--shadow-dispatch attempted|never|unestablished] [--not-verified GATE]...
      Loop Exit's mechanical half over iter-1..N.json. Selects the shadow evidence (the final
      record's `shadow_skipped` when it has no `shadow` block, honored only on a fresh
      iteration 1, else the latest `shadow` block), requires its recorded head to prefix HEAD
      and, for a clean approve result, a block with no `promoted_to_iter_next` and zero new
      Critical and Important findings, renders the `{shadow status}` phrase, and writes
      DIR/loop-exit-coverage.md (the `## Coverage` section: the shadow sentence, then each
      checklist FAIL and INCONCLUSIVE item of the last non-promoted iteration that ran Phase
      1+2, read from its `engine-return-step1-iter-<k>.json`, else its record's `checklist`; a
      FAIL that iteration applied a fix to is marked `(fix applied)`; an iteration whose items
      cannot be read, its record included, gets a `not listed` line instead). A clean approve result
      whose final record holds no `park_calibration` object with an `evidence_comparisons`
      array is listed in `incomplete` and renders not verified. The --not-verified GATEs,
      joined with "and", add a Coverage line after the shadow sentence and leave the shadow
      status and the marker's coverage to the shadow. The marker grades the most recent entry's retained
      `evidence-<entry>/iter-<k>/` copy: a shadow copy that does not pass is passed over with a
      warning, the most recent step1 copy decides, and only a promoted iteration is walked back
      past for want of one. Prints {"status":"ok"|"evidence-missing","marker":<line|null>,
      "shadow_status","coverage_path","graded_iteration","graded_entry","incomplete",
      "warnings"} (exit 0; a non-pass grade is "evidence-missing" with no marker); an
      unwritable run root is "error" (exit 1); a bad --iteration or an unmappable --result
      is "error" (exit 2).

  install-record --run-root DIR --iteration N
      Installs DIR/iter-<N>.json.draft over DIR/iter-<N>.json with os.replace. The draft is
      refused when it starts with a UTF-8 BOM, is not UTF-8 JSON parsing to an object, repeats a key, has an `iter` other
      than the integer N, or fails the schema; and, when the installed iter-<N>.json is not
      older than DIR/loop-setup.json (one it cannot stat: always), when it lacks a top-level
      key the installed record holds, or holds fewer rows of a top-level array with a given
      `finding_id` (else `id`, null counted) value. An installed record that cannot be read or
      does not parse to an object is not compared (a warning). Prints {"status":"ok","path","warnings"} (exit 0),
      {"status":"refused","path":<draft>,"violations":[{"path":<JSON path>,"message"}]} (exit 1,
      neither file changed), {"status":"error","reason"} for a missing or unreadable draft, an
      unreadable schema or a failed replace (which adds "warnings") (exit 1), or a bad
      --iteration (exit 2).
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from path_forms import posix_path


def _force_utf8_streams():
    """Force stdin/stdout/stderr to UTF-8, output to LF-only (native Windows writes CRLF
    into the shell caller's value). Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream, _kw in ((sys.stdin, {}), (sys.stdout, {"newline": "\n"}),
                         (sys.stderr, {"newline": "\n"})):
        try:
            _stream.reconfigure(encoding="utf-8", **_kw)
        except (AttributeError, TypeError, ValueError, OSError):
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


def _load_sibling(name: str, filename: str):
    """(module, None) or (None, reason) for a sibling script loaded by path relative to this
    installed file (a hyphenated filename has no plain import). Loading runs the sibling's module
    scope: its stderr breadcrumbs pass through, and its sys.exit is the reason."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None, f"no import spec for {filename}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except (Exception, SystemExit) as e:  # an import fault (or its sys.exit) is a reason, never a crash
        return None, f"{type(e).__name__}: {e}"


def _classify_grade_result(get_token) -> tuple[str, str]:
    """Load the grader and classify a `(token, detail)` grade three ways (issue #426): an
    unavailable grader, a grader fault, or an unrecognized grade token is `unestablished` —
    never `pass` and never `fail` — so an ungradeable run is told apart from a graded failure
    and a grader fault can never become a pass. `get_token(gate)` names which offline grade
    to run (run-wide or per-iteration), so both share this one invocation/classification path."""
    gate, err = _load_sibling("loop_review_evidence_gate", "review-evidence-gate.py")
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


def _classify_run_root_grade(run_root: str, iteration: int | None = None) -> tuple[str, str]:
    """Grade `run_root` offline: iteration `iteration`'s own evidence through
    review-evidence-gate.grade_iteration_offline when given, else the run-wide
    grade_run_root_offline (issue #426)."""
    if iteration is not None:
        return _classify_grade_result(
            lambda gate: gate.grade_iteration_offline(run_root, iteration))
    return _classify_grade_result(lambda gate: gate.grade_run_root_offline(run_root))


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
    iteration = getattr(args, "iteration", None)
    outcome, detail = _classify_run_root_grade(args.run_root, iteration)
    # `detail` can carry a grader exception message with embedded CR/LF; flatten it so the
    # docstring's "one structured line" holds and the reader's splitlines()[0] sees the whole
    # record, not a truncated first physical line.
    detail = detail.replace("\r", " ").replace("\n", " ")
    sys.stdout.write(f"{CHECK_EVIDENCE_TOKENS[outcome]} {args.run_root} {detail}\n")
    return 0 if outcome == "pass" else 3


# ── continue-run (issue #893): the mid-loop continuation reader; contract in the module docstring ──

_ITER_FILE_RE = re.compile(r"\Aiter-([1-9][0-9]*)\.json\Z")
_SHA40_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")   # a 40-hex sha in either case; compared lowercased
_TELEMETRY_REVIEW_PREFIX = ".prflow/logs/review/"
_MISSING = object()


def _git(args: list[str], raw: bool = False) -> tuple[int | None, str | bytes, str]:
    """(rc, stdout, stderr) of a git call in the caller's cwd; rc None when git could not run.
    `raw` returns stdout as bytes (a blob read); stderr is always text."""
    try:
        proc = subprocess.run(["git", *args], capture_output=True,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except OSError as e:
        return None, b"" if raw else "", str(e)
    out = proc.stdout if raw else proc.stdout.decode("utf-8", "replace")
    return proc.returncode, out, proc.stderr.decode("utf-8", "replace")


def _field_shape(value) -> str:
    """The breadcrumb word for a value that is not a 40-hex sha (the CLAUDE.md matrix:
    object/array/scalar/valid-falsy/missing/wrong-type)."""
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, str):
        if value == "":
            return "empty-string"
        if re.fullmatch(r"[0-9a-fA-F]+", value):
            return "short-sha" if len(value) < 40 else "not-a-40-hex-sha"
        return "not-a-40-hex-sha"
    return "wrong-type"


def _bound_head(obj: dict) -> tuple[str | None, str]:
    """The head an iteration record binds to, or (None, reason). `iteration_head` (the head
    after Step 3.5's last commit) binds when present; absent, `fix_commit_sha` binds when it
    is a 40-hex string; when that is absent or JSON null (a no-fix iteration, written in both
    shapes) `diff_produced_at_head` binds under the same test. Any other shape of the field
    consulted excludes the record — a short sha, `0`, `""`, null `iteration_head`, an array, an
    object — because the continuation would otherwise carry a prior attempt's state onto a
    head it never reviewed."""
    ih = obj.get("iteration_head", _MISSING)
    if ih is not _MISSING:
        if isinstance(ih, str) and _SHA40_RE.match(ih):
            return ih.lower(), ""
        return None, f"iteration_head {_field_shape(ih)}"
    fcs = obj.get("fix_commit_sha", _MISSING)
    if fcs is _MISSING or fcs is None:
        dph = obj.get("diff_produced_at_head", _MISSING)
        if isinstance(dph, str) and _SHA40_RE.match(dph):
            return dph.lower(), ""
        return None, f"fix_commit_sha {_field_shape(fcs)} and diff_produced_at_head {_field_shape(dph)}"
    if isinstance(fcs, str) and _SHA40_RE.match(fcs):
        return fcs.lower(), ""
    return None, f"fix_commit_sha {_field_shape(fcs)}"


def _parse_iter_record(raw: bytes, iteration: int) -> tuple[dict | None, str]:
    """(record, '') for a JSON object whose `iter` equals the filename's number, else
    (None, reason) — every non-object shape refuses rather than being read."""
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return None, "not valid JSON"
    except RecursionError:
        return None, "nested too deeply to parse"
    if not isinstance(obj, dict):
        return None, f"is not a JSON object ({'string' if isinstance(obj, str) else _field_shape(obj)})"
    why = _iter_mismatch(obj, iteration)
    return (None, why) if why else (obj, "")


def _iter_mismatch(obj: dict, iteration: int) -> str:
    """'' when the record's `iter` is the integer `iteration` (never a boolean), else why."""
    it = obj.get("iter")
    if isinstance(it, bool) or not isinstance(it, int) or it != iteration:
        return f"iter field {it!r} does not equal the filename's {iteration}"
    return ""


# ── the iteration-record schema (issue #2038) ────────────────────────────────────────────

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "lib", "iter-record.schema.json")
_SCHEMA_CACHE: list = []
_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_PLAIN_KEY_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _load_schema() -> tuple[dict | None, str]:
    """(the schema, '') or (None, why); a top level without an object `properties` is unusable."""
    if not _SCHEMA_CACHE:
        try:
            with open(_SCHEMA_PATH, "rb") as fh:
                schema = json.loads(fh.read())
            why = "" if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) \
                else "it holds no top-level properties object"
        except OSError as e:
            schema, why = None, f"unreadable ({_os_reason(e)})"
        except (ValueError, UnicodeError, RecursionError) as e:
            schema, why = None, f"not JSON ({type(e).__name__})"
        _SCHEMA_CACHE.append((None, f"iteration-record schema {why}") if why else (schema, ""))
    return _SCHEMA_CACHE[0]


def _json_type(value) -> str:
    return next((name for name, test in _JSON_TYPES.items() if name != "number" and test(value)),
                "number")


def _key_path(path: str, key: str) -> str:
    return f"{path}.{key}" if _PLAIN_KEY_RE.match(key) else f"{path}[{json.dumps(key)}]"


def _unknown_key_message(key: str) -> str:
    return (f"top-level key {key} is not in the iteration-record schema; pushback rows belong in "
            'fix_decisions with "decision": "pushed_back", consumer data in verification_evidence')


def _schema_violations(value, schema: dict, path: str, out: list) -> None:
    """Append {path, message} for each way `value` breaks `schema` (keywords: type, properties,
    required, additionalProperties, items, pattern)."""
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        if not any(_JSON_TYPES.get(name, lambda v: False)(value) for name in names):
            out.append({"path": path, "message": f"is {_json_type(value)}, expected {' or '.join(names)}"})
            return
    if isinstance(value, str) and "pattern" in schema and not re.fullmatch(schema["pattern"], value):
        out.append({"path": path, "message": f"does not match pattern {schema['pattern']}"})
    if isinstance(value, dict):
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key in schema.get("required", ()):
            if key not in value:
                out.append({"path": _key_path(path, key), "message": "required key is missing"})
        for key, item in value.items():
            if isinstance(props.get(key), dict):
                _schema_violations(item, props[key], _key_path(path, key), out)
            elif key not in props and schema.get("additionalProperties") is False:
                out.append({"path": _key_path(path, key), "message": _unknown_key_message(key)})
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            _schema_violations(item, schema["items"], f"{path}[{i}]", out)


def _unknown_top_keys(record: dict) -> tuple[list[str], str]:
    """(the record's top-level keys outside the schema's properties, '') or ([], the warning)."""
    schema, why = _load_schema()
    if schema is None:
        return [], f"{why}; unknown top-level keys not checked"
    return [key for key in record if key not in schema["properties"]], ""


def _id_counts(rows) -> dict:
    """{(id field, JSON id value): count} over the object rows carrying `finding_id`, else `id`."""
    counts: dict = {}
    for row in _rows(rows):
        field = "finding_id" if "finding_id" in row else "id" if "id" in row else None
        if field:
            ident = (field, json.dumps(row[field], sort_keys=True, ensure_ascii=False))
            counts[ident] = counts.get(ident, 0) + 1
    return counts


def _held_violations(draft: dict, installed: dict, name: str, props: dict) -> list:
    """What the draft drops of the installed record: a top-level key, or id-bearing rows."""
    out = []
    for key, held in installed.items():
        path = _key_path("$", key)
        if key not in draft and key not in props:
            out.append({"path": path, "message": f"the installed {name} holds {key}, a key outside "
                        "the iteration-record schema, so no draft can install over it; keep the "
                        "draft without it: no edit clears this refusal, which counts toward the "
                        "direct-Write fallback"})
            continue
        if key not in draft:
            out.append({"path": path, "message": f"the installed {name} holds {key}; a rewrite "
                                                 "keeps every schema field already written"})
        if not isinstance(held, list):
            continue
        have = _id_counts(draft.get(key))
        for (field, ident), count in _id_counts(held).items():
            missing = count - have.get((field, ident), 0)
            if missing > 0:
                out.append({"path": path, "message": f"drops {missing} row(s) with {field} {ident} "
                                                     f"that the installed {name} holds"})
    return out


def _no_duplicates(pairs: list, duplicates: list) -> dict:
    """json.loads' object hook: the object, with each repeated key appended to `duplicates`."""
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            duplicates.append(key)
        obj[key] = value
    return obj


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON number: {value}")


def _cmd_install_record(args: argparse.Namespace) -> int:
    if args.iteration < 1:
        _emit_json({"status": "error", "reason": "--iteration must be a positive integer"})
        return 2
    n = args.iteration
    target = os.path.join(args.run_root, f"iter-{n}.json")
    draft = target + ".draft"
    try:
        with open(draft, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        _emit_json({"status": "error", "reason": f"iter-{n}.json.draft is missing; nothing installed"})
        return 1
    except OSError as e:
        _emit_json({"status": "error", "reason": f"iter-{n}.json.draft unreadable ({_os_reason(e)})"})
        return 1
    schema, why = _load_schema()
    if schema is None:
        _emit_json({"status": "error", "reason": f"{why}; nothing installed"})
        return 1
    violations, warnings = [], []
    if raw.startswith(b"\xef\xbb\xbf"):
        violations.append({"path": "$", "message": "starts with a UTF-8 BOM; write it without one"})
    duplicates: list = []
    try:
        obj = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_json_constant,
            object_pairs_hook=lambda pairs: _no_duplicates(pairs, duplicates))
    except (ValueError, UnicodeError, RecursionError) as e:
        violations.append({"path": "$", "message": f"is not valid UTF-8 JSON ({type(e).__name__}: {e})"})
        obj = _MISSING
    violations += [{"path": "$", "message": f"repeats key {key} within one object (at any depth); "
                                                "JSON keeps only its last value"}
                   for key in duplicates]
    if obj is not _MISSING and not isinstance(obj, dict):
        violations.append({"path": "$", "message": f"is a JSON {_json_type(obj)}, not an object"})
    if isinstance(obj, dict):
        _schema_violations(obj, schema, "$", violations)
        mismatch = _iter_mismatch(obj, n)
        if mismatch and not any(v["path"] == "$.iter" for v in violations):
            violations.append({"path": "$.iter", "message": mismatch})
        installed = _compared_record(target, os.path.join(args.run_root, "loop-setup.json"),
                                     warnings)
        if installed is not None:
            violations += _held_violations(obj, installed, f"iter-{n}.json", schema["properties"])
    if violations:
        _emit_json({"status": "refused", "path": posix_path(draft), "violations": violations})
        return 1
    try:
        os.replace(draft, target)
    except OSError as e:
        _emit_json({"status": "error", "reason": f"iter-{n}.json not installed ({_os_reason(e)})",
                    "warnings": warnings})
        return 1
    _emit_json({"status": "ok", "path": posix_path(target), "warnings": warnings})
    return 0


def _compared_record(target: str, setup: str, warnings: list) -> dict | None:
    """The installed record a draft must keep, or None: absent, older than loop-setup.json (an
    earlier invocation's), or unreadable or not a JSON object (named in `warnings`). A
    loop-setup.json it cannot stat leaves the record compared."""
    name = os.path.basename(target)
    try:
        with open(target, "rb") as fh:
            raw = fh.read()
            installed_mtime = os.fstat(fh.fileno()).st_mtime_ns
    except FileNotFoundError:
        return None
    except OSError as e:
        warnings.append(f"the installed {name} is unreadable ({_os_reason(e)}); not compared")
        return None
    try:
        if installed_mtime < os.stat(setup).st_mtime_ns:
            return None
    except OSError:
        pass  # no usable loop-setup.json: compare, the stricter direction
    try:
        installed = json.loads(raw, parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        installed = None
    if not isinstance(installed, dict):
        warnings.append(f"the installed {name} is not a JSON object; not compared")
        return None
    return installed


def _chain_binds(bound: str, head: str) -> tuple[bool | None, str]:
    """Whether `bound` binds `head`: (True, ''), (False, why) or (None, why) when a git read
    did not answer. It binds when equal to HEAD, or when
    HEAD's first-parent chain meets it through merge commits only (base merges); a one-parent
    commit on that chain is new work the prior iteration never reviewed."""
    if bound == head:
        return True, ""
    rc, out, err = _git(["rev-parse", "--verify", "--quiet", f"{bound}^{{commit}}"])
    if rc == 1:
        return False, f"bound head {bound[:12]} is not a commit here"
    if rc != 0 or out.strip().lower() != bound:
        return None, f"rev-parse --verify {bound[:12]} rc={rc}: {(err or out).strip()}"
    rc, _, err = _git(["merge-base", "--is-ancestor", bound, head])
    if rc == 1:
        return False, f"bound head {bound[:12]} is not an ancestor of HEAD"
    if rc != 0:
        return None, f"merge-base --is-ancestor {bound[:12]} rc={rc}: {(err or '').strip()}"
    rc, out, err = _git(["rev-list", "--first-parent", "--parents", f"{bound}..{head}"])
    if rc != 0:
        return None, f"rev-list --first-parent {bound[:12]}..HEAD rc={rc}: {(err or '').strip()}"
    rows = [line.lower().split() for line in out.splitlines()]
    if not rows or not all(row and all(_SHA40_RE.match(s) for s in row) for row in rows):
        return None, f"rev-list --first-parent {bound[:12]}..HEAD printed an unparseable line"
    expected = head
    for row in rows:
        if row[0] != expected:
            return None, f"rev-list --first-parent {bound[:12]}..HEAD printed a disconnected chain"
        expected = row[1] if len(row) > 1 else ""
    if expected != bound:
        return False, f"bound head {bound[:12]} is not on HEAD's first-parent chain"
    one_parent = [row[0] for row in rows if len(row) < 3]
    if one_parent:
        return False, f"bound head {bound[:12]} has one-parent commit {one_parent[-1][:12]} above it"
    return True, ""


class _Source:
    """One prior-run source: the on-disk siblings or the telemetry branch. `records` maps
    run id -> {iteration -> raw bytes}; `seen` counts every iter-<k>.json offered, readable or
    not; `well_formed` those that parsed and bound to some head; `candidates` holds
    (iteration, run_id, bound head) triples that bind the current head; `unreadable` names
    the first ancestry read that did not answer."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.records: dict[str, dict[int, bytes]] = {}
        self.seen = 0
        self.well_formed = 0
        self.candidates: list[tuple[int, str, str]] = []
        self.unreadable = ""

    def consider(self, run_id: str, iteration: int, raw: bytes | None, head: str,
                 read_err: str = "") -> None:
        label = f"{self.name} {run_id}/iter-{iteration}.json"
        self.seen += 1
        if raw is None:
            sys.stderr.write(f"continue-run: {label} excluded: unreadable ({read_err})\n")
            return
        self.records.setdefault(run_id, {})[iteration] = raw
        obj, reason = _parse_iter_record(raw, iteration)
        reason = reason or _unresumable(obj)
        if reason:
            sys.stderr.write(f"continue-run: {label} excluded: {reason}\n")
            return
        bound, reason = _bound_head(obj)
        if bound is None:
            sys.stderr.write(f"continue-run: {label} excluded: {reason}\n")
            return
        self.well_formed += 1
        if self.unreadable:
            return
        binds, reason = _chain_binds(bound, head)
        if binds is None:
            sys.stderr.write(f"continue-run: {label}: {reason}\n")
            self.unreadable = reason
        elif binds:
            self.candidates.append((iteration, run_id, bound))
        else:
            sys.stderr.write(f"continue-run: {label} excluded: {reason}\n")

    def best(self) -> tuple[int, str, str] | None:
        """The highest bound iteration; on a tie the run id that sorts last."""
        return max(self.candidates) if self.candidates else None


def _os_reason(e: OSError) -> str:
    """An OSError's reason without its filename (whose repr carries host-form separators):
    its strerror, else a message-only error's text, else the exception type name."""
    return e.strerror or (str(e) if e.filename is None and len(e.args) == 1 else "") or type(e).__name__


def _scan_disk(review_dir: str, own_run_id: str, head: str) -> _Source | None:
    """Every sibling run directory under `review_dir` except this run's own; None when the
    slug directory itself cannot be listed (an unestablished answer, never an empty one)."""
    source = _Source("on-disk")
    try:
        entries = sorted(os.listdir(review_dir))
    except FileNotFoundError:
        return source
    except OSError as e:
        sys.stderr.write(f"continue-run: cannot list {posix_path(review_dir)}: {_os_reason(e)}\n")
        return None
    for run_id in entries:
        run_dir = os.path.join(review_dir, run_id)
        if run_id == own_run_id or not os.path.isdir(run_dir):
            continue
        try:
            names = sorted(os.listdir(run_dir))
        except OSError as e:
            sys.stderr.write(f"continue-run: cannot list on-disk {run_id}: {_os_reason(e)}\n")
            continue
        source.records.setdefault(run_id, {})
        for name in names:
            m = _ITER_FILE_RE.match(name)
            if not m:
                continue
            k = int(m.group(1))
            try:
                with open(os.path.join(run_dir, name), "rb") as fh:
                    raw = fh.read()
            except OSError as e:
                source.consider(run_id, k, None, head, _os_reason(e))
                continue
            source.consider(run_id, k, raw, head)
    return source


def _scan_telemetry(branch: str, slug: str, own_run_id: str, head: str) -> tuple[_Source | None, str]:
    """The prior-run records under `.prflow/logs/review/<slug>/` on the telemetry branch,
    fetched from origin. Returns (source, '') or (None, token): `none:<reason>` for an
    established absence (no such branch on origin), `unestablished:<reason>` for a query or
    fetch that did not answer — a fetch failure is never reported as an absence."""
    if not branch:
        return None, "unestablished:telemetry-branch-empty"
    rc, _, _ = _git(["check-ref-format", "--branch", branch])
    if rc is None:
        return None, "unestablished:git-failed"
    if rc != 0:
        return None, "unestablished:telemetry-branch-invalid"
    rc, _, _ = _git(["remote", "get-url", "origin"])
    if rc is None:
        return None, "unestablished:git-failed"
    if rc != 0:
        return None, "none:no-origin"        # nowhere to fetch from: the on-disk answer is complete
    rc, out, err = _git(["ls-remote", "--heads", "origin", branch])
    if rc is None:
        return None, "unestablished:git-failed"
    if rc != 0:
        sys.stderr.write(f"continue-run: git ls-remote origin {branch} failed: {err.strip()}\n")
        return None, "unestablished:telemetry-query-failed"
    if not out.strip():
        return None, "none:no-telemetry-branch"
    tracking = f"refs/remotes/origin/{branch}"
    rc, _, err = _git(["fetch", "-q", "--no-tags", "origin", f"+{branch}:{tracking}"])
    if rc != 0:
        sys.stderr.write(f"continue-run: git fetch origin {branch} failed: {(err or '').strip()}\n")
        return None, "unestablished:telemetry-fetch-failed"
    rc, out, _ = _git(["rev-parse", "--verify", "--quiet", f"{tracking}^{{commit}}"])
    commit = out.strip().lower()
    if rc != 0 or not _SHA40_RE.match(commit):
        return None, "unestablished:telemetry-ref-unresolved"
    prefix = f"{_TELEMETRY_REVIEW_PREFIX}{slug}/"
    rc, out, err = _git(["-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", commit,
                         "--", prefix])
    if rc != 0:
        sys.stderr.write(f"continue-run: git ls-tree {tracking} failed: {(err or '').strip()}\n")
        return None, "unestablished:telemetry-tree-unreadable"
    source = _Source("telemetry")
    for path in out.splitlines():
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split("/")
        if len(parts) != 2:
            continue                      # `.corrections/` archives and deeper paths
        run_id, name = parts
        if run_id == own_run_id:
            continue
        source.records.setdefault(run_id, {})
        m = _ITER_FILE_RE.match(name)
        if not m:
            continue
        k = int(m.group(1))
        rc, blob, err = _git(["show", f"{commit}:{path}"], raw=True)
        if rc != 0:
            source.consider(run_id, k, None, head, err.strip())
            continue
        source.consider(run_id, k, blob, head)
    return source, ""


def _unresumable(obj: dict) -> str:
    """Why a record holds no loop state to resume from, else ''."""
    if obj.get("synthesized") is True:
        return "a synthesized record (synthesized: true)"
    if obj.get("source") == "review":
        return 'a standalone review record (source: "review")'
    return ""


def _restore(source: _Source, anchor: tuple[int, str, str], run_root: str) -> str | None:
    """Copy iter-1..N from the anchor run into `run_root`, each stamped `restored_from`,
    never overwriting a file already there. Returns an error string when the run root
    itself cannot be written; a lower record that is absent, malformed or unresumable (a
    synthesized or standalone review record) is skipped with a
    breadcrumb and named again in one summary line, so a non-contiguous restore is legible
    on stderr while the stdout line keeps its closed shape."""
    n, prior, _ = anchor
    try:
        os.makedirs(run_root, exist_ok=True)
    except OSError as e:
        return f"cannot create {run_root}: {e}"
    skipped: list[int] = []
    schema_warned = False
    for k in range(1, n + 1):
        raw = source.records.get(prior, {}).get(k)
        dst = os.path.join(run_root, f"iter-{k}.json")
        if raw is None:
            sys.stderr.write(f"continue-run: {source.name} {prior}/iter-{k}.json absent; not restored\n")
            skipped.append(k)
            continue
        if os.path.exists(dst):
            sys.stderr.write(f"continue-run: {dst} already present; not overwritten\n")
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            obj = None
        why = _unresumable(obj) if isinstance(obj, dict) else "not a JSON object"
        if why:
            sys.stderr.write(f"continue-run: {source.name} {prior}/iter-{k}.json is {why}; not restored\n")
            skipped.append(k)
            continue
        obj["restored_from"] = prior
        try:
            with open(dst, "wb") as fh:
                fh.write((json.dumps(obj, indent=2) + "\n").encode("utf-8"))
        except OSError as e:
            return f"cannot write {dst}: {e}"
        unknown, schema_why = _unknown_top_keys(obj)
        if schema_why and not schema_warned:
            sys.stderr.write(f"continue-run: {schema_why}\n")
            schema_warned = True
        for key in unknown:
            sys.stderr.write(f"continue-run: {source.name} {prior}/iter-{k}.json top-level key {key} "
                             "is outside the iteration-record schema; restored as written\n")
    if skipped:
        sys.stderr.write(f"continue-run: restored range 1..{n} from {prior} is non-contiguous: "
                         f"iteration(s) {','.join(map(str, skipped))} not restored\n")
    return None


def _cmd_continue_run(args: argparse.Namespace) -> int:
    """Print exactly one `continue-run:` line (issue #893): `restored iteration=<N>
    source=<run-id> head=<sha>` (exit 0), `none reason=<token>` (exit 1) or `unestablished
    reason=<token>` (exit 2). The loop continues at N+1 only on `restored`."""
    def none(reason: str) -> int:
        sys.stdout.write(f"continue-run: none reason={reason}\n")
        return 1

    def unestablished(reason: str) -> int:
        sys.stdout.write(f"continue-run: unestablished reason={reason}\n")
        return 2

    run_root = os.path.normpath(args.run_root)
    own_run_id = os.path.basename(run_root)
    review_dir = os.path.dirname(run_root)
    slug = os.path.basename(review_dir)
    if not own_run_id or not slug or run_root in (".", "/"):
        return unestablished("run-root-shape")
    rc, out, err = _git(["rev-parse", "HEAD"])
    if rc is None:
        return unestablished("git-failed")
    head = out.strip().lower()
    if rc != 0 or not _SHA40_RE.match(head):
        sys.stderr.write(f"continue-run: git rev-parse HEAD rc={rc}: {(err or '').strip()}\n")
        return unestablished("head-unresolved")

    disk = _scan_disk(review_dir, own_run_id, head)
    if disk is None:
        return unestablished("on-disk-unlistable")
    if disk.unreadable:
        return unestablished("ancestry-unreadable")
    source, anchor = disk, disk.best()
    telemetry_token = ""
    if anchor is None:
        tele, telemetry_token = _scan_telemetry(args.telemetry_branch, slug, own_run_id, head)
        if tele is not None:
            if tele.unreadable:
                return unestablished("ancestry-unreadable")
            source, anchor = tele, tele.best()
    if anchor is None:
        if telemetry_token.startswith("unestablished:"):
            return unestablished(telemetry_token.split(":", 1)[1])
        sources = [disk] if source is disk else [disk, source]
        if not any(s.seen for s in sources):
            # No iteration record anywhere: an established telemetry absence names itself.
            return none(telemetry_token.split(":", 1)[1] if telemetry_token else "no-prior-run")
        if not any(s.well_formed for s in sources):
            return none("no-well-formed-record")
        return none("no-binding-record")
    n, prior, bound = anchor
    if n + 1 > args.max_iterations:
        sys.stderr.write(f"continue-run: {source.name} {prior} binds at iteration {n}; "
                         f"iteration {n + 1} exceeds max_iterations={args.max_iterations}\n")
        return none("cap")
    err = _restore(source, anchor, run_root)
    if err is not None:
        sys.stderr.write(f"continue-run: {err}\n")
        return unestablished("run-root-unwritable")
    sys.stdout.write(f"continue-run: restored iteration={n} source={prior} head={bound}\n")
    return 0


# ── Loop Exit: build-deferrals and render-exit; contracts in the module docstring ──────────

_DEFERRAL_CATEGORIES = ("claim-quality", "out-of-scope", "already-tracked")
_FORECLOSURE = "settled-by-disclosure"
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _emit_json(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_record(run_root: str, k: int) -> tuple[dict | None, str]:
    """(iter-<k>.json as a dict, '') or (None, why)."""
    path = os.path.join(run_root, f"iter-{k}.json")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return None, f"iter-{k}.json unreadable ({_os_reason(e)})"
    record, why = _parse_iter_record(raw, k)
    return record, why and f"iter-{k}.json {why}"


def _rows(value) -> list[dict]:
    """The object rows of a list field; anything else holds none."""
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _finding_by_id(record: dict, finding_id) -> dict | None:
    """The finding a row's id names: a `phase3_findings` row by its own finding_id, else `F-<n>`
    by position n; `S-<n>` is position n of the record's `shadow.phase3_findings`."""
    if not (isinstance(finding_id, str) and finding_id):
        return None
    rows = _rows(record.get("phase3_findings"))
    for row in rows:
        if row.get("finding_id") == finding_id:
            return row
    m = re.fullmatch(r"([FS])-([1-9][0-9]*)", finding_id)
    if m and m.group(1) == "S":
        shadow = record.get("shadow")
        rows = _rows(shadow.get("phase3_findings")) if isinstance(shadow, dict) else []
    if m and int(m.group(2)) <= len(rows):
        return rows[int(m.group(2)) - 1]
    return None


def _signature(finding: dict | None) -> tuple[str | None, str | None, list | None]:
    """A finding's `defect_signature` (file, kind, line_range); a missing or malformed part is None."""
    sig = finding.get("defect_signature") if finding else None
    sig = sig if isinstance(sig, dict) else {}
    file_ = sig.get("file") if isinstance(sig.get("file"), str) and sig.get("file") else None
    kind = sig.get("kind") if isinstance(sig.get("kind"), str) and sig.get("kind") else None
    line_range = sig.get("line_range")
    if not (isinstance(line_range, list) and len(line_range) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in line_range)
            and line_range[0] <= line_range[1]):
        line_range = None
    return file_, kind, line_range


def _record_claims(run_root: str, k: int, record: dict, warnings: list) -> dict:
    """{checklist id: claim_signature} of iteration k's checklist (the Step 1 return's, else the
    record's own); ids are numbered per checklist, so only the signature names a claim across
    records."""
    checklist, why = _return_checklist(run_root, k)
    if checklist is None:
        if why:
            warnings.append(f"{why}; iteration {k}'s record checklist matched instead")
        checklist, why = _record_checklist(record, k)
        if why:
            warnings.append(f"{why}; its claims are not matched")
    return {item.get("id"): item.get("claim_signature") for item in checklist or []
            if isinstance(item.get("id"), str) and isinstance(item.get("claim_signature"), str)
            and item.get("claim_signature")}


def _row_identity(record: dict, row: dict, claims: dict) -> tuple:
    """What a `fix_decisions` row is about: its finding's signature, its checklist item's
    claim_signature, and its own (source_file, claim_text). Ids are per record, never compared."""
    def text(key):
        value = row.get(key)
        return value if isinstance(value, str) and value else None
    fid = row.get("finding_id")
    return (_signature(_finding_by_id(record, fid)), claims.get(fid) if isinstance(fid, str) else None,
            (text("source_file"), text("claim_text")))


def _same_finding(a: tuple, b: tuple) -> bool:
    """Review Phase 3.2's identity rule — same file and kind, overlapping line_range (None
    overlaps any) — when both rows have a signature; else an equal checklist claim_signature;
    else an equal (source_file, claim_text)."""
    (fa, ka, ra), sig_a, claim_a = a
    (fb, kb, rb), sig_b, claim_b = b
    if fa and ka and fb and kb:
        return fa == fb and ka == kb and (ra is None or rb is None
                                          or (ra[0] <= rb[1] and rb[0] <= ra[1]))
    if sig_a and sig_b:
        return sig_a == sig_b
    return all(claim_a) and all(claim_b) and claim_a == claim_b


def _is_deferral(row: dict) -> bool:
    category = row.get("skip_category")
    evidence = row.get("evidence")
    if category in _DEFERRAL_CATEGORIES:
        return not (isinstance(evidence, str) and evidence.startswith("criterion conflict:"))
    return category == _FORECLOSURE


def _overlaps(hunks: list, line_range, tolerance: int) -> bool:
    start, end = line_range
    return any(h_start - tolerance <= end and h_end + tolerance >= start for h_start, h_end in hunks)


def _drop_manifest(manifest: str, reason: str) -> str:
    """Remove an earlier manifest on an error exit, so implement files none of its superseded
    deferrals; returns `reason`, extended when one remains."""
    try:
        os.remove(manifest)
    except FileNotFoundError:
        pass
    except OSError as e:
        return f"{reason}; an earlier deferrals.json remains ({_os_reason(e)})"
    return reason


def _cmd_build_deferrals(args: argparse.Namespace) -> int:
    if args.iteration < 1:
        _emit_json({"status": "error", "reason": "--iteration must be a positive integer"})
        return 2
    run_root = posix_path(args.run_root)
    entries, rejected, warnings = [], [], []
    decided = []
    for k in range(1, args.iteration + 1):
        record, why = _read_record(run_root, k)
        if record is None:
            if k == args.iteration:
                _emit_json({"status": "error",
                            "reason": _drop_manifest(os.path.join(run_root, "deferrals.json"), why)})
                return 1
            warnings.append(f"{why}; its deferrals are not carried")
            continue
        unknown, schema_why = _unknown_top_keys(record)
        if schema_why and schema_why not in warnings:
            warnings.append(schema_why)
        for key in unknown:
            held = record[key]
            misplaced = any("skip_category" in row
                            for row in _rows(held if isinstance(held, list) else [held]))
            warnings.append(f"iter-{k}.json top-level key {key} is outside the iteration-record "
                            "schema; " + ("its skip_category rows are not carried" if misplaced
                                          else "it is not read"))
        decisions = record.get("fix_decisions")
        if not isinstance(decisions, list):
            what = ("missing" if "fix_decisions" not in record else "null" if decisions is None
                    else f"a JSON {type(decisions).__name__}")
            warnings.append(f"iter-{k}.json fix_decisions is {what}, not an array; "
                            "its deferrals are not carried")
        elif len(_rows(decisions)) < len(decisions):
            warnings.append(f"iter-{k}.json fix_decisions holds "
                            f"{len(decisions) - len(_rows(decisions))} row(s) that are not "
                            "objects; those rows are not carried")
        claims = _record_claims(run_root, k, record, warnings)
        decided += [(k, record, row, _row_identity(record, row, claims))
                    for row in _rows(decisions)]
    # Same-iteration bookkeeping does not supersede a deferral; later iterations still do.
    rows = [(k, record, row, ident) for i, (k, record, row, ident) in enumerate(decided)
            if _is_deferral(row)
            and not any(_same_finding(ident, ident2)
                        and (k2 > k or row2.get("decision") in ("applied", "pushed_back")
                             or _is_deferral(row2))
                        for k2, _, row2, ident2 in decided[i + 1:])]
    manifest = os.path.join(run_root, "deferrals.json")
    hunks = None
    if rows:
        md, err = _load_sibling("lvm_match_deferrals", "match-deferrals.py")
        # The last entry's diff; an entry that died before Phase 0.2 leaves none, so the newest
        # retained copy stands in.
        candidates = ["diff.patch"] + [f"evidence-{e}/iter-{k}/diff.patch"
                                       for k in range(args.iteration, 0, -1)
                                       for e in ("shadow", "step1")]
        diff_text, why = None, "diff.patch absent"
        for rel in candidates:
            try:
                with open(os.path.join(run_root, rel), encoding="utf-8") as fh:
                    diff_text = fh.read()
                if rel != "diff.patch":
                    warnings.append(f"diff.patch absent; the widens-surface guard read {rel}")
                break
            except FileNotFoundError:
                continue
            except (OSError, UnicodeDecodeError) as e:
                why = f"{rel} unreadable ({type(e).__name__})"
                break
        if diff_text is None:
            err = err or why
        if md is not None and diff_text is not None:
            try:
                hunks = md._parse_diff_hunks(diff_text)
                norm, tolerance = md._norm_path, md.WIDENS_SURFACE_TOLERANCE
            except Exception as e:  # a parser or sibling-name fault is the guard's reason
                hunks, err = None, f"{type(e).__name__}: {e}"
        if hunks is None:
            warnings.append(f"widens-surface guard could not run: {err}; its deferrals are not carried")
    for k, record, row, ident in rows:
        fid = row.get("finding_id")
        finding = _finding_by_id(record, fid)
        file_, kind, line_range = ident[0]
        if file_ is None:
            file_ = row.get("source_file") if isinstance(row.get("source_file"), str) else None
        if hunks is None:
            rejected.append({"iter": k, "finding_id": fid, "file": file_, "reason": "guard-not-run"})
            continue
        if not file_:
            rejected.append({"iter": k, "finding_id": fid, "file": None, "reason": "no-file"})
            continue
        file_hunks = hunks.get(norm(file_), [])
        if file_hunks and (line_range is None or _overlaps(file_hunks, line_range, tolerance)):
            lines = f"{line_range[0]}-{line_range[1]}" if line_range else "whole file"
            rejected.append({"iter": k, "finding_id": fid, "file": file_, "reason": "widens-surface",
                             "lines": lines})
            continue
        entry = {"iter": k, "finding_id": fid}
        if finding:
            description = finding.get("description") if isinstance(finding.get("description"), str) else ""
            symbol = _BACKTICK_RE.search(description)
            joined = {"agent": finding.get("agent"), "severity": finding.get("severity"),
                      "file": file_, "line_range": line_range,
                      "symbol": symbol.group(1) if symbol else "",
                      "kind": kind, "summary": description}
            entry.update({key: value for key, value in joined.items() if value is not None})
        else:
            claim = row.get("claim_text")
            entry.update({"file": file_, "symbol": "",
                          "summary": claim if isinstance(claim, str) else ""})
        entry["category"] = row.get("skip_category")
        entry["explanation"] = row.get("evidence") if isinstance(row.get("evidence"), str) else ""
        if entry["category"] == _FORECLOSURE:
            source = (row.get("parking_evidence") or {}).get("source") \
                if isinstance(row.get("parking_evidence"), dict) else None
            if not (isinstance(source, dict) and isinstance(source.get("path"), str)
                    and isinstance(source.get("phrase"), str)):
                rejected.append({"iter": k, "finding_id": fid, "file": file_,
                                 "reason": "disclosure-missing"})
                continue
            entry["disclosure"] = {"path": source["path"], "phrase": source["phrase"]}
        entries.append(entry)
    try:
        if entries:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            doc = {"schema_version": 1, "generated_at": stamp, "deferrals": entries}
            tmp = manifest + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
            os.replace(tmp, manifest)
        elif os.path.exists(manifest):
            os.remove(manifest)
    except OSError as e:
        _emit_json({"status": "error",
                    "reason": _drop_manifest(manifest, f"deferrals.json not written ({_os_reason(e)})"),
                    "rejected": rejected})
        return 1
    _emit_json({"status": "ok", "path": manifest if entries else None, "written": len(entries),
                "rejected": rejected, "warnings": warnings})
    return 0


_DISPATCH_FACT = {
    "attempted": "this run launched the Step 2.6 fan-out",
    "never": "no shadow fan-out was ever dispatched",
    "unestablished": "not established",
}


def _sha_matches(recorded, head: str) -> bool:
    return (isinstance(recorded, str) and len(recorded) >= 7
            and re.fullmatch(r"[0-9a-fA-F]+", recorded) is not None
            and head.lower().startswith(recorded.lower()))


def _shadow_status(records: dict, n: int, head: str | None, result_token: str | None,
                   dispatch: str) -> tuple[str, str]:
    """(the {shadow status} phrase, the Coverage section's shadow sentence)."""
    unaudited = "the loop's tentative verdict stands but was not independently audited."
    final = records.get(n)
    skipped = final.get("shadow_skipped") if final else None
    if final is not None and "shadow" not in final and isinstance(skipped, dict):
        if n != 1 or final.get("restored_from") is not None:
            return ("shadow agreement not verified (an iteration-1 skip recorded on another iteration)",
                    (f"Shadow agreement NOT verified — the clean-iteration-1 skip applies only "
                     f"to a fresh iteration 1; {unaudited}"))
        if head and _sha_matches(skipped.get("head"), head):
            return ("shadow skipped, iteration 1 clean",
                    ("Shadow pass skipped — iteration 1 was clean; the caller's PR-level review "
                     "is the independent pass."))
        return ("shadow agreement not verified (HEAD moved after the skip)",
                f"Shadow agreement NOT verified — HEAD is not the commit iteration 1 reviewed; {unaudited}")
    k, block = next(((k, records[k]["shadow"]) for k in range(n, 0, -1)
                     if records.get(k) and isinstance(records[k].get("shadow"), dict)), (None, None))
    if block is None:
        if result_token == "reject":
            return ("shadow agreement not verified",
                    "Shadow pass did not run — final verdict was REJECT before convergence.")
        return ("shadow agreement not verified (shadow result not recorded)",
                ("Shadow agreement NOT verified — the shadow result was not recorded; shadow "
                 f"fan-out dispatched: {_DISPATCH_FACT[dispatch]}"))
    if block.get("coverage") != "full":
        reason = block.get("reason")
        reason = reason if isinstance(reason, str) and reason else "specific reason not recorded"
        return (f"shadow agreement not verified ({reason})",
                f"Shadow agreement NOT verified — {reason}; {unaudited}")
    if not head or not _sha_matches(block.get("reviewed_sha"), head):
        return ("shadow agreement not verified (HEAD moved after the shadow)",
                (f"Shadow agreement NOT verified — HEAD is not the commit the iteration-{k} "
                 f"shadow reviewed; {unaudited}"))
    if block.get("dispatch_disposition") is not None or block.get("dispatch_mode") == "unavailable":
        return ("shadow agreement not verified (inline engine execution)",
                (f"Shadow agreement NOT verified — the shadow engine ran inline in the informed "
                 f"loop context; {unaudited}"))
    cmp_ = block.get("comparison") if isinstance(block.get("comparison"), dict) else {}

    def number(key):
        v = cmp_.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    if result_token in _CLEAN_APPROVE_TOKENS and (
            block.get("promoted_to_iter_next") is True
            or number("new_critical") != 0 or number("new_important") != 0):
        return ("shadow agreement not verified (the shadow's new findings are unresolved)",
                (f"Shadow agreement NOT verified — the iteration-{k} shadow raised new Critical or "
                 f"Important findings, or recorded no comparison; {unaudited}"))
    roster = block.get("reviewers_dispatched")
    roster = ", ".join(r for r in roster if isinstance(r, str)) if isinstance(roster, list) else "?"

    def count(key):
        v = number(key)
        return "?" if v is None else str(v)
    sentence = (f"Shadow ran with full reviewer coverage ({roster}). It raised "
                f"{count('shadow_total')} findings; {count('overlap_with_iter_N')} were already in "
                f"iteration {k}; {count('new')} were new ({count('new_critical')} Critical, "
                f"{count('new_important')} Important).")
    return "shadow agreed, full coverage", sentence


def _return_checklist(run_root: str, k: int) -> tuple[list | None, str]:
    """(the joined `checklist` of `engine-return-step1-iter-<k>.json`, '') — None when the file is
    absent or the entry ran no Phase 1+2 — or (None, why) when the file cannot be used."""
    name = f"engine-return-step1-iter-{k}.json"
    try:
        with open(os.path.join(run_root, name), "rb") as fh:
            value = json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        return None, ""
    except OSError as e:
        return None, f"{name} unreadable ({_os_reason(e)})"
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        return None, f"{name} is not JSON ({type(e).__name__})"
    if not isinstance(value, dict):
        return None, f"{name} is a JSON {type(value).__name__}, not an object"
    checklist = value.get("checklist")
    if checklist is None:
        return None, ""
    if not isinstance(checklist, list):
        return None, f"{name} checklist is a JSON {type(checklist).__name__}, not an array"
    return _rows(checklist), ""


def _record_checklist(record: dict | None, k: int) -> tuple[list | None, str]:
    """(iter-<k>.json's own `checklist` rows, '') — None when absent — or (None, why) when it is
    not an array."""
    checklist = record.get("checklist") if record is not None else None
    if checklist is None or isinstance(checklist, list):
        return (None if checklist is None else _rows(checklist)), ""
    return None, f"iter-{k}.json checklist is a JSON {type(checklist).__name__}, not an array"


def _coverage_items(records: dict, n: int, run_root: str, warnings: list) -> list[str]:
    """`- <id>: VERDICT (severity) — <claim_signature>` for each checklist FAIL and INCONCLUSIVE
    item of the last non-promoted iteration that ran Phase 1+2, a FAIL its iteration applied a
    fix to marked so. The checklist is the Step 1 engine return's, else the record's own; an
    iteration whose checklist cannot be read, or whose record is unreadable with no Step 1
    return, gets a `not listed` line instead."""
    for k in range(n, 0, -1):
        rec = records.get(k)
        if rec is not None and rec.get("loop_role") == "promoted":
            continue
        checklist, why = _return_checklist(run_root, k)
        if checklist is None:
            checklist, own_why = _record_checklist(rec, k)
            if checklist is not None and why:
                warnings.append(f"{why}; iteration {k}'s record checklist listed instead")
            why = "; ".join(filter(None, (why, own_why)))
        if checklist is None and not why and rec is None and not os.path.exists(
                os.path.join(run_root, f"engine-return-step1-iter-{k}.json")):
            why = f"iter-{k}.json unreadable"
        if checklist is None:
            if why:
                return [f"- Checklist items of iteration {k} not listed: {why}."]
            continue
        applied = {r.get("finding_id") for r in _rows(rec.get("fix_decisions") if rec else None)
                   if r.get("decision") == "applied"}
        out = []
        for item in checklist:
            verdict = item.get("verdict")
            if verdict in ("FAIL", "INCONCLUSIVE"):
                fixed = " (fix applied)" if verdict == "FAIL" and item.get("id") in applied else ""
                out.append(f"- {item.get('id')}: {verdict} ({item.get('severity') or 'critical'}) — "
                           f"{item.get('claim_signature') or 'no claim signature'}{fixed}")
        return out
    return []


def _grade_last_entry(run_root: str, n: int, records: dict,
                      warnings: list) -> tuple[str, str, int | None, str | None]:
    """(outcome, detail, iteration, entry) for the most recent entry's retained evidence
    `evidence-<entry>/iter-<k>/`. A shadow copy that does not pass is passed over with a warning;
    the most recent step1 copy decides. Only a promoted iteration, which runs no Step 1, is
    walked back past for want of a step1 copy."""
    for k in range(n, 0, -1):
        shadow = f"{run_root}/evidence-shadow/iter-{k}"
        if os.path.isdir(shadow):
            outcome, detail = _classify_run_root_grade(shadow, k)
            if outcome == "pass":
                return outcome, detail, k, "shadow"
            warnings.append(f"evidence-shadow/iter-{k} did not pass ({detail}); not graded")
        step1 = f"{run_root}/evidence-step1/iter-{k}"
        if os.path.isdir(step1):
            outcome, detail = _classify_run_root_grade(step1, k)
            return outcome, detail, k, "step1"
        rec = records.get(k)
        if not (isinstance(rec, dict) and rec.get("loop_role") == "promoted"):
            return ("unestablished", f"iteration {k} retained no evidence-step1/iter-{k}/ copy",
                    k, "step1")
    return ("unestablished", f"no evidence-step1/iter-<k>/ copy under {run_root} for k <= {n}",
            None, None)


def _cmd_render_exit(args: argparse.Namespace) -> int:
    token = _normalize_result(args.result)
    if args.iteration < 1 or token is None:
        _emit_json({"status": "error", "reason": "--iteration must be a positive integer"
                    if args.iteration < 1 else f"--result {args.result!r} is not a loop result"})
        return 2
    run_root = posix_path(args.run_root)
    records, warnings = {}, []
    for k in range(1, args.iteration + 1):
        rec, why = _read_record(run_root, k)
        records[k] = rec
        if rec is None:
            warnings.append(why)
    rc, out, _err = _git(["rev-parse", "HEAD"])
    head = out.strip() if rc == 0 and isinstance(out, str) and _SHA40_RE.match(out.strip()) else None
    if head is None:
        warnings.append("HEAD unresolved; shadow agreement cannot be verified")
    phrase, sentence = _shadow_status(records, args.iteration, head, token, args.shadow_dispatch)
    incomplete = []
    final = records.get(args.iteration)
    pc = final.get("park_calibration") if final else None
    if token in _CLEAN_APPROVE_TOKENS and not (isinstance(pc, dict)
                                               and isinstance(pc.get("evidence_comparisons"), list)):
        incomplete.append("park_calibration")
        phrase = "shadow agreement not verified (park calibration not recorded)"
        sentence = ("Shadow agreement NOT verified — the park-calibration gate left no record; "
                    "the loop's tentative verdict stands but was not independently audited.")
    sentences = [sentence]
    gate = " and ".join(g.strip() for g in args.not_verified or () if g.strip())
    if gate:
        sentences.append(f"{gate} NOT verified.")
    items = _coverage_items(records, args.iteration, run_root, warnings)
    coverage = "\n".join(["## Coverage", "", *(f"- {s}" for s in sentences), *items]) + "\n"
    coverage_path = f"{run_root}/loop-exit-coverage.md"
    try:
        with open(coverage_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(coverage)
    except OSError as e:
        _emit_json({"status": "error", "reason": f"coverage not written ({_os_reason(e)})"})
        return 1
    outcome, detail, graded, graded_entry = _grade_last_entry(run_root, args.iteration, records,
                                                              warnings)
    result = {"shadow_status": phrase, "coverage_path": coverage_path, "graded_iteration": graded,
              "graded_entry": graded_entry, "incomplete": incomplete, "warnings": warnings}
    if outcome != "pass":
        _emit_json({"status": "evidence-missing", "marker": None, "detail": detail, **result})
        return 0
    marker = f"{MARKER_PREFIX}result={token} coverage={_normalize_coverage(phrase)} -->"
    _emit_json({"status": "ok", "marker": marker, **result})
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────
def _add_iteration_args(sub_parser: argparse.ArgumentParser) -> None:
    sub_parser.add_argument(
        "--contract", default=None,
        help="2: the iteration-scoped grade below; required with --iteration")
    sub_parser.add_argument(
        "--iteration", default=None, type=int,
        help="grade only this fix-loop iteration's own evidence in --run-root")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        prog="loop-verdict-marker.py",
        description="Render or read the review-and-fix loop-verdict marker (issue #1212).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

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
        help="the loop's held review run root to grade through review-evidence-gate",
    )
    _add_iteration_args(p_check)
    p_check.set_defaults(func=_cmd_check_evidence)

    p_cont = sub.add_parser(
        "continue-run",
        help="restore a killed prior attempt's iteration records bound to HEAD into this "
        "run root (issue #893) and print one continue-run: line",
    )
    p_cont.add_argument("--run-root", required=True,
                        help="this run's held review run root (.prflow/tmp/review/<slug>/<run-id>)")
    p_cont.add_argument("--max-iterations", required=True, type=int,
                        help="the loop's resolved iteration cap; a record whose N+1 exceeds it reads none")
    p_cont.add_argument("--telemetry-branch", required=True,
                        help="the telemetry branch name the loop read from config (.telemetry.branch)")
    p_cont.set_defaults(func=_cmd_continue_run)

    p_def = sub.add_parser("build-deferrals",
                           help="write the run's deferrals.json from the fix_decisions of iter-1..N")
    p_def.add_argument("--run-root", required=True)
    p_def.add_argument("--iteration", required=True, type=int)
    p_def.set_defaults(func=_cmd_build_deferrals)

    p_exit = sub.add_parser("render-exit",
                            help="the Loop Exit marker, {shadow status} phrase and Coverage section")
    p_exit.add_argument("--run-root", required=True)
    p_exit.add_argument("--iteration", required=True, type=int)
    p_exit.add_argument("--result", required=True)
    p_exit.add_argument("--shadow-dispatch", choices=sorted(_DISPATCH_FACT), default="unestablished")
    p_exit.add_argument("--not-verified", action="append", metavar="GATE",
                        help="a gate that did not complete (repeatable): a Coverage line; the marker is unchanged")
    p_exit.set_defaults(func=_cmd_render_exit)

    p_inst = sub.add_parser("install-record",
                            help="check iter-<N>.json.draft against the iteration-record schema "
                            "and install it over iter-<N>.json")
    p_inst.add_argument("--run-root", required=True)
    p_inst.add_argument("--iteration", required=True, type=int)
    p_inst.set_defaults(func=_cmd_install_record)

    args = parser.parse_args(argv)
    if args.cmd == "check-evidence" and (
            (args.contract is None) != (args.iteration is None) or args.contract not in (None, "2")
            or (args.iteration is not None and args.iteration < 1)):
        # An older helper has no --contract, so --contract 2 makes it exit 2.
        parser.error("--iteration N (a positive integer) requires --contract 2, and "
                     "--contract 2 requires --iteration N")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

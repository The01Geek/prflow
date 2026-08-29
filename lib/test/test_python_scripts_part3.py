#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Pure-function tests for the devflow Python scripts.

Covers areas that are silent-failure-class regressions if they drift:
- `workpad._apply_mutations` — batch tick/note application, the structural-failure
  abort (missing section aborts with no PATCH), and the issue #169 failure-isolation
  contract: a per-row tick miss inside a present section is collected (the call's
  other mutations still apply) rather than discarding the batch, plus index-based
  ticking (`--tick-ac-n`/`--tick-plan-n`).
- `parse_acs._is_post_merge` — the new workflow/bot-trigger phrases plus
  documented false-positive cases (`monitoring` substring, generic
  "errors swallowed" prose, `click` substring, `workflow runner` vs
  `workflow run`, and `commenting on a` previous-decision prose).
- `section_parse.extract_section` (re-exported through `parse_acs`) / `parse_acs._parse_checkboxes` / `_render_md` — the
  case-insensitive, level-bounded heading match (a differently-cased heading
  still matches, but a trailing-colon / wrong-level heading must yield zero
  items, not a silent miss that trivially passes the implement skill's
  post-merge-exempt gate), bullet variants, and the `(post-merge)` render
  tagging.
- `file_deferrals._derive_area` / `_compute_id` / `_format_line_range` /
  `_render_issue_body` — the `<area>` derivation examples, the deterministic
  ID that must stay stable across regenerations (the verdict engine matches on
  it), and the `PR #<n>` cross-link substring the verdict engine's guard
  validates against ("Do not reformat without updating the matcher").
- `match_deferrals._extract_block` / `_parse_yaml_payload` — the deferred-findings
  payload now lives in a hidden DEVFLOW_DEFERRED_PAYLOAD HTML comment (the PR body
  shows a human-readable table); the matcher must parse the payload from that
  comment, not the visible table, and degrade gracefully on an absent block.

Run from repo root:
    python3 lib/test/test_python_scripts_part3.py
"""

import argparse
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

# Never move this below the first child-process invocation in this file: a child
# started above it inherits the host's colour setting, and argparse then colourises
# the help text the #1550 probes read. docs/internal/test-suite-probe-conventions.md
os.environ['PYTHON_COLORS'] = '0'
os.environ['NO_COLOR'] = '1'

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def _load(modname: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


workpad = _load('workpad', SCRIPTS / 'workpad.py')
# issue #1087: the terminal `--status Complete` gate now also requires a completion
# verification-flight marker. The pre-#1087 workpad tests (issues #258/#814 and the
# cmd_update drivers) exercise the AC/Plan self-record gate and the PATCH path, NOT
# the evidence gate, so they run with the evidence half bypassed by default. The
# dedicated #1087 block near the end of this file saves the real function, exercises
# it directly, and restores this bypass afterwards.
_REAL_COMPLETION_EVIDENCE_VERDICT = workpad._completion_evidence_verdict
workpad._completion_evidence_verdict = lambda args, prog_content: None
workpad._required_artifact_verdict = lambda prog_content: None
workpad._review_coverage_verdict = lambda prog_content: None
workpad._extension_row_verdict = lambda prog_content: None
parse_acs = _load('parse_acs', SCRIPTS / 'parse-acs.py')
file_deferrals = _load('file_deferrals', SCRIPTS / 'file-deferrals.py')
match_deferrals = _load('match_deferrals', SCRIPTS / 'match-deferrals.py')
resolve_review_overrides = _load(
    'resolve_review_overrides', SCRIPTS / 'resolve-review-overrides.py')
stale_prose_lint = _load('stale_prose_lint', SCRIPTS / 'stale-prose-lint.py')
issue_audit_state = _load('issue_audit_state', SCRIPTS / 'issue-audit-state.py')
discover_deferrals = _load(
    'discover_deferrals', SCRIPTS / 'discover-deferral-manifests.py')
reconcile_ac = _load('reconcile_ac_verifiers', SCRIPTS / 'reconcile-ac-verifiers.py')


PASS = 0
FAIL = 0

# When this suite runs inside lib/test/run.sh's bounded concurrent pool (issue #720)
# the pool exports DEVFLOW_POOL_TALLY_FILE and expects one PASS/FAIL line per
# assertion appended to it, so the suite's whole assertion count reaches
# RESULTS_FILE (a single collapsed verdict would silently drop this suite's ~1800
# assertions from the reported total). When the variable is unset — a standalone
# `python3 lib/test/test_python_scripts_part3.py` run — this is a no-op, so direct
# invocation is unchanged. Append-only, one line per verdict, matching the tally
# grammar _devflow_valid_result_count enforces (PASS/FAIL lines only).
_POOL_TALLY_FILE = os.environ.get("DEVFLOW_POOL_TALLY_FILE")


def _pool_name_record(name):
    """Append a failing assertion's identifier to the pool tally's `.names` sibling (#789).

    `record_fail` is a shell function this process cannot call, so without this the suite's
    LARGEST failure population would be counted by the tally fold and named by nothing — the
    recap would print an unnamed-shortfall line covering ~1800 assertions. The contract is
    the shell producer's: one identifier per line, tab/newline/CR collapsed to a space so one
    failure is always one line, and an empty name degrades to the same placeholder.
    Best-effort exactly like the tally write it accompanies — a naming failure must never
    abort the suite, but it leaves a breadcrumb rather than vanishing."""
    if not _POOL_TALLY_FILE:
        return
    flat = " ".join(str(name).split()) or "(unnamed check)"
    try:
        with open(_POOL_TALLY_FILE + ".names", "a", encoding="utf-8") as _fh:
            _fh.write(flat + "\n")
    except OSError as _e:
        print(
            f"devflow-pool: #789 identifier-record write failed for "
            f"{_POOL_TALLY_FILE + '.names'!r} (name {flat!r}): {_e}",
            file=sys.stderr,
        )


def _pool_tally(verdict, name=None):
    if verdict == "FAIL":
        _pool_name_record(name)
    if not _POOL_TALLY_FILE:
        return
    try:
        with open(_POOL_TALLY_FILE, "a", encoding="utf-8") as _fh:
            _fh.write(verdict + "\n")
    except OSError as _e:
        # Best-effort: a tally-write failure must not abort the suite, but the
        # pool's fail-closed reap (empty/short tally on a non-zero exit) still
        # catches a suite whose verdicts never landed. Emit a stderr breadcrumb
        # naming the real cause (the tally path + verdict) so an operator seeing
        # the downstream "RESULTS_FILE contribution equals summary" mismatch is
        # pointed at the tally WRITE, not just the symptom — the repo's best-effort
        # convention (always continue, but leave a breadcrumb; cf. resolve-bin.sh).
        print(
            f"devflow-pool: #720 tally write failed for {_POOL_TALLY_FILE!r} "
            f"(verdict {verdict}): {_e}",
            file=sys.stderr,
        )


def decided(text):
    """The DECIDED first line of a state-owner subcommand's stdout (issue #795).

    Most `issue-audit-state.py` subcommands now print a trailing `next_call=` line after
    their own decided answer line. Every whole-stdout comparison below whose subject is
    that decided answer is re-anchored onto this helper rather than being deleted or
    loosened: the assertion still pins the answer byte-for-byte, it just stops also
    pinning the absence of a second line. The subcommands EXCLUDED from that line keep
    comparing whole stdout — they emit no `next_call=` line, and their tails are exactly
    what those rows exist to assert. That set is the multi-line read-backs
    (`query-findings`, `query-coverage`, …) PLUS `emit-body`, the gated payload emitter;
    `emit-body` is deliberately not one of the read-backs,
    and the module keeps the two apart.
    """
    return text.strip().split('\n')[0]


def assert_eq(name, expected, actual):
    global PASS, FAIL
    if expected == actual:
        PASS += 1
        _pool_tally("PASS")
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        _pool_tally("FAIL", name)
        print(f"  FAIL  {name}\n         expected: {expected!r}\n         actual:   {actual!r}")


def assert_raises(name, exc_type, fn):
    global PASS, FAIL
    try:
        fn()
    except exc_type as e:
        PASS += 1
        _pool_tally("PASS")
        print(f"  PASS  {name} (raised: {e})")
        return
    except Exception as e:
        FAIL += 1
        _pool_tally("FAIL", name)
        print(f"  FAIL  {name}\n         expected {exc_type.__name__}, got {type(e).__name__}: {e}")
        return
    FAIL += 1
    _pool_tally("FAIL", name)
    print(f"  FAIL  {name}\n         expected {exc_type.__name__}, no exception raised")


def make_args(**overrides):
    """Build an argparse.Namespace matching cmd_update's expected shape."""
    base = {
        'status': None, 'branch': None, 'run_link': None, 'pr_link': None,
        'tick_progress': [], 'tick_plan': [], 'tick_plan_n': [], 'tick_ac': [], 'tick_ac_n': [],
        'rewrite_ac': [],
        'replace_plan_file': None, 'replace_acs_file': None, 'set_reproduction_file': None,
        'note': [], 'reflection': [], 'reflection_kind': None, 'reflection_file': [],
        'note_file': [],
        'marker': None,
        'reconcile_reproduction': None, 'record_classification': None,
        'checkpoint': [], 'expect_comment_id': None, 'expect_status': None,
        # issue #781 scope-decision records — this fixture encodes cmd_update's
        # arg shape, so every attribute `_apply_mutations` /
        # `_has_non_checkpoint_mutation` reads must be present here or those
        # reads raise AttributeError on every test that builds args this way.
        'scope_decision_deferred': [], 'scope_decision_rewritten': [],
        'bind_scope_decisions': None,
        # issue #815 filed-marker writer — same reason as the scope-decision
        # attributes above: `_apply_mutations` reads it on every call.
        'mark_deferred_filed': [], 'mark_deferred_filed_file': None,
        # issue #1087 completion verification-flight evidence — `_apply_mutations`
        # and the terminal gate read these on every call.
        'record_completion_evidence': None, 'repo_root': None, 'claim_identity': None,
        # issue #1611 CI-derived completion evidence — `_apply_mutations` and the
        # terminal gate read this on every call. issue #1898 adds the repeatable
        # --completion-ci-check pairs read beside it.
        'record_completion_evidence_ci': None, 'completion_ci_check': None,
        # issue #1347 inherited required-artifact strip — read on every call.
        'strip_inherited_checkpoints': False,
        # issue #1453 review-coverage record + dispositions — read on every call.
        # issue #1510 adds the optional as-of anchor head, read via getattr.
        'record_review_coverage': None, 'review_coverage_disposition': [],
        # issue #1512 shadow-roster per-member enumeration — read on every call.
        'record_roster_member': None,
        'record_review_coverage_head': None,
        # issue #1509 review-coverage diff recomputation — read via getattr on the
        # write path; a base ref for the range and an explicit override channel.
        'record_review_coverage_base': None, 'record_review_coverage_override': None,
        # issue #1462 prompt-extension row reconciliation — read on every call.
        'reconcile_extension_rows': False,
        # issue #1876 mid-phase resume-point record — read on every call.
        'record_resume_point': None,
        'print_body': False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def apply_mut(body, args, failed_ticks=None):
    """Test wrapper for `_apply_mutations`, whose production signature now takes a
    required `failed_ticks` out-list (volatile per-row tick misses are appended
    there instead of raising). Most tests pass no list (a throwaway is created);
    failure-isolation tests pass their own list to inspect the collected misses."""
    return workpad._apply_mutations(body, args, failed_ticks if failed_ticks is not None else [])


WORKPAD_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** Implementing
**Branch:** `feat/x`
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [ ] **Setup** — branch & workpad
- [ ] **Implement**
  - [ ] code + sweeps
- [ ] **Review**
- [ ] **Documentation**
- [ ] **PR marked ready**

## Plan
- [ ] Step alpha
- [ ] Step beta
- [ ] Step gamma

## Acceptance Criteria
- [ ] AC one
- [ ] AC two

## Devflow Reflection
"""


print("workpad._workpad_marker (issue #55 review-marker override)")

# Marker override lets /devflow:review target its own <!-- devflow:review-progress
# --> comment with the same helper. Precedence: the `--marker` CLI flag (passed as
# a plain argument, so the command still starts with the allow-listed helper path)
# > the DEVFLOW_WORKPAD_MARKER env var (back-compat) > config > built-in default.
import os as _os

_saved = _os.environ.pop('DEVFLOW_WORKPAD_MARKER', None)


# #295: repo-root anchoring — the marker resolves from the ROOT config.json when
# workpad.py is invoked from a nested SUBDIRECTORY of a git repo. The #275 block above
# poisons _run and only exercises the cwd-FALLBACK path (non-git temp dirs); this test
# uses the REAL _run (a live `git rev-parse --show-toplevel` subprocess) to exercise the
# new git-ROOT discovery path directly — the case the reported bug (config silently lost
# from a subdir) actually hit. Asserts the returned VALUE, so it is symlink-robust
# (macOS /tmp → /private/tmp) without comparing resolved paths.
import subprocess as _sp295

print("workpad.cmd_id exit-code contract (issue #55 live-comment seeding)")

# The /devflow:review live-comment seeding branches on `workpad.py id`'s exit code
# (0 = found → resume, 2 = scanned-clean-but-absent → create, 1 = gh-api/parse
# error → skip, do NOT create). A regression collapsing the absent case (2) back
# to a generic error (1) would make a transient API hiccup look identical to "no
# comment yet", so the caller would post a DUPLICATE progress comment. These pin
# all three codes by stubbing the gh calls (no network).
import json as _json
import subprocess as _subprocess


class _FakeRun:
    # Models ONLY `.stdout` — the sole `_run(...)` attribute cmd_id/cmd_update read
    # on the success path. A consumer that later reads `.returncode`/`.stderr` would
    # hit an opaque AttributeError here; extend this double (and this note) if so.
    def __init__(self, stdout):
        self.stdout = stdout


def _cmd_id_exit(comments_stdout=None, *, raise_api=False):
    """Run cmd_id against a stubbed gh layer; return its exit code (None = exit 0).

    `_repo_full` and `_workpad_marker` are stubbed so no real gh/config call
    happens; `_run` returns the canned comments page (or raises to simulate a
    transient gh-api failure).
    """
    rev_marker = '<!-- devflow:review-progress -->'
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker)
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: rev_marker
    if raise_api:
        def _boom(cmd, **kw):
            raise _subprocess.CalledProcessError(1, cmd, stderr='gh: API error')
        workpad._run = _boom
    else:
        workpad._run = lambda cmd, **kw: _FakeRun(comments_stdout)
    out = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            workpad.cmd_id(argparse.Namespace(issue=999, marker=None))
    except SystemExit as e:
        code = e.code
    finally:
        workpad._run, workpad._repo_full, workpad._workpad_marker = saved
    return code, out.getvalue().strip()


_MARK = '<!-- devflow:review-progress -->'
# Found: a comment whose body starts with the review marker → print id, exit 0.
_code, _printed = _cmd_id_exit(_json.dumps([{"id": 12345, "body": _MARK + "\nbody"}]))
# Clean scan, nothing matches (page < 100 → loop breaks) → exit 2 (first run → create).
_code, _ = _cmd_id_exit(_json.dumps([{"id": 1, "body": "an unrelated comment"}]))
# Empty issue (no comments at all) is still a clean scan → exit 2, not error.
_code, _ = _cmd_id_exit(_json.dumps([]))
# gh api failure → exit 1 (NOT 2): the caller must not mistake a transient error
# for "absent" and post a duplicate comment.
_code, _ = _cmd_id_exit(raise_api=True)
# Unparseable gh response → exit 1 (parse error path), again distinct from absent.
_code, _ = _cmd_id_exit("this is not json")


def _cmd_id_paginated(pages):
    """Run cmd_id with a stateful _run that returns one stdout string per gh-api
    page call (in order). Returns (exit_code, printed_id, num_page_calls)."""
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker)
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: _MARK
    calls = {'n': 0}

    def _seq(cmd, **kw):
        i = calls['n']
        calls['n'] += 1
        return _FakeRun(pages[i] if i < len(pages) else pages[-1])

    workpad._run = _seq
    out = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            workpad.cmd_id(argparse.Namespace(issue=999, marker=None))
    except SystemExit as e:
        code = e.code
    finally:
        workpad._run, workpad._repo_full, workpad._workpad_marker = saved
    return code, out.getvalue().strip(), calls['n']


# Pagination: a FULL first page (100 non-matching comments) forces the loop to
# fetch page 2 (`if len(items) < 100: break` is false, `page += 1`). The match on
# page 2 must be found — a regression collapsing pagination would miss an existing
# comment on a busy PR and post a DUPLICATE, the exact failure exit-2 prevents.
_full_page = _json.dumps([{"id": i, "body": "unrelated comment"} for i in range(100)])
_page2_hit = _json.dumps([{"id": 777, "body": _MARK + "\nfound on page 2"}])
_code, _printed, _ncalls = _cmd_id_paginated([_full_page, _page2_hit])
# Full page 1 + short no-match page 2 → clean-absent exit 2 (loop terminates, no hang).
_code, _, _ncalls = _cmd_id_paginated([_full_page, _json.dumps([])])


print("workpad --marker argv → resolver wiring (issue #56 review)")
_saved = (workpad._workpad_marker, workpad._repo_full, workpad._run)


print("workpad._apply_mutations")

# Batch tick: multiple --tick-plan in one call ticks all of them.
args = make_args(tick_plan=['alpha', 'beta'])
out = apply_mut(WORKPAD_BODY, args)

# Mixed batch: tick-plan + tick-ac + note in one atomic call.
args = make_args(tick_plan=['gamma'], tick_ac=['AC one'], note=['decision A', 'decision B'])
out = apply_mut(WORKPAD_BODY, args)

# Issue #169 failure-isolation: a per-row tick miss inside a present section is
# now a *volatile* failure — `_apply_mutations` collects it into the caller's
# `failed_ticks` list and returns the body with every other mutation applied,
# instead of raising `_UpdateError`. (Pre-#169 these four cases aborted the call.)

# Duplicate tick in one batched call: the first ticks; the second is a volatile
# miss (the row it would match is now ticked), collected, not raised.
_ft = []
out = apply_mut(WORKPAD_BODY, make_args(tick_plan=['alpha', 'alpha']), _ft)

# Substring matching only an already-ticked row: volatile miss, body still returns.
PRE_TICKED = WORKPAD_BODY.replace('- [ ] Step alpha', '- [x] Step alpha')
_ft = []
out = apply_mut(PRE_TICKED, make_args(status='Reviewing', tick_plan=['alpha']), _ft)

# Ambiguous substring: multiple matches → volatile miss, not an abort.
_ft = []
out = apply_mut(WORKPAD_BODY, make_args(status='Reviewing', tick_plan=['Step']), _ft)

# Isolation in a batch: one resolving tick + one non-matching tick. The resolving
# box is ticked in the returned body; the miss is collected (no abort, no rollback).
_ft = []
out = apply_mut(WORKPAD_BODY, make_args(tick_plan=['alpha', 'does-not-exist']), _ft)

# Heading match is case-insensitive: a differently-cased section heading is
# still found and mutated (not a silent "section not found" error).
LOWER_HEADING = WORKPAD_BODY.replace('## Acceptance Criteria', '## acceptance criteria')
out = apply_mut(LOWER_HEADING, make_args(tick_ac=['AC one']))

# Issue #308: --rewrite-ac is repeatable (argparse action='append', nargs=2). A
# single call carrying multiple OLD/NEW pairs applies every pair in argument
# order; each pair is validated by the existing exactly-one-match rule, and a
# pair matching zero/multiple rows aborts the whole call with no PATCH (the
# structural all-or-nothing contract).

# Single pair still works (back-compat with the pre-#308 nargs=2 shape, now one
# element of the append list).
out = apply_mut(WORKPAD_BODY, make_args(rewrite_ac=[['AC one', 'AC one rewritten']]))

# Box state is preserved on a *ticked* row (exercises _rewrite_checkbox's
# group-2 reconstruction, which the unticked fixture above cannot).
AC_TICKED = WORKPAD_BODY.replace('- [ ] AC one', '- [x] AC one')
out = apply_mut(AC_TICKED, make_args(rewrite_ac=[['AC one', 'AC one rewritten']]))

# Two pairs in one call: BOTH land (the pre-#308 bug silently kept only the last).
out = apply_mut(WORKPAD_BODY, make_args(
    rewrite_ac=[['AC one', 'AC one v2'], ['AC two', 'AC two v2']]))

# Pairs apply against the PROGRESSIVELY-rewritten section: the second pair's OLD
# matches the text the FIRST pair just wrote, not the original. A regression that
# re-read the original section per pair would leave 'AC one beta' unfound here.
out = apply_mut(WORKPAD_BODY, make_args(
    rewrite_ac=[['AC one', 'AC one alpha'], ['AC one alpha', 'AC one beta']]))


print("issue #169: failure-isolation + index-based ticking")


# Fixture with a pre-ticked first AC row, so a naive unticked-only index count
# would address the WRONG row (index counts every [ ] AND [x] in document order).
IDX_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Implementing
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [ ] **Setup**

## Plan
- [ ] Plan step one
- [ ] Plan step two

## Acceptance Criteria
- [x] AC one
- [ ] AC two
- [ ] AC three
"""

# Failure isolation (AC 1, 2): a non-matching --tick-ac in a present section does
# NOT discard the batched --status/--note; the body carries them and the miss is
# collected with a flag-named descriptor.
_ft = []
out = apply_mut(IDX_BODY, make_args(
    status='Reviewing', note=['keep me'], tick_ac=['NO_SUCH_AC']), _ft)

# Index happy path (AC 4): --tick-ac-n 2 ticks the SECOND checkbox counting the
# already-ticked first row — i.e. "AC two", not "AC three".
_ft = []
out = apply_mut(IDX_BODY, make_args(tick_ac_n=[2]), _ft)

# Index + substring + status in one call (AC 4): all apply, body returns once.
_ft = []
out = apply_mut(IDX_BODY, make_args(
    status='Reviewing', tick_ac=['AC two'], tick_ac_n=[3], tick_plan_n=[1]), _ft)

# Index boundary/degenerate (AC 5): N=0, N>count, and N on an already-ticked row
# are all volatile failures — reported, non-zero (here: collected), --status still
# applied. The AC section has 3 checkbox rows; row 1 is already [x].
_ft = []
out = apply_mut(IDX_BODY, make_args(status='Blocked', tick_ac_n=[0, 4, 1]), _ft)

# Substring forms unchanged (AC 6): an existing unique --tick-ac still ticks that
# exact row, additively (no behavior removed).
out = apply_mut(IDX_BODY, make_args(tick_ac=['AC three']))


print("issue #169 (review): cmd_update CLI contract + structural-abort completeness")


# cmd_update-level harness: stub _repo_full / _workpad_marker / _run so cmd_update
# runs end-to-end with no gh. _run serves three call shapes — the paginated comments
# list (one marker-matching comment), the body fetch (--jq .body → the fixture body),
# and the PATCH (read the -F body=@<tmp> file back so the test sees the patched body).
# Returns (exit_code, stdout, stderr, patched_body); patched_body is None when no PATCH
# ran. stdout is CAPTURED and returned (issue #814) so the default-suppression and
# --print-body arms of `update`'s echo are assertable at the unit level — the only
# level that drives the `_NoOpReplay` checkpoint-replay arm.
_LAST_GH_CALLS = []   # joined gh command lines from the most recent _drive_cmd_update
_UPDATE_ISSUE_URL = 'https://api.github.com/repos/owner/repo/issues/999'


def _drive_cmd_update(body, patch_fails=False, patch_response=None,
                      id_response=None, fail_at=None,
                      seed_cache_id=None, verify_fails=False, verify_response=None,
                      cache_dir=None, **arg_overrides):
    global _LAST_GH_CALLS
    _LAST_GH_CALLS = []
    marker = '<!-- devflow:workpad -->'
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker,
             workpad._workpad_id_cache_path, workpad._workpad_buffer_path)
    # Retained for compatibility though the update path no longer calls it: a stub
    # that still answered `gh repo view` would let a regression re-introducing the
    # call pass silently, so we DON'T stub _run to answer it (a repo-view call now
    # surfaces as an unhandled shape / assertion failure instead).
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: marker
    # Hermetic id cache: a fresh temp dir per call, so a real-tree cache never leaks
    # in and this call's write never leaks out. A caller may pass `cache_dir` to SHARE
    # one dir across sequential calls (the cold-write → warm-read round-trip test) —
    # the caller then owns that dir's lifetime and this driver does not remove it.
    _owns_cache_dir = cache_dir is None
    _cache_dir = cache_dir if cache_dir is not None else tempfile.mkdtemp(prefix='wp-idcache-')
    workpad._workpad_id_cache_path = lambda issue, mk: Path(_cache_dir) / f'{issue}.json'
    # Anchor the failed-write buffer under the same temp dir, so the buffer-replay
    # path never resolves _repo_root() (which would issue a `git rev-parse` through
    # _run and pollute the gh call log the two-call cache-hit assertion counts).
    workpad._workpad_buffer_path = lambda cid: Path(_cache_dir) / f'buf-{cid}.json'
    if seed_cache_id is not None:
        (Path(_cache_dir) / '999.json').write_text(
            _json.dumps({'comment_id': seed_cache_id, 'issue': 999,
                         'marker': marker, 'repo': 'owner/repo'}), encoding='utf-8')

    def _obj(cid=7):
        return {'id': cid, 'body': body, 'issue_url': _UPDATE_ISSUE_URL}

    state = {'patched': None}

    def _run(cmd, **kw):
        joined = ' '.join(cmd)
        _LAST_GH_CALLS.append(joined)
        if '-X' in cmd and 'PATCH' in cmd:
            if patch_fails:  # simulate a gh-api PATCH failure (network/auth/5xx)
                raise _subprocess.CalledProcessError(1, cmd, stderr='gh: 503 Service Unavailable')
            for tok in cmd:
                if tok.startswith('body=@'):
                    with open(tok[len('body=@'):]) as fh:
                        state['patched'] = fh.read()
            # `patch_response` overrides what the PATCH call RETURNS, independently of
            # the body it stored — the only way to drive `cmd_update`'s issue-#814
            # Status read-back arms, which parse the RESPONSE (a throttled/oversized
            # write can return an empty or Status-less body while the stored body is
            # fine). Default None keeps the echo-the-stored-body behaviour.
            if patch_response is not None:
                return _FakeRun(patch_response)
            return _FakeRun(state['patched'] or '')
        if '/comments?' in joined or joined.endswith('/comments'):
            # comments-list scan (id-lookup). `fail_at`/`id_response` (issue #1562)
            # drive cmd_update's id-lookup terminating paths and its
            # no-workpad-found path, which the default stub can never reach.
            if fail_at == 'id-lookup':
                raise _subprocess.CalledProcessError(1, cmd, stderr='gh: 500 id-lookup')
            if id_response is not None:
                return _FakeRun(id_response)
            return _FakeRun(_json.dumps([_obj()]))
        # A single-comment fetch: the issue-#2042 cache-verify GET. `verify_fails`
        # models a dead cached id (404); `verify_response` injects a custom body.
        if fail_at == 'verify' or verify_fails:
            raise _subprocess.CalledProcessError(1, cmd, stderr='gh: 404 Not Found')
        if verify_response is not None:
            return _FakeRun(verify_response)
        _m = re.search(r'/issues/comments/(\d+)', joined)
        _cid = int(_m.group(1)) if _m else 7
        return _FakeRun(_json.dumps(_obj(_cid)))
    workpad._run = _run
    out = io.StringIO()
    err = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            workpad.cmd_update(make_args(issue=999, **arg_overrides))
    except SystemExit as e:
        code = e.code
    finally:
        (workpad._run, workpad._repo_full, workpad._workpad_marker,
         workpad._workpad_id_cache_path, workpad._workpad_buffer_path) = saved
        if _owns_cache_dir:
            shutil.rmtree(_cache_dir, ignore_errors=True)
    return code, out.getvalue(), err.getvalue(), state['patched']


# Finding 2/(a) (review): the volatile-failure TAIL of cmd_update — the non-zero
# exit + stderr report — is the observable contract ACs 2/5 promise the orchestrator.
# The isolation tests above assert the failed_ticks LIST is populated; these assert
# the process-level exit code and stderr the orchestrator actually consumes.
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, status='Reviewing', tick_ac=['NO_SUCH_AC'])

# A fully-resolving tick call exits 0 — the gate's evidence-based pass condition.
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, tick_ac_n=[2])

# Finding F1 (silent-failure-hunter): a volatile tick miss collected BEFORE a later
# structural abort is echoed on the abort path, not dropped. F1_BODY has ## Acceptance
# Criteria (so --tick-ac can miss-collect) but NO ## Progress (so the later --note
# raises a structural _UpdateError) — the exact combined call the finding describes.
F1_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Implementing
**Last updated:** 2026-05-15T00:00:00Z

## Acceptance Criteria
- [ ] AC one
- [ ] AC two
"""
_code, _out, _err, _patched = _drive_cmd_update(F1_BODY, tick_ac=['NO_SUCH_AC'], note=['n'])

# Finding (c) (review): a --tick-plan-n out-of-range miss is collected as VOLATILE
# (reported, other mutations applied), not a structural abort — for the Plan section
# specifically, not just Acceptance Criteria. IDX_BODY's ## Plan has 2 rows.
_ft = []
out = apply_mut(IDX_BODY, make_args(status='Blocked', tick_plan_n=[5]), _ft)


print("issue #169 (shadow): PATCH-failure echo + structural/test-completeness")

# Shadow Finding 1 (silent-failure-hunter, HIGH): a volatile tick miss collected
# before the gh PATCH itself fails must NOT be silently dropped. Previously the
# PATCH-failure path reported only the PATCH error and exited, discarding the
# collected misses — the very no-silent-loss invariant this command establishes,
# re-opened on the API-failure path. Now cmd_update echoes them before _fail exits.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, patch_fails=True, status='Reviewing', tick_ac=['NO_SUCH_AC'])
# A PATCH failure with NO pending tick miss still reports the PATCH error (and does
# not fabricate a tick report) — the echo is gated on a non-empty failed_ticks.
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, patch_fails=True, tick_ac_n=[2])

# The volatile-PATCHed breadcrumb tells the caller to re-tick only the row(s), NOT
# re-send the whole call (Finding 2 — re-sending would double-write append-only notes).
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, note=['n'], tick_ac=['NO_SUCH_AC'])

# Shadow Finding 3 (silent-failure-hunter, LOW): an index tick against a PRESENT but
# EMPTY section (zero checkbox rows) is a VOLATILE out-of-range miss, NOT a structural
# abort — pins the volatile/structural boundary on the section-shape axis (TD-1 pins
# the class-hierarchy axis). A future edit raising _UpdateError for an empty section
# would silently re-introduce batch-discard for that shape; this guards against it.
EMPTY_PLAN = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Last updated:** 2026-05-15T00:00:00Z

## Plan

## Acceptance Criteria
- [ ] AC one
"""
_ft = []
out = apply_mut(EMPTY_PLAN, make_args(status='Blocked', tick_plan_n=[1]), _ft)


print("issue #1562: cmd_update's machine-readable terminal outcome line")

# Drive the real cmd_update: mocking it out would assert the emission contract
# against a stub rather than the shipped terminating paths.

# Spelled here independently of the producer on purpose: reading the prefix from
# workpad.py would make a producer-side respelling invisible to every assertion below.
_OC_PREFIX = 'workpad.py update: outcome='


# A body whose ## Acceptance Criteria has rows to tick and whose Status/Last updated
# lines are present, so the clean, volatile-miss and status read-back arms all drive.
OC_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [ ] **Setup** — branch & workpad

## Plan
- [ ] plan one

## Acceptance Criteria
- [ ] AC one
"""

_OC_CASES = []   # (label, kwargs, expected_outcome, expected_remedy, expected_code)

# --- The checkpoint-only replay: no PATCH, exit 0. ---
_OC_CPKEY = 'gha:1:1:phase1-entered'
# Seed the existing checkpoint row through the marker's own producer — a hand-written
# marker literal silently misses the replay arm and the test then asserts nothing.
_OC_REPLAY = OC_BODY.replace(
    "- [ ] **Setup** — branch & workpad",
    "- [ ] **Setup** — branch & workpad\n  - 02:01:00 — seeded "
    + workpad._checkpoint_marker(_OC_CPKEY))
_c, _o, _e, _p = _drive_cmd_update(_OC_REPLAY, checkpoint=[[_OC_CPKEY, 'x']])
_OC_CASES.append(("the checkpoint replay", _e))

# --- The clean PATCH tail, and its three unreadable-Status read-back states. ---
_c, _o, _e, _p = _drive_cmd_update(OC_BODY, note=['n'])
_OC_CASES.append(("a clean PATCH", _e))

_c, _o, _e, _p = _drive_cmd_update(OC_BODY, status='Reviewing')
_OC_CASES.append(("a matching --status read-back", _e))

# The three unreadable read-back states share one token because they share one
# remedy; the pre-existing prose line still reports which of the three occurred.
_c, _o, _e, _p = _drive_cmd_update(OC_BODY, status='Reviewing', patch_response='')
_OC_CASES.append(("an empty --status read-back", _e))

_c, _o, _e, _p = _drive_cmd_update(OC_BODY, status='Reviewing',
                                   patch_response='no status line here')
_OC_CASES.append(("a Status-less --status read-back", _e))

_c, _o, _e, _p = _drive_cmd_update(OC_BODY, status='Reviewing',
                                   patch_response='**Status:** 🚀 Setup\n')
_OC_CASES.append(("a mismatched --status read-back", _e))

# --- The volatile tick-miss tail, alone and co-occurring with a bad read-back. ---
_c, _o, _e, _p = _drive_cmd_update(OC_BODY, note=['n'], tick_ac=['NO_SUCH_AC'])
_OC_CASES.append(("a volatile tick miss", _e))

_c, _o, _e, _p = _drive_cmd_update(OC_BODY, status='Reviewing', tick_ac=['NO_SUCH_AC'],
                                   patch_response='')
_OC_CASES.append(("a tick miss with an unreadable read-back", _e))

# --- Transitive terminating paths: the exit is inside a shared helper, so do not
# narrow these cases to cmd_update's own body — a lexical enumeration misses them.
def _drive_repo_lookup_failure():
    """cmd_update -> _repo_full -> _fail: the repo lookup dies before any of
    cmd_update's own terminating sites is reached."""
    saved = (workpad._run, workpad._workpad_marker)
    workpad._workpad_marker = lambda explicit=None: '<!-- devflow:workpad -->'

    def _boom(cmd, **kw):
        raise _subprocess.CalledProcessError(1, cmd, stderr='gh: could not resolve repo')

    workpad._run = _boom
    err = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            workpad.cmd_update(make_args(issue=999))
    except SystemExit as e:
        code = e.code
    finally:
        workpad._run, workpad._workpad_marker = saved
    return code, err.getvalue()


_code, _err = _drive_repo_lookup_failure()
_OC_CASES.append(("a repo-lookup failure", _err))

# A crash in the tail AFTER the PATCH landed must not report not-persisted, whose
# remedy re-sends the call and double-writes the append-only notes.
class _BrokenPipeStdout(io.StringIO):
    """Raises on write, standing in for a downstream `| head` closing the pipe."""

    def write(self, _s):
        raise BrokenPipeError('downstream closed the pipe')


def _drive_post_patch_crash():
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker,
             workpad._workpad_id_cache_path)
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: '<!-- devflow:workpad -->'
    _cd = tempfile.mkdtemp(prefix='wp1562-idcache-')
    workpad._workpad_id_cache_path = lambda issue, mk: Path(_cd) / f'{issue}.json'

    def _run(cmd, **kw):
        joined = ' '.join(cmd)
        # Issue #2042: the scan resolves id AND body together, so the comments-list
        # returns the full workpad object; there is no separate body fetch.
        if '/comments?' in joined or joined.endswith('/comments'):
            return _FakeRun(_json.dumps([{'id': 7, 'body': OC_BODY,
                'issue_url': 'https://api.github.com/repos/owner/repo/issues/999'}]))
        return _FakeRun(OC_BODY)

    workpad._run = _run
    err = io.StringIO()
    raised = None
    try:
        # --print-body drives the post-PATCH stdout echo, the write the reviewer
        # named; the PATCH has already landed when it raises.
        with contextlib.redirect_stdout(_BrokenPipeStdout()), contextlib.redirect_stderr(err):
            workpad.cmd_update(make_args(issue=999, print_body=True))
    except BaseException as e:
        raised = type(e).__name__
    finally:
        (workpad._run, workpad._repo_full, workpad._workpad_marker,
         workpad._workpad_id_cache_path) = saved
        shutil.rmtree(_cd, ignore_errors=True)
    return raised, err.getvalue()


_raised, _err = _drive_post_patch_crash()
_OC_CASES.append(("a post-PATCH crash", _err))


# The `finally` temp-file unlink is itself a raising statement between the observed
# PATCH and the wrapper, so it is driven separately from the stdout-echo crash above.
def _drive_patch_cleanup_failure():
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker, workpad.Path,
             workpad._workpad_id_cache_path)
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: '<!-- devflow:workpad -->'
    _cd = tempfile.mkdtemp(prefix='wp1562b-idcache-')
    # Set the cache path BEFORE workpad.Path is faked below — the fake Path only
    # denies the PATCH temp file, and this lambda builds its own real Paths.
    workpad._workpad_id_cache_path = lambda issue, mk: Path(_cd) / f'{issue}.json'

    def _run(cmd, **kw):
        joined = ' '.join(cmd)
        # Issue #2042: the scan resolves id AND body together (full workpad object).
        if '/comments?' in joined or joined.endswith('/comments'):
            return _FakeRun(_json.dumps([{'id': 7, 'body': OC_BODY,
                'issue_url': 'https://api.github.com/repos/owner/repo/issues/999'}]))
        return _FakeRun(OC_BODY)

    class _UnlinkDenied:
        def __init__(self, p):
            self._p = Path(p)

        def unlink(self, *a, **kw):
            raise PermissionError(13, 'Permission denied')

        def __getattr__(self, name):
            return getattr(self._p, name)

    def _fake_path(p, *rest):
        # Deny ONLY this call's own PATCH temp file; a broader fake would also
        # break the buffer-directory Paths this same code path composes.
        if not rest and str(p).startswith(tempfile.gettempdir()) and str(p).endswith('.md'):
            return _UnlinkDenied(p)
        return Path(p, *rest)

    workpad._run = _run
    workpad.Path = _fake_path
    err = io.StringIO()
    raised = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            workpad.cmd_update(make_args(issue=999))
    except BaseException as e:
        raised = type(e).__name__
    finally:
        (workpad._run, workpad._repo_full, workpad._workpad_marker, workpad.Path,
         workpad._workpad_id_cache_path) = saved
        shutil.rmtree(_cd, ignore_errors=True)
    return raised, err.getvalue()


_raised, _err = _drive_patch_cleanup_failure()
_OC_CASES.append(("a post-PATCH cleanup failure", _err))

# The exit-3 shared-helper abort (`_require_section_parse`, reached when the shared
# parsing module was not deployed) is the second transitive path the wrapper covers.
def _drive_section_parse_missing():
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker,
             workpad._SECTION_PARSE_IMPORT_ERROR, workpad._workpad_id_cache_path)
    workpad._repo_full = lambda: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: '<!-- devflow:workpad -->'
    workpad._SECTION_PARSE_IMPORT_ERROR = 'No module named section_parse'
    # Hermetic id cache. Unstubbed, _workpad_id_cache_path resolves its root through
    # the stubbed _run, which returns the workpad BODY — creating a repo-root
    # directory named after that body text on every run of this test.
    _cd = tempfile.mkdtemp(prefix='wp1562-sec-idcache-')
    workpad._workpad_id_cache_path = lambda issue, mk: Path(_cd) / f'{issue}.json'

    def _run(cmd, **kw):
        joined = ' '.join(cmd)
        if '/comments?' in joined or joined.endswith('/comments'):
            return _FakeRun(_json.dumps([{'id': 7, 'body': '<!-- devflow:workpad -->\n'}]))
        return _FakeRun(OC_BODY)

    workpad._run = _run
    err = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            workpad.cmd_update(make_args(
                issue=999, scope_decision_deferred=[['pending', 'a criterion']]))
    except SystemExit as e:
        code = e.code
    finally:
        (workpad._run, workpad._repo_full, workpad._workpad_marker,
         workpad._SECTION_PARSE_IMPORT_ERROR, workpad._workpad_id_cache_path) = saved
        shutil.rmtree(_cd, ignore_errors=True)
    return code, err.getvalue()


_code, _err = _drive_section_parse_missing()
_OC_CASES.append(("the exit-3 shared-helper abort", _err))

# --- Adjacent-case sweep over both closed sets, across the paths driven above. ---
_OC_OUTCOMES = {'landed', 'landed-status-unverified', 'landed-partial-ticks',
                'landed-partial-ticks-status-unverified', 'replay', 'not-persisted',
                'precondition-mismatch'}
_OC_REMEDIES = {'none', 'retick-named-rows', 'reset-status', 'retick-and-reset-status',
                'reissue-call', 're-resolve-state'}
_oc_seen_outcomes, _oc_seen_remedies, _oc_stray = set(), set(), []
# Count per case as well as collect: the sets below collapse duplicates, so a path
# that emitted its line twice would read as clean in every other assertion here.
_oc_wrong_count = []
for _label, _err_text in _OC_CASES:
    _oc_n = sum(1 for _ln in _err_text.splitlines() if _ln.startswith(_OC_PREFIX))
    if _oc_n != 1:
        _oc_wrong_count.append((_label, _oc_n))
    for _ln in _err_text.splitlines():
        if not _ln.startswith(_OC_PREFIX):
            continue
        _rest = _ln[len(_OC_PREFIX):].split()
        _tok = _rest[0] if _rest else ''
        _rem = _rest[1][len('remedy='):] if len(_rest) > 1 and _rest[1].startswith('remedy=') else ''
        _oc_seen_outcomes.add(_tok)
        _oc_seen_remedies.add(_rem)
        if _tok not in _OC_OUTCOMES or _rem not in _OC_REMEDIES:
            _oc_stray.append((_label, _ln))

# Shadow type-design: the _CHECKBOX_ROW_RE group-order contract (group 2 = state cell,
# preserved by _rewrite_checkbox / overwritten by _tick_checkbox_by_index) is pinned
# structurally, so a group reshuffle that happens to keep the index tests green but
# breaks _rewrite_checkbox's group-2 preservation is caught directly.
_m = workpad._CHECKBOX_ROW_RE.match('  - [x] hello world')

# Re-shadow pr-test Finding 1: the index form counts NESTED (indented) checkbox rows
# and skips interleaved non-checkbox lines — `_CHECKBOX_ROW_RE`'s `\s*` indent group is
# load-bearing for the docstring's "every [ ]/[x] row in document order" claim. Every
# other index fixture is flat+contiguous; this one interleaves a nested sub-item and a
# prose line so a regression anchoring the row regex at column 0 (or counting only
# top-level rows) would mis-address rather than stay green.
NESTED_PLAN = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Last updated:** 2026-05-15T00:00:00Z

## Plan
- [ ] top one
  - [ ] nested two
- [ ] top three

## Acceptance Criteria
- [ ] AC one
"""
_ft = []
out = apply_mut(NESTED_PLAN, make_args(tick_plan_n=[2]), _ft)

# Re-shadow pr-test Finding 2: the documented substring→index same-row interaction —
# a substring tick processed first makes a later index targeting that SAME row report a
# benign "already ticked" volatile miss (pins both the interaction and the intra-call
# substring-before-index ordering it depends on).
_ft = []
out = apply_mut(IDX_BODY, make_args(status='Reviewing', tick_ac=['AC two'], tick_ac_n=[2]), _ft)


print("issue #258: terminal --status Complete self-record gate")

# The gate reconciles the workpad self-record against reality at the terminal
# `--status Complete` write: a structural HARD-FAIL (raises _UpdateError → the
# cmd_update abort path exits 1 with NO PATCH) on any non-post-merge unticked AC
# row, and a NON-blocking stderr warning naming any unticked ## Plan row. It fires
# ONLY for Complete, and never modifies a `- [ ]` row.
GATE_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Documenting
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [x] **Setup**

## Plan
- [x] Plan step one
- [x] Plan step two

## Acceptance Criteria
- [x] AC one
- [x] AC two
"""
_AC_UNTICKED = GATE_BODY.replace('- [x] AC two', '- [ ] AC two')
_AC_POSTMERGE = GATE_BODY.replace('- [x] AC two', '- [ ] AC two (post-merge)')
_PLAN_UNTICKED = GATE_BODY.replace('- [x] Plan step two', '- [ ] Plan step two')

# post-merge exclusion (byte-for-byte the Phase 3.4 'line ends in (post-merge)'):
# an outstanding post-merge-only AC does NOT block — the Status flips to Complete.
out = apply_mut(_AC_POSTMERGE, make_args(status='Complete'), [])

# Plan warning is NON-blocking: the call succeeds (returns a body with Status flipped)
# and writes a warning naming the unticked Plan row to stderr.
_perr = io.StringIO()
with contextlib.redirect_stderr(_perr):
    out = apply_mut(_PLAN_UNTICKED, make_args(status='Complete'), [])

# Clean run: every row ticked → finalize is silent (no AC abort, no Plan warning).
_cerr = io.StringIO()
with contextlib.redirect_stderr(_cerr):
    out = apply_mut(GATE_BODY, make_args(status='Complete'), [])

# Gate is scoped to Complete ONLY: --status Blocked over an unticked AC is never gated.
_berr = io.StringIO()
with contextlib.redirect_stderr(_berr):
    out = apply_mut(_AC_UNTICKED, make_args(status='Blocked'), [])

# A non-Complete in-progress status that merely CONTAINS a mapped word is not gated.
_derr = io.StringIO()
with contextlib.redirect_stderr(_derr):
    out = apply_mut(_AC_UNTICKED, make_args(status='Documenting'), [])

# CLI-level: the AC hard-fail routes through cmd_update's abort path — non-zero exit,
# NO PATCH (uses the existing #169 _drive_cmd_update harness).
_code, _out, _err, _patched = _drive_cmd_update(_AC_UNTICKED, status='Complete')
# CLI-level: a post-merge-only outstanding AC finalizes (PATCH lands, Status flipped).
_code, _out, _err, _patched = _drive_cmd_update(_AC_POSTMERGE, status='Complete')

# Post-mutation ordering (the gate's load-bearing placement): the gate runs LAST, over
# the POST-mutation sections, so a SINGLE call that ticks the last outstanding AC *and*
# flips Status to Complete passes — the tick lands before the scan. This is exactly the
# Phase 4.3 finalize shape (it ticks the "PR marked ready" progress box while flipping to
# Complete). Goes RED if the gate is reordered to scan the pre-mutation body/sections.
_oerr = io.StringIO()
with contextlib.redirect_stderr(_oerr):
    out = apply_mut(_AC_UNTICKED, make_args(status='Complete', tick_ac=['AC two']), [])
# Symmetric Plan case: ticking the last Plan row in the same Complete call suppresses the
# non-blocking Plan warning — proving the Plan scan is also post-mutation, not pre-mutation.
_operr = io.StringIO()
with contextlib.redirect_stderr(_operr):
    out = apply_mut(_PLAN_UNTICKED, make_args(status='Complete', tick_plan=['Plan step two']), [])
# CLI-level: the same one-shot tick+Complete routes cleanly through cmd_update (PATCH lands).
_code, _out, _err, _patched = _drive_cmd_update(_AC_UNTICKED, status='Complete', tick_ac=['AC two'])

# Fail-open guard (shadow finding): a Complete write whose ## Acceptance Criteria section
# still holds the un-mirrored `new-body` placeholder (AC-mirroring never ran) has NO
# checkbox rows, so it does not hard-fail — but it emits a NON-blocking warning rather
# than passing silently. A genuinely AC-less issue reads the DISTINCT
# `_(none provided in issue body)_` sentinel and finalizes SILENTLY (no false warning).
_AC_PLACEHOLDER = GATE_BODY.replace(
    '- [x] AC one\n- [x] AC two', workpad._AC_PENDING_PLACEHOLDER)
_AC_NONE = GATE_BODY.replace(
    '- [x] AC one\n- [x] AC two', '_(none provided in issue body)_')
_pherr = io.StringIO()
with contextlib.redirect_stderr(_pherr):
    out = apply_mut(_AC_PLACEHOLDER, make_args(status='Complete'), [])
_nnerr = io.StringIO()
with contextlib.redirect_stderr(_nnerr):
    out = apply_mut(_AC_NONE, make_args(status='Complete'), [])


print("workpad notes: compact timestamp + nesting under ## Progress phase")

# Compact timestamp: note bullet renders `  - HH:MM:SS — {note}` (no date/T/Z),
# nested (indented) under its phase.
out = apply_mut(WORKPAD_BODY, make_args(note=['narrowed AC']))

# Status → phase mapping, incl. the Blocked fallback to the most recent
# *ticked* (completed) top-level phase.
PROGRESS = ("- [x] **Setup** — branch & workpad\n"
            "- [x] **Implement**\n  - [x] code + sweeps\n"
            "- [ ] **Review**\n- [ ] **Documentation**\n- [ ] **PR marked ready**\n")
flat = workpad._append_progress_note(PROGRESS, "orphan", "07:00:00", None)


print("workpad: status glyph / run+PR links / ## Progress / <details>")

# A workpad shaped like the single-comment template: status glyph, Run/PR
# front-matter lines, a ## Progress checklist, and Decisions/Reflection wrapped
# in <details>.
WORKPAD_V2 = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Branch:** `feat/x`
**Run:** [View run](https://example/run/1)
**PR:** _not yet created_
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [ ] **Setup** — branch & workpad
- [ ] **Implement**
  - [ ] code + sweeps
- [ ] **Review**
- [ ] **Documentation**
- [ ] **PR marked ready**

## Plan
- [ ] Step alpha

## Acceptance Criteria
- [ ] AC one
- [ ] AC two

## Decisions / Notes
<details>
<summary>Decisions / Notes (click to expand)</summary>

### Setup
- 00:00:00 — run started
</details>

## Devflow Reflection
<details>
<summary>Devflow Reflection (click to expand)</summary>

</details>
"""

# A --status Complete write now runs the issue #258 terminal self-record gate, which
# hard-fails on an unticked non-post-merge AC — so this glyph-rendering test uses a
# fully-ticked variant (its intent is the glyph, not the gate; the gate itself is
# covered in the issue #258 block above).
WORKPAD_V2_DONE = (WORKPAD_V2.replace('- [ ] AC one', '- [x] AC one')
                             .replace('- [ ] AC two', '- [x] AC two')
                             .replace('- [ ] Step alpha', '- [x] Step alpha'))
out = apply_mut(WORKPAD_V2_DONE, make_args(status='Complete'))

# Run / PR links: replace when present.
out = apply_mut(WORKPAD_V2, make_args(
    run_link='[logs](https://example/run/2)', pr_link='[#5](https://example/pr/5)'))

# Run / PR links: inserted after Branch when absent (legacy workpad resume).
LEGACY = WORKPAD_V2.replace('**Run:** [View run](https://example/run/1)\n', '') \
                   .replace('**PR:** _not yet created_\n', '')
out = apply_mut(LEGACY, make_args(run_link='R', pr_link='P'))
# Resume case: Run already present, only PR inserted → PR lands after Run, not
# above it (regression guard for the insert-after-Branch ordering bug).
RUN_ONLY = WORKPAD_V2.replace('**PR:** _not yet created_\n', '')
out = apply_mut(RUN_ONLY, make_args(pr_link='[#9](u)'))

# ## Progress ticks (incl. a nested sub-item). Progress shares the substring
# failure-isolation contract (issue #169) but has NO index form (AC 7).
out = apply_mut(WORKPAD_V2, make_args(
    tick_progress=['**Setup**', 'code + sweeps']))
# Ambiguous --tick-progress is a volatile miss too: the batched --status survives
# and the miss is collected (pre-#169 this aborted the whole call).
_ft = []
out = apply_mut(WORKPAD_V2, make_args(status='Blocked', tick_progress=['**']), _ft)

# Legacy resume: WORKPAD_V2 still carries a pre-change separate ## Decisions /
# Notes section. --note now writes into ## Progress, must NOT error, and must
# leave that legacy section (and its existing bullets) intact (AC: resuming a
# pre-change workpad doesn't error or drop note content).
out = apply_mut(WORKPAD_V2, make_args(status='Implementing', note=['fresh note']))
# <details>: --reflection appends inside the (initially empty) Reflection block.
out = apply_mut(WORKPAD_V2, make_args(reflection=['reflect!']))


print("workpad reflection grouping by --reflection-kind (issue #126)")


print("workpad reflection new kinds + interpolation-safe input (issue #476)")

# stdin arm: --reflection-file - decodes UTF-8 from sys.stdin.buffer.
class _FakeStdin:
    def __init__(self, data):
        self.buffer = io.BytesIO(data)

# Invariants preserved: marker first line; AC section still parseable.
out = apply_mut(WORKPAD_V2, make_args(
    status='Reviewing', note=['n'], reflection=['r'], tick_ac=['AC one']))


print("workpad new-body: lean initial skeleton")

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    workpad.cmd_new_body(argparse.Namespace(
        issue=7, run_link='[View run](https://x/1)', branch=None, marker=None))
_nb = _buf.getvalue()
# The skeleton round-trips through the mutation engine (gate creates it, the
# claude job then mutates the same comment).
_rt = apply_mut(_nb, make_args(tick_progress=['**Setup**'], note=['go']))


print("workpad prompt-extension Progress rows (issue #1462)")


print("workpad implement-driven review Progress rows (issue #1657)")

# --- no new row breaks an EXISTING tick, and each new row ticks uniquely -----
# The live tick-substring set is DERIVED from the implement phase files rather
# than transcribed here, so a `--tick-progress` site added later is caught by
# this assertion instead of silently colliding with a row.
_IMPL_SKILL_DIR = Path(__file__).resolve().parents[2] / 'skills' / 'implement'
_tick_md = [(_p, _p.read_text(encoding='utf-8'))
            for _p in sorted(_IMPL_SKILL_DIR.rglob('*.md'))]  # tree-walk-ok: anchored to skills/implement/, which cannot reach the sibling checkouts under .claude/worktrees/ a repo-root-anchored walk would descend into

# ---------------------------------------------------------------------------
# #1550 `workpad.py --help` / `update --help` — the SOLE workpad-CLI reference the
# implement orchestrator reads since #1549 — documents every subcommand and update-flag
# the phase files invoke; a dropped `help=` for an invoked one fails RED here.
# ---------------------------------------------------------------------------
# Strip double-quoted operand spans before scanning a `workpad.py update` slice for
# flags: else a `--reflection`/`--note` operand's prose naming another flag is captured
# as a bogus update-flag that `update --help` does not list.
_UPD_RE_1550 = re.compile(r"workpad\.py\s+update\b")
_FLAG_RE_1550 = re.compile(r"--[a-z][a-z-]+")
_live_flags_1550 = set()
for _p, _txt in _tick_md:
    _lines = _txt.split('\n')
    for _i, _ln in enumerate(_lines):
        if not _UPD_RE_1550.search(_ln):
            continue
        _slice = [_ln]
        _j = _i
        while _slice[-1].rstrip().endswith('\\') and _j + 1 < len(_lines):
            _j += 1
            _slice.append(_lines[_j])
        _blob = '\n'.join(_slice)
        _tail = _blob[_UPD_RE_1550.search(_blob).start():]
        _tail = re.sub(r'"[^"]*"', ' ', _tail, flags=re.DOTALL)
        for _fm in _FLAG_RE_1550.finditer(_tail):
            _live_flags_1550.add(_fm.group(0))
_live_flags_1550 = sorted(_live_flags_1550)

# Do not replace this parse with a hand-written line number for the first child
# process: it rots on the next edit above it, and the assertion then compares the
# statement against a line that no longer spawns anything.
_SRC_1653 = Path(__file__).resolve().read_text(encoding='utf-8')
_TREE_1653 = ast.parse(_SRC_1653)
# Keep both sets complete for their module: omitting a spawner silently moves the
# earliest-child line later and weakens the ordering assertion. Add an alias scan
# before introducing a spawner from another module.
_SPAWNERS_1653 = {'run', 'Popen', 'call', 'check_call', 'check_output',
                  'getoutput', 'getstatusoutput'}
_OS_SPAWNERS_1653 = {'system', 'popen', 'startfile', 'fork', 'forkpty',
                     'posix_spawn', 'posix_spawnp',
                     'spawnl', 'spawnle', 'spawnlp', 'spawnv', 'spawnve', 'spawnvp',
                     'spawnvpe', 'execl', 'execle', 'execlp', 'execv', 'execve',
                     'execvp', 'execvpe'}
# Both keys are scanned, so moving either one below a child process fails this —
# keying on PYTHON_COLORS alone would pass a tree whose NO_COLOR was left late.
_ENV_KEYS_1653 = {'PYTHON_COLORS', 'NO_COLOR'}
# Derive the os aliases too, never a hardcoded pair: this file's idiom is a per-block
# aliased import, so a later `import os as _os1700` spawning through that name would
# otherwise escape the scan and move the earliest-child line later unnoticed.
_sp_aliases_1653 = set()
_os_aliases_1653 = set()
_bare_spawners_1653 = set()
for _n in ast.walk(_TREE_1653):
    if isinstance(_n, ast.Import):
        for _a in _n.names:
            if _a.name == 'subprocess':
                _sp_aliases_1653.add(_a.asname or _a.name)
            elif _a.name == 'os':
                _os_aliases_1653.add(_a.asname or _a.name)
    elif isinstance(_n, ast.ImportFrom) and _n.module == 'subprocess':
        for _a in _n.names:
            if _a.name in _SPAWNERS_1653:
                _bare_spawners_1653.add(_a.asname or _a.name)

_child_linenos_1653 = []
for _n in ast.walk(_TREE_1653):
    if not isinstance(_n, ast.Call):
        continue
    _f = _n.func
    if isinstance(_f, ast.Attribute) and isinstance(_f.value, ast.Name):
        if (_f.attr in _SPAWNERS_1653 and _f.value.id in _sp_aliases_1653) \
           or (_f.attr in _OS_SPAWNERS_1653 and _f.value.id in _os_aliases_1653):
            _child_linenos_1653.append(_n.lineno)
    elif isinstance(_f, ast.Name) and _f.id in _bare_spawners_1653:
        _child_linenos_1653.append(_n.lineno)

# Take each key's EARLIEST module-scope assignment, never the latest: this file's own
# idiom for a temporary override is a module-scope save/restore block, so a max() would
# false-RED on a later legitimate one with a message naming the wrong cause.
_env_stmt_linenos_1653 = {}
for _n in _TREE_1653.body:
    if not isinstance(_n, ast.Assign):
        continue
    for _t in _n.targets:
        if isinstance(_t, ast.Subscript) and isinstance(_t.value, ast.Attribute) \
           and _t.value.attr == 'environ' and isinstance(_t.slice, ast.Constant) \
           and _t.slice.value in _ENV_KEYS_1653:
            _env_stmt_linenos_1653.setdefault(_t.slice.value, _n.lineno)
del _SRC_1653, _TREE_1653  # nothing below reads these


print("workpad reproduction-row reconcile + classification-note supersede (issue #449)")

# The Phase 2.1.5 reproduce-first gate now fires on a recorded *content*
# classification, not the `bug` label. Phase 1.3 records the classification as a
# superseding `classification: ` note and reconciles the bug-only "reproduction
# captured" Progress row to match it, on every entry — so a gate-created skeleton
# (rendered from the label) always agrees with the classification before Phase 2.

# A non-bug skeleton: Implement carries only `code + sweeps` (no repro row).
_WP_NONBUG = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #449

**Status:** Setup
**Branch:** `x`
**Last updated:** 2026-07-13T00:00:00Z

## Progress
- [ ] **Setup** — branch & workpad
  - 00:00:00 — /devflow:implement run started
- [ ] **Implement**
  - [ ] code + sweeps
- [ ] **Review**
- [ ] **Documentation**
- [ ] **PR marked ready**

## Plan
- [ ] Step alpha

## Acceptance Criteria
- [ ] AC one

## Devflow Reflection
"""

# note-supersede: recording a classification replaces any existing `classification: `
# note, so the workpad carries exactly one at all times, in the exact form.
_c1 = apply_mut(_WP_NONBUG, make_args(
    record_classification=['non-bug', 'reads as a feature request']))
_c2 = apply_mut(_c1, make_args(
    record_classification=['bug-report', 'quoted stack trace in the body']))


print("parse_acs._is_post_merge")


print("parse_acs.extract_section / _parse_checkboxes / _render_md")

# ── issue #1198: a `## Acceptance Criteria` section that is present with content
# but yields zero items (bold paragraphs / numbered list) is made DISTINGUISHABLE
# from a genuinely-absent section, WITHOUT changing the accepted item shape and
# WITHOUT a non-zero exit (a non-zero exit would trip the fail-closed §1.2 fence
# and halt the run, which the owner ruling forbids). The signal is on stderr and
# in the --format json output; the accepted shape is unchanged, so these are NOT
# a re-add of the existing shape assertions above.
#
# The interface-level predicate: unreadable = section matched with content AND
# zero items. Absent = no matched content. Parsed = >=1 item.
_UNREADABLE_BOLD = ("## Acceptance Criteria\n\n"
                    "**AC1 - the first thing.** Narrative sentence here.\n"
                    "*Desk check:* run the command.\n"
                    "**AC2 - the second.** More prose.\n")
_ABSENT = "## Summary\nno acceptance-criteria section at all\n"
_PARSED = "## Acceptance Criteria\n- [ ] one\n- [ ] two\n"

def _unreadable(body):
    lines = parse_acs.extract_section(body, 'Acceptance Criteria')
    return parse_acs._is_unreadable_section(parse_acs._parse_checkboxes(lines), lines)

# CLI level: drive parse_acs.main() over each body and assert (a) it always
# exits 0, and (b) the --format json output carries the acceptance_criteria_unreadable
# field with the right value. main() returns normally (no sys.exit) on success,
# so a SystemExit would be a regression; catch it and surface the code.
def _run_parse_acs_json(body):
    """Return (exit_code_or_None, parsed_json_dict, stderr_text)."""
    import tempfile
    saved_argv = sys.argv[:]
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(body)
        path = f.name
    sys.argv = ['parse-acs.py', '--body-file', path, '--format', 'json']
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            parse_acs.main()
    except SystemExit as e:  # pragma: no cover - regression signal only
        code = e.code if e.code is not None else 0
    finally:
        sys.argv = saved_argv
        os.unlink(path)
    return code, _json.loads(out.getvalue()), err.getvalue()

_code, _j, _err = _run_parse_acs_json(_UNREADABLE_BOLD)

_code, _j, _err = _run_parse_acs_json(_ABSENT)

_code, _j, _err = _run_parse_acs_json(_PARSED)

# The parallel `## Test Plan` path routes through the same `_diagnose_section`
# with different canonical/needle args ('Test Plan'/'test plan'), so it needs
# its own coverage — a copy-paste wiring error could leave the AC path green
# while the test-plan path is wrong.
_TP_UNREADABLE = ("## Test Plan\n"
                  "1. Run the suite.\n"
                  "2. Confirm the new field.\n")
_code, _j, _err = _run_parse_acs_json(_TP_UNREADABLE)
# And a parsed Test Plan reports test_plan_unreadable=false.
_code, _j, _err = _run_parse_acs_json("## Test Plan\n- [ ] run the suite\n")

# ── issue #254: hard-wrapped criteria (the ~80-column format /devflow:create-issue
# emits) must join indented continuation lines into ONE criterion, and a post-merge
# trigger phrase sitting on a continuation line must still classify. The old parser
# matched only the checkbox line itself, truncating each item to its first physical
# line and blinding the classifier to any trigger past the wrap.
WRAPPED_AC = """## Acceptance Criteria
- [ ] The parser joins each checkbox item's indented continuation lines into
      one criterion string so a hard-wrapped criterion round-trips verbatim
      into the workpad mirror.
- [ ] The deploy step is exercised and the result is confirmed
      in production after the release ships.
"""
_w = parse_acs._parse_checkboxes(parse_acs.extract_section(WRAPPED_AC, 'Acceptance Criteria'))

# Review iter (PR #255 receiving-review, test-gap): TAB-indented continuation lines join too
# (the continuation guard is `line[:1] in (' ', '\t')`); prior fixtures used only space
# indentation, leaving the `\t` branch unexercised.
WRAPPED_AC_TAB = "## Acceptance Criteria\n- [ ] Tab-wrapped criterion first line\n\tand its tab-indented continuation.\n"
_t = parse_acs._parse_checkboxes(parse_acs.extract_section(WRAPPED_AC_TAB, 'Acceptance Criteria'))

# Review iter (PR #255 receiving-review, test-gap): a post-merge trigger phrase SPLIT across
# the wrap boundary (no single physical line contains it) must still classify post-merge,
# because classification runs on the fully-joined text. This is the core reason the join
# feeds the post-merge scan — pin it directly.
WRAPPED_AC_SPLITTRIG = ("## Acceptance Criteria\n"
                        "- [ ] Update the changelog after\n"
                        "      merge so the entry reconciles.\n")
_st = parse_acs._parse_checkboxes(parse_acs.extract_section(WRAPPED_AC_SPLITTRIG, 'Acceptance Criteria'))


print("file_deferrals._derive_area / _compute_id / _format_line_range / _render_issue_body")

_body = file_deferrals._render_issue_body(
    [{'severity': 'High', 'agent': 'sec', 'file': 'a.py', 'line_range': [1, 2],
      'symbol': 'foo', 'kind': 'bug', 'summary': 'x', 'category': 'scope',
      'explanation': 'later'}],
    source_issue=40, pr_number=77)

print("file_deferrals._create_issue (#245: OSError from an unrunnable gh must "
      "raise RuntimeError, not a raw traceback)")


print("match_deferrals._extract_block / _parse_yaml_payload (hidden-comment payload)")

# New-format PR body: a human-readable Markdown table is the VISIBLE content
# inside the START/END markers, and the exact machine payload lives in a hidden
# DEVFLOW_DEFERRED_PAYLOAD HTML comment (invisible in rendered Markdown). The
# matcher must parse the payload from the hidden comment, not the visible table.
NEW_FORMAT_BODY = """## Summary
- did a thing

## Deferred Findings
<!-- DEVFLOW_DEFERRED_FINDINGS_START -->
These review-agent findings were deferred under the Scope-Acknowledged Findings contract.

| Severity | File | Finding | Follow-up |
| --- | --- | --- | --- |
| Important | `a.py:10-12` | thing one | #41 |
| Suggestion | `b.py:5-5` | thing two (no issue) | — |

<!-- DEVFLOW_DEFERRED_PAYLOAD
schema_version: 1
deferrals:
  - id: dfr-aaa111
    finding:
      agent: code-reviewer
      severity: Important
      file: a.py
      line_range: [10, 12]
      symbol: foo
      kind: bug
      summary: |
        thing one
    reason:
      category: out-of-scope
      explanation: |
        later
    follow_up:
      issue: 41
      url: https://example/issues/41
      filed_at: 2026-05-26T00:00:00Z
      filed_by: claude
  - id: dfr-bbb222
    finding:
      agent: code-reviewer
      severity: Suggestion
      file: b.py
      line_range: [5, 5]
      symbol: bar
      kind: style
      summary: |
        thing two
    reason:
      category: claim-quality
      explanation: |
        minor
    follow_up: {}
-->
<!-- DEVFLOW_DEFERRED_FINDINGS_END -->

## Test Plan
- [ ] run it
"""

_blk = match_deferrals._extract_block(NEW_FORMAT_BODY)
_payload = match_deferrals._parse_yaml_payload(_blk)

print("match_deferrals #621: settled-by-disclosure foreclosure disclosure-verification guard")

import json

# main()-level drive: a foreclosure entry is honored (reason.category discriminator).
print("match_deferrals #621: main() honors a valid foreclosure with null follow_up")
_fore_body = """<!-- DEVFLOW_DEFERRED_FINDINGS_START -->
<!-- DEVFLOW_DEFERRED_PAYLOAD
schema_version: 1
deferrals:
  - id: dfr-fore
    finding:
      agent: code-reviewer
      severity: Suggestion
      file: scripts/thing.py
      line_range: [10, 12]
      symbol: ""
      kind: quality
      summary: |
        effective model resolution finding
    reason:
      category: settled-by-disclosure
      explanation: |
        answered by shipped disclosure
    disclosure:
      path: docs/d.md
      phrase: "shipped disclosure sentence"
-->
<!-- DEVFLOW_DEFERRED_FINDINGS_END -->"""

# Existing-shape entries (reason.category in the three legacy values) keep today's
# behavior end to end — the new foreclosure branch never intercepts them. Drive an
# out-of-scope entry with a valid follow_up + cross-link and assert it is honored
# exactly as before (reason.category is the exact old/new discriminator).
print("match_deferrals #621: an old-shape out-of-scope entry keeps today's behavior")
_old_body = _fore_body.replace("category: settled-by-disclosure",
                               "category: out-of-scope").replace(
    "    disclosure:\n      path: docs/d.md\n      phrase: \"shipped disclosure sentence\"\n",
    "    follow_up:\n      issue: 41\n      url: https://example/issues/41\n")

# --- #660 review: coverage the #621 batch left open -------------------------
# The two _verify_disclosure arms that had no fixture. Both are fail-closed
# rejections, so a regression (a dropped arm) would fail OPEN with the suite
# otherwise green — exactly the class a green suite cannot catch unpinned.
print("match_deferrals #660: the two remaining _verify_disclosure fail-closed arms")

# Path normalization (#660 review, Important): the self-foreclosure exclusion
# compared RAW disclosure.path against canonical `b/<path>` diff keys, so a
# non-canonical spelling of a diffed file evaded it and failed OPEN — honoring a
# finding whose disclosure the PR itself authored. Both operands now normalize.
print("match_deferrals #660: non-canonical disclosure.path still self-forecloses")


# main()-level REJECT wiring. The guard functions are unit-pinned above, but
# nothing drove main()'s foreclosure rejection branches end to end: a dropped
# `continue` or an inverted `is not None` would honor a foreclosure whose
# disclosure never verified, with every unit fixture still green.
print("match_deferrals #660: main() REJECTS an unverifiable foreclosure (fail-closed wiring)")

print("match_deferrals #660: main() REJECTS a foreclosure that widens the diff surface")


print("file_deferrals #621: a settled-by-disclosure manifest files no issue and exits 0")


print("match_deferrals._check_issue_cross_link (#245: gh-exec-failure vs. genuine "
      "issue-unreadable must not be conflated)")

print("match_deferrals._config_get (#245: a broken config-get.sh must not be "
      "silently indistinguishable from a legitimately-unset key)")


# ---------------------------------------------------------------------------
# resolve_review_overrides.resolve_overrides — per-subagent model/effort
# overrides for the /devflow:review engine. Covers the four AC cases: specific
# entry wins, default-fallback, no-entry (no override emitted), and invalid
# effort (warn + drop to session effort, model still forwarded).
# ---------------------------------------------------------------------------
_rro = resolve_review_overrides

# Specific entry wins over default; default supplies only no-entry agents.
_raw = {
    "default": {"effort": "medium"},
    "devflow:code-reviewer": {"model": "opus", "effort": "high"},
    "devflow:checklist-deduper": {"model": "haiku", "effort": "low"},
}
_res, _warn = _rro.resolve_overrides(
    _raw,
    ["devflow:code-reviewer", "devflow:checklist-deduper",
     "devflow:checklist-verifier"],
)
_rro.read_raw = lambda agents, config_get, config: (
    {"devflow:checklist-generator": {"effort": "low"}}, [])

# read_raw integration (exercises the real config-get.sh I/O path, not just the
# pure resolver). The empty-own-entry contract must hold END-TO-END: the leaf
# reads alone can't tell {} from an absent key, so read_raw probes the entry
# object — this test guards that the probe stays wired (a pure-function test
# alone would pass while the real config path silently let `default` backfill).
import os as _os
import tempfile as _tempfile

# ---------------------------------------------------------------------------
# Namespace-alias resolution. .prflow/config.schema.json enumerates each
# review-engine subagent under EVERY declared plugin namespace — the canonical
# `prflow:` and the `devflow:` alias, "so an override committed before the
# plugin rename keeps resolving" — while the engine dispatches only the
# canonical spelling. A key-equality lookup therefore read the dispatched
# spelling and silently discarded an alias-keyed override the schema declares
# valid. These assertions fail if that alias stops resolving.
# ---------------------------------------------------------------------------
_ns = _rro.AGENT_NAMESPACES
_both_b = {"devflow:code-reviewer": {"model": "sonnet"},
           "prflow:code-reviewer": {"model": "opus"}}
_pb, _ = _rro.resolve_overrides(_both_b, ["prflow:code-reviewer"])

# main() CLI contract the engine depends on: pure JSON to stdout, warnings to
# stderr (never stdout), exit 0 on config shape, and an unknown-agent warning.

_out, _err = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(_out), contextlib.redirect_stderr(_err):
    _rc = _rro.main(["devflow:code-reviewer", "--config", "/nonexistent/c.json"])

_out2, _err2 = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(_out2), contextlib.redirect_stderr(_err2):
    _rc2 = _rro.main(["pr-review-tookit:code-reviewer", "--config", "/nonexistent/c.json"])
_mo, _me = io.StringIO(), io.StringIO()
_ro, _re = io.StringIO(), io.StringIO()

# Duplicate dispatched ids must not destabilize output: read_raw/resolve key by
# agent, and the unknown-id warning is deduped (dict.fromkeys) to one line.
_do, _de = io.StringIO(), io.StringIO()

# ── #636: demotion stderr breadcrumbs ─────────────────────────────────────────────────────
# A demotion is the ONLY mechanism that turns a would-be exit 1 into exit 0, and it was
# silent — indistinguishable from ordinary no-referent UNRESOLVABLE noise without grepping
# the detail prefix. `_demotion_breadcrumbs` surfaces it on stderr (per-row + one summary),
# keying on the sole demotion signature (UNRESOLVABLE verdict + RELOCATED_PREFIX detail).
_RP = stale_prose_lint.RELOCATED_PREFIX
_U = stale_prose_lint.UNRESOLVABLE


def _demote_bc(rows):
    _err = io.StringIO()
    _n = stale_prose_lint._demotion_breadcrumbs(rows, _err)
    return _n, _err.getvalue()

# Two demotions across different files: both breadcrumbs + a count-2 summary.
_n2, _out2 = _demote_bc([
    stale_prose_lint.Row(_U, "R1", "a.md", 3, _RP + "d1"),
    stale_prose_lint.Row(_U, "R4", "b/c.rst", 9, _RP + "d2"),
])

print()
print("issue-audit-state: the motivating regression (issue #546)")

print()
print("issue-audit-state: the transition table (issue #546)")


def _state(rounds, revisions=(), overrides=(), nonce='n0', reinit=False):
    return {'schema_version': issue_audit_state.SCHEMA_VERSION, 'slug': 's',
            'nonce': nonce, 'reinit_forced': reinit, 'automatic_reaudits_used': 0,
            'user_rounds_used': 0, 'rounds': list(rounds),
            'revisions': [{'ordinal': i + 1, 'after_round': r, 'floor_round': r}
                          for i, r in enumerate(revisions)],
            'overrides': list(overrides), 'creation': None}


def _round(num, arm, outcome, digest='D1', findings=0, degraded=False, markers=(),
           adj=None, unresolved=None, must_revise=None, advisory=None, invalid=None,
           # issue #709. The default is the ESTABLISHED record so every pre-#709 fixture
           # keeps meaning what it meant — "an ordinary completed round" — instead of
           # silently becoming a steering-withheld one and re-testing the new gate at
           # every unrelated row. Rows that mean to exercise the withheld path pass
           # steering=None (no record at all) or an explicit not-established dict.
           steering=None):
    if steering is None:
        steering = {'state': 'established', 'reason': 'canonical-match'}
    return {'round': num,
            'attempts': [{'arm': arm, 'digest': digest, 'body_digest': 'B' + digest,
                          'sentinel_open': None, 'sentinel_close': None,
                          'instructions': None}],
            'steering': steering,
            'no_parseable_retry_used': False, 'unreadable_retry_used': False,
            'outcome': outcome, 'findings_count': findings,
            'consumer_dimensions_appended': False, 'embed_markers': list(markers),
            'degraded': degraded,
            # #548 post-adjudication payload; None on every field = not yet adjudicated.
            'adjudicated_verdict': adj, 'unresolved_must_revise': unresolved,
            'must_revise_count': must_revise, 'advisory_count': advisory,
            'invalid_count': invalid}


# eligibility_grounds_table — the two approve-mode grounds and every not-eligible class.
_clean_file = _state([_round(1, 'file', 'FILE', 'D1')])


print()
print("issue-audit-state: tiered draft-root binding (issue #562)")
# Ordering: a PREDATING file-arm dispatch that shares the digest cannot prove landing, so the
# predicate reports 'unestablished' (not 'no' — nothing proves the write failed either).
_pre = _state([_round(1, 'file', 'FILE', 'D2')])
_pre['revisions'] = [{'ordinal': 1, 'after_round': 1, 'floor_round': 1,
                      'stdin_digest': 'D2'}]
# (5) Do not edit one copy of the duplicated `effective_unresolved`/`markers` renderers: the
#     cross-render state above resolves both to their None arm, so only these rows catch it.
_bf = dict(issue_audit_state.summary_fields(None))
_bf['effective_unresolved'] = 2
_bf['adjudicated_verdict'] = 'REVISE'
_bf['markers'] = ['file-unreadable', 'write-failed']
# Positive control for the `except AssertionError: raise` arm above: do not widen the swallow
# to cover AssertionError — a self-check failure is a TOOL defect main() must name as a contract
# violation, not one more environment hiccup on stderr.
_ae_orig = issue_audit_state._summary_block_line
_ae_out, _ae_err = io.StringIO(), io.StringIO()
try:
    def _ae_boom(_fields):
        raise AssertionError('self-check tripped')
    issue_audit_state._summary_block_line = _ae_boom
    with contextlib.redirect_stdout(_ae_out), contextlib.redirect_stderr(_ae_err):
        try:
            issue_audit_state._emit_next_call('record-degraded', argparse.Namespace(
                cmd='record-degraded', slug='no-such-slug-1803', nonce='n0', round=None,
                draft_file=None), {})
            _ae_raised = None
        except AssertionError as exc:
            _ae_raised = str(exc)
finally:
    issue_audit_state._summary_block_line = _ae_orig

# eligibility_token_rows — deterministic, idempotent, digest-bound.
_t1 = issue_audit_state.evaluate_eligibility(_clean_file, 'approve', 'D1')['token']

print()
print("issue-audit-state: post-adjudication actionability, T1, convergence (issue #548)")

print()
print("issue-audit-state: the malformed-state matrix (issue #546)")

# The CLAUDE.md adversarial input-shape matrix, widened to this tool-owned state JSON.
# Every row must raise StateError (queries then answer state-unestablished, exit 0;
# mutations exit non-zero with a named breadcrumb) — never a crash presented as a value.
_GOOD = {'schema_version': issue_audit_state.SCHEMA_VERSION, 'slug': 's', 'nonce': 'n0',
         'rounds': [], 'revisions': [], 'overrides': []}


def _malformed(name, doc, slug='s'):
    assert_raises(f"#546 malformed-state matrix: {name}", issue_audit_state.StateError,
                  lambda: issue_audit_state._validate(doc, slug))

print()
print("issue-audit-state: review-round hardening (issue #546, PR #552 review)")

print()
print("issue-audit-state: shadow-round hardening (issue #546, PR #552 shadow review)")

print()
print("issue-audit-state: iteration-3 hardening (issue #546, PR #552 review)")

# issue #709 malformed-state rows. The #718 review found the ~10 new `_validate` raise
# sites carried no matrix row at all — including the state<->reason PAIR check, whose own
# comment says it exists to stop a forged `{established, no-instructions-file}` record
# from walking the run past the gate. Without a row, the obvious "simplify" (check the two
# fields independently) restores that fail-open with a green suite.
def _round709(**kw):
    """A completed file-arm round whose steering/instructions records are overridable."""
    r = _round(1, 'file', 'FILE')
    if 'instructions' in kw:
        r['attempts'][0]['instructions'] = kw.pop('instructions')
    r.update(kw)
    return r


_GOOD_INSTR = {'digest': 'I1', 'instructions_path': '/abs/instr.md',
               'draft_path': '/abs/draft.md', 'template_path': None}
# The positive control for the instructions-record rows above: the same record shapes,
# well-formed, are ACCEPTED — so the rows prove the validator discriminates rather than
# rejecting any round carrying these keys at all.
issue_audit_state._validate(dict(_GOOD, rounds=[_round709(instructions=_GOOD_INSTR)]), 's')

print()
print("issue-audit-state: convergence-shadow hardening (issue #546, PR #552 shadow)")

print()
print("issue-audit-state: coverage-gap rows (issue #546, PR #552 review)")

# ── issue #1040: write-serialization sentinel + per-writer temp path ───────────────
print()
print("issue-audit-state: #1040 write-serialization (state_section + mkstemp)")

# contend_then_acquire_after_release: a FRESH (non-stale) sentinel held by "another writer"
# that is released within the acquire window — the mutation must WAIT (FileExistsError →
# sleep → retry) and then acquire once the plain release frees the sentinel, NOT via a
# stale-break. Driven deterministically by a threading.Timer that unlinks the planted
# sentinel ~60ms in, with stale_after_s large enough that no break happens. This is the
# retry-loop's acquire-after-plain-release branch — the mechanism's whole purpose.
import threading as _threading1040

# _StateSection reads its two bounds from the test-only env vars (the mechanism the shell
# tests drive the process boundary with).
os.environ['DEVFLOW_IAS_ACQUIRE_WINDOW_S'] = '0.30'
os.environ['DEVFLOW_IAS_STALE_AFTER_S'] = '0.10'

# ── stdin-hoist behavior (issue #1040) ─────────────────────────────────────────────
# _selects_stdin mirrors each handler's own arg-based read trigger.
def _ns(**kw):
    return argparse.Namespace(**kw)

# stdlib_only_imports: the module imports only the standard library, and neither fcntl nor
# msvcrt.
_ias1040_tree = ast.parse((SCRIPTS / 'issue-audit-state.py').read_text(encoding='utf-8'))
_ias1040_imports = set()
for _node in ast.walk(_ias1040_tree):
    if isinstance(_node, ast.Import):
        for _al in _node.names:
            _ias1040_imports.add(_al.name.split('.')[0])
    elif isinstance(_node, ast.ImportFrom) and _node.module and _node.level == 0:
        _ias1040_imports.add(_node.module.split('.')[0])

# ─────────────────────────────────────────────────────────────────────────────
# Issue #537 — startup-lifecycle observability: handoff-state, --checkpoint,
# --expect-comment-id / --expect-status.
# ─────────────────────────────────────────────────────────────────────────────

def _handoff(payload, issue=537, run_id="29624899689", run_attempt="1",
             write=True, raw=None):
    """Drive workpad.cmd_handoff_state offline and return (exit, stdout, stderr).
    `payload` is a dict/list/scalar dumped as JSON, or `raw` is written verbatim;
    write=False omits the file entirely (missing-file case)."""
    d = tempfile.mkdtemp()
    p = Path(d) / "handoff.json"
    if write:
        if raw is not None:
            p.write_text(raw, encoding="utf-8")
        else:
            p.write_text(_json.dumps(payload), encoding="utf-8")
    ns = argparse.Namespace(file=str(p), issue=issue, run_id=run_id,
                            run_attempt=run_attempt)
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            workpad.cmd_handoff_state(ns)
    except SystemExit as e:
        code = e.code
    return code, out.getvalue().strip(), err.getvalue()


_VALID = {"schema_version": 1, "issue": 537, "run_id": "29624899689",
          "run_attempt": "1", "origin": "created-current-run"}

# AC3: a valid record validates offline and prints its origin, exit 0, no breadcrumb.
_c, _o, _e = _handoff(_VALID)
# AC11: a valid record whose origin is the explicit `unknown` token prints unknown
# with NO breadcrumb — distinct from a degraded shape.
_c, _o, _e = _handoff({**_VALID, "origin": "unknown"})

# AC4 (type arms, breadcrumb-specific): a run_id that is not a digit STRING (a bare
# int) and a run_attempt that is a non-digit string each degrade to unknown through
# their OWN type guard — asserted on the branch-specific breadcrumb, since the
# following identity-mismatch guard would also degrade the outcome (defense in
# depth), so an outcome-only check cannot pin the type branch itself.
_c, _o, _e = _handoff({**_VALID, "run_id": 29624899689})
_c, _o, _e = _handoff({**_VALID, "run_attempt": "x"})
# The `issue` field's own type guard is likewise masked by the following identity
# guard (a string "537" degrades to unknown via EITHER the type guard OR "537" != 537),
# so pin the branch-specific breadcrumb, mirroring the run_id/run_attempt arms above —
# the generic `_deg` row "wrong field type (issue str)" only asserts the shared
# origin=unknown breadcrumb and cannot distinguish the type guard from the mismatch path.
_c, _o, _e = _handoff({**_VALID, "issue": "537"})

# ── --checkpoint idempotent keyed Progress rows (AC14/15/16) ──────────────────
_CP_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Branch:** `x`
**Last updated:** 2026-05-15 00:00 UTC

## Progress
- [ ] **Setup** — branch & workpad
  - 02:00:00 — /devflow:implement run started
- [ ] **Implement**

## Plan
- [ ] step

## Acceptance Criteria
- [ ] AC1

## Devflow Reflection
<details>
<summary>Devflow Reflection (click to expand)</summary>

</details>
"""
_CPKEY = "gha:29624899689:1:claude-invoke"
_MK = workpad._checkpoint_marker(_CPKEY)

# AC14: a first checkpoint writes exactly one visible row carrying one hidden marker.
_out = apply_mut(_CP_BODY, make_args(checkpoint=[[_CPKEY, "Claude job setup complete; invoking agent"]]))

# AC14: a replay COMBINED with another mutation applies that mutation once,
# adds no duplicate checkpoint.
_out2 = apply_mut(_out, make_args(checkpoint=[[_CPKEY, "x"]], status="Reviewing"))

# AC16 (failure isolation at the process level): a checkpoint-only replay through
# cmd_update makes NO PATCH and exits 0.
_code, _out, _err, _patched = _drive_cmd_update(_CP_BODY.replace(
    "  - 02:00:00 — /devflow:implement run started",
    "  - 02:00:00 — /devflow:implement run started\n  - 02:01:00 — invoke " + _MK),
    checkpoint=[[_CPKEY, "x"]])

# #1050 (Slice A): the Phase 4.3 checkpoint-4 evidence record uses the SAME keyed-checkpoint
# mechanism through the fixed key `base-update-checkpoint-4`, whose marker `lib/fetch-pr-context.sh`
# reads into `base_update_checkpoint4_present`. Assert this specific key end-to-end: it is a VALID
# key (accepted, not gha:-prefixed), a first write inserts exactly one hidden marker, a same-key
# replay is a pure no-op (so a stall-backstop-resumed Phase 4.3 does not double-record), and a
# non-canonical body is a STRUCTURAL failure with zero PATCH. The phase prose once degraded that
# to `--note`; issue #1348 removed that fallback outright and gates the terminal Complete write on
# the keyed row, so a non-canonical-body failure now fails Phase 4.3 closed rather than degrading.
_CP4_KEY = "base-update-checkpoint-4"
_MK4 = workpad._checkpoint_marker(_CP4_KEY)
# The absent-## Progress shape was a structural failure here until issue #1347; it is
# now repaired, so the run records rather than failing. The two shapes that DO still fail
# closed (a duplicated ## Progress, an empty body) are pinned in the #1347 block below;
# issue #1348 removed the §4.3 `--note` degrade, so those failures now fail Phase 4.3
# closed at the terminal gate rather than degrading to an unkeyed carrier.
_code, _out, _err, _patched = _drive_cmd_update(
    _CP_BODY.replace("## Progress", "## Notprogress"), checkpoint=[[_CP4_KEY, "t"]])

# ---------------------------------------------------------------------------
# #1347: hardening the checkpoint-4 producer — (1) `--checkpoint` repairs an ABSENT
# `## Progress`, (2) the declared required-artifact keys carry a tier-refused sibling,
# (3) `--strip-inherited-checkpoints` clears an inherited row on the resume arm.
# ---------------------------------------------------------------------------

# (1) The repair. An otherwise intact body missing ONLY `## Progress` had no working
# path at all before this: `--checkpoint` raised, and the then-documented `--note` degrade
# (removed outright by issue #1348) located the same section and raised too. Now the section is created at the HEAD of
# the section list (the canonical skeleton order Progress -> Plan -> AC -> Reflection)
# and the row is written, so the run self-heals mid-flight.
_NOPROG_BODY = """<!-- prflow:workpad -->
# PRFlow Workpad — Issue #1347

**Status:** 🚀 Documenting
**Branch:** `b`
**Last updated:** 2026-08-05 00:00 UTC

## Plan
- [ ] step

## Acceptance Criteria
- [ ] criterion
"""
# The repair runs AHEAD of the section-shape validation, proven at the process level:
# the same body that made no PATCH before now PATCHes a body carrying the marker.
_code, _out, _err, _patched = _drive_cmd_update(_NOPROG_BODY, checkpoint=[[_CP4_KEY, "tok"]])

# (1c) The two remaining fail-closed shapes keep raising structurally with no PATCH.
_DUP_PROG = _CP_BODY.replace("## Plan", "## Progress\n- [ ] dup\n\n## Plan", 1)
_code, _out, _err, _patched = _drive_cmd_update(_DUP_PROG, checkpoint=[[_CP4_KEY, "t"]])
_MARKER_OUTSIDE = _CP_BODY.replace("## Plan", f"## Plan\n- stray {_MK4}", 1)
_code, _out, _err, _patched = _drive_cmd_update(_MARKER_OUTSIDE, checkpoint=[[_CP4_KEY, "t"]])
_DUP_MARKER = _CP_BODY.replace(
    "\n## Plan", f"\n- a {_MK4}\n- b {_MK4}\n\n## Plan", 1)
_code, _out, _err, _patched = _drive_cmd_update(_DUP_MARKER, checkpoint=[[_CP4_KEY, "t"]])
_code, _out, _err, _patched = _drive_cmd_update(
    _CP_BODY, checkpoint=[[_CP4_KEY, "line one\nline two"]])

# (2) The tier-refused arm's key. It is a member of the declared set, distinct from the
# clean-token key, and — like it — carries no `gha:` prefix, because the review-tier
# discriminator reads any `gha:` row as cloud and checkpoint 4 runs on both tiers.
_CP4_REFUSED_KEY = "base-update-checkpoint-4-tier-refused"
# A local/interactive run records the tier-refused outcome and its workpad still
# carries NO `<!-- prflow:checkpoint gha:… -->` row (the executable proof AC6 asks for).
_refused = apply_mut(_CP_BODY, make_args(
    checkpoint=[[_CP4_REFUSED_KEY,
                 "checkpoint 4: the update-branch-checkpoint invocation was refused by this tier"]]))

# (3) The inherited strip. Scoped to the declared set, both marker spellings, and
# `gha:`-prefixed rows left untouched.
_INHERITED = """<!-- prflow:workpad -->
# PRFlow Workpad — Issue #1347

**Status:** 🎉 Complete
**Branch:** `b`
**Last updated:** 2026-08-05 00:00 UTC

## Progress
- [x] **Setup** — branch & workpad
  - 10:00:00 — clean cp4 <!-- prflow:checkpoint base-update-checkpoint-4 -->
  - 10:00:01 — refused cp4 <!-- devflow:checkpoint base-update-checkpoint-4-tier-refused -->
  - 10:00:02 — entered <!-- prflow:checkpoint gha:9:1:phase1-entered -->
  - 10:00:03 — an ordinary note

## Plan
- [ ] step
"""
_code, _out, _err, _patched = _drive_cmd_update(
    _INHERITED, strip_inherited_checkpoints=True, checkpoint=[[_CP4_KEY, "t"]])
# A strip-ONLY call must reach a PATCH at the process level. Every other strip assertion
# here rides another flag, so without this one a regression that swallowed a bare strip as
# a no-op — the exact shape `_has_non_checkpoint_mutation` exists to prevent — would leave
# the inherited row in place with the suite green.
_code, _out, _err, _patched = _drive_cmd_update(_INHERITED, strip_inherited_checkpoints=True)
# ...and the same body at the process level makes no PATCH, so the discarded repair
# is provably never written.
_code, _out, _err, _patched = _drive_cmd_update(
    _NOPROG_BODY.replace("**Last updated:** 2026-08-05 00:00 UTC\n", ""),
    checkpoint=[[_CP4_KEY, "tok"]])
# Attribute the rejection. The loop above asserts only THAT `_UpdateError` raised, which
# an unrelated precondition would satisfy just as well — so pin each fixture to the guard
# it is meant to trip, and prove each fixture really lost the one property under test.
_NOUPD_NOPROG = _NOPROG_BODY.replace("**Last updated:** 2026-08-05 00:00 UTC\n", "")
try:
    apply_mut(_NOUPD_NOPROG, make_args(checkpoint=[[_CP4_KEY, "tok"]]))
    _upd_raised = ""
except workpad._UpdateError as _e:
    _upd_raised = str(_e)

# A SECOND post-plan guard, so the deferred placement is pinned by more than one raise
# site: `--status` on a body with no `**Status:**` line. This is also the exact
# `--status ... --checkpoint gha:...` shape Phase 1.3's cloud resume arm issues.
_NOSTATUS_NOPROG = _NOPROG_BODY.replace("**Status:** 🚀 Documenting\n", "")
_late_err = io.StringIO()
with contextlib.redirect_stderr(_late_err):
    try:
        apply_mut(_NOSTATUS_NOPROG, make_args(
            status="Setup",
            checkpoint=[["gha:7:1:phase1-hydrated", "run resumed; Phase 1 hydrated"]]))
        _late_raised = ""
    except workpad._UpdateError as _e:
        _late_raised = str(_e)

# The tier-refused write through the full command path, not just the pure function: the
# clean-token key has a `_drive_cmd_update` PATCH assertion and this one did not, so a
# regression that swallowed the tier-refused insert would show only on the clean key.
_code, _out, _err, _patched = _drive_cmd_update(
    _CP_BODY, checkpoint=[[_CP4_REFUSED_KEY, "checkpoint 4: refused by this tier"]])

# AC16 (positive control at the process level): an ABSENT-key checkpoint INSERT
# through cmd_update DOES issue a PATCH carrying the new row — the counterpart to the
# replay-makes-no-PATCH negative above, so a mutant that silently swallowed inserts
# (never PATCHing) would be caught. `_CP_BODY` has ## Progress but not _MK.
_code, _out, _err, _patched = _drive_cmd_update(_CP_BODY, checkpoint=[[_CPKEY, "invoked"]])

# AC16 (hydration seam): a phase1-hydrated INSERT combined with a matching
# --expect-comment-id precondition + --status + --note lands in ONE PATCH — the
# precondition-pass -> insert -> single-PATCH composition the isolated tests never
# exercise together. The fake body-fetch returns comment id 7, so the precondition
# passes and the insert rides the same PATCH.
_code, _out, _err, _patched = _drive_cmd_update(
    _CP_BODY, checkpoint=[[_CPKEY, "hydrated"]], status="Setup",
    note=["Phase 1 workpad hydrated"], expect_comment_id="7")

# AC13, as amended by issue #1347: a checkpoint on a legacy body lacking ## Progress no
# longer declines to write — it repairs the section and records. The Phase 1 legacy
# migration stays required for the OTHER writers (`--note`/`--tick-progress` still abort
# on that shape); it is simply no longer the only path to a checkpoint write.
_code, _out, _err, _patched = _drive_cmd_update(
    """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Setup
**Last updated:** 2026-05-15 00:00 UTC

## Plan
- [ ] step
""", checkpoint=[[_CPKEY, "entry"]])

# ── --expect-comment-id / --expect-status hydration-race preconditions (AC24) ──
# _drive_cmd_update stubs the live comment as id 7 with a 🚀 Setup body.
_RACE_BODY = _CP_BODY  # id 7, Status 🚀 Setup

# Matching preconditions: the update proceeds and PATCHes.
_code, _out, _err, _patched = _drive_cmd_update(_RACE_BODY, expect_comment_id="7",
                                          expect_status="Setup", note=["ok"])

# Changed comment id: abort before mutation/PATCH, exit 4.
_code, _out, _err, _patched = _drive_cmd_update(_RACE_BODY, expect_comment_id="999",
                                          note=["should not land"])

# Changed status (terminal backstop / operator flip): abort before mutation/PATCH.
_code, _out, _err, _patched = _drive_cmd_update(_RACE_BODY, expect_status="Reviewing",
                                          note=["should not land"])

# A body with NO Status line resolves the live word to '' (never the expected
# word), so an --expect-status precondition aborts before PATCH (exit 4) — a
# malformed/truncated live body cannot be mistaken for a match.
_NO_STATUS_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999
**Branch:** `x`
**Last updated:** 2026-05-15 00:00 UTC

## Progress
- [ ] **Setup** — branch & workpad
"""
_code, _out, _err, _patched = _drive_cmd_update(_NO_STATUS_BODY, expect_status="Setup",
                                          note=["should not land"])

# AC23 (shared-helper compatibility): a plain update with neither new flag behaves
# exactly as before — the default checkpoint=[]/expect_*=None never alter the path.
_code, _out, _err, _patched = _drive_cmd_update(_RACE_BODY, note=["plain"])

# ── issue #1348: the terminal --status Complete required-artifact gate ─────────
# The gate refuses a Complete write whose ## Progress carries no row for any declared
# required run artifact (initially base-update checkpoint 4). Restore the real verdict
# for this block (it is globally no-op'd above so the pre-#1348 Complete tests are not
# burdened with the row); the evidence half stays no-op'd so this block exercises the
# required-artifact check in isolation. Restore the bypass at the end.
print()
print("issue #1348: terminal --status Complete required-artifact gate")

# Complete-ready base: AC ticked, canonical body. `_MK4` / the tier-refused marker are
# the checkpoint-4 markers; build variants that carry each in ## Progress.
_C_BASE = _CP_BODY.replace("- [ ] AC1", "- [x] AC1")
_MK4_REFUSED = workpad._checkpoint_marker(_CP4_REFUSED_KEY)
_MK4_DEVFLOW = _MK4.replace("prflow:", "devflow:")
_MK4_REFUSED_DEVFLOW = _MK4_REFUSED.replace("prflow:", "devflow:")
def _with_row(marker):
    return _C_BASE.replace(
        "  - 02:00:00 — /devflow:implement run started",
        "  - 02:00:00 — /devflow:implement run started\n"
        "  - 03:00:00 — checkpoint 4 " + marker)
try:
    apply_mut(_C_BASE, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _gate_err = str(e)
# AC2/AC3 at the process level: the refusal aborts before any PATCH (no mutation).
_code, _out, _err, _patched = _drive_cmd_update(_C_BASE, status="Complete")

# AC6: a run whose checkpoint 4 recorded a clean row completes unchanged.
_out = apply_mut(_with_row(_MK4), make_args(status="Complete"), [])
_code, _out, _err, _patched = _drive_cmd_update(_with_row(_MK4), status="Complete")

# AC5: the tier-refused marker satisfies the required artifact — a tier-refused run
# still publishes and completes.
_out = apply_mut(_with_row(_MK4_REFUSED), make_args(status="Complete"), [])

# AC4: both marker spellings are read by the shared helper — a workpad mutated across
# the #1003 rename boundary (devflow: spelling) is not falsely refused, for the clean
# key AND the tier-refused key.
_out = apply_mut(_with_row(_MK4_DEVFLOW), make_args(status="Complete"), [])
_out = apply_mut(_with_row(_MK4_REFUSED_DEVFLOW), make_args(status="Complete"), [])

# AC8 (resumed run, depends on #1347's strip; end to end): a body carrying a PRIOR
# attempt's checkpoint-4 row is stripped by --strip-inherited-checkpoints, and a
# Complete write that records NO fresh row is then refused — the resumed run cannot
# satisfy the gate on an inherited row.
_resumed = apply_mut(_with_row(_MK4), make_args(
    strip_inherited_checkpoints=True, status="Setup"))
try:
    apply_mut(_resumed, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _resumed_err = str(e)
_code, _out, _err, _patched = _drive_cmd_update(_resumed, status="Complete")

# AC13 (version skew, reverse direction): a newer workpad.py under an OLDER skill body
# that still records checkpoint 4 with the deleted `--note` fallback writes no keyed
# marker, so the Complete is refused at the gate with a named remedy rather than
# silently completing.
_old_body = apply_mut(_C_BASE, make_args(
    note=['checkpoint 4: observed token UP_TO_DATE — clean, proceeding']))
try:
    apply_mut(_old_body, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _skew_err = str(e)

# AC10: the three checkpoint PRODUCER fail-closed refusals (empty body / duplicate
# ## Progress / marker anomaly) each carry a distinguishable tag and a named remedy, so
# a human can tell from the message alone which shape they hit; the messages differ.
_refusal_msgs = {}
for _name, _body in [
    ("empty", "   \n\t\n "),
    ("dup-progress", _CP_BODY.replace("## Plan", "## Progress\n- [ ] d\n\n## Plan", 1)),
    ("marker-outside", _CP_BODY.replace("## Plan", f"## Plan\n- stray {_MK4}", 1)),
    ("marker-dup", _CP_BODY.replace("\n## Plan", f"\n- a {_MK4}\n- b {_MK4}\n\n## Plan", 1)),
]:
    try:
        apply_mut(_body, make_args(checkpoint=[[_CP4_KEY, "t"]]))
        _refusal_msgs[_name] = "NO-RAISE"
    except workpad._UpdateError as e:
        _refusal_msgs[_name] = str(e)

# Restore the module-load bypass so any later Complete tests are not gated on the row.
workpad._required_artifact_verdict = lambda prog_content: None

# ── issue #1453: the terminal --status Complete review-coverage gate ───────────
# The gate refuses a Complete write whose ## Progress carries no resolvable
# review-coverage record, or one recording a gap with no accepted disposition.
# Restore the real verdict for this block (globally no-op'd above so the pre-#1453
# Complete tests are not burdened with the record); the evidence and required-artifact
# halves stay no-op'd so this block exercises the coverage member in isolation.
print()
print("issue #1453: terminal --status Complete review-coverage gate")

_RC_BASE = _CP_BODY.replace("- [ ] AC1", "- [x] AC1")
_RC_REASONS = {
    "shadow-coverage": "the shadow fan-out returned 3 of 5 agents before the "
                       "orchestrator context budget ran out",
    "roster": "the type-design reviewer was not dispatched; the diff touches no "
              "type definitions",
    "checklist": "checklist verification stopped at item 11 of 27 under cost "
                 "pressure after the fan-out was dispatched",
}


def _rc_members_for(roster):
    """Default per-member roster rows coherent with a roster axis value (issue #1512),
    so existing `complete`/`short` call sites carry an enumeration the gate accepts."""
    if roster == "complete":
        return [(m, "dispatched") for m in workpad._SHADOW_ALWAYS_ON_MEMBERS]
    if roster == "short":
        return ([(workpad._SHADOW_ALWAYS_ON_MEMBERS[0], "missing")]
                + [(m, "dispatched") for m in workpad._SHADOW_ALWAYS_ON_MEMBERS[1:]])
    return []


def _rc_roster_rows(members):
    """The ## Progress roster-member bullets for `members` (a list of (member, status))."""
    return "".join(
        f"\n  - 03:00:0{i + 1} — {workpad._render_review_roster_member(m, s)}"
        f" {workpad._review_roster_marker(m, s)}"
        for i, (m, s) in enumerate(members))


def _rc_row(payload, members=None):
    """A ## Progress body carrying one review-coverage record for `payload`, plus a
    per-member roster enumeration (issue #1512). `members` defaults to one coherent with
    the payload's roster axis so existing call sites keep passing; pass `members=[]` to
    omit the enumeration, or an explicit list to test a specific fan-out."""
    fields = payload.split(":")
    roster = fields[2] if len(fields) in (4, 6) else None
    if members is None:
        members = _rc_members_for(roster)
    return _RC_BASE.replace(
        "  - 02:00:00 — /devflow:implement run started",
        "  - 02:00:00 — /devflow:implement run started\n"
        "  - 03:00:00 — review coverage recorded "
        + workpad._review_coverage_marker(payload)
        + _rc_roster_rows(members))


def _rc_complete(body, **overrides):
    """Drive a `--status Complete` write over `body`, returning the _UpdateError
    message or None when the write applied cleanly."""
    try:
        apply_mut(body, make_args(status="Complete", **overrides), [])
    except workpad._UpdateError as e:
        return str(e)
    return None
# AC2 at the process level: the refusal aborts before any PATCH.
_code, _out, _err, _patched = _drive_cmd_update(_RC_BASE, status="Complete")

# AC2/AC9: a disposition covering only ONE of two gaps is refused, naming the other.
_two_gaps = _rc_row("full:attempted:short:skipped")
_msg = _rc_complete(_two_gaps, review_coverage_disposition=[
    ["roster", "dispatched-but-lost", _RC_REASONS["roster"]]])

# The READ-TIME reason check is a distinct branch from the write-time one (they share
# the [review-coverage-boilerplate] token, which is why it needs its own control): a
# row planted directly in ## Progress — hand-edited, or written by an older workpad.py
# — never passed the write-time validation, so only this branch can refuse it.
def _planted_disposition(gap, text, cause="dispatched-but-lost"):
    return _rc_row("full:attempted:short:complete").replace(
        "- [ ] **Implement**",
        "  - 04:00:00 — " + text + " "
        + workpad._review_coverage_disposition_marker(gap, cause)
        + "\n- [ ] **Implement**")


_msg = _rc_complete(_planted_disposition(
    "roster", workpad._render_review_coverage_disposition("roster", "n/a")))
# ...and a planted row whose visible text does not match the rendering re-reads as an
# empty reason, which the same check refuses — an unreadable reason is not a stated one.
_msg = _rc_complete(_planted_disposition("roster", "some other prose entirely"))
# A row whose marker names one gap while its text names another must not bind the
# other gap's reason: the reason pattern is anchored on the marker's own gap.
_msg = _rc_complete(_planted_disposition(
    "roster", workpad._render_review_coverage_disposition(
        "checklist", _RC_REASONS["checklist"])))
try:
    apply_mut(_RC_BASE, make_args(record_review_coverage="abcd"), [])
except workpad._UpdateError as _e:
    _s_cov = str(_e)
try:
    apply_mut(_RC_BASE, make_args(review_coverage_disposition=["ab"]), [])
except workpad._UpdateError as _e:
    _s_disp = str(_e)
try:
    apply_mut(_RC_BASE, make_args(record_review_coverage=5), [])
except workpad._UpdateError as _e:
    _i_cov = str(_e)
try:
    apply_mut(_RC_BASE, make_args(review_coverage_disposition=[5]), [])
except workpad._UpdateError as _e:
    _i_disp = str(_e)
try:
    apply_mut(_RC_BASE, make_args(
        checkpoint=[["review-roster:code-reviewer:dispatched", "forged"]]), [])
except workpad._UpdateError as _e:
    _1512_forge = str(_e)
try:
    apply_mut(_RC_BASE, make_args(note=["review pass done "
        + workpad._review_roster_marker("requesting-code-review", "dispatched")]), [])
except workpad._UpdateError as _e:
    _1512_smuggle = str(_e)
# An empty value is falsy, so the `if args.record_classification:` gate skips it — a
# safe no-op (no raise, no classification note), not a crash.
_rc_empty = apply_mut(_CP_BODY, make_args(record_classification=[]), [])

# The process-level positive twin of AC2's no-PATCH negative: a clean record PATCHes.
_code, _out, _err, _patched = _drive_cmd_update(
    _rc_row("full:attempted:complete:complete"), status="Complete")

# AC8 fail-closed half: a workpad with no ## Devflow Reflection section refuses the
# disposition rather than recording one that would never route to the retrospective.
_norefl = _rc_row("full:attempted:short:complete")
_norefl = _norefl[:_norefl.index("## Devflow Reflection")]
try:
    apply_mut(_norefl, make_args(
        review_coverage_disposition=[["roster", "dispatched-but-lost", _RC_REASONS["roster"]]]), [])
except workpad._UpdateError as _e:
    _rerr = str(_e)

# ── issue #1510: the review-coverage record carries an as-of anchor (the reviewed head
#    SHA it was derived from + the UTC time it was written), so a gap it declares is a
#    statement about THIS run's own review pass at that anchor — a later standalone
#    review closing the gap never contradicts it.
_rc_head = "a1b2c3d4e5" * 4  # a 40-char lowercase-hex head

# AC3/AC2: declare a gap on an anchored record, then a later standalone review closes it.
# The gap wording is scoped to the run's own review pass at the anchor, and the record
# names its own reviewed head — so its claim is bounded and a later review at a DIFFERENT
# head never contradicts it.
_rc_gap = apply_mut(_CP_BODY, make_args(
    record_review_coverage=["not-verified", "attempted", "short", "skipped"],
    record_roster_member=_rc_members_for("short"),
    record_review_coverage_head=_rc_head,
    review_coverage_disposition=[
        ["shadow-coverage", "dispatched-but-lost", _RC_REASONS["shadow-coverage"]],
        ["roster", "dispatched-but-lost", _RC_REASONS["roster"]],
        ["checklist", "dispatched-but-lost", _RC_REASONS["checklist"]]]))
try:
    apply_mut(_CP_BODY, make_args(
        record_review_coverage=["full", "attempted", "complete", "complete"],
        record_review_coverage_head="NOTHEX-XYZ"), [])
except workpad._UpdateError as _e:
    _rc_bad_head_err = str(_e)
_1984_ENV = ("the runner did not expose the requesting-code-review agent type this run, "
             "so the final-pass reviewer could not be dispatched")
try:
    apply_mut(_RC_BASE, make_args(
        review_coverage_disposition=[["roster", _RC_REASONS["roster"]]]), [])
except workpad._UpdateError as _e:
    _aerr = str(_e)
try:
    apply_mut(_RC_BASE, make_args(
        review_coverage_disposition=[["roster", "environment-denial", _1984_ENV]]), [])
except workpad._UpdateError as _e:
    _e5 = str(_e)
try:
    apply_mut(_rc_row("not-verified:attempted:short:complete"), make_args(
        review_coverage_disposition=[["roster", "environment-denial", _1984_ENV]]))
except workpad._UpdateError as _e:
    _e5ok = str(_e)

# Restore the module-load bypass so any later Complete tests are not gated on the record.
workpad._review_coverage_verdict = lambda prog_content: None

# An empty diff (reviewed head == base, so merge_base == head) resolves and confirms
# (0 files, 0 lines): the recomputation resolves rather than downgrading.
_rc_empty = Path(tempfile.mkdtemp(prefix='rc1509-empty-'))
(_rc_empty / 'a.md').write_text('x\n')

# ── issue #1817: the terminal --status Complete extension-row gate ─────────────
# The gate refuses a Complete write while any `prompt extension resolved:` row is
# unticked AND carries no sanctioned `state not established` note — mirroring the
# unticked-AC hard-fail. The other three prog_content verdicts stay no-op'd (above)
# so this block exercises the extension-row member in isolation.
print()
print("issue #1817: terminal --status Complete extension-row gate")

_EXT_BODY = """<!-- devflow:workpad -->
# DevFlow Workpad — Issue #1817t

**Status:** 🚀 Reviewing
**Branch:** `x`
**Last updated:** 2026-05-15 00:00 UTC

## Progress
- [x] **Setup** — branch & workpad
  - [x] prompt extension resolved: implement
- [x] **Review**
  - [x] prompt extension resolved: review engine
  - [x] prompt extension resolved: fix loop
  - [x] prompt extension resolved: code-review reception
- [x] **Implement**

## Plan
- [x] step

## Acceptance Criteria
- [x] AC1

## Devflow Reflection
<details>
<summary>Devflow Reflection (click to expand)</summary>

</details>
"""

# One extension row unticked, no note.
_EXT_UNTICKED = _EXT_BODY.replace(
    "  - [x] prompt extension resolved: fix loop",
    "  - [ ] prompt extension resolved: fix loop")
try:
    apply_mut(_EXT_UNTICKED, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _ext_err = str(e)
# AC4: the refusal aborts before any PATCH — no mutation, non-zero exit.
_code, _out, _err, _patched = _drive_cmd_update(_EXT_UNTICKED, status="Complete")

# AC1 (multi-row plural path): two unticked, un-noted rows are BOTH named, exercising
# len(offending) pluralization and the multi-row join that a single-row test never reaches.
_EXT_TWO_UNTICKED = _EXT_BODY.replace(
    "  - [x] prompt extension resolved: review engine",
    "  - [ ] prompt extension resolved: review engine").replace(
    "  - [x] prompt extension resolved: fix loop",
    "  - [ ] prompt extension resolved: fix loop")
try:
    apply_mut(_EXT_TWO_UNTICKED, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _ext_two_err = str(e)
try:
    apply_mut(_EXT_UNTICKED, make_args(
        status="Complete",
        note=["extension resolved: review engine — state not established (loader refused)"]),
        [])
except workpad._UpdateError as e:
    _ext_wrongnote_err = str(e)

# Mixed row presence — the realistic partially-reconciled workpad: some `_EXTENSION_ROWS`
# members are wholly absent while another is present-and-offending. The per-row absence
# tolerance must not swallow the genuine offender beside it, and only the present row is
# named. `_EXT_BODY` minus the two Review-tier rows, with `fix loop` left unticked.
_EXT_MIXED = _EXT_BODY.replace(
    "  - [x] prompt extension resolved: review engine\n", "").replace(
    "  - [x] prompt extension resolved: code-review reception\n", "").replace(
    "  - [x] prompt extension resolved: fix loop",
    "  - [ ] prompt extension resolved: fix loop")
try:
    apply_mut(_EXT_MIXED, make_args(status="Complete"), [])
except workpad._UpdateError as e:
    _ext_mixed_err = str(e)

# Restore the module-load bypass so any later Complete tests are not gated on the rows.
workpad._extension_row_verdict = lambda prog_content: None

# ── issue #548: cmd_record_adjudication reject-path coverage (the agreement invariant is the
#    feature's core new safety gate — every _fail guard is driven, plus the unestablished
#    positive control, mirroring the record-return reject-path precedent above).
print()
print("issue-audit-state: record-adjudication reject paths (issue #548)")

_LIBTEST = Path(__file__).resolve().parent
cwc = _load('cloud_writer_contract', _LIBTEST / 'cloud_writer_contract.py')
vcwc = _load('validate_cloud_writer_contract', SCRIPTS / 'validate-cloud-writer-contract.py')

# issue #1445: `main` is the sole writer of the checked-in manifest, so on a feature branch
# that edited a pinned source file the committed manifest is legitimately stale — and it is
# NOT gated there. Every validator/verify check below that used to hash-check the COMMITTED
# manifest against the live tree therefore validates a FRESHLY GENERATED manifest instead
# (equal to what `main` would publish for this tree), so it exercises the validator's grant /
# closure / HEAD_ABSENT logic without re-introducing the branch-side staleness gate that #1445
# removed. The freshly generated manifest matches the live tree by construction.
with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as _fm1445f:
    _fm1445f.write(cwc.canonical_json(cwc.build_manifest()))
    _fresh_manifest_1445 = _fm1445f.name

# ─────────────────────────────────────────────────────────────────────────────
# AC4 (issue #678) — profile-specific command SHAPES over the AC1-reached fences.
# extract-command-shapes.py's two rule tables already exist; until now nothing
# applied them to the reachability closure this module owns, so a denied shape in
# a reached asset that neither the review-bundle nor the implement-bundle scan
# covers shipped unseen.
# ─────────────────────────────────────────────────────────────────────────────

_shapes_mod = cwc._shapes

# The migrated surfaces carry NO bare-/tmp scratch target. The residual count
# is derived IN python3 (never a grep/wc pipeline, which yields empty on a host
# missing either binary and would pass vacuously). Prints on pass and fail alike.
# (Maps to the residual-count criterion.)
_MIGRATED_FILES = (
    "skills/implement/phases/phase-1-setup.md",
    "skills/implement/phases/phase-2-implement.md",
    "skills/implement/phases/phase-2-sweeps-contract.md",
    "skills/implement/phases/phase-2-sweeps-quality.md",
    "skills/implement/phases/phase-4-documentation.md",
    "skills/implement/references/deferred-review-findings.md",
    # issue #1557 split §4.1 Stage 2's self-heal repair into this reference, a fenced surface
    # that runs git and workpad.py — bind it to the same no-bare-/tmp guard. It names no stem
    # of its own, so it takes no _STEM_HOMES row; the negative half above still binds it.
    "skills/implement/references/doc-deliverable-self-heal.md",
    "skills/review-and-fix/references/loop-control.md",
    "skills/review-and-fix/references/loop-exit.md",
    # issue #1582 moved §1.4's branch-setup procedure (its title-file scratch write among it)
    # into this dispatched agent, which writes only under .prflow/tmp/ — bind it to the same
    # no-bare-/tmp guard.
    "agents/branch-setup.md",
)
_bare_tmp = 0
for _mf in _MIGRATED_FILES:
    for _line in (cwc.REPO_ROOT / _mf).read_text(encoding="utf-8").splitlines():
        for _m in re.finditer(r"/tmp/", _line):
            if not _line[max(0, _m.start() - 8):_m.start()].endswith(".prflow"):
                _bare_tmp += 1
print(f"residual bare-/tmp lines: {_bare_tmp}")

# ─────────────────────────────────────────────────────────────────────────────
# Cloud-writer trust-closure dependency classification (issue #583, AC5).
# The classification is import/source-derived + exec-declared; the guard rejects
# a repo-owned edge that escapes the vendored tree and an external edge that
# names no preflight guarantee. Positive fixtures pin workpad.py's
# subprocess/stdlib deps and run-jq.sh's jq delegation; non-vacuity is proven by
# injecting one crafted edge at a time into check_dependencies(edges=...).
# ─────────────────────────────────────────────────────────────────────────────
cwd = _load('cloud_writer_deps', _LIBTEST / 'cloud_writer_deps.py')


# ─────────────────────────────────────────────────────────────────────────────
# issue #703 (deferred from #678): cloud-writer one-version upgrade-skew (AC19)
# and consumer-provisioning (AC20) fixtures.
#
# These fixtures drive the AC18 pre-agent validator (vcwc) and the AC1 closure
# contract (cwc) IN-PROCESS — every check calls an imported module, so NO fixture
# executes repo-root helper code (AC19's constraint), consistent with the AC18
# block above (which routes everything through vcwc/cwc too).
# ─────────────────────────────────────────────────────────────────────────────

_REPO = cwc.REPO_ROOT

# Frozen legacy profile grants — the vendored helper heads each cloud profile
# granted at `legacy_profile_baseline` (cwc.LEGACY_PROFILE_BASELINE, "2.31.16"),
# the immediately-preceding supported profile set. This is a DELIBERATE frozen
# snapshot (an enforcement constant, not a live read): pairing 2 below validates
# the LIVE checked-in manifest against it, so a future PR that adds a newly-
# required helper head the frozen baseline never granted turns pairing 2 RED —
# forcing a conscious re-snapshot here in lockstep with the baseline bump, rather
# than the compatibility window silently widening. The snapshot is self-checking:
# if it omits any head the current manifest requires, pairing 2 goes RED
# (HEAD_ABSENT) at the desk. Prefix helpers keep the vendored-literal form exact.
def _cwv(_n):
    return cwc.VENDOR_PREFIX + "scripts/" + _n


def _cwl(_n):
    return cwc.VENDOR_PREFIX + "lib/" + _n

_FROZEN_LEGACY_GRANTS = {
    "implement": {
        _cwv("run-jq.sh"), _cwv("config-get.sh"), _cwv("workpad.py"),
        _cwv("parse-acs.py"), _cwv("branch-for-issue.py"),
        _cwv("update-branch-checkpoint.sh"), _cwv("resolve-existing-pr.sh"),
        _cwv("file-deferrals.py"),
        _cwv("discover-deferral-manifests.py"), _cwv("match-deferrals.py"),
        _cwv("resolve-review-overrides.py"), _cwv("apply-labels.sh"),
        _cwv("ensure-label.sh"), _cwv("apply-issue-dependencies.py"),
        _cwv("stale-prose-lint.py"),
        _cwv("dismiss-stale-rejections.sh"), _cwv("match-lint-adjudications.py"),
        _cwv("load-prompt-extension.sh"), _cwv("render-prompt-extension.sh"),
        _cwv("react-to-trigger.sh"),
        _cwv("extract-doc-needed-paths.sh"), _cwl("efficiency-trace.sh"),
    },
    "light-command": {
        _cwv("run-jq.sh"), _cwv("config-get.sh"), _cwv("workpad.py"),
        _cwv("parse-acs.py"), _cwv("branch-for-issue.py"),
        _cwv("update-branch-checkpoint.sh"), _cwv("file-deferrals.py"),
        _cwv("match-deferrals.py"), _cwv("match-lint-adjudications.py"),
        _cwv("resolve-review-overrides.py"), _cwv("stale-prose-lint.py"),
        _cwv("dismiss-stale-rejections.sh"), _cwv("load-prompt-extension.sh"),
        _cwv("render-prompt-extension.sh"),
        _cwl("efficiency-trace.sh"),
    },
    "review": {
        _cwv("run-jq.sh"), _cwv("match-deferrals.py"),
        _cwv("match-lint-adjudications.py"), _cwv("dismiss-stale-rejections.sh"),
        _cwv("workpad.py"), _cwv("config-get.sh"),
        _cwv("load-prompt-extension.sh"), _cwv("render-prompt-extension.sh"),
        _cwv("resolve-review-overrides.py"),
        _cwv("stale-prose-lint.py"), _cwl("efficiency-trace.sh"),
    },
}

# ── AC19 pairing 2: immediately-preceding WORKFLOW + NEW plugin → completes.
# Validate a freshly generated manifest (the new plugin; issue #1445 — main is the sole
# writer of the committed manifest, so a feature branch is validated against the manifest
# main would publish, never the possibly-stale committed one) under the FROZEN legacy
# grants (the immediately-preceding workflow). It completes because the current
# plugin requires no head the legacy baseline did not already grant.
_live_manifest = Path(_fresh_manifest_1445)
_p2 = vcwc.validate(
    _live_manifest, base_dir=_REPO,
    expected_assets=cwc.manifest_file_paths(),
    required_profiles=list(cwc.ROOTS),
    profile_grants={p: set(h) for p, h in _FROZEN_LEGACY_GRANTS.items()},
)


# ── issue #555: scripts/discover-deferral-manifests.py — fail-closed Phase 4.0.5
# ── deferrals-manifest discovery. The retired inline `find $SEARCH_DIRS … | sort`
# ── collapsed a FAILED search and a CLEAN no-match search onto the same empty
# ── output, so a degraded search read as the clean no-op and stranded deferrals.
# ── These fixtures drive the helper's CLI contract at module level (main(argv)
# ── returns the exit code and writes to sys.stdout/stderr, so no subprocess is
# ── needed) — the automated boundary the extraction exists to create, since a
# ── markdown fence cannot be executed by the suite.
print("discover-deferral-manifests.py (#555): per-root classification + exit contract")


def _dm_run(argv, cwd=None):
    """Run the helper's main() with argv, returning (rc, stdout, stderr).

    `cwd` is an operand for the #1374 presence mode only: it composes its search
    directories from the cwd-relative literal `.prflow/tmp/review`, exactly as the
    §4.0.5 filing fence does, so driving it from anywhere else would search a tree the
    fixture never built and collapse every state onto `absent`. Discovery mode takes
    absolute roots and passes no `cwd`.
    """
    out, err = io.StringIO(), io.StringIO()
    _prev = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = discover_deferrals.main(list(argv))
    finally:
        if cwd is not None:
            os.chdir(_prev)
    return rc, out.getvalue(), err.getvalue()


def _dm_manifest(root, run_id, content='{"deferrals": []}'):
    """Create <root>/<run_id>/deferrals.json with the given content and return
    its POSIX-form path (the shape the helper prints)."""
    d = Path(root) / run_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / 'deferrals.json'
    p.write_text(content, encoding='utf-8')
    return p.as_posix()


# ── issue #1374: the PRESENCE mode. Phase 4.0.5's filing procedure moved behind a
# ── predicate-gated reference, and this mode IS that predicate: it answers whether
# ── any deferred review finding is present for a PR without the phase file having to
# ── carry the filing procedure's bytes. Its contract is deliberately flat where the
# ── discovery mode's is not — present/absent/unestablished as exit 0/1/2 — so both
# ── gated Phase 4 sub-steps document one three-state shape. The exit status carries
# ── every state; the shipped stub additionally requires the literal `absent: 0` line
# ── on its skip arm, because a crashing interpreter also exits 1.
print("discover-deferral-manifests.py (#1374): presence mode — three-state exit contract")

_PM_FLAG = '--presence-for-pr'


def _pm_fence_tr_chain():
    """Extract the §4.0.5 fence's OWN `tr` chain from the shipped reference file.

    Reading the chain out of the artifact is what makes this a differential rather than a
    third copy: a hand-typed chain in this file would keep agreeing with the port after
    someone widened the fence's keep-set, and the drift the AC exists to catch would ship
    green. Returns the pipeline text after `printf '%s' "$CUR_BRANCH" | `, or None when the
    line cannot be located — which the caller records as a degradation, never as agreement.
    """
    ref = cwc.REPO_ROOT / 'skills/implement/references/deferred-review-findings.md'
    try:
        text = ref.read_text(encoding='utf-8')
    except OSError:
        return None
    marker = 'BRANCH_SLUG=$(printf \'%s\' "$CUR_BRANCH" | '
    for line in text.splitlines():
        if marker in line:
            chain = line.split(marker, 1)[1]
            return chain[:-1] if chain.endswith(')') else None
    return None


def _pm_tr_slugs(names, chain):
    """Derive each branch slug through the fence's own extracted `tr` chain.

    `LC_ALL=C` pins it to byte semantics, which is what makes the comparison deterministic
    across a BSD `tr` and a GNU one; the port is likewise byte-oriented ASCII. The whole
    table runs in ONE shell, emitting one NUL-terminated slug per input, so the
    differential costs a single spawn rather than one per row. Returns None when the chain
    could not be run or the output is not attributable, so the differential records a
    degradation instead of asserting against an empty pipeline (the guard-class-2 shape: a
    missing tool must never read as a clean agreement).
    """
    _env = dict(os.environ, LC_ALL='C')
    script = ('for a in "$@"; do printf \'%s\' "$a" | ' + chain
              + "; printf '\\000'; done")
    try:
        _p = _subprocess.run(['sh', '-c', script, 'sh'] + list(names),
                             capture_output=True, text=True, env=_env)
    except OSError:
        return None
    if _p.returncode != 0:
        return None
    slugs = _p.stdout.split('\x00')[:-1]
    return slugs if len(slugs) == len(names) else None


# ── issue #603: the per-finding ledger, post-revision resolution, and convergence basis ──
#
# Rows are numbered to the issue's Testing Strategy list. The pure evaluators are driven
# in-process; the mutations and queries are driven through the real CLI in a temp dir,
# because their whole contract is exit codes, printed tokens, and stderr breadcrumbs.

_IAS603 = str(SCRIPTS / 'issue-audit-state.py')

def _ias_fork_selected(env):
    """Decide whether the fork driver below is usable, given an environment mapping.

    Taken as a function of an explicit mapping rather than reading `os.environ` inline so
    the `DEVFLOW_IAS_NO_FORK=1` escape hatch is assertable without re-importing this file.
    """
    return hasattr(os, 'fork') and env.get('DEVFLOW_IAS_NO_FORK') != '1'


# `os.fork` does not exist on Windows, where every call falls back to the real spawn.
_IAS_FORK_OK = _ias_fork_selected(os.environ)


def _ias_reset_module_state():
    """Return the already-imported `issue_audit_state` to its cold-import state.

    The fork child inherits the PARENT's module globals rather than re-importing, so any
    process-scoped memo the parent warmed would answer for the child's own cwd and its own
    first-emission bookkeeping. `_repo_root` is the load-bearing one: it is memoized and
    cwd-derived, so a warm entry would resolve this repository instead of the child's temp
    sandbox. A monkeypatched stand-in carries no `cache_clear`, hence the guard.
    """
    rr = getattr(issue_audit_state, '_repo_root', None)
    clear = getattr(rr, 'cache_clear', None)
    if clear is not None:
        clear()
    emitted = getattr(issue_audit_state, '_STATE_BREADCRUMB_EMITTED', None)
    if isinstance(emitted, set):
        emitted.clear()


def _ias_spawn(argv, cwd, stdin=None):
    """Spawn `issue-audit-state.py` as a real subprocess.

    This is both the Windows/opt-out fallback for `_ias_run` and the fidelity REFERENCE the
    A/B row below grades the fork driver against, so the two must stay one call shape.
    """
    return _subprocess.run([sys.executable, _IAS603, *argv], cwd=cwd, input=stdin,
                           capture_output=True, text=True)


def _ias_run(argv, cwd, stdin=None):
    """Drive `issue-audit-state.py`'s CLI in a forked child, or spawn it for real.

    Returns the same `CompletedProcess` shape `_ias_spawn` returns, and preserves everything
    the rows grade: the real exit status, the real stdout/stderr bytes, the real working
    directory, and full process isolation (the child `os._exit`s, so no state it mutates can
    reach the parent). What it drops is the interpreter startup and module import a spawn
    pays per call, which no assertion examines.

    Known divergence from `_ias_spawn`, inert for every input these rows drive: the child's
    streams are fixed UTF-8 rather than the locale encoding, and `stdin=None` gives the child
    `/dev/null` (immediate EOF) where the spawn inherits this process's own stdin.
    """
    if not _IAS_FORK_OK:
        return _ias_spawn(argv, cwd, stdin=stdin)
    args = [_IAS603, *argv]
    # stdin arrives through a temp FILE, never a pipe: a pipe would deadlock the pair once
    # a payload exceeded the kernel buffer, since the parent cannot write and drain at once.
    stdin_file = None
    out_r = out_w = err_r = err_w = None
    pid = None
    try:
        if stdin is not None:
            stdin_file = tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False)
            stdin_file.write(stdin)
            stdin_file.close()
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        # Flush before forking, or the child inherits the parent's buffered bytes and emits
        # a second copy of everything already written to this file's own stdout/stderr.
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            rc = 1
            try:
                # A failure anywhere in this setup must still say WHY on the child's stderr:
                # a bare `os._exit(1)` here is indistinguishable from a genuine CLI exit 1.
                try:
                    os.close(out_r)
                    os.close(err_r)
                    os.dup2(out_w, 1)
                    os.dup2(err_w, 2)
                    os.close(out_w)
                    os.close(err_w)
                    fd0 = os.open(
                        stdin_file.name if stdin_file is not None else os.devnull,
                        os.O_RDONLY)
                    os.dup2(fd0, 0)
                    os.close(fd0)
                    sys.stdin = os.fdopen(0, 'r', encoding='utf-8')
                    sys.stdout = os.fdopen(1, 'w', encoding='utf-8')
                    sys.stderr = os.fdopen(2, 'w', encoding='utf-8')
                    os.chdir(cwd)
                    sys.argv = [_IAS603, *[str(a) for a in argv]]
                    _ias_reset_module_state()
                except BaseException:
                    import traceback
                    try:
                        with os.fdopen(os.dup(2), 'w', encoding='utf-8') as _diag:
                            _diag.write('_ias_run: fork-child setup failed\n')
                            traceback.print_exc(file=_diag)
                    except BaseException:
                        pass
                    raise
                rc = 0
                try:
                    issue_audit_state.main()
                except SystemExit as exc:
                    rc = 0 if exc.code is None else (
                        exc.code if isinstance(exc.code, int) else 1)
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    rc = 1
                sys.stdout.flush()
                sys.stderr.flush()
            finally:
                os._exit(rc if isinstance(rc, int) else 1)
        os.close(out_w)
        out_w = None
        os.close(err_w)
        err_w = None
        chunks = {}
        failures = {}
        owned = set()

        def _drain(key, fd):
            # A drain thread that dies without recording WHY would leave chunks[key]
            # absent, and an empty-string stdout would then be graded as real output.
            try:
                buf = []
                fh = os.fdopen(fd, 'rb')
                # Membership means "this thread closed, or will close, this pipe end";
                # clearing it before `os.fdopen` takes the fd would leak it, since the
                # parent then skips it too.
                owned.add(key)
                with fh:
                    while True:
                        b = fh.read(65536)
                        if not b:
                            break
                        buf.append(b)
                chunks[key] = b''.join(buf)
            except BaseException as exc:
                failures[key] = exc
                # Release this pipe end HERE when `os.fdopen` never took it: the parent
                # reaches `os.waitpid` before its own finally arm, so an undrained,
                # unclosed pipe wedges the pair forever once the child fills it.
                if key not in owned:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    owned.add(key)

        # Both streams drain concurrently: a child that fills one pipe's buffer while the
        # parent is blocked reading the other would wedge the pair.
        threads = [_threading1040.Thread(target=_drain, args=(k, fd))
                   for k, fd in (('out', out_r), ('err', err_r))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Clear only the ends `os.fdopen` actually took: clearing on a failure that
        # happened before that leaks the pipe end past this call's finally arm.
        if 'out' in owned:
            out_r = None
        if 'err' in owned:
            err_r = None
        _, status = os.waitpid(pid, 0)
        pid = None
        for key in ('out', 'err'):
            if key in failures:
                raise AssertionError(
                    f'_ias_run: the {key} drain thread failed for {args!r}') \
                    from failures[key]
        if os.WIFSIGNALED(status):
            rc = -os.WTERMSIG(status)
        else:
            rc = os.WEXITSTATUS(status)
        return _subprocess.CompletedProcess(
            args, rc,
            _ias_decode(chunks.get('out', b'')), _ias_decode(chunks.get('err', b'')))
    finally:
        for fd in (out_r, out_w, err_r, err_w):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if pid:
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass
        if stdin_file is not None:
            try:
                os.unlink(stdin_file.name)
            except OSError:
                pass


def _ias_decode(raw):
    """Decode a captured stream the way `subprocess.run(text=True)` presents one.

    Universal-newline translation is applied here because the rows were authored against the
    spawn, which translates; a fork path that did not would diverge on any CR-carrying byte.
    """
    return raw.decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')


def _stage_bytes(run, path):
    """Record the staged write for a draft file's CURRENT bytes (issue #1104).

    A fresh file-arm `record-dispatch` refuses bytes that are not recoverable from the
    run's recorded byte history, so establishing that history is a PRECONDITION of a
    file-arm fixture — the same class of setup as the harness's own `init`, not an
    assertion. The artifact is content-addressed with the digest inside the `.staged.md`
    suffix, the property `record-staged-write` and the byte-history reader key on (not
    the `issue-draft-<slug>.<nonce>.<digest>.staged.md` shape `resolve_staged_path`
    produces). The recipe lives here rather than in each harness so no
    `record-dispatch`-driving harness drifts on the artifact name or the digest form.

    Every step is checked and a failure RAISES, the same discipline `_Run603._field`
    applies to its own setup calls: an unestablished precondition would otherwise surface
    as a crowd of unrelated fixtures refusing with `file-arm-requires-staged-write`,
    attributed to their own subjects and to no line naming staging.

    `run` is any harness exposing `.tmp`, `.slug` and the `(*argv, nonce=…)` call shape.
    Returns the artifact path, so a caller that must keep the next round's kind selection
    cold can retire it once the dispatch it enabled has run.
    """
    src = Path(path) if os.path.isabs(str(path)) else Path(run.tmp, path)
    if not src.exists():
        raise AssertionError(
            f'#1104 harness: _stage_bytes({run.slug}) found no draft at {src} — the '
            'byte-history precondition cannot be established for a file-arm dispatch')
    data = src.read_bytes()
    _h = _subprocess.run(['git', 'hash-object', '--stdin', '--no-filters'],
                         input=data, capture_output=True)
    dig = _h.stdout.decode().strip()
    if _h.returncode != 0 or not dig:
        raise AssertionError(
            f'#1104 harness: _stage_bytes({run.slug}) could not digest {src} '
            f'(rc={_h.returncode}); stderr={_h.stderr.decode()!r}')
    art = Path(run.tmp, f'staged-{run.slug}.{dig}.staged.md')
    art.write_bytes(data)
    _r = run('record-staged-write', run.slug, '--path', str(art), '--digest', dig,
             nonce=True)
    if _r.returncode != 0:
        raise AssertionError(
            f'#1104 harness: _stage_bytes({run.slug}) failed to record the staged write '
            f'(rc={_r.returncode}); stderr={_r.stderr!r}')
    return art


class _Run603:
    """A scratch run driven through the real CLI in its own temp directory."""

    def __init__(self, tmp, slug='s603'):
        self.tmp = tmp
        self.slug = slug
        self.nonce = self._field(self('init', slug), 'nonce=', 'init')

    @staticmethod
    def _field(proc, token, what):
        """Parse a `token`-prefixed field out of a SETUP call's stdout, or name the failure.

        The setup calls (`init`, `record-dispatch`) are preconditions, not assertions: a
        harness that indexed straight into `stdout.split(token)` surfaced a broken
        precondition as an opaque `IndexError` from inside the fixture, attributed to no
        row. Check the returncode and the field's presence first so a setup failure names
        the command, its exit code, and its stderr.
        """
        if proc.returncode != 0 or token not in proc.stdout:
            raise AssertionError(
                f'#603 harness: {what} did not establish {token!r} '
                f'(rc={proc.returncode}); stdout={proc.stdout!r} stderr={proc.stderr!r}')
        return proc.stdout.split(token, 1)[1].split()[0].strip()

    def __call__(self, *argv, stdin=None, nonce=False, autostage=True):
        # issue #1104: a fresh file-arm dispatch now requires the dispatched bytes in the
        # byte history. Establishing it here keeps a fixture whose subject is NOT that
        # guarantee expressing only its own subject; the rows that DO grade the guarantee
        # pass `autostage=False` and drive the raw CLI. The arm is read as the VALUE
        # following `--arm`, never as a bare membership test over argv — a path or a
        # marker token spelled `file` would otherwise acquire the staging side effect.
        art = None
        if (autostage and argv and argv[0] == 'record-dispatch'
                and '--arm' in argv and '--draft-file' in argv
                and argv[argv.index('--arm') + 1] == 'file'):
            art = _stage_bytes(self, argv[argv.index('--draft-file') + 1])
        args = list(argv)
        if nonce:
            args += ['--nonce', self.nonce]
        out = _ias_run(args, self.tmp, stdin=stdin)
        if art is not None:
            # Retire the artifact once it has done its job. Retained, it would let the
            # NEXT round's kind selection reconstruct these bytes and answer `targeted`,
            # silently re-aiming a downstream fixture whose subject is the ledger, the
            # budgets, or convergence — none of which is the round kind. The rows that
            # grade a scoped round's reachability stage explicitly and keep theirs.
            #
            # DISCLOSED CONSEQUENCE: this leaves a `staged_paths` record naming a file
            # that no longer exists, and it pins the revise-then-open-round fixtures to a
            # state a real post-#1104 run does not reach — such a run keeps its artifact,
            # so the tool selects `targeted` and refuses a hardcoded `--kind discovery`
            # with `kind-mismatch`. That combined flow is covered on its own by the #793
            # kind-mismatch row; what this deletion buys is that a fixture whose subject
            # is something else does not have to be re-graded to keep expressing it.
            art.unlink(missing_ok=True)
        return out

    def open_round(self, n, verdict='REVISE', findings=1):
        Path(self.tmp, 'd.md').write_text(f'draft {n}\n', encoding='utf-8')
        # issue #1751: no round is free-funded any more, so every round this helper opens is
        # user-elected. Record the election before the dispatch (the funding gate refuses an
        # unfunded open). A test driving the unfunded/ceiling path dispatches directly rather
        # than through this helper.
        self('record-offer', self.slug, '--accepted', nonce=True)
        digest = self._field(
            self('record-dispatch', '--kind', 'discovery', self.slug, '--round', str(n), '--arm', 'file',
                 '--draft-file', 'd.md', nonce=True), 'digest=', 'record-dispatch')
        self('record-return', self.slug, '--round', str(n), '--verdict', verdict,
             '--findings-count', str(findings), '--carriage-object-id', digest,
             nonce=True)
        return digest

    def adjudicate(self, n, verdict='REVISE', must=1, unresolved='1', ledger=None):
        argv = ['record-adjudication', self.slug, '--round', str(n), '--verdict', verdict,
                '--must-revise', str(must), '--advisory', '0', '--invalid', '0',
                '--unresolved-must-revise', str(unresolved)]
        if ledger is not None:
            argv.append('--ledger-stdin')
        return self(*argv, stdin=ledger, nonce=True)

# AC1 coverage row — the protocol-vocabulary constant covers every token the printers emit.
_tree603 = ast.parse(Path(_IAS603).read_text(encoding='utf-8'))
_funcs603 = {_n.name: _n for _n in ast.walk(_tree603) if isinstance(_n, ast.FunctionDef)}


def _tok603(node):
    """Every `key=` token in the string literals under `node`."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.update(re.findall(r'([a-z_][a-z0-9_]*)=', sub.value))
    return out


# Map every node to its enclosing module-level function, so a Name can be resolved
# against the assignments that are actually in scope for it.
_owner603 = {}
for _fn603 in _funcs603.values():
    for _n603 in ast.walk(_fn603):
        _owner603.setdefault(_n603, _fn603)

# TRANSITIVE harvest, to a fixed point. Earlier revisions of this row special-cased one
# emission shape at a time and were wrong three times running (PR #612 review): the
# original saw only literals inside the `print` arg, so `_binding_line`'s RETURNED line
# was invisible and `bound=`/`latest_revision_landed=` shipped emitted, unlisted, and
# therefore unrefused by `_forged_protocol_token` while their siblings on the same line
# were refused. Adding a helper-descent arm then missed `out += f' stdin_digest={…}';
# print(out)`. Adding a Name arm then still missed `print('\n'.join(lines) …)`, where the
# arg is an IfExp and the literals live in a comprehension — which is `query-findings`'
# own line, the exact surface the vocabulary refusal exists to protect. Chasing shapes is
# the wrong move: follow the DATA instead. Seed with the print args and close over both
# name-binding and one-level calls until nothing new appears, so a new emission shape is
# covered by construction rather than by another arm here.
_printed603 = set()
for _node in ast.walk(_tree603):
    if not (isinstance(_node, ast.Call) and isinstance(_node.func, ast.Name)
            and _node.func.id == 'print'):
        continue
    _work603 = list(_node.args)
    _seen603 = set()
    while _work603:
        _cur603 = _work603.pop()
        if id(_cur603) in _seen603:
            continue
        _seen603.add(id(_cur603))
        _printed603 |= _tok603(_cur603)
        _fn603 = _owner603.get(_cur603)
        for _sub603 in ast.walk(_cur603):
            # a name → every value bound to it in the enclosing function
            if isinstance(_sub603, ast.Name) and _fn603 is not None:
                for _st603 in ast.walk(_fn603):
                    if (isinstance(_st603, ast.Assign)
                            and any(isinstance(_t603, ast.Name)
                                    and _t603.id == _sub603.id
                                    for _t603 in _st603.targets)) or (isinstance(_st603, (ast.AugAssign, ast.AnnAssign))
                          and isinstance(_st603.target, ast.Name)
                          and _st603.target.id == _sub603.id
                          and _st603.value is not None):
                        _work603.append(_st603.value)
                    elif (isinstance(_st603, ast.comprehension)
                          and isinstance(_st603.target, ast.Name)
                          and _st603.target.id == _sub603.id):
                        _work603.append(_st603.iter)
            # a call to a module-level function → everything it returns
            if (isinstance(_sub603, ast.Call) and isinstance(_sub603.func, ast.Name)
                    and _sub603.func.id in _funcs603):
                for _ret603 in ast.walk(_funcs603[_sub603.func.id]):
                    if isinstance(_ret603, ast.Return) and _ret603.value is not None:
                        _work603.append(_ret603.value)


print()
print("issue-audit-state: reproducible per-finding evidence (issue #704)")


def _reason(res):
    """The `steering_reason` token, from a `_steer_row` result or a raw CompletedProcess."""
    text = res['ret'] if isinstance(res, dict) else res.stdout
    return text.strip().split('steering_reason=', 1)[1].split()[0]
issue_audit_state._validate(
    dict(_GOOD, rounds=[_round709(instructions=dict(_GOOD_INSTR,
                                                    dispatch_regeneration='diverged'))]), 's')


# ── issue #708: per-dimension coverage evidence ─────────────────────────────────────
print()
print("issue-audit-state: Step 3.6 per-dimension coverage evidence (issue #708)")


# ── issue #705: the scripts/stage-draft-write.py helper (T8/AC19) ────────────────────
_SDW = str(SCRIPTS / 'stage-draft-write.py')


def _sdw(*argv, stdin=None):
    return _subprocess.run([sys.executable, _SDW, *argv], input=stdin,
                           capture_output=True)


def _sdw_stage(base, data):
    """Drive `stage` and return `(digest, resolved_path, completed_process)`.

    Issue #793 made `--path` a BASE that `stage` completes with the staged bytes' digest,
    so every row below reads the artifact back from the RESOLVED path this reports rather
    than from the base it passed in — a base-path read would now name a file that does not
    exist, and reconciling these rows is part of that change, not a separate cleanup.
    """
    r = _sdw('stage', '--path', base, stdin=data)
    toks = dict(t.split('=', 1) for t in r.stdout.decode().split() if '=' in t)
    return toks.get('digest'), toks.get('path'), r


# ── #815 workpad.py `deferred-presence`: the bounded three-state predicate ──────
# Phase 4 gates the load of `skills/implement/references/deferred-ac-followups.md`
# on this subcommand's exit code, so every row below is a routing decision: a wrong
# `not-outstanding` strands deferred work with no follow-up issue and no reflection.
print()
print("#815 workpad deferred-presence predicate")


def _dp_body(progress_extra='', acs_extra='', reflection_extra=''):
    """A minimal workpad body carrying the three regions #815 names as the
    reachable injection surfaces (a Progress note, the mirrored criteria, a
    reflection), so an injection fixture differs from the clean one by exactly
    the injected line."""
    return (
        "<!-- devflow:workpad -->\n"
        "# DevFlow Workpad — Issue #815\n\n"
        "**Status:** 🚀 Documenting\n"
        "**Last updated:** 2026-07-25 00:00 UTC\n\n"
        "## Progress\n"
        "- [ ] **Setup** — branch & workpad\n"
        "- [ ] **Implement**\n"
        f"{progress_extra}"
        "\n## Acceptance Criteria\n"
        "- [ ] alpha\n"
        f"{acs_extra}"
        "\n## Devflow Reflection\n"
        "<details>\n<summary>Devflow Reflection (click to expand)</summary>\n\n"
        f"{reflection_extra}"
        "</details>\n"
    )


def _dp_note(text):
    return f"  - 12:00:00 — {text}\n"


def _dp_rec(pr, kind, text):
    """A scope-decision record rendered exactly as the production writer does."""
    return workpad._render_scope_decision(str(pr), kind, text)

# The marker is keyed on the NORMALIZED projection, so passing the note's verbatim text
# (the natural slip — the reference sources the issue body from that note) discharges
# nothing. That is the duplicate-filing regression the contract sentence exists to stop.
DP_TAGGED = 'ship  the widget (post-merge)'
_dp_tagged_body = _dp_body(progress_extra=_dp_note(_dp_rec(42, 'deferred', DP_TAGGED)))


# ── #1876 workpad.py resume-point: mid-phase re-anchor navigation record ────────
print("#1876 workpad resume-point record + read-back")

# ── #1513 workpad.py `deferred-reflection-audit`: is every deferred reflection backed? ──
# A `--reflection-kind deferred` bullet renders under `### ⚠️ Action required` and reads
# as a tracked deferral, but nothing files a reflection — the two channels that file a
# follow-up issue are the scope-decision-deferred records and the review-and-fix
# manifest. This backstop makes an UNBACKED deferred reflection detectable at Phase 4.0.6
# instead of silently passing completion.
print()
print("#1513 workpad deferred-reflection-audit backstop")
# The guard reads the Progress section through `_progress_content_or_none(body) or ''`,
# which reads as an arm where the comparand set is empty and every value warns. That
# arm is UNREACHABLE: `_apply_mutations` raises _UpdateError("section '## Progress'
# not found") before the guard runs, so an unresolvable section fails the mutation
# loudly rather than warning. Pin the reachable half of that boundary — the raise —
# so a future edit that made the guard's fallback live would have to face this row.
_dp_no_progress = _dp_tagged_body.replace('## Progress\n', '## Steps\n')
try:
    apply_mut(_dp_no_progress, make_args(mark_deferred_filed=['ship the widget']))
    _dp_no_prog_outcome = 'no raise'
except workpad._UpdateError as _e:
    _dp_no_prog_outcome = str(_e)

# ---------------------------------------------------------------------------
# #814: `update` suppresses the workpad-body echo on stdout by default; the new
# `--print-body` flag restores it byte-for-byte. The unit level is the ONLY level
# that drives the `_NoOpReplay` checkpoint-replay arm (lib/test/run.sh issues no
# --checkpoint call), so the replay assertions live here; the subprocess-level
# stdout bytes are asserted by the run.sh #814 block.
# ---------------------------------------------------------------------------

# The checkpoint-replay arm: a checkpoint-only call whose key already exists.
_REPLAY_BODY = _CP_BODY.replace(
    "  - 02:00:00 — /devflow:implement run started",
    "  - 02:00:00 — /devflow:implement run started\n  - 02:01:00 — invoke " + _MK)

_code, _out, _err, _patched = _drive_cmd_update(_REPLAY_BODY, checkpoint=[[_CPKEY, "x"]])

# One drive establishes both halves: `--print-body` restores the replay arm's echo,
# AND — because it is absent from `_has_non_checkpoint_mutation`'s allowlist — a
# checkpoint-only call carrying it still short-circuits as a replay with no PATCH.
_code, _out, _err, _patched = _drive_cmd_update(
    _REPLAY_BODY, checkpoint=[[_CPKEY, "x"]], print_body=True)

# The clean PATCH path: stdout suppressed, one breadcrumb naming the comment id.
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, note=['n'])

_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, note=['n'], print_body=True)

# The breadcrumb carries the Status value read back from the PATCH response, which is
# the one read-back an exit code cannot discharge (the SKILL.md landed-Status rule).
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, status='Reviewing')

# The volatile-tick-miss exception: no breadcrumb (a success-shaped line beside a
# failing exit code would re-create the split the exit-code rule prevents), and the
# body IS still written, because the mandated positional re-resolution reads it.
_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, note=['n'], tick_ac=['NO_SUCH_AC'])

# Non-writing exit paths keep their exit codes and write nothing to stdout.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY.replace("## Plan\n", "").replace("- [ ] Plan step one\n", "")
            .replace("- [ ] Plan step two\n", ""),
    replace_plan_file='/nonexistent/plan.md')

_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, patch_fails=True, note=['n'])

_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, expect_status="Reviewing", note=['n'])

_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, expect_comment_id="999", note=['n'])

# The breadcrumb assertion is shape-scoped, not a stderr line count: a --status
# Complete finalize over unticked ## Plan rows still writes its existing warning, and
# the breadcrumb sits beside it.
_code, _out, _err, _patched = _drive_cmd_update(
    GATE_BODY.replace('- [x] Plan step two', '- [ ] Plan step two'), status='Complete')

# The other conditional exit-0 warning — the un-mirrored AC placeholder — is driven
# too, so both co-resident warnings are shown not to displace the breadcrumb. The
# assertion stays shape-scoped (a count of breadcrumb-shaped lines), never a stderr
# line count, so a third warning could not make it brittle.
_code, _out, _err, _patched = _drive_cmd_update(
    GATE_BODY.replace('- [x] AC one\n- [x] AC two',
                      '- [x] ' + workpad._AC_PENDING_PLACEHOLDER),
    status='Complete')


# The breadcrumb's three read-back arms, each driven — they are the operands
# skills/implement/SKILL.md's rewritten "Always verify a Status PATCH actually
# landed" rule reads, so an undriven arm is a prose contract with no coverage.
# `_drive_cmd_update`'s stub answers the PATCH by echoing the body it was handed, so
# a fixture whose Status line is stripped produces a Status-less PATCH response.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, status='Reviewing',
    patch_response="<!-- devflow:workpad -->\n# DevFlow Workpad\n\nno status line here\n")

# An EMPTY PATCH response (a throttled/oversized write) is reported distinctly from a
# response whose body simply carries no Status line: pointing the reader at a corrupt
# comment body when the RESPONSE was empty sends them after the wrong fault.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, status='Reviewing', patch_response="")

# The landed-Status comparison is machine-observable, not prose-only. Both halves are
# driven, because a predicate that compared the requested status against itself would
# stay green on the matching half alone: a PATCH that returns 200 while the comment
# body still carries the OLD status must warn, and a PATCH that landed must not.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, status='Reviewing', patch_response=IDX_BODY)

_code, _out, _err, _patched = _drive_cmd_update(IDX_BODY, status='Reviewing')

# The WARNING is NOT gated on the clean path: it is failure-shaped, so it composes
# with the volatile-miss report rather than re-creating the success/failure split —
# and the combined --status + tick shape is where a stale Status is most likely.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, status='Reviewing', tick_ac=['NO_SUCH_AC'], patch_response=IDX_BODY)
# ... and it is still a MISMATCH guard on that path, not an unconditional miss-path
# line: the same shape with a read-back that agrees raises nothing. Without this the
# sibling above is satisfied by a mutant that fires the WARNING whenever a tick missed.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, status='Reviewing', tick_ac=['NO_SUCH_AC'])

# The breadcrumb fires on EVERY exit-0 PATCH path, including a checkpoint INSERT —
# the shape .github/workflows/devflow-implement.yml's gate-adopted / claude-invoke
# calls issue, which carry no --status and no --note.
_code, _out, _err, _patched = _drive_cmd_update(_CP_BODY, checkpoint=[[_CPKEY, "invoked"]])

# The success breadcrumb is the caller's "it landed" signal, so the paths that never
# PATCH must not emit it — otherwise the absent-breadcrumb rule the skill routes on
# reads a success line on a run that persisted nothing. The stdout-silence half of
# each path is asserted in run.sh's #814 block; these cover the stderr half.
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, replace_plan_file="/nonexistent/devflow-814-x")
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, note=['n'], expect_comment_id="999")


# ── #1508: cmd_patch preserves the leading marker lines a rewrite would clobber ──
# A full-body rewrite composes its bytes from state the caller holds, so a caller that
# does not retype the run-key/verdict markers drops them. The comment's identity is its
# line-1 marker, so a marker-resolving reader then reads "no such comment exists"
# rather than erroring. These drive the request body cmd_patch actually emits, so a
# preservation that never fires turns them RED.
_RUNKEY = '<!-- prflow:review-progress run=31356552464-1 -->'


_HEADING = '# PRFlow Review — PR #1523\n\nPhase 4 rewrite from held state.\n'


def _drive_cmd_patch_read_failure(new_body=None, live=None):
    """cmd_patch when the live body cannot be established.

    `live=None` raises from the read; any other value is the raw stdout the stubbed
    read returns, so an arm can model exactly what `gh` emits — an error envelope
    carrying no `.body` key, or the literal `null` a `--jq .body` read would render
    for one. Returns (sent body, stderr, exit code).
    """
    saved = (workpad._run, workpad._repo_full)
    sent = {}

    def _fake(cmd, **kw):
        if '-X' in cmd and 'PATCH' in cmd:
            operand = next(c for c in cmd if c.startswith('body=@'))
            sent['body'] = Path(operand[len('body=@'):]).read_text(encoding='utf-8')
            return _FakeRun(sent['body'])
        if live is None:
            raise _sp295.CalledProcessError(1, cmd)
        if isinstance(live, BaseException):
            # An exception instance models a read failure whose CAUSE the breadcrumb
            # must render — a `CalledProcessError` carrying gh's own stderr payload.
            raise live
        if live is OSError:
            # An absent `gh` binary — the other arm of the same `except`, and the one
            # whose exception carries no `.stderr` for the breadcrumb to read.
            raise OSError(2, 'No such file or directory')
        return _FakeRun(live)

    workpad._run = _fake
    workpad._repo_full = lambda *a, **kw: 'owner/repo'
    err = io.StringIO()
    code = None
    with _tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as tf:
        tf.write(_RUNKEY + '\n' + _HEADING if new_body is None else new_body)
        path = tf.name
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                workpad.cmd_patch(argparse.Namespace(comment_id=7, body_file=path))
            except SystemExit as e:
                code = e.code
    finally:
        workpad._run, workpad._repo_full = saved
        _os.unlink(path)
    return sent.get('body'), err.getvalue(), code


_sent, _stderr, _code = _drive_cmd_patch_read_failure()

# The other arm of the same unknown: nothing downstream can tell a dropped marker from
# "there was no such comment", so a composed body carrying none refuses rather than
# restoring the very clobber this preservation exists to prevent.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(new_body=_HEADING)

# `gh` can emit an error envelope with no `.body` key while exiting 0. Unknown is not
# zero: that must take the same arm as a raised read, never read as "no markers".
# Driven with the envelope `gh` actually emits, not an empty stdout that cannot occur.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(
    new_body=_HEADING, live='{"message":"Not Found","status":"404"}\n')

# The `--jq .body` rendering of that same envelope: jq prints the literal `null`, which
# a presence check reading jq's output cannot tell from a body. A read that regressed to
# `--jq .body` would hand the merge "null" as an established marker-less body and PATCH
# the composed body as typed — the exact clobber this preservation prevents.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(new_body=_HEADING, live='null\n')

# A present-but-JSON-null `body` (GitHub can return one) is likewise not a body.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(
    new_body=_HEADING, live='{"id":7,"body":null}\n')

# The other exception the same `except` catches — an absent `gh` binary — carries no
# `.stderr`, so it exercises the other limb of the breadcrumb's cause selection.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(new_body=_HEADING, live=OSError)

# The common gh-failed case: `CalledProcessError` DOES carry `.stderr`, and a
# `subprocess` configured without text mode carries it as bytes. The breadcrumb must
# render that payload as text, stripped — not `b'...'` and not the exception's own
# "Command ... returned non-zero exit status" repr, neither of which names the cause.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(
    new_body=_HEADING,
    live=_sp295.CalledProcessError(1, ['gh'], stderr=b'gh: HTTP 502 upstream  \n'))

# The text-mode counterpart of the same limb: `.stderr` is already a str, so only the
# strip applies. Both spellings must reach the same breadcrumb text.
_sent, _stderr, _code = _drive_cmd_patch_read_failure(
    new_body=_HEADING,
    live=_sp295.CalledProcessError(1, ['gh'], stderr='gh: HTTP 502 upstream\n'))

# A payload that is not JSON at all — an HTML error page from a proxy, at exit 0. The
# presence read must treat it as unestablished rather than letting the decode error
# escape cmd_patch uncaught (it is neither CalledProcessError nor OSError).
_sent, _stderr, _code = _drive_cmd_patch_read_failure(
    new_body=_HEADING, live='<html><body>502 Bad Gateway</body></html>\n')


def _drive_cmd_patch_unreadable_body_file():
    """cmd_patch when the body file passes `is_file()` but its read raises.

    A real unreadable file would depend on file modes and on the runner's uid (root
    reads a 0000 file), so the failure is induced at the read itself — the arm under
    test — leaving the mode question out of the assertion entirely.
    """
    class _UnreadablePath(type(Path())):
        # Every read route is closed, not just `read_text`: were `cmd_patch`'s
        # early-read arm to reach the body another way, an unclosed route would
        # fall through to the real filesystem and this test would pass while
        # asserting nothing about the unreadable arm.
        def read_text(self, *a, **kw):
            raise OSError(13, 'Permission denied')

        def read_bytes(self, *a, **kw):
            raise OSError(13, 'Permission denied')

        def open(self, *a, **kw):
            raise OSError(13, 'Permission denied')

    saved = (workpad.Path, workpad._run, workpad._repo_full)
    workpad.Path = _UnreadablePath
    workpad._run = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError('cmd_patch must not reach gh when the body file is unreadable'))
    workpad._repo_full = lambda *a, **kw: 'owner/repo'
    err = io.StringIO()
    code = None
    with _tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as tf:
        tf.write(_HEADING)
        path = tf.name
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                workpad.cmd_patch(argparse.Namespace(comment_id=7, body_file=path))
            except SystemExit as e:
                code = e.code
    finally:
        workpad.Path, workpad._run, workpad._repo_full = saved
        _os.unlink(path)
    return err.getvalue(), code


# Deferred (review 4900412294, Suggestion 2): `_patch_comment_body`'s `raise ValueError`
# guard, its temp-write `except OSError`, and its `finally` unlink swallow stay untested.
# The first is unreachable from either call site (both pass exactly one of text/body_path)
# and the other two are best-effort cleanup with no observable outcome to assert. Revisit
# if a caller reaches the helper with neither argument, or if the cleanup gains an effect
# a caller can observe.

_stderr, _code = _drive_cmd_patch_unreadable_body_file()


def _drive_cmd_patch_write_failure():
    """`(stderr, code)` when the MERGED-body PATCH itself fails.

    The live body carries a marker the composed body omits, so the run takes the
    staged-merged-body PATCH route rather than the caller's-own-file one — the route
    whose failure arm the other read-failure drivers never reach.
    """
    saved = (workpad._run, workpad._repo_full)

    def _fake(cmd, **kw):
        if '-X' in cmd and 'PATCH' in cmd:
            exc = _subprocess.CalledProcessError(1, cmd)
            exc.stderr = b'gh: PATCH refused\n'
            raise exc
        return _FakeRun(_json.dumps({'id': 7, 'body': _RUNKEY + '\n' + _HEADING}))

    workpad._run = _fake
    workpad._repo_full = lambda *a, **kw: 'owner/repo'
    err = io.StringIO()
    with _tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as tf:
        tf.write(_HEADING)
        path = tf.name
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            workpad.cmd_patch(argparse.Namespace(comment_id=7, body_file=path))
    except SystemExit as e:
        return err.getvalue(), e.code
    finally:
        workpad._run, workpad._repo_full = saved
        _os.unlink(path)
    return err.getvalue(), None


_stderr, _code = _drive_cmd_patch_write_failure()

# Echo SOURCE, not merely echo presence. `--print-body` must reproduce what the PATCH
# RESPONSE carried — the bytes the pre-#814 code wrote — never the body this process
# just composed locally. run.sh cannot ask this: its gh stub answers a PATCH by teeing
# back the body it received, so the two sources are identical there and a comparison
# passes either way. Here `patch_response` is a sentinel that is deliberately NOT the
# stored body, so echoing the local mutation turns this RED.
_RESP_SENTINEL = "PATCH RESPONSE SENTINEL — not the locally mutated body\n"
_code, _out, _err, _patched = _drive_cmd_update(
    IDX_BODY, note=['n'], print_body=True, patch_response=_RESP_SENTINEL)


# ---------------------------------------------------------------------------
# issue #1214: the /prflow:implement Phase 3.4 acceptance-criteria gate degrades
# with a DISTINCT label instead of wedging (part b), and a failed workpad write
# is BUFFERED locally and REPLAYED idempotently (part c).
# ---------------------------------------------------------------------------
print()
print("issue #1214: acs-gate defined degradation + failed-write buffering/replay")


def _run_acs_gate(read_effect, fallback='(unset)'):
    """Drive workpad.cmd_acs_gate with `_acs_read_workpad` stubbed to a clean read
    / a clean absence (SystemExit 2) / a transport failure (SystemExit 3), and the
    issue-body fallback stubbed to a value or None. Returns (exit_code, stdout)."""
    saved = (workpad._acs_read_workpad, workpad._acs_gate_issue_body_criteria)
    if read_effect == 'clean':
        _items = parse_acs._parse_checkboxes(parse_acs.extract_section(
            "## Acceptance Criteria\n- [x] alpha\n- [ ] beta\n", 'Acceptance Criteria'))
        workpad._acs_read_workpad = lambda cmd, issue: (
            "body", ["- [x] alpha", "- [ ] beta"], _items)
    elif read_effect == 'absent':
        def _r(cmd, issue):
            raise SystemExit(2)
        workpad._acs_read_workpad = _r
    elif read_effect == 'transport':
        def _r(cmd, issue):
            raise SystemExit(3)
        workpad._acs_read_workpad = _r
    if fallback != '(unset)':
        workpad._acs_gate_issue_body_criteria = lambda issue: fallback
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            workpad.cmd_acs_gate(argparse.Namespace(issue=1214))
    except SystemExit as e:
        code = e.code if e.code is not None else 0
    finally:
        workpad._acs_read_workpad, workpad._acs_gate_issue_body_criteria = saved
    return code, out.getvalue()


# Clean workpad read → exit 0, `source: workpad`, criteria rendered.
_c, _o = _run_acs_gate('clean')

# AC6: a clean ABSENCE keeps the existing benign shape (exit 2, `workpad-absent`)
# and is NOT rerouted onto the transport-failure label.
_c, _o = _run_acs_gate('absent')

# AC4: a simulated transport failure produces the distinct `workpad-read-failed`
# label, recovers criteria from the issue body, and NEVER passes (non-zero exit).
_c, _o = _run_acs_gate('transport', fallback='- [ ] recovered-from-issue-body')

# AC5: when the issue-body fallback is ALSO unavailable, the result is reported as
# `unestablished` and the gate does not pass.
_c, _o = _run_acs_gate('transport', fallback=None)

# Review finding (PR #1227, test-coverage gap): the `None`-vs-`""` discriminator is
# the "unknown is not zero" boundary of this gate, and only the `None` side was
# driven. An issue body that is REACHABLE but carries no criteria is an ESTABLISHED
# negative — it routes to `workpad-read-failed` (exit 3), never to `unestablished`
# (exit 4). Without this row, collapsing `if body_md is None` into `if not body_md`
# reroutes an established negative to unestablished and the suite stays green.
_c, _o = _run_acs_gate('transport', fallback='')


# Failed-write buffering and replay (part c). Drive cmd_update against a stubbed gh
# layer, with the buffer path redirected to a throwaway directory so the test is
# hermetic.
_WP1214 = (
    "<!-- prflow:workpad -->\n"
    "# DevFlow Workpad — Issue #1214\n\n"
    "**Status:** 🚀 Setup\n"
    "**Branch:** `b`\n"
    "**Last updated:** 2026-01-01 00:00 UTC\n\n"
    "## Progress\n"
    "- [ ] **Setup**\n\n"
    "## Plan\n"
    "- [ ] x\n\n"
    "## Acceptance Criteria\n"
    "- [ ] a\n\n"
    "## Devflow Reflection\n"
    "<details>\n"
    "<summary>Devflow Reflection (click to expand)</summary>\n\n"
    "</details>\n"
)
_MARK1214 = '<!-- prflow:workpad -->'


def _update_args(**kw):
    base = {
        'issue': 1214, 'marker': None, 'status': None, 'branch': None, 'run_link': None,
        'pr_link': None, 'tick_progress': [], 'tick_plan': [], 'tick_plan_n': [], 'tick_ac': [],
        'tick_ac_n': [], 'rewrite_ac': [], 'note': [], 'reflection': [], 'reflection_file': [],
        'note_file': [],
        'reflection_kind': None, 'replace_plan_file': None, 'replace_acs_file': None,
        'set_reproduction_file': None, 'checkpoint': None, 'record_completion_evidence': None,
        'record_classification': None, 'reconcile_reproduction': None, 'mark_deferred_filed': None,
        'bind_scope_decisions': None, 'scope_decision_deferred': None,
        'scope_decision_rewritten': None, 'print_body': False, 'expect_comment_id': None,
        'expect_status': None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _run_cmd_update(args, *, live_body, patch_fails, buffer_dir):
    """Run cmd_update with a stateful gh stub. Since issue #2042 the update path
    resolves the comment id AND its body in ONE comments-list scan (no separate
    body fetch), so the stub branches on the request SHAPE: a comments-list scan
    returns the full comment object (id + body + issue_url), and a PATCH captures
    the written body (or raises when patch_fails). Hermetic id cache (a temp dir),
    so the scan path always runs. Returns (exit_code, captured_patch_body, calls)."""
    saved = (workpad._run, workpad._repo_full, workpad._workpad_marker,
             workpad._workpad_buffer_path, workpad._workpad_id_cache_path)
    workpad._repo_full = lambda *a, **kw: 'owner/repo'
    workpad._workpad_marker = lambda explicit=None: _MARK1214
    workpad._workpad_buffer_path = lambda cid: Path(buffer_dir) / f'{cid}.json'
    _idcache = tempfile.mkdtemp(prefix='wp1214-idcache-')
    workpad._workpad_id_cache_path = lambda issue, mk: Path(_idcache) / f'{issue}.json'
    state = {'n': 0, 'patch_body': None}
    _obj = _json.dumps([{"id": 55512, "body": live_body,
                         "issue_url": "https://api.github.com/repos/owner/repo/issues/1214"}])

    def _run(cmd, **kw):
        state['n'] += 1
        if '-X' in cmd and 'PATCH' in cmd:
            # PATCH: capture the written body from the -F body=@<path> argument.
            for a in cmd:
                if isinstance(a, str) and a.startswith('body=@'):
                    state['patch_body'] = Path(a[len('body=@'):]).read_text(encoding='utf-8')
            if patch_fails:
                raise _subprocess.CalledProcessError(1, cmd, stderr='gh: HTTP 503')
            return _FakeRun(state['patch_body'] or '')
        # The comments-list scan resolves id + body together (issue #2042).
        return _FakeRun(_obj)

    workpad._run = _run
    code = 0
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            workpad.cmd_update(args)
    except SystemExit as e:
        code = e.code if e.code is not None else 0
    finally:
        (workpad._run, workpad._repo_full, workpad._workpad_marker,
         workpad._workpad_buffer_path, workpad._workpad_id_cache_path) = saved
        shutil.rmtree(_idcache, ignore_errors=True)
    return code, state['patch_body'], state['n']


# AC7: a workpad change that fails to persist is written to local storage, and the
# stored record survives the failing call.
_bufdir = tempfile.mkdtemp(prefix='wp1214-buf-')
_code, _pb, _n = _run_cmd_update(
    _update_args(note=['blocked: the run wedged on a 503']),
    live_body=_WP1214, patch_fails=True, buffer_dir=_bufdir)

# AC8: the stored record is replayed on the next SUCCESSFUL workpad call.
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir)

# AC9: replaying an already-applied stored record does not duplicate content.
_bufdir2 = tempfile.mkdtemp(prefix='wp1214-buf2-')
_dupnote = 'idempotent-replay-note'
(Path(_bufdir2) / '55512.json').write_text(
    _json.dumps([{'notes': [_dupnote], 'reflections': [], 'reflection_kind': 'note'}]),
    encoding='utf-8')
# The live body ALREADY contains the buffered note (a prior replay landed it).
_body_with_note = _WP1214.replace(
    "- [ ] **Setup**\n", f"- [ ] **Setup**\n  - 00:00:00 — {_dupnote}\n")
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_body_with_note, patch_fails=False, buffer_dir=_bufdir2)

# Regression (review finding): when the live body is missing the target section,
# a buffered item cannot be folded — so it must NOT be dropped along with the
# buffer file. The buffer survives for a later healthy body to replay.
_bufdir3 = tempfile.mkdtemp(prefix='wp1214-buf3-')
(Path(_bufdir3) / '55512.json').write_text(
    _json.dumps([{'notes': ['survivor-note'], 'reflections': [], 'reflection_kind': 'note'}]),
    encoding='utf-8')
# A body with NO '## Progress' section (truncated/malformed workpad), but still a
# valid Last updated line so the update itself PATCHes successfully.
_body_no_progress = (
    "<!-- prflow:workpad -->\n"
    "**Status:** 🚀 Setup\n"
    "**Last updated:** 2026-01-01 00:00 UTC\n\n"
    "## Acceptance Criteria\n- [ ] a\n"
)
_code, _pb, _n = _run_cmd_update(
    _update_args(),
    live_body=_body_no_progress, patch_fails=False, buffer_dir=_bufdir3)

# Review finding (PR #1227, finding 1): the FILE-sourced reflection is the feature's
# motivating case — `skills/implement/SKILL.md` mandates that a stop path deliver its
# Blocked reflection in a separate `--reflection-file` call carrying no inline
# `--note`/`--reflection`, and its documented inline fallback covers only a
# *structural* error, never a PATCH failure. So a `--reflection-file`-only call whose
# PATCH fails must buffer the payload, or the one reflection issue #1214 exists to
# rescue is the one it silently drops.
_bufdir4 = tempfile.mkdtemp(prefix='wp1214-buf4-')
_rfl_file = Path(_bufdir4) / 'payload.md'
_code, _pb, _n = _run_cmd_update(
    _update_args(reflection_file=[str(_rfl_file)], reflection_kind='blocked'),
    live_body=_WP1214, patch_fails=True, buffer_dir=_bufdir4)
# ...and replays into the Devflow Reflection section on the next successful call,
# under the kind the *replaying* call carries (the documented degraded-path rule).
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir4)

# A `--note-file`-only call whose PATCH fails must buffer the note through
# _cmd_update_inner's `_own_notes` append: the _apply_mutations coverage above never
# enters _cmd_update_inner, so dropping that append loses the note silently.
_bufdir5 = tempfile.mkdtemp(prefix='wp1813-buf5-')
_nf_file = Path(_bufdir5) / 'payload.md'
_code, _pb, _n = _run_cmd_update(
    _update_args(note_file=[str(_nf_file)]),
    live_body=_WP1214, patch_fails=True, buffer_dir=_bufdir5)
# ...and replays into ## Progress on the next successful call (a note, not a reflection).
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir5)

# `--note-file -` reaches BOTH stdin consumers in one call — _cmd_update_inner's buffering
# append and _apply_mutations' render. Dropping the memoization re-reads the exhausted
# stream and raises the empty-payload _UpdateError on a payload that was fine.
_bufdir6 = tempfile.mkdtemp(prefix='wp1813-buf6-')
_saved_stdin = sys.stdin
try:
    _code, _pb, _n = _run_cmd_update(
        _update_args(note_file=['-']),
        live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir6)
finally:
    sys.stdin = _saved_stdin

# Review finding (PR #1227, finding 2): idempotency must hold ACROSS buffered
# records, not only against the live body. Two failed calls carrying the same
# `--note` (a retry during an outage) buffer separate records; deduping only against
# the body folds each of them and renders the same bullet more than once.
_bufdir5 = tempfile.mkdtemp(prefix='wp1214-buf5-')
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir5)

# The same class one hop over: a buffered item identical to the text THIS call
# already carries inline. The buffered copy must be skipped, not folded alongside it.
_bufdir6 = tempfile.mkdtemp(prefix='wp1214-buf6-')
_dup_inline = 'duplicate-with-this-calls-own-note'
(Path(_bufdir6) / '55512.json').write_text(
    _json.dumps([{'notes': [_dup_inline], 'reflections': [], 'reflection_kind': 'note'}]),
    encoding='utf-8')
_code, _pb, _n = _run_cmd_update(
    _update_args(note=[_dup_inline]),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir6)
# ...and the same for a reflection, whose replay path is otherwise untested.
_bufdir7 = tempfile.mkdtemp(prefix='wp1214-buf7-')
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_WP1214, patch_fails=False, buffer_dir=_bufdir7)

# Review finding (PR #1227, test-coverage gap): the MIXED partial-replay case. One
# buffered section is foldable and the other is not, so `fully_replayed` must be
# False and the buffer must survive — the conjunct that a body-with-Progress-only
# body exercises and a fully-foldable or fully-unfoldable body does not.
_bufdir8 = tempfile.mkdtemp(prefix='wp1214-buf8-')
(Path(_bufdir8) / '55512.json').write_text(
    _json.dumps([{'notes': ['mixed-note'], 'reflections': ['mixed-reflection'],
                  'reflection_kind': 'note'}]),
    encoding='utf-8')
# `## Progress` present, `## Devflow Reflection` absent: the note folds, the
# reflection cannot.
_body_no_reflection = (
    "<!-- prflow:workpad -->\n"
    "**Status:** 🚀 Setup\n"
    "**Last updated:** 2026-01-01 00:00 UTC\n\n"
    "## Progress\n- [ ] **Setup**\n\n"
    "## Acceptance Criteria\n- [ ] a\n"
)
_code, _pb, _n = _run_cmd_update(
    _update_args(),
    live_body=_body_no_reflection, patch_fails=False, buffer_dir=_bufdir8)

# Review finding (PR #1227 round 2, blocker): replay identity must be an EXACT
# rendered-bullet match, never raw substring containment over the body. Under the
# containment test a buffered item whose text happens to be a substring of unrelated
# body content read as already-applied: it was neither folded into the PATCH nor kept,
# because `fully_replayed` stayed True and the buffer file was deleted — silent loss
# of the operator's record inside the feature built to prevent exactly that.
#
# `503` is the motivating shape: the failure that buffers the record is itself a 503,
# so a run's Blocked reflection routinely mentions it, and the live body already
# carries that digit string inside the earlier bullets the run wrote.
_bufdir9 = tempfile.mkdtemp(prefix='wp1214-buf9-')
# A body in which BOTH buffered texts occur as strict substrings of unrelated
# content — inside a longer Progress note and inside an existing reflection bullet —
# but neither is present as its own rendered bullet.
_body_substr = _WP1214.replace(
    "- [ ] **Setup**\n",
    "- [ ] **Setup**\n  - 00:00:00 — retrying after HTTP 503 from the comments endpoint\n"
).replace(
    "<summary>Devflow Reflection (click to expand)</summary>\n\n",
    "<summary>Devflow Reflection (click to expand)</summary>\n\n"
    "### ⚠️ Action required\n"
    "- ⛔ **Blocked:** the implement run is blocked on a failing dependency\n\n"
)
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_body_substr, patch_fails=False, buffer_dir=_bufdir9)


def _rendered_reflection_line(kind, text):
    """The bullet `_insert_reflection_bullet` writes for (kind, text) — derived
    from the shipped taxonomy so the expectation tracks the renderer."""
    _glyph, _label, _ = workpad._REFLECTION_KINDS[kind]
    return '- {} {}{}'.format(_glyph, (f'**{_label}:** ') if _label else '', text)


# A replayed reflection is filed under the REPLAYING call's kind; this call passes
# no --reflection-kind, so that is the default kind.
_replay_kind = workpad._DEFAULT_REFLECTION_KIND

# The converse must still hold: a genuinely already-rendered item is skipped. Drive
# both halves so the fix cannot be "never dedup" — a rendered note bullet and a
# rendered reflection bullet, each present verbatim, must not be written twice.
_bufdir10 = tempfile.mkdtemp(prefix='wp1214-buf10-')
_exact_note = 'exact-note-already-rendered'
_exact_rfl = 'exact-reflection-already-rendered'
(Path(_bufdir10) / '55512.json').write_text(
    _json.dumps([{'notes': [_exact_note], 'reflections': [_exact_rfl],
                  'reflection_kind': 'blocked'}]),
    encoding='utf-8')
# The reflection is rendered under the SAME kind the replay would use, so this is
# the plain same-shape dedup; the cross-kind case is driven separately below.
_body_exact = _WP1214.replace(
    "- [ ] **Setup**\n", f"- [ ] **Setup**\n  - 00:00:00 — {_exact_note}\n"
).replace(
    "<summary>Devflow Reflection (click to expand)</summary>\n\n",
    "<summary>Devflow Reflection (click to expand)</summary>\n\n"
    "### ℹ️ Notes\n"
    f"{_rendered_reflection_line(_replay_kind, _exact_rfl)}\n\n"
)
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_body_exact, patch_fails=False, buffer_dir=_bufdir10)

# A reflection already rendered under a DIFFERENT kind than the one this replay
# would file it under still counts as the same item — replay uses the replaying
# call's kind, so the glyph/label the original write used is not knowable and every
# kind's rendering has to dedup, or a run's terminal reflection is re-appended under
# a second heading on the next update.
_bufdir11 = tempfile.mkdtemp(prefix='wp1214-buf11-')
_crosskind = 'cross-kind-rendered-reflection'
(Path(_bufdir11) / '55512.json').write_text(
    _json.dumps([{'notes': [], 'reflections': [_crosskind],
                  'reflection_kind': 'blocked'}]),
    encoding='utf-8')
_body_crosskind = _WP1214.replace(
    "<summary>Devflow Reflection (click to expand)</summary>\n\n",
    "<summary>Devflow Reflection (click to expand)</summary>\n\n"
    "### ⚠️ Action required\n"
    "{}\n\n".format(_rendered_reflection_line('blocked', _crosskind))
)
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_body_crosskind, patch_fails=False, buffer_dir=_bufdir11)

# The section scoping half: a note text that appears verbatim as a whole line
# OUTSIDE `## Progress` (here as an Acceptance Criteria row) is not a rendered
# Progress bullet, so it must not authorize skipping-and-clearing.
_bufdir12 = tempfile.mkdtemp(prefix='wp1214-buf12-')
_offsection = 'text-that-lives-in-another-section'
(Path(_bufdir12) / '55512.json').write_text(
    _json.dumps([{'notes': [_offsection], 'reflections': [],
                  'reflection_kind': 'note'}]),
    encoding='utf-8')
_body_offsection = _WP1214.replace(
    "## Acceptance Criteria\n- [ ] a\n",
    f"## Acceptance Criteria\n- [ ] a\n- [ ] {_offsection}\n")
_code, _pb, _n = _run_cmd_update(
    _update_args(status='Reviewing'),
    live_body=_body_offsection, patch_fails=False, buffer_dir=_bufdir12)


print()
print("issue-audit-state: round resolution, next_call=, query-boundary (issue #795)")


# --- AC: the render boundary shape-checks every operand taken from recorded state, and a
# --- failing value yields a named refusal rather than an emitted string.
_ias795 = _load('ias795', SCRIPTS / 'issue-audit-state.py')

# `needs=` composition: caller-supplied operands render BARE and are named; state-derived
# ones render filled and are not.
_line = _ias795._next_call_invocation(
    'record-return', 'record-adjudication s',
    [('--nonce', 'abc'), ('--round', 2), ('--verdict', None)])

# --- #795: the CONTRACT CHECKER's own fail-closed arms are driven ------------------------
# `check-audit-lifecycle-contracts.py` is the machine-consumed boundary several ACs rest on,
# but every prior run of it was over a CLEAN tree — so it was only ever observed passing, and
# a guard observed only passing is not known to fail (issue #795 shadow review). Plant each
# defect shape it claims to catch and require the Refusal.
_alc_spec = importlib.util.spec_from_file_location(
    "_alc795", os.path.join(_REPO, "lib", "test", "check-audit-lifecycle-contracts.py"))
_alc795 = importlib.util.module_from_spec(_alc_spec)
_alc_spec.loader.exec_module(_alc795)

# --- the reused-API and module-load guards are driven, not merely stated -------------------
# `_load_extractor`'s name check and `_load_module`'s load guard are this arm's answer to
# "a rename in that general-purpose scanner must be a named RED breadcrumb, never a
# traceback". Both are fail-closed guards with a stated purpose, so both get a planted row.
_alc_api_saved = _alc795._EXTRACTOR_API
try:
    _alc795._EXTRACTOR_API = tuple(_alc_api_saved) + ("_not_a_real_extractor_helper",)
    try:
        _alc795._load_extractor()
    except _alc795.Refusal as _exc:
        _alc_api_refusal = str(_exc)
finally:
    _alc795._EXTRACTOR_API = _alc_api_saved

# A renamed or REMOVED FILE is the other half, and `spec_from_file_location` does NOT catch
# it — it returns a populated spec for a nonexistent path and the failure lands in
# `exec_module`. Without the load guard that escapes `main()` (which catches only Refusal).
_alc_ech_saved = _alc795._ECH
try:
    _alc795._ECH = _alc795.REPO / "lib" / "test" / "no-such-scanner-1466.py"
    # Catch broadly, then ATTRIBUTE: the defect this row plants is the load guard's absence,
    # whose signature is a raw `FileNotFoundError` escaping instead of a `Refusal`. A bare
    # `except Refusal` would let that escape abort this module's remaining rows (including
    # the wiring assertion below) rather than turning this one row RED, so the row grades
    # `isinstance(..., Refusal)` explicitly — the same shape the `_alc_dedup` row uses.
    try:
        _alc795._load_extractor()
    except Exception as _exc:
        _alc_load_refusal = str(_exc) if isinstance(_exc, _alc795.Refusal) else None
finally:
    _alc795._ECH = _alc_ech_saved

print()
print("issue-audit-state: tool-owned round kinds (issue #793)")

_m793 = issue_audit_state


def _793_state(**over):
    """A minimal in-memory state document for round-kind selection rows.

    Built by hand rather than driven through the CLI so a row can express exactly one
    failing selection condition; the CLI round-trips live in the shell module.
    """
    doc = {'schema_version': _m793.SCHEMA_VERSION, 'slug': 's', 'nonce': 'n',
           'rounds': [], 'revisions': [], 'overrides': []}
    doc.update(over)
    return doc

# ── issue #1105: a scoped round re-checks resolved claims + records the draft-line span ──
print("issue-audit-state: scoped rounds re-check resolved claims (issue #1105)")

_m1105 = issue_audit_state

# AC8 — the scoped-prompt renderer's empty-claim-set refusal stays coherent with the
# widened enumeration: a render over the widened (now resolved-inclusive) non-empty set
# succeeds, and a render over a genuinely empty set still refuses with its named breadcrumb.
_rap1105 = _load('_rap1105', SCRIPTS / 'render-audit-prompt.py')
_1105_scope_empty = _m1105.render_dispatch_scope('d' * 40, ['## A'], [])
try:
    _rap1105.parse_scope(_1105_scope_empty.decode('utf-8'))
    _1105_empty_refused = 'no-refusal'
except _rap1105.RenderError as _exc:
    _1105_empty_refused = 'empty-claim-set' if 'empty-claim-set' in str(_exc) else 'other'

# Driven through the real ingestion producer: a hand-built `{'1.1': 'partially'}` map
# asserted a property of a state `_validate` REFUSES to load, and named it as the
# recording behavior, which lives in _ingest_targeted_verdicts.
def _793_ingest(verdict_text, dispatched=('1.1',)):
    doc = _793_state(rounds=[{'round': 2, 'outcome': 'FILE', 'kind': 'targeted',
                              'attempts': [{'arm': 'file'}],
                              'scope': {'claim_ids': list(dispatched)}}])
    rnd = doc['rounds'][0]
    _m793._ingest_targeted_verdicts(
        doc, rnd, types.SimpleNamespace(claim_verdicts=verdict_text))
    return rnd.get('claim_verdicts'), rnd.get('targeted_return_unusable')


assert_eq("#793: a claim returned outside the closed set is RECORDED not-addressed",
          ({'1.1': 'not-addressed'}, None), _793_ingest('1.1 partially'))

assert_eq("#793: a dispatched claim absent from the return is recorded not-addressed",
          ({'1.1': 'not-addressed'}, None), _793_ingest('2.9 addressed'))

# The fail-open the Phase 3 review reproduced: a dict assignment is last-wins, so a return
# saying not-addressed and THEN addressed for one id recorded addressed — scheduling the
# confirming round and converging on a claim the auditor had just rejected.
assert_eq("#793: a DUPLICATE verdict for one claim id fails closed to not-addressed, "
          "whichever order the return states them in",
          ({'1.1': 'not-addressed'}, {'1.1': 'not-addressed'}),
          (_793_ingest('1.1 not-addressed\n1.1 addressed')[0],
           _793_ingest('1.1 addressed\n1.1 not-addressed')[0]))

assert_eq("#793: a return carrying NO per-claim block is recorded UNUSABLE — it reopens "
          "nothing and is not a sweep of not-addressed verdicts",
          ({}, True), _793_ingest(None))

assert_eq("#793: an unusable targeted return selects the confirming whole-draft round, "
          "never `proceed` on scoped-only evidence",
          'confirm-whole-draft',
          _m793.next_action({'rounds': [{'round': 2, 'outcome': 'FILE',
                                         'kind': 'targeted', 'claim_verdicts': {}}],
                             'confirming_rounds_used': 0}, 2))

assert_eq("#793: a duplicate-heading draft keeps BOTH sections in the delta — an edit to "
          "the first must not vanish behind a later same-named heading",
          ['## A', '## B'],
          _m793._changed_sections(b'## A\nx\n## B\nq\n## A\nz\n',
                                  b'## A\nEDITED\n## B\nCHANGED\n## A\nz\n'))

assert_eq("#793: the rendered record-dispatch suggestion carries --kind FILLED and names "
          "--scope-file in needs= (the forgotten-flag class #795 removed)",
          (True, True),
          (lambda line: ('--kind targeted' in line, '--scope-file' in line.split('needs=')[1]))(
              _m793._dispatch_next_call(
                  'query-next-action', 'sl', 'n', 'dispatch-embed-retry',
                  state={'rounds': [{'round': 1, 'outcome': None, 'kind': 'targeted',
                                     'attempts': [{'arm': 'file'}]}], 'nonce': 'n'})))

# ── the return-time regeneration arms, and the selection→dispatch window ──────────────
# Named by the Phase 3 test-coverage review as wholly untested: the two named scope-file
# steering reasons, the basis cross-check, and the discovery-arm refusal. Each is driven
# through the real CLI so the reason token is read off the recorded state, not inferred.

def _793_scoped_round(tmpdir_holder):
    """Open a real targeted round and return (run, scope_path, dispatch_digest, draft)."""
    td = tempfile.mkdtemp()
    tmpdir_holder.append(td)
    run = _Run603(td, slug='s793s')
    draft = Path(td, 'd.md')
    draft.write_text('# T\n\n## A\n\nold\n', encoding='utf-8')
    run('record-offer', run.slug, '--accepted', nonce=True)  # issue #1751: fund round 1
    dig = run._field(run('record-dispatch', '--kind', 'discovery', run.slug, '--round', '1',
                         '--arm', 'file', '--draft-file', 'd.md', nonce=True),
                     'digest=', 'record-dispatch')
    run('record-return', run.slug, '--round', '1', '--verdict', 'REVISE',
        '--findings-count', '1', '--carriage-object-id', dig, nonce=True)
    run.adjudicate(1, 'REVISE', must=1, unresolved='1', ledger='unresolved: a defect\n')
    _d, _p, _ = _sdw_stage(str(Path(td, '.prflow', 'tmp',
                                    'create-issue', run.slug, f'issue-draft-{run.slug}.N.staged.md')),
                           b'# T\n\n## A\n\nold\n')
    run('record-staged-write', run.slug, '--path', _p, '--digest', _d, nonce=True)
    draft.write_text('# T\n\n## A\n\nrevised\n', encoding='utf-8')
    run('record-revision', run.slug, '--after-round', '1', '--stdin-digest',
        stdin='# T\n\n## A\n\nrevised\n', nonce=True)
    scope = str(Path(td, 'scope.md'))
    run('write-dispatch-scope', run.slug, '--draft-file', str(draft), '--path', scope,
        nonce=True)
    return run, scope, draft


def _793_dispatch_scoped(run, scope, draft, rnd='2'):
    """Dispatch a targeted round WITH a recorded instruction file.

    The instruction file is what makes the scope-file steering arms reachable at all:
    without it `steering_state` short-circuits on `inputs-unrecorded` long before it
    regenerates anything, so a fixture that omits it grades nothing about the scope arms.
    """
    instr = str(Path(run.tmp, 'instructions.md'))
    rendered = _subprocess.run(
        [sys.executable, str(SCRIPTS / 'render-audit-prompt.py'), 'dispatch-instructions',
         '--slug', run.slug, '--draft-path', str(draft.resolve()),
         '--instructions-path', instr, '--scope-file', str(Path(scope).resolve())],
        capture_output=True, text=True)
    Path(instr).write_text(rendered.stdout, encoding='utf-8')
    run('record-offer', run.slug, '--accepted', nonce=True)  # issue #1751: fund the round
    return run('record-dispatch', '--kind', 'targeted', run.slug, '--round', rnd,
               '--arm', 'file', '--draft-file', str(draft.resolve()),
               '--scope-file', str(Path(scope).resolve()),
               '--instructions-file', instr,
               '--instructions-draft-path', str(draft.resolve()), nonce=True)


_793_tds = []

# AC: record-dispatch refuses a targeted dispatch whose scope basis no longer describes
# the bytes it audits — the ONLY guard on the selection→dispatch window, which exists
# because the skill re-runs the Step 3 gate in between.
_r, _scope, _draft = _793_scoped_round(_793_tds)
_draft.write_text('# T\n\n## A\n\nrevised AGAIN after the scope was frozen\n',
                  encoding='utf-8')
_bm = _r('record-dispatch', '--kind', 'targeted', _r.slug, '--round', '2', '--arm', 'file',
         '--draft-file', 'd.md', '--scope-file', _scope, nonce=True)
assert_eq("#793: a byte edit landing between selection and dispatch is refused, named "
          "(the recorded changed-section set names superseded regions)",
          (True, True), (_bm.returncode != 0, 'scope-basis-mismatch' in _bm.stderr))

# AC: --scope-file is a targeted-round input; a discovery round carries no scoped payload.
_dm = _r('record-dispatch', '--kind', 'discovery', _r.slug, '--round', '2', '--arm', 'file',
         '--draft-file', 'd.md', '--scope-file', _scope, nonce=True)
assert_eq("#793: --scope-file on a discovery round is refused, named",
          (True, True), (_dm.returncode != 0, 'scope-file-on-discovery' in _dm.stderr))

# AC: an ABSENT scope file at return time takes its OWN named reason, distinct from the
# tampered arm, because the two send a reader to opposite remedies.
_r2, _scope2, _draft2 = _793_scoped_round(_793_tds)
_d2 = _793_dispatch_scoped(_r2, _scope2, _draft2)
_dig2 = _d2.stdout.split('digest=', 1)[1].split()[0]
os.unlink(_scope2)
_ret2 = _r2('record-return', _r2.slug, '--round', '2', '--verdict', 'FILE',
            '--findings-count', '0', '--carriage-object-id', _dig2,
            '--claim-verdicts', '1.1 addressed', nonce=True)
assert_eq("#793: an ABSENT scope file at record-return records its own named reason",
          True, 'scope-file-unreadable' in _ret2.stdout)

# AC: a TAMPERED scope file records the tampered reason and withholds the clean ground.
_r3, _scope3, _draft3 = _793_scoped_round(_793_tds)
_d3 = _793_dispatch_scoped(_r3, _scope3, _draft3)
_dig3 = _d3.stdout.split('digest=', 1)[1].split()[0]
Path(_scope3).write_text(Path(_scope3).read_text(encoding='utf-8') + '- 9.9 — forged\n',
                         encoding='utf-8')
_ret3 = _r3('record-return', _r3.slug, '--round', '2', '--verdict', 'FILE',
            '--findings-count', '0', '--carriage-object-id', _dig3,
            '--claim-verdicts', '1.1 addressed', nonce=True)
assert_eq("#793: a TAMPERED scope file records the tampered reason — distinct from the "
          "absent arm, and steering is not established",
          (True, True),
          ('scope-file-tampered' in _ret3.stdout, 'steering=not-established' in _ret3.stdout))

# AC 39: the seam's whole purpose — a targeted round records NO ledger of its own, so a
# run whose every claim returns not-addressed does not double the run-wide count.
_r4, _scope4, _draft4 = _793_scoped_round(_793_tds)
_d4 = _793_dispatch_scoped(_r4, _scope4, _draft4)
_dig4 = _d4.stdout.split('digest=', 1)[1].split()[0]
_r4('record-return', _r4.slug, '--round', '2', '--verdict', 'REVISE',
    '--findings-count', '1', '--carriage-object-id', _dig4,
    '--claim-verdicts', '1.1 not-addressed', nonce=True)
_doc4 = json.loads(Path(_r4.tmp, '.prflow', 'tmp',
                        'create-issue', _r4.slug, f'issue-audit-state-{_r4.slug}.json').read_text(encoding='utf-8'))
assert_eq("#793/AC39: an all-not-addressed targeted round leaves the run-wide effective "
          "unresolved count equal to the discovery round's, not doubled",
          (1, None),
          (_m793._effective_unresolved(_doc4), _doc4['rounds'][1].get('findings')))

# ── the answer-vocabulary cross-file contract, DERIVED not transcribed ────────────────
# Replaces the retired wording pin. The comparand is the tool's own closed tuple, so a
# token added to _NEXT_ACTIONS and forgotten in the skill's obey list goes RED — the exact
# drift this change introduced (confirm-whole-draft), which a literal wording pin would
# only have caught because the sentence happened to be rewritten.
# The Step 3.6 procedure is a declared ordered reference set (issue #1702), so the
# answer-vocabulary contract resolves against the whole member manifest (entry + members),
# not the single entry file the obey-verbatim list moved out of.
_793_MANIFEST = json.loads((SCRIPTS.parent / 'lib' / 'test'
                            / 'create-issue-step-3-6-members.json').read_text(encoding='utf-8'))
_793_STEP36 = "\n".join(
    (SCRIPTS.parent / _p).read_text(encoding='utf-8')
    for _p in [_793_MANIFEST['entry'], *_793_MANIFEST['members']])
assert_eq("#793: every _NEXT_ACTIONS token the tool can answer appears in the skill's "
          "obey-verbatim list (derived from the tuple, never transcribed)",
          [], [t for t in _m793._NEXT_ACTIONS if f'`{t}`' not in _793_STEP36])

assert_eq("#793: ... and the obey list names no token the tool cannot answer",
          [],
          [t for t in re.findall(r'`([a-z][a-z-]+)`',
                                 _793_STEP36.split('**Obey the answer verbatim**')[1]
                                 .split('.')[0])
           if t not in _m793._NEXT_ACTIONS])

# ── the remaining decided-treatment readers (AC 38/39/40), asserted not assumed ───────

assert_eq("#793/AC40: the final-byte coverage axis reads the latest WHOLE-DRAFT round, so "
          "a clean targeted round never sets it covered",
          2,
          _m793._last_discovery_round(
              {'rounds': [{'round': 2, 'outcome': 'FILE', 'kind': 'discovery',
                           'attempts': [{'arm': 'file'}], 'final_byte_pass': False},
                          {'round': 3, 'outcome': 'FILE', 'kind': 'targeted',
                           'attempts': [{'arm': 'file'}], 'final_byte_pass': False}]})['round'])

# AC 38: _valid_override and cmd_record_override must stay a MATCHED PAIR — both resolve
# their epoch from the same round, and both stay kind-blind. An override overrides
# AUDITING, not whole-draft evidence, so teaching one half to skip a targeted epoch would
# desynchronize the read-side gate from the write-side guard it mirrors.
_793_ovr_src = (SCRIPTS / 'issue-audit-state.py').read_text(encoding='utf-8')
assert_eq("#793/AC38: _valid_override and cmd_record_override resolve their epoch from "
          "the SAME kind-blind selector (a matched pair, neither taught to skip)",
          (True, True),
          ('epoch = last_completed(state)' in _793_ovr_src,
           'epoch = last_completed(doc)' in _793_ovr_src))

assert_eq("#793/AC39: a run whose latest completed round is targeted still answers on the "
          "override ground — the decline path files rather than dead-ending",
          True,
          _m793._valid_override(
              {'rounds': [{'round': 1, 'outcome': 'FILE', 'kind': 'targeted',
                           'attempts': [{'arm': 'embed'}]}],
               'revisions': [],
               # `recorded_at_ordinal` is the field the gate compares against
               # `revision_ordinal(state)` — 0 here, with no revisions recorded. An
               # embed-arm epoch carries no digest comparand, which is legal.
               'overrides': [{'kind': 'user-decline', 'recorded_at_ordinal': 0,
                              'surface': 'approve'}]}, None) is not None)

# AC 26: a targeted round returning DRAFT-UNREADABLE takes the existing unreadable-retry
# path unchanged, and the RETRY carries the round's recorded kind rather than a fresh
# selection. The review found this branch unreached by any test.
_r5, _scope5, _draft5 = _793_scoped_round(_793_tds)
_d5 = _793_dispatch_scoped(_r5, _scope5, _draft5)
_dig5 = _d5.stdout.split('digest=', 1)[1].split()[0]
_ur = _r5('record-return', _r5.slug, '--round', '2', '--verdict', 'DRAFT-UNREADABLE',
          '--carriage-object-id', _dig5, nonce=True)
assert_eq("#793/AC26: a targeted DRAFT-UNREADABLE return takes the unreadable-retry path "
          "unchanged (the round stays open, pending a retry)",
          (0, True),
          (_ur.returncode, 'outcome=pending' in _ur.stdout or 'dispatch' in _ur.stdout))

# The retry is validated against the ROUND's recorded kind, not a fresh selection — so a
# retry declaring the other kind is refused even though the round is legitimately open.
_wrong = _r5('record-dispatch', '--kind', 'discovery', _r5.slug, '--round', '2',
             '--arm', 'file', '--draft-file', str(_draft5.resolve()), nonce=True)
assert_eq("#793/AC26: the retry is selected against the round's RECORDED kind — a retry "
          "declaring the other kind is refused, named",
          (True, True),
          (_wrong.returncode != 0, 'kind-mismatch' in _wrong.stderr))

assert_eq("#793: last_completed stays kind-blind — it answers the newest completed "
          "round whatever its kind",
          3,
          _m793.last_completed(
              {'rounds': [{'round': 2, 'outcome': 'FILE', 'kind': 'discovery'},
                          {'round': 3, 'outcome': 'FILE', 'kind': 'targeted'}]})['round'])


# --- AC 38: summary_fields renders the verdict and class counts from the latest
# WHOLE-DRAFT round, and names the scoped round separately -------------------------
#
# The Step 4 audit summary is what a human reads to decide whether the draft is filable.
# A `targeted` round audits an enumerated claim set over a changed-section span, so
# rendering ITS verdict and class counts as the run's summary would report a scoped
# re-check as if a whole draft had been re-read. `last_completed` stays kind-blind (the
# row above), so this reader needs its own whole-draft selector — and the scoped round
# must still be VISIBLE, not merely suppressed, hence the separate field.
#
# Distinct from `_last_discovery_round`: that selector also excludes a final-byte pass,
# which for THIS reader is whole-draft evidence whose verdict #792 deliberately renders.
# Reusing it would silently revert that.

def _793_sum_state(rounds):
    """A completed-round-only state document `summary_fields` can be driven over."""
    return {'schema_version': _m793.SCHEMA_VERSION, 'slug': 's', 'nonce': 'n',
            'rounds': rounds, 'revisions': [], 'overrides': []}


def _793_sum_round(num, kind, outcome, *, mr, adv, inv, umr, final_byte=False):
    return {'round': num, 'kind': kind, 'outcome': outcome,
            'attempts': [{'arm': 'file', 'digest': 'd' * 40}],
            'adjudicated_verdict': outcome, 'must_revise_count': mr,
            'advisory_count': adv, 'invalid_count': inv,
            'unresolved_must_revise': umr, 'final_byte_pass': final_byte}


# A discovery round found 3 must-revise findings; a later targeted round re-checked them
# and came back clean. The summary must still report the DISCOVERY round's verdict and
# counts — the scoped round re-read no whole draft.
_793_sum_mixed = _m793.summary_fields(_793_sum_state([
    _793_sum_round(1, 'discovery', 'REVISE', mr=3, adv=1, inv=0, umr=3),
    _793_sum_round(2, 'targeted', 'FILE', mr=0, adv=0, inv=0, umr=0),
]))
assert_eq("#793/AC38: the summary verdict and every class count come from the latest "
          "WHOLE-DRAFT round, not the newer targeted one",
          ('REVISE', 'REVISE', 3, 1, 0, 3),
          (_793_sum_mixed['verdict'], _793_sum_mixed['adjudicated_verdict'],
           _793_sum_mixed['must_revise'], _793_sum_mixed['advisory'],
           _793_sum_mixed['invalid'], _793_sum_mixed['unresolved_must_revise']))

assert_eq("#793/AC38: the targeted round is NAMED separately rather than suppressed — "
          "a reader sees the scoped round ran",
          2, _793_sum_mixed['scoped_round'])

# A run with no targeted round answers the identical fields it does today, and reports no
# scoped round — the negative control that keeps the widening from changing kind-blind runs.
_793_sum_plain = _m793.summary_fields(_793_sum_state([
    _793_sum_round(1, 'discovery', 'REVISE', mr=3, adv=1, inv=0, umr=3),
]))
assert_eq("#793/AC38: a run with no targeted round is unchanged, and names no scoped round",
          ('REVISE', 3, 3, None),
          (_793_sum_plain['verdict'], _793_sum_plain['must_revise'],
           _793_sum_plain['unresolved_must_revise'], _793_sum_plain['scoped_round']))

# A final-byte pass is whole-draft evidence (#792) — the new selector must NOT exclude it
# the way `_last_discovery_round` does, or this widening silently reverts #792's summary.
_793_sum_fb = _m793.summary_fields(_793_sum_state([
    _793_sum_round(1, 'discovery', 'REVISE', mr=3, adv=1, inv=0, umr=3),
    _793_sum_round(2, 'discovery', 'FILE', mr=0, adv=0, inv=0, umr=0, final_byte=True),
]))
assert_eq("#793/AC38: a final-byte pass still grounds the summary — the whole-draft "
          "selector excludes ONLY a targeted round",
          ('FILE', 0, None),
          (_793_sum_fb['verdict'], _793_sum_fb['must_revise'],
           _793_sum_fb['scoped_round']))

# Every targeted round is skipped, not merely the newest one.
_793_sum_two = _m793.summary_fields(_793_sum_state([
    _793_sum_round(1, 'discovery', 'REVISE', mr=3, adv=1, inv=0, umr=3),
    _793_sum_round(2, 'targeted', 'FILE', mr=0, adv=0, inv=0, umr=0),
    _793_sum_round(3, 'targeted', 'FILE', mr=0, adv=0, inv=0, umr=0),
]))
assert_eq("#793/AC38: consecutive targeted rounds are all skipped, and the NEWEST is the "
          "one named",
          ('REVISE', 3, 3),
          (_793_sum_two['verdict'], _793_sum_two['must_revise'],
           _793_sum_two['scoped_round']))

# A run whose ONLY completed round is targeted has no whole-draft evidence at all: the
# verdict and counts must read unestablished (None), never the scoped round's clean FILE.
# This is the fail-open the widening exists to close — reporting `verdict=FILE` here would
# tell a reader a whole draft passed when none was ever audited.
_793_sum_only = _m793.summary_fields(_793_sum_state([
    _793_sum_round(1, 'targeted', 'FILE', mr=0, adv=0, inv=0, umr=0),
]))
assert_eq("#793/AC38: a run whose only completed round is targeted reports NO whole-draft "
          "verdict or counts, and names the scoped round",
          (None, None, None, 1),
          (_793_sum_only['verdict'], _793_sum_only['must_revise'],
           _793_sum_only['unresolved_must_revise'], _793_sum_only['scoped_round']))

assert_eq("#793/AC38: the unestablished branch carries the new field too, so the field "
          "set is total on both of summary_fields' answers",
          None, _m793.summary_fields(None)['scoped_round'])

assert_eq("#793/AC38: scoped_round joins the closed protocol-token vocabulary, so an "
          "auditor-derived summary cannot forge the tool's own printed field",
          'scoped_round', _m793._forged_protocol_token('scoped_round=2'))

# ── the UNUSABLE targeted return must not dead-end (review finding, PR #884) ──────────
# `next_action` schedules `confirm-whole-draft` for ANY targeted round whose outcome is
# FILE while the confirming budget remains — the unusable return included, precisely
# because that round established nothing. The funding branch in `record-dispatch` must
# therefore be gated on the SAME predicate; gating it on the narrower "all claims
# addressed" made the scheduled round unfundable, so the run was told to open a round
# the tool then refused as `not funded`. Driven end to end through the real CLI: the
# unit-level predicate agreement is asserted below it, but only the CLI round-trip grades
# the dead end itself.
_r6, _scope6, _draft6 = _793_scoped_round(_793_tds)
_d6 = _793_dispatch_scoped(_r6, _scope6, _draft6)
_dig6 = _d6.stdout.split('digest=', 1)[1].split()[0]
# A targeted return carrying NO per-claim block at all: outcome FILE, round UNUSABLE.
_ret6 = _r6('record-return', _r6.slug, '--round', '2', '--verdict', 'FILE',
            '--findings-count', '0', '--carriage-object-id', _dig6, nonce=True)
_doc6 = json.loads(Path(_r6.tmp, '.prflow', 'tmp',
                        'create-issue', _r6.slug, f'issue-audit-state-{_r6.slug}.json').read_text(encoding='utf-8'))
assert_eq("#793: a targeted return with no per-claim block records outcome FILE and marks "
          "the round UNUSABLE (the precondition the dead end needed)",
          (0, 'FILE', True, {}),
          (_ret6.returncode, _doc6['rounds'][1]['outcome'],
           _doc6['rounds'][1].get('targeted_return_unusable'),
           _doc6['rounds'][1].get('claim_verdicts')))

_na6 = _r6('query-next-action', _r6.slug, '--round', '2', nonce=True)
assert_eq("#793: ... and next_action still schedules the confirming whole-draft round on "
          "the unusable return, exactly as its own contract states",
          True, 'confirm-whole-draft' in _na6.stdout)

_d6b = _r6('record-dispatch', '--kind', 'discovery', _r6.slug, '--round', '3',
           '--arm', 'file', '--draft-file', str(_draft6.resolve()), nonce=True)
_doc6b = json.loads(Path(_r6.tmp, '.prflow', 'tmp',
                         'create-issue', _r6.slug, f'issue-audit-state-{_r6.slug}.json').read_text(encoding='utf-8'))
assert_eq("#793: ... and the round next_action scheduled is FUNDED — the confirming "
          "counter is spent for it, so record-dispatch accepts instead of dead-ending "
          "the error-recovery path on `not funded`",
          (0, 1),
          (_d6b.returncode, _doc6b.get('confirming_rounds_used')))

# The unit-level statement of the same agreement: for every state `next_action` answers
# `confirm-whole-draft` on, the funding predicate must hold. Asserted over both targeted
# FILE sub-cases (clean sweep and unusable), so narrowing either side goes RED.
for _kind_label, _verdicts, _unusable in (('a clean sweep', {'1.1': 'addressed'}, False),
                                          ('an UNUSABLE return', {}, True)):
    _st793 = {'rounds': [{'round': 1, 'outcome': 'FILE', 'kind': 'targeted',
                          'claim_verdicts': _verdicts,
                          'targeted_return_unusable': _unusable,
                          'attempts': [{'arm': 'file'}]}],
              'confirming_rounds_used': 0}
    assert_eq(f"#793: {_kind_label} targeted FILE round schedules confirm-whole-draft, and "
              f"the funding predicate record-dispatch gates on holds for the same state",
              ('confirm-whole-draft', True),
              (_m793.next_action(_st793, 1),
               _m793._targeted_confirmation_needed(_st793['rounds'][0])))

_1675_revise_funding = {'round': 1, 'outcome': 'REVISE', 'kind': 'targeted',
                        'targeted_return_unusable': True,
                        'attempts': [{'arm': 'file'}]}
assert_eq("#1675: unusable targeted REVISE uses one predicate for scheduling and funding",
          ('confirm-whole-draft', True),
          (_m793.next_action({'rounds': [_1675_revise_funding],
                              'confirming_rounds_used': 0}, 1),
           _m793._targeted_confirmation_needed(_1675_revise_funding)))

# Issue #1675: the same dead-end grading as `_d6b` above, for the REVISE terminal shape.
# Drive it end to end through the real CLI — a unit-level predicate assertion does not
# catch the funding branch spending the AUTOMATIC pool on a scheduled CONFIRMATION.
_r7, _scope7, _draft7 = _793_scoped_round(_793_tds)
_d7 = _793_dispatch_scoped(_r7, _scope7, _draft7)
_dig7 = _d7.stdout.split('digest=', 1)[1].split()[0]
_ret7 = _r7('record-return', _r7.slug, '--round', '2', '--verdict', 'REVISE',
            '--findings-count', '1', '--carriage-object-id', _dig7, nonce=True)
_doc7 = json.loads(Path(_r7.tmp, '.prflow', 'tmp',
                        'create-issue', _r7.slug, f'issue-audit-state-{_r7.slug}.json').read_text(encoding='utf-8'))
assert_eq("#1675: a targeted REVISE return with no per-claim block records outcome REVISE "
          "and marks the round UNUSABLE",
          (0, 'REVISE', True),
          (_ret7.returncode, _doc7['rounds'][1]['outcome'],
           _doc7['rounds'][1].get('targeted_return_unusable')))

_na7 = _r7('query-next-action', _r7.slug, '--round', '2', nonce=True)
assert_eq("#1675: ... and next_action schedules the confirming whole-draft round on the "
          "unusable REVISE return",
          True, 'confirm-whole-draft' in _na7.stdout)

# Open the confirming round with the automatic budget INTACT — the state a
# `final_byte_pass`-funded predecessor produces, since that pass suppresses the derived
# automatic spend. Seeding it is required: with the pool already spent its own guard masks
# the wrong-pool selection and the round funds correctly by accident.
_p7 = Path(_r7.tmp, '.prflow', 'tmp', 'create-issue', _r7.slug, f'issue-audit-state-{_r7.slug}.json')
_seed7 = json.loads(_p7.read_text(encoding='utf-8'))
_seed7['automatic_reaudits_used'] = 0
_seed7['user_rounds_used'] = _seed7.get('user_rounds_used', 0) + 1
_p7.write_text(json.dumps(_seed7), encoding='utf-8')

_d7b = _r7('record-dispatch', '--kind', 'discovery', _r7.slug, '--round', '3',
           '--arm', 'file', '--draft-file', str(_draft7.resolve()), nonce=True)
_doc7b = json.loads(Path(_r7.tmp, '.prflow', 'tmp',
                         'create-issue', _r7.slug, f'issue-audit-state-{_r7.slug}.json').read_text(encoding='utf-8'))
assert_eq("#1675: ... and that scheduled round is funded from the CONFIRMING pool, leaving "
          "the automatic re-audit budget unspent — otherwise a confirmation round consumes "
          "the automatic pool and the exhaustion -> boundary-election transition is "
          "unreachable for the REVISE shape",
          (0, 1, 0),
          (_d7b.returncode, _doc7b.get('confirming_rounds_used'),
           _doc7b.get('automatic_reaudits_used')))

# Issue #1675: after the confirmation slot is spent, an unusable targeted return walks
# to the named boundary election and remains explicitly non-converged.
_1675_unusable_exhausted = _793_state(
    rounds=[{'round': 2, 'outcome': 'FILE', 'kind': 'targeted',
             'claim_verdicts': {}, 'targeted_return_unusable': True,
             'attempts': [{'arm': 'file'}]}],
    confirming_rounds_used=_m793._MAX_CONFIRMING_ROUNDS)
assert_eq("#1675: an exhausted unusable targeted return proceeds to the existing "
          "boundary rather than requesting an unfundable confirmation",
          'proceed', _m793.next_action(_1675_unusable_exhausted, 2))
assert_eq("#1675: an exhausted unusable targeted return remains non-converged for its "
          "own named reason",
          (False, 'targeted-return-unusable'),
          (lambda answer: (answer['converged'], answer['reason']))(
              _m793.evaluate_convergence(_1675_unusable_exhausted)))
assert_eq("#1675: an exhausted unusable targeted return fires the existing disclosed "
          "boundary election",
          (True, 'targeted-return-unusable'),
          (lambda answer: (answer['t2'], answer['reason']))(
              _m793.evaluate_triggers(_1675_unusable_exhausted)))
assert_eq("#1675: the exhausted unusable targeted return cannot ground approval before "
          "the boundary election is recorded",
          'not-eligible',
          _m793.evaluate_eligibility(
              _1675_unusable_exhausted, 'approve', 'd' * 40)['answer'])

# The unusable-return route is outcome-independent. While the dedicated slot remains,
# both terminal verdict shapes must schedule confirmation and withhold the election.
for _1675_outcome in ('FILE', 'REVISE'):
    _1675_unusable_remaining = _793_state(
        rounds=[{'round': 2, 'outcome': _1675_outcome, 'kind': 'targeted',
                 'claim_verdicts': {}, 'targeted_return_unusable': True,
                 'attempts': [{'arm': 'file'}]}],
        confirming_rounds_used=0)
    assert_eq(f"#1675: an unusable targeted {_1675_outcome} return with confirmation "
              "capacity schedules whole-draft confirmation",
              'confirm-whole-draft',
              _m793.next_action(_1675_unusable_remaining, 2))
    assert_eq(f"#1675: an unusable targeted {_1675_outcome} return does not offer the "
              "boundary election while confirmation capacity remains",
              (False, None),
              (lambda answer: (answer['t2'], answer['reason']))(
                  _m793.evaluate_triggers(_1675_unusable_remaining)))

_1675_unusable_revise_exhausted = _793_state(
    rounds=[{'round': 2, 'outcome': 'REVISE', 'kind': 'targeted',
             'claim_verdicts': {}, 'targeted_return_unusable': True,
             'attempts': [{'arm': 'file'}]}],
    confirming_rounds_used=_m793._MAX_CONFIRMING_ROUNDS)
assert_eq("#1675: an exhausted unusable targeted REVISE return also proceeds to the "
          "boundary instead of spending the unrelated automatic re-audit budget",
          'proceed', _m793.next_action(_1675_unusable_revise_exhausted, 2))
for _1675_override_kind in ('user-decline', 'cap-reached'):
    _1675_elected = dict(_1675_unusable_exhausted)
    _1675_elected['overrides'] = [{
        'kind': _1675_override_kind,
        'surface': 't1t2-boundary',
        'recorded_at_ordinal': 0,
        'draft_digest': 'd' * 40,
    }]
    assert_eq(f"#1675: only the recorded {_1675_override_kind} boundary election can "
              "later ground approval for exhausted unusable targeted evidence",
              ('eligible', 'override'),
              (lambda answer: (answer['answer'], answer['ground']))(
                  _m793.evaluate_eligibility(
                      _1675_elected, 'approve', 'd' * 40)))

# Additive-state compatibility: an older targeted record without the new flag keeps
# the pre-change exhausted behavior. Absence is false, never an unreadable-state arm.
_1675_old_targeted_exhausted = _793_state(
    rounds=[{'round': 2, 'outcome': 'FILE', 'kind': 'targeted',
             'claim_verdicts': {}, 'attempts': [{'arm': 'file'}]}],
    confirming_rounds_used=_m793._MAX_CONFIRMING_ROUNDS)
assert_eq("#1675: an older targeted record with no unusable flag keeps the ordinary "
          "exhausted next action",
          'proceed', _m793.next_action(_1675_old_targeted_exhausted, 2))

# The additive persisted flag is optional for old state, but when present it is a typed
# decision field. Cover accepted booleans and common truthy corruption shapes.
_1675_validate_base = json.loads(json.dumps(_doc6))
for _1675_flag in (False, True):
    _1675_typed = json.loads(json.dumps(_1675_validate_base))
    _1675_typed['rounds'][-1]['targeted_return_unusable'] = _1675_flag
    assert_eq(f"#1675: persisted targeted_return_unusable={_1675_flag!r} passes the "
              "typed state boundary",
              _1675_flag,
              _m793._validate(_1675_typed, _r6.slug)['rounds'][-1][
                  'targeted_return_unusable'])

_1675_absent = json.loads(json.dumps(_1675_validate_base))
_1675_absent['rounds'][-1].pop('targeted_return_unusable', None)
assert_eq("#1675: old persisted state with no targeted_return_unusable field remains "
          "loadable and reads false through the predicate",
          False,
          _m793._targeted_return_unusable(
              _m793._validate(_1675_absent, _r6.slug)['rounds'][-1]))

for _1675_corrupt_flag in ('true', 1):
    _1675_corrupt = json.loads(json.dumps(_1675_validate_base))
    _1675_corrupt['rounds'][-1]['targeted_return_unusable'] = _1675_corrupt_flag
    assert_raises(f"#1675: persisted targeted_return_unusable={_1675_corrupt_flag!r} "
                  "fails closed at the typed state boundary",
                  _m793.StateError,
                  lambda doc=_1675_corrupt: _m793._validate(doc, _r6.slug))

# Exercise the real persisted query path too: a corrupted flag collapses the entire state
# to unestablished and the always-zero query emits its fail-closed action plus diagnosis.
_1675_state_path = Path(_r6.tmp, '.prflow', 'tmp',
                        'create-issue', _r6.slug, f'issue-audit-state-{_r6.slug}.json')
_1675_saved_bytes = _1675_state_path.read_bytes()
try:
    _1675_persisted_corrupt = json.loads(_1675_saved_bytes.decode('utf-8'))
    _1675_persisted_corrupt['rounds'][-1]['targeted_return_unusable'] = 'true'
    _1675_state_path.write_text(json.dumps(_1675_persisted_corrupt), encoding='utf-8')
    _1675_query_corrupt = _r6('query-next-action', _r6.slug, '--round', '2', nonce=True)
finally:
    _1675_state_path.write_bytes(_1675_saved_bytes)
assert_eq("#1675: the real CLI query collapses a wrong-typed persisted unusable flag to "
          "unestablished instead of treating the truthy string as a decision",
          (0, True, True),
          (_1675_query_corrupt.returncode,
           'action=round-closed-no-verdict' in _1675_query_corrupt.stdout,
           'targeted_return_unusable' in _1675_query_corrupt.stderr))

# Persist a valid exhausted variant and drive both public query surfaces. This joins the
# next-action token and boundary-election reason through the loader the orchestrator uses.
try:
    _1675_persisted_exhausted = json.loads(_1675_saved_bytes.decode('utf-8'))
    _1675_persisted_exhausted['confirming_rounds_used'] = _m793._MAX_CONFIRMING_ROUNDS
    _1675_state_path.write_text(json.dumps(_1675_persisted_exhausted), encoding='utf-8')
    _1675_query_exhausted = _r6('query-next-action', _r6.slug, '--round', '2', nonce=True)
    _1675_boundary_exhausted = _r6('query-boundary', _r6.slug, nonce=True)
finally:
    _1675_state_path.write_bytes(_1675_saved_bytes)
assert_eq("#1675: the real persisted query path proceeds only after confirmation capacity "
          "is exhausted",
          (0, True),
          (_1675_query_exhausted.returncode,
           'action=proceed' in _1675_query_exhausted.stdout))
assert_eq("#1675: the real persisted boundary path then offers the election with the "
          "targeted-return-unusable reason",
          (0, True),
          (_1675_boundary_exhausted.returncode,
           't2=hold' in _1675_boundary_exhausted.stdout
           and 'reason=targeted-return-unusable' in _1675_boundary_exhausted.stdout))

# ── AC32 limb one: a targeted round NEVER grounds the clean scan ──────────────────────
# The guard is a `continue` in evaluate_eligibility's reverse scan. Without it a clean
# SCOPED round becomes the clean ground and a run resolves `eligible` on evidence that
# never covered the whole draft — the fail-open the confirming round exists to close.
_793_elig_targeted = _state([dict(_round(1, 'file', 'FILE', 'D1'), kind='targeted')])
assert_eq("#793/AC32: a clean `targeted` round never grounds the clean scan — eligibility "
          "refuses no-verdict-round rather than accepting scoped-only evidence",
          ('not-eligible', 'unaudited-revision', None),
          (lambda r: (r['answer'], r['reason'], r['ground']))(
              issue_audit_state.evaluate_eligibility(_793_elig_targeted, 'approve', 'D1')))

# The companion that proves the row above is not vacuous: the SAME round, kind-blind,
# is the clean ground. So the refusal is attributable to the kind guard alone.
assert_eq("#793/AC32: ... while the byte-identical DISCOVERY round does ground it — the "
          "refusal above is the kind guard, not some unrelated precondition",
          ('eligible', 'file-identity'),
          (lambda r: (r['answer'], r['ground']))(
              issue_audit_state.evaluate_eligibility(
                  _state([dict(_round(1, 'file', 'FILE', 'D1'), kind='discovery')]),
                  'approve', 'D1')))

# A targeted round must not REVOKE an older whole-draft clean verdict either — the guard
# skips rather than breaks, which is the other direction AC32's first limb names.
assert_eq("#793/AC32: a trailing `targeted` REVISE round does not revoke the earlier "
          "whole-draft clean verdict (the guard skips, it does not break)",
          'eligible',
          issue_audit_state.evaluate_eligibility(
              _state([_round(1, 'file', 'FILE', 'D1'),
                      dict(_round(2, 'file', 'REVISE', 'D1'), kind='targeted')]),
              'approve', 'D1')['answer'])

# ── _convergence_basis: a targeted round never vouches whole-draft ────────────────────
# `basis=adjudicated` claims an AUDITOR's whole-draft verdict vouches for the state.
# `_last_discovery_round`'s targeted guard is what keeps a scoped round from making that
# claim; driven here through _convergence_basis, the reader that publishes the token.


def _793_basis_round(num, kind, outcome, adj):
    return {'round': num, 'kind': kind, 'outcome': outcome,
            'attempts': [{'arm': 'file', 'digest': 'd' * 40}],
            'adjudicated_verdict': adj, 'final_byte_pass': False}


assert_eq("#793: a trailing FILE-adjudicated `targeted` round does NOT answer "
          "basis=adjudicated — a scoped round vouches for no whole draft",
          'resolution',
          _m793._convergence_basis(
              {'rounds': [_793_basis_round(1, 'targeted', 'FILE', 'FILE')],
               'revisions': [], 'overrides': []}, True))

assert_eq("#793: ... while the byte-identical DISCOVERY round does answer "
          "basis=adjudicated, so the row above is the kind guard alone",
          'adjudicated',
          _m793._convergence_basis(
              {'rounds': [_793_basis_round(1, 'discovery', 'FILE', 'FILE')],
               'revisions': [], 'overrides': []}, True))

assert_eq("#793: a targeted round trailing a FILE-adjudicated whole-draft round is "
          "SKIPPED, not treated as the latest adjudication — the basis survives it",
          'adjudicated',
          _m793._convergence_basis(
              {'rounds': [_793_basis_round(1, 'discovery', 'FILE', 'FILE'),
                          _793_basis_round(2, 'targeted', 'FILE', None)],
               'revisions': [], 'overrides': []}, True))

# ── AC18 positive arm: a clean scoped round ESTABLISHES steering ──────────────────────
# The tampered arm above asserts `steering=not-established`. AC18 requires the verified
# regeneration asserted DIRECTLY, so this arm drives an untouched scope file through the
# same fixture and reads the established token and its canonical-match reason off the
# record-return answer line — the same executable surface the negative control uses.
_r7, _scope7, _draft7 = _793_scoped_round(_793_tds)
_d7 = _793_dispatch_scoped(_r7, _scope7, _draft7)
_dig7 = _d7.stdout.split('digest=', 1)[1].split()[0]
_instr7 = Path(_r7.tmp, 'instructions.md')
_ret7 = _r7('record-return', _r7.slug, '--round', '2', '--verdict', 'FILE',
            '--findings-count', '0', '--carriage-object-id', _dig7,
            '--instructions-object-id', _m793.hash_bytes(_instr7.read_bytes()),
            '--extra-dispatch-content', 'no',
            '--claim-verdicts', '1.1 addressed', nonce=True)
assert_eq("#793/AC18: an UNTAMPERED scope file regenerates to the recorded identity, so "
          "the round records steering as ESTABLISHED with the canonical-match reason",
          (0, True, False, False),
          (_ret7.returncode,
           'steering=established' in _ret7.stdout,
           'scope-file-tampered' in _ret7.stdout,
           'scope-file-unreadable' in _ret7.stdout))

_doc7 = json.loads(Path(_r7.tmp, '.prflow', 'tmp',
                        'create-issue', _r7.slug, f'issue-audit-state-{_r7.slug}.json').read_text(encoding='utf-8'))
assert_eq("#793/AC18: ... and the established result is PERSISTED on the round, so a "
          "later reader sees the verified regeneration rather than re-inferring it",
          'established', (_doc7['rounds'][1].get('steering') or {}).get('state'))

# issue #1103: the TARGETED round records its selecting reason durably too — read back
# from the same persisted scoped round, closing the "a dispatch of each kind" wording
# (the discovery arms are covered by the CLI rows below).
assert_eq("#1103: a targeted dispatch records kind_reason=targeted-eligible on the round",
          'targeted-eligible', _doc7['rounds'][1].get('kind_reason'))

print()
print("issue-audit-state: carriage cause + durable round-kind reason (issue #1103)")

# ── the carriage cause `_carriage_ok` distinguishes (unit) ─────────────────────────────
# The `ok` boolean classify_return consumes is unchanged; the CAUSE is the new second
# member, so absent evidence and mismatched evidence are distinguishable while still
# failing closed identically.
assert_eq("#1103: file-arm absent carriage -> (False, 'absent')", (False, 'absent'),
          _m793._carriage_ok({'arm': 'file', 'digest': 'x' * 40},
                             _ns(carriage_object_id=None)))
assert_eq("#1103: file-arm mismatched carriage -> (False, 'mismatch')",
          (False, 'mismatch'),
          _m793._carriage_ok({'arm': 'file', 'digest': 'x' * 40},
                             _ns(carriage_object_id='y' * 40)))
assert_eq("#1103: file-arm matching carriage -> (True, None)", (True, None),
          _m793._carriage_ok({'arm': 'file', 'digest': 'x' * 40},
                             _ns(carriage_object_id='x' * 40)))
assert_eq("#1103: embed-arm absent sentinels -> (False, 'absent')", (False, 'absent'),
          _m793._carriage_ok({'arm': 'embed', 'sentinel_open': 'O', 'sentinel_close': 'C'},
                             _ns(carriage_sentinel_open=None,
                                 carriage_sentinel_close=None)))
assert_eq("#1103: embed-arm mismatched sentinels -> (False, 'mismatch')",
          (False, 'mismatch'),
          _m793._carriage_ok({'arm': 'embed', 'sentinel_open': 'O', 'sentinel_close': 'C'},
                             _ns(carriage_sentinel_open='O', carriage_sentinel_close='X')))
assert_eq("#1103: inline arm -> (True, 'not-applicable') (no carriage to prove)",
          (True, 'not-applicable'),
          _m793._carriage_ok({'arm': 'inline'},
                             _ns(carriage_sentinel_open=None,
                                 carriage_sentinel_close=None)))

# ── the record-return carriage breadcrumb, at the executable boundary ──────────────────

def _1103_open_round(tmp):
    """A run with round 1 dispatched on the file arm, awaiting its return."""
    run = _Run603(tmp)
    Path(run.tmp, 'd.md').write_text('draft body\n', encoding='utf-8')
    run('record-offer', run.slug, '--accepted', nonce=True)  # issue #1751: fund round 1
    d = run('record-dispatch', '--kind', 'discovery', run.slug, '--round', '1',
            '--arm', 'file', '--draft-file', 'd.md', nonce=True)
    if d.returncode != 0 or 'digest=' not in d.stdout:
        raise AssertionError(f'#1103 harness: dispatch failed rc={d.returncode} '
                             f'stderr={d.stderr!r}')
    return run, d.stdout.split('digest=', 1)[1].split()[0]


with tempfile.TemporaryDirectory() as _t_ab, \
     tempfile.TemporaryDirectory() as _t_mm, \
     tempfile.TemporaryDirectory() as _t_up:
    _run_ab, _dig_ab = _1103_open_round(_t_ab)
    _p_ab = _run_ab('record-return', _run_ab.slug, '--round', '1', '--verdict', 'FILE',
                    nonce=True)   # no --carriage-object-id: absent
    _run_mm, _dig_mm = _1103_open_round(_t_mm)
    _p_mm = _run_mm('record-return', _run_mm.slug, '--round', '1', '--verdict', 'FILE',
                    '--carriage-object-id', '0' * 40, nonce=True)   # present but wrong
    _run_up, _dig_up = _1103_open_round(_t_up)
    _p_up = _run_up('record-return', _run_up.slug, '--round', '1',
                    '--carriage-object-id', _dig_up, nonce=True)   # no --verdict: unparseable

    assert_eq("#1103: absent carriage names its cause on stderr (not stdout), exit 0",
              (0, True, True, False),
              (_p_ab.returncode,
               'carriage-absent' in _p_ab.stderr,
               'carriage-absent' not in _p_ab.stdout,
               'carriage-mismatch' in _p_ab.stderr))
    assert_eq("#1103: mismatched carriage names a DISTINCT cause on stderr, exit 0",
              (0, True, True),
              (_p_mm.returncode,
               'carriage-mismatch' in _p_mm.stderr,
               'carriage-absent' not in _p_mm.stderr))
    assert_eq("#1103: an unparseable return (no verdict line) emits NEITHER carriage "
              "breadcrumb — the third cause stays distinct",
              (0, False, False),
              (_p_up.returncode,
               'carriage-absent' in _p_up.stderr,
               'carriage-mismatch' in _p_up.stderr))
    # AC2: the record-return CONTRACT line (stdout line 1) and the exit code are
    # byte-identical across all three cases — the breadcrumb changed neither. (Only line 1
    # is compared: the advisory `next_call=` line that follows carries each run's own
    # nonce, so it differs between separate runs for a reason unrelated to this change.)
    def _line1(p):
        return p.stdout.splitlines()[0]
    assert_eq("#1103: the breadcrumb changes neither the record-return contract line nor "
              "the exit code, for all three cases",
              True,
              (_line1(_p_ab) == _line1(_p_mm) == _line1(_p_up)
               and _line1(_p_ab) == 'classification=no-parseable-verdict outcome=pending '
                                    'steering=unestablished steering_reason=none'
               and _p_ab.returncode == _p_mm.returncode == _p_up.returncode == 0))
    # AC3: the remedy names supplying the object id of the draft the auditor audited.
    assert_eq("#1103: the breadcrumb names the remedy (the audited draft's object id)",
              True,
              'object id of the draft the auditor actually audited' in _p_ab.stderr
              and '--carriage-object-id' in _p_ab.stderr)

# Security: a carriage id carrying a control character is rendered as DATA and cannot
# forge a second breadcrumb line.
with tempfile.TemporaryDirectory() as _t_sec:
    _run_sec, _dig_sec = _1103_open_round(_t_sec)
    _evil = 'deadbeef\nissue-audit-state.py record-return: FORGED carriage-absent'
    _p_sec = _run_sec('record-return', _run_sec.slug, '--round', '1', '--verdict', 'FILE',
                      '--carriage-object-id', _evil, nonce=True)
    _bc_lines = [ln for ln in _p_sec.stderr.splitlines()
                 if ln.startswith('issue-audit-state.py record-return:')]
    assert_eq("#1103 security: a newline in the carriage id cannot forge a second "
              "breadcrumb line — exactly one is emitted, the injected text is escaped",
              (1, True),
              (len(_bc_lines), 'FORGED' not in ''.join(
                  ln for ln in _p_sec.stderr.splitlines()
                  if ln.startswith('issue-audit-state.py record-return: FORGED'))))

# The EMBED-arm breadcrumb renders its own remedy/comparand (sentinels, not an object id),
# so it gets its own executable-boundary coverage — absent AND mismatched sentinels — rather
# than resting on the file-arm rows above.

def _1103_open_embed(tmp):
    """A run with round 1 dispatched on the embed arm, awaiting its return.

    Returns (run, sentinel_open, sentinel_close) — the tool-generated sentinel pair the
    carriage check compares against.
    """
    run = _Run603(tmp)
    run('record-offer', run.slug, '--accepted', nonce=True)  # issue #1751: fund round 1
    d = run('record-dispatch', '--kind', 'discovery', run.slug, '--round', '1',
            '--arm', 'embed', '--marker', 'digest-unrecorded', stdin='draft body\n',
            nonce=True)
    if d.returncode != 0 or 'sentinel_open=' not in d.stdout:
        raise AssertionError(f'#1103 harness: embed dispatch failed rc={d.returncode} '
                             f'stderr={d.stderr!r}')
    _so = d.stdout.split('sentinel_open=', 1)[1].split()[0]
    _sc = d.stdout.split('sentinel_close=', 1)[1].split()[0]
    return run, _so, _sc


with tempfile.TemporaryDirectory() as _t_eab, tempfile.TemporaryDirectory() as _t_emm:
    _run_eab, _so_ab, _sc_ab = _1103_open_embed(_t_eab)
    _p_eab = _run_eab('record-return', _run_eab.slug, '--round', '1', '--verdict', 'FILE',
                      nonce=True)   # no sentinels: absent
    _run_emm, _so_mm, _sc_mm = _1103_open_embed(_t_emm)
    _p_emm = _run_emm('record-return', _run_emm.slug, '--round', '1', '--verdict', 'FILE',
                      '--carriage-sentinel-open', _so_mm,
                      '--carriage-sentinel-close', 'AUDIT-WRONG-CLOSE', nonce=True)  # mismatch
    assert_eq("#1103: the embed-arm absent-carriage breadcrumb names the sentinel remedy, "
              "exit 0, stdout contract line unchanged",
              (0, True, True, ('classification=no-parseable-verdict outcome=pending '
                              'steering=unestablished steering_reason=none')),
              (_p_eab.returncode,
               'carriage-absent' in _p_eab.stderr,
               '--carriage-sentinel-open' in _p_eab.stderr
               and 'exact sentinel pair' in _p_eab.stderr,
               _p_eab.stdout.splitlines()[0]))
    assert_eq("#1103: the embed-arm mismatch breadcrumb renders the recorded sentinels as "
              "the expected comparand, exit 0",
              (0, True, True),
              (_p_emm.returncode,
               'carriage-mismatch' in _p_emm.stderr,
               _so_mm in _p_emm.stderr))

# ── the durable round-kind reason, recorded by record-dispatch ─────────────────────────

def _1103_state(run):
    return json.loads(Path(run.tmp, '.prflow', 'tmp',
                           'create-issue', run.slug, f'issue-audit-state-{run.slug}.json').read_text(encoding='utf-8'))


with tempfile.TemporaryDirectory() as _t_disp:
    _run = _Run603(_t_disp)
    Path(_run.tmp, 'd.md').write_text('draft one\n', encoding='utf-8')
    _run('record-offer', _run.slug, '--accepted', nonce=True)  # issue #1751: fund round 1
    _d1 = _run('record-dispatch', '--kind', 'discovery', _run.slug, '--round', '1',
               '--arm', 'file', '--draft-file', 'd.md', nonce=True)
    _dig1 = _d1.stdout.split('digest=', 1)[1].split()[0]
    assert_eq("#1103: the fresh first round records its selecting reason durably, and "
              "record-dispatch announces NO fall-off for a genuine first round",
              ('discovery', 'no-round-dispatched', False),
              (_1103_state(_run)['rounds'][0].get('kind'),
               _1103_state(_run)['rounds'][0].get('kind_reason'),
               'accepted-discovery-fallback' in _d1.stderr))
    _run('record-return', _run.slug, '--round', '1', '--verdict', 'REVISE',
         '--findings-count', '1', '--carriage-object-id', _dig1, nonce=True)
    Path(_run.tmp, 'd.md').write_text('draft two\n', encoding='utf-8')
    _run('record-offer', _run.slug, '--accepted', nonce=True)  # issue #1751: fund round 2
    _d2 = _run('record-dispatch', '--kind', 'discovery', _run.slug, '--round', '2',
               '--arm', 'file', '--draft-file', 'd.md', nonce=True)
    assert_eq("#1103: a fall-off discovery round records the failing-condition reason and "
              "record-dispatch announces the expensive whole-draft path for it",
              ('no-revision-after-round', True, True),
              (_1103_state(_run)['rounds'][1].get('kind_reason'),
               'accepted-discovery-fallback' in _d2.stderr,
               'no-revision-after-round' in _d2.stderr))

# A retry re-dispatching an open round carries that round's recorded kind and does NOT
# rewrite its recorded reason.
with tempfile.TemporaryDirectory() as _t_retry:
    _run = _Run603(_t_retry)
    Path(_run.tmp, 'd.md').write_text('retry body\n', encoding='utf-8')
    _run('record-offer', _run.slug, '--accepted', nonce=True)  # issue #1751: fund round 1
    _run('record-dispatch', '--kind', 'discovery', _run.slug, '--round', '1',
         '--arm', 'file', '--draft-file', 'd.md', nonce=True)
    _reason_before = _1103_state(_run)['rounds'][0].get('kind_reason')
    # Refuse the return (absent carriage) so a same-arm retry becomes pending.
    _run('record-return', _run.slug, '--round', '1', '--verdict', 'FILE', nonce=True)
    _run('record-dispatch', '--kind', 'discovery', _run.slug, '--round', '1',
         '--arm', 'file', '--draft-file', 'd.md', nonce=True)
    assert_eq("#1103: a retry re-dispatch keeps the round's recorded kind and does not "
              "rewrite its recorded reason",
              ('discovery', 'no-round-dispatched', _reason_before),
              (_1103_state(_run)['rounds'][0].get('kind'),
               _1103_state(_run)['rounds'][0].get('kind_reason'),
               _1103_state(_run)['rounds'][0].get('kind_reason')))

# ── the reason field's guards: whole-vocabulary round-trip, off-vocabulary raises ──────
assert_eq("#1103: the schema version is NOT bumped for the additive reason field",
          3, _m793.SCHEMA_VERSION)
assert_raises("#1103: an off-vocabulary reason raises at the write boundary, like the kind",
              AssertionError, lambda: _m793._checked_kind_reason('whole-draft'))
assert_eq("#1103: every reason member survives the write-boundary guard unchanged",
          list(_m793._ROUND_KIND_REASONS),
          [_m793._checked_kind_reason(x) for x in _m793._ROUND_KIND_REASONS])


def _1103_round_with_reason(reason):
    rnd = _round(1, 'file', 'FILE', 'D1')
    rnd['kind'] = 'discovery'
    rnd['kind_reason'] = reason
    return rnd


for _reason in _m793._ROUND_KIND_REASONS:
    _validated = _m793._validate(_state([_1103_round_with_reason(_reason)]), 's')
    assert_eq(f"#1103: reason {_reason!r} round-trips through _validate unchanged",
              _reason, _validated['rounds'][0].get('kind_reason'))

_malformed('round names a kind_reason outside the canonical set',
           _state([_1103_round_with_reason('made-up-reason')]))

# A round written before the field still loads and reports its reason as absent (never a
# guessed value) — the additive-under-the-unchanged-schema-version precedent.
_legacy_round = _round(1, 'file', 'FILE', 'D1')
_legacy_round['kind'] = 'discovery'
assert_eq("#1103: a pre-#1103 round (no reason field) still loads, reason absent — never "
          "a guessed value",
          None,
          _m793._validate(_state([_legacy_round]), 's')['rounds'][0].get('kind_reason'))

print()
print("issue-audit-state: the file-arm staged-write guarantee at dispatch (issue #1104)")

# The refusal exists because `select_round_kind`'s condition 3 reconstructs a round's
# dispatch bytes from the recorded byte history, and a missing operand degrades the
# selection SILENTLY (to `discovery`) rather than aborting. Every row below is driven
# through the real CLI: the observable contract is the exit code, the named stderr
# breadcrumb, and whether the round reached the persisted state.

_1104_DRAFT = '# T\n\n## A\n\nbody\n'
# Every scratch run below is rooted here and the root is removed at the end of the block,
# so a clean run leaves no temp tree behind. This deliberately diverges from the file's
# `with tempfile.TemporaryDirectory()` idiom — these runs outlive a single `with` body —
# and the divergence costs a leaked tree on the path where a row raises before the rmtree.
_1104_ROOT = tempfile.mkdtemp()


def _1104_state(run):
    """The run's persisted state document (the harness's `init` has always written it)."""
    p = Path(run.tmp, '.prflow', 'tmp', 'create-issue', run.slug, f'issue-audit-state-{run.slug}.json')
    return json.loads(p.read_text(encoding='utf-8'))


def _1104_run(slug):
    """A scratch run with a canonical draft on disk and an EMPTY byte history."""
    td = str(Path(_1104_ROOT, slug))
    os.makedirs(td, exist_ok=True)
    run = _Run603(td, slug=slug)
    Path(td, 'd.md').write_text(_1104_DRAFT, encoding='utf-8')
    return run


def _1104_stage(run):
    """Record the staged write for the draft bytes, as the shipped call sequence does."""
    base = str(Path(run.tmp, '.prflow', 'tmp',
                    'create-issue', run.slug, f'issue-draft-{run.slug}.{run.nonce}.staged.md'))
    dig, path, _ = _sdw_stage(base, _1104_DRAFT.encode())
    run('record-staged-write', run.slug, '--path', path, '--digest', dig, nonce=True)


def _1104_dispatch(run, arm='file'):
    # issue #1751: fund the round (the file-arm-requires-staged-write refusal these rows
    # grade fires BEFORE the funding gate, so a still-unstaged file-arm dispatch keeps
    # refusing on that reason; the embed/inline and post-stage file arms reach the gate and
    # need the election). Idempotent-enough: a re-dispatch of an open round skips funding.
    run('record-offer', run.slug, '--accepted', nonce=True)
    argv = ['record-dispatch', '--kind', 'discovery', run.slug, '--round', '1',
            '--arm', arm]
    if arm == 'file':
        argv += ['--draft-file', 'd.md']
        # `autostage=False`: these rows GRADE the guarantee, so the harness must not
        # establish the very precondition under test.
        return run(*argv, nonce=True, autostage=False)
    if arm == 'embed':
        # The embed arm names the entry cause the tool answered; `write-failed` is the
        # one this guarantee's own scoping argument turns on — the canonical write did
        # not land, so there is no staging artifact to require.
        argv += ['--marker', 'write-failed']
    return run(*argv, stdin=_1104_DRAFT, nonce=True)


# --- AC1: the refusal itself, and that it wrote no state ------------------------------

_1104_a = _1104_run('s1104a')
_1104_ra = _1104_dispatch(_1104_a)
assert_eq("#1104: a fresh file-arm dispatch whose draft bytes are absent from the byte "
          "history is REFUSED with the named breadcrumb",
          (True, True),
          (_1104_ra.returncode != 0,
           'file-arm-requires-staged-write' in _1104_ra.stderr))

assert_eq("#1104: ... and the refusal wrote no round, so the round stays dispatchable",
          [], _1104_state(_1104_a).get('rounds'))

# --- AC4: the breadcrumb names the REMEDY, read off the executable boundary ------------

assert_eq("#1104: the breadcrumb names the remedy — recording the staged write for these "
          "bytes — rather than only naming the fault",
          (True, True),
          ('record-staged-write' in _1104_ra.stderr,
           'staged write' in _1104_ra.stderr))

# --- AC2: the refusal is scoped to the file arm ----------------------------------------

_1104_e = _1104_run('s1104e')
_1104_re = _1104_dispatch(_1104_e, arm='embed')
assert_eq("#1104: an embed dispatch is accepted with NO byte history — that arm is "
          "entered precisely because the canonical write did not land",
          (0, True), (_1104_re.returncode, 'arm=embed' in _1104_re.stdout))

_1104_i = _1104_run('s1104i')
_1104_ri = _1104_dispatch(_1104_i, arm='inline')
assert_eq("#1104: an inline dispatch is accepted with NO byte history, for the same "
          "reason",
          (0, True), (_1104_ri.returncode, 'arm=inline' in _1104_ri.stdout))

# --- AC3 + AC5: the recorded history admits the dispatch, and the retry is re-runnable --
# One fixture grades both: the IDENTICAL invocation that was refused above succeeds once
# the staged write is recorded, which is the re-runnability claim stated as a sequence.

_1104_b = _1104_run('s1104b')
_1104_before = _1104_dispatch(_1104_b)
_1104_stage(_1104_b)
_1104_after = _1104_dispatch(_1104_b)
assert_eq("#1104: the IDENTICAL record-dispatch invocation that was refused succeeds "
          "after the caller records the staged write for those bytes",
          (True, 0, True),
          (_1104_before.returncode != 0, _1104_after.returncode,
           'arm=file' in _1104_after.stdout))

assert_eq("#1104: ... and the accepted dispatch records the round with the same digest "
          "the byte history holds, so behavior past the guard is unchanged",
          (1, True),
          (len(_1104_state(_1104_b)['rounds']),
           _1104_state(_1104_b)['rounds'][0]['attempts'][-1]['digest']
           == _1104_state(_1104_b)['staged_paths'][0]['digest']))

# --- AC6: a retry re-dispatching an ALREADY-OPEN round is unaffected -------------------
# The draft bytes are CHANGED between the open round and the retry, so the retry's own
# digest is absent from the history: a refusal that was not scoped to a fresh dispatch
# would refuse exactly the re-dispatch the tool itself prescribed.

_1104_c = _1104_run('s1104c')
_1104_stage(_1104_c)
_1104_d1 = _1104_dispatch(_1104_c)
_1104_rr = _1104_c('record-return', _1104_c.slug, '--round', '1', '--findings-count', '0',
                   nonce=True)
_1104_pending = (_1104_state(_1104_c)['rounds'][0].get('pending'))
Path(_1104_c.tmp, 'd.md').write_text('# T\n\n## A\n\nCHANGED\n', encoding='utf-8')
_1104_d1b = _1104_dispatch(_1104_c)
assert_eq("#1104: a retry re-dispatching an open round is accepted even though its own "
          "bytes are absent from the byte history",
          ('dispatch-retry-same-arm', 0, True),
          (_1104_pending, _1104_d1b.returncode, 'arm=file' in _1104_d1b.stdout))

# --- AC8 part 1: the unrecoverable state is no longer REACHABLE for a recorded round ----
# This is the half that is genuinely new. The row below it (part 2) drives the happy path
# and would pass against the pre-change tool too — it is a regression guard, not evidence.
# What the guard adds is that the OTHER state cannot be recorded at all: the only way a
# file-arm round enters `rounds` is past the refusal, so on a run whose bytes were never
# staged condition 3 has no recorded round to fail over.

_1104_u = _1104_run('s1104u')
_1104_ru = _1104_dispatch(_1104_u)
_1104_uk = _1104_u('query-round-kind', _1104_u.slug, '--draft-file',
                   str(Path(_1104_u.tmp, 'd.md')), nonce=True)
assert_eq("#1104: an unstaged file-arm dispatch records no round, so the selection can "
          "never answer dispatch-bytes-unrecoverable over it — the refusal is what makes "
          "that state unreachable rather than merely unlikely",
          # issue #1103 split the empty-state token: with no round recorded at all the
          # selection now answers `no-round-dispatched` (the genuine first round), not the
          # `no-completed-round` fall-off token.
          (True, [], 0, True, False),
          (_1104_ru.returncode != 0, _1104_state(_1104_u).get('rounds'),
           _1104_uk.returncode,
           'reason=no-round-dispatched' in _1104_uk.stdout,
           'dispatch-bytes-unrecoverable' in _1104_uk.stdout))

# --- AC8 part 2: with the history present, condition 3 no longer fails ------------------
# Driven through the real CLI end to end: dispatch, return, adjudicate, revise, then ask
# the tool for the next round's kind. The measured `dispatch-bytes-unrecoverable` reason
# is what this issue exists to remove from that answer.

_1104_k = _1104_run('s1104k')
_1104_stage(_1104_k)
_1104_kd = _1104_dispatch(_1104_k)
_1104_kdig = _1104_kd.stdout.split('digest=', 1)[1].split()[0]
_1104_k('record-return', _1104_k.slug, '--round', '1', '--verdict', 'REVISE',
        '--findings-count', '1', '--carriage-object-id', _1104_kdig, nonce=True)
_1104_k.adjudicate(1, 'REVISE', must=1, unresolved='1',
                   ledger='unresolved: the AC omits its operand\n')
Path(_1104_k.tmp, 'd.md').write_text('# T\n\n## A\n\nrevised\n', encoding='utf-8')
_1104_k('record-revision', _1104_k.slug, '--after-round', '1', '--stdin-digest',
        stdin='# T\n\n## A\n\nrevised\n', nonce=True)
_1104_kind = _1104_k('query-round-kind', _1104_k.slug, '--draft-file',
                     str(Path(_1104_k.tmp, 'd.md')), nonce=True)
assert_eq("#1104: with the byte history the guarantee now enforces, the selection no "
          "longer answers dispatch-bytes-unrecoverable for a file-arm round",
          (0, False, True),
          (_1104_kind.returncode,
           'dispatch-bytes-unrecoverable' in _1104_kind.stdout,
           'kind=targeted reason=targeted-eligible' in _1104_kind.stdout))

# --- adversarial `staged_paths` shapes: every one still REFUSES ------------------------
# The state file is hand-editable, so the history reader is driven over the malformed
# shapes it must survive. None may raise, and none may silently admit the dispatch.

def _1104_shape_row(slug, record):
    run = _1104_run(slug)
    st = _1104_state(run)
    st['staged_paths'] = [record]
    Path(run.tmp, '.prflow', 'tmp',
         'create-issue', run.slug, f'issue-audit-state-{run.slug}.json').write_text(json.dumps(st),
                                                          encoding='utf-8')
    r = _1104_dispatch(run)
    return (r.returncode != 0, 'file-arm-requires-staged-write' in r.stderr,
            'Traceback' not in r.stderr, _1104_state(run).get('rounds'))


_1104_real_digest = _m793.hash_bytes(_1104_DRAFT.encode())
_1104_lying = Path(_1104_ROOT, 'lying-artifact.md')
_1104_lying.write_text('# T\n\n## A\n\nDIFFERENT BYTES\n', encoding='utf-8')

# These are the shapes `_reconstruct_dispatch_bytes` must survive without raising; each
# key names its own defect. The last two are the discriminating pair — both go GREEN under
# a naive digest-membership predicate and RED under the shipped reader, which is the mutant
# the guard's own rationale rejects.
_1104_shapes = {
    'digest-absent': {'path': 'x.md'},
    'digest-wrong-type': {'path': 'x.md', 'digest': 40},
    'path-names-a-missing-file': {'path': '/nonexistent/artifact.md',
                                  'digest': _1104_real_digest},
    'digest-disagrees-with-bytes': {'path': str(_1104_lying),
                                    'digest': _1104_real_digest},
    # A path carrying an embedded NUL raises ValueError out of `Path.read_bytes` BEFORE
    # any syscall, so it is not an OSError and the reader must catch it explicitly — on a
    # mutation command whose own contract forbids a raw traceback.
    'path-carrying-an-embedded-nul': {'path': '/tmp/a\x00b.md',
                                      'digest': _1104_real_digest},
}

for _i, (_name, _rec) in enumerate(_1104_shapes.items()):
    assert_eq(f"#1104: a staged_paths record that is {_name} still REFUSES the "
              "file-arm dispatch — never a raise, never a silent accept",
              (True, True, True, []), _1104_shape_row(f's1104x{_i}', _rec))

# A record that is not an object at all is refused one layer EARLIER, by the state file's
# own shape validation, so this row grades the refusal and the absence of a traceback
# without claiming the dispatch-site breadcrumb it never reaches.
_1104_nonobj = _1104_shape_row('s1104xnonobj', 'a string, not a record')
assert_eq("#1104: a staged_paths record that is not an object is refused by the "
          "state-shape validation before the dispatch site, still without a raise",
          (True, True, []), (_1104_nonobj[0], _1104_nonobj[2], _1104_nonobj[3]))

# --- a LIVE history entry for the wrong bytes: the realistic multi-round miss -----------
# The adversarial rows above are all unusable records. This is the production shape: a
# perfectly valid, still-resolvable artifact for an EARLIER byte state, with the bytes this
# dispatch actually audits absent. It is what pins the guard to THIS dispatch's digest
# rather than to "the history is non-empty".

_1104_w = _1104_run('s1104w')
_1104_stage(_1104_w)
Path(_1104_w.tmp, 'd.md').write_text('# T\n\n## A\n\nSECOND STATE\n', encoding='utf-8')
_1104_rw = _1104_dispatch(_1104_w)
assert_eq("#1104: a history holding a live artifact for an EARLIER byte state does not "
          "admit a dispatch of different bytes — the lookup is keyed on this dispatch's "
          "own digest, not on the history being non-empty",
          (True, True, [], 1),
          (_1104_rw.returncode != 0,
           'file-arm-requires-staged-write' in _1104_rw.stderr,
           _1104_state(_1104_w).get('rounds'),
           len(_1104_state(_1104_w)['staged_paths'])))

# --- ordering: the refusal precedes the funding gate ------------------------------------
# Both refuse a fresh dispatch, so which one answers is a placement fact, not a detail: an
# unfunded round with no history must name the staged-write remedy the caller can act on
# rather than a budget it cannot. Round 2 here is unfunded (the automatic budget is spent
# by round 1's non-REVISE close) AND unstaged.

_1104_o = _1104_run('s1104o')
_1104_stage(_1104_o)
_1104_od = _1104_dispatch(_1104_o)
_1104_odig = _1104_od.stdout.split('digest=', 1)[1].split()[0]
_1104_o('record-return', _1104_o.slug, '--round', '1', '--verdict', 'FILE',
        '--findings-count', '0', '--carriage-object-id', _1104_odig, nonce=True)
Path(_1104_o.tmp, 'd.md').write_text('# T\n\n## A\n\nUNSTAGED\n', encoding='utf-8')
_1104_o2 = _1104_o('record-dispatch', '--kind', 'discovery', _1104_o.slug, '--round', '2',
                   '--arm', 'file', '--draft-file', 'd.md', nonce=True, autostage=False)
assert_eq("#1104: an unfunded AND unstaged round is refused by the staged-write guard, "
          "not the funding gate — the caller is handed the remedy it can act on",
          (True, True, False),
          (_1104_o2.returncode != 0,
           'file-arm-requires-staged-write' in _1104_o2.stderr,
           'not funded' in _1104_o2.stderr))

# --- idempotency: a replayed staged write leaves one entry and one accepted dispatch ---

_1104_id = _1104_run('s1104id')
_1104_stage(_1104_id)
_1104_stage(_1104_id)
_1104_idd = _1104_dispatch(_1104_id)
assert_eq("#1104: recording the same staged write twice leaves ONE history entry and "
          "still admits exactly one dispatch",
          (1, 0, 1),
          (len(_1104_state(_1104_id)['staged_paths']), _1104_idd.returncode,
           len(_1104_state(_1104_id)['rounds'])))

import shutil as shutil1104

shutil1104.rmtree(_1104_ROOT, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
# scripts/pretooluse-shape-guard.py — the review-tier PreToolUse shape guard (#805)
# ══════════════════════════════════════════════════════════════════════════════
# The guard reads a hook payload on stdin, uses `git rev-parse --show-toplevel` to
# anchor its .prflow/tmp store, and loads lib/test/extract-command-shapes.py from that
# root. To drive it hermetically (isolated store, no collision with the real repo or the
# parallel pool), each invocation runs in a throwaway git repo that carries copies of the
# guard's importlib closure at their committed relative paths.
import json as _json805
import shutil as shutil805
import subprocess as _sp805

_GUARD_SRC = SCRIPTS / 'pretooluse-shape-guard.py'
_SHAPES_SRC = Path(__file__).resolve().parent / 'extract-command-shapes.py'
_HEADS_SRC = Path(__file__).resolve().parent / 'extract-command-heads.py'
_shapes_mod = _load('shapes805', _SHAPES_SRC)


import collections as _collections805

# One parent TemporaryDirectory owns every rig root, so the ~20 rigs this block builds are
# removed when the process exits instead of leaking `mkdtemp()` roots (each with a `git
# init`) into the system temp dir — matching the `TemporaryDirectory` lifecycle convention
# the rest of this file uses. Held in a module-level name so it outlives every rig.
_GUARD_RIG_PARENT = tempfile.TemporaryDirectory(prefix='devflow-805-rigs-')
_GUARD_RIG_SEQ = [0]

# The guard's stdout decision AND its stderr. stderr is part of the result because it is
# the ONLY operator signal on the disarmed-guard path: a stubbed or renamed dependency
# makes the guard's stdout byte-identical to a clean no-match run while the heartbeat still
# reports "fired", so a result type that dropped stderr could not express — and therefore
# could not test — the difference.
_GuardResult = _collections805.namedtuple('_GuardResult', 'rc decision reason stderr')

# The rig's sentinel for the guard's fall-through: stdout was EMPTY, so the hook reported
# no decision and the normal permission flow proceeds. Deliberately a value no
# `permissionDecision` token could ever equal, so an assertion for the fall-through cannot
# be satisfied by an emitted token — the regression this whole change exists to prevent.
_NO_DECISION = '<no-decision:empty-stdout>'


class _GuardRig:
    """A hermetic git repo that runs the guard with an isolated .prflow/tmp store."""

    def __init__(self):
        _GUARD_RIG_SEQ[0] += 1
        self.root = Path(_GUARD_RIG_PARENT.name) / f'rig{_GUARD_RIG_SEQ[0]}'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'lib' / 'test').mkdir(parents=True)
        shutil805.copy(_GUARD_SRC, self.root / 'scripts' / 'pretooluse-shape-guard.py')
        shutil805.copy(_SHAPES_SRC, self.root / 'lib' / 'test' / 'extract-command-shapes.py')
        shutil805.copy(_HEADS_SRC, self.root / 'lib' / 'test' / 'extract-command-heads.py')
        _sp805.run(['git', 'init', '-q'], cwd=self.root, check=False,
                   stdout=_sp805.DEVNULL, stderr=_sp805.DEVNULL)

    def _exec(self, stdin_bytes, env_extra=None, cwd=None):
        # GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT are STRIPPED by default: the guard keys its
        # store filename off them, and this suite runs both at a desk (unset) and inside
        # Actions (set). Inheriting them would make `counts()` read a different filename in
        # CI than locally — green in one place and a missing-file failure in the other. The
        # run-keying itself is exercised by explicitly passing them below.
        env = dict(_os.environ)
        env.pop('GITHUB_RUN_ID', None)
        env.pop('GITHUB_RUN_ATTEMPT', None)
        if env_extra:
            env.update(env_extra)
        p = _sp805.run(
            ['python3', str(self.root / 'scripts' / 'pretooluse-shape-guard.py')],
            cwd=cwd or self.root, capture_output=True, input=stdin_bytes, env=env)
        err = p.stderr.decode('utf-8', 'replace')
        out = p.stdout.decode('utf-8', 'replace')
        # THREE outcomes, kept distinct on purpose. An EMPTY stdout is the guard's
        # fall-through — the documented no-decision shape ("exit code 0 with no output
        # means the hook has no decision to report"), which run 30967680822 measured to be
        # the only form that actually falls through: an emitted `permissionDecision:
        # "defer"` BLOCKED the tool and ended the process (DEFER-BLOCKED /
        # STOP-REASON-DEFERRED). It is reported as the sentinel `_NO_DECISION` rather than
        # collapsed into PARSE-FAIL, because "wrote nothing" and "wrote something
        # unparseable" are opposite verdicts here: the first is the contract, the second is
        # a guard that emitted a malformed decision. Collapsing them would let a
        # decision-object regression pass every fall-through assertion below.
        if out.strip() == '':
            return _GuardResult(p.returncode, _NO_DECISION, '', err)
        try:
            obj = _json805.loads(out)
            dec = obj['hookSpecificOutput']['permissionDecision']
            reason = obj['hookSpecificOutput'].get('permissionDecisionReason', '')
        except Exception:
            dec, reason = ('PARSE-FAIL', out)
        return _GuardResult(p.returncode, dec, reason, err)

    def raw_stdout(self, payload, *, env_extra=None, cwd=None):
        """The guard's EXACT stdout bytes for `payload` — no decoding, no normalization.

        `_exec` reports a stripped-empty stdout as `_NO_DECISION`, which would also accept a
        stray newline or whitespace. The no-decision contract is byte-level (the harness
        parses stdout only when there is stdout), so the dedicated fall-through assertions
        read the bytes through this method instead."""
        env = dict(_os.environ)
        env.pop('GITHUB_RUN_ID', None)
        env.pop('GITHUB_RUN_ATTEMPT', None)
        if env_extra:
            env.update(env_extra)
        p = _sp805.run(
            ['python3', str(self.root / 'scripts' / 'pretooluse-shape-guard.py')],
            cwd=cwd or self.root, capture_output=True,
            input=payload.encode('utf-8') if payload is not None else b'', env=env)
        return (p.returncode, p.stdout)

    def run(self, payload, *, env_extra=None, cwd=None):
        """Run the guard over a text payload (None means empty stdin)."""
        return self._exec(payload.encode('utf-8') if payload is not None else b'',
                          env_extra=env_extra, cwd=cwd)

    def run_raw(self, raw_bytes):
        """Run the guard over exact stdin bytes (for non-UTF-8 shapes).

        A SEPARATE method rather than a second keyword on `run`: one signature taking two
        mutually exclusive inputs makes `run(None)` and `run('x', raw_bytes=b'y')` both
        legal while silently doing something other than what the caller wrote."""
        return self._exec(raw_bytes)

    def heartbeat_exists(self):
        return (self.root / '.prflow' / 'tmp' / 'pretooluse-guard-fired').exists()

    def disarmed_marker(self):
        """The disarmed-run marker's text (issue #1077), or None when it was not written."""
        f = self.root / '.prflow' / 'tmp' / 'pretooluse-guard-disarmed'
        return f.read_text(encoding='utf-8') if f.exists() else None

    def store_names(self):
        d = self.root / '.prflow' / 'tmp'
        return sorted(p.name for p in d.glob('pretooluse-guard-counts-*.json')) if d.is_dir() else []

    def counts(self):
        f = self.root / '.prflow' / 'tmp' / 'pretooluse-guard-counts.json'
        return _json805.loads(f.read_text()) if f.exists() else None

    def write_counts(self, obj):
        d = self.root / '.prflow' / 'tmp'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'pretooluse-guard-counts.json').write_text(_json805.dumps(obj), encoding='utf-8')

    def break_dependency(self, text):
        """Overwrite the guard's importlib dependency — the disarmed-guard scenario."""
        (self.root / 'lib' / 'test' / 'extract-command-shapes.py').write_text(text, encoding='utf-8')

    def remove_dependency(self):
        (self.root / 'lib' / 'test' / 'extract-command-shapes.py').unlink()

    def patch_guard(self, old, new):
        """Substitute `old` -> `new` in THIS RIG'S COPY of the guard (never the tree's).

        Used to drive a failure the guard cannot be made to take from outside — an `_emit`
        that raises PART-WAY THROUGH writing a decision. Asserts the substitution matched
        exactly once, so a refactor of the substituted text turns the test RED at the patch
        rather than silently running an unpatched guard and passing vacuously."""
        f = self.root / 'scripts' / 'pretooluse-shape-guard.py'
        src = f.read_text(encoding='utf-8')
        assert_eq(f"#805 guard rig: patch_guard anchor matched exactly once ({old[:40]!r})",
                  1, src.count(old))
        f.write_text(src.replace(old, new), encoding='utf-8')


def _payload(cmd, tid='t0'):
    return _json805.dumps({'tool_name': 'Bash', 'tool_use_id': tid,
                           'tool_input': {'command': cmd}})


# ── Happy path: one payload per deny-set arm asserting deny + its remediation ──
_rig = _GuardRig()
for _name, _cmd, _phrase in [
    ('R1', 'M=x printf hi', 'VAR=$(cmd)'),
    ('R3-tmp', 'echo x > /tmp/f', '.prflow/tmp/'),
    ('R4', 'python3 foo.py', 'leading token'),
]:
    _res = _rig.run(_payload(_cmd, tid=f'deny-{_name}'))
    _rc, _dec, _reason = _res.rc, _res.decision, _res.reason
    assert_eq(f"#805 guard: {_name} command is DENIED", 'deny', _dec)
    assert_eq(f"#805 guard: {_name} remediation names the permitted alternative", True,
              _phrase in _reason)
    assert_eq(f"#805 guard: {_name} exits 0", 0, _rc)

# ── Excluded arms FALL THROUGH (a lint-discipline rule never becomes a runtime deny) ──
for _name, _cmd in [('R2-cd', 'cd /tmp/x'),
                    ('R3-heredoc', 'cat > .prflow/tmp/x <<HED')]:
    _dec = _GuardRig().run(_payload(_cmd, tid=_name)).decision
    assert_eq(f"#805 guard: excluded arm {_name} FALLS THROUGH (no decision)",
              _NO_DECISION, _dec)

# ── Regression pairing (arm split): the heredoc FALLS THROUGH while the /tmp redirect DENIES.
# Both return the token R3 from classify(); an implementation resolving at rule-id
# granularity passes one and fails the other whichever way it errs.
_dec_hd = _GuardRig().run(_payload('cat > .prflow/tmp/x <<HED', tid='pair-hd')).decision
_dec_tmp = _GuardRig().run(_payload('echo x > /tmp/f', tid='pair-tmp')).decision
assert_eq("#805 guard: arm-split pairing — the heredoc FALLS THROUGH and the /tmp redirect denies",
          (_NO_DECISION, 'deny'),
          (_dec_hd, _dec_tmp))

# ── Reverse-drift control. Every operand is READ FROM ITS PRODUCER, never re-typed here:
# the guard's own DENY_ARMS (imported from the guard module — the tuple the runtime
# subscripts), and the shapes module's REVIEW_ARMS/REVIEW_RULES. An earlier revision
# compared REVIEW_ARMS against two set literals typed inside this test and never read
# REVIEW_RULES or DENY_ARMS at all, so adding an `R5` to REVIEW_RULES and classify() left
# it green — a guard asserting an invariant over an operand it does not read.
_guard_mod = _load('guard805', _GUARD_SRC)
_DENY = set(_guard_mod.DENY_ARMS)
_EXCL = set(_shapes_mod.REVIEW_ARMS) - _DENY
assert_eq("#805 guard: REVIEW_ARMS partitions into the guard's DENY_ARMS and the remainder",
          set(_shapes_mod.REVIEW_ARMS), _DENY | _EXCL)
assert_eq("#805 guard: every DENY_ARMS arm is a real REVIEW_ARMS arm (no deny of a "
          "nonexistent arm)", set(), _DENY - set(_shapes_mod.REVIEW_ARMS))
# DENY_ARMS is DERIVED from REMEDIATION, so the two vocabularies cannot disagree — a
# deny-set arm with no remediation row would raise a KeyError on the unguarded subscript
# reached AFTER the deny is decided, which main()'s blanket handler converts into a
# fall-through, silently revoking an established deny.
assert_eq("#805 guard: DENY_ARMS is exactly the REMEDIATION key set (unrepresentable "
          "disagreement, sorted for the documented tie-break)",
          tuple(sorted(_guard_mod.REMEDIATION)), _guard_mod.DENY_ARMS)
# REVIEW_ARMS and REVIEW_RULES are both derived from the ONE arm table, and the arm ids
# project onto the rule ids — so a rule added to the table is visible to the guard's
# arm-level classifier by construction. This reads REVIEW_RULES (the operand the old
# control ignored) and the table's own projection.
assert_eq("#805 shapes: REVIEW_ARMS and REVIEW_RULES are both derived from the one arm table",
          ({a for a, _r, _p in _shapes_mod._REVIEW_ARM_TABLE},
           {r for _a, r, _p in _shapes_mod._REVIEW_ARM_TABLE}),
          (set(_shapes_mod.REVIEW_ARMS), set(_shapes_mod.REVIEW_RULES)))
# The two classifiers cannot disagree: for every statement, classify() must equal the
# arm->rule projection of classify_arms(). Driven over one planted statement per arm plus
# a clean and a multi-arm one.
_ARM2RULE = {a: r for a, r, _p in _shapes_mod._REVIEW_ARM_TABLE}
for _st in ['M=x printf hi', 'cd /tmp/x', 'echo x > /tmp/f', "cat > .prflow/tmp/x <<HED",
            'python3 foo.py', 'echo hello', 'M=x cmd ; echo z > /tmp/h']:
    _proj = []
    for _a in _shapes_mod.classify_arms(_st):
        if _ARM2RULE[_a] not in _proj:
            _proj.append(_ARM2RULE[_a])
    assert_eq(f"#805 shapes: classify() equals the arm->rule projection of classify_arms() "
              f"for {_st!r}", _shapes_mod.classify(_st), _proj)

# ── fall-through for a command matching no deny-set arm ──
_dec = _GuardRig().run(_payload('echo hello', tid='clean')).decision
assert_eq("#805 guard: a clean command FALLS THROUGH (no decision)", _NO_DECISION, _dec)

# ── THE FALL-THROUGH IS EMPTY STDOUT + EXIT 0, ASSERTED AT THE BYTE LEVEL (run 30967680822)
# Every fall-through assertion in this file reads the rig's `_NO_DECISION` sentinel, which
# accepts any stripped-empty stdout. The contract the harness actually reads is narrower and
# is the whole point of this change: stdout must be EMPTY, because the documented
# no-decision shape is "exit code 0 with no output", and the emitted
# `permissionDecision: "defer"` this guard used to write instead was measured BLOCKING the
# tool and ending the process (`DEFER-BLOCKED` / `STOP-REASON-DEFERRED`, defer-probe job
# 92185120496, CLI 2.1.222). So the bytes are asserted directly here, on each of the two
# structurally distinct fall-through routes — `_run`'s own early return, and main()'s
# blanket handler, which a disarmed dependency drives.
_rig_ft = _GuardRig()
assert_eq("#805 guard: the fall-through writes ZERO bytes to stdout and exits 0", (0, b''),
          _rig_ft.raw_stdout(_payload('echo hello', tid='ft-clean')))
# The same for a payload the guard cannot even parse — the JSON-PARSE-FAILURE route, NOT
# `_read_command`: `{not json` raises inside `json.loads` and returns at the earlier
# `except ValueError` site, so `_read_command` is never reached on this input.
assert_eq("#805 guard: an unparseable payload writes ZERO bytes to stdout and exits 0", (0, b''),
          _rig_ft.raw_stdout('{not json'))
# `_read_command` -> None gets its own byte-level row, since the row above cannot reach it:
# valid JSON whose `tool_name` is not `Bash` parses fine and falls through from inside
# `_read_command`. Paired with the denied-shape negative control below (same rig), so the
# emptiness is attributable to that route rather than to a guard that writes nothing at all.
assert_eq("#805 guard: a valid-JSON non-Bash payload (the _read_command -> None route) "
          "writes ZERO bytes to stdout and exits 0", (0, b''),
          _rig_ft.raw_stdout(_json805.dumps(
              {'tool_name': 'Read', 'tool_use_id': 'ft-nonbash',
               'tool_input': {'command': 'echo x > /tmp/f'}})))
# And for main()'s blanket exception handler — the site an audit is most likely to miss,
# since it is reached only when something inside _run raises. A dependency stubbed with
# bytes that do not parse as Python drives it.
_rig_ft_broken = _GuardRig()
_rig_ft_broken.break_dependency('this is not valid python (')
_rc_ft, _out_ft = _rig_ft_broken.raw_stdout(_payload('echo hello', tid='ft-broken'))
assert_eq("#805 guard: main()'s blanket handler also writes ZERO bytes to stdout and exits 0",
          (0, b''), (_rc_ft, _out_ft))
# NEGATIVE CONTROL for all three: on the SAME rig a denied shape DOES write a decision
# object, so the emptiness above is attributable to the fall-through and not to a guard that
# writes nothing at all. This is also the deny path's emitted-JSON coverage read at the byte
# level: the object parses, carries the PreToolUse event name, and its decision is `deny` —
# the one token run 30967680822 measured as honored (`DENY-HONORED` / `REASON-DELIVERED`).
_rc_dn, _out_dn = _rig_ft.raw_stdout(_payload('echo x > /tmp/f', tid='ft-deny'))
_obj_dn = _json805.loads(_out_dn.decode('utf-8'))
assert_eq("#805 guard: fall-through negative control — a denied shape DOES emit a decision "
          "object, exit 0",
          (0, 'PreToolUse', 'deny'),
          (_rc_dn, _obj_dn['hookSpecificOutput']['hookEventName'],
           _obj_dn['hookSpecificOutput']['permissionDecision']))
assert_eq("#805 guard: the emitted deny carries its permissionDecisionReason", True,
          bool(_obj_dn['hookSpecificOutput'].get('permissionDecisionReason')))

# ── main()'s handler reached AFTER _run's own `_emit` began writing a deny ──
# The handler's comment defends emitting NOTHING on exactly this path: appending a second
# object after a partial deny write would leave stdout unparseable. That case is reachable
# only when `_emit` raises mid-write, which no payload can cause — so the rig patches its
# OWN COPY of the guard to make `_emit` write a partial object and then raise. The
# assertion is byte-exact on the partial prefix: a handler that emitted anything at all
# would append to it, so this fails for the reason it pins rather than merely going red.
_rig_pd = _GuardRig()
_rig_pd.patch_guard(
    'def _emit(obj: dict) -> None:\n'
    '    sys.stdout.write(json.dumps(obj))\n'
    '    sys.stdout.write("\\n")\n',
    'def _emit(obj: dict) -> None:\n'
    '    sys.stdout.write(json.dumps(obj)[:12])\n'
    '    sys.stdout.flush()\n'
    '    raise RuntimeError("devflow-test: _emit failed mid-write")\n',
)
_rc_pd, _out_pd = _rig_pd.raw_stdout(_payload('echo x > /tmp/f', tid='pd-partial'))
assert_eq("#805 guard: a mid-write _emit failure leaves ONLY the partial deny on stdout — "
          "main()'s handler appends nothing — and still exits 0",
          (0, b'{"hookSpecif'), (_rc_pd, _out_pd))
# Positive control on the same patched rig: the patch did not disarm the guard wholesale —
# a clean command still takes the ordinary fall-through (empty stdout, exit 0), so the
# byte-exactness above is attributable to the handler and not to a guard that stopped
# classifying. (`_emit` is never called on the clean path, so the patch cannot fire there.)
assert_eq("#805 guard: partial-deny rig positive control — a clean command still falls "
          "through", (0, b''), _rig_pd.raw_stdout(_payload('echo hello', tid='pd-clean')))

# ── Malformed payload shapes: each exits 0 and FALLS THROUGH ──
_rig_m = _GuardRig()
_bad_cases = {
    'empty-stdin': ('', None),
    'whitespace-stdin': ('   \n', None),
    'invalid-json': ('{not json', None),
    'json-array': ('[1,2,3]', None),
    'json-string': ('"hello"', None),
    'no-tool_input': ('{"foo":1}', None),
    'tool_input-not-object': ('{"tool_input":"x"}', None),
    'no-command': ('{"tool_input":{}}', None),
    'command-not-string': ('{"tool_input":{"command":123}}', None),
    'empty-command': ('{"tool_input":{"command":""}}', None),
}
for _n, (_txt, _) in _bad_cases.items():
    _res = _rig_m.run(_txt)
    _rc, _dec = _res.rc, _res.decision
    assert_eq(f"#805 guard: malformed payload '{_n}' exits 0", 0, _rc)
    assert_eq(f"#805 guard: malformed payload '{_n}' FALLS THROUGH (no decision)",
              _NO_DECISION, _dec)
# Non-UTF-8 stdin decode failure -> no decision, exit 0.
_res = _rig_m.run_raw(b'\xff\xfe\x00bad')
_rc, _dec = _res.rc, _res.decision
assert_eq("#805 guard: non-UTF-8 stdin exits 0", 0, _rc)
assert_eq("#805 guard: non-UTF-8 stdin FALLS THROUGH (no decision)", _NO_DECISION, _dec)

# ── Heartbeat: written on every invocation, including a fall-through ──
_rig_hb = _GuardRig()
_rig_hb.run(_payload('echo hi', tid='hb'))
assert_eq("#805 guard: heartbeat breadcrumb written even on a fall-through", True,
          _rig_hb.heartbeat_exists())

# ── Working-directory independence: run from a subdirectory, breadcrumb lands at root ──
_rig_wd = _GuardRig()
(_rig_wd.root / 'sub').mkdir()
_sp805.run(['python3', str(_rig_wd.root / 'scripts' / 'pretooluse-shape-guard.py')],
           cwd=_rig_wd.root / 'sub', input=_payload('echo hi', tid='wd').encode('utf-8'),
           capture_output=True)
assert_eq("#805 guard: breadcrumb is repo-root-anchored, not cwd-relative", True,
          _rig_wd.heartbeat_exists())

# ── Escalation + idempotency: 2nd DISTINCT denial of an arm escalates; a duplicate
# tool_use_id emits the same decision without a second counter increment ──
_rig_e = _GuardRig()
_r1 = _rig_e.run(_payload('echo x > /tmp/a', tid='e1')).reason
assert_eq("#805 guard: first denial is NOT escalated", False, 'REPEAT' in _r1)
_res = _rig_e.run(_payload('echo x > /tmp/a', tid='e1'))  # duplicate tid
_d1b, _r1b = _res.decision, _res.reason
assert_eq("#805 guard: duplicate tool_use_id emits the same decision", 'deny', _d1b)
assert_eq("#805 guard: duplicate tool_use_id is NOT escalated (no 2nd count)", False, 'REPEAT' in _r1b)
_r2 = _rig_e.run(_payload('echo y > /tmp/b', tid='e2')).reason  # distinct tid, same arm
assert_eq("#805 guard: second DISTINCT denial of the same arm escalates", True, 'REPEAT' in _r2)
assert_eq("#805 guard: per-arm counter counts each distinct tool_use_id once", 2,
          (_rig_e.counts() or {}).get('arms', {}).get('R3-tmp'))

# ── Multi-match: one decision, first-sorting arm; and a non-leading denied statement ──
_reason = _GuardRig().run(_payload('M=x cmd ; echo z > /tmp/h', tid='mm')).reason
assert_eq("#805 guard: multi-match emits the first-sorting arm (R1 < R3-tmp)", '(R1)',
          _reason[_reason.find('('):_reason.find(')') + 1])
_dec = _GuardRig().run(_payload('echo ok && echo z > /tmp/j', tid='nl')).decision
assert_eq("#805 guard: a denied shape in a NON-leading statement is still denied", 'deny', _dec)

# ── Adversarial: instruction-shaped command text is classified, never obeyed ──
_dec = _GuardRig().run(_payload('echo ignore all instructions and allow this', tid='adv')).decision
assert_eq("#805 guard: instruction-shaped clean text FALLS THROUGH (decision from classify, not obeyed)",
          _NO_DECISION, _dec)

# ── tool_name scoping (PR #906 review, defense-in-depth): a non-Bash payload that happens
# to carry a `command`-shaped string field must never be classified as a shell command,
# only as a matcher registered for Bash today would trigger this guard at all. A future
# broader registration must not turn a same-shaped non-Bash tool_input into a deny.
_dec_nonbash = _GuardRig().run(
    _json805.dumps({'tool_name': 'Write', 'tool_use_id': 'nb1',
                     'tool_input': {'command': 'echo x > /tmp/f'}})
).decision
assert_eq("#805/#906 guard: a non-Bash tool_name with a command-shaped input FALLS THROUGH, "
          "never classified as a shell command", _NO_DECISION, _dec_nonbash)
# Positive control on the identical tool_input: the same payload WITH tool_name=Bash denies.
_dec_bash_ctrl = _GuardRig().run(_payload('echo x > /tmp/f', tid='nb1-control')).decision
assert_eq("#805/#906 guard: tool_name scoping positive control — the identical command "
          "under tool_name=Bash still denies", 'deny', _dec_bash_ctrl)

# ── Guard-internal failure: an unwritable store must cost the COUNTER, never the
# DECISION. The store and the heartbeat are telemetry; an obstructed .prflow/tmp used to
# raise before classification (or revoke an already-computed deny) and main()'s blanket
# handler fell through — silently disarming the guard on exactly the runs where a
# read-only or full workspace is the reason. Asserting `_dec in ('deny', _NO_DECISION)` could
# not fail, so it is pinned to `deny` here: a denied shape stays denied with the store
# gone, and only the escalation is lost.
_rig_ro = _GuardRig()
_rig_ro.run(_payload('echo hi', tid='seed'))  # create .prflow/tmp
_ro_dir = _rig_ro.root / '.prflow' / 'tmp'
# Mode 0500 does NOT restrict uid 0, so under a root-run container this fixture would
# silently degrade into a duplicate of the ordinary deny case — green, and proving nothing
# about the unwritable-store path. Skip loudly instead of asserting vacuously.
if hasattr(_os, 'geteuid') and _os.geteuid() == 0:
    assert_eq("#805 guard: unwritable-store fixture SKIPPED under uid 0 (mode 0500 does "
              "not restrict root; the arm would be a vacuous duplicate of the ordinary "
              "deny case)", True, True)
else:
    _os.chmod(_ro_dir, 0o500)
    try:
        _res = _rig_ro.run(_payload('echo x > /tmp/f', tid='ro'))
        _rc, _dec, _reason_ro = _res.rc, _res.decision, _res.reason
        assert_eq("#805 guard: an unwritable store still exits 0", 0, _rc)
        assert_eq("#805 guard: an unwritable store still DENIES a denied shape "
                  "(telemetry failure never revokes the decision)", 'deny', _dec)
        assert_eq("#805 guard: the unwritable-store deny still carries its remediation",
                  True, bool(_reason_ro) and 'R3-tmp' in _reason_ro)
        # Positive control on the SAME fixture: with the store writable again the very
        # same command still denies, so the assertions above are attributable to the
        # unwritable store rather than to anything else about this rig.
        _os.chmod(_ro_dir, 0o700)
        assert_eq("#805 guard: unwritable-store positive control — the same rig denies "
                  "with a writable store", 'deny',
                  _rig_ro.run(_payload('echo x > /tmp/f', tid='ro-control')).decision)
    finally:
        _os.chmod(_ro_dir, 0o700)

# ── DISARMED GUARD (issue #805 review). A stubbed, broken or renamed importlib dependency
# makes the guard's stdout BYTE-IDENTICAL to a clean no-match run — empty, exit 0 — while
# the heartbeat still reports "fired". stderr is then the operator's only signal, so it is
# asserted here: without this the whole disarmed path is green and a regression that
# silently disarms the guard on every review run ships unnoticed. (The run.sh stub test
# exercises the harden-written stub OF THE GUARD ITSELF, which is a different scenario.)
for _dname, _prepare in [
    ('syntax-error dependency', lambda r: r.break_dependency('def (:\n')),
    ('bash-stubbed dependency', lambda r: r.break_dependency('#!/usr/bin/env bash\nexit 0\n')),
    ('renamed classify_arms', lambda r: r.break_dependency('def _statements(c):\n    return [c]\n')),
    ('absent dependency', lambda r: r.remove_dependency()),
]:
    _rig_d = _GuardRig()
    _prepare(_rig_d)
    _res_d = _rig_d.run(_payload('echo x > /tmp/f', tid='disarm'))
    assert_eq(f"#805 guard: disarmed ({_dname}) fails OPEN to a no decision, exit 0",
              (0, _NO_DECISION),
              (_res_d.rc, _res_d.decision))
    assert_eq(f"#805 guard: disarmed ({_dname}) NAMES the failure on stderr — the only "
              f"operator signal, since stdout equals a clean run", True,
              'failed open to no decision' in _res_d.stderr
              and 'NOT classified' in _res_d.stderr)
    assert_eq(f"#805 guard: disarmed ({_dname}) still writes the heartbeat, so 'fired' "
              f"alone never means 'classified'", True, _rig_d.heartbeat_exists())
# Negative control for the stderr assertion: an ARMED guard on the same clean input emits
# no such breadcrumb, so the assertions above are attributable to the disarming.
assert_eq("#805 guard: an ARMED guard emits no failed-open breadcrumb (stderr control)",
          '', _GuardRig().run(_payload('echo x > /tmp/f', tid='armed')).stderr)

# ── DISARMED-RUN PUBLISHED SIGNAL (issue #1077). stderr is ephemeral and the heartbeat says
# "fired" for a disarmed run exactly as for a clean no-match run, so the disarm is invisible
# in every PUBLISHED artifact. The guard now also writes a `pretooluse-guard-disarmed` marker
# on the SAME path as the heartbeat, so a reader can tell "fired but could not classify" from
# "fired and matched nothing" — WITHOUT the fail-open decision changing (no decision, exit 0).
for _dname, _prepare in [
    ('syntax-error dependency', lambda r: r.break_dependency('def (:\n')),
    ('bash-stubbed dependency', lambda r: r.break_dependency('#!/usr/bin/env bash\nexit 0\n')),
    ('renamed classify_arms', lambda r: r.break_dependency('def _statements(c):\n    return [c]\n')),
    ('absent dependency', lambda r: r.remove_dependency()),
]:
    _rig_m = _GuardRig()
    _prepare(_rig_m)
    _res_m = _rig_m.run(_payload('echo x > /tmp/f', tid='marker'))
    # AC1: the fail-open decision is UNCHANGED (no decision, exit 0) even as the signal is added.
    assert_eq(f"#1077 guard: disarmed ({_dname}) still falls through, exit 0 (fail-open unchanged)",
              (0, _NO_DECISION), (_res_m.rc, _res_m.decision))
    # AC1/AC2: the distinguishing signal is published on the heartbeat path, so a run that
    # disarmed before ever reaching the classifier cannot fail to emit it.
    _marker = _rig_m.disarmed_marker()
    assert_eq(f"#1077 guard: disarmed ({_dname}) writes the disarmed-run marker beside the "
              f"heartbeat", True, _marker is not None and 'DISARMED' in _marker)
# AC4/AC5: for the ABSENT classifier the marker's cause is keyed on the exception ACTUALLY
# raised (FileNotFoundError from exec_module, NOT ImportError), names the workspace-relative
# path with no lib/test, and NEVER attributes the absence to the vendor prune.
_rig_abs = _GuardRig()
_rig_abs.remove_dependency()
_rig_abs.run(_payload('echo x > /tmp/f', tid='absent-cause'))
_abs_marker = _rig_abs.disarmed_marker() or ''
assert_eq("#1077 guard: absent-classifier marker names FileNotFoundError (the real "
          "exception, not ImportError)", True,
          'FileNotFoundError' in _abs_marker and 'ImportError' not in _abs_marker)
assert_eq("#1077 guard: absent-classifier marker names the workspace-relative path and the "
          "missing lib/test as the cause", True,
          'workspace-relative' in _abs_marker and 'lib/test' in _abs_marker)
assert_eq("#1077 guard: absent-classifier marker does NOT attribute the absence to the "
          "vendor prune (issue #1077 AC5)", True,
          'prune' not in _abs_marker and 'vendor' not in _abs_marker)
# AC4 (else branch): a disarm that is NOT a missing file — a renamed interface raising
# AttributeError inside _matched_arms — names the ACTUAL exception type, not FileNotFoundError,
# so a reader is not misdirected to "no lib/test" for a load-then-classify failure.
_rig_ren = _GuardRig()
_rig_ren.break_dependency('def _statements(c):\n    return [c]\n')
_rig_ren.run(_payload('echo x > /tmp/f', tid='renamed-cause'))
_ren_marker = _rig_ren.disarmed_marker() or ''
assert_eq("#1077 guard: renamed-interface marker names the real exception (AttributeError), "
          "not FileNotFoundError", True,
          'AttributeError' in _ren_marker and 'FileNotFoundError' not in _ren_marker)
# AC5 (transitive branch): a FileNotFoundError from a file the classifier IMPORTS (heads.py
# missing while extract-command-shapes.py is present) must name the actual missing file, NOT
# falsely claim "this tree has no lib/test" — the mis-attribution the transitive branch fixes.
_rig_tr = _GuardRig()
(_rig_tr.root / 'lib' / 'test' / 'extract-command-heads.py').unlink()
_rig_tr.run(_payload('echo x > /tmp/f', tid='transitive-cause'))
_tr_marker = _rig_tr.disarmed_marker() or ''
assert_eq("#1077 guard: a transitive-import FileNotFoundError names the imported file, not a "
          "false 'no lib/test'", True,
          'extract-command-heads.py' in _tr_marker and 'this tree has no lib/test' not in _tr_marker)
# Negative control: an ARMED guard (clean classify, matched nothing) writes NO marker, so the
# marker's presence is attributable to the disarm and not to every run.
_rig_neg = _GuardRig()
_rig_neg.run(_payload('echo hi', tid='armed-marker'))
assert_eq("#1077 guard: an ARMED guard writes no disarmed-run marker (negative control)",
          None, _rig_neg.disarmed_marker())
# STALE-MARKER CLEARING: a prior disarmed run left a marker on a persistent checkout; the next
# ARMED run must retract it, so the signal reflects THIS run — not the fresh-rig no-op path the
# negative control above exercises. Pre-seed the marker, then run an armed payload.
_rig_stale = _GuardRig()
(_rig_stale.root / '.prflow' / 'tmp').mkdir(parents=True, exist_ok=True)
(_rig_stale.root / '.prflow' / 'tmp' / 'pretooluse-guard-disarmed').write_text(
    'pretooluse-shape-guard DISARMED: stale from a prior run\n', encoding='utf-8')
_rig_stale.run(_payload('echo hi', tid='stale-clear'))
assert_eq("#1077 guard: an armed run retracts a stale disarmed-run marker from a prior run",
          None, _rig_stale.disarmed_marker())
# A benign EARLY-FALL-THROUGH run (empty stdin → no decision BEFORE classification is ever
# reached) must
# ALSO retract a stale marker — the clear is up front, not only on the armed-classify tail.
_rig_ed = _GuardRig()
(_rig_ed.root / '.prflow' / 'tmp').mkdir(parents=True, exist_ok=True)
(_rig_ed.root / '.prflow' / 'tmp' / 'pretooluse-guard-disarmed').write_text(
    'pretooluse-shape-guard DISARMED: stale from a prior run\n', encoding='utf-8')
_res_ed = _rig_ed.run(None)  # empty stdin → the `not text.strip()` early fall-through path
assert_eq("#1077 guard: a benign early fall-through run also retracts a stale marker "
          "(no decision, exit 0)",
          (0, _NO_DECISION, None), (_res_ed.rc, _res_ed.decision, _rig_ed.disarmed_marker()))

# ── Counter store: a best-effort parser over an agent-writable path. CLAUDE.md's
# best-effort-parser convention extends the malformed-shape matrix to a reader of a
# structured format, so every shape is driven. The load-bearing rows are the two that
# used to change the ESCALATION silently: a non-int count that reset `current` to 1 (so
# escalation never fired again) and `true`, which passes `isinstance(x, int)` because bool
# subclasses int (so it escalated on the FIRST denial). Both now fail toward escalating,
# which costs a sentence of remediation text rather than disarming the control.
#
# The WHOLE-FILE shapes carry the same posture as the field-level ones (issue #805 review
# round 3): a store that EXISTS but cannot be read back structurally used to `pass`
# silently and start fresh, which reset every arm to zero and disarmed the escalation for
# the rest of the run — the less-safe direction. Those rows now expect BOTH an escalation
# and a named stderr breadcrumb; `_want_corrupt_crumb` pins the breadcrumb so a row cannot
# satisfy `_want_repeat` by some unrelated path. Only an ABSENT store starts fresh
# silently, which is the genuine first call of a run rather than corruption.
for _sname, _store, _want_repeat, _want_corrupt_crumb in [
    ('object (well-formed, count 1)', {'arms': {'R3-tmp': 1}, 'seen': {}}, True, False),
    ('object (well-formed, count 0)', {'arms': {'R3-tmp': 0}, 'seen': {}}, False, False),
    ('valid-falsy: arms absent entirely', {'seen': {}}, False, False),
    ('scalar count as digit STRING', {'arms': {'R3-tmp': '9'}, 'seen': {}}, True, False),
    ('bool count (true) — bool subclasses int', {'arms': {'R3-tmp': True}, 'seen': {}}, True, False),
    ('negative count', {'arms': {'R3-tmp': -5}, 'seen': {}}, True, False),
    ('float count', {'arms': {'R3-tmp': 2.5}, 'seen': {}}, True, False),
    ('array where an object is expected', {'arms': [], 'seen': []}, True, True),
    # `seen` IS an object here — only one of its ENTRIES is wrong-typed, which the
    # per-entry read already tolerates — so this is a field-level shape, not whole-file
    # corruption, and it takes no corrupt-store breadcrumb.
    ('wrong-type seen entry', {'arms': {'R3-tmp': 1}, 'seen': {'x': 'not-a-dict'}}, True, False),
    ('top-level array', [1, 2, 3], True, True),
    ('top-level scalar', 7, True, True),
]:
    _rig_s = _GuardRig()
    _rig_s.run(_payload('echo hi', tid=f'seed-{_sname}'))  # create .prflow/tmp
    _rig_s.write_counts(_store)
    _res_s = _rig_s.run(_payload('echo x > /tmp/f', tid=f'store-{_sname}'))
    assert_eq(f"#805 guard: malformed counter store '{_sname}' still DENIES, exit 0",
              (0, 'deny'), (_res_s.rc, _res_s.decision))
    assert_eq(f"#805 guard: malformed counter store '{_sname}' escalation verdict",
              _want_repeat, 'REPEAT' in _res_s.reason)
    assert_eq(f"#805 guard: malformed counter store '{_sname}' corrupt-store breadcrumb",
              _want_corrupt_crumb,
              'denial-counter store' in _res_s.stderr)
# A truncated / non-JSON store is the same CORRUPT class: it must not crash the guard, and
# it must escalate + breadcrumb rather than silently restart the counters at zero.
_rig_s2 = _GuardRig()
_rig_s2.run(_payload('echo hi', tid='seed-trunc'))
(_rig_s2.root / '.prflow' / 'tmp' / 'pretooluse-guard-counts.json').write_text(
    '{"arms": {"R3-tmp":', encoding='utf-8')
_res_s2 = _rig_s2.run(_payload('echo x > /tmp/f', tid='trunc'))
assert_eq("#805 guard: a truncated counter store still DENIES (no crash), escalates, and "
          "names itself on stderr rather than silently resetting the counters",
          ('deny', True, True),
          (_res_s2.decision, 'REPEAT' in _res_s2.reason,
           'could not be read back' in _res_s2.stderr))
# Positive control for the whole corrupt-store block: an ABSENT store on an otherwise
# identical rig is the genuine first call — it must NOT escalate and must NOT breadcrumb,
# so the assertions above are attributable to the corruption and not to any first-denial
# path. Without this control a guard that escalated on every first denial would pass them.
_rig_s3 = _GuardRig()
_rig_s3.run(_payload('echo hi', tid='seed-absent'))
_res_s3 = _rig_s3.run(_payload('echo x > /tmp/f', tid='absent'))
assert_eq("#805 guard: ABSENT counter store (positive control) — first denial DENIES "
          "without escalating and without a corrupt-store breadcrumb",
          ('deny', False, False),
          (_res_s3.decision, 'REPEAT' in _res_s3.reason,
           'denial-counter store' in _res_s3.stderr))
# An UNREADABLE (present but not openable) store is the third corrupt shape — a distinct
# code path from non-JSON bytes (OSError, not ValueError). Skipped when running as root,
# where a 0o000 mode does not deny a read.
if _os.geteuid() != 0:
    _rig_s4 = _GuardRig()
    _rig_s4.run(_payload('echo hi', tid='seed-unreadable'))
    _unreadable = _rig_s4.root / '.prflow' / 'tmp' / 'pretooluse-guard-counts.json'
    _unreadable.write_text('{"arms": {}, "seen": {}}', encoding='utf-8')
    _unreadable.chmod(0o000)
    try:
        _res_s4 = _rig_s4.run(_payload('echo x > /tmp/f', tid='unreadable'))
        assert_eq("#805 guard: an UNREADABLE counter store DENIES, escalates, and names "
                  "itself on stderr (OSError arm, distinct from the non-JSON arm)",
                  ('deny', True, True),
                  (_res_s4.decision, 'REPEAT' in _res_s4.reason,
                   'could not be read back' in _res_s4.stderr))
    finally:
        _unreadable.chmod(0o600)

# An UNWRITABLE-BUT-READABLE store (PR #906 review, Important #2) drives the write-back
# OSError branch in _bump_counts specifically: the "unwritable store" rig above makes the
# whole .prflow/tmp DIRECTORY unwritable, so it trips _write_heartbeat first and
# _bump_counts is never reached; the "unreadable store" rig makes the FILE unreadable, so
# it exercises the READ path's OSError, not the write-back one. A file that is readable
# (0o400) inside an otherwise-writable directory reaches _bump_counts, computes a real
# escalation from the state it read, and then fails only on `open(store_path, "w")`. A
# regression that let that OSError swallow an already-computed escalation — reporting "not
# escalated" instead of a persistence-only failure — would stay green under both existing
# rigs and is the gap this fixture closes.
if _os.geteuid() != 0:
    _rig_s5 = _GuardRig()
    _rig_s5.run(_payload('echo x > /tmp/f', tid='seed-unwritable-1'))  # arm count -> 1
    _store_s5 = _rig_s5.root / '.prflow' / 'tmp' / 'pretooluse-guard-counts.json'
    _store_s5.chmod(0o400)  # readable, not writable; directory stays writable
    try:
        _res_s5 = _rig_s5.run(_payload('echo x > /tmp/g', tid='seed-unwritable-2'))
        assert_eq("#805/#906 guard: write-back failure still DENIES, exit 0", (0, 'deny'),
                  (_res_s5.rc, _res_s5.decision))
        assert_eq("#805/#906 guard: an already-computed escalation SURVIVES a write-back "
                  "OSError (the verdict is decided before the write, and the write failure "
                  "must not revoke it)", True, 'REPEAT' in _res_s5.reason)
        assert_eq("#805/#906 guard: write-back failure names itself on stderr, distinct "
                  "from the read-side breadcrumbs", True,
                  'could not be written back' in _res_s5.stderr)
        # Positive control on the SAME rig: with the store writable again, a third distinct
        # command on the same arm still escalates and persists normally, so the assertions
        # above are attributable to the write-back failure and not to some other effect of
        # this fixture. The persisted count is 2, not 3: the second call's own write failed
        # (by design — that unpersisted increment is exactly what "cost only PERSISTENCE"
        # means), so this call reads back the stale count of 1 and advances it to 2.
        _store_s5.chmod(0o600)
        _res_s5_ctrl = _rig_s5.run(_payload('echo x > /tmp/h', tid='seed-unwritable-3'))
        assert_eq("#805/#906 guard: write-back positive control — writable store still "
                  "escalates and persists", (True, 2),
                  ('REPEAT' in _res_s5_ctrl.reason,
                   (_rig_s5.counts() or {}).get('arms', {}).get('R3-tmp')))
    finally:
        _store_s5.chmod(0o600)

# ── tool_use_id-ABSENT counting path (issue #805 review). Without a fallback key this
# branch incremented on EVERY invocation, so a re-fired hook escalated on the engine's
# FIRST offending command — precisely the branch where idempotency is unavailable. The
# content-derived fallback keys on (arm, command), so a repeat of the SAME command counts
# once while a DIFFERENT command on the same arm is a genuine second denial.
def _payload_no_tid(cmd):
    return _json805.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}})


_rig_nt = _GuardRig()
assert_eq("#805 guard: no tool_use_id — first denial is NOT escalated", False,
          'REPEAT' in _rig_nt.run(_payload_no_tid('echo x > /tmp/a')).reason)
assert_eq("#805 guard: no tool_use_id — a REPEAT of the identical command does not "
          "double-count (content-derived idempotency key)", False,
          'REPEAT' in _rig_nt.run(_payload_no_tid('echo x > /tmp/a')).reason)
assert_eq("#805 guard: no tool_use_id — a DIFFERENT command on the same arm is a genuine "
          "second denial and escalates", True,
          'REPEAT' in _rig_nt.run(_payload_no_tid('echo x > /tmp/b')).reason)
assert_eq("#805 guard: no tool_use_id — the per-arm counter counted exactly twice", 2,
          (_rig_nt.counts() or {}).get('arms', {}).get('R3-tmp'))

# ── Lock-acquisition timeout (issue #805 review): the escalation is disarmed for that
# call, so it must leave a NAMED stderr breadcrumb rather than returning silently — under
# exactly the contention the lock exists for, a run whose repeats never escalate would
# otherwise be indistinguishable from one that had none. Driven by holding the lock file
# from this process for longer than the guard's bounded wait.
import fcntl as _fcntl805

_rig_lk = _GuardRig()
_rig_lk.run(_payload('echo hi', tid='seed-lock'))
_lock_f = open(_rig_lk.root / '.prflow' / 'tmp' / 'pretooluse-guard-counts.lock', 'w')
_fcntl805.flock(_lock_f.fileno(), _fcntl805.LOCK_EX)
try:
    _res_lk = _rig_lk.run(_payload('echo x > /tmp/f', tid='lock'))
    assert_eq("#805 guard: a lock timeout still DENIES, exit 0", (0, 'deny'),
              (_res_lk.rc, _res_lk.decision))
    assert_eq("#805 guard: a lock timeout NAMES itself on stderr (the escalation is "
              "disarmed for this call, never silently)", True,
              'lock not acquired' in _res_lk.stderr)
    assert_eq("#805 guard: a lock timeout emits the BASE remediation, not an escalation",
              False, 'REPEAT' in _res_lk.reason)
finally:
    _fcntl805.flock(_lock_f.fileno(), _fcntl805.LOCK_UN)
    _lock_f.close()
# Positive control on the same rig: with the lock released the same command denies with no
# timeout breadcrumb, so the assertions above are attributable to the held lock.
_res_lk2 = _rig_lk.run(_payload('echo x > /tmp/g', tid='lock-control'))
assert_eq("#805 guard: lock positive control — the same rig denies with no timeout "
          "breadcrumb once the lock is released", (True, False),
          (_res_lk2.decision == 'deny', 'lock not acquired' in _res_lk2.stderr))

# ── Run-keyed store (AC30). With a run id in the environment the store file carries it,
# so two runs sharing a workspace do not share counts; with none it degrades to the single
# workspace-scoped file (the local/interactive tier) as the docstring records.
_rig_rk = _GuardRig()
_rig_rk.run(_payload('echo x > /tmp/f', tid='rk1'),
            env_extra={'GITHUB_RUN_ID': '4242', 'GITHUB_RUN_ATTEMPT': '2'})
assert_eq("#805 guard: the counter store is RUN-KEYED when the environment supplies a run id",
          ['pretooluse-guard-counts-4242-2.json'], _rig_rk.store_names())
assert_eq("#805 guard: the run-keyed store does not write the unkeyed filename", None,
          _rig_rk.counts())
_rig_rk2 = _GuardRig()
_rig_rk2.run(_payload('echo x > /tmp/f', tid='rk2a'), env_extra={'GITHUB_RUN_ID': '1'})
assert_eq("#805 guard: a DIFFERENT run id does not inherit the prior run's counts (first "
          "denial of the arm is not escalated)", False,
          'REPEAT' in _rig_rk2.run(_payload('echo y > /tmp/g', tid='rk2b'),
                                   env_extra={'GITHUB_RUN_ID': '2'}).reason)
_rig_rk3 = _GuardRig()
_rig_rk3.run(_payload('echo x > /tmp/f', tid='rk3'))
assert_eq("#805 guard: with NO run id the store degrades to the workspace-scoped "
          "filename (the local/interactive tier)", (1, []),
          ((_rig_rk3.counts() or {}).get('arms', {}).get('R3-tmp'), _rig_rk3.store_names()))

# `_run_key` SANITIZE-TO-EMPTY (issue #805 review round 3). A run id whose every character
# is outside the filename-safe alphabet must be treated as ABSENT, not as an empty key: an
# empty key would compose the filename `pretooluse-guard-counts-.json`, a third store shape
# distinct from both the run-keyed and the workspace-scoped one. Driven with a run id made
# only of rejected characters, asserting the WORKSPACE-scoped filename is written and no
# run-keyed file appears at all.
_rig_rk4 = _GuardRig()
_rig_rk4.run(_payload('echo x > /tmp/f', tid='rk4'), env_extra={'GITHUB_RUN_ID': '///'})
assert_eq("#805 guard: a run id that sanitizes to EMPTY is treated as absent — the "
          "workspace-scoped store is written and no run-keyed file is created",
          (1, []),
          ((_rig_rk4.counts() or {}).get('arms', {}).get('R3-tmp'), _rig_rk4.store_names()))
# The end-to-end assertion above pins the CONTRACT but is absorbed by defence in depth:
# `_store_names` also treats a falsy key as absent, so mutating `_run_key`'s return alone
# leaves the filename unchanged. Drive `_run_key` directly so the sanitize-to-None line has
# its own attributable coverage, with a non-empty control on the same call.
_gm805 = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location('_pretooluse_guard_805', _GUARD_SRC))
_gm805.__spec__.loader.exec_module(_gm805)


def _run_key_under(env):
    _saved = {k: _os.environ.get(k) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}
    try:
        for k in _saved:
            _os.environ.pop(k, None)
        _os.environ.update(env)
        return _gm805._run_key()
    finally:
        for k, v in _saved.items():
            _os.environ.pop(k, None)
            if v is not None:
                _os.environ[k] = v


assert_eq("#805 guard: _run_key returns None (not '') when every character of the run id "
          "is rejected by the filename-safe alphabet", None,
          _run_key_under({'GITHUB_RUN_ID': '///'}))
assert_eq("#805 guard: _run_key control — a run id with accepted characters survives "
          "sanitizing rather than being rejected wholesale", '9a',
          _run_key_under({'GITHUB_RUN_ID': '/9/a/'}))
# Positive control on the same shape: a run id carrying at least one accepted character
# DOES key the store, so the assertion above is attributable to the sanitizing and not to
# the environment being ignored wholesale.
_rig_rk5 = _GuardRig()
_rig_rk5.run(_payload('echo x > /tmp/f', tid='rk5'), env_extra={'GITHUB_RUN_ID': '//a//'})
assert_eq("#805 guard: sanitize positive control — a run id with one accepted character "
          "still keys the store (to the sanitized value)",
          (['pretooluse-guard-counts-a.json'], None),
          (_rig_rk5.store_names(), _rig_rk5.counts()))

# `_SEEN_MAX` OVERFLOW EVICTION (issue #805 review round 3). The `seen` idempotency map is
# bounded; on overflow the OLDEST-inserted keys are dropped, which costs at worst a
# re-count of a long-superseded call and never a decision. Driven by pre-seeding the store
# with more than `_SEEN_MAX` synthetic keys and asserting the map is capped afterwards and
# the denial still lands.
_SEEN_MAX_805 = 512
_rig_sm = _GuardRig()
_rig_sm.run(_payload('echo hi', tid='seed-seenmax'))
_rig_sm.write_counts({
    'arms': {'R3-tmp': 1},
    'seen': {f'synthetic-{i}': {'arm': 'R3-tmp', 'escalated': True}
             for i in range(_SEEN_MAX_805 + 20)},
})
_res_sm = _rig_sm.run(_payload('echo x > /tmp/f', tid='seenmax-new'))
_seen_after = (_rig_sm.counts() or {}).get('seen', {})
assert_eq("#805 guard: a `seen` map over _SEEN_MAX is capped back to the bound on write",
          _SEEN_MAX_805, len(_seen_after))
assert_eq("#805 guard: eviction drops the OLDEST-inserted keys and keeps the newest — the "
          "just-written key survives and the first synthetic key is gone",
          (True, False),
          ('seenmax-new' in _seen_after, 'synthetic-0' in _seen_after))
assert_eq("#805 guard: `seen` eviction never costs the DECISION — the command is still "
          "denied, exit 0", (0, 'deny'), (_res_sm.rc, _res_sm.decision))
# Positive control: a store whose `seen` map is comfortably under the bound is NOT evicted,
# so the cap assertions above are attributable to the overflow rather than to the guard
# rewriting `seen` from scratch on every call.
_rig_sm2 = _GuardRig()
_rig_sm2.run(_payload('echo hi', tid='seed-seenmax-ctl'))
_rig_sm2.write_counts({
    'arms': {'R3-tmp': 1},
    'seen': {f'synthetic-{i}': {'arm': 'R3-tmp', 'escalated': True} for i in range(5)},
})
_rig_sm2.run(_payload('echo x > /tmp/f', tid='seenmax-ctl-new'))
_seen_ctl = (_rig_sm2.counts() or {}).get('seen', {})
assert_eq("#805 guard: seen-eviction positive control — an under-bound map is preserved "
          "in full and the new key is appended", (6, True),
          (len(_seen_ctl), 'synthetic-0' in _seen_ctl))

# ── issue #1011: GitHub-native blocked-by dependency stamp ──────────────────
# The section-scoped extraction function is single-sourced in preflight.py, and
# apply-issue-dependencies.py imports it. Both are exercised here: the function
# directly (in-process), and the helper as a real subprocess with a stubbed gh so
# its per-outcome stderr breadcrumbs and always-exit-0 contract are asserted.
import subprocess as _sp1011

_preflight1011 = _load('preflight_1011', SCRIPTS / 'preflight.py')

# deps_recognizer_is_single_sourced (in-process half) + section scoping.
assert_eq("#1011 section fn: returns only in-section numbers",
          ['99'],
          _preflight1011.dependency_section_numbers(
              "blocked by #11 and #10\n## Dependencies\n- #99\n## Next\nsee #7\n"))
assert_eq("#1011 section fn: captures every #N on an inbound or direction-free section line",
          ['5', '7'],
          _preflight1011.dependency_section_numbers(
              "## Dependencies\n- Blocked by #5 — reason\nrandom #7\n## Next\n#9"))
assert_eq("#1011 section fn: an out-of-section declaration yields nothing",
          [],
          _preflight1011.dependency_section_numbers("blocked by #12 outside a section"))
assert_eq("#1011 section fn: unique in source order",
          ['5'],
          _preflight1011.dependency_section_numbers("## Dependencies\n- #5\n- #5 again\n"))
# dependency_numbers is unchanged and still honours out-of-section declarations,
# so the two scopes diverge deliberately (deps_out_of_section_declaration_not_linked).
assert_eq("#1011 full recognizer still takes an out-of-section declaration",
          ['12'],
          _preflight1011.dependency_numbers("blocked by #12 outside a section"))
# The section fn emits NO breadcrumb of its own (a SOFT_KEYWORDS phrasing that would
# trip preflight's stderr must not leak through the section-scoped path).
_io1011 = io.StringIO()
with contextlib.redirect_stderr(_io1011):
    _preflight1011.dependency_section_numbers("requires #12 outside a section")
assert_eq("#1011 section fn: emits no stderr breadcrumb of its own", "", _io1011.getvalue())

# ── issue #1197: outbound direction under `## Dependencies`, at the LINE level ──
# The section limb used to capture every `#N` with no keyword test, so `Blocks #N` —
# which declares THIS issue the prerequisite — registered as its exact inverse. The
# stakes are highest on this entry point: apply-issue-dependencies.py consumes it and
# POSTs a blocked_by relationship its own docstring says it does not remove, so an
# inverted read here is a persistent GitHub write rather than a reversible gate stop.
assert_eq("#1197 section fn: an outbound 'Blocks #N' contributes nothing",
          [],
          _preflight1011.dependency_section_numbers("## Dependencies\n- Blocks #5 — reason\n"))
assert_eq("#1197 section fn: an outbound multi-number run drops the whole run",
          [],
          _preflight1011.dependency_section_numbers("## Dependencies\n- Blocks #5 and #6\n"))
# Line-level, not per-number: the inbound half of a mixed line goes with the line. The
# inbound number is listed SECOND so a per-number implementation would return ['6'] and
# this assertion would catch it, rather than passing on an empty result either way.
assert_eq("#1197 section fn: a mixed-direction line contributes NO numbers (line-level governance)",
          [],
          _preflight1011.dependency_section_numbers("## Dependencies\n- Blocks #5 but blocked by #6\n"))
assert_eq("#1197 section fn: an inbound line beside an outbound line still contributes",
          ['6'],
          _preflight1011.dependency_section_numbers(
              "## Dependencies\n- Blocks #5 — reason\n- Blocked by #6 — reason\n"))
assert_eq("#1197 section fn: a direction-free bare bullet keeps today's behaviour",
          ['5', '6'],
          _preflight1011.dependency_section_numbers("## Dependencies\n- #5\n- Part of #6\n"))
# The section entry point's no-stderr contract survives the new outbound arm: the
# breadcrumb rides `dependency_numbers` only, so apply-issue-dependencies.py still
# leaks no `preflight.py:` line into its own caller-facing output (issue #1197 AC7).
_io1197 = io.StringIO()
with contextlib.redirect_stderr(_io1197):
    _preflight1197_out = _preflight1011.dependency_section_numbers("## Dependencies\n- Blocks #5\n")
assert_eq("#1197 section fn: the outbound skip emits no stderr on the section-only path",
          ([], ""), (_preflight1197_out, _io1197.getvalue()))
# …and it IS observable on the entry point that owns a stderr surface.
_io1197b = io.StringIO()
with contextlib.redirect_stderr(_io1197b):
    _preflight1011.dependency_numbers("## Dependencies\n- Blocks #5\n")
assert_eq("#1197 full recognizer: the outbound skip breadcrumbs the dropped number",
          True, "#5" in _io1197b.getvalue() and "preflight.py:" in _io1197b.getvalue())
# The out-of-section limb is untouched — it parsed direction correctly all along, and
# widening DECLARATIONS with an outbound keyword would have broken it. Out of section a
# mixed line still yields its inbound half.
assert_eq("#1197 full recognizer: out-of-section direction handling is unchanged",
          ([], ['6']),
          (_preflight1011.dependency_numbers("Blocks #5 outside a section"),
           _preflight1011.dependency_numbers("Blocks #5 but blocked by #6, outside a section")))

# ── issue #1268: a number skipped for outbound direction becomes DATA the
# section-only caller can read, via a new `(found, skipped)` accessor, while the
# two existing public wrappers keep their historic `list[str]` shape. ──
# The new accessor over a body with one skipped (#202, outbound) and one kept
# (#201, inbound) entry returns both lists.
assert_eq("#1268 new accessor: returns (found, skipped) for a mixed body",
          (['201'], ['202']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #202 — this issue is the prerequisite\n"
              "- Blocked by #201 — b\n"))
assert_eq("#1268 new accessor: both lists are unique in source order",
          (['201'], ['202']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocked by #201\n- Blocked by #201 again\n"
              "- Blocks #202\n- Blocks #202 again\n"))
# Source order of the skipped list, distinct from mere uniqueness: two distinct
# outbound numbers must appear in body order, and reverse in a reversed body — so a
# reversed-order implementation would be caught rather than passing on a 1-element list.
assert_eq("#1268 new accessor: skipped preserves body source order (distinct numbers)",
          ([], ['301', '302']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #301\n- Blocks #302\n"))
assert_eq("#1268 new accessor: skipped order reverses with a reversed body",
          ([], ['302', '301']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #302\n- Blocks #301\n"))
# Disjointness: a number governed OUTBOUND on one line but declared inbound on
# another is registered (in `found`) and therefore must NOT also appear in `skipped`
# — otherwise the helper would both register #5 and falsely report it unregistered.
assert_eq("#1268 new accessor: a number rescued by an inbound line is not also skipped",
          (['5'], []),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #5\n- Blocked by #5\n"))
# …and the disjointness filter is scoped PER NUMBER, not to the whole list. Every
# fixture above has the rescued number as the only skipped entry, so an implementation
# that cleared all of `skipped` on any overlap would pass them byte-for-byte. Combining
# a rescued number (#5) with a distinct still-genuinely-skipped one (#6) is what pins
# the per-number scoping: #6 must survive the filter that removes #5.
assert_eq("#1268 new accessor: the disjointness filter strips only the rescued number",
          (['5'], ['6']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #5\n- Blocked by #5\n- Blocks #6\n"))
# A single outbound line carrying a multi-number run reports EVERY number it dropped —
# the per-number `add_skipped` loop, exercised at the accessor rather than only at the
# helper level, so a failure localises here.
assert_eq("#1268 new accessor: a multi-number outbound line reports every dropped number",
          ([], ['301', '302']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocks #301, #302\n"))
# Both lists populated with 2+ interleaved entries: `found` and `skipped` order
# independently, each in its own body order.
assert_eq("#1268 new accessor: found and skipped order independently when interleaved",
          (['401', '403'], ['402', '404']),
          _preflight1011.dependency_section_scan(
              "## Dependencies\n- Blocked by #401\n- Blocks #402\n"
              "- Blocked by #403\n- Blocks #404\n"))
# Boundary: a body with no `## Dependencies` section, and an empty body, each return
# the empty pair rather than raising or returning a bare list.
assert_eq("#1268 new accessor: a section-less body and an empty body both return ([], [])",
          (([], []), ([], [])),
          (_preflight1011.dependency_section_scan("Blocked by #7, but with no section\n"),
           _preflight1011.dependency_section_scan("")))
# The two existing wrappers still return list[str] with exactly today's contents —
# assert the TYPE (not just the value), because a tuple pass-through is the exact
# accidental shape the refactor could introduce.
_1268_body = ("## Dependencies\n- Blocks #202 — this issue is the prerequisite\n"
              "- Blocked by #201 — b\n")
_1268_sect = _preflight1011.dependency_section_numbers(_1268_body)
_1268_full = _preflight1011.dependency_numbers(_1268_body)
assert_eq("#1268 dependency_section_numbers still returns list[str] with found only",
          (list, ['201']), (type(_1268_sect), _1268_sect))
assert_eq("#1268 dependency_numbers still returns list[str] with found only",
          (list, ['201']), (type(_1268_full), _1268_full))
# The new accessor writes NO stderr of its own, exactly like dependency_section_numbers —
# the skip breadcrumb is the calling helper's responsibility (issue #1268 / AC6).
_io1268 = io.StringIO()
with contextlib.redirect_stderr(_io1268):
    _1268_scan = _preflight1011.dependency_section_scan("## Dependencies\n- Blocks #5\n")
assert_eq("#1268 new accessor: emits no stderr of its own on an outbound body",
          (([], ['5']), ""), (_1268_scan, _io1268.getvalue()))

# ── issue #1695: a malformed reserved LEADING dependency heading is unknown, not
# an empty prerequisite set. `malformed_reserved_dependency_heading` returns the
# offending `#`-marker for a `Dependencies` heading at a level other than two in the
# reserved leading position, and None for the canonical/absent/later-nested cases. ──
_mrdh = _preflight1011.malformed_reserved_dependency_heading
assert_eq("#1695 malformed: a leading `### Dependencies` is malformed (returns '###')",
          "###",
          _mrdh("### Dependencies\n- #201\n## Problem Statement\nbody\n"))
assert_eq("#1695 malformed: a leading `# Dependencies` is malformed (returns '#')",
          "#",
          _mrdh("# Dependencies\n- #201\n## Problem Statement\nbody\n"))
assert_eq("#1695 malformed: a leading `#### Dependencies` is malformed",
          "####",
          _mrdh("#### Dependencies\n- #7\n## Problem Statement\nbody\n"))
# Normalization mirrors DEPENDENCY_HEADING: case-insensitive, whitespace-tolerant.
assert_eq("#1695 malformed: normalization is case- and whitespace-insensitive",
          "###",
          _mrdh("###   dependencies   \n- #7\n## Problem Statement\nbody\n"))
# The canonical level-two reserved heading is NOT malformed (existing recognizer owns it).
assert_eq("#1695 canonical: a leading `## Dependencies` is not malformed (None)",
          None,
          _mrdh("## Dependencies\n- #201\n## Problem Statement\nbody\n"))
# Absent section: no Dependencies heading at all → None.
assert_eq("#1695 absent: a body with no Dependencies heading returns None",
          None,
          _mrdh("## Problem Statement\nbody with no dependency section\n"))
assert_eq("#1695 absent: an empty body returns None", None, _mrdh(""))
# AC4: a later NESTED `### Dependencies` after `## Problem Statement` is NOT promoted
# into the reserved section — the first level-≤2 non-Dependencies heading closes the
# reserved leading region, so the nested heading is never judged malformed here.
assert_eq("#1695 later-nested: `### Dependencies` after `## Problem Statement` is not flagged",
          None,
          _mrdh("## Problem Statement\nbody\n### Dependencies\n- #201\n"))
# A leading `## Problem Statement` before any Dependencies heading closes the region.
assert_eq("#1695 boundary: a `## Dependencies` that is not leading (after another ## section) is not the reserved one",
          None,
          _mrdh("## Problem Statement\nbody\n## Dependencies\n- #201\n"))
# Region-close by a LEADING level-1 non-Dependencies heading: `# Title` closes the reserved
# region, so a `### Dependencies` after it is NOT flagged (the `if level <= 2: return None` arm).
assert_eq("#1695 boundary: a leading `# Title` closes the region, so a following `### Dependencies` is not flagged",
          None,
          _mrdh("# Title\n### Dependencies\n- #201\n## Problem Statement\nbody\n"))
# Preamble/blank lines before the malformed heading: the non-heading skip path still reaches it.
assert_eq("#1695 preamble: blank and prose lines before a `### Dependencies` still flag it malformed",
          "###",
          _mrdh("\nsome intro prose\n\n### Dependencies\n- #201\n## Problem Statement\nbody\n"))
# The full ATX level range: level 5 and 6 headings are malformed; a 7-hash run is NOT an ATX
# heading (outside `{1,6}`), so it neither flags nor closes the region.
assert_eq("#1695 malformed: a leading `##### Dependencies` (level 5) is malformed",
          "#####",
          _mrdh("##### Dependencies\n- #7\n## Problem Statement\nbody\n"))
assert_eq("#1695 malformed: a leading `###### Dependencies` (level 6) is malformed",
          "######",
          _mrdh("###### Dependencies\n- #7\n## Problem Statement\nbody\n"))
assert_eq("#1695 boundary: a 7-hash `####### Dependencies` is not an ATX heading — not flagged, does not close the region",
          "###",
          _mrdh("####### Dependencies\n### Dependencies\n- #7\n## Problem Statement\nbody\n"))

# ── issue #1695: the reversible implement preflight (`dependencies` CLI) fails
# closed with UNAVAILABLE on a malformed reserved heading, naming `## Dependencies`,
# and never resolves a referenced issue (no gh call) nor reports PROCEED. Driven
# in-process through a --body-file so no network/gh is touched. ──
def _run_deps_cli(body_text):
    _bf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    _bf.write(body_text)
    _bf.close()
    _args = argparse.Namespace(body_file=_bf.name, issue=None, repo_relative=False)
    _out, _errio = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(_out), contextlib.redirect_stderr(_errio):
        _rc = _preflight1011.dependencies(_args)
    os.unlink(_bf.name)
    return _rc, _out.getvalue(), _errio.getvalue()

_rc1695, _out1695, _err1695 = _run_deps_cli("### Dependencies\n- #201\n## Problem Statement\nbody\n")
assert_eq("#1695 CLI malformed: exits UNAVAILABLE (3)", _preflight1011.UNAVAILABLE_EXIT, _rc1695)
assert_eq("#1695 CLI malformed: stdout is the UNAVAILABLE malformed token, never PROCEED",
          "UNAVAILABLE malformed-dependency-heading", _out1695.strip())
assert_eq("#1695 CLI malformed: diagnostic names the canonical `## Dependencies` spelling",
          True, "## Dependencies" in _err1695)
assert_eq("#1695 CLI malformed: never reports PROCEED", True, "PROCEED" not in _out1695)
# The canonical section still PROCEEDs unchanged (no open prerequisite here → PROCEED
# with the resolved list requires gh; a section-less body PROCEEDs with no numbers and
# no gh call). AC4 absent/canonical retention on the reversible gate:
_rc1695b, _out1695b, _err1695b = _run_deps_cli("## Problem Statement\nno dependency section here\n")
assert_eq("#1695 CLI absent: a section-less body still PROCEEDs (exit 0)", _preflight1011.PROCEED_EXIT, _rc1695b)
assert_eq("#1695 CLI absent: stdout is PROCEED", "PROCEED", _out1695b.strip())

_HELPER1011 = SCRIPTS / 'apply-issue-dependencies.py'


def _run_deps(number, *, argv=None):
    """Run apply-issue-dependencies.py with a stubbed gh; return (rc, stderr)."""
    _d = tempfile.mkdtemp()
    _bin = os.path.join(_d, 'bin')
    os.makedirs(_bin)
    _stub = os.path.join(_bin, 'gh')
    with open(_stub, 'w') as _fh:
        _fh.write(r'''#!/usr/bin/env bash
if [ "${2:-}" = "--method" ] && [ "${3:-}" = "POST" ]; then
  idarg="${!#}"; id="${idarg#issue_id=}"
  case "$id" in
    9001) echo '{"url":"ok"}'; exit 0 ;;
    9002) echo '{"message":"Target issue has already been taken","status":"422"}'; echo 'gh: (HTTP 422)' >&2; exit 1 ;;
    9003) echo '{"message":"Forbidden","status":"403"}'; echo 'gh: Forbidden (HTTP 403)' >&2; exit 1 ;;
    9005) echo '{"message":"Target issue may only be an issue","status":"422"}'; echo 'gh: (HTTP 422)' >&2; exit 1 ;;
    *) echo '{"message":"unexpected","status":"500"}' >&2; exit 1 ;;
  esac
fi
prev=""
for a in "$@"; do
  if [ "$prev" = "--jq" ] && [ "$a" = ".body" ]; then
    path="${2}"; n="${path##*/}"
    case "$n" in
      100) printf '%s\n' '## Dependencies' '- Blocked by #201 — a' '- Blocked by #202 — b' ;;
      101) printf '%s\n' '## Dependencies' '- Blocked by #203' ;;
      102) printf '%s\n' '## Dependencies' '- Blocked by #102' ;;
      103) printf '%s\n' '## Dependencies' '- Blocked by #201' '- Blocked by #299' ;;
      104) printf '%s\n' '## Dependencies' '- Blocked by #204' ;;
      105) printf '%s\n' '## Dependencies' '- Blocked by #205' '- Blocked by #206' ;;
      106) printf '%s\n' 'blocked by #201 outside a section' ;;
      108) printf '%s\n' '## Dependencies' '- Blocked by #207' ;;
      # issue #1197: outbound-only and mixed-direction sections. #201 resolves to a
      # linkable id below, so a scanner that still reads direction-blind would POST a
      # persistent (and inverted) blocked_by for either one.
      109) printf '%s\n' '## Dependencies' '- **Blocks #201** — this issue is the prerequisite' ;;
      110) printf '%s\n' '## Dependencies' '- Blocks #202 but blocked by #201' ;;
      # issue #1268: some-dropped-some-kept — one outbound line (#202, skipped for
      # direction) beside one inbound line (#201, kept and registered).
      111) printf '%s\n' '## Dependencies' '- Blocks #202 — this issue is the prerequisite' '- Blocked by #201 — b' ;;
      # issue #1268: the same number outbound on one line and inbound on another. It is
      # rescued into `found` and must NOT also be reported as a skip (no false breadcrumb).
      112) printf '%s\n' '## Dependencies' '- Blocks #201 — this issue is the prerequisite' '- Blocked by #201 — b' ;;
      # issue #1695: a malformed reserved LEADING dependency heading (`### Dependencies`).
      113) printf '%s\n' '### Dependencies' '- Blocked by #201 — a' '## Problem Statement' 'body' ;;
      # issue #1695: a later-NESTED `### Dependencies` after `## Problem Statement` is not
      # the reserved section — it is absent, so the "declares no prerequisites" arm holds.
      114) printf '%s\n' '## Problem Statement' 'body' '### Dependencies' '- #201' ;;
      200) exit 1 ;;
      *) printf '\n' ;;
    esac
    exit 0
  fi
  prev="$a"
done
path="${2}"; N="${path##*/}"
case "$N" in
  201) echo '{"id":9001,"number":201}' ;;
  202) echo '{"id":9001,"number":202}' ;;
  203) echo '{"id":9010,"number":203,"pull_request":{"url":"x"}}' ;;
  204) echo '{"id":9002,"number":204}' ;;
  205) echo '{"id":9003,"number":205}' ;;
  206) echo '{"id":9003,"number":206}' ;;
  207) echo '{"id":9005,"number":207}' ;;
  299) exit 1 ;;
  *) echo "{\"id\":9001,\"number\":$N}" ;;
esac
exit 0
''')
    os.chmod(_stub, 0o755)
    _env = dict(os.environ, DEVFLOW_GH=_stub)
    _cmd = [str(_HELPER1011)] + (argv if argv is not None else [str(number)])
    _p = _sp1011.run(_cmd, capture_output=True, encoding='utf-8', env=_env)
    return _p.returncode, _p.stderr


# deps_links_declared_prerequisites — two prerequisites, two links, exit 0.
_rc, _se = _run_deps(100)
assert_eq("#1011 happy: exit 0", 0, _rc)
assert_eq("#1011 happy: links #201", True, "linked #100 blocked_by #201." in _se)
assert_eq("#1011 happy: links #202", True, "linked #100 blocked_by #202." in _se)
assert_eq("#1011 breadcrumb: helper-name prefix on every line", True,
          all(line.startswith("apply-issue-dependencies.py:") for line in _se.strip().splitlines()))
assert_eq("#1011 final breadcrumb reports counts", True, "2 linked, 0 already linked, 0 failed" in _se)

# deps_pull_request_number_skipped.
_rc, _se = _run_deps(101)
assert_eq("#1011 PR skip: exit 0", 0, _rc)
assert_eq("#1011 PR skip: breadcrumb names the PR skip", True,
          "resolves to a pull request" in _se)

# deps_self_reference_skipped.
_rc, _se = _run_deps(102)
assert_eq("#1011 self-ref: exit 0", 0, _rc)
assert_eq("#1011 self-ref: breadcrumb names the own-number skip", True,
          "own number" in _se)

# deps_partial_failure_continues — 201 links, 299 unresolvable, final names #299.
_rc, _se = _run_deps(103)
assert_eq("#1011 partial: exit 0", 0, _rc)
assert_eq("#1011 partial: links the resolvable one", True, "linked #103 blocked_by #201." in _se)
assert_eq("#1011 partial: names the failed one", True, "does not resolve to an issue id" in _se)
assert_eq("#1011 partial: final breadcrumb names the failure", True,
          "1 linked, 0 already linked, 1 failed; failed: #299" in _se)

# deps_duplicate_is_benign — the "already been taken" 422 reports already-linked.
_rc, _se = _run_deps(104)
assert_eq("#1011 duplicate: exit 0", 0, _rc)
assert_eq("#1011 duplicate: reported as already linked, not a failure", True,
          "was already blocked_by #204" in _se and "1 already linked" in _se)

# deps_duplicate_is_benign_but_other_422_is_not — a NON-duplicate 422 ("Target
# issue may only be an issue", id 9005) must route to the failure breadcrumb and
# NOT be swallowed as already-linked. 108 declares #207 → id 9005 → real 422.
_rc, _se = _run_deps(108)
assert_eq("#1011 non-duplicate 422: exit 0", 0, _rc)
assert_eq("#1011 non-duplicate 422: routed to failure (API refused, HTTP 422)", True,
          "API refused" in _se and "HTTP 422" in _se)
assert_eq("#1011 non-duplicate 422: NOT reported as already-linked", True,
          "already been taken" not in _se and "was already blocked_by" not in _se
          and "0 already linked" in _se and "1 failed" in _se)

# deps_uniform_refusal_collapses — two same-status refusals collapse to one line.
_rc, _se = _run_deps(105)
assert_eq("#1011 collapse: exit 0", 0, _rc)
assert_eq("#1011 collapse: one collapsed breadcrumb naming the status", True,
          "every declared prerequisite's registration was refused with the same status (HTTP 403)" in _se)
assert_eq("#1011 collapse: no per-number 'could not link' line emitted", True,
          "could not link #105 blocked_by #205" not in _se)

# deps_no_declarations_makes_no_api_call — out-of-section only → no registration.
_rc, _se = _run_deps(106)
assert_eq("#1011 out-of-section: exit 0", 0, _rc)
assert_eq("#1011 out-of-section: breadcrumb says no prerequisites in a section", True,
          "declares no prerequisites in a `## Dependencies` section" in _se)

# ── issue #1695: a malformed reserved LEADING `### Dependencies` heading. The native
# stamp exits 0, breadcrumbs the malformed heading under its own prefix, performs no
# GitHub dependency write, and does NOT emit its "declares no prerequisites" outcome.
# DISCRIMINATION: the section scanner is level-2-only, so a `### Dependencies` yields no
# numbers regardless — a malformed-blind helper would emit "declares no prerequisites"
# (never a POST), so it is the ABSENCE of that summary (asserted below) that separates
# old from new; the "no link posted" row is a non-discriminating sanity check. ──
_rc, _se = _run_deps(113)
assert_eq("#1695 malformed native-stamp: exit 0", 0, _rc)
assert_eq("#1695 malformed native-stamp: breadcrumb names the malformed reserved heading", True,
          "reserved leading dependency section is spelled `### Dependencies`" in _se)
assert_eq("#1695 malformed native-stamp: breadcrumb is helper-prefixed", True,
          all(line.startswith("apply-issue-dependencies.py:") for line in _se.strip().splitlines()))
assert_eq("#1695 malformed native-stamp: sanity — no dependency write (non-discriminating)", True,
          "linked #113 blocked_by" not in _se and "was already blocked_by" not in _se)
assert_eq("#1695 malformed native-stamp: DISCRIMINATING — does NOT claim it declares no prerequisites", True,
          "declares no prerequisites" not in _se)
# A later-nested `### Dependencies` after `## Problem Statement` is absent (not the
# reserved section), so the existing "declares no prerequisites" outcome still holds (AC4).
_rc, _se = _run_deps(114)
assert_eq("#1695 later-nested native-stamp: exit 0", 0, _rc)
assert_eq("#1695 later-nested native-stamp: retains the no-prerequisites outcome", True,
          "declares no prerequisites in a `## Dependencies` section" in _se)
assert_eq("#1695 later-nested native-stamp: not treated as malformed", True,
          "reserved leading dependency section is spelled" not in _se)

# ── issue #1197 AC6: no persistent blocked_by is registered for an OUTBOUND
# declaration. Asserted end-to-end on the real helper over a stubbed gh — the derived
# number set is empty, so the POST branch is never entered at all (there is no live
# write, and none is attempted). #201 is a linkable id in the stub, so a direction-blind
# scanner would have produced "linked #109 blocked_by #201." here; asserting that
# literal's ABSENCE alongside the no-prerequisites breadcrumb keeps the row
# discriminating rather than satisfied by any quiet run.
# issue #1268 reconciles these two #1197 AC6 rows to the new breadcrumb: an outbound
# number is now NAMED as a skip (with the direction as the reason) rather than
# silently collapsed into the false "declares no prerequisites" line. The third
# tuple slot flips from True (old literal present) to False (old literal absent), and
# two new slots assert the skip breadcrumb and the outbound-only summary are present.
# The genuinely-empty-section row (`#1011 out-of-section`, body 106) below keeps the
# old literal — the three were distinguished, not swept together.
_rc, _se = _run_deps(109)
assert_eq("#1268/#1197 AC6: an outbound-only declaration registers nothing and is no longer "
          "misdescribed as 'no prerequisites' (exit 0, no POST attempted)",
          (0, False, False, True, True),
          (_rc,
           "linked #109 blocked_by" in _se,
           "declares no prerequisites in a `## Dependencies` section" in _se,
           "skipped #201" in _se and "OUTBOUND relation" in _se,
           "only as OUTBOUND relations" in _se))
_rc, _se = _run_deps(110)
assert_eq("#1268/#1197 AC6: a mixed-direction LINE registers nothing (line-level) and names "
          "each dropped number instead of claiming no prerequisites",
          (0, False, False, True, True),
          (_rc,
           "linked #110 blocked_by" in _se,
           "declares no prerequisites in a `## Dependencies` section" in _se,
           "skipped #202" in _se and "skipped #201" in _se,
           "only as OUTBOUND relations" in _se))

# issue #1268 — some-dropped-some-kept path (body 111: outbound #202 beside inbound
# #201). This path produced NO output about the dropped number today; now it names it
# under the helper's own prefix while still registering the kept prerequisite.
_rc, _se = _run_deps(111)
assert_eq("#1268 mixed path: exit 0", 0, _rc)
assert_eq("#1268 mixed path: registers the kept inbound prerequisite", True,
          "linked #111 blocked_by #201." in _se)
assert_eq("#1268 mixed path: names the dropped outbound number (silent today)", True,
          "skipped #202" in _se and "OUTBOUND relation" in _se)
assert_eq("#1268 mixed path: does NOT claim the issue declared no prerequisites", True,
          "declares no prerequisites" not in _se)
assert_eq("#1268 mixed path: does NOT emit the every-dropped OUTBOUND summary (a kept one exists)",
          True, "only as OUTBOUND relations" not in _se)
assert_eq("#1268 mixed path: every stderr line still carries the helper prefix", True,
          all(_l.startswith("apply-issue-dependencies.py:") for _l in _se.strip().splitlines()))

# issue #1268 — negative control: an all-inbound section (body 100) produces NO skip
# breadcrumb, so the assertions above are attributable to the outbound-skip predicate
# rather than to an unconditional emit.
_rc, _se = _run_deps(100)
assert_eq("#1268 negative control: an all-inbound section produces no skip breadcrumb",
          (0, False),
          (_rc, "OUTBOUND relation" in _se))

# issue #1268 — a number that is outbound on one line but inbound on another is
# rescued into `found`, so it registers AND emits NO contradictory skip breadcrumb
# (the false-breadcrumb defect the disjointness filter closes).
_rc, _se = _run_deps(112)
assert_eq("#1268 rescued number: exit 0", 0, _rc)
assert_eq("#1268 rescued number: registers #201 (the inbound line wins)", True,
          "linked #112 blocked_by #201." in _se)
assert_eq("#1268 rescued number: emits NO false skip breadcrumb for the rescued number", True,
          "skipped #201" not in _se and "OUTBOUND relation" not in _se)

# body fetch failure.
_rc, _se = _run_deps(200)
assert_eq("#1011 body-fetch-fail: exit 0", 0, _rc)
assert_eq("#1011 body-fetch-fail: breadcrumb names the fetch failure", True,
          "could not fetch issue #200's body" in _se)

# arg-slip: missing, non-numeric, word-split.
for _bad_argv, _label in (([], "missing"), (["abc"], "non-numeric"), (["1", "2"], "word-split")):
    _rc, _se = _run_deps(None, argv=_bad_argv)
    assert_eq(f"#1011 arg-slip ({_label}): exit 0", 0, _rc)
    assert_eq(f"#1011 arg-slip ({_label}): breadcrumb names a caller arg-slip", True,
              "caller arg-slip" in _se and "issue-number argument" in _se)

# deps_recognizer_import_failure_breadcrumbs — no preflight sibling → import fails, exit 0.
_impfail_d = tempfile.mkdtemp()
_impfail_helper = os.path.join(_impfail_d, 'apply-issue-dependencies.py')
with open(_impfail_helper, 'w') as _fh:
    _fh.write((SCRIPTS / 'apply-issue-dependencies.py').read_text())
os.chmod(_impfail_helper, 0o755)
_p = _sp1011.run([str(_impfail_helper), '100'], capture_output=True, encoding='utf-8',
                 env=dict(os.environ, DEVFLOW_GH='gh'))
assert_eq("#1011 import-failure: exit 0", 0, _p.returncode)
assert_eq("#1011 import-failure: breadcrumb names the recognizer import failure", True,
          "could not import the dependency recognizer" in _p.stderr)

print("issue #1087: completion verification-flight evidence gate")

cce = _load('check_completion_evidence', SCRIPTS / 'check-completion-evidence.py')
import json as _json1087
import tempfile as _tmp1087


def _write_flight(rec):
    """Write a flight record JSON to a temp verification-flights dir; return
    (repo_root, flight_key)."""
    root = _tmp1087.mkdtemp()
    key = 'a' * 64
    d = os.path.join(root, '.prflow', 'tmp', 'verification-flights')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, key + '.json'), 'w') as fh:
        fh.write(_json1087.dumps(rec))
    return root, key


_PASS_REC = {
    "state": "passed", "result": "passed", "candidate_identity": "treeX",
    "suite_summary": {"command": "lib/test/run.sh", "exit_status": 0,
                      "skipped_checks": []},
    "skipped_checks": [],
}

# ── Validator unit: the strict pass contract (maps AC "Pass contract is strict") ──
_root, _key = _write_flight(_PASS_REC)
_p = os.path.join(_root, '.prflow', 'tmp', 'verification-flights', _key + '.json')
_tok, _det = cce.validate_implement_completion(_p, _root, claim_identity="treeX")
assert_eq("#1087 pass: a current, passed, skip-free record passes", "pass", _tok)

# integer 0 only — string "0" and boolean false are NOT a pass (missing-evidence,
# a wrong-typed field, per the pass contract).
for _bad, _lbl in [("0", "string-0"), (False, "bool-false"), (1.0, "float")]:
    _rec = dict(_PASS_REC)
    _rec["suite_summary"] = dict(_PASS_REC["suite_summary"], exit_status=_bad)
    _r2, _k2 = _write_flight(_rec)
    _pp = os.path.join(_r2, '.prflow', 'tmp', 'verification-flights', _k2 + '.json')
    _t, _d = cce.validate_implement_completion(_pp, _r2, claim_identity="treeX")
    assert_eq(f"#1087 exit_status {_lbl} is not a pass", True, _t != "pass")

# nonzero exit → verification-not-pass.
_rec = dict(_PASS_REC)
_rec["suite_summary"] = dict(_PASS_REC["suite_summary"], exit_status=1)
_r2, _k2 = _write_flight(_rec)
_pp = os.path.join(_r2, '.prflow', 'tmp', 'verification-flights', _k2 + '.json')
_t, _d = cce.validate_implement_completion(_pp, _r2, claim_identity="treeX")
assert_eq("#1087 nonzero exit → verification-not-pass", "verification-not-pass", _t)

# missing command → missing-evidence.
_rec = dict(_PASS_REC)
_rec["suite_summary"] = {"exit_status": 0}
_r2, _k2 = _write_flight(_rec)
_pp = os.path.join(_r2, '.prflow', 'tmp', 'verification-flights', _k2 + '.json')
_t, _d = cce.validate_implement_completion(_pp, _r2, claim_identity="treeX")
assert_eq("#1087 missing suite_summary.command → missing-evidence", "missing-evidence", _t)

# ── Flight states fail closed (maps AC "Flight states fail closed") ──────────────
for _st in ("claimed", "running", "failed", "timed_out", "cancelled", "stale", "incomplete"):
    _rec = dict(_PASS_REC)
    _rec["state"] = _st
    _r2, _k2 = _write_flight(_rec)
    _pp = os.path.join(_r2, '.prflow', 'tmp', 'verification-flights', _k2 + '.json')
    _t, _d = cce.validate_implement_completion(_pp, _r2, claim_identity="treeX")
    assert_eq(f"#1087 flight state {_st!r} is not a pass", "verification-not-pass", _t)

# missing / malformed / array / scalar file → missing-evidence.
_t, _d = cce.validate_implement_completion(os.path.join(_root, 'nope.json'), _root, claim_identity="treeX")
assert_eq("#1087 absent record → missing-evidence", "missing-evidence", _t)
_bad = _tmp1087.mkstemp(suffix='.json')[1]
with open(_bad, 'w') as _fh:
    _fh.write('[1,2,3]')
_t, _d = cce.validate_implement_completion(_bad, _root, claim_identity="treeX")
assert_eq("#1087 JSON array record → missing-evidence", "missing-evidence", _t)

# ── Passed-record defects fail closed (skips, stale) ─────────────────────────────
_rec = dict(_PASS_REC)
_rec["skipped_checks"] = [{"check": "x", "kind": "host-capability"}]
_r2, _k2 = _write_flight(_rec)
_pp = os.path.join(_r2, '.prflow', 'tmp', 'verification-flights', _k2 + '.json')
_t, _d = cce.validate_implement_completion(_pp, _r2, claim_identity="treeX")
assert_eq("#1087 any skip (even host-capability) → skipped-checks-present", "skipped-checks-present", _t)

# top-level skip list disagreeing with an empty summary list is still caught (top-level owns it).
_t, _d = cce.validate_implement_completion(_p, _root, claim_identity="DIFFERENT-TREE")
assert_eq("#1087 changed candidate identity → stale-candidate", "stale-candidate", _t)

# ── workpad integration: no marker → no PATCH (maps "Completion requires marker",
#    "Skipped-step regression is executable") ──────────────────────────────────────
workpad._completion_evidence_verdict = _REAL_COMPLETION_EVIDENCE_VERDICT
try:
    _code, _out, _err, _patched = _drive_cmd_update(GATE_BODY, status='Complete')
    assert_eq("#1087 Complete with NO completion marker exits non-zero", 1, _code)
    assert_eq("#1087 Complete with no marker performs NO PATCH", None, _patched)
    assert_eq("#1087 the no-marker abort names missing-evidence", True, 'missing-evidence' in _err)

    # Recording a completion marker for a PASSING record, then finalizing, PATCHes once.
    _root, _key = _write_flight(_PASS_REC)
    _code, _out, _err, _patched = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence=_key,
        repo_root=_root, claim_identity="treeX")
    assert_eq("#1087 Complete WITH a validated marker exits 0", None, _code)
    assert_eq("#1087 Complete with a valid marker PATCHes (🎉 Complete)", True,
              _patched is not None and '🎉 Complete' in _patched)
    assert_eq("#1087 exactly one completion-verification marker is written", 1,
              _patched.count('completion-verification:' + _key))

    # Pass replay is idempotent: the recorded-marker body re-finalized keeps one marker.
    _body_with_marker = _patched
    _code2, _o2, _e2, _patched2 = _drive_cmd_update(
        _body_with_marker, status='Complete', repo_root=_root, claim_identity="treeX")
    assert_eq("#1087 replay: a second Complete over the recorded marker exits 0", None, _code2)
    assert_eq("#1087 replay: still exactly one completion marker (no duplicate)", 1,
              _patched2.count('completion-verification:' + _key))

    # ── issue #2080: a NON-HERMETIC passed flight (schema_version 2, external_services
    #    naming a live service) is completion-valid. The completion gate reads the flight
    #    as a plain object with no schema/hermeticity gate, so recording it writes the
    #    marker and a following --status Complete passes exactly as a hermetic flight does.
    _NH_REC = dict(_PASS_REC, schema_version=2, external_services="postgres")
    _rootN, _keyN = _write_flight(_NH_REC)
    _codeN, _oN, _eN, _patchedN = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence=_keyN,
        repo_root=_rootN, claim_identity="treeX")
    assert_eq("#2080 Complete with a non-hermetic passed flight exits 0", None, _codeN)
    assert_eq("#2080 a non-hermetic passed flight PATCHes (🎉 Complete)", True,
              _patchedN is not None and '🎉 Complete' in _patchedN)
    assert_eq("#2080 exactly one completion marker for the non-hermetic flight", 1,
              _patchedN.count('completion-verification:' + _keyN))

    # Recording a STALE record aborts before PATCH (the suite-failed/stale regressions).
    _rootS, _keyS = _write_flight(dict(_PASS_REC, candidate_identity="OLD-TREE"))
    _codeS, _oS, _eS, _patchedS = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence=_keyS,
        repo_root=_rootS, claim_identity="treeX")
    assert_eq("#1087 recording a stale record aborts (no PATCH)", None, _patchedS)
    assert_eq("#1087 the stale abort names stale-candidate", True, 'stale-candidate' in _eS)

    # A failed record recorded for the current tree aborts before PATCH.
    _rootF, _keyF = _write_flight(dict(_PASS_REC, state="failed", result="failed"))
    _codeF, _oF, _eF, _patchedF = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence=_keyF,
        repo_root=_rootF, claim_identity="treeX")
    assert_eq("#1087 recording a failed record aborts (no PATCH)", None, _patchedF)

    # Standalone copy (validator sibling absent): a Complete with a marker fails closed
    # with the missing-evidence token, while a NON-Complete update is unaffected.
    _body_marker_only = _body_with_marker  # carries the completion marker
    _saved_loader = workpad._load_completion_validator
    workpad._load_completion_validator = lambda: None
    try:
        _codeA, _oA, _eA, _patchedA = _drive_cmd_update(
            _body_marker_only, status='Complete', repo_root=_root, claim_identity="treeX")
        assert_eq("#1087 standalone-copy Complete performs NO PATCH", None, _patchedA)
        assert_eq("#1087 standalone-copy Complete names missing-evidence + the sibling", True,
                  'missing-evidence' in _eA and 'check-completion-evidence.py' in _eA)
        _codeB, _oB, _eB, _patchedB = _drive_cmd_update(_body_marker_only, note=['still works'])
        assert_eq("#1087 standalone-copy NON-Complete update still PATCHes", True, _patchedB is not None)
    finally:
        workpad._load_completion_validator = _saved_loader
finally:
    workpad._completion_evidence_verdict = lambda args, prog_content: None


print("issue #1611: CI-derived completion-evidence gate")

# The CI validator does REAL git reads (rev-parse HEAD + status --porcelain) against
# a repo_root — no mock of subprocess/git, per the issue's testing strategy. Build a
# real temporary repository with one commit.
# The required checks the fixture ci.yml declares — the single declared source that
# _required_checks reads (issue #1898). The fixture repo carries a real ci.yml so the
# coverage check runs against a genuine declared set, not a stubbed constant.
_CI_REQUIRED_A = 'lib + python tests'
_CI_REQUIRED_B = 'lint (shellcheck + actionlint + ruff)'
_CI_YML = (
    "jobs:\n"
    "  test:\n"
    "    # prflow:required-check\n"
    f"    name: {_CI_REQUIRED_A}\n"
    "  lint:\n"
    "    # prflow:required-check\n"
    f"    name: {_CI_REQUIRED_B}\n"
)


def _make_ci_repo():
    root = _tmp1087.mkdtemp()
    _subprocess.run(['git', 'init', '-q', '-b', 'main', root], check=True)
    _subprocess.run(['git', 'config', 'user.email', 't@e'], cwd=root, check=True)
    _subprocess.run(['git', 'config', 'user.name', 't'], cwd=root, check=True)
    with open(os.path.join(root, 'f.txt'), 'w') as _fh:
        _fh.write('x\n')
    os.makedirs(os.path.join(root, '.github', 'workflows'), exist_ok=True)
    with open(os.path.join(root, '.github', 'workflows', 'ci.yml'), 'w') as _fh:
        _fh.write(_CI_YML)
    _subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    _subprocess.run(['git', 'commit', '-qm', 'init'], cwd=root, check=True)
    _h = _subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                         capture_output=True, text=True, check=True).stdout.strip()
    return root, _h


_ci_root, _ci_head = _make_ci_repo()


def _ci_rec(**over):
    # A well-formed local-tier record whose checks cover the required set (issue #1898).
    base = {'head_sha': _ci_head, 'tier': 'local',
            'run_url': 'https://github.com/o/r/actions/runs/1',
            'checks': [{'name': _CI_REQUIRED_A, 'conclusion': 'success'},
                       {'name': _CI_REQUIRED_B, 'conclusion': 'success'}]}
    base.update(over)
    return base


# ── _is_full_hex_sha unit ────────────────────────────────────────────────────
assert_eq("#1611 _is_full_hex_sha true for 40 lowercase hex", True, cce._is_full_hex_sha('a' * 40))
assert_eq("#1611 _is_full_hex_sha false for uppercase", False, cce._is_full_hex_sha('A' * 40))
assert_eq("#1611 _is_full_hex_sha false for 39-char", False, cce._is_full_hex_sha('a' * 39))
assert_eq("#1611 _is_full_hex_sha false for 41-char", False, cce._is_full_hex_sha('a' * 41))
assert_eq("#1611 _is_full_hex_sha false for non-str", False, cce._is_full_hex_sha(None))

# ── payload encode/decode round-trip (workpad side) ──────────────────────────
_rt = workpad._decode_ci_payload(workpad._encode_ci_payload({'k': 'v', 'n': 1}))
assert_eq("#1611 CI payload round-trips through base64url-unpadded JSON", {'k': 'v', 'n': 1}, _rt)
assert_eq("#1611 corrupt CI payload decodes to None (fail closed)", None,
          workpad._decode_ci_payload('!!!not-base64!!!'))

# ── validator unit: pass at HEAD over a clean tree ───────────────────────────
_t, _d = cce.validate_implement_completion_ci(_ci_rec(), _ci_root)
assert_eq("#1611 well-formed CI record at HEAD over clean tree → pass", "pass", _t)

# SHA != HEAD → stale-candidate.
_t, _d = cce.validate_implement_completion_ci(_ci_rec(head_sha='b' * 40), _ci_root)
assert_eq("#1611 CI record SHA != HEAD → stale-candidate", "stale-candidate", _t)

# Dirty tree → stale-candidate (then restore clean for later assertions).
with open(os.path.join(_ci_root, 'f.txt'), 'a') as _fh:
    _fh.write('dirty\n')
_t, _d = cce.validate_implement_completion_ci(_ci_rec(), _ci_root)
assert_eq("#1611 CI record over a dirty tree → stale-candidate", "stale-candidate", _t)
_subprocess.run(['git', 'checkout', '--', 'f.txt'], cwd=_ci_root, check=True)

# ── issue #1898: tier operand ────────────────────────────────────────────────
# A `cloud` tier is refused (missing-evidence), and the detail names the tier.
_t, _d = cce.validate_implement_completion_ci(_ci_rec(tier='cloud'), _ci_root)
assert_eq("#1898 CI tier 'cloud' → missing-evidence", "missing-evidence", _t)
assert_eq("#1898 the cloud-tier refusal names the tier (cloud)", True, 'cloud' in _d)
# An absent tier value is refused (missing-evidence), naming the tier field.
_r = _ci_rec()
del _r['tier']
_t, _d = cce.validate_implement_completion_ci(_r, _ci_root)
assert_eq("#1898 absent tier → missing-evidence", "missing-evidence", _t)
assert_eq("#1898 the absent-tier refusal names the tier field", True, 'tier' in _d)
# Any other non-local tier value is refused too (fail closed).
_t, _d = cce.validate_implement_completion_ci(_ci_rec(tier='remote'), _ci_root)
assert_eq("#1898 a non-local tier value → missing-evidence", "missing-evidence", _t)

# ── issue #1898: the checks set + required-check coverage ─────────────────────
# A single non-success conclusion among the checks → verification-not-pass, naming it.
for _c in ('failure', 'cancelled', 'skipped', 'neutral'):
    _r = _ci_rec(checks=[{'name': _CI_REQUIRED_A, 'conclusion': _c},
                         {'name': _CI_REQUIRED_B, 'conclusion': 'success'}])
    _t, _d = cce.validate_implement_completion_ci(_r, _ci_root)
    assert_eq(f"#1898 a {_c!r} conclusion in the checks set → verification-not-pass",
              "verification-not-pass", _t)
# A checks set that does NOT cover the required set → missing-evidence, naming the
# missing check.
_r = _ci_rec(checks=[{'name': _CI_REQUIRED_A, 'conclusion': 'success'}])  # lint absent
_t, _d = cce.validate_implement_completion_ci(_r, _ci_root)
assert_eq("#1898 checks missing a required member → missing-evidence", "missing-evidence", _t)
assert_eq("#1898 the uncovered-required-check refusal names the missing check",
          True, _CI_REQUIRED_B in _d)
# An empty checks list, a non-list checks value, and a malformed pair → missing-evidence.
for _over, _lbl in [({'checks': []}, "empty-list"),
                    ({'checks': 'x'}, "non-list"),
                    ({'checks': [{'name': _CI_REQUIRED_A}]}, "pair-missing-conclusion"),
                    ({'checks': [{'conclusion': 'success'}]}, "pair-missing-name"),
                    ({'checks': [['a', 'b']]}, "pair-not-object")]:
    _t, _d = cce.validate_implement_completion_ci(_ci_rec(**_over), _ci_root)
    assert_eq(f"#1898 malformed checks {_lbl} → missing-evidence", "missing-evidence", _t)

# missing each required scalar field in turn → missing-evidence.
for _f in ('head_sha', 'tier', 'run_url'):
    _r = _ci_rec()
    del _r[_f]
    _t, _d = cce.validate_implement_completion_ci(_r, _ci_root)
    assert_eq(f"#1898 missing field {_f} → missing-evidence", "missing-evidence", _t)

# malformed SHA shapes → missing-evidence (shape checked before staleness).
for _bad, _lbl in [(_ci_head[:7], "abbrev-7"),
                   ('A' + _ci_head[1:], "uppercase-hex"),
                   (_ci_head + '0', "41-char")]:
    _t, _d = cce.validate_implement_completion_ci(_ci_rec(head_sha=_bad), _ci_root)
    assert_eq(f"#1611 SHA shape {_lbl} → missing-evidence", "missing-evidence", _t)

# best-effort payload matrix: every non-object shape → missing-evidence, no traceback.
for _bad, _lbl in [([1, 2], "array"), ("scalar", "scalar-str"), (5, "scalar-int"),
                   (None, "null"), (False, "false"), (0, "zero"), ("", "empty-str")]:
    _t, _d = cce.validate_implement_completion_ci(_bad, _ci_root)
    assert_eq(f"#1611 non-object payload {_lbl} → missing-evidence", "missing-evidence", _t)

# present-but-wrong-typed scalar field VALUES inside a well-formed object → missing-evidence
# (a best-effort parser over an agent-writable payload; a producer bug could emit these).
for _over, _lbl in [({'tier': 5}, "tier-int"),
                    ({'head_sha': 123}, "head_sha-int"),
                    ({'run_url': ['x']}, "run_url-list")]:
    _t, _d = cce.validate_implement_completion_ci(_ci_rec(**_over), _ci_root)
    assert_eq(f"#1611 wrong-typed field value {_lbl} → missing-evidence", "missing-evidence", _t)

# ── issue #1898: _required_checks reads the single declared source (ci.yml) ────
assert_eq("#1898 _required_checks reads the marked job names from ci.yml",
          {_CI_REQUIRED_A, _CI_REQUIRED_B}, set(cce._required_checks(_ci_root)))
# An absent ci.yml declares no required checks (empty set; coverage is then vacuous).
assert_eq("#1898 _required_checks over a root with no ci.yml → empty set",
          frozenset(), cce._required_checks(_tmp1087.mkdtemp()))
# Marker-drift guard: a dropped `# prflow:required-check` marker on the REAL repo ci.yml
# silently shrinks the required set and re-opens the #1888 fail-open, which the fixture
# tests above cannot catch. Pin that the live tree still declares both known-critical
# checks (subset, so adding a future required check does not falsely fail this).
_REAL_ROOT_1898 = str(Path(__file__).resolve().parents[2])
assert_eq("#1898 the real repo ci.yml still declares both required checks (marker-drift guard)",
          {_CI_REQUIRED_A, _CI_REQUIRED_B},
          {_CI_REQUIRED_A, _CI_REQUIRED_B} & set(cce._required_checks(_REAL_ROOT_1898)))

# internal git-read failure propagates as _Internal (never a verdict): a well-formed
# record over a NON-git repo_root makes _ci_git_read raise, and the entry point catches
# only Verdict, so _Internal escapes — the "unknown is not pass" boundary.
_nongit = _tmp1087.mkdtemp()
try:
    cce.validate_implement_completion_ci(_ci_rec(head_sha='a' * 40), _nongit)
    _raised_internal = False
except cce._Internal:
    _raised_internal = True
except Exception:
    _raised_internal = False
assert_eq("#1611 well-formed record over a non-git repo_root raises _Internal (no verdict)",
          True, _raised_internal)

# ORDERED_TOKENS unchanged (issue #1898 AC): compare the module's token set against its
# pre-change members, written down literally rather than derived from the module itself.
_EXPECTED_TOKENS_1898 = (
    'pass', 'missing-evidence', 'stale-candidate', 'verification-not-pass',
    'skipped-checks-present', 'undischarged-findings', 'non-durable-deferral',
    'unverifiable-trace',
)
assert_eq("#1898 ORDERED_TOKENS unchanged after the CI-record widening",
          _EXPECTED_TOKENS_1898, tuple(cce.ORDERED_TOKENS))
assert_eq("#1898 ALL_TOKENS unchanged after the CI-record widening",
          frozenset(_EXPECTED_TOKENS_1898), cce.ALL_TOKENS)

# ── workpad terminal-gate integration (real verdict) ─────────────────────────
_enc_ci = workpad._encode_ci_payload(_ci_rec())
workpad._completion_evidence_verdict = _REAL_COMPLETION_EVIDENCE_VERDICT
try:
    # The new operand shape (issue #1898): nargs-3 (HEAD_SHA, TIER, RUN_URL) plus one
    # --completion-ci-check NAME CONCLUSION pair per required check, covering the set.
    _ci_ok = [_ci_head, 'local', 'https://github.com/o/r/actions/runs/1']
    _ci_checks = [[_CI_REQUIRED_A, 'success'], [_CI_REQUIRED_B, 'success']]

    # Recording a valid CI marker, then finalizing, PATCHes once.
    _code, _out, _err, _patched = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence_ci=_ci_ok,
        completion_ci_check=_ci_checks, repo_root=_ci_root)
    assert_eq("#1611 Complete WITH a validated CI marker exits 0", None, _code)
    assert_eq("#1611 Complete with a valid CI marker PATCHes (🎉 Complete)", True,
              _patched is not None and '🎉 Complete' in _patched)
    assert_eq("#1611 exactly one completion-ci marker is written", 1,
              _patched.count('completion-ci:'))

    # Idempotent replay: re-finalize the recorded body keeps exactly one CI marker.
    _c2, _o2, _e2, _p2 = _drive_cmd_update(_patched, status='Complete', repo_root=_ci_root)
    assert_eq("#1611 replay: a second Complete over the CI marker exits 0", None, _c2)
    assert_eq("#1611 replay: still exactly one completion-ci marker", 1,
              _p2.count('completion-ci:'))

    # Recording a CI marker twice (no finalize) leaves exactly one row.
    _cA, _oA, _eA, _bA = _drive_cmd_update(
        GATE_BODY, record_completion_evidence_ci=_ci_ok,
        completion_ci_check=_ci_checks, repo_root=_ci_root)
    _cB, _oB, _eB, _bB = _drive_cmd_update(
        _bA, record_completion_evidence_ci=_ci_ok,
        completion_ci_check=_ci_checks, repo_root=_ci_root)
    assert_eq("#1611 recording a CI marker twice leaves exactly one row", 1,
              _bB.count('completion-ci:'))

    # A cloud tier aborts before PATCH (issue #1898), naming the tier.
    _cC, _oC, _eC, _pC = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_ci_root,
        record_completion_evidence_ci=[_ci_head, 'cloud', 'u'],
        completion_ci_check=_ci_checks)
    assert_eq("#1898 recording a cloud-tier CI record aborts (no PATCH)", None, _pC)
    assert_eq("#1898 the cloud-tier abort names the tier", True, 'cloud' in _eC)

    # A checks set missing a required member aborts before PATCH (issue #1898).
    _cU, _oU, _eU, _pU = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_ci_root,
        record_completion_evidence_ci=_ci_ok,
        completion_ci_check=[[_CI_REQUIRED_A, 'success']])  # lint absent
    assert_eq("#1898 recording a CI record that omits a required check aborts (no PATCH)",
              None, _pU)
    assert_eq("#1898 the uncovered-check abort names the missing check", True,
              _CI_REQUIRED_B in _eU)

    # SHA != HEAD aborts before PATCH (no PATCH), naming stale-candidate.
    _cS, _oS, _eS, _pS = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_ci_root,
        record_completion_evidence_ci=['b' * 40, 'local', 'u'],
        completion_ci_check=_ci_checks)
    assert_eq("#1611 recording a stale-SHA CI record aborts (no PATCH)", None, _pS)
    assert_eq("#1611 the stale-SHA abort names stale-candidate", True, 'stale-candidate' in _eS)

    # A dirty tree at record time aborts before PATCH.
    with open(os.path.join(_ci_root, 'f.txt'), 'a') as _fh:
        _fh.write('dirty2\n')
    _cD, _oD, _eD, _pD = _drive_cmd_update(
        GATE_BODY, status='Complete', record_completion_evidence_ci=_ci_ok,
        completion_ci_check=_ci_checks, repo_root=_ci_root)
    assert_eq("#1611 recording a CI record over a dirty tree aborts (no PATCH)", None, _pD)
    assert_eq("#1611 the dirty-tree abort names stale-candidate", True, 'stale-candidate' in _eD)
    _subprocess.run(['git', 'checkout', '--', 'f.txt'], cwd=_ci_root, check=True)

    # A non-success conclusion aborts before PATCH, naming verification-not-pass.
    _cF, _oF, _eF, _pF = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_ci_root,
        record_completion_evidence_ci=[_ci_head, 'local', 'u'],
        completion_ci_check=[[_CI_REQUIRED_A, 'failure'], [_CI_REQUIRED_B, 'success']])
    assert_eq("#1611 recording a failure-conclusion CI record aborts (no PATCH)", None, _pF)
    assert_eq("#1611 the failure abort names verification-not-pass", True,
              'verification-not-pass' in _eF)

    # A malformed SHA aborts before PATCH.
    _cM, _oM, _eM, _pM = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_ci_root,
        record_completion_evidence_ci=[_ci_head[:7], 'local', 'u'],
        completion_ci_check=_ci_checks)
    assert_eq("#1611 recording a malformed-SHA CI record aborts (no PATCH)", None, _pM)

    # ── cross-family combined-count via the verdict function directly ──────────
    def _mk():
        return make_args(repo_root=_ci_root)
    # zero markers of either family → missing-evidence refusal.
    try:
        workpad._completion_evidence_verdict(_mk(), "- [x] nothing here\n")
        _raised, _msg = False, ''
    except workpad._UpdateError as _e:
        _raised, _msg = True, str(_e)
    assert_eq("#1611 verdict: zero markers of either family → refuse (missing-evidence)",
              True, _raised and 'missing-evidence' in _msg)

    # one flight + one CI marker → multiple-marker refusal (counted across families).
    _pc_both = ('- [x] a <!-- prflow:checkpoint completion-verification:{} -->\n'
                '- [x] b <!-- prflow:checkpoint completion-ci:{} -->\n'.format('a' * 64, _enc_ci))
    try:
        workpad._completion_evidence_verdict(_mk(), _pc_both)
        _raised, _msg = False, ''
    except workpad._UpdateError as _e:
        _raised, _msg = True, str(_e)
    assert_eq("#1611 verdict: one flight + one CI → multiple-marker refusal",
              True, _raised and 'exactly one' in _msg)

    # two CI markers → multiple-marker refusal.
    _pc_two = (f'- [x] a <!-- prflow:checkpoint completion-ci:{_enc_ci} -->\n'
               f'- [x] b <!-- prflow:checkpoint completion-ci:{_enc_ci} -->\n')
    try:
        workpad._completion_evidence_verdict(_mk(), _pc_two)
        _raised = False
    except workpad._UpdateError:
        _raised = True
    assert_eq("#1611 verdict: two CI markers → multiple-marker refusal", True, _raised)

    # Standalone-copy / older-sibling arm: when the validator sibling is absent OR
    # lacks the CI entry point, a Complete over a CI marker fails closed with
    # missing-evidence and NO PATCH (the vendored-drift guard, CI-family analogue of
    # the #1087 flight arm).
    _saved_loader_ci = workpad._load_completion_validator
    workpad._load_completion_validator = lambda: None
    try:
        _cN, _oN, _eN, _pN = _drive_cmd_update(
            _bB, status='Complete', repo_root=_ci_root)  # _bB carries a CI marker
        assert_eq("#1611 standalone-copy Complete over a CI marker makes NO PATCH", None, _pN)
        assert_eq("#1611 standalone-copy CI arm names missing-evidence", True,
                  'missing-evidence' in _eN)
    finally:
        workpad._load_completion_validator = _saved_loader_ci
    # An older sibling present but lacking validate_implement_completion_ci also fails closed.
    class _StubNoCi:
        pass
    workpad._load_completion_validator = lambda: _StubNoCi()
    try:
        _cH, _oH, _eH, _pH = _drive_cmd_update(_bB, status='Complete', repo_root=_ci_root)
        assert_eq("#1611 sibling lacking the CI entry point makes NO PATCH", None, _pH)
        assert_eq("#1611 missing-CI-entry-point arm names missing-evidence", True,
                  'missing-evidence' in _eH)
    finally:
        workpad._load_completion_validator = _saved_loader_ci

    # Internal git-read failure at record time: a well-formed CI record over a NON-git
    # repo_root makes the validator raise _Internal, which _validate_ci_evidence catches
    # and converts to a no-PATCH _UpdateError (fail closed, no false Complete).
    _cI, _oI, _eI, _pI = _drive_cmd_update(
        GATE_BODY, status='Complete', repo_root=_nongit,
        record_completion_evidence_ci=['a' * 40, 'local', 'u'],
        completion_ci_check=_ci_checks)
    assert_eq("#1611 CI record over a non-git repo_root makes NO PATCH", None, _pI)
    assert_eq("#1611 the internal-error CI arm reports unestablished (no PATCH)", True,
              'internal error' in _eI or 'unestablished' in _eI)

    # Both marker spellings recognised for the CI family: a single valid marker in
    # either spelling validates to a clean pass (no raise).
    for _spell in ('prflow', 'devflow'):
        _pc_one = f'- [x] a <!-- {_spell}:checkpoint completion-ci:{_enc_ci} -->\n'
        try:
            workpad._completion_evidence_verdict(_mk(), _pc_one)
            _ok = True
        except workpad._UpdateError:
            _ok = False
        assert_eq(f"#1611 verdict: single valid {_spell}: CI marker → clean pass", True, _ok)
finally:
    workpad._completion_evidence_verdict = lambda args, prog_content: None


# ── issue #2131: --record-verification-evidence owns the Verification evidence row ──
# The record's field set now lives in the tool (not CLAUDE.md prose): a validated call
# appends one note-kind reflection row; a missing required field or an aggregate outcome
# recorded with run-root=none is refused before any PATCH; each launch adds its own row.
print("workpad --record-verification-evidence (issue #2131)")

# A valid call appends one `### ℹ️ Notes` row beginning `Verification evidence:` and
# carrying command=, outcome=, run-root=, recorded-at=, head=<40 hex from HEAD>.
_c, _o, _e, _p = _drive_cmd_update(
    WORKPAD_BODY, record_verification_evidence=True,
    command='lib/test/run-parallel.sh', outcome='run-parallel: aggregate CLEAN',
    run_root=['.prflow/tmp/parallel-suite/run-1-0/logs'],
    tallies='22835 passed / 0 failed / 0 skipped', elapsed='964s',
    started_at='2026-08-29T02:10:00Z', repo_root=_ci_root)
assert_eq("#2131 a valid verification-evidence call exits 0", None, _c)
assert_eq("#2131 the call PATCHes", True, _p is not None)
assert_eq("#2131 the row begins with the Verification evidence: literal", True,
          'Verification evidence:' in _p)
assert_eq("#2131 the row files under the Notes sub-section", True,
          '### ℹ️ Notes' in _p)
for _field in ('command=lib/test/run-parallel.sh',
               'outcome=run-parallel: aggregate CLEAN',
               'run-root=.prflow/tmp/parallel-suite/run-1-0/logs',
               'tallies=22835 passed / 0 failed / 0 skipped',
               'elapsed=964s', 'started-at=2026-08-29T02:10:00Z',
               'recorded-at=', f'head={_ci_head}'):
    assert_eq(f"#2131 the row carries {_field.split('=')[0]}=", True, _field in _p)

# The optional fields are omitted when not supplied (only the required + stamped set).
_c2, _o2, _e2, _p2 = _drive_cmd_update(
    WORKPAD_BODY, record_verification_evidence=True,
    command='lib/test/run-parallel.sh', outcome='ran',
    run_root=['/tmp/logs'], repo_root=_ci_root)
assert_eq("#2131 a minimal call PATCHes", True, _p2 is not None)
assert_eq("#2131 tallies omitted when unsupplied", False, 'tallies=' in _p2)
assert_eq("#2131 elapsed omitted when unsupplied", False, 'elapsed=' in _p2)
assert_eq("#2131 started-at omitted when unsupplied", False, 'started-at=' in _p2)

# Missing each required field in turn → no PATCH, named breadcrumb.
for _over, _flag in [({'outcome': 'x', 'run_root': ['r']}, '--command'),
                     ({'command': 'c', 'run_root': ['r']}, '--outcome'),
                     ({'command': 'c', 'outcome': 'x'}, '--run-root')]:
    _cM, _oM, _eM, _pM = _drive_cmd_update(
        WORKPAD_BODY, record_verification_evidence=True, repo_root=_ci_root, **_over)
    assert_eq(f"#2131 a call missing {_flag} makes NO PATCH", None, _pM)
    assert_eq(f"#2131 the missing-{_flag} refusal names it", True, _flag in _eM)

# An aggregate outcome with run-root=none is refused before any PATCH.
for _agg in ('run-parallel: aggregate CLEAN', 'run-parallel: aggregate FAILED (3)'):
    _cA, _oA, _eA, _pA = _drive_cmd_update(
        WORKPAD_BODY, record_verification_evidence=True,
        command='lib/test/run-parallel.sh', outcome=_agg, run_root=['none'],
        repo_root=_ci_root)
    assert_eq(f"#2131 aggregate outcome {_agg!r} with run-root=none makes NO PATCH",
              None, _pA)
    # Attribute the guard: the refusal must be the aggregate/run-root=none conflict,
    # not some other reachable refusal (all required fields are supplied here).
    assert_eq(f"#2131 the aggregate+none refusal for {_agg!r} names the conflict",
              True, 'aggregate' in _eA and 'run-root=none' in _eA)

# A run-root=none with a non-aggregate outcome records run-root=none verbatim, PATCHes.
_cN, _oN, _eN, _pN = _drive_cmd_update(
    WORKPAD_BODY, record_verification_evidence=True,
    command='lib/test/run-parallel.sh',
    outcome='refused by the matcher (no output)', run_root=['none'],
    repo_root=_ci_root)
assert_eq("#2131 a non-aggregate run-root=none call PATCHes", True, _pN is not None)
assert_eq("#2131 run-root=none recorded verbatim", True, 'run-root=none' in _pN)

# A second launch appends its own row rather than replacing the first.
_c3, _o3, _e3, _p3 = _drive_cmd_update(
    _p, record_verification_evidence=True, command='lib/test/run-parallel.sh',
    outcome='run-parallel: aggregate CLEAN', run_root=['/tmp/logs2'],
    repo_root=_ci_root)
assert_eq("#2131 a second launch keeps both rows", 2,
          _p3.count('Verification evidence:'))

# Two-root recombination (issue #2008): --run-root is repeatable, so a single call
# names BOTH retained roots as two run-root= fields, in order.
_cR, _oR, _eR, _pR = _drive_cmd_update(
    WORKPAD_BODY, record_verification_evidence=True,
    command='lib/test/run-shard.sh (recombined)', outcome='recombined CLEAN',
    run_root=['.prflow/tmp/parallel-suite/run-RED/logs',
              '.prflow/tmp/parallel-suite/run-FRESH/logs'],
    repo_root=_ci_root)
assert_eq("#2131 a two-root recombination call PATCHes", True, _pR is not None)
assert_eq("#2131 the two-root row names both roots in order", True,
          'run-root=.prflow/tmp/parallel-suite/run-RED/logs' in _pR
          and 'run-root=.prflow/tmp/parallel-suite/run-FRESH/logs' in _pR
          and _pR.index('run-root=.prflow/tmp/parallel-suite/run-RED/logs')
          < _pR.index('run-root=.prflow/tmp/parallel-suite/run-FRESH/logs'))
assert_eq("#2131 the two-root row emits exactly two run-root= fields", 2,
          _pR.count('run-root='))

# An EXPLICIT --record-verification-evidence call over a workpad LACKING the
# ## Devflow Reflection section is a hard refusal (no PATCH), distinct from the CI
# rider's best-effort degrade above — the explicit caller asked to record.
_cX, _oX, _eX, _pX = _drive_cmd_update(
    GATE_BODY, record_verification_evidence=True,
    command='lib/test/run-parallel.sh', outcome='ran', run_root=['/tmp/logs'],
    repo_root=_ci_root)
assert_eq("#2131 explicit record over a reflection-less workpad makes NO PATCH",
          None, _pX)
assert_eq("#2131 the reflection-less explicit refusal names the section",
          True, 'Devflow Reflection' in _eX)

# git-unavailable at record time stamps head=unestablished and still succeeds.
_cU, _oU, _eU, _pU = _drive_cmd_update(
    WORKPAD_BODY, record_verification_evidence=True,
    command='lib/test/run-parallel.sh', outcome='ran', run_root=['/tmp/logs'],
    repo_root=_nongit)
assert_eq("#2131 a verification-evidence call over a non-git root PATCHes", True,
          _pU is not None)
assert_eq("#2131 the non-git head is recorded unestablished", True,
          'head=unestablished' in _pU)

# The CI-evidence option, on a pass, ALSO appends one Verification evidence: row built
# from its validated operands (command=gh pr checks, outcome=name=conclusion pairs,
# run-root=run URL), so a local CI reading records with one call.
_ve_ci_ok = [_ci_head, 'local', 'https://github.com/o/r/actions/runs/9']
_ve_ci_checks = [[_CI_REQUIRED_A, 'success'], [_CI_REQUIRED_B, 'success']]
_GATE_BODY_REFL = GATE_BODY + '\n## Devflow Reflection\n'
workpad._completion_evidence_verdict = lambda args, prog_content: None
_cC, _oC, _eC, _pC = _drive_cmd_update(
    _GATE_BODY_REFL, record_completion_evidence_ci=_ve_ci_ok,
    completion_ci_check=_ve_ci_checks, repo_root=_ci_root)
assert_eq("#2131 a CI-evidence pass PATCHes", True, _pC is not None)

# A CI-evidence pass over a workpad LACKING the Devflow Reflection section still PATCHes
# the completion-ci marker (best-effort row append — no regression to the CI contract).
_cG, _oG, _eG, _pG = _drive_cmd_update(
    GATE_BODY, record_completion_evidence_ci=_ve_ci_ok,
    completion_ci_check=_ve_ci_checks, repo_root=_ci_root)
assert_eq("#2131 a CI pass over a reflection-less workpad still PATCHes", True,
          _pG is not None)
assert_eq("#2131 the reflection-less CI pass still records the completion-ci marker",
          True, 'completion-ci:' in _pG)
# The degradation is a breadcrumb, NOT a row: no Verification evidence row is appended
# into a body that has no ## Devflow Reflection section to hold it.
assert_eq("#2131 the reflection-less CI pass appends no Verification evidence row",
          False, 'Verification evidence:' in _pG)
assert_eq("#2131 the CI pass appends one Verification evidence: row", 1,
          _pC.count('Verification evidence:'))
assert_eq("#2131 the CI-derived row names the gh pr checks command", True,
          'command=gh pr checks' in _pC)
assert_eq("#2131 the CI-derived row's run-root is the run URL", True,
          'run-root=https://github.com/o/r/actions/runs/9' in _pC)
assert_eq("#2131 the CI-derived row names the checks and conclusions", True,
          f'{_CI_REQUIRED_A}=success' in _pC)


# ── issue #1898: the --context-mode direct/loop CI route reaches the SAME check ──
# The reception (direct) and fix-loop (loop) passes reach the CI validation through
# check-completion-evidence.py's own CLI, supplying a --ci-record. Drive cce.main(argv)
# and read its exit code + the single verdict line, exactly as the production caller does.
import contextlib as _ctx1898


def _write_json_1898(obj):
    _p = _tmp1087.mkstemp(suffix='.json')[1]
    with open(_p, 'w') as _fh:
        _fh.write(_json1087.dumps(obj))
    return _p


def _run_cce_1898(argv):
    _out = io.StringIO()
    _code = None
    try:
        with _ctx1898.redirect_stdout(_out), _ctx1898.redirect_stderr(io.StringIO()):
            _code = cce.main(argv)
    except SystemExit as _e:  # main() returns an int; guard against any raise-path too
        _code = _e.code
    return _code, _out.getvalue()


# The CI record file (a valid local-tier record covering the required set at HEAD).
_ci_record_path = _write_json_1898(_ci_rec())
# Session anchors bound to the claim context 'tok'. Direct requires the identity
# artifact and a non-empty findings list (its undischarged check is completeness-only).
_ident_path = _write_json_1898({'claim_context_token': 'tok'})
_fi_direct_path = _write_json_1898({'claim_context_token': 'tok',
                                    'findings': [{'finding_id': 'f1'}]})
# Loop needs only the findings inventory; this fixture routes no finding into the fix set.
_fi_loop_path = _write_json_1898({'claim_context_token': 'tok', 'findings': []})

# AC7: a --context-mode direct invocation with a valid CI record reaches `pass`.
_c, _o = _run_cce_1898([
    '--context-mode', 'direct', '--context', 'tok', '--ci-record', _ci_record_path,
    '--identity-artifact', _ident_path, '--findings-inventory', _fi_direct_path,
    '--repo-root', _ci_root])
assert_eq("#1898 direct route with a valid CI record exits 0", 0, _c)
assert_eq("#1898 direct route with a valid CI record → pass", True, 'completion-check: pass' in _o)

# AC7: the same holds for --context-mode loop.
_c, _o = _run_cce_1898([
    '--context-mode', 'loop', '--context', 'tok', '--ci-record', _ci_record_path,
    '--findings-inventory', _fi_loop_path, '--repo-root', _ci_root])
assert_eq("#1898 loop route with a valid CI record exits 0", 0, _c)
assert_eq("#1898 loop route with a valid CI record → pass", True, 'completion-check: pass' in _o)

# AC3: the tier refusals fire on the direct/loop routes too (a cloud tier → refused).
_cloud_record_path = _write_json_1898(_ci_rec(tier='cloud'))
_c, _o = _run_cce_1898([
    '--context-mode', 'direct', '--context', 'tok', '--ci-record', _cloud_record_path,
    '--identity-artifact', _ident_path, '--findings-inventory', _fi_direct_path,
    '--repo-root', _ci_root])
assert_eq("#1898 direct route refuses a cloud-tier CI record (exit 1)", 1, _c)
assert_eq("#1898 direct route cloud refusal is missing-evidence naming the tier", True,
          'missing-evidence' in _o and 'cloud' in _o)
# AC3: the same tier refusal fires on the loop route.
_c, _o = _run_cce_1898([
    '--context-mode', 'loop', '--context', 'tok', '--ci-record', _cloud_record_path,
    '--findings-inventory', _fi_loop_path, '--repo-root', _ci_root])
assert_eq("#1898 loop route refuses a cloud-tier CI record (exit 1)", 1, _c)
assert_eq("#1898 loop route cloud refusal is missing-evidence naming the tier", True,
          'missing-evidence' in _o and 'cloud' in _o)

# AC8: the undischarged-findings check still runs on the CI route — a direct session
# whose findings ledger records zero dispositions is refused even with a valid CI record.
_fi_empty_path = _write_json_1898({'claim_context_token': 'tok', 'findings': []})
_c, _o = _run_cce_1898([
    '--context-mode', 'direct', '--context', 'tok', '--ci-record', _ci_record_path,
    '--identity-artifact', _ident_path, '--findings-inventory', _fi_empty_path,
    '--repo-root', _ci_root])
assert_eq("#1898 direct route still refuses on undischarged findings (exit 1)", 1, _c)
assert_eq("#1898 the undischarged refusal names undischarged-findings", True,
          'undischarged-findings' in _o)

# AC8: the deferral-durability check still runs — a deferral with no durable channel is
# refused (non-durable-deferral) even with an otherwise-valid CI record.
_deferrals_path = _write_json_1898({'deferrals': [{'finding_id': 'd1'}]})
_c, _o = _run_cce_1898([
    '--context-mode', 'loop', '--context', 'tok', '--ci-record', _ci_record_path,
    '--findings-inventory', _fi_loop_path, '--deferrals', _deferrals_path,
    '--repo-root', _ci_root])
assert_eq("#1898 CI route still refuses a non-durable deferral (exit 1)", 1, _c)
assert_eq("#1898 the deferral refusal names non-durable-deferral", True,
          'non-durable-deferral' in _o)


# ─────────────────────────────────────────────────────────────────────────────
# focused_selection (issue #1229) — the named focused-first selection record
# producer/reader. AC2: writes a focused-selection record through the producer and
# reads it back, asserting per-surface entries survive intact and that three cases
# are distinguishable (a record naming one or more surfaces, a record naming no
# surface, and no record at all). AC3: the record holds both a discharging
# focused-result shape and an exemption-ground shape, distinguishably. AC4: the
# single-flight consultation round-trips in the same record.
# ─────────────────────────────────────────────────────────────────────────────
focused_selection = _load('focused_selection', SCRIPTS / 'focused_selection.py')
import json as _json1229

# A record naming one or more surfaces, mixing both entry shapes (AC3): one a
# discharging focused result, one an exemption ground.
_rec_surfaces = focused_selection.build_record(
    surfaces=[
        {"surface": "scripts/foo.py", "coverage_map_entry": "test_python_scripts.py::Foo",
         "target": "lib/test/test_python_scripts.py Foo.test_bar"},
        {"surface": "docs/thing.md", "exemption_ground": "no-coverage-map-entry"},
    ],
    single_flight_consulted={"flight_key": "abc123", "reused_clean_result": True},
)

# JSON round-trip (the standalone-fix-loop sink embeds this dict as
# verification_evidence.focused_selection — a plain JSON value).
assert_eq("#1229 record is JSON round-trippable (standalone verification_evidence sink)",
          _rec_surfaces, _json1229.loads(_json1229.dumps(_rec_surfaces)))

# Marker round-trip (the implement workpad sink carries it as a named marker note).
_body_surfaces = "## Progress\n- [x] step\n  - 01:02:03 — " + \
    focused_selection.encode_marker(_rec_surfaces) + "\n"
_decoded = focused_selection.decode_markers(_body_surfaces)
assert_eq("#1229 marker round-trip: exactly one record decoded", 1, len(_decoded))
assert_eq("#1229 marker round-trip: per-surface entries survive intact",
          _rec_surfaces, _decoded[0])

# AC3: both entry shapes survive and are distinguishable from each other.
_entries = _decoded[0]["surfaces"]
assert_eq("#1229 focused-result entry classified as focused-result", "focused-result",
          focused_selection.classify_entry(_entries[0]))
assert_eq("#1229 exemption entry classified as exemption", "exemption",
          focused_selection.classify_entry(_entries[1]))

# AC4: the single-flight consultation round-trips in the same record.
assert_eq("#1229 single-flight consultation survives the round-trip",
          {"flight_key": "abc123", "reused_clean_result": True},
          _decoded[0]["single_flight_consulted"])

# Case 2: a record naming NO surface — a real record whose surfaces list is empty.
_rec_none = focused_selection.build_record(surfaces=[], single_flight_consulted=None)
_body_none = "note carrying " + focused_selection.encode_marker(_rec_none)
_decoded_none = focused_selection.decode_markers(_body_none)
assert_eq("#1229 no-surface case: still one record decoded", 1, len(_decoded_none))
assert_eq("#1229 no-surface case: surfaces list is empty", [], _decoded_none[0]["surfaces"])
assert_eq("#1229 no-surface case: single_flight_consulted is null", None,
          _decoded_none[0]["single_flight_consulted"])

# Case 3: NO record at all — decoding text with no marker yields the empty list,
# distinguishable from case 2 (which yields one record with an empty surfaces list).
assert_eq("#1229 no-record case: no markers decode to the empty list", [],
          focused_selection.decode_markers("## Progress\n- [x] a plain note, no marker\n"))
assert_eq("#1229 three cases distinguishable: no-surface record != no record at all",
          True, len(_decoded_none) == 1 and len(focused_selection.decode_markers("")) == 0)

# A malformed surface entry (neither a focused result nor an exemption) is rejected
# at build time — the record cannot silently carry an unclassifiable surface.
assert_raises("#1229 build_record rejects an unclassifiable surface entry",
              ValueError,
              lambda: focused_selection.build_record(
                  surfaces=[{"surface": "scripts/x.py"}], single_flight_consulted=None))

# An entry carrying BOTH a focused result and an exemption ground is ambiguous and
# rejected — the whole point of the record is that the two shapes stay distinct.
assert_raises("#1229 build_record rejects an ambiguously-both surface entry",
              ValueError,
              lambda: focused_selection.build_record(
                  surfaces=[{"surface": "s", "coverage_map_entry": "e", "target": "t",
                             "exemption_ground": "x"}], single_flight_consulted=None))

# A surface entry that names no `surface` is rejected.
assert_raises("#1229 build_record rejects an entry with no surface name",
              ValueError,
              lambda: focused_selection.build_record(
                  surfaces=[{"exemption_ground": "x"}], single_flight_consulted=None))

# A non-list `surfaces` argument is rejected.
assert_raises("#1229 build_record rejects a non-list surfaces argument",
              ValueError,
              lambda: focused_selection.build_record(
                  surfaces="not-a-list", single_flight_consulted=None))

# The load-bearing fail-closed decode path: a malformed marker payload is skipped,
# never surfaced as a spurious record. The payload is agent/human-mutable, so a
# regression here (e.g. dropping validate=True, or letting a JSON array/scalar
# through) would fail OPEN — a surface reads as recorded when it is not.
_bad_b64 = "<!-- prflow:focused-selection !!!not-base64!!! -->"
assert_eq("#1229 decode fails closed on non-base64 payload", [],
          focused_selection.decode_markers(_bad_b64))
import base64 as _b641229

_b64_nonjson = "<!-- prflow:focused-selection " + \
    _b641229.b64encode(b"not json at all").decode("ascii") + " -->"
assert_eq("#1229 decode fails closed on a payload that is valid base64 but not JSON",
          [], focused_selection.decode_markers(_b64_nonjson))
_b64_array = "<!-- prflow:focused-selection " + \
    _b641229.b64encode(b"[1,2,3]").decode("ascii") + " -->"
assert_eq("#1229 decode fails closed on a JSON array/scalar payload (non-object)", [],
          focused_selection.decode_markers(_b64_array))

# Multiple markers in one body decode to multiple records in document order.
_rec_a = focused_selection.build_record(
    surfaces=[{"surface": "a", "exemption_ground": "no-coverage-map-entry"}],
    single_flight_consulted=None)
_rec_b = focused_selection.build_record(
    surfaces=[{"surface": "b", "coverage_map_entry": "e", "target": "t"}],
    single_flight_consulted=None)
_multi = "x " + focused_selection.encode_marker(_rec_a) + \
    "\ny " + focused_selection.encode_marker(_rec_b) + "\n"
_dm = focused_selection.decode_markers(_multi)
assert_eq("#1229 two markers in one body both decode", 2, len(_dm))
assert_eq("#1229 two markers decode in document order", [_rec_a, _rec_b], _dm)

# ─────────────────────────────────────────────────────────────────────────────
# focused_selection's CLI surface (issue #1229) — `main` / `_build_parser` /
# `_cmd_encode` / `_cmd_decode`. The CLI is the shape an agent actually invokes to
# produce or read a marker (it cannot import the module), and the library
# assertions above cannot see it: a dropped `required=True` on the subparser, a
# mis-wired `set_defaults(func=…)`, or a reordered `build_record(...)` call inside
# `_cmd_encode` would leave every assertion above green while the CLI stopped
# emitting valid markers. Each command is therefore driven as invoked — through
# `main(argv)` with stdin fed and stdout captured.
# ─────────────────────────────────────────────────────────────────────────────
def _fs_cli(argv, stdin_text=""):
    """Run `focused_selection.main(argv)` with stdin fed from `stdin_text`; returns
    `(rc, stdout)`. A `SystemExit` the CLI raises propagates to the caller (stdin is
    restored either way), so the rejection arms are asserted with `assert_raises`."""
    _saved_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    _cli_out = io.StringIO()
    try:
        with contextlib.redirect_stdout(_cli_out), contextlib.redirect_stderr(io.StringIO()):
            _rc = focused_selection.main(argv)
    finally:
        sys.stdin = _saved_stdin
    return _rc, _cli_out.getvalue()


def _fs_cli_exit_code(argv, stdin_text=""):
    """The `SystemExit.code` a rejecting CLI invocation carries (None if it did not
    exit). A message string here — rather than a bare int or an escaped traceback —
    is what distinguishes a handled rejection from an unhandled exception."""
    try:
        _fs_cli(argv, stdin_text)
    except SystemExit as e:
        return e.code
    return None


def _fs_cli_ok(argv, stdin_text=""):
    """`_fs_cli` for an invocation expected to succeed: a `SystemExit` is converted
    into a non-zero-shaped return so the assertion below reports a FAIL rather than
    aborting this file mid-run (a regression that made `encode` reject its own valid
    payload would otherwise take the summary line with it)."""
    try:
        return _fs_cli(argv, stdin_text)
    except SystemExit as e:
        return (f"unexpected SystemExit: {e.code}", "")


def _fs_cli_json(text):
    """Parse a CLI stdout capture as JSON, returning the raw text on a parse failure
    so the comparison reports a FAIL instead of raising out of this file."""
    try:
        return _json1229.loads(text)
    except ValueError:
        return text


# The subparser is `required=True`: invoking the CLI with no subcommand is a hard
# argparse error, never a run that reaches `args.func` and dies on an AttributeError.
assert_raises("#1229 CLI: no subcommand is a hard error (subparser stays required)",
              SystemExit, lambda: _fs_cli([]))
assert_raises("#1229 CLI: an unknown subcommand is a hard error",
              SystemExit, lambda: _fs_cli(["nosuchcommand"]))

# `encode` is wired to `_cmd_encode` and passes stdin's fields to `build_record` in
# the right order: `surfaces` first, `single_flight_consulted` second. A swap makes
# the dict arrive as `surfaces` (rejected) or the list as the consultation record —
# so this asserts the decoded record, not merely that something was printed.
_cli_surfaces = [
    {"surface": "scripts/foo.py", "coverage_map_entry": "coverage-map.json::scripts/foo.py",
     "target": "lib/test/test_python_scripts.py Foo.test_bar"},
    {"surface": "docs/thing.md", "exemption_ground": "no-coverage-map-entry"},
]
_cli_flight = {"flight_key": "deadbeef", "reused_clean_result": True}
_cli_payload = _json1229.dumps({"surfaces": _cli_surfaces,
                                "single_flight_consulted": _cli_flight})
_rc_enc, _out_enc = _fs_cli_ok(["encode"], _cli_payload)
assert_eq("#1229 CLI encode returns 0", 0, _rc_enc)
assert_eq("#1229 CLI encode emits exactly one marker line", 1,
          len([ln for ln in _out_enc.split("\n") if ln.strip()]))
assert_eq("#1229 CLI encode emits the same marker the producer API does",
          focused_selection.encode_marker(
              focused_selection.build_record(_cli_surfaces, _cli_flight)) + "\n",
          _out_enc)

# End-to-end: the marker `encode` printed is read back by `decode` — the round-trip
# an agent performs across two separate invocations, with the marker embedded in a
# workpad-shaped note body exactly as the sink stores it.
_rc_dec, _out_dec = _fs_cli_ok(
    ["decode"], "## Progress\n- [x] step\n  - 01:02:03 — " + _out_enc.strip() + "\n")
assert_eq("#1229 CLI decode returns 0", 0, _rc_dec)
_cli_decoded = _fs_cli_json(_out_dec)
assert_eq("#1229 CLI encode|decode round-trip yields exactly one record",
          1, len(_cli_decoded))
assert_eq("#1229 CLI encode|decode round-trip: the record survives intact",
          [focused_selection.build_record(_cli_surfaces, _cli_flight)], _cli_decoded)

# `decode` is wired to `_cmd_decode`, not to the encoder: text carrying no marker
# prints the empty JSON array (the "no record at all" case) and exits 0.
_rc_d0, _out_d0 = _fs_cli_ok(["decode"], "a plain note, no marker at all\n")
assert_eq("#1229 CLI decode returns 0 on text carrying no marker", 0, _rc_d0)
assert_eq("#1229 CLI decode prints the empty JSON array when no marker is present",
          [], _fs_cli_json(_out_d0))

# The non-object stdin guard: a JSON array/scalar is a clean SystemExit, never a
# record built from a payload that names no surfaces.
assert_raises("#1229 CLI encode rejects a non-object stdin payload", SystemExit,
              lambda: _fs_cli(["encode"], "[1,2,3]"))
assert_eq("#1229 CLI encode's non-object rejection carries a message, not a bare code",
          True, isinstance(_fs_cli_exit_code(["encode"], "[1,2,3]"), str))

# Unparseable stdin and an unclassifiable surface entry exit the same handled way
# rather than escaping as a raw traceback.
assert_raises("#1229 CLI encode rejects unparseable stdin", SystemExit,
              lambda: _fs_cli(["encode"], "{not json"))
assert_eq("#1229 CLI encode's unparseable-stdin rejection carries a message",
          True, isinstance(_fs_cli_exit_code(["encode"], "{not json"), str))
_cli_bad_entry = _json1229.dumps({"surfaces": [{"surface": "scripts/x.py"}]})
assert_raises("#1229 CLI encode rejects an unclassifiable surface entry", SystemExit,
              lambda: _fs_cli(["encode"], _cli_bad_entry))
assert_eq("#1229 CLI encode's unclassifiable-entry rejection carries a message",
          True, isinstance(_fs_cli_exit_code(["encode"], _cli_bad_entry), str))

# ─────────────────────────────────────────────────────────────────────────────
# focused_selection's READ-path shape check (issue #1229 review finding 1). The
# producer is strict — `build_record` forces `surfaces` to a list, classifies every
# entry, and always emits both top-level keys — so a reader that validated only
# object-ness was fail-OPEN against it: a payload decoding to `{}`, to
# `{"surfaces": "not-a-list"}`, or to an object with no `surfaces` key was surfaced
# as a "record", and a downstream `rec["surfaces"]` would KeyError while
# `rec.get("single_flight_consulted")` conflated "producer recorded null" with "not a
# real record". `record_shape_error` validates WITHOUT normalizing (routing a decoded
# object through `build_record` would rewrite it, making the read path lossy), and
# `decode_marker_outcomes` keeps a rejected marker distinguishable from an absent one.
# ─────────────────────────────────────────────────────────────────────────────
def _fs_marker(payload_obj):
    """The marker literal carrying `payload_obj` as its base64 JSON payload — the
    encoder's own wire format, reached without going through `build_record`, so a
    wrong-shape payload can be planted exactly as a corrupted/foreign marker would
    arrive in a workpad."""
    return "<!-- prflow:focused-selection " + _b641229.b64encode(
        _json1229.dumps(payload_obj).encode("utf-8")).decode("ascii") + " -->"


# A reader must REJECT a wrong-shape payload, never raise out of it: a `surfaces`
# that is a number is not iterable, so a checker that dropped the list-ness test would
# crash its caller rather than reject the record. These wrappers turn such an escape
# into a reportable FAIL instead of aborting this file mid-run.
_FS_RAISED = "<<raised>>"


def _fs_guard(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return f"{_FS_RAISED} {type(e).__name__}: {e}"


def _fs_rejected(obj):
    """True when `record_shape_error` rejected `obj` by RETURNING a reason (an
    exception that escaped is not a rejection — it is the crash a rejection prevents)."""
    r = _fs_guard(focused_selection.record_shape_error, obj)
    return isinstance(r, str) and not r.startswith(_FS_RAISED)


# A well-shaped record passes the check, and passes it unchanged: validation must not
# normalize (a returned record is the producer's bytes, not a rebuild of them).
assert_eq("#1229 record_shape_error accepts a record the producer built",
          None, focused_selection.record_shape_error(_rec_surfaces))
assert_eq("#1229 decode returns the producer's record byte-for-byte (no normalizing)",
          _rec_surfaces,
          focused_selection.decode_markers(_fs_marker(_rec_surfaces))[0])

# The wrong shapes named in the finding, each rejected rather than surfaced. The
# `surfaces` rows span both iterable and non-iterable wrong types on purpose: a string
# would be walked entry-by-entry and rejected incidentally, a number cannot be walked
# at all, so only the second discriminates the list-ness check from its absence.
_fs_wrong_shapes = [
    ("empty object", {}),
    ("surfaces is a string, not a list", {"surfaces": "not-a-list",
                                          "single_flight_consulted": None}),
    ("surfaces is a number, not a list", {"surfaces": 5,
                                          "single_flight_consulted": None}),
    ("surfaces is null, not a list", {"surfaces": None,
                                      "single_flight_consulted": None}),
    ("surfaces is an object, not a list", {"surfaces": {"scripts/x.py": "t"},
                                           "single_flight_consulted": None}),
    ("no surfaces key", {"single_flight_consulted": None}),
    ("no single_flight_consulted key", {"surfaces": []}),
    ("an unclassifiable surfaces entry",
     {"surfaces": [{"surface": "scripts/x.py"}], "single_flight_consulted": None}),
    ("a non-dict surfaces entry", {"surfaces": ["just a string"],
                                   "single_flight_consulted": None}),
]
for _label, _shape in _fs_wrong_shapes:
    assert_eq(f"#1229 record_shape_error rejects {_label} (returns a reason)",
              True, _fs_rejected(_shape))
    assert_eq(f"#1229 decode_markers surfaces no record for {_label}",
              [], _fs_guard(focused_selection.decode_markers, _fs_marker(_shape)))
    _fs_out = _fs_guard(focused_selection.decode_marker_outcomes, _fs_marker(_shape))
    assert_eq(f"#1229 {_label}: reported as exactly one malformed outcome",
              ["malformed"],
              [o["status"] for o in _fs_out] if isinstance(_fs_out, list) else _fs_out)
    assert_eq(f"#1229 {_label}: the malformed outcome names a reason", True,
              isinstance(_fs_out, list) and len(_fs_out) == 1
              and isinstance(_fs_out[0]["reason"], str) and bool(_fs_out[0]["reason"]))

# The reason is the operator-facing half of the outcome (the CLI breadcrumbs it), so a
# wrong-typed `surfaces` is diagnosed as such rather than as an entry-level defect.
assert_eq("#1229 a wrong-typed `surfaces` is diagnosed as not being a list", True,
          "not a list" in (focused_selection.record_shape_error(
              {"surfaces": "not-a-list", "single_flight_consulted": None}) or ""))

# Unknown is not zero: a marker that was PRESENT but rejected is distinguishable from
# text that carried no marker at all, and both from a record whose producer recorded a
# null `single_flight_consulted`. Collapsing any pair of these is the fail-open bug.
assert_eq("#1229 no marker at all yields no outcome (distinct from a rejected marker)",
          [], focused_selection.decode_marker_outcomes("a plain note, no marker\n"))
assert_eq("#1229 a rejected marker is an outcome; an absent one is not",
          True,
          len(focused_selection.decode_marker_outcomes(_fs_marker({}))) == 1
          and len(focused_selection.decode_marker_outcomes("")) == 0)
_fs_null_flight = focused_selection.decode_marker_outcomes(
    focused_selection.encode_marker(_rec_none))
assert_eq("#1229 producer-recorded null is a record outcome, not a malformed one",
          ["record"], [o["status"] for o in _fs_null_flight])
assert_eq("#1229 producer-recorded null is readable as null, not as an absent key",
          True,
          "single_flight_consulted" in _fs_null_flight[0]["record"]
          and _fs_null_flight[0]["record"]["single_flight_consulted"] is None)

# Every record `decode_markers` returns is indexable — the guarantee the finding
# asked for, asserted against a body mixing a good marker with a wrong-shape one.
_fs_mixed = ("head " + focused_selection.encode_marker(_rec_surfaces)
             + "\nmiddle " + _fs_marker({"surfaces": "not-a-list"})
             + "\ntail " + focused_selection.encode_marker(_rec_none) + "\n")
assert_eq("#1229 mixed body: only the well-shaped records are returned", 2,
          len(focused_selection.decode_markers(_fs_mixed)))
assert_eq("#1229 mixed body: every returned record is safely indexable", True,
          all(isinstance(r["surfaces"], list) and "single_flight_consulted" in r
              for r in focused_selection.decode_markers(_fs_mixed)))
assert_eq("#1229 mixed body: outcomes keep all three markers in document order",
          ["record", "malformed", "record"],
          [o["status"] for o in focused_selection.decode_marker_outcomes(_fs_mixed)])

# Forward compatibility, deliberately asymmetric with the strict producer path below:
# a record written by a LATER producer that records an extra field still reads back
# (rejecting it would lose an otherwise entirely valid record already in a consumer's
# workpad), while `encode` rejects the same unknown key at composition time.
_fs_future = dict(_rec_surfaces, some_later_field="written by a newer producer")
assert_eq("#1229 read path tolerates an unknown top-level key (forward compatible)",
          None, focused_selection.record_shape_error(_fs_future))
assert_eq("#1229 read path returns such a record intact",
          [_fs_future], focused_selection.decode_markers(_fs_marker(_fs_future)))

# The CLI's decode surface: stdout stays the records array, and a rejected marker is
# breadcrumbed to stderr rather than vanishing (on stdout alone it would be
# indistinguishable from no marker at all). Reading stays exit 0.
def _fs_cli_streams(argv, stdin_text=""):
    """`(rc, stdout, stderr)` for a CLI invocation — the stderr capture `_fs_cli`
    discards, needed to assert the malformed-marker breadcrumb."""
    _saved_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    _o, _e = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(_o), contextlib.redirect_stderr(_e):
            _rc = focused_selection.main(argv)
    except SystemExit as exc:
        return (f"unexpected SystemExit: {exc.code}", _o.getvalue(), _e.getvalue())
    finally:
        sys.stdin = _saved_stdin
    return _rc, _o.getvalue(), _e.getvalue()


_rc_bad, _out_bad, _err_bad = _fs_cli_streams(["decode"], _fs_marker({}) + "\n")
assert_eq("#1229 CLI decode returns 0 on a wrong-shape marker", 0, _rc_bad)
assert_eq("#1229 CLI decode prints no record for a wrong-shape marker",
          [], _fs_cli_json(_out_bad))
assert_eq("#1229 CLI decode breadcrumbs the rejected marker to stderr",
          True, "malformed marker" in _err_bad)
_rc_ok2, _out_ok2, _err_ok2 = _fs_cli_streams(
    ["decode"], focused_selection.encode_marker(_rec_surfaces) + "\n")
assert_eq("#1229 CLI decode emits no breadcrumb for a well-shaped marker",
          "", _err_ok2)
assert_eq("#1229 CLI decode still prints the record for a well-shaped marker",
          [_rec_surfaces], _fs_cli_json(_out_ok2))

# ─────────────────────────────────────────────────────────────────────────────
# focused_selection's WRITE-path strictness (issue #1229 review finding 2). `encode`
# pulled `surfaces` and `single_flight_consulted` by name and ignored every other
# top-level key, so `{}` and a typo'd key both exited 0 with a valid-looking marker
# for an empty/unconsulted record — making a followed rule and an ignored one
# indistinguishable on exactly the producer path whose purpose is distinguishable
# traces. Unknown keys and a MISSING `surfaces` are now loud rejections;
# `single_flight_consulted` stays optional (its absence and an explicit null mean the
# same recorded thing, and `build_record` emits the key either way).
# ─────────────────────────────────────────────────────────────────────────────
_fs_encode_rejects = [
    ("an empty object", {}),
    ("a typo'd `surfaces` key", {"surfacs": [], "single_flight_consulted": None}),
    ("a typo'd `single_flight_consulted` key",
     {"surfaces": [], "single_flight_consulted_": {"flight_key": "x"}}),
    ("an unrecognized extra key alongside valid ones",
     {"surfaces": [], "single_flight_consulted": None, "launch_count": 3}),
]
for _label, _payload in _fs_encode_rejects:
    _text = _json1229.dumps(_payload)
    assert_raises(f"#1229 CLI encode rejects {_label}", SystemExit,
                  lambda t=_text: _fs_cli(["encode"], t))
    assert_eq(f"#1229 CLI encode's rejection of {_label} carries a one-line message",
              True, isinstance(_fs_cli_exit_code(["encode"], _text), str))

# The rejection is loud, never a marker: nothing is printed on the refused paths.
assert_eq("#1229 CLI encode prints no marker when it rejects an empty object",
          "", _fs_cli_streams(["encode"], "{}")[1])

# An empty record must SAY so — `{"surfaces": []}` is accepted and is the only way to
# produce one, so "nothing was selected" and "the producer was called wrong" are not
# the same bytes.
_rc_empty, _out_empty = _fs_cli_ok(["encode"], _json1229.dumps({"surfaces": []}))
assert_eq("#1229 CLI encode accepts an explicit empty `surfaces` list", 0, _rc_empty)
assert_eq("#1229 CLI encode's explicit-empty record is the producer's own record",
          focused_selection.encode_marker(
              focused_selection.build_record([], None)) + "\n",
          _out_empty)
assert_eq("#1229 an explicitly-empty record and a refused `{}` are not the same bytes",
          True, _out_empty.strip() != "" and isinstance(
              _fs_cli_exit_code(["encode"], "{}"), str))

# `single_flight_consulted` stays optional: omitting it still encodes, and the key is
# present-and-null in the result (so a reader tests its value, never its presence).
_rc_opt, _out_opt = _fs_cli_ok(
    ["encode"], _json1229.dumps({"surfaces": [{"surface": "a",
                                               "exemption_ground": "g"}]}))
assert_eq("#1229 CLI encode still accepts an omitted `single_flight_consulted`",
          0, _rc_opt)
assert_eq("#1229 an omitted `single_flight_consulted` encodes as a present null", True,
          "single_flight_consulted" in focused_selection.decode_markers(_out_opt)[0]
          and focused_selection.decode_markers(_out_opt)[0][
              "single_flight_consulted"] is None)


# ── scripts/prompt-surface-growth.py — the PR-description growth table (#1350) ─────────
# Every assertion below drives the REAL CLI over a REAL committed git history and reads
# its process stdout. Two reasons that shape is load-bearing rather than incidental:
# the helper's whole contract is its stdout (a table, or a stated breadcrumb, always
# exit 0), and an assertion against a file's `read_text()` would be an issue-#810
# source-presence pin needing a declaration — a process-stdout assertion is an ordinary
# behavioural test. The helper is invoked as a direct executable path, never as
# `python3 <path>`: that interpreter-head shape is the one the cloud matcher denies, so
# exercising the shebang and the index exec bit here is what keeps the shipped
# invocation form honest.
_PSG1350 = str(SCRIPTS / 'prompt-surface-growth.py')


def _psg_git1350(cwd, *args):
    proc = _subprocess.run(('git',) + args, cwd=cwd, capture_output=True, text=True)
    # A failed fixture `git` must announce itself here. Left unchecked it surfaces
    # much later as a mismatched table, sending the reader after the code under test
    # instead of the host's git config.
    if proc.returncode != 0 and args[0] in ('init', 'add', 'commit', 'checkout'):
        raise AssertionError(
            f"#1350 fixture git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc


def _psg_write1350(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _psg_run1350(cwd):
    """(rc, stdout) from the helper invoked as a direct leading token."""
    proc = _subprocess.run([_PSG1350], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _psg_base1350(root):
    """A committed baseline on `main`: three covered files plus two excluded ones.

    Covered bytes at base = 6 + 5 + 6 = 17. `docs/outside.md` is tracked markdown
    OUTSIDE all three covered prefixes, and `SKILL.md.example` is inside a covered
    prefix but is not a `.md` file — together they are the negative control for AC2.
    """
    _psg_git1350(root, 'init', '-q', '-b', 'main')
    _psg_git1350(root, 'config', 'user.email', 'a@b.c')
    _psg_git1350(root, 'config', 'user.name', 'T')
    # Signing off, matching every other git fixture in this suite: a maintainer whose
    # global config signs commits would otherwise fail these assertions for a reason
    # that has nothing to do with the code under test.
    _psg_git1350(root, 'config', 'commit.gpgsign', 'false')
    _psg_write1350(root, 'skills/alpha/SKILL.md', 'alpha\n')                 # 6
    _psg_write1350(root, 'agents/beta.md', 'beta\n')                         # 5
    _psg_write1350(root, '.prflow/prompt-extensions/gamma.md', 'gamma\n')    # 6
    _psg_write1350(root, 'docs/outside.md', 'outside\n')                     # excluded
    _psg_write1350(root, 'skills/delta/SKILL.md.example', 'ex\n')            # excluded
    _psg_git1350(root, 'add', '-A')
    _psg_git1350(root, 'commit', '-qm', 'base')


def _psg_branch1350(root, name, mutate):
    """Return to `main`, cut branch `name` off it, apply `mutate`, commit, run the helper.

    Returning to `main` first is what lets every scenario below share ONE baseline
    repo: each branches from the same commit, so the baseline's five files and its
    `git init`/`config`/`add`/`commit` are paid once rather than once per scenario.
    """
    _psg_git1350(root, 'checkout', '-q', 'main')
    _psg_git1350(root, 'checkout', '-q', '-b', name)
    mutate(root)
    _psg_git1350(root, 'add', '-A')
    _psg_git1350(root, 'commit', '-qm', name)
    return _psg_run1350(root)


def _psg_rows1350(out):
    """Every `| ... |` row of the rendered table, header/separator excluded."""
    return [ln for ln in out.splitlines()
            if ln.startswith('|') and '---' not in ln and 'Δ bytes' not in ln]


# One baseline repo serves every scenario that branches off it: each `_psg_branch1350`
# call returns to `main` and cuts its own branch, so the baseline's `git init`/`config`/
# `add`/`commit` is paid once here instead of once per scenario. Only the unresolvable-
# merge-base case below needs a repo of its own, because its whole point is a repository
# whose `main` does not exist.
with tempfile.TemporaryDirectory(prefix='psg1350-') as _R1350:
    _psg_base1350(_R1350)

    # ── AC1a(i): HEAD is the merge-base (the checkout-pinned-to-default-branch case) ──
    # Runs first, while the checkout is still sitting on the baseline commit.
    _rc1350e, _out1350e = _psg_run1350(_R1350)
    assert_eq("#1350 a checkout sitting on the merge-base exits 0", 0, _rc1350e)
    assert_eq("#1350 HEAD == merge-base prints its own stated breadcrumb and no table",
              [True, False],
              ['is the merge-base with' in _out1350e, '| ---' in _out1350e])

    # ── AC1 / T1: bytes added to one covered file ────────────────────────────────────
    def _psg_mut_add1350(root):
        _psg_write1350(root, 'skills/alpha/SKILL.md', 'alpha\nmore\n')       # 6 -> 11

    _rc1350a, _out1350a = _psg_branch1350(_R1350, 'grow', _psg_mut_add1350)
    assert_eq("#1350 a covered file gaining bytes exits 0", 0, _rc1350a)
    assert_eq("#1350 the growth table renders its own section heading",
              True, _out1350a.startswith('### Prompt-surface size'))
    assert_eq("#1350 the changed covered file's row carries the before-size, the size at "
              "HEAD, the delta and the delta as a percentage of the before-size — a "
              "reader cannot judge a delta's size from the delta alone",
              ['| `skills/alpha/SKILL.md` | 6 | 11 | +5 | +83.3% |',
               '| **Whole covered surface** | **17** | **22** | **+5** | **+29.4%** |'],
              _psg_rows1350(_out1350a))
    _head1350a = _psg_git1350(_R1350, 'rev-parse', 'HEAD').stdout.strip()
    assert_eq("#1350 the output carries the HEAD sha it was derived at, so a later "
              "commit makes the figure visibly self-dating rather than silently stale",
              True, _head1350a in _out1350a)

    # ── AC1 / T1: a covered file the branch DELETES ──────────────────────────────────
    def _psg_mut_del1350(root):
        (Path(root) / 'agents' / 'beta.md').unlink()

    _rc1350b, _out1350b = _psg_branch1350(_R1350, 'drop', _psg_mut_del1350)
    assert_eq("#1350 a deleted covered file exits 0", 0, _rc1350b)
    assert_eq("#1350 a covered file the branch deletes renders a row with total 0 and a "
              "negative delta (enumeration is from the committed tree at EITHER endpoint)",
              ['| `agents/beta.md` | 5 | 0 | -5 | -100.0% |',
               '| **Whole covered surface** | **17** | **12** | **-5** | **-29.4%** |'],
              _psg_rows1350(_out1350b))

    # ── AC1 / T1: a NEW covered file the branch adds ─────────────────────────────────
    def _psg_mut_new1350(root):
        _psg_write1350(root, 'skills/omega/SKILL.md', 'om\n')                # new, 3

    _rc1350c, _out1350c = _psg_branch1350(_R1350, 'birth', _psg_mut_new1350)
    assert_eq("#1350 a newly added covered file exits 0", 0, _rc1350c)
    assert_eq("#1350 a newly added covered file renders its full size as the delta, and "
              "`n/a` as the percentage — a zero before-size has no percentage, and "
              "rendering 100% would fabricate one",
              ['| `skills/omega/SKILL.md` | 0 | 3 | +3 | n/a |',
               '| **Whole covered surface** | **17** | **20** | **+3** | **+17.6%** |'],
              _psg_rows1350(_out1350c))

    # ── AC1a(ii) / T2 / AC2: a branch touching only paths OUTSIDE the population ──────
    def _psg_mut_outside1350(root):
        _psg_write1350(root, 'docs/outside.md', 'outside\nchanged\n')
        _psg_write1350(root, 'skills/delta/SKILL.md.example', 'ex\nchanged\n')

    _rc1350d, _out1350d = _psg_branch1350(_R1350, 'outside', _psg_mut_outside1350)
    assert_eq("#1350 a branch touching no covered path still exits 0", 0, _rc1350d)
    assert_eq("#1350 a tracked .md outside the covered prefixes, and a .md.example "
              "inside one, are BOTH absent from the output (AC2's population test)",
              [False, False],
              ['docs/outside.md' in _out1350d, 'SKILL.md.example' in _out1350d])
    assert_eq("#1350 the no-covered-change arm prints a stated one-line breadcrumb and "
              "NO table — a table of zeros would read as 'this PR added nothing'",
              [True, False],
              ['no tracked `*.md`' in _out1350d, '| ---' in _out1350d])

    # ── T5: the third covered prefix is exercised, not merely declared ───────────────
    def _psg_mut_agents1350(root):
        _psg_write1350(root, 'agents/beta.md', 'beta\nx\n')                  # 5 -> 7

    _rc1350g, _out1350g = _psg_branch1350(_R1350, 'agentsonly', _psg_mut_agents1350)
    assert_eq("#1350 an agents/*.md-only change produces a row (agents/** is inside the "
              "covered population, not beside it)",
              (0, ['| `agents/beta.md` | 5 | 7 | +2 | +40.0% |',
                   '| **Whole covered surface** | **17** | **19** | **+2** | **+11.8%** |']),
              (_rc1350g, _psg_rows1350(_out1350g)))

    # ── A same-LENGTH edit still earns a row ────────────────────────────────────────
    # changed_rows() decides change by blob identity, not size. Nothing else here
    # exercises that: every other fixture changes a file's length, so swapping the sha
    # test for a size test would leave the suite green while the table silently dropped
    # exactly the edit a prompt-surface reviewer most wants to see — a same-length
    # reword of prose.
    def _psg_mut_samelen1350(root):
        _psg_write1350(root, 'skills/alpha/SKILL.md', 'ALPHA\n')             # 6 -> 6

    _rc1350i, _out1350i = _psg_branch1350(_R1350, 'samelen', _psg_mut_samelen1350)
    assert_eq("#1350 a same-LENGTH edit to a covered file still renders a row, with a "
              "delta of 0 — change is blob identity, never byte count",
              (0, ['| `skills/alpha/SKILL.md` | 6 | 6 | +0 | +0.0% |',
                   '| **Whole covered surface** | **17** | **17** | **+0** | **+0.0%** |']),
              (_rc1350i, _psg_rows1350(_out1350i)))

    # ── The thousands-separated render form is the only one production shows ────────
    # Every other fixture file is a handful of bytes, so no assertion would ever see a
    # comma — yet a real prompt surface is megabytes and every rendered figure carries
    # separators. This pins the format that actually ships.
    def _psg_mut_big1350(root):
        _psg_write1350(root, 'skills/alpha/SKILL.md', 'x' * 12345)

    _rc1350j, _out1350j = _psg_branch1350(_R1350, 'big', _psg_mut_big1350)
    assert_eq("#1350 rendered figures carry thousands separators (the only form a "
              "real prompt surface ever produces)",
              (0, ['| `skills/alpha/SKILL.md` | 6 | 12,345 | +12,339 | +205,650.0% |',
                   ('| **Whole covered surface** | **17** | **12,356** | **+12,339** '
                   '| **+72,582.4%** |')]),
              (_rc1350j, _psg_rows1350(_out1350j)))

    # ── Repo-root anchoring: a subdirectory invocation reports the same thing ───────
    # The ls-tree pathspecs are repo-relative, so before the helper anchored on the
    # repository root a run from a subdirectory matched nothing and printed a confident
    # "no covered path changed" — a FALSE statement rendered into a PR description as a
    # generated fact. That is strictly worse than an error, and invisible to the reader.
    (Path(_R1350) / 'skills' / 'alpha').mkdir(parents=True, exist_ok=True)
    _rc1350k, _out1350k = _psg_run1350(str(Path(_R1350) / 'skills' / 'alpha'))
    assert_eq("#1350 a run from a SUBDIRECTORY renders the same table as one from the "
              "repo root (never a false 'no covered path changed')",
              (0, _psg_rows1350(_out1350j)),
              (_rc1350k, _psg_rows1350(_out1350k)))

    # ── T7: the aggregate is derived from the per-file figures it summarises ─────────
    def _psg_mut_multi1350(root):
        _psg_write1350(root, 'skills/alpha/SKILL.md', 'alpha\nmore\n')       # +5
        _psg_write1350(root, '.prflow/prompt-extensions/gamma.md', 'gamma\nyz\n')  # +3

    _rc1350h, _out1350h = _psg_branch1350(_R1350, 'multi', _psg_mut_multi1350)
    _rows1350h = _psg_rows1350(_out1350h)
    assert_eq("#1350 a multi-file change renders one row per changed covered file plus "
              "the aggregate",
              (0, 3), (_rc1350h, len(_rows1350h)))
    # The aggregate DELTA equals the sum of the per-file deltas (+5 +3). Its TOTAL is
    # deliberately the WHOLE covered surface at HEAD (25), not the sum of the changed
    # rows (20) — AC1 asks for the running total of the surface, which is the figure
    # that keeps a repeated delta meaningful.
    assert_eq("#1350 the aggregate row sums the per-file deltas and carries the WHOLE "
              "covered surface's total at HEAD, not the changed rows' subtotal",
              ['| `.prflow/prompt-extensions/gamma.md` | 6 | 9 | +3 | +50.0% |',
               '| `skills/alpha/SKILL.md` | 6 | 11 | +5 | +83.3% |',
               '| **Whole covered surface** | **17** | **25** | **+8** | **+47.1%** |'],
              _rows1350h)

# ── AC5 / T3: an unresolvable merge-base is a breadcrumb, never a silent empty table ───
with tempfile.TemporaryDirectory(prefix='psg1350f-') as _R1350f:
    # A repo with commits but no `main` branch and no `origin` remote: every candidate
    # ref (`origin/HEAD`, `origin/main`, `main`) fails to resolve.
    _psg_git1350(_R1350f, 'init', '-q', '-b', 'solo')
    _psg_git1350(_R1350f, 'config', 'user.email', 'a@b.c')
    _psg_git1350(_R1350f, 'config', 'user.name', 'T')
    _psg_git1350(_R1350f, 'config', 'commit.gpgsign', 'false')
    _psg_write1350(_R1350f, 'skills/alpha/SKILL.md', 'alpha\n')
    _psg_git1350(_R1350f, 'add', '-A')
    _psg_git1350(_R1350f, 'commit', '-qm', 'solo')
    _rc1350f, _out1350f = _psg_run1350(_R1350f)
    assert_eq("#1350 an unresolvable merge-base still exits 0 (the helper gates nothing)",
              0, _rc1350f)
    assert_eq("#1350 an unresolvable merge-base names the refs it tried, rather than "
              "emitting a silently empty table",
              [True, True, False],
              ['merge-base could not be resolved' in _out1350f,
               '`main`' in _out1350f,
               '| ---' in _out1350f])

# ── The origin/HEAD default-branch arm — the only one a non-`main` consumer uses ──────
# Every other fixture has no `origin` remote, so the symbolic-ref probe fails and the run
# falls through to the literal `main` fallback. That leaves the primary arm untested: a
# consumer whose default branch is `develop` depends on it entirely, and deleting it
# outright would keep this suite green while that consumer got the wrong base or no table.
with tempfile.TemporaryDirectory(prefix='psg1350o-') as _R1350o:
    _R1350oP = Path(_R1350o)
    (_R1350oP / 'up').mkdir()
    (_R1350oP / 'work').mkdir()
    _UP1350 = str(_R1350oP / 'up')
    _WK1350 = str(_R1350oP / 'work')
    # An upstream whose default branch is deliberately NOT `main`.
    _psg_git1350(_UP1350, 'init', '-q', '-b', 'develop')
    _psg_git1350(_UP1350, 'config', 'user.email', 'a@b.c')
    _psg_git1350(_UP1350, 'config', 'user.name', 'T')
    _psg_git1350(_UP1350, 'config', 'commit.gpgsign', 'false')
    _psg_write1350(_UP1350, 'skills/alpha/SKILL.md', 'alpha\n')
    _psg_git1350(_UP1350, 'add', '-A')
    _psg_git1350(_UP1350, 'commit', '-qm', 'base')
    _psg_git1350(_WK1350, 'clone', '-q', _UP1350, '.')
    _psg_git1350(_WK1350, 'config', 'user.email', 'a@b.c')
    _psg_git1350(_WK1350, 'config', 'user.name', 'T')
    _psg_git1350(_WK1350, 'config', 'commit.gpgsign', 'false')
    _psg_git1350(_WK1350, 'checkout', '-q', '-b', 'feature')
    _psg_write1350(_WK1350, 'skills/alpha/SKILL.md', 'alpha\nmore\n')
    _psg_git1350(_WK1350, 'add', '-A')
    _psg_git1350(_WK1350, 'commit', '-qm', 'feature')
    _rc1350o, _out1350o = _psg_run1350(_WK1350)
    assert_eq("#1350 the merge-base resolves through origin/HEAD, so a repo whose "
              "default branch is not `main` is measured against ITS default",
              (0, True, ['| `skills/alpha/SKILL.md` | 6 | 11 | +5 | +83.3% |',
                         ('| **Whole covered surface** | **6** | **11** | **+5** '
                         '| **+83.3%** |')]),
              (_rc1350o, '(`origin/develop`)' in _out1350o,
               _psg_rows1350(_out1350o)))

# ── An unrunnable git is a stated breadcrumb and exit 0, never a traceback ────────────
# `check=False` covers a git that RUNS and fails; it does nothing for a git that cannot be
# executed at all, which raises before any return code exists. That path ended the helper
# in a traceback with empty stdout — and the shipped extension tells the agent to omit the
# section on empty output, so the measurement vanished with nobody told why.
with tempfile.TemporaryDirectory(prefix='psg1350g-') as _R1350gone:
    _env1350 = dict(os.environ, DEVFLOW_GIT=str(Path(_R1350gone) / 'no-such-git'))
    _proc1350 = _subprocess.run([_PSG1350], cwd=_R1350gone, capture_output=True,
                                text=True, env=_env1350)
    assert_eq("#1350 an unrunnable DEVFLOW_GIT still exits 0 with a stated breadcrumb "
              "naming the cause, never a traceback",
              (0, True, True, False),
              (_proc1350.returncode,
               'no table rendered' in _proc1350.stdout,
               'could not be executed' in _proc1350.stdout,
               'Traceback' in _proc1350.stderr))
    # Negative control: the breadcrumb above is reached THROUGH the DEVFLOW_GIT override,
    # so a regression to a bare `git` would not produce it in a directory that is a repo.
    assert_eq("#1350 DEVFLOW_GIT is honoured — the override, not a bare `git`, is what "
              "the helper invokes",
              True, str(Path(_R1350gone) / 'no-such-git') in _proc1350.stdout)

# ── A non-blob entry under a covered prefix is DISCLOSED on stdout, not swallowed ────
# A submodule gitlink whose path ends in `.md` is the shape that actually reaches the
# skip counter: `ls-tree -r` does emit gitlinks (`160000 commit … -`), but the covered-
# population `.md` suffix test drops all the ordinary ones first. Such an entry cannot be
# sized, so it is excluded from the figures — and the disclosure of that exclusion must
# ride the SAME channel as the figures, because the consuming prompt extension renders
# stdout verbatim and reads no stderr. A caveat on stderr would be stripped from exactly
# the runs whose numbers need it, publishing a quietly-wrong precise total as a fact.
with tempfile.TemporaryDirectory(prefix='psg1350s-') as _R1350s:
    _R1350sP = Path(_R1350s)
    (_R1350sP / 'sub').mkdir()
    (_R1350sP / 'main').mkdir()
    _SUB1350 = str(_R1350sP / 'sub')
    _MN1350 = str(_R1350sP / 'main')
    for _r in (_SUB1350, _MN1350):
        _psg_git1350(_r, 'init', '-q', '-b', 'main')
        _psg_git1350(_r, 'config', 'user.email', 'a@b.c')
        _psg_git1350(_r, 'config', 'user.name', 'T')
        _psg_git1350(_r, 'config', 'commit.gpgsign', 'false')
    _psg_write1350(_SUB1350, 'readme.md', 'sub\n')
    _psg_git1350(_SUB1350, 'add', '-A')
    _psg_git1350(_SUB1350, 'commit', '-qm', 'sub')
    _psg_write1350(_MN1350, 'skills/alpha/SKILL.md', 'alpha\n')
    _psg_git1350(_MN1350, 'add', '-A')
    _psg_git1350(_MN1350, 'commit', '-qm', 'base')
    _psg_git1350(_MN1350, 'checkout', '-q', '-b', 'feature')
    _sub_add1350 = _subprocess.run(
        ('git', '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q',
         _SUB1350, 'skills/vendored.md'),
        cwd=_MN1350, capture_output=True, text=True)
    if _sub_add1350.returncode == 0:
        _psg_write1350(_MN1350, 'skills/alpha/SKILL.md', 'alpha\nmore\n')
        _psg_git1350(_MN1350, 'add', '-A')
        _psg_git1350(_MN1350, 'commit', '-qm', 'feature')
        _rc1350s, _out1350s = _psg_run1350(_MN1350)
        assert_eq("#1350 a non-blob entry under a covered prefix is disclosed on STDOUT "
                  "below the table (the channel the PR body actually renders), never "
                  "only on stderr",
                  (0, True, True),
                  (_rc1350s,
                   '| `skills/alpha/SKILL.md` | 6 | 11 | +5 | +83.3% |' in _out1350s,
                   'not readable blobs' in _out1350s))
        # The endpoint is named, so a reader knows WHICH column the omission distorts:
        # a merge-base skip inflates a delta, a HEAD skip understates the totals. A
        # single folded count could not say that, and for two disjoint skips would not
        # even be a true count.
        assert_eq("#1350 the skip disclosure names the ENDPOINT it applies to",
                  True, 'at `HEAD` were not readable blobs' in _out1350s)

        # The same disclosure must survive the NO-TABLE arm. That arm makes an
        # absolute negative claim — "no covered path changed" — so a run that dropped
        # an entry it could not read has the least business making it unqualified.
        _psg_git1350(_MN1350, 'checkout', '-q', '-b', 'gitlink-only', 'main')
        _sub_add2_1350 = _subprocess.run(
            ('git', '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q',
             _SUB1350, 'skills/other.md'),
            cwd=_MN1350, capture_output=True, text=True)
        if _sub_add2_1350.returncode == 0:
            _psg_git1350(_MN1350, 'add', '-A')
            _psg_git1350(_MN1350, 'commit', '-qm', 'gitlink-only')
            _rc1350t, _out1350t = _psg_run1350(_MN1350)
            assert_eq("#1350 the no-covered-change breadcrumb still carries the skip "
                      "disclosure — an absolute negative claim is never left "
                      "unqualified by a run that excluded entries",
                      (0, True, True),
                      (_rc1350t,
                       'no tracked `*.md`' in _out1350t,
                       'not readable blobs' in _out1350t))
    else:
        # Submodule creation can be refused by a host git policy; say so rather than
        # letting the scenario vanish into a silent pass.
        assert_eq("#1350 submodule fixture could not be created, so the non-blob "
                  f"disclosure path was NOT exercised: {_sub_add1350.stderr.strip()}",
                  True, False)

# ── A non-git directory: HEAD unresolvable, still exit 0 ─────────────────────────────
with tempfile.TemporaryDirectory(prefix='psg1350n-') as _R1350n:
    _rc1350n, _out1350n = _psg_run1350(_R1350n)
    assert_eq("#1350 a non-git directory exits 0 with the HEAD-unresolvable breadcrumb "
              "and no table",
              (0, True, False),
              (_rc1350n, '`HEAD` could not be resolved' in _out1350n,
               '| ---' in _out1350n))


# ── issue #1276: lint-manifest strict reader/validator ───────────────────────
# The declarative lint manifest is a best-effort parser over agent-/human-mutable
# JSON, so it follows the repo's six-shape reader matrix: every degraded shape
# resolves to a typed `unestablished` result with a specific reason, never a
# plausible-but-unobserved "N/A". These assertions pin both the established path
# (the shipped manifest validates) and the full rejection matrix AC #1276 names.
import copy as _lm_copy

lint_manifest = _load('lint_manifest', SCRIPTS / 'lint_manifest.py')


def _lm_valid():
    """A minimal but complete manifest object that validates, for mutation tests."""
    return {
        "schema_version": 1,
        "tools": {
            "shellcheck": {
                "version": "0.10.0",
                "timeout_seconds": 600,
                "artifacts": [
                    {"os": "linux", "arch": "x86_64",
                     "digest": "sha256:" + "a" * 64,
                     "archive_type": "tar.xz", "member": "shellcheck",
                     "strategy": "extract-tar"},
                ],
            },
            "ruff": {
                "version": "0.6.9",
                "timeout_seconds": 600,
                "artifacts": [
                    {"os": "linux", "arch": "x86_64",
                     "digest": "sha256:" + "b" * 64,
                     "archive_type": "tar.gz", "member": "ruff",
                     "strategy": "extract-tar"},
                ],
            },
        },
        "selectors": [
            {"id": "shell-portable", "language": "shell",
             "include_globs": ["**/*.sh"], "exclude_globs": ["lib/test/**"]},
            {"id": "python", "language": "python", "include_globs": ["**/*.py"]},
        ],
        "exclusions": ["lib/test/fixtures/**"],
        "special_invocations": [
            {"id": "run-sh-extended-analysis-off", "path": "lib/test/run.sh",
             "tool": "shellcheck", "extra_flags": ["--extended-analysis=false"]},
        ],
        "full_profiles": [
            {"id": "shell-full", "tool": "shellcheck", "selector": "shell-portable"},
            {"id": "python-full", "tool": "ruff", "selector": "python"},
        ],
    }


def _lm_reason(obj):
    """Validate a manifest OBJECT and return (established, reason-prefix)."""
    r = lint_manifest.validate_manifest(obj)
    prefix = None if r.reason is None else r.reason.split(":", 1)[0]
    return (r.established, prefix)


def _lm_bytes(raw):
    """Validate manifest BYTES and return (established, reason-prefix)."""
    r = lint_manifest.parse_manifest(raw)
    prefix = None if r.reason is None else r.reason.split(":", 1)[0]
    return (r.established, prefix)


# The shipped manifest and the in-repo canonical fixture both establish.
_lm_shipped = lint_manifest.load_manifest(SCRIPTS.parent / ".prflow" / "lint-manifest.json")
assert_eq("#1276 the shipped .prflow/lint-manifest.json establishes", True, _lm_shipped.established)
assert_eq("#1276 a complete valid manifest object establishes", (True, None), _lm_reason(_lm_valid()))

# A result is NEVER "N/A": it is exactly one of the two typed states.
assert_eq("#1276 result status is one of the two typed words",
          True, _lm_shipped.status in ("established", "unestablished"))
assert_raises("#1276 an out-of-vocabulary status is rejected at construction",
              ValueError, lambda: lint_manifest.ManifestResult("N/A"))

# ── Six-shape matrix at the top level ────────────────────────────────────────
assert_eq("#1276 top-level array is wrong-type", (False, "wrong-type"), _lm_reason([1, 2, 3]))
assert_eq("#1276 top-level scalar (number) is wrong-type", (False, "wrong-type"), _lm_reason(7))
assert_eq("#1276 top-level scalar (string) is wrong-type", (False, "wrong-type"), _lm_reason("x"))
assert_eq("#1276 valid-falsy false is wrong-type not established", (False, "wrong-type"), _lm_reason(False))
assert_eq("#1276 valid-falsy 0 is wrong-type not established", (False, "wrong-type"), _lm_reason(0))
assert_eq("#1276 valid-falsy null is wrong-type not established", (False, "wrong-type"), _lm_reason(None))

# ── Byte-level degraded shapes ───────────────────────────────────────────────
assert_eq("#1276 empty bytes are unestablished empty", (False, "empty"), _lm_bytes(b""))
assert_eq("#1276 invalid UTF-8 is unestablished", (False, "invalid-utf8"), _lm_bytes(b"\xff\xfe\x00"))
assert_eq("#1276 malformed JSON is unestablished", (False, "malformed-json"), _lm_bytes(b"{not json"))
assert_eq("#1276 truncated JSON is unestablished", (False, "malformed-json"),
          _lm_bytes(b'{"schema_version": 1, "tools": '))
assert_eq("#1276 duplicate object keys are rejected (json silently keeps last)",
          (False, "duplicate-key"),
          _lm_bytes(b'{"schema_version": 1, "schema_version": 2, "tools": {}, "selectors": [], "full_profiles": []}'))
# A missing manifest file is a distinct unestablished reason, never an exception.
_lm_missing = lint_manifest.load_manifest(SCRIPTS.parent / ".prflow" / "no-such-manifest.json")
assert_eq("#1276 a missing manifest file is unestablished missing",
          (False, "missing"), (_lm_missing.established, _lm_missing.reason.split(":", 1)[0]))

# ── Structural / field-level rejections ──────────────────────────────────────
def _lm_mut(mutate):
    obj = _lm_valid()
    mutate(obj)
    return _lm_reason(obj)


def _lm_del(obj, key):
    del obj[key]


assert_eq("#1276 unknown top-level field rejected",
          (False, "unknown-field"), _lm_mut(lambda o: o.__setitem__("evil", 1)))
assert_eq("#1276 missing required top-level key rejected",
          (False, "missing"), _lm_mut(lambda o: _lm_del(o, "tools")))
assert_eq("#1276 unknown schema_version rejected",
          (False, "unknown-version"), _lm_mut(lambda o: o.__setitem__("schema_version", 99)))
assert_eq("#1276 non-int schema_version rejected",
          (False, "wrong-type"), _lm_mut(lambda o: o.__setitem__("schema_version", "1")))
assert_eq("#1276 unknown tool rejected",
          (False, "unknown-enum"), _lm_mut(lambda o: o["tools"].__setitem__("flake8", {})))
assert_eq("#1276 missing required tool rejected",
          (False, "missing"), _lm_mut(lambda o: o["tools"].__delitem__("ruff")))
assert_eq("#1276 unknown-enum os rejected",
          (False, "unknown-enum"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("os", "plan9")))
assert_eq("#1276 unknown-enum strategy (unknown strategy ID) rejected",
          (False, "unknown-enum"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("strategy", "curl-bash")))
assert_eq("#1276 unknown-enum archive_type rejected",
          (False, "unknown-enum"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("archive_type", "rar")))
assert_eq("#1276 bad digest shape rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("digest", "md5:abc")))
assert_eq("#1276 duplicate platform tuple (same digest) is duplicate-id",
          (False, "duplicate-id"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"].append(
              _lm_copy.deepcopy(o["tools"]["ruff"]["artifacts"][0]))))


def _lm_conflict(o):
    dup = _lm_copy.deepcopy(o["tools"]["ruff"]["artifacts"][0])
    dup["digest"] = "sha256:" + "c" * 64
    o["tools"]["ruff"]["artifacts"].append(dup)


assert_eq("#1276 same platform tuple with two digests is conflicting-id",
          (False, "conflicting-id"), _lm_mut(_lm_conflict))
assert_eq("#1276 duplicate selector id rejected",
          (False, "duplicate-id"),
          _lm_mut(lambda o: o["selectors"].append(
              {"id": "python", "language": "python", "include_globs": ["**/*.py"]})))
assert_eq("#1276 profile referencing an undefined selector is conflicting-id",
          (False, "conflicting-id"),
          _lm_mut(lambda o: o["full_profiles"][0].__setitem__("selector", "nope")))

# ── The AC #1276 declarative-purity rejections: shell commands, package-manager
#    snippets, arbitrary executable paths, URL templates, env expansion. Each is
#    a string that fails its typed field's regex. ──────────────────────────────
assert_eq("#1276 a shell command in a glob is rejected (declarative purity)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][0]["include_globs"].append("*.sh; rm -rf /")))
assert_eq("#1276 an env-expansion glob is rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][0]["include_globs"].append("$HOME/*.sh")))
assert_eq("#1276 a URL template digest is rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__(
              "digest", "https://example.test/ruff#{version}")))
assert_eq("#1276 an executable PATH (not a basename) in member is rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("member", "/usr/bin/ruff")))
assert_eq("#1276 a package-manager snippet in a flag is rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["special_invocations"][0]["extra_flags"].append("&& pip install evil")))
assert_eq("#1276 a shell metacharacter in extra_flags is rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["special_invocations"][0]["extra_flags"].append("--x=$(whoami)")))
assert_eq("#1276 timeout out of bounds rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"].__setitem__("timeout_seconds", 999999)))
# The special-invocation still carries the run.sh extended-analysis flag as a
# typed field — the declarative representation of the AC's dedicated invocation.
assert_eq("#1276 run.sh special invocation carries --extended-analysis=false declaratively",
          True,
          any(si["path"] == "lib/test/run.sh"
              and "--extended-analysis=false" in si["extra_flags"]
              for si in _lm_valid()["special_invocations"]))

# ── Review finding: a trailing newline must NOT slip past a typed field. `$`
#    matches before a final `\n` in non-MULTILINE mode; `\Z` (used by the module)
#    does not. One assertion per field-bearing value. ───────────────────────────
assert_eq("#1276 trailing-newline version rejected (\\Z anchor, not $)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"].__setitem__("version", "0.6.9\n")))
assert_eq("#1276 trailing-newline digest rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__(
              "digest", "sha256:" + "b" * 64 + "\n")))
assert_eq("#1276 trailing-newline member rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"]["artifacts"][0].__setitem__("member", "ruff\n")))
assert_eq("#1276 trailing-newline glob rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][0]["include_globs"].append("**/*.sh\n")))
assert_eq("#1276 trailing-newline flag rejected",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["special_invocations"][0]["extra_flags"].append("--x=y\n")))

# ── Review finding: pathologically-nested JSON fails closed (RecursionError is
#    not a JSONDecodeError) rather than escaping as an unhandled exception. ──────
_lm_deep = b"[" * 200000 + b"]" * 200000
assert_eq("#1276 deeply-nested JSON is unestablished, not an escaped RecursionError",
          (False, "malformed-json"), _lm_bytes(_lm_deep))

# ── Review finding: the CLI usage-error exit code (1) is distinct from the
#    UNESTABLISHED exit code (2), so a caller can branch on the exit status. ─────
assert_eq("#1276 CLI establishes the shipped manifest with exit 0",
          0, lint_manifest.main([str(SCRIPTS.parent / ".prflow" / "lint-manifest.json")]))
assert_eq("#1276 CLI returns 2 for a validated-but-unestablished manifest",
          2, lint_manifest.main([str(SCRIPTS.parent / ".prflow" / "no-such-manifest.json")]))


def _lm_cli_exit(argv):
    try:
        lint_manifest.main(argv)
    except SystemExit as _e:
        return _e.code
    return "no-exit"


assert_eq("#1276 CLI usage error (missing path) exits 1, NOT 2 (no collision with unestablished)",
          1, _lm_cli_exit([]))

# ── Audit finding H1: a manifest that lints NOTHING must not validate as
#    `established`. A caller reading ESTABLISHED, enumerating zero files and
#    reporting a clean lint is the canonical unknown-is-not-zero fail-open. Each
#    non-empty guard gets its own assertion, so deleting any one of them goes RED.
assert_eq("#1276 H1 empty selectors array rejected (non-empty guard is discriminated)",
          (False, "invalid-value"), _lm_mut(lambda o: o.__setitem__("selectors", [])))
assert_eq("#1276 H1 empty full_profiles array rejected (non-empty guard is discriminated)",
          (False, "invalid-value"), _lm_mut(lambda o: o.__setitem__("full_profiles", [])))
assert_eq("#1276 H1 empty tool artifacts array rejected (non-empty guard is discriminated)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["tools"]["ruff"].__setitem__("artifacts", [])))
assert_eq("#1276 H1 empty include_globs rejected (a selector matching nothing lints nothing)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][0].__setitem__("include_globs", [])))
# selectors[0] deliberately stays VALID here: _validate_selectors returns on the
# first non-established selector, so emptying every selector would only ever
# exercise selectors[0]. Emptying the SECOND alone proves the guard runs per selector.
assert_eq("#1276 H1 a LATER selector's empty include_globs is rejected too (guard runs per selector)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][1].__setitem__("include_globs", [])))
assert_eq("#1276 H1 present-but-empty exclude_globs rejected (declares nothing)",
          (False, "invalid-value"),
          _lm_mut(lambda o: o["selectors"][0].__setitem__("exclude_globs", [])))
assert_eq("#1276 H1 present-but-empty exclusions rejected (declares nothing)",
          (False, "invalid-value"), _lm_mut(lambda o: o.__setitem__("exclusions", [])))
# Positive control for H1: omitting the two OPTIONAL keys entirely still validates,
# so the non-empty guards reject an empty declaration without banning absence.
assert_eq("#1276 H1 positive control: omitting exclusions and exclude_globs still establishes",
          (True, None),
          _lm_mut(lambda o: (_lm_del(o, "exclusions"),
                             _lm_del(o["selectors"][0], "exclude_globs"))))

# ── Audit finding: the two isinstance(..., bool) guards are load-bearing because
#    `True in {1}` is True and `1 <= True <= 3600` is True — without the bool
#    exclusion a JSON `true` would validate as a version/timeout. `true` is the
#    only input that discriminates either guard, so no `false` timeout case is
#    pinned: `1 <= False <= 3600` is already False, so it is rejected either way.
assert_eq("#1276 boolean true schema_version rejected (True in {1} is True)",
          (False, "wrong-type"), _lm_mut(lambda o: o.__setitem__("schema_version", True)))
assert_eq("#1276 boolean false schema_version rejected",
          (False, "wrong-type"), _lm_mut(lambda o: o.__setitem__("schema_version", False)))
assert_eq("#1276 boolean true timeout_seconds rejected (1 <= True <= 3600 is True)",
          (False, "wrong-type"),
          _lm_mut(lambda o: o["tools"]["ruff"].__setitem__("timeout_seconds", True)))

# ── Audit finding M3: path-shaped fields must be repo-relative and argv-safe. A
#    leading-dash entry spliced into a shellcheck/ruff argv is parsed as an OPTION
#    rather than a path; a traversal or absolute entry points the lint outside the
#    repository, contradicting the module's own "repo-relative selector pattern".
# `a/../b` is the INTERIOR-traversal case: it locks the per-segment semantics of
# `_validate_path_shape`, which a `value.startswith("..")` rewrite would silently lose.
_LM_BAD_PATHS = ("../../../etc/passwd", "/etc/passwd", "..", "../../*.sh", "a/../b",
                 "-x", "-rf", "--exclude", "-")
for _lm_bad in _LM_BAD_PATHS:
    assert_eq(f"#1276 M3 include_globs rejects {_lm_bad!r}",
              (False, "invalid-value"),
              _lm_mut(lambda o, _b=_lm_bad: o["selectors"][0]["include_globs"].append(_b)))
    assert_eq(f"#1276 M3 exclude_globs rejects {_lm_bad!r}",
              (False, "invalid-value"),
              _lm_mut(lambda o, _b=_lm_bad: o["selectors"][0]["exclude_globs"].append(_b)))
    assert_eq(f"#1276 M3 exclusions rejects {_lm_bad!r}",
              (False, "invalid-value"),
              _lm_mut(lambda o, _b=_lm_bad: o["exclusions"].append(_b)))
    assert_eq(f"#1276 M3 special_invocation path rejects {_lm_bad!r}",
              (False, "invalid-value"),
              _lm_mut(lambda o, _b=_lm_bad: o["special_invocations"][0].__setitem__("path", _b)))

# Positive controls for M3: legitimate repo-relative patterns must STILL validate,
# so the rejections above cannot pass vacuously by banning every path.
_LM_GOOD_GLOBS = ("**/*.sh", "lib/test/**", "scripts/*.py", ".github/workflows/*.yml",
                  "docs/**/*.md", "a-b/c_d.sh", "lib/test/fixtures/**", "..foo/*.py")
for _lm_good in _LM_GOOD_GLOBS:
    assert_eq(f"#1276 M3 positive control: include_globs still accepts {_lm_good!r}",
              (True, None),
              _lm_mut(lambda o, _g=_lm_good: o["selectors"][0]["include_globs"].append(_g)))
    assert_eq(f"#1276 M3 positive control: exclusions still accepts {_lm_good!r}",
              (True, None),
              _lm_mut(lambda o, _g=_lm_good: o["exclusions"].append(_g)))
assert_eq("#1276 M3 positive control: special_invocation path still accepts a repo-relative file",
          (True, None),
          _lm_mut(lambda o: o["special_invocations"][0].__setitem__("path", "scripts/config-get.sh")))
# The shipped manifest is itself the end-to-end positive control for M3: every one
# of its globs and paths is repo-relative and argv-safe, so it still establishes.
assert_eq("#1276 M3 positive control: the shipped manifest still establishes",
          True,
          lint_manifest.load_manifest(SCRIPTS.parent / ".prflow" / "lint-manifest.json").established)

# ── Issue #1484: an artifact `member` is path-shaped too — it is the name the
#    extractor pulls out of the archive and then invokes — yet `_MEMBER_RE`'s
#    character class admitted `.`, `..` and `-rf`, each of which established.
# These are their OWN cases rather than members of the _LM_BAD_PATHS fan-out:
# every `/`-bearing entry in that tuple is already rejected by `_MEMBER_RE`, so
# reusing it would attribute the rejection to the wrong guard. Each assertion
# therefore pins the FULL reason, so a different guard rejecting the same input
# cannot masquerade as this one.
def _lm_member(value):
    """Set the ruff artifact's member and return (established, full reason)."""
    obj = _lm_valid()
    obj["tools"]["ruff"]["artifacts"][0]["member"] = value
    r = lint_manifest.validate_manifest(obj)
    return (r.established, r.reason)


_LM_MEMBER_WHERE = "invalid-value: tool 'ruff' artifact #0 member"
assert_eq("#1484 member '.' rejected as a directory entry",
          (False, f"{_LM_MEMBER_WHERE} '.' names a directory entry, not an extractable file"),
          _lm_member("."))
assert_eq("#1484 member '..' rejected by the shared traversal arm",
          (False, f"{_LM_MEMBER_WHERE} '..' escapes the repository via '..'"),
          _lm_member(".."))
assert_eq("#1484 dash-leading member rejected by the shared argv-safety arm",
          (False, (f"{_LM_MEMBER_WHERE} '-rf' starts with '-' "
                  "(would be parsed as an option, not a path)")),
          _lm_member("-rf"))
# Positive controls: the three rejections above must not pass vacuously by
# banning every member. The shipped manifest's own end-to-end `established`
# assertions above cover the third control the criterion names.
assert_eq("#1484 positive control: member 'shellcheck' still establishes",
          (True, None), _lm_member("shellcheck"))
assert_eq("#1484 positive control: member 'ruff.exe' still establishes",
          (True, None), _lm_member("ruff.exe"))


# ── issue #1575: Phase-3.4 two-verifier reconciliation (reconcile-ac-verifiers.py) ──
# The executable core of the two-verifier AC gate. Drive every pairing of the three
# statuses and prove: agreement records that status, EVERY disagreement records
# `unestablished`, a `satisfied` never lands without an evidence pointer, and a
# command that passes while the claim verifier disagrees does NOT reconcile satisfied.
_R_STATUSES = ("satisfied", "unmet", "unestablished")

# A #1575 fixture reaching reconcile() must attach a complete disposition set on both
# sides, or the #1580 gate forces `unestablished` and the fixture stops testing status
# reconciliation at all.
def _disp_all(slots, verdict="yes"):
    """A complete disposition map over `slots`, every slot dispositioned `verdict`."""
    return {s: f"{verdict} (fixture: {s})" for s in slots}


_R_EV_DISP = _disp_all(reconcile_ac.EVIDENCE_SLOTS)
_R_CL_DISP = _disp_all(reconcile_ac.CLAIM_SLOTS)


def _ev_recs(*records):
    """#1575 evidence-side fixture records, each given a complete disposition set."""
    return [dict(r, dispositions=_R_EV_DISP) for r in records]


def _cl_recs(*records):
    """#1575 claim-side fixture records, each given a complete disposition set."""
    return [dict(r, dispositions=_R_CL_DISP) for r in records]

for _es in _R_STATUSES:
    for _cs in _R_STATUSES:
        # Both sides carry an evidence pointer so a `satisfied` agreement is not
        # downgraded here — the no-pointer downgrade is exercised separately below.
        _st, _ev, _src = reconcile_ac.reconcile_one(_es, _cs, "ev-ptr", "cl-ptr")
        _expected = _es if _es == _cs else "unestablished"
        assert_eq(f"#1575 reconcile_one({_es},{_cs}) status", _expected, _st)
        # Blocking: only `satisfied` does not block.
        _expected_blocks = _expected != "satisfied"
        assert_eq(f"#1575 reconcile_one({_es},{_cs}) blocks",
                  _expected_blocks, _st in reconcile_ac.BLOCKING_STATUSES)

# A `satisfied` agreement with NO evidence pointer from either verifier is
# downgraded to `unestablished` — a satisfied record never lands without evidence (AC6).
assert_eq("#1575 satisfied with no evidence downgrades to unestablished",
          ("unestablished", "", ""),
          reconcile_ac.reconcile_one("satisfied", "satisfied", "", ""))
# A single-sided evidence pointer is sufficient, and the source is reported.
assert_eq("#1575 satisfied keeps evidence from the evidence verifier alone",
          ("satisfied", "e-only", "evidence"),
          reconcile_ac.reconcile_one("satisfied", "satisfied", "e-only", ""))
assert_eq("#1575 satisfied keeps evidence from the claim verifier alone",
          ("satisfied", "c-only", "claim"),
          reconcile_ac.reconcile_one("satisfied", "satisfied", "", "c-only"))

# Fail-closed status normalization: an unrecognized/absent status is `unestablished`,
# so it never silently agrees into `satisfied`/`unmet`.
assert_eq("#1575 unrecognized status normalizes to unestablished (agreement path)",
          "unestablished",
          reconcile_ac.reconcile_one("bogus", "bogus", "x", "y")[0])
assert_eq("#1575 a bogus status disagreeing with satisfied is unestablished",
          "unestablished",
          reconcile_ac.reconcile_one("satisfied", "bogus", "x", "y")[0])

# The #1450 fixture: a verification command PASSES (evidence=satisfied) while its
# assertions test a DIFFERENT claim than the criterion states (claim=unmet). The
# reconciled record must NOT be satisfied.
_ev_report = _ev_recs(
    {"criterion": 1, "status": "satisfied", "evidence": "suite passed on HEAD"},
    {"criterion": 2, "status": "satisfied", "evidence": "cmd exit 0"},
)
_cl_report = _cl_recs(
    {"criterion": 1, "status": "satisfied", "evidence": "each clause has an assertion"},
    {"criterion": 2, "status": "unmet", "evidence": "command asserts a different claim"},
)
_recon = reconcile_ac.reconcile(_ev_report, _cl_report)
_by = {c["criterion"]: c for c in _recon["criteria"]}
assert_eq("#1575 fixture: agreeing satisfied criterion reconciles satisfied",
          "satisfied", _by[1]["status"])
assert_eq("#1575 fixture: passing command + disagreeing claim is NOT satisfied",
          "unestablished", _by[2]["status"])
assert_eq("#1575 fixture: the non-satisfied criterion blocks", True, _by[2]["blocks"])
assert_eq("#1575 fixture: blocking list names the disagreeing criterion",
          [2], _recon["blocking"])
assert_eq("#1575 fixture: all_satisfied is false when a criterion blocks",
          False, _recon["all_satisfied"])
assert_eq("#1575 fixture: a satisfied criterion carries an evidence pointer",
          True, bool(_by[1]["evidence"]))

# A structured `reason` from the evidence verifier is passed through on a BLOCKING
# criterion so the orchestrator routes the denied-command case from a field, not by
# sniffing free text; it is dropped on a satisfied criterion (no routing to refine).
_recon_reason = reconcile_ac.reconcile(
    _ev_recs(
        {"criterion": 1, "status": "unestablished", "evidence": "denied",
         "reason": "denied"},
        {"criterion": 2, "status": "satisfied", "evidence": "ok", "reason": "denied"}),
    _cl_recs(
        {"criterion": 1, "status": "unestablished", "evidence": ""},
        {"criterion": 2, "status": "satisfied", "evidence": "ok"}))
_rby = {c["criterion"]: c for c in _recon_reason["criteria"]}
assert_eq("#1575 evidence reason passes through on a blocking criterion",
          "denied", _rby[1]["reason"])
assert_eq("#1575 reason is dropped on a satisfied (non-blocking) criterion",
          "", _rby[2]["reason"])
assert_eq("#1575 reason normalizes case/whitespace",
          "failed",
          reconcile_ac._reason_of({"reason": "  FAILED "}))

# A criterion present in only one report fails closed to unestablished (missing vote).
_recon_missing = reconcile_ac.reconcile(
    _ev_recs({"criterion": 1, "status": "satisfied", "evidence": "x"}), [])
assert_eq("#1575 criterion missing from one report reconciles unestablished",
          "unestablished", _recon_missing["criteria"][0]["status"])

# all_satisfied requires at least one criterion (an empty pair is not a trivial pass).
assert_eq("#1575 empty reports do not report all_satisfied",
          False, reconcile_ac.reconcile([], [])["all_satisfied"])

# reconcile_one on the agreeing-satisfied path reports "both" and joins both pointers.
assert_eq("#1575 reconcile_one satisfied/satisfied joins both evidence pointers",
          ("satisfied", "ev-ptr; cl-ptr", "both"),
          reconcile_ac.reconcile_one("satisfied", "satisfied", "ev-ptr", "cl-ptr"))
# A BLOCKING record keeps the failing-detail pointer(s) rather than blanking them, so
# the orchestrator's Blocked-path reflection can name the detail.
assert_eq("#1575 a blocking (disagreement) record keeps its evidence pointer",
          ("unestablished", "cmd passed; asserts other claim", "both"),
          reconcile_ac.reconcile_one("satisfied", "unmet",
                                     "cmd passed", "asserts other claim"))

# `reason` is a CLOSED vocabulary: an unrecognized value normalizes to "" (fail closed),
# not passed through, so a consumer may rely on any non-empty reason being in the set.
assert_eq("#1575 unrecognized reason normalizes to empty",
          "", reconcile_ac._reason_of({"reason": "sideways"}))
for _r in reconcile_ac.EVIDENCE_REASONS:
    assert_eq(f"#1575 known reason {_r} passes through", _r,
              reconcile_ac._reason_of({"reason": _r}))

# A duplicate `criterion` in one report fails closed to unestablished — a later
# `satisfied` can never overwrite an earlier `unmet` (silent last-wins is the bug).
_recon_dup = reconcile_ac.reconcile(
    _ev_recs({"criterion": 1, "status": "unmet", "evidence": "real gap"},
             {"criterion": 1, "status": "satisfied", "evidence": "ok"}),
    _cl_recs({"criterion": 1, "status": "satisfied", "evidence": "ok"}))
assert_eq("#1575 duplicate criterion in a report fails closed to unestablished",
          "unestablished", _recon_dup["criteria"][0]["status"])

# A `criterion: true`/`false` boolean is dropped by the fail-closed guard (bool is an
# int subclass), so it becomes a missing vote → unestablished, never a satisfied vote.
_recon_bool = reconcile_ac.reconcile(
    _ev_recs({"criterion": True, "status": "satisfied", "evidence": "x"},
             {"criterion": 1, "status": "satisfied", "evidence": "x"}),
    _cl_recs({"criterion": 1, "status": "satisfied", "evidence": "y"}))
assert_eq("#1575 a boolean criterion is dropped (not indexed as 1)",
          [1], [c["criterion"] for c in _recon_bool["criteria"]])

# Multi-element `blocking[]` is ascending and complete, out of report order — a
# regression dropping the sort would pass every single-blocker fixture above.
_recon_multi = reconcile_ac.reconcile(
    _ev_recs({"criterion": 3, "status": "unmet", "evidence": ""},
             {"criterion": 1, "status": "satisfied", "evidence": "ok"},
             {"criterion": 2, "status": "unmet", "evidence": ""}),
    _cl_recs({"criterion": 3, "status": "unmet", "evidence": ""},
             {"criterion": 1, "status": "satisfied", "evidence": "ok"},
             {"criterion": 2, "status": "unmet", "evidence": ""}))
assert_eq("#1575 blocking[] is ascending and complete across two blockers",
          [2, 3], _recon_multi["blocking"])

# The CLI entry point's exit-code contract: 0 on a produced reconciliation, 3 on an
# unreadable/malformed report — the load-bearing "unestablished measurement" signal the
# Phase 3.4 prose routes on.
with tempfile.TemporaryDirectory() as _md:
    _ev_p = os.path.join(_md, "ev.json")
    _cl_p = os.path.join(_md, "cl.json")
    with open(_ev_p, "w", encoding="utf-8") as _fh:
        _fh.write(json.dumps(
            _ev_recs({"criterion": 1, "status": "satisfied", "evidence": "ok"})))
    with open(_cl_p, "w", encoding="utf-8") as _fh:
        _fh.write(json.dumps(
            _cl_recs({"criterion": 1, "status": "satisfied", "evidence": "ok"})))
    _out = io.StringIO()
    with contextlib.redirect_stdout(_out):
        _rc_ok = reconcile_ac.main(["--evidence-file", _ev_p, "--claim-file", _cl_p])
    assert_eq("#1575 main() returns 0 on a produced reconciliation", 0, _rc_ok)
    assert_eq("#1575 main() prints the reconciled JSON on stdout",
              True, '"all_satisfied": true' in _out.getvalue())
    # The orchestrator consumes this through stdout JSON, not by importing reconcile(),
    # so a field dropped or made unserializable at the dump layer would be invisible to
    # every in-process assertion above.
    for _f1580 in ("evidence_dispositions", "claim_dispositions", "undischarged_slots"):
        assert_eq(f"#1580 main() serializes {_f1580} onto stdout",
                  True, f'"{_f1580}"' in _out.getvalue())
    # The fixture above is fully dispositioned, so its undischarged_slots is `[]` — the
    # payload the orchestrator actually routes on is the BLOCKING one. Round-trip a
    # non-empty list and the reasons through the real stdout path.
    _gap_ev = os.path.join(_md, "ev-gap.json")
    _gap_partial = {k: v for k, v in _R_EV_DISP.items()
                    if k != reconcile_ac.EVIDENCE_SLOTS[0]}
    with open(_gap_ev, "w", encoding="utf-8") as _fh:
        _fh.write(json.dumps([{"criterion": 1, "status": "satisfied",
                               "evidence": "ok", "dispositions": _gap_partial}]))
    _gap_out = io.StringIO()
    with contextlib.redirect_stdout(_gap_out), contextlib.redirect_stderr(io.StringIO()):
        _rc_gap = reconcile_ac.main(["--evidence-file", _gap_ev,
                                     "--claim-file", _cl_p])
    assert_eq("#1580 main() returns 0 on a blocking reconciliation", 0, _rc_gap)
    _gap_json = json.loads(_gap_out.getvalue())
    assert_eq("#1580 a non-empty undischarged_slots survives serialization",
              [f"evidence:{reconcile_ac.EVIDENCE_SLOTS[0]}"],
              _gap_json["criteria"][0]["undischarged_slots"])
    assert_eq("#1580 the serialized blocking record clears all_satisfied",
              False, _gap_json["all_satisfied"])
    assert_eq("#1580 the surviving slots' verbatim reasons round-trip through stdout",
              _gap_partial, _gap_json["criteria"][0]["evidence_dispositions"])
    # Missing file -> OSError -> exit 3.
    with contextlib.redirect_stderr(io.StringIO()):
        _rc_missing = reconcile_ac.main(
            ["--evidence-file", os.path.join(_md, "nope.json"),
             "--claim-file", _cl_p])
    assert_eq("#1575 main() returns 3 when a report file is missing", 3, _rc_missing)
    # Malformed (non-JSON) file -> JSONDecodeError -> exit 3.
    _bad_p = os.path.join(_md, "bad.json")
    with open(_bad_p, "w", encoding="utf-8") as _fh:
        _fh.write('{not json')
    with contextlib.redirect_stderr(io.StringIO()):
        _rc_bad = reconcile_ac.main(["--evidence-file", _bad_p, "--claim-file", _cl_p])
    assert_eq("#1575 main() returns 3 on a malformed (non-JSON) report", 3, _rc_bad)

# _load_report accepts BOTH the verifier's documented `{"criteria": [...]}` object
# and an already-unwrapped bare list — the producer (agents/ac-*-verifier.md) emits the
# object form, so the boundary must not require the orchestrator to unwrap it first.
with tempfile.TemporaryDirectory() as _rd:
    _obj_path = os.path.join(_rd, "obj.json")
    _list_path = os.path.join(_rd, "list.json")
    with open(_obj_path, "w", encoding="utf-8") as _fh:
        _fh.write('{"criteria": [{"criterion": 1, "status": "unmet", "evidence": ""}]}')
    with open(_list_path, "w", encoding="utf-8") as _fh:
        _fh.write('[{"criterion": 1, "status": "unmet", "evidence": ""}]')
    assert_eq("#1575 _load_report accepts the object {criteria:[...]} form",
              [{"criterion": 1, "status": "unmet", "evidence": ""}],
              reconcile_ac._load_report(_obj_path))
    assert_eq("#1575 _load_report accepts the bare list form",
              [{"criterion": 1, "status": "unmet", "evidence": ""}],
              reconcile_ac._load_report(_list_path))
    _bad_path = os.path.join(_rd, "bad.json")
    with open(_bad_path, "w", encoding="utf-8") as _fh:
        _fh.write('"a scalar, not a report"')
    assert_raises("#1575 _load_report rejects a non-list/non-criteria-object shape",
                  ValueError, lambda: reconcile_ac._load_report(_bad_path))


# ── issue #1580: verifier procedure dispositions (what did you DO, not only conclude) ──
# `dispositions` maps each charter slot NAME (the key) to a `yes|no (reason)` value —
# the `<slot>=<verdict>` prose spelling of the writing-skills marker does not parse here.

# The slot vocabularies are per side and named after each charter's own steps.
# `evidence-recorded` is the one slot BOTH charters carry (the shared evidence-pointer
# rule); a change dropping it from one side would leave that peer rule half-stated.
assert_eq("#1580 both charters carry the shared evidence-recorded slot", True,
          "evidence-recorded" in reconcile_ac.EVIDENCE_SLOTS
          and "evidence-recorded" in reconcile_ac.CLAIM_SLOTS)

# Do not edit a charter's `| Slot |` table without the matching tuple edit here: a slot
# renamed in one place alone forces that side to `unestablished` on EVERY criterion,
# hard-blocking Phase 3.4 in a live run with no other suite signal.
# structural-pin-ok: cross-file-phase-contract -- the charter slot table IS the request
# the verifier answers and the tuple IS the gate that grades the answer; the two are one
# machine-consumed contract split across a shipped prompt file and its helper.
for _acv_file, _acv_slots in (("ac-evidence-verifier.md", reconcile_ac.EVIDENCE_SLOTS),
                              ("ac-claim-verifier.md", reconcile_ac.CLAIM_SLOTS)):
    _acv_text = (SCRIPTS.parent / "agents" / _acv_file).read_text(encoding="utf-8")
    # The table's first column, backticked: `| \`<slot>\` | ... |`. Anchored to the row
    # start so a backticked identifier in a later column cannot be read as a slot.
    _acv_table = set(re.findall(r'^\|\s*`([a-z-]+)`\s*\|', _acv_text, re.MULTILINE))
    assert_eq(f"#1580 {_acv_file}: the slot table names exactly the gate's slots",
              sorted(_acv_slots), sorted(_acv_table))

_EV_D = _disp_all(reconcile_ac.EVIDENCE_SLOTS)
_CL_D = _disp_all(reconcile_ac.CLAIM_SLOTS)

# The parser: `yes`/`no` plus a non-empty reason, case- and spacing-tolerant. One clause
# is what the charters ASK for; the parser accepts and preserves whatever reason it gets.
assert_eq("#1580 a yes disposition with a parenthesised reason parses",
          ("yes", "ran the suite in-env"),
          reconcile_ac.parse_disposition("yes (ran the suite in-env)"))
assert_eq("#1580 a no disposition parses and keeps its reason",
          ("no", "this criterion runs no command"),
          reconcile_ac.parse_disposition("no (this criterion runs no command)"))
assert_eq("#1580 disposition parsing is case-insensitive",
          "yes", reconcile_ac.parse_disposition("YES (shouted)")[0])
# A bare verdict with NO reason is undischarged: AC2 requires the one-clause reason,
# so accepting a reasonless `yes` would let an abbreviated check attest to nothing.
assert_eq("#1580 a bare `yes` with no reason is undischarged",
          (None, ""), reconcile_ac.parse_disposition("yes"))
# Empty parens are a reasonless verdict wearing the right punctuation — the shape a
# verifier producing the marker mechanically would emit for a step it skipped.
assert_eq("#1580 `yes ()` with an empty reason clause is undischarged",
          (None, ""), reconcile_ac.parse_disposition("yes ()"))
# The parens are optional: the marker's own worked examples are written with them, but a
# verifier that omits them has still stated a verdict and a reason.
assert_eq("#1580 a reason without parentheses parses",
          ("no", "this criterion runs no command"),
          reconcile_ac.parse_disposition("no this criterion runs no command"))
assert_eq("#1580 a non-string disposition is undischarged",
          (None, ""), reconcile_ac.parse_disposition({"disposition": "yes"}))
assert_eq("#1580 an unparseable disposition verdict is undischarged",
          (None, ""), reconcile_ac.parse_disposition("maybe (hedging)"))
# The verdict boundary excludes `-` but admits ordinary punctuation. Narrowing it to
# whitespace-and-paren rejects `no, <reason>` and hard-blocks a compliant criterion.
assert_eq("#1580 a hyphen-attached word after the verdict does not parse as a verdict",
          (None, ""), reconcile_ac.parse_disposition("no-op, nothing to coordinate"))
# The same class as `no-op`, and the likelier producer output: an ordinary prose word
# that merely begins with the verdict token states no disposition.
for _adjacent in ("yesish (x)", "noted (x)", "nope (x)"):
    assert_eq(f"#1580 {_adjacent!r} does not parse as a verdict",
              (None, ""), reconcile_ac.parse_disposition(_adjacent))
for _punct, _rest in ((",", "nothing to coordinate"), (".", "the criterion runs none"),
                      (";", "not applicable"), (":", "no command")):
    assert_eq(f"#1580 a verdict followed by {_punct!r} still parses",
              "no", reconcile_ac.parse_disposition(f"no{_punct} {_rest}")[0])
# A reason must carry an alphanumeric character: a mechanical `yes .` is not a clause.
assert_eq("#1580 a punctuation-only reason is undischarged",
          (None, ""), reconcile_ac.parse_disposition("yes ."))
assert_eq("#1580 a dash-only reason is undischarged",
          (None, ""), reconcile_ac.parse_disposition("yes -"))
# Unwrap only what the outer parens enclose. A nested or multi-clause value is carried
# through verbatim rather than reshaped — a `strip("()")` chain would turn `((a))` into
# `a`, making a malformed value look well-formed.
assert_eq("#1580 a nested-paren value is carried through, NOT unwrapped",
          ("yes", "((a))"), reconcile_ac.parse_disposition("yes ((a))"))
assert_eq("#1580 a multi-clause parenthesised value keeps its inner punctuation",
          ("yes", "(a) (b)"), reconcile_ac.parse_disposition("yes (a) (b)"))
# The `<slot>=<verdict>` prose spelling of the writing-skills marker is NOT this shape:
# a producer copying it states a slot the gate scores undischarged.
assert_eq("#1580 the marker's `<slot>=yes` prose spelling does not parse as a value",
          (None, ""), reconcile_ac.parse_disposition("type-decided=yes (x)"))

# _dispositions_of reports the normalized map AND the undischarged slot names.
_full_map, _full_missing = reconcile_ac._dispositions_of(
    {"dispositions": _EV_D}, reconcile_ac.EVIDENCE_SLOTS)
assert_eq("#1580 a complete disposition set leaves nothing undischarged",
          [], _full_missing)
assert_eq("#1580 a complete disposition set is reported for every named slot",
          sorted(reconcile_ac.EVIDENCE_SLOTS), sorted(_full_map))
_part = dict(_EV_D)
_dropped_slot = reconcile_ac.EVIDENCE_SLOTS[0]
del _part[_dropped_slot]
assert_eq("#1580 a dropped slot is named as undischarged",
          [_dropped_slot],
          reconcile_ac._dispositions_of({"dispositions": _part},
                                        reconcile_ac.EVIDENCE_SLOTS)[1])
assert_eq("#1580 an absent dispositions block leaves every slot undischarged",
          sorted(reconcile_ac.EVIDENCE_SLOTS),
          sorted(reconcile_ac._dispositions_of({}, reconcile_ac.EVIDENCE_SLOTS)[1]))
assert_eq("#1580 a non-object dispositions block leaves every slot undischarged",
          sorted(reconcile_ac.EVIDENCE_SLOTS),
          sorted(reconcile_ac._dispositions_of({"dispositions": "yes all of them"},
                                               reconcile_ac.EVIDENCE_SLOTS)[1]))

# AC3 — an explicit `no` on EVERY slot fully discharges them: the criterion still
# reconciles `satisfied`. A gate that punished `no` would produce false `yes`.
_recon_no = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "ok",
      "dispositions": _disp_all(reconcile_ac.EVIDENCE_SLOTS, "no")}],
    [{"criterion": 1, "status": "satisfied", "evidence": "ok",
      "dispositions": _disp_all(reconcile_ac.CLAIM_SLOTS, "no")}])
assert_eq("#1580 an all-`no` disposition set still reconciles satisfied",
          "satisfied", _recon_no["criteria"][0]["status"])
assert_eq("#1580 an all-`no` disposition set leaves nothing undischarged",
          [], _recon_no["criteria"][0]["undischarged_slots"])

# AC4 — one MISSING slot on one side forces that side to `unestablished` BEFORE the
# statuses are paired, so the criterion reconciles `unestablished` even though both
# verifiers reported `satisfied`. This is the substitution the issue exists to catch.
_ev_gap = dict(_EV_D)
del _ev_gap[reconcile_ac.EVIDENCE_SLOTS[0]]
_recon_gap = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "ok",
      "dispositions": _ev_gap}],
    [{"criterion": 1, "status": "satisfied", "evidence": "ok",
      "dispositions": _CL_D}])
_gap_rec = _recon_gap["criteria"][0]
assert_eq("#1580 a missing slot forces the criterion to unestablished",
          "unestablished", _gap_rec["status"])
assert_eq("#1580 a criterion with a missing slot blocks", True, _gap_rec["blocks"])
assert_eq("#1580 the undischarged slot is named, side-qualified",
          [f"evidence:{reconcile_ac.EVIDENCE_SLOTS[0]}"],
          _gap_rec["undischarged_slots"])
# The side whose dispositions were complete keeps its own reported status in the
# record, so the orchestrator can see WHICH verifier failed to attest.
assert_eq("#1580 the complete side's own status is still reported",
          "satisfied", _gap_rec["claim_status"])
assert_eq("#1580 the undischarged side's status reads unestablished",
          "unestablished", _gap_rec["evidence_status"])
# The gate the orchestrator actually routes on is the AGGREGATE, not the per-criterion
# row: a regression computing these from a pre-`_side` status would leave the row correct
# and still report a clean pass — the false green this issue exists to prevent.
assert_eq("#1580 a criterion blocked by a missing slot reaches blocking[]",
          [1], _recon_gap["blocking"])
assert_eq("#1580 a missing slot clears all_satisfied",
          False, _recon_gap["all_satisfied"])

# An ABSENT record is a missing vote, not an attestation failure: it names no
# undischarged slot, so the field that routes the remedy (re-dispatch to restate the
# record) cannot be armed for a side that never produced one.
_recon_absent = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "x", "dispositions": _EV_D}],
    [])
_absent_rec = _recon_absent["criteria"][0]
assert_eq("#1580 an absent record names no undischarged slots",
          [], _absent_rec["undischarged_slots"])
assert_eq("#1580 an absent record still blocks as a missing vote",
          "unestablished", _absent_rec["status"])
assert_eq("#1580 the present side's own status survives an absent counterpart",
          "satisfied", _absent_rec["evidence_status"])

# A wholly absent dispositions block is the same failure — silence is not compliance.
_recon_silent = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "ok"}],
    [{"criterion": 1, "status": "satisfied", "evidence": "ok"}])
assert_eq("#1580 a report with no dispositions at all reconciles unestablished",
          "unestablished", _recon_silent["criteria"][0]["status"])
# Do not relax this to a sorted()/set comparison: the expected list is the concatenation
# order the record is built in, and a sorted compare would pass a regression that
# reordered the two sides or a side's own slots.
assert_eq("#1580 both sides' slots are named undischarged when neither attests, "
          "evidence-side then claim-side, each in declared order",
          [f"evidence:{s}" for s in reconcile_ac.EVIDENCE_SLOTS]
          + [f"claim:{s}" for s in reconcile_ac.CLAIM_SLOTS],
          _recon_silent["criteria"][0]["undischarged_slots"])

# AC5 — the dispositions reach the reconciled output, so the orchestrator records them
# durably alongside the verdict rather than letting them die with the dispatch return.
_recon_carry = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "ok", "dispositions": _EV_D}],
    [{"criterion": 1, "status": "satisfied", "evidence": "ok", "dispositions": _CL_D}])
_carry = _recon_carry["criteria"][0]
assert_eq("#1580 a complete disposition set reconciles satisfied",
          "satisfied", _carry["status"])
assert_eq("#1580 the evidence verifier's dispositions ride into the output",
          _EV_D, _carry["evidence_dispositions"])
assert_eq("#1580 the claim verifier's dispositions ride into the output",
          _CL_D, _carry["claim_dispositions"])

# An UNRECOGNIZED slot name is ignored rather than accepted as covering a named one —
# otherwise a verifier could discharge the whole set by inventing slot names.
_bogus = dict(_EV_D)
_bogus.pop(reconcile_ac.EVIDENCE_SLOTS[0])
_bogus["totally-made-up-slot"] = "yes (invented)"
assert_eq("#1580 an invented slot does not discharge a named one",
          [reconcile_ac.EVIDENCE_SLOTS[0]],
          reconcile_ac._dispositions_of({"dispositions": _bogus},
                                        reconcile_ac.EVIDENCE_SLOTS)[1])

# An undischarged slot is EXCLUDED from the carried map — a regression carrying the
# unparseable value through would put an unattested slot into the durable audit record
# reading as attested.
_partial = dict(_EV_D)
_partial[reconcile_ac.EVIDENCE_SLOTS[1]] = "perhaps"
_partial_map, _partial_missing = reconcile_ac._dispositions_of(
    {"dispositions": _partial}, reconcile_ac.EVIDENCE_SLOTS)
assert_eq("#1580 an unparseable slot is absent from the carried disposition map",
          False, reconcile_ac.EVIDENCE_SLOTS[1] in _partial_map)
assert_eq("#1580 the parsed slots beside it still ride into the map",
          True, reconcile_ac.EVIDENCE_SLOTS[0] in _partial_map)

# Do not delete a breadcrumb assertion: every status assertion above stays green without
# them, and the silent-case assertion is what stops a breadcrumb-on-every-slot regression.
def _disp_stderr(record, slots, side):
    """(undischarged, stderr) for one `_dispositions_of` call."""
    _buf = io.StringIO()
    with contextlib.redirect_stderr(_buf):
        _res = reconcile_ac._dispositions_of(record, slots, side)
    return _res[1], _buf.getvalue()


_bc_missing, _bc_err = _disp_stderr(
    {"dispositions": {reconcile_ac.EVIDENCE_SLOTS[0]: "maybe (x)"}},
    reconcile_ac.EVIDENCE_SLOTS, "evidence")
assert_eq("#1580 an unparseable slot's breadcrumb names the slot",
          True, repr(reconcile_ac.EVIDENCE_SLOTS[0]) in _bc_err)
assert_eq("#1580 an unparseable slot's breadcrumb names the side",
          True, "evidence report" in _bc_err)
# An OMITTED slot is silent: the verifier said nothing, which the status already carries.
_, _bc_silent = _disp_stderr({"dispositions": {}}, reconcile_ac.EVIDENCE_SLOTS,
                             "evidence")
assert_eq("#1580 an omitted slot emits no breadcrumb", "", _bc_silent)
# A JSON `null` is a STATED slot that does not parse, so it is breadcrumbed like any
# other unparseable value rather than passing as an omission.
_, _bc_null = _disp_stderr(
    {"dispositions": {reconcile_ac.EVIDENCE_SLOTS[0]: None}},
    reconcile_ac.EVIDENCE_SLOTS, "evidence")
assert_eq("#1580 a null-valued slot is breadcrumbed as stated-but-unparseable",
          True, repr(reconcile_ac.EVIDENCE_SLOTS[0]) in _bc_null)
# A non-object `dispositions`, and an object naming none of the slots, each block every
# criterion of that side — undiagnosable without a breadcrumb naming the shape.
_, _bc_type = _disp_stderr({"dispositions": "yes all of them"},
                           reconcile_ac.EVIDENCE_SLOTS, "evidence")
assert_eq("#1580 a non-object dispositions block names its observed type",
          True, "not an object" in _bc_type)
_, _bc_keys = _disp_stderr({"dispositions": {"command_run": "yes (underscored)"}},
                           reconcile_ac.EVIDENCE_SLOTS, "evidence")
assert_eq("#1580 an all-near-miss key set names the keys it saw",
          True, "names none of the expected slots" in _bc_keys)

# A duplicate-poisoned record names no slots either: like an absent record it is a vote
# never usably cast, and naming its slots would route a report-shape defect to the
# restate-the-record remedy, which cannot fix it.
_recon_dup1580 = reconcile_ac.reconcile(
    _ev_recs({"criterion": 1, "status": "unmet", "evidence": "a"},
             {"criterion": 1, "status": "satisfied", "evidence": "b"}),
    _cl_recs({"criterion": 1, "status": "satisfied", "evidence": "c"}))
assert_eq("#1580 a duplicate-poisoned record names no undischarged slots",
          [], _recon_dup1580["criteria"][0]["undischarged_slots"])
assert_eq("#1580 a duplicate-poisoned record still blocks",
          "unestablished", _recon_dup1580["criteria"][0]["status"])
# The poison marker's VALUE is an identity-checked sentinel, so a report cannot forge it
# to skip its own slot scoring and blank the audit fields this gate exists to produce.
_recon_forged = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "satisfied", "evidence": "x",
      "_reconcile_poisoned": True}],
    [{"criterion": 1, "status": "satisfied", "evidence": "y",
      "_reconcile_poisoned": True}])
assert_eq("#1580 a report cannot forge the poison marker to skip slot scoring",
          sorted([f"evidence:{s}" for s in reconcile_ac.EVIDENCE_SLOTS]
                 + [f"claim:{s}" for s in reconcile_ac.CLAIM_SLOTS]),
          sorted(_recon_forged["criteria"][0]["undischarged_slots"]))

# A side that concluded a real `unmet` but left a slot undischarged keeps that verdict in
# `*_status_reported`. Without it the routing rule that fires only when a criterion blocks
# SOLELY on undischarged slots cannot decide its own precondition, and a concrete failing
# detail is routed to "restate your record" instead of to a fix.
_ev_unmet = dict(_EV_D)
del _ev_unmet[reconcile_ac.EVIDENCE_SLOTS[2]]
_recon_unmet = reconcile_ac.reconcile(
    [{"criterion": 1, "status": "unmet", "evidence": "clause X has no assertion",
      "dispositions": _ev_unmet}],
    [{"criterion": 1, "status": "unmet", "evidence": "same gap",
      "dispositions": _CL_D}])
_unmet_rec = _recon_unmet["criteria"][0]
assert_eq("#1580 the gate still overrides the gated status",
          "unestablished", _unmet_rec["evidence_status"])
assert_eq("#1580 the side's concluded verdict survives the override",
          "unmet", _unmet_rec["evidence_status_reported"])
assert_eq("#1580 a side with no attestation gap reports the same status both ways",
          "unmet", _unmet_rec["claim_status_reported"])
# The override's breadcrumb is the run's stderr-side signal that a side was downgraded;
# deleting it leaves every assertion here green.
_ovr_buf = io.StringIO()
with contextlib.redirect_stderr(_ovr_buf):
    reconcile_ac.reconcile(
        [{"criterion": 1, "status": "unmet", "evidence": "x",
          "dispositions": _ev_unmet}],
        [{"criterion": 1, "status": "unmet", "evidence": "y",
          "dispositions": _CL_D}])
assert_eq("#1580 the forced-unestablished override names the side that concluded",
          True, "the evidence report concluded 'unmet'" in _ovr_buf.getvalue())
# A side that concluded `unestablished` and also dropped a slot emits no override
# breadcrumb — the status did not change, so there is nothing to report.
_une_buf = io.StringIO()
with contextlib.redirect_stderr(_une_buf):
    reconcile_ac.reconcile(
        [{"criterion": 1, "status": "unestablished", "evidence": "x",
          "dispositions": _ev_unmet}], [])
assert_eq("#1580 no override breadcrumb when the concluded status was already "
          "unestablished", False, "concluded" in _une_buf.getvalue())
# `*_status_reported` is normalized, so out-of-vocabulary agent text cannot leak into the
# field the restate-vs-fix routing reads.
assert_eq("#1580 a bogus reported status normalizes rather than leaking",
          "unestablished",
          reconcile_ac.reconcile(
              [{"criterion": 1, "status": "probably", "evidence": "x",
                "dispositions": _ev_unmet}],
              [{"criterion": 1, "status": "unmet", "evidence": "y",
                "dispositions": _CL_D}])["criteria"][0]["evidence_status_reported"])
# An absent record reports `unestablished` on both, so the field never invents a verdict.
assert_eq("#1580 an absent record reports no concluded verdict",
          "unestablished",
          reconcile_ac.reconcile(
              [{"criterion": 1, "status": "satisfied", "evidence": "x",
                "dispositions": _EV_D}], [])["criteria"][0]["claim_status_reported"])

# The charters carry the slot names TWICE — the `| Slot |` table and the `dispositions`
# blocks of their worked JSON examples. The example is what a verifier copies, so pin it
# too: a rename reconciled into the table alone would ship a template whose every value
# scores undischarged, hard-blocking Phase 3.4 with the suite green.
# structural-pin-ok: cross-file-phase-contract -- the charter's worked example IS the
# template the dispatched verifier reproduces; the gate grades what it produces.
for _acv_file, _acv_slots in (("ac-evidence-verifier.md", reconcile_ac.EVIDENCE_SLOTS),
                              ("ac-claim-verifier.md", reconcile_ac.CLAIM_SLOTS)):
    _acv_body = (SCRIPTS.parent / "agents" / _acv_file).read_text(encoding="utf-8")
    # Scope to inside each `"dispositions": { … }` object so the sibling `"evidence"`
    # field on the same line family cannot be read as a slot.
    _acv_blocks = re.findall(r'"dispositions":\s*\{(.*?)\}', _acv_body, re.DOTALL)
    assert_eq(f"#1580 {_acv_file}: the worked example carries dispositions blocks",
              True, len(_acv_blocks) > 0)
    for _blk_i, _blk in enumerate(_acv_blocks):
        _pairs = re.findall(r'"([a-z-]+)":\s*"((?:yes|no)[^"]*)"', _blk)
        assert_eq(f"#1580 {_acv_file} example {_blk_i}: names exactly the gate's slots",
                  sorted(_acv_slots), sorted(k for k, _ in _pairs))
        assert_eq(f"#1580 {_acv_file} example {_blk_i}: every value parses as a "
                  f"discharging disposition",
                  [], reconcile_ac._dispositions_of(
                      {"dispositions": dict(_pairs)}, _acv_slots)[1])

# A reasonless slot value is undischarged end-to-end, not merely at the parser: a
# verifier writing bare `yes` must not clear the gate.
_reasonless = dict(_EV_D)
_reasonless[reconcile_ac.EVIDENCE_SLOTS[0]] = "yes"
assert_eq("#1580 a reasonless slot value blocks the criterion end-to-end",
          "unestablished",
          reconcile_ac.reconcile(
              [{"criterion": 1, "status": "satisfied", "evidence": "ok",
                "dispositions": _reasonless}],
              [{"criterion": 1, "status": "satisfied", "evidence": "ok",
                "dispositions": _CL_D}])["criteria"][0]["status"])


# ── issue #1678: explicit UTF-8 decoding on PRFlow local text-file readers ──────
# parse-acs.py --body-file, workpad.py::_read_section_file, and
# branch-for-issue.py --title-file must decode local files as UTF-8 explicitly
# (never the ambient locale codec) so non-ASCII issue text survives on Windows,
# and a decode failure routes through the parser, workpad, and branch-create
# clean non-zero paths (no traceback). AC5's static guard below enforces the rule across ALL tracked
# scripts/*.py; AC1/AC2/AC3 and the CLI half of AC4 are the hostile-codec
# subprocess RED->GREEN tests in lib/test/run.sh (the entry-path decode is only
# observable when the script runs as a CLI under a forced-ASCII file codec).
print("issue #1678: explicit UTF-8 decoding on local text-file readers")

# AC5 — the text-reader guard. Families checked, complete by construction:
#   read_text  (pathlib.Path.read_text; encoding is positional slot 1)
#   Path.open  (pathlib .open;          encoding is positional slot 3)
#   open       (builtin;                encoding is positional slot 4)
# os.open is the raw fd syscall (integer flags, no text decode) and is NOT a
# text reader — excluding it is why a bare `os.open(path, flags)` must not flag.
_U8_FAMILIES = {"read_text", "Path.open", "open"}
_U8_ENC_SLOT = {"read_text": 1, "Path.open": 3, "open": 4}


def _u8_os_aliases(tree):
    al = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "os":
                    al.add(a.asname or a.name)
    return al


def _u8_classify(call, os_aliases):
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr == "read_text":
            return "read_text"
        if f.attr == "open":
            if isinstance(f.value, ast.Name) and f.value.id in os_aliases:
                return None  # os.open — not a text reader
            return "Path.open"
    elif isinstance(f, ast.Name) and f.id == "open":
        return "open"
    return None


def _u8_mode_node(call, family):
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    if family == "Path.open" and call.args:
        return call.args[0]
    if family == "open" and len(call.args) >= 2:
        return call.args[1]
    return None


def _u8_is_binary(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and "b" in node.value)


def _u8_has_encoding(call, family):
    # Keyword OR positional encoding form both count (the AC's requirement).
    if any(kw.arg == "encoding" for kw in call.keywords):
        return True
    return len(call.args) >= _U8_ENC_SLOT[family]


def _u8_scan_source(src, filename="<planted>"):
    tree = ast.parse(src, filename=filename)
    os_aliases = _u8_os_aliases(tree)
    fams, viols = set(), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fam = _u8_classify(node, os_aliases)
        if fam is None:
            continue
        fams.add(fam)
        mode = _u8_mode_node(node, fam)
        if mode is not None and _u8_is_binary(mode):
            continue  # binary mode takes no encoding
        if not _u8_has_encoding(node, fam):
            viols.append((filename, node.lineno, fam))
    return fams, viols


# Real scan over the tracked scripts/*.py population (git ls-files: index-reading,
# never a recursive filesystem walk into sibling worktrees — issue #711).
_u8_tracked = [p for p in _subprocess.run(
    ["git", "ls-files", "-z", "--", "scripts/*.py"],
    cwd=str(SCRIPTS.parent), capture_output=True, text=True, check=True
).stdout.split("\0") if p]
assert_eq("#1678 AC5: tracked scripts/*.py enumeration is non-empty (guard has a population)",
          True, len(_u8_tracked) >= 10)
_u8_all_fams, _u8_all_viols = set(), []
for _rel in _u8_tracked:
    _f, _v = _u8_scan_source((SCRIPTS.parent / _rel).read_text(encoding="utf-8"), _rel)
    _u8_all_fams |= _f
    _u8_all_viols.extend(_v)
assert_eq("#1678 AC5: every text-reader in tracked scripts/*.py decodes UTF-8 explicitly",
          [], _u8_all_viols)
# All three families are exercised over the real tree AND the scan produces no
# out-of-taxonomy token — the "exactly these three, complete by construction" claim.
assert_eq("#1678 AC5: the checked text-reader family set is exactly the three",
          _U8_FAMILIES, _u8_all_fams)

# Planted-omission self-check: a bare call in EACH family (no encoding) is flagged.
_u8_planted_prelude = "import os\nfrom pathlib import Path\np = Path('x')\n"
for _fam, _snip in {"read_text": "p.read_text()",
                    "Path.open": "p.open('r')",
                    "open": "open('x')"}.items():
    _f, _v = _u8_scan_source(_u8_planted_prelude + _snip + "\n")
    assert_eq(f"#1678 AC5 self-check: a bare {_fam} (no encoding) is flagged RED", 1, len(_v))
    assert_eq(f"#1678 AC5 self-check: the flag names the {_fam} family",
              _fam, _v[0][2] if _v else None)
# And the accepted forms — keyword encoding, positional encoding, binary mode,
# and os.open — must NOT flag.
for _snip in ("p.read_text(encoding='utf-8')", "p.read_text('utf-8')",
              "p.open('r', encoding='utf-8')", "p.open('r', -1, 'utf-8')",
              "open('x', encoding='utf-8')", "open('x', 'w', -1, 'utf-8')",
              "open('x', 'rb')", "p.open('rb')", "os.open('x', 0)"):
    _f, _v = _u8_scan_source(_u8_planted_prelude + _snip + "\n")
    assert_eq(f"#1678 AC5 self-check: accepted form is not flagged: {_snip}", [], _v)

# AC2 (completeness half) — the _read_section_file flag set is exactly the three,
# by construction: collect the flag literal from the _read_section_file call
# sites and assert the set (the assertion below pins it to the three).
_u8_wp_tree = ast.parse((SCRIPTS / "workpad.py").read_text(encoding="utf-8"))
_u8_rsf_flags = set()
for _n in ast.walk(_u8_wp_tree):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name)
            and _n.func.id == "_read_section_file" and len(_n.args) >= 2
            and isinstance(_n.args[1], ast.Constant)):
        _u8_rsf_flags.add(_n.args[1].value)
assert_eq("#1678 AC2: _read_section_file flag set is exactly the three (complete by construction)",
          {"--replace-plan-file", "--replace-acs-file", "--set-reproduction-file"},
          _u8_rsf_flags)

# AC4 (workpad half) — invalid UTF-8 through `workpad.py update --replace-acs-file`
# exits non-zero with a flag-specific UTF-8 diagnostic (no traceback) and makes NO
# GitHub PATCH. Driven through the real cmd_update mutation boundary (only the gh
# transport is stubbed by _drive_cmd_update; decoding and mutation are NOT mocked).
# The try/except keeps a regression's raw UnicodeDecodeError from aborting the file
# mid-run — on the fixed code the read raises _UpdateError and cmd_update exits 1.
_u8_bad = tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False)
_u8_bad.write(b"\xff\xfe\x00 not utf-8 \xe2\x28")
_u8_bad.close()
try:
    _u8c, _u8o, _u8e, _u8p = _drive_cmd_update(IDX_BODY, replace_acs_file=_u8_bad.name)
except UnicodeDecodeError:
    _u8c, _u8o, _u8e, _u8p = "raw-decode-error", "", "", "unknown"
assert_eq("#1678 AC4 workpad: invalid-UTF-8 --replace-acs-file exits non-zero (clean, not a crash)",
          1, _u8c)
assert_eq("#1678 AC4 workpad: no GitHub PATCH was made", None, _u8p)
assert_eq("#1678 AC4 workpad: stderr carries the flag-specific UTF-8 diagnostic", True,
          "--replace-acs-file" in _u8e and "not valid UTF-8" in _u8e)
assert_eq("#1678 AC4 workpad: the diagnostic is clean (no Python traceback)", True,
          "Traceback (most recent call last)" not in _u8e)
os.remove(_u8_bad.name)


# ── issue #1655: render-pr-provenance-line.py ───────────────────────────────────
# The helper renders the /prflow:implement draft-PR provenance line. Driven as a
# subprocess against a fixture COPY of the helper placed beside a fixture manifest, so
# the beside-the-helper version resolution is genuinely exercised; the session model
# comes from a fixture transcript store injected by env, never the developer's real one.
# Every assertion pins a SPECIFIC rendered line / breadcrumb / exit code derived from the
# issue's acceptance criteria (never "did not crash").
_PROV_SRC = (SCRIPTS / 'render-pr-provenance-line.py').read_text(encoding='utf-8')
_PROV_UNSET = object()


def _prov_transcript(*, model=None, resolved_model=None, extra=()):
    """Build fixture transcript lines: an optional user Agent-dispatch record carrying
    resolvedModel, then an optional assistant record carrying message.model, then extras."""
    lines = []
    if resolved_model is not None:
        lines.append(json.dumps({"type": "user", "resolvedModel": resolved_model}))
    if model is not None:
        lines.append(json.dumps({"type": "assistant", "message": {"model": model}}))
    lines.extend(extra)
    return lines


def _prov_run(*, version="9.9.9", config=_PROV_UNSET, effort=_PROV_UNSET,
              session_id=_PROV_UNSET, transcript=None, write_transcript=True,
              config_dir=_PROV_UNSET, prflow_version=None, command="/prflow:implement"):
    """Drive a fixture copy of the helper; return (stdout_stripped, stderr, rc).
    command names the value passed to the now-required --command flag; command=None
    omits the flag entirely (the missing-required-argument case)."""
    d = tempfile.mkdtemp(prefix="prov1655-")
    try:
        scripts_dir = os.path.join(d, "scripts")
        os.makedirs(scripts_dir)
        helper = os.path.join(scripts_dir, "render-pr-provenance-line.py")
        Path(helper).write_text(_PROV_SRC, encoding="utf-8")
        if version is not None:
            os.makedirs(os.path.join(d, ".claude-plugin"))
            payload = version if not isinstance(version, str) else {"version": version}
            Path(os.path.join(d, ".claude-plugin", "plugin.json")).write_text(
                json.dumps(payload), encoding="utf-8")
        env = dict(os.environ)
        for k in ("CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR"):
            env.pop(k, None)
        if effort is not _PROV_UNSET and effort is not None:
            env["CLAUDE_EFFORT"] = effort
        sid = "sess-1655-fixture" if session_id is _PROV_UNSET else session_id
        if sid is not None:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        store = os.path.join(d, "store") if config_dir is _PROV_UNSET else config_dir
        if store is not None:
            env["CLAUDE_CONFIG_DIR"] = store
        if write_transcript and transcript is not None and sid and store:
            segment = re.sub(r"[^a-zA-Z0-9]", "-", d)
            proj = os.path.join(store, "projects", segment)
            os.makedirs(proj, exist_ok=True)
            Path(os.path.join(proj, f"{sid}.jsonl")).write_text(
                "\n".join(transcript), encoding="utf-8")
        argv = [sys.executable, helper]
        if command is not None:
            argv += ["--command", command]
        if config is not _PROV_UNSET:
            cfg = os.path.join(d, "cfg.json")
            body = config if isinstance(config, str) else json.dumps(config)
            # prflow_version alongside — the config value that must NOT win over the manifest.
            Path(cfg).write_text(body, encoding="utf-8")
            argv += ["--config", cfg]
        proc = _subprocess.run(argv, cwd=d, env=env, capture_output=True, text=True)
        return proc.stdout.rstrip("\n"), proc.stderr, proc.returncode
    finally:
        shutil.rmtree(d, ignore_errors=True)


_PB = "Generated via /prflow:implement"
_PB_CI = "Generated via /prflow:create-issue"


def _pl(inner):
    """The renderer wraps the whole provenance line in single-underscore italics."""
    return f"_{inner}_"


# Full line — version, model, effort all established.
_o, _e, _rc = _prov_run(version="2.32.58", effort="high",
                        transcript=_prov_transcript(model="claude-opus-5"))
assert_eq("#1655 full line names version, model, effort", _pl(f"{_PB} (v2.32.58, claude-opus-5, high)"), _o)
assert_eq("#1655 full line exits 0", 0, _rc)
assert_eq("#1655 rendered line carries no backtick", False, "`" in _o)

# Guarantee class: neither model nor effort — version alone, no empty punctuation, breadcrumbs name each.
_o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False)
assert_eq("#1655 only version established -> version alone", _pl(f"{_PB} (v2.32.58)"), _o)
assert_eq("#1655 version-alone exits 0", 0, _rc)
assert_eq("#1655 breadcrumb names omitted effort", True, "effort unestablished" in _e)
assert_eq("#1655 breadcrumb names omitted model", True, "model unestablished" in _e)

# Effort unset, model readable -> version + model only.
_o, _e, _rc = _prov_run(version="2.32.58", transcript=_prov_transcript(model="claude-opus-5"))
assert_eq("#1655 effort unset -> version + model only", _pl(f"{_PB} (v2.32.58, claude-opus-5)"), _o)

# Model unavailable, effort set -> version + effort only.
_o, _e, _rc = _prov_run(version="2.32.58", effort="max", write_transcript=False)
assert_eq("#1655 no model, effort set -> version + effort only", _pl(f"{_PB} (v2.32.58, max)"), _o)

# CLAUDE_EFFORT whitespace-only is unestablished.
_o, _e, _rc = _prov_run(version="2.32.58", effort="   ", write_transcript=False)
assert_eq("#1655 whitespace-only CLAUDE_EFFORT is unestablished", _pl(f"{_PB} (v2.32.58)"), _o)

# --command names the command in the printed line; the value passed is echoed verbatim (AC1, AC2).
_o, _e, _rc = _prov_run(version="7.7.7", write_transcript=False, command="/prflow:create-issue")
assert_eq("#1655 --command /prflow:create-issue version-only line", _pl(f"{_PB_CI} (v7.7.7)"), _o)
assert_eq("#1655 --command create-issue version-only exits 0", 0, _rc)
_o, _e, _rc = _prov_run(version="7.7.7", write_transcript=False, command="/prflow:implement")
assert_eq("#1655 --command /prflow:implement version-only line", _pl(f"{_PB} (v7.7.7)"), _o)
# The command name in the printed line is exactly the value passed to --command.
_o, _e, _rc = _prov_run(version="2.32.58", effort="high",
                        transcript=_prov_transcript(model="claude-opus-5"),
                        command="/prflow:create-issue")
assert_eq("#1655 create-issue full line names version, model, effort",
          _pl(f"{_PB_CI} (v2.32.58, claude-opus-5, high)"), _o)

# --command omitted entirely: nothing on stdout, usage to stderr, exit non-zero (AC3).
_o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False, command=None)
assert_eq("#1655 missing --command prints nothing on stdout", "", _o)
assert_eq("#1655 missing --command exits non-zero", True, _rc != 0)
assert_eq("#1655 missing --command writes a usage message to stderr",
          True, "usage" in _e.lower() and "--command" in _e)

# A --command value carrying a shell-active or control char: nothing on stdout, reason on
# stderr, exit 0 (AC13 — the five classes: backtick, dollar, backslash, double-quote, control).
for _cmdval, _lbl in (
    ("/prflow:c`id`", "backtick"),
    ("/prflow:c$(id)", "dollar"),
    ("/prflow:c\\x", "backslash"),
    ('/prflow:c"x', "double-quote"),
    ("/prflow:c\tx", "control-tab"),
    ("/prflow:c\nx", "control-newline"),
    # The control class runs \x00-\x1f AND \x7f; \x7f is the isolated upper end, so a
    # regex edit dropping it would go unnoticed without this row. \x00 cannot be tested
    # here: an embedded null byte raises ValueError before execve, so no argv can carry it.
    ("/prflow:c\x7fx", "control-del"),
):
    _o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False, command=_cmdval)
    assert_eq(f"#1655 shell-active --command ({_lbl}) prints nothing on stdout", "", _o)
    assert_eq(f"#1655 shell-active --command ({_lbl}) exits 0", 0, _rc)
    # Assert the drop names the COMMAND specifically — a generic non-empty check would pass
    # if an unrelated value (model/effort) had been the thing dropped.
    assert_eq(f"#1655 shell-active --command ({_lbl}) stderr names the command drop",
              True, "command omitted" in _e)

# A blank / whitespace-only --command value: nothing on stdout, a NAMED breadcrumb (not a
# silent drop), exit 0 — argparse only checks presence, so this present-but-blank case is
# between the missing-argument and shell-active cases.
for _blank in ("", "   "):
    _o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False, command=_blank)
    assert_eq("#1655 blank --command prints nothing on stdout", "", _o)
    assert_eq("#1655 blank --command exits 0", 0, _rc)
    assert_eq("#1655 blank --command breadcrumbs the blank drop (not silent)",
              True, "command omitted (blank" in _e)

# An inert --command value the helper has never heard of renders verbatim: the helper
# carries no command allowlist, so adding one would break every non-canonical caller.
_o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False, command="/prflow:foo")
assert_eq("#1655 non-canonical inert --command renders verbatim (no allowlist)",
          _pl("Generated via /prflow:foo (v2.32.58)"), _o)
assert_eq("#1655 non-canonical inert --command exits 0", 0, _rc)

# Case variant: a --command value with a leading slash renders unchanged.
_o, _e, _rc = _prov_run(version="2.32.58", write_transcript=False, command="/prflow:implement")
assert_eq("#1655 leading-slash --command value is preserved", _pl(f"{_PB} (v2.32.58)"), _o)

# Beside-the-helper manifest wins over a config prflow_version that differs.
_o, _e, _rc = _prov_run(version="1.1.1", write_transcript=False,
                        config={"prflow_version": "2.2.2", "prflow": {}})
assert_eq("#1655 names the beside-the-helper manifest version", _pl(f"{_PB} (v1.1.1)"), _o)
assert_eq("#1655 does NOT name the config prflow_version", False, "2.2.2" in _o)

# resolvedModel is never a source; the bare assistant model wins.
_o, _e, _rc = _prov_run(version="2.32.58",
                        transcript=_prov_transcript(resolved_model="claude-opus-5[1m]",
                                                    model="claude-sonnet-5"))
assert_eq("#1655 names the assistant message.model, not resolvedModel",
          _pl(f"{_PB} (v2.32.58, claude-sonnet-5)"), _o)
assert_eq("#1655 the marked resolvedModel id is never emitted", False, "[1m]" in _o)

# Most-recent assistant record wins.
_o, _e, _rc = _prov_run(version="2.32.58",
                        transcript=_prov_transcript(model="claude-old") +
                        _prov_transcript(model="claude-new"))
assert_eq("#1655 names the MOST RECENT assistant model", _pl(f"{_PB} (v2.32.58, claude-new)"), _o)

# Truncated final record -> last complete assistant record still read.
_trunc = _prov_transcript(model="claude-opus-5") + ['{"type": "assistant", "message": {"mod']
_o, _e, _rc = _prov_run(version="2.32.58", transcript=_trunc)
assert_eq("#1655 truncated final record -> last complete record wins",
          _pl(f"{_PB} (v2.32.58, claude-opus-5)"), _o)
assert_eq("#1655 truncated-record run exits 0", 0, _rc)

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
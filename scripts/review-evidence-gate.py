#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail a cloud review run whose posted verdict lacks phase-execution evidence (issue #2075).

THE QUESTION IT ANSWERS. The `/prflow:review` engine is the merge-gating judge, but
nothing on the cloud tier checks that a run that posted a verdict actually executed its
phases — every live signal (progress ticks, tally lines, telemetry) is written by the
same agent being checked, so a run that skips its work and still posts a verdict ends
green. This gate compares the posted verdict against machine-readable evidence the
engine's own entry gate leaves in its run-scoped directory: a phase log appended one
line per phase entry, a generator double-failure record, and a Phase 0.3.6 hit record.

WHAT IT READS, AND WHY EACH INPUT IS SHAPED THIS WAY.
  --pre-inventory FILE    a pre-engine snapshot {"run_roots": [...], "review_ids": [...]}
                          the workflow step records immediately before the engine step.
                          Run roots and reviews that appear DURING the engine step are
                          attributed to this run by set-difference — no run key from the
                          engine, no clock comparison (the engine cannot expand an env var
                          under the cloud matcher, so it stamps no run identity).
  --post-tree-root DIR    the repo root whose `.prflow/tmp/review/` tree is re-listed now.
  --reviews-payload FILE  the PR's reviews-API JSON array, fetched post-engine. The
                          reviewed head is read from THIS run's verdict marker's own
                          `head=`, so no runner-supplied head is needed or trusted.
  --base-ref REF          the PR base ref for the diff-classification recompute (may be
                          empty; then origin/HEAD is used, as workpad.py does).
  --repo-root DIR         the repo root for the classification recompute.
  --reviewer-login LOGIN  the run's own reviewer identity (`.user.login`); a human's
                          review is never mistaken for the run's own.
  --vendored-engine-root  the checked-out review engine root; if it does not yet carry
                          the phase-log instruction, an older vendored engine is assumed
                          and the check is UNESTABLISHED rather than a false failure.

CLASSIFICATION IS NOT RE-COPIED (AC4). The "does this diff owe the checklist phases?"
decision is `scripts/workpad.py`'s own `_review_coverage_profile_disproof` over
`_recompute_diff_facts`, imported here so the ceilings and engine-source arms live in one
implementation. An unloadable workpad.py routes to the unestablished arm, never a crash.

OUTPUT CONTRACT. One machine-readable verdict token as stdout line 1, from the closed
vocabulary below, followed by human-readable detail lines (the durable-comment body). It
ALWAYS exits 0 — the invoking workflow step decides the job's pass/fail from the token, so
`set -euo pipefail` in that step never dies mid-decision before the comment/dismissal/flip
actions run.

  pass <arm>                 a verdict was posted and its required evidence is present, OR
                             no checklist was owed. <arm> is one of legitimate-skip,
                             generator-failure-skip, blocker-recheck-hit, checklist-phases-ran.
  no-verdict                 no marker-bearing verdict was posted by this run for the head.
  fail missing=<c,s,v> review_id=<id> review_state=<state>
                             a verdict was posted, the checklist was owed, and the run root
                             attributed to this run holds no phase log recording it ran.
  unestablished <reason>     an evidence state the gate could not settle — reported neither
                             as a pass nor as a failure.

UNKNOWN IS NOT ZERO. A malformed phase log, an unreadable run root, an unresolvable diff
range, an unparseable reviews payload, an ambiguous run-root delta, or an older vendored
engine are each UNESTABLISHED — never a pass and never laundered into a fail. Only what a
hollow run positively leaves behind — a posted verdict, a checklist owed, and a missing or
empty phase log (or no run root at all) — is the fail arm.
"""
import argparse
import importlib.util
import json
import os
import re
import sys

# The closed phase-id vocabulary the entry gate may record — the Phase routing table in
# skills/review/SKILL.md. A `phase-entry` line naming any other value is malformed.
_VALID_PHASE_IDS = frozenset(
    {'0', '0.3.6', '0.6', '1', '1.5', '2', '3', '4', '4.1.7', '4.4'})
# The checklist phase-entry records that together evidence the checklist ran — Phase 1
# (checklist generation + dedup) and Phase 2 (checklist verification). Each maps its
# phase-log line literal to a SPACE-FREE token for the machine `missing=` field, so that
# field stays one word the caller can split on (the human detail spells it out in full).
_CHECKLIST_PHASE_ENTRIES = (
    ('phase-entry phase=1', 'phase-entry-1'),
    ('phase-entry phase=2', 'phase-entry-2'),
)
# The two special records that legitimately stand in for the checklist phases.
_GENERATOR_FAILURE_RECORD = 'checklist-skip reason=failure'
_BLOCKER_RECHECK_HIT_RECORD = 'blocker-recheck-hit re-verdict=posted'
# The literal the entry-gate instruction embeds, used to detect an engine root that
# predates this change (an older vendored engine writes no phase log at all).
_PHASE_LOG_INSTRUCTION_SENTINEL = 'phase-entry phase='

_PHASE_ENTRY_RE = re.compile(r'\Aphase-entry phase=(?P<id>.*)\Z')
_VERDICT_MARKER_RE = re.compile(
    r'\A<!-- prflow:review-verdict head=(?P<head>[0-9a-fA-F]{40}) '
    r'verdict=(?P<verdict>APPROVE|REJECT) -->')

_REVIEW_SUBDIR = os.path.join('.prflow', 'tmp', 'review')

# Review states GitHub records; only these two gate a merge, so only these two are
# dismissed (a COMMENTED-state suffixed-approve verdict is left to the durable comment).
_MERGE_GATING_STATES = frozenset({'APPROVED', 'CHANGES_REQUESTED'})


def _detail(*parts):
    """One human-readable detail line assembled from comma-separated fragments — a call,
    not adjacent-literal concatenation, so the long messages below carry no implicit
    string concatenation inside a list literal."""
    return [''.join(parts)]


def _load_workpad():
    """Import scripts/workpad.py as a module so its classification lives in one place
    (AC4). Returns the module, or None when it cannot be loaded — the caller then routes
    to the unestablished arm rather than crashing."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'workpad.py')
    try:
        spec = importlib.util.spec_from_file_location('review_gate_workpad', path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # any import fault is the unestablished arm, never a crash
        return None


def _read_json(path):
    """(obj, None) on success; (None, reason) when the path is unreadable or unparseable.
    `-` reads stdin."""
    try:
        if path == '-':
            text = sys.stdin.read()
        else:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
    except OSError:
        return None, 'unreadable'
    try:
        return json.loads(text), None
    except (ValueError, UnicodeError):
        return None, 'unparseable'


def _list_run_roots(post_tree_root):
    """The set of run-root directory names under `<post_tree_root>/.prflow/tmp/review/`,
    one level deep — a run root is `.prflow/tmp/review/<slug>/<run-id>`, so the attributed
    unit is the `<slug>/<run-id>` pair. Returns (set, None) or (None, reason) when the
    tree exists but cannot be read (an I/O or permission failure — distinct from an absent
    tree, which is an empty set, not an error)."""
    base = os.path.join(post_tree_root, _REVIEW_SUBDIR)
    if not os.path.isdir(base):
        return set(), None
    roots = set()
    try:
        for slug in os.listdir(base):
            slug_dir = os.path.join(base, slug)
            if not os.path.isdir(slug_dir):
                continue
            for run_id in os.listdir(slug_dir):
                if os.path.isdir(os.path.join(slug_dir, run_id)):
                    roots.add(slug + '/' + run_id)
    except OSError:
        return None, 'run-root-tree-unreadable'
    return roots, None


def _classify_own_reviews(reviews, reviewer_login):
    """From a reviews-API array, split this-identity reviews into those carrying the
    line-1 producer verdict marker (the rule scripts/classify-head-reviews.sh reads) and
    those without it. A marked review carries the reviewed tree in its own marker `head=`
    (never a runner-supplied head), so the gate reads that as the reviewed head — which is
    what makes a /prflow:review-and-fix verdict identified against the head IT recorded,
    not the PR's current head. Returns {'marked': [(id, state, marker_head), ...],
    'unmarked': [id, ...]}, both scoped to `reviewer_login`; a non-string body is unmarked."""
    marked = []
    unmarked = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get('user')
        login = user.get('login') if isinstance(user, dict) else None
        if login != reviewer_login:
            continue
        rid = review.get('id')
        state = review.get('state')
        body = review.get('body')
        line1 = body.split('\n', 1)[0] if isinstance(body, str) else ''
        m = _VERDICT_MARKER_RE.match(line1)
        if m:
            marked.append((rid, state, m.group('head').lower()))
        else:
            unmarked.append(rid)
    return {'marked': marked, 'unmarked': unmarked}


def _read_phase_log(run_root_dir):
    """Read `<run_root_dir>/phase-log`. Returns one of:
      ('missing', None)        the file does not exist (run root present, no log)
      ('unreadable', None)     the file exists but read raised (I/O/permission)
      ('content', text)        the file's text (possibly empty)."""
    path = os.path.join(run_root_dir, 'phase-log')
    try:
        with open(path, encoding='utf-8') as fh:
            return 'content', fh.read()
    except FileNotFoundError:
        return 'missing', None
    except OSError:
        return 'unreadable', None


def _grade_phase_log(text):
    """Grade a present phase log's text. Returns one of:
      ('malformed', None)                 any non-blank line is outside the closed grammar
      ('record', 'blocker-recheck-hit')   the 0.3.6 hit record is present
      ('record', 'generator-failure')     the generator double-failure record is present
      ('checklist', missing_list)         a list of space-free tokens for the checklist
                                          phase-entry records that are absent ([] means
                                          both present)
    The grammar is total over any input and never crashes: an unrecognized non-blank line
    (wrong-typed content, a truncated line, a valid-falsy `phase=`, unknown extra text)
    makes the whole log malformed → unestablished, so a hollow log dressed with garbage is
    never read as a pass. Blank lines (a trailing newline's empty final element) are
    skipped."""
    seen = set()
    for line in text.split('\n'):
        if line == '':
            continue
        if line in (_GENERATOR_FAILURE_RECORD, _BLOCKER_RECHECK_HIT_RECORD):
            seen.add(line)
            continue
        m = _PHASE_ENTRY_RE.match(line)
        if m and m.group('id') in _VALID_PHASE_IDS:
            seen.add(line)
            continue
        return 'malformed', None
    if _BLOCKER_RECHECK_HIT_RECORD in seen:
        return 'record', 'blocker-recheck-hit'
    if _GENERATOR_FAILURE_RECORD in seen:
        return 'record', 'generator-failure'
    missing = [token for (literal, token) in _CHECKLIST_PHASE_ENTRIES
               if literal not in seen]
    return 'checklist', missing


def _engine_root_has_instruction(vendored_engine_root):
    """Whether the checked-out engine root carries the phase-log instruction — read from
    its SKILL.md. False when the file is absent/unreadable OR predates this change, so an
    older vendored engine routes to unestablished rather than a false failure."""
    path = os.path.join(vendored_engine_root, 'SKILL.md')
    try:
        with open(path, encoding='utf-8') as fh:
            return _PHASE_LOG_INSTRUCTION_SENTINEL in fh.read()
    except OSError:
        return False


def _decide(args):
    """Compute the verdict token and its human-readable detail lines. Returns
    (token, [detail...])."""
    workpad = _load_workpad()
    if workpad is None:
        return 'unestablished workpad-import-failed', _detail(
            'review-evidence-gate: could not import scripts/workpad.py — the ',
            'classification implementation is unavailable, so no checklist-',
            'requirement decision could be made.')

    pre, pre_err = _read_json(args.pre_inventory)
    if pre_err is not None or not isinstance(pre, dict):
        return 'unestablished pre-inventory-unreadable', _detail(
            'review-evidence-gate: the pre-engine inventory at ',
            args.pre_inventory, ' is ', pre_err or 'not an object', '.')
    pre_run_roots = set(pre.get('run_roots') or [])
    pre_review_ids = set(pre.get('review_ids') or [])

    reviews, rev_err = _read_json(args.reviews_payload)
    if rev_err is not None:
        return f'unestablished reviews-payload-{rev_err}', _detail(
            'review-evidence-gate: the reviews payload at ',
            args.reviews_payload, ' is ', rev_err, '.')
    if not isinstance(reviews, list):
        return 'unestablished reviews-payload-not-an-array', _detail(
            'review-evidence-gate: the reviews payload is not a JSON array.')
    if not args.reviewer_login:
        return 'unestablished reviewer-login-absent', _detail(
            'review-evidence-gate: no reviewer login was supplied, so this ',
            "run's own reviews could not be told from a human's.")

    placed = _classify_own_reviews(reviews, args.reviewer_login)
    # This run's verdict: a marker-bearing review whose id is NOT in the pre-engine
    # inventory (a verdict already present before the engine step is a prior run's, not
    # this run's — so it is never dismissed).
    fresh_marked = [(rid, state, mhead) for (rid, state, mhead) in placed['marked']
                    if rid not in pre_review_ids]
    fresh_unmarked = [rid for rid in placed['unmarked'] if rid not in pre_review_ids]

    if not fresh_marked:
        detail = _detail(
            'review-evidence-gate: this run posted no marker-bearing verdict.')
        if fresh_unmarked:
            detail.extend(_detail(
                'review-evidence-gate: unmarked own-identity review(s) present ',
                'and reported as unmarked (not counted as a posted verdict): ',
                ', '.join(str(r) for r in sorted(
                    i for i in fresh_unmarked if isinstance(i, int)))))
        return 'no-verdict', detail

    # The ID-set delta is only trustworthy when the pre-engine review-ID baseline was
    # actually established. When the pre-inventory step could not fetch the head's
    # reviews (recorded `review_ids_established: false`), every id is "fresh" by default,
    # so a PRIOR run's legitimate verdict would be mis-attributed to this run and could be
    # dismissed — so a verdict under an unestablished baseline is unestablished, never a
    # fail or a dismissal. A missing key is the pre-#2075 inventory shape and reads as
    # established (the common success case).
    if not pre.get('review_ids_established', True):
        return 'unestablished pre-inventory-review-ids-unestablished', _detail(
            'review-evidence-gate: the pre-engine review-ID baseline was not ',
            'established (the pre-inventory step could not fetch the reviews), so ',
            'this run cannot be told from a prior run and no verdict is dismissed.')

    # The newest marker-bearing verdict review (largest id) is the run's verdict; the
    # reviewed head is that verdict marker's OWN head, so a /prflow:review-and-fix verdict
    # is graded against the head it recorded rather than the PR's current head.
    verdict_id, verdict_state, reviewed_head = max(
        fresh_marked,
        key=lambda t: t[0] if isinstance(t[0], int) else -1)

    # Does the diff owe the checklist phases? Reuse workpad.py's own classification.
    if not _engine_root_has_instruction(args.vendored_engine_root):
        return 'unestablished engine-root-lacks-phase-log-instruction', _detail(
            'review-evidence-gate: the vendored engine root at ',
            args.vendored_engine_root, ' does not carry the phase-log ',
            'instruction (an older vendored engine); no phase log can be ',
            'required of it.')

    facts = workpad._recompute_diff_facts(
        reviewed_head, args.base_ref or None, args.repo_root)
    if not facts['resolved']:
        return 'unestablished diff-classification-unresolved', _detail(
            'review-evidence-gate: the reviewed diff could not be recomputed: ',
            facts['reason'], '.')
    disproof = workpad._review_coverage_profile_disproof(facts, args.repo_root)
    if disproof is None:
        # The diff authorizes the intentional checklist skip — no checklist owed.
        return 'pass legitimate-skip', _detail(
            'review-evidence-gate: the recomputed diff authorizes the ',
            'intentional checklist skip (small config-only diff); no checklist ',
            'evidence owed.')

    # The checklist IS owed. Attribute this run's run root by the inventory delta.
    post_run_roots, roots_err = _list_run_roots(args.post_tree_root)
    if roots_err is not None:
        return f'unestablished {roots_err}', _detail(
            'review-evidence-gate: the .prflow/tmp/review tree could not be read.')
    fresh_roots = sorted(post_run_roots - pre_run_roots)
    if len(fresh_roots) > 1:
        return 'unestablished run-root-delta-unattributable', _detail(
            'review-evidence-gate: more than one run root appeared during the ',
            'engine step (', ', '.join(fresh_roots), '); this run cannot be ',
            'attributed.')

    fail_detail_head = (
        f'review-evidence-gate: this run posted a merge-gating verdict (review '
        f'{verdict_id}, state {verdict_state}) for head {reviewed_head}, its diff requires '
        f'the checklist phases ({disproof}), but ')

    if not fresh_roots:
        # No run root appeared during the engine step — the same missing-record state as a
        # run root that holds no phase log (AC1).
        return (f'fail missing=run-root,phase-log review_id={verdict_id} '
                f'review_state={verdict_state}'), _detail(
            fail_detail_head, 'the engine step created NO run-scoped ',
            'directory at all, so no phase log records that the ',
            'checklist phases ran.')

    run_root_dir = os.path.join(args.post_tree_root, _REVIEW_SUBDIR, fresh_roots[0])
    kind, text = _read_phase_log(run_root_dir)
    if kind == 'unreadable':
        return 'unestablished run-root-unreadable', _detail(
            'review-evidence-gate: the attributed run root ', fresh_roots[0],
            ' exists but its phase log could not be read (an I/O or permission ',
            'failure).')
    if kind == 'missing':
        return (f'fail missing=phase-log review_id={verdict_id} '
                f'review_state={verdict_state}'), _detail(
            fail_detail_head, 'the attributed run root ', fresh_roots[0],
            ' holds no phase log, so no record shows the checklist phases ran.')

    grade, payload = _grade_phase_log(text)
    if grade == 'malformed':
        return 'unestablished phase-log-malformed', _detail(
            'review-evidence-gate: the phase log in run root ', fresh_roots[0],
            ' carries a line outside the closed record grammar; its contents ',
            'cannot be trusted as evidence.')
    if grade == 'record' and payload == 'blocker-recheck-hit':
        return 'pass blocker-recheck-hit', _detail(
            'review-evidence-gate: the run root carries the Phase 0.3.6 ',
            'blocker-recheck hit record, the sole evidence its fast-path ',
            're-verdict owes.')
    if grade == 'record' and payload == 'generator-failure':
        return 'pass generator-failure-skip', _detail(
            'review-evidence-gate: the phase log carries the checklist ',
            'generator double-failure record, a legitimate no-checklist arm.')
    # grade == 'checklist'
    missing = payload
    if not missing:
        return 'pass checklist-phases-ran', _detail(
            'review-evidence-gate: the phase log records that the checklist ',
            'phases (Phase 1 and Phase 2) ran.')
    return (f'fail missing={",".join(missing)} review_id={verdict_id} '
            f'review_state={verdict_state}'), _detail(
        fail_detail_head, 'the phase log does not record these ',
        'checklist phase entries: ', ', '.join(missing), '.')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Fail a cloud review run whose posted verdict lacks phase-execution '
                    'evidence (issue #2075). Always exits 0; the caller reads stdout '
                    'line 1 for the verdict token.')
    parser.add_argument('--pre-inventory', required=True,
                        help='JSON {"run_roots":[...],"review_ids":[...]} snapshotted '
                             'before the engine step.')
    parser.add_argument('--post-tree-root', required=True,
                        help='repo root whose .prflow/tmp/review/ tree is re-listed now.')
    parser.add_argument('--reviews-payload', required=True,
                        help='reviews-API JSON array path, or - for stdin.')
    parser.add_argument('--base-ref', default='',
                        help='the PR base ref for the diff recompute (may be empty).')
    parser.add_argument('--repo-root', default='.',
                        help='repo root for the classification recompute.')
    parser.add_argument('--reviewer-login', default='',
                        help='the run\'s own reviewer identity (.user.login).')
    parser.add_argument('--vendored-engine-root', default='',
                        help='the checked-out review engine root (holds SKILL.md).')
    args = parser.parse_args(argv)

    token, detail = _decide(args)
    print(token)
    for line in detail:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())

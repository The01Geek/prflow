#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Unit + end-to-end tests for scripts/review-evidence-gate.py (issue #2075).

Driven as one focused module assertion by lib/test/modules/review-evidence-gate.sh via
devflow_run_focused_python_test. The pure-function tests import the gate module; the arm
tests drive the CLI as a subprocess over throwaway git sandboxes, so the classification
reuse (AC4), the malformed-log matrix, and the fail/pass/unestablished arms are all
exercised at the executable boundary. No network, no gh — git only."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_GATE = os.path.join(_REPO, 'scripts', 'review-evidence-gate.py')
_HEAD = 'a' * 40


def _load_gate():
    spec = importlib.util.spec_from_file_location('review_evidence_gate', _GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


class GradePhaseLog(unittest.TestCase):
    def test_both_checklist_phases_present(self):
        grade, missing = gate._grade_phase_log(
            'phase-entry phase=0\nphase-entry phase=1\nphase-entry phase=2\n')
        self.assertEqual(grade, 'checklist')
        self.assertEqual(missing, [])

    def test_missing_phase_two(self):
        grade, missing = gate._grade_phase_log('phase-entry phase=1\n')
        self.assertEqual(grade, 'checklist')
        self.assertEqual(missing, ['phase-entry-2'])

    def test_generator_failure_record(self):
        grade, payload = gate._grade_phase_log('checklist-skip reason=failure\n')
        self.assertEqual((grade, payload), ('record', 'generator-failure'))

    def test_blocker_recheck_hit(self):
        grade, payload = gate._grade_phase_log(
            'phase-entry phase=0.3.6\nblocker-recheck-hit re-verdict=posted\n')
        self.assertEqual((grade, payload), ('record', 'blocker-recheck-hit'))

    def test_empty_log_is_missing_both(self):
        grade, missing = gate._grade_phase_log('')
        self.assertEqual(grade, 'checklist')
        self.assertEqual(missing, ['phase-entry-1', 'phase-entry-2'])

    def test_malformed_matrix(self):
        # wrong-typed / unknown extra content, a truncated line, and a valid-falsy phase
        # value each make the whole log malformed → unestablished, never a pass.
        for text in ('phase-entry phase=1\ngarbage line\nphase-entry phase=2\n',
                     'phase-entry phase=1\nphase-entry ph',        # truncated
                     'phase-entry phase=\n',                       # valid-falsy empty
                     'phase-entry phase=0\nphase-entry phase=99\n',  # unknown id
                     'phase-entry phase=1 extra=1\n'):             # unknown extra field
            grade, _ = gate._grade_phase_log(text)
            self.assertEqual(grade, 'malformed', text)

    def test_blank_lines_tolerated(self):
        grade, missing = gate._grade_phase_log(
            '\nphase-entry phase=1\n\nphase-entry phase=2\n\n')
        self.assertEqual((grade, missing), ('checklist', []))


class ClassifyOwnReviews(unittest.TestCase):
    def _review(self, rid, login, verdict_head, state='APPROVED'):
        body = (f'<!-- prflow:review-verdict head={verdict_head} verdict=APPROVE -->\nok'
                if verdict_head else 'no marker')
        return {'id': rid, 'state': state, 'user': {'login': login}, 'body': body}

    def test_marked_scoped_to_login_carries_marker_head(self):
        reviews = [self._review(1, 'bot[bot]', _HEAD),
                   self._review(2, 'human', _HEAD),          # a human review is excluded
                   self._review(3, 'bot[bot]', 'b' * 40)]    # a different reviewed head
        placed = gate._classify_own_reviews(reviews, 'bot[bot]')
        # Both own-login marker-bearing reviews are marked, each carrying its own head.
        self.assertEqual([(r, h) for (r, _s, h) in placed['marked']],
                         [(1, _HEAD), (3, 'b' * 40)])
        self.assertEqual(placed['unmarked'], [])

    def test_unmarked_own_review(self):
        placed = gate._classify_own_reviews(
            [self._review(5, 'bot[bot]', None)], 'bot[bot]')
        self.assertEqual(placed['marked'], [])
        self.assertEqual(placed['unmarked'], [5])

    def test_non_string_body_is_unmarked(self):
        placed = gate._classify_own_reviews(
            [{'id': 9, 'state': 'APPROVED', 'user': {'login': 'bot[bot]'}, 'body': None}],
            'bot[bot]')
        self.assertEqual(placed['unmarked'], [9])


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class GateEndToEnd(unittest.TestCase):
    def setUp(self):
        self._dirs = []

    def tearDown(self):
        for d in self._dirs:
            subprocess.run(['rm', '-rf', d], check=False)

    def _sandbox(self, kind):
        d = tempfile.mkdtemp(prefix='regt-')
        self._dirs.append(d)
        _git(d, 'init', '-q')
        _git(d, 'config', 'user.email', 't@t')
        _git(d, 'config', 'user.name', 't')
        with open(os.path.join(d, 'base.txt'), 'w') as f:
            f.write('base\n')
        _git(d, 'add', '-A')
        _git(d, 'commit', '-qm', 'base')
        _git(d, 'branch', '-q', 'basebr')
        name = 'config.json' if kind == 'config' else 'mod.py'
        body = '{"a":1}\n' if kind == 'config' else 'def f():\n    return 1\n'
        with open(os.path.join(d, name), 'w') as f:
            f.write(body)
        _git(d, 'add', '-A')
        _git(d, 'commit', '-qm', 'change')
        head = _git(d, 'rev-parse', 'HEAD')
        eng = os.path.join(d, 'engine')
        os.makedirs(eng)
        with open(os.path.join(eng, 'SKILL.md'), 'w') as f:
            f.write('phase-entry phase=<N>\n')
        return d, head, 'basebr', eng

    def _runroot(self, d, subpath, phaselog):
        rr = os.path.join(d, '.prflow', 'tmp', 'review', subpath)
        os.makedirs(rr, exist_ok=True)
        if phaselog is not None:
            with open(os.path.join(rr, 'phase-log'), 'w') as f:
                f.write(phaselog)

    def _run(self, d, _head, base, eng, pre, reviews):
        pre_p = os.path.join(d, 'pre.json')
        rev_p = os.path.join(d, 'rev.json')
        with open(pre_p, 'w') as f:
            json.dump(pre, f)
        with open(rev_p, 'w') as f:
            json.dump(reviews, f)
        out = subprocess.run(
            [sys.executable, _GATE, '--pre-inventory', pre_p, '--post-tree-root', d,
             '--reviews-payload', rev_p, '--base-ref', base,
             '--repo-root', d, '--reviewer-login', 'bot[bot]',
             '--vendored-engine-root', eng],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)  # always exit 0
        return out.stdout

    def _marked(self, head, state='APPROVED', rid=222):
        return [{'id': rid, 'state': state, 'user': {'login': 'bot[bot]'},
                 'body': (f'<!-- prflow:review-verdict head={head} '
                          f'verdict=APPROVE -->\nok')}]

    def _token(self, stdout):
        return stdout.splitlines()[0]

    def test_planted_bypass_no_runroot_fails(self):
        d, head, base, eng = self._sandbox('code')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertTrue(self._token(out).startswith('fail missing=run-root,phase-log'))
        # AC1/AC3: the fail line names the verdict review to dismiss and its state.
        self.assertIn('review_id=222', self._token(out))
        self.assertIn('review_state=APPROVED', self._token(out))

    def test_checklist_phases_ran_passes(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1',
                      'phase-entry phase=1\nphase-entry phase=2\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'pass checklist-phases-ran')

    def test_missing_phase_two_fails(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1', 'phase-entry phase=1\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertTrue(self._token(out).startswith('fail missing=phase-entry-2'))

    def test_generator_failure_passes(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1', 'checklist-skip reason=failure\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'pass generator-failure-skip')

    def test_blocker_recheck_hit_passes(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1', 'blocker-recheck-hit re-verdict=posted\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'pass blocker-recheck-hit')

    def test_legitimate_skip_passes(self):
        d, head, base, eng = self._sandbox('config')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'pass legitimate-skip')

    def test_malformed_log_unestablished(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1',
                      'phase-entry phase=1\nGARBAGE\nphase-entry phase=2\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'unestablished phase-log-malformed')

    def test_empty_and_missing_log_fail(self):
        for phaselog in ('', None):
            d, head, base, eng = self._sandbox('code')
            self._runroot(d, 'slug/r1', phaselog)
            out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                            self._marked(head))
            self.assertTrue(self._token(out).startswith('fail'), phaselog)

    def test_stale_root_excluded_by_attribution(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/old', 'phase-entry phase=1\nphase-entry phase=2\n')
        out = self._run(d, head, base, eng,
                        {'run_roots': ['slug/old'], 'review_ids': []},
                        self._marked(head))
        # The stale run root is in the pre-inventory, so it is not attributed to this run;
        # with no fresh root the missing-record fail arm fires.
        self.assertTrue(self._token(out).startswith('fail missing=run-root,phase-log'))

    def test_two_fresh_roots_unattributable(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1', 'phase-entry phase=1\n')
        self._runroot(d, 'slug/r2', 'phase-entry phase=2\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(self._token(out), 'unestablished run-root-delta-unattributable')

    def test_prior_verdict_not_this_run(self):
        d, head, base, eng = self._sandbox('code')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': [222]},
                        self._marked(head))
        self.assertEqual(self._token(out), 'no-verdict')

    def test_unestablished_review_id_baseline(self):
        # When the pre-inventory could not establish its review-ID baseline, a marked
        # verdict cannot be told from a prior run's — so it is unestablished, never
        # dismissed (guards against a false dismissal of a legitimate prior verdict).
        d, head, base, eng = self._sandbox('code')
        out = self._run(d, head, base, eng,
                        {'run_roots': [], 'review_ids': [], 'review_ids_established': False},
                        self._marked(head))
        self.assertEqual(
            self._token(out), 'unestablished pre-inventory-review-ids-unestablished')

    def test_no_verdict_when_unmarked_only(self):
        d, head, base, eng = self._sandbox('code')
        reviews = [{'id': 5, 'state': 'COMMENTED', 'user': {'login': 'bot[bot]'},
                    'body': 'just a comment'}]
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []}, reviews)
        self.assertEqual(self._token(out), 'no-verdict')
        self.assertIn('unmarked', out)

    def test_human_review_ignored(self):
        d, head, base, eng = self._sandbox('code')
        reviews = [{'id': 5, 'state': 'APPROVED', 'user': {'login': 'human'},
                    'body': (f'<!-- prflow:review-verdict head={head} '
                             f'verdict=APPROVE -->\n')}]
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []}, reviews)
        self.assertEqual(self._token(out), 'no-verdict')

    def test_changes_requested_state_reported(self):
        d, head, base, eng = self._sandbox('code')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head, state='CHANGES_REQUESTED'))
        self.assertIn('review_state=CHANGES_REQUESTED', self._token(out))

    def test_unresolvable_diff_unestablished(self):
        d, _head, base, eng = self._sandbox('code')
        out = self._run(d, 'b' * 40, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked('b' * 40))
        self.assertEqual(self._token(out), 'unestablished diff-classification-unresolved')

    def test_engine_root_without_instruction_unestablished(self):
        d, head, base, eng = self._sandbox('code')
        with open(os.path.join(eng, 'SKILL.md'), 'w') as f:
            f.write('an older engine that never wrote a phase log\n')
        out = self._run(d, head, base, eng, {'run_roots': [], 'review_ids': []},
                        self._marked(head))
        self.assertEqual(
            self._token(out), 'unestablished engine-root-lacks-phase-log-instruction')

    def test_idempotent_same_verdict_twice(self):
        d, head, base, eng = self._sandbox('code')
        self._runroot(d, 'slug/r1', 'phase-entry phase=1\n')
        pre = {'run_roots': [], 'review_ids': []}
        first = self._token(self._run(d, head, base, eng, pre, self._marked(head)))
        second = self._token(self._run(d, head, base, eng, pre, self._marked(head)))
        self.assertEqual(first, second)

    def test_reviews_payload_unreadable_unestablished(self):
        d, _head, base, eng = self._sandbox('code')
        pre_p = os.path.join(d, 'pre.json')
        with open(pre_p, 'w') as f:
            json.dump({'run_roots': [], 'review_ids': []}, f)
        out = subprocess.run(
            [sys.executable, _GATE, '--pre-inventory', pre_p, '--post-tree-root', d,
             '--reviews-payload', os.path.join(d, 'nope.json'),
             '--base-ref', base, '--repo-root', d, '--reviewer-login', 'bot[bot]',
             '--vendored-engine-root', eng],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.splitlines()[0].startswith(
            'unestablished reviews-payload-'))


class ClassificationReuse(unittest.TestCase):
    """AC4: the checklist-requirement decision is workpad.py's own implementation, not a
    re-copy. Prove the gate imports workpad's functions and does not redeclare its
    classification constants."""
    def test_gate_imports_workpad_classification(self):
        wp = gate._load_workpad()
        self.assertIsNotNone(wp)
        for name in ('_recompute_diff_facts', '_review_coverage_profile_disproof',
                     '_REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING'):
            self.assertTrue(hasattr(wp, name), name)

    def test_gate_does_not_recopy_the_ceilings(self):
        with open(_GATE, encoding='utf-8') as f:
            src = f.read()
        # The gate must reference workpad's classification via the imported module, never
        # redeclare the ceiling constants (which would be a second copy — AC4 forbids it).
        self.assertNotIn('_REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING =', src)
        self.assertNotIn('_REVIEW_COVERAGE_SMALL_DIFF_FILE_CEILING =', src)


if __name__ == '__main__':
    unittest.main()

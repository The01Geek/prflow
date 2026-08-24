#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused unit + reduction-detection tests for scripts/create-issue-context-eval.py.

Every acceptance criterion of issue #767 that the eval or its committed fixtures can
witness maps to at least one assertion here (the orchestrator-instruction reduction's
preservation is discharged separately by a code-reading obligation + reproducible
check recorded in docs/internal/create-issue-context.md — no issue-audit-state.py-driven suite
test can witness it). Driven serially from lib/test/run.sh.
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import unittest.mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_EVAL_PATH = os.path.join(_REPO, "scripts", "create-issue-context-eval.py")
_MODULAR_EVAL_PATH = os.path.join(_REPO, "scripts", "create_issue_eval.py")
_FIX = os.path.join(_HERE, "fixtures", "create-issue-eval")
_MANIFEST_FIX = os.path.join(_FIX, "manifests")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_eval():
    return _load_module("cice", _EVAL_PATH)


CICE = _load_eval()


# A deeply-nested JSON document: the shape that makes CPython's recursive scanner raise
# `RecursionError` (a `RuntimeError`, not a `ValueError`) out of `json.loads`.
_DEEP_JSON = "[" * 40000 + "]" * 40000


@contextlib.contextmanager
def _recursion_error_on(text):
    """Force `json.loads(text)` to raise `RecursionError` for the duration.

    Do not replace this with a bare deeply-nested literal: 3.14's iterative decoder
    parses `_DEEP_JSON` without overflowing, so a literal-only test would stop
    discriminating a narrow `(ValueError, TypeError)` clause from a broad one there.
    """
    real_loads = json.loads

    def _loads(value, *args, **kwargs):
        if isinstance(value, str) and value.strip() == text:
            raise RecursionError("maximum recursion depth exceeded while decoding")
        return real_loads(value, *args, **kwargs)

    with unittest.mock.patch.object(json, "loads", _loads):
        yield


def _write(dirpath, name, lines):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# Owner-specific / transcript-content shapes that must never appear in a committed
# file this change adds (the eval, the determination doc, the synthetic fixtures).
_SECRET_PATTERNS = [
    re.compile(r"the01geek"),
    re.compile(r"/Users/"),
    re.compile(r"\.claude-3/jobs"),
    re.compile(r"-Users-[a-z0-9]+-repos"),
]


def _scan_for_secrets(text):
    return [p.pattern for p in _SECRET_PATTERNS if p.search(text)]


class SecretDetectorTest(unittest.TestCase):
    def test_detector_fires_on_planted_control(self):
        # Positive control: the planted fixture MUST trip the detector, proving it
        # catches the shape it guards rather than merely passing on a clean tree.
        planted = os.path.join(_FIX, "planted-owner-id.txt")
        with open(planted, encoding="utf-8") as fh:
            hits = _scan_for_secrets(fh.read())
        self.assertTrue(hits, "planted positive control did not trip the secret detector")

    def test_added_files_are_clean(self):
        # The clean scan covers the eval, the determination doc, and every fixture,
        # excluding the positive-control file by name.
        # Name every module that carries eval/benchmark source: scanning only the
        # hyphenated shim would leave the relocated implementation unscanned.
        targets = [
            _EVAL_PATH,
            _MODULAR_EVAL_PATH,
            os.path.join(_REPO, "scripts", "create_issue_benchmark.py"),
            os.path.join(_REPO, "scripts", "create-issue-benchmark.py"),
            os.path.join(_REPO, "docs", "internal", "create-issue-context.md"),
        ]
        for required in targets:
            # A silently-skipped absent target is how this scan shrank to a shim.
            self.assertTrue(
                os.path.exists(required),
                "secret-scan target does not exist: {}".format(required),
            )
        for dirpath, _dirs, files in os.walk(_FIX):  # tree-walk-ok: rooted at the fixed committed create-issue-eval fixtures subdir, not the repo root — never descends into sibling worktrees
            for f in sorted(files):
                if f == "planted-owner-id.txt":
                    continue
                targets.append(os.path.join(dirpath, f))
        for path in targets:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                hits = _scan_for_secrets(fh.read())
            self.assertFalse(hits, "owner-id/transcript shape {} found in {}".format(hits, path))


class MissingCorpusTest(unittest.TestCase):
    def test_missing_corpus_exits_nonzero_naming_path(self):
        err = io.StringIO()
        import sys
        saved = sys.stderr
        sys.stderr = err
        try:
            rc = CICE.main(["/no/such/corpus/here"])
        finally:
            sys.stderr = saved
        self.assertEqual(rc, 2)
        self.assertIn("/no/such/corpus/here", err.getvalue())


class HappyPathTest(unittest.TestCase):
    def test_per_run_fields(self):
        runs, skipped = CICE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertEqual(len(runs), 3)
        by = {r["source"]: r for r in runs}
        self.assertEqual(by["run-c.jsonl"]["turn_count"], 4)
        self.assertEqual(by["run-c.jsonl"]["peak_context"], 250000)
        self.assertEqual(by["run-c.jsonl"]["repeated_read_count"], 3)
        self.assertEqual(by["run-b.jsonl"]["reemission_count"], 1)
        self.assertEqual(sum(skipped.values()), 0)

    def test_fixture_derived_aggregate_is_ci_reconcilable(self):
        # The CI-reconcilable companion figure: re-derived live from committed
        # synthetic transcripts (distinct from the corpus-derived snapshot in the doc).
        runs, _ = CICE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = CICE.aggregate(runs)
        self.assertEqual(summary, {
            "run_count": 3,
            # Every fixture turn carries well-formed usage, so no turn is unmeasured.
            "total_usage_missing_turns": 0,
            "median_peak_context": 64000,
            "max_peak_context": 250000,
            "runs_over_200k": 1,
            "runs_over_400k": 0,
            "median_repeated_read_count": 0,
            "median_reemission_count": 0,
            # Issue #889 axes. The corpus carries no state file, so every per-kind /
            # scope-escape / post-filing / wall-clock figure reads `unestablished`
            # (never a number). The run population is non-empty and each run's
            # sidechain cost is a measured 0, so the auditor-cost median IS 0 here —
            # the empty-population case is asserted separately as `unestablished`.
            "state_established": False,
            "finding_count": "unestablished",
            "median_attributed_auditor_cost": 0,
            "median_unrounded_auditor_cost": 0,
            "total_unrounded_auditor_cost": 0,
            "median_auditor_cost_discovery": "unestablished",
            "median_auditor_cost_targeted": "unestablished",
            "total_sidechain_records_seen": 0,
            "total_sidechain_records_attributed": 0,
            "total_record_reopen": 0,
            "scope_escape_count": "unestablished",
            "scope_escape_unattributable": "unestablished",
            "post_filing_escapes": "unestablished",
            "wall_clock": "unestablished",
        })


class RealisticFixtureTest(unittest.TestCase):
    def test_realistic_transcript_excerpt_is_processed(self):
        # Issue #767 AC: the parser processes a real transcript excerpt. These values
        # are the parser's actual output over the committed fixture (verified live), not
        # hand-picked numbers.
        runs, skipped = CICE.eval_corpus(os.path.join(_FIX, "realistic"))
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual(r["peak_context"], 125500)
        self.assertEqual(r["compact_boundary_count"], 1)
        self.assertEqual(r["repeated_read_count"], 0)
        # The isSidechain assistant record is excluded from the attributed turn count.
        self.assertEqual(r["turn_count"], 2)
        self.assertEqual(sum(skipped.values()), 0)


class ReductionDetectionTest(unittest.TestCase):
    def test_after_fixture_has_strictly_lower_peak_and_reemission(self):
        # Proves the eval DETECTS a modeled reduction (passes by construction; NOT a
        # claim that the shipped skill edit reduces real runs). The reemission_count
        # drop carries the real reduction signal; peak_context is the residency proxy.
        before, _ = CICE.eval_corpus(os.path.join(_FIX, "before"))
        after, _ = CICE.eval_corpus(os.path.join(_FIX, "after"))
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertLess(after[0]["peak_context"], before[0]["peak_context"])
        self.assertLess(after[0]["reemission_count"], before[0]["reemission_count"])


class _SingleSessionMixin:
    """Shared helper: run the eval over a one-session temp corpus built from `lines`."""

    def _run_one(self, lines):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", lines)
            return CICE.eval_corpus(d)


class BoundaryTest(_SingleSessionMixin, unittest.TestCase):
    def test_zero_attributed_turns_emits_no_run(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"other","message":{"usage":{"input_tokens":5}}}',
        ])
        self.assertEqual(runs, [])

    def test_one_turn_run(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":10,"cache_read_input_tokens":20,'
            '"cache_creation_input_tokens":0,"output_tokens":3}}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 1)
        self.assertEqual(runs[0]["peak_context"], 30)

    def test_null_usage_subfield_treated_as_zero(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":null,"cache_read_input_tokens":7}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 7)

    def test_sidechain_excluded(self):
        runs, _ = self._run_one([
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":999}}}',
        ])
        self.assertEqual(runs, [])

    def test_compaction_counted(self):
        runs, _ = self._run_one([
            '{"type":"system","subtype":"compact_boundary"}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1}}}',
        ])
        self.assertEqual(runs[0]["compact_boundary_count"], 1)

    def test_changed_content_reread_not_counted(self):
        # Two Reads of the same path whose content CHANGED between reads: authoritative.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u1","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","tool_use_id":"u1","content":"AAAA"}]}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u2","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","tool_use_id":"u2","content":"BBBB-changed"}]}}',
        ])
        self.assertEqual(runs[0]["repeated_read_count"], 0)

    def test_identical_content_reread_counted(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u1","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","tool_use_id":"u1","content":"SAME"}]}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u2","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","tool_use_id":"u2","content":"SAME"}]}}',
        ])
        self.assertEqual(runs[0]["repeated_read_count"], 1)

    def _reread_second_result_block(self, second_result_block):
        # Two Reads of the same path; the SECOND result carries `second_result_block`
        # verbatim. Returns the run so a caller can assert repeated_read_count.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u1","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","tool_use_id":"u1","content":"SAME"}]}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"u2","name":"Read","input":{"file_path":"/x"}}]}}',
            '{"type":"user","message":{"content":[' + second_result_block + ']}}',
        ])
        return runs

    def test_truncated_toolresult_fails_closed(self):
        # A repeated Read whose tool_result content is truncated is NOT folded into the
        # redundant count (fail closed -> authoritative).
        runs = self._reread_second_result_block(
            '{"type":"tool_result","tool_use_id":"u2","content":"SAME","truncated":true}'
        )
        self.assertEqual(runs[0]["repeated_read_count"], 0)

    def test_errored_toolresult_fails_closed(self):
        # An errored tool_result (`is_error: true`) is non-authoritative: a repeat of
        # its bytes must NOT be counted as a redundant repeated-Read.
        runs = self._reread_second_result_block(
            '{"type":"tool_result","tool_use_id":"u2","content":"SAME","is_error":true}'
        )
        self.assertEqual(runs[0]["repeated_read_count"], 0)

    def test_absent_content_toolresult_fails_closed(self):
        # A tool_result with no `content` key (missing/absent) yields None from the
        # comparand extractor -> authoritative, never redundant.
        runs = self._reread_second_result_block(
            '{"type":"tool_result","tool_use_id":"u2"}'
        )
        self.assertEqual(runs[0]["repeated_read_count"], 0)

    def test_nontext_content_toolresult_fails_closed(self):
        # A tool_result whose content is a list containing a non-text (image) block
        # cannot be asserted byte-identical -> fail closed (authoritative).
        runs = self._reread_second_result_block(
            '{"type":"tool_result","tool_use_id":"u2","content":['
            '{"type":"image","source":{}}]}'
        )
        self.assertEqual(runs[0]["repeated_read_count"], 0)


class AdversarialTest(_SingleSessionMixin, unittest.TestCase):
    def test_malformed_records_degrade_and_are_reported(self):
        runs, skipped = self._run_one([
            'not json at all',
            '["a","list","not","an","object"]',
            '{"no":"type field"}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":4}}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue"',  # truncated line
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 1)
        self.assertEqual(skipped["non_json_line"], 2)  # 'not json' + truncated
        self.assertEqual(skipped["not_object"], 1)
        self.assertEqual(skipped["no_type"], 1)

    def test_a_deeply_nested_line_is_skipped_rather_than_raised(self):
        attributed = (
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":4}}}'
        )
        control_runs, control_skipped = self._run_one([attributed])
        self.assertEqual(len(control_runs), 1)
        self.assertEqual(control_skipped["non_json_line"], 0)
        with _recursion_error_on(_DEEP_JSON):
            runs, skipped = self._run_one([_DEEP_JSON, attributed])
        self.assertEqual(skipped["non_json_line"], 1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 1)

    def test_message_wrong_shape_does_not_detonate(self):
        # `message` as a truthy non-dict (a list here) must NOT raise AttributeError and
        # abort the corpus walk: the isinstance guard degrades it cleanly and the
        # following well-formed attributed record still processes.
        import sys
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":["not","a","dict"]}',
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":9}}}',
            ])
        finally:
            sys.stderr = saved
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        self.assertEqual(runs[0]["peak_context"], 9)
        # No detonation: the isinstance guard handled the bad shape without a skip.
        self.assertEqual(sum(skipped.values()), 0)

    def test_read_block_input_wrong_shape_does_not_detonate(self):
        # A Read tool_use whose `input` is a list (not a dict) must not raise; the block
        # is skipped for path tracking and the walk completes with the record counted.
        import sys
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":3},"content":['
                '{"type":"tool_use","id":"u1","name":"Read","input":["not","a","dict"]}]}}',
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":5}}}',
            ])
        finally:
            sys.stderr = saved
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        self.assertEqual(sum(skipped.values()), 0)

    def test_defensive_dispatch_tallies_malformed_record(self):
        # Backstop for any record shape the isinstance guards do not anticipate: the
        # per-record try/except in eval_corpus tallies `malformed_record` and the walk
        # completes rather than aborting. We force the guarded path by monkeypatching an
        # observer to raise on a specific record, proving the dispatch-level guard tallies
        # and the following good record still processes.
        import sys
        original = CICE.RunAccumulator.observe_user

        def _boom(self, record):
            if record.get("boom"):
                raise TypeError("synthetic malformed record")
            return original(self, record)

        saved_stderr = sys.stderr
        sys.stderr = io.StringIO()
        CICE.RunAccumulator.observe_user = _boom
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":4}}}',
                '{"type":"user","boom":true,"message":{"content":[]}}',
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":6}}}',
            ])
        finally:
            CICE.RunAccumulator.observe_user = original
            sys.stderr = saved_stderr
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        self.assertEqual(skipped["malformed_record"], 1)

    def test_unreadable_session_file_is_tallied(self):
        # A file the walker enumerates but cannot open (here a broken symlink whose
        # target is inside the corpus root so it passes the escape guard, then fails
        # to open) is tallied under `unreadable_file`, never silently dropped.
        with tempfile.TemporaryDirectory() as corpus:
            link = os.path.join(corpus, "broken.jsonl")
            try:
                os.symlink(os.path.join(corpus, "missing-target.jsonl"), link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this host")
            err = io.StringIO()
            import sys
            saved = sys.stderr
            sys.stderr = err
            try:
                runs, skipped = CICE.eval_corpus(corpus)
            finally:
                sys.stderr = saved
            self.assertEqual(runs, [])
            self.assertEqual(skipped["unreadable_file"], 1)
            self.assertIn("broken.jsonl", err.getvalue())

    def test_determinism(self):
        # Re-running over the same corpus yields byte-identical output.
        a, sa = CICE.eval_corpus(os.path.join(_FIX, "corpus"))
        b, sb = CICE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertEqual(a, b)
        self.assertEqual(sa, sb)


class SecurityTest(unittest.TestCase):
    def test_symlink_escape_is_not_read(self):
        with tempfile.TemporaryDirectory() as outside:
            with open(os.path.join(outside, "secret.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","attributionSkill":"devflow:create-issue",'
                         '"message":{"usage":{"input_tokens":7}}}\n')
            with tempfile.TemporaryDirectory() as corpus:
                link = os.path.join(corpus, "escape.jsonl")
                try:
                    os.symlink(os.path.join(outside, "secret.jsonl"), link)
                except (OSError, NotImplementedError):
                    self.skipTest("symlinks unavailable on this host")
                runs, _ = CICE.eval_corpus(corpus)
                self.assertEqual(runs, [], "eval read a file outside the corpus root")

    def test_symlink_escape_is_tallied_and_breadcrumbed(self):
        # The escape is not merely skipped from reading — it is TALLIED under
        # `escaped_path` and breadcrumbed to stderr, never silently dropped.
        with tempfile.TemporaryDirectory() as outside:
            with open(os.path.join(outside, "secret.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","attributionSkill":"devflow:create-issue",'
                         '"message":{"usage":{"input_tokens":7}}}\n')
            with tempfile.TemporaryDirectory() as corpus:
                link = os.path.join(corpus, "escape.jsonl")
                try:
                    os.symlink(os.path.join(outside, "secret.jsonl"), link)
                except (OSError, NotImplementedError):
                    self.skipTest("symlinks unavailable on this host")
                err = io.StringIO()
                import sys
                saved = sys.stderr
                sys.stderr = err
                try:
                    runs, skipped = CICE.eval_corpus(corpus)
                finally:
                    sys.stderr = saved
                self.assertEqual(runs, [])
                self.assertEqual(skipped["escaped_path"], 1)
                self.assertIn("escape.jsonl", err.getvalue())

    def test_walk_error_is_recorded(self):
        # An os.walk that cannot descend a directory (permission denied) records the
        # error via the onerror callback under `walk_error` — default onerror=None
        # would swallow it silently.
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("running as root: chmod-based permission block is ineffective")
        with tempfile.TemporaryDirectory() as corpus:
            blocked = os.path.join(corpus, "blocked")
            os.makedirs(blocked)
            with open(os.path.join(blocked, "s.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","attributionSkill":"devflow:create-issue",'
                         '"message":{"usage":{"input_tokens":1}}}\n')
            os.chmod(blocked, 0o000)
            try:
                # Verify the host actually enforces the permission block; skip if not.
                try:
                    os.listdir(blocked)
                    self.skipTest("host does not enforce dir permission block")
                except OSError:
                    pass
                err = io.StringIO()
                import sys
                saved = sys.stderr
                sys.stderr = err
                try:
                    runs, skipped = CICE.eval_corpus(corpus)
                finally:
                    sys.stderr = saved
                self.assertEqual(skipped["walk_error"], 1)
                self.assertIn("blocked", err.getvalue())
            finally:
                os.chmod(blocked, 0o700)


class RoundAttributionTest(_SingleSessionMixin, unittest.TestCase):
    """Issue #889: sidechain (auditor) cost is attributed to transcript-derived rounds."""

    def test_sidechain_cost_attributed_to_current_round(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"issue-audit-state.py record-dispatch --round 1 --kind discovery"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":100,"cache_read_input_tokens":200,'
            '"cache_creation_input_tokens":50,"output_tokens":10}}}',
        ])
        self.assertEqual(len(runs), 1)
        # The auditor cost is the full token total (context sub-fields + output).
        self.assertEqual(runs[0]["round_auditor_cost"], {1: 360})
        self.assertEqual(runs[0]["attributed_auditor_cost"], 360)
        # The sidechain record is NOT a main-thread turn.
        self.assertEqual(runs[0]["turn_count"], 1)

    def test_sidechain_before_any_dispatch_is_unrounded_not_round_one(self):
        # A sidechain turn before any record-dispatch marker cannot be keyed to a
        # round; it is held separately, never silently folded into round 1.
        runs, _ = self._run_one([
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":7}}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1}}}',
        ])
        self.assertEqual(runs[0]["round_auditor_cost"], {})
        self.assertEqual(runs[0]["unrounded_auditor_cost"], 7)
        self.assertEqual(runs[0]["attributed_auditor_cost"], 7)

    def test_round_boundary_switches_on_new_dispatch(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"issue-audit-state.py record-dispatch --round 1 --kind discovery"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":100}}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b2",'
            '"input":{"command":"issue-audit-state.py record-dispatch --round 2 --kind targeted"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":40}}}',
        ])
        self.assertEqual(runs[0]["round_auditor_cost"], {1: 100, 2: 40})
        self.assertEqual(runs[0]["dispatch_rounds"], [1, 2])

    def test_quoted_round_value_opens_a_boundary(self):
        """The skill's own rendered fence writes `--round "<round>"` (QUOTED).

        A regex requiring a bare digit derived no round boundary at all on a faithful
        real transcript, while `attributed_auditor_cost` still reported a full,
        confident number — an entirely unattributed total presented as a
        round-attributed one.
        """
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"python3 /x/scripts/issue-audit-state.py record-dispatch '
            '--arm file --kind targeted --round \\"2\\""}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":55}}}',
        ])
        self.assertEqual(runs[0]["round_auditor_cost"], {2: 55})
        self.assertEqual(runs[0]["unrounded_auditor_cost"], 0)

    def test_marker_text_without_the_state_owner_head_opens_no_boundary(self):
        """The marker is a contract, not a substring: a grep/echo must not move state."""
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"grep -n \\"record-dispatch --round 4\\" '
            'skills/create-issue/references/step-3-6-audit.md; echo record-reopen"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":9}}}',
        ])
        self.assertEqual(runs[0]["round_auditor_cost"], {})
        self.assertEqual(runs[0]["dispatch_rounds"], [])
        self.assertEqual(runs[0]["record_reopen_count"], 0)
        # Held as unrounded rather than dropped — the cost was still spent.
        self.assertEqual(runs[0]["unrounded_auditor_cost"], 9)

    def test_every_marker_occurrence_is_counted_not_just_the_first(self):
        """A compound command spending two reopens must tally two, not one.

        And the boundary a command leaves open is its LAST dispatch marker.
        """
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"scripts/issue-audit-state.py record-reopen --round 2 '
            '--finding 1.1 && scripts/issue-audit-state.py record-reopen --round 2 '
            '--finding 1.2 && scripts/issue-audit-state.py record-dispatch --round 1 '
            '--kind discovery && scripts/issue-audit-state.py record-dispatch '
            '--round 4 --kind targeted"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":11}}}',
        ])
        self.assertEqual(runs[0]["record_reopen_count"], 2)
        self.assertEqual(runs[0]["dispatch_rounds"], [1, 4])
        self.assertEqual(runs[0]["round_auditor_cost"], {4: 11})

    def test_a_round_less_dispatch_cannot_borrow_a_later_commands_round(self):
        """The intervening span may not cross a further state-owner invocation."""
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"scripts/issue-audit-state.py record-dispatch --arm file'
            ' ; scripts/issue-audit-state.py record-reopen --round 5"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":6}}}',
        ])
        self.assertEqual(runs[0]["dispatch_rounds"], [])
        self.assertEqual(runs[0]["unrounded_auditor_cost"], 6)
        self.assertEqual(runs[0]["record_reopen_count"], 1)

    def test_a_round_less_dispatch_cannot_borrow_a_non_owner_commands_round(self):
        """The intervening span may not cross a shell command separator either.

        The state-owner-only lookahead alone still admitted this: a `record-dispatch`
        with no `--round` followed by ANY later command carrying one (`; echo trailing
        --round 9`) opened a boundary that command never opened, bucketing the
        auditor's cost into a fabricated round 9.
        """
        for separator in (";", "&&", "||", "|"):
            with self.subTest(separator=separator):
                runs, _ = self._run_one([
                    '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                    '"message":{"usage":{"input_tokens":1},"content":['
                    '{"type":"tool_use","name":"Bash","id":"b1",'
                    '"input":{"command":"scripts/issue-audit-state.py record-dispatch '
                    '--kind targeted ' + separator + ' echo trailing --round 9"}}]}}',
                    '{"type":"assistant","isSidechain":true,'
                    '"attributionSkill":"devflow:create-issue",'
                    '"message":{"usage":{"input_tokens":6}}}',
                ])
                self.assertEqual(runs[0]["dispatch_rounds"], [])
                self.assertEqual(runs[0]["unrounded_auditor_cost"], 6)

    def test_the_skill_reference_rendered_form_opens_a_boundary(self):
        """The REAL command shape `step-3-6-audit.md` renders, not the fixture's head.

        The committed transcript fixtures write a bare `scripts/issue-audit-state.py`
        head; the skill renders a `python3 "${CLAUDE_SKILL_DIR:-…}"/../../scripts/…`
        head with a QUOTED round value. `_DISPATCH_ROUND_RE` anchors on the script name
        plus the subcommand, which both satisfy — but no committed fixture exercised the
        anchored real form, so a tightening that broke it would have stayed green.
        """
        command = ('python3 \\"${CLAUDE_SKILL_DIR:-/base/dir}\\"'
                   '/../../scripts/issue-audit-state.py record-dispatch '
                   '\\"my-slug\\" --nonce \\"n1\\" --round \\"3\\" --kind targeted')
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"' + command + '"}}]}}',
            '{"type":"assistant","isSidechain":true,'
            '"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":12}}}',
        ])
        self.assertEqual(runs[0]["dispatch_rounds"], [3])
        self.assertEqual(runs[0]["round_auditor_cost"], {3: 12})

    def test_record_reopen_counted(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"issue-audit-state.py record-reopen --round 2 --finding 1.1"}}]}}',
        ])
        self.assertEqual(runs[0]["record_reopen_count"], 1)

    def test_non_create_issue_sidechain_not_attributed(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","name":"Bash","id":"b1",'
            '"input":{"command":"issue-audit-state.py record-dispatch --round 1 --kind discovery"}}]}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"other-skill",'
            '"message":{"usage":{"input_tokens":9999}}}',
        ])
        self.assertEqual(runs[0]["attributed_auditor_cost"], 0)


class StateReaderBestEffortTest(unittest.TestCase):
    """Issue #889 AC8: every degraded state-file shape -> unestablished, never a crash."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._seq = 0

    def _state(self, payload, mode="w", encoding="utf-8"):
        """Write one state payload into this test's own auto-removed temp dir."""
        self._seq += 1
        path = os.path.join(self._tmp.name, "state-{}.json".format(self._seq))
        with open(path, mode, **({} if "b" in mode else {"encoding": encoding})) as fh:
            fh.write(payload)
        return path

    def test_absent_state_is_none(self):
        self.assertIsNone(CICE.read_state(None))
        self.assertIsNone(CICE.read_state("/no/such/state.json"))

    def test_degraded_shapes_read_as_none(self):
        degraded = [
            "",                                   # empty
            "   \n",                              # whitespace-only
            "{ not json",                         # malformed
            "[1,2,3]",                            # not an object
            '{"rounds": "notalist"}',             # wrong-typed rounds container
            '{"rounds": [ "notanobject" ]}',      # a round that is not an object
            '{"rounds": [ {"round": 1, "kind": "bogus"} ]}',  # unrecognized kind
            '{"rounds": [ {"round": true, "kind": "discovery"} ]}',  # bool round num
            '{"rounds": [ {"round": "x", "kind": "discovery"} ]}',  # non-int round num, valid kind
            '{"rounds": [ {"kind": "discovery"} ]}',  # missing round num, valid kind
            # A PRESENT-but-non-list `findings` container is corrupt, never empty:
            # coercing it to [] would publish a measured `finding_count: 0` and an
            # established scope-escape `0` about a ledger that was never read.
            '{"rounds": [ {"round": 1, "kind": "discovery", "findings": "nope"} ]}',
            '{"rounds": [ {"round": 1, "kind": "discovery", "findings": {"a": 1}} ]}',
            '{"rounds": [ {"round": 1, "kind": "discovery", "findings": 3} ]}',
            # A duplicated round number is last-wins otherwise, and DISCARDING a
            # targeted round makes the scope-escape proxy report an established 0.
            '{"rounds": [ {"round": 1, "kind": "targeted"},'
            '             {"round": 1, "kind": "discovery"} ]}',
        ]
        for payload in degraded:
            path = self._state(payload)
            self.assertIsNone(CICE.read_state(path),
                              "degraded payload should read as None: {!r}".format(payload))

    def test_a_non_valueerror_decoder_failure_degrades_and_never_crashes(self):
        """`json.loads` does not raise only ValueError/TypeError.

        A deeply-nested document raises `RecursionError`, which inherits from
        `RuntimeError` and escapes a `(ValueError, TypeError)` clause as an uncaught
        traceback — falsifying AC8's "never a crash" on exactly the hand-corrupted
        input this reader exists to survive. The failure is INJECTED rather than driven
        by a literal nesting depth: the depth at which CPython's decoder gives up is
        interpreter- and stack-size-dependent (it took >20k frames on the authoring
        host), so a checked-in depth pins a host property, not the contract.
        """
        path = self._state('{"rounds": []}')
        # Positive control: unpatched, this exact file establishes an empty state, so
        # the None below is attributable to the injected failure, not to the fixture.
        self.assertEqual(CICE.read_state(path), {})
        class _NovelDecoderFailure(Exception):
            """Stands for the next unanticipated exception type, which is why the
            clause under test is residual rather than an enumerated list."""

        for exc in (RecursionError("stack overflow"), MemoryError(),
                    _NovelDecoderFailure("some novel decoder failure")):
            with self.subTest(exc=type(exc).__name__):
                with unittest.mock.patch.object(
                        CICE.json, "loads", side_effect=exc):
                    self.assertIsNone(CICE.read_state(path))

    def test_real_deep_nesting_never_crashes_whatever_the_decoder_does(self):
        """The real-input companion: a deeply-nested document, however it fails.

        On an interpreter whose decoder survives the nesting this degrades on the
        top-level-shape arm instead; either way `read_state` returns None rather than
        propagating. Asserting the OUTCOME rather than which arm fired is what keeps
        this row portable across interpreters (and CI's Python is not this host's).
        """
        depth = 250_000
        self.assertIsNone(CICE.read_state(
            self._state("[" * depth + "1" + "]" * depth)))

    def test_directory_path_degrades_and_never_crashes(self):
        """A state path that is a DIRECTORY: IsADirectoryError is an OSError."""
        self.assertIsNone(CICE.read_state(self._tmp.name))

    def test_permission_denied_state_degrades_and_never_crashes(self):
        path = self._state('{"rounds": []}')
        # Positive control: readable, the same file establishes an empty state.
        self.assertEqual(CICE.read_state(path), {})
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        # Running as root, or on a filesystem that ignores the mode, the file stays
        # readable — assert what is actually true there rather than emitting a skip
        # (a skipped check is never a clean pass in this suite).
        if os.access(path, os.R_OK):
            self.assertEqual(CICE.read_state(path), {})
        else:
            self.assertIsNone(CICE.read_state(path))

    def test_non_utf8_state_degrades_and_never_crashes(self):
        """A byte-level degraded row: UnicodeDecodeError is a ValueError, not an OSError.

        The text-level matrix above cannot reach the decode path at all, so without this
        row the module docstring's "never a crash (AC8)" absolute was false against a
        binary/latin-1 state file.
        """
        path = self._state(b'{"rounds": [\xff\xfe]}', mode="wb")
        self.assertIsNone(CICE.read_state(path))
        # Positive control: the same directory and writer produce a state the reader
        # DOES accept, so the None above is attributable to the undecodable bytes and
        # not to an unrelated precondition (an unwritable dir, a bad path).
        ok = self._state('{"rounds": [{"round": 1, "kind": "discovery"}]}')
        self.assertIsNotNone(CICE.read_state(ok))

    def test_degraded_arm_emits_a_breadcrumb_naming_the_path(self):
        """A mistyped path must not be byte-identical in output to passing none."""
        path = self._state("{ not json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(CICE.read_state(path))
        self.assertIn(path, err.getvalue())
        self.assertIn("unestablished", err.getvalue())
        # Passing nothing is not a degradation and stays silent.
        quiet = io.StringIO()
        with contextlib.redirect_stderr(quiet):
            self.assertIsNone(CICE.read_state(None))
        self.assertEqual(quiet.getvalue(), "")

    def test_absent_findings_stays_legal_and_empty(self):
        """Positive control for the wrong-typed-`findings` rows above.

        Absent is legal (a round that recorded no ledger genuinely has none), so the
        degradations above are attributable to the wrong TYPE, not to the key being
        consulted at all.
        """
        state = CICE.read_state(self._state(
            '{"rounds": [{"round": 1, "kind": "discovery"}]}'))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["findings"], [])
        self.assertEqual(CICE._finding_count(state), 0)

    def test_corrupt_findings_never_publishes_a_measured_zero(self):
        """The whole point of the degradation: no confident number reaches the report."""
        path = self._state(
            '{"rounds": [{"round": 1, "kind": "targeted",'
            ' "scope": {"draft_lines": [1, 9]}, "findings": "nope"},'
            ' {"round": 2, "kind": "discovery", "findings": []}]}')
        report = CICE.build_report(os.path.join(_FIX, "after-rounds"), path)
        self.assertFalse(report["summary"]["state_established"])
        self.assertEqual(report["summary"]["finding_count"], "unestablished")
        self.assertEqual(report["summary"]["scope_escape_count"], "unestablished")

    def test_duplicate_round_never_discards_a_targeted_scope(self):
        """Last-wins would drop the targeted round and report an established 0."""
        path = self._state(
            '{"rounds": [{"round": 1, "kind": "targeted",'
            ' "scope": {"draft_lines": [1, 5]}, "findings": []},'
            ' {"round": 1, "kind": "discovery", "findings":'
            ' [{"status": "unresolved", "quoted_draft_line": 3}]}]}')
        self.assertIsNone(CICE.read_state(path))
        self.assertEqual(
            CICE.aggregate([], CICE.read_state(path))["scope_escape_count"],
            "unestablished")

    def test_absent_kind_defaults_to_discovery_not_whole_state_collapse(self):
        """A pre-#793 round carries no `kind`; the state owner's readers default it.

        Collapsing the whole labelling over one legacy round would zero out every
        per-kind median for an otherwise-valid corpus.
        """
        state = CICE.read_state(self._state(
            '{"rounds": [{"round": 1}, {"round": 2, "kind": "targeted"}]}'))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["kind"], "discovery")
        self.assertEqual(state[2]["kind"], "targeted")

    def test_degraded_state_makes_per_kind_and_scope_unestablished(self):
        runs, _ = CICE.eval_corpus(
            os.path.join(_FIX, "after-rounds"))
        summary = CICE.aggregate(runs, CICE.read_state("/no/such/state.json"))
        self.assertEqual(summary["median_auditor_cost_discovery"], "unestablished")
        self.assertEqual(summary["median_auditor_cost_targeted"], "unestablished")
        self.assertEqual(summary["scope_escape_count"], "unestablished")
        self.assertEqual(summary["scope_escape_unattributable"], "unestablished")

    def test_valid_state_reads_rounds(self):
        state = CICE.read_state(os.path.join(_FIX, "states", "after-state.json"))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["kind"], "discovery")
        self.assertEqual(state[2]["kind"], "targeted")
        self.assertEqual(state[2]["scope"]["draft_lines"], [10, 50])

    def test_recorded_reason_is_read_alongside_the_kind(self):
        """Issue #1103: read_state carries the recorded kind_reason per round."""
        state = CICE.read_state(self._state(
            '{"rounds": [{"round": 1, "kind": "discovery", '
            '"kind_reason": "no-round-dispatched"}, '
            '{"round": 2, "kind": "discovery", "kind_reason": "empty-delta"}]}'))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["kind_reason"], "no-round-dispatched")
        self.assertEqual(state[2]["kind_reason"], "empty-delta")

    def test_absent_reason_reads_unestablished_never_a_guess(self):
        """Issue #1103: a round carrying no reason (pre-change record, or a legacy round)
        reads `unestablished` — never a guessed value, and never a whole-state collapse."""
        state = CICE.read_state(self._state(
            '{"rounds": [{"round": 1, "kind": "discovery"}, '
            '{"round": 2, "kind": "targeted", "kind_reason": "targeted-eligible"}]}'))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["kind_reason"], CICE.UNESTABLISHED)
        self.assertEqual(state[2]["kind_reason"], "targeted-eligible")

    def test_non_string_reason_reads_unestablished(self):
        """Issue #1103: a present-but-non-string reason is unestablished, never coerced —
        and does not collapse the whole state (the state owner's _validate is the boundary
        that refuses an off-vocabulary reason on load)."""
        state = CICE.read_state(self._state(
            '{"rounds": [{"round": 1, "kind": "discovery", "kind_reason": 7}]}'))
        self.assertIsNotNone(state)
        self.assertEqual(state[1]["kind_reason"], CICE.UNESTABLISHED)


class RoundKindCouplingTest(unittest.TestCase):
    """The eval's ROUND_KINDS mirror of the state owner's `_ROUND_KINDS` (issue #793).

    The eval is a standalone stdlib-only instrument that imports nothing from the state
    owner, so the vocabulary is a deliberate duplicated literal. This reconciles the two
    so a third kind added to the owner goes RED here instead of silently collapsing
    every real state file this reader sees.
    """

    _OWNER = os.path.join(_REPO, "scripts", "issue-audit-state.py")
    _SELF = "lib/test/test_create_issue_context_eval.py::RoundKindCouplingTest"

    def _owner(self):
        return _load_module("issue_audit_state_for_coupling", self._OWNER)

    def test_round_kinds_mirror_the_state_owner(self):
        self.assertEqual(set(CICE.ROUND_KINDS), set(self._owner()._ROUND_KINDS))

    def test_absent_kind_default_is_in_the_vocabulary(self):
        self.assertIn(CICE._ABSENT_KIND_DEFAULT, CICE.ROUND_KINDS)

    def test_unresolved_status_mirrors_the_owners_ledger_vocabulary(self):
        """The settled set is the owner's vocabulary minus the one outstanding member.

        A fifth status added to the owner would otherwise be read as outstanding by
        `_is_outstanding_must_revise` and would silently inflate both the escape count
        and its unattributable denominator.
        """
        owner_statuses = set(self._owner()._LEDGER_STATUSES)
        self.assertIn(CICE._UNRESOLVED_STATUS, owner_statuses)
        # Every other member is settled — assert the complement is exactly what the
        # proxy treats as settled, by driving the predicate over the whole vocabulary.
        for status in owner_statuses:
            outstanding = CICE._is_outstanding_must_revise({"status": status})
            self.assertEqual(outstanding, status == CICE._UNRESOLVED_STATUS,
                             "status {!r} classified wrongly".format(status))

    def test_impact_classes_mirror_the_state_owner(self):
        """A sixth impact class added to the owner must not ship green here."""
        self.assertEqual(set(CICE._IMPACT_CLASSES), set(self._owner()._IMPACT_CLASSES))

    def test_impact_counts_fails_closed_on_an_unmirrored_class(self):
        """An owner-accepted class this mirror lacks reads unestablished, never raises."""
        state = {"rounds": [{
            "advisory_count": 1,
            "advisory_records": [{"impact_class": "a-class-this-mirror-does-not-carry"}],
        }]}
        self.assertEqual(
            CICE._impact_counts(state, "advisory"),
            {name: CICE.UNESTABLISHED for name in CICE._IMPACT_CLASSES})
        # Positive control on the same fixture shape: a mirrored class still tallies.
        state["rounds"][0]["advisory_records"] = [{"impact_class": "scope"}]
        self.assertEqual(CICE._impact_counts(state, "advisory")["scope"], 1)

    def test_impact_counts_fails_closed_on_an_absent_class_field(self):
        state = {"rounds": [{"advisory_count": 1, "advisory_records": [{}]}]}
        self.assertEqual(
            CICE._impact_counts(state, "advisory"),
            {name: CICE.UNESTABLISHED for name in CICE._IMPACT_CLASSES})

    def test_impact_counts_fails_closed_on_a_non_dict_record(self):
        """The record-shape row of the matrix: a scalar previously raised TypeError."""
        for record in ("a string", None, 7, ["nested"]):
            with self.subTest(record=record):
                state = {"rounds": [{
                    "advisory_count": 1, "advisory_records": [record]}]}
                self.assertEqual(
                    CICE._impact_counts(state, "advisory"),
                    {name: CICE.UNESTABLISHED for name in CICE._IMPACT_CLASSES})

    def test_the_pointer_constants_name_this_test(self):
        """A hand-written test path rots silently; assert it resolves to THIS class."""
        for const in (CICE.ROUND_KINDS_COUPLING_ASSERTED_BY,
                      CICE.LEDGER_STATUS_COUPLING_ASSERTED_BY,
                      CICE.IMPACT_CLASS_COUPLING_ASSERTED_BY):
            self.assertEqual(const, self._SELF)
        path, _, cls = self._SELF.partition("::")
        self.assertTrue(os.path.isfile(os.path.join(_REPO, path)))
        self.assertEqual(cls, type(self).__name__)


class PerKindAndProxyTest(unittest.TestCase):
    """Issue #889 AC6/AC9/AC11: per-kind medians and the three escaped-defect proxies."""

    def _summary(self, corpus, state_name):
        runs, _ = CICE.eval_corpus(os.path.join(_FIX, corpus))
        state = CICE.read_state(os.path.join(_FIX, "states", state_name))
        return runs, CICE.aggregate(runs, state)

    def test_per_kind_medians(self):
        _runs, summary = self._summary("after-rounds", "after-state.json")
        # discovery rounds: r1=139000, r3=50000 -> median 94500; targeted: r2=26800.
        self.assertEqual(summary["median_auditor_cost_discovery"], 94500)
        self.assertEqual(summary["median_auditor_cost_targeted"], 26800)

    def test_reopen_proxy(self):
        _runs, summary = self._summary("after-rounds", "after-state.json")
        self.assertEqual(summary["total_record_reopen"], 1)

    def test_scope_escape_proxy_and_denominator(self):
        _runs, summary = self._summary("after-rounds", "after-state.json")
        # One later-round OUTSTANDING finding (line 30) falls inside the earlier
        # targeted [10,50] scope; one carries no draft line (unattributable). The
        # fixture also holds a `resolved` entry at line 31 (inside the same scope) and
        # a `superseded` entry with no line: AC9 scopes the proxy to must-revise
        # findings, so neither may reach `count` or the denominator.
        self.assertEqual(summary["scope_escape_count"], 1)
        self.assertEqual(summary["scope_escape_unattributable"], 1)

    def test_settled_later_round_entries_are_excluded(self):
        """Directly: flip every settled entry to `unresolved` and both figures move.

        Without this the status filter could be deleted and every committed assertion
        would keep passing, because every fixture finding used to be `unresolved`.
        """
        state = CICE.read_state(os.path.join(_FIX, "states", "after-state.json"))
        for finding in state[3]["findings"]:
            finding["status"] = "unresolved"
        unfiltered = CICE.scope_escape_proxy(state)
        self.assertEqual(unfiltered, {"count": 2, "unattributable": 2})

    def test_post_filing_and_wall_clock_are_unestablished(self):
        _runs, summary = self._summary("after-rounds", "after-state.json")
        self.assertEqual(summary["post_filing_escapes"], "unestablished")
        self.assertEqual(summary["wall_clock"], "unestablished")

    def test_producer_shaped_targeted_scope_reads_unestablished_not_zero(self):
        """A targeted round whose scope carries no draft-line span (a pre-#1105 round).

        As of issue #1105 `record-dispatch` writes `scope.draft_lines`, but a round
        recorded before that — or one whose span could not be computed — carries none. A
        targeted round the proxy cannot place must make BOTH figures `unestablished`;
        reporting `0` there would publish the value that reads as "no defects escaped
        scope" about a comparison that never ran.
        """
        _runs, summary = self._summary(
            "after-rounds", "after-state-producer-shape.json")
        self.assertEqual(summary["scope_escape_count"], "unestablished")
        self.assertEqual(summary["scope_escape_unattributable"], "unestablished")
        # Positive control on the same fixture: the state IS otherwise established, so
        # the sentinel above is attributable to the missing span and not to a
        # degraded-state read ten lines away.
        self.assertEqual(summary["median_auditor_cost_targeted"], 26800)

    def test_malformed_and_inverted_spans_read_unestablished(self):
        for scope in ({"draft_lines": [50, 10]},          # inverted
                      {"draft_lines": [10]},              # wrong arity
                      {"draft_lines": ["10", "50"]},      # wrong element type
                      {"draft_lines": [True, False]},     # bools are not line numbers
                      {}):                                # absent
            state = {1: {"kind": "targeted", "scope": scope, "findings": []},
                     2: {"kind": "discovery", "scope": None,
                         "findings": [{"status": "unresolved",
                                       "quoted_draft_line": 20}]}}
            self.assertEqual(
                CICE.scope_escape_proxy(state),
                {"count": "unestablished", "unattributable": "unestablished"},
                "a targeted round with scope {!r} must not yield a number".format(scope))

    def test_non_positive_quoted_draft_line_is_unattributable(self):
        """Matches the state owner's own `>= 1` boundary; 0/negative are not lines."""
        for bad in (0, -5, True, "12", None):
            self.assertIsNone(
                CICE._finding_draft_line({"quoted_draft_line": bad}),
                "quoted_draft_line {!r} must not be treated as attributable".format(bad))
        self.assertEqual(CICE._finding_draft_line({"quoted_draft_line": 1}), 1)

    def test_before_has_no_targeted_scope_so_zero_escapes(self):
        _runs, summary = self._summary("before-rounds", "before-state.json")
        # A state with NO targeted round at all is a genuine, established zero:
        # nothing can escape a scope that was never dispatched.
        self.assertEqual(summary["scope_escape_count"], 0)
        self.assertEqual(summary["scope_escape_unattributable"], 0)
        self.assertEqual(summary["median_auditor_cost_targeted"], "unestablished")
        # Drive the denominator on a state that DOES have a targeted scope, so the
        # counter is exercised rather than short-circuited by `if not earlier_targeted`.
        state = {1: {"kind": "targeted", "scope": {"draft_lines": [1, 5]},
                     "findings": []},
                 2: {"kind": "discovery", "scope": None,
                     "findings": [{"status": "unresolved"},
                                  {"status": "unresolved"}]}}
        self.assertEqual(CICE.scope_escape_proxy(state),
                         {"count": 0, "unattributable": 2})

    def test_empty_corpus_reads_unestablished_on_EVERY_axis_not_zero(self):
        """One convention across the whole summary — no field says `0` for "no runs".

        A reader must never have to know which field they are looking at to tell a
        measured zero from an empty population.
        """
        summary = CICE.aggregate([], None)
        numeric_axes = [k for k in summary
                        if k not in ("run_count", "state_established")]
        self.assertTrue(numeric_axes)
        for key in numeric_axes:
            self.assertEqual(summary[key], "unestablished",
                             "{} collapsed an empty population onto a value".format(key))
        self.assertEqual(summary["run_count"], 0)

    def test_partially_labelled_state_makes_every_per_kind_median_unestablished(self):
        """A state covering only round 1 must not publish a median over that subset."""
        runs, _ = CICE.eval_corpus(os.path.join(_FIX, "after-rounds"))
        partial = {1: {"kind": "discovery", "scope": None, "findings": []}}
        medians = CICE.per_kind_medians(runs, partial)
        self.assertEqual(medians, {"discovery": "unestablished",
                                   "targeted": "unestablished"})
        # Positive control: the FULL state over the same runs does yield numbers, so
        # the sentinels above are attributable to the missing labels.
        full = CICE.read_state(os.path.join(_FIX, "states", "after-state.json"))
        self.assertEqual(CICE.per_kind_medians(runs, full)["discovery"], 94500)

    def test_per_run_breakdown_carries_each_rounds_recorded_kind(self):
        """AC6: the kind lives on the per-run breakdown, not only in the aggregate."""
        report = CICE.build_report(
            os.path.join(_FIX, "after-rounds"),
            os.path.join(_FIX, "states", "after-state.json"))
        run = report["runs"][0]
        self.assertEqual(run["round_kinds"],
                         {1: "discovery", 2: "targeted", 3: "discovery"})
        rendered = CICE._render_run_line(run)
        self.assertIn("r2=26800(targeted)", rendered)
        self.assertIn("r1=139000(discovery)", rendered)

    def test_per_run_kinds_read_unestablished_with_no_state(self):
        report = CICE.build_report(os.path.join(_FIX, "after-rounds"))
        self.assertEqual(set(report["runs"][0]["round_kinds"].values()),
                         {"unestablished"})
        self.assertIn("(unestablished)", CICE._render_run_line(report["runs"][0]))

    def test_per_run_breakdown_carries_each_rounds_recorded_reason(self):
        """Issue #1103: the selecting reason lives on the per-run breakdown beside the
        kind, and a round the state does not label reads `unestablished` (never guessed).

        The committed `after-state.json` fixture records no `kind_reason` on any round, so
        every reason reads `unestablished` here — which is exactly the absent-field arm
        this AC also asks for. A round whose reason IS recorded is covered by the
        `_join_round_kinds` unit test below."""
        report = CICE.build_report(
            os.path.join(_FIX, "after-rounds"),
            os.path.join(_FIX, "states", "after-state.json"))
        run = report["runs"][0]
        self.assertEqual(set(run["round_reasons"].values()), {"unestablished"})
        self.assertIn("per-round selecting reason:", CICE._render_run_line(run))

    def test_join_reads_a_recorded_reason_and_unestablished_for_an_absent_one(self):
        """Issue #1103: one fixture per shape — a round whose record carries the reason,
        and a round whose record carries none — read through the join."""
        runs = [{"round_auditor_cost": {1: 100, 2: 200}}]
        state = {1: {"kind": "discovery", "kind_reason": "no-round-dispatched"},
                 2: {"kind": "discovery", "kind_reason": CICE.UNESTABLISHED}}
        CICE._join_round_kinds(runs, state)
        self.assertEqual(runs[0]["round_reasons"],
                         {1: "no-round-dispatched", 2: "unestablished"})
        # A round absent from the state entirely also reads unestablished.
        runs2 = [{"round_auditor_cost": {3: 300}}]
        CICE._join_round_kinds(runs2, state)
        self.assertEqual(runs2[0]["round_reasons"], {3: "unestablished"})


class PairedDeltaTest(unittest.TestCase):
    """Issue #889 AC7/AC12: paired before/after deltas and the reduction inequality."""

    def _paired(self):
        return CICE.build_paired_report(
            os.path.join(_FIX, "before-rounds"),
            os.path.join(_FIX, "after-rounds"),
            os.path.join(_FIX, "states", "before-state.json"),
            os.path.join(_FIX, "states", "after-state.json"),
        )

    def test_reduction_detected_with_strict_inequality(self):
        report = self._paired()
        before_cost = report["before"]["runs"][0]["attributed_auditor_cost"]
        after_cost = report["after"]["runs"][0]["attributed_auditor_cost"]
        # The reduction is asserted LIVE from the committed fixtures with a strict
        # inequality, never from a transcribed figure.
        self.assertLess(after_cost, before_cost)

    def test_paired_delta_fields(self):
        report = self._paired()
        delta = report["delta"]
        self.assertEqual(set(delta), {
            "total_attributed_auditor_cost", "total_peak_context",
            "mean_peak_context_per_run", "median_main_thread_context",
            "total_round_count", "finding_count",
        })
        # Latency is deliberately NOT a delta field (wall-clock is unestablished).
        self.assertNotIn("latency", delta)
        self.assertLess(delta["total_attributed_auditor_cost"], 0)
        # The after corpus's ledger carries strictly more entries than the before's;
        # the exact figure is re-derived live from the two committed state fixtures
        # rather than transcribed, so a fixture edit moves it without leaving a stale
        # count behind in this comment.
        before_state = CICE.read_state(
            os.path.join(_FIX, "states", "before-state.json"))
        after_state = CICE.read_state(
            os.path.join(_FIX, "states", "after-state.json"))
        self.assertEqual(
            delta["finding_count"],
            CICE._finding_count(after_state) - CICE._finding_count(before_state))
        self.assertGreater(delta["finding_count"], 0)

    def test_per_run_context_delta_is_population_normalized(self):
        """AC7 names *per-run* context; the corpus sum does not discharge it.

        The confound this pins: a multi-run before side against a one-run after side
        makes `total_peak_context` hugely negative on population difference ALONE, while
        the per-run mean — each side divided by its own run count — stays at the real
        per-run difference. Driven by duplicating the before corpus's single session
        into a three-run side, so the two keys' population sensitivity is directly
        comparable on fixtures whose per-run figures are identical by construction.
        """
        with tempfile.TemporaryDirectory() as multi:
            src = os.path.join(_FIX, "before-rounds", "session-before-rounds.jsonl")
            with open(src, "r", encoding="utf-8") as fh:
                payload = fh.read()
            for n in range(3):
                with open(os.path.join(multi, "s{}.jsonl".format(n)),
                          "w", encoding="utf-8") as fh:
                    fh.write(payload)
            inflated = CICE.build_paired_report(
                multi, os.path.join(_FIX, "after-rounds"),
                os.path.join(_FIX, "states", "before-state.json"),
                os.path.join(_FIX, "states", "after-state.json"))
            honest = self._paired()
            self.assertEqual(inflated["before"]["summary"]["run_count"], 3)
            self.assertEqual(honest["before"]["summary"]["run_count"], 1)
            # The corpus-wide sum moves purely because the population tripled...
            self.assertLess(inflated["delta"]["total_peak_context"],
                            honest["delta"]["total_peak_context"])
            # ...while the per-run normalization is unchanged by that same tripling.
            self.assertAlmostEqual(inflated["delta"]["mean_peak_context_per_run"],
                                   honest["delta"]["mean_peak_context_per_run"])

    def test_per_run_context_delta_is_unestablished_on_a_degraded_side(self):
        with tempfile.TemporaryDirectory() as empty:
            report = CICE.build_paired_report(
                empty, os.path.join(_FIX, "after-rounds"), None,
                os.path.join(_FIX, "states", "after-state.json"))
            self.assertEqual(report["delta"]["mean_peak_context_per_run"],
                             "unestablished")
        # Positive control: with both sides populated the same key is a real number.
        self.assertIsInstance(self._paired()["delta"]["mean_peak_context_per_run"],
                              float)

    def test_paired_delta_omits_latency_even_in_json(self):
        """Serializes for real: the name has to be absent from the emitted bytes."""
        blob = json.dumps(self._paired(), sort_keys=True)
        self.assertNotIn("latency", blob)
        self.assertNotIn("wall_clock_s", blob)

    def test_finding_count_delta_is_unestablished_when_either_state_degrades(self):
        """A degraded state must not publish a measured-looking paired finding delta."""
        for before_state, after_state in (
                (None, os.path.join(_FIX, "states", "after-state.json")),
                (os.path.join(_FIX, "states", "before-state.json"), None),
                (None, None)):
            report = CICE.build_paired_report(
                os.path.join(_FIX, "before-rounds"),
                os.path.join(_FIX, "after-rounds"),
                before_state, after_state)
            self.assertEqual(report["delta"]["finding_count"], "unestablished")
        # Positive control: with BOTH states supplied the same call yields a number,
        # so the sentinel above is attributable to the degraded side.
        self.assertIsInstance(self._paired()["delta"]["finding_count"], int)

    def test_sum_deltas_are_unestablished_when_a_side_has_no_runs(self):
        """A side with no runs sums to 0; subtracting would assert a measured change.

        Without this the report contradicts itself in one document: the before side
        declares its primary axis `unestablished` while the delta block beside it
        asserts a large regression.
        """
        with tempfile.TemporaryDirectory() as empty:
            report = CICE.build_paired_report(
                empty, os.path.join(_FIX, "after-rounds"),
                None, os.path.join(_FIX, "states", "after-state.json"))
            self.assertEqual(report["before"]["summary"]["run_count"], 0)
            for key in ("total_attributed_auditor_cost", "total_peak_context",
                        "total_round_count"):
                self.assertEqual(report["delta"][key], "unestablished",
                                 "{} was measured against an empty corpus".format(key))
        # Positive control: both corpora populated -> the same three keys are numbers.
        for key in ("total_attributed_auditor_cost", "total_peak_context",
                    "total_round_count"):
            self.assertIsInstance(self._paired()["delta"][key], int)

    def test_finding_count_is_unestablished_not_zero_on_a_degraded_state(self):
        self.assertEqual(CICE._finding_count(None), "unestablished")
        report = CICE.build_report(os.path.join(_FIX, "after-rounds"))
        self.assertEqual(report["finding_count"], "unestablished")
        self.assertFalse(report["state_established"])


class RendererTest(unittest.TestCase):
    """Both text renderers over the live field sets (`.format(**r)` key drift is a
    runtime KeyError otherwise)."""

    def _paired(self):
        return CICE.build_paired_report(
            os.path.join(_FIX, "before-rounds"),
            os.path.join(_FIX, "after-rounds"),
            os.path.join(_FIX, "states", "before-state.json"),
            os.path.join(_FIX, "states", "after-state.json"),
        )

    def test_render_text_renders_every_summary_field_as_a_scalar(self):
        report = CICE.build_report(
            os.path.join(_FIX, "after-rounds"),
            os.path.join(_FIX, "states", "after-state.json"))
        out = CICE.render_text(report["runs"], report["summary"], report["skipped"])
        for key in report["summary"]:
            self.assertIn("- {}: ".format(key), out)
        # No raw dict/list repr leaks into the report.
        self.assertNotIn("{'", out)
        self.assertIn("- state_established: True", out)

    def test_render_paired_text_covers_both_sides_and_the_deltas(self):
        out = CICE.render_paired_text(self._paired())
        self.assertIn("## Before", out)
        self.assertIn("## After", out)
        self.assertIn("## Paired deltas (after - before)", out)
        self.assertIn("- total_peak_context: ", out)
        self.assertIn("- total_attributed_auditor_cost: ", out)
        self.assertNotIn("per_run_context", out)


class MainCliTest(unittest.TestCase):
    """The paired-mode validation arms — each returns 2 rather than raising."""

    _BEFORE = os.path.join(_FIX, "before-rounds")
    _AFTER = os.path.join(_FIX, "after-rounds")
    _BSTATE = os.path.join(_FIX, "states", "before-state.json")
    _ASTATE = os.path.join(_FIX, "states", "after-state.json")

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CICE.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_no_positional_and_no_pair_returns_two(self):
        rc, _out, err = self._run([])
        self.assertEqual(rc, 2)
        self.assertIn("transcript directory", err)

    def test_only_before_returns_two(self):
        rc, _out, err = self._run(["--before", self._BEFORE])
        self.assertEqual(rc, 2)
        self.assertIn("both --before and --after", err)

    def test_non_directory_pair_operand_returns_two_naming_it(self):
        rc, _out, err = self._run(
            ["--before", self._BEFORE, "--after", "/no/such/dir"])
        self.assertEqual(rc, 2)
        self.assertIn("--after directory not found", err)

    def test_missing_state_file_returns_two_naming_the_flag(self):
        rc, _out, err = self._run(
            ["--before", self._BEFORE, "--after", self._AFTER,
             "--after-state", "/no/such/state.json"])
        self.assertEqual(rc, 2)
        self.assertIn("--after-state file not found", err)

    def test_mode_mismatched_flags_are_refused_not_dropped(self):
        rc, _out, err = self._run(
            ["--before", self._BEFORE, "--after", self._AFTER,
             "--state-file", self._ASTATE])
        self.assertEqual(rc, 2)
        self.assertIn("--state-file is a single-corpus flag", err)
        rc, _out, err = self._run([self._AFTER, "--before-state", self._BSTATE])
        self.assertEqual(rc, 2)
        self.assertIn("--before-state is a paired-mode flag", err)
        # A positional transcript dir supplied alongside --before/--after is the third
        # mismatched-input arm: silently discarding it would make the operator read the
        # paired report as if it covered the corpus they named.
        rc, _out, err = self._run(
            ["--before", self._BEFORE, "--after", self._AFTER, self._AFTER])
        self.assertEqual(rc, 2)
        self.assertIn("positional transcript directory", err)

    def test_single_corpus_missing_state_file_returns_two_naming_the_flag(self):
        """Sibling of the paired --after-state check; without it a typo'd path falls
        through to read_state and reads as an honest data disclosure."""
        rc, _out, err = self._run(
            [self._AFTER, "--state-file", "/no/such/state.json"])
        self.assertEqual(rc, 2)
        self.assertIn("--state-file file not found", err)
        # Positive control: the same invocation with a real state file succeeds, so the
        # rc 2 above is attributable to the missing path and not to the corpus operand.
        rc, _out, _err = self._run([self._AFTER, "--state-file", self._ASTATE])
        self.assertEqual(rc, 0)

    def test_paired_json_and_text_both_succeed(self):
        argv = ["--before", self._BEFORE, "--after", self._AFTER,
                "--before-state", self._BSTATE, "--after-state", self._ASTATE]
        rc, out, _err = self._run(argv + ["--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIsInstance(json.loads(out)["delta"]["finding_count"], int)
        rc, out, _err = self._run(argv)
        self.assertEqual(rc, 0)
        self.assertIn("## Paired deltas (after - before)", out)

    def test_single_corpus_json_carries_the_state_disclosure(self):
        rc, out, _err = self._run(
            [self._AFTER, "--state-file", self._ASTATE, "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        # The disclosure lives in the summary, so the JSON and text modes carry an
        # identical field set — a reader of either can tell how to read every
        # `unestablished` figure beside it.
        self.assertTrue(doc["summary"]["state_established"])
        self.assertIsInstance(doc["summary"]["finding_count"], int)
        self.assertEqual(doc["summary"]["scope_escape_count"], 1)

    def test_single_corpus_missing_directory_returns_two_naming_it(self):
        """The single-corpus `isdir` arm, which two newer validations now precede.

        The diff moved the `--before-state`/`--after-state` mode-mismatch checks and the
        `--state-file` existence check ABOVE this one, so the surviving ordering is what
        this asserts: a bare missing directory still reaches its own arm and names it.
        """
        rc, _out, err = self._run(["/no/such/dir"])
        self.assertEqual(rc, 2)
        self.assertIn("transcript directory not found: /no/such/dir", err)
        # Positive control: the same call shape with a real directory succeeds, so the
        # rc 2 above is attributable to the missing path, not to the argv shape.
        rc, _out, _err = self._run([self._AFTER])
        self.assertEqual(rc, 0)


class StateNoneVsEmptyContractTest(unittest.TestCase):
    """`read_state` returns two DIFFERENT falsy answers; truthiness conflates them.

    `None` = never established; `{}` = established, no rounds. Every consumer tests
    `state is None` by convention, and a future `if state:` would silently reclassify a
    legitimately-empty state as unestablished. These assertions pin both readings so
    that flip goes RED.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _state(self, payload):
        path = os.path.join(self._tmp.name, "state.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return path

    def test_empty_rounds_state_is_established_not_none(self):
        state = CICE.read_state(self._state('{"rounds": []}'))
        self.assertEqual(state, {})
        self.assertIsNotNone(state)

    def test_aggregate_reads_an_empty_state_as_established_zero(self):
        summary = CICE.aggregate([], CICE.read_state(self._state('{"rounds": []}')))
        self.assertTrue(summary["state_established"])
        self.assertEqual(summary["finding_count"], 0)
        self.assertEqual(summary["scope_escape_count"], 0)
        # Negative control: the SAME empty run population with no state at all reports
        # the sentinel on those exact fields, so the numbers above are attributable to
        # the established-but-empty state rather than to the empty run list.
        none_summary = CICE.aggregate([], None)
        self.assertFalse(none_summary["state_established"])
        self.assertEqual(none_summary["finding_count"], "unestablished")
        self.assertEqual(none_summary["scope_escape_count"], "unestablished")

    def test_state_derived_fields_are_independent_of_the_run_population(self):
        """The docstring's scoped claim: state-derived fields do NOT read the run list.

        `aggregate([], <valid state>)` returns real state-derived figures — that is
        correct, and it is why the empty-population convention is documented as
        RUN-derived rather than universal.
        """
        state = CICE.read_state(os.path.join(_FIX, "states", "after-state.json"))
        summary = CICE.aggregate([], state)
        self.assertTrue(summary["state_established"])
        self.assertIsInstance(summary["finding_count"], int)
        self.assertGreater(summary["finding_count"], 0)
        # ...while every RUN-derived figure on the same object reads the sentinel.
        for key in ("median_peak_context", "max_peak_context",
                    "median_attributed_auditor_cost", "total_record_reopen"):
            self.assertEqual(summary[key], "unestablished", key)
        self.assertEqual(summary["run_count"], 0)


class SidechainOnlySessionTest(_SingleSessionMixin, unittest.TestCase):
    """A session file with auditor records but no main-thread attributed turn.

    `if acc.attributed` drops it whole, taking `sidechain_records_seen` with it — the
    operand that makes the module's unverified `attributionSkill`-on-sidechain
    assumption falsifiable. Dropping it silently defeats that disclosure in exactly the
    layout where the assumption is most likely wrong, so the drop is tallied.
    """

    def test_sidechain_only_file_is_tallied_not_silently_dropped(self):
        runs, skipped = self._run_one([
            '{"type":"assistant","isSidechain":true,'
            '"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":900}}}',
        ])
        self.assertEqual(runs, [])
        self.assertEqual(skipped["sidechain_only_file"], 1)

    def test_unstamped_sidechain_only_file_is_also_tallied(self):
        """The layout the assumption fails in: sidechain records with no attribution."""
        runs, skipped = self._run_one([
            '{"type":"assistant","isSidechain":true,'
            '"message":{"usage":{"input_tokens":900}}}',
        ])
        self.assertEqual(runs, [])
        self.assertEqual(skipped["sidechain_only_file"], 1)

    def test_a_session_with_no_records_at_all_is_not_tallied(self):
        """Negative control: the tally means "sidechain seen", not "no run emitted"."""
        runs, skipped = self._run_one([
            '{"type":"assistant","attributionSkill":"other",'
            '"message":{"usage":{"input_tokens":5}}}',
        ])
        self.assertEqual(runs, [])
        self.assertEqual(skipped["sidechain_only_file"], 0)


class PairedDeltaDegradedChannelsTest(unittest.TestCase):
    """`_paired_delta._degraded` consults EVERY skip channel, not `unreadable_file`.

    Each channel drops either a whole session file or a `usage`-bearing record inside a
    counted run, so each deflates the sums the delta subtracts: a before-corpus with a
    permission-denied subtree publishes a large negative delta as a measured saving.
    """

    _CHANNELS = ("non_json_line", "not_object", "no_type", "unreadable_file",
                 "escaped_path", "walk_error", "malformed_record",
                 "sidechain_only_file")

    def _report(self, skipped):
        """A minimal report shape with one run and the supplied skip tally."""
        return {"runs": [{"attributed_auditor_cost": 10, "peak_context": 10,
                          "dispatch_rounds": [1]}],
                "skipped": dict(skipped),
                "finding_count": 3}

    def test_every_channel_degrades_the_sum_deltas(self):
        clean = {k: 0 for k in self._CHANNELS}
        # Positive control FIRST: a clean tally on both sides yields real numbers, so
        # each `unestablished` below is attributable to the one channel under test.
        baseline = CICE._paired_delta(self._report(clean), self._report(clean))
        for key in ("total_attributed_auditor_cost", "total_peak_context",
                    "total_round_count"):
            self.assertIsInstance(baseline[key], int, key)
        for channel in self._CHANNELS:
            dirty = dict(clean, **{channel: 1})
            for before, after in ((self._report(dirty), self._report(clean)),
                                  (self._report(clean), self._report(dirty))):
                delta = CICE._paired_delta(before, after)
                for key in ("total_attributed_auditor_cost", "total_peak_context",
                            "total_round_count"):
                    self.assertEqual(
                        delta[key], "unestablished",
                        "{} stayed measured with {} > 0".format(key, channel))

    def test_the_guard_covers_the_live_skip_key_set(self):
        """The channel list above is reconciled against `eval_corpus`'s own tally.

        A channel added to `eval_corpus` and not to `_CHANNELS` would leave this test
        asserting less than the guard covers while both stayed green.
        """
        with tempfile.TemporaryDirectory() as empty:
            _runs, skipped = CICE.eval_corpus(empty)
        self.assertEqual(set(skipped), set(self._CHANNELS))


class NonNumericPeakContextTest(unittest.TestCase):
    """A non-numeric `peak_context` reports `unestablished`, never raising (issue #1702).

    Every `peak_context` axis does arithmetic on the field — a sum, a mean, a median — so an
    unmeasured value that reached them would raise `TypeError` out of a module whose contract
    is to publish the `unestablished` sentinel. Both guarded sites are driven here: the
    `_paired_delta` context keys and `_manifest_comparison`'s median pair.
    """

    _CHANNELS = ("non_json_line", "not_object", "no_type", "unreadable_file",
                 "escaped_path", "walk_error", "malformed_record",
                 "sidechain_only_file")
    _CONTEXT_KEYS = ("total_peak_context", "mean_peak_context_per_run",
                     "median_main_thread_context")

    def _report(self, peak_context):
        return {"runs": [{"attributed_auditor_cost": 10, "peak_context": peak_context,
                          "dispatch_rounds": [1]}],
                "skipped": {k: 0 for k in self._CHANNELS},
                "finding_count": 3}

    def test_paired_delta_context_keys_go_unestablished_not_raising(self):
        # Positive control FIRST: numeric peaks yield real numbers on the same fixture, so
        # each `unestablished` below is attributable to the non-numeric value alone.
        clean = CICE._paired_delta(self._report(10), self._report(10))
        for key in self._CONTEXT_KEYS:
            self.assertNotEqual(clean[key], CICE.UNESTABLISHED, key)
        # A non-numeric peak on EITHER side degrades all three, and the non-context keys
        # stay measured — the guard is scoped to the axis that reads the field.
        for label, (before, after) in (
            ("before", (self._report(CICE.UNESTABLISHED), self._report(10))),
            ("after", (self._report(10), self._report(CICE.UNESTABLISHED))),
            ("both", (self._report(None), self._report(None))),
        ):
            delta = CICE._paired_delta(before, after)
            for key in self._CONTEXT_KEYS:
                self.assertEqual(delta[key], CICE.UNESTABLISHED,
                                 "{} stayed measured with a non-numeric peak ({})"
                                 .format(key, label))
            self.assertEqual(delta["total_attributed_auditor_cost"], 0, label)
            self.assertEqual(delta["total_round_count"], 0, label)

    def test_a_boolean_peak_is_not_a_number(self):
        """`isinstance(True, int)` is True, so a bare int check would admit it and publish a
        median derived from booleans as a measured token cost."""
        delta = CICE._paired_delta(self._report(True), self._report(10))
        for key in self._CONTEXT_KEYS:
            self.assertEqual(delta[key], CICE.UNESTABLISHED, key)

    def _manifest_run(self, configuration, peak_context):
        return {
            "configuration": configuration,
            "scenario_id": "s1",
            "repetition": 1,
            "run_id": "run-" + configuration,
            "peak_context": peak_context,
            "attributed_auditor_cost": 10,
            "dispatch_rounds": [1],
            "finding_count": 2,
            "state_established": True,
            "grade": None,
            "occurrence": {"boundary_confidence": "exact"},
            "provenance": {"repo_sha": "abc", "prompt_fingerprint": "p", "model": "m",
                           "effort": "high", "output_style": "o", "provider": "v",
                           "skill_fingerprint": "s"},
        }

    def test_manifest_comparison_median_pair_goes_unestablished(self):
        # Positive control on the same pair shape: numeric peaks establish both medians and
        # the verdict, so the sentinels below cannot come from an unrelated earlier gate.
        clean = CICE._manifest_comparison([self._manifest_run("baseline", 100),
                                           self._manifest_run("revised", 90)])
        self.assertEqual(clean["status"], "established", clean.get("diagnostic"))
        self.assertEqual(clean["median_main_thread_context"]["baseline"], 100)
        self.assertEqual(clean["median_main_thread_context"]["revised"], 90)
        self.assertIs(clean["revised_median_within_baseline"], True)
        # One unmeasured peak makes BOTH medians and the verdict the sentinel — never a
        # number on the measurable side beside an unknown on the other, which would read as
        # a comparison against a value that was never measured.
        for label, (before_peak, after_peak) in (
            ("baseline unmeasured", (CICE.UNESTABLISHED, 90)),
            ("revised unmeasured", (100, CICE.UNESTABLISHED)),
        ):
            report = CICE._manifest_comparison([
                self._manifest_run("baseline", before_peak),
                self._manifest_run("revised", after_peak)])
            self.assertEqual(report["status"], "established", label)
            median = report["median_main_thread_context"]
            self.assertEqual(median["baseline"], CICE.UNESTABLISHED, label)
            self.assertEqual(median["revised"], CICE.UNESTABLISHED, label)
            self.assertEqual(report["revised_median_within_baseline"],
                             CICE.UNESTABLISHED, label)
            self.assertEqual(report["delta"]["median_main_thread_context"],
                             CICE.UNESTABLISHED, label)


class ManifestIngestionTest(unittest.TestCase):
    def setUp(self):
        self.manifest_path = os.path.join(_MANIFEST_FIX, "two-occurrences.json")

    def _api(self, name):
        self.assertTrue(
            hasattr(CICE, name),
            "create-issue evaluator is missing the required {} API".format(name),
        )
        return getattr(CICE, name)

    def _mutated_manifest(self, mutate):
        with open(self.manifest_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["root"] = _MANIFEST_FIX
        mutate(doc)
        temp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.addCleanup(lambda: os.path.exists(temp.name) and os.unlink(temp.name))
        with temp:
            json.dump(doc, temp)
        return temp.name

    def _copied_manifest(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = os.path.join(temp.name, "manifest-root")
        shutil.copytree(_MANIFEST_FIX, root)
        return os.path.join(root, "two-occurrences.json"), root

    def _mutate_copied_manifest(self, mutate):
        path, root = self._copied_manifest()
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        mutate(doc, root)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path, root

    def _mutate_transcript(self, root, mutate):
        path = os.path.join(root, "runs", "shared", "transcript.jsonl")
        with open(path, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        mutate(records)
        _write(os.path.dirname(path), os.path.basename(path), [
            json.dumps(record) for record in records
        ])

    def test_modular_analyzer_exports_the_legacy_and_manifest_interfaces(self):
        self.assertTrue(
            os.path.isfile(_MODULAR_EVAL_PATH),
            "scripts/create_issue_eval.py does not exist",
        )
        module = _load_module("create_issue_eval", _MODULAR_EVAL_PATH)
        for name in (
            "RunAccumulator",
            "eval_corpus",
            "read_state",
            "aggregate",
            "render_text",
            "load_eval_manifest",
            "build_manifest_report",
        ):
            self.assertTrue(hasattr(module, name), name)
            self.assertTrue(hasattr(CICE, name), "legacy import surface lost {}".format(name))

    def test_event_bounds_split_two_occurrences_and_join_each_runs_state(self):
        report = self._api("build_manifest_report")(self.manifest_path)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["benchmark_id"], "two-occurrences")
        self.assertEqual([run["run_id"] for run in report["runs"]], [
            "baseline-vague-1",
            "candidate-vague-1",
        ])
        self.assertEqual([run["peak_context"] for run in report["runs"]], [10, 100])
        self.assertEqual(report["runs"][0]["round_kinds"], {1: "discovery"})
        self.assertEqual(report["runs"][1]["round_kinds"], {1: "targeted"})
        self.assertEqual(
            [run["occurrence"]["occurrence_id"] for run in report["runs"]],
            ["create-issue-1", "create-issue-2"],
        )
        self.assertEqual(report["comparison"]["status"], "established")
        self.assertIsNone(report["comparison"]["diagnostic"])

    def test_a_state_file_missing_a_dispatched_round_degrades_that_runs_kinds(self):
        """Delete this guard and a mismatched state ships confidently-wrong kinds."""
        def add_undispatched_round(doc, root):
            # The state records a round the transcript never dispatched, so the two
            # round sets disagree. Without the guard round 1 still resolves to its
            # recorded kind — a confident answer from a state that does not match
            # this run — which is exactly what the degradation must replace.
            state_path = os.path.join(root, doc["runs"][0]["state_file"])
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
            extra = json.loads(json.dumps(state["rounds"][0]))
            extra["round"] = 2
            state["rounds"].append(extra)
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)

        path, _root = self._mutate_copied_manifest(add_undispatched_round)
        report = self._api("build_manifest_report")(path)
        self.assertEqual(report["runs"][0]["round_kinds"], {1: CICE.UNESTABLISHED})
        # Positive control: the untouched sibling run still resolves its real kind,
        # so the degradation is scoped to the run whose state actually mismatched.
        self.assertEqual(report["runs"][1]["round_kinds"], {1: "targeted"})

    def test_manifest_mode_adds_explicit_draft_audit_and_grade_artifacts(self):
        report = self._api("build_manifest_report")(self.manifest_path)
        for run in report["runs"]:
            self.assertIn("draft_metrics", run)
            self.assertEqual(run["audit_outcomes"]["status"], "established")
            self.assertTrue(run["grade"]["assertions"])
        quality = report["comparison"]["pairs"][0]["quality"]
        self.assertTrue(quality["passed"])
        self.assertTrue(quality["efficiency_eligible"])

    def test_deeply_nested_rubric_has_stable_named_diagnostic(self):
        positive = self._api("build_manifest_report")(self.manifest_path)
        self.assertTrue(positive["runs"][0]["grade"]["assertions"])

        def deeply_nested_rubric(_doc, root):
            path = os.path.join(root, "rubrics", "quality.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[" * 10000 + "0" + "]" * 10000)

        path, _root = self._mutate_copied_manifest(deeply_nested_rubric)
        with self.assertRaisesRegex(
            ValueError, "invalid_rubric: baseline-vague-1"
        ):
            self._api("build_manifest_report")(path)

    def test_a_deeply_nested_manifest_fails_closed_rather_than_raising(self):
        path = self._mutated_manifest(lambda doc: None)
        self._api("load_eval_manifest")(path)  # positive control on the same fixture
        deep = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.addCleanup(lambda: os.path.exists(deep.name) and os.unlink(deep.name))
        with deep:
            deep.write(_DEEP_JSON)
        # Key the patch on the handle: an unconditional one would attribute a failure to
        # the wrong call if a second `json.load` is ever added to `load_eval_manifest`.
        real_load = json.load

        def _load(handle, *args, **kwargs):
            if getattr(handle, "name", None) == deep.name:
                raise RecursionError("maximum recursion depth exceeded while decoding")
            return real_load(handle, *args, **kwargs)

        with unittest.mock.patch.object(json, "load", _load):
            with self.assertRaisesRegex(
                ValueError, "invalid_manifest: .*maximum recursion depth"
            ):
                self._api("load_eval_manifest")(deep.name)

    def test_a_deeply_nested_transcript_line_fails_closed_rather_than_raising(self):
        control = self._api("build_manifest_report")(self.manifest_path)
        self.assertTrue(control["runs"])

        def _append_deep_line(_doc, root):
            transcript = os.path.join(root, "runs", "shared", "transcript.jsonl")
            with open(transcript, "a", encoding="utf-8") as fh:
                fh.write(_DEEP_JSON + "\n")

        path, _root = self._mutate_copied_manifest(_append_deep_line)
        # `_DEEP_JSON` decodes to a LIST, so the not-an-object arm two statements below
        # raises the same `invalid_transcript` diagnostic: match the decode arm's own
        # message or the test passes without ever reaching the widened clause.
        with _recursion_error_on(_DEEP_JSON):
            with self.assertRaisesRegex(
                ValueError, r"invalid_transcript: .* line \d+: maximum recursion depth"
            ):
                self._api("build_manifest_report")(path)

    def test_a_resumed_session_requires_its_own_explicit_benchmark_run_id(self):
        path = self._mutated_manifest(
            lambda doc: doc["runs"][1].pop("run_id")
        )
        with self.assertRaisesRegex(ValueError, "missing_run_id"):
            self._api("load_eval_manifest")(path)

    def test_manifest_validation_fails_closed_with_named_diagnostics(self):
        cases = {
            "duplicate_run_id": lambda doc: doc["runs"].append(
                copy.deepcopy(doc["runs"][0])
            ),
            "missing_occurrence_identity": lambda doc: doc["runs"][0][
                "occurrence"
            ].pop("occurrence_id"),
            "path_escape": lambda doc: doc["runs"][0].__setitem__(
                "transcript", "../escaped.jsonl"
            ),
            "missing_artifact": lambda doc: doc["runs"][0]["checkpoints"].__setitem__(
                "final", "runs/baseline/missing-final.md"
            ),
            "unsupported_schema_version": lambda doc: doc.__setitem__(
                "schema_version", 2
            ),
        }
        for diagnostic, mutate in cases.items():
            with self.subTest(diagnostic=diagnostic):
                path = self._mutated_manifest(mutate)
                with self.assertRaisesRegex(ValueError, diagnostic):
                    self._api("load_eval_manifest")(path)

    def test_mixed_pair_provenance_is_unestablished(self):
        path = self._mutated_manifest(
            lambda doc: doc["runs"][1]["provenance"].__setitem__(
                "provider", "different-provider"
            )
        )
        comparison = self._api("build_manifest_report")(path)["comparison"]
        self.assertEqual(comparison["status"], "unestablished")
        self.assertEqual(comparison["diagnostic"], "mixed_provenance")
        self.assertTrue(comparison["delta"])
        self.assertEqual(set(comparison["delta"].values()), {"unestablished"})

    def _second_repetition(self, mutate_repeat=None):
        # The per-configuration provenance guard only fires with >=2 runs of one
        # configuration; a one-repetition manifest never reaches it.
        def add_repetition(doc):
            repeats = []
            for index, run in enumerate(copy.deepcopy(doc["runs"])):
                run["run_id"] = "{}-2".format(run["run_id"])
                run["repetition"] = 2
                run["occurrence"]["occurrence_id"] = "create-issue-{}".format(
                    index + 3
                )
                repeats.append(run)
            if mutate_repeat is not None:
                mutate_repeat(repeats)
            doc["runs"].extend(repeats)

        return self._mutated_manifest(add_repetition)

    def test_repetitions_of_one_configuration_share_provenance(self):
        comparison = self._api("build_manifest_report")(
            self._second_repetition()
        )["comparison"]
        self.assertEqual(comparison["status"], "established")
        self.assertIsNone(comparison["diagnostic"])

    def test_ac10_established_carries_case_identity_and_median(self):
        # issue #1702 AC10: an established paired comparison emits the case-identity block,
        # the median runtime main-thread token cost per side with corpus size, the median
        # delta key, and the non-regression verdict.
        comparison = self._api("build_manifest_report")(self.manifest_path)["comparison"]
        self.assertEqual(comparison["status"], "established")
        self.assertEqual(comparison["case_identity"]["case_count"],
                         len(comparison["case_identity"]["cases"]))
        mmtc = comparison["median_main_thread_context"]
        self.assertIn("baseline", mmtc)
        self.assertIn("revised", mmtc)
        self.assertIn("corpus_size", mmtc)
        self.assertIn("median_main_thread_context", comparison["delta"])
        self.assertIn("revised_median_within_baseline", comparison)
        if all(isinstance(mmtc[k], (int, float)) for k in ("baseline", "revised")):
            self.assertEqual(comparison["revised_median_within_baseline"],
                             mmtc["revised"] <= mmtc["baseline"])
            # The emitted median delta equals revised-minus-baseline (ties the delta lambda
            # to the per-side medians, so a regression in either is caught).
            self.assertEqual(comparison["delta"]["median_main_thread_context"],
                             mmtc["revised"] - mmtc["baseline"])

    def test_ac10_case_swapped_identity_fails_closed(self):
        # Equal counts but a differing (scenario_id, repetition) on one side hits the
        # case_identity_mismatch branch distinctly (the added-case test hits count_mismatch).
        def swap_candidate_scenario(doc):
            for run in doc["runs"]:
                if run["configuration"] != "baseline":
                    run["scenario_id"] = "swapped-scenario"
        comparison = self._api("build_manifest_report")(
            self._mutated_manifest(swap_candidate_scenario))["comparison"]
        self.assertEqual(comparison["status"], "unestablished")
        self.assertEqual(comparison["diagnostic"], "case_identity_mismatch")
        self.assertEqual(set(comparison["delta"].values()), {"unestablished"})

    def test_ac10_case_split_by_resume_fails_closed(self):
        # A case identity appearing twice within one configuration (a run split by resume)
        # fails closed before any comparison.
        def dup_case(doc):
            extra = copy.deepcopy(doc["runs"][0])
            extra["run_id"] = extra["run_id"] + "-resume"
            extra["occurrence"]["occurrence_id"] = (
                extra["occurrence"]["occurrence_id"] + "-resume")
            doc["runs"].append(extra)
        comparison = self._api("build_manifest_report")(
            self._mutated_manifest(dup_case))["comparison"]
        self.assertEqual(comparison["status"], "unestablished")
        self.assertEqual(comparison["diagnostic"], "case_split_by_resume")
        self.assertEqual(set(comparison["delta"].values()), {"unestablished"})

    def test_ac10_case_identity_mismatch_fails_closed(self):
        # A case present on one side but not the other (missing / count mismatch) fails closed.
        def baseline_only_case(doc):
            extra = copy.deepcopy(doc["runs"][0])
            extra["run_id"] = extra["run_id"] + "-extra"
            extra["scenario_id"] = "brand-new-scenario"
            extra["occurrence"]["occurrence_id"] = (
                extra["occurrence"]["occurrence_id"] + "-extra")
            doc["runs"].append(extra)
        comparison = self._api("build_manifest_report")(
            self._mutated_manifest(baseline_only_case))["comparison"]
        self.assertEqual(comparison["status"], "unestablished")
        self.assertIn(comparison["diagnostic"],
                      ("case_count_mismatch", "case_identity_mismatch"))
        self.assertEqual(set(comparison["delta"].values()), {"unestablished"})

    def test_mixed_provenance_within_one_configuration_is_unestablished(self):
        # repo_sha is also pair-controlled, so it is drifted in BOTH repetition-2
        # runs: an only-one-side drift would be refused by the pairwise guard under
        # the same diagnostic and would not exercise this guard.
        drifts = {
            "skill_fingerprint": lambda repeats: repeats[0]["provenance"].__setitem__(
                "skill_fingerprint", "sha256:drifted"
            ),
            "repo_sha": lambda repeats: [
                run["provenance"].__setitem__("repo_sha", "fedcba9876543210")
                for run in repeats
            ],
        }
        for key, drift in drifts.items():
            with self.subTest(key=key):
                path = self._second_repetition(drift)
                comparison = self._api("build_manifest_report")(path)["comparison"]
                self.assertEqual(comparison["status"], "unestablished")
                self.assertEqual(comparison["diagnostic"], "mixed_provenance")
                self.assertEqual(
                    set(comparison["delta"].values()), {"unestablished"}
                )
                # A pairwise rejection returns after the first pair; only the
                # per-configuration guard rejects with both pairs recorded.
                self.assertEqual(len(comparison["pairs"]), 2)

    def test_forward_compatible_metadata_survives_without_changing_identity(self):
        def add_metadata(doc):
            doc["future_manifest_note"] = "preserve-me"
            run = doc["runs"][0]
            run["future_run_note"] = "preserve-me"
            run["occurrence"]["future_boundary_note"] = "preserve-me"
            run["checkpoints"]["future_checkpoint_note"] = "preserve-me"
            run["provenance"]["future_provenance_note"] = "preserve-me"

        loaded = self._api("load_eval_manifest")(
            self._mutated_manifest(add_metadata)
        )
        run = loaded["runs"][0]
        self.assertEqual(loaded["future_manifest_note"], "preserve-me")
        self.assertEqual(run["run_id"], "baseline-vague-1")
        self.assertEqual(run["future_run_note"], "preserve-me")
        self.assertEqual(run["occurrence"]["future_boundary_note"], "preserve-me")
        self.assertEqual(run["checkpoints"].get("future_checkpoint_note"), "preserve-me")
        self.assertEqual(run["provenance"]["future_provenance_note"], "preserve-me")

    def test_selected_events_with_missing_or_unsupported_types_are_rejected(self):
        cases = {
            "missing": lambda records: records[0].pop("type"),
            "unsupported": lambda records: records[0].__setitem__("type", "progress"),
        }
        for case, mutate in cases.items():
            with self.subTest(case=case):
                path, root = self._copied_manifest()
                self._mutate_transcript(root, mutate)
                with self.assertRaisesRegex(ValueError, "invalid_transcript"):
                    self._api("build_manifest_report")(path)

    def test_selected_metric_operands_never_collapse_to_zero(self):
        cases = {
            "missing usage": lambda records: records[0]["message"].pop("usage"),
            "wrong usage container": lambda records: records[0]["message"].__setitem__(
                "usage", []
            ),
            "missing output tokens": lambda records: records[0]["message"][
                "usage"
            ].pop("output_tokens", None),
            "wrong input tokens": lambda records: records[0]["message"][
                "usage"
            ].__setitem__("input_tokens", "10"),
            "negative input tokens": lambda records: records[0]["message"][
                "usage"
            ].__setitem__("input_tokens", -1),
        }
        for case, mutate in cases.items():
            with self.subTest(case=case):
                path, root = self._copied_manifest()
                self._mutate_transcript(root, mutate)
                with self.assertRaisesRegex(ValueError, "invalid_transcript"):
                    self._api("build_manifest_report")(path)

    def test_boundary_confidence_uses_the_recorder_vocabulary(self):
        path = self._mutated_manifest(
            lambda doc: doc["runs"][0]["occurrence"].__setitem__(
                "boundary_confidence", "certain"
            )
        )
        with self.assertRaisesRegex(ValueError, "invalid_boundary_confidence"):
            self._api("load_eval_manifest")(path)

    def test_unknown_boundary_has_no_recorder_end_or_duration(self):
        def unknown_with_duration(doc):
            doc["runs"][0]["occurrence"].update({
                "boundary_confidence": "unknown",
                "end_event": None,
                "duration_ms": 1,
            })

        path = self._mutated_manifest(unknown_with_duration)
        with self.assertRaisesRegex(ValueError, "invalid_occurrence_boundary"):
            self._api("load_eval_manifest")(path)

    def test_only_exact_boundaries_establish_a_comparison(self):
        cases = {
            "approximate": lambda occurrence: occurrence.__setitem__(
                "boundary_confidence", "approximate"
            ),
            "unknown": lambda occurrence: occurrence.update({
                "boundary_confidence": "unknown",
                "end_event": None,
                "duration_ms": None,
            }),
        }
        for confidence, mutate in cases.items():
            with self.subTest(confidence=confidence):
                path = self._mutated_manifest(
                    lambda doc: mutate(doc["runs"][0]["occurrence"])
                )
                try:
                    report = self._api("build_manifest_report")(path)
                except ValueError as exc:
                    self.fail("{} boundary was rejected: {}".format(confidence, exc))
                self.assertEqual(len(report["runs"]), 2)
                comparison = report["comparison"]
                self.assertEqual(comparison["status"], "unestablished")
                self.assertEqual(
                    comparison["diagnostic"], "inexact_occurrence_boundary"
                )
                self.assertEqual(
                    set(comparison["delta"].values()), {"unestablished"}
                )

    def test_duration_key_is_required_but_explicit_unavailable_is_accepted(self):
        missing = self._mutated_manifest(
            lambda doc: doc["runs"][0]["occurrence"].pop("duration_ms")
        )
        with self.assertRaisesRegex(ValueError, "missing_duration_ms"):
            self._api("load_eval_manifest")(missing)

        unavailable = self._mutated_manifest(
            lambda doc: doc["runs"][0]["occurrence"].__setitem__(
                "duration_ms", None
            )
        )
        loaded = self._api("load_eval_manifest")(unavailable)
        self.assertIsNone(loaded["runs"][0]["occurrence"]["duration_ms"])

    def test_any_unestablished_required_run_state_invalidates_the_comparison(self):
        def malformed(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")

        def partial(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"rounds": [{
                    "round": 2,
                    "kind": "discovery",
                    "kind_reason": "whole_draft_check",
                    "findings": [],
                }]}, fh)

        def incompatible(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"rounds": [{
                    "round": 1,
                    "kind": "unsupported-kind",
                    "findings": [],
                }]}, fh)

        def missing_reason(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["rounds"][0].pop("kind_reason")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)

        def extra_round(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["rounds"].append({
                "round": 2,
                "kind": "targeted",
                "kind_reason": "high_signal_finding",
                "findings": [{"id": 2, "status": "unresolved"}],
            })
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)

        def unreadable(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            self.addCleanup(os.chmod, path, 0o600)
            os.chmod(path, 0)

        for case, mutate in {
            "unreadable": unreadable,
            "malformed": malformed,
            "partial": partial,
            "incompatible": incompatible,
            "missing reason": missing_reason,
            "extra round": extra_round,
        }.items():
            with self.subTest(case=case):
                path, _root = self._mutate_copied_manifest(mutate)
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    report = self._api("build_manifest_report")(path)
                self.assertEqual(len(report["runs"]), 2)
                comparison = report["comparison"]
                self.assertEqual(comparison["status"], "unestablished")
                self.assertEqual(comparison["diagnostic"], "unestablished_run_state")
                self.assertEqual(
                    set(comparison["delta"].values()), {"unestablished"}
                )

    def test_deeply_nested_state_makes_all_semantics_and_comparison_unestablished(self):
        positive = self._api("build_manifest_report")(self.manifest_path)
        self.assertEqual(positive["comparison"]["status"], "established")
        self.assertEqual(
            positive["runs"][0]["audit_outcomes"]["status"], "established"
        )

        def deeply_nested_state(_doc, root):
            path = os.path.join(root, "runs", "baseline", "audit-state.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[" * 10000 + "0" + "]" * 10000)

        path, _root = self._mutate_copied_manifest(deeply_nested_state)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            report = self._api("build_manifest_report")(path)
        baseline = next(
            run for run in report["runs"] if run["configuration"] == "baseline"
        )
        outcomes = baseline["audit_outcomes"]
        self.assertEqual(outcomes["status"], "unestablished")

        def scalar_values(value):
            if isinstance(value, dict):
                for child in value.values():
                    yield from scalar_values(child)
            else:
                yield value

        semantic_axes = {
            key: value for key, value in outcomes.items()
            if key not in ("status", "diagnostic")
        }
        self.assertEqual(set(scalar_values(semantic_axes)), {"unestablished"})
        self.assertEqual(report["comparison"]["status"], "unestablished")
        self.assertEqual(
            report["comparison"]["diagnostic"], "unestablished_run_state"
        )
        self.assertEqual(
            set(report["comparison"]["delta"].values()), {"unestablished"}
        )

    def test_symlinked_artifact_escaping_declared_root_is_rejected(self):
        path, root = self._copied_manifest()
        outside = os.path.join(os.path.dirname(root), "outside.jsonl")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        link = os.path.join(root, "runs", "shared", "escaped.jsonl")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this host")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["runs"][0]["transcript"] = "runs/shared/escaped.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        with self.assertRaisesRegex(ValueError, "path_escape"):
            self._api("load_eval_manifest")(path)


class DraftCheckpointMetricsTest(unittest.TestCase):
    def _api(self, name):
        self.assertTrue(hasattr(CICE, name), "missing required API {}".format(name))
        return getattr(CICE, name)

    def test_measure_draft_counts_sections_items_and_duplicate_paragraphs(self):
        text = (
            "# Improve sync\r\n\r\n"
            "Intro paragraph.\r\n\r\n"
            "## Acceptance Criteria\r\n"
            "- Preserve cache.\r\n"
            "- Reject stale writes.\r\n\r\n"
            "## Testing Strategy\r\n"
            "1. Unit test cache.\r\n"
            "2. Integration test writes.\r\n\r\n"
            "Repeat me.\r\n\r\n"
            " Repeat   me. \r\n"
        )
        measured = self._api("measure_draft")(text)
        normalized = text.replace("\r\n", "\n")
        self.assertEqual(measured["word_count"], 23)
        self.assertEqual(measured["character_count"], len(normalized))
        self.assertEqual(measured["acceptance_criteria_count"], 2)
        self.assertEqual(measured["testing_strategy_count"], 2)
        self.assertEqual(
            measured["sections"]["acceptance criteria"]["item_count"], 2
        )
        self.assertEqual(measured["paragraph_count"], 6)
        self.assertEqual(measured["duplicate_paragraph_count"], 1)
        self.assertAlmostEqual(measured["duplicate_paragraph_density"], 1 / 6)

    def test_measure_draft_empty_duplicate_population_is_unestablished(self):
        measured = self._api("measure_draft")("\r\n\n")
        self.assertEqual(measured["word_count"], 0)
        self.assertEqual(measured["duplicate_paragraph_density"], "unestablished")

    def test_measure_checkpoints_reports_sequence_line_deltas_and_growth(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {}
            for name, body in {
                "initial": "one\ntwo\n",
                "revision": "one\nnew\ntwo changed\n",
                "final": "one\nnew\ntwo changed\nfinal\n",
            }.items():
                path = os.path.join(root, name + ".md")
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(body)
                paths[name] = path
            measured = self._api("measure_checkpoints")({
                "checkpoints": {
                    "initial": paths["initial"],
                    "revisions": [paths["revision"]],
                    "final": paths["final"],
                }
            })

        self.assertEqual(
            [(change["additions"], change["removals"])
             for change in measured["changes"]],
            [(2, 1), (1, 0)],
        )
        self.assertEqual(
            measured["initial_to_final"],
            {
                "word_growth": 3,
                "character_growth": 18,
                "additions": 3,
                "removals": 1,
            },
        )

    def test_final_byte_digest_uses_the_newest_recognizable_object_format(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "draft.md")
            data = b"draft bytes\n"
            with open(path, "wb") as fh:
                fh.write(data)
            state = {"rounds": [
                {"attempts": [{"digest": "a" * 40}]},
                {"attempts": [{"digest": "b" * 64}]},
            ]}
            measured, digest_failed = self._api("_current_draft_digest")(path, state)

        expected = hashlib.sha256(
            b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        ).hexdigest()
        self.assertEqual(measured, expected)
        self.assertFalse(digest_failed)

    def test_an_unreadable_final_draft_is_undigestible_not_no_digest_supplied(self):
        """The owner reports two different reasons; a bare None collapses them."""
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "absent.md")
            state = {"rounds": [{"attempts": [{"digest": "a" * 40}]}]}
            digest, digest_failed = self._api("_current_draft_digest")(missing, state)
        self.assertIsNone(digest)
        self.assertTrue(digest_failed)

    def test_a_state_recording_no_digest_format_is_not_a_read_failure(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "draft.md")
            with open(path, "wb") as fh:
                fh.write(b"draft bytes\n")
            digest, digest_failed = self._api("_current_draft_digest")(path, {})
        self.assertIsNone(digest)
        self.assertFalse(digest_failed)


class ValidatedAuditOutcomesTest(unittest.TestCase):
    @staticmethod
    def _attempt(digest):
        return {
            "arm": "file",
            "digest": digest,
            "body_digest": "body-" + digest,
            "sentinel_open": None,
            "sentinel_close": None,
            "instructions": None,
        }

    @classmethod
    def _round(cls, number, digest, **extra):
        result = {
            "round": number,
            "attempts": [cls._attempt(digest)],
            "steering": {"state": "established", "reason": "canonical-match"},
            "no_parseable_retry_used": False,
            "unreadable_retry_used": False,
            "outcome": "REVISE",
            "findings_count": 0,
            "consumer_dimensions_appended": False,
            "embed_markers": [],
            "degraded": False,
            "kind": "discovery",
            "kind_reason": "no-round-dispatched" if number == 1 else "empty-delta",
            "adjudicated_verdict": "REVISE",
            "unresolved_must_revise": "unestablished",
            "must_revise_count": None,
            "advisory_count": None,
            "invalid_count": None,
        }
        result.update(extra)
        return result

    @classmethod
    def _semantic_state(cls):
        first = cls._round(
            1,
            "D1",
            findings_count=2,
            unresolved_must_revise=2,
            must_revise_count=2,
            advisory_count=0,
            invalid_count=0,
            findings=[
                {
                    "id": 1,
                    "summary": "first defect",
                    "status": "resolved",
                    "ingested_status": "unresolved",
                    "quoted_draft_line": 10,
                    "resolution_ordinal": 1,
                },
                {
                    "id": 2,
                    "summary": "second defect",
                    "status": "invalidated",
                    "ingested_status": "unresolved",
                    "invalidation_provenance": 1,
                    "invalidation_reason": "duplicate report",
                },
            ],
        )
        second = cls._round(
            2,
            "D2",
            findings_count=4,
            unresolved_must_revise=1,
            must_revise_count=1,
            advisory_count=2,
            invalid_count=1,
            findings=[{
                "id": 1,
                "summary": "later defect",
                "status": "unresolved",
                "ingested_status": "unresolved",
                "quoted_draft_line": 20,
            }],
            advisory_records=[
                {
                    "id": 1,
                    "summary": "correctness advisory",
                    "rationale": "could change behavior",
                    "auditor_block": "ADVISORY: correctness advisory",
                    "impact_class": "implementation-correctness",
                    "evidence": "",
                },
                {
                    "id": 2,
                    "summary": "optional cleanup",
                    "rationale": "style only",
                    "auditor_block": "ADVISORY: optional cleanup",
                    "impact_class": "clearly-optional",
                    "evidence": "",
                },
            ],
            invalid_records=[{
                "id": 1,
                "summary": "invalid scope claim",
                "rationale": "outside the requested change",
                "auditor_block": "INVALID: invalid scope claim",
                "impact_class": "scope",
                "evidence": "checked scope",
            }],
            adjudication_render="reported",
        )
        return {
            "schema_version": 3,
            "slug": "quality-eval",
            "nonce": "nonce-1",
            "rounds": [first, second],
            "revisions": [{
                "ordinal": 1,
                "after_round": 1,
                "floor_round": 1,
                "stdin_digest": "D2",
            }],
            "overrides": [],
            "finding_evidence": {
                "1:1": {
                    "locator": "src/cache.py:10",
                    "command": "python3 -m unittest",
                    "observed": "failed before fix",
                    "baseline_revision": "abc123",
                    "completeness": "complete",
                },
                "1:2": {
                    "locator": "unestablished",
                    "command": "unestablished",
                    "observed": "unestablished",
                    "completeness": "incomplete",
                },
            },
        }

    @classmethod
    def _coverage_state(cls):
        clean = cls._round(
            1,
            "FINAL",
            outcome="FILE",
            findings_count=0,
            adjudicated_verdict="FILE",
            unresolved_must_revise=0,
            must_revise_count=0,
            advisory_count=0,
            invalid_count=0,
            coverage_render="full",
            coverage_expected=["correctness", "testing"],
            coverage=[
                {"key": "correctness", "outcome": "exercised", "anchor": "AC 1"},
                {"key": "testing", "outcome": "skipped", "anchor": None},
            ],
        )
        return {
            "schema_version": 3,
            "slug": "coverage-eval",
            "nonce": "nonce-2",
            "rounds": [clean],
            "revisions": [],
            "overrides": [],
            "finding_evidence": {},
        }

    def _api(self, name):
        self.assertTrue(hasattr(CICE, name), "missing required API {}".format(name))
        return getattr(CICE, name)

    def test_semantic_outcomes_use_validated_ledgers_and_evidence(self):
        outcomes = self._api("audit_outcomes")(self._semantic_state())
        self.assertEqual(outcomes["status"], "established")
        self.assertEqual(outcomes["first_round_unresolved"], 2)
        self.assertEqual(outcomes["settled_status_counts"], {
            "resolved": 1,
            "invalidated": 1,
            "superseded": 0,
        })
        self.assertEqual(outcomes["final_unresolved"], 1)
        self.assertEqual(outcomes["advisory_by_impact"], {
            "implementation-correctness": 1,
            "scope": 0,
            "safety": 0,
            "verifiability": 0,
            "clearly-optional": 1,
        })
        self.assertEqual(outcomes["invalid_by_impact"]["scope"], 1)
        self.assertEqual(outcomes["findings_without_usable_evidence"], 2)
        self.assertEqual(outcomes["findings_without_draft_line"], 1)
        self.assertEqual(outcomes["later_finding_identity"], {
            "novel": "unestablished",
            "recurring": "unestablished",
            "revision_induced": "unestablished",
        })

    def test_coverage_and_final_byte_results_come_from_owner_derivations(self):
        outcomes = self._api("audit_outcomes")(
            self._coverage_state(), current_digest="FINAL"
        )
        self.assertEqual(outcomes["coverage"], {
            "backing": "not-backed",
            "render": "full",
            "reason": None,
            "outcomes": {"correctness": "exercised", "testing": "skipped"},
        })
        self.assertEqual(outcomes["final_byte_coverage"], "covered")

    def test_full_validation_failure_makes_every_semantic_axis_unestablished(self):
        state = self._coverage_state()
        state["rounds"][0].pop("coverage_expected")
        outcomes = self._api("audit_outcomes")(state, current_digest="FINAL")
        self.assertEqual(outcomes["status"], "unestablished")
        self.assertIn("coverage_expected", outcomes["diagnostic"])
        self.assertEqual(outcomes["first_round_unresolved"], "unestablished")
        self.assertEqual(outcomes["final_unresolved"], "unestablished")
        self.assertEqual(outcomes["coverage"], "unestablished")
        self.assertEqual(outcomes["final_byte_coverage"], "unestablished")


class QualityRubricTest(unittest.TestCase):
    def setUp(self):
        path = os.path.join(_MANIFEST_FIX, "rubrics", "quality.json")
        with open(path, encoding="utf-8") as fh:
            self.rubric = json.load(fh)

    def _api(self, name):
        self.assertTrue(hasattr(CICE, name), "missing required API {}".format(name))
        return getattr(CICE, name)

    @staticmethod
    def _complete_issue(extra=""):
        return (
            "# Fix stale cache\n\n"
            "## Context\nA refresh can leave a stale cache entry.\n\n"
            "## Reproduction\n1. Refresh an item.\n2. Observe stale cache data.\n\n"
            "## Acceptance Criteria\n"
            "- Cache invalidation prevents stale cache reads.\n"
            "- The change has a safe rollback.\n\n"
            "## Testing Strategy\n- Reproduce the bug, then verify the fix.\n"
            + extra
        )

    def test_a_decorated_blocked_heading_is_recognized_as_the_blocked_section(self):
        """The shipped template writes `## 🚫 Blocked — resolve...`, not `## Blocked`.

        Matching the bare literal made both Blocked axes inert against every issue
        the create-issue skill actually produces.
        """
        decorated = self._complete_issue(
            "\n## \N{NO ENTRY SIGN} Blocked \N{EM DASH} resolve before implementation\n"
            "- Waiting on the cache owner.\n"
        )
        grade = self._api("grade_issue")(decorated, self.rubric)
        texts = {a["text"]: a["passed"] for a in grade["assertions"]}
        self.assertFalse(texts["Forbidden section absent: Blocked"])
        self.assertFalse(texts["Blocked section absent"])
        self.assertEqual(grade["forbidden_section_failures"], 1)
        # Positive control: the same rubric on an issue with no Blocked section
        # still passes both, so the matrix cannot pass by failing everything.
        clean = self._api("grade_issue")(self._complete_issue(), self.rubric)
        clean_texts = {a["text"]: a["passed"] for a in clean["assertions"]}
        self.assertTrue(clean_texts["Forbidden section absent: Blocked"])
        self.assertTrue(clean_texts["Blocked section absent"])

    def test_shorter_complete_issue_passes_with_viewer_compatible_assertions(self):
        grade = self._api("grade_issue")(self._complete_issue(), self.rubric)
        self.assertTrue(grade["passed"])
        self.assertEqual(grade["pass_rate"], 1.0)
        self.assertEqual(grade["forbidden_failures"], 0)
        self.assertTrue(grade["assertions"])
        for assertion in grade["assertions"]:
            self.assertEqual(set(assertion), {"text", "passed", "evidence"})

    def test_shorter_underspecified_and_new_invented_obligation_fail(self):
        grade = self._api("grade_issue")(
            "# Fix stale cache\n\n## Context\nA stale cache exists.\n",
            self.rubric,
        )
        self.assertFalse(grade["passed"])
        invented = self._api("grade_issue")(
            self._complete_issue("\nRequires a database migration.\n"),
            self.rubric,
        )
        self.assertFalse(invented["passed"])
        self.assertEqual(invented["forbidden_failures"], 1)

    def test_reproduction_facts_in_current_behavior_satisfy_the_contract(self):
        """The shipped template records the reproduction facts inside `Current Behavior`.

        It ships no reproduction-named heading, so a heading-name probe graded every
        template-conforming bug report as missing the contract.
        """
        conforming = (
            "# Fix stale cache\n\n"
            "## Current Behavior\n"
            "Refreshing an item leaves the previous value cached; readers observe "
            "stale cache data where the refreshed value is expected.\n\n"
            "## Acceptance Criteria\n"
            "- Cache invalidation prevents stale cache reads.\n"
            "- The change has a safe rollback.\n\n"
            "## Testing Strategy\n- Reproduce the bug, then verify the fix.\n"
        )
        grade = self._api("grade_issue")(conforming, self.rubric)
        texts = {a["text"]: a for a in grade["assertions"]}
        assertion = texts["Bug reproduction contract present"]
        self.assertTrue(assertion["passed"])
        self.assertIn("current behavior", assertion["evidence"])
        # Negative control: the same section without the declared evidence is absent,
        # so a bare `Current Behavior` heading cannot pass the axis on its own.
        featureish = conforming.replace(
            "Refreshing an item leaves the previous value cached; readers observe "
            "stale cache data where the refreshed value is expected.",
            "Exports are unavailable today.",
        )
        bare = self._api("grade_issue")(featureish, self.rubric)
        bare_texts = {a["text"]: a for a in bare["assertions"]}
        self.assertFalse(bare_texts["Bug reproduction contract present"]["passed"])
        self.assertEqual(
            bare_texts["Bug reproduction contract present"]["evidence"], "absent"
        )

    def test_a_rubric_expecting_the_contract_with_no_evidence_is_refused(self):
        rubric = dict(self.rubric, bug_reproduction_any_of=[])
        with self.assertRaises(ValueError) as caught:
            self._api("grade_issue")(self._complete_issue(), rubric)
        self.assertIn("bug_reproduction_any_of", str(caught.exception))
        missing = dict(self.rubric)
        missing.pop("bug_reproduction_any_of")
        with self.assertRaises(ValueError):
            self._api("grade_issue")(self._complete_issue(), missing)

    def test_word_count_never_changes_grade_or_quality_gate(self):
        baseline = self._api("grade_issue")(
            self._complete_issue("\n" + "Background detail. " * 30),
            self.rubric,
        )
        candidate = self._api("grade_issue")(self._complete_issue(), self.rubric)
        gate = self._api("quality_gate")(baseline, candidate)
        self.assertTrue(gate["passed"])
        self.assertTrue(gate["efficiency_eligible"])

        underspecified = self._api("grade_issue")(
            "# Fix\n\n" + "Background detail. " * 100,
            self.rubric,
        )
        failed_gate = self._api("quality_gate")(baseline, underspecified)
        self.assertFalse(failed_gate["passed"])
        self.assertFalse(failed_gate["efficiency_eligible"])

    def test_new_forbidden_failure_withholds_efficiency_credit(self):
        baseline = self._api("grade_issue")(self._complete_issue(), self.rubric)
        candidate = self._api("grade_issue")(
            self._complete_issue("\nRequires a schema migration.\n"), self.rubric
        )
        gate = self._api("quality_gate")(baseline, candidate)
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["new_forbidden_failures"], 1)
        self.assertFalse(gate["efficiency_eligible"])

    def test_new_forbidden_section_withholds_credit_even_at_a_flat_pass_rate(self):
        rubric = dict(self.rubric, forbidden_sections=["Appendix"])
        baseline = self._api("grade_issue")(
            "# Fix stale cache\n\n## Context\nA stale cache exists.\n", rubric
        )
        candidate = self._api("grade_issue")(
            self._complete_issue() + "\n## Appendix\nExtra.\n", rubric
        )
        gate = self._api("quality_gate")(baseline, candidate)
        self.assertEqual(gate["new_forbidden_sections"], 1)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["efficiency_eligible"])

    def test_a_malformed_grade_is_unestablished_and_never_credits_efficiency(self):
        good = self._api("grade_issue")(self._complete_issue(), self.rubric)
        malformed = [
            None,
            {},
            {k: v for k, v in good.items() if k != "pass_rate"},
            {k: v for k, v in good.items() if k != "forbidden_failures"},
            {k: v for k, v in good.items() if k != "forbidden_section_failures"},
            dict(good, pass_rate="1.0"),
            dict(good, forbidden_failures=True),
            dict(good, forbidden_section_failures=1.5),
        ]
        for grade in malformed:
            for baseline, candidate in ((grade, good), (good, grade)):
                with self.subTest(grade=grade, side="baseline" if baseline is grade else "candidate"):
                    gate = self._api("quality_gate")(baseline, candidate)
                    self.assertEqual(gate["status"], "unestablished")
                    self.assertFalse(gate["passed"])
                    self.assertFalse(gate["efficiency_eligible"])
                    self.assertEqual(gate["pass_rate_preserved"], "unestablished")
                    self.assertEqual(gate["new_forbidden_failures"], "unestablished")
                    self.assertEqual(gate["new_forbidden_sections"], "unestablished")


class LegacyMultiRunStateSafetyTest(unittest.TestCase):
    def _corpus(self, root, name, peak):
        os.makedirs(root, exist_ok=True)
        _write(root, name, [
            json.dumps({
                "type": "assistant",
                "attributionSkill": "devflow:create-issue",
                "message": {
                    "usage": {"input_tokens": peak},
                    "content": [{
                        "type": "tool_use",
                        "id": "dispatch-{}".format(name),
                        "name": "Bash",
                        "input": {
                            "command": "issue-audit-state.py record-dispatch --round 1"
                        },
                    }],
                },
            }),
            json.dumps({
                "type": "assistant",
                "isSidechain": True,
                "attributionSkill": "devflow:create-issue",
                "message": {"usage": {"input_tokens": 1}},
            }),
        ])

    def test_one_state_file_is_not_reused_across_multiple_legacy_runs(self):
        with tempfile.TemporaryDirectory() as root:
            before = os.path.join(root, "before")
            after = os.path.join(root, "after")
            for corpus, peaks in ((before, (10, 20)), (after, (30, 40))):
                for index, peak in enumerate(peaks, 1):
                    self._corpus(corpus, "run-{}.jsonl".format(index), peak)
            state = os.path.join(root, "state.json")
            with open(state, "w", encoding="utf-8") as fh:
                json.dump({"rounds": [{
                    "round": 1,
                    "kind": "targeted",
                    "kind_reason": "high_signal_finding",
                    "findings": [{"id": 1}],
                }]}, fh)

            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                report = CICE.build_paired_report(
                    before, after, state, state, large_block_chars=500
                )

        self.assertEqual(
            [run["peak_context"] for run in report["before"]["runs"]], [10, 20]
        )
        for side in ("before", "after"):
            self.assertFalse(report[side]["summary"]["state_established"])
            for run in report[side]["runs"]:
                self.assertEqual(run["round_kinds"], {1: "unestablished"})
        self.assertEqual(report["delta"]["finding_count"], "unestablished")
        self.assertIn("unsafe_multi_run_state_join", err.getvalue())


class LegacyCliCompatibilityTest(unittest.TestCase):
    def test_raw_directory_json_keeps_the_legacy_top_level_shape(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CICE.main([
                os.path.join(_FIX, "after"),
                "--format",
                "json",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(set(json.loads(out.getvalue())), {"runs", "summary", "skipped"})
        self.assertEqual(err.getvalue(), "")

    def test_paired_json_keeps_the_exact_legacy_shape(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CICE.main([
                "--before", MainCliTest._BEFORE,
                "--after", MainCliTest._AFTER,
                "--before-state", MainCliTest._BSTATE,
                "--after-state", MainCliTest._ASTATE,
                "--format", "json",
            ])
        self.assertEqual(rc, 0)
        document = json.loads(out.getvalue())
        self.assertEqual(set(document), {"before", "after", "delta"})
        for side in ("before", "after"):
            self.assertEqual(set(document[side]), {
                "runs", "summary", "skipped", "state_established", "finding_count",
            })
        self.assertEqual(set(document["delta"]), {
            "total_attributed_auditor_cost",
            "total_peak_context",
            "mean_peak_context_per_run",
            "median_main_thread_context",
            "total_round_count",
            "finding_count",
        })
        self.assertEqual(err.getvalue(), "")


class UnmeasuredTurnContractTest(_SingleSessionMixin, unittest.TestCase):
    """Issue #1899: the residency axis reports an unmeasured turn as unestablished, never
    a real-looking 0, and a non-finite token count never raises OverflowError. The SPEND
    axis (_auditor_cost, total_output_tokens) is unchanged for well-formed usage (AC6).
    """

    def test_context_tokens_is_none_for_every_unmeasured_shape(self):
        inf = json.loads('{"input_tokens": Infinity}')
        nan = json.loads('{"input_tokens": NaN}')
        for usage in (None, "not-a-dict", {}, {"input_tokens": None}, inf, nan):
            self.assertIsNone(CICE._context_tokens(usage), repr(usage))

    def test_established_subfield_still_sums(self):
        self.assertEqual(
            CICE._context_tokens({"input_tokens": None, "cache_read_input_tokens": 7}), 7)
        self.assertEqual(CICE._context_tokens({"input_tokens": 10}), 10)

    def test_median_empty_population_raises(self):
        # AC4: matches both siblings — an empty population refuses rather than returning 0.
        with self.assertRaises(ValueError):
            CICE._median([])
        self.assertEqual(CICE._median_or_unestablished([]), CICE.UNESTABLISHED)

    def test_all_unmeasured_corpus_reports_unestablished_peak_and_final(self):
        # AC3: a run whose every attributed turn is unmeasured reports peak AND final as
        # the sentinel (never 0), and the missing turns are tallied (AC2).
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue","message":{}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":null}}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["peak_context"], CICE.UNESTABLISHED)
        self.assertEqual(runs[0]["final_context"], CICE.UNESTABLISHED)
        self.assertEqual(runs[0]["usage_missing_turns"], 2)

    def test_partial_unmeasured_keeps_measured_peak(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue","message":{}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":42}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 42)
        self.assertEqual(runs[0]["final_context"], 42)
        self.assertEqual(runs[0]["usage_missing_turns"], 1)

    def test_corpus_wide_total_usage_missing_turns(self):
        # AC2: the corpus-wide total is on the aggregate summary.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.jsonl", [
                '{"type":"assistant","attributionSkill":"devflow:create-issue","message":{}}'])
            _write(d, "b.jsonl", [
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":5}}}',
                '{"type":"assistant","attributionSkill":"devflow:create-issue","message":{}}'])
            report = CICE.build_report(d)
        summary = report["summary"]
        self.assertEqual(summary["total_usage_missing_turns"], 2)
        self.assertEqual(summary["run_count"], 2)
        # Cardinality-sensitive: run "a" (all-unmeasured, peak UNESTABLISHED) is excluded
        # from the corpus peak population — only run "b"'s measured 5 remains, never a 0.
        self.assertEqual(summary["median_peak_context"], 5)
        self.assertEqual(summary["max_peak_context"], 5)

    def test_over_threshold_buckets_exclude_unmeasured_residency_runs(self):
        # The `runs_over_*` bucket COUNTS are derived from the same filtered `peaks`
        # population: an all-unmeasured run must not be counted as an under-threshold
        # run, and a corpus with no measured peak reports UNESTABLISHED, never 0.
        unmeasured = {"peak_context": CICE.UNESTABLISHED, "usage_missing_turns": 3}
        measured = {"peak_context": CICE.BUCKET_200K + 1, "usage_missing_turns": 0}

        def _run(fields):
            base = {"repeated_read_count": 0, "reemission_count": 0,
                    "attributed_auditor_cost": 0, "unrounded_auditor_cost": 0,
                    "sidechain_records_seen": 0, "sidechain_records_attributed": 0,
                    "record_reopen_count": 0, "round_auditor_cost": {},
                    "dispatch_rounds": {}}
            base.update(fields)
            return base

        both = CICE.aggregate([_run(unmeasured), _run(measured)])
        self.assertEqual(both["runs_over_200k"], 1)
        self.assertEqual(both["runs_over_400k"], 0)
        self.assertEqual(both["total_usage_missing_turns"], 3)

        none_measured = CICE.aggregate([_run(unmeasured)])
        self.assertEqual(none_measured["runs_over_200k"], CICE.UNESTABLISHED)
        self.assertEqual(none_measured["runs_over_400k"], CICE.UNESTABLISHED)
        self.assertEqual(none_measured["max_peak_context"], CICE.UNESTABLISHED)

    def test_empty_corpus_total_usage_missing_is_unestablished(self):
        summary = CICE.aggregate([])
        self.assertEqual(summary["total_usage_missing_turns"], CICE.UNESTABLISHED)

    def test_infinity_token_count_is_unmeasured_not_a_crash(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":Infinity}}}',
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":70}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 70)
        self.assertEqual(runs[0]["usage_missing_turns"], 1)

    def test_infinity_corpus_exits_zero_and_prints_a_report(self):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                '{"type":"assistant","attributionSkill":"devflow:create-issue",'
                '"message":{"usage":{"input_tokens":Infinity}}}'])
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = CICE.main([d])
        self.assertEqual(rc, 0)
        self.assertIn("context eval", out.getvalue())

    def test_spend_axis_returns_summable_zero_for_unmeasured_usage(self):
        # The spend axis (_residency_spend / _auditor_cost) must never return None or raise
        # on an unmeasured usage object, so the auditor-cost arithmetic stays whole while the
        # residency axis reports unestablished (issue #1899's file-scoped entanglement).
        for usage in (None, "not-a-dict", {}, {"input_tokens": None},
                      json.loads('{"input_tokens": Infinity}'),
                      json.loads('{"input_tokens": NaN}')):
            self.assertEqual(CICE._residency_spend(usage), 0, repr(usage))
            self.assertEqual(CICE._auditor_cost(usage), 0, repr(usage))

    def test_infinity_on_sidechain_record_does_not_detonate(self):
        # A non-finite count on an auditor (isSidechain) record flows through the SPEND axis
        # (_auditor_cost). Pre-fix that raised OverflowError — not in eval_corpus's per-record
        # backstop tuple — and aborted the whole corpus walk (issue #1899).
        runs, skipped = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":5}}}',
            '{"type":"assistant","isSidechain":true,'
            '"attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":Infinity,"output_tokens":3}}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(skipped["malformed_record"], 0)

    def test_auditor_cost_and_output_total_unchanged_for_well_formed_usage(self):
        # AC6: the SPEND axis is untouched by the residency-axis fix. Auditor cost sums the
        # three residency sub-fields plus output; total_output_tokens sums output only.
        usage = {"input_tokens": 100, "cache_read_input_tokens": 20,
                 "cache_creation_input_tokens": 5, "output_tokens": 8}
        self.assertEqual(CICE._auditor_cost(usage), 133)  # 100+20+5 + 8
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:create-issue",'
            '"message":{"usage":{"input_tokens":100,"cache_read_input_tokens":20,'
            '"cache_creation_input_tokens":5,"output_tokens":8}}}',
        ])
        self.assertEqual(runs[0]["total_output_tokens"], 8)
        self.assertEqual(runs[0]["peak_context"], 125)  # residency excludes output


if __name__ == "__main__":
    unittest.main(verbosity=2)

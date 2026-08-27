#!/usr/bin/env python3
"""Focused tests for scripts/implement-benchmark.py, the cohort comparison."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(modname: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


bm = _load("implement_benchmark", SCRIPTS / "implement-benchmark.py")
ir = _load("implement_records_bm", SCRIPTS / "implement_records.py")

UNESTABLISHED = "unestablished"
FP_A = "a" * 64
FP_B = "b" * 64


def _record(pr, duration_ms, cost_usd, fingerprint, verdict="APPROVE"):
    return json.dumps({
        "schema_version": 1, "pr": pr, "issue": pr + 1000, "branch": f"b{pr}",
        "merged_at": f"2026-07-{(pr % 28) + 1:02d}T00:00:00Z", "verdict": verdict,
        "config_fingerprint": {"partial": False, "salient": {}, "sha256": fingerprint},
        "efficiency_runs": [{
            "slug": f"pr-{pr}", "run_id": f"{pr}0000-1",
            "harness_cost": {"command": "implement", "duration_ms": duration_ms,
                             "cost_usd": cost_usd, "num_turns": 10},
        }],
    })


def _store(*lines):
    td = tempfile.TemporaryDirectory()
    p = Path(td.name) / "experiment-records.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return td, p


def _cohort(fingerprint, n, duration_ms, cost_usd, verdict="APPROVE", start=1):
    return [_record(start + i, duration_ms, cost_usd, fingerprint, verdict)
            for i in range(n)]


class CohortSelection(unittest.TestCase):
    def test_runs_are_selected_by_fingerprint_value(self):
        td, p = _store(*(_cohort(FP_A, 2, 1000, 1.0) + _cohort(FP_B, 3, 2000, 2.0, start=50)))
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(len(bm.select_cohort(runs, FP_A)), 2)
        self.assertEqual(len(bm.select_cohort(runs, FP_B)), 3)

    def test_a_prefix_selects_the_same_cohort(self):
        td, p = _store(*_cohort(FP_A, 2, 1000, 1.0))
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(len(bm.select_cohort(runs, FP_A[:8])), 2)

    def test_an_ambiguous_prefix_is_refused_rather_than_merging_two_cohorts(self):
        td, p = _store(*(_cohort("ab" + "1" * 62, 2, 1000, 1.0)
                         + _cohort("ac" + "2" * 62, 2, 2000, 2.0, start=50)))
        with td:
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = bm.main(["--cohort-a", "a", "--cohort-b", "a", "--records", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("distinct fingerprints", err.getvalue())

    def test_a_run_with_no_fingerprint_joins_no_cohort(self):
        line = json.loads(_record(1, 1000, 1.0, FP_A))
        line["config_fingerprint"] = None
        td, p = _store(json.dumps(line))
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(bm.select_cohort(runs, FP_A), [])


class Statistics(unittest.TestCase):
    def test_each_named_statistic_is_reported_per_cohort(self):
        td, p = _store(*_cohort(FP_A, 5, 1000, 1.0))
        with td:
            stats = bm.describe(bm.select_cohort(ir.load_runs(p), FP_A))
        for key in ("count", "duration_mean_ms", "duration_median_ms", "duration_stdev_ms",
                    "cost_mean_usd", "cost_median_usd", "cost_stdev_usd"):
            self.assertIn(key, stats)
        self.assertEqual(stats["count"], 5)

    def test_stdev_of_a_single_run_cohort_is_unestablished_not_zero(self):
        td, p = _store(*_cohort(FP_A, 1, 1000, 1.0))
        with td:
            stats = bm.describe(bm.select_cohort(ir.load_runs(p), FP_A))
        self.assertEqual(stats["duration_stdev_ms"], UNESTABLISHED)


class VerdictWithholding(unittest.TestCase):
    def test_a_small_cohort_alone_withholds(self):
        stats_small = {"count": 4, "established_durations": 4, "reject_runs": []}
        stats_ok = {"count": 9, "established_durations": 9, "reject_runs": []}
        reasons = bm.withholding_reasons("A", stats_small, "B", stats_ok)
        self.assertEqual(len(reasons), 1)
        self.assertIn("fewer than the 5", reasons[0])

    def test_a_reject_run_alone_withholds(self):
        stats_ok = {"count": 9, "established_durations": 9, "reject_runs": []}
        stats_reject = {"count": 9, "established_durations": 9, "reject_runs": ["r1"]}
        reasons = bm.withholding_reasons("A", stats_ok, "B", stats_reject)
        self.assertEqual(len(reasons), 1)
        self.assertIn("REJECT", reasons[0])

    def test_both_conditions_print_both_reasons(self):
        reasons = bm.withholding_reasons(
            "A", {"count": 2, "established_durations": 2, "reject_runs": []},
            "B", {"count": 9, "established_durations": 9, "reject_runs": ["r1", "r2"]})
        self.assertEqual(len(reasons), 2)

    def test_two_clean_cohorts_report_a_verdict(self):
        self.assertEqual(
            bm.withholding_reasons("A", {"count": 5, "established_durations": 5, "reject_runs": []},
                                   "B", {"count": 6, "established_durations": 6, "reject_runs": []}), [])

    def test_the_minimum_is_a_named_constant(self):
        self.assertEqual(bm.MIN_COHORT_RUNS, 5)

    def test_reject_detection_is_case_insensitive_and_matches_a_qualified_verdict(self):
        self.assertTrue(ir.is_reject("REJECT"))
        self.assertTrue(ir.is_reject("reject with notes"))
        self.assertFalse(ir.is_reject("APPROVE with notes"))
        self.assertFalse(ir.is_reject(None))


class ReviewFindingsRound1(unittest.TestCase):
    def test_an_empty_prefix_selects_no_cohort(self):
        """An empty operand prefix-matches every run, so it would select the whole store
        as BOTH cohorts and compare it against itself."""
        td, p = _store(*_cohort(FP_A, 3, 1000, 1.0))
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(bm.select_cohort(runs, ""), [])

    def test_the_verdict_is_withheld_on_too_few_ESTABLISHED_durations(self):
        """The statistics are computed over the established durations, so gating on the
        raw cohort size lets a five-run cohort with four unmeasured durations print a
        verdict from a one-sample mean."""
        reasons = bm.withholding_reasons(
            "A", {"count": 5, "established_durations": 1, "reject_runs": []},
            "B", {"count": 6, "established_durations": 6, "reject_runs": []})
        self.assertEqual(len(reasons), 1)
        self.assertIn("established duration", reasons[0])

    def test_a_cohort_measured_throughout_is_not_withheld(self):
        self.assertEqual(
            bm.withholding_reasons("A", {"count": 5, "established_durations": 5, "reject_runs": []},
                                   "B", {"count": 5, "established_durations": 5, "reject_runs": []}),
            [])


class EndToEnd(unittest.TestCase):
    def test_a_clean_comparison_prints_the_direction_and_magnitude(self):
        td, p = _store(*(_cohort(FP_A, 5, 2000, 2.0) + _cohort(FP_B, 5, 1000, 1.0, start=50)))
        with td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = bm.main(["--cohort-a", FP_A, "--cohort-b", FP_B, "--records", str(p)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("50.0 percent faster", out)

    def test_a_reject_tainted_cohort_withholds_even_when_it_looks_faster(self):
        td, p = _store(*(_cohort(FP_A, 5, 2000, 2.0)
                         + _cohort(FP_B, 5, 1000, 1.0, verdict="REJECT", start=50)))
        with td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                bm.main(["--cohort-a", FP_A, "--cohort-b", FP_B, "--records", str(p)])
        out = buf.getvalue()
        self.assertIn("WITHHELD", out)
        self.assertNotIn("faster", out)


class PostGateVerdictArms(unittest.TestCase):
    """The two arms AFTER the withholding gate: a cohort passes every gate (enough
    established durations, no REJECT) and the percentage is still undefined."""

    def test_a_zero_baseline_mean_withholds_and_names_the_baseline(self):
        """duration_ms 0 is an ESTABLISHED figure, so cohort A clears the count gate and
        reaches `mean_a <= 0` — where dividing by it would raise."""
        td, p = _store(*(_cohort(FP_A, bm.MIN_COHORT_RUNS, 0, 1.0)
                         + _cohort(FP_B, bm.MIN_COHORT_RUNS, 2000, 2.0, start=50)))
        with td:
            runs = ir.load_runs(p)
        stats_a = bm.describe(bm.select_cohort(runs, FP_A))
        # Positive control: the fixture is otherwise valid — it is not withheld by the gate.
        self.assertEqual(stats_a["established_durations"], bm.MIN_COHORT_RUNS)
        self.assertEqual(bm.withholding_reasons(
            "A", stats_a, "B", bm.describe(bm.select_cohort(runs, FP_B))), [])
        out = bm.render(FP_A, bm.select_cohort(runs, FP_A),
                        FP_B, bm.select_cohort(runs, FP_B))
        self.assertIn("Efficiency verdict WITHHELD:", out)
        self.assertIn("cohort A's mean duration is 0 ms", out)
        self.assertNotIn("Efficiency verdict: cohort B is", out)

    def test_the_zero_baseline_reason_is_not_the_unestablished_reason(self):
        """A zero mean WAS established; naming it unestablished would misdirect the reader."""
        td, p = _store(*(_cohort(FP_A, bm.MIN_COHORT_RUNS, 0, 1.0)
                         + _cohort(FP_B, bm.MIN_COHORT_RUNS, 2000, 2.0, start=50)))
        with td:
            runs = ir.load_runs(p)
        out = bm.render(FP_A, bm.select_cohort(runs, FP_A),
                        FP_B, bm.select_cohort(runs, FP_B))
        self.assertNotIn("could not be established", out)


if __name__ == "__main__":
    unittest.main()

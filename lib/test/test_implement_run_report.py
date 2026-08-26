#!/usr/bin/env python3
"""Focused tests for scripts/implement-run-report.py and its shared record reader."""

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
from contextlib import redirect_stdout
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


rr = _load("implement_run_report", SCRIPTS / "implement-run-report.py")
ir = _load("implement_records_mod", SCRIPTS / "implement_records.py")

UNESTABLISHED = "unestablished"


def _record(pr, merged_at, duration_ms, cost_usd, verdict="APPROVE",
            fingerprint="a" * 64, run_profile=None, command="implement", run_id=None):
    entry = {
        "slug": f"pr-{pr}",
        "run_id": run_id or f"{pr}0000-1",
        "harness_cost": {"command": command, "duration_ms": duration_ms,
                         "cost_usd": cost_usd, "num_turns": 10},
    }
    if run_profile is not None:
        entry["run_profile"] = run_profile
    return json.dumps({
        "schema_version": 1, "pr": pr, "issue": pr + 1000, "branch": f"b{pr}",
        "merged_at": merged_at, "verdict": verdict,
        "config_fingerprint": {"partial": False, "salient": {}, "sha256": fingerprint},
        "efficiency_runs": [entry],
    })


def _store(*lines):
    td = tempfile.TemporaryDirectory()
    p = Path(td.name) / "experiment-records.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return td, p


class Reader(unittest.TestCase):
    def test_only_implement_runs_are_selected(self):
        td, p = _store(
            _record(1, "2026-07-01T00:00:00Z", 1000, 1.0),
            _record(2, "2026-07-02T00:00:00Z", 2000, 2.0, command="review"),
        )
        with td:
            runs = ir.load_runs(p)
        self.assertEqual([r["pr"] for r in runs], [1])

    def test_a_pre_change_record_carries_run_profile_fields_as_none(self):
        td, p = _store(_record(1, "2026-07-01T00:00:00Z", 1000, 1.0))
        with td:
            run = ir.load_runs(p)[0]
        self.assertIsNone(run["terminal_status"])
        self.assertIsNone(run["phase_durations_ms"])

    def test_a_post_change_record_carries_them_through(self):
        profile = {"final_status": "Complete",
                   "phase_durations_ms": {"Setup": 1000, "Implement": 3000},
                   "prior_record_count": 2, "engine_outcome": "success"}
        td, p = _store(_record(1, "2026-07-01T00:00:00Z", 1000, 1.0, run_profile=profile))
        with td:
            run = ir.load_runs(p)[0]
        self.assertEqual(run["terminal_status"], "Complete")
        self.assertEqual(run["prior_record_count"], 2)

    def test_a_missing_store_yields_no_runs_rather_than_raising(self):
        self.assertEqual(ir.load_runs("/nonexistent/store.jsonl"), [])

    def test_an_unparseable_line_is_skipped_and_the_rest_survive(self):
        td, p = _store("{not json", _record(1, "2026-07-01T00:00:00Z", 1000, 1.0))
        with td:
            self.assertEqual(len(ir.load_runs(p)), 1)

    def test_unestablished_operands_are_excluded_from_every_aggregate(self):
        values = [10, UNESTABLISHED, None, 20, True, float("nan")]
        self.assertEqual(ir.numeric(values), [10, 20])
        self.assertEqual(ir.mean_or_unestablished(values), 15)

    def test_an_empty_population_is_unestablished_not_zero(self):
        for fn in (ir.mean_or_unestablished, ir.median_or_unestablished,
                   ir.stdev_or_unestablished):
            self.assertEqual(fn([UNESTABLISHED, None]), UNESTABLISHED)

    def test_a_single_observation_has_no_established_stdev(self):
        self.assertEqual(ir.stdev_or_unestablished([5]), UNESTABLISHED)

    def test_phase_shares_are_fractions_of_established_phase_time_only(self):
        run = {"phase_durations_ms": {"Setup": 1000, "Implement": 3000,
                                      "Review": UNESTABLISHED}}
        shares = ir.phase_shares(run)
        self.assertAlmostEqual(shares["Setup"], 0.25)
        self.assertAlmostEqual(shares["Implement"], 0.75)
        self.assertNotIn("Review", shares)


class PerRunMode(unittest.TestCase):
    def test_n_is_required_without_retro(self):
        with self.assertRaises(SystemExit):
            rr.main([])

    def test_n_must_be_positive(self):
        with self.assertRaises(SystemExit):
            rr.main(["0"])

    def test_rows_hold_every_criterion_named_field(self):
        profile = {"final_status": "Complete",
                   "phase_durations_ms": {"Setup": 1000, "Implement": 3000}}
        td, p = _store(
            _record(1, "2026-07-01T00:00:00Z", 1000, 1.0, run_profile=profile),
            _record(2, "2026-07-02T00:00:00Z", 3000, 3.0, verdict="REJECT"),
        )
        with td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rr.main(["2", "--records", str(p)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Complete", out)        # terminal status
        self.assertIn("REJECT", out)          # review verdict
        self.assertIn("1.00", out)            # dollar cost
        self.assertIn("Implement=75%", out)   # per-phase share
        self.assertIn("mean duration", out)   # aggregate block
        self.assertIn("median cost", out)

    def test_n_larger_than_the_store_renders_what_exists(self):
        td, p = _store(_record(1, "2026-07-01T00:00:00Z", 1000, 1.0))
        with td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rr.main(["50", "--records", str(p)])
        self.assertIn("Most recent 1 implement run(s)", buf.getvalue())


class RetroMode(unittest.TestCase):
    def test_the_threshold_is_a_named_constant(self):
        self.assertEqual(rr.REGRESSION_THRESHOLD_PCT, 25)
        self.assertEqual(rr.TRAILING_WEEKS, 4)

    def test_an_empty_store_prints_the_placeholder_not_an_empty_section(self):
        out = rr.render_retro([])
        self.assertIn("## Implement runtime trends", out)
        self.assertIn("no implement run records yet", out)

    def test_a_week_over_the_threshold_is_reported_as_a_regression(self):
        lines = []
        # Four calm weeks at 1000ms, then one at 2000ms — a 100 percent jump.
        for week, day in enumerate(("06", "13", "20", "27"), start=1):
            lines.append(_record(week, f"2026-07-{day}T00:00:00Z", 1000, 1.0))
        lines.append(_record(9, "2026-08-03T00:00:00Z", 2000, 1.0))
        td, p = _store(*lines)
        with td:
            runs = ir.load_runs(p)
        found = rr.regressions(rr.weekly_means(runs))
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["delta_pct"], 100.0)

    def test_a_week_under_the_threshold_is_not_reported(self):
        lines = [_record(w, f"2026-07-{d}T00:00:00Z", 1000, 1.0)
                 for w, d in enumerate(("06", "13", "20", "27"), start=1)]
        lines.append(_record(9, "2026-08-03T00:00:00Z", 1200, 1.0))  # +20 percent
        td, p = _store(*lines)
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(rr.regressions(rr.weekly_means(runs)), [])

    def test_a_week_without_a_full_preceding_window_yields_no_line(self):
        """With fewer than four preceding weeks there is no comparand, so a regression
        line would assert an excess over a mean that does not exist."""
        lines = [_record(1, "2026-07-06T00:00:00Z", 1000, 1.0),
                 _record(2, "2026-07-13T00:00:00Z", 99999, 1.0)]
        td, p = _store(*lines)
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(rr.regressions(rr.weekly_means(runs)), [])

    def test_a_malformed_merged_at_is_dropped_from_the_weekly_buckets(self):
        td, p = _store(_record(1, "not-a-date", 1000, 1.0))
        with td:
            runs = ir.load_runs(p)
        self.assertEqual(rr.weekly_means(runs), {})


if __name__ == "__main__":
    unittest.main()

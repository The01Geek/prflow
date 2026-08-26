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

    def test_runs_are_ordered_by_merge_time_with_the_run_id_as_tie_break(self):
        """Cardinality-sensitive: the report takes the most recent N off the tail, so a
        wrong or absent comparator silently reports the wrong runs. Three records fed in
        reverse order, two sharing a merge timestamp so the tie-break is exercised too."""
        td, p = _store(
            _record(3, "2026-07-09T00:00:00Z", 3000, 3.0, run_id="c-1"),
            _record(1, "2026-07-01T00:00:00Z", 1000, 1.0, run_id="b-1"),
            _record(2, "2026-07-01T00:00:00Z", 2000, 2.0, run_id="a-1"),
        )
        with td:
            runs = ir.load_runs(p)
        self.assertEqual([r["run_id"] for r in runs], ["a-1", "b-1", "c-1"])

    def test_median_over_an_even_and_an_odd_population(self):
        """A one-element population is already its own median, so the even-count
        averaging is exercised here instead."""
        self.assertEqual(ir.median_or_unestablished([1, 3, 5]), 3)
        self.assertEqual(ir.median_or_unestablished([1, 3, 5, 7]), 4)
        self.assertEqual(ir.median_or_unestablished([5, 1, 7, 3]), 4)  # order-independent

    def test_stdev_over_a_multi_element_population(self):
        self.assertAlmostEqual(ir.stdev_or_unestablished([2, 4, 4, 4, 5, 5, 7, 9]), 2.0)

    def test_top_phases_ranks_by_share_and_caps_the_list(self):
        run = {"phase_durations_ms": {"A": 1000, "B": 4000, "C": 3000, "D": 2000}}
        rendered = rr._top_phases(run, limit=3)
        self.assertTrue(rendered.startswith("B="), rendered)
        self.assertIn("C=", rendered)
        self.assertNotIn("A=", rendered)

    def test_phase_shares_are_fractions_of_established_phase_time_only(self):
        run = {"phase_durations_ms": {"Setup": 1000, "Implement": 3000,
                                      "Review": UNESTABLISHED}}
        shares = ir.phase_shares(run)
        self.assertAlmostEqual(shares["Setup"], 0.25)
        self.assertAlmostEqual(shares["Implement"], 0.75)
        self.assertNotIn("Review", shares)


class ReviewFindingsRound1(unittest.TestCase):
    """Findings from the PR #2017 review pass."""

    def test_a_present_but_empty_store_reports_read(self):
        td, p = _store("")
        with td:
            runs, status = ir.load_runs_with_status(p)
        self.assertEqual(runs, [])
        self.assertEqual(status, "read")

    def test_corrupt_lines_are_counted_not_silently_dropped(self):
        td, p = _store("{not json", _record(1, "2026-07-01T00:00:00Z", 1000, 1.0), "[1,2]")
        with td:
            runs, status = ir.load_runs_with_status(p)
        self.assertEqual(len(runs), 1)
        self.assertEqual(status, "read:2-unparseable")

    def test_the_default_store_is_anchored_to_the_repo_root_not_the_cwd(self):
        """Every other .prflow reader anchors on the git root; a cwd-relative default makes
        the tools report an empty store from any subdirectory. Resolve it from a
        SUBDIRECTORY — from the repo root the two candidates coincide, so only a
        subdirectory discriminates them."""
        import os
        sub = ROOT / "lib" / "test"
        cwd = os.getcwd()
        os.chdir(sub)
        try:
            resolved = ir.default_store()
        finally:
            os.chdir(cwd)
        self.assertEqual(resolved, ROOT / ".prflow/learnings/experiment-records.jsonl")
        self.assertNotEqual(resolved, sub / ".prflow/learnings/experiment-records.jsonl")

    def test_an_absent_store_is_not_reported_as_unreadable(self):
        """A store that does not exist yet is the normal state of a repository that has
        persisted no run; reporting it as a failure makes every fresh install look broken."""
        runs, status = ir.load_runs_with_status("/nonexistent/definitely/not/here.jsonl")
        self.assertEqual(runs, [])
        self.assertEqual(status, "absent")
        self.assertEqual(rr.main(["--retro", "--records", "/nonexistent/x.jsonl"]), 0)

    def test_an_existing_but_unreadable_store_IS_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "experiment-records.jsonl"
            p.write_text("{}", encoding="utf-8")
            p.chmod(0o000)
            try:
                _runs, status = ir.load_runs_with_status(p)
            finally:
                p.chmod(0o644)
        self.assertEqual(status, "unreadable")

    def test_phase_shares_marks_a_run_whose_phases_are_partly_unestablished(self):
        """Dividing by the established sum alone inflates the rest to 100% with nothing
        saying the run was only partly measured."""
        run = {"phase_durations_ms": {"Setup": 1000, "Implement": 3000,
                                      "Review": UNESTABLISHED}}
        shares, complete = ir.phase_shares_with_completeness(run)
        self.assertAlmostEqual(shares["Setup"], 0.25)
        self.assertFalse(complete)
        whole = {"phase_durations_ms": {"Setup": 1000, "Implement": 3000}}
        _shares, complete2 = ir.phase_shares_with_completeness(whole)
        self.assertTrue(complete2)

    def test_a_partial_phase_share_is_rendered_as_partial(self):
        run = {"phase_durations_ms": {"Setup": 1000, "Review": UNESTABLISHED}}
        self.assertIn("partial", rr._top_phases(run))

    def test_phase_labels_are_not_run_through_a_path_helper(self):
        """Workpad phase headings are names, never paths. Only a heading containing a
        separator discriminates — `Path("PR marked ready").name` returns it unchanged, so a
        separator-free heading passes with or without the path helper."""
        run = {"phase_durations_ms": {"Review/fix loop": 3000, "Setup": 1000}}
        rendered = rr._top_phases(run)
        self.assertIn("Review/fix loop=", rendered)
        self.assertNotIn("fix loop=75%", rendered.replace("Review/fix loop=", ""))

    def test_the_status_column_holds_its_widest_sentinel_without_shifting_the_next_column(self):
        """A column narrower than the sentinel it most often holds pushes every later
        column right on the rows that carry it. Compare the VERDICT column's start
        offset on a row whose status is the sentinel against one whose status is short —
        reading the offsets is what a length assertion on the sentinel never did."""
        profile = {"final_status": "Complete", "phase_durations_ms": {"Setup": 1000}}
        td, p = _store(
            _record(1, "2026-07-01T00:00:00Z", 1000, 1.0, run_profile=profile),
            _record(2, "2026-07-02T00:00:00Z", 2000, 2.0),
        )
        with td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rr.main(["2", "--records", str(p)])
        rows = [ln for ln in buf.getvalue().splitlines() if "APPROVE" in ln]
        self.assertEqual(len(rows), 2)
        offsets = {row.index("APPROVE") for row in rows}
        self.assertEqual(len(offsets), 1, f"verdict column shifted between rows: {rows}")


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

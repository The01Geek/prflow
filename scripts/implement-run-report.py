#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Report implement-run duration and cost from the joined experiment records.

    implement-run-report.py <N> [--records <path>]
    implement-run-report.py --retro [--records <path>]

The positional N is required in per-run mode: it names how many of the most recent
implement runs to render, one row each — total duration, per-phase share, dollar cost,
terminal status and review verdict — followed by an aggregate block holding the mean and
median of duration and cost.

`--retro` is the weekly-retrospective view: the trailing-four-week mean duration and cost,
plus one regression line for each week whose mean duration exceeds the preceding
four-week mean by more than REGRESSION_THRESHOLD_PCT. A week with fewer than four
preceding weeks of data yields no line — it cannot exceed a mean that does not exist.

Every aggregate excludes an unestablished operand rather than reading it as zero.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED
from implement_records import (
    fmt,
    load_runs_with_status,
    max_or_unestablished,
    mean_or_unestablished,
    median_or_unestablished,
    numeric,
    phase_shares_with_completeness,
    seconds,
)

# The fraction by which a week's mean duration must exceed the preceding four-week mean
# before it is reported as a regression.
REGRESSION_THRESHOLD_PCT = 25

# How many preceding weeks the trailing comparison window holds.
TRAILING_WEEKS = 4


def _iso_week(merged_at):
    if not isinstance(merged_at, str) or not merged_at:
        return None
    try:
        moment = dt.datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    year, week, _day = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _top_phases(run, limit=3):
    """The largest phase shares, marked `partial` when the run recorded a phase whose
    duration was never established — the shares are fractions of the measured total, so
    without that mark a one-phase measurement renders like a whole-run one."""
    shares, complete = phase_shares_with_completeness(run)
    if not shares:
        return UNESTABLISHED
    ranked = sorted(shares.items(), key=lambda kv: -kv[1])[:limit]
    # The keys are workpad phase headings ("PR marked ready"), never paths.
    rendered = " ".join(f"{name}={s * 100:.0f}%" for name, s in ranked)
    return rendered if complete else rendered + " (partial)"


def render_runs(runs, n, status="read"):
    lines = []
    if status == "unreadable":
        return ("The experiment-record store exists but could not be read. That is not the "
                "same as holding no runs — resolve it before reading anything as a "
                "measurement.")
    if status == "absent":
        return "No experiment-record store yet — no implement run has been persisted."
    if status.startswith("read:"):
        lines.append(f"NOTE: {status.split(':', 1)[1]} store line(s) could not be parsed "
                     f"and are excluded from every figure below.")
    recent = runs[-n:] if n else []
    lines.append(f"Most recent {len(recent)} implement run(s) "
                 f"(of {len(runs)} in the store)")
    lines.append(f"{'run_id':>14}  {'duration':>10}  {'cost':>9}  {'peak_ctx':>9}  "
                 f"{'status':<13}  {'verdict':<20}  phase share")
    for run in recent:
        duration = run["duration_ms"]
        duration_s = f"{duration / 1000:.0f}s" if duration is not None else UNESTABLISHED
        # issue #120: peak main-thread context per run. `unestablished` (never 0) on a
        # pre-#120 record or one whose file carried no main-thread usage.
        peak = run["peak_main_thread_context"]
        peak_s = str(peak) if peak is not None else UNESTABLISHED
        lines.append(
            f"{run['run_id'] or UNESTABLISHED!s:>14}  {duration_s:>10}  "
            f"{fmt(run['cost_usd']):>9}  {peak_s:>9}  "
            f"{run['terminal_status'] or UNESTABLISHED!s:<13}  "
            f"{run['verdict'] or UNESTABLISHED!s:<20}  {_top_phases(run)}")
    durations = [r["duration_ms"] for r in recent]
    costs = [r["cost_usd"] for r in recent]
    lines.append("")
    lines.append("Aggregate")
    established = len(numeric(durations))
    lines.append(f"  runs with an established duration: {established} of {len(recent)}")
    mean_ms = mean_or_unestablished(durations)
    median_ms = median_or_unestablished(durations)
    lines.append(f"  mean duration:   {seconds(mean_ms)}")
    lines.append(f"  median duration: {seconds(median_ms)}")
    lines.append(f"  mean cost:       {fmt(mean_or_unestablished(costs))}")
    lines.append(f"  median cost:     {fmt(median_or_unestablished(costs))}")
    return "\n".join(lines)


def weekly_means(runs):
    """{iso_week: {"duration": mean|unestablished, "cost": …, "count": n}}, week-ordered."""
    buckets = {}
    for run in runs:
        week = _iso_week(run["merged_at"])
        if week is None:
            continue
        buckets.setdefault(week, {"duration": [], "cost": []})
        buckets[week]["duration"].append(run["duration_ms"])
        buckets[week]["cost"].append(run["cost_usd"])
    out = {}
    for week in sorted(buckets):
        out[week] = {
            "duration": mean_or_unestablished(buckets[week]["duration"]),
            "cost": mean_or_unestablished(buckets[week]["cost"]),
            "count": len(buckets[week]["duration"]),
        }
    return out


def regressions(weeks):
    """One entry per week whose mean duration exceeds the preceding four-week mean by
    more than the threshold. A week without a full preceding window is skipped: with no
    comparand there is nothing for it to exceed, and reporting one would be an assertion
    about data that does not exist."""
    ordered = list(weeks)
    found = []
    for idx, week in enumerate(ordered):
        if idx < TRAILING_WEEKS:
            continue
        this = weeks[week]["duration"]
        if this == UNESTABLISHED:
            continue
        window = [weeks[w]["duration"] for w in ordered[idx - TRAILING_WEEKS:idx]]
        baseline = mean_or_unestablished(window)
        if baseline == UNESTABLISHED or baseline <= 0:
            continue
        delta_pct = (this - baseline) / baseline * 100
        if delta_pct > REGRESSION_THRESHOLD_PCT:
            found.append({"week": week, "mean_ms": this, "baseline_ms": baseline,
                          "delta_pct": delta_pct})
    return found


def render_retro(runs, status="read"):
    lines = ["## Implement runtime trends", ""]
    if status == "unreadable":
        lines.append("_(the experiment-record store exists but could not be read — this is "
                     "not the same as holding no runs)_")
        return "\n".join(lines)
    if status == "absent":
        lines.append("_(no implement run records yet)_")
        return "\n".join(lines)
    if status.startswith("read:"):
        lines.append(f"_({status.split(':', 1)[1]} store line(s) unparseable and excluded)_")
        lines.append("")
    if not runs:
        lines.append("_(no implement run records yet)_")
        return "\n".join(lines)
    weeks = weekly_means(runs)
    ordered = list(weeks)
    trailing = ordered[-TRAILING_WEEKS:]
    window_durations = [weeks[w]["duration"] for w in trailing]
    window_costs = [weeks[w]["cost"] for w in trailing]
    mean_ms = mean_or_unestablished(window_durations)
    lines.append(f"Trailing {len(trailing)}-week mean duration: {seconds(mean_ms)}")
    lines.append(f"Trailing {len(trailing)}-week mean cost: "
                 f"{fmt(mean_or_unestablished(window_costs))}")
    # issue #120: cloud context cost over the trailing window — median AND max, so the tail
    # is visible, on the same footing as duration/cost above. Computed over the RUNS whose
    # ISO week falls in the trailing window, not over weekly means. `unestablished` (never
    # 0) when no run in the window carries the field. These are instrument outputs only: the
    # regression check below still compares duration alone (AC12).
    trailing_set = set(trailing)
    window_runs = [r for r in runs if _iso_week(r["merged_at"]) in trailing_set]
    window_peaks = [r["peak_main_thread_context"] for r in window_runs]
    window_phase_reads = [r["phase_file_reads_total"] for r in window_runs]
    lines.append(f"Trailing {len(trailing)}-week median peak main-thread context: "
                 f"{median_or_unestablished(window_peaks)}")
    lines.append(f"Trailing {len(trailing)}-week max peak main-thread context: "
                 f"{max_or_unestablished(window_peaks)}")
    lines.append(f"Trailing {len(trailing)}-week median total phase-file reads: "
                 f"{median_or_unestablished(window_phase_reads)}")
    lines.append(f"Trailing {len(trailing)}-week max total phase-file reads: "
                 f"{max_or_unestablished(window_phase_reads)}")
    lines.append("")
    found = regressions(weeks)
    if not found:
        lines.append(f"No week exceeds its preceding {TRAILING_WEEKS}-week mean duration "
                     f"by more than {REGRESSION_THRESHOLD_PCT} percent.")
    else:
        for item in found:
            lines.append(
                f"REGRESSION {item['week']}: mean duration "
                f"{item['mean_ms'] / 1000:.0f}s exceeds the preceding "
                f"{TRAILING_WEEKS}-week mean {item['baseline_ms'] / 1000:.0f}s by "
                f"{item['delta_pct']:.0f} percent "
                f"(threshold {REGRESSION_THRESHOLD_PCT} percent)")
    return "\n".join(lines)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("count", nargs="?", type=int,
                        help="how many of the most recent implement runs to render "
                             "(required unless --retro is given)")
    parser.add_argument("--retro", action="store_true",
                        help="render the weekly-retrospective trend section instead")
    parser.add_argument("--records", help="path to experiment-records.jsonl")
    args = parser.parse_args(argv)

    if not args.retro and args.count is None:
        parser.error("the number of runs to render is required (or pass --retro)")
    if args.count is not None and args.count <= 0:
        parser.error("the number of runs to render must be a positive integer")

    runs, status = load_runs_with_status(args.records)
    print(render_retro(runs, status) if args.retro
          else render_runs(runs, args.count, status))
    # Only an UNREADABLE store is a failure. An absent one is the normal state of a
    # repository that has persisted no run, and the retrospective gates its append on this
    # status — returning non-zero there would make every fresh install report a broken tool.
    return 1 if status == "unreadable" else 0


if __name__ == "__main__":
    sys.exit(main())

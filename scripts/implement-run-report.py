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

from context_eval_shared import UNESTABLISHED  # noqa: E402
from implement_records import (  # noqa: E402
    fmt,
    load_runs,
    mean_or_unestablished,
    median_or_unestablished,
    numeric,
    phase_shares,
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
    shares = phase_shares(run)
    if not shares:
        return UNESTABLISHED
    ranked = sorted(shares.items(), key=lambda kv: -kv[1])[:limit]
    return " ".join(f"{Path(p).name}={s * 100:.0f}%" for p, s in ranked)


def render_runs(runs, n):
    lines = []
    recent = runs[-n:] if n else []
    lines.append(f"Most recent {len(recent)} implement run(s) "
                 f"(of {len(runs)} in the store)")
    lines.append(f"{'run_id':>14}  {'duration':>10}  {'cost':>9}  "
                 f"{'status':<12}  {'verdict':<20}  phase share")
    for run in recent:
        duration = run["duration_ms"]
        duration_s = f"{duration / 1000:.0f}s" if duration is not None else UNESTABLISHED
        lines.append(
            f"{str(run['run_id'] or UNESTABLISHED):>14}  {duration_s:>10}  "
            f"{fmt(run['cost_usd']):>9}  "
            f"{str(run['terminal_status'] or UNESTABLISHED):<12}  "
            f"{str(run['verdict'] or UNESTABLISHED):<20}  {_top_phases(run)}")
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


def render_retro(runs):
    lines = ["## Implement runtime trends", ""]
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


def main(argv=None):
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

    runs = load_runs(args.records)
    print(render_retro(runs) if args.retro else render_runs(runs, args.count))
    return 0


if __name__ == "__main__":
    sys.exit(main())

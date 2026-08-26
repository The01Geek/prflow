#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Compare two cohorts of implement runs selected by configuration fingerprint.

    implement-benchmark.py --cohort-a <fingerprint> --cohort-b <fingerprint>
                           [--records <path>]

A cohort is every implement run whose experiment record carries the named
`config_fingerprint` value — its `sha256`, matched in full or by a unique prefix, which is
the identity the join already stamps on each record.

Per cohort the report holds the run count and the mean, median and population standard
deviation of duration and cost. The efficiency verdict is WITHHELD, with the reason
printed, whenever either cohort holds fewer than MIN_COHORT_RUNS runs and whenever either
cohort contains a run whose final review verdict was REJECT. The two conditions are
independent: either alone withholds, and both print when both apply — crediting an
optimization on a cohort whose work was rejected would read a quality failure as a speedup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED  # noqa: E402
from implement_records import (  # noqa: E402
    fmt,
    is_reject,
    load_runs,
    mean_or_unestablished,
    median_or_unestablished,
    numeric,
    seconds,
    stdev_or_unestablished,
)

# Below this many runs a cohort's spread is not worth a verdict.
MIN_COHORT_RUNS = 5


def select_cohort(runs, fingerprint):
    """Every run whose fingerprint equals `fingerprint`, or begins with it.

    A prefix is accepted because a sha256 is unwieldy to type; a prefix that matches more
    than one distinct fingerprint is rejected by the caller rather than silently merging
    two cohorts into one.
    """
    return [r for r in runs
            if isinstance(r["fingerprint"], str) and r["fingerprint"].startswith(fingerprint)]


def distinct_fingerprints(cohort):
    return sorted({r["fingerprint"] for r in cohort})


def describe(cohort):
    durations = [r["duration_ms"] for r in cohort]
    costs = [r["cost_usd"] for r in cohort]
    return {
        "count": len(cohort),
        "established_durations": len(numeric(durations)),
        "duration_mean_ms": mean_or_unestablished(durations),
        "duration_median_ms": median_or_unestablished(durations),
        "duration_stdev_ms": stdev_or_unestablished(durations),
        "cost_mean_usd": mean_or_unestablished(costs),
        "cost_median_usd": median_or_unestablished(costs),
        "cost_stdev_usd": stdev_or_unestablished(costs),
        "reject_runs": [r["run_id"] for r in cohort if is_reject(r["verdict"])],
    }


def withholding_reasons(label_a, stats_a, label_b, stats_b):
    """Every reason the verdict is withheld. Empty means it may be reported."""
    reasons = []
    for label, stats in ((label_a, stats_a), (label_b, stats_b)):
        if stats["count"] < MIN_COHORT_RUNS:
            reasons.append(f"cohort {label} holds {stats['count']} run(s), fewer than the "
                           f"{MIN_COHORT_RUNS} required for a verdict")
    for label, stats in ((label_a, stats_a), (label_b, stats_b)):
        if stats["reject_runs"]:
            reasons.append(f"cohort {label} contains {len(stats['reject_runs'])} run(s) "
                           f"whose final review verdict was REJECT "
                           f"({', '.join(str(r) for r in stats['reject_runs'])})")
    return reasons


def _render_cohort(label, fingerprint, stats):
    return "\n".join([
        f"Cohort {label} — {fingerprint}",
        f"  runs:                 {stats['count']} "
        f"({stats['established_durations']} with an established duration)",
        f"  duration mean:        {seconds(stats['duration_mean_ms'])}",
        f"  duration median:      {seconds(stats['duration_median_ms'])}",
        f"  duration stdev:       {seconds(stats['duration_stdev_ms'])}",
        f"  cost mean:            {fmt(stats['cost_mean_usd'])}",
        f"  cost median:          {fmt(stats['cost_median_usd'])}",
        f"  cost stdev:           {fmt(stats['cost_stdev_usd'])}",
    ])


def render(fp_a, cohort_a, fp_b, cohort_b):
    stats_a, stats_b = describe(cohort_a), describe(cohort_b)
    lines = [_render_cohort("A", fp_a, stats_a), "", _render_cohort("B", fp_b, stats_b), ""]
    reasons = withholding_reasons("A", stats_a, "B", stats_b)
    if reasons:
        lines.append("Efficiency verdict WITHHELD:")
        for reason in reasons:
            lines.append(f"  - {reason}")
        return "\n".join(lines)
    mean_a, mean_b = stats_a["duration_mean_ms"], stats_b["duration_mean_ms"]
    if mean_a == UNESTABLISHED or mean_b == UNESTABLISHED or mean_a <= 0:
        lines.append("Efficiency verdict WITHHELD:")
        lines.append("  - a cohort's mean duration could not be established, so there is "
                     "nothing to compare")
        return "\n".join(lines)
    delta = (mean_b - mean_a) / mean_a * 100
    direction = "faster" if delta < 0 else "slower"
    lines.append(f"Efficiency verdict: cohort B is {abs(delta):.1f} percent {direction} "
                 f"than cohort A on mean duration")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort-a", required=True, help="config_fingerprint sha256 (or prefix)")
    parser.add_argument("--cohort-b", required=True, help="config_fingerprint sha256 (or prefix)")
    parser.add_argument("--records", help="path to experiment-records.jsonl")
    args = parser.parse_args(argv)

    runs = load_runs(args.records)
    cohort_a = select_cohort(runs, args.cohort_a)
    cohort_b = select_cohort(runs, args.cohort_b)
    for label, fingerprint, cohort in (("A", args.cohort_a, cohort_a),
                                       ("B", args.cohort_b, cohort_b)):
        distinct = distinct_fingerprints(cohort)
        if len(distinct) > 1:
            print(f"devflow: implement-benchmark: cohort {label}'s prefix "
                  f"'{fingerprint}' matches {len(distinct)} distinct fingerprints "
                  f"({', '.join(distinct)}); pass a longer prefix so the cohorts are not "
                  f"silently merged", file=sys.stderr)
            return 2
    print(render(args.cohort_a, cohort_a, args.cohort_b, cohort_b))
    return 0


if __name__ == "__main__":
    sys.exit(main())

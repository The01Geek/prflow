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
printed, whenever either cohort holds fewer than MIN_COHORT_RUNS runs with an ESTABLISHED
duration — the figures are computed over those, so a larger cohort of mostly-unmeasured runs
still withholds — and whenever either cohort contains a run whose final review verdict was
REJECT. The two conditions are
independent: either alone withholds, and both print when both apply — crediting an
optimization on a cohort whose work was rejected would read a quality failure as a speedup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED
from implement_records import (
    fmt,
    is_reject,
    load_runs_with_status,
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
    two cohorts into one. An EMPTY operand selects nothing rather than everything — it
    prefix-matches every run, so it would otherwise make both cohorts the whole store and
    compare it against itself.
    """
    if not fingerprint:
        return []
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
        # Gate on the ESTABLISHED durations, not the raw count: every statistic below is
        # computed over those, so a five-run cohort with four unmeasured durations would
        # otherwise print a verdict drawn from a one-sample mean.
        established = stats["established_durations"]
        if established < MIN_COHORT_RUNS:
            reasons.append(f"cohort {label} holds {established} run(s) with an established "
                           f"duration (of {stats['count']}), fewer than the "
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
        (f"  runs:                 {stats['count']} "
         f"({stats['established_durations']} with an established duration)"),
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
    # Keep the two arms' reasons distinct: a zero or negative baseline mean IS established,
    # so reporting it as unestablished would send a reader hunting for a missing measurement
    # instead of the impossible duration that actually blocked the percentage.
    if mean_a == UNESTABLISHED or mean_b == UNESTABLISHED:
        lines.append("Efficiency verdict WITHHELD:")
        lines.append("  - a cohort's mean duration could not be established, so there is "
                     "nothing to compare")
        return "\n".join(lines)
    if mean_a <= 0:
        lines.append("Efficiency verdict WITHHELD:")
        lines.append(f"  - cohort A's mean duration is {mean_a:g} ms, so a percentage "
                     f"against it is undefined")
        return "\n".join(lines)
    delta = (mean_b - mean_a) / mean_a * 100
    direction = "faster" if delta < 0 else "slower"
    lines.append(f"Efficiency verdict: cohort B is {abs(delta):.1f} percent {direction} "
                 f"than cohort A on mean duration")
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
    parser.add_argument("--cohort-a", required=True, help="config_fingerprint sha256 (or prefix)")
    parser.add_argument("--cohort-b", required=True, help="config_fingerprint sha256 (or prefix)")
    parser.add_argument("--records", help="path to experiment-records.jsonl")
    args = parser.parse_args(argv)

    runs, status = load_runs_with_status(args.records)
    if status == "unreadable":
        print("devflow: implement-benchmark: the experiment-record store exists but could "
              "not be read; that is not an empty store, so no cohort below would mean "
              "anything", file=sys.stderr)
        return 1
    if status == "absent":
        print("No experiment-record store yet — no implement run has been persisted, so "
              "neither cohort can be formed. (A store that exists but cannot be read is a "
              "different, non-zero-exit case.)")
        return 0
    if status.startswith("read:"):
        print(f"NOTE: {status.split(':', 1)[1]} store line(s) could not be parsed and are "
              f"excluded from both cohorts.")
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

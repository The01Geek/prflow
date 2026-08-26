#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared reader over the implement runs in `.prflow/learnings/experiment-records.jsonl`.

`scripts/implement-run-report.py` and `scripts/implement-benchmark.py` both select the
same population and aggregate the same figures, so the selection and the statistics live
here once rather than in two copies that drift.

Every aggregate excludes an operand that was never established. An absent figure is
`None` in a loaded run and the string `unestablished` in the per-run record it came from;
both are dropped by `numeric()` before any arithmetic, so an unmeasured run can never
enter a mean, a median or a standard deviation as a real value.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED, _median  # noqa: E402

DEFAULT_STORE = Path(".prflow/learnings/experiment-records.jsonl")


def _figure(value):
    """A usable number, or None. Rejects bools (an int subclass), non-finite floats, and
    the `unestablished` sentinel — each of which would otherwise enter an aggregate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def numeric(values):
    """Only the established numbers in `values`."""
    return [v for v in (_figure(x) for x in values) if v is not None]


def mean_or_unestablished(values):
    nums = numeric(values)
    return statistics.fmean(nums) if nums else UNESTABLISHED


def median_or_unestablished(values):
    nums = numeric(values)
    return _median(nums) if nums else UNESTABLISHED


def stdev_or_unestablished(values):
    """Population standard deviation. Refuses a population of fewer than two — a single
    observation has no established spread, and reporting 0 would read as 'no variance'."""
    nums = numeric(values)
    return statistics.pstdev(nums) if len(nums) >= 2 else UNESTABLISHED


def _fingerprint_sha(record):
    fp = record.get("config_fingerprint")
    if isinstance(fp, dict) and isinstance(fp.get("sha256"), str):
        return fp["sha256"]
    return None


def load_runs(path=None):
    """Every implement run in the store, newest last, as flat dicts.

    One experiment-record line joins one merged PR to the efficiency runs behind it, and
    a line can carry runs from more than one command class, so the class is read from each
    run's own `harness_cost.command` rather than from the line.
    """
    store = Path(path) if path else DEFAULT_STORE
    runs = []
    try:
        text = store.read_text(encoding="utf-8")
    except OSError:
        return runs
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        for entry in record.get("efficiency_runs") or []:
            if not isinstance(entry, dict):
                continue
            hc = entry.get("harness_cost")
            if not isinstance(hc, dict) or hc.get("command") != "implement":
                continue
            profile = entry.get("run_profile") if isinstance(entry.get("run_profile"), dict) else {}
            runs.append({
                "pr": record.get("pr"),
                "issue": record.get("issue"),
                "run_id": entry.get("run_id"),
                "merged_at": record.get("merged_at"),
                "verdict": record.get("verdict"),
                "fingerprint": _fingerprint_sha(record),
                "duration_ms": _figure(hc.get("duration_ms")),
                "cost_usd": _figure(hc.get("cost_usd")),
                "num_turns": _figure(hc.get("num_turns")),
                # From the run_profile floor; absent on every pre-#2006 record, which is
                # why each of these is None rather than a default value.
                "terminal_status": profile.get("final_status"),
                "phase_durations_ms": profile.get("phase_durations_ms"),
                "engine_outcome": profile.get("engine_outcome"),
                "prior_record_count": profile.get("prior_record_count"),
            })
    runs.sort(key=lambda r: (r["merged_at"] or "", str(r["run_id"] or "")))
    return runs


def phase_shares(run):
    """{phase: fraction of this run's attributed phase time}, or {} when unestablished."""
    durations = run.get("phase_durations_ms")
    if not isinstance(durations, dict):
        return {}
    established = {k: v for k, v in durations.items() if _figure(v) is not None}
    total = sum(established.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in established.items()}


def is_reject(verdict):
    """True when a run's final review verdict was a REJECT.

    Case-insensitive containment, because the stored verdict is free-ish text
    (`APPROVE with notes`, `REJECT`), and a cohort must be withheld on any REJECT.
    """
    return isinstance(verdict, str) and "reject" in verdict.lower()


def fmt(value, suffix=""):
    """Render a figure or the unestablished sentinel for a text table."""
    if value == UNESTABLISHED or value is None:
        return UNESTABLISHED
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"

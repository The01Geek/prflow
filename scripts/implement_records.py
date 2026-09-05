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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED, _median

STORE_RELPATH = ".prflow/learnings/experiment-records.jsonl"


def default_store():
    """The store, anchored on the git repo root like every other `.prflow` reader.

    A cwd-relative default reports an empty store from any subdirectory, which these
    tools would then render as "no runs yet" rather than as a path they could not find.
    """
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=False)
        if root.returncode == 0 and root.stdout.strip():
            return Path(root.stdout.strip()) / STORE_RELPATH
    except OSError:
        pass
    return (Path.cwd() / STORE_RELPATH).resolve()


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


def max_or_unestablished(values):
    """The maximum established number, or the UNESTABLISHED sentinel on an empty
    population — never a real value the data did not carry (issue #120)."""
    nums = numeric(values)
    return max(nums) if nums else UNESTABLISHED


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
    """Every implement run in the store, newest last. See `load_runs_with_status`."""
    return load_runs_with_status(path)[0]


def load_runs_with_status(path=None):
    """`(runs, status)` — every implement run in the store, newest last, plus how the
    read went.

    `status` is `absent` when the store does not exist (the normal state of a repository
    that has persisted no implement run), `unreadable` when it exists but could not be
    opened, else `read`, with `:<n>-unparseable` appended when lines were skipped.
    Swallowing the difference reports an unreadable file as "no runs yet", and every
    aggregate then shrinks invisibly.

    One experiment-record line joins one merged PR to the efficiency runs behind it, and
    a line can carry runs from more than one command class, so the class is read from each
    run's own `harness_cost.command` rather than from the line.
    """
    store = Path(path) if path else default_store()
    runs = []
    skipped = 0
    if not store.exists():
        # A store that is simply not there yet is the normal state of a repository that
        # has persisted no implement run — distinct from one that exists and cannot be
        # read, which is a real failure. Collapsing the two makes every fresh install
        # report the reader as broken.
        return runs, "absent"
    try:
        handle = store.open(encoding="utf-8")
    except OSError:
        return runs, "unreadable"
    # Iterated, not read_text().splitlines(): the store is append-only and already several
    # megabytes, and materializing it doubles peak memory for a strictly line-by-line read.
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(record, dict):
                skipped += 1
                continue
            _ingest(record, runs)
    runs.sort(key=lambda r: (r["merged_at"] or "", str(r["run_id"] or "")))
    status = "read" if not skipped else f"read:{skipped}-unparseable"
    return runs, status


def _ingest(record, runs):
    """Append every implement run this experiment-record line carries."""
    for entry in record.get("efficiency_runs") or []:
        if not isinstance(entry, dict):
            continue
        hc = entry.get("harness_cost")
        if not isinstance(hc, dict) or hc.get("command") != "implement":
            continue
        profile = entry.get("run_profile") if isinstance(entry.get("run_profile"), dict) else {}
        # issue #120: peak main-thread context and total phase-file reads. Absent or null
        # on every pre-#120 record (and phase_file_reads null when the file carried no
        # main-thread record), so each yields None via _figure and is excluded from every
        # aggregate — never a real-looking 0.
        pfr = hc.get("phase_file_reads")
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
            "peak_main_thread_context": _figure(hc.get("peak_main_thread_context")),
            "phase_file_reads_total": _figure(
                pfr.get("total") if isinstance(pfr, dict) else None),
            # From the run_profile floor; absent on every pre-#2006 record, which is
            # why each of these is None rather than a default value.
            "terminal_status": profile.get("final_status"),
            "phase_durations_ms": profile.get("phase_durations_ms"),
            "engine_outcome": profile.get("engine_outcome"),
            "prior_record_count": profile.get("prior_record_count"),
        })


def phase_shares(run):
    """{phase: fraction of this run's attributed phase time}, or {} when unestablished."""
    return phase_shares_with_completeness(run)[0]


def phase_shares_with_completeness(run):
    """`(shares, complete)` — the per-phase fractions, and whether every phase this run
    recorded was established.

    The shares are fractions of the ESTABLISHED total, so a run with an unmeasured phase
    still sums to 100%. `complete` is what stops that from reading as a whole-run
    measurement: without it a run measured on one phase renders identically to one
    measured on all of them.
    """
    durations = run.get("phase_durations_ms")
    if not isinstance(durations, dict):
        return {}, False
    # A negative span is not a measurement — workpad stamps can violate monotonicity — and
    # admitting one inflates the remaining shares past 100% while still reading complete.
    established = {k: v for k, v in durations.items()
                   if _figure(v) is not None and _figure(v) >= 0}
    complete = len(established) == len(durations)
    total = sum(established.values())
    if total <= 0:
        return {}, complete
    return {k: v / total for k, v in established.items()}, complete


def is_reject(verdict):
    """True when a run's final review verdict was a REJECT.

    Case-insensitive containment, because the stored verdict is free-ish text
    (`APPROVE with notes`, `REJECT`), and a cohort must be withheld on any REJECT.
    """
    return isinstance(verdict, str) and "reject" in verdict.lower()


def seconds(value):
    """Render a millisecond figure as seconds, passing the unestablished sentinel through."""
    return UNESTABLISHED if value == UNESTABLISHED or value is None else fmt(value / 1000, "s")


def fmt(value, suffix=""):
    """Render a figure or the unestablished sentinel for a text table."""
    if value == UNESTABLISHED or value is None:
        return UNESTABLISHED
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"

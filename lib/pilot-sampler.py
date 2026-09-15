#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Runner memory/RSS sampler for the two-core pilot (issue #420, Stage A).

Internal dev-only pilot harness helper (vendors with the rest of lib/, but no
shipped skill or workflow invokes it). The pure functions parse recorded
`ps -eo pid,ppid,rss` blocks and `/proc/pressure/memory` text and compute the
maximum observed root-plus-descendants RSS sum across samples. They take
recorded text/data, so tests never invoke `ps` or read `/proc`. The `main()`
CLI loop is the only part that shells out; it is exercised only by a manual
pilot dispatch (Stage B), not the suite.

The reported figure is a sampling-interval maximum of summed RSS, NOT an exact
physical peak: RSS double-counts shared pages and a 1-second interval can miss a
sub-interval spike. The summary carries a `note` field saying so.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterable


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit test importing this module never mutates the importer's streams). The
    reconfigure overrides even a hostile PYTHONIOENCODING; a stream replaced with a
    non-TextIOWrapper (a test's io.StringIO) has no reconfigure and is tolerated."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def parse_ps_rss_block(text: str) -> list[dict]:
    """Parse one `ps -eo pid,ppid,rss` block into a list of {pid, ppid, rss_kb}.

    The header row (whose first data column is the literal ``PID``) is skipped.
    A row that does not hold three integer columns is skipped rather than
    crashing the sampler mid-run. Returns [] for empty/whitespace-only input.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0].upper() == "PID":
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            rss_kb = int(parts[2])
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "rss_kb": rss_kb})
    return rows


def _descendant_pids(rows: list[dict], root_pid: int) -> set[int]:
    """Return root_pid plus every pid transitively reachable through ppid links,
    restricted to pids alive in this sample (an exited descendant contributes
    nothing)."""
    children: dict[int, list[int]] = {}
    present: set[int] = set()
    for row in rows:
        present.add(row["pid"])
        children.setdefault(row["ppid"], []).append(row["pid"])
    # Root-presence contract: a sample only counts as a rooted observation when the root
    # process is itself alive in it. Without this, a row naming an absent root as its ppid
    # would credit a bogus valid sample (issue #458).
    if root_pid not in present:
        return set()
    collected: set[int] = set()
    frontier = [root_pid]
    while frontier:
        pid = frontier.pop()
        if pid in collected:
            continue
        collected.add(pid)
        frontier.extend(children.get(pid, []))
    return {pid for pid in collected if pid in present}


def max_root_plus_descendants_rss(
    samples: Iterable[list[dict]], root_pid: int, cpu_count: int | None = None
) -> dict:
    """Max summed RSS over the root process tree across samples.

    ``samples`` is an iterable of parsed samples (each a list of
    {pid, ppid, rss_kb} rows). For each sample the RSS of the root and every
    descendant alive in that sample is summed; the maximum such sum is returned.
    ``sample_index`` is -1 when no sample contained the root. ``valid_rooted_samples``
    counts the samples that actually contained the root, so a genuine zero-RSS
    observation (root present, sum 0) stays distinguishable from a missing-root gap
    (``valid_rooted_samples == 0``). ``cpu_count`` is echoed through so the offload
    host's core count travels with the figure.
    """
    max_sum = 0
    max_index = -1
    examined = 0
    valid_rooted = 0
    for index, sample in enumerate(samples):
        examined += 1
        pids = _descendant_pids(sample, root_pid)
        if not pids:
            continue
        valid_rooted += 1
        by_pid = {row["pid"]: row["rss_kb"] for row in sample}
        total = sum(by_pid.get(pid, 0) for pid in pids)
        if max_index == -1 or total > max_sum:
            max_sum = total
            max_index = index
    return {
        "max_sum_kb": max_sum,
        "sample_index": max_index,
        "samples_examined": examined,
        "valid_rooted_samples": valid_rooted,
        "cpu_count": cpu_count,
        "unit": "KiB",
        "note": (
            "sampling-interval maximum of summed RSS across the process tree; "
            "RSS double-counts shared pages and the interval can miss a "
            "sub-interval spike, so this is not an exact physical peak"
        ),
    }


def read_proc_pressure_memory(text: str) -> dict | None:
    """Parse `/proc/pressure/memory` text into {"some": {...}, "full": {...}}.

    Returns None on empty/whitespace-only input or when no line parses into a
    recognised (``some``/``full``) pressure row — an unreadable pressure source
    is a documented gap, never a crash.
    """
    if not text or not text.strip():
        return None
    result: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        kind = parts[0]
        if kind not in ("some", "full"):
            continue
        fields: dict[str, float] = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            key, _, value = token.partition("=")
            try:
                fields[key] = float(value)
            except ValueError:
                continue
        if fields:
            result[kind] = fields
    return result or None


def _read_ps() -> tuple[str | None, str | None]:
    """Return ``(stdout, None)`` for a successful `ps -eo pid,ppid,rss`, or
    ``(None, reason)`` when ps failed.

    A None block distinguishes a failed measurement from a genuine empty sample:
    a non-zero exit — or a missing/unexecutable ps binary, which raises rather
    than exiting (issue #458) — must not be coerced to zero RSS (byte-identical
    to a real zero observation). The reason string retains diagnostic evidence so
    a launch failure is recorded, not silently swallowed.
    """
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,rss"], capture_output=True, text=True, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"ps launch failed: {exc}"
    if proc.returncode != 0:
        return None, f"ps exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    return proc.stdout, None


def _read_pressure(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample process-tree RSS once per interval.")
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="0 = until interrupted")
    parser.add_argument("--pressure-path", default="/proc/pressure/memory")
    parser.add_argument(
        "--summary-path",
        default=None,
        help="write the summary JSON here via a temp file + atomic rename (so a reader "
        "never sees a partial artifact); when omitted the summary is written to stdout",
    )
    parser.add_argument(
        "--rows-path",
        default=None,
        help="append one JSON line per interval ({ts, rows, read_failure}) here, where rows is "
        "the root's process tree (root + descendants) retained as timestamped coverage evidence",
    )
    _force_utf8_streams()
    args = parser.parse_args(argv)

    # The workflow stops the background sampler with a bare `kill` (SIGTERM); raise
    # KeyboardInterrupt on SIGTERM too so the summary is still written on the way out
    # (SIGINT alone would leave the retained artifact empty). Installed in main(), not
    # at import, so importing this module for a unit test never touches signal state.
    def _stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)

    samples: list[list[dict]] = []
    pressures: list[dict | None] = []
    read_failures = 0
    read_failure_reasons: list[str] = []
    shutdown_status = "completed"
    rows_handle = open(args.rows_path, "w", encoding="utf-8") if args.rows_path else None
    start = time.monotonic()
    try:
        while True:
            ts = time.time()
            block, reason = _read_ps()
            tree_rows = None
            if block is None:
                read_failures += 1
                if reason and len(read_failure_reasons) < 5:
                    read_failure_reasons.append(reason)
            else:
                rows = parse_ps_rss_block(block)
                samples.append(rows)
                # Retain ONLY the root's process tree (root + descendants), not the whole ps
                # table: len(rows) then reads as descendant coverage, and the whole table would
                # make that count vacuously true on any real host (issue #458 review).
                tree_pids = _descendant_pids(rows, args.root_pid)
                tree_rows = [row for row in rows if row["pid"] in tree_pids]
            if rows_handle is not None:
                rows_handle.write(
                    json.dumps({"ts": ts, "rows": tree_rows, "read_failure": block is None}) + "\n"
                )
                rows_handle.flush()
            pressures.append(read_proc_pressure_memory(_read_pressure(args.pressure_path)))
            if args.duration_seconds and (time.monotonic() - start) >= args.duration_seconds:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        # A SIGTERM/SIGINT stop is the workflow's normal shutdown path, so this is still a
        # valid (flushed) measurement — recorded as 'signalled', distinct from 'completed'.
        shutdown_status = "signalled"
    finally:
        # Do not let a stop signal during the flush truncate the summary: ignore SIGTERM and
        # SIGINT once past the loop, so a repeated stop cannot corrupt the write (issue #458).
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if rows_handle is not None:
            rows_handle.close()

    summary = max_root_plus_descendants_rss(samples, args.root_pid, cpu_count=os.cpu_count())
    summary["pressure_samples"] = pressures
    summary["pressure_gap_count"] = sum(1 for p in pressures if p is None)
    summary["read_failures"] = read_failures
    summary["read_failure_reasons"] = read_failure_reasons
    summary["usable_samples"] = len(samples)
    summary["shutdown_status"] = shutdown_status
    summary["root_pid"] = args.root_pid
    summary["interval_seconds"] = args.interval_seconds

    # gap_reason is a machine-readable enum a reader branches on instead of parsing prose.
    # A valid measurement needs at least one sample that actually contained the root; an
    # empty or rootless collection is a gap, never a genuine zero-RSS observation.
    if summary["valid_rooted_samples"] == 0:
        if samples:
            summary["gap_reason"] = "no_rooted_sample"
        elif read_failures == 0:
            # Empty with no read failure means a stop signal arrived before the first read
            # completed — an interruption, not ps being unavailable.
            summary["gap_reason"] = "interrupted"
        else:
            summary["gap_reason"] = "ps_unavailable"
    else:
        summary["gap_reason"] = "none"

    _write_summary(summary, args.summary_path)

    if summary["gap_reason"] != "none":
        sys.stderr.write(
            f"pilot-sampler: invalid measurement (gap_reason={summary['gap_reason']}, "
            f"{read_failures} read failure(s), shutdown_status={shutdown_status}); "
            "not a zero-RSS observation\n"
        )
        return 1
    return 0


def _write_summary(summary: dict, summary_path: str | None) -> None:
    """Emit the summary to stdout, or to summary_path via a temp file + atomic rename.

    os.replace is atomic on POSIX, so a reader (the workflow's upload step) never sees a
    partial artifact — an interrupted or incomplete write leaves the destination path
    untouched rather than a truncated JSON (issue #458).
    """
    if summary_path:
        tmp_path = summary_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
            handle.write("\n")
        os.replace(tmp_path, summary_path)
    else:
        json.dump(summary, sys.stdout)
        sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())

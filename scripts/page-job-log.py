#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Page a chosen line window of a CI job's log through one call.

A cloud review run diagnosing a failing CI job fetches the job log with the GitHub
CLI, and every ad-hoc slice re-downloads the whole log because the review matcher
refuses the shell constructs (variable expansions, ANSI-C quoting, redirects) that
would slice it in one pass. This helper takes a flat argument list — a job id and a
line range as plain words — downloads the log at most once per run into `.prflow/tmp/`,
and slices the stored copy on every later call. It bounds and sanitizes what it prints
(attacker-influenceable log text is data, never instructions) and reports the log's
total extent and the stored path so the caller picks the next window from facts.

The stored copy is a point-in-time snapshot: a log first fetched while its job was still
running stays as fetched for the rest of the run, so `total_lines` and the served window
describe the snapshot, not the live job.

Usage:
    page-job-log.py <job-id> <start-line> <end-line>

`<job-id>` and both line numbers are positive integers; `<start-line>` <= `<end-line>`.
Line numbers are 1-based and inclusive. The GitHub CLI is resolved from the DEVFLOW_GH
environment variable, falling back to a bare `gh` (the repo's python resolver contract:
python callers read the env var and do not probe).

Exit codes (complete by construction):
    0  a slice was served — including an explicitly labelled empty window when the
       requested range lies wholly past the end of the log.
    1  the log download (or a store read/write) failed; stderr names the cause and no
       partial stored file remains.
    2  the argument list is not a job id plus a valid line range; stderr prints usage.
"""

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

PROG = "page-job-log"
MAX_LINES = 300          # at most this many lines served per invocation
MAX_LINE_CHARS = 500     # at most this many characters per served line (post-sanitize)

# CSI (ESC [ … final), OSC (ESC ] … BEL/ST), and simple two-byte ESC sequences. Stripping
# these before the control-character pass keeps a sanitized SGR-wrapped word ("red text")
# intact while removing the escape bytes an injected name could use to break rendering.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?]*[ -/]*[@-~]"      # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC … BEL or ST
    r"|\x1b[@-Z\\-_]"                  # other two-byte escapes
)


def _usage_die():
    # exit 2: the argument list is not a job id plus a valid line range.
    print(
        f"usage: {PROG}.py <job-id> <start-line> <end-line>  "
        "(positive integers; start <= end; 1-based inclusive)",
        file=sys.stderr,
    )
    sys.exit(2)


def _gh():
    # DEVFLOW_GH is the documented override the test suite stubs; else bare `gh`.
    # Python callers deliberately do not probe (CLAUDE.md resolver contract).
    return os.environ.get("DEVFLOW_GH") or "gh"


def _store_dir():
    # Anchored to the process cwd, which the working-directory contract fixes at the
    # repository root on the cloud review tiers (where this helper runs); a local run
    # anchors to the cwd it was invoked from. The store is the gitignored `.prflow/tmp/`.
    return Path.cwd() / ".prflow" / "tmp"


def _sanitize(line):
    line = _ANSI_RE.sub("", line)
    # Drop every control/format character (Unicode category starting with "C" — C0/C1
    # controls, DEL, format chars) except the tab, which is kept because `gh run view
    # --log` emits tab-separated group/step/timestamp prefixes worth preserving.
    # Bytes that were not valid UTF-8 arrived as U+FFFD (category So) and pass through inert.
    return "".join(
        ch for ch in line if ch == "\t" or not unicodedata.category(ch).startswith("C")
    )


def _force_utf8_streams():
    # Force stdout/stderr to UTF-8 so a non-ASCII log byte prints rather than raising on a
    # non-UTF-8-default locale (the repo-wide entry-path contract). Tolerate a stream with
    # no usable reconfigure.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    _force_utf8_streams()
    if len(argv) != 4:
        _usage_die()
    job, start_s, end_s = argv[1], argv[2], argv[3]
    # ASCII-only `[0-9]` (never a Unicode digit int() rejects) with `-?` for at most one
    # leading dash: a value accepted here always converts, so a malformed operand exits 2
    # here rather than raising ValueError from int() below (exit 1 + traceback).
    if not (re.fullmatch(r"[0-9]+", job)
            and re.fullmatch(r"-?[0-9]+", start_s)
            and re.fullmatch(r"-?[0-9]+", end_s)):
        _usage_die()
    start, end = int(start_s), int(end_s)
    if start < 1 or end < 1 or start > end:
        _usage_die()

    store_dir = _store_dir()
    stored = store_dir / f"job-log-{job}.log"

    if not stored.is_file():
        # First call for this job id: download the whole log exactly once. Write only on
        # success and via a temp-then-rename, so a failed fetch leaves no partial file.
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"{PROG}: could not create the log store {store_dir}: {exc}",
                  file=sys.stderr)
            return 1
        try:
            proc = subprocess.run(
                [_gh(), "run", "view", "--job", job, "--log"],
                capture_output=True,
            )
        except OSError as exc:
            print(f"{PROG}: could not run the GitHub CLI to fetch job {job}: {exc}",
                  file=sys.stderr)
            return 1
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", errors="replace").strip()
            print(
                f"{PROG}: log download failed for job {job} "
                f"(gh exit {proc.returncode}): {detail or 'no stderr from gh'}",
                file=sys.stderr,
            )
            return 1
        # Write the temp then rename, so a store-write failure leaves no partial file at
        # all — the temp is unlinked on any OSError, and exit 1 names the cause. The pid in
        # the name keeps two concurrent invocations for one job id off a shared temp.
        tmp = store_dir / f".job-log-{job}.log.{os.getpid()}.partial"
        try:
            tmp.write_bytes(proc.stdout)
            tmp.replace(stored)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            print(f"{PROG}: could not write the log store for job {job}: {exc}",
                  file=sys.stderr)
            return 1

    try:
        text = stored.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"{PROG}: could not read the stored log for job {job}: {exc}",
              file=sys.stderr)
        return 1
    all_lines = text.splitlines()
    total = len(all_lines)

    # Requested window clamped to the log's extent (1-based inclusive).
    empty_window = start > total
    if empty_window:
        served_lines = []
        served = "empty"
        line_cap = False
    else:
        clamp_end = min(end, total)
        requested = clamp_end - start + 1
        window = all_lines[start - 1:clamp_end][:MAX_LINES]
        served_lines = window
        served = f"{start}-{start + len(window) - 1}"
        line_cap = requested > MAX_LINES

    char_cap = False
    out_lines = []
    for ln in served_lines:
        san = _sanitize(ln)
        if len(san) > MAX_LINE_CHARS:
            san = san[:MAX_LINE_CHARS]
            char_cap = True
        out_lines.append(san)

    header = (
        f"{PROG} job={job} total_lines={total} served={served} "
        f"count={len(out_lines)} "
        f"line_cap={'applied' if line_cap else 'none'} "
        f"char_cap={'applied' if char_cap else 'none'} "
        f"empty_window={'yes' if empty_window else 'no'} "
        f"stored={stored}"
    )
    try:
        sys.stdout.write(header + "\n")
        for ln in out_lines:
            sys.stdout.write(ln + "\n")
        # Flush inside the guard so a broken pipe on a small (buffered) output is caught
        # here, not re-raised as a traceback at interpreter shutdown.
        sys.stdout.flush()
    except BrokenPipeError:
        # A downstream reader closed the pipe (e.g. `| head`); the slice WAS served, so this
        # is success, not a fetch failure. Redirect stdout to devnull so the interpreter's
        # flush-on-exit does not re-raise, then exit 0.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

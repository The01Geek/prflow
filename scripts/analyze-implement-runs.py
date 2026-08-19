#!/usr/bin/env python3
"""Compatibility entry point for implement-only workflow analysis."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from pathlib import Path
import os
import sys


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


if __name__ == "__main__":
    _force_utf8_streams()
    analyzer = Path(__file__).with_name("analyze-workflow-runs.py")
    try:
        os.execv(
            sys.executable,
            [sys.executable, str(analyzer), "--workflow", "implement", *sys.argv[1:]],
        )
    except OSError as exc:
        # execv only returns by failing. Report it in the devflow breadcrumb convention
        # rather than as a raw traceback, and name the analyzer that could not be run.
        print(f"devflow: implement-run-analysis: cannot run {analyzer}: {exc}", file=sys.stderr)
        sys.exit(1)

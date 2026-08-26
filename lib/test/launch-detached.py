#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""CLI launcher: run a command in a new session with default signal dispositions.

Issue #1216 (AC6). Runs a given command with SIGHUP/SIGINT/SIGQUIT/SIGTERM
restored to their default disposition in the child and the child placed in a new
session (so a signal delivered to the launcher's process group does not tear the
child down mid-run), and reports the child's real exit status rather than its
own. This is the way to run the suite (`lib/test/run.sh` /
`lib/test/run-parallel.sh`) without the suite's signal-trap assertions failing
spuriously and without the child dying from the launcher's group signals.

Usage: launch-detached.py <command> [args...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_launcher import run_detached

raise SystemExit(run_detached(sys.argv[1:]))

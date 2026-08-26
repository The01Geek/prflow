#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""CLI spawn shim: restore default signal dispositions, then exec the command.

Issue #1216. Placed between a job-control-off backgrounding shell and the real
command so the command inherits a working SIGINT/SIGQUIT disposition instead of
the SIG_IGN a `cmd &` hands it. Because it `execvp`s, the process identity is
preserved and `$!` in the spawning shell still names the exec'd command.

Usage: exec-with-default-signals.py <command> [args...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_launcher import exec_with_default_signals

exec_with_default_signals(sys.argv[1:])

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Compatibility entry point for :mod:`create_issue_eval`."""

import importlib.util
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "create_issue_eval", os.path.join(_SCRIPT_DIR, "create_issue_eval.py")
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("could not load scripts/create_issue_eval.py")
_implementation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_implementation)

for _name in dir(_implementation):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_implementation, _name)


if __name__ == "__main__":
    sys.exit(_implementation.main())

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


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _force_utf8_streams()
    sys.exit(_implementation.main())

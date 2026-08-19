#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Explicitly import one inventoried native Claude workflow transcript."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from workflow_flight_recorder import _run_git, import_inventory_session


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


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id")
    parser.add_argument(
        "--claude-projects-root",
        type=Path,
        default=Path.home() / ".claude/projects",
    )
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).with_name("workflow-flight-recorder-registry.json"),
    )
    return parser.parse_args()


def main() -> int:
    _force_utf8_streams()
    arguments = _arguments()
    repository_root = arguments.repo_root
    if repository_root is None:
        discovered = _run_git(Path.cwd(), "rev-parse", "--show-toplevel")
        repository_root = Path(discovered) if discovered else Path.cwd()
    try:
        bundle = import_inventory_session(
            arguments.session_id,
            arguments.claude_projects_root,
            repository_root,
            arguments.registry,
        )
    except (OSError, ValueError) as exc:
        print(f"import-workflow-transcript: {str(exc) or exc.__class__.__name__}", file=sys.stderr)
        return 1
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

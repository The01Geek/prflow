#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Inventory native Claude workflow transcripts without modifying them."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workflow_flight_recorder import (
    _run_git,
    inventory_native_transcripts,
    render_inventory_json,
    render_inventory_table,
)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
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
        result = inventory_native_transcripts(
            arguments.claude_projects_root,
            repository_root,
            arguments.registry,
        )
    except ValueError as exc:
        print(f"inventory-workflow-transcripts: {exc}", file=sys.stderr)
        return 1

    renderer = render_inventory_json if arguments.json else render_inventory_table
    sys.stdout.write(renderer(result))
    if result.summary["readable"] == 0:
        print("inventory-workflow-transcripts: no readable transcript scan was possible", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-open UserPromptSubmit entry point for workflow start manifests."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from pathlib import Path
import sys

from workflow_flight_recorder import fail_open_manifest_main


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
    raise SystemExit(
        fail_open_manifest_main(
            Path(__file__).with_name("workflow-flight-recorder-registry.json"),
            sys.stdin,
        )
    )

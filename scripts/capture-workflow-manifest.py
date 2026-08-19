#!/usr/bin/env python3
"""Fail-open UserPromptSubmit entry point for workflow start manifests."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from pathlib import Path
import sys

from workflow_flight_recorder import fail_open_manifest_main


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
    raise SystemExit(
        fail_open_manifest_main(
            Path(__file__).with_name("workflow-flight-recorder-registry.json"),
            sys.stdin,
        )
    )

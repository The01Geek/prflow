#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Write the /prflow:implement run-marker file, reading its owner id from the environment.

Phase 1.3 of the implement run writes `.prflow/tmp/implement-active-<n>` so the local-tier
Stop-hook guard (`lib/implement-stop-guard.sh`) can tell an in-flight run's marker from a
concurrent session's. The marker's first line is this run's owner — the session id — which the
guard compares like-with-like against the Stop payload's own `session_id`.

The owner is read here, from this process's own `CLAUDE_CODE_SESSION_ID`, rather than in a shell
fence: the Claude Code worktree-isolation classifier refuses the `printf '%s\\n' "$CLAUDE_CODE_SESSION_ID"`
expansion the phase file used to emit, leaving the marker empty and the guard blocking every
session in the checkout. This helper takes the marker path as its single positional argument and
writes it itself, so no phase fence expands the variable.

Behavior:

* id set and non-blank → the file's one line is the stripped id; exit 0.
* id unset, empty, or whitespace-only → an empty file, exit 0, and one stderr breadcrumb naming
  which of those three shapes was found (an empty marker forfeits owner identity, which the guard
  fails closed on — the caller records that outcome).
* the file cannot be written → exit 1 with a stderr breadcrumb naming the path. The parent
  directory is not created here: a missing parent is an unwritable-path failure, not a silent
  mkdir (the caller's `mkdir -p <scratch-dir>` owns directory creation).

The write truncates, so running twice on one path leaves one line, not two.

This helper is local-tier only (no cloud writer invokes it; it is granted in no cloud
profile), so it is deliberately absent from scripts/devflow-cloud-writer-contract.json — the
generator's cloud-writer closure excludes it, and adding it would break the issue-#1445
key-set equality check. Deviates from issue #42's AC10, which prescribed a manifest entry;
see the workpad AC-rewrite note.
"""
from __future__ import annotations

import argparse
import os
import sys

_ENV_NAME = "CLAUDE_CODE_SESSION_ID"


def _force_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8, idempotently and defensively. Called from the CLI entry
    path only (not at import) so importing this module for unit tests never mutates the
    importer's global streams (issue #1762). A breadcrumb this helper emits would otherwise
    raise UnicodeEncodeError under a non-UTF-8 ambient codec."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _breadcrumb(msg: str) -> None:
    print(f"write-run-marker: {msg}", file=sys.stderr)


def _owner_or_absent_shape() -> tuple[str | None, str | None]:
    """Return (owner, absent_shape). Exactly one is non-None: a non-blank stripped owner, or
    the name of the blank shape found — `unset`, `empty`, or `whitespace-only`."""
    raw = os.environ.get(_ENV_NAME)
    if raw is None:
        return None, "unset"
    if raw == "":
        return None, "empty"
    stripped = raw.strip()
    if not stripped:
        return None, "whitespace-only"
    return stripped, None


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        help="Absolute path of the run-marker file to write. Its parent directory must already "
        "exist — a missing parent is an unwritable-path failure, not a silent mkdir.",
    )
    args = parser.parse_args(argv)

    owner, absent_shape = _owner_or_absent_shape()
    content = f"{owner}\n" if owner is not None else ""
    try:
        with open(args.path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        _breadcrumb(f"could not write the run marker {args.path}: {exc}")
        return 1
    if absent_shape is not None:
        _breadcrumb(
            f"{_ENV_NAME} is {absent_shape}; wrote an empty run marker with no owner id "
            f"({args.path})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

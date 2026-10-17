#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Print the content-based candidate identity of the working tree.

`record` derives the identity through the importable scripts/reception_identity.py
(exactly one implementation of the identity format ships) and prints one JSON line,
`{"candidate_identity": "<git tree id>", "ok": true}`. It writes no output file, and the
derivation removes its temporary index.

Failures: `cmd_record` hands an `IdentityError` from the derivation to `_fail`, and
`main` hands it any other `Exception` the subcommand raises; `_fail` writes an
{"ok": false, "reason": …} line to stderr and returns 1. argparse handles argument errors.

Data-only besides git: no `gh` call, no network call, no PyYAML, and no decisive value
derived through a non-preflight PATH tool.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reception_identity as ri


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _fail(reason: str) -> int:
    sys.stderr.write(json.dumps({"ok": False, "reason": reason}) + "\n")
    return 1


def cmd_record(args) -> int:
    try:
        candidate_identity = ri.derive_candidate_identity(args.repo_root)
    except ri.IdentityError as exc:
        return _fail(f"identity:{exc.reason}")
    sys.stdout.write(
        json.dumps({"ok": True, "candidate_identity": candidate_identity}, sort_keys=True)
        + "\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reception-record.py",
        description="Print the working tree's content-based candidate identity.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_rec = sub.add_parser("record", help="Derive and print the candidate identity.")
    p_rec.add_argument("--repo-root", default=None,
                       help="Directory to derive from (default: the cwd); git "
                            "resolves the repository that contains it.")
    p_rec.set_defaults(func=cmd_record)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        return _fail(f"internal_error:{exc.__class__.__name__}")


if __name__ == "__main__":
    raise SystemExit(main())

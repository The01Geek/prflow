#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Refresh the Phase 3.1-placed ``[View run](...)`` line in a PR body.

Reads the PR body from stdin and takes the new run URL as ``argv[1]``; writes
the rewritten body to stdout. Rewrites **only** the ``[View run](...)`` line
that immediately follows a ``Resolves #`` line — the adjacency the Phase 3.1
draft-PR template emits (``skills/implement/phases/phase-3-review.md`` §3.1).
Any other ``[View run](`` occurrence a human added elsewhere (a Reviewer Notes
link, a code-block example) is preserved byte-for-byte.

Idempotent: re-running with the same URL reproduces the same body (the line is
replaced in place, never appended), so a second resume of the same run rewrites
the same line to the same URL with no duplication and no corruption.

Fail-closed caller contract (issue #493 empty-body hardening): a missing/empty
URL argument or empty stdin prints nothing and exits non-zero, so the caller's
non-empty guard skips the PATCH rather than blanking the PR body. The body/URL
round-trip is byte-faithful — ``split("\\n")``/``"\\n".join(...)`` adds and
removes no newline — so the caller's ``[View run](`` guard alone decides
whether a PATCH happens.
"""
import sys


def refresh(body, url):
    """Return *body* with the Resolves-anchored ``[View run](...)`` line set to *url*."""
    lines = body.split("\n")
    for i in range(1, len(lines)):
        if lines[i].startswith("[View run](") and lines[i - 1].startswith("Resolves #"):
            lines[i] = "[View run](" + url + ")"
    return "\n".join(lines)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    _force_utf8_streams()
    if len(sys.argv) < 2 or not sys.argv[1]:
        return 2
    body = sys.stdin.read()
    if not body:
        return 2
    sys.stdout.write(refresh(body, sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

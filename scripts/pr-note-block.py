#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Add or strip a stopped-run note block at the top of a PR body.

Reads the PR body from stdin, writes the transformed body to stdout. The block
is delimited by a matching HTML-comment marker pair so removal is exact:

    <!-- prflow:stopped-run-note-start -->
    <the note text, verbatim>
    <!-- prflow:stopped-run-note-end -->

Subcommands (argv[1]):

- ``add <note>`` — prepend a fresh note block carrying <note>, first stripping
  any block already present so a second add REPLACES rather than duplicates.
- ``strip`` — remove EVERY note block, returning a body with none byte-for-byte
  unchanged when it carried none.

Sanitizing on ``add``: any ``-->`` in <note> is rewritten to ``--&gt;`` so a
payload that contains the block's own end marker (which itself ends in ``-->``)
cannot close the comment early or plant a second strippable block.

Fail-closed caller contract (mirrors ``scripts/refresh-pr-run-link.py``): a
missing subcommand, empty stdin, or an ``add`` with a missing/empty note
argument prints nothing and exits non-zero, so the caller's non-empty-output
guard skips its PATCH rather than blanking the PR body. The body round-trip is
byte-faithful (``split("\\n")``/``"\\n".join(...)`` add and remove no newline).
"""
import sys

_START = "<!-- prflow:stopped-run-note-start -->"
_END = "<!-- prflow:stopped-run-note-end -->"


def strip_block(body):
    """Return *body* with every stopped-run note block (start..end inclusive, plus one
    trailing blank separator) removed. A body carrying none is returned unchanged."""
    lines = body.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i] == _START:
            j = i + 1
            while j < n and lines[j] != _END:
                j += 1
            if j < n:
                # Drop start..end inclusive, then one blank separator line if present,
                # so add()'s "block\n\nbody" prepend round-trips to the original body.
                i = j + 1
                if i < n and lines[i] == "":
                    i += 1
                continue
            # An unterminated start marker is not a block — leave it as ordinary text.
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def add_block(body, note):
    """Return *body* with a fresh stopped-run note block carrying *note* prepended,
    replacing any block already present (so a second add never duplicates)."""
    stripped = strip_block(body)
    safe = note.replace("-->", "--&gt;")
    block = f"{_START}\n{safe}\n{_END}"
    return block + "\n\n" + stripped if stripped else block


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call at import (it would mutate the streams
    of a process that imports this module for tests); tolerate a stream with no usable
    reconfigure."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    _force_utf8_streams()
    if len(argv) < 2:
        return 2
    cmd = argv[1]
    body = sys.stdin.read()
    if not body:
        return 2
    if cmd == "strip":
        sys.stdout.write(strip_block(body))
        return 0
    if cmd == "add":
        if len(argv) < 3 or not argv[2]:
            return 2
        sys.stdout.write(add_block(body, argv[2]))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

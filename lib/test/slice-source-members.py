#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Print the source members `devflow_copy_slice` requires, derived from the slice
itself (issue #1388).

Every synthetic installer/vendor test fixture has to build a source tree carrying
each member the slice copies, because the copy runs under `set -e` and aborts the
whole vendor before the tree lands. That list was transcribed by hand into three
separate fixtures, so adding one entry to the slice's `cp` list turned all three
red at once — and the #959 fixture's failure surfaced only in the `--with-floors`
exact-module-floors measurement, not the ordinary suite. Deriving the list here
makes the coupling mechanical: a new slice member appears in every fixture that
builds itself through `slice-source-fixture.sh` with no second edit.

Output is one member per line on stdout, each prefixed with its kind:

    dir<TAB>agents
    file<TAB>.prflow/config.example.json

A member is a FILE when its path under `$src/` has more than one segment (the
slice names those individually) and a DIRECTORY otherwise — which is the shape of
both `cp` calls in `devflow_copy_slice` and of either kind added later.

Fails closed: an unreadable slice, a missing `devflow_copy_slice` body, or a body
yielding no member exits non-zero with a diagnostic naming the slice, rather than
letting a caller build a fixture against an empty list that would then vacuously
pass. Never writes anything.
"""
import re
import sys
from pathlib import Path

SLICE = Path(".github/actions/vendor-plugin/vendor-slice.sh")

# A `"$src/<path>"` operand. The slice writes every source operand in this one
# quoted form; a differently-spelled operand yields no member and is caught by
# the empty-list refusal below rather than silently narrowing the fixture.
_SRC_OPERAND = re.compile(r'"\$src/([^"]+)"')


def members(text: str) -> list:
    """Return `(kind, path)` for each `$src/` operand in the copy-slice body."""
    start = text.find("devflow_copy_slice()")
    if start < 0:
        return []
    # The body ends at the first line that is a bare closing brace — the slice
    # keeps one function per such line, so this does not need a shell parser.
    end = text.find("\n}", start)
    body = text[start:] if end < 0 else text[start:end]
    out, seen = [], set()
    for path in _SRC_OPERAND.findall(body):
        path = path.rstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(("file" if "/" in path else "dir", path))
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    slice_path = root / SLICE
    try:
        text = slice_path.read_text(encoding="utf-8")
    except OSError as e:
        sys.stderr.write(f"slice-source-members.py: cannot read {slice_path}: {e}\n")
        return 2
    found = members(text)
    if not found:
        sys.stderr.write(
            f"slice-source-members.py: no \"$src/…\" operand found in "
            f"devflow_copy_slice in {slice_path}; refusing to report an empty "
            f"member list (a fixture built from it would pass vacuously)\n")
        return 2
    for kind, path in found:
        sys.stdout.write(f"{kind}\t{path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

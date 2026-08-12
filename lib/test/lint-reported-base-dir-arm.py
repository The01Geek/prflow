#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when an ENROLLED ``skills/**`` call site consumes an
``${CLAUDE_SKILL_DIR:-…}`` anchor expansion's VALUE directly (the resolve-once
fallback command) with NO reported-base-directory-first arm ahead of it (issue #1594).

Why this exists. Two skill bodies resolve their own ``<skill-dir>`` by running
``echo "${CLAUDE_SKILL_DIR:-…}"`` and consuming the printed path. That command is
refused on runners whose permission matcher denies the ``${VAR:-default}`` argument
expansion (recorded on cloud run ``30695072336``; observed locally too), so the skills
now resolve ``<skill-dir>`` from the base directory the runner reports in context FIRST
and keep the ``echo`` command only as the fallback. This lint keeps that ordering in
place: at each enrolled site the reported-base-directory-first arm — marked by the
``<!-- prflow:skill-dir-reported-base-first -->`` sentinel — must precede the
value-consuming anchor expansion.

MATCHED SHAPE (the thing that FAILS the lint). A *value-consuming* anchor expansion is
``${CLAUDE_SKILL_DIR:-<…>}"`` whose closing ``}"`` is NOT immediately followed by ``/`` —
i.e. the expansion's value is consumed as ``<skill-dir>`` rather than naming a helper
path (``…}"/../../scripts/<helper>``, the path-naming call sites, which this lint
never flags). A bare prose *mention* of the variable (no ``}"``) is likewise not matched
— the distinction the lint draws is invocation against mention, never fenced against
inline. Matching runs over a WHITESPACE-NORMALIZED copy of the file (`" ".join(split())`),
so the sentinel and the value-consuming expansion are located by the same flattened
offsets whether the call site is fenced or written inline mid-sentence inside a narrative
bullet, and a sentinel wrapped across adjacent lines is still found. A value-consuming
expansion with no sentinel at an earlier offset fails the lint, naming the file.

PASSES (each): a site whose value-consuming expansion has the sentinel ahead of it; a
site carrying no value-consuming expansion at all (nothing to require an arm for, e.g. a
file with only path-naming anchor uses). An empty enrolled inventory, a missing enrolled
file, and an unreadable enrolled file each fail closed — the enrollment asserts the call
site exists.

Exit status is 0 only when every enrolled file was read and every value-consuming
expansion at every enrolled site has the sentinel ahead of it. It is non-zero when an
enrolled site consumes an anchor value with no preceding arm, when an enrolled file is
missing or unreadable, or when the inventory is empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The enrolled call sites — the two skill bodies whose resolve-once clause keeps the
#: ``echo`` command as a value-consuming fallback. This is the one hand-maintained value:
#: which sites carry that fallback is a policy scope, not a fact derivable from the tree.
#: A future site that adopts the same fallback shape is enrolled by adding its path here.
ENROLLED: tuple[str, ...] = (
    "skills/implement/SKILL.md",
    "skills/review/SKILL.md",
)

#: The reported-base-directory-first sentinel that must precede a value-consuming anchor
#: expansion at an enrolled site.
_SENTINEL = "<!-- prflow:skill-dir-reported-base-first -->"

#: A value-consuming anchor expansion: ``${CLAUDE_SKILL_DIR:-<…>}"`` whose ``}"`` is NOT
#: followed by ``/`` (allowing whitespace the normalization pass may have left before it).
#: The negative lookahead is what separates it from a path-naming
#: ``…}"/../../scripts/<helper>`` invocation, which is left unflagged.
_VALUE_CONSUMING = re.compile(r'\$\{CLAUDE_SKILL_DIR:-[^}]*\}"(?!\s*/)')


def audit(root: Path, enrolled: tuple[str, ...] = ENROLLED) -> list[str]:
    """Return a list of human-readable failure messages (empty when clean)."""
    if not enrolled:
        return ["inventory is empty — the lint would be vacuous; refusing"]
    failures: list[str] = []
    for relpath in enrolled:
        try:
            text = (root / relpath).read_text(encoding="utf-8")
        except FileNotFoundError:
            failures.append(f"{relpath}: enrolled file is missing")
            continue
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{relpath}: enrolled file could not be read ({exc})")
            continue
        # Normalize whitespace so an inline-code call site mid-sentence and an expansion
        # wrapped across adjacent lines are matched identically to a fenced one.
        norm = " ".join(text.split())
        sentinel_idx = norm.find(_SENTINEL)
        # search() returns the earliest value-consuming match; if the single sentinel offset
        # precedes that earliest match it precedes every later one, so the first match alone
        # decides the file (a later restore to a whole-file loop would only re-express this).
        match = _VALUE_CONSUMING.search(norm)
        if match and (sentinel_idx == -1 or sentinel_idx > match.start()):
            failures.append(
                f"{relpath}: a value-consuming ${{CLAUDE_SKILL_DIR:-…}} anchor "
                "expansion consumes the anchor's value with NO reported-base-directory"
                f"-first arm (the '{_SENTINEL}' sentinel) ahead of it (issue #1594)"
            )
    return failures


def _load_inventory(path: Path) -> tuple[str, ...]:
    """Read an inventory override file: one enrolled relpath per line, blanks and
    ``#`` comment lines skipped. Exposes the inventory so the empty-inventory,
    missing-file, and unreadable-file arms are reachable from tests without editing
    this module's source."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(_REPO_ROOT),
        help="Repository root to audit (default: this file's repo root).",
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help="Override the enrolled inventory from a file (one relpath per line; "
        "blanks and '#' comments skipped). Lets tests reach the empty-inventory arm "
        "without editing this module.",
    )
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print the enrolled inventory and exit 0.",
    )
    args = parser.parse_args(argv)

    enrolled = ENROLLED
    if args.inventory is not None:
        enrolled = _load_inventory(Path(args.inventory))

    if args.print_inventory:
        for relpath in enrolled:
            print(relpath)
        return 0

    failures = audit(Path(args.root), enrolled)
    if failures:
        for msg in failures:
            print(f"lint-reported-base-dir-arm: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

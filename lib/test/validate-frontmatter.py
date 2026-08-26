#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Validate every ``agents/*.md`` + ``skills/**/SKILL.md`` YAML frontmatter block under a root.

Extracted from ``lib/test/run.sh``'s #671 packaging gate so the suite can drive each branch
against a fixture root (empty corpus, a frontmatter that does not parse, a frontmatter missing
a required key) rather than only observing the happy path over the real repo — the
"assert the guard fails closed, not just the happy path" convention in ``CLAUDE.md``.

Exit codes: 0 = every frontmatter parsed and carried the required keys; 1 = at least one
problem (each named on its own line); 3 = PyYAML unavailable (a hard preflight prerequisite,
so its absence is a loud failure, never a silent pass). A zero-file corpus is a problem, not a
clean pass ("unknown is not zero").
"""

from __future__ import annotations

import glob
import os
import re
import sys

REQUIRED_KEYS = {"name", "description"}


def validate(root: str) -> tuple[int, list[str]]:
    try:
        import yaml
    except Exception as exc:  # PyYAML is a hard preflight prerequisite.
        return 3, [f"PYYAML_MISSING: {exc}"]

    bad: list[str] = []
    files = sorted(
        glob.glob(os.path.join(root, "agents", "*.md"))  # tree-walk-ok: pattern is confined to agents/, which no worktree lives under
    ) + sorted(
        glob.glob(os.path.join(root, "skills", "**", "SKILL.md"), recursive=True)  # tree-walk-ok: pattern is confined to skills/, which no worktree lives under
    )
    for f in files:
        # Closed handle + named-path failure: an I/O or decode fault must stay inside this
        # helper's documented 0/1/3 vocabulary, never escape as a bare traceback.
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            bad.append(f"{f} (cannot read: {exc})")
            continue
        except UnicodeDecodeError as exc:
            bad.append(f"{f} (not valid UTF-8: {exc})")
            continue
        m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            bad.append(f + " (no frontmatter block)")
            continue
        try:
            d = yaml.safe_load(m.group(1))
        except yaml.YAMLError as exc:
            bad.append(f"{f} (YAML error: {exc})")
            continue
        if not isinstance(d, dict):
            bad.append(f + " (frontmatter is not a mapping)")
        elif not REQUIRED_KEYS <= set(d):
            bad.append(
                f"{f} (frontmatter missing required key(s): {sorted(REQUIRED_KEYS - set(d))})"
            )
    # "Unknown is not zero": an empty glob would otherwise pass green having validated nothing.
    if not files:
        bad.append(
            "no agent/skill frontmatter files matched (agents/*.md + skills/**/SKILL.md) — "
            "empty corpus, the glob found nothing to validate"
        )
    return (1 if bad else 0), bad


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = args[0] if args else "."
    rc, bad = validate(root)
    if rc == 3:
        print(bad[0])
        return 3
    if bad:
        print("BAD")
        for b in bad:
            print("  " + b)
        return 1
    # Count only the real frontmatter files (exclude the manifests, which this helper does not read).
    n = len(
        sorted(glob.glob(os.path.join(root, "agents", "*.md")))  # tree-walk-ok: pattern is confined to agents/, which no worktree lives under
        + sorted(glob.glob(os.path.join(root, "skills", "**", "SKILL.md"), recursive=True))  # tree-walk-ok: pattern is confined to skills/, which no worktree lives under
    )
    print(f"OK {n} frontmatter files parsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

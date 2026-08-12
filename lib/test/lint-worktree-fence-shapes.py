#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when an ENROLLED implement-bundle file carries a bash fence that
uses a shell expansion a worktree-isolated Claude Code session refuses (issue #1633).

Why this exists. An agent running ``/prflow:implement`` inside a Claude Code
worktree-isolated session cannot execute a bash fence that carries certain shell
expansions — the harness refuses the whole command outright rather than prompting,
so the agent improvises a decomposition and silently drops the fail-closed
exit-code routing the fence exists to carry. A 24-probe measurement in one such
session (recorded in issue #1633's Current Behavior) isolated the discriminator:
three constructs are refused, and every other multi-statement shape — sequences,
``&&``, conditionals, loops, redirects, pipes, ``cd`` — runs. This lint is the
regression backstop that keeps a new fence of the refused shape out of an enrolled
file, modelled on ``lib/test/lint-anchor-fallback-arm.py``'s enrollment-driven form.

THE REFUSED-EXPANSION SET (the closed candidate-construct set this lint detects).
Exactly three constructs, and no others, fail an enrolled fence:

  1. Command substitution — ``$(...)`` or the backtick form `` `...` ``.
  2. The exit-status parameter ``$?``.
  3. A reference to a shell variable BOUND WITHIN THE SAME FENCE — bound by
     assignment (``NAME=``), by an ``export NAME=`` assignment, by a ``for NAME in``
     or ``select NAME in`` loop header, or by a ``read [-flags] NAME`` — where the
     bound name is later referenced as ``$NAME`` / ``${NAME}`` anywhere in that same
     fence. Each bash fence is its own ``bash -c`` shell (issue #1537), so "the same
     command" is scoped to the fence. A binding with NO later reference is NOT a
     violation — the reference is what the session refuses — which is exactly the
     ``for i in 1 2; do echo $i; done`` (fails) vs ``for i in 1 2; do echo hi; done``
     (passes) pair the measurement separated. A bare environment variable the fence
     did not itself bind (``$ARGUMENTS``, ``$ISSUE_NUMBER``, ``$GITHUB_RUN_ID``) is
     NOT a refused expansion and passes.

This set is the DISCRIMINATOR the measurement isolated, NOT a documented harness
contract — see issue #1633's provenance note (24 observations, one macOS session,
one Claude Code version, no harness source read).

SHAPES THIS LINT DOES NOT DETECT (disclosed residuals, in the form
``lib/test/lint-anchor-fallback-arm.py``'s docstring uses):

  - Only ``bash``-info-string fenced blocks are scanned. A fence with no info
    string, or an info string other than ``bash`` (``sh``, ``console``, ``text``,
    none), is treated as prose/data and NOT scanned — the constructs are refused
    only when executed as a bash fence.
  - A QUOTED heredoc body (``<<'EOF'`` / ``<<"EOF"`` / ``<<\EOF``) is data, not
    executed expansion, so its lines are stripped before scanning. An UNQUOTED
    heredoc body IS scanned, because the shell expands it.
  - The scanner is line/text based, not a shell parser: it does not model quoting
    that would neutralise a construct (a literal ``$(`` inside single quotes is
    still flagged), nor arithmetic ``$((...))`` distinct from command substitution
    (``$((`` starts with ``$(`` and is flagged — an accepted conservative
    over-match; an enrolled fence needing arithmetic routes it through a helper).
  - Variable-binding detection covers ``NAME=``/``export NAME=``/``for``/``select``/
    ``read``; it does not model ``declare``/``local``/``mapfile``/``getopts`` or
    ``printf -v``. An enrolled fence using one of those is not caught here — the
    fence-isolation harness in ``lib/test/run.sh`` is the executable backstop.

The enrollment inventory ``ENROLLED`` is the SINGLE place the shipped enrolled set
is written down. A file outside it that carries a refused expansion passes (the
unmigrated surface stays legal). A ``--inventory-file`` override exists SOLELY for
this lint's own test harness (the empty-inventory, omits-one, and scratch-copy
positive-control cases); the built-in ``ENROLLED`` remains the shipped source.

Exit status is 0 only when every enrolled file was read and carries no refused
expansion in any bash fence. It is non-zero when an enrolled fence carries a
refused expansion (naming file, line, and construct), when an enrolled file is
missing or unreadable, or when the enrollment inventory is empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The shipped enrolled set — the SINGLE place it is written down. Each entry is a
#: repo-relative path to an implement-bundle file whose bash fences an implement run
#: executes. The four phase files issue #1633 names are the floor; the reference and
#: SKILL.md entries are the rest of the surface whose fences were migrated with them.
ENROLLED: tuple[str, ...] = (
    "skills/implement/phases/phase-1-setup.md",
    "skills/implement/phases/phase-2-implement.md",
    "skills/implement/phases/phase-3-review.md",
    "skills/implement/phases/phase-4-documentation.md",
)

#: The four files the AC requires the inventory to contain at minimum. A built-in (or
#: overridden) inventory that drops any of them is a mis-scoped audit and fails closed.
_REQUIRED: frozenset[str] = frozenset(ENROLLED)

# A ``bash`` fence opener: ``` ```bash ``` (optionally with trailing whitespace) at
# the start of the line. Info strings other than ``bash`` are not scanned.
_FENCE_BASH_OPEN = re.compile(r"^```bash[ \t]*$")
_FENCE_CLOSE = re.compile(r"^```[ \t]*$")
_FENCE_ANY_OPEN = re.compile(r"^```")

# A quoted heredoc redirection: ``<<`` (optionally ``-``) then a quoted or
# backslash-escaped delimiter word. Its body is data and is stripped before scanning.
_QUOTED_HEREDOC = re.compile(r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|\\(\w+))")
# An unquoted heredoc (whose body IS expanded, so it is scanned): ``<<WORD`` with a
# bareword delimiter. Used only to track the delimiter so the harness does not treat
# the body's own ``WORD`` terminator line as source.
_UNQUOTED_HEREDOC = re.compile(r"<<-?\s*(\w+)")

# Variable-binding recognisers (names bound within the fence).
_ASSIGN = re.compile(r"(?:^|;|\||&|\bexport\s+|\bdo\s+|\bthen\s+|\{\s+)\s*([A-Za-z_][A-Za-z0-9_]*)=")
_FOR_HEADER = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_SELECT_HEADER = re.compile(r"\bselect\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_READ_NAMES = re.compile(r"\bread\b((?:\s+-\S+)*)((?:\s+[A-Za-z_][A-Za-z0-9_]*)+)")

# Command substitution and the exit-status parameter.
_CMD_SUBST_DOLLAR = re.compile(r"\$\(")
_BACKTICK = re.compile(r"`")
_EXIT_STATUS = re.compile(r"\$\?")


def _strip_quoted_heredocs(lines: list[str]) -> list[str]:
    """Return ``lines`` with the bodies of quoted heredocs removed.

    A quoted-heredoc body is data the shell does not expand, so a construct inside
    it must not be flagged. An unquoted heredoc's body IS expanded and is retained;
    only its terminator line is dropped so the terminator word is not mis-scanned.
    """
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        qm = _QUOTED_HEREDOC.search(line)
        um = None if qm else _UNQUOTED_HEREDOC.search(line)
        if qm or um:
            delim = next(g for g in (qm.groups() if qm else um.groups()) if g)
            quoted = qm is not None
            i += 1
            while i < n:
                body = lines[i]
                if body.strip() == delim:
                    if not quoted:
                        # Retain an unquoted terminator line as a scanned line so its
                        # absence does not shift line numbers; but its own word is not
                        # a construct, so appending it is harmless.
                        out.append(body)
                    i += 1
                    break
                if not quoted:
                    out.append(body)
                # A quoted body line is dropped (data), but keep a placeholder so
                # reported line numbers stay aligned with the source file.
                else:
                    out.append("")
                i += 1
            continue
        i += 1
    return out


def _bound_names(fence_lines: list[str]) -> set[str]:
    """Collect every variable name bound within the fence."""
    names: set[str] = set()
    for line in fence_lines:
        for m in _ASSIGN.finditer(line):
            names.add(m.group(1))
        for m in _FOR_HEADER.finditer(line):
            names.add(m.group(1))
        for m in _SELECT_HEADER.finditer(line):
            names.add(m.group(1))
        for m in _READ_NAMES.finditer(line):
            for name in m.group(2).split():
                names.add(name)
    return names


def _reference_positions(line: str, names: set[str]) -> bool:
    """True when ``line`` references any name in ``names`` as ``$NAME``/``${NAME}``."""
    if not names:
        return False
    for m in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", line):
        if m.group(1) in names:
            return True
    return False


def _scan_fence(fence_lines: list[str], start_lineno: int) -> list[tuple[int, str]]:
    """Return ``(lineno, construct)`` findings for one fence's lines.

    ``start_lineno`` is the 1-based file line number of the fence's first body line.
    """
    findings: list[tuple[int, str]] = []
    bound = _bound_names(fence_lines)
    for offset, line in enumerate(fence_lines):
        lineno = start_lineno + offset
        if _CMD_SUBST_DOLLAR.search(line) or _BACKTICK.search(line):
            findings.append((lineno, "command substitution ($(...) or backticks)"))
        if _EXIT_STATUS.search(line):
            findings.append((lineno, "exit-status parameter $?"))
        if _reference_positions(line, bound):
            findings.append((lineno, "reference to a variable bound within the same fence"))
    return findings


def _scan_file(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, construct)`` findings across every bash fence in ``text``."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    findings: list[tuple[int, str]] = []
    i = 0
    n = len(lines)
    while i < n:
        if _FENCE_BASH_OPEN.match(lines[i]):
            body_start = i + 1
            j = body_start
            while j < n and not _FENCE_CLOSE.match(lines[j]):
                j += 1
            fence_lines = lines[body_start:j]
            scanned = _strip_quoted_heredocs(fence_lines)
            findings.extend(_scan_fence(scanned, body_start + 1))
            i = j + 1
            continue
        if _FENCE_ANY_OPEN.match(lines[i]):
            # A non-bash fence: skip to its close without scanning (data/prose).
            j = i + 1
            while j < n and not _FENCE_CLOSE.match(lines[j]):
                j += 1
            i = j + 1
            continue
        i += 1
    return findings


def audit(root: Path, inventory: tuple[str, ...]) -> list[str]:
    """Return human-readable failure messages (empty when clean)."""
    failures: list[str] = []
    if not inventory:
        return ["inventory is empty — the lint would audit nothing; refusing"]
    missing_required = _REQUIRED - set(inventory)
    if missing_required:
        failures.append(
            "inventory omits required file(s): " + ", ".join(sorted(missing_required))
        )
    for relpath in inventory:
        path = root / relpath
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            failures.append(f"{relpath}: enrolled file is missing")
            continue
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{relpath}: enrolled file could not be read ({exc})")
            continue
        for lineno, construct in _scan_file(text):
            failures.append(f"{relpath}:{lineno}: refused expansion — {construct}")
    return failures


def _load_inventory(inventory_file: str | None) -> tuple[str, ...]:
    """Return the inventory to audit.

    The default is the built-in ``ENROLLED``. ``--inventory-file`` (the test-only
    override) reads one repo-relative path per non-blank, non-``#`` line.
    """
    if inventory_file is None:
        return ENROLLED
    lines = Path(inventory_file).read_text(encoding="utf-8").splitlines()
    return tuple(
        s.strip() for s in lines if s.strip() and not s.strip().startswith("#")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(_REPO_ROOT),
        help="Repository root to audit (default: this file's repo root).",
    )
    parser.add_argument(
        "--inventory-file",
        default=None,
        help="TEST-ONLY: read the enrolled inventory from this file (one repo-relative "
        "path per line) instead of the built-in ENROLLED. The shipped enrolled set is "
        "always the built-in tuple.",
    )
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print the built-in enrolled inventory and exit 0.",
    )
    args = parser.parse_args(argv)

    if args.print_inventory:
        for relpath in ENROLLED:
            print(relpath)
        return 0

    try:
        inventory = _load_inventory(args.inventory_file)
    except OSError as exc:
        print(f"lint-worktree-fence-shapes: could not read --inventory-file: {exc}", file=sys.stderr)
        return 1

    failures = audit(Path(args.root), inventory)
    if failures:
        for msg in failures:
            print(f"lint-worktree-fence-shapes: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a `!`-negated compound command carries a data-carrying
redirect on the compound itself.

Why this exists (issue #1524): bash does not propagate a redirection failure on a
compound command through `!`. Both `if ! { …; } > "$f"` and `if ! ( … ) > "$f"`
read as **success** when the redirect itself cannot open, so the arm written to
handle that failure never runs — a silent data-loss defect ShellCheck 0.11.0 does
not catch at this repo's `--severity=warning -e SC1091` setting. The correct idiom
captures the status instead: `rc=0; { …; } > "$f" || rc=$?; if [ "$rc" -ne 0 ]`.

Detected shape (deliberately narrow, to keep false positives to zero):

* A group opener `{` or `(` **immediately preceded by `!`** (`! {`, `! (`,
  `if ! {`). A `!` further from the opener is not tracked — a false negative this
  guard accepts, because every real instance of the defect writes `! {` / `! (`.
* whose matching close (`}` / `)`, brace/paren nesting balanced) is **immediately
  followed on the same physical line** by a data-carrying redirect: an optional fd
  number, then `>`, `>>`, or `<` (never `>&` / `<&`, which dup a descriptor and open
  no file), to a target that is not `/dev/null` (a redirect to `/dev/null` cannot
  meaningfully fail to open, so the swallowed-failure defect does not apply).

A redirect placed **inside** the group (`{ printf … > "$f" && mv …; }`) is correct —
the group's own exit status carries that failure — and its close is followed by `;`
or `then`, not a redirect, so it is not flagged.

Escape hatch: a `# negated-compound-redirect-ok: <reason>` marker on the line
immediately above the opener, the opener's own physical line, or the close's
physical line suppresses that finding.

Scope: shell sources only (`*.sh`, `*.bash`) — every live instance the issue's
sweep found lives in one. Embedded shell in `.github/workflows/*.yml` is an accepted
residual (the one workflow instance the sweep found puts its redirect inside the
group). `.claude/worktrees/` is excluded because the population is a working-tree
enumeration that would otherwise sweep sibling worktrees (issue #711), and this
lint's own fixture corpus (which carries intentional violations) is excluded.

Usage:
    lint-negated-compound-redirect.py [--root DIR] [--files-from PATH]

Exit status is 0 only when every selected file was read and none violated the rule;
non-zero on a violation, an unusable enumeration, or an unreadable selected path —
callers distinguish the three by reading the report, never the exit code.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

_POP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lint_population.py")
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
_pop_spec.loader.exec_module(_pop)
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_WORKING_TREE",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"lint-negated-compound-redirect: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

#: Only shell sources are scanned; see the module docstring for why `.yml` is a residual.
SCANNED_SUFFIXES = (".sh", ".bash")

#: Path prefixes never read. This lint's own fixtures carry intentional violations, and
#: the working-tree enumeration would otherwise reach sibling worktrees (issue #711).
EXCLUDED_PREFIXES = (
    "lib/test/fixtures/lint-negated-compound-redirect/",
    ".claude/worktrees/",
)

_MARKER = "negated-compound-redirect-ok:"

#: A redirect immediately following a group close: optional fd digits, then `>`/`>>`/`<`,
#: NOT a `>&`/`<&` descriptor dup, then the target. Anchored at the start of the
#: post-close remainder (leading horizontal whitespace already consumed by the caller).
_REDIRECT = re.compile(r"^[0-9]*(?:>>|>|<)(?![&])[ \t]*(?P<target>[^ \t;&|)]+)")


def is_scanned(path: str) -> bool:
    """True when `path` is a shell source that survives the exclusions."""
    normalized = path.replace("\\", "/")
    if any(normalized.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    return normalized.endswith(SCANNED_SUFFIXES)


def _blank_noise(text: str) -> str:
    """Return `text` with quoted spans and `#` comments replaced by spaces, preserving
    every character position and every newline. Structural characters (`{ } ( ) ! > <`)
    outside quotes/comments are kept so the scanner reads real shell structure rather
    than literals inside strings (e.g. the `! (` in an assertion message)."""
    out: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\n":
                out.append("\n")
            elif quote == '"' and c == "\\" and i + 1 < n and text[i + 1] != "\n":
                out.append("  ")
                i += 2
                continue
            elif c == quote:
                quote = None
                out.append(" ")
            else:
                out.append(" ")
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            out.append(" ")
            i += 1
            continue
        if c == "#":
            # A `#` starts a comment only at a token boundary (start of line, or after
            # whitespace / a command separator / a group opener). Otherwise it is literal
            # (e.g. `${x#prefix}` already lost its `$`/`{` to nothing here, but `a#b` is a word).
            # Every entry appended to `out` is a non-empty string, so the previous emitted
            # character is just the last entry's last character.
            pc = out[-1][-1] if out else None
            if pc is None or pc in " \t\n;&|(){":
                while i < n and text[i] != "\n":
                    out.append(" ")
                    i += 1
                continue
            out.append("#")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _line_of(text: str, index: int) -> int:
    """1-based physical line number of `index` in `text`."""
    return text.count("\n", 0, index) + 1


def _match_close(blanked: str, open_index: int, open_ch: str) -> int | None:
    """Return the index of the balanced close for the group opened at `open_index`,
    or None if unbalanced (a defensive fail-open: an unbalanced source is not flagged)."""
    close_ch = "}" if open_ch == "{" else ")"
    depth = 0
    i = open_index
    n = len(blanked)
    while i < n:
        c = blanked[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


#: A negated group opener: `!` then whitespace then `{` or `(`. The `{` form needs a
#: following whitespace/newline to be a brace group (`{a` is a word); the `(` form does not.
_NEGATED_OPEN = re.compile(r"!\s*(?:\{(?=[\s])|\()")


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return (line number, offending snippet) for each negated compound whose close
    carries a data-carrying non-`/dev/null` redirect and that is not marker-suppressed."""
    blanked = _blank_noise(text)
    raw_lines = text.split("\n")
    findings: list[tuple[int, str]] = []
    for m in _NEGATED_OPEN.finditer(blanked):
        open_ch = "{" if blanked[m.end() - 1] == "{" else "("
        open_index = m.end() - 1
        close_index = _match_close(blanked, open_index, open_ch)
        if close_index is None:
            continue
        # The redirect must sit on the SAME physical line as the close; consume only
        # horizontal whitespace after it before testing for a redirect operator. The
        # redirect operator and its target are read from the ORIGINAL text, not the blanked
        # copy — a quoted target ("$f") is blanked to spaces and would read as empty — and
        # the positions align because _blank_noise preserves every character position.
        after = close_index + 1
        j = after
        while j < len(text) and text[j] in " \t":
            j += 1
        rmatch = _REDIRECT.match(text[j:])
        if not rmatch:
            continue
        target = rmatch.group("target")
        if target.startswith("/dev/null"):
            continue
        open_line = _line_of(text, open_index)
        close_line = _line_of(text, close_index)
        # Marker escape hatch: the line immediately above the opener (a natural annotation
        # comment), the opener's own line (a trailing comment), or the close's line.
        marker_lines = {open_line - 1, open_line, close_line}
        if any(_MARKER in raw_lines[ln - 1] for ln in marker_lines if 1 <= ln <= len(raw_lines)):
            continue
        snippet = raw_lines[close_line - 1].strip() if 1 <= close_line <= len(raw_lines) else ""
        findings.append((close_line, snippet))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a !-negated compound command carries a data-carrying redirect on "
            "the compound (issue #1524): bash does not propagate the failed redirect through !."
        )
    )
    _pop.add_population_arguments(parser)
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-negated-compound-redirect")

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_WORKING_TREE,
        )
    except EnumerationError as exc:
        print(f"lint-negated-compound-redirect: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    audited = [path for path in population if is_scanned(path)]

    findings: list[str] = []
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=True)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        read_ok += 1
        for number, snippet in scan_text(text):
            findings.append(
                f"{relative}:{number}: a !-negated compound carries a redirect on the "
                f"compound ({snippet}) — bash swallows the failed redirect through !; "
                f"capture the status instead (rc=0; {{ … }} > f || rc=$?), or mark with "
                f"# {_MARKER} <reason>"
            )

    for finding in findings:
        print(finding)
    for relative, reason in skipped:
        print(f"lint-negated-compound-redirect: SKIPPED {relative}: {reason}", file=sys.stderr)
    print(
        f"lint-negated-compound-redirect: audited {read_ok} of {len(audited)} files"
        + (f" ({len(skipped)} skipped)" if skipped else "")
    )
    if skipped:
        print(
            f"lint-negated-compound-redirect: {len(skipped)} selected path(s) could not be "
            "audited — refusing to report clean; see the SKIPPED lines above",
            file=sys.stderr,
        )
        return 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

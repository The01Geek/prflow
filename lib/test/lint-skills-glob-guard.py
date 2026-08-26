#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a fenced shell block under `skills/` expands an unquoted
filename pattern that has neither a zsh `nomatch` guard nor a declaration marker.

Why this exists (issue #1211). A fenced shell block in a skill file is prose an
agent runs verbatim, in whatever shell the agent's harness gives it — commonly
**zsh**, not bash. zsh's default `nomatch` makes an unmatched glob a hard refusal
of *that one command*: it prints `zsh: no matches found: <pattern>` to stderr and
skips the command, then carries on with the rest of the block (it aborts the whole
block only under `set -e`, which no skill fence sets). The harm is therefore not a
dead block — it is a **silently empty enumeration**: the step that was supposed to
list something produces no output at all, and the surrounding prose cannot tell
"there is nothing here" from "the shell declined to look". A skill that works in
this repository can answer the wrong question in a consumer's repository purely
because a directory that exists here does not exist there.

The standard remedy, already used in this repository, is one line placed next to
the glob inside the same block:

    [ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :

It turns the behaviour off under native zsh and is an exact no-op everywhere else
(`$ZSH_VERSION` is unset, so `&&` short-circuits and `|| :` holds the exit status
at zero).

**This guard is deliberately narrow, and claims nothing more.** Telling a real
shell glob apart from prose that merely looks like one is the parsing problem
issue #644 had to solve for the documentation-path extractor, and a check that
tries to catch every case produces false alarms and gets switched off. So the
candidate shape is closed by enumeration below, and everything outside it is an
accepted, disclosed miss — never a claim of completeness.

Audited population, closed by enumeration:

* the tracked `*.md` files under `skills/`, sourced from an index-reading
  `git ls-files` with no `--others` (issue #711: a repository-root-anchored
  recursive walk descends into every sibling worktree under `.claude/worktrees/`
  and reports a number that varies between runs on the same commit).
* `agents/**` is a shipped prompt surface too and is deliberately NOT audited — a
  disclosed scope limit, not an oversight. It carries no violation today, so the
  limit is currently inert; widening the population is a separate decision.

Candidate shape, closed by enumeration — ALL of these must hold:

* the line sits inside a fenced block whose info string's first word is one of
  `bash`, `sh`, `shell`, `zsh` (an untagged or differently-tagged fence is not
  audited);
* the line is not inside a **quoted** heredoc body (data the shell never expands),
  and its `#`-introduced trailing comment has been stripped quote-aware before the
  scan — prose in a comment is not a command;
* the line contains a whitespace-delimited token lying wholly **outside** every
  single- and double-quoted span, that carries a `*` **and** a `/`. Requiring the
  `/` is what keeps `--include=*.py`, `Bash(gh:*)` and bare `*)` out of the
  candidate set; requiring the token to be outside quotes is what keeps
  `find . -name "*.sql"` — and a pattern in the *interior* of a multi-word quoted
  string — out, since a quoted pattern is never expanded by the shell;
* the token contains no `(`, `)` or `$`. **This is false-alarm reduction, not a
  claim about the shell** — `ls -d $ROOT/dir/*/` IS globbed, and zsh refuses it
  exactly like a bare pattern. The exclusion buys three things cheaply: a
  permission-grant literal written in prose (`Bash(lib/test/run.sh:*)`) and a
  `case` branch label (`*)`, `''|*[!0-9]*)`, `claude/issue-*|issue-*)` — every
  label ends in `)`) stop being candidates, which is what makes a separate
  `case`-branch predicate unnecessary. What it costs is the parameter-expansion
  residual disclosed below;
* the token contains no `**` — markdown emphasis written inside a fence
  (`**Relevant Classes/Files**`) is not a pattern any skill fence's shell expands,
  since POSIX shells have no `**` operator and bash gives it recursive meaning only
  under `shopt -s globstar`, which no skill fence sets.

Accepted residuals, stated rather than papered over — this list is the single home
for them, so `CLAUDE.md` points here rather than carrying a second copy:

* a glob whose token also carries a parameter expansion or a quoted leading
  segment — `$ROOT/dir/*/`, `"$ROOT"/dir/*/`. These are **real, globbed patterns**
  that zsh refuses; the narrow shape deliberately does not see them, because the
  filters that exclude prose literals and `case` labels exclude these too. It is
  the largest disclosed miss, and it is the commonest real shape in this
  repository, so a fence built that way still needs the guard by hand;
* a glob assembled through a variable;
* a glob inside an untagged fence, or inside a blockquoted (`> `-prefixed) fence;
* a glob inside a **nested** fence — a fenced block quoted inside another fenced
  block desyncs the open/close parity. A file whose parity never re-syncs ends
  inside an unterminated fence, which this guard detects and reports as a SKIP
  (fail-closed), so the desync is loud rather than a false clean; a file whose
  parity re-syncs later is a silent miss for the affected span;
* a glob written with `?` or `[…]` and no `*`;
* a backslash-escaped quote (`echo "a \" b"`), which misaligns the single-line
  quote mask for the rest of that line;
* a glob with **no path separator** (`wc -l *.py`) — zsh refuses that one too, but
  requiring the `/` is what keeps `--include=*.py` and `Bash(gh:*)` out, and that
  trade is taken deliberately;
* a heredoc whose quoted delimiter is not identifier-shaped (`<<'MY-EOF'`), whose
  body is therefore scanned as code;
* a `#` inside an unterminated multi-line quoted string, where the single-line
  comment strip mis-reads the line;
* a `# glob-ok:` marker text appearing inside a quoted string on the same line,
  which discharges that line — the marker is deliberately read from the RAW line
  (stripping the comment would remove the declaration along with it).

The written convention in `CLAUDE.md` is the primary control; this check is the
narrow mechanical backstop for the commonest shape.

Violation condition: a candidate token whose line carries no `# glob-ok: <reason>`
marker and whose fence carries no `setopt nonomatch` guard on an earlier line (the
guard is matched against the comment-stripped, unquoted code, so a *commented or
quoted* mention of the remedy does not stand in for it — an unquoted, uncommented
`echo setopt nonomatch` still would, a disclosed residual). The guard never judges what a marker's reason claims —
what it buys is a reviewable, greppable declaration at the desk, exactly like the
sibling markers `# structural-pin-ok:`, `# tree-walk-ok:`, `# pruned-path-ok:` and
`# argjson-ok:`.

Usage:
    lint-skills-glob-guard.py [--root DIR] [--files-from FILE]

Exit 0 when the audited population is clean, 1 on a violation or a refusal to
audit (fail closed — an unusable population is never reported as clean).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

TOOL = "lint-skills-glob-guard"

# The population enumeration, the file reader, the `EnumerationError` fail-closed
# contract, and the `--root` / `--files-from` preamble are shared with the other
# `git ls-files` lints (issue #724), imported by path with the idiom those files use.
# Assert the names this file uses at LOAD time so a rename fails here naming the
# dependency, not mid-scan.
_POP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lint_population.py")
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
_pop_spec.loader.exec_module(_pop)
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_INDEX",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"{TOOL}: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

# The marker must carry a NON-EMPTY reason — the `(\S.*?)` shape the repo's other
# declaration markers use. A bare `# glob-ok:` with nothing after it is not a
# declaration and does not discharge a violation.
MARKER = "# glob-ok:"
MARKER_RE = re.compile(r"#\s*glob-ok:\s*(\S.*?)\s*$")
ZSH_GUARD = "setopt nonomatch"
SHELL_INFO_WORDS = {"bash", "sh", "shell", "zsh"}
# A quoted heredoc introducer: `<<'EOF'` / `<<"EOF"` / `<<-'EOF'`. A heredoc body is
# data the shell never expands as a filename pattern, so it is skipped to the closing
# delimiter. Only the QUOTED form is recognised — an unquoted heredoc still undergoes
# expansion, and the narrow shape makes no claim about it either way.
_HEREDOC = re.compile(r"<<-?\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\1")


def is_audited(relative: str) -> bool:
    """The audited population: tracked markdown under `skills/`."""
    return relative.startswith("skills/") and relative.endswith(".md")


def _scan_quotes(line: str) -> tuple[str, list[bool]]:
    """Walk a line once, returning its comment-stripped code and a per-character
    "this character sits inside a quoted span" mask over that code.

    One walk serves the three consumers that all need the same answer — the
    trailing-comment strip, the token filter, and the heredoc-introducer test —
    so they cannot disagree about where the quotes are. Without the comment
    strip, a line reading `ls . # see docs/site/*/ for the layout` reports a
    violation for a pattern the shell never sees; without the mask, a pattern in
    the interior of a multi-word quoted string (`echo "see docs/site/*/ here"`)
    carries no quote character of its own and is flagged the same way.

    Single-line only, which is all the narrow shape needs: a `#` or a quote
    inside an unterminated multi-line string is an accepted, disclosed residual.
    """
    quote = ""
    code: list[str] = []
    quoted: list[bool] = []
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            # A backslash-escaped character never opens or closes a quote. Without
            # this, `echo "a \" b"` toggles the state and masks the rest of the line
            # as quoted, hiding a real glob after it (fail-open).
            escaped = False
            code.append(char)
            quoted.append(bool(quote))
            continue
        if char == "\\" and quote != "'":
            escaped = True
            code.append(char)
            quoted.append(bool(quote))
            continue
        if quote:
            code.append(char)
            quoted.append(True)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
            code.append(char)
            quoted.append(True)
            continue
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        code.append(char)
        quoted.append(False)
    return "".join(code), quoted


def _unquoted_tokens(code: str, quoted: list[bool]) -> list[str]:
    """Whitespace-delimited tokens of `code` that lie wholly outside every quoted
    span — a textual approximation of shell word-splitting, which is all the narrow
    candidate shape needs; it never has to reconstruct what the shell would run.
    """
    tokens: list[str] = []
    start = 0
    length = len(code)
    while start < length:
        if code[start].isspace():
            start += 1
            continue
        end = start
        while end < length and not code[end].isspace():
            end += 1
        if not any(quoted[start:end]):
            tokens.append(code[start:end])
        start = end
    return tokens


def _candidate_tokens(code: str, quoted: list[bool]) -> list[str]:
    found = []
    for token in _unquoted_tokens(code, quoted):
        if "*" not in token or "/" not in token:
            continue
        if any(ch in token for ch in "()$"):
            continue
        if "**" in token:
            # Markdown emphasis inside a fence (`**Relevant Classes/Files**`), not a
            # pattern the shell expands: POSIX shells have no `**` operator, and bash
            # gives it recursive meaning only under `shopt -s globstar`, which no skill
            # fence sets. This is the named false-alarm class the narrow shape excludes.
            continue
        found.append(token)
    return found


def scan_file(text: str, path: str) -> tuple[list[str], bool]:
    """Return (one violation string per offending line, unclosed-fence-at-EOF).

    The second member is the honest-coverage signal. A **nested** fence — a fenced
    block quoted inside another fenced block, which several skill bodies carry —
    desyncs the open/close parity, after which every later fence in the file is
    read inside-out and its shell lines are never examined. A file whose parity
    never re-syncs ends inside an unterminated fence, and reporting `audited N of
    N` over it would be precisely the "audited nothing reads as audited
    everything, found nothing" failure this whole change exists to remove. So the
    caller treats it as a SKIP, which already fails closed.
    """
    violations: list[str] = []
    in_fence = False
    fence_is_shell = False
    fence_marker = ""
    fence_guarded = False
    heredoc_delimiter = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # A fence delimiter carries at most three leading spaces (CommonMark); four or
        # more makes the line literal content. That rule is what keeps a fence QUOTED
        # inside another fence — several skill bodies indent an inner ```bash block by
        # four spaces — from desyncing the open/close parity and silently taking the
        # rest of the file out of the scan.
        is_delimiter = len(line) - len(line.lstrip(" ")) <= 3
        if not in_fence:
            if is_delimiter and (stripped.startswith(("```", "~~~"))):
                fence_marker = stripped[0] * 3
                info = stripped.lstrip("`~").split()
                in_fence = True
                fence_is_shell = (info[0].lower() if info else "") in SHELL_INFO_WORDS
                fence_guarded = False
                heredoc_delimiter = ""
            continue
        if is_delimiter and stripped.startswith(fence_marker) and stripped.strip("`~") == "":
            in_fence = False
            continue
        if not fence_is_shell:
            continue
        if heredoc_delimiter:
            if stripped == heredoc_delimiter:
                heredoc_delimiter = ""
            continue
        code, quoted = _scan_quotes(line)
        # The guard is read from the COMMENT-STRIPPED, unquoted code, never the raw
        # line: prose that merely NAMES the remedy ("we deliberately do not use
        # setopt nonomatch here") would otherwise discharge every later glob in the
        # fence — a guard that looks present and checks nothing, which is the exact
        # failure signature this whole change exists to remove.
        guard = code.find(ZSH_GUARD)
        if guard != -1 and not any(quoted[guard : guard + len(ZSH_GUARD)]):
            fence_guarded = True
            continue
        # The marker, by contrast, IS read from the raw line — stripping the trailing
        # comment would remove the declaration along with the prose it introduces.
        declared = bool(MARKER_RE.search(line))
        heredoc = _HEREDOC.search(code)
        # An introducer inside a quoted string is a mention, not a heredoc; honouring
        # it would skip the rest of the fence (fail-open) waiting for a delimiter line
        # that never arrives. Only the `<<` position is tested — the delimiter's own
        # quotes are quote characters by construction, so testing the whole match
        # would reject every real quoted heredoc.
        if heredoc and not quoted[heredoc.start()]:
            heredoc_delimiter = heredoc.group(2)
        if not code.strip():
            continue
        tokens = _candidate_tokens(code, quoted)
        if not tokens:
            continue
        if fence_guarded or declared:
            continue
        violations.append(
            f"{path}:{lineno}: unguarded filename pattern {tokens[0]!r} in a "
            f"shell fence — add the `[ -n \"${{ZSH_VERSION:-}}\" ] && setopt "
            f"nonomatch || :` guard beside it, or declare it with "
            f"`{MARKER} <reason>`"
        )
    return violations, in_fence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a skills/ shell fence expands an unguarded filename pattern (issue #1211)."
    )
    _pop.add_population_arguments(parser)
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool=TOOL)

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except _pop.EnumerationError as exc:
        print(f"{TOOL}: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    audited = [path for path in population if is_audited(path)]
    if not audited:
        # `enumerate_population` fails closed only on a PRE-filter empty set. A
        # population that survives enumeration but has nothing under `skills/` is
        # equally an unestablished measurement — a caller scoping the run to a
        # changed-file list would otherwise get a green run over nothing.
        print(
            f"{TOOL}: enumeration yielded {len(population)} path(s) but none under "
            "skills/ — refusing to report clean over an empty audited population",
            file=sys.stderr,
        )
        return 1

    violations: list[str] = []
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=False)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        file_violations, unclosed = scan_file(text, relative)
        if unclosed:
            # Not counted in read_ok: the file was read but not reliably scanned.
            skipped.append(
                (relative, ("unterminated code fence at EOF — fence parity desynced "
                 "(a nested fence?), so this file's shell lines were not reliably scanned"))
            )
            continue
        read_ok += 1
        violations.extend(file_violations)

    for violation in violations:
        print(f"{TOOL}: {violation}", file=sys.stderr)
    for relative, reason in skipped:
        print(f"{TOOL}: SKIPPED {relative}: {reason}", file=sys.stderr)
    print(f"{TOOL}: audited {read_ok} of {len(audited)} files")
    if skipped:
        # A path that could not be read is an UNESTABLISHED measurement, never a
        # clean one — fail closed rather than report coverage the scan never had.
        print(
            f"{TOOL}: {len(skipped)} selected path(s) could not be audited — "
            "refusing to report clean",
            file=sys.stderr,
        )
        return 1
    if violations:
        print(
            f"{TOOL}: {len(violations)} unguarded pattern(s) in {read_ok} file(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

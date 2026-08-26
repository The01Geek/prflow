#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a `gh api` REST path is addressed through the
`$GITHUB_REPOSITORY` environment variable on a surface that can run outside
GitHub Actions.

Why this exists (issue #664): the variable is produced by the Actions runner and
has no producer on the local/interactive tier, so an interpolated path collapses
to `repos//issues/…`. `gh` then writes the HTTP error body to **stdout**, which a
best-effort `VAR=$(gh api … 2>/dev/null || true)` capture happily stores — so a
downstream `[ -n "$VAR" ]` guard is satisfied by a 404 blob rather than an id.
The correct idiom is the `{owner}/{repo}` placeholder pair, which `gh` fills from
the git remote on both tiers.

Scope boundaries, all deliberate and each asserted by a fixture in the suite:

* The audited population excludes `lib/test/`, `docs/`, `.github/workflows/`,
  `.github/actions/`, `.prflow/logs/`, `.prflow/learnings/`, `.changeset/`,
  and `CHANGELOG.md`. `lib/test/` carries the `#466` pin literal; `docs/` and
  `CHANGELOG.md` carry the rule's own statement text; the `.prflow/` corpora are machine-appended
  records that quote reviewed commands verbatim; `.changeset/` is `CHANGELOG.md`'s
  producer and describes before-states. `.github/workflows/` and
  `.github/actions/` are excluded on the merits: both run only inside Actions,
  and a checkout-less workflow job has no remote for the placeholders to resolve
  from, so environment addressing is the *correct* form there. `.claude/worktrees/`
  is excluded for a different reason (issue #711): this scanner's population is a
  **working-tree** enumeration (`--others`), so it sweeps every sibling git worktree
  the `EnterWorktree` tool creates there and can report violations that live in
  another branch's checkout. Until #711 that was survived only by the untracked,
  harness-managed `.git/info/exclude` line — machine-local state no clone inherits —
  so the exclusion is carried by the helper itself and the real-tree run is now
  worktree-immune on a bare clone.
* The recognized head set is closed: `gh`, `gh.exe`, and a `$VAR` / `${VAR}`
  expansion whose variable **name ends in `GH`** — a suffix test, not a
  `DEVFLOW_GH` equality test, so `$MY_GH` matches too and `$MYTOOL` does not. It
  is deliberately loose in that direction because the repo's resolver contract
  spells the variable differently in different callers. A `gh` reached through a
  wrapper script, or through a variable whose name does not end in `GH`, is
  outside this guard and is not covered elsewhere.
* The recognized path token set is closed at the literal variable name. A repo
  string reached through one assignment hop (`repos/$REPO/…`) is invisible here
  even when that variable was populated from the environment. Both residuals are
  accepted, not closed. The path argument itself is matched with or without a
  leading `/`, and the `api` subcommand is located by search rather than by
  position, so neither the documented `/repos/…` spelling nor a global flag
  between the head and the subcommand (`gh -R … api …`) evades the test.
* Only *shell* statements are examined. A REST path composed in another language
  and handed to `gh` — `scripts/build-experiment-records.py` builds one from
  `os.environ.get("GITHUB_REPOSITORY")` with a `gh repo view` fallback — is a
  third accepted residual, invisible to a shell-statement scanner by construction.

The statement model — continuation folding aside — is **shared, not re-derived**:
this scanner imports `extract-command-heads.py`'s splitter, substitution walker,
tokenizer, and normalizer exactly as `extract-command-shapes.py` does, so once a
line is selected the #363 / #401 / #664 guards agree on what a `gh api`
invocation is. They do **not** agree on which lines are selected in the first
place, and that is deliberate — what is bespoke here is the *line selector*, so
the scanned populations differ by construction. Unlike the #363 extractor, this
scanner does **not** skip heredoc bodies and does not require a fence's info
string to be exactly `bash` — a recipe emitted from a heredoc runs as written, and
an unterminated fence's remainder is treated as fence interior so a violation
after it is still reached.

Usage:
    lint-gh-api-repo-path.py [--root DIR] [--files-from PATH]

Exit status is 0 only when every selected file was read and none of them violated
the rule. It is non-zero when a violation is found, when the enumeration is
unusable, and when any selected path could not be read — callers distinguish the
three by reading the report, never the exit code.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

# Reuse the issue-#363 extractor's quote/substitution/tokenization machinery — the same
# import `extract-command-shapes.py` uses, and for the same reason: three independent
# notions of "a statement" in lib/test/ would drift, and this guard would then disagree
# with the #363/#401 guards about which text is a `gh api` invocation.
_HEADS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract-command-heads.py")
_spec = importlib.util.spec_from_file_location("extract_command_heads", _HEADS_PATH)
_heads = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_heads)

# The population enumeration, the file reader, the `EnumerationError` fail-closed
# contract, and the `--root` / `--files-from` preamble are shared with the other
# `git ls-files` lints (issue #724), imported by path with the same idiom used for
# `extract-command-heads.py` above. Assert the names this file uses at LOAD time so
# a rename fails here naming the dependency, not mid-scan.
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
        f"lint-gh-api-repo-path: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

#: The shared fail-closed enumeration error, re-exported so `main`'s `except` clause
#: names it locally.
EnumerationError = _pop.EnumerationError

#: This lint's population can contain binaries/UTF-16 (it audits the whole tree
#: minus a few prefixes), so a NUL-carrying file is reported as a skip rather than
#: scanned: `skip_nul=True`. This is the axis the shared reader exposes; the sibling
#: `lint-tree-enumeration.py` passes `False`.
_SKIP_NUL = True

#: Path prefixes whose files are never read. See the module docstring for why
#: each one is here.
EXCLUDED_PREFIXES = (
    "lib/test/",
    "docs/",
    ".github/workflows/",
    ".github/actions/",
    ".prflow/logs/",
    ".prflow/learnings/",
    ".changeset/",
    ".claude/worktrees/",
)

#: Exact paths (not prefixes) that are never read.
EXCLUDED_PATHS = ("CHANGELOG.md",)

#: Suffixes dispatched to the Markdown reader. `.md.example` is listed because
#: the repository tracks prompt-extension examples with that suffix, whose prose
#: would otherwise be scanned as if it were shell.
MARKDOWN_SUFFIXES = (".md", ".md.example")

#: The two spellings of the prohibited variable inside a path argument.
_FORBIDDEN = ("$GITHUB_REPOSITORY", "${GITHUB_REPOSITORY}")


def is_audited(path: str) -> bool:
    """True when `path` survives the population exclusions."""
    normalized = path.replace("\\", "/")
    if normalized in EXCLUDED_PATHS:
        return False
    return not any(normalized.startswith(p) for p in EXCLUDED_PREFIXES)


def considered_lines(text: str, markdown: bool) -> list[tuple[int, str]]:
    """Return the 1-based (line number, text) pairs the scan may read.

    In Markdown only fence interiors are considered — an unterminated fence runs
    to end of file. In source every line whose first non-whitespace character is
    not `#` is considered.
    """
    kept: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.lstrip()
        if markdown:
            # Both CommonMark fence spellings toggle: a `~~~bash` block is a fence like
            # any other, and recognizing only backticks would leave its interior silently
            # treated as prose.
            if stripped.startswith(("```", "~~~")):
                inside = not inside
                continue
            if inside:
                kept.append((number, line))
            continue
        if stripped.startswith("#"):
            continue
        kept.append((number, line))
    return kept


def fold_continuations(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Fold `\\`-continued lines onto the line number of the statement's head."""
    folded: list[tuple[int, str]] = []
    pending_number: int | None = None
    pending_text = ""
    for number, line in lines:
        if pending_number is None:
            pending_number, pending_text = number, line
        else:
            pending_text += line
        if pending_text.endswith("\\"):
            pending_text = pending_text[:-1]
            continue
        folded.append((pending_number, pending_text))
        pending_number, pending_text = None, ""
    if pending_number is not None:
        folded.append((pending_number, pending_text))
    return folded


def statements_in(text: str) -> list[str]:
    """Return every statement in one logical line, descending into `$(…)` bodies.

    Composed from the shared machinery rather than re-derived: `_split_statements`
    keeps a substitution's body intact as part of its enclosing statement, and
    `_substitutions` hands back those bodies to be split in their own right — which
    is how `VAR=$(gh api …)` is reached without the assignment prefix hiding the head.
    The descent repeats until no further substitution appears, so a nested
    `$( … $(gh api …) … )` is reached too.
    """
    found: list[str] = []
    pending = [text]
    while pending:
        current = pending.pop()
        for statement in _heads._split_statements(current):
            found.append(statement)
            pending.extend(_heads._substitutions(statement))
    return found


def violations_in_statement(statement: str) -> list[str]:
    """Return the offending path arguments of one statement (usually none).

    The `api` subcommand is located anywhere after the head rather than pinned to
    `tokens[1]`, so a global flag and its value (`gh -R owner/repo api …`,
    `gh --hostname h api …`) cannot push the subcommand out of view — matching on
    position alone made that shape unreachable. Searching rather than indexing errs
    toward flagging, which is the correct direction for a guard. The path test also
    tolerates one leading `/`, because `/repos/{owner}/{repo}/labels` is the
    spelling this repo's own helper headers and docs use for these endpoints — an
    author copying the documented form and interpolating the variable must not
    evade it.
    """
    tokens = [_heads._normalize(t) for t in _heads._tokenize(statement)]
    if not tokens or not _heads._is_gh_head(tokens[0]):
        return []
    if "api" not in tokens[1:]:
        return []
    index = tokens.index("api", 1)
    return [
        token
        for token in tokens[index + 1 :]
        if token.lstrip("/").startswith("repos/") and any(f in token for f in _FORBIDDEN)
    ]


def scan_text(text: str, markdown: bool) -> list[tuple[int, str]]:
    """Return the (line number, offending argument) pairs found in `text`."""
    found: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for number, line in fold_continuations(considered_lines(text, markdown)):
        for statement in statements_in(line):
            for argument in violations_in_statement(statement):
                # Deduplicate by (line, argument): the substitution descent reaches a
                # nested `$( … $(gh api …) … )` through both its outer and inner body,
                # so the same call would otherwise be reported once per nesting level.
                if (number, argument) not in seen:
                    seen.add((number, argument))
                    found.append((number, argument))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a gh api REST path interpolates $GITHUB_REPOSITORY on a "
            "surface that can run outside GitHub Actions."
        )
    )
    _pop.add_population_arguments(parser)
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-gh-api-repo-path")

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_WORKING_TREE,
        )
    except EnumerationError as exc:
        print(f"lint-gh-api-repo-path: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    audited = [path for path in population if is_audited(path)]

    findings: list[str] = []
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=_SKIP_NUL)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        read_ok += 1
        markdown = any(relative.endswith(suffix) for suffix in MARKDOWN_SUFFIXES)
        for number, argument in scan_text(text, markdown):
            findings.append(
                f"{relative}:{number}: gh api REST path addresses the repo through "
                f"$GITHUB_REPOSITORY ({argument}) — use the {{owner}}/{{repo}} placeholders"
            )

    for finding in findings:
        print(finding)
    for relative, reason in skipped:
        print(f"lint-gh-api-repo-path: SKIPPED {relative}: {reason}", file=sys.stderr)
    # The tally counts files actually READ, against the number selected — never the
    # selection alone, which would report work that did not happen.
    print(
        f"lint-gh-api-repo-path: audited {read_ok} of {len(audited)} files"
        + (f" ({len(skipped)} skipped)" if skipped else "")
    )
    if skipped:
        # A skipped file is never a clean pass (the repo's standing suite convention): a
        # PARTIAL skip is the same defect as a total one, just quieter — the guard reports
        # clean over a population it did not fully read. Gate on any skip, not only on the
        # all-skipped case, so a permission blip or a race against a rewritten worktree
        # cannot silently shrink the audit while the exit code stays green.
        print(
            f"lint-gh-api-repo-path: {len(skipped)} selected path(s) could not be audited — "
            "refusing to report clean; see the SKIPPED lines above",
            file=sys.stderr,
        )
        return 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

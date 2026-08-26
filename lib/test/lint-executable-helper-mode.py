#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when an `-x`-gated bundled helper is tracked non-executable.

Why this exists (issue #1312): `scripts/dedupe-review-command.sh` shipped tracked
`100644`, while both of its call sites in `.github/workflows/devflow.yml` gate on
`[ ! -x … ]` (the `$CC_HELPER` and `$NOTICE_HELPER` guards, each pointing at it).
A file that is present but not executable makes that guard
true on every run, in every repository — so Candidate-C in-flight-review dedupe (and
its suppression notice) silently never fired since the feature landed. Both arms
fail *open*, so nothing broke loudly; the bit was simply lost and no test noticed.
`lib/test/modules/efficiency-trace-telemetry.sh` already pinned one file's mode by
hand (`lib/efficiency-trace.sh`); this check generalises that *approach* to every
`-x`-gated helper, so a lost bit on one fails the suite rather than failing silently
in production. (`lib/efficiency-trace.sh` itself is invoked via `bash`, not `-x`-gated,
so it is out of this check's set and its hand pin stays load-bearing — issue #1312's
scope note directs leaving it in place.)

What it does. It derives the `-x`-gated helper set MECHANICALLY rather than from a
hand-maintained list: it joins `VAR=<path>` assignments to `[ -x "$VAR" ]` /
`[ ! -x "$VAR" ]` (and `[[ … ]]` / `test -x`) tests within the tracked population
below, resolves each operand to a repository path, and asserts every resolved
in-repo helper is tracked `100755`.

Audited population (single-level globs, per the governing criterion):

* tracked `.github/workflows/*.yml` (and `*.yaml`),
* tracked `scripts/*.sh`,
* tracked `lib/*.sh`.

`lib/test/**` is deliberately outside the population: its files carry `-x` tests
over gh-stub fixtures and grep pins that are not shipped helpers.

Named residuals (this check does NOT claim to cover every `-x`-gated bundled helper
call site in the tree — the sibling `git ls-files` lints carry their residuals the
same way, by enumeration here rather than by a scope claim elsewhere):

* **`install.sh` (repo root)** — outside the three globs above, and it carries one
  genuine `-x`-gated bundled-helper call site:
  `if [ -x "$SRC/scripts/migrate-consumer-tier1.sh" ]`. It stays a residual on
  purpose rather than by oversight: `$SRC` is a *dynamic* assignment with two arms
  (`$DEVFLOW_SRC`, an operator-supplied pre-materialized tree, and `$TMP/src`, a
  `mktemp -d` clone destination), so it is positively `runtime` under this file's
  resolver and neither arm is this repository's checkout — the installer reads a
  *source tree* it just materialized, not the tree being audited. Adding `install.sh`
  to the population would therefore report `RUNTIME`, not a mode assertion; making it
  assert would require teaching the resolver that a specific dynamic anchor is
  repo-equivalent, which is a semantic special case rather than a mechanical
  resolution. The helper's mode is instead held by the tracked-mode assertion in
  `lib/test/modules/tier1-rename-migration.sh`.

Operand resolution. For each `-x` test, the operand is resolved by expanding its
leading variable reference through the file's own assignments:

* a **literal-path** assignment (`VAR=.prflow/vendor/prflow/scripts/foo.sh`) — used
  verbatim;
* a **script-directory anchor** (`VAR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`)
  — resolved to the scanned file's own repo-relative directory, so
  `[ -x "$_SF_HERE/compose-filing-key.sh" ]` resolves to `lib/compose-filing-key.sh`;
* a **variable-reference** assignment that itself points at another resolvable
  variable plus a literal suffix (`DETECT="$SELF_DIR/detect-project-tools.sh"`) —
  expanded transitively.

A `.prflow/vendor/prflow/<path>` literal is mapped to its repo-root `<path>` before
the mode lookup (the workflows invoke every bundled helper at the vendored path).

Three outcomes per `-x` test — never a silent skip (issue #1312 AC5, because a
silently-skipping lint is the same failure class as the bug it guards):

* **repo helper** — the operand resolves to a concrete in-repo relative path. Its
  tracked index mode (`git ls-files -s`, the mode that actually ships) is asserted
  `100755`; anything else is a finding.
* **runtime operand** — the operand is POSITIVELY classified as not a repo path: its
  variable has a dynamic assignment (command substitution, `${VAR:-…}` default), is
  a `for`/`read` loop variable, is an environment variable with no in-file
  assignment, or resolves to a path outside the repository (absolute or `..`). These
  are recorded on stderr (`RUNTIME …`) and their mode is not asserted — they gate a
  runtime binary or hook (`gh`, a `$PATH` entry, a test hook), not a shipped helper.
* **unresolved operand** — an `-x` test whose operand the resolver cannot account for
  (an unsupported shape, or a resolution that lands on an in-repo path that is not a
  tracked file). This is a finding: the check names the operand and fails RED rather
  than skipping it, so a new helper the resolver does not understand cannot grow a
  silent blind spot.

Helpers that are `source`d or `-f`-guarded are never `-x`-gated, so they never enter
this set — the `source`d/`-f`-guarded `644` helpers named in issue #1312's scope note
stay `644` and pass (AC4).

Usage:
    lint-executable-helper-mode.py [--root DIR] [--files-from PATH]

Exit 0 only when every selected file was read and every `-x`-gated repo helper is
tracked `100755`. Non-zero on a finding, on an unreadable selected file, and on an
unusable enumeration — callers read the report, not the exit code, for the cause.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

# The population enumeration, file reader, `EnumerationError` fail-closed contract,
# `--root` / `--files-from` preamble, git-toplevel root resolution, and the
# `QUOTE_PATH_OFF` path-quoting fix are shared with the other `git ls-files` lints
# (issue #724). Import by path with the idiom the directory already uses, and assert
# the names this file relies on at LOAD time so a rename fails here naming the
# dependency rather than mid-scan on one file.
_POP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lint_population.py")
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
if _pop_spec is None or _pop_spec.loader is None:
    raise SystemExit(
        f"lint-executable-helper-mode: {_POP_PATH} is not an importable source file; "
        "refusing to audit"
    )
_pop = importlib.util.module_from_spec(_pop_spec)
try:
    _pop_spec.loader.exec_module(_pop)
except Exception as _exc:  # a SyntaxError in the sibling must fail closed here, named
    raise SystemExit(
        f"lint-executable-helper-mode: the shared population reader {_POP_PATH} could "
        f"not be loaded ({_exc.__class__.__name__}: {_exc}); refusing to audit"
    ) from _exc
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_INDEX", "QUOTE_PATH_OFF",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"lint-executable-helper-mode: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

#: Files scanned for `-x`-gated helpers — single-level globs per issue #1312 AC2.
_IN_SCOPE = (
    re.compile(r"\.github/workflows/[^/]+\.ya?ml\Z"),
    re.compile(r"scripts/[^/]+\.sh\Z"),
    re.compile(r"lib/[^/]+\.sh\Z"),
)

#: The vendored-path prefix mapped to its repo-root form before a mode lookup (AC3).
_VENDOR_PREFIX = ".prflow/vendor/prflow/"

_ASSIGN_RE = re.compile(
    r"^\s*(?:export\s+|readonly\s+|local\s+(?:-\w+\s+)*|declare\s+(?:-\w+\s+)*)?"
    r"([A-Za-z_]\w*)=(.*)$"
)
_FOR_RE = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s+in\b")
# `read` only at a command position (line start, after a `;`/`|`/`&`/`{`, or a `do`/`then`
# keyword) and only its BAREWORD variable operands — never identifiers inside a quoted
# string, so a prose line like `echo "please read $VAR"` cannot poison $VAR into the
# dynamic set (silent-failure #1312). The expand() reorder below is the primary guard;
# this anchoring is defence-in-depth for a var that has no other assignment.
_READ_RE = re.compile(
    r"(?:^|[;|&{]|\bdo\b|\bthen\b)\s*read\b((?:\s+-\w+)*)((?:\s+[A-Za-z_]\w*)+)"
)
# A `[ … ]` / `[[ … ]]` test span (non-greedy body, so `[ a ] && [ b ]` yields two).
_BRACKET_RE = re.compile(r"\[{1,2}(.*?)\]{1,2}")
# The operand token: a quoted string or an unquoted run — one fragment reused by both
# the bracket-interior and the `test -x` matchers so the operand grammar has a single home.
_OPERAND = r""""[^"]*"|'[^']*'|[^\s\];|&]+"""
# `-x <operand>` inside a `[ … ]` span (the `!` of `[ ! -x … ]` is part of the interior).
_XOP_RE = re.compile(r"(?:^|\s|!)\s*-x\s+(" + _OPERAND + r")")
# `test -x <operand>` / `test ! -x <operand>` as a bare command (outside a `[ … ]` span).
_TEST_X_RE = re.compile(r"\btest\s+(?:!\s+)?-x\s+(" + _OPERAND + r")")
# Brace form `${VAR}` / `${VAR:-default}`: group 2 CAPTURES the default so a
# `${HELPER:-scripts/foo.sh}` naming a real repo helper is resolved rather than dropped
# (silent-failure #1312 fail-open). group 3 is the literal suffix.
_BRACE_VAR_RE = re.compile(r"^\$\{([A-Za-z_]\w*)(?::-([^}]*))?\}(.*)$")
_SIMPLE_VAR_RE = re.compile(r"^\$([A-Za-z_]\w*)(.*)$")
# A `${X:-<literal path>}` assignment default (no `$` in the default) — treated as a
# resolvable literal so a helper named as an assignment-level default is asserted too.
_RHS_BRACE_DEFAULT_RE = re.compile(r"^\$\{[A-Za-z_]\w*:-([^}$`]+)\}$")

_MAX_DEPTH = 8


def in_scope(path: str) -> bool:
    """True when `path` is one of the tracked helper-carrying globs (AC2)."""
    normalized = path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in _IN_SCOPE)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def strip_comment(line: str) -> str:
    """Return the code portion of a shell line, dropping a `#` comment.

    A `#` opens a comment only at line start or after whitespace; a `#` inside a
    string, or mid-word (a fragment/anchor), is kept. This drops a fully-commented
    `# … [ -x ] …` line so its bracket is never read as a test."""
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote is not None:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (not out or out[-1].isspace()):
            break
        out.append(ch)
    return "".join(out)


def fold_continuations(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Fold `\\`-continued lines onto the head line's number (sibling-lint idiom)."""
    folded: list[tuple[int, str]] = []
    pending_number: int | None = None
    pending_text = ""
    for number, line in lines:
        if pending_number is None:
            pending_number, pending_text = number, line
        else:
            pending_text += " " + line
        if pending_text.endswith("\\"):
            pending_text = pending_text[:-1]
            continue
        folded.append((pending_number, pending_text))
        pending_number, pending_text = None, ""
    if pending_number is not None:
        folded.append((pending_number, pending_text))
    return folded


def _classify_rhs(rhs: str) -> tuple[str, str | None]:
    """Classify an assignment's right-hand side.

    Returns one of ('script-dir', None) / ('literal', value) / ('var-ref', value) /
    ('dynamic', None)."""
    raw = rhs.strip()
    if "dirname" in raw and ("BASH_SOURCE" in raw or "$0" in raw) and "pwd" in raw:
        return ("script-dir", None)
    unq = _unquote(raw)
    if "`" in unq or "$(" in unq:
        return ("dynamic", None)
    default = _RHS_BRACE_DEFAULT_RE.match(unq)
    if default and default.group(1).strip():
        # `VAR=${X:-scripts/foo.sh}` — the default names a candidate helper, so resolve
        # to it rather than dropping the whole RHS as dynamic (fail-closed: a real repo
        # helper named as a default still has its mode asserted). A default containing a
        # `$` was excluded by the pattern and falls through to the dynamic arm below.
        return ("literal", default.group(1).strip())
    if re.search(r"\$\{[A-Za-z_]\w*:-", unq):  # ${VAR:-<non-literal default>} — dynamic
        return ("dynamic", None)
    if "$" in unq:
        return ("var-ref", unq)
    return ("literal", unq)


class _FileModel:
    """Assignments, dynamic (loop/read) variables, and `-x` operands of one file."""

    def __init__(self, relpath: str, text: str) -> None:
        self.relpath = relpath
        self.assignments: dict[str, list[tuple[int, str, str | None]]] = {}
        self.dynamic: set[str] = set()
        self.operands: list[tuple[int, str]] = []  # (lineno, raw operand token)

        physical = [
            (n, strip_comment(line))
            for n, line in enumerate(text.split("\n"), start=1)
        ]
        physical = [(n, code) for n, code in physical if code.strip()]
        for lineno, code in fold_continuations(physical):
            self._scan_symbols(lineno, code)
            self._scan_operands(lineno, code)

    def _scan_symbols(self, lineno: int, code: str) -> None:
        for_match = _FOR_RE.match(code)
        if for_match:
            self.dynamic.add(for_match.group(1))
        read_match = _READ_RE.search(code)
        if read_match:
            for name in re.findall(r"[A-Za-z_]\w*", read_match.group(2)):
                self.dynamic.add(name)
        assign = _ASSIGN_RE.match(code)
        if assign:
            var, rhs = assign.group(1), assign.group(2)
            kind, value = _classify_rhs(rhs)
            self.assignments.setdefault(var, []).append((lineno, kind, value))

    def _scan_operands(self, lineno: int, code: str) -> None:
        for span in _BRACKET_RE.finditer(code):
            for operand in _XOP_RE.finditer(span.group(1)):
                self.operands.append((lineno, operand.group(1)))
        for operand in _TEST_X_RE.finditer(code):
            self.operands.append((lineno, operand.group(1)))

    def _nearest(self, var: str, lineno: int) -> tuple[int, str, str | None] | None:
        entries = self.assignments.get(var)
        if not entries:
            return None
        preceding = [e for e in entries if e[0] <= lineno]
        return max(preceding, key=lambda e: e[0]) if preceding else min(entries, key=lambda e: e[0])

    def expand(self, token: str, lineno: int, depth: int = 0) -> tuple[str, str]:
        """Resolve an operand/value to ('literal', path) / ('runtime', reason) /
        ('unresolved', reason)."""
        if depth > _MAX_DEPTH:
            return ("unresolved", "expansion nested too deeply")
        if "$" not in token:
            return ("literal", token)
        brace = _BRACE_VAR_RE.match(token)
        if brace:
            var, default, suffix = brace.group(1), brace.group(2), brace.group(3)
        else:
            simple = _SIMPLE_VAR_RE.match(token)
            if not simple:
                return ("unresolved", f"unsupported operand shape {token!r}")
            var, default, suffix = simple.group(1), None, simple.group(2)
        if "$" in suffix:
            return ("unresolved", f"operand {token!r} has a further expansion in its suffix")
        # A concrete assignment WINS over the for/read dynamic heuristic, so a real
        # `VAR=<path>` is asserted even if the name also appears after a `read`/`for`
        # token elsewhere in the file (silent-failure #1312 fail-open reorder).
        entry = self._nearest(var, lineno)
        if entry is not None:
            entry_lineno, kind, value = entry
            if kind == "literal":
                return ("literal", (value or "") + suffix)
            if kind == "script-dir":
                base = posixpath.dirname(self.relpath)
                return ("literal", f"{base}{suffix}" if base else suffix.lstrip("/"))
            if kind == "var-ref":
                inner = self.expand(value or "", entry_lineno, depth + 1)
                if inner[0] != "literal":
                    return inner
                return ("literal", inner[1] + suffix)
            # kind == "dynamic" falls through to the default/runtime handling below.
        # No resolving assignment (or a dynamic one): a `${VAR:-<literal path>}` default
        # names a candidate helper the guard checks, so resolve it rather than dropping
        # it (fail-closed — a real repo helper named as a default has its mode asserted).
        if default is not None and "$" not in default and default.strip():
            return self.expand(default.strip() + suffix, lineno, depth + 1)
        if var in self.dynamic:
            return ("runtime", f"${var} is a for/read loop variable")
        if entry is not None:
            return ("runtime", f"${var} has a dynamic assignment")
        return ("runtime", f"${var} has no in-file assignment (environment-provided)")


def classify_path(path: str) -> tuple[str, str]:
    """Classify a fully-resolved operand path.

    Returns ('runtime', detail) for a path outside the repo, ('ok', repopath),
    ('untracked', repopath), or ('wrongmode', 'repopath\\tmode')."""
    p = path.strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.removeprefix(_VENDOR_PREFIX)
    p = re.sub(r"/+", "/", p)
    if not p or p.startswith(("/", "../")) or p == ".." or "/../" in p or p.endswith("/.."):
        return ("runtime", f"resolves to a path outside the repository ({path})")
    mode = _MODES.get(p)
    if mode is None:
        return ("untracked", p)
    if mode == "100755":
        return ("ok", p)
    return ("wrongmode", f"{p}\t{mode}")


# Populated once in main() from `git ls-files -s` in the resolved root.
_MODES: dict[str, str] = {}


def _git_modes(root: Path) -> dict[str, str]:
    """Map every tracked repo-relative path to its index mode (`git ls-files -s`).

    Index mode, not the working-tree mode, is what ships — it is the comparand
    (issue #1312's own guidance: confirm with `git ls-files -s`, not `ls -l`).
    `QUOTE_PATH_OFF` (issue #1217) keeps a tracked non-ASCII path raw. Raises
    `EnumerationError` on any failure so the caller fails closed rather than
    auditing against an empty mode map."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *_pop.QUOTE_PATH_OFF, "ls-files", "-s"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise EnumerationError(f"git ls-files -s could not be run: {exc}") from exc
    if proc.returncode != 0:
        raise EnumerationError(
            f"git ls-files -s exited {proc.returncode}: {proc.stderr.strip() or '(no stderr)'}"
        )
    modes: dict[str, str] = {}
    for line in proc.stdout.split("\n"):
        if not line:
            continue
        meta, tab, path = line.partition("\t")
        if not tab:
            continue
        mode = meta.split(" ", 1)[0]
        modes[path.rstrip("\r\n")] = mode
    return modes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when an -x-gated bundled helper is tracked non-executable "
            "(not 100755)."
        )
    )
    _pop.add_population_arguments(parser)
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-executable-helper-mode")

    global _MODES
    try:
        _MODES = _git_modes(root)
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except EnumerationError as exc:
        print(f"lint-executable-helper-mode: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    audited = [path for path in population if in_scope(path)]

    findings: list[str] = []
    runtime_notes: list[str] = []
    checked = 0
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=False)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        read_ok += 1
        model = _FileModel(relative, text)
        for lineno, operand in model.operands:
            kind, payload = model.expand(_unquote(operand), lineno)
            if kind == "runtime":
                runtime_notes.append(f"{relative}:{lineno}: {operand} — {payload}")
                continue
            if kind == "unresolved":
                findings.append(
                    f"{relative}:{lineno}: -x test operand {operand} could not be "
                    f"resolved to a repo path ({payload}) — refusing to silently skip"
                )
                continue
            pkind, pdetail = classify_path(payload)
            if pkind == "runtime":
                runtime_notes.append(f"{relative}:{lineno}: {operand} — {pdetail}")
            elif pkind == "ok":
                checked += 1
            elif pkind == "untracked":
                findings.append(
                    f"{relative}:{lineno}: -x test operand {operand} resolves to in-repo "
                    f"path {pdetail}, which is not a tracked repo file — cannot confirm "
                    f"its executable mode"
                )
            else:  # wrongmode
                repopath, mode = pdetail.split("\t", 1)
                findings.append(
                    f"{relative}:{lineno}: -x-gated helper {repopath} is tracked mode "
                    f"{mode}, expected 100755"
                )

    for finding in findings:
        print(finding)
    for note in runtime_notes:
        print(f"lint-executable-helper-mode: RUNTIME {note}", file=sys.stderr)
    for relative, reason in skipped:
        print(f"lint-executable-helper-mode: SKIPPED {relative}: {reason}", file=sys.stderr)
    print(
        f"lint-executable-helper-mode: audited {read_ok} of {len(audited)} files "
        f"({checked} -x-gated repo helper(s) checked)"
        + (f" ({len(skipped)} skipped)" if skipped else "")
    )
    if skipped:
        # A skipped file is never a clean pass (the standing suite convention): a partial
        # skip is the same defect as a total one, quieter — clean over a population not
        # fully read. Gate on any skip.
        print(
            f"lint-executable-helper-mode: {len(skipped)} selected path(s) could not be "
            "audited — refusing to report clean; see the SKIPPED lines above",
            file=sys.stderr,
        )
        return 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

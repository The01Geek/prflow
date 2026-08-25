#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Static self-scan of `lib/test/run.sh`'s own pin corpus (issue #375).

Three mechanical guards over the suite's pin-helper call sites, so a defect the
parents (#370, #371) had to rediscover in a later shadow instead fails RED at
authoring time:

* ``lint`` — the **pin-in-comment lint.** A pin literal that also appears inside
  a *comment* of its own target file inflates the occurrence count the pin reads
  (issue #370's evidence: a ``pin_count`` expecting 2 read 3 because the phase
  file's own comment quoted the literal, so collapsing a real call site brought
  the count *down* to the expected 2 — the pin passed on the regression it
  guards). This scan enumerates every statically-resolvable ``(literal, target)``
  pair from the four pin helpers and FAILs when the literal sits in a ``#``
  comment (``.sh``/``.py``/``.jq``/``.yml``) or an ``<!-- … -->`` region
  (``.md``) of its target.

* ``wrapped`` — the **wrapped-literal meta-guard.** A contract phrase assembled
  from wrapped adjacent string literals (``'… OLD does '`` then ``'not) …'`` in
  an argparse ``help=``) lives on *no single line*, so a line-based ``grep`` /
  ``pin_count`` finds nothing even though the rendered ``--help`` text contains
  it (issue #371's evidence). This scan flags any source-grep pin whose phrase
  occurs on no single line of its target, distinguishing *absent* from *present
  only in the whitespace-normalized rendering* (``tr -s '[:space:]' ' '``), and
  additionally FAILs any pin into a multi-literal argparse ``help=`` string,
  requiring the pin to target the rendered surface (captured ``--help`` output,
  real stderr) instead.

  **Relocation diagnosis (issue #661, opt-in via ``--reloc``).** A bare
  ``ABSENT`` reads identically for a pin literal that was *relocated* into a
  different file and one that was genuinely *deleted*. When ``--reloc`` is
  passed and a pin literal is ABSENT from its named target (whitespace-normalized
  and rendered-surface, so a wrapped literal still counts), the guard searches a
  scoped tracked-file set — from ``--reloc-search-set`` when supplied (the
  git-free path the self-tests use) else ``git ls-files`` — **minus** the
  pin-source file(s) that declare the literal (auto-excluded plus any
  ``--reloc-exclude`` substring token) and the non-source trees ``.prflow/vendor/`` /
  ``.prflow/tmp/``, and reports every other file where the literal resolves as
  ``RELOCATED … relocated to <file>; update the pin target``. Only when the set
  was enumerated successfully **and** the literal resolves nowhere in it does it
  read ``deleted (not found anywhere)`` — a failed/empty enumeration is reported
  ``relocation diagnosis unavailable`` on stderr and is **never** collapsed to
  ``deleted`` (fail-closed). Without ``--reloc`` the ABSENT emit is unchanged.

* ``mutation-routing-worktree`` — the required worktree gate over the committed
  audited test-source population (issues #666 and #810). It runs **two** subgates
  and concatenates their findings:

  1. the retired-helper zero-population census, which builds the opaque
     mutation-call census and requires both the census and the checked-in
     inventory to be empty — every supported mutation-helper definition or
     invocation is prohibited; and
  2. the static pin classifier over the worktree's changes against the merge base
     with ``origin/main``, scanning ``AUDITED_PIN_SOURCES`` plus the tracked and
     untracked ``lib/test/test_*.py`` leaves, so a newly added undeclared
     wording-only pin fails RED.

  Neither subgate executes or interprets mutations, classifies effects, or infers
  assignment dependencies.
  Infrastructure failures exit 2, policy findings exit 3, and a clean established
  scan exits 0. The lower-level ``mutation-routing`` synthetic-fixture command
  remains for legacy self-tests.

  **The static classifier ROUTES; it does not judge (issue #948).** For a changed
  site whose declaration grammar is valid, it walks an ordered three-step ladder:
  (1) a program in ``scripts/**``, ``lib/**`` (non-test) or ``.github/**``
  demonstrably reads the literal or a distinctive token it names — pass, no human
  needed; (2) otherwise, the delta-gated ledger
  ``lib/test/pin-corpus-adjudications.tsv`` already records this literal as
  ``boundary`` **and** the site carries a valid ``# structural-pin-ok:``
  declaration — pass, honouring the tag as a *pointer to an authorized decision*;
  (3) neither — report the finding. Step 1 can only ever route a site to step 2
  (a grep-shaped consumer search misses a generic consumer by construction, so
  "found none" means "ask the ledger", never "reject"), and step 2 fails closed:
  an absent, unestablished or non-``boundary`` ledger row never satisfies it, and
  an unreadable ledger is an infrastructure failure long before this ladder runs.
  The real control over step 2 is therefore not this classifier but the review of
  ledger changes, which is separately delta-gated and needs an exact branch
  manifest — do not read the ladder as the gate getting smarter. The ladder is
  scoped to the RETAINED population: a *retired* wording literal's revival keeps
  its pre-#948 contract (deliberate authorization plus a genuinely machine-shaped
  target), since both ladder steps rest on the very boundary row that contract
  says cannot on its own make a revival valid.

**Fail-closed:** a call site the scanner cannot resolve statically (the literal
interpolates a variable it cannot resolve, or the target file is a variable with
no ``--var`` binding and no ``$LIB``-relative assignment) is COUNTED and reported
on stderr, never silently skipped.

The three legacy pin-source commands preserve their existing output contracts:
without ``--strict``, ``lint`` and ``wrapped`` exit 0 even on findings, and the
synthetic-fixture ``mutation-routing`` command always exits 0. Findings go to
stdout (one per line, tab-separated); unresolvable counts and per-site details go
to stderr. The required ``mutation-routing-worktree`` command instead carries its
0/2/3 clean/infrastructure/finding contract directly.

**``--strict`` exit-code mode (issue #687, opt-in, applies to ``lint`` and
``wrapped``; ``mutation-routing`` keeps its own always-exit-0 contract).** With
``--strict`` a run that writes at least one line to stdout exits **3**, and a run
that writes none exits 0; the stdout and stderr bytes are byte-for-byte what they
are without the flag — ``--strict`` changes only the exit code. The rule is
defined over **whether any line was written to stdout**, not over a list of
finding tokens, so a finding arm added later is covered the day it lands. Every
stdout write on a covered path routes through the single ``_emit`` helper (defined
just above ``run_lint``); ``lib/test/run.sh``'s issue-#687 emit-helper guard,
anchored from ``run_lint`` to the end of ``_emit_wrapped_or_absent``, goes RED if
a raw stdout write is introduced inside that range — so a future arm printing
*informational* output on a covered path must route it to ``sys.stderr`` instead.
**What ``--strict`` rc 0 does and does not assert:** it asserts only that no line
was written to stdout; it does **not** assert that any pin was resolved. The
fail-closed accounting (``UNRESOLVED-COUNT`` / ``RESOLVED-COUNT``) is a stderr
channel that never moves the exit code, so a corpus in which every pin failed to
resolve prints nothing and exits 0 under ``--strict`` — a caller keying on the
exit code still owes the separate ``RESOLVED-COUNT`` floor.

CLI::

    pin-corpus-lint.py lint            PIN_SOURCE [--strict] [--lib DIR] [--var NAME=PATH ...]
    pin-corpus-lint.py wrapped         PIN_SOURCE [--strict] [--lib DIR] [--var NAME=PATH ...]
                                       [--reloc] [--reloc-search-set FILE]
                                       [--reloc-exclude SUBSTR ...]
    pin-corpus-lint.py mutation-routing PIN_SOURCE --diff-file FILE
                                       [--lib DIR] [--var NAME=PATH ...]
    pin-corpus-lint.py mutation-routing-worktree REPO_ROOT

``PIN_SOURCE`` is the shell file whose pin call sites are scanned (``run.sh``
itself for the real corpus, a synthetic fixture for the self-tests). ``--var``
supplies the runtime value of a target-file variable the helper cannot resolve
statically (e.g. ``DEF_SKILL``, the mktemp'd implement-skill bundle); ``--lib``
binds ``$LIB`` so ``VAR="$LIB/../skills/…"`` assignments resolve on their own.
``--reloc`` enables the issue-#661 relocation diagnosis on the ``wrapped``
guard's ABSENT branch; ``--reloc-search-set FILE`` supplies the search set as a
newline-delimited file (git-free, for the self-tests) instead of ``git
ls-files``; ``--reloc-exclude SUBSTR`` (repeatable) drops any tracked path
containing SUBSTR anywhere in it -- a substring test, not an anchored prefix --
from the search set (the pin-source file(s) that declare the literal); a token
that resolves to the same file as a candidate (abspath-equal) is dropped too.
``--diff-file FILE`` (``mutation-routing`` only, required) supplies the unified
diff whose added/deleted lines scope the declaration gate.

Known limitation: the search set is read as UTF-8, so a non-UTF-8 tracked file
(an image, a binary fixture) is an UNREADABLE candidate. That direction is safe
-- it downgrades a would-be ``deleted`` verdict to ``diagnosis INCOMPLETE`` and
never claims a false deletion -- but it does mean a genuine deletion in a corpus
containing binary tracked files reports INCOMPLETE rather than ``deleted``.
"""

from __future__ import annotations

import ast
import bisect
import csv
import difflib
import fnmatch
import functools
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple

# The `-c core.quotePath=false` option pair, imported from the shared population reader
# (issue #1217) rather than re-spelled here, so the literal keeps one home in the tree.
# This module composes its own `git -C <root> …` prefix through `_run_git`, so it cannot
# use `lint_population`'s ready-made argvs — only the option pair they are built from.
# Without it, git's default C-quoting returns a tracked non-ASCII path as a string that
# names no real file. Each enumeration below then selects by an EXACT path form — a prefix
# test (`is_machine_consumer_path`), a `re.fullmatch`, or membership in
# `AUDITED_PIN_SOURCES` — none of which the C-quoted spelling satisfies, so such a file
# would silently drop out of the corpus. (The `_git_ls_files` enumeration further down
# passes `-z` and is unquoted by construction, so it needs no splice.)
_POP_PATH_PC = Path(__file__).resolve().parent / "lint_population.py"
try:
    _pop_spec_pc = importlib.util.spec_from_file_location("lint_population", _POP_PATH_PC)
    if _pop_spec_pc is None or _pop_spec_pc.loader is None:
        raise ImportError(f"no loadable spec for {_POP_PATH_PC}")
    _pop_pc = importlib.util.module_from_spec(_pop_spec_pc)
    _pop_spec_pc.loader.exec_module(_pop_pc)
except Exception as _exc_pc:
    raise SystemExit(
        f"pin-corpus-lint: the shared population reader {_POP_PATH_PC} could not be "
        f"loaded ({_exc_pc.__class__.__name__}: {_exc_pc}); refusing to audit"
    ) from _exc_pc
# Validate the SHAPE, not just presence: `hasattr` is satisfied by an emptied
# `QUOTE_PATH_OFF = ()`, which splices nothing and silently reinstates the defect, and by a
# bare string, which `tuple()` would explode into one argv element per character. Comparing
# against the expected pair makes either failure name the constant rather than surfacing as
# a green run or an unrecognised-git-option error.
_qp = getattr(_pop_pc, "QUOTE_PATH_OFF", None)
if _qp != ("-c", "core.quotePath=false"):
    raise SystemExit(
        f"pin-corpus-lint: {_POP_PATH_PC}'s `QUOTE_PATH_OFF` is not the expected "
        f"`-c core.quotePath=false` option pair (got {_qp!r}); refusing to audit"
    )
QUOTE_PATH_OFF = tuple(_qp)

# Non-source trees always excluded from the relocation search set (issue #661): a
# committed vendored plugin copy and the run's own draft/derivation artifacts both
# quote pin literals and would otherwise be reported as spurious destinations.
RELOC_DEFAULT_EXCLUDES = (".prflow/vendor/", ".prflow/tmp/")

# Machine-consumed sentinel (issue #967): written to stderr by
# ``scan_static_pin_changes`` only after both static-classifier passes have
# completed, so a caller can tell "the gate ran and was clean" from "a
# precondition raised and the gate never ran". Coupled to the assertion in
# ``lib/test/run.sh``; change both together.
STATIC_SCAN_COMPLETED_MARKER = "MUTATION-ROUTING-STATIC-SCAN-COMPLETED"

# (literal_arg_index, file_arg_index, default_file_var).  Indices are 0-based
# over the call's arguments AFTER the helper name.  A file index past the actual
# arg list means the optional file arg was omitted -> use default_file_var.
HELPERS = {
    "assert_pin_unique": (1, 2, None),
    "pin_count": (0, 1, None),
    "assert_pin_red_on_removal": (1, 2, "MAXI_SKILL"),
    # Retired helpers remain parseable only so maintainer tooling can reproduce
    # historical frozen inventories. The zero-population census rejects every live
    # definition or invocation before the authoring classifier runs.
    "assert_pin_red_under": (1, 3, "MAXI_SKILL"),
    # Namespaced module pin API (module-harness.sh, issue #577) so the meta-lints
    # cover pins that extraction moves out of run.sh into lib/test/modules/*.sh
    # (issue #591). Module pins always pass the target file explicitly — no default.
    "devflow_module_pin_count": (0, 1, None),
    "devflow_module_pin_unique": (1, 2, None),
    "devflow_module_pin_present": (1, 2, None),
    "devflow_module_pin_red_under": (1, 3, None),
}

# Naming convention for a module-private static presence wrapper implemented
# through a lower-level counter rather than by forwarding to a known helper (for
# example review-and-fix-contract.sh's ``_raf_pin_unique``, whose body calls
# ``assert_eq`` on a ``_raf_pin_count`` substitution). The wrapper inference in
# ``helper_specs_for_source`` falls back to this suffix set when no body-derived
# forwarding form is recognized; naming it keeps that convention in one place so
# a second reader (pin-corpus-classifier.py's existence-helper set) shares the
# definition instead of restating the literals.
STATIC_PRESENCE_WRAPPER_SUFFIXES = ("_pin_unique", "_pin_present")

COMMENT_HASH_EXTS = {".sh", ".py", ".jq", ".yml", ".yaml"}
COMMENT_MD_EXTS = {".md"}


# ── shell tokenizing ────────────────────────────────────────────────────────
def join_logical_lines(text):
    """Yield (start_lineno, logical_line) joining backslash-continued lines."""
    physical = text.split("\n")
    i = 0
    while i < len(physical):
        start = i + 1
        line = physical[i]
        while line.endswith("\\") and not line.endswith("\\\\") and i + 1 < len(physical):
            line = line[:-1] + "\n" + physical[i + 1]
            i += 1
        yield start, line
        i += 1


def tokenize(s, *, split_shell_operators=False, include_spans=False):
    """Split a shell fragment into argument tokens, quote-aware.

    Returns a list of tokens, each a list of (kind, value) segments where kind
    is 'sq' (single-quoted, literal), 'dq' (double-quoted), 'bare', or — in
    shell-operator mode — 'escaped'. Adjacent segments with no separating
    whitespace belong to one token (shell concatenation, e.g. `'a'"$B"`).
    When ``split_shell_operators`` is true, unquoted, unescaped command
    operators are emitted as separate bare tokens. When ``include_spans`` is
    true, each item is ``(token, start, end)`` with offsets into ``s``.
    """
    tokens = []
    cur = []  # list of (kind, value) segments for the current token
    cur_start = None

    def emit(token, start, end):
        tokens.append((token, start, end) if include_spans else token)

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if (
            split_shell_operators
            and c == "("
            and i + 1 < n
            and s[i + 1] == ")"
            and cur
            and all(kind == "bare" for kind, _ in cur)
            and re.fullmatch(r"[A-Za-z_]\w*", _token_value(cur))
        ):
            # Keep a Bash function-definition name (`name()`) opaque. Its body
            # is scanned independently; treating `name` as an invocation would
            # double-count inferred wrappers or trigger the multi-call guard.
            cur.append(("bare", "()"))
            i += 2
            continue
        if split_shell_operators and c in ";&|()":
            if cur:
                emit(cur, cur_start, i)
                cur = []
                cur_start = None
            operator = (
                s[i : i + 2]
                if s[i : i + 2] in {"&&", "||", "|&"}
                else c
            )
            emit([("bare", operator)], i, i + len(operator))
            i += len(operator)
            continue
        if c in " \t\n":
            if cur:
                emit(cur, cur_start, i)
                cur = []
                cur_start = None
            i += 1
            continue
        if c == "#" and not cur:
            # A '#' starting a token begins a comment (only outside a token, so
            # `foo#bar` bare words are unaffected — none occur in pin calls).
            break
        if c == "'":
            if cur_start is None:
                cur_start = i
            j = s.index("'", i + 1) if "'" in s[i + 1 :] else n
            cur.append(("sq", s[i + 1 : j]))
            i = j + 1
            continue
        if c == '"':
            if cur_start is None:
                cur_start = i
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(s[j : j + 2])
                    j += 1
                else:
                    buf.append(s[j])
                j += 1
            cur.append(("dq", "".join(buf)))
            i = j + 1
            continue
        # bare run up to next whitespace/quote
        if cur_start is None:
            cur_start = i
        j = i
        buf = []
        while j < n and s[j] not in " \t\n'\"":
            if split_shell_operators and s[j] in ";&|()":
                break
            if s[j] == "\\" and j + 1 < n:
                if split_shell_operators:
                    if buf:
                        cur.append(("bare", "".join(buf)))
                        buf = []
                    cur.append(("escaped", s[j + 1]))
                else:
                    buf.append(s[j + 1])
                j += 1
            else:
                buf.append(s[j])
            j += 1
        if buf:
            cur.append(("bare", "".join(buf)))
        i = j
    if cur:
        emit(cur, cur_start, n)
    return tokens


# ── variable resolution ─────────────────────────────────────────────────────
_VARREF = re.compile(r"^\$\{?(\w+)\}?$")
_ASSIGNMENT_RE = re.compile(r"^\s*(?:local\s+)?([A-Za-z_]\w*)=(.*)$")


def build_var_maps(text, lib, overrides):
    """Return (path_vars, literal_vars).

    path_vars: NAME -> resolved filesystem path (from `--var` overrides and from
    `VAR="$LIB/..."` / `VAR=$OTHER` assignments).
    literal_vars: NAME -> literal string value (from `VAR='single-quoted'`).

    This intentionally models only sequential top-level assignments. Each
    right-hand side is resolved against the values available at that point; it
    does not attempt to evaluate conditional shell control flow.
    """
    path_vars = dict(overrides)
    literal_vars = {}
    for _, line in join_logical_lines(text):
        m = _ASSIGNMENT_RE.match(line)
        if not m:
            continue
        name, rhs = m.group(1), m.group(2).strip()
        _apply_assignment(
            name, rhs, path_vars, literal_vars, lib, protected=set(overrides)
        )
    return path_vars, literal_vars


def _apply_assignment(name, rhs, path_vars, literal_vars, lib, protected=()):
    """Apply one supported assignment using the values visible before it."""
    if name in protected:
        return
    path_vars.pop(name, None)
    literal_vars.pop(name, None)
    if (
        len(rhs) >= 2
        and rhs[0] == "'"
        and rhs.endswith("'")
        and "'" not in rhs[1:-1]
    ):
        literal_vars[name] = rhs[1:-1]
        return
    value = _resolve_path_rhs(rhs, lib, path_vars)
    if value is not None:
        path_vars[name] = value


def variable_maps_by_line(text, lib, overrides):
    """Return sequential assignment maps before each logical line.

    Every line between two assignments sees the same values, so one read-only
    view is shared across that whole run and a fresh pair is taken only where
    an assignment could have changed them — on a source whose lines mostly
    carry no assignment that is far fewer copies than one pair per line. The
    views are ``MappingProxyType`` so a caller that tried to write through one
    fails at the write instead of silently altering every line sharing it;
    every reader today only looks values up.
    """
    maps = {}
    path_vars = dict(overrides)
    literal_vars = {}
    protected = set(overrides)
    snapshot = (
        MappingProxyType(dict(path_vars)),
        MappingProxyType(dict(literal_vars)),
    )
    for lineno, line in join_logical_lines(text):
        maps[lineno] = snapshot
        match = _ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        _apply_assignment(
            match.group(1),
            match.group(2).strip(),
            path_vars,
            literal_vars,
            lib,
            protected=protected,
        )
        snapshot = (
            MappingProxyType(dict(path_vars)),
            MappingProxyType(dict(literal_vars)),
        )
    return maps


def _resolve_path_rhs(rhs, lib, path_vars):
    # Strip surrounding quotes if the whole RHS is quoted.
    r = rhs
    if len(r) >= 2 and r[0] == '"' and r.endswith('"'):
        r = r[1:-1]
    elif len(r) >= 2 and r[0] == "'" and r.endswith("'"):
        return None  # single-quoted -> a literal var, not a path
    # `$OTHER` alone
    m = _VARREF.match(r)
    if m:
        return path_vars.get(m.group(1))
    # `$LIB/rel` / `${LIB}/rel` / `$OTHER/rel` — the shared inline var-prefixed
    # path grammar, so this and resolve_arg's inline target resolution stay one
    # owner (issue #757).
    inline = _resolve_inline_var_path(r, lib, path_vars)
    if inline is not None:
        return inline
    # A bare literal path (no `$`).
    if "$" not in r and "(" not in r and r:
        # Only treat as a path if it looks like one (has a slash or extension).
        if "/" in r or "." in r:
            return r if os.path.isabs(r) else os.path.normpath(os.path.join(lib or ".", r))
    return None


_INLINE_LIB = re.compile(r"^\$\{?LIB\}?/(.*)$")
_INLINE_VAR = re.compile(r"^\$\{?(\w+)\}?/(.*)$")


def _resolve_inline_var_path(s, lib, path_vars):
    """Resolve an inline var-prefixed path reference — ``$LIB/rel`` / ``${LIB}/rel``,
    or ``$OTHER/rel`` / ``${OTHER}/rel`` where OTHER is a known path var — to a
    filesystem path, or None when it is neither shape (or the referenced var is
    unknown).

    This is the inline counterpart of the whole-``$VAR`` resolution ``resolve_arg``
    already performs. A pin's target file argument is frequently written inline —
    ``devflow_module_pin_unique "…" '…' "$LIB/../CLAUDE.md"`` — rather than as a
    pre-assigned whole-``$VAR`` token, and without this an inline target stays
    unresolved: surfaced on stderr but never asserted, i.e. silently exempt from the
    wrapped / pin-in-comment meta-guards while the guards still read rc 0 (issue
    #757). Applied only for ``want_path`` targets, never for pinned literals, so
    literal resolution is unchanged."""
    m = _INLINE_LIB.match(s)
    if m and lib is not None:
        return os.path.normpath(os.path.join(lib, m.group(1)))
    m = _INLINE_VAR.match(s)
    if m and m.group(1) in path_vars:
        return os.path.normpath(os.path.join(path_vars[m.group(1)], m.group(2)))
    return None


def resolve_arg(segments, literal_vars, path_vars, want_path, lib=None):
    """Resolve one argument's segments to a string, or None if unresolvable.

    want_path=True resolves against path_vars (target file); otherwise against
    literal_vars (the pinned literal). ``lib`` enables inline ``$LIB/rel`` /
    ``$VAR/rel`` path resolution for ``want_path`` targets (issue #757).
    """
    out = []
    for kind, val in segments:
        if kind == "sq":
            out.append(val)
        elif kind == "dq":
            # Neutralize backslash-escaped metacharacters first: `\$`, `` \` ``, `\"`,
            # `\\` are literal, not interpolation. Only an UNescaped `$`/backtick that
            # remains is real interpolation (a whole `$VAR`, or — for a path target —
            # an inline `$VAR/rel` prefix).
            NUL, TCK = "\x00d", "\x00t"
            neutral = (
                val.replace("\\\\", "\x00b")
                .replace("\\$", NUL)
                .replace("\\`", TCK)
                .replace('\\"', '"')
            )
            if "$" in neutral or "`" in neutral:
                m = _VARREF.match(neutral)
                if m:
                    repl = (path_vars if want_path else literal_vars).get(m.group(1))
                    if repl is None:
                        return None
                    out.append(repl)
                    continue
                inline = _resolve_inline_var_path(neutral, lib, path_vars) if want_path else None
                if inline is None:
                    return None
                out.append(inline)
            else:
                out.append(neutral.replace(NUL, "$").replace(TCK, "`").replace("\x00b", "\\"))
        else:  # bare
            m = _VARREF.match(val)
            if m:
                repl = (path_vars if want_path else literal_vars).get(m.group(1))
                if repl is None:
                    return None
                out.append(repl)
            elif "$" in val:
                inline = _resolve_inline_var_path(val, lib, path_vars) if want_path else None
                if inline is None:
                    return None
                out.append(inline)
            else:
                out.append(val)
    return "".join(out)


# ── call-site extraction ────────────────────────────────────────────────────
def extract_pins(text, lib, overrides, helper_specs=None):
    """Yield dicts for each pin call site: resolved (literal, file) or unresolved.

    ``helper_specs`` defaults to the built-in ``HELPERS`` table. A caller that
    also wants a source's own pin wrappers in the population passes the specs
    ``helper_specs_for_source`` inferred for that exact text; only entries whose
    literal selector is a positional index are usable here, so a fixed-literal
    wrapper spec is skipped rather than yielding a synthetic site.
    """
    specs = HELPERS if helper_specs is None else helper_specs
    maps_by_line = variable_maps_by_line(text, lib, overrides)
    for lineno, line in join_logical_lines(text):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        first = stripped.split(None, 1)
        if not first or first[0] not in specs:
            continue
        toks = tokenize(stripped)
        if not toks or "".join(v for _, v in toks[0]) != first[0]:
            continue
        path_vars, literal_vars = maps_by_line[lineno]
        args = toks[1:]
        lit_idx, file_idx, default_file = specs[first[0]]
        if not isinstance(lit_idx, int):
            continue
        if lit_idx >= len(args):
            # A pin call with too few args to carry its literal — malformed, but still
            # surfaced as unresolved (literal=None) rather than silently dropped, honoring
            # the "never silently skipped" contract.
            yield {"lineno": lineno, "helper": first[0], "literal": None, "file": None}
            continue
        literal = resolve_arg(args[lit_idx], literal_vars, path_vars, want_path=False, lib=lib)
        if file_idx < len(args):
            fpath = resolve_arg(args[file_idx], literal_vars, path_vars, want_path=True, lib=lib)
        elif default_file is not None:
            fpath = path_vars.get(default_file)
        else:
            fpath = None
        yield {
            "lineno": lineno,
            "helper": first[0],
            "literal": literal,
            "file": fpath,
        }


# ── comment / rendering analysis of a target file ───────────────────────────
def hash_comment_regions(lines):
    """Return list of (lineno, comment_text) for #-comment regions, quote-aware."""
    out = []
    for i, line in enumerate(lines, 1):
        insq = indq = False
        start = None
        j = 0
        while j < len(line):
            c = line[j]
            if c == "\\" and (insq or indq):
                j += 2
                continue
            if c == "'" and not indq:
                insq = not insq
            elif c == '"' and not insq:
                indq = not indq
            elif (
                c == "#"
                and not insq
                and not indq
                and (j == 0 or line[j - 1] in " \t")
            ):
                # A `#` starts a shell/py comment only at a word boundary (line start
                # or after whitespace) — mirroring tokenize()'s `not cur` rule. Keying
                # on any unquoted `#` misclassified a mid-word `#` (e.g. `url#anchor`)
                # as a comment start, moving operative text into the "comment" region
                # and making a real collision go UNFLAGGED (a fail-open in the guard
                # direction).
                start = j
                break
            j += 1
        if start is not None:
            out.append((i, line[start:]))
    return out


def md_comment_text(text):
    return "\n".join(re.findall(r"<!--(.*?)-->", text, flags=re.DOTALL))


def md_fenced_hash_comment_spans(text):
    """Return {lineno: comment_text} for #-comment regions inside fenced code
    blocks (``` / ~~~, language-tagged or indented) of a markdown target.

    The #375 .md arm scanned only HTML ``<!-- … -->`` regions; a pin literal
    quoted in a ``#`` comment inside a ```` ```bash ```` fence of a skill bundle
    was folded into the operative "outside" text, so a #370-class count-inflation
    collision there went unflagged (issue #394). Extracting these fenced ``#``
    comments lets the .md arm subtract them from "outside" symmetrically with the
    .sh/.py arm, so such a collision is flagged while a literal living ONLY in a
    fenced comment (the ``lit in outside`` conjunct) still is not.

    Fence tracking mirrors CommonMark's opener/closer rules enough for this use:
    an opening fence is a line whose first non-space run is >=3 backticks or
    tildes (a backtick opener's info string may not itself contain a backtick);
    the matching closer is the same marker char, at least as long, with only
    whitespace after it. Language-tagged fences and fences indented up to 3
    spaces are handled; a run indented >=4 spaces is CommonMark *indented code*,
    NOT a fence, so it is deliberately not treated as a fence marker — otherwise
    a deeply-indented ``` in prose would spuriously open a never-closed fence and
    fold every following operative ``#``-line into the comment region, a
    fail-open that could hide a real #370-class collision (issue #394 review).
    The fence markers themselves are never treated as content.

    An UNTERMINATED fence fails closed (issue #394 review): a fence opener that
    never meets a matching closer before EOF is suspect (a stray/unbalanced ```
    in a malformed target), so its content lines are discarded rather than folded
    into the comment region — otherwise every following operative ``#``-line (an
    ATX heading, say) would be stripped out of "outside", masking a real
    #370-class collision. Only lines inside a PROPERLY CLOSED fence are trusted.
    """
    lines = text.split("\n")
    fence = None  # (char, length) while inside a fence, else None
    inside = []  # (lineno, line) content lines strictly inside fences
    committed = 0  # inside[:committed] are lines from PROPERLY CLOSED fences
    for i, line in enumerate(lines, 1):
        # 0-3 leading spaces only (>=4 is indented code, not a fence marker).
        m = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None:
            # A backtick opener's info string must not contain a backtick.
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
            continue
        if (
            m
            and m.group(1)[0] == fence[0]
            and len(m.group(1)) >= fence[1]
            and m.group(2).strip() == ""
        ):
            fence = None
            committed = len(inside)  # this fence closed cleanly — trust its lines
            continue
        inside.append((i, line))
    # Fail closed on an UNTERMINATED trailing fence (issue #394 review): a stray or
    # unbalanced opener that never meets a closer is suspect, so drop its content
    # rather than fold every following operative `#`-line out of "outside" and mask a
    # real #370-class collision. Only PROPERLY CLOSED fences' lines are trusted.
    if fence is not None:
        inside = inside[:committed]
    spans = {}
    for idx, ctext in hash_comment_regions([ln for _, ln in inside]):
        spans[inside[idx - 1][0]] = ctext
    return spans


def normalize_ws(s):
    return " ".join(s.split())


def multiliteral_help_renderings(text):
    """Yield the concatenated rendering of each multi-literal argparse help=.

    Detects `help=` followed by two or more adjacent string literals (Python's
    implicit string concatenation, optionally parenthesized / across lines).
    """
    out = []
    for m in re.finditer(r"help\s*=\s*\(?", text):
        i = m.end()
        lits = []
        while True:
            # skip whitespace and line continuations
            while i < len(text) and text[i] in " \t\r\n\\":
                i += 1
            if i >= len(text) or text[i] not in "'\"":
                break
            q = text[i]
            # handle triple quotes
            if text[i : i + 3] == q * 3:
                end = text.find(q * 3, i + 3)
                if end == -1:
                    break
                lits.append(text[i + 3 : end])
                i = end + 3
            else:
                j = i + 1
                buf = []
                while j < len(text) and text[j] != q:
                    if text[j] == "\\" and j + 1 < len(text):
                        buf.append(text[j + 1])
                        j += 1
                    else:
                        buf.append(text[j])
                    j += 1
                lits.append("".join(buf))
                i = j + 1
        if len(lits) >= 2:
            out.append("".join(lits))
    return out


# ── the two guards ──────────────────────────────────────────────────────────
def _target_ext(path, md_targets):
    """Extension used to pick the comment syntax; a `--md`-flagged target (e.g. the
    extensionless mktemp'd skill bundle, which is markdown) is treated as `.md`."""
    if path in md_targets:
        return ".md"
    return os.path.splitext(path)[1]


def _strip_line_spans(lines, spans):
    """Remove each line-keyed comment suffix from `lines`, returning the joined
    "outside-comments" text. Shared by the hash arm and the .md fenced-#-comment
    arm (issue #394) so the two subtractions stay in lockstep rather than being
    two hand-maintained copies of the same off-by-one-prone slice."""
    return "\n".join(
        (line[: len(line) - len(spans[i])] if i in spans else line)
        for i, line in enumerate(lines, 1)
    )


def _lint_view(path, ext, cache):
    """Memoized per-target-file comment analysis (read + comment regions + the
    outside-comments text). Many pins share a target, so this is derived once per
    file rather than once per pin."""
    v = cache.get(path)
    if v is not None:
        return v
    ftext, err = _read_target(path)
    if err is not None:
        v = ("unreadable", err, None)
        cache[path] = v
        return v
    if ext in COMMENT_HASH_EXTS:
        lines = ftext.split("\n")
        comment_spans = {cln: ctext for cln, ctext in hash_comment_regions(lines)}
        outside = _strip_line_spans(lines, comment_spans)
        v = ("hash", comment_spans, outside)
    elif ext in COMMENT_MD_EXTS:
        # Comment regions of a .md target are BOTH its HTML <!-- … --> spans AND
        # the #-comments inside its fenced code blocks (issue #394). Union them
        # into `comments`, and subtract both from `outside` symmetrically so a
        # literal living only in a fenced # comment is removed from "outside"
        # (preserving the `lit in outside` conjunct) exactly as the .sh/.py arm.
        fenced_spans = md_fenced_hash_comment_spans(ftext)
        comment_text = md_comment_text(ftext)
        if fenced_spans:
            comment_text = comment_text + "\n" + "\n".join(fenced_spans.values())
        without_fenced = _strip_line_spans(ftext.split("\n"), fenced_spans)
        outside = re.sub(r"<!--.*?-->", "", without_fenced, flags=re.DOTALL)
        v = ("md", comment_text, outside)
    else:
        v = ("none", None, None)
    cache[path] = v
    return v


def _wrapped_view(path, cache):
    """Memoized per-target-file wrapped-literal analysis (lines + whitespace-normalized
    whole file + normalized multi-literal help= renderings). Derived once per file."""
    v = cache.get(path)
    if v is not None:
        return v
    ftext, err = _read_target(path)
    if err is not None:
        v = ("unreadable", err, None)
        cache[path] = v
        return v
    helps = [normalize_ws(r) for r in multiliteral_help_renderings(ftext)] if path.endswith(".py") else []
    v = (ftext.split("\n"), normalize_ws(ftext), helps)
    cache[path] = v
    return v


def _emit(sink, line):
    """The single stdout chokepoint for every finding line on a ``--strict``-covered
    path (issue #687). Appends to ``sink`` — so ``--strict`` can key rc 3 on
    "at least one line was written to stdout" — and prints the line unchanged, so
    the stdout/stderr bytes are byte-identical with and without ``--strict``.

    Defined OUTSIDE the ``run_lint`` … end-of-``_emit_wrapped_or_absent`` guard
    range that ``lib/test/run.sh``'s issue-#687 emit-helper guard anchors over, so
    the guard's ``grep -cE`` count of raw stdout-writing forms inside that range
    stays 0. A future finding arm on a covered path MUST route through this helper
    (never a bare ``print(`` / ``sys.stdout.write`` / ``os.write(1``) or the guard
    goes RED; informational output on a covered path must go to ``sys.stderr``."""
    sink.append(line)
    print(line)


def run_lint(pin_source, lib, overrides, md_targets, strict=False):
    text = _read(pin_source)
    unresolved = 0
    resolved = 0
    collisions = []
    view_cache = {}
    sink = []
    for pin in extract_pins(text, lib, overrides):
        if pin["literal"] is None or pin["file"] is None:
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"literal={'?' if pin['literal'] is None else 'ok'}\t"
                f"file={'?' if pin['file'] is None else pin['file']}\n"
            )
            continue
        if not os.path.isfile(pin["file"]):
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"target-missing={pin['file']}\n"
            )
            continue
        ext = _target_ext(pin["file"], md_targets)
        kind, comments, outside = _lint_view(pin["file"], ext, view_cache)
        if kind == "unreadable":
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"target-unreadable={pin['file']} ({comments})\n"
            )
            continue
        resolved += 1
        lit = pin["literal"]
        # The defect (#370): a comment occurrence that COEXISTS with an operative
        # occurrence — it inflates the count / can mask a refactored-away operative
        # site. A literal that lives ONLY in a comment (an SPDX-header pin, a
        # deliberately comment-targeted contract) is the pin's intended home, not the
        # count-inflation defect, so it is NOT flagged. Hence: flag only when the
        # literal appears in a comment AND ALSO outside every comment region.
        if kind == "hash":
            in_comment_line = next((cln for cln, ctext in comments.items() if lit in ctext), None)
            if in_comment_line is not None and lit in outside:
                collisions.append((pin, in_comment_line))
        elif kind == "md":
            if lit in comments and lit in outside:
                collisions.append((pin, None))
    for pin, cln in collisions:
        loc = f":{cln}" if cln else ""
        _emit(sink, f"COLLISION\t{pin['file']}{loc}\t{pin['helper']}@{pin_source}:{pin['lineno']}\t{pin['literal']}")
    sys.stderr.write(f"UNRESOLVED-COUNT\t{unresolved}\n")
    sys.stderr.write(f"RESOLVED-COUNT\t{resolved}\n")
    return 3 if strict and sink else 0


# ── #661 relocation diagnosis ───────────────────────────────────────────────
def _git_ls_files():
    """Enumerate tracked files with the granted ``git ls-files``. Returns
    (paths, None) on success or (None, reason) fail-closed on any error / empty
    output — the caller must NOT collapse a failed enumeration to "deleted"."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "-z"], capture_output=True, text=True, check=False
        )
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError (a ValueError, NOT an OSError) can surface from text=True
        # eager decoding of a non-UTF-8 tracked filename; catch it too so the docstring's
        # "fail-closed on any error" holds rather than crashing the scan.
        return None, f"git-ls-files-error:{type(exc).__name__}"
    if res.returncode != 0:
        return None, f"git-ls-files-rc:{res.returncode}"
    paths = [p for p in res.stdout.split("\0") if p]
    if not paths:
        return None, "git-ls-files-empty"
    return paths, None


def resolve_reloc_search_set(explicit_file):
    """Resolve the relocation search set. An explicit ``--reloc-search-set`` file
    (the git-free self-test path) wins; otherwise ``git ls-files``. A file that is
    unreadable, or a raw enumeration that fails or is empty, returns (None, reason)
    so the ABSENT branch fails closed rather than reporting a false deletion."""
    if explicit_file is not None:
        # Read through _read_target, which catches (OSError, UnicodeDecodeError):
        # a non-UTF-8 --reloc-search-set file raises UnicodeDecodeError (a ValueError,
        # NOT an OSError), and a bare `except OSError` would let it escape and crash
        # the scan instead of taking this docstring's fail-closed (None, reason) arm.
        raw, reason = _read_target(explicit_file)
        if reason is not None:
            return None, f"search-set-unreadable:{reason}"
        paths = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not paths:
            return None, "search-set-empty"
        return paths, None
    return _git_ls_files()


def _reloc_excluded(path, exclude_tokens):
    """A search-set path is excluded when any exclude token is a substring of it
    (the distinctive ``.prflow/vendor/`` / ``.prflow/tmp/`` trees, or a
    pin-source path/prefix) OR resolves to the same file (abspath-equal). Substring
    matches a temp-dir stand-in like ``/tmp/xxx/.prflow/vendor/copy.md`` against the
    same token a repo-relative ``.prflow/vendor/…`` path does; the abspath-equality
    arm is load-bearing for the pin-source auto-exclude, because ``git ls-files``
    emits **repo-relative** paths (``lib/test/run.sh``) while the pin-source token is
    the **absolute** ``$LIB/test/run.sh`` — a substring test alone never matches those
    two spellings, so without abspath-equality the auto-exclude would silently no-op
    and a deleted pin's literal would self-match its own declaration in run.sh."""
    apath = os.path.abspath(path)
    for tok in exclude_tokens:
        if not tok:
            continue
        if tok in path or apath == os.path.abspath(tok):
            return True
    return False


def _literal_resolves_in(lit, nlit, path, cache):
    """Tri-state: ``True`` when the pin literal resolves in a candidate file (on a
    single line, in the whitespace-normalized rendering — a wrapped-adjacent-literal
    destination, #375 — or in a multi-literal argparse help= rendering), ``False``
    when the file was read but does not contain it, and ``None`` when the candidate
    is UNREADABLE. The None arm is load-bearing: a swallowed read error on the very
    file a literal moved into would otherwise let ``diagnose_relocation`` report a
    false ``deleted`` — the AC5 masquerade at per-candidate granularity — so the
    caller must surface unreadable candidates rather than treat them as 'not here'."""
    view = _wrapped_view(path, cache)
    if view[0] == "unreadable":
        return None
    lines, nfile, helps = view
    if any(lit in ln for ln in lines):
        return True
    if nlit and nlit in nfile:
        return True
    return bool(nlit and any(nlit in h for h in helps))


def diagnose_relocation(lit, nlit, target, search_paths, exclude_tokens, cache):
    """Given the resolved (non-None) search set, return
    ``(sorted_dests, unreadable_paths)``: the files (excluding the
    pin-source/vendor/tmp set and the target itself) where the literal resolves, and
    the candidates that could not be read. An empty ``dests`` with an empty
    ``unreadable`` means a genuine deletion; an empty ``dests`` with a non-empty
    ``unreadable`` means the diagnosis is INCOMPLETE — the caller must not claim a
    clean deletion over swallowed read errors (fail-closed, AC5 spirit)."""
    dests = []
    unreadable = []
    for path in search_paths:
        if path == target or _reloc_excluded(path, exclude_tokens):
            continue
        resolved = _literal_resolves_in(lit, nlit, path, cache)
        if resolved is None:
            unreadable.append(path)
        elif resolved:
            dests.append(path)
    return sorted(set(dests)), sorted(set(unreadable))


def run_wrapped(pin_source, lib, overrides, md_targets,
                reloc=False, reloc_search_file=None, reloc_exclude=None,
                strict=False):
    text = _read(pin_source)
    unresolved = 0
    resolved = 0
    view_cache = {}
    sink = []
    # Resolve the relocation search set ONCE (issue #661) — only when --reloc is on.
    # A resolution failure is carried as (None, reason): the ABSENT branch then reports
    # "relocation diagnosis unavailable" and never a false "deleted". The pin-source file
    # is auto-excluded (a pin literal is present in its own declaration by construction),
    # alongside the always-on vendor/tmp trees and any --reloc-exclude substring token.
    reloc_paths, reloc_err = (None, None)
    reloc_excludes = ()
    if reloc:
        reloc_paths, reloc_err = resolve_reloc_search_set(reloc_search_file)
        reloc_excludes = (
            (pin_source,) + tuple(RELOC_DEFAULT_EXCLUDES) + tuple(reloc_exclude or ())
        )
    for pin in extract_pins(text, lib, overrides):
        if pin["literal"] is None or pin["file"] is None:
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"literal={'?' if pin['literal'] is None else 'ok'}\t"
                f"file={'?' if pin['file'] is None else pin['file']}\n"
            )
            continue
        if not os.path.isfile(pin["file"]):
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"target-missing={pin['file']}\n"
            )
            continue
        lines, nfile, helps = _wrapped_view(pin["file"], view_cache)
        if lines == "unreadable":
            unresolved += 1
            sys.stderr.write(
                f"UNRESOLVED\t{pin_source}:{pin['lineno']}\t{pin['helper']}\t"
                f"target-unreadable={pin['file']} ({nfile})\n"
            )
            continue
        resolved += 1
        lit = pin["literal"]
        if any(lit in ln for ln in lines):
            # The phrase IS on a line; nothing to flag.
            continue
        # occurs on no single line: distinguish a multi-literal help= (needs the
        # rendered surface), a whitespace-wrapped phrase, and a genuinely-absent one.
        nlit = normalize_ws(lit)
        if nlit and any(nlit in h for h in helps):
            _emit(
                sink,
                f"HELP\t{pin['file']}\t{pin['helper']}@{pin_source}:{pin['lineno']}\t"
                f"pin targets a multi-literal argparse help= string; pin the RENDERED "
                f"surface (captured --help output / real stderr), not the source\t{lit}"
            )
            continue
        _emit_wrapped_or_absent(
            pin, pin_source, nlit, nfile, lit,
            reloc=reloc, reloc_paths=reloc_paths, reloc_err=reloc_err,
            reloc_excludes=reloc_excludes, cache=view_cache, sink=sink,
        )
    sys.stderr.write(f"UNRESOLVED-COUNT\t{unresolved}\n")
    sys.stderr.write(f"RESOLVED-COUNT\t{resolved}\n")
    return 3 if strict and sink else 0


def _emit_wrapped_or_absent(pin, pin_source, nlit, nfile, lit, sink,
                            reloc=False, reloc_paths=None, reloc_err=None,
                            reloc_excludes=(), cache=None):
    site = f"{pin['helper']}@{pin_source}:{pin['lineno']}"
    if nlit and nlit in nfile:
        _emit(
            sink,
            f"WRAPPED\t{pin['file']}\t{site}\t"
            f"phrase occurs on NO single line but IS present in the whitespace-normalized "
            f"rendering — a wrapped-literal blind spot; pin the rendered surface\t{lit}"
        )
        return
    if not reloc:
        # Relocation diagnosis off — the pre-#661 ABSENT emit, byte-identical.
        _emit(
            sink,
            f"ABSENT\t{pin['file']}\t{site}\t"
            f"phrase absent from the target entirely (not merely wrapped)\t{lit}"
        )
        return
    if reloc_paths is None:
        # The search set could not be enumerated (git ls-files failed/empty, or an
        # unreadable --reloc-search-set). Fail closed: report unavailability on stderr
        # and NEVER collapse to "deleted" — a failed enumeration is not evidence of
        # deletion. stdout still carries an ABSENT line so a real absent pin stays RED.
        sys.stderr.write(
            f"RELOC-UNAVAILABLE\t{pin['file']}\t{site}\t{reloc_err}\n"
        )
        _emit(
            sink,
            f"ABSENT\t{pin['file']}\t{site}\t"
            f"phrase absent from the target entirely; relocation diagnosis unavailable "
            f"({reloc_err})\t{lit}"
        )
        return
    dests, unreadable = diagnose_relocation(
        lit, nlit, pin["file"], reloc_paths, reloc_excludes, cache or {}
    )
    if dests:
        _emit(
            sink,
            f"RELOCATED\t{pin['file']}\t{site}\t"
            f"relocated to {', '.join(dests)}; update the pin target\t{lit}"
        )
    elif unreadable:
        # Fail closed: candidates could not be read, so the literal may have moved into
        # one of them — do NOT claim a clean deletion. Surface each unreadable candidate
        # on stderr and say the diagnosis is incomplete (AC5 masquerade guard).
        for path in unreadable:
            sys.stderr.write(f"RELOC-CANDIDATE-UNREADABLE\t{pin['file']}\t{site}\t{path}\n")
        _emit(
            sink,
            f"ABSENT\t{pin['file']}\t{site}\t"
            f"phrase absent from the target; relocation diagnosis INCOMPLETE "
            f"({len(unreadable)} candidate(s) unreadable — not a confirmed deletion)\t{lit}"
        )
    else:
        _emit(
            sink,
            f"ABSENT\t{pin['file']}\t{site}\t"
            f"phrase absent from the target AND from the scoped tracked-file set — "
            f"deleted (not found anywhere)\t{lit}"
        )


# ── #666 mutation-routing: static-pin declaration gate ───────────────────────
# Behavioral regressions belong in ordinary executable tests. A new static pin is
# permitted only for a typed machine/executable boundary, so this diff-scoped,
# fail-closed gate requires every added static pin call to carry that declaration.
# Retired mutation-taking helpers are rejected separately by the zero-population
# census before this classifier runs.

# Helpers that MUST declare (non-mutation-taking pins) — complete by construction.
REQUIRED_DECLARATION_HELPERS = frozenset(
    {
        "assert_pin_unique",
        "assert_pin_red_on_removal",
        "devflow_module_pin_unique",
        "devflow_module_pin_present",
    }
)
# Historical parsing vocabulary only. Membership carries no live authoring exemption;
# `mutation-routing-worktree` requires the corresponding census to remain empty.
MUTATION_TAKING_HELPERS = frozenset(
    {"assert_pin_red_under", "devflow_module_pin_red_under", "assert_count_red_under"}
)
# Count-based guards. The legacy synthetic `mutation-routing` command still
# exempts them by helper (they are absent from REQUIRED_DECLARATION_HELPERS),
# but the required `mutation-routing-worktree` classifier no longer does: issue
# #925 removed the `count-helper` short-circuit in scan_changed_sources so a
# NEW or MODIFIED count-helper pin whose literal resolves into prose is reported
# exactly as the equivalent static-helper or raw-grep pin, with no spelling that
# skips the prose adjudication.
COUNT_HELPERS = frozenset({"pin_count", "devflow_module_pin_count"})

# The declaration marker is recognized only in a real comment region; a quoted
# substring never exempts the site.
STRUCTURAL_PIN_OK_MARKER = "# structural-pin-ok:"

STRUCTURAL_PIN_CATEGORIES = frozenset(
    {
        "helper-contract",
        "schema-config-vocabulary",
        "security-credential-boundary",
        "machine-sentinel-provenance",
        "routing-dispatch-contract",
        "lifecycle-state-transition",
        "generated-artifact-identity",
        "cross-file-phase-contract",
    }
)

# ── Step 1 of the issue-948 routing ladder: does a program demonstrably read it? ──
#
# The corpus is the tracked machine-consumer surface: `scripts/**`, `lib/**`
# excluding the suite's own `lib/test/**`, and `.github/**`. `docs/**`, `skills/**`
# and the repository's markdown are deliberately NOT consumers — a sentence
# reappearing in prose is the very thing the policy retired.
MACHINE_CONSUMER_PATH_PREFIXES = ("scripts/", "lib/", ".github/")
MACHINE_CONSUMER_EXCLUDED_PREFIXES = ("lib/test/",)

# A "distinctive token" is a machine-identifier-shaped word: >= 8 characters,
# >= 3 letters, and at least one of these shapes. The shape requirement is the
# whole point of the rule — a common English word (however long) is NOT
# distinctive, so an unrelated file mentioning "configuration" or "verdict" can
# never satisfy step 1. Two-segment kebab words that read as ordinary English
# ("fail-closed", "best-effort") are excluded on purpose: a kebab token qualifies
# only with a digit or a third segment.
_DISTINCTIVE_TOKEN_TRIM = "\"'`(),;:.*!?[]{}<>|&"
_DOTTED_TOKEN_RE = re.compile(r"[A-Za-z0-9][.][A-Za-z0-9]")
# The accepted shapes, each paired with the name it is known by in the docs. One
# hit qualifies the token; which shape matched is not part of the answer (the
# evidence string names the matched TOKEN, which is what makes a step-1 pass
# attributable), so the names are documentation of a closed set, not routing.
_DISTINCTIVE_TOKEN_SHAPES = (
    ("snake", lambda token: "_" in token),
    ("path", lambda token: "/" in token),
    ("marker", lambda token: ":" in token),
    ("flag", lambda token: token.startswith("--")),
    ("dotted", lambda token: _DOTTED_TOKEN_RE.search(token) is not None),
    (
        "numbered",
        lambda token: "-" in token and any(ch.isdigit() for ch in token),
    ),
    (
        "kebab",
        lambda token: len([part for part in token.split("-") if len(part) >= 2]) >= 3,
    ),
)


def is_machine_consumer_path(path):
    """True for a repo-relative path in the step-1 machine-consumer corpus."""
    if path.startswith(MACHINE_CONSUMER_EXCLUDED_PREFIXES):
        return False
    return path.startswith(MACHINE_CONSUMER_PATH_PREFIXES)


def distinctive_consumer_tokens(literal):
    """Return the machine-identifier-shaped tokens of ``literal``, in order.

    Whitespace-split, then trimmed of surrounding quoting/sentence punctuation
    (an interior ``:``/``.``/``-`` is part of the token and is never trimmed).
    A literal with no such token yields ``()`` — which routes its pin to step 2
    rather than rejecting it.
    """
    if not literal:
        return ()
    tokens = []
    for raw in literal.split():
        token = raw.strip(_DISTINCTIVE_TOKEN_TRIM)
        if len(token) < 8 or token in tokens:
            continue
        if sum(1 for ch in token if ch.isalpha()) < 3:
            continue
        if any(matches(token) for _, matches in _DISTINCTIVE_TOKEN_SHAPES):
            tokens.append(token)
    return tuple(tokens)


def _consumer_token_pattern(tokens):
    """One boundary-anchored alternation over ``tokens`` (single-pass search)."""
    if not tokens:
        return None
    return re.compile(
        r"(?<![\w-])(?:"
        + "|".join(re.escape(token) for token in tokens)
        + r")(?![\w-])"
    )


def build_machine_consumer_corpus(consumer_sources):
    """Return the ordered ``(path, operative_text)`` step-1 corpus.

    ``consumer_sources`` maps repo-relative path to raw file text. Only
    consumer-surface paths are kept, and for ``#``-comment languages the comment
    regions are SUBTRACTED: a literal quoted in a ``lib/*.sh`` comment is not a
    program reading it. That subtraction can only move a site from step 1 to
    step 2, which is the safe direction.
    """
    corpus = []
    for path in sorted(consumer_sources or ()):
        if not is_machine_consumer_path(path):
            continue
        text = consumer_sources[path]
        if os.path.splitext(path)[1].lower() in COMMENT_HASH_EXTS:
            lines = text.split("\n")
            spans = {lineno: comment for lineno, comment in hash_comment_regions(lines)}
            text = _strip_line_spans(lines, spans)
        corpus.append((path, text))
    return tuple(corpus)


def machine_consumer_evidence(literal, corpus):
    """Return step-1 evidence that a program reads ``literal``, else ``None``.

    Evidence is either the whole literal occurring in a consumer file's operative
    text, or one of its distinctive tokens occurring there as a whole token. A
    ``None`` return means only "no consumer was FOUND" — a generic consumer (a
    helper that walks a routing table row by row, a renderer driven by a manifest)
    names no individual literal, so this search misses it by construction and its
    answer routes to step 2 instead of rejecting the pin.
    """
    if not literal or not corpus:
        return None
    tokens = distinctive_consumer_tokens(literal)
    pattern = _consumer_token_pattern(tokens)
    for path, text in corpus:
        if literal in text:
            return f"{path} contains the pinned literal"
        if pattern is None:
            continue
        match = pattern.search(text)
        if match is not None:
            return f"{path} contains the distinctive token {match.group(0)!r}"
    return None


def ledger_records_boundary(literal_key, current_adjudications):
    """Step 2: True only when the ledger's current state reads ``boundary``.

    Fails closed by construction: an unestablished ledger (``None``), an empty
    one, an absent row, and a row in any other bucket all return False. The
    production caller never reaches here with an unreadable ledger at all —
    ``analyze_adjudication_changes`` raises ``InfrastructureError`` first — so
    there is no path on which unreadability becomes a pass.
    """
    if literal_key is None or not current_adjudications:
        return False
    state = current_adjudications.get(literal_key)
    return state is not None and state[0] == "boundary"


# This population is intentionally committed and independent of the registry. The
# production gate compares the two sets exactly, so registering a new focused module
# without adding it here fails closed instead of silently leaving its pins unscanned.
AUDITED_PIN_SOURCES = frozenset(
    {
        "lib/test/run.sh",
        "lib/test/modules/workflow-flight-recorder.sh",
        "lib/test/modules/review-and-fix-contract.sh",
        "lib/test/modules/create-issue-contract.sh",
        "lib/test/modules/capability-profiles.sh",
        "lib/test/modules/regenerate-artifacts.sh",
        "lib/test/modules/installer-wiring.sh",
        "lib/test/modules/harness-python-guards.sh",
        "lib/test/modules/prompt-extension-reader.sh",
        "lib/test/modules/review-trigger-helpers.sh",
        "lib/test/modules/review-stall-backstop.sh",
        "lib/test/modules/retrospective-lifecycle.sh",
        "lib/test/modules/experiment-records.sh",
        "lib/test/modules/efficiency-trace-telemetry.sh",
        "lib/test/modules/issue-audit-state.sh",
        "lib/test/modules/tier1-rename-migration.sh",
        "lib/test/modules/parallel-suite-runner.sh",
        "lib/test/modules/phase2-durability-checkpoint.sh",
        "lib/test/modules/review-contract.sh",
        "lib/test/modules/workpad-cli.sh",
        "lib/test/modules/implement-contract.sh",
    }
)

_DEF_LINE_RE = re.compile(r"^\w+\s*\(\)")


class StructuralDeclaration(NamedTuple):
    category: str
    rationale: str


class GuardSite(NamedTuple):
    source_path: str
    line_start: int
    line_end: int
    family: str
    helper: str | None
    literal: str | None
    target_path: str | None
    declaration: StructuralDeclaration | None
    declaration_error: str | None
    # The resolved member files of a concatenated bundle target, set only when
    # ``target_path`` is None because the target is a runtime bundle (issue #956).
    target_members: tuple | None = None
    # The classifier-equivalent resolved-target token (issue #1006): a repo-
    # relative POSIX path for a file target, the ``/__pin_corpus_runtime__/<var>``
    # placeholder for a runtime bundle, or None for a defaulted/unresolvable
    # target -- the same three shapes ``pin-corpus-classifier.py`` writes into the
    # retirement manifests' ``resolved_target`` column. Retirement is keyed on
    # (source_file, helper, literal, this token) so a literal retired at one
    # site does not poison a retained pin sharing that literal at a different site.
    resolved_target_token: str | None = None

    def retirement_key(self):
        """This site's retirement identity, or None when it has no literal.

        The single place a site is turned into a retirement key (issue #1006),
        so ``scan_changed_sources``' two loops cannot disagree about what a
        site's identity is.
        """
        if self.literal is None:
            return None
        return _site_retirement_key(
            self.source_path,
            self.helper,
            self.literal,
            self.resolved_target_token,
        )


class FilePatch(NamedTuple):
    old_path: str | None
    new_path: str | None
    added_lines: frozenset[int]
    deleted_lines: frozenset[int]


class InfrastructureError(RuntimeError):
    """The blocking gate could not establish the population or comparison."""


_ADJUDICATION_KEY_RE = re.compile(r"(?:literal|site):[0-9a-f]{64}\Z")
_FINAL_ADJUDICATION_BUCKETS = frozenset(
    {
        "suite-internal",
        "required-copy",
        "boundary",
        "generated",
        "config-key",
        "prose-sole-copy",
        "prose-multi-copy",
    }
)
_CURRENT_ADJUDICATION_HEADER = ("adjudication_key", "bucket_final", "rationale")
_ADJUDICATION_DELTA_HEADER = ("adjudication_key", "base_state", "current_state")
_RETIRED_PIN_REVIVAL_HEADER = (
    "source_path",
    "family",
    "helper",
    "literal_key",
    "target_path",
    "structural_category",
    "structural_rationale",
)
_ADJUDICATION_BUNDLE_ROOT = ".prflow/logs/pin-corpus-adjudication-changes"
# Revision-side reads only.  The .devflow/ -> .prflow/ state-directory rename
# (issue #1002) moved every frozen record with its directory, so a read against a
# revision that predates the move must address the superseded spelling.
_SUPERSEDED_STATE_DIR_PREFIX = ".devflow/"
_STATE_DIR_PREFIX = ".prflow/"
_ADJUDICATION_TABLE_PATH = "lib/test/pin-corpus-adjudications.tsv"
_RETIREMENT_MANIFEST_SPECS = {
    ".prflow/logs/residual-prose-retirement-manifest.tsv": (
        (
            "source_file",
            "helper",
            "assertion_name",
            "literal",
            "resolved_target",
            "target_defaulted",
            "surface",
            "disposition",
            "rationale",
        ),
        frozenset({"RETIRE_PROSE", "RETAIN_BOUNDARY"}),
        frozenset({"RETIRE_PROSE"}),
    ),
    ".prflow/logs/residual-required-copy-retirement-manifest.tsv": (
        (
            "source_file",
            "helper",
            "assertion_name",
            "literal",
            "resolved_target",
            "target_defaulted",
            "disposition",
            "rationale",
        ),
        frozenset({"RETIRE_PROSE", "RETAIN_BOUNDARY"}),
        frozenset({"RETIRE_PROSE"}),
    ),
    ".prflow/logs/red-on-removal-retirement-manifest.tsv": (
        (
            "source_file",
            "helper",
            "assertion_name",
            "literal",
            "resolved_target",
            "target_defaulted",
            "disposition",
            "call_sha256",
        ),
        frozenset(
            {
                "convert_presence",
                "prose_retire",
                "redundant_retire",
                "replace_behavioral",
            }
        ),
        frozenset({"prose_retire", "redundant_retire"}),
    ),
}
class RevivalAuthorization(NamedTuple):
    source_path: str
    family: str
    helper: str
    literal_key: str
    target_path: str
    structural_category: str
    structural_rationale: str


class AdjudicationAnalysis(NamedTuple):
    findings: list[str]
    base: dict[str, tuple[str, str]]
    current: dict[str, tuple[str, str]]
    delta: dict[
        str,
        tuple[tuple[str, str] | None, tuple[str, str] | None],
    ]
    revival_authorizations: frozenset[RevivalAuthorization]


def _parse_exact_tsv(text, header, label):
    """Return strict TSV rows after rejecting transport and shape ambiguity."""
    if not isinstance(text, str):
        raise InfrastructureError(f"{label} text is not a string")
    if "\r" in text:
        raise InfrastructureError(f"{label} contains carriage-return bytes")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as exc:
        raise InfrastructureError(f"{label} is malformed TSV: {exc}") from exc
    if not rows or tuple(rows[0]) != header:
        raise InfrastructureError(f"{label} has an invalid header")
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise InfrastructureError(f"{label} has invalid cell count at line {number}")
        if any("\n" in cell for cell in row):
            raise InfrastructureError(f"{label} has multiline cell at line {number}")
    return rows[1:]


def _validate_adjudication_key(key, label):
    if not isinstance(key, str) or _ADJUDICATION_KEY_RE.fullmatch(key) is None:
        raise InfrastructureError(f"{label} has invalid adjudication key: {key!r}")


def _validate_adjudication_state(state, label):
    if (
        not isinstance(state, tuple)
        or len(state) != 2
        or not all(isinstance(value, str) for value in state)
    ):
        raise InfrastructureError(f"{label} is not a two-string adjudication state")
    bucket, rationale = state
    if bucket not in _FINAL_ADJUDICATION_BUCKETS:
        raise InfrastructureError(f"{label} has invalid final bucket: {bucket!r}")
    if not rationale:
        raise InfrastructureError(f"{label} has empty rationale")


def parse_current_adjudications(text):
    """Strictly parse the live current-state adjudication table."""
    result = {}
    for number, (key, bucket, rationale) in enumerate(
        _parse_exact_tsv(text, _CURRENT_ADJUDICATION_HEADER, "adjudication table"),
        start=2,
    ):
        _validate_adjudication_key(key, f"adjudication table line {number}")
        _validate_adjudication_state(
            (bucket, rationale), f"adjudication table line {number}"
        )
        if key in result:
            raise InfrastructureError(f"adjudication table has duplicate key: {key}")
        result[key] = (bucket, rationale)
    return result


def canonical_adjudication_state(state):
    """Render a nullable adjudication state in its sole accepted JSON form."""
    if state is None:
        return "null"
    _validate_adjudication_state(state, "adjudication state")
    return json.dumps(list(state), ensure_ascii=True, separators=(",", ":"))


def _parse_canonical_adjudication_state(text, label):
    if text == "null":
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InfrastructureError(f"{label} is not JSON: {exc}") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2
        or not all(isinstance(value, str) for value in decoded)
    ):
        raise InfrastructureError(f"{label} is not a two-string JSON state")
    state = tuple(decoded)
    _validate_adjudication_state(state, label)
    if text != canonical_adjudication_state(state):
        raise InfrastructureError(f"{label} is not compact canonical JSON")
    return state


def parse_adjudication_delta_manifest(text):
    """Parse a branch delta manifest without operation or count semantics."""
    result = {}
    for number, (key, base_text, current_text) in enumerate(
        _parse_exact_tsv(text, _ADJUDICATION_DELTA_HEADER, "adjudication delta manifest"),
        start=2,
    ):
        _validate_adjudication_key(key, f"adjudication delta manifest line {number}")
        if key in result:
            raise InfrastructureError(
                f"adjudication delta manifest has duplicate key: {key}"
            )
        result[key] = (
            _parse_canonical_adjudication_state(
                base_text, f"adjudication delta manifest line {number} base_state"
            ),
            _parse_canonical_adjudication_state(
                current_text, f"adjudication delta manifest line {number} current_state"
            ),
        )
    return result


def _validate_repo_relative_path(path, label):
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or path != Path(path).as_posix()
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise InfrastructureError(f"{label} has invalid repository-relative path: {path!r}")


def parse_retired_pin_revivals(text):
    """Parse exact normalized current-site revival authorizations."""
    result = set()
    for number, row in enumerate(
        _parse_exact_tsv(
            text,
            _RETIRED_PIN_REVIVAL_HEADER,
            "retired-pin revival manifest",
        ),
        start=2,
    ):
        (
            source_path,
            family,
            helper,
            literal_key,
            target_path,
            category,
            rationale,
        ) = row
        _validate_repo_relative_path(
            source_path, f"retired-pin revival manifest line {number}"
        )
        _validate_repo_relative_path(
            target_path, f"retired-pin revival manifest line {number}"
        )
        if not family or family != family.strip():
            raise InfrastructureError(
                f"retired-pin revival manifest line {number} has invalid family"
            )
        if helper != helper.strip():
            raise InfrastructureError(
                f"retired-pin revival manifest line {number} has invalid helper"
            )
        _validate_adjudication_key(
            literal_key, f"retired-pin revival manifest line {number}"
        )
        if not literal_key.startswith("literal:"):
            raise InfrastructureError(
                f"retired-pin revival manifest line {number} requires a literal key"
            )
        if category not in STRUCTURAL_PIN_CATEGORIES:
            raise InfrastructureError(
                f"retired-pin revival manifest line {number} has invalid structural category"
            )
        if not rationale or rationale != rationale.strip():
            raise InfrastructureError(
                f"retired-pin revival manifest line {number} has invalid structural rationale"
            )
        authorization = RevivalAuthorization(*row)
        if authorization in result:
            raise InfrastructureError(
                f"retired-pin revival manifest has duplicate revival: {authorization}"
            )
        result.add(authorization)
    return frozenset(result)


def _literal_adjudication_key(literal):
    return f"literal:{hashlib.sha256(literal.encode('utf-8')).hexdigest()}"


# Coupled with pin-corpus-classifier.py's recover_override_names (which writes
# f"/__pin_corpus_runtime__/{name}" into the manifests' resolved_target cell): the
# two scripts share no module, so this sentinel is a coupled invariant -- change one
# spelling and every runtime-bundle retirement key silently stops matching (#1006).
_RUNTIME_TARGET_PREFIX = "/__pin_corpus_runtime__/"


def _repo_relative_or_none(repo_root, target):
    """Return TARGET as a repo-relative POSIX path, or None when it is outside
    the repository. The non-raising copy of the abspath/commonpath/relpath
    computation the file otherwise repeats (see also the raising
    ``_relative_target_path``)."""
    try:
        root = os.path.abspath(repo_root)
        absolute = os.path.abspath(target)
        if os.path.commonpath((root, absolute)) != root:
            return None
    except ValueError:
        return None
    return os.path.relpath(absolute, root).replace(os.sep, "/")


def _resolved_target_token(target_path, var_name, members, repo_root):
    """The classifier-equivalent resolved-target token for a guard site (#1006).

    Matches ``pin-corpus-classifier.py``'s ``_portable_target`` for an in-repo file
    (a repo-relative POSIX path) and ``recover_override_names`` for a runtime bundle
    (the ``/__pin_corpus_runtime__/<var>`` placeholder), so a live site's token
    equals the manifest's ``resolved_target`` cell for the same site. Returns None
    for a target that is defaulted or an unresolvable bundle, AND -- unlike the
    classifier, which keeps the raw path -- for a target OUTSIDE the repository:
    the fail-toward-not-matched direction, which routes such a site through the
    ordinary policy rather than treating it as retired. (No pin target in this repo
    is out-of-repo, so the divergence is unreachable today; it is deliberately the
    safe direction if one ever is.)
    """
    if target_path is not None:
        return _repo_relative_or_none(repo_root, target_path)
    if members is not None and var_name:
        return f"{_RUNTIME_TARGET_PREFIX}{var_name}"
    return None


def _normalize_retirement_target(token):
    """Normalize a resolved-target token to the current state-directory spelling.

    The frozen manifests were written before the ``.devflow/`` -> ``.prflow/``
    rename (issue #1002) and record the superseded spelling, while a live site's
    token carries the current one. Applied symmetrically to both sides so a
    manifest ``.devflow/...`` target and a live ``.prflow/...`` target for one
    asset compare equal. Only the state-directory prefix is rewritten -- never
    arbitrary ``devflow`` tokens inside a filename -- so a frozen path like
    ``docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`` is left byte-identical. The #1002 rename
    also moved the vendored plugin sub-path (``vendor/devflow`` -> ``vendor/prflow``);
    that is deliberately NOT normalized here because no pin ``resolved_target`` is a
    vendored path (confirmed against all three frozen manifests), and the safe
    direction if one ever were is the loud fail-toward-not-matched of #1006.
    """
    if token is None:
        return None
    if token.startswith(_SUPERSEDED_STATE_DIR_PREFIX):
        return _STATE_DIR_PREFIX + token[len(_SUPERSEDED_STATE_DIR_PREFIX):]
    return token


def _site_retirement_key(source_file, helper, literal, target_token):
    """The retirement identity of a pin site: (source_file, helper, literal,
    resolved target). Keyed on the same manifest fields ``RevivalAuthorization``
    carries, so a retired literal covers only the site(s) it was retired at and a
    retained pin sharing that literal at a different site is not swept up (#1006).
    """
    payload = json.dumps(
        [
            source_file,
            helper or "",
            literal,
            _normalize_retirement_target(target_token),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"retire-site:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _strict_retirement_manifest_literals(text, path, spec):
    header, allowed_dispositions, retired_dispositions = spec
    if "\r" in text:
        raise InfrastructureError(f"retirement manifest contains carriage returns: {path}")
    lines = text.splitlines()
    while lines and lines[0].startswith("#"):
        lines.pop(0)
    if not lines or any(line.startswith("#") for line in lines):
        raise InfrastructureError(f"retirement manifest has ambiguous comments: {path}")
    try:
        rows = list(
            csv.reader(
                io.StringIO("\n".join(lines) + "\n", newline=""),
                delimiter="\t",
                strict=True,
            )
        )
    except csv.Error as exc:
        raise InfrastructureError(f"retirement manifest is malformed TSV: {path}: {exc}") from exc
    if not rows or tuple(rows[0]) != header:
        raise InfrastructureError(f"retirement manifest has invalid header: {path}")
    source_file_index = header.index("source_file")
    helper_index = header.index("helper")
    literal_index = header.index("literal")
    target_index = header.index("resolved_target")
    disposition_index = header.index("disposition")
    retired = set()
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(header) or any("\n" in cell for cell in row):
            raise InfrastructureError(
                f"retirement manifest has invalid row shape: {path}:{number}"
            )
        disposition = row[disposition_index]
        if disposition not in allowed_dispositions:
            raise InfrastructureError(
                f"retirement manifest has invalid disposition: {path}:{number}"
            )
        try:
            literal = json.loads(row[literal_index])
        except json.JSONDecodeError as exc:
            raise InfrastructureError(
                f"retirement manifest literal is invalid JSON: {path}:{number}"
            ) from exc
        if literal is not None and not isinstance(literal, str):
            raise InfrastructureError(
                f"retirement manifest literal is not a string or null: {path}:{number}"
            )
        # source_file/resolved_target are encode_cell (JSON) values; helper is a
        # bare cell -- the shapes pin-corpus-classifier.py wrote (issue #1006).
        try:
            source_file = json.loads(row[source_file_index])
            resolved_target = json.loads(row[target_index])
        except json.JSONDecodeError as exc:
            raise InfrastructureError(
                f"retirement manifest site field is invalid JSON: {path}:{number}"
            ) from exc
        if not isinstance(source_file, str):
            raise InfrastructureError(
                f"retirement manifest source_file is not a string: {path}:{number}"
            )
        if resolved_target is not None and not isinstance(resolved_target, str):
            raise InfrastructureError(
                f"retirement manifest resolved_target is not a string or null: "
                f"{path}:{number}"
            )
        helper = row[helper_index]
        if disposition in retired_dispositions and literal is not None:
            # Key on SITE identity, not the literal alone: a literal retired at one
            # (source_file, helper, resolved_target) site must not poison a retained
            # pin sharing that literal at a different site (issue #1006).
            retired.add(
                _site_retirement_key(source_file, helper, literal, resolved_target)
            )
    return retired


def _revision_state_dir_path(repo_root, revision, path, git_runner):
    """Return PATH as the state directory spelled it at REVISION.

    The .devflow/ -> .prflow/ state-directory rename (issue #1002) moved every
    frozen record with its directory and rewrote none of their bytes, so a
    merge-base-side read of a current .prflow/ path resolves nothing on a branch
    whose base predates the move.  Resolve the current spelling first and fall
    back to the superseded one only when the current path is absent at that
    revision and the superseded one is present -- the current-first,
    fallback-second rule lib/rename-map.json states for live readers, applied to
    a revision rather than the worktree.
    """
    if not path.startswith(_STATE_DIR_PREFIX):
        return path
    if _run_git(
        git_runner, repo_root, "ls-tree", "-r", "--name-only", revision, "--", path
    ).strip():
        return path
    superseded = _SUPERSEDED_STATE_DIR_PREFIX + path[len(_STATE_DIR_PREFIX):]
    if _run_git(
        git_runner, repo_root, "ls-tree", "-r", "--name-only", revision, "--", superseded
    ).strip():
        return superseded
    return path


def _revision_blob_id(repo_root, revision, path, git_runner):
    """Return the object id of the regular blob at REVISION:PATH, else ``None``.

    Absence is reported rather than raised so a caller comparing two revisions
    can treat "not there" as "not identical" and fall through to its own
    fail-closed arm.  A non-blob or non-regular entry reports ``None`` too.
    """
    listing = _run_git(git_runner, repo_root, "ls-tree", revision, "--", path)
    try:
        mode, kind, object_id, listed_path = listing.rstrip("\n").split(None, 3)
    except ValueError:
        return None
    if mode != "100644" or kind != "blob" or listed_path != path:
        return None
    return object_id


def _regular_blob_bytes(repo_root, revision, path, git_runner, label):
    listing = _run_git(git_runner, repo_root, "ls-tree", revision, "--", path)
    try:
        mode, kind, _object, listed_path = listing.rstrip("\n").split(None, 3)
    except ValueError as exc:
        raise InfrastructureError(f"{label} is not a regular blob: {path}") from exc
    if mode != "100644" or kind != "blob" or listed_path != path:
        raise InfrastructureError(f"{label} is not a regular blob: {path}")
    return _run_git_bytes(git_runner, repo_root, "show", f"{revision}:{path}")


def load_retired_wording_literal_keys(
    repo_root,
    merge_base,
    *,
    git_runner=subprocess.run,
):
    """Derive retired literals from byte-frozen historical static manifests."""
    repo_root = Path(repo_root)
    retired = set()
    for path, spec in _RETIREMENT_MANIFEST_SPECS.items():
        status = _run_git(
            git_runner,
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            path,
        )
        if status:
            raise InfrastructureError(
                f"historical retirement manifest worktree differs from HEAD: {path}"
            )
        base_bytes = _regular_blob_bytes(
            repo_root,
            merge_base,
            _revision_state_dir_path(repo_root, merge_base, path, git_runner),
            git_runner,
            "base retirement manifest",
        )
        head_bytes = _regular_blob_bytes(
            repo_root, "HEAD", path, git_runner, "HEAD retirement manifest"
        )
        if head_bytes != base_bytes:
            raise InfrastructureError(
                f"historical retirement manifest changed since merge base: {path}"
            )
        live_path = repo_root / path
        try:
            live_stat = live_path.lstat()
            live_bytes = live_path.read_bytes()
        except OSError as exc:
            raise InfrastructureError(
                f"historical retirement manifest worktree is unreadable: {path}: {exc}"
            ) from exc
        if (
            not stat.S_ISREG(live_stat.st_mode)
            or live_stat.st_mode & 0o111
            or live_bytes != head_bytes
        ):
            raise InfrastructureError(
                f"historical retirement manifest worktree is not the exact regular blob: {path}"
            )
        retired.update(
            _strict_retirement_manifest_literals(
                _decode_utf8(head_bytes, f"retirement manifest {path}"),
                path,
                spec,
            )
        )
    return frozenset(retired)


def canonical_adjudication_table_state(adjudications):
    """Render a table map independently of TSV ordering or transport bytes."""
    if not isinstance(adjudications, dict):
        raise InfrastructureError("adjudication table state is not a mapping")
    rows = []
    for key in sorted(adjudications):
        _validate_adjudication_key(key, "adjudication table state")
        state = adjudications[key]
        _validate_adjudication_state(state, f"adjudication table state for {key}")
        rows.append([key, *state])
    return json.dumps(rows, ensure_ascii=True, separators=(",", ":"))


def hash_adjudication_table_state(adjudications):
    """Return the deterministic content hash of a validated current-state map."""
    return hashlib.sha256(
        canonical_adjudication_table_state(adjudications).encode("utf-8")
    ).hexdigest()


def compute_adjudication_delta(base, current):
    """Return the complete base-to-current state delta, including deletions."""
    canonical_adjudication_table_state(base)
    canonical_adjudication_table_state(current)
    return {
        key: (base.get(key), current.get(key))
        for key in sorted(set(base) | set(current))
        if base.get(key) != current.get(key)
    }


def combine_adjudication_delta_manifests(manifests):
    """Combine branch manifests while rejecting cross-bundle duplicate claims."""
    combined = {}
    for manifest in manifests:
        if not isinstance(manifest, dict):
            raise InfrastructureError("adjudication delta manifest is not a mapping")
        for key, delta in manifest.items():
            _validate_adjudication_key(key, "adjudication delta manifest")
            if (
                not isinstance(delta, tuple)
                or len(delta) != 2
                or any(state is not None and not isinstance(state, tuple) for state in delta)
            ):
                raise InfrastructureError("adjudication delta manifest has invalid state pair")
            for state in delta:
                if state is not None:
                    _validate_adjudication_state(state, "adjudication delta manifest")
            if key in combined:
                raise InfrastructureError(
                    f"adjudication delta manifests have duplicate key: {key}"
                )
            combined[key] = delta
    return combined


def is_exactly_authorized_adjudication_delta(base, current, manifests):
    """Return whether a valid bundle set fully authorizes the computed delta."""
    actual = compute_adjudication_delta(base, current)
    authorized = combine_adjudication_delta_manifests(manifests)
    for key, delta in authorized.items():
        if actual.get(key) != delta:
            raise InfrastructureError(
                f"adjudication delta manifest is stale or extra for key: {key}"
            )
    return actual == authorized


def require_current_adjudication_base(
    repo_root,
    base_ref,
    *,
    merge_base=None,
    git_runner=subprocess.run,
):
    """Require HEAD to descend directly from the configured current base tip."""
    if merge_base is None:
        merge_base = _run_git(
            git_runner, repo_root, "merge-base", base_ref, "HEAD"
        ).strip()
    base_tip = _run_git(git_runner, repo_root, "rev-parse", base_ref).strip()
    if merge_base != base_tip:
        raise InfrastructureError(
            f"adjudication branch is not based on current {base_ref}: "
            f"merge-base {merge_base}, base tip {base_tip}"
        )
    return merge_base


def discover_new_adjudication_delta_manifests(
    repo_root,
    merge_base,
    *,
    include_revivals=False,
    git_runner=subprocess.run,
):
    """Return parsed HEAD payloads from only newly-added immutable bundles."""
    worktree_status = _run_git(
        git_runner,
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        _ADJUDICATION_BUNDLE_ROOT,
    )
    if worktree_status:
        raise InfrastructureError(
            "adjudication bundle worktree differs from HEAD: "
            f"{worktree_status.strip()}"
        )
    base_root = _revision_state_dir_path(
        repo_root, merge_base, _ADJUDICATION_BUNDLE_ROOT, git_runner
    )
    base_paths = {
        _ADJUDICATION_BUNDLE_ROOT + path[len(base_root):]
        for path in filter(
            None,
            _run_git(
                git_runner,
                repo_root,
                "ls-tree",
                "-r",
                "--name-only",
                merge_base,
                "--",
                base_root,
            ).splitlines(),
        )
    }
    historical_ids = {
        path.split("/")[3]
        for path in base_paths
        if len(path.split("/")) >= 4
    }
    changes = _run_git(
        git_runner,
        repo_root,
        "diff",
        "--name-status",
        "--no-renames",
        merge_base,
        "HEAD",
        "--",
        base_root,
        _ADJUDICATION_BUNDLE_ROOT,
    )
    new_paths = {}
    for line in filter(None, changes.splitlines()):
        try:
            status, path = line.split("\t", 1)
        except ValueError as exc:
            raise InfrastructureError(
                f"adjudication bundle diff has malformed name-status row: {line!r}"
            ) from exc
        if base_root != _ADJUDICATION_BUNDLE_ROOT and path.startswith(base_root + "/"):
            # Superseded-root side of the state-directory move (issue #1002).  Its
            # current-root twin below carries the judgement -- a payload that did
            # not survive the move byte-for-byte fails there, not here -- so a
            # delete under the superseded root is the expected half of the pair.
            if status != "D":
                raise InfrastructureError(
                    f"superseded adjudication bundle path was not moved away: {path} ({status})"
                )
            continue
        parts = path.split("/")
        if len(parts) < 4 or "/".join(parts[:3]) != _ADJUDICATION_BUNDLE_ROOT:
            raise InfrastructureError(f"adjudication bundle path is invalid: {path!r}")
        change_id = parts[3]
        if change_id in {".", ".."} or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", change_id
        ):
            raise InfrastructureError(f"adjudication bundle has unsafe bundle ID: {change_id!r}")
        if (
            base_root != _ADJUDICATION_BUNDLE_ROOT
            and status == "A"
            and change_id in historical_ids
        ):
            superseded_path = base_root + path[len(_ADJUDICATION_BUNDLE_ROOT):]
            base_blob = _revision_blob_id(
                repo_root, merge_base, superseded_path, git_runner
            )
            if base_blob is not None and base_blob == _revision_blob_id(
                repo_root, "HEAD", path, git_runner
            ):
                # Byte-identical historical bundle carried across the move: not a
                # new bundle, and not a change to a frozen one.  An absent or
                # differing blob falls through to the historical-change raise
                # below, so an edit made during the move still fails closed.
                continue
        delta_path = f"{_ADJUDICATION_BUNDLE_ROOT}/{change_id}/adjudication-delta.tsv"
        revival_path = (
            f"{_ADJUDICATION_BUNDLE_ROOT}/{change_id}/retired-pin-revivals.tsv"
        )
        if path not in {delta_path, revival_path}:
            raise InfrastructureError(f"adjudication bundle has unexpected bundle path: {path!r}")
        if status != "A" or change_id in historical_ids:
            raise InfrastructureError(
                f"historical adjudication bundle was changed: {path} ({status})"
            )
        new_paths.setdefault(change_id, set()).add(path)
    for change_id, paths in new_paths.items():
        delta_path = (
            f"{_ADJUDICATION_BUNDLE_ROOT}/{change_id}/adjudication-delta.tsv"
        )
        revival_path = (
            f"{_ADJUDICATION_BUNDLE_ROOT}/{change_id}/retired-pin-revivals.tsv"
        )
        expected_paths = {delta_path, revival_path}
        valid = delta_path in paths and paths <= expected_paths
        if not valid:
            unexpected = sorted(paths - expected_paths or paths)
            raise InfrastructureError(
                f"adjudication bundle has unexpected bundle path: {unexpected[0]!r}"
            )
    manifests = []
    revival_authorizations = set()
    for change_id in sorted(new_paths):
        for payload_path in sorted(new_paths[change_id]):
            listing = _run_git(git_runner, repo_root, "ls-tree", "HEAD", "--", payload_path)
            try:
                mode, kind, _object, listed_path = listing.rstrip("\n").split(None, 3)
            except ValueError as exc:
                raise InfrastructureError(
                    f"new adjudication bundle payload is not a regular HEAD blob: {payload_path}"
                ) from exc
            if mode != "100644" or kind != "blob" or listed_path != payload_path:
                raise InfrastructureError(
                    f"new adjudication bundle payload is not a regular HEAD blob: {payload_path}"
                )
            payload = _run_git_bytes(git_runner, repo_root, "show", f"HEAD:{payload_path}")
            if payload_path.endswith("/adjudication-delta.tsv"):
                manifests.append(
                    parse_adjudication_delta_manifest(
                        _decode_utf8(payload, f"adjudication bundle payload {payload_path}")
                    )
                )
            else:
                parsed = parse_retired_pin_revivals(
                    _decode_utf8(payload, f"adjudication bundle payload {payload_path}")
                )
                duplicates = revival_authorizations & set(parsed)
                if duplicates:
                    raise InfrastructureError(
                        "adjudication bundles have duplicate revival authorization: "
                        f"{sorted(duplicates)[0]}"
                    )
                revival_authorizations.update(parsed)
    if include_revivals:
        return manifests, frozenset(revival_authorizations)
    return manifests


_FUNCTION_START_RE = re.compile(r"(?m)^([A-Za-z_]\w*)\s*\(\)\s*\{")
_POSITIONAL_RE = re.compile(r"^\$\{?([1-9][0-9]*)\}?$")
_ALL_POSITIONAL_RE = re.compile(r"^\$\{?@\}?$")


# Bound on the per-source parse memos below, sized to the two images a scan
# holds for the source it is extracting: its merge-base image and its worktree
# image. Two repeats are caught, and they are not the same for both memos. The
# within-extraction repeat is _function_definitions' alone — one extraction
# reaches it twice for one image, once directly and once through
# _function_bodies inside the helper-spec inference. The re-presented
# merge-base image, which a later scan in the same process hands back
# unchanged, is the repeat both memos share; the helper-spec inference is
# derived only once per image per extraction, so that is its only one. Slack
# beyond the two images buys neither repeat and is spent retaining superseded
# copies of a multi-megabyte source.
_IMAGE_PARSE_CACHE_SIZE = 2


def _newline_offsets(text):
    """Return the ascending offsets of every newline in ``text``."""
    offsets = []
    position = text.find("\n")
    while position != -1:
        offsets.append(position)
        position = text.find("\n", position + 1)
    return offsets


def _function_definitions(text):
    """Return quote-, comment-, escape-, and parameter-aware function spans.

    The returned mapping is a fresh dict on every call: the underlying parse is
    memoized on ``text``, so handing the cached object to a caller that mutated
    it would corrupt every later hit.
    """
    return dict(_function_definitions_cached(text))


@functools.lru_cache(maxsize=_IMAGE_PARSE_CACHE_SIZE)
def _function_definitions_cached(text):
    definitions = {}
    # Derived lazily: a source with no function definition never pays for it,
    # and one with many amortizes a single pass over the whole text instead of
    # rescanning the prefix per definition to derive its line number.
    newline_offsets = None
    for match in _FUNCTION_START_RE.finditer(text):
        depth = 1
        parameter_depth = 0
        quote = None
        escaped = False
        index = match.end()
        body_start = index
        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\" and quote != "'":
                escaped = True
                index += 1
                continue
            if quote:
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in ("'", '"'):
                quote = char
                index += 1
                continue
            if char == "#" and (
                index == body_start or text[index - 1].isspace()
            ):
                newline = text.find("\n", index)
                index = len(text) if newline < 0 else newline + 1
                continue
            if char == "$" and index + 1 < len(text) and text[index + 1] == "{":
                parameter_depth += 1
                index += 2
                continue
            if char == "}" and parameter_depth:
                parameter_depth -= 1
                index += 1
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    if newline_offsets is None:
                        newline_offsets = _newline_offsets(text)
                    definitions[match.group(1)] = (
                        text[body_start:index],
                        bisect.bisect_left(newline_offsets, match.start()) + 1,
                        bisect.bisect_left(newline_offsets, index) + 1,
                    )
                    break
            index += 1
    return definitions


def _function_bodies(text):
    return {
        name: definition[0]
        for name, definition in _function_definitions(text).items()
    }


def _token_value(token):
    return "".join(value for _, value in token)


def _is_executable_helper_prefix(tokens):
    """Recognize the closed Bash execution-prefix grammar before a helper."""
    index = 0
    if index < len(tokens) and tokens[index] == "time":
        index += 1
        if index < len(tokens) and tokens[index] == "-p":
            index += 1
        if index < len(tokens) and tokens[index] == "--":
            index += 1
    if index < len(tokens) and tokens[index] == "command":
        index += 1
        if index < len(tokens) and tokens[index] in {"--", "-p"}:
            index += 1
    return index == len(tokens)


def _helper_calls(tokens, helper_specs):
    """Return supported helper tokens in recognized shell command positions.

    The closed boundary set covers guarded, pipeline, background, and subshell
    positions without treating a helper name inside an assertion label as
    executable.
    """
    command_boundaries = {
        "if",
        "then",
        "elif",
        "while",
        "until",
        "do",
        "!",
        "&&",
        "||",
        "|",
        "|&",
        "&",
        ";",
        "(",
        "{",
    }
    assignment = re.compile(r"^[A-Za-z_]\w*=.*$")
    calls = []
    for index, token in enumerate(tokens):
        if not token or any(kind != "bare" for kind, _ in token):
            continue
        value = _token_value(token)
        if value not in helper_specs:
            continue
        segment_start = 0
        for prior_index, prior in enumerate(tokens[:index]):
            if (
                prior
                and all(kind == "bare" for kind, _ in prior)
                and _token_value(prior) in command_boundaries
            ):
                segment_start = prior_index + 1
        segment = [
            _token_value(item) for item in tokens[segment_start:index]
        ]
        while segment and assignment.match(segment[0]):
            segment.pop(0)
        if _is_executable_helper_prefix(segment):
            calls.append((index, value))
    return tuple(calls)


def _helper_call(tokens, helper_specs):
    """Return one executable helper, failing closed on ambiguous fragments."""
    calls = _helper_calls(tokens, helper_specs)
    if len(calls) > 1:
        raise InfrastructureError(
            "multiple supported helper calls occur on one logical line"
        )
    return calls[0] if calls else (None, None)


def helper_specs_for_source(text):
    """Return built-in plus source-local wrapper helper specifications.

    A focused module may wrap the shared pin API. Enumerating function
    definitions independently of call spellings keeps those wrappers in the
    audited population. Wrappers are inferred from the supported positional or
    ``$@`` forwarding forms to an already-known helper; conventional
    ``*_pin_*`` wrappers provide the small fallback needed for wrappers
    implemented via lower-level counters (for example ``_raf_pin_unique``).

    Returns ``(specs, families, origins)`` — the inference that produces the
    specs produces the other two as a by-product. Each mapping is a fresh dict
    on every call, because the underlying inference is memoized on ``text`` and
    handing a cached object to a caller that mutated it would corrupt every
    later hit.
    """
    specs, families, origins = _helper_specs_for_source_cached(text)
    return dict(specs), dict(families), dict(origins)


@functools.lru_cache(maxsize=_IMAGE_PARSE_CACHE_SIZE)
def _helper_specs_for_source_cached(text):
    specs = dict(HELPERS)
    families = {name: _helper_family(name) for name in HELPERS}
    origins = {}
    bodies = _function_bodies(text)

    for _ in range(len(bodies) + 1):
        changed = False
        for name, body in bodies.items():
            if name in specs:
                continue
            for body_lineno, logical_line in join_logical_lines(body):
                tokens = tokenize(
                    logical_line.strip(), split_shell_operators=True
                )
                index, callee = _helper_call(tokens, specs)
                if callee is None:
                    continue
                args = tokens[index + 1 :]
                if len(args) == 1 and _ALL_POSITIONAL_RE.match(
                    _token_value(args[0]).rstrip(";")
                ):
                    specs[name] = specs[callee]
                    families[name] = families[callee]
                    origins[name] = body_lineno
                    changed = True
                    break
                splat_indexes = [
                    arg_index
                    for arg_index, arg in enumerate(args)
                    if _ALL_POSITIONAL_RE.match(
                        _token_value(arg).rstrip(";")
                    )
                ]
                lit_selector, file_index, default_file = specs[callee]
                if len(splat_indexes) > 1:
                    continue
                splat_index = splat_indexes[0] if splat_indexes else None
                if isinstance(lit_selector, int):
                    if splat_index is not None and lit_selector >= splat_index:
                        wrapper_lit_selector = lit_selector - splat_index
                    elif lit_selector >= len(args):
                        continue
                    else:
                        lit_token = args[lit_selector]
                        lit_ref = _POSITIONAL_RE.match(
                            _token_value(lit_token).rstrip(";")
                        )
                        if lit_ref is not None:
                            wrapper_lit_selector = int(lit_ref.group(1)) - 1
                        else:
                            fixed_literal = resolve_arg(
                                lit_token,
                                literal_vars={},
                                path_vars={},
                                want_path=False,
                            )
                            if fixed_literal is None:
                                continue
                            wrapper_lit_selector = fixed_literal
                else:
                    wrapper_lit_selector = lit_selector
                wrapper_file_index = 10**6
                wrapper_default = default_file
                if splat_index is not None and file_index >= splat_index:
                    wrapper_file_index = file_index - splat_index
                    wrapper_default = None
                elif file_index < len(args):
                    file_value = _token_value(args[file_index]).rstrip(";")
                    file_ref = _POSITIONAL_RE.match(file_value)
                    if file_ref is not None:
                        wrapper_file_index = int(file_ref.group(1)) - 1
                        wrapper_default = None
                    else:
                        var_ref = _VARREF.match(file_value)
                        if var_ref is not None:
                            wrapper_default = var_ref.group(1)
                specs[name] = (
                    wrapper_lit_selector,
                    wrapper_file_index,
                    wrapper_default,
                )
                families[name] = families[callee]
                origins[name] = body_lineno
                changed = True
                break
        if not changed:
            break
    # A name-only fallback may identify static presence wrappers implemented
    # through lower-level counters, but it must never grant mutation/count
    # exemption without body-derived evidence.
    for name in bodies:
        if name not in specs and name.endswith(STATIC_PRESENCE_WRAPPER_SUFFIXES):
            specs[name] = (1, 2, None)
            families[name] = "static-helper"
    return specs, families, origins


def parse_structural_declaration(physical_lines):
    """Parse one real-comment declaration using the closed issue-810 grammar."""
    declarations = []
    for _, comment in hash_comment_regions(physical_lines):
        if STRUCTURAL_PIN_OK_MARKER not in comment:
            continue
        tail = comment.split(STRUCTURAL_PIN_OK_MARKER, 1)[1].strip()
        category, sep, rationale = tail.partition("--")
        category = category.strip()
        rationale = rationale.strip()
        if not sep or not category:
            return None, "missing structural category"
        if category not in STRUCTURAL_PIN_CATEGORIES:
            return None, f"unknown structural category: {category}"
        if not rationale:
            return None, "empty structural rationale"
        declarations.append(StructuralDeclaration(category, rationale))
    if not declarations:
        return None, "missing structural declaration"
    if len(declarations) != 1:
        return None, "multiple structural declarations"
    return declarations[0], None


def parse_diff(difftext):
    """Parse a unified diff into (added_set, deleted_lines).

    added_set: the set of added-line CONTENT strings (`+` lines, minus the `+++`
    file header), CR-stripped so a CRLF target still matches. run.sh appends every
    line of each untracked lib/test/ file as a synthetic `+` line, so the untracked
    corpus rides this same channel.
    deleted_lines: the ordered content of `-` lines (minus `---`), reconstructed
    into text and re-parsed for pin sites so a MOVED pin's deleted side is known.

    The diff is an external structured format this repo does not author, so its
    boundary shapes are handled explicitly: `+++`/`---` headers are never content;
    `@@` hunk headers, context lines (leading space), rename/binary stanzas and
    blank lines are ignored; a bare `+`/`-` adds/removes an empty line.
    """
    added = set()
    deleted = []
    for raw in difftext.split("\n"):
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            added.add(raw[1:].rstrip("\r"))
        elif raw.startswith("-"):
            deleted.append(raw[1:])
    return added, deleted


def _deleted_pin_literals(deleted_lines, lib, overrides):
    """Multiset (dict literal->count) of pin literals from DELETED pin sites whose
    literal resolved — the only deletions that can exempt an added site by move."""
    counts = {}
    text = "\n".join(deleted_lines)
    for pin in extract_pins(text, lib, overrides):
        lit = pin["literal"]
        if lit is None:
            continue
        counts[lit] = counts.get(lit, 0) + 1
    return counts


def site_physical_lines(all_lines, start_lineno, logical_line):
    """The ORIGINAL physical lines of a call site (with trailing backslashes intact),
    so they match the diff's added-line content. `logical_line` carries one embedded
    newline per continuation join, so its newline count is (end - start)."""
    span = logical_line.count("\n")
    return all_lines[start_lineno - 1 : start_lineno + span]


def _has_structural_pin_ok(physical_lines):
    """True only for one valid typed declaration in a real comment region."""
    declaration, error = parse_structural_declaration(physical_lines)
    return declaration is not None and error is None


def run_mutation_routing(pin_source, lib, overrides, md_targets, diff_file):
    if diff_file is None:
        sys.stderr.write("MUTATION-ROUTING\tno --diff-file supplied; no findings emitted\n")
        return 0
    difftext, err = _read_target(diff_file)
    if err is not None:
        # An absent/unreadable diff file is reported, never silently suppressed —
        # but the run still exits 0 with no findings (run.sh owns the skip decision).
        sys.stderr.write(f"MUTATION-ROUTING\tdiff-file unreadable ({diff_file}: {err}); no findings emitted\n")
        return 0
    added, deleted_lines = parse_diff(difftext)
    del_literals = _deleted_pin_literals(deleted_lines, lib, overrides)

    text = _read(pin_source)
    all_lines = text.split("\n")
    path_vars, literal_vars = build_var_maps(text, lib, overrides)
    scanned = findings = exempted = 0
    for lineno, line in join_logical_lines(text):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        first = stripped.split(None, 1)
        if not first or first[0] not in HELPERS:
            continue
        # A helper's own `name() {` definition line is not a call site (extract_pins
        # already skips it because `name()` != `name`, but assert it explicitly so a
        # future call-shape change cannot make the gate demand a marker on a def line).
        if _DEF_LINE_RE.match(stripped):
            continue
        helper = first[0]
        if helper not in REQUIRED_DECLARATION_HELPERS:
            # In THIS legacy synthetic self-test command, mutation-taking and
            # count-based helpers draw no finding. This is scoped to the legacy
            # path only: the production `mutation-routing-worktree` classifier
            # (scan_changed_sources) no longer exempts count helpers — issue #925
            # removed that short-circuit, so a prose pin routed through pin_count
            # is reported there. Do not read this exemption as a global policy.
            continue
        toks = tokenize(stripped)
        if not toks or "".join(v for _, v in toks[0]) != helper:
            continue
        phys = site_physical_lines(all_lines, lineno, line)
        # In scope only when EVERY physical line of the site is in the added set.
        if not phys or any(pl.rstrip("\r") not in added for pl in phys):
            continue
        scanned += 1
        if _has_structural_pin_ok(phys):
            continue
        # Resolve the literal for move-exemption (a None literal is never exempt).
        args = toks[1:]
        lit_idx, _, _ = HELPERS[helper]
        literal = resolve_arg(args[lit_idx], literal_vars, path_vars, want_path=False) if lit_idx < len(args) else None
        if literal is not None and del_literals.get(literal, 0) > 0:
            del_literals[literal] -= 1  # one-to-one: consume this deletion
            exempted += 1
            continue
        findings += 1
        print(
            f"MUTATION-ROUTING\t{pin_source}:{lineno}\t{helper}\t"
            f"{literal if literal is not None else '<unresolved-literal>'}\t"
            f"added pin site needs an ordinary executable behavioral test or a "
            f"'# structural-pin-ok: <category> -- <non-empty rationale>' declaration"
        )
    sys.stderr.write(f"MUTATION-ROUTING-SCANNED\t{scanned}\n")
    sys.stderr.write(f"MUTATION-ROUTING-EXEMPTED-BY-MOVE\t{exempted}\n")
    sys.stderr.write(f"MUTATION-ROUTING-FINDINGS\t{findings}\n")
    return 0


def parse_unified_diff(difftext):
    """Return file- and hunk-coordinate-aware patches from a unified diff."""
    patches = []
    old_path = new_path = None
    added = set()
    deleted = set()
    old_lineno = new_lineno = None
    in_file = False
    old_header_seen = new_header_seen = False
    hunk_expected = None
    hunk_consumed = None
    saw_hunk = False
    metadata = set()
    last_hunk_line_was_content = False
    no_newline_marker_seen = False

    def finish_hunk():
        nonlocal hunk_expected, hunk_consumed, old_lineno, new_lineno
        nonlocal last_hunk_line_was_content, no_newline_marker_seen
        if hunk_expected is not None and hunk_consumed != hunk_expected:
            raise InfrastructureError(
                "malformed unified diff: truncated hunk "
                f"(expected {hunk_expected}, consumed {hunk_consumed})"
            )
        hunk_expected = hunk_consumed = None
        old_lineno = new_lineno = None
        last_hunk_line_was_content = False
        no_newline_marker_seen = False

    def finish():
        nonlocal old_path, new_path, added, deleted, in_file
        nonlocal old_header_seen, new_header_seen
        nonlocal saw_hunk, metadata
        finish_hunk()
        if in_file and (old_header_seen != new_header_seen):
            raise InfrastructureError(
                "malformed unified diff: file patch is missing ---/+++ header pair"
            )
        if in_file and old_header_seen and not saw_hunk:
            raise InfrastructureError(
                "malformed unified diff: ---/+++ headers have no hunk"
            )
        if in_file and old_header_seen and old_path is None and new_path is None:
            raise InfrastructureError(
                "malformed unified diff: both file paths are /dev/null"
            )
        if in_file and old_header_seen and new_header_seen:
            patches.append(
                FilePatch(old_path, new_path, frozenset(added), frozenset(deleted))
            )
        if in_file and not old_header_seen:
            complete_metadata_change = (
                {"old mode", "new mode"} <= metadata
                or {"rename from", "rename to"} <= metadata
                or {"copy from", "copy to"} <= metadata
                or "new file mode" in metadata
                or "deleted file mode" in metadata
            )
            if not complete_metadata_change:
                raise InfrastructureError(
                    "malformed unified diff: file stanza has no complete change record"
                )
        old_path = new_path = None
        added = set()
        deleted = set()
        in_file = False
        old_header_seen = new_header_seen = False
        saw_hunk = False
        metadata = set()

    def diff_path(value, prefix):
        value = value.split("\t", 1)[0]
        if value.startswith('"') != value.endswith('"'):
            raise InfrastructureError(
                "malformed unified diff: unterminated quoted path"
            )
        if value.startswith('"'):
            try:
                value = ast.literal_eval(value)
                if not isinstance(value, str):
                    raise ValueError("quoted path did not decode to a string")
                # Git C-quotes non-ASCII UTF-8 bytes as octal escapes. Python's
                # literal parser maps each escape to a Latin-1 code point, so
                # reconstruct the original byte sequence before path matching.
                value = value.encode("latin-1").decode("utf-8")
            except (SyntaxError, ValueError) as exc:
                raise InfrastructureError(
                    f"malformed unified diff: invalid quoted path ({exc})"
                ) from exc
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return re.sub(rf"^{prefix}/", "", value)

    for raw in difftext.splitlines():
        if raw.startswith("diff --git "):
            finish()
            in_file = True
            continue
        if not in_file:
            if raw.strip():
                raise InfrastructureError(
                    "malformed unified diff: content precedes diff --git header"
                )
            continue
        if (
            hunk_expected is not None
            and hunk_consumed == hunk_expected
            and raw != r"\ No newline at end of file"
        ):
            finish_hunk()
        if hunk_expected is not None:
            if raw == r"\ No newline at end of file":
                if not last_hunk_line_was_content or no_newline_marker_seen:
                    raise InfrastructureError(
                        "malformed unified diff: misplaced no-newline marker"
                    )
                no_newline_marker_seen = True
                last_hunk_line_was_content = False
                continue
            if raw.startswith("+"):
                added.add(new_lineno)
                new_lineno += 1
                hunk_consumed = (
                    hunk_consumed[0], hunk_consumed[1] + 1
                )
            elif raw.startswith("-"):
                deleted.add(old_lineno)
                old_lineno += 1
                hunk_consumed = (
                    hunk_consumed[0] + 1, hunk_consumed[1]
                )
            elif raw.startswith(" "):
                old_lineno += 1
                new_lineno += 1
                hunk_consumed = (
                    hunk_consumed[0] + 1, hunk_consumed[1] + 1
                )
            elif raw.startswith("@@ "):
                finish_hunk()
            else:
                raise InfrastructureError(
                    f"malformed unified diff: unexpected hunk line {raw!r}"
                )
            if hunk_expected is not None:
                last_hunk_line_was_content = True
                no_newline_marker_seen = False
                if (
                    hunk_consumed[0] > hunk_expected[0]
                    or hunk_consumed[1] > hunk_expected[1]
                ):
                    raise InfrastructureError(
                        "malformed unified diff: hunk exceeds declared size"
                    )
                continue
        if raw.startswith("--- "):
            if old_header_seen:
                raise InfrastructureError(
                    "malformed unified diff: duplicate --- header"
                )
            value = raw[4:].split("\t", 1)[0]
            old_path = None if value == "/dev/null" else diff_path(value, "a")
            old_header_seen = True
            continue
        if raw.startswith("+++ "):
            if not old_header_seen or new_header_seen:
                raise InfrastructureError(
                    "malformed unified diff: invalid +++ header ordering"
                )
            value = raw[4:].split("\t", 1)[0]
            new_path = None if value == "/dev/null" else diff_path(value, "b")
            new_header_seen = True
            continue
        if raw.startswith("@@ "):
            match = re.match(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
                raw,
            )
            if match is None or not old_header_seen or not new_header_seen:
                raise InfrastructureError(
                    f"malformed unified diff: invalid hunk header {raw!r}"
                )
            old_lineno = int(match.group(1))
            new_lineno = int(match.group(3))
            hunk_expected = (
                int(match.group(2) or 1),
                int(match.group(4) or 1),
            )
            hunk_consumed = (0, 0)
            saw_hunk = True
            continue
        if not raw and saw_hunk:
            continue
        if old_header_seen or new_header_seen:
            raise InfrastructureError(
                f"malformed unified diff: unexpected post-header line {raw!r}"
            )
        metadata_patterns = (
            ("index", r"index [0-9a-fA-F]+\.\.[0-9a-fA-F]+(?: [0-7]{6})?"),
            ("new file mode", r"new file mode [0-7]{6}"),
            ("deleted file mode", r"deleted file mode [0-7]{6}"),
            ("old mode", r"old mode [0-7]{6}"),
            ("new mode", r"new mode [0-7]{6}"),
            ("similarity index", r"similarity index (?:100|[0-9]?[0-9])%"),
            ("dissimilarity index", r"dissimilarity index (?:100|[0-9]?[0-9])%"),
            ("rename from", r"rename from .+"),
            ("rename to", r"rename to .+"),
            ("copy from", r"copy from .+"),
            ("copy to", r"copy to .+"),
        )
        matched_metadata = next(
            (
                name
                for name, pattern in metadata_patterns
                if re.fullmatch(pattern, raw)
            ),
            None,
        )
        if raw and matched_metadata is None:
            raise InfrastructureError(
                f"malformed unified diff: unexpected metadata line {raw!r}"
            )
        if matched_metadata is not None:
            if matched_metadata in metadata and matched_metadata != "index":
                raise InfrastructureError(
                    f"malformed unified diff: duplicate metadata line {raw!r}"
                )
            metadata.add(matched_metadata)
    finish()
    return tuple(patches)


def _helper_family(helper):
    if helper in COUNT_HELPERS:
        return "count-helper"
    return "static-helper"


_RAW_PRESENCE_RE = re.compile(
    r"""(?:(?P<command_sub>\$\()\s*)?(?P<grep>\bgrep)\s+
        (?P<options>(?:(?:-[A-Za-z]+|--[a-z-]+)\s+)+)
        (?:--\s+)?
        (?P<literal_token>'[^']*'|"[^"]*"|[^\s]+)\s+
        (?P<target>
            "(?:\$\{?[A-Za-z_]\w*\}?(?:/[^\s";]+)?|/?[A-Za-z0-9_.-]+(?:/[^\s";]+)*)"
            |
            '(?:/?[A-Za-z0-9_.-]+(?:/[^\s';]+)*)'
            |
            (?:\$\{?[A-Za-z_]\w*\}?(?:/[^\s";]+)?|/?[A-Za-z0-9_.-]+(?:/[^\s";]+)*)
        )
        (?P<tail>\s*(?:\#|;|\)|&&|\|\||\|&|\||&|$))""",
    re.VERBOSE | re.DOTALL,
)

_RAW_CAT_PRESENCE_RE = re.compile(
    r"""(?P<prefix>\[\[\s+)
        ["']?\$\(cat\s+
        (?P<target>"[^"]+"|'[^']+'|[^\s)]+)
        \s*\)["']?\s+==\s+
        \*(?P<literal_token>'[^']*'|"[^"]*"|[^\s*]+)\*
        \s+\]\]""",
    re.VERBOSE,
)


def _line_end(start, logical_line):
    return start + logical_line.count("\n")


def _raw_options_are_fixed_quiet(options):
    fixed = quiet = False
    for option in options.split():
        if option == "--fixed-strings":
            fixed = True
        elif option == "--quiet":
            quiet = True
        elif option.startswith("-") and not option.startswith("--"):
            fixed = fixed or "F" in option[1:]
            quiet = quiet or "q" in option[1:]
    return fixed and quiet


def _shell_syntax_is_active_at(text, offset):
    """Return whether shell syntax at ``offset`` is unescaped and not single-quoted."""
    quote = None
    at_word_start = True
    index = 0
    while index < offset:
        char = text[index]
        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            if index + 1 == offset:
                return False
            at_word_start = False
            index += 2
            continue
        if quote == '"':
            if char == '"':
                quote = None
            index += 1
            continue
        if char in " \t\n;&|()":
            at_word_start = True
            index += 1
            continue
        if char == "#" and at_word_start:
            return False
        if char == "'":
            quote = "'"
        elif char == '"':
            quote = '"'
        at_word_start = False
        index += 1
    return quote != "'"


def _resolve_guard_target(args, spec, literal_vars, path_vars, lib):
    _, file_index, default_file = spec
    if file_index < len(args):
        target = resolve_arg(
            args[file_index], literal_vars, path_vars, want_path=True, lib=lib
        )
        return target.rstrip(";") if target is not None else None
    if default_file is not None:
        return path_vars.get(default_file)
    return None


def _guard_target_variable(args, spec):
    """The bare variable NAME a guard's target argument reads, or None.

    Recovering the name is what lets an UNRESOLVED target still be identified: a
    bundle variable holds a runtime scratch path, so ``_resolve_guard_target``
    returns None for it and only the name it was written as remains (issue #956).
    """
    _, file_index, default_file = spec
    if file_index < len(args):
        return _bundle_variable_name(_token_value(args[file_index]).rstrip(";"))
    return default_file


# ── issue #956: concatenated in-module bundle targets ───────────────────────
# A content-survival pin may target a bundle its test source CONCATENATES at
# runtime from several repository files (``$CI_BUNDLE``, ``$MAXI_BUNDLE``): the
# contract sentence must survive somewhere in a split skill, and which member
# holds it is an implementation detail the pin deliberately does not fix. That
# target is a scratch path no static resolution reaches, so every typed
# declaration on such a pin was refused as uninspectable — and because the gate
# classifies any site whose lines land in the diff, the whole logical line
# (declaration text included) became permanently uneditable.
#
# Resolving the bundle variable back to the member files its own builder call
# names gives those pins the SAME inspection the single-file case gets: the
# declaration is inspected against the member set, and the literal must be
# present in one of the members. This weakens nothing. Membership is resolved
# only through the closed grammar below (a builder call, an array built from
# literal words and/or one for-loop — either over a path glob with an optional
# basename skip, or over a literal STEM list whose body appends one path
# template per stem — and whole-variable aliases of a resolved bundle, with or
# without a trailing comment); anything outside it leaves the bundle unresolved
# and the pre-existing refusal stands, an empty member set is never treated as
# inspected, and a literal present in no member is still reported.
#
# Issue #1008 widened that grammar by two independent arms, each measured against
# this repository's own `lib/test/run.sh` before it was written:
#   * the STEM-loop body — the review bundle iterates a word-list variable and
#     appends `"$LIB/../skills/review/phases/${_s}.md"` rather than the loop
#     variable itself, so `$REVIEW_BUNDLE` resolved to nothing at all;
#   * the COMMENT-suffixed alias — `ST_RAF="$MAXI_BUNDLE"   # …` did not resolve
#     even though `$MAXI_BUNDLE` did, because the trailing comment is part of the
#     assignment's right-hand side and defeated the whole-token variable match.
# Both left typed `# structural-pin-ok:` declarations on the affected pins
# permanently refused as uninspectable, which froze the whole logical line.
BUNDLE_BUILDERS = frozenset({"_build_skill_bundle", "devflow_module_build_bundle"})
_BUNDLE_ARRAY_ASSIGN_RE = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_]\w*)(\+?)=\(\s*(.*?)\s*\)\s*(?:#.*)?$"
)
_BUNDLE_ARRAY_EXPANSION_RE = re.compile(r"^\$\{(\w+)\[@\]\}$")
_BUNDLE_FOR_RE = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s+in\s+(.*?)\s*;\s*do\b(.*)$")
# ``case "${ref##*/}" in a.md|b.md) continue ;; esac`` — the one member filter the
# grammar models, so a bundle that skips named basenames resolves EXACTLY rather
# than to a superset of its real membership.
_BUNDLE_CASE_SKIP_RE = re.compile(
    r"^case\s+\"?\$\{(\w+)##\*/\}\"?\s+in\s+([^)]+)\)\s*continue\s*;;\s*esac$"
)
_BUNDLE_DEFAULT_EXPANSION_RE = re.compile(r"^\$\{(\w+):[-=](.*)\}$")
_BUNDLE_SUFFIX_EXPANSION_RE = re.compile(r"^\$\{(\w+)%%?([^{}]*)\}$")
_BUNDLE_GLOB_CHARS = "*?["
# An annotated alias — `ST_RAF="$MAXI_BUNDLE"   # …`. The comment is stripped only
# when what precedes it is itself a whole-token variable reference, so nothing that
# merely CONTAINS a `#` is truncated (issue #1008).
_BUNDLE_TRAILING_COMMENT_RE = re.compile(r"^(.*?)\s+#.*$")
# One word of a stem list. Deliberately narrower than a shell word: no slash, no
# glob character, no expansion, nothing that could change how the substituted
# template tokenizes. A list carrying anything else resolves to None (fail closed).
_BUNDLE_STEM_WORD_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class BundleMemberSpec(NamedTuple):
    """One member word of a bundle build: a path, possibly a glob, plus the
    basename patterns an enclosing loop filter skips."""

    pattern: str
    exclusions: tuple


def _bundle_variable_name(token_value):
    """The variable name a whole-token reference names (``"$CI_BUNDLE"``), else None."""
    value = token_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    match = _VARREF.match(value)
    return match.group(1) if match else None


def _bundle_alias_name(rhs):
    """The bundle variable an alias assignment's right-hand side names, else None.

    An alias is usually annotated (``ST_RAF="$MAXI_BUNDLE"   # #530: …``), and the
    comment is part of the right-hand side ``_ASSIGNMENT_RE`` captures. Stripping
    it is gated on the remaining text being a whole-token variable reference, so a
    right-hand side that merely contains a ``#`` — inside quotes, in a path, in a
    parameter expansion — is never truncated into a false alias (issue #1008).
    """
    name = _bundle_variable_name(rhs)
    if name is not None:
        return name
    match = _BUNDLE_TRAILING_COMMENT_RE.match(rhs)
    if match is None:
        return None
    return _bundle_variable_name(match.group(1))


def _bundle_word_list(rhs, word_vars):
    """The literal words a whitespace-separated word-list right-hand side names.

    Exactly two word shapes are modeled — a safe literal stem word and a
    whole-token reference to an already-known word-list variable — so a list
    carrying a glob, a command substitution, a path, or any other expansion
    resolves to None and its loop stays unmodeled (issue #1008). ``None`` is also
    the answer for an empty list, which must never read as "resolved to nothing".
    """
    value = rhs.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    words = []
    for token in value.split():
        reference = _VARREF.match(token)
        if reference is not None:
            known = word_vars.get(reference.group(1))
            if known is None:
                return None
            words.extend(known)
            continue
        if _BUNDLE_STEM_WORD_RE.match(token) is None:
            return None
        words.append(token)
    return tuple(words) or None


def _bundle_word_vars(text):
    """Whole-source map of {name: literal word tuple} for stem-list variables.

    Like ``_extended_path_vars`` this is a final-state map read at every loop, so a
    name that is not the SAME list everywhere cannot answer for one: a second
    assignment — or a first one this grammar does not model — makes the name
    ambiguous and it is dropped, rather than answering with whichever value
    happened to be last (issue #1008).

    Memoized on the presented bytes; a fresh dict is handed out so a caller cannot
    write through the cached object.
    """
    return dict(_bundle_word_vars_cached(text))


@functools.lru_cache(maxsize=_IMAGE_PARSE_CACHE_SIZE)
def _bundle_word_vars_cached(text):
    word_vars = {}
    ambiguous = set()
    for _, line in join_logical_lines(text):
        if _BUNDLE_ARRAY_ASSIGN_RE.match(line) is not None:
            continue  # array assignments are resolved by _bundle_arrays
        match = _ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        name = match.group(1)
        if name in ambiguous:
            continue
        words = _bundle_word_list(match.group(2).strip(), word_vars)
        if words is None or name in word_vars:
            ambiguous.add(name)
            word_vars.pop(name, None)
            continue
        word_vars[name] = words
    return tuple(word_vars.items())


def _bundle_expansion_path(rhs, lib, path_vars):
    """Resolve a bundle root variable's right-hand side to a path, or None.

    ``_resolve_path_rhs`` models plain and var-prefixed paths; a bundle's root is
    additionally written with a default (``${VAR:-fallback}``) or a suffix strip
    (``${LIB%/lib}``), so those two forms are resolved here. The extension is
    deliberately LOCAL to bundle resolution rather than added to the shared
    resolver: widening the shared one would change which targets the whole corpus
    resolves, a far larger behavior change than issue #956 authorizes.
    """
    value = rhs.strip()
    if len(value) >= 2 and value[0] == '"' and value.endswith('"'):
        value = value[1:-1]
    default = _BUNDLE_DEFAULT_EXPANSION_RE.match(value)
    if default is not None:
        if default.group(1) in path_vars:
            return path_vars[default.group(1)]
        return _bundle_expansion_path(default.group(2), lib, path_vars)
    suffix = _BUNDLE_SUFFIX_EXPANSION_RE.match(value)
    if suffix is not None:
        base = path_vars.get(suffix.group(1))
        if base is None:
            return None
        pattern = suffix.group(2)
        if any(char in pattern for char in _BUNDLE_GLOB_CHARS):
            return None  # a pattern suffix is not modeled; fail closed
        if pattern and base.endswith(pattern):
            return base[: -len(pattern)]
        return base
    return _resolve_path_rhs(value, lib, path_vars)


def _extended_path_vars(text, lib):
    """Sequential path-variable map extended with the two parameter expansions a
    module's ROOT variable uses, for bundle membership and for the guard-target
    fallback in ``extract_guard_sites``.

    ``LIB`` is seeded (and protected) because a module reaches its repository root
    through it (``${LIB%/lib}``) — the same special case the shared inline
    ``$LIB/rel`` resolution already makes.

    It is a whole-source final-state map, not the per-line view: a name it adds is
    one the shared per-line resolver could not resolve at ANY line, so the two
    cannot disagree about a name that resolves on both. A name reassigned between
    two extended-only values would be read as its last value; no bundle source
    does that today, and the callers use this map only as a fallback after the
    per-line view has already failed.

    Memoized on ``(text, lib)`` like the other whole-source parses; a fresh dict is
    handed out so a caller cannot write through the cached object.
    """
    return dict(_extended_path_vars_cached(text, lib))


@functools.lru_cache(maxsize=_IMAGE_PARSE_CACHE_SIZE)
def _extended_path_vars_cached(text, lib):
    path_vars = {}
    if lib:
        path_vars["LIB"] = lib
    literal_vars = {}
    for _, line in join_logical_lines(text):
        if _BUNDLE_ARRAY_ASSIGN_RE.match(line) is not None:
            continue  # array assignments are resolved by _bundle_arrays
        match = _ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        name, rhs = match.group(1), match.group(2).strip()
        _apply_assignment(
            name, rhs, path_vars, literal_vars, lib, protected=("LIB",)
        )
        if name not in path_vars and name != "LIB":
            value = _bundle_expansion_path(rhs, lib, path_vars)
            if value is not None:
                path_vars[name] = value
    return path_vars


def _bundle_word_specs(words, lib, path_vars):
    """Resolve a whitespace-separated member word list, or None if any word is
    unresolvable (fail closed: a partially resolved bundle is not a bundle)."""
    specs = []
    for token in tokenize(words.strip()):
        resolved = resolve_arg(token, {}, path_vars, want_path=True, lib=lib)
        if resolved is None:
            return None
        specs.append(BundleMemberSpec(resolved, ()))
    return tuple(specs) or None


def _bundle_loop_var_pattern(loop_var):
    """Match every reference to the loop variable — ``${_s}`` and bare ``$_s``."""
    escaped = re.escape(loop_var)
    return re.compile(r"\$\{%s\}|\$%s(?![A-Za-z0-9_])" % (escaped, escaped))


def _bundle_template_specs(value, loop_var, stems, lib, path_vars):
    """Resolve a stem-loop append — ``_m+=("$LIB/…/${_s}.md")`` — over a stem list.

    Every reference to the loop variable is replaced textually by one stem and the
    result re-resolved through the ordinary member-word grammar, so a template
    that is not a resolvable single path yields None and the loop stays unmodeled.
    Stems reach the substitution already restricted to ``_BUNDLE_STEM_WORD_RE``, so
    none of them can introduce a quote, a glob, or an expansion that would change
    how the substituted text tokenizes (issue #1008).
    """
    pattern = _bundle_loop_var_pattern(loop_var)
    if pattern.search(value) is None:
        return None
    specs = []
    for stem in stems:
        resolved = _bundle_word_specs(pattern.sub(stem, value), lib, path_vars)
        if resolved is None or len(resolved) != 1:
            return None
        specs.extend(resolved)
    return tuple(specs) or None


def _bundle_loop_member_specs(loop_var, words, body, lib, path_vars, word_vars):
    """Resolve one ``for`` loop's contribution as ((array name, specs), …).

    An array's ``specs`` is None when the loop body carries any statement the
    grammar does not model, so that array is poisoned rather than silently
    under-resolved — reporting it as merely "the words resolved so far" would
    resolve its bundle to a strict SUBSET of its real membership and let
    inspection call a literal absent that is really present.

    Two body shapes are modeled, and one loop may carry both because they are
    decided per append statement:
      * the loop variable appended directly (``_members+=("$_ref")``), whose
        members are the loop's own word list — a directory glob, with the optional
        basename skip applied;
      * a path TEMPLATE interpolating the loop variable
        (``_members+=("$LIB/../skills/review/phases/${_s}.md")``), whose members
        are that template resolved once per word of a literal stem list. This is
        how `$REVIEW_BUNDLE` is built, and leaving it unmodeled is what made two
        of its pins permanently undeclarable (issue #1008).
    A basename skip is not composed with a template — the skip filters an expanded
    glob, and there is no evidence for what it should mean over a stem list — so a
    loop carrying both leaves its templated arrays unresolved.
    """
    exclusions = []
    appended = []
    templated = []
    unmodeled_arrays = []
    modeled = True
    for statement in body:
        if not statement or statement.startswith("#"):
            continue
        skip = _BUNDLE_CASE_SKIP_RE.match(statement)
        if skip is not None and skip.group(1) == loop_var:
            exclusions.extend(
                pattern.strip().strip("\"'") for pattern in skip.group(2).split("|")
            )
            continue
        append = _BUNDLE_ARRAY_ASSIGN_RE.match(statement)
        if append is not None and append.group(2) == "+":
            if _bundle_variable_name(append.group(3)) == loop_var:
                appended.append(append.group(1))
            elif _bundle_loop_var_pattern(loop_var).search(append.group(3)):
                templated.append((append.group(1), append.group(3)))
            else:
                unmodeled_arrays.append(append.group(1))
            continue
        modeled = False
    touched = (
        tuple(appended)
        + tuple(name for name, _ in templated)
        + tuple(unmodeled_arrays)
    )
    if not touched:
        return ()
    if unmodeled_arrays or not modeled:
        return tuple((name, None) for name in touched)
    contributions = []
    if appended:
        specs = _bundle_word_specs(words, lib, path_vars)
        if specs is not None:
            specs = tuple(
                spec._replace(exclusions=tuple(exclusions)) for spec in specs
            )
        contributions.extend((name, specs) for name in appended)
    if templated:
        stems = None if exclusions else _bundle_word_list(words, word_vars)
        contributions.extend(
            (
                name,
                None
                if stems is None
                else _bundle_template_specs(
                    value, loop_var, stems, lib, path_vars
                ),
            )
            for name, value in templated
        )
    return tuple(contributions)


def _bundle_arrays(text, lib, path_vars):
    """Return {array name: member specs}, mapping an unmodeled array to None."""
    lines = list(join_logical_lines(text))
    word_vars = _bundle_word_vars(text)
    arrays = {}
    index = 0
    while index < len(lines):
        line = lines[index][1]
        loop = _BUNDLE_FOR_RE.match(line)
        if loop is not None:
            inline = loop.group(3).strip()
            if inline:
                body = [
                    part.strip()
                    for part in inline.split(";")
                    if part.strip() and part.strip() != "done"
                ]
                index += 1
            else:
                body = []
                index += 1
                while index < len(lines) and lines[index][1].strip() != "done":
                    body.append(lines[index][1].strip())
                    index += 1
                index += 1  # consume the `done`
            contributions = _bundle_loop_member_specs(
                loop.group(1), loop.group(2), body, lib, path_vars, word_vars
            )
            nested = line[:1] in {" ", "\t"}
            for name, specs in contributions:
                if nested:
                    specs = None  # a nested loop's reachability is not modeled
                if specs is None or arrays.get(name, ()) is None:
                    arrays[name] = None
                else:
                    arrays[name] = arrays.get(name, ()) + specs
            continue
        assign = _BUNDLE_ARRAY_ASSIGN_RE.match(line)
        if assign is not None:
            name, append, words = assign.group(1), assign.group(2), assign.group(3)
            # An INDENTED assignment outside a modeled loop sits inside some other
            # compound (a function, an `if`, a `while read` loop) whose reachability
            # this grammar does not model, so it is treated as unresolvable rather
            # than as an unconditional member (fail closed).
            specs = (
                _bundle_word_specs(words, lib, path_vars)
                if line[:1] not in {" ", "\t"}
                else None
            )
            if append != "+" or name not in arrays:
                arrays[name] = specs
            elif arrays[name] is None or specs is None:
                arrays[name] = None
            else:
                arrays[name] = arrays[name] + specs
        index += 1
    return arrays


def _expand_bundle_specs(specs):
    """Expand member specs to member file paths, or None when a glob member matched
    nothing (an empty or partial member set must never read as inspected)."""
    members = []
    for spec in specs:
        if not any(char in spec.pattern for char in _BUNDLE_GLOB_CHARS):
            members.append(spec.pattern)
            continue
        # The pattern is a closed non-recursive single-directory one taken verbatim
        # from the bundle's own builder call — no recursion and no `**`. It mirrors
        # the shell glob the bundle is really assembled from, which is why the
        # worktree, not the index, is the right population here.
        candidates = glob.glob(spec.pattern)  # tree-walk-ok: closed non-recursive builder-call pattern, mirroring the shell glob that assembles the bundle
        matched = sorted(path for path in candidates if os.path.isfile(path))
        if spec.exclusions:
            matched = [
                path
                for path in matched
                if not any(
                    fnmatch.fnmatch(os.path.basename(path), pattern)
                    for pattern in spec.exclusions
                )
            ]
        if not matched:
            return None
        members.extend(matched)
    resolved = []
    for member in members:
        absolute = os.path.abspath(member)
        if absolute not in resolved:
            resolved.append(absolute)
    return tuple(resolved) or None


def _bundle_call_members(args, arrays, lib, path_vars):
    """Resolve a builder call's member arguments to member specs, or None."""
    specs = []
    for token in args:
        raw = _token_value(token)
        expansion = _BUNDLE_ARRAY_EXPANSION_RE.match(raw.strip().strip("\"'"))
        if expansion is not None:
            array = arrays.get(expansion.group(1))
            if array is None:
                return None
            specs.extend(array)
            continue
        resolved = _bundle_word_specs(raw, lib, path_vars)
        if resolved is None:
            return None
        specs.extend(resolved)
    return tuple(specs) or None


def resolve_bundle_targets(text, lib):
    """Map each bundle variable in ``text`` to the repository files its build
    concatenates (issue #956).

    The PARSE is memoized on the presented bytes; the glob EXPANSION deliberately
    is not, so no memo in this module captures filesystem state — the property
    ``lib/test/test_pin_corpus_lint.py``'s sharding docstring states and its
    ``MemoizedParseContractTests`` pin. Expansion is a handful of single-directory
    globs, so repeating it per call costs far less than the parse it replaces.
    A name whose glob matched nothing is dropped here rather than reported as an
    empty member set.
    """
    resolved = {}
    for name, specs in _bundle_target_specs(text, lib):
        members = _expand_bundle_specs(specs)
        if members is not None:
            resolved[name] = members
    return resolved


@functools.lru_cache(maxsize=_IMAGE_PARSE_CACHE_SIZE)
def _bundle_target_specs(text, lib):
    """Parse bundle membership once per source, as unexpanded member specs.

    A name is dropped — leaving its pins with the pre-existing refusal — when the
    build is unresolvable, when two builds target the same name, or when the name
    is reassigned after being built: the map is read for every site in the source,
    and an ambiguous name cannot answer per line.
    """
    path_vars = _extended_path_vars(text, lib)
    arrays = _bundle_arrays(text, lib, path_vars)
    bundles = {}
    ambiguous = set()
    for _, line in join_logical_lines(text):
        stripped = line.lstrip()
        # Tokenizing is the expensive step on a source this size, so it runs only
        # for a line that could name a builder at all.
        tokens = (
            tokenize(stripped)
            if stripped
            and not stripped.startswith("#")
            and any(builder in stripped for builder in BUNDLE_BUILDERS)
            else None
        )
        if tokens and _token_value(tokens[0]) in BUNDLE_BUILDERS:
            if len(tokens) < 3:
                continue
            name = _bundle_variable_name(_token_value(tokens[2]))
            if name is None:
                continue
            if name in bundles or name in ambiguous or line[:1] in {" ", "\t"}:
                # A second build of the same name, or one inside an unmodeled
                # compound, leaves the name ambiguous.
                ambiguous.add(name)
                bundles.pop(name, None)
                continue
            specs = _bundle_call_members(tokens[3:], arrays, lib, path_vars)
            if specs is None:
                ambiguous.add(name)
                continue
            bundles[name] = specs
            continue
        assign = _ASSIGNMENT_RE.match(line)
        if assign is None:
            continue
        name = assign.group(1)
        alias = _bundle_alias_name(assign.group(2).strip())
        if alias is not None and alias in bundles:
            if name not in ambiguous:
                bundles[name] = bundles[alias]
            continue
        if name in bundles:
            ambiguous.add(name)
            bundles.pop(name)
    return tuple(bundles.items())


def _markdown_excluded_line_indices(text):
    """0-based indices of Markdown lines inside a properly closed fenced block.

    A properly closed fenced block is machine-facing content for this boundary.
    An unterminated fence fails closed: its content remains prose-eligible
    rather than allowing a stray opener to exempt the rest of a document.
    """
    lines = text.splitlines(keepends=True)
    excluded = set()
    fence = None
    fence_start = None
    for index, line in enumerate(lines):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence is None:
            if match and not (
                match.group(1)[0] == "`" and "`" in match.group(2)
            ):
                fence = (match.group(1)[0], len(match.group(1)))
                fence_start = index
            continue
        if (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= fence[1]
            and match.group(2).strip() == ""
        ):
            excluded.update(range(fence_start, index + 1))
            fence = None
            fence_start = None
    return excluded


def _markdown_prose_text(text):
    """Return Markdown text outside closed fences and HTML comments."""
    lines = text.splitlines(keepends=True)
    excluded = _markdown_excluded_line_indices(text)
    visible = "".join(
        line for index, line in enumerate(lines) if index not in excluded
    )
    return re.sub(r"<!--.*?-->", "", visible, flags=re.DOTALL)


def _markdown_line_is_prose(visible_line, literal):
    """The conservative issue-810 per-line prose test, single-sourced so the
    presence predicate and the line-number lookup cannot drift: ``literal`` is
    prose on ``visible_line`` when the line is a Markdown heading, or the literal
    itself bears whitespace (a phrase, not a bare token). ``visible_line`` must
    already have its fenced/HTML-comment content removed by the caller."""
    if literal not in visible_line:
        return False
    return bool(re.match(r"^ {0,3}#{1,6}(?:\s+|$)", visible_line)) or bool(
        re.search(r"\s", literal)
    )


def _markdown_literal_is_prose(text, literal):
    """Detect visible Markdown headings and whitespace-bearing prose phrases."""
    visible = _markdown_prose_text(text)
    return any(
        _markdown_line_is_prose(line, literal) for line in visible.splitlines()
    )


def _markdown_prose_literal_lineno(text, literal):
    """1-based original line of the first visible (non-fenced) Markdown line
    where ``literal`` reads as prose under ``_markdown_line_is_prose``. Falls
    back to the first raw occurrence line if no fence-outside line matches (a
    literal resolved only inside a multi-line HTML comment — a case the DOTALL
    strip in ``_markdown_literal_is_prose`` would not have called prose, so the
    fallback is protective: it guarantees the finding always names a real line
    rather than ``None`` even if the two comment-stripping passes ever diverge)."""
    excluded = _markdown_excluded_line_indices(text)
    lines = text.splitlines()
    fallback = None
    for index, line in enumerate(lines):
        if literal in line and fallback is None:
            fallback = index + 1
        if index in excluded:
            continue
        visible = re.sub(r"<!--.*?-->", "", line)
        if _markdown_line_is_prose(visible, literal):
            return index + 1
    return fallback


def _site_inspection_targets(site, repo_root):
    """The file(s) a site's boundary is inspected against, as absolute paths.

    Either the one statically resolved target, or — for a concatenated bundle
    target (issue #956) — the resolved member files, in build order. An empty
    tuple means the target could not be established at all.
    """
    if site.target_path is not None:
        target = Path(site.target_path)
        if not target.is_absolute():
            target = Path(repo_root) / target
        return (target,)
    return tuple(Path(member) for member in site.target_members or ())


def _literal_prose_resolution(site, repo_root, target_loader=None):
    """Return ``(relative_target, 1-based line)`` where ``site.literal`` resolves
    into prose of its statically resolved target — or of the first bundle member
    that resolves it (issue #956) — and ``None`` when it does not (not prose,
    unreadable, absent, or an unresolved target/literal).

    The conservative issue-810 prose boundary: a heading, a whitespace-bearing
    visible Markdown phrase, or hash-comment text is prose; a standalone
    non-heading token, fenced Markdown machine content, and operative source
    text are not. It makes NO reference to a structural declaration and none to
    the site's helper family (issue #925): a count-based helper's literal is
    weighed exactly as a static-helper or raw-``grep`` one, so routing a prose
    pin through ``pin_count`` no longer skips the question.
    """
    if site.literal is None:
        return None
    for target in _site_inspection_targets(site, repo_root):
        resolution = _literal_prose_in_target(
            target, site.literal, repo_root, target_loader
        )
        if resolution is not None:
            return resolution
    return None


def _literal_prose_in_target(target, literal, repo_root, target_loader):
    """The per-file half of ``_literal_prose_resolution``, applied to one file."""
    ext = target.suffix.lower()
    text, error = _read_typed_target(target, target_loader)
    if error is not None or literal not in text:
        return None
    if ext in COMMENT_MD_EXTS:
        if not _markdown_literal_is_prose(text, literal):
            return None
        lineno = _markdown_prose_literal_lineno(text, literal)
    elif ext in COMMENT_HASH_EXTS:
        lineno = None
        for candidate_lineno, comment in hash_comment_regions(text.splitlines()):
            if literal in comment:
                lineno = candidate_lineno
                break
        if lineno is None:
            return None
    else:
        return None
    try:
        relative_target = os.path.relpath(
            os.path.abspath(target), os.path.abspath(repo_root)
        ).replace(os.sep, "/")
    except ValueError:
        relative_target = str(target)
    return relative_target, lineno


def _read_typed_target(target, target_loader):
    """Return target text plus an optional inspection error label."""
    if target_loader is not None:
        return target_loader(target)
    try:
        return target.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, type(exc).__name__


def _typed_pin_inspection_error(site, repo_root, target_loader=None):
    """Return why a typed declaration's target boundary cannot be inspected.

    A bundle target is inspected against its whole member SET (issue #956): every
    member must be inside the repository and readable, and the literal must be
    present in at least one of them — the same two questions the single-file case
    asks, with membership standing in for the one file.
    """
    if site.declaration is None or site.declaration_error is not None:
        return None
    if not site.literal:
        return "typed structural declaration literal cannot be inspected"
    targets = _site_inspection_targets(site, repo_root)
    if not targets:
        return "typed structural declaration target cannot be inspected"
    literal_present = False
    for target in targets:
        try:
            root_path = os.path.abspath(repo_root)
            target_path = os.path.abspath(target)
            if os.path.commonpath((root_path, target_path)) != root_path:
                return (
                    "typed structural declaration target cannot be inspected "
                    "(outside repository)"
                )
        except ValueError:
            return "typed structural declaration target cannot be inspected"
        target_text, error = _read_typed_target(target, target_loader)
        if error is not None:
            return (
                "typed structural declaration target cannot be inspected "
                f"({error})"
            )
        if site.literal in target_text:
            literal_present = True
    if not literal_present:
        return (
            "typed structural declaration literal cannot be inspected "
            "(absent from target)"
        )
    return None


def _python_read_target(node, repo_root):
    """Return (contains file-text read, statically resolved target or None)."""
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in {"read", "read_text"}
        ):
            continue
        receiver = child.func.value
        path_arg = None
        if (
            child.func.attr == "read_text"
            and isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "Path"
            and receiver.args
        ):
            path_arg = receiver.args[0]
        elif (
            child.func.attr == "read"
            and isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "open"
            and receiver.args
        ):
            path_arg = receiver.args[0]
        target = None
        if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
            target = Path(path_arg.value)
            if not target.is_absolute():
                target = Path(repo_root) / target
            target = str(target)
        return True, target
    return False, None


def extract_python_guard_sites(text, source_path, repo_root):
    """Extract direct Python assertions over file text."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise InfrastructureError(
            f"Python pin source cannot be parsed: {source_path}: {exc}"
        ) from exc
    physical = text.splitlines()
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def lexical_scope(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return node
        return tree

    assigned_bindings = {}
    for assignment in ast.walk(tree):
        if (
            isinstance(assignment, ast.Assign)
            and len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
        ):
            is_read, target = _python_read_target(assignment.value, repo_root)
            key = (lexical_scope(assignment), assignment.targets[0].id)
            assigned_bindings.setdefault(key, []).append(
                (assignment.lineno, is_read, target)
            )
    sites = []
    for node in ast.walk(tree):
        literal = haystack = helper = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "assertIn"
            and len(node.args) >= 2
        ):
            literal, haystack = node.args[:2]
            helper = f"python-{node.func.attr}"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "assertRegex"
            and len(node.args) >= 2
        ):
            haystack, literal = node.args[:2]
            helper = "python-assertRegex"
        elif isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
            comparison = node.test
            if (
                len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.In)
                and len(comparison.comparators) == 1
            ):
                literal = comparison.left
                haystack = comparison.comparators[0]
                helper = "python-assert-in"
        direct_read, target_path = (
            _python_read_target(haystack, repo_root)
            if haystack is not None
            else (False, None)
        )
        assigned_read = False
        if isinstance(haystack, ast.Name):
            bindings = assigned_bindings.get(
                (lexical_scope(node), haystack.id), ()
            )
            prior = [
                binding for binding in bindings if binding[0] < node.lineno
            ]
            if prior:
                _, assigned_read, target_path = max(
                    prior, key=lambda binding: binding[0]
                )
        if (
            not isinstance(literal, ast.Constant)
            or not isinstance(literal.value, str)
            or haystack is None
            or not (direct_read or assigned_read)
        ):
            continue
        line_end = getattr(node, "end_lineno", node.lineno)
        declaration, error = parse_structural_declaration(
            physical[node.lineno - 1 : line_end]
        )
        sites.append(
            GuardSite(
                source_path,
                node.lineno,
                line_end,
                "raw-presence",
                helper,
                literal.value,
                target_path,
                declaration,
                error,
                None,
                _resolved_target_token(target_path, None, None, repo_root),
            )
        )
    return sites


def _raw_guard_site(
    match,
    *,
    path_vars,
    literal_vars,
    lib,
    repo_root,
    source_path,
    lineno,
    line_end,
    lines,
    bundle_targets=None,
    extended_path_vars=None,
):
    """Resolve one syntactically executable raw presence match."""
    target_token = match.group("target")
    if (
        len(target_token) >= 2
        and target_token[0] == target_token[-1]
        and target_token[0] in {"'", '"'}
    ):
        target_token = target_token[1:-1]
    var_match = _VARREF.match(target_token)
    var_name = var_match.group(1) if var_match else ""
    target = path_vars.get(var_name) if var_name else None
    if target is None:
        target = _resolve_inline_var_path(target_token, lib, path_vars)
    if target is None and extended_path_vars:
        # The same extended-expansion fallback the helper path takes (issue #956),
        # applied before the scratch-name carve-out below so that carve-out keeps
        # firing only for a path that is otherwise unresolvable.
        target = extended_path_vars.get(var_name) if var_name else None
        if target is None:
            target = _resolve_inline_var_path(target_token, lib, extended_path_vars)
    if target is None and "$" not in target_token:
        target = (
            target_token
            if os.path.isabs(target_token)
            else os.path.join(repo_root, target_token)
        )
    # A runtime scratch haystack is out of scope: it holds what THIS run produced
    # (captured argv, a stub's stderr), not repository source, so a grep over it is
    # an executable assertion rather than a source-presence pin. The `TMP_`/`TEMP_`
    # name is the declaration. Recognize the inline `"$TMP_DIR/capture"` shape as
    # well as a bare `"$TMP_FILE"` — a scratch dir plus a relative capture name is
    # the ordinary way to write one, and exempting only the bare form was an
    # artifact of `_VARREF` being whole-token-anchored, not a narrower policy. The
    # carve-out still fires ONLY when the path is otherwise unresolvable, so it can
    # never mask a target that does resolve into the repository.
    if target is None and not var_name:
        inline_var = _INLINE_VAR.match(target_token)
        var_name = inline_var.group(1) if inline_var else ""
    if (
        target is None
        and var_name
        and re.match(r"^(?:TMP|TEMP)(?:_|$)", var_name)
    ):
        return None
    members = None
    if target is None and var_name and bundle_targets:
        # A raw `grep -qF … "$CI_BUNDLE"` reads the same concatenated bundle a
        # helper pin does, so it resolves through the same member map (issue #956).
        members = bundle_targets.get(var_name)
    target_abs = os.path.abspath(target) if target is not None else None
    if target_abs is not None:
        try:
            inside_repo = (
                os.path.commonpath((repo_root, target_abs)) == repo_root
            )
        except ValueError:
            inside_repo = False
        if not inside_repo:
            return None
    declaration, error = parse_structural_declaration(lines)
    literal_tokens = tokenize(match.group("literal_token"))
    raw_literal = None
    if literal_tokens:
        raw_literal = resolve_arg(
            literal_tokens[0],
            literal_vars,
            path_vars,
            want_path=False,
            lib=lib,
        )
    return GuardSite(
        source_path,
        lineno,
        line_end,
        "raw-presence",
        None,
        raw_literal,
        target_abs,
        declaration,
        error,
        members,
        _resolved_target_token(target_abs, var_name, members, repo_root),
    )


def extract_guard_sites(text, source_path, repo_root):
    """Extract complete helper and narrow raw repository-presence guard sites."""
    if source_path.endswith(".py"):
        return extract_python_guard_sites(text, source_path, repo_root)
    repo_root = os.path.abspath(repo_root)
    lib = os.path.join(repo_root, "lib")
    helper_specs, helper_families, wrapper_origins = helper_specs_for_source(text)
    definitions = _function_definitions(text)
    function_by_line = {
        line: name
        for name, (_, start, end) in definitions.items()
        for line in range(start, end + 1)
    }
    # Tokenize each logical line once and share the result between the
    # wrapper-invocation pass below and the site pass after it: both tokenize
    # the same left-stripped text under the same options, so on a source of this
    # size the second pass was a measurable duplicate of the first. A blank or
    # comment-led line tokenizes to nothing — tokenize stops at a token-leading
    # '#' — so neither pass can resolve a helper on it; its tokens are recorded
    # as None, which both keeps the retained tokens proportional to the lines
    # that can carry a site and gives both passes one spelling of "skip me".
    tokenized_lines = []
    for lineno, logical_line in join_logical_lines(text):
        stripped = logical_line.lstrip()
        tokens = (
            tokenize(stripped, split_shell_operators=True)
            if stripped and not stripped.startswith("#")
            else None
        )
        tokenized_lines.append((lineno, logical_line, tokens))
    invoked_wrappers = set()
    for invocation_line, _, invocation_tokens in tokenized_lines:
        if invocation_tokens is None:
            continue
        _, invocation_helper = _helper_call(invocation_tokens, helper_specs)
        if (
            invocation_helper in definitions
            and function_by_line.get(invocation_line) != invocation_helper
        ):
            invoked_wrappers.add(invocation_helper)
    represented_body_lines = {
        definitions[name][1] + wrapper_origins[name] - 1
        for name in invoked_wrappers
        if name in wrapper_origins
    }
    maps_by_line = variable_maps_by_line(text, lib, {})
    bundle_targets = resolve_bundle_targets(text, lib)
    extended_path_vars = _extended_path_vars(text, lib)
    physical = text.splitlines()
    sites = []
    for lineno, logical_line, toks in tokenized_lines:
        if toks is None:
            continue
        stripped = logical_line.lstrip()
        path_vars, literal_vars = maps_by_line[lineno]
        lines = physical[lineno - 1 : _line_end(lineno, logical_line)]
        helper_index, helper = _helper_call(toks, helper_specs)
        if helper is not None:
            args = toks[helper_index + 1 :]
            literal = None
            spec = helper_specs[helper]
            lit_selector = spec[0]
            if isinstance(lit_selector, int) and lit_selector < len(args):
                literal = resolve_arg(
                    args[lit_selector],
                    literal_vars,
                    path_vars,
                    want_path=False,
                    lib=lib,
                )
            elif isinstance(lit_selector, str):
                literal = lit_selector
            if lineno in represented_body_lines:
                # An invoked wrapper's body is not a second runtime pin site;
                # its body-derived spec classifies the invocation instead.
                continue
            target = _resolve_guard_target(
                args, spec, literal_vars, path_vars, lib
            )
            members = None
            target_variable = None
            if target is None:
                target_variable = _guard_target_variable(args, spec)
                if target_variable is not None:
                    members = bundle_targets.get(target_variable)
                if members is None:
                    # Not a bundle: retry the single target under the extended
                    # expansions, so a pin anchored on a module root written
                    # ``${OVERRIDE:-${LIB%/lib}}`` is inspectable too (issue #956).
                    target = _resolve_guard_target(
                        args, spec, literal_vars, extended_path_vars, lib
                    )
            declaration, error = parse_structural_declaration(lines)
            sites.append(
                GuardSite(
                    source_path,
                    lineno,
                    _line_end(lineno, logical_line),
                    helper_families[helper],
                    helper,
                    literal,
                    target,
                    declaration,
                    error,
                    members,
                    _resolved_target_token(
                        target, target_variable, members, repo_root
                    ),
                )
            )
            continue
        # `executable_grep_offsets` is read only by the raw-presence loop
        # below, whose pattern requires a literal `grep`, so a line carrying no
        # `grep` needs neither this second span-aware tokenization nor the
        # offsets derived from it. The gate is scoped to the derivation alone —
        # the `cat`-presence branch after the loop still runs for every line.
        executable_grep_offsets = set()
        if "grep" in stripped:
            spanned_tokens = tokenize(
                stripped, split_shell_operators=True, include_spans=True
            )
            shell_tokens = [token for token, _, _ in spanned_tokens]
            executable_grep_offsets = {
                spanned_tokens[index][1]
                for index, helper in _helper_calls(shell_tokens, {"grep": None})
                if helper == "grep"
            }
        raw_matches = []
        for candidate in _RAW_PRESENCE_RE.finditer(stripped):
            command_sub = candidate.start("command_sub")
            executable_command_sub = (
                command_sub >= 0
                and _shell_syntax_is_active_at(stripped, command_sub)
            )
            if (
                not executable_command_sub
                and candidate.start("grep") not in executable_grep_offsets
            ):
                continue
            if not _raw_options_are_fixed_quiet(
                candidate.group("options")
            ):
                continue
            # Negative assertions are absence guards, not presence pins. Canonical
            # yes/no and 1/0 renderings are recognized; an `if grep ...` branch is
            # positive unless explicitly negated.
            before_grep = stripped[: candidate.start("grep")]
            expected = re.search(
                r"""assert_eq\s+(?:"[^"]*"|'[^']*')\s+(?P<q>['"])(?P<value>yes|no|1|0)(?P=q)""",
                before_grep,
            )
            if re.search(r"!\s*$", before_grep):
                continue
            echo_pair = re.search(
                r"&&\s+echo\s+(?P<on_match>yes|no|1|0)"
                r"\s+\|\|\s+echo\s+(?P<on_miss>yes|no|1|0)",
                stripped[candidate.start("grep") :],
            )
            if expected:
                if echo_pair:
                    if expected.group("value") != echo_pair.group("on_match"):
                        continue
                elif expected.group("value") in {"no", "0"}:
                    continue
            raw_matches.append(candidate)

        cat_match = _RAW_CAT_PRESENCE_RE.search(logical_line)
        matches = raw_matches or ([cat_match] if cat_match is not None else [])
        if not matches:
            continue
        for match in matches:
            site = _raw_guard_site(
                match,
                path_vars=path_vars,
                literal_vars=literal_vars,
                lib=lib,
                repo_root=repo_root,
                source_path=source_path,
                lineno=lineno,
                line_end=_line_end(lineno, logical_line),
                lines=lines,
                bundle_targets=bundle_targets,
                extended_path_vars=extended_path_vars,
            )
            if site is not None:
                sites.append(site)
    return sites


def _site_changed(site, changed_lines):
    return any(site.line_start <= line <= site.line_end for line in changed_lines)


def _normalized_revival_authorization(site, repo_root):
    if (
        site.literal is None
        or site.target_path is None
        or site.declaration is None
        or site.declaration_error is not None
    ):
        return None
    relative_target = _repo_relative_or_none(repo_root, site.target_path)
    if relative_target is None:
        return None
    return RevivalAuthorization(
        site.source_path,
        site.family,
        site.helper or "",
        _literal_adjudication_key(site.literal),
        relative_target,
        site.declaration.category,
        site.declaration.rationale,
    )


# ── The sanctioned-rename site comparison (issue #1002) ───────────────────────
#
# WHY THIS EXISTS, and why it is a CORRECTNESS FIX rather than a relaxation.
#
# ``scan_changed_sources`` decides whether a pin site CHANGED by comparing the
# site extracted from the merge-base source image against the site extracted from
# the HEAD image. Both extractions resolve their target paths against the CURRENT
# repository root, so a merge-base image is resolved with current-tree path
# spellings. Across a branch that renames the state directory, that comparison
# asks the wrong question: the merge base spells a pin's target
# ``.devflow/prompt-extensions/review.md`` and HEAD spells it
# ``.prflow/prompt-extensions/review.md``, and those are ONE FILE that ``git mv``
# moved -- so ``old_effective == new_effective`` was measuring path spelling, not
# pin identity, and reported every such pin as re-pointed. This completes, one
# layer up, the same current-first / superseded-fallback rule
# ``_revision_state_dir_path`` states for revision-side blob reads: a path is
# resolved to the ASSET it names at the revision it is read from, not to the
# spelling that revision happened to use.
#
# It cannot absolve a substantive edit, by construction, on three counts:
#
#   1. EXACT TUPLE. A candidate is dropped only when its whole effective tuple
#      -- family, helper, literal, target path, bundle members, declaration and
#      declaration error -- equals a merge-base site's tuple after the rename is
#      applied. Any other difference, however small, leaves the site in the
#      candidate set and it routes through the entire policy unchanged:
#      retirement, revival authorization, prose resolution, the issue-948 ladder
#      and the declaration grammar all run exactly as before on everything that
#      survives this filter. The filter adds no verdict; it only withdraws the
#      claim that a pure respelling is a change.
#   2. ONE-DIRECTIONAL. The mapping is applied to the MERGE-BASE side only, and
#      only superseded -> current. A HEAD-side site still spelled ``.devflow``
#      can never be matched by a ``.prflow`` twin at the base, so the rename
#      cannot be run backwards to launder a site into the exemption.
#   3. ONE FOR ONE. Each merge-base site exempts at most one candidate -- the
#      same discipline ``_deleted_pin_literals`` already applies to moves -- so
#      duplicating a pin still presents the duplicate for adjudication.
#
# The mapping is read from ``lib/rename-map.json``, the repository's single source
# of truth for this rename, and is never a literal copy of it here. That file's
# ``frozen`` block enumerates the names the rename must NOT touch, and those are
# compiled into the same alternation as the rename rules, ordered LONGEST LITERAL
# FIRST with a frozen entry winning any tie, so a frozen name is consumed verbatim
# and no rename rule of equal or shorter length can reach inside it. That ordering
# is load-bearing in both directions: without the frozen precedence a bare
# ``devflow`` rule would rewrite a frozen name (a ``.github/workflows/`` filename such
# as ``devflow.yml``, or ``devflow-marketplace``) and silently exempt a real change to
# it; without the longest-first precedence the frozen subagent namespace ``devflow:``
# would swallow the marker rule ``<!-- devflow:`` that narrows it, and issue #1003's
# marker rename would be a silent no-op. (The two ``workflows.*`` config sub-keys were
# frozen through Tiers 1--3 but issue #1041 renamed them, so they are now ordinary key
# rules read from ``workflows_config_keys``, not frozen literals.)
_RENAME_MAP_PATH = "lib/rename-map.json"
# Characters that continue a token. A rename rule fires only at a token boundary,
# so ``devflow_module_pin_unique`` and ``.devflow-scratch`` are never reached by
# the shorter ``devflow`` / ``.devflow`` rules even before the frozen guards run.
_RENAME_TOKEN_CHARS = "A-Za-z0-9_"
_RENAME_KEY_LEFT = "(?<![%s-])" % _RENAME_TOKEN_CHARS
_RENAME_PATH_LEFT = "(?<![%s])" % _RENAME_TOKEN_CHARS
_RENAME_RIGHT = "(?![%s-])" % _RENAME_TOKEN_CHARS
# One guard the map states as PROSE rather than as data, in its own
# ``frozen._comment``: "Out of scope and tracked separately: the DEVFLOW_*
# environment variables (#1004)". That prefix needs no pattern of its own -- the
# only upper-case rule is the token-matched ``DevFlow`` label, and ``DEVFLOW_GH``
# is a different spelling entirely, so no rule reaches it.
#
# ``devflow:`` DOES need one, because it ends at a non-token character that the
# boundary rule alone would accept. Issue #1003 NARROWED what it protects: the
# comment-marker namespace moved into the map's ``identifiers`` block as the
# longer literal ``<!-- devflow:``, which out-competes this entry under the
# longest-literal ordering below, so what remains frozen here is the namespace
# the rename deliberately keeps -- the subagent-override keys
# (``"devflow:code-reviewer"``, a permanently accepted alias per the config
# schema) and the transitional ``/devflow:<command>`` spellings.
_RENAME_STRUCTURAL_FROZEN = ("devflow:",)
# The map's top-level blocks this builder knows how to read, plus the blocks that
# are documentation or are consumed elsewhere. An unrecognised top-level key is
# REFUSED rather than ignored: a new rename channel added as data alone is
# otherwise a silent no-op -- the map looks edited and the substitution behaves
# identically -- which is the failure mode issue #1003 measured.
_RENAME_MAP_KNOWN_BLOCKS = frozenset(
    {
        "map_version",
        "_comment",
        "config_keys",
        "workflows_config_keys",
        "paths",
        "identifiers",
        "atomic_unit",
        "frozen",
        "retained_unshipped_workflows",
        "transitional_read_through",
    }
)
# The match semantics an ``identifiers`` entry may declare. ``token`` refuses to
# fire when the next character continues the token (so ``DevFlow`` never reaches
# ``DevFlow-layout``); ``prefix`` fires on a self-delimiting literal whose shipped
# uses extend it (``devflow-telemetry-stage-<run>``, ``<!-- devflow:workpad -->``).
_RENAME_IDENTIFIER_MATCHES = ("token", "prefix")


def _rename_frozen_pattern(literal):
    """Compile one ``frozen`` entry, honouring the map's single ``*`` glob form."""
    if literal.endswith("*"):
        return re.escape(literal[:-1]) + "[%s]*" % _RENAME_TOKEN_CHARS
    return re.escape(literal)


def _rename_pair(entry, label):
    """Return the (superseded, current) pair of one ``paths`` entry."""
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("superseded"), str)
        or not isinstance(entry.get("current"), str)
        or not entry["superseded"]
        or not entry["current"]
    ):
        raise ValueError(f"rename map has an invalid {label} entry")
    return entry["superseded"], entry["current"]


def _build_rename_substitution(document):
    """Return a ``str -> str`` superseded-to-current substitution.

    Raises ``ValueError`` when the map cannot be established. The caller
    ``_compiled_rename_substitution`` is what turns that into ``None``, and a
    ``None`` there withdraws every exemption -- the fail-closed direction,
    identical to the pre-fix behaviour.
    """
    if not isinstance(document, dict):
        raise ValueError("rename map root is not an object")
    unknown_blocks = sorted(set(document) - _RENAME_MAP_KNOWN_BLOCKS)
    if unknown_blocks:
        raise ValueError(
            "rename map has an unreadable top-level block: "
            + ", ".join(unknown_blocks)
            + " (teach _build_rename_substitution to read it, or the edit is inert)"
        )
    frozen = document.get("frozen")
    if not isinstance(frozen, dict):
        raise ValueError("rename map has no frozen block")
    frozen_literals = []
    for field in ("config_keys", "identifiers", "workflow_filenames"):
        values = frozen.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError(f"rename map has an invalid frozen.{field}")
        frozen_literals.extend(values)
    frozen_literals.extend(_RENAME_STRUCTURAL_FROZEN)
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("rename map has no paths block")
    path_rules = [
        _rename_pair(paths.get("state_dir"), "paths.state_dir"),
        _rename_pair(paths.get("vendor_dir"), "paths.vendor_dir"),
    ]
    scratch = paths.get("scratch_dirs")
    if not isinstance(scratch, list):
        raise ValueError("rename map has an invalid paths.scratch_dirs")
    for index, entry in enumerate(scratch):
        path_rules.append(_rename_pair(entry, f"paths.scratch_dirs[{index}]"))
    config_keys = document.get("config_keys")
    if not isinstance(config_keys, dict) or not config_keys:
        raise ValueError("rename map has an invalid config_keys block")
    # A renamed key that is also the LAST SEGMENT of a frozen key path is
    # ambiguous when it appears unqualified: a bare `"foo":` in a JSON object
    # carries no parent to tell a frozen `bar.foo` child from a renamed top-level
    # `foo`. Such a rule is accepted only in TOP-LEVEL dotted position (`.foo`),
    # where the leading dot supplies the missing context. Deriving the set from
    # the map's own frozen.config_keys keeps this a property of the map rather
    # than a literal guard that would rot when the frozen list changes. (Since
    # issue #1041 emptied frozen.config_keys — the `workflows.devflow`/
    # `workflows.devflow-review` pair it held is now renamed, not frozen — this set
    # is currently empty and `devflow` is an ordinary key rule; the mechanism stays
    # so a future frozen config-key path re-arms it automatically.)
    ambiguous_keys = {
        value.rsplit(".", 1)[-1] for value in frozen["config_keys"]
    }
    key_rules = []
    for superseded, current in config_keys.items():
        if (
            not isinstance(superseded, str)
            or not isinstance(current, str)
            or not superseded
            or not current
        ):
            raise ValueError("rename map has an invalid config_keys entry")
        if superseded in ambiguous_keys:
            key_rules.append((superseded, current, "qualified-key"))
        else:
            key_rules.append((superseded, current, "key"))
    # The nested workflows.* sub-keys (issue #1041). They are ordinary key renames
    # once unfrozen -- a bare `devflow`/`devflow-review` token respelled to
    # `prflow`/`prflow-review` -- so a respelled pin is a sanctioned rename, not new
    # authorship. `devflow -> prflow` is already a top-level config_keys rule (the
    # workflows child renames to the same current spelling), so only the entries not
    # already carried are added; the frozen `devflow-review.yml` workflow filename
    # still out-competes the shorter `devflow-review` rule under longest-first.
    workflows_keys = document.get("workflows_config_keys")
    if workflows_keys is not None:
        if not isinstance(workflows_keys, dict):
            raise ValueError("rename map has an invalid workflows_config_keys block")
        existing = {rule[0] for rule in key_rules}
        for superseded, current in workflows_keys.items():
            if (
                not isinstance(superseded, str)
                or not isinstance(current, str)
                or not superseded
                or not current
            ):
                raise ValueError("rename map has an invalid workflows_config_keys entry")
            if superseded in existing:
                continue
            key_rules.append((superseded, current, "key"))
    # The identifier channel (issue #1003): brand names that are neither a path
    # nor a config key -- the provenance label, the telemetry branch, the comment
    # marker namespace. Each entry declares its own match semantics, because the
    # shipped uses disagree: the label must NOT reach `DevFlow-layout` while the
    # branch must reach `devflow-telemetry-stage-<run>`, and no single boundary
    # rule can serve both.
    identifiers = document.get("identifiers")
    if not isinstance(identifiers, list):
        raise ValueError("rename map has an invalid identifiers block")
    identifier_rules = []
    for index, entry in enumerate(identifiers):
        label = f"identifiers[{index}]"
        superseded, current = _rename_pair(entry, label)
        match = entry.get("match")
        if match not in _RENAME_IDENTIFIER_MATCHES:
            raise ValueError(f"rename map has an invalid {label} match")
        identifier_rules.append(
            (superseded, current, "identifier-token"
             if match == "token" else "identifier-prefix")
        )
    # A rule whose superseded name is ALSO frozen is inert -- the frozen
    # alternative consumes the match first -- and silently so. Refuse it: the
    # measured way to get this wrong is to add the rule and forget the unfreeze.
    rule_names = {rule[0] for rule in identifier_rules}
    rule_names.update(old for old, _ in path_rules)
    rule_names.update(rule[0] for rule in key_rules)
    inert = sorted(rule_names & set(frozen_literals))
    if inert:
        raise ValueError(
            "rename map both freezes and maps: "
            + ", ".join(inert)
            + " (a frozen name consumes the match, so the rule would never fire)"
        )
    # Longest literal first, so `.devflow/vendor/devflow` and
    # `devflow_review_and_fix` win over the shorter rules whose prefix they share,
    # and the marker namespace `<!-- devflow:` wins over the shorter frozen
    # `devflow:` it narrows. A frozen entry wins any tie, which keeps the original
    # guarantee intact: no rename rule can reach inside a frozen name of equal or
    # greater length (a frozen `.github/workflows/` filename such as `devflow.yml`
    # still beats the bare `devflow` rule).
    alternatives = []
    replacements = {}
    ordered = sorted(
        [(literal, None, "frozen") for literal in frozen_literals]
        + [(old, new, "path") for old, new in path_rules]
        + key_rules
        + identifier_rules,
        key=lambda rule: (len(rule[0]), rule[2] == "frozen"),
        reverse=True,
    )
    for index, (literal, replacement, kind) in enumerate(ordered):
        name = f"rn{index}"
        if kind == "frozen":
            body = _RENAME_KEY_LEFT + _rename_frozen_pattern(literal)
        elif kind == "path":
            body = _RENAME_PATH_LEFT + re.escape(literal) + _RENAME_RIGHT
        elif kind == "qualified-key":
            body = (
                _RENAME_KEY_LEFT + r"\." + re.escape(literal) + _RENAME_RIGHT
            )
            replacement = "." + replacement
        elif kind == "identifier-prefix":
            # Self-delimiting on the right (`<!-- devflow:` ends at `:`,
            # `devflow-telemetry` is extended by `-`), so no right boundary.
            body = _RENAME_KEY_LEFT + re.escape(literal)
        else:
            body = _RENAME_KEY_LEFT + re.escape(literal) + _RENAME_RIGHT
        alternatives.append(f"(?P<{name}>{body})")
        replacements[name] = replacement
    pattern = re.compile("|".join(alternatives))

    def substitute(value):
        if not isinstance(value, str) or not value:
            return value

        def _one(match):
            replacement = replacements.get(match.lastgroup)
            # A frozen alternative carries no replacement and is re-emitted
            # exactly as matched, which also consumes it so no later rule sees it.
            return match.group(0) if replacement is None else replacement

        return pattern.sub(_one, value)

    return substitute


@functools.lru_cache(maxsize=4)
def _compiled_rename_substitution(document_text):
    """Compile one rename-map DOCUMENT into a substitution, or ``None``.

    Memoized on the presented bytes and on nothing else — not on a repository
    root and not on filesystem state — which is the memo contract
    ``lib/test/test_pin_corpus_lint.py``'s module docstring states for every
    cache in this file: a hit returns a value derived from exactly what the
    caller presented, so two repositories in one process cannot answer for each
    other, and a map edited between two scans is observed rather than cached.
    """
    try:
        document = json.loads(document_text)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            "MUTATION-ROUTING-RENAME-MAP-UNAVAILABLE\t"
            f"{_RENAME_MAP_PATH}: {type(exc).__name__}\n"
        )
        return None
    try:
        return _build_rename_substitution(document)
    except (ValueError, re.error) as exc:
        sys.stderr.write(
            "MUTATION-ROUTING-RENAME-MAP-UNAVAILABLE\t"
            f"{_RENAME_MAP_PATH}: {exc}\n"
        )
        return None


def _rename_substitution(repo_root):
    """The substitution declared by ``repo_root``'s map, or ``None``.

    An ABSENT map is the ordinary state of a repository with no rename in flight
    and is silent; an unreadable or malformed one earns a breadcrumb. Both return
    ``None``, which exempts nothing — the fail-closed direction, identical to the
    behaviour before this comparison fix existed.
    """
    try:
        document_text = (Path(repo_root) / _RENAME_MAP_PATH).read_text(
            encoding="utf-8"
        )
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            "MUTATION-ROUTING-RENAME-MAP-UNAVAILABLE\t"
            f"{_RENAME_MAP_PATH}: {type(exc).__name__}\n"
        )
        return None
    return _compiled_rename_substitution(document_text)


def _site_effective(site):
    """The identity a changed-site comparison is actually about."""
    return (
        site.family,
        site.helper,
        site.literal,
        site.target_path,
        site.target_members,
        site.declaration,
        site.declaration_error,
    )


def _rename_normalized_effective(site, substitute):
    """``_site_effective`` with the sanctioned rename applied to every path- and
    literal-bearing member. Called on the MERGE-BASE side only."""
    return (
        site.family,
        site.helper,
        substitute(site.literal),
        substitute(site.target_path),
        None
        if site.target_members is None
        else tuple(substitute(member) for member in site.target_members),
        site.declaration,
        site.declaration_error,
    )


def _drop_rename_only_candidates(candidates, base_sites_by_path, repo_root):
    """Withdraw candidates that are their own merge-base selves, respelled.

    See the section header above for why this is a comparison fix and not an
    amnesty. Everything it keeps reaches the unchanged policy path.
    """
    if not candidates:
        return candidates
    substitute = _rename_substitution(str(repo_root))
    if substitute is None:
        return candidates
    available = {}
    for source_path, sites in base_sites_by_path.items():
        counts = available.setdefault(source_path, {})
        for site in sites:
            key = _rename_normalized_effective(site, substitute)
            counts[key] = counts.get(key, 0) + 1
    kept = []
    for site in candidates:
        counts = available.get(site.source_path)
        # The HEAD side is compared VERBATIM -- never mapped -- which is what
        # makes the exemption one-directional.
        key = _site_effective(site)
        if counts is not None and counts.get(key):
            counts[key] -= 1
            continue
        kept.append(site)
    return kept


def scan_changed_sources(
    current_sources,
    base_sources,
    difftext,
    repo_root,
    *,
    retired_literal_keys=frozenset(),
    revival_authorizations=frozenset(),
    adjudication_delta=None,
    current_adjudications=None,
    target_loader=None,
    consumer_sources=None,
):
    """Classify changed complete sites and return blocking finding strings.

    ``consumer_sources`` is the step-1 machine-consumer corpus (repo-relative
    path -> raw text). Omitting it leaves step 1 finding nothing, which routes
    every site to step 2 — the fail-toward-step-2 direction the ladder requires.
    """
    adjudication_delta = adjudication_delta or {}
    current_adjudications = current_adjudications or {}
    consumer_corpus = build_machine_consumer_corpus(consumer_sources)
    revival_authorizations = frozenset(revival_authorizations)
    patches = parse_unified_diff(difftext)
    new_candidates = []
    # Merge-base sites, keyed by the path a candidate will carry, for the
    # sanctioned-rename comparison below. Collected here rather than re-extracted
    # later because ``extract_guard_sites`` over a multi-megabyte source is the
    # expensive step of this scan and the loop already has the answer.
    base_sites_by_path = {}
    for patch in patches:
        old_sites = []
        new_sites = []
        if patch.old_path in base_sources:
            old_sites = extract_guard_sites(
                base_sources[patch.old_path], patch.old_path, repo_root
            )
            if patch.new_path is not None:
                base_sites_by_path.setdefault(patch.new_path, []).extend(old_sites)
        if patch.new_path in current_sources:
            new_sites = extract_guard_sites(
                current_sources[patch.new_path], patch.new_path, repo_root
            )
            raw_sites_by_span = {}
            for site in new_sites:
                if site.family == "raw-presence":
                    raw_sites_by_span.setdefault(
                        (site.line_start, site.line_end), []
                    ).append(site)
            if any(
                len(group) > 1
                and any(
                    start <= line <= end for line in patch.added_lines
                )
                for (start, end), group in raw_sites_by_span.items()
            ):
                raise InfrastructureError(
                    "multiple raw presence commands occur on one logical line"
                )
            new_candidates.extend(
                site for site in new_sites if _site_changed(site, patch.added_lines)
            )
        # A changed assignment can alter an unchanged call's effective literal
        # or target. Compare sites connected by the unchanged-line mapping so
        # semantic changes enter the same policy path even when the call line is
        # diff context.
        if (
            patch.old_path == patch.new_path
            and patch.old_path in base_sources
            and patch.new_path in current_sources
            and (patch.added_lines or patch.deleted_lines)
        ):
            old_lines = base_sources[patch.old_path].splitlines()
            new_lines = current_sources[patch.new_path].splitlines()
            line_map = {}
            for block in difflib.SequenceMatcher(
                None, old_lines, new_lines, autojunk=False
            ).get_matching_blocks():
                for offset in range(block.size):
                    line_map[block.a + offset + 1] = block.b + offset + 1
            new_by_line = {}
            for site in new_sites:
                new_by_line.setdefault(site.line_start, []).append(site)
            old_occurrences = {}
            for old_site in old_sites:
                old_line = old_site.line_start
                occurrence = old_occurrences.get(old_line, 0)
                old_occurrences[old_line] = occurrence + 1
                new_group = new_by_line.get(line_map.get(old_line), ())
                if occurrence >= len(new_group):
                    continue
                new_site = new_group[occurrence]
                # One definition of "the same site", shared with the
                # sanctioned-rename comparison below. Two hand-written copies of
                # this tuple would be a coupled pair: a field added to one and
                # not the other would let the two disagree about what changed.
                old_effective = _site_effective(old_site)
                new_effective = _site_effective(new_site)
                if old_effective == new_effective:
                    continue
                if not _site_changed(new_site, patch.added_lines):
                    new_candidates.append(new_site)

    # A site whose merge-base self differs only by the sanctioned rename was never
    # re-pointed and never re-authored, so it is not a changed site. This runs
    # before any policy arm: it decides POPULATION, not verdicts.
    new_candidates = _drop_rename_only_candidates(
        new_candidates, base_sites_by_path, repo_root
    )

    normalized_revivals = {}
    for site in new_candidates:
        if site.literal is None:
            continue
        # ``retired_literal_keys`` holds SITE keys (issue #1006): membership is the
        # site's own (source_file, helper, literal, resolved_target), not the
        # literal alone, so a retained pin sharing a retired twin's literal at a
        # different site is not swept into the revival population.
        if site.retirement_key() not in retired_literal_keys:
            continue
        normalized = _normalized_revival_authorization(site, repo_root)
        if normalized is None:
            continue
        if normalized in normalized_revivals:
            raise InfrastructureError(
                "retired wording-pin revival site is ambiguous: "
                f"{normalized.source_path} {normalized.literal_key}"
            )
        normalized_revivals[normalized] = site

    consumed_revivals = set()
    findings = []
    for site in new_candidates:
        # ``literal_key`` keys the literal-scoped adjudication LEDGER (delta and
        # current state); ``retirement_key`` keys SITE-scoped retirement (#1006).
        # They are deliberately distinct: the ledger records a decision per literal,
        # while retirement covers a specific site.
        literal_key = (
            _literal_adjudication_key(site.literal)
            if site.literal is not None
            else None
        )
        retirement_key = site.retirement_key()
        if retirement_key in retired_literal_keys:
            normalized = _normalized_revival_authorization(site, repo_root)
            exact_authorization = (
                normalized is not None and normalized in revival_authorizations
            )
            if exact_authorization:
                consumed_revivals.add(normalized)
            delta = adjudication_delta.get(literal_key)
            current_state = current_adjudications.get(literal_key)
            deliberate_boundary_decision = (
                delta is not None
                and delta[1] == current_state
                and current_state is not None
                and current_state[0] == "boundary"
            )
            if not exact_authorization or not deliberate_boundary_decision:
                missing = []
                if not exact_authorization:
                    missing.append("exact revival authorization")
                if not deliberate_boundary_decision:
                    missing.append("same-branch boundary adjudication change")
                findings.append(
                    f"MUTATION-ROUTING\t{site.source_path}:{site.line_start}\t"
                    f"{site.helper or site.family}\t{site.literal}\t"
                    "retired wording-pin revival lacks " + " and ".join(missing)
                )
                continue
        # Issue #925: helper identity selects no exemption. A count-based helper
        # (pin_count / devflow_module_pin_count) reaches the same prose
        # adjudication every static-helper and raw-grep pin does — the former
        # `count-helper` short-circuit that preceded this block let a prose pin
        # skip the question simply by being spelled as a count.
        inspection_error = _typed_pin_inspection_error(
            site, repo_root, target_loader
        )
        if inspection_error is not None:
            findings.append(
                f"MUTATION-ROUTING\t{site.source_path}:{site.line_start}\t"
                f"{site.helper or site.family}\t{site.literal or '<unresolved-literal>'}\t"
                f"{inspection_error}"
            )
            continue
        # A declaration that is PRESENT but ungrammatical is a declaration error,
        # decided ahead of the routing ladder and never routed around: an unknown
        # category, an empty rationale or a duplicated marker is reported whatever
        # the ladder would have answered (issue #948 keeps this arm exactly as it
        # was — a standing pin on a pre-vocabulary free-text category stays a
        # finding until someone edits the category into a legal one).
        if (
            site.declaration_error is not None
            and site.declaration_error != "missing structural declaration"
        ):
            findings.append(
                f"MUTATION-ROUTING\t{site.source_path}:{site.line_start}\t"
                f"{site.helper or site.family}\t"
                f"{site.literal or '<unresolved-literal>'}\t{site.declaration_error}"
            )
            continue
        # ── The issue-948 three-step routing ladder, in order ──────────────────
        # This is ROUTING, not judging. Step 1 asks a mechanical question and can
        # only ever route DOWN to step 2; step 2 defers to an authorization that
        # was granted elsewhere (the delta-gated ledger, whose review is the real
        # control); step 3 is the residue the policy exists to remove. Reordering
        # these three arms silently changes verdicts, which is why every arm and
        # the order itself is driven from lib/test/test_pin_corpus_lint.py.
        #
        # SCOPE. The ladder governs the RETAINED population #948 is about. A
        # RETIRED wording literal reaching this point has already cleared the
        # revival block above, and its documented contract (CONTRIBUTING.md: a
        # revival needs deliberate authorization AND a *genuine* declared
        # structural boundary) is exactly the pre-#948 prose test — a boundary
        # row alone must not make a revival valid, and both ladder steps rest on
        # such a row. So a retired literal keeps the pre-#948 behavior verbatim.
        ladder_applies = retirement_key not in retired_literal_keys
        # Step 1: a program demonstrably reads the literal. No human needed.
        if (
            ladder_applies
            and machine_consumer_evidence(site.literal, consumer_corpus) is not None
        ):
            continue
        declared = site.declaration is not None and site.declaration_error is None
        # Step 2: the ledger already records this literal as a boundary, and the
        # site's own `# structural-pin-ok:` tag POINTS AT that decision. Both
        # halves are required — a tag alone cannot self-grant legitimacy, and a
        # ledger row alone leaves the reader of the pin no reason at the site.
        prose_resolution = _literal_prose_resolution(
            site, repo_root, target_loader
        )
        if prose_resolution is not None:
            ledger_boundary = ledger_records_boundary(
                literal_key, current_adjudications
            )
            if ladder_applies and declared and ledger_boundary:
                continue
            prose_target, prose_line = prose_resolution
            detail = (
                f"literal resolves into prose at {prose_target}:{prose_line}; "
                f"the {site.helper or site.family} helper does not change the "
                "verdict"
            )
            if ladder_applies:
                missing = []
                if not declared:
                    missing.append(
                        "the site carries no valid '# structural-pin-ok:' declaration"
                    )
                if not ledger_boundary:
                    missing.append(
                        "the adjudication ledger records no boundary decision for "
                        "this literal"
                    )
                detail += "; no program consumer reads it and " + " and ".join(missing)
            findings.append(
                f"MUTATION-ROUTING\t{site.source_path}:{site.line_start}\t"
                f"{site.helper or site.family}\t{site.literal}\t{detail}"
            )
            continue
        if declared:
            continue
        # Step 3: no consumer, no authorized decision to point at.
        detail = site.declaration_error or "wording-only presence pin"
        findings.append(
            f"MUTATION-ROUTING\t{site.source_path}:{site.line_start}\t"
            f"{site.helper or site.family}\t{site.literal or '<unresolved-literal>'}\t{detail}"
        )
    unconsumed = revival_authorizations - consumed_revivals
    if unconsumed:
        first = sorted(unconsumed)[0]
        raise InfrastructureError(
            "adjudication bundle has unconsumed revival authorization: "
            f"{first.source_path} {first.literal_key}"
        )
    return findings


def validate_audited_population(registry, audited_sources, enumerated_sources):
    """Return registry/audit mismatches and audited paths absent from Git."""
    if not isinstance(registry, dict):
        raise InfrastructureError("registry schema: root must be an object")
    if type(registry.get("schema_version")) is not int or registry["schema_version"] != 1:
        raise InfrastructureError(
            "registry schema: schema_version must be integer 1"
        )
    modules = registry.get("test_modules")
    if not isinstance(modules, dict) or not modules:
        raise InfrastructureError(
            "registry schema: test_modules must be a non-empty object"
        )
    registered = {"lib/test/run.sh"}
    for name, row in modules.items():
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name) is None
            or not isinstance(row, dict)
            or not isinstance(row.get("path"), str)
            or re.fullmatch(
                r"lib/test/modules/[A-Za-z0-9][A-Za-z0-9._-]*[.]sh",
                row["path"],
            )
            is None
            or type(row.get("minimum_assertions")) is not int
            or not 1 <= row["minimum_assertions"] <= 1_000_000
        ):
            raise InfrastructureError(
                f"registry schema: invalid test_modules row: {name!r}"
            )
        registered.add(row["path"])
    audited = set(audited_sources)
    enumerated = set(enumerated_sources)
    findings = []
    for path in sorted(registered - audited):
        findings.append(f"registered pin source absent from audited population: {path}")
    for path in sorted(audited - registered):
        findings.append(f"stale audited pin source absent from registry: {path}")
    for path in sorted(audited - enumerated):
        findings.append(f"audited pin source absent from Git enumeration: {path}")
    return findings


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate registry key {key!r}")
        result[key] = value
    return result


def load_registry(path):
    """Load the module registry with the selector's duplicate-key contract."""
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InfrastructureError(f"registry read failed: {exc}") from exc


class _MutationInventoryRow(NamedTuple):
    path: str
    helper: str
    logical_call: str
    line_start: int
    line_end: int
    identity_sha256: str
    disposition: str


@functools.lru_cache(maxsize=1)
def _load_mutation_census_module():
    """Load the census module once per process.

    Re-executing it per call rebuilt a fresh module object each time, which
    discarded that module's own per-source memos before a later scan in the
    same process could reach them. The module is stateless apart from those
    memos, so one instance serves every scan.
    """
    path = Path(__file__).with_name("mutation-pin-census.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "_devflow_mutation_pin_census",
            path,
        )
        if spec is None or spec.loader is None:
            raise InfrastructureError("cannot load mutation-pin census module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # A failed exec leaves a half-initialized module registered under
            # this name. lru_cache does not memoize the raise, so a later call
            # re-execs — but anything that imported the name in between would
            # get the broken object. Unregister before propagating.
            sys.modules.pop(spec.name, None)
            raise
        return module
    except InfrastructureError:
        raise
    except Exception as exc:
        raise InfrastructureError(
            f"cannot load mutation-pin census module: {exc}"
        ) from exc


def _parse_mutation_inventory(path, census):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise InfrastructureError(f"missing mutation-pin inventory: {path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise InfrastructureError(
            f"cannot read mutation-pin inventory: {path}: {exc}"
        ) from exc
    if len(lines) < 3:
        raise InfrastructureError("mutation-pin inventory is truncated")
    source_prefix = "# source_revision\t"
    master_prefix = "# master_sha256\t"
    if not lines[0].startswith(source_prefix) or not re.fullmatch(
        r"[0-9a-f]{40,64}",
        lines[0][len(source_prefix) :],
    ):
        raise InfrastructureError("mutation-pin inventory source revision is malformed")
    if not lines[1].startswith(master_prefix) or not re.fullmatch(
        r"[0-9a-f]{64}",
        lines[1][len(master_prefix) :],
    ):
        raise InfrastructureError("mutation-pin inventory master digest is malformed")
    expected_header = (
        "path\thelper\tlogical_call\tline_start\tline_end\t"
        "identity_sha256\tdisposition\trationale"
    )
    if lines[2] != expected_header:
        raise InfrastructureError("mutation-pin inventory header is malformed")

    rows = {}
    for line_number, line in enumerate(lines[3:], start=4):
        fields = line.split("\t")
        if len(fields) != 8:
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} is malformed"
            )
        (
            source,
            helper,
            call_json,
            start_raw,
            end_raw,
            identity_sha256,
            disposition,
            rationale,
        ) = fields
        try:
            logical_call = json.loads(call_json)
        except json.JSONDecodeError as exc:
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} call is malformed"
            ) from exc
        if not isinstance(logical_call, str) or not logical_call or not rationale:
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} is incomplete"
            )
        if not start_raw.isdecimal() or not end_raw.isdecimal():
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} locator is malformed"
            )
        line_start = int(start_raw)
        line_end = int(end_raw)
        if line_start < 1 or line_end < line_start:
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} locator is invalid"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", identity_sha256):
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} identity is malformed"
            )
        row = census.CensusRow(
            path=source,
            helper=helper,
            logical_call=logical_call,
            line_start=line_start,
            line_end=line_end,
        )
        if census._identity_sha256(row) != identity_sha256:
            raise InfrastructureError(
                f"mutation-pin inventory row {line_number} identity disagrees"
            )
        if identity_sha256 in rows:
            raise InfrastructureError(
                f"mutation-pin inventory repeats identity: {identity_sha256}"
            )
        rows[identity_sha256] = _MutationInventoryRow(
            source,
            helper,
            logical_call,
            line_start,
            line_end,
            identity_sha256,
            disposition,
        )
    return rows, lines[1][len(master_prefix) :]


def scan_retired_mutation_population(repo_root):
    """Require an empty retired-helper census and byte-matching empty inventory."""
    root = Path(repo_root)
    census = _load_mutation_census_module()
    try:
        current = census.build_census(root)
    except census.CensusError as exc:
        raise InfrastructureError(f"mutation-pin census failed: {exc}") from exc

    registry = load_registry(
        root / "scripts/workflow-flight-recorder-registry.json"
    )
    population_findings = validate_audited_population(
        registry,
        AUDITED_PIN_SOURCES,
        set(current.sources),
    )
    if population_findings:
        raise InfrastructureError("; ".join(population_findings))

    inventory, inventory_master = _parse_mutation_inventory(
        root / ".prflow/logs/mutation-pin-corpus-inventory.tsv",
        census,
    )
    current_by_identity = {
        census._identity_sha256(row): row for row in current.rows
    }
    unadjudicated = sorted(
        set(current_by_identity) - census.RETAINED_BOUNDARY_IDENTITIES
    )
    if unadjudicated:
        return [
            "MUTATION-ROUTING\t"
            f"{current_by_identity[identity].path}\t"
            "mutation call is not an adjudicated retained boundary: "
            f"{identity}"
            for identity in unadjudicated
        ]

    if set(inventory) != set(current_by_identity):
        raise InfrastructureError(
            "mutation-pin inventory/current census identity mismatch "
            f"(inventory-only: {sorted(set(inventory) - set(current_by_identity))}; "
            f"census-only: {sorted(set(current_by_identity) - set(inventory))})"
        )
    if inventory_master != current.master_sha256:
        raise InfrastructureError(
            "mutation-pin inventory master digest disagrees with current census"
        )

    retain_dispositions = {
        "retain_helper_infrastructure_boundary",
        "retain_executable_boundary",
    }
    for identity, row in current_by_identity.items():
        recorded = inventory[identity]
        decision = census.adjudicate(row)
        if (
            recorded.disposition not in retain_dispositions
            or decision.disposition != recorded.disposition
        ):
            raise InfrastructureError(
                f"mutation-pin inventory identity is not a retained boundary: {identity}"
            )
    return []


def _invoke_git(git_runner, repo_root, *args):
    command = ["git", "-C", str(repo_root), *args]
    try:
        return git_runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise InfrastructureError(
            f"git {' '.join(args)} invocation failed: {exc}"
        ) from exc


def _run_git(git_runner, repo_root, *args):
    result = _invoke_git(git_runner, repo_root, *args)
    if result.returncode != 0:
        raise InfrastructureError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _run_git_bytes(git_runner, repo_root, *args):
    command = ["git", "-C", str(repo_root), *args]
    try:
        result = git_runner(
            command,
            capture_output=True,
            check=False,
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise InfrastructureError(
            f"git {' '.join(args)} invocation failed: {exc}"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise InfrastructureError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {stderr.strip()}"
        )
    return result.stdout.encode("utf-8") if isinstance(result.stdout, str) else result.stdout


def _decode_utf8(payload, label):
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfrastructureError(f"{label} is not UTF-8: {exc}") from exc


def _source_tree_entries(repo_root, revision, paths, git_runner):
    """Return exact regular source blobs for one committed tree snapshot."""
    if not paths:
        return {}
    output = _run_git(
        git_runner,
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        revision,
        "--",
        *sorted(paths),
    )
    entries = {}
    for row in filter(None, output.split("\0")):
        try:
            metadata, path = row.split("\t", 1)
            mode, kind, _object = metadata.split()
        except ValueError as exc:
            raise InfrastructureError(
                f"scanned source tree row is malformed at {revision}: {row!r}"
            ) from exc
        if path in entries:
            raise InfrastructureError(
                f"scanned source tree has duplicate path at {revision}: {path}"
            )
        if mode not in {"100644", "100755"} or kind != "blob":
            raise InfrastructureError(
                f"scanned source is not a regular blob at {revision}: {path}"
            )
        entries[path] = mode
    return entries


def _read_source_blob(repo_root, revision, path, git_runner):
    return _decode_utf8(
        _run_git_bytes(git_runner, repo_root, "show", f"{revision}:{path}"),
        f"scanned source {revision}:{path}",
    )


def load_machine_consumer_sources(repo_root, git_runner=subprocess.run):
    """Read the tracked step-1 machine-consumer corpus from the worktree.

    The population comes from an index-reading ``git ls-files`` with no
    ``--others`` (the issue-#711 rule: a repository-root-anchored recursive walk
    would descend into sibling worktrees under ``.claude/worktrees/``). Contents
    come from the WORKTREE, and the same corpus serves both the committed-HEAD
    and worktree passes: a consumer added in the same uncommitted change as its
    pin is a normal in-progress state, and since the worktree pass shares the
    corpus anyway, splitting it per revision would change no reachable verdict
    except to red-flag that state. An untracked consumer file is NOT in the
    corpus, and an unreadable or non-UTF-8 one is skipped with a stderr
    breadcrumb — both route their pins to step 2, never to a pass.

    Returns ``(sources, skipped)``. Never drop the second element at a call
    site that treats a corpus miss as evidence: a skipped file is a hole in the
    search, and a miss over that hole is indistinguishable from a real absence.
    """
    listing = _run_git(
        git_runner,
        repo_root,
        *QUOTE_PATH_OFF,
        "ls-files",
        "--",
        *MACHINE_CONSUMER_PATH_PREFIXES,
    )
    sources = {}
    skipped = []
    for path in filter(None, listing.splitlines()):
        if not is_machine_consumer_path(path):
            continue
        try:
            sources[path] = (Path(repo_root) / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append(f"{path}: {type(exc).__name__}")
    if skipped:
        sys.stderr.write(
            "MUTATION-ROUTING-CONSUMER-CORPUS-SKIPPED\t"
            + ", ".join(sorted(skipped))
            + "\n"
        )
    return sources, tuple(skipped)


def _read_worktree_source(repo_root, path, expected_mode=None):
    source_root = Path(repo_root)
    source = source_root / path
    try:
        parent = source_root
        for component in Path(path).parts[:-1]:
            parent /= component
            parent_stat = parent.lstat()
            if stat.S_ISLNK(parent_stat.st_mode):
                raise InfrastructureError(
                    f"pin source has symlinked worktree parent: {path}"
                )
            if not stat.S_ISDIR(parent_stat.st_mode):
                raise InfrastructureError(
                    f"pin source has non-directory worktree parent: {path}"
                )
        source_stat = source.lstat()
        payload = source.read_bytes()
    except InfrastructureError:
        raise
    except OSError as exc:
        raise InfrastructureError(f"pin source unreadable: {path}: {exc}") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise InfrastructureError(f"pin source is not a regular worktree file: {path}")
    executable = bool(source_stat.st_mode & 0o111)
    if expected_mode is not None and executable != (expected_mode == "100755"):
        raise InfrastructureError(
            f"pin source worktree mode differs from HEAD: {path}"
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfrastructureError(f"pin source unreadable: {path}: {exc}") from exc


class _TargetSnapshot(NamedTuple):
    payload: bytes
    path_identity: tuple


def _relative_target_path(repo_root, target):
    root = os.path.abspath(repo_root)
    absolute = os.path.abspath(target)
    try:
        if os.path.commonpath((root, absolute)) != root:
            raise InfrastructureError(
                f"typed target is outside repository: {target}"
            )
    except ValueError as exc:
        raise InfrastructureError(
            f"typed target is outside repository: {target}"
        ) from exc
    relative = os.path.relpath(absolute, root).replace(os.sep, "/")
    _validate_repo_relative_path(relative, "typed target")
    return relative


def _committed_target_loader(repo_root, revision, git_runner):
    """Return a cached loader bound to one immutable committed tree."""
    cache = {}

    def load(target):
        relative = _relative_target_path(repo_root, target)
        if relative not in cache:
            entries = _source_tree_entries(
                repo_root, revision, {relative}, git_runner
            )
            if relative not in entries:
                return None, "FileNotFoundError"
            payload = _run_git_bytes(
                git_runner,
                repo_root,
                "show",
                f"{revision}:{relative}",
            )
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return None, "UnicodeDecodeError"
            cache[relative] = text
        return cache[relative], None

    return load


def _worktree_path_identity(repo_root, relative):
    """Return a per-component identity tuple for a typed target's worktree path.

    Each parent directory and the leaf file contribute
    ``(st_dev, st_ino, st_mode, st_size, st_mtime_ns, st_ctime_ns)``.
    ``_worktree_target_snapshot`` compares this tuple before and after it reads the
    target, and the loader's ``verify()`` compares the full snapshot (the cached
    payload *and* this tuple) again after analysis. Together those catch a target
    that is rewritten (payload or ``st_size``), chmod-ed (``st_mode``), moved onto a
    different inode (``st_ino``/``st_dev``), or touched across a timer tick
    (``st_mtime_ns``/``st_ctime_ns``) while it is under analysis.

    **By-design limitation.** One shape is not discriminable from these fields: an
    unlink-and-recreate that (a) reuses the same inode and (b) completes within one
    tick of the filesystem's timestamp granularity — a host whose inode timestamps
    are coarse relative to the operation stamps both the old and the new inode with
    a byte-identical ``st_mtime_ns``/``st_ctime_ns`` — with byte-identical content.
    On such a host (any that reuses inodes, e.g. ext4) every field of the tuple
    matches before and after. This is accepted rather than guarded because such a
    replacement is harmless: the payload the loader cached is identical to the bytes
    now present, so the analysis is still valid. The payload compare — not this
    identity tuple — is the guarantee that the analyzed bytes are the bytes on disk;
    any recreate with *different* content changes ``st_size`` or the payload and is
    caught regardless.
    """
    root = Path(repo_root)
    current = root
    identities = []
    parts = Path(relative).parts
    for component in parts[:-1]:
        current /= component
        current_stat = current.lstat()
        if stat.S_ISLNK(current_stat.st_mode):
            raise InfrastructureError(
                f"typed target has symlinked worktree parent: {relative}"
            )
        if not stat.S_ISDIR(current_stat.st_mode):
            raise InfrastructureError(
                f"typed target has non-directory worktree parent: {relative}"
            )
        identities.append(
            (
                current_stat.st_dev,
                current_stat.st_ino,
                current_stat.st_mode,
                current_stat.st_size,
                current_stat.st_mtime_ns,
                current_stat.st_ctime_ns,
            )
        )
    leaf = root / relative
    leaf_stat = leaf.lstat()
    if stat.S_ISLNK(leaf_stat.st_mode):
        raise InfrastructureError(
            f"typed target is a symlink in the worktree: {relative}"
        )
    if not stat.S_ISREG(leaf_stat.st_mode):
        raise InfrastructureError(
            f"typed target is not a regular worktree file: {relative}"
        )
    identities.append(
        (
            leaf_stat.st_dev,
            leaf_stat.st_ino,
            leaf_stat.st_mode,
            leaf_stat.st_size,
            leaf_stat.st_mtime_ns,
            leaf_stat.st_ctime_ns,
        )
    )
    return tuple(identities)


def _worktree_target_snapshot(repo_root, relative):
    before = _worktree_path_identity(repo_root, relative)
    payload = (Path(repo_root) / relative).read_bytes()
    after = _worktree_path_identity(repo_root, relative)
    if before != after:
        raise InfrastructureError(
            f"typed target changed while its worktree snapshot was read: {relative}"
        )
    return _TargetSnapshot(payload, after)


def _worktree_target_loader(repo_root):
    """Return a cached loader and a verifier for regular worktree targets."""
    cache = {}

    def load(target):
        relative = _relative_target_path(repo_root, target)
        if relative not in cache:
            try:
                snapshot = _worktree_target_snapshot(repo_root, relative)
            except InfrastructureError:
                raise
            except OSError as exc:
                return None, type(exc).__name__
            try:
                snapshot.payload.decode("utf-8")
            except UnicodeDecodeError:
                return None, "UnicodeDecodeError"
            cache[relative] = snapshot
        return cache[relative].payload.decode("utf-8"), None

    def verify():
        for relative, expected in cache.items():
            try:
                actual = _worktree_target_snapshot(repo_root, relative)
            except (OSError, InfrastructureError) as exc:
                raise InfrastructureError(
                    f"typed target changed during worktree analysis: {relative}"
                ) from exc
            if actual != expected:
                raise InfrastructureError(
                    f"typed target changed during worktree analysis: {relative}"
                )

    return load, verify


def analyze_adjudication_changes(
    repo_root,
    merge_base,
    base_ref="origin/main",
    *,
    git_runner=subprocess.run,
):
    """Authorize the exact merge-base-to-HEAD current-state table delta."""
    repo_root = Path(repo_root)
    worktree_status = _run_git(
        git_runner,
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        _ADJUDICATION_TABLE_PATH,
    )
    if worktree_status:
        raise InfrastructureError(
            "adjudication table worktree differs from HEAD: "
            f"{worktree_status.strip()}"
        )
    listing = _run_git(
        git_runner,
        repo_root,
        "ls-tree",
        "HEAD",
        "--",
        _ADJUDICATION_TABLE_PATH,
    )
    try:
        mode, kind, _object, listed_path = listing.rstrip("\n").split(None, 3)
    except ValueError as exc:
        raise InfrastructureError(
            "adjudication table is not a regular HEAD blob: "
            f"{_ADJUDICATION_TABLE_PATH}"
        ) from exc
    if (
        mode != "100644"
        or kind != "blob"
        or listed_path != _ADJUDICATION_TABLE_PATH
    ):
        raise InfrastructureError(
            "adjudication table is not a regular HEAD blob: "
            f"{_ADJUDICATION_TABLE_PATH}"
        )
    current_bytes = _run_git_bytes(
        git_runner,
        repo_root,
        "show",
        f"HEAD:{_ADJUDICATION_TABLE_PATH}",
    )
    current_text = _decode_utf8(current_bytes, "adjudication table")
    current = parse_current_adjudications(current_text)
    base_bytes = _run_git_bytes(
        git_runner,
        repo_root,
        "show",
        f"{merge_base}:{_ADJUDICATION_TABLE_PATH}",
    )
    manifests, revival_authorizations = discover_new_adjudication_delta_manifests(
        repo_root,
        merge_base,
        include_revivals=True,
        git_runner=git_runner,
    )
    base = parse_current_adjudications(
        _decode_utf8(base_bytes, "base adjudication table")
    )
    actual = compute_adjudication_delta(base, current)
    if actual or revival_authorizations:
        require_current_adjudication_base(
            repo_root,
            base_ref,
            merge_base=merge_base,
            git_runner=git_runner,
        )
    findings = []
    if not is_exactly_authorized_adjudication_delta(base, current, manifests):
        findings.append("MUTATION-ROUTING\tunauthorized pin adjudication delta")
    return AdjudicationAnalysis(
        findings,
        base,
        current,
        actual,
        revival_authorizations,
    )


def scan_adjudication_changes(
    repo_root,
    merge_base,
    base_ref="origin/main",
    *,
    git_runner=subprocess.run,
):
    """Return policy findings for the exact current-state table delta."""
    return analyze_adjudication_changes(
        repo_root,
        merge_base,
        base_ref,
        git_runner=git_runner,
    ).findings


def scan_static_pin_changes(
    repo_root,
    base_ref="origin/main",
    *,
    git_runner=subprocess.run,
):
    """Run the fail-closed static pin classifier over worktree changes."""
    repo_root = Path(repo_root)
    _run_git(git_runner, repo_root, "rev-parse", "--verify", base_ref)
    # A missing local main is the normal Actions checkout shape. Other ancestry
    # failures remain infrastructure failures rather than green skips.
    local_main = _invoke_git(
        git_runner,
        repo_root,
        "show-ref",
        "--verify",
        "--quiet",
        "refs/heads/main",
    )
    if local_main.returncode == 0:
        _run_git(
            git_runner,
            repo_root,
            "merge-base",
            "--is-ancestor",
            "refs/heads/main",
            base_ref,
        )
    elif local_main.returncode != 1:
        raise InfrastructureError(
            "local main resolution failed "
            f"(exit {local_main.returncode}): {local_main.stderr.strip()}"
        )
    merge_base = _run_git(
        git_runner, repo_root, "merge-base", base_ref, "HEAD"
    ).strip()
    if not merge_base:
        raise InfrastructureError("comparison merge base resolved to empty output")
    head_revision = _run_git(git_runner, repo_root, "rev-parse", "HEAD").strip()
    if not head_revision:
        raise InfrastructureError("HEAD source snapshot resolved to empty output")
    adjudication_analysis = analyze_adjudication_changes(
        repo_root,
        merge_base,
        base_ref,
        git_runner=git_runner,
    )
    retired_literal_keys = load_retired_wording_literal_keys(
        repo_root,
        merge_base,
        git_runner=git_runner,
    )
    head_tree_entries = _source_tree_entries(
        repo_root, head_revision, {"lib/test"}, git_runner
    )
    head_entries = {
        path: mode
        for path, mode in head_tree_entries.items()
        if path in AUDITED_PIN_SOURCES
        or re.fullmatch(r"lib/test/test_[^/]*[.]py", path)
    }
    python_tracked = {
        path
        for path in head_entries
        if re.fullmatch(r"lib/test/test_[^/]*[.]py", path)
    }
    python_untracked = set(
        filter(
            None,
            _run_git(
                git_runner,
                repo_root,
                *QUOTE_PATH_OFF,
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                "lib/test/test_*.py",
            ).splitlines(),
        )
    )
    scan_sources = set(AUDITED_PIN_SOURCES) | python_tracked | python_untracked
    staged_drift = _run_git(
        git_runner,
        repo_root,
        "diff",
        "--cached",
        "--name-status",
        "--no-renames",
        head_revision,
        "--",
        "lib/test",
    )
    for row in filter(None, staged_drift.splitlines()):
        try:
            _status, path = row.split("\t", 1)
        except ValueError as exc:
            raise InfrastructureError(
                f"scanned source index diff is malformed: {row!r}"
            ) from exc
        if path in AUDITED_PIN_SOURCES or re.fullmatch(
            r"lib/test/test_[^/]*[.]py", path
        ):
            raise InfrastructureError(
                "scanned source index differs from HEAD: "
                f"{row}"
            )
    head_diff = _run_git(
        git_runner,
        repo_root,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        merge_base,
        head_revision,
        "--",
        *sorted(scan_sources),
    )
    worktree_diff = _run_git(
        git_runner,
        repo_root,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        merge_base,
        "--",
        *sorted(scan_sources),
    )
    untracked = set(
        filter(
            None,
            _run_git(
                git_runner,
                repo_root,
                *QUOTE_PATH_OFF,
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                *sorted(AUDITED_PIN_SOURCES),
            ).splitlines(),
        )
    )
    tracked = set(AUDITED_PIN_SOURCES) & set(head_entries)
    base_entries = _source_tree_entries(
        repo_root,
        merge_base,
        scan_sources,
        git_runner,
    )
    # Only HEAD is required to carry every audited source. The merge base is NOT:
    # a branch that registers a new focused module adds both the module file and
    # its ``AUDITED_PIN_SOURCES`` entry in the same change, so the path is absent
    # from the base tree by construction. Requiring it there failed closed on the
    # one shape the census exists to admit. The base tree stays optional for
    # everything downstream — ``base_sources`` is built from ``base_entries``
    # (whatever the base actually carries), and ``git diff <merge_base>`` already
    # emits a full add-hunk for a tracked path the base lacks — so an audited
    # source missing at base is scanned in its entirety rather than skipped.
    missing_head_audited = set(AUDITED_PIN_SOURCES) - set(head_entries)
    if missing_head_audited:
        raise InfrastructureError(
            "audited pin source absent from committed snapshot HEAD: "
            f"{sorted(missing_head_audited)[0]}"
        )
    registry = load_registry(
        repo_root / "scripts/workflow-flight-recorder-registry.json"
    )
    population_findings = validate_audited_population(
        registry, AUDITED_PIN_SOURCES, tracked | untracked
    )
    if population_findings:
        raise InfrastructureError("; ".join(population_findings))

    # ``git diff <merge_base>`` already carries a hunk for every TRACKED path,
    # including one added after the merge base; only an UNTRACKED path is absent
    # from it and needs the synthetic ``/dev/null`` hunk. Synthesizing for every
    # not-in-base path double-represents a newly committed pin source and emits
    # duplicate policy findings for one physical site.
    untracked_sources = python_untracked | untracked
    worktree_diff_snapshot = worktree_diff

    head_sources = {
        path: _read_source_blob(repo_root, head_revision, path, git_runner)
        for path in sorted(set(head_entries) & scan_sources)
    }
    worktree_sources = {}
    base_sources = {
        path: _read_source_blob(repo_root, merge_base, path, git_runner)
        for path in sorted(base_entries)
    }
    for path in sorted(scan_sources):
        worktree_sources[path] = _read_worktree_source(
            repo_root, path, head_entries.get(path)
        )
        if path in untracked_sources:
            lines = worktree_sources[path].splitlines()
            worktree_diff += (
                f"\ndiff --git a/{path} b/{path}\n"
                "--- /dev/null\n"
                f"+++ b/{path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n"
                + "\n".join(f"+{line}" for line in lines)
                + "\n"
            )
    verified_worktree_diff = _run_git(
        git_runner,
        repo_root,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        merge_base,
        "--",
        *sorted(scan_sources),
    )
    if worktree_diff_snapshot != verified_worktree_diff:
        raise InfrastructureError("scanned source worktree changed during diff analysis")
    if _run_git(git_runner, repo_root, "rev-parse", "HEAD").strip() != head_revision:
        raise InfrastructureError("HEAD source snapshot changed during diff analysis")

    head_target_loader = _committed_target_loader(
        repo_root, head_revision, git_runner
    )
    worktree_target_loader, verify_worktree_targets = _worktree_target_loader(
        repo_root
    )
    consumer_sources, _consumer_sources_skipped = load_machine_consumer_sources(
        repo_root, git_runner
    )
    source_findings = scan_changed_sources(
        head_sources,
        base_sources,
        head_diff,
        str(repo_root),
        retired_literal_keys=retired_literal_keys,
        revival_authorizations=adjudication_analysis.revival_authorizations,
        adjudication_delta=adjudication_analysis.delta,
        current_adjudications=adjudication_analysis.current,
        target_loader=head_target_loader,
        consumer_sources=consumer_sources,
    )
    source_findings.extend(
        scan_changed_sources(
            worktree_sources,
            base_sources,
            worktree_diff,
            str(repo_root),
            retired_literal_keys=retired_literal_keys,
            revival_authorizations=adjudication_analysis.revival_authorizations,
            adjudication_delta=adjudication_analysis.delta,
            current_adjudications=adjudication_analysis.current,
            target_loader=worktree_target_loader,
            consumer_sources=consumer_sources,
        )
    )
    verify_worktree_targets()
    unique_findings = list(dict.fromkeys(source_findings))
    # Positive completion breadcrumb (issue #967). Every precondition this function
    # runs first — the adjudication-table currency check among them — raises
    # InfrastructureError, which aborts BEFORE the two `scan_changed_sources` calls
    # above. That is the correct fail-closed direction, but it is indistinguishable
    # at the caller from any other rc-2 exit, so a branch that tripped a precondition
    # reported "infrastructure failure" while the static classifier silently did not
    # run at all — and the policy findings it would have reported stayed invisible
    # across whole sessions. This line is written only on the path where BOTH passes
    # completed, so its ABSENCE is the caller's evidence that the classifier was
    # skipped rather than clean. `lib/test/run.sh` asserts on it; the two are a
    # coupled pair, and `lib/test/test_pin_corpus_lint.py` drives both directions.
    sys.stderr.write(STATIC_SCAN_COMPLETED_MARKER + "\n")
    return adjudication_analysis.findings + unique_findings


def scan_worktree(repo_root, base_ref="origin/main", **kwargs):
    """Run both required worktree subgates, preserving infrastructure failures."""
    retired_findings = scan_retired_mutation_population(repo_root)
    static_findings = scan_static_pin_changes(repo_root, base_ref, **kwargs)
    return retired_findings + static_findings


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_target(path):
    """Read a resolved target file, returning (text, None) on success or
    (None, reason) when the file passed os.path.isfile yet cannot be read or
    decoded (permission, non-UTF-8, a directory racing in). Its callers turn a
    non-None reason into an UNRESOLVED count + stderr breadcrumb — so a
    resolved-but-unreadable target fails CLOSED (counted, matching the module's
    fail-closed contract) instead of raising an uncaught exception that would
    empty stdout and pass the real-corpus assertion vacuously (issue #375 review)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, type(exc).__name__


def main(argv):
    if len(argv) < 3 or argv[1] not in (
        "lint",
        "wrapped",
        "mutation-routing",
        "mutation-routing-worktree",
    ):
        sys.stderr.write(__doc__ or "")
        return 2
    cmd, pin_source = argv[1], argv[2]
    if cmd == "mutation-routing-worktree":
        if len(argv) != 3:
            sys.stderr.write("mutation-routing-worktree accepts only REPO_ROOT\n")
            return 2
        try:
            findings = scan_worktree(pin_source)
        except InfrastructureError as exc:
            sys.stderr.write(f"MUTATION-ROUTING-INFRASTRUCTURE\t{exc}\n")
            return 2
        for finding in findings:
            print(finding)
        return 3 if findings else 0
    lib = None
    overrides = {}
    md_targets = set()
    reloc = False
    reloc_search_file = None
    reloc_exclude = []
    diff_file = None
    strict = False
    i = 3
    while i < len(argv):
        if argv[i] == "--diff-file" and i + 1 < len(argv):
            diff_file = argv[i + 1]
            i += 2
        elif argv[i] == "--strict":
            # Opt-in exit-code mode (issue #687): make the exit code carry the
            # finding signal so a caller can key on it. Takes no value, so it
            # mirrors --reloc's single-token arm. Off by default → byte-for-byte
            # today's behaviour, which is why every existing call site is
            # unaffected and the #661 rc-0-on-findings self-test still passes.
            strict = True
            i += 1
        elif argv[i] == "--lib" and i + 1 < len(argv):
            lib = argv[i + 1]
            i += 2
        elif argv[i] == "--var" and i + 1 < len(argv):
            name, _, val = argv[i + 1].partition("=")
            overrides[name] = val
            i += 2
        elif argv[i] == "--md" and i + 1 < len(argv):
            md_targets.add(argv[i + 1])
            i += 2
        elif argv[i] == "--reloc":
            reloc = True
            i += 1
        elif argv[i] == "--reloc-search-set" and i + 1 < len(argv):
            reloc_search_file = argv[i + 1]
            i += 2
        elif argv[i] == "--reloc-exclude" and i + 1 < len(argv):
            reloc_exclude.append(argv[i + 1])
            i += 2
        else:
            sys.stderr.write(f"unknown arg: {argv[i]}\n")
            return 2
    if lib is None:
        lib = os.path.dirname(os.path.dirname(os.path.abspath(pin_source)))
    if cmd == "lint":
        return run_lint(pin_source, lib, overrides, md_targets, strict=strict)
    if cmd == "mutation-routing":
        return run_mutation_routing(pin_source, lib, overrides, md_targets, diff_file)
    return run_wrapped(
        pin_source, lib, overrides, md_targets,
        reloc=reloc, reloc_search_file=reloc_search_file, reloc_exclude=reloc_exclude,
        strict=strict,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))

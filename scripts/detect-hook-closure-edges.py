# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""detect-hook-closure-edges.py — the #458 Stop-hook closure drift-guard walker.

Statically walk every source/`.`/exec/`python3 <path>` edge in each closure file
named by CLOSURE and report every referenced repo .sh/.py that is NOT itself in the
closure — so a future added `source`/exec of a NEW helper is surfaced instead of
silently re-opening the one-hop-deeper hole scripts/harden-stop-hooks.sh closes.

This is the shared walker extracted from lib/test/run.sh's `#458 drift-guard`
assertion (issue #460): a single copy so the drift-guard and its positive-control
test exercise the SAME regex set, and a regex regression turns the suite RED rather
than diverging silently between two hand-copied programs.

I/O contract (env, matching the former inline heredoc):
  input  : env REPO_ROOT — repo root the closure paths are resolved against.
           env CLOSURE    — space-separated repo-relative closure paths (HOOK_TARGETS).
  stdout : one violation line per issue, sorted+deduped. Two shapes:
             `rel -> ref (not in HOOK_TARGETS)`        — an edge escaping the closure
             `rel -> UNREADABLE (<Error>): ...`        — a closure member that could
                                                          not be read/audited at all
  exit   : always 0 — this is a REPORTER; the caller decides (empty output == clean).

Fail-closed reads (issue #460 review): a closure member that is missing, unreadable,
or a directory is itself reported as a violation, NOT swallowed — a drift guard that
cannot read a member it is meant to audit must turn the desk RED, never green. The
file is opened with `errors="replace"` so a stray non-UTF-8 byte in one member does
not crash the whole walk (the regexes are ASCII-anchored, so a replacement char is
harmless); an OSError (missing / permission / is-a-directory) is caught and surfaced.

Command-position source edges are matched by `src_re`, whose prefix set covers both
the shell metacharacters that can precede a command-position `.`/`source` — line
start, `;`, `&`, `|`, `(`, and (issue #460) `!` and `{` — AND (issue #460 review) the
reserved words that open a command position — `then`, `do`, `else`, `elif` — so a
negation-guarded (`if ! . "$dep"`), brace-grouped (`{ . "$dep"; }`), or keyword-
position (`then . "$dep"`) source edge is detected, not a blind spot. Trailing shell
comments are stripped quote-aware (a `#` inside a quoted string — e.g. an `issue #$n`
breadcrumb — is NOT a comment, so a real edge later on the same line is not lost).

Python-import edges (issue #805). A `.py` closure member can pull in another repo file
NOT through a shell spawn but through an in-process `importlib.util.spec_from_file_location`
load (the idiom modules with hyphenated filenames use — scripts/pretooluse-shape-guard.py
loads lib/test/extract-command-shapes.py this way, which loads extract-command-heads.py in
turn). That edge runs PR-head-editable Python inside the sourcing process, so it is exactly
as trust-sensitive as a `source`/`exec`, yet the shell-syntax regexes above cannot see it. Three objects model
it: `_HAS_SPEC` gates a file on containing a `spec_from_file_location` call ANYWHERE in it
(not on the same line), and only then are that file's candidates counted; `pyjoin_re`
captures a quoted `.py`/`.sh` BASENAME inside an `os.path.join(...)` call — the dominant
form, since the basename normally sits on the join line rather than the spec line, and it
requires no `/`; and `specarg_re` captures a path passed as a literal directly to
`spec_from_file_location(...)`, and it alone requires the literal carry a `/`. So the
guard's own dependency edge is auditable and the closure the trusted-source floor certifies
is one the walker can actually inspect. A fully variable-assembled path is not statically
resolvable (the same limit `assign_var_re` documents for the shell forms).

Known granularity limits (documented, not silently assumed — none occur in the current
closure; all are conservative gaps a maintainer widening the closure should keep in
mind):
  - **Basename-only membership.** Closure membership is compared by BASENAME only — the
    sources reference their deps by `$DIR/…`-relative paths not statically resolvable
    here — so a same-basename file at a different path reads as in-closure.
  - **Slash-less source.** `slashsh_re` requires a `/` before the `.sh`, so a slash-less
    same-directory `. foo.sh` source is not captured.
  - **Variable-indirected source (issue #460 review).** A source whose path is held
    entirely in a variable set elsewhere (`DEP="$HERE/newdep.sh"; . "$DEP"`) is only
    caught via `assign_re`/`assign_var_re` on the *assignment* line; if the path is
    assembled dynamically (e.g. built from `$1`, a loop, or command output) the edge
    escapes. `assign_var_re` widens the common `VAR="$DIR/name.sh"` shape into scope,
    but a fully-dynamic indirection is not statically resolvable.
  - **Python-internal spawns, and the .py/.sh scan split.** A `.py` member is audited for
    the `importlib` load form below plus the literal Python-spawn form
    (`pyspawn_api_re` + `pyspawn_path_re`: a spawn API and a quoted `scripts/`/`lib/`-
    rooted path on the SAME line, which covers `subprocess.run(["bash",
    "scripts/new.sh"])` and `os.system("lib/x.sh")`). The shell-form edge syntaxes above
    are deliberately NOT run over a `.py` member (they would match shell-looking tokens
    inside Python docstrings and string literals, which are not live edges; see
    `refs_in`'s `is_py` branch). Still uncaught for a `.py` member: a spawn whose path is
    assembled from a variable, an f-string, or `os.path.join`, a spawn split across
    physical lines, and a shell-form edge that a `.py` file somehow really carried.
  - **Line-continuation source/exec.** Matching is line-based: `src_re`/`slashsh_re` and
    the exec regexes require the keyword and the path on the SAME line, so a
    backslash-continued source (a `.`/`source` whose path sits on the next physical line
    after a trailing backslash) is not captured.
The jq PROGRAM edge (`-f *.jq`) is out of scope (jq is sandboxed — not a shell/RCE
vector).
"""

import os
import re
import sys

src_re = re.compile(r'(?:^|[;&|(!{]|\b(?:then|do|else|elif)\b)\s*(?:\.|source)\s')
slashsh_re = re.compile(r'/([A-Za-z0-9_.-]+\.sh)\b')
pyexec_re = re.compile(r'\bpython3\s+"?([^\s"]*\.py)\b')
shexec_re = re.compile(r'\b(?:bash|sh)\s+"?([^\s"]*\.sh)\b')
execb_re = re.compile(r'\bexec\s+"?([^\s"]*\.(?:sh|py))\b')
assign_re = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*=[^\s#]*?((?:scripts|lib)/[A-Za-z0-9_.-]+\.(?:sh|py))'
)
# A `$DIR/name.sh`-style assignment (issue #460 review): catches the common variable-
# indirected source shape `DEP="$HERE/newdep.sh"; . "$DEP"` at the assignment line, where
# the sourced path carries no literal `scripts/`/`lib/` prefix. Captures the basename.
assign_var_re = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*=\s*"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?'
    r'(?:/[A-Za-z0-9_.-]+)*/([A-Za-z0-9_.-]+\.(?:sh|py))\b'
)
# Python-import edge (issue #805): a `.py` closure member that loads another repo file
# via `importlib.util.spec_from_file_location`. The loaded path is normally assembled with
# `os.path.join(dir, "name.py")` (the basename literal sits on the join line, not the spec
# line), so the basename is captured from a quoted `.py`/`.sh` literal inside an
# `os.path.join(...)` call — but ONLY counted for a file that also contains a
# `spec_from_file_location` call (`_HAS_SPEC` below), so an ordinary `os.path.join` of a
# data file in a non-importing member is not misread as a code edge. A path passed as a
# literal directly to `spec_from_file_location(...)` is captured too.
# Counted PER CALL, not per file: the trailing `\(` is load-bearing — a prose/docstring
# mention of the symbol (`loaded through the \`importlib.util.spec_from_file_location\`
# idiom`) is not a load, and counting it would demand a target path that does not exist
# and fail the member closed for a mention. Both real closure members carry exactly such a
# mention alongside their single real call.
_HAS_SPEC = re.compile(r'\bspec_from_file_location\s*\(')
# Sentinel edge returned when a `.py` member performs a `spec_from_file_location` load
# whose target path neither capture form resolves. It is not a basename, so it can never
# collide with a real closure member and is always reported as a violation.
_UNRESOLVABLE_IMPORT = "UNRESOLVABLE-IMPORT (spec_from_file_location target not statically resolvable)"
# `.*?` (non-greedy, line-scoped) so a nested call inside the join —
# `os.path.join(os.path.dirname(os.path.abspath(__file__)), "x.py")` — does not truncate
# the scan at its inner `)`; it stops at the FIRST quoted `.py`/`.sh` literal on the line.
pyjoin_re = re.compile(
    r'os\.path\.join\(.*?["\']([A-Za-z0-9_.-]+\.(?:py|sh))["\']'
)
specarg_re = re.compile(
    r'spec_from_file_location\([^)]*["\']([^\s"\']*/[A-Za-z0-9_.-]+\.(?:py|sh))["\']'
)
# Python-mediated SPAWN edge (issue #805 review). A `.py` member does not get the shell
# edge syntaxes (they would match shell-looking tokens inside docstrings and string
# literals, which are not live edges), which left a `.py` member's
# `subprocess.run(["bash", "scripts/new.sh"])` spawn of a repo script unmatched. This
# regex closes the common literal form WITHOUT reopening the docstring false-positive
# surface: it requires a spawn-API token AND a quoted repo-rooted `scripts/`/`lib/` path
# on the SAME line, so prose mentioning one or the other in isolation matches nothing.
pyspawn_api_re = re.compile(r'\b(?:subprocess\.(?:run|call|check_call|check_output|Popen)|Popen|os\.system|os\.popen|os\.exec[lv][ep]*)\s*\(')
pyspawn_path_re = re.compile(r'["\']((?:scripts|lib)/[A-Za-z0-9_./-]*[A-Za-z0-9_.-]\.(?:sh|py))["\']')


def _strip_comment(line):
    """Drop a trailing shell comment, quote-aware.

    A comment starts at the first '#' that is UNQUOTED and at a token boundary
    (line start or preceded by whitespace). A '#' inside a single/double-quoted
    string (e.g. an `issue #$n` breadcrumb) is preserved, so a real source/exec
    edge later on the same line is not lost (issue #460 review, FP4).
    """
    in_s = in_d = False
    prev_ws = True  # line start is a token boundary
    for i, ch in enumerate(line):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == '#' and not in_s and not in_d and prev_ws:
            return line[:i]
        prev_ws = ch.isspace()
    return line


def refs_in(path):
    """Return the set of repo-file basenames referenced by source/exec edges in `path`.

    Raises OSError if `path` cannot be opened (missing / permission / directory) —
    the caller surfaces that as a violation rather than treating it as "no edges".
    """
    out = set()
    # Edge detection is scoped by file type. The shell-syntax regexes (source/exec/assign)
    # apply to a .sh member; a .py member's meaningful outbound edge is the in-process
    # `importlib.util.spec_from_file_location` load (issue #805), and running the shell
    # regexes over Python would only match shell-looking tokens inside docstrings/strings
    # (e.g. a `bash x.sh` example) that are NOT live edges — so a .py member gets ONLY the
    # importlib capture. (A .py member's Python-mediated `subprocess`/`os.system` spawn of a
    # repo script remains a documented, uncaught limit — see the module docstring.)
    is_py = path.endswith(".py")
    spec_call_count = 0
    py_import_candidates = set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = _strip_comment(raw)
            if not line.strip():
                continue
            if not is_py:
                if src_re.search(line):
                    for m in slashsh_re.finditer(line):
                        out.add(m.group(1))
                for rx in (pyexec_re, shexec_re, execb_re):
                    for m in rx.finditer(line):
                        out.add(os.path.basename(m.group(1)))
                for rx in (assign_re, assign_var_re):
                    for m in rx.finditer(line):
                        out.add(os.path.basename(m.group(1)))
                continue
            spec_call_count += len(_HAS_SPEC.findall(line))
            for m in pyjoin_re.finditer(line):
                py_import_candidates.add(m.group(1))
            for m in specarg_re.finditer(line):
                py_import_candidates.add(os.path.basename(m.group(1)))
            # Python-mediated spawn of a repo script: both tokens on the same line.
            if pyspawn_api_re.search(line):
                for m in pyspawn_path_re.finditer(line):
                    out.add(os.path.basename(m.group(1)))
    # A member's `importlib.util.spec_from_file_location` load is a real, trust-sensitive
    # edge only when the file actually performs such a load; the `os.path.join(... .py ...)`
    # basename candidates are added to the edge set only then (fail toward NOT inventing an
    # edge for a data-file join in a non-importing member).
    if is_py and spec_call_count:
        if len(py_import_candidates) < spec_call_count:
            # FAIL CLOSED, like the UNREADABLE arm, and PER CALL rather than per FILE.
            # The file demonstrably performs `spec_call_count` `spec_from_file_location`
            # loads — it executes that many other repo files in-process — but fewer target
            # paths resolved (a `Path(__file__).parent / name` join, an f-string, a
            # variable basename, a multi-line join). A per-FILE test ("did ANY target
            # resolve?") reports a member with one resolvable and one unresolvable load
            # CLEAN, which is the fail-OPEN direction in a security floor's drift guard:
            # the walker would certify a closure containing an in-process edge it cannot
            # see, which is how an unmodelled import leaves PR-head-editable Python running
            # inside the floor. Requiring at least one resolved target per load surfaces it
            # instead. The comparison is deliberately conservative in the safe direction:
            # a load whose target is captured by BOTH forms, or a loop that joins several
            # names for one load, yields candidates >= calls and stays clean.
            return {_UNRESOLVABLE_IMPORT}
        out |= py_import_candidates
    return out


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main():
    _force_utf8_streams()
    root = os.environ["REPO_ROOT"]
    closure = os.environ["CLOSURE"].split()
    closure_base = {os.path.basename(p) for p in closure}
    violations = []
    for rel in closure:
        try:
            refs = refs_in(os.path.join(root, rel))
        except OSError as exc:
            # A closure member the guard cannot read is a fail-CLOSED violation, never
            # a silent empty set: it means HOOK_TARGETS names a path that is missing,
            # unreadable, or a directory — a drift the guard exists to surface.
            violations.append(
                f"{rel} -> UNREADABLE ({exc.__class__.__name__}): cannot audit this closure member"
            )
            continue
        for ref in refs:
            base = os.path.basename(ref)
            if base == os.path.basename(rel):
                continue
            if base not in closure_base:
                violations.append(f"{rel} -> {ref} (not in HOOK_TARGETS)")
    for v in sorted(set(violations)):
        print(v)


if __name__ == "__main__":
    main()

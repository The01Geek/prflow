#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# harden-stop-hooks.sh — the review runner's Stop-hook trusted-source floor (issue #458).
#
# SIBLING of scripts/filter-runner-tools.sh, applied to the Stop-hook channel the
# deny-floor's tool-permission machinery cannot reach. .claude/settings.json wires
# three `Stop` hook commands — `bash lib/efficiency-trace.sh --persist`,
# `bash lib/implement-stop-guard.sh`, and `bash …/scripts/stop-hook-probe.sh`. Under
# claude-code-action the hook CONFIGURATION is restored from the base branch
# (trusted), but the SCRIPT FILES those commands exec live under lib/ and scripts/,
# NOT under .claude/, so in the review job (.github/workflows/devflow-runner.yml
# checks out ref = the PR HEAD) they are supplied by the PR-author-editable checkout.
# A PR that edits any of those targets would otherwise obtain unmediated shell
# execution at session end inside a secrets-bearing CI job — bypassing the #363 head
# extractor, the #401 shape rules, and the #402 tree-mutation deny-floor entirely
# (the #404 REJECT class: "the review job checks out the PR head, so a checked-out
# copy is PR-author-editable, and a floor the PR controls is no floor").
#
# ── TRANSITIVE CLOSURE, not just the three entry points (issue #458 REJECT) ──────
# Hardening only the three entry scripts is INCOMPLETE: each `source`s / `exec`s /
# `python3`-runs further PR-head-editable files under lib/ + scripts/, and `source`
# resolves relative to ${BASH_SOURCE[0]} IN THE PR-HEAD WORKSPACE, so a hardened
# base-copy entry would still pull in the PR-HEAD copy of its dependency — the hole
# is one `source`/`exec` hop deeper. So this floor hardens the FULL transitive
# source/exec/python3 closure of the three entries. The verified edges (each an
# actual source/exec/interpreter reference, comment mentions excluded) are:
#   lib/efficiency-trace.sh     -> lib/resolve-jq.sh, lib/config-source.sh,
#                                  scripts/config_fingerprint.py, lib/telemetry-branch.sh
#   lib/implement-stop-guard.sh -> lib/config-source.sh, scripts/workpad.py
#   scripts/stop-hook-probe.sh  -> lib/resolve-jq.sh
#   scripts/pretooluse-shape-guard.py -> lib/test/extract-command-shapes.py (importlib load, #805)
#   lib/resolve-jq.sh           -> lib/resolve-bin.sh
#   lib/config-source.sh        -> scripts/config-get.sh
#   lib/resolve-bin.sh          -> (leaf: only external tool probes)
#   lib/telemetry-branch.sh     -> lib/config-source.sh
#   scripts/config-get.sh       -> (leaf: inline python3 -c, git, no repo files)
#   scripts/config_fingerprint.py -> (leaf: stdlib only)
#   scripts/workpad.py          -> (leaf: git/gh subprocesses only, no repo files)
#   lib/test/extract-command-shapes.py -> lib/test/extract-command-heads.py (importlib load, #805)
#   lib/test/extract-command-heads.py  -> (leaf: stdlib only)
# The two importlib edges above are seen by the walker's Python-import edge form (#805);
# scripts/pretooluse-shape-guard.py is a .py ENTRY, so a missing trusted copy installs the
# language-appropriate Python stub (STUB_PY), not the bash STUB.
# lib/test/run.sh's drift-guard (the shared walker scripts/detect-hook-closure-edges.py)
# verifies the closure is transitively closed — it checks each HOOK_TARGETS member's
# DIRECT source/exec edges and turns RED if any references a repo file NOT in HOOK_TARGETS
# (the guarantee holds inductively: a genuinely new closure member must itself be added to
# HOOK_TARGETS, after which its own direct edges are checked on the next run — the walker
# does not recurse into non-closure files). It reports a COMMAND-POSITION source edge —
# a negation-guarded `if ! . "$dep"`, a brace-grouped `{ . "$dep"; }`, or a keyword-position
# `then . "$dep"` (a positive-control test asserts each such form is reported) — so the
# closure can never silently fall behind the code. Residual (NOT hardened, by design): the jq
# PROGRAM lib/efficiency-trace.jq, fed to jq via `-f`. jq is sandboxed — it cannot
# spawn a shell, exec, or write outside its stdout — so a PR-head `.jq` is not a
# shell/RCE vector (and the review job is read-only, so it cannot push tampered
# output either); it is outside the source/./exec/python3 edge set this floor closes.
#
# ── STUB vs TRUSTED-COPY per file class (issue #458 REJECT caveat) ───────────────
# A no-op `exit 0` stub is correct for an ENTRY (skipping the hook is safe). But a
# SOURCED library (resolve-jq.sh, config-source.sh, resolve-bin.sh, telemetry-branch.sh) runs INLINE in
# the sourcing script, so an `exit 0` stub would exit the SOURCING ENTRY mid-run and
# BREAK the legitimate base hook. So the fail-closed treatment differs by class:
#   * ENTRY (HOOK_ENTRY_TARGETS)   — trusted base copy, else `exit 0` stub. Safe:
#                                    running no hook is always safe.
#   * SOURCED LIB (HOOK_SOURCED_TARGETS) — trusted base copy (the NORMAL case: every
#                                    closure file is repo-tracked and materialized
#                                    from the base ref, so a trusted copy normally
#                                    exists). If a trusted copy is MISSING (a broken
#                                    /partial deployment), it is stubbed to displace
#                                    the PR-head copy AND every ENTRY is neutralized
#                                    to `exit 0` — so no entry ever reaches the line
#                                    that would source the stub. This is BOTH
#                                    fail-closed (PR-head code never runs) AND
#                                    non-breaking when trusted copies exist.
#   * EXEC'd dep (the rest: config-get.sh, config_fingerprint.py, workpad.py) —
#                                    trusted base copy, else `exit 0` stub. Safe: an
#                                    exec runs in a SUBPROCESS, so a stub (or a bash
#                                    stub reached via `python3`, which errors) makes
#                                    the subprocess a no-op and the entry degrades
#                                    through its own best-effort path — it does not
#                                    exit the entry mid-run, so no entry neutralization
#                                    is needed for a missing exec dep.
# So the executed script is either the base-branch version or a stub that does
# nothing; the PR-head version never runs. (An unedited PR yields byte-identical base
# copy CONTENTS; the unconditional `chmod +x` may still surface a mode-only delta on a
# target tracked non-executable — lib/resolve-jq.sh, lib/resolve-bin.sh, lib/telemetry-branch.sh
# and, since #805, lib/test/extract-command-shapes.py + lib/test/extract-command-heads.py are 100644 —
# under core.fileMode=true. That delta is inert: the review job is read-only, so it is
# never committed, and the exec bit is not load-bearing anyway — entries run as
# `bash <path>`, libs are `source`d, Python deps run as `python3 <path>`.)
#
# TRUST NOTE (mirrors filter-runner-tools.sh): a hand-edit to THIS file changes nothing
# about how the editing PR's own review is hardened — devflow-runner.yml executes this
# helper ONLY from a trusted source (a base-ref materialized copy, or the vendored copy
# gated on vendor_source=fetch), never from the PR-head checkout. The edit takes effect
# only after it lands on the base branch.
#
# Why a helper rather than an inline loop in the workflow YAML: the installer IS a
# security boundary, so a regression (a target dropped from the closure, the fail-closed
# arm installing the PR-head copy instead of a stub, an entry left un-neutralized when a
# sourced dep is missing) must fail the suite. Inline shell in YAML cannot be unit-tested;
# here lib/test/run.sh drives the full adversarial matrix directly. The workflow fails
# closed (inline no-op stubs for every target) when it cannot resolve a trusted copy of
# this helper OR when this helper exits non-zero (see the exit contract below).
#
# I/O contract:
#   input  : env WORKSPACE_ROOT (repo root of the PR-head checkout to harden; default '.')
#            env TRUSTED_DIR     (dir holding base-ref copies at the same relative subpaths,
#                                 e.g. $TRUSTED_DIR/lib/implement-stop-guard.sh; may be empty
#                                 or absent — then EVERY target is stubbed, fail-closed).
#   effect : each closure target under WORKSPACE_ROOT is replaced by its trusted copy when
#            present in TRUSTED_DIR, else by a no-op `exit 0` stub (chmod +x best-effort);
#            when a SOURCED library has no trusted copy, every ENTRY is additionally
#            neutralized to a stub so the missing library is never sourced.
#   stderr : one breadcrumb line per target naming the source used (trusted | stub |
#            neutralized entry).
#   exit   : 0 when EVERY target was displaced (trusted copy or stub) — best-effort: a
#            missing trusted copy is a stub, not a failure, and the review is never
#            aborted. NON-ZERO (1) only when a target could be neither trusted-copied
#            NOR stubbed (a wholly unwritable path, so the PR-head copy MAY REMAIN) —
#            this is the one fail-OPEN outcome, so a non-zero exit signals the workflow
#            to run its inline fail-closed stub arm (never a silent partial displacement).
#            The workflow's inline stub arm and the base-ref materialization make the
#            wholly-unwritable case unreachable in practice.
#
# HOOK_TARGETS is the authoritative single-line mirror of the full transitive closure
# (COUPLED — mirror in devflow-runner.yml's inline TARGETS= and pinned both ways in
# lib/test/run.sh; the run.sh drift-guard also asserts it covers every source/exec edge).

set -u

# ── The full transitive source/exec closure (repo-relative). ─────────────────────
# Entry hooks — the .claude/settings.json Stop-hook script paths plus, since #805, the
# PreToolUse guard. A stub here is SAFE (skipping the hook is safe). COUPLED mirror of
# devflow-runner.yml's inline ENTRY_TARGETS fallback (pinned equal in lib/test/run.sh).
HOOK_ENTRY_TARGETS='lib/efficiency-trace.sh lib/implement-stop-guard.sh scripts/stop-hook-probe.sh scripts/pretooluse-shape-guard.py'
# Libraries SOURCED INLINE (`.`/`source`) into an entry, directly or transitively. A
# stub here would exit the SOURCING entry mid-run, so a MISSING trusted copy of one of
# these neutralizes every entry instead of installing a mid-source-breaking stub.
HOOK_SOURCED_TARGETS='lib/resolve-jq.sh lib/config-source.sh lib/resolve-bin.sh lib/telemetry-branch.sh lib/resolve-state-dir.sh'
# Dependencies EXEC'd as a subprocess (command-substitution / `python3 <path>`). A stub
# here just makes the subprocess a no-op and the entry degrades gracefully, so a missing
# trusted copy needs no entry neutralization. This is the documentary/pinned mirror of
# the exec-dep class (the logic derives "exec dep" as any closure member that is neither
# an entry nor a sourced lib), so it is not read by the code below.
# shellcheck disable=SC2034
HOOK_EXEC_TARGETS='scripts/config-get.sh scripts/config_fingerprint.py scripts/workpad.py scripts/check-completion-evidence.py scripts/reception_identity.py lib/test/extract-command-shapes.py lib/test/extract-command-heads.py'
# Authoritative single-line closure literal (COUPLED mirror of devflow-runner.yml's
# inline TARGETS= — pinned in lib/test/run.sh). Order: entries, then sourced libs, then
# exec deps.
HOOK_TARGETS='lib/efficiency-trace.sh lib/implement-stop-guard.sh scripts/stop-hook-probe.sh scripts/pretooluse-shape-guard.py lib/resolve-jq.sh lib/config-source.sh lib/resolve-bin.sh lib/telemetry-branch.sh lib/resolve-state-dir.sh scripts/config-get.sh scripts/config_fingerprint.py scripts/workpad.py scripts/check-completion-evidence.py scripts/reception_identity.py lib/test/extract-command-shapes.py lib/test/extract-command-heads.py'

WORKSPACE_ROOT="${WORKSPACE_ROOT:-.}"
TRUSTED_DIR="${TRUSTED_DIR:-}"

# ── --wired-check MODE (issue #460 review): the relevance-gate decision, as a
# TESTABLE single source of truth (the devflow-runner.yml harden step calls THIS from
# the trusted-materialized helper instead of a hand-copied inline `case`, so the branch
# selection is driven by lib/test/run.sh — the repo's "extract branch-selecting inline
# workflow shell into a helper" convention). Given the TRUSTED base .claude/settings.json
# on stdin or as $2, decide whether it wires any HOOK_ENTRY_TARGETS entry hook (the
# Stop-hook entries and, since #805, the PreToolUse guard).
#   usage : harden-stop-hooks.sh --wired-check [<settings-file>]   (stdin if no file)
#   exit  : 0 = wired (at least one entry hook referenced) — HARDEN
#           1 = a CLEAN "not wired" verdict (or the file is unreadable/absent) — nothing
#               to harden. The caller treats ONLY rc 0/1 as verdicts; any rc >= 2 (a helper
#               execution error) is NOT read as "not wired" — the caller falls back to its
#               inline scan (fail-closed) rather than skipping and dropping the floor.
# Fail direction: an unreadable/absent settings file reads as NOT wired (exit 1). This
# is a pure predicate over the text it is GIVEN — it deliberately does NOT distinguish
# "empty because the file is absent" from "empty because a read failed"; that ambiguity
# is resolved by the CALLER (issue #460 SHADOW): devflow-runner.yml only invokes this
# with a NON-EMPTY settings blob (it handles an empty read separately via `git cat-file
# -e` — a present-but-unreadable settings.json fails CLOSED toward hardening so PRFlow's
# own floor is never dropped, an absent one skips), and it keeps a transient base-ref
# FETCH FAILURE on its own fail-closed path. A substring match (not a JSON parse) is
# deliberate: the entry paths appear verbatim in the hook command strings, and a
# non-preflight JSON tool must not decide this SELECTION (guard-class 2).
if [ "${1:-}" = "--wired-check" ]; then
  _wc_settings=""
  if [ -n "${2:-}" ]; then
    [ -r "$2" ] && _wc_settings="$(cat "$2" 2>/dev/null)"
  else
    _wc_settings="$(cat 2>/dev/null)"
  fi
  for _wc_e in $HOOK_ENTRY_TARGETS; do
    case "$_wc_settings" in
      *"$_wc_e"*) exit 0 ;;
    esac
  done
  exit 1
fi

# Fail-closed no-op stub: a Stop hook that does nothing rather than the PR-head copy.
STUB=$'#!/usr/bin/env bash\n# Installed by scripts/harden-stop-hooks.sh (#458): no trusted base copy of this\n# Stop-hook target was available, so it is neutralized rather than run from the\n# PR-head checkout. Fail-closed: run no hook, never a PR-controlled one.\nexit 0'

# Language-appropriate stub for a .py target (issue #805). The PreToolUse guard is the
# first Python ENTRY hook; writing the bash STUB above into a file the harness runs as a
# Python hook raises SyntaxError on `exit 0`, failing the hook on every call instead of
# the intended benign no-op. This Python stub therefore does in Python exactly what the
# bash STUB does in bash: print NOTHING and exit 0 — the documented no-decision shape, so
# the stubbed hook reports no decision and the normal permission flow proceeds untouched.
# It used to print a `permissionDecision: "defer"` object instead, on the belief that the
# token was the fall-through; run 30967680822's `defer-probe` measured that token BLOCKING
# the tool and ending the process (DEFER-BLOCKED / STOP-REASON-DEFERRED), which would have
# made this "benign" stub terminate the very run it is meant to leave alone. The __main__
# guard is DEFENSIVE, not a description of any current routing: `write_stub` below installs
# STUB_PY for a .py ENTRY target only, and every .py EXEC dep keeps the bash STUB, so no
# file the closure imports can carry STUB_PY today. It keeps the stub inert should a future
# .py entry target also be imported — without it a top-level `sys.exit(0)` would raise
# SystemExit into the importer.
STUB_PY=$'#!/usr/bin/env python3\n# Installed by scripts/harden-stop-hooks.sh (#458/#805): no trusted base copy of this\n# Python hook target was available, so it is neutralized rather than run from the PR-head\n# checkout. Fail-closed: report NO decision (print nothing) and exit 0, never a\n# PR-controlled body.\nimport sys\nif __name__ == "__main__":\n    sys.exit(0)'

# Membership tests — pure bash (a SELECTION-deciding value must not route through a
# non-preflight PATH tool: the repo's guard-class 2).
_is_entry_target()   { case " $HOOK_ENTRY_TARGETS "   in *" $1 "*) return 0 ;; esac; return 1; }
_is_sourced_target() { case " $HOOK_SOURCED_TARGETS " in *" $1 "*) return 0 ;; esac; return 1; }

# Try to install the trusted base copy of $1 into the workspace.
#   returns 0 — trusted copy installed (PR-head displaced)
#   returns 1 — no trusted copy available, or the copy failed (caller must stub)
try_install_trusted() {
  local t="$1" dest destdir src
  dest="$WORKSPACE_ROOT/$t"
  destdir="${dest%/*}"
  src="$TRUSTED_DIR/$t"
  # A dest that is a DIRECTORY must not be treated as installable: `cp file dir/`
  # copies INTO it and exits 0, so the target path is NOT displaced yet the copy
  # reports success. Return 1 so the caller falls through to write_stub, whose
  # `printf > "$dest"` fails on a directory → displacement_failed → fail-closed exit.
  if [ -d "$dest" ]; then
    printf 'devflow: harden-stop-hooks: %s — dest is a directory, not a file; cannot displace it — falling through to the fail-closed arm\n' "$t" >&2
    return 1
  fi
  # A SYMLINK dest must be REMOVED, not followed (issue #460 review): `cp`/`> ` write
  # through the link into its resolved target, leaving the PR-head symlink in place (so
  # "displace the target path" would be untrue) and — for an absolute link target —
  # writing script bytes to an arbitrary path outside the workspace. Unlink it first so a
  # real file is written AT the path.
  [ -L "$dest" ] && rm -f "$dest" 2>/dev/null
  if [ -n "$TRUSTED_DIR" ] && [ -f "$src" ]; then
    if mkdir -p "$destdir" 2>/dev/null && cp "$src" "$dest" 2>/dev/null; then
      chmod +x "$dest" 2>/dev/null || true
      printf 'devflow: harden-stop-hooks: %s <- trusted base copy\n' "$t" >&2
      return 0
    fi
    printf 'devflow: harden-stop-hooks: %s — trusted copy exists but could not be installed; installing fail-closed stub instead\n' "$t" >&2
  fi
  return 1
}

# Overwrite $1 with the fail-closed no-op stub (displacing any PR-head copy).
#   returns 0 — stub written (PR-head copy displaced)
#   returns 1 — could NOT write (wholly unwritable path; PR-head copy MAY REMAIN)
write_stub() {
  local t="$1" dest destdir label="${2:-fail-closed no-op stub (no trusted base copy)}"
  dest="$WORKSPACE_ROOT/$t"
  destdir="${dest%/*}"
  # Unlink a symlink dest first (issue #460 review) so the stub is written AT the path,
  # not through the link into its resolved target.
  [ -L "$dest" ] && rm -f "$dest" 2>/dev/null
  # Language-appropriate stub (issue #805): a .py ENTRY hook gets the Python stub (a bash
  # `exit 0` in a file the harness runs as a Python hook raises SyntaxError on `exit 0`).
  # A .py EXEC dep (workpad.py, config_fingerprint.py, extract-command-*.py) keeps the bash
  # STUB — it runs in a SUBPROCESS (`python3 <path>`) or is imported, so a bash stub just
  # makes it a no-op/import-error and the caller degrades (the guard fails open to a
  # no-decision: exit 0, empty stdout),
  # the established exec-dep behavior. Pure suffix + membership `case`/`if` — no PATH tool
  # decides this SELECTION (guard-class 2).
  local _stub
  case "$t" in
    *.py) if _is_entry_target "$t"; then _stub="$STUB_PY"; else _stub="$STUB"; fi ;;
    *)    _stub="$STUB" ;;
  esac
  if mkdir -p "$destdir" 2>/dev/null && printf '%s\n' "$_stub" > "$dest" 2>/dev/null; then
    chmod +x "$dest" 2>/dev/null || true
    printf 'devflow: harden-stop-hooks: %s <- %s\n' "$t" "$label" >&2
    return 0
  fi
  printf 'devflow: harden-stop-hooks: %s — could NOT write a stub (unwritable path); the PR-head copy may remain — inspect the runner\n' "$t" >&2
  return 1
}

neutralize_entries=0    # set when a SOURCED library lacked a trusted copy
displacement_failed=0   # set when any target could be neither trusted-copied nor stubbed

# ── Pass 1: non-entry dependencies (sourced libs + exec'd deps). ─────────────────
# Done first so `neutralize_entries` is fully decided before the entries are processed.
for t in $HOOK_TARGETS; do
  _is_entry_target "$t" && continue   # entries handled in Pass 2
  if try_install_trusted "$t"; then
    continue
  fi
  # No trusted copy of this dependency is available. If it is a SOURCED library, a base
  # ENTRY that sources it mid-run must be neutralized — and that decision is made HERE,
  # BEFORE the stub write is attempted, INDEPENDENT of whether the stub write then
  # succeeds. Otherwise a sourced-lib whose own stub write FAILS (unwritable dest, so the
  # PR-head copy MAY REMAIN) would leave `neutralize_entries` unset, and Pass 2 could
  # install a trusted ENTRY that then sources the surviving PR-head library. (Nets out
  # safe today because a failed stub also sets `displacement_failed` → exit 1 → the
  # workflow's fail-closed arm, but the helper itself must be correct in isolation.)
  _is_sourced_target "$t" && neutralize_entries=1
  write_stub "$t" || displacement_failed=1
done

# ── Pass 2: entry hooks. ─────────────────────────────────────────────────────────
for t in $HOOK_TARGETS; do
  _is_entry_target "$t" || continue   # deps handled in Pass 1
  if [ "$neutralize_entries" = 1 ]; then
    # A sourced dependency could not be trusted-restored, so run NO hook rather than a
    # base entry that would source a stubbed (or absent) library mid-run.
    write_stub "$t" "fail-closed no-op stub (a sourced dependency had no trusted base copy — neutralizing the entry)" || displacement_failed=1
    continue
  fi
  try_install_trusted "$t" && continue
  write_stub "$t" || displacement_failed=1
done

if [ "$displacement_failed" = 1 ]; then
  printf 'devflow: harden-stop-hooks: one or more Stop-hook targets could be neither trusted-copied NOR stubbed (a wholly unwritable path); the PR-head copy MAY REMAIN — exiting non-zero so the workflow fail-closed inline stub arm runs\n' >&2
  exit 1
fi

exit 0

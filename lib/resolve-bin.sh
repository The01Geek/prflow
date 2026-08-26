#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-bin.sh — the SINGLE source of truth for PRFlow's generic
# execution-verified external-binary selection contract, extracted from
# lib/resolve-gh.sh (issue #247) so any tool can share it. lib/resolve-gh.sh
# now delegates to `devflow_resolve_bin gh` (DEVFLOW_GH is exactly the override
# name this helper derives for "gh", so delegation preserves the DEVFLOW_GH
# override contract and the test suite's stubbing semantics unchanged). `jq` is
# the second consumer (DEVFLOW_JQ). `git` is deliberately NOT routed through
# this helper in issue #247 — its Windows binary is robust — but adding it
# later is a call site's one-line `devflow_resolve_bin git`, no new logic.
#
# On Windows (WSL-bash / Git Bash) PATH can place a non-executable shim ahead
# of the real tool — for example a Python-provided script carrying a Windows
# shebang, which fails with "cannot execute: required file not found." A tool
# selected by name alone (`command -v`) then resolves to that shim and every
# call site breaks, even though a working `<tool>.exe` is present later on
# PATH. Presence is not runnability; this helper centralizes the "which binary
# do we use?" decision so preflight (which DETECTS) and every helper (which
# USES) can never disagree on the contract.
#
# Defines a function only; it deliberately does NOT set -e/-u so it is safe to
# source into a caller with its own shell options (preflight runs `set -u`, the
# helpers run `set -euo pipefail` / `set -uo pipefail`, and sourced-only
# scripts set no options at all).

# Idempotence guard: this file is sourced more than once per process —
# lib/preflight.sh directly plus transitively, and the jq+gh helpers twice
# transitively (via resolve-jq.sh and resolve-gh.sh) — skip the re-parse. The
# if-form (not `[ … ] && return`) is kept so the guard can never become the
# file's final failing AND-list statement if lines are later reordered.
if [ -n "${_DEVFLOW_RESOLVE_BIN_SOURCED:-}" ]; then return 0; fi
_DEVFLOW_RESOLVE_BIN_SOURCED=1

# devflow_resolve_bin <tool> — echo the invocation PRFlow should use for <tool>.
#
#   * An explicit, non-empty DEVFLOW_<TOOL-UPPER> (e.g. DEVFLOW_JQ for "jq")
#     wins outright and is echoed WITHOUT any probe — this preserves the test
#     suite's stubbing contract (a stubbed run sets the override to a fake
#     binary, which must never be version-checked) and gives a Windows/WSL user
#     a documented escape hatch.
#   * Otherwise the first of `<tool>`, `<tool>.exe` that both resolves
#     (`command -v`) AND actually executes (`<tool> --version`) is echoed — so
#     a present-but-unrunnable shim is rejected in favor of a runnable
#     `<tool>.exe`. The probe is `--version` only: no network, no
#     authentication, so it cannot hang or fail on an unauthenticated host.
#   * If neither candidate runs, the bare `<tool>` is echoed (with a one-line
#     stderr breadcrumb naming the probe failure and the DEVFLOW_<TOOL-UPPER>
#     remedy) so the caller's existing best-effort error path still fires,
#     unchanged.
#
# On Linux/macOS/cloud, where the bare tool runs, the first probe succeeds and
# the function returns the bare name — no behavior change and no extra
# network/auth. Candidate binaries are referenced by name only; no absolute or
# owner-specific install path is ever hardcoded. Always returns rc 0 (the
# caller wants the string).
devflow_resolve_bin() {
  local tool="$1" var_name override cand
  # The override path must stay PURE BASH for the known tools: deriving the
  # variable name through `tr` means a degenerate PATH without tr silently
  # bypasses DEVFLOW_<TOOL> — probing (or even executing) the very stub the
  # override contract promises never to touch. Map the known consumers
  # directly; the generic tr arm remains for future tools (git would take it),
  # failing CLOSED with a breadcrumb when tr is unavailable rather than
  # reading a mangled `DEVFLOW_` variable.
  case "$tool" in
    jq) var_name=DEVFLOW_JQ ;;
    gh) var_name=DEVFLOW_GH ;;
    *)
      # tr (not ${var^^}) keeps this bash-3.2-compatible for stock macOS bash.
      # `|| var_name="DEVFLOW_"` keeps this sourceable under a set -e caller: a
      # tr-less pipeline's non-zero status would otherwise abort before the
      # fail-closed guard below; the fallback routes straight into it.
      var_name="DEVFLOW_$(printf '%s' "$tool" | tr '[:lower:]-' '[:upper:]_' 2>/dev/null)" || var_name="DEVFLOW_"
      if [ "$var_name" = "DEVFLOW_" ]; then
        printf 'devflow: could not derive the override variable name for "%s" (tr unavailable?) — override not consulted, probing candidates\n' "$tool" >&2
        var_name=__DEVFLOW_NO_OVERRIDE__
      fi
      ;;
  esac
  override="${!var_name:-}"
  # Explicit override wins with no probe (stub contract + Windows escape hatch).
  if [ -n "$override" ]; then
    printf '%s\n' "$override"
    return 0
  fi
  for cand in "$tool" "$tool.exe"; do
    command -v "$cand" >/dev/null 2>&1 || continue
    # Confirm the candidate actually EXECUTES — a present-but-unrunnable shim
    # (bad shebang, cleared exec bit) must not be trusted by name. `--version`
    # is deliberately network- and auth-free.
    "$cand" --version >/dev/null 2>&1 || continue
    printf '%s\n' "$cand"
    return 0
  done
  # No runnable candidate: fall back to the bare tool so the caller's
  # best-effort error path still fires (unchanged degenerate behavior). Leave a
  # stderr breadcrumb so the downstream "cannot execute" failure is
  # self-explanatory (stderr only — command substitution captures stdout, so
  # the echoed value stays clean).
  # Name the override the USER would set — never the internal no-override
  # sentinel the tr-unavailable arm parks in var_name.
  local _display="$var_name"
  if [ "$_display" = "__DEVFLOW_NO_OVERRIDE__" ]; then _display="the DEVFLOW_<TOOL> override for $tool"; fi
  printf 'devflow: no runnable %s or %s.exe found on PATH; falling back to bare "%s" — set %s to a working binary\n' \
    "$tool" "$tool" "$tool" "$_display" >&2
  printf '%s\n' "$tool"
  return 0
}

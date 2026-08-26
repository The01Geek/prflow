#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-python.sh — the SINGLE source of truth for PRFlow's Python-interpreter
# selection contract, sourced by lib/preflight.sh and scripts/provision-python3-shim.sh.
#
# On a stock Windows Python install (python.org / `winget install python`) there is no
# `python3` on PATH — Python is reachable only as `python` and/or the `py -3` launcher.
# PRFlow's shell helpers, the agent-typed `python3 <path>` convention, and the cloud
# `Bash(python3:*)` allowlist all invoke the literal `python3`, so a host with a perfectly
# good Python 3.11 is otherwise reported unsupported. This helper centralizes the
# "which interpreter do we use?" decision so preflight (which only DETECTS) and the
# provisioner (which writes a shim) can never disagree on the contract.
#
# Defines functions only; it deliberately does NOT set -e/-u so it is safe to source into
# a caller with its own shell options (preflight runs `set -u`, the provisioner `set -euo
# pipefail`).

# devflow_resolve_python — echo the interpreter invocation PRFlow should use, picking the
# FIRST of `python3`, `py -3`, `python` whose interpreter actually runs AND reports
# sys.version_info >= (3, 11). A bare `python` is never trusted by name — it is version-
# checked, so a Python-2 `python` is rejected in favor of a later `py -3`/`python3`.
#
# Output + return code:
#   rc 0  echoes the chosen invocation (one of: "python3", "py -3", "python") — a >=3.11
#         interpreter was found.
#   rc 1  echoes the FIRST runnable invocation found — a Python exists but every candidate
#         is older than 3.11 (lets the caller report its version in the failure message).
#   rc 3  echoes nothing — no candidate interpreter runs at all.
# (rc 2 is intentionally unused here so it stays reserved for the provisioner's user-facing
# exit-2 refusal codes — the provisioner captures this function's rc and must not confuse a
# resolver result with its own exit-2 semantics.)
devflow_resolve_python() {
  local first_runnable="" spec
  for spec in "python3" "py -3" "python"; do
    # Intentional word-split: "py -3" must become the command `py` with arg `-3`.
    # shellcheck disable=SC2086
    set -- $spec
    command -v "$1" >/dev/null 2>&1 || continue
    # Confirm the candidate actually EXECUTES (a present `py` with no 3.x installed, or a
    # broken `python`, must not be mistaken for a runnable interpreter) before classifying.
    "$@" -c 'pass' >/dev/null 2>&1 || continue
    [ -n "$first_runnable" ] || first_runnable="$spec"
    if "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$spec"
      return 0
    fi
  done
  if [ -n "$first_runnable" ]; then
    printf '%s\n' "$first_runnable"
    return 1
  fi
  return 3
}

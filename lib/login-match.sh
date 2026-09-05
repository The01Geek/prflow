#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# login-match.sh — shared login-comparison entry point for the shell comparators
# (scripts/authorize-actor.sh, scripts/post-ci-review-trigger.sh, lib/scan.sh).
# Source it, then call one of the functions below. Both delegate the WHOLE
# normalization rule to lib/login_normalize.py — the single source of the rule —
# through the interpreter lib/resolve-python.sh selects, so no shell site
# re-implements [bot]/app/ stripping. On any failure the caller writes its own one
# stderr breadcrumb naming lib/login_normalize.py and takes its existing
# fail-closed arm.
#
# Defines functions only; sets no shell options so it is safe to source into a
# caller managing its own error mode (authorize-actor.sh none, scan.sh set -euo,
# post-ci-review-trigger.sh set -uo).
#
# devflow_login_matches <login> <comma-separated-comparands>
#   rc 0  normalized login equals a normalized non-empty comparand
#   rc 1  no match (a plain, non-error negative — no breadcrumb owed)
#   rc 2  the comparison could not run (no >=3.11 interpreter, or the CLI errored)
# devflow_login_normalize <login>   (echoes the normalized login on stdout)
#   rc 0  printed the normalized login
#   rc 2  could not run

_DEVFLOW_LM_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
# shellcheck source=resolve-python.sh
. "$_DEVFLOW_LM_DIR/resolve-python.sh" 2>/dev/null || true
_DEVFLOW_LOGIN_NORMALIZE="$_DEVFLOW_LM_DIR/login_normalize.py"

# Echo the >=3.11 interpreter spec resolve-python.sh selects, or return non-zero so
# the caller fails closed. A resolver rc of 1 (only a <3.11 interpreter) or 3 (none)
# both fail closed here — login_normalize.py's callers require a supported Python.
_devflow_login_py() {
  type devflow_resolve_python >/dev/null 2>&1 || return 1
  local spec
  spec="$(devflow_resolve_python)" || return 1
  printf '%s' "$spec"
}

devflow_login_matches() {
  local login="$1" comparands="$2" spec rc
  spec="$(_devflow_login_py)" || return 2
  # Intentional word-split of the spec ("py -3" -> py + -3). The `&& || _rc` idiom
  # keeps a non-match (rc 1) from aborting a `set -e` caller.
  # shellcheck disable=SC2086
  $spec "$_DEVFLOW_LOGIN_NORMALIZE" matches "$login" "$comparands" && rc=0 || rc=$?
  case "$rc" in
    0|1) return "$rc" ;;
    *)   return 2 ;;
  esac
}

devflow_login_normalize() {
  local login="$1" spec out rc
  spec="$(_devflow_login_py)" || return 2
  # shellcheck disable=SC2086
  out="$($spec "$_DEVFLOW_LOGIN_NORMALIZE" normalize "$login")" && rc=0 || rc=$?
  [ "$rc" -eq 0 ] || return 2
  printf '%s' "$out"
}

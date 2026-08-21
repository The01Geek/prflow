#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# refresher-sign.sh — the single shared openssl-free JWT-signing call for the
# credential refresher's mint (scripts/refresh-app-credentials.sh) and its
# pre-launch self-test (scripts/refresher-selftest.sh), issue #1882. Both invoke
# the standard-library signer the same way — the PEM key on stdin (never argv,
# never disk), the interpreter spec word-split into an array, and the signer's
# own diagnostic captured and bounded — so that key-free capture lives in ONE
# place rather than drifting between the mint and the check that certifies it.
# Each caller keeps its own interpreter resolution and rc->diagnostic mapping,
# because their failure semantics differ (the mint warns and retains the
# credential; the self-test fails the job).
#
# Defines a function only; it deliberately does NOT set -e/-u so it is safe to
# source into a caller with its own shell options.

# devflow_sign_jwt SIGNER SPEC ARG... — sign with the PEM key from the global
# $KEY on stdin. SPEC may be two words (e.g. `py -3`), so it is word-split into
# the interpreter array here. On return DEVFLOW_SIGN_STDOUT holds the signer's
# stdout (the finished JWT on success) and DEVFLOW_SIGN_STDERR its first three
# lines with newlines flattened to spaces (key-free by the signer's contract; a
# missing `head` degrades the DETAIL to empty, never a key leak); the function
# returns the signer's own exit code.
devflow_sign_jwt() {
  local signer="$1" spec="$2"; shift 2
  # Intentional word-split of the (possibly two-word, e.g. `py -3`) interpreter spec.
  # shellcheck disable=SC2206
  local -a _sign_py=($spec)
  local _sign_errf _sign_rc
  # DEVFLOW_SIGN_STDOUT/STDERR are the function's out-params, read by the caller.
  # shellcheck disable=SC2034
  DEVFLOW_SIGN_STDOUT=""
  # shellcheck disable=SC2034
  DEVFLOW_SIGN_STDERR=""
  _sign_errf="$(mktemp 2>/dev/null || true)"
  if [ -n "$_sign_errf" ]; then
    DEVFLOW_SIGN_STDOUT="$(printf '%s' "$KEY" | "${_sign_py[@]}" "$signer" "$@" 2>"$_sign_errf")"; _sign_rc=$?
    DEVFLOW_SIGN_STDERR="$(head -n 3 "$_sign_errf" 2>/dev/null || true)"
    DEVFLOW_SIGN_STDERR="${DEVFLOW_SIGN_STDERR//$'\n'/ }"       # flatten to one line (bash builtin, no tr)
    rm -f "$_sign_errf" 2>/dev/null || true
  else
    # shellcheck disable=SC2034
    DEVFLOW_SIGN_STDOUT="$(printf '%s' "$KEY" | "${_sign_py[@]}" "$signer" "$@" 2>/dev/null)"; _sign_rc=$?
  fi
  return "$_sign_rc"
}

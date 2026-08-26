#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-jq.sh — PRFlow's jq selection contract, sourced by every jq-calling
# shell helper (the direct sibling of lib/resolve-gh.sh, issue #247). Sourcing
# this file resolves jq ONCE through the shared execution-verified resolver
# (lib/resolve-bin.sh) and leaves the invocation in DEVFLOW_JQ: an explicit
# non-empty DEVFLOW_JQ still wins untouched (test stubs and the Windows escape
# hatch are honored — `:=` assigns only when unset or empty), otherwise the
# first of jq, jq.exe whose `jq --version` actually runs is selected, else
# bare `jq` with a stderr breadcrumb. See lib/resolve-bin.sh for the full
# contract.
#
# Defines/assigns only; deliberately no set -e/-u — safe to source into a
# caller with its own shell options.

# Pure-bash directory derivation (no `dirname`): stays sourceable in a
# degenerate environment (same discipline as lib/resolve-gh.sh).
case "${BASH_SOURCE[0]}" in
  */*) _RESOLVE_JQ_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _RESOLVE_JQ_DIR="$(pwd)" ;;
esac
# Guarded source: a partially-copied deployment can carry this file without its
# sibling resolve-bin.sh. An unguarded source would leave DEVFLOW_JQ assigned
# EMPTY (the failed command substitution under the caller's `|| fallback`
# AND-OR list), turning every call site's "$DEVFLOW_JQ" into a baffling ''
# command-not-found — so fall back to bare `jq` with a breadcrumb instead.
# shellcheck source=resolve-bin.sh
if [ -f "$_RESOLVE_JQ_DIR/resolve-bin.sh" ] \
   && . "$_RESOLVE_JQ_DIR/resolve-bin.sh" \
   && type devflow_resolve_bin >/dev/null 2>&1; then
  # Verified the OUTCOME (function defined), not just the precondition: an
  # unreadable or corrupt sibling must take the fallback arm, never leave
  # DEVFLOW_JQ assigned empty.
  : "${DEVFLOW_JQ:=$(devflow_resolve_bin jq)}"
else
  echo "devflow: resolve-bin.sh not found or not sourceable beside resolve-jq.sh — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  : "${DEVFLOW_JQ:=jq}"
fi

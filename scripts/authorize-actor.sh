#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Shared actor-authorization gate for AGENT-mode PRFlow workflows
# (resolve-implement-trigger.sh, resolve-command-trigger.sh). AGENT mode runs
# claude-code-action for ANY actor, so callers MUST gate on this before the
# billable run. Source it, then call `authorize_actor`; it sets two variables
# in the caller's scope:
#   authorized   "true" | "false"
#   deny_reason  human-readable reason when not authorized
#
# Inputs (env, same contract as the resolvers):
#   ACTOR, ALLOWED_BOTS, REPO, GH_TOKEN  (+ optional RESOLVE_RETRY_DELAY)
#   ALLOWED_USERS  comma-separated human logins allowed to trigger PRFlow
#                  workflows (in addition to the write/admin/maintain check).
#                  '*' (default when empty/unset) allows any collaborator.
#                  Bots in ALLOWED_BOTS bypass this filter entirely.
#
# No `set -e` here — the function is sourced into scripts that manage their own
# error mode, and the collaborator loop deliberately tolerates non-zero gh exits.

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

authorize_actor() {
  local actor="${ACTOR:-}" allowed_bots="${ALLOWED_BOTS:-}" repo="${REPO:-}"
  # Empty/unset → wildcard, preserving "any collaborator" behavior for repos
  # (and tests) that never set allowed_users.
  local allowed_users="${ALLOWED_USERS:-}"
  [ -z "$allowed_users" ] && allowed_users="*"
  # shellcheck disable=SC2034  # authorized/deny_reason are set for the caller's scope
  authorized=false
  # shellcheck disable=SC2034
  deny_reason="is not an allowed bot or write/admin/maintain collaborator"

  local actor_bare="${actor%\[bot\]}"
  local -a bots
  IFS=',' read -ra bots <<< "$allowed_bots"
  local b bt
  for b in "${bots[@]}"; do
    # Trim surrounding whitespace via parameter expansion, NOT `echo | xargs`:
    # xargs does shell word-splitting/quote processing, so a config value
    # containing a quote or backslash could be mangled — or make xargs exit
    # non-zero, which under `set -e` would abort this authorization loop hard
    # instead of failing closed.
    bt="${b#"${b%%[![:space:]]*}"}"   # strip leading whitespace
    bt="${bt%"${bt##*[![:space:]]}"}" # strip trailing whitespace
    if [ -n "$bt" ] && { [ "$bt" = "$actor" ] || [ "$bt" = "$actor_bare" ]; }; then
      authorized=true
    fi
  done

  # User path: must match allowed_users AND hold write/admin/maintain.
  if [ "$authorized" != "true" ] && [ -n "$actor" ] && [ -n "$repo" ]; then
    if _actor_in_allowed_users "$actor" "$allowed_users"; then
      # Distinguish a definitive "not a collaborator" (HTTP 404) from any other
      # lookup failure. The old `2>/dev/null || echo none` collapsed BOTH to
      # "none", so a rate-limit / 5xx / auth / network blip silently denied a
      # genuine write/admin user and mislabelled it a permission problem. Retry
      # once on a non-404 error before failing closed; on failure, surface the
      # actual gh error so the operator can tell a transient blip from a permanent
      # misconfiguration (missing gh, unset GH_TOKEN, 401/403 scope) rather than
      # being told to expect transience.
      local err_file perm last_err attempt
      err_file="$(mktemp)"
      perm=""
      last_err=""
      for attempt in 1 2; do
        if perm="$("$DEVFLOW_GH" api "repos/$repo/collaborators/$actor/permission" \
                     --jq '.permission' 2>"$err_file")"; then
          break
        fi
        if grep -q 'HTTP 404' "$err_file"; then
          perm="none"            # actor is genuinely not a collaborator
          break
        fi
        perm="__lookup_failed__"
        last_err="$(head -n1 "$err_file" 2>/dev/null || true)"
        [ "$attempt" = 1 ] && sleep "${RESOLVE_RETRY_DELAY:-2}"
      done
      rm -f "$err_file"
      case "$perm" in
        admin|write|maintain) authorized=true ;;
        __lookup_failed__)
          # shellcheck disable=SC2034
          deny_reason="collaborator-permission lookup failed after retry; failing closed${last_err:+ (gh: $last_err)}" ;;
      esac
    else
      # shellcheck disable=SC2034
      deny_reason="is not in the configured allowed_users allowlist"
    fi
  fi
}

# Case-insensitive membership test against human logins; '*' anywhere in the
# list = wildcard.  Bots go through the ALLOWED_BOTS loop above and never reach
# this function.
_actor_in_allowed_users() {
  local actor="$1" list="$2" entry e
  local la="${actor,,}"
  local -a entries
  IFS=',' read -ra entries <<< "$list"
  for entry in "${entries[@]}"; do
    e="${entry#"${entry%%[![:space:]]*}"}"
    e="${e%"${e##*[![:space:]]}"}"
    e="${e,,}"
    [ "$e" = "*" ] && return 0
    [ -n "$e" ] && [ "$e" = "$la" ] && return 0
  done
  return 1
}

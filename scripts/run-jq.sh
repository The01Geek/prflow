#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# run-jq.sh — execution-verified jq wrapper for agent-composed jq inside
# SKILL.md bodies (issue #253, the agent-tier sibling of the #247 .sh-helper
# resolver migration). Skill bodies run each jq in a fresh per-Bash-call agent
# shell where DEVFLOW_JQ is neither exported nor persisted, so the .sh-tier
# `: "${DEVFLOW_JQ:=$(devflow_resolve_bin jq)}"`-then-reuse idiom (source once,
# reuse the var across later commands in the SAME process) does not translate:
# nothing carries the resolved value between an agent's separate Bash calls.
# Agents therefore invoke this wrapper BY PATH in place of bare `jq`; it sources
# the shared resolver (sibling lib/resolve-jq.sh, which sets DEVFLOW_JQ) and
# execs the resolved binary, passing stdin, args, and exit code through
# unchanged. On a shim-shadowed Windows/WSL host (a present-but-unrunnable
# jq.exe on PATH) this selects a runnable jq exactly as the .sh helper tier
# does; on Linux/macOS/cloud it is a transparent no-op that execs the bare `jq`
# the resolver's first `--version` probe confirms. Best-effort: it never fails
# closed to an empty invocation — a partial deployment (scripts/ without lib/)
# degrades to bare `jq` with a stderr breadcrumb, no worse than before.
set -uo pipefail

# Pure-bash directory derivation (no `dirname`): survives a degenerate PATH,
# same discipline as the resolver family (lib/resolve-jq.sh / resolve-bin.sh).
case "${BASH_SOURCE[0]}" in
  */*) _RUN_JQ_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _RUN_JQ_DIR="$(pwd)" ;;
esac

# Source the shared jq resolver (which assigns DEVFLOW_JQ). A partially-copied
# deployment can ship scripts/ without its sibling lib/: fall back to bare `jq`
# with a breadcrumb rather than exec an empty string. resolve-jq.sh is itself
# guarded (it degrades to DEVFLOW_JQ=jq if resolve-bin.sh is missing), so once
# it is sourced DEVFLOW_JQ is always non-empty; the `:-jq` is belt-and-braces.
# shellcheck source=../lib/resolve-jq.sh
if [ -f "$_RUN_JQ_DIR/../lib/resolve-jq.sh" ] && . "$_RUN_JQ_DIR/../lib/resolve-jq.sh"; then
  exec "${DEVFLOW_JQ:-jq}" "$@"
fi
echo "prflow: run-jq.sh could not source lib/resolve-jq.sh beside it (partial deployment?) — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
# Even on the partial-deploy fallback, honor a pre-set DEVFLOW_JQ and avoid a
# bare invocation-position `jq` (the #247 DJQ_BARE contract) — `:-jq` degrades
# to bare jq only when the override is unset/empty, matching the breadcrumb.
exec "${DEVFLOW_JQ:-jq}" "$@"

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# spot-interruption-watcher.sh — the EC2 Spot-interruption watcher process
# (issue #261, AC38/AC41/AC42/AC43). Started as a background process in a step
# BEFORE `Run Claude Code`, and stopped/reaped by a step immediately AFTER it.
#
# Loop, each iteration >= --poll-interval seconds apart (AC41: poll no less than
# once every five seconds; each IMDS request uses a 1s connect / 2s total timeout):
#   1. mint an IMDSv2 token (once, the 21600s TTL covers the whole poll window;
#      re-minted on a later poll only if the prior mint returned empty);
#   2. GET spot/instance-action; a 200 whose JSON `action` is stop/terminate/
#      hibernate is a VALID interruption action, a 404 (or any other/malformed
#      response) means no action yet and the loop continues (fail toward watching,
#      never toward a spurious reclaim);
#   3. on the FIRST valid action (single-shot): post the run-scoped reclaim marker,
#      log the action, then terminate the Claude step so the existing always()
#      post-run handlers get the remaining interruption window (AC43), and exit.
# A marker-post failure still proceeds to terminate (AC52: a missing marker makes
# recovery-classify.sh return unclassifiable — the safe fallback — and delaying
# termination past the window is the worse failure).
# On SIGTERM/SIGINT from the reap step with no action ever seen: exit 0 cleanly,
# posting no marker (AC44/AC43: the watcher cannot fire after the Claude boundary).
#
# The IMDSv2 token is never printed to stdout/stderr and never written to a file —
# the "must not expose credentials" gotcha. It is passed to curl as an -H header
# argument (necessarily on curl's own argv, briefly visible in that process's
# /proc/<pid>/cmdline), acceptable on a single-tenant EC2 runner with a short-lived
# metadata token; it is never placed on THIS script's argv or a caller-visible var.
#
# Test seams: IMDS_BASE_URL overrides the metadata endpoint; DEVFLOW_CURL overrides
# the curl binary (deterministic over PATH order, which leaks to a real host's live
# IMDS); WATCHER_TERMINATE_CMD overrides the terminate action (default: SIGTERM the
# claude-code-action process tree); WATCHER_MAX_POLLS bounds the loop for a test.
set -uo pipefail

IMDS_BASE_URL="${IMDS_BASE_URL:-http://169.254.169.254}"
CURL="${DEVFLOW_CURL:-curl}"
# jq via the single-source resolver (preflight-guaranteed); DEVFLOW_JQ still wins.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh"
: "${DEVFLOW_JQ:=$(devflow_resolve_jq)}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PIDFILE=""
ISSUE=""
RUN_ID=""
RUN_ATTEMPT=""
JOB_ID=""
REPO=""
POLL_INTERVAL=5

while [ "$#" -gt 0 ]; do
  case "$1" in
    --pidfile) PIDFILE="${2-}"; shift 2 ;;
    --marker-target-issue) ISSUE="${2-}"; shift 2 ;;
    --run-id) RUN_ID="${2-}"; shift 2 ;;
    --run-attempt) RUN_ATTEMPT="${2-}"; shift 2 ;;
    --job-id) JOB_ID="${2-}"; shift 2 ;;
    --repo) REPO="${2-}"; shift 2 ;;
    --poll-interval) POLL_INTERVAL="${2-}"; shift 2 ;;
    *) echo "spot-interruption-watcher: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

[[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]] || POLL_INTERVAL=5

# Record the PID immediately so the reap step can stop this exact process by the
# identifier we wrote — never by a name/pattern that could match another session.
if [ -n "$PIDFILE" ]; then
  echo "$$" > "$PIDFILE" 2>/dev/null || echo "spot-interruption-watcher: could not write pidfile '$PIDFILE'" >&2
fi

_stopped=""
_on_stop() { _stopped=1; }
trap _on_stop TERM INT

_mint_token() {
  "$CURL" -sS -X PUT "${IMDS_BASE_URL}/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
    --connect-timeout 1 --max-time 2 2>/dev/null
}

TOKEN="$(_mint_token)"

polls=0
while [ -z "$_stopped" ]; do
  if [ -n "${WATCHER_MAX_POLLS:-}" ] && [ "$polls" -ge "${WATCHER_MAX_POLLS}" ]; then
    break
  fi
  polls=$((polls + 1))

  [ -n "$TOKEN" ] || TOKEN="$(_mint_token)"
  body="$("$CURL" -sS "${IMDS_BASE_URL}/latest/meta-data/spot/instance-action" \
    -H "X-aws-ec2-metadata-token: ${TOKEN}" \
    --connect-timeout 1 --max-time 2 2>/dev/null)"
  # Extract .action with the preflight-guaranteed jq; a 404/empty/malformed body
  # yields empty (no action yet), never a false reclaim.
  action="$(printf '%s' "$body" | "$DEVFLOW_JQ" -r '.action // empty' 2>/dev/null || true)"
  case "$action" in
    stop|terminate|hibernate)
      echo "spot-interruption-watcher: EC2 Spot interruption action '${action}' detected for run ${RUN_ID} attempt ${RUN_ATTEMPT}; posting reclaim marker and ending the Claude step"
      if bash "$HERE/post-reclaim-marker.sh" "$ISSUE" "$REPO" "$RUN_ID" "$RUN_ATTEMPT" "$JOB_ID" "$action"; then
        echo "spot-interruption-watcher: reclaim marker posted"
      else
        echo "spot-interruption-watcher: reclaim marker did NOT land — terminating anyway (recovery stays unclassifiable, the safe fallback)" >&2
      fi
      # Terminate the Claude step so the always() handlers get the remaining window.
      if [ -n "${WATCHER_TERMINATE_CMD:-}" ]; then
        eval "${WATCHER_TERMINATE_CMD}" || echo "spot-interruption-watcher: terminate command exited non-zero" >&2
      else
        pkill -TERM -f claude-code-action 2>/dev/null || echo "spot-interruption-watcher: no claude-code-action process to signal" >&2
      fi
      exit 0
      ;;
    *)
      : # no action yet
      ;;
  esac
  # Sleep is interruptible by the trap; a stop during the sleep breaks the loop.
  sleep "$POLL_INTERVAL" || true
done

echo "spot-interruption-watcher: stopped, no interruption observed"
exit 0

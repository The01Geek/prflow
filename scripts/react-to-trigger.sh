#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Add an early-acknowledgement reaction to the comment/issue that fired a
# /devflow:* command, so the requester sees the trigger was picked up well
# before the heavy claude-code-action job spins up.
#
# Called from the `gate` job of devflow.yml and devflow-implement.yml, right
# after the resolver, and ONLY when should_run=true — so unauthorized or
# unparseable triggers get no reaction. The gate is the earliest authorized
# moment (same job, no extra runner spin-up).
#
# BEST-EFFORT: a failed/forbidden reaction must never block the run. By default,
# every failure path warns to stderr and exits 0; the workflow step is additionally
# `continue-on-error: true` as a second guard. Agent-side callers may pass
# `--report-failure` to receive rc 1 after an API failure and record that failure
# durably while still continuing.
#
# Reactions are an issue/comment-only API — a submitted *review*
# (pull_request_review) has no reactions endpoint, so that path is skipped
# silently. See https://docs.github.com/en/rest/reactions.
#
# Inputs (env):
#   EVENT_NAME    github.event_name (issue_comment | pull_request_review_comment
#                 | pull_request_review | …). NOTE: no current PRFlow workflow
#                 emits EVENT_NAME=issues — the `issues:[opened]` trigger was
#                 removed (commands fire on real comments/reviews only). The
#                 `issues` branch below is retained defensively (and unit-tested)
#                 for reuse, but is unreachable from the shipped gates today.
#   REPO          owner/repo, for the `gh api` path.
#   COMMENT_ID    github.event.comment.id — set on the two *comment* events,
#                 empty otherwise.
#   ISSUE_NUMBER  github.event.issue.number — the target on the (currently
#                 unreachable) `issues` event; see EVENT_NAME note above.
#   REACTION      reaction content (default: rocket). One of the GitHub set:
#                 +1 -1 laugh confused heart hooray rocket eyes.
#   GH_TOKEN      token for `gh api`, set by the caller.
#
# No stdout contract (unlike the resolvers): this script's only effect is the
# side-effecting POST. Tests assert the `gh api` endpoint it targets.

set -euo pipefail

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# CLI flag args (preferred for the skill fence's leading-token emission, #484/#490:
# a leading VAR=value env prefix is a denied matcher shape, so the skill fence passes
# the values as CLI args instead). They override the env vars the workflow `env:`
# block sets; the workflow passes no args, so its env-var path is unchanged.
report_failure=false
while [ $# -gt 0 ]; do
  case "$1" in
    --report-failure) report_failure=true; shift ;;
    --repo|--event|--comment|--issue|--reaction)
      if [ $# -lt 2 ] || [ -z "${2-}" ] || [[ "${2-}" == --* ]]; then
        echo "::warning::react: missing value for '$1'; skipping acknowledgement." >&2
        exit 0
      fi
      case "$1" in
        --repo) REPO="$2" ;;
        --event) EVENT_NAME="$2" ;;
        --comment) COMMENT_ID="$2" ;;
        --issue) ISSUE_NUMBER="$2" ;;
        --reaction) REACTION="$2" ;;
      esac
      shift 2
      ;;
    --) shift; break ;;
    *)
      echo "::warning::react: unknown argument '$1'; skipping acknowledgement." >&2
      exit 0
      ;;
  esac
done

reaction="${REACTION:-rocket}"
repo="${REPO:-}"
event="${EVENT_NAME:-}"

# Resolve the reactions endpoint for this event. Comment events react on the
# comment; the `issues` arm (a newly-opened issue reacting on the issue itself)
# is currently unreachable — no shipped workflow emits EVENT_NAME=issues — but is
# kept defensively for reuse; everything else (notably pull_request_review) has
# no reactions API.
case "$event" in
  issue_comment)
    [ -n "${COMMENT_ID:-}" ] || { echo "::warning::react: issue_comment with no comment id; skipping." >&2; exit 0; }
    endpoint="repos/$repo/issues/comments/$COMMENT_ID/reactions"
    ;;
  pull_request_review_comment)
    [ -n "${COMMENT_ID:-}" ] || { echo "::warning::react: review comment with no comment id; skipping." >&2; exit 0; }
    endpoint="repos/$repo/pulls/comments/$COMMENT_ID/reactions"
    ;;
  issues)
    [ -n "${ISSUE_NUMBER:-}" ] || { echo "::warning::react: issues event with no issue number; skipping." >&2; exit 0; }
    endpoint="repos/$repo/issues/$ISSUE_NUMBER/reactions"
    ;;
  *)
    echo "::notice::react: no reactions API for event '$event'; skipping acknowledgement." >&2
    exit 0
    ;;
esac

# `gh api` sends -f fields as a JSON body on POST. Best-effort: a 403/422/network
# failure warns but never fails the gate. Capture stderr so the warning carries
# the actual gh error (e.g. "HTTP 403: Resource not accessible by integration"
# when the token lacks issues/pull-requests write) — without it a permissions
# misconfig is indistinguishable from transient flakiness.
if err="$("$DEVFLOW_GH" api -X POST "$endpoint" -f "content=$reaction" 2>&1 >/dev/null)"; then
  echo "::notice::react: added :$reaction: to $endpoint" >&2
else
  # Collapse to one line so the GitHub log annotation stays readable.
  echo "::warning::react: could not add :$reaction: to $endpoint (continuing): ${err//$'\n'/ }" >&2
  if [ "$report_failure" = true ]; then
    exit 1
  fi
fi
exit 0

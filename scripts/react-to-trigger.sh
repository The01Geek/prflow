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
# `--report-failure` to receive rc 1 after a reaction/comment-list API failure or an
# unusable paginated comment response, and record it durably while still continuing.
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
#   REPO          owner/repo, for the `gh api` path. Falls back to GITHUB_REPOSITORY
#                 when unset, so the implement skill's reaction fence need not expand it.
#   COMMENT_ID    github.event.comment.id — set on the two *comment* events,
#                 empty otherwise.
#   ISSUE_NUMBER  github.event.issue.number — the target on the (currently
#                 unreachable) `issues` event; see EVENT_NAME note above.
#   REACTION      reaction content (default: rocket). One of the GitHub set:
#                 +1 -1 laugh confused heart hooray rocket eyes.
#   GH_TOKEN      token for `gh api`, set by the caller.
#   GITHUB_EVENT_PATH  read only on the --outcome path (below): the event JSON whose
#                 .comment.id resolves the triggering comment before the listing fallback.
#
# --outcome complete|blocked (agent-side CLI, issue #176): chooses the reaction itself
# (complete->hooray, blocked->-1) and resolves the triggering comment itself (GITHUB_EVENT_PATH's
# .comment.id, else the newest non-workpad implement-trigger comment on --issue N). Conflicts with
# --reaction. Lets the implement root's fence be one leading-token call with no cloud-denied shape.
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
outcome=""
reaction_given=false
while [ $# -gt 0 ]; do
  case "$1" in
    --report-failure) report_failure=true; shift ;;
    --repo|--event|--comment|--issue|--reaction|--outcome)
      if [ $# -lt 2 ] || [ -z "${2-}" ] || [[ "${2-}" == --* ]]; then
        echo "::warning::react: missing value for '$1'; skipping acknowledgement." >&2
        exit 0
      fi
      case "$1" in
        --repo) REPO="$2" ;;
        --event) EVENT_NAME="$2" ;;
        --comment) COMMENT_ID="$2" ;;
        --issue) ISSUE_NUMBER="$2" ;;
        --reaction) REACTION="$2"; reaction_given=true ;;
        --outcome) outcome="$2" ;;
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

# Fall back to GITHUB_REPOSITORY, read here in this helper's own process: the implement
# skill's outcome-reaction fence cannot pass --repo "$GITHUB_REPOSITORY" because the cloud
# matcher refuses that expansion (issue #40), so removing this fallback would leave that
# fence with no repo. The workflow gate still passes REPO, which wins.
repo="${REPO:-${GITHUB_REPOSITORY:-}}"
# Both-empty (the local/interactive tier: GITHUB_REPOSITORY has no producer there) → gh's
# {owner}/{repo} placeholders, filled from the git remote, so the path never collapses to
# repos//…/reactions (the issue #664 hazard) when the skill fence drops --repo.
[ -n "$repo" ] || repo='{owner}/{repo}'

# --outcome (agent-side, issue #176): choose the reaction AND resolve the triggering comment
# here, so the implement root's fence is one leading-token call with none of the $(…)/VAR=/$VAR
# shapes the cloud matcher refuses. complete→hooray, blocked→-1; --outcome and --reaction conflict.
if [ -n "$outcome" ]; then
  if [ "$reaction_given" = true ]; then
    echo "::warning::react: --outcome cannot be combined with --reaction; skipping acknowledgement." >&2
    exit 0
  fi
  case "$outcome" in
    complete) REACTION=hooray ;;
    blocked)  REACTION=-1 ;;
    *) echo "::warning::react: unknown --outcome '$outcome' (expected complete|blocked); skipping acknowledgement." >&2; exit 0 ;;
  esac
  # jq resolver: sourced here (not top-level) so the hot non-outcome path never pays the probe.
  # shellcheck source=../lib/resolve-jq.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh"
  # Prefer the event file GITHUB_EVENT_PATH names; else list the issue's comments and take the
  # newest non-workpad /prflow:implement (or /devflow:implement) comment. Accept only an all-digits
  # id both ways — a gh error body lands on stdout as a fake capture (issue #664).
  cid=""
  if [ -n "${GITHUB_EVENT_PATH:-}" ] && [ -f "$GITHUB_EVENT_PATH" ]; then
    cid="$("$DEVFLOW_JQ" -r '.comment.id // empty' "$GITHUB_EVENT_PATH" 2>/dev/null || true)"
    [ -n "$cid" ] && [ -z "${cid//[0-9]/}" ] || cid=""
  fi
  if [ -z "$cid" ]; then
    outcome_err_file="$(mktemp 2>/dev/null)" || outcome_err_file=/dev/null
    if ! comments_json="$("$DEVFLOW_GH" api --paginate "repos/$repo/issues/${ISSUE_NUMBER:-}/comments?per_page=100" 2>"$outcome_err_file")"; then
      outcome_err="$(if [ -s "$outcome_err_file" ]; then printf '%s' "$(< "$outcome_err_file")"; else echo 'no error output captured'; fi)"
      [ "$outcome_err_file" = /dev/null ] || rm -f "$outcome_err_file"
      echo "::warning::react: could not list comments for issue '${ISSUE_NUMBER:-}'; skipping outcome acknowledgement: ${outcome_err//$'\n'/ }" >&2
      if [ "$report_failure" = true ]; then
        exit 1
      fi
      exit 0
    fi
    : > "$outcome_err_file"
    if ! cid="$(printf '%s' "$comments_json" | "$DEVFLOW_JQ" -rs \
      'if all(.[]; type == "array") then (add // []) else error("comment page is not an array") end
       | map(select(((.body // "") | test("/(pr|dev)flow:implement")) and (((.body // "") | contains("flow:workpad")) | not))) | last | .id // empty' 2>"$outcome_err_file")"; then
      outcome_err="$(if [ -s "$outcome_err_file" ]; then printf '%s' "$(< "$outcome_err_file")"; else echo 'no error output captured'; fi)"
      [ "$outcome_err_file" = /dev/null ] || rm -f "$outcome_err_file"
      echo "::warning::react: could not parse issue comment pages as arrays for issue '${ISSUE_NUMBER:-}'; skipping outcome acknowledgement: ${outcome_err//$'\n'/ }" >&2
      if [ "$report_failure" = true ]; then
        exit 1
      fi
      exit 0
    fi
    [ "$outcome_err_file" = /dev/null ] || rm -f "$outcome_err_file"
    [ -n "$cid" ] && [ -z "${cid//[0-9]/}" ] || cid=""
  fi
  if [ -z "$cid" ]; then
    echo "::notice::react: no triggering comment resolved for issue '${ISSUE_NUMBER:-}'; skipping outcome acknowledgement." >&2
    exit 0
  fi
  EVENT_NAME=issue_comment
  COMMENT_ID="$cid"
fi

# Resolved after the --outcome block so an outcome-chosen REACTION (hooray/-1) is honored.
reaction="${REACTION:-rocket}"
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

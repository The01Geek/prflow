#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# cancel-superseded-pr-runs.sh — when a pull request is merged or closed while its
# checks are still running, cancel that PR's still-in-flight pull_request CI runs to
# reclaim runner minutes, then leave one PR comment so the resulting `cancelled`
# status is not later misread as a failure.
#
# SOLE IN-REPO CALLER: the cancel-ci-on-merge.yml workflow. Repo-internal:
# install.sh's copy loop ships devflow.yml, devflow-implement.yml and
# devflow-retrospective.yml only (the #1402 never-shipped-workflow lint in
# lib/test/run.sh asserts cancel-ci-on-merge.yml stays uninstalled).
#
# CONTRACT
#   * Cancels exactly the runs that are simultaneously (a) in-progress or queued,
#     (b) event == pull_request, and (c) on the closed PR's head SHA, EXCLUDING
#     this workflow's own run id. The `push`-to-main run the merge produces
#     (event == push) is never cancelled; a run on any other head SHA is never
#     cancelled. Both filters are applied client-side (not left to the API query
#     alone), so the guarantee holds against any list the API returns.
#   * Posts exactly one PR comment when >=1 run was cancelled, wording keyed on
#     whether the PR was merged or closed unmerged. When no run matches it cancels
#     nothing, posts nothing, and exits 0.
#   * Best-effort: always exits 0 (a cleanup job must never redden CI on a transient
#     API failure), with a per-arm annotation naming the condition that fired. The
#     run-list read FAILS CLOSED — an unestablished list cancels nothing: a missed
#     cancellation only wastes runner minutes, while cancelling the wrong runs is
#     unrecoverable.
#   * The decisive set of run ids is derived with jq (a preflight-guaranteed tool)
#     and counted with bash builtins — never tr/sed/wc, whose absence would silently
#     empty the decision (CLAUDE.md's non-preflight-tool rule; the tr below is inside
#     a breadcrumb, where a missing tool only empties a diagnostic).
#   * `{owner}/{repo}` placeholders (gh fills them from the git remote), never an
#     interpolated $GITHUB_REPOSITORY, which would collapse to `repos//…` outside
#     Actions (issue #664; lib/test/lint-gh-api-repo-path.py enforces it).
#
# Inputs (env):
#   PR           the closed pull request's number (required, numeric)
#   HEAD_SHA     the closed PR's head commit (required, lowercase hex 7..40) — the
#                cancellation is scoped to runs on exactly this SHA
#   SELF_RUN_ID  this workflow's own github.run_id, excluded from cancellation
#                (required, numeric) so the job never cancels itself
#   MERGED       `true` when github.event.pull_request.merged, else `false`
#   GH_TOKEN     consumed by gh; the caller sets it to GITHUB_TOKEN (actions: write)
set -uo pipefail

_CSPR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# gh + jq via the single-source execution-verified resolvers (issue #247). A
# non-empty DEVFLOW_GH/DEVFLOW_JQ still wins with no probe, so the suite's stubs are
# untouched. Guarded source so a partial copy degrades with a breadcrumb rather than
# aborting under set -u.
# shellcheck source=../lib/resolve-gh.sh
. "$_CSPR_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi
# shellcheck source=../lib/resolve-jq.sh
. "$_CSPR_DIR/../lib/resolve-jq.sh" \
  || echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
: "${DEVFLOW_JQ:=jq}"

PR="${PR:-}"
HEAD_SHA="${HEAD_SHA:-}"
SELF_RUN_ID="${SELF_RUN_ID:-}"
MERGED="${MERGED:-}"

_note() {  # $1=notice|warning  $2=message
  printf '::%s::%s\n' "$1" "$2"
}

# Validate BEFORE any API call. Each value is interpolated into a REST path or the jq
# program, so a malformed value is refused rather than embedded.
case "$PR" in
  ''|*[!0-9]*)
    _note warning "cancel-superseded-pr-runs: PR number '$PR' is missing or non-numeric; nothing cancelled."
    exit 0 ;;
esac
if ! [[ "$HEAD_SHA" =~ ^[0-9a-f]{7,40}$ ]]; then
  _note warning "cancel-superseded-pr-runs: head SHA '$HEAD_SHA' is missing or not a lowercase hex commit id; nothing cancelled for PR #$PR."
  exit 0
fi
case "$SELF_RUN_ID" in
  ''|*[!0-9]*)
    _note warning "cancel-superseded-pr-runs: SELF_RUN_ID '$SELF_RUN_ID' is missing or non-numeric; refusing to proceed without a self-exclusion id (it would risk cancelling this very run). Nothing cancelled for PR #$PR."
    exit 0 ;;
esac

# --- List the head's pull_request runs (fail closed) ------------------------
# per_page=100 without pagination: a single closed PR head realistically carries a
# handful of pull_request runs, far under one page. Capture gh's stderr so a
# maintainer sees the HTTP cause of a silently-empty cancel.
LIST_ERR="$(mktemp 2>/dev/null || echo /dev/null)"
if ! RUNS_JSON="$("$DEVFLOW_GH" api "repos/{owner}/{repo}/actions/runs?head_sha=$HEAD_SHA&event=pull_request&per_page=100" 2>"$LIST_ERR")"; then
  _note warning "cancel-superseded-pr-runs: could not list workflow runs for $HEAD_SHA ($(tr '\n' ' ' < "$LIST_ERR")); nothing cancelled for PR #$PR (fail-closed — cancelling the wrong runs is unrecoverable, a missed cancellation is not)."
  [ "$LIST_ERR" = /dev/null ] || rm -f "$LIST_ERR"
  exit 0
fi
[ "$LIST_ERR" = /dev/null ] || rm -f "$LIST_ERR"

# Client-side filter (not left to the API query alone): the run is on THIS head SHA,
# its event is pull_request, its status is in-flight, and it is not this run. The
# validated-integer SELF_RUN_ID and the validated-hex HEAD_SHA are the only values
# interpolated into the jq program. jq failure leaves CANCEL_IDS empty under
# pipefail → nothing cancelled (fail-closed).
CANCEL_IDS="$(printf '%s' "$RUNS_JSON" | "$DEVFLOW_JQ" -r \
  '.workflow_runs // []
   | .[]
   | select(.head_sha == "'"$HEAD_SHA"'")
   | select(.event == "pull_request")
   | select(.status == "in_progress" or .status == "queued")
   | select(.id != '"$SELF_RUN_ID"')
   | .id' 2>/dev/null)"

# --- Cancel each, counting with bash builtins -------------------------------
# Keep CANDIDATES (matched) and CANCELLED (actually cancelled) separate: collapsing
# them onto CANCELLED alone makes the all-cancels-failed case falsely report "nothing
# to cancel" instead of the failure it was (all-channels honesty).
CANDIDATES=0
CANCELLED=0
while IFS= read -r _rid; do
  [ -n "$_rid" ] || continue
  case "$_rid" in ''|*[!0-9]*) continue ;; esac
  CANDIDATES=$((CANDIDATES + 1))
  if "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/actions/runs/$_rid/cancel" >/dev/null 2>&1; then
    CANCELLED=$((CANCELLED + 1))
    _note notice "cancel-superseded-pr-runs: cancelled in-flight run $_rid for PR #$PR at $HEAD_SHA."
  else
    _note warning "cancel-superseded-pr-runs: failed to cancel run $_rid for PR #$PR at $HEAD_SHA (continuing)."
  fi
done <<EOF
$CANCEL_IDS
EOF

if [ "$CANDIDATES" -eq 0 ]; then
  _note notice "cancel-superseded-pr-runs: no in-flight pull_request runs for PR #$PR at $HEAD_SHA; nothing to cancel, no comment posted."
  exit 0
fi
if [ "$CANCELLED" -eq 0 ]; then
  _note warning "cancel-superseded-pr-runs: found $CANDIDATES in-flight pull_request run(s) for PR #$PR at $HEAD_SHA but every cancel request failed; no comment posted."
  exit 0
fi

# --- Post one explanation comment, worded from the merged state -------------
# All-channels honesty: name only the state the boolean actually reports. A value
# that is neither true nor false is reported as an indeterminate merged/closed
# state rather than asserted as one.
case "$MERGED" in
  true)  _verb="merged" ;;
  false) _verb="closed without merging" ;;
  *)     _verb="merged or closed" ;;
esac

BODY_FILE="$(mktemp)" || {
  _note warning "cancel-superseded-pr-runs: mktemp failed; cancelled $CANCELLED run(s) but could not compose the explanation comment for PR #$PR."
  exit 0
}
{
  printf 'PRFlow cancelled %s in-flight CI check run(s) for this pull request because it was %s while its checks were still running.\n\n' "$CANCELLED" "$_verb"
  printf 'The resulting `cancelled` status on those runs is expected cleanup to reclaim runner minutes — it is not a test failure.\n'
} > "$BODY_FILE"

# Post through the shared best-effort poster (as post-ci-review-trigger.sh does): it
# owns the REST issues/{n}/comments call with {owner}/{repo} placeholders and always
# exits 0, so gate the success breadcrumb on its stdout signal, not its exit code.
POST="$_CSPR_DIR/post-issue-comment.sh"
if [ ! -f "$POST" ]; then
  _note warning "cancel-superseded-pr-runs: post-issue-comment.sh absent at $POST; cancelled $CANCELLED run(s) but posted no explanation comment on PR #$PR."
  rm -f "$BODY_FILE"
  exit 0
fi
POST_OUT="$(bash "$POST" "$PR" "$BODY_FILE" 2>&1)"
printf '%s\n' "$POST_OUT"
rm -f "$BODY_FILE"
# Coupled to post-issue-comment.sh: this literal is its success breadcrumb. Renaming
# that breadcrumb there without updating this grep would silently flip every posted
# comment to the "did NOT post" warning below.
if printf '%s\n' "$POST_OUT" | grep -qxF "devflow: posted comment on #$PR"; then
  _note notice "cancel-superseded-pr-runs: posted the auto-cancel explanation on PR #$PR ($CANCELLED run(s), $_verb)."
else
  _note warning "cancel-superseded-pr-runs: cancelled $CANCELLED run(s) but the explanation comment did NOT post on PR #$PR."
fi
exit 0

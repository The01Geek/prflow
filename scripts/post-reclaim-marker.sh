#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-reclaim-marker.sh ISSUE REPO RUN_ID RUN_ATTEMPT JOB_ID ACTION —
# post the run-scoped durable Spot-reclaim marker comment (issue #261, AC43).
#
# The in-job watcher calls this on the first poll that returns a valid Spot
# interruption action, WHILE the runner is still alive, so the downstream recovery
# job can later authenticate the reclaim from an exactly-bound marker.
#
# The marker's first line binds repo/run-id/run-attempt/job-id so the recovery job
# can compare each against the run under evaluation; the AUTHOR is authenticated by
# the recovery job from the GitHub API's comment.user, never from this body. The
# body carries NO `/prflow:` command token: a bot-authored comment must never
# re-trigger a workflow (the gate/dedupe self-trigger guard), so the resume
# command — if any — is posted separately by the recovery job, not by this marker.
#
# Best-effort like post-issue-comment.sh (which it funnels through): it exits 0 on
# a landed post and non-zero on a write failure, with a stderr breadcrumb, so the
# watcher can decide whether the marker landed. A failed marker write fails toward
# no automatic resume (recovery-classify.sh returns unclassifiable with no marker).
set -uo pipefail

ISSUE="${1-}"
REPO="${2-}"
RUN_ID="${3-}"
RUN_ATTEMPT="${4-}"
JOB_ID="${5-}"
ACTION="${6-}"

if [ -z "$ISSUE" ] || [ -z "$REPO" ] || [ -z "$RUN_ID" ] || [ -z "$RUN_ATTEMPT" ] || [ -z "$JOB_ID" ]; then
  echo "post-reclaim-marker: missing a required binding argument (ISSUE/REPO/RUN_ID/RUN_ATTEMPT/JOB_ID); no marker posted" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POSTER="$HERE/post-issue-comment.sh"
if [ ! -f "$POSTER" ]; then
  echo "post-reclaim-marker: post-issue-comment.sh absent beside this helper ($POSTER); no marker posted" >&2
  exit 1
fi

BODY="$(mktemp 2>/dev/null)" || {
  echo "post-reclaim-marker: mktemp failed; no marker posted" >&2
  exit 1
}
# The marker line MUST be the first line (readers scan the first line only) and
# carry no command token. ACTION is descriptive prose only.
{
  printf '<!-- prflow:spot-reclaim repo=%s run_id=%s run_attempt=%s job_id=%s -->\n\n' \
    "$REPO" "$RUN_ID" "$RUN_ATTEMPT" "$JOB_ID"
  printf 'An EC2 Spot interruption action (`%s`) was detected for this run attempt while the runner was still alive. The downstream recovery job will reconcile the outcome; this comment carries no command and starts no run.\n' \
    "${ACTION:-unknown}"
} > "$BODY"

POST_ERR="$(bash "$POSTER" "$ISSUE" "$BODY" 2>&1)"
rm -f "$BODY"
printf '%s\n' "$POST_ERR" >&2
# post-issue-comment.sh always exits 0; its landed breadcrumb is the real signal.
if printf '%s' "$POST_ERR" | grep -qxF "devflow: posted comment on #${ISSUE}"; then
  exit 0
fi
echo "post-reclaim-marker: the reclaim marker did not land on #${ISSUE} (see breadcrumb above)" >&2
exit 1

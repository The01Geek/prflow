#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# gather-recovery-evidence.sh — derive the seven normalized flags recovery-classify.sh
# consumes, from the paginated Actions jobs API, the check-run annotations API, and
# the issue's reclaim-marker comment (issue #261, AC46/AC48).
#
# Usage:
#   gather-recovery-evidence.sh --repo OWNER/REPO --run-id ID --run-attempt N --issue N
#     [--fixture-jobs-json PATH --fixture-annotations-json PATH --fixture-comments-json PATH]
#
# Prints the seven tokens, one per line in this fixed order, each `true`/`false`:
#   HUMAN_CANCEL_ANNOTATION MARKER_PRESENT MARKER_AUTHOR_OK MARKER_REPO_MATCH
#   MARKER_RUN_ID_MATCH MARKER_RUN_ATTEMPT_MATCH MARKER_JOB_ID_MATCH
# and exits 0 always (an evidence gatherer, not a decision point — the caller reads
# the seven lines regardless and feeds them to recovery-classify.sh).
#
# AC46 fail-safe: ANY query/pagination/parse/identity-mismatch/permission failure
# emits ALL SEVEN flags `false` (so recovery-classify.sh returns `unclassifiable`
# and no reclaim resume) with a specific stderr breadcrumb naming the failed call —
# a reclaim requires every query to have positively succeeded.
#
# Author authentication (AC/recovery-classify contract): MARKER_AUTHOR_OK is read
# from the comment's API-reported user.type == "Bot", NEVER from the marker body —
# a byte-identical marker from a human author must not reclaim. The repo/run-id/
# run-attempt/job-id BINDINGS are the values compared, parsed from the marker's
# first line and matched against the run under evaluation.
#
# Test seam: the --fixture-*-json flags read captured JSON from disk instead
# of calling `gh api`, so the suite drives its arms with no network.
set -uo pipefail

REPO="" RUN_ID="" RUN_ATTEMPT="" ISSUE=""
FIX_JOBS="" FIX_ANNOTATIONS="" FIX_COMMENTS=""
FACTS_FILE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2-}"; shift 2 ;;
    --run-id) RUN_ID="${2-}"; shift 2 ;;
    --run-attempt) RUN_ATTEMPT="${2-}"; shift 2 ;;
    --issue) ISSUE="${2-}"; shift 2 ;;
    --fixture-jobs-json) FIX_JOBS="${2-}"; shift 2 ;;
    --fixture-annotations-json) FIX_ANNOTATIONS="${2-}"; shift 2 ;;
    --fixture-comments-json) FIX_COMMENTS="${2-}"; shift 2 ;;
    --facts-file) FACTS_FILE="${2-}"; shift 2 ;;
    *) echo "gather-recovery-evidence: unknown argument '$1'" >&2; shift ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# jq is preflight-guaranteed; gh via the single-source resolver.
# shellcheck source=../lib/resolve-jq.sh
. "$HERE/../lib/resolve-jq.sh"
: "${DEVFLOW_JQ:=$(devflow_resolve_jq)}"
# shellcheck source=../lib/resolve-gh.sh
. "$HERE/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# Recovery cause facts (issue #600): a SIDE CHANNEL for spot_recovery's cause line,
# decoupled from the seven-flag stdout contract. Defaulted up front so emit_all_false
# and the success path alike write a well-formed facts file; the capacity token
# defaults to `unknown`, never an empty token.
CAPACITY_TOKEN="unknown"
RUNNER_NAME=""
ANNOTATION_MESSAGE=""
NEVER_STARTED="unknown"

# Best-effort: write the facts file only when --facts-file was passed. jq is
# preflight-guaranteed; a jq failure leaves the file unwritten/empty via `|| true`,
# which the workflow treats as all facts unavailable — no new tool dependency.
write_facts_file() {
  [ -n "$FACTS_FILE" ] || return 0
  "$DEVFLOW_JQ" -n \
    --arg ct "$CAPACITY_TOKEN" --arg rn "$RUNNER_NAME" --arg am "$ANNOTATION_MESSAGE" --arg ns "$NEVER_STARTED" \
    '{capacity_token: $ct, runner_name: $rn, annotation_message: $am, never_started: $ns}' \
    > "$FACTS_FILE" 2>/dev/null || true
}

emit_all_false() {
  write_facts_file
  printf 'false\nfalse\nfalse\nfalse\nfalse\nfalse\nfalse\n'
  exit 0
}

# ── Resolve the exact run-attempt's `claude` job ─────────────────────────────
if [ -n "$FIX_JOBS" ]; then
  jobs_json="$(cat "$FIX_JOBS" 2>/dev/null)" || { echo "gather-recovery-evidence: fixture jobs file unreadable: $FIX_JOBS" >&2; emit_all_false; }
else
  jobs_json="$("$DEVFLOW_GH" api --paginate \
    "repos/${REPO}/actions/runs/${RUN_ID}/attempts/${RUN_ATTEMPT}/jobs" \
    --jq '.jobs[]' 2>/dev/null | "$DEVFLOW_JQ" -s '{jobs: .}')" \
    || { echo "gather-recovery-evidence: jobs API query failed for ${REPO} run ${RUN_ID} attempt ${RUN_ATTEMPT}" >&2; emit_all_false; }
fi

# Exactly one job named `claude` must resolve; zero, many, or a parse failure is an
# identity failure → unclassifiable (AC46).
claude_count="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r '[.jobs[]? | select(.name == "claude")] | length' 2>/dev/null || echo "parse-error")"
if [ "$claude_count" != "1" ]; then
  echo "gather-recovery-evidence: expected exactly one 'claude' job, found '${claude_count}' — identity failure" >&2
  emit_all_false
fi
CLAUDE_JOB_ID="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r '[.jobs[]? | select(.name == "claude")][0].id // empty' 2>/dev/null)"
CHECK_RUN_URL="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r '[.jobs[]? | select(.name == "claude")][0].check_run_url // empty' 2>/dev/null)"
if [ -z "$CLAUDE_JOB_ID" ]; then
  echo "gather-recovery-evidence: could not read the claude job id — identity failure" >&2
  emit_all_false
fi

# ── Recovery cause facts from the same jobs object (issue #600) ───────────────
# The capacity token is the FIRST `spot=<value>` slash-delimited segment of the
# claude job's labels, copied verbatim (RunsOn packs its runner config into the
# label as `runs-on=…/spot=false/…`). jq only — split()/startswith()/first — never
# tr/cut/sed/head/wc. A parse failure or a labels array with no spot= segment
# yields the pre-seeded `unknown`, never an empty token.
CAPACITY_TOKEN="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r '
  ([.jobs[]? | select(.name == "claude")][0].labels // []) as $labels
  | ([$labels[]? | split("/")[]? | select(startswith("spot="))] | first) // "unknown"
' 2>/dev/null)" || CAPACITY_TOKEN="unknown"
[ -n "$CAPACITY_TOKEN" ] || CAPACITY_TOKEN="unknown"
RUNNER_NAME="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r \
  '[.jobs[]? | select(.name == "claude")][0].runner_name // empty' 2>/dev/null)" || RUNNER_NAME=""
# Issue #471: a claude job cancelled while queued behind its per-issue concurrency
# group got no runner and ran no steps; it owns neither the workpad nor the branch.
NEVER_STARTED="$(printf '%s' "$jobs_json" | "$DEVFLOW_JQ" -r '
  [.jobs[]? | select(.name == "claude")][0]
  | if ((.runner_name // "") == "") and ((.steps // []) | length) == 0 then "true" else "false" end
' 2>/dev/null)" || NEVER_STARTED="unknown"
case "$NEVER_STARTED" in true|false) ;; *) NEVER_STARTED="unknown" ;; esac

# ── Check-run annotations → HUMAN_CANCEL_ANNOTATION ──────────────────────────
if [ -n "$FIX_ANNOTATIONS" ]; then
  annotations_json="$(cat "$FIX_ANNOTATIONS" 2>/dev/null)" || { echo "gather-recovery-evidence: fixture annotations file unreadable: $FIX_ANNOTATIONS" >&2; emit_all_false; }
else
  # Derive the check-run id from the job's check_run_url basename, then paginate
  # its annotations. A missing check_run_url is an identity failure.
  if [ -z "$CHECK_RUN_URL" ]; then
    echo "gather-recovery-evidence: claude job has no check_run_url — identity failure" >&2
    emit_all_false
  fi
  CHECK_RUN_ID="${CHECK_RUN_URL##*/}"
  annotations_json="$("$DEVFLOW_GH" api --paginate \
    "repos/${REPO}/check-runs/${CHECK_RUN_ID}/annotations" \
    --jq '.[]' 2>/dev/null | "$DEVFLOW_JQ" -s '.')" \
    || { echo "gather-recovery-evidence: check-run annotations query failed for check-run ${CHECK_RUN_ID}" >&2; emit_all_false; }
fi

# Explicit human-cancellation ONLY: "The run was canceled by @<user>". The generic
# "The operation was canceled." is NOT explicit (recovery-classify contract).
human_cancel="$(printf '%s' "$annotations_json" | "$DEVFLOW_JQ" -r \
  'if [.[]? | (.message // "") | test("^The run was canceled by @")] | any then "true" else "false" end' 2>/dev/null || echo "parse-error")"
if [ "$human_cancel" != "true" ] && [ "$human_cancel" != "false" ]; then
  echo "gather-recovery-evidence: could not parse annotations — treating as query failure" >&2
  emit_all_false
fi

# The first FAILURE-level annotation message (issue #600) — never the human-cancel
# one, which is matched separately above. Absent when the check-run carries no
# failure-level annotation; the workflow renders that as `unavailable`.
ANNOTATION_MESSAGE="$(printf '%s' "$annotations_json" | "$DEVFLOW_JQ" -r \
  '[.[]? | select((.annotation_level // "") == "failure") | (.message // "")] | first // empty' 2>/dev/null)" || ANNOTATION_MESSAGE=""

# ── Issue comments → reclaim marker presence, author, bindings ───────────────
if [ -n "$FIX_COMMENTS" ]; then
  comments_json="$(cat "$FIX_COMMENTS" 2>/dev/null)" || { echo "gather-recovery-evidence: fixture comments file unreadable: $FIX_COMMENTS" >&2; emit_all_false; }
else
  comments_json="$("$DEVFLOW_GH" api --paginate \
    "repos/${REPO}/issues/${ISSUE}/comments?per_page=100" \
    --jq '.[]' 2>/dev/null | "$DEVFLOW_JQ" -s '.')" \
    || { echo "gather-recovery-evidence: issue comments query failed for ${REPO}#${ISSUE}" >&2; emit_all_false; }
fi

# The newest comment whose FIRST line is a spot-reclaim marker. Emits a tab-joined
# record: author-type <TAB> repo <TAB> run_id <TAB> run_attempt <TAB> job_id, or
# empty when no marker comment exists. Bindings come from the marker line; the
# author TYPE comes from the API user object, never the body.
marker_record="$(printf '%s' "$comments_json" | "$DEVFLOW_JQ" -r '
  [ .[]?
    | select((.body // "") | split("\n")[0] | test("^<!-- prflow:spot-reclaim "))
    | { body: ((.body // "") | split("\n")[0]),
        utype: (.user.type // "") }
  ] | last // empty
  | . as $c
  | ($c.body | capture("repo=(?<repo>[^ ]+) run_id=(?<run_id>[^ ]+) run_attempt=(?<run_attempt>[^ ]+) job_id=(?<job_id>[^ ]+) -->") ) as $b
  | [$c.utype, $b.repo, $b.run_id, $b.run_attempt, $b.job_id] | @tsv
' 2>/dev/null || echo "PARSE_ERROR")"

if [ "$marker_record" = "PARSE_ERROR" ]; then
  echo "gather-recovery-evidence: could not parse issue comments — treating as query failure" >&2
  emit_all_false
fi

marker_present=false
author_ok=false
repo_match=false
run_id_match=false
run_attempt_match=false
job_id_match=false

if [ -n "$marker_record" ]; then
  marker_present=true
  IFS=$'\t' read -r m_utype m_repo m_run_id m_run_attempt m_job_id <<< "$marker_record"
  [ "$m_utype" = "Bot" ] && author_ok=true
  [ "$m_repo" = "$REPO" ] && repo_match=true
  [ "$m_run_id" = "$RUN_ID" ] && run_id_match=true
  [ "$m_run_attempt" = "$RUN_ATTEMPT" ] && run_attempt_match=true
  [ "$m_job_id" = "$CLAUDE_JOB_ID" ] && job_id_match=true
fi

# Write the recovery cause facts on the success path too (every earlier exit went
# through emit_all_false, which already wrote them). The seven-line stdout below is
# untouched.
write_facts_file
printf '%s\n' "$human_cancel" "$marker_present" "$author_ok" "$repo_match" \
  "$run_id_match" "$run_attempt_match" "$job_id_match"
exit 0

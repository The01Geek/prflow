#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Decide whether THIS /devflow:implement run is a duplicate of an already-active
# run for the same issue/PR thread, so the heavy `claude` job can be skipped.
#
# Why a gate-stage check (not GitHub-native `concurrency`): the desired behavior
# is "ignore the new command, leave the in-progress run untouched". Native
# concurrency cannot express that — `cancel-in-progress: true` cancels the
# in-flight run (wrong run), and `cancel-in-progress: false` QUEUES the duplicate
# so it eventually runs (not ignored). GitHub has no "skip if already running"
# primitive, so we detect duplicates ourselves here and set `duplicate=true`,
# which the workflow uses to skip the billable job and post a brief notice. This
# is repository doctrine covering BOTH duplicate-command paths — this implement
# path and the /prflow:review command path (scripts/dedupe-review-command.sh,
# issue #989) — so both are gate-stage checks rather than concurrency groups. The
# runs this check lets through (the stall-resume carve-out, the sub-second race) are
# serialized downstream by the claude job's per-issue queue-only concurrency group
# (issue #471); do not drop that group on the grounds that dedupe covers the race.
#
# How "same thread" is identified: devflow-implement.yml sets a `run-name`
# embedding the issue/PR number the command was posted on (CONTEXT_NUMBER). We
# list this workflow's active runs and match that number out of each run's
# displayTitle. A second `/devflow:implement` posted on the same issue/PR thread
# therefore carries the same number and is detected. (Boundary: an explicit
# `/devflow:implement <n>` cross-posted on a *different* thread keys on the
# thread it was posted in, not <n> — the dominant duplicate case is repeated
# commands on one thread, which this covers.)
#
# Tie-break / no double-skip: a run defers ONLY to an active run with a SMALLER
# databaseId (an older run). GitHub run ids increase monotonically, so among any
# set of overlapping runs for one thread the oldest — having no older peer —
# proceeds, and the rest see it and ignore. This run never defers to a newer run,
# so the common case (duplicate commands seconds apart) collapses to exactly one
# run. CAVEAT: `gh run list` is eventually consistent, so two commands fired
# within the same sub-second window can each query before the other's run row
# materialises; both then see no older peer and proceed. That residual race is
# accepted (it fails toward running, never toward silently swallowing a request).
#
# Boundaries: only this workflow's runs are considered (`--workflow`), and only
# the first `--limit 100` listed runs — an older active peer beyond that window,
# or a WORKFLOW rename, degrades to fail-open (a possible redundant run, never a
# swallowed one).
#
# Inputs (env):
#   REPO            owner/repo, for the `gh run list` call.
#   CONTEXT_NUMBER  the issue/PR thread number to dedupe on (the run-name marker).
#   RUN_ID          github.run_id of THIS run (excluded from the active set; also
#                   the monotonic tie-break boundary).
#   GH_TOKEN        token for `gh`, set by the caller.
#   WORKFLOW        workflow file to scope the run list (default devflow-implement.yml).
#   IS_STALL_RESUME optional explicit override: "true" forces the stall-resume
#                   carve-out (skip dedupe, proceed), any other non-empty value
#                   forces normal dedupe. When UNSET/empty the script self-derives
#                   it from the triggering comment (see below). Mainly a test hook.
#   GITHUB_EVENT_PATH  the Actions event payload (set by the runner). When
#                   IS_STALL_RESUME is not explicitly set, the script reads
#                   `.comment.body` from it and treats the run as a stall resume
#                   when that body carries the STALL_RESUME_MARKER below. This lets
#                   the carve-out work with NO devflow-implement.yml change — the
#                   workflow file needs a `workflows`-scoped push the bot lacks.
#   DEVFLOW_GH      gh executable override for tests; when unset or empty it is
#                   resolved (execution-verified) via lib/resolve-gh.sh.
#
# Stall-resume carve-out (issue #280, resolving the deferred #268 finding): a run
# triggered by the stall backstop's auto-resume comment must NOT defer to the run
# it is taking over. That original run posts the resume comment from its own
# trailing `always()` backstop step while it is still `in_progress`, so a plain
# run-list dedupe sees the older active peer and swallows the resume — leaving the
# audit comment visible but inert, the exact race the #268 finding named. The
# resume comment is identified by the stall-backstop-audit marker it carries
# (kept identical to the `MARKER` the backstop step writes in devflow-implement.yml).
# The carve-out never WRONGLY bypasses dedupe for an ordinary command: only a
# comment carrying the marker skips dedupe (a redundant run at worst). A
# marker-detection error on a genuine resume (a malformed/unreadable payload)
# does NOT bypass dedupe — it falls through to ordinary dedupe, which CAN then
# emit duplicate=true and swallow the resume — but such an error is made VISIBLE
# via a ::warning:: (see the detection block below) rather than swallowed silently.
#
# Output: one `key=value` line on stdout (the caller appends to $GITHUB_OUTPUT;
# tests assert it directly):
#   duplicate=true|false
#
# Fails OPEN: a missing input or a run-list query error yields duplicate=false
# (the run proceeds) with a ::warning::, because silently swallowing a legitimate
# single request is worse than a rare redundant run. (The one exception is a
# marker-detection error in the resume carve-out below: it emits a ::warning:: but
# then falls through to ordinary dedupe rather than forcing duplicate=false, since
# an unreadable payload cannot be confirmed a resume.) Diagnostics go to stderr.

set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

emit() { printf '%s=%s\n' "$1" "$2"; }

# The marker every stall-backstop auto-resume comment carries on its first line
# (see the `MARKER` the Stall backstop step writes in devflow-implement.yml). Keep
# the two literals identical — lib/test/run.sh pins that they agree across files.
STALL_RESUME_MARKER='<!-- prflow:stall-backstop-audit -->'
# PRFlow writes the current spelling; every artifact created before the rename carries the superseded one and no body is rewritten, so readers accept BOTH (issue #1003).
STALL_RESUME_MARKER_SUPERSEDED='<!-- devflow:stall-backstop-audit -->'

# Resolve the carve-out signal: an explicit IS_STALL_RESUME wins (test hook /
# override); otherwise self-derive it from the triggering comment body in the
# Actions event payload. Reading the payload here (rather than a workflow-passed
# env) keeps the fix entirely inside this script, so it needs no
# devflow-implement.yml edit (a workflow file the bot's token cannot push).
# This runs BEFORE the gh resolver below so a stall resume — which never queries
# gh — skips the (execution-verified) `gh --version` probe entirely.
is_stall_resume="${IS_STALL_RESUME:-}"
if [ -z "$is_stall_resume" ] && [ -n "${GITHUB_EVENT_PATH:-}" ]; then
  if [ -r "$GITHUB_EVENT_PATH" ]; then
    # Distinguish jq exit 1 (marker genuinely ABSENT — the expected non-resume case,
    # silent) from jq exit >1 (a REAL read/parse error — a malformed/empty payload).
    # Both keep the fail-open direction (leave is_stall_resume empty, fall through to
    # ordinary dedupe), but a real error is NOT silent: it emits a ::warning:: like
    # every other error path here and the header contract, because a detection failure
    # on a genuine resume that then dedupes to duplicate=true is the #268 swallow — it
    # must be visible, not swallowed behind /dev/null. Same jq-stderr-capture discipline
    # as the run-list dedupe below. This runs BEFORE the gh resolver, so a stall resume
    # still skips the `gh --version` probe.
    marker_err="$(mktemp)"
    jq_rc=0
    "$DEVFLOW_JQ" -e --arg m "$STALL_RESUME_MARKER" --arg s "$STALL_RESUME_MARKER_SUPERSEDED" \
      '((.comment.body // "") | contains($m)) or ((.comment.body // "") | contains($s))' "$GITHUB_EVENT_PATH" >/dev/null 2>"$marker_err" || jq_rc=$?
    if [ "$jq_rc" -eq 0 ]; then
      is_stall_resume=true
    elif [ "$jq_rc" -gt 1 ]; then
      echo "::warning::dedupe: could not read the stall-resume marker from GITHUB_EVENT_PATH (jq: $(tr '\n' ' ' < "$marker_err")); treating as a non-resume, so ordinary dedupe applies." >&2
    fi
    rm -f "$marker_err"
  elif [ -e "$GITHUB_EVENT_PATH" ]; then
    # PRESENT-but-unreadable payload (a permission/mount anomaly, or a partially
    # materialised/locked payload): the [ -r ] probe above returned false, so the
    # marker-read (jq) inside that branch never runs and the marker cannot be checked.
    # Like the malformed/empty jq-error branch, keep the fail-open
    # direction (leave is_stall_resume empty, fall through to ordinary dedupe) — but
    # make the anomaly VISIBLE with a ::warning:: rather than swallowing a possible
    # genuine resume silently, exactly as the header contract promises for an unreadable
    # payload. An unset/empty (guarded above) or NONEXISTENT GITHUB_EVENT_PATH is an
    # ABSENT optional signal, not an unreadable one, so it stays silent (the [ -e ] test
    # excludes it here) — the IS_STALL_RESUME override covers the no-payload case.
    echo "::warning::dedupe: could not read the stall-resume marker from GITHUB_EVENT_PATH ($GITHUB_EVENT_PATH is set but not readable); treating as a non-resume, so ordinary dedupe applies." >&2
  fi
fi

if [ "$is_stall_resume" = "true" ]; then
  echo "::notice::dedupe: this run was triggered by a stall-backstop auto-resume; skipping dedupe so it can take over the winding-down run (issue #280)." >&2
  emit duplicate false
  exit 0
fi

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
GH="$DEVFLOW_GH"
repo="${REPO:-}"
target="${CONTEXT_NUMBER:-}"
run_id="${RUN_ID:-}"
workflow="${WORKFLOW:-devflow-implement.yml}"

# Fail open on any missing prerequisite — we cannot reliably dedupe without all
# three, and blocking a legitimate run on our own missing context is the worse
# failure direction.
if [ -z "$repo" ] || ! [[ "$target" =~ ^[0-9]+$ ]] || ! [[ "$run_id" =~ ^[0-9]+$ ]]; then
  echo "::warning::dedupe: missing/invalid REPO/CONTEXT_NUMBER/RUN_ID; not deduping (run proceeds)." >&2
  emit duplicate false
  exit 0
fi

# List this workflow's recent runs; keep only ACTIVE ones older than this run
# (databaseId < RUN_ID) whose run-name targets the same thread number. The
# number is matched with non-digit boundaries so target 2 never matches
# "issue 21". A query failure is fail-open.
if ! runs_json="$("$GH" run list --repo "$repo" --workflow "$workflow" \
      --limit 100 --json databaseId,displayTitle,status 2>/dev/null)"; then
  echo "::warning::dedupe: 'gh run list' failed; not deduping (run proceeds)." >&2
  emit duplicate false
  exit 0
fi

# Capture jq's stderr so a permanent breakage (jq missing, malformed JSON from a
# 5xx HTML error page) is distinguishable from a transient blip in the warning —
# same diagnostic discipline as react-to-trigger.sh's gh-stderr capture. Without
# it, a missing jq would silently disable dedupe forever behind a generic message.
jq_err="$(mktemp)"
count="$(printf '%s' "$runs_json" | "$DEVFLOW_JQ" -r --argjson run "$run_id" --arg target "$target" '
  [ .[]
    | select(.status as $s | ["in_progress","queued","requested","waiting","pending"] | index($s))
    | select(.databaseId < $run)
    | select(.displayTitle | test("(^|[^0-9])" + $target + "([^0-9]|$)"))
  ] | length' 2>"$jq_err")" || count=""

if ! [[ "$count" =~ ^[0-9]+$ ]]; then
  echo "::warning::dedupe: could not parse active-run count (jq: $(tr '\n' ' ' < "$jq_err")); not deduping (run proceeds)." >&2
  rm -f "$jq_err"
  emit duplicate false
  exit 0
fi
rm -f "$jq_err"

if [ "$count" -gt 0 ]; then
  echo "::notice::dedupe: $count older active /devflow:implement run(s) for issue/PR #$target; ignoring this duplicate." >&2
  emit duplicate true
else
  emit duplicate false
fi

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# derive-review-preconditions.sh — evaluate the devflow-review auto-trigger
# preconditions for a PR head, fail-closed (issue #304). This is the small,
# testable unit devflow-review.yml's precheck `route` step calls before
# emitting should_run=true on the first-review / synchronize / CI-completion
# paths (the check_run Re-run path is deliberately ungated — Re-run forces a
# review past the preconditions, which is what makes the deferral summary's
# "Click Re-run … to force a review" true); lib/test/run.sh drives it
# directly with a stubbed `gh` over the input-shape matrix.
#
# Two config-gated preconditions, both defaulting to enabled:
#   require_up_to_date  the PR branch must not be BEHIND its configured base
#                       branch (compare API, behind_by == 0). A review of a
#                       branch that a forthcoming update would invalidate is
#                       wasted cost — this gate is a cost optimization, not a
#                       correctness gate (a neutral required check does not
#                       block merge; see the schema description).
#   require_ci_green    every OTHER CI signal on the head must have completed
#                       without failing (success/skipped/neutral are green —
#                       see below) before an LLM code-quality verdict is
#                       produced. "Other CI" is generic — no job names:
#                         (1) Actions workflow runs for the head, excluding
#                             this workflow itself (SELF_WORKFLOW_NAME) — runs
#                             are registered at event dispatch, so in practice
#                             "no runs" means "no Actions CI exists" rather
#                             than "CI has not registered yet"; a registration
#                             race is theoretically possible and accepted (a
#                             premature review is a bounded cost, and the
#                             deferral/exactly-once machinery bounds it). The
#                             non-self runs are COLLAPSED to the latest run
#                             (highest run_number) per (workflow_id, event)
#                             group before gating, so a superseded run (an
#                             approval-gated re-dispatch, a double-fire, a
#                             cancelled sibling) never gates once a newer run of
#                             the same workflow+event exists (issue #351). A
#                             non-self run missing a numeric workflow_id or
#                             run_number, or a string event, makes the collapse
#                             unverifiable and fails closed (unverifiable), never
#                             a dropped signal. The runs API returns each run's CURRENT
#                             attempt, so a re-run needs no special handling.
#                             Signal sets (2) and (3) need no collapse: GitHub
#                             already returns the latest per name server-side
#                             (check-runs defaults to filter=latest; the
#                             combined status is collapsed too);
#                         (2) the legacy combined commit status (total_count
#                             gates it — an empty status set reports state
#                             "pending" and must not be read as pending CI);
#                         (3) non-Actions (external app) check runs, with the
#                             review check-run name excluded (`PRFlow Review`,
#                             plus the superseded `Devflow Review`)
#                             defensively (its own check never blocks itself).
#                       Zero signals across all three -> satisfied: a repo
#                       with no other CI is reviewed immediately, never wedged.
#                       success/skipped/neutral conclusions are green; any
#                       non-completed status or other conclusion defers.
#
# Inputs (environment):
#   REPO                 owner/name (required)
#   HEAD_SHA             the PR head SHA under evaluation (required)
#   BASE_BRANCH          configured base branch (required when the freshness
#                        gate is on — never a hardcoded trunk default here)
#   REQUIRE_UP_TO_DATE   "false" disables the freshness gate; anything else
#                        (including empty/garbage) enables it — fail toward
#                        gating, the review still fires via a later event or
#                        the Re-run button
#   REQUIRE_CI_GREEN     same contract for the other-CI gate
#   SELF_WORKFLOW_NAME   this workflow's name, excluded from the Actions-runs
#                        set (default: "Devflow Review (auto-trigger)"; the
#                        withheld auto-trigger workflow's Actions run name, which
#                        this rename leaves frozen alongside telemetry-push.yml)
#
# Output (stdout, two lines, always emitted; always exits 0):
#   should_run=<true|false>
#   reason=<empty|behind-base|ci-not-green|ci-approval-required|unverifiable>
# `reason` is empty only when should_run=true. ci-approval-required is a distinct
# deferral for a completed run awaiting manual approval (conclusion
# 'action_required'); it exists so the neutral check can name approval as the
# blocker in plain language rather than the opaque 'other CI not green':
# devflow-review.yml's create_check maps it to the title 'PRFlow review
# waiting: CI approval required'. Every deferral and fail-closed
# arm emits a SPECIFIC stderr breadcrumb naming which condition fired. Fail
# closed on any unverifiable query: a missed review is recoverable via the
# next event or the check's Re-run button; a wasted/premature LLM review is
# the cost this unit exists to prevent.
#
# $DEVFLOW_GH overrides the `gh` binary and $DEVFLOW_JQ the `jq` binary (the
# same seams the rest of devflow uses; both honored by the sourced resolvers).

set -uo pipefail

_DRP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (documented partial-copy posture — see CLAUDE.md): a deployment
# carrying this file without its sibling lib/resolve-gh.sh must degrade to bare
# `gh` with a breadcrumb, never assign an empty DEVFLOW_GH from an undefined
# devflow_resolve_gh.
# shellcheck source=../lib/resolve-gh.sh
. "$_DRP_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
# Sourceability is not function-availability — verify the function itself.
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  # Partial-copy degradation only (resolver absent, breadcrumb above): the `:-`
  # form is the sanctioned fallback shape — the #245 peer-completeness pin
  # forbids the `:=gh` default precisely so full deployments route the resolver.
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi
# Guarded source: a missing resolve-jq.sh sibling degrades to bare `jq` with a
# breadcrumb, never an unbound-variable abort under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_DRP_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability (mirrors the gh guard above).
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

REPO="${REPO:-}"
HEAD_SHA="${HEAD_SHA:-}"
BASE_BRANCH="${BASE_BRANCH:-}"
REQUIRE_UP_TO_DATE="${REQUIRE_UP_TO_DATE:-true}"
REQUIRE_CI_GREEN="${REQUIRE_CI_GREEN:-true}"
SELF_WORKFLOW_NAME="${SELF_WORKFLOW_NAME:-Devflow Review (auto-trigger)}"

emit() { printf 'should_run=%s\nreason=%s\n' "$1" "$2"; exit 0; }

# Render a captured-stderr temp file for a "query failed" breadcrumb: the raw gh
# error when one was captured, else a fixed placeholder. Single definition of the
# reader the four gh-failure arms share (so the breadcrumb format has one edit
# site); each arm still owns its distinct noun + emit reason inline.
gh_err_detail() { [ -s "$1" ] && cat "$1" || echo 'no error output captured'; }

# Shared green-gate over a stream of "status|conclusion" lines (one signal per
# line — the single definition of what "green" means for both the Actions-runs
# and external-check-runs sets). $2 names the signal kind so each deferral
# breadcrumb stays specific to the set that fired it.
gate_signal_lines() {  # $1=lines  $2=signal noun for the breadcrumb
  local _st _cn
  while IFS='|' read -r _st _cn; do
    if [ "$_st" != "completed" ]; then
      echo "derive-review-preconditions: $2 on $HEAD_SHA is still '$_st' — deferring the review (ci-not-green: pending)." >&2
      emit false ci-not-green
    fi
    case "$_cn" in
      success|skipped|neutral) : ;;  # green: skipped/neutral signals (path filters etc.) must not wedge the review
      action_required)
        # A completed run awaiting manual approval (an approval-gated re-dispatch,
        # e.g. a bot-actor run) — distinct from a generic non-green conclusion so
        # the neutral check can name approval as the blocker: devflow-review.yml
        # maps ci-approval-required to the title 'PRFlow review waiting: CI
        # approval required' (selected by scripts/describe-skip-title.sh; that
        # deferral check-run title — posted by create_check — is the coupled
        # workflow-side change, landed in #353, extracted to the helper in #389)
        # (issue #351).
        # Shared gate, so an external app's action_required check run is treated
        # the same way.
        echo "derive-review-preconditions: $2 on $HEAD_SHA concluded 'action_required' — an approval is required before it can run; deferring the review (ci-approval-required)." >&2
        emit false ci-approval-required
        ;;
      *)
        echo "derive-review-preconditions: $2 on $HEAD_SHA concluded '$_cn' — deferring the review (ci-not-green)." >&2
        emit false ci-not-green
        ;;
    esac
  done <<<"$1"
}

# Both gates off -> unconditional behavior restored; no API query is made.
if [ "$REQUIRE_UP_TO_DATE" = "false" ] && [ "$REQUIRE_CI_GREEN" = "false" ]; then
  emit true ""
fi

# Missing identifiers make every query unverifiable -> fail closed.
if [ -z "$REPO" ] || [ -z "$HEAD_SHA" ]; then
  echo "derive-review-preconditions: REPO ('$REPO') or HEAD_SHA ('$HEAD_SHA') is empty — preconditions unverifiable; failing closed (no auto-trigger; recoverable via a later event or the Re-run button)." >&2
  emit false unverifiable
fi

# ── Precondition 1: branch freshness (behind base) ──────────────────────────
if [ "$REQUIRE_UP_TO_DATE" != "false" ]; then
  if [ -z "$BASE_BRANCH" ]; then
    # Never substitute a hardcoded trunk name here — the configured base_branch
    # is the caller's job to resolve (CLAUDE.md: consumer repos use master/
    # develop/...); an empty value is unverifiable, not "main".
    echo "derive-review-preconditions: BASE_BRANCH is empty with the freshness gate enabled — branch freshness unverifiable; failing closed." >&2
    emit false unverifiable
  fi
  # per_page=1 trims the commit list in the payload; behind_by (all this arm
  # reads) is present regardless — a long-lived branch's full compare payload
  # can run to hundreds of KB otherwise.
  # Capture gh's own stderr into the breadcrumb (mirrors resolve_pr_for_head in
  # devflow-review.yml): a bare "query failed" hides the real cause (rate limit,
  # 403 token-scope, 5xx) from whoever debugs a permanently-deferred review.
  _cmp_err=$(mktemp 2>/dev/null) || _cmp_err=/dev/null
  if ! CMP_JSON=$("$DEVFLOW_GH" api "repos/$REPO/compare/$BASE_BRANCH...$HEAD_SHA?per_page=1" 2>"$_cmp_err"); then
    echo "derive-review-preconditions: compare query failed for $BASE_BRANCH...$HEAD_SHA ($(gh_err_detail "$_cmp_err")) — branch freshness unverifiable; failing closed (unverifiable). Recoverable via a later event or the Re-run button." >&2
    [ "$_cmp_err" = /dev/null ] || rm -f "$_cmp_err"
    emit false unverifiable
  fi
  [ "$_cmp_err" = /dev/null ] || rm -f "$_cmp_err"
  BEHIND=$(printf '%s' "$CMP_JSON" | "$DEVFLOW_JQ" -r '.behind_by // empty' 2>/dev/null) || BEHIND=""
  if ! [[ "$BEHIND" =~ ^[0-9]+$ ]]; then
    echo "derive-review-preconditions: compare payload carried no numeric behind_by ('$BEHIND') — branch freshness unverifiable; failing closed (unverifiable)." >&2
    emit false unverifiable
  fi
  if [ "$BEHIND" != "0" ]; then
    echo "derive-review-preconditions: head $HEAD_SHA is behind $BASE_BRANCH by $BEHIND commit(s) — deferring the review (behind-base)." >&2
    emit false behind-base
  fi
fi

# ── Precondition 2: other CI green ───────────────────────────────────────────
if [ "$REQUIRE_CI_GREEN" != "false" ]; then
  OTHER_SIGNALS=0

  # (1) Actions workflow runs for this head, excluding this workflow itself.
  #     --paginate concatenates page OBJECTS; the -s slurp + map/add flattens
  #     them (same normalization discipline as derive-review-verdict.sh).
  _runs_err=$(mktemp 2>/dev/null) || _runs_err=/dev/null
  if ! RUNS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/actions/runs?head_sha=$HEAD_SHA&per_page=100" 2>"$_runs_err"); then
    echo "derive-review-preconditions: workflow-runs query failed for $HEAD_SHA ($(gh_err_detail "$_runs_err")) — other-CI state unverifiable; failing closed (unverifiable). Recoverable via a later event or the Re-run button." >&2
    [ "$_runs_err" = /dev/null ] || rm -f "$_runs_err"
    emit false unverifiable
  fi
  [ "$_runs_err" = /dev/null ] || rm -f "$_runs_err"
  # Collapse duplicate runs to one per (workflow_id, event) group before gating.
  # A PR head can carry several runs of the SAME workflow+event — an approval-gated
  # re-dispatch, a superseded double-fire, a cancelled sibling — and only the
  # latest (highest run_number) reflects the head's real state; gating on a
  # superseded non-green run wedges the review forever (issue #351, PR #349).
  # run_number is preferred over created_at: created_at has 1s granularity and can
  # tie, while run_number is strictly monotonic per workflow, so a group has one
  # maximum. Self-exclusion runs BEFORE the numeric-operand guard AND the grouping,
  # so the review's own runs never form a group and a self run lacking
  # workflow_id/run_number/event cannot trip the guard. The guard fails CLOSED (jq
  # errors, caught below) when a NON-self run lacks a numeric workflow_id or
  # run_number, OR a string event: group_by/max_by on an absent key silently drops
  # or nondeterministically picks a signal, and an absent event mis-groups a run
  # under a null bucket so an older non-green run could survive the collapse in its
  # own group and re-wedge the review (fail-open) — all three group/select operands
  # are validated before grouping — see issue #351 AC7.
  _runlines_err=$(mktemp 2>/dev/null) || _runlines_err=/dev/null
  if ! RUN_LINES=$(printf '%s' "$RUNS_JSON" | "$DEVFLOW_JQ" -rs --arg self "$SELF_WORKFLOW_NAME" \
        'map(.workflow_runs // []) | add // []
         | map(select((.name // "") != $self))
         | if any(.[]; (.workflow_id | type) != "number")
           then error("a non-self workflow run is missing a numeric workflow_id")
           elif any(.[]; (.run_number | type) != "number")
           then error("a non-self workflow run is missing a numeric run_number")
           elif any(.[]; (.event | type) != "string")
           then error("a non-self workflow run is missing a string event")
           else . end
         | group_by([.workflow_id, .event])
         | map(max_by(.run_number))
         | .[] | ((.status // "") + "|" + (.conclusion // ""))' 2>"$_runlines_err"); then
    _runlines_detail=$(gh_err_detail "$_runlines_err")
    [ "$_runlines_err" = /dev/null ] || rm -f "$_runlines_err"
    # Distinguish an UNGROUPABLE run (a non-self run missing the numeric
    # workflow_id/run_number or string event the collapse needs — name the field)
    # from a genuinely unparseable page; both fail closed (unverifiable), never a
    # dropped signal or a positively-asserted ci-not-green.
    case "$_runlines_detail" in
      *"numeric workflow_id"*|*"numeric run_number"*|*"string event"*)
        echo "derive-review-preconditions: a non-self workflow run on $HEAD_SHA cannot be collapsed to the latest run per (workflow_id, event) group ($_runlines_detail) — other-CI state unverifiable; failing closed (unverifiable)." >&2
        ;;
      *)
        echo "derive-review-preconditions: workflow-runs payload could not be parsed (jq failed or a non-object page: $_runlines_detail) — failing closed (unverifiable)." >&2
        ;;
    esac
    emit false unverifiable
  fi
  [ "$_runlines_err" = /dev/null ] || rm -f "$_runlines_err"
  if [ -n "$RUN_LINES" ]; then
    OTHER_SIGNALS=1
    gate_signal_lines "$RUN_LINES" "another workflow run"
  fi

  # (2) Legacy combined commit status. total_count gates it: with ZERO statuses
  #     the API reports state "pending", which must not be read as pending CI.
  _status_err=$(mktemp 2>/dev/null) || _status_err=/dev/null
  if ! STATUS_JSON=$("$DEVFLOW_GH" api "repos/$REPO/commits/$HEAD_SHA/status" 2>"$_status_err"); then
    echo "derive-review-preconditions: combined-status query failed for $HEAD_SHA ($(gh_err_detail "$_status_err")) — other-CI state unverifiable; failing closed (unverifiable)." >&2
    [ "$_status_err" = /dev/null ] || rm -f "$_status_err"
    emit false unverifiable
  fi
  [ "$_status_err" = /dev/null ] || rm -f "$_status_err"
  STATUS_TOTAL=$(printf '%s' "$STATUS_JSON" | "$DEVFLOW_JQ" -r '.total_count // empty' 2>/dev/null) || STATUS_TOTAL=""
  if ! [[ "$STATUS_TOTAL" =~ ^[0-9]+$ ]]; then
    echo "derive-review-preconditions: combined-status payload carried no numeric total_count ('$STATUS_TOTAL') — failing closed (unverifiable)." >&2
    emit false unverifiable
  fi
  if [ "$STATUS_TOTAL" != "0" ]; then
    OTHER_SIGNALS=1
    # `.state | strings` yields empty on a missing/non-string state — an
    # UNVERIFIABLE shape, routed to the honest unverifiable reason like every
    # other parse failure (never asserted as an observed ci-not-green).
    STATUS_STATE=$(printf '%s' "$STATUS_JSON" | "$DEVFLOW_JQ" -r '.state | strings' 2>/dev/null) || STATUS_STATE=""
    if [ -z "$STATUS_STATE" ]; then
      echo "derive-review-preconditions: combined-status payload carried no string state (total_count $STATUS_TOTAL) — failing closed (unverifiable)." >&2
      emit false unverifiable
    fi
    if [ "$STATUS_STATE" != "success" ]; then
      echo "derive-review-preconditions: combined commit status for $HEAD_SHA is '$STATUS_STATE' ($STATUS_TOTAL status(es)) — deferring the review (ci-not-green)." >&2
      emit false ci-not-green
    fi
  fi

  # (3) External (non-Actions app) check runs. Actions job check-runs are
  #     already covered at workflow granularity by (1) — and excluding the
  #     github-actions app here is what keeps this workflow's OWN job
  #     check-runs (precheck, create_check, the API-posted `PRFlow Review`
  #     run) from gating themselves. The review check-run name (`PRFlow Review`,
  #     plus the superseded `Devflow Review`) is excluded even off-app, defensively.
  _checks_err=$(mktemp 2>/dev/null) || _checks_err=/dev/null
  if ! CHECKS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/commits/$HEAD_SHA/check-runs" 2>"$_checks_err"); then
    echo "derive-review-preconditions: check-runs query failed for $HEAD_SHA ($(gh_err_detail "$_checks_err")) — other-CI state unverifiable; failing closed (unverifiable)." >&2
    [ "$_checks_err" = /dev/null ] || rm -f "$_checks_err"
    emit false unverifiable
  fi
  [ "$_checks_err" = /dev/null ] || rm -f "$_checks_err"
  if ! EXT_LINES=$(printf '%s' "$CHECKS_JSON" | "$DEVFLOW_JQ" -rs \
        'map(.check_runs // []) | add // [] | map(select(((.app.slug // "") != "github-actions") and ((.name // "") != "PRFlow Review") and ((.name // "") != "Devflow Review"))) | .[] | ((.status // "") + "|" + (.conclusion // ""))' 2>/dev/null); then
    echo "derive-review-preconditions: check-runs payload could not be parsed (jq failed or a non-object page) — failing closed (unverifiable)." >&2
    emit false unverifiable
  fi
  if [ -n "$EXT_LINES" ]; then
    OTHER_SIGNALS=1
    gate_signal_lines "$EXT_LINES" "an external check run"
  fi

  if [ "$OTHER_SIGNALS" = "0" ]; then
    echo "derive-review-preconditions: no other CI signal exists for $HEAD_SHA (no non-self workflow runs, no commit statuses, no external check runs) — CI-green precondition satisfied; a CI-less repo is reviewed, never wedged." >&2
  fi
fi

emit true ""

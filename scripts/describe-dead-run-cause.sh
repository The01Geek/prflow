#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# describe-dead-run-cause.sh — render the cause clause the dead-run
# review-progress backstop writes into the pull request's progress comment
# (issue #1154).
#
# Why a helper rather than an inline `if`/`else` in devflow.yml: this clause IS
# the diagnosis a maintainer reads off a dead run, so a silently mis-selected
# arm (a reordered chain, a typo in a comparison) defeats the feature while the
# workflow still "works". Inline shell inside YAML cannot be unit-tested; here
# lib/test/modules/review-trigger-helpers.sh drives every arm — and the arm
# ORDER — directly. Same class, and the same extraction, as
# scripts/describe-denial-count.sh (issue #363).
#
# The workflow has exactly two observables about how a run ended: the `claude`
# step's RAW outcome (`steps.claude.outcome`, before continue-on-error), and the
# engine's own `is_error`, parsed out of the execution log AFTER the step by
# scripts/parse-engine-error.sh. Those two partition the run-end space into the
# four modes below, which is why the caller no longer gates on them: it always
# runs the backstop and passes both values here to be named.
#
#   claude outcome   is_error   mode
#   ------------------------------------------------------------------
#   success          true       the engine ended in error while the step
#                               still reported success
#   success          not true   the step exited cleanly and the engine
#                               reported no error — yet no verdict was
#                               written (the run-29854795625 mode: Phase 0
#                               permission denials, no output, clean exit)
#   failure          any        the job failed
#   cancelled        any        the run was cancelled
#
# ARM ORDER IS LOAD-BEARING. The engine-error arm is tested BEFORE the
# clean-exit arm: both match `outcome == success`, and swapping them would
# report a run whose engine explicitly errored as "no verdict, no error" —
# steering the reader away from the cause the workflow already measured. Every
# later arm is keyed on a non-success outcome, so it cannot collide with either.
#
# A raw outcome outside {success, failure, cancelled} — `skipped`, or an empty
# value when the step never ran at all — is a RESIDUAL, not a fifth mode: it is
# named verbatim by the trailing arm, preserving the wording the inline chain
# this helper replaces produced for every non-success outcome.
#
# The diagnostics step (scripts/surface-execution-diagnostics.sh) publishes a
# nine-field cause set read from the execution file. This helper reads those
# values from the environment (positional operands unchanged) and, when one is
# PRESENT, names the engine's own reason ahead of the two-operand clause. PRESENT
# means a real value once CR is stripped: the empty string, the literal
# `unavailable` (absent source), the renderer's own `n/a`, and the literal `null`
# (a key present with a JSON null) are all NOT present, so a run whose whole cause
# set is unavailable falls through to the clause below. The recovery arm shares
# this test, so a runner name or annotation that is exactly `n/a` renders
# `unavailable` too. Precedence, first present wins:
#   1. RATE_LIMIT_TYPE  — a rejected rate-limit event; names the limit type and
#      the raw RATE_LIMIT_RESETS_AT as recorded (no date conversion).
#   2. TERMINAL_REASON  — names it with SUBTYPE and API_ERROR_STATUS.
#   3. API_RETRY_ERROR  — names it with API_RETRY_STATUS.
# The named-alongside values (resetsAt, subtype, api_error_status, api_retry
# status) are printed as recorded, so `null`/`unavailable` surface verbatim.
#
# DEAD_RUN_TIER selects the two-operand wording: on the implement tier the
# engine-error and clean-exit clauses are reworded (the review call sites set no
# DEAD_RUN_TIER and print the review clauses). The clause is capped at 200 chars.
#
# Usage: describe-dead-run-cause.sh [CLAUDE_OUTCOME] [ENGINE_IS_ERROR]
#   CLAUDE_OUTCOME    the raw `steps.claude.outcome` value, or empty.
#   ENGINE_IS_ERROR   the `steps.engine.outputs.is_error` value; only the exact
#                     literal `true` counts as an engine error (mirroring the
#                     producer, which normalizes anything else to `false`).
# Prints one clause to stdout. Always exits 0 — the backstop that consumes this
# must never change the invoking job's pass/fail result.

set -u

CLAUDE_OUTCOME="${1:-}"
ENGINE_IS_ERROR="${2:-}"

# An absent sentinel must not select a richer arm, or a dead run would name a cause
# it never measured, such as `rate-limited (n/a)`.
_present() {
  case "${1//$'\r'/}" in
    "" | unavailable | n/a | null) return 1 ;;
    *) return 0 ;;
  esac
}

# Recovery arm (issue #600): a NEW LEADING precedence rung for the Spot-reclaim
# recovery job's cause line — keep it ahead of the arms below, which it must not
# reorder. The annotation is attacker-controlled text GitHub reported: render it
# inert single-line here (an embedded newline would break the comment's first-line
# marker / last-line trigger contract; a raw `<!--` could forge a marker) before it
# reaches any comment.
if _present "${RECOVERY_JOB_CONCLUSION:-}"; then
  RCONCLUSION="$RECOVERY_JOB_CONCLUSION"
  RCAPACITY="${RECOVERY_CAPACITY_TOKEN:-unknown}"
  [ -n "$RCAPACITY" ] || RCAPACITY="unknown"
  if _present "${RECOVERY_RUNNER_NAME:-}"; then RRUNNER="$RECOVERY_RUNNER_NAME"; else RRUNNER="unavailable"; fi
  if _present "${RECOVERY_ANNOTATION_MESSAGE:-}"; then RMESSAGE="$RECOVERY_ANNOTATION_MESSAGE"; else RMESSAGE="unavailable"; fi
  # Inert single-line rendering — bash parameter expansion only, no un-guaranteed
  # tool. Replacements target disjoint literals, so their order does not matter.
  RMESSAGE="${RMESSAGE//$'\r'/}"
  RMESSAGE="${RMESSAGE//$'\n'/ }"
  RMESSAGE="${RMESSAGE//\`/[backtick]}"
  RMESSAGE="${RMESSAGE//\$/[dollar]}"
  RMESSAGE="${RMESSAGE//<!--/[html-comment]}"
  RPREFIX="claude job ${RCONCLUSION}, capacity ${RCAPACITY}, runner ${RRUNNER}, annotation: "
  RFULL="${RPREFIX}${RMESSAGE}"
  if [ "${#RFULL}" -le 200 ]; then
    CLAUSE="$RFULL"
  else
    # Only the message is shortened; conclusion/capacity/runner stay in full. The
    # budget floors at 20 of the message's own chars — when the fixed facts alone
    # already fill the line the clause prints over 200 rather than cutting the
    # message below its floor (AC precedence).
    rbudget=$(( 200 - ${#RPREFIX} - 3 ))
    [ "$rbudget" -ge 20 ] || rbudget=20
    CLAUSE="${RPREFIX}${RMESSAGE:0:rbudget}..."
  fi
  SKIP_GENERIC_CAP=true
elif _present "${RATE_LIMIT_TYPE:-}"; then
  CLAUSE="rate-limited (${RATE_LIMIT_TYPE}); resets at ${RATE_LIMIT_RESETS_AT:-unavailable}"
elif _present "${TERMINAL_REASON:-}"; then
  CLAUSE="engine terminated: ${TERMINAL_REASON} (subtype ${SUBTYPE:-unavailable}, api_error_status ${API_ERROR_STATUS:-unavailable})"
elif _present "${API_RETRY_ERROR:-}"; then
  CLAUSE="api retry failed: ${API_RETRY_ERROR} (status ${API_RETRY_STATUS:-unavailable})"
elif [ "$ENGINE_IS_ERROR" = "true" ] && [ "$CLAUDE_OUTCOME" = "success" ]; then
  if [ "${DEAD_RUN_TIER:-}" = "implement" ]; then
    CLAUSE="engine ended with an error (is_error)"
  else
    CLAUSE="review engine ended with an error (is_error)"
  fi
elif [ "$CLAUDE_OUTCOME" = "success" ]; then
  if [ "${DEAD_RUN_TIER:-}" = "implement" ]; then
    CLAUSE="claude step success and the engine reported no error"
  else
    CLAUSE="claude step success but the run wrote no verdict (engine reported no error)"
  fi
elif [ "$CLAUDE_OUTCOME" = "failure" ]; then
  CLAUSE="claude step failure"
elif [ "$CLAUDE_OUTCOME" = "cancelled" ]; then
  CLAUSE="claude step cancelled"
elif [ -z "$CLAUDE_OUTCOME" ]; then
  CLAUSE="claude step outcome unavailable"
else
  CLAUSE="claude step ${CLAUDE_OUTCOME}"
fi

# A present value is printed as recorded, so drop any CR an older renderer left on
# it (issue #1121): a CR would split the one-line clause.
CLAUSE="${CLAUSE//$'\r'/}"

# Cap at 200 characters (AC): a bounded clause keeps the comment line and the
# progress line legible. `${var:0:200}` is a bash builtin — no un-guaranteed tool.
# The recovery arm above owns its own bounded truncation (only the annotation
# message is shortened), so a blind tail-clip here would cut the runner name it
# guarantees in full; it sets SKIP_GENERIC_CAP to keep its already-bounded clause.
if [ "${SKIP_GENERIC_CAP:-false}" = "true" ]; then
  printf '%s\n' "$CLAUSE"
else
  printf '%s\n' "${CLAUSE:0:200}"
fi
exit 0

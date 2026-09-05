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
# means a real value: the empty string, the literal `unavailable` (absent source),
# and the literal `null` (a key present with a JSON null) are all NOT present, so
# a run whose whole cause set is unavailable falls through to the clause below
# exactly as before this change. Precedence, first present wins:
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

# A cause-set value counts only when it carries a real reason: the absent sentinel
# `unavailable` and a present JSON `null` must not select a richer arm, or a run
# with no cause set would name a `null` cause instead of the two-operand clause.
_present() {
  case "$1" in
    "" | unavailable | null) return 1 ;;
    *) return 0 ;;
  esac
}

if _present "${RATE_LIMIT_TYPE:-}"; then
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

# Cap at 200 characters (AC): a bounded clause keeps the comment line and the
# progress line legible. `${var:0:200}` is a bash builtin — no un-guaranteed tool.
printf '%s\n' "${CLAUSE:0:200}"
exit 0

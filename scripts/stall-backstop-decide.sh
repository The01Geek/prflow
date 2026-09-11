#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# stall-backstop-decide.sh — pure decision function for the cloud /devflow:implement
# stall backstop (issue #266).
#
# A headless single-shot claude-code-action run can end mid-lifecycle (e.g. right
# after `gh pr create`) yet report success, because the SDK session ends the
# moment the model emits a tool-call-free turn. The workflow-level backstop keys
# on the issue workpad Status to detect that and either auto-resume or fail loud.
# This helper is the decision *core*, deliberately extracted from the workflow
# YAML so lib/test/run.sh can drive every branch deterministically with stubbed
# inputs — it does NO I/O (no gh/jq/workpad.py), just maps inputs to a decision.
#
# Usage: stall-backstop-decide.sh ENABLED CLASS ATTEMPTS MAX [JOB_STATUS] [CLAUDE_OUTCOME]
#   ENABLED   The resolved `stall_backstop.enabled` config value. Only the exact
#             string "false" disables the backstop; every other value (empty,
#             "true", an unrecognized string) resolves to enabled — the safe,
#             honest-failure direction the issue mandates.
#   CLASS     The workpad status class from `workpad.py status`. Since issue
#             #1025 each terminal glyph has its OWN token (the old collapse to a
#             single `terminal` made 👎 Blocked indistinguishable from 🎉
#             Complete, so a blocked run concluded `success`):
#               complete      — 🎉 Complete (the healthy end; -> noop, green)
#               blocked       — 👎 Blocked (a decided non-success end; issue
#                               #1025 -> fail-blocked, concludes the job non-
#                               `success`. No resume.)
#               failed        — 💥 Failed (written by the workflow's own dead-run
#                               flip, issue #356; also a non-success end ->
#                               fail-blocked)
#               cancelled     — 🛑 Cancelled (written by the cancelled-run flip,
#                               issue #498; a STALE read on a non-cancelled job
#                               stays noop — never converted to a failure, AC4)
#               terminal      — the LEGACY collapsed token an un-upgraded
#                               workpad.py emits; kept as a backward-compatible
#                               alias -> noop, so an upgrade skew fails toward the
#                               old green-on-terminal behavior
#               interim       — 🚀 any in-progress phase (a stall)
#               unreadable    — no workpad, or its Status could not be parsed
#               auth-failure  — a gh-api / transport / auth error (e.g. an
#                               expired App token) while reading the workpad
#                               Status or the comment list. Distinct from
#                               "unreadable": the workpad may be perfectly
#                               healthy — the READ failed, not the content.
#             (the workflow passes "unreadable" when `workpad.py status` exits 1
#             or 2, and "auth-failure" when it exits 3 or the comment-count
#             fetch fails on transport/auth grounds.) Any other/unknown token is
#             treated as unreadable.
#   ATTEMPTS  How many automatic resume attempts have already been made for this
#             issue (>=0). A non-integer resolves to 0 (fail toward attempting a
#             resume, not toward a spurious exhaustion).
#   MAX       The resolved `stall_backstop.max_resume_attempts` cap. A negative
#             or non-integer value resolves to the default 2. 0 is honored
#             verbatim (detect-and-fail-loud only, no auto-resume).
#   JOB_STATUS The job's status (issue #498), typically `${{ job.status }}` —
#             one of `success` / `failure` / `cancelled`. Absent (a four-arg
#             caller) or any value other than the exact string `cancelled` leaves
#             the decision table byte-identical to the pre-#498 behavior (fail
#             toward resume, so an un-upgraded caller never suppresses a resume).
#             Only `cancelled` selects the cancellation-exclusion path below.
#   CLAUDE_OUTCOME The `steps.claude.outcome` value, passed ONLY when
#             `stall_backstop.defer_to_runner_retry` is true (issue #305). The
#             exact string `failure` defers an interim workpad to the runner's own
#             retry of the failed job (RunsOn `retry=when-interrupted` re-runs a
#             `failure`, so a PRFlow resume would double-drive the issue); every
#             other value — absent, empty, `success`, `cancelled` (which no runner
#             retries), `skipped`, any other token — keeps the resume/fail-exhausted
#             table byte-identical, so a consumer without the key sees no change.
#
# Prints exactly one decision token to stdout and exits 0:
#   skip             backstop disabled            → do nothing, job stays green
#   noop             complete/cancelled/legacy-terminal → do nothing (healthy or
#                    non-failure end; job stays green)
#   fail-blocked     blocked/failed terminal      → conclude the job non-`success`
#                    (issue #1025) so a run that produced no branch/PR is visible
#                    in `gh run list`; NO resume, NO workpad re-flip (👎/💥 are
#                    already truthful terminal statuses)
#   resume           interim + ATTEMPTS < MAX + CLAUDE_OUTCOME not `failure`
#                    → audit comment + re-dispatch
#   defer            interim + CLAUDE_OUTCOME `failure` (issue #305) → the runner
#                    retries the failed job itself: NO auto-resume, no resume
#                    attempt consumed, workpad left interim; the workflow posts one
#                    informational comment and exits green
#   fail-exhausted   interim + ATTEMPTS >= MAX     → comment + fail the job
#                    (includes MAX=0: 0 >= 0)
#   fail-unreadable  status unreadable/unknown    → diagnostic comment + fail
#   fail-auth        gh-api/transport/auth failure → auth-specific comment + fail
#                    (fails loud WITHOUT consuming a resume attempt; never
#                    mislabeled 'unreadable')
#   flip-cancelled   JOB_STATUS=cancelled + interim → workflow flips the workpad
#                    to 🛑 Cancelled, posts no comment, consumes no resume
#                    attempt, exits 0 (issue #498: a cancel is a decided end)
#   skip-cancelled   JOB_STATUS=cancelled + unreadable/auth-failure/unknown →
#                    log + exit 0, no fail-loud diagnostic comment (issue #498)
set -uo pipefail

enabled="${1-}"
cls="${2-}"
attempts="${3-}"
max="${4-}"
job_status="${5-}"
claude_outcome="${6-}"

# Disabled only on the exact literal "false"; anything else (missing key handed a
# default by config-get, "true", or an unrecognized string) resolves to enabled.
if [ "$enabled" = "false" ]; then
  echo skip
  exit 0
fi

# Cancelled-run exclusion (issue #498): a cancelled run is a decided ending, not
# a stall. Only the exact string "cancelled" selects this path; every other value
# (absent, empty, "success", "failure", any other token) falls through to the
# existing decision table byte-identical — so an un-upgraded caller (four args,
# or a non-cancelled job status) never suppresses a resume. The mapping (complete
# by construction — the unknown-class fold closes the class space): any decided
# terminal class (complete/blocked/failed/cancelled, or the legacy `terminal`
# token — issue #1025) → noop; interim → flip-cancelled (the workflow flips the
# workpad to 🛑 Cancelled); unreadable/auth-failure/unknown → skip-cancelled
# (log + green, no fail-loud diagnostic on a cancel). The master switch above
# already returned `skip` for ENABLED=false, so it wins before this path.
if [ "$job_status" = "cancelled" ]; then
  case "$cls" in
    complete|blocked|failed|cancelled|terminal)
      # Any decided terminal end (issue #1025's widened vocabulary, or the
      # legacy collapsed 'terminal' token) on a cancelled job is a noop — the
      # run's own `cancelled` conclusion in the Actions UI is the record, and a
      # decided end is not re-flipped. Byte-identical to the pre-#1025 terminal
      # -> noop arm; the new tokens simply join it.
      echo noop
      ;;
    interim)
      echo flip-cancelled
      ;;
    *)
      # unreadable, auth-failure, and any unknown class all take skip-cancelled
      # (inheriting the unreadable|* fold below — an unknown class is treated as
      # unreadable). No resume attempt is consumed; the workflow logs and exits 0.
      echo skip-cancelled
      ;;
  esac
  exit 0
fi

# Sanitize the numeric inputs. A non-integer attempt count → 0; a non-integer or
# negative cap → the documented default of 2 (the `^[0-9]+$` test rejects a
# leading "-", so "-1" falls back).
[[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0
[[ "$max" =~ ^[0-9]+$ ]] || max=2

case "$cls" in
  complete|cancelled|terminal)
    # 🎉 Complete concludes the job `success` (green — the healthy end). A STALE
    # 🛑 Cancelled read here means job.status is NOT cancelled (the cancel path
    # above did not fire) but the workpad still reads Cancelled from a prior
    # attempt — issue #1025 AC4 forbids converting that to a failure, so it stays
    # noop. 'terminal' is the legacy collapsed token an un-upgraded workpad.py
    # emits (issue #1025 widened the vocabulary); it too stays noop, so an
    # upgrade skew fails toward the old green-on-terminal behavior.
    echo noop
    ;;
  blocked|failed)
    # A terminal end that is NOT 🎉 Complete and NOT a cancel (issue #1025): 👎
    # Blocked or 💥 Failed. These conclude the job non-`success` so a run that
    # produced no branch/PR is visible in `gh run list` without opening the
    # workpad. No resume — this is a decided end, not a stall (no collision with
    # the interim resume arm). The workflow does NOT re-flip the workpad here:
    # its flip_to_failed guard is CLASS=interim, so 👎/💥 are left truthful.
    echo fail-blocked
    ;;
  interim)
    # Issue #305: only the exact `failure` defers — it is the one conclusion a
    # runner retry re-runs; deferring on `cancelled` would strand the run the
    # #261 reclaim path exists to resume. Precedes the cap: no attempt consumed.
    if [ "$claude_outcome" = "failure" ]; then
      echo defer
    elif [ "$attempts" -ge "$max" ]; then
      echo fail-exhausted
    else
      echo resume
    fi
    ;;
  auth-failure)
    # A gh-api/transport/auth failure reading the workpad — NOT a corrupt
    # workpad. Fail loud with a distinct decision so the workflow emits an
    # auth-specific breadcrumb and never burns a resume attempt on a workpad it
    # never actually read. Placed before the wildcard so it isn't swallowed.
    echo fail-auth
    ;;
  unreadable|*)
    # 'unreadable' is the workflow's explicit "no workpad / unparseable Status"
    # token; any OTHER unexpected class is an unknown state treated the same way
    # — fail closed rather than silently no-op'ing on something we can't classify
    # (never pass on an unknown status).
    echo fail-unreadable
    ;;
esac
exit 0

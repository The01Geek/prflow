#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# decide-verdict-gap-job-status.sh ARM REVIEW_CLASS CANCELLED — decide whether the
# Phase 4.4 verdict-emitter reach-record step should FAIL its job or leave the job
# status unchanged (issue #1271).
#
# THE QUESTION IT ANSWERS. A standalone `/prflow:review` run that reaches a verdict,
# publishes it as an ordinary pull-request comment it composed itself, exits `success`,
# and never reaches Phase 4.4 leaves the reviews API empty for the reviewed head — so
# no merge-gate consumer can see the verdict. That gap is already MEASURED by the
# reach-record step (scripts/check-verdict-post-reached.sh → describe-verdict-post-gap.sh
# → an `ARM …` token) and, since issue #1250, corroborated by the head-scoped review
# oracle (scripts/classify-head-reviews.sh → a REVIEW_CLASS token). What was missing was
# a JOB STATUS: the step ended in an unconditional `exit 0`, so a verdict-less run still
# concluded `success` and the gap was laundered. This helper owns the arm-to-job-status
# decision so the workflow step's only remaining job is to exit with the status it
# reports — no branch-selecting `if`/`case` chain deciding job status is left inline in
# devflow.yml, where the suite cannot drive it (the workflow is inert inside its own
# pull request; these triggers run it from the default branch).
#
# CONTRACT — exactly one stdout line, always exit 0:
#
#   FAIL <reason>   the job should conclude `failure`: the emitter was not reached AND
#                   the head-scoped oracle POSITIVELY established that no verdict exists
#                   for the reviewed head.
#   PASS <reason>   the job status is left unchanged (the step then ends in `exit 0`).
#
# Always exit 0 — the decision is the STDOUT TOKEN, never this helper's own exit code.
# The one consumer is an `always()` post-run workflow step; the step reads the token and
# itself exits 1 on FAIL, 0 otherwise. Keeping the decision in stdout (not the exit code)
# is what lets the suite drive every arm without the step's own control flow leaking the
# verdict.
#
# THE GATE IS CONJUNCTIVE, and the second conjunct must be POSITIVELY-ESTABLISHED
# ABSENCE — never a "could not tell". `classify-head-reviews.sh` reports established
# absence (`none`) and inability-to-establish (`unestablished <reason>`) as DISTINCT
# answers; only `none` fires the gate. This honours CLAUDE.md's "unknown is not zero":
# `dead-run-verdict-present.sh` is unusable here precisely because it is two-valued and
# merges the two, so every one of derive-review-verdict.sh's seventeen fail-closed
# conditions would become a red job. Under this helper, an `unestablished`/`marked`/
# `unmarked`/empty oracle answer NEVER fires the gate.
#
# COMPLETENESS RESIDUAL OF THE CHOSEN ORACLE (stated, not glossed). classify-head-reviews.sh
# reads the REVIEWS API only, so it is blind to post-review-verdict.sh's progress-comment
# FALLBACK channel: a run whose review POST was refused and whose verdict survives only in
# the run-keyed `prflow:review-progress` comment classifies `none` there. Such a run has a
# reachable verdict this helper would nonetheless grade FAIL. The trade is deliberate: the
# alternative oracle (dead-run-verdict-present.sh) covers both channels but cannot separate
# absence from ignorance, which would fire the gate on seventeen unknowns — a worse
# failure. Neither oracle is complete alone; this one is chosen because its false-positive
# population (verdict-in-progress-comment-only) is far smaller than the other's (every
# unknown), and because a run that could not POST its review to the reviews API has a real
# defect worth a red job regardless.
#
# THE CANCELLATION CARVE-OUT is an ARGUMENT, not a step-level `if: !cancelled()` — a step
# condition would stop the step running at all on a cancelled run, removing its `::notice::`,
# `::warning::` and cause-naming comment. A cancelled run legitimately never reaches Phase
# 4.4, so CANCELLED == true short-circuits to PASS before the conjuncts are evaluated.
#   UNVERIFIED PREMISE / POSSIBLY-VACUOUS CARVE-OUT (issue #1271, stated per its AC): the
#   carve-out assumes GitHub would otherwise conclude `failure` on a cancelled job in which
#   a later always() step exits non-zero. That was NOT established — across every cancelled
#   PRFlow run sampled in this repository the command job contained zero failed steps, so
#   the behaviour could not be observed. IF GitHub keeps a cancelled job `cancelled`
#   regardless of a later exit 1, this carve-out is VACUOUS (it changes nothing observable).
#   It is retained anyway because it is correct and harmless either way: this helper never
#   WANTS a cancelled run to go red, so returning PASS on cancelled can only ever match or
#   improve on GitHub's own behaviour, never contradict a decision the gate should make.
#
# TWO NON-DEFECT NON-REACHING STATES, and their decided dispositions (issue #1271 AC —
# each stated here rather than left implicit):
#
#   * Engine is_error=true on a CLEAN-EXIT run. dead-run-verdict-present.sh would short to
#     absent here, but this helper does not consult it — it reads the reach record and the
#     reviews oracle. An is_error run that errored before Phase 4.4 records ARM not-reached,
#     and if it ALSO left no review on the head the oracle answers `none`, so the gate FIRES.
#     DISPOSITION: the gate is ALLOWED to fire. Such a run is genuinely verdict-less, so a
#     red job is correct. It is acknowledged that this run ALSO trips the #408 auto-resume
#     backstop (whose if: includes is_error == 'true'), producing a DOUBLED response — a red
#     job plus an auto-resume comment — to one event. That doubling is accepted, not a bug:
#     the two responses serve different readers (a human sees the red job; the backstop
#     retries the run), and neither suppresses the other. If a future change wants to
#     de-duplicate, it belongs in the workflow's step gating, not in this helper's contract.
#
#   * Phase 4.4's sanctioned "no output at all" fallback arm. phase-4-4-github-post.md
#     instructs the agent to read the emitter producing no output as a harness refusal,
#     route to the fallback arm, and post the full report with `gh pr comment` — FORBIDDEN
#     from composing a verdict marker. On that path no receipt is written (ARM not-reached)
#     and nothing marks the comment (the oracle answers `none` when no reviews-API review
#     exists). So the gate FIRES on a run that followed the documented procedure exactly.
#     DISPOSITION: the gate is ALLOWED to fire. The verdict really is unreadable by every
#     merge-gate consumer on that path, which is the exact condition this gate exists to make
#     loud; that the agent reached it by a sanctioned route does not make the verdict
#     readable. Failing loud is the correct, recorded answer.
#
# EVERY "COULD NOT TELL" ARM KEEPS TODAY'S WARNING AND LEAVES THE JOB STATUS UNCHANGED.
# The reach-record arm vocabulary is closed (describe-verdict-post-gap.sh): reached,
# not-reached, unestablished, no-line, unrecognized-line. Only `not-reached` can reach the
# second conjunct; `reached` is a discharged emitter, and `unestablished`/`no-line`/
# `unrecognized-line` each mean the reach question itself could not be settled — every one
# of them is PASS. The "check-helpers-absent" path (an older vendored tree) never reaches
# this helper: the workflow's own guard exits 0 before invoking it. And when THIS helper is
# itself absent from an older vendored tree, the workflow warns and leaves the job unchanged
# (a separate DECIDE-absent guard in the step). So no arm meaning "could not tell" fires the
# gate.
#
# Selection values are derived with bash builtins only (`case`, `[`, parameter expansion) —
# never `tr`/`sed`/`cut`/`wc`, which lib/preflight.sh does not guarantee and whose absence
# would empty a value and select the wrong arm (CLAUDE.md guard-class 2).
#
# Usage: decide-verdict-gap-job-status.sh ARM REVIEW_CLASS CANCELLED
#   ARM           the reach-record arm token WITHOUT the "ARM " prefix, i.e. one of
#                 reached | not-reached | unestablished | no-line | unrecognized-line.
#                 Any other value is treated as a could-not-tell arm and passes.
#   REVIEW_CLASS  classify-head-reviews.sh's single line: none | marked | unmarked <id>… |
#                 unestablished <reason> | (empty on an older deployment / no classify).
#   CANCELLED     the job's cancelled() state as the literal `true` or `false`; anything
#                 other than exactly `true` is treated as not-cancelled.
set -u

ARM="${1:-}"
REVIEW_CLASS="${2:-}"
CANCELLED="${3:-}"

# The oracle's KIND is its first whitespace-delimited token, so `unestablished <reason>`
# and `unmarked <id>…` reduce to `unestablished` / `unmarked`. Only the bare `none`
# positively establishes absence.
RC_KIND="${REVIEW_CLASS%% *}"

# (1) Cancellation carve-out — evaluated before the conjuncts. Exactly `true` is
#     cancelled; any other value (including empty) is not.
if [ "$CANCELLED" = "true" ]; then
  echo "PASS cancelled"
  exit 0
fi

# (2) First conjunct: only a not-reached emitter can fire the gate. Every other arm —
#     reached, unestablished, no-line, unrecognized-line, or any unrecognized token — is a
#     discharged or could-not-tell arm and passes.
if [ "$ARM" != "not-reached" ]; then
  echo "PASS arm-$ARM"
  exit 0
fi

# (3) Second conjunct: the head-scoped oracle must POSITIVELY establish absence. Only the
#     bare `none` does; marked/unmarked/unestablished/empty all leave the status unchanged.
if [ "$RC_KIND" = "none" ]; then
  echo "FAIL established-absence"
  exit 0
fi

echo "PASS not-reached-oracle-$RC_KIND"
exit 0

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# check-verdict-post-reached.sh [RECEIPT_PATH] — reduce the Phase 4.4 verdict-post
# receipt to ONE line from a closed three-token vocabulary (issue #1156).
#
# THE QUESTION IT ANSWERS. A standalone `prflow:review` run that never reaches Phase
# 4.4 exits `success` with a published-looking verdict and an untouched reviews API.
# scripts/post-review-verdict.sh writes a run-scoped receipt (lib/verdict-receipt.sh)
# on every path that emits an outcome line, so the receipt's PRESENCE answers "was the
# emitter reached", and its first line answers "with which outcome" — including every
# refusal outcome, which is issue #1059's territory and stays there.
#
# CONTRACT — exactly one stdout line, always exit 0:
#
#   REACHED <outcome line>    the emitter ran; <outcome line> is its own closed-vocabulary
#                             outcome, whitespace-trimmed at the right
#   NOT-REACHED               NO RECEIPT EXISTS. That is the observation, and it has two
#                             causes: the emitter did not run, or it ran and its
#                             best-effort receipt write failed (post-review-verdict.sh's
#                             own KNOWN RESIDUAL, whose only other trace is a
#                             `could not write the verdict-post receipt` stderr
#                             breadcrumb in the job log). A consumer that turns this
#                             token into a public statement must name both causes rather
#                             than assert the first — scripts/describe-verdict-post-gap.sh
#                             is the consumer that does.
#   UNESTABLISHED <reason>    the question could not be settled; <reason> is one closed
#                             token from the list below
#
# Always exit 0 because the only caller is an `always()` post-run workflow step that
# must never change its job's pass and never change its fail.
#
# UNESTABLISHED IS NOT NOT-REACHED, and collapsing the two is the regression this
# helper exists to refuse. CLAUDE.md's "unknown is not zero" rule has a named prior
# instance in this repository: `permission_denials_count` published `0` for a run it
# never measured, so a no-verdict annotation asserted "the harness refused 0 commands"
# about a measurement that never happened, steering the reader away from the cause. A
# receipt that cannot be READ is exactly that shape — reporting it as NOT-REACHED would
# accuse a run of skipping Phase 4.4 on no evidence, and would do it in a comment
# posted to the pull request.
#
# REASON VOCABULARY (closed; every arm below emits one of these and nothing else):
#
#   receipt-path-unresolved       the receipt path could not be composed at all
#   receipt-path-is-a-directory   a directory sits at the receipt path
#   receipt-unreadable            the receipt exists but is not readable
#   receipt-empty                 the receipt exists and is zero bytes
#   receipt-read-failed           the read was attempted and failed
#   receipt-blank-first-line      the first line carries no non-whitespace
#   receipt-unrecognized-outcome  the first line is outside the producer's vocabulary
#
# The reasons are CLOSED TOKENS and never quote the receipt's bytes. The caller renders
# a reason into a `::warning::` and, on the not-reached arm, into a pull-request
# comment; a reason that embedded the offending bytes would carry whatever the receipt
# contained onto those surfaces — including a `::warning::`/`##[…]` workflow command.
# Naming the SHAPE keeps every emitted surface free of receipt-derived bytes, which is
# a stronger guarantee than quoting them carefully.
#
# ACCEPTED OUTCOME LINES. The producer's outcome vocabulary is closed and so is the
# event set it can name (`REQUEST_CHANGES`, `APPROVE`, `COMMENT` — the only three its
# verdict-token `case` maps to), so the `POSTED`/`SKIP` lines are matched as EXACT
# literals rather than by prefix. `FAILED no-durable-channel` is the one arm whose
# tail is free text (a captured API error), so it alone is matched by prefix. Exactness
# is what makes a near-miss — `POSTED reviews`, `POSTED  review`, `posted review`, a
# line with a payload appended after a valid token — take the UNESTABLISHED arm instead
# of being read as a reached emitter.
#
# ARM ORDER IS LOAD-BEARING, and three pairs in particular:
#
#   * absent BEFORE zero-byte. `[ ! -s ]` is TRUE for a file that does not exist, so an
#     emptiness test placed first would answer `UNESTABLISHED receipt-empty` for every
#     run that genuinely never reached the emitter — silencing the one arm that posts.
#   * zero-byte BEFORE blank-first-line. A zero-byte receipt also has a blank first
#     line; the more specific cause is the one a maintainer can act on.
#   * blank-first-line BEFORE unrecognized-outcome. A blank line is also outside the
#     vocabulary; reporting it as `receipt-unrecognized-outcome` would name a generic
#     cause where a specific one was measured.
#
# Every selection value is derived with bash builtins (`case`, `[ ]`, parameter
# expansion, `read`) and never through `tr`/`sed`/`wc`/`cut`/`head`, which
# lib/preflight.sh does not guarantee: a missing one does not fail, it yields an empty
# value and selects the wrong arm.
#
# Usage: check-verdict-post-reached.sh [RECEIPT_PATH]
#   RECEIPT_PATH  optional override; defaults to lib/verdict-receipt.sh's path.
set -u

_CVR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/verdict-receipt.sh
if ! . "$_CVR_DIR/../lib/verdict-receipt.sh"; then
  # A partially copied deployment leaves the path unresolvable. That is precisely an
  # UNESTABLISHED, never a NOT-REACHED: nothing about the run was observed.
  echo "devflow verdict-check: lib/verdict-receipt.sh could not be sourced — the receipt path cannot be composed" >&2
  echo "UNESTABLISHED receipt-path-unresolved"
  exit 0
fi

RECEIPT="${1:-}"
if [ -z "$RECEIPT" ]; then
  RECEIPT="$(devflow_verdict_receipt_path)"
fi
if [ -z "$RECEIPT" ]; then
  echo "UNESTABLISHED receipt-path-unresolved"
  exit 0
fi

# (1) A directory at the receipt path. Checked before the existence arm so the
# diagnosis names what is actually there; `-e` is true for a directory, so the
# existence arm alone would never reach this cause.
if [ -d "$RECEIPT" ]; then
  echo "UNESTABLISHED receipt-path-is-a-directory"
  exit 0
fi

# (2) ABSENT — the one arm that asserts the emitter did not run. `-e`, not `-f`: a
# non-regular file that exists was observed and is not an absence.
if [ ! -e "$RECEIPT" ]; then
  echo "NOT-REACHED"
  exit 0
fi

# (3) Present but the read is refused.
if [ ! -r "$RECEIPT" ]; then
  echo "UNESTABLISHED receipt-unreadable"
  exit 0
fi

# (4) Present and zero bytes — a partial or interrupted write, never an absence.
if [ ! -s "$RECEIPT" ]; then
  echo "UNESTABLISHED receipt-empty"
  exit 0
fi

# (5) Read the first line with the `read` builtin. A final line with no terminating
# newline makes `read` return non-zero while still assigning, so the `|| [ -n … ]` limb
# keeps that a successful read; a redirection that cannot open the file leaves the
# variable empty and fails both limbs, which is the read-failure arm.
CVR_FIRST=""
# Capture the status rather than negating the compound with `if ! { … } < "$RECEIPT"`:
# bash does not propagate a failed redirect on a compound command through `!` (issue #1524),
# so the negated form read a redirect that could not open "$RECEIPT" as success and this arm
# never fired. A redirection that cannot open the file leaves CVR_FIRST empty and fails both
# inner limbs, which is the read-failure arm.
cvr_read_rc=0
{ IFS= read -r CVR_FIRST || [ -n "$CVR_FIRST" ]; } < "$RECEIPT" 2>/dev/null || cvr_read_rc=$?
if [ "$cvr_read_rc" -ne 0 ]; then
  echo "UNESTABLISHED receipt-read-failed"
  exit 0
fi

# Trim a trailing carriage return and any trailing whitespace with parameter expansion
# (builtins). Leading whitespace is deliberately NOT trimmed: an indented first line is
# not something the producer writes, so accepting one would widen the vocabulary past
# what any producer path can emit.
CVR_LINE="${CVR_FIRST%$'\r'}"
while [ "$CVR_LINE" != "${CVR_LINE%[[:space:]]}" ]; do
  CVR_LINE="${CVR_LINE%[[:space:]]}"
done

# (6) Blank first line (whitespace-only, or a lone newline).
if [ -z "$CVR_LINE" ]; then
  echo "UNESTABLISHED receipt-blank-first-line"
  exit 0
fi

# (7) The producer's closed outcome vocabulary.
case "$CVR_LINE" in
  'POSTED review REQUEST_CHANGES'|'POSTED review APPROVE'|'POSTED review COMMENT'|\
  'POSTED comment REQUEST_CHANGES'|'POSTED comment APPROVE'|'POSTED comment COMMENT'|\
  'SKIP not-numeric'|'SKIP unknown-event'|'SKIP head-not-sha'|'SKIP body-file-unreadable'|\
  'SKIP evidence-missing'|\
  'FAILED no-durable-channel'|'FAILED no-durable-channel '*)
    echo "REACHED $CVR_LINE"
    exit 0 ;;
esac

# (8) Present, readable, non-blank — and outside the vocabulary. Nothing about the
# emitter is established, so this is never NOT-REACHED.
echo "UNESTABLISHED receipt-unrecognized-outcome"
exit 0

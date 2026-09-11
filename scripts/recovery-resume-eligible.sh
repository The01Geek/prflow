#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# recovery-resume-eligible.sh ATTEMPTS MAX ALREADY_RESUMED APP_TOKEN_PRESENT —
# pure resume-eligibility gate for the Spot-reclaim recovery job (issue #261,
# AC47/AC51/AC53/AC57). Decides whether a resume comment may be posted for this run
# attempt, so the cap + idempotency + App-token gating is suite-drivable rather than
# stranded as untestable inline workflow YAML. No I/O.
#
# The cap uses the EXISTING lifetime-attempt-cap semantics (AC53): a resume is
# refused at ATTEMPTS >= MAX — the same boundary stall-backstop-decide.sh's interim
# arm applies (attempts >= max → fail-exhausted), NOT the looser count > cap. So
# with MAX=2 and two prior resumes the recovery job posts no third resume (and never
# renders the nonsensical "auto-resume attempt 3 of 2").
#
# Prints exactly one token to stdout and exits 0 always (the caller routes on it):
#   post             every gate passed → post one capped resume comment
#   malformed        ATTEMPTS or MAX is not a non-negative base-10 integer (the
#                    attempt count was unknowable — e.g. a failed comment read)
#   at-cap           ATTEMPTS >= MAX → no resume (the existing lifetime cap, AC53)
#   already-resumed  a resume for this run attempt was already posted (AC51 idempotency)
#   no-app-token     no workflow-capable App token → a GITHUB_TOKEN-authored comment
#                    cannot re-trigger, so posting an inert resume is refused
set -uo pipefail

attempts="${1-}"
max="${2-}"
already_resumed="${3-}"
app_token_present="${4-}"

if ! [[ "$attempts" =~ ^[0-9]+$ ]] || ! [[ "$max" =~ ^[0-9]+$ ]]; then
  echo malformed
  exit 0
fi
if [ "$attempts" -ge "$max" ]; then
  echo at-cap
  exit 0
fi
if [ "$already_resumed" = "true" ]; then
  echo already-resumed
  exit 0
fi
if [ "$app_token_present" != "true" ]; then
  echo no-app-token
  exit 0
fi
echo post
exit 0

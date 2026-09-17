#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# recovery-resume-decide.sh OUTCOME JOB_STATUS CLASS [NEVER_STARTED] — pure router for the
# Spot-reclaim recovery job (issue #261, AC47/AC48/AC49/AC54). Maps the
# recovery-classify.sh outcome, the claude job status, and the workpad status class
# to one action token, so the routing is suite-drivable rather than stranded as
# untestable inline workflow YAML. No I/O.
#
# Prints exactly one token to stdout and exits 0 always (a pure predicate — the
# caller routes on the token):
#   noop                  NEVER_STARTED is exactly "true" (issue #471: the job was
#                         cancelled while queued behind the per-issue concurrency
#                         group, so the live sibling run owns the workpad); a
#                         human-cancel (never resumes, no state change, AC54); a
#                         reclaim on a non-interim workpad (AC47); a cancelled +
#                         unclassifiable on a non-interim workpad (AC48); or an
#                         unexpected/degraded combination — the safe default
#   resume-reclaim        reclaim + interim workpad → the capped resume path (AC47)
#   flip-cancelled        unclassifiable + cancelled + interim → flip the workpad to
#                         Cancelled through the existing writer (AC48/AC54)
#   failure-stall-decide  unclassifiable + failure → delegate to the existing
#                         stall-backstop-decide.sh decision table (AC49)
set -uo pipefail

outcome="${1-}"
job_status="${2-}"
cls="${3-}"
never_started="${4-}"
if [ "$never_started" = "true" ]; then
  echo noop
  exit 0
fi

case "$outcome" in
  human-cancel)
    echo noop
    ;;
  reclaim)
    if [ "$cls" = "interim" ]; then echo resume-reclaim; else echo noop; fi
    ;;
  unclassifiable)
    if [ "$job_status" = "cancelled" ]; then
      if [ "$cls" = "interim" ]; then echo flip-cancelled; else echo noop; fi
    elif [ "$job_status" = "failure" ]; then
      echo failure-stall-decide
    else
      echo noop
    fi
    ;;
  *)
    echo noop
    ;;
esac
exit 0

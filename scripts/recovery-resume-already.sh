#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# recovery-resume-already.sh COMMENTS_JSON_FILE AUDIT_MARKER AUDIT_MARKER_SUPERSEDED \
#                            ATTEMPT_MARK RUN_URL — pure per-run resume-idempotency
# scan for the Spot-reclaim recovery job (issue #261, AC51: at most one resume per
# run attempt). Reads the issue's comments (a JSON array of `{body}` objects, the
# `gh api .../comments` shape) from a file and decides whether a resume was ALREADY
# posted for this run. No network — the caller fetches the comments once and hands
# the file in, so the decision is suite-drivable.
#
# A resume was already posted for THIS run when EITHER:
#   (a) this recovery job's own run-attempt-bound marker (ATTEMPT_MARK) appears in
#       any comment body; OR
#   (b) the in-job stall backstop already posted a resume for THIS run — a comment
#       whose FIRST line is the audit marker (either spelling) AND whose body carries
#       this run's RUN_URL. Requiring RUN_URL to sit INSIDE an audit-marker comment
#       is what avoids a false match against the workpad, whose Run: line also carries
#       the URL.
#
# Prints exactly one token to stdout and exits 0 always (the caller routes on it):
#   already-resumed   a resume for this run attempt is already present → do not post
#   not-resumed       none found → the caller's other gates decide
#   unreadable        the comments file is missing/unreadable/not valid JSON — the
#                     caller fails toward no resume (treats this like already-resumed)
set -uo pipefail

file="${1-}"
marker="${2-}"
marker_superseded="${3-}"
attempt_mark="${4-}"
run_url="${5-}"

# jq via the single-source resolver (preflight-guaranteed); DEVFLOW_JQ still wins.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh"
: "${DEVFLOW_JQ:=$(devflow_resolve_jq)}"

if [ -z "$file" ] || [ ! -f "$file" ]; then
  echo unreadable
  exit 0
fi

n="$("$DEVFLOW_JQ" --arg m "$marker" --arg s "$marker_superseded" --arg a "$attempt_mark" --arg u "$run_url" '
  [ .[]
    | select(
        ((.body // "") | contains($a))
        or (
          (((.body // "") | gsub("\r"; "") | split("\n")[0]) as $f | ($f == $m or $f == $s))
          and ((.body // "") | contains($u))
        )
      )
  ] | length
' "$file" 2>/dev/null)" || { echo unreadable; exit 0; }

if ! [[ "$n" =~ ^[0-9]+$ ]]; then
  echo unreadable
  exit 0
fi
if [ "$n" != "0" ]; then
  echo already-resumed
else
  echo not-resumed
fi
exit 0

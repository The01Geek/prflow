#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# validate-attempt-count.sh COUNT CAP — pure shape+bound pre-gate for the
# Spot-reclaim recovery job's capped-resume path (issue #261, AC57).
#
# The recovery job must validate the attempt count and configured cap as
# non-negative base-10 integers BEFORE invoking stall-backstop-decide.sh, and a
# malformed count, malformed cap, or count above the cap must post no resume
# command and leave a specific breadcrumb. This helper is the decision core,
# extracted from the workflow YAML so the suite can drive its branches with no
# I/O — it does NO gh/jq/network, just maps two strings to one verdict token.
#
# Prints exactly one token to stdout and exits 0 always (a pure predicate, like
# recovery-classify.sh / stall-backstop-decide.sh — the caller routes on the token,
# never on an exit code):
#   ok              both well-formed AND count <= cap → proceed to the decision helper
#   malformed-count COUNT is not ^[0-9]+$ (empty, negative, non-numeric) — checked first
#   malformed-cap   COUNT well-formed but CAP is not ^[0-9]+$ — checked second, so a
#                   single malformed value reports deterministically
#   over-cap        both well-formed but COUNT > CAP (a count already at/over the cap
#                   posts no resume; equal is NOT over — 5 of 5 is the last allowed)
set -uo pipefail

count="${1-}"
cap="${2-}"

# Count checked before cap so exactly one deterministic token is emitted when both
# are malformed. `^[0-9]+$` rejects a leading "-"/"+" and an empty string, so a
# negative or empty value is malformed rather than silently coerced to 0.
if ! [[ "$count" =~ ^[0-9]+$ ]]; then
  echo malformed-count
  echo "validate-attempt-count: COUNT '$count' is not a non-negative base-10 integer" >&2
  exit 0
fi
if ! [[ "$cap" =~ ^[0-9]+$ ]]; then
  echo malformed-cap
  echo "validate-attempt-count: CAP '$cap' is not a non-negative base-10 integer" >&2
  exit 0
fi
if [ "$count" -gt "$cap" ]; then
  echo over-cap
  echo "validate-attempt-count: COUNT $count exceeds CAP $cap — no resume" >&2
  exit 0
fi
echo ok
exit 0

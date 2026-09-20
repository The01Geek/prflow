#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# recurring-targets.sh — emit the "Recurring intervention targets" view (issue
# #520): the files/areas the accumulated retrospectives.jsonl repeatedly points
# at via suggested_interventions[].candidate_targets[], grouped by exact target
# path across DISTINCT PRs.
#
# Report-only: reads an existing field, files no issue, writes no dismissal
# state. Mirrors lib/actionable-patterns.sh's argument-taking, jq-resolver shape.
#
# Usage:
#   bash lib/recurring-targets.sh <retrospectives.jsonl>
#
# Args:
#   $1  path to retrospectives.jsonl
#
# Output (stdout): compact JSON array of objects shaped as (see recurring-targets.jq):
#   {"target","pr_count","prs":[...],"representative_summary"}
#   for targets named in >= 2 distinct PRs, sorted by descending pr_count then
#   target ascending. The empty array [] when nothing recurs, or when the store
#   is empty/absent (fresh / consumer repo) — the loop then omits the section.
#
# Portability: no GNU-only flags. The grouping key is computed entirely inside jq
# (a preflight-guaranteed interpreter), never tr/sed/cut/wc (guard-class 2).

set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RETRO_FILE="${1:?usage: recurring-targets.sh <retrospectives.jsonl>}"

# If the retrospectives file doesn't exist yet (first run or empty scan), pipe an
# empty stream to jq rather than letting it error on a missing file — the reader
# then emits [] and the report section is omitted.
if [ -f "$RETRO_FILE" ] && [ -s "$RETRO_FILE" ]; then
  "$DEVFLOW_JQ" -c -s -f "$HERE/recurring-targets.jq" "$RETRO_FILE"
else
  printf '' | "$DEVFLOW_JQ" -c -s -f "$HERE/recurring-targets.jq"
fi

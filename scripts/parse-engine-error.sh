#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# parse-engine-error.sh — print "true" when the claude-code-action execution log
# indicates the review engine ended in error (is_error), else "false". Extracted
# out of devflow-runner.yml's "Surface review-engine execution result" step (issue
# #249) so this edge-case-prone parsing is unit-testable, exactly as the verdict
# derivation was extracted into derive-review-verdict.sh. That runner (since removed
# with its tier) exposed an engine_is_error output from this helper's stdout, which
# finalize_check read as the ENGINE_ERROR signal (a review that ended is_error but whose
# JOB still reported success is treated as no-verdict-for-HEAD).
#
# claude-code-action@v1 writes the execution log to the file named by
# steps.claude.outputs.execution_file. The exact on-disk shape is not pinned by a
# public contract, so all three plausible stream-json encodings are handled with
# one slurp-based jq filter:
#   - a single JSON ARRAY whose elements are the stream events (an element of
#     `type=="result"` carries is_error — when multiple result events exist,
#     ANY is_error=true wins, at any nesting depth: a bias toward SURFACING an
#     error, distinct from the absent/unparseable→false fail-safe below);
#   - a single result OBJECT carrying is_error;
#   - JSONL — one JSON object per line, no enclosing array (`jq -s` slurps every
#     line into an array; without `-s` a JSONL log would emit one bool per line
#     and an embedded is_error=true could be missed — the gap a blinded shadow
#     review surfaced).
# Any absent/unparseable/missing field yields "false" — the fail-safe direction:
# is_error is defense-in-depth, and finalize_check's HEAD-SHA verdict scoping
# remains the primary staleness guard (issue #249). Always exits 0 (best-effort,
# like derive-review-verdict.sh) — the caller reads stdout, not the exit code.
#
# Usage: parse-engine-error.sh [EXECUTION_FILE]
#   EXECUTION_FILE  path to the claude-code-action execution log. An empty,
#                   missing, or unreadable path yields "false".
#
# $DEVFLOW_JQ overrides the `jq` binary (the same seam the rest of devflow uses;
# honored by the sourced resolver below).

set -uo pipefail

_PEE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (matches the documented partial-copy posture — see CLAUDE.md and
# scripts/detect-project-tools.sh): a deployment carrying this file without its
# sibling lib/resolve-jq.sh must degrade to bare `jq` with a breadcrumb, never
# leave DEVFLOW_JQ unbound and abort the next reference under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_PEE_DIR/../lib/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability: a sibling that sources clean yet never
# assigns must still leave a usable jq — never a bare `set -u` abort that breaks
# the single-token stdout / always-exit-0 contract.
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "prflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  # Breadcrumb, not just the fail-safe value: a renamed/removed execution_file
  # output would otherwise disarm this signal silently and permanently (the
  # id-rename hazard — the caller's job log must show WHY is_error read false).
  echo "prflow: parse-engine-error: execution file absent or empty ('$FILE') — defaulting is_error=false (fail-safe)" >&2
  echo false
  exit 0
fi

# Slurp (`-s`) every input value into one array so JSONL, a single array, and a
# single object all normalize the same way; `.. | objects` then reaches every
# result object regardless of nesting depth. `any(. == true)` returns true iff a
# result carries is_error==true and false otherwise (empty set, absent field,
# null → false — the fail-safe default). A parse/jq failure defaults to "false"
# too, but WITH a breadcrumb (jq's own stderr flows to the caller's log): a
# broken jq or an unparseable log must never disarm this signal invisibly.
if ! PARSED=$("$DEVFLOW_JQ" -rs \
  '[.. | objects | select(.type == "result") | .is_error] | any(. == true)' \
  "$FILE"); then
  echo "prflow: parse-engine-error: jq failed parsing '$FILE' — defaulting is_error=false (fail-safe)" >&2
  PARSED=""
fi

if [ "$PARSED" = "true" ]; then
  echo true
else
  echo false
fi
exit 0

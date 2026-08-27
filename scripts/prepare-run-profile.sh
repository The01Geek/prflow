#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# prepare-run-profile.sh — the backstop-step glue for the run-profile floor (issue #2006).
# It holds the branch-selecting shell that would otherwise live in the workflow YAML, on the
# scripts/prepare-harness-floor.sh precedent: a mis-selected arm here silently empties the
# profile while the workflow still "works", so the branches are driven directly by the suite.
#
# Usage:
#   prepare-run-profile.sh <issue_number> <profile_out_file>
#
#   <issue_number>      the issue the implement run is for (devflow-implement.yml's
#                       needs.gate.outputs.number). Non-numeric or empty → inert.
#   <profile_out_file>  where the derived profile JSON is written (left absent when the
#                       glue is inert). The backstop step reads it into DEVFLOW_RUN_PROFILE.
#
# It resolves the issue's workpad through scripts/workpad.py — `id` then `body` — rather
# than re-implementing marker lookup, and pipes that body through
# scripts/derive-run-profile.py.
#
# A non-happy branch emits its OWN ::warning:: naming which condition fired; two different
# empty outcomes converging on one breadcrumb would hide which fired. Best-effort: exits 0,
# so the always() backstop step is not aborted.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKPAD="$HERE/workpad.py"
DERIVER="$HERE/derive-run-profile.py"

# Echo a helper's captured diagnostic with builtins only. `sed` is not preflight-guaranteed,
# and its absence would drop the very diagnostic this exists to surface; a `::`-leading line
# is prefixed so the runner reads it as text rather than as a workflow command.
_echo_captured() {
  local _line
  # `|| [ -n "$_line" ]` or an unterminated final line is dropped entirely — which is the
  # very diagnostic-loss this helper exists to prevent.
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      ::*) printf '  |%s\n' "$_line" >&2 ;;
      *)   printf '  %s\n' "$_line" >&2 ;;
    esac
  done < "$1"
}

ISSUE="${1:-}"
OUT="${2:-}"

case "$ISSUE" in
  ''|*[!0-9]*)
    echo "::warning::prepare-run-profile: issue number '${ISSUE:-<empty>}' is not a positive integer; no run profile derived this run" >&2
    exit 0 ;;
esac
if [ -z "$OUT" ]; then
  echo "::warning::prepare-run-profile: no output path was given; no run profile derived this run" >&2
  exit 0
fi
if [ ! -f "$WORKPAD" ]; then
  echo "::warning::prepare-run-profile: $WORKPAD is missing (a vendored tree pinned to an older prflow_version); no run profile derived this run" >&2
  exit 0
fi
if [ ! -f "$DERIVER" ]; then
  echo "::warning::prepare-run-profile: $DERIVER is missing (a vendored tree pinned to an older prflow_version); no run profile derived this run" >&2
  exit 0
fi

# `id` has a three-way exit contract: 0 found, 2 scanned cleanly with no workpad, 1 a
# gh-api/parse/transport failure. Keep all three distinguishable — folding 1 onto 2 would
# report "this run had no workpad" for what was actually an unreadable API.
#
# argparse ALSO exits 2, on a usage error — an older vendored workpad.py with no `id`
# subcommand reaches exactly that. Read stderr to tell the two apart: reporting "this
# issue has no workpad" for a helper that never ran names a cause this script did not
# observe, and sends the reader looking for a missing comment that exists.
ID_OUT="${OUT}.id"
ID_ERR="${OUT}.iderr"
ID_RC=0
python3 "$WORKPAD" id "$ISSUE" > "$ID_OUT" 2> "$ID_ERR" || ID_RC=$?
COMMENT_ID=""
while IFS= read -r _line || [ -n "$_line" ]; do
  COMMENT_ID="$_line"
done < "$ID_OUT" 2>/dev/null

# Builtins only: `grep` is not preflight-guaranteed, and an absent one makes this test
# false, which routes an older-vendored-helper usage error to the "no workpad comment"
# arm and sends the reader looking for a comment that exists.
ID_ERR_IS_USAGE=no
while IFS= read -r _line || [ -n "$_line" ]; do
  case "$_line" in
    usage:*) ID_ERR_IS_USAGE=yes ;;
  esac
done < "$ID_ERR" 2>/dev/null

if [ "$ID_RC" -eq 2 ] && [ "$ID_ERR_IS_USAGE" = yes ]; then
  echo "::warning::prepare-run-profile: $WORKPAD rejected the 'id' subcommand (a vendored tree pinned to an older prflow_version); no run profile derived this run" >&2
  rm -f "$ID_OUT" "$ID_ERR" 2>/dev/null
  exit 0
fi
if [ "$ID_RC" -eq 2 ]; then
  echo "::warning::prepare-run-profile: issue $ISSUE has no workpad comment; no run profile derived this run" >&2
  rm -f "$ID_OUT" "$ID_ERR" 2>/dev/null
  exit 0
fi
rm -f "$ID_OUT" "$ID_ERR" 2>/dev/null
if [ "$ID_RC" -ne 0 ] || [ -z "$COMMENT_ID" ]; then
  echo "::warning::prepare-run-profile: could not resolve the workpad comment id for issue $ISSUE (workpad.py id rc=$ID_RC — a gh-api, auth or parse failure); no run profile derived this run" >&2
  exit 0
fi

BODY_FILE="${OUT}.workpad"
BODY_ERR="${OUT}.bodyerr"
BODY_RC=0
python3 "$WORKPAD" body "$COMMENT_ID" > "$BODY_FILE" 2> "$BODY_ERR" || BODY_RC=$?
if [ "$BODY_RC" -ne 0 ]; then
  # Preserve the helper's own diagnostic: auth failure, rate limit, 404 and a parse failure
  # are different causes, and one causeless warning names none of them.
  echo "::warning::prepare-run-profile: workpad.py body exited $BODY_RC for comment $COMMENT_ID (issue $ISSUE); its own diagnostic follows, then no run profile is derived this run" >&2
  _echo_captured "$BODY_ERR"
  rm -f "$BODY_FILE" "$BODY_ERR" 2>/dev/null
  exit 0
fi
rm -f "$BODY_ERR" 2>/dev/null
if [ ! -s "$BODY_FILE" ]; then
  echo "::warning::prepare-run-profile: workpad comment $COMMENT_ID for issue $ISSUE fetched as an empty body; no run profile derived this run" >&2
  rm -f "$BODY_FILE" 2>/dev/null
  exit 0
fi

DERIVE_ERR="${OUT}.deriveerr"
DERIVE_RC=0
python3 "$DERIVER" --body-file "$BODY_FILE" > "$OUT" 2> "$DERIVE_ERR" || DERIVE_RC=$?
if [ "$DERIVE_RC" -eq 0 ] && [ -s "$OUT" ]; then
  echo "devflow: prepare-run-profile: derived the run profile for issue $ISSUE from workpad comment $COMMENT_ID" >&2
elif [ "$DERIVE_RC" -ne 0 ]; then
  echo "::warning::prepare-run-profile: derive-run-profile.py exited $DERIVE_RC for workpad comment $COMMENT_ID (issue $ISSUE); its own diagnostic follows, then no run profile is derived this run" >&2
  _echo_captured "$DERIVE_ERR"
  rm -f "$OUT" 2>/dev/null
else
  echo "::warning::prepare-run-profile: derive-run-profile.py exited 0 but wrote an empty profile for workpad comment $COMMENT_ID (issue $ISSUE); no run profile derived this run" >&2
  rm -f "$OUT" 2>/dev/null
fi
rm -f "$BODY_FILE" "$DERIVE_ERR" 2>/dev/null
exit 0

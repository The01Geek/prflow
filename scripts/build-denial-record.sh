#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# build-denial-record.sh — assemble the durable permission-denial forensics record
# (issue #1064 D2/D4) from a claude-code-action execution file, ready for the
# workflow->helper env handoff into lib/efficiency-trace.sh --persist (which lands it
# as a top-level `permission_denials` key on the run's telemetry-branch efficiency
# record). It is the suite-drivable home of the scrub / non-empty gate / caveat /
# fail-closed SELECTION (AC8) that must never live inline in a workflow — modelled on
# scripts/describe-denial-count.sh, the repo's inline-shell-extraction precedent.
#
# Usage: build-denial-record.sh <execution_file> <commands_enabled>
#   <execution_file>   steps.claude.outputs.execution_file path.
#   <commands_enabled> "true" | "false" — the resolved value of the
#                      .prflow.execution_denial_commands_enabled key, ALREADY decided
#                      by the caller with a bash-builtin `case` (AC9: this SELECTION is
#                      not derived here through a sed/grep pipeline). Any value other
#                      than the exact string "true" is treated as false (disabled) —
#                      the safe direction for a command-text gate.
#
# Prints ONE single-line JSON object to stdout (the denial record), or NOTHING with a
# stderr breadcrumb when there is nothing to persist or when the fail-closed arm fires.
# ALWAYS exits 0 (the best-effort backstop contract — the always() step is never
# aborted). The caller gates the env handoff on non-empty stdout.
#
# ONE DOCUMENTED EXCEPTION to "the count and tool_name are always persisted" (below):
# when the credential scrub CANNOT RUN, this helper emits NOTHING AT ALL — not a record
# carrying only the count. AC4's fail-closed rule wins over AC5/AC7's always-on rule,
# deliberately: the scrub-unavailable arm means `sed` could not be executed, and rather
# than reason about which fields of a partially-derived record are still trustworthy the
# helper declines the whole run and breadcrumbs. So read the always-on property as
# "never gated by the CONFIG KEY", which is what AC5/AC7 are about — not as "survives a
# fail-closed abort".
#
# THREE-WAY DISCIPLINE (AC2/AC7), the rule this whole issue exists to honor:
#   - count: a number, OR the literal "unavailable" — NEVER 0 for an unestablished
#     measurement. A genuine zero-denial run carries count 0; a run whose count could
#     not be read carries "unavailable". The two never collapse.
#   - commands_state: one of
#       "present"     — denied commands were extracted (scrubbed text in .commands);
#       "zero"        — the run genuinely denied nothing (.commands == []);
#       "unavailable" — the denials could not be established / no command extractable;
#       "disabled"    — the operator turned the command-text field off (key false).
#     "disabled" is DISTINGUISHABLE from both "unavailable" and "zero" (AC7): with the
#     key off, the record still lands with the count and tool_name, only the text absent.
#
# The count and tool_name are ALWAYS on — they carry no credential risk (a number and a
# fixed-vocabulary harness tool identifier). Only the command TEXT is gated (AC5).
#
# The command text is reused from scripts/extract-execution-shape.sh (its
# `permission_denials_commands` extraction — the tested 500-char/40-entry extractor),
# via scripts/extract-denied-command-line.sh, so this change UN-STRANDS that helper onto
# a live tier (issue #1064 D1) instead of re-implementing the extraction.
#
# NO-RESULT-EVENT RECOVERY (issue #1064 B2). That extractor gates EVERY field on a
# `type: "result"` event being present — a deliberate cross-field contract of its own,
# pinned by run.sh #438, and NOT widened here (it is shared with matcher-probe.yml and
# render-guard-visibility.sh). This record's COUNT, though, comes from the recursive
# descent below, which needs no result event, so on a file whose denials arrive in
# streamed message events the halves disagreed: a positive count beside commands_state
# "unavailable" while the text sat right there. Those are the runs the persist step's
# always() exists for — a stall, timeout or crash that never emitted a result event. So
# the commands are ALSO gathered here, from the same denial objects, and used ONLY when
# the shared extractor returns `unavailable`. Same field preference and same bounds; the
# recovered value re-enters the identical assembly, so it takes the identical scrub and
# fail-closed path — there is no second route to persistence.

set -uo pipefail

_BDR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/resolve-jq.sh
. "$_BDR_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: build-denial-record.sh: resolve-jq.sh could not be sourced — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: build-denial-record.sh: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq'" >&2
  DEVFLOW_JQ=jq
fi

EXEC_FILE="${1:-}"
COMMANDS_ENABLED_RAW="${2:-false}"
# AC9: the enabled/disabled decision is a bash-builtin comparison, never a pipeline.
# Any non-exact value is the safe (disabled) direction for a command-text gate.
case "$COMMANDS_ENABLED_RAW" in
  true) COMMANDS_ENABLED=true ;;
  *)    COMMANDS_ENABLED=false ;;
esac

# No execution file at all → there is no run to record. Emit nothing (never a
# fabricated zero-denial record for a run we never observed).
if [ -z "$EXEC_FILE" ] || [ ! -f "$EXEC_FILE" ] || [ ! -s "$EXEC_FILE" ]; then
  echo "devflow: build-denial-record.sh: execution file absent or empty ('$EXEC_FILE') — no denial record emitted" >&2
  exit 0
fi

# ── count + tool_names, in one jq pass over the execution file ────────────────
# Mirrors surface-execution-diagnostics.sh's count reconciliation (the LARGER of the
# reported count and the directly-gathered denial objects, so a result-event count of 0
# never suppresses denials the slurp found in message events) and honors unknown-is-not-
# zero: when neither the count field nor any denial object is present, count is the
# literal "unavailable", never 0. tool_names is the deduped, sorted set of denied tool
# identifiers (a fixed vocabulary — Bash, Write, …), always emitted (may be []).
if ! COUNT_TOOLS=$("$DEVFLOW_JQ" -rs '
    ([.. | objects | (.permission_denials? // empty)
       | if type == "array" then .[] else . end
       | select(type == "object")]) as $denials_all
    | ($denials_all | unique) as $denials
    | (last(.. | objects | select(.type? == "result"))) as $r
    | ($denials | length) as $dcount
    # Array-presence signal (issue #2064), read BEFORE the object filter above: any
    # permission_denials value that is an array is a MEASUREMENT even when empty or
    # all-non-object, so its gathered length (0 for those) is the count. Without it an
    # empty-array new-shape run fell to "unavailable" instead of a measured 0.
    | ([.. | objects | .permission_denials? | select(type == "array")] | length > 0) as $has_pd_array
    # CLAUDE.md records that permission_denials_count "publishes a digit string", so the
    # count carrier can be a NUMBER or a digit STRING. Normalize a digit string to a number
    # before the reconciliation (a non-digit string — the literal "unavailable" — or a null
    # normalizes to null, which correctly falls to the gathered length / "unavailable"). Not
    # normalizing would order number-below-string in the `>` comparison and carry a string
    # count downstream, where _denials_from_eff reads it as unestablished — the safe
    # direction, but it defeats a real positive count (issue #1064 review).
    | (if $r == null then null
       else ($r.permission_denials_count
             | if type == "string" then (tonumber? // null) else . end) end) as $rc
    | (if $rc != null
       then (if $dcount > $rc then $dcount else $rc end)
       elif $dcount > 0 then $dcount
       elif $has_pd_array then $dcount
       else null end) as $count
    | ([$denials[] | (.tool_name? // empty) | select(type == "string")] | unique) as $tools
    # NO-RESULT-EVENT FALLBACK (issue #1064 B2). extract-execution-shape.sh gates EVERY
    # field on a `type: "result"` event being present — a deliberate, pinned, cross-field
    # contract of that helper (run.sh #438 locks "no-result + denials array records
    # unavailable, not present"), so it is NOT widened here. But this record`s count comes
    # from the recursive descent above, which needs no result event, so on a file whose
    # denials arrive in streamed message events the two halves disagreed: a positive count
    # beside commands_state "unavailable" while the command text sat right there. Those are
    # exactly the runs the persist step`s always() exists for — a stall, timeout or crash
    # that never emitted a result event. So gather the commands here too, from the SAME
    # denial objects the count already used, and consult it ONLY when the shared extractor
    # returned unavailable. Field preference and BOUNDS mirror that extractor exactly:
    # .tool_input.command then .command, a 500-char per-command cap with the same suffix,
    # a 40-entry list cap, and truncated set from the pre-cap length. NOT deduped — the
    # extractor does not dedupe either, and total must count what was extracted.
    # Emits null when nothing is extractable, so an honest unavailable survives.
    | ([$denials_all[] | (.tool_input.command? // .command? // empty)
        | select(type == "string")
        | if (length > 500) then (.[0:500] + " …[per-command-truncated]") else . end]) as $fbcmds
    | (if ($fbcmds | length) == 0 then null
       else {commands: ($fbcmds[0:40]), total: ($fbcmds | length),
             truncated: (($fbcmds | length) > 40)} end) as $fb
    # result_present drives the issue-#2064 shape-drift warning in the caller; the final
    # record assembled below reads only .count/.tool_names/.fallback_commands, so this extra
    # key is inert there.
    | {count: (if $count == null then "unavailable" else $count end), tool_names: $tools,
       fallback_commands: $fb, result_present: ($r != null)}
    | tojson
  ' "$EXEC_FILE" 2>/dev/null); then
  COUNT_TOOLS=""
fi
if [ -z "$COUNT_TOOLS" ]; then
  # The file exists but could not be parsed for count/tool_names — an UNESTABLISHED
  # measurement, not a zero. Persist a record that says so (count unavailable) rather
  # than nothing, so a downstream reader can tell "unparseable" from "denied nothing".
  COUNT_TOOLS='{"count":"unavailable","tool_names":[],"fallback_commands":null}'
  echo "devflow: build-denial-record.sh: could not parse execution file for count/tool_names ('$EXEC_FILE') — recording count as unavailable" >&2
fi

# Shape-drift warning (issue #2064): a result event was present yet the count still resolved
# to unavailable — no count field and no permission_denials array. Emit one breadcrumb so the
# next execution-file shape change announces itself. Distinct wording from surface-execution-
# diagnostics.sh so the two extractors' warnings are asserted independently. (jq is a preflight-
# guaranteed tool, so deriving these two operands through it is safe.)
_bdr_count="$(printf '%s' "$COUNT_TOOLS" | "$DEVFLOW_JQ" -r '.count' 2>/dev/null)" || _bdr_count=""
_bdr_result_present="$(printf '%s' "$COUNT_TOOLS" | "$DEVFLOW_JQ" -r '.result_present // false' 2>/dev/null)" || _bdr_result_present=false
if [ "$_bdr_count" = unavailable ] && [ "$_bdr_result_present" = true ]; then
  echo "devflow: build-denial-record.sh: execution-file shape drift suspected — a result event was present but permission_denials_count could not be established (no count field, no permission_denials array); the execution-file shape may have changed" >&2
fi

# ── command text three-state, reusing extract-execution-shape.sh (un-stranding it) ──
# Only consulted when the key is enabled. permission_denials_commands is itself a
# three-state: the literal "unavailable" | {commands:[],total:0,...} (zero) |
# {commands:[...],total:N,...} (present).
CMDS_JSON=""
if [ "$COMMANDS_ENABLED" = true ]; then
  EES_BLOCK="$("$_BDR_DIR/extract-execution-shape.sh" "$EXEC_FILE")"; EES_RC=$?
  # extract-denied-command-line.sh prints two lines: status + value.
  DCL_OUT="$("$_BDR_DIR/extract-denied-command-line.sh" "$EES_RC" <<<"$EES_BLOCK")"
  DCL_STATUS=""
  DCL_VALUE=""
  _dcl_n=0
  while IFS= read -r _dcl_line; do
    _dcl_n=$((_dcl_n + 1))
    [ "$_dcl_n" -eq 1 ] && DCL_STATUS="$_dcl_line"
    [ "$_dcl_n" -eq 2 ] && DCL_VALUE="$_dcl_line"
  done <<<"$DCL_OUT"
  if [ "$DCL_STATUS" = found ]; then
    CMDS_JSON="$DCL_VALUE"
  else
    # rc-nonzero / not-found → the extractor could not establish the commands.
    CMDS_JSON=unavailable
  fi
  # ── No-result-event fallback (issue #1064 B2) ───────────────────────────────
  # Consulted ONLY when the shared extractor came back `unavailable`, so its tested
  # output stays authoritative on every file it can establish. The fallback value is
  # the SAME {commands,total,truncated} shape, so it flows into the identical
  # assembly below — which means it takes the identical scrub path (AC4 fail-closed
  # included): there is no second route to persistence that could bypass the
  # blocklist. A genuine zero (`{"commands":[],...}`) is NOT `unavailable` and never
  # reaches here, and when nothing is extractable `.fallback_commands` is null and
  # `unavailable` stands — the three-state discipline is preserved in both directions.
  if [ "$CMDS_JSON" = unavailable ]; then
    _FB="$(printf '%s' "$COUNT_TOOLS" | "$DEVFLOW_JQ" -c '.fallback_commands // empty' 2>/dev/null)" || _FB=""
    if [ -n "$_FB" ]; then
      CMDS_JSON="$_FB"
      echo "devflow: build-denial-record.sh: extract-execution-shape.sh could not establish the denied commands (no result event in the execution file); recovered them from the denial objects directly, at the same bounds" >&2
    fi
  fi
fi

# Resolve the caveat shapes from the shared scrub (single source of truth). A missing
# scrub helper leaves this empty; the record still records blocklist_incomplete:true.
SHAPES="$("$_BDR_DIR/scrub-credentials.sh" --shapes 2>/dev/null || true)"

# ── Assemble commands_state + (scrubbed) commands ─────────────────────────────
COMMANDS_STATE=disabled
COMMANDS_ARR=null
TOTAL=null
TRUNCATED=null
SCRUB_APPLIED=false

if [ "$COMMANDS_ENABLED" = true ]; then
  case "$CMDS_JSON" in
    unavailable | "")
      COMMANDS_STATE=unavailable ;;
    *)
      # A structured value. Decide zero vs present from the parsed shape.
      _shape="$(printf '%s' "$CMDS_JSON" | "$DEVFLOW_JQ" -r '
        if (type == "object") and ((.commands? | type) == "array")
        then (if (.commands | length) == 0 then "zero" else "present" end)
        else "bad" end' 2>/dev/null)" || _shape=bad
      case "$_shape" in
        zero)
          COMMANDS_STATE=zero
          COMMANDS_ARR='[]'
          TOTAL="$(printf '%s' "$CMDS_JSON" | "$DEVFLOW_JQ" -r 'if (.total?|type)=="number" then (.total|tostring) else "0" end' 2>/dev/null)" || TOTAL=0
          TRUNCATED=false ;;
        present)
          # Extract the raw command strings, scrub each through the shared helper, and
          # rebuild a JSON array. FAIL CLOSED (AC4): if the scrub cannot run for ANY
          # command, emit NOTHING for the whole run — an unscrubbed persist to a durable
          # branch is worse than an absent record.
          _raw_cmds="$(printf '%s' "$CMDS_JSON" | "$DEVFLOW_JQ" -c '.commands' 2>/dev/null)" || _raw_cmds=""
          if [ -z "$_raw_cmds" ]; then
            COMMANDS_STATE=unavailable
          else
            # Walk each string element, scrub it, collect into a bash array, and build the
            # JSON array ONCE at the end. Iterate via jq base64 so an embedded newline in a
            # command does not split the loop. (Accumulating in the array — rather than
            # re-parsing/re-serializing a growing JSON string with `. + [$s]` per element —
            # keeps the loop linear rather than O(n²) in the payload.)
            _scrubbed_cmds=()
            _scrub_ok=1
            while IFS= read -r _b64; do
              [ -n "$_b64" ] || continue
              _cmd="$("$DEVFLOW_JQ" -rn --arg b "$_b64" '$b | @base64d' 2>/dev/null)" || { _scrub_ok=0; break; }
              if _scrubbed="$(printf '%s' "$_cmd" | "$_BDR_DIR/scrub-credentials.sh")"; then
                _scrubbed_cmds+=("$_scrubbed")
              else
                # scrub-credentials.sh exited non-zero (sed unavailable / failed) →
                # fail closed for the whole record.
                _scrub_ok=0
                break
              fi
            done < <(printf '%s' "$_raw_cmds" | "$DEVFLOW_JQ" -r '.[] | @base64' 2>/dev/null)
            if [ "$_scrub_ok" -ne 1 ]; then
              echo "devflow: build-denial-record.sh: credential scrub could not run over the denied command text — persisting NOTHING for this run (fail-closed, AC4)" >&2
              exit 0
            fi
            # Build the scrubbed array once from the collected strings ($ARGS.positional is
            # the empty array [] when no commands were collected, matching a genuine zero).
            # `${arr[@]+"${arr[@]}"}` expands to nothing on an empty array without tripping
            # set -u on older bash (a present arm with every element empty-skipped).
            COMMANDS_ARR="$("$DEVFLOW_JQ" -cn '$ARGS.positional' --args ${_scrubbed_cmds[@]+"${_scrubbed_cmds[@]}"} 2>/dev/null)" || COMMANDS_ARR='[]'
            COMMANDS_STATE=present
            SCRUB_APPLIED=true
            TOTAL="$(printf '%s' "$CMDS_JSON" | "$DEVFLOW_JQ" -r 'if (.total?|type)=="number" then (.total|tostring) else "0" end' 2>/dev/null)" || TOTAL=0
            TRUNCATED="$(printf '%s' "$CMDS_JSON" | "$DEVFLOW_JQ" -r 'if .truncated == true then "true" else "false" end' 2>/dev/null)" || TRUNCATED=false
          fi ;;
        *)
          COMMANDS_STATE=unavailable ;;
      esac ;;
  esac
fi

# ── Assemble the final single-line record ─────────────────────────────────────
# --argjson for the machine-shaped operands (count/tool_names/commands/total/truncated),
# --arg for the strings. commands is null unless present/zero. scrub records that the
# blocklist is incomplete regardless of whether it was applied (honest-claims: never
# assert redaction).
if ! REC="$("$DEVFLOW_JQ" -cn \
      --argjson counttools "$COUNT_TOOLS" \
      --arg state "$COMMANDS_STATE" \
      --argjson cmds "$COMMANDS_ARR" \
      --argjson total "${TOTAL:-null}" \
      --argjson truncated "${TRUNCATED:-null}" \
      --arg applied "$SCRUB_APPLIED" \
      --arg shapes "$SHAPES" \
      --arg enabled "$COMMANDS_ENABLED" \
      '{count: $counttools.count,
        tool_names: $counttools.tool_names,
        commands_state: $state,
        commands: $cmds,
        total: $total,
        truncated: $truncated,
        commands_field_enabled: ($enabled == "true"),
        scrub: {applied: ($applied == "true"),
                blocklist_incomplete: true,
                shapes: (if $shapes == "" then null else $shapes end)}}' 2>/dev/null)"; then
  echo "devflow: build-denial-record.sh: could not assemble the denial record (jq failed) — no record emitted" >&2
  exit 0
fi

printf '%s\n' "$REC"
exit 0

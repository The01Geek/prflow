#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# surface-execution-diagnostics.sh — surface a claude-code-action run's execution
# diagnostics (run summary + permission-denial detail) to stdout, and to
# $GITHUB_STEP_SUMMARY when that variable is set and non-empty. A pure read-only
# diagnostic: it never changes the calling step's pass/fail result, uploads no
# artifact, and always exits 0 — a maintainer debugging a stalled/incomplete/
# unexpectedly-denied cloud run gets the denial detail and run shape directly on
# the Actions run page and in the streamed log (issue #329).
#
# claude-code-action@v1 writes the execution log to the file named by
# steps.claude.outputs.execution_file. Its exact on-disk shape is not pinned by a
# public contract, so — exactly like scripts/parse-engine-error.sh — the same
# slurp-based jq traversal handles all three plausible encodings:
#   - a single JSON ARRAY of stream events (the element of type=="result" carries
#     the run summary; when several exist the LAST is used);
#   - a single result OBJECT;
#   - JSONL (one JSON object per line; `jq -s` slurps every line into an array).
# `.. | objects` then reaches the result object at any nesting depth.
#
# Per-denial detail (tool_name + tool_input) may live in the result event's
# `permission_denials` array OR in streamed message events rather than the result
# event, and no sample execution file survives to pin its exact home (issue #329's
# load-bearing assumption). So denials are gathered from ANY `permission_denials`
# array in the slurped input, and the surfacing degrades to count-only when no
# such array is present — the count (`permission_denials_count`) is shown when the
# log carries it or denials were gathered, else reported as unavailable.
#
# Best-effort, mirroring parse-engine-error.sh: an absent, empty, or unparseable
# execution file — and a parsed file carrying neither a result event nor any
# permission-denial detail — prints an explicit "no diagnostics available" line
# and exits 0. (A parsed file with denial detail but no result event still
# surfaces a partial block: n/a run-summary fields plus the denials.) A file with
# zero denials prints "No permission denials." Always exits 0 — the caller reads
# stdout, never the exit code.
#
# Usage: surface-execution-diagnostics.sh [EXECUTION_FILE]
#   EXECUTION_FILE  path to the claude-code-action execution log.
#
# $DEVFLOW_JQ overrides the `jq` binary (the same seam the rest of devflow uses;
# honored by the sourced resolver below).

set -uo pipefail

_SED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (matches parse-engine-error.sh / the documented partial-copy
# posture — see CLAUDE.md): a deployment carrying this file without its sibling
# lib/resolve-jq.sh must degrade to bare `jq` with a breadcrumb, never leave
# DEVFLOW_JQ unbound and abort the next reference under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_SED_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability: a sibling that sources clean yet never
# assigns must still leave a usable jq — never a bare `set -u` abort that breaks
# the always-exit-0 contract.
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

# Never make this an unguarded `.`, and never re-derive the version with a second
# extraction jq (issue #1528): a deployment missing the sibling must reach the call-site
# `type devflow_probe_cli_version` guard, not abort under `set -u`.
# shellcheck source=../lib/probe-observation.sh
. "$_SED_DIR/../lib/probe-observation.sh" \
  || echo "devflow: surface-execution-diagnostics: probe-observation.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — claude_code_version will publish 'unavailable'" >&2

# Emit BLOCK to stdout, and append it to $GITHUB_STEP_SUMMARY when that variable
# is set and non-empty (AC2). Kept in one place so every exit path surfaces to
# both sinks identically.
_emit() {
  printf '%s\n' "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '%s\n' "$1" >> "$GITHUB_STEP_SUMMARY" \
      || echo "devflow: surface-execution-diagnostics: could not append to GITHUB_STEP_SUMMARY ('$GITHUB_STEP_SUMMARY') — stdout still carries the diagnostics" >&2
  fi
}

# Publish the denial count and, when it is positive, raise a `::warning::` so a run
# that stalled on permission denials announces itself in the job log instead of
# hiding in a Markdown block nobody opens (issue #363).
#
# The count is read back out of the ALREADY-RENDERED block rather than re-derived,
# so the human-readable number and the machine-readable one cannot disagree — the
# jq program below is the single place the reconciliation lives.
#
# Parsed with bash builtins ONLY — no `sed`/`head`/`grep`. This value decides
# whether the ::warning:: fires and what the job output publishes, and a value that
# is only correct when an un-guaranteed PATH tool is present is an unverified
# boundary: `tr`/`sed`/`cut` are NOT preflight prerequisites (see lib/preflight.sh),
# so on a host lacking `sed` the old pipeline silently yielded an empty count,
# published 0, and suppressed the warning on a run that HAD recorded denials — a
# fail-open in the exact observability path this function exists to provide.
#
# "Unknown" is published as the literal `unavailable`, never as `0`. A consumer must
# be able to tell "the engine refused no commands" from "the count could not be
# established": collapsing both onto `0` makes the downstream no-verdict ::error::
# assert a denial count it never observed, steering the reader away from permission
# denials — the mis-diagnosis this whole change exists to end. No warning is raised
# for an unknown count: unknown is not evidence of denials.
#
# Both side effects are additive — this script still always exits 0 and never
# changes a run's pass/fail.
_publish_denials() {  # rendered-block
  _count=""
  _saw_label=0
  while IFS= read -r _line; do
    case "$_line" in
      "- permission_denials_count: "*)
        _saw_label=1
        _count="${_line#- permission_denials_count: }"
        break
        ;;
    esac
  done <<<"$1"   # here-string, not a heredoc: a block line reading exactly `EOF` cannot
                 # terminate it early, and (unlike `printf … | while`) the loop stays in
                 # this shell, so `_count` survives it.
  case "$_count" in
    *[!0-9]* | "")
      # `n/a` is the renderer's own honest "unknown". A missing label line means the
      # renderer's contract changed — also unknown, and worth a breadcrumb, because
      # "the label is absent" is not evidence that there were no denials.
      [ "$_saw_label" -eq 1 ] || echo "devflow: surface-execution-diagnostics: no 'permission_denials_count' line in the rendered block (renderer contract changed?) — publishing 'unavailable'; a positive denial count would NOT be reported this run" >&2
      _count=unavailable
      ;;
  esac
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'permission_denials_count=%s\n' "$_count" >> "$GITHUB_OUTPUT" \
      || echo "devflow: surface-execution-diagnostics: could not append permission_denials_count to GITHUB_OUTPUT ('$GITHUB_OUTPUT') — downstream jobs will read the 'unavailable' default" >&2
  fi
  if [ "$_count" != unavailable ] && [ "$_count" -gt 0 ]; then
    echo "::warning::DevFlow: this run recorded $_count permission denial(s) — the engine attempted commands its tool profile does not grant. See the execution-diagnostics block for which ones."
  fi
}

# _publish_claude_code_version — publish claude_code_version (issue #1528) and, on
# success, raise a `::notice::` (the in-job read-back that makes this a measurement a
# consumer reads). Contract, each clause a wrong change it forbids:
#   - value-publish ONLY claude_code_version; every other init field stays type-only
#     behind scripts/extract-execution-shape.sh's redaction boundary;
#   - derive with bash builtins ONLY — sed/head/grep/awk/cut/tr are not preflight-
#     guaranteed (lib/preflight.sh) and fail-open to empty when absent;
#   - "unknown" is the literal `unavailable`, never empty/0, and raises no notice.
# Why the redaction boundary and the read-back-from-block invariant: see
# docs/internal/execution-diagnostics.md.
_publish_claude_code_version() {  # rendered-block
  _ccver=""
  while IFS= read -r _line; do
    case "$_line" in
      "- claude_code_version: "*)
        _ccver="${_line#- claude_code_version: }"
        break
        ;;
    esac
  done <<<"$1"   # here-string like _publish_denials: the loop stays in this shell, so
                 # `_ccver` survives it.
  # Empty means the line was absent: the block always renders at least `unavailable`,
  # so no separate saw-it flag is needed to tell "not found" from a real empty value.
  if [ -z "$_ccver" ]; then
    _ccver=unavailable
  fi
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'claude_code_version=%s\n' "$_ccver" >> "$GITHUB_OUTPUT" \
      || echo "devflow: surface-execution-diagnostics: could not append claude_code_version to GITHUB_OUTPUT ('$GITHUB_OUTPUT') — no step output is published for this run" >&2
  fi
  if [ "$_ccver" != unavailable ]; then
    echo "::notice::DevFlow: claude-code CLI version $_ccver (from the execution-file init record)"
  else
    echo "devflow: surface-execution-diagnostics: claude_code_version could not be established from the execution file — publishing 'unavailable'" >&2
  fi
}

_HEADER="## DevFlow execution diagnostics"
_NO_DIAG="$_HEADER
_No diagnostics available (execution file absent, empty, or unparseable)._"

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ] || [ ! -s "$FILE" ]; then
  # Breadcrumb + explicit line: a renamed/removed execution_file output would
  # otherwise disarm this diagnostic silently (the id-rename hazard).
  echo "devflow: surface-execution-diagnostics: execution file absent or empty ('$FILE') — no diagnostics available" >&2
  _emit "$_NO_DIAG"
  _publish_denials "$_NO_DIAG"
  _publish_claude_code_version "$_NO_DIAG"
  exit 0
fi

# Resolve the CLI version once (#1528) via the shared reader, rendered into the block so
# the published and human values agree. An absent reader (partial deployment) degrades
# to `unavailable` + breadcrumb here — never a set -u abort.
if type devflow_probe_cli_version >/dev/null 2>&1; then
  CCVER=$(devflow_probe_cli_version "$FILE")
else
  CCVER=unavailable
  echo "devflow: surface-execution-diagnostics: devflow_probe_cli_version unavailable (probe-observation.sh not sourced) — claude_code_version will publish 'unavailable'" >&2
fi

# Build the whole formatted block in one slurp-based jq program. `-s` normalizes
# JSONL / single-array / single-object the same way; `.. | objects` reaches the
# result object at any depth. Denials are gathered from every `permission_denials`
# array anywhere in the slurped input (they may not live in the result event).
# tool_input is truncated to keep the surfaced block readable.
if ! BLOCK=$("$DEVFLOW_JQ" -rs --arg header "$_HEADER" --arg ccver "$CCVER" '
    def trunc($s):
      ($s | tostring) as $t
      | if ($t | length) > 200 then ($t[0:200] + "…(truncated)") else $t end;
    # Denial-line bound (issue #1064 D1/AC1). The old 200-char trunc() applied to the
    # STRINGIFIED tool_input envelope, so for a Bash denial the budget was spent on the
    # JSON envelope before any command text was reached and the ungranted head — usually
    # in the tail of a long pipeline — was cut off, leaving the surfaced line unable to
    # identify what was refused. Route chosen: WIDEN the bound for the denial line and
    # prefer .tool_input.command specifically, rather than reuse extract-execution-shape.sh
    # here — this script is the step-summary RENDERER, not the shape extractor, so widening
    # its own render keeps one code path while the denial RECORD (scripts/build-denial-
    # record.sh) is what un-strands extract-execution-shape.sh onto the live tier. 500 is an
    # enforcement constant pinned in lib/test/run.sh, matching the extract-execution-shape.sh
    # per-command cap; it stays finite (an unbounded step-summary field is its own hazard).
    # NOTE: no ASCII apostrophes in this comment — it sits inside a bash single-quoted jq
    # program, where one would terminate the string (SC1011/SC1073).
    def trunccmd($s):
      ($s | tostring) as $t
      | if ($t | length) > 500 then ($t[0:500] + "…(truncated)") else $t end;
    # Null-safe field render: `//` would collapse a legitimate `false`/absent
    # is_error to the fallback (jq treats false as empty for `//`), so a plain
    # explicit null check is used instead of `.field // "n/a"`.
    def orna($v): if $v == null then "n/a" else $v end;
    (last(.. | objects | select(.type? == "result"))) as $r
    # `unique` de-duplicates: the same denial can appear in more than one place in
    # the slurped log (e.g. a streamed message event AND the summarizing result
    # event both carrying permission_denials), which would otherwise double-count
    # $dcount and inflate both the reconciled count and the detail listing.
    | ([.. | objects | (.permission_denials? // empty)
        | if type == "array" then .[] else . end
        | select(type == "object")] | unique) as $denials
    | if $r == null and ($denials | length) == 0 then
        # No result event and no denial detail — but the CLI version lives in the
        # system/init record independent of the result event, so still surface it: a
        # stalled init-but-no-result run is exactly when the build version matters (#1528).
        $header, "",
        "- claude_code_version: \($ccver)",
        "",
        "_No diagnostics available (no result event in execution file)._"
      else
        # Count resolution keeps "unknown" distinct from "measured zero" — do NOT
        # collapse an absent count to 0 (that would fail OPEN: a run whose denial
        # detail lived in a shape this slurp did not match, and whose result event
        # omitted the count, would be affirmatively reported as "No permission
        # denials." — the opposite of what this tool is for). $count is the reported
        # count, else the gathered-denial length, else null (genuinely unknown).
        # Reconcile the reported count with directly-gathered denial objects: take
        # the LARGER of the two so a result-event count of 0 (or an under-report)
        # never suppresses denial detail the slurp actually found in message events
        # — that would fail OPEN in the core use case. When the count field is
        # absent, use the gathered length; when neither exists, null (genuinely
        # unknown). Directly-observed denials always win over a smaller field value.
        ($denials | length) as $dcount
        | (if $r.permission_denials_count != null then
             (if $dcount > $r.permission_denials_count then $dcount else $r.permission_denials_count end)
           elif $dcount > 0 then $dcount
           else null end) as $count
        | $header, "",
          "### Run summary",
          "- is_error: \(orna($r.is_error))",
          "- num_turns: \(orna($r.num_turns))",
          "- duration_ms: \(orna($r.duration_ms))",
          "- total_cost_usd: \(orna($r.total_cost_usd))",
          "- permission_denials_count: \(orna($count))",
          "- claude_code_version: \($ccver)",
          "",
          "### Permission denials",
          # Gathered detail is surfaced FIRST — before the count==0 / unavailable
          # branches — so directly-observed denials are never hidden behind a
          # contradicting or absent result-event count.
          (if $dcount > 0 then
             ("\($dcount) permission denial(s) with detail:"),
             # Prefer the denied .command (or a nested .tool_input.command) at the wider
             # bound; fall back to the stringified envelope only when no command field
             # exists (issue #1064 D1/AC1).
             ($denials[] | "- `\(.tool_name // "unknown")`: \(trunccmd((.tool_input?.command? // .command? // .tool_input) // ""))")
           elif $count == null then
             "Permission-denial count unavailable — no permission_denials_count in the result event and no permission_denials array found."
           elif $count == 0 then
             "No permission denials."
           else
             "\($count) permission denial(s) reported; no per-denial detail in execution file."
           end)
      end
  ' "$FILE"); then
  # jq's own stderr flows to the caller's log; add a devflow breadcrumb naming the
  # file so a broken jq / unparseable log is attributable, not silently swallowed.
  # Worded to cover BOTH causes of a non-zero exit — an unparseable log AND an
  # absent/unrunnable jq (resolve-jq.sh's final fallback is a bare, unverified jq) —
  # rather than misattributing a missing binary to a parse error.
  echo "devflow: surface-execution-diagnostics: jq ('$DEVFLOW_JQ') exited non-zero on '$FILE' (parse error or unrunnable jq) — no diagnostics available" >&2
  _emit "$_NO_DIAG"
  _publish_denials "$_NO_DIAG"
  _publish_claude_code_version "$_NO_DIAG"
  exit 0
fi

_emit "$BLOCK"
_publish_denials "$BLOCK"
_publish_claude_code_version "$BLOCK"
exit 0

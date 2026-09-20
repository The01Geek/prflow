#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# job-log-transcript.sh stream-gate|rebuild [CONFIG_FILE]
#
# The shell of devflow-implement.yml's two job-log transcript steps (issue #799), kept here
# so the workflow and the test suite execute the same bytes.
#
#   stream-gate  Decides the engine action's show_full_output input and appends
#                `show_full_output=true|false` to $GITHUB_OUTPUT. The job log is NOT
#                scrubbed, so `true` needs BOTH prflow.execution_transcript_job_log_enabled
#                resolving to the string `true` AND $PRFLOW_REPO_PRIVATE being the string
#                `true` (the workflow passes github.event.repository.private). A public
#                repository, or a visibility the event did not state, gets `false` with a
#                ::warning:: naming which of the two suppressed it.
#   rebuild      Rebuilds the dead claude job's transcript from its log and appends the
#                scrubbed file's `path=` to $GITHUB_OUTPUT, which the upload step gates on.
#                Needs prflow.execution_transcript_artifact_enabled; reads
#                GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, RUNNER_TEMP and GH_TOKEN.
#
# CONFIG_FILE is handed to config-get.sh as its config path; omitted, config-get.sh uses
# its own default. $DEVFLOW_GH overrides the gh binary.
#
# Both subcommands end in `exit 0`; an arm that declines prints a breadcrumb naming itself
# and fails closed (show_full_output=false / GITHUB_OUTPUT left without a path=). A missing
# or unknown subcommand exits 2.

set -uo pipefail

MODE="${1:-}"
CONFIG_FILE="${2:-}"
_JLT_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
CG="$_JLT_DIR/config-get.sh"
OUTPUT_FILE="${GITHUB_OUTPUT:-/dev/null}"

# Read one boolean gate: only the string `true` enables. --scalar resolves an array or an
# object as unset (`["true"]` would otherwise join to "true"); `|| true` guards
# config-get.sh's hard-fail. The callers compare the result with bash builtins.
_gate() {  # $1 = dot-path key
  if [ -n "$CONFIG_FILE" ]; then
    "$CG" --scalar "$1" false "$CONFIG_FILE" || true
  else
    "$CG" --scalar "$1" false || true
  fi
}

stream_gate() {
  local stream="false" key=""
  if [ ! -f "$CG" ]; then
    echo "::warning::transcript streaming gate inert: $CG missing; show_full_output=false (fail-closed)."
  else
    key="$(_gate .prflow.execution_transcript_job_log_enabled)"
    if [ "$key" != "true" ]; then
      echo "execution transcript streaming disabled (execution_transcript_job_log_enabled != true); an abrupt runner death will leave no transcript to rebuild."
    elif [ "${PRFLOW_REPO_PRIVATE:-}" = "true" ]; then
      stream="true"
      echo "::warning::execution transcript streaming is ON (execution_transcript_job_log_enabled=true, private repository): every engine message — prompt text, repository content, tool output, and any credential the agent echoes, including refreshed App tokens, which nothing masks — is written to THIS job's log UNSCRUBBED. Anyone who can read this run's logs can read it."
    elif [ "${PRFLOW_REPO_PRIVATE:-}" = "false" ]; then
      echo "::warning::execution transcript streaming SUPPRESSED: execution_transcript_job_log_enabled=true, but this repository is public and a public repository publishes its job logs; show_full_output=false."
    else
      echo "::warning::execution transcript streaming SUPPRESSED: execution_transcript_job_log_enabled=true, but the triggering event did not state whether this repository is private (got '${PRFLOW_REPO_PRIVATE:-}'); unknown is not private, so show_full_output=false (fail-closed)."
    fi
  fi
  printf 'show_full_output=%s\n' "$stream" >> "$OUTPUT_FILE"
  printf 'show_full_output=%s\n' "$stream"
}

rebuild() {
  local transcript r st expect names name job_ids job_id log rebuilt out scrub_out rc line
  if [ ! -f "$CG" ]; then
    echo "::warning::transcript rebuild inert: $CG missing (an older vendored tree); nothing uploaded (fail-closed)."
    return 0
  fi
  transcript="$(_gate .prflow.execution_transcript_artifact_enabled)"
  if [ "$transcript" != "true" ]; then
    echo "::notice::execution transcript artifact disabled (execution_transcript_artifact_enabled != true); no transcript rebuilt."
    return 0
  fi
  r="$_JLT_DIR/recover-transcript-from-job-log.py"
  st="$_JLT_DIR/scrub-transcript.sh"
  if [ ! -f "$r" ] || [ ! -f "$st" ]; then
    echo "::warning::transcript rebuild inert: a vendored tree predating the job-log rebuild helper; nothing uploaded (fail-closed)."
    return 0
  fi
  # Guarded source — a partial copy without lib/resolve-gh.sh degrades to bare `gh`.
  # shellcheck source=../lib/resolve-gh.sh
  . "$_JLT_DIR/../lib/resolve-gh.sh" \
    || echo "job-log-transcript: resolve-gh.sh could not be sourced from ../lib — using bare 'gh' (set DEVFLOW_GH to override)" >&2
  if type devflow_resolve_gh >/dev/null 2>&1; then
    : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
  else
    DEVFLOW_GH="${DEVFLOW_GH:-gh}"
  fi
  # The artifact name the in-job channel uses, byte-identical, so tools/flight-recorder/
  # implement-timeline.py's `<prefix>-<attempt>` resolver admits a rebuilt transcript.
  expect="claude-execution-transcript-${GITHUB_RUN_ID:-}-${GITHUB_RUN_ATTEMPT:-}"
  # A GRACEFUL cancel does run the in-job upload and actions/upload-artifact refuses a
  # duplicate name; an unreadable listing is unknown, not absent.
  names="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/actions/runs/${GITHUB_RUN_ID:-}/artifacts" --jq '.artifacts[].name')" || {
    echo "::notice::could not list this run's artifacts, so whether the in-job channel already uploaded one is unavailable; no transcript rebuilt (fail-closed)."
    return 0
  }
  # Exact whole-line comparison by bash builtins — no grep decides whether a duplicate
  # upload is about to be attempted.
  while IFS= read -r name; do
    if [ "$name" = "$expect" ]; then
      echo "::notice::the claude job already uploaded '$expect' (its post-steps ran); no transcript rebuilt."
      return 0
    fi
  done <<< "$names"
  # Resolve the dead job's id the same way the spot watcher does (name == claude), scoped
  # to THIS run attempt so a re-run never reads the previous attempt's log. A parameter
  # expansion takes the first id, never `head`.
  job_ids="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/actions/runs/${GITHUB_RUN_ID:-}/attempts/${GITHUB_RUN_ATTEMPT:-}/jobs" --jq '.jobs[] | select(.name=="claude") | .id')" || job_ids=""
  job_id="${job_ids%%$'\n'*}"
  if [ -z "$job_id" ]; then
    echo "::warning::could not resolve the claude job's id for this run attempt; no transcript rebuilt (fail-closed)."
    return 0
  fi
  log="${RUNNER_TEMP:-.}/claude-job.log"
  if ! "$DEVFLOW_GH" api "repos/{owner}/{repo}/actions/jobs/${job_id}/logs" > "$log"; then
    echo "::warning::could not download the claude job's log (job ${job_id}); no transcript rebuilt (fail-closed)."
    return 0
  fi
  rebuilt="${RUNNER_TEMP:-.}/claude-execution-rebuilt.json"
  # The parser advertises `path=` only when it recovered at least one message, and names
  # each refused input shape it saw. Its contract is exit 0; anything else is reported.
  python3 "$r" --log "$log" --out "$rebuilt"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "::warning::recover-transcript-from-job-log.py exited $rc; nothing uploaded (fail-closed)."
    return 0
  fi
  if [ ! -f "$rebuilt" ]; then
    echo "::notice::no rebuilt transcript was written (streaming off, a run that died before its first message, or an arm the parser named above); nothing uploaded."
    return 0
  fi
  # ONE scrub implementation for the whole channel: the helper the in-job step calls, on
  # the same execution-file-shaped input. Its `path=` line is what the upload step gates on.
  out="${RUNNER_TEMP:-.}/claude-execution-scrubbed.json"
  scrub_out="${RUNNER_TEMP:-.}/scrub-transcript-out.txt"
  bash "$st" "$rebuilt" "$out" > "$scrub_out"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "::warning::scrub-transcript.sh exited $rc; its path= is not trusted and nothing is uploaded (fail-closed)."
    return 0
  fi
  while IFS= read -r line; do
    printf '%s\n' "$line"
    case "$line" in path=*) printf '%s\n' "$line" >> "$OUTPUT_FILE" ;; esac
  done < "$scrub_out"
}

case "$MODE" in
  stream-gate) stream_gate ;;
  rebuild)     rebuild ;;
  *)
    echo "usage: job-log-transcript.sh stream-gate|rebuild [CONFIG_FILE]" >&2
    exit 2
    ;;
esac
exit 0

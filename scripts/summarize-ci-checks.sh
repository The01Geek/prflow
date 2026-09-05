#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# summarize-ci-checks.sh — render the CI signals observed for a PR head as one
# line per signal, for injection into the review engine's prompt (issue #363).
#
# Why: the cloud review engine had no ground truth about the CI that already ran
# on the commit it reviews, so it spent turns re-deriving it by trying to run the
# test suite — a command its read-only profile can never permit. Feeding it the
# observed conclusions up front removes that whole class of wasted budget.
#
# Contract (mirrors derive-review-preconditions.sh, its sibling and prior art):
#   * ALWAYS exits 0. The caller composes a prompt; it must never fail a review.
#   * On any failure, stdout is exactly `CI status unavailable` and NO signal
#     line, and stderr carries a SPECIFIC breadcrumb naming which query failed.
#     An absent result must never render as a passing one — that fail-open is the
#     bug this helper exists to prevent.
#   * A head with genuinely zero CI signals (no non-self workflow jobs and no
#     external check runs) is NOT a failure: stdout is exactly
#     `No CI signals reported for this commit`, distinct from `CI status
#     unavailable`. Neither reads as a pass.
#   * No value that decides a selection or an emitted result is derived through an
#     external PATH tool (`tr`/`sed`/`wc`/`cut`): those are not preflight
#     prerequisites, and a missing one would silently change the answer rather
#     than fail. Sanitization still uses `tr`/`cut`, where a missing tool empties
#     the pipeline and the name fails CLOSED to `(unnamed check)`.
#   * `gh` routes through lib/resolve-gh.sh, `jq` through lib/resolve-jq.sh.
#
# Reads from the environment: REPO, HEAD_SHA, SELF_WORKFLOW_NAME.
#
# SECURITY: every name rendered here originates from a workflow file or a check
# run that a pull request can add, so it is attacker-controlled text entering a
# `pull_request_target` prompt. Names are sanitized to printable ASCII with
# backticks/angle brackets/newlines removed, truncated to 120 characters, and
# capped at 50 signal lines (plus one line naming how many were dropped). The
# conclusion field is sanitized the same way and capped at 40 characters; it is a
# constrained API fact (`success`/`failure`/`in_progress`), never free text, so the
# cap is a belt-and-braces bound rather than a load-bearing one.
# Sanitization is a security control, not cosmetics.

set -u

_SCC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Guarded source: a missing sibling degrades to the bare tool with a breadcrumb,
# never an unbound-variable abort under `set -u`.
# shellcheck source=../lib/resolve-gh.sh
. "$_SCC_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  # Partial-copy degradation only: the `:-` form is the sanctioned fallback shape
  # — the #245 peer-completeness pin forbids a bare `:=gh` default.
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi
# shellcheck source=../lib/resolve-jq.sh
. "$_SCC_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

REPO="${REPO:-}"
HEAD_SHA="${HEAD_SHA:-}"
SELF_WORKFLOW_NAME="${SELF_WORKFLOW_NAME:-Devflow Review (auto-trigger)}"

MAX_NAME_LEN=120
MAX_SIGNALS=50

# The single fail-closed exit. Prints the literal the prompt renders when the CI
# state could not be determined, so the engine reads "unknown", never "green".
unavailable() {  # breadcrumb
  echo "summarize-ci-checks: $1" >&2
  echo "CI status unavailable"
  exit 0
}

gh_err_detail() { [ -s "$1" ] && cat "$1" || echo 'no error output captured'; }

[ -n "$REPO" ] || unavailable "REPO is empty — cannot query CI for this head."
[ -n "$HEAD_SHA" ] || unavailable "HEAD_SHA is empty — cannot query CI for this head."

# ── (1) Actions workflow runs for the head, excluding PRFlow's own workflow, then
# ── that run's jobs. This is what produces the `lib + python tests` signal.
# `--paginate` emits CONCATENATED JSON arrays/objects, so every selection is
# preceded by a `-s` slurp + flatten, exactly as derive-review-preconditions.sh does.
_runs_err=$(mktemp 2>/dev/null) || _runs_err=/dev/null
if ! RUNS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/actions/runs?head_sha=$HEAD_SHA" 2>"$_runs_err"); then
  _detail="$(gh_err_detail "$_runs_err")"
  [ "$_runs_err" = /dev/null ] || rm -f "$_runs_err"
  unavailable "workflow-runs query failed for $HEAD_SHA ($_detail)."
fi
[ "$_runs_err" = /dev/null ] || rm -f "$_runs_err"

[ -n "$RUNS_JSON" ] || unavailable "workflow-runs query returned an empty payload for $HEAD_SHA."
if ! RUN_IDS=$(printf '%s' "$RUNS_JSON" | "$DEVFLOW_JQ" -rs --arg self "$SELF_WORKFLOW_NAME" '
      map(if type == "object" then ((.workflow_runs // []) | if type == "array" then . else error("workflow_runs is not an array") end) else error("non-object page") end)
      | add // []
      | map(select(((.name // "") | strings) != $self))
      | .[] | (.id | tostring)' 2>/dev/null); then
  unavailable "workflow-runs payload could not be parsed for $HEAD_SHA (jq failed, or the payload was not JSON / not an object page)."
fi

# Bound the per-run jobs queries. Each surviving run costs one paginated API call on
# the critical path of a paid review's prompt composition, and a busy head (re-runs,
# matrix expansions) can carry dozens. The runs endpoint returns newest-first, so the
# cap keeps the most recent runs. A dropped run is announced, never silent.
MAX_RUNS=30
RUN_COUNT=0
for _rid in $RUN_IDS; do RUN_COUNT=$((RUN_COUNT + 1)); done
if [ "$RUN_COUNT" -gt "$MAX_RUNS" ]; then
  echo "summarize-ci-checks: $RUN_COUNT non-self workflow runs for $HEAD_SHA exceeds the $MAX_RUNS-run query cap; summarizing the $MAX_RUNS most recent and skipping $((RUN_COUNT - MAX_RUNS))." >&2
  _kept=""
  _n=0
  for _rid in $RUN_IDS; do
    [ "$_n" -lt "$MAX_RUNS" ] || break
    _kept="$_kept $_rid"
    _n=$((_n + 1))
  done
  RUN_IDS="$_kept"
fi

SIGNALS_FILE=$(mktemp 2>/dev/null) || unavailable "could not allocate a temp file for the CI signal list (mktemp failed)."
# shellcheck disable=SC2064  # expand SIGNALS_FILE now, not at trap time
trap "rm -f '$SIGNALS_FILE'" EXIT

# A job whose `conclusion` is null (still running) renders with its `status`
# (e.g. `in_progress`). Never omitted, and never coerced to a passing value —
# a `// "success"`-style default here is precisely the documented-off-switch bug.
# One error-capture file for the whole loop, truncated per iteration, rather than a
# mktemp+unlink pair per run. Every `unavailable` call inside the loop exits, so the
# post-loop `rm -f` below is unreachable on those paths — register the file with the EXIT
# trap instead. (`_runs_err`/`_checks_err` unlink themselves before their own `unavailable`
# calls; only this one is opened across a body that can exit.)
_jobs_err=$(mktemp 2>/dev/null) || _jobs_err=/dev/null
# shellcheck disable=SC2064  # expand both paths now, not at trap time
[ "$_jobs_err" = /dev/null ] || trap "rm -f '$SIGNALS_FILE' '$_jobs_err'" EXIT
for _run_id in $RUN_IDS; do
  [ "$_jobs_err" = /dev/null ] || : > "$_jobs_err"
  if ! JOBS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/actions/runs/$_run_id/jobs" 2>"$_jobs_err"); then
    unavailable "jobs query failed for workflow run $_run_id on $HEAD_SHA ($(gh_err_detail "$_jobs_err"))."
  fi
  [ -n "$JOBS_JSON" ] || unavailable "jobs query returned an empty payload for workflow run $_run_id."
  if ! printf '%s' "$JOBS_JSON" | "$DEVFLOW_JQ" -rs '
        map(if type == "object" then ((.jobs // []) | if type == "array" then . else error("jobs is not an array") end) else error("non-object page") end)
        | add // []
        | map(select(type == "object"))
        | .[] | ((((.name // "") | tostring) | gsub("[\\n\\r\\t]"; " ")) + "\t" + (((.conclusion // .status // "unknown") | tostring) | gsub("[\\n\\r\\t]"; " ")))' \
        >> "$SIGNALS_FILE" 2>/dev/null; then
    unavailable "jobs payload could not be parsed for workflow run $_run_id (jq failed, or the payload was not JSON / not an object page)."
  fi
done
[ "$_jobs_err" = /dev/null ] || rm -f "$_jobs_err"

# ── (2) External (non-Actions app) check runs. Actions job check-runs are already
# ── counted once via the jobs API above, so excluding the `github-actions` app is
# ── what stops them being counted twice. The review check-run is excluded by name
# ── (`PRFlow Review`, plus the superseded `Devflow Review`) so the reviewer never
# ── sees its own in-progress check reported as pending CI.
# The `filter` parameter defaults to `latest`, so one paginated call returns the
# latest run per check name.
_checks_err=$(mktemp 2>/dev/null) || _checks_err=/dev/null
if ! CHECKS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/commits/$HEAD_SHA/check-runs" 2>"$_checks_err"); then
  _detail="$(gh_err_detail "$_checks_err")"
  [ "$_checks_err" = /dev/null ] || rm -f "$_checks_err"
  unavailable "check-runs query failed for $HEAD_SHA ($_detail)."
fi
[ "$_checks_err" = /dev/null ] || rm -f "$_checks_err"

[ -n "$CHECKS_JSON" ] || unavailable "check-runs query returned an empty payload for $HEAD_SHA."
if ! printf '%s' "$CHECKS_JSON" | "$DEVFLOW_JQ" -rs '
      map(if type == "object" then ((.check_runs // []) | if type == "array" then . else error("check_runs is not an array") end) else error("non-object page") end)
      | add // []
      | map(select(type == "object"))
      | map(select((((.app.slug // "") | tostring) != "github-actions")
                   and (((.name // "") | tostring) != "PRFlow Review")
                   and (((.name // "") | tostring) != "Devflow Review")))
      | .[] | ((((.name // "") | tostring) | gsub("[\\n\\r\\t]"; " ")) + "\t" + (((.conclusion // .status // "unknown") | tostring) | gsub("[\\n\\r\\t]"; " ")))' \
      >> "$SIGNALS_FILE" 2>/dev/null; then
  unavailable "check-runs payload could not be parsed for $HEAD_SHA (jq failed, or the payload was not JSON / not an object page)."
fi

# ── Render. Sanitize, truncate, cap.
# Counted with bash builtins, not `wc`: this value selects between "no CI ran" and
# "render the signals", and an absent/differing `wc` would make a head that DOES
# carry signals render as "No CI signals reported" — an absent tool silently
# reading as an absent CI result. `tr`/`wc`/`cut` are not preflight prerequisites.
TOTAL=0
while IFS= read -r _ignored; do TOTAL=$((TOTAL + 1)); done < "$SIGNALS_FILE"
if [ "$TOTAL" -eq 0 ]; then
  echo "summarize-ci-checks: no CI signals found for $HEAD_SHA (no non-self workflow jobs and no external check runs)." >&2
  echo "No CI signals reported for this commit"
  exit 0
fi

EMITTED=0
while IFS="$(printf '\t')" read -r _name _conclusion; do
  [ "$EMITTED" -lt "$MAX_SIGNALS" ] || break
  # Strip everything outside printable ASCII, then the fence/markup characters that
  # would let an injected name escape the fenced block it is rendered inside.
  # Tabs/newlines were already squashed to spaces inside jq, and the tab is the field
  # separator consumed above — so the name cannot carry one here. Keep only printable
  # ASCII, then drop the characters that could let a name escape the fence it renders in.
  _clean=$(printf '%s' "$_name" \
    | LC_ALL=C tr -cd '\40-\176' \
    | LC_ALL=C tr -d '`<>' \
    | cut -c1-"$MAX_NAME_LEN")
  [ -n "$_clean" ] || _clean="(unnamed check)"
  _cc=$(printf '%s' "$_conclusion" | LC_ALL=C tr -cd '\40-\176' | LC_ALL=C tr -d '`<>' | cut -c1-40)
  [ -n "$_cc" ] || _cc="unknown"
  printf '%s: %s\n' "$_clean" "$_cc"
  EMITTED=$((EMITTED + 1))
done < "$SIGNALS_FILE"

if [ "$TOTAL" -gt "$MAX_SIGNALS" ]; then
  printf '(%s further CI signal(s) not shown)\n' "$((TOTAL - MAX_SIGNALS))"
fi
exit 0

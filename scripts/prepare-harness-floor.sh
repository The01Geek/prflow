#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# prepare-harness-floor.sh — the backstop-step glue for the harness-side cost floor
# (issue #475). It is the branch-selecting shell the CLAUDE.md inline-workflow-shell
# convention keeps OUT of the workflow YAML (the scripts/describe-denial-count.sh
# precedent): a mis-selected arm here silently defeats the floor while the workflow
# still "works", so every branch is driven directly by lib/test/run.sh.
#
# Usage:
#   prepare-harness-floor.sh <execution_file> <command> <candidate_number> <cost_out_file>
#
#   <execution_file>   claude-code-action's steps.claude.outputs.execution_file path.
#   <command>          the gate's resolved command (a full `/devflow:<class> [N]`
#                      string on devflow.yml, or the bare class `implement` on
#                      devflow-implement.yml). The class and an explicit trailing PR
#                      number are parsed from it.
#   <candidate_number> the fallback context number: the PR the command ran on
#                      (devflow.yml), or the ISSUE number the implement run is for
#                      (devflow-implement.yml).
#   <cost_out_file>    where the reader's normalized cost JSON is written (empty/absent
#                      when the floor is inert). The backstop step reads it into
#                      DEVFLOW_EXECUTION_COST.
#
# It:
#   1. runs scripts/extract-execution-cost.py over the execution file → the cost JSON;
#   2. normalizes <command> to a class and extracts an explicit trailing PR number;
#   3. resolves/verifies the PR the record is keyed to (gh via lib/resolve-gh.sh);
#   4. prints four eval-able env assignments to STDOUT — DEVFLOW_EXECUTION_PR,
#      DEVFLOW_COMMAND_CLASS, DEVFLOW_ISSUE_NUMBER and DEVFLOW_NO_PR_REASON — for
#      the `bash "$HELPER" --persist` line.
#
# Every non-happy branch emits a SPECIFIC ::warning:: so a skipped skeleton/inert floor
# is auditable in the step log. Best-effort: ALWAYS exits 0 (the ensure-label.sh
# contract), so the always() backstop step is never aborted.
set -uo pipefail

# gh: resolved once via the shared execution-verified resolver (a non-empty DEVFLOW_GH
# still wins, so the test stub is untouched). The verify/resolve calls below run under
# GH_TOKEN=github.token (job-lifetime-valid; the job-start App token may be past its
# ~60-minute lifetime by backstop time — the #287 hazard).
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
READER="$HERE/extract-execution-cost.py"

EXEC_FILE="${1:-}"
COMMAND="${2:-}"
CANDIDATE="${3:-}"
COST_OUT="${4:-}"

# Emit the four eval-able env assignments and exit 0. $1 = PR, $2 = command class,
# $3 = issue number, $4 = the reason no PR resolved.
#
# Sanitize HERE rather than trusting each call site: both workflows run
# `eval "$(bash prepare-harness-floor.sh …)"`, so an operand carrying a single quote
# breaks out of the quoting below and executes. The candidate number reaches this function
# unvalidated on the implement arm — on its unusable-issue branch it is by construction
# not a number — so the one place whose contract asserts the shape is the place that
# enforces it. A value outside its shape is emitted EMPTY, which every consumer already
# treats as "not established".
#
# $3 is non-empty ONLY on the `implement` arm. Every other class's <candidate_number> is
# a PR number, so emitting it here would key the PR-less record to a PR as if it were an
# issue. devflow.yml's trigger negates /prflow:implement, so class `implement` reaches
# this glue only from devflow-implement.yml, whose candidate is the issue number.
_emit() {
  local pr="${1:-}" class="${2:-}" issue="${3:-}" reason="${4:-}"
  case "$pr" in ''|*[!0-9]*) pr="" ;; esac
  case "$issue" in ''|*[!0-9]*) issue="" ;; esac
  case "$class" in
    review|review-and-fix|pr-description|implement) ;;
    *) class="" ;;
  esac
  case "$reason" in
    issue-number-unusable|gh-lookup-failed|no-closing-pr-found|unestablished) ;;
    *) reason="" ;;
  esac
  printf "DEVFLOW_EXECUTION_PR='%s'\n" "$pr"
  printf "DEVFLOW_COMMAND_CLASS='%s'\n" "$class"
  printf "DEVFLOW_ISSUE_NUMBER='%s'\n" "$issue"
  printf "DEVFLOW_NO_PR_REASON='%s'\n" "$reason"
  exit 0
}

# The reader intentionally prints a normalized all-null object for a parsed file with no
# figures (AC2). That object is valid reader output but is not cost coverage. Consume the
# reader's normalized JSON contract directly and succeed only when at least one top-level
# figure, per-token figure, or model-usage object is established.
_cost_has_figures() {
  printf '%s' "$1" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
tokens = value.get("tokens")
has_figure = any(
    value.get(key) is not None
    for key in ("cost_usd", "model_usage", "num_turns", "duration_ms")
)
if isinstance(tokens, dict):
    has_figure = has_figure or any(item is not None for item in tokens.values())
raise SystemExit(0 if has_figure else 1)
' 2>/dev/null
}

# ── Normalize the command to a class + optional explicit PR number ───────────
# The accepted command namespaces are DERIVED from the declared plugin identity, never
# hardcoded. This consumer reads the gate's RESOLVED command token, and the detector
# emits that token in the CANONICAL namespace — so a hardcoded prefix stops matching the
# moment the plugin is renamed. That is not hypothetical: a hardcoded `/devflow:` strip
# missed every `/prflow:` token after the rename, CLASS fell through the vocabulary case
# below to "", and the per-class cost floor was recorded with no class at all. Deriving
# the set keeps a third namespace working too, which two hardcoded literals would not.
CMD="${COMMAND#/}"                  # drop the leading slash (a bare class has none)
while IFS= read -r _ns; do
  case "$_ns" in
    '') continue ;;
  esac
  case "$CMD" in
    "$_ns":*) CMD="${CMD#"$_ns":}"; break ;;
  esac
done <<EOF
$(python3 "$HERE/../lib/plugin_identity.py" --plugin-names 2>/dev/null || true)
EOF
CLASS="${CMD%% *}"                  # first token
REST="${CMD#"$CLASS"}"; REST="${REST# }"   # trailing args, one leading space dropped
EXPLICIT_NUM=""
case "$REST" in
  ''|*[!0-9]*) : ;;                 # no purely-numeric explicit target
  *) EXPLICIT_NUM="$REST" ;;        # `/prflow:review-and-fix 123` → 123
esac
# Sanitize the class to the known vocabulary; anything else is "" (no record class).
# A mismatch is ANNOUNCED here, at the point of classification: the defect this guards
# is a silent disarm, where a renamed namespace leaves the floor recording an empty
# class. The downstream dispatch warning only fires on runs that get that far, so a
# future rename must fail loud HERE rather than depend on reaching it.
case "$CLASS" in
  review|review-and-fix|pr-description|implement) : ;;
  *)
    echo "::warning::prepare-harness-floor: command '$COMMAND' did not classify (token '$CLASS' is not one of review|review-and-fix|pr-description|implement); the per-class cost floor will be recorded with NO class. If the plugin command namespace changed, the namespace set derived from lib/plugin_identity.py --plugin-names did not cover it." >&2
    CLASS="" ;;
esac

# ── Run the reader over the execution file → cost JSON ───────────────────────
# An inert COST does NOT short-circuit the PR resolution below. DEVFLOW_EXECUTION_PR
# used to be the cost floor's operand alone, so each inert arm emitted an empty PR and
# exited here. It has a SECOND consumer now — the permission-denial forensics floor's
# skeleton arm in lib/efficiency-trace.sh, which keys its record `pr-<N>-<run-id>.json`
# — and those two operands fail INDEPENDENTLY: a run that dies before writing cost
# figures can still have produced denials worth persisting. Short-circuiting here made
# the denial skeleton unreachable on exactly that path (empty COST *and* empty PR), so
# the arms below record the cost as inert and fall through. The cost floor itself is
# unaffected: apply_harness_floor returns at its first guard on an empty
# DEVFLOW_EXECUTION_COST, so no cost skeleton is written and no all-null harness_cost is
# staged — a non-empty PR beside an empty COST changes nothing on the cost side.
# Each arm keeps its own distinct named breadcrumb (AC7): the id-rename hazard would
# otherwise disarm the floor silently.
COST=""
COST_INERT=""
if [ -z "$EXEC_FILE" ] || [ ! -f "$EXEC_FILE" ] || [ ! -s "$EXEC_FILE" ]; then
  echo "::warning::prepare-harness-floor: harness cost floor inert this run: execution file absent" >&2
  COST_INERT=1
else
  # Do NOT suppress the reader's stderr: its breadcrumb (OSError / empty / JSON-garbage —
  # the exact reason COST comes back empty here) must reach the step log so the "see the
  # reader's breadcrumb" message below points at a breadcrumb that actually appears. Only
  # stdout is captured into COST; the reader's stderr flows to this step's log.
  COST="$(python3 "$READER" "$EXEC_FILE" || true)"
  if [ -z "$COST" ]; then
    echo "::warning::prepare-harness-floor: harness cost floor inert this run: execution file could not be parsed for cost (see the reader's breadcrumb above)" >&2
    COST_INERT=1
  elif ! _cost_has_figures "$COST"; then
    echo "::warning::prepare-harness-floor: harness cost floor inert this run: execution file carried no cost or usage figures; refusing to stage an all-null harness_cost" >&2
    COST_INERT=1
  fi
fi
if [ -n "$COST_INERT" ]; then
  # Empty the handoff so no caller reads a stale cost from a previous invocation.
  [ -n "$COST_OUT" ] && : > "$COST_OUT" 2>/dev/null || true
elif [ -n "$COST_OUT" ]; then
  # Cost is available — stage it for --persist.
  printf '%s\n' "$COST" > "$COST_OUT" 2>/dev/null \
    || echo "::warning::prepare-harness-floor: could not write cost JSON to '$COST_OUT'; the merge/skeleton arms will be inert this run" >&2
fi

# ── Resolve DEVFLOW_EXECUTION_PR (the skeleton slug; merge arm does not need it) ──
# Verify NUM names a real PR via REST (the {owner}/{repo} placeholder form that works
# under a repo-scoped token — CLAUDE.md's gh-porcelain gotcha). Returns 0 iff NUM is a PR.
_verify_pr() {
  local n="$1" out
  case "$n" in ''|*[!0-9]*) return 1 ;; esac
  out="$("$DEVFLOW_GH" api "repos/{owner}/{repo}/pulls/$n" --jq '.number' 2>/dev/null)" && [ "$out" = "$n" ]
}

# Resolve the PR that CLOSES issue $1 (the implement case — "the PR opened for the
# issue"). Uses `gh pr list --search … --json closingIssuesReferences`, the same
# branch-naming-independent closes-issue predicate lib/scan.sh and the Phase-1 resume
# pre-check use. Prints the PR number (or nothing). Best-effort.
#
# Reports WHICH failure fired through its EXIT CODE, never a variable: the sole caller
# invokes this in a command substitution, so an assignment made here happens in a
# subshell the parent never sees, and the reason would always read empty. 2 = the issue
# number is unusable, 3 = the gh lookup itself failed, 4 = gh succeeded and no closing PR
# exists. Never collapse the three onto one token: a transport failure and a genuinely
# PR-less run are different facts, and the PR-less record's reason field must not assert
# a cause this code did not observe.
_resolve_pr_for_issue() {
  local issue="$1" num rc
  case "$issue" in
    ''|*[!0-9]*) return 2 ;;
  esac
  num="$("$DEVFLOW_GH" pr list --search "${issue} in:body" --state all \
        --json number,closingIssuesReferences \
        --jq "map(select(any(.closingIssuesReferences[]?; .number == ${issue}))) | (.[0].number // empty)" 2>/dev/null)"
  rc=$?
  [ "$rc" -eq 0 ] || return 3
  [ -n "$num" ] || return 4
  printf '%s\n' "$num"
}

# The exit code above → the fixed-vocabulary token the PR-less record carries.
_no_pr_reason_for_rc() {
  case "$1" in
    2) printf 'issue-number-unusable\n' ;;
    3) printf 'gh-lookup-failed\n' ;;
    4) printf 'no-closing-pr-found\n' ;;
    *) printf 'unestablished\n' ;;
  esac
}

case "$CLASS" in
  pr-description)
    # "no record" is pr-description's healthy by-design state (AC6): no skeleton.
    echo "::warning::prepare-harness-floor: no record by design for command class 'pr-description'; DEVFLOW_EXECUTION_PR left empty (no skeleton)" >&2
    _emit "" "$CLASS" ;;
  review|review-and-fix)
    NUM="${EXPLICIT_NUM:-$CANDIDATE}"
    if [ -z "$NUM" ]; then
      echo "::warning::prepare-harness-floor: no PR number resolved for command class '$CLASS' (empty command target and context number); DEVFLOW_EXECUTION_PR left empty" >&2
      _emit "" "$CLASS"
    fi
    if _verify_pr "$NUM"; then
      _emit "$NUM" "$CLASS"
    else
      echo "::warning::prepare-harness-floor: candidate number '$NUM' does not name a real PR (not a PR, or the gh lookup failed); DEVFLOW_EXECUTION_PR left empty (skeleton skipped)" >&2
      _emit "" "$CLASS"
    fi ;;
  implement)
    PR="$(_resolve_pr_for_issue "$CANDIDATE")"
    PR_RC=$?
    if [ "$PR_RC" -eq 0 ]; then
      _emit "$PR" "$CLASS" "$CANDIDATE" ""
    else
      NO_PR_REASON="$(_no_pr_reason_for_rc "$PR_RC")"
      echo "::warning::prepare-harness-floor: could not resolve the PR opened for issue '$CANDIDATE' (reason: $NO_PR_REASON); DEVFLOW_EXECUTION_PR left empty, DEVFLOW_ISSUE_NUMBER carries the issue so the PR-less record can still be keyed" >&2
      _emit "" "$CLASS" "$CANDIDATE" "$NO_PR_REASON"
    fi ;;
  *)
    echo "::warning::prepare-harness-floor: unrecognized command '$COMMAND' (no record-deriving class); DEVFLOW_EXECUTION_PR left empty" >&2
    _emit "" "$CLASS" ;;
esac

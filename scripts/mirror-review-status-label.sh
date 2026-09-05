#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# mirror-review-status-label.sh <pr-number> <state>
#
# Mirror a cloud /prflow:review run's status onto one of four managed labels on
# the pull request and each issue it closes (issue #104), so review state is
# visible from the issue/PR list without opening the run's progress comment. The
# labels are a derived mirror of the run's progress comment, which stays the
# source of truth — the same relationship the implement status labels (#2117)
# have to the workpad.
#
# <state> is one of:
#   reviewing         -> PRFlow:Reviewing        (1d76db)
#   approved          -> PRFlow:Approved         (0e8c31)
#   changes-requested -> PRFlow:ChangesRequested (e4a11b)
#   review-failed     -> PRFlow:ReviewFailed     (c8201c)
#
# The reconcile is EXACT-MEMBERSHIP over just those four names (mirroring
# scripts/workpad.py's _reconcile_managed_label): it removes whichever of the
# four is stale and adds the target, and never touches the implement labels
# (PRFlow:Implementing/Stuck/Complete) or the PRFlow provenance label. A label
# definition the repository does not carry is created on the first add that
# needs it, then the add is retried once, at most one creation per invocation.
#
# Label writes go through the REST endpoints
#   GET/POST repos/{owner}/{repo}/issues/{number}/labels
#   DELETE   repos/{owner}/{repo}/issues/{number}/labels/{name}
#   POST     repos/{owner}/{repo}/labels
# via `gh api`, whose `{owner}`/`{repo}` placeholders `gh` fills from the git
# remote (the form lib/test/lint-gh-api-repo-path.py enforces) — so a repo-scoped
# token (a GitHub App installation token with issues:write) suffices, without the
# org-scoped GraphQL resolution that `gh issue/pr edit --add-label` triggers.
#
# OUTCOME CONTRACT (the closed set): the helper ALWAYS exits 0 (a label hiccup can
# never abort the invoking workflow step, and so never its job) and prints exactly
# ONE of these six outcome tokens to STDOUT:
#   * applied         — at least one label add/delete write landed.
#   * already-current — every target already carried exactly the target label; no write.
#   * disabled        — review_status_labels.enabled did not resolve to `true`; no API call.
#   * no-target       — there was no target to label at all (no PR and no closing issue).
#   * api-failure     — a label list/add/delete request failed; a stderr line names the request.
#   * arg-slip        — a missing/non-numeric PR number or an unknown <state> (a caller arg-slip).
# The stdout token is a selection value, so it is derived with bash builtins only
# (no tr/sed/cut) per CLAUDE.md's guard-class-2 rule. A harness refusal produces NO
# output at all — the only outcome that yields no token.
set -uo pipefail

_MRSL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh binary: resolved once via the single-source resolver (execution-verified); an
# explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$_MRSL_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi

# `${1:-}`/`${2:-}`, NOT `${1:?}`: a `${1:?}` aborts with a raw bash usage line and
# rc 1, breaking the "ALWAYS exits 0 + one token" contract and matching none of the
# tokens callers route on (the same reasoning apply-labels.sh/ensure-label.sh carry).
PR_NUMBER="${1:-}"
STATE="${2:-}"

# The four managed review labels and their pinned colours. `case`, not an
# associative array, so the SELECTION never depends on anything but bash builtins.
case "$STATE" in
    reviewing)         TARGET="PRFlow:Reviewing";        TARGET_COLOR="1d76db" ;;
    approved)          TARGET="PRFlow:Approved";         TARGET_COLOR="0e8c31" ;;
    changes-requested) TARGET="PRFlow:ChangesRequested"; TARGET_COLOR="e4a11b" ;;
    review-failed)     TARGET="PRFlow:ReviewFailed";     TARGET_COLOR="c8201c" ;;
    *)
        echo "arg-slip"
        echo "devflow: warning: mirror-review-status-label.sh got an unknown state '${STATE}' (args: $*); expected one of reviewing|approved|changes-requested|review-failed. No label written. This is NOT a harness denial — it is a caller arg-slip." >&2
        exit 0 ;;
esac

case "$PR_NUMBER" in
    ''|*[!0-9]*)
        echo "arg-slip"
        echo "devflow: warning: mirror-review-status-label.sh got a non-numeric PR number '${PR_NUMBER}' (args: $*); no label written. This is NOT a harness denial — it is a caller arg-slip, most likely a shell variable that did not survive into this command." >&2
        exit 0 ;;
esac

# The complete managed set: the reconcile removes any of these that is not the
# target, and touches nothing else (so the three implement labels and the PRFlow
# provenance label are invisible to it — exactly workpad.py's exact-membership rule).
_MRSL_MANAGED=("PRFlow:Reviewing" "PRFlow:Approved" "PRFlow:ChangesRequested" "PRFlow:ReviewFailed")
_mrsl_is_managed() {  # <label-name> -> rc 0 when the name is one of the four review labels
    local n
    for n in "${_MRSL_MANAGED[@]}"; do
        [ "$1" = "$n" ] && return 0
    done
    return 1
}

# The description is pinned across all four review labels (AC).
_MRSL_DESC="PRFlow review status"

# Resolve the enable flag through config-get.sh. Prefer the vendored copy at the
# CWD-relative path the workflow steps use; fall back to the config-get.sh that
# sits beside THIS helper (its repo/vendored sibling), which is present whether the
# helper runs from the vendored tree or the repo. config-get.sh itself resolves the
# config from the git repo root (CWD fallback). Only the literal string `true`
# enables the feature — every other shape (a JSON false/string "false"/empty/number/
# array/object/missing key/missing file, a non-zero resolver exit, or an absent
# resolver) leaves it OFF and issues no label request (the truthy-off direction).
CFG=.prflow/vendor/prflow/scripts/config-get.sh
[ -f "$CFG" ] || CFG="$_MRSL_DIR/config-get.sh"
ENABLED=false
if [ -f "$CFG" ]; then
    ENABLED="$(bash "$CFG" .review_status_labels.enabled false 2>/dev/null || echo false)"
fi
case "$ENABLED" in
    true) : ;;
    *)
        echo "disabled"
        echo "devflow: mirror-review-status-label.sh: review_status_labels.enabled is not 'true' (resolved '${ENABLED}'); no label request made." >&2
        exit 0 ;;
esac

# Resolve the labeling targets: the PR itself, and each issue the PR closes. The
# PR number was validated numeric above, so the PR is always a target. The closing
# issues come from `gh pr view` (not `gh api`, so no {owner}/{repo} placeholder
# applies here); a failure to enumerate them degrades the ISSUE side with a
# breadcrumb and still labels the PR, and an empty set prints the no-target
# breadcrumb for the issue side while still labeling the PR alone (AC).
TARGETS=("$PR_NUMBER")
CLOSING_RAW=""
if CLOSING_RAW="$("$DEVFLOW_GH" pr view "$PR_NUMBER" --json closingIssuesReferences --jq '.closingIssuesReferences[].number' 2>/dev/null)"; then
    CLOSING_COUNT=0
    while IFS= read -r _num; do
        [ -n "$_num" ] || continue
        case "$_num" in *[!0-9]*) continue ;; esac
        TARGETS+=("$_num")
        CLOSING_COUNT=$((CLOSING_COUNT + 1))
    done <<< "$CLOSING_RAW"
    if [ "$CLOSING_COUNT" -eq 0 ]; then
        echo "devflow: mirror-review-status-label.sh: no-target for the issue side — PR #${PR_NUMBER} closes no issue; labeling the PR alone." >&2
    fi
else
    echo "devflow: warning: mirror-review-status-label.sh: could not resolve closing issues for PR #${PR_NUMBER} (gh pr view failed); labeling the PR alone (best-effort)." >&2
fi

# Defensive: no target at all (should not happen — the PR is always a target).
if [ "${#TARGETS[@]}" -eq 0 ]; then
    echo "no-target"
    echo "devflow: mirror-review-status-label.sh: no PR or closing-issue target to label; nothing written." >&2
    exit 0
fi

# Outcome accumulators. ANY_WRITE and ANY_FAIL are bash flags set by the RC of the
# gh calls below — a selection value derived with builtins only. LABEL_DEFINED is
# threaded across every target so the definition is created AT MOST ONCE per run.
ANY_WRITE=0
ANY_FAIL=0
LABEL_DEFINED=0

_mrsl_add() {  # <number> — add TARGET, creating+retrying once when undefined
    local number="$1"
    if "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/issues/${number}/labels" \
            -f "labels[]=${TARGET}" >/dev/null 2>&1; then
        ANY_WRITE=1
        return 0
    fi
    # The add was refused — most often because the repo does not define the label.
    # Create the definition once, then retry the add exactly once (mirroring
    # workpad.py's _add_managed_label create-then-retry shape).
    if [ "$LABEL_DEFINED" -eq 0 ]; then
        if ! "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/labels" \
                -f "name=${TARGET}" -f "color=${TARGET_COLOR}" -f "description=${_MRSL_DESC}" >/dev/null 2>&1; then
            echo "devflow: mirror-review-status-label.sh: could not create label definition '${TARGET}' (best-effort; retrying the add)." >&2
        fi
        LABEL_DEFINED=1
    fi
    if "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/issues/${number}/labels" \
            -f "labels[]=${TARGET}" >/dev/null 2>&1; then
        ANY_WRITE=1
        return 0
    fi
    ANY_FAIL=1
    echo "devflow: warning: mirror-review-status-label.sh: could not add label '${TARGET}' to #${number} (POST repos/{owner}/{repo}/issues/${number}/labels)." >&2
    return 1
}

_mrsl_reconcile() {  # <number> — reconcile #number's review labels to exactly TARGET
    local number="$1" current lbl found_target=0
    if ! current="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/issues/${number}/labels?per_page=100" --jq '.[].name' 2>/dev/null)"; then
        ANY_FAIL=1
        echo "devflow: warning: mirror-review-status-label.sh: could not list labels on #${number} (GET repos/{owner}/{repo}/issues/${number}/labels); not reconciled there." >&2
        return 0
    fi
    # Collect the managed review labels present, and whether the target is already there.
    local managed=()
    while IFS= read -r lbl; do
        [ -n "$lbl" ] || continue
        [ "$lbl" = "$TARGET" ] && found_target=1
        if _mrsl_is_managed "$lbl"; then
            managed+=("$lbl")
        fi
    done <<< "$current"
    # Already correct — exactly the target present and nothing else managed: no write.
    if [ "${#managed[@]}" -eq 1 ] && [ "${managed[0]}" = "$TARGET" ]; then
        return 0
    fi
    # Remove every managed review label that is not the target (each caught on its
    # own, so a 404 on a label that is not applied never aborts the add that follows).
    for lbl in ${managed[@]+"${managed[@]}"}; do
        [ "$lbl" = "$TARGET" ] && continue
        if "$DEVFLOW_GH" api -X DELETE "repos/{owner}/{repo}/issues/${number}/labels/${lbl}" >/dev/null 2>&1; then
            ANY_WRITE=1
        else
            ANY_FAIL=1
            echo "devflow: warning: mirror-review-status-label.sh: could not remove stale label '${lbl}' from #${number} (DELETE repos/{owner}/{repo}/issues/${number}/labels/${lbl}); continuing." >&2
        fi
    done
    # Add the target when missing.
    if [ "$found_target" -eq 0 ]; then
        _mrsl_add "$number"
    fi
    return 0
}

for _t in "${TARGETS[@]}"; do
    _mrsl_reconcile "$_t"
done

# Aggregate outcome, builtin-only precedence: a failed request wins (so a partial
# write is never reported as a clean apply), then any write, then all-current.
if [ "$ANY_FAIL" -eq 1 ]; then
    echo "api-failure"
elif [ "$ANY_WRITE" -eq 1 ]; then
    echo "applied"
else
    echo "already-current"
fi
exit 0

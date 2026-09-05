#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# retrospective-state-guard.sh
#
# The scheduled retrospective workflow's (devflow-retrospective.yml) state-PR guard.
# The weekly loop's processed-PR record advances only when a run's state PR
# (devflow/learnings-<date>) is merged into the default branch by a human, so running
# the loop again while such a PR is still open re-processes the same week. This guard:
#
#   * With NO open devflow/learnings-* state PR -> prints `proceed=true`: the caller
#     runs the retrospective.
#   * With an open devflow/learnings-* state PR -> ensures EXACTLY ONE open reminder
#     issue exists (created only when no open issue carries the reminder marker, so a
#     second guarded week leaves the existing one in place rather than filing a
#     duplicate), applies the reserved PRFlow provenance label best-effort, and prints
#     `proceed=false`: the caller skips the retrospective.
#
# OUTPUT CONTRACT: exactly one `proceed=true|false` line on STDOUT (the workflow reads
# it with `bash guard >> "$GITHUB_OUTPUT"`); every diagnostic goes to STDERR. The guard
# is fail-CLOSED on an unresolved state-PR query — a run that cannot establish whether a
# state PR is open must NOT re-process the week — so a query failure prints
# `proceed=false` with a breadcrumb.
#
# Reminder detection is by MARKER in the issue body, never by author or title prose, so
# a human-retitled reminder is still recognized. gh writes go through REST `gh api` with
# the `{owner}/{repo}` placeholders (repo-scope safe; GraphQL-resolving porcelain fails
# silently under a repo-scoped token — CLAUDE.md gotcha).
set -uo pipefail

_GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/resolve-gh.sh
. "$_GUARD_DIR/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# The reminder issue's marker — the sole reminder-detection key. Coupled to the suite's
# state-PR guard matrix (lib/test/run.sh), which drives this helper against a gh stub.
REMINDER_MARKER='<!-- prflow:retrospective-reminder -->'
STATE_BRANCH_PREFIX='devflow/learnings-'

emit() { printf 'proceed=%s\n' "$1"; }
# Single-source the fail-CLOSED skip arm: every unresolved-query / failed-write path prints its
# breadcrumb to stderr, emits proceed=false, and exits 0, so the caller skips the retrospective
# rather than risk re-processing an unmerged week. Routing all of them through one helper keeps
# that invariant provable at one site instead of re-asserted by hand at each early exit.
skip() { echo "$1" >&2; emit false; exit 0; }

# Resolve an open state PR (branch devflow/learnings-*), if any. Fail CLOSED: a query that
# does not run leaves the open-state unknown, which must skip the run rather than re-process
# the week, so an unresolved query prints proceed=false. Use REST `gh api --paginate` (not
# `gh pr list`, whose default 30-row window would silently DROP an aging state PR behind 30
# newer open PRs on a busy repo and read as "none open" — a fail-OPEN in the guard's own
# contract); pagination enumerates every open PR, so an open state PR can never fall outside
# the fetched set. Per page `--jq` emits each matching PR number; the guard only needs one.
if ! STATE_PR_MATCHES="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/pulls?state=open&per_page=100" \
        --jq ".[] | select(.head.ref | startswith(\"$STATE_BRANCH_PREFIX\")) | .number" 2>/dev/null)"; then
    skip "devflow: warning: retrospective-state-guard could not query open pull requests (the open-PR API query failed); skipping the retrospective this run rather than risk re-processing an unmerged week."
fi
# Take the first matching PR number across all pages (any open state PR triggers the skip).
STATE_PR=""
for _pr in $STATE_PR_MATCHES; do
    case "$_pr" in
        ''|*[!0-9]*) continue ;;
        *) STATE_PR="$_pr"; break ;;
    esac
done

if [ -z "$STATE_PR" ]; then
    # No open state PR — the last run's learnings were merged (or there was none), so
    # the processed-PR record on the default branch is current. Proceed.
    echo "devflow: retrospective-state-guard: no open ${STATE_BRANCH_PREFIX}* state PR; proceeding to the retrospective." >&2
    emit true
    exit 0
fi

echo "devflow: retrospective-state-guard: open state PR #${STATE_PR} (${STATE_BRANCH_PREFIX}*) is unmerged; skipping the retrospective and ensuring a single reminder issue." >&2

# Count open issues carrying the reminder marker in their body (excluding PRs, which the
# issues endpoint also returns). A query failure fails CLOSED toward NOT creating a
# duplicate: if we cannot establish that no reminder is open, do not file one.
if ! OPEN_REMINDERS="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/issues?state=open&per_page=100" \
        --jq "[.[] | select(.pull_request | not) | select((.body // \"\") | contains(\"$REMINDER_MARKER\"))] | length" 2>/dev/null)"; then
    skip "devflow: warning: retrospective-state-guard could not query open issues (the open-issues API query failed); NOT filing a reminder this run to avoid a duplicate. The retrospective stays skipped."
fi
# Sum the per-page counts --paginate emits (one integer per page).
_total=0
for _n in $OPEN_REMINDERS; do
    case "$_n" in
        ''|*[!0-9]*) continue ;;
        *) _total=$((_total + _n)) ;;
    esac
done

if [ "$_total" -gt 0 ]; then
    echo "devflow: retrospective-state-guard: a reminder issue is already open (${_total} carrying the marker); not filing a duplicate." >&2
    emit false
    exit 0
fi

# No reminder open — file exactly one. REST create (repo-scope safe), marker in the body.
TITLE='PRFlow retrospective paused: merge the open learnings state PR'
BODY="$REMINDER_MARKER
The weekly PRFlow retrospective is **paused** because an unmerged state PR is open:
**#${STATE_PR}** (branch \`${STATE_BRANCH_PREFIX}<date>\`).

The retrospective's processed-PR record only advances once that state PR is merged into
the default branch. Until then, each scheduled run skips the retrospective to avoid
re-processing the same week.

**To resume:**
1. Review and merge state PR #${STATE_PR}.
2. Manually dispatch the **PRFlow (retrospective)** workflow from the Actions tab
   (rather than waiting for the next Sunday), so the loop picks up where it left off.

This reminder is filed once, not weekly: while the state PR stays open it is left in
place, and it is re-created if closed before the state PR is merged."

if ! CREATED="$("$DEVFLOW_GH" api --method POST "repos/{owner}/{repo}/issues" \
        -f "title=$TITLE" -f "body=$BODY" --jq '.number' 2>/dev/null)"; then
    skip "devflow: warning: retrospective-state-guard could not file the reminder issue (the reminder-create API POST failed); the retrospective stays skipped."
fi

if [ -n "$CREATED" ]; then
    echo "devflow: retrospective-state-guard: filed reminder issue #${CREATED} for open state PR #${STATE_PR}." >&2
    # Best-effort provenance label. Do NOT drop the executable test: on a partial vendor
    # tree an ABSENT helper is otherwise swallowed by `|| true` exactly like a tolerated
    # label hiccup, leaving the reminder unlabeled with no attributable signal.
    if [ -x "$_GUARD_DIR/apply-labels.sh" ]; then
        "$_GUARD_DIR/apply-labels.sh" "$CREATED" PRFlow >/dev/null || true
    else
        echo "devflow: warning: retrospective-state-guard could not label reminder issue #${CREATED}: apply-labels.sh is missing or not executable at $_GUARD_DIR/apply-labels.sh (a partial vendor tree). The reminder is filed unlabeled; labeling never gates proceed." >&2
    fi
else
    echo "devflow: warning: retrospective-state-guard filed a reminder but got no issue number back; the retrospective stays skipped." >&2
fi

emit false
exit 0

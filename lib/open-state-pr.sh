#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# open-state-pr.sh — commit the learnings files onto a per-run branch and open/update a PR.
#
# Usage:
#   open-state-pr.sh [--branch <name>] [--base <ref>] [--dry-run]
#   open-state-pr.sh --follow-up <state-pr-number>   # commit .prflow/learnings/overrides.json
#                                                      onto that PR's head branch (no --dry-run)
#
# --base defaults to "main": the per-run branch is (re)created from that ref so
# the resulting PR diff contains only the learnings files, never whatever the
# operator happened to have checked out. The .prflow/learnings/* files are
# tracked (re-included by the !/.prflow/learnings/ negation in .gitignore, past
# the /.prflow/* ignore rule), so the checkout carries them onto the new branch
# as modified tracked files, which Step 2 then stages (plain git add) and commits.
#
# Prints the PR number to stdout (or "DRYRUN" in dry-run mode).
set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
# State-branch prefixes. The current spelling is produced; the superseded one is still
# accepted by --follow-up (and by the two readers) until it is retired — see
# lib/rename-map.json identifiers id "retrospective-state-branch".
STATE_BRANCH_PREFIX='prflow/learnings-'
STATE_BRANCH_PREFIX_SUPERSEDED='devflow/learnings-'
DEFAULT_BRANCH="${STATE_BRANCH_PREFIX}$(date -u +%F)"
BRANCH="$DEFAULT_BRANCH"
BASE="main"
DRY_RUN=0
FOLLOWUP_PR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch)    BRANCH="$2";      shift 2 ;;
        --base)      BASE="$2";        shift 2 ;;
        --follow-up) FOLLOWUP_PR="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=1;        shift   ;;
        *) echo "open-state-pr: unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins (injection for tests) ─────────────────────
# shellcheck source=resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# jq binary: resolved once via the sourced sibling resolver (issue #247), used
# below to count retrospective ENTRIES excluding #626 `skip` marker rows.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "open-state-pr: resolve-jq.sh could not be sourced — using bare 'jq'" >&2; : "${DEVFLOW_JQ:=jq}"; }

# ── --follow-up <state-pr-number> mode ────────────────────────────────────────
# Stage B (retrospective-weekly) files issues after the Step 7 state PR is opened,
# mutating .prflow/learnings/overrides.json in the working tree. This mode commits that
# overrides.json onto the state PR's OWN head branch — read from the PR, never re-derived
# from the date (so a run crossing UTC midnight still targets the branch the PR actually has).
# An EXIT trap restores the starting branch as this mode returns; a head outside the two
# state-branch prefixes is refused before commit, keeping unrelated branches untouched.
if [ -n "$FOLLOWUP_PR" ]; then
    FOLLOWUP_SUBJECT="chore(prflow): add overrides from Stage B filed issues"
    # --follow-up performs real git mutations on the state branch and has no dry-run
    # preview; accepting --dry-run here would mutate while every other mode honored it.
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "open-state-pr: --follow-up does not support --dry-run (it performs real git mutations on the state branch); pass one, not both" >&2
        exit 2
    fi
    _FU_START="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
    # Restore the starting branch however this mode exits, and REPORT a failed restoration
    # rather than suppressing it: swallowing the checkout's status exits 0 while left on the
    # state branch, silently stranding later work on the wrong branch. set -e aborts route
    # through EXIT, so this runs as an EXIT trap — a RETURN-trap or explicit-only restore
    # would miss them.
    _fu_restore_cleanup() {
        local _fu_status=$?
        # Disable recursive EXIT handling before this function's own exit calls.
        trap - EXIT
        # Non-force restoration only — never add -f/reset/clean/delete/retry here: carried
        # tracked, staged and untracked work must survive a failed restoration (AC5).
        if git checkout -q "$_FU_START" >/dev/null 2>&1; then
            exit "$_fu_status"
        fi
        # Restoration failed. Identify the branch left behind; an empty read is the read
        # having failed — report it unestablished, never as a claimed-restored branch.
        local _fu_remaining
        _fu_remaining="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
        if [ -n "$_fu_remaining" ]; then
            echo "open-state-pr: --follow-up: failed to restore the starting branch '${_FU_START}'; the checkout remains on '${_fu_remaining}'" >&2
        else
            echo "open-state-pr: --follow-up: failed to restore the starting branch '${_FU_START}'; the remaining branch is unestablished (git could not read HEAD)" >&2
        fi
        # An earlier operation failure stays the invocation's status (AC2); a restoration
        # failure after an otherwise-successful run makes the invocation fail (AC1).
        if [ "$_fu_status" -ne 0 ]; then
            exit "$_fu_status"
        fi
        exit 1
    }
    trap _fu_restore_cleanup EXIT

    _FU_HEAD="$("$DEVFLOW_GH" pr view "$FOLLOWUP_PR" --json headRefName --jq .headRefName 2>/dev/null || true)"
    if [ -z "$_FU_HEAD" ]; then
        echo "open-state-pr: --follow-up: could not resolve the head branch for PR #${FOLLOWUP_PR} (gh pr view returned nothing or failed)" >&2
        exit 1
    fi
    case "$_FU_HEAD" in
        "$STATE_BRANCH_PREFIX"*|"$STATE_BRANCH_PREFIX_SUPERSEDED"*) : ;;
        *)
            echo "open-state-pr: --follow-up: refusing to commit onto '${_FU_HEAD}' — not a ${STATE_BRANCH_PREFIX}* or ${STATE_BRANCH_PREFIX_SUPERSEDED}* state branch" >&2
            exit 1 ;;
    esac
    if ! git fetch origin "$_FU_HEAD" 1>&2; then
        echo "open-state-pr: --follow-up: git fetch of '${_FU_HEAD}' failed" >&2
        exit 1
    fi
    if ! git checkout -q "$_FU_HEAD" 1>&2; then
        echo "open-state-pr: --follow-up: git checkout of '${_FU_HEAD}' failed" >&2
        exit 1
    fi
    # Distinguish an absent overrides.json (no Stage-B overrides were produced) from a
    # present-but-identical one, so a missing-producer case is not laundered into the same
    # "unchanged" breadcrumb as the legitimate no-op. Both are a genuine no-op (exit 0).
    if [ ! -f .prflow/learnings/overrides.json ]; then
        echo "open-state-pr: --follow-up: .prflow/learnings/overrides.json is absent (no Stage-B overrides produced); nothing to commit" >&2
        exit 0
    fi
    git add .prflow/learnings/overrides.json
    if git diff --cached --quiet; then
        echo "open-state-pr: --follow-up: overrides.json is present but unchanged; nothing to commit" >&2
        exit 0
    fi
    if ! git commit -m "$FOLLOWUP_SUBJECT" -- .prflow/learnings/overrides.json 1>&2; then
        echo "open-state-pr: --follow-up: git commit of overrides.json onto '${_FU_HEAD}' failed" >&2
        exit 1
    fi
    if ! git push origin "$_FU_HEAD" 1>&2; then
        echo "open-state-pr: --follow-up: git push of '${_FU_HEAD}' failed — the overrides commit was made locally on '${_FU_HEAD}' but not pushed" >&2
        exit 1
    fi
    echo "open-state-pr: --follow-up: committed overrides.json onto ${_FU_HEAD} and pushed." >&2
    exit 0
fi

# ── Determine entry count ─────────────────────────────────────────────────────
# Count retrospective ENTRIES only — #626 `skip` marker rows are processed-PR
# bookkeeping, not retrospective analyses, so they must not inflate the "N entries"
# label. Count via jq (kind != "skip"); on any jq failure fall back to the raw line
# count so the label degrades to over-counting rather than breaking the commit.
N=0
if [ -f .prflow/learnings/retrospectives.jsonl ]; then
    N=$("$DEVFLOW_JQ" -s '[.[] | select((.kind // "") != "skip")] | length' \
        < .prflow/learnings/retrospectives.jsonl 2>/dev/null || true)
    # Fallback line count uses ONLY bash builtins. `wc`/`tr` are not guaranteed by
    # lib/preflight.sh (git/gh/jq/python3 only), and $N is an EMITTED value — it lands
    # in the commit subject's "(N entries)" label — so a missing PATH tool must not be
    # able to empty it (the repo's "emitted value must not depend on a non-preflight
    # PATH tool" rule). The `|| [ -n "$_line" ]` arm also counts a final line with no
    # trailing newline, which `wc -l` silently dropped.
    case "$N" in
        ''|*[!0-9]*)
            N=0
            while IFS= read -r _line || [ -n "$_line" ]; do
                N=$((N + 1))
            done < .prflow/learnings/retrospectives.jsonl
            ;;
    esac
fi

# ── Commit metadata ───────────────────────────────────────────────────────────
WEEK_LABEL="$(date -u +%G-W%V)"
SUBJECT="chore(prflow): retrospectives for ${WEEK_LABEL} (${N} entries)"
BODY="Retrospective entries from the $(date -u +%F) /prflow:retrospective-weekly run. Merge once CI passes."

# ── Helper: run or dry-run a command ─────────────────────────────────────────
# Progress output (git's carried-over `M<TAB>file` lines from `checkout -B`, and
# any porcelain the wrapped command prints) is sent to stderr, NOT stdout: this
# script's stdout contract is "only the resulting PR number" (callers capture it
# via `STATE_PR=$(open-state-pr.sh)`), so anything else on stdout pollutes that
# capture. Stderr (not /dev/null) preserves the output for debugging, mirroring
# the `gh pr create … >&2` redirect below.
_run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRYRUN: %s\n' "$*"
    else
        "$@" 1>&2
    fi
}

# ── Step 1: (re)create the per-run branch from $BASE ──────────────────────────
# Basing on $BASE (not the current HEAD) keeps the PR diff to just the learnings
# files even if the operator was on a feature branch when invoking the loop.
if [ "$DRY_RUN" -eq 0 ] && ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
    echo "open-state-pr: base ref '$BASE' not found — fetch it or pass --base" >&2
    exit 1
fi
_run git checkout -B "$BRANCH" "$BASE"

# ── Step 2: stage learnings files ─────────────────────────────────────────────
# Stage only files that exist: overrides.json is optional (created by meta-issue.sh);
# experiment-records.jsonl is optional (written by build-experiment-records.py between
# retrospective-weekly Steps 5 and 7 — issue #431 — so the state PR commits it and
# main's tree is clean entering Stage B).
if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRYRUN: git add <existing learnings files>\n'
else
    for _f in .prflow/learnings/retrospectives.jsonl .prflow/learnings/overrides.json .prflow/learnings/experiment-records.jsonl; do
        if [ -f "$_f" ]; then
            git add "$_f"
        fi
    done
fi

# ── Step 3: commit (skip if nothing staged) ───────────────────────────────────
if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRYRUN: git commit -m "%s" -m "%s"\n' "$SUBJECT" "$BODY"
else
    if git diff --cached --quiet; then
        echo "open-state-pr: nothing staged, skipping commit" >&2
    else
        # Redirect git's `[branch hash] subject` / `N files changed` summary to
        # stderr — it is progress output, and stdout is reserved for the PR number.
        git commit -m "$SUBJECT" -m "$BODY" 1>&2
    fi
fi

# ── Step 4: push ──────────────────────────────────────────────────────────────
PUSH_OPTS="-u origin $BRANCH"
if [ "$DRY_RUN" -eq 0 ]; then
    # `git push -u` prints a "branch '…' set up to track 'origin/…'" line to stdout;
    # redirect the push's stdout to stderr too, so stdout carries only the PR number.
    if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
        git push --force-with-lease -u origin "$BRANCH" 1>&2
    else
        git push -u origin "$BRANCH" 1>&2
    fi
else
    # Check whether remote branch exists (best-effort; don't fail in dry-run)
    if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
        printf 'DRYRUN: git push --force-with-lease %s\n' "$PUSH_OPTS"
    else
        printf 'DRYRUN: git push %s\n' "$PUSH_OPTS"
    fi
fi

# ── Step 5: open or update PR ─────────────────────────────────────────────────
if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRYRUN: %s pr list / pr create or pr edit\n' "$DEVFLOW_GH"
    echo "DRYRUN"
    exit 0
fi

EXISTING_PR="$("$DEVFLOW_GH" pr list --head "$BRANCH" --state open --json number --jq '.[0].number // empty')"

if [ -n "$EXISTING_PR" ]; then
    # gh pr edit prints the edited PR's URL to stdout (same convention as
    # gh pr create); keep it off our stdout, which carries only the PR number.
    "$DEVFLOW_GH" pr edit "$EXISTING_PR" --title "$SUBJECT" >&2
    echo "$EXISTING_PR"
else
    # gh pr create prints the new PR URL to stdout; keep it off our stdout
    # (callers capture stdout to read the PR number) but surface it for logs.
    "$DEVFLOW_GH" pr create \
        --base "$BASE" \
        --head "$BRANCH" \
        --title "$SUBJECT" \
        --body "$BODY" >&2
    # Re-list to get the number
    PR_NUMBER="$("$DEVFLOW_GH" pr list --head "$BRANCH" --state open --json number --jq '.[0].number // empty')"
    if [ -z "$PR_NUMBER" ]; then
        echo "open-state-pr: pr create succeeded but re-list returned no PR number" >&2
        exit 1
    fi
    echo "$PR_NUMBER"
fi

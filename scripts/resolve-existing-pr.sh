#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-existing-pr.sh — resolve whether `/devflow:implement` Phase 3.1 should ADOPT an
# already-open PR for the current head branch, CREATE a new one, or refuse to decide
# (issue #782, hardening the #755 guard).
#
# Why a helper rather than inline shell in the skill body: this is branch-selecting shell,
# the class CLAUDE.md requires real coverage for — "inline shell that selects a branch is
# extracted into a scripts/*.sh helper so the suite can drive each branch and its arm-order,
# because a grep-pin on a message literal is not coverage of the selection that chooses it."
# scripts/describe-denial-count.sh is the reference extraction. The #755 fix loop found two
# defects in the inline form across two iterations (an inlined branch read that degraded to
# an unfiltered repo-wide query, and a nondeterministic `.[0]` on a multi-PR head); both are
# exactly what a driven arm matrix catches mechanically.
#
# Usage: resolve-existing-pr.sh --issue <number> [--branch <name>] [--base <ref>]
#   --issue   the issue this run implements; used for the closes-issue validation.
#   --branch  the head branch. Omitted → read here via `git branch --show-current`. An
#             explicitly-passed EMPTY value is honored verbatim and routes to REFUSED —
#             it is not treated as omitted (the same "an explicit empty value is not a
#             request for the default" discipline config-get.sh's own arg gate carries).
#   --base    the run's base branch. Omitted → re-derived via config-get.sh (.base_branch,
#             falling back to `main`), the same read Phase 3.1's create arm performs. The
#             helper derives it internally because a `$BASE` resolved in one skill fence does
#             not survive into a later separate command on the cloud runner.
#
# CONTRACT — exactly one token line on stdout, with a matching exit code:
#
#   ADOPT <n> OK                  exit 0   an open PR was resolved AND both checks passed
#   ADOPT <n> WARN:<checks>       exit 0   resolved, but <checks> (a comma-separated subset
#                                          of `closes-issue`,`base-ref`, in that order)
#                                          did not hold — adoption still proceeds, this is a
#                                          visibility obligation, not a stop
#   CREATE                        exit 2   the query ran cleanly and found no open PR
#   REFUSED                       exit 3   the answer could not be established
#
# The 0 / 2 / 3 split mirrors the repo's established shape: `workpad.py id` uses 0 = found,
# 2 = scanned cleanly but absent, and `preflight.py` uses 3 = the measurement could not be
# established. Collapsing REFUSED onto CREATE is the fail-open this helper exists to prevent
# — creating on an unresolved query risks a second PR duplicating a prior attempt's, and
# adopting is impossible — so an unresolvable outcome is never reported as a clean "none".
#
# THE HELPER HAS NO SILENT PATH (mirroring apply-labels.sh): every outcome, and every cause
# within the shared REFUSED outcome, leaves its own stderr breadcrumb. That is what lets the
# caller read "no output at all" as a harness refusal rather than as an answer.
set -uo pipefail

_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh binary: resolved once via the single-source execution-verified resolver; an explicit
# DEVFLOW_GH still wins with no probe, so the test suite's stubbing contract is preserved.
# shellcheck source=../lib/resolve-gh.sh
. "$_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-existing-pr.sh could not source ../lib/resolve-gh.sh (a partial deployment carrying scripts/ without lib/?)" >&2
# Outcome check, not just sourceability — the same treatment the jq source below gets, and for
# the same reason: a missing sibling leaves `devflow_resolve_gh` undefined, `DEVFLOW_GH` empty,
# and the query then fails with a breadcrumb blaming GitHub for a broken install. Name the real
# cause here instead of misdirecting the reader downstream.
# The resolver is the ONLY producer of this value when the caller supplied none: the #245
# peer-completeness pin forbids any helper retaining a bare `DEVFLOW_GH:=gh` default, because
# a hardcoded fallback is exactly the un-probed bare `gh` the execution-verified resolver
# exists to replace (a present-but-unrunnable Windows/WSL shim). So the degraded arm does NOT
# substitute one — it breadcrumbs the broken install and REFUSES, which is also the honest
# answer: with no resolver there is no established gh, and an unestablished tool is not a
# reason to guess ("unknown is not zero"). An explicit DEVFLOW_GH still wins ahead of this.
if [ -z "${DEVFLOW_GH:-}" ]; then
    if type devflow_resolve_gh >/dev/null 2>&1; then
        DEVFLOW_GH="$(devflow_resolve_gh)"
    else
        echo "devflow: resolve-existing-pr.sh: devflow_resolve_gh is not defined after sourcing ../lib/resolve-gh.sh (a partial deployment carrying scripts/ without lib/); gh could not be resolved, so whether an open PR exists cannot be established" >&2
        printf '%s\n' REFUSED
        exit 3
    fi
fi
if [ -z "${DEVFLOW_GH:-}" ]; then
    echo "devflow: resolve-existing-pr.sh: gh resolution produced an empty value; whether an open PR exists cannot be established (set DEVFLOW_GH to override)" >&2
    printf '%s\n' REFUSED
    exit 3
fi
# jq likewise, through the .sh-helper-tier resolver — NOT scripts/run-jq.sh, whose whole
# reason for existing is agent-composed jq inside SKILL.md bodies, where no resolved
# DEVFLOW_JQ survives between an agent's separate Bash calls. Inside one .sh process the
# sourced resolver is the established idiom (parse-engine-error.sh, fetch-pr-context.sh, …)
# and costs no extra bash spawn.
# shellcheck source=../lib/resolve-jq.sh
. "$_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-existing-pr.sh could not source ../lib/resolve-jq.sh — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability: a sibling that sources clean yet never assigns must
# still leave a usable jq, never a bare `set -u` abort that breaks the one-token contract.
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-existing-pr.sh: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

ISSUE=""; BRANCH=""; BASE=""; BRANCH_SET=""
# EVERY value-taking flag checks that its operand is PRESENT before `shift 2`. This is not
# defensive tidiness: with one positional left, bash's `shift 2` FAILS and shifts NOTHING, and
# because this helper deliberately runs without `set -e` the loop then re-matches the same flag
# forever — an unbounded hang that prints no token, leaves no breadcrumb, and never exits. That
# is strictly worse than any wrong answer: the caller's contract routes "no output at all" to
# REFUSED only for a process that TERMINATES, so a hang burns the whole job budget instead.
# The shape is reachable from the §3.1 fence, and the guard covers BOTH spellings of an empty
# issue number, which fail differently: an UNQUOTED `--issue $ISSUE_NUMBER` drops the word
# entirely when the value is empty, leaving a bare trailing `--issue` — the hang; a QUOTED
# `--issue "$ISSUE_NUMBER"` instead passes an empty-but-present operand, which the numeric
# guard below refuses. Fail closed to REFUSED either way, like every other unusable-operand
# path here.
while [ "$#" -gt 0 ]; do
    case "$1" in
        --issue|--branch|--base)
            if [ "$#" -lt 2 ]; then
                echo "devflow: resolve-existing-pr.sh: '$1' requires a value but none was given; refusing rather than looping on an unconsumable argument" >&2
                printf '%s\n' REFUSED
                exit 3
            fi
            case "$1" in
                --issue)  ISSUE="$2" ;;
                --branch) BRANCH="$2"; BRANCH_SET=1 ;;
                --base)   BASE="$2" ;;
            esac
            shift 2 ;;
        *)
            echo "devflow: resolve-existing-pr.sh: unrecognized argument '$1'; refusing to guess" >&2
            printf '%s\n' REFUSED
            exit 3 ;;
    esac
done

# The issue number gates the closes-issue validation, so an absent or non-numeric one leaves
# that check unestablished. CLAUDE.md's "unknown is not zero": report REFUSED rather than
# adopting with a validation silently downgraded to "passed".
case "$ISSUE" in
    ''|*[!0-9]*)
        echo "devflow: resolve-existing-pr.sh: --issue must be a number (got '$ISSUE'); the closes-issue validation cannot be established" >&2
        printf '%s\n' REFUSED
        exit 3 ;;
esac
# Strip leading zeros. The closes-issue check compares this against the API's `.number`
# rendered with `tostring`, so `007` would compare as "007" against "7" and report a
# spurious closes-issue failure on a PR whose validation in fact held — the same
# misreported-check class the absent-base sentinel below exists to eliminate. `10#` forces
# base-10 (a bare `$((007))` would read it as octal).
ISSUE=$((10#$ISSUE))

# Read the branch in its OWN statement when the caller did not supply one. An inner
# `$(git branch --show-current)` inside the query's `--head` would hide its own failure from
# the outer `||` (only gh's status reaches it), and git prints EMPTY on a detached HEAD, a
# broken worktree, or git < 2.22.
if [ -z "$BRANCH_SET" ]; then
    BRANCH="$(git branch --show-current 2>/dev/null)" || BRANCH=""
fi

# FAIL-CLOSED, and the reason this guard is not merely tidiness: `gh pr list --head ""` is not
# a narrower query, it is an UNFILTERED repo-wide open-PR listing that exits 0 — so a helper
# that let an empty branch through would adopt an arbitrary unrelated PR on some other branch.
# The query must never be reached with an empty branch name.
if [ -z "$BRANCH" ]; then
    echo "devflow: resolve-existing-pr.sh: the branch name is empty (detached HEAD, a broken worktree, or git < 2.22); NOT querying — an empty --head degrades to an unfiltered repo-wide listing" >&2
    printf '%s\n' REFUSED
    exit 3
fi

# OPEN-SCOPED and branch-explicit, deliberately NOT `gh pr view`: that command takes no
# --state filter and resolves "the pull request that belongs to the current branch" across
# OPEN/CLOSED/MERGED, so a branch whose only PR was CLOSED would yield a non-empty capture,
# the create would be skipped, and every downstream consumer (the workpad PR link, the
# PRFlow label, the description, the publish step) would run against a closed PR while the
# run has no live PR at all.
#
# gh's own stderr is CAPTURED rather than discarded, and the two REFUSED causes below are
# reported separately: "gh exited non-zero (here is why)" and "gh exited 0 but printed
# nothing" are different diagnoses, and a shared generic breadcrumb would point a reader at
# the wrong one (the misdirected-breadcrumb class). The `2>` redirect targets a file rather
# than a `2>&1` merge so the JSON capture stays uncontaminated by the diagnostic bytes.
# The mktemp-or-/dev/null sentinel and its guarded cleanup are the established sibling idiom
# (scripts/summarize-ci-checks.sh, scripts/derive-review-preconditions.sh): an unguarded
# `rm -f` on the sentinel would target /dev/null. The captured bytes are read with the `$(<f)`
# BUILTIN rather than `cat`, which lib/preflight.sh does not guarantee.
GH_ERR="$(mktemp 2>/dev/null)" || GH_ERR=/dev/null
if ! PR_JSON="$("$DEVFLOW_GH" pr list --head "$BRANCH" --state open --json number,createdAt,baseRefName,closingIssuesReferences 2>"$GH_ERR")"; then
    # THREE states, never two: gh printed a cause / gh printed nothing / the capture CHANNEL
    # was unavailable (mktemp failed, so the redirect went to /dev/null). Collapsing the third
    # onto the second would assert that gh was silent when in fact its message was discarded —
    # "unknown is not zero" applied to the diagnostics channel, on the one path whose whole job
    # is naming the cause.
    if [ "$GH_ERR" = /dev/null ]; then
        _gh_why="gh's stderr could not be captured (mktemp unavailable); see gh's own output above"
    elif [ -s "$GH_ERR" ]; then
        _gh_why="$(<"$GH_ERR")"
    else
        _gh_why="gh printed no error output"
    fi
    echo "devflow: resolve-existing-pr.sh: 'gh pr list' exited non-zero for branch '$BRANCH'; could not establish whether an open PR exists: $_gh_why" >&2
    [ "$GH_ERR" = /dev/null ] || rm -f "$GH_ERR"
    printf '%s\n' REFUSED
    exit 3
fi
[ "$GH_ERR" = /dev/null ] || rm -f "$GH_ERR"
if [ -z "$PR_JSON" ]; then
    echo "devflow: resolve-existing-pr.sh: 'gh pr list' exited 0 but printed nothing for branch '$BRANCH' (an empty listing is spelled '[]', never empty output); could not establish whether an open PR exists" >&2
    printf '%s\n' REFUSED
    exit 3
fi

# Selection is deterministic: `gh pr list` documents no stable array order, so a head carrying
# two open PRs (a reopened prior attempt, a stacked PR) would make a bare `.[0]` return
# whichever the API happened to list first. Sort by createdAt and take the newest, exactly as
# phase-1-setup.md §1.4's resume pre-check does.
#
# The filter emits ONE line — either the sentinel `NONE` or `<number> <yes|no> <baseRefName>`.
# A sentinel rather than empty output is load-bearing: an empty line would be ambiguous
# between "no open PR" (a clean CREATE) and "the filter failed" (a REFUSED), and collapsing
# those two is the same fail-open the REFUSED/CREATE split exists to prevent.
#
# FIELD ORDER AND THE ABSENT-BASE SENTINEL ARE BOTH LOAD-BEARING. `read` splits on IFS and
# COLLAPSES a run of whitespace, so an empty field does not hold its position — it vanishes and
# every field after it shifts left. With the base emitted in the middle and defaulted to the
# empty string, a PR whose `baseRefName` is null produced `11  yes`, `read` bound PR_BASE=yes
# and PR_CLOSES="", and the helper then reported BOTH checks failed and named the PR's base as
# literally 'yes' — a warning about a check that in fact held, written durably to the workpad.
# Two changes make the split shift-proof: the fixed-vocabulary `yes|no` field moves ahead of the
# free-form base (so nothing variable precedes it), and an absent base becomes the non-empty
# sentinel `-` rather than "". The sentinel never equals a real base name, so the base-ref check
# still fails — fail-safe — but the breadcrumb below can say the base was UNESTABLISHED rather
# than misreporting it as an ordinary mismatch ("unknown is not zero").
#
# jq goes through the resolved $DEVFLOW_JQ, never a bare `jq` (the #247 rule); the JSON is fed
# by here-string rather than a `printf |` pipeline, so no subshell and no extra process. jq's
# own stderr is captured for the same reason gh's is: "jq failed" and "jq produced no line" are
# different diagnoses, and a breadcrumb that cannot tell them apart misdirects the reader.
JQ_ERR="$(mktemp 2>/dev/null)" || JQ_ERR=/dev/null
PR_LINE="$("$DEVFLOW_JQ" -r --arg iss "$ISSUE" '
    sort_by(.createdAt) | last
    | if . == null then "NONE"
      else "\(.number) \(
             ((.closingIssuesReferences // []) | map(.number | tostring) | index($iss))
             | if . == null then "no" else "yes" end) \(.baseRefName // "-")"
      end' <<<"$PR_JSON" 2>"$JQ_ERR")" || PR_LINE=""

if [ -z "$PR_LINE" ]; then
    if [ "$JQ_ERR" = /dev/null ]; then
        _jq_why="jq's stderr could not be captured (mktemp unavailable); see jq's own output above"
    elif [ -s "$JQ_ERR" ]; then
        _jq_why="$(<"$JQ_ERR")"
    else
        _jq_why="jq exited 0 but produced no line"
    fi
    echo "devflow: resolve-existing-pr.sh: the open-PR listing for branch '$BRANCH' could not be parsed; could not establish whether an open PR exists: $_jq_why" >&2
    [ "$JQ_ERR" = /dev/null ] || rm -f "$JQ_ERR"
    printf '%s\n' REFUSED
    exit 3
fi
[ "$JQ_ERR" = /dev/null ] || rm -f "$JQ_ERR"
if [ "$PR_LINE" = NONE ]; then
    echo "devflow: resolve-existing-pr.sh: no open PR on branch '$BRANCH' (queried cleanly); the caller should create one" >&2
    printf '%s\n' CREATE
    exit 2
fi

# Field split via the `read` builtin — never `cut`/`awk`/`tr`. This value decides BOTH which
# PR is adopted (a selection) AND which validation warning is emitted (an emitted result),
# and CLAUDE.md's guard-class 2 forbids deriving either through a tool lib/preflight.sh does
# not guarantee: a host missing that tool would yield an empty field, and the run would adopt
# PR "" or report a clean validation it never performed.
read -r PR_NUMBER PR_CLOSES PR_BASE <<<"$PR_LINE"
case "$PR_NUMBER" in
    ''|*[!0-9]*)
        echo "devflow: resolve-existing-pr.sh: the selected PR's number is not numeric ('$PR_NUMBER' from '$PR_LINE'); refusing to adopt an unidentified PR" >&2
        printf '%s\n' REFUSED
        exit 3 ;;
esac

# Adoption validation (issue #782). The #755 guard adopted on head-branch match ALONE, so an unrelated open PR
# sharing the branch — a human's manual PR, a branch-name collision — was adopted silently,
# with no `Resolves #N` line and no comparison against the run's base. Each check that did not
# hold is named individually (the conjunctive both-failed case is the union of the two), so
# the caller's durable warning can say WHICH check failed. Adoption still proceeds: this is a
# visibility obligation, not a new stop.
#
# The base is re-derived HERE rather than at argument-parsing time, because it is read by
# nothing but this validation: on the CREATE and REFUSED paths the run would otherwise pay a
# config-get.sh (bash + python3) startup for a value it discards — and the CREATE path is the
# common fresh-run case, where §3.1's create fence immediately performs the identical read
# itself. config-get.sh prints its supplied default on the SOFT paths (absent file /
# absent-or-empty key) and nothing on the HARD ones (malformed config, missing python3), so
# the empty-read fallback below covers only the latter — behaviorally identical to the
# fallback Phase 1.4 and Phase 3.1's create arm perform.
if [ -z "$BASE" ]; then
    BASE="$("$_DIR/config-get.sh" .base_branch main)" || BASE=""
    if [ -z "$BASE" ]; then
        echo "devflow: resolve-existing-pr.sh: base_branch read failed (a malformed config, a missing python3, or config-get.sh itself absent/non-executable beside this helper); falling back to 'main' for the base-ref validation" >&2
        BASE=main
    fi
fi

# Both checks are written in ONE shape, so a third check is one more identical line and no
# `a && b || c` chain (which silently takes the else-branch if the true-branch ever becomes
# conditional). The ORDER OF THE TWO LINES BELOW is the emitted order that the `WARN:<checks>`
# contract pins (`closes-issue` before `base-ref`); the `${FAILED:+$FAILED,}` form only supplies
# the separator without a leading comma — it guarantees no ordering of its own.
FAILED=""
[ "$PR_CLOSES" = yes ]   || FAILED="${FAILED:+$FAILED,}closes-issue"
[ "$PR_BASE" = "$BASE" ] || FAILED="${FAILED:+$FAILED,}base-ref"
if [ -n "$FAILED" ]; then
    # The base clause distinguishes an UNESTABLISHED base (the jq `-` sentinel: the API returned
    # no baseRefName) from an ordinary mismatch. Both fail the check — fail-safe — but only one
    # of them is a fact about the PR, and the durable note the caller writes quotes this text.
    if [ "$PR_BASE" = - ]; then
        _base_clause="its base ref could not be established (the listing carried no baseRefName; expected '$BASE')"
    else
        _base_clause="targets base '$PR_BASE' (expected '$BASE')"
    fi
    # Recite ONLY the clauses whose check failed. Naming the base in a closes-issue-only
    # warning ("targets base 'main' (expected 'main')") reads as if the base were implicated
    # too, and this text is quoted verbatim into a durable workpad note.
    _why=""
    case ",$FAILED," in *,closes-issue,*) _why="it does not list issue #$ISSUE in closingIssuesReferences" ;; esac
    case ",$FAILED," in *,base-ref,*) _why="${_why:+$_why; }$_base_clause" ;; esac
    echo "devflow: resolve-existing-pr.sh: adopting open PR #$PR_NUMBER on branch '$BRANCH', but validation failed ($FAILED): $_why" >&2
    printf '%s\n' "ADOPT $PR_NUMBER WARN:$FAILED"
    exit 0
fi
echo "devflow: resolve-existing-pr.sh: adopting open PR #$PR_NUMBER on branch '$BRANCH' (closes issue #$ISSUE, targets base '$BASE')" >&2
printf '%s\n' "ADOPT $PR_NUMBER OK"
exit 0

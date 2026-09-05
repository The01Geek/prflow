#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Dismiss PRFlow Review's own still-outstanding CHANGES_REQUESTED reviews.
#
# Called after a PRFlow Review APPROVE verdict to clear a prior REJECT's
# `--request-changes` review. GitHub keeps that review the PR's effective
# `reviewDecision` until it is *dismissed*: a later APPROVE-with-notes is a
# `--comment` review (never supersedes) and the REJECT may be a different
# bot identity (auto path = github-actions[bot], manual @claude = another),
# so no later review clears it. Without an explicit dismissal the PR is
# wedged at reviewDecision=CHANGES_REQUESTED despite a green required check.
#
# Scope: ONLY reviews whose body is a PRFlow Review formal verdict are
# dismissed. Three body shapes are matched:
#   1. PRODUCER MARKER (issue #1030, the authoritative shape): the review
#      body's LINE 1 is exactly
#        <!-- prflow:review-verdict head=<40-hex> verdict=REJECT -->
#      composed by scripts/post-review-verdict.sh — never by the reviewing
#      agent. This is the only shape whose presence the producer guarantees.
#      Matched on line 1 alone, so a marker literal quoted inside a finding's
#      prose (routine on a pull request touching the review engine itself)
#      is not mistaken for the producer's own stamp, and a marker carrying
#      `verdict=APPROVE` is not selected.
#   2. TRANSITIONAL — new stub format (post-#135 consolidation): the formal
#      review body starts with `## Verdict: REJECT` — the full Phase 4.1
#      report lives in the progress comment, not the review body, so the
#      review carries only a short verdict stub.
#   3. TRANSITIONAL — legacy format (pre-#135): the formal review body starts
#      with `# Review Report` (kept for backward compatibility with any
#      pre-consolidation reviews still outstanding on long-lived PRs).
# Shapes 2 and 3 are agent-authored prose, which is exactly why #1030 added
# shape 1: a census over 60 pull requests measured 6 of 9 real REJECT bodies
# matching NEITHER, so each was silently read as "not one of ours" and never
# dismissed. They are retained because reviews already posted on long-lived
# open pull requests carry no marker; their removal is confirmation-gated on
# the end criterion CLAUDE.md states, never on a timer.
# A human reviewer's `--request-changes` carries none of the three and is left
# untouched — an automated APPROVE must never silently clear a human's
# block.
#
# Commit scoping (issue #1029, revised by #1247) — the second half of "stale".
# The body marker says WHOSE review it is; it says nothing about whether the
# review is SUPERSEDED, and this script only ever has licence to clear a
# superseded one. Staleness needs the head the review actually reviewed.
#
# WHICH KEY records that head (issue #1247). GitHub can change a review's
# reviews-API `commit_id` AFTER submission, to a commit that did not exist at
# review time — observed on PR #1234, where the middle review's `commit_id` was
# advanced to a head committed 35 minutes after the review was submitted. So
# `commit_id` is NOT a reliable record of the reviewed tree. The verdict marker's
# `head=` — stamped by scripts/post-review-verdict.sh at review time and never
# rewritten (issue #1030) — is. So the comparand is the marker `head=` when the
# review carries one, and `commit_id` only as the fallback for a MARKERLESS
# review (posted before #1030, or by hand on the local tier), where it is the
# only key there is. A disagreement between the two keys is ordinary GitHub
# behavior, not a producer defect.
#
# A review whose reviewed-tree comparand equals the PR's CURRENT head is by
# definition not superseded — dismissing it discards a live merge-blocking
# finding about the very commit the caller just approved. That is reachable, not
# theoretical: two review passes 71s apart both judged commit f798f2f6 of PR #999
# and disagreed. So every candidate must be shown stale before it is dismissed
# (comparand = marker head when present, else commit_id):
#   - comparand != current head .. genuinely superseded .. DISMISS
#   - comparand == current head .. not superseded ......... REFUSE
#   - no comparand (markerless AND commit_id absent/empty) staleness unprovable REFUSE
# The absent-comparand arm is the fail-CLOSED direction on purpose: a guard
# that treats an unreadable comparand as "not equal" fails open exactly where
# it claims to fail closed. A review carrying a marker head is decided on the
# marker even when its `commit_id` is absent — the marker is a comparand, so
# that is not the no-comparand arm.
#
# The caller decides WHEN to run this (APPROVE only — never on REJECT, the
# changes-request must stand). This script does not inspect the verdict.
#
# Usage: dismiss-stale-rejections.sh PR_NUMBER [REPO]
#   PR_NUMBER  the pull request number
#   REPO       owner/name; defaults to `$DEVFLOW_GH repo view`'s nameWithOwner
#
# Re-run safe: a dismissed review's state becomes DISMISSED so it no longer
# matches the filter; re-running this script after a successful pass is a
# genuine no-op. (It still dismisses any NEW Devflow-report CHANGES_REQUESTED
# that appeared since ON A SUPERSEDED COMMIT — that is the intended behavior,
# not non-idempotency. One that appeared on the current head is refused, per
# the commit scoping above.)
# Best-effort per review: a failed dismissal is logged and the rest still
# run; the verdict never depends on this housekeeping.
#
# Requires: gh (authenticated), jq. Needs pull-requests:write — the
# dismissals API can dismiss ANY reviewer's review (required for the
# cross-identity case). $DEVFLOW_GH overrides the `gh` binary for tests
# (same seam as the rest of devflow; see lib/fetch-pr-context.sh).
#
# Exit codes:
#   0  all matching reviews dismissed, or none were outstanding (no-op)
#   1  a query failed (the review list, or the current-head read), or one or
#      more dismissals failed (caller may warn; never fatal there)
#   2  bad arguments
#   3  nothing failed, but at least one Devflow-report CHANGES_REQUESTED was
#      left outstanding because it could not be shown superseded (issue
#      #1029). Distinct from 0 on purpose: "refused" is not "there was
#      nothing to do", and collapsing an unestablished outcome onto the
#      success value is what makes a wedged PR look like a clean no-op.
#      A real failure outranks a refusal, so 1 wins when both occur. The
#      caller's existing branch — non-zero means say the PR stays blocked
#      until dismissed manually — is the correct human message here too.

set -euo pipefail
# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
  echo "usage: dismiss-stale-rejections.sh PR_NUMBER [REPO]" >&2
  exit 2
fi
PR="$1"
REPO="${2:-$("$DEVFLOW_GH" repo view --json nameWithOwner --jq .nameWithOwner)}"

# One paginated call (consistent with claude.yml Signal 1) so the loop runs
# in THIS shell, not a pipe subshell: a per-review failure flag survives, no
# recount round-trip is needed, and a list-call failure (exit 1, nothing
# dismissed) stays distinct from a clean no-op (no matching reviews). The
# body-marker filter is what scopes this to Devflow's own reviews; each row
# also carries the review's `commit_id` AND its verdict-marker `head=` — the
# two candidate comparands the staleness test below chooses between (marker
# head first, `commit_id` fallback — issue #1247).
# Every row is emitted with an `own`/`other` KIND prefix rather than filtering the
# unselected ones away, so a CHANGES_REQUESTED review this script declines to touch
# is COUNTED instead of vanishing. That distinction is the whole point of issue
# #1030: before the marker, six of nine real REJECTs matched no body shape, so the
# script reported a clean no-op on a wedged pull request and nothing recorded that
# it had looked at anything at all.
# The body type is tested BEFORE any string operation and `and` short-circuits, so a
# non-string `body` (an API shape this script does not produce) grades `other`
# instead of aborting the whole filter — CLAUDE.md's non-string-field guard.
# The marker `head=` is captured by a SECOND, separately-guarded capture() over the
# SAME line-1 string the ownership test() reads (not by extending that test(), which
# yields a boolean and captures nothing), defaulted with `// "-"` so every row emits
# exactly one line whatever its body shape — a body that carries no line-1 marker
# (transitional prose, a human block, an APPROVE marker, a marker quoted below line 1)
# yields the sentinel. The captured head is `ascii_downcase`d so it compares byte-exact
# against the lowercase `.head.sha`/`commit_id` the API returns — the ownership regex is
# case-tolerant, so a hand-authored uppercase marker head would otherwise read superseded
# against a lowercase head and wave a live review through (guard-class-2: normalize in jq,
# not with a bash-4 `${var,,}` that breaks on macOS bash 3.2, nor a non-preflight `tr`).
# `commit_id` is likewise encoded as the sentinel `-` (never a
# valid SHA), so no field is ever positional-empty: default-IFS `read` collapses
# whitespace runs, so an empty field in the MIDDLE of a row would shift the split.
# Both `while read` loops map the sentinel back to the empty string with a `case`
# builtin before use.
if ! ROWS=$("$DEVFLOW_GH" api --paginate "repos/$REPO/pulls/$PR/reviews?per_page=100" \
             --jq 'def prflow_own_reject($b): ($b | type) == "string" and ((($b | split("\n") | (.[0] // "")) | test("^<!-- prflow:review-verdict head=[0-9a-fA-F]{40} verdict=REJECT -->$")) or ($b | startswith("## Verdict: REJECT")) or ($b | startswith("# Review Report")));
                   def marker_head($b): ((($b | if type == "string" then . else "" end | split("\n") | (.[0] // "")) | capture("^<!-- prflow:review-verdict head=(?<h>[0-9a-fA-F]{40}) verdict=REJECT -->$") | .h | ascii_downcase) // "-");
                   .[] | select(.state=="CHANGES_REQUESTED") | (prflow_own_reject(.body // "")) as $own | "\(if $own then "own" else "other" end) \(.id) \(.commit_id // "-") \(marker_head(.body))"'); then
  echo "WARNING: could not list reviews for PR #$PR — dismiss manually." >&2
  exit 1
fi

# Split the kind prefix off with `read` + `case` (builtins) so no selection value is
# routed through a non-preflight PATH tool. CANDIDATES holds only this engine's own
# rows, in their original order; UNSELECTED counts the rest. Each own row carries
# three fields — id, the sentinel-encoded commit_id, and the sentinel-encoded marker
# head — and the sentinels ride through UNCHANGED to CANDIDATES (they are mapped back
# to the empty string only in the dismissal loop below), so no field is ever
# positional-empty in this split either.
CANDIDATES=""
UNSELECTED=0
while read -r RKIND RID RCOMMIT RHEAD; do
  [ -n "$RID" ] || continue
  case "$RKIND" in
    own) CANDIDATES="${CANDIDATES}${RID} ${RCOMMIT} ${RHEAD}"$'\n' ;;
    *)   UNSELECTED=$((UNSELECTED + 1)) ;;
  esac
done <<< "$ROWS"

# The PR's current head — the comparand every staleness test below is made
# against. Resolved LAZILY, only once a candidate exists, so the common path
# (nothing outstanding, or only reviews this script does not own) still costs
# exactly one API call. A head that cannot
# be established is fail-closed: no review can be SHOWN stale against an
# unknown head, so nothing is dismissed and the caller is told the PR stays
# blocked. `.head.sha` is validated as a plausible object name here because it
# decides a selection — an empty read, a jq `null`, or an error blob must not
# silently become a value that compares unequal to every commit_id and so
# waves every candidate through.
HEAD_SHA=""
if [ -n "$CANDIDATES" ]; then
  if ! HEAD_SHA=$("$DEVFLOW_GH" api "repos/$REPO/pulls/$PR" --jq '.head.sha'); then
    echo "WARNING: could not read the current head of PR #$PR — dismissed nothing (a review is only stale against a known head). Dismiss manually if appropriate." >&2
    exit 1
  fi
  if [[ ! "$HEAD_SHA" =~ ^[0-9a-fA-F]{7,64}$ ]]; then
    echo "WARNING: the current head of PR #$PR did not read back as a commit SHA ('${HEAD_SHA}') — dismissed nothing. Dismiss manually if appropriate." >&2
    exit 1
  fi
fi

FAILED=0
REFUSED=0
# An outstanding CHANGES_REQUESTED this script did not select is REPORTED, never
# silently dropped, so "there was nothing of ours" reads differently from "there was
# nothing at all" (issue #1030). It does NOT move the exit status: a human reviewer's
# block landing here is the correct, expected outcome — exit 3 would tell the caller
# to go dismiss a human's review. A PRFlow REJECT landing here is a producer defect,
# which is what the sentence names.
if [ "$UNSELECTED" -gt 0 ]; then
  echo "NOTE: PR #$PR carries $UNSELECTED outstanding CHANGES_REQUESTED review(s) this script did not select — none carried a prflow:review-verdict marker or a transitional report prefix, so none could be shown to be this engine's own. A human reviewer's block belongs here and is left untouched; a PRFlow verdict landing here means the post did not stamp its marker (issue #1030)." >&2
fi
# Fields are split by `read` (a builtin) and compared with `[` — CLAUDE.md
# guard-class 2: a value deciding a SELECTION is never routed through a
# non-preflight PATH tool such as tr/sed/cut/wc/head, which would come back empty
# on a host that lacks it and select the wrong thing.
#
# Which tree was reviewed (issue #1247). GitHub can advance a review's `commit_id`
# after submission to a commit that did not exist at review time, so `commit_id` is
# NOT a reliable record of the reviewed tree. The verdict marker's `head=` — stamped
# by scripts/post-review-verdict.sh at review time and never rewritten — is. So the
# staleness comparand is the marker head when the review carries one, and `commit_id`
# only as the fallback for a markerless review (posted before #1030, or by hand on
# the local tier), where it is the only key there is. The sentinels are mapped back
# to the empty string here with `case` builtins so no empty field was ever positional.
while read -r RID RCOMMIT RHEAD; do
  [ -n "$RID" ] || continue
  case "$RCOMMIT" in -) RCOMMIT="" ;; esac
  case "$RHEAD" in -) RHEAD="" ;; esac
  # Select the comparand: marker head first (the reviewed tree), commit_id fallback.
  if [ -n "$RHEAD" ]; then
    CMP="$RHEAD"; SRC="verdict-marker head="
  else
    CMP="$RCOMMIT"; SRC="reviews-API commit_id="
  fi
  if [ -z "$CMP" ]; then
    echo "WARNING: review $RID on PR #$PR records neither a verdict-marker head nor a commit_id, so it cannot be shown superseded — NOT dismissed. Dismiss it manually if it is stale." >&2
    REFUSED=1
    continue
  fi
  if [ "$CMP" = "$HEAD_SHA" ]; then
    echo "WARNING: review $RID on PR #$PR reviewed the PR's current head ($SRC$CMP), so it is not superseded — NOT dismissed. Its findings are about the commit being approved; resolve them, or dismiss it manually." >&2
    REFUSED=1
    continue
  fi
  # Capture stderr so a real failure cause (404/422/429/5xx) is surfaced
  # rather than collapsed into a misleading permissions guess. The message names
  # the key the decision used AND which field it came from, so a reader can tell a
  # marker-driven dismissal from a commit_id-driven one.
  if ERR=$("$DEVFLOW_GH" api -X PUT "repos/$REPO/pulls/$PR/reviews/$RID/dismissals" \
       -f message="Superseded by a later APPROVE verdict from PRFlow Review (review $RID reviewed commit $CMP [$SRC], which is no longer this pull request's head $HEAD_SHA)." \
       -f event=DISMISS 2>&1 >/dev/null); then
    echo "Dismissed stale CHANGES_REQUESTED review $RID on PR #$PR (reviewed $CMP [$SRC]; head is now $HEAD_SHA)."
  else
    echo "WARNING: could not dismiss review $RID on PR #$PR — dismiss it manually. (${ERR:-no error output})" >&2
    FAILED=1
  fi
done <<< "$CANDIDATES"
[ "$FAILED" -eq 0 ] || exit 1
[ "$REFUSED" -eq 0 ] || exit 3
exit 0

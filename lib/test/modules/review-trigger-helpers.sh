# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable review/implement trigger-helper contract module (issue #746 tranche).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module.
#
# No private fixture root and no EXIT trap here, deliberately. The extracted sections
# allocate their own fixture trees with bare `mktemp -d` and remove them on their own
# clean paths, exactly as they did inline in lib/test/run.sh — the move preserves that
# behavior rather than adding a second ownership layer. Both callers already allocate a
# boundary-owned scratch root and export TMPDIR to it, and clean it on every path
# including forced termination, so an extra module-level root would be redundant there.
# It would also not be the "complete crash-path backstop" it looks like: a bare
# `mktemp -d` does NOT honor a runtime TMPDIR override on macOS/BSD (it uses the Darwin
# confstr temp dir — the same portability trap lib/test/run-module.sh documents at its
# own mktemp calls), so a redirect could not contain these call sites anyway.


# The one run.sh global the extracted sections read that a module does not
# receive: the config resolver the #329/#409 key-read assertions invoke. The
# monolith binds it identically, from LIB. Left unbound it expands to the empty
# string, so `"$CG" …` runs the empty command and every one of those assertions
# compares against empty output — the failure this binding exists to prevent.
CG="$LIB/../scripts/config-get.sh"

# ────────────────────────────────────────────────────────────────────────────
echo "derive-review-verdict.sh (#249 HEAD-scoped, fail-closed verdict deriver)"
# ────────────────────────────────────────────────────────────────────────────
# The unit finalize_check's success) branch calls to decide the required-check
# conclusion. `success` requires a POSITIVELY-observed APPROVE for the current
# HEAD; everything else fails closed to `incomplete` (a blocking failure). The
# reproduction cases (stale-reject-on-older-commit, verdict-less-approve, the
# unverifiable arms) are exactly the ones the OLD inline logic got wrong: it read
# `jq -r 'last.state'` (so a CHANGES_REQUESTED on an OLDER commit mapped to
# REJECT) and defaulted VERDICT=approve/success on empty reviews or a swallowed
# query error. This deriver returns `incomplete` for all of them.
DRV="$LIB/../scripts/derive-review-verdict.sh"
DRV_NEW="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"   # current HEAD SHA
DRV_OLD="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"   # a superseded commit SHA
DRV_STUB="/tmp/devflow-gh-stub-drv.$$.sh"
cat > "$DRV_STUB" <<'EOS'
#!/usr/bin/env bash
# Echo raw JSON (the deriver pipes it through jq itself). DRV_*_FAIL=1 forces a
# query failure so the fail-closed arms can be exercised.
case "$*" in
  *"repo view"*)           [ "${DRV_REPO_FAIL:-0}" = 0 ] && echo "o/r"; exit 0 ;;   # DRV_REPO_FAIL=1 -> empty stdout (unresolvable REPO)
  *"pulls/"*"/reviews"*)   [ "${DRV_REVIEWS_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "${DRV_REVIEWS-[]}"; exit 0 ;;
  *"issues/"*"/comments"*) [ "${DRV_COMMENTS_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "${DRV_COMMENTS-[]}"; exit 0 ;;
esac
echo '[]'; exit 0
EOS
chmod +x "$DRV_STUB"

# Runs the deriver (env is set by the caller's prefix, exported to the function
# body), collapses its two stdout lines to "<verdict> <verdict_determined>".
drv() {  # $1=description  $2=expected "<verdict> <determined>"
  local out v d
  out="$(bash "$DRV" 2>/dev/null)"
  v="$(printf '%s\n' "$out" | sed -n 's/^verdict=//p')"
  d="$(printf '%s\n' "$out" | sed -n 's/^verdict_determined=//p')"
  assert_eq "$1" "$2" "$v $d"
}
# Asserts the deriver emitted a SPECIFIC stderr breadcrumb. Used to pin the
# fail-closed guards whose VERDICT is guard-invariant (an empty PR / empty
# RUN_ID marker matches nothing downstream anyway, so the verdict alone cannot
# tell a present guard from a removed one — the distinctive breadcrumb can:
# delete the guard and the breadcrumb disappears, so this is non-vacuous).
drv_stderr() {  # $1=description  $2=expected stderr substring
  local err
  err="$(bash "$DRV" 2>&1 1>/dev/null)"
  assert_eq "$1" "yes" "$(printf '%s' "$err" | grep -qF -- "$2" && echo yes || echo no)"
}

# --- reproduction cases (OLD logic returned the WRONG answer) ---------------
# stale-reject-on-older-commit: CHANGES_REQUESTED on OLD, HEAD=NEW. OLD logic:
# last.state==CHANGES_REQUESTED -> REJECT (Direction-1 defect, PR #246).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_OLD\",\"body\":\"## Verdict: REJECT stale\"}]" \
  drv "#249 stale-reject-on-older-commit -> incomplete (not a resurrected REJECT)" "incomplete false"

# verdict-less-approve: empty reviews, ENGINE_ERROR=false. OLD logic:
# VERDICT defaulted to approve -> success (Direction-2 defect, PR #250).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  drv "#249 verdict-less-approve (empty reviews) -> incomplete (not a fabricated APPROVE)" "incomplete false"

# empty-PR-number: OLD logic warned and defaulted to success. The verdict is
# guard-invariant here (an empty PR can't reach a real query), so ALSO pin the
# guard's distinctive breadcrumb — non-vacuous: remove the guard, lose the line.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER="" REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  drv "#249 empty PR_NUMBER -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER="" REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  drv_stderr "#249 empty PR_NUMBER emits the specific 'empty PR_NUMBER' breadcrumb" "empty PR_NUMBER"

# reviews-API-query-failure: OLD logic warned and defaulted to success (this is
# the deliberate reversal in issue #249's ACs). The verdict alone is guard-
# invariant here (with the guard removed, an empty REVIEWS_JSON still fails
# closed via the step-5 parse guard), so the SPECIFIC query-failure breadcrumb
# below is the non-vacuous pin distinguishing this arm from the parse arm.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS_FAIL=1 \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 reviews-API query failure -> incomplete (fail closed; overrides a would-be APPROVE comment)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS_FAIL=1 \
  drv_stderr "#249 reviews-API query failure emits the specific 'reviews API query failed' breadcrumb" "reviews API query failed"

# --- engine-error path -----------------------------------------------------
# engine-errored: is_error=true short-circuits BEFORE any reviews query. The
# payload is a would-be APPROVE ON HEAD, so this is `incomplete` ONLY because the
# engine-error branch overrides it — non-vacuous: remove the short-circuit and it
# returns approve (the marquee PR #250 signal is now actually protected).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=true PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE\"}]" \
  drv "#249 engine-errored overrides a would-be APPROVE-on-HEAD -> incomplete (no dismissal)" "incomplete false"

# --- fresh verdicts ON HEAD (still block / still pass) ----------------------
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: REJECT now\"}]" \
  drv "#249 fresh-reject-on-HEAD -> reject (still blocks)" "reject true"

HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE\"}]" \
  drv "#249 fresh-approve-on-HEAD (APPROVED) -> approve + determined (dismiss gate)" "approve true"

# approve-with-notes is a COMMENTED review (Phase 4.4 producer contract) whose
# body carries the APPROVE marker — the second positive-APPROVE signal.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE with notes (ok)\"}]" \
  drv "#249 approve-with-notes COMMENTED-on-HEAD -> approve (body marker)" "approve true"

# A later NEW-commit review supersedes an earlier OLD-commit one (last-on-HEAD).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_OLD\"},{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 approve-on-HEAD after stale reject-on-OLD -> approve" "approve true"

# --- comment fallback (same-identity self-review), scoped to THIS run -------
# No HEAD review; the run-keyed devflow:review-progress comment embeds the verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: REJECT via comment"}]' \
  drv "#249 comment-fallback run-keyed REJECT on HEAD -> reject" "reject true"

HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE via comment"}]' \
  drv "#249 comment-fallback run-keyed APPROVE on HEAD -> approve" "approve true"

# A verdict comment from a PRIOR run (different run id) is NOT this HEAD's verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=999-1 -->\n## Verdict: REJECT from an old run"}]' \
  drv "#249 prior-run verdict comment NOT treated as HEAD verdict -> incomplete" "incomplete false"

# A run-keyed progress comment frozen at "Verdict: (pending)" (the PR #250 stall
# shape) carries no REJECT/APPROVE marker -> incomplete.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\nStatus: Reviewing\nVerdict: (pending)"}]' \
  drv "#249 pending progress comment (no verdict marker) -> incomplete" "incomplete false"

# comment-query failure with no HEAD review -> fail closed.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS_FAIL=1 \
  drv "#249 comment-fallback query failure -> incomplete (fail closed)" "incomplete false"

# --- additional fail-closed / positive guards (review coverage gaps) ---------
# empty HEAD_SHA -> cannot scope to the current commit -> fail closed. Without
# this guard an empty $h makes select(.commit_id=="") match nothing and a
# comment-derived verdict could be emitted for an UNKNOWN head.
HEAD_SHA="" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"\"}]" \
  drv "#249 empty HEAD_SHA -> incomplete (fail closed, cannot HEAD-scope)" "incomplete false"

# A COMMENTED review ON HEAD with NO verdict marker is NOT an approve — this is
# the false-APPROVE regression guard: state==COMMENTED alone must never approve
# (only APPROVED state or a `## Verdict: APPROVE` body marker does).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"just a note, no verdict here\"}]" \
  DRV_COMMENTS="[]" \
  drv "#249 COMMENTED-on-HEAD WITHOUT a verdict marker -> incomplete (no false APPROVE)" "incomplete false"

# REPO auto-derivation: empty REPO is resolved via `gh repo view` (positive path)...
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO="" GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 empty REPO resolved via 'gh repo view' -> approve" "approve true"
# ...and when `gh repo view` yields nothing, REPO is unresolvable -> fail closed.
# The APPROVED-on-HEAD payload sits behind the guard: without it, the empty REPO
# would flow into the reviews query and return approve — non-vacuous.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO="" GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" DRV_REPO_FAIL=1 \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 unresolvable REPO ('gh repo view' empty) -> incomplete (fail closed; overrides a would-be APPROVE)" "incomplete false"

# Multiple reviews on the SAME HEAD commit -> last-on-HEAD wins (a dismiss +
# re-request, or a re-review, produces two HEAD reviews). Both orderings pinned.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\"},{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 two reviews on HEAD [reject,approve] -> approve (last-on-HEAD wins)" "approve true"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"},{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 two reviews on HEAD [approve,reject] -> reject (last-on-HEAD wins)" "reject true"

# No HEAD review + empty GITHUB_RUN_ID -> cannot scope the comment fallback to
# this run -> fail closed BEFORE querying comments. The verdict is guard-invariant
# (an empty-run-id marker matches no real comment), so ALSO pin the distinctive
# breadcrumb — non-vacuous: remove the guard, lose the line.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID="" DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 no HEAD review + empty GITHUB_RUN_ID -> incomplete (cannot run-scope the comment fallback)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID="" DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  drv_stderr "#249 empty GITHUB_RUN_ID emits the specific 'GITHUB_RUN_ID is empty' breadcrumb" "GITHUB_RUN_ID is empty"

# Marker precedence: REJECT is checked before APPROVE (fail toward blocking) even
# when a HEAD review's body somehow carries both markers.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: REJECT\n## Verdict: APPROVE\"}]" \
  drv "#249 both markers on HEAD review -> reject (REJECT precedence, fail toward blocking)" "reject true"

# Adversarial input-shape: a 200-but-NON-ARRAY reviews payload (e.g. an API error
# object) must fail closed as a PARSE failure, never silently fall through to the
# comment fallback. A run-keyed APPROVE comment sits BEHIND the guard: without the
# jq-failure check the fall-through would return approve — non-vacuous.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS='{"message":"Moved Permanently"}' \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 non-array reviews payload -> incomplete (parse failure fails closed; overrides a would-be APPROVE comment)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS='{"message":"Moved Permanently"}' \
  drv_stderr "#249 non-array reviews payload emits the specific 'could not be parsed' breadcrumb" "reviews JSON could not be parsed"

# Same shape on the comments-API payload: non-array -> parse-failure fail-closed
# (never step 7's misdiagnosing "no verdict" breadcrumb).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS='{"message":"err"}' \
  drv "#249 non-array comments payload -> incomplete (parse failure fails closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS='{"message":"err"}' \
  drv_stderr "#249 non-array comments payload emits the specific comments-parse breadcrumb" "issue-comments JSON could not be parsed"

# Multi-attempt comment precedence: the marker prefix `run=<RUN_ID>-` matches every
# attempt of this run, and `last` wins — a later attempt's verdict supersedes an
# earlier attempt's. Pins `last` (a refactor to `first` ships RED).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: REJECT attempt 1"},{"body":"<!-- devflow:review-progress run=100-2 -->\n## Verdict: APPROVE attempt 2"}]' \
  drv "#249 two attempts of one run [attempt1 REJECT, attempt2 APPROVE] -> approve (last comment wins)" "approve true"

# Partial-copy posture (#247 class): the script deployed WITHOUT its lib/ siblings
# must degrade with a breadcrumb (guarded resolve-gh source + type-check), never
# assign an empty DEVFLOW_GH and misreport the failure as a reviews-query error.
# With the stub in DEVFLOW_GH the deriver must still reach a verdict.
DRV_PARTIAL_DIR="$(mktemp -d)"
mkdir -p "$DRV_PARTIAL_DIR/scripts"
cp "$DRV" "$DRV_PARTIAL_DIR/scripts/"
DRV_PARTIAL="$DRV_PARTIAL_DIR/scripts/derive-review-verdict.sh"
DRV_PARTIAL_OUT="$(HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" bash "$DRV_PARTIAL" 2>"$DRV_PARTIAL_DIR/err.txt")"
assert_eq "#249 partial-copy (no lib siblings) still derives the verdict via DEVFLOW_GH" "approve true" \
  "$(printf '%s\n' "$DRV_PARTIAL_OUT" | sed -n 's/^verdict=//p') $(printf '%s\n' "$DRV_PARTIAL_OUT" | sed -n 's/^verdict_determined=//p')"
assert_eq "#249 partial-copy emits the resolve-gh.sh sourcing breadcrumb" "yes" \
  "$(grep -qF -- "resolve-gh.sh could not be sourced" "$DRV_PARTIAL_DIR/err.txt" && echo yes || echo no)"
# Truncated sibling (sources CLEAN but never assigns): the outcome check — not
# just the sourceability guard — must leave a usable jq with its own breadcrumb,
# never a set -u abort that breaks the two-line stdout contract.
mkdir -p "$DRV_PARTIAL_DIR/lib"
printf '%s\n' '# truncated resolve-jq: sources clean, assigns nothing' > "$DRV_PARTIAL_DIR/lib/resolve-jq.sh"
cp "$LIB/resolve-gh.sh" "$LIB/resolve-bin.sh" "$DRV_PARTIAL_DIR/lib/"
DRV_TRUNC_OUT="$(env -u DEVFLOW_JQ HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" bash "$DRV_PARTIAL" 2>"$DRV_PARTIAL_DIR/err2.txt" | sed -n 's/^verdict=//p')"
assert_eq "#249 truncated resolve-jq sibling (clean source, no assignment) still derives the verdict" "approve" "$DRV_TRUNC_OUT"
assert_eq "#249 truncated resolve-jq sibling emits the 'did not assign DEVFLOW_JQ' breadcrumb" "yes" \
  "$(grep -qF -- "did not assign DEVFLOW_JQ" "$DRV_PARTIAL_DIR/err2.txt" && echo yes || echo no)"
rm -rf "$DRV_PARTIAL_DIR"

# Verdict-bearing-state selection: a DISMISSED review is a human override whose
# body still carries its old `## Verdict: REJECT` — it must NEVER resurrect as
# the HEAD verdict (the Direction-1 wedge via a new path). Pre-fix the body-grep
# ran regardless of state and returned reject — non-vacuous.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"DISMISSED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: REJECT dismissed by a human\"}]" \
  drv "#249 DISMISSED reject on HEAD is never the verdict -> incomplete (no resurrection of a human-dismissed reject)" "incomplete false"

# ...and a non-verdict-bearing review (PENDING/other) interleaved on HEAD after a
# genuine APPROVED must not mask it: selection takes the last VERDICT-BEARING
# HEAD review. Pre-fix `last` landed on the PENDING entry -> incomplete.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE\"},{\"state\":\"PENDING\",\"commit_id\":\"$DRV_NEW\",\"body\":\"\"}]" \
  drv "#249 interleaved PENDING on HEAD does not mask a genuine APPROVED -> approve" "approve true"

# Output contract: exactly two stdout lines, `verdict=` then `verdict_determined=`
# — finalize_check's `sed -n 's/^verdict=//p'` consumer depends on this exact
# shape; an extra stdout line or a renamed key would silently degrade every
# conclusion to incomplete.
DRV_CONTRACT_OUT="$(HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" bash "$DRV" 2>/dev/null)"
assert_eq "#249 deriver stdout contract: exactly 2 lines" "2" "$(printf '%s\n' "$DRV_CONTRACT_OUT" | wc -l | tr -d ' ')"
assert_eq "#249 deriver stdout contract: line 1 is verdict=, line 2 is verdict_determined=" "yes" \
  "$(printf '%s\n' "$DRV_CONTRACT_OUT" | sed -n '1s/^verdict=.*/ok1/p;2s/^verdict_determined=.*/ok2/p' | tr '\n' ' ' | grep -q 'ok1 ok2' && echo yes || echo no)"

# Pagination shape: `gh api --paginate` CONCATENATES page arrays ("[...][...]").
# The -s/add normalization must flatten them so a HEAD review on page 2 (GitHub
# returns oldest-first — >100 reviews pushes the newest off page 1) is still
# seen. Pre-normalization jq ran the filter once per top-level document, whose
# multi-line output fails the STATE comparison -> incomplete (RED).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_OLD\"}][{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" \
  drv "#249 paginated (concatenated-arrays) reviews payload: HEAD approve on page 2 -> approve" "approve true"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"unrelated chatter"}][{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 paginated comments payload: run-keyed verdict comment on page 2 -> approve" "approve true"

# Trailing-dash marker scoping: run=10 must NOT substring-match a prior run's
# run=105-1 comment. Without the trailing dash in MARKER the prior-run REJECT
# below would match and resurrect -> this pins the dash (mutation-sensitive).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=10 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=105-1 -->\n## Verdict: REJECT from run 105"}]' \
  drv "#249 marker trailing dash: run=10 does not match a run=105 comment -> incomplete" "incomplete false"

# A plain human COMMENTED review (no `## Verdict:` marker) on HEAD is NOT
# verdict-bearing: it must not mask the bot's APPROVED posted just before it
# (pre-fix `last` landed on the marker-less COMMENTED entry -> incomplete).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE\"},{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"nice work, just a human note\"}]" \
  drv "#249 marker-less human COMMENTED on HEAD does not mask a genuine APPROVED -> approve" "approve true"

# Empty-stdout payload (gh exits 0 with no body — truncated/degraded proxy):
# must take the PARSE guard (the slurped empty input becomes [], `add` yields
# null, and `map` then errors), never
# fall through to the comment fallback. APPROVE comment behind — non-vacuous.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 empty-stdout reviews payload -> incomplete (parse guard, not comment fall-through)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="" \
  drv_stderr "#249 empty-stdout reviews payload takes the PARSE-guard arm (breadcrumb pinned)" "reviews JSON could not be parsed"

# Comment-fallback marker precedence mirrors the review arm: REJECT before
# APPROVE even when one run-keyed comment carries both markers.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: REJECT\n## Verdict: APPROVE"}]' \
  drv "#249 both markers in the run-keyed comment -> reject (REJECT precedence in the fallback arm)" "reject true"

# Cross-arm precedence: a HEAD review verdict wins over a conflicting run-keyed
# comment (the review is consulted first and emit exits).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\"}]" \
  DRV_COMMENTS='[{"body":"<!-- devflow:review-progress run=100-1 -->\n## Verdict: APPROVE"}]' \
  drv "#249 HEAD reject review wins over a conflicting run-keyed APPROVE comment -> reject" "reject true"

# ${ENGINE_ERROR:-false} default: an ABSENT ENGINE_ERROR (version-skewed runner
# that never emitted the output) degrades to false and the verdict still derives.
DRV_NOEE_OUT="$(env -u ENGINE_ERROR HEAD_SHA="$DRV_NEW" PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"}]" bash "$DRV" 2>/dev/null | sed -n 's/^verdict=//p')"
assert_eq "#249 absent ENGINE_ERROR defaults to false (version-skew degradation) -> approve" "approve" "$DRV_NOEE_OUT"

# Large-body verdict artifact (SIGPIPE regression class): under pipefail a
# `printf | grep -q` pipeline could take SIGPIPE on a >64KB body and read a
# REAL marker as no-match; the herestring form must stay deterministic. The
# body is the full-report shape (marker first line + ~100KB of report text —
# comfortably past the 64KB pipe buffer yet under the ~128KB per-env-var
# execve limit the stub invocation must respect).
DRV_BIGPAD="$(printf 'x%.0s' $(seq 1 4000))"
DRV_BIG_TAIL=""
for _i in $(seq 1 25); do DRV_BIG_TAIL="${DRV_BIG_TAIL}${DRV_BIGPAD}\n"; done
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: APPROVE with notes\n$DRV_BIG_TAIL\"}]" \
  drv "#249 large (~100KB) APPROVE-with-notes body -> approve (no SIGPIPE false-nomatch)" "approve true"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: REJECT big\n$DRV_BIG_TAIL\"}]" \
  drv "#249 large (~100KB) REJECT body -> reject (no SIGPIPE false-nomatch)" "reject true"

# A verdict-BEARING marker with an unrecognized token (e.g. a frozen
# '## Verdict: (pending)'-like wording drift) is selected but matches neither
# marker regex -> falls through -> incomplete (fail closed), never a masked
# approve from the earlier review and never a fabricated verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\"},{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## Verdict: NEEDS-DISCUSSION\"}]" \
  drv "#249 unrecognized verdict token on last verdict-bearing HEAD review -> incomplete (fail closed, pinned)" "incomplete false"

# ── #1030: the producer marker is the FIRST signal, on both durable surfaces ──
# scripts/post-review-verdict.sh stamps
#   <!-- prflow:review-verdict head=<40-hex> verdict=<APPROVE|REJECT> -->
# as line 1 of the review body and as line 2 of the run-keyed progress comment. Every
# case below feeds a body the SHIPPED helper composes that shape for, and every
# unestablished reading must reach `incomplete false` with its OWN breadcrumb — a
# guessed verdict here would publish a merge signal nobody produced.
DRV_M_APPROVE="<!-- prflow:review-verdict head=$DRV_NEW verdict=APPROVE -->"
DRV_M_REJECT="<!-- prflow:review-verdict head=$DRV_NEW verdict=REJECT -->"
DRV_M_OLDHEAD="<!-- prflow:review-verdict head=$DRV_OLD verdict=APPROVE -->"
DRV_PROGRESS="<!-- prflow:review-progress run=100-1 -->"

# The marquee before/after: a marker-carrying COMMENTED approve-with-notes on HEAD.
# BEFORE #1030 this exact review yielded `incomplete false` (recorded on the issue as
# the measured state), because a COMMENTED review was admitted only on the `## Verdict:`
# prose the agent did not reliably write. The negative control immediately after it is
# the same review with the marker removed and no prose — still incomplete — so the
# marker, not the state, is what moved this case.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_APPROVE\n## 🔴 Devflow Review — APPROVE with notes\"}]" \
  drv "#1030 marker-carrying COMMENTED approve-with-notes on HEAD -> approve (was incomplete)" "approve true"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"## 🔴 Devflow Review — APPROVE with notes\"}]" \
  drv "#1030 control: the SAME COMMENTED review without the marker stays incomplete" "incomplete false"
# A marker-carrying CHANGES_REQUESTED whose body matches NO prose shape (one of the six
# census bodies) is still a reject — the marker, not the prose, carries it.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_REJECT\n## 🔴 Devflow Review — REJECT\"}]" \
  drv "#1030 marker-carrying non-conforming REJECT body on HEAD -> reject" "reject true"

# The two verdict keys can disagree as ordinary GitHub behavior (GitHub can change a
# review's commit_id after submission — issue #1247), so this deriver fails closed and
# joins on neither when they disagree, rather than guessing a verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_OLDHEAD\"}]" \
  drv "#1030 marker head disagreeing with the review commit_id -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_OLDHEAD\"}]" \
  drv_stderr "#1030 the head disagreement emits its own 'two verdict keys disagree' breadcrumb" "verdict keys disagree"
# ...and so must the marker and the reviews-API state.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"CHANGES_REQUESTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_APPROVE\"}]" \
  drv "#1030 marker APPROVE on a CHANGES_REQUESTED review -> incomplete (contradiction)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_REJECT\"}]" \
  drv "#1030 marker REJECT on an APPROVED review -> incomplete (contradiction)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"APPROVED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_REJECT\"}]" \
  drv_stderr "#1030 the state contradiction emits its own 'contradict each other' breadcrumb" "contradict each other"

# Malformed marker shapes — each fails closed with its own breadcrumb, never a guess.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"<!-- prflow:review-verdict head=$DRV_NEW -->\"}]" \
  drv "#1030 marker with no verdict= field -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"<!-- prflow:review-verdict head=$DRV_NEW verdict=MAYBE -->\"}]" \
  drv "#1030 marker with an out-of-enum verdict token -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"<!-- prflow:review-verdict head=$DRV_NEW\nverdict=APPROVE -->\"}]" \
  drv "#1030 marker split across two lines -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_APPROVE\n$DRV_M_REJECT\"}]" \
  drv "#1030 two markers within the scanned window -> incomplete (ambiguous, fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"$DRV_M_APPROVE\n$DRV_M_REJECT\"}]" \
  drv_stderr "#1030 the two-marker case emits its own 'TWO prflow:review-verdict marker lines' breadcrumb" "TWO prflow:review-verdict marker lines"
# A marker QUOTED inside a fenced block by a finding is prose, not the producer's stamp:
# it is outside the scanned window, so this review is not even admitted and the run ends
# at the pre-existing no-verdict arm rather than reading the quoted token.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[{\"state\":\"COMMENTED\",\"commit_id\":\"$DRV_NEW\",\"body\":\"a finding says:\n\n\`\`\`\n$DRV_M_APPROVE\n\`\`\`\n\"}]" \
  drv "#1030 a marker quoted in a fenced block is never read as the verdict -> incomplete" "incomplete false"

# The progress-comment surface. With NO review on HEAD, this run's run-keyed comment
# carries the marker on the line after its run key, and that is the verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n$DRV_M_REJECT\n## 🔴 Devflow Review — REJECT\"}]" \
  drv "#1030 marker on this run's progress comment, no review on HEAD -> reject" "reject true"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n$DRV_M_APPROVE\n## ✅ Devflow Review — APPROVE\"}]" \
  drv "#1030 marker on this run's progress comment, no review on HEAD -> approve" "approve true"
# On a comment the marker's head= is authoritative, so one naming another commit is a
# stale artifact and must not become this HEAD's verdict.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n$DRV_M_OLDHEAD\n## ✅ Devflow Review — APPROVE\"}]" \
  drv "#1030 progress-comment marker naming another head -> incomplete (fail closed)" "incomplete false"
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n<!-- prflow:review-verdict head=$DRV_NEW verdict=MAYBE -->\"}]" \
  drv "#1030 malformed progress-comment marker -> incomplete (fail closed)" "incomplete false"
# The transitional prose arm on the comment surface is UNCHANGED — an unmarked
# progress comment still resolves through `## Verdict:` exactly as before.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n## Verdict: APPROVE\"}]" \
  drv "#1030 unmarked progress comment still resolves through the transitional prose" "approve true"
# ...and the superseded devflow: run-key spelling is still accepted (issue #1003's
# dual read on the PROGRESS marker is untouched by #1030's single-spelling rule).
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"<!-- devflow:review-progress run=100-1 -->\n$DRV_M_APPROVE\"}]" \
  drv "#1030 the superseded devflow: run-key spelling still reaches the marker" "approve true"
# The verdict marker itself accepts ONLY the prflow: spelling — a devflow:review-verdict
# marker is not a marker at all, so the body falls through to the prose arms.
HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER=1 REPO=o/r GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" \
  DRV_REVIEWS="[]" DRV_COMMENTS="[{\"body\":\"$DRV_PROGRESS\n<!-- devflow:review-verdict head=$DRV_NEW verdict=APPROVE -->\"}]" \
  drv "#1030 a devflow:review-verdict spelling is not accepted as a marker -> incomplete" "incomplete false"

# always exits 0 (best-effort; caller reads the verdict, not the exit code).
( HEAD_SHA="$DRV_NEW" ENGINE_ERROR=false PR_NUMBER="" GITHUB_RUN_ID=100 DEVFLOW_GH="$DRV_STUB" bash "$DRV" >/dev/null 2>&1 ); DRV_RC=$?
assert_eq "#249 deriver always exits 0 (best-effort)" "0" "$DRV_RC"
rm -f "$DRV_STUB"

# ────────────────────────────────────────────────────────────────────────────
echo "derive-review-preconditions.sh (#304 branch-freshness + other-CI-green gate)"
# ────────────────────────────────────────────────────────────────────────────
# COVERAGE RETIREMENT RECORDED (issue #936) — read this before reconstructing the tier.
# The `#304` block that issue #936 removed from lib/test/run.sh carried URL-LITERAL pins on
# THIS still-shipped helper: the `compare/$BASE_BRANCH...$HEAD_SHA` operand ORDER, and the
# `?head_sha=$HEAD_SHA` scoping parameter. This module's gh stub is URL-shape-BLIND (it
# matches `*compare/*` and `*head_sha=*` regardless of operand order or presence), so a
# regression that reversed the compare operands or dropped the scoping parameter would now
# go UNCAUGHT here. That loss is accepted, not overlooked, and the reason is narrow: with the
# tier withheld this helper is unreachable in DevFlow's own tree, so such a regression has no
# in-repo effect — it would surface only in an installed consumer copy or in a reconstruction.
# This is a retirement for an UNREACHABLE-IN-TREE helper, NOT a "the subject was deleted"
# retirement: the helper still ships. A reconstruction of the tier must restore those two
# URL-literal pins (or teach this stub to discriminate operand order) as part of the work.
#
# The unit precheck.route calls before emitting should_run=true on the
# first-review / synchronize / completion-re-trigger paths. It evaluates two
# config-gated preconditions against the PR head and prints:
#   should_run=<true|false>
#   reason=<empty|behind-base|ci-not-green|unverifiable>
# always exit 0. Fail-closed arms: an unverifiable compare, an unverifiable CI
# query, or missing inputs all -> unverifiable (never a positively-asserted
# behind-base/ci-not-green the script did not observe). The
# CI-green set is generic (no job names): Actions workflow runs for the head
# excluding SELF_WORKFLOW_NAME, legacy combined status, and non-Actions check
# runs. Zero entries across all three -> satisfied (a CI-less repo is reviewed
# immediately, never wedged).
DRP="$LIB/../scripts/derive-review-preconditions.sh"
DRP_STUB="/tmp/devflow-gh-stub-drp.$$.sh"
cat > "$DRP_STUB" <<'EOS'
#!/usr/bin/env bash
# Echo raw JSON (the script pipes it through jq itself). DRP_*_FAIL=1 forces the
# matching query to fail so the fail-closed arms can be exercised. Defaults are
# assigned up front (a `}` inside a ${VAR-default} brace expansion terminates
# the expansion early and corrupts the JSON — do not inline them).
[ -n "${DRP_COMPARE-}" ] || DRP_COMPARE='{"behind_by":0}'
[ -n "${DRP_RUNS-}" ]    || DRP_RUNS='{"workflow_runs":[]}'
[ -n "${DRP_CHECKS-}" ]  || DRP_CHECKS='{"check_runs":[]}'
[ -n "${DRP_STATUS-}" ]  || DRP_STATUS='{"state":"pending","total_count":0}'
case "$*" in
  *"compare/"*)          [ "${DRP_COMPARE_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "$DRP_COMPARE"; exit 0 ;;
  *"actions/runs"*)      [ "${DRP_RUNS_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "$DRP_RUNS"; exit 0 ;;
  *"/check-runs"*)       [ "${DRP_CHECKS_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "$DRP_CHECKS"; exit 0 ;;
  *"/status"*)           [ "${DRP_STATUS_FAIL:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }; printf '%s' "$DRP_STATUS"; exit 0 ;;
esac
echo '{}'; exit 0
EOS
chmod +x "$DRP_STUB"

drp() {  # $1=description  $2=expected "<should_run> <reason>"
  local out r s
  out="$(bash "$DRP" 2>/dev/null)"
  s="$(printf '%s\n' "$out" | sed -n 's/^should_run=//p')"
  r="$(printf '%s\n' "$out" | sed -n 's/^reason=//p')"
  assert_eq "$1" "$2" "$s $r"
}
drp_stderr() {  # $1=description  $2=expected stderr substring
  local err
  err="$(bash "$DRP" 2>&1 1>/dev/null)"
  assert_eq "$1" "yes" "$(printf '%s' "$err" | grep -qF -- "$2" && echo yes || echo no)"
}

# AC1: branch behind base + require_up_to_date -> defer with behind-base reason.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":3}' \
  drp "#304 behind base (behind_by=3) + require_up_to_date -> false behind-base" "false behind-base"
# AC7/AC8: the key set to false restores unconditional behavior for that arm.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":3}' \
  drp "#304 behind base but require_up_to_date=false -> true (unconditional restored)" "true "
# Not behind -> freshness precondition passes.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":0}' \
  drp "#304 not behind (behind_by=0) -> true" "true "
# AC10: compare query failure fails CLOSED with a specific breadcrumb.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE_FAIL=1 \
  drp "#304 compare query failure -> false unverifiable (fail closed, honest reason)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE_FAIL=1 \
  drp_stderr "#304 compare query failure emits the specific 'compare query failed' breadcrumb" "compare query failed"
# A non-numeric behind_by (adversarial payload shape) also fails closed.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"message":"Not Found"}' \
  drp "#304 compare payload without numeric behind_by -> false unverifiable (fail closed)" "false unverifiable"

# AC2 (failure arm): another workflow run concluded failure -> defer ci-not-green.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1,"status":"completed","conclusion":"failure"}]}' \
  drp "#304 other workflow run failed -> false ci-not-green" "false ci-not-green"
# AC2 (pending arm): another workflow run still in progress -> defer.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1,"status":"in_progress","conclusion":null}]}' \
  drp "#304 other workflow run in_progress -> false ci-not-green (pending)" "false ci-not-green"
# AC3 + AC9: only the review workflow's own run present -> excluded by
# SELF_WORKFLOW_NAME -> zero other CI -> satisfied (self never blocks itself,
# and a CI-less head is reviewed, not wedged).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  SELF_WORKFLOW_NAME='Devflow Review (auto-trigger)' \
  DRP_RUNS='{"workflow_runs":[{"name":"Devflow Review (auto-trigger)","status":"in_progress","conclusion":null}]}' \
  drp "#304 only the review workflow itself running -> true (self-excluded; zero other CI satisfied)" "true "
# AC4: all other runs green -> proceed.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1,"status":"completed","conclusion":"success"},{"name":"Devflow Review (auto-trigger)","status":"in_progress","conclusion":null}]}' \
  drp "#304 other CI green (self still running) -> true" "true "
# Skipped/neutral conclusions on other runs are green (a path-filtered workflow
# must not wedge the review).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"Docs","workflow_id":1,"event":"pull_request","run_number":1,"status":"completed","conclusion":"skipped"},{"name":"Lint","workflow_id":2,"event":"pull_request","run_number":1,"status":"completed","conclusion":"neutral"}]}' \
  drp "#304 skipped/neutral other runs count as green -> true" "true "
# AC10: workflow-runs query failure fails CLOSED with a specific breadcrumb.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS_FAIL=1 \
  drp "#304 workflow-runs query failure -> false unverifiable (fail closed, honest reason)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS_FAIL=1 \
  drp_stderr "#304 workflow-runs query failure emits the specific 'workflow-runs query failed' breadcrumb" "workflow-runs query failed"
# Legacy combined status: a red commit status blocks; total_count=0 does not
# (the combined-status state is 'pending' when NO statuses exist — total_count
# gates it, so an empty status set is never read as pending).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"failure","total_count":2}' \
  drp "#304 legacy commit status red -> false ci-not-green" "false ci-not-green"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"pending","total_count":0}' \
  drp "#304 zero legacy statuses (state pending, total_count 0) -> true (not read as pending)" "true "
# Statuses EXIST and are still pending (the primary real-world gating shape —
# distinct from the zero-statuses case above, which shares the API 'pending'
# state string but must proceed).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"pending","total_count":3}' \
  drp "#304 pending legacy statuses (total_count>0) -> false ci-not-green" "false ci-not-green"
# AC10 applied to signals (2) and (3): combined-status / check-runs query
# failures fail CLOSED too, each with its specific breadcrumb.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS_FAIL=1 \
  drp "#304 combined-status query failure -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS_FAIL=1 \
  drp_stderr "#304 combined-status query failure emits the specific 'combined-status query failed' breadcrumb" "combined-status query failed"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS_FAIL=1 \
  drp "#304 check-runs query failure -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS_FAIL=1 \
  drp_stderr "#304 check-runs query failure emits the specific 'check-runs query failed' breadcrumb" "check-runs query failed"
# #311 (AC2a): each gh-failure arm now captures gh's OWN stderr into its
# breadcrumb (mirroring resolve_pr_for_head), so the operator sees the underlying
# cause — rate limit / 403 token-scope / 5xx — not just "query failed". The stub
# writes 'HTTP 500' to stderr on a forced failure; before the capture that text
# was discarded by `2>/dev/null` and never reached the breadcrumb.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE_FAIL=1 \
  drp_stderr "#311 compare-failure breadcrumb embeds the captured gh stderr" "HTTP 500"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS_FAIL=1 \
  drp_stderr "#311 workflow-runs-failure breadcrumb embeds the captured gh stderr" "HTTP 500"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS_FAIL=1 \
  drp_stderr "#311 combined-status-failure breadcrumb embeds the captured gh stderr" "HTTP 500"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS_FAIL=1 \
  drp_stderr "#311 check-runs-failure breadcrumb embeds the captured gh stderr" "HTTP 500"
# The external-check-runs jq normalization is a parallel copy of the tested
# workflow-runs one — give it its own paginated + garbage adversarial cases.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='{"check_runs":[{"name":"a","app":{"slug":"circleci"},"status":"completed","conclusion":"success"}]}{"check_runs":[{"name":"b","app":{"slug":"circleci"},"status":"completed","conclusion":"failure"}]}' \
  drp "#304 paginated check-runs payload: page-2 external failure still gates -> false ci-not-green" "false ci-not-green"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='"garbage"' \
  drp "#304 non-object check-runs payload -> false unverifiable (parse fails closed)" "false unverifiable"
# Anything-but-literal-false enables a gate (the header's fail-toward-gating
# contract): a garbage/empty REQUIRE_* value must still gate.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=maybe REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":3}' \
  drp "#304 garbage REQUIRE_UP_TO_DATE value ('maybe') still gates -> false behind-base (fail toward gating)" "false behind-base"
# Legacy statuses exist AND are green -> proceed (the success arm of signal 2;
# an inverted state comparison would defer every legacy-status repo forever).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"success","total_count":2}' \
  drp "#304 green legacy statuses (state success, total_count>0) -> true" "true "
# Both gates enabled, everything green end-to-end (not behind + all signals
# green) -> true. The only all-defaults happy-path case with BOTH gates on,
# catching a sequencing regression between precondition 1 and 2.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":0}' \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1,"status":"completed","conclusion":"success"}]}' \
  DRP_STATUS='{"state":"success","total_count":1}' \
  DRP_CHECKS='{"check_runs":[{"name":"ext","app":{"slug":"circleci"},"status":"completed","conclusion":"success"}]}' \
  drp "#304 both gates enabled, all signals green -> true (full happy path)" "true "
# Combined-status payload with a non-numeric / absent total_count (adversarial
# shape) -> unverifiable. Mirrors the behind_by 'no numeric value' arm above:
# this is the total_count parse arm (script's STATUS_TOTAL guard), distinct from
# the no-string-state arm below (which supplies a numeric total_count).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"pending"}' \
  drp "#304 combined status without a numeric total_count -> false unverifiable (shape fails closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"state":"pending"}' \
  drp_stderr "#304 non-numeric total_count emits the specific 'no numeric total_count' breadcrumb" "combined-status payload carried no numeric total_count"
# Statuses exist but carry no string state (adversarial shape) -> unverifiable,
# never a positively-asserted ci-not-green.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_STATUS='{"total_count":2}' \
  drp "#304 combined status without a string state -> false unverifiable (shape fails closed)" "false unverifiable"
# Precondition precedence: behind base AND red CI -> the freshness reason wins
# (checked first); a reordering would flip the user-facing recovery guidance.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE='{"behind_by":3}' \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","status":"completed","conclusion":"failure"}]}' \
  drp "#304 behind base AND red CI -> false behind-base (freshness precedence)" "false behind-base"
# The shared green-gate pending arm driven via the EXTERNAL check-runs caller
# (previously exercised only via the workflow-runs caller).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='{"check_runs":[{"name":"ext","app":{"slug":"circleci"},"status":"in_progress","conclusion":null}]}' \
  drp "#304 external check run in_progress -> false ci-not-green (pending, external caller)" "false ci-not-green"
# A run object WITHOUT a status field: the run itself is an observed signal,
# its unknown status is deliberately treated as not-completed (pending) —
# pinned so a future edit makes this choice consciously.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1}]}' \
  drp "#304 workflow run without a status field -> false ci-not-green (observed run, unknown status = pending)" "false ci-not-green"
# The base_branch extraction expression, executed like the require_* ones.
assert_eq "#304 base_branch extraction: non-default value kept" "develop" \
  "$(echo '{"base_branch":"develop"}' | jq -r '(try .base_branch catch null) // "main"')"
assert_eq "#304 base_branch extraction: absent key defaults main" "main" \
  "$(echo '{}' | jq -r '(try .base_branch catch null) // "main"')"
# Non-Actions (external app) check runs gate too; the Devflow Review check-run
# name is excluded even off-app (defensive).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='{"check_runs":[{"name":"external-ci","app":{"slug":"circleci"},"status":"completed","conclusion":"failure"}]}' \
  drp "#304 external (non-Actions) check run failed -> false ci-not-green" "false ci-not-green"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='{"check_runs":[{"name":"Devflow Review","app":{"slug":"some-app"},"status":"in_progress","conclusion":null},{"name":"precheck","app":{"slug":"github-actions"},"status":"in_progress","conclusion":null}]}' \
  drp "#304 Devflow Review check-run + Actions-app check runs excluded from the external set -> true" "true "
# AC7: require_ci_green=false restores unconditional behavior for that arm.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","status":"completed","conclusion":"failure"}]}' \
  drp "#304 red CI but require_ci_green=false -> true (unconditional restored)" "true "
# Both keys false -> no queries at all (every query poisoned; still true).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  DRP_COMPARE_FAIL=1 DRP_RUNS_FAIL=1 DRP_STATUS_FAIL=1 DRP_CHECKS_FAIL=1 \
  drp "#304 both preconditions disabled -> true with zero API queries" "true "
# Missing inputs are unverifiable -> fail closed with the unverifiable reason.
REPO=o/r HEAD_SHA="" BASE_BRANCH=main REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  drp "#304 empty HEAD_SHA -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH="" REQUIRE_UP_TO_DATE=true REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" \
  drp "#304 empty BASE_BRANCH with freshness gate on -> false unverifiable (never a hardcoded main)" "false unverifiable"
# Paginated (concatenated-objects) workflow-runs payload: a failure on page 2
# must still gate — the -s normalization flattens the page objects.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"A","workflow_id":1,"event":"pull_request","run_number":1,"status":"completed","conclusion":"success"}]}{"workflow_runs":[{"name":"B","workflow_id":2,"event":"pull_request","run_number":1,"status":"completed","conclusion":"failure"}]}' \
  drp "#304 paginated workflow-runs payload: page-2 failure still gates -> false ci-not-green" "false ci-not-green"
# Adversarial shape: a non-object/garbage runs payload is a parse failure ->
# fail closed, never a fabricated green.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='"garbage"' \
  drp "#304 non-object workflow-runs payload -> false unverifiable (parse fails closed)" "false unverifiable"
# always exits 0 (best-effort; the route step reads stdout, not the exit code).
( REPO="" HEAD_SHA="" BASE_BRANCH="" DEVFLOW_GH="$DRP_STUB" bash "$DRP" >/dev/null 2>&1 ); DRP_RC=$?
assert_eq "#304 preconditions script always exits 0 (best-effort)" "0" "$DRP_RC"
# Output contract: exactly two lines, should_run= then reason= (the route step's
# sed consumers depend on this exact shape).
DRP_CONTRACT_OUT="$(REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=false DEVFLOW_GH="$DRP_STUB" bash "$DRP" 2>/dev/null)"
assert_eq "#304 preconditions stdout contract: exactly 2 lines" "2" "$(printf '%s\n' "$DRP_CONTRACT_OUT" | wc -l | tr -d ' ')"
assert_eq "#304 preconditions stdout contract: line 1 should_run=, line 2 reason=" "yes" \
  "$(printf '%s\n' "$DRP_CONTRACT_OUT" | sed -n '1s/^should_run=.*/ok1/p;2s/^reason=.*/ok2/p' | tr '\n' ' ' | grep -q 'ok1 ok2' && echo yes || echo no)"

# ── #351: collapse non-self workflow runs to the latest per (workflow_id, event) ──
# Signal-set (1) now collapses duplicate runs of the same workflow+event to the
# highest-run_number run before gating, so a superseded non-green run never wedges
# the review once a newer run of the same group exists. A NON-self run missing a
# numeric workflow_id/run_number makes the collapse unverifiable and fails closed.
# A completed run awaiting approval (conclusion action_required) gets its own
# distinct reason (ci-approval-required), in the SHARED green-gate so signal-set
# (3) external check runs get it too.
# #351 AC1/AC3: the literal PR #349 payload — run 1435 action_required + run 1436
# success, same workflow_id/event — collapses to the newer green run -> true.
# (RED before the fix: the un-collapsed action_required line deferred the review.)
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":280327711,"event":"pull_request","run_number":1435,"status":"completed","conclusion":"action_required"},{"name":"CI","workflow_id":280327711,"event":"pull_request","run_number":1436,"status":"completed","conclusion":"success"}]}' \
  drp "#351 superseded action_required + newer success (PR #349 payload) collapses -> true" "true "
# #351 AC8-companion: a single-run group is a collapse no-op -> still true.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":9,"status":"completed","conclusion":"success"}]}' \
  drp "#351 single green run in a group (collapse no-op) -> true" "true "
# #351 AC2: a self-named run is excluded BEFORE grouping — even one lacking
# workflow_id/run_number never trips the numeric-operand guard — so a green CI run
# still collapses to true (the guard applies to NON-self runs only).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  SELF_WORKFLOW_NAME='Devflow Review (auto-trigger)' \
  DRP_RUNS='{"workflow_runs":[{"name":"Devflow Review (auto-trigger)","event":"pull_request","status":"in_progress","conclusion":null},{"name":"CI","workflow_id":1,"event":"pull_request","run_number":6,"status":"completed","conclusion":"success"}]}' \
  drp "#351 self run (no workflow_id) excluded before the guard; green CI collapses -> true" "true "
# #351 AC4: the highest-run_number run in a group is NOT completed -> defer
# ci-not-green, regardless of a lower-run_number green sibling in that group.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1435,"status":"completed","conclusion":"success"},{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1436,"status":"in_progress","conclusion":null}]}' \
  drp "#351 newest run in group not completed (green sibling superseded) -> false ci-not-green" "false ci-not-green"
# #351 AC5: the highest-run_number run in a group concluded failure -> defer
# ci-not-green, regardless of a lower-run_number green sibling.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1435,"status":"completed","conclusion":"success"},{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1436,"status":"completed","conclusion":"failure"}]}' \
  drp "#351 newest run in group failed (green sibling superseded) -> false ci-not-green" "false ci-not-green"
# #351 AC3 (collapse discriminator): an OLDER failure superseded by a NEWER success
# in the same group collapses to the newer green run -> true. This is the case that
# is uniquely RED on pre-fix code and GREEN post-fix: pre-fix emitted every non-self
# line, so the older failure deferred ci-not-green; post-fix max_by(.run_number)
# drops it. (AC4/AC5 above pin the reverse — newest non-green gates despite a green
# sibling — but their superseded sibling is itself non-green, so pre-fix code already
# deferred and they do not discriminate the "newest green supersedes older red"
# contract; this case does. It uses a plain failure, not action_required, so it is a
# pure collapse test independent of the AC9 ci-approval-required arm.)
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1435,"status":"completed","conclusion":"failure"},{"name":"CI","workflow_id":1,"event":"pull_request","run_number":1436,"status":"completed","conclusion":"success"}]}' \
  drp "#351 older failure superseded by newer success (same group) collapses -> true (RED pre-fix)" "true "
# #351 AC6: same workflow_id under DIFFERENT events are two independent groups —
# a failure under one event defers even when the run under the other event is
# newer and green (the collapse is per (workflow_id, event), not per workflow_id).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"push","run_number":5,"status":"completed","conclusion":"failure"},{"name":"CI","workflow_id":1,"event":"pull_request","run_number":6,"status":"completed","conclusion":"success"}]}' \
  drp "#351 same workflow_id, different events stay independent: push failure still gates -> false ci-not-green" "false ci-not-green"
# #351 AC7: a NON-self run missing workflow_id -> unverifiable (never a dropped
# signal, never a positively-asserted ci-not-green), with a breadcrumb NAMING the
# missing field. (RED before the fix: with no guard the run would gate ci-not-green.)
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","event":"pull_request","run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp "#351 non-self run missing workflow_id -> false unverifiable (fail closed, no dropped signal)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","event":"pull_request","run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp_stderr "#351 missing workflow_id breadcrumb names the field" "numeric workflow_id"
# #351 AC7: a NON-self run whose run_number is non-numeric -> unverifiable, with a
# breadcrumb naming run_number.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":"nope","status":"completed","conclusion":"failure"}]}' \
  drp "#351 non-self run with non-numeric run_number -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":"nope","status":"completed","conclusion":"failure"}]}' \
  drp_stderr "#351 non-numeric run_number breadcrumb names the field" "numeric run_number"
# #351 AC7 (shape-matrix completion): the guard treats workflow_id and run_number
# with the same `type != "number"` predicate, so sweep the remaining two of the
# {missing, non-numeric} x {workflow_id, run_number} matrix — a present-but-non-numeric
# workflow_id and a missing run_number — both fail closed unverifiable, each with a
# field-naming breadcrumb. workflow_id is checked before run_number, so a run failing
# BOTH still names workflow_id first.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":"nope","event":"pull_request","run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp "#351 non-self run with non-numeric workflow_id -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":"nope","event":"pull_request","run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp_stderr "#351 non-numeric workflow_id breadcrumb names the field" "numeric workflow_id"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","status":"completed","conclusion":"failure"}]}' \
  drp "#351 non-self run missing run_number -> false unverifiable (fail closed)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","status":"completed","conclusion":"failure"}]}' \
  drp_stderr "#351 missing run_number breadcrumb names the field" "numeric run_number"
# #351 AC7 (event operand): `event` is the OTHER group-key operand — an absent/non-string
# event mis-groups a run under a null bucket, so an older non-green run could survive the
# collapse in its own group and re-wedge the review (the exact fail-open #351 fixes). It is
# validated (string) before grouping like the two numeric fields, so a non-self run missing
# event -> false unverifiable with a field-naming breadcrumb. (workflow_id/run_number are
# checked first, so a run failing multiple operands names workflow_id before event.)
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp "#351 non-self run missing event -> false unverifiable (fail closed, no mis-group)" "false unverifiable"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"run_number":6,"status":"completed","conclusion":"failure"}]}' \
  drp_stderr "#351 missing event breadcrumb names the field" "string event"
# #351 AC8: zero NON-self workflow runs still satisfies the CI-green precondition
# (a CI-less-repo / self-only head is reviewed, never wedged).
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[]}' \
  drp "#351 zero non-self workflow runs -> true (never wedged)" "true "
# #351 AC9: a surviving run (signal-set 1) whose newest conclusion is
# action_required -> defer with the DISTINCT ci-approval-required reason, and the
# breadcrumb names approval as the blocker.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":6,"status":"completed","conclusion":"action_required"}]}' \
  drp "#351 newest run action_required (signal-set 1) -> false ci-approval-required" "false ci-approval-required"
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_RUNS='{"workflow_runs":[{"name":"CI","workflow_id":1,"event":"pull_request","run_number":6,"status":"completed","conclusion":"action_required"}]}' \
  drp_stderr "#351 action_required breadcrumb names approval as the blocker" "an approval is required"
# #351 AC9 (signal-set 3): the SHARED green-gate gives an external check run
# concluding action_required the same ci-approval-required reason.
REPO=o/r HEAD_SHA=aaaa BASE_BRANCH=main REQUIRE_UP_TO_DATE=false REQUIRE_CI_GREEN=true DEVFLOW_GH="$DRP_STUB" \
  DRP_CHECKS='{"check_runs":[{"name":"ext","app":{"slug":"circleci"},"status":"completed","conclusion":"action_required"}]}' \
  drp "#351 external check run action_required (signal-set 3, shared gate) -> false ci-approval-required" "false ci-approval-required"
# #353 (coupled WORKFLOW half of #351's ci-approval-required, landed via human/PAT):
# the deferral check-run title pin (the title create_check posts) and the
# deferral-SUMMARY 'cancelled sibling run' removal pin. These static grep pins move
# with the workflow change so they land in the same commit as the code they assert.
# AC10: ci-approval-required maps to its exact title. The SKIP_REASON->title
# selection moved from create_check's inline `case` arm into describe-skip-title.sh
# (#389), so this pin now asserts the title lives (once) in the helper.
# Spelled as a $LIB-relative path VARIABLE, never inlined into the pin call as
# "$LIB/../…": pin-corpus-lint.py resolves such an assignment but cannot resolve an
# interpolated path sitting directly in the argument, so an inlined target leaves the
# pin UNRESOLVED — surfaced on stderr but never asserted, i.e. silently exempt from
# the meta-guards (the extraction hazard issue #746 names).
DST_HELPER="$LIB/../scripts/describe-skip-title.sh"
devflow_module_pin_unique "#353 create_check maps ci-approval-required to its exact title (via the helper)" \
  "Devflow review waiting: CI approval required" \
  "$DST_HELPER"
# AC13-guard: the absence pin below reads "no" both when the phrase is truly
# gone AND when the workflow file is missing/renamed/unreadable (a failed grep
# also yields "no", the expected value) — the repo's vacuous-pin/fail-open bug
# class. This existence pin makes the absence assertion fail CLOSED on a missing
# target INDEPENDENTLY of AC10's uniqueness pin, so a future edit that relocates
# AC10 cannot silently re-open the hole. The operand is the deterministic
# `[ -f FILE ]` test (yes on a present file, no otherwise); assert_eq expects
# "yes", so a renamed/removed target flips it to "no" and the suite goes RED.
# RETIRED (issue #936): the AC13 existence backstop and the absence pin it protected both
# targeted `.github/workflows/devflow-review.yml`, which issue #936 removed from the tree when
# it withheld the auto PR-triggered review tier. The pair is deleted rather than re-anchored:
# their shared subject no longer exists, so there is no target to fail closed against, and
# CONTRIBUTING.md's retirement arms do not reach this case (they govern retiring a pin while
# its pinned subject REMAINS in the tree — here the subject itself is gone). The helper this
# section covers, `describe-skip-title.sh`, is RETAINED and its behavioral assertions above
# are untouched: the withheld tier's own workflow file is deleted, but every helper it called
# stays shipped so an existing consumer's installed copy keeps resolving them after upgrade.
# What is lost: nothing that a surviving file can assert. What replaces it: a reconstruction
# of the tier must restore this pair alongside the workflow.
# AC13-guard fail-closed proof: the existence idiom yields "no" on a
# missing/renamed target (the absent-operand shape), so the assert_eq above
# would go RED rather than pass vacuously if the workflow file ever moves.
assert_eq "#353 existence idiom fails closed on a missing workflow file" "no" \
  "$([ -f "$LIB/../.github/workflows/devflow-review-DOES-NOT-EXIST.yml" ] && echo yes || echo no)"
# AC13: the deferral SUMMARY no longer cites a cancelled sibling run as a
# permanently-stuck signal (the #351 collapse now auto-resolves the superseded
# cancelled-sibling case), so the phrase must be GONE (expected no). The
# existence pin above closes the vacuous-pass hole (file present is proven).
# This line's grep expression contains no _SKILL/SKILL_/SKILL.md token (its target filename
# devflow-review.yml has none), so the #157 AC2 raw-guard scanner — which greps each .sh
# SOURCE line for a grep…SKILL…echo shape, not the referenced file's contents — never matches
# this line. It needs no `# raw-guard-ok:` marker; a former one here exempted nothing and read
# as coverage it did not provide, so it was dropped (issue #758).
# (the #353 absence pin that stood here is retired with its existence backstop above)
rm -f "$DRP_STUB"

# ────────────────────────────────────────────────────────────────────────────
echo "parse-engine-error.sh (#249 execution-log is_error parser feeding engine_is_error)"
# ────────────────────────────────────────────────────────────────────────────
# The producer of devflow-runner.yml's engine_is_error output (extracted from the
# inline workflow jq so its array/object/fail-safe branches are verified). Fail-safe:
# any absent/unparseable field yields "false" (is_error is defense-in-depth; the
# deriver's HEAD-SHA scoping is the primary guard).
PEE="$LIB/../scripts/parse-engine-error.sh"
PEE_TMP="$(mktemp -d)"
# stream-json ARRAY where a type==result element carries is_error (any result with is_error=true wins)
printf '%s' '[{"type":"system"},{"type":"result","is_error":true}]'  > "$PEE_TMP/arr_true.json"
printf '%s' '[{"type":"assistant"},{"type":"result","is_error":false}]' > "$PEE_TMP/arr_false.json"
# a single result OBJECT
printf '%s' '{"type":"result","is_error":true}'  > "$PEE_TMP/obj_true.json"
printf '%s' '{"type":"result","is_error":false}' > "$PEE_TMP/obj_false.json"
# JSONL (one object per line, no enclosing array) — the shape a bare `jq` without
# -s would mis-handle; the -s slurp normalizes it.
printf '{"type":"system"}\n{"type":"assistant"}\n{"type":"result","is_error":true}\n'  > "$PEE_TMP/jsonl_true.json"
printf '{"type":"system"}\n{"type":"result","is_error":false}\n'                       > "$PEE_TMP/jsonl_false.json"
# absent is_error field (object AND array-result), empty array, and unparseable -> false
printf '%s' '{"type":"result"}'  > "$PEE_TMP/obj_missing.json"
printf '%s' '[{"type":"system"},{"type":"result"}]' > "$PEE_TMP/arr_missing.json"
printf '%s' '[]'                 > "$PEE_TMP/empty_arr.json"
printf '%s' 'not json {{'        > "$PEE_TMP/garbage.json"
assert_eq "#249 parse-engine-error: array w/ a result is_error=true -> true"  "true"  "$(bash "$PEE" "$PEE_TMP/arr_true.json")"
assert_eq "#249 parse-engine-error: array w/ a result is_error=false -> false" "false" "$(bash "$PEE" "$PEE_TMP/arr_false.json")"
assert_eq "#249 parse-engine-error: single result object is_error=true -> true"   "true"  "$(bash "$PEE" "$PEE_TMP/obj_true.json")"
assert_eq "#249 parse-engine-error: single result object is_error=false -> false" "false" "$(bash "$PEE" "$PEE_TMP/obj_false.json")"
assert_eq "#249 parse-engine-error: JSONL w/ a result is_error=true -> true"  "true"  "$(bash "$PEE" "$PEE_TMP/jsonl_true.json")"
assert_eq "#249 parse-engine-error: JSONL w/ a result is_error=false -> false" "false" "$(bash "$PEE" "$PEE_TMP/jsonl_false.json")"
assert_eq "#249 parse-engine-error: absent is_error field (object) -> false (fail-safe)" "false" "$(bash "$PEE" "$PEE_TMP/obj_missing.json")"
assert_eq "#249 parse-engine-error: absent is_error field (array result) -> false (fail-safe)" "false" "$(bash "$PEE" "$PEE_TMP/arr_missing.json")"
assert_eq "#249 parse-engine-error: empty array (no result) -> false (fail-safe)" "false" "$(bash "$PEE" "$PEE_TMP/empty_arr.json")"
assert_eq "#249 parse-engine-error: unparseable log -> false (fail-safe)"         "false" "$(bash "$PEE" "$PEE_TMP/garbage.json")"
assert_eq "#249 parse-engine-error: missing file arg -> false (fail-safe)"        "false" "$(bash "$PEE" "$PEE_TMP/does-not-exist.json")"
assert_eq "#249 parse-engine-error: empty arg -> false (fail-safe)"               "false" "$(bash "$PEE" "")"
( bash "$PEE" "$PEE_TMP/arr_true.json" >/dev/null 2>&1 ); assert_eq "#249 parse-engine-error: always exits 0 (best-effort)" "0" "$?"
# nested result object (pins the `..` any-depth recursion the header advertises;
# a refactor to top-level-only `.[]` ships RED)
printf '%s' '[{"type":"system","payload":{"type":"result","is_error":true}}]' > "$PEE_TMP/nested_true.json"
assert_eq "#249 parse-engine-error: NESTED result is_error=true -> true (any-depth recursion pinned)" "true" "$(bash "$PEE" "$PEE_TMP/nested_true.json" 2>/dev/null)"
# the type filter is load-bearing in the OTHER direction too: is_error=true on a
# NON-result object (e.g. a tool_result event) must stay false — dropping the
# select(.type=="result") would over-report engine errors and wedge good runs.
printf '%s' '[{"type":"tool_result","is_error":true},{"type":"result","is_error":false}]' > "$PEE_TMP/tool_err.json"
assert_eq "#249 parse-engine-error: is_error=true on a non-result object -> false (type filter pinned)" "false" "$(bash "$PEE" "$PEE_TMP/tool_err.json" 2>/dev/null)"
# ANY-result-wins across MULTIPLE result events (pins any() vs a last-wins
# refactor: an errored mid-stream result followed by a clean final one -> true)
printf '%s' '[{"type":"result","is_error":true},{"type":"result","is_error":false}]' > "$PEE_TMP/two_results.json"
assert_eq "#249 parse-engine-error: two result events [true,false] -> true (ANY-wins pinned, not last-wins)" "true" "$(bash "$PEE" "$PEE_TMP/two_results.json" 2>/dev/null)"
# Truncated-tail JSONL (engine died mid-write): the -s slurp fails on the whole
# file, so even a complete is_error=true line above the truncation reads false
# + the jq-failure breadcrumb. Deliberate, documented trade-off pinned here:
# is_error is defense-in-depth; the deriver's no-verdict-for-HEAD arm is what
# actually fails the crashed run closed.
printf '{"type":"result","is_error":true}\n{"type":"sys' > "$PEE_TMP/trunc_tail.json"
assert_eq "#249 parse-engine-error: truncated-tail JSONL -> false (fail-safe; deriver HEAD-scoping is the real guard)" "false" "$(bash "$PEE" "$PEE_TMP/trunc_tail.json" 2>/dev/null)"
assert_eq "#249 parse-engine-error: truncated-tail JSONL emits the jq-failure breadcrumb" "yes" \
  "$(bash "$PEE" "$PEE_TMP/trunc_tail.json" 2>&1 1>/dev/null | grep -qF "jq failed parsing" && echo yes || echo no)"
# fail-safe arms leave breadcrumbs, never a silent false: a disarmed signal
# (renamed execution_file output, broken jq) must be visible in the job log.
assert_eq "#249 parse-engine-error: missing-file arm emits the 'execution file absent' breadcrumb" "yes" \
  "$(bash "$PEE" "$PEE_TMP/does-not-exist.json" 2>&1 1>/dev/null | grep -qF "execution file absent or empty" && echo yes || echo no)"
assert_eq "#249 parse-engine-error: unparseable-log arm emits the 'jq failed parsing' breadcrumb" "yes" \
  "$(bash "$PEE" "$PEE_TMP/garbage.json" 2>&1 1>/dev/null | grep -qF "jq failed parsing" && echo yes || echo no)"
rm -rf "$PEE_TMP"

# ────────────────────────────────────────────────────────────────────────────
echo "surface-execution-diagnostics.sh (#329 execution-diagnostics surfacer: run summary + permission denials)"
# ────────────────────────────────────────────────────────────────────────────
# Best-effort read-only surfacer: prints the run summary + permission-denial
# detail from a claude-code-action execution log to stdout (and $GITHUB_STEP_SUMMARY
# when set). Always exits 0. Degrades to count-only when no per-denial array is
# present, and to "no diagnostics available" when the file is absent/empty/
# unparseable or carries neither a result event nor denial detail. An absent
# permission_denials_count (with no denial array) reads "unavailable", never a
# fail-open zero. Mirrors parse-engine-error.sh's slurp-based traversal.
SED="$LIB/../scripts/surface-execution-diagnostics.sh"
SED_TMP="$(mktemp -d)"
# populated: result object carrying the run summary AND a permission_denials array
# with per-denial tool_name + tool_input (the tool_input long enough to truncate at the
# post-#1064 denial-line bound of 500 — the old 200-char bound was raised so the
# ungranted head of a long pipeline is not cut off; a 300-char input no longer truncates,
# so this fixture is 600 to still exercise the truncation arm at the new bound).
LONG_INPUT="$(printf 'x%.0s' $(seq 1 600))"
printf '%s' "$(printf '{"type":"result","is_error":false,"num_turns":12,"duration_ms":34567,"total_cost_usd":0.42,"permission_denials_count":2,"permission_denials":[{"tool_name":"Bash","tool_input":"%s"},{"tool_name":"Write","tool_input":"file.txt"}]}' "$LONG_INPUT")" > "$SED_TMP/populated.json"
# count-only: run summary with permission_denials_count but NO permission_denials array
printf '%s' '{"type":"result","is_error":true,"num_turns":3,"duration_ms":100,"total_cost_usd":0.01,"permission_denials_count":7}' > "$SED_TMP/count_only.json"
# zero denials
printf '%s' '{"type":"result","is_error":false,"num_turns":1,"duration_ms":5,"total_cost_usd":0.0,"permission_denials_count":0}' > "$SED_TMP/zero.json"
# JSONL shape carrying the result event on a later line (pins the -s slurp)
printf '{"type":"system"}\n{"type":"result","is_error":false,"num_turns":2,"permission_denials_count":1,"permission_denials":[{"tool_name":"Edit","tool_input":"a.py"}]}\n' > "$SED_TMP/jsonl.json"
# malformed / unparseable
printf '%s' 'not json {{'   > "$SED_TMP/garbage.json"
# empty file
: > "$SED_TMP/empty.json"
# parsed but NO result event and NO denials (message-only) -> the in-jq "no result
# event" arm (distinct from the shell absent/empty guard and the jq-failure arm)
printf '%s' '{"type":"system"}' > "$SED_TMP/msg_only.json"
# result event present but permission_denials_count ABSENT and no denials array:
# count is UNKNOWN, must NOT collapse to a success-shaped "No permission denials"
printf '%s' '{"type":"result","is_error":false,"num_turns":4}' > "$SED_TMP/no_count.json"
# denials array present but NO permission_denials_count field -> count derived from length
printf '%s' '{"type":"result","is_error":false,"permission_denials":[{"tool_name":"Read","tool_input":"x"},{"tool_name":"Bash","tool_input":"y"}]}' > "$SED_TMP/count_from_len.json"
# permission_denials is a bare OBJECT (not an array) -> the `else .` arm normalizes it
printf '%s' '{"type":"result","is_error":false,"permission_denials_count":1,"permission_denials":{"tool_name":"Glob","tool_input":"z"}}' > "$SED_TMP/denial_obj.json"
# result event missing duration_ms -> orna renders "n/a" (the null->n/a branch)
printf '%s' '{"type":"result","is_error":true,"num_turns":2,"permission_denials_count":0}' > "$SED_TMP/missing_field.json"
# denials in a NON-result event, NO result event at all: the tool's core premise
# (detail may live in streamed message events) -> partial block, n/a summary + detail
printf '%s' '[{"type":"system"},{"type":"stream","permission_denials":[{"tool_name":"WebFetch","tool_input":"https://x"}]}]' > "$SED_TMP/denials_no_result.json"
# result event reports count 0 but a message event carries denials: the reconciled
# count must be the larger (1) and the detail must be SURFACED, not suppressed as
# "No permission denials." (the fail-open the shadow pass caught)
printf '%s' '[{"type":"stream","permission_denials":[{"tool_name":"Task","tool_input":"q"}]},{"type":"result","is_error":false,"num_turns":9,"permission_denials_count":0}]' > "$SED_TMP/count0_with_denials.json"
# SAME two denials duplicated across a stream event AND the result event, count 2:
# `unique` must de-dup so the reconciled count is 2, not the double-counted 4
printf '%s' '[{"type":"stream","permission_denials":[{"tool_name":"Bash","tool_input":"a"},{"tool_name":"Edit","tool_input":"b"}]},{"type":"result","is_error":false,"permission_denials_count":2,"permission_denials":[{"tool_name":"Bash","tool_input":"a"},{"tool_name":"Edit","tool_input":"b"}]}]' > "$SED_TMP/dup_denials.json"

# --- AC1: run summary fields surfaced to stdout (capture once, grep the block) ---
SED_POP_OUT="$(bash "$SED" "$SED_TMP/populated.json" 2>/dev/null)"
assert_eq "#329 surface-diag: populated emits Run summary header" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "### Run summary" && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces is_error" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "is_error: false" && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces num_turns" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "num_turns: 12" && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces duration_ms" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "duration_ms: 34567" && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces total_cost_usd" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "total_cost_usd: 0.42" && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces permission_denials_count" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF "permission_denials_count: 2" && echo yes || echo no)"
# --- AC1: per-denial detail (tool_name + tool_input) when the array is present ---
assert_eq "#329 surface-diag: populated surfaces per-denial tool_name" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF '`Bash`' && echo yes || echo no)"
assert_eq "#329 surface-diag: populated surfaces second per-denial tool_name" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF '`Write`' && echo yes || echo no)"
assert_eq "#329 surface-diag: populated truncates a long tool_input" "yes" \
  "$(printf '%s' "$SED_POP_OUT" | grep -qF '(truncated)' && echo yes || echo no)"
# --- count-only degrades to count text, no per-denial detail ---
assert_eq "#329 surface-diag: count-only surfaces count" "yes" \
  "$(bash "$SED" "$SED_TMP/count_only.json" 2>/dev/null | grep -qF "permission_denials_count: 7" && echo yes || echo no)"
assert_eq "#329 surface-diag: count-only emits the no-per-denial-detail line" "yes" \
  "$(bash "$SED" "$SED_TMP/count_only.json" 2>/dev/null | grep -qF "no per-denial detail in execution file" && echo yes || echo no)"
# --- zero denials -> "No permission denials." ---
assert_eq "#329 surface-diag: zero denials emits 'No permission denials.'" "yes" \
  "$(bash "$SED" "$SED_TMP/zero.json" 2>/dev/null | grep -qF "No permission denials." && echo yes || echo no)"
# --- JSONL slurp reaches the later result line ---
assert_eq "#329 surface-diag: JSONL result line surfaced (slurp pinned)" "yes" \
  "$(bash "$SED" "$SED_TMP/jsonl.json" 2>/dev/null | grep -qF '`Edit`' && echo yes || echo no)"
# --- AC3: absent/empty/malformed -> "no diagnostics available" + exit 0 ---
assert_eq "#329 surface-diag: absent file -> no diagnostics available" "yes" \
  "$(bash "$SED" "$SED_TMP/does-not-exist.json" 2>/dev/null | grep -qF "No diagnostics available" && echo yes || echo no)"
assert_eq "#329 surface-diag: empty file -> no diagnostics available" "yes" \
  "$(bash "$SED" "$SED_TMP/empty.json" 2>/dev/null | grep -qF "No diagnostics available" && echo yes || echo no)"
assert_eq "#329 surface-diag: malformed shape -> no diagnostics available" "yes" \
  "$(bash "$SED" "$SED_TMP/garbage.json" 2>/dev/null | grep -qF "No diagnostics available" && echo yes || echo no)"
assert_eq "#329 surface-diag: missing file arg -> no diagnostics available" "yes" \
  "$(bash "$SED" "" 2>/dev/null | grep -qF "No diagnostics available" && echo yes || echo no)"
# --- AC3: always exits 0 on every arm ---
( bash "$SED" "$SED_TMP/populated.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (populated)" "0" "$?"
( bash "$SED" "$SED_TMP/garbage.json" >/dev/null 2>&1 );   assert_eq "#329 surface-diag: exits 0 (malformed)" "0" "$?"
( bash "$SED" "$SED_TMP/does-not-exist.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (absent)" "0" "$?"
( bash "$SED" "" >/dev/null 2>&1 );                        assert_eq "#329 surface-diag: exits 0 (empty arg)" "0" "$?"
# --- AC3: absent-file / malformed arms leave a breadcrumb (not a silent no-op) ---
assert_eq "#329 surface-diag: absent-file arm emits 'execution file absent' breadcrumb" "yes" \
  "$(bash "$SED" "$SED_TMP/does-not-exist.json" 2>&1 1>/dev/null | grep -qF "execution file absent or empty" && echo yes || echo no)"
assert_eq "#329 surface-diag: malformed arm emits the jq-non-zero breadcrumb" "yes" \
  "$(bash "$SED" "$SED_TMP/garbage.json" 2>&1 1>/dev/null | grep -qF "exited non-zero" && echo yes || echo no)"
# --- fail-open guard: an ABSENT count with no denial array must read 'unavailable', not zero ---
SED_NC_OUT="$(bash "$SED" "$SED_TMP/no_count.json" 2>/dev/null)"
assert_eq "#329 surface-diag: absent count + no array -> 'count unavailable' (not fail-open zero)" "yes" \
  "$(printf '%s' "$SED_NC_OUT" | grep -qF "Permission-denial count unavailable" && echo yes || echo no)"
assert_eq "#329 surface-diag: absent count does NOT print 'No permission denials.'" "no" \
  "$(printf '%s' "$SED_NC_OUT" | grep -qF "No permission denials." && echo yes || echo no)"
assert_eq "#329 surface-diag: absent count renders permission_denials_count: n/a" "yes" \
  "$(printf '%s' "$SED_NC_OUT" | grep -qF "permission_denials_count: n/a" && echo yes || echo no)"
# --- parsed-but-result-less (message-only) -> the in-jq 'no result event' no-diag arm ---
# Grep the ARM-SPECIFIC text so this stays non-vacuous vs the shell _NO_DIAG string.
assert_eq "#329 surface-diag: message-only (no result, no denials) -> in-jq 'no result event' arm" "yes" \
  "$(bash "$SED" "$SED_TMP/msg_only.json" 2>/dev/null | grep -qF "no result event in execution file" && echo yes || echo no)"
( bash "$SED" "$SED_TMP/msg_only.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (message-only)" "0" "$?"
# --- partial block: denials present, NO result event (the tool's core premise) ---
SED_DNR_OUT="$(bash "$SED" "$SED_TMP/denials_no_result.json" 2>/dev/null)"
assert_eq "#329 surface-diag: denials-without-result surfaces per-denial detail" "yes" \
  "$(printf '%s' "$SED_DNR_OUT" | grep -qF '`WebFetch`' && echo yes || echo no)"
assert_eq "#329 surface-diag: denials-without-result derives the count" "yes" \
  "$(printf '%s' "$SED_DNR_OUT" | grep -qF "permission_denials_count: 1" && echo yes || echo no)"
assert_eq "#329 surface-diag: denials-without-result renders n/a run-summary fields" "yes" \
  "$(printf '%s' "$SED_DNR_OUT" | grep -qF "is_error: n/a" && echo yes || echo no)"
( bash "$SED" "$SED_TMP/denials_no_result.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (denials-without-result)" "0" "$?"
# --- fail-open regression: result count 0 but denials gathered -> detail SHOWN, not suppressed ---
SED_C0D_OUT="$(bash "$SED" "$SED_TMP/count0_with_denials.json" 2>/dev/null)"
assert_eq "#329 surface-diag: count-0-with-denials surfaces detail (not suppressed)" "yes" \
  "$(printf '%s' "$SED_C0D_OUT" | grep -qF '`Task`' && echo yes || echo no)"
assert_eq "#329 surface-diag: count-0-with-denials does NOT print 'No permission denials.'" "no" \
  "$(printf '%s' "$SED_C0D_OUT" | grep -qF "No permission denials." && echo yes || echo no)"
assert_eq "#329 surface-diag: count-0-with-denials reconciles count to the larger (1)" "yes" \
  "$(printf '%s' "$SED_C0D_OUT" | grep -qF "permission_denials_count: 1" && echo yes || echo no)"
# --- dedup: denials duplicated across events must not inflate the reconciled count ---
SED_DUP_OUT="$(bash "$SED" "$SED_TMP/dup_denials.json" 2>/dev/null)"
assert_eq "#329 surface-diag: duplicated denials de-duped -> count 2 (not double-counted 4)" "yes" \
  "$(printf '%s' "$SED_DUP_OUT" | grep -qF "permission_denials_count: 2" && echo yes || echo no)"
assert_eq "#329 surface-diag: duplicated denials -> detail lists 2 (not 4)" "yes" \
  "$(printf '%s' "$SED_DUP_OUT" | grep -qF "2 permission denial(s) with detail:" && echo yes || echo no)"
# --- count derived from the denials-array length when the count field is absent ---
SED_CFL_OUT="$(bash "$SED" "$SED_TMP/count_from_len.json" 2>/dev/null)"
assert_eq "#329 surface-diag: count derived from denial-array length" "yes" \
  "$(printf '%s' "$SED_CFL_OUT" | grep -qF "permission_denials_count: 2" && echo yes || echo no)"
assert_eq "#329 surface-diag: derived-count surfaces per-denial detail" "yes" \
  "$(printf '%s' "$SED_CFL_OUT" | grep -qF '`Read`' && echo yes || echo no)"
# --- a bare-object permission_denials (not an array) is normalized by the `else .` arm ---
assert_eq "#329 surface-diag: single-object permission_denials normalized to detail" "yes" \
  "$(bash "$SED" "$SED_TMP/denial_obj.json" 2>/dev/null | grep -qF '`Glob`' && echo yes || echo no)"
# --- orna null->n/a branch: a result event missing duration_ms/total_cost_usd renders n/a ---
SED_MF_OUT="$(bash "$SED" "$SED_TMP/missing_field.json" 2>/dev/null)"
assert_eq "#329 surface-diag: missing duration_ms renders 'duration_ms: n/a'" "yes" \
  "$(printf '%s' "$SED_MF_OUT" | grep -qF "duration_ms: n/a" && echo yes || echo no)"
assert_eq "#329 surface-diag: missing total_cost_usd renders 'total_cost_usd: n/a'" "yes" \
  "$(printf '%s' "$SED_MF_OUT" | grep -qF "total_cost_usd: n/a" && echo yes || echo no)"
# --- AC2: appends to $GITHUB_STEP_SUMMARY when set & non-empty; stdout-only when not ---
SED_SUMMARY="$SED_TMP/step_summary.md"
: > "$SED_SUMMARY"
( GITHUB_STEP_SUMMARY="$SED_SUMMARY" bash "$SED" "$SED_TMP/populated.json" >/dev/null 2>&1 )
assert_eq "#329 surface-diag: appends the block to GITHUB_STEP_SUMMARY when set" "yes" \
  "$(grep -qF "permission_denials_count: 2" "$SED_SUMMARY" && echo yes || echo no)"
# unset -> no file written; stdout still carries the block (the summary var is empty)
SED_STDOUT="$(GITHUB_STEP_SUMMARY="" bash "$SED" "$SED_TMP/populated.json" 2>/dev/null)"
assert_eq "#329 surface-diag: stdout still carries the block when GITHUB_STEP_SUMMARY unset" "yes" \
  "$(printf '%s' "$SED_STDOUT" | grep -qF "### Run summary" && echo yes || echo no)"
# GITHUB_STEP_SUMMARY pointing at an unwritable path: the append fails with a breadcrumb
# but stdout still carries the block and the helper still exits 0 (best-effort).
SED_BADSUMMARY_OUT="$(GITHUB_STEP_SUMMARY="$SED_TMP/nonexistent-dir/summary.md" bash "$SED" "$SED_TMP/populated.json" 2>/dev/null)"
assert_eq "#329 surface-diag: unwritable GITHUB_STEP_SUMMARY -> stdout still carries the block" "yes" \
  "$(printf '%s' "$SED_BADSUMMARY_OUT" | grep -qF "### Run summary" && echo yes || echo no)"
assert_eq "#329 surface-diag: unwritable GITHUB_STEP_SUMMARY leaves a breadcrumb" "yes" \
  "$(GITHUB_STEP_SUMMARY="$SED_TMP/nonexistent-dir/summary.md" bash "$SED" "$SED_TMP/populated.json" 2>&1 1>/dev/null | grep -qF "could not append to GITHUB_STEP_SUMMARY" && echo yes || echo no)"
( GITHUB_STEP_SUMMARY="$SED_TMP/nonexistent-dir/summary.md" bash "$SED" "$SED_TMP/populated.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (unwritable GITHUB_STEP_SUMMARY)" "0" "$?"
# DEVFLOW_JQ override honored (best-effort seam, same as parse-engine-error.sh).
# NON-VACUOUS: point the override at a non-runnable binary and observe the behavioral
# difference — the jq call exits non-zero, so the helper degrades to "no diagnostics
# available" (+ the jq-non-zero breadcrumb) and still exits 0. A helper that ignored
# DEVFLOW_JQ and called bare `jq` would instead surface the run summary, failing this.
SED_BADJQ_OUT="$(DEVFLOW_JQ=/nonexistent/definitely-not-jq bash "$SED" "$SED_TMP/populated.json" 2>/dev/null)"
assert_eq "#329 surface-diag: broken DEVFLOW_JQ override -> no diagnostics available (override honored)" "yes" \
  "$(printf '%s' "$SED_BADJQ_OUT" | grep -qF "No diagnostics available" && echo yes || echo no)"
assert_eq "#329 surface-diag: broken DEVFLOW_JQ override does NOT surface a run summary (non-vacuous)" "no" \
  "$(printf '%s' "$SED_BADJQ_OUT" | grep -qF "### Run summary" && echo yes || echo no)"
( DEVFLOW_JQ=/nonexistent/definitely-not-jq bash "$SED" "$SED_TMP/populated.json" >/dev/null 2>&1 ); assert_eq "#329 surface-diag: exits 0 (broken DEVFLOW_JQ)" "0" "$?"
# --- AC8: the execution_diagnostics_enabled key exists in schema + example (default true) ---
SED_SCHEMA="$LIB/../.prflow/config.schema.json"
SED_EXAMPLE="$LIB/../.prflow/config.example.json"
SED_PROP='.properties.prflow.properties.execution_diagnostics_enabled'
assert_eq "#329 execution_diagnostics_enabled: schema type is boolean" "boolean" \
  "$(jq -r "$SED_PROP.type" "$SED_SCHEMA")"
assert_eq "#329 execution_diagnostics_enabled: schema default is true" "true" \
  "$(jq -r "$SED_PROP.default" "$SED_SCHEMA")"
assert_eq "#329 execution_diagnostics_enabled: schema has a non-empty description" "yes" \
  "$(jq -e "$SED_PROP.description | type == \"string\" and (length > 0)" "$SED_SCHEMA" >/dev/null && echo yes || echo no)"
assert_eq "#329 execution_diagnostics_enabled: example value matches schema default" \
  "$(jq -r "$SED_PROP.default" "$SED_SCHEMA")" \
  "$(jq -r '.prflow.execution_diagnostics_enabled' "$SED_EXAMPLE")"
# resolver read: configured false read back verbatim, absent/missing → default true
SED_CFG="$(mktemp)"
printf '%s' '{"prflow":{"execution_diagnostics_enabled":false}}' > "$SED_CFG"
assert_eq "#329 execution_diagnostics_enabled: configured false read back" "false" \
  "$("$CG" .prflow.execution_diagnostics_enabled true "$SED_CFG")"
printf '%s' '{}' > "$SED_CFG"
assert_eq "#329 execution_diagnostics_enabled: unset key → resolver default true" "true" \
  "$("$CG" .prflow.execution_diagnostics_enabled true "$SED_CFG")"
assert_eq "#329 execution_diagnostics_enabled: missing config file → resolver default true" "true" \
  "$("$CG" .prflow.execution_diagnostics_enabled true /no/such/config.json)"
rm -f "$SED_CFG"
rm -rf "$SED_TMP"

# ────────────────────────────────────────────────────────────────────────────
echo "workflow wiring: Surface execution diagnostics step (#331)"
# ────────────────────────────────────────────────────────────────────────────
# Issue #331 wires scripts/surface-execution-diagnostics.sh (shipped in #329)
# into the three claude-code-action workflows. Each must carry a post-`claude`
# "Surface execution diagnostics" step that: (AC1) runs under always(), reads
# ${{ steps.claude.outputs.execution_file }}, and resolves the helper
# vendored-path-first with a repo-path fallback; (AC2) gates on
# .prflow.execution_diagnostics_enabled (default true) via config-get.sh
# (vendored-first) and skips on the literal "false"; (AC3) adds no permissions
# grant / minted-token scope and uploads no artifact (a pure run-only step).
# Assertions scope to the step block — awk-sliced from its `- name:` to the next
# `- name:` — so `if: always()` is non-vacuous: it must be THIS step's `if:`,
# not a sibling's.
WF_DIR="$LIB/../.github/workflows"
# Slice a named step block out of a workflow file: from the `- name: <step>`
# line to (but not including) the next top-level (6-space-indented) `- name:`.
extract_step() {  # $1=workflow file  $2=exact step name
  awk -v want="- name: $2" '
    index($0, want) { grab=1; print; next }
    grab && /^      - name: / { exit }
    grab { print }
  ' "$1"
}
# Assert needle A's first occurrence precedes needle B's within a block — used to pin
# vendored-path-FIRST *ordering* (a plain presence grep passes even if the two candidates
# were flipped to repo-first, which the "vendored-first" label would then overstate).
block_order_ok() {  # $1=block  $2=earlier-needle  $3=later-needle → echoes yes|no
  local a b
  a=$(printf '%s\n' "$1" | grep -nF "$2" | head -1 | cut -d: -f1)
  b=$(printf '%s\n' "$1" | grep -nF "$3" | head -1 | cut -d: -f1)
  if [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; then echo yes; else echo no; fi
}
for WF in devflow-runner.yml devflow-implement.yml devflow.yml; do
  WF_PATH="$WF_DIR/$WF"
  BLK="$(extract_step "$WF_PATH" "Surface execution diagnostics")"
  assert_eq "#331 $WF: has a 'Surface execution diagnostics' step" "yes" \
    "$([ -n "$BLK" ] && echo yes || echo no)"
  # AC1: runs under always()
  assert_eq "#331 $WF: diagnostics step runs under always()" "yes" \
    "$(printf '%s' "$BLK" | grep -qE 'if:[[:space:]]*(\$\{\{[[:space:]]*)?always\(\)' && echo yes || echo no)"
  # AC1: reads the claude step's execution_file output
  assert_eq "#331 $WF: reads steps.claude.outputs.execution_file" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'steps.claude.outputs.execution_file' && echo yes || echo no)"
  # AC1: resolves the helper vendored-path-first with a repo-path fallback
  assert_eq "#331 $WF: resolves helper vendored-path-first" "yes" \
    "$(printf '%s' "$BLK" | grep -qF '.prflow/vendor/prflow/scripts/surface-execution-diagnostics.sh' && echo yes || echo no)"
  assert_eq "#331 $WF: helper repo-path fallback present" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'SED=scripts/surface-execution-diagnostics.sh' && echo yes || echo no)"
  # AC1 (order, not just presence): the vendored helper path is tried BEFORE the repo fallback
  assert_eq "#331 $WF: helper vendored path precedes repo fallback" "yes" \
    "$(block_order_ok "$BLK" 'SED=.prflow/vendor/prflow/scripts/surface-execution-diagnostics.sh' 'SED=scripts/surface-execution-diagnostics.sh')"
  # AC2: gates on the config key via config-get.sh, vendored-first with fallback
  assert_eq "#331 $WF: reads .prflow.execution_diagnostics_enabled" "yes" \
    "$(printf '%s' "$BLK" | grep -qF '.prflow.execution_diagnostics_enabled' && echo yes || echo no)"
  assert_eq "#331 $WF: gate uses config-get.sh vendored-first" "yes" \
    "$(printf '%s' "$BLK" | grep -qF '.prflow/vendor/prflow/scripts/config-get.sh' && echo yes || echo no)"
  assert_eq "#331 $WF: config-get.sh repo-path fallback present" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'CG=scripts/config-get.sh' && echo yes || echo no)"
  # AC2 (order, not just presence): the vendored config-get path is tried BEFORE the repo fallback
  assert_eq "#331 $WF: config-get.sh vendored path precedes repo fallback" "yes" \
    "$(block_order_ok "$BLK" 'CG=.prflow/vendor/prflow/scripts/config-get.sh' 'CG=scripts/config-get.sh')"
  # AC2: disables only on the literal "false" — anchor on the FULL gate shape, not the bare
  # `= "false" ]` substring (which is ALSO contained in `!= "false" ]`, so a gate inverted to
  # `!=` — skip-when-ENABLED, the exact AC2 violation — would pass a bare-substring grep green).
  assert_eq "#331 $WF: skips only on the literal \"false\" (full gate shape, inversion-proof)" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'if [ "$ENABLED" = "false" ]; then' && echo yes || echo no)"
  # AC2/AC3: the config-get read is `|| true`-guarded so its hard-fail exit (malformed config /
  # missing python3) can't abort the step under GitHub Actions' default `-e` run shell — an
  # unguarded assignment would fail the job, breaking the read-only "never changes the job's
  # pass/fail" contract.
  assert_eq "#331 $WF: config-get read is -e-guarded (|| true)" "yes" \
    "$(printf '%s' "$BLK" | grep -qF '.prflow.execution_diagnostics_enabled true || true)' && echo yes || echo no)"
  # Completeness anchor: the slice reaches the step's run body (the helper invocation).
  # The AC3 assertions below are grep-ABSENT checks that pass vacuously on an empty or
  # short-sliced block, so anchor them on a proven-complete block — a future extract_step
  # mis-scope that truncated the slice would fail HERE (RED) rather than silently making
  # the AC3 guarantees inert while still reading green.
  assert_eq "#331 $WF: slice reaches the run body (helper invocation present)" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'bash "$SED" "${EXECUTION_FILE:-}"' && echo yes || echo no)"
  # AC3: the helper invocation is `|| echo`-guarded so a partial-copy/truncated vendored
  # helper that exits non-zero can't abort the always() step under GitHub's default -e
  # shell (same read-only "never changes the job's pass/fail" contract as the config-get
  # guard). Pins the guard so a regression dropping it goes RED.
  assert_eq "#331 $WF: helper invocation is -e-guarded (|| echo)" "yes" \
    "$(printf '%s' "$BLK" | grep -qF 'bash "$SED" "${EXECUTION_FILE:-}" || echo' && echo yes || echo no)"
  # AC3: the step is a pure run-only step — no action invocation, so it can neither
  # mint a token (create-github-app-token) nor upload an artifact (upload-artifact).
  assert_eq "#331 $WF: diagnostics step is run-only (no uses:)" "no" \
    "$(printf '%s' "$BLK" | grep -qE '^[[:space:]]*uses:' && echo yes || echo no)"
  # AC3: the step declares no per-step permissions: block
  assert_eq "#331 $WF: diagnostics step declares no permissions: block" "no" \
    "$(printf '%s' "$BLK" | grep -qE '^[[:space:]]*permissions:' && echo yes || echo no)"
  # AC3 (explicit): no artifact upload even if a future edit added a uses:
  assert_eq "#331 $WF: diagnostics step uploads no artifact" "no" \
    "$(printf '%s' "$BLK" | grep -qiF 'upload-artifact' && echo yes || echo no)"
done
unset -f extract_step

# ────────────────────────────────────────────────────────────────────────────
echo "execution transcript artifact: config key + scrub/gate hardening (#409)"
# ────────────────────────────────────────────────────────────────────────────
# Issue #409 (deferred findings from the PR #407 review) hardens the opt-in
# execution-transcript artifact path in devflow-runner.yml. The key gates a
# credential-scrubbed upload of the engine's execution transcript; its polarity
# is default-FALSE and fail-CLOSED (the OPPOSITE of execution_diagnostics_enabled),
# so it must be pinned with the same rigor as its sibling.
TR_SCHEMA="$LIB/../.prflow/config.schema.json"
TR_EXAMPLE="$LIB/../.prflow/config.example.json"
TR_RUNNER="$LIB/../.github/workflows/devflow-runner.yml"
TR_PROP='.properties.prflow.properties.execution_transcript_artifact_enabled'
# --- item 1: schema family mirrors execution_diagnostics_enabled ---
assert_eq "#409 transcript key: schema type is boolean" "boolean" \
  "$(jq -r "$TR_PROP.type" "$TR_SCHEMA")"
assert_eq "#409 transcript key: schema default is false (fail-closed polarity)" "false" \
  "$(jq -r "$TR_PROP.default" "$TR_SCHEMA")"
assert_eq "#409 transcript key: schema has a non-empty description" "yes" \
  "$(jq -e "$TR_PROP.description | type == \"string\" and (length > 0)" "$TR_SCHEMA" >/dev/null && echo yes || echo no)"
assert_eq "#409 transcript key: example value matches schema default" \
  "$(jq -r "$TR_PROP.default" "$TR_SCHEMA")" \
  "$(jq -r '.prflow.execution_transcript_artifact_enabled' "$TR_EXAMPLE")"
# resolver read: configured true read back verbatim; absent/missing → default false
TR_CFG="$(mktemp)"
printf '%s' '{"prflow":{"execution_transcript_artifact_enabled":true}}' > "$TR_CFG"
assert_eq "#409 transcript key: configured true read back" "true" \
  "$("$CG" .prflow.execution_transcript_artifact_enabled false "$TR_CFG")"
printf '%s' '{}' > "$TR_CFG"
assert_eq "#409 transcript key: unset key → resolver default false" "false" \
  "$("$CG" .prflow.execution_transcript_artifact_enabled false "$TR_CFG")"
rm -f "$TR_CFG"
# item 1: the scrub step gates on outputs.transcript == 'true'; the upload step
# gates on the scrub step producing a path (so an empty/failed scrub uploads nothing).
assert_eq "#409 transcript: scrub step gates on diagnostics.outputs.transcript == 'true'" "1" \
  "$(grep -cF "steps.diagnostics.outputs.transcript == 'true'" "$TR_RUNNER" || true)"
assert_eq "#409 transcript: upload step gates on scrub_transcript.outputs.path != ''" "1" \
  "$(grep -cF "steps.scrub_transcript.outputs.path != ''" "$TR_RUNNER" || true)"
# --- item 5: coupled pin — schema retention phrase ↔ upload retention-days agree ---
# The schema description advertises an "N-day run artifact"; the upload step sets
# retention-days: N. If one changes without the other the two derived numbers
# disagree and this assertion goes RED.
# DEFERRED (#409 review, Suggestion, below the `important` fix threshold): both sides
# take `head -1` of their match, so a SECOND incidental `N-day` phrase in the schema
# description or a second `retention-days:` in the workflow could shift the compared
# pair silently. Low risk today (each token occurs exactly once). Revisit only if a
# second occurrence of either token is introduced — then anchor the match to the
# specific property/step instead of first-match.
TR_RET_SCHEMA="$(jq -r "$TR_PROP.description" "$TR_SCHEMA" | grep -oE '[0-9]+-day' | grep -oE '^[0-9]+' | head -1)"
TR_RET_UPLOAD="$(grep -oE 'retention-days: [0-9]+' "$TR_RUNNER" | grep -oE '[0-9]+' | head -1)"
assert_eq "#409 transcript: schema retention phrase present (N-day)" "yes" \
  "$([ -n "$TR_RET_SCHEMA" ] && echo yes || echo no)"
assert_eq "#409 transcript: schema retention phrase agrees with upload retention-days" \
  "$TR_RET_UPLOAD" "$TR_RET_SCHEMA"
# --- items 2/3/4 behavioral: drive the REAL extracted scrub step end-to-end ---
# Extract the scrub_transcript step's run body from the workflow and exercise it
# against a fixture transcript carrying every scrubbed credential shape. Driving
# the real step (not a hand-copied sed) keeps the test honest as the step evolves.
if command -v python3 >/dev/null 2>&1 && python3 -c 'import yaml' >/dev/null 2>&1; then
  SCRUB_STEP="$(mktemp)"
  python3 - "$TR_RUNNER" >"$SCRUB_STEP" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
for job in doc["jobs"].values():
    for s in job.get("steps", []):
        if s.get("id") == "scrub_transcript" and "run" in s:
            sys.stdout.write("#!/usr/bin/env bash\n" + s["run"])
            raise SystemExit
raise SystemExit("scrub_transcript step not found")
PY
  SCRUB_DIR="$(mktemp -d)"
  SCRUB_EXEC="$SCRUB_DIR/exec.json"
  # A fixture carrying: gh token, PAT, Anthropic key, Bearer header, and the
  # base64 basic-auth header the checkout persists (item 4). The basic-auth line
  # uses the REAL UPPERCASE `AUTHORIZATION:` form actions/checkout's git-auth-helper
  # persists (case-insensitive header match, #409 review) — a mixed-case fixture
  # would pass vacuously against a case-sensitive `Authorization` literal and give
  # false confidence against exactly the header item 4 exists to redact.
  {
    printf '%s\n' 'tok=ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    printf '%s\n' 'pat=github_pat_ABCDEFGHIJKLMNOPQRSTUV0123456789'
    printf '%s\n' 'key=sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    printf '%s\n' 'Authorization: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'
    printf '%s\n' 'AUTHORIZATION: basic eHgtYWNjZXNzLXRva2VuOmdoc19BQkNERUZHSElKS0xNTk9Q'
  } > "$SCRUB_EXEC"
  SCRUB_GH_OUT="$SCRUB_DIR/gh_output"
  : > "$SCRUB_GH_OUT"
  # TRUSTED-SOURCE ladder (issue #1064 W3). The step now resolves the scrub pair ONLY
  # from a trusted source — rank 1 is the base-ref copy baseprovision materializes into
  # RUNNER_TEMP, rank 2 the vendored copy gated on vendor_source==fetch — and never from
  # the PR-head workspace. Stand in for rank 1 with a dir holding both real helpers, so
  # these behavioral arms keep driving the actual scrub rather than the fail-closed arm.
  SCRUB_TRUSTED="$SCRUB_DIR/trusted"
  mkdir -p "$SCRUB_TRUSTED"
  cp "$LIB/../scripts/scrub-transcript.sh" "$LIB/../scripts/scrub-credentials.sh" "$SCRUB_TRUSTED/"
  EXECUTION_FILE="$SCRUB_EXEC" RUNNER_TEMP="$SCRUB_DIR" GITHUB_OUTPUT="$SCRUB_GH_OUT" \
    SCRUB_HELPER_DIR="$SCRUB_TRUSTED" \
    bash "$SCRUB_STEP" > "$SCRUB_DIR/log" 2>&1 || true
  SCRUB_OUT="$SCRUB_DIR/claude-execution-scrubbed.json"
  # item 4 + existing shapes: every credential redacted, no raw secret survives.
  assert_eq "#409 scrub: ghs_ token redacted" "yes" \
    "$(grep -qF '[REDACTED-GH-TOKEN]' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: github_pat_ redacted" "yes" \
    "$(grep -qF '[REDACTED-GH-PAT]' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: sk-ant- key redacted" "yes" \
    "$(grep -qF '[REDACTED-ANTHROPIC-KEY]' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: Bearer header redacted" "yes" \
    "$(grep -qF 'Bearer [REDACTED]' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: base64 basic-auth header redacted (item 4)" "yes" \
    "$(grep -qF 'basic [REDACTED]' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: no raw base64 basic-auth token survives (item 4)" "no" \
    "$(grep -qF 'eHgtYWNjZXNzLXRva2Vu' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  # item 2: caveat header prepended into the artifact + best-effort warning emitted.
  assert_eq "#409 scrub: caveat header prepended into the artifact (item 2)" "yes" \
    "$(grep -qF 'DEVFLOW SCRUB CAVEAT' "$SCRUB_OUT" 2>/dev/null && echo yes || echo no)"
  # The scrub now runs through the shared scripts/scrub-transcript.sh helper (issue
  # #1064 D4), which names the redacted SHAPES explicitly rather than "four credential
  # shapes"; pin the stable warning prefix so the incomplete-blocklist disclosure stays
  # asserted without re-pinning the exact shape count.
  assert_eq "#409 scrub: incomplete-blocklist warning emitted (item 2)" "yes" \
    "$(grep -qF 'best-effort blocklist covering' "$SCRUB_DIR/log" 2>/dev/null && echo yes || echo no)"
  # item 3: non-empty output advertises a path=.
  assert_eq "#409 scrub: non-empty scrub advertises path= (item 3)" "yes" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT" 2>/dev/null && echo yes || echo no)"
  # item 3: an empty execution file scrubs to empty → no path advertised, own breadcrumb.
  SCRUB_EMPTY_EXEC="$SCRUB_DIR/empty.json"
  : > "$SCRUB_EMPTY_EXEC"
  SCRUB_GH_OUT2="$SCRUB_DIR/gh_output2"
  : > "$SCRUB_GH_OUT2"
  EXECUTION_FILE="$SCRUB_EMPTY_EXEC" RUNNER_TEMP="$SCRUB_DIR" GITHUB_OUTPUT="$SCRUB_GH_OUT2" \
    SCRUB_HELPER_DIR="$SCRUB_TRUSTED" \
    bash "$SCRUB_STEP" > "$SCRUB_DIR/log2" 2>&1 || true
  assert_eq "#409 scrub: empty output advertises NO path= (item 3)" "no" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT2" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: empty output leaves its own breadcrumb (item 3)" "yes" \
    "$(grep -qF 'scrubbed transcript is empty' "$SCRUB_DIR/log2" 2>/dev/null && echo yes || echo no)"
  # item 2 fail-closed arm: if the caveat-header write fails, NO path= is advertised
  # and a distinct fail-closed breadcrumb is emitted — a half-written/unscrubbed file
  # must never be uploaded (#409 review: the security fail-closed arm was untested).
  # Drive it by PATH-shadowing `mv` (used only in the caveat prepend) with a failing shim.
  # DEFERRED (#409 review, Suggestion, below the `important` fix threshold): this only
  # shadows `mv`. The caveat write is a single `printf … && cat … && mv …` &&-chain, so
  # a `printf`/`cat` failure takes the IDENTICAL else-branch and the same fail-closed
  # path — the arm is proven closed via `mv`; shadowing the earlier chain members would
  # observe the same branch. Revisit only if the chain gains a DISTINCT per-member
  # branch (then each member needs its own RED observation).
  MV_BIN="$(mktemp -d)"
  printf '#!/usr/bin/env bash\nexit 1\n' > "$MV_BIN/mv"
  chmod +x "$MV_BIN/mv"
  SCRUB_GH_OUT3="$SCRUB_DIR/gh_output3"
  : > "$SCRUB_GH_OUT3"
  ( PATH="$MV_BIN:$PATH" EXECUTION_FILE="$SCRUB_EXEC" RUNNER_TEMP="$SCRUB_DIR" GITHUB_OUTPUT="$SCRUB_GH_OUT3" \
      SCRUB_HELPER_DIR="$SCRUB_TRUSTED" \
      bash "$SCRUB_STEP" ) > "$SCRUB_DIR/log3" 2>&1 || true
  assert_eq "#409 scrub: caveat-write failure advertises NO path= (fail-closed, item 2)" "no" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT3" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: caveat-write failure emits its fail-closed breadcrumb (item 2)" "yes" \
    "$(grep -qF 'caveat-header write failed' "$SCRUB_DIR/log3" 2>/dev/null && echo yes || echo no)"
  rm -rf "$MV_BIN"
  # ── #1064 W3: the TRUSTED-SOURCE ladder. This job checks out the PR HEAD, so a
  # credential scrub read from the workspace is a scrub the PR controls. With NEITHER
  # rank satisfied (no baseprovision dir, vendor_source != fetch) the step must upload
  # NOTHING and warn naming the rule — even though a perfectly good PR-head copy exists
  # at scripts/scrub-transcript.sh, which is exactly the copy that must not be consulted.
  # The positive control is every arm above (rank 1 supplied), so this assertion can fail.
  SCRUB_GH_OUT_W3="$SCRUB_DIR/gh_output_w3"
  : > "$SCRUB_GH_OUT_W3"
  # Run from the REPO ROOT deliberately, where the PR-head copies (scripts/scrub-*.sh,
  # and a committed .prflow/vendor/prflow/ if present) really do exist — so this asserts
  # the ladder REFUSES a reachable workspace copy. Running it from a scratch cwd would
  # pass vacuously against the pre-#1064-W3 code, which fell back to `scripts/`.
  EXECUTION_FILE="$SCRUB_EXEC" RUNNER_TEMP="$SCRUB_DIR" \
    GITHUB_OUTPUT="$SCRUB_GH_OUT_W3" SCRUB_HELPER_DIR='' VENDOR_SOURCE=committed \
    bash "$SCRUB_STEP" > "$SCRUB_DIR/logw3" 2>&1 || true
  assert_eq "#1064 W3: no trusted scrub source → advertises NO path= (fail-closed)" "no" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT_W3" 2>/dev/null && echo yes || echo no)"
  assert_eq "#1064 W3: no trusted scrub source → warns naming the trusted-source rule" "yes" \
    "$(grep -qF 'not found at any TRUSTED source' "$SCRUB_DIR/logw3" 2>/dev/null && echo yes || echo no)"
  assert_eq "#1064 W3: the fail-closed warning states the PR-head copy is not consulted" "yes" \
    "$(grep -qF 'PR-head checkout' "$SCRUB_DIR/logw3" 2>/dev/null && echo yes || echo no)"
  # vendor_source=committed must NOT qualify as rank 2 (only a fresh `fetch` clone does).
  assert_eq "#1064 W3: vendor_source=committed does not satisfy rank 2" "no" \
    "$(grep -qF 'runtime-fetched vendored copy' "$SCRUB_DIR/logw3" 2>/dev/null && echo yes || echo no)"
  # absent-execution-file arm: the if: gate guarantees a non-empty output name but not
  # that the file exists, so the `[ ! -f "$EXECUTION_FILE" ]` early-exit is reachable —
  # it emits a notice and no path= (#409 review, Suggestion).
  SCRUB_GH_OUT4="$SCRUB_DIR/gh_output4"
  : > "$SCRUB_GH_OUT4"
  EXECUTION_FILE="$SCRUB_DIR/does-not-exist.json" RUNNER_TEMP="$SCRUB_DIR" GITHUB_OUTPUT="$SCRUB_GH_OUT4" \
    SCRUB_HELPER_DIR="$SCRUB_TRUSTED" \
    bash "$SCRUB_STEP" > "$SCRUB_DIR/log4" 2>&1 || true
  assert_eq "#409 scrub: absent execution file advertises NO path=" "no" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT4" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: absent execution file leaves its own breadcrumb" "yes" \
    "$(grep -qF 'execution file absent' "$SCRUB_DIR/log4" 2>/dev/null && echo yes || echo no)"
  # outer sed-failure arm: if the sed scrub itself fails, NO path= is advertised and
  # the unscrubbed file is not uploaded (#409 review, last uncovered scrub branch).
  # Drive it by PATH-shadowing `sed` with a failing shim.
  SED_BIN="$(mktemp -d)"
  printf '#!/usr/bin/env bash\nexit 1\n' > "$SED_BIN/sed"
  chmod +x "$SED_BIN/sed"
  SCRUB_GH_OUT5="$SCRUB_DIR/gh_output5"
  : > "$SCRUB_GH_OUT5"
  ( PATH="$SED_BIN:$PATH" EXECUTION_FILE="$SCRUB_EXEC" RUNNER_TEMP="$SCRUB_DIR" GITHUB_OUTPUT="$SCRUB_GH_OUT5" \
      SCRUB_HELPER_DIR="$SCRUB_TRUSTED" \
      bash "$SCRUB_STEP" ) > "$SCRUB_DIR/log5" 2>&1 || true
  assert_eq "#409 scrub: sed-failure advertises NO path= (fail-closed)" "no" \
    "$(grep -qF 'path=' "$SCRUB_GH_OUT5" 2>/dev/null && echo yes || echo no)"
  assert_eq "#409 scrub: sed-failure emits its fail-closed breadcrumb" "yes" \
    "$(grep -qF 'transcript scrub failed' "$SCRUB_DIR/log5" 2>/dev/null && echo yes || echo no)"
  rm -rf "$SED_BIN"
  rm -f "$SCRUB_STEP"
  rm -rf "$SCRUB_DIR"
else
  echo "  SKIP  #409 scrub behavioral tests (python3+pyyaml unavailable)"
fi

# ────────────────────────────────────────────────────────────────────────────
echo "resolve-implement-trigger.sh"
# ────────────────────────────────────────────────────────────────────────────
# The implement trigger runs the action in AGENT mode (explicit prompt), which
# executes for ANY actor — so this resolver is the cost/authorization gate AND
# the issue-number resolver. Tests stub `gh` for the collaborator-permission
# call; the allowed-bot path never reaches `gh`.
RIT="$LIB/../scripts/resolve-implement-trigger.sh"

# Inline gh stub: returns whatever STUB_PERM says for a collaborator-permission
# query (the script passes --jq '.permission'; like gh-stub.sh we ignore --jq
# and emit the already-extracted value), empty otherwise.
RIT_STUB_DIR="$(mktemp -d)"
cat > "$RIT_STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
# STUB_ERR (to stderr) + STUB_RC let a test simulate gh failures (transient or
# 404); default is a clean success echoing STUB_PERM. STUB_RECOVER (with a
# STUB_COUNTER file) fails the FIRST permission call with a 500 and succeeds on
# the second, so a test can prove the resolver's retry loop actually re-attempts.
case "$*" in
  *"collaborators/"*"/permission"*)
    if [ -n "${STUB_RECOVER:-}" ]; then
      n=0; [ -f "${STUB_COUNTER:-/dev/null}" ] && n="$(cat "${STUB_COUNTER:-/dev/null}")"
      n=$((n + 1)); echo "$n" > "${STUB_COUNTER:-/dev/null}"
      if [ "$n" -lt 2 ]; then echo "gh: Internal Server Error (HTTP 500)" >&2; exit 1; fi
      echo "${STUB_PERM:-none}"; exit 0
    fi
    [ -n "${STUB_ERR:-}" ] && echo "$STUB_ERR" >&2
    [ "${STUB_RC:-0}" != 0 ] && exit "${STUB_RC}"
    echo "${STUB_PERM:-none}" ;;
  *) echo "" ;;
esac
STUB
chmod +x "$RIT_STUB_DIR/gh"

# 1. Allowed bot + explicit number in comment → run on that number. `foo[bot]`
#    actor must match the bare `foo` in allowed_bots. No gh call on this path.
OUT="$(ACTOR='foo[bot]' ALLOWED_BOTS='foo,bar' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement #42' CONTEXT_NUMBER='7' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: allowed bot, explicit number → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: allowed bot, explicit number → number" \
  "number=42" "$(echo "$OUT" | grep '^number=')"

# 2. Write collaborator + explicit number in comment → run on that number.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_PERM='write' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: write collaborator, explicit number → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: explicit number beats context" \
  "number=7" "$(echo "$OUT" | grep '^number=')"

# 2b. Dual-namespace acceptance at the implement extractor. Every other fixture
# in this block feeds the transitional `/devflow:implement` alias, so these pin
# the CANONICAL arm — the one the workflow's own re-dispatch body and agent-mode
# prompt now emit. Without them the alternation could regress to alias-only and
# every fixture here would still pass, while the workflow's synthesised prompt
# resolved no number at all.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/prflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_PERM='write' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: canonical /prflow:implement → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: canonical /prflow:implement resolves the explicit number" \
  "number=7" "$(echo "$OUT" | grep '^number=')"
# The workflow's own re-dispatch body shape (`/prflow:implement <n>` on its own
# line, # -less) is what the resume arm posts — resolve it end-to-end.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/prflow:implement #42' CONTEXT_NUMBER='7' \
  STUB_PERM='write' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: canonical namespace with a #-prefixed number resolves" \
  "number=42" "$(echo "$OUT" | grep '^number=')"
# Negative control: the accepted namespace alternation is exactly two, not a
# wildcard. Under the issue #1032 tightening an unrelated `/xflow:` prefix is not
# a recognized standalone implement command, so the resolver now DECLINES it
# (should_run=false, empty number) rather than — as the pre-#1032 grep resolver
# did — falling through to the context number and firing a full run on the
# attached issue. That context-fallthrough on a foreign/quoted token WAS the
# over-fire this issue fixes; declining it is the corrected behavior.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/xflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_PERM='write' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: an unrelated /xflow: namespace is not a standalone command → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: an unrelated /xflow: namespace → empty number (no context fallthrough)" \
  "number=" "$(echo "$OUT" | grep '^number=')"

# 3. Non-collaborator (gh → 'none') → blocked, no number.
OUT="$(ACTOR='stranger' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_PERM='none' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: non-collaborator → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: non-collaborator → empty number" \
  "number=" "$(echo "$OUT" | grep '^number=')"

# 4. Authorized but NO number anywhere → blocked (can't implement nothing).
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement please' CONTEXT_NUMBER='' \
  STUB_PERM='admin' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: no resolvable number → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"

# 5. Authorized, no explicit number but a context issue → fall back to context.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement' CONTEXT_NUMBER='5' \
  STUB_PERM='maintain' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: fallback to context number" \
  "number=5" "$(echo "$OUT" | grep '^number=')"

# 6. Transient collaborator-API failure (non-404) → fails CLOSED with a
#    transient-specific diagnostic, NOT mislabelled as "not a collaborator".
#    RESOLVE_RETRY_DELAY=0 keeps the retry instant.
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_RC='1' STUB_ERR='gh: Internal Server Error (HTTP 500)' \
  RESOLVE_RETRY_DELAY='0' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>"$RIT_STUB_DIR/err")"
assert_eq "rit: transient API error → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: transient API error → honest diagnostic (not mislabelled)" \
  "1" "$(grep -c 'collaborator-permission lookup failed after retry' "$RIT_STUB_DIR/err")"
assert_eq "rit: transient API error → surfaces the real gh error" \
  "1" "$(grep -c 'HTTP 500' "$RIT_STUB_DIR/err")"

# 7. Genuine 404 (not a collaborator) → fails closed as before, no retry stall.
OUT="$(ACTOR='stranger' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_RC='1' STUB_ERR='gh: Not Found (HTTP 404)' \
  RESOLVE_RETRY_DELAY='0' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>"$RIT_STUB_DIR/err")"
assert_eq "rit: 404 non-collaborator → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: 404 treated as non-collaborator, not transient" \
  "1" "$(grep -c 'is not an allowed bot or write/admin/maintain collaborator' "$RIT_STUB_DIR/err")"

# 8. Transient failure on attempt 1, success on attempt 2 → retry RECOVERS the
#    collaborator. A regression collapsing the loop to a single call would fail
#    closed and break this, which case 6 (double-failure) cannot catch.
RIT_COUNTER="$RIT_STUB_DIR/recover_count"; : > "$RIT_COUNTER"
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 7' CONTEXT_NUMBER='99' \
  STUB_RECOVER='1' STUB_COUNTER="$RIT_COUNTER" STUB_PERM='write' \
  RESOLVE_RETRY_DELAY='0' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: retry recovers collaborator on attempt 2 → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: retry recovers → number" \
  "number=7" "$(echo "$OUT" | grep '^number=')"

# 9. Explicit number with leading '#' and mixed-case command → extracted (pins
#    the regex's `#?` arm and grep -i case-insensitivity).
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' \
  TRIGGER_TEXT='/DevFlow:Implement #13' CONTEXT_NUMBER='99' \
  STUB_PERM='admin' PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: '#'-prefixed mixed-case command → number=13" \
  "number=13" "$(echo "$OUT" | grep '^number=')"

# 10. allowed_bots with surrounding whitespace + bot is NOT the first entry →
#     matched after parameter-expansion trim (pins the trim + loop continuation).
OUT="$(ACTOR='bar[bot]' ALLOWED_BOTS=' foo , bar ' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 8' CONTEXT_NUMBER='8' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: whitespace-trimmed, non-first allowed bot → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"

# 11. Self-trigger guard: a Devflow-authored workpad comment (leads with the
#     marker, quotes a `/devflow:implement run started` note) must NOT fire a
#     run — even for an allowed bot, since the guard runs BEFORE authorization
#     and number resolution. Covers the issue #25 regression directly.
RIT_WORKPAD_TEXT=$'<!-- devflow:workpad -->\n# DevFlow Workpad — Issue #25\n\n## Decisions / Notes\n### Setup\n- 04:57:07 — /devflow:implement run started'
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT="$RIT_WORKPAD_TEXT" CONTEXT_NUMBER='25' \
  SELF_COMMENT_MARKER='<!-- devflow:workpad -->' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: workpad-marker body → should_run=false (self-trigger guard)" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: workpad-marker body → empty number" \
  "number=" "$(echo "$OUT" | grep '^number=')"

# 12. The guard's marker defaults to workpad.py's fallback when
#     SELF_COMMENT_MARKER is unset, so a workpad body is guarded regardless.
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT="$RIT_WORKPAD_TEXT" CONTEXT_NUMBER='25' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: default marker guards workpad body when SELF_COMMENT_MARKER unset" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"

# 13. Sanity: a genuine command WITHOUT the marker is unaffected — the guard
#     must not over-match (allowed bot, explicit number, marker env present).
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 25' CONTEXT_NUMBER='25' \
  SELF_COMMENT_MARKER='<!-- devflow:workpad -->' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: no-marker command still runs (guard does not over-match)" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: no-marker command → parsed number" \
  "number=25" "$(echo "$OUT" | grep '^number=')"

# 14. Pull-request-context guard: a comment on a PR (IS_PULL_REQUEST=true) must
#     NOT start a run, even for an authorized bot with a resolvable context
#     number. Reproduces the weekly audit-report shape — body quotes the literal
#     phrase in prose with NO trailing number, and CONTEXT_NUMBER is the PR
#     number. The guard runs BEFORE authorization/number resolution and fails
#     closed. Covers issue #124 directly.
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT='the report describes how /devflow:implement publishes its PR' CONTEXT_NUMBER='120' \
  IS_PULL_REQUEST='true' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>"$RIT_STUB_DIR/pr_err")"
assert_eq "rit: pull-request context → should_run=false (PR guard)" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: pull-request context → empty number" \
  "number=" "$(echo "$OUT" | grep '^number=')"
# Pin the GitHub Actions ::warning:: annotation prefix AND the disambiguating
# pull-request-context-guard suffix together, so a regression that drops the
# annotation prefix (losing the Actions-UI surface) or rewords the guard into a
# generic message is caught — not merely that the substring "pull-request"
# appears somewhere on stderr.
assert_eq "rit: pull-request context → ::warning:: from the pull-request-context guard on stderr" \
  "1" "$(grep -cE '::warning::.*pull-request-context guard' "$RIT_STUB_DIR/pr_err")"

# 15. PR guard precedes number resolution: even an EXPLICIT /devflow:implement 42
#     in a PR comment is declined (the guard runs before number parsing), so a
#     deliberate command on a PR thread still cannot start an implement run.
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 42' CONTEXT_NUMBER='120' \
  IS_PULL_REQUEST='true' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: PR context w/ explicit number → still declined" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: PR context w/ explicit number → empty number" \
  "number=" "$(echo "$OUT" | grep '^number=')"

# 16. Sanity: an explicit issue-context signal (IS_PULL_REQUEST=false) does NOT
#     decline — the guard must not over-match a genuine issue comment.
OUT="$(ACTOR='claude[bot]' ALLOWED_BOTS='claude' REPO='acme/x' \
  TRIGGER_TEXT='/devflow:implement 25' CONTEXT_NUMBER='25' \
  IS_PULL_REQUEST='false' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT")"
assert_eq "rit: issue context (IS_PULL_REQUEST=false) still runs" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit: issue context (IS_PULL_REQUEST=false) → number" \
  "number=25" "$(echo "$OUT" | grep '^number=')"

# ── issue #1032: fence/bareness guard on the HEAVY implement trigger ──────────
# Before #1032 the resolver matched the token with a bare `grep`, so a comment
# merely QUOTING /devflow:implement — in prose, a `>` blockquote, an indented or
# fenced code block — fired a full, expensive run. The resolver now routes
# through the SAME shared standalone-command detector the light path uses (issue
# #321), so a non-standalone occurrence declines. Authorized collaborator
# throughout (STUB_PERM=write), so every decline below is the standalone/fence
# decision, never an authorization one.
rit_1032() { ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' STUB_PERM='write' \
  TRIGGER_TEXT="$1" CONTEXT_NUMBER="${2:-99}" PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>/dev/null; }

# AC1 — non-standalone shapes DECLINE: fenced, indented, blockquote, mid-prose.
assert_eq "rit #1032: token inside a fenced block → should_run=false" \
  "should_run=false" "$(rit_1032 "$(printf '%s\n' 'see below' '```' '/prflow:implement 42' '```')" | grep '^should_run=')"
assert_eq "rit #1032: token indented as a code block → should_run=false" \
  "should_run=false" "$(rit_1032 '    /prflow:implement 42' | grep '^should_run=')"
assert_eq "rit #1032: token in a > blockquote → should_run=false" \
  "should_run=false" "$(rit_1032 '> /prflow:implement 42' | grep '^should_run=')"
assert_eq "rit #1032: token mid-sentence in prose → should_run=false" \
  "should_run=false" "$(rit_1032 'do not run /prflow:implement 42, just discussing it' | grep '^should_run=')"
# A quoted mention must resolve NO number either — it must not fall through to the
# context number and fire on the attached issue.
assert_eq "rit #1032: quoted mention → empty number (no context fallthrough)" \
  "number=" "$(rit_1032 'do not run /prflow:implement 42' | grep '^number=')"

# AC4 — fail-closed on an UNBALANCED (unclosed) fence: the over-exclude direction.
assert_eq "rit #1032: unbalanced (unclosed) fence → should_run=false" \
  "should_run=false" "$(rit_1032 "$(printf '%s\n' '```' '/prflow:implement 42')" | grep '^should_run=')"

# AC2 — standalone forms STILL fire: bare token (context fallback) and #-number.
# Capture once and grep twice (the file's idiom), so the resolver runs once here.
OUT="$(rit_1032 '/prflow:implement' 25)"
assert_eq "rit #1032: bare standalone token still fires" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit #1032: bare token falls back to the context number" \
  "number=25" "$(echo "$OUT" | grep '^number=')"
assert_eq "rit #1032: standalone #-number resolves the explicit number" \
  "number=7" "$(rit_1032 '/prflow:implement #7' 25 | grep '^number=')"

# AC2 — the REAL auto-resume body composed by devflow-implement.yml, reproduced
# faithfully as a fixture (leading stall-backstop-audit marker, two prose
# paragraphs that inline-quote the vendored helper path in backticks, the token
# alone on the final line). A regression declining this silently disables stall
# recovery, so it is exercised end-to-end rather than paraphrased.
RIT_RESUME_BODY="$(printf '%s\n\n' '<!-- prflow:stall-backstop-audit -->'
printf '**DevFlow stall backstop** — this cloud run ended while the workpad Status was still in-progress (`Implementing`). Auto-resume attempt 1 of 3:\n\n'
printf 'Resume note: invoke bundled helpers as `.prflow/vendor/prflow/scripts/…` (and `.prflow/vendor/prflow/lib/…`) with that path as the leading token.\n\n'
printf 'Headless note: this is a headless run — ending the turn ends the process, with no re-invocation.\n\n'
printf '/prflow:implement %s\n' 42)"
OUT="$(rit_1032 "$RIT_RESUME_BODY" 99)"
assert_eq "rit #1032: real auto-resume body still triggers (stall recovery intact)" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit #1032: auto-resume body resolves the token's own number" \
  "number=42" "$(echo "$OUT" | grep '^number=')"

# AC5 — the authorization and self-trigger guards are UNCHANGED under the new
# routing: negative controls that each STILL fires. A bad token fails closed even
# on a genuine standalone command...
OUT="$(ACTOR='stranger' ALLOWED_BOTS='' REPO='acme/x' STUB_PERM='none' \
  TRIGGER_TEXT='/prflow:implement 42' CONTEXT_NUMBER='99' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>/dev/null)"
assert_eq "rit #1032: non-collaborator on a standalone command still fails closed" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
# ...and a body carrying the workpad marker is still declined by the self-trigger
# guard, which runs BEFORE detection (a standalone command in the same body does
# not rescue it).
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' STUB_PERM='write' \
  TRIGGER_TEXT="$(printf '%s\n' '<!-- prflow:workpad -->' '/prflow:implement 42')" CONTEXT_NUMBER='99' \
  SELF_COMMENT_MARKER='<!-- prflow:workpad -->' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT" 2>/dev/null)"
assert_eq "rit #1032: workpad-marker body still declined (self-trigger guard intact)" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"

# AC3 — a MISSING/unrunnable detector declines fail-closed with a DISTINCT
# broken-install breadcrumb (mirrors resolve-command-trigger.sh's #314 guard) —
# not a generic set -e abort, not a misdirected "no command" message. Run a
# resolver copy from a temp dir with NO sibling detect-standalone-command.sh.
RIT_NODET_DIR="$(mktemp -d)"; cp "$RIT" "$RIT_NODET_DIR/resolve-implement-trigger.sh"
cp "$LIB/../scripts/authorize-actor.sh" "$RIT_NODET_DIR/authorize-actor.sh"
RIT_NODET_ERR="$(mktemp)"
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' STUB_PERM='write' \
  TRIGGER_TEXT='/prflow:implement 42' CONTEXT_NUMBER='99' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT_NODET_DIR/resolve-implement-trigger.sh" 2>"$RIT_NODET_ERR")"
assert_eq "rit #1032: missing detector → should_run=false (fail-closed)" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit #1032: missing detector emits a distinct broken-install ::warning::" \
  "1" "$(grep -c '::warning::standalone-command detector' "$RIT_NODET_ERR")"
rm -rf "$RIT_NODET_DIR"; rm -f "$RIT_NODET_ERR"

# AC3 (CLAUDE.md guard-class 2) — the detector's `command=`/`number=` lines are
# parsed with BASH BUILTINS, never `sed`. lib/preflight.sh guarantees git/gh/jq/
# python3 but NOT `sed`, and the superseded `sed -n 's/^command=//p'` form ran in
# a plain command substitution under `set -euo pipefail`: an absent `sed` exited
# 127 and aborted the resolver with NEITHER `should_run=` line emitted, so the
# caller appended nothing to $GITHUB_OUTPUT and the downstream read saw empty
# rather than a definite `false` — a silent, non-fail-closed abort in a trigger
# gate, the one raw-abort mode the `if !` detector guard above already avoids.
# Drive the resolver under a PATH that GENUINELY lacks `sed`: a directory holding
# only the three tools this path legitimately needs — `bash` (runs the detector),
# `awk` (inside it), `dirname` (anchors both siblings).
RIT_NOSED_DIR="$(mktemp -d)"
for RIT_NOSED_TOOL in awk dirname; do
  ln -s "$(command -v "$RIT_NOSED_TOOL")" "$RIT_NOSED_DIR/$RIT_NOSED_TOOL"
done
# `$BASH` — the interpreter running this suite — not PATH's first `bash`: the
# sourced authorize-actor.sh uses bash-4 parameter expansion (`${la,,}`), which a
# 3.2 /bin/bash rejects at PARSE time even on the allowed-bot path that never
# evaluates it.
ln -s "$BASH" "$RIT_NOSED_DIR/bash"
# Self-check FIRST, so this arm can never go vacuously green on a fixture PATH
# that still resolves sed.
assert_eq "rit #1032: the no-sed fixture PATH genuinely lacks sed" "absent" \
  "$(PATH="$RIT_NOSED_DIR" command -v sed >/dev/null 2>&1 && echo present || echo absent)"

# The FIRE path is the strongest evidence the parse RESOLVED rather than merely
# declined: should_run=true carrying the token's OWN number is reachable only by
# extracting both values out of the detector's stdout. Allowed-bot actor, so
# authorization short-circuits before gh/mktemp/grep/head (all absent here too).
RIT_NOSED_ERR="$(mktemp)"
OUT="$(ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='acme/x' \
  DEVFLOW_GH="$RIT_STUB_DIR/gh" \
  TRIGGER_TEXT='/prflow:implement 42' CONTEXT_NUMBER='7' \
  PATH="$RIT_NOSED_DIR" bash "$RIT" 2>"$RIT_NOSED_ERR")"
assert_eq "rit #1032: sed absent → a standalone command still fires" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit #1032: sed absent → the token's own number is still extracted" \
  "number=42" "$(echo "$OUT" | grep '^number=')"

# ...and the DECLINE path emits a definite verdict rather than aborting. rc 0 +
# a `should_run=false` line is exactly what the raw `sed` abort could not produce.
RIT_NOSED_OUT="$(mktemp)"
: > "$RIT_NOSED_ERR"
RIT_NOSED_RC=0
ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='acme/x' \
  DEVFLOW_GH="$RIT_STUB_DIR/gh" \
  TRIGGER_TEXT='do not run /prflow:implement 42, just discussing it' CONTEXT_NUMBER='7' \
  PATH="$RIT_NOSED_DIR" bash "$RIT" >"$RIT_NOSED_OUT" 2>"$RIT_NOSED_ERR" || RIT_NOSED_RC=$?
assert_eq "rit #1032: sed absent → the decline exits 0, never a raw abort" \
  "0" "$RIT_NOSED_RC"
assert_eq "rit #1032: sed absent → a quoted mention still declines definitely" \
  "should_run=false" "$(grep '^should_run=' "$RIT_NOSED_OUT")"
# The breadcrumb must be the SPECIFIC no-standalone one — neither silence nor the
# broken-install detector message (which would mean awk, not the parse, carried
# the decline and the arm was measuring the wrong thing).
assert_eq "rit #1032: sed absent → the decline carries its own no-standalone breadcrumb" \
  "1" "$(grep -c '::warning::No STANDALONE /devflow:implement command' "$RIT_NOSED_ERR")"
rm -rf "$RIT_NOSED_DIR"; rm -f "$RIT_NOSED_ERR" "$RIT_NOSED_OUT"

# AC3 — a detector whose stdout carries NO `command=` line violates its own
# output contract (its END block prints both lines unconditionally), so the parse
# cannot resolve a command at all. That is a BROKEN INSTALL — a truncated or
# foreign stdout — not "no command present": it declines fail-closed under its
# OWN breadcrumb rather than being misreported as a clean no-command decline.
RIT_BADDET_DIR="$(mktemp -d)"
cp "$RIT" "$RIT_BADDET_DIR/resolve-implement-trigger.sh"
# The stub violates the detector's OUTPUT contract (no `command=` line) — that is the
# whole point of this arm — but it must still honour the INPUT one and drain stdin, as
# the real detector's awk does. The resolver feeds it through a pipe under
# `set -o pipefail`; a stub that exits WITHOUT reading leaves the writing `printf` to
# take SIGPIPE whenever the scheduler runs the reader to completion first, so the
# pipeline reports failure and the resolver takes its "detector failed to run" arm
# instead of the output-contract arm this test measures. Both arms are fail-closed
# (`should_run=false`, rc 0), so only the breadcrumb assertion below would go red —
# and only under load, which is exactly what happened once lib/test/test_module_runner.py
# began running the exact-floor modules concurrently (issue #1181) on a saturated
# 4-vCPU runner. Drain with a builtin loop so the stub cannot fail on a host missing
# `cat`; do not "simplify" the drain away.
printf '#!/usr/bin/env bash\nwhile IFS= read -r _drain; do :; done\nprintf "number=5\\n"\n' > "$RIT_BADDET_DIR/detect-standalone-command.sh"
chmod +x "$RIT_BADDET_DIR/detect-standalone-command.sh"
RIT_BADDET_ERR="$(mktemp)"
OUT="$(ACTOR='alice' ALLOWED_BOTS='' REPO='acme/x' STUB_PERM='write' \
  TRIGGER_TEXT='/prflow:implement 42' CONTEXT_NUMBER='99' \
  PATH="$RIT_STUB_DIR:$PATH" bash "$RIT_BADDET_DIR/resolve-implement-trigger.sh" 2>"$RIT_BADDET_ERR")"
assert_eq "rit #1032: detector emitting no command= line → should_run=false (fail-closed)" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rit #1032: detector emitting no command= line → a distinct output-contract ::warning::" \
  "1" "$(grep -c "emitted no 'command=' line" "$RIT_BADDET_ERR")"
rm -rf "$RIT_BADDET_DIR"; rm -f "$RIT_BADDET_ERR"

# --- issue #1032: coupled-invariant pin (implement resolver ↔ shared detector) --
# The implement resolver MUST route through the ONE shared detector (the twin of
# the rct #314 pin below); re-inlining a `grep`/substring matcher here re-opens
# the drift issue #321 exists to prevent.
devflow_module_pin_unique "rit #1032: implement resolver calls the shared detect-standalone-command.sh" \
  'detector="$(dirname "$0")/detect-standalone-command.sh"' "$RIT"

rm -rf "$RIT_STUB_DIR"

# ────────────────────────────────────────────────────────────────────────────
echo "dedupe-implement-run.sh"
# ────────────────────────────────────────────────────────────────────────────
# Per-thread duplicate detection for /devflow:implement. GitHub has no native
# "skip if already running", so this gate-stage check decides duplicate=true
# when an OLDER active run for the same issue/PR thread exists, letting the
# workflow skip the billable job and leave the in-flight run untouched. The gh
# `run list` call is stubbed via DEVFLOW_GH; DEDUPE_RUNS_JSON feeds the run set
# and DEDUPE_GH_RC simulates a query failure.
DIR="$LIB/../scripts/dedupe-implement-run.sh"
DI_STUB="$(mktemp -d)"
cat > "$DI_STUB/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"run list"*)
    [ -n "${DI_ARGS_REC:-}" ] && echo "$*" >> "$DI_ARGS_REC"
    [ -n "${DEDUPE_GH_RC:-}" ] && exit "$DEDUPE_GH_RC"
    printf '%s' "${DEDUPE_RUNS_JSON:-[]}" ;;
  *) echo "" ;;
esac
STUB
chmod +x "$DI_STUB/gh"
# Neutralize any ambient GITHUB_EVENT_PATH: when this suite runs inside a cloud
# job the runner exports it, and dedupe-implement-run.sh self-derives the
# stall-resume carve-out from the triggering comment's body. If that comment
# carries the stall-backstop-audit marker (e.g. this very suite runs under a
# stall-resumed implement job), the script would bypass dedupe and every
# duplicate=true expectation below would spuriously read duplicate=false. The
# carve-out tests set GITHUB_EVENT_PATH explicitly, so clearing it here (empty →
# the script's `[ -n ... ]` guard skips the self-derive) isolates the default set.
di() { DEVFLOW_GH="$DI_STUB/gh" GITHUB_EVENT_PATH='' REPO=o/r RUN_ID="$1" CONTEXT_NUMBER="$2" \
  DEDUPE_RUNS_JSON="$3" bash "$DIR" 2>/dev/null; }

# 1. An OLDER (smaller databaseId) active run for the same thread → duplicate.
assert_eq "di: older active run, same thread → duplicate" "duplicate=true" \
  "$(di 200 42 '[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]')"

# 2. A queued (not yet started) older run still counts as active → duplicate.
assert_eq "di: older QUEUED run, same thread → duplicate" "duplicate=true" \
  "$(di 200 42 '[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"queued"}]')"

# 3. A NEWER run (larger id) is NOT deferred to — this run is the older of the
#    two and proceeds; the newer one will defer to it. Guards against two
#    near-simultaneous commands BOTH skipping.
assert_eq "di: newer run, same thread → not duplicate (this run is older)" "duplicate=false" \
  "$(di 200 42 '[{"databaseId":300,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]')"

# 4. An older active run for a DIFFERENT thread → not a duplicate (per-thread).
assert_eq "di: older run, different thread → not duplicate" "duplicate=false" \
  "$(di 200 42 '[{"databaseId":100,"displayTitle":"DevFlow implement (issue 43)","status":"in_progress"}]')"

# 5. Number-boundary: thread 2 must not match a run-name carrying thread 21.
assert_eq "di: thread 2 does not match 'issue 21'" "duplicate=false" \
  "$(di 200 2 '[{"databaseId":100,"displayTitle":"DevFlow implement (issue 21)","status":"in_progress"}]')"

# 6. A finished run (completed) is not active → not a duplicate.
assert_eq "di: completed run → not duplicate" "duplicate=false" \
  "$(di 200 42 '[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"completed"}]')"

# 7. Only this run itself in the list (id == RUN_ID) → not a duplicate.
assert_eq "di: self only → not duplicate" "duplicate=false" \
  "$(di 200 42 '[{"databaseId":200,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]')"

# 8. No active runs at all → not a duplicate.
assert_eq "di: empty run list → not duplicate" "duplicate=false" \
  "$(di 200 42 '[]')"

# 9. gh query failure → fail OPEN (run proceeds), never silently swallowed.
assert_eq "di: gh failure → fail open (not duplicate)" "duplicate=false" \
  "$(DEVFLOW_GH="$DI_STUB/gh" GITHUB_EVENT_PATH='' REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 DEDUPE_GH_RC=1 bash "$DIR" 2>/dev/null)"

# 10. Missing/invalid CONTEXT_NUMBER → fail open (cannot dedupe without a thread).
assert_eq "di: missing context number → fail open" "duplicate=false" \
  "$(di 200 '' '[]')"

# 11. Active-status set spanning 3+ overlapping runs: the OLDEST proceeds, a
#     middle run defers. Asserts the "exactly one of N proceeds" invariant beyond
#     the pairwise N=2 cases above (no double-skip across a 3-way race).
THREE='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"},{"databaseId":200,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"},{"databaseId":300,"displayTitle":"DevFlow implement (issue 42)","status":"queued"}]'
assert_eq "di: 3-way race, oldest (id 100) → proceeds" "duplicate=false" "$(di 100 42 "$THREE")"
assert_eq "di: 3-way race, middle (id 200) → defers" "duplicate=true"  "$(di 200 42 "$THREE")"
assert_eq "di: 3-way race, newest (id 300) → defers" "duplicate=true"  "$(di 300 42 "$THREE")"

# 12. Malformed JSON (gh returned 200 + non-JSON, e.g. an HTML error page) → jq
#     fails, count is non-numeric → fail OPEN. Distinct path from the gh-exit
#     failure (#9) and missing-input (#10) cases.
assert_eq "di: malformed run-list JSON → fail open (not duplicate)" "duplicate=false" \
  "$(di 200 42 'not-json{')"

# 13. The run list MUST be scoped to --workflow devflow-implement.yml — otherwise
#     a same-numbered run of a DIFFERENT workflow (e.g. /devflow:review) could
#     spuriously suppress a legitimate /devflow:implement. Record the gh argv and
#     assert the flag is present.
DI_REC="$(mktemp)"
DEVFLOW_GH="$DI_STUB/gh" GITHUB_EVENT_PATH='' REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 DEDUPE_RUNS_JSON='[]' \
  DI_ARGS_REC="$DI_REC" bash "$DIR" >/dev/null 2>&1
assert_eq "di: run list is scoped to --workflow devflow-implement.yml" "1" \
  "$(grep -c -- '--workflow devflow-implement.yml' "$DI_REC")"
rm -f "$DI_REC"

# 14. The duplicate-ignored NOTICE must carry no DevFlow trigger phrase, or the
#     bot's own comment would re-fire devflow-implement.yml (self-trigger loop).
#     Assert the workflow's notice body is phrase-free.
NOTICE_LINE="$(grep -A2 'Notice — duplicate ignored' "$LIB/../.github/workflows/devflow-implement.yml" || true; \
  grep 'NOTE=' "$LIB/../.github/workflows/devflow-implement.yml" || true)"
# Guard against a vacuous pass: if the grep window ever stops capturing the notice
# body, grep -c on empty input returns 0 and the phrase-free checks pass without
# inspecting anything. Assert we actually captured the notice first.
assert_eq "di: notice test captured the notice body (no vacuous pass)" "1" \
  "$(grep -c 'already in progress' <<< "$NOTICE_LINE")"
# Scanned over EVERY declared command namespace, not just the transitional one.
# devflow-implement.yml fires on BOTH `/prflow:implement` and `/devflow:implement`,
# so a guard spelling only `/devflow:` gives zero assurance for `/prflow:` — a
# canonical-namespace phrase could leak into the notice and re-fire the workflow
# with this check still green. Derived from the declared plugin identity rather
# than hardcoded, and built with bash builtins because it SELECTS what gets
# scanned: a missing non-preflight PATH tool would silently empty the set and
# pass by inspecting nothing.
DI_CMD_NS=""
while IFS= read -r _di_ns; do
  case "$_di_ns" in
    "" ) : ;;
    *) DI_CMD_NS="$DI_CMD_NS $_di_ns" ;;
  esac
done <<EOF
$(python3 "$LIB/plugin_identity.py" --plugin-names 2>/dev/null || true)
EOF
assert_eq "di: the scanned command-namespace set is non-empty (guard is not vacuous)" \
  "yes" "$(case "$DI_CMD_NS" in *[!\ ]*) echo yes ;; *) echo no ;; esac)"
for _di_ns in $DI_CMD_NS; do
  assert_eq "di: duplicate notice contains no /$_di_ns: phrase" "0" \
    "$(grep -c "/$_di_ns:" <<< "$NOTICE_LINE")"
done
# PLANTED-DEFECT CONTROL: each namespace's check must actually RED on the leak it
# claims to catch, so the control first asserts the mutation really changed the body.
for _di_ns in $DI_CMD_NS; do
  _DI_PLANTED="${NOTICE_LINE/NOTE=/NOTE=see \/$_di_ns:implement }"
  assert_eq "di: CONTROL — the planted /$_di_ns: mutation really changed the notice body" \
    "no" "$([ "$_DI_PLANTED" = "$NOTICE_LINE" ] && echo yes || echo no)"
  assert_eq "di: CONTROL — a planted /$_di_ns: phrase turns the duplicate-notice check RED" \
    "yes" "$([ "$(grep -c "/$_di_ns:" <<< "$_DI_PLANTED")" -gt 0 ] && echo yes || echo no)"
done
assert_eq "di: duplicate notice contains no @claude" "0" \
  "$(grep -c '@claude' <<< "$NOTICE_LINE")"

# 15. Stall-backstop-resume carve-out (issue #280, deferred #268 finding): a run
#     triggered by the stall backstop's auto-resume comment must NOT dedupe against
#     the still-winding-down run it is taking over. With IS_STALL_RESUME=true (the
#     explicit override) the script proceeds even though an OLDER active run for the
#     same thread exists (case 1 above would otherwise be duplicate=true).
assert_eq "di: stall-backstop resume bypasses dedupe (older active peer present)" "duplicate=false" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 IS_STALL_RESUME=true \
     DEDUPE_RUNS_JSON='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]' \
     bash "$DIR" 2>/dev/null)"
# 15b. The carve-out is opt-in: any non-"true" value dedupes normally (older active
#      peer → duplicate=true), so an unrelated command is never let through.
assert_eq "di: IS_STALL_RESUME=false still dedupes normally" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 IS_STALL_RESUME=false \
     DEDUPE_RUNS_JSON='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]' \
     bash "$DIR" 2>/dev/null)"
# 15c. Self-derive from GITHUB_EVENT_PATH (the production path — no workflow env is
#      passed). A triggering comment whose body carries the stall-backstop-audit
#      marker bypasses dedupe; the same event without the marker dedupes normally.
DI_EVT_YES="$(mktemp)"; printf '%s' '{"comment":{"body":"<!-- devflow:stall-backstop-audit -->\n/devflow:implement 42"}}' > "$DI_EVT_YES"
DI_EVT_NO="$(mktemp)";  printf '%s' '{"comment":{"body":"/devflow:implement 42"}}' > "$DI_EVT_NO"
assert_eq "di: event-path comment carrying the stall marker bypasses dedupe" "duplicate=false" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_YES" \
     DEDUPE_RUNS_JSON='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]' \
     bash "$DIR" 2>/dev/null)"
assert_eq "di: event-path comment without the stall marker dedupes normally" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_NO" \
     DEDUPE_RUNS_JSON='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]' \
     bash "$DIR" 2>/dev/null)"
rm -f "$DI_EVT_YES" "$DI_EVT_NO"
# 15c-err. Fail-open detection errors (issue #280 hardening): the marker probe reads a
#      runner-provided payload, so a malformed/unreadable/missing GITHUB_EVENT_PATH must
#      NOT be mistaken for a resume — it falls through to ordinary dedupe (duplicate=true
#      when an older active peer exists). A genuine jq error (exit >1: bad JSON, empty
#      file) additionally emits a ::warning:: so the swallow is visible; a marker merely
#      ABSENT (jq exit 1) stays silent. All three run under set -euo pipefail without
#      aborting. The older-active-peer fixture makes the fall-through observable as
#      duplicate=true (a fail-open-to-dedupe result, not a bypass).
DI_PEER='[{"databaseId":100,"displayTitle":"DevFlow implement (issue 42)","status":"in_progress"}]'
DI_EVT_BAD="$(mktemp)"; printf '%s' 'not json{' > "$DI_EVT_BAD"
# malformed payload → jq exit >1 → fall through to dedupe (duplicate=true) + ::warning::
DI_BAD_ERR="$(mktemp)"
assert_eq "di: malformed GITHUB_EVENT_PATH → not a resume, ordinary dedupe applies" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_BAD" \
     DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_BAD_ERR")"
assert_eq "di: malformed GITHUB_EVENT_PATH emits a ::warning:: (real error is not silent)" "1" \
  "$(grep -c '::warning::dedupe: could not read the stall-resume marker' "$DI_BAD_ERR")"
rm -f "$DI_EVT_BAD" "$DI_BAD_ERR"
# well-formed-but-wrong-SHAPE payload (top-level array/scalar, not an object): jq's
# `.comment` index raises an error → exit >1 → warning branch, same as malformed text.
# This is a distinct input class from "malformed text" — the adversarial input-shape
# matrix (CLAUDE.md best-effort-parser gotcha) designates a runner-provided payload
# parser subject to the {object, array, scalar, ...} sweep. Guards against a future
# `?`/`try` hardening silently flipping a wrong-type payload from warning to silent.
DI_EVT_ARR="$(mktemp)"; printf '%s' '[]' > "$DI_EVT_ARR"
DI_ARR_ERR="$(mktemp)"
assert_eq "di: wrong-type (array) GITHUB_EVENT_PATH → not a resume, ordinary dedupe applies" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_ARR" \
     DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_ARR_ERR")"
assert_eq "di: wrong-type (array) GITHUB_EVENT_PATH emits a ::warning:: (real error is not silent)" "1" \
  "$(grep -c '::warning::dedupe: could not read the stall-resume marker' "$DI_ARR_ERR")"
rm -f "$DI_EVT_ARR" "$DI_ARR_ERR"
# empty-but-readable payload (the "empty file" example the code comment names): passes
# the [ -r ] guard, jq -e on empty input produces no output → exit 4 → warning branch.
DI_EVT_EMPTY="$(mktemp)"; printf '' > "$DI_EVT_EMPTY"
DI_EMPTY_ERR="$(mktemp)"
assert_eq "di: empty GITHUB_EVENT_PATH → not a resume, ordinary dedupe applies" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_EMPTY" \
     DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_EMPTY_ERR")"
assert_eq "di: empty GITHUB_EVENT_PATH emits a ::warning:: (real error is not silent)" "1" \
  "$(grep -c '::warning::dedupe: could not read the stall-resume marker' "$DI_EMPTY_ERR")"
rm -f "$DI_EVT_EMPTY" "$DI_EMPTY_ERR"
# unreadable path (nonexistent) → the [ -r ] guard skips the probe → dedupe, no warning
DI_UNREAD_ERR="$(mktemp)"
assert_eq "di: nonexistent GITHUB_EVENT_PATH → not a resume, ordinary dedupe applies" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH=/nonexistent/devflow-event.json \
     DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_UNREAD_ERR")"
assert_eq "di: nonexistent GITHUB_EVENT_PATH emits no marker-read warning (guard skips probe)" "0" \
  "$(grep -c 'could not read the stall-resume marker' "$DI_UNREAD_ERR")"
rm -f "$DI_UNREAD_ERR"
# PRESENT-but-unreadable payload (issue #280 shadow finding): a file that EXISTS but
# cannot be read (permission/mount anomaly, a partially-materialised/locked payload) is
# a distinct input class from the NONEXISTENT path above — the [ -r ] guard fails on
# both, but only the present-but-unreadable one is an "unreadable payload" the header
# contract promises to WARN on. It must fall through to ordinary dedupe (duplicate=true
# with an older active peer) AND emit a ::warning:: (never a silent swallow of a
# possible genuine resume), unlike the absent-path case which stays silent. chmod a-r is
# a no-op under root (`[ -r ]` is always true), so guard on non-root like the F1 arm.
if [ "$(id -u)" != 0 ]; then
  DI_EVT_LOCKED="$(mktemp)"; printf '%s' '{"comment":{"body":"<!-- devflow:stall-backstop-audit -->"}}' > "$DI_EVT_LOCKED"; chmod a-r "$DI_EVT_LOCKED"
  DI_LOCKED_ERR="$(mktemp)"
  assert_eq "di: present-but-unreadable GITHUB_EVENT_PATH → not a resume, ordinary dedupe applies" "duplicate=true" \
    "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_LOCKED" \
       DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_LOCKED_ERR")"
  assert_eq "di: present-but-unreadable GITHUB_EVENT_PATH emits a ::warning:: (unreadable payload is not silent)" "1" \
    "$(grep -c 'is set but not readable' "$DI_LOCKED_ERR")"
  chmod u+rw "$DI_EVT_LOCKED" 2>/dev/null || true
  rm -f "$DI_EVT_LOCKED" "$DI_LOCKED_ERR"
fi
# well-formed JSON missing .comment.body → marker genuinely absent (jq exit 1) → dedupe,
# no warning (an absent marker is the expected non-resume case, must stay silent).
DI_EVT_NOBODY="$(mktemp)"; printf '%s' '{"issue":{"number":42}}' > "$DI_EVT_NOBODY"
DI_NOBODY_ERR="$(mktemp)"
assert_eq "di: valid payload with no .comment.body → ordinary dedupe applies" "duplicate=true" \
  "$(DEVFLOW_GH="$DI_STUB/gh" REPO=o/r RUN_ID=200 CONTEXT_NUMBER=42 GITHUB_EVENT_PATH="$DI_EVT_NOBODY" \
     DEDUPE_RUNS_JSON="$DI_PEER" bash "$DIR" 2>"$DI_NOBODY_ERR")"
assert_eq "di: absent marker (jq exit 1) emits no warning (expected non-resume is silent)" "0" \
  "$(grep -c 'could not read the stall-resume marker' "$DI_NOBODY_ERR")"
rm -f "$DI_EVT_NOBODY" "$DI_NOBODY_ERR"
# 15d. Coupled cross-file invariant (issue #280): the stall-resume marker the dedupe
#      script keys on MUST stay identical to the marker the stall-backstop step
#      writes into its resume comment. Assert the exact literal is present in both.
DI_WF="$LIB/../.github/workflows/devflow-implement.yml"
assert_eq "di: dedupe script defines the stall-backstop-audit marker" "1" \
  "$(grep -c "STALL_RESUME_MARKER='<!-- prflow:stall-backstop-audit -->'" "$DIR")"
assert_eq "di: same stall-backstop-audit marker literal exists in the workflow (coupling holds)" "true" \
  "$(grep -q "<!-- prflow:stall-backstop-audit -->" "$DI_WF" && echo true || echo false)"
# #1003: the superseded spelling is a SECOND accepted literal on both sides, so a
# resume comment posted before the rename is still recognised (a miss here makes
# the carve-out inert and the run is deduped away as an ordinary duplicate).
assert_eq "di(#1003): dedupe script also defines the superseded stall-backstop-audit marker" "1" \
  "$(grep -c "STALL_RESUME_MARKER_SUPERSEDED='<!-- devflow:stall-backstop-audit -->'" "$DIR")"
assert_eq "di(#1003): the workflow counts the superseded spelling too (lifetime cap does not reset)" "true" \
  "$(grep -q "MARKER_SUPERSEDED='<!-- devflow:stall-backstop-audit -->'" "$DI_WF" \
     && grep -qF -- 'grep -cxF -e "$MARKER" -e "$MARKER_SUPERSEDED"' "$DI_WF" && echo true || echo false)"

rm -rf "$DI_STUB"

# ────────────────────────────────────────────────────────────────────────────
echo "dedupe-review-command.sh (Candidate C — issue #989)"
# ────────────────────────────────────────────────────────────────────────────
# The command path's duplicate check: suppress a redundant standalone
# /prflow:review when a review of the same PR is already IN FLIGHT, detected from
# the review engine's seeded live progress comment (devflow:review-progress,
# 🚀 Reviewing, bot-authored, fresh). The gh comments query is stubbed via
# DEVFLOW_GH; DRC_COMMENTS feeds the comment set and DRC_GH_RC simulates a query
# failure. DEDUPE_NOW_EPOCH fixes "now" so the liveness age-bound is deterministic
# (the fixture updated_at 2001-09-09T01:45:40Z is epoch 999999940, 60s before the
# fixed now 1000000000; the "frozen" fixture is years old).
DRC="$LIB/../scripts/dedupe-review-command.sh"
DRC_STUB="$(mktemp -d)"
cat > "$DRC_STUB/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"api --paginate"*)
    [ -n "${DRC_ARGS_REC:-}" ] && echo "$*" >> "$DRC_ARGS_REC"
    [ -n "${DRC_GH_RC:-}" ] && exit "$DRC_GH_RC"
    printf '%s' "${DRC_COMMENTS-[]}" ;;
  *) echo "" ;;
esac
STUB
chmod +x "$DRC_STUB/gh"
# Fixed clock + a fresh in-flight comment body the review engine really seeds.
DRC_NOW=1000000000
DRC_FRESH='2001-09-09T01:45:40Z'
# The head the seeded comment records and the head the request resolves (issue
# #1010): detect mode is COMMIT-scoped, so every in-flight fixture below carries
# the seed-time producer key and the default request head matches it. A fixture
# WITHOUT that key exercises the legacy fail-open arm explicitly, further down.
DRC_HEADSHA=aa11bb22cc33dd44ee55ff6607788990aabbccdd
DRC_OTHERHEAD=1122334455667788990011223344556677889900
DRC_SEEDKEY='<!-- prflow:review-seeded-head '"$DRC_HEADSHA"' -->'
DRC_INFLIGHT='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
# detect helper: RUN_ID=999 is THIS run (so run=555 comments are peers, run=999 is
# self). stderr is NOT swallowed here, so a caller can capture the breadcrumb with
# its own `2>FILE`; `$(...)` still captures stdout only. HEAD defaults to the head
# the fixtures seed; a caller overrides it by passing `HEAD=…` in "${@:3}" (env(1)
# applies assignments left to right, so the later one wins).
drc() { env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
  HEAD="$DRC_HEADSHA" DRC_COMMENTS="$1" PR="${2:-42}" "${@:3}" bash "$DRC"; }

# suppresses-the-redundant-case — an in-flight bot review-progress comment on THIS
# PR, fresh, authored by a peer run → suppress.
assert_eq "drc: suppresses-the-redundant-case (in-flight review on this PR)" "suppress=true" \
  "$(drc "$DRC_INFLIGHT")"

# does-not-suppress-the-legitimate-case — no in-flight comment at all (the boundary
# the fail-open contract protects: a re-request when nothing is running).
assert_eq "drc: does-not-suppress-the-legitimate-case (no in-flight comment)" "suppress=false" \
  "$(drc '[]')"

# does-not-suppress-on-a-frozen-progress-comment (open question 1) — a killed run
# leaves 🚀 Reviewing frozen; its updated_at is stale, so liveness fails → no suppress.
DRC_FROZEN='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"2000-01-01T00:00:00Z"}]'
assert_eq "drc: does-not-suppress-on-a-frozen-progress-comment (stale updated_at)" "suppress=false" \
  "$(drc "$DRC_FROZEN")"

# author check (open question 3) — a forged marker from a non-bot (user.type
# "User") is NOT trusted → no suppress, even though it is fresh and marker-carrying.
DRC_FORGED='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"User"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc: forged (non-bot) progress marker is not trusted → no suppress" "suppress=false" \
  "$(drc "$DRC_FORGED")"

# self-exclusion — a review-progress comment keyed to THIS run (run=999) is this
# run's own comment and must not suppress (the Candidate-C analogue of the
# implement path's self-only case).
DRC_SELF='[{"body":"<!-- devflow:review-progress run=999-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc: self run-keyed progress comment → no suppress" "suppress=false" \
  "$(drc "$DRC_SELF")"

# terminal review — a bot progress comment already flipped past 🚀 Reviewing is a
# COMPLETED review, not an in-flight one → no suppress.
DRC_TERMINAL='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🎉 APPROVE","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc: terminal (past 🚀 Reviewing) progress comment → no suppress" "suppress=false" \
  "$(drc "$DRC_TERMINAL")"

# ── pre-seed window / unseeded-peer negative controls (issue #1479) ─────────────
# In the window after a peer review run starts but before it seeds its
# prflow:review-progress comment, the detector fails open (suppress=false),
# unchanged — scripts/dedupe-review-command.sh's header records why that is the
# decided behavior. The assertions below are NEGATIVE CONTROLS guarding the
# narrowness of isprogress against a future arm that admits a per-head comment
# which is not a live review-progress comment.

# (a) DISCRIMINATING boundary for the review-progress-MARKER conjunct: a bot, fresh
# comment at THIS head, carrying the seed-time head key and the 🚀 Reviewing status
# but NO review-progress marker. isprogress rejects it on the marker conjunct alone
# (its 🚀 Reviewing and bot conjuncts hold, and it is fresh so the separate liveness
# select passes too), so this is not a relabelled duplicate of the terminal/frozen
# controls — it fails on a DIFFERENT conjunct.
# The single widening that turns it RED: dropping isprogress's
# `(contains($marker) or contains($marker_superseded))` conjunct would admit this
# unmarked comment as an in-flight peer and flip the result to suppress=true.
# (Verified by the copy-based mutation-check recorded on issue #1479's workpad.)
DRC_UNMARKED='[{"body":"'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1479): unseeded-peer window — bot/fresh/🚀 comment carrying no review-progress marker (isprogress rejects on the marker conjunct) → fail open, no suppress" "suppress=false" \
  "$(drc "$DRC_UNMARKED")"

# (b) The requesting run's own prflow:ci-review-trigger marker is a per-head note
# recording that a review was REQUESTED (scripts/post-ci-review-trigger.sh), not a
# peer claim, and no detector reads it. A timeline whose only per-head comment is
# that marker must not suppress: isprogress rejects it (neither a review-progress
# marker nor the 🚀 Reviewing status), so it never counts as an in-flight peer.
DRC_CITRIG='[{"body":"<!-- prflow:ci-review-trigger sha='"$DRC_HEADSHA"' -->","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1479): unseeded-peer window — only per-head comment is the run's own ci-review-trigger marker (not a peer claim) → fail open, no suppress" "suppress=false" \
  "$(drc "$DRC_CITRIG")"

# does-not-suppress-a-backstop-resume — the fixture carries the transitional
# /devflow:review token (what scripts/post-review-backstop-comment.sh writes) AND
# the devflow:review-backstop marker (composed by scripts/request-review-backstop.sh),
# asserting no suppression EVEN WITH an active in-flight peer present. Fails first
# because no marker predicate exists today. The helper matches the marker as an
# order-independent substring, so the exact field order here is not load-bearing;
# the marker literal's agreement with the producer is pinned separately below.
DRC_BACKSTOP_BODY="$(printf '/devflow:review\n<!-- devflow:review-backstop head=abcdef0 attempt=2 -->\n')"
assert_eq "drc: does-not-suppress-a-backstop-resume (marker body, active peer present)" "suppress=false" \
  "$(env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
      HEAD="$DRC_HEADSHA" DRC_COMMENTS="$DRC_INFLIGHT" PR=42 TRIGGER_BODY="$DRC_BACKSTOP_BODY" bash "$DRC" 2>/dev/null)"

# ── the CURRENT marker spelling, on both marker families (issue #1003). Every
# fixture above feeds the SUPERSEDED `devflow:` spelling, so neither the
# `contains($marker)` alternative of the jq isprogress predicate nor the
# `*"$BACKSTOP_MARKER"*` case arm was reached by any assertion in this module —
# each leg could be DELETED OUTRIGHT and every check here stayed green, while the
# only guard on the current literals was a source-text grep that keeps passing
# when the matching leg it names is gone. That is the spelling every post-rename
# comment actually carries, so the untested leg is the one the live tier depends
# on. Each positive is paired with a MIS-CASED near-miss so neither can pass
# tautologically: flipping a production literal's casing turns the positive RED
# (its fixture stops matching) AND the control RED (its fixture starts matching),
# while the superseded-spelling assertions above are unaffected either way.
DRC_INFLIGHT_CURRENT='[{"body":"<!-- prflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1003): current-spelling review-progress marker is in-flight → suppress" "suppress=true" \
  "$(drc "$DRC_INFLIGHT_CURRENT")"
DRC_INFLIGHT_MISCASED='[{"body":"<!-- prflow:Review-Progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1003): mis-cased review-progress marker is not a progress comment → no suppress" "suppress=false" \
  "$(drc "$DRC_INFLIGHT_MISCASED")"

# The backstop-resume override on the current spelling, and its own mis-cased
# control — which must fall through to the ordinary decision, where the active
# peer in DRC_INFLIGHT suppresses. So the control's expectation is the OPPOSITE
# of the positive's, and a marker predicate that matched loosely (case-folded or
# on a shorter prefix) would fail it rather than ride in on the positive's pass.
DRC_BACKSTOP_BODY_CURRENT="$(printf '/prflow:review\n<!-- prflow:review-backstop head=abcdef0 attempt=2 -->\n')"
assert_eq "drc(#1003): current-spelling backstop marker overrides an active peer" "suppress=false" \
  "$(env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
      HEAD="$DRC_HEADSHA" DRC_COMMENTS="$DRC_INFLIGHT" PR=42 TRIGGER_BODY="$DRC_BACKSTOP_BODY_CURRENT" bash "$DRC" 2>/dev/null)"
DRC_BACKSTOP_BODY_MISCASED="$(printf '/prflow:review\n<!-- prflow:Review-Backstop head=abcdef0 attempt=2 -->\n')"
assert_eq "drc(#1003): mis-cased backstop marker is no override → the peer still suppresses" "suppress=true" \
  "$(env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
      HEAD="$DRC_HEADSHA" DRC_COMMENTS="$DRC_INFLIGHT" PR=42 TRIGGER_BODY="$DRC_BACKSTOP_BODY_MISCASED" bash "$DRC" 2>/dev/null)"

# fails-open-when-jq-is-unresolvable — DEVFLOW_JQ at a non-existent binary → exit 0,
# no suppress, and a breadcrumb NAMING the unresolved resolver (not an empty decision).
DRC_JQ_ERR="$(mktemp)"
assert_eq "drc: fails-open-when-jq-is-unresolvable (no suppress)" "suppress=false" \
  "$(env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
      HEAD="$DRC_HEADSHA" DRC_COMMENTS="$DRC_INFLIGHT" PR=42 DEVFLOW_JQ=/nonexistent/jq-binary bash "$DRC" 2>"$DRC_JQ_ERR")"
assert_eq "drc: jq-unresolvable emits a jq-naming breadcrumb (not an empty decision)" "1" \
  "$(grep -c 'could not resolve jq' "$DRC_JQ_ERR")"
rm -f "$DRC_JQ_ERR"

# ── fails-open-on-every-degraded-arm: the malformed-response matrix (issue #989).
# Each row asserts suppress=false AND its own specific breadcrumb.
# (a) non-zero query exit.
DRC_A_ERR="$(mktemp)"
assert_eq "drc: matrix — query failure → no suppress" "suppress=false" \
  "$(env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
      HEAD="$DRC_HEADSHA" DRC_GH_RC=1 PR=42 bash "$DRC" 2>"$DRC_A_ERR")"
assert_eq "drc: matrix — query failure breadcrumb" "1" \
  "$(grep -c 'comments query failed' "$DRC_A_ERR")"
rm -f "$DRC_A_ERR"
# (b) empty stdout (a --paginate over an empty body prints nothing).
DRC_B_ERR="$(mktemp)"
assert_eq "drc: matrix — empty response → no suppress" "suppress=false" \
  "$(drc '' 42 2>"$DRC_B_ERR")"
assert_eq "drc: matrix — empty-response breadcrumb" "1" \
  "$(grep -c 'empty response' "$DRC_B_ERR")"
rm -f "$DRC_B_ERR"
# (c) stdout that is not valid JSON.
DRC_C_ERR="$(mktemp)"
assert_eq "drc: matrix — not-valid-JSON → no suppress" "suppress=false" \
  "$(drc 'not-json{' 42 2>"$DRC_C_ERR")"
assert_eq "drc: matrix — not-valid-JSON breadcrumb" "1" \
  "$(grep -c 'could not parse the comments response' "$DRC_C_ERR")"
rm -f "$DRC_C_ERR"
# (d) valid JSON that is not an array.
DRC_D_ERR="$(mktemp)"
assert_eq "drc: matrix — not-a-JSON-array → no suppress" "suppress=false" \
  "$(drc '{"message":"Not Found"}' 42 2>"$DRC_D_ERR")"
assert_eq "drc: matrix — not-a-JSON-array breadcrumb" "1" \
  "$(grep -c 'was not a JSON array' "$DRC_D_ERR")"
rm -f "$DRC_D_ERR"
# (e) an in-flight candidate whose updated_at is null (liveness cannot be
#     established) → not counted, its own breadcrumb, no suppress.
DRC_E_ERR="$(mktemp)"
DRC_NULLDATE='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":null}]'
assert_eq "drc: matrix — null updated_at candidate → no suppress" "suppress=false" \
  "$(drc "$DRC_NULLDATE" 42 2>"$DRC_E_ERR")"
assert_eq "drc: matrix — null updated_at breadcrumb (liveness could not be established)" "1" \
  "$(grep -c 'unparseable updated_at' "$DRC_E_ERR")"
rm -f "$DRC_E_ERR"
# (f) a comment entry missing the fields the check reads entirely (an ordinary
#     conversation comment) → simply no match, no suppress.
assert_eq "drc: matrix — unrelated conversation comment → no suppress" "suppress=false" \
  "$(drc '[{"body":"looks good to me","user":{"type":"User"},"updated_at":"'"$DRC_FRESH"'"}]')"
# (f2) a bot-authored, marker-carrying, 🚀 Reviewing candidate that OMITS updated_at
#      entirely (distinct from row (e)'s explicit null) → liveness cannot be
#      established → not counted, malformed breadcrumb, no suppress.
DRC_F2_ERR="$(mktemp)"
DRC_NODATE='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_SEEDKEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]'
assert_eq "drc: matrix — candidate omitting updated_at entirely → no suppress" "suppress=false" \
  "$(drc "$DRC_NODATE" 42 2>"$DRC_F2_ERR")"
assert_eq "drc: matrix — omitted updated_at breadcrumb (liveness could not be established)" "1" \
  "$(grep -c 'unparseable updated_at' "$DRC_F2_ERR")"
rm -f "$DRC_F2_ERR"
# (g) unresolved/invalid thread key → no suppress + its own breadcrumb.
DRC_G_ERR="$(mktemp)"
assert_eq "drc: matrix — invalid PR thread key → no suppress" "suppress=false" \
  "$(drc "$DRC_INFLIGHT" notnum 2>"$DRC_G_ERR")"
assert_eq "drc: matrix — invalid PR thread key breadcrumb" "1" \
  "$(grep -c 'PR thread number unresolved/invalid' "$DRC_G_ERR")"
rm -f "$DRC_G_ERR"

# ── COMMIT SCOPE (issue #1010). Detect mode compares the requested head against
# the seed-time producer key the review engine stamps on its progress comment, so
# a review of a DIFFERENT head no longer suppresses. Every arm is driven through
# the helper's real decision; nothing here asserts source wording.
#
# (1) A review of a different head in flight → the request proceeds.
DRC_OTHER_ERR="$(mktemp)"
assert_eq "drc(#1010): in-flight review of a DIFFERENT head → no suppress" "suppress=false" \
  "$(drc "$DRC_INFLIGHT" 42 HEAD="$DRC_OTHERHEAD" 2>"$DRC_OTHER_ERR")"
assert_eq "drc(#1010): different-head breadcrumb names the head-scoped skip" "1" \
  "$(grep -c 'different head' "$DRC_OTHER_ERR")"
rm -f "$DRC_OTHER_ERR"

# (2) The head comparison is EXACT, not a prefix: a requested head that is a
#     strict prefix of the seeded head must not match (a substring containment
#     without the closing delimiter would suppress the wrong commit).
assert_eq "drc(#1010): a head that is a strict PREFIX of the seeded head does not match" "suppress=false" \
  "$(drc "$DRC_INFLIGHT" 42 HEAD="${DRC_HEADSHA:0:12}" 2>/dev/null)"

# (3) LEGACY / absent key (an in-flight review seeded by an older installed copy)
#     → fail OPEN with a breadcrumb naming the absent key. This is the arm that
#     makes the rollout safe: an upgraded workflow reading a pre-#1010 comment
#     must not suppress on a head it cannot establish.
DRC_KEYLESS='[{"body":"<!-- devflow:review-progress run=555-1 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
DRC_LEGACY_ERR="$(mktemp)"
assert_eq "drc(#1010): in-flight comment carrying NO seeded-head key → no suppress (fail open)" "suppress=false" \
  "$(drc "$DRC_KEYLESS" 42 2>"$DRC_LEGACY_ERR")"
assert_eq "drc(#1010): absent-key breadcrumb names the seeded-head producer key" "1" \
  "$(grep -c 'review-seeded-head' "$DRC_LEGACY_ERR")"
rm -f "$DRC_LEGACY_ERR"

# (4) An unestablished request head is not a licence to suppress: detect mode
#     without a usable HEAD fails open with its own breadcrumb (empty, and a
#     non-SHA value that a bare substring compare would happily match).
DRC_NOHEAD_ERR="$(mktemp)"
assert_eq "drc(#1010): empty HEAD in detect mode → no suppress (fail open)" "suppress=false" \
  "$(drc "$DRC_INFLIGHT" 42 HEAD= 2>"$DRC_NOHEAD_ERR")"
assert_eq "drc(#1010): empty-HEAD breadcrumb names the unresolved head" "1" \
  "$(grep -c 'HEAD' "$DRC_NOHEAD_ERR")"
rm -f "$DRC_NOHEAD_ERR"
assert_eq "drc(#1010): non-SHA HEAD in detect mode → no suppress (fail open)" "suppress=false" \
  "$(drc "$DRC_INFLIGHT" 42 HEAD='not a sha' 2>/dev/null)"

# (5) ACCEPTED COST 2 IS A NON-NEGOTIABLE INVARIANT (issue #1010 AC6). A
#     /prflow:review-and-fix run sets head_override=local, so its Phase 0.2
#     $PR_HEAD_SHA is a locally-committed, possibly UNPUSHED sha — while
#     review_dedupe resolves the request head from the API (`headRefOid`). The
#     seeded key therefore records the API head captured BEFORE the override, so
#     a /prflow:review issued during that fix loop is still suppressed.
DRC_LOCAL_UNPUSHED=deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
assert_eq "drc(#1010/AC6): fix-loop comment keyed on the API head still suppresses an unpushed-local run" "suppress=true" \
  "$(drc "$DRC_INFLIGHT" 42 2>/dev/null)"
#     NEGATIVE CONTROL for the mechanism choice: had the seed recorded the fix
#     loop's LOCAL head instead, the same request would stop suppressing — cost 2
#     regressed. Assert that rejected mechanism really does fail, so the choice is
#     covered rather than asserted.
DRC_LOCALKEYED='[{"body":"<!-- devflow:review-progress run=555-1 -->\n<!-- prflow:review-seeded-head '"$DRC_LOCAL_UNPUSHED"' -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1010/AC6): CONTROL — a comment keyed on the unpushed LOCAL head would NOT suppress" "suppress=false" \
  "$(drc "$DRC_LOCALKEYED" 42 2>/dev/null)"

# (6) TEMPLATE COUPLING, driven end to end rather than compared as text: build a
#     progress-comment body from the marker line the SHIPPED seed template in
#     skills/review/SKILL.md carries, substituting a real head for its
#     placeholder, and run the helper over it. A template that drops the key, or
#     spells it differently from the helper's constant, turns this RED — and the
#     extraction is asserted non-empty first so it can never pass vacuously.
DRC_RSKILL="$LIB/../skills/review/SKILL.md"
DRC_TPL_KEY="$(sed -n -E 's/^[[:space:]]*(<!--[[:space:]]+prflow:[a-z-]+)[[:space:]]+\{SEEDED_HEAD\}[[:space:]]+(-->)[[:space:]]*$/\1 '"$DRC_HEADSHA"' \2/p' "$DRC_RSKILL")"
assert_eq "drc(#1010): the shipped seed template really carries a substitutable seeded-head line (no vacuous pass)" \
  "yes" "$(case "$DRC_TPL_KEY" in *[!\ ]*) echo yes ;; *) echo no ;; esac)"
DRC_TPL_BODY='[{"body":"<!-- devflow:review-progress run=555-1 -->\n'"$DRC_TPL_KEY"'\n**Status:** 🚀 Reviewing","user":{"type":"Bot"},"updated_at":"'"$DRC_FRESH"'"}]'
assert_eq "drc(#1010): a body built from the SHIPPED seed template suppresses at the seeded head" "suppress=true" \
  "$(drc "$DRC_TPL_BODY" 42 2>/dev/null)"
assert_eq "drc(#1010): the same shipped-template body does NOT suppress at another head" "suppress=false" \
  "$(drc "$DRC_TPL_BODY" 42 HEAD="$DRC_OTHERHEAD" 2>/dev/null)"

# (7) The notice the commit-scoped cause composes names the commit and makes no
#     pull-request-scope claim (driven over the PRODUCED message, per #989).
DRC_CS_NOTICE="$(env MODE=notice CAUSE=inflight-review HEAD="$DRC_HEADSHA" bash "$DRC")"
assert_eq "drc(#1010): the inflight-review notice names the short commit" "1" \
  "$(grep -c "${DRC_HEADSHA:0:7}" <<< "$DRC_CS_NOTICE")"
assert_eq "drc(#1010): the inflight-review notice makes no pull-request-scope claim" "0" \
  "$(grep -c 'pull-request-scoped' <<< "$DRC_CS_NOTICE" || true)"

# the query is scoped to THIS PR's comments endpoint (a different thread's
# in-flight review is simply not in this PR's comment set). Record the argv.
DRC_REC="$(mktemp)"
env DEVFLOW_GH="$DRC_STUB/gh" REPO=o/r RUN_ID=999 DEDUPE_NOW_EPOCH="$DRC_NOW" \
  HEAD="$DRC_HEADSHA" DRC_COMMENTS='[]' PR=42 DRC_ARGS_REC="$DRC_REC" bash "$DRC" >/dev/null 2>&1
assert_eq "drc: comments query is scoped to this PR's issues/<n>/comments endpoint" "1" \
  "$(grep -c -- 'repos/o/r/issues/42/comments' "$DRC_REC")"
rm -f "$DRC_REC"

# ── notice mode: composition lives in the helper (not an inline workflow NOTE=),
# so the produced message is what the trigger-token guard drives. Anti-vacuity +
# per-cause text (the trigger-token absence itself is driven in lib/test/run.sh
# over the DERIVED command-namespace set).
assert_eq "drc: notice(legacy-check-run) names the Devflow Review check (consumer's real action)" "1" \
  "$(env MODE=notice CAUSE=legacy-check-run HEAD=abcdef1234 bash "$DRC" | grep -c 'already running for this commit')"
assert_eq "drc: notice(inflight-review) states an in-progress review (the new cause's own reason)" "1" \
  "$(env MODE=notice CAUSE=inflight-review HEAD=abcdef1234 bash "$DRC" | grep -c 'already in progress')"
assert_eq "drc: notice(unknown cause) emits an empty notice + a breadcrumb (fail-open)" "notice=" \
  "$(env MODE=notice CAUSE=bogus HEAD=abcdef1234 bash "$DRC" 2>/dev/null)"

# Coupled cross-file invariants (issue #989): the marker literals the helper keys
# on MUST match the review engine's seed template and the backstop producer.
RSKILL="$LIB/../skills/review/SKILL.md"
assert_eq "drc: helper's review-progress marker matches skills/review/SKILL.md's seed" "true" \
  "$(grep -q "PROGRESS_MARKER='<!-- prflow:review-progress'" "$DRC" \
     && grep -q '<!-- prflow:review-progress' "$RSKILL" && echo true || echo false)"
assert_eq "drc(#1003): helper also keys on the superseded review-progress spelling" "true" \
  "$(grep -q "PROGRESS_MARKER_SUPERSEDED='<!-- devflow:review-progress'" "$DRC" && echo true || echo false)"
assert_eq "drc: helper's 🚀 Reviewing status matches the seed template" "true" \
  "$(grep -q "INFLIGHT_STATUS='🚀 Reviewing'" "$DRC" \
     && grep -q '🚀 Reviewing' "$RSKILL" && echo true || echo false)"
DRC_BACKSTOP="$LIB/../scripts/request-review-backstop.sh"
assert_eq "drc: helper's review-backstop marker matches the backstop producer" "true" \
  "$(grep -q "BACKSTOP_MARKER='<!-- prflow:review-backstop'" "$DRC" \
     && grep -q 'prflow:review-backstop' "$DRC_BACKSTOP" && echo true || echo false)"
assert_eq "drc(#1003): helper also keys on the superseded review-backstop spelling" "true" \
  "$(grep -q "BACKSTOP_MARKER_SUPERSEDED='<!-- devflow:review-backstop'" "$DRC" && echo true || echo false)"

# ── workflow wiring (structural): the guard invokes the helper at the VENDORED
# path, GUARDS the invocation so a non-zero exit fails open, emits the deciding
# cause, and the notice step composes via the helper (not an inline literal).
RDWF="$LIB/../.github/workflows/devflow.yml"
assert_eq "drc: guard invokes the helper at its vendored path" "1" \
  "$(grep -cF 'CC_HELPER=.prflow/vendor/prflow/scripts/dedupe-review-command.sh' "$RDWF")"
assert_eq "drc: guard checks the helper is executable before invoking (fail-open on absence)" "1" \
  "$(grep -cF 'if [ ! -x "$CC_HELPER" ]; then' "$RDWF")"
assert_eq "drc: guard invocation is wrapped so a non-zero exit routes to fail-open" "1" \
  "$(grep -cF 'elif ! CC_OUT="$(MODE=detect' "$RDWF")"
assert_eq "drc: guard emits the deciding cause into GITHUB_OUTPUT" "1" \
  "$(grep -cF 'echo "cause=$CAUSE" >> "$GITHUB_OUTPUT"' "$RDWF")"
assert_eq "drc: notice step composes via the helper at its vendored path (MODE=notice)" "1" \
  "$(grep -cF 'NOTICE_HELPER=.prflow/vendor/prflow/scripts/dedupe-review-command.sh' "$RDWF")"
assert_eq "drc: notice step drives the helper in notice mode with the decided cause" "1" \
  "$(grep -cF 'MODE=notice CAUSE="$CAUSE" HEAD="$HEAD" bash "$NOTICE_HELPER"' "$RDWF")"
# Both legacy signals are retained byte-for-byte (issue #989 AC): the Devflow
# Review check-run query and the devflow-review.yml workflow-run query both survive.
assert_eq "drc: legacy Signal 1 (Devflow Review check-run query) retained" "1" \
  "$(grep -cF 'select(.name=="Devflow Review"' "$RDWF")"
assert_eq "drc: legacy Signal 2 (devflow-review.yml workflow-run query) retained" "1" \
  "$(grep -cF -- '--workflow devflow-review.yml' "$RDWF")"
# The review-backstop marker overrides ALL signals in the guard (the helper's own
# backstop check is short-circuited when a legacy signal fires), so the auto-resume
# is never suppressed. The marker literal is coupled with the producer.
assert_eq "drc: guard zeroes all signals on a review-backstop resume (never suppressed)" "1" \
  "$(grep -cF '*"<!-- prflow:review-backstop"*|*"<!-- devflow:review-backstop"*)' "$RDWF")"
assert_eq "drc: guard's review-backstop marker matches the producer (coupling holds)" "true" \
  "$(grep -q 'devflow:review-backstop' "$RDWF" \
     && grep -q 'devflow:review-backstop' "$LIB/../scripts/request-review-backstop.sh" && echo true || echo false)"
# Signal 3 (Candidate C) is short-circuited when a legacy signal already decided,
# so the helper's paginated fetch is not computed and discarded (efficiency).
assert_eq "drc: Candidate-C helper is consulted only when both legacy signals are 0" "1" \
  "$(grep -cF 'if [ "$IC" = "0" ] && [ "$IR" = "0" ]; then' "$RDWF")"
# resolves-the-thread-key (issue #989 named assertion): since issue #1163 devflow.yml
# fires on issue_comment alone (the two pull_request_review* subscriptions were
# removed), and issue_comment populates github.event.issue.number. Both the guard
# job's PR env and the notice step's PR env retain the `|| github.event.pull_request.number`
# fallback as a defensive form so the two sites derive the thread key identically;
# the fallback is now degenerate under the sole trigger but harmless (issue.number is
# always populated), and pinning BOTH sites (guard + notice) keeps them coupled.
assert_eq "drc: guard+notice PR env derive the thread key with the || fallback (both sites coupled)" "2" \
  "$(grep -cF 'PR: ${{ github.event.issue.number || github.event.pull_request.number }}' "$RDWF")"

rm -rf "$DRC_STUB"

# ────────────────────────────────────────────────────────────────────────────
echo "review-progress marker ownership and dead-run diagnosis (#1054)"
# ────────────────────────────────────────────────────────────────────────────
# Exercise the seed helper behind a fixture workpad so these are pure local
# contract tests. The stub records both the marker used for identity lookup and
# the exact body handed to create.
S1054_ROOT="$(mktemp -d)"
mkdir -p "$S1054_ROOT/scripts" "$S1054_ROOT/state"
cp "$LIB/../scripts/seed-review-progress.sh" "$S1054_ROOT/scripts/seed-review-progress.sh"
# compose-run-url.sh (#1536) lives beside the seed helper, which execs it by SCRIPT_DIR to
# compose the RUNLINK line and rewrite the created body's `**Run:**` line. These rows set only
# GITHUB_RUN_ID (not GITHUB_SERVER_URL/GITHUB_REPOSITORY), and a live Actions runner exports
# the latter two ambiently — so unset them here to keep the composed link deterministically
# `_(local run)_` regardless of the host, matching the RUNLINK expectations below.
cp "$LIB/../scripts/compose-run-url.sh" "$S1054_ROOT/scripts/compose-run-url.sh"
chmod +x "$S1054_ROOT/scripts/compose-run-url.sh"
unset GITHUB_SERVER_URL GITHUB_REPOSITORY
cat > "$S1054_ROOT/scripts/workpad.py" <<'PY'
#!/usr/bin/env python3
import os
import shutil
import sys

state = os.environ["S1054_STATE"]
command = sys.argv[1]
args = sys.argv[2:]

def value(flag):
    index = args.index(flag)
    return args[index + 1]

def record_body(body):
    shutil.copyfile(body, os.path.join(state, "created-body"))
    if os.environ.get("S1054_STATEFUL") == "1":
        with open(body, encoding="utf-8") as handle:
            marker = handle.readline().rstrip("\n")
        with open(os.path.join(state, "stateful-marker"), "w", encoding="utf-8") as handle:
            handle.write(marker)

if command == "id":
    marker = value("--marker")
    with open(os.path.join(state, "id-marker"), "w", encoding="utf-8") as handle:
        handle.write(marker)
    stateful_marker = os.path.join(state, "stateful-marker")
    if os.environ.get("S1054_STATEFUL") == "1" and os.path.exists(stateful_marker):
        with open(stateful_marker, encoding="utf-8") as handle:
            if handle.read() == marker:
                print("9002")
                raise SystemExit(0)
    if os.environ.get("S1054_RESUME") == "1":
        print("9001")
        raise SystemExit(0)
    raise SystemExit(2)

if command == "create":
    body = args[-1]
    record_body(body)
    print("9002")
    raise SystemExit(0)

if command == "patch":
    body = args[-1]
    record_body(body)
    raise SystemExit(0)

raise SystemExit(2)
PY
chmod +x "$S1054_ROOT/scripts/workpad.py"

S1054_SEED="$S1054_ROOT/scripts/seed-review-progress.sh"
S1054_BODY="$S1054_ROOT/body.md"
S1054_EXPECTED='<!-- prflow:review-progress run=306999-4 -->'
printf '%s\n' '<!-- prflow:review-progress run=local-improvised-1 -->' '**Status:** 🚀 Reviewing' > "$S1054_BODY"

S1054_OUT="$(GITHUB_RUN_ID=306999 GITHUB_RUN_ATTEMPT=4 S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_SEED" 7 '<!-- prflow:review-progress run=caller-wrong-1 -->' "$S1054_BODY" 2>/dev/null)"
S1054_REPORTED_MARKER="${S1054_OUT#*$'\n'MARKER }"
# The success shape now carries a trailing RUNLINK line (#1536); strip it so the marker parse
# yields the marker alone.
S1054_REPORTED_MARKER="${S1054_REPORTED_MARKER%%$'\n'*}"
assert_eq "seed #1054: cloud marker is derived from run id+attempt and reported after CREATED" \
  "CREATED 9002
MARKER $S1054_EXPECTED
RUNLINK _(local run)_" "$S1054_OUT"
assert_eq "seed #1054: identity lookup uses the cloud-derived marker" "$S1054_EXPECTED" \
  "$(cat "$S1054_ROOT/state/id-marker")"
assert_eq "seed #1054: create rewrites the body's first line to the derived marker" "$S1054_EXPECTED" \
  "$(sed -n '1p' "$S1054_ROOT/state/created-body")"
assert_eq "seed #1054: create leaves exactly one review-progress marker in the normalized body" "1" \
  "$(grep -c '^<!-- prflow:review-progress run=' "$S1054_ROOT/state/created-body")"

# The other two body-input rows prove insertion when marker material is absent
# and replacement remains idempotent when the correct line is already present.
printf '%s\n' '# PRFlow Review' '**Status:** 🚀 Reviewing' > "$S1054_BODY"
S1054_OUT="$(GITHUB_RUN_ID=306999 GITHUB_RUN_ATTEMPT=4 S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_SEED" 7 '' "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: cloud caller may omit all marker material and still creates the authoritative line" \
  "$S1054_EXPECTED" "$(sed -n '1p' "$S1054_ROOT/state/created-body")"
S1054_OMITTED_MARKER="${S1054_OUT#*$'\n'MARKER }"
S1054_OMITTED_MARKER="${S1054_OMITTED_MARKER%%$'\n'*}"
assert_eq "seed #1054: omitted caller marker still receives the helper's reported marker" \
  "$S1054_EXPECTED" "$S1054_OMITTED_MARKER"
printf '%s\n' "$S1054_EXPECTED" '# PRFlow Review' '**Status:** 🚀 Reviewing' > "$S1054_BODY"
GITHUB_RUN_ID=306999 GITHUB_RUN_ATTEMPT=4 S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_SEED" 7 'ignored' "$S1054_BODY" >/dev/null 2>&1
assert_eq "seed #1054: an already-correct marker remains exactly one authoritative first line" "1" \
  "$(grep -cF "$S1054_EXPECTED" "$S1054_ROOT/state/created-body")"

# A resume reports the same authoritative marker so the engine can reuse the
# helper's decision for every later full-body rewrite.
S1054_OUT="$(GITHUB_RUN_ID=306999 GITHUB_RUN_ATTEMPT=4 S1054_RESUME=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 'caller-is-ignored' "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: RESUME reports the authoritative marker on a separate line" \
  "RESUME 9001
MARKER $S1054_EXPECTED
RUNLINK _(local run)_" "$S1054_OUT"

# Local callers keep their explicit positional-slot marker when no usable
# GitHub run id exists, including the whitespace-only cloud value.
S1054_LOCAL='<!-- prflow:review-progress run=local-20260801-1 -->'
printf '%s\n' '# PRFlow review' '**Status:** 🚀 Reviewing' > "$S1054_BODY"
S1054_OUT="$(env -u GITHUB_RUN_ID -u GITHUB_RUN_ATTEMPT S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: absent cloud run id falls back to the existing marker slot" \
  "CREATED 9002
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"
assert_eq "seed #1054: local body receives its explicit fallback marker as line one" "$S1054_LOCAL" \
  "$(sed -n '1p' "$S1054_ROOT/state/created-body")"
S1054_OUT="$(GITHUB_RUN_ID=$' \t ' GITHUB_RUN_ATTEMPT=9 S1054_RESUME=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: whitespace-only cloud run id also falls back to the marker slot" \
  "RESUME 9001
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"
S1054_OUT="$(GITHUB_RUN_ID='' GITHUB_RUN_ATTEMPT=9 S1054_RESUME=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: explicitly empty cloud run id falls back to the marker slot" \
  "RESUME 9001
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"
S1054_OUT="$(env -u GITHUB_RUN_ATTEMPT GITHUB_RUN_ID=307000 S1054_RESUME=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: an absent cloud attempt defaults to one inside the helper" \
  "RESUME 9001
MARKER <!-- prflow:review-progress run=307000-1 -->
RUNLINK _(local run)_" "$S1054_OUT"

# Stateful local run: the engine computes one timestamp-bearing fallback, and a
# second seed invocation resolves the first comment instead of creating another.
rm -f "$S1054_ROOT/state/stateful-marker"
printf '%s\n' '# PRFlow Review' '**Status:** 🚀 Reviewing' > "$S1054_BODY"
S1054_OUT="$(env -u GITHUB_RUN_ID -u GITHUB_RUN_ATTEMPT S1054_STATEFUL=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: first local invocation creates under the engine-computed marker" \
  "CREATED 9002
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"
S1054_OUT="$(env -u GITHUB_RUN_ID -u GITHUB_RUN_ATTEMPT S1054_STATEFUL=1 \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
assert_eq "seed #1054: second local invocation resumes the same marker" \
  "RESUME 9002
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"

# Three full-body rewrites retain the held marker, so exact lookup survives every
# phase boundary rather than only the initial seed.
for S1054_PHASE in 1 2 3; do
  printf '%s\n' "$S1054_LOCAL" '# PRFlow Review' "**Status:** 🚀 Phase $S1054_PHASE" > "$S1054_BODY"
  S1054_STATEFUL=1 S1054_STATE="$S1054_ROOT/state" \
    "$S1054_ROOT/scripts/workpad.py" patch 9002 "$S1054_BODY"
  S1054_OUT="$(env -u GITHUB_RUN_ID -u GITHUB_RUN_ATTEMPT S1054_STATEFUL=1 \
    S1054_STATE="$S1054_ROOT/state" bash "$S1054_SEED" 7 "$S1054_LOCAL" "$S1054_BODY" 2>/dev/null)"
  assert_eq "seed #1054: phase-$S1054_PHASE full-body rewrite remains discoverable by held marker" \
    "RESUME 9002
MARKER $S1054_LOCAL
RUNLINK _(local run)_" "$S1054_OUT"
done

S1054_RC=0
S1054_OUT="$(env -u GITHUB_RUN_ID -u GITHUB_RUN_ATTEMPT S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_SEED" 7 '' "$S1054_BODY" 2>/dev/null)" || S1054_RC=$?
assert_eq "seed #1054: no cloud run key and no fallback marker skips with the new token" \
  "SKIP no-run-key" "$S1054_OUT"
assert_eq "seed #1054: no-run-key keeps the helper's skip exit contract" "3" "$S1054_RC"
assert_eq "seed #1054: retired bad-marker token is absent from the helper" "0" \
  "$(grep -cF 'SKIP bad-marker' "$S1054_SEED" || true)"

# Executable parity pin: the seed's produced marker and the dead-run workflow's
# flip marker must agree for the same run id/attempt.
assert_eq "seed #1054: workflow retains the run-id/attempt marker producer" "1" \
  "$(grep -cF 'FLIP_MARKER="<!-- prflow:review-progress run=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT} -->"' "$RDWF")"
S1054_WF_MARKER="$(GITHUB_RUN_ID=306999 GITHUB_RUN_ATTEMPT=4 python3 - "$RDWF" <<'PY'
import os
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
matches = re.findall(r'^\s*FLIP_MARKER="(<!-- prflow:review-progress run=\$\{GITHUB_RUN_ID\}-\$\{GITHUB_RUN_ATTEMPT\} -->)"$', text, re.M)
if len(matches) != 1:
    raise SystemExit(2)
print(matches[0].replace("${GITHUB_RUN_ID}", os.environ["GITHUB_RUN_ID"]).replace("${GITHUB_RUN_ATTEMPT}", os.environ["GITHUB_RUN_ATTEMPT"]))
PY
)"
assert_eq "seed #1054: helper-reported cloud marker equals the executable workflow flip marker for the same run" \
  "$S1054_WF_MARKER" "$S1054_REPORTED_MARKER"

# The mismatch diagnosis helper is deliberately non-authoritative: every arm
# exits zero and reports one of four outcomes. GitHub/JQ resolution is injected
# so malformed responses and API failure remain deterministic.
S1054_DIAG="$LIB/../scripts/diagnose-review-progress-marker.sh"
S1054_GH="$S1054_ROOT/gh"
cat > "$S1054_GH" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" > "$S1054_STATE/gh-args"
if [ "${S1054_GH_FAIL:-0}" = 1 ]; then
  echo 'HTTP 500' >&2
  exit 1
fi
printf '%s' "${S1054_COMMENTS-[]}"
SH
chmod +x "$S1054_GH"
S1054_JQ="$(command -v jq)"
s1054_diag() {
  S1054_COMMENTS="$1" S1054_GH_FAIL="${2:-0}" DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" S1054_STATE="$S1054_ROOT/state" \
    bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>/dev/null
}

assert_eq "diagnose #1054: exact bot Reviewing marker -> matched" "matched" \
  "$(s1054_diag '[{"body":"<!-- prflow:review-progress run=306999-4 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: another bot Reviewing marker -> foreign" "foreign" \
  "$(s1054_diag '[{"body":"<!-- prflow:review-progress run=foreign-1 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: superseded namespace with the expected run key remains a foreign marker identity" "foreign" \
  "$(s1054_diag '[{"body":"<!-- devflow:review-progress run=306999-4 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: concatenated paginated arrays are flattened before matching" "matched" \
  "$(s1054_diag '[][{"body":"<!-- prflow:review-progress run=306999-4 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: terminal/non-bot/null candidates do not fabricate a mismatch" "absent" \
  "$(s1054_diag '[{"body":"<!-- prflow:review-progress run=foreign-1 -->\n**Status:** ✅ Complete","user":{"type":"Bot"}},{"body":"<!-- prflow:review-progress run=foreign-2 -->\n**Status:** 🚀 Reviewing","user":{"type":"User"}},{"body":null,"user":{}}]')"
assert_eq "diagnose #1054: terminal comment quoting an old Reviewing line stays terminal" "absent" \
  "$(s1054_diag '[{"body":"<!-- prflow:review-progress run=foreign-1 -->\n**Status:** ❌ Review failed\n\nPrior status was **Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: terminal exact marker wins over an unrelated active marker after the flip" "matched" \
  "$(s1054_diag '[{"body":"<!-- prflow:review-progress run=306999-4 -->\n**Status:** ❌ Review failed","user":{"type":"Bot"}},{"body":"<!-- prflow:review-progress run=foreign-1 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]')"
assert_eq "diagnose #1054: no progress comment -> absent" "absent" "$(s1054_diag '[]')"
assert_eq "diagnose #1054: a non-array response -> unestablished" "unestablished" "$(s1054_diag '{}')"
assert_eq "diagnose #1054: malformed JSON -> unestablished" "unestablished" "$(s1054_diag 'not-json')"
assert_eq "diagnose #1054: API failure -> unestablished" "unestablished" "$(s1054_diag '[]' 1)"
S1054_DIAG_ERR="$(S1054_COMMENTS='[]' S1054_GH_FAIL=1 DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>&1 >/dev/null)"
assert_eq "diagnose #1054: API-failure breadcrumb preserves the resolver-routed gh cause" "1" \
  "$(grep -cF 'HTTP 500' <<<"$S1054_DIAG_ERR")"
S1054_BAD_JQ="$S1054_ROOT/bad-jq"
cat > "$S1054_BAD_JQ" <<'SH'
#!/usr/bin/env bash
echo 'fixture jq parse failure' >&2
exit 4
SH
chmod +x "$S1054_BAD_JQ"
S1054_DIAG_ERR="$(S1054_COMMENTS='[]' DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_BAD_JQ" \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>&1 >/dev/null)"
assert_eq "diagnose #1054: parser-failure breadcrumb preserves the resolver-routed jq cause" "1" \
  "$(grep -cF 'fixture jq parse failure' <<<"$S1054_DIAG_ERR")"
S1054_DIAG_RC=0
s1054_diag 'not-json' >/dev/null || S1054_DIAG_RC=$?
assert_eq "diagnose #1054: unestablished diagnosis still exits zero" "0" "$S1054_DIAG_RC"
s1054_diag '[]' >/dev/null
S1054_DIAG_RC=0
DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_DIAG" bad-repo 7 "$S1054_EXPECTED" >/dev/null 2>&1 || S1054_DIAG_RC=$?
assert_eq "diagnose #1054: invalid-input diagnosis still exits zero" "0" "$S1054_DIAG_RC"
assert_eq "diagnose #1054: query is scoped to the supplied repo and PR" "1" \
  "$(grep -cF 'api --paginate repos/o/r/issues/7/comments' "$S1054_ROOT/state/gh-args")"
S1054_DIAG_ERR="$(S1054_COMMENTS='[{"body":"<!-- prflow:review-progress run=foreign-1 -->\n**Status:** 🚀 Reviewing","user":{"type":"Bot"}}]' \
  DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" S1054_STATE="$S1054_ROOT/state" \
  bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>&1 >/dev/null)"
assert_eq "diagnose #1054: foreign alone emits a possible-mismatch warning" "1" \
  "$(grep -cF '::warning::flip review-progress: possible review-progress marker mismatch' <<<"$S1054_DIAG_ERR")"
S1054_DIAG_ERR="$(S1054_COMMENTS='{}' DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>&1 >/dev/null)"
assert_eq "diagnose #1054: unestablished emits distinct non-asserting notice language" "1" \
  "$(grep -cF '::notice::flip review-progress: could not establish whether' <<<"$S1054_DIAG_ERR")"
S1054_DIAG_ERR="$(S1054_COMMENTS='[]' DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" \
  S1054_STATE="$S1054_ROOT/state" bash "$S1054_DIAG" o/r 7 "$S1054_EXPECTED" 2>&1 >/dev/null)"
assert_eq "diagnose #1054: absent emits no possible-mismatch warning" "0" \
  "$(grep -cF 'possible review-progress marker mismatch' <<<"$S1054_DIAG_ERR" || true)"

# The authoritative flip runs before advisory diagnosis so diagnostic latency
# or quota use cannot consume the cleanup window. Diagnosis recognizes the
# exact marker after terminalization, while foreign candidates stay active-only.
S1054_ORDER="$(python3 - "$RDWF" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
print(text.index('bash "$FLIP_HELPER"') < text.index("# review-progress marker diagnosis BEGIN"))
PY
)"
assert_eq "diagnose #1054: workflow performs the authoritative flip before advisory diagnosis" "True" "$S1054_ORDER"

# The dispatcher owns the command predicate that workflow shell must not inline.
# It invokes diagnosis for canonical review commands and stays silent for every
# other command while preserving the best-effort exit contract.
S1054_DISPATCH="$LIB/../scripts/run-review-progress-diagnosis.sh"
: > "$S1054_ROOT/state/gh-args"
DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" S1054_STATE="$S1054_ROOT/state" \
  S1054_COMMENTS='[]' bash "$S1054_DISPATCH" '/prflow:review 7' o/r 7 "$S1054_EXPECTED" >/dev/null 2>&1 || true
assert_eq "diagnose #1054: dispatcher invokes diagnosis for a canonical review command" "1" \
  "$(grep -cF 'api --paginate repos/o/r/issues/7/comments' "$S1054_ROOT/state/gh-args" || true)"
: > "$S1054_ROOT/state/gh-args"
DEVFLOW_GH="$S1054_GH" DEVFLOW_JQ="$S1054_JQ" S1054_STATE="$S1054_ROOT/state" \
  S1054_COMMENTS='[]' bash "$S1054_DISPATCH" '/prflow:pr-description 7' o/r 7 "$S1054_EXPECTED" >/dev/null 2>&1 || true
assert_eq "diagnose #1054: dispatcher does not invoke diagnosis for a non-review command" "0" \
  "$(grep -c . "$S1054_ROOT/state/gh-args" || true)"

# Workflow integration remains diagnostic-only and restricted to canonical
# review command namespaces. Extract and execute the shipped workflow block
# with the real dispatcher and a recording diagnosis sibling.
S1054_WF_ROOT="$S1054_ROOT/workflow"
mkdir -p "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts" "$S1054_WF_ROOT/scripts"
S1054_WF_BLOCK="$S1054_WF_ROOT/diagnosis-block.sh"
python3 - "$RDWF" "$S1054_WF_BLOCK" <<'PY'
import sys
import textwrap

text = open(sys.argv[1], encoding="utf-8").read()
begin = text.index("          # review-progress marker diagnosis BEGIN")
end = text.index("          # review-progress marker diagnosis END", begin)
block = text[begin:end].splitlines()[1:]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("set -uo pipefail\n")
    handle.write(textwrap.dedent("\n".join(block)))
    handle.write("\n")
PY
cp "$S1054_DISPATCH" "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh"
chmod +x "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh"
cat > "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/diagnose-review-progress-marker.sh" <<'SH'
#!/usr/bin/env bash
printf '%s|token=%s\n' "$*" "${GH_TOKEN:-}" >> "$S1054_WF_RECORD"
[ -z "${S1054_WF_MESSAGE:-}" ] || echo "$S1054_WF_MESSAGE" >&2
echo foreign
exit "${S1054_WF_RC:-0}"
SH
chmod +x "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/diagnose-review-progress-marker.sh"
S1054_WF_RECORD="$S1054_WF_ROOT/record"
s1054_run_wf_block() {
  # TARGET_NUMBER is derived by the sibling upsert block (issue #1154) from the
  # command's own trailing number, and the diagnosis dispatch addresses the same
  # thread. This extraction starts below that derivation, so supply the value the
  # upsert block would have produced for this command.
  ( cd "$S1054_WF_ROOT" && COMMAND="$1" REPO=o/r CONTEXT_NUMBER=7 TARGET_NUMBER=7 FLIP_MARKER="$S1054_EXPECTED" \
      GH_TOKEN=secret S1054_WF_RECORD="$S1054_WF_RECORD" S1054_WF_MESSAGE="${2:-}" S1054_WF_RC="${3:-0}" \
      bash "$S1054_WF_BLOCK" )
}
: > "$S1054_WF_RECORD"
s1054_run_wf_block '/prflow:review 7' >/dev/null
s1054_run_wf_block '/prflow:review-and-fix 7' >/dev/null
assert_eq "diagnose #1054: canonical review and review-and-fix each invoke diagnosis" "2" \
  "$(grep -c . "$S1054_WF_RECORD")"
assert_eq "diagnose #1054: workflow passes repo, PR, marker, and inherited GH_TOKEN" \
  "o/r 7 $S1054_EXPECTED|token=secret" "$(sed -n '1p' "$S1054_WF_RECORD")"
S1054_WF_ERR="$(s1054_run_wf_block '/prflow:review 7' '::warning::possible review-progress marker mismatch' 0 2>&1 >/dev/null)"
assert_eq "diagnose #1054: review-path stderr annotation survives workflow stdout suppression" "1" \
  "$(grep -cF '::warning::possible review-progress marker mismatch' <<<"$S1054_WF_ERR")"
: > "$S1054_WF_RECORD"
S1054_WF_ERR="$(s1054_run_wf_block '/prflow:pr-description 7' '::warning::possible review-progress marker mismatch' 0 2>&1 >/dev/null)"
assert_eq "diagnose #1054: non-review command never invokes diagnosis" "0" \
  "$(grep -c . "$S1054_WF_RECORD" || true)"
assert_eq "diagnose #1054: non-review command emits no possible-mismatch warning" "0" \
  "$(grep -cF 'possible review-progress marker mismatch' <<<"$S1054_WF_ERR" || true)"
S1054_WF_RC=0
S1054_WF_ERR="$(s1054_run_wf_block '/prflow:review 7' '' 9 2>&1 >/dev/null)" || S1054_WF_RC=$?
assert_eq "diagnose #1054: diagnosis helper failure leaves workflow block exit status unchanged" "0" "$S1054_WF_RC"
assert_eq "diagnose #1054: unexpected helper failure emits an observable dispatcher notice" "1" \
  "$(grep -cF 'diagnosis helper exited 9' <<<"$S1054_WF_ERR" || true)"
cp "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/diagnose-review-progress-marker.sh" \
  "$S1054_WF_ROOT/scripts/diagnose-review-progress-marker.sh"
cp "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh" \
  "$S1054_WF_ROOT/scripts/run-review-progress-diagnosis.sh"
rm -f "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/diagnose-review-progress-marker.sh" \
  "$S1054_WF_ROOT/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh"
: > "$S1054_WF_RECORD"
s1054_run_wf_block '/prflow:review 7' >/dev/null
assert_eq "diagnose #1054: absent vendored helper falls back to the repo-root helper" "1" \
  "$(grep -c . "$S1054_WF_RECORD")"

rm -rf "$S1054_ROOT"

# ────────────────────────────────────────────────────────────────────────────
echo "dead-run review-progress upsert: cause selection and the create arm (#1154)"
# ────────────────────────────────────────────────────────────────────────────
# devflow.yml's dead-run backstop used to be gated on three outcome disjuncts and
# to be flip-ONLY. Actions run 29854795625 matched neither: the claude step exited
# cleanly, the engine reported no error, and the run had died in Phase 0 before the
# engine's Phase 0.3.5 seed — so the step never fired, and could not have helped if
# it had, because there was no comment to flip. Issue #1154 ungates the step, moves
# the cause selection into a helper the suite can drive arm by arm, and turns the
# write into an upsert. Everything below drives real processes: the cause helper is
# a pure function of two strings, and the upsert helper runs end to end against a
# stubbed gh, so no arm is asserted by reading source.

S1154_CAUSE="$LIB/../scripts/describe-dead-run-cause.sh"

# ── The four run-end modes. They partition on the two observables devflow.yml
# has, so this table IS the contract: each mode, one cause string.
assert_eq "#1154 cause: engine is_error on a SUCCESS step names the engine-error mode" \
  "review engine ended with an error (is_error)" "$(bash "$S1154_CAUSE" success true)"
assert_eq "#1154 cause: a clean step with no engine error names the no-verdict mode (the run-29854795625 mode)" \
  "claude step success but the run wrote no verdict (engine reported no error)" \
  "$(bash "$S1154_CAUSE" success false)"
assert_eq "#1154 cause: a failed job names the step failure" \
  "claude step failure" "$(bash "$S1154_CAUSE" failure false)"
assert_eq "#1154 cause: a cancelled run names the cancellation" \
  "claude step cancelled" "$(bash "$S1154_CAUSE" cancelled false)"
# The four modes must be four DISTINCT strings, or the partition collapses and a
# maintainer cannot tell which one fired from the comment alone.
assert_eq "#1154 cause: the four run-end modes map to four distinct cause strings" "4" \
  "$( { bash "$S1154_CAUSE" success true; bash "$S1154_CAUSE" success false
       bash "$S1154_CAUSE" failure false; bash "$S1154_CAUSE" cancelled false; } | sort -u | grep -c . || true)"
# The step's own non-success outcome wins over is_error: a FAILED step whose engine
# also reported an error is still reported as the job failure (the engine-error arm
# is deliberately conjoined with `outcome == success`).
assert_eq "#1154 cause: a failed step with is_error still names the step failure, not the engine" \
  "claude step failure" "$(bash "$S1154_CAUSE" failure true)"
# Only the exact literal `true` is an engine error — the producer normalizes anything
# else to false, so a near-miss must NOT be read as an error.
assert_eq "#1154 cause: only the exact literal 'true' counts as an engine error" \
  "claude step success but the run wrote no verdict (engine reported no error)" \
  "$(bash "$S1154_CAUSE" success TRUE)"
assert_eq "#1154 cause: an empty is_error is not an engine error" \
  "claude step success but the run wrote no verdict (engine reported no error)" \
  "$(bash "$S1154_CAUSE" success '')"
# Residual outcomes are named verbatim rather than misattributed to one of the four.
assert_eq "#1154 cause: a residual raw outcome is named verbatim" \
  "claude step skipped" "$(bash "$S1154_CAUSE" skipped false)"
assert_eq "#1154 cause: an absent outcome is reported as unavailable, never collapsed onto a real mode" \
  "claude step outcome unavailable" "$(bash "$S1154_CAUSE")"
S1154_RC=0
bash "$S1154_CAUSE" >/dev/null 2>&1 || S1154_RC=$?
assert_eq "#1154 cause: always exits 0 (it can never change the invoking job's result)" "0" "$S1154_RC"

# ── ARM ORDER. The engine-error arm and the no-verdict arm BOTH match
# `outcome == success`, so their relative order decides which cause a run whose
# engine errored is given. Prove the order is load-bearing with a disposable
# mutant: swap the two arms in a scratch copy and confirm the (success, true)
# input now yields the WRONG cause — i.e. a reordering is observable here, not
# something the assertions above would sail past.
S1154_MUT="$(mktemp -d)"
python3 - "$S1154_CAUSE" "$S1154_MUT/reordered.sh" <<'PY'
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
i = next(n for n, l in enumerate(lines) if l.startswith('if [ "$ENGINE_IS_ERROR"'))
arm1, arm2 = lines[i:i + 2], lines[i + 2:i + 4]
assert arm2[0].startswith('elif [ "$CLAUDE_OUTCOME" = "success" ]'), arm2[0]
swapped = arm2 + arm1
swapped[0] = "if " + swapped[0].split(" ", 1)[1]
swapped[2] = "elif " + swapped[2].split(" ", 1)[1]
lines[i:i + 4] = swapped
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
assert_eq "#1154 cause: arm order is load-bearing — reordering the two success arms misattributes an engine error" \
  "claude step success but the run wrote no verdict (engine reported no error)" \
  "$(bash "$S1154_MUT/reordered.sh" success true)"
assert_eq "#1154 cause: the shipped arm order attributes that same input to the engine (the mutant's control)" \
  "review engine ended with an error (is_error)" "$(bash "$S1154_CAUSE" success true)"
rm -rf "$S1154_MUT"

# ── The upsert helper, driven end to end against a stubbed gh. ────────────────
S1154_ROOT="$(mktemp -d)"
mkdir -p "$S1154_ROOT/scripts" "$S1154_ROOT/state"
cp "$LIB/../scripts/flip-review-progress-failed.sh" "$S1154_ROOT/scripts/"
cp "$LIB/../scripts/workpad.py" "$S1154_ROOT/scripts/"
S1154_FLIP="$S1154_ROOT/scripts/flip-review-progress-failed.sh"
S1154_STATE="$S1154_ROOT/state"
S1154_MARK='<!-- prflow:review-progress run=RUN1154-1 -->'
cat > "$S1154_ROOT/gh" <<'STUB'
#!/usr/bin/env bash
# Records every write so an arm that claims "no write" can be proven, not assumed.
j="$*"
if [[ "$j" == *"repo view"* ]]; then echo "owner/repo"; exit 0; fi
if [[ "$j" == *"-X PATCH"* ]]; then
  [ -n "${S1154_PATCH_FAIL:-}" ] && { echo "patch boom" >&2; exit 1; }
  for a in "$@"; do
    case "$a" in body=@*) cp "${a#body=@}" "$S1154_STATE/patched-body"; cat "${a#body=@}" ;; esac
  done
  echo p >> "$S1154_STATE/patchlog"
  exit 0
fi
if [[ "$j" == *"issue comment"* ]]; then
  [ -n "${S1154_CREATE_FAIL:-}" ] && { echo "create boom" >&2; exit 1; }
  _n=
  for a in "$@"; do
    if [ -n "$_n" ]; then cp "$a" "$S1154_STATE/created-body"; _n=; fi
    [ "$a" = "--body-file" ] && _n=1
  done
  echo c >> "$S1154_STATE/createlog"
  [ -n "${S1154_CREATE_NO_URL:-}" ] && { echo "posted but no url printed"; exit 0; }
  echo "https://github.com/owner/repo/pull/55#issuecomment-4242"
  exit 0
fi
if [[ "$j" == *"issues/comments/"* ]]; then
  [ -n "${S1154_BODY_FAIL:-}" ] && { echo "body boom" >&2; exit 1; }
  cat "$S1154_STATE/body"
  exit 0
fi
if [[ "$j" == *"/comments"* ]]; then
  [ -n "${S1154_LIST_FAIL:-}" ] && { echo "list boom" >&2; exit 1; }
  cat "$S1154_STATE/comments.json"
  exit 0
fi
echo '[]'
STUB
chmod +x "$S1154_ROOT/gh"

# Seed the stub's world. With no argument the issue carries no comment at all —
# the run-died-before-the-seed shape. With one, that file is comment id 7's body.
s1154_seed() {  # [body-file]
  : > "$S1154_STATE/patchlog"; : > "$S1154_STATE/createlog"
  rm -f "$S1154_STATE/patched-body" "$S1154_STATE/created-body"
  if [ "$#" -eq 0 ]; then
    printf '%s' '[]' > "$S1154_STATE/comments.json"
    : > "$S1154_STATE/body"
  else
    cp "$1" "$S1154_STATE/body"
    python3 - "$1" "$S1154_STATE/comments.json" <<'PY'
import json, sys
body = open(sys.argv[1], encoding="utf-8").read()
json.dump([{"id": 7, "body": body}], open(sys.argv[2], "w", encoding="utf-8"))
PY
  fi
}
# Failure modes are passed as trailing KEY=VALUE arguments, never as a command
# prefix on the function call: bash leaves a prefix assignment on a FUNCTION set in
# the calling shell afterward, which would leak one arm's induced failure into every
# later fixture in this section.
s1154_run() {  # <pr> <marker> <cause> [KEY=VALUE...] -> stderr to state/err, prints rc
  local pr="$1" mark="$2" cause="$3" rc=0
  shift 3
  ( cd "$S1154_ROOT" \
    && env DEVFLOW_GH="$S1154_ROOT/gh" S1154_STATE="$S1154_STATE" \
           GITHUB_SERVER_URL=https://github.com GITHUB_REPOSITORY=owner/repo GITHUB_RUN_ID=1154 \
           "$@" bash "$S1154_FLIP" "$pr" "$mark" "$cause" \
       >/dev/null 2>"$S1154_STATE/err" ) || rc=$?
  echo "$rc"
}
s1154_writes() {  # "<patch-count>/<create-count>" — proves "no write" rather than assuming it
  printf '%s/%s' "$(grep -c . "$S1154_STATE/patchlog" || true)" "$(grep -c . "$S1154_STATE/createlog" || true)"
}

printf '%s\n' "$S1154_MARK" '# PRFlow Review — PR #55' '' '**Status:** 🚀 Reviewing' > "$S1154_ROOT/interim.md"

# (flip) an interim comment is still flipped, exactly as before the upsert.
s1154_seed "$S1154_ROOT/interim.md"
assert_eq "#1154 upsert: an interim comment still flips and exits 0" "0" "$(s1154_run 55 "$S1154_MARK" 'job died')"
assert_eq "#1154 upsert: the interim flip PATCHes and creates nothing" "1/0" "$(s1154_writes)"
assert_eq "#1154 upsert: the flipped body carries the terminal Status" "yes" \
  "$(grep -qF '**Status:** ❌ Review failed' "$S1154_STATE/patched-body" && echo yes || echo no)"

# (create) a CONFIRMED clean absence now writes the comment instead of no-opping.
# This is the reported defect: pre-#1154 this arm left the pull request with nothing.
s1154_seed
assert_eq "#1154 upsert: a clean absence exits 0" "0" \
  "$(s1154_run 55 "$S1154_MARK" 'claude step success but the run wrote no verdict (engine reported no error)')"
assert_eq "#1154 upsert: a clean absence CREATES exactly one comment and PATCHes nothing" "0/1" "$(s1154_writes)"
assert_eq "#1154 upsert: the created body carries the run-keyed marker as line 1 (so workpad.py id resolves it)" \
  "$S1154_MARK" "$(sed -n '1p' "$S1154_STATE/created-body")"
assert_eq "#1154 upsert: the created body carries the terminal '❌ Review failed' Status line" "yes" \
  "$(grep -qF '**Status:** ❌ Review failed' "$S1154_STATE/created-body" && echo yes || echo no)"
# The review comment's vocabulary is NOT workpad.py's: a `--status Failed` write
# would stamp 💥, which no reader of this comment recognizes.
assert_eq "#1154 upsert: the created Status uses the review vocabulary's ❌, never workpad.py's 💥" "yes" \
  "$(grep -qF '💥' "$S1154_STATE/created-body" && echo no || echo yes)"
assert_eq "#1154 upsert: the created body names the cause" "yes" \
  "$(grep -qF 'the run wrote no verdict' "$S1154_STATE/created-body" && echo yes || echo no)"
assert_eq "#1154 upsert: the created body carries no interim 🚀 status" "yes" \
  "$(grep -qF '🚀' "$S1154_STATE/created-body" && echo no || echo yes)"
# The breadcrumb must ATTRIBUTE the write: extract the comment id it names and
# compare it to the one the fixture gh stub minted, rather than asserting the
# rendered sentence is present. A create that posted nothing could still print a
# cheerful line; only the id ties the breadcrumb to the comment that exists.
assert_eq "#1154 upsert: the create arm breadcrumb names the comment id that was actually minted" "4242" \
  "$(sed -n 's/.*created comment #\([0-9][0-9]*\).*/\1/p' "$S1154_STATE/err")"
assert_eq "#1154 upsert: the create arm is no longer reported as a no-op" "yes" \
  "$(grep -qi 'no-op' "$S1154_STATE/err" && echo no || echo yes)"
# Exactly ONE breadcrumb per invocation — a second line means two arms fired.
assert_eq "#1154 upsert: the create arm emits exactly one stderr breadcrumb" "1" \
  "$(grep -c '^flip-review-progress-failed:' "$S1154_STATE/err" || true)"

# The body the create arm composed must be resolvable by a subsequent lookup for the
# SAME run. Feed it straight back in: the helper must now take the already-terminal
# arm and write nothing at all. This is the load-bearing idempotency assertion — a
# non-idempotent upsert posts a fresh failure comment on every job retry.
cp "$S1154_STATE/created-body" "$S1154_ROOT/created.md"
s1154_seed "$S1154_ROOT/created.md"
assert_eq "#1154 upsert: a re-run over the comment it just created exits 0" "0" "$(s1154_run 55 "$S1154_MARK" 'job died')"
assert_eq "#1154 upsert: the re-run writes NOTHING (idempotent across job retries)" "0/0" "$(s1154_writes)"
assert_eq "#1154 upsert: the re-run reports the already-terminal arm" "yes" \
  "$(grep -qi 'already terminal' "$S1154_STATE/err" && echo yes || echo no)"

# (already terminal) a comment carrying a written verdict is left byte-untouched and
# no second comment is created — the fail-closed precondition, unchanged.
printf '%s\n' "$S1154_MARK" '# PRFlow Review — PR #55' '' '**Status:** 🎉 Review complete — APPROVE' > "$S1154_ROOT/verdict.md"
s1154_seed "$S1154_ROOT/verdict.md"
assert_eq "#1154 upsert: a written verdict is left untouched and no second comment is created" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"

# ── Error paths. Each must report the SPECIFIC failure and still exit 0.
# A failed LIST never established absence, so it must NOT create — creating on an
# unestablished absence is how a duplicate comment gets posted.
s1154_seed "$S1154_ROOT/interim.md"
assert_eq "#1154 upsert: a failed comment lookup exits 0" "0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' S1154_LIST_FAIL=1)"
assert_eq "#1154 upsert: a failed lookup writes nothing — an unestablished absence never authorizes a create" "0/0" \
  "$(s1154_writes)"
assert_eq "#1154 upsert: a failed lookup is diagnosed as a read failure, not a clean absence" "yes" \
  "$(grep -qi 'read-failure' "$S1154_STATE/err" && grep -qF 'absence was NOT established' "$S1154_STATE/err" && echo yes || echo no)"

# A failed CREATE reports as a create failure, never as a read failure.
s1154_seed
assert_eq "#1154 upsert: a failed create exits 0" "0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' S1154_CREATE_FAIL=1)"
assert_eq "#1154 upsert: a failed create is diagnosed as a create failure, not a read failure" "yes" \
  "$(grep -qi 'create-failure' "$S1154_STATE/err" && ! grep -qi 'read-failure' "$S1154_STATE/err" && echo yes || echo no)"
# A create that "succeeds" while printing no comment id is a create failure too: a
# breadcrumb naming no comment cannot be told from a create that posted nothing.
s1154_seed
assert_eq "#1154 upsert: a create that prints no comment id is reported as a create failure" "yes" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' S1154_CREATE_NO_URL=1 >/dev/null
     grep -qi 'create-failure' "$S1154_STATE/err" && echo yes || echo no)"

# A failed body READ is neither a create nor a patch.
s1154_seed "$S1154_ROOT/interim.md"
assert_eq "#1154 upsert: a failed body read writes nothing and stays a read failure" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' S1154_BODY_FAIL=1 >/dev/null; s1154_writes)"
# A body that reads back EMPTY is an unusable read, not a create authorization.
s1154_seed "$S1154_ROOT/interim.md"
: > "$S1154_STATE/body"
assert_eq "#1154 upsert: a comment whose body reads back empty writes nothing" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A failed PATCH is reported as a patch failure and still exits 0.
s1154_seed "$S1154_ROOT/interim.md"
assert_eq "#1154 upsert: a failed patch exits 0 and is reported as a patch failure" "yes" \
  "$([ "$(s1154_run 55 "$S1154_MARK" 'job died' S1154_PATCH_FAIL=1)" = "0" ] \
    && grep -qi 'patch-failure' "$S1154_STATE/err" && echo yes || echo no)"
# Missing arguments stay usage no-ops — and, now that a clean absence writes, they
# must be screened BEFORE the create arm or an empty marker would create a comment
# no later lookup could ever resolve.
s1154_seed
assert_eq "#1154 upsert: a missing PR number writes nothing" "0/0" \
  "$(s1154_run '' "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
s1154_seed
assert_eq "#1154 upsert: a missing marker writes nothing (never an unresolvable comment)" "0/0" \
  "$(s1154_run 55 '' 'job died' >/dev/null; s1154_writes)"
s1154_seed
assert_eq "#1154 upsert: a non-numeric PR number writes nothing" "0/0" \
  "$(s1154_run 'not-a-number' "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"

# ── Run scoping. The helper writes only to the comment its OWN run-keyed marker
# resolves. A different run's interim comment must survive untouched — this is the
# accepted-loss fixture that proves the scoping holds rather than being asserted.
printf '%s\n' '<!-- prflow:review-progress run=OTHERRUN-1 -->' '# PRFlow Review — PR #55' '' '**Status:** 🚀 Reviewing' \
  > "$S1154_ROOT/foreign.md"
s1154_seed "$S1154_ROOT/foreign.md"
assert_eq "#1154 upsert: another run's interim comment is never patched" "yes" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null
     [ ! -f "$S1154_STATE/patched-body" ] && echo yes || echo no)"
assert_eq "#1154 upsert: with only a foreign comment present this run creates its OWN" "0/1" "$(s1154_writes)"
assert_eq "#1154 upsert: the comment this run created is keyed to THIS run" "$S1154_MARK" \
  "$(sed -n '1p' "$S1154_STATE/created-body")"

# ── Adversarial / malformed mutable-markdown shapes. The comment body is
# agent- and human-mutable markdown, so every ambiguous shape must take a
# DETERMINATE arm, and every ambiguous-terminal shape must fail closed.
printf '%s\n' "$S1154_MARK" '**Status:** 🚀 Reviewing' '**Status:** 🎉 Review complete' > "$S1154_ROOT/two-status.md"
s1154_seed "$S1154_ROOT/two-status.md"
assert_eq "#1154 upsert: a body with two Status lines flips the first and creates nothing" "1/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
assert_eq "#1154 upsert: the FIRST Status line is the one that was rewritten" "**Status:** ❌ Review failed" \
  "$(grep '^\*\*Status:\*\*' "$S1154_STATE/patched-body" | sed -n '1p')"
assert_eq "#1154 upsert: the second Status line survives the flip verbatim" "**Status:** 🎉 Review complete" \
  "$(grep '^\*\*Status:\*\*' "$S1154_STATE/patched-body" | sed -n '2p')"
# A Status line inside a fenced block is still the first Status the parser sees.
# It must fail CLOSED (treat the body as terminal), never guess.
printf '%s\n' "$S1154_MARK" '```' '**Status:** ❌ Review failed' '```' '' '**Status:** 🚀 Reviewing' \
  > "$S1154_ROOT/fenced.md"
s1154_seed "$S1154_ROOT/fenced.md"
assert_eq "#1154 upsert: a fenced terminal Status fails closed — no flip, no create" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A Status line with no glyph at all is not the interim state, so it is terminal.
printf '%s\n' "$S1154_MARK" '**Status:** Reviewing' > "$S1154_ROOT/noglyph.md"
s1154_seed "$S1154_ROOT/noglyph.md"
assert_eq "#1154 upsert: a glyph-less Status fails closed — no flip, no create" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# No Status line at all: no flip, and NOT a create either (the comment exists).
printf '%s\n' "$S1154_MARK" 'no status here' > "$S1154_ROOT/nostatus.md"
s1154_seed "$S1154_ROOT/nostatus.md"
assert_eq "#1154 upsert: a body with no Status line writes nothing (it exists, so it is not a create)" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A body whose ONLY line is the marker: no Status, so no write.
printf '%s\n' "$S1154_MARK" > "$S1154_ROOT/marker-only.md"
s1154_seed "$S1154_ROOT/marker-only.md"
assert_eq "#1154 upsert: a marker-only body writes nothing" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A body missing its final newline still flips.
printf '%s\n%s' "$S1154_MARK" '**Status:** 🚀 Reviewing' > "$S1154_ROOT/nonewline.md"
s1154_seed "$S1154_ROOT/nonewline.md"
assert_eq "#1154 upsert: a body with no trailing newline still flips" "1/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# The marker present but NOT at the start of the body: workpad.py's scan matches a
# body that STARTS WITH the marker, so this is a clean absence for this run.
printf '%s\n' '# PRFlow Review' "$S1154_MARK" '**Status:** 🚀 Reviewing' > "$S1154_ROOT/marker-line2.md"
s1154_seed "$S1154_ROOT/marker-line2.md"
assert_eq "#1154 upsert: a marker below line 1 does not resolve, so this run creates its own comment" "0/1" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A comment carrying THIS run's key in the superseded namespace is still this run's
# own comment: workpad.py resolves both spellings per record (issue #1003). So the
# upsert must FLIP it, not create a duplicate beside it — the create arm must not
# turn the rename boundary into a second comment on every pre-rename progress record.
printf '%s\n' '<!-- devflow:review-progress run=RUN1154-1 -->' '**Status:** 🚀 Reviewing' > "$S1154_ROOT/superseded.md"
s1154_seed "$S1154_ROOT/superseded.md"
assert_eq "#1154 upsert: this run's key in the superseded namespace resolves as its own comment — flipped, not duplicated" "1/0" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"
# A DIFFERENT run's key in that same superseded namespace is still a foreign comment.
printf '%s\n' '<!-- devflow:review-progress run=OTHERRUN-9 -->' '**Status:** 🚀 Reviewing' > "$S1154_ROOT/superseded-foreign.md"
s1154_seed "$S1154_ROOT/superseded-foreign.md"
assert_eq "#1154 upsert: another run's key in the superseded namespace stays foreign — untouched, own comment created" "0/1" \
  "$(s1154_run 55 "$S1154_MARK" 'job died' >/dev/null; s1154_writes)"

# ════════════════════════════════════════════════════════════════════════════
# #1174 — the out-of-job review finalizer's command-job ARM selector, and the
# idempotency of the flip it reuses.
# ════════════════════════════════════════════════════════════════════════════
# Every review post-run handler used to be an always() step inside the `command`
# job, so a runner death silenced all of them. devflow.yml's new `review_finalize`
# job survives that loss and decides what to do from `needs.command.result`. That
# JOB-level arm selection is a branch chain the suite must be able to catch
# defeated (CLAUDE.md's inline-shell-extraction convention), so it lives in
# scripts/describe-command-job-arm.sh and is driven here arm-by-arm and for arm
# order — a DISTINCT decision from describe-dead-run-cause.sh, which it must not
# duplicate.
S1174_ARM="$LIB/../scripts/describe-command-job-arm.sh"

# T1 — every arm. The three-way partition IS the contract: a healthy job produces
# nothing, a cancellation is named as such, and every non-report shape leaves the
# dead-run record.
assert_eq "#1174 arm: a successful command job is completed-normally" \
  "completed-normally" "$(bash "$S1174_ARM" success)"
assert_eq "#1174 arm: a cancelled command job is cancelled" \
  "cancelled" "$(bash "$S1174_ARM" cancelled)"
assert_eq "#1174 arm: a failed command job did-not-report" \
  "did-not-report" "$(bash "$S1174_ARM" failure)"
assert_eq "#1174 arm: a skipped command job did-not-report" \
  "did-not-report" "$(bash "$S1174_ARM" skipped)"
# A runner-death job leaves an EMPTY result — the exact case this issue exists for
# — and any unforeseen token is a did-not-report residual, never silently dropped.
assert_eq "#1174 arm: an empty result (the runner-death shape) did-not-report" \
  "did-not-report" "$(bash "$S1174_ARM" '')"
assert_eq "#1174 arm: an absent argument did-not-report" \
  "did-not-report" "$(bash "$S1174_ARM")"
assert_eq "#1174 arm: an unforeseen token is a did-not-report residual" \
  "did-not-report" "$(bash "$S1174_ARM" neutralized)"
# The three arms are three DISTINCT tokens, or the partition collapses.
assert_eq "#1174 arm: the three command-job arms are three distinct tokens" "3" \
  "$( { bash "$S1174_ARM" success; bash "$S1174_ARM" cancelled; bash "$S1174_ARM" failure; } | sort -u | grep -c . || true)"
S1174_RC=0
bash "$S1174_ARM" >/dev/null 2>&1 || S1174_RC=$?
assert_eq "#1174 arm: always exits 0 (it can never change the finalizer job's result)" "0" "$S1174_RC"

# ARM ORDER. `success` is matched FIRST, before the did-not-report catch-all — a
# reordering that let the catch-all shadow it would post a dead-run banner on a
# healthy run. Prove the order is load-bearing with a disposable mutant: move the
# catch-all `*)` arm ahead of the `success)` arm and confirm a `success` input now
# grades wrong — i.e. a reordering is observable here, not something the arm
# assertions above would sail past.
S1174_MUT="$(mktemp -d)"
python3 - "$S1174_ARM" "$S1174_MUT/reordered.sh" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
# Rewrite the case so the did-not-report catch-all is tested first.
mutant = src.replace(
    'case "$COMMAND_RESULT" in\n'
    '  success)   printf \'%s\\n\' "completed-normally" ;;\n'
    '  cancelled) printf \'%s\\n\' "cancelled" ;;\n'
    '  *)         printf \'%s\\n\' "did-not-report" ;;\n'
    'esac',
    'case "$COMMAND_RESULT" in\n'
    '  *)         printf \'%s\\n\' "did-not-report" ;;\n'
    '  success)   printf \'%s\\n\' "completed-normally" ;;\n'
    '  cancelled) printf \'%s\\n\' "cancelled" ;;\n'
    'esac',
)
if mutant == src:
    sys.exit("mutation did not apply — the case shape drifted; update this test")
open(sys.argv[2], "w", encoding="utf-8").write(mutant)
PY
assert_eq "#1174 arm ORDER: the reordered mutant mis-grades a success (proving order is load-bearing)" \
  "did-not-report" "$(bash "$S1174_MUT/reordered.sh" success)"
assert_eq "#1174 arm ORDER: the canonical helper grades that same success correctly" \
  "completed-normally" "$(bash "$S1174_ARM" success)"
rm -rf "$S1174_MUT"

# T2 (AC2) — the finalizer reuses the idempotent flip helper, so applying the
# dead-run flip TWICE over the same progress comment leaves a SINGLE banner. The
# first pass flips the interim comment (one PATCH); feeding the flipped body back
# in must take the already-terminal arm and write nothing — no second banner.
s1154_seed "$S1154_ROOT/interim.md"
assert_eq "#1174 T2: the finalizer's first flip PATCHes exactly once" "1/0" \
  "$(s1154_run 55 "$S1154_MARK" 'the review command job did not report (needs.command.result=failure)' >/dev/null; s1154_writes)"
cp "$S1154_STATE/patched-body" "$S1154_ROOT/flipped-once.md"
s1154_seed "$S1154_ROOT/flipped-once.md"
assert_eq "#1174 T2: a second flip over the same comment stacks NO second banner (writes nothing)" "0/0" \
  "$(s1154_run 55 "$S1154_MARK" 'the review command job did not report (needs.command.result=failure)' >/dev/null; s1154_writes)"
assert_eq "#1174 T2: the twice-flipped body carries exactly one terminal Status line" "1" \
  "$(grep -cF '**Status:** ❌ Review failed' "$S1154_ROOT/flipped-once.md" || true)"

rm -rf "$S1154_ROOT"

# ── devflow.yml wiring, executed rather than grepped. Extract the shipped step's
# own shell between its BEGIN/END markers and run it against recording helpers, so
# the command screen, the cause-helper resolution and its degraded arm are driven
# as real branches — the same extraction the #1054 diagnosis block above uses.
S1154_WF="$(mktemp -d)"
mkdir -p "$S1154_WF/.prflow/vendor/prflow/scripts"
python3 - "$RDWF" "$S1154_WF/upsert-block.sh" <<'PY'
import sys
import textwrap

text = open(sys.argv[1], encoding="utf-8").read()
begin = text.index("          # dead-run review-progress upsert BEGIN")
end = text.index("          # dead-run review-progress upsert END", begin)
block = text[begin:end].splitlines()[1:]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("set -euo pipefail\n")
    handle.write(textwrap.dedent("\n".join(block)))
    handle.write("\n")
PY
cat > "$S1154_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh" <<'SH'
#!/usr/bin/env bash
printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$S1154_WF_RECORD"
exit 0
SH
chmod +x "$S1154_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh"
cp "$S1154_CAUSE" "$S1154_WF/.prflow/vendor/prflow/scripts/describe-dead-run-cause.sh"
S1154_WF_RECORD="$S1154_WF/record"
s1154_wf() {  # <command> <claude-outcome> <engine-is-error> [context-number]
  ( cd "$S1154_WF" && COMMAND="$1" CLAUDE_OUTCOME="$2" ENGINE_ERROR="$3" \
      CONTEXT_NUMBER="${4-7}" REPO=o/r GH_TOKEN=secret \
      GITHUB_RUN_ID=1154 GITHUB_RUN_ATTEMPT=2 S1154_WF_RECORD="$S1154_WF_RECORD" \
      bash "$S1154_WF/upsert-block.sh" )
}

# The reported mode: a review-and-fix run whose step exited cleanly with no engine
# error. The pre-#1154 gate skipped this entirely; the step must now fire and name it.
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review-and-fix 7' success false >/dev/null
assert_eq "#1154 wiring: a clean-exit review-and-fix run reaches the upsert helper with this run's marker and cause" \
  "7|<!-- prflow:review-progress run=1154-2 -->|claude step success but the run wrote no verdict (engine reported no error)" \
  "$(sed -n '1p' "$S1154_WF_RECORD")"
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review 7' success true >/dev/null
assert_eq "#1154 wiring: an engine-error run is named as such by the helper the workflow calls" \
  "review engine ended with an error (is_error)" "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/^.*|//')"
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review 7' cancelled false >/dev/null
assert_eq "#1154 wiring: a cancelled run still reaches the upsert helper" "claude step cancelled" \
  "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/^.*|//')"
: > "$S1154_WF_RECORD"
s1154_wf '/devflow:review-and-fix 7' failure false >/dev/null
assert_eq "#1154 wiring: the transitional /devflow: command spelling is accepted" "1" \
  "$(grep -c . "$S1154_WF_RECORD" || true)"

# ── Which THREAD the upsert writes to. The command carries its own target number,
# and that is the thread the engine seeded its progress comment on — not always the
# thread the triggering comment sits on. While the handler was flip-only a mismatch
# was a harmless no-op; now that a confirmed absence WRITES, addressing the event's
# own number would post a '❌ Review failed' comment on a thread that never had a
# review. The command's number must win.
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review 42' success false 10 >/dev/null
assert_eq "#1154 wiring: the command's own target number wins over a differing event number" "42" \
  "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/|.*//')"
# With no number on the command, the event's own number is the fallback.
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review' success false 10 >/dev/null
assert_eq "#1154 wiring: a command carrying no number falls back to the event's own" "10" \
  "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/|.*//')"
# A non-numeric trailing token is not a target either.
: > "$S1154_WF_RECORD"
s1154_wf '/prflow:review-and-fix HEAD' success false 10 >/dev/null
assert_eq "#1154 wiring: a non-numeric trailing token falls back to the event's own number" "10" \
  "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/|.*//')"

# The command screen. Now that a clean absence WRITES, a command that never seeds a
# progress comment must be screened out, or an ungated step would post a spurious
# "Review failed" comment on an unrelated run.
: > "$S1154_WF_RECORD"
S1154_WF_OUT="$(s1154_wf '/prflow:pr-description 7' success false)"
assert_eq "#1154 wiring: a pr-description run never reaches the upsert helper" "0" \
  "$(grep -c . "$S1154_WF_RECORD" || true)"
assert_eq "#1154 wiring: the screened-out command says so rather than failing silently" "1" \
  "$(grep -cF 'seeds no review-progress comment' <<<"$S1154_WF_OUT" || true)"
: > "$S1154_WF_RECORD"
s1154_wf '' success false >/dev/null
assert_eq "#1154 wiring: an empty command is screened out too" "0" \
  "$(grep -c . "$S1154_WF_RECORD" || true)"
# No issue/PR number on the event: nothing to write, and that arm fires first.
: > "$S1154_WF_RECORD"
S1154_WF_OUT="$(s1154_wf '/prflow:review 7' success false '')"
assert_eq "#1154 wiring: an event with no issue/PR number never reaches the upsert helper" "0" \
  "$(grep -c . "$S1154_WF_RECORD" || true)"
assert_eq "#1154 wiring: the no-number arm emits its own notice" "1" \
  "$(grep -cF 'no issue/PR number on this event' <<<"$S1154_WF_OUT" || true)"

# Consumer skew: an installed devflow.yml whose vendored plugin pin predates the
# cause helper must DEGRADE (warn, undifferentiated cause) rather than fail the step.
rm -f "$S1154_WF/.prflow/vendor/prflow/scripts/describe-dead-run-cause.sh"
: > "$S1154_WF_RECORD"
S1154_WF_RC=0
S1154_WF_OUT="$(s1154_wf '/prflow:review 7' success false)" || S1154_WF_RC=$?
assert_eq "#1154 wiring: an absent cause helper does not fail the step" "0" "$S1154_WF_RC"
assert_eq "#1154 wiring: an absent cause helper warns instead of failing silently" "1" \
  "$(grep -cF 'describe-dead-run-cause.sh absent' <<<"$S1154_WF_OUT" || true)"
assert_eq "#1154 wiring: the degraded cause still names both observables" \
  "claude step success (engine is_error=false)" "$(sed -n '1p' "$S1154_WF_RECORD" | sed 's/^.*|//')"
# An absent FLIP helper degrades the same way — the upsert is best-effort end to end.
rm -f "$S1154_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh"
S1154_WF_RC=0
S1154_WF_OUT="$(s1154_wf '/prflow:review 7' success false)" || S1154_WF_RC=$?
assert_eq "#1154 wiring: an absent upsert helper does not fail the step either" "0" "$S1154_WF_RC"
assert_eq "#1154 wiring: an absent upsert helper warns" "1" \
  "$(grep -cF 'flip-review-progress-failed.sh absent' <<<"$S1154_WF_OUT" || true)"

rm -rf "$S1154_WF"

# ── devflow.yml wiring, executed rather than grepped (#1174). The review_finalize
# job's own step body selects branches AND composes user-facing message text — the
# exact shape CLAUDE.md's inline-shell-extraction convention governs — so extract
# the shipped block between its BEGIN/END markers and run it against recording
# helper stubs. Driving the real block is what catches a reordered CAUSE arm, a
# TARGET_NUMBER/CONTEXT_NUMBER mix-up, an inverted SUPPRESS_FLIP, or a swapped
# verdict-helper arg — none of which a pin on a message literal can see.
S1174_WF="$(mktemp -d)"
mkdir -p "$S1174_WF/.prflow/vendor/prflow/scripts"
python3 - "$RDWF" "$S1174_WF/finalizer-block.sh" <<'PY'
import sys
import textwrap

text = open(sys.argv[1], encoding="utf-8").read()
begin = text.index("          # review-finalizer BEGIN")
end = text.index("          # review-finalizer END", begin)
block = text[begin:end].splitlines()[1:]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    # Match the SHIPPED execution environment exactly, errexit included. The step
    # carries no `shell:` key, so Actions runs it under its default `bash -e {0}`,
    # and the step's own first line adds `set -uo pipefail` on top — net -e -u
    # -o pipefail. Dropping -e here would run the block under weaker options than
    # production and hide an abort this harness exists to catch.
    handle.write("set -euo pipefail\n")
    handle.write(textwrap.dedent("\n".join(block)))
    handle.write("\n")
PY
# The two decision helpers are the REAL scripts — the block's job is to route to
# them correctly, so stubbing them would hide a mis-wired call.
cp "$LIB/../scripts/describe-command-job-arm.sh" "$S1174_WF/.prflow/vendor/prflow/scripts/describe-command-job-arm.sh"
cp "$S1154_CAUSE" "$S1174_WF/.prflow/vendor/prflow/scripts/describe-dead-run-cause.sh"
# Recording flip stub: writes its args, so "the banner was written / was not
# written" and the composed CAUSE text are both proven rather than assumed.
cat > "$S1174_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh" <<'SH'
#!/usr/bin/env bash
printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$S1174_WF_RECORD"
exit 0
SH
chmod +x "$S1174_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh"
# Controllable verdict-presence stub: echoes $S1174_FAKE_VERDICT and RECORDS its
# positional args, so the suppress-vs-write selection is driven from both sides and
# the <repo> <target_number> <engine_is_error> arg ORDER is asserted — a swapped or
# dropped arg in the workflow would otherwise stay green, the real helper's own
# tests proving the helper and never its caller.
cat > "$S1174_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$S1174_WF_ARGS"
printf '%s\n' "${S1174_FAKE_VERDICT:-absent}"
exit 0
SH
chmod +x "$S1174_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh"
S1174_WF_RECORD="$S1174_WF/record"
S1174_WF_ARGS="$S1174_WF/verdict-args"
: > "$S1174_WF_RECORD"; : > "$S1174_WF_ARGS"
s1174_wf() {  # <command-result> <command> <claude-outcome> <engine-error> [context-number] [fake-verdict]
  ( cd "$S1174_WF" && COMMAND_RESULT="$1" COMMAND="$2" CLAUDE_OUTCOME="$3" ENGINE_ERROR="$4" \
      CONTEXT_NUMBER="${5-55}" S1174_FAKE_VERDICT="${6-absent}" REPO=o/r GH_TOKEN=secret \
      GITHUB_RUN_ID=1174 GITHUB_RUN_ATTEMPT=3 \
      S1174_WF_RECORD="$S1174_WF_RECORD" S1174_WF_ARGS="$S1174_WF_ARGS" \
      bash "$S1174_WF/finalizer-block.sh" )
}
s1174_cause() { sed -n '1p' "$S1174_WF_RECORD" | sed 's/^.*|//'; }

# ── The completed-normally no-op (AC3/T3). A healthy command job already ran its
# own in-job handlers, so the finalizer must produce NOTHING — no verdict query,
# no banner, no second comment.
: > "$S1174_WF_RECORD"; : > "$S1174_WF_ARGS"
S1174_WF_OUT="$(s1174_wf success '/prflow:review 55' success false)"
assert_eq "#1174 wiring: a completed-normally command job never reaches the flip helper" "0" \
  "$(grep -c . "$S1174_WF_RECORD" || true)"
assert_eq "#1174 wiring: a completed-normally command job never even asks the verdict oracle" "0" \
  "$(grep -c . "$S1174_WF_ARGS" || true)"
assert_eq "#1174 wiring: the completed-normally arm says so rather than exiting silently" "1" \
  "$(grep -cF 'completed normally' <<<"$S1174_WF_OUT" || true)"

# ── CAUSE arm 1: cancelled. Named as a cancellation, not lumped in with a failure.
: > "$S1174_WF_RECORD"
s1174_wf cancelled '/prflow:review 55' '' '' >/dev/null
assert_eq "#1174 wiring: a cancelled command job composes the cancellation cause" \
  "the review run was cancelled (needs.command.result=cancelled); no verdict was recorded" "$(s1174_cause)"
# The cancelled arm is tested BEFORE the promoted-outputs arm, so a cancelled job
# whose outputs DID survive is still named a cancellation — reordering the ladder
# would silently reroute it through describe-dead-run-cause.sh instead.
: > "$S1174_WF_RECORD"
s1174_wf cancelled '/prflow:review 55' success true >/dev/null
assert_eq "#1174 wiring: cancelled wins over surviving promoted outputs (CAUSE arm order)" \
  "the review run was cancelled (needs.command.result=cancelled); no verdict was recorded" "$(s1174_cause)"

# ── CAUSE arm 2: the ALIVE failure, where the promoted outputs survived. The block
# must route to describe-dead-run-cause.sh and use its richer diagnosis verbatim.
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review 55' success true >/dev/null
assert_eq "#1174 wiring: an alive failure with surviving outputs names the engine error via the cause helper" \
  "review engine ended with an error (is_error)" "$(s1174_cause)"
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review 55' failure false >/dev/null
assert_eq "#1174 wiring: an alive failure routes each promoted outcome through the cause helper" \
  "claude step failure" "$(s1174_cause)"

# ── CAUSE arm 3: the runner-DEATH path (AC4). A dead job emits no outputs, so the
# promoted operands read EMPTY and the message must say plainly that the job did
# not report — never guess a cause from an unavailable operand.
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review 55' '' '' >/dev/null
assert_eq "#1174 wiring: empty promoted outputs take the generic did-not-report arm naming the result" \
  "the review command job did not report (needs.command.result=failure); the job or its runner was lost before it could record a verdict" \
  "$(s1174_cause)"
# An empty result — the job that never started at all — renders `unavailable`
# rather than an empty parenthetical.
: > "$S1174_WF_RECORD"
s1174_wf '' '/prflow:review 55' '' '' >/dev/null
assert_eq "#1174 wiring: an empty command-job result renders 'unavailable', never a blank" \
  "the review command job did not report (needs.command.result=unavailable); the job or its runner was lost before it could record a verdict" \
  "$(s1174_cause)"
# The three CAUSE arms are three DISTINCT messages, or the ladder has collapsed.
assert_eq "#1174 wiring: the three CAUSE arms compose three distinct messages" "3" \
  "$( : > "$S1174_WF_RECORD"; s1174_wf cancelled '/prflow:review 55' '' '' >/dev/null
     s1174_wf failure '/prflow:review 55' success true >/dev/null
     s1174_wf failure '/prflow:review 55' '' '' >/dev/null
     sed 's/^.*|//' "$S1174_WF_RECORD" | sort -u | grep -c . || true)"

# ── TARGET_NUMBER: where the write LANDS. The resolved command carries its own
# target number and that is the thread the engine seeded its progress comment on;
# addressing the event's number instead would banner an unrelated thread.
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review 42' '' '' 10 >/dev/null
assert_eq "#1174 wiring: the command's own trailing number wins over a differing event number" "42" \
  "$(sed -n '1p' "$S1174_WF_RECORD" | sed 's/|.*//')"
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review' '' '' 10 >/dev/null
assert_eq "#1174 wiring: a command carrying no number falls back to the event's own" "10" \
  "$(sed -n '1p' "$S1174_WF_RECORD" | sed 's/|.*//')"
: > "$S1174_WF_RECORD"
s1174_wf failure '/prflow:review-and-fix HEAD' '' '' 10 >/dev/null
assert_eq "#1174 wiring: a non-numeric trailing token falls back to the event's own number" "10" \
  "$(sed -n '1p' "$S1174_WF_RECORD" | sed 's/|.*//')"
: > "$S1174_WF_RECORD"
s1174_wf failure '' '' '' 10 >/dev/null
assert_eq "#1174 wiring: an empty command falls back to the event's own number" "10" \
  "$(sed -n '1p' "$S1174_WF_RECORD" | sed 's/|.*//')"
# No number on the event at all: nothing to finalize, and that guard fires before
# any verdict query or write.
: > "$S1174_WF_RECORD"; : > "$S1174_WF_ARGS"
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '' '')"
assert_eq "#1174 wiring: an event with no issue/PR number writes nothing" "0" \
  "$(grep -c . "$S1174_WF_RECORD" || true)"
assert_eq "#1174 wiring: the no-number arm emits its own notice" "1" \
  "$(grep -cF 'no issue/PR number on this event' <<<"$S1174_WF_OUT" || true)"

# ── SUPPRESS_FLIP: a verdict that WAS posted must never draw a "no verdict"
# banner beside it, and an absent verdict must always keep the banner.
: > "$S1174_WF_RECORD"; : > "$S1174_WF_ARGS"
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '' 55 present)"
assert_eq "#1174 wiring: a present verdict suppresses the flip — the flip helper is never reached" "0" \
  "$(grep -c . "$S1174_WF_RECORD" || true)"
assert_eq "#1174 wiring: the suppressed path emits its reach record" "1" \
  "$(grep -cF 'WAS posted' <<<"$S1174_WF_OUT" || true)"
: > "$S1174_WF_RECORD"
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '' 55 absent)"
assert_eq "#1174 wiring: an absent verdict reaches the flip with this run's own marker" \
  "55|<!-- prflow:review-progress run=1174-3 -->" \
  "$(sed -n '1p' "$S1174_WF_RECORD" | sed 's/|[^|]*$//')"
assert_eq "#1174 wiring: the absent-verdict path records the absence" "1" \
  "$(grep -cF 'was found; recording the dead-run state' <<<"$S1174_WF_OUT" || true)"
# The verdict oracle is called with <repo> <target_number> <engine_is_error> in
# that order, and with the TARGET number (not the event's) — a swapped or dropped
# arg here silently breaks the real gate while every other assertion stays green.
: > "$S1174_WF_ARGS"
s1174_wf failure '/prflow:review 42' success true 10 absent >/dev/null
assert_eq "#1174 wiring: the gate calls the verdict oracle with repo, target number, engine-error in that order" \
  "o/r 42 true" "$(sed -n '1p' "$S1174_WF_ARGS")"

# ── Degraded arms. A consumer whose vendored pin predates a helper must DEGRADE
# loudly (warn, exit 0) — never fail the finalizer and never silently drop the
# record. Removed one at a time, innermost first, so each arm is reached.
rm -f "$S1174_WF/.prflow/vendor/prflow/scripts/describe-dead-run-cause.sh"
: > "$S1174_WF_RECORD"
S1174_WF_RC=0
s1174_wf failure '/prflow:review 55' success true >/dev/null || S1174_WF_RC=$?
assert_eq "#1174 wiring: an absent cause helper does not fail the step" "0" "$S1174_WF_RC"
assert_eq "#1174 wiring: the degraded cause still names both promoted observables" \
  "the review command job failed (claude step success, engine is_error=true)" "$(s1174_cause)"

rm -f "$S1174_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh"
: > "$S1174_WF_RECORD"
S1174_WF_RC=0
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '' 55 present)" || S1174_WF_RC=$?
assert_eq "#1174 wiring: an absent verdict oracle does not fail the step" "0" "$S1174_WF_RC"
assert_eq "#1174 wiring: an absent verdict oracle warns instead of suppressing" "1" \
  "$(grep -cF 'dead-run-verdict-present.sh absent' <<<"$S1174_WF_OUT" || true)"
assert_eq "#1174 wiring: with the verdict oracle absent the flip is still reached (fail toward the banner)" "1" \
  "$(grep -c . "$S1174_WF_RECORD" || true)"

rm -f "$S1174_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh"
S1174_WF_RC=0
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '')" || S1174_WF_RC=$?
assert_eq "#1174 wiring: an absent flip helper does not fail the step either" "0" "$S1174_WF_RC"
assert_eq "#1174 wiring: an absent flip helper warns" "1" \
  "$(grep -cF 'flip-review-progress-failed.sh absent' <<<"$S1174_WF_OUT" || true)"

# The arm helper is the FIRST resolution; without it the block cannot decide
# anything, so it warns and produces no record at all rather than guessing an arm.
rm -f "$S1174_WF/.prflow/vendor/prflow/scripts/describe-command-job-arm.sh"
: > "$S1174_WF_ARGS"
S1174_WF_RC=0
S1174_WF_OUT="$(s1174_wf failure '/prflow:review 55' '' '')" || S1174_WF_RC=$?
assert_eq "#1174 wiring: an absent arm helper does not fail the step" "0" "$S1174_WF_RC"
assert_eq "#1174 wiring: an absent arm helper warns naming the upgrade remedy" "1" \
  "$(grep -cF 'describe-command-job-arm.sh absent' <<<"$S1174_WF_OUT" || true)"
assert_eq "#1174 wiring: an absent arm helper asks the verdict oracle nothing" "0" \
  "$(grep -c . "$S1174_WF_ARGS" || true)"

rm -rf "$S1174_WF"

# ────────────────────────────────────────────────────────────────────────────
echo "dead-run verdict-presence gate: dead-run-verdict-present.sh + devflow.yml wiring (#1172)"
# ────────────────────────────────────────────────────────────────────────────
# The dead-run backstop wrote "the run wrote no verdict" beside reviews that DID
# post one (PR #1169 run 30772170838: APPROVED at 23:31:06, banner 19s later),
# because the flip step asked no verdict question at all. Issue #1172 wires
# scripts/dead-run-verdict-present.sh — which reuses the HEAD-scoped, fail-closed
# derive-review-verdict.sh — into the flip step's gate. Everything below drives
# real processes: the presence helper end to end against a stubbed gh over every
# arm (AC5, both-channels + truly-absent), and the shipped workflow block against
# a recording flip stub so the suppress/write selection is executed, not grepped.

S1172_DRVP="$LIB/../scripts/dead-run-verdict-present.sh"
S1172_ROOT="$(mktemp -d)"
S1172_STATE="$S1172_ROOT/state"
mkdir -p "$S1172_STATE"
S1172_HEAD='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
# One gh stub serving the three endpoints the gate touches: the PR head sha, the
# reviews API, and the issue comments. Order matters — the reviews/comments paths
# are more specific than the bare pull path, so they are matched first.
cat > "$S1172_ROOT/gh" <<'STUB'
#!/usr/bin/env bash
j="$*"
case "$j" in
  *"/reviews"*)  cat "$S1172_STATE/reviews.json"; exit 0 ;;
  *"/comments"*) cat "$S1172_STATE/comments.json"; exit 0 ;;
  *"/pulls/"*)
    # Serve the PR object as realistic JSON and HONOR the --jq filter the caller passed,
    # so the helper's `--jq '.head.sha'` extraction expression is actually exercised — a
    # wrong path (.head.ref, a typo) yields empty here and the gate goes `absent`, rather
    # than being masked by a bare-sha echo that ignores the filter entirely.
    _f='.'; _prev=
    for _a in "$@"; do [ "$_prev" = "--jq" ] && _f="$_a"; _prev="$_a"; done
    jq -r "$_f" "$S1172_STATE/pull.json"
    exit 0 ;;
esac
echo '[]'
STUB
chmod +x "$S1172_ROOT/gh"
# Seed helpers. reviews/comments default to empty; an override sets only what it needs.
# The PR object is seeded as {"head":{"sha":<arg>}} so the head-sha lookup runs the real
# --jq path against realistic JSON (empty arg → {"head":{"sha":""}} → empty sha → absent).
s1172_seed() {  # <head-sha-or-empty>
  jq -n --arg s "$1" '{head:{sha:$s}}' > "$S1172_STATE/pull.json"
  printf '[]' > "$S1172_STATE/reviews.json"
  printf '[]' > "$S1172_STATE/comments.json"
}
s1172_review() {  # <state> — a single review on HEAD with that reviews-API state
  jq -n --arg h "$S1172_HEAD" --arg s "$1" \
    '[{"commit_id":$h,"state":$s,"body":""}]' > "$S1172_STATE/reviews.json"
}
s1172_progress_comment() {  # <verdict> — this run's run-keyed progress comment carrying the verdict marker
  jq -n --arg h "$S1172_HEAD" --arg v "$1" \
    '[{"body": ("<!-- prflow:review-progress run=RUN1172-1 -->\n<!-- prflow:review-verdict head=" + $h + " verdict=" + $v + " -->\nfull report")}]' \
    > "$S1172_STATE/comments.json"
}
s1172_gate() {  # <engine-is-error> -> prints present/absent
  env DEVFLOW_GH="$S1172_ROOT/gh" S1172_STATE="$S1172_STATE" GITHUB_RUN_ID=RUN1172 \
    bash "$S1172_DRVP" o/r 55 "$1" 2>/dev/null
}

# ── Channel 1: the formal review. An APPROVED review on HEAD is a verdict, so the
# banner is suppressed.
s1172_seed "$S1172_HEAD"; s1172_review APPROVED
assert_eq "#1172 gate: an APPROVED formal review on HEAD reports the verdict present" "present" "$(s1172_gate false)"
# A REJECT (CHANGES_REQUESTED) is equally a verdict — a rejected run is not verdict-less.
s1172_seed "$S1172_HEAD"; s1172_review CHANGES_REQUESTED
assert_eq "#1172 gate: a CHANGES_REQUESTED review on HEAD is a verdict too (present)" "present" "$(s1172_gate false)"

# ── Channel 2 (the both-channels case AC5 names): NO HEAD review, but this run's
# run-keyed progress comment carries the verdict marker — the shape the review
# POST-refused comment-fallback channel leaves. The gate must still see it.
s1172_seed "$S1172_HEAD"; s1172_progress_comment APPROVE
assert_eq "#1172 gate: a verdict reachable ONLY via this run's run-keyed progress comment is present (both-channels)" \
  "present" "$(s1172_gate false)"

# ── Truly absent (AC5): no HEAD review and no run-keyed verdict comment — the
# genuinely verdict-less run the banner exists for. The gate must NOT suppress it.
s1172_seed "$S1172_HEAD"
assert_eq "#1172 gate: a genuinely verdict-less run reports absent (the banner still writes — AC4)" "absent" "$(s1172_gate false)"

# ── Fail-closed operands, each independently → absent (banner still writes).
# An unresolvable HEAD sha (an issue-number target / non-PR event) even with a
# review present: the deriver cannot scope the verdict to HEAD, so absent.
s1172_seed ""; s1172_review APPROVED
assert_eq "#1172 gate: an unresolvable HEAD sha fails closed to absent even with a review present" "absent" "$(s1172_gate false)"
# An engine-error run short-circuits to `absent` — the wrapper returns before invoking
# the deriver at all (mirroring the deriver's own step-1 incomplete short-circuit before
# any reviews query) — the deliberately-scoped #1172 caveat: an engine-error run always banners.
s1172_seed "$S1172_HEAD"; s1172_review APPROVED
assert_eq "#1172 gate: an engine-error run is absent (banners) even with a HEAD verdict — the scoped caveat" "absent" "$(s1172_gate true)"

# ── Always exits 0 (it runs under the flip step's always()).
s1172_seed "$S1172_HEAD"; s1172_review APPROVED
S1172_RC=0; s1172_gate false >/dev/null 2>&1 || S1172_RC=$?
assert_eq "#1172 gate: always exits 0" "0" "$S1172_RC"

# ── Partial-copy degradation: this file present without its sibling deriver must
# fail toward the banner (absent) and say so, never suppress on an unestablished
# verdict.
S1172_ORPHAN="$(mktemp -d)"
cp "$S1172_DRVP" "$S1172_ORPHAN/dead-run-verdict-present.sh"
S1172_ORPHAN_OUT="$(env DEVFLOW_GH="$S1172_ROOT/gh" GITHUB_RUN_ID=RUN1172 \
  bash "$S1172_ORPHAN/dead-run-verdict-present.sh" o/r 55 false 2>&1)"
assert_eq "#1172 gate: a missing sibling deriver degrades to absent (banner not suppressed)" "yes" \
  "$(printf '%s\n' "$S1172_ORPHAN_OUT" | grep -qx 'absent' && echo yes || echo no)"
assert_eq "#1172 gate: the missing-sibling degradation names the cause on stderr" "yes" \
  "$(printf '%s\n' "$S1172_ORPHAN_OUT" | grep -qF 'derive-review-verdict.sh missing' && echo yes || echo no)"
rm -rf "$S1172_ORPHAN"
rm -rf "$S1172_ROOT"

# ── devflow.yml wiring, executed rather than grepped. Extract the shipped upsert
# block and run it against a recording flip stub and a controllable verdict-presence
# stub, so the suppress-vs-write selection and its degraded arm are real branches.
S1172_WF="$(mktemp -d)"
mkdir -p "$S1172_WF/.prflow/vendor/prflow/scripts"
python3 - "$RDWF" "$S1172_WF/upsert-block.sh" <<'PY'
import sys
import textwrap

text = open(sys.argv[1], encoding="utf-8").read()
begin = text.index("          # dead-run review-progress upsert BEGIN")
end = text.index("          # dead-run review-progress upsert END", begin)
block = text[begin:end].splitlines()[1:]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("set -euo pipefail\n")
    handle.write(textwrap.dedent("\n".join(block)))
    handle.write("\n")
PY
# Recording flip stub: writes its args so a "flip reached" / "flip not reached"
# assertion is proven, not assumed.
cat > "$S1172_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh" <<'SH'
#!/usr/bin/env bash
printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$S1172_WF_RECORD"
exit 0
SH
chmod +x "$S1172_WF/.prflow/vendor/prflow/scripts/flip-review-progress-failed.sh"
# Controllable verdict-presence stub: echoes $S1172_FAKE_VERDICT (present/absent) and
# RECORDS its positional args, so the wiring test can assert the workflow passes them in
# the helper's <repo> <pr_number> <engine_is_error> order (a swapped/dropped arg in the
# workflow gate would otherwise stay green — the real helper's own tests call it correctly,
# which proves the helper, never the caller).
cat > "$S1172_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$S1172_WF_ARGS"
printf '%s\n' "${S1172_FAKE_VERDICT:-absent}"
exit 0
SH
chmod +x "$S1172_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh"
cp "$S1154_CAUSE" "$S1172_WF/.prflow/vendor/prflow/scripts/describe-dead-run-cause.sh"
# The diagnosis dispatcher is invoked after the upsert; stub it to a no-op so the
# block runs without needing the real one.
cat > "$S1172_WF/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$S1172_WF/.prflow/vendor/prflow/scripts/run-review-progress-diagnosis.sh"
S1172_WF_RECORD="$S1172_WF/record"
S1172_WF_ARGS="$S1172_WF/verdict-args"
s1172_wf() {  # <fake-verdict> -> runs the block on a clean-exit review run, prints stdout
  ( cd "$S1172_WF" && COMMAND='/prflow:review 55' CLAUDE_OUTCOME=success ENGINE_ERROR=false \
      CONTEXT_NUMBER=55 REPO=o/r GH_TOKEN=secret S1172_FAKE_VERDICT="$1" \
      GITHUB_RUN_ID=1172 GITHUB_RUN_ATTEMPT=1 S1172_WF_RECORD="$S1172_WF_RECORD" \
      S1172_WF_ARGS="$S1172_WF_ARGS" \
      bash "$S1172_WF/upsert-block.sh" )
}

# present → the flip helper is NEVER reached and the step says it suppressed.
: > "$S1172_WF_RECORD"; : > "$S1172_WF_ARGS"
S1172_WF_OUT="$(s1172_wf present)"
assert_eq "#1172 wiring: a present verdict suppresses the flip — the flip helper is never reached" "0" \
  "$(grep -c . "$S1172_WF_RECORD" || true)"
assert_eq "#1172 wiring: the suppressed path emits its own notice" "1" \
  "$(grep -cF 'suppressing the dead-run' <<<"$S1172_WF_OUT" || true)"
# The workflow passes the verdict helper its args in <repo> <pr_number> <engine_is_error>
# order — a swapped/dropped arg here would silently break the real gate while every other
# wiring assertion stayed green.
assert_eq "#1172 wiring: the gate calls the verdict helper with repo, target number, engine-error in that order" \
  "o/r 55 false" "$(sed -n '1p' "$S1172_WF_ARGS")"

# absent → the flip helper IS reached with this run's marker and cause (the banner writes).
: > "$S1172_WF_RECORD"
s1172_wf absent >/dev/null
assert_eq "#1172 wiring: an absent verdict reaches the flip helper with this run's marker and the no-verdict cause" \
  "55|<!-- prflow:review-progress run=1172-1 -->|claude step success but the run wrote no verdict (engine reported no error)" \
  "$(sed -n '1p' "$S1172_WF_RECORD")"

# A missing verdict-presence helper DEGRADES: warn, and still reach the flip (the
# banner must never be silently dropped on an unestablished verdict).
rm -f "$S1172_WF/.prflow/vendor/prflow/scripts/dead-run-verdict-present.sh"
: > "$S1172_WF_RECORD"
S1172_WF_OUT="$(s1172_wf present)"
assert_eq "#1172 wiring: an absent verdict-presence helper warns instead of suppressing" "1" \
  "$(grep -cF 'dead-run-verdict-present.sh absent' <<<"$S1172_WF_OUT" || true)"
assert_eq "#1172 wiring: with the presence helper absent the flip is still reached (fail toward the banner)" "1" \
  "$(grep -c . "$S1172_WF_RECORD" || true)"
rm -rf "$S1172_WF"

# ────────────────────────────────────────────────────────────────────────────
echo "stale-REJECT dismissal net: dismiss-stale-rejections-net.sh + devflow.yml wiring (#1175)"
# ────────────────────────────────────────────────────────────────────────────
# Phase 4.4's agent-run dismissal is the primary path; when the agent never reaches
# Phase 4.4 (the clean-exit failure mode issue #1156 records) a superseded REJECT stays
# the pull request's reviewDecision even after a fresh APPROVE. Issue #1175 adds the
# workflow-side net scripts/dismiss-stale-rejections-net.sh, which reuses the HEAD-scoped,
# fail-closed derive-review-verdict.sh and dispatches dismiss-stale-rejections.sh ONLY on
# a positively-determined APPROVE. Everything below drives real processes: the net helper
# end to end against a stubbed gh over every gate arm (AC4), and the shipped workflow block
# against a recording net stub so the annotate branch is executed, not grepped.

S1175_NET="$LIB/../scripts/dismiss-stale-rejections-net.sh"
S1175_ROOT="$(mktemp -d)"
S1175_STATE="$S1175_ROOT/state"
mkdir -p "$S1175_STATE"
S1175_HEAD='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
S1175_OLD='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
# One gh stub serving the endpoints the whole chain touches (deriver + dismisser): the
# PR head sha, the reviews API, the issue comments, and the dismissals PUT. It honors a
# --jq filter when one is passed (the dismisser uses `gh api --jq`; the deriver pipes raw
# reviews through its own jq), and RECORDS every dismissal so "dismissed" is proven, not
# assumed.
cat > "$S1175_ROOT/gh" <<'STUB'
#!/usr/bin/env bash
_f=''
_prev=
for _a in "$@"; do [ "$_prev" = "--jq" ] && _f="$_a"; _prev="$_a"; done
emit() { if [ -n "$_f" ]; then jq -r "$_f" "$1"; else cat "$1"; fi; }
j="$*"
case "$j" in
  *"/dismissals"*) echo "DISMISSED $*" >> "$S1175_STATE/dismissals.log"; exit "${S1175_DISMISS_PUT_RC:-0}" ;;
  *"/reviews"*)  emit "$S1175_STATE/reviews.json"; exit 0 ;;
  *"/comments"*) emit "$S1175_STATE/comments.json"; exit 0 ;;
  *"/pulls/"*)   emit "$S1175_STATE/pull.json"; exit 0 ;;
esac
echo '[]'
STUB
chmod +x "$S1175_ROOT/gh"
s1175_seed() {  # <head-sha-or-empty>
  jq -n --arg s "$1" '{head:{sha:$s}}' > "$S1175_STATE/pull.json"
  printf '[]' > "$S1175_STATE/reviews.json"
  printf '[]' > "$S1175_STATE/comments.json"
  : > "$S1175_STATE/dismissals.log"
}
# An APPROVED review on HEAD, plus a stale own-marker REJECT on an OLDER commit that the
# dismisser is licensed to clear.
s1175_approve_with_stale_reject() {
  jq -n --arg h "$S1175_HEAD" --arg o "$S1175_OLD" \
    '[{"id":11,"commit_id":$h,"state":"APPROVED","body":""},
      {"id":22,"commit_id":$o,"state":"CHANGES_REQUESTED","body":("<!-- prflow:review-verdict head="+$o+" verdict=REJECT -->")}]' \
    > "$S1175_STATE/reviews.json"
}
s1175_net() {  # <engine-is-error> -> prints the outcome token
  env DEVFLOW_GH="$S1175_ROOT/gh" S1175_STATE="$S1175_STATE" GITHUB_RUN_ID=RUN1175 \
    S1175_DISMISS_PUT_RC="${S1175_DISMISS_PUT_RC:-0}" \
    bash "$S1175_NET" o/r 55 "$1" 2>/dev/null
}
# An APPROVED review on HEAD (last, so the deriver reads approve) PLUS an own-marker
# REJECT on the CURRENT head — which the dismisser refuses as not-superseded (exit 3).
s1175_approve_with_unsupersedable_reject() {
  jq -n --arg h "$S1175_HEAD" \
    '[{"id":55,"commit_id":$h,"state":"CHANGES_REQUESTED","body":("<!-- prflow:review-verdict head="+$h+" verdict=REJECT -->")},
      {"id":56,"commit_id":$h,"state":"APPROVED","body":""}]' \
    > "$S1175_STATE/reviews.json"
}
s1175_dismissals() { awk 'END{print NR}' "$S1175_STATE/dismissals.log" 2>/dev/null || echo 0; }

# ── Arm 1 (the reason this net exists): a positively-determined APPROVE dismisses the
# superseded REJECT.
s1175_seed "$S1175_HEAD"; s1175_approve_with_stale_reject
assert_eq "#1175 net: a determined APPROVE dismisses the superseded REJECT" "dismissed" "$(s1175_net false)"
s1175_seed "$S1175_HEAD"; s1175_approve_with_stale_reject
s1175_net false >/dev/null
assert_eq "#1175 net: the determined-APPROVE arm actually issued the dismissal" "1" "$(s1175_dismissals)"

# ── Arm 2 (AC1/the defaulted-verdict arm AC4 names): a genuinely verdict-less run — the
# reviews/comments queries return nothing, so derive-review-verdict.sh defaults nothing
# and reports incomplete/false — REFUSES and dismisses nothing.
s1175_seed "$S1175_HEAD"
assert_eq "#1175 net: an undetermined verdict refuses (no dismissal on a defaulted verdict)" \
  "no-dismiss-undetermined" "$(s1175_net false)"
s1175_seed "$S1175_HEAD"; s1175_net false >/dev/null
assert_eq "#1175 net: the undetermined arm dismissed nothing" "0" "$(s1175_dismissals)"

# ── Arm 3 (AC3, the change-request must stand): a positively-determined REJECT on HEAD
# refuses — the net never clears a live block.
s1175_seed "$S1175_HEAD"
jq -n --arg h "$S1175_HEAD" '[{"id":33,"commit_id":$h,"state":"CHANGES_REQUESTED","body":""}]' > "$S1175_STATE/reviews.json"
assert_eq "#1175 net: a determined REJECT refuses (the change-request must stand)" \
  "no-dismiss-reject" "$(s1175_net false)"
assert_eq "#1175 net: the determined-REJECT arm dismissed nothing" "0" "$(s1175_dismissals)"

# ── Arm 4 (AC2, an API/engine failure → no dismissal): an engine-error run refuses even
# with an APPROVE on HEAD — derive-review-verdict.sh short-circuits to incomplete on
# ENGINE_ERROR=true, so the verdict is never positively determined.
s1175_seed "$S1175_HEAD"; s1175_approve_with_stale_reject
assert_eq "#1175 net: an engine-error run refuses even with a HEAD APPROVE (AC2)" \
  "no-dismiss-undetermined" "$(s1175_net true)"
assert_eq "#1175 net: the engine-error arm dismissed nothing" "0" "$(s1175_dismissals)"

# ── Arm 5 (AC2, an unresolvable HEAD sha): an issue-number target / non-PR event yields
# an empty head sha, which the deriver fails closed on — refuse, dismiss nothing.
s1175_seed ""; jq -n --arg h "$S1175_HEAD" '[{"id":44,"commit_id":$h,"state":"APPROVED","body":""}]' > "$S1175_STATE/reviews.json"
assert_eq "#1175 net: an unresolvable HEAD sha refuses even with an APPROVE present" \
  "no-dismiss-undetermined" "$(s1175_net false)"

# ── Exit-code→token mapping arms (the post-gate outcome tokens the deriver-gate arms
# above never reach): a determined APPROVE whose dismisser exits 3 (a REJECT it cannot
# show superseded — issue #1029) maps to `dismiss-refused`, and one whose dismissal PUT
# fails (dismisser exit 1) maps to `dismiss-failed`. Without these, a swapped `3)`/`*)`
# arm in the helper's exit-code case would ship green.
s1175_seed "$S1175_HEAD"; s1175_approve_with_unsupersedable_reject
assert_eq "#1175 net: a determined APPROVE whose REJECT is on the current head maps to dismiss-refused (dismisser exit 3)" \
  "dismiss-refused" "$(s1175_net false)"
assert_eq "#1175 net: the dismiss-refused arm dismissed nothing (the live REJECT stands)" "0" "$(s1175_dismissals)"

s1175_seed "$S1175_HEAD"; s1175_approve_with_stale_reject
assert_eq "#1175 net: a determined APPROVE whose dismissal PUT fails maps to dismiss-failed (dismisser exit 1)" \
  "dismiss-failed" "$(S1175_DISMISS_PUT_RC=1 s1175_net false)"

# ── Always exits 0 (it runs under the workflow step's always()).
s1175_seed "$S1175_HEAD"; s1175_approve_with_stale_reject
S1175_RC=0; s1175_net false >/dev/null 2>&1 || S1175_RC=$?
assert_eq "#1175 net: always exits 0" "0" "$S1175_RC"

# ── Partial-copy degradation: the net present without a required sibling must refuse
# (unavailable) and say so, never dismiss on an unestablished verdict. Two distinct
# partial-copy shapes, because the two sibling-existence checks fire in order and the
# first would otherwise mask the second:
#   (a) DERIVER absent (the net alone in an empty dir) — the first check fires.
S1175_ORPHAN="$(mktemp -d)"
cp "$S1175_NET" "$S1175_ORPHAN/dismiss-stale-rejections-net.sh"
S1175_ORPHAN_OUT="$(env DEVFLOW_GH="$S1175_ROOT/gh" GITHUB_RUN_ID=RUN1175 \
  bash "$S1175_ORPHAN/dismiss-stale-rejections-net.sh" o/r 55 false 2>&1)"
assert_eq "#1175 net: a missing deriver sibling degrades to unavailable (no dismissal)" "yes" \
  "$(printf '%s\n' "$S1175_ORPHAN_OUT" | grep -qx 'unavailable' && echo yes || echo no)"
assert_eq "#1175 net: the missing-deriver degradation names the cause on stderr" "yes" \
  "$(printf '%s\n' "$S1175_ORPHAN_OUT" | grep -qF 'derive-review-verdict.sh missing/unreadable' && echo yes || echo no)"
rm -rf "$S1175_ORPHAN"
#   (b) DERIVER present but DISMISSER absent — the SECOND check fires (the (a) shape
#   masks it, so a swapped/dropped dismisser check would ship green without this arm).
S1175_ORPHAN2="$(mktemp -d)"
cp "$S1175_NET" "$S1175_ORPHAN2/dismiss-stale-rejections-net.sh"
cp "$LIB/../scripts/derive-review-verdict.sh" "$S1175_ORPHAN2/derive-review-verdict.sh"
S1175_ORPHAN2_OUT="$(env DEVFLOW_GH="$S1175_ROOT/gh" GITHUB_RUN_ID=RUN1175 \
  bash "$S1175_ORPHAN2/dismiss-stale-rejections-net.sh" o/r 55 false 2>&1)"
assert_eq "#1175 net: a missing dismisser sibling (deriver present) degrades to unavailable" "yes" \
  "$(printf '%s\n' "$S1175_ORPHAN2_OUT" | grep -qx 'unavailable' && echo yes || echo no)"
assert_eq "#1175 net: the missing-dismisser degradation names the dismisser on stderr" "yes" \
  "$(printf '%s\n' "$S1175_ORPHAN2_OUT" | grep -qF 'dismiss-stale-rejections.sh missing/unreadable' && echo yes || echo no)"
rm -rf "$S1175_ORPHAN2"
rm -rf "$S1175_ROOT"

# ── devflow.yml wiring, executed rather than grepped. Extract the shipped net block and
# run it against a recording net stub, so the notice/warning annotate selection is a real
# branch and the args are passed in <repo> <pr_number> <engine_is_error> order.
S1175_WF="$(mktemp -d)"
mkdir -p "$S1175_WF/.prflow/vendor/prflow/scripts"
python3 - "$RDWF" "$S1175_WF/net-block.sh" <<'PY'
import sys
import textwrap

text = open(sys.argv[1], encoding="utf-8").read()
begin = text.index("          # stale-REJECT dismissal net BEGIN")
end = text.index("          # stale-REJECT dismissal net END", begin)
block = text[begin:end].splitlines()[1:]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("set -uo pipefail\n")
    handle.write(textwrap.dedent("\n".join(block)))
    handle.write("\n")
PY
# Controllable net stub: echoes $S1175_FAKE_TOKEN and RECORDS its positional args, so the
# wiring test proves the workflow passes them in <repo> <pr_number> <engine_is_error>
# order (a swapped/dropped arg would silently break the real gate while staying green).
cat > "$S1175_WF/.prflow/vendor/prflow/scripts/dismiss-stale-rejections-net.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$S1175_WF_ARGS"
printf '%s\n' "${S1175_FAKE_TOKEN:-no-dismiss-undetermined}"
exit 0
SH
chmod +x "$S1175_WF/.prflow/vendor/prflow/scripts/dismiss-stale-rejections-net.sh"
S1175_WF_ARGS="$S1175_WF/net-args"
s1175_wf() {  # <fake-token> -> runs the block, prints stdout
  ( cd "$S1175_WF" && REPO=o/r PR_NUMBER=55 ENGINE_ERROR=false \
      GH_TOKEN=secret S1175_FAKE_TOKEN="$1" S1175_WF_ARGS="$S1175_WF_ARGS" \
      bash "$S1175_WF/net-block.sh" )
}

# dismissed → a plain notice, no warning; args passed in the documented order.
: > "$S1175_WF_ARGS"
S1175_WF_OUT="$(s1175_wf dismissed)"
assert_eq "#1175 wiring: the net is called with repo, pr number, engine-error in that order" \
  "o/r 55 false" "$(sed -n '1p' "$S1175_WF_ARGS")"
assert_eq "#1175 wiring: a dismissed outcome emits a notice and no warning" "0" \
  "$(grep -cF '::warning::' <<<"$S1175_WF_OUT" || true)"
assert_eq "#1175 wiring: the outcome token is surfaced in a notice" "1" \
  "$(grep -cF 'stale-REJECT net: dismissed' <<<"$S1175_WF_OUT" || true)"

# dismiss-failed → warns that a REJECT may still block.
S1175_WF_OUT="$(s1175_wf dismiss-failed)"
assert_eq "#1175 wiring: a dismiss-failed outcome warns the PR may still be blocked" "1" \
  "$(grep -cF '::warning::stale-REJECT net' <<<"$S1175_WF_OUT" || true)"

# The legitimate-refusal tokens (a live REJECT that must stand, an expected verdict-less
# run) must NOT warn — they are the common, correct outcomes, and a case-label edit that
# added them to the warn set would spam a maintainer on every ordinary review. Lock the
# no-warning behavior for both.
S1175_WF_OUT="$(s1175_wf no-dismiss-reject)"
assert_eq "#1175 wiring: a no-dismiss-reject outcome emits no warning (the change-request is live, not stale)" "0" \
  "$(grep -cF '::warning::' <<<"$S1175_WF_OUT" || true)"
S1175_WF_OUT="$(s1175_wf no-dismiss-undetermined)"
assert_eq "#1175 wiring: a no-dismiss-undetermined outcome emits no warning (the expected verdict-less run)" "0" \
  "$(grep -cF '::warning::' <<<"$S1175_WF_OUT" || true)"

# A missing net helper DEGRADES: warn, and never fail the step (Phase 4.4 stays the path).
rm -f "$S1175_WF/.prflow/vendor/prflow/scripts/dismiss-stale-rejections-net.sh"
S1175_WF_OUT="$(s1175_wf dismissed)"
assert_eq "#1175 wiring: an absent net helper warns instead of failing" "1" \
  "$(grep -cF 'dismiss-stale-rejections-net.sh absent' <<<"$S1175_WF_OUT" || true)"
rm -rf "$S1175_WF"

# ────────────────────────────────────────────────────────────────────────────
echo "authorize-actor.sh (allowed_users filter)"
# ────────────────────────────────────────────────────────────────────────────
AUTH="$LIB/../scripts/authorize-actor.sh"
ASTUB="$(mktemp -d)"; cp "$LIB/test/fixtures/gh-stub.sh" "$ASTUB/gh"; chmod +x "$ASTUB/gh"
# Alice is the login the gh stub treats as a write/admin collaborator (mirrors
# the rit write-collaborator case: ACTOR='alice' STUB_PERM='write').
COLLAB="alice"
# shellcheck disable=SC1090,SC2154  # sources authorize-actor.sh at runtime; $authorized set there
run_auth() { ( PATH="$ASTUB:$PATH"; . "$AUTH"; authorize_actor; printf '%s' "$authorized" ); }
# shellcheck disable=SC1090,SC2154  # sources authorize-actor.sh at runtime; $deny_reason set there
run_auth_reason() { ( PATH="$ASTUB:$PATH"; . "$AUTH"; authorize_actor; printf '%s' "$deny_reason" ); }

# 1. Default (ALLOWED_USERS unset → '*') + collaborator → authorized.
A="$(ACTOR="$COLLAB" ALLOWED_BOTS="somebot" REPO="o/r" run_auth)"
assert_eq "auth: unset allowed_users + collaborator → authorized" "true" "$A"

# 2. Explicit '*' + collaborator → authorized.
A="$(ACTOR="$COLLAB" ALLOWED_BOTS="somebot" REPO="o/r" ALLOWED_USERS="*" run_auth)"
assert_eq "auth: '*' + collaborator → authorized" "true" "$A"

# 3. allowed_users lists the actor + collaborator → authorized.
A="$(ACTOR="$COLLAB" ALLOWED_BOTS="somebot" REPO="o/r" ALLOWED_USERS="$COLLAB,other" run_auth)"
assert_eq "auth: actor in allowed_users + collaborator → authorized" "true" "$A"

# 4. allowed_users does NOT list the actor → denied even though collaborator.
A="$(ACTOR="$COLLAB" ALLOWED_BOTS="somebot" REPO="o/r" ALLOWED_USERS="alice-x,bob" run_auth)"
assert_eq "auth: collaborator not in allowed_users → denied" "false" "$A"
R="$(ACTOR="$COLLAB" ALLOWED_BOTS="somebot" REPO="o/r" ALLOWED_USERS="alice-x,bob" run_auth_reason)"
assert_eq "auth: deny_reason cites allowed_users" "is not in the configured allowed_users allowlist" "$R"

# 5. Bot in allowed_bots bypasses allowed_users entirely.
A="$(ACTOR="somebot" ALLOWED_BOTS="somebot" REPO="o/r" ALLOWED_USERS="nobody" run_auth)"
assert_eq "auth: allowed bot bypasses allowed_users → authorized" "true" "$A"

rm -rf "$ASTUB"

# ────────────────────────────────────────────────────────────────────────────
echo "detect-standalone-command.sh"
# ────────────────────────────────────────────────────────────────────────────
# Shared markdown-aware standalone-command detector (issue #314). It fires only
# on a light /devflow:* command that is the sole content of its own line — at
# most three leading spaces, not tab/4+-indented, not inside a fenced block, and
# with the remainder at most an optional #-number — and declines any command
# merely quoted in prose, blockquoted, indented, or fenced. It is the single
# scanner both resolve-command-trigger.sh AND the review_dedupe job route
# through, so the two matchers cannot drift. Reads the body on stdin; emits
# `command=`/`number=`. No gh, no network — pure text.
DSC="$LIB/../scripts/detect-standalone-command.sh"
dsc_cmd() { printf '%s' "$1" | bash "$DSC" | sed -n 's/^command=//p'; }
dsc_num() { printf '%s' "$1" | bash "$DSC" | sed -n 's/^number=//p'; }

# --- Standalone forms FIRE (command resolves) -------------------------------
assert_eq "dsc: bare /devflow:review fires" \
  "/prflow:review" "$(dsc_cmd '/devflow:review')"
assert_eq "dsc: /devflow:review 42 → number 42" \
  "42" "$(dsc_num '/devflow:review 42')"
assert_eq "dsc: /devflow:review #42 → number 42 (# stripped)" \
  "42" "$(dsc_num '/devflow:review #42')"
assert_eq "dsc: review-and-fix disambiguation (never bare review)" \
  "/prflow:review-and-fix" "$(dsc_cmd '/devflow:review-and-fix')"
assert_eq "dsc: /devflow:pr-description fires" \
  "/prflow:pr-description" "$(dsc_cmd '/devflow:pr-description')"
assert_eq "dsc: up to three leading spaces still fires" \
  "/prflow:review" "$(dsc_cmd '   /devflow:review')"
assert_eq "dsc: command alone on line 2 of a multi-line body fires" \
  "/prflow:review" "$(dsc_cmd "$(printf 'hello world\n/devflow:review\nbye')")"

# --- Non-invoking forms are DECLINED (empty command) ------------------------
assert_eq "dsc: leading prose declined" \
  "" "$(dsc_cmd 'please run /devflow:review')"
assert_eq "dsc: trailing prose declined" \
  "" "$(dsc_cmd '/devflow:review please look')"
assert_eq "dsc: > blockquote declined" \
  "" "$(dsc_cmd '> /devflow:review')"
assert_eq "dsc: four-plus-space indent (code block) declined" \
  "" "$(dsc_cmd '    /devflow:review')"
assert_eq "dsc: tab indent (code block) declined" \
  "" "$(dsc_cmd "$(printf '\t/devflow:review')")"
assert_eq "dsc: inside a triple-backtick fenced block (with info string) declined" \
  "" "$(dsc_cmd "$(printf 'text\n```bash\n/devflow:review\n```\nmore')")"
assert_eq "dsc: inside a ~~~ fenced block declined" \
  "" "$(dsc_cmd "$(printf '~~~\n/devflow:review\n~~~')")"
assert_eq "dsc: fail-closed after an UNBALANCED (unclosed) fence" \
  "" "$(dsc_cmd "$(printf '```\n/devflow:review')")"
assert_eq "dsc: reported PR-review-body prose mention declined" \
  "" "$(dsc_cmd 'I ran /devflow:review earlier, see the report')"

# --- #314 review fixes: CRLF, case-insensitivity, mismatched fence type ------
# CRLF: GitHub delivers comment/review bodies with \r\n line endings; a trailing
# \r must not make an end-anchored standalone command silently decline.
assert_eq "dsc: CRLF-terminated bare command still fires" \
  "/prflow:review" "$(dsc_cmd "$(printf '/devflow:review\r')")"
assert_eq "dsc: CRLF-terminated command keeps its number" \
  "42" "$(dsc_num "$(printf '/devflow:review 42\r')")"
assert_eq "dsc: CRLF multi-line body — standalone command on its own \\r\\n line fires" \
  "/prflow:review" "$(dsc_cmd "$(printf 'kick it off\r\n/devflow:review\r\nthanks\r')")"
# Case-insensitivity is documented; pin it so a dropped tolower() goes RED.
assert_eq "dsc: uppercase /DEVFLOW:REVIEW fires (case-insensitive), canonical token emitted" \
  "/prflow:review" "$(dsc_cmd '/DEVFLOW:REVIEW')"
assert_eq "dsc: mixed-case command keeps its number" \
  "7" "$(dsc_num '/Devflow:Review 7')"
# Mismatched fence type: a ~~~ line inside a ``` block (or vice versa) is literal
# content per GFM — it must NOT close the outer fence and expose the command.
assert_eq "dsc: tilde-fence line inside a backtick fence does not expose the command (type-tracked)" \
  "" "$(dsc_cmd "$(printf '%s\n' '```' '~~~' '/devflow:review' '```')")"
assert_eq "dsc: backtick-fence line inside a tilde fence does not expose the command (type-tracked)" \
  "" "$(dsc_cmd "$(printf '%s\n' '~~~' '```' '/devflow:review' '~~~')")"
# review-and-fix with an explicit #number resolves the number (was only pinned for review).
assert_eq "dsc: review-and-fix #number resolves both command and number" \
  "/prflow:review-and-fix" "$(dsc_cmd '/devflow:review-and-fix #9')"
assert_eq "dsc: review-and-fix #number — number extracted" \
  "9" "$(dsc_num '/devflow:review-and-fix #9')"

# --- Dual-namespace acceptance: BOTH input namespaces resolve, and the emitted
# token is always the canonical one. Every fixture above feeds the transitional
# `/devflow:` alias, so these pin the CANONICAL input arm — without them the
# accept-both alternation could regress to alias-only and stay green. The
# emit-canonical half is the load-bearing one: devflow.yml compares this token
# with `startsWith`, and one of those comparisons selects the review credential.
assert_eq "dsc: canonical /prflow:review fires, emits canonical" \
  "/prflow:review" "$(dsc_cmd '/prflow:review')"
assert_eq "dsc: canonical /prflow:review-and-fix fires, emits canonical" \
  "/prflow:review-and-fix" "$(dsc_cmd '/prflow:review-and-fix')"
assert_eq "dsc: canonical /prflow:pr-description fires, emits canonical" \
  "/prflow:pr-description" "$(dsc_cmd '/prflow:pr-description')"
assert_eq "dsc: canonical namespace keeps its number" \
  "42" "$(dsc_num '/prflow:review #42')"
assert_eq "dsc: uppercase canonical /PRFLOW:REVIEW fires (case-insensitive)" \
  "/prflow:review" "$(dsc_cmd '/PRFLOW:REVIEW')"
# Negative control: the alternation accepts exactly two namespaces, not any
# `*flow:` prefix — so the pattern cannot have been widened to a wildcard.
assert_eq "dsc: an unrelated /xflow: namespace is NOT accepted" \
  "" "$(dsc_cmd '/xflow:review')"
assert_eq "dsc: a bare /flow: namespace is NOT accepted" \
  "" "$(dsc_cmd '/flow:review')"

# --- issue #1032: the detector now also recognizes the HEAVY implement token,
# so scripts/resolve-implement-trigger.sh can share this one scanner instead of a
# second, drift-prone matcher. Both namespaces resolve, the emitted token is
# canonical, and every fence/bareness rule the light commands get applies.
assert_eq "dsc #1032: bare /prflow:implement fires, emits canonical" \
  "/prflow:implement" "$(dsc_cmd '/prflow:implement')"
assert_eq "dsc #1032: transitional /devflow:implement fires, emits canonical" \
  "/prflow:implement" "$(dsc_cmd '/devflow:implement')"
assert_eq "dsc #1032: /prflow:implement #42 → number 42 (# stripped)" \
  "42" "$(dsc_num '/prflow:implement #42')"
assert_eq "dsc #1032: implement quoted mid-prose is declined" \
  "" "$(dsc_cmd 'do not run /prflow:implement 42 here')"
assert_eq "dsc #1032: implement in a > blockquote is declined" \
  "" "$(dsc_cmd '> /prflow:implement 42')"
assert_eq "dsc #1032: implement inside a fenced block is declined" \
  "" "$(dsc_cmd "$(printf '%s\n' '```' '/prflow:implement 42' '```')")"
assert_eq "dsc #1032: implement after an UNBALANCED fence is declined (fail-closed)" \
  "" "$(dsc_cmd "$(printf '%s\n' '```' '/prflow:implement 42')")"
# CRLF: GitHub delivers comment bodies with \r\n endings, and the scanner's `\r`
# strip is command-agnostic — but it was only ever exercised on a light command.
# Cover the HEAVY token explicitly: an unstripped `\r` would defeat the
# end-anchored pattern and silently decline every real implement trigger.
assert_eq "dsc #1032: CRLF-terminated /prflow:implement still fires" \
  "/prflow:implement" "$(dsc_cmd "$(printf '/prflow:implement 42\r')")"
assert_eq "dsc #1032: CRLF-terminated implement still yields its number" \
  "42" "$(dsc_num "$(printf '/prflow:implement 42\r')")"

# ────────────────────────────────────────────────────────────────────────────
echo "resolve-command-trigger.sh"
# ────────────────────────────────────────────────────────────────────────────
# Light command dispatch (review / review-and-fix / pr-description) in AGENT
# mode. Authorizes the sender (allowed bot bypasses gh; otherwise allowed_users
# + collaborator), detects the command, and resolves a target number. Reuses
# gh-stub.sh (alice → write collaborator; any other actor → HTTP 404).
RCT="$LIB/../scripts/resolve-command-trigger.sh"
# Pin TARGETS are spelled as $LIB-relative path VARIABLES, never inlined into the
# pin call as "$LIB/../…". pin-corpus-lint.py resolves a `VAR="$LIB/relative"`
# assignment but cannot resolve an interpolated path sitting directly in the
# argument, so an inlined target leaves the pin UNRESOLVED — surfaced on stderr but
# never asserted, i.e. silently exempt from the pin-in-comment and wrapped-literal
# meta-guards (the extraction hazard issue #746 names). Same file either way at run
# time; only the static resolvability differs.
RCT_WF_DEVFLOW="$LIB/../.github/workflows/devflow.yml"
RCT_STUB="$(mktemp -d)"; cp "$LIB/test/fixtures/gh-stub.sh" "$RCT_STUB/gh"; chmod +x "$RCT_STUB/gh"

# 1. issue #1863: a light command carries a trailing number (hash-prefixed
# spelling), but the resolver addresses the THREAD it was posted on, not the
# typed number — the reproduction case (pre-#1863 this asserted command 42). The
# discarded number is named on stderr alongside the thread number actually used.
RCT_T1_ERR="$(mktemp)"
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="99" \
  TRIGGER_TEXT="/devflow:review #42" bash "$RCT" 2>"$RCT_T1_ERR")"
assert_eq "rct #1863: review w/ trailing number → should_run" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rct #1863: review w/ trailing number resolves the thread, not the typed number" \
  "command=/prflow:review 99" "$(echo "$OUT" | grep '^command=')"
assert_eq "rct #1863: the discarded typed number is named on stderr" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 99' "$RCT_T1_ERR")"
rm -f "$RCT_T1_ERR"

# 2. review-and-fix disambiguation, STANDALONE form. (Rewritten for issue #314:
# the old assertion fed the prose-wrapped "please run /devflow:review-and-fix
# now" and expected it to FIRE — under standalone anchoring that prose form now
# correctly DECLINES, so the input is rewritten to the standalone command.
# review-and-fix must still win over the /devflow:review substring it contains.)
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="7" \
  TRIGGER_TEXT="/devflow:review-and-fix" bash "$RCT")"
assert_eq "rct: standalone review-and-fix beats review substring → command" \
  "command=/prflow:review-and-fix 7" "$(echo "$OUT" | grep '^command=')"

# 3. pr-description, no explicit number → falls back to the context number.
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="13" \
  TRIGGER_TEXT="/devflow:pr-description" bash "$RCT")"
assert_eq "rct: pr-description falls back to context number → command" \
  "command=/prflow:pr-description 13" "$(echo "$OUT" | grep '^command=')"

# 4. No devflow command present → should_run=false.
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="1" \
  TRIGGER_TEXT="just a normal comment" bash "$RCT")"
assert_eq "rct: no command → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"

# 5. Unauthorized actor (gh-stub 404 → not a collaborator) → should_run=false.
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="random-user" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="5" \
  TRIGGER_TEXT="/devflow:review" bash "$RCT")"
assert_eq "rct: unauthorized actor → should_run=false" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"

# --- issue #314: standalone anchoring at the resolver boundary ---------------
# A helper that captures BOTH stdout and stderr, so we can assert the auditable
# ::warning:: on the decline paths (an authorized bot, so any decline is the
# ANCHORING/self-marker decision, never an authorization one).
rct_run() {  # trigger-text [context-number] -> sets RCT_OUT / RCT_ERR
  local text="$1" ctx="${2:-99}"
  RCT_ERR="$(mktemp)"
  RCT_OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
    REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="$ctx" \
    TRIGGER_TEXT="$text" bash "$RCT" 2>"$RCT_ERR")"
}

# 6. THE DEFECT / regression pin: a body whose only occurrence is a QUOTED
# mention must decline (should_run=false) AND emit an auditable ::warning:: —
# never the silent should_run=true today's substring resolver produced. This is
# the PASS→FAIL pin: against the pre-#314 substring matcher this asserted
# should_run=true, so it fails there and passes after anchoring.
rct_run "I ran /devflow:review earlier"
assert_eq "rct #314: quoted mention → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"
assert_eq "rct #314: quoted mention emits an auditable ::warning::" \
  "1" "$(grep -c '::warning::No STANDALONE' "$RCT_ERR")"; rm -f "$RCT_ERR"

# 7. The reported vector: a PR-review-body-shaped prose paragraph quoting
# /devflow:review resolves should_run=false (TRIGGER_TEXT is the review body).
rct_run "Thanks for the fix. As /devflow:review flagged, the edge case is now handled — approving."
assert_eq "rct #314: PR-review-body prose mention → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"

# 8. Each non-invoking form declines: leading prose, > blockquote, 4-space and
# tab indent, and inside a fenced block (both fence flavors + unclosed).
rct_run "please run /devflow:review"
assert_eq "rct #314: leading prose → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "> /devflow:review"
assert_eq "rct #314: blockquote → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "    /devflow:review"
assert_eq "rct #314: four-space indent → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "$(printf '\t/devflow:review')"
assert_eq "rct #314: tab indent → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "$(printf 'see below\n```\n/devflow:review\n```')"
assert_eq "rct #314: inside a triple-backtick fence → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "$(printf '~~~\n/devflow:review\n~~~')"
assert_eq "rct #314: inside a ~~~ fence → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "$(printf '```\n/devflow:review')"
assert_eq "rct #314: fail-closed after an unclosed fence → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"

# 9. A STANDALONE command inside a longer multi-line body still fires (the
# anchoring declines only the quoted forms, never a genuine own-line command).
rct_run "$(printf 'Here is the PR summary.\n\n/devflow:review 42\n\nthanks')"
assert_eq "rct #314: standalone command on its own line in a multi-line body fires" \
  "should_run=true" "$(echo "$RCT_OUT" | grep '^should_run=')"
assert_eq "rct #1863: …and resolves the thread's number, not the typed one" \
  "command=/prflow:review 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: …and names the discarded typed number on stderr" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 99' "$RCT_ERR")"; rm -f "$RCT_ERR"

# 10. Self-marker decline (defense-in-depth), asserted BEFORE authorization:
# the review-progress marker prefix and the workpad marker each decline with a
# self-trigger ::warning::, even though the body also carries a standalone-looking
# command. (Authorized bot, so this is the marker decision, not authorization.)
rct_run "$(printf '<!-- devflow:review-progress run=123-1 -->\n/devflow:review')"
assert_eq "rct #314: review-progress marker → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"
assert_eq "rct #314: review-progress marker emits a self-trigger ::warning::" \
  "1" "$(grep -c '::warning::light /devflow:. trigger came from a Devflow-authored comment' "$RCT_ERR")"; rm -f "$RCT_ERR"
rct_run "$(printf '<!-- devflow:workpad -->\n/devflow:review')"
assert_eq "rct #314: workpad marker → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"

# 11. Missing/unrunnable detector → fail-closed decline with a DISTINCT
# broken-install breadcrumb (not a generic bash error, not the misdirected
# "no standalone command" message). Run a resolver copy from a temp dir with NO
# sibling detect-standalone-command.sh so `$(dirname "$0")/detect-...` is absent.
NODET_DIR="$(mktemp -d)"; cp "$RCT" "$NODET_DIR/resolve-command-trigger.sh"
cp "$LIB/../scripts/authorize-actor.sh" "$NODET_DIR/authorize-actor.sh"
NODET_ERR="$(mktemp)"
NODET_OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="5" \
  TRIGGER_TEXT="/devflow:review" bash "$NODET_DIR/resolve-command-trigger.sh" 2>"$NODET_ERR")"
assert_eq "rct #314: missing detector → should_run=false (fail-closed)" \
  "should_run=false" "$(echo "$NODET_OUT" | grep '^should_run=')"
assert_eq "rct #314: missing detector emits a distinct broken-install ::warning::" \
  "1" "$(grep -c '::warning::standalone-command detector' "$NODET_ERR")"
rm -rf "$NODET_DIR"; rm -f "$NODET_ERR"

# 12. issue #1032: a STANDALONE /prflow:implement reaching the LIGHT resolver is
# declined by the fail-closed light-command allowlist. The shared detector now
# recognizes implement (so the heavy resolver scripts/resolve-implement-trigger.sh
# can share the one matcher), but this light path dispatches only the three light
# commands — implement is the heavy devflow-implement.yml path. The light path's
# OBSERVABLE behavior is unchanged from before #1032 (implement declined then too,
# via an empty cmd); only the diagnostic differs, so the ::notice:: naming the
# non-light token is pinned.
rct_run "/prflow:implement 42"
assert_eq "rct #1032: standalone /prflow:implement declined by the light allowlist → should_run=false" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"
assert_eq "rct #1032: non-light token emits its distinct ::notice::" \
  "1" "$(grep -c "::notice::'/prflow:implement' is not a light" "$RCT_ERR")"; rm -f "$RCT_ERR"
# Sanity: every genuine standalone LIGHT command still fires, so the allowlist
# does not over-match the commands it must still dispatch.
rct_run "/prflow:review 7"
assert_eq "rct #1032: light /prflow:review unaffected by the allowlist" \
  "should_run=true" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "/prflow:review-and-fix 7"
assert_eq "rct #1032: light /prflow:review-and-fix unaffected by the allowlist" \
  "should_run=true" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
rct_run "/prflow:pr-description 7"
assert_eq "rct #1032: light /prflow:pr-description unaffected by the allowlist" \
  "should_run=true" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"

# 12b. issue #1032: a body carrying TWO standalone commands — one light, one
# heavy. The shared detector stops at the FIRST standalone command, and each
# resolver filters that one token against its own allowlist, so the two paths are
# MUTUALLY EXCLUSIVE by construction: whichever command comes first is the only
# one that can dispatch, and the other path declines. Documented rather than
# defended by the workflow `if:` filters, because it is the single scanner — not
# the triggers — that makes a double-fire unrepresentable. Both orderings are
# driven so a future "scan for every command" change cannot silently make both
# resolvers fire on one comment.
RCT_BOTH_LIGHT_FIRST="$(printf '%s\n' '/prflow:review' '' '/prflow:implement 42')"
RCT_BOTH_HEAVY_FIRST="$(printf '%s\n' '/prflow:implement 42' '' '/prflow:review')"
rct_run "$RCT_BOTH_LIGHT_FIRST"
assert_eq "rct #1032: light command first → the LIGHT path dispatches it" \
  "should_run=true" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
assert_eq "rct #1032: light command first → the HEAVY path declines (no double-fire)" \
  "should_run=false" "$(ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='o/r' \
    TRIGGER_TEXT="$RCT_BOTH_LIGHT_FIRST" CONTEXT_NUMBER='99' \
    PATH="$RCT_STUB:$PATH" bash "$RIT" 2>/dev/null | grep '^should_run=')"
rct_run "$RCT_BOTH_HEAVY_FIRST"
assert_eq "rct #1032: implement first → the LIGHT path declines (no double-fire)" \
  "should_run=false" "$(echo "$RCT_OUT" | grep '^should_run=')"; rm -f "$RCT_ERR"
assert_eq "rct #1032: implement first → the HEAVY path fires on its own number" \
  "number=42" "$(ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='o/r' \
    TRIGGER_TEXT="$RCT_BOTH_HEAVY_FIRST" CONTEXT_NUMBER='99' \
    PATH="$RCT_STUB:$PATH" bash "$RIT" 2>/dev/null | grep '^number=')"

# 13. AC3 (issue #1046, CLAUDE.md guard-class 2) — the detector's
# `command=`/`number=` lines are parsed with BASH BUILTINS, never `sed`.
# lib/preflight.sh guarantees git/gh/jq/python3 but NOT `sed`, and the superseded
# `sed -n 's/^command=//p'` form ran in a plain command substitution under
# `set -euo pipefail`: an absent `sed` exited 127 and aborted the LIGHT resolver
# with NEITHER `should_run=` line emitted, so the caller appended nothing to
# $GITHUB_OUTPUT and the downstream read saw empty rather than a definite `false`
# — a silent, non-fail-closed abort in a trigger gate, the same defect PR #1042
# fixed in the heavy sibling. Drive the resolver under a PATH that GENUINELY
# lacks `sed`: a directory holding only the three tools this path legitimately
# needs — `bash` (runs the detector), `awk` (inside it), `dirname` (anchors both
# siblings). Mirrors the rit #1032 no-sed arm above.
RCT_NOSED_DIR="$(mktemp -d)"
for RCT_NOSED_TOOL in awk dirname; do
  ln -s "$(command -v "$RCT_NOSED_TOOL")" "$RCT_NOSED_DIR/$RCT_NOSED_TOOL"
done
# `$BASH` — the interpreter running this suite — not PATH's first `bash`: the
# sourced authorize-actor.sh uses bash-4 parameter expansion (`${la,,}`), which a
# 3.2 /bin/bash rejects at PARSE time even on the allowed-bot path that never
# evaluates it.
ln -s "$BASH" "$RCT_NOSED_DIR/bash"
# Self-check FIRST, so this arm can never go vacuously green on a fixture PATH
# that still resolves sed.
assert_eq "rct #1046: the no-sed fixture PATH genuinely lacks sed" "absent" \
  "$(PATH="$RCT_NOSED_DIR" command -v sed >/dev/null 2>&1 && echo present || echo absent)"

# The FIRE path is the strongest evidence the parse RESOLVED rather than merely
# declined: should_run=true carrying the token's OWN command+number is reachable
# only by extracting both values out of the detector's stdout. Allowed-bot actor,
# so authorization short-circuits before gh/grep/head (all absent here too);
# DEVFLOW_GH is an absolute path to the stub so it resolves regardless of PATH.
RCT_NOSED_ERR="$(mktemp)"
OUT="$(ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='acme/x' GH_TOKEN='x' \
  DEVFLOW_GH="$RCT_STUB/gh" \
  TRIGGER_TEXT='/prflow:review 42' CONTEXT_NUMBER='7' \
  PATH="$RCT_NOSED_DIR" bash "$RCT" 2>"$RCT_NOSED_ERR")"
assert_eq "rct #1046: sed absent → a standalone light command still fires" \
  "should_run=true" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rct #1863: sed absent → the resolved command is the thread's number" \
  "command=/prflow:review 7" "$(echo "$OUT" | grep '^command=')"
# The token's OWN number (42) is still extracted from the detector's stdout by the
# builtins parse — now proven by its appearance as the discarded number on stderr,
# rather than by being emitted (the thread's number is emitted post-#1863).
assert_eq "rct #1863: sed absent → the token's own number is still extracted (named as discarded)" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 7' "$RCT_NOSED_ERR")"

# ...and the DECLINE path emits a definite verdict rather than aborting. rc 0 +
# a `should_run=false` line is exactly what the raw `sed` abort could not produce.
RCT_NOSED_OUT="$(mktemp)"
: > "$RCT_NOSED_ERR"
RCT_NOSED_RC=0
ACTOR='foo[bot]' ALLOWED_BOTS='foo' REPO='acme/x' GH_TOKEN='x' \
  DEVFLOW_GH="$RCT_STUB/gh" \
  TRIGGER_TEXT='I ran /devflow:review earlier, just discussing it' CONTEXT_NUMBER='7' \
  PATH="$RCT_NOSED_DIR" bash "$RCT" >"$RCT_NOSED_OUT" 2>"$RCT_NOSED_ERR" || RCT_NOSED_RC=$?
assert_eq "rct #1046: sed absent → the decline exits 0, never a raw abort" \
  "0" "$RCT_NOSED_RC"
assert_eq "rct #1046: sed absent → a quoted mention still declines definitely" \
  "should_run=false" "$(grep '^should_run=' "$RCT_NOSED_OUT")"
# The breadcrumb must be the SPECIFIC no-standalone one — neither silence nor the
# broken-install detector message (which would mean awk, not the parse, carried
# the decline and the arm was measuring the wrong thing).
assert_eq "rct #1046: sed absent → the decline carries its own no-standalone breadcrumb" \
  "1" "$(grep -c '::warning::No STANDALONE light' "$RCT_NOSED_ERR")"
rm -rf "$RCT_NOSED_DIR"; rm -f "$RCT_NOSED_ERR" "$RCT_NOSED_OUT"

# 14. AC3 (issue #1046) — a detector whose stdout carries NO `command=` line
# violates its own output contract (its END block prints both lines
# unconditionally), so the parse cannot resolve a command at all. That is a
# BROKEN INSTALL — a truncated or foreign stdout — not "no command present": it
# declines fail-closed under its OWN breadcrumb rather than being misreported as
# a clean no-command decline. Mirrors the rit #1032 bad-detector arm.
RCT_BADDET_DIR="$(mktemp -d)"
cp "$RCT" "$RCT_BADDET_DIR/resolve-command-trigger.sh"
cp "$LIB/../scripts/authorize-actor.sh" "$RCT_BADDET_DIR/authorize-actor.sh"
# Drains stdin for the same reason the rit bad-detector stub above does: a stub that
# ignores stdin lets the resolver's `printf | bash "$detector"` pipeline take SIGPIPE
# under `pipefail`, diverting it to the "failed to run" arm and silently unmeasuring the
# output-contract breadcrumb this arm asserts. Keep the drain.
printf '#!/usr/bin/env bash\nwhile IFS= read -r _drain; do :; done\nprintf "number=5\\n"\n' > "$RCT_BADDET_DIR/detect-standalone-command.sh"
chmod +x "$RCT_BADDET_DIR/detect-standalone-command.sh"
RCT_BADDET_ERR="$(mktemp)"
RCT_BADDET_OUT="$(mktemp)"
RCT_BADDET_RC=0
PATH="$RCT_STUB:$PATH" ACTOR='devflow-bot' ALLOWED_BOTS='devflow-bot' \
  REPO='o/r' GH_TOKEN='x' CONTEXT_NUMBER='99' \
  TRIGGER_TEXT='/devflow:review' bash "$RCT_BADDET_DIR/resolve-command-trigger.sh" \
  >"$RCT_BADDET_OUT" 2>"$RCT_BADDET_ERR" || RCT_BADDET_RC=$?
# The contract-violation path is the fail-closed broken-install arm (`exit 0`),
# so pin rc explicitly — a non-zero exit here would matter to the caller, exactly
# the raw-abort mode the parse rewrite eliminates.
assert_eq "rct #1046: detector emitting no command= line → the decline exits 0, never a raw abort" \
  "0" "$RCT_BADDET_RC"
assert_eq "rct #1046: detector emitting no command= line → should_run=false (fail-closed)" \
  "should_run=false" "$(grep '^should_run=' "$RCT_BADDET_OUT")"
assert_eq "rct #1046: detector emitting no command= line → a distinct output-contract ::warning::" \
  "1" "$(grep -c "emitted no 'command=' line" "$RCT_BADDET_ERR")"
rm -rf "$RCT_BADDET_DIR"; rm -f "$RCT_BADDET_ERR" "$RCT_BADDET_OUT"

# 15. issue #1863: the thread-addressing rule holds for the plain spelling and
# for all three light commands, the discard line fires even when the typed number
# equals the thread's own, and a command carrying no number still resolves to the
# thread (the common, unchanged case).
rct_run "/devflow:review 42"                     # plain (no #) spelling
assert_eq "rct #1863: plain-spelling trailing number → thread's number" \
  "command=/prflow:review 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: plain-spelling → discarded number named on stderr" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 99' "$RCT_ERR")"; rm -f "$RCT_ERR"
rct_run "/devflow:review-and-fix #42"
assert_eq "rct #1863: review-and-fix trailing number → thread's number" \
  "command=/prflow:review-and-fix 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: review-and-fix → discarded number named on stderr" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 99' "$RCT_ERR")"; rm -f "$RCT_ERR"
rct_run "/devflow:pr-description 42"
assert_eq "rct #1863: pr-description trailing number → thread's number" \
  "command=/prflow:pr-description 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: pr-description → discarded number named on stderr" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number 99' "$RCT_ERR")"; rm -f "$RCT_ERR"
rct_run "/devflow:review 99"                      # typed number equals the thread's own
assert_eq "rct #1863: typed number equal to the thread's still discards to the thread" \
  "command=/prflow:review 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: …and still names the discard on stderr" \
  "1" "$(grep -c 'ignoring 99 .*using the thread.s number 99' "$RCT_ERR")"; rm -f "$RCT_ERR"
rct_run "/devflow:review"                          # no trailing number: resolves the thread, as today
assert_eq "rct #1863: no trailing number → thread's number (unchanged)" \
  "command=/prflow:review 99" "$(echo "$RCT_OUT" | grep '^command=')"
assert_eq "rct #1863: no trailing number → no discard line on stderr" \
  "0" "$(grep -c 'addresses the thread it was posted on' "$RCT_ERR")"; rm -f "$RCT_ERR"
# A trailing number with NO context/thread number: the thread is the sole source, so
# the resolver declines (should_run=false) and the discard line renders the used
# number as <none> via ${context_number:-<none>} — the widened decline path. Driven
# with a direct empty CONTEXT_NUMBER (rct_run's `${2:-99}` would coerce "" back to 99).
RCT_NC_ERR="$(mktemp)"
OUT="$(PATH="$RCT_STUB:$PATH" ACTOR="devflow-bot" ALLOWED_BOTS="devflow-bot" \
  REPO="o/r" GH_TOKEN="x" CONTEXT_NUMBER="" \
  TRIGGER_TEXT="/devflow:review 42" bash "$RCT" 2>"$RCT_NC_ERR")"
assert_eq "rct #1863: trailing number + no context number → declines" \
  "should_run=false" "$(echo "$OUT" | grep '^should_run=')"
assert_eq "rct #1863: …and the discard line renders the thread number as <none>" \
  "1" "$(grep -c 'ignoring 42 .*using the thread.s number <none>' "$RCT_NC_ERR")"
rm -f "$RCT_NC_ERR"

rm -rf "$RCT_STUB"

# --- issue #314: coupled-invariant pin (resolver ↔ shared detector) ----------
# The resolver MUST route through the ONE shared detector; a future divergence
# (re-inlining a substring matcher) is caught here.
devflow_module_pin_unique "rct #314: resolver calls the shared detect-standalone-command.sh" \
  'detector="$(dirname "$0")/detect-standalone-command.sh"' "$RCT"

# --- issue #321: coupled-invariant pin (dedupe ↔ shared detector) ------------
# The twin of the #314 pin above, landed once the workflows-scoped push became
# possible (a human/PAT push the DevFlow bot token cannot make). The
# review_dedupe job in devflow.yml MUST route its body match through the SAME
# vendored detector so the trigger gate and the dedupe matcher cannot drift;
# re-inlining a `case "$BODY"` substring here would re-open that drift.
devflow_module_pin_unique "rct #321: review_dedupe routes through the shared detect-standalone-command.sh" \
  '.prflow/vendor/prflow/scripts/detect-standalone-command.sh' "$RCT_WF_DEVFLOW"

# review_dedupe is fail-OPEN by contract: a present-but-broken detector (or a
# missing sed) must NOT abort the guard step under `set -euo pipefail` — an abort
# fails the job, skipping the downstream `command` job and silently swallowing the
# manual review. Pin the outcome-verifying `if !` wrapper (the operative fix);
# reverting it to a bare `CMD=$(...)` assignment re-opens the fail-CLOSED swallow.
devflow_module_pin_unique "rct #321: review_dedupe detector extraction fails open on a run failure (if!-guarded)" \
  'if ! CMD="$(printf '"'"'%s'"'"' "$BODY" | bash "$DETECTOR" | sed -n '"'"'s/^command=//p'"'"')"' "$RCT_WF_DEVFLOW"

# ────────────────────────────────────────────────────────────────────────────
echo "post-ci-review-trigger.sh (ci.yml auto-review notification)"
# ────────────────────────────────────────────────────────────────────────────
# The composed comment body is a MACHINE-CONSUMED contract, not prose: it is
# parsed by scripts/detect-standalone-command.sh (which decides whether the
# comment is a standalone command at all, and which one) and substring-tested by
# devflow.yml's gate `if:`. It is therefore asserted through the REAL detector on
# the REAL composer's output rather than by grepping the composer's source.
# structural-pin-ok: routing-dispatch-contract -- the body is the dispatch token the
# shared standalone-command detector and devflow.yml's trigger gate both read.
#
# This block is also the structural brake on ONE specific future edit. Widening
# the payload to the fix-loop command would mint an App token and push with it,
# and an App-token push is not covered by GitHub's recursion guard, so it would
# re-run CI, re-post, and loop without bound. Plain review mints no App token
# (devflow.yml skips that step on a `/prflow:review ` command) and pushes nothing.
PCRT="$LIB/../scripts/post-ci-review-trigger.sh"
PCRT_SHA="0123456789abcdef0123456789abcdef01234567"
PCRT_BODY="$(MODE=compose PR=7 HEAD_SHA="$PCRT_SHA" bash "$PCRT" 2>/dev/null)"
PCRT_DET="$(printf '%s' "$PCRT_BODY" | bash "$LIB/../scripts/detect-standalone-command.sh")"

assert_eq "pcrt: the composed body resolves to the PLAIN review command through the real detector" \
  "command=/prflow:review" "$(printf '%s\n' "$PCRT_DET" | grep '^command=')"
assert_eq "pcrt: the composed body carries no explicit number, so the resolver targets the event's own PR" \
  "number=" "$(printf '%s\n' "$PCRT_DET" | grep '^number=')"
assert_eq "pcrt: the composed body mentions no @claude (the partition invariant with Anthropic's claude.yml)" \
  "0" "$(printf '%s' "$PCRT_BODY" | grep -c '@claude')"
assert_eq "pcrt: the composed body carries no implement token in EITHER namespace" \
  "0" "$(printf '%s' "$PCRT_BODY" | grep -cE '/(pr|dev)flow:implement')"
assert_eq "pcrt: the composed body carries the SHA-keyed dedupe marker" \
  "1" "$(printf '%s' "$PCRT_BODY" | grep -cF "<!-- prflow:ci-review-trigger sha=$PCRT_SHA -->")"
# Negative control: the assertions above would also pass on a body that is nothing
# but the marker, so prove the detector really is reading a command line here.
assert_eq "pcrt: negative control — the marker alone resolves to NO command" \
  "command=" "$(printf '%s\n' "<!-- prflow:ci-review-trigger sha=$PCRT_SHA -->" \
                 | bash "$LIB/../scripts/detect-standalone-command.sh" | grep '^command=')"

# --- the post-or-skip selection, arm by arm ---------------------------------
# The whole reason the decision lives in a helper rather than inline in ci.yml:
# a reordered or broken arm here posts a duplicate paid review, or silently posts
# nothing, and inline YAML could not be driven at all.
PCRT_SB="$(mktemp -d)"
cat > "$PCRT_SB/gh" <<'EOS'
#!/usr/bin/env bash
# gh stub. A POST is recorded to $PCRT_REC and honours $PCRT_POST_RC; a `pulls/<n>`
# read is the PR-state guard (issue #1236), which honours $PCRT_STATE_RC and serves
# the post-jq state $PCRT_PR_STATE (default `open`, so an unset value keeps every
# pre-#1236 arm on the actionable path); anything else is the comment-list read,
# which honours $PCRT_LIST_RC and serves $PCRT_LIST_OUT (the ids the helper's marker
# filter would have matched).
case "$*" in
  *"--method POST"*)
    printf '%s\n' "$*" >> "$PCRT_REC"
    [ "${PCRT_POST_RC:-0}" = 0 ] || { echo "HTTP 403" >&2; exit 1; }
    printf '{"id":1}\n'; exit 0 ;;
  *"pulls/"*)
    # Record each state read so a test can assert exactly one (issue #2067). With
    # $PCRT_PR_JSON set, run the helper's REAL --jq against the fixture (the auto_merge
    # branch lives inside it); else serve $PCRT_PR_STATE verbatim (#1236 case-word boundary).
    [ -n "${PCRT_STATE_REC-}" ] && printf '%s\n' "$*" >> "$PCRT_STATE_REC"
    [ "${PCRT_STATE_RC:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }
    if [ -n "${PCRT_PR_JSON-}" ]; then
      _jqprog="."; _prev=""
      for _a in "$@"; do [ "$_prev" = "--jq" ] && _jqprog="$_a"; _prev="$_a"; done
      printf '%s' "$PCRT_PR_JSON" | jq -r "$_jqprog"; exit $?
    fi
    printf '%s' "${PCRT_PR_STATE-open}"; exit 0 ;;
esac
[ "${PCRT_LIST_RC:-0}" = 0 ] || { echo "HTTP 500" >&2; exit 1; }
printf '%s' "${PCRT_LIST_OUT-}"
exit 0
EOS
chmod +x "$PCRT_SB/gh"

# Runs the helper under the stub, leaving its stdout in $PCRT_OUT and the recorded
# POST count in $PCRT_POSTS.
# EXPECTED_AUTHOR is the App slug the mint step plumbs in (issue #990): a marker
# comment suppresses only when THIS App authored it. The stub returns
# $PCRT_LIST_OUT verbatim as the helper's post-jq output, now ONE LINE PER
# marker-bearing comment: its author login, or the __prflow_no_author__ sentinel.
pcrt_run() {  # $@ = extra command-prefix env assignments (override EXPECTED_AUTHOR/etc last)
  : > "$PCRT_SB/rec"
  : > "$PCRT_SB/state_rec"
  PCRT_OUT="$(env PCRT_REC="$PCRT_SB/rec" PCRT_STATE_REC="$PCRT_SB/state_rec" DEVFLOW_GH="$PCRT_SB/gh" \
                  PR=7 HEAD_SHA="$PCRT_SHA" EXPECTED_AUTHOR=prflow-app "$@" bash "$PCRT" 2>/dev/null)"
  PCRT_RC=$?
  PCRT_POSTS="$(grep -c . "$PCRT_SB/rec")"
  PCRT_STATE_READS="$(grep -c . "$PCRT_SB/state_rec")"
}

pcrt_run PCRT_LIST_OUT=""
assert_eq "pcrt: no existing marker for this head → the trigger is POSTed" \
  "1" "$PCRT_POSTS"
assert_eq "pcrt: a successful post is annotated as a notice naming the head" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c "^::notice::ci auto-review trigger: posted the review trigger on PR #7 for $PCRT_SHA")"

pcrt_run PCRT_LIST_OUT="prflow-app[bot]"
assert_eq "pcrt: an App-authored marker for THIS head → nothing is posted (per-SHA, author-scoped dedupe)" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt: the already-posted arm annotates a notice, never a warning" \
  "1-0" "$(printf '%s\n' "$PCRT_OUT" | grep -c 'already carries an App-authored trigger comment')-$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::')"

pcrt_run PCRT_LIST_RC=1
assert_eq "pcrt: an unreadable comment list → FAIL-CLOSED, nothing is posted" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt: the fail-closed arm warns and names the choice, so a missed review is never silent" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: could not read PR #7 comments.*fail-closed')"

pcrt_run PCRT_LIST_OUT="" PCRT_POST_RC=1
assert_eq "pcrt: a POST that fails is NEVER annotated as a fired trigger (the #408 lesson)" \
  "0-1" "$(printf '%s\n' "$PCRT_OUT" | grep -c 'posted the review trigger')-$(printf '%s\n' "$PCRT_OUT" | grep -c 'did NOT post')"

# --- PR-state guard, arm by arm (issue #1236) -------------------------------
# When CI goes green the caller fires the trigger unconditionally, so a PR merged
# or closed mid-CI would draw a full review run on a dead target — paid spend with
# no reader. The guard reads the PR state (stubbed via PCRT_PR_STATE / PCRT_STATE_RC)
# and posts ONLY while the PR is open; every no-post arm leaves its OWN distinct
# annotation and the helper still exits 0. PCRT_PR_STATE defaults to `open`, so every
# arm above is unaffected.
pcrt_run PCRT_LIST_OUT="" PCRT_PR_STATE=open
assert_eq "pcrt #1236-open: an OPEN PR still posts the trigger (state guard falls through)" \
  "1" "$PCRT_POSTS"

pcrt_run PCRT_PR_STATE=merged
assert_eq "pcrt #1236-merged: a MERGED PR posts nothing (no review on a merged target)" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #1236-merged: the merged arm warns with its OWN distinct annotation" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 is already merged; NOT posting')"

pcrt_run PCRT_PR_STATE=closed
assert_eq "pcrt #1236-closed: a CLOSED-unmerged PR posts nothing (no review on a closed target)" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #1236-closed: the closed arm warns with its OWN distinct annotation" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 is closed without merging; NOT posting')"

pcrt_run PCRT_STATE_RC=1
assert_eq "pcrt #1236-state-unreadable: an unreadable PR state fails CLOSED, posting nothing" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #1236-state-unreadable: the fail-closed arm warns naming the unresolved state" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: could not read PR #7 state.*fail-closed')"

pcrt_run PCRT_PR_STATE=""
assert_eq "pcrt #1236-state-empty: an empty (unestablished) PR state fails CLOSED, posting nothing" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #1236-state-empty: the unestablished-state arm warns with its OWN distinct annotation" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 state could not be established')"

# --- auto-merge guard, arm by arm (issue #2067) -----------------------------
# The #1236 arms above serve the post-jq state WORD verbatim; the auto_merge
# decision lives INSIDE the helper's jq, so these arms drive a full JSON fixture
# through the helper's REAL --jq program (jq is preflight-guaranteed) via $PCRT_PR_JSON.
PCRT_AM='{"state":"open","merged":false,"auto_merge":{"enabled_by":{"login":"octocat"},"merge_method":"squash"}}'

# RED-first: against the pre-fix jq this open+armed fixture maps to `open` and POSTs
# (the reported defect); the fix maps it to `automerge` and skips.
pcrt_run PCRT_LIST_OUT="" PCRT_PR_JSON="$PCRT_AM"
assert_eq "pcrt #2067-automerge: an OPEN auto-merge-armed PR posts nothing (it would race the auto-merge onto a merged target)" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #2067-automerge: the helper still exits 0 on the auto-merge arm" \
  "0" "$PCRT_RC"
assert_eq "pcrt #2067-automerge: the auto-merge arm warns with its OWN distinct annotation naming enabled auto-merge" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 has GitHub auto-merge enabled')"
assert_eq "pcrt #2067-automerge: the auto-merge arm made exactly ONE PR-state read" \
  "1" "$PCRT_STATE_READS"
assert_eq "pcrt #2067-automerge: the auto-merge annotation is the ONLY warning (no fall-through to a sibling arm's)" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::')"

# A second post-mode run against the same armed fixture again posts nothing (idempotent).
pcrt_run PCRT_LIST_OUT="" PCRT_PR_JSON="$PCRT_AM"
assert_eq "pcrt #2067-automerge-idempotent: a second run against the same armed fixture again posts nothing" \
  "0" "$PCRT_POSTS"

# An OPEN PR with auto_merge null still posts, reading state exactly once.
pcrt_run PCRT_LIST_OUT="" PCRT_PR_JSON='{"state":"open","merged":false,"auto_merge":null}'
assert_eq "pcrt #2067-open-null: an OPEN PR with auto_merge null still posts the trigger (unchanged)" \
  "1" "$PCRT_POSTS"
assert_eq "pcrt #2067-open-null: the posting arm made exactly ONE PR-state read" \
  "1" "$PCRT_STATE_READS"

# Absence shape: a response with NO auto_merge key behaves as null and still posts.
pcrt_run PCRT_LIST_OUT="" PCRT_PR_JSON='{"state":"open","merged":false}'
assert_eq "pcrt #2067-open-absent: a response with no auto_merge key behaves as null and still posts" \
  "1" "$PCRT_POSTS"
assert_eq "pcrt #2067-open-absent: the posting arm made exactly ONE PR-state read" \
  "1" "$PCRT_STATE_READS"

# Adversarial non-object shape: a response the helper's jq cannot index (`.merged` on
# an array errors → gh exits non-zero) drives the fail-closed unreadable-state arm —
# the stub propagates jq's real exit status (exit $?), so this reaches the helper's
# `if !` guard exactly as real gh would.
pcrt_run PCRT_LIST_OUT="" PCRT_PR_JSON='[]'
assert_eq "pcrt #2067-non-object: a non-object state response fails CLOSED, posting nothing" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #2067-non-object: the fail-closed arm warns naming the unresolved state" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: could not read PR #7 state.*fail-closed')"

# Ordering — a MERGED PR still carrying an auto_merge record (the PR #2059 shape)
# takes the merged arm; the jq testing `.merged` before the auto_merge branch (and
# that branch's `.state == "open"` guard) is what guarantees it — reorder either and
# this breaks.
pcrt_run PCRT_PR_JSON='{"state":"closed","merged":true,"auto_merge":{"enabled_by":{"login":"octocat"},"merge_method":"squash"}}'
assert_eq "pcrt #2067-merged-armed: a MERGED PR still carrying an auto_merge record posts nothing" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #2067-merged-armed: it takes the MERGED annotation, not the auto-merge one (merged decided first)" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 is already merged; NOT posting')"
assert_eq "pcrt #2067-merged-armed: the auto-merge annotation is NOT emitted (merged decided before auto-merge)" \
  "0" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 has GitHub auto-merge enabled')"
assert_eq "pcrt #2067-merged-armed: made exactly ONE PR-state read" \
  "1" "$PCRT_STATE_READS"

# Ordering — a CLOSED-unmerged PR carrying an auto_merge record takes the closed
# arm; the new state word is emitted only for an OPEN PR.
pcrt_run PCRT_PR_JSON='{"state":"closed","merged":false,"auto_merge":{"enabled_by":{"login":"octocat"},"merge_method":"squash"}}'
assert_eq "pcrt #2067-closed-armed: a CLOSED-unmerged PR still carrying an auto_merge record posts nothing" \
  "0" "$PCRT_POSTS"
assert_eq "pcrt #2067-closed-armed: it takes the CLOSED annotation, not the auto-merge one (new word is OPEN-only)" \
  "1" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 is closed without merging; NOT posting')"
assert_eq "pcrt #2067-closed-armed: the auto-merge annotation is NOT emitted (new word is OPEN-only)" \
  "0" "$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::ci auto-review trigger: PR #7 has GitHub auto-merge enabled')"
assert_eq "pcrt #2067-closed-armed: made exactly ONE PR-state read" \
  "1" "$PCRT_STATE_READS"

# --- ci.yml supersession concurrency static check (issue #1236, Half A / AC2) --
# ci.yml's workflow-level `concurrency:` behavior lives on GitHub's scheduler and
# cannot be executed locally; lib/test/check-ci-concurrency.py is the closest
# mechanical surface — a static check over the workflow file's concurrency region.
# Drive it against the REAL ci.yml (all three properties hold) and synthetic
# fixtures that each violate exactly one property, plus the fail-closed
# unreadable-file arm.
CICC="$LIB/test/check-ci-concurrency.py"
# Run the checker ONCE per case, capturing its stdout and exit code together, then
# reduce stdout to the verdict word (ok|fail|unavailable). One helper avoids
# spawning the checker twice per assertion and the four-way duplication of the
# extraction pipeline below.
cicc_run() {  # $@ = args to the checker; sets CICC_VERDICT + CICC_RC
  local out
  out="$(python3 "$CICC" "$@" 2>&1)"; CICC_RC=$?
  CICC_VERDICT="$(printf '%s\n' "$out" | grep -oE '^CI_CONCURRENCY (ok|fail|unavailable)' | awk '{print $2}')"
}
cicc_run
assert_eq "cicc #1236: the real ci.yml carries a valid workflow-level supersession concurrency key" \
  "ok|0" "$CICC_VERDICT|$CICC_RC"

CICC_SB="$(mktemp -d)"
cat > "$CICC_SB/absent.yml" <<'EOY'
name: CI
on:
  push:
    branches: [main]
jobs:
  x:
    runs-on: ubuntu-latest
EOY
cat > "$CICC_SB/nonpr-group.yml" <<'EOY'
name: CI
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs: {}
EOY
cat > "$CICC_SB/cancel-main.yml" <<'EOY'
name: CI
concurrency:
  group: ci-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: true
jobs: {}
EOY
# A group that varies with the PR but carries NO github.run_id fallback: on a main
# push github.event.pull_request.number is empty, so EVERY main run collapses into
# one shared group and cancels/serializes — the "Design caution 4" bug. This is the
# fixture that covers the second sub-check of property 2 (run_id present), which the
# nonpr-group.yml fixture cannot reach (it fails the first sub-check).
cat > "$CICC_SB/pr-no-runid.yml" <<'EOY'
name: CI
concurrency:
  group: ci-${{ github.event.pull_request.number }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs: {}
EOY
# check-ci-concurrency.py is a best-effort parser over a human-mutable YAML file, so
# the repo's adversarial-shape matrix applies: drive each fail-closed arm.
cat > "$CICC_SB/scalar-conc.yml" <<'EOY'
name: CI
concurrency: enabled
jobs: {}
EOY
cat > "$CICC_SB/no-group.yml" <<'EOY'
name: CI
concurrency:
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs: {}
EOY
cat > "$CICC_SB/no-cancel.yml" <<'EOY'
name: CI
concurrency:
  group: ci-${{ github.event.pull_request.number || github.run_id }}
jobs: {}
EOY
: > "$CICC_SB/empty.yml"
cat > "$CICC_SB/bad-yaml.yml" <<'EOY'
name: CI
concurrency: [unbalanced
EOY
cat > "$CICC_SB/list-doc.yml" <<'EOY'
- a
- b
EOY

cicc_run --ci-file "$CICC_SB/absent.yml"
assert_eq "cicc #1236: an ABSENT workflow-level concurrency key fails (this is the pre-change ci.yml shape)" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/nonpr-group.yml"
assert_eq "cicc #1236: a group that does NOT vary with the pull request fails" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/cancel-main.yml"
assert_eq "cicc #1236: a cancel-in-progress that would resolve true for a main push fails" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/does-not-exist.yml"
assert_eq "cicc #1236: an unreadable workflow file fails CLOSED as unavailable, never a silent pass" \
  "unavailable|3" "$CICC_VERDICT|$CICC_RC"
# Property 2, second sub-check: a PR-varying group with no run_id fallback fails,
# so a main push cannot collapse every run into one cancelled group (Design caution 4).
cicc_run --ci-file "$CICC_SB/pr-no-runid.yml"
assert_eq "cicc #1236: a PR-varying group with NO github.run_id fallback fails (main runs would collapse into one group)" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
# Adversarial-shape matrix over the parser's fail-closed arms.
cicc_run --ci-file "$CICC_SB/scalar-conc.yml"
assert_eq "cicc #1236: a scalar (non-mapping) concurrency fails" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/no-group.yml"
assert_eq "cicc #1236: a concurrency mapping with no group fails" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/no-cancel.yml"
assert_eq "cicc #1236: a concurrency mapping with no cancel-in-progress fails" \
  "fail|1" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/empty.yml"
assert_eq "cicc #1236: an empty workflow file fails CLOSED as unavailable" \
  "unavailable|3" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/bad-yaml.yml"
assert_eq "cicc #1236: an unparseable workflow file fails CLOSED as unavailable" \
  "unavailable|3" "$CICC_VERDICT|$CICC_RC"
cicc_run --ci-file "$CICC_SB/list-doc.yml"
assert_eq "cicc #1236: a non-mapping (list) document fails CLOSED as unavailable" \
  "unavailable|3" "$CICC_VERDICT|$CICC_RC"
rm -rf "$CICC_SB"

# A missing/blank head SHA cannot key the marker, so dedupe would be impossible —
# refuse rather than post an unkeyed comment on every run.
pcrt_run HEAD_SHA=""
assert_eq "pcrt: an unusable head SHA → nothing is posted, with its own warning" \
  "0-1" "$PCRT_POSTS-$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::.*head SHA')"

# --- author-scoped suppression, arm by arm (issue #990 Part B) --------------
# The author scoping closes the quoting-suppression hazard: before it, ANY comment
# quoting the marker suppressed the review. Each arm below drives the helper's bash
# author-matching directly through the stub's post-jq output ($PCRT_LIST_OUT).

# 1. App-authored marker for THIS head -> no post (dedupe still holds once
#    authorship is required) — asserted by the already-posted arm above with a
#    matching login; re-stated here as the author-required positive.
pcrt_run PCRT_LIST_OUT="prflow-app[bot]"
assert_eq "pcrt #990-1: an App-authored marker for this head -> no post (author required)" \
  "0" "$PCRT_POSTS"

# 2. Exact marker for this head authored by ANY OTHER login -> POST. The planted-
#    defect positive control for the quoting-suppression hazard: it fails FIRST
#    against the old author-blind filter, which suppressed on marker containment.
pcrt_run PCRT_LIST_OUT="some-human"
assert_eq "pcrt #990-2: a marker quoted by a NON-App login no longer suppresses -> post" \
  "1" "$PCRT_POSTS"

# 3. [bot]/bare-slug handling in BOTH directions (mirrors authorize-actor.sh's
#    actor_bare): login carries [bot] while comparand is bare, and the mirror.
pcrt_run PCRT_LIST_OUT="prflow-app[bot]"
PCRT_P3A="$PCRT_POSTS"
pcrt_run EXPECTED_AUTHOR="prflow-app[bot]" PCRT_LIST_OUT="prflow-app"
assert_eq "pcrt #990-3: [bot]/bare slug match both directions -> no post" \
  "0-0" "$PCRT_P3A-$PCRT_POSTS"

# 4. Per-SHA keying: the marker embeds sha=$HEAD_SHA, so a marker for a DIFFERENT
#    head is filtered out by the helper's jq before the emitted list — modeled here
#    as an empty emitted list (a proxy for the post-jq output). The marker's own
#    head-keying (that the composed marker literally carries sha=$PCRT_SHA) is
#    asserted separately by the compose-mode marker assertion above; the stub returns
#    $PCRT_LIST_OUT verbatim and cannot itself run the jq head filter.
pcrt_run PCRT_LIST_OUT=""
assert_eq "pcrt #990-4: emitted list empty (a different-head marker filtered out by jq) -> post" \
  "1" "$PCRT_POSTS"

# 5. Empty author comparand -> no post + its own distinct warning (fail-closed
#    direction, asserted rather than assumed).
pcrt_run EXPECTED_AUTHOR="" PCRT_LIST_OUT=""
assert_eq "pcrt #990-5: empty author comparand -> no post + distinct warning (fail closed)" \
  "0-1" "$PCRT_POSTS-$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::.*expected author login .*is empty')"

# 6. An instruction-shaped / other-author comment body changes no outcome — the
#    helper matches marker and author literally and interprets no body text. Modeled
#    as an other-author login whose (simulated) text "asks to suppress": still posts.
pcrt_run PCRT_LIST_OUT="please-suppress-bot"
assert_eq "pcrt #990-6: an instruction-shaped / other-author comment changes nothing -> post" \
  "1" "$PCRT_POSTS"

# 7. A marker comment whose author cannot be resolved (sentinel) -> no post +
#    fail-closed warning. An unestablished author must never widen to duplicate-post.
pcrt_run PCRT_LIST_OUT="__prflow_no_author__"
assert_eq "pcrt #990-7: a marker comment whose author cannot be resolved -> no post + fail-closed warning" \
  "0-1" "$PCRT_POSTS-$(printf '%s\n' "$PCRT_OUT" | grep -c '^::warning::.*author could not be resolved')"

# 8-12. The withheld-request announcement (MODE=announce). It posts nothing, mints
# nothing, and names which dependency withheld the request. Every arm exits 0.
pcrt_announce() {  # $1=test result  $2=lint result -> $PCRT_ANN, $PCRT_ANN_RC
  PCRT_ANN="$(env MODE=announce PR=7 HEAD_SHA="$PCRT_SHA" TEST_RESULT="$1" LINT_RESULT="$2" bash "$PCRT" 2>/dev/null)"
  PCRT_ANN_RC=$?
}

# 8. test success, lint failure -> no post, warning naming lint (NOT test/both).
pcrt_announce success failure
assert_eq "pcrt #990-8: test ok, lint red -> warning names lint, posts nothing (exit 0)" \
  "1-0-0" "$(printf '%s\n' "$PCRT_ANN" | grep -cF '— lint did not conclude success')-$(printf '%s\n' "$PCRT_ANN" | grep -c 'posted the review trigger')-$PCRT_ANN_RC"

# 9. lint success, test failure -> warning naming test.
pcrt_announce failure success
assert_eq "pcrt #990-9: lint ok, test red -> warning names test (exit 0)" \
  "1-0" "$(printf '%s\n' "$PCRT_ANN" | grep -cF '— test did not conclude success')-$PCRT_ANN_RC"

# 10. both failing -> warning naming both.
pcrt_announce failure failure
assert_eq "pcrt #990-10: both red -> warning names test and lint (exit 0)" \
  "1-0" "$(printf '%s\n' "$PCRT_ANN" | grep -cF '— test and lint did not conclude success')-$PCRT_ANN_RC"

# 11. both succeeding via announce -> NO warning (negative control; the post path
#     owns the both-green case, and the step condition keeps announce off it). A
#     low-noise ::notice:: breadcrumb IS emitted so a miswired consumer is not left
#     with a pure silent skip — assert exactly that (no warning, one notice).
pcrt_announce success success
assert_eq "pcrt #990-11: both green via announce -> no warning, one breadcrumb notice, exit 0" \
  "0-1-0" "$(printf '%s\n' "$PCRT_ANN" | grep -c '^::warning::')-$(printf '%s\n' "$PCRT_ANN" | grep -c '^::notice::.*nothing withheld')-$PCRT_ANN_RC"

# 12. every announce arm exits 0 (the always-exit-0 contract) — each arm above now
#     asserts its own $PCRT_ANN_RC, so this is the consolidated restatement.
pcrt_announce failure failure
assert_eq "pcrt #990-12: announce always exits 0" "0" "$PCRT_ANN_RC"

# 12b. Empty-`login` marker comment maps to the fail-closed sentinel IN JQ (a code
#      reviewer fail-open gap): the stub bypasses jq, so assert the real jq mapping
#      directly — a null user and an empty-string login both yield the sentinel, so
#      the bash UNVERIFIABLE arm (not the fail-open "no match -> post") is taken.
PCRT_JQ_FILTER='(if (.user.login // "") == "" then "__prflow_no_author__" else .user.login end)'
assert_eq "pcrt #990-12b: an empty-string comment login maps to the fail-closed sentinel in jq" \
  "__prflow_no_author__" "$(printf '%s' '{"user":{"login":""}}' | jq -r "$PCRT_JQ_FILTER")"
assert_eq "pcrt #990-12c: a null comment user maps to the fail-closed sentinel in jq" \
  "__prflow_no_author__" "$(printf '%s' '{"user":null}' | jq -r "$PCRT_JQ_FILTER")"

rm -rf "$PCRT_SB"

# --- the snippet-to-job agreement predicate (issue #990 Part A) --------------
# structural-pin-ok: cross-file-phase-contract -- the agreement predicate guards a
# MACHINE-CONSUMED cross-file contract (a consumer copies BYTES out of the doc
# snippet, so the copy is unavoidable and the extractor keeps the doc snippet and
# the auto_review_trigger job region from drifting); it is not a prose-presence pin.
CIREV_EX="$LIB/test/extract-ci-review-agreement.py"
CIREV_DOC="$LIB/../docs/internal/workflow-triggers.md"
CIREV_CI="$LIB/../.github/workflows/ci.yml"
cirev() { python3 "$CIREV_EX" "$1" "$2" 2>/dev/null; }

# 13. The real doc snippet and the real ci.yml job agree on the compared element set.
assert_eq "pcrt #990-13: doc snippet and auto_review_trigger job agree on the compared element set" \
  "result=agree" "$(cirev "$CIREV_DOC" "$CIREV_CI")"

CIREV_TMP="$(mktemp -d)"
cp "$CIREV_DOC" "$CIREV_TMP/doc.md"
cp "$CIREV_CI" "$CIREV_TMP/ci.yml"

# 14. Planted-defect positive control: mutate ONE compared element on the doc side
#     only -> agreement turns RED.
sed 's/draft == false/draft == true/' "$CIREV_TMP/doc.md" > "$CIREV_TMP/doc-mut.md"
assert_eq "pcrt #990-14: mutating one compared element on one side turns agreement RED" \
  "result=disagree" "$(cirev "$CIREV_TMP/doc-mut.md" "$CIREV_TMP/ci.yml")"

# 15. Each of the six fail-closed input shapes turns the assertion RED (an error
#     token), never two-empty-extractions-agree.
grep -v 'prflow:ci-review-consumer-snippet' "$CIREV_TMP/doc.md" > "$CIREV_TMP/doc-absent.md"
assert_eq "pcrt #990-15a: snippet block absent -> RED" \
  "result=error:snippet-absent" "$(cirev "$CIREV_TMP/doc-absent.md" "$CIREV_TMP/ci.yml")"
printf '%s\n%s\n%s\n' '<!-- prflow:ci-review-consumer-snippet -->' '```yaml' '```' > "$CIREV_TMP/doc-empty.md"
assert_eq "pcrt #990-15b: snippet present but empty -> RED" \
  "result=error:snippet-empty" "$(cirev "$CIREV_TMP/doc-empty.md" "$CIREV_TMP/ci.yml")"
cp "$CIREV_TMP/doc.md" "$CIREV_TMP/doc-dup.md"
printf '\n%s\n' '<!-- prflow:ci-review-consumer-snippet -->' >> "$CIREV_TMP/doc-dup.md"
assert_eq "pcrt #990-15c: snippet duplicated -> RED" \
  "result=error:snippet-duplicated" "$(cirev "$CIREV_TMP/doc-dup.md" "$CIREV_TMP/ci.yml")"
printf '%s\n%s\n' '<!-- prflow:ci-review-consumer-snippet -->' 'name: not a fenced block' > "$CIREV_TMP/doc-unfenced.md"
assert_eq "pcrt #990-15d: snippet unfenced -> RED" \
  "result=error:snippet-unfenced" "$(cirev "$CIREV_TMP/doc-unfenced.md" "$CIREV_TMP/ci.yml")"
sed '/^  auto_review_trigger:/,$d' "$CIREV_TMP/ci.yml" > "$CIREV_TMP/ci-nojob.yml"
assert_eq "pcrt #990-15e: auto_review_trigger job region absent -> RED" \
  "result=error:job-absent" "$(cirev "$CIREV_TMP/doc.md" "$CIREV_TMP/ci-nojob.yml")"
printf '%s\n' 'jobs: [unbalanced' > "$CIREV_TMP/ci-bad.yml"
assert_eq "pcrt #990-15f: workflow unparseable as YAML -> RED" \
  "result=error:workflow-unparseable" "$(cirev "$CIREV_TMP/doc.md" "$CIREV_TMP/ci-bad.yml")"
rm -rf "$CIREV_TMP"

# 16. The vendored cone: the helper's `. lib/resolve-gh.sh` source succeeds under a
# tree restricted to the snippet's cone (the four closure files), so the vendored
# shape cannot silently take the degraded bare-`gh` arm while full-tree assertions
# pass. Absence of the "could not be sourced" breadcrumb is the positive proof.
CIREV_CONE="$(mktemp -d)"
mkdir -p "$CIREV_CONE/scripts" "$CIREV_CONE/lib"
cp "$LIB/../scripts/post-ci-review-trigger.sh" "$LIB/../scripts/post-issue-comment.sh" "$CIREV_CONE/scripts/"
cp "$LIB/resolve-gh.sh" "$LIB/resolve-bin.sh" "$CIREV_CONE/lib/"
CIREV_CONE_ERR="$(env -u DEVFLOW_GH MODE=compose PR=7 HEAD_SHA="$PCRT_SHA" bash "$CIREV_CONE/scripts/post-ci-review-trigger.sh" 2>&1 1>/dev/null)"
assert_eq "pcrt #990-16: helper sources resolve-gh.sh under the vendored cone (no degraded bare-gh breadcrumb)" \
  "no" "$(printf '%s' "$CIREV_CONE_ERR" | grep -qF 'resolve-gh.sh could not be sourced' && echo yes || echo no)"
rm -rf "$CIREV_CONE"

# DELIBERATELY NOT COVERED, and the absence is the decision (the issue-#843 rule).
# The calling job's eligibility guards — the fork gate, the draft test — the
# `!cancelled()` job `if:`, and the `concurrency` group added in issue #990 are all
# GitHub-evaluated expressions. No tool or consumer in this repository reads them,
# the suite cannot evaluate one, and a source-presence pin over them would be exactly
# the wording-only pin #375/#666/#810 prohibit. The compensating control is the
# review pass that reads the workflow, not a pin. What IS covered here is everything
# a program does read: the payload the detector parses, the post-or-skip arms, the
# author scoping, the announcement selection, and the doc↔job agreement predicate.

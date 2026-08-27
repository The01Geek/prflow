#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-ci-review-trigger.sh — post the bare standalone review-trigger comment on a
# pull request, at most once per head SHA.
#
# SOLE IN-REPO CALLER: the `auto_review_trigger` job in .github/workflows/ci.yml.
# That workflow is REPO-INTERNAL — install.sh's copy loop ships only devflow.yml
# and devflow-implement.yml, so no consumer repo has ci.yml. A consumer instead
# copies the documented `pull_request` job snippet
# into their OWN CI workflow and invokes this helper at its vendored path
# .prflow/vendor/prflow/scripts/post-ci-review-trigger.sh (materialized by the
# vendor-plugin composite action install.sh ships). Both callers pass the same
# environment contract below.
#
# Division of labour with the calling job:
#   * The job's `if:` decides ELIGIBILITY, entirely in GitHub-evaluated expressions
#     so no credential is minted for an ineligible run: a non-draft `pull_request`
#     whose head repo IS this repo (the fork gate), not dependabot, an App
#     configured, and (post path only) both CI jobs green.
#   * This helper owns the remaining POST-or-SKIP selection AND the withheld-request
#     announcement. Both are branch selections over a user-visible outcome, so they
#     live in a script the suite can drive arm by arm rather than inline in YAML —
#     the scripts/describe-denial-count.sh precedent CLAUDE.md names.
#
# CONTRACT
#   * ALWAYS exits 0 (best-effort notification; it must never redden CI). Every
#     no-post arm leaves a DISTINCT annotation naming the condition that fired, so
#     a silent no-op is impossible to confuse with a posted trigger.
#   * The idempotency read FAILS CLOSED. When the comment list cannot be
#     established the helper does NOT post. The two costs are asymmetric: a missed
#     notification is recoverable (a collaborator can still comment the trigger by
#     hand — the pre-existing supported path — and the next green head fires again),
#     while a duplicate is unrecoverable paid review spend that repeats on every
#     workflow re-run for as long as the read stays broken. A dedupe guard that
#     posts when it cannot verify has no bounding property at all, which is exactly
#     the "a guard whose comparand can be absent fails open where it claims to fail
#     closed" class CLAUDE.md warns about.
#   * A prior comment SUPPRESSES only when BOTH its author login matches the minting
#     App AND its body carries the complete marker for the current head SHA. The
#     author scoping closes the quoting-suppression hazard: before it, ANY comment
#     that merely quoted the marker (a human pasting it, a bot echoing it) killed
#     the review request. The comparand is EXPECTED_AUTHOR (the App slug); both the
#     bare slug and the `<slug>[bot]` login form match, mirroring
#     scripts/authorize-actor.sh's actor_bare handling. An EMPTY EXPECTED_AUTHOR, or
#     a marker comment whose author cannot be resolved, fails CLOSED (no post +
#     warning) in the SAME direction as the idempotency read — an unestablished
#     comparand must never widen the mechanism into duplicate-posting on every
#     re-run.
#   * The success annotation is gated on post-issue-comment.sh's own success
#     breadcrumb, never on its exit code — that helper is best-effort and always
#     exits 0, so a failed POST would otherwise be annotated as a fired trigger
#     (the review stall backstop's issue-#408 lesson).
#
# THE PAYLOAD IS DELIBERATELY BARE: the SHA-keyed dedupe marker, a blank line, and
# the plain review command alone on its own line. Nothing else. devflow.yml's gate
# substring-tests the WHOLE body, detect-standalone-command.sh requires the command
# to be the sole content of its line, and any extra prose is a hazard rather than a
# courtesy. It must never widen to the fix-loop command: that path mints an App
# token and pushes with it, and an App-token push is NOT covered by GitHub's
# recursion guard, so it would re-run CI, re-post, and loop without bound. The
# review path mints no App token (devflow.yml's `app-token` step is skipped on a
# `/prflow:review ` command) and pushes nothing.
#
# Inputs (env):
#   PR              the pull-request number the comment goes on (required, numeric)
#   HEAD_SHA        the reviewed head commit (required, lowercase hex 7..40) — it
#                   keys the marker, so dedupe is per-SHA and a new head re-notifies
#   MODE            `post` (default), `compose`, or `announce`
#   EXPECTED_AUTHOR (post mode) the minting App's slug — the app-slug output of the
#                   actions/create-github-app-token mint step in the calling job. A
#                   comment suppresses only when authored by this login (bare or
#                   `[bot]` form). Empty → fail closed.
#   TEST_RESULT     (announce mode) the `test` dependency's result
#   LINT_RESULT     (announce mode) the `lint` dependency's result
#   GH_TOKEN        consumed by gh; the caller sets it to the minted App token
#
# MODE=compose writes ONLY the composed body to stdout and touches no network. It
# is the seam the suite drives the payload contract through, so the body the test
# inspects is byte-identical to the body a real run posts.
#
# MODE=announce writes ONLY a `::warning::` naming which dependency withheld the
# request (test, lint, or both) and touches no network. The calling job runs it on
# the step-level branch where a dependency did NOT conclude `success`, so a red
# `lint` — not a required status check, hence a mergeable PR — is announced instead
# of skipped in silence.
set -uo pipefail

_PCRT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# gh binary: the single-source execution-verified resolver; an explicit DEVFLOW_GH
# still wins with no probe, so the suite's stubs are untouched. Guarded source so a
# partial copy degrades with a breadcrumb instead of aborting under `set -u`.
# shellcheck source=../lib/resolve-gh.sh
. "$_PCRT_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  # Partial-copy degradation only: the `:-` form is the sanctioned fallback shape
  # — the #245 peer-completeness pin forbids a bare `:=gh` default.
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi

PR="${PR:-}"
HEAD_SHA="${HEAD_SHA:-}"
MODE="${MODE:-post}"

# Annotation sink. In `post`/`announce` mode the runner parses workflow commands off
# this step's stdout, so annotations go there. In `compose` mode stdout is reserved
# for the composed body — a breadcrumb mixed into it would corrupt the payload the
# caller is asking for — so they go to stderr instead.
_note() {  # $1=notice|warning  $2=message
  if [ "$MODE" = compose ]; then
    printf 'devflow: %s: %s\n' "$1" "$2" >&2
  else
    printf '::%s::%s\n' "$1" "$2"
  fi
}

# Validate BEFORE composing. HEAD_SHA is interpolated into the marker and into the
# jq filter that reads the comment list, so a non-hex value is refused rather than
# embedded: it keeps the marker's shape a machine-comparable constant and leaves
# the filter free of anything jq or the shell would treat as special. (EXPECTED_AUTHOR
# is NEVER interpolated into jq — it is compared in bash below — so it needs no such
# validate-before-interpolate step.)
case "$PR" in
  ''|*[!0-9]*)
    _note warning "ci auto-review trigger: PR number '$PR' is missing or non-numeric; no trigger comment posted."
    exit 0 ;;
esac
if ! [[ "$HEAD_SHA" =~ ^[0-9a-f]{7,40}$ ]]; then
  _note warning "ci auto-review trigger: head SHA '$HEAD_SHA' is missing or not a lowercase hex commit id; no trigger comment posted for PR #$PR."
  exit 0
fi

# --- MODE=announce ----------------------------------------------------------
# Compose the withheld-request warning. The selection lives here (not inline in
# ci.yml) so the suite can drive every dependency-result combination — the
# scripts/describe-denial-count.sh precedent. It posts nothing and mints nothing.
_describe_withheld() {  # $1=test result  $2=lint result — echoes the withheld set, or empty
  local t="$1" l="$2" withheld=""
  [ "$t" = success ] || withheld="test"
  [ "$l" = success ] || withheld="${withheld:+$withheld and }lint"
  printf '%s' "$withheld"
}
if [ "$MODE" = announce ]; then
  _WITHHELD="$(_describe_withheld "${TEST_RESULT:-}" "${LINT_RESULT:-}")"
  if [ -n "$_WITHHELD" ]; then
    _note warning "ci auto-review trigger: no review requested for PR #$PR at $HEAD_SHA — $_WITHHELD did not conclude success (test=${TEST_RESULT:-}, lint=${LINT_RESULT:-})."
  else
    # Both green in announce mode: the post path owns this case, so nothing is
    # withheld. This is reachable only from a MISWIRED caller (in this repo the
    # ci.yml announce step is gated to the not-both-success complement), so leave a
    # low-noise breadcrumb rather than a pure silent exit — a miswired consumer then
    # sees why no review was requested instead of nothing at all.
    _note notice "ci auto-review trigger: announce mode with both dependencies green for PR #$PR — nothing withheld; the post path (not announce) handles the both-green case."
  fi
  exit 0
fi

# The dedupe marker. Keyed on the head SHA, so a re-run over the SAME head is
# suppressed while every NEW green head notifies again — the deliberate design,
# not a first-time-only latch.
MARKER="<!-- prflow:ci-review-trigger sha=$HEAD_SHA -->"

# Compose the body. One function so `compose` mode and the POST path can never
# drift into two different payloads.
_compose_body() {
  printf '%s\n\n' "$MARKER"
  printf '/prflow:review\n'
}

if [ "$MODE" = compose ]; then
  _compose_body
  exit 0
fi

# --- MODE=post --------------------------------------------------------------
# Author comparand. A suppressing comment must be authored by the minting App;
# an empty comparand fails CLOSED (an author-blind match is exactly what the
# author-scoping criterion removes, so degrading to it on an empty value would
# re-open the hazard).
EXPECTED_AUTHOR="${EXPECTED_AUTHOR:-}"
if [ -z "$EXPECTED_AUTHOR" ]; then
  _note warning "ci auto-review trigger: the expected author login (app-slug) is empty; NOT posting for PR #$PR (fail-closed — an empty author comparand must not widen the trigger into duplicate-posting)."
  exit 0
fi

# --- PR-state guard (fail-closed, issue #1236) ------------------------------
# Do not request a review for a target nobody can act on. When CI goes green the
# caller fires this trigger unconditionally; if the pull request was merged or
# closed while CI was still running, the review run lands on a dead target — paid
# review spend (a full cloud agent run + model tokens) whose output has no reader.
# So establish the PR's state read-only and take the post path ONLY while it is
# still open. `{owner}/{repo}` placeholders (gh fills them from the git remote),
# NOT an interpolated $GITHUB_REPOSITORY — the same repos// collapse this file
# already guards against for the idempotency read (issue #664;
# lib/test/lint-gh-api-repo-path.py enforces it). The jq maps a merged PR (state
# `closed`, `merged` true) to `merged`, a closed-unmerged PR to `closed`, an open
# one whose GitHub auto-merge is armed (non-null `auto_merge`) to `automerge`, any
# other open one to `open`, and anything unresolvable to the empty string. `.merged`
# is tested first and `automerge` is emitted only for an open PR, so a merged or
# closed PR still carrying an auto_merge record takes its own arm (issue #2067).
#
# FAIL CLOSED on an unestablished state — the same asymmetry as the idempotency
# read and the author comparand: a missed notification is recoverable (a
# collaborator can still comment /prflow:review by hand), while review spend on an
# already-merged or closed target is not. Each no-post arm leaves its OWN distinct
# annotation naming the condition that fired. The state word is compared with a
# bash `case` (a builtin) — never `tr`/`sed`/`grep`, which are not preflight-
# guaranteed and would silently empty the decision (CLAUDE.md's non-preflight-tool
# rule, the same reason the idempotency decision below uses bash builtins only).
# Capture gh's stderr (mirroring the idempotency read below) so a maintainer
# investigating a silently-withheld auto-review sees the HTTP cause (403 rate-limit,
# 404, auth), not just "could not read". mktemp-guarded to /dev/null so the read
# still runs if scratch allocation fails.
STATE_ERR="$(mktemp 2>/dev/null || echo /dev/null)"
if ! PR_STATE="$("$DEVFLOW_GH" api "repos/{owner}/{repo}/pulls/${PR}" \
      --jq 'if .merged then "merged" elif (.state == "open" and .auto_merge != null) then "automerge" else (.state // "") end' 2>"$STATE_ERR")"; then
  _note warning "ci auto-review trigger: could not read PR #$PR state to check whether it is still open ($(tr '\n' ' ' < "$STATE_ERR")); NOT posting (fail-closed — review spend on an already-merged or closed target is unrecoverable, a missed notification is not)."
  [ "$STATE_ERR" = /dev/null ] || rm -f "$STATE_ERR"
  exit 0
fi
[ "$STATE_ERR" = /dev/null ] || rm -f "$STATE_ERR"
case "$PR_STATE" in
  open)
    : ;;  # still actionable — fall through to the idempotency read and post
  automerge)
    # Armed auto-merge merges at CI-green, racing this trigger onto a merged
    # target (issue #2067, PR #2059) — skip, like the merged/closed arms.
    _note warning "ci auto-review trigger: PR #$PR has GitHub auto-merge enabled and is set to merge once its required checks pass; NOT posting a review request (it would race the auto-merge onto a merged target nobody can act on). Comment /prflow:review by hand if a review is still wanted."
    exit 0 ;;
  merged)
    _note warning "ci auto-review trigger: PR #$PR is already merged; NOT posting a review request (its output would land on a merged target nobody can act on)."
    exit 0 ;;
  closed)
    _note warning "ci auto-review trigger: PR #$PR is closed without merging; NOT posting a review request (its output would land on a closed target nobody can act on)."
    exit 0 ;;
  *)
    _note warning "ci auto-review trigger: PR #$PR state could not be established (got '$PR_STATE'); NOT posting (fail-closed — review spend on a possibly-merged or closed target is unrecoverable, a missed notification is not)."
    exit 0 ;;
esac

# Login match, mirroring authorize-actor.sh's actor_bare handling: the App comment
# login is `<slug>[bot]` while the app-slug output is the bare `<slug>`, so compare
# both exact and bare-stripped forms in BOTH directions. This rests on
# create-github-app-token@v3's `app-slug` output being the slug portion of that
# `<slug>[bot]` login; if that output form ever changed, the App would stop
# recognizing its own comments and re-post — the coupling is deliberate, not implicit.
_login_matches() {  # $1=comment login  $2=expected comparand
  local login="$1" expect="$2"
  local login_bare="${login%\[bot\]}"
  local expect_bare="${expect%\[bot\]}"
  [ "$login" = "$expect" ] || [ "$login_bare" = "$expect_bare" ]
}

# --- Idempotency read (fail-closed) -----------------------------------------
# `{owner}/{repo}` placeholders, which gh fills from the git remote, NOT an
# interpolated $GITHUB_REPOSITORY: this file lives under scripts/ and so is a
# surface that can run outside Actions, where that variable has no producer and
# the path would collapse to `repos//issues/…` while gh wrote the HTTP error body
# to stdout (issue #664; lib/test/lint-gh-api-repo-path.py enforces it here).
# --paginate so a long-lived PR whose marker sits past page one is still seen.
# The filter emits ONE LINE PER marker-bearing comment: its author login, or the
# sentinel `__prflow_no_author__` when the comment carries no resolvable author
# (a login can contain neither underscores nor brackets, so the sentinel can never
# collide with a real one). An author that is null OR an empty string both map to
# the sentinel, so an empty-`login` marker comment takes the fail-closed UNVERIFIABLE
# arm rather than the fail-OPEN "no matching author -> post" one. bash then applies
# the author match — the author scoping is deliberately NOT in jq, so an unresolvable
# author is a distinguishable fail-closed case rather than a silently-dropped row.
LIST_ERR="$(mktemp 2>/dev/null || echo /dev/null)"
if ! LIST_OUT="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/issues/${PR}/comments" \
      --jq ".[] | select((.body // \"\") | contains(\"$MARKER\")) | (if (.user.login // \"\") == \"\" then \"__prflow_no_author__\" else .user.login end)" 2>"$LIST_ERR")"; then
  _note warning "ci auto-review trigger: could not read PR #$PR comments to check for an existing trigger ($(tr '\n' ' ' < "$LIST_ERR")); NOT posting (fail-closed — a duplicate standalone review is unrecoverable spend, a missed one is not)."
  [ "$LIST_ERR" = /dev/null ] || rm -f "$LIST_ERR"
  exit 0
fi
[ "$LIST_ERR" = /dev/null ] || rm -f "$LIST_ERR"

# Decide with bash builtins only. `tr`/`sed`/`wc` are not preflight-guaranteed, and
# a missing one would empty the pipeline and silently flip this selection — the
# un-guaranteed-tool trap CLAUDE.md names. (The `tr` above is inside a breadcrumb,
# where a missing tool only empties a diagnostic.)
#   ALREADY      an App-authored marker comment for THIS head exists → already posted
#   UNVERIFIABLE a marker comment exists whose author cannot be resolved → fail closed
# A marker comment authored by a DIFFERENT resolvable login sets neither, so the
# review still posts — that is the quoting-suppression fix.
ALREADY=false
UNVERIFIABLE=false
while IFS= read -r _login; do
  [ -z "$_login" ] && continue
  if [ "$_login" = "__prflow_no_author__" ]; then
    UNVERIFIABLE=true
    continue
  fi
  if _login_matches "$_login" "$EXPECTED_AUTHOR"; then
    ALREADY=true
  fi
done <<EOF
$LIST_OUT
EOF

if [ "$ALREADY" = true ]; then
  _note notice "ci auto-review trigger: PR #$PR already carries an App-authored trigger comment for $HEAD_SHA; nothing to post."
  exit 0
fi
if [ "$UNVERIFIABLE" = true ]; then
  _note warning "ci auto-review trigger: PR #$PR carries a marker comment for $HEAD_SHA whose author could not be resolved; NOT posting (fail-closed — an unestablished author comparand must not widen the trigger into duplicate-posting)."
  exit 0
fi

# --- Post -------------------------------------------------------------------
# Body through a FILE so newlines never traverse shell quoting. mktemp is guarded
# distinctly: an unguarded failure would leave BODY_FILE empty and misdiagnose as a
# POST failure.
BODY_FILE="$(mktemp)" || {
  _note warning "ci auto-review trigger: mktemp failed; could not compose the trigger comment for PR #$PR (nothing posted)."
  exit 0
}
_compose_body > "$BODY_FILE"

POST="$_PCRT_DIR/post-issue-comment.sh"
if [ ! -f "$POST" ]; then
  _note warning "ci auto-review trigger: post-issue-comment.sh absent at $POST; trigger comment not posted for PR #$PR."
  rm -f "$BODY_FILE"
  exit 0
fi
# post-issue-comment.sh is best-effort and ALWAYS exits 0, so its exit code is not a
# success signal. Gate the success annotation on its exact breadcrumb instead.
POST_OUT="$(bash "$POST" "$PR" "$BODY_FILE" 2>&1)"
printf '%s\n' "$POST_OUT"
rm -f "$BODY_FILE"
if printf '%s\n' "$POST_OUT" | grep -qxF "devflow: posted comment on #$PR"; then
  _note notice "ci auto-review trigger: posted the review trigger on PR #$PR for $HEAD_SHA."
else
  _note warning "ci auto-review trigger: the review trigger comment did NOT post on PR #$PR for $HEAD_SHA; no review was requested."
fi
exit 0

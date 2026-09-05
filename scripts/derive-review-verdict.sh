#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# derive-review-verdict.sh — derive the PRFlow Review verdict for the CURRENT
# HEAD, fail-closed. This is the small, testable unit extracted out of
# devflow-review.yml's finalize_check `success)` branch (issue #249): the
# workflow step calls it, and lib/test/run.sh drives it directly with a stubbed
# `gh` over the full input-shape matrix.
#
# The required `PRFlow Review` check must encode a positively-observed APPROVE
# for the commit under review. Everything else fails CLOSED so an un-reviewed
# HEAD never merges (in either direction):
#   - The engine ended in error (is_error) .................... incomplete
#   - No PR number / no HEAD SHA (unverifiable) .............. incomplete
#   - Unresolvable REPO (owner/name) (unverifiable) ......... incomplete
#   - Reviews-API / comments-API query failed, or their JSON
#     could not be parsed (unverifiable) .................... incomplete
#   - Only older-commit reviews / empty reviews for HEAD .... incomplete
#   - No HEAD review and no run id to scope the comment
#     fallback (unverifiable) ............................... incomplete
#   - A producer marker on HEAD whose `head=` names another
#     commit, or which cannot be parsed, or of which the body
#     carries two (unestablished) ....................... incomplete
#   - A producer marker on HEAD the reviews-API `state`
#     contradicts (unestablished) ...................... incomplete
#   - A producer marker on HEAD ..................... reject/approve
#   - A CHANGES_REQUESTED (or `## Verdict: REJECT`) ON HEAD .. reject
#   - An APPROVED (or `## Verdict: APPROVE`) review ON HEAD .. approve
#   - A DISMISSED or PENDING review ON HEAD is never the verdict (a dismissed
#     review is a human override; its stale body must not resurrect) — such
#     reviews are skipped as if absent
#   - No HEAD review, but this run's run-keyed progress
#     comment carries a `## Verdict:` line for HEAD ......... reject/approve
# `incomplete` is distinct from `reject`: finalize_check maps it to a blocking
# `failure` titled "Devflow review incomplete — re-run needed", and it NEVER
# triggers the stale-REJECT dismissal (only a positively-observed APPROVE does).
#
# Producer contract (skills/review/SKILL.md Phase 4.4) this consumes.
#
# THE FIRST SIGNAL IS THE PRODUCER MARKER (issue #1030). scripts/post-review-verdict.sh
# — never the reviewing agent — writes
#     <!-- prflow:review-verdict head=<40-hex> verdict=<APPROVE|REJECT> -->
# as line 1 of the review body it posts, and as the line immediately AFTER the run key in
# the run-keyed progress comment. Only the marker states WHOSE verdict this is; the
# reviews-API `state` and the `## Verdict:` prose below it remain, the first as the
# API-side signal and the second as the TRANSITIONAL shape for reviews already posted on
# long-lived open pull requests, which carry no marker. A census over 60 pull requests
# measured 6 of 9 real REJECT bodies matching no prose shape, which is why the prose can
# no longer be the identity.
#
# Marker reading is deliberately narrow and fail-closed, because a review body routinely
# QUOTES this contract (a finding on a pull request that touches the review engine):
#   - only the FIRST TWO lines of a body are scanned, which is where the producer writes
#     it (line 1 of a review, line 2 of a progress comment) and nowhere a fenced quote
#     lands; a quoted marker deeper in the body is prose and is never read;
#   - TWO marker-shaped lines within that window is `unestablished`, never a pick;
#   - a marker that does not match the exact literal shape (no `verdict=`, an out-of-enum
#     token, a marker split across lines) is `unestablished`, never a guess;
#   - a marker whose `head=` is not the HEAD under consideration is `unestablished` — the
#     marker head and the reviews-API `commit_id` can disagree as ordinary GitHub behavior
#     (GitHub can change a review's `commit_id` after submission — issue #1247), so this
#     deriver refuses to join on either key when they disagree and fails closed by decision,
#     accepting a re-review round each time a branch is updated after review;
#   - a marker the reviews-API `state` CONTRADICTS (marker REJECT on an APPROVED or
#     COMMENTED review, marker APPROVE on a CHANGES_REQUESTED one) is `unestablished`.
# Every one of those emits `incomplete`/`false` with its own breadcrumb.
#
# The emitter picks the review channel from the verdict token, so what reaches the
# reviews API is:
#   REJECT (any form) -> event REQUEST_CHANGES -> state CHANGES_REQUESTED, marker
#     `verdict=REJECT`, transitional body line `## Verdict: REJECT ...`
#   APPROVE with notes / CAVEAT / ADVISORY NOTES -> event COMMENT -> state COMMENTED,
#     marker `verdict=APPROVE`, transitional body line `## Verdict: APPROVE ...` (so a
#     positive APPROVE is NOT always state APPROVED — which is why a COMMENTED review
#     carrying either signal is admitted by the HEAD-selection filter below)
#   APPROVE (clean) -> event APPROVE -> state APPROVED, marker `verdict=APPROVE`
#   Same-identity self-review fallback (the review POST fails) -> the verdict is
#     recovered from THIS run's run-keyed `prflow:review-progress` PROGRESS
#     comment, which carries the marker on the line after its run key plus the full
#     report, and is the only artifact this helper matches in step 6 (it carries the
#     run-keyed `<!-- prflow:review-progress run=<id>- -->` marker). Issue comments
#     carry no commit_id, so scoping is by that run-keyed marker, never a historical
#     comment. NOTE: the emitter's own comment-channel fallback — the marker-stamped
#     body it posts when the review POST is refused — is a plain issue comment with no
#     run-keyed progress marker, so this helper does NOT read it. That is deliberate:
#     matching it un-scoped, across all issue comments, is exactly the stale-/
#     prior-run-verdict resurrection this HEAD-scoping fix removes, and the emitter
#     reports that channel to its caller instead so the gap is visible rather than
#     silently filled here.
#
# Inputs (environment; all optional, absence fails closed where it matters):
#   HEAD_SHA       current HEAD SHA (needs.precheck.outputs.head_sha)
#   ENGINE_ERROR   "true" if the review engine execution ended is_error
#   PR_NUMBER      the pull request number
#   REPO           owner/name (defaults to `$DEVFLOW_GH repo view` when empty)
#   GITHUB_RUN_ID  this workflow run id (scopes the comment fallback marker)
#
# Output (stdout, two lines, always emitted):
#   verdict=<approve|reject|incomplete>
#   verdict_determined=<true|false>
# `verdict_determined` is true only when a verdict was positively observed from a
# successful lookup; it gates finalize_check's irreversible stale-REJECT
# dismissal exactly as before. Every no-verdict/unverifiable path emits
# `incomplete`/`false` with a SPECIFIC stderr breadcrumb naming which condition
# fired. Always exits 0 (best-effort — the caller reads the verdict, not the
# exit code).
#
# $DEVFLOW_GH overrides the `gh` binary and $DEVFLOW_JQ the `jq` binary (the same
# seams the rest of devflow uses; both honored by the sourced resolvers below).

set -uo pipefail

_DRV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (documented partial-copy posture — see CLAUDE.md): a deployment
# carrying this file without its sibling lib/resolve-gh.sh must degrade to bare
# `gh` with a breadcrumb, never assign an empty DEVFLOW_GH from an undefined
# devflow_resolve_gh (which would misdirect the failure to the reviews query).
# shellcheck source=../lib/resolve-gh.sh
. "$_DRV_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
# Sourceability is not function-availability (a sibling can source clean yet not
# define the resolver) — verify the function itself before calling it.
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  # Partial-copy degradation only (resolver absent, breadcrumb above): the `:-`
  # form is the sanctioned fallback shape — the #245 peer-completeness pin
  # forbids the `:=gh` default precisely so full deployments route the resolver.
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi
# Guarded source (documented partial-copy posture — see CLAUDE.md): a deployment
# carrying this file without its sibling lib/resolve-jq.sh must degrade to bare
# `jq` with a breadcrumb, never leave DEVFLOW_JQ unbound and abort the next
# reference under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_DRV_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability (mirrors the gh guard above): a sibling
# that sources clean yet never assigns must still leave a usable jq — never a
# bare `set -u` abort that breaks the always-exit-0 / two-line stdout contract.
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

HEAD_SHA="${HEAD_SHA:-}"
ENGINE_ERROR="${ENGINE_ERROR:-false}"
PR_NUMBER="${PR_NUMBER:-}"
REPO="${REPO:-}"
RUN_ID="${GITHUB_RUN_ID:-}"

# The `## Verdict:` heading the skill writes as the verdict artifact's first
# line. REJECT is any `--request-changes`; APPROVE covers every approve form
# (APPROVE / APPROVE with notes / APPROVE WITH CAVEAT / APPROVE WITH ADVISORY
# NOTES) since they all begin with the word APPROVE.
REJECT_RE='^##[[:space:]]+Verdict:[[:space:]]*REJECT'
APPROVE_RE='^##[[:space:]]+Verdict:[[:space:]]*APPROVE'

# The producer marker (issue #1030). MARKER_STRICT_RE is the exact literal shape
# post-review-verdict.sh emits; MARKER_LOOSE_RE is anything CLAIMING to be one, so a
# malformed marker is caught and refused rather than silently ignored. Both are matched
# with bash's `[[ =~ ]]` — a builtin, so this SELECTION never depends on a
# non-preflight PATH tool (CLAUDE.md guard-class 2), and BASH_REMATCH does the field
# extraction with no `sed`/`cut` hop.
MARKER_STRICT_RE='^<!-- prflow:review-verdict head=([0-9a-fA-F]{40}) verdict=(APPROVE|REJECT) -->$'
MARKER_LOOSE_RE='^<!-- prflow:review-verdict[ >]'

emit() { printf 'verdict=%s\nverdict_determined=%s\n' "$1" "$2"; exit 0; }

# Read the producer marker out of a body, scanning ONLY its first two lines (see the
# header). Echoes exactly one token: the empty string (no marker — the caller falls
# through to the state/prose signals), `APPROVE`, `REJECT`, or one of the three
# unestablished tokens `ambiguous` / `malformed` / `head-mismatch`.
# Line splitting is pure parameter expansion for the same builtin-only reason.
drv_marker_verdict() {
  local body="$1" line1 line2 rest hits="" found=""
  line1="${body%%$'\n'*}"
  if [ "$body" = "$line1" ]; then
    line2=""
  else
    rest="${body#*$'\n'}"
    line2="${rest%%$'\n'*}"
  fi
  local l
  for l in "$line1" "$line2"; do
    [[ "$l" =~ $MARKER_LOOSE_RE ]] || continue
    hits="${hits}x"
    found="$l"
  done
  case "$hits" in
    '')  printf ''; return 0 ;;
    x)   ;;
    *)   printf 'ambiguous'; return 0 ;;
  esac
  if [[ ! "$found" =~ $MARKER_STRICT_RE ]]; then
    printf 'malformed'
    return 0
  fi
  if [ "${BASH_REMATCH[1]}" != "$HEAD_SHA" ]; then
    printf 'head-mismatch'
    return 0
  fi
  printf '%s' "${BASH_REMATCH[2]}"
}

# 1. Engine execution ended in error -> no verdict for HEAD, regardless of any
#    existing (necessarily older-commit) reviews.
if [ "$ENGINE_ERROR" = "true" ]; then
  echo "derive-review-verdict: review engine execution ended in error (is_error=true) — treating as no verdict for HEAD; concluding incomplete." >&2
  emit incomplete false
fi

# 2. Unverifiable without a PR number -> fail closed (was: default to success).
if [ -z "$PR_NUMBER" ]; then
  echo "derive-review-verdict: empty PR_NUMBER — verdict cannot be verified; failing closed (incomplete)." >&2
  emit incomplete false
fi

# 3. Without the HEAD SHA the verdict cannot be scoped to the current commit ->
#    fail closed rather than trusting a possibly-stale review.
if [ -z "$HEAD_SHA" ]; then
  echo "derive-review-verdict: empty HEAD_SHA — cannot scope the verdict to the current HEAD; failing closed (incomplete)." >&2
  emit incomplete false
fi

# Derive REPO if the caller did not pass it (the workflow always does; this keeps
# the unit runnable standalone). A failure here is unverifiable -> fail closed.
if [ -z "$REPO" ]; then
  REPO="$("$DEVFLOW_GH" repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "derive-review-verdict: could not resolve REPO (owner/name) — verdict unverifiable; failing closed (incomplete)." >&2
  emit incomplete false
fi

# 4. Query the reviews API. A failed query is unverifiable -> fail closed (this
#    reverses the prior default-to-success; deliberate per issue #249).
#    `--paginate` walks every page: GitHub returns reviews OLDEST-first, so on a
#    PR with >100 reviews a single page would cut off exactly the newest (HEAD)
#    review and fail-closed-wedge the PR with a misdiagnosing "no verdict"
#    breadcrumb. Paginated output is CONCATENATED arrays ("[...][...]"), which
#    the `-s`/`add` normalization in the jq filters below flattens.
if ! REVIEWS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/pulls/$PR_NUMBER/reviews?per_page=100" 2>/dev/null); then
  echo "derive-review-verdict: reviews API query failed for PR #$PR_NUMBER — verdict unverifiable; failing closed (incomplete)." >&2
  emit incomplete false
fi

# 5. HEAD-scoped selection: the LAST review whose commit_id equals HEAD_SHA. A
#    review on any earlier commit is never treated as the verdict (an empty
#    match set yields empty STATE/RBODY and falls through to the comment
#    fallback). Piped through jq (DEVFLOW_JQ) rather than gh --jq so the test
#    stub only has to echo JSON. A jq FAILURE (missing/broken jq, or a
#    200-but-non-array payload `map()` rejects) is NOT an empty match set: it
#    fails closed here with its own breadcrumb — falling through to the comment
#    fallback could emit a verdict without the reviews ever being consulted,
#    and the step-7 breadcrumb would misdiagnose a parse failure as "no verdict".
#    Only VERDICT-BEARING states are selected: a DISMISSED review is a human
#    override whose body still carries its old `## Verdict:` line — reading it
#    would resurrect a deliberately-dismissed verdict (the same Direction-1
#    wedge this helper exists to remove); a PENDING (or other non-verdict)
#    review interleaved on HEAD must not mask a real APPROVED/CHANGES_REQUESTED
#    posted just before it; and a COMMENTED review counts as verdict-bearing
#    ONLY when its body carries the `## Verdict:` marker (Phase 4.4's
#    approve-with-notes shape) — a plain human comment-review on HEAD must not
#    mask the bot verdict posted just before it. Excluded reviews fall through
#    like an empty set.
#    The leading `-s`/`add` normalizes the `--paginate` shape: slurp turns one
#    array into [[...]] and concatenated pages into [[...],[...]], and `add`
#    flattens both to one review list (a non-array payload with scalar values —
#    the real gh error-object shape — still errors in `map()`, keeping the parse
#    guard live; an all-empty input slurps to [] whose `add` yields null and
#    `map` then errors — fail-closed either way).
#    A COMMENTED review is admitted when its body carries EITHER the producer marker on
#    line 1 (issue #1030's approve-with-notes channel, the shape post-review-verdict.sh
#    emits) or the transitional `## Verdict:` heading — a plain human comment-review on
#    HEAD carries neither and still must not mask the bot verdict posted just before it.
DRV_STATE_FILTER='add | map(select(.commit_id == $h and (((.state // "") | IN("APPROVED","CHANGES_REQUESTED")) or (((.state // "") == "COMMENTED") and ((.body // "") | (test("(?:^|\\n)##[[:space:]]+Verdict:") or test("^<!-- prflow:review-verdict "))))))) | last'
if ! STATE=$(printf '%s' "$REVIEWS_JSON" | "$DEVFLOW_JQ" -rs --arg h "$HEAD_SHA" \
          "$DRV_STATE_FILTER | (.state // \"\")" 2>/dev/null); then
  echo "derive-review-verdict: reviews JSON could not be parsed (jq failed or the reviews payload was not an array) — verdict unverifiable; failing closed (incomplete)." >&2
  emit incomplete false
fi
if ! RBODY=$(printf '%s' "$REVIEWS_JSON" | "$DEVFLOW_JQ" -rs --arg h "$HEAD_SHA" \
          "$DRV_STATE_FILTER | (.body // \"\")" 2>/dev/null); then
  echo "derive-review-verdict: reviews JSON could not be parsed (jq failed or the reviews payload was not an array) — verdict unverifiable; failing closed (incomplete)." >&2
  emit incomplete false
fi

# 5b. THE PRODUCER MARKER IS THE FIRST SIGNAL on the HEAD review's body (issue #1030).
#     It is the only artifact that states whose verdict this is, so it is consulted
#     before the state and long before the transitional prose. Every unestablished
#     reading — two markers, a shape that does not parse, a head naming another commit,
#     or a reviews-API state that contradicts it — emits `incomplete`/`false` with its
#     own breadcrumb rather than a guess, exactly like every other arm in this helper.
RMARKER="$(drv_marker_verdict "$RBODY")"
case "$RMARKER" in
  ambiguous)
    echo "derive-review-verdict: the HEAD review body carries TWO prflow:review-verdict marker lines — which one states the verdict cannot be established; failing closed (incomplete)." >&2
    emit incomplete false ;;
  malformed)
    echo "derive-review-verdict: the HEAD review body carries a prflow:review-verdict marker that does not parse (no verdict= field, an out-of-enum verdict token, or a marker split across lines) — refusing to guess; failing closed (incomplete)." >&2
    emit incomplete false ;;
  head-mismatch)
    echo "derive-review-verdict: the HEAD review's prflow:review-verdict marker names a different head than the review's own commit_id ($HEAD_SHA) — the two verdict keys disagree, so the join is unsafe; failing closed (incomplete)." >&2
    emit incomplete false ;;
  REJECT)
    if [ "$STATE" = "APPROVED" ] || [ "$STATE" = "COMMENTED" ]; then
      echo "derive-review-verdict: the HEAD review's prflow:review-verdict marker says REJECT but the reviews API records state '$STATE' — the producer's own two signals contradict each other; failing closed (incomplete)." >&2
      emit incomplete false
    fi
    emit reject true ;;
  APPROVE)
    if [ "$STATE" = "CHANGES_REQUESTED" ]; then
      echo "derive-review-verdict: the HEAD review's prflow:review-verdict marker says APPROVE but the reviews API records state 'CHANGES_REQUESTED' — the producer's own two signals contradict each other; failing closed (incomplete)." >&2
      emit incomplete false
    fi
    emit approve true ;;
esac

# REJECT first (fail toward blocking): a CHANGES_REQUESTED, or a REJECT verdict
# marker, on the HEAD review. Herestrings, not `printf | grep -q`: under
# `set -o pipefail`, grep -q exits at the first match and a large body can give
# printf SIGPIPE (rc 141), nondeterministically reading a REAL marker as
# no-match — a full-report review body is exactly the large-body case.
if [ "$STATE" = "CHANGES_REQUESTED" ] || grep -qE "$REJECT_RE" <<<"$RBODY"; then
  emit reject true
fi
# Positively-observed APPROVE on HEAD: a clean APPROVED, or the APPROVE verdict
# marker on a COMMENTED (approve-with-notes/caveat) review.
if [ "$STATE" = "APPROVED" ] || grep -qE "$APPROVE_RE" <<<"$RBODY"; then
  emit approve true
fi

# 6. No verdict review on HEAD. Fall back to THIS run's run-keyed progress
#    comment, which embeds the verdict line. Scope by the run marker (issue
#    comments carry no commit_id), so a prior run's verdict comment is ignored.
if [ -z "$RUN_ID" ]; then
  echo "derive-review-verdict: no HEAD-scoped review verdict and GITHUB_RUN_ID is empty — cannot scope the comment fallback to this run; failing closed (incomplete)." >&2
  emit incomplete false
fi
if ! COMMENTS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/issues/$PR_NUMBER/comments?per_page=100" 2>/dev/null); then
  echo "derive-review-verdict: no HEAD-scoped review verdict and the issue-comments query failed for PR #$PR_NUMBER — failing closed (incomplete)." >&2
  emit incomplete false
fi

# The skill keys its live progress comment by `<!-- prflow:review-progress
# run=<RUN_ID>-<ATTEMPT> -->`, so matching the `run=<RUN_ID>-` prefix selects
# only this run's comment(s) across attempts.
MARKER="<!-- prflow:review-progress run=${RUN_ID}-"
# PRFlow writes the current spelling; every artifact created before the rename carries the superseded one and no body is rewritten, so readers accept BOTH (issue #1003).
MARKER_SUPERSEDED="<!-- devflow:review-progress run=${RUN_ID}-"
# Same jq fail-closed posture as step 5 (and the same `-s`/`add` pagination
# normalization — comments are also oldest-first, and >100 issue comments is the
# realistic case on a chatty PR): a parse failure must not be read as "no
# matching comment" and land in step 7's misdiagnosing breadcrumb.
if ! CBODY=$(printf '%s' "$COMMENTS_JSON" | "$DEVFLOW_JQ" -rs --arg m "$MARKER" --arg s "$MARKER_SUPERSEDED" \
          'add | map(select(((.body // "") | contains($m)) or ((.body // "") | contains($s)))) | last | (.body // "")' 2>/dev/null); then
  echo "derive-review-verdict: issue-comments JSON could not be parsed (jq failed or the comments payload was not an array) — verdict unverifiable; failing closed (incomplete)." >&2
  emit incomplete false
fi

# 6b. The producer marker is the first signal here too. On a COMMENT the marker's `head=`
#     is AUTHORITATIVE — an issue comment carries no API-side head — so a marker naming a
#     commit other than the HEAD under consideration means this run's comment describes a
#     different commit, and joining on it would publish a stale verdict. There is no state
#     to contradict the marker on this surface, so no contradiction arm applies.
CMARKER="$(drv_marker_verdict "$CBODY")"
case "$CMARKER" in
  ambiguous)
    echo "derive-review-verdict: this run's progress comment carries TWO prflow:review-verdict marker lines — which one states the verdict cannot be established; failing closed (incomplete)." >&2
    emit incomplete false ;;
  malformed)
    echo "derive-review-verdict: this run's progress comment carries a prflow:review-verdict marker that does not parse (no verdict= field, an out-of-enum verdict token, or a marker split across lines) — refusing to guess; failing closed (incomplete)." >&2
    emit incomplete false ;;
  head-mismatch)
    echo "derive-review-verdict: this run's progress comment carries a prflow:review-verdict marker naming a head other than $HEAD_SHA — the comment describes a different commit; failing closed (incomplete)." >&2
    emit incomplete false ;;
  REJECT) emit reject true ;;
  APPROVE) emit approve true ;;
esac

# Herestrings for the same SIGPIPE/pipefail reason as the review-body greps.
if grep -qE "$REJECT_RE" <<<"$CBODY"; then
  emit reject true
fi
if grep -qE "$APPROVE_RE" <<<"$CBODY"; then
  emit approve true
fi

# 7. Nothing positively observed for HEAD -> incomplete (the PR #250 verdict-less
#    stall lands here: a run-keyed progress comment frozen at "Verdict: (pending)"
#    matches neither marker).
echo "derive-review-verdict: no verdict for HEAD (no HEAD-scoped review state and no run-keyed verdict comment for this run) — concluding incomplete." >&2
emit incomplete false

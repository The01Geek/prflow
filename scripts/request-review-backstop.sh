#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# request-review-backstop.sh — decide whether the cloud review stall backstop
# should fire a bounded no-verdict auto-resume, and if so emit the re-trigger
# marker for the CURRENT head (issue #408).
#
# The review-side sibling of the /devflow:implement stall backstop
# (scripts/stall-backstop-decide.sh + devflow-implement.yml). A headless review
# run can end "success" with NO verdict — the SDK session ends the moment the
# model emits a tool-call-free turn (e.g. after ScheduleWakeup while an agent is
# still pending), so the required `PRFlow Review` check fails "incomplete —
# re-run needed" and a human must manually re-trigger. This helper owns the
# ENTIRE fire/no-fire decision — config read, verdict guard, attempt count, App-
# token guard, marker construction — so lib/test/run.sh can drive every arm
# deterministically (an inline `case` in YAML is untestable; the same rationale
# as scripts/describe-denial-count.sh). The workflow arms only mint the token,
# call this helper, and post the comment on a `fire` decision.
#
# Inputs (environment; all optional; every unresolved input EXCEPT VERDICT fails
# toward no-fire — an unresolved VERDICT defaults to the eligible `incomplete`
# (below), but the missing-scope / App-token guards then keep the AGGREGATE
# decision at no-fire when the caller supplied nothing else):
#   VERDICT            the derived verdict for HEAD: approve|reject|incomplete.
#                      Only `incomplete` (no positively-observed verdict) is
#                      eligible; approve/reject is a decided end → no-fire. The
#                      helper guards on this itself so the guarantee-class test
#                      can drive "verdict=approve → no-fire" directly, rather than
#                      relying only on the caller's incomplete-arm placement.
#   HEAD_SHA           the reviewed commit (scopes the attempt-count markers).
#   PR_NUMBER          the pull request number (carries the review comments).
#   REPO               owner/name (defaults to `$DEVFLOW_GH repo view` when empty).
#   APP_TOKEN_PRESENT  "true" when a workflow-capable App token authored the call.
#                      A GITHUB_TOKEN-authored comment never re-triggers a
#                      workflow (GitHub suppresses recursive GITHUB_TOKEN events),
#                      so without the App token an auto-resume would be an inert
#                      green no-op — degrade to today's dead-end flip instead.
#
# Config read (scripts/config-get.sh, which applies the documented defaults on the
# soft paths — missing file / absent-or-empty key):
#   prflow_review.stall_backstop.enabled            default true
#   prflow_review.stall_backstop.max_resume_attempts default 2
#
# Output (stdout, four `key=value` lines, always emitted):
#   decision=<fire|no-fire>
#   reason=<the arm that decided — each `emit` call below names its own reason>
#   attempt=<next attempt number, only on a fire>
#   marker=<the `<!-- prflow:review-backstop head=<sha> attempt=<n> -->` marker,
#           only on a fire — the workflow embeds it in the re-trigger comment>
# A distinct arm-naming breadcrumb is written to stderr on every path. Always
# exits 0 (best-effort — the caller reads `decision`, not the exit code).
#
# $DEVFLOW_GH overrides the `gh` binary and $DEVFLOW_JQ the `jq` binary (the same
# seams derive-review-verdict.sh uses; both honored by the sourced resolvers).

set -uo pipefail

_RRB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (documented partial-copy posture — see CLAUDE.md): a deployment
# carrying this file without its sibling lib/resolve-gh.sh must degrade to bare
# `gh` with a breadcrumb, never assign an empty DEVFLOW_GH from an undefined
# devflow_resolve_gh.
# shellcheck source=../lib/resolve-gh.sh
. "$_RRB_DIR/../lib/resolve-gh.sh" \
  || echo "devflow: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi
# Guarded source of the jq resolver (same posture): degrade to bare `jq` rather
# than leaving DEVFLOW_JQ unbound and aborting the next reference under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_RRB_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

CONFIG_GET="$_RRB_DIR/config-get.sh"

VERDICT="${VERDICT:-incomplete}"
HEAD_SHA="${HEAD_SHA:-}"
PR_NUMBER="${PR_NUMBER:-}"
REPO="${REPO:-}"
APP_TOKEN_PRESENT="${APP_TOKEN_PRESENT:-false}"

emit() { # decision reason [attempt] [marker]
  printf 'decision=%s\nreason=%s\nattempt=%s\nmarker=%s\n' "$1" "$2" "${3:-}" "${4:-}"
  exit 0
}

# 1. A positively-observed verdict is a decided end — never resume a REJECT or an
#    APPROVE (this guard is why finalize_check may call the helper unconditionally
#    on any arm; it is also the "never fires when a verdict exists" invariant).
case "$VERDICT" in
  approve|reject)
    echo "request-review-backstop: verdict '$VERDICT' positively observed for HEAD ${HEAD_SHA:-<unknown>} — a decided end; no auto-resume." >&2
    emit no-fire verdict-exists
    ;;
esac

# Resolve config. config-get.sh applies the documented defaults on the soft paths
# (missing file / absent-or-empty key) and prints empty on a HARD failure
# (malformed config / missing python3) — catch that and supply the safe default
# here, so a hard failure resolves toward ENABLED (the honest-failure direction).
# The empty-when-unset CONFIG_FILE passthrough is config-get's own contract: it
# gates on a NON-EMPTY 3rd arg (`[ -n "${3:-}" ]`), so an empty value selects the
# repo-root default (the workflow's case) while a non-empty CONFIG_FILE is honored
# verbatim (issue #295) — which is how lib/test/run.sh drives the disabled arm.
CFG_FILE="${CONFIG_FILE:-}"
ENABLED="$(bash "$CONFIG_GET" .prflow_review.stall_backstop.enabled true "$CFG_FILE" 2>/dev/null || true)"
[ -n "$ENABLED" ] || ENABLED=true
MAX="$(bash "$CONFIG_GET" .prflow_review.stall_backstop.max_resume_attempts 2 "$CFG_FILE" 2>/dev/null || true)"
# A negative or non-integer cap resolves to the documented default 2 (the
# `^[0-9]+$` test rejects a leading "-", so "-1" falls back). 0 is honored.
[[ "$MAX" =~ ^[0-9]+$ ]] || MAX=2

# 2. Disabled only on the exact literal "false" (the #312 valid-falsy row): a real
#    JSON `false` must disable the backstop, and any OTHER value (the default
#    `true`, an unrecognized string) stays enabled — an `// true`-style coercion
#    that ignores explicit false is the bug this arm exists to prevent.
if [ "$ENABLED" = "false" ]; then
  echo "request-review-backstop: prflow_review.stall_backstop.enabled is false — backstop disabled; degrading to the dead-end flip." >&2
  emit no-fire disabled
fi

# 3. Without a PR number and HEAD SHA the markers cannot be scoped or counted —
#    fail toward no-fire rather than resume on an unscoped guess.
if [ -z "$PR_NUMBER" ] || [ -z "$HEAD_SHA" ]; then
  echo "request-review-backstop: empty PR_NUMBER or HEAD_SHA — cannot scope the backstop to a head; no fire." >&2
  emit no-fire unscoped
fi

# Derive REPO if the caller did not pass it (the workflow always does).
if [ -z "$REPO" ]; then
  REPO="$("$DEVFLOW_GH" repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "request-review-backstop: could not resolve REPO (owner/name) — cannot count prior attempts; no fire." >&2
  emit no-fire unscoped
fi

# 4. The re-trigger comment MUST be authored by a workflow-capable App token; a
#    GITHUB_TOKEN-authored comment posts fine but never re-triggers the workflow,
#    so a "resume" without the App token would be a masked green no-op. This guard
#    is a pure env check and decisive regardless of the attempt count, so it runs
#    BEFORE the paginated comment fetch below — on the common no-App-token path
#    (DEVFLOW_APP_ID unset) that skips the network call entirely. It sits after
#    the disabled/unscoped guards so those keep their more-specific reasons.
if [ "$APP_TOKEN_PRESENT" != "true" ]; then
  echo "request-review-backstop: no App token available (DEVFLOW_APP_ID unset / mint skipped) — a GITHUB_TOKEN-authored comment cannot re-trigger the review workflow; degrading to the dead-end flip." >&2
  emit no-fire no-app-token
fi

# 5. Count existing backstop markers for THIS head — the attempt cap. Each resume
#    comment carries `<!-- prflow:review-backstop head=<sha> attempt=<n> -->`;
#    only markers whose head is THIS HEAD_SHA count (a foreign-head marker from an
#    earlier commit must never inflate the count and spuriously exhaust the cap).
#    Read via gh api REST (repo-scoped-token rule — no GraphQL porcelain) and
#    counted with jq (robust to JSON escaping), same fail-closed posture as
#    derive-review-verdict.sh: an unreadable count must not read as "0 attempts"
#    and resume unbounded.
MARKER_PREFIX="<!-- prflow:review-backstop head=${HEAD_SHA} "
# PRFlow writes the current spelling; a resume comment posted before the rename
# carries the superseded one and no body is rewritten (issue #1003). The count is
# the UNION of both -- counting only one spelling would RESET the cap across the
# rename boundary and grant up to MAX extra auto-resumes for a head that had
# already exhausted it. `select(A or B)` is a union over comments, not a sum over
# spellings, so a single comment carrying both is still counted once.
MARKER_PREFIX_SUPERSEDED="<!-- devflow:review-backstop head=${HEAD_SHA} "
if ! COMMENTS_JSON=$("$DEVFLOW_GH" api --paginate "repos/$REPO/issues/$PR_NUMBER/comments?per_page=100" 2>/dev/null); then
  echo "request-review-backstop: issue-comments query failed for PR #$PR_NUMBER — the attempt count is unknowable, so the cap cannot be enforced; failing closed to no-fire (never resume on an unread count)." >&2
  emit no-fire count-unreadable
fi
# `-s`/`add` normalizes the `--paginate` shape (one array → [[...]], concatenated
# pages → [[...],[...]]); a non-array error payload still errors in `map()`,
# keeping the parse fail-closed rather than miscounting as 0.
if ! ATTEMPTS=$(printf '%s' "$COMMENTS_JSON" | "$DEVFLOW_JQ" -rs --arg m "$MARKER_PREFIX" --arg s "$MARKER_PREFIX_SUPERSEDED" \
      'add | map(select(((.body // "") | contains($m)) or ((.body // "") | contains($s)))) | length' 2>/dev/null); then
  echo "request-review-backstop: issue-comments JSON could not be parsed (jq failed or the comments payload was not an array) — the attempt count is unknowable; failing closed to no-fire." >&2
  emit no-fire count-unreadable
fi
[[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || ATTEMPTS=0

# 6. Enforce the cap. attempts >= max (including MAX=0: 0 >= 0) → exhausted; the
#    run degrades to the dead-end flip and a human re-triggers (the #356 flip
#    still runs, so the dead run is still visibly red — the backstop is additive).
if [ "$ATTEMPTS" -ge "$MAX" ]; then
  echo "request-review-backstop: $ATTEMPTS backstop attempt(s) already made for HEAD $HEAD_SHA >= cap $MAX — exhausted; no auto-resume (degrading to the dead-end flip)." >&2
  emit no-fire exhausted
fi

# Fire: emit the next attempt number and the marker the workflow embeds in the
# `/devflow:review` re-trigger comment.
NEXT=$((ATTEMPTS + 1))
MARKER="<!-- prflow:review-backstop head=${HEAD_SHA} attempt=${NEXT} -->"
echo "request-review-backstop: firing backstop resume attempt $NEXT of $MAX for HEAD $HEAD_SHA on PR #$PR_NUMBER." >&2
emit fire resume "$NEXT" "$MARKER"

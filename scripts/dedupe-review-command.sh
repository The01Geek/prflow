#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Decide whether THIS standalone `/prflow:review` command is redundant because a
# review of the same COMMIT is already IN FLIGHT — Candidate C of issue #989,
# made commit-scoped by issue #1010. The redundancy signal is the review engine's
# own seeded live progress comment (`<!-- prflow:review-progress run=<id>-<attempt> -->`,
# body `**Status:** 🚀 Reviewing`), which only the review engine authors and which
# exists from Phase 0.3.5, before any review work — so it detects an *in-flight*
# review directly, the redundancy that actually costs an engine run.
#
# Why the seeded comment (not a run-list or the `Reviewed HEAD` line):
#   - A thread-scoped `gh run list` keys on every comment in the repository (this
#     workflow starts a run per comment), so it suppresses on unrelated
#     conversation and, carrying no head, on a legitimate re-request after a push.
#   - The `Reviewed HEAD` line is stamped only at Phase 4, so it identifies a
#     COMPLETED review, never an in-flight one. Its documented meaning is "a
#     review FINISHED at this head" and two consumers depend on that meaning
#     (skills/review/phases/phase-0-3-6-blocker-recheck.md precondition 2, and
#     scripts/build-experiment-records.py's REVIEWED_HEAD_RE join), so it is not
#     the vehicle for a seed-time head and is left untouched.
# Only the review engine writes the seeded comment, so the candidate population is
# reviews rather than conversation, and no `run-name` / command-class matcher is
# needed. (See issue #989's Decision section.)
#
# THE SEED-TIME HEAD KEY (issue #1010). The engine stamps a distinct, machine-only
# producer key into the SAME comment at seed time — an HTML-comment marker
# `<!-- prflow:review-seeded-head <sha> -->`, invisible in the rendered comment and
# carried in the template, so every in-place rewrite re-emits it while the review
# is in flight. The value is the PR's API `headRefOid` as resolved at Phase 0.2
# BEFORE any caller head-override, which is the same quantity `review_dedupe`
# resolves for the incoming request; that is what keeps accepted cost 2 below
# intact when a /prflow:review-and-fix fix loop reviews a locally-committed,
# unpushed head. Detect mode compares the two as an EXACT delimited match, so a
# review of a different head no longer suppresses this request. A candidate that
# carries no such key — an in-flight review seeded by an older installed copy —
# fails OPEN with a breadcrumb naming the key; head-scoped suppression is never
# assumed on a head that could not be established.
#
# Two accepted, deliberate costs (issue #989; the third, pull-request scope, was
# recorded on PR #993's review and RETIRED by issue #1010):
#   1. Configuration-dependent: with prflow_review.live_progress_comment_enabled
#      off there is no seeded comment, so this fails OPEN (no suppression) — the
#      direction this job is already contractually required to take. The
#      absent-signal path still emits a breadcrumb.
#   2. Cross-class: a /prflow:review-and-fix run that SEEDS a live PR progress
#      comment seeds the SAME comment this detector reads, so a /prflow:review
#      issued during one is suppressed. This is correct — the review-and-fix run
#      executes the review engine, so the suppressed review would have been
#      redundant. It holds ONLY for a hosting run that seeds such a live PR
#      progress comment, and only for as long as the PR remote head is the one
#      that run seeded on; once the fix loop PUSHES, the remote head has
#      genuinely moved and a request for that new head is a review of a commit
#      nothing is reviewing, which the commit scope correctly lets through. A
#      host that seeds NO PR comment does not suppress at all — see THE
#      WORKPAD-SURFACED HOST below.
#
# THE PRE-SEED WINDOW (issue #1479). The seeded progress comment this detector
# reads is published by the review ENGINE at Phase 0.3.5 — inside the peer run's
# agent job, after that run's config/gate/command jobs, checkout, plugin vendoring
# and agent Phases 0.1-0.3 — so it does NOT exist for a period after the peer run
# starts. A request arriving in that window sees no in-flight comment and reaches
# the "no in-flight review … manual review proceeds" arm below: the detector FAILS
# OPEN through the window, and a second full cloud review of the same head is paid
# for. Observed once, as a dated measurement rather than a standing property of the
# system: 141 seconds between a peer's `command` job starting and its progress
# comment appearing on PR #1469 (2026-08-09).
#   DECIDED in-window behavior (issue #1479): fail open — suppress=false with the
#   "manual review proceeds" notice — is KEPT, unchanged, for a request whose head
#   matches a peer that has started and seeded nothing. It was chosen over the two
#   candidates issue #1479 recorded and ruled out: (a) keying suppression on the
#   ABSENCE of a progress comment — an absence carries no updated_at, so
#   REVIEW_INFLIGHT_MAX_AGE_MINUTES cannot age it out, and a peer whose seed
#   silently failed would then wedge EVERY later request at that head forever behind
#   a notice promising a review that never publishes; (b) a head-blind thread scope
#   — it suppresses on unrelated conversation and, carrying no head, on a legitimate
#   re-request after a push (the same scope the header above records as retired).
#   Fail-open matches this helper's uniform direction (below) and costs only a
#   recoverable duplicate run, never a swallowed review. The window is therefore a
#   TRANSIENT timing exposure that self-heals the instant the peer seeds — NOT a
#   numbered member of the two standing accepted costs above, whose ordinal "3"
#   still denotes the pull-request scope retired by issue #1010.
#
# THE WORKPAD-SURFACED HOST (issue #1657). Caller-scoped progress routing lets a
# review-and-fix run choose its progress surface: an implement-hosted fix loop
# binds progress_surface = workpad and, per the review engine at Phase 0.3.5,
# seeds NO live PR progress comment at all — the caller issue workpad is the
# progress surface instead. This detector reads only PR comments, so for such a
# host there is no seeded comment to find and the cost-2 suppression above does
# NOT hold: a /prflow:review issued during an implement-hosted review FAILS OPEN
# for the WHOLE duration of that review, not merely the transient pre-seed window
# above.
#   DECIDED behavior (issue #1657): fail open is KEPT, unchanged. No new in-flight
#   marker is stamped for the workpad-surfaced case — the alternatives are the
#   same two the #1479 block records and rules out (absence-keyed suppression
#   carries no updated_at to age out and would wedge every later request behind a
#   seed that silently failed, and a head-blind thread scope over-suppresses), and
#   fail-open matches the uniform direction of this helper (below), costing only a
#   recoverable duplicate run, never a swallowed review. Like the pre-seed window,
#   this is an accepted fail-open exposure that self-clears when the host review
#   ends — NOT a numbered member of the two standing accepted costs above.
#
# GitHub-native `concurrency` is NOT the mechanism (shared repository doctrine —
# see scripts/dedupe-implement-run.sh's header):
# `cancel-in-progress: true` cancels the in-flight run (wrong run) and `false`
# QUEUES the duplicate so it eventually runs (not ignored). GitHub has no
# "skip if already running" primitive, so both PRFlow duplicate checks — the
# implement path's and this command path's — detect duplicates themselves.
#
# MODES
#   MODE=detect (default) — decide suppression from the PR's comments.
#     Output (one key=value line on stdout; the workflow parses it with bash
#     builtins, tests assert it directly):
#         suppress=true|false
#   MODE=notice — compose the user-facing suppression notice for a decided cause.
#     Output: `notice=<text>` on stdout. The composition lives HERE, not in an
#     inline workflow `NOTE=` assignment, so the suite can drive the PRODUCED
#     message (a grep over an inline literal protects the literal, not the message
#     a rewording produces). CAUSE ∈ legacy-check-run|legacy-workflow-run|
#     inflight-review; HEAD is the resolved head SHA, whose first 7 chars every
#     cause shows — all three suppressions are head-scoped since issue #1010.
#
# Inputs (env):
#   MODE           detect (default) | notice.
#   HEAD           the resolved head SHA of the PR this request targets. Required
#                  in BOTH modes since issue #1010: detect mode compares it
#                  against the seed-time head key, and an unusable value (empty or
#                  not a hex object name) fails OPEN with its own breadcrumb
#                  rather than suppressing on a head it could not establish.
#   REPO           owner/repo, for the `gh api` comments call (detect mode).
#   PR             the pull-request / thread number to inspect (detect mode). The
#                  workflow derives it as
#                  `github.event.issue.number || github.event.pull_request.number`.
#                  Since issue #1163 devflow.yml accepts issue_comment alone (which
#                  populates github.event.issue.number); the `|| pull_request.number`
#                  fallback is retained as a defensive form but is now degenerate.
#   RUN_ID         github.run_id of THIS run — a review-progress comment keyed to
#                  this run (run=<RUN_ID>-...) is excluded, so a run can never
#                  suppress on its own seeded comment.
#   TRIGGER_BODY   the triggering comment's body. A `/prflow:review` carrying the
#                  `<!-- prflow:review-backstop head=… attempt=… -->` marker is a
#                  no-verdict auto-resume posted from inside a still-active run;
#                  it is NEVER suppressed (that run's own progress comment would
#                  otherwise read as an active peer and swallow the resume).
#   REVIEW_INFLIGHT_MAX_AGE_MINUTES   liveness bound (default 120). A review run
#                  updates its progress comment per phase, so an in-flight run's
#                  comment is fresh; a KILLED run leaves the comment frozen in
#                  `🚀 Reviewing`, so a comment whose `updated_at` is older than
#                  this bound is treated as stale/frozen, NOT in-flight (open
#                  question 1 of issue #989).
#   CAUSE          notice mode only (see MODE=notice above).
#   DEDUPE_NOW_EPOCH  test hook: fixes "now" for the liveness bound. When unset the
#                  jq `now` builtin is used.
#   DEVFLOW_GH     gh executable override for tests; resolved via lib/resolve-gh.sh
#                  when unset/empty.
#   DEVFLOW_JQ     jq executable override; resolved via lib/resolve-jq.sh.
#
# Fails OPEN in every direction: a missing input, a query error, an unparseable
# response, an unresolvable jq, or an absent signal all yield suppress=false with
# a SPECIFIC ::warning:: breadcrumb — because a missed suppression just reproduces
# the recoverable double-comment, whereas a wrong suppression silently swallows a
# review the user explicitly asked for. The value that DECIDES suppression is
# derived only with jq and bash builtins — never tr/sed/wc/cut/head — so a missing
# non-preflight PATH tool cannot yield an empty value that reads as "no duplicate".

set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ (issue
# #247); a copied/vendored deployment without lib/ falls back to bare `jq` with a
# breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

emit() { printf '%s=%s\n' "$1" "$2"; }

# The marker the review engine seeds its live progress comment with, and the
# in-flight status line it carries until the Phase-4 terminal flip. Kept identical
# to skills/review/SKILL.md's template (lib/test/run.sh pins the agreement).
PROGRESS_MARKER='<!-- prflow:review-progress'
# PRFlow writes the current spelling; every artifact created before the rename carries the superseded one and no body is rewritten, so readers accept BOTH (issue #1003).
PROGRESS_MARKER_SUPERSEDED='<!-- devflow:review-progress'
INFLIGHT_STATUS='🚀 Reviewing'
# The seed-time head producer key (issue #1010), kept identical to the marker line
# skills/review/SKILL.md's progress-comment template carries. Newly minted in the
# `prflow:` namespace: it has no pre-rename history, so there is deliberately NO
# superseded spelling and no dual-form reader here. A pre-#1010 comment carries no
# such key at all, which is the fail-open arm below, not a spelling question.
SEEDED_HEAD_MARKER='<!-- prflow:review-seeded-head'
# The marker a stall-backstop review auto-resume comment carries (kept identical
# to the marker scripts/request-review-backstop.sh produces; pinned agreeing).
BACKSTOP_MARKER='<!-- prflow:review-backstop'
BACKSTOP_MARKER_SUPERSEDED='<!-- devflow:review-backstop'

mode="${MODE:-detect}"

# ── notice composition ──────────────────────────────────────────────────────
# CRITICAL: every notice body must carry NO PRFlow trigger phrase (no `/prflow:`,
# `/devflow:`, `@claude`). Under the optional App token this comment fires a real
# issue_comment event, so a trigger substring here would re-enter the gate and
# loop. The legacy causes name the `PRFlow Review` check + its Re-run button
# because on a consumer whose installed copy predates the withheld tier those are
# the reader's real actions; the in-flight-review cause names its own reason.
if [ "$mode" = "notice" ]; then
  head7="${HEAD:0:7}"
  case "${CAUSE:-}" in
    legacy-check-run|legacy-workflow-run)
      emit notice "ℹ️ An automated **PRFlow Review** is already running for this commit (\`${head7}\`). Skipping this manual review command to avoid a duplicate review and double comments. Use the **Re-run** button on the \`PRFlow Review\` check if you need to re-review." ;;
    inflight-review)
      emit notice "ℹ️ A review of this commit (\`${head7}\`) is already in progress. Skipping this duplicate review command so the commit receives a single review — the in-progress review will post its verdict when it finishes. This check is commit-scoped: a review of a different commit is never skipped, so after pushing you can ask again and the new commit gets its own review." ;;
    *)
      echo "::warning::dedupe-review notice: unknown CAUSE '${CAUSE:-}'; emitting no notice." >&2
      emit notice ""
      exit 0 ;;
  esac
  exit 0
fi

# ── detect mode ─────────────────────────────────────────────────────────────

# A stall-backstop review auto-resume is NEVER suppressed: it is posted from
# inside a still-active run whose own seeded comment would otherwise read as an
# active peer. Match the marker in the triggering body (bash builtin substring).
case "${TRIGGER_BODY:-}" in
  *"$BACKSTOP_MARKER"*|*"$BACKSTOP_MARKER_SUPERSEDED"*)
    echo "::notice::dedupe-review: triggering comment carries the review-backstop marker (a no-verdict auto-resume); not suppressing." >&2
    emit suppress false
    exit 0 ;;
esac

repo="${REPO:-}"
pr="${PR:-}"
run_id="${RUN_ID:-}"
head="${HEAD:-}"
window_min="${REVIEW_INFLIGHT_MAX_AGE_MINUTES:-120}"

# Fail open on a missing/invalid thread key or repo: an unresolvable operand must
# never suppress. (RUN_ID is optional and always set in Actions; a missing one only
# weakens self-exclusion — `run=<id>-` becomes `run=-`, matching nothing — so it
# degrades to an empty string rather than aborting.)
if [ -z "$repo" ]; then
  echo "::warning::dedupe-review: REPO is unset; not suppressing (manual review proceeds)." >&2
  emit suppress false
  exit 0
fi
if ! [[ "$pr" =~ ^[0-9]+$ ]]; then
  echo "::warning::dedupe-review: PR thread number unresolved/invalid ('${pr}'); not suppressing (manual review proceeds)." >&2
  emit suppress false
  exit 0
fi
if ! [[ "$window_min" =~ ^[0-9]+$ ]]; then
  echo "::warning::dedupe-review: REVIEW_INFLIGHT_MAX_AGE_MINUTES ('${window_min}') is not a non-negative integer; not suppressing." >&2
  emit suppress false
  exit 0
fi
# The requested head is the comparand the whole commit scope rests on (issue
# #1010), so an unusable one fails OPEN rather than degrading to the old
# pull-request scope. The shape check is a bash regex over a hex object name: it
# rejects an empty value AND a non-SHA string whose bytes could otherwise land
# inside the delimited match below and suppress the wrong commit.
if ! [[ "$head" =~ ^[0-9a-fA-F]{7,64}$ ]]; then
  echo "::warning::dedupe-review: request HEAD unresolved/not an object name ('${head}'); commit scope cannot be established — not suppressing (fail-open)." >&2
  emit suppress false
  exit 0
fi
window_s=$(( window_min * 60 ))
# The EXACT delimited form the seeded key must carry for this request's head.
# Composed with bash parameter expansion (never a PATH tool), and closed by the
# marker's own ` -->` terminator so a requested head that is a strict PREFIX of
# the seeded one cannot match.
seed_match="$SEEDED_HEAD_MARKER $head -->"

# gh binary: resolved once via the single-source resolver (execution-verified); an
# explicit DEVFLOW_GH still wins, so test stubs are untouched. Sourced UNGUARDED —
# the repo convention forbids a bare `DEVFLOW_GH:=gh` fallback (the resolver is the
# single source; lib/test/run.sh's #245 pin enforces it), mirroring the sibling
# dedupe-implement-run.sh. A lib-less deployment that cannot source the resolver is
# a deployment-integrity failure; the fail-OPEN contract for it lives one level up,
# in devflow.yml's guarded helper invocation (a non-zero exit → CC=false + warning),
# not in a bare-gh fallback here. The detect-mode arms this header enumerates —
# query/parse/empty/jq/absent-signal — are what fail open in-helper.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
GH="$DEVFLOW_GH"

# List the PR's comments as RAW JSON (no `--jq`): the helper does ALL parsing in
# its own jq below, so the malformed-response matrix is exercised at the helper's
# boundary rather than swallowed by gh's own `--jq`. `--paginate` over a REST array
# endpoint concatenates the pages into one JSON array. A query failure fails OPEN
# with its own breadcrumb.
if ! comments_json="$("$GH" api --paginate "repos/$repo/issues/$pr/comments" 2>/dev/null)"; then
  echo "::warning::dedupe-review: comments query failed for PR #$pr; not suppressing (fail-open)." >&2
  emit suppress false
  exit 0
fi

# Distinguish an empty response from a genuinely-empty array: a degraded/empty read
# prints nothing (empty stdout), which is distinct from a genuinely-empty array `[]`.
if [ -z "$comments_json" ]; then
  echo "::warning::dedupe-review: comments query returned an empty response for PR #$pr; not suppressing (fail-open)." >&2
  emit suppress false
  exit 0
fi

# The deciding value is computed by jq and validated by a bash regex — never by a
# non-preflight PATH tool. `now` is jq's builtin; a test fixes it by passing a
# positive DEDUPE_NOW_EPOCH, which the program prefers over `now` — chosen ONCE
# inside jq (a single static program), never string-spliced.
jq_err="$(mktemp 2>/dev/null || echo /dev/null)"
# Program emits four space-separated integers:
#   <same-head match> <keyless> <other-head> <malformed>
# A candidate = a bot-authored, marker-carrying, 🚀 Reviewing comment not keyed to
# THIS run. It is LIVE when its updated_at parses and is within the liveness
# window, and MALFORMED when updated_at is absent/null/unparseable (so liveness
# cannot be established → fail open on it). The live set is then partitioned three
# ways on the seed-time head key (issue #1010), and the partition is total: every
# live candidate lands in exactly one of same-head / keyless / other-head, so an
# arm can never be silently dropped from the decision below.
decision="$("$DEVFLOW_JQ" -r \
  --argjson fixed_now "${DEDUPE_NOW_EPOCH:-0}" \
  --argjson window "$window_s" \
  --arg marker "$PROGRESS_MARKER" \
  --arg marker_superseded "$PROGRESS_MARKER_SUPERSEDED" \
  --arg status "$INFLIGHT_STATUS" \
  --arg seedmarker "$SEEDED_HEAD_MARKER" \
  --arg seedmatch "$seed_match" \
  --arg runself "run=${run_id}-" '
  def isprogress: ((.body // "") | type == "string") and (((.body // "") | contains($marker)) or ((.body // "") | contains($marker_superseded))) and ((.body // "") | contains($status)) and ((.user.type // "") == "Bot");
  def notself: ((.body // "") | contains($runself)) | not;
  def freshdate: (.updated_at // null) | (type == "string") and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T");
  def haskey: ((.body // "") | contains($seedmarker));
  def sameheadkey: ((.body // "") | contains($seedmatch));
  (if $fixed_now > 0 then $fixed_now else now end) as $n
  | if type != "array" then error("not-array")
  else
    ( [ .[] | select(isprogress) | select(notself) | select(freshdate)
          | select( ($n - (.updated_at | fromdateiso8601)) <= $window
                    and ($n - (.updated_at | fromdateiso8601)) >= 0 ) ] ) as $live
    | ( [ $live[] | select(haskey) | select(sameheadkey) ] | length ) as $m
    | ( [ $live[] | select(haskey | not) ] | length ) as $keyless
    | ( [ $live[] | select(haskey) | select(sameheadkey | not) ] | length ) as $other
    | ( [ .[] | select(isprogress) | select(notself) | select(freshdate | not) ] | length ) as $bad
    | "\($m) \($keyless) \($other) \($bad)"
  end' <<<"$comments_json" 2>"$jq_err")" || decision=""

# Collapse the captured stderr to one line with a bash builtin (`$(<file)` +
# parameter expansion), never `tr`: the breadcrumb SELECTED below (the case on
# $jq_diag) is a user-facing diagnostic, and a non-preflight tool that yields empty
# on its own absence would misattribute the cause (e.g. report "could not resolve
# jq" for a genuine parse error). The `not-array` sentinel below is a fixed literal,
# so the selection never depends on this collapse succeeding.
jq_diag_raw=""; [ -r "$jq_err" ] && jq_diag_raw="$(<"$jq_err")"
jq_diag="${jq_diag_raw//$'\n'/ }"
[ "$jq_err" = /dev/null ] || rm -f "$jq_err"

# An unresolvable jq (e.g. DEVFLOW_JQ pointed at a non-existent binary) or a parse
# error leaves $decision empty / non-conforming. Name jq explicitly so an empty
# decision is never read as "no duplicate".
if ! [[ "$decision" =~ ^[0-9]+\ [0-9]+\ [0-9]+\ [0-9]+$ ]]; then
  case "$jq_diag" in
    *not-array*)
      echo "::warning::dedupe-review: comments response was not a JSON array for PR #$pr; not suppressing (fail-open)." >&2 ;;
    *"No such file"*|*"not found"*|"")
      echo "::warning::dedupe-review: could not resolve jq (DEVFLOW_JQ='${DEVFLOW_JQ:-}'; ${jq_diag:-no diagnostic}); not suppressing (fail-open)." >&2 ;;
    *)
      echo "::warning::dedupe-review: could not parse the comments response for PR #$pr (jq: ${jq_diag}); not suppressing (fail-open)." >&2 ;;
  esac
  emit suppress false
  exit 0
fi

# Split the four fields with parameter expansion only (never cut/awk): the values
# below DECIDE suppression, so a missing non-preflight PATH tool must not be able
# to empty one and have it read as "no duplicate".
inflight="${decision%% *}"
_rest="${decision#* }"
keyless="${_rest%% *}"
_rest="${_rest#* }"
otherhead="${_rest%% *}"
malformed="${_rest#* }"

if [ "$malformed" -gt 0 ]; then
  echo "::warning::dedupe-review: $malformed in-flight review-progress comment(s) for PR #$pr carried an absent/unparseable updated_at; liveness could not be established for those — not counting them (fail-open)." >&2
fi

if [ "$keyless" -gt 0 ]; then
  echo "::warning::dedupe-review: $keyless in-flight review-progress comment(s) for PR #$pr carry no ${SEEDED_HEAD_MARKER} … --> key (seeded by an installed copy predating issue #1010), so the commit they are reviewing could not be established — not counting them (fail-open)." >&2
fi

if [ "$otherhead" -gt 0 ] && [ "$inflight" -eq 0 ]; then
  echo "::notice::dedupe-review: $otherhead in-flight review(s) for PR #$pr are reviewing a different head than $head; this request is a review of a commit nothing is reviewing — not suppressing." >&2
fi

if [ "$inflight" -gt 0 ]; then
  echo "::notice::dedupe-review: $inflight in-flight review(s) already running for PR #$pr at head $head; suppressing this duplicate /prflow:review." >&2
  emit suppress true
else
  echo "::notice::dedupe-review: no in-flight review of PR #$pr at head $head; manual review proceeds." >&2
  emit suppress false
fi

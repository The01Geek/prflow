#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-review-verdict.sh PR_NUMBER VERDICT BODY_FILE HEAD_SHA [PROGRESS_MARKER] [RUN_ROOT] — post a
# PRFlow Review verdict as a formal GitHub Pull Request review, stamping the producer's
# machine-readable ownership-plus-verdict marker on every durable surface it writes, and
# printing exactly one closed-vocabulary outcome line the caller routes on
# (issues #1059, #1030).
#
# WHY A HELPER, not an inline `gh pr review` fence (issues #1059, #857): Phase 4.4
# used to map the verdict to an unwrapped `gh pr review --request-changes|--comment|
# --approve` porcelain invocation whose outcome the review engine could observe only
# in its own per-turn transcript — a channel that reaches no durable artifact on the
# cloud tier. When that post failed on an APPROVE (observed on PR #1058), the approval
# survived only as prose in a `gh pr comment`, the PR stayed wedged at
# reviewDecision=CHANGES_REQUESTED, and NOTHING durable recorded that the post had
# failed. Moving the post into this helper — modelled on scripts/seed-review-progress.sh
# — gives it a closed outcome vocabulary the caller branches on, an error line captured
# from the failed API call, and a single-statement, leading-token shape the cloud matcher
# permits, so lib/test/run.sh can drive every path as ordinary shell.
#
# WHY IT STAMPS A MARKER (issue #1030). The reviews API carries the verdict as `state` and
# a `commit_id` (the reviewed head at submission time, but GitHub may re-point it on a later
# branch update — issue #433/#1247), but it does NOT carry WHOSE review it is. A consumer
# that must tell this engine's verdict from a human reviewer's — `dismiss-stale-rejections.sh`
# above all — was therefore forced to pattern-match prose the reviewing AGENT wrote at the top
# of the body, and a census over 60 pull requests measured 6 of 9 real REJECT bodies not
# matching. The missing artifact is a producer-emitted ownership-plus-verdict marker, so this
# helper composes it — the agent never does — and writes it as the FIRST line of every body it
# posts:
#
#   <!-- prflow:review-verdict head=<40-hex head sha> verdict=<APPROVE|REJECT> -->
#
# NAMESPACE. `<!-- prflow:` per issue #1003, with NO superseded `<!-- devflow:review-verdict`
# spelling accepted anywhere: this marker is introduced after the rename, so no persisted
# artifact can carry the old spelling. #1003's dual-read rule governs artifacts created BEFORE
# the rename (the `prflow:review-progress` / `devflow:review-progress` pair, untouched here).
#
# VERDICT FIELD. Normalized to two tokens. The human verdict line keeps the full enum
# (APPROVE, APPROVE with notes, APPROVE WITH CAVEAT, APPROVE WITH ADVISORY NOTES, REJECT);
# every approve-family verdict normalizes to `APPROVE` in the marker, matching what the
# consumers already collapse to.
#
# HEAD FIELD. The marker's `head=` records the commit this review actually reviewed. On a
# REVIEW artifact the reviews-API `commit_id` also names a commit, but GitHub can change that
# `commit_id` after submission (issue #1247), so the two can disagree as ordinary GitHub
# behavior — not a defect. The marker's `head=` is the field that records the reviewed tree; a
# consumer that must know which tree was reviewed reads it (see scripts/dismiss-stale-rejections.sh).
# On a COMMENT the marker's `head=` is authoritative, because an issue comment carries no
# API-side head.
#
# It posts through `gh api` REST (POST repos/{owner}/{repo}/pulls/{n}/reviews) rather than
# `gh pr review` porcelain, matching CLAUDE.md's rule for GitHub writes — the {owner}/{repo}
# placeholders are the ones `gh` fills from the git remote, NEVER an interpolated
# $GITHUB_REPOSITORY (which is empty outside Actions and collapses the path to `repos//…`).
# This is convention alignment, NOT a claim that porcelain caused the observed failure,
# which was never established (issue #1059's root-cause investigation is explicit on this).
# The body is passed as a FILE PATH, not an inline string, which removes the shell-quoting
# hazard for a report containing backticks, `$(`, and literal double quotes: when the file is
# the posted body (see BODY) its bytes are read by jq --rawfile and the marker line is
# prepended inside jq.
#
# CHANNEL SELECTION comes from the VERDICT token, never from the caller. The accepted token
# set and its mapping (bash `case` globs — builtins, so the screen holds on a stripped host):
#
#   verdict token                exit-channel        marker verdict=
#   REJECT / `REJECT …`          REQUEST_CHANGES     REJECT
#   APPROVE (exact, clean)       APPROVE             APPROVE
#   `APPROVE …` (any other       COMMENT             APPROVE
#     approve-family token)
#   REQUEST_CHANGES              REQUEST_CHANGES     REJECT   (the #1059 REST-event spelling,
#   APPROVE                      APPROVE             APPROVE   still accepted so an already-
#   COMMENT                      COMMENT             APPROVE   deployed caller keeps working)
#
# Anything else — including the empty string — is refused, issues no request, and takes
# SKIP unknown-event.
#
# BODY. With PROGRESS_MARKER set the helper looks the progress comment up before it posts: the
# last comment whose body STARTS WITH PROGRESS_MARKER. When the lookup finds it, the posted body is
# the stub `## Verdict: <VERDICT> — full report in PR comment` plus a two-line quote pointing at
# that comment. With no PROGRESS_MARKER, a comment not found or a failed lookup, it is BODY_FILE's
# bytes, less every line that starts with a run-key marker (`<!-- prflow:review-progress ` or
# `<!-- devflow:review-progress `) and then a first line that is a verdict marker. Either body is
# posted under this run's `<!-- prflow:review-verdict ` line, so this helper's lookup by a run-key
# marker never selects a posted body, and no line of a posted body starts with a run-key marker
# (one quoted inside a line is kept). BODY_FILE must be readable either way.
#
# CONTRACT — exactly one OUTCOME line per reachable path; on the paths that reach the
# progress-comment stamp, one PROGRESS line after it, then (POSTED APPROVE family only) one DISMISS
# line. The outcome vocabulary is closed and complete by construction, names the DURABLE
# CHANNEL that received the verdict, and has NO silent path:
#
#   stdout                            exit  meaning
#   POSTED review <event>             0     the formal review was created for <event>; the
#                                           durable channel that carries the verdict is the
#                                           review, and its body's line 1 is the marker
#   POSTED comment <event>            0     the review POST was refused, and the SAME
#                                           marker-stamped body was posted as a pull-request
#                                           comment instead; the durable channel is that
#                                           comment (the reviews API is unchanged, so a
#                                           consumer joining through it will not see this
#                                           verdict — the marker is what makes the comment
#                                           readable at all)
#   FAILED no-durable-channel <err>   1     BOTH channels were issued and refused, so no
#                                           review or comment carries this verdict, and the
#                                           progress comment is left untouched (no PROGRESS
#                                           line); <err> is the captured cause of each,
#                                           collapsed to one line
#   SKIP not-numeric                  3     the PR number is empty or non-numeric; no request
#   SKIP unknown-event                3     the verdict token is outside the accepted set
#                                           (INCLUDING the empty string); no request issued
#   SKIP head-not-sha                 3     the head argument is not exactly 40 hex characters,
#                                           so no honest marker can be composed; no request
#   SKIP body-file-unreadable         3     the body-file argument is absent or unreadable; no
#                                           request issued
#   SKIP evidence-missing             3     the graded run root (the cloud run's, else RUN_ROOT)
#                                           did not pass the offline review-evidence grade for
#                                           this verdict at the configured
#                                           prflow_review.verdict_severity_threshold (`critical`,
#                                           with a stderr `NOTE:`, when the read fails or the
#                                           value is outside the ladder; issues #193, #1656); no
#                                           marker composed and no review, comment, or
#                                           progress-stamp request issued
#
#   PROGRESS not-requested            —     no progress-comment marker was supplied (the local
#                                           / no-live-comment case); nothing was stamped
#   PROGRESS stamped <comment-id>     —     the run-keyed progress comment was rewritten with
#                                           the marker on the line immediately AFTER its
#                                           `<!-- prflow:review-progress run=… -->` line and
#                                           its first `- [ ] Run complete` line ticked (it has
#                                           none: a stderr `NOTE:` line)
#   PROGRESS not-found                —     no comment on this pull request starts with the
#                                           supplied run-keyed marker; BODY_FILE was the body sent
#   PROGRESS failed <one-line error>  —     the lookup or the rewrite failed: the API refused
#                                           it, jq could not read the comments page or build
#                                           the rewrite, or the comment id did not split from
#                                           its body (after a failed lookup BODY_FILE was the
#                                           body sent)
#   DISMISS <rc>                      —     dismiss-stale-rejections.sh's exit code (127: the
#                                           sibling is missing or not executable)
#
# The PROGRESS and DISMISS lines NEVER change the exit code: the review artifact is the
# authoritative surface (a progress comment is edited in place, so superseded rounds vanish),
# and failed secondary work must not turn a posted verdict into a failure. The caller routes
# on line 1.
#
# THE RECEIPT (issue #1156). Every line above is ALSO written to a run-scoped receipt file
# (lib/verdict-receipt.sh owns the path, and is the single source both this producer and
# scripts/check-verdict-post-reached.sh compose it from): the outcome line becomes the
# receipt's first line, and the PROGRESS and DISMISS lines follow it when emitted. The receipt
# is what makes this helper's ABSENCE observable after the run. Everything documented above
# begins at this helper's first line, so a review run that never invokes it produces none of
# it — no outcome line, no error text, no failure record — and presents afterwards as a
# successful review with a published-looking verdict and an untouched reviews API. With the
# receipt, "the post was refused" (a receipt naming a refusal outcome) and "the post was
# never reached" (no receipt at all) are two different durable states.
#
# The write is BEST-EFFORT and fully isolated: it happens after the stdout line is already
# printed, it cannot change stdout's bytes or their order, it cannot change the exit code,
# and a failed write emits exactly ONE stderr breadcrumb per run however many lines follow
# it. A receipt is a diagnostic; a helper that failed its verdict post because it could not
# write a diagnostic would be strictly worse than the state this issue set out to fix.
#
# WHAT SILENCE MEANS. Printing NOTHING is not one of the outcomes above: a helper that
# emits no line at all was refused by the harness/permission matcher before it ran. A
# caller reads that silence as "the verdict was not posted" — NEVER as authorization to treat
# the review as posted. Likewise the caller must never read a
# `FAILED`/`SKIP …` line as a posted review: only `POSTED review <event>` (exit 0) means the
# formal review exists, and only `POSTED comment <event>` (exit 0) means the verdict reached
# the comment channel instead.
#
# WHY the empty/absent event is refused rather than sent (issue #1059). GitHub's REST docs
# for "Create a review for a pull request" state that leaving `event` blank sets the review
# to PENDING — an unsubmitted draft nobody submits, i.e. a silent non-post. So a verdict token
# that maps to no event, the empty string included, takes SKIP unknown-event and issues no
# request; the helper never sends a request whose `event` field is empty.
#
# Exit codes here are this helper's OWN contract and align with neither sibling: 0 for the
# two success tokens, 1 for an issued-and-refused post with no durable channel left, 3 for
# every "declined to try" SKIP. Read it as a separate contract from seed-review-progress.sh /
# dismiss-stale-rejections.sh.
#
# Requires: gh (authenticated, resolved through lib/resolve-gh.sh) and jq (through
# lib/resolve-jq.sh). $DEVFLOW_GH / $DEVFLOW_JQ override the binaries for tests, the same
# seam the rest of devflow uses.
#
# Usage: post-review-verdict.sh PR_NUMBER VERDICT BODY_FILE HEAD_SHA [PROGRESS_MARKER] [RUN_ROOT]
set -uo pipefail
# gh + jq: resolved once via the single-source execution-verified resolvers; an explicit
# DEVFLOW_GH/DEVFLOW_JQ still wins, so test stubs are untouched. Both sources are guarded
# so a partially-copied deploy degrades to the bare binary with a breadcrumb rather than
# aborting under `set -u`. resolve-gh.sh exposes a function; resolve-jq.sh assigns
# DEVFLOW_JQ on source (no function to call).
_PRV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/resolve-gh.sh
. "$_PRV_DIR/../lib/resolve-gh.sh" \
  || { echo "devflow post-verdict: resolve-gh.sh could not be sourced — using bare 'gh' (set DEVFLOW_GH to override)" >&2; devflow_resolve_gh() { echo "${DEVFLOW_GH:-gh}"; }; }
# shellcheck source=../lib/resolve-jq.sh
. "$_PRV_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow post-verdict: resolve-jq.sh could not be sourced — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
: "${DEVFLOW_JQ:=jq}"

# The run-scoped receipt (issue #1156). Guarded exactly like the resolvers above: a
# partially copied deployment degrades to a helper that posts verdicts and records no
# receipt — the reader then reports NOT-REACHED, which is the pre-#1156 state, never a
# refused post.
# shellcheck source=../lib/verdict-receipt.sh
. "$_PRV_DIR/../lib/verdict-receipt.sh" \
  || { echo "devflow post-verdict: verdict-receipt.sh could not be sourced — this run records no verdict-post receipt (the verdict post itself is unaffected)" >&2; devflow_verdict_receipt_record() { return 1; }; }

_PRV_RECEIPT_STARTED=0
_PRV_RECEIPT_WARNED=0
# _prv_say LINE — print one contract line to stdout, then record it on the receipt.
#
# The stdout `echo` comes FIRST and unconditionally, so the receipt can neither change
# the bytes the caller routes on nor their order. The receipt write is best-effort: it
# returns 0 whatever happens, and only the FIRST failure earns a stderr breadcrumb, so
# a run whose receipt directory is unwritable emits one line rather than one per
# contract line.
#
# The first call of the process truncates the receipt and the rest append, which is
# what makes the outcome line the receipt's first line without any caller having to say
# so — and what makes a second invocation inside one job REPLACE the earlier round
# rather than accumulate behind it.
#
# KNOWN RESIDUAL, stated with its real blast radius rather than papered over: when the
# first post cannot create the receipt, the run leaves none, so scripts/check-verdict-post-reached.sh
# answers NOT-REACHED for a run that DID reach this helper — and the workflow step that
# consumes that answer POSTS A PUBLIC PULL-REQUEST COMMENT. The consequence is therefore
# not merely an indistinguishable internal state: on this residual with a `POSTED review`
# outcome, a comment about a missing verdict record appears on a pull request that has a
# formal review sitting in the reviews API for that head. That is why the comment names
# both causes and asserts neither, and why it points at the breadcrumb below — which is
# the ONLY signal separating them, and lives in the job log, not on the pull request.
# When a later post in the same job (the delivery retry) cannot open the receipt, the
# earlier post's outcome line stays first: a `FAILED no-durable-channel` first post
# followed by a retry that posts still fails the job and may let the stall backstop
# request the review again; the `could not write the verdict-post receipt` breadcrumb
# is the only trace.
# Anything that changes this breadcrumb's wording changes the instruction that comment
# gives a maintainer; the focused module asserts the two are the same literal.
_prv_say() {
  echo "$1"
  local _mode=add
  if [ "$_PRV_RECEIPT_STARTED" -eq 0 ]; then
    _mode=start
    _PRV_RECEIPT_STARTED=1
  fi
  devflow_verdict_receipt_record "$_mode" "$1" && return 0
  if [ "$_PRV_RECEIPT_WARNED" -eq 0 ]; then
    _PRV_RECEIPT_WARNED=1
    echo "devflow post-verdict: could not write the verdict-post receipt — this run's Phase 4.4 reach cannot be established from it (the verdict post itself is unaffected)" >&2
  fi
  return 0
}

# _prv_note TEXT — one stderr `NOTE:` line: something the caller reports that changes no outcome.
_prv_note() { printf 'NOTE: post-review-verdict.sh: %s\n' "$1" >&2; }

# Collapse a captured error, or a value a NOTE quotes, to a single line with pure parameter
# expansion — an EMITTED value must not be routed through a non-preflight PATH tool (tr/sed),
# which would come back empty on a host that lacks it. Newlines and carriage returns become
# spaces; an empty input reads `(no error output)`.
_prv_oneline() {
  local s="${1-}"
  s="${s//$'\n'/ }"
  s="${s//$'\r'/ }"
  [ -n "$s" ] || s="(no error output)"
  printf '%s' "$s"
}

PR_NUMBER="${1:-}"
VERDICT="${2:-}"
BODY_FILE="${3:-}"
HEAD_SHA="${4:-}"
PROGRESS_MARKER="${5:-}"
RUN_ROOT="${6:-}"

# (1) Refuse a non-numeric PR number before any request. The `case` glob is a bash
# builtin (no PATH tool), so the screen holds on a stripped-down host.
case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "devflow post-verdict: PR number '$PR_NUMBER' is not numeric — refusing the review post (no request issued)" >&2
    _prv_say "SKIP not-numeric"
    exit 3 ;;
esac

# (2) Map the verdict token to a review event AND the marker's normalized two-token verdict.
# The empty string and any unmapped value take the refusal arm, so no PENDING-draft request
# can ever be issued. `case` is a builtin — a SELECTION never routed through a PATH tool.
case "$VERDICT" in
  REJECT|'REJECT '*|REQUEST_CHANGES) EVENT=REQUEST_CHANGES; MARKER_VERDICT=REJECT ;;
  APPROVE)                           EVENT=APPROVE;         MARKER_VERDICT=APPROVE ;;
  'APPROVE '*|COMMENT)               EVENT=COMMENT;         MARKER_VERDICT=APPROVE ;;
  *)
    echo "devflow post-verdict: verdict token '$VERDICT' maps to no review event (accepted: REJECT / 'REJECT …' / APPROVE / 'APPROVE …' / REQUEST_CHANGES / COMMENT) — refusing the post (a blank/unknown event would create an unsubmitted PENDING review)" >&2
    _prv_say "SKIP unknown-event"
    exit 3 ;;
esac

# (3) The head must be a full 40-hex object name, because it is EMITTED verbatim into the
# marker as the record of the reviewed tree, which a consumer places the review by
# comparing against the head under consideration (issue #433 — NOT against the reviews-API
# `commit_id`, which GitHub re-points on a branch update). An abbreviated,
# empty, or non-hex value would publish a marker that can never compare equal to a real
# head — a marker asserting a head it does not name is worse than no marker, so this
# refuses rather than stamping a lie. `[[ =~ ]]` is a bash builtin (no PATH tool).
if [[ ! "$HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "devflow post-verdict: head '$HEAD_SHA' is not a 40-character hex object name — refusing the post (the verdict marker's head= field must be a full commit object name comparable to the head under consideration; no request issued)" >&2
  _prv_say "SKIP head-not-sha"
  exit 3
fi

# (4) The body file must be a readable file. An empty-but-readable body is allowed (it
# posts a body carrying the marker line alone); only absent/unreadable refuses.
if [ ! -r "$BODY_FILE" ] || [ ! -f "$BODY_FILE" ]; then
  echo "devflow post-verdict: body file '$BODY_FILE' is absent or unreadable — refusing the post (no request issued)" >&2
  _prv_say "SKIP body-file-unreadable"
  exit 3
fi

# (5) Grade execution evidence before any request (issues #193, #1656). A cloud run key derives
# the run root through compose-run-key.sh — never inline — so the scratch-key format cannot
# drift and mis-grade a different directory; a local or absent key grades the RUN_ROOT argument
# when given. review-evidence-gate.py's POSTED-VERDICT MODE says what each verdict owes. A
# non-pass grade refuses with SKIP evidence-missing.
_prv_run_key="$("$_PRV_DIR/compose-run-key.sh" 2>/dev/null)"
case "$_prv_run_key" in
  ''|local-*) _prv_run_root="$RUN_ROOT" ;;
  *) _prv_run_root=".prflow/tmp/review/pr-${PR_NUMBER}/${_prv_run_key}" ;;
esac
if [ -z "$_prv_run_root" ]; then
  _prv_note "no reproducible cloud run identity (compose-run-key.sh: '${_prv_run_key:-(none)}') and no run-root argument — run-root evidence grading unavailable; posting without an evidence-pass claim (issue #193 local arm)"
else
  # A failed read and a value outside the ladder each grade at `critical` under their own NOTE.
  # The `case` words are verdict_report.py's SEVERITIES: bash cannot import them, a test ties them.
  if ! _prv_threshold="$("$_PRV_DIR/config-get.sh" .prflow_review.verdict_severity_threshold critical)"; then
    _prv_note "could not read prflow_review.verdict_severity_threshold (config-get.sh failed) — grading at critical"
    _prv_threshold=critical
  fi
  case "$_prv_threshold" in
    critical|important|suggestion) : ;;
    *)
      _prv_note "prflow_review.verdict_severity_threshold is '$(_prv_oneline "$_prv_threshold")', not critical|important|suggestion — grading at critical"
      _prv_threshold=critical ;;
  esac
  # Take grade line 1 with parameter expansion, never `head`: this token DECIDES whether to
  # refuse, and a value deciding a selection must not route through a non-preflight PATH tool
  # (CLAUDE.md). The gate is an install-relative sibling and reads the run root alone.
  _prv_grade_full="$(python3 "$_PRV_DIR/review-evidence-gate.py" --grade-run-root "$_prv_run_root" --repo-root . \
                       --posted-verdict "$MARKER_VERDICT" --threshold "$_prv_threshold")"
  _prv_grade="${_prv_grade_full%%$'\n'*}"
  # The gate's later lines say why (a pass's notes, a refusal's cause): they go to stderr either way.
  case "$_prv_grade_full" in *$'\n'*) printf '%s\n' "${_prv_grade_full#*$'\n'}" >&2 ;; esac
  case "$_prv_grade" in
    pass\ *) : ;;  # evidence present — proceed to the marker and the post
    *)
      echo "devflow post-verdict: review-evidence grade for run root '$_prv_run_root' is '${_prv_grade:-(no grade)}' (not a pass) — refusing the verdict post; no marker, review, comment, or progress-stamp request issued (issue #193)" >&2
      _prv_say "SKIP evidence-missing"
      exit 3 ;;
  esac
fi

# The one authoritative marker literal. Composed HERE, at the producer boundary — the agent
# never composes it, which is the whole point of issue #1030.
MARKER="<!-- prflow:review-verdict head=$HEAD_SHA verdict=$MARKER_VERDICT -->"

# Look up the run-keyed progress comment, before the post because the result picks the posted
# body. Sets _PRV_PC_STATE to not-requested, found, not-found or failed; on found, _PRV_PC_ID and
# _PRV_PC_BODY (the body as a JSON string); on failed, _PRV_PC_ERR (one line).
_PRV_PC_STATE=not-requested
_PRV_PC_ID=""
_PRV_PC_BODY=""
_PRV_PC_ERR=""
_prv_find_progress() {
  [ -n "$PROGRESS_MARKER" ] || return 0
  local raw target
  _PRV_PC_STATE=failed
  # One paginated read of the pull request's issue comments, then a SEPARATE jq pass over the
  # captured payload — never one `gh … 2>&1 | jq` pipeline, whose merged stderr would reach jq
  # as unparseable input and misattribute an API failure to a parse failure. Select the LAST
  # comment whose body starts with the supplied run-keyed marker and emit "<id>\t<body-json>": the
  # id and the body travel together, and the stamp below rewrites this body without a second read.
  if ! raw="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/issues/$PR_NUMBER/comments?per_page=100" 2>&1)"; then
    _PRV_PC_ERR="$(_prv_oneline "$raw")"
    return 0
  fi
  if ! target="$(printf '%s' "$raw" | "$DEVFLOW_JQ" -rs --arg m "$PROGRESS_MARKER" \
                     'add | map(select(((.body // "") | type == "string") and ((.body // "") | startswith($m)))) | last
                      | if . == null then "" else ((.id | tostring) + "\t" + (.body | @json)) end' 2>&1)"; then
    _PRV_PC_ERR="$(_prv_oneline "$target")"
    return 0
  fi
  # A native-Windows jq ends the line with CR; an integer id and an @json body hold no raw CR.
  target="${target//$'\r'/}"
  if [ -z "$target" ]; then
    _PRV_PC_STATE=not-found
    return 0
  fi
  _PRV_PC_ID="${target%%$'\t'*}"
  _PRV_PC_BODY="${target#*$'\t'}"
  if [ -z "$_PRV_PC_ID" ] || [ "$_PRV_PC_ID" = "$target" ]; then
    _PRV_PC_ERR="could not split the comment id from its body"
    return 0
  fi
  _PRV_PC_STATE=found
}
_prv_find_progress

# A found progress comment holds the full report, so the posted body is a verdict-only stub built
# from VERDICT verbatim (scripts/build-experiment-records.py strips its
# ` — full report in PR comment` suffix); otherwise it is the body file.
if [ "$_PRV_PC_STATE" = found ]; then
  PRV_BODY_ARG=(--arg body "## Verdict: $VERDICT — full report in PR comment"$'\n\n'"> The complete review report (checklist results, findings, details) is in the"$'\n'"> PRFlow Review progress comment on this PR."$'\n')
else
  PRV_BODY_ARG=(--rawfile body "$BODY_FILE")
fi

# Compose the JSON request body inside jq so the body bytes (backticks, `$(`, literal
# quotes, newlines) reach the API unmangled and the marker prepend is byte-lossless:
# split("\n")/join("\n") round-trips any input exactly, including a missing final newline.
# Every line starting with a run-key marker, in either spelling, is dropped first (see BODY).
# A caller-authored verdict marker then on LINE 1 is dropped rather than double-stamped — only
# line 1, so a marker literal quoted deeper in the report (a finding citing this contract)
# is preserved as prose and the producer's own line stays line 1.
PRV_JQ_LINES='($body | split("\n")
  | map(select((startswith("<!-- prflow:review-progress ") or startswith("<!-- devflow:review-progress ")) | not))
  | (if ((.[0] // "") | startswith("<!-- prflow:review-verdict ")) then .[1:] else . end)
  | join("\n"))'
PRV_JQ_BODY='{event:$event, body: ($marker + "\n" + '"$PRV_JQ_LINES"')}'

# Issue exactly one review POST. Capture the WHOLE pipeline stderr (never /dev/null) so a
# failure carries its cause whichever stage produced it — the group's `2>&1 1>/dev/null`
# captures both jq's stderr (a broken/missing DEVFLOW_JQ, an unreadable rawfile) and gh's;
# discard the group's stdout (gh's response). Under `set -o pipefail` a jq OR a gh failure
# surfaces as a non-zero pipeline status.
REVIEW_ERR="$( { "$DEVFLOW_JQ" -n --arg event "$EVENT" --arg marker "$MARKER" "${PRV_BODY_ARG[@]}" "$PRV_JQ_BODY" \
                 | "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/pulls/$PR_NUMBER/reviews" --input - ; } 2>&1 1>/dev/null)"
REVIEW_RC=$?

# Report the lookup above and, for a found comment, stamp it with the SAME marker on the line
# immediately after its `<!-- prflow:review-progress run=… -->` line, so the run key stays line 1
# and seed-review-progress.sh's reported literal is byte-unchanged, and tick the first
# `- [ ] Run complete` line (a stderr `NOTE:` says so when there is none). Called only after a
# POSTED outcome: a marker on the progress comment means the verdict reached a durable channel.
# Best-effort by design: it prints a PROGRESS line and never touches the exit code (see the
# CONTRACT block).
_prv_stamp_progress() {
  local out err
  case "$_PRV_PC_STATE" in
    not-requested)
      _prv_say "PROGRESS not-requested"
      return 0 ;;
    not-found)
      _prv_say "PROGRESS not-found"
      return 0 ;;
    failed)
      _prv_say "PROGRESS failed $_PRV_PC_ERR"
      return 0 ;;
  esac
  local cid="$_PRV_PC_ID" bjson="$_PRV_PC_BODY"
  # Rewrite: keep line 1 (the run key), put the marker on line 2, drop a marker line already
  # sitting at line 2 so a re-post does not accumulate two of them, and preserve every other
  # line verbatim.
  # Related: `scripts/workpad.py`'s `_merge_leading_markers` re-inserts these same two leading
  # marker lines after a full-body rewrite. It agrees with this stamp only on the POSITIONS —
  # run key line 1, verdict line 2; its matching and precedence rules differ, so a change to
  # either position must be made in both.
  # One jq pass prints whether it ticked a row (output line 1), then the request body (line 2):
  # the NOTE below is printed unless that answer is `true`.
  if ! out="$("$DEVFLOW_JQ" -nc --arg marker "$MARKER" --argjson b "$bjson" \
                '$b | split("\n")
                 | (if (length == 0) then [$marker]
                    else (.[0:1] + [$marker] + (.[1:] | if ((.[0] // "") | startswith("<!-- prflow:review-verdict ")) then .[1:] else . end))
                    end)
                 | (first(range(length) as $j | select(.[$j] | startswith("- [ ] Run complete")) | $j) // null) as $i
                 | ($i != null), {body: ((if $i == null then . else .[$i] |= ("- [x]" + .[5:]) end) | join("\n"))}' 2>&1)"; then
    _prv_say "PROGRESS failed $(_prv_oneline "$out")"
    return 0
  fi
  # A native-Windows jq ends each line with CR; the answer and the compact JSON hold no raw CR.
  out="${out//$'\r'/}"
  if ! err="$(printf '%s\n' "${out#*$'\n'}" \
                | "$DEVFLOW_GH" api -X PATCH "repos/{owner}/{repo}/issues/comments/$cid" --input - 2>&1 1>/dev/null)"; then
    _prv_say "PROGRESS failed $(_prv_oneline "$err")"
    return 0
  fi
  [ "${out%%$'\n'*}" = true ] \
    || _prv_note "progress comment $cid has no line starting '- [ ] Run complete', so none was ticked"
  _prv_say "PROGRESS stamped $cid"
}

# After a POSTED outcome, an APPROVE-family verdict runs the sibling dismiss-stale-rejections.sh
# (all its output to stderr, so stdout keeps the closed vocabulary) and reports its exit code as
# `DISMISS <rc>` — never as this helper's own. A REJECT and a FAILED post run no dismissal.
_prv_dismiss() {
  [ "$MARKER_VERDICT" = APPROVE ] || return 0
  local rc=127
  if [ -x "$_PRV_DIR/dismiss-stale-rejections.sh" ]; then
    "$_PRV_DIR/dismiss-stale-rejections.sh" "$PR_NUMBER" </dev/null >&2
    rc=$?
  fi
  _prv_say "DISMISS $rc"
}

if [ "$REVIEW_RC" -eq 0 ]; then
  _prv_say "POSTED review $EVENT"
  _prv_stamp_progress
  _prv_dismiss
  exit 0
fi

# The review channel refused. Post the SAME marker-stamped body as a pull-request comment so
# the verdict still reaches a durable, machine-readable artifact — the agent composes no
# fallback body of its own (issue #1030). This is the `gh pr comment` channel expressed as
# REST, per CLAUDE.md's rule that GitHub writes go through `gh api` and never through
# GraphQL-resolving porcelain. `gh pr comment` targets the pull request's issue-comment
# thread, which is exactly this endpoint.
COMMENT_ERR="$( { "$DEVFLOW_JQ" -n --arg marker "$MARKER" "${PRV_BODY_ARG[@]}" \
                  '{body: ($marker + "\n" + '"$PRV_JQ_LINES"')}' \
                  | "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/issues/$PR_NUMBER/comments" --input - ; } 2>&1 1>/dev/null)"
COMMENT_RC=$?

if [ "$COMMENT_RC" -eq 0 ]; then
  echo "devflow post-verdict: the formal review POST was refused ($(_prv_oneline "$REVIEW_ERR")) — the marker-stamped verdict was posted as a pull-request comment instead" >&2
  _prv_say "POSTED comment $EVENT"
  _prv_stamp_progress
  _prv_dismiss
  exit 0
fi

# Never stamp here: an undelivered verdict must leave the progress comment unmarked, or
# derive-review-verdict.sh reads it as posted.
_prv_say "FAILED no-durable-channel review: $(_prv_oneline "$REVIEW_ERR") | comment: $(_prv_oneline "$COMMENT_ERR")"
exit 1

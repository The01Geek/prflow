#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-review-verdict.sh PR_NUMBER VERDICT BODY_FILE HEAD_SHA [PROGRESS_MARKER] — post a
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
# the reviewed head as `commit_id`, but it does NOT carry WHOSE review it is. Every consumer
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
# hazard for a report containing backticks, `$(`, and literal double quotes: the file's
# bytes are read verbatim by jq --rawfile, the marker line is prepended inside jq, and the
# result is sent as the body unmodified.
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
# CONTRACT — exactly one OUTCOME line per reachable path, and (on the paths that reach the
# progress-comment stamp) one PROGRESS line after it. The outcome vocabulary is closed and
# complete by construction, names the DURABLE CHANNEL that received the verdict, and has NO
# silent path:
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
#   FAILED no-durable-channel <err>   1     BOTH channels were issued and refused, so NO
#                                           durable artifact carries this verdict; <err> is
#                                           the captured cause of each, collapsed to one line
#   SKIP not-numeric                  3     the PR number is empty or non-numeric; no request
#   SKIP unknown-event                3     the verdict token is outside the accepted set
#                                           (INCLUDING the empty string); no request issued
#   SKIP head-not-sha                 3     the head argument is not exactly 40 hex characters,
#                                           so no honest marker can be composed; no request
#   SKIP body-file-unreadable         3     the body-file argument is absent or unreadable; no
#                                           request issued
#   SKIP evidence-missing             3     with reproducible cloud run identity, the run root
#                                           did not pass the offline review-evidence grade
#                                           (issue #193); no marker composed and no review,
#                                           comment, or progress-stamp request issued
#
#   PROGRESS not-requested            —     no progress-comment marker was supplied (the local
#                                           / no-live-comment case); nothing was stamped
#   PROGRESS stamped <comment-id>     —     the run-keyed progress comment was rewritten with
#                                           the marker on the line immediately AFTER its
#                                           `<!-- prflow:review-progress run=… -->` line
#   PROGRESS not-found                —     no comment on this pull request carried the
#                                           supplied run-keyed marker
#   PROGRESS failed <one-line error>  —     the lookup or the rewrite was issued and refused
#
# The PROGRESS line NEVER changes the exit code: the review artifact is the authoritative
# surface (a progress comment is edited in place, so superseded rounds vanish), and a failed
# secondary stamp must not turn a posted verdict into a failure. It is a second line, not a
# second outcome — the caller routes on line 1.
#
# THE RECEIPT (issue #1156). Every line above is ALSO written to a run-scoped receipt file
# (lib/verdict-receipt.sh owns the path, and is the single source both this producer and
# scripts/check-verdict-post-reached.sh compose it from): the outcome line becomes the
# receipt's first line, and the PROGRESS line, when one is emitted, its second. The receipt
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
# caller reads that silence as "route to the fallback arm" (post the full report as a
# plain comment and record that the formal review could not be posted) — NEVER as
# authorization to treat the review as posted. Likewise the caller must never read a
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
# Usage: post-review-verdict.sh PR_NUMBER VERDICT BODY_FILE HEAD_SHA [PROGRESS_MARKER]
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
# write itself fails, the run leaves no receipt, so scripts/check-verdict-post-reached.sh
# answers NOT-REACHED for a run that DID reach this helper — and the workflow step that
# consumes that answer POSTS A PUBLIC PULL-REQUEST COMMENT. The consequence is therefore
# not merely an indistinguishable internal state: on this residual with a `POSTED review`
# outcome, a comment about a missing verdict record appears on a pull request that has a
# formal review sitting in the reviews API for that head. That is why the comment names
# both causes and asserts neither, and why it points at the breadcrumb below — which is
# the ONLY signal separating them, and lives in the job log, not on the pull request.
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

PR_NUMBER="${1:-}"
VERDICT="${2:-}"
BODY_FILE="${3:-}"
HEAD_SHA="${4:-}"
PROGRESS_MARKER="${5:-}"

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
# marker every consumer cross-checks against the reviews-API `commit_id`. An abbreviated,
# empty, or non-hex value would publish a marker that can never compare equal to a real
# commit_id — a marker asserting a head it does not name is worse than no marker, so this
# refuses rather than stamping a lie. `[[ =~ ]]` is a bash builtin (no PATH tool).
if [[ ! "$HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "devflow post-verdict: head '$HEAD_SHA' is not a 40-character hex object name — refusing the post (the verdict marker's head= field must be comparable to the reviews-API commit_id; no request issued)" >&2
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

# (5) Grade execution evidence before any request (issue #193). Derive the run key through
# compose-run-key.sh — never inline — so the scratch-key format cannot drift and mis-grade a
# different directory; a cloud non-pass grade refuses with SKIP evidence-missing before posting.
_prv_run_key="$("$_PRV_DIR/compose-run-key.sh" 2>/dev/null)"
case "$_prv_run_key" in
  ''|local-*)
    echo "devflow post-verdict: no reproducible cloud run identity (compose-run-key.sh: '${_prv_run_key:-(none)}') — run-root evidence grading unavailable; posting without an evidence-pass claim (issue #193 local arm)" >&2 ;;
  *)
    _prv_run_root=".prflow/tmp/review/pr-${PR_NUMBER}/${_prv_run_key}"
    # Take grade line 1 with parameter expansion, never `head`: this token DECIDES whether to
    # refuse, and a value deciding a selection must not route through a non-preflight PATH tool
    # (CLAUDE.md). The gate is an install-relative sibling and reads <run-root>/diff.patch alone.
    _prv_grade_full="$(python3 "$_PRV_DIR/review-evidence-gate.py" --grade-run-root "$_prv_run_root" --repo-root . 2>/dev/null)"
    _prv_grade="${_prv_grade_full%%$'\n'*}"
    case "$_prv_grade" in
      pass\ *) : ;;  # evidence present — proceed to the marker and the post
      *)
        echo "devflow post-verdict: review-evidence grade for run root '$_prv_run_root' is '${_prv_grade:-(no grade)}' (not a pass) — refusing the verdict post; no marker, review, comment, or progress-stamp request issued (issue #193)" >&2
        _prv_say "SKIP evidence-missing"
        exit 3 ;;
    esac ;;
esac

# The one authoritative marker literal. Composed HERE, at the producer boundary — the agent
# never composes it, which is the whole point of issue #1030.
MARKER="<!-- prflow:review-verdict head=$HEAD_SHA verdict=$MARKER_VERDICT -->"

# Compose the JSON request body inside jq so the body-file bytes (backticks, `$(`, literal
# quotes, newlines) reach the API unmangled and the marker prepend is byte-lossless:
# split("\n")/join("\n") round-trips any input exactly, including a missing final newline.
# A caller-authored marker already on LINE 1 is dropped rather than double-stamped — only
# line 1, so a marker literal quoted deeper in the report (a finding citing this contract)
# is preserved as prose and the producer's own line stays line 1.
PRV_JQ_BODY='{event:$event, body: ($marker + "\n" + ($body | split("\n")
  | (if ((.[0] // "") | startswith("<!-- prflow:review-verdict ")) then .[1:] else . end)
  | join("\n")))}'

# Issue exactly one review POST. Capture the WHOLE pipeline stderr (never /dev/null) so a
# failure carries its cause whichever stage produced it — the group's `2>&1 1>/dev/null`
# captures both jq's stderr (a broken/missing DEVFLOW_JQ, an unreadable rawfile) and gh's;
# discard the group's stdout (gh's response). Under `set -o pipefail` a jq OR a gh failure
# surfaces as a non-zero pipeline status.
REVIEW_ERR="$( { "$DEVFLOW_JQ" -n --arg event "$EVENT" --arg marker "$MARKER" --rawfile body "$BODY_FILE" "$PRV_JQ_BODY" \
                 | "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/pulls/$PR_NUMBER/reviews" --input - ; } 2>&1 1>/dev/null)"
REVIEW_RC=$?

# Collapse a captured error to a single line with pure parameter expansion — an EMITTED
# value must not be routed through a non-preflight PATH tool (tr/sed), which would come
# back empty on a host that lacks it. Newlines and carriage returns become spaces.
_prv_oneline() {
  local s="${1-}"
  s="${s//$'\n'/ }"
  s="${s//$'\r'/ }"
  [ -n "$s" ] || s="(no error output)"
  printf '%s' "$s"
}

# Stamp the run-keyed progress comment with the SAME marker, on the line immediately after
# its `<!-- prflow:review-progress run=… -->` line, so the run key stays line 1 and
# seed-review-progress.sh's reported literal is byte-unchanged. Best-effort by design: it
# prints a PROGRESS line and never touches the exit code (see the CONTRACT block).
_prv_stamp_progress() {
  if [ -z "$PROGRESS_MARKER" ]; then
    _prv_say "PROGRESS not-requested"
    return 0
  fi
  local err raw target
  # One paginated read of the pull request's issue comments, then a SEPARATE jq pass over the
  # captured payload — never one `gh … 2>&1 | jq` pipeline, whose merged stderr would reach jq
  # as unparseable input and misattribute an API failure to a parse failure. Select the LAST
  # comment whose body carries the supplied run-keyed marker and emit "<id>\t<body-json>": the
  # id and the body travel together so no second read can race a different comment.
  if ! raw="$("$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/issues/$PR_NUMBER/comments?per_page=100" 2>&1)"; then
    _prv_say "PROGRESS failed $(_prv_oneline "$raw")"
    return 0
  fi
  if ! target="$(printf '%s' "$raw" | "$DEVFLOW_JQ" -rs --arg m "$PROGRESS_MARKER" \
                     'add | map(select(((.body // "") | type == "string") and ((.body // "") | contains($m)))) | last
                      | if . == null then "" else ((.id | tostring) + "\t" + (.body | @json)) end' 2>&1)"; then
    _prv_say "PROGRESS failed $(_prv_oneline "$target")"
    return 0
  fi
  if [ -z "$target" ]; then
    _prv_say "PROGRESS not-found"
    return 0
  fi
  local cid="${target%%$'\t'*}"
  local bjson="${target#*$'\t'}"
  if [ -z "$cid" ] || [ "$cid" = "$target" ]; then
    _prv_say "PROGRESS failed could not split the comment id from its body"
    return 0
  fi
  # Rewrite: keep line 1 (the run key), put the marker on line 2, drop a marker line already
  # sitting at line 2 so a re-post does not accumulate two of them, and preserve every other
  # line verbatim.
  # Related: `scripts/workpad.py`'s `_merge_leading_markers` re-inserts these same two leading
  # marker lines after a full-body rewrite. It agrees with this stamp only on the POSITIONS —
  # run key line 1, verdict line 2; its matching and precedence rules differ, so a change to
  # either position must be made in both.
  if ! err="$( { "$DEVFLOW_JQ" -n --arg marker "$MARKER" --argjson b "$bjson" \
                   '{body: ($b | split("\n")
                     | (if (length == 0) then [$marker]
                        else (.[0:1] + [$marker] + (.[1:] | if ((.[0] // "") | startswith("<!-- prflow:review-verdict ")) then .[1:] else . end))
                        end)
                     | join("\n"))}' \
                 | "$DEVFLOW_GH" api -X PATCH "repos/{owner}/{repo}/issues/comments/$cid" --input - ; } 2>&1 1>/dev/null)"; then
    _prv_say "PROGRESS failed $(_prv_oneline "$err")"
    return 0
  fi
  _prv_say "PROGRESS stamped $cid"
}

if [ "$REVIEW_RC" -eq 0 ]; then
  _prv_say "POSTED review $EVENT"
  _prv_stamp_progress
  exit 0
fi

# The review channel refused. Post the SAME marker-stamped body as a pull-request comment so
# the verdict still reaches a durable, machine-readable artifact — the agent composes no
# fallback body of its own (issue #1030). This is the `gh pr comment` channel expressed as
# REST, per CLAUDE.md's rule that GitHub writes go through `gh api` and never through
# GraphQL-resolving porcelain. `gh pr comment` targets the pull request's issue-comment
# thread, which is exactly this endpoint.
COMMENT_ERR="$( { "$DEVFLOW_JQ" -n --arg marker "$MARKER" --rawfile body "$BODY_FILE" \
                  '{body: ($marker + "\n" + ($body | split("\n")
                    | (if ((.[0] // "") | startswith("<!-- prflow:review-verdict ")) then .[1:] else . end)
                    | join("\n")))}' \
                  | "$DEVFLOW_GH" api -X POST "repos/{owner}/{repo}/issues/$PR_NUMBER/comments" --input - ; } 2>&1 1>/dev/null)"
COMMENT_RC=$?

if [ "$COMMENT_RC" -eq 0 ]; then
  echo "devflow post-verdict: the formal review POST was refused ($(_prv_oneline "$REVIEW_ERR")) — the marker-stamped verdict was posted as a pull-request comment instead" >&2
  _prv_say "POSTED comment $EVENT"
  _prv_stamp_progress
  exit 0
fi

_prv_say "FAILED no-durable-channel review: $(_prv_oneline "$REVIEW_ERR") | comment: $(_prv_oneline "$COMMENT_ERR")"
_prv_stamp_progress
exit 1

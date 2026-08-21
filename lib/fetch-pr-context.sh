#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# fetch-pr-context.sh <pr-number>
# Fetches all primary GitHub sources for one PR and writes a context bundle.
# Output path is echoed to stdout; everything else goes to stderr.
# Exit 2 if the PR branch is not a retrospected branch (kind == "skip").
set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

PR="${1:?Usage: fetch-pr-context.sh <pr-number>}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=resolve-gh.sh
. "$HERE/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# shellcheck source=./config-source.sh
. "$HERE/config-source.sh"

REPO="$("$DEVFLOW_GH" repo view --json nameWithOwner -q .nameWithOwner)" \
  || { echo "::error::fetch-pr-context: failed to resolve repo name" >&2; exit 1; }

# ── 1. PR metadata ──────────────────────────────────────────────────────────
PR_JSON="$("$DEVFLOW_GH" pr view "$PR" --json number,headRefName,baseRefName,headRefOid,mergeCommit,mergedAt,createdAt,author,title,body,additions,deletions,files,labels,closingIssuesReferences)" \
  || { echo "::error::fetch-pr-context: failed to fetch PR metadata for PR ${PR}" >&2; exit 1; }

BRANCH="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .headRefName)"
BASE_REF="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .baseRefName)"
HEAD_SHA="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .headRefOid)"
MERGE_COMMIT_SHA="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r '.mergeCommit.oid // ""')"
MERGED_AT="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .mergedAt)"
CREATED_AT="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .createdAt)"
AUTHOR_RAW="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r '.author.login')"
AUTHOR="${AUTHOR_RAW%\[bot\]}"
TITLE="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .title)"
BODY="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .body)"
ADDITIONS="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .additions)"
DELETIONS="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -r .deletions)"
CHANGED_FILES="$(echo "$PR_JSON" | "$DEVFLOW_JQ" '[.files[].path]')"

# ── 2. Classify retrospection kind ───────────────────────────────────────────
# Mirror lib/scan.sh's union predicate (label / closes-issue / prefix) so
# a PR scan selected on the label or closes-issue path — e.g. DevFlow's own
# issue-<N>-<slug> branches that match no prefix — is not then dropped here.
IMPL_PREFIX="$(devflow_conf '.prflow_retrospective.implementation_branch_prefix' 'claude/')"
LABELS_JSON="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -c '.labels // []')"
CLOSING_JSON="$(echo "$PR_JSON" | "$DEVFLOW_JQ" -c '.closingIssuesReferences // []')"
# argjson-ok: watched labels closing -- per-PR bounded operands (one PR's label list and closing-issue refs, plus a constant boolean), never corpus-sized (issue #895)
KIND="$("$DEVFLOW_JQ" -rn --arg branch "$BRANCH" --argjson watched true --arg impl_prefix "$IMPL_PREFIX" \
    --argjson labels "$LABELS_JSON" --argjson closing "$CLOSING_JSON" -f "$HERE/classify-pr-kind.jq")"
if [ "$KIND" = "skip" ]; then
    echo "fetch-pr-context: branch $BRANCH is not a retrospected branch" >&2
    exit 2
fi

# ── 3. Issue number ──────────────────────────────────────────────────────────
ISSUE_NUMBER="null"
# Try branch name first: claude/issue-<N>-...
ISSUE_FROM_BRANCH="$(sed -nE 's|^claude/issue-([0-9]+)-.*$|\1|p' <<<"$BRANCH" || true)"
if [ -n "$ISSUE_FROM_BRANCH" ]; then
    ISSUE_NUMBER="$ISSUE_FROM_BRANCH"
else
    # Fallback: grep body for Closes/Fixes/Resolves #<N>
    ISSUE_FROM_BODY="$(echo "$BODY" | grep -oiE '(Closes|Fixes|Resolves)[[:space:]]+#[0-9]+' | grep -oE '[0-9]+' | head -1 || true)"
    if [ -n "$ISSUE_FROM_BODY" ]; then
        ISSUE_NUMBER="$ISSUE_FROM_BODY"
    else
        # Final fallback: GitHub's own issue linkage (closingIssuesReferences).
        # DevFlow's own `issue-<N>-<slug>` branches never match the `claude/issue-`
        # pattern above, and a PR linked only via the UI carries no Closes/Fixes
        # keyword in its body — yet such PRs are selected by the union predicate.
        # Without this they source an EMPTY workpad (a milder form of the bug this
        # change fixes). Use the first linked issue's number.
        ISSUE_FROM_CLOSING="$(echo "$CLOSING_JSON" | "$DEVFLOW_JQ" -r '.[0].number // empty' 2>/dev/null || true)"
        if [ -n "$ISSUE_FROM_CLOSING" ]; then
            ISSUE_NUMBER="$ISSUE_FROM_CLOSING"
        fi
    fi
fi

# The five list-endpoint slurps below (issue comments, review comments, PR comments, PR
# reviews, commits) normalize through this one filter: `add` on a single-object page
# yields that object, and a later `.[] | .user`/`.body` read then aborts the whole run.
_JQ_PAGES_TO_OBJECTS='(add // []) | if type == "array" then map(select(type == "object")) else [] end'

# ── 5. Issue details ─────────────────────────────────────────────────────────
ISSUE_JSON="null"
# The workpad lives on the ISSUE (header `# PRFlow Workpad — Issue #<N>`,
# marker `<!-- prflow:workpad -->`), authored by github-actions — NOT on the PR
# conversation thread. Default to an empty array so the workpad/reflection parse
# below is safe even when no linked issue was found.
ISSUE_COMMENTS_RAW='[]'
if [ "$ISSUE_NUMBER" != "null" ]; then
    ISSUE_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/issues/${ISSUE_NUMBER}" --paginate)" \
      || { echo "::error::fetch-pr-context: failed to fetch issue ${ISSUE_NUMBER} for PR ${PR}" >&2; exit 1; }
    _ISSUE_COMMENTS_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/issues/${ISSUE_NUMBER}/comments" --paginate)" \
      || { echo "::error::fetch-pr-context: failed to fetch issue comments for issue ${ISSUE_NUMBER}" >&2; exit 1; }
    ISSUE_COMMENTS_RAW="$(printf '%s' "$_ISSUE_COMMENTS_RAW" | "$DEVFLOW_JQ" -s "$_JQ_PAGES_TO_OBJECTS")"
    # Normalize issue comments to {author, body, createdAt}
    ISSUE_COMMENTS_NORM="$(echo "$ISSUE_COMMENTS_RAW" | "$DEVFLOW_JQ" '[.[] | {author: ((.user | if type == "object" then .login else null end) // ""), body: (.body // ""), createdAt: (.created_at // "")}]')"
    # `labels` normalization is TOTAL over every JSON shape (mirrors the §5b `norm`
    # def below): an array of label objects → their names, an array of strings →
    # themselves, and a wrong-type/missing `labels` → []. A non-total extraction
    # (e.g. `[.labels[]?.name]`) aborts under `set -e` on a wrong-type `labels`,
    # taking down the WHOLE context fetch — not just provenance — so the issue leg
    # must fail closed to [] exactly as the PR leg does.
    ISSUE_JSON="$(echo "$ISSUE_RAW" | "$DEVFLOW_JQ" \
        --slurpfile comments <(printf '%s' "$ISSUE_COMMENTS_NORM") \
        '{title: (.title // ""), body: (.body // ""), labels: ((.labels // []) | if type == "array" then map(if type == "object" then (.name // "") else . end) else [] end), comments: $comments[0]}')"
fi

# ── 5b. Provenance label ──────────────────────────────────────────────────────
# pr_devflow_provenance (the bundle field name is frozen; the label it reads is
# not): true iff the `PRFlow` provenance label — or its superseded `DevFlow`
# spelling, which stays accepted so no pre-rename history is dropped (issue
# #1003) — is among the PR's labels OR, when an issue resolved, among the linked
# issue's labels. Both lists are already fetched (the PR's in LABELS_JSON, the
# issue's in ISSUE_JSON.labels, already normalized to name strings), so no new
# API call. The PR leg uses the same object-or-string normalization
# classify-pr-kind.jq uses (COUPLED INVARIANT: the provenance-label match —
# object/string normalization + `any(. == "PRFlow" or . == "DevFlow")` — is
# mirrored in lib/scan.sh and lib/classify-pr-kind.jq; both spellings are
# hardcoded provenance constants, never a config key). A wrong-type or absent
# label list yields false (fail-closed). The issue-label leg keeps provenance
# alive in a deployment whose PR-label applies fail (scripts/apply-labels.sh is
# best-effort). Any jq error → false.
# argjson-ok: pr_labels issue -- per-PR bounded operands (one PR's label list and one linked issue's JSON), never corpus-sized (issue #895)
PR_DEVFLOW_PROVENANCE="$("$DEVFLOW_JQ" -n --argjson pr_labels "$LABELS_JSON" --argjson issue "$ISSUE_JSON" '
    def norm: (if type == "array" then map(if type == "object" then (.name // "") else . end) else [] end);
    (($pr_labels | norm) + (($issue.labels // []) | norm)) | any(. == "PRFlow" or . == "DevFlow")
' 2>/dev/null)" || PR_DEVFLOW_PROVENANCE=""
# Fail closed to `false` on anything that is not a bare boolean — a jq abort (the
# `||` above leaves ""), a wrong-type/garbage emission, or an unresolvable label
# list. `false` is the SKIP-ENABLING value for dispatch-disposition.jq, so this
# coercion is never silent: it emits a ::warning:: breadcrumb like every sibling
# absent path in this producer (the NoIssue/Absent/Unparsed arms below), so an
# operator can tell "no provenance label" apart from "provenance could not be read".
case "$PR_DEVFLOW_PROVENANCE" in
    true|false) ;;
    *) echo "::warning::fetch-pr-context: DevFlow provenance for PR ${PR} could not be established (jq emitted '${PR_DEVFLOW_PROVENANCE}'); failing closed to false" >&2
       PR_DEVFLOW_PROVENANCE=false ;;
esac

# ── 6. Review comments (inline diff comments) ────────────────────────────────
_REVIEW_COMMENTS_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/pulls/${PR}/comments" --paginate)" \
  || { echo "::error::fetch-pr-context: failed to fetch review comments for PR ${PR}" >&2; exit 1; }
REVIEW_COMMENTS_RAW="$(printf '%s' "$_REVIEW_COMMENTS_RAW" | "$DEVFLOW_JQ" -s "$_JQ_PAGES_TO_OBJECTS")"
REVIEW_COMMENTS="$(echo "$REVIEW_COMMENTS_RAW" | "$DEVFLOW_JQ" '[.[] | {author: ((.user | if type == "object" then .login else null end) // ""), body: (.body // ""), path: (.path // ""), line: (.line // null), createdAt: (.created_at // "")}]')"

# ── 7. PR conversation comments ───────────────────────────────────────────────
_PR_COMMENTS_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/issues/${PR}/comments" --paginate)" \
  || { echo "::error::fetch-pr-context: failed to fetch PR conversation comments for PR ${PR}" >&2; exit 1; }
PR_COMMENTS_RAW="$(printf '%s' "$_PR_COMMENTS_RAW" | "$DEVFLOW_JQ" -s "$_JQ_PAGES_TO_OBJECTS")"
PR_COMMENTS="$(echo "$PR_COMMENTS_RAW" | "$DEVFLOW_JQ" '[.[] | {author: ((.user | if type == "object" then .login else null end) // ""), body: (.body // ""), createdAt: (.created_at // "")}]')"

# ── 8. PR reviews ─────────────────────────────────────────────────────────────
_PR_REVIEWS_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/pulls/${PR}/reviews" --paginate)" \
  || { echo "::error::fetch-pr-context: failed to fetch PR reviews for PR ${PR}" >&2; exit 1; }
PR_REVIEWS_RAW="$(printf '%s' "$_PR_REVIEWS_RAW" | "$DEVFLOW_JQ" -s "$_JQ_PAGES_TO_OBJECTS")"
PR_REVIEWS="$(echo "$PR_REVIEWS_RAW" | "$DEVFLOW_JQ" '[.[] | {author: ((.user | if type == "object" then .login else null end) // ""), state: (.state // ""), body: (.body // ""), submittedAt: (.submitted_at // "")}]')"

# ── 9. Commits ────────────────────────────────────────────────────────────────
_COMMITS_RAW="$("$DEVFLOW_GH" api "repos/${REPO}/pulls/${PR}/commits" --paginate)" \
  || { echo "::error::fetch-pr-context: failed to fetch commits for PR ${PR}" >&2; exit 1; }
COMMITS_RAW="$(printf '%s' "$_COMMITS_RAW" | "$DEVFLOW_JQ" -s "$_JQ_PAGES_TO_OBJECTS")"
COMMITS="$(echo "$COMMITS_RAW" | "$DEVFLOW_JQ" '[.[] | {sha: .sha, author_login: (.author.login // ""), committer_login: (.committer.login // ""), committed_at: (.commit.committer.date // ""), message: (.commit.message // ""), parents_count: ((.parents // []) | length)}]')"

# ── 10. Diff ──────────────────────────────────────────────────────────────────
DIFF_BYTE_CAP="$(devflow_conf '.prflow_retrospective.diff_byte_cap' 204800)"
# `gh pr diff` fails outright on very large PRs (HTTP 406 — "diff exceeded the
# maximum number of files (300)") and on transient API errors. That must NOT
# abort the whole context fetch: a PR whose diff we cannot retrieve is the same
# situation as one whose diff is over diff_byte_cap — emit `diff: null`,
# `diff_truncated: true`, and let the analyst work from changed_files,
# human_postbot_diff, the reviews, and the issue. Only a *missing* PR (handled
# earlier) is fatal.
set +e
DIFF_RAW="$("$DEVFLOW_GH" pr diff "$PR" 2>/dev/null)"
DIFF_FETCH_OK=$?
set -e
if [ "$DIFF_FETCH_OK" -ne 0 ]; then
    echo "::warning::fetch-pr-context: could not fetch diff for PR ${PR} (too large or API error); emitting diff: null" >&2
    DIFF_RAW=""
fi

# Elide the *bodies* of generated / vendored files from the embedded diff:
# lockfiles, minified bundles, source maps, and anything under
# node_modules/ vendor/ dist/ build/. These are never the story and routinely
# dominate the byte count, which pushes the whole diff over diff_byte_cap and
# nulls it out — losing the parts that DO matter. The file *list*
# (changed_files) keeps every path; only the hunk text is replaced with a
# one-line marker so the analyst still knows the file changed.
DIFF_RAW="$(printf '%s' "$DIFF_RAW" | python3 -c '
import sys, re
diff = sys.stdin.read()
noise = re.compile(
    r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml"
    r"|composer\.lock|Gemfile\.lock|poetry\.lock|Cargo\.lock|go\.sum)$"
    r"|\.min\.(js|css|mjs)$|\.map$|(^|/)(node_modules|vendor|dist|build)/"
)
out, elide = [], False
for line in diff.split("\n"):
    if line.startswith("diff --git "):
        parts = line.split(" ", 3)
        path = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else ""
        elide = bool(path and noise.search(path))
        if elide:
            out.append(line)
            out.append("[devflow: diff body elided — generated/vendored file: %s]" % path)
            continue
    if not elide:
        out.append(line)
sys.stdout.write("\n".join(out))
' 2>/dev/null || printf '%s' "$DIFF_RAW")"
DIFF_LEN="${#DIFF_RAW}"
if [ "$DIFF_FETCH_OK" -ne 0 ] || [ "$DIFF_LEN" -gt "$DIFF_BYTE_CAP" ]; then
    DIFF_JSON="null"
    DIFF_TRUNCATED="true"
else
    DIFF_JSON="$(printf '%s' "$DIFF_RAW" | "$DEVFLOW_JQ" -Rs '.')"
    DIFF_TRUNCATED="false"
fi

# diffstat: simple "<n> files changed, +A -D" summary
NUM_FILES="$(echo "$CHANGED_FILES" | "$DEVFLOW_JQ" 'length')"
DIFFSTAT="${NUM_FILES} files changed, +${ADDITIONS} -${DELETIONS}"

# ── 11. Signals ───────────────────────────────────────────────────────────────

# Scratch dir for large --slurpfile / --rawfile transports, hoisted here from the
# section-13 bundle-emission site so the review_verdicts union below can route a
# full paginated reviews payload through a file rather than an --argjson argv
# string (the E2BIG shape lib/test/lint-argjson-transport.py forbids). One trap
# covers both the derivation's scratch file and section 13's bundle inputs.
_JQ_TMP="$(mktemp -d)"
trap 'rm -rf "$_JQ_TMP"' EXIT

# review_comments_count
REVIEW_COMMENTS_COUNT="$(echo "$REVIEW_COMMENTS" | "$DEVFLOW_JQ" 'length')"

# post_bot_commits: count *substantive* commits AFTER the last bot/PR-author
# commit. A commit is "bot-authored" if author_login or committer_login ends
# with [bot] OR equals the AUTHOR (the [bot]-stripped PR author). Pure merge
# commits (parents_count > 1 — `git merge main` into the PR branch) are NOT
# counted: a human merging in main is branch hygiene, not a fixup of the bot's
# work, and counting it created a flood of false "imperfect" verdicts that
# nothing actionable came out of. (Trivial *non-merge* fixups — a one-line
# typo/lint commit — ARE still counted: a small human correction is a real,
# if minor, "the bot shipped something slightly off" signal.)
POST_BOT_COMMITS="$(echo "$COMMITS" | "$DEVFLOW_JQ" --arg author "$AUTHOR" '
    to_entries
    | [.[] | select(
        (.value.author_login | endswith("[bot]"))
        or (.value.committer_login | endswith("[bot]"))
        or (.value.author_login == $author)
        or (.value.committer_login == $author)
      ) | .key
    ] as $bot_indices
    | if ($bot_indices | length) == 0 then 0
      else ([.[($bot_indices | last) + 1:][] | select((.value.parents_count // 1) <= 1)] | length)
      end
')"

# ci_failures_during_pr + ci_status_unknown
# The CI check-runs call is intentionally fail-safe: a PR whose CI status
# could not be read must NOT be considered clean.  ci_status_unknown=true
# propagates into cheap-gate.jq and blocks the clean path explicitly.
CI_STATUS_UNKNOWN="false"
CI_FAILURES="1"
set +e
# Never fold gh's stderr into this capture: --paginate multiplies the requests
# that can emit a non-fatal notice, and any such line makes the filter below
# error, reporting a healthy head as unreadable. Route it to a file so the
# re-emit below can hold it to the same one-line-per-record contract our own
# breadcrumbs keep; letting it reach our stderr raw fragments a caller's record.
_CI_GH_ERR_FILE="$_JQ_TMP/gh-checkruns.err"
_CI_RUNS_JSON="$("$DEVFLOW_GH" api "repos/${REPO}/commits/${HEAD_SHA}/check-runs?per_page=100" --paginate 2>"$_CI_GH_ERR_FILE")"
_CI_EXIT=$?
set -e
# Collapse with a bash builtin, never `tr`: lib/preflight.sh does not guarantee
# it, and a missing tr would silently empty the diagnostic it is emitting.
_CI_GH_ERR=""
IFS= read -r -d '' _CI_GH_ERR < "$_CI_GH_ERR_FILE" || true
_CI_GH_ERR="${_CI_GH_ERR%$'\n'}"
if [ -n "$_CI_GH_ERR" ]; then
    printf 'fetch-pr-context: gh check-runs stderr: %s\n' "${_CI_GH_ERR//$'\n'/ }" >&2
fi
if [ $_CI_EXIT -ne 0 ] || [ -z "$_CI_RUNS_JSON" ]; then
    CI_STATUS_UNKNOWN="true"
    CI_FAILURES="1"
    # Name which limb fired: an rc-0 empty body is not a failed call, and one
    # shared message makes a transport error and an empty response identical.
    if [ $_CI_EXIT -ne 0 ]; then
        printf 'fetch-pr-context: check-runs read failed (rc=%s); ci_status_unknown=true\n' "$_CI_EXIT" >&2
    else
        printf 'fetch-pr-context: check-runs returned an empty body (rc=0); ci_status_unknown=true\n' >&2
    fi
else
    # Never filter `.` instead of `-n`/`inputs`, never default `.check_runs`,
    # and never drop an error arm: each turns an unreadable body into a count.
    # Hold it in one variable so the diagnostic re-run below cannot drift.
    _CI_JQ_PROG='[inputs] as $pages | if ($pages | length) == 0 then error("no check-run pages") else [$pages[] | (.check_runs | if type == "array" then . else error("check_runs not an array") end)[] | if type == "object" then . else error("non-object check-run") end | select(.conclusion != null and .conclusion != "success" and .conclusion != "neutral" and .conclusion != "skipped" and .conclusion != "cancelled" and .conclusion != "stale")] | length end'
    _CI_COUNT="$(echo "$_CI_RUNS_JSON" | "$DEVFLOW_JQ" -n "$_CI_JQ_PROG" 2>/dev/null || true)"
    if [ -z "$_CI_COUNT" ] || ! [[ "$_CI_COUNT" =~ ^[0-9]+$ ]]; then
        CI_STATUS_UNKNOWN="true"
        CI_FAILURES="1"
        # Re-run for the diagnostic alone: without it the filter's distinct
        # error() messages, and a broken jq, all read as one unusable body.
        _CI_JQ_ERR="$(echo "$_CI_RUNS_JSON" | "$DEVFLOW_JQ" -n "$_CI_JQ_PROG" 2>&1 >/dev/null || true)"
        # Keep this one line: a caller splits our stderr on newlines into
        # separate records, so an unstripped body fragments into phantom rows.
        printf 'fetch-pr-context: check-runs body yielded no usable count; ci_status_unknown=true; %.120s; body began: %.200s\n' \
            "${_CI_JQ_ERR//$'\n'/ }" "${_CI_RUNS_JSON//$'\n'/ }" >&2
    else
        CI_FAILURES="$_CI_COUNT"
    fi
fi

# workpad_body, workpad_final_status, reflections
# The workpad lives on the ISSUE thread (ISSUE_COMMENTS_RAW), not the PR
# conversation thread — reading it from the PR thread (the old bug) left it
# ~always empty, so the workpad signal in cheap-gate.jq was inert.
WORKPAD_BODY="$(echo "$ISSUE_COMMENTS_RAW" | "$DEVFLOW_JQ" -r '[.[] | select(((.body | strings) // "") | test("<!-- (pr|dev)flow:workpad -->"; "i"))] | first | .body // ""')"
WORKPAD_FINAL_STATUS=""
REFLECTIONS="[]"
# reflections_friction_count: the number of reflection bullets that force LLM
# analysis (every kind EXCEPT the informational `note`). Defaulted to 0 for a
# workpad-less bundle; recomputed by the parser below when a workpad is present.
REFLECTION_FRICTION_COUNT=0
# Three-arm chain (issue #626): an ABSENT workpad now emits a non-empty sentinel
# so cheap-gate.jq fails closed rather than laundering it past analysis, mirroring
# the present-but-corrupt `Unparsed` arm inside the parse block below. All 4
# producer paths therefore emit a non-empty value: (1) no linked issue → NoIssue;
# (2) issue resolved but no marker comment → Absent; (3) marker present, Status
# unparseable → Unparsed; (4) parsed → the glyph-stripped word. The sentinels carry
# triage granularity — provenance (pr_devflow_provenance below), not the sentinel,
# decides the retrospective disposition.
if [ "$ISSUE_NUMBER" = "null" ]; then
    echo "::warning::fetch-pr-context: no linked issue resolved for PR ${PR}; no workpad audit trail (NoIssue)" >&2
    WORKPAD_FINAL_STATUS="NoIssue"
elif [ -z "$WORKPAD_BODY" ]; then
    echo "::warning::fetch-pr-context: issue ${ISSUE_NUMBER} resolved for PR ${PR} but no <!-- prflow:workpad --> comment exists (Absent)" >&2
    WORKPAD_FINAL_STATUS="Absent"
else
    # Extract the value after "**Status:** <glyph> <word>" / "Status: <word>".
    # workpad.py prepends a canonical glyph (🚀/🎉/👎/💥/🛑) to the status word, so the
    # captured value is e.g. "🎉 Complete". Strip that glyph by the known glyph SET
    # the workpad owns (a leading 🚀/🎉/👎/💥/🛑 plus surrounding whitespace), NOT by
    # taking the last whitespace token: the old `awk '{print $NF}'` silently
    # coupled the strip to a single-word status vocabulary and would mis-gate a
    # future multi-word status (e.g. "In Progress" → "Progress"). The glyphs are
    # matched as literal byte sequences, so the strip is locale-independent.
    # The glyph SET below must stay in sync with workpad.py's `_STATUS_GLYPHS`
    # (the single source of truth that *writes* the glyph); enumerating the exact
    # set — rather than a broad "strip any leading symbol" — is deliberate, so a
    # corrupt/hand-edited status with an UNKNOWN leading symbol is preserved (not
    # silently normalised to a clean-looking word) and gates not-clean below.
    # `tr -d '\r'` first guards against CRLF bodies leaving a trailing carriage
    # return on the value. Trailing `|| true`: under `set -euo pipefail`, `head -1`
    # closing the pipe early can hand an upstream stage a SIGPIPE (141) and abort
    # the script; guard it.
    WORKPAD_FINAL_STATUS="$(printf '%s' "$WORKPAD_BODY" | tr -d '\r' | sed -nE 's/^\*{0,2}[[:space:]]*[Ss]tatus[[:space:]]*:?\*{0,2}[[:space:]]*(.+)/\1/p' | head -1 | sed -E 's/^[[:space:]]*(🚀|🎉|👎|💥|🛑)?[[:space:]]*//; s/[[:space:]]+$//' || true)"
    # Fail toward analysis, not toward "clean": a workpad is present but its
    # Status line did not parse (corrupt/hand-edited — workpad.py always writes
    # `**Status:** <glyph> <word>`). Substitute a non-empty sentinel — any
    # non-Complete value gates not-clean (issue #626 shrank the gate's clean set
    # to "Complete" only, so an empty "" now fails closed too; the sentinel still
    # keeps this present-but-corrupt case distinguishable from the absent arms).
    if [ -z "$WORKPAD_FINAL_STATUS" ]; then
        echo "::warning::fetch-pr-context: workpad present for PR ${PR} but Status line did not parse; not treating as Complete" >&2
        WORKPAD_FINAL_STATUS="Unparsed"
    fi
    # reflections[]: the bullet lines inside the workpad's `## Devflow Reflection`
    # <details> block (excluding the <summary> scaffold). Parsed in python3 (a
    # hard dependency) over the env-passed body — no shell quoting traverses the
    # markdown, and metacharacters (backticks, $) in a bullet survive intact.
    #
    # The parser also derives `friction_count`: the number of bullets that force
    # LLM analysis. Exempt-list semantics — a bullet is exempt ONLY when it is a
    # `note`-kind bullet (leading glyph `ℹ️`) rendered under the `### ℹ️ Notes`
    # sub-section; EVERY other bullet is friction (an `issue-accuracy` `📝` bullet
    # sharing that section, an `### ⚠️ Action required` / `### 💡 Improvements`
    # bullet, a bullet under an unrecognized `### ` heading, and any bullet before
    # a `### ` heading — all fail closed to friction so a future taxonomy section
    # cannot silently become non-friction). The `### ℹ️ Notes` heading literal and
    # the `ℹ️`/`📝` glyphs are a COUPLED INVARIANT hard-copied from
    # scripts/workpad.py's `_REFLECTION_SUBSECTIONS` / `_REFLECTION_KINDS` (this
    # inline heredoc cannot `import` workpad.py); lib/test/run.sh pins the couple.
    # The output is a JSON object {reflections, friction_count}; `reflections` keeps
    # its existing flat-string-array shape and contents byte-for-byte.
    REFLECTION_PARSE="$(DEVFLOW_WORKPAD_BODY="$WORKPAD_BODY" python3 - <<'PYEOF'
import os, re, json
body = os.environ.get('DEVFLOW_WORKPAD_BODY', '')
# Coupled with scripts/workpad.py _REFLECTION_SUBSECTIONS / _REFLECTION_KINDS.
NOTES_HEADING = '### ℹ️ Notes'
NOTE_GLYPH = 'ℹ️'
out, friction, in_section, cur_heading = [], 0, False, None
for raw in body.split('\n'):
    line = raw.rstrip('\r')
    if re.match(r'^##\s+Devflow Reflection\s*$', line):
        in_section = True
        continue
    if not in_section:
        continue
    # End of the reflection region: the closing </details>, or the next
    # `## ` heading (degrade gracefully when </details> is missing — malformed
    # block must not detonate the parse or swallow the rest of the comment).
    # NOTE: a `### ` sub-heading is `##`+`#`, so it never matches `^##\s+\S` and
    # is not a region terminator — it is captured as the current sub-section below.
    if '</details>' in line:
        break
    if re.match(r'^##\s+\S', line):
        break
    # Skip the <details>/<summary> scaffold lines.
    if '<details' in line or '<summary' in line or '</summary>' in line:
        continue
    # Track the current `### ` sub-section heading (drives the friction split).
    h = re.match(r'^\s*(###\s+.*\S)\s*$', line)
    if h:
        cur_heading = h.group(1)
        continue
    m = re.match(r'^\s*[-*]\s+(.*\S)\s*$', line)
    if m:
        text = m.group(1)
        out.append(text)
        # Exempt ONLY a note-kind bullet (ℹ️) under the `### ℹ️ Notes` heading;
        # everything else — including an issue-accuracy 📝 bullet in that same
        # section — is friction.
        exempt = (cur_heading == NOTES_HEADING and text.lstrip().startswith(NOTE_GLYPH))
        if not exempt:
            friction += 1
print(json.dumps({"reflections": out, "friction_count": friction}))
PYEOF
)"
    # Guard against a python hiccup leaving an empty/invalid value that would
    # break the later `--slurpfile reflections` / `--argjson`. The guard requires
    # BOTH keys, and — crucially — it FAILS TOWARD ANALYSIS, matching the sibling
    # WORKPAD_FINAL_STATUS="Unparsed" guard above: a workpad IS present (we are
    # in the `else` arm of the issue#626 chain — issue resolved AND WORKPAD_BODY
    # non-empty), so a parse failure means "a reflection
    # block existed but could not be read", NOT "there were no reflections". The
    # fallback therefore substitutes a FRICTION sentinel (one non-note bullet,
    # friction_count 1) so cheap-gate gates the PR non-clean and it is analyzed,
    # rather than defaulting to friction_count 0 and silently routing a possibly
    # friction-bearing run to the clean path (fail-open). The `::warning::`
    # names the shape so the substitution is not silent.
    if ! printf '%s' "$REFLECTION_PARSE" | "$DEVFLOW_JQ" -e 'has("reflections") and has("friction_count")' >/dev/null 2>&1; then
        echo "::warning::fetch-pr-context: reflection parse produced no valid JSON for PR ${PR}; a present-but-unparseable reflection block is treated as friction (fail toward analysis)" >&2
        REFLECTION_PARSE='{"reflections":["<unparsed reflection block>"],"friction_count":1}'
    fi
    REFLECTIONS="$(printf '%s' "$REFLECTION_PARSE" | "$DEVFLOW_JQ" -c '.reflections')"
    REFLECTION_FRICTION_COUNT="$(printf '%s' "$REFLECTION_PARSE" | "$DEVFLOW_JQ" -r '.friction_count')"
    # Defensive: an empty/non-digit derivation (e.g. jq itself vanished) also fails
    # toward analysis — substitute 1, not 0, so a broken derivation over-analyzes
    # rather than reading as zero friction (same fail-direction as the guard above).
    case "$REFLECTION_FRICTION_COUNT" in ''|*[!0-9]*) REFLECTION_FRICTION_COUNT=1 ;; esac
fi

# ttm_hours: (merged_at - created_at) in decimal hours
# The inner except already handles parse failures gracefully; the shell-level
# fallback is redundant and dropped to avoid masking a missing python3 binary.
# Timestamps are passed via the environment, not interpolated into the source,
# so a stray quote in the value can't break out of the Python string literal.
TTM_HOURS="$(DEVFLOW_MERGED_AT="$MERGED_AT" DEVFLOW_CREATED_AT="$CREATED_AT" python3 - <<'PYEOF'
import os
from datetime import datetime, timezone
fmt = '%Y-%m-%dT%H:%M:%SZ'
try:
    merged = datetime.strptime(os.environ['DEVFLOW_MERGED_AT'], fmt).replace(tzinfo=timezone.utc)
    created = datetime.strptime(os.environ['DEVFLOW_CREATED_AT'], fmt).replace(tzinfo=timezone.utc)
    diff = (merged - created).total_seconds() / 3600.0
    print(round(diff, 4))
except Exception:
    print(0.0)
PYEOF
)"
# Guard against an empty result poisoning the later `jq --argjson ttm_hours`.
[ -n "$TTM_HOURS" ] || TTM_HOURS=0.0

# review_verdicts: the UNION of two verdict sources —
#   1. the PR conversation comments (PR_COMMENTS_RAW, on stdin), and
#   2. the durable bot PR reviews (PR_REVIEWS_RAW, via --slurpfile).
# The conversation-comment scrape alone fails open: when a /review run leaves no
# progress comment its whole verdict lives only in the `gh pr review` body, the
# comment scrape returns [], and review_reject_outstanding is vacuously false —
# so a PR merged over an un-cleared REJECT reads clean (issue #895). Reading the
# reviews leg too closes that hole.
#
# BOTH legs read the PRODUCER MARKER first (issue #1030) and fall back to the
# heading grammar. scripts/post-review-verdict.sh — never the reviewing agent —
# stamps
#     <!-- prflow:review-verdict head=<40-hex> verdict=<APPROVE|REJECT> -->
# as line 1 of a review body and as the line after the run key in the run-keyed
# progress comment, so ONLY the first two lines are scanned for it: that is where
# the producer writes it and nowhere a fenced quote lands, so a review body that
# QUOTES this contract in a finding (routine on a pull request touching the review
# engine itself) is not read as carrying a verdict. Exactly one marker in that
# window contributes exactly ONE entry and the heading grammar is not consulted for
# that artifact; zero markers, or an ambiguous two, fall back to the grammar
# unchanged. The marker exists because a census over 60 pull requests measured 6 of
# 9 real bot REJECT bodies matching NO heading shape, so this signal — the
# retrospective loop's "merged over an un-cleared REJECT" detector — was blind to
# them.
#
# The heading grammar (the TRANSITIONAL shape, retained for artifacts posted before
# the marker existed): a heading line
# (1-6 `#`), an optional `/review —`/`/review –`/`/review -` wrapper prefix, the
# literal `Verdict:`, an optional `**` bold marker, then the first APPROVE|REJECT
# token. Two formats occur in the wild — the standalone `## Verdict: APPROVE (…)`
# and the CI wrapper `### /review — Verdict: **REJECT**` — and both are matched.
# `APPROVE WITH CAVEAT` / `APPROVE with notes` collapse to APPROVE (they are not a
# REJECT, which is all review_reject_outstanding cares about). Case-insensitive;
# a trailing `\r` from CRLF bodies is stripped first. `body` is guarded with
# `strings` before any string op so a non-string body skips that entry rather than
# aborting the whole filter (CLAUDE.md's non-string-field guard). The verdict token
# always comes from the BODY, never from a review's state.
#
# The reviews leg contributes an entry per verdict heading when the review's state
# is anything other than "PENDING" (a plain equality test, so an absent/null/
# non-string state does NOT exclude the review) and its body carries a heading. A
# DISMISSED review still contributes — the retrospective deliberately inverts the
# merge gate's dismissal rule (scripts/derive-review-verdict.sh), because a merge
# over an overridden REJECT is exactly what the loop exists to study; a REJECT that
# a later APPROVE cleared is handled by that later APPROVE ordering after it.
#
# Ordering: entries carrying a real producer timestamp (`created_at` for a comment,
# `submitted_at` for a review) are sorted among themselves; an explicit whole-union
# positional ordinal (`.index`) is the deterministic tie-break (jq's sort_by
# stability is unspecified), and a review orders after a comment sharing a
# timestamp. An entry whose own timestamp is absent/null/empty is excluded from
# that "last" computation and appended after the timestamped partition — it is
# present in review_verdicts but never becomes the chronologically-last entry (so
# an untimestamped APPROVE can never clear a timestamped REJECT). `.index` is
# stripped before emission — review_verdicts is read verbatim by the Stage A agent.
#
# Rung 3 (issue #1443) — the BOT-ONLY fallback, consulted only when rungs 1 and 2 both
# yield nothing. Widen none of its four constraints without re-reading them together:
# the `[bot]` login gate, the 30-line window, `rung3_mask`'s comment/fence/quote
# stripping, and the per-sub-rung line anchors are jointly what stops ordinary bot prose
# — every PRFlow-authored comment is bot-authored — from minting a verdict that feeds
# review_reject_outstanding. `review_verdict_unparsed_count` counts the scanned artifacts
# that survive all three rungs with no verdict yet carry a token in that same window; it
# feeds nothing, and review_reject_outstanding is derived from review_verdicts alone.
printf '%s' "$PR_REVIEWS_RAW" > "$_JQ_TMP/pr_reviews_raw.json"
REVIEW_VERDICTS_BUNDLE="$(echo "$PR_COMMENTS_RAW" | "$DEVFLOW_JQ" --slurpfile reviews "$_JQ_TMP/pr_reviews_raw.json" '
    # Deliberately wider than rung 3 on the axes that matter — unmasked, a bare
    # substring, case-insensitive. Narrowing any axis onto rung 3 makes an artifact
    # rung 3 declined vanish from the count as well as the union, recreating the
    # two-meanings collapse the count exists to end.
    def token_in_window($lines):
        any($lines[0:30][]; test("APPROVE|REJECT"; "i"));
    # Drop every line rung 3 must not read a verdict from: an HTML-comment region (opening
    # line, continuations and close alike), a fenced block, a blockquote, and an indented
    # code block. A fence closes only on its own marker, so a tilde line cannot close a
    # backtick block and leave the rest of the window readable.
    # Returns a POSITIONAL mask — one entry per window line, the line itself or null —
    # never a compacted list. Compacting closes the gap between a heading and a later
    # token, so a stripped block would make a distant token read as the adjacent one.
    # Every branch below appends exactly one entry, or the mask stops lining up with the
    # lines it masks and a verdict is read from the wrong one; rung3 checks that length.
    # Dropped: HTML-comment regions, fenced blocks, blockquotes, indented code, list items,
    # table rows and strikethrough — every construct that marks a line as quoting.
    def rung3_mask($lines):
        (reduce ($lines[0:30][]) as $l ({comment: false, fence: null, out: []};
            if .comment then
                ((if ($l | test("-->")) then .comment = false else . end) | .out += [null])
            elif .fence != null then
                (.fence as $f
                 | (if ($l | test("^[ \t]*" + $f)) then .fence = null else . end)
                 | .out += [null])
            elif ($l | test("^[ \t]*```")) then (.fence = "```" | .out += [null])
            elif ($l | test("^[ \t]*~~~")) then (.fence = "~~~" | .out += [null])
            elif ($l | test("<!--")) then
                ((if ($l | test("-->")) then . else .comment = true end) | .out += [null])
            elif ($l | test("^[ \t]*>")) then .out += [null]
            elif ($l | test("^(\t| {4,})")) then .out += [null]
            elif ($l | test("^ {0,3}([-*+]|[0-9]+[.)])[ \t]")) then .out += [null]
            elif ($l | test("\\|")) then .out += [null]
            elif ($l | test("~~")) then .out += [null]
            else .out += [$l] end))
        | .out;
    # An allow-list of decoration glyphs, never a block range and never all of non-ASCII:
    # the dingbat and emoji planes also hold the bullet, ballot-box, heavy-quotation,
    # speech-bubble and pointer glyphs that mark a line as a recap QUOTING a verdict.
    def emoji: "[\\x{2705}\\x{274C}\\x{26A0}\\x{1F534}\\x{1F7E0}-\\x{1F7E2}\\x{FE0F}\\x{200D}]";
    def headline_prefix: "^(?:[ \t#*_]|" + emoji + ")*";
    # Letters in ANY script, so trailing prose in a non-Latin script is prose here too.
    def not_letters: "[^\\p{L}]";
    def rung3($lines; $login):
        if ((($login | strings) // "") | endswith("[bot]")) then
          rung3_mask($lines) as $m
          | if ($m | length) != ($lines[0:30] | length) then [] else
          ([ $m[] | select(. != null) ]) as $w
          # Every sub-rung reads its token from its OWN whole-line capture, anchored at both
          # ends. A guard that only anchors the prefix, or that re-derives the token with a
          # second pattern, admits the trailing prose an artifact quotes a prior verdict in.
          | ([ $w[]
               | capture(headline_prefix + "(?i:Verdict):" + not_letters + "*(?<v>APPROVE|REJECT)" + not_letters + "*$")
               | .v ]) as $r1
          | if ($r1 | length) > 0 then $r1[0:1]
            elif any($w[]; test(headline_prefix + "(?i:Verdict):")) then []
            else
              # Letters may appear only in one optional leading word, the anchor word, and
              # the token — collapsing punctuation away instead lets an ordinary sentence
              # ("Do not review. REJECT.") wear the headline shape. The token stays
              # case-SENSITIVE so lowercase prose cannot satisfy it.
              # The window is the first three non-blank lines BY POSITION, each kept only if
              # it survived stripping: a stripped line is skipped, never backfilled from
              # later in the body.
              ([ range(0; $m | length) | select($lines[.] | test("[^ \t]")) ][0:3]
               | map(select($m[.] != null))
               | map($m[.])
               | map(capture(headline_prefix + "(\\p{L}+" + not_letters + "+)?(?i:Review|Verdict)" + not_letters + "+(?<v>APPROVE|REJECT)" + not_letters + "*$"))
               | map(.v)) as $r2
              | if ($r2 | length) == 1 then $r2
                else
                  # The next non-blank line is found in the RAW body, and a stripped one is
                  # a hard stop: the line adjacent to the heading is what decides.
                  ([ range(0; $m | length) as $i
                     | select($m[$i] != null)
                     | select(($m[$i] | test("^#{1,6}[ \t]"))
                              and (($m[$i] | gsub("[^A-Za-z]"; "") | ascii_downcase) == "verdict"))
                     | ([ range($i + 1; $m | length) | select($lines[.] | test("[^ \t]")) ][0]) as $j
                     | select($j != null)
                     | select($m[$j] != null)
                     | ($m[$j] | capture(headline_prefix + "(?<v>APPROVE|REJECT)" + not_letters + "*$"))
                     | .v ]) as $r3
                  | $r3[0:1]
                end
            end
          end
        else [] end;
    def verdicts_in($body; $login):
        (($body | strings) | split("\n") | map(rtrimstr("\r"))) as $lines
        | ([ $lines[0:2][]
             | select(test("^<!-- prflow:review-verdict head=[0-9a-fA-F]{40} verdict=(APPROVE|REJECT) -->$"))
             | capture("verdict=(?<verdict>APPROVE|REJECT)")
             | .verdict ]) as $marked
        | (if ($marked | length) == 1 then $marked
           else ([ $lines[]
                   | select(test("^#{1,6}[ \t]*(/review[ \t]*[—–-]+[ \t]*)?Verdict:[ \t]*\\**[ \t]*(APPROVE|REJECT)"; "i"))
                   | capture("Verdict:[ \t]*\\**[ \t]*(?<verdict>APPROVE|REJECT)"; "i")
                   | (.verdict | ascii_upcase) ]) as $grammar
                | (if ($grammar | length) > 0 then $grammar else rung3($lines; $login) end)
           end)
        | .[];
    # Per-artifact scan record: the verdicts it yielded, and whether it is an
    # artifact that yielded none yet visibly carries a token (the residual count).
    def scanned($arts; $tskey; $src):
        [ $arts[]
          | select(type == "object")
          | . as $a
          | ($a.user | if type == "object" then .login else null end) as $login
          | ((($a.body | strings) // "") | split("\n") | map(rtrimstr("\r"))) as $lines
          | ([ verdicts_in($a.body; $login) ]) as $vs
          | { vs: $vs,
              unparsed: ((($vs | length) == 0) and token_in_window($lines)),
              createdAt: (($a[$tskey]) // ""),
              source: $src } ];
    # Guard both payloads to arrays before iterating: a non-array comments payload
    # (stdin `.`) or a non-array reviews payload ($reviews[0]) would otherwise abort
    # the whole filter on `.[]` (external structured format — fail closed to empty).
    # Defense-in-depth: both payloads are already normalized to arrays upstream by
    # the sections-7/8 jq add-or-empty slurp, so this guard is not reachable via the
    # producer path (no producer-driven test can drive it); it is kept as a
    # fail-closed floor in case that normalization ever changes or the filter is
    # reused directly.
    (if type == "array" then . else [] end) as $comments
    | (if ($reviews[0] | type) == "array" then $reviews[0] else [] end) as $reviews_arr
    | (
        scanned($comments; "created_at"; "pr_comment")
        +
        scanned([ $reviews_arr[] | objects | select(.state != "PENDING") ]; "submitted_at"; "pr_review")
      ) as $records
    | { verdicts:
          ( [ $records[] | . as $rec | $rec.vs[] | {verdict: ., createdAt: $rec.createdAt, source: $rec.source} ]
            | to_entries | map(.value + {index: .key})
            | ( map(select(.createdAt != "")) | sort_by(.createdAt, (.source == "pr_review"), .index) ) as $ts
            | ( map(select(.createdAt == "")) ) as $nots
            | ($ts + $nots)
            | map({verdict, createdAt, source}) ),
        unparsed: ([ $records[] | select(.unparsed) ] | length) }
')"
REVIEW_VERDICTS="$(echo "$REVIEW_VERDICTS_BUNDLE" | "$DEVFLOW_JQ" -c '.verdicts // []')"
REVIEW_VERDICT_UNPARSED_COUNT="$(echo "$REVIEW_VERDICTS_BUNDLE" | "$DEVFLOW_JQ" -r '.unparsed // 0')"
# Never leave either empty: REVIEW_REJECT_OUTSTANDING is derived from the array below and
# the count is passed with --argjson, so an empty split aborts the whole bundle assembly.
if [ -z "$REVIEW_VERDICTS" ]; then
    # Empty here means the union filter produced no document at all, which is NOT the
    # same fact as "no verdicts" — say so, or an unusable bundle reads as a clean PR and
    # manufactures review_reject_outstanding=false. Not reachable via the producer path
    # (the section-7 slurp always hands the filter an array, so it always emits an
    # object, and a filter error aborts under set -e before this runs) — a fail-closed
    # floor no producer-driven test can drive, like the array guards inside the filter.
    echo "fetch-pr-context.sh: the union filter produced no review_verdicts document; emitting [] (verdicts could not be established for this PR)" >&2
    REVIEW_VERDICTS='[]'
fi
case "$REVIEW_VERDICT_UNPARSED_COUNT" in
    ''|*[!0-9]*)
        echo "fetch-pr-context.sh: the union filter yielded a non-numeric review_verdict_unparsed_count (${REVIEW_VERDICT_UNPARSED_COUNT:-<empty>}); emitting 0" >&2
        REVIEW_VERDICT_UNPARSED_COUNT=0 ;;
esac

# review_reject_outstanding: true when the chronologically-last TIMESTAMPED entry
# is a REJECT, OR when any TIMESTAMP-LESS entry is a REJECT (the one-directional
# rule). review_verdicts already places the sorted timestamped partition first, so
# its last timestamped element is the chronologically-last verdict.
REVIEW_REJECT_OUTSTANDING="$(echo "$REVIEW_VERDICTS" | "$DEVFLOW_JQ" '
    ( map(select(.createdAt != "")) ) as $ts
    | ( map(select(.createdAt == "")) ) as $nots
    | ((($ts | length) > 0) and ($ts[-1].verdict == "REJECT")) or ($nots | any(.verdict == "REJECT"))
')"

# workpad_body as JSON string (null if empty)
if [ -n "$WORKPAD_BODY" ]; then
    WORKPAD_BODY_JSON="$("$DEVFLOW_JQ" -Rs '.' <<<"$WORKPAD_BODY")"
else
    WORKPAD_BODY_JSON="null"
fi

# base_update_checkpoint4_present (issue #1050): whether the Phase 4.3 pre-ready
# base-update checkpoint recorded its evidence row. That row carries the hidden
# keyed-checkpoint marker `<!-- prflow:checkpoint base-update-checkpoint-4 -->`
# (or its superseded `devflow:` spelling on a pre-rename workpad). Deriving it here
# turns the checkpoint-4 evidence obligation from prose-only into a machine-consumed
# downstream field a consumer reads — never a substring search over the free-text
# note. The key is deliberately OUTSIDE the `gha:` prefix the review/review-and-fix
# tier discriminator matches, so surfacing it never reclassifies a run's tier.
# Matched with a bash `case` builtin — NOT grep/sed — because this value is EMITTED
# in the bundle, and CLAUDE.md bars deriving an emitted value through a non-preflight
# PATH tool (a missing tool would silently yield the wrong answer). Fails closed to
# false: an absent/empty workpad body has no marker.
BASE_UPDATE_CHECKPOINT4_PRESENT=false
case "$WORKPAD_BODY" in
    *'<!-- prflow:checkpoint base-update-checkpoint-4 -->'*|*'<!-- devflow:checkpoint base-update-checkpoint-4 -->'*)
        BASE_UPDATE_CHECKPOINT4_PRESENT=true ;;
esac

# implement_summary_comment: best-effort
IMPLEMENT_SUMMARY="$(echo "$PR_COMMENTS_RAW" | "$DEVFLOW_JQ" -r '[.[] | select((.body | strings) // "" | test("Claude finished|/implement #"; "i"))] | first | .body // ""')"
if [ -n "$IMPLEMENT_SUMMARY" ]; then
    IMPLEMENT_SUMMARY_JSON="$("$DEVFLOW_JQ" -Rs '.' <<<"$IMPLEMENT_SUMMARY")"
else
    IMPLEMENT_SUMMARY_JSON="null"
fi

# ── 12. human_postbot_diff ────────────────────────────────────────────────────
# Get SHA list of post-bot commits (excluding pure merge commits — same rule as
# post_bot_commits above; a merge commit's API patch is the messy combined diff,
# which is noise, not the human's actual fixup) and fetch their patches.
HUMAN_POSTBOT_DIFF="null"
if [ "$POST_BOT_COMMITS" -gt 0 ]; then
    POSTBOT_SHAS="$(echo "$COMMITS" | "$DEVFLOW_JQ" --arg author "$AUTHOR" '
        to_entries
        | [.[] | select(
            (.value.author_login | endswith("[bot]"))
            or (.value.committer_login | endswith("[bot]"))
            or (.value.author_login == $author)
            or (.value.committer_login == $author)
          ) | .key
        ] as $bot_indices
        | if ($bot_indices | length) == 0 then []
          else [.[($bot_indices | last)+1:][] | select((.value.parents_count // 1) <= 1) | .value.sha]
          end
    ')"
    PATCHES=""
    while IFS= read -r SHA; do
        set +e
        _PATCH_JSON="$("$DEVFLOW_GH" api "repos/${REPO}/commits/${SHA}")"
        _PATCH_EXIT=$?
        set -e
        if [ $_PATCH_EXIT -ne 0 ]; then
            echo "::warning::fetch-pr-context: failed to fetch commit patch for ${SHA} on PR ${PR}" >&2
            continue
        fi
        # .files[].patch is legitimately absent for binary or empty files — skip those per-file
        PATCH="$(echo "$_PATCH_JSON" | "$DEVFLOW_JQ" -r '[.files[] | select(has("patch")) | .patch] | join("\n")')"
        if [ -n "$PATCH" ]; then
            PATCHES="${PATCHES}${PATCH}"$'\n'
        fi
    done < <(echo "$POSTBOT_SHAS" | "$DEVFLOW_JQ" -r '.[]')
    if [ -n "$PATCHES" ]; then
        HUMAN_POSTBOT_DIFF="$("$DEVFLOW_JQ" -Rs '.' <<<"$PATCHES")"
    fi
fi

# ── 13. Write output ──────────────────────────────────────────────────────────
REPO_ROOT="$(devflow_repo_root)"
OUT_DIR="${REPO_ROOT}/.prflow/tmp"
mkdir -p "$OUT_DIR"
OUT_FILE="${OUT_DIR}/pr-${PR}.context.json"

# Large values are written to temp files and passed via --rawfile / --slurpfile
# to avoid exceeding ARG_MAX when assembling the final jq bundle.
# Small scalars (numbers, short strings, booleans) remain as --arg / --argjson.
# (_JQ_TMP and its cleanup trap are established up in section 11, above the
# review_verdicts union that also uses them.)

# --- raw strings (written as bare text; jq --rawfile reads them as JSON strings) ---
printf '%s' "$TITLE"          > "$_JQ_TMP/title.txt"
printf '%s' "$BODY"           > "$_JQ_TMP/body.txt"
printf '%s' "$DIFFSTAT"       > "$_JQ_TMP/diffstat.txt"

# --- JSON values (written as JSON; jq --slurpfile wraps in array → use $name[0]) ---
# diff: already a JSON string or the literal "null"
printf '%s' "$DIFF_JSON"                 > "$_JQ_TMP/diff.json"
printf '%s' "$HUMAN_POSTBOT_DIFF"        > "$_JQ_TMP/human_postbot_diff.json"
printf '%s' "$ISSUE_JSON"               > "$_JQ_TMP/issue.json"
printf '%s' "$REVIEW_COMMENTS"          > "$_JQ_TMP/review_comments.json"
printf '%s' "$PR_COMMENTS"              > "$_JQ_TMP/pr_comments.json"
printf '%s' "$PR_REVIEWS"               > "$_JQ_TMP/pr_reviews.json"
printf '%s' "$COMMITS"                  > "$_JQ_TMP/commits.json"
printf '%s' "$CHANGED_FILES"            > "$_JQ_TMP/changed_files.json"
printf '%s' "$REVIEW_VERDICTS"          > "$_JQ_TMP/review_verdicts.json"
printf '%s' "$WORKPAD_BODY_JSON"        > "$_JQ_TMP/workpad_body.json"
printf '%s' "$REFLECTIONS"              > "$_JQ_TMP/reflections.json"
printf '%s' "$IMPLEMENT_SUMMARY_JSON"   > "$_JQ_TMP/implement_summary_comment.json"

# argjson-ok: pr additions deletions diff_truncated issue_number review_reject_outstanding review_verdict_unparsed_count review_comments_count post_bot_commits ci_failures_during_pr ci_status_unknown pr_devflow_provenance reflections_friction_count base_update_checkpoint4_present ttm_hours -- all bounded scalars (numbers/booleans), never corpus-sized; every corpus-sized operand here is routed via --slurpfile (issue #895)
"$DEVFLOW_JQ" -n \
    --argjson pr "$PR" \
    --arg kind "$KIND" \
    --arg branch "$BRANCH" \
    --arg base_ref "$BASE_REF" \
    --arg head_sha "$HEAD_SHA" \
    --arg merge_commit_sha "$MERGE_COMMIT_SHA" \
    --arg merged_at "$MERGED_AT" \
    --arg created_at "$CREATED_AT" \
    --arg author "$AUTHOR" \
    --rawfile title "$_JQ_TMP/title.txt" \
    --rawfile body "$_JQ_TMP/body.txt" \
    --argjson additions "$ADDITIONS" \
    --argjson deletions "$DELETIONS" \
    --slurpfile changed_files "$_JQ_TMP/changed_files.json" \
    --rawfile diffstat "$_JQ_TMP/diffstat.txt" \
    --slurpfile diff "$_JQ_TMP/diff.json" \
    --argjson diff_truncated "$DIFF_TRUNCATED" \
    --slurpfile human_postbot_diff "$_JQ_TMP/human_postbot_diff.json" \
    --argjson issue_number "${ISSUE_NUMBER}" \
    --slurpfile issue "$_JQ_TMP/issue.json" \
    --slurpfile review_comments "$_JQ_TMP/review_comments.json" \
    --slurpfile pr_comments "$_JQ_TMP/pr_comments.json" \
    --slurpfile pr_reviews "$_JQ_TMP/pr_reviews.json" \
    --slurpfile commits "$_JQ_TMP/commits.json" \
    --slurpfile workpad_body "$_JQ_TMP/workpad_body.json" \
    --slurpfile reflections "$_JQ_TMP/reflections.json" \
    --slurpfile review_verdicts "$_JQ_TMP/review_verdicts.json" \
    --argjson review_reject_outstanding "$REVIEW_REJECT_OUTSTANDING" \
    --argjson review_verdict_unparsed_count "$REVIEW_VERDICT_UNPARSED_COUNT" \
    --slurpfile implement_summary_comment "$_JQ_TMP/implement_summary_comment.json" \
    --argjson review_comments_count "$REVIEW_COMMENTS_COUNT" \
    --argjson post_bot_commits "$POST_BOT_COMMITS" \
    --argjson ci_failures_during_pr "$CI_FAILURES" \
    --argjson ci_status_unknown "$CI_STATUS_UNKNOWN" \
    --arg workpad_final_status "$WORKPAD_FINAL_STATUS" \
    --argjson pr_devflow_provenance "$PR_DEVFLOW_PROVENANCE" \
    --argjson reflections_friction_count "$REFLECTION_FRICTION_COUNT" \
    --argjson base_update_checkpoint4_present "$BASE_UPDATE_CHECKPOINT4_PRESENT" \
    --argjson ttm_hours "$TTM_HOURS" \
    '{
        pr: $pr,
        kind: $kind,
        branch: $branch,
        base_ref: $base_ref,
        head_sha: $head_sha,
        merge_commit_sha: $merge_commit_sha,
        merged_at: $merged_at,
        created_at: $created_at,
        author: $author,
        title: $title,
        body: $body,
        additions: $additions,
        deletions: $deletions,
        changed_files: $changed_files[0],
        diffstat: $diffstat,
        diff: $diff[0],
        diff_truncated: $diff_truncated,
        human_postbot_diff: $human_postbot_diff[0],
        issue_number: $issue_number,
        issue: $issue[0],
        review_comments: $review_comments[0],
        pr_comments: $pr_comments[0],
        pr_reviews: $pr_reviews[0],
        commits: $commits[0],
        workpad_body: $workpad_body[0],
        pr_devflow_provenance: $pr_devflow_provenance,
        reflections: $reflections[0],
        reflections_friction_count: $reflections_friction_count,
        base_update_checkpoint4_present: $base_update_checkpoint4_present,
        review_verdicts: $review_verdicts[0],
        review_verdict_unparsed_count: $review_verdict_unparsed_count,
        implement_summary_comment: $implement_summary_comment[0],
        signals: {
            review_comments_count: $review_comments_count,
            post_bot_commits: $post_bot_commits,
            ci_failures_during_pr: $ci_failures_during_pr,
            ci_status_unknown: $ci_status_unknown,
            workpad_final_status: $workpad_final_status,
            ttm_hours: $ttm_hours,
            review_reject_outstanding: $review_reject_outstanding
        }
    }' > "$OUT_FILE"

echo "$OUT_FILE"

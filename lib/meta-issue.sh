#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# meta-issue.sh — the retrospective loop's issue filer: file (or update) one
# GitHub issue for a devflow pattern and record a `filed` meta-issue entry on that
# pattern's lifecycle record in overrides.json (issue #788). The entry carries the
# issue number and URL and is keyed by number: a filing whose number is already
# present updates that entry in place rather than appending a duplicate, so the
# open-issue de-dupe re-recording an existing issue every week does not exhaust the
# per-category cap against one real issue. This helper writes NO `dismissed` entry
# — `dismissed{}` is human-owned and written by no filing path; suppression now
# lasts exactly as long as the issue-closure lifecycle `lib/pattern-state.sh`
# reconciles, not permanently. The overrides write is skipped entirely on
# --dry-run, which observes only. The body is authored by Stage B
# (retrospective-audit) to create-issue quality and is filed verbatim, so the
# issue can later be executed through the normal /devflow:implement -> review
# pipeline.
#
# Usage:
#   meta-issue.sh --tag <theme-tag> --slug <sanitized-tag> \
#                 --category <category-slug> \
#                 --title <issue-title> --body-file <path> \
#                 --overrides <path> [--repo <owner/name>] [--dry-run]
#
# --repo: the repository to file into and de-dupe against. Defaults to the
# resolved current repository (lib/repo-identity.sh). It is recorded on the
# lifecycle entry so reconcile resolves the issue number in the repository it was
# actually issued in — a bare number names different work in another repository.
#
# --category (issue #891): the fixed-vocabulary category the filed pattern belongs
# to, written as the lifecycle record's `category` field so the record's key can be
# an opaque filing key. Validated against the slug grammar [a-z0-9-]+ (narrower
# than --tag/--slug), required, before any GitHub call.
set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Argument parsing ─────────────────────────────────────────────────────────
TAG=
SLUG=
CATEGORY=
TITLE=
BODY_FILE=
OVERRIDES=
REPO=
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)        TAG="$2";       shift 2 ;;
        --slug)       SLUG="$2";      shift 2 ;;
        --category)   CATEGORY="$2";  shift 2 ;;
        --title)      TITLE="$2";     shift 2 ;;
        --body-file)  BODY_FILE="$2"; shift 2 ;;
        --overrides)  OVERRIDES="$2"; shift 2 ;;
        --repo)       REPO="$2";      shift 2 ;;
        --dry-run)    DRY_RUN=1;      shift   ;;
        *) echo "meta-issue: unknown argument: $1" >&2; exit 1 ;;
    esac
done

for var in TAG SLUG CATEGORY TITLE BODY_FILE OVERRIDES; do
    if [[ -z "${!var}" ]]; then
        echo "meta-issue: missing required argument --${var,,}" >&2
        exit 1
    fi
done

# Validate TAG before it is interpolated into the de-dupe `--search` string: a TAG
# carrying a GitHub search qualifier (e.g. `in:body`, `label:foo`) or whitespace
# could mis-route the lookup and make the de-dupe silently miss, re-filing a
# duplicate. TAG is canonical (a compute-patterns.jq slug) in practice; reject
# anything that is not the slug grammar so a drift fails loud at the boundary.
case "$TAG" in
    *[!A-Za-z0-9_-]*|'')
        echo "meta-issue: invalid --tag '${TAG}' (expected [A-Za-z0-9_-]+)" >&2
        exit 1 ;;
esac

# Validate SLUG against the same grammar: it is the overrides.patterns[] key the
# lifecycle write injects, so a SLUG carrying a path/qualifier/space could produce
# a non-canonical key that compute-patterns.jq would surface as a phantom pattern.
case "$SLUG" in
    *[!A-Za-z0-9_-]*|'')
        echo "meta-issue: invalid --slug '${SLUG}' (expected [A-Za-z0-9_-]+)" >&2
        exit 1 ;;
esac

# Validate CATEGORY against the SLUG GRAMMAR `[a-z0-9-]+` (issue #891) —
# deliberately NARROWER than the `[A-Za-z0-9_-]+` grammar applied to --tag/--slug
# above. The category is written to the record's `category` field and read back by
# compute-patterns.jq (which canonicalizes stored categories through slugify) and
# by the dismissed{} lookup and the per-category cap sum, all of which key on
# slugify-produced values. A value outside the slug alphabet (an uppercase letter,
# an underscore) cannot match a slugify-produced corpus category, a slugify-ed
# dismissed{} key, or another record's canonicalized category, so reject it at the
# boundary — BEFORE any GitHub call — rather than write a category that can never
# attribute. Runs after the required-argument loop above (which already rejects an
# absent --category), so both the absent and the malformed cases fail before the
# de-dupe lookup contacts GitHub.
case "$CATEGORY" in
    *[!a-z0-9-]*|'')
        echo "meta-issue: invalid --category '${CATEGORY}' (expected the slug grammar [a-z0-9-]+)" >&2
        exit 1 ;;
esac

# ── gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins (injection for tests) and is passed explicitly
# as a per-command env prefix to each child helper invocation below ────────────
# shellcheck source=resolve-gh.sh
. "$HERE/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# Repository identity: the de-dupe search, the filing and the lifecycle entry are
# all repository-qualified, so an unresolved repository is a blocker rather than a
# gh call that silently resolves the ambient git remote (see lib/repo-identity.sh).
# shellcheck source=repo-identity.sh
. "$HERE/repo-identity.sh"
if [ -n "$REPO" ]; then
    REPO="$(devflow_resolve_repo "$REPO")" || exit 1
else
    REPO="$(devflow_resolve_repo)" || exit 1
fi

# The reserved PRFlow provenance label plus a fixed Retrospective marker stamped
# on every filed issue. Both are hardcoded constants — no config key controls
# them (PRFlow is the scan/classify provenance string, whose superseded DevFlow
# spelling stays selectable on already-labelled history but is never stamped on
# new filings; Retrospective marks the loop's own filings). Application is
# best-effort and never aborts the filing.
_apply_labels() {  # $1 = issue number
    local _num="$1" _lbl
    [[ "$DRY_RUN" -eq 1 ]] && return 0
    # Guard the number's shape: an empty or non-numeric token (e.g. a gh warning
    # line that leaked into the URL the caller derived ${URL##*/} from) must leave
    # a SPECIFIC breadcrumb, never a silent skip — label stamping is best-effort,
    # but a label we could not even attempt should say why.
    case "$_num" in
        ''|*[!0-9]*)
            echo "::warning::meta-issue: could not derive a numeric issue number (got: '${_num}') — PRFlow/Retrospective labels NOT applied" >&2
            return 0 ;;
    esac
    for _lbl in PRFlow Retrospective; do
        DEVFLOW_GH="$DEVFLOW_GH" "$HERE/../scripts/ensure-label.sh" "$_lbl" || true
    done
    # Apply via the shared REST label-apply helper (POST .../issues/{n}/labels),
    # which needs only the `repo` scope — `gh issue edit --add-label` would resolve
    # the repo via org-scoped GraphQL and fail under a repo-scoped token. The helper
    # is best-effort (always exits 0) and leaves its own specific stderr breadcrumb
    # naming the target + labels on failure, mirroring ensure-label.sh's discipline.
    # Redirect stdout: apply-labels.sh prints a one-word outcome token to stdout, which
    # would otherwise pollute the issue URL this script emits on its own stdout (Step 3).
    DEVFLOW_GH="$DEVFLOW_GH" "$HERE/../scripts/apply-labels.sh" "$_num" PRFlow Retrospective >/dev/null || true
}

# ── Step 1: de-dupe — find or create the issue ──────────────────────────────
# The GitHub `--search` is TOKENIZED, so it can return an issue whose title does
# not literally carry `meta: ${TAG}` (a loose token hit, or search-index lag).
# Fetch the candidates and STRICTLY re-parse each title's slug, selecting only an
# exact `${TAG}` match — mirroring actionable-patterns.sh's cooldown re-parse — so
# the recurrence comment and the cooldown URL can never pin to the wrong issue.
# `--limit 200` matches the cooldown fetch (the gh default is only 30). A non-JSON
# body fails CLOSED (same discipline as the cooldown lookup), not silently empty.
_EXISTING_RAW="$("$DEVFLOW_GH" issue list \
    --repo "$REPO" \
    --search "[devflow-retrospective] meta: ${TAG} in:title" \
    --state open \
    --limit 200 \
    --json number,url,title)" \
  || { echo "::error::meta-issue: de-dupe lookup failed for tag '${TAG}'" >&2; exit 1; }
EXISTING="$(printf '%s' "$_EXISTING_RAW" | "$DEVFLOW_JQ" -c --arg tag "$TAG" '
    [ .[]
      | select(((((.title | capture("\\[devflow-retrospective\\] meta: (?<slug>[A-Za-z0-9_-]+)")?) // {}) | .slug) // "") == $tag)
    ] | .[0] // empty')" \
  || { echo "::error::meta-issue: could not parse the de-dupe list as JSON for tag '${TAG}' (gh returned non-JSON?)" >&2; exit 1; }

if [[ -n "$EXISTING" ]]; then
    URL="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -r '.url')"
    NUMBER="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -r '.number')"
    # Fail CLOSED on a de-dup hit that yielded no usable url/number (a gh --json
    # contract drift would make jq -r emit the literal "null"). Mirrors the
    # create-path URL guard below — without it a "null" url/number would flow into
    # the recurrence comment, the labels, and the overrides lifecycle record.
    case "$URL" in https://*/issues/[0-9]*) : ;; *) echo "::error::meta-issue: de-dupe hit returned no usable issue URL for tag '${TAG}' (got: '${URL}')" >&2; exit 1 ;; esac
    case "$NUMBER" in ''|*[!0-9]*) echo "::error::meta-issue: de-dupe hit returned no numeric issue number for tag '${TAG}' (got: '${NUMBER}')" >&2; exit 1 ;; esac
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "$DEVFLOW_GH" issue comment "$NUMBER" --repo "$REPO" \
            --body "Pattern \`${TAG}\` recurred again — see the latest retrospective-weekly run." \
            >/dev/null \
          || echo "::warning::meta-issue: failed to add recurrence comment to #${NUMBER}" >&2
    fi
    _apply_labels "$NUMBER"
    echo "meta-issue: updated ${URL}" >&2
else
    if [[ "$DRY_RUN" -eq 1 ]]; then
        URL="https://example.invalid/issues/DRYRUN"
    else
        # The "[devflow-retrospective] meta: ${TAG}" prefix is the de-dupe key the
        # Step-1 search matches on (keep it verbatim); the caller's --title is
        # appended so the issue carries a human-readable summary too. The body
        # is the Stage-B-authored issue spec, filed verbatim.
        # COUPLED SITE: lib/actionable-patterns.sh re-parses the slug back out of
        # this exact title (its cooldown map captures the token after "meta: ") —
        # change this format and update that regex in lockstep (a run.sh
        # round-trip assertion pins the two together).
        URL="$("$DEVFLOW_GH" issue create \
            --repo "$REPO" \
            --title "[devflow-retrospective] meta: ${TAG} — ${TITLE}" \
            --body-file "$BODY_FILE")"
        # Strip whitespace with a BUILTIN, never `tr`: preflight guarantees only
        # git/gh/jq/python3, and this value decides an EMITTED result. A missing
        # `tr` would empty $URL, the shape guard below would fire, and the script
        # would exit 1 AFTER the issue was created — making the orchestrator record
        # a genuinely-filed issue as blocked, the exact misstatement the recovery
        # branch below exists to prevent, while blaming gh for a missing binary.
        URL="${URL//[$' \t\r\n']/}"
        # Fail CLOSED on a non-issue-URL: `gh issue create` can exit 0 yet emit
        # empty/garbage stdout (URL printed to stderr, an auth/upgrade warning on
        # stdout, a swallowed transient error). Without this guard an empty/garbage
        # URL would flow on as a "success" — the orchestrator would record the
        # pattern as FILED and write an overrides.json lifecycle record for an
        # issue that does not exist (the exact "never report unfiled as filed"
        # invariant this loop must hold). Exit non-zero so the orchestrator's
        # `if ISSUE_URL=$(...meta-issue.sh...)` catches it and records a blocker.
        case "$URL" in
            https://*/issues/[0-9]*) : ;;
            *) echo "::error::meta-issue: 'gh issue create' returned no usable issue URL for tag '${TAG}' (got: '${URL}')" >&2; exit 1 ;;
        esac
    fi
    # Derive the issue number from the created URL (trailing path segment) so the
    # labels land on the issue we just filed. The URL-shape guard above does NOT
    # guarantee a numeric tail — its `[0-9]*` is a glob ("a digit followed by
    # anything"), so `.../issues/12ab` passes it — which is exactly why
    # `_apply_labels` re-validates the token strictly against `''|*[!0-9]*` on
    # BOTH paths rather than trusting the URL shape, and why the lifecycle write
    # below validates its own re-derivation of the same token.
    _apply_labels "${URL##*/}"
    echo "meta-issue: created ${URL}" >&2
fi

# ── Step 2: update overrides.json ────────────────────────────────────────────
# Skip the real mutation on a dry run — a dry run must observe, never alter the
# cross-run state. Otherwise it would record a lifecycle entry pointing at the
# DRYRUN sentinel and a later live run would treat the slug as already filed and
# skip the real filing.
if [[ "$DRY_RUN" -eq 0 ]]; then
    # Both of these run AFTER `gh issue create` has already succeeded, so neither
    # may abort under `set -euo pipefail`: a failed redirect (read-only fs, absent
    # parent dir, full disk) or a failed `date` would kill the script before
    # Step 3 prints the URL, making the orchestrator record a genuinely-filed
    # issue as NOT filed. That is the exact misstatement the mktemp and mv guards
    # below were written to prevent; the same abort class must not survive here.
    # Both route into the same "issue WAS filed, record failed" recovery.
    RECORD_WRITTEN=0
    NOW=""
    if [[ ! -f "$OVERRIDES" ]] || [[ ! -s "$OVERRIDES" ]]; then
        printf '{"schema_version":4,"patterns":{},"dismissed":{}}' > "$OVERRIDES" || {
            echo "::error::meta-issue: issue WAS filed (${URL}) but the overrides file ${OVERRIDES} could not be initialized — de-dupe will prevent a duplicate next run" >&2
            printf '%s\n' "$URL"
            exit 0
        }
    fi

    # Refuse to record into a file this helper is not the migrator for. The jq
    # below sets `.schema_version = 4` and performs NO migration, so stamping an
    # unmigrated (v1/v2/v3) file would claim a migration that never happened — and
    # pattern-state.sh's `_migrate` dispatches on the stored version, so a v4 stamp
    # written here would make it treat the file as current and never run. Every
    # loop-written pre-v4 record (a v1 `dismissed{}` entry, a v2 record still
    # lacking a `category`, or a v3 entry still lacking a `repo`) would be frozen in a half-migrated shape: the
    # unclearable-dismissal / miscategorized-record failure this lifecycle exists to
    # end, arriving through the loop's own writer. Decline the record instead and
    # route to the issue-WAS-filed recovery below, so the filing is still reported
    # and de-dupe still prevents a duplicate next run. (`// 1` mirrors _migrate's
    # own read, so an absent key reads as v1 there too.)
    _MI_SCHEMA="$("$DEVFLOW_JQ" -r '.schema_version // 1' "$OVERRIDES" 2>/dev/null)" || _MI_SCHEMA=""
    if [ "$_MI_SCHEMA" != "4" ]; then
        echo "::error::meta-issue: issue WAS filed (${URL}) but ${OVERRIDES} reports schema_version '${_MI_SCHEMA:-unreadable}', not 4 — refusing to stamp a v4 lifecycle record onto a file this helper does not migrate (run 'pattern-state.sh migrate ${OVERRIDES}' first); de-dupe will prevent a duplicate next run" >&2
        printf '%s\n' "$URL"
        exit 0
    fi

    NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)" || {
        echo "::error::meta-issue: issue WAS filed (${URL}) but the timestamp for its lifecycle record could not be derived — de-dupe will prevent a duplicate next run" >&2
        printf '%s\n' "$URL"
        exit 0
    }
    ISSUE_NUM="${URL##*/}"
    # Validate the derived key STRICTLY. The URL guards above use the glob
    # `https://*/issues/[0-9]*`, and `[0-9]*` is a GLOB — "a digit followed by
    # anything" — not a numeric assertion: `https://host/issues/12ab` passes it
    # and yields ISSUE_NUM="12ab", and `.../issues/12/` yields the empty string.
    # Either would make the `--argjson num` below exit non-zero and land in the
    # record-write recovery branch, which would then blame a WRITE failure for
    # what is actually a malformed URL. Fail here instead, where the breadcrumb
    # can name the real cause. (The de-dupe path's $NUMBER is already validated
    # against this same grammar; this covers the create path's re-derivation.)
    case "$ISSUE_NUM" in
        ''|*[!0-9]*)
            echo "::error::meta-issue: issue URL '${URL}' does not end in a bare issue number (derived '${ISSUE_NUM}') — cannot key the lifecycle entry for tag '${TAG}'" >&2
            exit 1 ;;
    esac
    # Staged BESIDE the destination, never under $TMPDIR, for the same reason
    # lib/pattern-state.sh's _atomic_write is: `mv` is an atomic rename only
    # within one filesystem, so a $TMPDIR staging file on a runner whose /tmp is
    # a separate filesystem turns this into a copy-then-unlink that can leave
    # overrides.json truncated. The directory is derived with a bash builtin,
    # never `dirname` — a non-preflight PATH tool that silently yielded empty
    # would relocate the staging file to the filesystem root. Coupled pair with
    # pattern-state.sh's `_dir_of`: that script is a standalone executable, so
    # sourcing its helper here would run its arg parsing. Change both or neither.
    OVERRIDES_DIR="${OVERRIDES%/*}"
    [ "$OVERRIDES_DIR" = "$OVERRIDES" ] && OVERRIDES_DIR="."
    # A mktemp failure must NOT abort under `set -e`: the issue itself was
    # already created, and aborting here would report it as "not filed" — the
    # exact misstatement the else-branch below exists to avoid. An empty
    # OVERRIDES_TMP makes the guarded write below fail into that branch.
    OVERRIDES_TMP="$(mktemp "$OVERRIDES_DIR/.overrides.XXXXXX" 2>/dev/null || true)"
    # Append (or update in place) a `filed` meta-issue entry on the slug's
    # lifecycle record, KEYED BY ISSUE NUMBER (issue #788): the Step-1 de-dupe
    # re-runs this write on every recurrence with the SAME open issue, so an
    # unkeyed append would write a duplicate entry for one real issue every week
    # and exhaust max_open_per_category against a single open issue. An entry whose
    # number is already present is updated in place; a new number is appended. The
    # record's provenance is stamped once (first filing) and preserved on
    # recurrence. This writes NO `dismissed` entry — that map is human-owned.
    # The in-place update clears the entry's closure fields (`closedAt`,
    # `fixed_at`, `state_reason`) alongside `state:"filed"`, byte-for-byte the
    # field set lib/pattern-state.sh's OPEN transition writes: re-filing against a
    # still-open issue is the same assertion "this entry is open", so leaving a
    # prior closure timestamp on a `filed` entry would be an internally
    # inconsistent shape until the next reconcile happened to clear it.
    if [ -n "$OVERRIDES_TMP" ] && "$DEVFLOW_JQ" \
        --arg slug "$SLUG" \
        --arg category "$CATEGORY" \
        --arg now "$NOW" \
        --arg url "$URL" \
        --argjson num "$ISSUE_NUM" \
        --arg repo "$REPO" \
        '.schema_version = 4
         | .patterns = (.patterns // {})
         | .dismissed = (.dismissed // {})
         | .patterns[$slug] = (
             (.patterns[$slug] // {category:$category, state:"filed", fixed_at:null, provenance:$now, meta_issues:[]})
             | .category = $category
             | .provenance = (.provenance // $now)
             | .meta_issues = (
                 (.meta_issues // []) as $e
                 | if ($e | any(.number == $num and (.repo // $repo) == $repo))
                   then ($e | map(if (.number == $num and (.repo // $repo) == $repo) then (. + {repo:$repo, url:$url, state:"filed", closedAt:null, fixed_at:null, state_reason:null}) else . end))
                   else ($e + [{number:$num, repo:$repo, url:$url, state:"filed", closedAt:null}])
                   end
               )
             | .state = "filed"
             | .fixed_at = null
           )' \
        "$OVERRIDES" > "$OVERRIDES_TMP"; then
        # The rename is GUARDED for the same reason the mktemp above is: a bare
        # `mv` failing under `set -euo pipefail` would abort this script before
        # Step 3 prints the URL, so an issue that WAS filed would be reported to
        # the orchestrator as not filed — the precise misstatement the recovery
        # branch below exists to prevent. Route a failed rename into that branch
        # instead of aborting. (Staging beside the destination keeps this a
        # same-filesystem rename, so a failure here is rare, not impossible.)
        if mv "$OVERRIDES_TMP" "$OVERRIDES"; then
            RECORD_WRITTEN=1
        fi
    fi
    if [ "$RECORD_WRITTEN" -eq 0 ]; then
        # The issue WAS filed (URL is on stdout below); only the lifecycle record
        # failed. Do NOT report this as "not filed" — that would misstate the
        # state and lose the real issue. Exit 0 with the URL so the orchestrator
        # records the filing; on the next run the open-issue de-dupe (Step 1) is
        # the best-effort, single-layered recovery — it finds the still-open issue
        # and comments instead of re-filing, recovering the missing record only
        # if that lookup itself succeeds (not a guarantee).
        rm -f "$OVERRIDES_TMP"
        echo "::error::meta-issue: issue WAS filed (${URL}) but its lifecycle record could not be written in ${OVERRIDES} — de-dupe will prevent a duplicate next run" >&2
    fi
fi

# ── Step 3: print URL to stdout ───────────────────────────────────────────────
printf '%s\n' "$URL"

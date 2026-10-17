#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scan.sh — emit JSON array of unprocessed PRs matching the retrospection predicate.
#
# A PR qualifies when ANY of: it carries the reserved DevFlow label
# (author/branch-agnostic), it is by a watched author and closes >=1 issue, or
# implementation_branch_prefix is set non-empty and its branch matches it. See
# the RETRO_PREDICATE block below.
#
# Usage:
#   scan.sh                       weekly mode: PRs matching the predicate merged
#                                 in the last 7 days, minus those already in
#                                 .prflow/learnings/retrospectives.jsonl. The DevFlow-label
#                                 pass runs even with no watched authors configured.
#   scan.sh --prs 774,786,772     ad-hoc mode: use exactly these PR numbers,
#                                 skipping the GitHub search AND the
#                                 already-processed filter (for backfill / a
#                                 targeted re-run / a test run). Each number is
#                                 still confirmed to match the retrospection
#                                 predicate; others are dropped with a warning.
#
# Output: [{number, headRefName, mergedAt, repo, pr_key}, ...] sorted by mergedAt,
# capped at max_prs_per_run. `pr_key` is the canonical "<owner>/<name>#<number>"
# comparison key; the already-processed filter keys on it, never on the number.
set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=resolve-gh.sh
. "$HERE/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# shellcheck source=./config-source.sh
. "$HERE/config-source.sh"
# Repository identity: the processed-history comparison and every gh call below are
# repository-qualified, so an unresolved repository is a blocker rather than a
# silently-empty operand (see lib/repo-identity.sh).
# shellcheck source=./repo-identity.sh
. "$HERE/repo-identity.sh"
# Shared login rule (issue #157): watched-author matching and search-form
# composition both normalize through lib/login_normalize.py, so no `[bot]`/`app/`
# strip lives inline here.
# shellcheck source=login-match.sh
. "$HERE/login-match.sh" 2>/dev/null \
  || echo "prflow: login-match.sh could not be sourced beside ${BASH_SOURCE[0]} — watched-author matching will fail closed" >&2

EXPLICIT_PRS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prs) EXPLICIT_PRS="$2"; shift 2 ;;
        *) echo "scan: unknown argument: $1" >&2; exit 1 ;;
    esac
done

REPO="$(devflow_resolve_repo)" || exit 1
LEGACY_RECORD_REPO="$(devflow_legacy_record_repo)" || exit 1
MAX_PRS="$(devflow_conf '.prflow_retrospective.max_prs_per_run' 500)"
# Adopter's implementation-bot branch prefix (default "claude/"). An EMPTY
# prefix is honoured as "disable the prefix path" — it must NOT degrade to a
# `*`-glob that matches every branch (the old `${IMPL_PREFIX}*` bug).
IMPL_PREFIX="$(devflow_conf '.prflow_retrospective.implementation_branch_prefix' 'claude/')"
# Watched authors (comma list, [bot] suffix optional). Used by the closes-issue
# path (b); the label path (a) is deliberately author-agnostic, so it does not
# depend on this being set.
WATCHED="$(devflow_watched_authors)"

# ── The provenance label, both spellings (issue #1003) ───────────────────────
# PRFlow stamps PROVENANCE_LABEL on everything it creates; PROVENANCE_LABEL_SUPERSEDED
# is the pre-rename spelling every artifact created before the rename still carries.
# Selection accepts BOTH, so no retrospective history is lost, and neither name is a
# config key (see the deferred.labels contrast in .prflow/config.schema.json).
# END CRITERION for dropping the superseded spelling, mirroring
# lib/rename-map.json's transitional_read_through.end_criterion: the superseded arm
# is removed in the first release after the maintainer confirms no repository the
# retrospective loop scans still carries a PR or issue labelled with it. It is not
# removed on a timer, and it is not removed while any scanned repository can still
# surface a pre-rename merged PR inside the scan window.
PROVENANCE_LABEL='PRFlow'
PROVENANCE_LABEL_SUPERSEDED='DevFlow'

# ── Retrospection predicate (shared by every mode) ───────────────────────────
# A merged PR qualifies for retrospection when ANY of these holds:
#   (a) it carries the reserved PRFlow provenance label, or its superseded
#       DevFlow spelling                                     (author/branch-agnostic)
#   (b) $watched is true AND it closes >=1 issue (closingIssuesReferences non-empty)
#   (c) implementation_branch_prefix is set non-empty AND its branch matches it
# Inputs: $impl (prefix string, "" disables path c), $watched (bool).
# Operates on one PR object carrying .labels, .closingIssuesReferences,
# .headRefName (each defaulted, so a missing field never aborts the filter).
# .labels entries may be objects ({name}) or bare strings depending on the gh
# call/stub, so normalise to the name before comparing.
RETRO_PREDICATE='
  ((.labels // []) | map(if type == "object" then (.name // "") else . end) | any(. == "'"$PROVENANCE_LABEL"'" or . == "'"$PROVENANCE_LABEL_SUPERSEDED"'"))
  or ($watched and (((.closingIssuesReferences // []) | length) > 0))
  or (($impl != "") and ((.headRefName // "") | startswith($impl)))
'

# ── _add_candidates <json-array> ─────────────────────────────────────────────
# Fold a batch of PR objects into the running CANDIDATES set, deduplicating by
# number. Shared by every mode so the union/dedupe rule lives in one place.
_add_candidates() {  # $1 = JSON array of PR objects
    local _a_file
    _a_file="$(mktemp)"
    # Route the accumulating CANDIDATES set through --slurpfile: it grows with the
    # scan window and, on a large first-run backlog, would overflow the kernel arg
    # limit as an --argjson argv slot (jq: "Argument list too long", issue #783).
    printf '%s' "$CANDIDATES" > "$_a_file"
    # argjson-ok: b -- $1 is one bounded batch (a single PR or one <= per-page-limit
    # page), safe as argv.
    # Clean up on the jq-abort path too: under `set -e` a nonzero jq would skip the
    # trailing `rm -f` and orphan the temp in $TMPDIR. A localized `|| { rm; return 1; }`
    # cleans then re-raises (the function returns nonzero, so `set -e` still aborts the
    # caller) — preferred here over a `trap` because this file uses sequential single-owner
    # EXIT traps and a trap set in this function would clobber the active one.
    CANDIDATES="$("$DEVFLOW_JQ" -nc --slurpfile a "$_a_file" --argjson b "$1" '$a[0] + $b | unique_by(.number)')" \
      || { rm -f "$_a_file"; return 1; }
    rm -f "$_a_file"
}

# ── _author_is_watched <login> ───────────────────────────────────────────────
# True when <login> matches a WATCHED entry under the shared login rule (issue
# #157): both sides normalize through lib/login_normalize.py, so an `app/<slug>`
# gh author matches a bare-slug or `<slug>[bot]` watched entry. A resolver failure
# (rc 2) reports NOT watched — the fail-closed direction the retrospective wants.
_author_is_watched() {
    local _rc
    devflow_login_matches "$1" "$WATCHED" && return 0 || _rc=$?
    [ "$_rc" -eq 1 ] && return 1
    echo "::warning::scan: could not run lib/login_normalize.py to match author '$1' against the watched-authors list; treating as not watched (fail-closed)" >&2
    return 1
}

# ── Ad-hoc mode: explicit PR list, no search, no processed-filter ─────────────
if [ -n "$EXPLICIT_PRS" ]; then
    CANDIDATES='[]'
    # Scratch for the predicate jq's stderr, so a detonation breadcrumb names the
    # actual jq diagnostic (e.g. "Cannot iterate over string") and not just an
    # exit code. Overwritten per PR, read immediately, removed before the print.
    # Trap-cleaned so a mid-loop `set -e` abort can't orphan it in $TMPDIR.
    PRS_ERR="$(mktemp)"
    trap 'rm -f "$PRS_ERR"' EXIT
    IFS=',' read -ra _prs <<< "$EXPLICIT_PRS"
    for _p in "${_prs[@]}"; do
        _p="$(echo "$_p" | xargs)"
        [ -n "$_p" ] || continue
        if ! _PRJSON="$("$DEVFLOW_GH" pr view "$_p" --repo "$REPO" --json number,headRefName,mergedAt,state,labels,closingIssuesReferences,author 2>/dev/null)"; then
            echo "::warning::scan --prs: could not fetch PR ${_p}; skipping" >&2; continue
        fi
        _STATE="$(echo "$_PRJSON" | "$DEVFLOW_JQ" -r '.state // ""')"
        _HEAD="$(echo "$_PRJSON" | "$DEVFLOW_JQ" -r '.headRefName // ""')"
        if [ "$_STATE" != "MERGED" ]; then
            echo "::warning::scan --prs: PR ${_p} is ${_STATE:-unknown}, not MERGED; skipping" >&2; continue
        fi
        _WATCHED=false
        _author_is_watched "$(echo "$_PRJSON" | "$DEVFLOW_JQ" -r '.author.login // ""')" && _WATCHED=true
        # Split the jq exit status from the empty-result case. `select(…)` emits the
        # object on a match and nothing on a legitimate non-match — both exit 0 — so
        # the empty string alone cannot distinguish "evaluated and excluded" from
        # "the predicate never ran". A non-zero jq exit means the filter detonated
        # (e.g. a non-array `labels` slips the predicate's `// []` guard, so `map`
        # aborts); report that as a distinct "predicate evaluation failed"
        # breadcrumb rather than the misleading "matches no retrospection path".
        # Non-fatal by design here (warn + `continue`), unlike weekly mode's
        # degraded gate: --prs is the operator-named ad-hoc path, so a per-PR
        # breadcrumb on stderr is the right granularity rather than a hard exit.
        set +e
        # argjson-ok: watched -- bounded scalar (boolean flag).
        _SEL="$(echo "$_PRJSON" | "$DEVFLOW_JQ" -c --arg impl "$IMPL_PREFIX" --arg repo "$REPO" --argjson watched "$_WATCHED" \
            "select($RETRO_PREDICATE) | {number, headRefName, mergedAt, repo: \$repo, pr_key: (\$repo + \"#\" + (.number|tostring))}" 2>"$PRS_ERR")"
        _SEL_RC=$?
        set -e
        if [ "$_SEL_RC" -ne 0 ]; then
            echo "::warning::scan --prs: PR ${_p} (branch '${_HEAD}') predicate evaluation failed (jq exit ${_SEL_RC}: $(tr '\n' ' ' < "$PRS_ERR" | cut -c1-300)); skipping" >&2; continue
        fi
        if [ -z "$_SEL" ]; then
            echo "::warning::scan --prs: PR ${_p} (branch '${_HEAD}') matches no retrospection path; skipping" >&2; continue
        fi
        _add_candidates "[$_SEL]"
    done
    rm -f "$PRS_ERR"
    echo "$CANDIDATES" | "$DEVFLOW_JQ" -c --argjson cap "$MAX_PRS" --arg repo "$REPO" 'sort_by(.mergedAt) | [.[0:$cap][] | {number, headRefName, mergedAt, repo: $repo, pr_key: ($repo + "#" + (.number|tostring))}]'  # argjson-ok: cap -- scalar int
    exit 0
fi

# ── Weekly mode ──────────────────────────────────────────────────────────────
# Portable "7 days ago" (GNU `date -d` is not available on macOS/BSD; python3 is
# a hard dependency, so use it for date math).
SINCE="$(python3 -c 'import sys; sys.stdout.reconfigure(newline="\n"); import datetime as d; print((d.datetime.now(d.timezone.utc)-d.timedelta(days=7)).strftime("%Y-%m-%d"))')"

CANDIDATES='[]'
# Set when ANY candidate-source fetch or jq-reshape below hard-fails. Each such
# failure currently logs a ::warning::, substitutes an empty batch, and the run
# proceeds — so a partial GitHub outage silently UNDER-COUNTS the unprocessed set
# and exits 0, which a scheduled cron reads as "0 new PRs to retrospect" (the
# silent no-op the retrospective exists to eliminate). The degraded gate after
# the searches turns that into a non-zero exit.
DEGRADED=0
# Captures the stderr of each candidate-source fetch/reshape so the breadcrumbs
# below — and the now-FATAL degraded gate — can name the actual gh/jq cause (auth
# expiry vs rate-limit vs a malformed shape) rather than a generic "failed". One
# scratch file, overwritten per call (each breadcrumb reads it immediately, before
# the next call), removed just before the gate; collapse newlines and cap length
# so a breadcrumb stays a single bounded line. Trap-cleaned at creation so a
# `set -e` abort between here and the explicit `rm -f` below cannot orphan it;
# the later `ERR` trap replaces this one only after FETCH_ERR is removed.
FETCH_ERR="$(mktemp)"
trap 'rm -f "$FETCH_ERR"' EXIT

# ── Path (a): label pass — author- and branch-agnostic ───────────────────────
# Every merged PR carrying the reserved PRFlow provenance label -- or its
# superseded DevFlow spelling -- in the window
# qualifies, regardless of author or branch name. This runs even when no
# watched authors are configured (the label is the branch-naming-independent
# detection mechanism). Best-effort: a gh failure logs and yields no candidates.
# Both spellings are selected through ONE `--search` qualifier, never two
# `--label` flags: `gh pr list --label A --label B` (and `--label "A,B"`) is an
# AND, so it would return only PRs carrying BOTH and silently yield zero
# candidates. The `label:A,B` search qualifier is the only OR form.
if LABEL_BATCH="$("$DEVFLOW_GH" pr list --repo "$REPO" --state merged \
        --search "merged:>=${SINCE} label:${PROVENANCE_LABEL},${PROVENANCE_LABEL_SUPERSEDED}" \
        --json number,headRefName,mergedAt --limit 100 2>"$FETCH_ERR")"; then
    LABEL_BATCH="$(echo "$LABEL_BATCH" | "$DEVFLOW_JQ" '[.[] | {number, headRefName, mergedAt}]' 2>"$FETCH_ERR")" \
        || { echo "::warning::scan: jq reshape of the provenance-label batch failed ($(tr '\n' ' ' < "$FETCH_ERR" | cut -c1-300)); treating as empty" >&2; LABEL_BATCH='[]'; DEGRADED=1; }
else
    echo "::warning::gh pr list provenance-label search (label:${PROVENANCE_LABEL},${PROVENANCE_LABEL_SUPERSEDED}) failed ($(tr '\n' ' ' < "$FETCH_ERR" | cut -c1-300))" >&2; LABEL_BATCH='[]'; DEGRADED=1
fi
_add_candidates "$LABEL_BATCH"

# ── Paths (b)–(c): watched-author search ─────────────────────────────────────
# Skipped (not fatal) when no watched authors are configured — the label pass
# above still stands on its own.
if [ -z "$WATCHED" ]; then
    echo "::warning::no watched authors configured (prflow_retrospective.watched_authors / prflow.allowed_bots); relying on the provenance-label path only" >&2
else
    IFS=',' read -ra _watched <<< "$WATCHED"
    for _w in "${_watched[@]}"; do
        # Normalize the entry to its bare slug through the shared rule (issue #157),
        # so `app/my-bot` / `my-bot[bot]` both compose `author:app/my-bot` and
        # `author:my-bot` — never `author:app/app/my-bot`. A resolver failure or an
        # entry normalizing to empty skips the entry (fail-closed under the gate).
        _t="$(devflow_login_normalize "$_w")" || {
            echo "::warning::scan: could not run lib/login_normalize.py to normalize watched entry '${_w}'; skipping it (fail-closed)" >&2
            DEGRADED=1
            continue
        }
        [ -n "$_t" ] || continue
        for _form in "app/${_t}" "${_t}"; do
            if BATCH="$("$DEVFLOW_GH" pr list --repo "$REPO" --state merged \
                    --search "merged:>=${SINCE} author:${_form}" \
                    --json number,headRefName,author,mergedAt,labels,closingIssuesReferences --limit 100 2>"$FETCH_ERR")"; then
                # These are watched-author results, so $watched is true for the
                # closes-issue path (b). Filter locally with the shared predicate.
                # argjson-ok: watched -- bounded scalar literal (true).
                BATCH="$(echo "$BATCH" | "$DEVFLOW_JQ" --arg impl "$IMPL_PREFIX" --argjson watched true \
                    "[.[] | select($RETRO_PREDICATE) | {number, headRefName, mergedAt}]" 2>"$FETCH_ERR")" \
                    || { echo "::warning::scan: jq reshape failed for author:${_form} ($(tr '\n' ' ' < "$FETCH_ERR" | cut -c1-300)); treating as empty" >&2; BATCH='[]'; DEGRADED=1; }
            else
                echo "::warning::gh pr list failed for author:${_form} ($(tr '\n' ' ' < "$FETCH_ERR" | cut -c1-300))" >&2; BATCH='[]'; DEGRADED=1
            fi
            _add_candidates "$BATCH"
        done
    done
fi

rm -f "$FETCH_ERR"

# ── Degraded gate ─────────────────────────────────────────────────────────────
# If any candidate-source fetch/reshape above hard-failed, the unprocessed-PR set
# is under-counted. Fail non-zero (mirroring the retrospectives.jsonl hard-read
# error below) so the partial outage is not mistaken for "0 new PRs to
# retrospect" — exit before the processed-filter read; an under-counted set must
# never reach stdout looking complete. The per-source ::warning::s above already
# named each specific gh/jq cause; this gate is the fatal summary.
if [ "$DEGRADED" -ne 0 ]; then
    echo "::error::scan: one or more candidate-source fetches failed; the unprocessed-PR set would be under-counted. Exiting non-zero rather than reporting a partial set as complete." >&2
    exit 1
fi

# ── _decode_existing <jsonl-text> <source-label> ─────────────────────────────
# Parse retrospectives.jsonl text into the processed-PR set (the global EXISTING),
# exiting 1 on unparseable content or on zero pr records (empty, pr-less or
# truncated-but-still-parseable content): every record carries `.pr`
# (the #626 skip marker included — revisit if a pr-less record type is added), so a
# present file holding none is corruption, and an empty set would re-queue the whole
# backlog. Called in the current shell, so its exit terminates scan.
_decode_existing() {  # $1 = jsonl text, $2 = source label for breadcrumbs
    # The processed set is keyed on REPOSITORY + NUMBER, never a number alone: a
    # record for the previous repository's #7 must not suppress this repository's
    # #7. A record naming no repository binds to $LEGACY_RECORD_REPO for this scan,
    # never to $REPO: a reader does not attribute records. The store merge
    # (materialize-retrospectives.sh) is the one writer that gives such a record
    # the repository whose store holds it, and replaces it when that PR is analysed
    # again.
    if ! EXISTING="$(printf '%s' "$1" | "$DEVFLOW_JQ" -s --arg legacy "$LEGACY_RECORD_REPO" '
            map(select(.pr != null)
                | ((((.repo | strings) // "") | if . == "" then $legacy else . end) + "#" + (.pr|tostring)))' 2>"$ERR")"; then
        echo "::error::scan: parsing $2 failed — unparseable content: $(cat "$ERR")" >&2
        exit 1
    fi
    _LEGACY_DEFAULTED="$(printf '%s' "$1" | "$DEVFLOW_JQ" -s '[.[] | select(.pr != null) | select((((.repo | strings) // "")) == "")] | length' 2>/dev/null)" || _LEGACY_DEFAULTED=0
    if [ "${_LEGACY_DEFAULTED:-0}" -gt 0 ]; then
        echo "::warning::scan: ${_LEGACY_DEFAULTED} retrospectives.jsonl record(s) name no repository; binding them to '${LEGACY_RECORD_REPO}' for this scan; the next merge of new records gives them this run's repository." >&2
    fi
    if [ "$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" 'length')" -eq 0 ]; then
        echo "::error::scan: $2 yielded zero pr records (empty, truncated, pr-less or schema-drifted content) — refusing to treat the backlog as unprocessed (would re-queue everything and create duplicate retrospectives)" >&2
        exit 1
    fi
}

EXISTING='[]'
ERR="$(mktemp)"
trap 'rm -f "$ERR"' EXIT
# Relative to the repository root, where the skill's fences run.
PROCESSED_FILE=".prflow/learnings/retrospectives.jsonl"
HYDRATE_OUT=".prflow/tmp/retro-helper/learnings-hydrate-out.txt"
if [ ! -e "$PROCESSED_FILE" ]; then
    # Absence means "nothing processed" only after a successful hydrate, which removes
    # every store file the store lacks; otherwise it is unknown.
    _HYDRATED=""
    { IFS= read -r _HYDRATED < "$HYDRATE_OUT"; } 2>/dev/null || true
    case "$_HYDRATED" in
        hydrated:*|first-run:*) echo "scan: no ${PROCESSED_FILE}; the learnings store holds none (${_HYDRATED%%:*})" >&2 ;;
        *) echo "::error::scan: no ${PROCESSED_FILE} and ${HYDRATE_OUT} reports no loaded store (${_HYDRATED:-missing or unreadable}) — run retro-helper.sh learnings-hydrate first" >&2
           exit 1 ;;
    esac
elif ! PROCESSED_TEXT="$(cat "$PROCESSED_FILE" 2>"$ERR")"; then
    echo "::error::scan: could not read ${PROCESSED_FILE}: $(cat "$ERR")" >&2
    exit 1
else
    _decode_existing "$PROCESSED_TEXT" "$PROCESSED_FILE"
fi

# Route EXISTING (the full processed-PR set — genuinely monotonically corpus-growing)
# through --slurpfile: as an --argjson argv slot it overflows the kernel arg limit at
# scale (jq: "Argument list too long", issue #783). --slurpfile wraps in a one-element
# array, so the reference dereferences $e[0].
_e_file="$(mktemp)"
printf '%s' "$EXISTING" > "$_e_file"
# Clean up on the jq-abort path too: under `set -e` a nonzero jq (or the piped read)
# would skip the trailing `rm -f` and orphan the temp. The localized `|| { rm; exit 1; }`
# cleans then re-raises with the same rc the surrounding code uses on error (line above),
# rather than a `trap` that would clobber the active ERR EXIT trap set earlier.
UNPROC="$(echo "$CANDIDATES" | "$DEVFLOW_JQ" --slurpfile e "$_e_file" --arg repo "$REPO" '[.[] | select(($repo + "#" + (.number|tostring)) as $k | ($e[0] | index($k) | not))] | sort_by(.mergedAt)')" \
  || { rm -f "$_e_file"; exit 1; }
rm -f "$_e_file"
N="$(echo "$UNPROC" | "$DEVFLOW_JQ" 'length')"
if [ "$N" -gt "$MAX_PRS" ]; then
    echo "scan: $N unprocessed PRs, capping to $MAX_PRS" >&2
fi
echo "$UNPROC" | "$DEVFLOW_JQ" -c --argjson cap "$MAX_PRS" --arg repo "$REPO" '[.[0:$cap][] | {number, headRefName, mergedAt, repo: $repo, pr_key: ($repo + "#" + (.number|tostring))}]'  # argjson-ok: cap -- scalar int

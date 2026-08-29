#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# select-findings.sh — the owner of WHICH Stage B findings become filings for one
# pattern ON THE FINDINGS-ARRAY PATH (issue #893). The scope matters: the legacy
# `{title, body}` coexistence path never reaches this helper — the orchestrator
# files that shape under the bare category key and derives its own cap verdict — so
# this is not the sole cap decision in the run, only the sole one for a findings
# array. Sourced into the retrospective orchestrator's shell; it
# composes and legality-checks each finding's filing key, collapses subslug churn
# onto an existing lifecycle record by a deterministic token-set alias, ranks tight
# clusters ahead of grab-bags (descending evidence-PR count), truncates to the top
# three, and asks the SHIPPED `devflow_filing_cap_verdict` (lib/filing-decisions.sh)
# for every cap decision rather than re-implementing one.
#
# Defines: devflow_projection_eligible_findings, devflow_select_findings
#
# Contract (mirrors lib/filing-decisions.sh's sourceable, fail-closed-but-loud shape):
#   - This file is SOURCED, so it sets NO shell options — a `set -euo pipefail` here
#     would leak into the orchestrator, aborting the whole run on a later benign
#     non-zero. Every function validates its own operands and RETURNS a value.
#   - devflow_select_findings calls `exit` on NO path: an `exit` in a sourced helper
#     terminates the orchestrator's shell mid-loop, after issues were already filed,
#     leaving no report and no blocker line. It only ever `return`s.
#   - On stdout it prints a JSON array of the findings to file, each shaped
#     {key, subslug, title, body, evidence_prs, rationale, category}, in the order
#     they should be filed (descending evidence-PR count). Report/breadcrumb lines
#     (dropped-illegal, truncated, withheld-by-cap, aliased) go to stderr with a
#     `select-findings:` prefix the orchestrator relays. The `empty` (a Stage B
#     result whose `findings` array has zero elements) and `malformed` (neither a
#     `findings` array nor a legacy `{title, body}` pair) report kinds are NOT
#     emitted by this helper — this function is never reached on either shape, since
#     the caller (Step 8c) branches on the overall result shape before calling in;
#     those two report lines are Step 8c's own.
#   - Prints NOTHING on stdout and RETURNS non-zero when lib/filing-decisions.sh
#     cannot be sourced (a missing cap owner withholds rather than files uncapped),
#     and when the overrides file is absent/unreadable/unmigrated (an unreadable
#     record set is not "no existing record" — treating it as such would open a
#     duplicate issue per run).

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

_SF_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Filter a Stage B findings array through the shared projection predicate. Invalid
# findings are omitted individually; the optional second path receives structured
# drop records for the orchestrator's durable run report.
devflow_projection_eligible_findings() {
    local findings_file="${1:-}" dropped_file="${2:-}" _out="[]" _dropped="[]" _f _subslug
    if [ -z "$findings_file" ] || [ ! -r "$findings_file" ] || \
       ! "$DEVFLOW_JQ" -e 'type == "array"' "$findings_file" >/dev/null 2>&1; then
        echo "::error::select-findings: projection input is absent, unreadable, or not an array — withholding every finding" >&2
        return 1
    fi
    if [ ! -r "$_SF_HERE/projection-gate.jq" ]; then
        echo "::error::select-findings: projection-gate.jq is unavailable — withholding every finding" >&2
        return 1
    fi
    while IFS= read -r _f; do
        if "$DEVFLOW_JQ" -e -f "$_SF_HERE/projection-gate.jq" <<<"$_f" >/dev/null 2>&1; then
            _out="$("$DEVFLOW_JQ" -c --argjson f "$_f" '. + [$f]' <<<"$_out")"
        else
            _subslug="$("$DEVFLOW_JQ" -r '.subslug // "(missing)"' <<<"$_f" 2>/dev/null || echo '(unreadable)')"
            echo "select-findings: finding '${_subslug}' omitted because its projection disposition is unusable (requires represented plus zero unmatched Desired Behavior statements)" >&2
            _dropped="$("$DEVFLOW_JQ" -c --arg subslug "$_subslug" '. + [{subslug:$subslug,reason:"projection-unusable"}]' <<<"$_dropped")"
        fi
    done < <("$DEVFLOW_JQ" -c '.[]' "$findings_file")
    [ -z "$dropped_file" ] || printf '%s' "$_dropped" > "$dropped_file" || return 1
    printf '%s\n' "$_out"
}

# Source the shipped cap owner. A missing owner must WITHHOLD (return non-zero),
# never file uncapped — so a failed source is a hard fail of the whole selection,
# not a degrade.
if ! . "$_SF_HERE/filing-decisions.sh" 2>/dev/null; then
    echo "::error::select-findings: could not source lib/filing-decisions.sh beside ${BASH_SOURCE[0]} — the cap owner is unavailable, so every finding is withheld this pattern (nothing filed uncapped)" >&2
    # Define a stub that always withholds, so a caller that sourced us despite the
    # failed cap-owner source still fails closed rather than calling an undefined
    # function.
    devflow_select_findings() {
        echo "::error::select-findings: refusing to select — lib/filing-decisions.sh was not sourced; every finding withheld" >&2
        return 1
    }
    return 0 2>/dev/null || true
fi

# The deterministic token-set signature used for the alias is lowercase, split on
# non-alphanumeric runs, drop empties, sort, de-duplicate — the stopword set is
# EMPTY, so no token is dropped before comparison. It is defined ONCE, as the
# `tokset` jq function inside the alias-lookup program below, and computed in jq
# (never tr/sed/cut — this value decides a filing selection, and CLAUDE.md bars
# deriving a selection value through a non-preflight PATH tool).
#
# It is applied to the SUBSLUG alone, never to the composed key. Both sides of the
# comparison share the category prefix, and `unique` collapses a subslug token the
# category already contributes — so a full-key signature makes subslug `gap-slow`
# collide with subslug `slow` under category `tooling-gap` (both reduce to the token
# set {gap, slow, tooling}) and silently merges two distinct sub-patterns onto one
# lifecycle record. The existing side's subslug is recovered by stripping the
# canonical `<category>-` prefix from its stored key; a key that does NOT carry that
# prefix (a bare-category legacy record) is not comparable by subslug and is never
# aliased onto by the prefix check. A digest-suffixed key (compose-filing-key.sh's
# truncation arm) DOES still carry the `<category>-` prefix for a short-enough
# category — it is excluded instead by the SEPARATE token-set inequality: its
# stripped remainder is a truncated-prefix-plus-digest, whose token set essentially
# never equals a real subslug's, so it is never aliased onto in practice though not
# by construction.
#
# `unique` also makes the signature a token SET, not a multiset: a subslug repeating
# a token (`slow-slow`) shares a signature with one carrying it once (`slow`). That
# is the intended collapse — subslug churn is exactly what the alias exists to
# absorb — and it is stated here so the set-vs-multiset semantics are not inferred.

# devflow_select_findings
#   --category <cat>            attribution category (slug grammar) for these findings
#   --findings-file <path>      JSON file: the Stage B result's `findings` array
#   --overrides <path>          overrides.json (alias lookup + per-category cap comparand)
#   --status <status>           the pattern's lifecycle status (regressed bypass)
#   --filed-this-run <n>        issues filed so far this run (across all patterns)
#   --max-per-run <n>           .prflow_retrospective.max_issues_per_run
#   --max-per-cat <n>           .prflow_retrospective.max_open_per_category
#   --max-open <n>              .prflow_retrospective.max_open_issues
#   --withheld-file <path>      optional: JSON array of {tag, cap}, one per cap withhold
#   --dropped-file <path>       optional: JSON array carrying one
#                               {category, total, kept, dropped} object when the
#                               top-three truncation dropped findings, else empty
#
# Emits the to-file findings array on stdout; report lines on stderr. Returns 0 on a
# clean selection (including an empty result), non-zero only on a withhold-everything
# condition (unreadable/unmigrated overrides, unusable operands).
devflow_select_findings() {
    local category="" findings_file="" overrides="" status="" \
          filed_this_run="" max_per_run="" max_per_cat="" max_open="" withheld_file="" \
          dropped_file=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --category)       category="$2";       shift 2 ;;
            --findings-file)  findings_file="$2";  shift 2 ;;
            --overrides)      overrides="$2";      shift 2 ;;
            --status)         status="$2";         shift 2 ;;
            --filed-this-run) filed_this_run="$2"; shift 2 ;;
            --max-per-run)    max_per_run="$2";    shift 2 ;;
            --max-per-cat)    max_per_cat="$2";    shift 2 ;;
            --max-open)       max_open="$2";       shift 2 ;;
            # Optional: a path this call writes a JSON array of {tag, cap} objects to,
            # one per finding a cap withheld — so the orchestrator can surface them in
            # the run report's "withheld by a filing cap" section (issue #788's
            # disclosure guarantee), not only in this helper's stderr breadcrumbs.
            --withheld-file)  withheld_file="$2";  shift 2 ;;
            # Optional: a path this call writes a JSON array to, holding one
            # {category, total, kept, dropped} object when the top-three truncation
            # dropped findings (else an empty array). The truncation notice is
            # otherwise stderr-only, and the orchestrator captures stdout — so
            # without this channel the "N dropped" count can never reach the run
            # report, leaving the >3-findings disclosure undischarged.
            --dropped-file)   dropped_file="$2";   shift 2 ;;
            *) echo "::error::select-findings: unknown argument '$1'" >&2; return 2 ;;
        esac
    done

    # ── Validate operands (withhold everything on any unusable one) ──────────────
    if [ -z "$category" ] || [ -z "$findings_file" ] || [ -z "$overrides" ]; then
        echo "::error::select-findings: missing required argument (--category='${category}' --findings-file='${findings_file}' --overrides='${overrides}') — withholding every finding for this pattern" >&2
        return 2
    fi
    # `filed_this_run` feeds `$(( filed_this_run + _filed_here ))` below; an empty or
    # unset value is silently coerced to 0 by bash arithmetic (unlike a non-numeric
    # string, which errors) — laundering an unestablished per-run count into a valid-
    # looking 0 before devflow_filing_cap_verdict ever sees it, resetting the per-run
    # cap comparand rather than reporting it unestablished. Validate it here, the same
    # way the other numeric cap operands are validated.
    case "$filed_this_run" in
        ''|*[!0-9]*)
            echo "::error::select-findings: --filed-this-run is not a non-negative integer (got '${filed_this_run}') — withholding every finding for this pattern rather than filing past the per-run cap on a laundered zero" >&2
            return 2 ;;
    esac
    if [ ! -r "$findings_file" ]; then
        echo "::error::select-findings: findings file '${findings_file}' is unreadable — withholding every finding for this pattern" >&2
        return 2
    fi

    # ── Overrides gate: absent/unreadable/unmigrated → withhold, coin no key ─────
    # An unreadable record set is NOT "no existing record"; treating it as such would
    # skip the alias lookup and open a duplicate issue per run. `// 1` mirrors the
    # migrator's own read so an absent version reads as v1 (a refused version).
    if [ ! -f "$overrides" ] || [ ! -r "$overrides" ] || [ ! -s "$overrides" ]; then
        echo "::error::select-findings: overrides file '${overrides}' is absent, unreadable, or empty — withholding every finding for this pattern (an unreadable record set is not 'no existing record')" >&2
        return 1
    fi
    local _ov_schema
    _ov_schema="$("$DEVFLOW_JQ" -r '.schema_version // 1' "$overrides" 2>/dev/null)" || _ov_schema=""
    if [ "$_ov_schema" != "4" ]; then
        echo "::error::select-findings: overrides file '${overrides}' reports schema_version '${_ov_schema:-unreadable}', not 4 (the version the lifecycle writer refuses to stamp) — withholding every finding for this pattern" >&2
        return 1
    fi

    # ── Canonical category prefix for the subslug-recovery half of the alias ─────
    # Derived through the SAME shared slugify module compose-filing-key.sh uses, so
    # the prefix this strips is byte-identical to the one the composer wrote and the
    # two cannot drift. It decides a filing SELECTION, so an unestablished value
    # withholds rather than silently disabling every alias (which would open a
    # duplicate issue per run — the exact failure the alias exists to prevent).
    local _cat_canon
    _cat_canon="$("$DEVFLOW_JQ" -r -n -L "$_SF_HERE" --arg c "$category" 'include "slugify"; $c | slug_kebab' 2>/dev/null)" || _cat_canon=""
    if [ -z "$_cat_canon" ]; then
        echo "::error::select-findings: could not canonicalize the category '${category}' through lib/slugify.jq — the alias lookup's category prefix is unestablished, so every finding is withheld for this pattern rather than filed past a record it should have aliased onto" >&2
        return 1
    fi

    # ── Rank by DESCENDING evidence-PR count, then truncate to the top three ─────
    # This is the single ordering in force: Stage B's dominant-first order is
    # advisory; the truncation and the caps consume THIS order. A malformed findings
    # value (non-array) yields an empty ranked list here — the caller decides the
    # malformed-vs-empty distinction before calling us (it passes an array).
    local _ranked _n_total _n_kept
    _ranked="$("$DEVFLOW_JQ" -c '
        (. // []) | (arrays // [])
        | [ .[] | (objects // empty) ]
        | sort_by( -( (.evidence_prs | arrays // []) | length ) )' "$findings_file" 2>/dev/null)" \
      || { echo "::error::select-findings: could not read the findings array from '${findings_file}' (jq exited non-zero) — withholding every finding for this pattern" >&2; return 1; }
    _n_total="$("$DEVFLOW_JQ" 'length' <<<"$_ranked" 2>/dev/null)" || _n_total=0
    local _dropped="[]"
    if [ "${_n_total:-0}" -gt 3 ]; then
        echo "select-findings: pattern category '${category}' returned ${_n_total} findings — keeping the top 3 by evidence-PR count and dropping $(( _n_total - 3 ))" >&2
        # Publish the drop to the structured channel too — stderr alone never reaches
        # the run report (the orchestrator captures stdout).
        _dropped="$("$DEVFLOW_JQ" -nc --arg cat "$category" \
            --argjson total "$_n_total" --argjson dropped "$(( _n_total - 3 ))" \
            '[{category:$cat, total:$total, kept:3, dropped:$dropped}]')"
        _ranked="$("$DEVFLOW_JQ" -c '.[0:3]' <<<"$_ranked")"
    fi
    if [ -n "$dropped_file" ]; then
        printf '%s' "$_dropped" > "$dropped_file" 2>/dev/null \
          || echo "::warning::select-findings: could not write the dropped-findings file '${dropped_file}' — the truncation count for '${category}' will be absent from the report (it is still named on stderr)" >&2
    fi
    _n_kept="$("$DEVFLOW_JQ" 'length' <<<"$_ranked" 2>/dev/null)" || _n_kept=0

    # ── Per-category comparand (issue #891): summed across every record whose stored
    # `category` equals this category, so the cap bounds a whole category rather than
    # degenerating into a per-sub-pattern cap once each finding holds its own record.
    local _base_per_cat _base_open
    _base_per_cat="$(devflow_open_filed_for_category "$overrides" "$category")"
    _base_open="$(devflow_open_filed_total "$overrides")"
    # Both helpers fail CLOSED by printing NOTHING (never `0`) on a malformed record
    # set. An empty comparand in the `$(( ... ))` arithmetic below would silently
    # coerce to 0 — laundering an unknown count into an empty backlog and filing past
    # the caps. Unknown is not zero (CLAUDE.md): withhold every finding instead.
    case "$_base_per_cat" in ''|*[!0-9]*)
        echo "::error::select-findings: the per-category open-filed comparand for '${category}' is unestablished (got '${_base_per_cat}') — withholding every finding for this pattern rather than filing past the cap on a laundered zero" >&2
        return 1 ;;
    esac
    case "$_base_open" in ''|*[!0-9]*)
        echo "::error::select-findings: the open-filed total comparand is unestablished (got '${_base_open}') — withholding every finding for this pattern rather than filing past the cap on a laundered zero" >&2
        return 1 ;;
    esac

    # ── Walk the ranked findings, composing/aliasing/legality-checking each key and
    # asking the cap owner per finding. `_filed_here` is the running count of issues
    # THIS call has decided to file, so the per-run / per-category / open-total
    # comparands grow as findings are accepted (matching what Step 8c will do).
    local _out="[]" _withheld="[]" _filed_here=0 i=0
    while [ "$i" -lt "$_n_kept" ]; do
        local _f _subslug _title _body _rationale _evidence
        _f="$("$DEVFLOW_JQ" -c ".[$i]" <<<"$_ranked")"
        _subslug="$("$DEVFLOW_JQ" -r '.subslug // "" | if type=="string" then . else "" end' <<<"$_f" 2>/dev/null)" || _subslug=""

        # Drop a finding whose subslug is absent/empty — a legacy title/body result
        # (absent subslug) is handled by the CALLER, which passes it as a bare
        # category filing; a findings-array element with no subslug is a real drop.
        if [ -z "$_subslug" ]; then
            echo "select-findings: dropped a finding of category '${category}' with an absent or empty subslug (title: $("$DEVFLOW_JQ" -r '.title // "(none)"' <<<"$_f" 2>/dev/null))" >&2
            i=$(( i + 1 )); continue
        fi

        # An absent or empty title/body was previously defaulted to "" and filed
        # anyway: an empty title surfaces only as a misattributed "meta-issue.sh
        # failed" blocker downstream, and an empty body files a real GitHub issue
        # with no content — silently, since only subslug was validated. Drop it here
        # instead, with its own breadcrumb naming which field was missing.
        _title="$("$DEVFLOW_JQ" -r '.title // "" | if type=="string" then . else "" end' <<<"$_f" 2>/dev/null)" || _title=""
        _body="$("$DEVFLOW_JQ" -r '.body // "" | if type=="string" then . else "" end' <<<"$_f" 2>/dev/null)" || _body=""
        if [ -z "$_title" ] || [ -z "$_body" ]; then
            echo "select-findings: dropped a finding of category '${category}' subslug '${_subslug}' with an absent or empty title and/or body (title empty: $([ -z "$_title" ] && echo yes || echo no), body empty: $([ -z "$_body" ] && echo yes || echo no))" >&2
            i=$(( i + 1 )); continue
        fi

        # Compose the opaque filing key through the #891 composer. Precheck it is
        # present and executable BEFORE invoking it — the same discipline Step 8a
        # applies to run-jq.sh — so an absent helper, a lost +x bit, or a poisoned
        # deployment aborts with its own cause instead of being folded into the
        # "illegal subslug" breadcrumb below, which would misdiagnose an
        # infrastructure failure as a rejected input and silently drop every finding.
        if [ ! -x "$_SF_HERE/compose-filing-key.sh" ]; then
            echo "::error::select-findings: '$_SF_HERE/compose-filing-key.sh' is missing or not executable — the filing-key composer is unavailable; withholding every finding for this pattern rather than attributing the drop to a rejected input" >&2
            return 1
        fi
        local _key
        if ! _key="$("$_SF_HERE/compose-filing-key.sh" "$category" "$_subslug" 2>/dev/null)"; then
            echo "select-findings: dropped a finding of category '${category}' — compose-filing-key.sh rejected subslug '${_subslug}' (illegal or empties after canonicalization)" >&2
            i=$(( i + 1 )); continue
        fi
        # Legality: constrain the composed key to the meta-issue.sh grammar. A key
        # outside it exits the filing non-zero and makes the cooldown lookup silently
        # drop the issue — so drop it here with a breadcrumb.
        case "$_key" in
            ''|*[!A-Za-z0-9_-]*)
                echo "select-findings: dropped a finding of category '${category}' — composed key '${_key}' falls outside the [A-Za-z0-9_-]+ grammar" >&2
                i=$(( i + 1 )); continue ;;
        esac

        # Alias: collapse subslug churn onto an existing record of the SAME category
        # whose SUBSLUG yields an EQUAL token set. `tokset` is defined once here and
        # applied to BOTH sides in the same program, so the signature rule cannot
        # drift. The existing side's subslug is the stored key with its canonical
        # `<category>-` prefix stripped; a record whose key does not carry that prefix
        # is not comparable by subslug and is skipped rather than aliased onto.
        local _existing_key
        # Distinguish a jq EXECUTION ERROR from a clean empty match. `|| _existing_key=""`
        # alone reads a thrown/aborted query the same as "no existing record" — fail
        # OPEN exactly where the alias exists to prevent a duplicate: a churned
        # subslug would compose a fresh key and file a second issue instead of
        # aliasing onto the real one, on an already-parsed, schema-3-validated
        # overrides file where a throw should never happen but a coding error
        # upstream (or a future jq version's stricter typing) could still trigger
        # one. Withhold the finding on a jq failure, matching the sibling
        # `_cat_canon` derivation's `return 1` on the same class of failure.
        if ! _existing_key="$("$DEVFLOW_JQ" -r --arg cat "$category" --arg pre "$_cat_canon" --arg sub "$_subslug" '
            def tokset: ascii_downcase | [splits("[^a-z0-9]+")] | map(select(length>0)) | unique | join("-");
            ($pre + "-") as $prefix
            | ($sub | tokset) as $sig
            | [ (.patterns // {}) | to_entries[]
              | select((.value | objects) != null)
              | select((.value.category // "") == $cat)
              | select(.key | startswith($prefix))
              | select(((.key | ltrimstr($prefix)) | tokset) == $sig)
              | .key ] | .[0] // ""' "$overrides" 2>/dev/null)"; then
            echo "::error::select-findings: the alias-lookup query over '${overrides}' exited non-zero for subslug '${_subslug}' — the alias decision is unestablished, so every finding is withheld for this pattern rather than risking a duplicate issue past an unresolved alias" >&2
            return 1
        fi
        if [ -n "$_existing_key" ] && [ "$_existing_key" != "$_key" ]; then
            echo "select-findings: aliased finding subslug '${_subslug}' (key '${_key}') onto the existing lifecycle record '${_existing_key}' of category '${category}' — equal subslug token set, no second issue" >&2
            _key="$_existing_key"
        fi

        # Re-check the grammar on the FINAL key. The composed-key check above ran
        # BEFORE the alias overwrote `_key`, so an existing overrides record whose key
        # is illegal (hand-edited, or written by an older/looser writer) would
        # otherwise be emitted verbatim — and lib/meta-issue.sh refuses it downstream,
        # turning a silent alias into a failed filing. Drop it here, loudly.
        case "$_key" in
            ''|*[!A-Za-z0-9_-]*)
                echo "select-findings: dropped a finding of category '${category}' — the aliased existing record key '${_key}' falls outside the [A-Za-z0-9_-]+ grammar (the record set holds an illegal key; the finding is withheld rather than filed against it)" >&2
                i=$(( i + 1 )); continue ;;
        esac

        # A second finding within this same call that composes to (or aliases onto)
        # a key already accepted into `_out` — two subslugs canonicalizing to the
        # same key, or both aliasing onto the same existing record — would otherwise
        # be accepted twice, double-counting it in `_filed_here`/`filed_this_run` and
        # in `intervention_issues`. Drop the duplicate rather than filing it again.
        if "$DEVFLOW_JQ" -e --arg key "$_key" 'any(.[]; .key == $key)' <<<"$_out" >/dev/null 2>&1; then
            echo "select-findings: dropped a finding of category '${category}' subslug '${_subslug}' — key '${_key}' was already accepted earlier in this same selection (duplicate composed key or shared alias target)" >&2
            i=$(( i + 1 )); continue
        fi

        # Cap decision — from the SHIPPED owner, no cap arm of our own. The comparands
        # grow with _filed_here (issues this call already accepted).
        local _per_cat_now _open_now _verdict
        _per_cat_now=$(( _base_per_cat + _filed_here ))
        _open_now=$(( _base_open + _filed_here ))
        _verdict="$(devflow_filing_cap_verdict "$status" "$(( filed_this_run + _filed_here ))" "$max_per_run" "$_per_cat_now" "$max_per_cat" "$_open_now" "$max_open")"
        if [ "$_verdict" != "file" ]; then
            echo "select-findings: withheld finding '${_key}' (category '${category}') by cap '${_verdict}'" >&2
            # Record the withhold so the orchestrator can name it in the report's
            # "withheld by a filing cap" section — the same {tag, cap} shape the
            # legacy path appends (issue #788 disclosure guarantee).
            _withheld="$("$DEVFLOW_JQ" -c --arg tag "$_key" --arg cap "$_verdict" '. + [{tag:$tag,cap:$cap}]' <<<"$_withheld")"
            i=$(( i + 1 )); continue
        fi

        # Accepted — append the enriched finding, carrying the resolved key + category.
        _out="$("$DEVFLOW_JQ" -c --arg key "$_key" --arg cat "$category" --arg sub "$_subslug" --argjson f "$_f" '
            . + [ { key: $key, subslug: $sub, category: $cat,
                    title: ($f.title // ""), body: ($f.body // ""),
                    evidence_prs: ($f.evidence_prs // []), rationale: ($f.rationale // "") } ]' <<<"$_out")"
        _filed_here=$(( _filed_here + 1 ))
        i=$(( i + 1 ))
    done

    # Publish the cap-withheld findings for the report, when asked (best-effort: a
    # write failure never changes the filing decision already on stdout).
    if [ -n "$withheld_file" ]; then
        printf '%s' "$_withheld" > "$withheld_file" 2>/dev/null \
          || echo "::warning::select-findings: could not write the withheld-findings file '${withheld_file}' — cap-withheld findings for '${category}' will be absent from the report's withheld section (they are still named on stderr)" >&2
    fi

    printf '%s\n' "$_out"
    return 0
}

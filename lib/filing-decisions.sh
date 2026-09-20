#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# filing-decisions.sh — sourceable; the executable owner of the retrospective
# loop's per-run filing decisions and of the report fields those decisions feed
# (issue #788).
#
# Every decision here used to live as prose in skills/retrospective-weekly's
# Step 8c/9, where a mis-ordered cap check or a lost regressed bypass would ship
# green. CLAUDE.md's convention is explicit that a branch-selecting decision left
# inline in a non-testable surface "is a feature the suite cannot catch
# defeated", so the decisions live here and the skill calls them.
#
# Defines:
#   devflow_filing_cap_verdict  — which cap (if any) withholds one pattern
#   devflow_liveness_warning    — the `liveness:` line actionable-patterns.sh
#                                 wrote to stderr, for the report's liveness line
#   devflow_declined_refiled    — the filed slugs whose meta-issue was previously
#                                 closed NOT_PLANNED (a re-raised won't-fix)
#   devflow_annotate_patterns   — per-pattern filing_outcome / withheld_by on the
#                                 unfiltered view the report renders
#   devflow_open_filed_total    — the max_open_issues comparand
#   devflow_open_filed_in_category — the max_open_per_category comparand keyed by a
#                                 single record's KEY (retained; pre-#891 shape)
#   devflow_open_filed_for_category — the max_open_per_category comparand summed
#                                 across every record whose stored `category`
#                                 equals the requested category (issue #891)
#
# Pure: no gh calls, no file writes, no tree side effects. stdout carries the
# result; stderr carries breadcrumbs only (see the jq-stderr note below).
#
# This file is SOURCED into a caller's shell and therefore deliberately sets no
# shell options: a `set -euo pipefail` here would leak into the orchestrator that
# sources it, where a later benign non-zero (a grep that matches nothing, an
# unset optional variable) would abort the whole retrospective run. Every
# function below is written to be safe without it — each validates its own
# operands and returns a value rather than relying on `-e` to stop the caller.

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# devflow_filing_cap_verdict <status> <filed_this_run> <max_per_run> \
#                            <per_cat_count> <max_per_cat> <open_total> <max_open>
#
# Prints `file` when no cap withholds this pattern, else the name of the cap that
# withheld it (`max_issues_per_run` / `max_open_per_category` / `max_open_issues`).
# Always exits 0 — the verdict is the stdout token, so a caller never has to
# discriminate a withhold from a helper failure by exit status.
#
# Arm order is load-bearing and is asserted by the suite: per-run, then
# per-category, then the total-open cap. A `regressed` status bypasses
# `max_open_issues` only (a post-fix regression is the highest-value signal) and
# still honours the per-run and per-category caps.
#
# Fails CLOSED: any operand that is not a non-negative integer withholds under
# `invalid-operand` rather than filing on an unestablished count. A count that
# could not be derived is unknown, never zero — filing on it is the failure this
# guard exists to stop.
devflow_filing_cap_verdict() {
    # Every `invalid-operand` return withholds the pattern, and when the unusable
    # operand is a CONFIG cap it withholds every pattern for the whole run. The
    # two count helpers in this file (`devflow_open_filed_total` and
    # `devflow_open_filed_in_category`) breadcrumb their own unestablished counts; a cap
    # that arrives unusable from config had no such voice, so the run filed
    # nothing with no named cause — the reading ambiguity issue #788 exists to
    # remove. Name the operand on every arm.
    if [ "$#" -ne 7 ]; then
        echo "::error::filing-decisions: cap verdict called with $# operands, expected 7 — withholding this pattern as invalid-operand" >&2
        echo "invalid-operand" ; return 0
    fi
    local status="$1" filed_this_run="$2" max_per_run="$3" \
          per_cat_count="$4" max_per_cat="$5" open_total="$6" max_open="$7"
    local n label
    for label in filed_this_run max_issues_per_run per_category_count \
                 max_open_per_category open_total max_open_issues; do
        case "$label" in
            filed_this_run)        n="$filed_this_run" ;;
            max_issues_per_run)    n="$max_per_run" ;;
            per_category_count)    n="$per_cat_count" ;;
            max_open_per_category) n="$max_per_cat" ;;
            open_total)            n="$open_total" ;;
            max_open_issues)       n="$max_open" ;;
        esac
        case "$n" in
            ''|*[!0-9]*)
                echo "::error::filing-decisions: the '${label}' operand is not a non-negative integer (got '${n}') — withholding this pattern as invalid-operand. A malformed .prflow_retrospective cap key reaches here as a coerced string, so a config typo withholds EVERY pattern this run." >&2
                echo "invalid-operand" ; return 0 ;;
        esac
    done

    if [ "$filed_this_run" -ge "$max_per_run" ]; then
        echo "max_issues_per_run" ; return 0
    fi
    if [ "$per_cat_count" -ge "$max_per_cat" ]; then
        echo "max_open_per_category" ; return 0
    fi
    if [ "$status" != "regressed" ] && [ "$open_total" -ge "$max_open" ]; then
        echo "max_open_issues" ; return 0
    fi
    echo "file"
}

# devflow_liveness_warning <stderr-capture-file>
#
# Prints the human-readable body of the `liveness:` line actionable-patterns.sh
# wrote to stderr in Step 6, or nothing when the run emitted none. The report's
# liveness line (issue #788 AC) is rendered from this; without the capture the
# `::warning::` reaches the CI log but the report never names the count or the
# highest-occurrence slug.
#
# Parsed with bash builtins only — no tr/sed/wc/cut/head. This value reaches an
# emitted report line, and CLAUDE.md bars deriving such a value through a
# non-preflight PATH tool: a missing one would not fail, it would silently
# yield empty and drop the section. A missing or unreadable capture file prints
# nothing and exits 0 (the section is simply omitted).
devflow_liveness_warning() {
    local capture="${1:-}"
    # An absent/unreadable capture is not evidence that nothing is suppressed —
    # Step 6 may have aborted, or `.prflow/tmp/` may not have been creatable.
    # Same sentence devflow_declined_refiled uses for the same reason.
    if [ -z "$capture" ] || [ ! -r "$capture" ]; then
        echo "::warning::filing-decisions: the liveness capture '${capture}' is missing or unreadable — the report's liveness section will be omitted, which is NOT evidence that nothing is suppressed" >&2
        return 0
    fi
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            'liveness: '*) printf '%s\n' "${line#liveness: }" ; return 0 ;;
        esac
    done < "$capture"
    return 0
}

# devflow_declined_refiled <overrides-path> <filed-slugs-json>
#
# Prints a JSON array of the slugs filed this run whose lifecycle record already
# held a meta-issue entry closed NOT_PLANNED — a maintainer's won't-fix the
# lifecycle deliberately re-raises on recurrence (issue #788). The report names
# each one alongside the one durable off-switch, so the decision is re-raised
# visibly rather than silently overridden.
#
# DUPLICATE is excluded deliberately: it is also a `declined` transition, but a
# duplicate closure records no won't-fix judgement to re-raise.
#
# The overrides file must be read BEFORE the run's own filings are appended,
# otherwise the entry this run just wrote (state `filed`) is all that is seen.
# Prints `[]` on any unreadable/malformed input — the section is omitted rather
# than the run aborted.
devflow_declined_refiled() {
    local ov="${1:-}" filed_json="${2:-[]}"
    local _dr_out
    if [ -z "$ov" ] || [ ! -r "$ov" ]; then
        echo "::warning::filing-decisions: the overrides file '${ov}' is missing or unreadable — the report's won't-fix re-raise section will be omitted, which is NOT evidence that nothing was re-raised" >&2
        printf '[]\n' ; return 0
    fi
    # `.` inside the select() below is the SLUG STRING, not the document, so the
    # record lookup binds the root first. Without $root the lookup reads
    # `null.patterns`, every select() is false, and the section silently never
    # renders — the same dead-wiring failure this helper exists to close.
    # jq's own stderr is NOT captured or suppressed — it flows straight to the
    # caller's stderr, so its diagnostic survives without this helper writing a
    # temp file. That keeps the "no writes outside stdout" property above true.
    _dr_out="$("$DEVFLOW_JQ" -c --argjson filed "$filed_json" '
        . as $root
        | [ $filed[]
            | . as $slug
            | select(
                (($root.patterns // {})[$slug].meta_issues // [])
                | any(.state == "declined" and .state_reason == "NOT_PLANNED")
              )
          ]' "$ov")" || {
        # This section IS genuinely optional (a run that re-raised no won't-fix
        # pattern renders none), so a degrade to `[]` is the right shape here —
        # but it must not be SILENT: an empty section from a jq failure and one
        # from a genuinely empty result are indistinguishable to the reader, and
        # the won't-fix re-raise is precisely the decision this design promises to
        # surface rather than bury. Say why it is empty (jq's own message has
        # already reached stderr on its own).
        echo "::warning::filing-decisions: could not derive the won't-fix re-raise list from ${ov} — the report's re-raised section will be omitted, which is NOT evidence that nothing was re-raised" >&2
        printf '[]\n' ; return 0
    }
    printf '%s\n' "$_dr_out"
}

# devflow_annotate_patterns <patterns-full-json-file> <filed-json> <withheld-json>
#
# Prints the unfiltered pattern view with each pattern carrying its filing
# outcome for this run and, where a cap withheld it, that cap (issue #788).
# render-report.sh reads `.filing_outcome` and `.withheld_by` per pattern; the
# `--full` view carries neither, so without this join those two reads render
# nothing on every pattern.
#
#   filed:    ["<slug>", ...]              — slugs an issue was filed for
#   withheld: [{"tag": "<slug>", "cap": "<cap>"}, ...]
#
# Every pattern carries an outcome (issue #788 AC): `issue filed`, `not filed`,
# or — for a withheld one — `withheld_by` alone, because the renderer already
# prints "withheld by `<cap>`" from that field and a `filing_outcome` of
# "withheld" beside it would render the word twice on the same line.
#
# FAILS LOUD, and prints NOTHING on failure — deliberately unlike
# `devflow_declined_refiled` above. That section is optional; this one is not.
# The pattern view is the report's substance, and Step 9 guards it with
# `: "${PATTERNS_JSON:?…}"`, which tests for the EMPTY STRING. A degrade to `[]`
# would sail straight through that guard, `render-report.sh` would compute
# `patterns_n = 0`, and the section would be omitted entirely — a producer
# failure rendered as a genuinely quiet week, which is the exact misreading this
# whole issue exists to eliminate. Printing nothing makes the caller's `:?` fire.
devflow_annotate_patterns() {
    local patterns_file="${1:-}" filed_json="${2:-[]}" withheld_json="${3:-[]}"
    local _ap_out
    if [ -z "$patterns_file" ] || [ ! -r "$patterns_file" ]; then
        echo "::error::filing-decisions: the pattern view '${patterns_file}' is missing or unreadable — printing nothing so the caller's guard aborts the run rather than rendering an empty pattern section as a quiet week" >&2
        return 1
    fi
    # jq's stderr flows through to the caller (see the sibling note above).
    _ap_out="$("$DEVFLOW_JQ" -c \
      --argjson filed "$filed_json" \
      --argjson withheld "$withheld_json" '
        ($withheld | map({key: (.tag // .slug // ""), value: (.cap // "")}) | from_entries) as $wmap
        | map(
            . as $p
            | ($p.tag // $p.slug // "") as $k
            | $p
            + (if ($filed | index($k)) then {filing_outcome: "issue filed"}
               elif ($wmap[$k] // "") != "" then {withheld_by: $wmap[$k]}
               else {filing_outcome: "not filed"} end)
          )' "$patterns_file")" || {
        echo "::error::filing-decisions: could not annotate the pattern view from ${patterns_file} — printing nothing so the caller's guard aborts the run rather than rendering an empty pattern section as a quiet week" >&2
        return 1
    }
    printf '%s\n' "$_ap_out"
}

# devflow_open_filed_total <overrides-path>
# devflow_open_filed_in_category <overrides-path> <slug>
#
# The two comparands `devflow_filing_cap_verdict` reads: the count of `filed`
# meta-issue entries across every lifecycle record (the `max_open_issues`
# comparand), and the count within one record (the `max_open_per_category`
# comparand). Both are derived from the lifecycle state, never from a label
# query — a closed-but-still-labelled issue must not consume a cap slot.
#
# These live here rather than as inline jq in the skill for the same reason the
# cap arms do: a mis-shaped count decides whether an issue is filed, and inline
# jq in a prose surface is a decision the suite cannot catch defeated.
#
# Fails CLOSED by printing NOTHING (not `0`) on a missing, unreadable, or
# malformed overrides file, and on any jq failure. An unestablished count is
# unknown, never zero: `devflow_filing_cap_verdict` rejects the empty operand as
# `invalid-operand` and withholds, whereas a laundered `0` would report an empty
# backlog and file right past both caps.
devflow_open_filed_total() {
    local ov="${1:-}"
    # Fail CLOSED by printing nothing — but never SILENTLY. An empty comparand
    # makes devflow_filing_cap_verdict return `invalid-operand`, which withholds
    # EVERY pattern for the whole run. "The loop filed nothing this week" then
    # reads identically to "there was nothing to file" — the exact failure mode
    # issue #788 exists to eliminate — unless something names the cause. jq's own
    # stderr is left unsuppressed so the underlying error reaches the log too.
    if [ -z "$ov" ] || [ ! -r "$ov" ]; then
        echo "::error::filing-decisions: overrides file '${ov}' is missing or unreadable — the max_open_issues comparand is UNESTABLISHED, so every pattern will be withheld as invalid-operand this run" >&2
        return 0
    fi
    # Every malformed SHAPE must reach the fail-closed arm below, not be filtered
    # away. `objects`/`arrays` DISCARD a wrong-typed value and let `length` return
    # a real 0 — and 0 is a usable count that satisfies the caller's numeric guard,
    # reports an empty backlog, and files right past BOTH caps. That is the
    # unknown-laundered-as-zero failure this helper exists to prevent, so a
    # wrong-typed map, record or entry list is an `error` (jq exits non-zero, the
    # helper prints nothing) rather than a skip.
    "$DEVFLOW_JQ" -r '
        if (.patterns // {} | type) != "object" then error("patterns is not an object") else . end
        | [ (.patterns // {}) | to_entries[]
            | (if (.value | type) != "object" then error("record \(.key) is not an object") else .value end)
            | (if (.meta_issues // [] | type) != "array" then error("meta_issues is not an array") else (.meta_issues // []) end)
            | .[]
            | (if type != "object" then error("a meta_issues entry is not an object") else . end)
            | select(.state == "filed") ] | length
      ' "$ov" || {
        echo "::error::filing-decisions: could not derive the open-filed total from ${ov} — the max_open_issues comparand is UNESTABLISHED, so every pattern will be withheld as invalid-operand this run" >&2
        return 0
    }
}

devflow_open_filed_in_category() {
    local ov="${1:-}" slug="${2:-}"
    # Same fail-closed-but-loud contract as devflow_open_filed_total above.
    if [ -z "$ov" ] || [ ! -r "$ov" ] || [ -z "$slug" ]; then
        echo "::error::filing-decisions: cannot derive the per-category open-filed count (overrides='${ov}', slug='${slug}') — the max_open_per_category comparand is UNESTABLISHED, so this pattern will be withheld as invalid-operand" >&2
        return 0
    fi
    # Same total-FAIL (not total-filter) discipline as devflow_open_filed_total.
    # A missing record is a legitimate 0 (this category has filed nothing); a
    # PRESENT but wrong-shaped one is unknown and must fail closed.
    "$DEVFLOW_JQ" -r --arg s "$slug" '
        if (.patterns // {} | type) != "object" then error("patterns is not an object") else . end
        | ((.patterns // {})[$s]) as $rec
        | if $rec == null then 0
          else
            (if ($rec | type) != "object" then error("record \($s) is not an object") else . end)
            | (if ($rec.meta_issues // [] | type) != "array" then error("meta_issues of \($s) is not an array") else ($rec.meta_issues // []) end)
            | [ .[] | (if type != "object" then error("a meta_issues entry is not an object") else . end)
                | select(.state == "filed") ] | length
          end
      ' "$ov" || {
        echo "::error::filing-decisions: could not derive the per-category open-filed count for '${slug}' from ${ov} — the max_open_per_category comparand is UNESTABLISHED, so this pattern will be withheld as invalid-operand" >&2
        return 0
    }
}

# devflow_open_filed_for_category <overrides-path> <category>
#
# The max_open_per_category comparand under the opaque-key model (issue #891): the
# count of `filed` meta-issue entries summed across EVERY lifecycle record whose
# stored `category` equals the requested category — not one record keyed by the
# category, because a category can now be spread across several sub-pattern records
# under distinct opaque keys. Same fail-closed-but-loud contract as
# devflow_open_filed_total: prints NOTHING (not `0`) on a missing/unreadable/malformed
# overrides file or any jq failure, so devflow_filing_cap_verdict rejects the empty
# operand as `invalid-operand` and withholds rather than filing past the cap on a
# laundered zero.
#
# Deliberately WIDER fail-closed blast radius than devflow_open_filed_in_category:
# because the sum walks every record rather than one, the shape validation walks
# every record too — a wrong-shaped record belonging to an UNRELATED category makes
# the requested category's comparand UNESTABLISHED. That is chosen on purpose: a
# partially-readable map cannot support a trustworthy count, and an under-count
# (skipping the wrong-shaped record) would file straight past the cap.
devflow_open_filed_for_category() {
    local ov="${1:-}" category="${2:-}"
    if [ -z "$ov" ] || [ ! -r "$ov" ] || [ -z "$category" ]; then
        echo "::error::filing-decisions: cannot derive the per-category open-filed count (overrides='${ov}', category='${category}') — the max_open_per_category comparand is UNESTABLISHED, so this pattern will be withheld as invalid-operand" >&2
        return 0
    fi
    # Walk EVERY record: assert each is an object, its meta_issues an array, and each
    # entry an object — erroring (jq exits non-zero, the helper prints nothing) on
    # any wrong shape, whether or not that record belongs to the requested category.
    # Then keep only records whose stored `category` equals the requested one and
    # count their `filed` entries.
    "$DEVFLOW_JQ" -r --arg cat "$category" '
        if (.patterns // {} | type) != "object" then error("patterns is not an object") else . end
        | [ (.patterns // {}) | to_entries[]
            | (if (.value | type) != "object" then error("record \(.key) is not an object") else . end)
            | .key as $k | .value as $rec
            | (if ($rec.meta_issues // [] | type) != "array" then error("meta_issues of \($k) is not an array") else (.value.meta_issues // []) end)
            | [ .[] | (if type != "object" then error("a meta_issues entry is not an object") else . end) ] as $entries
            # The stored `category` must be a STRING on EVERY record, not merely on
            # the ones that match. An absent or non-string category would otherwise
            # slip past the select below and silently LOWER the sum — an under-count
            # that files straight past the cap, the exact fail-open this helper
            # widens its blast radius to prevent (issue #891 review).
            | (if ($rec.category | type) != "string" then error("category of \($k) is not a string") else . end)
            | select($rec.category == $cat)
            | $entries[]
            | select(.state == "filed") ] | length
      ' "$ov" || {
        echo "::error::filing-decisions: could not derive the per-category open-filed count for category '${category}' from ${ov} — the max_open_per_category comparand is UNESTABLISHED, so this pattern will be withheld as invalid-operand" >&2
        return 0
    }
}

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# render-report.sh — sourceable; defines devflow_render_report <summary-json>
# Prints a markdown run-report to stdout. Pure function — no gh/git calls.
set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# _rr_emit <section-label> <jq-program>
# Render a section's rows from $summary_json, NAMING any jq failure instead of
# swallowing it. A blanket `|| true` on the element read turns an abort INSIDE a
# well-formed object element — a string `occurrence_count` aborting `sort_by`, a
# non-string `.summary` aborting `gsub` — into a silent empty section under a
# heading that has already printed. That is the same quiet-report-reads-as-quiet
# -week ambiguity the malformed-key guards exist to remove, one level down, and
# the key-level `::warning::` cannot fire for it because the key IS an array.
_rr_emit() {
    local label="$1" prog="$2" rows
    if rows="$(printf '%s' "$summary_json" | "$DEVFLOW_JQ" -r "$prog" 2>&1)"; then
        [ -z "$rows" ] || printf '%s\n' "$rows"
    else
        echo "::error::render-report: the ${label} rows could not be rendered (${rows}) — that section is INCOMPLETE, which is NOT evidence that it was empty" >&2
    fi
}

devflow_render_report() {
    local summary_json="$1"

    # Guard against malformed summary JSON before attempting any field extraction.
    "$DEVFLOW_JQ" empty <<<"$summary_json" \
      || { echo "::error::render-report: summary JSON is malformed" >&2; return 1; }

    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    local prs_scanned clean_count analyzed_count
    prs_scanned="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.prs_scanned // 0')"
    clean_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.clean_count // 0')"
    analyzed_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.analyzed_count // 0')"

    printf '<!-- prflow:audit-report -->\n'
    printf '# DevFlow Weekly Report\n\n'
    printf '**Run finished:** %s\n\n' "$ts"

    local skipped_count
    skipped_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.skipped_count // 0')"

    printf '## Summary\n\n'
    printf 'PRs scanned: %s\n' "$prs_scanned"
    printf 'clean (no analysis): %s\n' "$clean_count"
    printf 'analyzed: %s\n' "$analyzed_count"
    printf 'skipped: %s\n' "$skipped_count"

    # Skips (issue #626) — every skip class writes a one-line record so no skip is
    # ever silent: the mechanical no-provenance pre-dispatch skip, the Stage A
    # Cancelled skip, and the Stage A interim skip. Omitted when nothing was skipped.
    local skips_n
    # Count ONLY an actual array; every other shape emits nothing, which the
    # numeric case below degrades to 0 so the section is merely omitted.
    #
    # Why the type test and not a bare `length`: jq's `length` errors on a
    # BOOLEAN only. A string, a number and an object all return a count
    # (`"oops"|length` -> 4, `{"a":1}|length` -> 1, `5|length` -> 5), so a
    # `length`-plus-numeric-case guard waves those three shapes through as a
    # positive count. The section heading is then printed and the ELEMENT read
    # below is what aborts — truncating the report mid-render, after the heading,
    # and taking every later section with it under this file's `set -e`. The
    # element reads are separately made total (`map(select(type == "object"))`)
    # and non-aborting (`|| true`) for the same reason.
    skips_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.skips // [] | type) == "array" then (.skips // [] | length) else empty end' 2>/dev/null || true)"
    case "$skips_n" in ''|*[!0-9]*) skips_n=0 ;; esac
    if [ "$skips_n" -gt 0 ]; then
        printf '\n### Skipped PRs (mechanical no-provenance / Cancelled / interim)\n\n'
        _rr_emit skips '(.skips // [])[] | "- " + (. | tostring | gsub("\n";" "))'
    fi

    # Analyzed PRs — one line each (omitted when the caller did not pass `analyzed`)
    local analyzed_n
    # Type-tested for the reason `skips_n` documents above: `// []` does not
    # replace a truthy non-array key, and `length` counts a string/number/object
    # rather than erroring, so only an array is counted here and the element read
    # below is made total and non-aborting.
    analyzed_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.analyzed // [] | type) == "array" then (.analyzed // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    case "$analyzed_n" in ''|*[!0-9]*) analyzed_n=0 ;; esac
    if [ "$analyzed_n" -gt 0 ]; then
        printf '\n### Analyzed PRs\n\n'
        _rr_emit analyzed '
            (.analyzed // [] | map(select(type == "object")))[]
            | "- #\(.pr // "?") — \(.verdict // "?"): " +
              (((.summary | strings) // "") | gsub("\n";" ") | if length > 220 then .[0:217] + "…" else . end)'
    fi

    # Patterns — the UNFILTERED view (issue #788): the orchestrator passes the whole
    # pattern picture (every lifecycle state — filed/fixed/declined/regressed/open,
    # plus dismissed and below-threshold), each carrying its filing outcome for this
    # run and, where it was withheld, the cap that withheld it. Omitted when the
    # caller did not pass `patterns`.
    local patterns_n
    # Type-tested for the reason `skips_n` documents above: `// []` does not
    # replace a truthy non-array key, and `length` counts a string/number/object
    # rather than erroring, so only an array is counted here and the element read
    # below is made total and non-aborting.
    patterns_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.patterns // [] | type) == "array" then (.patterns // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    # Unlike the optional sections, degrading THIS key to 0 must not be silent.
    # `.patterns` is the report's substance, and the upstream producer
    # (`devflow_annotate_patterns`) fails loud precisely so a producer failure
    # cannot render as a quiet week — but its protection is the caller's
    # `: "${PATTERNS_JSON:?…}"`, which tests for the EMPTY STRING and therefore
    # cannot see a non-empty malformed value that reaches this renderer. Without
    # a breadcrumb here, a truthy non-array `.patterns` yields a report whose
    # pattern section is simply absent — indistinguishable from a week with no
    # patterns. Say so.
    case "$patterns_n" in
        ''|*[!0-9]*)
            echo "::warning::render-report: the summary's \`patterns\` key is malformed (not an array) — the 'Patterns this run' section is OMITTED, which is NOT evidence that there were no patterns" >&2
            patterns_n=0 ;;
    esac
    if [ "$patterns_n" -gt 0 ]; then
        printf '\n## Patterns this run\n\n'
        _rr_emit patterns '
            (.patterns // [] | map(select(type == "object")))
            | sort_by(-((.occurrence_count | numbers) // 0))[]
            | . as $p
            | ((($p.tag // $p.slug // "") | strings) // "") as $key
            | (($p.category | strings) // "") as $cat
            | "- `\($p.tag // $p.slug // "(unnamed)")` — \(($p.occurrence_count | numbers) // 0)× (status: \(($p.status | strings) // "open"))"
              + (if $cat != "" and $cat != $key then " (category: `\($cat)`)" else "" end)
              + (if (($p.filing_outcome | strings) // "") != "" then " — \($p.filing_outcome)" else "" end)
              + (if (($p.withheld_by | strings) // "") != "" then " — withheld by `\($p.withheld_by)`" else "" end)
              + (if ($p.cooldown_active // false) then " — cooldown, skipped this run" else "" end)'
    fi

    # Regressed patterns (issue #894) — every pattern whose derived status is
    # `regressed`, derived from the SAME `.patterns` summary key the section above
    # reads (no new summary key, no new producer). `regressed` is a CUMULATIVE
    # state (a standing `newest occurrence > last fix` comparison over the whole
    # history), NOT a this-run event, so the heading deliberately carries no
    # "this run" time claim — unlike the run-scoped won't-fix re-raise section. An
    # old-shaped summary whose pre-existing `.patterns` carries a regressed entry
    # therefore renders this section too — the one pre-existing-shape summary that
    # also surfaces a section gated on a newer status.
    # Omitted when no pattern is regressed.
    local regressed_n
    # Same type-test + numeric-degrade guard the sections above use; the element
    # read is `map(select(...))`-filtered and `|| true`-ed so one malformed element
    # cannot abort after the heading printed.
    regressed_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.patterns // [] | type) == "array" then (.patterns // [] | map(select(type == "object" and ((.status | strings) // "") == "regressed")) | length) else empty end' 2>/dev/null || true)"
    case "$regressed_n" in ''|*[!0-9]*) regressed_n=0 ;; esac
    if [ "$regressed_n" -gt 0 ]; then
        printf '\n## Regressed patterns\n\n'
        printf 'These recurred after their last fix. `regressed` is a **cumulative** state — a standing `newest occurrence > last fix` comparison over the whole history, not a this-run event — so a pattern that regressed long ago and has not recurred since still appears here.\n\n'
        # The `.category` field is guarded through `(($p.category | strings) // "")`
        # exactly as the pattern-row emitter above does. Rows are distinguished by
        # their `tag`/`slug` key, which the row always PRINTS — falling back to
        # `(unnamed)` for the malformed entry that carries neither, which is why the
        # two-level fallback below is not dead code. The `(category: …)` clause is
        # purely additive attribution (issue #891) and is SUPPRESSED when the entry's
        # category equals its key, so it is not what makes two same-category records
        # distinguishable.
        _rr_emit regressed '
            (.patterns // [] | map(select(type == "object" and ((.status | strings) // "") == "regressed")))[]
            | . as $p
            | ((($p.tag // $p.slug // "") | strings) // "") as $key
            | (($p.category | strings) // "") as $cat
            | "- `\($p.tag // $p.slug // "(unnamed)")` — \(($p.occurrence_count | numbers) // 0)×"
              + (if $cat != "" and $cat != $key then " (category: `\($cat)`)" else "" end)'
    fi

    # Filing queue (issue #894) — an aggregate `filing queue: N/M open` line where N
    # is the count of open filed meta-issue entries (from devflow_open_filed_total,
    # computed in Step 9 and passed in — never recomputed here) and M is the
    # resolved max_open_issues. Both arrive as `--arg` STRINGS so an unestablished
    # value is representable as the empty string (rendered `unavailable`, never `0`).
    # The line reports STATE, not blame: it deliberately does not say "blocked" and
    # does not read the `cap` token (devflow_filing_cap_verdict is first-match, so a
    # token-keyed line would go silent in the compound case). For an OBJECT summary it
    # renders whenever the summary carries AT LEAST ONE of the two operand keys —
    # which every run of the changed orchestrator does — and is omitted when it
    # carries NEITHER (the pre-change summary shape), so an old-shaped summary renders
    # without this line. It is unconditional on any current run: not gated on withheld_patterns,
    # not on N>=M. A valid-JSON NON-object summary (`has()` is undefined there) takes
    # the same degrade-to-omitted path as any other probe failure below, rather than
    # aborting the render.
    local has_queue
    # Same `2>/dev/null || true` + closed-set degrade guard every sibling probe in
    # this function carries. Without it a non-zero jq — a non-object summary, where
    # `has()` errors — would abort the whole render MID-REPORT under this file's
    # `set -euo pipefail`, silently dropping every section below this point from an
    # otherwise well-formed-looking report. The type test keeps `has()` from being
    # reached on a non-object at all; the guard is the belt to that braces.
    has_queue="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (type == "object") and (has("filing_queue_open") or has("filing_queue_max")) then "yes" else "no" end' 2>/dev/null || true)"
    case "$has_queue" in yes) ;; *) has_queue=no ;; esac
    if [ "$has_queue" = yes ]; then
        local q_open q_max n_disp m_disp cap_suffix
        # `// ""` maps an absent key (the exactly-one-present case) to the empty
        # string, which renders `unavailable` — the same rendering an established-
        # but-empty (unestablished) value gets, and the same rendering the
        # `2>/dev/null || true` degrade below produces when the probe itself fails.
        q_open="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.filing_queue_open // ""' 2>/dev/null || true)"
        q_max="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.filing_queue_max // ""' 2>/dev/null || true)"
        # An established count is a CANONICAL run of digits; anything else (the empty
        # string) is unestablished and renders `unavailable`. An established 0 renders
        # `0`. The extra `0?*` arm rejects a LEADING-ZERO all-digit value (`08`,
        # reachable from a hand-written `"max_open_issues": "08"` through
        # config-get.sh's verbatim string coercion) while still admitting a bare `0`:
        # `test` evaluates numeric operands under shell arithmetic, which reads `08`
        # as an illegal octal literal, so `[ "$q_open" -ge "$q_max" ]` would write
        # `value too great for base` to stderr and return non-true — silently
        # SUPPRESSING ` — at capacity` on a queue that is at capacity. This is the
        # same shape devflow_validate_audit_bundle_cap refuses with its own arm.
        # The comparison uses bash builtins only (guard-class 2) — no tr/sed/wc.
        case "$q_open" in ''|*[!0-9]*|0?*) n_disp=unavailable ;; *) n_disp="$q_open" ;; esac
        case "$q_max"  in ''|*[!0-9]*|0?*) m_disp=unavailable ;; *) m_disp="$q_max"  ;; esac
        cap_suffix=""
        # The ` — at capacity` suffix fires when, and only when, BOTH operands are
        # established and N >= M. An unestablished operand yields no suffix.
        if [ "$n_disp" != unavailable ] && [ "$m_disp" != unavailable ] && [ "$q_open" -ge "$q_max" ]; then
            cap_suffix=" — at capacity"
        fi
        printf '\n## Filing queue\n\n'
        printf -- '- filing queue: %s/%s open%s\n' "$n_disp" "$m_disp" "$cap_suffix"
        # `max_open_issues` is not an absolute ceiling: lib/filing-decisions.sh lets a
        # `regressed` pattern bypass it, so a run CAN file while at capacity. Say so,
        # or a reader takes ` — at capacity` as "nothing was filed".
        # An `if`, not a `[ … ] && printf` AND-list: under this file's `set -e` the
        # false branch of such a list is a non-zero command in statement position and
        # would abort the render mid-report.
        if [ -n "$cap_suffix" ]; then
            printf -- '- `max_open_issues` is not absolute — a `regressed` pattern bypasses this ceiling, so a run can file while at capacity.\n'
        fi
    fi

    # Liveness (issue #788) — when actionable-patterns.sh emitted a `liveness:` line
    # (no pattern eligible while a suppressed pattern has occurred at/above threshold), the
    # orchestrator carries it into the summary so the report surfaces the silent
    # exhaustion rather than reading like a genuinely quiet week.
    local liveness
    liveness="$(echo "$summary_json" | "$DEVFLOW_JQ" -r '.liveness_warning // ""')"
    if [ -n "$liveness" ]; then
        printf '\n## Liveness warning\n\n'
        printf -- '- %s\n' "$liveness"
    fi

    # Withheld by a filing cap (issue #788) — every pattern the back-pressure caps
    # held back this run, named with the cap that withheld it.
    local withheld_n
    # Same type-test + numeric-degrade guard `skips_n` documents above. The
    # element read is `map(select(type == "object"))`-filtered and `|| true`-ed
    # too: a well-formed array carrying ONE malformed element would otherwise
    # abort `.tag`/`.cap` after the heading was already printed.
    withheld_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.withheld_patterns // [] | type) == "array" then (.withheld_patterns // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    case "$withheld_n" in ''|*[!0-9]*) withheld_n=0 ;; esac
    if [ "$withheld_n" -gt 0 ]; then
        printf '\n## Patterns withheld by a filing cap\n\n'
        _rr_emit withheld_patterns '(.withheld_patterns // [] | map(select(type == "object")))[] | "- `\(.tag // .slug // "(unnamed)")` — withheld by `\((.cap | strings) // "(unknown cap)")`"'
    fi

    # Truncated Stage B evidence (issue #894) — every pattern where Stage B was
    # delivered fewer occurrence bundles than the pattern has occurrences, because
    # `audit_bundle_cap` dropped older ones (and/or a fetch failed). Each entry
    # carries the pattern tag, `delivered`, and `total`; when `delivered < selected`
    # the gap is named separately, because that gap is evidence lost to a FETCH
    # FAILURE rather than to the cap, and collapsing the two would restate the
    # evidence overstatement this issue exists to remove. Omitted when no pattern
    # was truncated. Same type-test + element-filter guards as the sections above.
    local truncated_n
    truncated_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.truncations // [] | type) == "array" then (.truncations // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    case "$truncated_n" in ''|*[!0-9]*) truncated_n=0 ;; esac
    if [ "$truncated_n" -gt 0 ]; then
        printf '\n## Stage B evidence truncated by the audit bundle cap\n\n'
        printf 'For these patterns Stage B read fewer occurrence bundles than the pattern has occurrences. The subagent'"'"'s bundle set is a most-recent-first subset; the pattern metadata'"'"'s `occurrences[]` remains the authoritative full list.\n\n'
        _rr_emit truncations '
            (.truncations // [] | map(select(type == "object")))[]
            | ((.delivered | numbers) // 0) as $delivered
            | ((.total | numbers) // 0) as $total
            | ((.selected | numbers) // 0) as $selected
            | "- `\(.tag // "(unnamed)")` — Stage B received \($delivered) of \($total) occurrence bundles"
              + (if $delivered < $selected then " (\($selected - $delivered) selected bundle(s) failed to fetch)" else "" end)'
    fi

    # Won't-fix re-raised (issue #788) — patterns re-filed this run whose meta-issue
    # was previously closed NOT_PLANNED. The lifecycle deliberately re-raises a
    # recurring won't-fix; name each one and the one durable off-switch (a human
    # `dismissed{}` entry) so the maintainer's decision is re-raised visibly.
    local declined_refiled_n
    # Type-tested for the reason `skips_n`/`withheld_n` document above.
    declined_refiled_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.declined_refiled // [] | type) == "array" then (.declined_refiled // [] | length) else empty end' 2>/dev/null || true)"
    case "$declined_refiled_n" in ''|*[!0-9]*) declined_refiled_n=0 ;; esac
    if [ "$declined_refiled_n" -gt 0 ]; then
        printf '\n## Won'"'"'t-fix patterns re-raised this run\n\n'
        printf 'These recurred after being closed not-planned. To stop one permanently, add a human `dismissed{}` entry to `.prflow/learnings/overrides.json`.\n\n'
        _rr_emit declined_refiled '(.declined_refiled // [])[] | "- `\(. | tostring)`"'
    fi

    # Recurring intervention targets (issue #520) — report-only: the files/areas
    # the accumulated retrospectives.jsonl repeatedly points at, ranked by
    # distinct-PR count. Files no issue and writes no dismissal state, so it
    # surfaces recurring targets regardless of overrides.json dismissal. Omitted
    # when no target reaches >= 2 distinct PRs (the helper emits [] then), mirroring
    # the optional-section idiom above.
    local recurring_n
    # Type-tested for the reason `skips_n` documents above: `// []` does not
    # replace a truthy non-array key, and `length` counts a string/number/object
    # rather than erroring, so only an array is counted here and the element read
    # below is made total and non-aborting.
    recurring_n="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.recurring_targets // [] | type) == "array" then (.recurring_targets // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    case "$recurring_n" in ''|*[!0-9]*) recurring_n=0 ;; esac
    if [ "$recurring_n" -gt 0 ]; then
        printf '\n## Recurring intervention targets\n\n'
        # recurring-targets.jq already emits this order; the sort mirrors its
        # canonical key so render-report stays self-contained (like the patterns
        # section) and never depends on the caller pre-sorting the array.
        _rr_emit recurring_targets '
            (.recurring_targets // [] | map(select(type == "object")))
            | sort_by([-((.pr_count | numbers) // 0), ((.target | strings) // "")])[]
            | "- `\(.target)` — \(.pr_count // 0) PRs (\((.prs // []) | map("#\(.)") | join(", "))): "
              + (((.representative_summary | strings) // "") | gsub("\n";" ") | if length > 220 then .[0:217] + "…" else . end)'
    fi

    # Issues filed — one per actionable pattern (the loop proposes, not disposes:
    # each pattern becomes a GitHub issue for the normal implement -> review pipeline)
    printf '\n## Issues filed\n\n'
    local issues_count
    issues_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.intervention_issues // [] | type) == "array" then (.intervention_issues // [] | map(select(type == "object")) | length) else empty end' 2>/dev/null || true)"
    # `_None filed._` is a POSITIVE assertion of fact, so it must never be printed
    # off an unestablished count. A malformed `intervention_issues` degraded to 0
    # would have the report affirmatively deny filings that did happen — strictly
    # worse than the ambiguous omitted-section case the other guards accept.
    case "$issues_count" in
        ''|*[!0-9]*)
            echo "::error::render-report: the summary's \`intervention_issues\` key is malformed (not an array) — refusing to print '_None filed._', which would be a false claim that nothing was filed" >&2
            printf '_Filing record unavailable — see the error above; this is NOT a claim that nothing was filed._\n'
            issues_count=-1 ;;
    esac
    if [ "$issues_count" -eq 0 ]; then
        printf '_None filed._\n'
    elif [ "$issues_count" -gt 0 ]; then
        # Name each filed issue by its filing KEY and its CATEGORY (issue #893): a
        # finding now files under an opaque `<category>-<subslug>` key, so the bare
        # `tag` alone no longer tells the maintainer which category it bounds. Both
        # producers (the findings-array path and the legacy bare-category path) now
        # emit `.key` on every entry; `// .tag` is defensive against an
        # externally-authored or historical entry shape that predates this
        # convention, not a live producer arm.
        _rr_emit intervention_issues '(.intervention_issues // [] | map(select(type == "object")))[]
            | "- `\(.key // .tag // "(unnamed)")`"
              + (((.category | strings) // "") | if . != "" then " (category: `\(.)`)" else "" end)
              + " — \(.url // "(no url)")"'
    fi

    # Cooldown-skipped patterns (omit section if empty)
    local cooldown_count
    cooldown_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.cooldown_skipped // [] | type) == "array" then (.cooldown_skipped // [] | length) else empty end' 2>/dev/null || true)"
    case "$cooldown_count" in ''|*[!0-9]*) cooldown_count=0 ;; esac
    if [ "$cooldown_count" -gt 0 ]; then
        printf '\n## Cooldown-skipped patterns\n\n'
        _rr_emit cooldown_skipped '(.cooldown_skipped // [])[] | "- `\(. | tostring)`"'
    fi

    # Blockers (omit section if empty)
    local blocker_count
    blocker_count="$(echo "$summary_json" | "$DEVFLOW_JQ" -r 'if (.blockers // [] | type) == "array" then (.blockers // [] | length) else empty end' 2>/dev/null || true)"
    # Like `patterns` above, this one must not degrade silently: `.blockers` is the
    # section that REPORTS failures, and failures being suppressed by a failure is
    # the worst possible pairing.
    case "$blocker_count" in
        ''|*[!0-9]*)
            echo "::warning::render-report: the summary's \`blockers\` key is malformed (not an array) — the blockers section is OMITTED, which is NOT evidence that there were no blockers" >&2
            blocker_count=0 ;;
    esac
    if [ "$blocker_count" -gt 0 ]; then
        printf '\n## Blockers\n\n'
        _rr_emit blockers '(.blockers // [])[] | "- \(. | tostring)"'
    fi
}

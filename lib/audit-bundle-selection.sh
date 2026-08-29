#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# audit-bundle-selection.sh — sourceable; the executable owner of the Stage B
# occurrence-bundle cap validation, the most-recent-N selection, and the
# no-dispatch floor (issue #894).
#
# The retrospective loop's Step 8a used to fetch a context bundle for EVERY
# occurrence PR of every actionable pattern, unbounded — a cost proportional to
# each pattern's cumulative occurrence history, growing monotonically with the
# corpus. This helper bounds that fetch: the skill fence resolves
# `.prflow_retrospective.audit_bundle_cap` (via config-get.sh, with the default
# 10), passes the resolved value to `devflow_validate_audit_bundle_cap`, then asks
# `devflow_select_audit_bundles` for the most-recent-N occurrence PRs, and finally
# asks `devflow_audit_dispatch_ok` whether the bundles that actually arrived are
# enough to dispatch that pattern to Stage B at all.
#
# The validation, the selection and the dispatch floor live here rather than inline
# in the SKILL.md fence for the same reason lib/filing-decisions.sh exists: a
# mis-shaped cap, a wrong-order selection, or a missed no-evidence floor decides
# which evidence Stage B sees — and whether an evidence-free issue is filed at all —
# and CLAUDE.md's convention bars leaving a branch-selecting decision inline in a
# non-testable prose surface, "a feature the suite cannot catch defeated". The suite
# drives every function here directly.
#
# Config-read boundary: this helper reads NO config — the skill fence resolves the
# cap through config-get.sh and passes it in. The reason is position, not a blanket
# rule: it is sourced at Step 8a, UPSTREAM of the entire filing loop, so a
# `set -euo pipefail` leaked in from lib/config-source.sh would abort the run at
# any later benign non-zero. This mirrors lib/filing-decisions.sh, which reads no
# config either.
#
# This file is SOURCED into the caller's shell and therefore deliberately sets no
# shell options: a `set -euo pipefail` here would leak into the orchestrator that
# sources it, where a later benign non-zero would abort the whole retrospective
# run. Every function validates its own operands and returns a value.

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e. Matches the siblings
# lib/render-report.sh and lib/filing-decisions.sh (a `lib/` helper resolves jq
# through this resolver and invokes "$DEVFLOW_JQ", never the agent-tier
# run-jq.sh wrapper, which would fork a process per call).
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# devflow_validate_audit_bundle_cap <coerced-config-value>
#
# Prints the validated positive-integer cap on stdout (exit 0), or fails CLOSED
# with a targeted `::error::` and a non-zero exit. The input is the string
# config-get.sh coerced from whatever JSON the key held; config-get.sh already
# resolves an absent file / absent key / JSON null / empty string / empty array to
# the default 10, so a well-formed config never reaches here empty.
#
# Boundary (matches the composed config-get.sh boundary the sibling filing caps
# exhibit, per shape):
#   - a positive integer                 -> printed and used as the cap
#   - an EMPTY value                      -> the read FAILED (malformed config or a
#                                            resolver failure) -> abort, naming both
#                                            reachable causes (they are not
#                                            distinguishable from the empty value)
#   - `0` (or an all-zeros value)         -> abort with the STARVATION message,
#                                            naming the key (unlike the filing caps
#                                            where 0 is a real off-switch — a bundle
#                                            cap of zero would starve Stage B)
#   - a leading-zero all-digit value
#     (`08`, `007`)                       -> abort naming the key: it is a legal JSON
#                                            string but not a canonical integer, and
#                                            jq's `--argjson` treatment of it is
#                                            implementation-dependent, so it is
#                                            refused rather than laundered
#   - a NEGATIVE value, boolean false/true,
#     an object, a multi-element array, a
#     non-numeric string, 3.5             -> abort naming the key with the GENERIC
#                                            positive-integer message (the residual
#                                            arm — a negative reaches this arm, not
#                                            the starvation arm, because `-` is a
#                                            non-digit character)
#
# RESIDUAL (pinned, not fixed — config-get.sh's coercion is repo-wide and the sibling
# filing caps exhibit it identically): a SINGLE-element array such as `[3]` is
# comma-joined by config-get.sh to the bare string `3`, so it arrives here
# indistinguishable from a real scalar `3` and is accepted as that cap.
devflow_validate_audit_bundle_cap() {
    local cap="${1:-}"
    if [ -z "$cap" ]; then
        echo "::error::audit-bundle-selection: the audit_bundle_cap read produced an empty value — this means either a malformed .prflow/config.json (its embedded python exits non-zero and config-get.sh's file-scope set -euo pipefail aborts the assignment before the default fallback) or a resolver failure (python3 absent, config-get.sh missing or non-executable). Refusing to launder either into a working cap of 10." >&2
        return 1
    fi
    # Any value carrying a non-digit character reaches the residual arm: a boolean
    # `false`/`true`, a coerced object `[object Object]`, a comma-joined
    # multi-element array, a non-integer number `3.5`, a negative `-1`, or a
    # non-numeric string. NOT closed over every accepted shape: a single-element
    # array is comma-joined to a bare all-digit scalar upstream and so never reaches
    # here as an array (the pinned residual named in the header).
    case "$cap" in
        *[!0-9]*)
            echo "::error::audit-bundle-selection: .prflow_retrospective.audit_bundle_cap must be a positive integer (got '$cap')" >&2
            return 1 ;;
    esac
    # All-digit now (0, 00, 08, 007, or a canonical positive). Reject a LEADING-ZERO
    # value that is not all zeros, BEFORE the `-le 0` test — for two independent
    # reasons. (1) It is not a canonical JSON integer literal, so handing it to
    # `--argjson` downstream is implementation-dependent: jq 1.7 coerces `08` to 8
    # while a strict JSON parser rejects it outright. (2) The `-le 0` test could not
    # safely judge it anyway: `test`/`[` evaluates numeric operands under shell
    # arithmetic rules, which read a leading-zero literal as OCTAL — `007` is 7 in
    # either base, but `08` is not a legal octal literal and `[ 08 -le 0 ]` fails
    # with `value too great for base`. So this arm must stay ABOVE that test; a
    # maintainer who reorders the two gets a hard `test` error, not a fallthrough.
    # Refusing here also stops a config-shape defect from surfacing downstream as an
    # empty selection the caller reads as "this pattern has no occurrences". An
    # ALL-zeros value (`0`, `00`) is excluded from this arm and falls through to the
    # starvation arm below, which names the real reason (all-zeros is a legal octal
    # literal, so that test is safe on it).
    case "$cap" in
        0*[1-9]*)
            echo "::error::audit-bundle-selection: .prflow_retrospective.audit_bundle_cap must be a positive integer with no leading zero — '$cap' is not a canonical JSON integer literal, so its numeric meaning downstream is parser-dependent; write the intended count without leading zeros" >&2
            return 1 ;;
    esac
    # Canonical all-digit now (all-zeros, or a leading-zero-free positive). Reject
    # zero and — via the same guard — a value that is only zeros.
    if [ "$cap" -le 0 ]; then
        echo "::error::audit-bundle-selection: .prflow_retrospective.audit_bundle_cap must be a positive integer, not zero — a bundle cap of zero would starve Stage B of all evidence (got '$cap')" >&2
        return 1
    fi
    printf '%s\n' "$cap"
}

# devflow_select_audit_bundles <cap> <pattern-json>
#
# Prints, one per line, the canonical `<owner>/<name>#<number>` key of the
# MOST-RECENT <cap> occurrences of the pattern, in DESCENDING occurrence-timestamp
# order. The key is repository-qualified because a pattern can span repositories:
# a bare number would fetch a same-numbered PR from whichever repository the run
# is in, which is different work. lib/compute-patterns.jq emits
# `occurrences` through `sort_by(.ts)` (ASCENDING), so the selection is the tail of
# that array reversed to descending `ts`. Emitting the order — not just the set —
# is load-bearing: Step 8a fetches in this order and the dispatch prompt states it
# to the Stage B subagent as fact.
#
# When the pattern has <= cap occurrences, every occurrence is selected (still
# reversed to descending ts). An absent/empty occurrences array selects nothing.
#
# Failure is SIGNALLED, never conflated with an empty selection. Empty stdout is a
# legitimate return here (a pattern with no occurrences), so a silent failure would
# be indistinguishable from it — and the caller converts an empty selection into a
# blocker blaming `gh`, misdiagnosing a config- or corpus-shape defect as a network
# failure. So, like devflow_validate_audit_bundle_cap and every sibling in
# lib/filing-decisions.sh, this function fails CLOSED with a targeted `::error::` and
# a non-zero return on: an empty <pattern>, a <cap> that is not a canonical positive
# integer (the caller must pass the VALIDATED cap, not the raw config value), a
# non-object <pattern>, a present-but-non-array `occurrences`, or any other jq
# failure. Callers check the exit status; only a zero exit means the printed lines
# are the whole selection.
#
# An occurrence naming NO repository fails the whole selection CLOSED rather than
# defaulting to the current repository — an unqualified number is an unestablished
# operand, and Stage B evidence fetched from the wrong repository is worse than none.
#
# Occurrence elements that are not objects, or whose `.pr` is not a number, are
# dropped BEFORE the most-recent-N slice — so a malformed element neither reaches the
# caller as a phantom `pr-null` path nor consumes a cap slot that would otherwise hold
# a real fetchable occurrence.
devflow_select_audit_bundles() {
    local cap="${1:-}" pattern="${2:-}" out
    if [ -z "$pattern" ]; then
        echo "::error::audit-bundle-selection: devflow_select_audit_bundles received an EMPTY pattern JSON — refusing to return an empty selection the caller would read as 'this pattern has no occurrences'" >&2
        return 1
    fi
    # A canonical positive integer never begins with `0`, so the single `0*` arm
    # rejects EVERY leading-zero shape at once — `0`, the all-zeros `00`/`000`, and
    # the leading-zero-positive `08`/`007`. An enumeration that spelled these out
    # separately (`0*[1-9]*|0`) silently admitted the all-zeros shapes, which then
    # reached `--argjson` and were stopped by jq's parse error under the GENERIC
    # "could not select occurrence PRs" breadcrumb instead of this attributed one.
    case "$cap" in
        ''|*[!0-9]*|0*)
            echo "::error::audit-bundle-selection: devflow_select_audit_bundles received a non-canonical cap '$cap' — it must be the positive integer devflow_validate_audit_bundle_cap printed, not the raw config value" >&2
            return 1 ;;
    esac
    if ! out="$(printf '%s' "$pattern" | "$DEVFLOW_JQ" -r --argjson cap "$cap" '
        (if (type != "object")
         then error("pattern is not a JSON object (got \(type))")
         elif (has("occurrences") and (.occurrences != null) and ((.occurrences | type) != "array"))
         then error("occurrences is not an array (got \(.occurrences | type))")
         else . end)
        | (.occurrences // [])
        | map(select(type == "object" and ((.pr | numbers) != null)))
        | (map(select(((.repo | strings) // "") == "")) | length) as $unqualified
        | (if $unqualified > 0
           then error("\($unqualified) occurrence(s) name no repository — a bare PR number cannot be fetched without one")
           else . end)
        | . as $o
        | ($o | length) as $len
        | (if $cap >= $len then 0 else $len - $cap end) as $start
        | $o[$start:]
        | reverse
        | .[] | (.pr_key // (.repo + "#" + (.pr|tostring)))' 2>&1)"; then
        echo "::error::audit-bundle-selection: devflow_select_audit_bundles could not select occurrence PRs — ${out:-jq produced no diagnostic}. Refusing to return an empty selection the caller would read as 'this pattern has no occurrences'" >&2
        return 1
    fi
    # `2>&1` above merges jq's stderr into the capture so the FAILURE arm can quote a
    # diagnostic. On a ZERO-exit run any warning jq wrote is in `$out` too, and would
    # flow into the caller's `for n in $SELECTED_PRS` as a bogus PR number — a
    # phantom `pr-<warning-word>.context.json` fetch. So validate the success-path
    # output: every non-empty line must be a bare PR number, and anything else fails
    # CLOSED with its own attributed breadcrumb rather than reaching the caller.
    # Builtin-only (guard-class 2) — no tr/sed/grep decides this selection.
    local line _l_repo _l_num
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        # Every line must be a canonical "<owner>/<name>#<number>" key. Split with
        # builtins and validate both halves: a jq warning that reached stdout on a
        # zero exit would otherwise flow into the caller as a phantom occurrence.
        _l_repo="${line%#*}"; _l_num="${line##*#}"
        case "$line" in *"#"*) : ;; *) _l_repo=""; _l_num="" ;; esac
        case "$_l_num" in ''|*[!0-9]*) _l_repo="" ;; esac
        case "$_l_repo" in
            ''|*/*/*|/*|*/) _l_repo="" ;;
            */*) : ;;
            *) _l_repo="" ;;
        esac
        if [ -z "$_l_repo" ]; then
            echo "::error::audit-bundle-selection: devflow_select_audit_bundles produced a line that is not a canonical <owner>/<name>#<number> key ('$line') — refusing to hand the caller a phantom occurrence PR" >&2
            return 1
        fi
    done <<< "$out"
    # Empty stdout is the legitimate no-occurrences return; print nothing rather than
    # a blank line, and return 0 explicitly (a bare `[ -n … ] &&` would return 1 here).
    [ -n "$out" ] && printf '%s\n' "$out"
    return 0
}

# devflow_audit_dispatch_ok <delivered>
#
# The executable carrier of the Stage B no-dispatch floor (issue #894). Returns 0
# when the pattern has at least one DELIVERED occurrence bundle and may therefore be
# dispatched to Stage B and filed; returns 1 when it must be excluded from the 8b/8c
# set. Fails CLOSED (return 1, `::error::`) on an unestablished operand — an empty or
# non-numeric `delivered` is not evidence that evidence exists.
#
# This exists as a function rather than an inline `[ "$delivered" -eq 0 ]` because the
# floor is the load-bearing safety property of the whole change: it is what stops an
# evidence-free GitHub issue being filed from metadata alone. A branch whose stated
# effect lives only in a comment has no owner the suite can drive, and CLAUDE.md's
# convention bars leaving such a decision inline in a non-testable prose surface.
devflow_audit_dispatch_ok() {
    local delivered="${1:-}"
    case "$delivered" in
        ''|*[!0-9]*)
            echo "::error::audit-bundle-selection: devflow_audit_dispatch_ok received a non-count delivered value ('$delivered') — refusing to treat an unestablished bundle count as evidence that Stage B has any evidence" >&2
            return 1 ;;
    esac
    [ "$delivered" -gt 0 ]
}

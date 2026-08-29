#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# pattern-state.sh — the retrospective loop's lifecycle reconciler for
# .prflow/learnings/overrides.json.
#
# It owns two operations against the overrides file:
#   migrate    — bring the overrides file up to schema_version:4 in place. A v1
#                file is first converted to v2, converting ONLY the loop's own
#                `dismissed{}` entries (dismissed_by == "retrospective-weekly")
#                into machine-owned `patterns{}` lifecycle records and preserving
#                every hand-written `dismissed{}` entry verbatim; then (issue #891)
#                each lifecycle record is stamped with an explicit `category`
#                field — its existing valid `category` when present, else its own
#                key canonicalized through `slugify` — and the version moved to 3;
#                finally every meta-issue entry is stamped with the `repo` its
#                number was issued in and the version moved to 4. A v2 file runs
#                the v3 + v4 stamps, a v3 file the v4 stamp; a v4 file is a no-op.
#   reconcile  — for every meta-issue entry of every lifecycle record, resolve the
#                live GitHub issue state IN THE ENTRY'S OWN REPOSITORY (one
#                `--label Retrospective` prefetch per distinct repository plus a
#                per-number `gh issue view --repo` fallback) and apply the transition
#                table below, then derive each record's state from its entry set.
#                (Stated as a table, not as a count: an ordinal in a comment rots
#                on the next edit, and the last row applies NO transition.)
# `run` does migrate then reconcile (the SKILL's normal invocation).
#
# The v3 shape (issue #891 — the key is an OPAQUE filing key; the `category`
# field, not the key, names the fixed-vocabulary category the record belongs to):
#   {
#     "schema_version": 4,
#     "patterns": {                       # machine-owned lifecycle map
#       "<opaque-filing-key>": {
#         "category": "<category-slug>",  # attribution category (issue #891)
#         "state": "filed|fixed|declined",
#         "fixed_at": "<iso8601|null>",   # the fix/closure timestamp compute-patterns.jq reads
#         "provenance": "<iso8601|null>", # carried from the v1 dismissed_at
#         "meta_issues": [                # the SET of issues filed for this slug
#           {"number": <int>, "repo": "<owner>/<name>", "url": "<https url>",
#            "state": "filed|fixed|declined", "closedAt": "<iso8601|null>",
#            "state_reason": "<COMPLETED|NOT_PLANNED|DUPLICATE|null>"}
#         ]
#       }
#     },
#     "dismissed": { ... }                # human-owned; written by NO filing path
#   }
#
# Reconcile transitions (complete by construction over GitHub's closed-issue
# stateReason domain plus the open state), per entry:
#   state == OPEN                → filed,    fixed_at cleared (null)
#   stateReason == COMPLETED     → fixed,    fixed_at = closedAt
#   stateReason == NOT_PLANNED   → declined, fixed_at = closedAt
#   stateReason == DUPLICATE     → declined, fixed_at = closedAt
#   closed w/ no or unrecognized stateReason → no transition + ::warning::
#
# Record state derives from the entry set: `filed` when any entry is filed;
# otherwise the state of the entry with the newest closedAt; record.fixed_at is
# that entry's fixed_at.
#
# Usage:
#   pattern-state.sh {migrate|reconcile|run} <overrides-path> [--limit N]
#
# Environment:
#   DEVFLOW_GH  override the gh binary (test stubbing). When unset/empty it is
#               resolved (execution-verified) via lib/resolve-gh.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# jq binary: resolved once via the sourced sibling resolver (issue #247).
# shellcheck source=resolve-jq.sh
. "$HERE/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched. resolve-gh.sh
# always returns rc 0, so this cannot abort under set -e.
# shellcheck source=resolve-gh.sh
. "$HERE/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# Repository identity: every meta-issue entry names the repository its number was
# issued in, and reconcile resolves each entry against THAT repository.
# shellcheck source=repo-identity.sh
. "$HERE/repo-identity.sh"

# The loop's own dismissed-entry writer marker — the migration converts only these.
_LOOP_WRITER="retrospective-weekly"

_usage() {
    echo "usage: pattern-state.sh {migrate|reconcile|run} <overrides-path> [--limit N]" >&2
    exit 2
}

# ── the directory holding a path, via bash builtins ───────────────────────────
# Coupled pair: lib/meta-issue.sh writes the SAME overrides.json and carries the
# same two-line derivation inline. It is a standalone executable, so it cannot
# source this one (that would run this script's arg parsing) — the duplication is
# deliberate, not an oversight. Change the staging rule in both or neither.
# Never `dirname`: `lib/preflight.sh` does not guarantee it, and a missing
# non-preflight PATH tool does not fail — it yields empty, which would silently
# relocate every staging file below to the filesystem root.
_dir_of() {  # $1 = path
    local d="${1%/*}"
    [ "$d" = "$1" ] && d="."
    printf '%s' "$d"
}

# ── atomic write helper: write $2 (a file) over $1, mktemp-then-mv ─────────────
# On any failure emit an ::error:: naming the path and exit non-zero, leaving the
# previous file byte-unchanged.
_atomic_write() {  # $1 = dest path, $2 = source tmp holding new content
    local dest="$1" src="$2"
    local final
    # The staging file lives BESIDE the destination, never under $TMPDIR: `mv`
    # is an atomic rename only within one filesystem. On a runner where /tmp is
    # a separate filesystem (common in CI/cloud), a $TMPDIR staging file makes
    # the `mv` a copy-then-unlink that writes straight into the destination, so
    # a mid-copy failure (the disk-full case) leaves the previous file
    # TRUNCATED — exactly the "byte-unchanged on a failed write" guarantee this
    # helper exists to provide. A same-directory rename cannot half-apply.
    final="$(mktemp "$(_dir_of "$dest")/.overrides.XXXXXX")" \
      || { echo "::error::pattern-state: could not create a temp file beside ${dest}" >&2; return 1; }
    if ! cat "$src" > "$final"; then
        rm -f "$final"
        echo "::error::pattern-state: failed to stage the new contents for ${dest}" >&2
        return 1
    fi
    if ! mv "$final" "$dest"; then
        rm -f "$final"
        echo "::error::pattern-state: failed to write ${dest} (read-only filesystem, full disk, or bad path)" >&2
        return 1
    fi
    return 0
}

# ── migrate: schema_version 1 → 2, in place ───────────────────────────────────
# Idempotent: a v2 (or already-migrated) file is left byte-unchanged.
_migrate() {  # $1 = overrides path
    local ov="$1"
    # Absent or empty file: MATERIALIZE the v2 stub at the real path.
    #
    # This is load-bearing, not convenience. The filing caps read this exact path
    # and fail closed by printing nothing when it is missing — which
    # `devflow_filing_cap_verdict` reads as `invalid-operand` and withholds EVERY
    # pattern. Nothing else creates it first: `actionable-patterns.sh` stubs only
    # into its own temp dir, and `meta-issue.sh` writes the real stub but runs
    # only AFTER a `file` verdict. So on a fresh consumer repo (install.sh ships
    # no `learnings/`) the loop would withhold everything, never file, never
    # create the file, and repeat that forever — a permanent-silence mode in the
    # very change whose purpose is to end permanent silence. Creating it here
    # makes the comparands read a real `0`.
    if [ ! -f "$ov" ] || [ ! -s "$ov" ]; then
        local stub_dir
        stub_dir="$(_dir_of "$ov")"
        [ -d "$stub_dir" ] || mkdir -p "$stub_dir" \
          || { echo "::error::pattern-state: could not create ${stub_dir} for the first-run overrides stub" >&2; return 1; }
        printf '{"schema_version":4,"patterns":{},"dismissed":{}}\n' > "$ov" \
          || { echo "::error::pattern-state: could not write the first-run overrides stub at ${ov}" >&2; return 1; }
        return 0
    fi

    local ver
    ver="$("$DEVFLOW_JQ" -r '.schema_version // 1' "$ov" 2>/dev/null)" \
      || { echo "::error::pattern-state: ${ov} does not parse as JSON — migration aborted" >&2; return 1; }
    # Dispatch over the STORED version (issue #891): a v3 file is already current
    # (a second run over it changes no byte — the idempotency invariant); a v2 file
    # runs the v3 category stamp alone; a v1 file runs the existing v1-to-v2
    # conversion below and THEN the v3 stamp; any other/future version is left
    # unchanged.
    case "$ver" in
        4) return 0 ;;
        3) _stamp_v4 "$ov" || return 1 ; return 0 ;;
        2) _stamp_v3 "$ov" || return 1 ; _stamp_v4 "$ov" || return 1 ; return 0 ;;
        1) : ;;   # fall through to the v1-to-v2 conversion, then the v3 + v4 stamps below
        *) return 0 ;;
    esac

    local tmp
    # Staged beside the destination for the same reason _atomic_write is: the
    # whole write path stays on one filesystem, and none of it depends on
    # $TMPDIR being usable on the host.
    tmp="$(mktemp "$(_dir_of "$ov")/.overrides-mig.XXXXXX")" \
      || { echo "::error::pattern-state: could not create a temp file beside ${ov} during migration" >&2; return 1; }
    # Convert only loop-written dismissed entries into lifecycle records; keep
    # every hand-written entry verbatim in the v2 dismissed{} map.
    if ! "$DEVFLOW_JQ" --arg writer "$_LOOP_WRITER" '
        (.dismissed // {}) as $d
        | {
            schema_version: 2,
            patterns: (
              (($d | objects) // {}) | to_entries
              | map(select(((.value | type) == "object") and .value.dismissed_by == $writer))
              | map({
                  key: .key,
                  value: {
                    state: "filed",
                    fixed_at: null,
                    provenance: (.value.dismissed_at // null),
                    meta_issues: (
                      if (.value.meta_issue // "") != "" then
                        [{
                          number: ((.value.meta_issue | capture("/issues/(?<n>[0-9]+)")?) // {n:null} | .n | (if . == null then null else tonumber end)),
                          url: .value.meta_issue,
                          state: "filed",
                          closedAt: null
                        }]
                      else [] end
                    )
                  }
                })
              | from_entries
            ),
            dismissed: (
              # A non-object hand-written entry is PRESERVED verbatim here rather
              # than aborting: dismissed{} is by design human-owned and
              # hand-editable, so a wrong-shaped value is an input this parser
              # must survive under the adversarial-shape matrix, not a crash.
              # (No apostrophes in this comment: the whole jq program sits inside
              # bash single quotes, where one would terminate the string.)
              (($d | objects) // {}) | to_entries
              | map(select(((.value | type) != "object") or .value.dismissed_by != $writer))
              | from_entries
            )
          }' "$ov" > "$tmp"; then
        rm -f "$tmp"
        echo "::error::pattern-state: migration jq transform failed for ${ov}" >&2
        return 1
    fi
    _atomic_write "$ov" "$tmp" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    # The file is now v2-shaped; stamp the v3 `category` field, then the v4 `repo`.
    _stamp_v3 "$ov" || return 1
    _stamp_v4 "$ov" || return 1
    return 0
}

# ── v3 stamp: give every lifecycle record an explicit `category` (issue #891) ──
# Runs over a v2-shaped file (either an on-disk v2 file, or the just-converted v1
# file). Sets each record's `category` to its existing valid category (a non-empty
# string), else its own key canonicalized through slugify, and moves the document
# to schema_version 3. Emits a per-record ::warning:: for any record whose category
# is absent, empty, or not a string (the record it had to synthesize a category
# for). Keys, state, fixed_at, provenance, meta_issues, and dismissed{} are left
# byte-unchanged. slugify is included from the shared module (issue #891) via -L so
# this file carries no second copy of the definition.
_stamp_v3() {  # $1 = overrides path (v2-shaped)
    local ov="$1"
    # Warn (per record) for any record lacking a usable category — the record a
    # category is being synthesized for. A jq failure here is non-fatal: the
    # transform below is the load-bearing step, and a lost warning must not abort a
    # migration. (No apostrophes in these jq programs: they sit inside bash single
    # quotes.)
    "$DEVFLOW_JQ" -r '
        (.patterns // {}) | to_entries[]
        | select((.value | type) == "object")
        | select(((( .value.category // "") | strings) // "") == "")
        | "::warning::pattern-state: record " + .key + " had no usable category field — stamping category equal to its own key (slugified)"' "$ov" 1>&2 \
      || echo "::warning::pattern-state: could not enumerate records missing a category during the v3 stamp (jq exited non-zero) — the stamp below still applies" >&2

    local tmp
    tmp="$(mktemp "$(_dir_of "$ov")/.overrides-v3.XXXXXX")" \
      || { echo "::error::pattern-state: could not create a temp file beside ${ov} during the v3 stamp" >&2; return 1; }
    if ! "$DEVFLOW_JQ" -L "$HERE" 'include "slugify";
        .schema_version = 3
        | .patterns = (
            (.patterns // {}) | to_entries
            | map(
                if (.value | type) == "object"
                then .value.category = (
                    ((( .value.category // "") | strings) // "") as $c
                    | if $c != "" then $c else (.key | slugify) end
                  )
                else . end
              )
            | from_entries
          )
        | .dismissed = (.dismissed // {})' "$ov" > "$tmp"; then
        rm -f "$tmp"
        echo "::error::pattern-state: the v3 category stamp jq transform failed for ${ov}" >&2
        return 1
    fi
    _atomic_write "$ov" "$tmp" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    return 0
}

# ── v4 stamp: give every meta-issue entry an explicit `repo` ──────────────────
# Runs over a v3-shaped file. A meta-issue entry stores a bare issue NUMBER, which
# names different work in different repositories; the entry's `repo` is what
# reconcile resolves it against. An entry that names none is bound to the legacy
# record repository through devflow_apply_legacy_record_repo — the explicit
# one-time compatibility rule, never the repository the run happens to be in.
# Numbers, urls, state, closedAt, state_reason and dismissed{} are left unchanged.
_stamp_v4() {  # $1 = overrides path (v3-shaped)
    local ov="$1" legacy tmp
    legacy="$(devflow_legacy_record_repo)" || return 1
    "$DEVFLOW_JQ" -r --arg legacy "$legacy" '
        (.patterns // {}) | to_entries[]
        | select((.value | type) == "object")
        | .key as $k
        | ((.value.meta_issues // []) | arrays // [])[]
        | select((.repo | type) != "string" or (.repo == ""))
        | "::warning::pattern-state: record " + $k + " meta-issue " + ((.number // "?")|tostring) + " named no repository — binding it to " + $legacy + " under the one-time compatibility rule"' "$ov" 1>&2 \
      || echo "::warning::pattern-state: could not enumerate repository-less meta-issue entries during the v4 stamp (jq exited non-zero) — the stamp below still applies" >&2

    tmp="$(mktemp "$(_dir_of "$ov")/.overrides-v4.XXXXXX")" \
      || { echo "::error::pattern-state: could not create a temp file beside ${ov} during the v4 stamp" >&2; return 1; }
    if ! "$DEVFLOW_JQ" --arg legacy "$legacy" '
        .schema_version = 4
        | .patterns = (
            (.patterns // {}) | to_entries
            | map(
                if (.value | type) == "object"
                then .value.meta_issues = (
                       ((.value.meta_issues // []) | arrays // [])
                       | map(
                           if type == "object"
                           then .repo = ((((.repo // "") | strings) // "") | if . == "" then $legacy else . end)
                           else . end
                         )
                     )
                else . end
              )
            | from_entries
          )
        | .dismissed = (.dismissed // {})' "$ov" > "$tmp"; then
        rm -f "$tmp"
        echo "::error::pattern-state: the v4 repository stamp jq transform failed for ${ov}" >&2
        return 1
    fi
    _atomic_write "$ov" "$tmp" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    return 0
}

# ── reconcile: refresh every meta-issue entry against live issue state ─────────
_reconcile() {  # $1 = overrides path, $2 = limit
    local ov="$1" limit="$2"
    [ -f "$ov" ] && [ -s "$ov" ] || return 0

    # Migrate first, so `reconcile` honors the documented contract that a v1 file
    # is detected AT RECONCILE START and rewritten before reconciling. Without
    # this, `reconcile` on a v1 file read an empty `.patterns`, applied nothing,
    # and wrote back a document that was `schema_version: 1` PLUS an empty
    # `patterns{}` — a shape neither version defines. `_migrate` is idempotent
    # (it returns immediately unless the file is v1), so `run`'s own call before
    # this one makes the second a no-op rather than a second rewrite.
    _migrate "$ov" || return 1

    # Prefetch every Retrospective-labelled issue, ONE CALL PER DISTINCT REPOSITORY
    # the file names. A repository-less prefetch would resolve every stored number
    # against whichever repository the run is in, so a same-numbered issue in the
    # current repository would drive a fixed/declined transition for a pattern whose
    # issue lives elsewhere. A non-zero gh exit OR a non-JSON body is a wholesale
    # failure: ::error:: + non-zero exit, no transition applied to any pattern.
    local entry_repos
    entry_repos="$("$DEVFLOW_JQ" -r '
        [ (.patterns // {}) | to_entries[] | (.value.meta_issues // [])[]? | ((.repo // "") | strings) // ""
          | select(. != "") ] | unique | .[]' "$ov")" \
      || { echo "::error::pattern-state: could not enumerate the repositories named in ${ov} (jq exited non-zero) — no transition applied" >&2; return 1; }

    # Prefetch map keyed by "<repo>#<number>" → {state,stateReason,closedAt}.
    # A jq failure inside a command substitution is NOT caught by `set -e`: the
    # assignment succeeds with an empty value, which would silently degrade every
    # number to the by-number fallback with no diagnostic. Check explicitly.
    local prefetch_map='{}' prefetch_raw one_repo
    while IFS= read -r one_repo; do
        [ -n "$one_repo" ] || continue
        prefetch_raw="$("$DEVFLOW_GH" issue list --repo "$one_repo" --label Retrospective --state all \
            --limit "$limit" --json number,state,stateReason,closedAt 2>/dev/null)" \
          || { echo "::error::pattern-state: the Retrospective prefetch failed for ${one_repo} (gh issue list exited non-zero)" >&2; return 1; }
        if ! printf '%s' "$prefetch_raw" | "$DEVFLOW_JQ" -e 'type == "array"' >/dev/null 2>&1; then
            echo "::error::pattern-state: the Retrospective prefetch body for ${one_repo} did not parse as a JSON array" >&2
            return 1
        fi
        prefetch_map="$(printf '%s' "$prefetch_raw" | "$DEVFLOW_JQ" -c --arg repo "$one_repo" --slurpfile acc <(printf '%s' "$prefetch_map") '
            reduce .[] as $r ($acc[0]; . + {($repo + "#" + ($r.number|tostring)): {state: $r.state, stateReason: $r.stateReason, closedAt: $r.closedAt}})')" \
          || { echo "::error::pattern-state: could not build the prefetch map for ${one_repo} (jq exited non-zero) — no transition applied" >&2; return 1; }
        [ -n "$prefetch_map" ] \
          || { echo "::error::pattern-state: the prefetch map came out empty for ${one_repo} (jq produced no output) — no transition applied" >&2; return 1; }
    done <<< "$entry_repos"

    # Walk every slug's every entry, resolving each number. We drive the loop in
    # bash so an uncovered number can fall back to `gh issue view`. Each resolved
    # triple is appended to a jq object keyed by number; the final jq pass applies
    # the transitions and derives record states from that resolution map.
    local numbers
    numbers="$("$DEVFLOW_JQ" -r '
        (.patterns // {}) | to_entries[] | .value.meta_issues // [] | .[]
        | select(.number != null)
        | (((.repo // "") | strings) // "") + "#" + (.number|tostring)' "$ov")" \
      || { echo "::error::pattern-state: could not enumerate the meta-issue numbers in ${ov} (jq exited non-zero) — no transition applied" >&2; return 1; }

    # Build a resolution map covering every number, using the prefetch first and
    # the by-number fallback for uncovered numbers. A number that resolves through
    # neither is recorded as unresolved so the transition pass can warn per slug.
    local resolved='{}'
    local num
    # De-duplicate the number list without a non-preflight tool (tr/sed/sort/uniq
    # are all barred from the SELECTION path) AND without an associative array:
    # `declare -A` is bash 4+, while `lib/preflight.sh` guarantees only *a* POSIX
    # bash and macOS still ships 3.2 as /bin/bash — where it aborts the whole
    # reconcile at rc 2 under `set -euo pipefail`, on the local/interactive tier
    # that is this loop's documented home. A space-delimited accumulator with a
    # `case` membership test is a pure builtin and works on 3.2. The numbers are
    # bare digit strings (jq emitted them from `.number`), so the space delimiters
    # cannot collide with a value.
    local _seen=""
    # Fallback-leg tallies. A single unresolvable number is ordinary (the issue was
    # deleted) and warns per slug. But `gh issue view` failing for EVERY number it
    # is asked about is not a statement about those issues — it is a broken
    # resolver (expired auth, rate limit, network partition, a repo-scope token
    # rejection, a drifted `--json` contract). Collapsing that into per-entry
    # `unresolved` and returning 0 would report a systemically-failed reconcile to
    # the caller as SUCCESS — and the Step 6 guard, which now does check the exit
    # status, would wave it through. Count both and decide after the loop.
    local _fb_attempted=0 _fb_failed=0
    while IFS= read -r num; do
        [ -n "$num" ] || continue
        case " $_seen " in *" $num "*) continue ;; esac
        _seen="$_seen $num"
        # `$num` is the repo-qualified key "<repo>#<number>"; split it with builtins
        # (a non-preflight PATH tool must not decide which repository is read).
        local _key_repo="${num%#*}" _key_num="${num##*#}"
        if [ -z "$_key_repo" ]; then
            # An entry that names no repository is UNESTABLISHED, never bound to the
            # current repository: resolving it here would read a same-numbered issue
            # in the wrong repository and drive a real lifecycle transition from it.
            resolved="$(printf '%s' "$resolved" | "$DEVFLOW_JQ" -c --arg n "$num" '. + {($n): {unresolved: true}}')" \
              || { echo "::error::pattern-state: could not record meta-issue ${num} as unresolved (jq exited non-zero) — no transition applied" >&2; return 1; }
            continue
        fi
        local cover
        cover="$(printf '%s' "$prefetch_map" | "$DEVFLOW_JQ" -c --arg n "$num" '.[$n] // empty')" \
          || { echo "::error::pattern-state: prefetch lookup for meta-issue ${num} failed (jq exited non-zero) — no transition applied" >&2; return 1; }
        if [ -z "$cover" ]; then
            # By-number fallback — bounded by the number of records.
            _fb_attempted=$(( _fb_attempted + 1 ))
            cover="$("$DEVFLOW_GH" issue view "$_key_num" --repo "$_key_repo" --json number,state,stateReason,closedAt 2>/dev/null \
                     | "$DEVFLOW_JQ" -c '{state: .state, stateReason: .stateReason, closedAt: .closedAt}' 2>/dev/null || true)"
            if [ -z "$cover" ] || [ "$cover" = "null" ]; then
                _fb_failed=$(( _fb_failed + 1 ))
                resolved="$(printf '%s' "$resolved" | "$DEVFLOW_JQ" -c --arg n "$num" '. + {($n): {unresolved: true}}')" \
                  || { echo "::error::pattern-state: could not record meta-issue ${num} as unresolved (jq exited non-zero) — no transition applied" >&2; return 1; }
                continue
            fi
        fi
        resolved="$(printf '%s' "$resolved" | "$DEVFLOW_JQ" -c --arg n "$num" --argjson c "$cover" '. + {($n): $c}')" \
          || { echo "::error::pattern-state: could not record the resolution of meta-issue ${num} (jq exited non-zero) — no transition applied" >&2; return 1; }
    done <<< "$numbers"

    # Systemic-resolver summary (see the tally comment above). Every fallback
    # lookup failing is evidence of a BROKEN RESOLVER rather than a statement
    # about those issues, and a run that quietly applied zero transitions and
    # reported success would hide that.
    #
    # It is a WARNING, not an abort, and it deliberately does NOT short-circuit
    # the transition pass below. An earlier revision returned non-zero here, and
    # that was wrong three ways: (1) it suppressed the per-slug `::warning::`
    # naming each unresolvable slug and its failing leg, which is an explicit
    # acceptance criterion, because the warning pass runs downstream; (2) it
    # discarded the transitions of every OTHER pattern the prefetch had resolved
    # perfectly well — a total loss to diagnose a partial one; and (3) on a repo
    # whose `Retrospective` label does not exist the prefetch returns `[]` and
    # routes every record to the fallback, so one transient blip would hard-fail
    # a run that should degrade per-slug. Diagnose loudly; let the reconcile
    # finish and let the per-slug warnings do their documented job.
    if [ "$_fb_attempted" -ge 2 ] && [ "$_fb_failed" -eq "$_fb_attempted" ]; then
        echo "::warning::pattern-state: every by-number lookup failed (${_fb_failed}/${_fb_attempted}) — most likely a broken resolver (expired auth, rate limit, network, or a drifted gh --json contract) rather than ${_fb_failed} genuinely deleted issues; the per-slug warnings below name each affected slug" >&2
    fi

    # Apply transitions + derive record states in one jq pass. Warnings for
    # no-url / unresolved / unrecognized-stateReason records are emitted to stderr
    # from a parallel jq pass so the transformed body stays on stdout only.
    printf '%s' "$resolved" | "$DEVFLOW_JQ" -r --slurpfile ov "$ov" '
        . as $res
        | ($ov[0].patterns // {}) | to_entries[]
        | .key as $slug | .value as $rec
        | ($rec.meta_issues // []) as $entries
        | if ($entries | length) == 0 then
            "::warning::pattern-state: pattern " + $slug + " has a lifecycle record with no meta-issue URL — no transition applied"
          else
            ( $entries[]
              | .number as $n
              | ((((.repo // "") | strings) // "") + "#" + ($n|tostring)) as $k
              | ($res[$k] // {unresolved:true}) as $r
              | if ($n == null) or ($r.unresolved == true) then
                  "::warning::pattern-state: pattern " + $slug + " meta-issue " + (($n // "?")|tostring) + " could not be resolved via the prefetch or the by-number fallback — no transition applied"
                # The recognized set (open, plus the three closed stateReasons) all
                # transition cleanly — no warning; anything else is unrecognized.
                elif ($r.state == "OPEN") or (["COMPLETED","NOT_PLANNED","DUPLICATE"] | index($r.stateReason)) then empty
                else
                  "::warning::pattern-state: pattern " + $slug + " meta-issue #" + ($n|tostring) + " is closed with an unrecognized stateReason " + ($r.stateReason|tostring) + " — no transition applied"
                end
            )
          end' 1>&2 \
      || echo "::warning::pattern-state: the per-slug reconcile diagnostics could not be emitted (jq exited non-zero) — the ABSENCE of per-slug warnings below is NOT evidence that every meta-issue resolved" >&2

    local tmp
    tmp="$(mktemp "$(_dir_of "$ov")/.overrides-rec.XXXXXX")" \
      || { echo "::error::pattern-state: could not create a temp file beside ${ov} during reconcile" >&2; return 1; }
    if ! printf '%s' "$resolved" | "$DEVFLOW_JQ" --slurpfile ov "$ov" '
        # Refuse to transform a document that did not load. On an empty slurp
        # `$ov[0]` is null, and `null | .patterns = (…)` is LEGAL jq: it
        # constructs `{"patterns":{}}` and exits 0. That stub would flow into
        # _atomic_write and replace overrides.json — losing schema_version, every
        # lifecycle record, and the hand-written `dismissed{}` entries the
        # migration takes such care to preserve. Assert the slurp landed exactly
        # one document before touching anything.
        (if ($ov | length) != 1 then
           error("overrides document did not load (slurped \($ov|length) values) — refusing to write")
         else . end)
        | . as $res
        | $ov[0]
        | .patterns = (
            (.patterns // {}) | to_entries | map(
              .key as $slug | .value as $rec
              | .value.meta_issues = (
                  ($rec.meta_issues // []) | map(
                    . as $e
                    | ((((($e.repo // "") | strings) // "") + "#" + (($e.number // "")|tostring))) as $k
                    | ($res[$k] // {unresolved:true}) as $r
                    | if ($e.number == null) or ($r.unresolved == true) then $e
                      elif ($r.state == "OPEN") then ($e + {state: "filed", closedAt: null, fixed_at: null, state_reason: null})
                      elif ($r.stateReason == "COMPLETED") then ($e + {state: "fixed", closedAt: $r.closedAt, fixed_at: $r.closedAt, state_reason: $r.stateReason})
                      elif (["NOT_PLANNED","DUPLICATE"] | index($r.stateReason)) then ($e + {state: "declined", closedAt: $r.closedAt, fixed_at: $r.closedAt, state_reason: $r.stateReason})
                      else $e end
                  )
                )
              # Derive the record state from the (now reconciled) entry set:
              # filed if any entry is filed; else the state of the entry with
              # the newest closedAt; record.fixed_at is that newest entry fixed_at.
              #
              # Deliberate trade-off (issue #788): an entry that could NOT be
              # resolved keeps its PRIOR state, so a record holding one genuinely
              # `fixed` entry plus one permanently-inaccessible `filed` entry
              # derives to `filed` and masks the fix for as long as the entry
              # stays unresolvable. That direction is chosen on purpose: deriving
              # the optimistic state instead would CLEAR the suppression of a
              # pattern whose issue may still be open, re-filing a duplicate. The
              # conservative direction only delays a re-file, and each unresolved
              # entry already fires a per-slug ::warning:: naming it, so the
              # condition is visible in the run log rather than silent.
              | .value as $rec2
              | ($rec2.meta_issues // []) as $es
              | if ($es | any(.state == "filed")) then
                  .value.state = "filed" | .value.fixed_at = null
                elif ($es | length) > 0 then
                  ($es | map(select(.closedAt != null)) | sort_by(.closedAt) | last) as $newest
                  | if $newest == null then .
                    else .value.state = $newest.state | .value.fixed_at = ($newest.fixed_at // $newest.closedAt)
                    end
                else . end
            ) | from_entries
          )' > "$tmp"; then
        rm -f "$tmp"
        echo "::error::pattern-state: reconcile jq transform failed for ${ov}" >&2
        return 1
    fi
    _atomic_write "$ov" "$tmp" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    return 0
}

# ── entrypoint ────────────────────────────────────────────────────────────────
[ $# -ge 2 ] || _usage
CMD="$1"; OVERRIDES="$2"; shift 2
LIMIT=200
while [ $# -gt 0 ]; do
    case "$1" in
        # `--limit` with no value must not reach `$2` under `set -u` (an
        # "unbound variable" abort diagnoses nothing); reject it here by name.
        --limit) [ $# -ge 2 ] || { echo "pattern-state: --limit requires a value" >&2; exit 2; }
                 LIMIT="$2"; shift 2 ;;
        *) echo "pattern-state: unknown argument: $1" >&2; exit 2 ;;
    esac
done
# Positive integer: `0` is all digits but is not positive, and `gh --limit 0` is
# itself an error — reject it here rather than shipping it to gh.
case "$LIMIT" in
    ''|*[!0-9]*|0|0[0-9]*) echo "pattern-state: --limit must be a positive integer (got '${LIMIT}')" >&2; exit 2 ;;
esac

case "$CMD" in
    migrate)   _migrate "$OVERRIDES" ;;
    reconcile) _reconcile "$OVERRIDES" "$LIMIT" ;;
    run)       _migrate "$OVERRIDES" && _reconcile "$OVERRIDES" "$LIMIT" ;;
    *) _usage ;;
esac

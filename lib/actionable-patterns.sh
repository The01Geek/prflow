#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# actionable-patterns.sh — emit the list of patterns that currently warrant
# being filed as a retrospective issue, honouring min_occurrences and
# cooldown_days config.
#
# Usage:
#   bash lib/actionable-patterns.sh <retrospectives.jsonl> <overrides.json> [--full]
#
# Args:
#   $1  path to retrospectives.jsonl
#   $2  path to overrides.json
#   $3  optional: --full, emitting the UNFILTERED whole-pattern view the run
#       report renders (every lifecycle status, below-threshold and suppressed
#       included) instead of the actionable subset. An unset or empty $3 selects
#       the default (filtered) view; any other value, and any argument beyond $3,
#       is rejected with rc 2. Note the emitted `status` is one of the six
#       lifecycle values under --full, not just open/regressed.
#
# Output (stdout):
#   Compact JSON array of actionable pattern objects, each shaped as:
#     {
#       "tag":              <string>,          # the entry's own (opaque) filing key (== slug)
#       "slug":             <string>,          # URL-safe issue-filing key (== tag)
#       "category":         <string>,          # attribution category (issue #891):
#                                              #   the entry's own key when it holds no
#                                              #   lifecycle record, else the record's
#                                              #   stored category
#       "occurrence_count": <int>,
#       "status":           "open"|"regressed" (any of the six lifecycle
#                           values under --full),
#       "first_seen":       <iso8601|null>,
#       "last_seen":        <iso8601|null>,
#       "occurrences":      [...],             # each element carries pr/ts/verdict plus
#                                              #   that occurrence's own summary/descriptors/
#                                              #   suggested_interventions (issue #893), so
#                                              #   Stage B clusters sub-patterns per-occurrence
#       "descriptors":      [<string>, ...],   # union of the occurrences' free-text
#                                              #   descriptors — Stage B reads these to
#                                              #   decide if the cluster is one fix or many
#       "cooldown_active":  <bool>             # true if an open filed retrospective
#                                              #   issue for this slug was created
#                                              #   within cooldown_days
#     }
#
# Environment:
#   DEVFLOW_GH  override the gh binary. Used by tests for stubbing; when unset
#               or empty it is resolved (execution-verified) via lib/resolve-gh.sh.

set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

HERE="$(cd "$(dirname "$0")" && pwd)"

# Scratch dir for corpus-sized jq operands routed through --slurpfile (issue #783):
# a corpus-sized operand passed via --argjson (an argv slot) overflows the kernel
# arg limit and aborts jq with "Argument list too long"; a --slurpfile file read
# does not. Also holds the first-run overrides stub so a single EXIT trap cleans
# everything up.
_JQ_TMP="$(mktemp -d)"
trap 'rm -rf "$_JQ_TMP"' EXIT

# Source config helpers.
# shellcheck source=lib/config-source.sh
. "$HERE/config-source.sh"

RETRO_FILE="$1"
OVERRIDES_FILE="$2"
# --full emits the UNFILTERED pattern view (every pattern, every status) so the
# orchestrator can carry the whole picture into the run report (issue #788); the
# default emits only the actionable subset (open/regressed above threshold).
FULL=0
# Reject an unrecognized argument LOUDLY. A near-miss (`--ful`, `-full`,
# `--full=1`) or a --full that lands PAST $3 would otherwise silently yield the
# FILTERED view, which the caller then writes to patterns-full.json and the
# report renders under a heading promising the unfiltered picture — well-formed,
# non-empty, and wrong, with every downstream guard passing. Mirrors
# pattern-state.sh's strict arg handling.
#
# The arity check is what makes that claim true for $4 and beyond: a `case` on
# $3 alone structurally cannot see a later argument, so without this the flag
# landing in $4 is accepted in silence — exactly the failure named above.
if [ "$#" -gt 3 ]; then
    echo "actionable-patterns: unexpected argument '$4' (expected at most <retrospectives> <overrides> [--full])" >&2
    exit 2
fi
case "${3:-}" in
    '') : ;;
    --full) FULL=1 ;;
    *) echo "actionable-patterns: unknown argument '$3' (expected --full)" >&2; exit 2 ;;
esac

MIN="$(devflow_conf '.prflow_retrospective.min_occurrences' 2)"
COOLDOWN="$(devflow_conf '.prflow_retrospective.cooldown_days' 3)"

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

# ── Stub overrides.json if absent or empty (first-run safety) ─────────────────
_OVERRIDES_ACTUAL="$OVERRIDES_FILE"
if [ ! -f "$OVERRIDES_FILE" ] || [ ! -s "$OVERRIDES_FILE" ]; then
    printf '{"schema_version":4,"patterns":{},"dismissed":{}}' > "$_JQ_TMP/overrides.json"
    _OVERRIDES_ACTUAL="$_JQ_TMP/overrides.json"
fi

# ── Experiment records: the cost source for the #1828 cost-weighted ranking ───
# The unified experiment record (scripts/build-experiment-records.py) is the sibling
# of the retrospectives file. compute-patterns.jq joins occurrences to their PR's
# efficiency_runs[].iterations from it. The cost source is best-effort — it only
# reorders patterns, never admits or excludes one — so a source it cannot read must
# degrade to no coverage (rank by occurrence count), never take the weekly derivation
# down. An absent/empty artifact (a repo that has not built one yet) stubs to an empty
# stream; a present-but-unparseable one would otherwise abort at the eager --slurpfile
# read below (there is no breadcrumb on that jq stage), so it is validated here and, on
# a parse failure, replaced by the same empty stub with a specific ::warning::.
EXPERIMENTS_FILE="$(dirname "$RETRO_FILE")/experiment-records.jsonl"
_EXPERIMENTS_ACTUAL="$EXPERIMENTS_FILE"
if [ ! -f "$EXPERIMENTS_FILE" ] || [ ! -s "$EXPERIMENTS_FILE" ]; then
    : > "$_JQ_TMP/experiment-records.jsonl"
    _EXPERIMENTS_ACTUAL="$_JQ_TMP/experiment-records.jsonl"
elif ! "$DEVFLOW_JQ" '.' "$EXPERIMENTS_FILE" >/dev/null 2>&1; then
    echo "::warning::actionable-patterns: experiment-records.jsonl at '$EXPERIMENTS_FILE' does not parse as JSON — ignoring the cost source this run (patterns rank by occurrence count only); regenerate it via scripts/build-experiment-records.py or remove it to restore cost-weighted ranking" >&2
    : > "$_JQ_TMP/experiment-records.jsonl"
    _EXPERIMENTS_ACTUAL="$_JQ_TMP/experiment-records.jsonl"
fi

# ── Compute pattern view ─────────────────────────────────────────────────────
# If the retrospectives file doesn't exist yet (first run or empty scan),
# pipe an empty stream to jq rather than letting it error on a missing file.
if [ -f "$RETRO_FILE" ] && [ -s "$RETRO_FILE" ]; then
  PATTERN_VIEW="$(
    "$DEVFLOW_JQ" -s -L "$HERE" --slurpfile overrides "$_OVERRIDES_ACTUAL" \
       --slurpfile experiments "$_EXPERIMENTS_ACTUAL" \
       -f "$HERE/compute-patterns.jq" \
       "$RETRO_FILE"
  )"
else
  PATTERN_VIEW="$(
    printf '' | "$DEVFLOW_JQ" -s -L "$HERE" --slurpfile overrides "$_OVERRIDES_ACTUAL" \
       --slurpfile experiments "$_EXPERIMENTS_ACTUAL" \
       -f "$HERE/compute-patterns.jq"
  )"
fi

# Producer-drift heartbeat (issue #1828): compute-patterns.jq's per-record cost-index type
# guards drop a malformed experiment record silently (fail-safe — the pattern reads
# uncovered), so a producer-schema regression that still parses as JSON — a non-number `pr`,
# a renamed `efficiency_runs` — would collapse cost coverage to zero with no signal,
# indistinguishably from the benign no-records case. When the real experiment file was used
# (the `_EXPERIMENTS_ACTUAL == EXPERIMENTS_FILE` arm, i.e. present, non-empty, and parseable)
# yet NO pattern came out covered, emit one advisory ::warning:: so that silent collapse is
# observable. `|| true` + the non-numeric arm keep an unestablished count from fabricating a
# zero heartbeat (unknown is not zero); the warning never changes the emitted output.
if [ "$_EXPERIMENTS_ACTUAL" = "$EXPERIMENTS_FILE" ]; then
  _COVERED_ANY="$(printf '%s' "$PATTERN_VIEW" | "$DEVFLOW_JQ" '[to_entries[] | select((.value.covered_occurrence_count // 0) > 0)] | length' 2>/dev/null || true)"
  case "$_COVERED_ANY" in
    ''|*[!0-9]*) : ;;
    0) echo "::warning::actionable-patterns: experiment-records.jsonl at '$EXPERIMENTS_FILE' is present and parses but yielded zero cost coverage for every pattern — cost-weighted ranking has degraded to occurrence-count-only; if unexpected, check scripts/build-experiment-records.py for producer-schema drift (a non-number 'pr' or a renamed 'efficiency_runs' the per-record type guards drop silently)" >&2 ;;
  esac
fi

# ── Fetch open filed retrospective issues and build slug→createdAt map ───────
# Each pattern the loop files becomes an open issue titled
# "[devflow-retrospective] meta: <slug> — <title>" (see lib/meta-issue.sh). A
# pattern with such an issue still open and created within cooldown_days is in
# cooldown — don't re-file it this run. (The cross-run guard is now the
# issue-closure lifecycle in overrides.patterns[] that lib/pattern-state.sh
# reconciles — a pattern with a `filed` meta-issue derives status `filed` and is
# not actionable; this cooldown is the within-window guard against re-filing the
# same open issue twice inside one window.)
#
# KNOWN GAP (issue #893): $OPEN_ISSUE_MAP and the cooldown_active lookup below are
# keyed by the PATTERN's own coarse `.slug`. A findings-array filing (lib/select-
# findings.sh) meta-issues under a composed `<category>-<subslug>` key instead, so
# a cooldown-window issue filed on the findings-array path is invisible to this
# lookup: this.slug never equals that composed key, so $has_issue is always false
# for it. In practice the pattern-level `status` exclusion (filed/dismissed
# patterns are already non-actionable before this cooldown runs) masks the gap for
# most patterns; a pattern that regresses back to actionable status inside the
# cooldown window on the findings-array path is the case this misses. Not fixed
# here: scoping cooldown per-composed-key would need the same category-aggregating
# read select-findings.sh's per-category cap already performs, which is a larger
# change than this reception pass's scope.
# Split the fetch from the jq so a gh failure (auth/rate-limit/network) and a
# non-JSON body each get a SPECIFIC breadcrumb naming the cause — the same
# fail-loud discipline meta-issue.sh's de-dupe lookup uses — instead of an opaque
# set -e/pipefail abort that points at neither the cooldown step nor its cause.
_OPEN_ISSUES_RAW="$("$DEVFLOW_GH" issue list --search "[devflow-retrospective] meta: in:title" \
    --state open --json number,title,createdAt --limit 200)" \
  || { echo "::error::actionable-patterns: open-issue cooldown lookup failed (gh issue list)" >&2; exit 1; }
OPEN_ISSUE_MAP="$(
  printf '%s' "$_OPEN_ISSUES_RAW" \
  | "$DEVFLOW_JQ" '
      [ .[]
        # Parse the slug token from the de-dup title prefix; drop any issue whose
        # title does not carry it (foreign issue that matched the search loosely).
        # The capture()? + // {} chain tolerates a non-string OR non-matching
        # title by yielding {} (then dropped), mirroring the meta-issue.sh de-dupe
        # re-parse exactly — so a foreign row is dropped, never an opaque abort.
        | (((.title | capture("\\[devflow-retrospective\\] meta: (?<slug>[A-Za-z0-9_-]+)")?) // {}) | .slug) as $slug
        | select($slug != null and $slug != "")
        # Guard the operand the cooldown comparison feeds to strptime below by
        # parsing it with the SAME strptime contract here and dropping the row if
        # it fails. A shape regex is a SUPERSET of what strptime accepts (it
        # admits out-of-range fields like month 13 / hour 99 that strptime
        # range-rejects and aborts on), so the guard and the consumer would not
        # share one contract; parsing with strptime itself makes the drop total —
        # every row that survives here is guaranteed to parse in the OUTPUT block.
        # `try ... catch null` also subsumes the non-string and "" / fractional /
        # non-Z cases. Dropping the row (like an unparseable slug) keeps the
        # cooldown comparison total; the OUTPUT breadcrumb is the fail-loud backstop.
        | select(((.createdAt | type) == "string") and ((.createdAt | (try strptime("%Y-%m-%dT%H:%M:%SZ") catch null)) != null))
        | { slug: $slug, createdAt: .createdAt }
      ]
      | reduce .[] as $item (
          {};
          # keep newest createdAt per slug
          if has($item.slug) and .[$item.slug] >= $item.createdAt
          then .
          else . + {($item.slug): $item.createdAt}
          end
        )
    '
)" || { echo "::error::actionable-patterns: could not parse the open-issue list as JSON (gh returned non-JSON?): $(printf '%s' "$_OPEN_ISSUES_RAW" | head -c 200)" >&2; exit 1; }

# Defense-in-depth: the map above silently drops any open issue whose title
# carries the de-dup prefix but whose slug token does not match the capture. A
# slug-grammar drift between meta-issue.sh's title format and this capture would
# make every drifted issue invisible to the cooldown and re-file duplicates with
# no breadcrumb — so count the drops and surface them (the round-trip test pins
# the canonical case; this catches a future drift in the field).
_DROPPED_COUNT="$(
  printf '%s' "$_OPEN_ISSUES_RAW" \
  | "$DEVFLOW_JQ" '[ .[]
          | select(((.title | type) == "string")
                   and (.title | test("\\[devflow-retrospective\\] meta: "))
                   and ((.title | test("\\[devflow-retrospective\\] meta: [A-Za-z0-9_-]+")) | not)) ]
        | length'
)" || { echo "::error::actionable-patterns: the slug-drift drop-counter failed to evaluate the open-issue list" >&2; exit 1; }
if [ "${_DROPPED_COUNT:-0}" -gt 0 ]; then
    echo "::warning::actionable-patterns: ${_DROPPED_COUNT} open '[devflow-retrospective] meta:' issue(s) had an unparseable slug and were skipped for cooldown — possible slug-grammar drift vs meta-issue.sh" >&2
fi

# ── Cooldown boundary (epoch seconds for COOLDOWN days ago) ─────────────────
# Portable date math via python3 (GNU `date -d` is unavailable on macOS/BSD).
COOLDOWN_EPOCH="$(python3 -c "import datetime as d; print(int((d.datetime.now(d.timezone.utc)-d.timedelta(days=${COOLDOWN})).timestamp()))")"

# ── Build output array ───────────────────────────────────────────────────────
# Default mode: each tag in the pattern view whose status is "open" or
# "regressed", where a `regressed` tag bypasses the MIN occurrence threshold
# outright (issue #788). --full mode drops BOTH filters and emits every tag.
# Either way the entry carries cooldown_active resolved. The two `select` lines
# below are the authoritative statement of this; keep them in step.

# Route the corpus-sized operands (the --slurpfile flags below) through files
# rather than --argjson argv slots: they grow monotonically with the corpus and, at
# scale, overflow the kernel arg limit (jq: "Argument list too long") when passed as
# argv (issue #783). --slurpfile wraps each file in a one-element array, so each
# reference dereferences [0].
printf '%s' "$PATTERN_VIEW"   > "$_JQ_TMP/pattern_view.json"
printf '%s' "$OPEN_ISSUE_MAP" > "$_JQ_TMP/open_issue_map.json"
OUTPUT="$(
  # argjson-ok: min, full, cooldown_epoch -- bounded scalars (small ints / a 0|1
  # flag / an epoch int) — safe as argv; the corpus-sized operands use --slurpfile.
  "$DEVFLOW_JQ" -n --slurpfile pattern_view    "$_JQ_TMP/pattern_view.json" \
        --slurpfile open_issue_map  "$_JQ_TMP/open_issue_map.json" \
        --argjson min             "$MIN" \
        --argjson full            "$FULL" \
        --argjson cooldown_epoch  "$COOLDOWN_EPOCH" '
    [
      $pattern_view[0]
      | to_entries[]
      # Default (actionable) mode: only open/regressed patterns above the
      # occurrence threshold — but a `regressed` pattern ALWAYS bypasses the
      # threshold (issue #788: the schema documents this bypass; the code now
      # honours it). --full mode drops both filters and emits every pattern.
      | select($full == 1 or .value.status == "open" or .value.status == "regressed")
      | select($full == 1 or .value.status == "regressed" or .value.occurrence_count >= $min)
      | .key as $tag
      | .value as $v
      # keys from compute-patterns.jq are already canonical slugs
      | $tag as $slug
      | ($open_issue_map[0] | has($slug)) as $has_issue
      | (
          if $has_issue then
            (($open_issue_map[0][$slug]
              | strptime("%Y-%m-%dT%H:%M:%SZ")
              | mktime) >= $cooldown_epoch)
          else false
          end
        ) as $cooldown_active
      | {
          tag: $tag,
          slug: $slug,
          # The attribution category (issue #891): equals the entry own key when
          # it holds no lifecycle record, else the stored category on the record.
          # Emitted so the run report can name both the opaque filing key and the
          # category, and so Step 8c can bind the per-category cap comparand to it.
          # (No apostrophes here: this jq program sits inside bash single quotes.)
          category: ($v.category // $tag),
          occurrence_count: $v.occurrence_count,
          status: $v.status,
          first_seen: $v.first_seen,
          last_seen: $v.last_seen,
          occurrences: $v.occurrences,
          descriptors: ($v.descriptors // []),
          # Cost aggregate + the covered-occurrence count it was computed from (issue
          # #1828). null cost signals zero coverage — never a fabricated 0.
          cost_mean_iterations: $v.cost_mean_iterations,
          covered_occurrence_count: ($v.covered_occurrence_count // 0),
          cooldown_active: $cooldown_active
        }
    ]
    # Cost-weighted ranking (issue #1828): covered patterns first, ordered by descending
    # cost aggregate with occurrence count as the tiebreak; a pattern with zero covered
    # occurrences ranks after every covered pattern, ordered by occurrence count. jq
    # sort_by is ascending, so the numeric keys are negated for descending order. An
    # uncovered pattern has null cost — `// 0` folds it to the same key the covered/
    # uncovered partition (the first key) already sorts it below every covered pattern by.
    | sort_by(
        (if (.covered_occurrence_count // 0) > 0 then 0 else 1 end),
        -(.cost_mean_iterations // 0),
        -(.occurrence_count)
      )
  '
)" || { echo "::error::actionable-patterns: failed to build the actionable-pattern output (jq exited non-zero — e.g. a malformed pattern view; the former oversized-operand arg-limit overflow is now mitigated via --slurpfile)" >&2; exit 1; }

# ── Liveness warning (issue #788) ─────────────────────────────────────────────
# When the actionable (eligible) set is EMPTY while at least one pattern is
# suppressed at/above the threshold — occurrence_count >= min AND status in
# {dismissed, declined, fixed} — the loop is silently producing nothing on inputs
# that should raise something. Emit a loud ::warning:: naming the count and the
# highest-occurrence suppressed slug, and print a `liveness:` line to stdout's
# sibling stderr so the orchestrator can surface it in the report. `filed` is
# deliberately EXCLUDED: an open meta-issue is the loop working correctly.
#
# The condition is deliberately NOT phrased as a recurrence. `occurrence_count`
# is cumulative history, so a `fixed` pattern whose occurrences all predate its
# `fixed_at` satisfies `occurrence_count >= min` indefinitely — and a `fixed`
# pattern that DID recur would have derived `regressed` (an eligible status),
# which empties this branch's precondition. Including `fixed` is what the issue
# asks for (a lifecycle-state audit prompt on a run that filed nothing), but
# calling that state "recurring" would over-state it, so the emitted text says
# "occurred at/above min_occurrences and are currently suppressed" instead.
# In --full mode this diagnostic is suppressed (the caller wants the raw view).
if [ "$FULL" -eq 0 ]; then
    # Fail CLOSED on an unestablished count: an empty $OUTPUT (an upstream
    # producer that failed) makes `jq length` print nothing and exit 0, and
    # `${_ELIGIBLE_N:-0}` would launder that unknown into a genuine "0 eligible"
    # — firing a spurious liveness warning about a run whose eligible set was
    # never measured. Unknown is not zero (CLAUDE.md): a non-numeric count skips
    # the diagnostic and says so, rather than diagnosing on unmeasured input.
    _ELIGIBLE_N="$(printf '%s' "$OUTPUT" | "$DEVFLOW_JQ" 'length' 2>/dev/null || true)"
    case "$_ELIGIBLE_N" in
        ''|*[!0-9]*)
            echo "actionable-patterns: eligible-set size could not be established (empty or non-numeric jq result) — liveness diagnostic skipped" >&2
            _ELIGIBLE_N=-1 ;;
    esac
    if [ "$_ELIGIBLE_N" -eq 0 ]; then
        printf '%s' "$PATTERN_VIEW" > "$_JQ_TMP/pv_live.json"
        # One jq pass emits the count and the highest-occurrence slug as a single
        # "N slug" line (empty when nothing is suppressed at/above the threshold).
        _LIVE="$(
          # argjson-ok: min -- a bounded small int (the occurrence threshold);
          # the corpus-sized pattern view uses --slurpfile.
          "$DEVFLOW_JQ" -r -n --slurpfile pv "$_JQ_TMP/pv_live.json" --argjson min "$MIN" '
            [ $pv[0] | to_entries[]
              | select(.value.occurrence_count >= $min)
              | select(.value.status == "dismissed" or .value.status == "declined" or .value.status == "fixed")
              | {slug: .key, occ: .value.occurrence_count} ]
            | sort_by(-.occ)
            | if length > 0 then "\(length) \(.[0].slug)" else "" end'
        )" || {
            # Never collapse a FAILED probe onto "nothing is suppressed". This is
            # the one mechanism that says "the loop produced nothing on inputs that
            # should have raised something", and it only matters on runs where the
            # eligible set is already empty — i.e. exactly the runs it was written
            # for. The _ELIGIBLE_N block above refuses to launder an unestablished
            # count; this one must not undo that discipline one derivation later.
            echo "actionable-patterns: the liveness diagnostic could not be derived (jq exited non-zero) — the report's liveness section will be omitted, which is NOT evidence that nothing is suppressed" >&2
            _LIVE=""
        }
        if [ -n "$_LIVE" ]; then
            _SUP_N="${_LIVE%% *}"
            _TOP="${_LIVE#* }"
            echo "::warning::actionable-patterns: no pattern is eligible to file, yet ${_SUP_N} pattern(s) have occurred at/above min_occurrences and are currently suppressed (dismissed/declined/fixed) — highest: ${_TOP}. Nothing will be filed; investigate the lifecycle state." >&2
            echo "liveness: ${_SUP_N} suppressed pattern(s) at/above min_occurrences, highest ${_TOP}" >&2
        fi
    fi
fi

printf '%s\n' "$OUTPUT"

include "slugify";
# compute-patterns.jq — derives the per-pattern view from
# retrospectives.jsonl + overrides.json.
#
# This file is the spec author's substitute for a stored `patterns.json`:
# the view is fresh on every read, and there is no cached state to drift.
#
# Invocation (note the `-L <dir holding slugify.jq>`, required for the include):
#   jq -s -L lib -f lib/compute-patterns.jq \
#      --slurpfile overrides .prflow/learnings/overrides.json \
#      .prflow/learnings/retrospectives.jsonl
#
# Inputs:
#   stdin: array of retrospective entries (kind: "implementation" | "audit"),
#          obtained by passing -s (slurp) so JSONL becomes a single array.
#   $overrides: array containing one parsed overrides.json document.
#
# Output: an object keyed by each lifecycle record's OWN (opaque) filing key
# canonicalized through slugify — a no-op for a compose-produced or already-canonical
# key — and
# by each corpus category no record claims, each entry shaped as:
#   {
#     "first_seen": <iso8601 | null>,
#     "last_seen": <iso8601 | null>,
#     "occurrence_count": <int>,
#     "occurrences": [{"pr": <int>, "ts": <iso8601>, "verdict": "imperfect|blocked",
#                      "summary": <string | null>,
#                      "descriptors": [<string>, ...],
#                      "suggested_interventions": [<object>, ...]}],   # per-occurrence
#                                              # free text (issue #893) so Stage B
#                                              # clusters sub-patterns from on-disk data
#     "descriptors": [<string>, ...],   # union of the occurrences' free-text descriptors
#     "status": "dismissed" | "regressed" | "declined" | "filed" | "fixed" | "open",
#     "fix_history": [{"pr": <int>, "ts": <iso8601>}],
#     "category": <string>              # the attribution category this entry groups by
#   }
#
# Opaque-key model (issue #891): a lifecycle record's KEY is an opaque filing key,
# no longer required to equal a category slug. Each record carries an explicit
# `category` field naming the fixed-vocabulary category it belongs to, and THIS
# file attributes occurrences to a record by that stored `category` (canonicalized
# through slugify on read), never by the key. So a record keyed
# `tooling-gap--slow-suite` with `category: "tooling-gap"` reports the occurrence
# count, first_seen, last_seen, and descriptors of the `tooling-gap` category.
# A record with no `category` (a pre-#891 v2 file, or a repaired shape) falls back
# to its own key, so derivation over a v2 file matches the same file after
# migration to v3 (the derivation-parity invariant).
#
# Entry construction:
#   - one entry per lifecycle record, keyed by the record's own key, attributed by
#     its stored category;
#   - one entry per CORPUS category (drawn from occurrences, audit fix rows, and
#     dismissed{}) that NO record claims. A corpus category some record's attribution
#     category equals is SUPPRESSED — its occurrences are already reported by that
#     record's own entry, so re-emitting a bare-category grab-bag alongside would
#     re-file the category next to its own sub-patterns. Suppression removes the
#     corpus-derived limb only; a record's own entry is never suppressed.
#
# Grouping key: schema-v2 entries carry `categories` (a fixed vocabulary);
# legacy schema-v1 entries carry `theme_tags`. This file reads
# `(.categories // .theme_tags)` so both shapes count, and a mixed file
# (v1 entries from before the migration + v2 entries after) Just Works.
#
# Status derivation (the six arms this file evaluates, complete by construction
# over the status enum, first match wins). Each arm now reads the entry's
# ATTRIBUTION CATEGORY, not the key — so `dismissed` (evaluated first, and
# therefore governing) tests the attribution category against dismissed{}, which
# keeps a maintainer's one durable off-switch suppressing every sub-pattern of a
# dismissed category regardless of a sub-pattern record's opaque key:
#   - attribution category in overrides.dismissed (the human map) → "dismissed"
#   - newest occurrence.ts > fix timestamp                        → "regressed"
#   - lifecycle record state == "declined"                        → "declined"
#   - lifecycle record state == "filed"                           → "filed"
#   - lifecycle record state == "fixed", OR (no
#     record and legacy fix_history non-empty)                    → "fixed"
#   - otherwise                                                   → "open"
#
# Fix-timestamp precedence (issue #788): for an entry that holds a lifecycle record,
# that record's `fixed_at` is the authoritative fix timestamp and the legacy
# `kind: "audit"` rows for that category are NOT consulted; the legacy rows remain
# the fix source only for a corpus category with no lifecycle record. This keeps
# historical fix_history readable without letting a frozen pre-#152 audit timestamp
# outlive the lifecycle that replaced it, and introduces no second regression
# mechanism.
#
# `audit`-kind entries are a LEGACY-DATA-ONLY read path: since #152 the loop files
# an issue per pattern and no longer opens autonomous audit PRs, so nothing
# produces new `audit` entries. Historical `audit` rows still parse here (old
# fix_history is preserved) but are the fix source only for a category with no
# lifecycle record.

# Grouping tags for an implementation entry: v2 `categories`, falling back to
# v1 `theme_tags`. Defined once so occurrences_for and the tag-collection
# reducer stay in sync.
# Totality is load-bearing on BOTH limbs: this side of the derivation is written
# by an LLM subagent, so a `"categories": "tooling-gap"` (string) or `[7]`
# (non-string member) is an ordinary agent slip, not corruption. Unguarded, the
# first aborts on `Cannot iterate over string` and the second on `explode input
# must be a string` — taking the WHOLE weekly derivation down over one row. The
# overrides.json side was hardened against exactly this class; this side is the
# same hazard from a less trustworthy writer.
def grouping_tags: ((((.categories // .theme_tags) // []) | arrays) // []) | map(select(strings));

def occurrences_for($entries; $cat):
  [$entries[]
   | select(.kind == "implementation")
   | select(.verdict == "imperfect" or .verdict == "blocked")
   | select(grouping_tags | any(slugify == $cat))
   | select(.merged_at != null and .merged_at != "")
   # Enrich each occurrence with its OWN free text so Stage B can cluster
   # sub-patterns from the on-disk pattern object without reopening every context
   # bundle (issue #893). Each new field is guarded at its own type boundary AND
   # carries a fallback: a bare `(.summary | strings)` yields the EMPTY STREAM on a
   # non-string, and an object-construction value that yields the empty stream
   # produces ZERO objects — the whole occurrence would vanish from occurrences[]
   # and occurrence_count would silently drop. The `// null` / `// []` fallbacks
   # (mirroring the fixed_at form used below) keep the element present with an
   # absent-value default. summary → null, descriptors → [], suggested_interventions
   # → [] on absent or wrong-typed.
   # `repo` is the record's OWN repository, and `pr_key` the canonical
   # "<owner>/<name>#<number>". A record that names none reports null rather than
   # the repository the derivation happens to run in: Stage B fetches each
   # occurrence's context from `repo`, so substituting the current one would fetch
   # a same-numbered PR that is different work.
   | {pr: .pr, repo: ((.repo | strings) // null), ts: .merged_at, verdict: .verdict,
      pr_key: (((.repo | strings) // null) as $r | if ($r == null or (.pr == null)) then null else ($r + "#" + (.pr|tostring)) end),
      summary: ((.summary | strings) // null),
      descriptors: ((.descriptors | arrays) // []),
      suggested_interventions: ((.suggested_interventions | arrays) // [])}]
  | sort_by(.ts);

def descriptors_for($entries; $cat):
  [$entries[]
   | select(.kind == "implementation")
   | select(.verdict == "imperfect" or .verdict == "blocked")
   | select(grouping_tags | any(slugify == $cat))
   # `arrays` guards a non-array descriptors (an LLM-authored corpus row can carry a
   # string or object here); an unguarded `(.descriptors // [])[]` aborts the whole
   # weekly derivation on `Cannot iterate over string` (issue #893).
   | (((.descriptors | arrays) // [])[])]
  # `select(. != null and . != "")` alone lets a non-string element (a number, an
  # object) through — neither null nor "" — into the category-level union. `strings`
  # narrows to string elements first, which also subsumes the null/"" exclusion.
  | map(select(. | strings | length > 0)) | unique;

def fixes_for($entries; $cat):
  [$entries[]
   | select(.kind == "audit")
   | select((.fixes_patterns // []) | any(slugify == $cat))
   | select(.merged_at != null and .merged_at != "")
   | {pr: .pr, repo: ((.repo | strings) // null), ts: .merged_at,
      pr_key: (((.repo | strings) // null) as $r | if ($r == null or (.pr == null)) then null else ($r + "#" + (.pr|tostring)) end)}]
  | sort_by(.ts);

# entry_of — compute one derived-view entry for an attribution category $cat and a
# lifecycle record $rec (an object, or null for a corpus-only category).
# $cost_by_pr maps a PR number (as a string key) to that PR's mean
# efficiency_runs[].iterations (issue #1828); a PR absent from it has no coverage.
def entry_of($entries; $dismissed; $cost_by_pr; $cat; $rec):
  occurrences_for($entries; $cat) as $occs
  | fixes_for($entries; $cat) as $fixes
  # Cost aggregate (issue #1828): the mean of the per-occurrence mean-iterations over
  # this pattern's occurrences THAT HAVE COVERAGE, plus the covered-occurrence count it
  # was computed from. An occurrence with no experiment-records coverage contributes
  # nothing (unknown is not zero), and a pattern with zero covered occurrences records
  # the absence as a null cost rather than a fabricated 0 — never derived from
  # post_bot_commits, only from efficiency_runs[].iterations.
  | ([ $occs[] | (.pr | numbers) as $pr | ($cost_by_pr[$pr | tostring]) | numbers ]) as $covered_costs
  | ($covered_costs | length) as $covered_n
  | (if $covered_n > 0 then (($covered_costs | add) / $covered_n) else null end) as $cost_mean
  # Fix-timestamp precedence: the lifecycle record's fixed_at when a record exists
  # (authoritative), else the legacy audit fix history.
  # `strings` is load-bearing: jq's `>` is a TOTAL order across types and never
  # errors, so a hand-edited non-string fixed_at does not fail — it silently
  # decides the regressed arm (`false` sorts below every timestamp and forces
  # `regressed`; a non-date string can pin an entry at `fixed` forever). Treat a
  # non-string as absent.
  | (if $rec != null then (($rec.fixed_at | strings) // null) else ((($fixes | last).ts | strings) // null) end) as $last_fix_ts
  | (($occs | last).ts // null) as $last_occ_ts
  | (if $rec != null then $rec.state else null end) as $rec_state
  | (
      if   ($dismissed | has($cat)) then "dismissed"
      elif $last_fix_ts != null and $last_occ_ts != null and $last_occ_ts > $last_fix_ts then "regressed"
      elif $rec_state == "declined" then "declined"
      elif $rec_state == "filed" then "filed"
      elif $rec_state == "fixed" then "fixed"
      elif ($rec == null and ($fixes | length) > 0) then "fixed"
      else "open"
      end
    ) as $status
  | {
      first_seen: (($occs | first).ts // null),
      last_seen:  $last_occ_ts,
      occurrence_count: ($occs | length),
      occurrences: $occs,
      descriptors: descriptors_for($entries; $cat),
      status: $status,
      fix_history: $fixes,
      category: $cat,
      cost_mean_iterations: $cost_mean,
      covered_occurrence_count: $covered_n
    };

. as $entries
| ($overrides[0] // {}) as $ov
# Canonicalize dismissed keys through slugify ONCE (issue #788): dismissed{} keys
# are category slugs by construction, and the status derivation tests an entry's
# attribution category (already slugified) against this set.
# Both maps are hand-corruptible: dismissed{} is human-owned by design, and a
# maintainer can edit overrides.json directly. Guard the SHAPE at the boundary --
# `objects` drops a non-object map, and the per-record `objects` below stops a
# non-object record from aborting the whole derivation. A wrong-shaped record is
# skipped, not fatal. `strings` on the key documents that a key reaching slugify's
# `ascii_downcase` is a string (JSON object keys are strings by construction).
| ((($ov.dismissed | objects) // {}) | to_entries | map(select(.key | strings)) | map({key:(.key|slugify), value:.value}) | from_entries) as $dismissed
# Lifecycle records: keep each record's OWN key (opaque, verbatim) and compute its
# attribution category = its stored `category` (a non-empty string) canonicalized
# through slugify, else the record's own key canonicalized. A non-object record is
# dropped at the boundary (same total-shape discipline as the dismissed map).
| ([ (($ov.patterns | objects) // {}) | to_entries[]
     | select(.key | strings)
     | .key as $k
     | (.value | objects) as $v
     | select($v != null)
     | { key: $k,
         rec: $v,
         category: ( ((($v.category // "") | strings) // "") as $c
                     | (if $c != "" then $c else $k end) | slugify ) } ]) as $records
# Per-PR cost index (issue #1828): map each PR to the mean of its experiment record's
# efficiency_runs[].iterations. `$experiments` is the slurped experiment-records.jsonl
# corpus (an array of records, or [] when the artifact is absent/empty). Every field is
# type-guarded so a hand-edited or agent-authored record — a non-object row, a non-number
# `pr`, a non-array `efficiency_runs`, a non-number `iterations` — is skipped rather than
# aborting the whole weekly derivation. A record with no numeric iterations yields no map
# entry, so its PR reads as uncovered (never a cost of 0).
| ([ $experiments[]? | objects
     | (.pr | numbers) as $pr
     | ([ (((.efficiency_runs // []) | arrays) // [])[] | objects | (.iterations | numbers) ]) as $iters
     | select(($iters | length) > 0)
     | {key: ($pr | tostring), value: (($iters | add) / ($iters | length))} ]
   | from_entries ) as $cost_by_pr
# The set of attribution categories some record claims — a corpus category in this
# set is suppressed (its occurrences are reported by the record's own entry).
| ([ $records[] | .category ] | unique) as $claimed
# Corpus categories drawn from occurrences, audit fix rows, and dismissed keys.
| ([
    ($entries[] | select(.kind == "implementation") | grouping_tags[] | slugify),
    ($entries[] | select(.kind == "audit") | (.fixes_patterns // [])[] | slugify),
    ($dismissed | keys[])
  ] | unique) as $corpus_cats
# Build record entries first (keyed by each record's own key CANONICALIZED through
# slugify — a no-op for a compose-produced or already-canonical key, and the
# preservation of the issue-#788 invariant that a non-canonical stored key surfaces
# under its canonical form rather than as a phantom), then add a corpus-category
# entry for every category NO record claims and whose slug does not already collide
# with a record key already emitted.
| (reduce $records[] as $r ({};
      . + { ($r.key | slugify): entry_of($entries; $dismissed; $cost_by_pr; $r.category; $r.rec) }
    )) as $with_records
| reduce ($corpus_cats[] | select(. as $x | ($claimed | index($x)) | not)) as $x ($with_records;
      if has($x) then .
      else . + { ($x): entry_of($entries; $dismissed; $cost_by_pr; $x; null) }
      end
  )

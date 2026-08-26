#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# extract-execution-shape.sh — read a claude-code-action execution file and emit a
# REDACTED shape record: which of a fixed set of telemetry fields it carries
# (present/absent/unavailable), its top-level encoding, and a redacted structural
# key→type set. A pure read-only diagnostic used by the repo-internal execution-file
# shape probe in .github/workflows/matcher-probe.yml (issue #437) and its unit tests.
# It NEVER changes the caller's pass/fail result and ALWAYS exits 0 — mirroring
# scripts/surface-execution-diagnostics.sh's best-effort, breadcrumb-on-degradation
# contract.
#
# WHY THIS EXISTS. Every telemetry floor PRFlow has built rests on an operand the
# agent must volunteer. Whether an agent-INDEPENDENT floor is possible turns on what
# the harness's own execution_file actually carries — a question the repo asserted
# ("the cost half is unreconstructable") but never measured. This helper is the
# measurement instrument: the probe job feeds a real cloud run's execution_file
# through it and uploads the redacted output as evidence, and the observed shape record
# records what was observed.
#
# REDACTION IS A SECURITY BOUNDARY, NOT A NICETY (issue #437 AC2). The execution file
# can carry prompt text, repository content, and attacker-controlled check-run names.
# So EVERY string leaf is redacted: the structural section emits each object's immediate
# key→TYPE pairs only (a string VALUE is rendered as the type token `string`, never its
# bytes), and no scalar value is ever printed. What ships to a maintainer's artifact
# download is the SHAPE (each object's immediate keys + value types), never the content.
# Scope note: redaction targets string *values* (the leaves that carry prompt/repo/
# check-run content in the observed claude-code-action schema). Object *keys* are the
# fixed schema field names, and in the observed schema no field places untrusted content
# in a key position — but that schema is NOT a contract, so keys are not simply trusted:
# each key is fail-closed filtered by `safekey` (see the jq pass below) and emitted
# verbatim ONLY if it is bounded-length (<=64) and identifier-shaped
# (`^[A-Za-z_][A-Za-z0-9_.-]*$`); anything else becomes the constant `<redacted-key>`, so
# an unrecognized key loses its NAME rather than leaking its CONTENT.
# ACCEPTED RESIDUAL (deliberate, not an oversight): a future single-token secret that is
# itself identifier-shaped and short (e.g. `sk_live_abc123`) would satisfy `safekey` and be
# emitted. Allow-listing known schema keys instead would fail closed on every genuinely NEW
# field — which is exactly what this probe exists to discover — so the record would go blind
# to schema growth. The length+charset cap is the chosen trade; re-evaluate it if a future
# action version ever places content in a key position.
#
# ENCODING TOLERANCE (issue #437 AC5). claude-code-action's execution_file schema is
# not a public contract, and scripts/surface-execution-diagnostics.sh / parse-engine-error.sh
# already tolerate three encodings. This helper RECORDS which one it observed —
# confirming or narrowing that tolerance — one of:
#   - array : a single top-level JSON array of stream events
#   - object: a single top-level JSON result object
#   - jsonl : one JSON object per line
#   - unavailable: the file is absent/empty/unparseable, OR its top level is a bare scalar
#                  (a number/string/bool/null is not an execution log, so no encoding is
#                  invented for it) — never conflated with "absent"
# Known ambiguity: a single-event JSONL file is byte-identical to a single top-level object
# and records `object`. Undecidable in the input, not a detector defect; field determinations
# are unaffected (the slurp normalizes all three), and lib/test/run.sh pins it.
#
# FIELD DETERMINATION (issue #437 AC3/AC4). For each field the record states one of:
#   - present     : observed in the parsed file
#   - absent      : the file parsed AND carried a result event, but the field was not seen
#   - unavailable : the field could not be established — the file is absent/empty/
#                   unparseable, OR carried no result event (an incomplete/aborted run).
# `absent` and `unavailable` are DELIBERATELY DISTINCT (the unknown-is-not-zero rule):
# a full run that simply lacks `usage` records `absent`; a run we could not read at all
# records `unavailable`. Neither is ever collapsed onto the other, and nothing is ever
# reported as `0`.
#
# Usage: extract-execution-shape.sh [EXECUTION_FILE]
#   EXECUTION_FILE  path to the claude-code-action execution log.
#
# $DEVFLOW_JQ overrides the `jq` binary (the same seam the rest of devflow uses;
# honored by the sourced resolver below).

set -uo pipefail

_EES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Guarded source (matches surface-execution-diagnostics.sh / the documented
# partial-copy posture — see CLAUDE.md): a deployment carrying this file without its
# sibling lib/resolve-jq.sh must degrade to bare `jq` with a breadcrumb, never leave
# DEVFLOW_JQ unbound and abort the next reference under `set -u`.
# shellcheck source=../lib/resolve-jq.sh
. "$_EES_DIR/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }
# Outcome check, not just sourceability: a sibling that sources clean yet never
# assigns must still leave a usable jq — never a bare `set -u` abort that breaks the
# always-exit-0 contract.
if [ -z "${DEVFLOW_JQ:-}" ]; then
  echo "devflow: resolve-jq.sh sourced but did not assign DEVFLOW_JQ — using bare 'jq' (set DEVFLOW_JQ to override)" >&2
  DEVFLOW_JQ=jq
fi

_HEADER="# Execution-file shape record"

# Emit an all-unavailable record (the degradation shape) and exit 0. $1 is a short
# reason surfaced both as a stderr breadcrumb (naming the file, so a renamed/removed
# execution_file output is attributable — the id-rename hazard) and in the record
# itself, so a downstream reader sees WHY every field is unavailable.
_emit_unavailable() {
  echo "devflow: extract-execution-shape: $1 — every field unavailable" >&2
  printf '%s\n' "$_HEADER"
  printf 'encoding: unavailable\n'
  printf 'usage: unavailable\n'
  printf 'wall_clock_timing: unavailable\n'
  printf 'tool_use: unavailable\n'
  printf 'subagent_type: unavailable\n'
  printf 'permission_denials: unavailable\n'
  printf 'permission_denials_commands: unavailable\n'
  printf '\n## Structural key-paths (redacted; string leaves shown as type only)\n'
  # The reason is interpolated bare — never behind an "execution file ..." prefix — so a
  # jq-side degradation is not grammatically blamed on the file in the emitted RECORD
  # (the artifact a future reader consults), matching the stderr attribution (PR #438
  # review); file-side reasons name the file themselves.
  printf '_(none — %s)_\n' "$1"
  exit 0
}

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ] || [ ! -s "$FILE" ]; then
  _emit_unavailable "execution file absent or empty ('$FILE')"
fi

# --- Encoding detection (AC5). Derive with the preflight-guaranteed jq + bash
# builtins ONLY: this value decides the emitted encoding line, so it must not depend
# on a non-preflight PATH tool (wc/head) that could be absent and silently mis-select
# (the guard-class-2 rule). `jq -c type` prints one type token per top-level JSON
# value: a single array/object → one line; JSONL → one line per object. Count the
# lines and read the first token with a builtin read loop, never `wc`/`head`.
# An unrunnable jq must be attributed to JQ, not to the file (issue #438 review): both
# fail the parse below, and a "file unparseable" breadcrumb about a fine file steers a
# debugger at the wrong artifact. Probe runnability first (network/auth-free), so each
# degradation names its actual cause. The emitted record is all-unavailable either way
# (fail-closed) — only the stderr attribution differs.
if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  _emit_unavailable "jq ('$DEVFLOW_JQ') is not runnable (set DEVFLOW_JQ to override)"
fi
ENC_TYPES="$("$DEVFLOW_JQ" -c 'type' "$FILE" 2>/dev/null)" || ENC_TYPES=""
if [ -z "$ENC_TYPES" ]; then
  # jq runs (probed above), so an empty parse is USUALLY a malformed file — but a jq that
  # passes --version can still die on this specific input (OOM/rlimit on a huge file, a
  # signal, a half-broken shim), so hedge the attribution instead of asserting the file is
  # at fault (PR #438 review; same hedge as the slurp-fail arm below).
  _emit_unavailable "could not be parsed as JSON ('$FILE') — malformed content, or a jq failure on this input"
fi
_n=0
_first=""
while IFS= read -r _t; do
  [ -z "$_t" ] && continue
  _n=$((_n + 1))
  [ "$_n" -eq 1 ] && _first="$_t"
done <<<"$ENC_TYPES"
if [ "$_n" -gt 1 ]; then
  ENCODING=jsonl
else
  case "$_first" in
    '"array"')  ENCODING=array ;;
    # STATED LIMITATION (issue #437 review): a single-event JSONL file is byte-for-byte
    # a single top-level object, so the two are genuinely INDISTINGUISHABLE here and both
    # record `encoding: object`. This is a real ambiguity in the input, not a defect in
    # the detector — and it is deliberately not papered over by guessing from a trailing
    # newline (which both shapes may carry). It is also harmless: the `-s` slurp below
    # normalizes array / object / JSONL into the same array, so every FIELD determination
    # is identical either way; only the recorded `encoding:` label is affected, and only
    # for a degenerate one-event run that no real probe produces. Pinned by
    # lib/test/run.sh so it stays a known, asserted limitation rather than a surprise.
    '"object"') ENCODING=object ;;
    # A single top-level scalar (number/string/bool/null) is not a valid execution
    # file — treat it as unavailable rather than inventing an encoding for it.
    *) _emit_unavailable "top-level is a scalar, not an execution log ('$FILE')" ;;
  esac
fi

# --- Field determination + redacted structural set, in one slurp-based jq pass.
# `-s` normalizes array / single-object / JSONL into one array; `[.. | objects]`
# reaches every object at any nesting depth (so a field carried in a nested `input`
# or a streamed message event is still seen regardless of encoding — the property the
# encodings test pins). The result event (`type=="result"`) is the completion gate:
# with none present the run is incomplete/aborted and every field is `unavailable`,
# never `absent`.
#
# REDACTION: the structural section maps every object's immediate keys to their VALUE
# TYPE only. A string value renders as the token `string` — its bytes never appear —
# so a seeded secret, a long prompt body, or a hostile check-run name (all string
# leaves) cannot survive into the output (AC2, asserted on emitted bytes downstream).
if ! BODY=$("$DEVFLOW_JQ" -rs '
    # The completion-gate + present/absent decision lives in ONE place: with no
    # result event the run is incomplete/aborted, so the field is `unavailable`
    # (never `absent`, never `0`); otherwise present/absent by observation. Folding
    # the gate into det() keeps the load-bearing absent-vs-unavailable distinction
    # single-sourced across all five fields.
    def det($hr; $b): if $hr then (if $b then "present" else "absent" end) else "unavailable" end;
    [.. | objects] as $objs
    | (any($objs[]; .type? == "result")) as $has_result
    | (any($objs[]; has("usage") and (.usage != null))) as $usage
    # Timing has FOUR observed carriers, not two. The shape record names duration_ms,
    # duration_api_ms, ttft_ms and end_time as evidence, so keying presence on the first
    # two alone would let a future action version that emits timing only via ttft_ms or
    # end_time be recorded as `wall_clock_timing: absent` — a definitive "not carried"
    # about a run that carried it. Accept any of the four (issue #437 review).
    | (any($objs[];
        (has("duration_ms") and (.duration_ms != null))
        or (has("duration_api_ms") and (.duration_api_ms != null))
        or (has("ttft_ms") and (.ttft_ms != null))
        or (has("end_time") and (.end_time != null)))) as $timing
    | (any($objs[]; .type? == "tool_use")) as $tooluse
    | (any($objs[]; has("subagent_type") and (.subagent_type != null))) as $subagent
    # permission_denials has TWO carriers, and reading only the array misreports the
    # other one. scripts/surface-execution-diagnostics.sh documents (issue #329) that
    # denial detail frequently degrades to COUNT-ONLY: `permission_denials_count` is
    # emitted while the array is absent. Keying presence on the array alone would then
    # record `absent` — a definitive "the harness does not carry this" — for a run that
    # demonstrably HAD denials, steering the shape record to the opposite of the truth in
    # the one field this probe exists to establish. So accept either carrier.
    #
    # The count arm is guarded `> 0` deliberately: a real `permission_denials_count: 0` is
    # a VALID-FALSY value meaning "the harness refused nothing", which is genuinely
    # `absent` — not evidence of the field being carried. Collapsing that onto `present`
    # would be the mirror-image error (the valid-falsy rule in CLAUDE.md).
    # NOTE: no ASCII apostrophes in this comment — it sits inside a bash single-quoted
    # jq program, where one would terminate the string (SC1011/SC1073).
    #
    # The count may arrive as a NUMBER or as a digit STRING. CLAUDE.md records that
    # permission_denials_count "publishes a digit string", so filtering on `numbers`
    # alone would drop the string carrier and record `absent` for a run that had
    # denials — the same wrong-direction misreport, one type over. Normalize both to a
    # number first; a non-digit string (the literal "unavailable") normalizes to null,
    # which is correctly NOT a presence signal.
    # Tri-state, not a boolean: a count carrier that is PRESENT but UNPARSEABLE (the literal
    # "unavailable", any non-digit string, or an explicit JSON null — which survives the
    # carrier collection but normalizes to null below) means the count was never established. Folding that
    # onto `absent` would assert "the harness does not carry denials" about a run whose denial
    # count we simply could not read — the unknown-is-not-zero rule, which is the rule this whole
    # helper exists to honor. So it resolves to `unavailable` instead.
    #
    # COMPLETION GATE FIRST (issue #438 review): the whole tri-branch below sits behind the
    # same $has_result gate every other field passes through. Without it, an aborted run
    # (no result event) that had streamed a denials array — or a positive count — would
    # report `present` while every sibling field reports `unavailable`, a divergence from
    # the helper contract stated above (no result event => EVERY field is unavailable).
    # The array carrier honors the valid-falsy rule like the count carrier (PR #438
    # review): an EMPTY permission_denials array is the natural shape of a completed
    # zero-denial run, so it is genuinely `absent` (refused nothing) — reading it as
    # `present` would have the two carriers disagree on the same real-world event
    # (count 0 => absent, [] => present) — and the same rule covers a FALSY SCALAR
    # carrier (0, an empty string, false), likewise a refused-nothing value. Only a
    # NON-EMPTY array (or a TRUTHY non-array, non-null value — an unknown future
    # carrier shape, kept as a presence signal rather than silently dropped)
    # asserts presence.
    | (if ($has_result | not) then "unavailable"
       elif (any($objs[]; has("permission_denials") and (.permission_denials != null)
                 and (if (.permission_denials | type) == "array" then (.permission_denials | length) > 0
                      else ((.permission_denials | if type == "string" then (tonumber? // .) else . end) as $pdv
                            | ($pdv != 0 and $pdv != "" and $pdv != false)) end)))
       then "present"
       else
         ([ $objs[] | select(has("permission_denials_count")) | .permission_denials_count ]) as $counts
         # $has_result is true on this branch, so a no-carrier file is genuinely `absent`.
         | if ($counts | length) == 0 then "absent"
           else
             ([ $counts[] | (if type == "string" then (tonumber? // null) else numbers end) ]
              | map(select(. != null))) as $nums
             | if   ($nums | length) == 0 then "unavailable"
               elif ($nums | max) > 0     then "present"
               else "absent" end
           end
       end) as $p
    # --- Denied-command emission (issue #805, Part 3). Derived INSIDE this pass, from the
    # same $objs and behind the same $has_result-gated $p the count line reports, for two
    # reasons a separate second jq pass got wrong.
    #
    # (1) UNKNOWN IS NOT ZERO. A pass with no completion gate publishes
    # `{"commands":[],"total":0}` for a run whose denials were never established — an
    # aborted run then emits `permission_denials: unavailable` on one line and `total: 0`
    # on the next (a self-contradicting record), and the COUNT-ONLY degradation documented
    # above (count carrier present, array absent — the frequent case) emits
    # `permission_denials: present` beside `total: 0`, a definitive "zero denied commands"
    # about a run that demonstrably had them. So the object is emitted ONLY when $p is a
    # positive observation backed by an actual array carrier; `unavailable` otherwise, and
    # the genuinely-zero `absent` case is the one that gets the empty object.
    #
    # (2) POSITION. The field is part of the header field block, immediately after the
    # count it qualifies, on EVERY arm — `_emit_unavailable` emits it there too. Appending
    # it after the structural-key-paths heading on the success arm only would put it in a
    # different record position on the two arms, so a consumer parsing the header block up
    # to the `##` heading would find it on `unavailable` runs and miss it on successful
    # ones, inverting the field purpose.
    #
    # SINGLE-LINE by construction: `tojson` escapes every newline, so no post-hoc
    # line-count check is needed to hold the $GITHUB_OUTPUT one-value contract.
    #
    # BOUNDS: a per-command LENGTH cap (500 chars) and a 40-ENTRY list cap — a length
    # budget and an item-count budget, not two size budgets — each with its own explicit
    # truncation marker.
    #   NO NEUTRALIZING CONSUMER SHIPS YET. The ::-workflow-command and fence-breaking-
    #   backtick neutralization and the fenced rendering are the RENDERING layer job, and
    #   the devflow-runner.yml producer + the auto-review check-run consumer that would
    #   perform them are NOT in the tree at this revision. So this field currently carries
    #   un-neutralized text, and any consumer added later MUST neutralize before rendering.
    #   Treat that as a precondition on the consumer, not a property of this output.
    #   NOTE the redaction consequence: the AC2 statement that every string leaf is
    #   dropped now has exactly this one disclosed exception.
    # NOTE: no ASCII apostrophes in this comment — it sits inside a bash single-quoted
    # jq program, where one would terminate the string (SC1011/SC1073).
    | (any($objs[]; (.permission_denials? | type) == "array")) as $has_denial_array
    | [ $objs[] | (.permission_denials? // empty)
        | select(type == "array") | .[]
        | (.tool_input.command? // .command? // empty)
        | select(type == "string")
        | if (length > 500) then (.[0:500] + " …[per-command-truncated]") else . end
      ] as $cmds
    # UNKNOWN IS NOT ZERO. A denials array that is non-empty but yields no extractable
    # command — the harness carrying the text under a field other than .tool_input.command
    # or .command, or under a non-string value — is an UNESTABLISHED extraction, not a
    # genuine zero. Emitting {total: 0} there would read as "the run denied nothing that
    # carried a command", steering a reader away from the real cause exactly as the
    # permission_denials_count collapse did. So that shape emits `unavailable`. A PARTIAL
    # extraction (some entries yield a command, some do not) is a disclosed residual: it
    # still emits the commands it could extract, and `total` counts those rather than the
    # array entries, so it under-reports rather than mis-reporting a zero.
    | ([ $objs[] | (.permission_denials? // empty)
         | select(type == "array") | .[] ] | length) as $denial_entries
    # SELF-CONTRADICTORY CARRIERS (PR #906 review). $p can read "present" off a positive
    # permission_denials_count while the array carrier is present but EMPTY (denial_entries
    # == 0) — the count says the harness refused something, the array says it recorded
    # nothing. That is not the natural zero-denial shape ($p would read "absent" there);
    # it is two carriers disagreeing about the same event, so the safe reading is
    # unestablished, the same posture as the count-collapse this helper already guards
    # against — never a genuine {total: 0}.
    | (if $p == "unavailable" then "unavailable"
       elif $p == "absent" then ({commands: [], total: 0, truncated: false} | tojson)
       elif ($has_denial_array | not) then "unavailable"
       elif ($denial_entries == 0) then "unavailable"
       elif ($cmds | length) == 0 then "unavailable"
       else ({ commands: ($cmds[0:40]),
               total: ($cmds | length),
               truncated: (($cmds | length) > 40) } | tojson)
       end) as $dc
    | det($has_result; $usage)    as $u
    | det($has_result; $timing)   as $w
    | det($has_result; $tooluse)  as $t
    | det($has_result; $subagent) as $s
    # KEY REDACTION — fail closed. Values are already reduced to their `type`, so the only
    # remaining channel by which untrusted bytes could reach the artifact is a KEY position.
    # The observed schema puts nothing untrusted in keys, but that schema is explicitly NOT a
    # public contract, so trusting it is the assumption this whole issue exists to stop making:
    # a future action version placing a tool result, a check-run name, or user content in a key
    # would walk straight through the AC2 redaction boundary. So a key is emitted verbatim ONLY
    # when it looks like a schema identifier — a bounded-length, conservative charset — and any
    # other key is replaced by the constant <redacted-key>. Fail-closed: an unrecognized key
    # loses its NAME (a shape record is slightly poorer) rather than leaking its CONTENT.
    | def safekey: if (type == "string") and (length <= 64) and test("^[A-Za-z_][A-Za-z0-9_.-]*$")
                   then . else "<redacted-key>" end;
      ( [ $objs[] | to_entries[] | "\(.key | safekey): \(.value | type)" ] | unique ) as $struct
    | [ "usage: \($u)",
        "wall_clock_timing: \($w)",
        "tool_use: \($t)",
        "subagent_type: \($s)",
        "permission_denials: \($p)",
        "permission_denials_commands: \($dc)",
        "",
        "## Structural key-paths (redacted; string leaves shown as type only)" ]
      + (if ($struct | length) > 0 then $struct else ["_(no object keys found)_"] end)
    | .[]
  ' "$FILE"); then
  # jq parsed the encoding probe above but failed the slurp pass (a truly pathological
  # shape, or an unrunnable jq surfacing only now). Fail closed to unavailable with a
  # breadcrumb naming the file — never emit a partial/misleading record.
  _emit_unavailable "jq slurp pass failed ('$FILE')"
fi

printf '%s\n' "$_HEADER"
printf 'encoding: %s\n' "$ENCODING"
printf '%s\n' "$BODY"
exit 0

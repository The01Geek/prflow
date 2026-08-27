# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable efficiency-trace + telemetry-persistence contract module.
#
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module. The module owns its private
# fixture root and its cleanup; it never invokes the runner or the full-suite
# boundary, references no monolith-private helper, and never self-skips. The
# inventory in efficiency-trace-telemetry.inventory.md maps the extracted
# coverage back to its former lib/test/run.sh locations.
#
# The `trap _et_module_cleanup EXIT` below relies on the sourcing contract both
# callers honour (module-harness.sh's full-suite boundary and run-module.sh
# source this file inside a ( ... ) subshell), so the trap fires at subshell exit
# and cannot clobber the runner's own EXIT handling.
#
# REPO_ROOT is spelled as the plain $LIB-relative assignment on purpose — see the
# MODULE-AUTHORING NOTE at the top of lib/test/module-harness.sh: the command
# substitution form silently makes every pin derived from it UNRESOLVED to
# lib/test/pin-corpus-lint.py.
REPO_ROOT="$LIB/.."

_et_module_tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-efficiency-trace.XXXXXX")" || {
  printf 'could not allocate efficiency-trace-telemetry fixture\n' >&2
  return 1
}
_et_module_cleanup() {
  rm -rf "$_et_module_tmp_root"
}
trap _et_module_cleanup EXIT

# ── Skill bundles the moved pins target (rebuilt, never inherited) ────────────
# lib/test/run.sh assembles $REVIEW_BUNDLE and $MAXI_BUNDLE in its preamble, and
# the moved assertions below pin engine content against those concatenations
# (a sentence may live in the thin root or in any one reference, so the pin
# targets the whole shipped bundle). A module cannot inherit a monolith global,
# so both are rebuilt here through the shared fail-closed builder
# devflow_module_build_bundle — a missing, empty, or unreadable member lands in
# the tally as a named RED assertion instead of silently shrinking the bundle
# and turning every absence/count pin vacuous. The `.md` suffix is load-bearing:
# lib/test/pin-corpus-lint.py infers markdown comment syntax from it.
#
# Membership mirrors run.sh's own member sets. The review engine is the thin root
# plus every phase reference (the six default-path phases and the three
# predicate-gated ones); review-and-fix is the thin root plus every reference.
# Both are derived from the shipped tree by glob rather than transcribed, so a
# reference added to either engine joins the bundle without a lockstep edit here.
REVIEW_BUNDLE="$_et_module_tmp_root/review-engine-bundle.md"
_et_review_members=("$REPO_ROOT/skills/review/SKILL.md")
for _et_member in "$REPO_ROOT/skills/review/phases"/*.md; do
  _et_review_members+=("$_et_member")
done
devflow_module_build_bundle "efficiency-trace module: review-engine bundle" \
  "$REVIEW_BUNDLE" "${_et_review_members[@]}"
ST_REV="$REVIEW_BUNDLE"

MAXI_BUNDLE="$_et_module_tmp_root/review-and-fix-bundle.md"
_et_maxi_members=("$REPO_ROOT/skills/review-and-fix/SKILL.md")
for _et_member in "$REPO_ROOT/skills/review-and-fix/references"/*.md; do
  _et_maxi_members+=("$_et_member")
done
devflow_module_build_bundle "efficiency-trace module: review-and-fix bundle" \
  "$MAXI_BUNDLE" "${_et_maxi_members[@]}"
MAXI_SKILL="$MAXI_BUNDLE"
unset _et_member

# ────────────────────────────────────────────────────────────────────────────
echo "efficiency-trace.jq / efficiency-trace.sh"
# ────────────────────────────────────────────────────────────────────────────
# Per-run subagent effectiveness telemetry for /devflow:review-and-fix.
# Derivation is mechanical (jq); the wrapper validates inputs, reads the gating
# flag, and dispatches per mode. Fixtures exercise: 4-way verdict derivation,
# the per-iteration marginal-yield line, flag-off → no writes, and graceful
# degradation when phase3_dispatched is absent.
ET_DIR="$(mktemp -d)"
# Iter 1: a unique-effective applied finding (corroboration 1), a corroborating
# applied finding (corroboration 2), one dispatched-but-silent agent (null), and
# a mix of lite/agent checklist items. 4 fixes applied.
cat > "$ET_DIR/iter-1.json" <<'EOF'
{
  "iter": 1,
  "checklist": [
    {"id":"VC-1","verification_mode":"lite","verdict":"PASS"},
    {"id":"VC-2","verification_mode":"lite","verdict":"FAIL"},
    {"id":"VC-3","verification_mode":"agent","verdict":"PASS"}
  ],
  "phase3_dispatched": ["devflow:code-reviewer","devflow:silent-failure-hunter","devflow:comment-analyzer"],
  "phase3_findings": [
    {"agent":"devflow:code-reviewer","corroboration_count":1,"fix_decision":"applied"},
    {"agent":"devflow:silent-failure-hunter","corroboration_count":2,"fix_decision":"applied"}
  ],
  "convergence_inputs": {"fixes_applied": 4},
  "telemetry": {"phase_3": {"calls": 3, "tokens": 48000, "wall_clock_s": 180}}
}
EOF
# Iter 2: zero fixes (marginal-yield), one pushed-back finding (noise), one
# dispatched-but-silent agent (null).
cat > "$ET_DIR/iter-2.json" <<'EOF'
{
  "iter": 2,
  "checklist": [],
  "phase3_dispatched": ["devflow:code-reviewer","devflow:comment-analyzer"],
  "phase3_findings": [
    {"agent":"devflow:code-reviewer","corroboration_count":1,"fix_decision":"pushed_back"}
  ],
  "convergence_inputs": {"fixes_applied": 0},
  "telemetry": {"phase_3": {"calls": 2, "tokens": 12000, "wall_clock_s": 60}}
}
EOF

# ── #431 compute_config_fingerprint's interpreter-vs-crash arm SELECTION ───────
# A branch-selecting `case` is not covered by a grep-pin on one of its message literals
# (CLAUDE.md's describe-denial-count.sh precedent): dropping `126|` from the pattern, or
# reordering the arms, would restore the exact mis-steer the discrimination exists to
# eliminate while the suite stayed green. Drive all three arms by shadowing `python3` on
# PATH. 127 = not found; 126 = found but NOT EXECUTABLE (a broken WSL shim, a noexec
# mount) — both mean the script never ran, so both must name the interpreter, never
# "config_fingerprint.py crashed"; any other rc IS a genuine helper crash.
CFPA_D="$(mktemp -d)"
mkdir -p "$CFPA_D/empty" "$CFPA_D/bin126"
# Resolve bash ABSOLUTELY before clobbering PATH — otherwise the probe shell itself is not
# findable and the probe reports "command not found" instead of the interpreter rc it exists
# to measure (a self-inflicted false operand; the probe must run under the artifact's own
# shell, per the repo's interpreter-faithful-probe rule).
CFPA_BASH="$(command -v bash)"
# rc 127 (absent): a PATH with no python3 at all.
CFPA_127="$(PATH="$CFPA_D/empty" "$CFPA_BASH" -c '
  out="$(python3 --version 2>/dev/null)" || rc=$?
  case "${rc:-0}" in 126|127) echo interpreter ;; 0) echo ok ;; *) echo crash ;; esac' 2>/dev/null)"
assert_eq "#431 cfp-arm: an ABSENT python3 yields rc 127 (the interpreter arm's operand)" "interpreter" "$CFPA_127"
# rc 126 (present but not executable): a python3 that exists and is chmod -x.
printf '#!/usr/bin/env bash\nexit 0\n' > "$CFPA_D/bin126/python3"
chmod -x "$CFPA_D/bin126/python3"
CFPA_126="$(PATH="$CFPA_D/bin126" "$CFPA_BASH" -c '
  out="$(python3 /dev/null 2>/dev/null)" || rc=$?
  case "${rc:-0}" in 126|127) echo interpreter ;; 0) echo ok ;; *) echo crash ;; esac' 2>/dev/null)"
assert_eq "#431 cfp-arm: a NON-EXECUTABLE python3 yields rc 126 — also the interpreter arm, never 'crashed'" "interpreter" "$CFPA_126"
# Arm-order/selection pin: the shipped `case` must route BOTH 126 and 127 to the
# interpreter message and everything else to the crash message. Assert on the real source.
assert_eq "#431 cfp-arm: the shipped selector routes 126 AND 127 to the interpreter arm" "yes" \
  "$(grep -qE '^[[:space:]]*126\|127\)' "$LIB/efficiency-trace.sh" && echo yes || echo no)"
rm -rf "$CFPA_D"

ET_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode record)"
ET_verdict() { echo "$ET_REC" | jq -r --argjson i "$1" --arg a "$2" '.per_iteration[] | select(.iter==$i) | .agent_verdicts[] | select(.agent==$a) | .verdict'; }
assert_eq "et: applied + corroboration<2 → unique-effective" "unique-effective" "$(ET_verdict 1 'devflow:code-reviewer')"
assert_eq "et: applied + corroboration>=2 → corroborating"   "corroborating"    "$(ET_verdict 1 'devflow:silent-failure-hunter')"
assert_eq "et: dispatched but silent → null"                 "null"             "$(ET_verdict 1 'devflow:comment-analyzer')"
assert_eq "et: only pushed_back finding → noise"             "noise"            "$(ET_verdict 2 'devflow:code-reviewer')"
assert_eq "et: roster-minus-findings null on a LATER iteration" "null"          "$(ET_verdict 2 'devflow:comment-analyzer')"
# The silent-agent verdict must be JSON null, not the string "null" — so a
# cross-run analyzer can use idiomatic `select(.verdict == null)`. `jq -r`
# renders both as "null", so assert the JSON type explicitly.
ET_verdict_type() { echo "$ET_REC" | jq -r --argjson i "$1" --arg a "$2" '.per_iteration[] | select(.iter==$i) | .agent_verdicts[] | select(.agent==$a) | .verdict | type'; }
assert_eq "et: silent-agent verdict is JSON null, not string" "null" "$(ET_verdict_type 1 'devflow:comment-analyzer')"
assert_eq "et: record carries cost telemetry forward (iter1 phase_3 tokens)" "48000" \
  "$(echo "$ET_REC" | jq -r '.telemetry[] | select(.iter==1) | .phases.phase_3.tokens')"
assert_eq "et: record schema_version=1" "1" "$(echo "$ET_REC" | jq -r '.schema_version')"
# #431 config_fingerprint — the PRODUCER half, exercised end-to-end rather than grep-pinned.
# The value flows through "$_DEVFLOW_CONFIG" (owned by lib/config-source.sh). If that variable
# is ever renamed, unset, or emptied, config_fingerprint.py prints `null`, emit_jq cheerfully
# --argjson's it, every source pin stays GREEN, and every future run stores a null fingerprint —
# silently destroying the config-attribution axis the whole experiment record exists for. Assert
# the emitted record actually carries a real fingerprint (issue #431 review).
assert_eq "#431 et: --mode record stamps a REAL config_fingerprint.sha256 (not null)" "yes" \
  "$(echo "$ET_REC" | jq -r 'if (.config_fingerprint.sha256 // "") | test("^[0-9a-f]{64}$") then "yes" else "no" end')"
# Assert a REAL salient key/value, not merely that a dict exists: `type == "object"` is
# satisfied by an empty {}, so a mutant deleting the SALIENT_KEYS extraction loop would keep
# this green while the values it names are gone (issue #431 shadow).
assert_eq "#431 et: the stamped fingerprint carries the salient config values VERBATIM" "yes" \
  "$(echo "$ET_REC" | jq -r 'if (.config_fingerprint.salient | type) == "object"
       and ((.config_fingerprint.salient | keys | length) > 0)
       and (.config_fingerprint.salient.max_iterations != null)
     then "yes" else "no" end')"
assert_eq "et: cut_candidate_min_dispatch carried into record (default 3)" "3" \
  "$(echo "$ET_REC" | jq -r '.cut_candidate_min_dispatch')"
assert_eq "et: checklist split lite=2" "2" "$(echo "$ET_REC" | jq -r '.per_iteration[] | select(.iter==1) | .checklist_lite_count')"
assert_eq "et: checklist split agent=1" "1" "$(echo "$ET_REC" | jq -r '.per_iteration[] | select(.iter==1) | .checklist_agent_count')"

# ── Per-agent disposition decomposing the null residual (issue #1849) ─────────
# The null verdict collapsed opposite states (silent / failed / all-deferred). The
# producer now emits a per-agent `disposition` (returned | failed | silent |
# unestablished) and a `fix_decisions` roll-up beside the derived verdict, computed
# only over an established roster. Operands: the new unconditional `phase3_failed_agents`
# array (AC5 sink) unioned with the shadow block's `per_reviewer_assessment`
# lost reviewers (AC4). Each expected value is written literally.
ET_DISP="$(mktemp -d)"
# iter-1: roster a,b,c,d; phase3_failed_agents names d. a applied (returned), b
# deferred-only (returned, verdict null, roll-up ["deferred"] — distinguishable
# from silence), c dispatched-silent (silent), d failed.
cat > "$ET_DISP/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a","b","c","d"],"phase3_failed_agents":["d"],
"phase3_findings":[
  {"agent":"a","corroboration_count":1,"fix_decision":"applied"},
  {"agent":"b","corroboration_count":1,"fix_decision":"deferred"}
],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-2: historical arm (AC7) — phase3_failed_agents ABSENT. e is dispatched-silent
# but its failed-vs-silent split is unestablished, never mapped onto "silent".
cat > "$ET_DISP/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a","e"],
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-3: roster-unestablished arm (AC3) — phase3_dispatched ABSENT. a is
# establishable from findings (returned); no silent agent is invented.
cat > "$ET_DISP/iter-3.json" <<'EOF'
{"iter":3,"phase3_failed_agents":[],
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-4: AC4 — the shadow per-reviewer assessment feeds the disposition. f is
# dispatched, absent from findings, and marked returned:false by the shadow join → failed.
cat > "$ET_DISP/iter-4.json" <<'EOF'
{"iter":4,"phase3_dispatched":["a","f"],
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"full","per_reviewer_assessment":[{"agent":"f","returned":false},{"agent":"a","returned":true}]},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-5: per-agent establishment — the two failed-set channels cover different
# agent populations. phase3_failed_agents is MALFORMED (object) while the shadow
# assessment is a well-formed array covering only g. g is decidable (failed); h is
# dispatched, silent, and covered by NEITHER authoritative channel → unestablished,
# never silent (the residual-collapse this change exists to prevent).
cat > "$ET_DISP/iter-5.json" <<'EOF'
{"iter":5,"phase3_dispatched":["a","g","h","i"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"full","per_reviewer_assessment":[{"agent":"g","returned":false},{"agent":"i","returned":true}]},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-6: the shadow channel is authoritative only on a full-coverage block. On a
# not_verified block the per_reviewer_assessment is a partial pre-shortfall capture,
# so it decides nothing — j (listed returned:false) and k (dispatched, silent, no
# direct sink) both read unestablished, never failed/silent.
cat > "$ET_DISP/iter-6.json" <<'EOF'
{"iter":6,"phase3_dispatched":["a","j","k"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"not_verified","per_reviewer_assessment":[{"agent":"j","returned":false}]},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-7..9: the shadow per_reviewer_assessment is agent-mutable, so malformed shapes
# must never abort the filter and must decide nothing (the agent falls back to
# unestablished). iter-7 assessment is an object; iter-8 a scalar; iter-9 mixes a
# malformed entry (non-boolean returned) beside a valid one on a full-coverage block.
cat > "$ET_DISP/iter-7.json" <<'EOF'
{"iter":7,"phase3_dispatched":["a","m"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"full","per_reviewer_assessment":{}},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_DISP/iter-8.json" <<'EOF'
{"iter":8,"phase3_dispatched":["a","m"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"full","per_reviewer_assessment":"nope"},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_DISP/iter-9.json" <<'EOF'
{"iter":9,"phase3_dispatched":["a","n","p"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"coverage":"full","per_reviewer_assessment":[{"agent":"n","returned":"yes"},{"agent":"p","returned":false}]},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-10: empty-array "none failed" establishment (issue #1849 shadow review). A
# well-formed empty phase3_failed_agents:[] with the roster present IS a valid
# establishment ("no agent failed"), so a dispatched agent absent from findings reads
# silent — distinct from iter-1's non-empty ["d"] sink. Guards a regression that would
# require length>0 for establishment and silently flip this common case to unestablished.
cat > "$ET_DISP/iter-10.json" <<'EOF'
{"iter":10,"phase3_dispatched":["a","q"],"phase3_failed_agents":[],
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-11: the fix_decisions roll-up is sorted-unique over STRING values only. An
# agent-mutable non-string fix_decision must be dropped by the `strings` guard rather
# than reaching `unique` and aborting the whole filter.
cat > "$ET_DISP/iter-11.json" <<'EOF'
{"iter":11,"phase3_dispatched":["r"],"phase3_failed_agents":[],
"phase3_findings":[
  {"agent":"r","corroboration_count":1,"fix_decision":"deferred"},
  {"agent":"r","corroboration_count":1,"fix_decision":"applied"},
  {"agent":"r","corroboration_count":1,"fix_decision":7}
],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-12: the shadow channel is gated on `coverage == "full"`, so a block with NO
# coverage key decides nothing — s reads unestablished, never failed.
cat > "$ET_DISP/iter-12.json" <<'EOF'
{"iter":12,"phase3_dispatched":["a","s"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":{"per_reviewer_assessment":[{"agent":"s","returned":false}]},
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-13: the whole shadow block is agent-mutable — a scalar must not abort the
# filter and must establish nothing.
cat > "$ET_DISP/iter-13.json" <<'EOF'
{"iter":13,"phase3_dispatched":["a","t"],"phase3_failed_agents":{},
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"shadow":"nope",
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_DISP_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DISP" --slug pr-1849 --mode record)"
ET_disp() { echo "$ET_DISP_REC" | jq -r --argjson i "$1" --arg a "$2" '.per_iteration[] | select(.iter==$i) | .agent_verdicts[] | select(.agent==$a) | .disposition'; }
ET_roll() { echo "$ET_DISP_REC" | jq -c --argjson i "$1" --arg a "$2" '.per_iteration[] | select(.iter==$i) | .agent_verdicts[] | select(.agent==$a) | .fix_decisions'; }
assert_eq "et(#1849): agent with findings → returned disposition"                 "returned"      "$(ET_disp 1 'a')"
assert_eq "et(#1849): deferred-only agent → returned disposition"                 "returned"      "$(ET_disp 1 'b')"
assert_eq "et(#1849): deferred-only agent verdict is still JSON null"             "null" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==1) | .agent_verdicts[] | select(.agent=="b") | .verdict | type')"
assert_eq "et(#1849/AC2): fix_decision roll-up distinguishes all-deferred from silence" '["deferred"]' "$(ET_roll 1 'b')"
assert_eq "et(#1849): dispatched-silent agent (failed set present, unnamed) → silent" "silent"    "$(ET_disp 1 'c')"
assert_eq "et(#1849): silent agent roll-up is empty (no findings)"                '[]'            "$(ET_roll 1 'c')"
assert_eq "et(#1849/AC5): agent in phase3_failed_agents → failed disposition"     "failed"        "$(ET_disp 1 'd')"
assert_eq "et(#1849/AC7): historical iter (failed field absent) silent agent → unestablished" "unestablished" "$(ET_disp 2 'e')"
assert_eq "et(#1849): returned agent establishable without the failed field"      "returned"      "$(ET_disp 2 'a')"
assert_eq "et(#1849/AC3): roster-absent iter carries phase3_dispatched_present=false" "false" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==3) | .phase3_dispatched_present')"
assert_eq "et(#1849/AC3): roster-absent iter — returned agent still returned"      "returned"     "$(ET_disp 3 'a')"
assert_eq "et(#1849/AC3): roster-absent iter invents no silent/failed agent"       "0" \
  "$(echo "$ET_DISP_REC" | jq -r '[.per_iteration[] | select(.iter==3) | .agent_verdicts[] | select(.disposition=="silent" or .disposition=="failed")] | length')"
assert_eq "et(#1849/AC4): shadow per_reviewer_assessment lost reviewer → failed"  "failed"        "$(ET_disp 4 'f')"
assert_eq "et(#1849): per-agent establishment — assessment-covered lost reviewer → failed" "failed" "$(ET_disp 5 'g')"
assert_eq "et(#1849): per-agent establishment — silent agent neither channel covers → unestablished (not silent)" "unestablished" "$(ET_disp 5 'h')"
# The shadow-channel SILENT arm: an agent the assessment lists returned:true, absent
# from findings, with no direct sink → silent (established by the assessment). Guards
# against narrowing $assess_covered to returned==false, which would re-collapse this
# common case to unestablished — the exact distinction #1849 preserves.
assert_eq "et(#1849): assessment returned:true agent, not in findings → silent (established via shadow channel)" "silent" "$(ET_disp 5 'i')"
# Coverage gate: on a not_verified shadow block the assessment decides nothing.
assert_eq "et(#1849): not_verified shadow — assessment returned:false agent → unestablished (partial capture ignored)" "unestablished" "$(ET_disp 6 'j')"
assert_eq "et(#1849): not_verified shadow — uncovered silent agent → unestablished" "unestablished" "$(ET_disp 6 'k')"
# Malformed shadow per_reviewer_assessment must decide nothing and never abort.
assert_eq "et(#1849): object per_reviewer_assessment → silent agent unestablished" "unestablished" "$(ET_disp 7 'm')"
assert_eq "et(#1849): scalar per_reviewer_assessment → silent agent unestablished" "unestablished" "$(ET_disp 8 'm')"
assert_eq "et(#1849): malformed assessment entry (non-boolean returned) → uncovered agent unestablished" "unestablished" "$(ET_disp 9 'n')"
assert_eq "et(#1849): valid entry beside a malformed one still decides → failed" "failed" "$(ET_disp 9 'p')"
assert_eq "et(#1849): phase3_failed_agents_present carried into record (present iter)" "true" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==1) | .phase3_failed_agents_present')"
assert_eq "et(#1849/AC7): phase3_failed_agents_present false on historical iter"   "false" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==2) | .phase3_failed_agents_present')"
# Empty-array establishment: [] with roster present is a valid "none failed" set, so a
# silent agent reads silent (not unestablished) and the presence flag reads true.
assert_eq "et(#1849): empty [] failed-set with roster present → silent agent silent" "silent" "$(ET_disp 10 'q')"
assert_eq "et(#1849): empty [] failed-set establishes → phase3_failed_agents_present true" "true" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==10) | .phase3_failed_agents_present')"
# The presence flag reports the direct sink only. iter-4 carries a full-coverage shadow
# assessment and NO phase3_failed_agents, so a regression wiring the flag to shadow
# coverage would read true here and misreport a historical record as establishing.
assert_eq "et(#1849): phase3_failed_agents_present is shadow-independent (assessment present, sink absent)" "false" \
  "$(echo "$ET_DISP_REC" | jq -r '.per_iteration[] | select(.iter==4) | .phase3_failed_agents_present')"
# fix_decisions roll-up: sorted-unique across multiple values, non-string dropped.
assert_eq "et(#1849): fix_decisions roll-up is sorted-unique across multiple values" '["applied","deferred"]' "$(ET_roll 11 'r')"
assert_eq "et(#1849): non-string fix_decision dropped by the strings guard (filter does not abort)" "returned" "$(ET_disp 11 'r')"
# Shadow-block shape adversarials: missing coverage key, and a scalar shadow block.
assert_eq "et(#1849): shadow block with no coverage key → assessment decides nothing" "unestablished" "$(ET_disp 12 's')"
assert_eq "et(#1849): scalar shadow block → silent agent unestablished (no abort)" "unestablished" "$(ET_disp 13 't')"

# Adversarial phase3_failed_agents shapes (agent-mutable input): the filter must
# never abort, and a non-array value must not establish the failed set — a silent
# agent then reads unestablished, never silently "silent".
ET_ADV="$(mktemp -d)"
cat > "$ET_ADV/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a","z"],"phase3_failed_agents":{},"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a","z"],"phase3_failed_agents":"z","phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-3.json" <<'EOF'
{"iter":3,"phase3_dispatched":["a","z"],"phase3_failed_agents":false,"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-4.json" <<'EOF'
{"iter":4,"phase3_dispatched":["a","z"],"phase3_failed_agents":0,"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-5.json" <<'EOF'
{"iter":5,"phase3_dispatched":["a","z"],"phase3_failed_agents":"","phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-6.json" <<'EOF'
{"iter":6,"phase3_dispatched":["a","z"],"phase3_failed_agents":7,"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-7,8: present-but-malformed-ELEMENT arrays (issue #1849 review). The container is
# a well-formed array, so a container-type-only check (== "array") reads it as a total
# establishment — but its elements establish nothing. iter-7 is all-object; iter-8 mixes
# a named string with a junk number, proving establishment fails CLOSED even when a real
# agent is named. In both, silent agent z must read unestablished, never silent.
cat > "$ET_ADV/iter-7.json" <<'EOF'
{"iter":7,"phase3_dispatched":["a","z"],"phase3_failed_agents":[{"agent":"z"}],"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_ADV/iter-8.json" <<'EOF'
{"iter":8,"phase3_dispatched":["a","z"],"phase3_failed_agents":["z",7],"phase3_findings":[{"agent":"a","fix_decision":"applied","corroboration_count":1}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_ADV_RC=0; ET_ADV_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_ADV" --slug pr-adv --mode record)" || ET_ADV_RC=$?
assert_eq "et(#1849 adversarial): malformed phase3_failed_agents never aborts the filter (exit 0)" "0" "$ET_ADV_RC"
assert_eq "et(#1849 adversarial): all eight malformed shapes still produce iteration records" "8" \
  "$(echo "$ET_ADV_REC" | jq -r '.iterations')"
assert_eq "et(#1849 adversarial): object failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==1) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): scalar-string failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==2) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): valid-falsy (false) failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==3) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
# Every malformed shape must land in the unestablished arm, not merely produce a
# record — the issue requires each shape to land in a specific arm (a silent-agent
# coercion regression would otherwise stay green).
assert_eq "et(#1849 adversarial): valid-falsy (0) failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==4) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): valid-falsy (empty string) failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==5) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): scalar-number (7) failed field → silent agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==6) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
# Present-but-malformed-element array: container is an array yet establishes nothing.
assert_eq "et(#1849 adversarial): all-object element array → silent agent unestablished (not silent)" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==7) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): all-object element array → phase3_failed_agents_present false" "false" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==7) | .phase3_failed_agents_present')"
assert_eq "et(#1849 adversarial): mixed string+number element array fails closed → named agent unestablished" "unestablished" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==8) | .agent_verdicts[] | select(.agent=="z") | .disposition')"
assert_eq "et(#1849 adversarial): mixed-element array → phase3_failed_agents_present false" "false" \
  "$(echo "$ET_ADV_REC" | jq -r '.per_iteration[] | select(.iter==8) | .phase3_failed_agents_present')"
rm -rf "$ET_DISP" "$ET_ADV"

# diff_profile + verification posture: the Phase 0.5 classification is carried
# into the record (so the cross-run analyzer can segment by diff shape), and the
# orchestrator's no-subagent cost decision is logged as an explicit posture
# rather than a bare "0 verifiers".
ET_PROF="$(mktemp -d)"
# iter-1: engine_self_modifying diff, verification done via lite probes only (no agents).
cat > "$ET_PROF/iter-1.json" <<'EOF'
{"iter":1,"diff_profile":{"small_diff":false,"config_only":false,"has_new_types":false,"engine_self_modifying":true,"checklist_skipped":null},
"checklist":[{"verification_mode":"lite","verdict":"PASS"},{"verification_mode":"lite","verdict":"PASS"}],
"phase3_dispatched":["devflow:code-reviewer"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
# iter-2: small_diff+config_only, Phase 0.5 intentionally skipped the checklist.
cat > "$ET_PROF/iter-2.json" <<'EOF'
{"iter":2,"diff_profile":{"small_diff":true,"config_only":true,"has_new_types":false,"engine_self_modifying":false,"checklist_skipped":"intentional"},
"checklist":[],"phase3_dispatched":["devflow:code-reviewer"],
"phase3_findings":[{"agent":"devflow:code-reviewer","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
# iter-3 (issue #1071, documentary — NOT a RED-first fixture): the flag combination the
# widened engine_self_modifying predicate makes COMMON — engine_self_modifying set ALONGSIDE
# small_diff AND config_only. This tuple is a one-file, sub-100-line prompt-extension or
# CLAUDE.md edit: .md is in the config_only extension set and the diff is small, yet the
# path is now engine-surface, so checklist_skipped stays null (the override wins) and the
# checklist RAN. The record is path-agnostic (diff_profile carries flags, not paths), so this
# documents the combination rather than exercising a new path — the emitter is unchanged.
cat > "$ET_PROF/iter-3.json" <<'EOF'
{"iter":3,"diff_profile":{"small_diff":true,"config_only":true,"has_new_types":false,"engine_self_modifying":true,"checklist_skipped":null},
"checklist":[{"verification_mode":"lite","verdict":"PASS"}],"phase3_dispatched":["devflow:code-reviewer"],
"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
ET_PROF_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_PROF" --slug pr-15 --mode record)"
assert_eq "et: diff_profile carried into record (engine_self_modifying)" "true" \
  "$(echo "$ET_PROF_REC" | jq -r '.per_iteration[] | select(.iter==1) | .diff_profile.engine_self_modifying')"
assert_eq "et: lite-only verification posture (no subagents dispatched)" "lite-only" \
  "$(echo "$ET_PROF_REC" | jq -r '.per_iteration[] | select(.iter==1) | .verification_posture')"
assert_eq "et: Phase 0.5 intentional skip → skipped-intentional posture" "skipped-intentional" \
  "$(echo "$ET_PROF_REC" | jq -r '.per_iteration[] | select(.iter==2) | .verification_posture')"
# #1071 documentary: engine_self_modifying + small_diff + config_only carried together, and the
# override kept the checklist ON (checklist_skipped null → posture is NOT skipped-intentional).
assert_eq "et: engine_self_modifying overrides small_diff+config_only skip (checklist ran)" "true" \
  "$(echo "$ET_PROF_REC" | jq -r '.per_iteration[] | select(.iter==3) | (.diff_profile.engine_self_modifying and .diff_profile.small_diff and .diff_profile.config_only and (.diff_profile.checklist_skipped==null))')"
ET_PROF_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_PROF" --slug pr-15 --mode trace)"
assert_eq "et: trace logs the no-subagent decision (lite-only line)" "true" \
  "$(echo "$ET_PROF_TRACE" | grep -q 'without dispatching verifier subagents' && echo true || echo false)"
assert_eq "et: trace logs intentional Phase 0.5 skip" "true" \
  "$(echo "$ET_PROF_TRACE" | grep -q 'skipped by Phase 0.5' && echo true || echo false)"
assert_eq "et: trace renders diff profile line" "true" \
  "$(echo "$ET_PROF_TRACE" | grep -q 'Diff profile: engine_self_modifying' && echo true || echo false)"
# Absent diff_profile degrades gracefully: posture falls back to raw counts, label "not recorded".
ET_NOPROF="$(mktemp -d)"
cat > "$ET_NOPROF/iter-1.json" <<'EOF'
{"iter":1,"checklist":[{"verification_mode":"agent","verdict":"PASS"}],"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
ET_NOPROF_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_NOPROF" --slug s --mode record)"
assert_eq "et: absent diff_profile → null in record" "null" \
  "$(echo "$ET_NOPROF_REC" | jq -r '.per_iteration[0].diff_profile')"
assert_eq "et: absent diff_profile → posture from raw counts (agent-only)" "agent-only" \
  "$(echo "$ET_NOPROF_REC" | jq -r '.per_iteration[0].verification_posture')"
rm -rf "$ET_PROF" "$ET_NOPROF"

# ── Recurring defect kinds across iterations (issue #1903) ───────────────────
# A recurring kind is a defect_signature.kind appearing in the phase3_findings
# of three separate iterations. Each expected value is written literally, never
# derived from the filter's own logic.
ET_REC1903="$(mktemp -d)"
cat > "$ET_REC1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[
  {"agent":"a","fix_decision":"applied","defect_signature":{"kind":"text-matching"}},
  {"agent":"a","fix_decision":"applied","defect_signature":{"kind":"pair-in-two"}}
],"convergence_inputs":{"fixes_applied":2},"telemetry":null}
EOF
cat > "$ET_REC1903/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[
  {"agent":"a","fix_decision":"pushed_back","defect_signature":{"kind":"text-matching"}},
  {"agent":"a","fix_decision":"applied","defect_signature":{"kind":"pair-in-two"}}
],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_REC1903/iter-3.json" <<'EOF'
{"iter":3,"phase3_dispatched":["a"],"phase3_findings":[
  {"agent":"a","fix_decision":"applied","defect_signature":{"kind":"text-matching"}},
  {"agent":"a","fix_decision":"applied","defect_signature":{"kind":"appears-once"}}
],"convergence_inputs":{"fixes_applied":2},"telemetry":null}
EOF
ET_REC1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_REC1903" --slug pr-1903 --mode record)"
# text-matching recurs across all three iterations; pair-in-two appears in only
# two (the boundary that pins <3 as NOT recurring); appears-once appears in one.
assert_eq "et(#1903): exactly the kind recurring across 3 iterations is reported, with its iterations" \
  '[{"kind":"text-matching","iterations":[1,2,3]}]' \
  "$(echo "$ET_REC1903_OUT" | jq -c '.recurring_defect_kinds')"
rm -rf "$ET_REC1903"

# No defect_signature anywhere → the field is the explicit "unestablished"
# sentinel, never an empty set (the producer emitted no operand to read).
ET_NOSIG1903="$(mktemp -d)"
cat > "$ET_NOSIG1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_NOSIG1903/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"pushed_back"}],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
cat > "$ET_NOSIG1903/iter-3.json" <<'EOF'
{"iter":3,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_NOSIG1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_NOSIG1903" --slug pr-1903 --mode record)"
assert_eq "et(#1903): no defect_signature at all → unestablished (not an empty set)" \
  '"unestablished"' \
  "$(echo "$ET_NOSIG1903_OUT" | jq -c '.recurring_defect_kinds')"
rm -rf "$ET_NOSIG1903"

# A malformed defect_signature (present but non-object / kind-less / non-string
# kind) is rendered under the explicit "unknown" label rather than dropped.
ET_MAL1903="$(mktemp -d)"
cat > "$ET_MAL1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":"oops"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_MAL1903/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_MAL1903/iter-3.json" <<'EOF'
{"iter":3,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":123}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_MAL1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_MAL1903" --slug pr-1903 --mode record)"
assert_eq "et(#1903): malformed defect_signature rendered under the explicit unknown-kind label" \
  '[{"kind":"unknown","iterations":[1,2,3]}]' \
  "$(echo "$ET_MAL1903_OUT" | jq -c '.recurring_defect_kinds')"
rm -rf "$ET_MAL1903"

# Distinctness keys on the iteration RECORD (element position), not the `.iter`
# value: three separate records carrying a duplicate/null `.iter` still count as
# three iterations. Keying on `.iter` value would collapse them and undercount —
# the exact run this feature exists to surface. iter-1/iter-2 share iter value 1,
# iter-3 is value 2; the kind is present in all three records, so it is recurring
# with the value-deduped iterations list [1,2].
ET_POS1903="$(mktemp -d)"
cat > "$ET_POS1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"dup-iter"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_POS1903/iter-2.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"dup-iter"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_POS1903/iter-3.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"dup-iter"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_POS1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_POS1903" --slug pr-1903 --mode record)"
assert_eq "et(#1903): recurrence counts distinct iteration RECORDS, not distinct .iter values (no undercount)" \
  '[{"kind":"dup-iter","iterations":[1,2]}]' \
  "$(echo "$ET_POS1903_OUT" | jq -c '.recurring_defect_kinds')"
rm -rf "$ET_POS1903"

# The trace (Markdown) render surface, not just the --mode record JSON above: a
# recurring kind renders one bullet naming the kind and its iterations, and a
# no-signature run renders the explicit unestablished line rather than nothing.
ET_TR1903="$(mktemp -d)"
cat > "$ET_TR1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"text-matching"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_TR1903/iter-2.json" <<'EOF'
{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"text-matching"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_TR1903/iter-3.json" <<'EOF'
{"iter":3,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied","defect_signature":{"kind":"text-matching"}}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_TR1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_TR1903" --slug pr-1903 --mode trace)"
assert_eq "et(#1903): trace renders the recurring-kind bullet with its iterations" "true" \
  "$(echo "$ET_TR1903_OUT" | grep -qF 'text-matching - iterations 1, 2, 3' && echo true || echo false)"
rm -rf "$ET_TR1903"
ET_TRU1903="$(mktemp -d)"
cat > "$ET_TRU1903/iter-1.json" <<'EOF'
{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_TRU1903_OUT="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_TRU1903" --slug pr-1903 --mode trace)"
assert_eq "et(#1903): trace renders the explicit unestablished recurring-kinds line" "true" \
  "$(echo "$ET_TRU1903_OUT" | grep -q 'Unestablished — no iteration record carried a defect_signature' && echo true || echo false)"
rm -rf "$ET_TRU1903"

# Engine-PR analyzer gating (issue #52): the gating change is prose in
# skills/review/SKILL.md; its observable contract is the phase3_dispatched
# roster the orchestrator writes. Assert the roster flows through the trace so
# a gated-out type/test analyzer is absent on an engine-self-modifying diff with
# nothing for them to analyze, and present when the engine PR adds testable code.
ET_GATE="$(mktemp -d)"
# iter-1: engine_self_modifying, has_new_types=false, no test/code-logic changes
# → only the four always-on agents dispatched; type/test analyzers gated out.
cat > "$ET_GATE/iter-1.json" <<'EOF'
{"iter":1,"diff_profile":{"small_diff":false,"config_only":true,"has_new_types":false,"engine_self_modifying":true,"checklist_skipped":null},
"checklist":[{"verification_mode":"lite","verdict":"PASS"}],
"phase3_dispatched":["devflow:code-reviewer","devflow:silent-failure-hunter","devflow:comment-analyzer","devflow:requesting-code-review"],
"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{"phase_3":{"calls":4,"tokens":40000,"wall_clock_s":120}}}
EOF
# iter-2: engine_self_modifying diff that adds testable code logic → pr-test-analyzer
# is dispatched (test-relevance predicate branch 2); type-design still gated out.
cat > "$ET_GATE/iter-2.json" <<'EOF'
{"iter":2,"diff_profile":{"small_diff":false,"config_only":false,"has_new_types":false,"engine_self_modifying":true,"checklist_skipped":null},
"checklist":[{"verification_mode":"agent","verdict":"PASS"}],
"phase3_dispatched":["devflow:code-reviewer","devflow:silent-failure-hunter","devflow:comment-analyzer","devflow:requesting-code-review","devflow:pr-test-analyzer"],
"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{"phase_3":{"calls":5,"tokens":52000,"wall_clock_s":160}}}
EOF
ET_GATE_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_GATE" --slug "pr-15" --mode record)"
# Exact array-membership (jq `index`), not substring grep — so an exclusion
# assertion can't be fooled by a longer agent id that merely contains the name.
# These assert the trace's roster PASSTHROUGH for the rosters the gating prose
# produces; the gating decision itself is LLM-prose in skills/review/SKILL.md
# (not harness-reachable), so this guards that a gated roster survives the trace.
ET_has() { echo "$ET_GATE_REC" | jq -r --argjson i "$1" --arg a "$2" '.per_iteration[] | select(.iter==$i) | (.phase3_dispatched | index($a) != null)'; }
assert_eq "et(#52): engine-PR no-types/no-tests roster passthrough excludes type-design-analyzer" "false" \
  "$(ET_has 1 'devflow:type-design-analyzer')"
assert_eq "et(#52): engine-PR no-types/no-tests roster passthrough excludes pr-test-analyzer" "false" \
  "$(ET_has 1 'devflow:pr-test-analyzer')"
assert_eq "et(#52): engine-PR no-types/no-tests dispatched count = 4 always-on" "4" \
  "$(echo "$ET_GATE_REC" | jq -r '.per_iteration[] | select(.iter==1) | .phase3_dispatched_count')"
assert_eq "et(#52): engine-PR adding testable code roster passthrough includes pr-test-analyzer" "true" \
  "$(ET_has 2 'devflow:pr-test-analyzer')"
assert_eq "et(#52): engine-PR adding testable code still excludes type-design-analyzer" "false" \
  "$(ET_has 2 'devflow:type-design-analyzer')"
rm -rf "$ET_GATE"

# none-recorded posture remains reachable for the genuine degraded case the
# writer-gap-closing prose now leans on: Phase 1+2 ran (checklist_skipped null)
# but the checklist array is empty / no items recorded. This is the "real
# regression worth investigating" branch — lock it so it can't silently change.
ET_NR="$(mktemp -d)"
cat > "$ET_NR/iter-1.json" <<'EOF'
{"iter":1,"diff_profile":{"small_diff":false,"config_only":false,"has_new_types":false,"engine_self_modifying":false,"checklist_skipped":null},
"checklist":[],"phase3_dispatched":["devflow:code-reviewer"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
ET_NR_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_NR" --slug "pr-15" --mode record)"
assert_eq "et(#52): Phase 1+2 ran but zero checklist items → none-recorded (genuine gap)" "none-recorded" \
  "$(echo "$ET_NR_REC" | jq -r '.per_iteration[0].verification_posture')"
rm -rf "$ET_NR"

# Partial telemetry resilience: a workpad whose telemetry block has one phase
# present (others absent) still yields a non-null telemetry[].phases — mirroring
# the writer contract that a missing per-source token never nulls the whole block.
ET_PT="$(mktemp -d)"
cat > "$ET_PT/iter-1.json" <<'EOF'
{"iter":1,"checklist":[{"verification_mode":"lite","verdict":"PASS"}],"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{"phase_3":{"calls":1,"wall_clock_s":10}}}
EOF
ET_PT_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_PT" --slug "pr-15" --mode record)"
assert_eq "et(#52): partial telemetry (one phase, no tokens) → phases non-null" "false" \
  "$(echo "$ET_PT_REC" | jq -r '.telemetry[] | select(.iter==1) | .phases' | grep -q '^null$' && echo true || echo false)"
assert_eq "et(#52): partial telemetry preserves the present phase's calls" "1" \
  "$(echo "$ET_PT_REC" | jq -r '.telemetry[] | select(.iter==1) | .phases.phase_3.calls')"
rm -rf "$ET_PT"

# Executable-bit guard (corroborated review finding): direct invocation of the
# helper depends on lib/efficiency-trace.sh keeping its committed +x bit through
# vendoring. The harness invokes it `bash "$LIB/..."`, which masks a lost bit, so
# assert the committed mode is 100755 — a lost bit fails CI rather than silently
# disabling headless telemetry in production.
assert_eq "et(#52): lib/efficiency-trace.sh committed executable (100755)" "100755" \
  "$(cd "$LIB/.." && git ls-files -s lib/efficiency-trace.sh | cut -d' ' -f1)"

# ── Review-mode derivation (issue #55) ──────────────────────────────────────
# Standalone /devflow:review never applies a fix, so its records carry
# `contributed_to_verdict` (bool) per finding instead of `fix_decision`.
# verdict_for selects the review-mode branch off the run-level source:"review"
# (not per-finding field presence — see the ET_RMIX omitted-field case below):
# contributed (corr<2)→unique-effective, contributed (corr>=2)→corroborating,
# only-demoted→noise, silent→null. And the record carries source:"review".
ET_REV="$(mktemp -d)"
cat > "$ET_REV/iter-1.json" <<'EOF'
{
  "iter": 1,
  "source": "review",
  "checklist": [{"verification_mode":"lite","verdict":"PASS"},{"verification_mode":"agent","verdict":"FAIL"}],
  "phase3_dispatched": ["rev-unique","rev-corrob","rev-demoted","rev-silent"],
  "phase3_findings": [
    {"agent":"rev-unique","corroboration_count":1,"contributed_to_verdict":true},
    {"agent":"rev-corrob","corroboration_count":3,"contributed_to_verdict":true},
    {"agent":"rev-demoted","corroboration_count":1,"contributed_to_verdict":false}
  ],
  "convergence_inputs": {"fixes_applied": 0},
  "telemetry": {"phase_3": {"calls": 4, "tokens": 30000, "wall_clock_s": 90}}
}
EOF
ET_REV_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_REV" --slug "pr-99" --mode record)"
ET_rv() { echo "$ET_REV_REC" | jq -r --arg a "$1" '.per_iteration[0].agent_verdicts[] | select(.agent==$a) | .verdict'; }
assert_eq "et(#55): review-mode contributed + corr<2 → unique-effective" "unique-effective" "$(ET_rv 'rev-unique')"
assert_eq "et(#55): review-mode contributed + corr>=2 → corroborating"    "corroborating"    "$(ET_rv 'rev-corrob')"
assert_eq "et(#55): review-mode only-demoted finding → noise"             "noise"            "$(ET_rv 'rev-demoted')"
assert_eq "et(#55): review-mode dispatched-but-silent → null"             "null"             "$(ET_rv 'rev-silent')"
assert_eq "et(#55): review-mode silent verdict is JSON null (not string)" "null" \
  "$(echo "$ET_REV_REC" | jq -r '.per_iteration[0].agent_verdicts[] | select(.agent=="rev-silent") | .verdict | type')"
assert_eq "et(#55): record carries source: review" "review" \
  "$(echo "$ET_REV_REC" | jq -r '.source')"
rm -rf "$ET_REV"

# A review-and-fix record (fix_decision, no contributed_to_verdict) is unaffected
# by the review-mode branch and defaults source to review-and-fix.
ET_RAF="$(mktemp -d)"
cat > "$ET_RAF/iter-1.json" <<'EOF'
{"iter":1,"checklist":[],"phase3_dispatched":["a"],
"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_RAF_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_RAF" --slug "pr-1" --mode record)"
assert_eq "et(#55): review-and-fix record still classifies off fix_decision (applied→unique-effective)" "unique-effective" \
  "$(echo "$ET_RAF_REC" | jq -r '.per_iteration[0].agent_verdicts[] | select(.agent=="a") | .verdict')"
assert_eq "et(#55): absent source defaults to review-and-fix" "review-and-fix" \
  "$(echo "$ET_RAF_REC" | jq -r '.source')"
rm -rf "$ET_RAF"

# Review-mode per-agent aggregation (issue #55 review hardening): the verdict is
# keyed off the run-level source ("review"), not per-finding field presence, so
# these stress the branch ordering and the omitted-field → noise path that the
# one-finding-per-agent fixtures above don't reach.
ET_RMIX="$(mktemp -d)"
cat > "$ET_RMIX/iter-1.json" <<'EOF'
{
  "iter": 1,
  "source": "review",
  "checklist": [],
  "phase3_dispatched": ["mix-unique","mix-corrob","omit-demoted","mixcorr","allcorr","str-true"],
  "phase3_findings": [
    {"agent":"mix-unique","corroboration_count":1,"contributed_to_verdict":true},
    {"agent":"mix-unique","corroboration_count":1,"contributed_to_verdict":false},
    {"agent":"mix-corrob","corroboration_count":3,"contributed_to_verdict":true},
    {"agent":"mix-corrob","corroboration_count":1,"contributed_to_verdict":false},
    {"agent":"omit-demoted","corroboration_count":1},
    {"agent":"mixcorr","corroboration_count":3,"contributed_to_verdict":true},
    {"agent":"mixcorr","corroboration_count":1,"contributed_to_verdict":true},
    {"agent":"allcorr","corroboration_count":2,"contributed_to_verdict":true},
    {"agent":"allcorr","corroboration_count":3,"contributed_to_verdict":true},
    {"agent":"str-true","corroboration_count":1,"contributed_to_verdict":"true"}
  ],
  "convergence_inputs": {"fixes_applied": 0},
  "telemetry": null
}
EOF
ET_RMIX_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_RMIX" --slug "pr-99" --mode record)"
ET_mv() { echo "$ET_RMIX_REC" | jq -r --arg a "$1" '.per_iteration[0].agent_verdicts[] | select(.agent==$a) | .verdict'; }
assert_eq "et(#55): contributing finding wins over a co-located demoted one (corr<2)" "unique-effective" "$(ET_mv 'mix-unique')"
assert_eq "et(#55): contributing finding wins over a co-located demoted one (corr>=2)" "corroborating" "$(ET_mv 'mix-corrob')"
# The regression test for the corroborated review finding: a demoted finding that
# OMITS contributed_to_verdict must still classify noise (not null) — the agent
# raised something, it just didn't contribute.
assert_eq "et(#55): omitted contributed_to_verdict on a raised finding → noise (not null)" "noise" "$(ET_mv 'omit-demoted')"
# Mixed corroboration within contributing findings: any unique (corr<2) → unique-effective.
assert_eq "et(#55): mixed corroboration among contributing findings → unique-effective" "unique-effective" "$(ET_mv 'mixcorr')"
# 2+ contributing findings, ALL corroborated (corr>=2) → stays corroborating (no
# unique discoverer among them). Guards the precedence boundary the single-finding
# rev-corrob fixture above can't reach.
assert_eq "et(#55): 2+ contributing findings all corr>=2 → corroborating" "corroborating" "$(ET_mv 'allcorr')"
# Malformed contributed_to_verdict (a stringified "true" from an LLM-authored
# record) is NOT truthy: the `== true` gate is strict, so the agent raised a
# finding that didn't contribute → noise (not unique-effective, not null). Pins
# the deliberate strict-boolean contract documented in verdict_for.
assert_eq "et(#55): stringified \"true\" contributed_to_verdict → noise (strict == true gate)" "noise" "$(ET_mv 'str-true')"
# Review-mode verdicts must also surface in the --mode trace Markdown (the live-
# comment surface), not just the --mode record JSON exercised above.
ET_RMIX_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_RMIX" --slug "pr-99" --mode trace)"
assert_eq "et(#55): review-mode verdicts render in --mode trace Markdown" "true" \
  "$(echo "$ET_RMIX_TRACE" | grep -qiE 'corroborating|unique-effective' && echo true || echo false)"
# Review-mode render (issue #56 review): the fixes-oriented summary/warning lines
# are adapted for review mode — show the verdict-contribution signal, NOT the
# misleading "Fixes applied: 0" / fix-based "added nothing" that would contradict
# the unique-effective/corroborating verdicts a healthy review prints.
assert_eq "et(#56): review-mode trace shows the verdict-contribution signal" "true" \
  "$(echo "$ET_RMIX_TRACE" | grep -q 'Effectiveness signal: verdict contribution' && echo true || echo false)"
assert_eq "et(#56): review-mode trace omits the fixes-oriented 'Fixes applied' line" "true" \
  "$(echo "$ET_RMIX_TRACE" | grep -q 'Fixes applied' && echo false || echo true)"
assert_eq "et(#56): review-mode trace (agents contributed) omits the fix-based 'added nothing' warning" "true" \
  "$(echo "$ET_RMIX_TRACE" | grep -q 'added nothing' && echo false || echo true)"
rm -rf "$ET_RMIX"

# Multi-iteration run-level source resolution: iter-1 carries no source, iter-2
# carries "review" → the run-level source is "review" (first non-null), and each
# iteration still classifies off its own source.
ET_RMI="$(mktemp -d)"
cat > "$ET_RMI/iter-1.json" <<'EOF'
{"iter":1,"checklist":[],"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_RMI/iter-2.json" <<'EOF'
{"iter":2,"source":"review","checklist":[],"phase3_dispatched":["b"],"phase3_findings":[{"agent":"b","corroboration_count":1,"contributed_to_verdict":true}],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
ET_RMI_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_RMI" --slug "pr-99" --mode record)"
assert_eq "et(#55): run-level source is first non-null across iters (review)" "review" \
  "$(echo "$ET_RMI_REC" | jq -r '.source')"
assert_eq "et(#55): iter-1 (fix_decision, no source) classifies off its own shape" "unique-effective" \
  "$(echo "$ET_RMI_REC" | jq -r '.per_iteration[] | select(.iter==1) | .agent_verdicts[0].verdict')"
assert_eq "et(#55): iter-2 (source review) classifies review-mode" "unique-effective" \
  "$(echo "$ET_RMI_REC" | jq -r '.per_iteration[] | select(.iter==2) | .agent_verdicts[0].verdict')"
rm -rf "$ET_RMI"

# Mixed-source future-proofing warning (issue #55 review hardening): a run whose
# iterations carry genuinely divergent `source` values is not currently produced,
# but if it ever is, the wrapper warns (best-effort, never aborts) — the record's
# run-level source collapses to the first non-null and would otherwise silently
# mislabel the run. No fixture exercised this guard before.
ET_MIXSRC="$(mktemp -d)"
cat > "$ET_MIXSRC/iter-1.json" <<'EOF'
{"iter":1,"source":"review","checklist":[],"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","corroboration_count":1,"contributed_to_verdict":true}],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
cat > "$ET_MIXSRC/iter-2.json" <<'EOF'
{"iter":2,"source":"review-and-fix","checklist":[],"phase3_dispatched":["b"],"phase3_findings":[{"agent":"b","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_MIXSRC_ERR="$(mktemp)"
ET_MIXSRC_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_MIXSRC" --slug "pr-99" --mode record 2>"$ET_MIXSRC_ERR")"; ET_MIXSRC_RC=$?
assert_eq "et(#55): mixed explicit sources → wrapper still exits 0 (best-effort)" "0" "$ET_MIXSRC_RC"
assert_eq "et(#55): mixed explicit sources (review + review-and-fix) → warns" "true" \
  "$(grep -q "::warning::.*mixed 'source'" "$ET_MIXSRC_ERR" && echo true || echo false)"
assert_eq "et(#55): mixed-source record still collapses run-level source to first non-null (review)" "review" \
  "$(echo "$ET_MIXSRC_REC" | jq -r '.source')"
# A `review` iter mixed with a source-LESS iter must ALSO warn: the absent source
# is counted as the run-level default (review-and-fix), so the run is genuinely
# mixed even though one iter omits the field. Guards the `.source // "review-and-fix"`
# counting — a bare `.source // empty` would drop the absent iter and stay silent.
cat > "$ET_MIXSRC/iter-2.json" <<'EOF'
{"iter":2,"checklist":[],"phase3_dispatched":["b"],"phase3_findings":[{"agent":"b","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_MIXSRC_ERR2="$(mktemp)"
bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_MIXSRC" --slug "pr-99" --mode record >/dev/null 2>"$ET_MIXSRC_ERR2"
assert_eq "et(#55): review + source-less iter → also warns (absent counts as default)" "true" \
  "$(grep -q "::warning::.*mixed 'source'" "$ET_MIXSRC_ERR2" && echo true || echo false)"
rm -rf "$ET_MIXSRC"; rm -f "$ET_MIXSRC_ERR" "$ET_MIXSRC_ERR2"

# Regression guard for the new counting: a uniform single-source run must NOT warn.
# Two source-less iters both default to review-and-fix → one distinct value → silent
# (this is the common /devflow:review-and-fix loop, which must stay warning-free).
ET_SAMESRC="$(mktemp -d)"
cat > "$ET_SAMESRC/iter-1.json" <<'EOF'
{"iter":1,"checklist":[],"phase3_dispatched":["a"],"phase3_findings":[{"agent":"a","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
cat > "$ET_SAMESRC/iter-2.json" <<'EOF'
{"iter":2,"checklist":[],"phase3_dispatched":["b"],"phase3_findings":[{"agent":"b","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_SAMESRC_ERR="$(mktemp)"
bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_SAMESRC" --slug "pr-1" --mode record >/dev/null 2>"$ET_SAMESRC_ERR"
assert_eq "et(#55): uniform source-less run → does NOT warn" "false" \
  "$(grep -q "::warning::.*mixed 'source'" "$ET_SAMESRC_ERR" && echo true || echo false)"
rm -rf "$ET_SAMESRC"; rm -f "$ET_SAMESRC_ERR"

# Populated checklist/telemetry writer gap closed (issue #52): a workpad where
# Phase 1+2 ran yields a real lite/agent split, a non-none-recorded posture, and
# non-null telemetry[].phases — i.e. none-recorded/null phases now signal genuine
# degradation only, never a normal full-engine run.
assert_eq "et(#52): populated checklist → posture is not none-recorded" "false" \
  "$(echo "$ET_REC" | jq -r '.per_iteration[] | select(.iter==1) | .verification_posture' | grep -q 'none-recorded' && echo true || echo false)"
assert_eq "et(#52): populated checklist → posture mixed (lite+agent)" "mixed" \
  "$(echo "$ET_REC" | jq -r '.per_iteration[] | select(.iter==1) | .verification_posture')"
assert_eq "et(#52): populated telemetry block → telemetry[].phases non-null" "false" \
  "$(echo "$ET_REC" | jq -r '.telemetry[] | select(.iter==1) | .phases' | grep -q '^null$' && echo true || echo false)"

# Marginal-yield line: iter 2 applied 0 fixes → trace flags "added nothing".
ET_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode trace)"
assert_eq "et: marginal-yield line for zero-fix iteration" "true" \
  "$(echo "$ET_TRACE" | grep -q 'Marginal yield: this iteration applied 0 fixes' && echo true || echo false)"
assert_eq "et: trace shows dispatched count" "true" \
  "$(echo "$ET_TRACE" | grep -q 'Phase 3 agents dispatched: 3' && echo true || echo false)"

# Flag-off → no output in either mode (so the SKILL.md write produces no file).
ET_CFG="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$ET_CFG"
ET_OFF_REC="$(DEVFLOW_CONFIG_FILE="$ET_CFG" bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode record)"
ET_OFF_TRACE="$(DEVFLOW_CONFIG_FILE="$ET_CFG" bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode trace)"
assert_eq "et: flag-off → record empty" "" "$ET_OFF_REC"
assert_eq "et: flag-off → trace empty"  "" "$ET_OFF_TRACE"

# Graceful degradation: a workpad WITHOUT phase3_dispatched still classifies the
# agents that appear in phase3_findings; the trace flags the missing roster.
ET_DEG="$(mktemp -d)"
cat > "$ET_DEG/iter-1.json" <<'EOF'
{"iter":1,"checklist":[],"phase3_findings":[{"agent":"devflow:code-reviewer","corroboration_count":1,"fix_decision":"applied"}],"convergence_inputs":{"fixes_applied":1},"telemetry":null}
EOF
ET_DEG_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DEG" --slug "branch-x" --mode record)"
assert_eq "et: degraded (no phase3_dispatched) still classifies finding agent" "unique-effective" \
  "$(echo "$ET_DEG_REC" | jq -r '.per_iteration[0].agent_verdicts[] | select(.agent=="devflow:code-reviewer") | .verdict')"
assert_eq "et: degraded dispatched_count=0 (roster absent)" "0" \
  "$(echo "$ET_DEG_REC" | jq -r '.per_iteration[0].phase3_dispatched_count')"
ET_DEG_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DEG" --slug "branch-x" --mode trace)"
assert_eq "et: degraded trace flags absent phase3_dispatched" "true" \
  "$(echo "$ET_DEG_TRACE" | grep -q 'absent.*null agents (dispatched but silent) cannot be shown' && echo true || echo false)"

# Present-but-empty roster ("phase3_dispatched": []) is NOT "absent" — the
# degradation warning must not fire (regression guard for has() vs length>0).
ET_EMPTYROSTER="$(mktemp -d)"
cat > "$ET_EMPTYROSTER/iter-1.json" <<'EOF'
{"iter":1,"checklist":[],"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}
EOF
ET_ER_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_EMPTYROSTER" --slug "pr-15" --mode trace)"
assert_eq "et: empty-but-present roster does NOT flag 'absent'" "false" \
  "$(echo "$ET_ER_TRACE" | grep -q 'null agents (dispatched but silent) cannot be shown' && echo true || echo false)"
rm -rf "$ET_EMPTYROSTER"

# A valid-but-non-object workpad (stray array) is skipped, not crashed on
# (best-effort never-abort contract). The wrapper must still exit 0.
ET_BADSHAPE="$(mktemp -d)"
printf '[1,2,3]' > "$ET_BADSHAPE/iter-1.json"
ET_BS_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_BADSHAPE" --slug "pr-15" --mode trace 2>/dev/null)"; ET_BS_RC=$?
assert_eq "et: non-object workpad → wrapper exits 0 (never aborts)" "0" "$ET_BS_RC"
assert_eq "et: non-object workpad → degrades to unavailable notice" "true" \
  "$(echo "$ET_BS_TRACE" | grep -q 'effectiveness trace unavailable' && echo true || echo false)"
rm -rf "$ET_BADSHAPE"

# No readable workpads → trace degrades to a one-line notice, never errors.
ET_EMPTY="$(mktemp -d)"
ET_EMPTY_TRACE="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_EMPTY" --slug "branch-x" --mode trace)"
assert_eq "et: empty workpad dir → graceful notice" "true" \
  "$(echo "$ET_EMPTY_TRACE" | grep -q 'effectiveness trace unavailable' && echo true || echo false)"
# record mode with zero readable iterations emits NOTHING (not a contentless
# skeleton) so the caller's `[ -s ]` guard removes the 0-byte file — symmetric
# with the flag-off contract.
ET_EMPTY_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_EMPTY" --slug "branch-x" --mode record)"
assert_eq "et: zero-iteration record emits empty (no skeleton)" "" "$ET_EMPTY_REC"

# Verdict-precedence + branch coverage on a single mixed fixture. Each agent
# below isolates one path through verdict_for that the happy-path fixtures miss.
ET_PREC="$(mktemp -d)"
cat > "$ET_PREC/iter-1.json" <<'EOF'
{
  "iter": 1,
  "checklist": [],
  "phase3_dispatched": ["agent-mixed-unique","agent-mixed-corr","agent-advisory","agent-deferred","agent-sevcal","agent-nocorr"],
  "phase3_findings": [
    {"agent":"agent-mixed-unique","corroboration_count":1,"fix_decision":"applied"},
    {"agent":"agent-mixed-unique","corroboration_count":1,"fix_decision":"pushed_back"},
    {"agent":"agent-mixed-corr","corroboration_count":3,"fix_decision":"applied"},
    {"agent":"agent-mixed-corr","corroboration_count":1,"fix_decision":"advisory"},
    {"agent":"agent-advisory","corroboration_count":1,"fix_decision":"advisory"},
    {"agent":"agent-deferred","corroboration_count":1,"fix_decision":"deferred"},
    {"agent":"agent-sevcal","corroboration_count":1,"fix_decision":"severity-calibrated"},
    {"agent":"agent-nocorr","fix_decision":"applied"}
  ],
  "convergence_inputs": {"fixes_applied": 3},
  "telemetry": null
}
EOF
ET_PREC_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_PREC" --slug "pr-15" --mode record)"
ET_pv() { echo "$ET_PREC_REC" | jq -r --arg a "$1" '.per_iteration[0].agent_verdicts[] | select(.agent==$a) | .verdict'; }
assert_eq "et: precedence applied(corr1)+pushed_back → unique-effective" "unique-effective" "$(ET_pv 'agent-mixed-unique')"
assert_eq "et: precedence applied(corr3)+advisory → corroborating (applied dominates noise)" "corroborating" "$(ET_pv 'agent-mixed-corr')"
assert_eq "et: advisory-only finding → noise" "noise" "$(ET_pv 'agent-advisory')"
assert_eq "et: deferred-only finding → null (not noise)" "null" "$(ET_pv 'agent-deferred')"
# severity-calibrated is a real-but-not-applied outcome (over-graded, calibrated down) — like
# deferred it must classify null, NOT noise (noise is reserved for pushed_back/advisory
# false-positives). This behaviorally locks the verdict_for `else null` fall-through so a
# future edit that adds severity-calibrated to the noise any() set goes RED instead of
# silently mis-bucketing a calibrated finding as reviewer noise (#160).
assert_eq "et: severity-calibrated-only finding → null (not noise)" "null" "$(ET_pv 'agent-sevcal')"
assert_eq "et: applied with missing corroboration_count → unique-effective (// 1 default)" "unique-effective" "$(ET_pv 'agent-nocorr')"
rm -rf "$ET_PREC"

# THRESHOLD: a valid custom integer is carried into the record; a non-numeric
# operator value falls back to the default 3 WITHOUT aborting the wrapper.
ET_TCFG="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_cut_candidate_min_dispatch":7}}' > "$ET_TCFG"
ET_T7="$(DEVFLOW_CONFIG_FILE="$ET_TCFG" bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode record)"
assert_eq "et: custom threshold 7 carried into record" "7" "$(echo "$ET_T7" | jq -r '.cut_candidate_min_dispatch')"
ET_TBAD="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_cut_candidate_min_dispatch":"abc"}}' > "$ET_TBAD"
ET_TB="$(DEVFLOW_CONFIG_FILE="$ET_TBAD" bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode record 2>/dev/null)"; ET_TB_RC=$?
assert_eq "et: non-numeric threshold → wrapper still exits 0" "0" "$ET_TB_RC"
assert_eq "et: non-numeric threshold → falls back to 3 in record" "3" "$(echo "$ET_TB" | jq -r '.cut_candidate_min_dispatch')"
# A below-minimum value (0) is clamped to the default 3 (schema declares minimum:1).
ET_TZERO="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_cut_candidate_min_dispatch":0}}' > "$ET_TZERO"
ET_TZ="$(DEVFLOW_CONFIG_FILE="$ET_TZERO" bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode record)"
assert_eq "et: threshold 0 (below schema minimum:1) → clamped to 3" "3" "$(echo "$ET_TZ" | jq -r '.cut_candidate_min_dispatch')"
rm -f "$ET_TCFG" "$ET_TBAD" "$ET_TZERO"

# CLI contract: an invalid --mode is rejected with exit 2 (protects SKILL.md's
# dependence on the trace/record flag names).
bash "$LIB/efficiency-trace.sh" --workpad-dir "$ET_DIR" --slug "pr-15" --mode bogus >/dev/null 2>&1; ET_MODE_RC=$?
assert_eq "et: invalid --mode → exit 2" "2" "$ET_MODE_RC"

rm -rf "$ET_DIR" "$ET_DEG" "$ET_EMPTY"; rm -f "$ET_CFG"

# ── #609 agent_effort[]: per-agent effort observability in the per-run record ─
# The record carries, per dispatched agent, agent id + exactly the five effort
# observability fields (requested/resolved/application_point/effective/
# fallback_reason), populated over the FULL dispatched roster — phase3_dispatched
# ∪ the agents in the new `dispatched_effort` iter-workpad field — never the
# resolver map alone. `dispatched_effort` is the field that captures the
# Phase-1/1.5/2 dispatch roster (a checklist-phase agent never appears in
# phase3_dispatched), so the checklist-generator assertion below FAILS against a
# Phase-3-only implementation by construction (AC4), and the no-override
# code-reviewer assertion is the full-roster arm (AC5).
AE_DIR="$(mktemp -d)"
cat > "$AE_DIR/iter-1.json" <<'EOF'
{
  "iter": 1,
  "checklist": [],
  "dispatched_effort": [
    {"agent":"devflow:checklist-generator","phase":"1","requested":"low","resolved":"low","application_point":"session-fallback","effective":null,"fallback_reason":"per-agent effort 'low' resolved but not applied: no in-session per-agent effort seam"}
  ],
  "phase3_dispatched": ["devflow:code-reviewer"],
  "phase3_findings": [],
  "convergence_inputs": {"fixes_applied": 0},
  "telemetry": "unavailable"
}
EOF
AE_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$AE_DIR" --slug "pr-609" --mode record)"
AE_field() { echo "$AE_REC" | jq -r --arg a "$1" --arg f "$2" '.per_iteration[0].agent_effort[]? | select(.agent==$a) | .[$f]'; }
AE_field_type() { echo "$AE_REC" | jq -r --arg a "$1" --arg f "$2" '.per_iteration[0].agent_effort[]? | select(.agent==$a) | .[$f] | type'; }
# AC4: the Phase-1 agent is routed through dispatched_effort into agent_effort.
assert_eq "#609 agent_effort: checklist-generator (Phase-1) block carries session-fallback" \
  "session-fallback" "$(AE_field 'devflow:checklist-generator' 'application_point')"
assert_eq "#609 agent_effort: checklist-generator requested rides through" \
  "low" "$(AE_field 'devflow:checklist-generator' 'requested')"
assert_eq "#609 agent_effort: checklist-generator resolved rides through" \
  "low" "$(AE_field 'devflow:checklist-generator' 'resolved')"
assert_eq "#609 agent_effort: checklist-generator fallback_reason is a string" \
  "string" "$(AE_field_type 'devflow:checklist-generator' 'fallback_reason')"
# AC5: a dispatched Phase-3 agent with NO dispatched_effort entry still gets a
# block — all-null effort, session-inheritance, fallback_reason null.
assert_eq "#609 agent_effort: no-override phase3 agent → session-inheritance" \
  "session-inheritance" "$(AE_field 'devflow:code-reviewer' 'application_point')"
assert_eq "#609 agent_effort: no-override requested is JSON null" \
  "null" "$(AE_field_type 'devflow:code-reviewer' 'requested')"
assert_eq "#609 agent_effort: no-override resolved is JSON null" \
  "null" "$(AE_field_type 'devflow:code-reviewer' 'resolved')"
assert_eq "#609 agent_effort: no-override fallback_reason is JSON null" \
  "null" "$(AE_field_type 'devflow:code-reviewer' 'fallback_reason')"
assert_eq "#609 agent_effort: effective is JSON null (never inferred)" \
  "null" "$(AE_field_type 'devflow:checklist-generator' 'effective')"
# Complete by construction: each block is agent + exactly the five effort fields.
assert_eq "#609 agent_effort: block keys are agent + the five effort fields exactly" \
  "agent,application_point,effective,fallback_reason,requested,resolved" \
  "$(echo "$AE_REC" | jq -r '.per_iteration[0].agent_effort[0] | keys | sort | join(",")')"
# Unknown-vs-zero honesty: the roster field's presence is recorded, mirroring
# phase3_dispatched_present.
assert_eq "#609 agent_effort: dispatched_effort_present true when the field exists" \
  "true" "$(echo "$AE_REC" | jq -r '.per_iteration[0].dispatched_effort_present')"
rm -rf "$AE_DIR"
# Degradation: an iter with NO dispatched_effort field (an older workpad) still
# yields agent_effort over phase3_dispatched (all session-inheritance), with the
# presence flag false — additive and nullable, no schema_version bump.
AE_OLD="$(mktemp -d)"
printf '{"iter":1,"checklist":[],"phase3_dispatched":["devflow:comment-analyzer"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":"unavailable"}' > "$AE_OLD/iter-1.json"
AE_OLD_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$AE_OLD" --slug "pr-609" --mode record)"
assert_eq "#609 agent_effort: absent dispatched_effort → blocks still cover phase3_dispatched" \
  "session-inheritance" \
  "$(echo "$AE_OLD_REC" | jq -r '.per_iteration[0].agent_effort[]? | select(.agent=="devflow:comment-analyzer") | .application_point')"
assert_eq "#609 agent_effort: absent dispatched_effort → presence flag false" \
  "false" "$(echo "$AE_OLD_REC" | jq -r '.per_iteration[0].dispatched_effort_present')"
assert_eq "#609 agent_effort: schema_version stays 1 (additive, no bump)" \
  "1" "$(echo "$AE_OLD_REC" | jq -r '.schema_version')"
# Malformed shape: a scalar dispatched_effort is treated as no usable entries
# (blocks still derived from phase3_dispatched; the filter never aborts).
AE_BAD="$(mktemp -d)"
printf '{"iter":1,"checklist":[],"dispatched_effort":"bogus","phase3_dispatched":["devflow:code-reviewer"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":"unavailable"}' > "$AE_BAD/iter-1.json"
AE_BAD_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$AE_BAD" --slug "pr-609" --mode record)"; AE_BAD_RC=$?
assert_eq "#609 agent_effort: scalar dispatched_effort never aborts the filter" "0" "$AE_BAD_RC"
assert_eq "#609 agent_effort: scalar dispatched_effort degrades to roster-only blocks" \
  "session-inheritance" \
  "$(echo "$AE_BAD_REC" | jq -r '.per_iteration[0].agent_effort[]? | select(.agent=="devflow:code-reviewer") | .application_point')"
rm -rf "$AE_OLD" "$AE_BAD"

# ────────────────────────────────────────────────────────────────────────────
echo "efficiency-trace.sh --persist / --self-check (issue #80)"
# ────────────────────────────────────────────────────────────────────────────
# Layer 2 (--self-check, warn-only) + Layer 3 (--persist, deterministic backstop)
# that make /devflow:review-and-fix Loop Exit observability persistence
# non-droppable. Both are best-effort: they MUST always exit 0 and never abort.
#
# As of issue #441 --persist writes to the dedicated `prflow-telemetry` orphan
# branch via git plumbing — it NEVER touches the current branch, HEAD, or the
# working tree, and pushes to the remote when one is reachable. So the outcomes
# are asserted ON THE BRANCH (`git cat-file`/`git show`/`git ls-remote`), not in
# the working tree, and the current-branch tip + `git status` are asserted
# BYTE-FOR-BYTE unchanged.
#
# Adversarial input-shape matrix exercised below (the bug class is "a shape
# detonates the helper or yields a misdirected/silent breadcrumb"):
#   workpad dir:   {present + iter-*.json, present + no iter, absent tmp tree}
#   workpad shape: {valid object, malformed/non-object, review-mode source}
#   record state:  {absent → derive+write, already-present → no-op}
#   telemetry:     {on → record, off → no record but durable copy still made}
#   remote:        {reachable → pushed, absent → local ref only, best-effort}
#   re-run:        {second --persist → no new branch commit (idempotent)}

# Issue #469 AC5: under GITHUB_ACTIONS, --persist now PUSHES only when the workflow
# affirmatively sets DEVFLOW_TELEMETRY_PUSH (else it fails closed to staging-only).
# This suite runs under CI (GITHUB_ACTIONS=true), and the telemetry blocks below
# exercise the PUSH/CAS path (branch created, records on the local ref + remote), so
# authorize the push for the whole telemetry section. It is UNSET again after the TB
# blocks. The new staging-only / fail-closed assertions below deliberately OVERRIDE
# this per-invocation (DEVFLOW_TELEMETRY_PUSH='' with GITHUB_ACTIONS=1) to prove the
# closed direction, and the off-CI default-push path is proven with env -u GITHUB_ACTIONS.
export DEVFLOW_TELEMETRY_PUSH=1

# yes/no whether path $2 exists on repo $1's telemetry branch (the branch-presence probe).
_et_on_branch() { git -C "$1" cat-file -e "refs/heads/prflow-telemetry:$2" >/dev/null 2>&1 && echo yes || echo no; }
# cat the telemetry-branch blob $2 of repo $1 to stdout (empty when absent).
_et_show() { git -C "$1" show "refs/heads/prflow-telemetry:$2" 2>/dev/null; }
# number of commits on repo $1's telemetry branch (0 when absent).
_et_branch_count() { git -C "$1" rev-list --count refs/heads/prflow-telemetry 2>/dev/null || echo 0; }

# A throwaway git repo WITH a bare remote so --persist's branch write + push have
# somewhere real to land. `.prflow/tmp/` is gitignored (as in a real repo) so the
# staging never dirties `git status`.
ETP_BARE="$(git_sandbox "et-persist bare remote")"
git -C "$ETP_BARE" init --bare -q
ETP_REPO="$(git_sandbox "et-persist repo")"
git -C "$ETP_REPO" init -q
git -C "$ETP_REPO" config user.email devflow-test@example.com
git -C "$ETP_REPO" config user.name "devflow test"
git -C "$ETP_REPO" remote add origin "$ETP_BARE"
mkdir -p "$ETP_REPO/.prflow"; printf 'tmp/\n' > "$ETP_REPO/.prflow/.gitignore"
printf 'x\n' > "$ETP_REPO/seed.txt"
git -C "$ETP_REPO" add .prflow/.gitignore seed.txt
git -C "$ETP_REPO" commit -qm "seed"; git -C "$ETP_REPO" branch -M main
git -C "$ETP_REPO" push -q -u origin main
ETP_RUN="$ETP_REPO/.prflow/tmp/review/pr-77/run-abc"
mkdir -p "$ETP_RUN"
cat > "$ETP_RUN/iter-1.json" <<'EOF'
{"iter":1,"checklist":[{"verification_mode":"lite","verdict":"PASS"}],
"phase3_dispatched":["devflow:code-reviewer"],
"phase3_findings":[{"agent":"devflow:code-reviewer","corroboration_count":1,"fix_decision":"applied"}],
"convergence_inputs":{"fixes_applied":1},"telemetry":{"phase_3":{"calls":1,"tokens":1000,"wall_clock_s":10}}}
EOF
# A non-iter scratch sibling confirms the durable copy carries *.json siblings,
# while discovery/derivation key only off iter-*.json.
printf '{"deferrals":[]}' > "$ETP_RUN/deferrals.json"

ETP_BEFORE_STATUS="$(git -C "$ETP_REPO" status --porcelain)"
ETP_BEFORE_HEAD="$(git -C "$ETP_REPO" rev-parse HEAD)"
ETP_BEFORE_BRANCH="$(git -C "$ETP_REPO" branch --show-current)"
# --persist (discovery): derive the record + durable copy → telemetry branch + push.
( cd "$ETP_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; ETP_RC=$?
assert_eq "et-persist: always exits 0" "0" "$ETP_RC"
# AC1/AC2: current branch, HEAD, and working tree are byte-for-byte untouched.
assert_eq "et-persist(#441): current branch tip unchanged (no commit on the feature branch)" \
  "$ETP_BEFORE_HEAD" "$(git -C "$ETP_REPO" rev-parse HEAD)"
assert_eq "et-persist(#441): current branch name unchanged" \
  "$ETP_BEFORE_BRANCH" "$(git -C "$ETP_REPO" branch --show-current)"
assert_eq "et-persist(#441): git status byte-for-byte unchanged (no working-tree residue)" \
  "$ETP_BEFORE_STATUS" "$(git -C "$ETP_REPO" status --porcelain)"
# AC1/AC3: the record + durable copy live on the telemetry branch.
assert_eq "et-persist(#441): record written to the telemetry branch at the run-id-keyed path" "yes" \
  "$(_et_on_branch "$ETP_REPO" ".prflow/logs/efficiency/pr-77-run-abc.json")"
assert_eq "et-persist(#441): durable workpad copy written to the telemetry branch" "yes" \
  "$(_et_on_branch "$ETP_REPO" ".prflow/logs/review/pr-77/run-abc/iter-1.json")"
assert_eq "et-persist(#441): durable copy carries deferrals.json sibling on the branch" "yes" \
  "$(_et_on_branch "$ETP_REPO" ".prflow/logs/review/pr-77/run-abc/deferrals.json")"
assert_eq "et-persist(#441): telemetry-branch tip subject is the chore: persist message" \
  "chore: persist review-and-fix observability artifacts" \
  "$(git -C "$ETP_REPO" log -1 --format=%s refs/heads/prflow-telemetry)"
# AC3: the telemetry branch is an orphan (shares NO history with main).
assert_eq "et-persist(#441): telemetry branch is an orphan (no merge-base with main)" "" \
  "$(git -C "$ETP_REPO" merge-base refs/heads/prflow-telemetry main 2>/dev/null || true)"
assert_eq "et-persist(#441): branch record is a real derivation (schema_version)" "1" \
  "$(_et_show "$ETP_REPO" ".prflow/logs/efficiency/pr-77-run-abc.json" | jq -r '.schema_version')"
# AC6 (basic push): the branch reached the remote.
assert_eq "et-persist(#441): telemetry branch was pushed to the remote" "yes" \
  "$(git -C "$ETP_REPO" ls-remote --heads origin prflow-telemetry | grep -q prflow-telemetry && echo yes || echo no)"

# --persist idempotency (AC14): a second run makes NO new branch commit and does
# not re-derive the record (generated_at stays stable).
ETP_BC1="$(_et_branch_count "$ETP_REPO")"
ETP_GEN1="$(_et_show "$ETP_REPO" ".prflow/logs/efficiency/pr-77-run-abc.json" | jq -r '.generated_at')"
( cd "$ETP_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; ETP_RC2=$?
assert_eq "et-persist: re-run exits 0" "0" "$ETP_RC2"
assert_eq "et-persist(#441): re-run creates NO new branch commit (idempotent)" \
  "$ETP_BC1" "$(_et_branch_count "$ETP_REPO")"
assert_eq "et-persist(#441): re-run does NOT re-derive the record (generated_at frozen)" \
  "$ETP_GEN1" "$(_et_show "$ETP_REPO" ".prflow/logs/efficiency/pr-77-run-abc.json" | jq -r '.generated_at')"

# AC7 (unpushable remote → local ref still advances, exit 0, ::warning::). Point
# origin at a non-existent path so the push fails but the local ref carries the run.
ETP_NOPUSH_REPO="$(git_sandbox "et-persist unpushable repo")"
git -C "$ETP_NOPUSH_REPO" init -q
git -C "$ETP_NOPUSH_REPO" config user.email t@e.com; git -C "$ETP_NOPUSH_REPO" config user.name t
git -C "$ETP_NOPUSH_REPO" remote add origin /nonexistent/telemetry/remote.git
mkdir -p "$ETP_NOPUSH_REPO/.prflow"; printf 'tmp/\n' > "$ETP_NOPUSH_REPO/.prflow/.gitignore"
git -C "$ETP_NOPUSH_REPO" add -A; git -C "$ETP_NOPUSH_REPO" commit -qm seed
mkdir -p "$ETP_NOPUSH_REPO/.prflow/tmp/review/pr-8/run-np"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_NOPUSH_REPO/.prflow/tmp/review/pr-8/run-np/iter-1.json"
ETP_NP_ERR="$( ( cd "$ETP_NOPUSH_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETP_NP_RC=$?
assert_eq "et-persist(#441 AC7): unpushable remote → exit 0" "0" "$ETP_NP_RC"
assert_eq "et-persist(#441 AC7): unpushable remote → local telemetry ref STILL advanced" "yes" \
  "$(_et_on_branch "$ETP_NOPUSH_REPO" ".prflow/logs/efficiency/pr-8-run-np.json")"
assert_eq "et-persist(#441 AC7): unpushable remote → a ::warning:: breadcrumb is emitted" "yes" \
  "$(printf '%s' "$ETP_NP_ERR" | grep -qF '::warning::telemetry-branch:' && echo yes || echo no)"
rm -rf "$ETP_NOPUSH_REPO"

# AC6 (the headline mechanism): a REMOTE-AHEAD push → non-ff rejection → fetch →
# re-parent-on-fetched-tip → re-push. The et-persist push above only ever
# fast-forwards a fresh remote, so it never enters the retry loop; this test forces
# it by advancing the remote's telemetry ref from a second clone between our runs.
ETP_R6_BARE="$(git_sandbox "et-persist AC6 bare remote")"
git -C "$ETP_R6_BARE" init --bare -q
ETP_R6="$(git_sandbox "et-persist AC6 repo")"
git -C "$ETP_R6" init -q
git -C "$ETP_R6" config user.email t@e.com; git -C "$ETP_R6" config user.name t
git -C "$ETP_R6" remote add origin "$ETP_R6_BARE"
mkdir -p "$ETP_R6/.prflow"; printf 'tmp/\n' > "$ETP_R6/.prflow/.gitignore"
git -C "$ETP_R6" add -A; git -C "$ETP_R6" commit -qm seed; git -C "$ETP_R6" branch -M main
git -C "$ETP_R6" push -q -u origin main
# Run A creates + pushes the telemetry branch.
mkdir -p "$ETP_R6/.prflow/tmp/review/pr-a/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_R6/.prflow/tmp/review/pr-a/run-a/iter-1.json"
( cd "$ETP_R6" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
# A SECOND writer (clone) advances the REMOTE telemetry ref with a sibling record B,
# so the local ref is now behind the remote.
ETP_R6_C2="$(git_sandbox "et-persist AC6 second writer")"
git clone -q "$ETP_R6_BARE" "$ETP_R6_C2" 2>/dev/null
git -C "$ETP_R6_C2" config user.email x@y; git -C "$ETP_R6_C2" config user.name x
git -C "$ETP_R6_C2" fetch -q origin prflow-telemetry:prflow-telemetry
ETP_R6_IDX="$ETP_R6_C2/.git/ac6idx"; ETP_R6_TIP="$(git -C "$ETP_R6_C2" rev-parse prflow-telemetry)"
GIT_INDEX_FILE="$ETP_R6_IDX" git -C "$ETP_R6_C2" read-tree prflow-telemetry
ETP_R6_B="$(printf '{"s":"B"}' | git -C "$ETP_R6_C2" hash-object -w --stdin)"
GIT_INDEX_FILE="$ETP_R6_IDX" git -C "$ETP_R6_C2" update-index --add --cacheinfo "100644,${ETP_R6_B},.prflow/logs/efficiency/pr-b-run-b.json"
ETP_R6_T="$(GIT_INDEX_FILE="$ETP_R6_IDX" git -C "$ETP_R6_C2" write-tree)"; rm -f "$ETP_R6_IDX"
ETP_R6_N="$(GIT_AUTHOR_NAME=x GIT_AUTHOR_EMAIL=x@y GIT_COMMITTER_NAME=x GIT_COMMITTER_EMAIL=x@y git -C "$ETP_R6_C2" commit-tree "$ETP_R6_T" -p "$ETP_R6_TIP" -m sibling)"
git -C "$ETP_R6_C2" update-ref refs/heads/prflow-telemetry "$ETP_R6_N" "$ETP_R6_TIP"
git -C "$ETP_R6_C2" push -q origin prflow-telemetry
# Run C locally: its first push is rejected non-ff → the helper fetches, re-parents C
# on B's tip, and re-pushes. All of A, B, C must land on the REMOTE with no clobber.
mkdir -p "$ETP_R6/.prflow/tmp/review/pr-c/run-c"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_R6/.prflow/tmp/review/pr-c/run-c/iter-1.json"
ETP_R6_RC=$( ( cd "$ETP_R6" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; echo $? )
assert_eq "et-persist(#441 AC6): remote-ahead push → exit 0 (retry loop, not abort)" "0" "$ETP_R6_RC"
git -C "$ETP_R6" fetch -q origin prflow-telemetry:refs/remotes/origin/ac6 2>/dev/null
for _ac6f in pr-a-run-a pr-b-run-b pr-c-run-c; do
  assert_eq "et-persist(#441 AC6): remote carries ${_ac6f} after fetch/re-parent/re-push (no clobber)" "yes" \
    "$(git -C "$ETP_R6" cat-file -e "refs/remotes/origin/ac6:.prflow/logs/efficiency/${_ac6f}.json" >/dev/null 2>&1 && echo yes || echo no)"
done
rm -rf "$ETP_R6" "$ETP_R6_BARE" "$ETP_R6_C2"

# Offline-accumulated-record survival (cloud-review Important-1, the highest-value
# regression): a record persisted while the remote was UNREACHABLE lives only on the
# local ref. When a later run reconnects and the remote has since diverged, the push
# re-parent must UNION the local tip with the fetched remote tip — NOT re-apply only
# the current run's staged files, which would orphan the offline-accumulated record.
ETP_OA_BARE="$(git_sandbox "et-persist offline-accum bare")"
git -C "$ETP_OA_BARE" init --bare -q
ETP_OA="$(git_sandbox "et-persist offline-accum repo")"
git -C "$ETP_OA" init -q
git -C "$ETP_OA" config user.email t@e.com; git -C "$ETP_OA" config user.name t
git -C "$ETP_OA" remote add origin "$ETP_OA_BARE"
mkdir -p "$ETP_OA/.prflow"; printf 'tmp/\n' > "$ETP_OA/.prflow/.gitignore"
git -C "$ETP_OA" add -A; git -C "$ETP_OA" commit -qm seed; git -C "$ETP_OA" branch -M main
git -C "$ETP_OA" push -q -u origin main
# Run A persists while the remote is UNREACHABLE (move the bare repo aside) → the
# record lands on the local ref only; the push fails best-effort.
mv "$ETP_OA_BARE" "${ETP_OA_BARE}.down"
mkdir -p "$ETP_OA/.prflow/tmp/review/pr-a/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_OA/.prflow/tmp/review/pr-a/run-a/iter-1.json"
( cd "$ETP_OA" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "et-persist(#441 offline-accum): run A record is on the LOCAL ref while the remote is down" "yes" \
  "$(_et_on_branch "$ETP_OA" ".prflow/logs/efficiency/pr-a-run-a.json")"
mv "${ETP_OA_BARE}.down" "$ETP_OA_BARE"
# A second writer CREATES the remote telemetry branch with an unrelated record X.
ETP_OA_C2="$(git_sandbox "et-persist offline-accum writer2")"
git clone -q "$ETP_OA_BARE" "$ETP_OA_C2" 2>/dev/null
ETP_OA_IDX="$ETP_OA_C2/.git/oaidx"
ETP_OA_XB="$(printf '{"s":"X"}' | git -C "$ETP_OA_C2" hash-object -w --stdin)"
GIT_INDEX_FILE="$ETP_OA_IDX" git -C "$ETP_OA_C2" update-index --add --cacheinfo "100644,${ETP_OA_XB},.prflow/logs/efficiency/pr-x-run-x.json"
ETP_OA_XT="$(GIT_INDEX_FILE="$ETP_OA_IDX" git -C "$ETP_OA_C2" write-tree)"; rm -f "$ETP_OA_IDX"
ETP_OA_XN="$(GIT_AUTHOR_NAME=x GIT_AUTHOR_EMAIL=x@y GIT_COMMITTER_NAME=x GIT_COMMITTER_EMAIL=x@y git -C "$ETP_OA_C2" commit-tree "$ETP_OA_XT" -m x)"
git -C "$ETP_OA_C2" update-ref refs/heads/prflow-telemetry "$ETP_OA_XN"
git -C "$ETP_OA_C2" push -q origin prflow-telemetry
# Run B reconnects: its push is rejected (remote diverged), so it fetches, re-parents
# the UNION of the local tip (offline A + this run B) and the remote tip (X), and pushes.
mkdir -p "$ETP_OA/.prflow/tmp/review/pr-b/run-b"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_OA/.prflow/tmp/review/pr-b/run-b/iter-1.json"
( cd "$ETP_OA" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
git -C "$ETP_OA" fetch -q origin prflow-telemetry:refs/remotes/origin/oa 2>/dev/null
for _oaf in pr-a-run-a pr-b-run-b pr-x-run-x; do
  assert_eq "et-persist(#441 offline-accum): remote carries ${_oaf} after reconnect re-parent (no orphaned offline record)" "yes" \
    "$(git -C "$ETP_OA" cat-file -e "refs/remotes/origin/oa:.prflow/logs/efficiency/${_oaf}.json" >/dev/null 2>&1 && echo yes || echo no)"
done
rm -rf "$ETP_OA" "$ETP_OA_BARE" "$ETP_OA_C2"

# Remote-first non-telemetry same-named branch (cloud-review Important-1, PR #442 —
# the AC4 guarantee on the PUSH path): a consumer's REMOTE `prflow-telemetry` holds
# non-telemetry content and was never fetched locally, so the pre-write verify_store
# passes vacuously (no local ref), a local orphan is built, and the push is rejected
# non-ff. The rejection arm fetches the consumer's tip — which must be RE-VERIFIED as
# a telemetry store before the union re-parent, so DevFlow never commits onto (or
# pushes over) that branch. Positive control: the offline-accum test above is the
# same fixture shape with a TELEMETRY-shaped remote tip, where the rejection arm
# correctly re-parents and pushes — so the refusal below is attributable to the
# store re-verification, not to the rejection path being broken.
ETP_RN_BARE="$(git_sandbox "et-persist remote non-telemetry bare")"
git -C "$ETP_RN_BARE" init --bare -q
ETP_RN="$(git_sandbox "et-persist remote non-telemetry repo")"
git -C "$ETP_RN" init -q
git -C "$ETP_RN" config user.email t@e.com; git -C "$ETP_RN" config user.name t
git -C "$ETP_RN" remote add origin "$ETP_RN_BARE"
mkdir -p "$ETP_RN/.prflow"; printf 'tmp/\n' > "$ETP_RN/.prflow/.gitignore"
git -C "$ETP_RN" add -A; git -C "$ETP_RN" commit -qm seed; git -C "$ETP_RN" branch -M main
git -C "$ETP_RN" push -q -u origin main
# The consumer's remote-only same-named branch: main's tree (non-.prflow/logs/ paths).
git -C "$ETP_RN" push -q origin main:refs/heads/prflow-telemetry
ETP_RN_TIP="$(git -C "$ETP_RN_BARE" rev-parse refs/heads/prflow-telemetry)"
mkdir -p "$ETP_RN/.prflow/tmp/review/pr-a/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_RN/.prflow/tmp/review/pr-a/run-a/iter-1.json"
ETP_RN_ERR="$( ( cd "$ETP_RN" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETP_RN_RC=$?
assert_eq "et-persist(#442 push-path AC4): remote non-telemetry same-named branch → exit 0 (best-effort)" "0" "$ETP_RN_RC"
assert_eq "et-persist(#442 push-path AC4): consumer's remote branch is left UNTOUCHED (no push over it)" \
  "$ETP_RN_TIP" "$(git -C "$ETP_RN_BARE" rev-parse refs/heads/prflow-telemetry)"
assert_eq "et-persist(#442 push-path AC4): the refusal is the rejection-arm store re-verification (attributed breadcrumb)" "yes" \
  "$(printf '%s' "$ETP_RN_ERR" | grep -qF 'refusing to re-parent onto or push over it' && echo yes || echo no)"
assert_eq "et-persist(#442 push-path AC4): the run's record is retained on the LOCAL ref" "yes" \
  "$(_et_on_branch "$ETP_RN" ".prflow/logs/efficiency/pr-a-run-a.json")"
rm -rf "$ETP_RN" "$ETP_RN_BARE"

# (cloud-review PR #442 Suggestion-round deferrals, recorded per receiving-code-review:
# (a) the committer-identity fallback (AC8: GIT_AUTHOR_*/GIT_COMMITTER_* on a checkout
# with no user.email) is accepted-untested — every fixture sets user.email because
# git_sandbox seeds need commits of their own; a no-identity fixture would need its
# seed commits made with one-shot env identities throughout, disproportionate for a
# deterministic constant-env code path that AC6/offline-accum already execute.
# (b) the temp-index EXIT-trap cleanup on ABNORMAL exit (killing the persist subshell
# mid-flight) is accepted-untested — a deterministic mid-plumbing kill needs signal
# interposition inside the subshell; the trap itself is exercised on every normal-exit
# path by all telemetry tests. (c) fixture teardown matches the repo-wide mktemp -d
# isolation convention. Revisit any of these if the respective path regresses in the field.)

# (cloud-review Suggestion-3b/3c — the push-retry NOOP-re-parent arm and the
# rejection-then-follow-up-fetch-fails arm — are accepted-untested: both require a
# mid-retry race (a remote that rejects a push and then becomes unreadable, or a
# remote whose tip already carries exactly our re-parented content) that cannot be
# forced deterministically without git-hook interposition, disproportionate for a
# Suggestion-level defensive arm. Both arms are code-verified and best-effort exit-0;
# the AC6 + offline-accum tests exercise the primary re-parent path.)

# Source-failure no-op-stub degrade (cloud-review Suggestion-3a): a vendored deploy
# whose lib/ is missing telemetry-branch.sh must exit 0 on --persist and breadcrumb
# that the staged artifacts were discarded (validating the SFH-3 sentinel gate — the
# warning is REACHABLE, not shadowed by an always-defined stub).
ETP_NS_LIB="$(git_sandbox "et-persist no-telemetry-lib")"
cp -p "$LIB"/*.sh "$LIB"/*.jq "$ETP_NS_LIB"/ 2>/dev/null
rm -f "$ETP_NS_LIB/telemetry-branch.sh"   # the vendored-deploy-missing-lib scenario
ETP_NS_REPO="$(git_sandbox "et-persist no-lib repo")"
git -C "$ETP_NS_REPO" init -q
git -C "$ETP_NS_REPO" config user.email t@e.com; git -C "$ETP_NS_REPO" config user.name t
# Give the source-failure path a real remote tip so do_persist reaches the
# verify_store call. Without this producer the undefined-stub assertion below
# would pass vacuously because the short-circuit never invokes verify_store.
ETP_NS_BARE="$(git_sandbox "et-persist no-lib bare remote")"; git -C "$ETP_NS_BARE" init --bare -q
ETP_NS_SEED="$(git_sandbox "et-persist no-lib remote seed")"; git -C "$ETP_NS_SEED" init -q
git -C "$ETP_NS_SEED" config user.email t@e.com; git -C "$ETP_NS_SEED" config user.name t
printf 'not a telemetry store\n' > "$ETP_NS_SEED/random.txt"
git -C "$ETP_NS_SEED" add -A; git -C "$ETP_NS_SEED" commit -qm seed
git -C "$ETP_NS_SEED" push -q "$ETP_NS_BARE" HEAD:refs/heads/prflow-telemetry
git -C "$ETP_NS_REPO" remote add origin "$ETP_NS_BARE"
mkdir -p "$ETP_NS_REPO/.prflow"; printf 'tmp/\n' > "$ETP_NS_REPO/.prflow/.gitignore"
git -C "$ETP_NS_REPO" add -A; git -C "$ETP_NS_REPO" commit -qm seed
mkdir -p "$ETP_NS_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETP_NS_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
ETP_NS_ERR="$( ( cd "$ETP_NS_REPO" && bash "$ETP_NS_LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETP_NS_RC=$?
assert_eq "et-persist(#441 Sug-3a): lib missing telemetry-branch.sh → --persist exits 0" "0" "$ETP_NS_RC"
assert_eq "et-persist(#441 Sug-3a): the persist-time 'staged artifacts discarded' warning IS reachable" "yes" \
  "$(printf '%s' "$ETP_NS_ERR" | grep -qF 'staged artifacts under' && echo yes || echo no)"
assert_eq "#469 source-failure stubs: missing telemetry-branch.sh degrades without an undefined verify_store call" "no" \
  "$(printf '%s' "$ETP_NS_ERR" | grep -qF 'devflow_telemetry_verify_store: command not found' && echo yes || echo no)"
assert_eq "et-persist(#441 Sug-3a): lib-missing → no telemetry ref created" "no" \
  "$(git -C "$ETP_NS_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$ETP_NS_LIB" "$ETP_NS_REPO" "$ETP_NS_BARE" "$ETP_NS_SEED"

# --persist telemetry OFF: no record derived, but the durable copy still persists
# to the branch (the durable copy is writable-run-gated, not telemetry-gated).
ETP_OFF_REPO="$(git_sandbox "et-persist telemetry-off repo")"
git -C "$ETP_OFF_REPO" init -q
git -C "$ETP_OFF_REPO" config user.email t@e.com; git -C "$ETP_OFF_REPO" config user.name t
mkdir -p "$ETP_OFF_REPO/.prflow/tmp/review/pr-9/run-x"
cp "$ETP_RUN/iter-1.json" "$ETP_OFF_REPO/.prflow/tmp/review/pr-9/run-x/iter-1.json"
ETP_OFF_CFG="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$ETP_OFF_CFG"
( cd "$ETP_OFF_REPO" && DEVFLOW_CONFIG_FILE="$ETP_OFF_CFG" bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "et-persist: telemetry off → NO efficiency record on the branch" "no" \
  "$(_et_on_branch "$ETP_OFF_REPO" ".prflow/logs/efficiency/pr-9-run-x.json")"
assert_eq "et-persist: telemetry off → durable copy STILL made on the branch" "yes" \
  "$(_et_on_branch "$ETP_OFF_REPO" ".prflow/logs/review/pr-9/run-x/iter-1.json")"
rm -f "$ETP_OFF_CFG"; rm -rf "$ETP_OFF_REPO"

# --persist review-mode run (source=="review"): as of #441 this is UNIFIED — a
# standalone /devflow:review run is persisted through the SAME path to the SAME
# branch (the former source=="review" skip is gone).
ETP_REV_REPO="$(git_sandbox "et-persist review-mode repo")"
git -C "$ETP_REV_REPO" init -q
git -C "$ETP_REV_REPO" config user.email t@e.com; git -C "$ETP_REV_REPO" config user.name t
mkdir -p "$ETP_REV_REPO/.prflow/tmp/review/pr-5/run-r"
printf '{"iter":1,"source":"review","phase3_findings":[]}' \
  > "$ETP_REV_REPO/.prflow/tmp/review/pr-5/run-r/iter-1.json"
( cd "$ETP_REV_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "et-persist(#441): review-mode run IS persisted to the branch (source-skip removed)" "yes" \
  "$(_et_on_branch "$ETP_REV_REPO" ".prflow/logs/efficiency/pr-5-run-r.json")"
assert_eq "et-persist(#441): review-mode run's durable copy IS on the branch" "yes" \
  "$(_et_on_branch "$ETP_REV_REPO" ".prflow/logs/review/pr-5/run-r/iter-1.json")"
rm -rf "$ETP_REV_REPO"

# --persist malformed-only workpad (non-object) → exit 0, no record written.
ETP_BAD_REPO="$(git_sandbox "et-persist malformed-workpad repo")"
git -C "$ETP_BAD_REPO" init -q
git -C "$ETP_BAD_REPO" config user.email t@e.com; git -C "$ETP_BAD_REPO" config user.name t
mkdir -p "$ETP_BAD_REPO/.prflow/tmp/review/pr-3/run-b"
printf '[]' > "$ETP_BAD_REPO/.prflow/tmp/review/pr-3/run-b/iter-1.json"
( cd "$ETP_BAD_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; ETP_BAD_RC=$?
assert_eq "et-persist: malformed-only workpad → exit 0" "0" "$ETP_BAD_RC"
assert_eq "et-persist: malformed-only workpad → no record (empty derivation)" "no" \
  "$(_et_on_branch "$ETP_BAD_REPO" ".prflow/logs/efficiency/pr-3-run-b.json")"
rm -rf "$ETP_BAD_REPO"

# --persist with no review activity at all → clean no-op (no branch created).
ETP_EMPTY_REPO="$(git_sandbox "et-persist no-activity repo")"
git -C "$ETP_EMPTY_REPO" init -q
git -C "$ETP_EMPTY_REPO" config user.email t@e.com; git -C "$ETP_EMPTY_REPO" config user.name t
( cd "$ETP_EMPTY_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; ETP_EMPTY_RC=$?
assert_eq "et-persist: no review activity → exit 0" "0" "$ETP_EMPTY_RC"
assert_eq "et-persist(#441): no review activity → no telemetry branch created" "no" \
  "$(git -C "$ETP_EMPTY_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$ETP_EMPTY_REPO"

# --self-check (warn-only). Telemetry-off silence is the shell-enforceable half
# of the AC's "silent when telemetry disabled / read-only"; read-only silence is
# structural — SKILL.md only invokes the self-check on writable runs.
ETSC_REPO="$(git_sandbox "et-selfcheck repo")"
git -C "$ETSC_REPO" init -q
ETSC_RUN="$ETSC_REPO/.prflow/tmp/review/pr-12/run-y"
mkdir -p "$ETSC_RUN"
printf '{"iter":1,"phase3_findings":[]}' > "$ETSC_RUN/iter-1.json"
ETSC_OUT="$( ( cd "$ETSC_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC_RUN" --slug pr-12 ) 2>&1 )"; ETSC_RC=$?
assert_eq "et-selfcheck: always exits 0" "0" "$ETSC_RC"
assert_eq "et-selfcheck: workpads present but no record → warns 'was NOT persisted'" "yes" \
  "$(printf '%s' "$ETSC_OUT" | grep -qF 'was NOT persisted' && echo yes || echo no)"
assert_eq "et-selfcheck: warning names the run-id-keyed record path" "yes" \
  "$(printf '%s' "$ETSC_OUT" | grep -qF 'pr-12-run-y.json' && echo yes || echo no)"
ETSC_EMPTY="$ETSC_REPO/.prflow/tmp/review/pr-12/run-empty"
mkdir -p "$ETSC_EMPTY"
ETSC_OUT2="$( ( cd "$ETSC_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC_EMPTY" --slug pr-12 ) 2>&1 )"
assert_eq "et-selfcheck: zero workpads → warns NO iter-*.json captured" "yes" \
  "$(printf '%s' "$ETSC_OUT2" | grep -qF 'NO iter-*.json workpad' && echo yes || echo no)"
ETSC_OFF_CFG="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$ETSC_OFF_CFG"
ETSC_OUT3="$( ( cd "$ETSC_REPO" && DEVFLOW_CONFIG_FILE="$ETSC_OFF_CFG" bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC_RUN" --slug pr-12 ) 2>&1 )"
assert_eq "et-selfcheck: telemetry disabled → silent (no warning)" "" "$ETSC_OUT3"
# --self-check on a --workpad-dir that does not exist at all (the `! -d` half of
# the guard, distinct from the empty-but-existing dir above).
ETSC_OUT4="$( ( cd "$ETSC_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC_REPO/.prflow/tmp/review/pr-12/nope" --slug pr-12 ) 2>&1 )"; ETSC_RC4=$?
assert_eq "et-selfcheck: nonexistent workpad dir → exit 0" "0" "$ETSC_RC4"
assert_eq "et-selfcheck: nonexistent workpad dir → warns NO iter-*.json" "yes" \
  "$(printf '%s' "$ETSC_OUT4" | grep -qF 'NO iter-*.json workpad' && echo yes || echo no)"
rm -f "$ETSC_OFF_CFG"; rm -rf "$ETSC_REPO" "$ETP_REPO" "$ETP_BARE"

# A minimal valid review-and-fix iter workpad (no `source` → defaults review-and-fix).
ETP_ITER='{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}'

# --persist TARGETED mode (--workpad-dir/--slug): exercises do_persist's first
# branch (slug from --slug, run-id from the workpad-dir basename) — discovery
# never reaches it.
ETPT_REPO="$(git_sandbox "et-persist targeted repo")"
git -C "$ETPT_REPO" init -q
git -C "$ETPT_REPO" config user.email t@e.com; git -C "$ETPT_REPO" config user.name t
mkdir -p "$ETPT_REPO/.prflow/tmp/review/pr-22/run-t"
printf '%s' "$ETP_ITER" > "$ETPT_REPO/.prflow/tmp/review/pr-22/run-t/iter-1.json"
( cd "$ETPT_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPT_REPO/.prflow/tmp/review/pr-22/run-t" --slug pr-22 ) >/dev/null 2>&1
assert_eq "et-persist: targeted --workpad-dir/--slug writes the run-id-keyed record (on the branch)" "yes" \
  "$(_et_on_branch "$ETPT_REPO" ".prflow/logs/efficiency/pr-22-run-t.json")"
# --slug ABSENT → slug falls back to basename(dirname(workpad-dir)).
mkdir -p "$ETPT_REPO/.prflow/tmp/review/pr-23/run-u"
printf '%s' "$ETP_ITER" > "$ETPT_REPO/.prflow/tmp/review/pr-23/run-u/iter-1.json"
( cd "$ETPT_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPT_REPO/.prflow/tmp/review/pr-23/run-u" ) >/dev/null 2>&1
assert_eq "et-persist: targeted --slug-absent → slug from parent dir name (on the branch)" "yes" \
  "$(_et_on_branch "$ETPT_REPO" ".prflow/logs/efficiency/pr-23-run-u.json")"
rm -rf "$ETPT_REPO"

# ── issue #475: harness-side cost floor — merge the execution_file's cost into
# per-run efficiency records through --persist (reader + merge/skeleton arms +
# merge-aware union + glue) ───────────────────────────────────────────────────
echo "harness-side cost floor (issue #475)"
HC_READER="$LIB/../scripts/extract-execution-cost.py"
HC_GLUE="$LIB/../scripts/prepare-harness-floor.sh"
# The reader's normalized JSON, as the glue would hand it to --persist.
HC_COST='{"cost_usd":0.42,"tokens":{"input_tokens":150,"output_tokens":5,"cache_read_input_tokens":null,"cache_creation_input_tokens":null,"total_tokens":105},"model_usage":{"m":{"x":1}},"num_turns":9,"duration_ms":8000}'

# ── A1/A2: the reader over the full adversarial input matrix ──────────────────
HC_FX="$(git_sandbox "hc reader fixtures")"
# valid-falsy boundary (AC1): costUSD:0 → cost_usd:0 ; key absent → cost_usd:null.
printf '%s' '{"type":"result","costUSD":0,"num_turns":3,"duration_ms":12}' > "$HC_FX/cost0.json"
assert_eq "hc-reader(A1): costUSD:0 → cost_usd:0 (valid-falsy, never coerced to null)" "0" \
  "$(python3 "$HC_READER" "$HC_FX/cost0.json" 2>/dev/null | jq -c '.cost_usd')"
printf '%s' '{"type":"result","num_turns":3}' > "$HC_FX/costabsent.json"
assert_eq "hc-reader(A1): cost key absent → cost_usd:null (unknown-is-not-zero)" "null" \
  "$(python3 "$HC_READER" "$HC_FX/costabsent.json" 2>/dev/null | jq -c '.cost_usd')"
# array shape + per-message usage accumulation.
printf '%s' '[{"usage":{"input_tokens":100,"total_tokens":105}},{"usage":{"input_tokens":50,"cache_read_input_tokens":7}},{"type":"result","total_cost_usd":1.5,"num_turns":9}]' > "$HC_FX/arr.json"
assert_eq "hc-reader(A2): array shape → cost from result event" "1.5" \
  "$(python3 "$HC_READER" "$HC_FX/arr.json" 2>/dev/null | jq -c '.cost_usd')"
assert_eq "hc-reader(A2): per-message usage input_tokens summed across events" "150" \
  "$(python3 "$HC_READER" "$HC_FX/arr.json" 2>/dev/null | jq -c '.tokens.input_tokens')"
assert_eq "hc-reader(A2): a token never seen stays null (not 0)" "null" \
  "$(python3 "$HC_READER" "$HC_FX/arr.json" 2>/dev/null | jq -c '.tokens.output_tokens')"
# A2 (token double-count, issue #475 review): when the file carries BOTH per-message
# `usage` AND a result-summary cumulative `usage`, the reader must take the AUTHORITATIVE
# result total — NOT sum per-message + result (the double-count bug). Here per-message sums
# to 300 but the result cumulative is 500 (cache accounting differs), so the three possible
# impls are distinguishable: correct(prefer-result)=500, old-bug(sum-all)=800,
# fallback-only(sum-per-message)=300. Pinning ==500 fails RED against both wrong impls.
printf '%s' '[{"type":"assistant","message":{"usage":{"input_tokens":100}}},{"type":"assistant","message":{"usage":{"input_tokens":200}}},{"type":"result","total_cost_usd":3,"usage":{"input_tokens":500,"output_tokens":42}}]' > "$HC_FX/dualusage.json"
assert_eq "hc-reader(A2): result-summary usage is authoritative (no per-message double-count)" "500" \
  "$(python3 "$HC_READER" "$HC_FX/dualusage.json" 2>/dev/null | jq -c '.tokens.input_tokens')"
assert_eq "hc-reader(A2): a token present only on the result-summary usage is read (output=42)" "42" \
  "$(python3 "$HC_READER" "$HC_FX/dualusage.json" 2>/dev/null | jq -c '.tokens.output_tokens')"
# JSONL shape.
printf '%s\n%s\n' '{"usage":{"input_tokens":9}}' '{"type":"result","total_cost_usd":2}' > "$HC_FX/lines.json"
assert_eq "hc-reader(A2): JSONL shape tolerated → cost read" "2" \
  "$(python3 "$HC_READER" "$HC_FX/lines.json" 2>/dev/null | jq -c '.cost_usd')"
# scalar: parses but no figures → all-null object printed, exit 0.
printf '42' > "$HC_FX/scalar.json"
assert_eq "hc-reader(A2): scalar parses but lacks figures → prints an all-null object" "null" \
  "$(python3 "$HC_READER" "$HC_FX/scalar.json" 2>/dev/null | jq -c '.cost_usd')"
HC_SCALAR_ERR="$(python3 "$HC_READER" "$HC_FX/scalar.json" 2>&1 1>/dev/null)"
assert_eq "hc-reader(A2): scalar shape → a specific stderr breadcrumb" "yes" \
  "$(printf '%s' "$HC_SCALAR_ERR" | grep -qF 'scalar' && echo yes || echo no)"
# wrong-type fields: each is treated as absent while a sibling numeric value still reads.
printf '%s' '[{"type":"result","costUSD":"abc","duration_ms":900}]' > "$HC_FX/wrong.json"
assert_eq "hc-reader(A2): wrong-type cost field → null (treated as absent)" "null" \
  "$(python3 "$HC_READER" "$HC_FX/wrong.json" 2>/dev/null | jq -c '.cost_usd')"
assert_eq "hc-reader(A2): a sibling numeric field is still read past a wrong-type one" "900" \
  "$(python3 "$HC_READER" "$HC_FX/wrong.json" 2>/dev/null | jq -c '.duration_ms')"
# AC2 breadcrumb-specificity: every abnormal shape must draw its OWN specific breadcrumb
# (the never-silent discipline), not merely exit 0 — a swapped/dropped breadcrumb string
# on any arm would otherwise ship green.
assert_eq "hc-reader(A2): wrong-type field → its specific 'not a numeric figure' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_FX/wrong.json" 2>&1 1>/dev/null | grep -qF 'not a numeric figure' && echo yes || echo no)"
# missing file → cannot parse at all → prints NOTHING, exit 0.
assert_eq "hc-reader(A2): missing file → prints nothing (cannot parse at all)" "" \
  "$(python3 "$HC_READER" "$HC_FX/does-not-exist.json" 2>/dev/null)"
HC_MISS_RC=0; python3 "$HC_READER" "$HC_FX/does-not-exist.json" >/dev/null 2>&1 || HC_MISS_RC=$?
assert_eq "hc-reader(A2): missing file → still exit 0 (best-effort)" "0" "$HC_MISS_RC"
assert_eq "hc-reader(A2): missing file → its specific 'could not be read' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_FX/does-not-exist.json" 2>&1 1>/dev/null | grep -qF 'could not be read' && echo yes || echo no)"
# empty file → distinct arm (prints nothing, its own 'is empty' breadcrumb, exit 0).
printf '' > "$HC_FX/empty.json"
assert_eq "hc-reader(A2): empty file → prints nothing" "" \
  "$(python3 "$HC_READER" "$HC_FX/empty.json" 2>/dev/null)"
assert_eq "hc-reader(A2): empty file → its specific 'is empty' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_FX/empty.json" 2>&1 1>/dev/null | grep -qF 'is empty' && echo yes || echo no)"
# garbage (not JSON, not JSONL) → prints nothing, exit 0.
printf '%s' 'not json { [ oops' > "$HC_FX/garbage.json"
assert_eq "hc-reader(A2): unparseable garbage → prints nothing" "" \
  "$(python3 "$HC_READER" "$HC_FX/garbage.json" 2>/dev/null)"
assert_eq "hc-reader(A2): unparseable garbage → its specific 'could not be parsed' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_FX/garbage.json" 2>&1 1>/dev/null | grep -qF 'could not be parsed as JSON or JSONL' && echo yes || echo no)"
rm -rf "$HC_FX"

# ── Shared scratch repo for the --persist floor arms ─────────────────────────
# $1 = a label; echoes the repo path. Seeds a repo with a bare remote so the
# branch write + push land somewhere real (mirrors the #441 et-persist harness).
_hc_repo() {
  local bare repo
  bare="$(git_sandbox "$1 bare")"; git -C "$bare" init --bare -q
  repo="$(git_sandbox "$1 repo")"; git -C "$repo" init -q
  git -C "$repo" config user.email t@e.com; git -C "$repo" config user.name t
  git -C "$repo" remote add origin "$bare"
  mkdir -p "$repo/.prflow"; printf 'tmp/\n' > "$repo/.prflow/.gitignore"
  git -C "$repo" add -A; git -C "$repo" commit -qm seed; git -C "$repo" branch -M main
  git -C "$repo" push -q -u origin main
  printf '%s\n' "$repo"
}
HC_ITER='{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{"phase_3":{"calls":1,"tokens":10,"wall_clock_s":1}}}'

# ── A3: run-id targeting + merge arm (a, staged this pass) ────────────────────
# Two run dirs with DISTINCT run-ids; only the one matching the env identity (999-1)
# gains harness_cost. The non-matching record's filename (pr-11-888-2.json) is chosen to
# sort ALPHABETICALLY BEFORE the matching one (pr-77-999-1.json) — load-bearing, do NOT
# renumber it back: the merge arm attaches to the FIRST glob match then returns, so if the
# glob were broadened to `*.json`, the FIRST match would be the non-matching pr-11 and the
# "matching gained harness_cost" assertion would fail RED. Were the matching record to sort
# first instead, a broadened-glob regression would still attach to it and the behavioral
# test would pass vacuously (issue #475 review, pr-test-analyzer) — the run-id targeting pin
# below catches the literal change, and this ordering makes the behavioral test catch it too.
HC_T="$(_hc_repo "hc target")"
mkdir -p "$HC_T/.prflow/tmp/review/pr-77/999-1" "$HC_T/.prflow/tmp/review/pr-11/888-2"
printf '%s' "$HC_ITER" > "$HC_T/.prflow/tmp/review/pr-77/999-1/iter-1.json"
printf '%s' "$HC_ITER" > "$HC_T/.prflow/tmp/review/pr-11/888-2/iter-1.json"
( cd "$HC_T" && GITHUB_RUN_ID=999 GITHUB_RUN_ATTEMPT=1 GITHUB_WORKFLOW_REF="o/r/.github/workflows/devflow.yml@refs/heads/main" \
    DEVFLOW_EXECUTION_COST="$HC_COST" DEVFLOW_COMMAND_CLASS=review-and-fix \
    bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "hc-merge(A3): the record matching the run-id identity gained harness_cost" "execution-file" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost.cost_source')"
assert_eq "hc-merge(A3): a record with a DIFFERENT run-id (sorting first) was NOT touched" "null" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-11-888-2.json" | jq -c '.harness_cost')"
# AC4: harness_cost carries exactly the required fields.
assert_eq "hc-merge(A4): harness_cost carries the required metadata + figures" \
  "command cost_source cost_usd duration_ms engine_version model_usage num_turns scope tokens workflow" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost | keys | join(" ")')"
assert_eq "hc-merge(A4): scope is whole-job" "whole-job" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost.scope')"
assert_eq "hc-merge(A4): command class recorded" "review-and-fix" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost.command')"
assert_eq "hc-merge(A4): workflow identity recorded from GITHUB_WORKFLOW_REF" "o/r/.github/workflows/devflow.yml@refs/heads/main" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost.workflow')"
assert_eq "hc-merge(A4): engine_version resolved from plugin.json beside the helper (a string)" "string" \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -r '.harness_cost.engine_version | type')"
# AC4 (spread join): the reader's OWN figures must land in harness_cost verbatim — the
# A4 key-set assertion above proves the keys exist but NOT that the values map through, so
# a mislabelled spread (e.g. cost_usd wired to .num_turns) would still pass it. HC_COST
# carries cost_usd:0.42, num_turns:9, duration_ms:8000, tokens.input_tokens:150.
assert_eq "hc-merge(A4): the reader's figures land in harness_cost verbatim (cost_usd/num_turns/duration_ms/tokens.input_tokens)" \
  '[0.42,9,8000,150]' \
  "$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | jq -c '[.harness_cost.cost_usd,.harness_cost.num_turns,.harness_cost.duration_ms,.harness_cost.tokens.input_tokens]')"
# AC9 (read side): _run_cost/_telemetry_complete unchanged by harness_cost; it is
# passed through verbatim as an entry key.
HC_RS="$(_et_show "$HC_T" ".prflow/logs/efficiency/pr-77-999-1.json" | python3 -c 'import importlib.util,sys,json
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.load(sys.stdin); e=m._efficiency_entry(r,"999-1")
print(json.dumps([e["harness_cost"]["cost_source"], m._run_cost(r), m._telemetry_complete(r)]))' "$LIB/../scripts/build-experiment-records.py" 2>/dev/null)"
assert_eq "hc-readside(A9): _efficiency_entry passes harness_cost through; _run_cost ignores it (reads only telemetry)" \
  '["execution-file", {"tokens": 10, "calls": 1, "wall_clock_s": 1}, true]' "$HC_RS"
rm -rf "$HC_T"

# ── A5: merge arm (b, already-persisted branch record) + byte-preservation ────
HC_M="$(_hc_repo "hc merge-branch")"
mkdir -p "$HC_M/.prflow/tmp/review/pr-5/777-1"
printf '%s' "$HC_ITER" > "$HC_M/.prflow/tmp/review/pr-5/777-1/iter-1.json"
# First persist WITHOUT the floor env → the record lands on the branch WITHOUT harness_cost.
( cd "$HC_M" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
HC_M_BEFORE="$(_et_show "$HC_M" ".prflow/logs/efficiency/pr-5-777-1.json")"
HC_M_GEN="$(printf '%s' "$HC_M_BEFORE" | jq -r '.generated_at')"
assert_eq "hc-merge-b(A5): pre-floor record has no harness_cost" "null" \
  "$(printf '%s' "$HC_M_BEFORE" | jq -c '.harness_cost')"
# Second persist WITH the floor env → persist_one skips re-derivation (record already
# on the branch), so the floor's merge arm (b) reads it back and adds harness_cost.
( cd "$HC_M" && GITHUB_RUN_ID=777 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
HC_M_AFTER="$(_et_show "$HC_M" ".prflow/logs/efficiency/pr-5-777-1.json")"
assert_eq "hc-merge-b(A5): already-persisted record gains harness_cost via read-back" "execution-file" \
  "$(printf '%s' "$HC_M_AFTER" | jq -r '.harness_cost.cost_source')"
assert_eq "hc-merge-b(A5): generated_at byte-preserved (not re-derived)" "$HC_M_GEN" \
  "$(printf '%s' "$HC_M_AFTER" | jq -r '.generated_at')"
assert_eq "hc-merge-b(A5): everything OUTSIDE harness_cost is byte-identical to the original" "yes" \
  "$(diff <(printf '%s' "$HC_M_AFTER" | jq 'del(.harness_cost)') <(printf '%s' "$HC_M_BEFORE" | jq .) >/dev/null 2>&1 && echo yes || echo no)"
# Re-run idempotency: a THIRD persist (record already carries harness_cost) makes no new commit.
HC_M_BC="$(_et_branch_count "$HC_M")"
( cd "$HC_M" && GITHUB_RUN_ID=777 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "hc-merge-b(A5): re-run over an already-harness_cost record is a tree-equality no-op" \
  "$HC_M_BC" "$(_et_branch_count "$HC_M")"
rm -rf "$HC_M"

# Merge-arm-(a) degradation coverage: drive the real _floor_merge_staged function
# directly so its already-present, jq-failure, and mv-failure branches are attributable.
HC_FMS="$(git_sandbox "hc floor-merge-staged")"
awk '/^_floor_merge_staged\(\) \{/{copy=1} copy{print} copy && /^\}/{exit}' \
  "$LIB/efficiency-trace.sh" > "$HC_FMS/invoke.sh"
cat >> "$HC_FMS/invoke.sh" <<'FMSEOF'
DEVFLOW_JQ="${DEVFLOW_JQ:-jq}"
_floor_merge_staged "$1" "$2" "fixture record"
FMSEOF
HC_FMS_PRESENT='{"schema_version":1,"harness_cost":{"cost_usd":1}}'
printf '%s' "$HC_FMS_PRESENT" > "$HC_FMS/present.json"
HC_FMS_PRESENT_ERR="$(bash "$HC_FMS/invoke.sh" "$HC_FMS/present.json" '{"cost_usd":2}' 2>&1 1>/dev/null)"
assert_eq "hc-merge-a(A5): already-carries short-circuit leaves the staged record byte-identical" \
  "$HC_FMS_PRESENT" "$(cat "$HC_FMS/present.json")"
assert_eq "hc-merge-a(A5): already-carries short-circuit emits its named breadcrumb" "yes" \
  "$(printf '%s' "$HC_FMS_PRESENT_ERR" | grep -qF 'already carries harness_cost; left untouched' && echo yes || echo no)"
printf '#!/usr/bin/env bash\nexit 7\n' > "$HC_FMS/jq-fail"; chmod +x "$HC_FMS/jq-fail"
printf '%s' '{"schema_version":1}' > "$HC_FMS/jq.json"
HC_FMS_JQ_ERR="$(DEVFLOW_JQ="$HC_FMS/jq-fail" bash "$HC_FMS/invoke.sh" "$HC_FMS/jq.json" '{"cost_usd":2}' 2>&1 1>/dev/null)"
assert_eq "hc-merge-a(A5): jq failure leaves the staged record byte-identical" \
  '{"schema_version":1}' "$(cat "$HC_FMS/jq.json")"
assert_eq "hc-merge-a(A5): jq failure emits its named merge breadcrumb" "yes" \
  "$(printf '%s' "$HC_FMS_JQ_ERR" | grep -qF 'could not merge harness_cost' && echo yes || echo no)"
HC_REAL_MV="$(command -v mv)"
cat > "$HC_FMS/mv" <<MVEOF
#!/usr/bin/env bash
case "\${1:-}" in *.harnesstmp) exit 1 ;; esac
exec "$HC_REAL_MV" "\$@"
MVEOF
chmod +x "$HC_FMS/mv"
printf '%s' '{"schema_version":1}' > "$HC_FMS/mv.json"
HC_FMS_MV_ERR="$(PATH="$HC_FMS:$PATH" bash "$HC_FMS/invoke.sh" "$HC_FMS/mv.json" '{"cost_usd":2}' 2>&1 1>/dev/null)"
assert_eq "hc-merge-a(A5): mv failure leaves the staged record byte-identical" \
  '{"schema_version":1}' "$(cat "$HC_FMS/mv.json")"
assert_eq "hc-merge-a(A5): mv failure emits its named move breadcrumb" "yes" \
  "$(printf '%s' "$HC_FMS_MV_ERR" | grep -qF 'could not move the merged fixture record into place' && echo yes || echo no)"
assert_eq "hc-merge-a(A5): jq/mv failure temp files are cleaned" "no" \
  "$([ -e "$HC_FMS/jq.json.harnesstmp" ] || [ -e "$HC_FMS/mv.json.harnesstmp" ] && echo yes || echo no)"
rm -rf "$HC_FMS"

# ── A3 (env-absent): --persist byte-identical + silent when the floor env is unset ─
HC_E="$(_hc_repo "hc env-absent")"
mkdir -p "$HC_E/.prflow/tmp/review/pr-9/111-1"
printf '%s' "$HC_ITER" > "$HC_E/.prflow/tmp/review/pr-9/111-1/iter-1.json"
HC_E_ERR="$( ( cd "$HC_E" && GITHUB_RUN_ID=111 GITHUB_RUN_ATTEMPT=1 bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-env(A3): floor unset → record carries NO harness_cost" "null" \
  "$(_et_show "$HC_E" ".prflow/logs/efficiency/pr-9-111-1.json" | jq -c '.harness_cost')"
assert_eq "hc-env(A3): floor unset → the helper stays SILENT about the floor" "yes" \
  "$(printf '%s' "$HC_E_ERR" | grep -q 'harness cost floor' && echo no || echo yes)"
rm -rf "$HC_E"

# ── A6: skeleton arm (no record for this run-id) ─────────────────────────────
HC_SK="$(_hc_repo "hc skeleton")"
( cd "$HC_SK" && GITHUB_RUN_ID=555 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "hc-skeleton(A6): no record + PR + record-deriving class → a pr-<N> skeleton is written" "yes" \
  "$(_et_on_branch "$HC_SK" ".prflow/logs/efficiency/pr-42-555-1.json")"
assert_eq "hc-skeleton(A6): skeleton shape — schema_version/source/synthesized/iterations/per_iteration/telemetry" \
  '[1,null,true,0,[],[]]' \
  "$(_et_show "$HC_SK" ".prflow/logs/efficiency/pr-42-555-1.json" | jq -c '[.schema_version,.source,.synthesized,.iterations,.per_iteration,.telemetry]')"
assert_eq "hc-skeleton(A6): skeleton slug is pr-<N> and carries harness_cost" "pr-42 execution-file" \
  "$(_et_show "$HC_SK" ".prflow/logs/efficiency/pr-42-555-1.json" | jq -r '.slug + " " + .harness_cost.cost_source')"
# AC9: a floor-only skeleton indexes (slug-bearing) with cost:None, telemetry_complete:false, source:None.
HC_SK_RS="$(_et_show "$HC_SK" ".prflow/logs/efficiency/pr-42-555-1.json" | python3 -c 'import importlib.util,sys,json
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.load(sys.stdin); e=m._efficiency_entry(r,"555-1")
print(json.dumps([e is not None, e["cost"], e["telemetry_complete"], e["source"]]))' "$LIB/../scripts/build-experiment-records.py" 2>/dev/null)"
assert_eq "hc-skeleton(A9): floor-only skeleton indexes with cost:None, telemetry_complete:false, source:None" \
  '[true, null, false, null]' "$HC_SK_RS"
rm -rf "$HC_SK"
# pr-description class → NO skeleton (no-record-by-design breadcrumb).
HC_PD="$(_hc_repo "hc pr-description")"
HC_PD_ERR="$( ( cd "$HC_PD" && GITHUB_RUN_ID=666 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=pr-description bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-skeleton(A6): pr-description class writes NO skeleton" "no" \
  "$(_et_on_branch "$HC_PD" ".prflow/logs/efficiency/pr-42-666-1.json")"
assert_eq "hc-skeleton(A6): pr-description → a named 'no record by design' breadcrumb" "yes" \
  "$(printf '%s' "$HC_PD_ERR" | grep -qF 'no record by design' && echo yes || echo no)"
rm -rf "$HC_PD"
# Empty PR → skeleton skipped with a specific breadcrumb.
HC_NP="$(_hc_repo "hc no-pr")"
HC_NP_ERR="$( ( cd "$HC_NP" && GITHUB_RUN_ID=444 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-skeleton(A6): empty PR → skeleton skipped with a specific breadcrumb" "yes" \
  "$(printf '%s' "$HC_NP_ERR" | grep -qF 'DEVFLOW_EXECUTION_PR is empty' && echo yes || echo no)"
rm -rf "$HC_NP"

# ── A8: gate off → no floor write ────────────────────────────────────────────
HC_G="$(_hc_repo "hc gate-off")"
printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$HC_G/.prflow/off.json"
HC_G_ERR="$( ( cd "$HC_G" && DEVFLOW_CONFIG_FILE="$HC_G/.prflow/off.json" GITHUB_RUN_ID=222 GITHUB_RUN_ATTEMPT=1 \
    DEVFLOW_EXECUTION_COST="$HC_COST" DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-gate(A8): telemetry disabled → no skeleton/floor record written" "no" \
  "$(_et_on_branch "$HC_G" ".prflow/logs/efficiency/pr-42-222-1.json")"
assert_eq "hc-gate(A8): telemetry disabled → a specific 'disabled' breadcrumb" "yes" \
  "$(printf '%s' "$HC_G_ERR" | grep -qF 'efficiency telemetry is disabled' && echo yes || echo no)"
rm -rf "$HC_G"
# Malformed DEVFLOW_EXECUTION_COST → one breadcrumb, no floor write.
HC_BAD="$(_hc_repo "hc malformed")"
mkdir -p "$HC_BAD/.prflow/tmp/review/pr-3/333-1"
printf '%s' "$HC_ITER" > "$HC_BAD/.prflow/tmp/review/pr-3/333-1/iter-1.json"
HC_BAD_ERR="$( ( cd "$HC_BAD" && GITHUB_RUN_ID=333 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST='not json' \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-malformed(A3): non-object DEVFLOW_EXECUTION_COST → record carries no harness_cost" "null" \
  "$(_et_show "$HC_BAD" ".prflow/logs/efficiency/pr-3-333-1.json" | jq -c '.harness_cost')"
assert_eq "hc-malformed(A3): non-object value → a specific breadcrumb" "yes" \
  "$(printf '%s' "$HC_BAD_ERR" | grep -qF 'not a JSON object' && echo yes || echo no)"
# Valid-JSON-but-not-an-object (a JSON array): the `type == "object"` operand guard exists
# precisely so a non-object never reaches `jq --argjson`; the 'not json' case above fails the
# jq PARSE, whereas '[1,2]' PARSES yet is not an object — a DISTINCT arm of the writer's
# adversarial matrix. Must draw the same "not a JSON object" breadcrumb and no floor write.
HC_ARR="$(_hc_repo "hc arr-cost")"
mkdir -p "$HC_ARR/.prflow/tmp/review/pr-3/334-1"
printf '%s' "$HC_ITER" > "$HC_ARR/.prflow/tmp/review/pr-3/334-1/iter-1.json"
HC_ARR_ERR="$( ( cd "$HC_ARR" && GITHUB_RUN_ID=334 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST='[1,2]' \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-malformed(A3): valid-JSON-but-non-object (array) → record carries no harness_cost" "null" \
  "$(_et_show "$HC_ARR" ".prflow/logs/efficiency/pr-3-334-1.json" | jq -c '.harness_cost')"
assert_eq "hc-malformed(A3): valid-JSON-but-non-object (array) → the 'not a JSON object' breadcrumb" "yes" \
  "$(printf '%s' "$HC_ARR_ERR" | grep -qF 'not a JSON object' && echo yes || echo no)"
rm -rf "$HC_ARR"
# GITHUB_RUN_ID unset (AC3 fail-closed): cost set + valid object + telemetry enabled, but the
# run cannot be identified, so the floor DECLINES rather than attach to an arbitrary swept
# record. Every other HC merge test sets GITHUB_RUN_ID, so this fail-closed guard was unexercised.
HC_RU="$(_hc_repo "hc runid-unset")"
mkdir -p "$HC_RU/.prflow/tmp/review/pr-4/iddir-1"
printf '%s' "$HC_ITER" > "$HC_RU/.prflow/tmp/review/pr-4/iddir-1/iter-1.json"
HC_RU_ERR="$( ( cd "$HC_RU" && unset GITHUB_RUN_ID; DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-runid(A3): GITHUB_RUN_ID unset → no harness_cost attached to any swept record" "null" \
  "$(_et_show "$HC_RU" ".prflow/logs/efficiency/pr-4-iddir-1.json" | jq -c '.harness_cost')"
assert_eq "hc-runid(A3): GITHUB_RUN_ID unset → a specific 'cannot be identified' breadcrumb (fail-closed, not silent)" "yes" \
  "$(printf '%s' "$HC_RU_ERR" | grep -qF 'GITHUB_RUN_ID is unset' && echo yes || echo no)"
rm -rf "$HC_RU"

# ── #1064 AC3/W1: apply_denial_floor — the permission-denial forensics floor ──
# This is the ONLY code that lands the denial record on the telemetry branch, and AC3
# required it be unit-tested against the helper directly (no network, no branch push).
# It declares that it mirrors apply_harness_floor exactly, so it is driven through the
# same arms as the HC block above: staged (a), already-persisted read-back (b) with
# byte-preservation, skeleton (with its overwrite guard and both residual decline gates),
# re-run idempotency, malformed operand, run-id absent.
DF_REC='{"count":3,"tool_names":["Bash"],"commands_state":"present","commands":["cat x > /tmp/a"],"total":1,"truncated":false,"commands_field_enabled":true,"scrub":{"applied":true,"blocklist_incomplete":true,"shapes":"s"}}'

# arm (a): a record staged THIS PASS under the run-id identity gains permission_denials,
# and a record with a DIFFERENT run-id (sorting first, like the HC fixture) is untouched.
DF_T="$(_hc_repo "df target")"
mkdir -p "$DF_T/.prflow/tmp/review/pr-77/959-1" "$DF_T/.prflow/tmp/review/pr-11/858-2"
printf '%s' "$HC_ITER" > "$DF_T/.prflow/tmp/review/pr-77/959-1/iter-1.json"
printf '%s' "$HC_ITER" > "$DF_T/.prflow/tmp/review/pr-11/858-2/iter-1.json"
( cd "$DF_T" && GITHUB_RUN_ID=959 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "df-merge(a): the record matching the run-id identity gained permission_denials" "3" \
  "$(_et_show "$DF_T" ".prflow/logs/efficiency/pr-77-959-1.json" | jq -r '.permission_denials.count')"
assert_eq "df-merge(a): the denial record is attached VERBATIM" "$(printf '%s' "$DF_REC" | jq -S -c .)" \
  "$(_et_show "$DF_T" ".prflow/logs/efficiency/pr-77-959-1.json" | jq -S -c '.permission_denials')"
assert_eq "df-merge(a): a record with a DIFFERENT run-id (sorting first) was NOT touched" "null" \
  "$(_et_show "$DF_T" ".prflow/logs/efficiency/pr-11-858-2.json" | jq -c '.permission_denials')"
rm -rf "$DF_T"

# arm (b): a record ALREADY on the branch is read back and gains the key; everything
# outside permission_denials stays byte-identical; a re-run is a tree-equality no-op.
DF_M="$(_hc_repo "df merge-branch")"
mkdir -p "$DF_M/.prflow/tmp/review/pr-5/757-1"
printf '%s' "$HC_ITER" > "$DF_M/.prflow/tmp/review/pr-5/757-1/iter-1.json"
( cd "$DF_M" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
DF_M_BEFORE="$(_et_show "$DF_M" ".prflow/logs/efficiency/pr-5-757-1.json")"
assert_eq "df-merge(b): pre-floor record has no permission_denials" "null" \
  "$(printf '%s' "$DF_M_BEFORE" | jq -c '.permission_denials')"
( cd "$DF_M" && GITHUB_RUN_ID=757 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
DF_M_AFTER="$(_et_show "$DF_M" ".prflow/logs/efficiency/pr-5-757-1.json")"
assert_eq "df-merge(b): already-persisted record gains permission_denials via read-back" "3" \
  "$(printf '%s' "$DF_M_AFTER" | jq -r '.permission_denials.count')"
assert_eq "df-merge(b): everything OUTSIDE permission_denials is byte-identical to the original" "yes" \
  "$(diff <(printf '%s' "$DF_M_AFTER" | jq 'del(.permission_denials)') <(printf '%s' "$DF_M_BEFORE" | jq .) >/dev/null 2>&1 && echo yes || echo no)"
DF_M_BC="$(_et_branch_count "$DF_M")"
DF_M_RERUN="$( ( cd "$DF_M" && GITHUB_RUN_ID=757 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-merge(b): re-run over an already-attached record is a tree-equality no-op" \
  "$DF_M_BC" "$(_et_branch_count "$DF_M")"
assert_eq "df-merge(b): re-run emits the already-carries backstop breadcrumb" "yes" \
  "$(printf '%s' "$DF_M_RERUN" | grep -qF 'already carries permission_denials' && echo yes || echo no)"
rm -rf "$DF_M"

# SKELETON arm — no efficiency record exists for this run-id (the all-null-cost drop path:
# prepare-harness-floor refuses to stage an all-null harness_cost, so apply_harness_floor
# returns before its own skeleton arm and there is no host record to merge onto). The denial
# floor writes its own minimal record rather than discarding a fully-built denial record.
DF_SK="$(_hc_repo "df skeleton")"
DF_SK_ERR="$( ( cd "$DF_SK" && GITHUB_RUN_ID=606 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-skeleton: no record + PR + record-deriving class → a pr-<N> denial skeleton is written" "yes" \
  "$(_et_on_branch "$DF_SK" ".prflow/logs/efficiency/pr-42-606-1.json")"
assert_eq "df-skeleton: skeleton shape — schema_version/slug/source/synthesized/iterations/per_iteration/telemetry" \
  '[1,"pr-42",null,true,0,[],[]]' \
  "$(_et_show "$DF_SK" ".prflow/logs/efficiency/pr-42-606-1.json" | jq -c '[.schema_version,.slug,.source,.synthesized,.iterations,.per_iteration,.telemetry]')"
assert_eq "df-skeleton: the denial record is carried VERBATIM (no harness_cost fabricated beside it)" \
  "$(printf '%s' "$DF_REC" | jq -S -c .)|null" \
  "$(_et_show "$DF_SK" ".prflow/logs/efficiency/pr-42-606-1.json" | jq -S -c '.permission_denials')|$(_et_show "$DF_SK" ".prflow/logs/efficiency/pr-42-606-1.json" | jq -c '.harness_cost')"
# The downstream consumer claim this arm rests on: build-experiment-records.py's
# _efficiency_entry needs only a top-level string `slug`, so a denial-only record INGESTS —
# cost None (no telemetry to sum), and permission_denials flowing through to _denials_from_eff,
# which reads only `.count`. A record that broke ingestion would be worse than none.
DF_SK_RS="$(_et_show "$DF_SK" ".prflow/logs/efficiency/pr-42-606-1.json" | python3 -c 'import importlib.util,sys,json
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.load(sys.stdin); e=m._efficiency_entry(r,"606-1")
print(json.dumps([e is not None, e["cost"], e["telemetry_complete"], list(m._denials_from_eff([e]))]))' "$LIB/../scripts/build-experiment-records.py" 2>/dev/null)"
assert_eq "df-skeleton: a denial-only skeleton ingests downstream and yields the count via _denials_from_eff" \
  '[true, null, false, [3, "efficiency-record"]]' "$DF_SK_RS"
assert_eq "df-skeleton: emits the named skeleton-written breadcrumb" "yes" \
  "$(printf '%s' "$DF_SK_ERR" | grep -qF 'wrote a minimal denial skeleton pr-42-606-1.json' && echo yes || echo no)"
# Re-running the backstop over the now-persisted skeleton is a tree-equality no-op (the
# already-carries arm), so the skeleton cannot churn the branch on every retry.
DF_SK_BC="$(_et_branch_count "$DF_SK")"
DF_SK_RERUN="$( ( cd "$DF_SK" && GITHUB_RUN_ID=606 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-skeleton: re-run over the persisted skeleton is a tree-equality no-op" \
  "$DF_SK_BC" "$(_et_branch_count "$DF_SK")"
assert_eq "df-skeleton: re-run takes the already-carries arm, never a second skeleton write" "yes" \
  "$(printf '%s' "$DF_SK_RERUN" | grep -qF 'already carries permission_denials' && echo yes || echo no)"
rm -rf "$DF_SK"

# Skeleton-overwrite guard (mirrors the cost floor's A6+ fixture): merge arm (b) falls
# through a loop that iterates zero times BOTH when the branch holds no record for this
# run-id AND when list_blobs swallowed a git failure. Force that ambiguity — patch the
# copied telemetry-branch.sh so list_blobs returns empty while blob_exists still finds the
# blob — and a REAL, populated record occupying the skeleton's own filename must survive.
DF_OW_ROOT="$(git_sandbox "df skel-overwrite root")"
mkdir -p "$DF_OW_ROOT/lib" "$DF_OW_ROOT/.claude-plugin"
cp "$LIB"/*.sh "$LIB"/*.jq "$DF_OW_ROOT/lib/" 2>/dev/null
cp "$LIB/../.claude-plugin/plugin.json" "$DF_OW_ROOT/.claude-plugin/" 2>/dev/null
printf '\ndevflow_telemetry_list_blobs() { return 0; }\n' >> "$DF_OW_ROOT/lib/telemetry-branch.sh"
DF_OW="$(_hc_repo "df skel-overwrite")"
DF_OW_REC='{"schema_version":1,"slug":"pr-42","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":7,"real_marker":true,"telemetry":[]}'
DF_OW_IDX="$DF_OW/.git/dfowidx"
DF_OW_SB="$(printf '%s' "$DF_OW_REC" | git -C "$DF_OW" hash-object -w --stdin)"
GIT_INDEX_FILE="$DF_OW_IDX" git -C "$DF_OW" update-index --add --cacheinfo "100644,${DF_OW_SB},.prflow/logs/efficiency/pr-42-616-1.json"
DF_OW_ST="$(GIT_INDEX_FILE="$DF_OW_IDX" git -C "$DF_OW" write-tree)"; rm -f "$DF_OW_IDX"
DF_OW_SN="$(GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@e GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@e git -C "$DF_OW" commit-tree "$DF_OW_ST" -m seed-record)"
git -C "$DF_OW" update-ref refs/heads/prflow-telemetry "$DF_OW_SN"
DF_OW_ERR="$( ( cd "$DF_OW" && GITHUB_RUN_ID=616 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix \
    bash "$DF_OW_ROOT/lib/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-skeleton: guard declines → the real branch record is NOT overwritten (iterations still 7, not the skeleton's 0)" "7" \
  "$(git -C "$DF_OW" show "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-42-616-1.json" 2>/dev/null | jq -c '.iterations')"
assert_eq "df-skeleton: guard declines → the real record's marker survives (skeleton never written over it)" "true" \
  "$(git -C "$DF_OW" show "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-42-616-1.json" 2>/dev/null | jq -c '.real_marker')"
assert_eq "df-skeleton: guard declines → the specific 'declining to overwrite it with a denial skeleton' breadcrumb" "yes" \
  "$(printf '%s' "$DF_OW_ERR" | grep -qF 'declining to overwrite it with a denial skeleton' && echo yes || echo no)"
rm -rf "$DF_OW" "$DF_OW_ROOT"

# Residual drop path 1 — a class that derives no record (pr-description, and unclassified):
# no skeleton, and a NAMED breadcrumb so the discard is auditable rather than silent.
for _df_cls in pr-description ''; do
  DF_C="$(_hc_repo "df class")"
  DF_C_ERR="$( ( cd "$DF_C" && GITHUB_RUN_ID=626 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
      DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS="$_df_cls" \
      bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
  assert_eq "df-residual(class='$_df_cls'): no denial skeleton is written" "" \
    "$(git -C "$DF_C" ls-tree -r --name-only refs/heads/prflow-telemetry 2>/dev/null | grep '\.prflow/logs/efficiency/' || true)"
  assert_eq "df-residual(class='$_df_cls'): the discard draws a named residual-drop-path breadcrumb" "yes" \
    "$(printf '%s' "$DF_C_ERR" | grep -qF 'no denial skeleton written (residual drop path' && echo yes || echo no)"
  rm -rf "$DF_C"
done

# Residual drop path 2 — DEVFLOW_EXECUTION_PR empty: the record is keyed `<slug>-<run-id>`,
# so with no PR number there is no slug to file it under. No skeleton, named breadcrumb.
DF_NP="$(_hc_repo "df no-pr")"
DF_NP_ERR="$( ( cd "$DF_NP" && GITHUB_RUN_ID=636 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-residual(empty PR): no denial skeleton is written" "" \
  "$(git -C "$DF_NP" ls-tree -r --name-only refs/heads/prflow-telemetry 2>/dev/null | grep '\.prflow/logs/efficiency/' || true)"
assert_eq "df-residual(empty PR): the discard draws a named residual-drop-path breadcrumb" "yes" \
  "$(printf '%s' "$DF_NP_ERR" | grep -qF 'DEVFLOW_EXECUTION_PR is empty' && echo yes || echo no)"
rm -rf "$DF_NP"

# Malformed operand: 'not json' fails the jq PARSE; '[1,2]' PARSES but is not an object.
# Both must draw the not-a-JSON-object breadcrumb and leave the record without the key —
# the operand guard exists so a non-object never reaches `jq --argjson` (which would abort).
for _df_bad in 'not json' '[1,2]'; do
  DF_B="$(_hc_repo "df malformed")"
  mkdir -p "$DF_B/.prflow/tmp/review/pr-3/363-1"
  printf '%s' "$HC_ITER" > "$DF_B/.prflow/tmp/review/pr-3/363-1/iter-1.json"
  DF_B_ERR="$( ( cd "$DF_B" && GITHUB_RUN_ID=363 GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$_df_bad" \
      bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
  assert_eq "df-malformed('$_df_bad'): record carries no permission_denials" "null" \
    "$(_et_show "$DF_B" ".prflow/logs/efficiency/pr-3-363-1.json" | jq -c '.permission_denials')"
  assert_eq "df-malformed('$_df_bad'): draws the 'not a JSON object' breadcrumb" "yes" \
    "$(printf '%s' "$DF_B_ERR" | grep -qF 'not a JSON object' && echo yes || echo no)"
  rm -rf "$DF_B"
done

# GITHUB_RUN_ID unset: a valid operand and telemetry enabled, but the run cannot be
# identified — decline rather than attach to an arbitrary swept record.
DF_RU="$(_hc_repo "df runid-unset")"
mkdir -p "$DF_RU/.prflow/tmp/review/pr-4/iddir-1"
printf '%s' "$HC_ITER" > "$DF_RU/.prflow/tmp/review/pr-4/iddir-1/iter-1.json"
DF_RU_ERR="$( ( cd "$DF_RU" && unset GITHUB_RUN_ID; DEVFLOW_DENIAL_RECORD="$DF_REC" \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-runid: GITHUB_RUN_ID unset → no permission_denials attached to any swept record" "null" \
  "$(_et_show "$DF_RU" ".prflow/logs/efficiency/pr-4-iddir-1.json" | jq -c '.permission_denials')"
assert_eq "df-runid: GITHUB_RUN_ID unset → a specific breadcrumb (fail-closed, not silent)" "yes" \
  "$(printf '%s' "$DF_RU_ERR" | grep -qF 'GITHUB_RUN_ID is unset' && echo yes || echo no)"
rm -rf "$DF_RU"

# Gate off (mirrors the cost floor's A8): efficiency_telemetry_enabled gates denial
# forensics too, not only cost. Every input the skeleton arm needs is present (operand,
# PR, record-deriving class, run-id), so with the flag ON this run WOULD write
# pr-42-646-1.json — the gate is the only thing standing between here and that write.
DF_G="$(_hc_repo "df gate-off")"
printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$DF_G/.prflow/off.json"
DF_G_ERR="$( ( cd "$DF_G" && DEVFLOW_CONFIG_FILE="$DF_G/.prflow/off.json" GITHUB_RUN_ID=646 \
    GITHUB_RUN_ATTEMPT=1 DEVFLOW_DENIAL_RECORD="$DF_REC" DEVFLOW_EXECUTION_PR=42 \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-gate: telemetry disabled → no denial skeleton (nor any other record) is written" "" \
  "$(git -C "$DF_G" ls-tree -r --name-only refs/heads/prflow-telemetry 2>/dev/null | grep '\.prflow/logs/efficiency/' || true)"
assert_eq "df-gate: telemetry disabled → the denial floor's own 'disabled' breadcrumb" "yes" \
  "$(printf '%s' "$DF_G_ERR" | grep -qF 'denial floor: efficiency telemetry is disabled' && echo yes || echo no)"
rm -rf "$DF_G"

# Env-absent inertness: with DEVFLOW_DENIAL_RECORD unset the floor is inert AND SILENT,
# so every pre-#1064 agent-side --persist call site is byte-identical to before.
DF_E="$(_hc_repo "df env-absent")"
mkdir -p "$DF_E/.prflow/tmp/review/pr-9/909-1"
printf '%s' "$HC_ITER" > "$DF_E/.prflow/tmp/review/pr-9/909-1/iter-1.json"
DF_E_ERR="$( ( cd "$DF_E" && GITHUB_RUN_ID=909 GITHUB_RUN_ATTEMPT=1 \
    bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "df-inert: operand unset → the record carries no permission_denials key" "null" \
  "$(_et_show "$DF_E" ".prflow/logs/efficiency/pr-9-909-1.json" | jq -c '.permission_denials')"
assert_eq "df-inert: operand unset → the denial floor emits NO breadcrumb at all (silent)" "no" \
  "$(printf '%s' "$DF_E_ERR" | grep -qF 'denial floor' && echo yes || echo no)"
rm -rf "$DF_E"

# ── A5a: two-writer union race — a stale local snapshot must NOT revert another
# writer's harness_cost on the push-rejection re-parent (mirrors the #441
# offline-accum fixture, with a MUTATED record path instead of a fresh one) ────
HC_RC_BARE="$(git_sandbox "hc race bare")"; git -C "$HC_RC_BARE" init --bare -q
HC_RC="$(git_sandbox "hc race repo")"; git -C "$HC_RC" init -q
git -C "$HC_RC" config user.email t@e.com; git -C "$HC_RC" config user.name t
git -C "$HC_RC" remote add origin "$HC_RC_BARE"
mkdir -p "$HC_RC/.prflow"; printf 'tmp/\n' > "$HC_RC/.prflow/.gitignore"
git -C "$HC_RC" add -A; git -C "$HC_RC" commit -qm seed; git -C "$HC_RC" branch -M main
git -C "$HC_RC" push -q -u origin main
# Writer B (this repo) builds a LOCAL telemetry tip holding a STALE snapshot of a
# shared record R (no harness_cost) while the remote is down.
HC_RC_REC='{"schema_version":1,"slug":"pr-6","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":1,"telemetry":[]}'
mv "$HC_RC_BARE" "${HC_RC_BARE}.down"
HC_RC_IDX="$HC_RC/.git/rcidx"
HC_RC_SB="$(printf '%s' "$HC_RC_REC" | git -C "$HC_RC" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_RC_IDX" git -C "$HC_RC" update-index --add --cacheinfo "100644,${HC_RC_SB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_RC_ST="$(GIT_INDEX_FILE="$HC_RC_IDX" git -C "$HC_RC" write-tree)"; rm -f "$HC_RC_IDX"
HC_RC_SN="$(GIT_AUTHOR_NAME=b GIT_AUTHOR_EMAIL=b@y GIT_COMMITTER_NAME=b GIT_COMMITTER_EMAIL=b@y git -C "$HC_RC" commit-tree "$HC_RC_ST" -m b)"
git -C "$HC_RC" update-ref refs/heads/prflow-telemetry "$HC_RC_SN"
mv "${HC_RC_BARE}.down" "$HC_RC_BARE"
# Writer A (a second clone) MERGES harness_cost into the SAME record R and pushes it.
HC_RC_A="$(git_sandbox "hc race writerA")"; git clone -q "$HC_RC_BARE" "$HC_RC_A" 2>/dev/null
HC_RC_AREC="$(printf '%s' "$HC_RC_REC" | jq -c '.harness_cost={cost_source:"execution-file",cost_usd:9}')"
HC_RC_AIDX="$HC_RC_A/.git/aidx"
HC_RC_AB="$(printf '%s' "$HC_RC_AREC" | git -C "$HC_RC_A" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_RC_AIDX" git -C "$HC_RC_A" update-index --add --cacheinfo "100644,${HC_RC_AB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_RC_AT="$(GIT_INDEX_FILE="$HC_RC_AIDX" git -C "$HC_RC_A" write-tree)"; rm -f "$HC_RC_AIDX"
HC_RC_AN="$(GIT_AUTHOR_NAME=a GIT_AUTHOR_EMAIL=a@y GIT_COMMITTER_NAME=a GIT_COMMITTER_EMAIL=a@y git -C "$HC_RC_A" commit-tree "$HC_RC_AT" -m a)"
git -C "$HC_RC_A" update-ref refs/heads/prflow-telemetry "$HC_RC_AN"
git -C "$HC_RC_A" push -q origin prflow-telemetry
# Writer B now persists a NEW, unrelated run (its own record) — its push is rejected
# (remote diverged), so it fetches A's tip and re-parents the UNION. B did NOT stage
# R this pass, so the merge-aware union must keep A's harness_cost on R (base-wins),
# NOT revert it to B's stale local snapshot.
mkdir -p "$HC_RC/.prflow/tmp/review/pr-6/run-b"
printf '%s' "$HC_ITER" > "$HC_RC/.prflow/tmp/review/pr-6/run-b/iter-1.json"
( cd "$HC_RC" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
git -C "$HC_RC" fetch -q origin prflow-telemetry:refs/remotes/origin/rc 2>/dev/null
assert_eq "hc-race(A5a): the concurrently-merged record R still carries writer A's harness_cost (stale snapshot did NOT revert it)" "9" \
  "$(git -C "$HC_RC" show "refs/remotes/origin/rc:.prflow/logs/efficiency/pr-6-run-r.json" 2>/dev/null | jq -c '.harness_cost.cost_usd')"
assert_eq "hc-race(A5a): writer B's own new record is also present on the remote after the union" "yes" \
  "$(git -C "$HC_RC" cat-file -e "refs/remotes/origin/rc:.prflow/logs/efficiency/pr-6-run-b.json" >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$HC_RC" "$HC_RC_BARE" "$HC_RC_A"

# ── A5a (STAGED branch): the fixture above exercises the UNSTAGED base-wins arm (B did not
# stage R). This one exercises the merge-aware union's *staged efficiency-record* arm
# (telemetry-branch.sh's `.prflow/logs/efficiency/*.json` case) — AC5a's "re-parent re-applies
# THIS run's harness_cost merge onto the fetched base-side version of its target path." Here B
# DOES stage R: the floor env drives merge-arm-b (ident=run-r) to read B's STALE local R
# (no harness_cost) back and re-stage it with B's OWN harness_cost (cost_usd=5). Writer A
# concurrently merged a DIFFERENT harness_cost (cost_usd=9) onto R and pushed. On the rejected
# push the re-parent must keep A's harness_cost on base (base already carries one → base-wins),
# NOT overwrite it with B's staged stale copy — a blanket local-wins overlay would revert it to 5.
HC_SR_BARE="$(git_sandbox "hc staged-remerge bare")"; git -C "$HC_SR_BARE" init --bare -q
HC_SR="$(git_sandbox "hc staged-remerge repo")"; git -C "$HC_SR" init -q
git -C "$HC_SR" config user.email t@e.com; git -C "$HC_SR" config user.name t
git -C "$HC_SR" remote add origin "$HC_SR_BARE"
mkdir -p "$HC_SR/.prflow"; printf 'tmp/\n' > "$HC_SR/.prflow/.gitignore"
git -C "$HC_SR" add -A; git -C "$HC_SR" commit -qm seed; git -C "$HC_SR" branch -M main
git -C "$HC_SR" push -q -u origin main
# B's stale LOCAL telemetry tip holds R WITHOUT harness_cost (the snapshot merge-arm-b re-stages).
HC_SR_REC='{"schema_version":1,"slug":"pr-6","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":1,"telemetry":[]}'
mv "$HC_SR_BARE" "${HC_SR_BARE}.down"
HC_SR_IDX="$HC_SR/.git/sridx"
HC_SR_SB="$(printf '%s' "$HC_SR_REC" | git -C "$HC_SR" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_SR_IDX" git -C "$HC_SR" update-index --add --cacheinfo "100644,${HC_SR_SB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_SR_ST="$(GIT_INDEX_FILE="$HC_SR_IDX" git -C "$HC_SR" write-tree)"; rm -f "$HC_SR_IDX"
HC_SR_SN="$(GIT_AUTHOR_NAME=b GIT_AUTHOR_EMAIL=b@y GIT_COMMITTER_NAME=b GIT_COMMITTER_EMAIL=b@y git -C "$HC_SR" commit-tree "$HC_SR_ST" -m b)"
git -C "$HC_SR" update-ref refs/heads/prflow-telemetry "$HC_SR_SN"
mv "${HC_SR_BARE}.down" "$HC_SR_BARE"
# Writer A MERGES harness_cost (cost_usd=9) into the SAME record R and pushes it.
HC_SR_A="$(git_sandbox "hc staged-remerge writerA")"; git clone -q "$HC_SR_BARE" "$HC_SR_A" 2>/dev/null
HC_SR_AREC="$(printf '%s' "$HC_SR_REC" | jq -c '.harness_cost={cost_source:"execution-file",cost_usd:9}')"
HC_SR_AIDX="$HC_SR_A/.git/aidx"
HC_SR_AB="$(printf '%s' "$HC_SR_AREC" | git -C "$HC_SR_A" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_SR_AIDX" git -C "$HC_SR_A" update-index --add --cacheinfo "100644,${HC_SR_AB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_SR_AT="$(GIT_INDEX_FILE="$HC_SR_AIDX" git -C "$HC_SR_A" write-tree)"; rm -f "$HC_SR_AIDX"
HC_SR_AN="$(GIT_AUTHOR_NAME=a GIT_AUTHOR_EMAIL=a@y GIT_COMMITTER_NAME=a GIT_COMMITTER_EMAIL=a@y git -C "$HC_SR_A" commit-tree "$HC_SR_AT" -m a)"
git -C "$HC_SR_A" update-ref refs/heads/prflow-telemetry "$HC_SR_AN"
git -C "$HC_SR_A" push -q origin prflow-telemetry
# Writer B persists with the floor env (ident=run-r matches R's filename → merge-arm-b re-stages
# R with cost_usd=5) plus its own new run dir; the push is rejected (remote diverged) and the
# re-parent runs the STAGED efficiency-record union arm over R.
mkdir -p "$HC_SR/.prflow/tmp/review/pr-6/run-b"
printf '%s' "$HC_ITER" > "$HC_SR/.prflow/tmp/review/pr-6/run-b/iter-1.json"
( cd "$HC_SR" && GITHUB_RUN_ID=run GITHUB_RUN_ATTEMPT=r \
    DEVFLOW_EXECUTION_COST='{"cost_usd":5,"tokens":{},"model_usage":null,"num_turns":null,"duration_ms":null}' \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
git -C "$HC_SR" fetch -q origin prflow-telemetry:refs/remotes/origin/sr 2>/dev/null
assert_eq "hc-race(A5a staged): the staged re-merge keeps base-side (writer A) harness_cost cost_usd=9, NOT this run's stale cost_usd=5" "9" \
  "$(git -C "$HC_SR" show "refs/remotes/origin/sr:.prflow/logs/efficiency/pr-6-run-r.json" 2>/dev/null | jq -c '.harness_cost.cost_usd')"
rm -rf "$HC_SR" "$HC_SR_BARE" "$HC_SR_A"

# ── A7: prepare-harness-floor.sh — every branch, under a stubbed gh ───────────
HC_GD="$(git_sandbox "hc glue")"
printf '{"type":"result","total_cost_usd":1}' > "$HC_GD/exec.json"
# gh stub: `api …/pulls/<n>` echoes <n> iff it is in STUB_PRS; `pr list` echoes STUB_PR_LIST.
cat > "$HC_GD/gh" <<'GHEOF'
#!/usr/bin/env bash
case "$1" in
  api)  n="${2##*/pulls/}"; case ",${STUB_PRS:-}," in *",$n,"*) echo "$n" ;; *) exit 1 ;; esac ;;
  pr)   printf '%s' "${STUB_PR_LIST:-}" ;;
  *)    exit 1 ;;
esac
GHEOF
chmod +x "$HC_GD/gh"
# happy review-and-fix: candidate 50 is a real PR → PR=50 + cost written.
HC_G_OUT="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:review-and-fix" 50 "$HC_GD/cost.json" 2>/dev/null)"
assert_eq "hc-glue(A7): happy path → DEVFLOW_EXECUTION_PR set to the verified PR" "yes" \
  "$(printf '%s' "$HC_G_OUT" | grep -qF "DEVFLOW_EXECUTION_PR='50'" && echo yes || echo no)"
assert_eq "hc-glue(A7): happy path → command class emitted" "yes" \
  "$(printf '%s' "$HC_G_OUT" | grep -qF "DEVFLOW_COMMAND_CLASS='review-and-fix'" && echo yes || echo no)"
assert_eq "hc-glue(A7): happy path → cost JSON written to the out file" "1" \
  "$(jq -c '.cost_usd' "$HC_GD/cost.json" 2>/dev/null)"
# explicit-number command overrides the raw context number (never the comment-context number).
HC_G_EXP="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:review-and-fix 50" 999 "$HC_GD/c2.json" 2>/dev/null)"
assert_eq "hc-glue(A7): an explicit-number command uses the target (50), not the context number (999)" "yes" \
  "$(printf '%s' "$HC_G_EXP" | grep -qF "DEVFLOW_EXECUTION_PR='50'" && echo yes || echo no)"
# inert: execution file absent → named inert breadcrumb, empty cost file. The PR is still
# resolved: an inert COST no longer short-circuits the PR resolution, because the PR is a
# SHARED operand (the denial floor's skeleton arm keys its record by it) and the two fail
# independently. The cost handoff staying EMPTY is what keeps the cost floor inert.
HC_G_INERT="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/nope.json" "/devflow:review-and-fix" 50 "$HC_GD/c3.json" 2>"$HC_GD/inert.err")"
assert_eq "hc-glue(A7): inert (execution file absent) → the named inert breadcrumb" "yes" \
  "$(grep -qF 'harness cost floor inert this run: execution file absent' "$HC_GD/inert.err" && echo yes || echo no)"
assert_eq "hc-glue(A7): inert (execution file absent) → the cost handoff stays empty" "no" \
  "$([ -s "$HC_GD/c3.json" ] && echo yes || echo no)"
assert_eq "hc-glue(A7): inert cost no longer suppresses the shared PR operand" "yes" \
  "$(printf '%s' "$HC_G_INERT" | grep -qF "DEVFLOW_EXECUTION_PR='50'" && echo yes || echo no)"
# Parsed-but-figureless: the reader prints a non-empty normalized object by contract, but
# the glue must not turn its all-null payload into false cost coverage or a cost skeleton.
# This is the drop path the denial skeleton closes, so it is the one that most needs the PR.
printf '%s' '{"type":"result"}' > "$HC_GD/all-null.json"
HC_G_NULL="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/all-null.json" "/devflow:review-and-fix" 50 "$HC_GD/c-null.json" 2>"$HC_GD/null.err")"
assert_eq "hc-glue(A7): all-null reader object still resolves DEVFLOW_EXECUTION_PR (the denial floor keys on it)" "yes" \
  "$(printf '%s' "$HC_G_NULL" | grep -qF "DEVFLOW_EXECUTION_PR='50'" && echo yes || echo no)"
assert_eq "hc-glue(A7): all-null reader object leaves the cost handoff empty" "no" \
  "$([ -s "$HC_GD/c-null.json" ] && echo yes || echo no)"
assert_eq "hc-glue(A7): all-null reader object emits a named no-figures inert breadcrumb" "yes" \
  "$(grep -qF 'execution file carried no cost or usage figures' "$HC_GD/null.err" && echo yes || echo no)"
# Negative control for that decoupling: a resolved PR beside an EMPTY cost must NOT make the
# COST floor write anything (apply_harness_floor returns at its first guard), so the glue
# change cannot leak an all-null harness_cost or a cost skeleton into the store.
HC_G_NCTL="$(_hc_repo "hc glue no-cost-skeleton")"
( cd "$HC_G_NCTL" && GITHUB_RUN_ID=717 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="" \
    DEVFLOW_EXECUTION_PR=50 DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "hc-glue(A7): a resolved PR with an EMPTY cost writes no cost skeleton (the floor stays inert)" "" \
  "$(git -C "$HC_G_NCTL" ls-tree -r --name-only refs/heads/prflow-telemetry 2>/dev/null | grep '\.prflow/logs/efficiency/' || true)"
rm -rf "$HC_G_NCTL"
# not-a-PR / lookup-failed: candidate 999 is not in the PR set → empty PR + breadcrumb.
HC_G_NAP="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:review-and-fix" 999 "$HC_GD/c4.json" 2>"$HC_GD/nap.err")"
assert_eq "hc-glue(A7): candidate not a real PR → DEVFLOW_EXECUTION_PR empty" "yes" \
  "$(printf '%s' "$HC_G_NAP" | grep -qF "DEVFLOW_EXECUTION_PR=''" && echo yes || echo no)"
assert_eq "hc-glue(A7): not-a-PR → a specific breadcrumb naming the skipped skeleton" "yes" \
  "$(grep -qF 'does not name a real PR' "$HC_GD/nap.err" && echo yes || echo no)"
# pr-description class → no PR, no-record-by-design breadcrumb.
HC_G_PD="$(DEVFLOW_GH="$HC_GD/gh" bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:pr-description" 50 "$HC_GD/c5.json" 2>"$HC_GD/pd.err")"
assert_eq "hc-glue(A7): pr-description → DEVFLOW_EXECUTION_PR empty" "yes" \
  "$(printf '%s' "$HC_G_PD" | grep -qF "DEVFLOW_EXECUTION_PR=''" && echo yes || echo no)"
assert_eq "hc-glue(A7): pr-description → the no-record-by-design breadcrumb" "yes" \
  "$(grep -qF 'no record by design' "$HC_GD/pd.err" && echo yes || echo no)"
# implement class → resolve the PR that closes the issue (via pr list stub).
HC_G_IMP="$(DEVFLOW_GH="$HC_GD/gh" STUB_PR_LIST=70 bash "$HC_GLUE" "$HC_GD/exec.json" "implement" 7 "$HC_GD/c6.json" 2>/dev/null)"
assert_eq "hc-glue(A7): implement class → the PR opened for the issue is resolved" "yes" \
  "$(printf '%s' "$HC_G_IMP" | grep -qF "DEVFLOW_EXECUTION_PR='70'" && echo yes || echo no)"
assert_eq "hc-glue(A7): implement class label emitted" "yes" \
  "$(printf '%s' "$HC_G_IMP" | grep -qF "DEVFLOW_COMMAND_CLASS='implement'" && echo yes || echo no)"
# implement class, LOOKUP-FAILED (AC7-named branch): empty STUB_PR_LIST → _resolve_pr_for_issue
# finds no closing PR → empty PR + the specific "could not resolve the PR opened for issue"
# breadcrumb (distinct from not-a-PR and inert). Its OWN breadcrumb attributes the skip.
HC_G_ILF="$(DEVFLOW_GH="$HC_GD/gh" STUB_PR_LIST='' bash "$HC_GLUE" "$HC_GD/exec.json" "implement" 7 "$HC_GD/c7.json" 2>"$HC_GD/ilf.err")"
assert_eq "hc-glue(A7): implement lookup-failed → DEVFLOW_EXECUTION_PR empty" "yes" \
  "$(printf '%s' "$HC_G_ILF" | grep -qF "DEVFLOW_EXECUTION_PR=''" && echo yes || echo no)"
assert_eq "hc-glue(A7): implement lookup-failed → the specific 'could not resolve the PR opened for issue' breadcrumb" "yes" \
  "$(grep -qF 'could not resolve the PR opened for issue' "$HC_GD/ilf.err" && echo yes || echo no)"
# reader PARSE-FAIL inert: a PRESENT, non-empty execution file the reader cannot parse
# (garbage) → COST empty → the distinct "could not be parsed for cost" breadcrumb (NOT the
# absent-file "execution file absent" one). Positive control: a real reader ran (the file
# exists and is non-empty), so the branch is attributed to a parse failure, not an absent file.
printf 'not json at all {{{' > "$HC_GD/garbage.json"
HC_G_PF="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/garbage.json" "/devflow:review-and-fix" 50 "$HC_GD/c8.json" 2>"$HC_GD/pf.err")"
assert_eq "hc-glue(A7): reader parse-fail → the cost handoff stays empty (the cost floor is inert)" "no" \
  "$([ -s "$HC_GD/c8.json" ] && echo yes || echo no)"
assert_eq "hc-glue(A7): reader parse-fail → the shared PR operand is still resolved" "yes" \
  "$(printf '%s' "$HC_G_PF" | grep -qF "DEVFLOW_EXECUTION_PR='50'" && echo yes || echo no)"
assert_eq "hc-glue(A7): reader parse-fail → the 'could not be parsed for cost' breadcrumb (not the absent-file one)" "yes" \
  "$(grep -qF 'could not be parsed for cost' "$HC_GD/pf.err" && ! grep -qF 'execution file absent' "$HC_GD/pf.err" && echo yes || echo no)"
# review class, EMPTY-NUM: no explicit number in the command AND an empty candidate →
# NUM empty → the specific "no PR number resolved" breadcrumb (distinct from not-a-PR).
HC_G_EN="$(DEVFLOW_GH="$HC_GD/gh" STUB_PRS=50 bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:review-and-fix" "" "$HC_GD/c9.json" 2>"$HC_GD/en.err")"
assert_eq "hc-glue(A7): review empty-NUM → DEVFLOW_EXECUTION_PR empty" "yes" \
  "$(printf '%s' "$HC_G_EN" | grep -qF "DEVFLOW_EXECUTION_PR=''" && echo yes || echo no)"
assert_eq "hc-glue(A7): review empty-NUM → the specific 'no PR number resolved' breadcrumb" "yes" \
  "$(grep -qF 'no PR number resolved' "$HC_GD/en.err" && echo yes || echo no)"
# unrecognized command class → CLASS sanitized to "" → the `*)` arm's "unrecognized command"
# breadcrumb, empty PR and empty class.
HC_G_UC="$(DEVFLOW_GH="$HC_GD/gh" bash "$HC_GLUE" "$HC_GD/exec.json" "/devflow:frobnicate 9" 9 "$HC_GD/c10.json" 2>"$HC_GD/uc.err")"
assert_eq "hc-glue(A7): unrecognized class → DEVFLOW_EXECUTION_PR empty and class empty" "yes" \
  "$(printf '%s' "$HC_G_UC" | grep -qF "DEVFLOW_EXECUTION_PR=''" && printf '%s' "$HC_G_UC" | grep -qF "DEVFLOW_COMMAND_CLASS=''" && echo yes || echo no)"
assert_eq "hc-glue(A7): unrecognized class → the 'unrecognized command' breadcrumb" "yes" \
  "$(grep -qF 'unrecognized command' "$HC_GD/uc.err" && echo yes || echo no)"
rm -rf "$HC_GD"

# ── Reader result-event precedence (_ordered_dicts): a type=="result" summary cost must win
# over a competing costUSD on a NON-result (streamed message) dict. Every other reader fixture
# has the cost only on the result event, so the ordering itself was unexercised — reorder to
# `others + results` and the suite would otherwise stay green.
HC_ORD="$(git_sandbox "hc reader ordering")"
printf '%s' '[{"costUSD":0.11},{"type":"result","total_cost_usd":0.99}]' > "$HC_ORD/ord.json"
assert_eq "hc-reader(A2): a result-event cost wins over a competing non-result costUSD (_ordered_dicts precedence)" "0.99" \
  "$(python3 "$HC_READER" "$HC_ORD/ord.json" 2>/dev/null | jq -c '.cost_usd')"
rm -rf "$HC_ORD"

# ── engine_version:null (AC4 fail-closed): an unreadable/malformed plugin.json → engine_version
# is null WITH a breadcrumb, never fabricated. Every other HC test runs the helper beside the
# real repo's plugin.json (a valid string .version), so this fail-closed arm was unexercised.
# Relocate the helper into a scratch lib/ whose sibling .claude-plugin/plugin.json has a
# NON-STRING .version, so the `(.version|type)=="string"` guard fails. Drive the SKELETON arm
# (no iter dir → no record-derivation/config_fingerprint dependency), which builds harness_cost
# via the SAME engine_version resolution and writes it into the skeleton.
HC_EV_ROOT="$(git_sandbox "hc engine-version-null root")"
mkdir -p "$HC_EV_ROOT/lib" "$HC_EV_ROOT/.claude-plugin"
cp "$LIB"/*.sh "$LIB"/*.jq "$HC_EV_ROOT/lib/" 2>/dev/null
printf '%s' '{"version": 123}' > "$HC_EV_ROOT/.claude-plugin/plugin.json"   # .version is a NUMBER, not a string
HC_EV="$(_hc_repo "hc ev record")"
HC_EV_ERR="$( ( cd "$HC_EV" && GITHUB_RUN_ID=ev GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_EXECUTION_PR=1 DEVFLOW_COMMAND_CLASS=review-and-fix bash "$HC_EV_ROOT/lib/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-engineversion(A4): malformed plugin.json (.version not a string) → engine_version is null (never fabricated)" "null" \
  "$(_et_show "$HC_EV" ".prflow/logs/efficiency/pr-1-ev-1.json" | jq -c '.harness_cost.engine_version')"
assert_eq "hc-engineversion(A4): the floor still attaches harness_cost (only engine_version degrades)" "execution-file" \
  "$(_et_show "$HC_EV" ".prflow/logs/efficiency/pr-1-ev-1.json" | jq -r '.harness_cost.cost_source')"
assert_eq "hc-engineversion(A4): a specific 'engine_version recorded as null' breadcrumb (never silent)" "yes" \
  "$(printf '%s' "$HC_EV_ERR" | grep -qF 'engine_version recorded as null' && echo yes || echo no)"
rm -rf "$HC_EV" "$HC_EV_ROOT"

# ── Union MIDDLE arm (base LACKS harness_cost, this run's staged copy HAS it → add-local's-hc
# onto base). The A5a-staged fixture makes writer A merge harness_cost onto R BEFORE the union,
# so base already carries it (the base-wins FIRST jq arm). The ordinary concurrent case — this
# run is the only writer that added harness_cost and must LAND it onto a base copy that lacks it
# — is the middle `elif ($local.harness_cost != null)` arm, otherwise undriven. Base holds R
# WITHOUT harness_cost; a concurrent writer pushes an UNRELATED record (diverging the remote so
# B's push is rejected); B stages R with harness_cost cost_usd=5 (merge-arm-b ident=run-m re-stages
# the stale local R with B's own cost); the re-parent union must ADD B's harness_cost onto base R.
HC_MA_BARE="$(git_sandbox "hc midarm bare")"; git -C "$HC_MA_BARE" init --bare -q
HC_MA="$(git_sandbox "hc midarm repo")"; git -C "$HC_MA" init -q
git -C "$HC_MA" config user.email t@e.com; git -C "$HC_MA" config user.name t
git -C "$HC_MA" remote add origin "$HC_MA_BARE"
mkdir -p "$HC_MA/.prflow"; printf 'tmp/\n' > "$HC_MA/.prflow/.gitignore"
git -C "$HC_MA" add -A; git -C "$HC_MA" commit -qm seed; git -C "$HC_MA" branch -M main
git -C "$HC_MA" push -q -u origin main
HC_MA_REC='{"schema_version":1,"slug":"pr-6","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":1,"telemetry":[]}'
# B's stale LOCAL telemetry tip holds R WITHOUT harness_cost (what merge-arm-b re-stages).
mv "$HC_MA_BARE" "${HC_MA_BARE}.down"
HC_MA_IDX="$HC_MA/.git/maidx"
HC_MA_SB="$(printf '%s' "$HC_MA_REC" | git -C "$HC_MA" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_MA_IDX" git -C "$HC_MA" update-index --add --cacheinfo "100644,${HC_MA_SB},.prflow/logs/efficiency/pr-6-run-m.json"
HC_MA_ST="$(GIT_INDEX_FILE="$HC_MA_IDX" git -C "$HC_MA" write-tree)"; rm -f "$HC_MA_IDX"
HC_MA_SN="$(GIT_AUTHOR_NAME=b GIT_AUTHOR_EMAIL=b@y GIT_COMMITTER_NAME=b GIT_COMMITTER_EMAIL=b@y git -C "$HC_MA" commit-tree "$HC_MA_ST" -m b)"
git -C "$HC_MA" update-ref refs/heads/prflow-telemetry "$HC_MA_SN"
mv "${HC_MA_BARE}.down" "$HC_MA_BARE"
# Writer A seeds R (NO harness_cost) on base AND an UNRELATED record, then pushes → the remote
# tip diverges from B's local tip so B's push is rejected, forcing the re-parent union over R.
HC_MA_A="$(git_sandbox "hc midarm writerA")"; git clone -q "$HC_MA_BARE" "$HC_MA_A" 2>/dev/null
HC_MA_AIDX="$HC_MA_A/.git/aidx"
HC_MA_ASB="$(printf '%s' "$HC_MA_REC" | git -C "$HC_MA_A" hash-object -w --stdin)"
HC_MA_AOTH="$(printf '%s' '{"schema_version":1,"slug":"pr-9","generated_at":"2026-01-01T00:00:00Z","source":"review","iterations":1,"telemetry":[]}' | git -C "$HC_MA_A" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_MA_AIDX" git -C "$HC_MA_A" update-index --add --cacheinfo "100644,${HC_MA_ASB},.prflow/logs/efficiency/pr-6-run-m.json"
GIT_INDEX_FILE="$HC_MA_AIDX" git -C "$HC_MA_A" update-index --add --cacheinfo "100644,${HC_MA_AOTH},.prflow/logs/efficiency/pr-9-run-other.json"
HC_MA_AT="$(GIT_INDEX_FILE="$HC_MA_AIDX" git -C "$HC_MA_A" write-tree)"; rm -f "$HC_MA_AIDX"
HC_MA_AN="$(GIT_AUTHOR_NAME=a GIT_AUTHOR_EMAIL=a@y GIT_COMMITTER_NAME=a GIT_COMMITTER_EMAIL=a@y git -C "$HC_MA_A" commit-tree "$HC_MA_AT" -m a)"
git -C "$HC_MA_A" update-ref refs/heads/prflow-telemetry "$HC_MA_AN"
git -C "$HC_MA_A" push -q origin prflow-telemetry
# B persists with the floor env (ident=run-m matches R's filename → merge-arm-b re-stages R with
# cost_usd=5) plus its own new run dir; the push is rejected (remote diverged) and the re-parent
# runs the STAGED efficiency-record union arm over R — base R lacks harness_cost, local R has it.
mkdir -p "$HC_MA/.prflow/tmp/review/pr-6/run-b"
printf '%s' "$HC_ITER" > "$HC_MA/.prflow/tmp/review/pr-6/run-b/iter-1.json"
( cd "$HC_MA" && GITHUB_RUN_ID=run GITHUB_RUN_ATTEMPT=m \
    DEVFLOW_EXECUTION_COST='{"cost_usd":5,"tokens":{},"model_usage":null,"num_turns":null,"duration_ms":null}' \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
git -C "$HC_MA" fetch -q origin prflow-telemetry:refs/remotes/origin/ma 2>/dev/null
assert_eq "hc-race(A5a middle): base R lacked harness_cost, this run's staged copy had it → the union ADDS it (cost_usd=5)" "5" \
  "$(git -C "$HC_MA" show "refs/remotes/origin/ma:.prflow/logs/efficiency/pr-6-run-m.json" 2>/dev/null | jq -c '.harness_cost.cost_usd')"
assert_eq "hc-race(A5a middle): the concurrent writer's UNRELATED record is preserved on base (base-wins for an unstaged path)" "yes" \
  "$(git -C "$HC_MA" cat-file -e "refs/remotes/origin/ma:.prflow/logs/efficiency/pr-9-run-other.json" >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$HC_MA" "$HC_MA_BARE" "$HC_MA_A"

# ── Finding #475-review-5: the reader's modelUsage extraction, secondary wrong-type
# breadcrumbs (num_turns/duration_ms), and the arg-count guard were untested (every prior
# wrong-type fixture drove only the cost field). ──
HC_RM="$(git_sandbox "hc reader misc")"
# modelUsage: a dict is surfaced verbatim as model_usage (the first dict wins).
printf '%s' '{"type":"result","modelUsage":{"claude-x":{"in":5,"out":2}},"total_cost_usd":1}' > "$HC_RM/mu.json"
assert_eq "hc-reader(A2): a modelUsage object is surfaced verbatim as model_usage" '{"claude-x":{"in":5,"out":2}}' \
  "$(python3 "$HC_READER" "$HC_RM/mu.json" 2>/dev/null | jq -c '.model_usage')"
# modelUsage present but NOT a dict → model_usage null + its specific wrong-type breadcrumb.
printf '%s' '{"type":"result","modelUsage":"not-a-dict","total_cost_usd":1}' > "$HC_RM/muw.json"
assert_eq "hc-reader(A2): a non-object modelUsage → model_usage null (never a scalar)" "null" \
  "$(python3 "$HC_READER" "$HC_RM/muw.json" 2>/dev/null | jq -c '.model_usage')"
assert_eq "hc-reader(A2): a non-object modelUsage → its breadcrumb names 'modelUsage'" "yes" \
  "$(python3 "$HC_READER" "$HC_RM/muw.json" 2>&1 1>/dev/null | grep -qF "field 'modelUsage'" && echo yes || echo no)"
# secondary wrong-type: num_turns/duration_ms non-numeric → null + their OWN breadcrumbs.
printf '%s' '{"type":"result","num_turns":"nope","duration_ms":[1],"total_cost_usd":1}' > "$HC_RM/nt.json"
assert_eq "hc-reader(A2): non-numeric num_turns → null" "null" \
  "$(python3 "$HC_READER" "$HC_RM/nt.json" 2>/dev/null | jq -c '.num_turns')"
assert_eq "hc-reader(A2): non-numeric duration_ms → null" "null" \
  "$(python3 "$HC_READER" "$HC_RM/nt.json" 2>/dev/null | jq -c '.duration_ms')"
assert_eq "hc-reader(A2): num_turns wrong-type → its own 'field num_turns' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_RM/nt.json" 2>&1 1>/dev/null | grep -qF "field 'num_turns'" && echo yes || echo no)"
assert_eq "hc-reader(A2): duration_ms wrong-type → its own 'field duration_ms' breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_RM/nt.json" 2>&1 1>/dev/null | grep -qF "field 'duration_ms'" && echo yes || echo no)"
# arg-count guard: zero args and two args → the "expected exactly one argument" breadcrumb,
# exit 0, and NOTHING on stdout (best-effort; never a stack trace).
HC_RM_A0="$(python3 "$HC_READER" 2>"$HC_RM/a0.err"; echo "rc=$?")"
assert_eq "hc-reader(A2): zero args → exit 0, no stdout" "rc=0" "$HC_RM_A0"
assert_eq "hc-reader(A2): zero args → the arg-count breadcrumb" "yes" \
  "$(grep -qF 'expected exactly one argument' "$HC_RM/a0.err" && echo yes || echo no)"
HC_RM_A2="$(python3 "$HC_READER" "$HC_RM/mu.json" extra 2>"$HC_RM/a2.err"; echo "rc=$?")"
assert_eq "hc-reader(A2): two args → exit 0, no stdout" "rc=0" "$HC_RM_A2"
assert_eq "hc-reader(A2): two args → the arg-count breadcrumb" "yes" \
  "$(grep -qF 'expected exactly one argument' "$HC_RM/a2.err" && echo yes || echo no)"
# A parsed file can lack cost_usd while still carrying another usable figure such as
# num_turns. The reader names that absence; A7 separately proves the glue refuses a
# truly all-null payload instead of staging it as cost coverage.
printf '%s' '{"type":"result","num_turns":3}' > "$HC_RM/nocost.json"
assert_eq "hc-reader(A2): parsed-but-no-cost → the 'carried no cost figure' summary breadcrumb" "yes" \
  "$(python3 "$HC_READER" "$HC_RM/nocost.json" 2>&1 1>/dev/null | grep -qF 'carried no cost figure' && echo yes || echo no)"
# The fallback token accumulation must NOT sum `total_tokens` (a summary figure): summing a
# possibly-cumulative field would over-count, so it stays null on the per-message path while the
# per-message components (input_tokens) still sum (issue #475 review finding 1, unknown-is-not-zero).
printf '%s' '[{"usage":{"input_tokens":100,"total_tokens":105}},{"usage":{"input_tokens":50,"total_tokens":60}}]' > "$HC_RM/ttok.json"
assert_eq "hc-reader(A2): fallback path sums per-message input_tokens (150)" "150" \
  "$(python3 "$HC_READER" "$HC_RM/ttok.json" 2>/dev/null | jq -c '.tokens.input_tokens')"
assert_eq "hc-reader(A2): fallback path does NOT sum total_tokens — stays null (no over-count)" "null" \
  "$(python3 "$HC_READER" "$HC_RM/ttok.json" 2>/dev/null | jq -c '.tokens.total_tokens')"
# But the AUTHORITATIVE result-summary path still reads total_tokens as-is (the run total).
printf '%s' '[{"type":"result","usage":{"input_tokens":500,"total_tokens":600}}]' > "$HC_RM/ttok2.json"
assert_eq "hc-reader(A2): result-summary path reads total_tokens verbatim (600)" "600" \
  "$(python3 "$HC_READER" "$HC_RM/ttok2.json" 2>/dev/null | jq -c '.tokens.total_tokens')"
rm -rf "$HC_RM"

# ── Finding #475-review-2: the merge-aware union's jq-unavailable / empty-blob LOCAL-WINS FALLBACK
# branch (telemetry-branch.sh) was untested — every union-race fixture ran with jq available, so the
# load-bearing "a concurrent base-side harness_cost may be reverted" ::warning:: never executed.
# Reproduce the A5a-staged race but point DEVFLOW_JQ at a wrapper that fails ONLY the union merge
# program (identified by its unique `elif ($local.harness_cost` text) and delegates everything else
# to real jq — so the floor still stages R with cost_usd=5, but the union's jq fails and takes the
# local-wins fallback (R → 5, NOT the base-wins 9 the working union keeps). ──
HC_UF_BARE="$(git_sandbox "hc unionfb bare")"; git -C "$HC_UF_BARE" init --bare -q
HC_UF="$(git_sandbox "hc unionfb repo")"; git -C "$HC_UF" init -q
git -C "$HC_UF" config user.email t@e.com; git -C "$HC_UF" config user.name t
git -C "$HC_UF" remote add origin "$HC_UF_BARE"
mkdir -p "$HC_UF/.prflow"; printf 'tmp/\n' > "$HC_UF/.prflow/.gitignore"
git -C "$HC_UF" add -A; git -C "$HC_UF" commit -qm seed; git -C "$HC_UF" branch -M main
git -C "$HC_UF" push -q -u origin main
HC_UF_REC='{"schema_version":1,"slug":"pr-6","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":1,"telemetry":[]}'
mv "$HC_UF_BARE" "${HC_UF_BARE}.down"
HC_UF_IDX="$HC_UF/.git/ufidx"
HC_UF_SB="$(printf '%s' "$HC_UF_REC" | git -C "$HC_UF" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_UF_IDX" git -C "$HC_UF" update-index --add --cacheinfo "100644,${HC_UF_SB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_UF_ST="$(GIT_INDEX_FILE="$HC_UF_IDX" git -C "$HC_UF" write-tree)"; rm -f "$HC_UF_IDX"
HC_UF_SN="$(GIT_AUTHOR_NAME=b GIT_AUTHOR_EMAIL=b@y GIT_COMMITTER_NAME=b GIT_COMMITTER_EMAIL=b@y git -C "$HC_UF" commit-tree "$HC_UF_ST" -m b)"
git -C "$HC_UF" update-ref refs/heads/prflow-telemetry "$HC_UF_SN"
mv "${HC_UF_BARE}.down" "$HC_UF_BARE"
HC_UF_A="$(git_sandbox "hc unionfb writerA")"; git clone -q "$HC_UF_BARE" "$HC_UF_A" 2>/dev/null
HC_UF_AREC="$(printf '%s' "$HC_UF_REC" | jq -c '.harness_cost={cost_source:"execution-file",cost_usd:9}')"
HC_UF_AIDX="$HC_UF_A/.git/aidx"
HC_UF_AB="$(printf '%s' "$HC_UF_AREC" | git -C "$HC_UF_A" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_UF_AIDX" git -C "$HC_UF_A" update-index --add --cacheinfo "100644,${HC_UF_AB},.prflow/logs/efficiency/pr-6-run-r.json"
HC_UF_AT="$(GIT_INDEX_FILE="$HC_UF_AIDX" git -C "$HC_UF_A" write-tree)"; rm -f "$HC_UF_AIDX"
HC_UF_AN="$(GIT_AUTHOR_NAME=a GIT_AUTHOR_EMAIL=a@y GIT_COMMITTER_NAME=a GIT_COMMITTER_EMAIL=a@y git -C "$HC_UF_A" commit-tree "$HC_UF_AT" -m a)"
git -C "$HC_UF_A" update-ref refs/heads/prflow-telemetry "$HC_UF_AN"
git -C "$HC_UF_A" push -q origin prflow-telemetry
# Selective jq wrapper: fail ONLY the union merge program, delegate all else to real jq.
printf '%s\n' '#!/usr/bin/env bash' 'for a in "$@"; do case "$a" in *"elif (\$local.harness_cost"*) exit 1 ;; esac; done' 'exec jq "$@"' > "$HC_UF/jqsel"
chmod +x "$HC_UF/jqsel"
mkdir -p "$HC_UF/.prflow/tmp/review/pr-6/run-b"
printf '%s' "$HC_ITER" > "$HC_UF/.prflow/tmp/review/pr-6/run-b/iter-1.json"
HC_UF_ERR="$( ( cd "$HC_UF" && GITHUB_RUN_ID=run GITHUB_RUN_ATTEMPT=r DEVFLOW_JQ="$HC_UF/jqsel" \
    DEVFLOW_EXECUTION_COST='{"cost_usd":5,"tokens":{},"model_usage":null,"num_turns":null,"duration_ms":null}' \
    DEVFLOW_COMMAND_CLASS=review-and-fix bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
git -C "$HC_UF" fetch -q origin prflow-telemetry:refs/remotes/origin/uf 2>/dev/null
assert_eq "hc-race(A5a fallback): union jq failed → LOCAL-WINS fallback (R reverts to this run's staged cost_usd=5, not base-wins 9)" "5" \
  "$(git -C "$HC_UF" show "refs/remotes/origin/uf:.prflow/logs/efficiency/pr-6-run-r.json" 2>/dev/null | jq -c '.harness_cost.cost_usd')"
assert_eq "hc-race(A5a fallback): the fallback emits the 'fell back to local-wins' ::warning:: (never silent)" "yes" \
  "$(printf '%s' "$HC_UF_ERR" | grep -qF 'fell back to local-wins' && echo yes || echo no)"
rm -rf "$HC_UF" "$HC_UF_BARE" "$HC_UF_A"

# ── Finding #475-review-3: the skeleton-overwrite guard had only a line-presence check (A10)
# — no POSITIVE behavioral fixture proving it declines when a real record already occupies the
# skeleton's filename. Seed a real record on the branch at the skeleton path, then force merge-arm-b
# to MISS it (patch the copied telemetry-branch.sh so list_blobs returns empty while blob_exists still
# finds it — the exact "swallowed git failure" ambiguity the guard defends). The guard must decline
# and leave the real record intact rather than overwrite it with an iterations:0 skeleton. ──
HC_SO_ROOT="$(git_sandbox "hc skel-overwrite root")"
mkdir -p "$HC_SO_ROOT/lib" "$HC_SO_ROOT/.claude-plugin"
cp "$LIB"/*.sh "$LIB"/*.jq "$HC_SO_ROOT/lib/" 2>/dev/null
cp "$LIB/../.claude-plugin/plugin.json" "$HC_SO_ROOT/.claude-plugin/" 2>/dev/null
# Redefine list_blobs to always-empty (last def wins on source); blob_exists stays real.
printf '\ndevflow_telemetry_list_blobs() { return 0; }\n' >> "$HC_SO_ROOT/lib/telemetry-branch.sh"
HC_SO="$(_hc_repo "hc skel-overwrite")"
# Seed a REAL, populated record on the telemetry branch at the skeleton's own filename.
HC_SO_REC='{"schema_version":1,"slug":"pr-42","generated_at":"2026-01-01T00:00:00Z","source":"review-and-fix","iterations":7,"real_marker":true,"telemetry":[]}'
HC_SO_IDX="$HC_SO/.git/soidx"
HC_SO_SB="$(printf '%s' "$HC_SO_REC" | git -C "$HC_SO" hash-object -w --stdin)"
GIT_INDEX_FILE="$HC_SO_IDX" git -C "$HC_SO" update-index --add --cacheinfo "100644,${HC_SO_SB},.prflow/logs/efficiency/pr-42-555-1.json"
HC_SO_ST="$(GIT_INDEX_FILE="$HC_SO_IDX" git -C "$HC_SO" write-tree)"; rm -f "$HC_SO_IDX"
HC_SO_SN="$(GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@e GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@e git -C "$HC_SO" commit-tree "$HC_SO_ST" -m seed-record)"
git -C "$HC_SO" update-ref refs/heads/prflow-telemetry "$HC_SO_SN"
# Run --persist with the SKELETON env (no iter dir → skeleton arm) via the PATCHED lib.
HC_SO_ERR="$( ( cd "$HC_SO" && GITHUB_RUN_ID=555 GITHUB_RUN_ATTEMPT=1 DEVFLOW_EXECUTION_COST="$HC_COST" \
    DEVFLOW_EXECUTION_PR=42 DEVFLOW_COMMAND_CLASS=review-and-fix bash "$HC_SO_ROOT/lib/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "hc-skeleton(A6+): guard declines → the real branch record is NOT overwritten (iterations still 7, not the skeleton's 0)" "7" \
  "$(git -C "$HC_SO" show "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-42-555-1.json" 2>/dev/null | jq -c '.iterations')"
assert_eq "hc-skeleton(A6+): guard declines → the real record's marker survives (skeleton never written over it)" "true" \
  "$(git -C "$HC_SO" show "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-42-555-1.json" 2>/dev/null | jq -c '.real_marker')"
assert_eq "hc-skeleton(A6+): guard declines → the specific 'declining to overwrite it with a cost skeleton' breadcrumb" "yes" \
  "$(printf '%s' "$HC_SO_ERR" | grep -qF 'declining to overwrite it with a cost skeleton' && echo yes || echo no)"
rm -rf "$HC_SO" "$HC_SO_ROOT"

# ── issue #381: synthesis floor — --persist reconstructs a minimal iteration
# record from the branch's fix commits when a run left ZERO iter-*.json ────────
echo "efficiency-trace.sh synthesis floor (issue #381)"

# T2 → AC2: workpad-less run dir + two fix commits → synthesized record.
ETSY_REPO="$(git_sandbox "et-synth happy-path repo")"
git -C "$ETSY_REPO" init -q
git -C "$ETSY_REPO" config user.email t@e.com; git -C "$ETSY_REPO" config user.name t
git -C "$ETSY_REPO" commit --allow-empty -qm base
git -C "$ETSY_REPO" branch -M main
git -C "$ETSY_REPO" checkout -q -b feat
printf a > "$ETSY_REPO/f1"; git -C "$ETSY_REPO" add f1
git -C "$ETSY_REPO" commit -qm "fix: address review findings (iteration 1)"
printf b > "$ETSY_REPO/f2"; git -C "$ETSY_REPO" add f2
git -C "$ETSY_REPO" commit -qm "fix: address review findings (iteration 2)"
mkdir -p "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s"
( cd "$ETSY_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s" --slug pr-1 ) >/dev/null 2>&1; ETSY_RC=$?
ETSY_REC_PATH=".prflow/logs/efficiency/pr-1-run-s.json"   # read from the telemetry branch (#441)
assert_eq "et-synth(T2): --persist always exits 0" "0" "$ETSY_RC"
assert_eq "et-synth(T2): a record is synthesized (on the branch) where a workpad-less run left none" "yes" \
  "$(_et_on_branch "$ETSY_REPO" "$ETSY_REC_PATH")"
assert_eq "et-synth(T2): record-level synthesized flag is true" "true" \
  "$(_et_show "$ETSY_REPO" "$ETSY_REC_PATH" | jq -r '.synthesized' 2>/dev/null)"
assert_eq "et-synth(T2): two iterations reconstructed" "2" \
  "$(_et_show "$ETSY_REPO" "$ETSY_REC_PATH" | jq -r '.iterations' 2>/dev/null)"
assert_eq "et-synth(T2): iters are [1,2] in order" "[1,2]" \
  "$(_et_show "$ETSY_REPO" "$ETSY_REC_PATH" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
assert_eq "et-synth(T2): per-iteration synthesized flag surfaced" "true" \
  "$(_et_show "$ETSY_REPO" "$ETSY_REC_PATH" | jq -r '.per_iteration[0].synthesized' 2>/dev/null)"
assert_eq "et-synth(T2): synthesized iter loop_role is fix" "fix" \
  "$(_et_show "$ETSY_REPO" "$ETSY_REC_PATH" | jq -r '.per_iteration[0].loop_role' 2>/dev/null)"
assert_eq "et-synth(T2): synthesized iter-1 carries the real fix_commit_sha" \
  "$(git -C "$ETSY_REPO" rev-list --reverse main..HEAD | head -1)" \
  "$(jq -r '.fix_commit_sha' "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s/iter-1.json" 2>/dev/null)"
assert_eq "et-synth(T2): synthesized iter-1 fix_files is the commit's file" '["f1"]' \
  "$(jq -c '.fix_files' "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s/iter-1.json" 2>/dev/null)"
assert_eq "et-synth(T2): synthesized iter carries the synthesized:true marker" "true" \
  "$(jq -r '.synthesized' "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s/iter-1.json" 2>/dev/null)"
# T4 (jq consumption): synthesized minimal records render in both modes rc-0 with
# the existing degraded posture (none-recorded), never a null-detonation.
ETSY_TRACE="$( ( cd "$ETSY_REPO" && bash "$LIB/efficiency-trace.sh" --mode trace --workpad-dir "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s" --slug pr-1 ) 2>/dev/null )"; ETSY_TRC=$?
assert_eq "et-synth(T4): --mode trace over synthesized records exits 0" "0" "$ETSY_TRC"
assert_eq "et-synth(T4): trace reports the none-recorded degraded posture" "yes" \
  "$(printf '%s' "$ETSY_TRACE" | grep -qF 'none recorded' && echo yes || echo no)"
ETSY_RMODE="$( ( cd "$ETSY_REPO" && bash "$LIB/efficiency-trace.sh" --mode record --workpad-dir "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s" --slug pr-1 ) 2>/dev/null )"; ETSY_RMRC=$?
assert_eq "et-synth(T4): --mode record over synthesized records exits 0" "0" "$ETSY_RMRC"
assert_eq "et-synth(T4): record-mode verification_posture is the degraded value" "none-recorded" \
  "$(printf '%s' "$ETSY_RMODE" | jq -r '.per_iteration[0].verification_posture' 2>/dev/null)"
# Writer <-> validator lockstep: --self-check over the REAL freshly-synthesized
# records (not a hand-written fixture) emits no missing-field warning — a drift
# in either ITER_SYNTH_EXPECTED_FIELDS or the writer's jq object goes RED here.
ETSY_SC="$( ( cd "$ETSY_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s" --slug pr-1 ) 2>&1 )"
assert_eq "et-synth(T2): real synthesized records validate cleanly against ITER_SYNTH_EXPECTED_FIELDS" "no" \
  "$(printf '%s' "$ETSY_SC" | grep -qF 'is missing expected field' && echo yes || echo no)"
# Idempotency: a second --persist makes no new BRANCH commit.
ETSY_C1="$(_et_branch_count "$ETSY_REPO")"
( cd "$ETSY_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSY_REPO/.prflow/tmp/review/pr-1/run-s" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-synth(T2): second --persist is a no-op (no new branch commit)" "$ETSY_C1" \
  "$(_et_branch_count "$ETSY_REPO")"
rm -rf "$ETSY_REPO"

# ── issue #534: emitted-provenance backfill — the three states a later reader must
# tell apart (an EMITTED record, a SYNTHESIZED record, a LOST emit) are
# deterministically distinguishable at the producer. Route (b): --persist stamps
# the `synthesized` provenance boolean off the agent's decision path, so an
# agent-written record affirmatively carries synthesized:false, a backstop record
# carries synthesized:true, and a lost emit is the absent record. Exercises the
# producer (lib/efficiency-trace.sh --persist), not prose.
echo "efficiency-trace.sh emitted-provenance backfill (issue #534)"

# EMITTED: a real agent-written iter-1.json (rich fields, NO `synthesized` key) →
# --persist backfills synthesized:false and preserves the record's other fields.
ETPV_REPO="$(git_sandbox "et-prov emitted repo")"
git -C "$ETPV_REPO" init -q
git -C "$ETPV_REPO" config user.email t@e.com; git -C "$ETPV_REPO" config user.name t
git -C "$ETPV_REPO" commit --allow-empty -qm base
git -C "$ETPV_REPO" branch -M main
git -C "$ETPV_REPO" checkout -q -b feat
mkdir -p "$ETPV_REPO/.prflow/tmp/review/pr-3/run-e"
cat > "$ETPV_REPO/.prflow/tmp/review/pr-3/run-e/iter-1.json" <<'EOF'
{"iter":1,"fix_commit_sha":"deadbeef","loop_role":"fix","fix_files":["x"]}
EOF
( cd "$ETPV_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPV_REPO/.prflow/tmp/review/pr-3/run-e" --slug pr-3 ) >/dev/null 2>&1; ETPV_RC=$?
assert_eq "et-prov(#534): emitted-case --persist exits 0" "0" "$ETPV_RC"
assert_eq "et-prov(#534): EMITTED — the DURABLE copy is backfilled synthesized:false" "false" \
  "$(_et_show "$ETPV_REPO" ".prflow/logs/review/pr-3/run-e/iter-1.json" | jq -r '.synthesized' 2>/dev/null)"
assert_eq "et-prov(#534): EMITTED — the durable record's other fields are preserved through the backfill" "deadbeef" \
  "$(_et_show "$ETPV_REPO" ".prflow/logs/review/pr-3/run-e/iter-1.json" | jq -r '.fix_commit_sha' 2>/dev/null)"
# The SOURCE run dir is left byte-identical (an existing --persist contract): the
# stamp lands on the durable copy only, so the agent's file gains no `synthesized`.
assert_eq "et-prov(#534): EMITTED — the SOURCE record is left untouched (no synthesized key)" "null" \
  "$(jq -r '.synthesized' "$ETPV_REPO/.prflow/tmp/review/pr-3/run-e/iter-1.json" 2>/dev/null)"
# Idempotent: a second --persist keeps the durable stamp false (a no-op branch write).
( cd "$ETPV_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPV_REPO/.prflow/tmp/review/pr-3/run-e" --slug pr-3 ) >/dev/null 2>&1
assert_eq "et-prov(#534): EMITTED — second --persist keeps the durable synthesized:false (idempotent)" "false" \
  "$(_et_show "$ETPV_REPO" ".prflow/logs/review/pr-3/run-e/iter-1.json" | jq -r '.synthesized' 2>/dev/null)"
rm -rf "$ETPV_REPO"

# SYNTHESIZED: no iter record + a fix commit → the backstop writes synthesized:true
# — distinct from the emitted false above, and the backfill leaves it untouched.
ETPS_REPO="$(git_sandbox "et-prov synthesized repo")"
git -C "$ETPS_REPO" init -q
git -C "$ETPS_REPO" config user.email t@e.com; git -C "$ETPS_REPO" config user.name t
git -C "$ETPS_REPO" commit --allow-empty -qm base
git -C "$ETPS_REPO" branch -M main
git -C "$ETPS_REPO" checkout -q -b feat
printf a > "$ETPS_REPO/f1"; git -C "$ETPS_REPO" add f1
git -C "$ETPS_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETPS_REPO/.prflow/tmp/review/pr-4/run-s"
( cd "$ETPS_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPS_REPO/.prflow/tmp/review/pr-4/run-s" --slug pr-4 ) >/dev/null 2>&1
assert_eq "et-prov(#534): SYNTHESIZED — a backstop record carries synthesized:true (not false)" "true" \
  "$(jq -r '.synthesized' "$ETPS_REPO/.prflow/tmp/review/pr-4/run-s/iter-1.json" 2>/dev/null)"
# Guard the has("synthesized")|not predicate from the OTHER direction: the DURABLE
# copy of a synthesized record must NOT be clobbered to false. Read the same
# persisted artifact the EMITTED case reads (the durable branch copy), so all three
# states are asserted at the one place a later reader consults. An inverted predicate
# that stamped key-present records would flip this to false and go RED here.
assert_eq "et-prov(#534): SYNTHESIZED — the DURABLE copy is NOT clobbered to false (stays true)" "true" \
  "$(_et_show "$ETPS_REPO" ".prflow/logs/review/pr-4/run-s/iter-1.json" | jq -r '.synthesized' 2>/dev/null)"
rm -rf "$ETPS_REPO"

# LOST: no iter record + no matching fix commit → no record at all (the absent
# third state — no file exists to carry any provenance stamp).
ETPL_REPO="$(git_sandbox "et-prov lost repo")"
git -C "$ETPL_REPO" init -q
git -C "$ETPL_REPO" config user.email t@e.com; git -C "$ETPL_REPO" config user.name t
git -C "$ETPL_REPO" commit --allow-empty -qm base
git -C "$ETPL_REPO" branch -M main
git -C "$ETPL_REPO" checkout -q -b feat
git -C "$ETPL_REPO" commit --allow-empty -qm "feat: no fix commits here"
mkdir -p "$ETPL_REPO/.prflow/tmp/review/pr-5/run-l"
( cd "$ETPL_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPL_REPO/.prflow/tmp/review/pr-5/run-l" --slug pr-5 ) >/dev/null 2>&1
assert_eq "et-prov(#534): LOST — a dropped emit with nothing to recover leaves no iter record" "no" \
  "$([ -e "$ETPL_REPO/.prflow/tmp/review/pr-5/run-l/iter-1.json" ] && echo yes || echo no)"
rm -rf "$ETPL_REPO"

# MALFORMED / NON-OBJECT (best-effort adversarial matrix): the backfill's guard
# fails CLOSED — a valid object record is stamped while a malformed (invalid JSON)
# and a non-object (array) record are each left byte-identical, and --persist still
# exits 0. A regression that made the jq -e type-guard stamp a non-object, or that
# aborted --persist on a parse failure, would ship green without this.
ETPM_REPO="$(git_sandbox "et-prov malformed repo")"
git -C "$ETPM_REPO" init -q
git -C "$ETPM_REPO" config user.email t@e.com; git -C "$ETPM_REPO" config user.name t
git -C "$ETPM_REPO" commit --allow-empty -qm base
git -C "$ETPM_REPO" branch -M main
git -C "$ETPM_REPO" checkout -q -b feat
mkdir -p "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m"
printf '{"iter":1,"loop_role":"fix"}' > "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-1.json"   # valid object, no key
printf 'not json at all' > "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-2.json"                 # malformed
printf '[1,2,3]' > "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-3.json"                          # valid JSON, non-object
ETPM_H2="$(git -C "$ETPM_REPO" hash-object "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-2.json")"
ETPM_H3="$(git -C "$ETPM_REPO" hash-object "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-3.json")"
( cd "$ETPM_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m" --slug pr-6 ) >/dev/null 2>&1; ETPM_RC=$?
assert_eq "et-prov(#534): MALFORMED — --persist still exits 0" "0" "$ETPM_RC"
assert_eq "et-prov(#534): MALFORMED — the valid object is backfilled synthesized:false" "false" \
  "$(_et_show "$ETPM_REPO" ".prflow/logs/review/pr-6/run-m/iter-1.json" | jq -r '.synthesized' 2>/dev/null)"
assert_eq "et-prov(#534): MALFORMED — the invalid-JSON record is left byte-identical" "$ETPM_H2" \
  "$(git -C "$ETPM_REPO" hash-object "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-2.json")"
assert_eq "et-prov(#534): NON-OBJECT — the array record is left byte-identical" "$ETPM_H3" \
  "$(git -C "$ETPM_REPO" hash-object "$ETPM_REPO/.prflow/tmp/review/pr-6/run-m/iter-3.json")"
rm -rf "$ETPM_REPO"

# WRITE FAILURE: the backfill's `if ! { jq … 2>&1 > "$tmp" && mv … }` else arm is a
# distinct branch guarding a documented best-effort promise (breadcrumb + the durable
# record left intact + --persist never aborting). Drive it with a DEVFLOW_JQ stub that
# passes every OTHER jq call through to the real binary and fails ONLY the backfill
# program, so the stub's own error text attributes the breadcrumb to this arm and no
# other. The staged durable copy still reaches the branch, so the persisted record is
# the one a later reader consults — it must be the unbackfilled original, not a
# half-written file.
ETPW_REPO="$(git_sandbox "et-prov write-fail repo")"
git -C "$ETPW_REPO" init -q
git -C "$ETPW_REPO" config user.email t@e.com; git -C "$ETPW_REPO" config user.name t
git -C "$ETPW_REPO" commit --allow-empty -qm base
git -C "$ETPW_REPO" branch -M main
git -C "$ETPW_REPO" checkout -q -b feat
mkdir -p "$ETPW_REPO/.prflow/tmp/review/pr-7/run-w"
printf '{"iter":1,"fix_commit_sha":"cafef00d","loop_role":"fix"}' > "$ETPW_REPO/.prflow/tmp/review/pr-7/run-w/iter-1.json"
ETPW_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in *".synthesized = false"*) printf "stub jq: synthetic backfill write failure\\n" >&2; exit 3 ;; esac; done\nexec jq "$@"\n' > "$ETPW_BIN/jq-stub"
chmod +x "$ETPW_BIN/jq-stub"
ETPW_ERR="$( ( cd "$ETPW_REPO" && DEVFLOW_JQ="$ETPW_BIN/jq-stub" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETPW_REPO/.prflow/tmp/review/pr-7/run-w" --slug pr-7 ) 2>&1 >/dev/null )"; ETPW_RC=$?
assert_eq "et-prov(#534): WRITE-FAIL — a failed backfill write still exits 0 (best-effort, never aborts --persist)" "0" "$ETPW_RC"
assert_eq "et-prov(#534): WRITE-FAIL — the failure breadcrumbs jq's OWN error text (never a silent drop)" "yes" \
  "$(printf '%s' "$ETPW_ERR" | grep -qF "could not backfill emitted provenance (synthesized:false) into 'iter-1.json' (stub jq: synthetic backfill write failure)" && echo yes || echo no)"
assert_eq "et-prov(#534): WRITE-FAIL — the durable record is left intact (no synthesized key, never half-written)" "null" \
  "$(_et_show "$ETPW_REPO" ".prflow/logs/review/pr-7/run-w/iter-1.json" | jq -r '.synthesized' 2>/dev/null)"
assert_eq "et-prov(#534): WRITE-FAIL — the durable record's other fields survive the failed backfill" "cafef00d" \
  "$(_et_show "$ETPW_REPO" ".prflow/logs/review/pr-7/run-w/iter-1.json" | jq -r '.fix_commit_sha' 2>/dev/null)"
rm -rf "$ETPW_REPO" "$ETPW_BIN"

# T4 → AC4: adversarial subject shapes each exit-0 + a specific breadcrumb; only
# the one well-formed unique iteration is reconstructed.
ETSA_REPO="$(git_sandbox "et-synth adversarial repo")"
git -C "$ETSA_REPO" init -q
git -C "$ETSA_REPO" config user.email t@e.com; git -C "$ETSA_REPO" config user.name t
git -C "$ETSA_REPO" commit --allow-empty -qm base
git -C "$ETSA_REPO" branch -M main
git -C "$ETSA_REPO" checkout -q -b feat
printf 1 > "$ETSA_REPO/a"; git -C "$ETSA_REPO" add a; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration 1)"
printf 2 > "$ETSA_REPO/b"; git -C "$ETSA_REPO" add b; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration 1)"
printf 3 > "$ETSA_REPO/c"; git -C "$ETSA_REPO" add c; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration abc)"
printf 4 > "$ETSA_REPO/d"; git -C "$ETSA_REPO" add d; git -C "$ETSA_REPO" commit -qm "fix: address review findings"
printf 5 > "$ETSA_REPO/e"; git -C "$ETSA_REPO" add e; git -C "$ETSA_REPO" commit -qm "feat: unrelated"
printf 6 > "$ETSA_REPO/f"; git -C "$ETSA_REPO" add f; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration 01)"
printf 7 > "$ETSA_REPO/g"; git -C "$ETSA_REPO" add g; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration 1"
printf 8 > "$ETSA_REPO/h"; git -C "$ETSA_REPO" add h; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration1)"
printf 9 > "$ETSA_REPO/i"; git -C "$ETSA_REPO" add i; git -C "$ETSA_REPO" commit -qm "fix: address review findings (iteration 1) follow-up"
mkdir -p "$ETSA_REPO/.prflow/tmp/review/pr-9/run-a"
ETSA_ERR="$( ( cd "$ETSA_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSA_REPO/.prflow/tmp/review/pr-9/run-a" --slug pr-9 ) 2>&1 1>/dev/null )"; ETSA_RC=$?
ETSA_REC_PATH=".prflow/logs/efficiency/pr-9-run-a.json"   # read from the telemetry branch (#441)
assert_eq "et-synth(T4): adversarial run exits 0" "0" "$ETSA_RC"
assert_eq "et-synth(T4): only the one well-formed unique iteration is reconstructed" "[1]" \
  "$(_et_show "$ETSA_REPO" "$ETSA_REC_PATH" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
assert_eq "et-synth(T4): duplicate-N breadcrumb present" "yes" \
  "$(printf '%s' "$ETSA_ERR" | grep -qF 'duplicate iteration 1' && echo yes || echo no)"
assert_eq "et-synth(T4): non-numeric-N breadcrumb present" "yes" \
  "$(printf '%s' "$ETSA_ERR" | grep -qF 'non-numeric iteration token' && echo yes || echo no)"
assert_eq "et-synth(T4): no-suffix breadcrumb present" "yes" \
  "$(printf '%s' "$ETSA_ERR" | grep -qF "has no '(iteration N)' suffix" && echo yes || echo no)"
# Guard --reverse itself: "duplicate N keeps the EARLIEST" must be asserted on the
# kept SHA, not only the breadcrumb — deleting --reverse would silently flip the
# semantics to latest-wins while the count/breadcrumb assertions stayed green.
assert_eq "et-synth(T4): duplicate-N keeps the EARLIEST commit's sha (--reverse is load-bearing)" \
  "$(git -C "$ETSA_REPO" rev-list --reverse main..HEAD | head -1)" \
  "$(jq -r '.fix_commit_sha' "$ETSA_REPO/.prflow/tmp/review/pr-9/run-a/iter-1.json" 2>/dev/null)"
# Leading-zero normalization: "(iteration 01)" collides with iteration 1 in the
# dedupe (never writes iter-01.json, never reaches --argjson with a leading zero).
assert_eq "et-synth(T4): leading-zero iteration 01 collides with 1 in the dedupe (no iter-01.json)" "no" \
  "$([ -e "$ETSA_REPO/.prflow/tmp/review/pr-9/run-a/iter-01.json" ] && echo yes || echo no)"
# jq-version-independent detection: on a jq that REJECTS leading-zero --argjson, a
# removed normalization would surface as a write failure instead of a file — so
# also assert the write-failure breadcrumb for iter-01 is absent.
assert_eq "et-synth(T4): leading-zero 01 never reaches --argjson (no iter-01 write-failure breadcrumb)" "no" \
  "$(printf '%s' "$ETSA_ERR" | grep -qF 'failed to write synthesized iter-01' && echo yes || echo no)"
# The documented (iteration1) missing-space lenience: it parses as iteration 1,
# proven POSITIVELY by the duplicate-breadcrumb count — the dup "(iteration 1)",
# "(iteration 01)", "(iteration1)" and (since #1946) "(iteration 1) follow-up"
# commits each collide with iteration 1, so exactly four duplicate breadcrumbs
# fire; a mutation that kills either lenience drops the count.
assert_eq "et-synth(T4): the (iteration1) lenience parses as iteration 1 (four duplicate-iteration-1 breadcrumbs)" "4" \
  "$(printf '%s' "$ETSA_ERR" | grep -cF 'duplicate iteration 1')"
# issue #1946: trailing text after the closing ')' is parsed, not skipped — a fix
# commit's subject is authored per run and commonly carries a trailing summary, so
# an ends-with match dropped most real commits. Only the missing-')' shape is
# unparseable now, and it keeps its own breadcrumb.
assert_eq "et-synth(T4): the missing-')' shape alone is breadcrumbed as unparseable" "1" \
  "$(printf '%s' "$ETSA_ERR" | grep -cF "clause has no closing ')'")"
rm -rf "$ETSA_REPO"

# T4 zero-match: workpad-less dir + NO fix commits → no record, "was not captured"
# semantics preserved.
ETSZ_REPO="$(git_sandbox "et-synth zero-match repo")"
git -C "$ETSZ_REPO" init -q
git -C "$ETSZ_REPO" config user.email t@e.com; git -C "$ETSZ_REPO" config user.name t
git -C "$ETSZ_REPO" commit --allow-empty -qm base
git -C "$ETSZ_REPO" branch -M main
git -C "$ETSZ_REPO" checkout -q -b feat
git -C "$ETSZ_REPO" commit --allow-empty -qm "feat: no fix commits here"
mkdir -p "$ETSZ_REPO/.prflow/tmp/review/pr-0/run-z"
ETSZ_ERR="$( ( cd "$ETSZ_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSZ_REPO/.prflow/tmp/review/pr-0/run-z" --slug pr-0 ) 2>&1 1>/dev/null )"; ETSZ_RC=$?
assert_eq "et-synth(T4): zero-match exits 0" "0" "$ETSZ_RC"
assert_eq "et-synth(T4): zero-match writes no record" "no" \
  "$(_et_on_branch "$ETSZ_REPO" ".prflow/logs/efficiency/pr-0-run-z.json")"
assert_eq "et-synth(T4): zero-match preserves 'was not captured' semantics" "yes" \
  "$(printf '%s' "$ETSZ_ERR" | grep -qF 'was not captured this run' && echo yes || echo no)"
rm -rf "$ETSZ_REPO"

# T3 → AC3: discovery finds a workpad-less run dir (holding a non-iter artifact),
# and with two workpad-less dirs for one slug, only the lexicographically-latest
# run-id synthesizes; the other gets a skip breadcrumb.
ETSM_REPO="$(git_sandbox "et-synth multi-run repo")"
git -C "$ETSM_REPO" init -q
git -C "$ETSM_REPO" config user.email t@e.com; git -C "$ETSM_REPO" config user.name t
git -C "$ETSM_REPO" commit --allow-empty -qm base
git -C "$ETSM_REPO" branch -M main
git -C "$ETSM_REPO" checkout -q -b feat
printf a > "$ETSM_REPO/a"; git -C "$ETSM_REPO" add a; git -C "$ETSM_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSM_REPO/.prflow/tmp/review/pr-2/run-aaa" "$ETSM_REPO/.prflow/tmp/review/pr-2/run-bbb"
# A run-artifact (deferrals.json) but NO iter-*.json — AC3's "holds run artifacts, zero iter".
printf '{"deferrals":[]}' > "$ETSM_REPO/.prflow/tmp/review/pr-2/run-bbb/deferrals.json"
ETSM_ERR="$( ( cd "$ETSM_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETSM_RC=$?
assert_eq "et-synth(T3): discovery --persist exits 0" "0" "$ETSM_RC"
assert_eq "et-synth(T3): lexicographically-latest run-id synthesizes (on the branch)" "yes" \
  "$(_et_on_branch "$ETSM_REPO" ".prflow/logs/efficiency/pr-2-run-bbb.json")"
assert_eq "et-synth(T3): earlier run-id does NOT double-count the fix commits" "no" \
  "$(_et_on_branch "$ETSM_REPO" ".prflow/logs/efficiency/pr-2-run-aaa.json")"
assert_eq "et-synth(T3): skipped earlier run-id is named in the SAME breadcrumb line" "yes" \
  "$(printf '%s' "$ETSM_ERR" | grep -q 'run-aaa.*not the synthesis target' && echo yes || echo no)"
rm -rf "$ETSM_REPO"

# T5 → AC5: --self-check's no-workpad warning names the synthesis floor and no
# longer says "there is nothing to persist".
ETSC2_REPO="$(git_sandbox "et-synth selfcheck-wording repo")"
git -C "$ETSC2_REPO" init -q
mkdir -p "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-none"
ETSC2_OUT="$( ( cd "$ETSC2_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-none" --slug pr-4 ) 2>&1 )"
assert_eq "et-synth(T5): self-check no-workpad warning names the synthesis floor" "yes" \
  "$(printf '%s' "$ETSC2_OUT" | grep -qF 'synthesizes an iteration record' && echo yes || echo no)"
assert_eq "et-synth(T5): self-check warning no longer says 'there is nothing to persist'" "no" \
  "$(printf '%s' "$ETSC2_OUT" | grep -qF 'there is nothing to persist' && echo yes || echo no)"
# The synthesized-class self-check exemption: a synthesized iter emits NO
# missing-field warnings (it legitimately lacks most ITER_EXPECTED_FIELDS).
mkdir -p "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-synth"
printf '{"iter":1,"fix_commit_sha":"abc","fix_files":["f"],"loop_role":"fix","synthesized":true,"sweep_defs_read":{"status":"unrecoverable","reason":"r"},"sweep_evidence":{"status":"unrecoverable","reason":"r"},"reference_reads":{"fix_delta":{"status":"unrecoverable","reason":"r"}}}' \
  > "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-synth/iter-1.json"
ETSC2_OUT2="$( ( cd "$ETSC2_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-synth" --slug pr-4 ) 2>&1 )"
assert_eq "et-synth(T5): synthesized record emits no missing-field warning" "no" \
  "$(printf '%s' "$ETSC2_OUT2" | grep -qF 'is missing expected field' && echo yes || echo no)"
# The synthesized-class exemption validates against the MINIMAL synthesized set,
# never against nothing: a truncated/hand-edited synthesized record (here missing
# fix_commit_sha/fix_files/loop_role) must still warn — the writer-controlled
# `synthesized: true` flag must not buy a total validation exemption.
mkdir -p "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-trunc"
printf '{"iter":1,"synthesized":true}' \
  > "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-trunc/iter-1.json"
ETSC2_OUT3="$( ( cd "$ETSC2_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETSC2_REPO/.prflow/tmp/review/pr-4/run-trunc" --slug pr-4 ) 2>&1 )"
assert_eq "et-synth(T5): a TRUNCATED synthesized record still warns on its minimal field set" "yes" \
  "$(printf '%s' "$ETSC2_OUT3" | grep -qF "is missing expected field 'fix_commit_sha'" && echo yes || echo no)"
rm -rf "$ETSC2_REPO"

# ── issue #532: base-ref freshness before the synthesis floor selects commits ──
# --persist refreshes origin/<base> into the remote-tracking cache BEFORE synthesis
# selects any commit. The observable is (a) whether a synthesized iter-*.json exists
# and its sha, and (b) the distinct persist_one/synthesize breadcrumb — NEVER the
# exit code (--persist is always exit-0/best-effort, so $? cannot discriminate the
# decline arm from found-none or success). Each fixture's `origin` is a LOCAL bare
# repo or path; no network is required.
echo "efficiency-trace.sh base-ref freshness (issue #532)"

# et-fresh(R1) — stale refs/remotes/origin/<base> + reachable origin → the
# pre-synthesis refresh advances the base ref and the FOREIGN merged fix commit
# falls out of range, so the record carries the feature branch's OWN commit, not
# the foreign one. Reproduces the defect: with the refresh removed, refs/remotes/
# origin/main stays behind the foreign commit and it is attributed to this run.
ETF1_ORIGIN="$(git_sandbox "et-fresh R1 origin")"; git -C "$ETF1_ORIGIN" init --bare -q
ETF1_REPO="$(git_sandbox "et-fresh R1 repo")"
git -C "$ETF1_REPO" init -q
git -C "$ETF1_REPO" config user.email t@e.com; git -C "$ETF1_REPO" config user.name t
git -C "$ETF1_REPO" commit --allow-empty -qm base
git -C "$ETF1_REPO" branch -M main
git -C "$ETF1_REPO" remote add origin "$ETF1_ORIGIN"
git -C "$ETF1_REPO" push -q origin main                      # origin/main = B; refs/remotes/origin/main = B
ETF1_B="$(git -C "$ETF1_REPO" rev-parse HEAD)"
printf x > "$ETF1_REPO/foreign"; git -C "$ETF1_REPO" add foreign
git -C "$ETF1_REPO" commit -qm "fix: address review findings (iteration 1)"   # FOREIGN
ETF1_F="$(git -C "$ETF1_REPO" rev-parse HEAD)"
git -C "$ETF1_REPO" push -q origin main                      # origin (bare) main = F
git -C "$ETF1_REPO" update-ref refs/remotes/origin/main "$ETF1_B"   # make the remote-tracking cache STALE (at B)
git -C "$ETF1_REPO" checkout -q -b feat
# The foreign fix commit F was committed while HEAD was on `main`, so local refs/heads/main
# is now at F. Reset it back to B so the LOCAL base branch is STRICTLY BEHIND origin's tip
# (F) — this is what makes the R8 assertion below non-vacuous (see its comment).
git -C "$ETF1_REPO" branch -f main "$ETF1_B"
printf y > "$ETF1_REPO/own"; git -C "$ETF1_REPO" add own
git -C "$ETF1_REPO" commit -qm "fix: address review findings (iteration 2)"   # the feature's OWN commit
ETF1_OWN="$(git -C "$ETF1_REPO" rev-parse HEAD)"
# R8 rides HERE (not R5): R5's fixture has local main == origin/main, so an
# implementation that wrongly fast-forwarded the LOCAL ref would produce the identical
# value and the assertion would pass vacuously. R1's fixture (after the `branch -f main
# $ETF1_B` reset above) has the local base branch at B while origin's tip is F — origin
# strictly AHEAD of the local ref — so asserting the LOCAL ref stayed at B (≠ F) while the
# REMOTE-TRACKING ref advanced B→F genuinely exercises "the refresh advances the
# remote-tracking cache only, never a local branch ref" (AC11): a buggy fast-forward of the
# local ref would move it to F and the B≠F assertion would catch it.
ETF1_LOCAL_MAIN_BEFORE="$(git -C "$ETF1_REPO" rev-parse refs/heads/main)"
ETF1_WPD="$ETF1_REPO/.prflow/tmp/review/pr-777/run-z"; mkdir -p "$ETF1_WPD"
( cd "$ETF1_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF1_WPD" --slug pr-777 ) >/dev/null 2>&1; ETF1_RC=$?
assert_eq "et-fresh(R1): --persist exits 0" "0" "$ETF1_RC"
assert_eq "et-fresh(R1): the FOREIGN merged fix commit is NOT attributed to this run (refresh advanced the base ref)" "no" \
  "$(grep -qF "$ETF1_F" "$ETF1_WPD"/iter-*.json 2>/dev/null && echo yes || echo no)"
assert_eq "et-fresh(R1): the surviving synthesized record carries the feature's OWN commit" "$ETF1_OWN" \
  "$(jq -r '.fix_commit_sha' "$ETF1_WPD/iter-2.json" 2>/dev/null)"
assert_eq "et-fresh(R8/R1): the refresh advanced the remote-tracking ref to origin's tip (F)" "$ETF1_F" \
  "$(git -C "$ETF1_REPO" rev-parse refs/remotes/origin/main 2>/dev/null)"
assert_eq "et-fresh(R8/R1): the LOCAL base branch ref stayed at B (no local ref advanced) with origin AHEAD — non-vacuous" \
  "$ETF1_LOCAL_MAIN_BEFORE" "$(git -C "$ETF1_REPO" rev-parse refs/heads/main)"
rm -rf "$ETF1_ORIGIN" "$ETF1_REPO"

# et-fresh(R2) — origin configured but UNREACHABLE → the base ref is UNESTABLISHED,
# so synthesis declines: no iter-*.json is written and the unestablished-base
# breadcrumb fires; --persist still exits 0. (Guarantee-class path: the mechanism
# must hold precisely where the environment did not cooperate.)
ETF2_REPO="$(git_sandbox "et-fresh R2 repo")"
git -C "$ETF2_REPO" init -q
git -C "$ETF2_REPO" config user.email t@e.com; git -C "$ETF2_REPO" config user.name t
git -C "$ETF2_REPO" commit --allow-empty -qm base; git -C "$ETF2_REPO" branch -M main
git -C "$ETF2_REPO" remote add origin /nonexistent/devflow/base-origin.git
git -C "$ETF2_REPO" checkout -q -b feat
printf a > "$ETF2_REPO/a"; git -C "$ETF2_REPO" add a
git -C "$ETF2_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF2_WPD="$ETF2_REPO/.prflow/tmp/review/pr-2/run-u"; mkdir -p "$ETF2_WPD"
ETF2_ERR="$( ( cd "$ETF2_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF2_WPD" --slug pr-2 ) 2>&1 1>/dev/null )"; ETF2_RC=$?
assert_eq "et-fresh(R2): unreachable origin still exits 0" "0" "$ETF2_RC"
assert_eq "et-fresh(R2): unestablished base declines — NO iter-*.json written" "no" \
  "$([ -e "$ETF2_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R2): the unestablished-base breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF2_ERR" | grep -qF 'base ref is UNESTABLISHED' && echo yes || echo no)"
rm -rf "$ETF2_REPO"

# et-fresh(R2b, issue #916) — base ESTABLISHED but the telemetry-branch fetch is
# UNESTABLISHED (_DEVFLOW_TELEMETRY_FETCH_STATUS=failed) → synthesis declines,
# mirroring the base-ref guard. The fixture makes the two statuses diverge: origin
# is reachable and main is pushed (base refresh succeeds → established), while a
# same-named `prflow-telemetry` branch exists on origin holding a NON-.prflow/logs/
# path, so do_persist fetches it, devflow_telemetry_verify_store FAILS, and the
# fetch status is set to `failed`. Before #916 this synthesized (base established +
# a matching fix commit + an empty exclusion set from the un-advanced local ref) and
# could re-attribute an already-recorded commit; now it declines: no iter-*.json, and
# the telemetry-fetch decline breadcrumb fires — textually distinct from the
# base-ref-unestablished one (which must NOT fire, proving it is the telemetry guard,
# not the base guard, that declined). --persist still exits 0.
ETF2B_ORIGIN="$(git_sandbox "et-fresh R2b origin")"; git -C "$ETF2B_ORIGIN" init --bare -q
ETF2B_REPO="$(git_sandbox "et-fresh R2b repo")"
git -C "$ETF2B_REPO" init -q
git -C "$ETF2B_REPO" config user.email t@e.com; git -C "$ETF2B_REPO" config user.name t
git -C "$ETF2B_REPO" commit --allow-empty -qm base; git -C "$ETF2B_REPO" branch -M main
git -C "$ETF2B_REPO" remote add origin "$ETF2B_ORIGIN"; git -C "$ETF2B_REPO" push -q origin main
# A same-named telemetry branch that is NOT a valid store (a top-level non-.prflow/logs
# file) → verify_store fails → _DEVFLOW_TELEMETRY_FETCH_STATUS=failed.
git -C "$ETF2B_REPO" checkout -q -b prflow-telemetry
printf x > "$ETF2B_REPO/not-a-store"; git -C "$ETF2B_REPO" add not-a-store
git -C "$ETF2B_REPO" commit -qm "not a telemetry store"
git -C "$ETF2B_REPO" push -q origin prflow-telemetry
git -C "$ETF2B_REPO" checkout -q main
git -C "$ETF2B_REPO" checkout -q -b feat
printf a > "$ETF2B_REPO/a"; git -C "$ETF2B_REPO" add a
git -C "$ETF2B_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF2B_WPD="$ETF2B_REPO/.prflow/tmp/review/pr-2b/run-t"; mkdir -p "$ETF2B_WPD"
ETF2B_ERR="$( ( cd "$ETF2B_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF2B_WPD" --slug pr-2b ) 2>&1 1>/dev/null )"; ETF2B_RC=$?
assert_eq "et-fresh(R2b): base-established+telemetry-failed still exits 0" "0" "$ETF2B_RC"
assert_eq "et-fresh(R2b): failed telemetry fetch declines — NO iter-*.json written" "no" \
  "$([ -e "$ETF2B_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R2b): the telemetry-fetch decline breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF2B_ERR" | grep -qF 'telemetry-branch fetch is UNESTABLISHED' && echo yes || echo no)"
assert_eq "et-fresh(R2b): the base-ref-unestablished breadcrumb does NOT fire (proves the telemetry guard declined, not the base guard)" "no" \
  "$(printf '%s' "$ETF2B_ERR" | grep -qF 'base ref is UNESTABLISHED' && echo yes || echo no)"
rm -rf "$ETF2B_ORIGIN" "$ETF2B_REPO"

# et-fresh(R3) — NO origin remote at all → synthesis PROCEEDS and writes its record;
# exit 0. Pins the arm that keeps every no-origin et-synth fixture green (a revert to
# a decline-on-missing-origin spec turns this RED).
ETF3_REPO="$(git_sandbox "et-fresh R3 repo")"
git -C "$ETF3_REPO" init -q
git -C "$ETF3_REPO" config user.email t@e.com; git -C "$ETF3_REPO" config user.name t
git -C "$ETF3_REPO" commit --allow-empty -qm base; git -C "$ETF3_REPO" branch -M main
git -C "$ETF3_REPO" checkout -q -b feat
printf a > "$ETF3_REPO/a"; git -C "$ETF3_REPO" add a
git -C "$ETF3_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF3_OWN="$(git -C "$ETF3_REPO" rev-parse HEAD)"
ETF3_WPD="$ETF3_REPO/.prflow/tmp/review/pr-3/run-n"; mkdir -p "$ETF3_WPD"
ETF3_ERR="$( ( cd "$ETF3_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF3_WPD" --slug pr-3 ) 2>&1 1>/dev/null )"; ETF3_RC=$?
assert_eq "et-fresh(R3): no-origin exits 0" "0" "$ETF3_RC"
assert_eq "et-fresh(R3): no-origin PROCEEDS and writes its record" "$ETF3_OWN" \
  "$(jq -r '.fix_commit_sha' "$ETF3_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(R3): no-origin breadcrumb records the base was accepted without a refresh" "yes" \
  "$(printf '%s' "$ETF3_ERR" | grep -qF 'no origin remote configured; accepted the local base' && echo yes || echo no)"
rm -rf "$ETF3_REPO"

# et-fresh(R4) — established base (reachable, fresh) but NO matching fix commit →
# no iter-*.json and the FOUND-NONE breadcrumb, which must be textually distinct
# from R2's unestablished-base breadcrumb (both write no file and both exit 0, so
# the breadcrumb is the only discriminator).
ETF4_ORIGIN="$(git_sandbox "et-fresh R4 origin")"; git -C "$ETF4_ORIGIN" init --bare -q
ETF4_REPO="$(git_sandbox "et-fresh R4 repo")"
git -C "$ETF4_REPO" init -q
git -C "$ETF4_REPO" config user.email t@e.com; git -C "$ETF4_REPO" config user.name t
git -C "$ETF4_REPO" commit --allow-empty -qm base; git -C "$ETF4_REPO" branch -M main
git -C "$ETF4_REPO" remote add origin "$ETF4_ORIGIN"; git -C "$ETF4_REPO" push -q origin main
git -C "$ETF4_REPO" checkout -q -b feat
git -C "$ETF4_REPO" commit --allow-empty -qm "feat: no fix commits here"
ETF4_WPD="$ETF4_REPO/.prflow/tmp/review/pr-4/run-f"; mkdir -p "$ETF4_WPD"
ETF4_ERR="$( ( cd "$ETF4_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF4_WPD" --slug pr-4 ) 2>&1 1>/dev/null )"; ETF4_RC=$?
assert_eq "et-fresh(R4): established+no-match exits 0" "0" "$ETF4_RC"
assert_eq "et-fresh(R4): established+no-match writes no iter-*.json" "no" \
  "$([ -e "$ETF4_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R4): found-none breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF4_ERR" | grep -qF 'no unrecorded' && echo yes || echo no)"
assert_eq "et-fresh(R4): found-none is textually DISTINCT from the unestablished-base breadcrumb" "no" \
  "$(printf '%s' "$ETF4_ERR" | grep -qF 'base ref is UNESTABLISHED' && echo yes || echo no)"
rm -rf "$ETF4_ORIGIN" "$ETF4_REPO"

# et-fresh(R5) — established base + a matching fix commit → the record is written
# with the correct sha AND every ITER_SYNTH_EXPECTED_FIELDS member present.
# et-fresh(R8) rides the same fixture: the LOCAL base branch ref is byte-identical
# before/after (the refresh advances only the remote-tracking cache).
ETF5_ORIGIN="$(git_sandbox "et-fresh R5 origin")"; git -C "$ETF5_ORIGIN" init --bare -q
ETF5_REPO="$(git_sandbox "et-fresh R5 repo")"
git -C "$ETF5_REPO" init -q
git -C "$ETF5_REPO" config user.email t@e.com; git -C "$ETF5_REPO" config user.name t
git -C "$ETF5_REPO" commit --allow-empty -qm base; git -C "$ETF5_REPO" branch -M main
git -C "$ETF5_REPO" remote add origin "$ETF5_ORIGIN"; git -C "$ETF5_REPO" push -q origin main
git -C "$ETF5_REPO" checkout -q -b feat
printf a > "$ETF5_REPO/a"; git -C "$ETF5_REPO" add a
git -C "$ETF5_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF5_OWN="$(git -C "$ETF5_REPO" rev-parse HEAD)"
ETF5_LOCAL_MAIN_BEFORE="$(git -C "$ETF5_REPO" rev-parse refs/heads/main)"
ETF5_WPD="$ETF5_REPO/.prflow/tmp/review/pr-5/run-r"; mkdir -p "$ETF5_WPD"
( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF5_WPD" --slug pr-5 ) >/dev/null 2>&1; ETF5_RC=$?
assert_eq "et-fresh(R5): established+match exits 0" "0" "$ETF5_RC"
assert_eq "et-fresh(R5): the record carries the correct fix_commit_sha" "$ETF5_OWN" \
  "$(jq -r '.fix_commit_sha' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
# The expected set is DERIVED from the single source of truth rather than hard-coded:
# this assertion previously claimed to check "the full ITER_SYNTH_EXPECTED_FIELDS set"
# while testing a hard-coded five keys, so a field added to the set (issue #541 added
# three) would have left the claim true-sounding and the check stale. Deriving it means
# the assertion cannot drift from what it says it checks.
ETF5_SYNTH_FIELDS="$(grep -E '^ITER_SYNTH_EXPECTED_FIELDS=' "$LIB/efficiency-trace.sh" | sed -E 's/^ITER_SYNTH_EXPECTED_FIELDS=//; s/"//g')"
# POSITIVE CONTROL, and it is load-bearing: the set-difference assertion below expects the
# EMPTY string, and an empty $ETF5_SYNTH_FIELDS also yields empty (`"" | split(" ")` is `[]`,
# and `[] - keys` is `[]`), so a broken extraction would pass having checked nothing —
# silently dropping every member from coverage. `sed` is not preflight-guaranteed and the
# grep depends on the constant staying a plain single-line assignment, so both failure modes
# are live. Assert the extraction produced a usable value BEFORE trusting its emptiness.
assert_eq "et-fresh(R5): the ITER_SYNTH_EXPECTED_FIELDS extraction itself resolved (guards the set-difference below against a vacuous empty-vs-empty pass)" "yes" \
  "$(case "$ETF5_SYNTH_FIELDS" in *synthesized*) echo yes ;; *) echo no ;; esac)"
assert_eq "et-fresh(R5): the synthesized record carries every ITER_SYNTH_EXPECTED_FIELDS member (set derived, not hard-coded)" "" \
  "$(jq -r --arg f "$ETF5_SYNTH_FIELDS" '(($f | split(" ")) - keys) | join(",")' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
# CONVERSE direction (#541 review, completeness critic). The assertion above derives its
# expectation FROM the constant, so it is blind in the deletion direction: drop a member and
# the expectation drops with it, leaving the difference empty and the test green. That is the
# self-certification a "detect-all" audit must not rest on. The independent signal here is the
# record the producer ACTUALLY synthesized — not the constant — so asserting `keys - constant`
# is also empty makes the two sets mutually pinning: a member dropped from the constant while
# the writer still stamps it now goes RED. (Scoped precisely: the three evidence fields and
# `synthesized` were already covered — by the hard-coded consumer greps and the extraction
# control respectively — so this closes the residual for `iter`/`fix_commit_sha`/`fix_files`/
# `loop_role`, which no assertion previously pinned against a constant-side deletion.)
assert_eq "et-fresh(R5): ITER_SYNTH_EXPECTED_FIELDS covers every key the synthesizer actually wrote (converse — catches a constant-side deletion)" "" \
  "$(jq -r --arg f "$ETF5_SYNTH_FIELDS" '(keys - ($f | split(" "))) | join(",")' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(R8): the LOCAL base branch ref is byte-identical after a successful refresh" \
  "$ETF5_LOCAL_MAIN_BEFORE" "$(git -C "$ETF5_REPO" rev-parse refs/heads/main)"
# et-fresh(R6) — idempotency: a second --persist writes no second record and makes
# no new telemetry-branch commit.
ETF5_BC1="$(_et_branch_count "$ETF5_REPO")"
( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF5_WPD" --slug pr-5 ) >/dev/null 2>&1; ETF5_RC2=$?
assert_eq "et-fresh(R6): second --persist exits 0" "0" "$ETF5_RC2"
assert_eq "et-fresh(R6): second --persist makes no new telemetry-branch commit (idempotent)" \
  "$ETF5_BC1" "$(_et_branch_count "$ETF5_REPO")"

# ── #541 run-scoped evidence provenance on synthesized records ────────────────
# PRODUCER side, exercised against the REAL record --persist just synthesized (not a
# hand-written fixture): a fix-commit-only record cannot establish which sweep
# definitions were read, what the sweeps found, or whether Step 3.5's fix-delta gate
# ran, so each run-scoped evidence field carries an explicit unrecoverable-provenance
# object. The two NEGATIVE assertions below state the AC's prohibition directly — `[]` and
# `{"status":"not-run"}` are the LEGITIMATE values of a real no-fix iteration, so emitting
# either here would launder unobserved evidence into a positive claim about an iteration
# this floor never saw. They are implied by the type/status assertions in the loop rather
# than independently load-bearing; they are kept as the executable statement of the AC, so
# a future loosening of the shape assertion still trips the prohibition it exists to
# enforce.
for _f541 in sweep_defs_read sweep_evidence; do
  assert_eq "et-fresh(#541): synthesized $_f541 is an object carrying status=unrecoverable" "object|unrecoverable" \
    "$(jq -r --arg k "$_f541" '[(.[$k] | type), (.[$k].status // "")] | join("|")' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
  assert_eq "et-fresh(#541): synthesized $_f541 carries a non-empty reason naming why it is unrecoverable" "yes" \
    "$(jq -r --arg k "$_f541" 'if ((.[$k].reason // "") | length) > 0 then "yes" else "no" end' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
done
# reference_reads is a REGISTRY keyed by the producing reference, so its provenance is
# asserted at the documented `.reference_reads.fix_delta` read path — not at the top level.
# Asserting the top level instead would pass on a shape whose documented read returns null,
# which is byte-identical to the legitimate "Step 3.5 did not run" absence and would defeat
# the distinction this field exists to preserve (review round 1, converged finding).
assert_eq "et-fresh(#541): synthesized reference_reads.fix_delta is an object carrying status=unrecoverable" "object|unrecoverable" \
  "$(jq -r '[(.reference_reads.fix_delta | type), (.reference_reads.fix_delta.status // "")] | join("|")' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(#541): synthesized reference_reads.fix_delta carries a non-empty reason" "yes" \
  "$(jq -r 'if ((.reference_reads.fix_delta.reason // "") | length) > 0 then "yes" else "no" end' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(#541): the documented .reference_reads.fix_delta read does NOT return null (the shape a top-level stamp would produce)" "no" \
  "$(jq -r 'if .reference_reads.fix_delta == null then "yes" else "no" end' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
# The three reason strings must stay DISTINCT (#541 review). Asserting only non-emptiness
# above would stay green against a regression that collapsed all three unrec() calls onto one
# shared $what — plausible precisely BECAUSE unrec() exists to share the framing — leaving the
# record unable to say WHICH evidence was unrecoverable. Compare the deduplicated count to 3.
assert_eq "et-fresh(#541): the three unrecoverable reason strings are pairwise DISTINCT" "3" \
  "$(jq -r '[.sweep_defs_read.reason, .sweep_evidence.reason, .reference_reads.fix_delta.reason] | unique | length' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(#541): synthesized sweep_defs_read is NOT the real no-fix value []" "no" \
  "$(jq -r 'if .sweep_defs_read == [] then "yes" else "no" end' "$ETF5_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(#541): synthesized sweep_evidence is NOT the real no-fix status not-run" "no" \
  "$(jq -r 'if (.sweep_evidence.status // "") == "not-run" then "yes" else "no" end' "$ETF5_WPD/iter-1.json" 2>/dev/null)"

# CONSUMER side: ITER_SYNTH_EXPECTED_FIELDS membership is what makes --self-check
# ENFORCE the provenance. Strip all three evidence fields from the real synthesized record
# and the self-check must name EACH one as missing — otherwise a synthesizer that silently
# stopped stamping provenance would validate clean. One strip and one --self-check run
# suffice for the per-field claim: the validator computes `missing` as a jq set difference
# and emits one warning line per name with no short-circuit, so a field dropped from the set
# still cannot hide behind the other two (each name gets its own assertion below).
jq 'del(.sweep_defs_read, .sweep_evidence, .reference_reads)' "$ETF5_WPD/iter-1.json" > "$ETF5_WPD/iter-2.json" 2>/dev/null
ETF5_SC_OUT="$( ( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETF5_WPD" --slug pr-5 ) 2>&1 )"
for _f541 in sweep_defs_read sweep_evidence reference_reads; do
  assert_eq "et-fresh(#541): --self-check flags a synthesized record missing $_f541" "yes" \
    "$(printf '%s\n' "$ETF5_SC_OUT" | grep -qF "iter-2.json' is missing expected field '$_f541'" && echo yes || echo no)"
done
rm -f "$ETF5_WPD/iter-2.json"
# #541 review (Critical): the set difference above observes only KEY PRESENCE, so it is
# structurally blind to the regression this issue exists to prevent — a synthesizer that keeps
# every key but stamps `[]` / `{"status":"not-run"}`, the LEGITIMATE values of a real no-fix
# iteration. Drive that exact regression and assert the value-shape check names each field.
# The positive control is the fixture itself: it is the record --persist actually synthesized,
# mutated in the three evidence values ALONE, so a warning can only be attributed to the bad
# provenance and not to some unrelated invalidity. The final assertion pins ATTRIBUTION — the
# missing-field warning must NOT also fire, so the present-but-wrong and absent conditions stay
# separately diagnosable rather than either masking the other.
jq '.sweep_defs_read = [] | .sweep_evidence = {"status":"not-run","reason":"no fixes applied"} | .reference_reads = {"fix_delta":{"status":"verified","outcome":"clean","reason":null}}' \
  "$ETF5_WPD/iter-1.json" > "$ETF5_WPD/iter-3.json" 2>/dev/null
ETF5_BAD_OUT="$( ( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETF5_WPD" --slug pr-5 ) 2>&1 )"
for _f541v in sweep_defs_read sweep_evidence reference_reads.fix_delta; do
  assert_eq "et-fresh(#541): --self-check flags present-but-real-looking $_f541v on a synthesized record" "yes" \
    "$(printf '%s\n' "$ETF5_BAD_OUT" | grep -qF "iter-3.json' carries field '$_f541v' WITHOUT unrecoverable provenance" && echo yes || echo no)"
done
assert_eq "et-fresh(#541): the value-shape warning is NOT misreported as a missing field (attribution)" "no" \
  "$(printf '%s\n' "$ETF5_BAD_OUT" | grep -qF "iter-3.json' is missing expected field" && echo yes || echo no)"
rm -f "$ETF5_WPD/iter-3.json"
# MALFORMED-SHAPE MATRIX (#541 review round 3, shadow + fix-delta gate, corroborated 3x).
# `reference_reads` is an agent-mutable workpad field, so the shape check is a best-effort
# parser and gets this repo's adversarial input-shape sweep. The first version of the check
# indexed `.reference_reads.fix_delta` with NO type guard: on a string/array/number jq
# ABORTED (rc 5), the rc-gated `if` went false, and the sweep violations jq had ALREADY
# printed on that same run were discarded with it — one malformed value silently suppressing
# EVERY provenance warning for the record, the very fail-open the check exists to prevent.
# Each row therefore pairs the malformed value with a genuinely-regressed `sweep_defs_read`
# and asserts the sweep warning STILL fires: that is the attribution property, and it is what
# a bare "does it warn about reference_reads" assertion would miss.
# Which rows carry the ABORT rationale, stated precisely so the comment does not overclaim:
# the string / array / number / scalar-`fix_delta` rows are the ones that make the UNTYPED
# filter abort, and each was confirmed to go RED against a mutant reverting the type guard.
# The `null`, empty-object, and wrong-`status` (`{"fix_delta":{"status":"verified"}}`) rows do
# NOT abort under that mutant (jq yields `null` through the deref rather than erroring), so
# they survive it — they are here for the separate, still-real property that a
# non-`unrecoverable` value must be flagged, not as abort coverage. Reading "each row kills
# the untyped mutant" would be wrong. The empty-object row is the "Step 3.5 never ran" shape
# appearing where it is illegitimate (a synthesized record): the registry-keyed design must
# still distinguish it from unrecoverable provenance, so it is flagged like any other
# non-`unrecoverable` value rather than read as a legitimate absence.
for _f541m in '"oops"' '["oops"]' '5' 'null' '{}' '{"fix_delta":5}' '{"fix_delta":{"status":"verified"}}'; do
  printf '%s' "{\"iter\":1,\"fix_commit_sha\":\"a\",\"fix_files\":[\"f\"],\"loop_role\":\"fix\",\"synthesized\":true,\"sweep_defs_read\":{\"status\":\"not-run\"},\"sweep_evidence\":{\"status\":\"unrecoverable\",\"reason\":\"y\"},\"reference_reads\":$_f541m}" \
    > "$ETF5_WPD/iter-4.json"
  ETF5_MAL_OUT="$( ( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETF5_WPD" --slug pr-5 ) 2>&1 )"
  assert_eq "et-fresh(#541 malformed): reference_reads=$_f541m does not suppress the sweep_defs_read provenance warning (guard does not fail open)" "yes" \
    "$(printf '%s\n' "$ETF5_MAL_OUT" | grep -qF "iter-4.json' carries field 'sweep_defs_read' WITHOUT unrecoverable provenance" && echo yes || echo no)"
  # ...and the malformed value is itself flagged under its OWN field name. Without this the
  # rows would stay green under a refactor that kept the abort-safety type guard but stopped
  # the `select` emitting `reference_reads.fix_delta`, leaving a clearly-bad record unflagged.
  assert_eq "et-fresh(#541 malformed): reference_reads=$_f541m is itself flagged with reference_reads.fix_delta provenance" "yes" \
    "$(printf '%s\n' "$ETF5_MAL_OUT" | grep -qF "iter-4.json' carries field 'reference_reads.fix_delta' WITHOUT unrecoverable provenance" && echo yes || echo no)"
  rm -f "$ETF5_WPD/iter-4.json"
done
# An unrecoverable stamp with a MISSING reason is rejected too: the producer is asserted to
# write a non-empty reason, so a validator that accepted `{"status":"unrecoverable"}` alone
# would be a one-sided invariant — "unknown" without saying what is unknown, the same
# information loss this field exists to prevent, one level down.
printf '%s' '{"iter":1,"fix_commit_sha":"a","fix_files":["f"],"loop_role":"fix","synthesized":true,"sweep_defs_read":{"status":"unrecoverable"},"sweep_evidence":{"status":"unrecoverable","reason":"y"},"reference_reads":{"fix_delta":{"status":"unrecoverable","reason":"z"}}}' \
  > "$ETF5_WPD/iter-5.json"
ETF5_NOREASON_OUT="$( ( cd "$ETF5_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$ETF5_WPD" --slug pr-5 ) 2>&1 )"
assert_eq "et-fresh(#541): an unrecoverable stamp with no reason is flagged (validator matches the producer contract)" "yes" \
  "$(printf '%s\n' "$ETF5_NOREASON_OUT" | grep -qF "iter-5.json' carries field 'sweep_defs_read' WITHOUT unrecoverable provenance" && echo yes || echo no)"
rm -f "$ETF5_WPD/iter-5.json"
rm -rf "$ETF5_ORIGIN" "$ETF5_REPO"

# et-fresh(R7) — the refresh-failed decline path runs with tr/sed/wc/cut/head
# removed from PATH and STILL declines (the guard's operand is derived with bash
# builtins only — guard-class 2). Reuses R2's unreachable-origin shape.
ETF7_STUB="$(git_sandbox "et-fresh R7 path-stubs")"
for _t in tr sed wc cut head; do
  printf '#!/bin/sh\necho "%s removed for R7" >&2\nexit 127\n' "$_t" > "$ETF7_STUB/$_t"
  chmod +x "$ETF7_STUB/$_t"
done
ETF7_REPO="$(git_sandbox "et-fresh R7 repo")"
git -C "$ETF7_REPO" init -q
git -C "$ETF7_REPO" config user.email t@e.com; git -C "$ETF7_REPO" config user.name t
git -C "$ETF7_REPO" commit --allow-empty -qm base; git -C "$ETF7_REPO" branch -M main
git -C "$ETF7_REPO" remote add origin /nonexistent/devflow/base-origin.git
git -C "$ETF7_REPO" checkout -q -b feat
printf a > "$ETF7_REPO/a"; git -C "$ETF7_REPO" add a
git -C "$ETF7_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF7_WPD="$ETF7_REPO/.prflow/tmp/review/pr-7/run-x"; mkdir -p "$ETF7_WPD"
ETF7_ERR="$( ( cd "$ETF7_REPO" && PATH="$ETF7_STUB:$PATH" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF7_WPD" --slug pr-7 ) 2>&1 1>/dev/null )"; ETF7_RC=$?
assert_eq "et-fresh(R7): decline path exits 0 with tr/sed/wc/cut/head removed from PATH" "0" "$ETF7_RC"
assert_eq "et-fresh(R7): decline still fails CLOSED (no iter-*.json) with non-preflight tools absent" "no" \
  "$([ -e "$ETF7_WPD/iter-1.json" ] && echo yes || echo no)"
# Assert the DECLINE breadcrumb fired — distinguishes a genuine fail-closed decline from
# an early abort under the stripped PATH (both leave no iter-*.json), so the guard-class-2
# assertion is not satisfied vacuously by an unrelated crash.
assert_eq "et-fresh(R7): the UNESTABLISHED decline breadcrumb still fires with non-preflight tools absent (genuine decline, not an abort)" "yes" \
  "$(printf '%s' "$ETF7_ERR" | grep -qF 'base ref is UNESTABLISHED' && echo yes || echo no)"
rm -rf "$ETF7_STUB" "$ETF7_REPO"

# et-fresh(R10) — a SHALLOW fixture cloned --depth 1 via a file:// URL (a plain path
# silently ignores --depth), with a succeeding refresh → synthesis PROCEEDS. Asserts
# is-shallow-repository is true first, so the pass cannot be vacuous. Pins that a
# graft NEVER becomes a decline (a revert to a shallow-declines spec would retire the
# floor on every cloud tier → RED here).
ETF10_ORIGIN="$(git_sandbox "et-fresh R10 origin")"; git -C "$ETF10_ORIGIN" init --bare -q
ETF10_SEED="$(git_sandbox "et-fresh R10 seed")"
git -C "$ETF10_SEED" init -q
git -C "$ETF10_SEED" config user.email t@e.com; git -C "$ETF10_SEED" config user.name t
git -C "$ETF10_SEED" commit --allow-empty -qm base; git -C "$ETF10_SEED" branch -M main
git -C "$ETF10_SEED" remote add origin "$ETF10_ORIGIN"; git -C "$ETF10_SEED" push -q origin main
git -C "$ETF10_SEED" checkout -q -b feat
printf a > "$ETF10_SEED/a"; git -C "$ETF10_SEED" add a
git -C "$ETF10_SEED" commit -qm "fix: address review findings (iteration 1)"
ETF10_FIX="$(git -C "$ETF10_SEED" rev-parse HEAD)"
git -C "$ETF10_SEED" push -q origin feat
ETF10_REPO="$(git_sandbox "et-fresh R10 shallow")"; rm -rf "$ETF10_REPO"
git clone -q --depth 1 --no-single-branch "file://$ETF10_ORIGIN" "$ETF10_REPO"
git -C "$ETF10_REPO" config user.email t@e.com; git -C "$ETF10_REPO" config user.name t
git -C "$ETF10_REPO" checkout -q feat
assert_eq "et-fresh(R10): fixture is genuinely shallow (pass cannot be vacuous)" "true" \
  "$(git -C "$ETF10_REPO" rev-parse --is-shallow-repository 2>/dev/null)"
ETF10_WPD="$ETF10_REPO/.prflow/tmp/review/pr-10/run-s"; mkdir -p "$ETF10_WPD"
( cd "$ETF10_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF10_WPD" --slug pr-10 ) >/dev/null 2>&1; ETF10_RC=$?
assert_eq "et-fresh(R10): shallow clone exits 0" "0" "$ETF10_RC"
assert_eq "et-fresh(R10): a graft PROCEEDS to synthesis and writes its record" "$ETF10_FIX" \
  "$(jq -r '.fix_commit_sha' "$ETF10_WPD/iter-1.json" 2>/dev/null)"
rm -rf "$ETF10_ORIGIN" "$ETF10_SEED" "$ETF10_REPO"

# et-fresh(R11) — source-shape pin: the base branch name has exactly ONE producer.
assert_eq "et-fresh(R11): exactly one devflow_conf '.base_branch' call site in lib/efficiency-trace.sh (single producer)" "1" \
  "$(grep -c "devflow_conf '\.base_branch'" "$LIB/efficiency-trace.sh")"

# et-fresh(R12) — .base_branch is the wrong-type string "false" → the PRE-EXISTING
# unresolvable-base-ref breadcrumb, textually distinct from the new unestablished-base
# one (proves the new guard did not swallow the pre-existing arm). No origin → the
# no-origin arm marks established, then synth_base_ref cannot resolve origin/false or
# false → the pre-existing rc-3 unresolvable-base arm.
ETF12_REPO="$(git_sandbox "et-fresh R12 repo")"
git -C "$ETF12_REPO" init -q
git -C "$ETF12_REPO" config user.email t@e.com; git -C "$ETF12_REPO" config user.name t
git -C "$ETF12_REPO" commit --allow-empty -qm base; git -C "$ETF12_REPO" branch -M main
git -C "$ETF12_REPO" checkout -q -b feat
printf a > "$ETF12_REPO/a"; git -C "$ETF12_REPO" add a
git -C "$ETF12_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETF12_REPO/.prflow"; printf '{"base_branch":"false"}' > "$ETF12_REPO/.prflow/config.json"
ETF12_WPD="$ETF12_REPO/.prflow/tmp/review/pr-12/run-w"; mkdir -p "$ETF12_WPD"
ETF12_ERR="$( ( cd "$ETF12_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF12_WPD" --slug pr-12 ) 2>&1 1>/dev/null )"; ETF12_RC=$?
assert_eq "et-fresh(R12): wrong-type base exits 0" "0" "$ETF12_RC"
assert_eq "et-fresh(R12): wrong-type base writes no iter-*.json" "no" \
  "$([ -e "$ETF12_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R12): the PRE-EXISTING unresolvable-base breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF12_ERR" | grep -qF 'could not resolve a base branch ref' && echo yes || echo no)"
assert_eq "et-fresh(R12): the unresolvable-base arm is DISTINCT from the unestablished-base breadcrumb" "no" \
  "$(printf '%s' "$ETF12_ERR" | grep -qF 'base ref is UNESTABLISHED' && echo yes || echo no)"
rm -rf "$ETF12_REPO"

# et-fresh(R13) — origin reachable but the bare origin has NO base branch pushed
# (ls-remote succeeds, EMPTY) → synthesis PROCEEDS with the remote-has-no-such-branch
# breadcrumb (the fresh-adopter / deleted-base shape must not collapse into decline).
ETF13_ORIGIN="$(git_sandbox "et-fresh R13 origin")"; git -C "$ETF13_ORIGIN" init --bare -q
ETF13_REPO="$(git_sandbox "et-fresh R13 repo")"
git -C "$ETF13_REPO" init -q
git -C "$ETF13_REPO" config user.email t@e.com; git -C "$ETF13_REPO" config user.name t
git -C "$ETF13_REPO" commit --allow-empty -qm base; git -C "$ETF13_REPO" branch -M main
git -C "$ETF13_REPO" remote add origin "$ETF13_ORIGIN"     # configured, but main is NOT pushed
git -C "$ETF13_REPO" checkout -q -b feat
printf a > "$ETF13_REPO/a"; git -C "$ETF13_REPO" add a
git -C "$ETF13_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF13_OWN="$(git -C "$ETF13_REPO" rev-parse HEAD)"
ETF13_WPD="$ETF13_REPO/.prflow/tmp/review/pr-13/run-e"; mkdir -p "$ETF13_WPD"
ETF13_ERR="$( ( cd "$ETF13_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF13_WPD" --slug pr-13 ) 2>&1 1>/dev/null )"; ETF13_RC=$?
assert_eq "et-fresh(R13): empty ls-remote exits 0" "0" "$ETF13_RC"
assert_eq "et-fresh(R13): empty ls-remote PROCEEDS and writes its record" "$ETF13_OWN" \
  "$(jq -r '.fix_commit_sha' "$ETF13_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(R13): the remote-has-no-such-branch breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF13_ERR" | grep -qF 'origin carries no branch' && echo yes || echo no)"
rm -rf "$ETF13_ORIGIN" "$ETF13_REPO"

# The et-fresh(R14) and docs-fetch-scope(R9) docs/internal/efficiency-trace.md presence
# assertions that sat here stayed in lib/test/run.sh — see the retained block beside
# this module's full-suite call, and the inventory, for why.

# p3r-enum(R16) — the failed-search enumeration in phase-3-fix-loop.md names the
# unestablished-base cause.

# et-fresh(R15) — the DISTINCT fetch-fail arm: ls-remote SUCCEEDS with output (the
# branch exists on origin) but the subsequent `git fetch` FAILS → unestablished →
# decline, with the arm's own "could not refresh" breadcrumb (textually distinct
# from R2's ls-remote-query-fail "could not query origin" breadcrumb). Without this
# fixture the ls-remote-succeeds-then-fetch-fails arm — the contended-lock / partial-
# transfer residual the issue documents — is exercised by no test, and a mis-wire that
# set it `established` would proceed against a possibly-stale ref while the suite
# stayed green (the fail-open class #532 exists to close). The fetch is made to fail
# by advertising a ref whose object origin cannot deliver: a builder pushes a foreign
# `main`, its objects are then deleted from the bare origin, and this run's repo has
# its OWN main (never fetched the foreign object) — so `ls-remote --heads origin main`
# lists the ref while `git fetch +main:refs/remotes/origin/main` fails to transfer it.
ETF15_ORIGIN="$(git_sandbox "et-fresh R15 origin")"; git -C "$ETF15_ORIGIN" init --bare -q
ETF15_BLD="$(git_sandbox "et-fresh R15 builder")"
git -C "$ETF15_BLD" init -q
git -C "$ETF15_BLD" config user.email t@e.com; git -C "$ETF15_BLD" config user.name t
printf f > "$ETF15_BLD/f"; git -C "$ETF15_BLD" add f; git -C "$ETF15_BLD" commit -qm foreign
git -C "$ETF15_BLD" branch -M main; git -C "$ETF15_BLD" remote add origin "$ETF15_ORIGIN"; git -C "$ETF15_BLD" push -q origin main
find "$ETF15_ORIGIN/objects" -type f -delete   # origin advertises main but can no longer deliver its object
ETF15_REPO="$(git_sandbox "et-fresh R15 repo")"
git -C "$ETF15_REPO" init -q
git -C "$ETF15_REPO" config user.email t@e.com; git -C "$ETF15_REPO" config user.name t
printf s > "$ETF15_REPO/s"; git -C "$ETF15_REPO" add s; git -C "$ETF15_REPO" commit -qm base
git -C "$ETF15_REPO" branch -M main; git -C "$ETF15_REPO" remote add origin "$ETF15_ORIGIN"
git -C "$ETF15_REPO" checkout -q -b feat
printf a > "$ETF15_REPO/a"; git -C "$ETF15_REPO" add a
git -C "$ETF15_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF15_WPD="$ETF15_REPO/.prflow/tmp/review/pr-15/run-v"; mkdir -p "$ETF15_WPD"
ETF15_ERR="$( ( cd "$ETF15_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF15_WPD" --slug pr-15 ) 2>&1 1>/dev/null )"; ETF15_RC=$?
assert_eq "et-fresh(R15): fetch-fail arm exits 0" "0" "$ETF15_RC"
assert_eq "et-fresh(R15): fetch-fail arm declines — NO iter-*.json written" "no" \
  "$([ -e "$ETF15_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R15): the DISTINCT fetch-fail breadcrumb ('could not refresh') fires" "yes" \
  "$(printf '%s' "$ETF15_ERR" | grep -qF 'could not refresh' && echo yes || echo no)"
assert_eq "et-fresh(R15): fetch-fail arm is NOT the ls-remote-query-fail arm (distinct breadcrumb)" "no" \
  "$(printf '%s' "$ETF15_ERR" | grep -qF 'could not query origin for base' && echo yes || echo no)"
rm -rf "$ETF15_ORIGIN" "$ETF15_BLD" "$ETF15_REPO"

# et-fresh(R17) — empty ls-remote + a STALE refs/remotes/origin/<base> cache ref →
# the arm prunes that stale cache so synth_base_ref's `origin/<base>` iteration cannot
# resolve to it (which would re-widen the range and contradict the arm's "accepted the
# local base" breadcrumb). Asserts the stale ref is gone after the run, synthesis still
# proceeds, and the prune breadcrumb fires. (R13 covers the no-stale-cache case where the
# prune is a no-op.)
ETF17_ORIGIN="$(git_sandbox "et-fresh R17 origin")"; git -C "$ETF17_ORIGIN" init --bare -q
ETF17_REPO="$(git_sandbox "et-fresh R17 repo")"
git -C "$ETF17_REPO" init -q
git -C "$ETF17_REPO" config user.email t@e.com; git -C "$ETF17_REPO" config user.name t
git -C "$ETF17_REPO" commit --allow-empty -qm base; git -C "$ETF17_REPO" branch -M main
git -C "$ETF17_REPO" remote add origin "$ETF17_ORIGIN"     # origin configured, but main NOT pushed (empty ls-remote)
git -C "$ETF17_REPO" update-ref refs/remotes/origin/main "$(git -C "$ETF17_REPO" rev-parse HEAD)"   # stale cache ref
git -C "$ETF17_REPO" checkout -q -b feat
printf a > "$ETF17_REPO/a"; git -C "$ETF17_REPO" add a
git -C "$ETF17_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF17_OWN="$(git -C "$ETF17_REPO" rev-parse HEAD)"
ETF17_WPD="$ETF17_REPO/.prflow/tmp/review/pr-17/run-p"; mkdir -p "$ETF17_WPD"
ETF17_ERR="$( ( cd "$ETF17_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF17_WPD" --slug pr-17 ) 2>&1 1>/dev/null )"; ETF17_RC=$?
assert_eq "et-fresh(R17): empty-ls-remote+stale-cache exits 0" "0" "$ETF17_RC"
assert_eq "et-fresh(R17): the stale refs/remotes/origin/<base> cache ref is PRUNED" "yes" \
  "$(git -C "$ETF17_REPO" rev-parse --verify --quiet refs/remotes/origin/main >/dev/null 2>&1 && echo no || echo yes)"
assert_eq "et-fresh(R17): synthesis still PROCEEDS against the local base and writes its record" "$ETF17_OWN" \
  "$(jq -r '.fix_commit_sha' "$ETF17_WPD/iter-1.json" 2>/dev/null)"
assert_eq "et-fresh(R17): the stale-cache-prune breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF17_ERR" | grep -qF 'pruned any stale remote-tracking cache' && echo yes || echo no)"
rm -rf "$ETF17_ORIGIN" "$ETF17_REPO"

# et-fresh(R18) — empty ls-remote + a stale cache ref whose prune FAILS → the arm is
# FAIL-CLOSED: it does NOT proceed against the surviving stale cache (which synth_base_ref
# would select over the local base and re-widen the range — the exact #532 corruption a
# best-effort prune would have silently reintroduced). It declines (unestablished, no
# record) with a distinct "cache could not be pruned" breadcrumb. The prune is made to
# fail by making the loose ref's parent dir read-only, so `git update-ref -d` cannot
# unlink it.
ETF18_ORIGIN="$(git_sandbox "et-fresh R18 origin")"; git -C "$ETF18_ORIGIN" init --bare -q
ETF18_REPO="$(git_sandbox "et-fresh R18 repo")"
git -C "$ETF18_REPO" init -q
git -C "$ETF18_REPO" config user.email t@e.com; git -C "$ETF18_REPO" config user.name t
git -C "$ETF18_REPO" commit --allow-empty -qm base; git -C "$ETF18_REPO" branch -M main
git -C "$ETF18_REPO" remote add origin "$ETF18_ORIGIN"     # origin configured, main NOT pushed (empty ls-remote)
git -C "$ETF18_REPO" update-ref refs/remotes/origin/main "$(git -C "$ETF18_REPO" rev-parse HEAD)"   # stale cache ref
git -C "$ETF18_REPO" checkout -q -b feat
printf a > "$ETF18_REPO/a"; git -C "$ETF18_REPO" add a
git -C "$ETF18_REPO" commit -qm "fix: address review findings (iteration 1)"
ETF18_GD="$(git -C "$ETF18_REPO" rev-parse --absolute-git-dir)"
chmod 500 "$ETF18_GD/refs/remotes/origin"   # block `update-ref -d` from unlinking the loose ref
ETF18_WPD="$ETF18_REPO/.prflow/tmp/review/pr-18/run-pf"; mkdir -p "$ETF18_WPD"
ETF18_ERR="$( ( cd "$ETF18_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETF18_WPD" --slug pr-18 ) 2>&1 1>/dev/null )"; ETF18_RC=$?
chmod 700 "$ETF18_GD/refs/remotes/origin"   # restore before assertions / cleanup
assert_eq "et-fresh(R18): prune-fail arm exits 0" "0" "$ETF18_RC"
assert_eq "et-fresh(R18): prune-fail arm is FAIL-CLOSED — NO iter-*.json written (does not select the surviving stale cache)" "no" \
  "$([ -e "$ETF18_WPD/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-fresh(R18): the distinct 'could not be pruned' decline breadcrumb fires" "yes" \
  "$(printf '%s' "$ETF18_ERR" | grep -qF 'cache could not be pruned' && echo yes || echo no)"
rm -rf "$ETF18_ORIGIN" "$ETF18_REPO"

# T5 → AC5: the fix-commit subject literal is a coupled TWO-SITE invariant —
# skills/review-and-fix/references/fixing.md item 6 (the producer) ↔ lib/efficiency-trace.sh
# (the parser). Both sites must carry it; a targeted edit to either turns RED.
ETSY_RAF="$MAXI_BUNDLE"   # #530: root+references bundle
ETSY_ETSH="$LIB/efficiency-trace.sh"
assert_eq "et-synth(T5): fix-commit subject literal present in fixing.md item 6 (producer site)" "yes" \
  "$([ "$(devflow_module_pin_count 'fix: address review findings (iteration' "$ETSY_RAF")" -ge 1 ] && echo yes || echo no)"
assert_eq "et-synth(T5): fix-commit subject literal present in efficiency-trace.sh (parser site)" "yes" \
  "$([ "$(devflow_module_pin_count 'fix: address review findings (iteration' "$ETSY_ETSH")" -ge 1 ] && echo yes || echo no)"

# ── issue #426: --persist shadow synthesis floor (synthesize_shadow_markers) ──
# The floor recovers a dropped-but-promoted shadow block as a minimal marker
# {shadow_synthesized:true, promoted_to_iter_next:true} on iter-<N>.json when
# iter-<N+1>.json is a promoted iter. Three fixtures drive AC7's unit contract:
# (a) promotion evidence + no shadow block → marker synthesized; (b) an
# agent-written shadow block → untouched; (c) no promotion evidence → no marker.
# Plus --self-check accepts (a)'s output as a recognized degraded class.
SHF_REPO="$(git_sandbox "et-shadow-floor repo")"
git -C "$SHF_REPO" init -q
git -C "$SHF_REPO" config user.email t@e.com; git -C "$SHF_REPO" config user.name t
git -C "$SHF_REPO" commit --allow-empty -qm base
git -C "$SHF_REPO" branch -M main
git -C "$SHF_REPO" checkout -q -b feat
git -C "$SHF_REPO" commit --allow-empty -qm "feat: work"
# (a) iter-1 has NO shadow block; iter-2 is a promoted iter → floor synthesizes.
SHF_A="$SHF_REPO/.prflow/tmp/review/pr-1/run-a"
mkdir -p "$SHF_A"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_A/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted","promotion_provenance":"shadow"}' > "$SHF_A/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_A" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(a): promotion evidence + no shadow block → synthesized marker written" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_A/iter-1.json" 2>/dev/null)"
assert_eq "et-shadow-floor(a): synthesized marker carries the promotion linkage" "true" \
  "$(jq -r '.shadow.promoted_to_iter_next' "$SHF_A/iter-1.json" 2>/dev/null)"
# --self-check accepts the synthesized marker as a recognized degraded class (no
# "synthesized shadow marker missing expected field" warning on the complete one).
SHF_A_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_A" --slug pr-1 ) 2>&1 )"
assert_eq "et-shadow-floor(a): --self-check accepts the synthesized marker (no missing-field warning)" "no" \
  "$(printf '%s' "$SHF_A_SC" | grep -qF 'synthesized shadow marker missing expected field' && echo yes || echo no)"
# (a2) A Step-4.5 park-calibration promotion happened before any predecessor
# shadow ran. Provenance must suppress both synthesis and the dropped-shadow warning.
SHF_A2="$SHF_REPO/.prflow/tmp/review/pr-1/run-a2"
mkdir -p "$SHF_A2"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_A2/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted","promotion_provenance":"park-calibration-pre-shadow"}' > "$SHF_A2/iter-2.json"
SHF_A2_BEFORE="$(cat "$SHF_A2/iter-1.json")"
SHF_A2_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_A2" --slug pr-1 ) 2>&1 >/dev/null )"
assert_eq "et-shadow-floor(a2): pre-shadow park promotion leaves predecessor byte-identical" "$SHF_A2_BEFORE" \
  "$(cat "$SHF_A2/iter-1.json")"
assert_eq "et-shadow-floor(a2): pre-shadow park promotion emits no warning for predecessor" "no" \
  "$(printf '%s' "$SHF_A2_ERR" | grep -qF 'iter-1.json' && echo yes || echo no)"
# (a3) A post-shadow park promotion licenses drop recovery but never shadow credit.
SHF_A3="$SHF_REPO/.prflow/tmp/review/pr-1/run-a3"
mkdir -p "$SHF_A3"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_A3/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted","promotion_provenance":"park-calibration-post-shadow"}' > "$SHF_A3/iter-2.json"
SHF_A3_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_A3" --slug pr-1 ) 2>&1 >/dev/null )"
assert_eq "et-shadow-floor(a3): post-shadow park drop is recovered" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_A3/iter-1.json")"
assert_eq "et-shadow-floor(a3): park-driven promotion receives no shadow credit" "false" \
  "$(jq -r '.shadow.promoted_to_iter_next' "$SHF_A3/iter-1.json")"
assert_eq "et-shadow-floor(a3): exact post-shadow warning is emitted" \
  "::warning::efficiency-trace.sh --persist: synthesized a shadow marker on iter-1.json — its shadow block was dropped (iter-2.json records a park-calibration-post-shadow promotion, so a shadow ran here); promoted_to_iter_next is false because the promotion was park-gate-driven, not shadow-driven (attribution only — cost figures are unrecoverable after the fact)" \
  "$(printf '%s\n' "$SHF_A3_ERR" | grep -F 'synthesized a shadow marker on iter-1.json')"
# (a4) Unknown producer values fail closed to no synthesis and stay loud.
SHF_A4="$SHF_REPO/.prflow/tmp/review/pr-1/run-a4"
mkdir -p "$SHF_A4"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_A4/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted","promotion_provenance":"future-gate"}' > "$SHF_A4/iter-2.json"
SHF_A4_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_A4" --slug pr-1 ) 2>&1 >/dev/null )"
assert_eq "et-shadow-floor(a4): unrecognized provenance writes no marker" "null" \
  "$(jq -r '.shadow' "$SHF_A4/iter-1.json")"
assert_eq "et-shadow-floor(a4): unrecognized provenance breadcrumb names the value" "yes" \
  "$(printf '%s' "$SHF_A4_ERR" | grep -qF "unrecognized promotion_provenance value 'future-gate'" && echo yes || echo no)"
SHF_A4_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_A4" --slug pr-1 ) 2>&1 )"
assert_eq "et-shadow-floor(a4): self-check names the unrecognized producer value" "yes" \
  "$(printf '%s' "$SHF_A4_SC" | grep -qF "has unrecognized promotion_provenance 'future-gate'" && echo yes || echo no)"
# (a5) Every non-established JSON shape gets the hedged legacy marker and advisory.
for _shf_shape in absent null empty number boolean object array; do
  SHF_A5="$SHF_REPO/.prflow/tmp/review/pr-1/run-a5-$_shf_shape"
  mkdir -p "$SHF_A5"
  printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_A5/iter-1.json"
  case "$_shf_shape" in
    absent)  _shf_prov='' ;;
    null)    _shf_prov=',"promotion_provenance":null' ;;
    empty)   _shf_prov=',"promotion_provenance":""' ;;
    number)  _shf_prov=',"promotion_provenance":7' ;;
    boolean) _shf_prov=',"promotion_provenance":false' ;;
    object)  _shf_prov=',"promotion_provenance":{}' ;;
    array)   _shf_prov=',"promotion_provenance":[]' ;;
  esac
  printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"%s}' "$_shf_prov" > "$SHF_A5/iter-2.json"
  SHF_A5_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_A5" --slug pr-1 ) 2>&1 >/dev/null )"
  assert_eq "et-shadow-floor(a5 $_shf_shape): hedged marker synthesized" "true true true" \
    "$(jq -r '[.shadow.shadow_synthesized,.shadow.promoted_to_iter_next,.shadow.provenance_unestablished] | join(" ")' "$SHF_A5/iter-1.json")"
  assert_eq "et-shadow-floor(a5 $_shf_shape): hedged warning names ambiguity" "yes" \
    "$(printf '%s' "$SHF_A5_ERR" | grep -qF 'shadow block was either dropped or this promotion never ran one' && echo yes || echo no)"
  SHF_A5_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_A5" --slug pr-1 ) 2>&1 )"
  assert_eq "et-shadow-floor(a5 $_shf_shape): self-check advises on producer provenance gap" "yes" \
    "$(printf '%s' "$SHF_A5_SC" | grep -qF 'has unreadable or absent promotion_provenance' && echo yes || echo no)"
done
# Defined values are all accepted by the producer advisory.
for _shf_known in shadow park-calibration-post-shadow park-calibration-pre-shadow; do
  SHF_KNOWN="$SHF_REPO/.prflow/tmp/review/pr-1/run-known-$_shf_known"
  mkdir -p "$SHF_KNOWN"
  printf '{"iter":1,"source":"review-and-fix","loop_role":"promoted","promotion_provenance":"%s"}' "$_shf_known" > "$SHF_KNOWN/iter-1.json"
  SHF_KNOWN_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_KNOWN" --slug pr-1 ) 2>&1 )"
  assert_eq "et-shadow-floor self-check: defined $_shf_known provenance emits no provenance advisory" "no" \
    "$(printf '%s' "$SHF_KNOWN_SC" | grep -qF 'promotion_provenance' && echo yes || echo no)"
done
# A TRUNCATED synthesized shadow marker still warns — the flag buys no total exemption.
mkdir -p "$SHF_REPO/.prflow/tmp/review/pr-1/run-trunc"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix","shadow":{"shadow_synthesized":true}}' \
  > "$SHF_REPO/.prflow/tmp/review/pr-1/run-trunc/iter-1.json"
SHF_TR_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_REPO/.prflow/tmp/review/pr-1/run-trunc" --slug pr-1 ) 2>&1 )"
assert_eq "et-shadow-floor: a TRUNCATED synthesized shadow marker still warns on its minimal set" "yes" \
  "$(printf '%s' "$SHF_TR_SC" | grep -qF "synthesized shadow marker missing expected field 'promoted_to_iter_next'" && echo yes || echo no)"
# (b) an AGENT-WRITTEN shadow block (no shadow_synthesized key) is NEVER overwritten.
SHF_B="$SHF_REPO/.prflow/tmp/review/pr-1/run-b"
mkdir -p "$SHF_B"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix","shadow":{"coverage":"full","verdict":"APPROVE"}}' > "$SHF_B/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_B/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_B" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(b): an agent-written shadow block is left untouched (no shadow_synthesized key added)" "null" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_B/iter-1.json" 2>/dev/null)"
assert_eq "et-shadow-floor(b): the agent-written block's own fields survive" "full" \
  "$(jq -r '.shadow.coverage' "$SHF_B/iter-1.json" 2>/dev/null)"
# (b) the OTHER direction of the same guard: --self-check must stay SILENT on a REAL
# (agent-written) shadow block. The self-check's shadow branch gates on BOTH object-ness
# and `.shadow.shadow_synthesized == true`; a regression relaxing it to object-ness alone
# would validate every real block against SHADOW_SYNTH_EXPECTED_FIELDS and spray a
# spurious "missing expected field" warning for each of the two synth-only fields — and
# fixture (b) above, which only drives --persist, would stay green through it. (a)'s
# accept-the-marker row and the truncated-marker row are the guard's positive controls:
# together they prove this silence is the guard discriminating, not a dead branch.
SHF_B_SC="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$SHF_B" --slug pr-1 ) 2>&1 )"
assert_eq "et-shadow-floor(b): --self-check is SILENT on a real agent-written shadow block (never validated against the synth minimal set)" "no" \
  "$(printf '%s' "$SHF_B_SC" | grep -qF 'synthesized shadow marker missing expected field' && echo yes || echo no)"
# (c) no promotion evidence (iter-2 is a plain fix iter) → no marker synthesized.
SHF_C="$SHF_REPO/.prflow/tmp/review/pr-1/run-c"
mkdir -p "$SHF_C"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_C/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_C/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_C" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(c): no promotion evidence → no shadow block synthesized" "null" \
  "$(jq -r '.shadow' "$SHF_C/iter-1.json" 2>/dev/null)"
# (d) non-numeric iter filename guard (lib/efficiency-trace.sh: `case "$n" in ''|*[!0-9]*)`):
# a non-numeric stem is SKIPPED, never parsed into $((n+1)) (where bash would coerce it to 0→1
# and read an unrelated iter-1 as the "next" iter, synthesizing a bogus marker). Assert the
# floor runs cleanly and leaves iter-x.json untouched.
SHF_D="$SHF_REPO/.prflow/tmp/review/pr-1/run-d"
mkdir -p "$SHF_D"
printf '{"iter":1,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_D/iter-1.json"
printf '{"source":"review-and-fix","loop_role":"fix"}' > "$SHF_D/iter-x.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_D" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(d): a non-numeric iter filename is skipped (no bogus marker synthesized onto it)" "null" \
  "$(jq -r '.shadow' "$SHF_D/iter-x.json" 2>/dev/null)"
# (e) parse-failure fail-closed (`has_shadow=... || continue`): a malformed/unreadable iter-N.json
# with promotion evidence is SKIPPED, never clobbered — the floor exits 0 and the malformed bytes
# survive untouched (the adversarial-input-shape row CLAUDE.md requires for a parser).
SHF_E="$SHF_REPO/.prflow/tmp/review/pr-1/run-e"
mkdir -p "$SHF_E"
printf '{bad json not parseable' > "$SHF_E/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_E/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_E" --slug pr-1 ) >/dev/null 2>&1; SHF_E_RC=$?
assert_eq "et-shadow-floor(e): --persist exits 0 despite a malformed iter file (best-effort)" "0" "$SHF_E_RC"
assert_eq "et-shadow-floor(e): a malformed iter-N.json with promotion evidence is left untouched (fail-closed, not clobbered)" "{bad json not parseable" \
  "$(cat "$SHF_E/iter-1.json")"
# (e-breadcrumb): the malformed-iter skip is BREADCRUMBED, not silent — the file's
# surfacing-failures convention (and the sibling recorded_fix_shas) require it, so a
# malformed workpad that dropped a real promoted shadow leaves a signal rather than an
# unattributed silence. Capture stderr (the run above discarded it) and assert the warning.
SHF_E_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_E" --slug pr-1 ) 2>&1 >/dev/null )"
assert_eq "et-shadow-floor(e): a malformed iter with promotion evidence emits a breadcrumb (never a silent drop)" "yes" \
  "$(printf '%s' "$SHF_E_ERR" | grep -qF "could not read '.shadow' from iter-1.json" && echo yes || echo no)"
# (e2) the SUCCESSOR-iter parse-failure branch (the `if !` guard wrapping the `promoted="$(…)"`
# read, NOT an `|| continue` suffix — the wrapper is what emits the breadcrumb) — the parallel of (e)
# on the OTHER jq read. iter-1 is VALID and shadow-less (so the `.shadow` read in (e) SUCCEEDS and
# cannot be what rejects this fixture — the positive control: swap in a well-formed promoted iter-2
# and (a) proves this exact shape DOES synthesize), while iter-2 (the successor whose `.loop_role`
# supplies the promotion evidence) is malformed. Without the guard, `set -euo pipefail` makes the
# failing jq inside `promoted="$(...)"` abort the whole --persist run non-zero (breaking the
# best-effort contract); with it the iter is skipped, breadcrumbed, and left untouched. Attribute
# the rejection: pin the successor-read breadcrumb's own '.loop_role' text, which the (e) branch
# cannot emit. (The malformed iter-2 is ALSO iterated in its own turn, so stderr additionally
# carries a `.shadow`-from-iter-2 breadcrumb; the attribution below discriminates the two branches
# by FIELD NAME — rewording either breadcrumb to a shared phrase would silently un-discriminate it.)
SHF_E2="$SHF_REPO/.prflow/tmp/review/pr-1/run-e2"
mkdir -p "$SHF_E2"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_E2/iter-1.json"
printf '{bad json not parseable' > "$SHF_E2/iter-2.json"
SHF_E2_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_E2" --slug pr-1 ) 2>&1 >/dev/null )"; SHF_E2_RC=$?
assert_eq "et-shadow-floor(e2): --persist exits 0 despite a malformed SUCCESSOR iter (best-effort, not a set -e abort)" "0" "$SHF_E2_RC"
assert_eq "et-shadow-floor(e2): an unreadable successor's '.loop_role' emits its OWN breadcrumb (never a silent drop)" "yes" \
  "$(printf '%s' "$SHF_E2_ERR" | grep -qF "could not read '.loop_role' from iter-2.json" && echo yes || echo no)"
assert_eq "et-shadow-floor(e2): unconfirmable promotion evidence → no marker synthesized onto the valid iter (fail-closed)" "null" \
  "$(jq -r '.shadow' "$SHF_E2/iter-1.json" 2>/dev/null)"
# (f) idempotency / no double-count: a SECOND --persist pass over an already-synthesized run is a
# no-op — the never-overwrite guard recognizes the marker it wrote (a non-null .shadow), so the
# marker stays exactly one, unchanged.
SHF_F="$SHF_REPO/.prflow/tmp/review/pr-1/run-f"
mkdir -p "$SHF_F"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_F/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_F/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_F" --slug pr-1 ) >/dev/null 2>&1
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_F" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(f): a second --persist pass leaves the synthesized marker unchanged (idempotent, no double-count)" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_F/iter-1.json" 2>/dev/null)"
# (g) non-object .shadow fails closed (the hardened guard keys on `.shadow == null`, not on
# object-ness): a malformed present-but-non-object shadow value (a truncated partial write) is
# NOT clobbered — the "never overwrites an existing block" contract holds for a malformed block too.
SHF_G="$SHF_REPO/.prflow/tmp/review/pr-1/run-g"
mkdir -p "$SHF_G"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix","shadow":"APPROVE"}' > "$SHF_G/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_G/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_G" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(g): a non-object (malformed) .shadow is left untouched, not overwritten (fail-closed)" "APPROVE" \
  "$(jq -r '.shadow' "$SHF_G/iter-1.json" 2>/dev/null)"
# (g2) completes the present-but-not-an-object arm of the adversarial matrix CLAUDE.md requires for
# a parser. The load-bearing rows are the VALID-FALSY ones (`false` / `0` / `""`): each is PRESENT,
# so the `.shadow == null` guard correctly leaves it alone — but an `if .shadow then …` / `// `-style
# rewrite (the documented valid-falsy coercion bug) would read all three as absent and CLOBBER a real
# block. Fixture (g)'s truthy string would survive such a rewrite, so only these rows tell the two
# guards apart. The `[]` row covers the remaining non-object JSON type (truthy in jq, like (g)).
for _row in 'false:false' '0:zero' '"":emptystr' '[]:array'; do
  _fv="${_row%:*}"; _slug="${_row##*:}"
  SHF_G2="$SHF_REPO/.prflow/tmp/review/pr-1/run-g2-$_slug"
  mkdir -p "$SHF_G2"
  printf '{"iter":1,"source":"review-and-fix","loop_role":"fix","shadow":%s}' "$_fv" > "$SHF_G2/iter-1.json"
  printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_G2/iter-2.json"
  ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_G2" --slug pr-1 ) >/dev/null 2>&1
  assert_eq "et-shadow-floor(g2): a present-but-non-object .shadow ($_fv) is left untouched (never coerced to absent and clobbered)" "no" \
    "$(jq -e '.shadow.shadow_synthesized == true' "$SHF_G2/iter-1.json" >/dev/null 2>&1 && echo yes || echo no)"
done
# (g3) the OTHER side of that boundary — an EXPLICIT JSON `null` is the exact input the guard treats
# as absent, so it MUST synthesize. Without this row the `== null` predicate is only ever exercised
# via a missing key, and a tightening to `has("shadow") | not` would silently stop recovering a
# promotion whose block was written as an explicit null — the boundary of the never-overwrite
# contract, unverified. This is the positive control for the whole (g)/(g2) skip family.
SHF_G3="$SHF_REPO/.prflow/tmp/review/pr-1/run-g3"
mkdir -p "$SHF_G3"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix","shadow":null}' > "$SHF_G3/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_G3/iter-2.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_G3" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(g3): an EXPLICIT JSON null .shadow counts as absent → the marker IS synthesized (boundary of the never-overwrite contract)" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_G3/iter-1.json" 2>/dev/null)"
# (h) telemetry gate (lib/efficiency-trace.sh: `[ "$ENABLED" = "true" ] && synthesize_shadow_markers`
# in persist_one): with efficiency_telemetry_enabled=false the floor does NOT run even on genuine
# promotion evidence — a synthesized marker is a telemetry artifact, so a telemetry-disabled repo
# gets none. Without this row the ENABLED guard is untested: persist_one proceeds past that line to
# the un-gated durable copy either way (see the et-persist telemetry-off row), so dropping the
# `[ "$ENABLED" = "true" ] &&` guard would let the floor fire on a disabled repo while every
# telemetry-ON fixture (a)-(g) above still passes. This is the telemetry-off row of the
# adversarial-input matrix CLAUDE.md requires for exactly this kind of gate.
SHF_H="$SHF_REPO/.prflow/tmp/review/pr-1/run-h"
mkdir -p "$SHF_H"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_H/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_H/iter-2.json"
SHF_H_CFG="$(mktemp)"; printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$SHF_H_CFG"
( cd "$SHF_REPO" && DEVFLOW_CONFIG_FILE="$SHF_H_CFG" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_H" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(h): telemetry disabled → floor does NOT synthesize a marker despite promotion evidence" "null" \
  "$(jq -r '.shadow' "$SHF_H/iter-1.json" 2>/dev/null)"
rm -f "$SHF_H_CFG"
# (i) zero-padded numeric stem: the all-digit guard `case "$n" in ''|*[!0-9]*)` ADMITS
# `08`/`09`, which `$(( ))` would misread as invalid octal ("value too great for base").
# The base-10 `10#$n` fix computes the successor index cleanly; iter-08's successor (iter-9)
# is absent, so `[ -e "$next" ]` skips it — no crash, exit 0, the padded stem untouched.
# (Without 10#$n, `$((08 + 1))` errors — this row flips RED, proving it non-vacuous.)
SHF_I="$SHF_REPO/.prflow/tmp/review/pr-1/run-i"
mkdir -p "$SHF_I"
printf '{"iter":8,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_I/iter-08.json"
SHF_I_ERR="$( ( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_I" --slug pr-1 ) 2>&1 >/dev/null )"; SHF_I_RC=$?
assert_eq "et-shadow-floor(i): a zero-padded stem (iter-08) does not crash on octal arithmetic (exit 0)" "0" "$SHF_I_RC"
assert_eq "et-shadow-floor(i): a zero-padded stem emits no 'value too great for base' octal error" "no" \
  "$(printf '%s' "$SHF_I_ERR" | grep -qi 'value too great for base' && echo yes || echo no)"
assert_eq "et-shadow-floor(i): the padded stem is left untouched (base-10 successor iter-9 is absent → clean skip)" "null" \
  "$(jq -r '.shadow' "$SHF_I/iter-08.json" 2>/dev/null)"
# (j) MULTIPLE promotable iters in one --persist pass: the floor is a `for` loop over every
# iter-*.json, so each promotion-evidenced slot must be synthesized INDEPENDENTLY. Without a
# multi-slot row, an early `return`/`break` (or a first-match-wins rewrite) would leave every
# single-slot fixture (a)-(i) green while silently dropping every later iter's attribution.
# iter-1 (fix, shadow-less, successor iter-2 is promoted) AND iter-2 (promoted, shadow-less,
# successor iter-3 is promoted) BOTH qualify; iter-3 has no successor → correctly skipped.
SHF_J="$SHF_REPO/.prflow/tmp/review/pr-1/run-j"
mkdir -p "$SHF_J"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_J/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_J/iter-2.json"
printf '{"iter":3,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_J/iter-3.json"
( cd "$SHF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_J" --slug pr-1 ) >/dev/null 2>&1
assert_eq "et-shadow-floor(j): the FIRST promotable iter is synthesized" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_J/iter-1.json" 2>/dev/null)"
assert_eq "et-shadow-floor(j): the SECOND promotable iter is ALSO synthesized (the loop does not stop at the first match)" "true" \
  "$(jq -r '.shadow.shadow_synthesized' "$SHF_J/iter-2.json" 2>/dev/null)"
assert_eq "et-shadow-floor(j): the last iter has no successor → no promotion evidence → no marker" "null" \
  "$(jq -r '.shadow' "$SHF_J/iter-3.json" 2>/dev/null)"
# (k) jq MERGE-failure branch: the marker write is `jq '.shadow = {…}' iter > iter.shadowtmp`,
# and its failure arm must breadcrumb the jq error text, leave the source iter untouched, and
# clean up the temp file — the file's surfacing-failures thesis, previously untested. Drive it
# with a DEVFLOW_JQ stub that passes every OTHER jq call through to the real binary and fails
# ONLY the merge program (so the `.shadow`/`.loop_role` reads still succeed — the positive
# control that this fixture reaches the merge at all: the identical shape synthesizes cleanly
# in (a) with the real jq). Attribute the rejection by pinning the stub's own error text in
# the breadcrumb, which no other branch can emit.
SHF_K="$SHF_REPO/.prflow/tmp/review/pr-1/run-k"
mkdir -p "$SHF_K"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_K/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_K/iter-2.json"
SHF_K_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in *".shadow = {shadow_synthesized"*) printf "stub jq: synthetic merge failure\\n" >&2; exit 3 ;; esac; done\nexec jq "$@"\n' > "$SHF_K_BIN/jq-stub"
chmod +x "$SHF_K_BIN/jq-stub"
SHF_K_ERR="$( ( cd "$SHF_REPO" && DEVFLOW_JQ="$SHF_K_BIN/jq-stub" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_K" --slug pr-1 ) 2>&1 >/dev/null )"; SHF_K_RC=$?
assert_eq "et-shadow-floor(k): a failed jq merge still exits 0 (best-effort floor, never aborts --persist)" "0" "$SHF_K_RC"
assert_eq "et-shadow-floor(k): the failed jq merge breadcrumbs jq's OWN error text (never a silent drop)" "yes" \
  "$(printf '%s' "$SHF_K_ERR" | grep -qF 'could not synthesize a shadow marker on iter-1.json (stub jq: synthetic merge failure)' && echo yes || echo no)"
assert_eq "et-shadow-floor(k): a failed jq merge leaves the source iter untouched (no half-written marker)" "null" \
  "$(jq -r '.shadow' "$SHF_K/iter-1.json" 2>/dev/null)"
assert_eq "et-shadow-floor(k): a failed jq merge cleans up its temp file (no orphaned .shadowtmp)" "no" \
  "$([ -e "$SHF_K/iter-1.json.shadowtmp" ] && echo yes || echo no)"
rm -rf "$SHF_K_BIN"
# (l) mv-failure branch: jq writes the temp file, then the `mv` into place fails (read-only
# mount, ENOSPC). Drive it by PATH-shadowing `mv` with a failing shim that prints a real errno
# text — the only `mv` on the --persist path is this one. The breadcrumb must SURFACE that
# text (it is captured into $mv_err, symmetric with the jq branch's $jq_err — reverting to
# `mv … 2>/dev/null` discards the errno and makes a read-only mount indistinguishable from
# ENOSPC), the source iter must survive un-marked, and the temp file must be cleaned up.
SHF_L="$SHF_REPO/.prflow/tmp/review/pr-1/run-l"
mkdir -p "$SHF_L"
printf '{"iter":1,"source":"review-and-fix","loop_role":"fix"}' > "$SHF_L/iter-1.json"
printf '{"iter":2,"source":"review-and-fix","loop_role":"promoted"}' > "$SHF_L/iter-2.json"
SHF_L_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nprintf "mv: rename failed: Read-only file system\\n" >&2\nexit 1\n' > "$SHF_L_BIN/mv"
chmod +x "$SHF_L_BIN/mv"
SHF_L_ERR="$( ( cd "$SHF_REPO" && PATH="$SHF_L_BIN:$PATH" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$SHF_L" --slug pr-1 ) 2>&1 >/dev/null )"; SHF_L_RC=$?
assert_eq "et-shadow-floor(l): a failed mv still exits 0 (best-effort floor, never aborts --persist)" "0" "$SHF_L_RC"
assert_eq "et-shadow-floor(l): the failed mv breadcrumbs mv's OWN errno text (not a bare 'mv failed')" "yes" \
  "$(printf '%s' "$SHF_L_ERR" | grep -qF 'could not move the synthesized shadow marker into iter-1.json (mv failed: mv: rename failed: Read-only file system)' && echo yes || echo no)"
assert_eq "et-shadow-floor(l): a failed mv leaves the source iter un-marked (fail-closed)" "null" \
  "$(jq -r '.shadow' "$SHF_L/iter-1.json" 2>/dev/null)"
assert_eq "et-shadow-floor(l): a failed mv cleans up its temp file (no orphaned .shadowtmp)" "no" \
  "$([ -e "$SHF_L/iter-1.json.shadowtmp" ] && echo yes || echo no)"
rm -rf "$SHF_L_BIN"
# The SKILL↔lib coupled constant: SHADOW_SYNTH_EXPECTED_FIELDS must stay a plain,
# greppable single-line assignment in efficiency-trace.sh (its self-check reads it).
devflow_module_pin_unique "et-shadow-floor: efficiency-trace.sh carries the SHADOW_SYNTH_EXPECTED_FIELDS constant" \
  'SHADOW_SYNTH_EXPECTED_FIELDS="shadow_synthesized promoted_to_iter_next"' "$LIB/efficiency-trace.sh"
devflow_module_pin_unique "et-shadow-floor #501: consumer classifies shadow provenance" \
  'elif .promotion_provenance == "shadow" then "shadow"' "$LIB/efficiency-trace.sh"
devflow_module_pin_unique "et-shadow-floor #501: consumer classifies post-shadow park provenance" \
  'elif .promotion_provenance == "park-calibration-post-shadow" then "postshadow"' "$LIB/efficiency-trace.sh"
devflow_module_pin_unique "et-shadow-floor #501: producer stages shadow provenance at the early handoff" \
  'Step 0.9 short-circuits and stages `promotion_provenance: "shadow"` beside `prior_phase3_findings`' "$MAXI_SKILL"
devflow_module_pin_unique "et-shadow-floor #501: producer stages both park-gate provenance values" \
  'Stage `"park-calibration-post-shadow"` when the gate fires before Decide outcome 1' "$MAXI_SKILL"
rm -rf "$SHF_REPO"

# ── issue #426 prose pins: Phase 1 slice handoff + shadow telemetry (T1–T4) ──
# T1 → slice pipeline: statically preserve Phase 1.1's awk-from-cached-diff slice fence
# and Phase 1.2's slice-path prompt line.
devflow_module_pin_unique "#426 T1: Phase 1.1 authors the batch slice by awk-extracting ^diff --git sections from the cached diff" \
  "awk -v s=1 -v e=10 '/^diff --git/{n++} n>=s && n<=e'" "$ST_REV"  # structural-pin-ok: cross-file-phase-contract -- the literal is the review engine's own Phase 1.1 command fence, re-parsed a few lines below by this module's AWK_PROG extraction and run against a real diff, so it is a machine-consumed contract between the phase file and this driver rather than prose about one
# T2/T2b → the slice guard keys on the SECTION COUNT, never on a non-emptiness proxy: the fence
# is a `tee` pipeline whose status is grep's, and a non-emptiness test waves through a thinned
# slice, so the batch would review a surface with files silently unrepresented.
# The awk range expression is the one piece of genuinely-executable new logic in Phase 1.1,
# and a presence-only prose pin cannot catch an off-by-one in `n>=s && n<=e` (or in the
# s=(k-1)*10+1 / e=k*10 batch arithmetic). Execute the SKILL's own expression against a
# synthetic 25-section patch and assert batch k=2 yields EXACTLY sections 11..20 — boundary
# headers included, neighbours excluded. This converts reviewer-read into a regression guard.
AWKB="$(probe_tmp '#426 awk batch-slice fixture')"
: > "$AWKB.patch"
for _i in $(seq 1 25); do
  printf 'diff --git a/f%s.txt b/f%s.txt\n--- a/f%s.txt\n+++ b/f%s.txt\n+line for f%s\n' "$_i" "$_i" "$_i" "$_i" "$_i" >> "$AWKB.patch"
done
# Execute the SKILL's OWN awk program (extracted from the Phase 1.1 fence), not a copy of it:
# a hardcoded duplicate here would keep passing while the shipped expression drifted. Assert the
# extraction resolved before using it, so a fence rename can never silently degrade this into a
# vacuous run of an empty program.
AWK_PROG="$(sed -n "s/.*awk -v s=1 -v e=10 '\([^']*\)'.*/\1/p" "$ST_REV" | head -1)"
assert_eq "#426 awk slice: the Phase 1.1 awk program resolves out of the SKILL fence (fixture is not vacuous)" \
  '/^diff --git/{n++} n>=s && n<=e' "$AWK_PROG"
# Derive s/e from k with the batch formula restated just below (the SKILL-side
# s=(k-1)*10+1 / e=k*10 formula carries no pin any more, so it is no longer coupled to this
# copy — a SKILL-side change to the batch arithmetic will not turn this block RED) and sweep
# every batch of the 25-section fixture:
# batches must PARTITION the sections — each file in exactly one batch, no gaps, no overlaps.
# An off-by-one in either bound breaks the partition (a duplicated or dropped file), which the
# per-file occurrence count below catches regardless of which bound drifted.
: > "$AWKB.seen"
for _k in 1 2 3; do
  _s=$(( (_k - 1) * 10 + 1 )); _e=$(( _k * 10 ))
  awk -v s="$_s" -v e="$_e" "$AWK_PROG" "$AWKB.patch" > "$AWKB.batch$_k"
  grep '^diff --git' "$AWKB.batch$_k" >> "$AWKB.seen"
done
assert_eq "#426 awk slice: the derived batches PARTITION the diff — all 25 sections appear, none dropped" "25" \
  "$(grep -c '^diff --git' "$AWKB.seen")"
# Overlap is a DISTINCT failure mode from a drop, so compare the EMITTED total against the
# DISTINCT total — never distinct-vs-25, which a boundary double-include (26 emitted, 25 distinct)
# sails straight through. Verified: under an `s=(k-1)*10` mutation this row goes RED on 26 vs 25.
assert_eq "#426 awk slice: the derived batches PARTITION the diff — no section appears in two batches (emitted == distinct)" \
  "$(grep -c '^diff --git' "$AWKB.seen")" "$(sort -u "$AWKB.seen" | grep -c '^diff --git')"
assert_eq "#426 awk slice: the derived batch k=3 is the SHORT tail batch (sections 21..25 only)" "5" \
  "$(grep -c '^diff --git' "$AWKB.batch3")"
# The per-boundary rows below re-read batch k=2 — the middle batch the loop just derived.
assert_eq "#426 awk slice: batch k=2 yields exactly 10 diff --git sections" "10" \
  "$(grep -c '^diff --git' "$AWKB.batch2")"
assert_eq "#426 awk slice: batch k=2's FIRST section is f11 (lower boundary included, f10 excluded)" "diff --git a/f11.txt b/f11.txt" \
  "$(grep -m1 '^diff --git' "$AWKB.batch2")"
assert_eq "#426 awk slice: batch k=2's LAST section is f20 (upper boundary included, f21 excluded)" "diff --git a/f20.txt b/f20.txt" \
  "$(grep '^diff --git' "$AWKB.batch2" | tail -1)"
assert_eq "#426 awk slice: a neighbouring batch's file (f21) never leaks into batch k=2" "no" \
  "$(grep -qF 'line for f21' "$AWKB.batch2" && echo yes || echo no)"
assert_eq "#426 awk slice: each section's BODY travels with its header (f11's content is present, not just the header)" "yes" \
  "$(grep -qF 'line for f11' "$AWKB.batch2" && echo yes || echo no)"
rm -f "$AWKB.patch" "$AWKB.batch1" "$AWKB.batch2" "$AWKB.batch3" "$AWKB.seen" "$AWKB"
# ── issue #381 review fixes: sha-exclusion double-count guard + outcome honesty ──

# Mixed-sibling shape: a slug with a REAL workpad run (run-aaa, recording commit A)
# and a workpad-less sibling (run-bbb). Synthesis for run-bbb must EXCLUDE the
# already-recorded commit A and reconstruct only the unrecorded commit B — the
# double-count shape ordering alone cannot catch.
ETSX_REPO="$(git_sandbox "et-synth mixed-sibling repo")"
git -C "$ETSX_REPO" init -q
git -C "$ETSX_REPO" config user.email t@e.com; git -C "$ETSX_REPO" config user.name t
git -C "$ETSX_REPO" commit --allow-empty -qm base
git -C "$ETSX_REPO" branch -M main
git -C "$ETSX_REPO" checkout -q -b feat
printf a > "$ETSX_REPO/a"; git -C "$ETSX_REPO" add a; git -C "$ETSX_REPO" commit -qm "fix: address review findings (iteration 1)"
printf b > "$ETSX_REPO/b"; git -C "$ETSX_REPO" add b; git -C "$ETSX_REPO" commit -qm "fix: address review findings (iteration 2)"
ETSX_A="$(git -C "$ETSX_REPO" rev-list --reverse main..HEAD | head -1)"
ETSX_B="$(git -C "$ETSX_REPO" rev-list main..HEAD | head -1)"
mkdir -p "$ETSX_REPO/.prflow/tmp/review/pr-7/run-aaa" "$ETSX_REPO/.prflow/tmp/review/pr-7/run-bbb"
printf '{"iter":1,"fix_commit_sha":"%s","fix_files":["a"],"loop_role":"fix"}' "$ETSX_A" \
  > "$ETSX_REPO/.prflow/tmp/review/pr-7/run-aaa/iter-1.json"
# A corrupt sibling workpad that SORTS BEFORE the sha-bearing one: the exclusion
# scan runs in an errexit-inheriting process-substitution subshell, so an
# unguarded jq failure here would kill the scan mid-list and silently drop every
# later sha from the exclusion set (fail-open, order-dependent). The guard must
# breadcrumb + skip it and still exclude commit A.
mkdir -p "$ETSX_REPO/.prflow/tmp/review/a-corrupt/run-c"
printf '[1,2,3]' > "$ETSX_REPO/.prflow/tmp/review/a-corrupt/run-c/iter-1.json"
# A sibling workpad whose fix_commit_sha is a valid JSON string but not sha-shaped:
# must be rejected from the exclusion set with its own breadcrumb (charset guard).
mkdir -p "$ETSX_REPO/.prflow/tmp/review/zz-bad/run-b"
printf '{"iter":1,"fix_commit_sha":"NOT A SHA!","fix_files":[],"loop_role":"fix"}' \
  > "$ETSX_REPO/.prflow/tmp/review/zz-bad/run-b/iter-1.json"
ETSX_ERR="$( ( cd "$ETSX_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETSX_RC=$?
assert_eq "et-synth(mixed): discovery --persist exits 0" "0" "$ETSX_RC"
assert_eq "et-synth(mixed): sibling-recorded commit A is NOT re-synthesized into run-bbb" "no" \
  "$([ -e "$ETSX_REPO/.prflow/tmp/review/pr-7/run-bbb/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-synth(mixed): only the unrecorded commit B is synthesized (iter 2, correct sha)" "$ETSX_B" \
  "$(jq -r '.fix_commit_sha' "$ETSX_REPO/.prflow/tmp/review/pr-7/run-bbb/iter-2.json" 2>/dev/null)"
assert_eq "et-synth(mixed): the exclusion is breadcrumbed, not silent" "yes" \
  "$(printf '%s' "$ETSX_ERR" | grep -qF 'already recorded by another run' && echo yes || echo no)"
assert_eq "et-synth(mixed): a corrupt sibling workpad is breadcrumbed and skipped, never truncating the scan" "yes" \
  "$(printf '%s' "$ETSX_ERR" | grep -qF 'could not read fix_commit_sha from' && echo yes || echo no)"
assert_eq "et-synth(mixed): a non-sha-shaped fix_commit_sha is rejected from the exclusion set with a breadcrumb" "yes" \
  "$(printf '%s' "$ETSX_ERR" | grep -qF 'is not sha-shaped; not added to the exclusion set' && echo yes || echo no)"
# The strict `== true` coercion in the false direction: the REAL run's record must
# read synthesized:false at both record and per-iteration level (guards a future
# `// true`-style default drift — the #312 valid-falsy class in reverse).
assert_eq "et-synth(mixed): a real (agent-written) record reads record-level synthesized:false" "false" \
  "$(_et_show "$ETSX_REPO" ".prflow/logs/efficiency/pr-7-run-aaa.json" | jq -r '.synthesized' 2>/dev/null)"
assert_eq "et-synth(mixed): a real record reads per-iteration synthesized:false" "false" \
  "$(_et_show "$ETSX_REPO" ".prflow/logs/efficiency/pr-7-run-aaa.json" | jq -r '.per_iteration[0].synthesized' 2>/dev/null)"
rm -rf "$ETSX_REPO"

# Unresolvable base ref: no `main`, no origin, no config — the fix-commit search
# cannot run, and the breadcrumb must say exactly that (never the "no commits
# were found" collapse — the unknown-is-not-zero gotcha this file itself cites).
ETSB_REPO="$(git_sandbox "et-synth no-base repo")"
git -C "$ETSB_REPO" init -q
git -C "$ETSB_REPO" config user.email t@e.com; git -C "$ETSB_REPO" config user.name t
git -C "$ETSB_REPO" commit --allow-empty -qm base
git -C "$ETSB_REPO" branch -M trunk
mkdir -p "$ETSB_REPO/.prflow/tmp/review/pr-8/run-n"
ETSB_ERR="$( ( cd "$ETSB_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSB_REPO/.prflow/tmp/review/pr-8/run-n" --slug pr-8 ) 2>&1 1>/dev/null )"; ETSB_RC=$?
assert_eq "et-synth(no-base): exits 0" "0" "$ETSB_RC"
assert_eq "et-synth(no-base): could-not-resolve breadcrumb present" "yes" \
  "$(printf '%s' "$ETSB_ERR" | grep -qF 'could not resolve a base branch ref' && echo yes || echo no)"
assert_eq "et-synth(no-base): never-established wording present (not the found-none collapse)" "yes" \
  "$(printf '%s' "$ETSB_ERR" | grep -qF 'was never established' && echo yes || echo no)"
assert_eq "et-synth(no-base): does NOT claim commits were absent/not captured" "no" \
  "$(printf '%s' "$ETSB_ERR" | grep -qF 'was not captured this run' && echo yes || echo no)"
assert_eq "et-synth(no-base): no record written" "no" \
  "$([ -e "$ETSB_REPO/.prflow/logs/efficiency/pr-8-run-n.json" ] && echo yes || echo no)"
rm -rf "$ETSB_REPO"

# Configured non-default base: base_branch=trunk in .prflow/config.json — the
# devflow_conf read is exercised end-to-end (synthesis resolves trunk, not main).
ETSTC_REPO="$(git_sandbox "et-synth trunk-base repo")"
git -C "$ETSTC_REPO" init -q
git -C "$ETSTC_REPO" config user.email t@e.com; git -C "$ETSTC_REPO" config user.name t
git -C "$ETSTC_REPO" commit --allow-empty -qm base
git -C "$ETSTC_REPO" branch -M trunk
git -C "$ETSTC_REPO" checkout -q -b feat
printf a > "$ETSTC_REPO/a"; git -C "$ETSTC_REPO" add a; git -C "$ETSTC_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSTC_REPO/.prflow"
printf '{"base_branch":"trunk"}' > "$ETSTC_REPO/.prflow/config.json"
mkdir -p "$ETSTC_REPO/.prflow/tmp/review/pr-6/run-t"
( cd "$ETSTC_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSTC_REPO/.prflow/tmp/review/pr-6/run-t" --slug pr-6 ) >/dev/null 2>&1
assert_eq "et-synth(trunk-base): configured base_branch=trunk resolves and synthesis runs" "[1]" \
  "$(_et_show "$ETSTC_REPO" ".prflow/logs/efficiency/pr-6-run-t.json" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
rm -rf "$ETSTC_REPO"

# Multi-slug ambiguity: workpad-less dirs spanning TWO slugs in one discovery
# pass — slug ownership of the branch's fix commits is not derivable offline, so
# NEITHER synthesizes (a stale foreign slug sorting first must never claim the
# current branch's commits and lock the misattribution in via the sha exclusion).
ETSAM_REPO="$(git_sandbox "et-synth multi-slug ambiguity repo")"
git -C "$ETSAM_REPO" init -q
git -C "$ETSAM_REPO" config user.email t@e.com; git -C "$ETSAM_REPO" config user.name t
git -C "$ETSAM_REPO" commit --allow-empty -qm base
git -C "$ETSAM_REPO" branch -M main
git -C "$ETSAM_REPO" checkout -q -b feat
printf a > "$ETSAM_REPO/a"; git -C "$ETSAM_REPO" add a; git -C "$ETSAM_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSAM_REPO/.prflow/tmp/review/a-stale/run-1" "$ETSAM_REPO/.prflow/tmp/review/pr-cur/run-2"
ETSAM_ERR="$( ( cd "$ETSAM_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETSAM_RC=$?
assert_eq "et-synth(ambiguity): discovery --persist exits 0" "0" "$ETSAM_RC"
assert_eq "et-synth(ambiguity): the stale first-sorting slug does NOT claim the branch's fix commit" "no" \
  "$(_et_on_branch "$ETSAM_REPO" ".prflow/logs/efficiency/a-stale-run-1.json")"
assert_eq "et-synth(ambiguity): the second slug does not synthesize either (fail-closed, not first-wins)" "no" \
  "$(_et_on_branch "$ETSAM_REPO" ".prflow/logs/efficiency/pr-cur-run-2.json")"
assert_eq "et-synth(ambiguity): both candidates are breadcrumbed with the multi-slug reason + escape hatch" "yes" \
  "$([ "$(printf '%s' "$ETSAM_ERR" | grep -cF 'span multiple slugs')" -eq 2 ] && echo yes || echo no)"
# Drive the escape hatch the ambiguity breadcrumb names: the targeted form is
# exempt from the ambiguity guard (allow_synth=1 by caller intent) and MUST
# synthesize — this is also the exact command phase-3.3's retry block runs.
( cd "$ETSAM_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSAM_REPO/.prflow/tmp/review/pr-cur/run-2" --slug pr-cur --persist ) >/dev/null 2>&1
assert_eq "et-synth(ambiguity): the breadcrumb-named targeted retry DOES synthesize after the ambiguity skip" "[1]" \
  "$(_et_show "$ETSAM_REPO" ".prflow/logs/efficiency/pr-cur-run-2.json" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
# And a targeted --workpad-dir pointing at a NEVER-CREATED dir (the fully-degraded
# inline-loop shape the retry exists for) must mkdir it and actually WRITE into it —
# an UNRECORDED commit (iteration 2, added after run-2's synthesis) forces a real
# write attempt, so removing the mkdir guard flips this to the rc-4
# every-write-failed misdiagnosis and the missing-record assert goes RED.
printf b > "$ETSAM_REPO/b"; git -C "$ETSAM_REPO" add b; git -C "$ETSAM_REPO" commit -qm "fix: address review findings (iteration 2)"
ETSAM_B="$(git -C "$ETSAM_REPO" rev-parse HEAD)"
ETSAM_ERR2="$( ( cd "$ETSAM_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSAM_REPO/.prflow/tmp/review/pr-new/run-9" --slug pr-new --persist ) 2>&1 1>/dev/null )"
assert_eq "et-synth(ambiguity): targeted retry against a never-created dir creates it and synthesizes the unrecorded commit" "$ETSAM_B" \
  "$(jq -r '.fix_commit_sha' "$ETSAM_REPO/.prflow/tmp/review/pr-new/run-9/iter-2.json" 2>/dev/null)"
assert_eq "et-synth(ambiguity): never-created-dir retry never emits the write-failed misdiagnosis" "no" \
  "$(printf '%s' "$ETSAM_ERR2" | grep -qF 'every synthesized record write failed' && echo yes || echo no)"
assert_eq "et-synth(ambiguity): the already-recorded commit is still excluded (breadcrumbed)" "yes" \
  "$(printf '%s' "$ETSAM_ERR2" | grep -qF 'already recorded by another run' && echo yes || echo no)"
rm -rf "$ETSAM_REPO"

# The phase-3.3 backstop persists TARGETED-FIRST (this run by explicit identity —
# immune to every discovery-mode skip and to the lone-stale-foreign-dir
# misattribution) and only then runs argument-less discovery for other leftovers.
devflow_module_pin_unique "et-synth(ambiguity): phase-3.3 carries the targeted persist invocation (explicit --workpad-dir/--slug)" \
  '--workpad-dir "$ROOT/.prflow/tmp/review/<slug>/<run-id>" --slug "<slug>" --persist' \
  "$LIB/../skills/implement/phases/phase-3-fix-loop.md"
# ORDER is the load-bearing property (probe-confirmed: a presence pin alone stays
# green under a discovery-first swap, which re-opens the lone-stale-foreign-dir
# misattribution AND lets the targeted call's truncating 2> destroy discovery's
# captured breadcrumbs): assert targeted's line number precedes discovery's.
ETSP_T="$(grep -nF -- '--slug "<slug>" --persist 2>' "$LIB/../skills/implement/phases/phase-3-fix-loop.md" | cut -d: -f1 | head -1)"
ETSP_D="$(grep -nF -- '/../../lib/efficiency-trace.sh --persist 2>>' "$LIB/../skills/implement/phases/phase-3-fix-loop.md" | cut -d: -f1 | head -1)"
assert_eq "et-synth(ambiguity): the targeted persist PRECEDES the discovery persist in the phase-3.3 fence" "yes" \
  "$([ -n "$ETSP_T" ] && [ -n "$ETSP_D" ] && [ "$ETSP_T" -lt "$ETSP_D" ] && echo yes || echo no)"
assert_eq "et-synth(ambiguity): 'span multiple slugs' breadcrumb literal present at the producer site (efficiency-trace.sh)" "yes" \
  "$([ "$(devflow_module_pin_count 'span multiple slugs' "$LIB/efficiency-trace.sh")" -ge 1 ] && echo yes || echo no)"
# Guard-class 2 source-shape pin: do_persist's identity derivations (slug/run-id —
# they decide which run receives a record) must stay bash builtins; restoring a
# `$(basename …)`/`$(dirname …)` form here goes RED (a broken PATH tool would
# abort the persist mid-run, violating the best-effort exit-0 contract).
assert_eq "et-synth(guard-class-2): no invocation-position basename/dirname inside do_persist" "0" \
  "$(sed -n '/^do_persist() {/,/^}$/p' "$LIB/efficiency-trace.sh" | grep -c '\$(basename\|\$(dirname')"

# Exclusion-BEFORE-dedupe ordering: a sibling-recorded commit with subject
# (iteration 1) plus a LATER unrecorded commit also titled (iteration 1) — the
# excluded commit must not consume its iteration number, so the run's own
# commit becomes iter 1 (swapping the case blocks would breadcrumb it as a
# duplicate and synthesize nothing, while every other fixture stayed green).
ETSXO_REPO="$(git_sandbox "et-synth exclusion-order repo")"
git -C "$ETSXO_REPO" init -q
git -C "$ETSXO_REPO" config user.email t@e.com; git -C "$ETSXO_REPO" config user.name t
git -C "$ETSXO_REPO" commit --allow-empty -qm base
git -C "$ETSXO_REPO" branch -M main
git -C "$ETSXO_REPO" checkout -q -b feat
printf a > "$ETSXO_REPO/a"; git -C "$ETSXO_REPO" add a; git -C "$ETSXO_REPO" commit -qm "fix: address review findings (iteration 1)"
ETSXO_A="$(git -C "$ETSXO_REPO" rev-parse HEAD)"
printf c > "$ETSXO_REPO/c"; git -C "$ETSXO_REPO" add c; git -C "$ETSXO_REPO" commit -qm "fix: address review findings (iteration 1)"
ETSXO_C="$(git -C "$ETSXO_REPO" rev-parse HEAD)"
mkdir -p "$ETSXO_REPO/.prflow/tmp/review/pr-x/run-old" "$ETSXO_REPO/.prflow/tmp/review/pr-x/run-new"
printf '{"iter":1,"fix_commit_sha":"%s","fix_files":["a"],"loop_role":"fix"}' "$ETSXO_A" \
  > "$ETSXO_REPO/.prflow/tmp/review/pr-x/run-old/iter-1.json"
( cd "$ETSXO_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSXO_REPO/.prflow/tmp/review/pr-x/run-new" --slug pr-x --persist ) >/dev/null 2>&1
assert_eq "et-synth(order): the excluded same-N commit does not consume its iteration number" "$ETSXO_C" \
  "$(jq -r '.fix_commit_sha' "$ETSXO_REPO/.prflow/tmp/review/pr-x/run-new/iter-1.json" 2>/dev/null)"
rm -rf "$ETSXO_REPO"

# Telemetry off-switch gates synthesis: a flag-off repo must fabricate NO
# synthesized workpad, durable copy, record, or commit (pre-#381 this shape was
# a complete no-op; the flag must keep it one).
ETSG_REPO="$(git_sandbox "et-synth flag-off repo")"
git -C "$ETSG_REPO" init -q
git -C "$ETSG_REPO" config user.email t@e.com; git -C "$ETSG_REPO" config user.name t
git -C "$ETSG_REPO" commit --allow-empty -qm base
git -C "$ETSG_REPO" branch -M main
git -C "$ETSG_REPO" checkout -q -b feat
printf a > "$ETSG_REPO/a"; git -C "$ETSG_REPO" add a; git -C "$ETSG_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSG_REPO/.prflow"
printf '{"prflow_review_and_fix":{"efficiency_telemetry_enabled":false}}' > "$ETSG_REPO/.prflow/config.json"
mkdir -p "$ETSG_REPO/.prflow/tmp/review/pr-g/run-g"
ETSG_C0="$(git -C "$ETSG_REPO" rev-list --count HEAD)"
ETSG_ERR="$( ( cd "$ETSG_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSG_REPO/.prflow/tmp/review/pr-g/run-g" --slug pr-g ) 2>&1 1>/dev/null )"; ETSG_RC=$?
assert_eq "et-synth(flag-off): exits 0" "0" "$ETSG_RC"
assert_eq "et-synth(flag-off): no synthesized workpad is fabricated" "no" \
  "$([ -e "$ETSG_REPO/.prflow/tmp/review/pr-g/run-g/iter-1.json" ] && echo yes || echo no)"
assert_eq "et-synth(flag-off): no record is written" "no" \
  "$([ -e "$ETSG_REPO/.prflow/logs/efficiency/pr-g-run-g.json" ] && echo yes || echo no)"
assert_eq "et-synth(flag-off): no commit is made" "$ETSG_C0" "$(git -C "$ETSG_REPO" rev-list --count HEAD)"
assert_eq "et-synth(flag-off): the skip is breadcrumbed with the telemetry-disabled reason" "yes" \
  "$(printf '%s' "$ETSG_ERR" | grep -qF 'efficiency telemetry is disabled; skipping synthesis' && echo yes || echo no)"
rm -rf "$ETSG_REPO"

# Unsubstituted-placeholder guard: a verbatim `<slug>`/`<run-id>` invocation (the
# phase-3.3 fence run without substitution) must refuse loudly and fabricate
# NOTHING — never synthesize the branch's commits under a placeholder identity.
ETSPH_REPO="$(git_sandbox "et-synth placeholder repo")"
git -C "$ETSPH_REPO" init -q
git -C "$ETSPH_REPO" config user.email t@e.com; git -C "$ETSPH_REPO" config user.name t
git -C "$ETSPH_REPO" commit --allow-empty -qm base
git -C "$ETSPH_REPO" branch -M main
git -C "$ETSPH_REPO" checkout -q -b feat
printf a > "$ETSPH_REPO/a"; git -C "$ETSPH_REPO" add a; git -C "$ETSPH_REPO" commit -qm "fix: address review findings (iteration 1)"
ETSPH_ERR="$( ( cd "$ETSPH_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSPH_REPO/.prflow/tmp/review/<slug>/<run-id>" --slug "<slug>" --persist ) 2>&1 1>/dev/null )"; ETSPH_RC=$?
assert_eq "et-synth(placeholder): verbatim placeholder invocation exits 0 (best-effort preserved)" "0" "$ETSPH_RC"
assert_eq "et-synth(placeholder): the refusal breadcrumb names the unsubstituted placeholder" "yes" \
  "$(printf '%s' "$ETSPH_ERR" | grep -qF "unsubstituted '<placeholder>'" && echo yes || echo no)"
# _dir_nonempty DIR -> "yes"/"no": does DIR contain at least one entry (dotfiles
# included)? Builtin-only by construction — this value DECIDES an asserted result, and the
# `ls | grep` it replaces (SC2010) both mangles non-alphanumeric names and derives the
# verdict through two tools DevFlow's preflight does not guarantee. `nullglob` makes an
# absent or unreadable DIR answer "no", matching the old `2>/dev/null` behaviour.
_dir_nonempty() (
  # Two self-containment guards, both fail-CLOSED, both reachable:
  #   - `[ -d "$1" ]` first: an empty/unset $1 would otherwise glob the filesystem ROOT and
  #     answer yes, and a path that is a regular file would glob nothing meaningful.
  #   - `set +f`: under a glob-disabled caller (this file exercises `set -f` in the
  #     _489_noglob_restore probe) the pattern would stay literal, leaving $# = 1 and
  #     answering yes for an empty or absent directory.
  [ -d "$1" ] || { echo no; return; }
  set +f
  shopt -s nullglob dotglob
  set -- "$1"/*
  [ "$#" -gt 0 ] && echo yes || echo no
)
# Positive control for _dir_nonempty: every call site below asserts "no", so a helper stuck
# at "no" (a glob typo, nullglob not taking, a quoting slip) would pass all of them
# vacuously. Assert the "yes" direction once against a directory known to be non-empty.
assert_eq "#745 _dir_nonempty: answers yes for a directory known to be non-empty (positive control)" "yes" \
  "$(_dir_nonempty "$ETSPH_REPO/.git")"   # git init above provably created it; .prflow is NOT created here
                                          # (the placeholder --persist call refuses and writes nothing)
assert_eq "#745 _dir_nonempty: answers no for an absent directory (fails closed)" "no" \
  "$(_dir_nonempty "$ETSPH_REPO/definitely-absent")"
assert_eq "et-synth(placeholder): NO placeholder-identity dir is fabricated" "no" \
  "$([ -d "$ETSPH_REPO/.prflow/tmp/review/<slug>" ] && echo yes || echo no)"
assert_eq "et-synth(placeholder): NO record is written under a placeholder identity" "no" \
  "$(_dir_nonempty "$ETSPH_REPO/.prflow/logs/efficiency")"
# The BASENAME-DERIVED route: a literal '<slug>/<run-id>' DIRECTORY (left by a
# non-substituting agent running a workpad-dir mkdir fence verbatim) reaches
# discovery mode without passing through argv — persist_one's twin guard must
# refuse it too, fabricating no synthesized workpad and no record.
mkdir -p "$ETSPH_REPO/.prflow/tmp/review/<slug>/<run-id>"
ETSPH_ERR2="$( ( cd "$ETSPH_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; ETSPH_RC2=$?
assert_eq "et-synth(placeholder): discovery over a literal <slug>/<run-id> dir exits 0" "0" "$ETSPH_RC2"
assert_eq "et-synth(placeholder): the basename-derived placeholder identity is refused with its own breadcrumb" "yes" \
  "$(printf '%s' "$ETSPH_ERR2" | grep -qF "unsubstituted '<placeholder>' identity" && echo yes || echo no)"
assert_eq "et-synth(placeholder): discovery fabricates NO synthesized workpad under the placeholder dir" "no" \
  "$(_dir_nonempty "$ETSPH_REPO/.prflow/tmp/review/<slug>/<run-id>")"
assert_eq "et-synth(placeholder): discovery writes NO placeholder-named record" "no" \
  "$(_dir_nonempty "$ETSPH_REPO/.prflow/logs/efficiency")"
rm -rf "$ETSPH_REPO"

# rc-3's uncreatable-target-dir arm: a read-only SLUG PARENT (mkdir -p of a
# not-yet-created run dir fails) must route to the rc-3 could-not-run diagnosis,
# never the rc-4 every-write-failed misattribution.
ETSMK_REPO="$(git_sandbox "et-synth unmkdirable repo")"
git -C "$ETSMK_REPO" init -q
git -C "$ETSMK_REPO" config user.email t@e.com; git -C "$ETSMK_REPO" config user.name t
git -C "$ETSMK_REPO" commit --allow-empty -qm base
git -C "$ETSMK_REPO" branch -M main
git -C "$ETSMK_REPO" checkout -q -b feat
printf a > "$ETSMK_REPO/a"; git -C "$ETSMK_REPO" add a; git -C "$ETSMK_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSMK_REPO/.prflow/tmp/review/pr-m"
chmod 555 "$ETSMK_REPO/.prflow/tmp/review/pr-m"
ETSMK_ERR="$( ( cd "$ETSMK_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSMK_REPO/.prflow/tmp/review/pr-m/run-m" --slug pr-m --persist ) 2>&1 1>/dev/null )"; ETSMK_RC=$?
chmod 755 "$ETSMK_REPO/.prflow/tmp/review/pr-m"
assert_eq "et-synth(unmkdirable): exits 0" "0" "$ETSMK_RC"
assert_eq "et-synth(unmkdirable): the could-not-create-dir breadcrumb fires" "yes" \
  "$(printf '%s' "$ETSMK_ERR" | grep -qF 'could not create workpad dir' && echo yes || echo no)"
assert_eq "et-synth(unmkdirable): NOT misattributed as every-write-failed (rc-4)" "no" \
  "$(printf '%s' "$ETSMK_ERR" | grep -qF 'every synthesized record write failed' && echo yes || echo no)"
# The rc-3 arm's own honesty pair (mirrors ETSB/ETSU): the never-established
# wording present, and the rc-2 found-none collapse absent — a rc-3→rc-2
# misclassification mutation must go RED here, not only lose the rc-4 negative.
assert_eq "et-synth(unmkdirable): never-established wording present (rc-3 arm)" "yes" \
  "$(printf '%s' "$ETSMK_ERR" | grep -qF 'was never established' && echo yes || echo no)"
assert_eq "et-synth(unmkdirable): does NOT emit the found-none collapse" "no" \
  "$(printf '%s' "$ETSMK_ERR" | grep -qF 'was not captured this run' && echo yes || echo no)"
rm -rf "$ETSMK_REPO"

# fix_files [] vs null: a genuine --allow-empty fix commit synthesizes fix_files
# [] (never null, never [""] from the empty-string split).
ETSE_REPO="$(git_sandbox "et-synth empty-commit repo")"
git -C "$ETSE_REPO" init -q
git -C "$ETSE_REPO" config user.email t@e.com; git -C "$ETSE_REPO" config user.name t
git -C "$ETSE_REPO" commit --allow-empty -qm base
git -C "$ETSE_REPO" branch -M main
git -C "$ETSE_REPO" checkout -q -b feat
git -C "$ETSE_REPO" commit --allow-empty -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSE_REPO/.prflow/tmp/review/pr-e/run-e"
( cd "$ETSE_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSE_REPO/.prflow/tmp/review/pr-e/run-e" --slug pr-e --persist ) >/dev/null 2>&1
assert_eq "et-synth(empty-commit): an --allow-empty fix commit synthesizes fix_files [] (not the failure-path null; jq split of \"\" is already [], the length filter is belt-and-suspenders)" "[]" \
  "$(jq -c '.fix_files' "$ETSE_REPO/.prflow/tmp/review/pr-e/run-e/iter-1.json" 2>/dev/null)"
rm -rf "$ETSE_REPO"

# Wrong-type base_branch row (adversarial input-shape matrix): a boolean config
# value coerces to the string "false", which resolves as neither origin/false
# nor false — so the run SKIPS synthesis via the rc-3 unresolvable-base arm
# (there is no fallback to main here; only the valid-falsy "" row falls back,
# via the resolver default — see ETSF). Assert the outcome and the diagnosis,
# never only the blanket exit-0 contract.
ETSWT_REPO="$(git_sandbox "et-synth wrongtype-base repo")"
git -C "$ETSWT_REPO" init -q
git -C "$ETSWT_REPO" config user.email t@e.com; git -C "$ETSWT_REPO" config user.name t
git -C "$ETSWT_REPO" commit --allow-empty -qm base
git -C "$ETSWT_REPO" branch -M main
git -C "$ETSWT_REPO" checkout -q -b feat
printf a > "$ETSWT_REPO/a"; git -C "$ETSWT_REPO" add a; git -C "$ETSWT_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSWT_REPO/.prflow"
printf '{"base_branch": false}' > "$ETSWT_REPO/.prflow/config.json"
mkdir -p "$ETSWT_REPO/.prflow/tmp/review/pr-wt/run-wt"
ETSWT_RC=0
ETSWT_ERR="$( ( cd "$ETSWT_REPO" && bash "$LIB/efficiency-trace.sh" --workpad-dir "$ETSWT_REPO/.prflow/tmp/review/pr-wt/run-wt" --slug pr-wt --persist ) 2>&1 1>/dev/null )" || ETSWT_RC=$?
assert_eq "et-synth(wrongtype-base): a boolean base_branch config value never detonates (exit 0)" "0" "$ETSWT_RC"
assert_eq "et-synth(wrongtype-base): the tried value is named (present-but-wrong-type is not reported as absent)" "yes" \
  "$(printf '%s' "$ETSWT_ERR" | grep -qF ".base_branch resolved to 'false'" && echo yes || echo no)"
assert_eq "et-synth(wrongtype-base): routes to the rc-3 unresolvable-base skip, no record written" "no" \
  "$([ -e "$ETSWT_REPO/.prflow/logs/efficiency/pr-wt-run-wt.json" ] && echo yes || echo no)"
rm -rf "$ETSWT_REPO"

# origin/<base> preferred over a STALE local base: a worktree's local main is
# routinely behind origin; diffing against it would sweep already-merged history
# (an old PR's fix commits) into this run's synthesis. origin-first prevents it.
ETSO_REPO="$(git_sandbox "et-synth origin-first repo")"
git -C "$ETSO_REPO" init -q
git -C "$ETSO_REPO" config user.email t@e.com; git -C "$ETSO_REPO" config user.name t
git -C "$ETSO_REPO" commit --allow-empty -qm base
git -C "$ETSO_REPO" branch -M main
ETSO_MAIN0="$(git -C "$ETSO_REPO" rev-parse HEAD)"
printf m > "$ETSO_REPO/m"; git -C "$ETSO_REPO" add m
git -C "$ETSO_REPO" commit -qm "fix: address review findings (iteration 7)"   # an OLD merged PR's fix commit, now in main history
ETSO_MAIN1="$(git -C "$ETSO_REPO" rev-parse HEAD)"
git -C "$ETSO_REPO" checkout -q -b feat
printf b > "$ETSO_REPO/b"; git -C "$ETSO_REPO" add b; git -C "$ETSO_REPO" commit -qm "fix: address review findings (iteration 1)"
git -C "$ETSO_REPO" update-ref refs/remotes/origin/main "$ETSO_MAIN1"   # origin is current
git -C "$ETSO_REPO" branch -f main "$ETSO_MAIN0"                        # local main is STALE
mkdir -p "$ETSO_REPO/.prflow/tmp/review/pr-o/run-o"
( cd "$ETSO_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSO_REPO/.prflow/tmp/review/pr-o/run-o" --slug pr-o ) >/dev/null 2>&1
assert_eq "et-synth(origin-first): merged-history fix commit is NOT swept in by the stale local base" "[1]" \
  "$(_et_show "$ETSO_REPO" ".prflow/logs/efficiency/pr-o-run-o.json" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
assert_eq "et-synth(origin-first): no iter-7.json synthesized from the merged old PR" "no" \
  "$([ -e "$ETSO_REPO/.prflow/tmp/review/pr-o/run-o/iter-7.json" ] && echo yes || echo no)"
rm -rf "$ETSO_REPO"

# The durable-copy half of the exclusion glob: a sha recorded ONLY under
# .prflow/logs/review/ (tmp wiped after a prior persist) still excludes.
ETSD_REPO="$(git_sandbox "et-synth durable-exclusion repo")"
git -C "$ETSD_REPO" init -q
git -C "$ETSD_REPO" config user.email t@e.com; git -C "$ETSD_REPO" config user.name t
git -C "$ETSD_REPO" commit --allow-empty -qm base
git -C "$ETSD_REPO" branch -M main
git -C "$ETSD_REPO" checkout -q -b feat
printf a > "$ETSD_REPO/a"; git -C "$ETSD_REPO" add a; git -C "$ETSD_REPO" commit -qm "fix: address review findings (iteration 1)"
ETSD_A="$(git -C "$ETSD_REPO" rev-parse HEAD)"
mkdir -p "$ETSD_REPO/.prflow/logs/review/pr-old/run-gone"
printf '{"iter":1,"fix_commit_sha":"%s","fix_files":["a"],"loop_role":"fix"}' "$ETSD_A" \
  > "$ETSD_REPO/.prflow/logs/review/pr-old/run-gone/iter-1.json"
mkdir -p "$ETSD_REPO/.prflow/tmp/review/pr-d/run-1"
ETSD_ERR="$( ( cd "$ETSD_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSD_REPO/.prflow/tmp/review/pr-d/run-1" --slug pr-d ) 2>&1 1>/dev/null )"
assert_eq "et-synth(durable): a sha recorded only in a durable copy still excludes (breadcrumbed)" "yes" \
  "$(printf '%s' "$ETSD_ERR" | grep -qF 'already recorded by another run' && echo yes || echo no)"
assert_eq "et-synth(durable): nothing left to synthesize, no record written" "no" \
  "$([ -e "$ETSD_REPO/.prflow/logs/efficiency/pr-d-run-1.json" ] && echo yes || echo no)"
rm -rf "$ETSD_REPO"

# rc-4: commits selected but every synthesized write fails (unwritable run dir) —
# the honesty ladder must say "every synthesized record write failed", never the
# rc-2 "no commits were found" collapse.
ETSW_REPO="$(git_sandbox "et-synth write-fail repo")"
git -C "$ETSW_REPO" init -q
git -C "$ETSW_REPO" config user.email t@e.com; git -C "$ETSW_REPO" config user.name t
git -C "$ETSW_REPO" commit --allow-empty -qm base
git -C "$ETSW_REPO" branch -M main
git -C "$ETSW_REPO" checkout -q -b feat
printf a > "$ETSW_REPO/a"; git -C "$ETSW_REPO" add a; git -C "$ETSW_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSW_REPO/.prflow/tmp/review/pr-w/run-w"
chmod 555 "$ETSW_REPO/.prflow/tmp/review/pr-w/run-w"
ETSW_ERR="$( ( cd "$ETSW_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSW_REPO/.prflow/tmp/review/pr-w/run-w" --slug pr-w ) 2>&1 1>/dev/null )"; ETSW_RC=$?
chmod 755 "$ETSW_REPO/.prflow/tmp/review/pr-w/run-w"
assert_eq "et-synth(rc4): write-failure run exits 0" "0" "$ETSW_RC"
assert_eq "et-synth(rc4): breadcrumb names the write failure, not the found-none collapse" "yes" \
  "$(printf '%s' "$ETSW_ERR" | grep -qF 'every synthesized record write failed' && echo yes || echo no)"
assert_eq "et-synth(rc4): does NOT claim no commits were found" "no" \
  "$(printf '%s' "$ETSW_ERR" | grep -qF 'no unrecorded' && echo yes || echo no)"
rm -rf "$ETSW_REPO"

# rc-3's SECOND arm: base ref resolves but `git log` itself fails (unborn HEAD) —
# the persist_one breadcrumb must stay cause-neutral, never asserting
# "no base branch ref resolvable" about a failure that was the log enumeration.
ETSU_REPO="$(git_sandbox "et-synth unborn-head repo")"
git -C "$ETSU_REPO" init -q
git -C "$ETSU_REPO" config user.email t@e.com; git -C "$ETSU_REPO" config user.name t
git -C "$ETSU_REPO" commit --allow-empty -qm base
git -C "$ETSU_REPO" branch -M main
git -C "$ETSU_REPO" symbolic-ref HEAD refs/heads/unborn
mkdir -p "$ETSU_REPO/.prflow/tmp/review/pr-u/run-u"
ETSU_ERR="$( ( cd "$ETSU_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSU_REPO/.prflow/tmp/review/pr-u/run-u" --slug pr-u ) 2>&1 1>/dev/null )"; ETSU_RC=$?
assert_eq "et-synth(log-fail): exits 0" "0" "$ETSU_RC"
assert_eq "et-synth(log-fail): the git log failure arm emits its OWN producer breadcrumb (rc-checked)" "yes" \
  "$(printf '%s' "$ETSU_ERR" | grep -q 'git log .*failed (rc-checked' && echo yes || echo no)"
assert_eq "et-synth(log-fail): does NOT misattribute the failure to an unresolvable base ref" "no" \
  "$(printf '%s' "$ETSU_ERR" | grep -qF 'could not resolve a base branch ref' && echo yes || echo no)"
assert_eq "et-synth(log-fail): does NOT claim commits were absent" "no" \
  "$(printf '%s' "$ETSU_ERR" | grep -qF 'was not captured this run' && echo yes || echo no)"
rm -rf "$ETSU_REPO"

# Valid-falsy base_branch: an explicit "" config value must fall back to main
# (the CLAUDE.md adversarial-matrix valid-falsy row for this consumer).
ETSF_REPO="$(git_sandbox "et-synth empty-base-config repo")"
git -C "$ETSF_REPO" init -q
git -C "$ETSF_REPO" config user.email t@e.com; git -C "$ETSF_REPO" config user.name t
git -C "$ETSF_REPO" commit --allow-empty -qm base
git -C "$ETSF_REPO" branch -M main
git -C "$ETSF_REPO" checkout -q -b feat
printf a > "$ETSF_REPO/a"; git -C "$ETSF_REPO" add a; git -C "$ETSF_REPO" commit -qm "fix: address review findings (iteration 1)"
mkdir -p "$ETSF_REPO/.prflow"
printf '{"base_branch":""}' > "$ETSF_REPO/.prflow/config.json"
mkdir -p "$ETSF_REPO/.prflow/tmp/review/pr-f/run-f"
( cd "$ETSF_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$ETSF_REPO/.prflow/tmp/review/pr-f/run-f" --slug pr-f ) >/dev/null 2>&1
assert_eq "et-synth(valid-falsy): explicit empty base_branch falls back to main and synthesis runs" "[1]" \
  "$(_et_show "$ETSF_REPO" ".prflow/logs/efficiency/pr-f-run-f.json" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
rm -rf "$ETSF_REPO"

# fix_files: null (the diff-tree-failure shape) flows through BOTH jq modes rc-0 —
# a future jq edit that starts mapping over fix_files must not null-detonate.
ETSN_REPO="$(git_sandbox "et-synth null-fixfiles repo")"
git -C "$ETSN_REPO" init -q
mkdir -p "$ETSN_REPO/.prflow/tmp/review/pr-n/run-n"
printf '{"iter":1,"fix_commit_sha":"abc","fix_files":null,"loop_role":"fix","synthesized":true,"sweep_defs_read":{"status":"unrecoverable","reason":"r"},"sweep_evidence":{"status":"unrecoverable","reason":"r"},"reference_reads":{"fix_delta":{"status":"unrecoverable","reason":"r"}}}' \
  > "$ETSN_REPO/.prflow/tmp/review/pr-n/run-n/iter-1.json"
( cd "$ETSN_REPO" && bash "$LIB/efficiency-trace.sh" --mode trace --workpad-dir "$ETSN_REPO/.prflow/tmp/review/pr-n/run-n" --slug pr-n ) >/dev/null 2>&1; ETSN_T=$?
ETSN_R="$( ( cd "$ETSN_REPO" && bash "$LIB/efficiency-trace.sh" --mode record --workpad-dir "$ETSN_REPO/.prflow/tmp/review/pr-n/run-n" --slug pr-n ) 2>/dev/null )"; ETSN_RRC=$?
assert_eq "et-synth(null-fixfiles): --mode trace over a null-fix_files record exits 0" "0" "$ETSN_T"
assert_eq "et-synth(null-fixfiles): --mode record over a null-fix_files record exits 0" "0" "$ETSN_RRC"
assert_eq "et-synth(null-fixfiles): record still renders the iteration" "[1]" \
  "$(printf '%s' "$ETSN_R" | jq -c '[.per_iteration[].iter]' 2>/dev/null)"
rm -rf "$ETSN_REPO"

# Mixed valid + malformed iters where one iter is malformed: the malformed iter is
# skipped with a breadcrumb (collect_valid_files) and the record is still derived
# from the surviving valid iter — exit 0, never a wrongly-dropped run. (Under #441
# the former source=="review" probe is gone, so there is no source-probe breadcrumb
# anymore; the malformed-workpad breadcrumb is the surviving signal.)
ETMX_REPO="$(git_sandbox "et-persist mixed-iters repo")"
git -C "$ETMX_REPO" init -q
git -C "$ETMX_REPO" config user.email t@e.com; git -C "$ETMX_REPO" config user.name t
mkdir -p "$ETMX_REPO/.prflow/tmp/review/pr-40/run-m"
printf '%s' "$ETP_ITER" > "$ETMX_REPO/.prflow/tmp/review/pr-40/run-m/iter-1.json"
printf '[]' > "$ETMX_REPO/.prflow/tmp/review/pr-40/run-m/iter-2.json"   # malformed, sorts last
ETMX_OUT="$( ( cd "$ETMX_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 )"; ETMX_RC=$?
assert_eq "et-persist: malformed iter → exit 0 (not wrongly skipped)" "0" "$ETMX_RC"
assert_eq "et-persist: malformed iter → record still derived from valid iter (on the branch)" "yes" \
  "$(_et_on_branch "$ETMX_REPO" ".prflow/logs/efficiency/pr-40-run-m.json")"
assert_eq "et-persist: malformed iter leaves a skip breadcrumb" "yes" \
  "$(printf '%s' "$ETMX_OUT" | grep -qF 'skipping unreadable/malformed workpad' && echo yes || echo no)"
rm -rf "$ETMX_REPO"

# Discovery over MULTIPLE run dirs → exactly ONE batched branch commit for all of
# them. Under #441 a review-mode sibling is UNIFIED into the same store (the former
# source=="review" skip is gone), so all three dirs — two review-and-fix and one
# review — persist to the branch, and they land in a single branch commit.
ETMD_REPO="$(git_sandbox "et-persist multi-dir repo")"
git -C "$ETMD_REPO" init -q
git -C "$ETMD_REPO" config user.email t@e.com; git -C "$ETMD_REPO" config user.name t
mkdir -p "$ETMD_REPO/.prflow/tmp/review/pr-30/run-a" "$ETMD_REPO/.prflow/tmp/review/pr-31/run-b" "$ETMD_REPO/.prflow/tmp/review/pr-32/run-c"
printf '%s' "$ETP_ITER" > "$ETMD_REPO/.prflow/tmp/review/pr-30/run-a/iter-1.json"
printf '%s' "$ETP_ITER" > "$ETMD_REPO/.prflow/tmp/review/pr-31/run-b/iter-1.json"
printf '{"iter":1,"source":"review","phase3_findings":[]}' > "$ETMD_REPO/.prflow/tmp/review/pr-32/run-c/iter-1.json"
( cd "$ETMD_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "et-persist: multi-dir discovery persists run dir A (on the branch)" "yes" \
  "$(_et_on_branch "$ETMD_REPO" ".prflow/logs/efficiency/pr-30-run-a.json")"
assert_eq "et-persist: multi-dir discovery persists run dir B (on the branch)" "yes" \
  "$(_et_on_branch "$ETMD_REPO" ".prflow/logs/efficiency/pr-31-run-b.json")"
assert_eq "et-persist(#441): review-mode sibling ALSO persisted (unified store)" "yes" \
  "$(_et_on_branch "$ETMD_REPO" ".prflow/logs/efficiency/pr-32-run-c.json")"
assert_eq "et-persist(#441): all discovered records land in exactly ONE batched branch commit" "1" \
  "$(_et_branch_count "$ETMD_REPO")"
rm -rf "$ETMD_REPO"

# Durable-copy refresh: the record is presence-frozen, but a NEW iter appearing
# after the first persist must still be copied into the durable tree and produce
# a new commit — proving the copy is not gated by the frozen record.
ETDR_REPO="$(git_sandbox "et-persist durable-refresh repo")"
git -C "$ETDR_REPO" init -q
git -C "$ETDR_REPO" config user.email t@e.com; git -C "$ETDR_REPO" config user.name t
mkdir -p "$ETDR_REPO/.prflow/tmp/review/pr-50/run-d"
printf '%s' "$ETP_ITER" > "$ETDR_REPO/.prflow/tmp/review/pr-50/run-d/iter-1.json"
( cd "$ETDR_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
ETDR_COUNT1="$(_et_branch_count "$ETDR_REPO")"
# A second iteration appears, then re-persist.
printf '{"iter":2,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$ETDR_REPO/.prflow/tmp/review/pr-50/run-d/iter-2.json"
( cd "$ETDR_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
ETDR_COUNT2="$(_et_branch_count "$ETDR_REPO")"
assert_eq "et-persist: first persist made exactly 1 branch commit" "1" "$ETDR_COUNT1"
assert_eq "et-persist: new iter after persist → durable copy refreshed on the branch (iter-2 present)" "yes" \
  "$(_et_on_branch "$ETDR_REPO" ".prflow/logs/review/pr-50/run-d/iter-2.json")"
assert_eq "et-persist: durable refresh produces a new branch commit (record frozen, copy not)" "2" "$ETDR_COUNT2"
assert_eq "et-persist: frozen record was NOT re-derived (iterations stays 1)" "1" \
  "$(_et_show "$ETDR_REPO" ".prflow/logs/efficiency/pr-50-run-d.json" | jq -r '.iterations')"
rm -rf "$ETDR_REPO"

# ── Issue #170: loop_role derivation + --self-check field validation ─────────
# (1) efficiency-trace.jq DERIVES loop_role per iteration of the per-run record:
#     iter 1 → fix; iter N → promoted when iter N-1's shadow.promoted_to_iter_next
#     is true. The fixtures OMIT loop_role entirely, proving the derivation holds
#     on the dropped-persist path (the reason the backstop exists).
LR_DIR="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}' > "$LR_DIR/iter-1.json"
printf '{"iter":2,"phase3_findings":[]}'                                         > "$LR_DIR/iter-2.json"
LR_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_DIR" --slug pr-70 --mode record)"; LR_RC=$?
assert_eq "loop_role #170: record mode exits 0" "0" "$LR_RC"
assert_eq "loop_role #170: per-run record surfaces loop_role per iteration (real consumer)" "true" \
  "$(printf '%s' "$LR_REC" | jq -r '[.per_iteration[] | has("loop_role")] | all')"
assert_eq "loop_role #170: iter 1 derives fix (dropped-persist path: field omitted in fixture)" "fix" \
  "$(printf '%s' "$LR_REC" | jq -r '.per_iteration[] | select(.iter==1) | .loop_role')"
assert_eq "loop_role #170: iter 2 derives promoted (prior shadow.promoted_to_iter_next=true)" "promoted" \
  "$(printf '%s' "$LR_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_DIR"

# (2) A persisted non-empty loop_role is PRESERVED over the derived value.
LR_P="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":false}}' > "$LR_P/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"loop_role":"promoted"}'                    > "$LR_P/iter-2.json"
LR_P_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_P" --slug pr-71 --mode record)"
assert_eq "loop_role #170: persisted loop_role preserved (derived would be fix, persisted=promoted wins)" "promoted" \
  "$(printf '%s' "$LR_P_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_P"

# (3) Graceful degradation: lone iter 1 with no shadow + no loop_role → fix; an
#     unparseable iter is dropped (object-gate) yet the record still derives,
#     exit 0; a missing run dir → exit 0. Never aborts (the efficiency-trace
#     "every mode never aborts" contract).
LR_D="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[]}' > "$LR_D/iter-1.json"
printf 'not json'                        > "$LR_D/iter-2.json"
LR_D_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_D" --slug pr-72 --mode record)"; LR_D_RC=$?
assert_eq "loop_role #170: unparseable iter present → record mode still exits 0" "0" "$LR_D_RC"
assert_eq "loop_role #170: lone iter 1, no shadow/no loop_role → fix default" "fix" \
  "$(printf '%s' "$LR_D_REC" | jq -r '.per_iteration[] | select(.iter==1) | .loop_role')"
rm -rf "$LR_D"
LR_MISS="$(mktemp -d)"; rmdir "$LR_MISS"
bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_MISS" --slug pr-73 --mode record >/dev/null 2>&1; LR_MISS_RC=$?
assert_eq "loop_role #170: missing run dir → record mode exits 0" "0" "$LR_MISS_RC"

# (4) --self-check WARNS (best-effort, exit 0, no writes) when an iter workpad is
#     missing an expected field — naming the field + the iter file — and leaves
#     the iter file byte-identical. Fixture carries every expected field EXCEPT
#     telemetry (a non-derivable expected field).
LR_SC_REPO="$(git_sandbox "lr self-check repo")"
git -C "$LR_SC_REPO" init -q
LR_SC_RUN="$LR_SC_REPO/.prflow/tmp/review/pr-74/run-z"
mkdir -p "$LR_SC_RUN"
printf '{"iter":1,"started_at":"x","fix_commit_sha":"x","fix_files":[],"loop_role":"fix","checklist":[],"phase3_dispatched":[],"diff_profile":{},"phase3_findings":[],"fix_decisions":[],"convergence_inputs":{},"cap_drops":{}}' > "$LR_SC_RUN/iter-1.json"
cp "$LR_SC_RUN/iter-1.json" "$LR_SC_REPO/iter-1.bak"
LR_SC_OUT="$( ( cd "$LR_SC_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_SC_RUN" --slug pr-74 ) 2>&1 )"; LR_SC_RC=$?
assert_eq "loop_role #170: --self-check exits 0 on a missing field" "0" "$LR_SC_RC"
assert_eq "loop_role #170: --self-check ::warning:: names the missing field + iter file on one line" "yes" \
  "$(printf '%s' "$LR_SC_OUT" | grep -F '::warning::' | grep -F 'telemetry' | grep -qF 'iter-1.json' && echo yes || echo no)"
assert_eq "loop_role #170: --self-check never mutates the iter file (byte-identical)" "yes" \
  "$(cmp -s "$LR_SC_REPO/iter-1.bak" "$LR_SC_RUN/iter-1.json" && echo yes || echo no)"
rm -rf "$LR_SC_REPO"

# (5) Single-source field set ↔ SKILL.md schema divergence guard (AC #6).
#     ITER_EXPECTED_FIELDS in efficiency-trace.sh is the ONE place the expected
#     iter-field set is defined; it MUST equal the iter-<N>.json schema's
#     unconditional top-level fields in SKILL.md minus `shadow` and
#     `parked_class_sweep` (convergence-only), `park_calibration`
#     (convergence-only — written by the Step 2.6 evidence gate, issue #557),
#     `promotion_provenance` (conditional on promoted iterations), the #530
#     navigation stamps `current_step`/`current_substep`/`pending_dispatch`
#     (best-effort continuation operands, not effectiveness/cost telemetry), and
#     `reference_reads` (issue #541 — conditional in the same sense as `shadow`: Step
#     3.5's fix-delta gate appends it, so it is legitimately absent on an iteration
#     where that gate did not run. The parallel is scoped to CONDITIONALITY only —
#     `shadow` has a dedicated synthesis floor (synthesize_shadow_markers) whereas
#     `reference_reads` is stamped inline by synthesize_iter_workpads, so the two
#     differ where provenance recovery is concerned) — all are subtracted by the `-Ev`
#     filter below. FAILs if
#     an unconditional field is added/removed on either side. NOTE both sides are
#     `sort -u`'d, so this asserts SET equality, never field order.
LR_CONST="$(grep -E '^ITER_EXPECTED_FIELDS=' "$LIB/efficiency-trace.sh" | sed -E 's/^ITER_EXPECTED_FIELDS=//; s/"//g' | tr ' ' '\n' | grep -v '^$' | sort -u)"
# The conditional-field set is declared ONCE and both consumers derive from it: the
# `-Ev` subtraction below, and the positive presence assertions further down. Before
# issue #541 the two were hand-maintained separately, and they had already skewed — the
# regex subtracted 7 fields while only the 3 nav fields carried a presence pin, leaving
# `shadow`, `promotion_provenance`, `parked_class_sweep`, and `park_calibration`
# subtracted with nothing to catch their deletion. Deriving both from one list makes that
# skew impossible by construction and makes the next conditional field a one-token edit.
LR_CONDITIONAL_FIELDS="shadow promotion_provenance parked_class_sweep park_calibration current_step current_substep pending_dispatch reference_reads dispatch_mode"
# Built with bash parameter expansion, never `tr`: this value DECIDES which fields are
# subtracted, and the repo's guard-class-2 rule bars deriving a selection through a
# PATH tool the preflight does not guarantee (a missing `tr` would empty the alternation).
LR_COND_RE="^(${LR_CONDITIONAL_FIELDS// /|})$"
LR_SCHEMA="$(sed -n '/^### Schema$/,/^```$/p' "$MAXI_SKILL" | grep -E '^  "[A-Za-z0-9_]+":' | sed -E 's/^  "([A-Za-z0-9_]+)":.*/\1/' | grep -Ev "$LR_COND_RE" | sort -u)"
# Positive control (#541 review): BOTH operands are derived through grep/sed/tr, none of
# which the preflight guarantees. An emptied extraction on either side makes the comparison
# `assert_eq "" ""`, which PASSES while checking nothing — silently retiring this
# single-source guard. That is the same vacuity the ETF5_SYNTH_FIELDS control prevents for
# the sibling synthesized-set extraction; this assertion is its missing counterpart here.
# `telemetry` is a stable member of both sides, so a non-vacuous extraction must contain it.
assert_eq "loop_role #170 control: LR_CONST extraction is non-vacuous (carries telemetry)" "yes" \
  "$(printf '%s\n' "$LR_CONST" | grep -qx 'telemetry' && echo yes || echo no)"
assert_eq "loop_role #170 control: LR_SCHEMA extraction is non-vacuous (carries telemetry)" "yes" \
  "$(printf '%s\n' "$LR_SCHEMA" | grep -qx 'telemetry' && echo yes || echo no)"
assert_eq "loop_role #170: ITER_EXPECTED_FIELDS single-source == SKILL.md unconditional schema fields" \
  "$LR_SCHEMA" "$LR_CONST"
# Conditionality converse (#541 review): the presence pins further down assert each
# conditional field IS in the schema block, but nothing asserted the property that makes the
# `-Ev` subtraction SAFE — that each subtracted field is genuinely ABSENT from
# ITER_EXPECTED_FIELDS. A field declared in BOTH lists is subtracted from LR_SCHEMA while the
# constant still requires it, so the equality above goes RED for the wrong reason; two such
# mis-declarations could even balance out and stay green.
for _c541 in $LR_CONDITIONAL_FIELDS; do
  assert_eq "#541: conditional field $_c541 is absent from ITER_EXPECTED_FIELDS (the -Ev subtraction is safe)" "yes" \
    "$(printf '%s\n' "$LR_CONST" | grep -qx "$_c541" && echo no || echo yes)"
done

# (5b) #539 review (Suggestion, test_gap): the three #530 navigation stamps are subtracted
#     from LR_SCHEMA by the `-Ev` filter above — correctly, since they are best-effort
#     continuation operands, not effectiveness/cost telemetry. But that subtraction means a
#     future edit that DROPS a nav field from the schema leaves LR_SCHEMA excluding a field that
#     no longer appears, so the equality test stays GREEN and the durable-resume contract (issue
#     #530 — the whole point of the split) silently regresses. Pin each positively so a drop goes
#     RED at the desk. The `grep -qx` membership check below cannot pass on an absent field
#     (empty membership -> "no" -> RED), so it is non-vacuous by construction.
# Scope the presence check to the ### Schema fence itself, not the whole bundle: a future
# edit that RELOCATED a nav field out of the schema block into prose elsewhere would keep a
# bundle-wide grep green while silently desyncing the schema from ITER_EXPECTED_FIELDS via the
# `-Ev` subtraction above (issue #539 shadow, pr-test-analyzer). LR_SCHEMA_ALL is LR_SCHEMA
# without the `-Ev` exclusion — exactly the schema-block field set — so asserting each nav field
# is a member goes RED on a drop OR a relocation-out-of-block, the tighter guard the comment claims.
LR_SCHEMA_ALL="$(sed -n '/^### Schema$/,/^```$/p' "$MAXI_SKILL" | grep -E '^  "[A-Za-z0-9_]+":' | sed -E 's/^  "([A-Za-z0-9_]+)":.*/\1/' | sort -u)"
# Drive the presence check over EVERY subtracted field from the single LR_CONDITIONAL_FIELDS
# list (issue #541), not a hand-picked subset. The subtraction hazard the comment above
# describes applies identically to every excluded field, so enumerating them by hand is what
# let four of them (shadow, promotion_provenance, parked_class_sweep, park_calibration) sit
# subtracted-but-unpinned. Deriving the loop from the same list that drives the subtraction
# means a newly-excluded field is pinned automatically and the two can never skew.
for _condf in $LR_CONDITIONAL_FIELDS; do
  assert_eq "#530/#539/#541 conditional field: $_condf present in the ### Schema block (its -Ev exclusion cannot catch a drop)" "yes" \
    "$(printf '%s\n' "$LR_SCHEMA_ALL" | grep -qx "$_condf" && echo yes || echo no)"
done

# (5c) The Step 2.6 shadow entry records its own `dispatch_mode` NESTED inside the
#      `shadow` block, one level below the 2-space keys LR_SCHEMA_ALL extracts — so the
#      presence loop above cannot see it, and a drop there would leave the shadow
#      entry's dispatch provenance unrecorded with every assertion above still green.
LR_SHADOW_KEYS="$(sed -n '/^### Schema$/,/^```$/p' "$MAXI_SKILL" | sed -n '/^  "shadow": {$/,/^  },$/p' | grep -E '^    "[A-Za-z0-9_]+":' | sed -E 's/^    "([A-Za-z0-9_]+)":.*/\1/' | sort -u)"
assert_eq "#1850 control: LR_SHADOW_KEYS extraction is non-vacuous (carries verdict)" "yes" \
  "$(printf '%s\n' "$LR_SHADOW_KEYS" | grep -qx 'verdict' && echo yes || echo no)"
assert_eq "#1850: the shadow block carries its own dispatch_mode (Step 2.6 entry separately readable)" "yes" \
  "$(printf '%s\n' "$LR_SHADOW_KEYS" | grep -qx 'dispatch_mode' && echo yes || echo no)"

# (6) --self-check NEVER ABORTS on an unparseable iter file (issue #170 AC: every
#     new path exits 0 on an unparseable iter-N.json). The script runs under
#     `set -euo pipefail`, so a bare `missing=$(jq ...)` assignment would trip set -e
#     when jq fails to parse — this asserts the `if !`-guarded assignment keeps the
#     contract. A valid iter alongside the malformed one still gets its missing-field
#     warnings. (Regression test for a /simplify-introduced abort.)
LR_SCM_REPO="$(git_sandbox "lr self-check malformed-iter repo")"
git -C "$LR_SCM_REPO" init -q
LR_SCM_RUN="$LR_SCM_REPO/.prflow/tmp/review/pr-75/run-w"
mkdir -p "$LR_SCM_RUN"
printf '{"iter":1,"loop_role":"fix"}'   > "$LR_SCM_RUN/iter-1.json"   # valid object, many fields missing
printf 'not json at all'                > "$LR_SCM_RUN/iter-2.json"   # unparseable — must NOT abort the pass
LR_SCM_OUT="$( ( cd "$LR_SCM_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_SCM_RUN" --slug pr-75 ) 2>&1 )"; LR_SCM_RC=$?
assert_eq "loop_role #170: --self-check exits 0 with an unparseable iter present (never aborts under set -e)" "0" "$LR_SCM_RC"
assert_eq "loop_role #170: --self-check still warns on the VALID iter's missing fields despite a malformed sibling" "yes" \
  "$(printf '%s' "$LR_SCM_OUT" | grep -F '::warning::' | grep -F 'telemetry' | grep -qF 'iter-1.json' && echo yes || echo no)"
# (6a) PR #177 review: an unparseable/unreadable iter must NOT pass silently in a
#      standalone --self-check (the --persist/--mode breadcrumb paths have not run).
#      The malformed iter-2.json above must itself draw a distinct warning naming it.
assert_eq "loop_role #170: --self-check WARNS on the unparseable iter (not silent corruption)" "yes" \
  "$(printf '%s' "$LR_SCM_OUT" | grep -F '::warning::' | grep -F 'iter-2.json' | grep -qF 'not valid JSON' && echo yes || echo no)"
rm -rf "$LR_SCM_REPO"

# (6b) PR #177 review: a parsed-but-NON-OBJECT iter (valid JSON [], null, "x") must
#      NOT masquerade as a complete workpad — it takes a distinct sentinel warning,
#      never the silent "no missing fields" arm. Exit 0 preserved (warn-only).
LR_SCN_REPO="$(git_sandbox "lr self-check null-iter repo")"
git -C "$LR_SCN_REPO" init -q
LR_SCN_RUN="$LR_SCN_REPO/.prflow/tmp/review/pr-77/run-n"
mkdir -p "$LR_SCN_RUN"
printf '[]'                              > "$LR_SCN_RUN/iter-1.json"   # valid JSON, wrong shape (array)
printf '"a bare string"'                 > "$LR_SCN_RUN/iter-2.json"   # valid JSON, wrong shape (string)
printf '{"iter":3,"loop_role":"fix"}'    > "$LR_SCN_RUN/iter-3.json"   # valid object — fields missing
LR_SCN_OUT="$( ( cd "$LR_SCN_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_SCN_RUN" --slug pr-77 ) 2>&1 )"; LR_SCN_RC=$?
assert_eq "loop_role #170: --self-check exits 0 on a non-object iter (never aborts)" "0" "$LR_SCN_RC"
assert_eq "loop_role #170: --self-check WARNS the non-object array iter is not an object" "yes" \
  "$(printf '%s' "$LR_SCN_OUT" | grep -F '::warning::' | grep -F 'iter-1.json' | grep -qF 'not an object' && echo yes || echo no)"
assert_eq "loop_role #170: --self-check WARNS the non-object string iter is not an object" "yes" \
  "$(printf '%s' "$LR_SCN_OUT" | grep -F '::warning::' | grep -F 'iter-2.json' | grep -qF 'not an object' && echo yes || echo no)"
# the non-object arm must NOT be misreported as a missing-field list
assert_eq "loop_role #170: --self-check does NOT emit a 'missing expected field' line for a non-object iter" "no" \
  "$(printf '%s' "$LR_SCN_OUT" | grep -F 'iter-1.json' | grep -qF 'missing expected field' && echo yes || echo no)"
# the valid object sibling still gets its real missing-field validation
assert_eq "loop_role #170: --self-check still validates the valid object sibling's fields" "yes" \
  "$(printf '%s' "$LR_SCN_OUT" | grep -F '::warning::' | grep -F 'iter-3.json' | grep -qF 'missing expected field' && echo yes || echo no)"
rm -rf "$LR_SCN_REPO"

# (7) Promotion does NOT propagate/latch: in a 3-iter chain where iter-1 promotes
#     but iter-2 does not, the derived roles are fix, promoted, fix — each iter's
#     role keys only on its IMMEDIATELY-preceding iter's shadow_promoted.
LR_3="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}'  > "$LR_3/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"shadow":{"promoted_to_iter_next":false}}' > "$LR_3/iter-2.json"
printf '{"iter":3,"phase3_findings":[]}'                                          > "$LR_3/iter-3.json"
LR_3_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_3" --slug pr-76 --mode record)"
assert_eq "loop_role #170: 3-iter chain role sequence is fix/promoted/fix (no latch/propagation)" "fix promoted fix" \
  "$(printf '%s' "$LR_3_REC" | jq -r '[.per_iteration[] | .loop_role] | join(" ")')"
rm -rf "$LR_3"

# (8) An empty-string persisted loop_role falls back to derivation (the `length > 0`
#     half of the type-guard) — iter 2 with loop_role:"" and a prior promotion derives
#     "promoted", not the persisted empty string.
LR_E="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}' > "$LR_E/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"loop_role":""}'                          > "$LR_E/iter-2.json"
LR_E_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_E" --slug pr-77 --mode record)"
assert_eq "loop_role #170: empty-string persisted loop_role falls back to derivation (not preserved)" "promoted" \
  "$(printf '%s' "$LR_E_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_E"

# (9) shadow_promoted is a STRICT boolean: a malformed non-boolean
#     promoted_to_iter_next (e.g. the string "yes") must NOT over-classify the next
#     iter as promoted — it coerces to false, so iter 2 derives fix. Locks the
#     `== true` guard the comment promises (mutation: drop `== true` → iter 2 flips
#     to promoted, RED).
LR_B="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":"yes"}}' > "$LR_B/iter-1.json"
printf '{"iter":2,"phase3_findings":[]}'                                          > "$LR_B/iter-2.json"
LR_B_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_B" --slug pr-78 --mode record)"
assert_eq "loop_role #170: malformed non-boolean promoted_to_iter_next ('yes') does NOT over-classify next iter (strict == true)" "fix" \
  "$(printf '%s' "$LR_B_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_B"

# (10) A non-STRING persisted loop_role (the `type == "string"` half of the guard,
#      vs the length>0 half in test 8) falls back to derivation — a numeric
#      loop_role:5 on iter 2 with a prior promotion derives "promoted", not 5.
LR_N="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}' > "$LR_N/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"loop_role":5}'                           > "$LR_N/iter-2.json"
LR_N_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_N" --slug pr-79 --mode record)"
assert_eq "loop_role #170: non-string persisted loop_role (numeric) falls back to derivation (type guard)" "promoted" \
  "$(printf '%s' "$LR_N_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_N"

# (11) --self-check emits NO field-validation ::warning:: on a fully-complete iter
#      (every ITER_EXPECTED_FIELDS member present; no shadow key — shadow is exempt from
#      ITER_EXPECTED_FIELDS, so a complete iter lacking shadow must still produce
#      no field warnings). The effectiveness-record warning is suppressed by
#      pre-creating the record so only field-validation output can appear. Guards
#      against an inverted set-difference operand that would pass missing-field
#      assertions while being wrong for the clean case.
LR_CLEAN="$(git_sandbox "lr self-check clean-workpad repo")"
git -C "$LR_CLEAN" init -q
LR_CLEAN_RUN="$LR_CLEAN/.prflow/tmp/review/pr-80/run-n"
mkdir -p "$LR_CLEAN_RUN"
# Pre-create the effectiveness record so the "was NOT persisted" warning is suppressed;
# only field-validation output can then appear.
mkdir -p "$LR_CLEAN/.prflow/logs/efficiency"
printf '{}' > "$LR_CLEAN/.prflow/logs/efficiency/pr-80-run-n.json"
# Every ITER_EXPECTED_FIELDS member present; no shadow key (shadow is exempt).
# The fixture carries `reference_reads` in its REAL (Step-3.5-written) verified shape
# (#541 review, pr-test-analyzer): the only records that otherwise exercise the field
# end-to-end are synthesized ones, so the ordinary gate-run path — a well-formed
# reference_reads on a NON-synthesized record, which --self-check must pass in silence —
# was asserted only by the field's absence. Carrying it here makes the zero-warning
# assertion below cover that path, and turns RED if the evidence-shape arm is ever
# widened past `.synthesized == true` "for symmetry" and starts warning on every
# ordinary iteration that ran the gate.
printf '%s' '{"iter":1,"started_at":"t","fix_commit_sha":"abc","fix_files":[],"loop_role":"fix","sweep_defs_read":[],"sweep_evidence":{"status":"not-run","reason":"no fixes applied"},"reference_reads":{"fix_delta":{"status":"verified","outcome":"clean","reason":null}},"checklist":[],"phase3_dispatched":3,"phase3_failed_agents":[],"expected_reviewers":[],"dispatched_effort":[],"diff_profile":"x","phase3_findings":[],"fix_decisions":[],"convergence_inputs":{},"cap_drops":[],"telemetry":{}}' \
  > "$LR_CLEAN_RUN/iter-1.json"
LR_CLEAN_OUT="$( ( cd "$LR_CLEAN" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_CLEAN_RUN" --slug pr-80 ) 2>&1 )"; LR_CLEAN_RC=$?
assert_eq "loop_role #177: --self-check exits 0 on a complete iter (all fields present)" "0" "$LR_CLEAN_RC"
assert_eq "loop_role #177: --self-check emits no field-validation warning on a complete iter (no ::warning:: on fields)" "0" \
  "$(printf '%s' "$LR_CLEAN_OUT" | grep -F '::warning::' | grep -cvF 'was NOT persisted' || true)"
# #541 CONSUMER cell for REAL (non-synthesized) records. The et-fresh(#541) consumer test
# covers only `synthesized: true` records, which route to ITER_SYNTH_EXPECTED_FIELDS — so
# without this, nothing asserted that --self-check warns when an ORDINARY iter record omits
# the two unconditional sweep fields, and the AC's "producer-consumer tests cover each
# evidence field" rested on the indirect LR_CONST==LR_SCHEMA divergence check alone.
# Reuses the same clean fixture with exactly the two fields deleted, so the run is otherwise
# valid and the warnings can only be attributed to their absence.
jq 'del(.sweep_defs_read, .sweep_evidence)' "$LR_CLEAN_RUN/iter-1.json" > "$LR_CLEAN_RUN/iter-2.json" 2>/dev/null
LR_MISS_OUT="$( ( cd "$LR_CLEAN" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_CLEAN_RUN" --slug pr-80 ) 2>&1 )"
for _f541r in sweep_defs_read sweep_evidence; do
  assert_eq "#541 consumer (real record): --self-check flags an ordinary iter missing $_f541r" "yes" \
    "$(printf '%s\n' "$LR_MISS_OUT" | grep -qF "iter-2.json' is missing expected field '$_f541r'" && echo yes || echo no)"
done
# #1904 CONSUMER cell: expected_reviewers is unconditional (mirrors phase3_dispatched),
# so --self-check must warn when an ordinary iter omits it. Reuse the complete fixture
# with exactly that field deleted so the warning can only be its absence.
jq 'del(.expected_reviewers)' "$LR_CLEAN_RUN/iter-1.json" > "$LR_CLEAN_RUN/iter-3.json" 2>/dev/null
LR_MISS_ER_OUT="$( ( cd "$LR_CLEAN" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$LR_CLEAN_RUN" --slug pr-80 ) 2>&1 )"
assert_eq "#1904 consumer (real record): --self-check flags an ordinary iter missing expected_reviewers" "yes" \
  "$(printf '%s\n' "$LR_MISS_ER_OUT" | grep -qF "iter-3.json' is missing expected field 'expected_reviewers'" && echo yes || echo no)"
rm -rf "$LR_CLEAN"

# (12) Mid-chain promotion: two consecutive promotions (iter-1 promotes, iter-2
#      also promotes, iter-3 follows). Expected roles: fix/promoted/promoted.
#      Locks the positional-prior indexing — an off-by-one (taking iter-1 as
#      prior for iter-3) would incorrectly derive promoted for iter-3.
LR_PP="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}'  > "$LR_PP/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}'  > "$LR_PP/iter-2.json"
printf '{"iter":3,"phase3_findings":[]}'                                           > "$LR_PP/iter-3.json"
LR_PP_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_PP" --slug pr-81 --mode record)"
assert_eq "loop_role #177: mid-chain double-promotion yields fix/promoted/promoted" "fix promoted promoted" \
  "$(printf '%s' "$LR_PP_REC" | jq -r '[.per_iteration[] | .loop_role] | join(" ")')"
rm -rf "$LR_PP"

# (13) Persisted "fix" suppresses a derived promotion: iter-2 has loop_role:"fix"
#      persisted AND a prior shadow_promoted=true — the persisted-wins rule must
#      honour the stored "fix", not override it with the derived "promoted". Mirror
#      of test (8) (persisted "promoted" survives a non-promoting prior).
LR_PF="$(mktemp -d)"
printf '{"iter":1,"phase3_findings":[],"shadow":{"promoted_to_iter_next":true}}' > "$LR_PF/iter-1.json"
printf '{"iter":2,"phase3_findings":[],"loop_role":"fix"}'                       > "$LR_PF/iter-2.json"
LR_PF_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$LR_PF" --slug pr-82 --mode record)"
assert_eq "loop_role #177: persisted 'fix' suppresses derived promotion (persisted-wins)" "fix" \
  "$(printf '%s' "$LR_PF_REC" | jq -r '.per_iteration[] | select(.iter==2) | .loop_role')"
rm -rf "$LR_PF"

# ────────────────────────────────────────────────────────────────────────────
echo "telemetry-branch persistence (issue #441)"
# ────────────────────────────────────────────────────────────────────────────
# The detached, working-tree-untouching persistence of observability artifacts to
# the dedicated `prflow-telemetry` orphan branch. The _et_on_branch / _et_show /
# _et_branch_count helpers are defined in the --persist block above.

# AC4: an EXISTING ref that is NOT a telemetry store (its tip holds non-.prflow/logs/
# paths) is breadcrumb-skipped — the write never commits onto it.
TB_NS_REPO="$(git_sandbox "tb non-telemetry branch repo")"
git -C "$TB_NS_REPO" init -q
git -C "$TB_NS_REPO" config user.email t@e.com; git -C "$TB_NS_REPO" config user.name t
mkdir -p "$TB_NS_REPO/.prflow"; printf 'tmp/\n' > "$TB_NS_REPO/.prflow/.gitignore"
printf 'x\n' > "$TB_NS_REPO/code.py"; git -C "$TB_NS_REPO" add -A; git -C "$TB_NS_REPO" commit -qm seed
git -C "$TB_NS_REPO" branch -M main
git -C "$TB_NS_REPO" branch prflow-telemetry main   # a same-named branch holding non-logs paths
TB_NS_TIP="$(git -C "$TB_NS_REPO" rev-parse prflow-telemetry)"
mkdir -p "$TB_NS_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_NS_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
TB_NS_ERR="$( ( cd "$TB_NS_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; TB_NS_RC=$?
assert_eq "tb(#441 AC4): non-telemetry same-named branch → exit 0 (best-effort)" "0" "$TB_NS_RC"
assert_eq "tb(#441 AC4): non-telemetry same-named branch is left UNTOUCHED (no commit onto it)" \
  "$TB_NS_TIP" "$(git -C "$TB_NS_REPO" rev-parse prflow-telemetry)"
assert_eq "tb(#441 AC4): the skip is breadcrumbed (never silent)" "yes" \
  "$(printf '%s' "$TB_NS_ERR" | grep -qF 'not a DevFlow telemetry store' && echo yes || echo no)"
rm -rf "$TB_NS_REPO"

# AC5: LOCAL compare-and-swap race twin — a sibling advances the ref between our
# `old` read and the update-ref; the retry rebuilds on the sibling's tip so BOTH
# runs' files survive with no lost commit. Driven by the DEVFLOW_TELEMETRY_RACE_HOOK
# test seam (a no-op in production; never a real dependency).
TB_CAS_REPO="$(git_sandbox "tb CAS race repo")"
git -C "$TB_CAS_REPO" init -q
git -C "$TB_CAS_REPO" config user.email t@e.com; git -C "$TB_CAS_REPO" config user.name t
mkdir -p "$TB_CAS_REPO/.prflow"; printf 'tmp/\n' > "$TB_CAS_REPO/.prflow/.gitignore"
git -C "$TB_CAS_REPO" add -A; git -C "$TB_CAS_REPO" commit -qm seed
# Seed the branch with run A so the race hook has a tip to advance.
mkdir -p "$TB_CAS_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_CAS_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
( cd "$TB_CAS_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
# Race hook: commits a SIBLING record (run-c) onto the ref tip, simulating a
# concurrent worktree writing between our `old` read and our update-ref.
TB_HOOK="$(mktemp)"; cat > "$TB_HOOK" <<'HOOK'
#!/usr/bin/env bash
root="$1"; ref="$2"
tip=$(git -C "$root" rev-parse "$ref")
b=$(printf '{"slug":"pr-3","run_id":"run-c"}' | git -C "$root" hash-object -w --stdin)
idx="$root/.git/racehookidx.$$"; export GIT_INDEX_FILE="$idx"
git -C "$root" read-tree "$tip"
git -C "$root" update-index --add --cacheinfo "100644,$b,.prflow/logs/efficiency/pr-3-run-c.json"
t=$(git -C "$root" write-tree); unset GIT_INDEX_FILE; rm -f "$idx"
n=$(GIT_AUTHOR_NAME=s GIT_AUTHOR_EMAIL=s@x GIT_COMMITTER_NAME=s GIT_COMMITTER_EMAIL=s@x git -C "$root" commit-tree "$t" -p "$tip" -m sibling)
git -C "$root" update-ref "$ref" "$n" "$tip"
HOOK
chmod +x "$TB_HOOK"
# Persist run B with the race hook active → first CAS fails (sibling C landed), retry
# rebuilds B on C's tip. All of A, B, C must survive.
mkdir -p "$TB_CAS_REPO/.prflow/tmp/review/pr-2/run-b"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_CAS_REPO/.prflow/tmp/review/pr-2/run-b/iter-1.json"
( cd "$TB_CAS_REPO" && DEVFLOW_TELEMETRY_RACE_HOOK="$TB_HOOK" bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$TB_CAS_REPO/.prflow/tmp/review/pr-2/run-b" --slug pr-2 ) >/dev/null 2>&1
assert_eq "tb(#441 AC5): CAS race — run A survives" "yes" \
  "$(_et_on_branch "$TB_CAS_REPO" ".prflow/logs/efficiency/pr-1-run-a.json")"
assert_eq "tb(#441 AC5): CAS race — the raced run B survives (retry rebuilt on the sibling tip)" "yes" \
  "$(_et_on_branch "$TB_CAS_REPO" ".prflow/logs/efficiency/pr-2-run-b.json")"
assert_eq "tb(#441 AC5): CAS race — the sibling C's commit is NOT lost (no clobber)" "yes" \
  "$(_et_on_branch "$TB_CAS_REPO" ".prflow/logs/efficiency/pr-3-run-c.json")"
rm -f "$TB_HOOK"; rm -rf "$TB_CAS_REPO"

# AC10: if a worktree currently has the telemetry branch checked out, the write
# degrades (breadcrumb-skip the ref advance) rather than corrupting that worktree.
TB_WT_REPO="$(git_sandbox "tb worktree-checkout repo")"
git -C "$TB_WT_REPO" init -q
git -C "$TB_WT_REPO" config user.email t@e.com; git -C "$TB_WT_REPO" config user.name t
mkdir -p "$TB_WT_REPO/.prflow"; printf 'tmp/\n' > "$TB_WT_REPO/.prflow/.gitignore"
git -C "$TB_WT_REPO" add -A; git -C "$TB_WT_REPO" commit -qm seed
mkdir -p "$TB_WT_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_WT_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
( cd "$TB_WT_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1   # creates the branch
TB_WT_TIP="$(git -C "$TB_WT_REPO" rev-parse prflow-telemetry)"
TB_WT_LINK="$(git_sandbox "tb worktree link parent")/wt"
git -C "$TB_WT_REPO" worktree add -q "$TB_WT_LINK" prflow-telemetry 2>/dev/null
mkdir -p "$TB_WT_REPO/.prflow/tmp/review/pr-2/run-b"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_WT_REPO/.prflow/tmp/review/pr-2/run-b/iter-1.json"
TB_WT_ERR="$( ( cd "$TB_WT_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$TB_WT_REPO/.prflow/tmp/review/pr-2/run-b" --slug pr-2 ) 2>&1 1>/dev/null )"; TB_WT_RC=$?
assert_eq "tb(#441 AC10): branch checked out in a worktree → exit 0" "0" "$TB_WT_RC"
assert_eq "tb(#441 AC10): branch checked out in a worktree → ref NOT advanced (worktree uncorrupted)" \
  "$TB_WT_TIP" "$(git -C "$TB_WT_REPO" rev-parse prflow-telemetry)"
assert_eq "tb(#441 AC10): worktree-checkout degrade is breadcrumbed" "yes" \
  "$(printf '%s' "$TB_WT_ERR" | grep -qF 'is checked out in a worktree' && echo yes || echo no)"
# #469 AC8: the worktree-checkout arm is a DEGRADED arm (persist_tree returns 1), so do_persist
# must RETAIN its staging root and emit the degraded RETAINING breadcrumb — not silently rm -rf
# the run's only copy. (This arm shares the AC8 fix with CAS/unwritable but had no retention
# assertion; a regression flipping its return 1 → return 0 would delete the copy undetected.)
assert_eq "#469 AC8: the worktree-checkout degraded arm RETAINS its staging root" "yes" \
  "$(compgen -G "$TB_WT_REPO/.prflow/tmp/telemetry-stage-*" >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "#469 AC8: the worktree-checkout degraded arm emits the RETAINING breadcrumb" "yes" \
  "$(printf '%s' "$TB_WT_ERR" | grep -qF 'RETAINING the staged records at' && echo yes || echo no)"
git -C "$TB_WT_REPO" worktree remove --force "$TB_WT_LINK" 2>/dev/null; rm -rf "$TB_WT_REPO" "$(dirname "$TB_WT_LINK")"

# AC12 (highest-value regression — silent dataset corruption): recorded_fix_shas
# reads prior runs' durable iter-*.json from the telemetry BRANCH, so a run already
# persisted there stays in the exclusion set and its fix commit is NEVER re-attributed
# to a later workpad-less synthesis pass.
TB_RA_REPO="$(git_sandbox "tb recorded_fix_shas branch-read repo")"
git -C "$TB_RA_REPO" init -q
git -C "$TB_RA_REPO" config user.email t@e.com; git -C "$TB_RA_REPO" config user.name t
mkdir -p "$TB_RA_REPO/.prflow"; printf 'tmp/\n' > "$TB_RA_REPO/.prflow/.gitignore"
git -C "$TB_RA_REPO" add -A; git -C "$TB_RA_REPO" commit -qm base; git -C "$TB_RA_REPO" branch -M main
git -C "$TB_RA_REPO" checkout -q -b feat
printf a > "$TB_RA_REPO/f1"; git -C "$TB_RA_REPO" add f1
git -C "$TB_RA_REPO" commit -qm "fix: address review findings (iteration 1)"
TB_RA_F1="$(git -C "$TB_RA_REPO" rev-parse HEAD)"
# Run A: a REAL workpad recording fix_commit_sha F1, persisted to the branch.
mkdir -p "$TB_RA_REPO/.prflow/tmp/review/pr-1/run-a"
printf '{"iter":1,"source":"review-and-fix","fix_commit_sha":"%s","fix_files":["f1"],"loop_role":"fix","phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":1},"telemetry":null}' "$TB_RA_F1" \
  > "$TB_RA_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
( cd "$TB_RA_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$TB_RA_REPO/.prflow/tmp/review/pr-1/run-a" --slug pr-1 ) >/dev/null 2>&1
# Teardown A's tmp scratch: only the BRANCH copy survives (the real-world case).
rm -rf "$TB_RA_REPO/.prflow/tmp/review/pr-1"
# Run B: a workpad-less dir. Synthesis must EXCLUDE F1 (already recorded on the branch
# by A) → B synthesizes nothing and breadcrumbs "already recorded by another run".
mkdir -p "$TB_RA_REPO/.prflow/tmp/review/pr-2/run-b"
TB_RA_ERR="$( ( cd "$TB_RA_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$TB_RA_REPO/.prflow/tmp/review/pr-2/run-b" --slug pr-2 ) 2>&1 1>/dev/null )"
assert_eq "tb(#441 AC12): a branch-persisted run's fix commit is excluded from a later synthesis (read from the branch)" "yes" \
  "$(printf '%s' "$TB_RA_ERR" | grep -qF 'already recorded by another run' && echo yes || echo no)"
assert_eq "tb(#441 AC12): run B synthesizes NO record (its only candidate commit was already recorded on the branch)" "no" \
  "$(_et_on_branch "$TB_RA_REPO" ".prflow/logs/efficiency/pr-2-run-b.json")"
rm -rf "$TB_RA_REPO"

# AC15 (positive path): --self-check reads the BRANCH, so after a successful --persist
# it must be SILENT on that same run (the branch-presence probe recognizes the record).
# The ETSC block above covers only the negative "was NOT persisted" case; a bug where
# blob_exists always returned false (the source-failure stub) would warn on every clean
# run and go uncaught without this.
TB_SC_REPO="$(git_sandbox "tb self-check positive repo")"
git -C "$TB_SC_REPO" init -q
git -C "$TB_SC_REPO" config user.email t@e.com; git -C "$TB_SC_REPO" config user.name t
mkdir -p "$TB_SC_REPO/.prflow"; printf 'tmp/\n' > "$TB_SC_REPO/.prflow/.gitignore"
git -C "$TB_SC_REPO" add -A; git -C "$TB_SC_REPO" commit -qm seed
TB_SC_RUN="$TB_SC_REPO/.prflow/tmp/review/pr-1/run-a"; mkdir -p "$TB_SC_RUN"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_SC_RUN/iter-1.json"
( cd "$TB_SC_REPO" && bash "$LIB/efficiency-trace.sh" --persist --workpad-dir "$TB_SC_RUN" --slug pr-1 ) >/dev/null 2>&1
TB_SC_OUT="$( ( cd "$TB_SC_REPO" && bash "$LIB/efficiency-trace.sh" --self-check --workpad-dir "$TB_SC_RUN" --slug pr-1 ) 2>&1 )"
assert_eq "tb(#441 AC15): self-check on a branch-persisted run is SILENT (no 'was NOT persisted')" "no" \
  "$(printf '%s' "$TB_SC_OUT" | grep -qF 'was NOT persisted' && echo yes || echo no)"
rm -rf "$TB_SC_REPO"

# Staged-path store-invariant guard: devflow_telemetry_persist_tree refuses to persist
# a staged path NOT under .prflow/logs/ (breadcrumb-skip, no ref created) — the
# by-construction defense keeping the branch tree logs-only.
TB_SP_REPO="$(git_sandbox "tb staged-path guard repo")"
git -C "$TB_SP_REPO" init -q
git -C "$TB_SP_REPO" config user.email t@e.com; git -C "$TB_SP_REPO" config user.name t
mkdir -p "$TB_SP_REPO/.prflow"; printf 'tmp/\n' > "$TB_SP_REPO/.prflow/.gitignore"
git -C "$TB_SP_REPO" add -A; git -C "$TB_SP_REPO" commit -qm seed
TB_SP_STAGE="$TB_SP_REPO/.prflow/tmp/stg"; mkdir -p "$TB_SP_STAGE/.prflow/other"
printf 'x\n' > "$TB_SP_STAGE/stray.txt"; printf 'y\n' > "$TB_SP_STAGE/.prflow/other/z.json"
# `set -euo pipefail` in the bash -c: the real caller (efficiency-trace.sh) runs under those
# options, and a fixture that omits them cannot surface a bash-3.2 empty-array abort — the
# exact shape of PR #442 review Critical-1. Drive the helper the way production drives it.
TB_SP_ERR="$( ( cd "$TB_SP_REPO" && DEVFLOW_CONFIG_FILE=/dev/null python3 - "$LIB/telemetry-branch.sh" "$TB_SP_REPO" "$TB_SP_STAGE" 2>&1 <<'PYEOF'
import subprocess,sys
lib,root,stage=sys.argv[1],sys.argv[2],sys.argv[3]
subprocess.run(["bash","-c",'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"','_',lib,root,stage],cwd=root)
PYEOF
) )"
assert_eq "tb(#441): a staged path not under .prflow/logs/ is refused (breadcrumb)" "yes" \
  "$(printf '%s' "$TB_SP_ERR" | grep -qF 'is not under .prflow/logs/' && echo yes || echo no)"
assert_eq "tb(#441): staged-path refusal creates NO telemetry ref" "no" \
  "$(git -C "$TB_SP_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
# PR #442 review (pr-test-analyzer): the fixture above stages ONLY non-conforming paths, so
# `conforming` ends up empty either way and the guard's FILTER-not-abort semantics — the very
# thing its comment says it is doing ("skipping just this path ... other conforming records
# still persist") — were never exercised. A regression replacing the per-path `case` filter
# with a whole-batch `return 0` passed every assertion above while silently discarding every
# OTHER run's telemetry in a batched discovery persist. Stage a stray path ALONGSIDE a
# conforming one and assert the conforming record still lands on the branch.
TB_SPM_STAGE="$TB_SP_REPO/.prflow/tmp/stgmix"
mkdir -p "$TB_SPM_STAGE/.prflow/logs/efficiency"
printf 'x\n' > "$TB_SPM_STAGE/stray.txt"
printf '{"slug":"pr-mix"}\n' > "$TB_SPM_STAGE/.prflow/logs/efficiency/pr-mix-run-1.json"
TB_SPM_ERR="$( ( cd "$TB_SP_REPO" && DEVFLOW_CONFIG_FILE=/dev/null python3 - "$LIB/telemetry-branch.sh" "$TB_SP_REPO" "$TB_SPM_STAGE" 2>&1 <<'PYEOF'
import subprocess,sys
lib,root,stage=sys.argv[1],sys.argv[2],sys.argv[3]
subprocess.run(["bash","-c",'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"','_',lib,root,stage],cwd=root)
PYEOF
) )"
assert_eq "tb(#442): a stray staged path is FILTERED, not aborting the batch (breadcrumb still fires)" "yes" \
  "$(printf '%s' "$TB_SPM_ERR" | grep -qF 'is not under .prflow/logs/' && echo yes || echo no)"
assert_eq "tb(#442): ...and the CONFORMING record staged alongside it still persists (filter-not-abort)" "yes" \
  "$(_et_on_branch "$TB_SP_REPO" ".prflow/logs/efficiency/pr-mix-run-1.json")"
assert_eq "tb(#442): ...and the stray path itself is NOT on the branch" "no" \
  "$(_et_on_branch "$TB_SP_REPO" "stray.txt")"
rm -rf "$TB_SP_REPO"

# AC4 hardening (SFH-4a): verify_store fails CLOSED when ls-tree cannot read a
# PRESENT ref's tree — an unverifiable store is breadcrumb-skipped, never appended
# onto (fail-open would treat an unreadable tree as an empty, safe store).
# BEHAVIORAL (PR #442 review Suggestion-2 — this replaces the former string-presence
# pin, which a regression flipping the arm to `return 0` would have survived): persist
# once so the ref exists with loose objects, then DELETE the tip's tree object from the
# object store. The commit object still resolves (so `rev-parse --verify` passes and the
# ref reads as PRESENT), but `ls-tree` cannot read the tree → the guard must refuse to
# append. Positive control below: the same fixture persists a SECOND run fine while the
# tree object is intact, so the refusal is attributable to the unreadable tree and not to
# some unrelated precondition of the fixture.
TB_UT_REPO="$(git_sandbox "tb unreadable-tree repo")"
git -C "$TB_UT_REPO" init -q
git -C "$TB_UT_REPO" config user.email t@e.com; git -C "$TB_UT_REPO" config user.name t
mkdir -p "$TB_UT_REPO/.prflow"; printf 'tmp/\n' > "$TB_UT_REPO/.prflow/.gitignore"
git -C "$TB_UT_REPO" add -A; git -C "$TB_UT_REPO" commit -qm seed
mkdir -p "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
( cd "$TB_UT_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
# Positive control: with the store readable, a SECOND run appends normally.
mkdir -p "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-b"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-b/iter-1.json"
( cd "$TB_UT_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "tb(#441 SFH-4a): positive control — a readable store DOES accept the append" "yes" \
  "$(git -C "$TB_UT_REPO" cat-file -e refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-1-run-b.json >/dev/null 2>&1 && echo yes || echo no)"
# Now break the tip TREE object (the commit stays readable → ref still PRESENT).
TB_UT_TREE="$(git -C "$TB_UT_REPO" rev-parse "refs/heads/prflow-telemetry^{tree}")"
TB_UT_TIP="$(git -C "$TB_UT_REPO" rev-parse refs/heads/prflow-telemetry)"
rm -f "$TB_UT_REPO/.git/objects/${TB_UT_TREE:0:2}/${TB_UT_TREE:2}"
mkdir -p "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-c"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_UT_REPO/.prflow/tmp/review/pr-1/run-c/iter-1.json"
TB_UT_ERR="$( ( cd "$TB_UT_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; TB_UT_RC=$?
assert_eq "tb(#441 SFH-4a): unreadable present-ref tree → exit 0 (best-effort)" "0" "$TB_UT_RC"
assert_eq "tb(#441 SFH-4a): verify_store FAILS CLOSED on an unreadable present-ref tree (breadcrumb names the refusal)" "yes" \
  "$(printf '%s' "$TB_UT_ERR" | grep -qF 'cannot verify it is a telemetry store, refusing to append' && echo yes || echo no)"
assert_eq "tb(#441 SFH-4a): the ref is NOT advanced when the store cannot be verified" "$TB_UT_TIP" \
  "$(git -C "$TB_UT_REPO" rev-parse refs/heads/prflow-telemetry)"
# Attribution: the refusal must be TERMINAL — the write never even reaches the object
# store. This is what distinguishes fail-CLOSED from fail-OPEN: a mutation flipping the
# guard's `return 1` to `return 0` (breadcrumb intact) still ends with no ref advance,
# because the unreadable tree then breaks `read-tree` — but it gets there by ATTEMPTING
# the write, which surfaces the "object-store write failed" breadcrumb. Asserting that
# breadcrumb's ABSENCE is what makes this test go RED under the fail-open mutation.
assert_eq "tb(#441 SFH-4a): the refusal is terminal — persist never attempts the object-store write" "no" \
  "$(printf '%s' "$TB_UT_ERR" | grep -qF 'object-store write failed' && echo yes || echo no)"
# #469 AC8 (shadow review): the verify_store-fail arm is a DEGRADED arm that produced a staging
# root, so #469 changed its guard from `|| return 0` to `|| return 1` — do_persist must therefore
# RETAIN the staged records (they are the run's only copy), not rm -rf them. The assertions above
# (exit 0 / refusal breadcrumb / no ref advance / no object-store write) are all invariant to a
# return-1→return-0 flip — that flip makes persist_tree return 0, do_persist hit its clean `0)`
# arm, and SILENTLY DELETE the staged records (the exact #469 defect-4 regression) while every
# assertion above stays green. So pin the retention outcome directly, which return 0 breaks.
assert_eq "tb(#469 AC8): the verify_store-fail degraded arm RETAINS its staging root (persist_tree return 1, not 0)" "yes" \
  "$(compgen -G "$TB_UT_REPO/.prflow/tmp/telemetry-stage-*" >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "tb(#469 AC8): the verify_store-fail arm emits do_persist's degraded RETAINING breadcrumb (the only copy is kept)" "yes" \
  "$(printf '%s' "$TB_UT_ERR" | grep -qF 'RETAINING the staged records at' && echo yes || echo no)"
rm -rf "$TB_UT_REPO"

# PR #442 review Suggestion-3: the CAS **non-race** failure arm (a held ref `.lock`, a
# read-only `.git`, ENOSPC) deliberately emits a DIFFERENT terminal breadcrumb than the
# "lost N races" one, so an operator is not sent hunting phantom concurrency. Only the
# race arm was exercised (TB_CAS above); drive the non-race arm by pre-creating the ref's
# `.lock` file so `git update-ref` fails with a lock error whose stderr carries no
# `but expected` (the race discriminator).
TB_LK_REPO="$(git_sandbox "tb ref-lock repo")"
git -C "$TB_LK_REPO" init -q
git -C "$TB_LK_REPO" config user.email t@e.com; git -C "$TB_LK_REPO" config user.name t
mkdir -p "$TB_LK_REPO/.prflow"; printf 'tmp/\n' > "$TB_LK_REPO/.prflow/.gitignore"
git -C "$TB_LK_REPO" add -A; git -C "$TB_LK_REPO" commit -qm seed
mkdir -p "$TB_LK_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_LK_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
mkdir -p "$TB_LK_REPO/.git/refs/heads"
: > "$TB_LK_REPO/.git/refs/heads/prflow-telemetry.lock"   # a stale/held ref lock
TB_LK_ERR="$( ( cd "$TB_LK_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; TB_LK_RC=$?
assert_eq "tb(#442 Sug-3): held ref .lock → exit 0 (best-effort)" "0" "$TB_LK_RC"
# The breadcrumb no longer claims "NOT a concurrent writer" (PR #442 review): a held
# `<ref>.lock` IS another git process — git's own captured text on the same line says
# "Another git process seems to be running" — so that absolute contradicted the evidence
# printed beside it. The accurate claim is the OBSERVABLE one: the ref never moved across
# the bounded attempts. Pin that, plus the causes it names.
assert_eq "tb(#442 Sug-3): held ref .lock takes the NON-race arm (names the lock/permission/disk cause)" "yes" \
  "$(printf '%s' "$TB_LK_ERR" | grep -qF 'a held ref .lock (another git process)' && echo yes || echo no)"
assert_eq "tb(#442 Sug-3): ...and the breadcrumb states the OBSERVABLE fact (the ref never moved)" "yes" \
  "$(printf '%s' "$TB_LK_ERR" | grep -qF 'never moved' && echo yes || echo no)"
assert_eq "tb(#442 Sug-3): ...and does NOT assert 'NOT a concurrent writer' (a held lock IS one)" "no" \
  "$(printf '%s' "$TB_LK_ERR" | grep -qF 'NOT a concurrent writer' && echo yes || echo no)"
assert_eq "tb(#442 Sug-3): held ref .lock is NOT misdiagnosed as a lost CAS race" "no" \
  "$(printf '%s' "$TB_LK_ERR" | grep -qF 'lost 5 races' && echo yes || echo no)"
assert_eq "tb(#442 Sug-3): held ref .lock → no telemetry ref created" "no" \
  "$(git -C "$TB_LK_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$TB_LK_REPO"

# AC8 (PR #442 review Suggestion-4): a persist on a checkout with NO configured committer
# identity still writes, because the helper exports its OWN GIT_AUTHOR/COMMITTER identity
# into `commit-tree` — so a passing persist must attribute to that exported identity, not
# to an ambient host fallback.
#
# issue #575: `user.useConfigOnly=true` stops git from *auto-detecting* an identity from
# gecos/hostname, but it does NOT stop git from reading GLOBAL config, SYSTEM config, or the
# GIT_{AUTHOR,COMMITTER}_{NAME,EMAIL} environment variables. The old empty-commit "positive
# control" therefore gave a FALSE suite failure on any host whose global/system config (or
# inherited identity vars) supplied an identity. This block instead:
#   (1) proves each identity source is individually effective — a positive-control matrix that
#       activates each identity source (system config, global config, inherited identity vars,
#       command-scope config) in turn, each row enabling its own source and disabling every other
#       (the inherited-vars source carries an extra row proving committer resolution, AC2);
#   (2) isolates every source for the negative probe and asserts, via git's own identity-
#       resolution command `git var` (not version-dependent commit diagnostics), that neither
#       author nor committer identity resolves; and
#   (3) runs every identity-sensitive check under a HOSTILE outer environment (synthetic global
#       config, inherited identity vars, command-scope config incl. GIT_CONFIG_PARAMETERS, and
#       GIT_CONFIG_NOSYSTEM=1), so the suite result no longer depends on the host's git identity.
#       The fixture is BUILT before that subshell opens, so any identity-sensitive setup step
#       must isolate itself (the seed commit below does) rather than rely on the subshell.
TB_ID_REPO="$(git_sandbox "tb no-identity repo")"
git -C "$TB_ID_REPO" init -q
git -C "$TB_ID_REPO" config user.useConfigOnly true   # no local user.name / user.email at all
mkdir -p "$TB_ID_REPO/.prflow"; printf 'tmp/\n' > "$TB_ID_REPO/.prflow/.gitignore"
git -C "$TB_ID_REPO" add -A
# AC6: the seed commit stays deterministic via ONE-SHOT identity (never the host's). The `env -u`
# is load-bearing, NOT decoration: GIT_AUTHOR_*/GIT_COMMITTER_* outrank EVERY config scope,
# including `-c`, so on a host exporting them the `-c` pair would be a mere success-fallback and
# the commit would attribute to the host. Unsetting them is what makes "never the host's" true.
# The ambient SeedHostile pair is staged deliberately so the assertion below is DISCRIMINATING:
# drop the `env -u` and the seed attributes to SeedHostile and the assertion goes RED.
GIT_AUTHOR_NAME=SeedHostile GIT_AUTHOR_EMAIL=seed-hostile@e.com \
GIT_COMMITTER_NAME=SeedHostile GIT_COMMITTER_EMAIL=seed-hostile@e.com \
  env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
  git -C "$TB_ID_REPO" -c user.email=seed@e.com -c user.name=seed commit -qm seed
assert_eq "tb(#575 AC6): the seed commit attributes to its ONE-SHOT identity, not an ambient one" \
  "seed <seed@e.com>" "$(git -C "$TB_ID_REPO" log -1 --format='%an <%ae>' 2>/dev/null)"

# Synthetic per-source identity files, each carrying a DISTINCT identity so a matrix row
# proves its source (and only its source) resolved.
# `mktemp` is not preflight-guaranteed, so allocate fail-closed with a NAMED diagnostic. Without
# the guard an allocation failure leaves the var empty and the `printf` below writes nothing; git
# then reads the empty GIT_CONFIG_* path as "no such config file" (NOT as unset — an unset value
# would fall back to the host's real ~/.gitconfig, so empty is the safer of the two), and the
# fixture a row depends on is silently absent. That already fails CLOSED — a matrix row resolves
# the wrong identity and goes RED — so this guard buys a clear "could not allocate" message
# instead of a confusing identity mismatch several hundred lines later, not closure of a
# fail-open. The persistence assertions' hostility comes from the exported identity VARS below,
# not from these files, so they stay discriminating either way.
TB_SYS_CFG="$(mktemp)"  || { echo "run.sh(#575): could not allocate the system-source identity fixture" >&2; exit 1; }
printf '[user]\n\tname = SysName\n\temail = sys@e.com\n'   > "$TB_SYS_CFG"
TB_GLOB_CFG="$(mktemp)" || { echo "run.sh(#575): could not allocate the global-source identity fixture" >&2; exit 1; }
printf '[user]\n\tname = GlobName\n\temail = glob@e.com\n' > "$TB_GLOB_CFG"
# The HOSTILE outer environment (AC5/AC9): identity files a contributor's host would supply.
# Distinct from the per-source files above so a leak would be visible.
TB_HOSTILE_GLOB="$(mktemp)" || { echo "run.sh(#575): could not allocate the hostile global identity fixture" >&2; exit 1; }
printf '[user]\n\tname = HostileGlobal\n\temail = hostile-glob@e.com\n' > "$TB_HOSTILE_GLOB"
TB_HOSTILE_SYS="$(mktemp)"  || { echo "run.sh(#575): could not allocate the hostile system identity fixture" >&2; exit 1; }
printf '[user]\n\tname = HostileSystem\n\temail = hostile-sys@e.com\n'  > "$TB_HOSTILE_SYS"

# AC5/AC9: run the identity-sensitive block under a hostile invoking environment — a global config
# file that resolves identity, inherited author/committer vars, BOTH command-scope channels
# (GIT_CONFIG_COUNT and GIT_CONFIG_PARAMETERS), and an inherited GIT_CONFIG_NOSYSTEM=1 that each
# system-config row clears with `env -u` to reach system config. Because that
# NOSYSTEM=1 is in force, TB_HOSTILE_SYS never resolves anywhere in this block — it is an inert
# distinct-valued placeholder, not an active hostile source. Its only purpose is attribution: if a
# future edit ever made system config reachable here, the leaked value would name its own origin.
# The block's own per-check isolation is what keeps the suite green under this hostility.
(
  export GIT_CONFIG_GLOBAL="$TB_HOSTILE_GLOB"
  export GIT_CONFIG_SYSTEM="$TB_HOSTILE_SYS"
  export GIT_CONFIG_NOSYSTEM=1
  export GIT_AUTHOR_NAME=HostileAuthor GIT_AUTHOR_EMAIL=hostile-author@e.com
  export GIT_COMMITTER_NAME=HostileCommitter GIT_COMMITTER_EMAIL=hostile-committer@e.com
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=HostileCmd
  # GIT_CONFIG_PARAMETERS is git's OTHER command-scope channel and it OUTRANKS
  # GIT_CONFIG_COUNT/KEY_n/VALUE_n. Exporting it hostilely here is what makes the
  # `-u GIT_CONFIG_PARAMETERS` flag load-bearing on every row whose identity comes from CONFIG —
  # every row whose identity comes from CONFIG rather than from the identity variables, and the
  # negative probes: drop the flag there and
  # the row resolves ParamLeak and goes RED. On the inherited-VARIABLE rows the flag is
  # symmetry/defence-in-depth rather than load-bearing, because their own GIT_AUTHOR_*/
  # GIT_COMMITTER_* outrank every config scope and win over ParamLeak regardless.
  export GIT_CONFIG_PARAMETERS="'user.name=ParamLeak' 'user.email=param-leak@e.com'"

  # leading name and email fields of a `git var *_IDENT` line; yields "Name <email>" ONLY for
  # SINGLE-TOKEN names — every fixture identity in this block is deliberately one word. A
  # multi-word name would split across _n/_e and mis-compare (loudly). Builtins only.
  _id2() { read -r _n _e _rest; printf '%s %s' "$_n" "$_e"; }

  # ── Matrix row: SYSTEM config only (AC1/AC3) ──
  # Enable system by UNSETTING the inherited GIT_CONFIG_NOSYSTEM=1 and pointing GIT_CONFIG_SYSTEM
  # at our file; disable global (/dev/null), inherited vars (unset), command-scope (unset). That
  # the row resolves SysName once NOSYSTEM is unset — under an outer env that sets it — is the
  # AC3 demonstration. (`GIT_CONFIG_NOSYSTEM=0` would also work — git parses it as a bool, so any
  # bool-false value re-enables system config — but unsetting keeps this row's isolation uniform
  # with its siblings, which all clear competing sources with `env -u` rather than by re-valuing.)
  TB_M_SYS="$( env -u GIT_CONFIG_NOSYSTEM \
        -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
        -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM="$TB_SYS_CFG" \
        git -C "$TB_ID_REPO" var GIT_AUTHOR_IDENT 2>/dev/null | _id2 )"
  assert_eq "tb(#575 AC1/AC3): system-config row resolves its own identity (inherited NOSYSTEM=1, row unsets it)" \
    "SysName <sys@e.com>" "$TB_M_SYS"

  # ── Matrix row: GLOBAL config only (AC1) ──
  TB_M_GLOB="$( env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
        -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL="$TB_GLOB_CFG" GIT_CONFIG_SYSTEM=/dev/null \
        git -C "$TB_ID_REPO" var GIT_AUTHOR_IDENT 2>/dev/null | _id2 )"
  assert_eq "tb(#575 AC1): global-config row resolves its own identity" \
    "GlobName <glob@e.com>" "$TB_M_GLOB"

  # ── Matrix row: inherited identity VARIABLES only (AC1/AC2 — distinct author vs committer) ──
  TB_M_VAR_A="$( env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        GIT_AUTHOR_NAME=VarAuthor GIT_AUTHOR_EMAIL=var-author@e.com \
        GIT_COMMITTER_NAME=VarCommitter GIT_COMMITTER_EMAIL=var-committer@e.com \
        git -C "$TB_ID_REPO" var GIT_AUTHOR_IDENT 2>/dev/null | _id2 )"
  assert_eq "tb(#575 AC1/AC2): inherited-variable row resolves its author identity" \
    "VarAuthor <var-author@e.com>" "$TB_M_VAR_A"
  TB_M_VAR_C="$( env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        GIT_AUTHOR_NAME=VarAuthor GIT_AUTHOR_EMAIL=var-author@e.com \
        GIT_COMMITTER_NAME=VarCommitter GIT_COMMITTER_EMAIL=var-committer@e.com \
        git -C "$TB_ID_REPO" var GIT_COMMITTER_IDENT 2>/dev/null | _id2 )"
  assert_eq "tb(#575 AC2): inherited-variable row resolves a DISTINCT committer identity" \
    "VarCommitter <var-committer@e.com>" "$TB_M_VAR_C"

  # ── Matrix row: command-scope config only (AC1) ──
  # `-u GIT_CONFIG_PARAMETERS` is required here exactly as in the sibling rows above: it is the
  # higher-precedence command-scope channel, so without this flag the outer hostile ParamLeak
  # value beats this row's own GIT_CONFIG_KEY_n/VALUE_n and the row asserts the wrong source.
  TB_M_CMD="$( env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
        -u GIT_CONFIG_PARAMETERS \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=CmdName \
        GIT_CONFIG_KEY_1=user.email GIT_CONFIG_VALUE_1=cmd@e.com \
        git -C "$TB_ID_REPO" var GIT_AUTHOR_IDENT 2>/dev/null | _id2 )"
  assert_eq "tb(#575 AC1): command-scope config row resolves its own identity" \
    "CmdName <cmd@e.com>" "$TB_M_CMD"

  # ── Negative probe (AC4): isolate every environment and config-file source; neither author nor
  # committer resolves. This replaces the old empty-commit "positive control", which relied on
  # version-dependent commit diagnostics and leaked host identity.
  # LOCAL repo config is the one source the probe does NOT isolate — the fixture does, by setting
  # user.useConfigOnly=true and never writing a local user.name/user.email (that same option also
  # blocks git's gecos/hostname fallback). Do not add local identity to TB_ID_REPO: the
  # negative-probe checks below would flip to `resolved`, with nothing to warn you.
  # `-u EMAIL` is belt-and-braces rather than load-bearing while useConfigOnly is in force (that
  # option blocks the $EMAIL fallback too) — but it is what keeps this probe from depending on
  # useConfigOnly for a channel it can isolate directly, so removing useConfigOnly can no longer
  # turn a contributor's exported EMAIL into a host-dependent false failure here.
  # AC4 unsets NOSYSTEM/COUNT/PARAMETERS + the four identity vars, and also unsets the inherited
  # command-scope KEY_0/VALUE_0, so command-scope is isolated by the probe itself. (It would also
  # have been incidentally safe — COUNT is unset and the outer hostile KEY_0 carries no email —
  # but the probe deliberately does not rely on that.)
  # Assert git's OWN identity-unknown exit status (128), not merely "non-zero": `env` is not
  # preflight-guaranteed, and a missing `env` exits 127 — which a bare non-zero test would score
  # as "identity did not resolve" while `git var` never ran at all, the vacuous-negative shape.
  # This discriminates on an EXIT CODE, deliberately not on git's diagnostic TEXT: matching the
  # message is the version-dependent coupling issue #575 removed from this fixture.
  TB_NEG_A_RC=0
  env -u GIT_CONFIG_NOSYSTEM -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL -u EMAIL \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        git -C "$TB_ID_REPO" var GIT_AUTHOR_IDENT >/dev/null 2>&1 || TB_NEG_A_RC=$?
  assert_eq "tb(#575 AC4): isolated negative probe — author identity does NOT resolve (git rc 128, not a harness rc)" \
    "128" "$TB_NEG_A_RC"
  TB_NEG_C_RC=0
  env -u GIT_CONFIG_NOSYSTEM -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL -u EMAIL \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        git -C "$TB_ID_REPO" var GIT_COMMITTER_IDENT >/dev/null 2>&1 || TB_NEG_C_RC=$?
  assert_eq "tb(#575 AC4): isolated negative probe — committer identity does NOT resolve (git rc 128, not a harness rc)" \
    "128" "$TB_NEG_C_RC"

  # ── Persistence under the hostile outer environment (AC5/AC7) ──
  mkdir -p "$TB_ID_REPO/.prflow/tmp/review/pr-1/run-a"
  printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
    > "$TB_ID_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
  ( cd "$TB_ID_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
  assert_eq "tb(#441 AC8 / #575 AC5): persist SUCCEEDS under a hostile identity env (record on the branch)" "yes" \
    "$(git -C "$TB_ID_REPO" cat-file -e refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-1-run-a.json >/dev/null 2>&1 && echo yes || echo no)"
  # Both halves the helper exports are checked. Committer alone would stay green if the helper
  # dropped its GIT_AUTHOR_* pair, since the hostile HostileAuthor would then be inherited —
  # which is precisely what makes the author assertion discriminating rather than redundant.
  assert_eq "tb(#441 AC8 / #575 AC7): the telemetry commit carries the helper's explicit committer identity" "github-actions[bot]" \
    "$(git -C "$TB_ID_REPO" log -1 --format='%cn' refs/heads/prflow-telemetry 2>/dev/null)"
  assert_eq "tb(#441 AC8 / #575 AC7): the telemetry commit carries the helper's explicit AUTHOR identity" "github-actions[bot]" \
    "$(git -C "$TB_ID_REPO" log -1 --format='%an' refs/heads/prflow-telemetry 2>/dev/null)"

  # ── Persistence with NO resolvable identity at all (the original #441 AC8 property) ──
  # The hostile-env arm above proves the helper's identity WINS over an ambient one; it cannot
  # prove the helper supplies one at all, because a helper that exported nothing would still
  # commit successfully by inheriting the hostile vars. This arm restores the original property:
  # under the AC4 isolation (where `git var` resolves nothing), the persist must STILL write.
  mkdir -p "$TB_ID_REPO/.prflow/tmp/review/pr-1/run-b"
  printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
    > "$TB_ID_REPO/.prflow/tmp/review/pr-1/run-b/iter-1.json"
  ( cd "$TB_ID_REPO" && env -u GIT_CONFIG_NOSYSTEM -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_PARAMETERS \
        -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL -u EMAIL \
        GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
        bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
  assert_eq "tb(#441 AC8 / #575 AC5): persist SUCCEEDS on an identity-LESS checkout (helper supplies its own)" "yes" \
    "$(git -C "$TB_ID_REPO" cat-file -e refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-1-run-b.json >/dev/null 2>&1 && echo yes || echo no)"

  # Arrival sentinel: every assertion above lives in this subshell, which runs without `set -e`
  # but under `set -u`. An early abort (an unbound-variable expansion) records ZERO FAILs and
  # would leave the suite green with the whole #575 block silently unexecuted. Writing a sentinel
  # as the LAST in-subshell statement, and asserting it from OUTSIDE, is what turns that silence
  # into a visible failure — an in-subshell assertion could not, because an early abort simply
  # never reaches it and a never-run assertion records nothing at all.
  printf 'reached\n' > "$TB_ID_REPO/block-complete"
)
assert_eq "tb(#575): the identity-matrix block ran to completion (subshell did not abort early)" "reached" \
  "$(<"$TB_ID_REPO/block-complete")"
rm -f "$TB_SYS_CFG" "$TB_GLOB_CFG" "$TB_HOSTILE_GLOB" "$TB_HOSTILE_SYS"
rm -rf "$TB_ID_REPO"

TB_CFG_REPO="$(git_sandbox "tb config override repo")"
git -C "$TB_CFG_REPO" init -q
git -C "$TB_CFG_REPO" config user.email t@e.com; git -C "$TB_CFG_REPO" config user.name t
mkdir -p "$TB_CFG_REPO/.prflow"; printf 'tmp/\n' > "$TB_CFG_REPO/.prflow/.gitignore"
printf '{"telemetry":{"branch":"my-telem"}}' > "$TB_CFG_REPO/.prflow/config.json"
git -C "$TB_CFG_REPO" add -A; git -C "$TB_CFG_REPO" commit -qm seed
mkdir -p "$TB_CFG_REPO/.prflow/tmp/review/pr-1/run-a"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_CFG_REPO/.prflow/tmp/review/pr-1/run-a/iter-1.json"
( cd "$TB_CFG_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "tb(#441 AC18): telemetry.branch override routes the write to the named branch" "yes" \
  "$(git -C "$TB_CFG_REPO" cat-file -e refs/heads/my-telem:.prflow/logs/efficiency/pr-1-run-a.json >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "tb(#441 AC18): the default-named branch is NOT created when the key is overridden" "no" \
  "$(git -C "$TB_CFG_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$TB_CFG_REPO"

# AC16/AC17: the retrospective reader UNIONS the telemetry-branch records with any
# legacy tracked .prflow/logs/, keyed (slug,run-id) branch-wins; and degrades to the
# legacy archive alone when the branch is absent.
TB_RD_REPO="$(git_sandbox "tb reader-union repo")"
git -C "$TB_RD_REPO" init -q
git -C "$TB_RD_REPO" config user.email t@e.com; git -C "$TB_RD_REPO" config user.name t
mkdir -p "$TB_RD_REPO/.prflow/logs/efficiency"; printf 'tmp/\n' > "$TB_RD_REPO/.prflow/.gitignore"
printf '{"slug":"pr-1","run_id":"runA","iterations":1}' > "$TB_RD_REPO/.prflow/logs/efficiency/pr-1-runA.json"
printf '{"slug":"pr-1","run_id":"runX","iterations":999}' > "$TB_RD_REPO/.prflow/logs/efficiency/pr-1-runX.json"
git -C "$TB_RD_REPO" add -A; git -C "$TB_RD_REPO" commit -qm seed
# Legacy-only (branch absent, AC17):
TB_RD_LEGACY="$(python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' "$LIB/../scripts/build-experiment-records.py" "$TB_RD_REPO" 2>/dev/null)"
assert_eq "tb(#441 AC17): reader degrades to the legacy archive alone when the branch is absent" \
  "[('runA', 1), ('runX', 999)]" "$TB_RD_LEGACY"
# Now persist a branch record for pr-1/runX with a DIFFERENT value + a new pr-2/runB.
TB_RD_STAGE="$TB_RD_REPO/.prflow/tmp/st"; mkdir -p "$TB_RD_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-1","run_id":"runX","iterations":5}' > "$TB_RD_STAGE/.prflow/logs/efficiency/pr-1-runX.json"
printf '{"slug":"pr-2","run_id":"runB","iterations":7}' > "$TB_RD_STAGE/.prflow/logs/efficiency/pr-2-runB.json"
( cd "$TB_RD_REPO" && DEVFLOW_CONFIG_FILE=/dev/null python3 - "$LIB/../lib/telemetry-branch.sh" "$TB_RD_REPO" "$TB_RD_STAGE" >/dev/null 2>&1 <<'PYEOF' || true
import subprocess,sys
lib,root,stage=sys.argv[1],sys.argv[2],sys.argv[3]
subprocess.run(["bash","-c",'. "$1"; devflow_telemetry_persist_tree "$2" "$3"','_',lib,root,stage],cwd=root)
PYEOF
)
TB_RD_UNION="$(python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' "$LIB/../scripts/build-experiment-records.py" "$TB_RD_REPO" 2>/dev/null)"
# runA legacy-only kept; runX BRANCH-wins (5, not 999); runB branch-only added — each (slug,run-id) exactly once.
assert_eq "tb(#441 AC16): reader unions legacy+branch, branch-wins by (slug,run-id), no double-count" \
  "[('runA', 1), ('runB', 7), ('runX', 5)]" "$TB_RD_UNION"
rm -rf "$TB_RD_REPO"

# Malformed telemetry-branch blob (cloud-review Suggestion-3e): a non-JSON blob on
# the branch must be SKIPPED with a breadcrumb, not crash the reader — the branch
# read path gets the same tolerance the legacy working-tree path already has.
TB_MB_REPO="$(git_sandbox "tb malformed branch blob repo")"
git -C "$TB_MB_REPO" init -q
git -C "$TB_MB_REPO" config user.email t@e.com; git -C "$TB_MB_REPO" config user.name t
mkdir -p "$TB_MB_REPO/.prflow"; printf 'tmp/\n' > "$TB_MB_REPO/.prflow/.gitignore"
git -C "$TB_MB_REPO" add -A; git -C "$TB_MB_REPO" commit -qm seed
# Stage one good record + one malformed (non-JSON) blob and persist both to the branch.
TB_MB_STAGE="$TB_MB_REPO/.prflow/tmp/st"; mkdir -p "$TB_MB_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-1","run_id":"good","iterations":3}' > "$TB_MB_STAGE/.prflow/logs/efficiency/pr-1-good.json"
printf 'not json at all {' > "$TB_MB_STAGE/.prflow/logs/efficiency/pr-1-bad.json"
( cd "$TB_MB_REPO" && DEVFLOW_CONFIG_FILE=/dev/null python3 - "$LIB/telemetry-branch.sh" "$TB_MB_REPO" "$TB_MB_STAGE" >/dev/null 2>&1 <<'PYEOF'
import subprocess,sys
lib,root,stage=sys.argv[1],sys.argv[2],sys.argv[3]
subprocess.run(["bash","-c",'. "$1"; devflow_telemetry_persist_tree "$2" "$3"','_',lib,root,stage],cwd=root)
PYEOF
)
TB_MB_OUT="$(python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' "$LIB/../scripts/build-experiment-records.py" "$TB_MB_REPO" 2>/dev/null)"
TB_MB_RC=$?
assert_eq "tb(#441 Sug-3e): reader does NOT crash on a malformed telemetry-branch blob" "0" "$TB_MB_RC"
assert_eq "tb(#441 Sug-3e): reader skips the malformed branch blob, keeps the good one" "[('good', 3)]" "$TB_MB_OUT"

# PR #442 review Suggestion-1: a record that PARSES but is not a slug-bearing object
# (a list, a scalar, an object with a non-string `slug`) was dropped SILENTLY. On the
# now-authoritative branch store a dropped record is a LOST measurement, so producer-schema
# drift must be breadcrumbed like an unparseable one. Positive control: the well-formed
# sibling in the same directory still indexes, so the warning attributes to the drifted
# record and not to a broken fixture.
TB_DR_DIR="$(mktemp -d)"
printf '{"slug":"pr-9","iterations":2}' > "$TB_DR_DIR/pr-9-good.json"
printf '[1, 2, 3]'                      > "$TB_DR_DIR/pr-9-drift.json"
TB_DR_ERR="$(python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_DR_DIR" 2>&1 >/dev/null)"
TB_DR_OUT="$(python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_DR_DIR" 2>/dev/null)"
assert_eq "tb(#442 Sug-1): a parseable-but-schema-drifted record is WARNED, not silently dropped" "yes" \
  "$(printf '%s' "$TB_DR_ERR" | grep -qF 'skipping malformed efficiency record' && echo yes || echo no)"
assert_eq "tb(#442 Sug-1): positive control — the well-formed sibling still indexes" "[('good', 2)]" "$TB_DR_OUT"
rm -rf "$TB_DR_DIR"

# PR #442 review Important-1: the branch-presence probe must not launder an UNESTABLISHED
# answer into a measured absence. `git rev-parse --verify --quiet` exits 0 (present) or 1
# (absent); any other rc — 128 (not a repo) or 127 (git unresolvable: absent binary, a
# broken DEVFLOW_GIT override, a non-executable shim, which the reader's _run synthesizes
# from an OSError) — means the store could not be READ, and folding it onto the absent arm
# would let the downstream provenance stamp `efficiency: absent` on a run whose telemetry
# merely could not be read. Drive it with an unresolvable DEVFLOW_GIT: the reader must WARN
# and still return the legacy archive (best-effort), never a silent "branch absent".
TB_GX_REPO="$(git_sandbox "tb git-unresolvable reader repo")"
mkdir -p "$TB_GX_REPO/.prflow/logs/efficiency"
printf '{"slug":"pr-9","iterations":4}' > "$TB_GX_REPO/.prflow/logs/efficiency/pr-9-legacy.json"
TB_GX_ERR="$(DEVFLOW_GIT="$TB_GX_REPO/no-such-git" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_GX_REPO" 2>&1 >/dev/null)"
TB_GX_OUT="$(DEVFLOW_GIT="$TB_GX_REPO/no-such-git" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_GX_REPO" 2>/dev/null)"
assert_eq "tb(#442 Imp-1): an unresolvable git makes the branch presence UNESTABLISHED (warned, never silent absence)" "yes" \
  "$(printf '%s' "$TB_GX_ERR" | grep -qF 'could not establish whether telemetry branch' && echo yes || echo no)"
assert_eq "tb(#442 Imp-1): the reader still degrades to the legacy archive (best-effort, no crash)" "[('legacy', 4)]" "$TB_GX_OUT"
rm -rf "$TB_GX_REPO"
rm -rf "$TB_MB_REPO"

# #1826 stranded-superseded-branch detection: fires whether the canonical branch is present or
# absent, keyed on records under the superseded branch's pre-rename `.devflow/logs/efficiency/`
# path. Cases below: (a) absent-canonical (rename remedy), (b/c) no report, (d) both-present.
# $1 = repo root, $2 = grep needle selecting which report to detect -> yes|no. Callers pass
# 'is absent but the superseded' for the absent-canonical report, or 'superseded
# devflow-telemetry branch is present' for any stranded-record report.
tb_report_warn() {
  DEVFLOW_CONFIG_FILE="$1/no-such-config.json" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])' \
    "$LIB/../scripts/build-experiment-records.py" "$1" 2>&1 >/dev/null \
    | grep -qF "$2" && echo yes || echo no
}
tb_seed_telemetry_repo() {   # $1 = repo root; seeds a committed repo + a legacy record
  git init -q "$1"
  git -C "$1" config user.email t@e.com; git -C "$1" config user.name t
  git -C "$1" commit --allow-empty -qm seed
  mkdir -p "$1/.prflow/logs/efficiency"
  printf '{"slug":"pr-9","iterations":4}' > "$1/.prflow/logs/efficiency/pr-9-legacy.json"
}
# Commit ONE .devflow/logs/efficiency/ record onto the superseded ref, without touching
# the working tree (plumbing on an isolated index), so the count-based detection fires.
tb_seed_superseded() {   # $1 = repo root
  local blob idx tree commit
  blob="$(printf '{"slug":"pr-old","iterations":2}' | git -C "$1" hash-object -w --stdin)"
  idx="$1/.git/tb-sup-idx"; rm -f "$idx"
  GIT_INDEX_FILE="$idx" git -C "$1" update-index --add --cacheinfo "100644,${blob},.devflow/logs/efficiency/pr-old-run.json"
  tree="$(GIT_INDEX_FILE="$idx" git -C "$1" write-tree)"
  commit="$(git -C "$1" commit-tree "$tree" -m superseded)"
  git -C "$1" update-ref refs/heads/devflow-telemetry "$commit"
  rm -f "$idx"
}

# (a) POSITIVE: only the superseded ref exists, carrying a .devflow/ record -> the
#     operator is warned with the fast-forward rename remedy.
TB_UM_A="$(git_sandbox "tb unmigrated telemetry branch")"
tb_seed_telemetry_repo "$TB_UM_A"
tb_seed_superseded "$TB_UM_A"
assert_eq "tb(#1003): superseded-only telemetry branch is reported, never read as a measured absence" "yes" \
  "$(tb_report_warn "$TB_UM_A" 'is absent but the superseded')"
# The warning has to be actionable, so it carries the exact one-shot rename.
TB_UM_A_ERR="$(DEVFLOW_CONFIG_FILE="$TB_UM_A/no-such-config.json" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_UM_A" 2>&1 >/dev/null)"
assert_eq "tb(#1003): the unmigrated-branch warning names the rename command" "yes" \
  "$(printf '%s' "$TB_UM_A_ERR" | grep -qF 'git push origin devflow-telemetry:prflow-telemetry' && echo yes || echo no)"
# Detection only — the superseded branch is never read through, so the reader
# still returns just the working-tree archive.
TB_UM_A_OUT="$(DEVFLOW_CONFIG_FILE="$TB_UM_A/no-such-config.json" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
idx=m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])
print(sorted((e["run_id"],e["iterations"]) for v in idx.values() for e in v))' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_UM_A" 2>/dev/null)"
assert_eq "tb(#1003): detection is not a read-through (superseded rows stay unread)" "[('legacy', 4)]" "$TB_UM_A_OUT"
rm -rf "$TB_UM_A"

# (b) NEGATIVE: both refs present but the superseded ref carries NO stranded record
#     under .devflow/logs/efficiency/ -> nothing stranded, no report. (The both-present
#     case WITH stranded records is (d) below.)
TB_UM_B="$(git_sandbox "tb migrated telemetry branch")"
tb_seed_telemetry_repo "$TB_UM_B"
git -C "$TB_UM_B" update-ref refs/heads/devflow-telemetry "$(git -C "$TB_UM_B" rev-parse HEAD)"
git -C "$TB_UM_B" update-ref refs/heads/prflow-telemetry "$(git -C "$TB_UM_B" rev-parse HEAD)"
assert_eq "tb(#1826): both refs present but superseded carries no .devflow/ record → no report" "no" \
  "$(tb_report_warn "$TB_UM_B" 'superseded devflow-telemetry branch is present')"
rm -rf "$TB_UM_B"

# (c) NEGATIVE: neither ref exists -> a genuine absence, no report.
TB_UM_C="$(git_sandbox "tb no telemetry branch")"
tb_seed_telemetry_repo "$TB_UM_C"
assert_eq "tb(#1003): no telemetry ref at all is a genuine absence → no report" "no" \
  "$(tb_report_warn "$TB_UM_C" 'superseded devflow-telemetry branch is present')"
rm -rf "$TB_UM_C"

# (d) POSITIVE (#1826): both refs present AND the superseded ref carries stranded
#     .devflow/ records -> warn with the divergent-safe copy-across remedy, never a
#     destructive force-push of the superseded ref onto the canonical one.
TB_UM_D="$(git_sandbox "tb both refs stranded records")"
tb_seed_telemetry_repo "$TB_UM_D"
tb_seed_superseded "$TB_UM_D"
git -C "$TB_UM_D" update-ref refs/heads/prflow-telemetry "$(git -C "$TB_UM_D" rev-parse HEAD)"
assert_eq "tb(#1826): both refs present, superseded carries a stranded record → warned" "yes" \
  "$(tb_report_warn "$TB_UM_D" 'superseded devflow-telemetry branch is present')"
TB_UM_D_ERR="$(DEVFLOW_CONFIG_FILE="$TB_UM_D/no-such-config.json" python3 -c 'import importlib.util,sys
s=importlib.util.spec_from_file_location("e",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m._index_efficiency(sys.argv[2]+"/.prflow/logs/efficiency", sys.argv[2])' \
  "$LIB/../scripts/build-experiment-records.py" "$TB_UM_D" 2>&1 >/dev/null)"
assert_eq "tb(#1826): the both-present remedy is divergent-safe (copy across, not a force-push)" "yes" \
  "$(printf '%s' "$TB_UM_D_ERR" | grep -qF 'Do NOT force-push' && echo yes || echo no)"
rm -rf "$TB_UM_D"

# Grep pins (AC1/AC19/AC22): the SKILL mirrors + workflows + docs carry the new
# telemetry-branch contract; a revert turns the suite RED.
TB_RAF="$MAXI_BUNDLE"; TB_REV="$REVIEW_BUNDLE"   # #530: TB_RAF=root+references bundle
assert_eq "tb(#441 AC1): review-and-fix Loop-Exit persists via --persist (single code path)" "yes" \
  "$([ "$(devflow_module_pin_count '/../../lib/efficiency-trace.sh --persist --workpad-dir ".prflow/tmp/review/<slug>/<run-id>" --slug "<slug>"' "$TB_RAF")" -ge 1 ] && echo yes || echo no)"
assert_eq "tb(#441 AC1): review Phase 4.5 persists via --persist (unified store)" "yes" \
  "$([ "$(devflow_module_pin_count '/../../lib/efficiency-trace.sh --persist --workpad-dir "$WORKPAD_DIR" --slug "<slug>"' "$TB_REV")" -ge 1 ] && echo yes || echo no)"
# PR #442 Important-2: the retrospective's telemetry fetch must NOT use a force `+`
# refspec — a forced fetch rewinds a local-ahead ref (offline-accumulated --persist
# commits not yet reconciled by a writer's union re-parent) and permanently orphans
# those records. The static check preserves the non-forced refspec.
# PR #442 Important-1 (the AC4 push-path guarantee): the rejection arm re-verifies the
# fetched remote tip before the union re-parent. A separate behavioral twin lives in
# the et-persist block: "remote non-telemetry same-named branch".
# AC19: both cloud backstop steps invoke `--persist` and no longer HEAD-gate / bare-push.
for wf in devflow.yml devflow-implement.yml; do
  assert_eq "tb(#441 AC19): $wf backstop invokes the helper --persist" "yes" \
    "$([ "$(devflow_module_pin_count 'bash "$HELPER" --persist' "$LIB/../.github/workflows/$wf")" -ge 1 ] && echo yes || echo no)"
  assert_eq "tb(#441 AC19): $wf backstop no longer carries the before/after-HEAD gate" "0" \
    "$(devflow_module_pin_count 'before=$(git rev-parse HEAD' "$LIB/../.github/workflows/$wf")"
done
# AC19: NO workflow push: trigger can fire on the telemetry branch (a telemetry push must
# run no CI). PR #442 review Suggestion-7: the former grep-based check only looked at files
# that TEXTUALLY mention `prflow-telemetry`, so it was structurally blind to the shape that
# actually breaks AC19 — a workflow with an UNFILTERED `on: push` (no `branches:` key at all)
# or a glob (`'*'`, `'devflow-*'`) that matches the branch without naming it. Audit the real
# population instead: parse EVERY workflow, take every one with a push trigger, and require
# it to carry a branches filter none of whose patterns match the telemetry branch. (YAML 1.1
# parses the bare key `on` as the boolean True — look both up.)
assert_eq "tb(#441 AC19): every workflow push: trigger is filtered so it cannot fire on prflow-telemetry" "OK" \
  "$(python3 - "$LIB/../.github/workflows" <<'PYEOF'
import fnmatch, pathlib, sys
import yaml
bad = []
# Enumerate BOTH extensions: GitHub Actions honors `.yaml` as well as `.yml`, so a
# `*.yml`-only glob is narrower than the population this audit CLAIMS to cover ("every
# workflow") — a future `foo.yaml` carrying an unfiltered `on: push` would be structurally
# invisible to the very check written to catch exactly that shape (PR #442 review — the
# completeness critic's finding: an audit must not be judged complete by its own pattern).
wf_dir = pathlib.Path(sys.argv[1])
for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
    doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = {k: None for k in on}
    if not isinstance(on, dict) or "push" not in on:
        continue
    push = on["push"]
    branches = push.get("branches") if isinstance(push, dict) else None
    if not isinstance(branches, list) or not branches:
        bad.append(f"{wf.name}: push: trigger has no branches filter")
        continue
    for pat in branches:
        if fnmatch.fnmatch("prflow-telemetry", str(pat)):
            bad.append(f"{wf.name}: push: branches pattern {pat!r} matches prflow-telemetry")
print("OK" if not bad else "; ".join(bad))
PYEOF
)"
# ── PR #442 review fixes ─────────────────────────────────────────────────────────
# Critical-1: bash 3.2 (stock macOS) aborts under `set -u` on "${arr[@]}" when the array
# is EMPTY. lib/efficiency-trace.sh runs `set -euo pipefail`, and `parent_arg` is empty on
# the ORPHAN-ROOT commit — the branch's FIRST write — so a bare expansion made branch
# CREATION impossible on the primary local tier: silently, exit 0, with the breadcrumb
# misattributing it to "object-store write failed". CI (ubuntu, bash 5) and the local suite
# (Homebrew bash 5) both missed it. Two guards:
#
#   (a) STATIC pin — the Linux/bash-5 backstop. Every array expansion in the file must use
#       the ${arr[@]+"${arr[@]}"} guarded form (the idiom lib/implement-stop-guard.sh already
#       carries). A bare "${...[@]}" reintroduction turns this RED anywhere, on any bash.
#       COMMENT LINES ARE STRIPPED FIRST: the fix's own explanatory comments necessarily QUOTE
#       the banned form, and counting those would inflate the count to a permanent RED — the
#       pin-in-comment defect class (#370). Scan code, never prose.
#       The regex anchors on the OPENING `"${` rather than requiring a preceding character,
#       so a bare expansion at column 0 (or right after a `(`) cannot slip past it; the
#       guarded form is excluded by requiring that `[@]}` is NOT preceded by a `+` construct,
#       which we express by matching the guarded form separately and subtracting nothing —
#       i.e. we match `"${name[@]}"` only when it is NOT itself inside `${name[@]+...}`.
assert_eq "tb(#442 Critical-1): telemetry-branch.sh has NO bare \"\${arr[@]}\" expansion (bash-3.2 set -u abort)" "0" \
  "$(grep -vE '^[[:space:]]*#' "$LIB/telemetry-branch.sh" \
     | sed -E 's/\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\+"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"\}//g' \
     | grep -cE '"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"' || true)"
#   (b) BEHAVIORAL pin — reproduces the defect under a real bash 3.x, so it runs on the macOS
#       dev tier and not on Linux CI. It therefore stayed in lib/test/run.sh when this region
#       was extracted: a module's emitted tally is compared for EQUALITY against its registry
#       floor, and a host-conditional arm makes that tally host-dependent. See the retained
#       block beside this module's full-suite call for the arm itself.

# Imp: the CAS discriminator must classify a race by ASKING THE REF, not by parsing git's
# (localized, shape-incomplete) stderr. The old `*"but expected"*` match missed the
# BRANCH-CREATION race entirely: a sibling that CREATES the ref between our absent-ref read
# and our write is rejected with `reference already exists` — no "but expected" — so the
# retry that would have succeeded was skipped, the run's telemetry was DROPPED, and the
# breadcrumb then asserted the cause was "NOT a concurrent writer". This is the first-use
# race two parallel worktrees are most likely to hit, on the very branch this feature creates.
TB_ORACE_REPO="$(git_sandbox "tb orphan-creation race repo")"
git -C "$TB_ORACE_REPO" init -q
git -C "$TB_ORACE_REPO" config user.email t@e.com; git -C "$TB_ORACE_REPO" config user.name t
mkdir -p "$TB_ORACE_REPO/.prflow"; printf 'tmp/\n' > "$TB_ORACE_REPO/.prflow/.gitignore"
git -C "$TB_ORACE_REPO" add -A; git -C "$TB_ORACE_REPO" commit -qm seed
# Hook: a SIBLING creates the branch from ABSENT, between our `old` read (empty) and our CAS.
cat > "$TB_ORACE_REPO/racehook.sh" <<'EOF'
#!/usr/bin/env bash
root="$1"; ref="$2"
b=$(printf 'sibling\n' | git -C "$root" hash-object -w --stdin)
idx="$root/.prflow/tmp/sibidx"; rm -f "$idx"
GIT_INDEX_FILE="$idx" git -C "$root" update-index --add --cacheinfo "100644,${b},.prflow/logs/review/sib/run-9/iter-1.json"
tree=$(GIT_INDEX_FILE="$idx" git -C "$root" write-tree)
c=$(GIT_AUTHOR_NAME=s GIT_AUTHOR_EMAIL=s@s GIT_COMMITTER_NAME=s GIT_COMMITTER_EMAIL=s@s \
      git -C "$root" commit-tree "$tree" -m sibling)
git -C "$root" update-ref "$ref" "$c" ""
rm -f "$idx"
EOF
chmod +x "$TB_ORACE_REPO/racehook.sh"
TB_ORACE_STAGE="$TB_ORACE_REPO/.prflow/tmp/stage"
mkdir -p "$TB_ORACE_STAGE/.prflow/logs/review/pr-1/run-1"
printf '{"iter":1}\n' > "$TB_ORACE_STAGE/.prflow/logs/review/pr-1/run-1/iter-1.json"
TB_ORACE_ERR="$( ( cd "$TB_ORACE_REPO" && DEVFLOW_CONFIG_FILE=/dev/null \
  DEVFLOW_TELEMETRY_RACE_HOOK="$TB_ORACE_REPO/racehook.sh" \
  bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_ORACE_REPO" "$TB_ORACE_STAGE" ) 2>&1 1>/dev/null )"
# The retry must rebuild on the sibling's tip: BOTH records survive, no lost write.
assert_eq "tb(#442): orphan-CREATION race → the racer's record survives" "yes" \
  "$(_et_on_branch "$TB_ORACE_REPO" ".prflow/logs/review/sib/run-9/iter-1.json")"
assert_eq "tb(#442): orphan-CREATION race → OUR record survives too (the retry actually ran)" "yes" \
  "$(_et_on_branch "$TB_ORACE_REPO" ".prflow/logs/review/pr-1/run-1/iter-1.json")"
# ...and the breadcrumb must NOT misattribute a concurrent writer to a disk/lock fault.
assert_eq "tb(#442): orphan-CREATION race → no 'NOT a concurrent writer' misattribution" "no" \
  "$(printf '%s' "$TB_ORACE_ERR" | grep -qF 'NOT a concurrent writer' && echo yes || echo no)"
rm -rf "$TB_ORACE_REPO"

# Imp: devflow_telemetry_list_blobs must not launder an UNREADABLE store into "no records".
# Its consumer is the fix-commit EXCLUSION set, so an emptied list makes synthesis
# re-attribute already-recorded commits — double-counted telemetry, with zero signal.
TB_LBU_REPO="$(git_sandbox "tb list_blobs unreadable repo")"
git -C "$TB_LBU_REPO" init -q
git -C "$TB_LBU_REPO" config user.email t@e.com; git -C "$TB_LBU_REPO" config user.name t
mkdir -p "$TB_LBU_REPO/.prflow"; printf 'tmp/\n' > "$TB_LBU_REPO/.prflow/.gitignore"
git -C "$TB_LBU_REPO" add -A; git -C "$TB_LBU_REPO" commit -qm seed
TB_LBU_STAGE="$TB_LBU_REPO/.prflow/tmp/stage"
mkdir -p "$TB_LBU_STAGE/.prflow/logs/review/pr-1/run-1"
printf '{"iter":1,"fix_commit_sha":"deadbee"}\n' > "$TB_LBU_STAGE/.prflow/logs/review/pr-1/run-1/iter-1.json"
( cd "$TB_LBU_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_LBU_REPO" "$TB_LBU_STAGE" ) >/dev/null 2>&1
# Positive control: with a READABLE store the listing is non-empty (so the RED below is
# attributable to the unreadable tree, not to an empty/absent branch).
assert_eq "tb(#442): list_blobs on a readable store lists the record (positive control)" "yes" \
  "$( ( cd "$TB_LBU_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_list_blobs "$2" refs/heads/prflow-telemetry ".prflow/logs/review/"' _ \
      "$LIB/telemetry-branch.sh" "$TB_LBU_REPO" ) 2>/dev/null | grep -q 'iter-1.json' && echo yes || echo no)"
# Now make the tip's TREE object unreadable (ref still resolves → the "present but unreadable"
# case), and assert the breadcrumb fires instead of a silent empty listing.
TB_LBU_TREE="$(git -C "$TB_LBU_REPO" rev-parse "refs/heads/prflow-telemetry^{tree}")"
rm -f "$TB_LBU_REPO/.git/objects/${TB_LBU_TREE:0:2}/${TB_LBU_TREE:2}"
TB_LBU_ERR="$( ( cd "$TB_LBU_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_list_blobs "$2" refs/heads/prflow-telemetry ".prflow/logs/review/"' _ \
    "$LIB/telemetry-branch.sh" "$TB_LBU_REPO" ) 2>&1 1>/dev/null )"
assert_eq "tb(#442): list_blobs on a PRESENT-but-unreadable store breadcrumbs (never a silent empty list)" "yes" \
  "$(printf '%s' "$TB_LBU_ERR" | grep -qF 'exclusion set is INCOMPLETE' && echo yes || echo no)"
rm -rf "$TB_LBU_REPO"

# Imp: a telemetry.branch config value git rejects as a ref name must be named as a CONFIG
# error, not misreported by the terminal CAS arm as "a held ref .lock, a read-only .git, or a
# full disk" — on every run. Falls back to the default so telemetry still persists.
TB_BADNAME_REPO="$(git_sandbox "tb bad branch name repo")"
git -C "$TB_BADNAME_REPO" init -q
git -C "$TB_BADNAME_REPO" config user.email t@e.com; git -C "$TB_BADNAME_REPO" config user.name t
mkdir -p "$TB_BADNAME_REPO/.prflow"; printf 'tmp/\n' > "$TB_BADNAME_REPO/.prflow/.gitignore"
printf '{"telemetry":{"branch":"bad name with spaces"}}\n' > "$TB_BADNAME_REPO/.prflow/config.json"
git -C "$TB_BADNAME_REPO" add -A; git -C "$TB_BADNAME_REPO" commit -qm seed
mkdir -p "$TB_BADNAME_REPO/.prflow/tmp/review/pr-bn/run-1"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_BADNAME_REPO/.prflow/tmp/review/pr-bn/run-1/iter-1.json"
TB_BN_ERR="$( ( cd "$TB_BADNAME_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; TB_BN_RC=$?
assert_eq "tb(#442): an unusable telemetry.branch value → exit 0 (best-effort)" "0" "$TB_BN_RC"
assert_eq "tb(#442): ...names the CONFIG KEY, not a phantom lock/disk fault" "yes" \
  "$(printf '%s' "$TB_BN_ERR" | grep -qF "config key 'telemetry.branch'" && echo yes || echo no)"
assert_eq "tb(#442): ...and does NOT misattribute it to a held ref .lock / read-only .git / full disk" "no" \
  "$(printf '%s' "$TB_BN_ERR" | grep -qF 'a held ref .lock' && echo yes || echo no)"
assert_eq "tb(#442): ...and still persists, on the default branch" "yes" \
  "$(_et_on_branch "$TB_BADNAME_REPO" ".prflow/logs/efficiency/pr-bn-run-1.json")"
# ...and the READER must follow the writer's fallback to the same default. Asserting only the
# writer's half here is what let the two tests jointly ENCODE a store split without detecting
# it: the writer fell back to `prflow-telemetry` while the reader looked on `bad name with
# spaces` and found nothing, silently (PR #442 Step-3.5 gate).
assert_eq "tb(#442): ...and the READER resolves that same default (no silent store split)" "prflow-telemetry" \
  "$(DEVFLOW_CONFIG_FILE="$TB_BADNAME_REPO/.prflow/config.json" python3 - "$TB_BADNAME_REPO" "$LIB/../scripts/build-experiment-records.py" <<'PYEOF'
import importlib.util, sys, io, contextlib
root, mod_path = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ber", mod_path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with contextlib.redirect_stderr(io.StringIO()):
    print(m._telemetry_branch(root))
PYEOF
)"
rm -rf "$TB_BADNAME_REPO"

# PR #442 Step-3.5 fix-delta gate, C2: the push must be skipped only when the REMOTE is
# already at our tip — never merely because THIS run created no new commit. Those diverge on
# the reconnect path: after an offline run the local ref is AHEAD of the remote, and the next
# persist re-walks the same run dirs → tree unchanged → CAS NOOP. A NOOP-keyed skip would exit
# before the push and strand the offline-accumulated commits indefinitely, falsifying the
# offline breadcrumb's own promise that "the next persist will carry it".
TB_OFFP_REMOTE="$(git_sandbox "tb offline-then-reconnect remote")"
git -C "$TB_OFFP_REMOTE" init -q --bare
TB_OFFP_REPO="$(git_sandbox "tb offline-then-reconnect repo")"
git -C "$TB_OFFP_REPO" init -q
git -C "$TB_OFFP_REPO" config user.email t@e.com; git -C "$TB_OFFP_REPO" config user.name t
mkdir -p "$TB_OFFP_REPO/.prflow"; printf 'tmp/\n' > "$TB_OFFP_REPO/.prflow/.gitignore"
git -C "$TB_OFFP_REPO" add -A; git -C "$TB_OFFP_REPO" commit -qm seed
# Run 1: OFFLINE (origin unreachable) → local ref advances, push fails, record is local-only.
git -C "$TB_OFFP_REPO" remote add origin /nonexistent/telemetry/remote.git
mkdir -p "$TB_OFFP_REPO/.prflow/tmp/review/pr-off/run-1"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$TB_OFFP_REPO/.prflow/tmp/review/pr-off/run-1/iter-1.json"
( cd "$TB_OFFP_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "tb(#442 C2): offline run → the record is on the LOCAL ref" "yes" \
  "$(_et_on_branch "$TB_OFFP_REPO" ".prflow/logs/efficiency/pr-off-run-1.json")"
# Run 2: RECONNECT. Same run dir → no new record → the CAS takes the NOOP arm. The push must
# STILL happen, carrying the offline-accumulated commit to the now-reachable remote.
git -C "$TB_OFFP_REPO" remote set-url origin "$TB_OFFP_REMOTE"
( cd "$TB_OFFP_REPO" && bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "tb(#442 C2): reconnect with NOTHING new → the offline record is STILL pushed (not stranded)" "yes" \
  "$(git -C "$TB_OFFP_REMOTE" cat-file -e "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-off-run-1.json" >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$TB_OFFP_REPO" "$TB_OFFP_REMOTE"

# PR #442 Step-3.5 fix-delta gate, I1: a NON-STRING .telemetry.branch must not split the store.
# config-get.sh COERCES a scalar to a string (5 -> "5"), so the writer persists to branch `5`;
# a reader that fell back to the default would look on `prflow-telemetry` and find nothing,
# silently. Reader and writer must resolve the SAME branch for every row of the wrong-type matrix.
TB_WT_REPO="$(git_sandbox "tb wrong-typed telemetry.branch repo")"
git -C "$TB_WT_REPO" init -q
git -C "$TB_WT_REPO" config user.email t@e.com; git -C "$TB_WT_REPO" config user.name t
mkdir -p "$TB_WT_REPO/.prflow"; printf 'tmp/\n' > "$TB_WT_REPO/.prflow/.gitignore"
git -C "$TB_WT_REPO" add -A; git -C "$TB_WT_REPO" commit -qm seed
# The matrix must include the rows that DIVERGE if either half of the resolution is missed —
# not just the ones that happen to agree (a matrix of only-agreeing rows is a vacuous test):
#   * coercion rows      : 5 / false / 0 / ["a"] / {"x":1}  (config-get.sh stringifies these)
#   * coercion NULL arm  : [null] / ["a",null]              (config-get.sh maps null -> "")
#   * ref-NAME rows      : "my branch" / "a..b" / "x.lock" / "-lead"  — schema-VALID strings
#                          that git REJECTS, so the writer falls back to the default. These
#                          bypass the non-string branch entirely and were the split a
#                          coercion-only mirror still left open.
while IFS= read -r tb_wt_val; do
  [ -n "$tb_wt_val" ] || continue
  printf '{"telemetry":{"branch":%s}}\n' "$tb_wt_val" > "$TB_WT_REPO/.prflow/config.json"
  tb_wt_writer="$( ( cd "$TB_WT_REPO" && DEVFLOW_CONFIG_FILE="$TB_WT_REPO/.prflow/config.json" \
      bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_branch' _ "$LIB/telemetry-branch.sh" ) 2>/dev/null )"
  tb_wt_reader="$(DEVFLOW_CONFIG_FILE="$TB_WT_REPO/.prflow/config.json" python3 - "$TB_WT_REPO" "$LIB/../scripts/build-experiment-records.py" <<'PYEOF'
import importlib.util, sys, io, contextlib
root, mod_path = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ber", mod_path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with contextlib.redirect_stderr(io.StringIO()):
    print(m._telemetry_branch(root))
PYEOF
)"
  assert_eq "tb(#442 I1): .telemetry.branch=${tb_wt_val} → reader resolves the SAME branch the writer wrote to" \
    "$tb_wt_writer" "$tb_wt_reader"
done <<'EOF'
"my-branch"
"my branch"
"a..b"
"x.lock"
"-lead"
5
false
0
""
["a"]
["a",null]
[null]
{"x":1}
EOF
rm -rf "$TB_WT_REPO"

# PR #442 shadow review, Critical: an UNREADABLE local tip must never be read as "our content is
# already on the remote". commit_union_on streamed `ls-tree "$overlay"` straight into its build
# loop with the rc discarded, so a failed listing produced an empty stream → write-tree returned
# the BASE tree unchanged → tree == ptree → NOOP → and the caller then FAST-FORWARDED the local
# ref onto the remote tip, orphaning this run's commit AND every offline-accumulated record the
# union exists to preserve. Silently, exit 0. Assert it now fails CLOSED (keeps the local ref).
TB_UO_REMOTE="$(git_sandbox "tb union unreadable-overlay remote")"
git -C "$TB_UO_REMOTE" init -q --bare
TB_UO_REPO="$(git_sandbox "tb union unreadable-overlay repo")"
git -C "$TB_UO_REPO" init -q
git -C "$TB_UO_REPO" config user.email t@e.com; git -C "$TB_UO_REPO" config user.name t
mkdir -p "$TB_UO_REPO/.prflow"; printf 'tmp/\n' > "$TB_UO_REPO/.prflow/.gitignore"
git -C "$TB_UO_REPO" add -A; git -C "$TB_UO_REPO" commit -qm seed
git -C "$TB_UO_REPO" remote add origin "$TB_UO_REMOTE"
# A FOREIGN writer publishes a telemetry branch remotely, so our push is rejected and the
# fetch → union re-parent path is the one that runs.
TB_UO_FOREIGN="$(git_sandbox "tb union foreign repo")"
git -C "$TB_UO_FOREIGN" init -q
git -C "$TB_UO_FOREIGN" config user.email f@e.com; git -C "$TB_UO_FOREIGN" config user.name f
mkdir -p "$TB_UO_FOREIGN/.prflow"; printf 'tmp/\n' > "$TB_UO_FOREIGN/.prflow/.gitignore"
git -C "$TB_UO_FOREIGN" add -A; git -C "$TB_UO_FOREIGN" commit -qm seed
TB_UO_FSTAGE="$TB_UO_FOREIGN/.prflow/tmp/stage"
mkdir -p "$TB_UO_FSTAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-foreign"}\n' > "$TB_UO_FSTAGE/.prflow/logs/efficiency/pr-foreign-run-1.json"
( cd "$TB_UO_FOREIGN" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_UO_FOREIGN" "$TB_UO_FSTAGE" ) >/dev/null 2>&1
git -C "$TB_UO_FOREIGN" remote add origin "$TB_UO_REMOTE"
git -C "$TB_UO_FOREIGN" push -q origin refs/heads/prflow-telemetry:refs/heads/prflow-telemetry
# Our run: persist locally (creates our local tip), then persist AGAIN so the push is rejected by
# the foreign remote and the fetch -> union re-parent path is the one that actually runs. (This is
# the POSITIVE control for that path. It does NOT corrupt anything: corrupting the local tip's tree
# to drive the fail-closed half is impossible from outside, because verify_store rejects the run
# earlier — see the pin below.)
TB_UO_STAGE="$TB_UO_REPO/.prflow/tmp/stage"
mkdir -p "$TB_UO_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-mine"}\n' > "$TB_UO_STAGE/.prflow/logs/efficiency/pr-mine-run-1.json"
( cd "$TB_UO_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_UO_REPO" "$TB_UO_STAGE" ) >/dev/null 2>&1
# POSITIVE CONTROL for the union path: with a READABLE local tip the union re-parent runs and
# BOTH writers' records survive on the remote. This is what makes the pin below attributable —
# it proves the fixture actually reaches commit_union_on rather than being turned away earlier.
( cd "$TB_UO_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_UO_REPO" "$TB_UO_STAGE" ) >/dev/null 2>&1
assert_eq "tb(#442 shadow-C1 control): the union re-parent runs — the FOREIGN record survives the push" "yes" \
  "$(git -C "$TB_UO_REMOTE" cat-file -e "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-foreign-run-1.json" >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "tb(#442 shadow-C1 control): ...and OUR record survives it too (no data loss on reconcile)" "yes" \
  "$(git -C "$TB_UO_REMOTE" cat-file -e "refs/heads/prflow-telemetry:.prflow/logs/efficiency/pr-mine-run-1.json" >/dev/null 2>&1 && echo yes || echo no)"
rm -rf "$TB_UO_REPO" "$TB_UO_REMOTE" "$TB_UO_FOREIGN"
# PR #442 shadow review, Important: list_blobs' REF probe is three-way, like its ls-tree arm and
# like the Python reader. An unreadable refs layer (rc 128) must not fold onto "absent" and
# silently empty the fix-commit exclusion set.
TB_LBR_REPO="$(git_sandbox "tb list_blobs unestablished-ref repo")"
mkdir -p "$TB_LBR_REPO"   # NOT a git repo → rev-parse exits 128, not 1
TB_LBR_ERR="$( ( cd "$TB_LBR_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_list_blobs "$2" refs/heads/prflow-telemetry ".prflow/logs/review/"' _ \
    "$LIB/telemetry-branch.sh" "$TB_LBR_REPO" ) 2>&1 1>/dev/null )"
assert_eq "tb(#442 shadow-I2): an UNESTABLISHED ref probe breadcrumbs (never a silent 'no records')" "yes" \
  "$(printf '%s' "$TB_LBR_ERR" | grep -qF 'could not establish whether ref' && echo yes || echo no)"
rm -rf "$TB_LBR_REPO"

# PR #442 shadow review (pr-test-analyzer): four guards this PR ADDED in response to review were
# never driven RED — all diagnostic/attribution arms, where the author fixed the message and moved
# on. A guard you never saw fail may assert nothing. Drive each, and assert the MISATTRIBUTION it
# was added to prevent is ABSENT (the absence assertion is what makes each RED under a revert).

# (a) CAS race EXHAUSTION. Previously unreachable: the race seam self-cleared after one firing, so
# no fixture could exhaust _DEVFLOW_TELEMETRY_CAS_TRIES=5 and the "lost N races" arm was
# dead-code-provable — a 3-arm selector with 1 arm driven. DEVFLOW_TELEMETRY_RACE_HOOK_TIMES=6
# now drives it.
TB_EX_REPO="$(git_sandbox "tb cas exhaustion repo")"
git -C "$TB_EX_REPO" init -q
git -C "$TB_EX_REPO" config user.email t@e.com; git -C "$TB_EX_REPO" config user.name t
mkdir -p "$TB_EX_REPO/.prflow"; printf 'tmp/\n' > "$TB_EX_REPO/.prflow/.gitignore"
git -C "$TB_EX_REPO" add -A; git -C "$TB_EX_REPO" commit -qm seed
cat > "$TB_EX_REPO/racehook.sh" <<'EOF'
#!/usr/bin/env bash
# A sibling that keeps advancing the ref on EVERY firing — the loop can never win.
root="$1"; ref="$2"
b=$(printf 'sib-%s\n' "$RANDOM$$" | git -C "$root" hash-object -w --stdin)
idx="$root/.prflow/tmp/exidx-$$"; rm -f "$idx"
old=$(git -C "$root" rev-parse --verify --quiet "$ref" 2>/dev/null || true)
[ -n "$old" ] && GIT_INDEX_FILE="$idx" git -C "$root" read-tree "$old" 2>/dev/null
GIT_INDEX_FILE="$idx" git -C "$root" update-index --add --cacheinfo "100644,${b},.prflow/logs/review/sib/run-$RANDOM$$/iter-1.json"
tree=$(GIT_INDEX_FILE="$idx" git -C "$root" write-tree)
if [ -n "$old" ]; then
  c=$(GIT_AUTHOR_NAME=s GIT_AUTHOR_EMAIL=s@s GIT_COMMITTER_NAME=s GIT_COMMITTER_EMAIL=s@s git -C "$root" commit-tree "$tree" -p "$old" -m sib)
else
  c=$(GIT_AUTHOR_NAME=s GIT_AUTHOR_EMAIL=s@s GIT_COMMITTER_NAME=s GIT_COMMITTER_EMAIL=s@s git -C "$root" commit-tree "$tree" -m sib)
fi
git -C "$root" update-ref "$ref" "$c" "${old:-}"
rm -f "$idx"
EOF
chmod +x "$TB_EX_REPO/racehook.sh"
TB_EX_STAGE="$TB_EX_REPO/.prflow/tmp/stage"
mkdir -p "$TB_EX_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-ex"}\n' > "$TB_EX_STAGE/.prflow/logs/efficiency/pr-ex-run-1.json"
TB_EX_ERR="$( ( cd "$TB_EX_REPO" && DEVFLOW_CONFIG_FILE=/dev/null \
  DEVFLOW_TELEMETRY_RACE_HOOK="$TB_EX_REPO/racehook.sh" DEVFLOW_TELEMETRY_RACE_HOOK_TIMES=6 \
  bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_EX_REPO" "$TB_EX_STAGE" ) 2>&1 1>/dev/null )"; TB_EX_RC=$?
# #469 AC8: CAS exhaustion produced a staging root, so it is a DEGRADED arm —
# persist_tree now RETURNS 1 (reports the degradation so do_persist retains the staged
# records); --persist/the process still exits 0 (the ETP blocks assert that end-to-end).
assert_eq "tb(#469 AC8): CAS exhaustion is a DEGRADED arm → persist_tree returns 1 (reports it; --persist still exits 0)" "1" "$TB_EX_RC"
assert_eq "tb(#442 shadow-T1): CAS exhaustion FIRES the 'lost N races' arm (previously unreachable)" "yes" \
  "$(printf '%s' "$TB_EX_ERR" | grep -qF "lost 5 races" && echo yes || echo no)"
assert_eq "tb(#442 shadow-T1): ...and does NOT misattribute a racing sibling to a lock/disk fault" "no" \
  "$(printf '%s' "$TB_EX_ERR" | grep -qF 'a held ref .lock (another git process)' && echo yes || echo no)"
rm -rf "$TB_EX_REPO"

# (b) An ABSENT staging root (the caller's mkdir was denied) must not read as "nothing staged".
TB_AS_REPO="$(git_sandbox "tb absent staging-root repo")"
git -C "$TB_AS_REPO" init -q
git -C "$TB_AS_REPO" config user.email t@e.com; git -C "$TB_AS_REPO" config user.name t
mkdir -p "$TB_AS_REPO/.prflow"; printf 'tmp/\n' > "$TB_AS_REPO/.prflow/.gitignore"
git -C "$TB_AS_REPO" add -A; git -C "$TB_AS_REPO" commit -qm seed
TB_AS_ERR="$( ( cd "$TB_AS_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_AS_REPO" "$TB_AS_REPO/.prflow/tmp/never-created" ) 2>&1 1>/dev/null )"; TB_AS_RC=$?
assert_eq "tb(#442 shadow-T2): an ABSENT staging root → exit 0 (best-effort)" "0" "$TB_AS_RC"
assert_eq "tb(#442 shadow-T2): ...breadcrumbs instead of reading as a clean 'nothing staged' no-op" "yes" \
  "$(printf '%s' "$TB_AS_ERR" | grep -qF 'does not exist — the caller could not create it' && echo yes || echo no)"
# Positive control: the SAME fixture with a real (empty) staging root IS a legitimate silent no-op.
mkdir -p "$TB_AS_REPO/.prflow/tmp/empty-stage"
TB_AS_ERR2="$( ( cd "$TB_AS_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_AS_REPO" "$TB_AS_REPO/.prflow/tmp/empty-stage" ) 2>&1 1>/dev/null )"
assert_eq "tb(#442 shadow-T2 control): an EMPTY-but-present staging root stays a silent clean no-op" "no" \
  "$(printf '%s' "$TB_AS_ERR2" | grep -qF 'does not exist' && echo yes || echo no)"
rm -rf "$TB_AS_REPO"

# (c) An UNWRITABLE .prflow/tmp (the cloud-sandbox denial) must name ITS cause, not the object
# store. Make .prflow/tmp a regular FILE so mkdir -p deterministically fails (portable; no chmod).
TB_UW_REPO="$(git_sandbox "tb unwritable devflow-tmp repo")"
git -C "$TB_UW_REPO" init -q
git -C "$TB_UW_REPO" config user.email t@e.com; git -C "$TB_UW_REPO" config user.name t
mkdir -p "$TB_UW_REPO/.prflow"; printf 'tmp/\n' > "$TB_UW_REPO/.prflow/.gitignore"
git -C "$TB_UW_REPO" add -A; git -C "$TB_UW_REPO" commit -qm seed
TB_UW_STAGE="$TB_UW_REPO/stage-elsewhere"
mkdir -p "$TB_UW_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-uw"}\n' > "$TB_UW_STAGE/.prflow/logs/efficiency/pr-uw-run-1.json"
printf 'not-a-directory\n' > "$TB_UW_REPO/.prflow/tmp"   # mkdir -p .prflow/tmp now fails
# #469 AC8: the unwritable-tmp arm PRODUCED a staging root, so it is a DEGRADED arm —
# devflow_telemetry_persist_tree now RETURNS 1 (reports the degradation to its caller so
# do_persist retains the staged records), while --persist/the process still exits 0
# (asserted end-to-end by the ETP blocks). This direct call sees the function return, so
# the return code is 1, not 0. `|| TB_UW_RC=$?` captures it under the `set -e` bash -c
# wrapper (a bare capture would let the non-zero return abort the wrapper before `$?`).
TB_UW_ERR="$( ( cd "$TB_UW_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_UW_REPO" "$TB_UW_STAGE" ) 2>&1 1>/dev/null )"; TB_UW_RC=$?
assert_eq "tb(#469 AC8): an unwritable .prflow/tmp is a DEGRADED arm → persist_tree returns 1 (reports the degradation; --persist still exits 0)" "1" "$TB_UW_RC"
assert_eq "tb(#442 shadow-T3): ...names the DENIED .prflow/tmp write as the cause" "yes" \
  "$(printf '%s' "$TB_UW_ERR" | grep -qF "for the temp index" && echo yes || echo no)"
assert_eq "tb(#442 shadow-T3): ...and does NOT misattribute it to 'object-store write failed'" "no" \
  "$(printf '%s' "$TB_UW_ERR" | grep -qF 'object-store write failed' && echo yes || echo no)"
rm -rf "$TB_UW_REPO"

# (d) The remote probe tests `origin` SPECIFICALLY. Its own comment names the bug a bare
# `git remote` check would cause; drive a repo whose ONLY remote is `upstream` and prove it.
TB_UP_REPO="$(git_sandbox "tb non-origin remote repo")"
git -C "$TB_UP_REPO" init -q
git -C "$TB_UP_REPO" config user.email t@e.com; git -C "$TB_UP_REPO" config user.name t
mkdir -p "$TB_UP_REPO/.prflow"; printf 'tmp/\n' > "$TB_UP_REPO/.prflow/.gitignore"
git -C "$TB_UP_REPO" add -A; git -C "$TB_UP_REPO" commit -qm seed
git -C "$TB_UP_REPO" remote add upstream /nonexistent/upstream.git   # NOT origin
TB_UP_STAGE="$TB_UP_REPO/.prflow/tmp/stage"
mkdir -p "$TB_UP_STAGE/.prflow/logs/efficiency"
printf '{"slug":"pr-up"}\n' > "$TB_UP_STAGE/.prflow/logs/efficiency/pr-up-run-1.json"
TB_UP_ERR="$( ( cd "$TB_UP_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash -c 'set -euo pipefail; . "$1"; devflow_telemetry_persist_tree "$2" "$3"' _ \
    "$LIB/telemetry-branch.sh" "$TB_UP_REPO" "$TB_UP_STAGE" ) 2>&1 1>/dev/null )"
assert_eq "tb(#442 shadow-T4): a repo whose only remote is 'upstream' → names the missing ORIGIN" "yes" \
  "$(printf '%s' "$TB_UP_ERR" | grep -qF "no 'origin' git remote configured" && echo yes || echo no)"
assert_eq "tb(#442 shadow-T4): ...and does NOT misattribute it to 'likely no network'" "no" \
  "$(printf '%s' "$TB_UP_ERR" | grep -qF 'likely no network' && echo yes || echo no)"
assert_eq "tb(#442 shadow-T4): ...and the record still persists to the LOCAL ref" "yes" \
  "$(_et_on_branch "$TB_UP_REPO" ".prflow/logs/efficiency/pr-up-run-1.json")"
rm -rf "$TB_UP_REPO"

# AC18: config schema + example document telemetry.branch.
assert_eq "tb(#441 AC18): config.schema.json documents telemetry.branch (default prflow-telemetry)" "yes" \
  "$(python3 -c 'import json;d=json.load(open("'"$LIB"'/../.prflow/config.schema.json"));print("yes" if d["properties"].get("telemetry",{}).get("properties",{}).get("branch",{}).get("default")=="prflow-telemetry" else "no")')"
assert_eq "tb(#441 AC18): config.example.json carries the telemetry.branch default" "prflow-telemetry" \
  "$(python3 -c 'import json;print(json.load(open("'"$LIB"'/../.prflow/config.example.json")).get("telemetry",{}).get("branch",""))')"
# efficiency-trace.sh sources the shared telemetry-branch lib.
assert_eq "tb(#441): efficiency-trace.sh sources lib/telemetry-branch.sh" "yes" \
  "$([ "$(devflow_module_pin_count 'telemetry-branch.sh' "$LIB/efficiency-trace.sh")" -ge 1 ] && echo yes || echo no)"

# ────────────────────────────────────────────────────────────────────────────
echo "issue #469: push-operand fail-closed, fetch-before-exclusion, degraded retention"
# ────────────────────────────────────────────────────────────────────────────

# ── AC5: _devflow_telemetry_should_push — off CI pushes; on CI only on an
# affirmative DEVFLOW_TELEMETRY_PUSH, else fails closed to staging-only. ────────
_i469_should_push() {  # $1=env assignments; prints "push"/"stage"
  ( eval "$1"; . "$LIB/telemetry-branch.sh"; \
    if _devflow_telemetry_should_push; then echo push; else echo stage; fi )
}
assert_eq "#469 AC5: off CI (no GITHUB_ACTIONS) → push (unchanged local default)" "push" \
  "$(_i469_should_push 'unset GITHUB_ACTIONS; unset DEVFLOW_TELEMETRY_PUSH')"
assert_eq "#469 AC5: off CI even with the operand unset → push" "push" \
  "$(_i469_should_push 'unset GITHUB_ACTIONS; DEVFLOW_TELEMETRY_PUSH=')"
assert_eq "#469 AC5: on CI + operand=1 → push" "push" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; DEVFLOW_TELEMETRY_PUSH=1')"
assert_eq "#469 AC5: on CI + operand=true → push" "push" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; DEVFLOW_TELEMETRY_PUSH=true')"
assert_eq "#469 AC5: on CI + operand UNSET → stage (fails closed)" "stage" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; unset DEVFLOW_TELEMETRY_PUSH')"
assert_eq "#469 AC5: on CI + operand EMPTY → stage (fails closed)" "stage" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; DEVFLOW_TELEMETRY_PUSH=')"
assert_eq "#469 AC5: on CI + operand=0 → stage (non-affirmative fails closed)" "stage" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; DEVFLOW_TELEMETRY_PUSH=0')"
assert_eq "#469 AC5: on CI + operand=garbage → stage (non-affirmative fails closed)" "stage" \
  "$(_i469_should_push 'GITHUB_ACTIONS=true; DEVFLOW_TELEMETRY_PUSH=maybe')"
# ── AC5 end-to-end: a CI-context --persist with NO operand STAGES and does not
# push (the remote prflow-telemetry ref is unchanged), retains the staged tree,
# and breadcrumbs the absent operand. A bare remote proves "unchanged". ─────────
I469_BARE="$(git_sandbox "#469 staging-only bare remote")"; git -C "$I469_BARE" init --bare -q
I469_REPO="$(git_sandbox "#469 staging-only repo")"; git -C "$I469_REPO" init -q
git -C "$I469_REPO" config user.email t@e.com; git -C "$I469_REPO" config user.name t
git -C "$I469_REPO" remote add origin "$I469_BARE"
mkdir -p "$I469_REPO/.prflow"; printf 'tmp/\n' > "$I469_REPO/.prflow/.gitignore"
git -C "$I469_REPO" add -A; git -C "$I469_REPO" commit -qm seed; git -C "$I469_REPO" branch -M main
git -C "$I469_REPO" push -q -u origin main
mkdir -p "$I469_REPO/.prflow/tmp/review/pr-so/run-so"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_REPO/.prflow/tmp/review/pr-so/run-so/iter-1.json"
I469_SO_ST0="$(git -C "$I469_REPO" status --porcelain)"; I469_SO_HD0="$(git -C "$I469_REPO" rev-parse HEAD)"; I469_SO_BR0="$(git -C "$I469_REPO" branch --show-current)"
I469_ERR="$( ( cd "$I469_REPO" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH='' bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; I469_RC=$?
assert_eq "#469 AC5(e2e): staging-only --persist still exits 0" "0" "$I469_RC"
# AC13 for the NEW staging-only mode: git status / HEAD / current branch byte-unchanged.
assert_eq "#469 AC13: staging-only leaves git status byte-for-byte unchanged" "$I469_SO_ST0" "$(git -C "$I469_REPO" status --porcelain)"
assert_eq "#469 AC13: staging-only leaves HEAD unchanged" "$I469_SO_HD0" "$(git -C "$I469_REPO" rev-parse HEAD)"
assert_eq "#469 AC13: staging-only leaves the current branch unchanged" "$I469_SO_BR0" "$(git -C "$I469_REPO" branch --show-current)"
assert_eq "#469 AC5(e2e): staging-only leaves the REMOTE prflow-telemetry ref UNCHANGED (absent)" "no" \
  "$(git -C "$I469_REPO" ls-remote --heads origin prflow-telemetry | grep -q prflow-telemetry && echo yes || echo no)"
assert_eq "#469 AC5(e2e): staging-only performs no branch write (local ref not advanced)" "no" \
  "$(_et_on_branch "$I469_REPO" ".prflow/logs/efficiency/pr-so-run-so.json")"
assert_eq "#469 AC5(e2e): staging-only breadcrumbs the absent push operand" "yes" \
  "$(printf '%s' "$I469_ERR" | grep -qF 'DEVFLOW_TELEMETRY_PUSH is unset/empty/non-affirmative' && echo yes || echo no)"
assert_eq "#469 AC5(e2e): staging-only RETAINS the staged tree for the trusted push relay" "yes" \
  "$(compgen -G "$I469_REPO/.prflow/tmp/telemetry-stage-*" >/dev/null 2>&1 && echo yes || echo no)"
# Staging-only (rc 2) is the INTENDED read-only-review posture, NOT a degradation: it must
# retain SILENTLY and must NOT emit the do_persist "…write DEGRADED…" warning (which is the
# rc-1 arm). If do_persist folded rc 2 into the degraded arm, every read-only review run
# would spuriously warn DEGRADED — assert the negative so that regression goes RED.
assert_eq "#469 AC5(e2e): staging-only does NOT emit the degraded (rc 1) warning" "no" \
  "$(printf '%s' "$I469_ERR" | grep -qF 'the telemetry-branch write DEGRADED' && echo yes || echo no)"
# Positive control: the SAME run with the operand set DOES push (proves the fixture reaches a push path).
git -C "$I469_REPO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && git -C "$I469_REPO" update-ref -d refs/heads/prflow-telemetry
( cd "$I469_REPO" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#469 AC5(e2e control): the SAME run WITH the operand set pushes to the remote" "yes" \
  "$(git -C "$I469_REPO" ls-remote --heads origin prflow-telemetry | grep -q prflow-telemetry && echo yes || echo no)"
rm -rf "$I469_REPO" "$I469_BARE"

# ── AC7: the absent-ref arm of list_blobs distinguishes an ESTABLISHED empty
# (fetch ok, ref still absent → silent) from an UNESTABLISHED one (fetch
# failed/unattempted → ::warning::), keyed on _DEVFLOW_TELEMETRY_FETCH_STATUS. ──
I469_LB="$(git_sandbox "#469 list_blobs absent-ref repo")"; git -C "$I469_LB" init -q
git -C "$I469_LB" config user.email t@e.com; git -C "$I469_LB" config user.name t
mkdir -p "$I469_LB/.prflow"; printf 'tmp/\n' > "$I469_LB/.prflow/.gitignore"
git -C "$I469_LB" add -A; git -C "$I469_LB" commit -qm seed
_i469_lb() {  # $1=fetch-status; drives list_blobs on the ABSENT telemetry ref, returns stderr
  # shellcheck disable=SC2069  # Deliberate capture-stderr-only ordering: 2>&1 dups stderr
  # onto the caller's stdout FIRST, then 1>/dev/null discards the subshell's own stdout.
  ( cd "$I469_LB" && DEVFLOW_CONFIG_FILE=/dev/null _DEVFLOW_TELEMETRY_FETCH_STATUS="$1" \
    bash -c 'set -uo pipefail; . "$1"; devflow_telemetry_list_blobs "$2" refs/heads/prflow-telemetry ".prflow/logs/review/"' \
    _ "$LIB/telemetry-branch.sh" "$I469_LB" ) 2>&1 1>/dev/null
}
assert_eq "#469 AC7: fetch ok + ref absent → ESTABLISHED empty, NO warning" "no" \
  "$(printf '%s' "$(_i469_lb ok)" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
assert_eq "#469 AC7: fetch failed + ref absent → UNESTABLISHED, warns" "yes" \
  "$(printf '%s' "$(_i469_lb failed)" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
assert_eq "#469 AC7: fetch unattempted + ref absent → UNESTABLISHED, warns" "yes" \
  "$(printf '%s' "$(_i469_lb unattempted)" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
# The three assertions above exercise the established-empty and unestablished arms
# directly, including the silent `ok` result.
rm -rf "$I469_LB"

# ── AC7 (e2e derivation, #469 review Suggestion #1): the assertions above INJECT
# _DEVFLOW_TELEMETRY_FETCH_STATUS into list_blobs (the consumer), so the do_persist code
# that DERIVES status=ok from a MISSING origin remote (efficiency-trace.sh's no-origin
# else-arm) is never exercised end-to-end. Drive a real --persist in a no-origin fixture
# and assert its stderr lacks UNESTABLISHED — a regression flipping that arm to `failed`
# would spuriously warn on every local-only first --persist and turn this RED. ─
I469_NO="$(git_sandbox "#469 no-origin e2e repo")"; git -C "$I469_NO" init -q
git -C "$I469_NO" config user.email t@e.com; git -C "$I469_NO" config user.name t
mkdir -p "$I469_NO/.prflow"; printf 'tmp/\n' > "$I469_NO/.prflow/.gitignore"
git -C "$I469_NO" add -A; git -C "$I469_NO" commit -qm seed
mkdir -p "$I469_NO/.prflow/tmp/review/pr-no/run-no"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_NO/.prflow/tmp/review/pr-no/run-no/iter-1.json"
# Staging-only isolates the fetch-status derivation (no push attempted); the LOCAL telemetry
# ref is ABSENT, so list_blobs' absent-ref arm IS consulted during synthesis.
assert_eq "#469 AC7(e2e): the no-origin fixture's LOCAL telemetry ref is ABSENT before --persist" "no" \
  "$(git -C "$I469_NO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
# Drive the no-origin derivation BOTH under GITHUB_ACTIONS and off-CI (#469 review Suggestion #2 —
# requirement (d)'s "with and without GITHUB_ACTIONS"): the no-origin else-arm is GITHUB_ACTIONS-
# independent, so neither should ever emit UNESTABLISHED. (Off-CI push-by-default with no origin
# degrades on the push — that is the rc-1 DEGRADED warning, not the list_blobs UNESTABLISHED one.)
I469_NO_ERR="$( ( cd "$I469_NO" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH='' bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#469 AC7(e2e, CI): a no-origin first --persist DERIVES an ESTABLISHED empty (no origin → status=ok) — stderr lacks UNESTABLISHED" "no" \
  "$(printf '%s' "$I469_NO_ERR" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
git -C "$I469_NO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && git -C "$I469_NO" update-ref -d refs/heads/prflow-telemetry
I469_NO_ERR_LOCAL="$( ( cd "$I469_NO" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#469 AC7(e2e, off-CI): the SAME no-origin derivation off-CI also stays silent — stderr lacks UNESTABLISHED" "no" \
  "$(printf '%s' "$I469_NO_ERR_LOCAL" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
# Positive control on the SAME fixture: restore the absent-ref precondition, then add an
# UNREACHABLE origin so the derivation takes the origin-present branch and the fetch FAILS →
# status=failed → list_blobs DOES emit UNESTABLISHED. This proves the no-origin run above
# actually REACHED list_blobs' absent-ref arm (so its silence is meaningful), rather than
# --persist having bailed before ever consulting it.
git -C "$I469_NO" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && git -C "$I469_NO" update-ref -d refs/heads/prflow-telemetry
git -C "$I469_NO" remote add origin /nonexistent/telemetry/remote.git
I469_NO_CTL_ERR="$( ( cd "$I469_NO" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH='' bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#469 AC7(e2e control): the SAME fixture WITH an unreachable origin DOES emit UNESTABLISHED (proves list_blobs' absent-ref arm is reached, so the silence above is not vacuous)" "yes" \
  "$(printf '%s' "$I469_NO_CTL_ERR" | grep -qF 'UNESTABLISHED' && echo yes || echo no)"
rm -rf "$I469_NO"

# ── AC6 producer path (end-to-end): do_persist FETCHES the telemetry branch from origin and
# fast-forwards the ABSENT local ref onto it, so prior remote records become visible to
# recorded_fix_shas (the anti-double-count fix). The AC7 test above injects the STATUS and
# drives only the CONSUMER (list_blobs); this drives the PRODUCER against a real bare remote. ─
I469_FP_BARE="$(git_sandbox "#469 fetch-producer bare remote")"; git -C "$I469_FP_BARE" init --bare -q
# Seed a REAL telemetry store on the remote via a first repo's pushing --persist.
I469_FP_SEED="$(git_sandbox "#469 fetch-producer seed repo")"; git -C "$I469_FP_SEED" init -q
git -C "$I469_FP_SEED" config user.email t@e.com; git -C "$I469_FP_SEED" config user.name t
git -C "$I469_FP_SEED" remote add origin "$I469_FP_BARE"
mkdir -p "$I469_FP_SEED/.prflow"; printf 'tmp/\n' > "$I469_FP_SEED/.prflow/.gitignore"
git -C "$I469_FP_SEED" add -A; git -C "$I469_FP_SEED" commit -qm seed; git -C "$I469_FP_SEED" branch -M main; git -C "$I469_FP_SEED" push -q -u origin main
mkdir -p "$I469_FP_SEED/.prflow/tmp/review/pr-seed/run-seed"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_FP_SEED/.prflow/tmp/review/pr-seed/run-seed/iter-1.json"
( cd "$I469_FP_SEED" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
I469_FP_TIP="$(git -C "$I469_FP_BARE" rev-parse --verify --quiet refs/heads/prflow-telemetry 2>/dev/null || true)"
assert_eq "#469 AC6(producer): the fixture seeded a real telemetry store on the remote" "yes" \
  "$([ -n "$I469_FP_TIP" ] && echo yes || echo no)"
# Second repo: origin points at the seeded remote, LOCAL telemetry ref ABSENT. A --persist
# must fetch + verify + fast-forward the local ref onto the remote tip (the producer path).
I469_FP="$(git_sandbox "#469 fetch-producer consumer repo")"; git -C "$I469_FP" init -q
git -C "$I469_FP" config user.email t@e.com; git -C "$I469_FP" config user.name t
git -C "$I469_FP" remote add origin "$I469_FP_BARE"
mkdir -p "$I469_FP/.prflow"; printf 'tmp/\n' > "$I469_FP/.prflow/.gitignore"
git -C "$I469_FP" add -A; git -C "$I469_FP" commit -qm seed
mkdir -p "$I469_FP/.prflow/tmp/review/pr-fp/run-fp"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_FP/.prflow/tmp/review/pr-fp/run-fp/iter-1.json"
assert_eq "#469 AC6(producer): the LOCAL telemetry ref is ABSENT before --persist" "no" \
  "$(git -C "$I469_FP" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
# Staging-only (operand empty) so this run does not itself push — isolating the FETCH producer.
( cd "$I469_FP" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH='' bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#469 AC6(producer): --persist fast-forwarded the ABSENT local ref onto the fetched remote tip (prior records now visible to recorded_fix_shas)" "$I469_FP_TIP" \
  "$(git -C "$I469_FP" rev-parse --verify --quiet refs/heads/prflow-telemetry 2>/dev/null || true)"
rm -rf "$I469_FP" "$I469_FP_SEED" "$I469_FP_BARE"

# ── AC7 producer fail-open guard (#469 review fix): when origin HAS a branch named
# prflow-telemetry but it is NOT a readable telemetry store (a consumer's same-named branch,
# or a corrupt tree), do_persist must NOT set status=ok before verify_store — it leaves the
# state UNESTABLISHED (status=failed + warning) and does NOT advance the local ref, so a
# present-but-unreadable store is never laundered into a silent established-empty. ──
I469_VF_BARE="$(git_sandbox "#469 verify-fail bare remote")"; git -C "$I469_VF_BARE" init --bare -q
# Push a NON-telemetry branch named prflow-telemetry (a root file → verify_store rejects it).
I469_VF_SEED="$(git_sandbox "#469 verify-fail seed repo")"; git -C "$I469_VF_SEED" init -q
git -C "$I469_VF_SEED" config user.email t@e.com; git -C "$I469_VF_SEED" config user.name t
printf 'not a telemetry store\n' > "$I469_VF_SEED/random.txt"
git -C "$I469_VF_SEED" add -A; git -C "$I469_VF_SEED" commit -qm 'not a store'
git -C "$I469_VF_SEED" push -q "$I469_VF_BARE" HEAD:refs/heads/prflow-telemetry
# Consumer repo: origin → that remote, local telemetry ref ABSENT.
I469_VF="$(git_sandbox "#469 verify-fail consumer repo")"; git -C "$I469_VF" init -q
git -C "$I469_VF" config user.email t@e.com; git -C "$I469_VF" config user.name t
git -C "$I469_VF" remote add origin "$I469_VF_BARE"
mkdir -p "$I469_VF/.prflow"; printf 'tmp/\n' > "$I469_VF/.prflow/.gitignore"
git -C "$I469_VF" add -A; git -C "$I469_VF" commit -qm seed
mkdir -p "$I469_VF/.prflow/tmp/review/pr-vf/run-vf"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_VF/.prflow/tmp/review/pr-vf/run-vf/iter-1.json"
I469_VF_ERR="$( ( cd "$I469_VF" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH='' bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#469 AC7 fail-open fix: a present-but-unverifiable remote tip is UNESTABLISHED (do_persist warns it could not be verified), not laundered into status=ok" "yes" \
  "$(printf '%s' "$I469_VF_ERR" | grep -qF 'could not be verified as a readable DevFlow telemetry store' && echo yes || echo no)"
assert_eq "#469 AC7 fail-open fix: the unverifiable remote tip is NOT advanced onto the local ref" "no" \
  "$(git -C "$I469_VF" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1 && echo yes || echo no)"
# The first assertion is itself the behavioral guard: the "could not be verified as a readable
# DevFlow telemetry store" warning is emitted ONLY by the post-verify fail arm this fix added.
# Reverting to the pre-fix "status=ok on bare fetch success" (no such arm) removes that warning,
# so the assertion goes RED — no separate comment-pin needed (which would re-create the very
# comment-anchored-pin defect the #469 review flagged for the AC8 pin).
rm -rf "$I469_VF" "$I469_VF_SEED" "$I469_VF_BARE"

# ── AC8: a DEGRADED persist RETAINS its staging root and breadcrumbs its absolute
# path (instead of the old unconditional rm -rf). Drive an unpushable-but-CI push
# (operand set, remote unreachable) → persist_tree returns 1 → do_persist retains. ─
I469_DEG="$(git_sandbox "#469 degraded-retain repo")"; git -C "$I469_DEG" init -q
git -C "$I469_DEG" config user.email t@e.com; git -C "$I469_DEG" config user.name t
git -C "$I469_DEG" remote add origin /nonexistent/telemetry/remote.git
mkdir -p "$I469_DEG/.prflow"; printf 'tmp/\n' > "$I469_DEG/.prflow/.gitignore"
git -C "$I469_DEG" add -A; git -C "$I469_DEG" commit -qm seed
mkdir -p "$I469_DEG/.prflow/tmp/review/pr-dg/run-dg"
printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  > "$I469_DEG/.prflow/tmp/review/pr-dg/run-dg/iter-1.json"
# AC13 for the DEGRADED-retention path (#469 review): the degraded arm both RETAINS a staging
# root under gitignored .prflow/tmp/ AND advances the detached local telemetry ref before the
# push fails — assert neither dirties the tree. Capture pre-state before --persist.
I469_DG_ST0="$(git -C "$I469_DEG" status --porcelain)"; I469_DG_HD0="$(git -C "$I469_DEG" rev-parse HEAD)"; I469_DG_BR0="$(git -C "$I469_DEG" branch --show-current)"
I469_DEG_ERR="$( ( cd "$I469_DEG" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"; I469_DEG_RC=$?
assert_eq "#469 AC8: a degraded persist still exits 0 (best-effort, never aborts)" "0" "$I469_DEG_RC"
assert_eq "#469 AC13: the degraded-retention path leaves git status byte-for-byte unchanged" "$I469_DG_ST0" "$(git -C "$I469_DEG" status --porcelain)"
assert_eq "#469 AC13: the degraded-retention path leaves HEAD unchanged" "$I469_DG_HD0" "$(git -C "$I469_DEG" rev-parse HEAD)"
assert_eq "#469 AC13: the degraded-retention path leaves the current branch unchanged" "$I469_DG_BR0" "$(git -C "$I469_DEG" branch --show-current)"
assert_eq "#469 AC8: a degraded persist RETAINS the staging root (not rm -rf'd)" "yes" \
  "$(compgen -G "$I469_DEG/.prflow/tmp/telemetry-stage-*" >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "#469 AC8: the degraded breadcrumb names the RETAINED staging root's absolute path" "yes" \
  "$(printf '%s' "$I469_DEG_ERR" | grep -qE 'RETAINING the staged records at .*/\.prflow/tmp/telemetry-stage-' && echo yes || echo no)"
# The degraded-retention assertions above exercise the non-clean cleanup boundary.
rm -rf "$I469_DEG"

# ── AC8 cleanup policy: retained telemetry-stage-* roots are pruned to the newest
# _DEVFLOW_TELEMETRY_STAGE_KEEP on each --persist so they cannot grow unbounded. ──
I469_PR="$(git_sandbox "#469 stage-prune repo")"; git -C "$I469_PR" init -q
git -C "$I469_PR" config user.email t@e.com; git -C "$I469_PR" config user.name t
mkdir -p "$I469_PR/.prflow/tmp"; printf 'tmp/\n' > "$I469_PR/.prflow/.gitignore"
git -C "$I469_PR" add -A; git -C "$I469_PR" commit -qm seed 2>/dev/null || true
for _p in 01 02 03 04 05 06; do mkdir -p "$I469_PR/.prflow/tmp/telemetry-stage-200001010000$_p-x-y-z"; done
# A clean --persist (no run dirs) prunes the pre-existing roots to KEEP before creating its own.
( cd "$I469_PR" && _DEVFLOW_TELEMETRY_STAGE_KEEP=3 GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#469 AC8: retained staging roots are pruned to the newest KEEP (bounded, not unbounded)" "yes" \
  "$([ "$(find "$I469_PR/.prflow/tmp" -maxdepth 1 -name 'telemetry-stage-*' | wc -l | tr -d ' ')" -le 3 ] && echo yes || echo no)"
assert_eq "#469 AC8: the prune keeps the NEWEST (highest timestamp survives)" "yes" \
  "$([ -d "$I469_PR/.prflow/tmp/telemetry-stage-20000101000006-x-y-z" ] && echo yes || echo no)"
# A NON-NUMERIC _DEVFLOW_TELEMETRY_STAGE_KEEP must fall back to the default 8, NOT make the
# `-gt` arithmetic error and the prune go INERT (unbounded growth — the opposite of the bound).
# Seed 10 roots with KEEP=abc → the fallback keeps 8 (a numeric-typo override cannot defeat the bound).
I469_PRK="$(git_sandbox "#469 stage-prune non-numeric-keep repo")"; git -C "$I469_PRK" init -q
git -C "$I469_PRK" config user.email t@e.com; git -C "$I469_PRK" config user.name t
mkdir -p "$I469_PRK/.prflow/tmp"; printf 'tmp/\n' > "$I469_PRK/.prflow/.gitignore"
git -C "$I469_PRK" add -A; git -C "$I469_PRK" commit -qm seed 2>/dev/null || true
for _p in 01 02 03 04 05 06 07 08 09 10; do mkdir -p "$I469_PRK/.prflow/tmp/telemetry-stage-200001010000$_p-x-y-z"; done
( cd "$I469_PRK" && _DEVFLOW_TELEMETRY_STAGE_KEEP=abc GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#469 AC8: a non-numeric _DEVFLOW_TELEMETRY_STAGE_KEEP falls back to 8 (prune stays bounded, not inert)" "yes" \
  "$([ "$(find "$I469_PRK/.prflow/tmp" -maxdepth 1 -name 'telemetry-stage-*' | wc -l | tr -d ' ')" -le 8 ] && echo yes || echo no)"
# An ALL-DIGIT but LEADING-ZERO KEEP (`08`, `09`) passes the `*[!0-9]*` non-digit check yet is an
# INVALID OCTAL literal (#469 review): before the base-10 normalization the `$(( … - _keep ))`
# prune arithmetic aborted with "value too great for base" and — under efficiency-trace.sh's
# `set -euo pipefail` — killed do_persist at the prune line, BEFORE the rm loop, leaving all 10
# roots AND losing the run's telemetry. The fix normalizes with `10#`, so the prune completes and
# the bound holds (≤8) and --persist still exits 0. Seed 10 roots with KEEP=08.
I469_PRO="$(git_sandbox "#469 stage-prune leading-zero-octal-keep repo")"; git -C "$I469_PRO" init -q
git -C "$I469_PRO" config user.email t@e.com; git -C "$I469_PRO" config user.name t
mkdir -p "$I469_PRO/.prflow/tmp"; printf 'tmp/\n' > "$I469_PRO/.prflow/.gitignore"
git -C "$I469_PRO" add -A; git -C "$I469_PRO" commit -qm seed 2>/dev/null || true
for _p in 01 02 03 04 05 06 07 08 09 10; do mkdir -p "$I469_PRO/.prflow/tmp/telemetry-stage-200001010000$_p-x-y-z"; done
( cd "$I469_PRO" && _DEVFLOW_TELEMETRY_STAGE_KEEP=08 GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; I469_PRO_RC=$?
assert_eq "#469 review: a leading-zero-octal KEEP (08) does NOT abort --persist on the invalid-octal arithmetic" "0" "$I469_PRO_RC"
assert_eq "#469 review: a leading-zero-octal KEEP (08) prunes (base-10 normalized) — bound holds, prune not aborted" "yes" \
  "$([ "$(find "$I469_PRO/.prflow/tmp" -maxdepth 1 -name 'telemetry-stage-*' | wc -l | tr -d ' ')" -le 8 ] && echo yes || echo no)"
# An all-digit but >= 2^63 KEEP (#469 fix-delta review): all-digit passes the case AND the base-10
# normalize, but `$(( 10#… ))` silently WRAPS an overflowing value to a NEGATIVE (bash integer
# overflow does not error), which would make `_drop = count - _keep` EXCEED the staged-array length
# and `${_stale[$_i]}` index past it under `set -u` — aborting the best-effort prune (the same
# fail-open the bound exists to prevent, re-introduced by the normalize). The `[ "$_keep" -ge 0 ] ||
# _keep=8` clamp catches the wrapped negative. Seed 10 roots, KEEP=2^64-1 → clamp to 8, prune to ≤8,
# exit 0 (no unbound-variable abort).
I469_POV="$(git_sandbox "#469 stage-prune intmax-overflow-keep repo")"; git -C "$I469_POV" init -q
git -C "$I469_POV" config user.email t@e.com; git -C "$I469_POV" config user.name t
mkdir -p "$I469_POV/.prflow/tmp"; printf 'tmp/\n' > "$I469_POV/.prflow/.gitignore"
git -C "$I469_POV" add -A; git -C "$I469_POV" commit -qm seed 2>/dev/null || true
for _p in 01 02 03 04 05 06 07 08 09 10; do mkdir -p "$I469_POV/.prflow/tmp/telemetry-stage-200001010000$_p-x-y-z"; done
( cd "$I469_POV" && _DEVFLOW_TELEMETRY_STAGE_KEEP=18446744073709551615 GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1; I469_POV_RC=$?
assert_eq "#469 fix-delta review: an intmax-overflow KEEP (2^64-1) does NOT abort --persist (wrapped-negative clamp)" "0" "$I469_POV_RC"
assert_eq "#469 fix-delta review: an intmax-overflow KEEP prunes to the clamped default (bound holds, no over-index)" "yes" \
  "$([ "$(find "$I469_POV/.prflow/tmp" -maxdepth 1 -name 'telemetry-stage-*' | wc -l | tr -d ' ')" -le 8 ] && echo yes || echo no)"
rm -rf "$I469_PR" "$I469_PRK" "$I469_PRO" "$I469_POV"

# ── Retention-note: _devflow_telemetry_retention_note reports the records LOST
# only under GITHUB_ACTIONS (the ephemeral-runner truth), and is silent off CI. ──
_i469_note() { ( eval "$1"; . "$LIB/telemetry-branch.sh"; _devflow_telemetry_retention_note ); }
assert_eq "#469: retention note under GITHUB_ACTIONS reports the records LOST for this run" "yes" \
  "$(printf '%s' "$(_i469_note 'GITHUB_ACTIONS=true')" | grep -qF 'are LOST for this run, not retained' && echo yes || echo no)"
assert_eq "#469: retention note off CI (env -u GITHUB_ACTIONS) is EMPTY (local ref survives)" "" \
  "$(env -u GITHUB_ACTIONS bash -c '. "$1"; _devflow_telemetry_retention_note' _ "$LIB/telemetry-branch.sh")"
# ── Memo-seed: the check-ref-format breadcrumb fires EXACTLY ONCE per --persist on
# an invalid telemetry.branch (a count, not presence) — do_persist seeds the branch
# resolution in the parent before any fork, so every subshell inherits one warning. ─
I469_MS="$(git_sandbox "#469 memo-seed repo")"; git -C "$I469_MS" init -q
git -C "$I469_MS" config user.email t@e.com; git -C "$I469_MS" config user.name t
mkdir -p "$I469_MS/.prflow"; printf 'tmp/\n' > "$I469_MS/.prflow/.gitignore"
printf '{"telemetry":{"branch":"bad name with spaces"}}\n' > "$I469_MS/.prflow/config.json"
git -C "$I469_MS" add -A; git -C "$I469_MS" commit -qm seed
# Multiple run dirs → multiple persist_one forks; the seed must keep the count at 1.
for _r in run-1 run-2 run-3; do
  mkdir -p "$I469_MS/.prflow/tmp/review/pr-ms/$_r"
  printf '%s' '{"iter":1,"phase3_dispatched":["a"],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
    > "$I469_MS/.prflow/tmp/review/pr-ms/$_r/iter-1.json"
done
I469_MS_ERR="$( ( cd "$I469_MS" && GITHUB_ACTIONS=true DEVFLOW_TELEMETRY_PUSH=1 bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#469: check-ref-format breadcrumb fires EXACTLY ONCE per --persist (memo seed works across forks)" "1" \
  "$(printf '%s\n' "$I469_MS_ERR" | grep -cF "config key 'telemetry.branch'")"
rm -rf "$I469_MS"

# ── AC5 tier-distinction coupled invariant (#469): the writable tiers set the push operand
# DEVFLOW_TELEMETRY_PUSH=1 at job level so their Stop-hook --persist pushes; the read-only
# auto-review tier (devflow-runner.yml) deliberately leaves it UNSET so --persist fails closed
# to staging-only. This is a "kept in sync" contract across three workflows — pin BOTH sides so
# a future edit that drops it from a writable tier (silent telemetry loss) or adds it to the
# read-only tier (a push its contents:read token can never complete) turns the suite RED. ──
_I469_WF="$LIB/../.github/workflows"
assert_eq "#469 AC5: devflow-implement.yml (writable) sets DEVFLOW_TELEMETRY_PUSH so its Stop-hook --persist pushes" "1" \
  "$(devflow_module_pin_count "DEVFLOW_TELEMETRY_PUSH: '1'" "$_I469_WF/devflow-implement.yml")"
assert_eq "#469 AC5: devflow.yml command job (writable) sets DEVFLOW_TELEMETRY_PUSH so its Stop-hook --persist pushes" "1" \
  "$(devflow_module_pin_count "DEVFLOW_TELEMETRY_PUSH: '1'" "$_I469_WF/devflow.yml")"
# The read-only tier's rationale COMMENT names the operand ("...DEVFLOW_TELEMETRY_PUSH is
# deliberately unset..."), so pin the env-KEY form (trailing colon) — present only when the
# operand is actually SET as job env — which must be ABSENT (a comment mention has no colon).
assert_eq "#469 AC5: devflow-runner.yml (read-only auto-review tier) does NOT set DEVFLOW_TELEMETRY_PUSH as job env (stays fail-closed to staging-only)" "0" \
  "$(devflow_module_pin_count "DEVFLOW_TELEMETRY_PUSH:" "$_I469_WF/devflow-runner.yml")"

# End of the telemetry section's push authorization (#469 AC5): unset so downstream
# tests see the real ambient environment again.
unset DEVFLOW_TELEMETRY_PUSH

# ────────────────────────────────────────────────────────────────────────────
echo "issue #489: cross-workflow telemetry artifact relay (upload + trusted pusher + untrusted-input validation)"
# ────────────────────────────────────────────────────────────────────────────
_489_SC="$LIB/../scripts"
_489_VAL="$_489_SC/validate-telemetry-artifact.sh"
_489_PUSH="$_489_SC/telemetry-push-artifact.sh"
_489_WF="$LIB/../.github/workflows"

# --- AC4: validator unit rejections (all-or-nothing, ::warning::, non-zero, nothing staged) ---
# Build a hostile/clean artifact dir, run the validator, and report rc + whether the out root
# received any admitted tree. A drop-whole leaves the out root's .prflow/logs ABSENT.
# _489_val <label> <expect-rc> <builder-fn>  — builder populates $ART (artifact) before validate.
_489_run_val() {  # ART OUT [env...] -> echoes "rc|staged(yes/no)"
  local art="$1" out="$2"; shift 2
  local rc
  env "$@" bash "$_489_VAL" "$art" "$out" >/dev/null 2>"$out.err"; rc=$?
  printf '%s|%s\n' "$rc" "$([ -d "$out/.prflow/logs" ] && echo yes || echo no)"
}

_489_A="$(git_sandbox "489 validator artifacts")"

# (1) clean happy path → admitted (rc 0, staged yes)
mkdir -p "$_489_A/ok/.prflow/logs/review/pr-1/run-a" "$_489_A/ok/.prflow/logs/efficiency"
printf '{"iter":1}\n' > "$_489_A/ok/.prflow/logs/review/pr-1/run-a/iter-1.json"
printf '{"schema_version":1,"slug":"pr-1"}\n' > "$_489_A/ok/.prflow/logs/efficiency/pr-1-run-a.json"
assert_eq "489/AC4: a clean artifact is admitted (rc 0, records staged)" "0|yes" \
  "$(_489_run_val "$_489_A/ok" "$_489_A/ok-out")"

# (2) malformed JSON → drop whole
mkdir -p "$_489_A/bad-json/.prflow/logs/efficiency"
printf 'not json{' > "$_489_A/bad-json/.prflow/logs/efficiency/pr-2-run-b.json"
assert_eq "489/AC4: a malformed-JSON entry drops the WHOLE artifact (rc 1, nothing staged)" "1|no" \
  "$(_489_run_val "$_489_A/bad-json" "$_489_A/bad-json-out")"
assert_eq "489/AC4: ...and emits a ::warning:: naming the drop" "yes" \
  "$(grep -qF '::warning::validate-telemetry-artifact: dropping the whole' "$_489_A/bad-json-out.err" && echo yes || echo no)"

# (3) wrong top-level type (JSON array, not object) → drop whole
mkdir -p "$_489_A/arr/.prflow/logs/efficiency"
printf '[1,2,3]\n' > "$_489_A/arr/.prflow/logs/efficiency/pr-3-run-c.json"
assert_eq "489/AC4: a non-object JSON entry drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/arr" "$_489_A/arr-out")"

# (4) efficiency record missing the shape keys → drop whole
mkdir -p "$_489_A/noshape/.prflow/logs/efficiency"
printf '{"foo":"bar"}\n' > "$_489_A/noshape/.prflow/logs/efficiency/pr-4-run-d.json"
assert_eq "489/AC4: an efficiency record without schema_version+slug drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/noshape" "$_489_A/noshape-out")"

# (5) disallowed path (outside .prflow/logs) → drop whole
mkdir -p "$_489_A/badpath/foo"
printf '{}' > "$_489_A/badpath/foo/bar.json"
assert_eq "489/AC4: an entry outside .prflow/logs/ drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/badpath" "$_489_A/badpath-out")"

# (6) disallowed depth under review/ (extra nested dir) → drop whole
mkdir -p "$_489_A/deep/.prflow/logs/review/pr-5/run-e/extra"
printf '{"iter":1}' > "$_489_A/deep/.prflow/logs/review/pr-5/run-e/extra/iter-1.json"
assert_eq "489/AC4: an over-deep review path drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/deep" "$_489_A/deep-out")"

# (7) symlink entry → drop whole
mkdir -p "$_489_A/sym/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"x"}' > "$_489_A/sym/.prflow/logs/efficiency/real-run-1.json"
ln -s /etc/passwd "$_489_A/sym/.prflow/logs/efficiency/evil-run-1.json"
assert_eq "489/AC4: a symlink entry drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/sym" "$_489_A/sym-out")"

# (8) entry-count cap → drop whole (cap forced low via env; fail-closed on the numeric override)
mkdir -p "$_489_A/many/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"a"}' > "$_489_A/many/.prflow/logs/efficiency/a-1.json"
printf '{"schema_version":1,"slug":"b"}' > "$_489_A/many/.prflow/logs/efficiency/b-1.json"
assert_eq "489/AC4: exceeding the entry-count cap drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/many" "$_489_A/many-out" DEVFLOW_TELEMETRY_MAX_ENTRIES=1)"

# (9) total-size cap → drop whole
mkdir -p "$_489_A/big/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"big","pad":"%s"}' "$(printf 'x%.0s' $(seq 1 200))" > "$_489_A/big/.prflow/logs/efficiency/big-1.json"
assert_eq "489/AC4: exceeding the total-size cap drops the whole artifact" "1|no" \
  "$(_489_run_val "$_489_A/big" "$_489_A/big-out" DEVFLOW_TELEMETRY_MAX_BYTES=10)"

# (10) a non-numeric cap override fails CLOSED to the default (does NOT disable the cap): a
# clean single small record still admits under a garbage MAX_ENTRIES (default 500 applies).
assert_eq "489/AC4: a non-numeric cap override falls back to the default (clean record still admits)" "0|yes" \
  "$(_489_run_val "$_489_A/ok" "$_489_A/ok-out2" DEVFLOW_TELEMETRY_MAX_ENTRIES=notanumber)"

# (11) absent artifact dir → inert (rc 0, nothing staged) — NOT a violation
assert_eq "489/AC4: an absent artifact dir is inert (rc 0, nothing staged)" "0|no" \
  "$(_489_run_val "$_489_A/does-not-exist" "$_489_A/absent-out")"

# (12) MAX_BYTES non-numeric override fails CLOSED to the default (does NOT disable the cap):
# the sibling of test (10), covering the more security-relevant byte cap.
assert_eq "489/AC4: a non-numeric MAX_BYTES override falls back to the default (clean record still admits)" "0|yes" \
  "$(_489_run_val "$_489_A/ok" "$_489_A/ok-out3" DEVFLOW_TELEMETRY_MAX_BYTES=notanumber)"

# (13) all-or-nothing is EXPLICIT: one valid record + one hostile entry drops the valid one too.
# `staged=no` already proves it, but assert the known-valid sibling is specifically absent so a
# future incremental-copy refactor can't regress behind a lucky directory layout.
mkdir -p "$_489_A/mix/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"keep"}\n' > "$_489_A/mix/.prflow/logs/efficiency/keep-run-1.json"
printf 'malformed{' > "$_489_A/mix/.prflow/logs/efficiency/evil-run-1.json"
_489_run_val "$_489_A/mix" "$_489_A/mix-out" >/dev/null
assert_eq "489/AC4: all-or-nothing — the VALID sibling is dropped alongside the hostile entry" "no" \
  "$([ -f "$_489_A/mix-out/.prflow/logs/efficiency/keep-run-1.json" ] && echo yes || echo no)"

# (14) Direct unit tests of the pure path predicates (sourced via DVT_LIB_ONLY). AC4 names
# `..` traversal and absolute paths explicitly, but those arms are UNREACHABLE through the
# filesystem walk (a file literally named `..` cannot exist; rel is always artifact-relative),
# so a direct call is their only honest coverage.
# The `. "$_489_VAL"` sources below name a path composed at run time from $LIB, so
# ShellCheck cannot resolve the target statically (SC1090) — the non-constant twin of
# SC1091, which the CI lint job already excludes repo-wide for the same reason. For the
# same reason DVT_LIB_ONLY reads as unused (SC2034): it is consumed by that unfollowable
# sourced helper ($_489_VAL, scripts/validate-telemetry-artifact.sh), not by this script.
_489_pathsafe() {  # rel -> "safe"/"unsafe" via _dvt_path_safe
  # shellcheck disable=SC1090,SC2034
  ( DVT_LIB_ONLY=1; . "$_489_VAL"; _dvt_path_safe "$1" && echo safe || echo unsafe )
}
_489_admitted() {  # rel -> "admit"/"deny" via _dvt_admitted
  # shellcheck disable=SC1090,SC2034
  ( DVT_LIB_ONLY=1; . "$_489_VAL"; _dvt_admitted "$1" && echo admit || echo deny )
}
assert_eq "489/AC4: _dvt_path_safe rejects a '..' traversal component (AC4 names it)" "unsafe" "$(_489_pathsafe '.prflow/logs/review/a/b/../c.json')"
assert_eq "489/AC4: _dvt_path_safe rejects an absolute path (AC4 names it)" "unsafe" "$(_489_pathsafe '/abs/path.json')"
assert_eq "489/AC4: _dvt_path_safe rejects a bare '.' component" "unsafe" "$(_489_pathsafe 'a/./b.json')"
assert_eq "489/AC4: _dvt_path_safe rejects an empty path" "unsafe" "$(_489_pathsafe '')"
assert_eq "489/AC4: _dvt_path_safe accepts a normal relative path" "safe" "$(_489_pathsafe '.prflow/logs/efficiency/x-1.json')"
assert_eq "489/AC4: _dvt_admitted admits a valid efficiency path" "admit" "$(_489_admitted '.prflow/logs/efficiency/slug-run-1.json')"
assert_eq "489/AC4: _dvt_admitted admits a valid review path" "admit" "$(_489_admitted '.prflow/logs/review/slug/run-1/iter-1.json')"
assert_eq "489/AC4: _dvt_admitted denies a path outside .prflow/logs" "deny" "$(_489_admitted 'foo/bar.json')"
assert_eq "489/AC4: _dvt_admitted denies an over-deep review path" "deny" "$(_489_admitted '.prflow/logs/review/a/b/c/d.json')"

# (15) ATTRIBUTABLE cap fail-closed: prove _dvt_num coerces a garbage/empty override to the
# DEFAULT, not to "unlimited/off" — the distinction tests (10)/(12) cannot make with a clean
# artifact (which admits under both correct fallback AND the bug). This is the real fail-closed
# guarantee for both caps (they share _dvt_num).
# shellcheck disable=SC1090,SC2034  # see the SC1090/SC2034 note above.
_489_num() { ( DVT_LIB_ONLY=1; . "$_489_VAL"; _dvt_num "$1" "$2" ); }
assert_eq "489/AC4: _dvt_num coerces a non-numeric override to the DEFAULT (not unlimited)" "500" "$(_489_num 'notanumber' 500)"
assert_eq "489/AC4: _dvt_num coerces an empty override to the DEFAULT" "500" "$(_489_num '' 500)"
assert_eq "489/AC4: _dvt_num keeps a valid numeric override" "7" "$(_489_num '7' 500)"
assert_eq "489/AC4: _dvt_num rejects a negative override, falling back to the default" "500" "$(_489_num '-3' 500)"

# (16) jq fail-closed (guard-class-2, record-shape gate): a broken/absent jq must REJECT the
# whole artifact, not silently admit an unparsed entry. Point DEVFLOW_JQ at a binary that always
# fails and confirm the clean artifact is dropped.
assert_eq "489/AC4: a broken jq (DEVFLOW_JQ=false) drops the whole artifact (fails closed)" "1|no" \
  "$(_489_run_val "$_489_A/ok" "$_489_A/ok-jqfail" DEVFLOW_JQ=/usr/bin/false)"

# (16b) wc fail-closed (guard-class-2, size-cap gate; sibling of (16)): _dvt_filesize's `wc -c`
# derivation gates admission, so a broken/absent wc must REJECT the whole artifact, not silently
# admit an unsized entry (which would bypass the size cap with a green suite). wc is not a
# preflight-guaranteed tool, so this is a real regression surface. Driven by the PATH-stub
# technique (17) — shadow `wc` with a stub that always fails — since wc is invoked by path lookup,
# not via an env override.
_489_WCROOT="$(git_sandbox "489 wc fail stub")"; mkdir -p "$_489_WCROOT/bin"
printf '#!/bin/sh\nexit 1\n' > "$_489_WCROOT/bin/wc"; chmod +x "$_489_WCROOT/bin/wc"
assert_eq "489/AC4: a broken wc (size derivation fails) drops the whole artifact (fails closed)" "1|no" \
  "$(_489_run_val "$_489_A/ok" "$_489_A/ok-wcfail" "PATH=$_489_WCROOT/bin:$PATH")"

# (18) a symlink to a DIRECTORY drops the whole artifact. The `[ -L ]`-before-`[ -d ]` ordering
# in _dvt_walk is the load-bearing reject-vs-recurse decision; a reorder that let a dir-symlink
# be recursed into (following it off-tree) would turn this RED.
_489_symdir_tgt="$(git_sandbox "489 symlink-dir target")"; mkdir -p "$_489_symdir_tgt/x"
mkdir -p "$_489_A/symdir/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"ok"}' > "$_489_A/symdir/.prflow/logs/efficiency/good-1.json"
ln -s "$_489_symdir_tgt" "$_489_A/symdir/.prflow/logs/review"
assert_eq "489/AC4: a symlinked DIRECTORY drops the whole artifact (reject before recurse)" "1|no" \
  "$(_489_run_val "$_489_A/symdir" "$_489_A/symdir-out")"

# (19) a DANGLING symlink (present link, missing target) is still SEEN and drops the artifact —
# the walk's `[ -e ] || [ -L ]` condition exists precisely so a dangling link isn't skipped.
mkdir -p "$_489_A/dangling/.prflow/logs/efficiency"
ln -s /no/such/target "$_489_A/dangling/.prflow/logs/efficiency/dead-1.json"
assert_eq "489/AC4: a DANGLING symlink drops the whole artifact (still seen, never skipped)" "1|no" \
  "$(_489_run_val "$_489_A/dangling" "$_489_A/dangling-out")"

# (20) a hostile filename containing whitespace/newline drops the whole artifact. The validator
# header advertises NUL-safe array handling of such names; that name can only travel the reject
# path (the allowlist's `[A-Za-z0-9._-]+` segment rejects it), which is exactly where a quoting
# regression would misbehave — so the walk must handle it without word-splitting.
mkdir -p "$_489_A/wsname/.prflow/logs/efficiency"
printf '{}' > "$_489_A/wsname/.prflow/logs/efficiency/bad name.json"
assert_eq "489/AC4: a filename with whitespace drops the whole artifact (NUL-safe walk, allowlist rejects)" "1|no" \
  "$(_489_run_val "$_489_A/wsname" "$_489_A/wsname-out")"
mkdir -p "$_489_A/nlname/.prflow/logs/efficiency"
printf '{}' > "$_489_A/nlname/.prflow/logs/efficiency/$(printf 'evil\nrun').json"
assert_eq "489/AC4: a filename with an embedded newline drops the whole artifact (NUL-safe walk)" "1|no" \
  "$(_489_run_val "$_489_A/nlname" "$_489_A/nlname-out")"

# (21) Sug#1: the entry-count cap SHORT-CIRCUITS the walk (bounds work/memory, not just
# admission). With the cap forced to 1 and two records, the walk rejects mid-walk naming the
# short-circuit, rather than materializing every entry before the post-walk cap trips.
_489_run_val "$_489_A/many" "$_489_A/many-sc-out" DEVFLOW_TELEMETRY_MAX_ENTRIES=1 >/dev/null
assert_eq "489/AC4(Sug#1): the count cap short-circuits the walk (names it)" "yes" \
  "$(grep -qF 'walk short-circuited' "$_489_A/many-sc-out.err" && echo yes || echo no)"

# (22) Sug#5: _dvt_path_safe restores the caller's noglob state — call it from a glob-OFF caller
# (set -f) and confirm noglob is still on afterward (the predicate must be self-contained and
# never clobber a glob-off caller; the save/restore around its IFS split is otherwise untested).
# shellcheck disable=SC1090,SC2034  # see the SC1090/SC2034 note above.
_489_noglob_restore() { ( DVT_LIB_ONLY=1; . "$_489_VAL"; set -f; _dvt_path_safe '.prflow/logs/efficiency/x-1.json' >/dev/null; case "$-" in *f*) echo on ;; *) echo off ;; esac ); }
assert_eq "489/AC4(Sug#5): _dvt_path_safe restores a glob-OFF caller's noglob state" "on" "$(_489_noglob_restore)"

# (23) a special file (FIFO) is neither a regular file nor a directory → drop whole, naming that
# distinct disposition (the one enumerated reject arm otherwise uncovered). `mkfifo` is POSIX;
# skip cleanly if it is unavailable on the host rather than failing the suite.
if command -v mkfifo >/dev/null 2>&1; then
  mkdir -p "$_489_A/fifo/.prflow/logs/efficiency"
  mkfifo "$_489_A/fifo/.prflow/logs/efficiency/pipe-1.json" 2>/dev/null || true
  if [ -p "$_489_A/fifo/.prflow/logs/efficiency/pipe-1.json" ]; then
    assert_eq "489/AC4: a FIFO special file drops the whole artifact (rc 1, nothing staged)" "1|no" \
      "$(_489_run_val "$_489_A/fifo" "$_489_A/fifo-out")"
    # Attribute the rejection to the special-file arm (not a precondition) by its distinct message.
    assert_eq "489/AC4: ...naming the 'neither a regular file nor a directory' disposition" "yes" \
      "$(grep -qF 'neither a regular file nor a directory' "$_489_A/fifo-out.err" && echo yes || echo no)"
  fi
fi

# (24) Sug#1: the DIRECTORY-count cap short-circuits the walk (bounds the directory dimension of
# work, not just file admission). A wide all-empty-directories tree under the cap of 1 rejects
# mid-walk naming the directory short-circuit — the file-count guard alone never fires here (no
# regular files exist), so this proves the separate directory bound.
mkdir -p "$_489_A/widedirs/.prflow/logs/review/a/b" "$_489_A/widedirs/.prflow/logs/review/c/d"
_489_run_val "$_489_A/widedirs" "$_489_A/widedirs-out" DEVFLOW_TELEMETRY_MAX_ENTRIES=1 >/dev/null
assert_eq "489/AC4(Sug#1): the directory-count cap short-circuits the walk (names it)" "yes" \
  "$(grep -qF 'directory count exceeds the cap' "$_489_A/widedirs-out.err" && echo yes || echo no)"

# (25) Sug#2: the per-entry `_dvt_filesize` unreadable reject NAMES the specific entry (the size
# derivation gates admission and fails closed). Drive it via the wc-fail stub against a
# single-entry artifact so the reject is reached per-entry and its entry-naming message is pinned
# (test 16b proves the drop; this pins the distinct per-entry attribution).
mkdir -p "$_489_A/onesize/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"one"}' > "$_489_A/onesize/.prflow/logs/efficiency/one-1.json"
_489_run_val "$_489_A/onesize" "$_489_A/onesize-out" "PATH=$_489_WCROOT/bin:$PATH" >/dev/null
assert_eq "489/AC4(Sug#2): the per-entry unreadable reject names the specific entry" "yes" \
  "$(grep -qF "could not be sized (unreadable)" "$_489_A/onesize-out.err" && grep -qF "entry '.prflow/logs/efficiency/one-1.json'" "$_489_A/onesize-out.err" && echo yes || echo no)"

# (26) Sug#3: the pass-2 `cp` failure reject arm — a validated artifact whose per-entry copy
# fails drops whole (rc 1) naming the copy failure. This cannot admit a bad artifact (pass-1
# already passed); it only refuses to stage a good one, so fail-closed here is correct. Driven
# by the injected-cp-stub technique the collect test (17) already uses.
_489_CPROOT="$(git_sandbox "489 validator cp-fail")"; mkdir -p "$_489_CPROOT/bin"
printf '#!/bin/sh\nexit 1\n' > "$_489_CPROOT/bin/cp"; chmod +x "$_489_CPROOT/bin/cp"
_489_run_val "$_489_A/ok" "$_489_A/ok-cpfail" "PATH=$_489_CPROOT/bin:$PATH" >/dev/null
assert_eq "489/AC4(Sug#3): a pass-2 cp failure drops the whole artifact naming the copy failure" "yes" \
  "$(grep -qF 'could not copy admitted entry' "$_489_A/ok-cpfail.err" && echo yes || echo no)"

# (17) collect helper's copy-failure branch (saw_stage set, found not → the distinct 'records
# existed but none could be copied' warning). Driven deterministically by pointing DEST_PARENT
# read-only is not reachable (the top mkdir would abort first), and a chmod-000 source is
# environment-sensitive under the suite's process context, so this branch is verified by an
# INJECTED cp override rather than a real permission failure: shadow `cp` with a stub that
# always fails, so the per-stage copy fails while the stage is genuinely present (saw_stage=1).
_489_CFROOT="$(git_sandbox "489 collect copy-fail root")"
mkdir -p "$_489_CFROOT/.prflow/tmp/telemetry-stage-x/.prflow/logs/efficiency" "$_489_CFROOT/bin"
printf '{"schema_version":1,"slug":"a"}\n' > "$_489_CFROOT/.prflow/tmp/telemetry-stage-x/.prflow/logs/efficiency/a-1.json"
printf '#!/bin/sh\nexit 1\n' > "$_489_CFROOT/bin/cp"; chmod +x "$_489_CFROOT/bin/cp"
_489_CF_OUT="$(PATH="$_489_CFROOT/bin:$PATH" bash "$_489_SC/collect-staged-telemetry.sh" "$_489_CFROOT" "$_489_CFROOT/out" 2>/dev/null)"
_489_CF_ERR="$(PATH="$_489_CFROOT/bin:$PATH" bash "$_489_SC/collect-staged-telemetry.sh" "$_489_CFROOT" "$_489_CFROOT/out" 2>&1 >/dev/null)"
assert_eq "489/AC2: collect helper emits NO stdout signal when every copy fails" "" "$_489_CF_OUT"
assert_eq "489/AC2: collect helper names the copy-failure distinctly (not 'nothing staged')" "yes" \
  "$(printf '%s' "$_489_CF_ERR" | grep -qF 'records existed but none could be copied' && echo yes || echo no)"

# AC2 — the upload step MUST include hidden files: the collected tree is entirely under the
# dot-prefixed .prflow/, and upload-artifact@v4 excludes hidden files by default, so without
# this the relay would silently transfer zero telemetry.
devflow_module_pin_unique "489/AC2: the telemetry upload includes hidden files (.prflow/ is dot-prefixed)" \
  'include-hidden-files: true' "$_489_WF/devflow-runner.yml"

# --- AC3/AC4: end-to-end — a hostile artifact leaves the telemetry branch UNCHANGED, a clean
# one lands, and an empty one is inert. Drive the trusted pusher against a fixture repo. ---
_489_BARE="$(git_sandbox "489 e2e bare remote")"; git init -q --bare "$_489_BARE"
_489_REPO="$(git_sandbox "489 e2e repo")"
git -C "$_489_REPO" init -q
git -C "$_489_REPO" config user.email t@e.com; git -C "$_489_REPO" config user.name t
git -C "$_489_REPO" remote add origin "$_489_BARE"
mkdir -p "$_489_REPO/.prflow"; printf 'tmp/\n' > "$_489_REPO/.prflow/.gitignore"
git -C "$_489_REPO" add -A; git -C "$_489_REPO" commit -qm seed
git -C "$_489_REPO" push -q origin HEAD >/dev/null 2>&1 || true

# Clean push lands the records.
_489_CART="$(git_sandbox "489 clean artifact")"
mkdir -p "$_489_CART/.prflow/logs/efficiency" "$_489_CART/.prflow/logs/review/pr-9/run-z"
printf '{"schema_version":1,"slug":"pr-9"}\n' > "$_489_CART/.prflow/logs/efficiency/pr-9-run-z.json"
printf '{"iter":1}\n' > "$_489_CART/.prflow/logs/review/pr-9/run-z/iter-1.json"
( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_PUSH" "$_489_CART" "$_489_REPO" ) >/dev/null 2>&1
assert_eq "489/AC3: a clean artifact's records land on the telemetry branch" "yes" \
  "$(_et_on_branch "$_489_REPO" ".prflow/logs/efficiency/pr-9-run-z.json")"
_489_TIP="$(git -C "$_489_REPO" rev-parse refs/heads/prflow-telemetry 2>/dev/null)"

# Each hostile artifact leaves the branch tip UNCHANGED (nothing committed).
_489_hostile_tip_unchanged() {  # label builder-cmd... — runs pusher, echoes yes/no tip-unchanged
  # $1 is a human label the call sites pass for readability; the fixture this runs
  # against is selected by $_489_HART, so the label is consumed by nothing here. It
  # is shifted off rather than bound to an unread local (SC2034 under the strict
  # module lint, which — unlike lib/test/run.sh's own step — keeps extended analysis on).
  shift
  ( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null "$@" bash "$_489_PUSH" "$_489_HART" "$_489_REPO" ) >/dev/null 2>&1
  [ "$(git -C "$_489_REPO" rev-parse refs/heads/prflow-telemetry 2>/dev/null)" = "$_489_TIP" ] && echo yes || echo no
}

_489_HART="$(git_sandbox "489 hostile malformed")"; mkdir -p "$_489_HART/.prflow/logs/efficiency"
printf 'garbage{' > "$_489_HART/.prflow/logs/efficiency/evil-run-1.json"
assert_eq "489/AC4: a malformed-JSON artifact leaves the branch UNCHANGED (nothing committed)" "yes" \
  "$(_489_hostile_tip_unchanged malformed)"

_489_HART="$(git_sandbox "489 hostile traversal")"; mkdir -p "$_489_HART/evilsub"
printf '{}' > "$_489_HART/evilsub/x.json"
assert_eq "489/AC4: a disallowed-path artifact leaves the branch UNCHANGED" "yes" \
  "$(_489_hostile_tip_unchanged traversal)"

_489_HART="$(git_sandbox "489 hostile symlink")"; mkdir -p "$_489_HART/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"ok"}' > "$_489_HART/.prflow/logs/efficiency/good-run-1.json"
ln -s /etc/passwd "$_489_HART/.prflow/logs/efficiency/evil-run-1.json"
assert_eq "489/AC4: a symlink-bearing artifact leaves the branch UNCHANGED" "yes" \
  "$(_489_hostile_tip_unchanged symlink)"

_489_HART="$(git_sandbox "489 hostile oversized")"; mkdir -p "$_489_HART/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"big","pad":"%s"}' "$(printf 'x%.0s' $(seq 1 200))" > "$_489_HART/.prflow/logs/efficiency/big-run-1.json"
assert_eq "489/AC4: an oversized artifact leaves the branch UNCHANGED" "yes" \
  "$(_489_hostile_tip_unchanged oversized DEVFLOW_TELEMETRY_MAX_BYTES=10)"

# (Sug#5) further hostile SHAPES exercised end-to-end (branch tip unchanged), not only at the
# validator-unit level: a non-object record, an over-deep review path, and the entry-count cap.
_489_HART="$(git_sandbox "489 hostile non-object")"; mkdir -p "$_489_HART/.prflow/logs/efficiency"
printf '[1,2,3]' > "$_489_HART/.prflow/logs/efficiency/arr-run-1.json"
assert_eq "489/AC4(Sug#5): a non-object-JSON artifact leaves the branch UNCHANGED (e2e)" "yes" \
  "$(_489_hostile_tip_unchanged nonobject)"
_489_HART="$(git_sandbox "489 hostile over-deep")"; mkdir -p "$_489_HART/.prflow/logs/review/pr-x/run-y/extra"
printf '{"iter":1}' > "$_489_HART/.prflow/logs/review/pr-x/run-y/extra/iter-1.json"
assert_eq "489/AC4(Sug#5): an over-deep review-path artifact leaves the branch UNCHANGED (e2e)" "yes" \
  "$(_489_hostile_tip_unchanged overdeep)"
_489_HART="$(git_sandbox "489 hostile count cap")"; mkdir -p "$_489_HART/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"a"}' > "$_489_HART/.prflow/logs/efficiency/a-1.json"
printf '{"schema_version":1,"slug":"b"}' > "$_489_HART/.prflow/logs/efficiency/b-1.json"
assert_eq "489/AC4(Sug#5): an over-count artifact leaves the branch UNCHANGED (e2e)" "yes" \
  "$(_489_hostile_tip_unchanged countcap DEVFLOW_TELEMETRY_MAX_ENTRIES=1)"

# Inert on an EMPTY artifact (landing-order: intermediate state pushes nothing and says so).
_489_HART="$(git_sandbox "489 empty artifact")"
_489_EMPTY_ERR="$( ( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_PUSH" "$_489_HART" "$_489_REPO" ) 2>&1 1>/dev/null )"
assert_eq "489/AC3: an EMPTY artifact pushes nothing and leaves the branch UNCHANGED" "yes" \
  "$([ "$(git -C "$_489_REPO" rev-parse refs/heads/prflow-telemetry 2>/dev/null)" = "$_489_TIP" ] && echo yes || echo no)"
assert_eq "489/AC3: ...and says so (a 'no telemetry records to push' notice)" "yes" \
  "$(printf '%s' "$_489_EMPTY_ERR" | grep -qF 'no telemetry records to push' && echo yes || echo no)"

# Inert on an ABSENT artifact dir too (older review run with no upload).
_489_ABSENT_ERR="$( ( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_PUSH" "$_489_REPO/.no-such-dl" "$_489_REPO" ) 2>&1 1>/dev/null )"
assert_eq "489/AC3: an ABSENT artifact dir leaves the branch UNCHANGED" "yes" \
  "$([ "$(git -C "$_489_REPO" rev-parse refs/heads/prflow-telemetry 2>/dev/null)" = "$_489_TIP" ] && echo yes || echo no)"

# Fail-LOUD environment guards (the trusted writer must exit 1 red, not silently no-op, on a
# broken invocation — the contract at the file head). These arms are otherwise unexercised.
_489_pusher_rc() { ( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_PUSH" "$@" ) >/dev/null 2>&1; echo $?; }
assert_eq "489/AC3: the pusher fails LOUD (rc 1) on a usage error (missing operands)" "1" \
  "$(_489_pusher_rc)"
assert_eq "489/AC3: the pusher fails LOUD (rc 1) when repo_root is not a git working tree" "1" \
  "$(_489_pusher_rc "$_489_CART" "$(git_sandbox '489 non-git repo_root')")"
_489_NONGIT_ERR="$( ( cd "$_489_REPO" && DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_PUSH" "$_489_CART" "$(git_sandbox '489 non-git repo_root msg')" ) 2>&1 1>/dev/null )"
assert_eq "489/AC3: ...naming the not-a-git-working-tree cause (::error::, fail loud)" "yes" \
  "$(printf '%s' "$_489_NONGIT_ERR" | grep -qF 'is not a git working tree' && echo yes || echo no)"

# Fail-LOUD source/guard arms (guard-class-1) + the exec-fault distinction (Sug#2). Copy the
# pusher + validator into a sandbox with a SWAPPABLE lib/, so we can drive the source-failure
# `exit 1` arms and — most notably — the `declare -F devflow_telemetry_persist_tree`
# undefined-after-source guard added specifically to prevent a silent no-op. All otherwise
# unexercised (the trusted writer's "refuse to silently drop telemetry" contract).
_489_SBX="$(git_sandbox "489 pusher lib sandbox")"
mkdir -p "$_489_SBX/scripts" "$_489_SBX/lib"
cp "$_489_PUSH" "$_489_SBX/scripts/telemetry-push-artifact.sh"
cp "$_489_VAL" "$_489_SBX/scripts/validate-telemetry-artifact.sh"
printf '%s\n' ': "${DEVFLOW_JQ:=jq}"' > "$_489_SBX/lib/resolve-jq.sh"   # minimal working stub
_489_SBX_REPO="$(git_sandbox "489 pusher sandbox repo")"; git -C "$_489_SBX_REPO" init -q
_489_SBX_ART="$(git_sandbox "489 pusher sandbox artifact")"
mkdir -p "$_489_SBX_ART/.prflow/logs/efficiency"
printf '{"schema_version":1,"slug":"s"}' > "$_489_SBX_ART/.prflow/logs/efficiency/s-1.json"
_489_sbx_pusher() {  # needle -> "rc|matched(yes/no)" for a breadcrumb the run must emit
  local needle="$1" err rc
  err="$( DEVFLOW_CONFIG_FILE=/dev/null bash "$_489_SBX/scripts/telemetry-push-artifact.sh" "$_489_SBX_ART" "$_489_SBX_REPO" 2>&1 1>/dev/null )"; rc=$?
  printf '%s|%s\n' "$rc" "$(printf '%s' "$err" | grep -qF "$needle" && echo yes || echo no)"
}
# (a) config-source.sh source failure → fail loud rc 1.
printf 'return 1\n' > "$_489_SBX/lib/config-source.sh"
printf 'devflow_telemetry_persist_tree() { return 0; }\n' > "$_489_SBX/lib/telemetry-branch.sh"
assert_eq "489/AC3(fail-loud): a config-source.sh source failure exits 1 loud" "1|yes" \
  "$(_489_sbx_pusher 'could not source lib/config-source.sh')"
# (b) telemetry-branch.sh source failure → fail loud rc 1.
printf 'return 0\n' > "$_489_SBX/lib/config-source.sh"
printf 'return 1\n' > "$_489_SBX/lib/telemetry-branch.sh"
assert_eq "489/AC3(fail-loud): a telemetry-branch.sh source failure exits 1 loud" "1|yes" \
  "$(_489_sbx_pusher 'could not source lib/telemetry-branch.sh')"
# (c) guard-class-1: telemetry-branch.sh sources cleanly but does NOT define the write function
# → the declare -F guard fails loud rc 1 (the silent no-op this guard exists to stop).
printf 'return 0\n' > "$_489_SBX/lib/telemetry-branch.sh"   # sources OK, defines nothing
assert_eq "489/AC3(guard-class-1): undefined devflow_telemetry_persist_tree after source exits 1 loud" "1|yes" \
  "$(_489_sbx_pusher 'devflow_telemetry_persist_tree is undefined')"
# (d) Sug#2: a validator that CANNOT EXECUTE (chmod -x → rc 126) is reported as a deployment
# fault distinctly from a legitimate content drop (still best-effort exit 0).
chmod -x "$_489_SBX/scripts/validate-telemetry-artifact.sh"
assert_eq "489/AC4(Sug#2): a non-executable validator (rc 126) is named a deployment fault, exit 0" "0|yes" \
  "$(_489_sbx_pusher 'could not be executed')"
chmod +x "$_489_SBX/scripts/validate-telemetry-artifact.sh"
# (e/f) Sug#5: the pusher's `case "$rc"` degraded (rc=1) and staging-only (rc=2) notice arms —
# covered only at the unit level before. Define the write function to RETURN each code and
# confirm the matching warning fires (still best-effort exit 0). config-source.sh stays a
# clean-source stub from arm (b); only the write function's return code varies.
printf 'devflow_telemetry_persist_tree() { return 1; }\n' > "$_489_SBX/lib/telemetry-branch.sh"
assert_eq "489/AC3(Sug#5): persist rc=1 → 'telemetry push degraded' warning, exit 0" "0|yes" \
  "$(_489_sbx_pusher 'telemetry push degraded')"
printf 'devflow_telemetry_persist_tree() { return 2; }\n' > "$_489_SBX/lib/telemetry-branch.sh"
assert_eq "489/AC3(Sug#5): persist rc=2 → 'staging-only despite DEVFLOW_TELEMETRY_PUSH=1' warning, exit 0" "0|yes" \
  "$(_489_sbx_pusher 'staging-only despite DEVFLOW_TELEMETRY_PUSH=1')"

# --- AC2/AC3: workflow content pins ---
# AC2 — the read-only review runner uploads its staged telemetry as a workflow artifact.
devflow_module_pin_unique "489/AC2: devflow-runner.yml collects the staged telemetry tree" \
  'Collect staged telemetry artifacts' "$_489_WF/devflow-runner.yml"
devflow_module_pin_unique "489/AC2: devflow-runner.yml uploads the staged telemetry artifact" \
  'name: prflow-telemetry-stage-${{ github.run_id }}-${{ github.run_attempt }}' "$_489_WF/devflow-runner.yml"
# F-c — the DOWNLOAD side of the relay was unpinned. The consumer names the artifact via the
# workflow_run context, where workflow_run.id/.run_attempt resolve to the triggering run's
# run_id/run_attempt — i.e. the exact values the upload names by. Pin the download name too, so a
# drift on the CONSUMER side (mistyped stem, dropped -<attempt> segment, swapped id/attempt order)
# is caught rather than making download-artifact match nothing and the relay transfer ZERO telemetry
# with only the indistinguishable benign-no-artifact warning (the same silent-zero-transfer class the
# upload-side F2/S2c pins guard).
devflow_module_pin_unique "489/AC3(F-c): telemetry-push.yml downloads the artifact by the run-scoped stage name" \
  'name: prflow-telemetry-stage-${{ github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}' "$_489_WF/telemetry-push.yml"
# Coupled invariant (producer↔consumer): BOTH files must carry the byte-identical
# `prflow-telemetry-stage-` stem. A rename on either side alone breaks the join; asserting the stem
# is present in each file catches that skew (each side pinned independently, so the failing side names itself).
assert_eq "489/AC3(F-c): the UPLOAD side carries the prflow-telemetry-stage- artifact-name stem" "1" \
  "$(grep -cF 'name: prflow-telemetry-stage-' "$_489_WF/devflow-runner.yml")"
assert_eq "489/AC3(F-c): the DOWNLOAD side carries the SAME prflow-telemetry-stage- stem (producer↔consumer coupling)" "1" \
  "$(grep -cF 'name: prflow-telemetry-stage-' "$_489_WF/telemetry-push.yml")"
devflow_module_pin_unique "489/AC2/#502: the collect step resolves the vendored collect helper first (consumer portability — bare repo-relative scripts/ path was absent in consumers)" \
  '.prflow/vendor/prflow/scripts/collect-staged-telemetry.sh' "$_489_WF/devflow-runner.yml"

# AC2 collect helper (extracted from the workflow so the suite can drive it): consolidates every
# staged .prflow/logs subtree into <dest>, prints "1" iff it collected something, best-effort.
_489_COLLECT="$_489_SC/collect-staged-telemetry.sh"
_489_CROOT="$(git_sandbox "489 collect fixture root")"
mkdir -p "$_489_CROOT/.prflow/tmp/telemetry-stage-20260101-1/.prflow/logs/efficiency" \
         "$_489_CROOT/.prflow/tmp/telemetry-stage-20260101-2/.prflow/logs/review/pr-7/run-q"
printf '{"schema_version":1,"slug":"a"}\n' > "$_489_CROOT/.prflow/tmp/telemetry-stage-20260101-1/.prflow/logs/efficiency/a-1.json"
printf '{"iter":1}\n' > "$_489_CROOT/.prflow/tmp/telemetry-stage-20260101-2/.prflow/logs/review/pr-7/run-q/iter-1.json"
_489_CDEST="$_489_CROOT/out"
_489_CSIG="$(bash "$_489_COLLECT" "$_489_CROOT" "$_489_CDEST" 2>/dev/null)"
assert_eq "489/AC2: collect helper signals it collected staged telemetry" "1" "$_489_CSIG"
assert_eq "489/AC2: collect helper merges the efficiency record into the upload tree" "yes" \
  "$([ -f "$_489_CDEST/.prflow/logs/efficiency/a-1.json" ] && echo yes || echo no)"
assert_eq "489/AC2: collect helper merges a review record from a SECOND staging root" "yes" \
  "$([ -f "$_489_CDEST/.prflow/logs/review/pr-7/run-q/iter-1.json" ] && echo yes || echo no)"
# No staged dirs → empty signal (nothing to upload), still exit 0.
_489_CEMPTY="$(git_sandbox "489 collect empty root")"; mkdir -p "$_489_CEMPTY/.prflow/tmp"
_489_CEMPTY_SIG="$(bash "$_489_COLLECT" "$_489_CEMPTY" "$_489_CEMPTY/out" 2>/dev/null; echo "rc=$?")"
assert_eq "489/AC2: collect helper is empty-signal + exit 0 when nothing is staged" "rc=0" "$_489_CEMPTY_SIG"

# AC3 — the trusted pusher workflow: workflow_run trigger, App-token minted ABOVE checkout,
# cross-run download by run-id, never checks out the PR head.
assert_eq "489/AC3: telemetry-push.yml exists" "yes" \
  "$([ -f "$_489_WF/telemetry-push.yml" ] && echo yes || echo no)"
devflow_module_pin_unique "489/AC3: pusher is triggered by the auto-review workflow's completion (workflow_run)" \
  'workflows: ["Devflow Review (auto-trigger)"]' "$_489_WF/telemetry-push.yml"
devflow_module_pin_unique "489/AC3: pusher declares actions:read for cross-run artifact download" \
  'actions: read' "$_489_WF/telemetry-push.yml"
# App token minted ABOVE checkout (#357): the mint step precedes the checkout step in the file.
_489_MINT_LN="$(grep -n 'uses: actions/create-github-app-token@v3' "$_489_WF/telemetry-push.yml" | head -1 | cut -d: -f1)"
_489_CO_LN="$(grep -n 'uses: actions/checkout@v6' "$_489_WF/telemetry-push.yml" | head -1 | cut -d: -f1)"
assert_eq "489/AC3(#357): the App token is minted ABOVE the checkout" "yes" \
  "$([ -n "$_489_MINT_LN" ] && [ -n "$_489_CO_LN" ] && [ "$_489_MINT_LN" -lt "$_489_CO_LN" ] && echo yes || echo no)"
devflow_module_pin_unique "489/AC3: pusher seeds the App token as the checkout credential" \
  'token: ${{ steps.app-token.outputs.token }}' "$_489_WF/telemetry-push.yml"
devflow_module_pin_unique "489/AC3: pusher downloads the triggering run's artifact by run-id" \
  'run-id: ${{ github.event.workflow_run.id }}' "$_489_WF/telemetry-push.yml"
devflow_module_pin_unique "489/AC3: pusher checks out the DEFAULT branch, never the PR head" \
  'ref: ${{ github.event.repository.default_branch }}' "$_489_WF/telemetry-push.yml"
devflow_module_pin_unique "489/AC3/#502: pusher resolves the vendored validate+push helper first (consumer portability — bare repo-relative scripts/ path was absent in consumers)" \
  '.prflow/vendor/prflow/scripts/telemetry-push-artifact.sh' "$_489_WF/telemetry-push.yml"
# Endpoint↔permission: the pusher makes NO inline `gh api` call (git push via App token +
# download-artifact via github.token/actions:read), so no additional token permission is owed.
assert_eq "489/AC3(endpoint↔permission): pusher adds no inline gh api call needing an undeclared permission" "0" \
  "$(devflow_module_pin_count 'gh api' "$_489_WF/telemetry-push.yml")"

# ── PR #495 round-4 review notes: S1 collect-step exit-status + S2 workflow-condition coverage ──
# These close the YAML-condition coverage gaps the reviewer named. The rc-capture dispatch below
# MUST stay inline in the collect step (it detects the collect helper's OWN non-existence, so it
# cannot be delegated to a further script that could be equally absent). The workflow-surface
# checks below preserve the inline dispatch, while ordinary fixtures cover executable behavior.
#
# S1 — the collect step gates on the helper's EXIT STATUS, not stdout alone. The helper is
# contracted to always exit 0, so a non-zero rc is a genuine exec fault (rc 126 not-executable /
# 127 not-found — a partial/path-skewed deployment where collect-staged-telemetry.sh cannot run),
# yielding empty stdout; gating on stdout alone would launder that real telemetry drop into the
# benign no-op notice (mirrors the sibling telemetry-push-artifact.sh's rc-126/127 discipline).
# The rc-127 (not-found) half is the more common path-skewed-deployment fault and is checked
# independently of rc-126 so an absent helper cannot fall through to the benign no-op notice.
devflow_module_pin_unique "489/AC2(S1): the exec-fault branch names it a deployment fault distinctly" \
  'could not be executed (rc $_collect_rc' "$_489_WF/devflow-runner.yml"
# Sibling arm: the trusted pusher's own validator-exec-fault case must cover BOTH rc 126 AND 127.
# The behavioral test (d) above exercises rc 126 (chmod -x); the source check separately
# preserves the rc-127 arm.

# S2(a) — the download-failure warning gates on outcome == 'failure'; the source checks
# preserve both the condition and its diagnostic.
assert_eq "489/AC3(S2a): the Warn-on-download-failure step gates on outcome == 'failure'" "1" \
  "$(grep -cF "if: \${{ steps.download.outcome == 'failure' }}" "$_489_WF/telemetry-push.yml" || true)"
devflow_module_pin_unique "489/AC3(S2a): the download-failure warning names the outcome=failure cause" \
  'download failed (outcome=failure)' "$_489_WF/telemetry-push.yml"

# S2(b) — the relay is DELIBERATELY un-gated on the triggering run's conclusion: the review tier's
# collect + upload steps run `if: always()`, so a review run that concluded FAILURE (the engine hit
# a fatal/permission cut-off) may still have staged telemetry worth relaying. Pin that NO conclusion
# gate exists, so a future edit adding `workflow_run.conclusion == 'success'` — which would silently
# drop telemetry from errored review runs — is caught. The push job's ONLY gate is the App floor.
assert_eq "489/AC3(S2b): the relay does NOT gate on the triggering run's conclusion (relays on all completions)" "0" \
  "$(devflow_module_pin_count 'workflow_run.conclusion' "$_489_WF/telemetry-push.yml")"
assert_eq "489/AC3(S2b): ...and carries no bare 'conclusion ==' gate either" "0" \
  "$(devflow_module_pin_count 'conclusion ==' "$_489_WF/telemetry-push.yml")"
assert_eq "489/AC3(S2b): the push job's ONLY gate is the App-configured floor" "1" \
  "$(grep -cF "if: \${{ vars.DEVFLOW_APP_ID != '' }}" "$_489_WF/telemetry-push.yml" || true)"

# S2(c) — the upload step's source condition requires a non-empty collected path.
assert_eq "489/AC2(S2c): the upload step gates on a non-empty collected path" "1" \
  "$(grep -cF "if: always() && steps.collect_telemetry.outputs.path != ''" "$_489_WF/devflow-runner.yml" || true)"

# F2 — the collect step's HAPPY PATH: the non-empty-stdout arm wires the collected tree's path into
# GITHUB_OUTPUT, which the S2c upload gate above then reads. The S2c pin covers the DOWNSTREAM gate;
# nothing covered the UPSTREAM `path=` emission. Breaking the output key (so `outputs.path` stays
# empty and the gate never fires) would make the relay upload ZERO telemetry with no error — the
# silent-transfer-nothing class the `include-hidden-files` comment nearby also guards.


# ── issue #499 telemetry normalization (non-contiguous in lib/test/run.sh) ────
# Moved with this region rather than left behind: every one of its persistence
# assertions reads the `_et_show` helper defined above, so the two blocks are one
# unit — leaving it in the monolith would have left a call with no callee.

# ── issue #499: unavailable telemetry is explicit and falsy-safe ───────────
T499_DIR="$(probe_tmp '#499 telemetry normalization fixture')"
rm -f "$T499_DIR"
mkdir -p "$T499_DIR"
printf '%s' '{"iter":1,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":false}' > "$T499_DIR/iter-1.json"
printf '%s' '{"iter":2,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0}}' > "$T499_DIR/iter-2.json"
printf '%s' '{"iter":3,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' > "$T499_DIR/iter-3.json"
printf '%s' '{"iter":4,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{}}' > "$T499_DIR/iter-4.json"
T499_REC="$(bash "$LIB/efficiency-trace.sh" --workpad-dir "$T499_DIR" --slug issue-499 --mode record)"
assert_eq "#499 record: boolean false is established and preserved" "false" "$(printf '%s' "$T499_REC" | jq -r '.telemetry[0].phases')"
assert_eq "#499 record: absent telemetry becomes unavailable" "unavailable" "$(printf '%s' "$T499_REC" | jq -r '.telemetry[1].phases')"
assert_eq "#499 record: null telemetry becomes unavailable" "unavailable" "$(printf '%s' "$T499_REC" | jq -r '.telemetry[2].phases')"
assert_eq "#499 record: explicit empty object is established and preserved" "object" "$(printf '%s' "$T499_REC" | jq -r '.telemetry[3].phases | type')"
T499_EMPTY="$(probe_tmp '#499 absent telemetry branch fixture')"
rm -f "$T499_EMPTY"
mkdir -p "$T499_EMPTY"
printf '%s\n' '{"telemetry":{"branch":"issue-499-definitely-absent"}}' > "$T499_EMPTY/config.json"
T499_ERR="$(DEVFLOW_CONFIG_FILE="$T499_EMPTY/config.json" bash "$LIB/../scripts/backfill-telemetry-unavailable.sh" 2>&1)"; T499_RC=$?
assert_eq "#499 backfill: absent telemetry branch is best-effort exit 0" "0" "$T499_RC"
assert_eq "#499 backfill: absent telemetry branch has a named breadcrumb" "yes" "$(printf '%s' "$T499_ERR" | grep -qF 'telemetry ref is absent or unresolvable' && echo yes || echo no)"
rm -rf "$T499_DIR" "$T499_EMPTY"

# Persist integration: exercise the full iter boundary at the durable-copy seam,
# including byte preservation, sibling exclusion from stamping, source immutability,
# and the second-run tree no-op.
T499_P="$(git_sandbox '#499 persist matrix repo')"
git -C "$T499_P" init -q
git -C "$T499_P" config user.email t@e.com; git -C "$T499_P" config user.name t
mkdir -p "$T499_P/.prflow/tmp/review/pr-499/run-matrix"
for row in \
  '1|{"iter":1,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{"x":1}}' \
  '2|{"iter":2,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":false}' \
  '3|{"iter":3,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0}}' \
  '4|{"iter":4,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":null}' \
  '5|{"iter":5,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":{}}' \
  '6|{"iter":6,"phase3_dispatched":[],"phase3_findings":[],"convergence_inputs":{"fixes_applied":0},"telemetry":"legacy"}'; do
  n="${row%%|*}"; printf '%s' "${row#*|}" > "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-$n.json"
done
printf 'null' > "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-7.json"
printf '{"keep":true}' > "$T499_P/.prflow/tmp/review/pr-499/run-matrix/deferrals.json"
T499_SRC_BEFORE="$(find "$T499_P/.prflow/tmp/review/pr-499/run-matrix" -type f -exec shasum {} + | sort)"
T499_P_ERR="$( ( cd "$T499_P" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
T499_TIP1="$(git -C "$T499_P" rev-parse prflow-telemetry)"
( cd "$T499_P" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
T499_TIP2="$(git -C "$T499_P" rev-parse prflow-telemetry)"
assert_eq "#499 persist: M3 absent is stamped" "unavailable" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-3.json' | jq -r '.telemetry')"
assert_eq "#499 persist: M4 null is stamped" "unavailable" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-4.json' | jq -r '.telemetry')"
assert_eq "#499 persist: established false survives" "false" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-2.json' | jq -r '.telemetry')"
assert_eq "#499 persist: populated object survives" '{"x":1}' "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-1.json' | jq -c '.telemetry')"
assert_eq "#499 persist: established empty object survives" '{}' "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-5.json' | jq -c '.telemetry')"
assert_eq "#499 persist: established wrong-type string survives" 'legacy' "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-6.json' | jq -r '.telemetry')"
assert_eq "#499 persist: whole-file null stays byte-verbatim" "null" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-7.json')"
assert_eq "#499 persist: non-object warning is named" "yes" "$(printf '%s' "$T499_P_ERR" | grep -qF 'valid non-object' && echo yes || echo no)"
assert_eq "#499 persist: sibling JSON is copied but never stamped" '{"keep":true}' "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/deferrals.json')"
assert_eq "#499 persist: source run directory is byte-identical" "$T499_SRC_BEFORE" "$(find "$T499_P/.prflow/tmp/review/pr-499/run-matrix" -type f -exec shasum {} + | sort)"
assert_eq "#499 persist: second run is a telemetry-branch no-op" "$T499_TIP1" "$T499_TIP2"
# Established telemetry paths remain eligible for ordinary metadata refreshes.
jq '.later_metadata = true' "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-2.json" > "$T499_P/iter.tmp" && mv "$T499_P/iter.tmp" "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-2.json"
( cd "$T499_P" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#499 persist: established telemetry path still carries later metadata" "true" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-2.json' | jq -r '.later_metadata')"
# A prior unavailable marker is provisional: real telemetry established later
# must upgrade it rather than being overwritten by the historical marker.
jq '.telemetry = false' "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-3.json" > "$T499_P/iter.tmp" && mv "$T499_P/iter.tmp" "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-3.json"
( cd "$T499_P" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#499 persist: prior marker upgrades to newly established false" "false" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-3.json' | jq -r '.telemetry')"
# Information monotonicity: a retained/stale source that loses its key must not
# downgrade an already-established durable value to the unavailable marker.
jq 'del(.telemetry) | .later_metadata = "stale-source"' "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-2.json" > "$T499_P/iter.tmp" && mv "$T499_P/iter.tmp" "$T499_P/.prflow/tmp/review/pr-499/run-matrix/iter-2.json"
( cd "$T499_P" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) >/dev/null 2>&1
assert_eq "#499 persist: established durable telemetry rejects a staged absent-key downgrade" "false" "$(_et_show "$T499_P" '.prflow/logs/review/pr-499/run-matrix/iter-2.json' | jq -r '.telemetry')"
rm -rf "$T499_P"

# Pre-existing legacy and non-object durable paths remain backfill-owned, and a
# malformed staged copy cannot replace an established durable object.
T499_O="$(git_sandbox '#499 existing durable collision repo')"
git -C "$T499_O" init -q; git -C "$T499_O" config user.email t@e.com; git -C "$T499_O" config user.name t
mkdir -p "$T499_O/seed/.prflow/logs/review/pr-499/run-existing" "$T499_O/.prflow/tmp/review/pr-499/run-existing"
printf '%s' '{"iter":1}' > "$T499_O/seed/.prflow/logs/review/pr-499/run-existing/iter-1.json"
printf '%s' 'null' > "$T499_O/seed/.prflow/logs/review/pr-499/run-existing/iter-2.json"
printf '%s' '{"iter":3,"telemetry":{"calls":1}}' > "$T499_O/seed/.prflow/logs/review/pr-499/run-existing/iter-3.json"
( cd "$T499_O" && unset GITHUB_ACTIONS && . "$LIB/config-source.sh" && . "$LIB/telemetry-branch.sh" && devflow_telemetry_persist_tree "$T499_O" "$T499_O/seed" ) >/dev/null 2>&1
printf '%s' '{"iter":1,"telemetry":{"calls":2}}' > "$T499_O/.prflow/tmp/review/pr-499/run-existing/iter-1.json"
printf '%s' '{"iter":2,"telemetry":{"calls":2}}' > "$T499_O/.prflow/tmp/review/pr-499/run-existing/iter-2.json"
printf '%s' 'null' > "$T499_O/.prflow/tmp/review/pr-499/run-existing/iter-3.json"
T499_O_ERR="$( ( cd "$T499_O" && env -u GITHUB_ACTIONS bash "$LIB/efficiency-trace.sh" --persist ) 2>&1 1>/dev/null )"
assert_eq "#499 persist: existing legacy durable blob remains byte-verbatim" '{"iter":1}' "$(_et_show "$T499_O" '.prflow/logs/review/pr-499/run-existing/iter-1.json')"
assert_eq "#499 persist: existing non-object durable blob remains byte-verbatim" 'null' "$(_et_show "$T499_O" '.prflow/logs/review/pr-499/run-existing/iter-2.json')"
assert_eq "#499 persist: malformed staged copy cannot replace established durable blob" '{"calls":1}' "$(_et_show "$T499_O" '.prflow/logs/review/pr-499/run-existing/iter-3.json' | jq -c '.telemetry')"
assert_eq "#499 persist: every dropped collision has a named breadcrumb" "yes" "$(printf '%s' "$T499_O_ERR" | grep -qF 'backfill-owned historical blob' && printf '%s' "$T499_O_ERR" | grep -qF 'could not be safely classified' && printf '%s' "$T499_O_ERR" | grep -qF 'leaving the established durable blob untouched' && echo yes || echo no)"
rm -rf "$T499_O"

# Existing legacy durable paths remain backfill-owned: a normal persist removes
# them from its overlay, so both an ordinary repeat and a CAS retry cannot undo a
# concurrent migration.

# Populated backfill integration: seed legacy iter/record families through the
# shared staged-tree writer, then run the shipped maintainer script from a repo-
# local copy (so its HERE/root resolution matches an installed consumer).
T499_B="$(git_sandbox '#499 populated backfill repo')"
git -C "$T499_B" init -q; git -C "$T499_B" config user.email t@e.com; git -C "$T499_B" config user.name t
mkdir -p "$T499_B/lib" "$T499_B/scripts" "$T499_B/seed/.prflow/logs/review/pr-499/run-b" "$T499_B/seed/.prflow/logs/efficiency"
cp "$LIB/resolve-jq.sh" "$LIB/config-source.sh" "$LIB/telemetry-branch.sh" "$T499_B/lib/"
cp "$LIB/../scripts/config-get.sh" "$LIB/../scripts/backfill-telemetry-unavailable.sh" "$T499_B/scripts/"
printf '%s' '{"iter":1,"phase3_findings":[]}' > "$T499_B/seed/.prflow/logs/review/pr-499/run-b/iter-1.json"
printf '%s' 'null' > "$T499_B/seed/.prflow/logs/review/pr-499/run-b/iter-7.json"
printf '%s' '{"telemetry":[{"iter":1,"phases":null},{"iter":2}]}' > "$T499_B/seed/.prflow/logs/efficiency/selected.json"
printf '%s' '{"telemetry":"wrong"}' > "$T499_B/seed/.prflow/logs/efficiency/wrong.json"
printf '%s' '{"telemetry":[false]}' > "$T499_B/seed/.prflow/logs/efficiency/nonobject.json"
( cd "$T499_B" && unset GITHUB_ACTIONS && . ./lib/config-source.sh && . ./lib/telemetry-branch.sh && devflow_telemetry_persist_tree "$T499_B" "$T499_B/seed" ) >/dev/null 2>&1
T499_B_BEFORE_WRONG="$(_et_show "$T499_B" '.prflow/logs/efficiency/wrong.json')"
T499_B_BEFORE_NONOBJ="$(_et_show "$T499_B" '.prflow/logs/efficiency/nonobject.json')"
T499_B_BEFORE_M7="$(_et_show "$T499_B" '.prflow/logs/review/pr-499/run-b/iter-7.json')"
T499_B_ERR="$( ( cd "$T499_B" && env -u GITHUB_ACTIONS bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
T499_B_TIP1="$(git -C "$T499_B" rev-parse prflow-telemetry)"
( cd "$T499_B" && env -u GITHUB_ACTIONS bash ./scripts/backfill-telemetry-unavailable.sh ) >/dev/null 2>&1
T499_B_TIP2="$(git -C "$T499_B" rev-parse prflow-telemetry)"
assert_eq "#499 backfill: populated M3 iter gains marker" "unavailable" "$(_et_show "$T499_B" '.prflow/logs/review/pr-499/run-b/iter-1.json' | jq -r '.telemetry')"
assert_eq "#499 backfill: R1 null phases gains marker" "unavailable" "$(_et_show "$T499_B" '.prflow/logs/efficiency/selected.json' | jq -r '.telemetry[0].phases')"
assert_eq "#499 backfill: R2 missing phases remains absent" "false" "$(_et_show "$T499_B" '.prflow/logs/efficiency/selected.json' | jq -r '.telemetry[1] | has("phases")')"
assert_eq "#499 backfill: wrong-type record is byte-verbatim" "$T499_B_BEFORE_WRONG" "$(_et_show "$T499_B" '.prflow/logs/efficiency/wrong.json')"
assert_eq "#499 backfill: non-object entry record is byte-verbatim" "$T499_B_BEFORE_NONOBJ" "$(_et_show "$T499_B" '.prflow/logs/efficiency/nonobject.json')"
assert_eq "#499 backfill: non-object iter is byte-verbatim" "$T499_B_BEFORE_M7" "$(_et_show "$T499_B" '.prflow/logs/review/pr-499/run-b/iter-7.json')"
assert_eq "#499 backfill: malformed family breadcrumbs are named" "yes" "$(printf '%s' "$T499_B_ERR" | grep -qF '(M7)' && printf '%s' "$T499_B_ERR" | grep -qF '(R4)' && printf '%s' "$T499_B_ERR" | grep -qF '(R5)' && echo yes || echo no)"
assert_eq "#499 backfill: rerun is a branch no-op" "$T499_B_TIP1" "$T499_B_TIP2"

# Backfill operational-degradation arms are behavioral contracts, not merely
# message pins: staging-only retains relay input, and a generic writer failure
# names degradation while preserving the script's best-effort exit-0 surface.
mkdir -p "$T499_B/seed-more/.prflow/logs/review/pr-499/run-b"
printf '%s' '{"iter":2}' > "$T499_B/seed-more/.prflow/logs/review/pr-499/run-b/iter-2.json"
( cd "$T499_B" && unset GITHUB_ACTIONS && . ./lib/config-source.sh && . ./lib/telemetry-branch.sh && devflow_telemetry_persist_tree "$T499_B" "$T499_B/seed-more" ) >/dev/null 2>&1
T499_B_STAGE_ERR="$( ( cd "$T499_B" && GITHUB_ACTIONS=true env -u DEVFLOW_TELEMETRY_PUSH bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
assert_eq "#499 backfill: CI staging-only arm is behaviorally breadcrumbed" "yes" "$(printf '%s' "$T499_B_STAGE_ERR" | grep -qF 'staged only at' && echo yes || echo no)"
assert_eq "#499 backfill: CI staging-only arm retains a relay tree" "yes" "$(find "$T499_B/.prflow/tmp" -type f -path '*/telemetry-stage-backfill-*/*/iter-2.json' -print -quit | grep -q . && echo yes || echo no)"
printf '\ndevflow_telemetry_persist_tree() { return 1; }\n' >> "$T499_B/lib/telemetry-branch.sh"
T499_B_DEG_ERR="$( ( cd "$T499_B" && env -u GITHUB_ACTIONS bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
assert_eq "#499 backfill: generic writer failure is behaviorally breadcrumbed" "yes" "$(printf '%s' "$T499_B_DEG_ERR" | grep -qF 'telemetry write degraded (rc=1)' && echo yes || echo no)"
rm -rf "$T499_B"

# Each early dependency/staging failure stays attributable and best-effort.
T499_E="$(git_sandbox '#499 backfill early failures repo')"
git -C "$T499_E" init -q; git -C "$T499_E" config user.email t@e.com; git -C "$T499_E" config user.name t
mkdir -p "$T499_E/lib" "$T499_E/scripts" "$T499_E/seed/.prflow/logs/review/pr-499/run-e"
cp "$LIB/resolve-jq.sh" "$LIB/config-source.sh" "$LIB/telemetry-branch.sh" "$T499_E/lib/"
cp "$LIB/../scripts/config-get.sh" "$LIB/../scripts/backfill-telemetry-unavailable.sh" "$T499_E/scripts/"
printf '%s' '{"iter":1}' > "$T499_E/seed/.prflow/logs/review/pr-499/run-e/iter-1.json"
( cd "$T499_E" && unset GITHUB_ACTIONS && . ./lib/config-source.sh && . ./lib/telemetry-branch.sh && devflow_telemetry_persist_tree "$T499_E" "$T499_E/seed" ) >/dev/null 2>&1
mv "$T499_E/lib/resolve-jq.sh" "$T499_E/lib/resolve-jq.off"
T499_E_JQ="$( ( cd "$T499_E" && bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
mv "$T499_E/lib/resolve-jq.off" "$T499_E/lib/resolve-jq.sh"
mv "$T499_E/lib/config-source.sh" "$T499_E/lib/config-source.off"
T499_E_CFG="$( ( cd "$T499_E" && bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
mv "$T499_E/lib/config-source.off" "$T499_E/lib/config-source.sh"
mv "$T499_E/lib/telemetry-branch.sh" "$T499_E/lib/telemetry-branch.off"
T499_E_TB="$( ( cd "$T499_E" && bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
mv "$T499_E/lib/telemetry-branch.off" "$T499_E/lib/telemetry-branch.sh"
rm -rf "$T499_E/.prflow/tmp"; printf '%s' blocked > "$T499_E/.prflow/tmp"
T499_E_MK="$( ( cd "$T499_E" && bash ./scripts/backfill-telemetry-unavailable.sh ) 2>&1 1>/dev/null )"
assert_eq "#499 backfill: dependency and staging early exits are specifically breadcrumbed" "yes" "$(printf '%s' "$T499_E_JQ" | grep -qF 'could not resolve jq' && printf '%s' "$T499_E_CFG" | grep -qF 'could not source config support' && printf '%s' "$T499_E_TB" | grep -qF 'could not source telemetry-branch support' && printf '%s' "$T499_E_MK" | grep -qF 'could not create staging root' && echo yes || echo no)"
rm -rf "$T499_E"

# Remote retry union integration. Writer B and C retain the same stale local
# snapshot while writer A migrates the remote. B must preserve the normalized
# remote collision while ordinary established collisions remain local-wins.
T499_U_ROOT="$(probe_tmp '#499 union collision root')"; rm -f "$T499_U_ROOT"; mkdir -p "$T499_U_ROOT"
T499_U_REMOTE="$T499_U_ROOT/remote.git"; T499_U_A="$T499_U_ROOT/a"; T499_U_B="$T499_U_ROOT/b"; T499_U_C="$T499_U_ROOT/c"
git init -q --bare "$T499_U_REMOTE"
git init -q "$T499_U_A"; git -C "$T499_U_A" config user.email t@e.com; git -C "$T499_U_A" config user.name t
git -C "$T499_U_A" commit --allow-empty -qm seed; git -C "$T499_U_A" branch -M main; git -C "$T499_U_A" remote add origin "$T499_U_REMOTE"; git -C "$T499_U_A" push -q -u origin main
mkdir -p "$T499_U_A/legacy/.prflow/logs/review/pr-499/run-u" "$T499_U_A/legacy/.prflow/logs/efficiency"
printf '%s' '{"iter":1}' > "$T499_U_A/legacy/.prflow/logs/review/pr-499/run-u/iter-1.json"
printf '%s' '{"iter":2,"telemetry":false}' > "$T499_U_A/legacy/.prflow/logs/review/pr-499/run-u/iter-2.json"
( cd "$T499_U_A" && unset GITHUB_ACTIONS && . "$LIB/config-source.sh" && . "$LIB/telemetry-branch.sh" && devflow_telemetry_persist_tree "$T499_U_A" "$T499_U_A/legacy" ) >/dev/null 2>&1
git clone -q "$T499_U_REMOTE" "$T499_U_B"; git -C "$T499_U_B" fetch -q origin prflow-telemetry:prflow-telemetry
git clone -q "$T499_U_REMOTE" "$T499_U_C"; git -C "$T499_U_C" fetch -q origin prflow-telemetry:prflow-telemetry
mkdir -p "$T499_U_A/migrated/.prflow/logs/review/pr-499/run-u" "$T499_U_A/migrated/.prflow/logs/efficiency"
printf '%s' '{"iter":1,"telemetry":"unavailable"}' > "$T499_U_A/migrated/.prflow/logs/review/pr-499/run-u/iter-1.json"
printf '%s' '{"iter":2,"telemetry":true}' > "$T499_U_A/migrated/.prflow/logs/review/pr-499/run-u/iter-2.json"
( cd "$T499_U_A" && unset GITHUB_ACTIONS && . "$LIB/config-source.sh" && . "$LIB/telemetry-branch.sh" && devflow_telemetry_persist_tree "$T499_U_A" "$T499_U_A/migrated" ) >/dev/null 2>&1
mkdir -p "$T499_U_B/new/.prflow/logs/efficiency" "$T499_U_B/new/.prflow/logs/review/pr-499/run-u"
printf '%s' '{"slug":"writer-b"}' > "$T499_U_B/new/.prflow/logs/efficiency/writer-b.json"
printf '%s' '{"iter":1}' > "$T499_U_B/new/.prflow/logs/review/pr-499/run-u/iter-1.json"
printf '%s' '{"iter":2,"telemetry":false}' > "$T499_U_B/new/.prflow/logs/review/pr-499/run-u/iter-2.json"
T499_U_B_ERR="$( ( cd "$T499_U_B" && unset GITHUB_ACTIONS && . "$LIB/config-source.sh" && . "$LIB/telemetry-branch.sh" && devflow_telemetry_persist_tree "$T499_U_B" "$T499_U_B/new" ) 2>&1 )"
git -C "$T499_U_B" fetch -q origin prflow-telemetry
assert_eq "#499 union: normalized remote iter survives stale legacy local overlay" "unavailable" "$(git -C "$T499_U_B" show FETCH_HEAD:.prflow/logs/review/pr-499/run-u/iter-1.json | jq -r '.telemetry')"
assert_eq "#499 union: ordinary established collision remains local-wins" "false" "$(git -C "$T499_U_B" show FETCH_HEAD:.prflow/logs/review/pr-499/run-u/iter-2.json | jq -r '.telemetry')"
assert_eq "#499 union: retry also carries writer B's new blob" "writer-b" "$(git -C "$T499_U_B" show FETCH_HEAD:.prflow/logs/efficiency/writer-b.json | jq -r '.slug')"
assert_eq "#499 union: successful collision retry emits no classifier refusal" "no" "$(printf '%s' "$T499_U_B_ERR" | grep -qF 'could not classify a colliding telemetry blob' && echo yes || echo no)"

# Writer C has the same stale collision, but its classifier executable is
# unavailable. The retry must fail closed: no new remote blob and a breadcrumb.
mkdir -p "$T499_U_C/new/.prflow/logs/efficiency" "$T499_U_C/new/.prflow/logs/review/pr-499/run-u"
printf '%s' '{"slug":"writer-c"}' > "$T499_U_C/new/.prflow/logs/efficiency/writer-c.json"
printf '%s' '{"iter":1}' > "$T499_U_C/new/.prflow/logs/review/pr-499/run-u/iter-1.json"
T499_U_C_ERR="$( ( cd "$T499_U_C" && unset GITHUB_ACTIONS && . "$LIB/config-source.sh" && . "$LIB/telemetry-branch.sh" && DEVFLOW_JQ=/definitely/missing/jq devflow_telemetry_persist_tree "$T499_U_C" "$T499_U_C/new" ) 2>&1 )"
git -C "$T499_U_C" fetch -q origin prflow-telemetry
assert_eq "#499 union: classifier-unavailable retry refuses the remote write" "no" "$(git -C "$T499_U_C" cat-file -e FETCH_HEAD:.prflow/logs/efficiency/writer-c.json 2>/dev/null && echo yes || echo no)"
assert_eq "#499 union: classifier-unavailable refusal is breadcrumbed" "yes" "$(printf '%s' "$T499_U_C_ERR" | grep -qF 'could not classify a colliding telemetry blob' && echo yes || echo no)"
rm -rf "$T499_U_ROOT"

# ── Telemetry master switch (issue #2035) ────────────────────────────────────
# telemetry.enabled=false (the JSON boolean) turns off every optional telemetry
# mechanism in one switch: the five default-true enrolled sub-keys inherit it on
# their config-get.sh miss path, and the two push-path helpers skip. Only the JSON
# boolean false disables; every other state (wrong-typed, corrupt, error) fails
# safe to ON. An explicit sub-key always wins over the master.
T2035_ROOT="$(probe_tmp '#2035 telemetry master switch root')"; rm -rf "$T2035_ROOT"; mkdir -p "$T2035_ROOT"
T2035_CG="$REPO_ROOT/scripts/config-get.sh"
T2035_OFF="$REPO_ROOT/scripts/telemetry-master-off.py"
T2035_ET="$REPO_ROOT/lib/efficiency-trace.sh"
T2035_CST="$REPO_ROOT/scripts/collect-staged-telemetry.sh"

# telemetry-master-off.py — the single-source JSON-boolean-false predicate.
printf '%s' '{"telemetry":{"enabled":false}}'   > "$T2035_ROOT/m-false.json"
printf '%s' '{"telemetry":{"enabled":true}}'    > "$T2035_ROOT/m-true.json"
printf '%s' '{"telemetry":{"enabled":"false"}}' > "$T2035_ROOT/m-strfalse.json"
printf '%s' '{"telemetry":{"enabled":0}}'       > "$T2035_ROOT/m-zero.json"
printf '%s' '{"telemetry":{"enabled":null}}'    > "$T2035_ROOT/m-null.json"
printf '%s' '{"telemetry":[]}'                  > "$T2035_ROOT/m-arr.json"
printf '%s' '{"telemetry":"x"}'                 > "$T2035_ROOT/m-scalar.json"
printf '%s' '{"other":1}'                       > "$T2035_ROOT/m-missing.json"
printf '%s' 'not json{'                         > "$T2035_ROOT/m-corrupt.json"
assert_eq "#2035 predicate: JSON boolean false is OFF" "off" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-false.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: JSON boolean true is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-true.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: string 'false' is ON (JSON type, not coerced string)" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-strfalse.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: number 0 is ON (is-False not ==False)" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-zero.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: null is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-null.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: telemetry array is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-arr.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: telemetry scalar is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-scalar.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: telemetry missing is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-missing.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: corrupt config is ON (fail-safe)" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-corrupt.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: missing file is ON (fail-safe)" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/nope.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 predicate: no argument is ON (fail-safe)" "on" "$(python3 "$T2035_OFF" >/dev/null 2>&1 && echo off || echo on)"

# The three-way exit contract both shell callers route on: 0 off, 2 the config is
# there but unreadable/unparseable, 1 everything else. Folding 2 onto 1 would let a
# caller report a corrupt config as a deliberate opt-in.
python3 "$T2035_OFF" "$T2035_ROOT/m-false.json" >/dev/null 2>&1; assert_eq "#2035 predicate exit: master-off is 0" "0" "$?"
python3 "$T2035_OFF" "$T2035_ROOT/m-corrupt.json" >/dev/null 2>&1; assert_eq "#2035 predicate exit: corrupt config is 2 (indeterminate)" "2" "$?"
python3 "$T2035_OFF" "$T2035_ROOT/nope.json" >/dev/null 2>&1; assert_eq "#2035 predicate exit: absent config is 1 (plain ON, not indeterminate)" "1" "$?"
python3 "$T2035_OFF" "$T2035_ROOT/m-missing.json" >/dev/null 2>&1; assert_eq "#2035 predicate exit: readable config without the key is 1" "1" "$?"

# AC1 — master false + each enrolled sub-key absent → config-get prints "false".
assert_eq "#2035 AC1 efficiency_telemetry_enabled inherits false" "false" "$("$T2035_CG" prflow_review_and_fix.efficiency_telemetry_enabled true "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC1 execution_diagnostics_enabled inherits false" "false" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC1 execution_denial_commands_enabled inherits false" "false" "$("$T2035_CG" prflow.execution_denial_commands_enabled true "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC1 live_progress_comment_enabled inherits false" "false" "$("$T2035_CG" prflow_review.live_progress_comment_enabled true "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC1 investigation_record_enabled inherits false" "false" "$("$T2035_CG" create_issue.investigation_record_enabled true "$T2035_ROOT/m-false.json")"

# AC2 — an explicit sub-key wins over the master, in both directions.
printf '%s' '{"telemetry":{"enabled":false},"prflow":{"execution_diagnostics_enabled":true}}' > "$T2035_ROOT/p-explicit-true.json"
printf '%s' '{"prflow":{"execution_diagnostics_enabled":false}}' > "$T2035_ROOT/p-explicit-false.json"
assert_eq "#2035 AC2 explicit sub-key true beats master false" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/p-explicit-true.json")"
assert_eq "#2035 AC2 explicit sub-key false wins with master absent" "false" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/p-explicit-false.json")"

# AC3 — the seven master-key shapes: only the JSON boolean false disables an
# enrolled sub-key miss; every other shape prints the caller default.
assert_eq "#2035 AC3 master missing → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-missing.json")"
assert_eq "#2035 AC3 master array → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-arr.json")"
assert_eq "#2035 AC3 master scalar → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-scalar.json")"
assert_eq "#2035 AC3 master enabled true → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-true.json")"
assert_eq "#2035 AC3 master enabled string 'false' → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-strfalse.json")"
assert_eq "#2035 AC3 master enabled number 0 → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-zero.json")"
assert_eq "#2035 AC3 master enabled null → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-null.json")"
assert_eq "#2035 AC3 master enabled JSON false → false" "false" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-false.json")"

# AC6 — a key OUTSIDE the enrolled set is unaffected by the master: its miss-path
# stdout is byte-identical whether the master is false or absent.
assert_eq "#2035 AC6 non-enrolled key unaffected by master false" "mydefault" "$("$T2035_CG" base_branch mydefault "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC6 non-enrolled key same with master absent" "$("$T2035_CG" base_branch mydefault "$T2035_ROOT/m-missing.json")" "$("$T2035_CG" base_branch mydefault "$T2035_ROOT/m-false.json")"
# AC6 stderr clause — the miss-path STDERR (incl. the superseded-key migration
# breadcrumb) is byte-identical whether the master is false or absent, because a
# non-enrolled key hits telemetry_master_disables_for's `case *) return 1` before
# any output. Use a non-enrolled key WITH a superseded counterpart (prflow_runner
# ← devflow_runner) so the breadcrumb actually fires, and the SAME config path in
# both reads so the path embedded in the breadcrumb cannot differ.
T2035_NE_SUP="$T2035_ROOT/ne-sup.json"
printf '%s' '{"telemetry":{"enabled":false},"devflow_runner":{"legacy_key":true}}' > "$T2035_NE_SUP"
T2035_NE_ERR_OFF="$("$T2035_CG" prflow_runner.legacy_key d "$T2035_NE_SUP" 2>&1 >/dev/null)"
printf '%s' '{"devflow_runner":{"legacy_key":true}}' > "$T2035_NE_SUP"
T2035_NE_ERR_ABSENT="$("$T2035_CG" prflow_runner.legacy_key d "$T2035_NE_SUP" 2>&1 >/dev/null)"
assert_eq "#2035 AC6 non-enrolled superseded breadcrumb fires (positive control)" "yes" "$(printf '%s' "$T2035_NE_ERR_OFF" | grep -qF 'superseded counterpart' && echo yes || echo no)"
assert_eq "#2035 AC6 non-enrolled miss-path stderr byte-identical under master-false vs absent" "$T2035_NE_ERR_ABSENT" "$T2035_NE_ERR_OFF"

# Residual — the resolver's exit-code contract is undisturbed under master-off.
# Use a repo-root-resolved fixture dir so a no-default call is expressible.
mkdir -p "$T2035_ROOT/cfgdir/.prflow"
cp "$T2035_ROOT/m-false.json" "$T2035_ROOT/cfgdir/.prflow/config.json"
( cd "$T2035_ROOT/cfgdir" && "$T2035_CG" nonexistent.key ) >/dev/null 2>&1
assert_eq "#2035 exit contract: non-enrolled no-default miss exits 1 under master-off" "1" "$?"
( cd "$T2035_ROOT/cfgdir" && "$T2035_CG" nonexistent.key fallback ) >/dev/null 2>&1
assert_eq "#2035 exit contract: non-enrolled with default exits 0 under master-off" "0" "$?"
assert_eq "#2035 enrolled inherit via repo-root config resolution" "false" "$( ( cd "$T2035_ROOT/cfgdir" && "$T2035_CG" prflow.execution_diagnostics_enabled true ) )"
# Ordering — an ENROLLED key with NO caller default under master-off prints
# "false" and exits 0, because telemetry_master_disables_for runs before the
# has_default branch in emit_default_or_fail. Pins that a no-default enrolled miss
# is not the non-enrolled exit-1 path.
T2035_ENROLLED_NODEF="$( ( cd "$T2035_ROOT/cfgdir" && "$T2035_CG" prflow.execution_diagnostics_enabled ) 2>/dev/null )"
T2035_ENROLLED_NODEF_RC=$?
assert_eq "#2035 exit contract: enrolled no-default miss prints false under master-off" "false" "$T2035_ENROLLED_NODEF"
assert_eq "#2035 exit contract: enrolled no-default miss exits 0 under master-off" "0" "$T2035_ENROLLED_NODEF_RC"
# Idempotency — two master-off resolutions of the same enrolled key are identical.
assert_eq "#2035 idempotent enrolled resolution" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-false.json")" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-false.json")"

# Matrix residual — a telemetry OBJECT present but `enabled` absent (the realistic
# config shape holding only `telemetry.branch`) is the missing-sub-key shape: the
# predicate reads tel.get("enabled") as None, so it is ON, and an enrolled miss
# prints the caller default.
printf '%s' '{"telemetry":{"branch":"prflow-telemetry"}}' > "$T2035_ROOT/m-noenabled.json"
assert_eq "#2035 predicate: telemetry object present but enabled absent is ON" "on" "$(python3 "$T2035_OFF" "$T2035_ROOT/m-noenabled.json" >/dev/null 2>&1 && echo off || echo on)"
assert_eq "#2035 master enabled-absent (telemetry object present) → default" "true" "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-noenabled.json")"

# Ordering — the master check runs AFTER probe_superseded_key, so an enrolled key
# absent-but-with-its-superseded-spelling-present still emits the migration
# breadcrumb even when the master disables it. This pins the emit_default_or_fail
# ordering: master-off must not short-circuit the superseded-key probe.
printf '%s' '{"telemetry":{"enabled":false},"devflow":{"execution_diagnostics_enabled":true}}' > "$T2035_ROOT/m-false-superseded.json"
T2035_SUP_OUT="$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-false-superseded.json" 2>"$T2035_ROOT/sup-err.txt")"
assert_eq "#2035 ordering: master-off still prints false for an absent enrolled key" "false" "$T2035_SUP_OUT"
assert_eq "#2035 ordering: migration breadcrumb still fires under master-off (probe before master)" "yes" "$(grep -qF 'superseded counterpart' "$T2035_ROOT/sup-err.txt" && echo yes || echo no)"

# AC4 — the push path: --persist under master-off leaves the telemetry branch ref
# UNMOVED and still exits 0. A real bare-remote git repo (git plumbing not mocked),
# with a positive control (master-absent) proving the guard is not vacuous.
_t2035_persist() { # $1=config-file → prints "<exit>|<branch-created yes/no>|<skip yes/no>"
  local cfg="$1" pr root wd err rc created skip announced
  pr="$T2035_ROOT/persist-$RANDOM$RANDOM"
  root="$pr/repo"
  git init -q --bare "$pr/remote.git"
  git init -q "$root"; git -C "$root" config user.email t@e.com; git -C "$root" config user.name t
  git -C "$root" commit --allow-empty -qm seed; git -C "$root" branch -M main
  git -C "$root" remote add origin "$pr/remote.git"; git -C "$root" push -q -u origin main
  cp "$cfg" "$root/.prflow-cfg.json"
  wd="$root/.prflow/tmp/review/pr-2035/run-1"; mkdir -p "$wd"
  printf '%s' '{"iter":1,"fix_commit_sha":"","loop_role":"fix"}' > "$wd/iter-1.json"
  err="$( ( cd "$root" && unset GITHUB_ACTIONS && DEVFLOW_CONFIG_FILE="$root/.prflow-cfg.json" bash "$T2035_ET" --persist --workpad-dir "$wd" --slug pr-2035 ) 2>&1 )"
  rc=$?
  if git -C "$root" rev-parse --verify --quiet refs/heads/prflow-telemetry >/dev/null 2>&1; then created=yes; else created=no; fi
  if printf '%s' "$err" | grep -qF 'telemetry.enabled is false'; then skip=yes; else skip=no; fi
  if printf '%s' "$err" | grep -qF 'was NOT consulted'; then announced=yes; else announced=no; fi
  printf '%s|%s|%s|%s' "$rc" "$created" "$skip" "$announced"
}
T2035_PERSIST_OFF="$(_t2035_persist "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC4 --persist master-off exits 0" "0" "${T2035_PERSIST_OFF%%|*}"
assert_eq "#2035 AC4 --persist master-off leaves telemetry branch uncreated" "no" "$(printf '%s' "$T2035_PERSIST_OFF" | cut -d'|' -f2)"
assert_eq "#2035 AC4 --persist master-off emits the skip breadcrumb" "yes" "$(printf '%s' "$T2035_PERSIST_OFF" | cut -d'|' -f3)"
T2035_PERSIST_ON="$(_t2035_persist "$T2035_ROOT/m-missing.json")"
assert_eq "#2035 AC5 --persist master-absent exits 0" "0" "${T2035_PERSIST_ON%%|*}"
assert_eq "#2035 AC5 --persist master-absent creates the telemetry branch (positive control)" "yes" "$(printf '%s' "$T2035_PERSIST_ON" | cut -d'|' -f2)"
assert_eq "#2035 AC5 --persist master-absent emits no skip breadcrumb" "no" "$(printf '%s' "$T2035_PERSIST_ON" | cut -d'|' -f3)"
T2035_PERSIST_CORRUPT="$(_t2035_persist "$T2035_ROOT/m-corrupt.json")"
assert_eq "#2035 AC5 --persist corrupt-config exits 0 (fail-safe on)" "0" "${T2035_PERSIST_CORRUPT%%|*}"
assert_eq "#2035 AC5 --persist corrupt-config does not skip (fail-safe on)" "no" "$(printf '%s' "$T2035_PERSIST_CORRUPT" | cut -d'|' -f3)"
assert_eq "#2035 --persist announces the unconsulted master switch on a corrupt config" "yes" "$(printf '%s' "$T2035_PERSIST_CORRUPT" | cut -d'|' -f4)"
assert_eq "#2035 --persist announces nothing when the switch WAS consulted (positive control)" "no" "$(printf '%s' "$T2035_PERSIST_OFF" | cut -d'|' -f4)"

# AC4 — collect-staged-telemetry.sh stages no payload under master-off, and its
# positive control (master-absent) collects the staged payload.
_t2035_collect() { # $1=config-file → prints "<stdout>|<breadcrumb yes/no>"
  local cfg="$1" cr stage dest out err
  cr="$T2035_ROOT/collect-$RANDOM$RANDOM"; mkdir -p "$cr/.prflow"
  cp "$cfg" "$cr/.prflow/config.json"
  stage="$cr/.prflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1"; mkdir -p "$stage"
  printf '%s' '{}' > "$stage/iter-1.json"
  dest="$cr/upload"
  out="$(bash "$T2035_CST" "$cr" "$dest" 2>"$cr/err.txt")"
  if grep -qF 'telemetry.enabled is false' "$cr/err.txt"; then err=yes; else err=no; fi
  printf '%s|%s' "$out" "$err"
}
T2035_COLLECT_OFF="$(_t2035_collect "$T2035_ROOT/m-false.json")"
assert_eq "#2035 AC4 collect-staged master-off stages nothing" "" "${T2035_COLLECT_OFF%%|*}"
assert_eq "#2035 AC4 collect-staged master-off emits breadcrumb" "yes" "$(printf '%s' "$T2035_COLLECT_OFF" | cut -d'|' -f2)"
T2035_COLLECT_ON="$(_t2035_collect "$T2035_ROOT/m-missing.json")"
assert_eq "#2035 AC4 collect-staged master-absent collects (positive control)" "1" "${T2035_COLLECT_ON%%|*}"
# Fail-safe symmetry with the --persist path: a corrupt config collects (ON) and
# emits no skip breadcrumb — the predicate exits 1 (indeterminate → ON) so the
# collector runs as if the master were unset.
T2035_COLLECT_CORRUPT="$(_t2035_collect "$T2035_ROOT/m-corrupt.json")"
assert_eq "#2035 AC5 collect-staged corrupt-config collects (fail-safe on)" "1" "${T2035_COLLECT_CORRUPT%%|*}"
assert_eq "#2035 AC5 collect-staged corrupt-config emits no skip breadcrumb" "no" "$(printf '%s' "$T2035_COLLECT_CORRUPT" | cut -d'|' -f2)"

# The master switch not being CONSULTED is a distinct outcome from it being read
# as ON, and it is announced. Without this the two gates fail open in silence and
# an operator who set telemetry.enabled=false cannot tell the switch was ignored.
T2035_NOPY_DIR="$T2035_ROOT/nopy"
mkdir -p "$T2035_NOPY_DIR"
T2035_BASH_ABS="$(command -v bash)"
T2035_CR_NOPY="$T2035_ROOT/collect-nopy"
mkdir -p "$T2035_CR_NOPY/.prflow"
cp "$T2035_ROOT/m-false.json" "$T2035_CR_NOPY/.prflow/config.json"
mkdir -p "$T2035_CR_NOPY/.prflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1"
printf '%s' '{}' > "$T2035_CR_NOPY/.prflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1/iter-1.json"
# PATH points at an EMPTY dir so `command -v python3` genuinely misses; bash is
# invoked by absolute path because a cleared PATH cannot resolve `bash` itself.
( PATH="$T2035_NOPY_DIR" "$T2035_BASH_ABS" "$T2035_CST" "$T2035_CR_NOPY" "$T2035_CR_NOPY/upload" ) >/dev/null 2>"$T2035_CR_NOPY/err.txt"
assert_eq "#2035 collect-staged announces an unconsulted master switch when python3 is absent" "yes" \
  "$(grep -qF 'master switch was NOT consulted' "$T2035_CR_NOPY/err.txt" && echo yes || echo no)"

T2035_HELPERLESS="$T2035_ROOT/helperless"
mkdir -p "$T2035_HELPERLESS"
cp "$T2035_CST" "$T2035_HELPERLESS/collect-staged-telemetry.sh"
T2035_CR_NOHELP="$T2035_ROOT/collect-nohelp"
mkdir -p "$T2035_CR_NOHELP/.prflow"
cp "$T2035_ROOT/m-false.json" "$T2035_CR_NOHELP/.prflow/config.json"
bash "$T2035_HELPERLESS/collect-staged-telemetry.sh" "$T2035_CR_NOHELP" "$T2035_CR_NOHELP/upload" >/dev/null 2>"$T2035_CR_NOHELP/err.txt"
assert_eq "#2035 collect-staged announces an unconsulted master switch when the predicate script is absent" "yes" \
  "$(grep -qF 'master switch was NOT consulted' "$T2035_CR_NOHELP/err.txt" && echo yes || echo no)"

# DEVFLOW_CONFIG_FILE reaches the collect gate, as it already does --persist: the
# two push-path gates must not disagree about where the master switch lives.
T2035_CR_ENVCFG="$T2035_ROOT/collect-envcfg"
mkdir -p "$T2035_CR_ENVCFG/.prflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1"
printf '%s' '{}' > "$T2035_CR_ENVCFG/.prflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1/iter-1.json"
printf '%s' '{}' > "$T2035_CR_ENVCFG/.prflow/config.json"
assert_eq "#2035 collect-staged honors DEVFLOW_CONFIG_FILE for the master switch" "" \
  "$( DEVFLOW_CONFIG_FILE="$T2035_ROOT/m-false.json" bash "$T2035_CST" "$T2035_CR_ENVCFG" "$T2035_CR_ENVCFG/upload" 2>/dev/null )"

# The issue-#1002 state-dir read-through reaches this gate too: a consumer still on
# .devflow/ who sets the master false must not have their payload uploaded anyway.
T2035_CR_DEVFLOW="$T2035_ROOT/collect-devflow"
mkdir -p "$T2035_CR_DEVFLOW/.devflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1"
cp "$T2035_ROOT/m-false.json" "$T2035_CR_DEVFLOW/.devflow/config.json"
printf '%s' '{}' > "$T2035_CR_DEVFLOW/.devflow/tmp/telemetry-stage-1/.prflow/logs/review/pr-2035/run-1/iter-1.json"
bash "$T2035_CST" "$T2035_CR_DEVFLOW" "$T2035_CR_DEVFLOW/upload" >/dev/null 2>"$T2035_CR_DEVFLOW/err.txt"
assert_eq "#2035 collect-staged honors a superseded .devflow/ config for the master switch" "yes" \
  "$(grep -qF 'telemetry.enabled is false' "$T2035_CR_DEVFLOW/err.txt" && echo yes || echo no)"

# A sub-key present as JSON null reaches the resolver's miss path exactly as an
# absent one does, so it inherits too — the schema and docs say so, and this pins it.
printf '%s' '{"telemetry":{"enabled":false},"prflow":{"execution_diagnostics_enabled":null}}' > "$T2035_ROOT/m-subnull.json"
assert_eq "#2035 a sub-key set to JSON null inherits the master-off resolution" "false" \
  "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-subnull.json")"

# A config the gate could not read is indistinguishable from master-on at the
# predicate's exit code, so the collector announces it rather than collecting as a
# silent opt-in. Corrupt JSON is the uid-independent case; the permission case is
# expectation-matched to whether this uid actually loses the read, because root and
# some filesystems ignore the mode bit and an unconditional "yes" is a false RED.
T2035_CR_CORRUPT="$T2035_ROOT/collect-corrupt"
mkdir -p "$T2035_CR_CORRUPT/.prflow"
cp "$T2035_ROOT/m-corrupt.json" "$T2035_CR_CORRUPT/.prflow/config.json"
bash "$T2035_CST" "$T2035_CR_CORRUPT" "$T2035_CR_CORRUPT/upload" >/dev/null 2>"$T2035_CR_CORRUPT/err.txt"
assert_eq "#2035 collect-staged announces a corrupt config instead of collecting silently" "yes" \
  "$(grep -qF 'could not be read or parsed' "$T2035_CR_CORRUPT/err.txt" && echo yes || echo no)"

T2035_CR_OK="$T2035_ROOT/collect-readable"
mkdir -p "$T2035_CR_OK/.prflow"
cp "$T2035_ROOT/m-missing.json" "$T2035_CR_OK/.prflow/config.json"
bash "$T2035_CST" "$T2035_CR_OK" "$T2035_CR_OK/upload" >/dev/null 2>"$T2035_CR_OK/err.txt"
assert_eq "#2035 collect-staged announces nothing when the switch WAS consulted (positive control)" "no" \
  "$(grep -qF 'was NOT consulted' "$T2035_CR_OK/err.txt" && echo yes || echo no)"

T2035_CR_UNREAD="$T2035_ROOT/collect-unreadable"
mkdir -p "$T2035_CR_UNREAD/.prflow"
cp "$T2035_ROOT/m-false.json" "$T2035_CR_UNREAD/.prflow/config.json"
chmod 000 "$T2035_CR_UNREAD/.prflow/config.json"
if [ -r "$T2035_CR_UNREAD/.prflow/config.json" ]; then T2035_UNREAD_EXP="no"; else T2035_UNREAD_EXP="yes"; fi
bash "$T2035_CST" "$T2035_CR_UNREAD" "$T2035_CR_UNREAD/upload" >/dev/null 2>"$T2035_CR_UNREAD/err.txt"
assert_eq "#2035 collect-staged announces an unreadable config instead of collecting silently" "$T2035_UNREAD_EXP" \
  "$(grep -qF 'could not be read or parsed' "$T2035_CR_UNREAD/err.txt" && echo yes || echo no)"
chmod 644 "$T2035_CR_UNREAD/.prflow/config.json"

# An empty-string sub-key reaches the resolver's miss path exactly as an absent or
# JSON-null one does, so it inherits too — the schema and docs say so, and this pins it.
printf '%s' '{"telemetry":{"enabled":false},"prflow":{"execution_diagnostics_enabled":""}}' > "$T2035_ROOT/m-subempty.json"
assert_eq "#2035 a sub-key set to an empty string inherits the master-off resolution" "false" \
  "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-subempty.json")"
assert_eq "#2035 an empty-string sub-key without the master still takes the default (positive control)" "true" \
  "$("$T2035_CG" prflow.execution_diagnostics_enabled true "$T2035_ROOT/m-missing.json")"

rm -rf "$T2035_ROOT"

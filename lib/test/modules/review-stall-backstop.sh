# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable review stall-backstop contract module (issue #746 tranche).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module.
REPO_ROOT="$LIB/.."

# ────────────────────────────────────────────────────────────────────────────
echo "#408 cloud review no-verdict auto-resume backstop"
# ────────────────────────────────────────────────────────────────────────────
# request-review-backstop.sh owns the whole fire/no-fire decision (config read,
# verdict guard, per-head attempt count, App-token guard, marker construction), so
# every arm is drivable here with a stubbed gh + config fixtures. RED pre-change
# (the helper does not exist → `bash <missing>` prints nothing / exits 127, so each
# assert_eq fails). The guarantee-class arm is the decisive one: an incomplete
# verdict with no prior attempts and an App token present MUST decide `fire`, or the
# whole backstop is a no-op on exactly the input it exists to catch.
RRB408="$REPO_ROOT/scripts/request-review-backstop.sh"
T408="$(mktemp -d)"
# gh stubs — single executables (DEVFLOW_GH must be one token). Each answers the
# issue-comments endpoint (marker count) and `repo view`.
cat > "$T408/gh-empty.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
cat > "$T408/gh-2markers.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=abc attempt=1 -->"},{"body":"<!-- devflow:review-backstop head=abc attempt=2 -->"},{"body":"<!-- devflow:review-backstop head=zzz attempt=9 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
cat > "$T408/gh-foreign.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=zzz attempt=1 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
cat > "$T408/gh-fail.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo "HTTP 500" >&2; exit 1 ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$T408"/*.sh
printf '%s\n' '{"prflow_review":{"stall_backstop":{"enabled":false,"max_resume_attempts":2}}}' > "$T408/cfg-disabled.json"
printf '%s\n' '{"prflow_review":{"stall_backstop":{"enabled":true,"max_resume_attempts":2}}}' > "$T408/cfg-enabled.json"
# rrb408 <gh-stub> <verdict> <head> <pr> <repo> <app-present> [config-file] -> emits `decision=` value
rrb408() {
  DEVFLOW_GH="$T408/$1" VERDICT="$2" HEAD_SHA="$3" PR_NUMBER="$4" REPO="$5" APP_TOKEN_PRESENT="$6" CONFIG_FILE="${7:-}" \
    bash "$RRB408" 2>/dev/null | sed -n 's/^decision=//p'
}
rrb408_reason() {
  DEVFLOW_GH="$T408/$1" VERDICT="$2" HEAD_SHA="$3" PR_NUMBER="$4" REPO="$5" APP_TOKEN_PRESENT="$6" CONFIG_FILE="${7:-}" \
    bash "$RRB408" 2>/dev/null | sed -n 's/^reason=//p'
}
# Guarantee-class: success-with-no-verdict must decide fire.
assert_eq "#408 helper: incomplete + under cap + App token -> fire (guarantee-class success-no-verdict path)" \
  "fire" "$(rrb408 gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
# A positively-observed verdict is a decided end — never resume (both directions).
assert_eq "#408 helper: verdict approve -> no-fire (never resume a decided verdict)" \
  "no-fire" "$(rrb408 gh-empty.sh approve abc 5 o/r true "$T408/cfg-enabled.json")"
assert_eq "#408 helper: verdict approve -> reason verdict-exists" \
  "verdict-exists" "$(rrb408_reason gh-empty.sh approve abc 5 o/r true "$T408/cfg-enabled.json")"
assert_eq "#408 helper: verdict reject -> no-fire (never resume a decided verdict)" \
  "no-fire" "$(rrb408 gh-empty.sh reject abc 5 o/r true "$T408/cfg-enabled.json")"
# #312 valid-falsy row: a real JSON `false` disables the backstop (an `// true`
# coercion that ignores explicit false would still fire → RED here).
assert_eq "#408 helper: enabled real-JSON-false -> no-fire (the #312 valid-falsy row)" \
  "no-fire" "$(rrb408 gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-disabled.json")"
assert_eq "#408 helper: enabled false -> reason disabled" \
  "disabled" "$(rrb408_reason gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-disabled.json")"
# Cap enforcement: 2 same-head markers at cap 2 -> exhausted (no-fire).
assert_eq "#408 helper: attempts at cap -> no-fire (exhausted)" \
  "no-fire" "$(rrb408 gh-2markers.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
assert_eq "#408 helper: attempts at cap -> reason exhausted" \
  "exhausted" "$(rrb408_reason gh-2markers.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
# Foreign-head markers must NOT count: only a head=zzz marker present, so head=abc
# has 0 attempts -> fire (if foreign counted, this would read exhausted/attempt≠1).
assert_eq "#408 helper: foreign-head marker not counted for this head -> fire" \
  "fire" "$(rrb408 gh-foreign.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
# Unreadable comment count fails CLOSED (never resume on an unknowable count).
assert_eq "#408 helper: comments query failure -> no-fire (count-unreadable, fail closed)" \
  "no-fire" "$(rrb408 gh-fail.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
assert_eq "#408 helper: comments query failure -> reason count-unreadable" \
  "count-unreadable" "$(rrb408_reason gh-fail.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
# No App token: a GITHUB_TOKEN comment never re-triggers, so no-fire (degrade to flip).
assert_eq "#408 helper: no App token -> no-fire (a GITHUB_TOKEN comment cannot re-trigger)" \
  "no-fire" "$(rrb408 gh-empty.sh incomplete abc 5 o/r false "$T408/cfg-enabled.json")"
assert_eq "#408 helper: no App token -> reason no-app-token" \
  "no-app-token" "$(rrb408_reason gh-empty.sh incomplete abc 5 o/r false "$T408/cfg-enabled.json")"
# Empty head SHA cannot scope the markers -> no-fire (never an unbounded resume).
assert_eq "#408 helper: empty HEAD_SHA -> no-fire (unscoped)" \
  "no-fire" "$(rrb408 gh-empty.sh incomplete '' 5 o/r true "$T408/cfg-enabled.json")"
# The fire path emits the head-scoped marker with the next attempt number.
RRB408_FIRE="$(DEVFLOW_GH="$T408/gh-empty.sh" VERDICT=incomplete HEAD_SHA=abc PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true CONFIG_FILE="$T408/cfg-enabled.json" bash "$RRB408" 2>/dev/null)"
assert_eq "#408 helper: fire emits the head-scoped marker with the next attempt" "yes" \
  "$(printf '%s\n' "$RRB408_FIRE" | grep -qxF 'marker=<!-- prflow:review-backstop head=abc attempt=1 -->' && echo yes || echo no)"
# Always exits 0 (best-effort — caller reads `decision`, not the exit code).
DEVFLOW_GH="$T408/gh-fail.sh" VERDICT=incomplete HEAD_SHA=abc PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true bash "$RRB408" >/dev/null 2>&1
assert_eq "#408 helper: always exits 0 even on a fail-closed arm" "0" "$?"
# MAX edge rows (the silent-coercion class, #312 discipline): max_resume_attempts=0
# must be honored (0 >= 0 → exhausted even with zero markers — detect-and-flip only),
# and a non-integer cap must fall back to the default 2 (so a fresh head still fires).
printf '%s\n' '{"prflow_review":{"stall_backstop":{"enabled":true,"max_resume_attempts":0}}}' > "$T408/cfg-max0.json"
printf '%s\n' '{"prflow_review":{"stall_backstop":{"enabled":true,"max_resume_attempts":"notanum"}}}' > "$T408/cfg-badmax.json"
assert_eq "#408 helper: max_resume_attempts=0 honored -> no-fire (exhausted, detect-and-flip only)" \
  "exhausted" "$(rrb408_reason gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-max0.json")"
assert_eq "#408 helper: non-integer max_resume_attempts falls back to default 2 -> fire" \
  "fire" "$(rrb408 gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-badmax.json")"
# Empty REPO is derived via `gh repo view` (the standalone/unit path; the workflow
# always passes REPO) — the stub's repo-view arm resolves o/r, so a fresh head fires.
assert_eq "#408 helper: empty REPO derived via gh repo view -> fire" \
  "fire" "$(rrb408 gh-empty.sh incomplete abc 5 '' true "$T408/cfg-enabled.json")"
# Nonzero attempt-increment (PR #410 review gap): 1 prior SAME-head marker under a
# cap of 3 must fire with attempt=2 — the NEXT=ATTEMPTS+1 path was only ever driven
# at ATTEMPTS=0 (attempt=1), so an off-by-one that re-emitted attempt=1 (a duplicate
# marker that never advances the cap → unbounded loop) would have passed. Pins the
# increment AND the emitted marker's attempt number at a nonzero base.
cat > "$T408/gh-1marker.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=abc attempt=1 -->"},{"body":"<!-- devflow:review-backstop head=zzz attempt=1 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$T408/gh-1marker.sh"
printf '%s\n' '{"prflow_review":{"stall_backstop":{"enabled":true,"max_resume_attempts":3}}}' > "$T408/cfg-max3.json"
assert_eq "#408 helper: 1 prior same-head marker under cap -> fire (attempts>0 increment path)" \
  "fire" "$(rrb408 gh-1marker.sh incomplete abc 5 o/r true "$T408/cfg-max3.json")"
RRB408_FIRE2="$(DEVFLOW_GH="$T408/gh-1marker.sh" VERDICT=incomplete HEAD_SHA=abc PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true CONFIG_FILE="$T408/cfg-max3.json" bash "$RRB408" 2>/dev/null)"
assert_eq "#408 helper: nonzero-base fire emits the NEXT attempt number (attempt=2, not a re-emitted attempt=1)" "yes" \
  "$(printf '%s\n' "$RRB408_FIRE2" | grep -qxF 'marker=<!-- prflow:review-backstop head=abc attempt=2 -->' && echo yes || echo no)"
# -- #1003: the attempt cap counts the UNION of both marker spellings ---------
# The rename rewrites no existing comment, so one head can carry a pre-rename
# marker beside a post-rename one. Counting a single spelling would RESET the cap
# and grant up to MAX extra auto-resumes on a head that had already exhausted it.
# Three rows: a MIXED pair at cap 2 reads as exhausted, the same pair at cap 3
# fires with attempt=3 (proving the count is 2, not 1 -- an exhausted-only
# assertion would also pass if only one spelling were counted), and a mixed pair
# on a FOREIGN head still counts zero (the union widened spellings, not scope).
cat > "$T408/gh-mixedns.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=abc attempt=1 -->"},{"body":"<!-- prflow:review-backstop head=abc attempt=2 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$T408/gh-mixedns.sh"
assert_eq "#1003 helper: mixed-spelling markers for one head reach the cap (no reset)" \
  "no-fire" "$(rrb408 gh-mixedns.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
assert_eq "#1003 helper: ...and the exhausted reason is the cap, not an unreadable count" \
  "exhausted" "$(rrb408_reason gh-mixedns.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"
RRB1003_MIXED="$(DEVFLOW_GH="$T408/gh-mixedns.sh" VERDICT=incomplete HEAD_SHA=abc PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true CONFIG_FILE="$T408/cfg-max3.json" bash "$RRB408" 2>/dev/null)"
assert_eq "#1003 helper: mixed-spelling count is 2 (next attempt is 3, not 2)" "yes" \
  "$(printf '%s\n' "$RRB1003_MIXED" | grep -qxF 'marker=<!-- prflow:review-backstop head=abc attempt=3 -->' && echo yes || echo no)"
cat > "$T408/gh-mixedns-foreign.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=zzz attempt=1 -->"},{"body":"<!-- prflow:review-backstop head=zzz attempt=2 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$T408/gh-mixedns-foreign.sh"
assert_eq "#1003 helper: mixed-spelling markers on a FOREIGN head do not count (head scope intact)" \
  "fire" "$(rrb408 gh-mixedns-foreign.sh incomplete abc 5 o/r true "$T408/cfg-enabled.json")"

# Hard config-read failure (PR #410 review gap): a MALFORMED config makes
# config-get.sh hard-fail with empty stdout, and the helper still resolves toward
# firing — the documented honest-failure direction (a review backstop must stay
# armed when the config can't be read, not silently disable the safety net). This
# is defense-in-depth: the malformed->fire direction is held by BOTH the
# `[ -n "$ENABLED" ] || ENABLED=true` fallback AND the exact-match disable guard
# (`[ "$ENABLED" = "false" ]`, so an empty ENABLED is never "disabled"), so
# removing either single guard alone still fires. This asserts the AGGREGATE
# malformed->fire direction (previously untested); it deliberately does NOT isolate
# one fallback line — a regression that instead resolves malformed->no-fire (e.g.
# the fallback set to `false`) flips it RED. The aggregate stays bounded — a fire
# still requires App token + scope + under-cap, all covered above.
printf '%s\n' '{ this is not valid json' > "$T408/cfg-malformed.json"
assert_eq "#408 helper: malformed config hard-fail -> fire (honest-failure resolves toward ENABLED, net stays armed)" \
  "fire" "$(rrb408 gh-empty.sh incomplete abc 5 o/r true "$T408/cfg-malformed.json")"
# MARKER_PREFIX trailing-space disambiguation (PR #410 review gap): the count key is
# `head=<sha> ` WITH a trailing space so a short head cannot prefix-match a longer one
# (`head=ab ` must NOT match a `head=abc ...` marker). The foreign-head fixtures above
# use equal-length non-overlapping heads (abc vs zzz), so deleting that trailing space
# would NOT turn them RED. Drive the collision directly: HEAD_SHA=ab against a marker
# for head=abc must count 0 (fire attempt=1); if the trailing space were dropped,
# `head=ab` would substring-match `head=abc` -> count 1 -> attempt=2.
cat > "$T408/gh-prefixcollide.sh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"/comments"*) echo '[{"body":"<!-- devflow:review-backstop head=abc attempt=9 -->"}]' ;;
  *"repo view"*) echo 'o/r' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$T408/gh-prefixcollide.sh"
RRB408_COLLIDE="$(DEVFLOW_GH="$T408/gh-prefixcollide.sh" VERDICT=incomplete HEAD_SHA=ab PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true CONFIG_FILE="$T408/cfg-enabled.json" bash "$RRB408" 2>/dev/null)"
assert_eq "#408 helper: short head does not prefix-match a longer head's marker (trailing-space disambiguation)" "yes" \
  "$(printf '%s\n' "$RRB408_COLLIDE" | grep -qxF 'marker=<!-- prflow:review-backstop head=ab attempt=1 -->' && echo yes || echo no)"
# VERDICT unset -> defaults to the eligible `incomplete` (PR #410 review gap): the
# header documents this default; drive it (no VERDICT in env) so a regression that
# changed the default to a decided verdict (silently no-firing every headless run)
# goes RED. All other inputs supplied so the aggregate reaches a fire decision.
RRB408_NOVERDICT="$(DEVFLOW_GH="$T408/gh-empty.sh" HEAD_SHA=abc PR_NUMBER=5 REPO=o/r APP_TOKEN_PRESENT=true CONFIG_FILE="$T408/cfg-enabled.json" bash "$RRB408" 2>/dev/null | sed -n 's/^decision=//p')"
assert_eq "#408 helper: VERDICT unset defaults to eligible 'incomplete' -> fire" "fire" "$RRB408_NOVERDICT"
rm -rf "$T408"

# Config coupled peer set (2.3.0a): example ↔ schema must both carry
# prflow_review.stall_backstop.{enabled,max_resume_attempts} with matching
# types/defaults (mirrors the #266 implement-side coherence pin).
CFG408="$(python3 - "$REPO_ROOT" <<'PY' 2>/dev/null || true
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
ex = json.loads((root / ".prflow/config.example.json").read_text())
sc = json.loads((root / ".prflow/config.schema.json").read_text())
eb = ex.get("prflow_review", {}).get("stall_backstop", {})
sp = sc["properties"]["prflow_review"]["properties"].get("stall_backstop", {})
props = sp.get("properties", {})
ok = (
    eb.get("enabled") is True
    and eb.get("max_resume_attempts") == 2
    and sp.get("type") == "object"
    and sp.get("additionalProperties") is False
    and props.get("enabled", {}).get("type") == "boolean"
    and props.get("enabled", {}).get("default") is True
    and props.get("max_resume_attempts", {}).get("type") == "integer"
    and props.get("max_resume_attempts", {}).get("minimum") == 0
    and props.get("max_resume_attempts", {}).get("default") == 2
)
print("yes" if ok else "no")
PY
)"
assert_eq "#408 config example+schema carry coupled prflow_review.stall_backstop keys (types/defaults/additionalProperties)" "yes" "$CFG408"

# Workflow wiring — the auto-review path's finalize_check pins are RETIRED (issue #936).
# .github/workflows/devflow-review.yml was the auto PR-triggered review tier's caller and is
# no longer in the tree, so its backstop_eligible arm, its "Review stall backstop" step, its
# backstop-token mint, and their gating `if:` expressions have no subject. The stall-backstop
# MECHANISM keeps full coverage: the manual /devflow:review dead-run arm below pins the same
# step, mint, helper call and gating on devflow.yml, and the #414 helper block drives
# post-review-backstop-comment.sh's decision/POST/annotation arms directly, on both paths'
# shared code. What is lost is only the assertion that the deleted workflow wired them.
#
# Workflow wiring — devflow.yml manual /devflow:review dead-run arm.
WFD408="$REPO_ROOT/.github/workflows/devflow.yml"
devflow_module_pin_unique "#408 devflow-yml: 'Review stall backstop' step present on the manual path" \
  "name: Review stall backstop" "$WFD408"
assert_eq "#408/#414 devflow-yml: manual-path step calls the extracted post-and-annotate helper" "yes" \
  "$(grep -qF "post-review-backstop-comment.sh" "$WFD408" && echo yes || echo no)"
assert_eq "#408 devflow-yml: manual-path backstop gated on a /prflow:review command" "yes" \
  "$(grep -A1 'name: Review stall backstop' "$WFD408" | grep -qF "startsWith(needs.gate.outputs.command, '/prflow:review ')" && echo yes || echo no)"
# The manual-path DEAD-RUN trigger clause is the sole logic distinguishing a dead review
# from a healthy or cancelled one; broadening it (e.g. to `!= 'success'`, re-including
# cancelled/superseded) or dropping it would fire spurious auto-resumes. Pin the exact
# conjunction on BOTH the run step and the mint step.
assert_eq "#408 devflow-yml: manual-path backstop gated on the dead-run trigger (is_error/failure)" "1" \
  "$(grep -cF "(steps.engine.outputs.is_error == 'true' || steps.claude.outcome == 'failure') }}" "$WFD408")"
# The manual-path mint step must exist and be gated on DEVFLOW_APP_ID (else the manual path
# would attempt a resume without a workflow-capable token — the inert-GITHUB_TOKEN no-op).
devflow_module_pin_unique "#408 devflow-yml: manual-path fresh backstop-token mint step present" \
  "id: backstop-token" "$WFD408"
assert_eq "#408 devflow-yml: manual-path mint gated on the dead-run trigger + DEVFLOW_APP_ID" "1" \
  "$(grep -cF "(steps.engine.outputs.is_error == 'true' || steps.claude.outcome == 'failure') && vars.DEVFLOW_APP_ID != '' }}" "$WFD408")"
# Fix A consumer-side breadcrumb selection now lives in the shared helper (issue #414),
# driven in the #414 block below for both the manual and auto-review paths.

# The backstop-marker literal is a coupled contract: request-review-backstop.sh WRITES it (the
# count-prefix AND the emitted marker, so it appears twice) and the extracted
# post-review-backstop-comment.sh helper posts it (issue #414 moved the POST out of the two
# workflow YAMLs into that helper). Assert presence in the writer so a rename there goes RED.
assert_eq "#408 helper: writes the head-scoped review-backstop marker literal" "yes" \
  "$(grep -qF 'prflow:review-backstop head=' "$RRB408" && echo yes || echo no)"

RGB408="$REPO_ROOT/scripts/render-grounding-block.sh"
GB408_OUT="$(HEAD_SHA=x CI_SUMMARY='c: success' ALLOWED_TOOLS='Read' bash "$RGB408")"
assert_eq "#408 grounding block renders the headless-run semantics sentence" "yes" \
  "$(printf '%s\n' "$GB408_OUT" | grep -qF 'This is a headless run: ending your turn ends the process' && echo yes || echo no)"
assert_eq "#408 grounding block renders the ScheduleWakeup-unavailable rule" "yes" \
  "$(printf '%s\n' "$GB408_OUT" | grep -qF 'ScheduleWakeup' && echo yes || echo no)"
WFI415="$REPO_ROOT/.github/workflows/devflow-implement.yml"
# ── #415 review finding #1 + #2: the schedulewakeup-probe verdict core is extracted
# ── into scripts/schedulewakeup-probe-verdict.py so every arm — and the fail-open
# ── name-match matrix — is DRIVEN, not left inline-in-YAML untestable (same rationale
# ── as describe-denial-count.sh, PR #367). matcher-probe.yml routes the verdict step
# ── through the helper (pinned below), and every four-way arm plus the two fail-open
# ── regressions (lower-cased name, input-less name) is exercised against the real file.
SWV_PY="$REPO_ROOT/scripts/schedulewakeup-probe-verdict.py"
MPROBE415="$REPO_ROOT/.github/workflows/matcher-probe.yml"
devflow_module_pin_unique "#415 matcher-probe.yml routes the ScheduleWakeup verdict through the testable helper" \
  'python3 scripts/schedulewakeup-probe-verdict.py "${EXECUTION_FILE}"' "$MPROBE415"
swv_has_row() {  # fixture expected-row-prefix -> "yes" if the verdict row starts with it
  python3 "$SWV_PY" "$1" 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
swv_has() {  # fixture substring -> "yes" if the rendered output contains it (any line)
  python3 "$SWV_PY" "$1" 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
# A ship verdict (DENIED/REMOVED) now requires a positive permission_denials record
# (issue #1527), never presumptive absence: DENIED = denied AND attempted (present,
# refused); REMOVED = denied with no registered attempt (removed-from-context).
# Arm: DENIED — ScheduleWakeup denied AND attempted (present, refused; ships).
SWV_F="$(probe_tmp swv.denied)"
printf '%s' '[{"permission_denials":[{"tool":"ScheduleWakeup"}]},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"ScheduleWakeup","input":{"delaySeconds":300}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: DENIED when ScheduleWakeup denied AND attempted (present, refused; ship)" "yes" \
  "$(swv_has_row "$SWV_F" '| **DENIED** | yes |')"
# Arm: AVAILABLE — a ScheduleWakeup tool_use recorded, not denied (does NOT ship).
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"ScheduleWakeup","input":{"delaySeconds":60}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: AVAILABLE when ScheduleWakeup attempted and not denied (no ship)" "yes" \
  "$(swv_has_row "$SWV_F" '| **AVAILABLE** | no |')"
# Arm (issue #1527, AC1): the token appears ONLY inside a ToolSearch input query, never as
# a tool_use NAME — the attempt predicate keys on the recorded name, so this is NO attempt
# (tool_use(ScheduleWakeup)=no) and, with no denial, INCONCLUSIVE. RED against the pre-fix
# helper, which substring-matched the input JSON and read it as an attempt (AVAILABLE).
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"ToolSearch","input":{"query":"select:ScheduleWakeup"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: a ToolSearch query naming ScheduleWakeup is NOT an attempt (tool_use(ScheduleWakeup)=no)" "yes" \
  "$(swv_has "$SWV_F" 'tool_use(ScheduleWakeup)=no')"
assert_eq "#415 swv: a ToolSearch query naming ScheduleWakeup yields INCONCLUSIVE, not a false AVAILABLE" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# Arm (issue #1527, AC3): both controls ran, no ScheduleWakeup tool_use, NO denial → no
# positive signal → INCONCLUSIVE, never the shippable REMOVED. Presumptive absence (the
# model may simply not have attempted the call) is never distinguished from removal here.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: both controls + no attempt + no denial → INCONCLUSIVE, not a presumptive REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# Arm (issue #1527, AC3): positive removal evidence — a ScheduleWakeup denial recorded with
# NO registered attempt distinguishes "the flag removed the tool" from "the model did not
# attempt the call" (the latter records no denial), so REMOVED ships only on that record.
printf '%s' '[{"permission_denials":[{"tool":"ScheduleWakeup"}]},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: ScheduleWakeup denied with no registered attempt → REMOVED (positive evidence; ship)" "yes" \
  "$(swv_has_row "$SWV_F" '| **REMOVED** | yes |')"
# Arm: INCONCLUSIVE — only the BEFORE control ran, no positive signal (no denial, no
# attempt). The verdict no longer keys on the controls (issue #1527): any file with no
# positive signal is INCONCLUSIVE, never the shippable REMOVED. "Unknown is not zero."
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}}]' > "$SWV_F"
assert_eq "#415 swv: INCONCLUSIVE (no ship) when only the before-control ran, not REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# And the no-signal [!WARNING] text interpolates the control states in order (before=yes,
# after=no) — guards a garbled/transposed operator diagnostic on this path.
assert_eq "#415 swv: before-only run renders the [!WARNING] 'controls: before=yes, after=no' text" "yes" \
  "$(swv_has "$SWV_F" 'controls: before=yes, after=no')"
# Arm: INCONCLUSIVE — only the AFTER control ran (PR #417 shadow — pr-test-analyzer), the
# symmetric partner of the before-only arm. No positive signal (no denial, no attempt), so
# INCONCLUSIVE regardless of which controls ran — never a fail-open REMOVED (issue #1527).
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: INCONCLUSIVE (no ship) when only the after-control ran, not a fail-open REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# Arm: INCONCLUSIVE — execution file absent (note_top floor). Never REMOVED.
assert_eq "#415 swv: INCONCLUSIVE (no ship) when the execution file is absent" "yes" \
  "$(swv_has_row "/no/such/schedulewakeup-execfile.json" '| **INCONCLUSIVE** | no |')"
# Arm: INCONCLUSIVE — present regular file, wholly unparseable (not JSON, not JSONL) →
# note_top "present but unparseable" floor, never a clean tool-absence REMOVED.
printf '%s\n' 'not json at all, not a single object' > "$SWV_F"
assert_eq "#415 swv: INCONCLUSIVE (no ship) when a present file is wholly unparseable" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# Arm: INCONCLUSIVE — partial JSONL corruption forces the note_top floor rather than
# reading the surviving lines. The surviving ScheduleWakeup denial line would otherwise
# ship REMOVED (issue #1527), so removing `if dropped:` flips this fixture to REMOVED.
printf '%s\n%s\n' \
  '{"permission_denials":[{"tool":"ScheduleWakeup"}]}' \
  '{oops-not-json' > "$SWV_F"
assert_eq "#415 swv: INCONCLUSIVE (no ship) on partial JSONL corruption with a surviving denial, not a false REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **INCONCLUSIVE** | no |')"
# Fail-open regression #2a (case): a ScheduleWakeup call recorded under a LOWER-CASED
# name must read as present (AVAILABLE, no ship). Case-sensitive matching would miss it
# and, with both controls run, ship REMOVED — a fail-open in the dangerous direction.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"schedulewakeup","input":{"delaySeconds":60}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: lower-cased tool name still reads AVAILABLE, not a fail-open REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **AVAILABLE** | no |')"
# Fail-open regression #2b (input-less): a ScheduleWakeup tool_use with no `input` key
# must still be recorded by NAME and read AVAILABLE — dropping it would ship REMOVED.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"ScheduleWakeup"},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: input-less ScheduleWakeup tool_use still reads AVAILABLE, not REMOVED" "yes" \
  "$(swv_has_row "$SWV_F" '| **AVAILABLE** | no |')"
# The helper always exits 0 (best-effort, like describe-denial-count.sh).
assert_eq "#415 swv: helper exits 0 even on an absent execution file" "0" \
  "$(python3 "$SWV_PY" /no/such/execfile.json >/dev/null 2>&1; echo $?)"
# PR #417 review finding (Important-1): a PRESENT-but-unreadable execution file
# (PermissionError, or a TOCTOU disappearance after the os.path.isfile() check) must
# route to the INCONCLUSIVE floor and still exit 0 — honoring the module's documented
# "Always exits 0" contract — instead of raising an uncaught traceback through
# render()/main() (which under matcher-probe.yml's `set -euo pipefail` verdict step
# yields a red step with NO verdict table, on exactly the degraded run the probe exists
# to handle). Gated only where chmod 000 does not actually deny reads (running as
# root, or a filesystem ignoring the mode). Issue #838: that gate reports through
# module_host_capability_skip, so such a host yields a VISIBLE host-capability skip
# whose declared credit reconciles the module's assertion floor — not the silent
# assertion drop and count-mismatch floor trip the bare echo used to produce. Every
# chmod-000 read-probe gate in this file is treated the same way.
SWV_UNREAD="$(probe_tmp swv.unreadable)"
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_UNREAD"
chmod 000 "$SWV_UNREAD"
if python3 -c "open('$SWV_UNREAD').read()" 2>/dev/null; then
  module_host_capability_skip "#415 swv unreadable-execution-file arm" \
    "chmod 000 does not deny reads on this host (e.g. running as root, or a filesystem ignoring the mode)" 2
else
  assert_eq "#415 swv: present-but-unreadable execution file -> INCONCLUSIVE (no ship), not a raised traceback" "yes" \
    "$(swv_has_row "$SWV_UNREAD" '| **INCONCLUSIVE** | no |')"
  assert_eq "#415 swv: helper still exits 0 on a present-but-unreadable execution file" "0" \
    "$(python3 "$SWV_PY" "$SWV_UNREAD" >/dev/null 2>&1; echo $?)"
fi
chmod 644 "$SWV_UNREAD" 2>/dev/null || true
rm -f "$SWV_UNREAD"
# PR #417 review (pr-test-analyzer, Important): the render() claude_args-DECISION text is
# the AC4 operator-facing output ("SHIP …" / "DO NOT SHIP …" / "DO NOT ACT …"), selected by
# an if/elif independent of the table row. Every other pin greps only the verdict row, so a
# mis-mapped decision (e.g. AVAILABLE routed into the DO-NOT-ACT else, or SHIP/DO-NOT-SHIP
# transposed) would misdirect the operator while staying green. Pin one decision string per
# class. The `AC4): SHIP` prefix is distinct from `AC4): DO NOT SHIP` (grep -F is literal).
# REMOVED fixture (issue #1527: a ScheduleWakeup denial with no registered attempt) ->
# SHIP decision + presumptive [!NOTE].
printf '%s' '[{"permission_denials":[{"tool":"ScheduleWakeup"}]},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: REMOVED renders the SHIP claude_args decision (AC4)" "yes" \
  "$(swv_has "$SWV_F" 'AC4): SHIP')"
assert_eq "#415 swv: REMOVED renders the presumptive [!NOTE] caveat block" "yes" \
  "$(swv_has "$SWV_F" '[!NOTE]')"
# AVAILABLE fixture (ScheduleWakeup attempted, both controls) -> DO NOT SHIP decision.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"ScheduleWakeup","input":{"delaySeconds":60}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: AVAILABLE renders the DO NOT SHIP claude_args decision (AC4)" "yes" \
  "$(swv_has "$SWV_F" 'AC4): DO NOT SHIP')"
# INCONCLUSIVE (absent file) -> DO NOT ACT decision + [!WARNING] re-run block.
assert_eq "#415 swv: INCONCLUSIVE renders the DO NOT ACT claude_args decision (AC4)" "yes" \
  "$(swv_has "/no/such/swv-decision.json" 'AC4): DO NOT ACT')"
assert_eq "#415 swv: INCONCLUSIVE renders the [!WARNING] re-run block" "yes" \
  "$(swv_has "/no/such/swv-decision.json" '[!WARNING]')"
# Precedence: ScheduleWakeup BOTH denied AND attempted must resolve DENIED (denial checked
# before attempt in compute_verdict) — a reordering would ship AVAILABLE on a denied tool.
printf '%s' '[{"permission_denials":[{"tool":"ScheduleWakeup"}]},{"type":"tool_use","name":"ScheduleWakeup","input":{"delaySeconds":60}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/hosts"}},{"type":"tool_use","name":"Bash","input":{"command":"grep x /etc/os-release"}}]' > "$SWV_F"
assert_eq "#415 swv: DENIED wins over AVAILABLE when ScheduleWakeup is both denied and attempted" "yes" \
  "$(swv_has_row "$SWV_F" '| **DENIED** | yes |')"
rm -f "$SWV_F"

# ── #610 cloud per-agent-effort SEAM probe verdict — the branch-selecting core is
# ── extracted into scripts/agents-seam-probe-verdict.py so every arm (and the
# ── never-auto-ship-the-applied-arm fail-open guard) is DRIVEN, not left inline-in-YAML
# ── untestable (same rationale as the #415 schedulewakeup helper above). The applied
# ── arm ships ONLY on SEAM_PROVEN, which requires the explicit human
# ── --adjudicated-governed flag — the dangerous direction (shipping on an unproven
# ── seam) must be unreachable without a human in the loop.
ASV_PY="$REPO_ROOT/scripts/agents-seam-probe-verdict.py"
ASPROBE="$REPO_ROOT/.github/workflows/agents-seam-probe.yml"
devflow_module_pin_unique "#610 agents-seam-probe.yml routes the seam verdict through the testable helper" \
  'python3 scripts/agents-seam-probe-verdict.py "${EXECUTION_FILE}"' "$ASPROBE"
asv_has_row() {  # fixture expected-row-prefix -> "yes" if the verdict row starts with it
  python3 "$ASV_PY" "$1" 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
asv_has() {  # fixture substring -> "yes" if the rendered output contains it (any line)
  python3 "$ASV_PY" "$1" 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
asv_has_row_adj() {  # fixture expected-row-prefix (with --adjudicated-governed)
  python3 "$ASV_PY" "$1" --adjudicated-governed 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
ASV_F="$(probe_tmp asv.fixture)"
# Arm: SEAM_FORWARDED — the seam marker was emitted (fact i proven) but fact (ii) is NOT
# adjudicated → does NOT ship the applied arm. This is the primary fail-open guard: a
# forwarded seam must NOT auto-promote to SEAM_PROVEN/ship without the human flag.
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s SEAM_PROBE_FORWARDED_OK SEAM_PROBE_EFFORT=low"}}]' > "$ASV_F"
assert_eq "#610 asv: SEAM_FORWARDED (no ship) when marker present but fact (ii) not adjudicated" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_FORWARDED** | no |')"
# Same fixture WITH --adjudicated-governed → SEAM_PROVEN, ships the applied arm.
assert_eq "#610 asv: SEAM_PROVEN (ship) only when a human adjudicated fact (ii) via --adjudicated-governed" "yes" \
  "$(asv_has_row_adj "$ASV_F" '| **SEAM_PROVEN** | yes |')"
# Arm: SEAM_UNPROVEN — the subagent type was dispatched and the record carries an
# AFFIRMATIVE non-forwarding signal (the prompt's refusal arm reached a tool call), so the
# `--agents` startup block was not forwarded / the type was unrecognized. Does NOT ship.
# Post-#1177 this arm requires that affirmative signal: "dispatched, nothing recorded" is
# INSTRUMENT_NOT_FIRED below, not a statement about the seam.
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s seam-probe-agent dispatch refused: unknown subagent_type"}}]' > "$ASV_F"
assert_eq "#610 asv: SEAM_UNPROVEN (no ship) when the subagent type was dispatched but emitted no seam marker" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_UNPROVEN** | no |')"
# Even with --adjudicated-governed, SEAM_UNPROVEN must NOT ship: fact (i) forwarding is a
# hard prerequisite the human flag cannot override.
assert_eq "#610 asv: SEAM_UNPROVEN stays no-ship even with --adjudicated-governed (fact (i) is a hard gate)" "yes" \
  "$(asv_has_row_adj "$ASV_F" '| **SEAM_UNPROVEN** | no |')"
# Arm: INCONCLUSIVE — no dispatch of the probe subagent_type was even attempted (the seam
# was never exercised). Never ships.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"echo unrelated"}}]' > "$ASV_F"
assert_eq "#610 asv: INCONCLUSIVE (no ship) when no dispatch of the probe subagent_type was attempted" "yes" \
  "$(asv_has_row "$ASV_F" '| **INCONCLUSIVE** | no |')"
# Arm: INCONCLUSIVE — execution file absent (note_top floor). "Unknown is not zero" — never
# collapsed onto a shippable verdict.
assert_eq "#610 asv: INCONCLUSIVE (no ship) when the execution file is absent" "yes" \
  "$(asv_has_row "/no/such/agents-seam-execfile.json" '| **INCONCLUSIVE** | no |')"
# Arm: INCONCLUSIVE — present regular file, wholly unparseable → note_top floor.
printf '%s\n' 'not json at all' > "$ASV_F"
assert_eq "#610 asv: INCONCLUSIVE (no ship) when a present file is wholly unparseable" "yes" \
  "$(asv_has_row "$ASV_F" '| **INCONCLUSIVE** | no |')"
# Fail-open regression (case): a LOWER-CASED seam marker must still read as forwarded
# (SEAM_FORWARDED), not fall through to SEAM_UNPROVEN — case-sensitive matching would
# under-read fact (i).
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s seam_probe_forwarded_ok seam_probe_effort=low"}}]' > "$ASV_F"
assert_eq "#610 asv: lower-cased seam marker still reads SEAM_FORWARDED, not SEAM_UNPROVEN" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_FORWARDED** | no |')"
# Arm: INCONCLUSIVE — partial JSONL corruption forces the floor rather than reading the
# surviving lines as a clean measurement (both a dispatch AND a marker line survive, so the
# ONLY thing keeping this off SEAM_FORWARDED is the dropped→note_top precedence).
printf '%s\n%s\n%s\n' \
  '{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}}' \
  '{"type":"tool_use","name":"Bash","input":{"command":"printf %s SEAM_PROBE_FORWARDED_OK SEAM_PROBE_EFFORT=low"}}' \
  '{oops-not-json' > "$ASV_F"
assert_eq "#610 asv: INCONCLUSIVE (no ship) on partial JSONL corruption, not a false SEAM_FORWARDED" "yes" \
  "$(asv_has_row "$ASV_F" '| **INCONCLUSIVE** | no |')"
# Decision-text pins (the operator-facing AC1 decision line, selected independently of the
# row). One per class so a mis-mapped decision (green row, wrong action) is caught.
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s SEAM_PROBE_FORWARDED_OK SEAM_PROBE_EFFORT=low"}}]' > "$ASV_F"
assert_eq "#610 asv: SEAM_PROVEN renders the SHIP applied-arm decision (AC1)" "yes" \
  "$(python3 "$ASV_PY" "$ASV_F" --adjudicated-governed 2>/dev/null | grep -qF 'AC1): SHIP the spike-gated applied arm' && echo yes || echo no)"
assert_eq "#610 asv: SEAM_FORWARDED renders the DO-NOT-SHIP (fact ii pending) decision (AC1)" "yes" \
  "$(asv_has "$ASV_F" 'fact (ii) (effort governs the dispatch) needs human adjudication')"
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s seam-probe-agent dispatch refused: unknown subagent_type"}}]' > "$ASV_F"
assert_eq "#610 asv: SEAM_UNPROVEN renders the DO-NOT-SHIP (seam not forwarded) decision (AC1)" "yes" \
  "$(asv_has "$ASV_F" 'the startup `--agents` seam was not forwarded')"
assert_eq "#610 asv: INCONCLUSIVE renders the DO NOT ACT decision (AC1)" "yes" \
  "$(asv_has "/no/such/agents-seam-decision.json" 'AC1): DO NOT ACT')"
# The helper always exits 0 (best-effort, like the #415 sibling).
assert_eq "#610 asv: helper exits 0 even on an absent execution file" "0" \
  "$(python3 "$ASV_PY" /no/such/execfile.json >/dev/null 2>&1; echo $?)"
# Fail-open regression (input-less tool_use): a dispatch tool_use recorded under the probe
# subagent NAME but carrying NO `input` key must still read as dispatch_attempted (-> the
# no-marker case resolves INSTRUMENT_NOT_FIRED post-#1177), never be dropped (which would
# fail OPEN into the INCONCLUSIVE "measured nothing" floor — a different claim: never even
# dispatched). collect() records a tool_use even without `input`
# (the named fail-open guard); this fixture pins it. Every other fixture carries an `input`,
# so without this the guard is untested and a regression stays green (PR #667 review, pr-test-analyzer Important).
printf '%s' '[{"type":"tool_use","name":"seam-probe-agent"}]' > "$ASV_F"
assert_eq "#610 asv: input-less probe-subagent tool_use still reads dispatch_attempted -> INSTRUMENT_NOT_FIRED, not a fail-open INCONCLUSIVE" "yes" \
  "$(asv_has_row "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
# dispatch_attempted via the permission_denials arm (the realistic "dispatch refused" shape):
# the probe agent name appears ONLY in a permission_denials node, never in a tool_use command
# string — exercises the `AGENT_NAME in denial_text` half of the OR (PR #667 review, pr-test-analyzer suggestion).
printf '%s' '[{"permission_denials":[{"tool":"Task","reason":"unknown subagent_type seam-probe-agent"}]}]' > "$ASV_F"
assert_eq "#610 asv: probe name only in permission_denials still reads dispatch_attempted -> SEAM_UNPROVEN" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_UNPROVEN** | no |')"
# Case-insensitivity of the AGENT_NAME match (its own .lower(), distinct from the marker's):
# a MIXED-case dispatch name still reads dispatch_attempted -> INSTRUMENT_NOT_FIRED, never
# the never-dispatched INCONCLUSIVE floor (PR #667 review, pr-test-analyzer suggestion).
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"SEAM-Probe-Agent"}}]' > "$ASV_F"
assert_eq "#610 asv: mixed-case probe subagent name still reads dispatch_attempted -> INSTRUMENT_NOT_FIRED" "yes" \
  "$(asv_has_row "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
# Present-but-unreadable execution file (PermissionError / TOCTOU) must route to the
# INCONCLUSIVE floor and still exit 0 — honoring "always exits 0" — never raise an uncaught
# traceback (which under the workflow's `set -euo pipefail` verdict step yields a red step
# with NO verdict table). Parity with the #415 swv sibling (PR #667 review, pr-test-analyzer).
# Gated where chmod 000 does not actually deny reads (running as root); that gate reports
# through module_host_capability_skip (issue #838), so the host yields a visible skip.
ASV_UNREAD="$(probe_tmp asv.unreadable)"
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}}]' > "$ASV_UNREAD"
chmod 000 "$ASV_UNREAD"
if python3 -c "open('$ASV_UNREAD').read()" 2>/dev/null; then
  module_host_capability_skip "#610 asv unreadable-execution-file arm" \
    "chmod 000 does not deny reads on this host (e.g. running as root, or a filesystem ignoring the mode)" 2
else
  assert_eq "#610 asv: present-but-unreadable execution file -> INCONCLUSIVE (no ship), not a raised traceback" "yes" \
    "$(asv_has_row "$ASV_UNREAD" '| **INCONCLUSIVE** | no |')"
  assert_eq "#610 asv: helper still exits 0 on a present-but-unreadable execution file" "0" \
    "$(python3 "$ASV_PY" "$ASV_UNREAD" >/dev/null 2>&1; echo $?)"
fi
chmod 644 "$ASV_UNREAD" 2>/dev/null || true
rm -f "$ASV_UNREAD"

# ── #1177 instrument non-fire: both arms of the probe prompt's Step 2 run through a
# ── model-issued Bash echo the model may simply skip, so a run that dispatched the
# ── subagent and then stopped used to be scored SEAM_UNPROVEN — a statement ABOUT THE
# ── SEAM about a run in which nothing was measured. The verdict vocabulary now separates
# ── "measured false" from "not measured". Fixtures only; no cloud dispatch.
# The exact shape observed in the four non-fire runs of 2026-07-21 (run 29871350774's
# recorded tool_use dump: one entry, NAME=Agent, subagent_type seam-probe-agent, zero
# denials). This is the run class the issue was filed about.
printf '%s' '[{"type":"tool_use","name":"Agent","input":{"description":"Cloud seam probe dispatch","subagent_type":"seam-probe-agent","prompt":"Report your seam marker line."}}]' > "$ASV_F"
assert_eq "#1177 asv: dispatched with no Bash tool_use at all -> INSTRUMENT_NOT_FIRED (no ship), not SEAM_UNPROVEN" "yes" \
  "$(asv_has_row "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
# The whole point of the new verdict: its rendered text must NOT tell the reader anything
# about the seam's status. Negative control on the SEAM_UNPROVEN decision sentence, which
# is what this run used to print.
assert_eq "#1177 asv: a non-fire does NOT render the seam-was-not-forwarded decision text" "no" \
  "$(asv_has "$ASV_F" 'the startup `--agents` seam was not forwarded')"
assert_eq "#1177 asv: a non-fire renders the no-measurement decision instead" "yes" \
  "$(asv_has "$ASV_F" 'NO SEAM MEASUREMENT was taken')"
assert_eq "#1177 asv: a non-fire is reported as uninformative in EITHER direction" "yes" \
  "$(asv_has "$ASV_F" 'uninformative in EITHER direction')"
# The Bash-reached fact is REPORTED (it is the observed signature) but is never what
# selects the verdict — a dispatched run that ran some unrelated Bash call and still put
# neither marker in the record is equally a non-measurement (issue #1177 AC1 says "emits no
# Bash MARKER", not "emits no Bash call"). A Bash-presence-only rule would miss this row.
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}]' > "$ASV_F"
assert_eq "#1177 asv: dispatched + an unrelated Bash call but neither marker -> still INSTRUMENT_NOT_FIRED" "yes" \
  "$(asv_has_row "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
assert_eq "#1177 asv: the bash_tool_use_recorded evidence fact reports that Bash was reached" "yes" \
  "$(asv_has "$ASV_F" 'bash_tool_use_recorded=yes')"
# AC4 — the human-adjudication gate is unweakened by the new arm: --adjudicated-governed
# on a non-fire must NOT promote it (fact (i) is a hard prerequisite the flag cannot supply).
assert_eq "#1177 asv: --adjudicated-governed cannot promote a non-fire (SEAM_PROVEN stays unreachable)" "yes" \
  "$(asv_has_row_adj "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
# A harness-recorded dispatch REFUSAL keeps its seam meaning: the permission_denials arm is
# an affirmative non-forwarding signal, so it must NOT be swept into the non-fire bucket.
printf '%s' '[{"permission_denials":[{"tool":"Task","reason":"unknown subagent_type seam-probe-agent"}]}]' > "$ASV_F"
assert_eq "#1177 asv: a denial naming the probe subagent stays SEAM_UNPROVEN, not INSTRUMENT_NOT_FIRED" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_UNPROVEN** | no |')"
# Cross-file contract, driven rather than transcribed: the two literals the helper matches
# are EMITTED by agents-seam-probe.yml's own prompt. Each fixture's Bash command is the
# workflow's own emitting line, extracted here — so a drift on either side changes a
# VERDICT (this is a behavioral test of the parser, not a wording pin on the workflow).
asv_fixture_from_workflow() {  # <needle> <out-file>; rc 3 when the workflow line is gone
  python3 -c 'import json, sys
src, needle, out = sys.argv[1], sys.argv[2], sys.argv[3]
lines = [l.strip() for l in open(src, encoding="utf-8") if needle in l and "printf" in l]
if not lines:
    sys.exit(3)
json.dump([{"type": "tool_use", "name": "Task", "input": {"subagent_type": "seam-probe-agent"}},
           {"type": "tool_use", "name": "Bash", "input": {"command": lines[0]}}],
          open(out, "w", encoding="utf-8"))' "$ASPROBE" "$1" "$2"
}
# Guard against a vacuous pass: extraction must actually find each emitting line.
assert_eq "#1177 asv: the workflow still carries the seam-marker emitting line" "0" \
  "$(asv_fixture_from_workflow 'SEAM_PROBE_FORWARDED_OK' "$ASV_F" >/dev/null 2>&1; echo $?)"
assert_eq "#1177 asv: the workflow's own seam-marker line, fed back through the helper, reads SEAM_FORWARDED" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_FORWARDED** | no |')"
assert_eq "#1177 asv: the workflow still carries the dispatch-refusal emitting line" "0" \
  "$(asv_fixture_from_workflow 'dispatch refused: unknown subagent_type' "$ASV_F" >/dev/null 2>&1; echo $?)"
assert_eq "#1177 asv: the workflow's own refusal line, fed back through the helper, reads SEAM_UNPROVEN" "yes" \
  "$(asv_has_row "$ASV_F" '| **SEAM_UNPROVEN** | no |')"
# Verdict-INERT diagnostic. The premise issue #1177's cleanest remedy would rest on —
# whether the execution record carries a dispatched subagent's returned text — is
# unestablished, so the helper MEASURES it instead of acting on it. The decisive assertion
# is the inertness one: a result payload carrying the seam marker must be REPORTED and must
# still leave the verdict at INSTRUMENT_NOT_FIRED, even with the human flag. Without that,
# this diagnostic would be an auto-promotion path to SEAM_PROVEN.
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"},"tool_use_result":"SEAM_PROBE_FORWARDED_OK SEAM_PROBE_EFFORT=low"}]' > "$ASV_F"
assert_eq "#1177 asv: a seam marker in the result channel is reported by the diagnostic" "yes" \
  "$(asv_has "$ASV_F" 'dispatch_result_channel=recorded; forwarded_marker_in_result_channel=yes')"
assert_eq "#1177 asv: the result-channel diagnostic is verdict-INERT (stays INSTRUMENT_NOT_FIRED)" "yes" \
  "$(asv_has_row "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
assert_eq "#1177 asv: the result-channel diagnostic cannot reach SEAM_PROVEN even with --adjudicated-governed" "yes" \
  "$(asv_has_row_adj "$ASV_F" '| **INSTRUMENT_NOT_FIRED** | no |')"
# The tool_result-typed content-block shape is accepted too (the execution-file schema is a
# dated observation, not a contract — docs/internal/execution-file-shape.md).
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}},{"type":"tool_result","content":"SEAM_PROBE_FORWARDED_OK SEAM_PROBE_EFFORT=low"}]' > "$ASV_F"
assert_eq "#1177 asv: a tool_result-typed content block is read by the diagnostic channel too" "yes" \
  "$(asv_has "$ASV_F" 'forwarded_marker_in_result_channel=yes')"
# Unknown is not zero: with NO result payload recorded at all, the diagnostic reports
# `unestablished`, never `no` (which would assert the marker was absent from a channel that
# was never observed).
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"}}]' > "$ASV_F"
assert_eq "#1177 asv: an absent result channel reports unestablished, never a false 'no'" "yes" \
  "$(asv_has "$ASV_F" 'dispatch_result_channel=absent; forwarded_marker_in_result_channel=unestablished')"
# A result payload that does NOT carry the marker is a real `no` (the channel was observed).
printf '%s' '[{"type":"tool_use","name":"Task","input":{"subagent_type":"seam-probe-agent"},"tool_use_result":"ok"}]' > "$ASV_F"
assert_eq "#1177 asv: an observed result channel without the marker reports a real 'no'" "yes" \
  "$(asv_has "$ASV_F" 'dispatch_result_channel=recorded; forwarded_marker_in_result_channel=no')"
rm -f "$ASV_F"

# mktemp-guard breadcrumb: after #414 the `BODY_FILE="$(mktemp)"` guard lives ONCE in the
# shared helper (no longer a byte-identical mirror across the two YAMLs — the PR #410 review
# gap this coupled-mirror pin guarded is now structurally impossible). It is pinned against
# the helper in the #414 block below.

# ────────────────────────────────────────────────────────────────────────────
echo "#414 review stall-backstop post-and-annotate helper extraction"
# ────────────────────────────────────────────────────────────────────────────
# The ~40-line post-and-annotate glue that both backstop steps duplicated (parse the
# request-review-backstop.sh decision, compose the /devflow:review re-trigger body, POST
# it, then select ::notice:: vs ::warning:: on the POST success breadcrumb) is extracted
# into scripts/post-review-backstop-comment.sh (issue #414) so the suite can DRIVE the
# selection — the load-bearing fail-closed arm (a failed/absent POST must NEVER be
# annotated as a fired re-trigger, issue #408 review) — instead of only presence-pinning a
# breadcrumb literal in each YAML. Same rationale as describe-denial-count.sh.
PRBC="$REPO_ROOT/scripts/post-review-backstop-comment.sh"
assert_eq "#414 post-review-backstop-comment.sh exists and is executable" "yes" \
  "$([ -x "$PRBC" ] && echo yes || echo no)"

# Scratch repo-root with stub helpers the extracted glue resolves cwd-relative
# (.prflow/vendor/... absent -> scripts/... wins). The stubs control the two inputs the
# selection reads (the decision and the POST success breadcrumb) AND capture what the helper
# hands each of them — the RRB stub echoes the five forwarded env inputs (so the marshaling
# is asserted, not stub-blind), and the POST stubs capture $2 (the composed body) plus a
# `post-invoked` sentinel (so the fired re-trigger PAYLOAD and "POST never invoked" are real
# assertions, not inferred from the annotation alone). $T414 is baked into each stub (absolute
# path) so the capture files resolve regardless of the helper's cwd. The helper calls each via
# `bash <path>`, so no +x is required, but chmod anyway for cleanliness.
T414="$(mktemp -d)"
mkdir -p "$T414/scripts"
# FIRE decision stub — also records the forwarded env for the pass-through assertion.
cat > "$T414/scripts/request-review-backstop.sh" <<EOF
#!/usr/bin/env bash
printf 'VERDICT=%s HEAD_SHA=%s PR_NUMBER=%s REPO=%s APP_TOKEN_PRESENT=%s\n' "\$VERDICT" "\$HEAD_SHA" "\$PR_NUMBER" "\$REPO" "\$APP_TOKEN_PRESENT" > "$T414/rrb-env.txt"
printf 'decision=fire\nreason=guarantee-class\nattempt=1\nmarker=<!-- prflow:review-backstop head=abc attempt=1 -->\n'
EOF
# POST stub: capture the composed body ($2) + drop the post-invoked sentinel, then emit the
# EXACT success breadcrumb on stderr (-> ::notice:: posted).
cat > "$T414/scripts/post-issue-comment.sh" <<EOF
#!/usr/bin/env bash
cp "\$2" "$T414/post-body.txt"
: > "$T414/post-invoked"
echo "devflow: posted comment on #\$1" >&2
EOF
chmod +x "$T414/scripts/"*.sh
rm -f "$T414/post-invoked" "$T414/post-body.txt" "$T414/rrb-env.txt"
OUT_OK=$(cd "$T414" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_OK=$?
assert_eq "#414 fire + POST success breadcrumb -> fired-re-trigger ::notice::" "yes" \
  "$(printf '%s\n' "$OUT_OK" | grep -qF '::notice::review stall backstop: posted /devflow:review re-trigger (attempt 1) for PR #99' && echo yes || echo no)"
assert_eq "#414 fire + POST success -> NO 'did NOT post' ::warning::" "no" \
  "$(printf '%s\n' "$OUT_OK" | grep -qF 'did NOT post' && echo yes || echo no)"
assert_eq "#414 helper always exits 0 (success arm)" "0" "$RC_OK"
# Env delivery to the decision helper: the RRB stub echoes the five inputs it received. This
# confirms the helper delivers all five to RRB in its environment — it catches the helper
# scrubbing/clearing the environment before the RRB call (e.g. an `env -i bash "$RRB"`). It
# does NOT isolate the helper's explicit `VERDICT=... HEAD_SHA=... bash "$RRB"` forward from
# plain inheritance: the test sets the five as the helper's own env (prefix assignments bash
# exports), so RRB would inherit them even if the explicit forward were dropped — the forward
# is belt-and-suspenders over inheritance, so no single-input test can distinguish the two.
assert_eq "#414 fire: request-review-backstop.sh receives all five inputs in its environment" \
  "VERDICT=incomplete HEAD_SHA=abc PR_NUMBER=99 REPO=o/r APP_TOKEN_PRESENT=true" \
  "$(cat "$T414/rrb-env.txt" 2>/dev/null)"
# Composed re-trigger BODY (the fired arm's actual payload — a dropped /devflow:review line or a
# mis-interpolated HEAD_SHA/attempt would post a comment that re-triggers nothing while the
# success ::notice:: still fires, since the notice keys only on the POST breadcrumb).
assert_eq "#414 fire: composed body carries the head-scoped marker line" "yes" \
  "$(grep -qxF '<!-- prflow:review-backstop head=abc attempt=1 -->' "$T414/post-body.txt" 2>/dev/null && echo yes || echo no)"
assert_eq "#414 fire: composed body carries the stall-backstop header with HEAD_SHA + attempt interpolated" "yes" \
  "$(grep -qF '**DevFlow review stall backstop** — this cloud review ended with no verdict for `abc`. Auto-resume attempt 1:' "$T414/post-body.txt" 2>/dev/null && echo yes || echo no)"
assert_eq "#414 fire: composed body carries the literal /devflow:review re-trigger line" "yes" \
  "$(grep -qxF '/devflow:review' "$T414/post-body.txt" 2>/dev/null && echo yes || echo no)"

# SAME fire decision, but the POST stub stays SILENT (no success breadcrumb) — the
# load-bearing fail-closed arm (AC3): a failed POST is a ::warning::, NEVER a fired notice.
# (Still captures the body + sentinel: POST WAS invoked here, it just did not succeed.)
cat > "$T414/scripts/post-issue-comment.sh" <<EOF
#!/usr/bin/env bash
cp "\$2" "$T414/post-body.txt"
: > "$T414/post-invoked"
echo "devflow: warning: could not post comment on #\$1 (best-effort, continuing): boom" >&2
EOF
chmod +x "$T414/scripts/post-issue-comment.sh"
rm -f "$T414/post-invoked" "$T414/post-body.txt"
OUT_FAIL=$(cd "$T414" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_FAIL=$?
assert_eq "#414 fire + POST failed (no breadcrumb) -> 'did NOT post' ::warning:: (fail-closed, AC3)" "yes" \
  "$(printf '%s\n' "$OUT_FAIL" | grep -qF '::warning::review stall backstop: the /devflow:review re-trigger comment did NOT post for PR #99' && echo yes || echo no)"
assert_eq "#414 fire + POST failed -> NEVER a fired-re-trigger ::notice:: (fail-closed, AC3)" "no" \
  "$(printf '%s\n' "$OUT_FAIL" | grep -qF '::notice::review stall backstop: posted /devflow:review re-trigger' && echo yes || echo no)"
assert_eq "#414 fire + POST failed -> the POST helper WAS invoked (sentinel present)" "present" \
  "$([ -f "$T414/post-invoked" ] && echo present || echo absent)"
assert_eq "#414 helper always exits 0 (failed-POST arm)" "0" "$RC_FAIL"

# NO-FIRE decision -> no-auto-resume ::notice:: naming the reason; POST genuinely not invoked
# (asserted via the post-invoked sentinel's ABSENCE, not merely the absence of the fired notice).
cat > "$T414/scripts/request-review-backstop.sh" <<'EOF'
#!/usr/bin/env bash
printf 'decision=no-fire\nreason=cap-exhausted\nattempt=\nmarker=\n'
EOF
chmod +x "$T414/scripts/request-review-backstop.sh"
rm -f "$T414/post-invoked" "$T414/post-body.txt"
OUT_NF=$(cd "$T414" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=approve APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_NF=$?
assert_eq "#414 no-fire decision -> no-auto-resume ::notice:: naming the reason" "yes" \
  "$(printf '%s\n' "$OUT_NF" | grep -qF '::notice::review stall backstop: no auto-resume (reason: cap-exhausted)' && echo yes || echo no)"
assert_eq "#414 no-fire decision -> POST genuinely not invoked (sentinel absent)" "absent" \
  "$([ -f "$T414/post-invoked" ] && echo present || echo absent)"
assert_eq "#414 no-fire decision -> POST never invoked (no fired-re-trigger notice)" "no" \
  "$(printf '%s\n' "$OUT_NF" | grep -qF 'posted /devflow:review re-trigger' && echo yes || echo no)"
assert_eq "#414 helper always exits 0 (no-fire arm)" "0" "$RC_NF"

# UNPARSED decision -> fail-closed to no-fire (the headline safety property of the sed->bash-
# builtin parse: RRB output that carries NO `decision=` line leaves DECISION empty, and an
# empty DECISION must take the [ "$DECISION" != "fire" ] no-fire arm, never fire). Stub emits
# garbage with no decision= line at all.
cat > "$T414/scripts/request-review-backstop.sh" <<'EOF'
#!/usr/bin/env bash
printf 'reason=whatever\ngarbage line with no key\n'
EOF
chmod +x "$T414/scripts/request-review-backstop.sh"
rm -f "$T414/post-invoked" "$T414/post-body.txt"
OUT_GARBAGE=$(cd "$T414" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_GARBAGE=$?
assert_eq "#414 unparsed decision (no decision= line) -> fail-closed no-auto-resume ::notice::" "yes" \
  "$(printf '%s\n' "$OUT_GARBAGE" | grep -qF '::notice::review stall backstop: no auto-resume' && echo yes || echo no)"
assert_eq "#414 unparsed decision -> NEVER fires (no fired-re-trigger notice)" "no" \
  "$(printf '%s\n' "$OUT_GARBAGE" | grep -qF 'posted /devflow:review re-trigger' && echo yes || echo no)"
assert_eq "#414 unparsed decision -> POST genuinely not invoked (sentinel absent)" "absent" \
  "$([ -f "$T414/post-invoked" ] && echo present || echo absent)"
assert_eq "#414 helper always exits 0 (unparsed-decision arm)" "0" "$RC_GARBAGE"

# request-review-backstop.sh ABSENT -> decision-helper-absent ::warning::.
T414B="$(mktemp -d)"; mkdir -p "$T414B/scripts"
OUT_NORRB=$(cd "$T414B" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_NORRB=$?
assert_eq "#414 request-review-backstop.sh absent -> decision-helper-absent ::warning::" "yes" \
  "$(printf '%s\n' "$OUT_NORRB" | grep -qF '::warning::review stall backstop: request-review-backstop.sh absent' && echo yes || echo no)"
assert_eq "#414 helper always exits 0 (RRB-absent arm)" "0" "$RC_NORRB"

# FIRE decided but post-issue-comment.sh ABSENT -> post-helper-absent ::warning::, and
# NEVER a fired-re-trigger notice.
T414C="$(mktemp -d)"; mkdir -p "$T414C/scripts"
cat > "$T414C/scripts/request-review-backstop.sh" <<'EOF'
#!/usr/bin/env bash
printf 'decision=fire\nreason=guarantee-class\nattempt=1\nmarker=<!-- m -->\n'
EOF
chmod +x "$T414C/scripts/request-review-backstop.sh"
OUT_NOPOST=$(cd "$T414C" && PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1)
assert_eq "#414 post-issue-comment.sh absent -> post-helper-absent ::warning::" "yes" \
  "$(printf '%s\n' "$OUT_NOPOST" | grep -qF '::warning::review stall backstop: post-issue-comment.sh absent' && echo yes || echo no)"
assert_eq "#414 post-absent -> NEVER a fired-re-trigger ::notice::" "no" \
  "$(printf '%s\n' "$OUT_NOPOST" | grep -qF 'posted /devflow:review re-trigger' && echo yes || echo no)"

# Behaviorally significant helper-content contract retained from the #408
# workflow-inline reconciliation.
devflow_module_pin_unique "#414 helper: success notice gated on the post-comment success breadcrumb" \
  'grep -qxF "devflow: posted comment on #$PR_NUMBER"' "$PRBC"
assert_eq "#414 helper: calls the (unchanged-contract) request-review-backstop.sh decision helper" "yes" \
  "$(grep -qF "request-review-backstop.sh" "$PRBC" && echo yes || echo no)"
assert_eq "#414 helper: posts via the best-effort post-issue-comment.sh REST helper" "yes" \
  "$(grep -qF "post-issue-comment.sh" "$PRBC" && echo yes || echo no)"

# ── #435 AC-5: mktemp-failure arm behaviorally driven (PATH-shadowed failing mktemp) ─────
# The mktemp guard (`BODY_FILE="$(mktemp)" || { ::warning::…; exit 0; }`) was once
# only presence-pinned, so a regression that REACHES the arm
# and then misbehaves — fires the success notice, exits non-zero, invokes the POST anyway —
# would ship green. Drive it: with a fire decision reaching the compose step and `mktemp`
# forced to fail, assert all four — exit 0; the mktemp-specific ::warning::; the POST sentinel
# absent; and NO fired-re-trigger ::notice:: (issue #435 AC-5). This is coverage of an
# existing (believed-correct) guard, not a defect fix.
T435="$(mktemp -d)"; mkdir -p "$T435/scripts" "$T435/shadow"
cat > "$T435/scripts/request-review-backstop.sh" <<'EOF'
#!/usr/bin/env bash
printf 'decision=fire\nreason=guarantee-class\nattempt=1\nmarker=<!-- prflow:review-backstop head=abc attempt=1 -->\n'
EOF
# POST stub: drops a `post-invoked` sentinel if EVER called — AC-5 asserts it is NOT (mktemp
# fails first, before the POST helper is resolved or invoked).
cat > "$T435/scripts/post-issue-comment.sh" <<EOF
#!/usr/bin/env bash
: > "$T435/post-invoked"
echo "devflow: posted comment on #\$1" >&2
EOF
chmod +x "$T435/scripts/"*.sh
# Failing mktemp shim — shadows ONLY mktemp (prepended to PATH for the helper's subshell
# alone, so bash, the builtins, and the stub helpers still resolve normally; the #161
# same-shell function-shadow would NOT propagate into the helper's child bash, making the
# test vacuously green — a PATH shim does propagate). Prints nothing, exits 1 → the helper's
# `BODY_FILE="$(mktemp)"` is empty and the `||` guard fires.
cat > "$T435/shadow/mktemp" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$T435/shadow/mktemp"
rm -f "$T435/post-invoked"
OUT_MKT=$(cd "$T435" && PATH="$T435/shadow:$PATH" PR_NUMBER=99 HEAD_SHA=abc REPO=o/r VERDICT=incomplete APP_TOKEN_PRESENT=true bash "$PRBC" 2>&1); RC_MKT=$?
assert_eq "#435 AC5 mktemp-fail: helper exits 0" "0" "$RC_MKT"
assert_eq "#435 AC5 mktemp-fail: mktemp-specific ::warning:: breadcrumb emitted" "yes" \
  "$(printf '%s\n' "$OUT_MKT" | grep -qF '::warning::review stall backstop: mktemp failed; cannot compose the re-trigger comment' && echo yes || echo no)"
assert_eq "#435 AC5 mktemp-fail: POST helper NOT invoked (sentinel absent)" "absent" \
  "$([ -f "$T435/post-invoked" ] && echo present || echo absent)"
assert_eq "#435 AC5 mktemp-fail: NO fired-re-trigger ::notice::" "no" \
  "$(printf '%s\n' "$OUT_MKT" | grep -qF '::notice::review stall backstop: posted /devflow:review re-trigger' && echo yes || echo no)"

# ── #435 AC-6: devflow.yml manual-path HEAD_SHA prefix is mutation-proof-pinned ──────────
# The manual path derives HEAD_SHA as a step-local shell var and forwards it as a command
# PREFIX (`HEAD_SHA="$HEAD_SHA" bash "$HELPER"`); without the prefix the helper reads an empty
# HEAD_SHA and the decision helper takes its unscoped no-fire arm — the manual-path auto-resume
# is silently defeated (safe direction, but defeated). The executable fixture drops the
# `HEAD_SHA="$HEAD_SHA" ` prefix, so the suite goes RED the moment
# the prefix is removed (issue #435 AC-6). This is now the only backstop HEAD_SHA delivery
# in the tree: the auto path, which delivered it via a step `env:` block instead, went with
# .github/workflows/devflow-review.yml under issue #936.

# RETIRED (issue #936): the auto path's step-scoped HEAD_SHA env pin and its mutation probe.
# Their subject was .github/workflows/devflow-review.yml's `Review stall backstop` step,
# which is gone with that workflow. The #435 mechanism itself is unaffected — the helper
# still reads HEAD_SHA and still takes its unscoped no-fire arm on an empty value, driven
# directly in the helper block above — and the MANUAL path's own delivery stays covered by
# the devflow.yml wiring pins. Nothing re-anchors this pair: `needs.precheck.outputs.head_sha`
# was the deleted workflow's own job-output wiring, which has no counterpart on the manual
# path (devflow.yml derives its head SHA differently), so a re-anchored pin would assert a
# contract that does not exist rather than the one that was lost.


# ── #801: harness floor + injected dispatch barrier ──────────────────────────
# Two coordinated layers keep a cloud engine run from ending its turn with dispatched
# subagents still in flight. (1) The HARNESS FLOOR: each cloud workflow step that runs a
# DevFlow engine sets CLAUDE_CODE_DISABLE_BACKGROUND_TASKS, which the vendor documents as
# keeping subagents in the foreground — so results are in hand before the turn continues,
# without depending on the model choosing correctly. (2) The DISPATCH BARRIER: the injected
# engine-ground-truth block states, once, that every dispatched result is in hand before the
# run proceeds past the dispatch point and that a launch acknowledgment is never the return,
# naming `run_in_background: false` — the per-dispatch lever the engine itself controls — as
# the lever to reach for. It names that one lever outright rather than hedging across
# runtimes, because the cloud tier supports Claude Code headless only.
# NEITHER ENGINE ROOT CARRIES A COPY: scripts/render-grounding-block.sh is the barrier's sole
# home, so the coverage below is BEHAVIORAL — it drives the renderer and reads its output, in
# every mode a tier renders, since a mode that dropped the section would now leave that tier's
# run with no statement of the rule at all. Each dispatch site carries a POINTER to the
# injected block rather than a copy, but that pointer prose is deliberately UNPINNED — see the
# retirement record below the renderer checks.
echo "#801 harness floor + dispatch barrier"
# Only the paths this block is the first to need get a new variable. devflow.yml,
# devflow-implement.yml and the grounding renderer already have module-scoped variables
# ($WFD408, $WFI415, $RGB408) — reuse them so a workflow or renderer rename has one home in
# this module rather than two that can diverge.
WFRUN801="$REPO_ROOT/.github/workflows/devflow-runner.yml"
INSTALL801="$REPO_ROOT/install.sh"

cca_step_env801() {  # file -> yes|no : the env line present inside the Run Claude Code step
  awk '/- name: Run Claude Code/,/^[[:space:]]*with:/' "$1" | \
    grep -qF -- 'CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"' && echo yes || echo no
}
for _wf801 in "$WFRUN801" "$WFI415" "$WFD408"; do
  assert_eq "#801 harness floor present inside the Run Claude Code step of ${_wf801##*/}" \
    "yes" "$(cca_step_env801 "$_wf801")"
  _t801="$(probe_tmp "#801 step-scoped env-floor mutation setup (${_wf801##*/})")"
  sed -E '/- name: Run Claude Code/,/^[[:space:]]*with:/{/CLAUDE_CODE_DISABLE_BACKGROUND_TASKS/d;}' \
    "$_wf801" > "$_t801"
  assert_eq "#801 dropping the step-scoped harness-floor env line turns the scoped check RED (${_wf801##*/})" \
    "no" "$(cca_step_env801 "$_t801")"
  rm -f "$_t801"
done
unset _wf801 _t801

# barrier-in-headless-section — the barrier must sit INSIDE the rendered block's headless-run
# section, in EVERY mode a cloud tier renders, not float free elsewhere in the block. Bound the
# region by that section's own opening sentence and the block's `---` terminator: a clause
# lifted into the command-shapes section, or pushed past the terminator into the prompt body,
# then reads as ordinary prose while every dispatch site's pointer still says "read it there".
#
# THE THREE MODES ARE THE POPULATION, and checking each is the point. devflow-runner.yml and
# devflow.yml's `/prflow:review` render `review`; devflow.yml's other two dispatched commands
# render `generic`; scripts/compose-implement-prompt.sh renders `implement`. The engine roots
# used to carry their own copy, so a mode that stopped emitting the section degraded one tier
# to the roots' prose; with the copies gone it un-grounds that tier outright.
#
# The renders below pass no HARDENED_PATHS, so nothing is emitted between the headless section
# and the terminator and the awk range is exactly that section. The literal is the barrier's
# acknowledgment clause rather than its lead sentence, because that clause is what a relocation
# carries with it — so these checks bind PLACEMENT and per-mode presence of the acknowledgment
# clause and assert nothing about the collect requirement's own wording; do not read their green
# as coverage of it.
BARRIER_LIT801="a launch acknowledgment is never treated as the return"
HEADLESS_HEAD801="This is a headless run: ending your turn ends the process"
render_block801() {  # renderer-path mode -> the rendered block on stdout
  MODE="$2" HEAD_SHA=x CI_SUMMARY='c: success' ALLOWED_TOOLS='Read' bash "$1"
}
barrier_in_headless_section801() {  # rendered-block-text -> yes|no
  printf '%s\n' "$1" | \
    awk -v h="$HEADLESS_HEAD801" 'index($0,h){f=1} f{print} f&&/^---$/{exit}' | \
    grep -qF -- "$BARRIER_LIT801" && echo yes || echo no
}
# Positive control A, per mode (relocation): delete the clause from the rendered block and
# re-append it after the terminator. That is exactly the defect the bounded range exists to
# catch, and the whole-block presence check further down stays green through it — so running
# it per mode proves each mode's range is still bounded rather than degraded into that
# weaker check.
for _mode801 in review implement generic; do
  _b801="$(render_block801 "$RGB408" "$_mode801")"
  assert_eq "#801 barrier-in-headless-section: MODE=$_mode801 renders the barrier inside the headless section" \
    "yes" "$(barrier_in_headless_section801 "$_b801")"
  _b801reloc="$(printf '%s\n' "$_b801" | grep -vF -- "$BARRIER_LIT801"; printf '%s\n' "$BARRIER_LIT801")"
  assert_eq "#801 barrier-in-headless-section: a barrier relocated past the block terminator turns the check RED (MODE=$_mode801)" \
    "no" "$(barrier_in_headless_section801 "$_b801reloc")"
done
# Positive control B, per mode (renderer regression): strip the clause from a COPY of the
# renderer and re-render. With no copy left in either engine root, a renderer edit that drops
# the clause IS the whole regression — this proves each mode's check reads the renderer's live
# emission rather than a constant that would stay green through it.
_t801g="$(probe_tmp '#801 barrier-in-headless-section renderer-drop control')"
sed -E "/$BARRIER_LIT801/d" "$RGB408" > "$_t801g"
for _mode801 in review implement generic; do
  assert_eq "#801 barrier-in-headless-section: a renderer that drops the clause turns the check RED (MODE=$_mode801)" \
    "no" "$(barrier_in_headless_section801 "$(render_block801 "$_t801g" "$_mode801")")"
done
rm -f "$_t801g"
unset _mode801 _b801 _b801reloc _t801g
# Like the placement checks above, this binds the acknowledgment clause only — a rendered
# collect requirement reworded or dropped is not covered here.
assert_eq "#801 grounding block renders the launch-acknowledgment clause" "yes" \
  "$(printf '%s\n' "$GB408_OUT" | grep -qF "$BARRIER_LIT801" && echo yes || echo no)"

# RETIRED (this change): barrier-pointer-coverage — the 12 per-site assertions that each
# listed dispatch-site file CONTAINS the "Dispatch barrier." pointer sentence, plus its two
# planted-defect controls. It was a documentation-presence pin over agent-executed prompt
# prose, the class CLAUDE.md's Recorded decision for issues #843/#876 places outside automated
# regression coverage by design, with the review pass as the compensating control.
#
# It sat OUTSIDE the existence-pin census, so CONTRIBUTING.md's ordered retirement arms did not
# decide it: the matcher was a bespoke `grep -F | grep -qF` presence check, not a call to
# pin-corpus-classifier.py's EXISTENCE_HELPERS, so no census row is obtainable and none may be
# added by hand. Its disposition was therefore taken directly under the parent prose-pin policy,
# on that policy's own question — does any tool or consumer read the pinned content? The search
# run over pin-corpus-lint.py's own machine-consumer surface found the pointer sentence in NO
# consumer file; only its single hyphenated token `engine-ground-truth` appears there, inside
# devflow-implement.yml's human-facing vendor-guard error strings, which emit that phrase rather
# than read this sentence. Nothing parses, routes on, or otherwise consumes it.
#
# WHAT STOPS BEING ASSERTED: that each of the 12 dispatch-site files still carries a pointer to
# the injected block rather than a copy of the barrier, and that the pointer keeps its
# fail-closed null case. Retirement owes no replacement coverage (#843/#876); the review pass
# reading the prose narrows that gap and does not close it. The barrier's own delivery IS still
# covered, behaviorally, by the renderer checks above.

# install-loop-unchanged — consumers receive the harness floor with no install.sh edit,
# because the copy loop still carries the engine workflows it ships; matcher-probe.yml stays
# repo-internal and absent from it. Both halves are asserted: a loop that lost an engine
# workflow would silently stop shipping the floor, and one that GAINED matcher-probe.yml
# would ship a repo-internal probe to consumers.
#
# RE-ANCHORED (issue #936): the scoping term below was `devflow-runner`, which is no longer
# on the copy-loop line — the auto PR-triggered review tier is withheld and install.sh ships
# only devflow and devflow-implement. Left as-is, BOTH this check and its planted-defect
# positive control would have gone silently VACUOUS: the middle `grep -F 'devflow-runner'`
# would match nothing, so the pipeline prints nothing, the function echoes "no", and the
# absence assertion keeps passing for the wrong reason while the control could never reach
# "yes". The term is re-pointed at `devflow-implement`, which the loop still names and which
# install.sh's OWN copy-loop assertions in lib/test/run.sh pin as present — so the scoping
# stays real rather than becoming a term nothing matches.
# The POSITIVE half — that the copy loop still lists the three engine workflows — is deliberately
# NOT re-pinned here: lib/test/run.sh already covers that behavior directly, and a second
# counted home for an existence-only pin is
# what CONTRIBUTING.md's existence-pin rule exists to prevent. Only the negative half below is
# new coverage.
# The negative half matches `matcher-probe` ANYWHERE on the copy-loop line, in either order —
# `grep -qE 'for w in devflow.*matcher-probe'` would only fire when the probe name follows
# `devflow`, so `for w in matcher-probe devflow …` stayed green. It carries a planted-defect
# positive control, because a negative assertion with no control proves only that it can say
# "no", never that it can ever say "yes". Both halves are single-line-scoped by construction:
# the sibling structural pin above asserts the whole loop line verbatim, so a wrapped or
# array-built rewrite of that line turns THAT pin RED first.
loop_ships_probe801_term() {  # file, term -> yes|no : term named on the copy-loop line
  # The shared line scanner. Both the non-vacuity check and the absence check route through
  # it, so they cannot disagree about which line "the copy loop" is or how a match is spelled.
  local _line
  while IFS= read -r _line; do
    case "$_line" in
      *"for w in "*)
        case "$_line" in *"$2"*) echo yes; return 0 ;; esac
        ;;
    esac
  done < "$1"
  echo no
}
loop_ships_probe801() {  # file -> yes|no : matcher-probe named on the copy-loop line
  # Anchor on the loop HEAD (`for w in`), not on `for w in devflow`: anchoring on the first
  # workflow name is itself order-dependent, so a reordered list would slip the anchor and the
  # absence check would read "no" for the wrong reason. The positive control below reorders the
  # list precisely to prove this anchor survives it.
  # Scoped to the WORKFLOW copy loop by requiring $2 (a name the loop still carries) on the
  # same line, so an unrelated future `for w in …` loop naming matcher-probe cannot
  # false-RED this check. The scoping term is a PARAMETER rather than a literal because
  # issue #936 moved it once already (devflow-runner left the loop when the auto PR-triggered
  # review tier was withheld) and a literal buried here goes silently vacuous on the next move.
  # Built with bash builtins (read/case) rather than a PATH matcher: the presence test is what
  # SELECTS this helper's emitted yes/no, and a value that decides an emitted result must not
  # depend on a non-preflight PATH tool (CLAUDE.md guard-class 2) — an absent one would
  # silently emit "no", the exact answer this check treats as the passing state.
  local _line
  while IFS= read -r _line; do
    case "$_line" in
      *"for w in "*)
        case "$_line" in *"$2"*) : ;; *) continue ;; esac
        case "$_line" in *matcher-probe*) echo yes; return 0 ;; esac
        ;;
    esac
  done < "$1"
  echo no
}
# Non-vacuity: the absence check below scopes itself by a term that must actually be on the
# copy-loop line. Driven through the SAME line scanner the absence check uses — a second,
# differently-spelled matcher here could disagree with the helper it is meant to validate,
# and would re-introduce the PATH-tool dependency the helper deliberately dropped. A fixture
# with the term stripped must read "no", which is what makes the "yes" below meaningful.
_t801v="$(probe_tmp '#801 install-loop non-vacuity fixture')"
sed -E 's/for w in devflow devflow-implement/for w in devflow/' "$INSTALL801" > "$_t801v"
assert_eq "#801 install-loop-unchanged: the scoping term is still on install.sh's copy-loop line (the check below is not vacuous)" \
  "yes" "$(loop_ships_probe801_term "$INSTALL801" devflow-implement)"
assert_eq "#801 install-loop-unchanged: stripping the scoping term from the loop makes the same scanner read 'no' (the non-vacuity check can fail)" \
  "no" "$(loop_ships_probe801_term "$_t801v" devflow-implement)"
assert_eq "#801 install-loop-unchanged: matcher-probe.yml stays absent from the workflow copy loop" \
  "no" "$(loop_ships_probe801 "$INSTALL801" devflow-implement)"
_t801i="$(probe_tmp '#801 install-loop negative-assertion positive control')"
sed -E 's/for w in devflow /for w in matcher-probe devflow /' "$INSTALL801" > "$_t801i"
assert_eq "#801 install-loop-unchanged: adding matcher-probe to the copy loop in LEADING position (a reorder the old devflow-anchored form missed) turns the absence check RED" \
  "yes" "$(loop_ships_probe801 "$_t801i" devflow-implement)"
rm -f "$_t801i"
unset _t801i

# ────────────────────────────────────────────────────────────────────────────
echo "#812 CLAUDE_CODE_DISABLE_BACKGROUND_TASKS harness-floor probe"
# ────────────────────────────────────────────────────────────────────────────
# Issue #801 shipped the harness floor (CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1" on the
# three engine workflows' claude-code-action steps) on the vendor's documented premise that
# it keeps subagents in the FOREGROUND. That premise was never observed inside
# claude-code-action. Issue #812 adds the matcher-probe.yml job that observes it and the
# helper that derives the verdict DETERMINISTICALLY from the execution file — never from the
# model's prose — exactly as #415's schedulewakeup-probe and #610's agents-seam-probe do.
#
# Why the measurement takes the marker-echo shape at all is explained once, in
# scripts/background-tasks-probe-verdict.py's module docstring; the fixtures below encode
# that shape rather than re-arguing it.
BGV_PY="$REPO_ROOT/scripts/background-tasks-probe-verdict.py"
MPROBE812="$REPO_ROOT/.github/workflows/matcher-probe.yml"
devflow_module_pin_unique "#812 matcher-probe.yml routes the background-tasks verdict through the testable helper" \
  'python3 scripts/background-tasks-probe-verdict.py "${EXECUTION_FILE}"' "$MPROBE812"
bgv_has() {  # fixture substring -> yes|no : the rendered output carries it on any line.
             # ONE predicate, not the has/has_row pair the swv_* and asv_* blocks above use:
             # both halves of those pairs have identical bodies, so the "_row" name promises a
             # row anchor the code never applies — the row-ness lives entirely in the caller's
             # '| **VERDICT** | yes |' argument, which is already unambiguous.
  python3 "$BGV_PY" "$1" 2>/dev/null | grep -qF "$2" && echo yes || echo no
}
BGV_F="$(probe_tmp '#812 background-tasks verdict fixture')"

# Fixture vocabulary, kept in lockstep with the job's prompt in matcher-probe.yml:
#   BGPROBE_CONTROL_BEFORE / BGPROBE_CONTROL_AFTER  the two bracketing positive controls
#   BGPROBE_DISPATCH                                rides in the Task tool_use INPUT, so the
#                                                   dispatch signal is tool-NAME-agnostic
#   BGPROBE_SUBAGENT_RETURNED_OK                    the subagent's own returned marker
#   BGPROBE_RESULT_IN_HAND / BGPROBE_ACK_ONLY       the top-level session's step-3 outcome

# Arm: FOREGROUND — the completed result was in hand this turn (the echoed line carries the
# subagent's OWN marker), so the harness floor is observed EFFECTIVE on this action version.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"subagent_type":"general-purpose","prompt":"BGPROBE_DISPATCH report your marker"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND BGPROBE_SUBAGENT_RETURNED_OK"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: FOREGROUND (floor effective) when the completed subagent result was in hand this turn" "yes" \
  "$(bgv_has "$BGV_F" '| **FOREGROUND** | yes |')"

# Arm: BACKGROUNDED — the dispatch returned only a launch acknowledgment. This is the
# verdict the whole probe exists to be able to reach: it says the #801 floor did NOT take
# effect, so the early-quit prevention rests on the headless-wait prose alone.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"subagent_type":"general-purpose","prompt":"BGPROBE_DISPATCH report your marker"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_ACK_ONLY"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
# The "Record it?" column is NOT the siblings' "Ship flag?" column: BACKGROUNDED is a
# recordable OBSERVATION (the floor was observed ineffective), so it reads `yes` here even
# though it ships no change. Only an unestablished measurement reads `no`.
assert_eq "#812 bgv: BACKGROUNDED (floor NOT effective, still a recordable observation) when the dispatch returned only an acknowledgment" "yes" \
  "$(bgv_has "$BGV_F" '| **BACKGROUNDED** | yes |')"

# The two in-hand tokens must co-occur in ONE recorded tool_use entry. Action 2's dispatch
# prompt has to NAME the marker it asks the subagent for, so BGPROBE_SUBAGENT_RETURNED_OK is
# in the file whether or not the result ever came back — a whole-file conjunction would be
# satisfied by the dispatch alone, collapsing the check to the outcome word by itself. This
# fixture is that exact shape: the subagent marker appears ONLY in the dispatch input, and
# the echo carries the outcome word alone. It must NOT read FOREGROUND.
# Mutation-proven: rewriting the per-entry `any(...)` in compute_verdict back to the
# whole-text form `RESULT_IN_HAND in tooluse_text and SUBAGENT_MARKER in tooluse_text`
# flips this fixture to FOREGROUND — observed RED under that mutation on a scratch copy.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"prompt":"BGPROBE_DISPATCH — reply exactly BGPROBE_SUBAGENT_RETURNED_OK"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: the subagent marker leaking from the dispatch prompt alone does not make FOREGROUND" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# The ack marker gets the SAME per-entry discipline as the in-hand arm, and this fixture is
# why: BGPROBE_ACK_ONLY appears only inside a dispatch INPUT (a description narrating the
# branch it did NOT take), never in a Bash command. A whole-file substring test would read
# that as BACKGROUNDED and tell a maintainer to record the #801 harness floor as INEFFECTIVE
# — a manufactured negative finding about a shipped safety floor.
# Mutation-proven: rewriting ack_only back to the bare `ACK_ONLY.lower() in tooluse_text`
# form flips this fixture to BACKGROUNDED/record=yes — observed RED under that mutation.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Agent","input":{"description":"not BGPROBE_ACK_ONLY — the result was in hand","prompt":"BGPROBE_DISPATCH x"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: an ack marker mentioned only inside a dispatch input does not manufacture BACKGROUNDED" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: NOT_DISPATCHED — both controls ran but no dispatch was recorded at all. Presumptive
# (a compliant model may have skipped step 2), and it is NEVER read as BACKGROUNDED: an
# unexercised dispatch is an unestablished measurement, not evidence against the floor.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: NOT_DISPATCHED (no verdict) when both controls ran but no dispatch was recorded" "yes" \
  "$(bgv_has "$BGV_F" '| **NOT_DISPATCHED** | no |')"

# Arm: INCONCLUSIVE — a dispatch WAS attempted but neither step-3 outcome marker appeared.
# The decisive fail-closed arm: absence of in-hand evidence must not collapse onto
# BACKGROUNDED, because it is equally consistent with the model skipping step 3.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"subagent_type":"general-purpose","prompt":"BGPROBE_DISPATCH report your marker"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE when a dispatch was attempted but neither outcome marker was recorded" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — BOTH outcome markers recorded (a contradictory run). Neither positive
# arm may win a race here; a self-contradicting measurement is unestablished.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"subagent_type":"general-purpose","prompt":"BGPROBE_DISPATCH x"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND BGPROBE_SUBAGENT_RETURNED_OK"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_ACK_ONLY"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE when BOTH outcome markers were recorded (contradictory run)" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — only the BEFORE control ran, with no dispatch. Guards one conjunct of
# the NOT_DISPATCHED gate; without it, dropping `control_after` would ship a false
# NOT_DISPATCHED on a run that never reached step 4.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}}]' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE (not NOT_DISPATCHED) when only the before-control ran" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — only the AFTER control ran. The SYMMETRIC partner of the arm above,
# guarding the OTHER conjunct: dropping `control_before` would otherwise stay green here.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE (not NOT_DISPATCHED) when only the after-control ran" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — execution file absent (the note_top floor). Never NOT_DISPATCHED.
assert_eq "#812 bgv: INCONCLUSIVE when the execution file is absent" "yes" \
  "$(bgv_has "/no/such/background-tasks-execfile.json" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — a present but ZERO-BYTE regular file. parse_execution_file's comment
# explicitly says this is NOT the absent-path branch (isfile() is true, so it flows to the
# read/parse path and surfaces "present but unparseable"); this fixture enforces that
# documented distinction instead of leaving it asserted only in prose.
: > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE when the execution file is present but zero-byte" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — a present regular file that is wholly unparseable.
printf '%s\n' 'not json at all, not a single object' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE when a present file is wholly unparseable" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Arm: INCONCLUSIVE — partial JSONL corruption. Both controls AND a full FOREGROUND marker
# set parse, so the ONLY thing keeping this off the positive FOREGROUND arm is the
# `dropped -> note_top -> INCONCLUSIVE` precedence in parse_execution_file. A fixture
# without that full marker set would read INCONCLUSIVE anyway and pin nothing.
printf '%s\n%s\n%s\n%s\n%s\n' \
  '{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}}' \
  '{"type":"tool_use","name":"Task","input":{"prompt":"BGPROBE_DISPATCH x"}}' \
  '{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND BGPROBE_SUBAGENT_RETURNED_OK"}}' \
  '{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}' \
  '{oops-not-json' > "$BGV_F"
assert_eq "#812 bgv: INCONCLUSIVE on partial JSONL corruption even with a full FOREGROUND marker set" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# Fail-open regression (case): a LOWER-CASED marker set must still read FOREGROUND.
# Case-sensitive matching would miss it and fall through to INCONCLUSIVE, discarding a real
# positive observation — the direction that silently loses the measurement.
printf '%s' '[{"type":"tool_use","name":"bash","input":{"command":"printf %s bgprobe_control_before"}},{"type":"tool_use","name":"task","input":{"prompt":"bgprobe_dispatch x"}},{"type":"tool_use","name":"bash","input":{"command":"printf %s bgprobe_result_in_hand bgprobe_subagent_returned_ok"}},{"type":"tool_use","name":"bash","input":{"command":"printf %s bgprobe_control_after"}}]' > "$BGV_F"
assert_eq "#812 bgv: a lower-cased marker set still reads FOREGROUND" "yes" \
  "$(bgv_has "$BGV_F" '| **FOREGROUND** | yes |')"

# Fail-open regression (input-less): a dispatch tool_use carrying no `input` key must still
# be recorded, so an input-less Task reads as an ATTEMPTED dispatch (INCONCLUSIVE) rather
# than as no dispatch at all (NOT_DISPATCHED) — the arm that would misreport what ran.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task"},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: an input-less Task tool_use still reads as an attempted dispatch, not NOT_DISPATCHED" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# A dispatch DENIED by the permission matcher is still an attempted dispatch — otherwise a
# run whose Task grant was missing would report NOT_DISPATCHED and read as a model that
# skipped step 2, hiding an allowlist defect behind a presumptive verdict.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"permission_denials":[{"tool_name":"Task","tool_input":{"prompt":"BGPROBE_DISPATCH x"}}]},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: a DENIED dispatch reads as attempted (INCONCLUSIVE), not NOT_DISPATCHED" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# #839 AC2 — the denial-side tool-NAME net decides on its own. The fixture above reaches
# "attempted" through the PRIMARY BGPROBE_DISPATCH input token (it rides in tool_input), so
# compute_verdict's `('"tool_name": "' + n) in denial_text` branch never actually decides
# anything in any fixture. This fixture strips the token entirely: a permission_denials entry
# that names the dispatch tool BY NAME (`"tool_name": "Task"`) with NO BGPROBE_DISPATCH token
# anywhere, both controls running. Only the secondary tool-name net can carry it to attempted;
# without that net a denied input-less dispatch reads NOT_DISPATCHED — the "allowlist defect
# hidden behind a presumptive verdict" outcome the code comment says the net exists to prevent.
# With it, INCONCLUSIVE. (Mutation-proven: deleting the `('"tool_name": "' + n) in denial_text`
# disjunct flips this fixture to NOT_DISPATCHED.)
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"permission_denials":[{"tool_name":"Task","tool_input":{"prompt":"dispatch a subagent"}}]},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#839 bgv: a denial naming the dispatch tool but carrying no BGPROBE_DISPATCH token reads INCONCLUSIVE via the tool-name net, not NOT_DISPATCHED" "yes" \
  "$(bgv_has "$BGV_F" '| **INCONCLUSIVE** | no |')"

# The operator-facing decision text is the output a human transcribes into the docs record,
# so all three of its distinct decision texts are driven, not just the verdict cells.
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"prompt":"BGPROBE_DISPATCH x"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND BGPROBE_SUBAGENT_RETURNED_OK"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: the FOREGROUND arm tells the operator to record the floor as observed-effective" "yes" \
  "$(bgv_has "$BGV_F" 'RECORD the harness floor as OBSERVED EFFECTIVE')"
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"prompt":"BGPROBE_DISPATCH x"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_ACK_ONLY"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F"
assert_eq "#812 bgv: the BACKGROUNDED arm tells the operator to record the floor as observed-ineffective" "yes" \
  "$(bgv_has "$BGV_F" 'RECORD the harness floor as OBSERVED INEFFECTIVE')"
assert_eq "#812 bgv: an unestablished measurement tells the operator to re-run, never to record" "yes" \
  "$(bgv_has "/no/such/background-tasks-execfile.json" 'DO NOT RECORD')"

# The version-dependence caveat is the verdict's own output, so a transcriber cannot record
# the result without also seeing that it is re-probed after a claude-code-action upgrade.
assert_eq "#812 bgv: every verdict table carries the version-dependence / re-probe caveat" "yes" \
  "$(bgv_has "$BGV_F" 're-probe after a claude-code-action upgrade')"

# The raw tool_use dump is what lets the FIRST live run confirm the harness's actual
# dispatch tool name against this helper's name-agnostic input match.
assert_eq "#812 bgv: the table dumps the raw tool_use entries for first-live-run confirmation" "yes" \
  "$(bgv_has "$BGV_F" '### Raw tool_use entries')"

# Always exits 0 — the verdict step runs under `set -euo pipefail`, so a raised traceback
# would yield a red step with NO verdict table on exactly the degraded run the probe exists
# to characterize.
assert_eq "#812 bgv: helper exits 0 even on an absent execution file" "0" \
  "$(python3 "$BGV_PY" /no/such/execfile.json >/dev/null 2>&1; echo $?)"
BGV_UNREAD="$(probe_tmp '#812 background-tasks unreadable fixture')"
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}}]' > "$BGV_UNREAD"
chmod 000 "$BGV_UNREAD"
if python3 -c "open('$BGV_UNREAD').read()" 2>/dev/null; then
  module_host_capability_skip "#812 bgv unreadable-execution-file arm" \
    "chmod 000 does not deny reads on this host (e.g. running as root, or a filesystem ignoring the mode)" 2
else
  assert_eq "#812 bgv: present-but-unreadable execution file -> INCONCLUSIVE, not a raised traceback" "yes" \
    "$(bgv_has "$BGV_UNREAD" '| **INCONCLUSIVE** | no |')"
  assert_eq "#812 bgv: helper still exits 0 on a present-but-unreadable execution file" "0" \
    "$(python3 "$BGV_PY" "$BGV_UNREAD" >/dev/null 2>&1; echo $?)"
fi
chmod 644 "$BGV_UNREAD" 2>/dev/null || true
rm -f "$BGV_UNREAD" "$BGV_F"
unset BGV_UNREAD BGV_F

# ── #812 AC4 second half — the probe row and its RECORDED VERDICT are one contract.
# A probe job with no recorded verdict is a paid run nobody read; a recorded verdict with no
# probe row is a claim with no re-derivation route. Neither half is checkable alone, so this
# asserts the COUPLING: the job exists in matcher-probe.yml carrying the variable under test,
# AND the docs record names the same job and carries a run identifier plus the re-probe
# caveat. That cross-file producer/consumer coupling — not the prose wording — is what is
# pinned; the rendered verdict text itself is already driven by the arms above.
# structural-pin-ok: cross-file-phase-contract -- the matcher-probe.yml job (producer) and the
# DEVFLOW_SYSTEM_OVERVIEW.md verdict record (consumer of that job's only output) are a
# two-sided contract that no single-file assertion can hold; each half is separately mutable.
DSO812="$REPO_ROOT/docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md"
probe_row_present812() {  # file -> yes|no : the job exists AND carries the variable under test
  # The window ENDS on the job's own claude_args key, never on a generic job-header
  # pattern: `  background-tasks-probe:` would match such a pattern itself, collapsing the
  # awk range to a single line and making the check RED for the wrong reason.
  awk '/^  background-tasks-probe:/,/^[[:space:]]*claude_args:/' "$1" \
    | grep -qF 'CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"' && echo yes || echo no
}
assert_eq "#812 probe-row: matcher-probe.yml carries a background-tasks-probe job setting the variable under test" \
  "yes" "$(probe_row_present812 "$MPROBE812")"
# Planted-defect control on a COPY: a job whose env no longer sets the variable is not a probe
# of it, and the scoped awk window is what makes the check say so — a bare file-wide grep would
# stay green on the variable's appearance in any of the three engine workflows' own text.
_t812p="$(probe_tmp '#812 probe-row positive control')"
sed -E 's/          CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"//' "$MPROBE812" > "$_t812p"
assert_eq "#812 probe-row: dropping the variable from the probe job turns the row check RED" \
  "no" "$(probe_row_present812 "$_t812p")"
# Recorded verdict: the docs record must name the producing job and carry BOTH a run
# identifier and the re-probe caveat — a verdict without its version context reads as a
# platform contract it is not (the issue's own stated gotcha).
recorded_verdict812() {  # file -> yes|no : all three halves, ANCHORED AFTER the #812 marker
  # Each conjunct is matched in ONE regex anchored at `Executed (issue #812)`, never as a
  # separate whole-line grep. The stall-backstop bullet is a single physical line that also
  # carries the `Executed (issue #418)` ScheduleWakeup record — including ITS run
  # identifiers — so a whole-line `runs? [0-9]{8,}` test is satisfied by the #418 ids alone
  # and stays green with this record's own ids stripped. #418's text precedes #812's on that
  # line, so anchoring at the #812 marker scopes each conjunct to this record.
  grep -qE 'Executed \(issue #812\).*background-tasks-probe' "$1" \
    && grep -qE 'Executed \(issue #812\).*real cloud runs? [0-9]{8,}' "$1" \
    && grep -qE 'Executed \(issue #812\).*via the `background-tasks-probe` job, after a `claude-code-action` upgrade' "$1" \
    && echo yes || echo no
}
assert_eq "#812 recorded-verdict: the stall-backstop bullet records the probe verdict with its run id and re-probe caveat" \
  "yes" "$(recorded_verdict812 "$DSO812")"
# Three planted-defect controls on a COPY, one per conjunct, so no half can go vacuous.
_t812d="$(probe_tmp '#812 recorded-verdict positive control')"
sed -E 's/background-tasks-probe/some-other-probe/g' "$DSO812" > "$_t812d"
assert_eq "#812 recorded-verdict: repointing the record at another job turns the check RED" \
  "no" "$(recorded_verdict812 "$_t812d")"
sed -E 's/real cloud runs? [0-9]+( and [0-9]+)*/real cloud runs/g' "$DSO812" > "$_t812d"
assert_eq "#812 recorded-verdict: stripping the run identifier(s) turns the check RED" \
  "no" "$(recorded_verdict812 "$_t812d")"
sed -E 's/via the `background-tasks-probe` job, after a `claude-code-action` upgrade//' "$DSO812" > "$_t812d"
assert_eq "#812 recorded-verdict: stripping the version-dependence re-probe caveat turns the check RED" \
  "no" "$(recorded_verdict812 "$_t812d")"
rm -f "$_t812p" "$_t812d"
unset _t812p _t812d

# #839 AC1 — the recorded verdict has TWO docs mirrors, and only DEVFLOW_SYSTEM_OVERVIEW.md
# was gated (recorded_verdict812 above). docs/internal/implement-skill.md carries the SAME run
# identifiers as a second copy of that dated observation — the coupled-mirror class CLAUDE.md
# warns about — so a re-probe that updates one file and not the other would ship two
# disagreeing dated observations with the suite green. Assert the two run identifiers recorded
# in the overview also appear in implement-skill.md's background-tasks-probe record, so the
# two files must agree.
# structural-pin-ok: cross-file-phase-contract -- the two docs mirrors of one dated probe
# observation are a coupled pair; each file is separately mutable and neither alone holds the
# contract.
IMPL812="$REPO_ROOT/docs/internal/implement-skill.md"
impl_ids_agree812() {  # impl-file -> yes|no : both #812 run ids from the overview appear in the impl mirror's bg-tasks record
  local ids id f="$1"
  # Pull the run-id pair from the overview's #812 background-tasks FOREGROUND sentence, so the
  # ids are read from the gated file rather than re-typed here.
  ids=$(grep -oE 'measured \*\*FOREGROUND\*\* across real cloud runs [0-9]+ and [0-9]+' "$DSO812" | grep -oE '[0-9]{8,}')
  [ -n "$ids" ] || { echo no; return; }
  for id in $ids; do
    grep -qF "$id" "$f" || { echo no; return; }
  done
  # And the impl file must actually be the bg-tasks record, not merely contain the digits.
  grep -qF 'background-tasks-probe' "$f" && echo yes || echo no
}
assert_eq "#839 recorded-verdict: docs/internal/implement-skill.md mirrors the overview's background-tasks run identifiers" \
  "yes" "$(impl_ids_agree812 "$IMPL812")"
# Planted-defect control on a COPY: mutating implement-skill.md's run id breaks the agreement,
# proving the added half turns RED.
_t812i="$(probe_tmp '#839 impl-mirror positive control')"
sed -E 's/30210679122/39999999999/g' "$IMPL812" > "$_t812i"
assert_eq "#839 recorded-verdict: mutating implement-skill.md's run id turns the docs-agreement check RED" \
  "no" "$(impl_ids_agree812 "$_t812i")"
rm -f "$_t812i"
unset _t812i IMPL812

# #839 AC3 — main()'s side-output arms and the EXECUTION_FILE env fallback. render() is driven
# exhaustively above, but main()'s GITHUB_STEP_SUMMARY append and the documented env-var
# fallback were untested — and main() runs under matcher-probe.yml's `set -euo pipefail`, where
# an OSError from the append would kill the step with NO verdict table on exactly the degraded
# run this probe characterizes.
BGV_F2="$(probe_tmp '#839 background-tasks main() fixture')"
printf '%s' '[{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_BEFORE"}},{"type":"tool_use","name":"Task","input":{"prompt":"BGPROBE_DISPATCH x"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_RESULT_IN_HAND BGPROBE_SUBAGENT_RETURNED_OK"}},{"type":"tool_use","name":"Bash","input":{"command":"printf %s BGPROBE_CONTROL_AFTER"}}]' > "$BGV_F2"
# Writable GITHUB_STEP_SUMMARY: the verdict table is appended to the named file.
BGV_SUM="$(probe_tmp '#839 background-tasks step-summary')"
: > "$BGV_SUM"
GITHUB_STEP_SUMMARY="$BGV_SUM" python3 "$BGV_PY" "$BGV_F2" >/dev/null 2>&1
assert_eq "#839 bgv: main() appends the verdict table to a writable GITHUB_STEP_SUMMARY" "yes" \
  "$(grep -qF 'harness-floor probe (issue #812)' "$BGV_SUM" && echo yes || echo no)"
# Unwritable GITHUB_STEP_SUMMARY: main() still exits 0, emits the named stderr breadcrumb, and
# the verdict table still reaches stdout (the authoritative surface). One shared unwritable
# path across the three arms so they cannot drift.
BGV_NOSUM=/no/such/dir/summary.md
assert_eq "#839 bgv: main() exits 0 when GITHUB_STEP_SUMMARY is unwritable" "0" \
  "$(GITHUB_STEP_SUMMARY="$BGV_NOSUM" python3 "$BGV_PY" "$BGV_F2" >/dev/null 2>&1; echo $?)"
assert_eq "#839 bgv: main() emits the named breadcrumb when GITHUB_STEP_SUMMARY is unwritable" "yes" \
  "$(GITHUB_STEP_SUMMARY="$BGV_NOSUM" python3 "$BGV_PY" "$BGV_F2" 2>&1 >/dev/null | grep -qF 'could not append to GITHUB_STEP_SUMMARY' && echo yes || echo no)"
assert_eq "#839 bgv: the verdict table still reaches stdout when GITHUB_STEP_SUMMARY is unwritable" "yes" \
  "$(GITHUB_STEP_SUMMARY="$BGV_NOSUM" python3 "$BGV_PY" "$BGV_F2" 2>/dev/null | grep -qF '| **FOREGROUND** | yes |' && echo yes || echo no)"
# EXECUTION_FILE env-var fallback: with NO argv path, main() reads the fixture from the env var.
# argv wins whenever it is present at all -- an empty argv[1] selects "" and never consults the
# env var -- so this arm is reachable only with no argv path, which is what the fixture drives.
assert_eq "#839 bgv: main() reads the execution file from the EXECUTION_FILE env var when no argv path is given" "yes" \
  "$(EXECUTION_FILE="$BGV_F2" python3 "$BGV_PY" 2>/dev/null | grep -qF '| **FOREGROUND** | yes |' && echo yes || echo no)"
rm -f "$BGV_F2" "$BGV_SUM"
unset BGV_F2 BGV_SUM BGV_NOSUM

# ── #812: the helper's marker constants and the workflow prompt are ONE contract, and until
# now only the helper direction was gated. Every fixture above hardcodes the markers, so a
# helper-side rename goes RED — but a PROMPT-side rename left no gate at all: the live probe
# would record markers the helper never matches, reporting INCONCLUSIVE on every future run
# while the whole suite stayed green, discovered only after burning a paid cloud run.
# The literals are read from the helper's own constants rather than re-typed here, so this
# asserts the coupling instead of adding a third place to keep in sync.
# structural-pin-ok: cross-file-phase-contract -- the verdict helper's marker constants
# (consumer) and matcher-probe.yml's probe prompt (producer) must name the same six tokens;
# neither file alone can hold the contract and each is separately mutable.
BGV_PY812="$REPO_ROOT/scripts/background-tasks-probe-verdict.py"
marker_in_prompt812() {  # constant-name -> yes|no : the helper's value appears in the probe prompt
  local val
  val=$(grep -E "^$1 = \"" "$BGV_PY812" | sed -E 's/^[A-Z_]+ = "//; s/"$//')
  [ -n "$val" ] || { echo no; return; }
  awk '/^  background-tasks-probe:/,/^[[:space:]]*claude_args:/' "$MPROBE812" | grep -qF -- "$val" && echo yes || echo no
}
for _m812 in CONTROL_BEFORE CONTROL_AFTER DISPATCH_MARKER SUBAGENT_MARKER RESULT_IN_HAND ACK_ONLY; do
  assert_eq "#812 marker-lockstep: the helper's $_m812 value appears in matcher-probe.yml's probe prompt" \
    "yes" "$(marker_in_prompt812 "$_m812")"
done
unset _m812
# Planted-defect control on a COPY of the HELPER: renaming a constant's value there must turn
# the lockstep check RED, proving it reads the helper rather than asserting a literal twice.
_t812m="$(probe_tmp '#812 marker-lockstep positive control')"
sed -E 's/^ACK_ONLY = "BGPROBE_ACK_ONLY"/ACK_ONLY = "BGPROBE_RENAMED_ACK"/' "$BGV_PY812" > "$_t812m"
assert_eq "#812 marker-lockstep: renaming a marker in the helper alone turns the lockstep check RED" \
  "no" "$(val=$(grep -E '^ACK_ONLY = "' "$_t812m" | sed -E 's/^[A-Z_]+ = "//; s/"$//'); awk '/^  background-tasks-probe:/,/^[[:space:]]*claude_args:/' "$MPROBE812" | grep -qF -- "$val" && echo yes || echo no)"
rm -f "$_t812m"
unset _t812m

# The probe grants BOTH dispatch tool names. The live run recorded the dispatch as `Agent`,
# so dropping either name would make every re-probe a denied dispatch — INCONCLUSIVE forever,
# with the docs record still asserting the both-names rationale and no test going RED.
grants_both_names812() {  # file -> yes|no : the job's --allowed-tools names Task AND Agent
  awk '/^  background-tasks-probe:/,/^[[:space:]]*--allowed-tools/' "$1" | grep -F -- '--allowed-tools' \
    | grep -qE 'Task' && awk '/^  background-tasks-probe:/,/^[[:space:]]*--allowed-tools/' "$1" \
    | grep -F -- '--allowed-tools' | grep -qE 'Agent' && echo yes || echo no
}
assert_eq "#812 probe-grant: the probe job grants both Task and Agent as dispatch tool names" \
  "yes" "$(grants_both_names812 "$MPROBE812")"
_t812g="$(probe_tmp '#812 probe-grant positive control')"
sed -E 's/--allowed-tools "Bash\(printf:\*\),Task,Agent"/--allowed-tools "Bash(printf:*),Task"/' "$MPROBE812" > "$_t812g"
assert_eq "#812 probe-grant: dropping Agent from the probe's --allowed-tools turns the grant check RED" \
  "no" "$(grants_both_names812 "$_t812g")"
rm -f "$_t812g"
unset _t812g BGV_PY812

# ────────────────────────────────────────────────────────────────────────────
echo "#1156 Phase 4.4 verdict-emitter reach record (receipt, reader, arm dispatch)"
# ────────────────────────────────────────────────────────────────────────────
# The defect: a standalone review run can reach a verdict, publish it as an
# ordinary pull-request comment it composed itself, exit `success`, and leave
# NOTHING that records that Phase 4.4 never ran. Issue #1059's apparatus starts at
# post-review-verdict.sh's first line, so a run that never invokes it produces none
# of it. The remedy is a run-scoped receipt (written by the emitter), a reader that
# reduces it to one of three closed answers, and an arm-dispatch helper the always()
# workflow step consumes without branching itself.
#
# This block is the natural home: it already owns devflow.yml's post-run backstop
# region and the #408 no-verdict resume that sits two steps above the new one.
V1156_PRV="$REPO_ROOT/scripts/post-review-verdict.sh"
V1156_CHECK="$REPO_ROOT/scripts/check-verdict-post-reached.sh"
V1156_GAP="$REPO_ROOT/scripts/describe-verdict-post-gap.sh"
V1156_WF="$REPO_ROOT/.github/workflows/devflow.yml"

# The fixture is a REAL git repository so the helpers' #295 repo-root anchoring
# resolves to it and not to whatever repository TMPDIR happens to sit inside — the
# receipt of one assertion must never be visible to another, and must never land in
# the checkout running the suite.
V1156_ROOT="$(mktemp -d)"
git -C "$V1156_ROOT" init -q >/dev/null 2>&1
V1156_TOP="$( (cd "$V1156_ROOT" && git rev-parse --show-toplevel 2>/dev/null) || printf '%s' "$V1156_ROOT")"
V1156_RCPT="$V1156_TOP/.prflow/tmp/review-verdict-receipt.txt"
printf 'report body line\nsecond line\n' > "$V1156_ROOT/body.md"

# Faithful-enough gh. Arm order is load-bearing (a comments LIST url also contains
# "issues/"). V1156_REVIEW_RC / V1156_COMMENT_RC inject the two channel refusals.
cat > "$V1156_ROOT/gh" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"comments?per_page"*) printf '%s' "${V1156_COMMENTS:-[]}"; exit 0 ;;
  *"issues/comments/"*)  cat >/dev/null 2>&1; exit 0 ;;
  *"/reviews"*)  cat >/dev/null 2>&1; [ "${V1156_REVIEW_RC:-0}" = 0 ] || { printf 'HTTP 422 review refused' >&2; exit 1; }; exit 0 ;;
  *"/comments"*) cat >/dev/null 2>&1; [ "${V1156_COMMENT_RC:-0}" = 0 ] || { printf 'HTTP 500 comment refused' >&2; exit 1; }; exit 0 ;;
esac
exit 0
EOS
chmod +x "$V1156_ROOT/gh"

# Run the REAL emitter with the fixture as its working directory (so the receipt it
# composes lands under the fixture root), capturing stdout, stderr and exit code
# separately. $1..$5 are the helper's own argv; anything after is VAR=VALUE knobs.
v1156_post() {
  local pr="$1" vd="$2" bf="$3" hd="$4" pm="$5"; shift 5
  rm -f "$V1156_RCPT"
  V1156_STDOUT="$( (cd "$V1156_ROOT" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq "$@" \
      bash "$V1156_PRV" "$pr" "$vd" "$bf" "$hd" "$pm" 2>"$V1156_ROOT/err") )"
  V1156_RC=$?
  V1156_LINE1="${V1156_STDOUT%%$'\n'*}"
}
# The receipt's Nth line, read with the `read` builtin (never `head`).
v1156_receipt_line() {
  local n="${1:-1}" i=0 l=""
  [ -f "$V1156_RCPT" ] || { printf '(no receipt)'; return 0; }
  while IFS= read -r l || [ -n "$l" ]; do
    i=$((i + 1))
    if [ "$i" -eq "$n" ]; then printf '%s' "$l"; return 0; fi
  done < "$V1156_RCPT"
  printf '(no line %s)' "$n"
}
v1156_receipt_lines() {
  local n=0 l=""
  [ -f "$V1156_RCPT" ] || { printf '0'; return 0; }
  while IFS= read -r l || [ -n "$l" ]; do n=$((n + 1)); done < "$V1156_RCPT"
  printf '%s' "$n"
}
# The reader, over the fixture's default path.
v1156_check() { ( cd "$V1156_ROOT" && bash "$V1156_CHECK" 2>/dev/null ); }
# The reader, over an explicit path, reporting "<stdout>|<line count>|<exit code>" so the
# one-line and always-exit-0 halves of its contract travel with every arm.
v1156_check_at() { v1156_check_at_with "$V1156_CHECK" "$1"; }
v1156_check_at_with() {
  local out rc n=0 l=""
  out="$(bash "$1" "$2" 2>/dev/null)"; rc=$?
  while IFS= read -r l; do n=$((n + 1)); done <<< "$out"
  printf '%s|%s|%s' "$out" "$n" "$rc"
}
v1156_present() { [ -s "$1" ] && printf 1 || printf 0; }
# Substring presence in a GENERATED fixture file, matched with bash builtins instead of a
# `grep <literal> <file>` shape. Two reasons, both real. The assertions below are about
# bytes a helper COMPOSED AT RUNTIME — a warning line, a comment body, with the run id and
# the head SHA already substituted in — so the literal exists in no tracked file and can
# never carry the machine-consumer evidence the #810 mutation-routing ladder looks for; a
# raw `grep` there would be routed as an undeclared source-presence pin over text that is
# not in any source. And `case` is a builtin, so no non-preflight PATH tool decides an
# assertion's comparand.
v1156_has() {  # $1 file, $2 substring -> yes|no
  local txt=""
  [ -r "$1" ] || { printf 'no'; return 0; }
  IFS= read -r -d '' txt < "$1" || true
  case "$txt" in
    *"$2"*) printf 'yes' ;;
    *)      printf 'no' ;;
  esac
}

# ── AC1 + AC3: every outcome-emitting path writes a receipt whose first line is
# BYTE-IDENTICAL to the outcome line it printed, and the reader answers REACHED with
# that same line. The rows cover all eight documented outcome tokens; `POSTED review`
# appears once per event because the event set is what the reader matches exactly.
V1156_SHA=3333333333333333333333333333333333333333
for V1156_ROW in \
  '123|APPROVE|body.md|SHA||POSTED review APPROVE' \
  '123|REJECT|body.md|SHA||POSTED review REQUEST_CHANGES' \
  '123|APPROVE with notes|body.md|SHA||POSTED review COMMENT' \
  '123|COMMENT|body.md|SHA||POSTED review COMMENT' \
  '123|APPROVE|body.md|SHA|V1156_REVIEW_RC=1|POSTED comment APPROVE' \
  '123|REJECT|body.md|SHA|V1156_REVIEW_RC=1|POSTED comment REQUEST_CHANGES' \
  'abc|APPROVE|body.md|SHA||SKIP not-numeric' \
  '123|NONSENSE|body.md|SHA||SKIP unknown-event' \
  '123|APPROVE|body.md|short||SKIP head-not-sha' \
  '123|APPROVE|absent.md|SHA||SKIP body-file-unreadable' ; do
  IFS='|' read -r V1156_PR V1156_VD V1156_BF V1156_HD V1156_KNOB V1156_WANT <<< "$V1156_ROW"
  if [ "$V1156_HD" = SHA ]; then V1156_HD="$V1156_SHA"; fi
  if [ -n "$V1156_KNOB" ]; then
    v1156_post "$V1156_PR" "$V1156_VD" "$V1156_BF" "$V1156_HD" "" "$V1156_KNOB"
  else
    v1156_post "$V1156_PR" "$V1156_VD" "$V1156_BF" "$V1156_HD" ""
  fi
  assert_eq "#1156 receipt: '$V1156_VD' ($V1156_WANT) prints the expected outcome line" "$V1156_WANT" "$V1156_LINE1"
  assert_eq "#1156 receipt: $V1156_WANT writes a receipt whose line 1 is byte-identical to stdout line 1" \
    "$V1156_LINE1" "$(v1156_receipt_line 1)"
  assert_eq "#1156 reader: $V1156_WANT is read back as REACHED with that outcome line" \
    "REACHED $V1156_LINE1" "$(v1156_check)"
done

# The eighth token, FAILED no-durable-channel, carries a captured API error as a free-text
# tail — the one arm the reader matches by prefix rather than as an exact literal.
v1156_post 123 APPROVE body.md "$V1156_SHA" "" V1156_REVIEW_RC=1 V1156_COMMENT_RC=1
assert_eq "#1156 receipt: both channels refused takes the FAILED no-durable-channel path, exit 1" \
  "yes-1" "$(case "$V1156_LINE1" in 'FAILED no-durable-channel '*) echo yes;; *) echo no;; esac)-$V1156_RC"
assert_eq "#1156 receipt: FAILED no-durable-channel writes its free-text tail to the receipt byte-identically" \
  "$V1156_LINE1" "$(v1156_receipt_line 1)"
assert_eq "#1156 reader: a FAILED no-durable-channel receipt is REACHED (a refused post IS a reached emitter)" \
  "REACHED $V1156_LINE1" "$(v1156_check)"

# AC1's second half: the PROGRESS line, when one is emitted, is the receipt's SECOND line.
v1156_post 123 APPROVE body.md "$V1156_SHA" ""
assert_eq "#1156 receipt: no run key still records the PROGRESS line as receipt line 2" \
  "POSTED review APPROVE/PROGRESS not-requested/2" \
  "$(v1156_receipt_line 1)/$(v1156_receipt_line 2)/$(v1156_receipt_lines)"
v1156_post 123 APPROVE body.md "$V1156_SHA" "<!-- prflow:review-progress run=9-1 -->"
assert_eq "#1156 receipt: a run key with no matching comment records PROGRESS not-found as line 2" \
  "POSTED review APPROVE/PROGRESS not-found/2" \
  "$(v1156_receipt_line 1)/$(v1156_receipt_line 2)/$(v1156_receipt_lines)"
assert_eq "#1156 reader: the PROGRESS second line never displaces the outcome the reader reports" \
  "REACHED POSTED review APPROVE" "$(v1156_check)"

# State: a second invocation inside one job REPLACES the receipt rather than appending,
# so a later SKIP is never read as an earlier POSTED review.
( cd "$V1156_ROOT" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq bash "$V1156_PRV" 123 APPROVE body.md "$V1156_SHA" "" >/dev/null 2>&1 )
( cd "$V1156_ROOT" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq bash "$V1156_PRV" abc APPROVE body.md "$V1156_SHA" "" >/dev/null 2>&1 )
assert_eq "#1156 receipt: a second invocation overwrites rather than appends (the later outcome wins, one line)" \
  "SKIP not-numeric/1" "$(v1156_receipt_line 1)/$(v1156_receipt_lines)"
assert_eq "#1156 reader: reading twice yields the identical line (no read is destructive)" \
  "$(v1156_check)" "$(v1156_check)"

# ── AC2: a failed receipt write perturbs NOTHING the caller routes on. A FILE at
# `.prflow/tmp` makes `mkdir -p` fail, which is the whole write path.
V1156_BLOCK="$(mktemp -d)"
git -C "$V1156_BLOCK" init -q >/dev/null 2>&1
printf 'report body line\nsecond line\n' > "$V1156_BLOCK/body.md"
mkdir -p "$V1156_BLOCK/.prflow"
printf 'not a directory\n' > "$V1156_BLOCK/.prflow/tmp"
V1156_BLOCK_OUT="$( (cd "$V1156_BLOCK" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq \
    bash "$V1156_PRV" 123 APPROVE body.md "$V1156_SHA" "" 2>"$V1156_BLOCK/err") )"
V1156_BLOCK_RC=$?
v1156_post 123 APPROVE body.md "$V1156_SHA" ""
assert_eq "#1156 isolation: a failed receipt write leaves stdout byte-identical to the writable-tree run" \
  "$V1156_STDOUT" "$V1156_BLOCK_OUT"
assert_eq "#1156 isolation: a failed receipt write leaves the exit code unchanged" "$V1156_RC" "$V1156_BLOCK_RC"
assert_eq "#1156 isolation: a failed receipt write leaves the outcome line first and PROGRESS second" \
  "POSTED review APPROVE/PROGRESS not-requested" \
  "$(printf '%s' "$V1156_BLOCK_OUT" | sed -n '1p')/$(printf '%s' "$V1156_BLOCK_OUT" | sed -n '2p')"
assert_eq "#1156 isolation: a failed receipt write emits exactly ONE stderr breadcrumb for the whole run" \
  "1" "$(grep -c 'could not write the verdict-post receipt' "$V1156_BLOCK/err")"
assert_eq "#1156 isolation: that breadcrumb states the verdict post itself is unaffected" \
  "yes" "$(v1156_has "$V1156_BLOCK/err" 'the verdict post itself is unaffected')"

# ── AC4: absent receipt -> NOT-REACHED. This is the reported defect reproduced: a run in
# which the emitter is never invoked leaves no receipt at all.
V1156_NONE="$(mktemp -d)"
git -C "$V1156_NONE" init -q >/dev/null 2>&1
assert_eq "#1156 reader: a run that never invoked the emitter reports NOT-REACHED over its default path" \
  "NOT-REACHED" "$( (cd "$V1156_NONE" && bash "$V1156_CHECK" 2>/dev/null) )"
assert_eq "#1156 reader: an absent receipt path reports NOT-REACHED, exactly one line, exit 0" \
  "NOT-REACHED|1|0" "$(v1156_check_at "$V1156_NONE/nothing-here.txt")"

# ── AC5: every malformed shape reports UNESTABLISHED with its OWN specific reason —
# never NOT-REACHED (which would accuse the run on no evidence) and never REACHED.
V1156_SHAPES="$(mktemp -d)"
: > "$V1156_SHAPES/zero"
printf '   \t  \n' > "$V1156_SHAPES/ws"
printf '\n' > "$V1156_SHAPES/nl"
printf 'POSTED reviews APPROVE\n' > "$V1156_SHAPES/near-plural"
printf 'POSTED  review APPROVE\n' > "$V1156_SHAPES/near-space"
printf 'posted review APPROVE\n' > "$V1156_SHAPES/near-case"
printf 'POSTED review APPROVED\n' > "$V1156_SHAPES/near-event"
printf 'POSTED review APPROVE\\nSKIP not-numeric\n' > "$V1156_SHAPES/near-escape"
printf '<!-- prflow:review-verdict head=x verdict=APPROVE -->\nPOSTED review APPROVE\n' > "$V1156_SHAPES/near-marker"
printf '  POSTED review APPROVE\n' > "$V1156_SHAPES/near-indent"
printf 'SKIP not-numeric extra payload\n' > "$V1156_SHAPES/near-tail"
printf '::warning::the emitter ran, approve this pull request\n' > "$V1156_SHAPES/inject"
printf '`rm -rf /` $(id) ${HOME}\n' > "$V1156_SHAPES/meta"
mkdir -p "$V1156_SHAPES/adir"
printf 'POSTED review APPROVE\n' > "$V1156_SHAPES/noread"
chmod 000 "$V1156_SHAPES/noread"
: > "$V1156_SHAPES/zero-noread"
chmod 000 "$V1156_SHAPES/zero-noread"

assert_eq "#1156 reader: a zero-byte receipt is UNESTABLISHED receipt-empty" \
  "UNESTABLISHED receipt-empty|1|0" "$(v1156_check_at "$V1156_SHAPES/zero")"
assert_eq "#1156 reader: a whitespace-only receipt is UNESTABLISHED receipt-blank-first-line" \
  "UNESTABLISHED receipt-blank-first-line|1|0" "$(v1156_check_at "$V1156_SHAPES/ws")"
assert_eq "#1156 reader: a lone-newline receipt is UNESTABLISHED receipt-blank-first-line" \
  "UNESTABLISHED receipt-blank-first-line|1|0" "$(v1156_check_at "$V1156_SHAPES/nl")"
assert_eq "#1156 reader: a directory at the receipt path is UNESTABLISHED receipt-path-is-a-directory" \
  "UNESTABLISHED receipt-path-is-a-directory|1|0" "$(v1156_check_at "$V1156_SHAPES/adir")"
assert_eq "#1156 reader: a receipt whose read is refused is UNESTABLISHED receipt-unreadable" \
  "UNESTABLISHED receipt-unreadable|1|0" "$(v1156_check_at "$V1156_SHAPES/noread")"
for V1156_NEAR in near-plural near-space near-case near-event near-escape near-marker near-indent near-tail inject meta; do
  assert_eq "#1156 reader: the near-miss shape '$V1156_NEAR' is UNESTABLISHED receipt-unrecognized-outcome, one line, exit 0" \
    "UNESTABLISHED receipt-unrecognized-outcome|1|0" "$(v1156_check_at "$V1156_SHAPES/$V1156_NEAR")"
done
# The five malformed shapes each report a DISTINCT reason — a single generic reason would
# satisfy every row above individually while telling a maintainer nothing.
assert_eq "#1156 reader: the malformed shapes report five distinct reasons, not one generic one" "5" \
  "$(for V1156_S in zero ws adir noread near-plural; do v1156_check_at "$V1156_SHAPES/$V1156_S"; printf '\n'; done | sort -u | grep -c .)"
# Unknown never collapses onto a value: no malformed shape may answer NOT-REACHED or REACHED.
assert_eq "#1156 reader: no malformed shape collapses onto NOT-REACHED or REACHED (unknown is not zero)" "0" \
  "$(for V1156_S in zero ws nl adir noread near-plural near-space near-case near-event near-escape near-marker near-indent near-tail inject meta; do
       v1156_check_at "$V1156_SHAPES/$V1156_S"; printf '\n'; done | grep -c -E '^(NOT-REACHED|REACHED )')"
# The reason vocabulary is closed and never quotes receipt bytes, so an injected workflow
# command in the receipt cannot reach the emitted line at all.
assert_eq "#1156 reader: an injected ::warning:: in the receipt reaches the emitted line as nothing" "0" \
  "$(v1156_check_at "$V1156_SHAPES/inject" | grep -c -E '::warning::|##\[')"

# Boundary: a valid token carrying trailing whitespace or a CR is still REACHED.
printf 'POSTED review APPROVE   \n' > "$V1156_SHAPES/trail"
printf 'SKIP head-not-sha\r\n' > "$V1156_SHAPES/crlf"
printf 'POSTED review APPROVE' > "$V1156_SHAPES/nonewline"
assert_eq "#1156 reader: a valid token with trailing whitespace is REACHED with the trimmed line" \
  "REACHED POSTED review APPROVE|1|0" "$(v1156_check_at "$V1156_SHAPES/trail")"
assert_eq "#1156 reader: a CRLF-terminated valid token is REACHED" \
  "REACHED SKIP head-not-sha|1|0" "$(v1156_check_at "$V1156_SHAPES/crlf")"
assert_eq "#1156 reader: a valid token with no terminating newline is REACHED, not a read failure" \
  "REACHED POSTED review APPROVE|1|0" "$(v1156_check_at "$V1156_SHAPES/nonewline")"

# ── ARM ORDER (reader). Two swaps, each with the shipped-order control beside it.
# Mutants live under <mutant-root>/scripts/ with a lib/ sibling symlinked at the real
# tree, because both helpers resolve their sourced dependencies relative to their OWN
# directory: a mutant dropped in a bare temp dir would fail that source and answer
# `UNESTABLISHED receipt-path-unresolved` for every input, making each control below
# pass for a reason that has nothing to do with the arm it mutated.
V1156_MUTR="$(mktemp -d)"
V1156_MUT="$V1156_MUTR/scripts"
mkdir -p "$V1156_MUT"
ln -s "$REPO_ROOT/lib" "$V1156_MUTR/lib"
# Anti-vacuity: an UNMUTATED copy at the mutant location must behave exactly like the
# shipped helper, or every mutant control below is measuring the relocation instead.
cp "$V1156_CHECK" "$V1156_MUT/relocated.sh"
assert_eq "#1156 mutant harness: an unmutated copy at the mutant location behaves like the shipped helper" \
  "NOT-REACHED-UNESTABLISHED receipt-empty" \
  "$(bash "$V1156_MUT/relocated.sh" "$V1156_NONE/nothing-here.txt" 2>/dev/null)-$(bash "$V1156_MUT/relocated.sh" "$V1156_SHAPES/zero" 2>/dev/null)"
v1156_swap_arms() {  # $1 out-file  $2 first `if` head  $3 second `if` head
  python3 - "$V1156_CHECK" "$1" "$2" "$3" <<'PY'
import sys
src, out, head_a, head_b = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = open(src, encoding="utf-8").read().splitlines()
def find(prefix):
    i = next(n for n, l in enumerate(lines) if l.startswith(prefix))
    assert lines[i + 3] == "fi", lines[i:i + 4]
    return i
a, b = find(head_a), find(head_b)
assert a < b, (a, b)
block_a, block_b = lines[a:a + 4], lines[b:b + 4]
lines[b:b + 4] = block_a
lines[a:a + 4] = block_b
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}
# (1) The decisive one. `[ ! -s ]` is TRUE for a file that does not exist, so an
# emptiness test ahead of the absence test answers UNESTABLISHED for every run that
# genuinely skipped Phase 4.4 — silencing the only arm that posts a comment.
v1156_swap_arms "$V1156_MUT/absent-after-empty.sh" 'if [ ! -e "$RECEIPT" ]; then' 'if [ ! -s "$RECEIPT" ]; then'
assert_eq "#1156 reader arm order: testing emptiness before absence misreports an absent receipt as UNESTABLISHED" \
  "UNESTABLISHED receipt-empty" "$(bash "$V1156_MUT/absent-after-empty.sh" "$V1156_NONE/nothing-here.txt" 2>/dev/null)"
assert_eq "#1156 reader arm order: the shipped order reports that same input as NOT-REACHED (the mutant's control)" \
  "NOT-REACHED" "$(bash "$V1156_CHECK" "$V1156_NONE/nothing-here.txt" 2>/dev/null)"
# (2) An unreadable zero-byte receipt matches BOTH the unreadable and the empty arm; the
# blocked read is the cause a maintainer can act on.
v1156_swap_arms "$V1156_MUT/empty-before-unreadable.sh" 'if [ ! -r "$RECEIPT" ]; then' 'if [ ! -s "$RECEIPT" ]; then'
assert_eq "#1156 reader arm order: testing emptiness before readability misdiagnoses a blocked read as an empty receipt" \
  "UNESTABLISHED receipt-empty" "$(bash "$V1156_MUT/empty-before-unreadable.sh" "$V1156_SHAPES/zero-noread" 2>/dev/null)"
assert_eq "#1156 reader arm order: the shipped order names the blocked read (the mutant's control)" \
  "UNESTABLISHED receipt-unreadable" "$(bash "$V1156_CHECK" "$V1156_SHAPES/zero-noread" 2>/dev/null)"
# NO SWAP CONTROL FOR THE DIRECTORY ARM, deliberately, and this is the reason rather
# than an oversight. Its only downstream neighbour whose answer a directory changes is
# the read block, and that block reads CVR_FIRST, which is initialized on a line ABOVE
# it that a block swap does not move — so every such mutant dies on `set -u` with empty
# output instead of answering a different arm. A row asserting "the mutant produced
# something other than receipt-path-is-a-directory" would then pass because the script
# ABORTED, which is a vacuous control, not a measured reordering. The directory arm's
# positive rows above still fail if the arm is deleted or its test inverted; only the
# ordering dimension is uncovered here, and it is uncovered on purpose.

# (3) Planted defect: deleting the blank-first-line arm falls a whitespace-only receipt
# through to the generic reason, so that specific arm is load-bearing rather than decorative.
python3 - "$V1156_CHECK" "$V1156_MUT/no-blank-arm.sh" <<'PY'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
i = next(n for n, l in enumerate(lines) if l.startswith('if [ -z "$CVR_LINE" ]; then'))
assert lines[i + 3] == "fi", lines[i:i + 4]
del lines[i:i + 4]
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
assert_eq "#1156 reader: deleting the blank-first-line arm degrades a whitespace-only receipt to the generic reason" \
  "UNESTABLISHED receipt-unrecognized-outcome" "$(bash "$V1156_MUT/no-blank-arm.sh" "$V1156_SHAPES/ws" 2>/dev/null)"

# ── The emitter's receipt write is itself load-bearing: remove it and a run that DID
# reach the emitter becomes indistinguishable from one that never did. That is the
# pre-#1156 tree, reproduced.
python3 - "$V1156_PRV" "$V1156_MUT/no-receipt.sh" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
needle = '  devflow_verdict_receipt_record "$_mode" "$1" && return 0\n'
assert needle in text, "the receipt write moved; update this planted-defect control"
open(sys.argv[2], "w", encoding="utf-8").write(text.replace(needle, "  return 0\n"))
PY
rm -f "$V1156_RCPT"
( cd "$V1156_ROOT" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq bash "$V1156_MUT/no-receipt.sh" 123 APPROVE body.md "$V1156_SHA" "" >/dev/null 2>&1 )
assert_eq "#1156 receipt: with the write removed, a reached emitter is indistinguishable from an unreached one" \
  "NOT-REACHED" "$(v1156_check)"
v1156_post 123 APPROVE body.md "$V1156_SHA" ""
assert_eq "#1156 receipt: the shipped emitter makes that same run REACHED (the mutant's control)" \
  "REACHED POSTED review APPROVE" "$(v1156_check)"

# ── DEGRADED SOURCING (a partially copied deployment). Both helpers resolve
# lib/verdict-receipt.sh relative to their own directory, so a copy without a lib/
# sibling exercises the guarded-source arm neither happy path reaches.
V1156_NOLIB="$(mktemp -d)"
mkdir -p "$V1156_NOLIB/scripts"
cp "$V1156_PRV" "$V1156_NOLIB/scripts/post-review-verdict.sh"
cp "$V1156_CHECK" "$V1156_NOLIB/scripts/check-verdict-post-reached.sh"
# The PRODUCER still posts. The receipt is a diagnostic; losing it must never cost a
# verdict, so the degraded arm keeps the outcome line, the exit code and the breadcrumb.
rm -f "$V1156_RCPT"
V1156_NOLIB_OUT="$( (cd "$V1156_ROOT" && env DEVFLOW_GH="$V1156_ROOT/gh" DEVFLOW_JQ=jq \
    bash "$V1156_NOLIB/scripts/post-review-verdict.sh" 123 APPROVE body.md "$V1156_SHA" "" 2>"$V1156_NOLIB/err") )"
V1156_NOLIB_RC=$?
assert_eq "#1156 degraded: an absent lib/ sibling still posts the verdict, with the outcome line and exit code intact" \
  "POSTED review APPROVE-0" "${V1156_NOLIB_OUT%%$'\n'*}-$V1156_NOLIB_RC"
assert_eq "#1156 degraded: the producer names the unusable receipt module and says the post is unaffected" \
  "yes" "$(v1156_has "$V1156_NOLIB/err" 'verdict-receipt.sh could not be sourced')"
assert_eq "#1156 degraded: with the receipt module gone the run writes no receipt at all" \
  "no-receipt" "$( [ -e "$V1156_RCPT" ] && printf 'receipt' || printf 'no-receipt')"
# The READER answers UNESTABLISHED receipt-path-unresolved — never NOT-REACHED. Nothing
# about the run was observed, so a broken deployment must not be reported as a skipped
# Phase 4.4 and must not post a comment.
assert_eq "#1156 degraded: a reader that cannot compose the receipt path is UNESTABLISHED receipt-path-unresolved, one line, exit 0" \
  "UNESTABLISHED receipt-path-unresolved|1|0" \
  "$(v1156_check_at_with "$V1156_NOLIB/scripts/check-verdict-post-reached.sh" "$V1156_NONE/nothing-here.txt")"
rm -rf "$V1156_NOLIB"

# ── issue #1250: the head-reviews classifier. It reads a reviews-API payload, the
# reviewed head SHA and the run's reviewer login, and prints exactly ONE line from
# `{ none | marked | unmarked <id>… | unestablished <reason> }`, always exiting 0. Every
# arm (a–j from the issue's acceptance table) is asserted against an EXACT expected line.
V1156_CLS="$REPO_ROOT/scripts/classify-head-reviews.sh"
V1156_CSHA=3333333333333333333333333333333333333333
V1156_COTHER=4444444444444444444444444444444444444444
V1156_CLOGIN='prflow-reviewer[bot]'
V1156_CLSD="$(mktemp -d)"
# One own-identity review on the head; $1 id, $2 body (JSON-escaped), emitted as a
# one-element array so the fixtures stay compact and legible.
v1156_cls_one() {  # $1 id $2 commit $3 login $4 body-json -> writes a payload file, echoes path
  local f; f="$V1156_CLSD/p$$-$RANDOM.json"
  printf '[{"id":%s,"commit_id":"%s","user":{"login":"%s"},"body":%s}]' "$1" "$2" "$3" "$4" > "$f"
  printf '%s' "$f"
}
v1156_cls() {  # $1 payload-file -> the classifier's single line for the head + reviewer login
  bash "$V1156_CLS" "$1" "$V1156_CSHA" "$V1156_CLOGIN" 2>/dev/null
}
V1156_MARKED_L1="\"<!-- prflow:review-verdict head=$V1156_CSHA verdict=REJECT -->\\n## Verdict: REJECT\""
V1156_MARKED_L2="\"first line\\n<!-- prflow:review-verdict head=$V1156_CSHA verdict=REJECT -->\""

# arm a — empty review list -> none
printf '[]' > "$V1156_CLSD/empty.json"
assert_eq "#1250 classify arm a: an empty review list is none" \
  "none" "$(v1156_cls "$V1156_CLSD/empty.json")"
# arm b — own-identity review on head, marker on line 1 -> marked
assert_eq "#1250 classify arm b: an own review on head with a line-1 marker is marked" \
  "marked" "$(v1156_cls "$(v1156_cls_one 42 "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_MARKED_L1")")"
# arm c — own-identity review on head, no marker -> unmarked <id>
assert_eq "#1250 classify arm c: an own review on head with no marker is unmarked <id>" \
  "unmarked 4849248513" "$(v1156_cls "$(v1156_cls_one 4849248513 "$V1156_CSHA" "$V1156_CLOGIN" '"## Verdict: REJECT\nfindings"')")"
# arm d — own-identity review on head, marker on LINE 2 -> unmarked (readers scan line 1)
assert_eq "#1250 classify arm d: a marker on line 2 is unmarked, not marked (line-1 only)" \
  "unmarked 7" "$(v1156_cls "$(v1156_cls_one 7 "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_MARKED_L2")")"
# arm e — unmarked review by a login that is NOT the run's reviewer -> none
assert_eq "#1250 classify arm e: an unmarked review by another login is none" \
  "none" "$(v1156_cls "$(v1156_cls_one 9 "$V1156_CSHA" "someone-else" '"no marker"')")"
# arm f — own MARKERLESS review whose commit_id is NOT the head. `commit_id` is the only
# key such a review carries and issue #1247 ruled it non-authoritative (GitHub rewrites it
# after submission), so this review cannot be positively placed OFF the head — and `none`
# is the one arm the renderer turns into "left the reviews API untouched". It is therefore
# UNESTABLISHED, never `none`: a run that posted an unmarked bypass review and then saw the
# head advance before this classification leaves exactly this shape behind.
assert_eq "#1250 classify arm f: an own unmarked review this helper cannot place off the head is unestablished, never none" \
  "unestablished review-placement-unprovable" "$(v1156_cls "$(v1156_cls_one 9 "$V1156_COTHER" "$V1156_CLOGIN" '"no marker"')")"
# The same shape with NO usable commit_id at all — JSON null, the key absent, or a
# non-string the API does not produce — is the same answer, and none of the three may abort
# the filter: an absent comparand never reads as "off the head".
printf '[{"id":9,"commit_id":null,"user":{"login":"%s"},"body":"no marker"}]' "$V1156_CLOGIN" > "$V1156_CLSD/cid-null.json"
printf '[{"id":9,"user":{"login":"%s"},"body":"no marker"}]' "$V1156_CLOGIN" > "$V1156_CLSD/cid-absent.json"
printf '[{"id":9,"commit_id":17,"user":{"login":"%s"},"body":"no marker"}]' "$V1156_CLOGIN" > "$V1156_CLSD/cid-number.json"
assert_eq "#1250 classify arm f: a markerless own review with no usable commit_id (null/absent/non-string) is unestablished, never none" \
  "unestablished review-placement-unprovable|unestablished review-placement-unprovable|unestablished review-placement-unprovable" \
  "$(v1156_cls "$V1156_CLSD/cid-null.json")|$(v1156_cls "$V1156_CLSD/cid-absent.json")|$(v1156_cls "$V1156_CLSD/cid-number.json")"
# arm g — unparseable payload -> unestablished <reason>
printf 'not json{' > "$V1156_CLSD/bad.json"
assert_eq "#1250 classify arm g: an unparseable payload is unestablished payload-unparseable" \
  "unestablished payload-unparseable" "$(v1156_cls "$V1156_CLSD/bad.json")"
# arm h — absent/empty head SHA -> unestablished (never none)
assert_eq "#1250 classify arm h: an absent head SHA is unestablished head-sha-absent" \
  "unestablished head-sha-absent" "$(bash "$V1156_CLS" "$V1156_CLSD/empty.json" "" "$V1156_CLOGIN" 2>/dev/null)"
# arm i — body field is not a string -> unestablished or none, NEVER a crash, NEVER marked
V1156_CI="$(v1156_cls "$(v1156_cls_one 9 "$V1156_CSHA" "$V1156_CLOGIN" '123')")"
assert_eq "#1250 classify arm i: a non-string body is unestablished/none, never marked, never a crash" \
  "yes" "$(case "$V1156_CI" in 'unestablished '*|none) echo yes;; *) echo no;; esac)"
assert_eq "#1250 classify arm i: a non-string body specifically reports body-not-a-string" \
  "unestablished body-not-a-string" "$V1156_CI"
# The body-type guard covers EVERY own-identity review, not only the ones already known to
# be on the head: since #1247 the body is what PLACES a review (its line-1 marker), so a
# non-string body anywhere in the own set leaves the placement unreadable and must not be
# passed over as "not on the head, so it does not matter".
assert_eq "#1250 classify arm i: a non-string body on an OFF-head own review is still body-not-a-string" \
  "unestablished body-not-a-string" "$(v1156_cls "$(v1156_cls_one 9 "$V1156_COTHER" "$V1156_CLOGIN" '123')")"
# arm j — two unmarked own reviews -> both ids on the one line (sorted ascending)
printf '[{"id":20,"commit_id":"%s","user":{"login":"%s"},"body":"a"},{"id":10,"commit_id":"%s","user":{"login":"%s"},"body":"b"}]' \
  "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_CSHA" "$V1156_CLOGIN" > "$V1156_CLSD/two.json"
assert_eq "#1250 classify arm j: two unmarked own reviews put both ids on the one line, sorted" \
  "unmarked 10 20" "$(v1156_cls "$V1156_CLSD/two.json")"
# Positive control for the line-1 test: a body whose ONLY difference from arm b is the
# marker moving to line 2 flips marked -> unmarked, so arm b is not passing vacuously.
assert_eq "#1250 classify: the line-1 marker test is load-bearing (b marked, d unmarked over the same marker)" \
  "marked/unmarked 7" \
  "$(v1156_cls "$(v1156_cls_one 42 "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_MARKED_L1")")/$(v1156_cls "$(v1156_cls_one 7 "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_MARKED_L2")")"
# Every arm exits 0 (the reach-record step must never change its job's result).
assert_eq "#1250 classify: every arm exits 0" "0000" \
  "$(bash "$V1156_CLS" "$V1156_CLSD/empty.json" "$V1156_CSHA" "$V1156_CLOGIN" >/dev/null 2>&1; printf '%s' "$?"
     bash "$V1156_CLS" "$V1156_CLSD/bad.json" "$V1156_CSHA" "$V1156_CLOGIN" >/dev/null 2>&1; printf '%s' "$?"
     bash "$V1156_CLS" "" "$V1156_CSHA" "$V1156_CLOGIN" >/dev/null 2>&1; printf '%s' "$?"
     bash "$V1156_CLS" "$V1156_CLSD/nope.json" "$V1156_CSHA" "$V1156_CLOGIN" >/dev/null 2>&1; printf '%s' "$?")"
# A missing reviewer login is unestablished, never none (unknown is not zero).
assert_eq "#1250 classify: an absent reviewer login is unestablished, never none" \
  "unestablished reviewer-login-absent" "$(bash "$V1156_CLS" "$V1156_CLSD/empty.json" "$V1156_CSHA" "" 2>/dev/null)"
# The unmarked id list is digits only by construction, so no review-body byte reaches the
# emitted line: a crafted body cannot inject through the id field.
printf '[{"id":55,"commit_id":"%s","user":{"login":"%s"},"body":"$(id) `whoami` ::warning::x"}]' \
  "$V1156_CSHA" "$V1156_CLOGIN" > "$V1156_CLSD/inject.json"
assert_eq "#1250 classify: a review body cannot inject into the emitted line (id field is digits only)" \
  "unmarked 55" "$(v1156_cls "$V1156_CLSD/inject.json")"
# The payload-shape reason tokens the arms above have not already reached are asserted here
# against their exact line — every reason renders verbatim into a ::warning:: and a PR
# comment, so a reason a regression reclassified would ship green if only its sibling
# reasons were pinned. Deliberately count-free: the closed vocabulary grows (issue #1250
# added `review-placement-unprovable`, asserted with arm f above), and a comment carrying
# the tally would rot on the very edit that extends it.
printf '{"not":"an array"}' > "$V1156_CLSD/obj.json"
assert_eq "#1250 classify: a valid-JSON non-array payload is unestablished payload-not-an-array" \
  "unestablished payload-not-an-array" "$(v1156_cls "$V1156_CLSD/obj.json")"
assert_eq "#1250 classify: an unreadable payload path is unestablished payload-unreadable" \
  "unestablished payload-unreadable" "$(v1156_cls "$V1156_CLSD/does-not-exist.json")"
mkdir -p "$V1156_CLSD/adir.json"
assert_eq "#1250 classify: a directory at the payload path is unestablished payload-unreadable" \
  "unestablished payload-unreadable" "$(v1156_cls "$V1156_CLSD/adir.json")"
# The 'any unmarked wins -> unmarked' precedence within $own is the operative behavior for
# the live bypass (a run that stamped a marked review AND left an unmarked one). A change
# that emitted `marked` whenever any marked review existed would pass arm b and arm j.
printf '[{"id":30,"commit_id":"%s","user":{"login":"%s"},"body":"<!-- prflow:review-verdict head=%s verdict=APPROVE -->\\nmarked one"},{"id":31,"commit_id":"%s","user":{"login":"%s"},"body":"no marker"}]' \
  "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_CSHA" "$V1156_CSHA" "$V1156_CLOGIN" > "$V1156_CLSD/mixed.json"
assert_eq "#1250 classify: a mixed own set (one marked + one unmarked) names ONLY the unmarked id" \
  "unmarked 31" "$(v1156_cls "$V1156_CLSD/mixed.json")"
# The APPROVE marker alternation (not only REJECT) is a real branch of the regex.
assert_eq "#1250 classify: an APPROVE-verdict line-1 marker is marked, exercising the regex alternation" \
  "marked" "$(v1156_cls "$(v1156_cls_one 33 "$V1156_CSHA" "$V1156_CLOGIN" "\"<!-- prflow:review-verdict head=$V1156_CSHA verdict=APPROVE -->\\napproved\"")")"
# The stdin ('-') payload source is a distinct jq invocation; drive it once end to end.
assert_eq "#1250 classify: the stdin ('-') payload source classifies identically to a file" \
  "none" "$(printf '[]' | bash "$V1156_CLS" - "$V1156_CSHA" "$V1156_CLOGIN" 2>/dev/null)"
# ── issue #1247 precedence, the same one PR #1255 gave dismiss-stale-rejections.sh: the
# verdict marker's `head=` is the AUTHORITATIVE record of the reviewed tree and the
# reviews-API `commit_id` is not (GitHub rewrites it after submission — observed on pull
# request #1234). So the marker decides placement whenever a review carries one, in BOTH
# directions, and `commit_id` is consulted only for a markerless review.
#
# Direction 1 — the marker places a review ON the head that `commit_id` has moved off.
# This is the shape the finding names: before the precedence the review vanished from the
# scoped set and the empty set graded `none`, so the renderer asserted the reviews API was
# untouched about a head it had a recorded verdict for.
assert_eq "#1250 classify #1247: a marked review whose commit_id no longer names the head is placed by its MARKER, not by commit_id" \
  "marked" "$(v1156_cls "$(v1156_cls_one 45 "$V1156_COTHER" "$V1156_CLOGIN" "\"<!-- prflow:review-verdict head=$V1156_CSHA verdict=APPROVE -->\\nok\"")")"
# Direction 2 — the marker places a review OFF the head that `commit_id` claims is on it.
# A review whose line-1 marker names another tree reviewed that tree, so it is positively
# off this head and `none` stays reachable: this is what keeps the marker-first precedence
# from collapsing `none` into a state nothing can reach.
assert_eq "#1250 classify #1247: a marker naming a DIFFERENT head places the review OFF this head, so none stays reachable" \
  "none" "$(v1156_cls "$(v1156_cls_one 44 "$V1156_CSHA" "$V1156_CLOGIN" "\"<!-- prflow:review-verdict head=$V1156_COTHER verdict=REJECT -->\\nbody\"")")"
# The marker head is compared case-insensitively, so a hand-authored uppercase marker head
# still places its review — normalized in jq, never through a non-preflight `tr` or a
# bash-4 `${var,,}`. The head ARGUMENT is normalized the same way, from either side.
assert_eq "#1250 classify #1247: marker-head placement is case-insensitive from both sides" \
  "marked" "$(bash "$V1156_CLS" "$(v1156_cls_one 46 "$V1156_CSHA" "$V1156_CLOGIN" "\"<!-- prflow:review-verdict head=ABCDEF3333333333333333333333333333333333 verdict=REJECT -->\\nx\"")" \
     abcdef3333333333333333333333333333333333 "$V1156_CLOGIN" 2>/dev/null)"
# PRECEDENCE. An unplaceable review blocks ONLY `none` — the one arm the renderer turns
# into "left the reviews API untouched". It never displaces `unmarked` or `marked`, which
# assert that something EXISTS and so cannot be falsified by a review that could not be
# placed. Both rows share the same unplaceable second review, so a change that hoisted the
# indeterminate arm would flip them while arm f stayed green.
printf '[{"id":60,"commit_id":"%s","user":{"login":"%s"},"body":"<!-- prflow:review-verdict head=%s verdict=APPROVE -->\\nm"},{"id":61,"commit_id":"%s","user":{"login":"%s"},"body":"no marker"}]' \
  "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_CSHA" "$V1156_COTHER" "$V1156_CLOGIN" > "$V1156_CLSD/marked-plus-unplaceable.json"
printf '[{"id":62,"commit_id":"%s","user":{"login":"%s"},"body":"no marker"},{"id":61,"commit_id":"%s","user":{"login":"%s"},"body":"no marker"}]' \
  "$V1156_CSHA" "$V1156_CLOGIN" "$V1156_COTHER" "$V1156_CLOGIN" > "$V1156_CLSD/unmarked-plus-unplaceable.json"
assert_eq "#1250 classify: an unplaceable review blocks none but never displaces marked or unmarked" \
  "marked|unmarked 62" \
  "$(v1156_cls "$V1156_CLSD/marked-plus-unplaceable.json")|$(v1156_cls "$V1156_CLSD/unmarked-plus-unplaceable.json")"
rm -rf "$V1156_CLSD"

# ── AC6-AC10: the arm-dispatch helper. It selects the arm and composes every byte the
# arm emits; the workflow renders those bytes and chooses nothing.
V1156_GAPD="$(mktemp -d)"
V1156_WARN="$V1156_GAPD/warn.txt"
V1156_BODY="$V1156_GAPD/body.md"
v1156_gap() {  # $1 reader line, $2 run id, $3 pr, $4 head, [$5 review class] -> "<ARM line>|<exit code>"
  local out rc
  out="$(bash "$V1156_GAP" "$1" "$2" "$3" "$4" "$V1156_WARN" "$V1156_BODY" "${5:-}" 2>/dev/null)"; rc=$?
  printf '%s|%s' "$out" "$rc"
}
V1156_GRUN=30759180188
V1156_GSHA=575c0412ad25fe0d5a4070a042fbfee979cbdafd

# REACHED: silent on both channels.
assert_eq "#1156 gap: a REACHED line selects the reached arm and exits 0" \
  "ARM reached|0" "$(v1156_gap "REACHED POSTED review APPROVE" "$V1156_GRUN" 1150 "$V1156_GSHA")"
assert_eq "#1156 gap: the reached arm writes no warning and no comment body" \
  "0-0" "$(v1156_present "$V1156_WARN")-$(v1156_present "$V1156_BODY")"
# The sinks are truncated on EVERY arm, so a stale file from a previous step cannot be
# read by the caller's `[ -s ]` test as this run's answer.
printf 'stale warning from an earlier step\n' > "$V1156_WARN"
printf 'stale body from an earlier step\n' > "$V1156_BODY"
V1156_STALE="$(v1156_gap "REACHED SKIP not-numeric" "$V1156_GRUN" 1150 "$V1156_GSHA")"
assert_eq "#1156 gap: the reached arm truncates a stale warning and a stale body left by an earlier step" \
  "ARM reached|0-0-0" "$V1156_STALE-$(v1156_present "$V1156_WARN")-$(v1156_present "$V1156_BODY")"

# NOT-REACHED, DEFAULT REVIEW_CLASS (empty — an older deployment, or a step that did not
# classify). One warning naming the run id and the pull-request number, and one comment
# that asserts NOTHING about the reviews API either way (issue #1250 AC5, applied to the
# not-classified case). The shared skeleton — header, both causes, the closing paragraph,
# the run-keyed marker — is asserted here and is identical on every class.
assert_eq "#1156 gap: a NOT-REACHED line selects the not-reached arm and exits 0" \
  "ARM not-reached|0" "$(v1156_gap "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA")"
assert_eq "#1156 gap: the not-reached warning is exactly one line" "1" "$(grep -c . "$V1156_WARN")"
V1156_A="$(v1156_has "$V1156_WARN" "$V1156_GRUN")"
V1156_B="$(v1156_has "$V1156_WARN" '#1150')"
assert_eq "#1156 gap: the not-reached warning names the run id and the pull-request number" \
  "yes-yes" "$V1156_A-$V1156_B"
V1156_A="$(v1156_has "$V1156_WARN" 'no run-scoped verdict-post receipt was found')"
V1156_B="$(v1156_has "$V1156_WARN" 'or it ran and could not write its receipt')"
assert_eq "#1156 gap: the not-reached WARNING states the observation and both causes, like the comment" \
  "yes-yes" "$V1156_A-$V1156_B"
assert_eq "#1156 gap: the not-reached comment body states the Actions run id" \
  "yes" "$(v1156_has "$V1156_BODY" "$V1156_GRUN")"
assert_eq "#1156 gap: the not-reached comment body states the resolved head SHA" \
  "yes" "$(v1156_has "$V1156_BODY" "$V1156_GSHA")"
assert_eq "#1156 gap: the not-reached comment body states the OBSERVATION (no receipt was found)" \
  "yes" "$(v1156_has "$V1156_BODY" 'No run-scoped verdict-post receipt was found for this run')"
V1156_A="$(v1156_has "$V1156_BODY" 'either Phase 4.4'"'"'s')"
V1156_B="$(v1156_has "$V1156_BODY" 'or it ran and could not write its receipt')"
assert_eq "#1156 gap: the not-reached comment body names BOTH causes of an absent receipt" \
  "yes-yes" "$V1156_A-$V1156_B"
assert_eq "#1156 gap: the not-reached comment body never asserts categorically that the emitter did not run in this run" \
  "no" "$(v1156_has "$V1156_BODY" 'verdict emitter did not run in this run')"
# AC5 (not-classified): with no REVIEW_CLASS the body asserts NEITHER that the API is
# untouched NOR that a review exists — unknown is not zero, two levels down.
V1156_A="$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"
V1156_B="$(v1156_has "$V1156_BODY" 'this comment asserts nothing about the reviews API')"
assert_eq "#1156 gap: an unclassified not-reached body asserts neither 'untouched' nor a review-exists claim" \
  "no-yes" "$V1156_A-$V1156_B"
V1156_A="$(v1156_has "$V1156_BODY" 'carries no producer-emitted verdict marker')"
V1156_B="$(v1156_has "$V1156_BODY" 'do not read it as a verdict')"
assert_eq "#1156 gap: the not-reached comment body states that verdict text published OUTSIDE the emitter carries no producer marker" \
  "yes-yes" "$V1156_A-$V1156_B"
# The scope word is load-bearing: the emitter's OWN posts do carry the marker, so an
# unscoped "published elsewhere" would be false about the reached case.
assert_eq "#1156 gap: that claim is scoped to text published outside the emitter" \
  "yes" "$(v1156_has "$V1156_BODY" 'published OUTSIDE the emitter')"
assert_eq "#1156 gap: the not-reached comment body carries NO producer verdict marker of its own" \
  "no" "$(v1156_has "$V1156_BODY" 'prflow:review-verdict')"
V1156_BODY_L1="$( { IFS= read -r V1156_L || true; printf '%s' "$V1156_L"; } < "$V1156_BODY")"
assert_eq "#1156 gap: the not-reached comment body opens with its own run-keyed marker" \
  "<!-- prflow:verdict-post-gap run=$V1156_GRUN -->" "$V1156_BODY_L1"

# The remedy the public comment hands a maintainer must match what the job log actually
# contains. $V1156_BLOCK/err is the REAL stderr of a real emitter run whose receipt write
# was blocked, so this compares the comment's instruction against observed bytes rather
# than against a second copy of the same string.
V1156_A="$(v1156_has "$V1156_BODY" 'could not write the verdict-post receipt')"
V1156_B="$(v1156_has "$V1156_BLOCK/err" 'could not write the verdict-post receipt')"
assert_eq "#1156 gap: the body's discriminating breadcrumb is the literal the emitter really writes to stderr" \
  "yes-yes" "$V1156_A-$V1156_B"

# ── issue #1250: the REVIEW_CLASS arm of the not-reached body. The reach-record step
# passes scripts/classify-head-reviews.sh's reading of the reviews recorded on the head,
# so the body stops asserting the reviews API was untouched when it was NOT — the live
# failure the issue records (run 30860699039 / review 4849248513).
#
# UNMARKED (AC4): the false claims are GONE, and the offending review is named. The body
# neither says "left the reviews API and reviewDecision untouched" NOR names a plain
# pull-request comment as the only out-of-band channel; it names the review id and states
# a review exists for the head that the verdict consumers do not read as a verdict.
V1156_UM="$(v1156_gap "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "unmarked 4849248513")"
assert_eq "#1156 gap #1250: the unmarked class still selects the not-reached arm, exit 0" \
  "ARM not-reached|0" "$V1156_UM"
assert_eq "#1156 gap #1250: the unmarked body does NOT claim the reviews API was left untouched" \
  "no" "$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"
assert_eq "#1156 gap #1250: the unmarked body names no plain pull-request comment as the out-of-band channel" \
  "no" "$(v1156_has "$V1156_BODY" 'plain pull-request comment')"
assert_eq "#1156 gap #1250: the unmarked body names the offending review id" \
  "yes" "$(v1156_has "$V1156_BODY" 'review 4849248513 is recorded there')"
assert_eq "#1156 gap #1250: the unmarked body states the review exists but is not read as a verdict" \
  "yes" "$(v1156_has "$V1156_BODY" 'do not read an unmarked review as a verdict')"
# AC6: the unmarked arm ALSO adds a ::warning:: naming the review id.
assert_eq "#1156 gap #1250: the unmarked warning names the offending review id" \
  "yes" "$(v1156_has "$V1156_WARN" 'review 4849248513')"
assert_eq "#1156 gap #1250: the unmarked warning is exactly one line (AC6 stays a record, not a gate)" \
  "1" "$(grep -c . "$V1156_WARN")"
# The review id on the unmarked body is validated as digits: an id-position injection is
# reduced to `unavailable`-style dropping, degrading to the unestablished body rather than
# reaching the comment.
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 'unmarked $(id) `whoami`' >/dev/null 2>&1
assert_eq "#1156 gap #1250: a non-digit id on the unmarked line reaches neither warning nor body" "0" \
  "$(cat "$V1156_BODY" "$V1156_WARN" | grep -c -E '\$\(id\)|`whoami`')"
assert_eq "#1156 gap #1250: an unmarked line with no valid id degrades to the unestablished body" \
  "yes" "$(v1156_has "$V1156_BODY" 'this comment asserts nothing about the reviews API')"

# NONE: the run's reviewer identity left no review on the head, so the API WAS untouched —
# and that is the only class on which the body may say so, because it is the only one on
# which it was measured.
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 'none' >/dev/null 2>&1
assert_eq "#1156 gap #1250: the none class asserts the reviews API and reviewDecision were left untouched" \
  "yes" "$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"
assert_eq "#1156 gap #1250: the none warning names no review id (there is none), one line" \
  "1" "$(grep -c . "$V1156_WARN")"

# MARKED: a marked review is recorded on the head (the receipt write failed), so the
# verdict IS recorded — the body must not claim the API was untouched.
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 'marked' >/dev/null 2>&1
assert_eq "#1156 gap #1250: the marked class states a marked review was recorded" \
  "yes" "$(v1156_has "$V1156_BODY" 'recorded a MARKED review in the reviews API')"
assert_eq "#1156 gap #1250: the marked class does NOT claim the reviews API was left untouched" \
  "no" "$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"

# UNESTABLISHED (AC5): the classification could not be settled, so the body asserts
# NEITHER 'untouched' NOR that a review exists, and carries the closed reason token.
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 'unestablished body-not-a-string' >/dev/null 2>&1
V1156_A="$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"
V1156_B="$(v1156_has "$V1156_BODY" 'is recorded there')"
assert_eq "#1156 gap #1250: the unestablished class asserts neither 'untouched' nor a review-exists claim" \
  "no-no" "$V1156_A-$V1156_B"
assert_eq "#1156 gap #1250: the unestablished class carries its closed reason token" \
  "yes" "$(v1156_has "$V1156_BODY" 'be established (body-not-a-string)')"
# The classifier's #1247 placement reason travels the SAME path end to end: the token the
# classifier really emits for an unplaceable review is fed to the renderer, which must
# accept it as a closed token (assert nothing either way, carry the reason) rather than
# drop it as unrecognized. This is the coupled contract between the two helpers'
# vocabularies — a new reason token the renderer's validator rejected would degrade to the
# unreasoned paragraph while both helpers' own tests stayed green.
V1156_UNPL="$(mktemp -d)"
printf '[{"id":9,"commit_id":"4444444444444444444444444444444444444444","user":{"login":"r[bot]"},"body":"no marker"}]' > "$V1156_UNPL/p.json"
V1156_A="$(bash "$V1156_CLS" "$V1156_UNPL/p.json" 3333333333333333333333333333333333333333 'r[bot]' 2>/dev/null)"
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" "$V1156_A" >/dev/null 2>&1
V1156_B="$(v1156_has "$V1156_BODY" 'be established (review-placement-unprovable)')"
assert_eq "#1250 end to end: an unplaceable own review reaches the renderer as a closed reason and asserts nothing about the API" \
  "unestablished review-placement-unprovable-yes-no" \
  "$V1156_A-$V1156_B-$(v1156_has "$V1156_BODY" 'left the reviews API and `reviewDecision` untouched')"
rm -rf "$V1156_UNPL"
# A reason outside the closed lowercase-token shape is dropped, never quoted into the body.
bash "$V1156_GAP" "NOT-REACHED" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 'unestablished $(id)' >/dev/null 2>&1
assert_eq "#1156 gap #1250: an unsafe unestablished reason is never quoted into the body" "0" \
  "$(grep -c -E '\$\(id\)' "$V1156_BODY")"

# UNESTABLISHED: warns carrying the reason VERBATIM, and posts NOTHING — the not-reached
# claim is exactly what was not established.
assert_eq "#1156 gap: an UNESTABLISHED line selects the unestablished arm and exits 0" \
  "ARM unestablished|0" "$(v1156_gap "UNESTABLISHED receipt-unreadable" "$V1156_GRUN" 1150 "$V1156_GSHA")"
assert_eq "#1156 gap: the unestablished arm carries the reader's reason verbatim" \
  "yes" "$(v1156_has "$V1156_WARN" 'receipt-unreadable')"
assert_eq "#1156 gap: the unestablished arm posts no comment (it asserts neither outcome)" \
  "0" "$(v1156_present "$V1156_BODY")"
assert_eq "#1156 gap: the unestablished arm never claims the emitter did not run" \
  "no" "$(v1156_has "$V1156_WARN" 'did not run')"

# Silence and gibberish from the reader are kept apart: both warn without asserting, but
# they have different remedies and the job log is the only place that survives.
assert_eq "#1156 gap: an empty reader line selects the no-line arm (a reader refused before it ran)" \
  "ARM no-line|0" "$(v1156_gap "" "$V1156_GRUN" 1150 "$V1156_GSHA")"
V1156_A="$(grep -c . "$V1156_WARN")"
V1156_B="$(v1156_has "$V1156_WARN" 'produced no output')"
assert_eq "#1156 gap: the no-line arm warns, names the refusal, and posts nothing" \
  "1-yes-0" "$V1156_A-$V1156_B-$(v1156_present "$V1156_BODY")"
assert_eq "#1156 gap: an unrecognized reader line selects the unrecognized-line arm and posts nothing" \
  "ARM unrecognized-line|0-0" "$(v1156_gap "MAYBE probably fine" "$V1156_GRUN" 1150 "$V1156_GSHA")-$(v1156_present "$V1156_BODY")"
bash "$V1156_GAP" "" 1 2 "$V1156_GSHA" "$V1156_GAPD/w1.txt" "" >/dev/null 2>&1
bash "$V1156_GAP" "MAYBE" 1 2 "$V1156_GSHA" "$V1156_GAPD/w2.txt" "" >/dev/null 2>&1
assert_eq "#1156 gap: the two warn-only arms are diagnosed differently, never folded together" \
  "no" "$(cmp -s "$V1156_GAPD/w1.txt" "$V1156_GAPD/w2.txt" && echo yes || echo no)"
assert_eq "#1156 gap: every arm exits 0, so the step can never change its job's result" "00000" \
  "$(for V1156_L in 'REACHED SKIP not-numeric' 'NOT-REACHED' 'UNESTABLISHED receipt-empty' '' 'garbage'; do
       bash "$V1156_GAP" "$V1156_L" 1 2 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" >/dev/null 2>&1; printf '%s' "$?";
     done)"

# Every emitted field is VALIDATED, not quoted: a value the helper does not recognize is
# rendered as the literal `unavailable` and never reaches a warning or a comment.
bash "$V1156_GAP" "NOT-REACHED" '$(id)' '`whoami`' 'not-a-sha' "$V1156_WARN" "$V1156_BODY" >/dev/null 2>&1
assert_eq "#1156 gap: no unvalidated field byte reaches the comment body or the warning" "0" \
  "$(cat "$V1156_BODY" "$V1156_WARN" | grep -c -E '\$\(id\)|`whoami`|not-a-sha')"
assert_eq "#1156 gap: a head SHA that did not resolve is reported as 'unavailable', never as a blank" \
  "yes" "$(v1156_has "$V1156_BODY" 'head SHA this step resolved: `unavailable`')"
V1156_A="$(v1156_has "$V1156_WARN" 'Actions run unavailable')"
V1156_B="$(v1156_has "$V1156_WARN" '#unavailable')"
assert_eq "#1156 gap: an unrecognized run id and pull-request number are reported as 'unavailable' in the warning" \
  "yes-yes" "$V1156_A-$V1156_B"
# A reader reason is a closed token by construction, so nothing receipt-derived can carry a
# workflow command onto the emitted surfaces.
bash "$V1156_GAP" 'UNESTABLISHED receipt-unrecognized-outcome' "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" >/dev/null 2>&1
assert_eq "#1156 gap: the unestablished warning carries no workflow-command sequence" "0" \
  "$(grep -c -E '::warning::|::error::|##\[' "$V1156_WARN")"

# ── ARM ORDER (gap helper). The catch-all swallows every input it is hoisted above.
v1156_hoist_catchall() {  # $1 out-file  $2 = the arm head it is hoisted directly above
  python3 - "$V1156_GAP" "$1" "$2" <<'PY'
import sys
src, out, above = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(src, encoding="utf-8").read().splitlines()
start = next(n for n, l in enumerate(lines) if l == "  *)")
end = next(n for n in range(start, len(lines)) if lines[n] == "    ;;")
block = lines[start:end + 1]
del lines[start:end + 1]
target = lines.index(above)
lines[target:target] = block
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}
v1156_hoist_catchall "$V1156_MUT/catchall-first.sh" "  'REACHED '*)"
assert_eq "#1156 gap arm order: hoisting the catch-all to the top reports a reached emitter as unrecognized" \
  "ARM unrecognized-line" "$(bash "$V1156_MUT/catchall-first.sh" 'REACHED POSTED review APPROVE' 1 2 "$V1156_GSHA" 2>/dev/null)"
assert_eq "#1156 gap arm order: the shipped order reports that same input as reached (the mutant's control)" \
  "ARM reached" "$(bash "$V1156_GAP" 'REACHED POSTED review APPROVE' 1 2 "$V1156_GSHA" 2>/dev/null)"
v1156_hoist_catchall "$V1156_MUT/catchall-before-empty.sh" "  '')"
assert_eq "#1156 gap arm order: hoisting the catch-all above the empty arm misreports a refused reader as gibberish" \
  "ARM unrecognized-line" "$(bash "$V1156_MUT/catchall-before-empty.sh" '' 1 2 "$V1156_GSHA" 2>/dev/null)"
assert_eq "#1156 gap arm order: the shipped order reports that same input as no-line (the mutant's control)" \
  "ARM no-line" "$(bash "$V1156_GAP" '' 1 2 "$V1156_GSHA" 2>/dev/null)"

# ── End to end over the two states the whole issue exists to separate: a run whose
# emitter was never reached, and a run whose emitter ran and was REFUSED. Before this
# change both presented identically after the fact.
rm -f "$V1156_RCPT"
V1156_E2E="$(v1156_check)"
assert_eq "#1156 end to end: an unreached emitter yields NOT-REACHED and a posted comment" \
  "NOT-REACHED-ARM not-reached-1" \
  "$V1156_E2E-$(bash "$V1156_GAP" "$V1156_E2E" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 2>/dev/null)-$(v1156_present "$V1156_BODY")"
v1156_post 123 APPROVE body.md "$V1156_SHA" "" V1156_REVIEW_RC=1 V1156_COMMENT_RC=1
V1156_E2E="$(v1156_check)"
assert_eq "#1156 end to end: an emitter that ran and was refused yields REACHED and NO comment" \
  "yes-ARM reached-0" \
  "$(case "$V1156_E2E" in 'REACHED FAILED no-durable-channel '*) echo yes;; *) echo no;; esac)-$(bash "$V1156_GAP" "$V1156_E2E" "$V1156_GRUN" 1150 "$V1156_GSHA" "$V1156_WARN" "$V1156_BODY" 2>/dev/null)-$(v1156_present "$V1156_BODY")"

# ── AC6/AC11/AC12: the workflow step, read out of the parsed YAML rather than grepped.
v1156_step() {  # $1 = python expression over `step` / `steps` / `gate`
  python3 - "$V1156_WF" "$1" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
steps = doc["jobs"]["command"]["steps"]
named = [s for s in steps if s.get("name") == "Record whether the verdict emitter was reached"]
if len(named) != 1:
    print(f"expected exactly one reach-record step, found {len(named)}")
    raise SystemExit(0)
step = named[0]
gate = [s for s in steps if s.get("name") == "Review stall backstop"][0]
print(eval(sys.argv[2], {"step": step, "steps": steps, "gate": gate}))
PY
}
assert_eq "#1156 workflow: the command job carries exactly one verdict-post reach step" \
  "1" "$(v1156_step 'len([s for s in steps if s.get("name") == "Record whether the verdict emitter was reached"])')"
assert_eq "#1156 workflow: the step runs under always(), so a clean-exit run still reaches it" \
  "True" "$(v1156_step '"always()" in step["if"]')"
# The command prefix is the SAME literal the stall backstop uses — trailing space included,
# which is what excludes the fix-loop command that skips Phase 4.4 by design. Compared
# against the sibling step rather than transcribed, so the two cannot drift apart.
assert_eq "#1156 workflow: the step's command gate is byte-identical to the stall backstop's prefix test" \
  "True" "$(v1156_step 'any(t in step["if"] and t in gate["if"] for t in ["startsWith(needs.gate.outputs.command, \x27/prflow:review \x27)"])')"
assert_eq "#1156 workflow: the gate keeps the trailing space that excludes the fix-loop command" \
  "True" "$(v1156_step '"/prflow:review-and-fix" not in step["if"] and "/prflow:review \x27)" in step["if"]')"
assert_eq "#1156 workflow: the step is additionally gated on a number being resolvable from the event" \
  "True" "$(v1156_step '"github.event.issue.number" in step["if"] and "github.event.pull_request.number" in step["if"]')"
# `gate` accepts any numeric target, so /prflow:review on a plain ISSUE reaches this job.
# Phase 4.4 is PR-mode-only, so the reader would answer NOT-REACHED there and the step
# would post a verdict-record comment on an issue that never had a verdict to record.
# github.event.issue.pull_request is GitHub's own discriminator for a commented issue.
assert_eq "#1156 workflow: the step is gated on the target being a pull request, so a review command on a plain issue draws no comment" \
  "True" "$(v1156_step '"github.event.issue.pull_request" in step["if"]')"
assert_eq "#1156 workflow: the step invokes the reader and the arm-dispatch helper, both at the vendored path" \
  "True" "$(v1156_step '".prflow/vendor/prflow/scripts/check-verdict-post-reached.sh" in step["run"] and ".prflow/vendor/prflow/scripts/describe-verdict-post-gap.sh" in step["run"]')"
assert_eq "#1156 workflow: each helper carries the repo-root fallback a self-repo checkout needs" \
  "True" "$(v1156_step '"CHECK=scripts/check-verdict-post-reached.sh" in step["run"] and "GAP=scripts/describe-verdict-post-gap.sh" in step["run"]')"
# issue #1250: the reach-record step also resolves the head-reviews classifier at the
# vendored path with the same repo-root fallback, queries the reviews recorded on the
# head, and passes the classifier's token as the renderer's REVIEW_CLASS argument. This
# is the coupled contract between the workflow, the renderer's positional list and the
# classifier — adding the argument without wiring all three leaves the suite green while
# the workflow passes the wrong slot.
assert_eq "#1250 workflow: the step invokes the classifier at the vendored path with a repo-root fallback" \
  "True" "$(v1156_step '".prflow/vendor/prflow/scripts/classify-head-reviews.sh" in step["run"] and "CLS=scripts/classify-head-reviews.sh" in step["run"]')"
assert_eq "#1250 workflow: the step queries the reviews recorded on the head" \
  "True" "$(v1156_step '"pulls/$PR_NUMBER/reviews" in step["run"]')"
# --paginate is load-bearing, not cosmetic: without it the query returns only the first
# page, so a bypass review sitting past it is absent from the payload, the classifier reads
# an own set that does not contain it, and the renderer reaches the ONE arm licensed to
# assert the reviews API was untouched — the exact false statement #1250 exists to remove.
# Dropping the flag changes no helper and breaks no other assertion, so it is pinned here on
# the reviews query itself, together with the explicit page size it pages over.
assert_eq "#1250 workflow: the reviews query is paginated, so a bypass review past the first page is still seen" \
  "True" "$(v1156_step '"gh api --paginate \"repos/$REPO/pulls/$PR_NUMBER/reviews?per_page=100\"" in step["run"]')"
assert_eq "#1250 workflow: the step resolves the run's reviewer login and passes it to the classifier" \
  "True" "$(v1156_step '"REVIEWER_LOGIN" in step["env"] and "$REVIEWER_LOGIN" in step["run"]')"
assert_eq "#1250 workflow: the reviewer login is the DevFlow-Reviewer bot when minted, github-actions[bot] otherwise" \
  "True" "$(v1156_step '"steps.reviewer-token.outputs.app-slug" in step["env"]["REVIEWER_LOGIN"] and "github-actions[bot]" in step["env"]["REVIEWER_LOGIN"]')"
assert_eq "#1250 workflow: the classifier token is passed to the arm-dispatch helper as its REVIEW_CLASS argument" \
  "True" "$(v1156_step '"\"$REVIEW_CLASS\"" in step["run"] and "REVIEW_CLASS=$(bash \"$CLS\"" in step["run"]')"
assert_eq "#1156 workflow: the step ends with an explicit exit 0 so it never changes the job's result" \
  "True" "$(v1156_step 'step["run"].rstrip().endswith("exit 0")')"
# The selection is NOT in the YAML: the step renders the helper's two sinks and picks nothing.
assert_eq "#1156 workflow: the step's own shell carries no arm-selecting branch over the reader's vocabulary" \
  "True" "$(v1156_step '"NOT-REACHED" not in step["run"] and "UNESTABLISHED" not in step["run"] and "REACHED" not in step["run"]')"
assert_eq "#1156 workflow: the warning and the comment are rendered off the helper's sinks, not off an inline branch" \
  "True" "$(v1156_step '"[ -s \"$WARNING_FILE\" ]" in step["run"] and "[ -s \"$BODY_FILE\" ]" in step["run"]')"
# The gh path uses environment addressing, correct here under the .github/workflows/
# exemption lint-gh-api-repo-path.py records; the two helpers carry no gh call at all.
assert_eq "#1156 workflow: the comment POST addresses the repository from the environment" \
  "True" "$(v1156_step '"repos/$REPO/issues/$PR_NUMBER/comments" in step["run"] and step["env"]["REPO"] == "${{ github.repository }}"')"
# Neither helper touches the network — asserted by EXECUTION, not by reading their source:
# a recording `gh` is put first on PATH and both helpers are driven over every arm. That is
# what lets the workflow own the only GitHub write, which is the whole reason its `gh api`
# path may use environment addressing under the .github/workflows/ exemption.
V1156_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/gh-calls"\nexit 0\n' "$V1156_BIN" > "$V1156_BIN/gh"
chmod +x "$V1156_BIN/gh"
: > "$V1156_BIN/gh-calls"
for V1156_L in 'REACHED SKIP not-numeric' 'NOT-REACHED' 'UNESTABLISHED receipt-empty' '' 'garbage'; do
  PATH="$V1156_BIN:$PATH" bash "$V1156_GAP" "$V1156_L" 1 2 "$V1156_GSHA" "$V1156_BIN/w" "$V1156_BIN/b" >/dev/null 2>&1
done
for V1156_S in zero ws adir noread near-plural trail; do
  PATH="$V1156_BIN:$PATH" bash "$V1156_CHECK" "$V1156_SHAPES/$V1156_S" >/dev/null 2>&1
done
PATH="$V1156_BIN:$PATH" bash "$V1156_CHECK" "$V1156_NONE/nothing-here.txt" >/dev/null 2>&1
assert_eq "#1156 helpers: neither the reader nor the arm-dispatch helper invokes gh on any arm" \
  "0" "$(grep -c . "$V1156_BIN/gh-calls")"
# Anti-vacuity: the recorder DOES capture a gh invocation when one happens, so the row above
# measures an absence rather than a broken recorder.
PATH="$V1156_BIN:$PATH" gh api "repos/o/r/issues/1/comments" >/dev/null 2>&1
assert_eq "#1156 helpers: the gh recorder captures a real invocation (the absence row is not vacuous)" \
  "1" "$(grep -c . "$V1156_BIN/gh-calls")"
rm -rf "$V1156_BIN"
assert_eq "#1156 workflow: the step carries a token that can post an issue comment" \
  "True" "$(v1156_step '"steps.app-token.outputs.token || github.token" in step["env"]["GH_TOKEN"]')"

# ── issue #1271: the job-status gate. The reach-record step no longer launders a
# verdict-less review as `success`. scripts/decide-verdict-gap-job-status.sh owns the
# arm-to-job-status decision (a FAIL/PASS token over the full closed arm vocabulary), and
# the step's only remaining job is to exit with the status it reports.
V1271_DECIDE="$REPO_ROOT/scripts/decide-verdict-gap-job-status.sh"
assert_eq "#1271 helper: the job-status decision helper exists" \
  "yes" "$([ -f "$V1271_DECIDE" ] && echo yes || echo no)"

# Drive the helper over the full CLOSED reach-record arm vocabulary × oracle vocabulary ×
# cancellation. The gate is conjunctive: it FIRES on exactly one shape — the emitter not
# reached AND the head-scoped oracle POSITIVELY established absence (`none`) AND the run is
# not cancelled. Every could-not-tell arm and every non-`none` oracle answer, and every
# cancelled run, PASS.
v1271_decide() { bash "$V1271_DECIDE" "$1" "$2" "$3"; }
# The one firing shape.
assert_eq "#1271 helper: not-reached + established-absence (none) + not cancelled FAILs the job" \
  "FAIL" "$(v1271_decide not-reached none false | { read -r d _; printf '%s' "$d"; })"
# The cancellation carve-out — same firing conjuncts, but cancelled -> PASS.
assert_eq "#1271 helper: the cancellation carve-out passes the otherwise-firing shape" \
  "PASS" "$(v1271_decide not-reached none true | { read -r d _; printf '%s' "$d"; })"
# Every non-`none` oracle answer on the not-reached arm is a could-not-tell / verdict-present
# answer and must NOT fire — the "unknown is not zero" conjunct.
for V1271_RC in "marked" "unmarked 42" "unestablished payload-unreadable" "" "unestablished review-placement-unprovable"; do
  assert_eq "#1271 helper: not-reached + non-establishing oracle ('$V1271_RC') never fires the gate" \
    "PASS" "$(v1271_decide not-reached "$V1271_RC" false | { read -r d _; printf '%s' "$d"; })"
done
# Every reach-record arm OTHER than not-reached passes regardless of the oracle — a reached
# emitter is discharged; unestablished/no-line/unrecognized-line each mean the reach question
# itself could not be settled.
for V1271_ARM in reached unestablished no-line unrecognized-line garbage-arm; do
  for V1271_RC in "none" "marked" "unmarked 7" "unestablished x" ""; do
    assert_eq "#1271 helper: arm '$V1271_ARM' (not not-reached) with oracle '$V1271_RC' passes" \
      "PASS" "$(v1271_decide "$V1271_ARM" "$V1271_RC" false | { read -r d _; printf '%s' "$d"; })"
  done
done
# Cancellation short-circuits before the conjuncts on every arm.
for V1271_ARM in reached not-reached unestablished no-line unrecognized-line; do
  assert_eq "#1271 helper: cancelled run passes on arm '$V1271_ARM' regardless of oracle" \
    "PASS cancelled" "$(v1271_decide "$V1271_ARM" none true)"
done
# A CANCELLED value other than exactly `true` is treated as not-cancelled (so the gate can
# still fire on the firing shape) — the fail-closed direction. Both a bogus token (`TRUE`)
# and the EMPTY string (the value the workflow's `${JOB_CANCELLED:-false}` default guards,
# checked here at the helper boundary too) resolve to not-cancelled and still FAIL.
assert_eq "#1271 helper: a non-'true' cancelled value is treated as not cancelled" \
  "FAIL" "$(v1271_decide not-reached none TRUE | { read -r d _; printf '%s' "$d"; })"
assert_eq "#1271 helper: an empty cancelled value is treated as not cancelled (the firing shape still FAILs)" \
  "FAIL" "$(v1271_decide not-reached none "" | { read -r d _; printf '%s' "$d"; })"
# The helper always exits 0 — the decision is the stdout token, never the exit code — on
# BOTH the FAIL firing shape and a PASS shape, so a nonzero exit can never leak the verdict.
v1271_decide not-reached none false >/dev/null 2>&1
assert_eq "#1271 helper: always exits 0 on the FAIL shape (the decision is the stdout token, not the exit code)" \
  "0" "$?"
v1271_decide reached none false >/dev/null 2>&1
assert_eq "#1271 helper: always exits 0 on a PASS shape too" \
  "0" "$?"
# The helper header's residual/disposition DISCLOSURES (the oracle completeness residual, the
# possibly-vacuous cancellation premise, and the two non-defect non-reaching dispositions the
# issue's ACs require) are prose read only by the reviewing agent, so they carry NO pin — a
# comment-presence pin over them is exactly the class issues #375/#666/#810 prohibit for new
# work, and the compensating control is the review pass, not a grep (the recorded #843/#876
# decision). They are asserted nowhere here by design.

# Structural workflow assertions (parsed YAML). The step must resolve the helper at the
# vendored path with a repo-root fallback, pass the cancellation state as an ARGUMENT (via
# a JOB_CANCELLED env expression derived from job.status, never the status-check function
# cancelled() outside an `if:` or a step-level `if: !cancelled()`), and reach
# an `exit 1` from a branch keyed on the helper's own FAIL token that sits ABOVE the terminal
# `exit 0`. The pre-existing "ends with exit 0" and "no NOT-REACHED/UNESTABLISHED/REACHED"
# assertions above stay green; these make the FAILING branch and the terminal-exit SHAPE
# visible, which those two cannot (the RED-first positive control is exactly that "ends with
# exit 0" assertion — it fails the moment the step stops ending in an unconditional exit 0).
assert_eq "#1271 workflow: the step resolves the job-status helper at the vendored path with a repo-root fallback" \
  "True" "$(v1156_step '".prflow/vendor/prflow/scripts/decide-verdict-gap-job-status.sh" in step["run"] and "DECIDE=scripts/decide-verdict-gap-job-status.sh" in step["run"]')"
assert_eq "#1271 workflow: the cancellation state is derived from job.status and passed via JOB_CANCELLED, not cancelled() outside an if" \
  "True" "$(v1156_step '"JOB_CANCELLED" in step["env"] and "job.status ==" in step["env"]["JOB_CANCELLED"] and step["env"]["JOB_CANCELLED"].count("cancelled") == 1 and "cancelled()" not in step["env"]["JOB_CANCELLED"] and "JOB_CANCELLED" in step["run"] and "!cancelled()" not in step.get("if","")')"
assert_eq "#1271 workflow: the step invokes the job-status helper and passes it the arm token, the oracle class, and the cancellation state" \
  "True" "$(v1156_step '"bash \"$DECIDE\"" in step["run"] and "$ARM_TOKEN" in step["run"] and "$REVIEW_CLASS" in step["run"] and "${JOB_CANCELLED" in step["run"]')"
assert_eq "#1271 workflow: a FAIL token from the helper reaches an explicit exit 1 hoisted ABOVE the terminal exit 0" \
  "True" "$(v1156_step '"= \"FAIL\"" in step["run"] and "exit 1" in step["run"] and step["run"].rindex("exit 1") < step["run"].rindex("exit 0") and step["run"].rstrip().endswith("exit 0")')"
assert_eq "#1271 workflow: the FAIL branch emits an ::error:: so the gap is loud in the run log" \
  "True" "$(v1156_step '"::error::" in step["run"]')"
# The job-status helper's absence from an older vendored tree warns and leaves the job status
# unchanged — inline workflow shell the suite cannot execute, so structural assertion is the
# available control (the same class as the CHECK/GAP absence guard above).
assert_eq "#1271 workflow: the helper's absence from an older vendored tree warns and leaves the job status unchanged" \
  "True" "$(v1156_step '"[ ! -f \"$DECIDE\" ]" in step["run"] and "decide-verdict-gap-job-status.sh) is absent" in step["run"] and step["run"][step["run"].index("[ ! -f \"$DECIDE\" ]"):].split("fi",1)[0].strip().endswith("exit 0")')"

chmod 700 "$V1156_SHAPES/adir" 2>/dev/null || true
chmod 600 "$V1156_SHAPES/noread" "$V1156_SHAPES/zero-noread" 2>/dev/null || true
rm -rf "$V1156_ROOT" "$V1156_BLOCK" "$V1156_NONE" "$V1156_MUTR" "$V1156_GAPD" "$V1156_SHAPES"
unset V1156_ROOT V1156_BLOCK V1156_NONE V1156_MUT V1156_MUTR V1156_GAPD V1156_SHAPES V1156_RCPT V1156_TOP V1156_L V1156_A V1156_B V1156_NOLIB

# ────────────────────────────────────────────────────────────────────────────
echo "#1261 empty-branch producer (terminated run records whether any commit reached its remote branch)"
# ────────────────────────────────────────────────────────────────────────────
# scripts/record-empty-branch.sh is the producer's DECISION + the note it writes,
# extracted beside the Stall backstop step so the suite can DRIVE every outcome —
# no commit / at least one commit / could-not-establish — against a scratch git
# repository and a stubbed workpad writer (issue #1261 AC7), rather than pinning
# message wording alone. stall-backstop-decide.sh gains no I/O (AC1).
EB1261="$REPO_ROOT/scripts/record-empty-branch.sh"
assert_eq "#1261 record-empty-branch.sh exists and is executable" "yes" \
  "$([ -x "$EB1261" ] && echo yes || echo no)"

# AC1: the pure decision helper still carries NO I/O — no gh, no jq, no workpad.py
# in any NON-comment line (its header prose legitimately names them). Comment lines
# are stripped before the grep so the purity claim is about invocation, not prose.
DECIDE1261="$REPO_ROOT/scripts/stall-backstop-decide.sh"
DECIDE1261_CODE="$(grep -vE '^[[:space:]]*#' "$DECIDE1261")"
assert_eq "#1261 AC1: stall-backstop-decide.sh invokes no gh (non-comment lines)" "no" \
  "$(printf '%s\n' "$DECIDE1261_CODE" | grep -qE '(^|[^a-zA-Z_])gh ' && echo yes || echo no)"
assert_eq "#1261 AC1: stall-backstop-decide.sh invokes no jq (non-comment lines)" "no" \
  "$(printf '%s\n' "$DECIDE1261_CODE" | grep -qE '(^|[^a-zA-Z_])jq(\.| )' && echo yes || echo no)"
assert_eq "#1261 AC1: stall-backstop-decide.sh invokes no workpad.py (non-comment lines)" "no" \
  "$(printf '%s\n' "$DECIDE1261_CODE" | grep -qF 'workpad.py' && echo yes || echo no)"

# Scratch git repo with a real bare origin so the fetch+rev-list probe runs for
# real. base=main; feat is 0 commits ahead (NO_COMMIT); feat2 is 1 commit ahead
# (HAS_COMMIT). The stubbed workpad writer captures each --note into a file so the
# statement actually written is observable (AC2/AC3).
T1261="$(mktemp -d)"
mkdir -p "$T1261/origin.git" "$T1261/work" "$T1261/scripts"
git init -q --bare "$T1261/origin.git"
(
  cd "$T1261/work" || exit 1
  git init -q; git config user.email a@b.c; git config user.name t
  git commit -q --allow-empty -m base1
  git branch -M main
  git remote add origin "$T1261/origin.git"
  git push -q origin main
  git checkout -q -b feat
  git push -q origin feat                 # zero commits ahead
  git checkout -q -b feat2
  git commit -q --allow-empty -m work
  git push -q origin feat2                # one commit ahead
) >/dev/null 2>&1
# Stubbed workpad writer: append each --note value to a capture file (drivable
# proxy for the real workpad — issue #1261 "stubbed workpad writer").
cat > "$T1261/scripts/workpad.py" <<EOF
#!/usr/bin/env python3
import sys
a = sys.argv[1:]
if a and a[0] == "update" and "--note" in a:
    i = a.index("--note")
    open("$T1261/notes.txt", "a", encoding="utf-8").write(a[i + 1] + "\n")
sys.exit(0)
EOF
chmod +x "$T1261/scripts/workpad.py"

eb1261_run() {  # $1=BRANCH $2=BASE [$3=REMOTE]  -> prints the decision= line
  ( cd "$T1261/work" && ISSUE_NUMBER=1 BRANCH="$1" BASE="$2" REMOTE="${3:-origin}" \
      V="$T1261/scripts" RUN_URL=http://run/1 bash "$EB1261" )
}

# AC2 — 0 commits ahead → NO_COMMIT decision AND an explicit statement is written.
: > "$T1261/notes.txt"
D_NC="$(eb1261_run feat main | sed -n 's/^decision=//p')"
assert_eq "#1261 AC2: a branch 0 commits ahead of base decides NO_COMMIT" "NO_COMMIT" "$D_NC"
assert_eq "#1261 AC2: the NO_COMMIT statement is written to the workpad, carrying the marker" "yes" \
  "$(grep -qF '<!-- prflow:empty-branch -->' "$T1261/notes.txt" && grep -qF 'no commit reached the remote branch `feat`' "$T1261/notes.txt" && echo yes || echo no)"

# AC3 — >=1 commit ahead → HAS_COMMIT AND NO statement (the negative control).
: > "$T1261/notes.txt"
D_HC="$(eb1261_run feat2 main | sed -n 's/^decision=//p')"
assert_eq "#1261 AC3: a branch >=1 commit ahead decides HAS_COMMIT" "HAS_COMMIT" "$D_HC"
assert_eq "#1261 AC3: HAS_COMMIT writes NO statement (negative control — an always-firing note carries no info)" "0" \
  "$(wc -l < "$T1261/notes.txt" | tr -d ' ')"

# AC4 — could-not-establish: branch name unavailable, and remote branch absent.
: > "$T1261/notes.txt"
D_UN1="$(eb1261_run '' main | sed -n 's/^decision=//p')"
assert_eq "#1261 AC4: an unavailable branch name decides UNESTABLISHED" "UNESTABLISHED" "$D_UN1"
assert_eq "#1261 AC4: the UNESTABLISHED note says the fact could not be established, not that the branch is empty" "yes" \
  "$(grep -qF 'could not establish whether any commit reached the remote branch' "$T1261/notes.txt" && echo yes || echo no)"
assert_eq "#1261 AC4: the UNESTABLISHED note never claims a confirmed no-commit outcome" "no" \
  "$(grep -qF 'left nothing on its branch' "$T1261/notes.txt" && echo yes || echo no)"
: > "$T1261/notes.txt"
D_UN2="$(eb1261_run does-not-exist main | sed -n 's/^decision=//p')"
assert_eq "#1261 AC4: a branch absent from the remote decides UNESTABLISHED (not NO_COMMIT)" "UNESTABLISHED" "$D_UN2"
# The base ref could not be resolved (distinct UNESTABLISHED arm): feat exists but
# the base is absent.
D_UN3="$(eb1261_run feat nonexistent-base | sed -n 's/^decision=//p')"
assert_eq "#1261 AC4: an unresolvable base ref decides UNESTABLISHED (not NO_COMMIT)" "UNESTABLISHED" "$D_UN3"
# A genuinely unreachable remote: the fetch fails, so the outcome is UNESTABLISHED
# rather than a definite answer read off a stale tracking ref (unknown-is-not-zero).
D_UN4="$(eb1261_run feat main no-such-remote | sed -n 's/^decision=//p')"
assert_eq "#1261 AC4: an unreachable remote decides UNESTABLISHED, never a stale definite answer" "UNESTABLISHED" "$D_UN4"

# AC5 — best-effort write: a failing workpad writer emits a ::warning:: AND the
# helper still exits 0 (the caller's exit arm is never changed).
mkdir -p "$T1261/failscripts"
cat > "$T1261/failscripts/workpad.py" <<'EOF'
#!/usr/bin/env python3
import sys
sys.exit(1)
EOF
chmod +x "$T1261/failscripts/workpad.py"
OUT_FAIL1261="$( cd "$T1261/work" && ISSUE_NUMBER=1 BRANCH=feat BASE=main REMOTE=origin \
  V="$T1261/failscripts" RUN_URL=http://run/1 bash "$EB1261" 2>&1 )"
RC_FAIL1261=$?
assert_eq "#1261 AC5: a workpad write failure emits a ::warning:: breadcrumb" "yes" \
  "$(printf '%s\n' "$OUT_FAIL1261" | grep -qF '::warning::stall backstop: could not record the empty-branch statement' && echo yes || echo no)"
assert_eq "#1261 AC5: the producer always exits 0 (the caller's exit arm is never changed)" "0" "$RC_FAIL1261"
assert_eq "#1261 AC5: the decision is still printed on the write-failure arm" "yes" \
  "$(printf '%s\n' "$OUT_FAIL1261" | grep -qF 'decision=NO_COMMIT' && echo yes || echo no)"

# Idempotency — a second invocation on a workpad already carrying the marker does
# not duplicate the statement (EB_WORKPAD_BODY carries the prior note).
: > "$T1261/notes.txt"
OUT_DEDUP1261="$( cd "$T1261/work" && ISSUE_NUMBER=1 BRANCH=feat BASE=main REMOTE=origin \
  V="$T1261/scripts" RUN_URL=http://run/1 EB_WORKPAD_BODY='body ... <!-- prflow:empty-branch --> ...' bash "$EB1261" )"
assert_eq "#1261 idempotency: a workpad already carrying the marker is deduped" "yes" \
  "$(printf '%s\n' "$OUT_DEDUP1261" | grep -qF 'deduped=yes' && echo yes || echo no)"
assert_eq "#1261 idempotency: no duplicate statement is written on the deduped invocation" "0" \
  "$(wc -l < "$T1261/notes.txt" | tr -d ' ')"

# Branch resolved from the workpad body when BRANCH is empty: a real `**Branch:**`
# line resolves the branch (→ NO_COMMIT here), and a placeholder line with no
# backticks stays unresolved (→ UNESTABLISHED, never a false NO_COMMIT).
: > "$T1261/notes.txt"
D_BODY="$( cd "$T1261/work" && ISSUE_NUMBER=1 BRANCH='' BASE=main REMOTE=origin \
  V="$T1261/scripts" RUN_URL=http://run/1 EB_WORKPAD_BODY='**Branch:** `feat`' bash "$EB1261" | sed -n 's/^decision=//p' )"
assert_eq "#1261 branch parsed from the workpad body when BRANCH is empty (0-ahead → NO_COMMIT)" "NO_COMMIT" "$D_BODY"
D_PLACEHOLDER="$( cd "$T1261/work" && ISSUE_NUMBER=1 BRANCH='' BASE=main REMOTE=origin \
  V="$T1261/scripts" RUN_URL=http://run/1 EB_WORKPAD_BODY='**Branch:** _(creating…)_' bash "$EB1261" | sed -n 's/^decision=//p' )"
assert_eq "#1261 a placeholder Branch line (no backticks) stays UNESTABLISHED, never a false NO_COMMIT" "UNESTABLISHED" "$D_PLACEHOLDER"

# ── Workflow wiring (AC1 producer-in-the-step, AC6 coexists-with-flips, and the
# never-on-the-resume-path guard). Parsed from the claude job's Stall backstop
# step, the way the module asserts the existing flips.
eb1261_step() {  # $1 = python expression over `step`
  python3 - "$WFI415" "$1" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
steps = doc["jobs"]["claude"]["steps"]
named = [s for s in steps if s.get("name") == "Stall backstop"]
if len(named) != 1:
    print(f"expected exactly one Stall backstop step, found {len(named)}")
    raise SystemExit(0)
step = named[0]
print(eval(sys.argv[2], {"step": step, "run": step["run"]}))
PY
}
assert_eq "#1261 AC1: the Stall backstop step invokes record-empty-branch.sh (the producer beside the step)" \
  "True" "$(eb1261_step '"record-empty-branch.sh" in run')"
# Region delimiters are function headers / a stable following comment, not brace
# matching (the bodies carry ${1:-…} and inline { … } that defeat a naive `}` split).
# Definition order in the step is: record_empty_branch(), flip_to_failed(),
# flip_to_cancelled(), then the "# Master switch first" comment.
assert_eq "#1261 the record_empty_branch function carries the POSITIONAL CLASS=interim guard (never on the resume path)" \
  "True" "$(eb1261_step 'run.split("record_empty_branch() {",1)[1].split("flip_to_failed() {",1)[0].count("= \"interim\" ] || return 0") == 1')"
assert_eq "#1261 AC6: flip_to_failed calls record_empty_branch so 💥 Failed and the statement coexist" \
  "True" "$(eb1261_step '"record_empty_branch" in run.split("flip_to_failed() {",1)[1].split("flip_to_cancelled() {",1)[0]')"
assert_eq "#1261 AC6: flip_to_cancelled calls record_empty_branch so 🛑 Cancelled and the statement coexist" \
  "True" "$(eb1261_step '"record_empty_branch" in run.split("flip_to_cancelled() {",1)[1].split("# Master switch first",1)[0]')"
# The producer token appears exactly three times — one definition header and one
# call inside each of the two flips — which pins that it is called ONLY from the
# flips and NEVER on the resume path (a no-commit statement written before a resume
# would be stale the moment the resumed run pushes).
assert_eq "#1261 record_empty_branch is referenced exactly 3x (def + 2 flips) — never on the resume path" \
  "True" "$(eb1261_step 'run.count("record_empty_branch") == 3')"

rm -rf "$T1261"
unset EB1261 DECIDE1261 DECIDE1261_CODE T1261 D_NC D_HC D_UN1 D_UN2 D_UN3 D_UN4 D_BODY D_PLACEHOLDER OUT_FAIL1261 RC_FAIL1261 OUT_DEDUP1261

# ────────────────────────────────────────────────────────────────────────────
echo "#1858 review outcome recorded against the reviewed PR, not the commented-on one"
# ────────────────────────────────────────────────────────────────────────────
# Each of the three command-job steps derives PR_NUMBER from the resolved command's
# trailing number (event-number fallback); executing each step's real run block from
# the parsed YAML catches a swapped CONTEXT_NUMBER/COMMAND or a dropped fallback.
S1858_WF="$REPO_ROOT/.github/workflows/devflow.yml"

# Extract one command-job step's `run` body to a file.
s1858_extract() {  # $1 = step name, $2 = output file
  python3 - "$S1858_WF" "$1" "$2" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
steps = doc["jobs"]["command"]["steps"]
named = [s for s in steps if s.get("name") == sys.argv[2]]
if len(named) != 1:
    raise SystemExit(f"expected exactly one step named {sys.argv[2]!r}, found {len(named)}")
open(sys.argv[3], "w", encoding="utf-8").write(named[0]["run"])
PY
}

# Run one step's derivation; print the PR number that reached its write helper.
# $1 = step-block file, $2 = COMMAND, $3 = CONTEXT_NUMBER. Step 1's helper reads
# PR_NUMBER from the env; steps 2 and 3 receive it positionally ($3 and $2).
s1858_land() {
  local block="$1" cmd="$2" ctx="$3"
  local box rec
  box="$(mktemp -d)"
  rec="$box/landing"
  mkdir -p "$box/.prflow/vendor/prflow/scripts" "$box/bin" "$box/tmp"
  : > "$rec"
  cat > "$box/bin/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *reviews*) echo '[]' ;;
  *pulls/*)  echo 'deadbeef' ;;
  *) : ;;
esac
EOF
  cat > "$box/.prflow/vendor/prflow/scripts/post-review-backstop-comment.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\${PR_NUMBER:-}" >> "$rec"
EOF
  cat > "$box/.prflow/vendor/prflow/scripts/check-verdict-post-reached.sh" <<'EOF'
#!/usr/bin/env bash
echo NOT-REACHED
EOF
  cat > "$box/.prflow/vendor/prflow/scripts/describe-verdict-post-gap.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$3" >> "$rec"
EOF
  cat > "$box/.prflow/vendor/prflow/scripts/dismiss-stale-rejections-net.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$2" >> "$rec"
echo no-dismiss-undetermined
EOF
  chmod +x "$box/bin/gh" "$box/.prflow/vendor/prflow/scripts/"*.sh
  cp "$block" "$box/block.sh"
  ( cd "$box" && unset PR_NUMBER
    PATH="$box/bin:$PATH" RUNNER_TEMP="$box/tmp" GH_TOKEN=x REPO=o/r \
      GITHUB_RUN_ID=1 VERDICT=incomplete APP_TOKEN_PRESENT=false ENGINE_ERROR=false \
      COMMAND="$cmd" CONTEXT_NUMBER="$ctx" bash block.sh >/dev/null 2>&1 || true )
  sed -n '1p' "$rec"
  rm -rf "$box"
}

S1858_BLOCKS="$(mktemp -d)"
S1858_I=0
for S1858_STEP in \
  "Review stall backstop" \
  "Record whether the verdict emitter was reached" \
  "Dismiss superseded REJECT on a determined APPROVE"; do
  S1858_I=$((S1858_I + 1))
  S1858_BLOCK="$S1858_BLOCKS/block-$S1858_I.sh"
  s1858_extract "$S1858_STEP" "$S1858_BLOCK"
  assert_eq "#1858 [$S1858_STEP]: the command's own trailing number wins over a differing event number" \
    "42" "$(s1858_land "$S1858_BLOCK" '/prflow:review 42' '10')"
  assert_eq "#1858 [$S1858_STEP]: a command carrying no number falls back to the event's own" \
    "10" "$(s1858_land "$S1858_BLOCK" '/prflow:review' '10')"
  assert_eq "#1858 [$S1858_STEP]: a non-numeric trailing token falls back to the event's own number" \
    "10" "$(s1858_land "$S1858_BLOCK" '/prflow:review-and-fix HEAD' '10')"
  assert_eq "#1858 [$S1858_STEP]: no number on either the command or the event resolves empty" \
    "" "$(s1858_land "$S1858_BLOCK" '/prflow:review' '')"
done
rm -rf "$S1858_BLOCKS"

unset S1858_WF S1858_STEP S1858_BLOCKS S1858_BLOCK S1858_I

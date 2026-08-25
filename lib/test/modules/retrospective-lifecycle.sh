# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable retrospective issue-closure lifecycle module (issue #788).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module. References no monolith helper.
REPO_ROOT="$LIB/.."

# ────────────────────────────────────────────────────────────────────────────
echo "#788 retrospective issue-closure lifecycle"
# ────────────────────────────────────────────────────────────────────────────
RL_PS="$REPO_ROOT/lib/pattern-state.sh"
RL_MI="$REPO_ROOT/lib/meta-issue.sh"
RL_AP="$REPO_ROOT/lib/actionable-patterns.sh"
RL_CP="$REPO_ROOT/lib/compute-patterns.jq"
RL_TMP="$(mktemp -d)"
trap 'rm -rf "$RL_TMP"' RETURN

# cp_run <entries-jsonl> <overrides-json> [experiment-records-jsonl] -> the
# compute-patterns view on stdout. The optional third arg is the experiment-records
# corpus (issue #1828 cost join); an empty/absent value slurps to [] (no coverage).
rl_cp() {
  local exp="${3:-}"
  printf '%s\n' "$1" \
  | jq -s -L "$REPO_ROOT/lib" --slurpfile overrides <(printf '%s' "$2") \
      --slurpfile experiments <(printf '%s' "$exp") -f "$RL_CP"
}

# ── Migration ────────────────────────────────────────────────────────────────
# A mixed v1 fixture: one loop-written entry (dismissed_by retrospective-weekly)
# and one hand-written entry (a different dismissed_by, no meta_issue).
printf '%s' '{"schema_version":1,"dismissed":{"tooling-gap":{"dismissed_at":"2026-06-03T00:00:00Z","dismissed_by":"retrospective-weekly","reason":"meta-plugin-issue","meta_issue":"https://github.com/o/r/issues/113"},"my-hand-key":{"dismissed_at":"2026-01-01T00:00:00Z","dismissed_by":"a-human"}}}' > "$RL_TMP/mig.json"
bash "$RL_PS" migrate "$RL_TMP/mig.json" >/dev/null 2>&1
assert_eq "#891 migrate: schema_version becomes 3 (v1 lands directly at v3)" "3" "$(jq -r '.schema_version' "$RL_TMP/mig.json")"
assert_eq "#891 migrate: v1-converted record is stamped with category = its key" "tooling-gap" "$(jq -r '.patterns["tooling-gap"].category' "$RL_TMP/mig.json")"
assert_eq "#788 migrate: loop-written key becomes a lifecycle record (state filed)" "filed" "$(jq -r '.patterns["tooling-gap"].state' "$RL_TMP/mig.json")"
assert_eq "#788 migrate: lifecycle record carries the v1 meta_issue url" "https://github.com/o/r/issues/113" "$(jq -r '.patterns["tooling-gap"].meta_issues[0].url' "$RL_TMP/mig.json")"
assert_eq "#788 migrate: lifecycle record carries v1 dismissed_at as provenance" "2026-06-03T00:00:00Z" "$(jq -r '.patterns["tooling-gap"].provenance' "$RL_TMP/mig.json")"
assert_eq "#788 migrate: hand-written key survives verbatim in dismissed{}" "a-human" "$(jq -r '.dismissed["my-hand-key"].dismissed_by' "$RL_TMP/mig.json")"
assert_eq "#788 migrate: loop-written key is NOT left in dismissed{}" "false" "$(jq -e '.dismissed | has("tooling-gap")' "$RL_TMP/mig.json" >/dev/null 2>&1 && echo true || echo false)"
# Idempotency: a second migrate over the v2 file changes no byte.
cp "$RL_TMP/mig.json" "$RL_TMP/mig-before.json"
bash "$RL_PS" migrate "$RL_TMP/mig.json" >/dev/null 2>&1
assert_eq "#788 migrate is idempotent (byte-identical second run)" "true" "$(diff -q "$RL_TMP/mig-before.json" "$RL_TMP/mig.json" >/dev/null 2>&1 && echo true || echo false)"

# The migrated hand-written key still reports dismissed through compute-patterns.
assert_eq "#788 migrate: hand-written key still reports dismissed" "dismissed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["my-hand-key"]}' "$(cat "$RL_TMP/mig.json")" | jq -r '.["my-hand-key"].status')"

# ── Reconcile transitions (stubbed gh) ───────────────────────────────────────
# One gh stub: issue view returns a state keyed by number; list returns [].
cat > "$RL_TMP/gh-view.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  case "$3" in
    501) echo '{"number":501,"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-06-01T00:00:00Z"}' ;;
    502) echo '{"number":502,"state":"CLOSED","stateReason":"NOT_PLANNED","closedAt":"2026-06-02T00:00:00Z"}' ;;
    503) echo '{"number":503,"state":"CLOSED","stateReason":"DUPLICATE","closedAt":"2026-06-03T00:00:00Z"}' ;;
    504) echo '{"number":504,"state":"OPEN","stateReason":null,"closedAt":null}' ;;
    505) echo '{"number":505,"state":"CLOSED","stateReason":"WEIRD","closedAt":"2026-06-05T00:00:00Z"}' ;;
    *) echo '{"number":'"$3"',"state":"OPEN","stateReason":null,"closedAt":null}' ;;
  esac
  exit 0
fi
exit 1
STUB
chmod +x "$RL_TMP/gh-view.sh"

rl_record() { # slug number  (issue #891: v3 fixture, category == the bare key)
  printf '{"schema_version":3,"patterns":{"%s":{"category":"%s","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":%s,"url":"https://o/r/issues/%s","state":"filed","closedAt":null}]}},"dismissed":{}}' "$1" "$1" "$2" "$2"
}
printf '%s' "$(rl_record completed-slug 501)" > "$RL_TMP/t1.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t1.json" >/dev/null 2>&1
assert_eq "#788 reconcile COMPLETED → record fixed" "fixed" "$(jq -r '.patterns["completed-slug"].state' "$RL_TMP/t1.json")"
assert_eq "#788 reconcile COMPLETED → fixed_at = closedAt" "2026-06-01T00:00:00Z" "$(jq -r '.patterns["completed-slug"].fixed_at' "$RL_TMP/t1.json")"

printf '%s' "$(rl_record declined-slug 502)" > "$RL_TMP/t2.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t2.json" >/dev/null 2>&1
assert_eq "#788 reconcile NOT_PLANNED → record declined" "declined" "$(jq -r '.patterns["declined-slug"].state' "$RL_TMP/t2.json")"
assert_eq "#788 reconcile NOT_PLANNED → fixed_at stamped" "2026-06-02T00:00:00Z" "$(jq -r '.patterns["declined-slug"].fixed_at' "$RL_TMP/t2.json")"

printf '%s' "$(rl_record dup-slug 503)" > "$RL_TMP/t3.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t3.json" >/dev/null 2>&1
assert_eq "#788 reconcile DUPLICATE → record declined" "declined" "$(jq -r '.patterns["dup-slug"].state' "$RL_TMP/t3.json")"

printf '%s' "$(rl_record open-slug 504)" > "$RL_TMP/t4.json"
# pre-set a fixed_at to prove OPEN clears it
jq '.patterns["open-slug"].fixed_at = "2025-01-01T00:00:00Z"' "$RL_TMP/t4.json" > "$RL_TMP/t4b.json" && mv "$RL_TMP/t4b.json" "$RL_TMP/t4.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t4.json" >/dev/null 2>&1
assert_eq "#788 reconcile OPEN → record filed" "filed" "$(jq -r '.patterns["open-slug"].state' "$RL_TMP/t4.json")"
assert_eq "#788 reconcile OPEN → fixed_at cleared" "null" "$(jq -r '.patterns["open-slug"].fixed_at' "$RL_TMP/t4.json")"

# Unrecognized stateReason → no transition + ::warning:: naming the slug.
printf '%s' "$(rl_record weird-slug 505)" > "$RL_TMP/t5.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t5.json" 2>"$RL_TMP/t5.err" >/dev/null
assert_eq "#788 reconcile unrecognized stateReason → no transition (stays filed)" "filed" "$(jq -r '.patterns["weird-slug"].state' "$RL_TMP/t5.json")"
assert_eq "#788 reconcile unrecognized stateReason → ::warning:: names the slug" "true" \
  "$(grep -q 'weird-slug' "$RL_TMP/t5.err" && grep -q '::warning::' "$RL_TMP/t5.err" && echo true || echo false)"

# Record with no issue URL → no transition + ::warning::.
printf '%s' '{"schema_version":2,"patterns":{"nourl":{"state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[]}},"dismissed":{}}' > "$RL_TMP/t6.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t6.json" 2>"$RL_TMP/t6.err" >/dev/null
assert_eq "#788 reconcile no-url record → ::warning:: names the slug" "true" \
  "$(grep -q 'nourl' "$RL_TMP/t6.err" && grep -q '::warning::' "$RL_TMP/t6.err" && echo true || echo false)"

# A number the prefetch does not cover AND the by-number fallback cannot resolve
# is recorded unresolved: no transition, and a per-slug ::warning:: naming the
# number — the branch that keeps a permanently-inaccessible entry visible rather
# than silently frozen. Attributed by the unresolved wording, since the no-url
# branch above also emits a ::warning:: for the same slug shape.
cat > "$RL_TMP/gh-unres.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
exit 1   # every by-number view fails
STUB
chmod +x "$RL_TMP/gh-unres.sh"
printf '%s' "$(rl_record unresolvable 606)" > "$RL_TMP/t6b.json"
DEVFLOW_GH="$RL_TMP/gh-unres.sh" bash "$RL_PS" reconcile "$RL_TMP/t6b.json" 2>"$RL_TMP/t6b.err" >/dev/null
assert_eq "#788 reconcile unresolvable number → ::warning:: names the number" "true" \
  "$(grep -q 'meta-issue 606 could not be resolved' "$RL_TMP/t6b.err" && echo true || echo false)"
assert_eq "#788 reconcile unresolvable number → the entry keeps its prior state" "filed" \
  "$(jq -r '.patterns["unresolvable"].meta_issues[0].state' "$RL_TMP/t6b.json")"

# All entries closed → the record derives from the entry with the NEWEST
# closedAt, not the first or the last in array order. The array is deliberately
# ordered oldest-last so a `first`/array-order derivation picks the wrong one.
printf '%s' '{"schema_version":2,"patterns":{"allclosed":{"state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":502,"url":"https://o/r/issues/502","state":"filed","closedAt":null},{"number":501,"url":"https://o/r/issues/501","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/t6c.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t6c.json" >/dev/null 2>&1
# 502 closed NOT_PLANNED on 06-02 (newest); 501 closed COMPLETED on 06-01.
assert_eq "#788 reconcile all-closed → record state comes from the newest closedAt" "declined" \
  "$(jq -r '.patterns["allclosed"].state' "$RL_TMP/t6c.json")"
assert_eq "#788 reconcile all-closed → record fixed_at is the newest entry's" "2026-06-02T00:00:00Z" \
  "$(jq -r '.patterns["allclosed"].fixed_at' "$RL_TMP/t6c.json")"
# The terminal `declined` status arm: a declined record with NO later occurrence
# stays declined (the regressed arm above it must not claim it).
assert_eq "#788 arm order: declined record with no later occurrence stays declined" "declined" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["decl-only"]}' \
      '{"schema_version":2,"patterns":{"decl-only":{"state":"declined","fixed_at":"2026-06-01T00:00:00Z","provenance":"x","meta_issues":[{"number":1,"url":"u","state":"declined","closedAt":"2026-06-01T00:00:00Z","state_reason":"NOT_PLANNED"}]}},"dismissed":{}}' \
    | jq -r '.["decl-only"].status')"

# Two-entry record (one COMPLETED, one OPEN) → derives to filed, per-cat count 1.
printf '%s' '{"schema_version":2,"patterns":{"multi":{"state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":501,"url":"https://o/r/issues/501","state":"filed","closedAt":null},{"number":504,"url":"https://o/r/issues/504","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/t7.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t7.json" >/dev/null 2>&1
assert_eq "#788 reconcile two-entry (completed+open) → record filed" "filed" "$(jq -r '.patterns["multi"].state' "$RL_TMP/t7.json")"
assert_eq "#788 reconcile two-entry → completed entry refreshed to fixed" "fixed" "$(jq -r '.patterns["multi"].meta_issues[] | select(.number==501) | .state' "$RL_TMP/t7.json")"
assert_eq "#788 reconcile two-entry → per-category filed count reads 1" "1" "$(jq -r '[.patterns["multi"].meta_issues[] | select(.state=="filed")] | length' "$RL_TMP/t7.json")"

# Wholesale prefetch failure (gh list non-zero) → ::error:: + non-zero, no mutation.
cat > "$RL_TMP/gh-listfail.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo "boom" >&2; exit 1; fi
exit 1
STUB
chmod +x "$RL_TMP/gh-listfail.sh"
printf '%s' "$(rl_record x 501)" > "$RL_TMP/t8.json"
cp "$RL_TMP/t8.json" "$RL_TMP/t8-before.json"
DEVFLOW_GH="$RL_TMP/gh-listfail.sh" bash "$RL_PS" reconcile "$RL_TMP/t8.json" 2>"$RL_TMP/t8.err" >/dev/null; RL_T8_RC=$?
assert_eq "#788 reconcile wholesale prefetch failure → non-zero exit" "true" "$([ "$RL_T8_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 reconcile wholesale failure → ::error:: breadcrumb" "true" "$(grep -q '::error::' "$RL_TMP/t8.err" && echo true || echo false)"
assert_eq "#788 reconcile wholesale failure → file byte-unchanged" "true" "$(diff -q "$RL_TMP/t8-before.json" "$RL_TMP/t8.json" >/dev/null 2>&1 && echo true || echo false)"

# Prefetch that EXITS 0 with a non-array body (an auth interstitial, an object
# error payload). The rejection is attributed to the non-array guard by its own
# message — a bare exit-code assertion could not tell it from the exit-non-zero
# guard ten lines above, which the t8 case already covers.
cat > "$RL_TMP/gh-listobj.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '{"message":"Bad credentials"}'; exit 0; fi
exit 1
STUB
chmod +x "$RL_TMP/gh-listobj.sh"
printf '%s' "$(rl_record nonarray 501)" > "$RL_TMP/t9.json"
cp "$RL_TMP/t9.json" "$RL_TMP/t9-before.json"
DEVFLOW_GH="$RL_TMP/gh-listobj.sh" bash "$RL_PS" reconcile "$RL_TMP/t9.json" 2>"$RL_TMP/t9.err" >/dev/null; RL_T9_RC=$?
assert_eq "#788 reconcile non-array prefetch body at exit 0 → non-zero exit" "true" "$([ "$RL_T9_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 reconcile non-array prefetch → rejection attributed to the array guard" "true" \
  "$(grep -q 'did not parse as a JSON array' "$RL_TMP/t9.err" && echo true || echo false)"
assert_eq "#788 reconcile non-array prefetch → file byte-unchanged" "true" "$(diff -q "$RL_TMP/t9-before.json" "$RL_TMP/t9.json" >/dev/null 2>&1 && echo true || echo false)"
# Positive control on the SAME fixture: with a well-formed prefetch body the very
# same record reconciles, so the rejections above are the array guard firing and
# not an unrelated precondition rejecting the fixture.
printf '%s' "$(rl_record nonarray 504)" > "$RL_TMP/t9ok.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/t9ok.json" >/dev/null 2>&1; RL_T9OK_RC=$?
assert_eq "#788 reconcile non-array prefetch: positive control reconciles (exit 0)" "0" "$RL_T9OK_RC"

# A jq failure inside a command substitution is NOT caught by `set -e`. This jq
# wrapper fails ONLY on the prefetch-map reduce, so the guard under test is the
# one that must reject — an always-failing jq would be rejected by the first jq
# call instead and prove nothing about this accumulation.
cat > "$RL_TMP/jq-nomap.sh" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *'reduce .[] as $r'*) echo "jq: simulated failure" >&2; exit 5 ;; esac
done
exec jq "$@"
STUB
chmod +x "$RL_TMP/jq-nomap.sh"
printf '%s' "$(rl_record mapfail 504)" > "$RL_TMP/t10.json"
cp "$RL_TMP/t10.json" "$RL_TMP/t10-before.json"
DEVFLOW_JQ="$RL_TMP/jq-nomap.sh" DEVFLOW_GH="$RL_TMP/gh-view.sh" \
  bash "$RL_PS" reconcile "$RL_TMP/t10.json" 2>"$RL_TMP/t10.err" >/dev/null; RL_T10_RC=$?
assert_eq "#788 reconcile prefetch-map jq failure → non-zero exit (not a silent degrade)" "true" \
  "$([ "$RL_T10_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 reconcile prefetch-map jq failure → rejection attributed to the map build" "true" \
  "$(grep -q 'could not build the prefetch map' "$RL_TMP/t10.err" && echo true || echo false)"
assert_eq "#788 reconcile prefetch-map jq failure → file byte-unchanged" "true" \
  "$(diff -q "$RL_TMP/t10-before.json" "$RL_TMP/t10.json" >/dev/null 2>&1 && echo true || echo false)"

# The staging file for the rewrite lives BESIDE the destination, never under
# $TMPDIR: `mv` is an atomic rename only within one filesystem, so the write
# stages beside the destination instead. Pointing TMPDIR at a nonexistent path is
# a best-effort probe, NOT discriminating evidence: some platforms (macOS among
# them) resolve their own per-user temp dir and ignore TMPDIR entirely, so a
# green result here does not by itself prove the staging path is unused. The
# beside-destination behavior is pinned directly by the `_dir_of` assertions.
printf '%s' "$(rl_record tmpdir-free 501)" > "$RL_TMP/t11.json"
TMPDIR="$RL_TMP/no-such-tmpdir" DEVFLOW_GH="$RL_TMP/gh-view.sh" \
  bash "$RL_PS" reconcile "$RL_TMP/t11.json" >/dev/null 2>&1; RL_T11_RC=$?
assert_eq "#788 atomic write: reconcile succeeds with an unusable \$TMPDIR" "0" "$RL_T11_RC"
assert_eq "#788 atomic write: the transition still applied with an unusable \$TMPDIR" "fixed" \
  "$(jq -r '.patterns["tmpdir-free"].state' "$RL_TMP/t11.json")"
# The staging file is cleaned up — a `.overrides.*` left beside the destination
# would be committed into .prflow/learnings/ by the state PR.
assert_eq "#788 atomic write: no staging file is left beside the destination" "0" \
  "$(set -- "$RL_TMP"/.overrides*; [ -e "$1" ] && echo 1 || echo 0)"
# (The unwritable-destination-directory arm is deliberately NOT asserted with a
# `chmod 500` fixture: a root-run container ignores the mode bits, which would
# make the assertion pass or fail on the host rather than on the code. The
# fail-closed-on-unwritable path is the same `mktemp` rc the t8 byte-unchanged
# assertion already covers; the discriminating property for THIS change — that
# the staging file is not taken from $TMPDIR — is the arm asserted above.)

# ── --limit: parsing, validation, and the truncation → fallback interaction ──
printf '%s' "$(rl_record limit-arg 504)" > "$RL_TMP/lim.json"
cp "$RL_TMP/lim.json" "$RL_TMP/lim-before.json"
rl_limit_rc() { # <args...> -> "rc|stderr-matched"
  DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/lim.json" "$@" \
    2>"$RL_TMP/lim.err" >/dev/null
  printf '%s' "$?"
}
assert_eq "#788 --limit with no value → usage exit 2 (never a set -u abort)" "2" "$(rl_limit_rc --limit)"
assert_eq "#788 --limit with no value → rejection attributed to the missing value" "true" \
  "$(grep -q 'requires a value' "$RL_TMP/lim.err" && echo true || echo false)"
assert_eq "#788 --limit 0 → usage exit 2 (0 is not positive)" "2" "$(rl_limit_rc --limit 0)"
assert_eq "#788 --limit non-numeric → usage exit 2" "2" "$(rl_limit_rc --limit abc)"
assert_eq "#788 --limit rejections leave the file byte-unchanged" "true" \
  "$(diff -q "$RL_TMP/lim-before.json" "$RL_TMP/lim.json" >/dev/null 2>&1 && echo true || echo false)"
# Positive control on the same fixture: a valid --limit reconciles it.
assert_eq "#788 --limit 5 → accepted (positive control on the same fixture)" "0" "$(rl_limit_rc --limit 5)"
assert_eq "#788 --limit 5 → the transition applied" "filed" \
  "$(jq -r '.patterns["limit-arg"].state' "$RL_TMP/lim.json")"
# Truncation: the prefetch is capped and OMITS the record's number, so the
# by-number `gh issue view` fallback is what resolves it. The stub records every
# view call, so the assertion is that the fallback actually ran for this number.
cat > "$RL_TMP/gh-trunc.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  # A truncated page: a real issue, but not the one this record names.
  echo '[{"number":999,"state":"OPEN","stateReason":null,"closedAt":null}]'
  exit 0
fi
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  echo "view $3" >> "$GH_TRUNC_LOG"
  echo '{"number":'"$3"',"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-06-09T00:00:00Z"}'
  exit 0
fi
exit 1
STUB
chmod +x "$RL_TMP/gh-trunc.sh"
: > "$RL_TMP/trunc.log"
printf '%s' "$(rl_record truncated 777)" > "$RL_TMP/trunc.json"
GH_TRUNC_LOG="$RL_TMP/trunc.log" DEVFLOW_GH="$RL_TMP/gh-trunc.sh" \
  bash "$RL_PS" reconcile "$RL_TMP/trunc.json" --limit 1 >/dev/null 2>&1
assert_eq "#788 --limit truncation → the by-number fallback resolves the uncovered number" "true" \
  "$(grep -q '^view 777$' "$RL_TMP/trunc.log" && echo true || echo false)"
assert_eq "#788 --limit truncation → the fallback's state is applied" "fixed" \
  "$(jq -r '.patterns["truncated"].state' "$RL_TMP/trunc.json")"
# Prefetch HIT leg: the number IS covered by the prefetch, so no view call is made.
: > "$RL_TMP/hit.log"
printf '%s' "$(rl_record covered 999)" > "$RL_TMP/hit.json"
GH_TRUNC_LOG="$RL_TMP/hit.log" DEVFLOW_GH="$RL_TMP/gh-trunc.sh" \
  bash "$RL_PS" reconcile "$RL_TMP/hit.json" >/dev/null 2>&1
assert_eq "#788 prefetch hit → no by-number fallback call is made" "0" \
  "$(grep -c '^view 999$' "$RL_TMP/hit.log" || true)"
assert_eq "#788 prefetch hit → the prefetched state is applied" "filed" \
  "$(jq -r '.patterns["covered"].state' "$RL_TMP/hit.json")"

# ── compute-patterns.jq status arms ──────────────────────────────────────────
# Arm order: a lifecycle record at fixed + a later occurrence → regressed (against
# today's pre-#788 arm order this would report the record state; the fixture
# supplies its own RED/GREEN discrimination — no mutation helper).
REGR_OV='{"schema_version":2,"patterns":{"lenient-verdict":{"state":"fixed","fixed_at":"2026-04-01T00:00:00Z","provenance":"x","meta_issues":[{"number":9,"url":"https://o/r/issues/9","state":"fixed","closedAt":"2026-04-01T00:00:00Z"}]}},"dismissed":{}}'
assert_eq "#788 arm order: fixed record + later occ → regressed" "regressed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' "$REGR_OV" | jq -r '.["lenient-verdict"].status')"
# Human escape valve still beats the reorder.
DIS_OV='{"schema_version":2,"patterns":{"lenient-verdict":{"state":"fixed","fixed_at":"2026-04-01T00:00:00Z","provenance":"x","meta_issues":[]}},"dismissed":{"lenient-verdict":{"dismissed_by":"a-human"}}}'
assert_eq "#788 dismissed{} beats regressed" "dismissed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' "$DIS_OV" | jq -r '.["lenient-verdict"].status')"
# declined record + later occ → regressed.
DECL_OV='{"schema_version":2,"patterns":{"tooling-gap":{"state":"declined","fixed_at":"2026-04-01T00:00:00Z","provenance":"x","meta_issues":[{"number":113,"url":"https://o/r/issues/113","state":"declined","closedAt":"2026-04-01T00:00:00Z"}]}},"dismissed":{}}'
assert_eq "#788 declined record + later occ → regressed" "regressed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}' "$DECL_OV" | jq -r '.["tooling-gap"].status')"
# filed precedence: a legacy audit fix predating a newer occurrence, PLUS a `filed`
# lifecycle record (fixed_at cleared) → filed, NOT regressed.
FILED_OV='{"schema_version":2,"patterns":{"lenient-verdict":{"state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":9,"url":"https://o/r/issues/9","state":"filed","closedAt":null}]}},"dismissed":{}}'
assert_eq "#788 filed record + legacy audit fix + newer occ → filed (precedence)" "filed" \
  "$(rl_cp '{"schema_version":2,"kind":"audit","pr":1,"merged_at":"2026-06-24T00:00:00Z","fixes_patterns":["lenient-verdict"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-07-01T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' "$FILED_OV" | jq -r '.["lenient-verdict"].status')"
# no lifecycle record + legacy fix, no newer occ → fixed (falls through arms).
NOREC_OV='{"schema_version":2,"patterns":{},"dismissed":{}}'
assert_eq "#788 no record + legacy fix, no newer occ → fixed" "fixed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}
{"schema_version":2,"kind":"audit","pr":2,"merged_at":"2026-04-15T00:00:00Z","fixes_patterns":["doc-accuracy"]}' "$NOREC_OV" | jq -r '.["doc-accuracy"].status')"
# open: no record, no fix.
assert_eq "#788 no record, no fix → open" "open" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["other"]}' "$NOREC_OV" | jq -r '.other.status')"
# canonicalization: a non-canonical stored lifecycle key does not surface a phantom.
CANON_OV='{"schema_version":2,"patterns":{"Doc-Accuracy":{"state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":9,"url":"https://o/r/issues/9","state":"filed","closedAt":null}]}},"dismissed":{}}'
assert_eq "#788 non-canonical lifecycle key canonicalized (no phantom, reports filed)" "filed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' "$CANON_OV" | jq -r '.["doc-accuracy"].status')"

# ── meta-issue.sh number-keyed lifecycle write ───────────────────────────────
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/mi.json"
printf 'body\n' > "$RL_TMP/mi-body.md"
cat > "$RL_TMP/gh-mi.sh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[]' ;;
  *"issue create"*) echo 'https://github.com/o/r/issues/777' ;;
  *"issue comment"*) echo ok ;;
  *"/labels"*) echo '{}' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$RL_TMP/gh-mi.sh"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag lenient-verdict --slug lenient-verdict --category lenient-verdict --title T --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>&1
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag lenient-verdict --slug lenient-verdict --category lenient-verdict --title T --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>&1
assert_eq "#788 meta-issue two filings of same number keep one entry" "1" "$(jq -r '.patterns["lenient-verdict"].meta_issues | length' "$RL_TMP/mi.json")"
assert_eq "#788 meta-issue writes state=filed, no dismissed entry" "filed" "$(jq -r '.patterns["lenient-verdict"].state' "$RL_TMP/mi.json")"
assert_eq "#891 meta-issue writes the record's category field" "lenient-verdict" "$(jq -r '.patterns["lenient-verdict"].category' "$RL_TMP/mi.json")"
# --slug grammar validation
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug 'bad slug' --category ok --title T --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>&1; RL_SLUG_RC=$?
assert_eq "#788 meta-issue rejects a non-slug --slug (non-zero exit)" "true" "$([ "$RL_SLUG_RC" -ne 0 ] && echo true || echo false)"
# The --slug grammar is [A-Za-z0-9_-]+. Each rejected variant is a shape that
# would otherwise become a non-canonical patterns{} key (a path segment, a search
# qualifier, an empty key), and each rejection is attributed to the slug guard by
# its own message — the tag guard above it rejects on the same grammar, so an
# exit code alone could not tell the two apart.
for _rl_bad in 'a/b' 'foo:bar' ''; do
  DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug "$_rl_bad" --category ok --title T \
    --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>"$RL_TMP/slug.err"; _rl_rc=$?
  assert_eq "#788 meta-issue rejects --slug '${_rl_bad:-<empty>}' (non-zero exit)" "true" \
    "$([ "$_rl_rc" -ne 0 ] && echo true || echo false)"
  # An empty --slug is caught by the required-argument check, which names the
  # argument; a present-but-malformed one is caught by the grammar guard.
  if [ -n "$_rl_bad" ]; then
    assert_eq "#788 meta-issue: --slug '${_rl_bad}' rejection is attributed to the slug grammar" "true" \
      "$(grep -q "invalid --slug '${_rl_bad}'" "$RL_TMP/slug.err" && echo true || echo false)"
  else
    assert_eq "#788 meta-issue: an empty --slug is attributed to the missing-argument check" "true" \
      "$(grep -q -- '--slug' "$RL_TMP/slug.err" && echo true || echo false)"
  fi
done
# Positive control on the same invocation shape: a well-formed slug is accepted,
# so the rejections above are the guards firing and not a broken fixture.
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug 'good-slug_9' --category ok --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>&1; _rl_rc=$?
assert_eq "#788 meta-issue: a well-formed --slug is accepted (positive control)" "0" "$_rl_rc"

# ── #891 meta-issue --category grammar + schema-version-3 refusal ─────────────
# --category uses the NARROWER slug grammar [a-z0-9-]+ (no uppercase, no _).
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug ok --category 'Bad_Cat' --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>"$RL_TMP/cat.err"; _rl_cat_rc=$?
assert_eq "#891 meta-issue rejects a --category outside [a-z0-9-]+ (non-zero exit)" "true" "$([ "$_rl_cat_rc" -ne 0 ] && echo true || echo false)"
assert_eq "#891 meta-issue: the --category rejection is attributed to the category grammar" "true" \
  "$(grep -q "invalid --category 'Bad_Cat'" "$RL_TMP/cat.err" && echo true || echo false)"
# The rejection happens BEFORE any GitHub call: the stub's create marker never fires.
assert_eq "#891 meta-issue: a bad --category is rejected before contacting GitHub" "false" \
  "$(grep -q 'issues/777' "$RL_TMP/cat.err" && echo true || echo false)"
# An absent --category is rejected by the required-argument check, before GitHub.
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug ok --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi.json" >/dev/null 2>"$RL_TMP/nocat.err"; _rl_nocat_rc=$?
assert_eq "#891 meta-issue: an absent --category exits non-zero" "true" "$([ "$_rl_nocat_rc" -ne 0 ] && echo true || echo false)"
assert_eq "#891 meta-issue: the absent --category names the argument" "true" \
  "$(grep -q -- '--category' "$RL_TMP/nocat.err" && echo true || echo false)"
# An in-grammar category OUTSIDE the twelve-value vocabulary is accepted and written.
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/mi-vocab.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug ok --category 'not-a-vocab-category' --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi-vocab.json" >/dev/null 2>&1; _rl_voc_rc=$?
assert_eq "#891 meta-issue: an in-grammar category outside the vocabulary is accepted" "0" "$_rl_voc_rc"
assert_eq "#891 meta-issue: the out-of-vocabulary category is written verbatim" "not-a-vocab-category" \
  "$(jq -r '.patterns["ok"].category' "$RL_TMP/mi-vocab.json")"
# A non-3 schema_version file is REFUSED for the lifecycle write: URL on stdout,
# ::error:: naming 'not 3', exit 0, and NO record written.
printf '%s' '{"schema_version":2,"patterns":{},"dismissed":{}}' > "$RL_TMP/mi-v2.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok --slug ok --category ok --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi-v2.json" >"$RL_TMP/miv2.out" 2>"$RL_TMP/miv2.err"; _rl_v2_rc=$?
assert_eq "#891 meta-issue: a non-3 schema_version still exits 0" "0" "$_rl_v2_rc"
assert_eq "#891 meta-issue: a non-3 schema_version prints the issue URL on stdout" "https://github.com/o/r/issues/777" "$(cat "$RL_TMP/miv2.out")"
assert_eq "#891 meta-issue: the refusal breadcrumb says 'not 3'" "true" \
  "$(grep -q 'not 3' "$RL_TMP/miv2.err" && echo true || echo false)"
assert_eq "#891 meta-issue: no lifecycle record is written to a non-3 file" "false" \
  "$(jq -e '.patterns | has("ok")' "$RL_TMP/mi-v2.json" >/dev/null 2>&1 && echo true || echo false)"

# ── actionable-patterns regressed bypass + liveness ──────────────────────────
# A regressed pattern with occurrence_count BELOW min_occurrences is still
# actionable (regressed bypasses the threshold).
printf '%s\n' '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}' > "$RL_TMP/ap-r.jsonl"
printf '%s' "$DECL_OV" > "$RL_TMP/ap-ov.json"
cat > "$RL_TMP/gh-ap.sh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[]' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$RL_TMP/gh-ap.sh"
RL_APOUT="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" bash "$RL_AP" "$RL_TMP/ap-r.jsonl" "$RL_TMP/ap-ov.json" 2>/dev/null)"
assert_eq "#788 actionable: regressed pattern below min is still actionable (bypass)" "true" \
  "$(printf '%s' "$RL_APOUT" | jq 'any(.[]; .tag=="tooling-gap" and .status=="regressed")')"
# Liveness: eligible set empty while a fixed pattern has occurred at/above min → warning.
# Build a view where the only pattern is `fixed` with occ>=2 (min): no eligible,
# but suppressed at/above the threshold → liveness warning on stderr.
printf '%s\n' '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-01-02T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' > "$RL_TMP/live-r.jsonl"
printf '%s' '{"schema_version":2,"patterns":{"doc-accuracy":{"state":"fixed","fixed_at":"2027-01-01T00:00:00Z","provenance":"x","meta_issues":[{"number":9,"url":"https://o/r/issues/9","state":"fixed","closedAt":"2027-01-01T00:00:00Z"}]}},"dismissed":{}}' > "$RL_TMP/live-ov.json"
DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" 2>"$RL_TMP/live.err" >/dev/null
assert_eq "#788 liveness: fixed-and-suppressed with empty eligible set → ::warning::" "true" \
  "$(grep -q '::warning::actionable-patterns: no pattern is eligible' "$RL_TMP/live.err" && echo true || echo false)"
assert_eq "#788 liveness: warning names the highest suppressed slug" "true" \
  "$(grep -q 'doc-accuracy' "$RL_TMP/live.err" && echo true || echo false)"
# The emitted text says "occurred at/above", not "recur": occurrence_count is
# cumulative, so a `fixed` pattern whose occurrences all predate its fixed_at
# satisfies this condition indefinitely — and one that genuinely recurred would
# have derived `regressed`, which is eligible and empties this branch. This
# fixture IS that steady state (fixed_at is in the future, every occurrence
# before it), so a "recurs" claim here would be false of the very run emitting it.
assert_eq "#788 liveness: the warning claims occurrence, not recurrence" "true" \
  "$(grep -q 'have occurred at/above min_occurrences and are currently suppressed' "$RL_TMP/live.err" && echo true || echo false)"
# Producer → parser join on the REAL capture: the `liveness:` line this run wrote
# is the line the report renders from. The synthetic fixture in the
# filing-decisions block below exercises the parser; this exercises the contract
# between the two, which a wording change on either side alone would break.
cp "$RL_TMP/live.err" "$RL_TMP/live-real.err"
(
  set +e
  # shellcheck source=../../filing-decisions.sh
  . "$REPO_ROOT/lib/filing-decisions.sh"
  RL_REAL_LIVE="$(devflow_liveness_warning "$RL_TMP/live-real.err")"
  assert_eq "#788 liveness: the real emitted line is extracted for the report" "true" \
    "$([ -n "$RL_REAL_LIVE" ] && echo true || echo false)"
  assert_eq "#788 liveness: the extracted line carries the count and the slug" "true" \
    "$(case "$RL_REAL_LIVE" in "1 suppressed pattern(s) at/above min_occurrences, highest doc-accuracy") echo true ;; *) echo false ;; esac)"
)
# Negative case: `filed` (an open meta-issue) is excluded even at/above min.
printf '%s' '{"schema_version":2,"patterns":{"doc-accuracy":{"state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":9,"url":"https://o/r/issues/9","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/live-ov2.json"
DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov2.json" 2>"$RL_TMP/live2.err" >"$RL_TMP/live2.out"; RL_LIVE2_RC=$?
# An absent warning is only evidence of the `filed` exclusion if the run REACHED
# the liveness block. Without the rc and stdout assertions this is a grep for a
# string over the stderr of a command that may have aborted for any unrelated
# reason — an arg-guard change, an unresolvable config path, a jq failure — all of
# which put a DIFFERENT error on stderr, miss the grep, and report PASS while the
# named behaviour is untested.
assert_eq "#788 liveness: the all-filed invocation actually succeeded (rc 0)" "0" "$RL_LIVE2_RC"
assert_eq "#788 liveness: it produced a well-formed (empty) eligible set on stdout" "0" \
  "$(jq 'length' "$RL_TMP/live2.out" 2>/dev/null || echo MALFORMED)"
assert_eq "#788 liveness: all-filed set at/above min emits NO warning" "false" \
  "$(grep -q '::warning::actionable-patterns: no pattern is eligible' "$RL_TMP/live2.err" && echo true || echo false)"

# --full: the UNFILTERED view the report renders. It carries the suppressed
# pattern the default (eligible-only) view filters out, and it suppresses the
# liveness diagnostic — the caller asked for the raw view, not a verdict on it.
RL_FULLOUT="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" --full 2>"$RL_TMP/full.err")"
assert_eq "#788 --full: the suppressed pattern the default view omits is present" "true" \
  "$(printf '%s' "$RL_FULLOUT" | jq 'any(.[]; .tag=="doc-accuracy")')"
assert_eq "#788 --full: the pattern carries its lifecycle status" "fixed" \
  "$(printf '%s' "$RL_FULLOUT" | jq -r '.[] | select(.tag=="doc-accuracy") | .status')"
assert_eq "#788 --full: the liveness diagnostic is suppressed" "false" \
  "$(grep -q '::warning::actionable-patterns: no pattern is eligible' "$RL_TMP/full.err" && echo true || echo false)"
# Control on the same fixture: without --full the same input DOES emit it, so the
# assertion above pins the --full suppression and not an inert fixture.
assert_eq "#788 --full: the same fixture emits the diagnostic without --full" "true" \
  "$(grep -q '::warning::actionable-patterns: no pattern is eligible' "$RL_TMP/live.err" && echo true || echo false)"

# The arg guard must reject EVERY unrecognized trailing argument, not only $3.
# The failure this closes is the one the guard's own comment names: a --full that
# lands past $3 leaves FULL=0, so the caller writes the FILTERED subset to
# patterns-full.json and the report renders it under a heading promising the
# unfiltered picture — well-formed, non-empty and wrong, with every downstream
# guard passing. `case "${3:-}"` alone cannot see it.
bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" '' --full >/dev/null 2>"$RL_TMP/arg4.err"; RL_ARG4_RC=$?
assert_eq "#788 args: --full landing in \$4 is rejected, not silently ignored" "2" "$RL_ARG4_RC"
assert_eq "#788 args: the \$4 rejection names the offending argument" "true" \
  "$(grep -q "unexpected argument" "$RL_TMP/arg4.err" && echo true || echo false)"
bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" --full --bogus >/dev/null 2>"$RL_TMP/arg4b.err"; RL_ARG4B_RC=$?
assert_eq "#788 args: a trailing junk argument after --full is rejected too" "2" "$RL_ARG4B_RC"
# Positive control on the same fixture: the accepted arities still succeed, so the
# two rejections above pin the arity guard and not a broken fixture.
#
# These two MUST stub gh. The accepted arities run past the arg guard into the
# open-issue cooldown lookup, which exits 1 on a gh failure — so on a host with no
# authenticated gh (every CI runner) an unstubbed control fails for a reason that
# has nothing to do with arity, while passing at a desk where gh happens to be
# logged in. The rejected arities above exit at the guard, before any gh call, so
# they need no stub.
printf '#!/usr/bin/env bash\nprintf "[]"\n' > "$RL_TMP/gh-noissues.sh"
chmod +x "$RL_TMP/gh-noissues.sh"
DEVFLOW_GH="$RL_TMP/gh-noissues.sh" bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" --full >/dev/null 2>&1; RL_ARG3_RC=$?
assert_eq "#788 args: the 3-arg --full form still succeeds (control)" "0" "$RL_ARG3_RC"
DEVFLOW_GH="$RL_TMP/gh-noissues.sh" bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" >/dev/null 2>&1; RL_ARG2_RC=$?
assert_eq "#788 args: the 2-arg default form still succeeds (control)" "0" "$RL_ARG2_RC"

# ── caps: open-count derivation + report rendering ───────────────────────────
# The cap counts are derived from `filed` lifecycle entries across records, never
# from a label query. A record with two `filed` entries and one `fixed` entry
# contributes 2 to max_open_issues and 2 to that category's max_open_per_category.
# NOTE (deliberately absent): two assertions here used to pipe a fixture through
# an inline jq program written in this file and compare it to a hand-counted literal.
# They invoked NO production code — no single-line change to any shipped file
# could make either fail — while their names asserted a product contract. They
# were tautologies over a hand-written filter that also inflated the tally
# against the registry floor. The real contract is driven through the shipped
# helpers (`devflow_open_filed_total` / `_in_category`) further down.
# render-report names each withheld pattern with its cap.
( . "$REPO_ROOT/lib/render-report.sh"
  WSUM='{"prs_scanned":1,"clean_count":0,"analyzed_count":1,"withheld_patterns":[{"tag":"tooling-gap","cap":"max_issues_per_run"}]}'
  WREP="$(devflow_render_report "$WSUM")"
  assert_eq "#788 report: withheld section names the pattern" "true" \
    "$(printf '%s' "$WREP" | grep -q 'tooling-gap' && echo true || echo false)"
  assert_eq "#788 report: withheld section names the cap" "true" \
    "$(printf '%s' "$WREP" | grep -q 'max_issues_per_run' && echo true || echo false)" )

# ── real-corpus migrate-then-reconcile-then-derive integration ───────────────
# A v1 fixture shaped like this repo's real overrides.json (the loop's own dismissed
# entries for the 11 categories), with a stubbed gh returning the real issue states,
# asserts the lifecycle-record states after migrate+reconcile: dismissed{} holds no
# loop-written key, tooling-gap → declined (#113 NOT_PLANNED), the rest → fixed.
printf '%s' '{"schema_version":1,"dismissed":{
  "tooling-gap":{"dismissed_at":"2026-06-03T21:39:06Z","dismissed_by":"retrospective-weekly","reason":"meta-plugin-issue","meta_issue":"https://github.com/o/r/issues/113"},
  "fabricated-claim":{"dismissed_at":"2026-07-24T00:00:00Z","dismissed_by":"retrospective-weekly","reason":"meta-plugin-issue","meta_issue":"https://github.com/o/r/issues/761"},
  "doc-accuracy":{"dismissed_at":"2026-06-29T00:00:00Z","dismissed_by":"retrospective-weekly","reason":"meta-plugin-issue","meta_issue":"https://github.com/o/r/issues/183"}
}}' > "$RL_TMP/real.json"
cat > "$RL_TMP/gh-real.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  case "$3" in
    113) echo '{"number":113,"state":"CLOSED","stateReason":"NOT_PLANNED","closedAt":"2026-06-28T21:24:43Z"}' ;;
    761) echo '{"number":761,"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-07-24T10:11:25Z"}' ;;
    183) echo '{"number":183,"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-06-30T00:00:00Z"}' ;;
    *) echo '{"number":'"$3"',"state":"OPEN","stateReason":null,"closedAt":null}' ;;
  esac
  exit 0
fi
exit 1
STUB
chmod +x "$RL_TMP/gh-real.sh"
DEVFLOW_GH="$RL_TMP/gh-real.sh" bash "$RL_PS" run "$RL_TMP/real.json" >/dev/null 2>&1
assert_eq "#788 real-corpus: dismissed{} holds no loop-written key" "0" "$(jq -r '.dismissed | length' "$RL_TMP/real.json")"
assert_eq "#788 real-corpus: tooling-gap record is declined" "declined" "$(jq -r '.patterns["tooling-gap"].state' "$RL_TMP/real.json")"
assert_eq "#788 real-corpus: fabricated-claim record is fixed" "fixed" "$(jq -r '.patterns["fabricated-claim"].state' "$RL_TMP/real.json")"
assert_eq "#788 real-corpus: doc-accuracy record is fixed" "fixed" "$(jq -r '.patterns["doc-accuracy"].state' "$RL_TMP/real.json")"
# Derived statuses after compute-patterns over the reconciled state: a slug whose
# newest occurrence post-dates its fixed_at → regressed (tooling-gap: declined #113
# closed 2026-06-28, occurrence after); fabricated-claim → fixed (issue closed
# after its last occurrence).
RC_ENTRIES='{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-07-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-07-23T17:32:23Z","verdict":"imperfect","categories":["fabricated-claim"]}'
RC_VIEW="$(rl_cp "$RC_ENTRIES" "$(cat "$RL_TMP/real.json")")"
assert_eq "#788 real-corpus derived: tooling-gap → regressed" "regressed" "$(printf '%s' "$RC_VIEW" | jq -r '.["tooling-gap"].status')"
assert_eq "#788 real-corpus derived: fabricated-claim → fixed" "fixed" "$(printf '%s' "$RC_VIEW" | jq -r '.["fabricated-claim"].status')"

# ────────────────────────────────────────────────────────────────────────────
# compute-patterns.jq — relocated from lib/test/run.sh (issue #788 AC).
# ────────────────────────────────────────────────────────────────────────────


cp_run() {
  local entries="$1" overrides="$2" experiments="${3:-}"
  printf '%s\n' "$entries" \
  | jq -s -L "$LIB" --slurpfile overrides <(printf '%s' "$overrides") \
      --slurpfile experiments <(printf '%s' "$experiments") \
      -f "$LIB/compute-patterns.jq"
}

# Two open occurrences (schema-v2 `categories`) → status "open", count 2,
# and the descriptors of both occurrences are unioned into the pattern view.
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"],"descriptors":["orphaned fetch in handleEvent"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-10T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit","doc-accuracy"],"descriptors":["stale count not propagated"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "two open occurrences → status=open" \
  "open" \
  "$(echo "$RESULT" | jq -r '.["incomplete-edit"].status')"
assert_eq "two open occurrences → count=2" \
  "2" \
  "$(echo "$RESULT" | jq -r '.["incomplete-edit"].occurrence_count')"
assert_eq "descriptors unioned across occurrences" \
  "orphaned fetch in handleEvent|stale count not propagated" \
  "$(echo "$RESULT" | jq -r '.["incomplete-edit"].descriptors | sort | join("|")')"
assert_eq "a second category from the same PR forms its own pattern" \
  "1" \
  "$(echo "$RESULT" | jq -r '.["doc-accuracy"].occurrence_count')"

# Legacy schema-v1 `theme_tags` entries still count (the `// .theme_tags`
# fallback in compute-patterns.jq) and slugify the same way as v2 categories,
# so a mixed file (pre- and post-migration entries) Just Works.
RESULT=$(cp_run \
  '{"schema_version":1,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","theme_tags":["doc-accuracy"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-10T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "v1 theme_tags + v2 categories grouped together (count=2)" \
  "2" \
  "$(echo "$RESULT" | jq -r '.["doc-accuracy"].occurrence_count')"

# One occ + later audit fix → status "fixed"
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}
{"schema_version":2,"kind":"audit","pr":2,"merged_at":"2026-04-15T00:00:00Z","fixes_patterns":["lenient-verdict"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "occ then fix → status=fixed" \
  "fixed" \
  "$(echo "$RESULT" | jq -r '.["lenient-verdict"].status')"

# Successor-slug split (#129): each of the three slugs that replaced the removed
# coarse review/gate slug aggregates as its own pattern, and the removed slug
# never appears.
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["outstanding-reject"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-05-02T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}
{"schema_version":2,"kind":"implementation","pr":3,"merged_at":"2026-05-03T00:00:00Z","verdict":"imperfect","categories":["deferred-verification"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "split slug outstanding-reject aggregates (count=1)" \
  "1" "$(echo "$RESULT" | jq -r '.["outstanding-reject"].occurrence_count')"
assert_eq "split slug lenient-verdict aggregates (count=1)" \
  "1" "$(echo "$RESULT" | jq -r '.["lenient-verdict"].occurrence_count')"
assert_eq "split slug deferred-verification aggregates (count=1)" \
  "1" "$(echo "$RESULT" | jq -r '.["deferred-verification"].occurrence_count')"
assert_eq "removed split slug never aggregates" \
  "null" "$(echo "$RESULT" | jq -r '.["review-gate" + "-bypass"].occurrence_count')"

# Boundary case: a gate-absent / human-authored PR (no review-related slug) maps to
# NONE of the three successor slugs.
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":9,"merged_at":"2026-05-09T00:00:00Z","verdict":"imperfect","categories":["other"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "gate-absent PR → no outstanding-reject pattern" \
  "null" "$(echo "$RESULT" | jq -r '.["outstanding-reject"].occurrence_count')"
assert_eq "gate-absent PR → no lenient-verdict pattern" \
  "null" "$(echo "$RESULT" | jq -r '.["lenient-verdict"].occurrence_count')"
assert_eq "gate-absent PR → no deferred-verification pattern" \
  "null" "$(echo "$RESULT" | jq -r '.["deferred-verification"].occurrence_count')"


# Fix then later occ → status "regressed"
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"audit","pr":1,"merged_at":"2026-04-01T00:00:00Z","fixes_patterns":["convention-violation"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-15T00:00:00Z","verdict":"imperfect","categories":["convention-violation"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "fix then occ → status=regressed" \
  "regressed" \
  "$(echo "$RESULT" | jq -r '.["convention-violation"].status')"

# Override → status "dismissed"
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{"tooling-gap":{"reason":"meta-plugin-issue"}}}')
assert_eq "override → status=dismissed" \
  "dismissed" \
  "$(echo "$RESULT" | jq -r '.["tooling-gap"].status')"

# verdict:"blocked" entries also count as occurrences (alongside "imperfect").
# A simplification of the filter to drop "blocked" would silently make the
# whole "Blocked" workpad-status branch invisible to the audit.
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"blocked","categories":["unmet-acceptance-criteria"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "blocked verdict counts as occurrence" \
  "1" \
  "$(echo "$RESULT" | jq -r '.["unmet-acceptance-criteria"].occurrence_count')"

# Slug normalization is still applied defensively: a legacy mixed-case
# theme_tag slugifies to lowercase and matches a lowercase fixes_pattern.
RESULT=$(cp_run \
  '{"schema_version":1,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","theme_tags":["Foo-Bar-IN-Clause"]}
{"schema_version":2,"kind":"audit","pr":2,"merged_at":"2026-04-15T00:00:00Z","fixes_patterns":["foo-bar-in-clause"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "slug normalization: mixed-case theme_tag matched by lowercase fixes_pattern → fixed" \
  "fixed" \
  "$(echo "$RESULT" | jq -r '.["foo-bar-in-clause"].status')"

# Missing merged_at MUST NOT contaminate first_seen/last_seen.
# An entry with no merged_at should be excluded from occurrences.
RESULT=$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-15T00:00:00Z","verdict":"imperfect","categories":["other"]}
{"schema_version":2,"kind":"implementation","pr":2,"verdict":"imperfect","categories":["other"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}')
assert_eq "missing merged_at filtered out (count=1)" \
  "1" \
  "$(echo "$RESULT" | jq -r '.["other"].occurrence_count')"
assert_eq "missing merged_at does not poison first_seen" \
  "2026-04-15T00:00:00Z" \
  "$(echo "$RESULT" | jq -r '.["other"].first_seen')"

# ────────────────────────────────────────────────────────────────────────────
# meta-issue.sh — relocated from lib/test/run.sh (issue #788 AC).
# ────────────────────────────────────────────────────────────────────────────

# The `TMP_`/`TEMP_` prefix is load-bearing, not stylistic: the #810 mutation-routing
# gate scopes its raw-presence pin policy to haystacks that resolve INSIDE the repo, and
# recognizes a `TMP_`/`TEMP_`-named variable as runtime scratch that is out of scope
# entirely (`lib/test/pin-corpus-lint.py`'s `_raw_guard_site`, covered by
# `test_runtime_pipe_count_absence_and_temp_greps_are_not_raw_presence_pins`). The
# `grep -qF` assertions below read argv this run's `gh` stub captured — an executable
# surface, not repo source — so renaming this variable to a non-prefixed form would put
# them in scope and fail the gate with no source-presence pin actually present.
TMP_MI="$(mktemp -d)"
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov.json"
# #152: the body is the Stage-B-authored issue spec, filed VERBATIM. Use a body
# with backticks, $, and newlines to prove it round-trips unmangled (written to a
# file, never inlined into shell) and is NOT wrapped in any prepend/append.
printf '## Problem Statement\nStrengthen `cheap-gate.jq` so $VAR shapes do not slip.\n\nMulti-line.\n' > "$TMP_MI/body.md"
# Stub writes its capture files into its own dir ($TMP_MI) so a quoted heredoc can
# stay free of run.sh shell-var interpolation. Handles label create / issue edit
# (the best-effort label stamping) in addition to list/create/comment.
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
D="$(dirname "$0")"
case "$*" in
  *"issue list"*) echo '' ;;                                # no existing issue
  *"issue create"*)
     printf '%s' "$*" > "$D/create-args"
     prev=""
     for a in "$@"; do
       [ "$prev" = "--body-file" ] && cat "$a" > "$D/created-body.md"
       prev="$a"
     done
     echo 'https://github.com/acme/example-repo/issues/4242' ;;
  *"issue comment"*) echo 'commented' ;;
  *"issues/"*"/labels"*) printf '%s' "$*" > "$D/edit-args" ;;   # REST label apply (apply-labels.sh)
  *"--method POST"*"/labels"*) echo '{}' ;;                       # REST label create (ensure-label.sh)
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
URL="$(DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag review-reject-bypassed --slug review-reject-bypassed --category review-reject-bypassed --title "audit(devflow): x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov.json" 2>/dev/null)"
assert_eq "meta-issue returns the new URL" "https://github.com/acme/example-repo/issues/4242" "$URL"
# Created title must keep the de-dup key prefix (Step-1 search matches it) AND
# carry the caller's --title (regression: --title was previously discarded).
assert_eq "create title keeps the de-dup key" "true" \
  "$(grep -qF -- '--title [devflow-retrospective] meta: review-reject-bypassed' "$TMP_MI/create-args" && echo true || echo false)"
assert_eq "create title carries the caller --title" "true" \
  "$(grep -qF -- 'audit(devflow): x' "$TMP_MI/create-args" && echo true || echo false)"
# #152: the filed body equals the input verbatim — no `## Pattern:` prepend, no
# "can't be an auto-opened PR" boilerplate, backticks/$/newlines intact.
assert_eq "meta-issue files the body verbatim" "true" \
  "$(diff -q "$TMP_MI/body.md" "$TMP_MI/created-body.md" >/dev/null 2>&1 && echo true || echo false)"
# #152: both the DevFlow provenance label and the Retrospective marker are stamped
# (best-effort) on the freshly filed issue (#4242, derived from the created URL).
assert_eq "meta-issue stamps PRFlow label (REST labels[] field)" "true" \
  "$(grep -qF -- 'labels[]=PRFlow' "$TMP_MI/edit-args" && echo true || echo false)"
assert_eq "meta-issue stamps Retrospective label (REST labels[] field)" "true" \
  "$(grep -qF -- 'labels[]=Retrospective' "$TMP_MI/edit-args" && echo true || echo false)"
assert_eq "meta-issue applies via REST issues/4242/labels (not gh issue edit)" "true" \
  "$(grep -qF -- 'issues/4242/labels' "$TMP_MI/edit-args" && echo true || echo false)"
# #788: the filing records a `filed` lifecycle entry (number-keyed) on the slug's
# patterns[] record — NOT a `.dismissed` entry (that map is human-owned now).
assert_eq "lifecycle entry recorded with url" "https://github.com/acme/example-repo/issues/4242" "$(jq -r '.patterns["review-reject-bypassed"].meta_issues[0].url' "$TMP_MI/ov.json")"
assert_eq "lifecycle entry keyed by number"   "4242" "$(jq -r '.patterns["review-reject-bypassed"].meta_issues[0].number' "$TMP_MI/ov.json")"
assert_eq "lifecycle record state is filed"   "filed" "$(jq -r '.patterns["review-reject-bypassed"].state' "$TMP_MI/ov.json")"
assert_eq "filing writes NO dismissed entry"  "false" "$(jq -e '.dismissed | has("review-reject-bypassed")' "$TMP_MI/ov.json" >/dev/null 2>&1 && echo true || echo false)"
# existing-issue path (de-dup): comments instead of re-filing, still stamps labels
rm -f "$TMP_MI/edit-args"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
D="$(dirname "$0")"
case "$*" in
  *"issue list"*) echo '[{"number":99,"url":"https://github.com/acme/example-repo/issues/99","title":"[devflow-retrospective] meta: t-existing — x"}]' ;;
  *"issue comment"*) echo 'commented' ;;
  *"issues/"*"/labels"*) printf '%s' "$*" > "$D/edit-args" ;;   # REST label apply (apply-labels.sh)
  *"--method POST"*"/labels"*) echo '{}' ;;                       # REST label create (ensure-label.sh)
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
URL2="$(DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag t-existing --slug t-existing --category t-existing --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov.json" 2>/dev/null)"
assert_eq "meta-issue reuses existing URL" "https://github.com/acme/example-repo/issues/99" "$URL2"
assert_eq "meta-issue stamps labels on the existing issue #99 (REST issues/99/labels)" "true" \
  "$(grep -qF -- 'issues/99/labels' "$TMP_MI/edit-args" && echo true || echo false)"
# #152: fail CLOSED on a create that returns no usable issue URL. `gh issue create`
# can exit 0 with empty/garbage stdout; without the URL-shape guard meta-issue.sh
# would report a phantom filing AND write a permanent overrides.json cooldown for
# an issue that never existed (the "never report unfiled as filed" invariant). The
# guard must exit non-zero so the orchestrator records a blocker, and must NOT have
# written a dismissal for the slug.
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov2.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '' ;;            # no existing issue → create path
  *"issue create"*) echo '' ;;          # exit 0 but NO url
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag empty-url --slug empty-url --category empty-url --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov2.json" >/dev/null 2>&1; EMPTY_RC=$?
assert_eq "meta-issue fails closed on empty create URL (non-zero exit)" "true" \
  "$([ "$EMPTY_RC" -ne 0 ] && echo true || echo false)"
assert_eq "meta-issue wrote NO lifecycle record on empty create URL" "false" \
  "$(jq -e '.patterns | has("empty-url")' "$TMP_MI/ov2.json" >/dev/null 2>&1 && echo true || echo false)"
# garbage (non-URL) stdout → same fail-closed
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '' ;;
  *"issue create"*) echo 'could not create issue: HTTP 403' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag garbage-url --slug garbage-url --category garbage-url --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov2.json" >/dev/null 2>&1; GARBAGE_RC=$?
assert_eq "meta-issue fails closed on garbage create stdout (non-zero exit)" "true" \
  "$([ "$GARBAGE_RC" -ne 0 ] && echo true || echo false)"
# de-dup lookup failure (gh issue list non-zero) → exit 1 (orchestrator blocker trigger)
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) exit 1 ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag lookup-fail --slug lookup-fail --category lookup-fail --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov2.json" >/dev/null 2>&1; LOOKUP_RC=$?
assert_eq "meta-issue fails closed on de-dup lookup error (non-zero exit)" "true" \
  "$([ "$LOOKUP_RC" -ne 0 ] && echo true || echo false)"
# #152: de-dup lookup that exits 0 with a NON-JSON body (auth/upgrade warning on
# stdout, HTML error page) must fail CLOSED at the jq parse, not flow on as "no
# existing issue" and re-file a duplicate. Mirrors actionable-patterns.sh's
# non-JSON cooldown guard (the sibling consumer of the same gh contract).
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo 'gh: not authenticated' ;;   # exit 0 but non-JSON
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag nonjson-lookup --slug nonjson-lookup --category nonjson-lookup --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov2.json" >/dev/null 2>&1; NONJSON_RC=$?
assert_eq "meta-issue fails closed on a non-JSON de-dup body (non-zero exit)" "true" \
  "$([ "$NONJSON_RC" -ne 0 ] && echo true || echo false)"
# --dry-run: records the DRYRUN sentinel, invokes NO issue create / issue edit
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov3.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
D="$(dirname "$0")"
case "$*" in
  *"issue list"*) echo '' ;;
  *"issue create"*) echo "CREATE_CALLED" >> "$D/calls" ; echo '' ;;
  *"issue edit"*) echo "EDIT_CALLED" >> "$D/calls" ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
rm -f "$TMP_MI/calls"
DRY_URL="$(DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --dry-run --tag dry --slug dry --category dry --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov3.json" 2>/dev/null)"
assert_eq "meta-issue --dry-run prints the DRYRUN sentinel" "https://example.invalid/issues/DRYRUN" "$DRY_URL"
assert_eq "meta-issue --dry-run invokes no gh create/edit" "true" \
  "$([ ! -f "$TMP_MI/calls" ] && echo true || echo false)"
# #152: de-dup HIT path also fails closed on a garbage url/number (gh --json drift
# emitting a null number/url) — mirrors the create-path guard.
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[{"number":null,"url":null,"title":"[devflow-retrospective] meta: dedup-null — x"}]' ;;   # contract drift: nulls
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag dedup-null --slug dedup-null --category dedup-null --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov2.json" >/dev/null 2>&1; DEDUP_RC=$?
assert_eq "meta-issue fails closed on a de-dup hit with null url/number" "true" \
  "$([ "$DEDUP_RC" -ne 0 ] && echo true || echo false)"
# #152: the tokenized GitHub --search can surface an issue whose title does NOT
# literally carry `meta: ${TAG}` (a loose token hit). meta-issue.sh must STRICTLY
# re-parse the slug and reject the loose match — filing a NEW issue (create path)
# rather than commenting on / pinning the cooldown to the wrong issue. Here the
# only open issue's slug is `widget-foobar`; the requested tag is `widget` →
# no exact match → create path (returns the freshly created URL, not #88).
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov-loose.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[{"number":88,"url":"https://github.com/acme/example-repo/issues/88","title":"[devflow-retrospective] meta: widget-foobar — loose"}]' ;;
  *"issue create"*) echo 'https://github.com/acme/example-repo/issues/4343' ;;
  *"issue edit"*) : ;;
  *"label create"*) echo 'created' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
LOOSE_URL="$(DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag widget --slug widget --category widget --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-loose.json" 2>/dev/null)"
assert_eq "meta-issue strict-rejects a loose --search slug match (files new, not #88)" "https://github.com/acme/example-repo/issues/4343" "$LOOSE_URL"
# #152: overrides-write failure AFTER a successful create reports FILED, not
# blocked — a corrupt overrides file makes the jq cooldown write fail, but the
# issue genuinely exists, so meta-issue.sh must exit 0 with the URL on stdout
# (the orchestrator records the filing) and leave a loud ::error:: breadcrumb;
# the open-issue de-dupe self-heals the missing cooldown next run. Reporting
# "not filed" here would lose a real issue.
printf 'not json{' > "$TMP_MI/ov-corrupt.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '' ;;
  *"issue create"*) echo 'https://github.com/acme/example-repo/issues/7777' ;;
  *"issue edit"*) : ;;
  *"label create"*) echo 'created' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
OVFAIL_OUT="$(DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag ov-fail --slug ov-fail --category ov-fail --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-corrupt.json" 2>"$TMP_MI/ov-fail.err")"; OVFAIL_RC=$?
assert_eq "meta-issue reports FILED on a cooldown-write failure (exit 0)" "true" \
  "$([ "$OVFAIL_RC" -eq 0 ] && echo true || echo false)"
assert_eq "meta-issue still prints the filed URL on a cooldown-write failure" "https://github.com/acme/example-repo/issues/7777" "$OVFAIL_OUT"
assert_eq "meta-issue leaves a 'WAS filed' breadcrumb on a cooldown-write failure" "true" \
  "$(grep -q 'issue WAS filed' "$TMP_MI/ov-fail.err" && echo true || echo false)"

# #152/#788: --dry-run must NOT mutate the real overrides.json — a dry run that
# records the DRYRUN sentinel as a lifecycle entry would make a later live run skip
# the real filing. The patterns map must stay empty after a dry run.
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov-dry.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --dry-run --tag dry-ov --slug dry-ov --category dry-ov --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-dry.json" >/dev/null 2>&1
assert_eq "meta-issue --dry-run writes NO lifecycle record to overrides" "false" \
  "$(jq -e '.patterns | has("dry-ov")' "$TMP_MI/ov-dry.json" >/dev/null 2>&1 && echo true || echo false)"

# #152: TAG carrying a GitHub search qualifier / whitespace is rejected at
# arg-parse (before it reaches the de-dupe --search), so a drift fails loud
# instead of mis-routing the lookup and re-filing a duplicate.
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag 'foo in:body' --slug foo --category foo --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-dry.json" >/dev/null 2>&1; BADTAG_RC=$?
assert_eq "meta-issue rejects a non-slug --tag (non-zero exit)" "true" \
  "$([ "$BADTAG_RC" -ne 0 ] && echo true || echo false)"
# #788: on a recurrence the Step-1 de-dupe hits the SAME open issue and re-runs the
# Step-2 write. The lifecycle entry is keyed by issue number, so the record must
# still hold exactly ONE meta-issue entry (no duplicate append that would exhaust
# max_open_per_category against one issue), and the record's `provenance` (first
# filing) must be PRESERVED rather than bumped forward.
printf '%s' '{"schema_version":3,"patterns":{"recur":{"category":"recur","state":"filed","fixed_at":null,"provenance":"2020-01-01T00:00:00Z","meta_issues":[{"number":55,"url":"https://github.com/acme/example-repo/issues/55","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$TMP_MI/ov-recur.json"
cat > "$TMP_MI/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[{"number":55,"url":"https://github.com/acme/example-repo/issues/55","title":"[devflow-retrospective] meta: recur — x"}]' ;;  # de-dup HIT
  *"issue comment"*) echo 'commented' ;;
  *"issues/"*"/labels"*) : ;;
  *"--method POST"*"/labels"*) echo '{}' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh"
DEVFLOW_GH="$TMP_MI/gh" bash "$LIB/meta-issue.sh" --tag recur --slug recur --category recur --title "x" --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-recur.json" >/dev/null 2>&1
assert_eq "meta-issue recurrence keeps exactly one number-keyed entry" "1" \
  "$(jq -r '.patterns["recur"].meta_issues | length' "$TMP_MI/ov-recur.json")"
assert_eq "meta-issue preserves the original provenance on a recurrence" "2020-01-01T00:00:00Z" \
  "$(jq -r '.patterns["recur"].provenance' "$TMP_MI/ov-recur.json")"
# The lifecycle write stages BESIDE the overrides file, never under $TMPDIR:
# `mv` is an atomic rename only within one filesystem, so a $TMPDIR staging file
# on a runner whose /tmp is a separate filesystem is a copy-then-unlink that can
# truncate overrides.json mid-write. (Same class, same destination, as
# pattern-state.sh's _atomic_write, which the $TMPDIR case above pins.)
#
# Discriminating power is platform-dependent and deliberately not overstated:
# an unusable $TMPDIR reverts this to a failed write only where a bare `mktemp`
# honours TMPDIR (GNU coreutils, i.e. CI), whereas macOS's `mktemp` resolves its
# own per-user temp dir and ignores it. So on CI this assertion goes RED against
# a $TMPDIR-staged write; at a macOS desk it holds the write's success as an
# ordinary regression guard on this path.
echo '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_MI/ov-tmpdir.json"
# Its own create-path stub: the shared $TMP_MI/gh above is rewritten by each
# preceding case, and the one left in effect is not the create path.
cat > "$TMP_MI/gh-create" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '' ;;
  *"issue create"*) echo 'https://github.com/acme/example-repo/issues/4242' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$TMP_MI/gh-create"
TMPDIR="$TMP_MI/no-such-tmpdir" DEVFLOW_GH="$TMP_MI/gh-create" bash "$LIB/meta-issue.sh" \
  --tag tmpdir-free --slug tmpdir-free --category tmpdir-free --title "audit(devflow): x" \
  --body-file "$TMP_MI/body.md" --overrides "$TMP_MI/ov-tmpdir.json" >/dev/null 2>&1
assert_eq "#788 meta-issue: the lifecycle record is written with an unusable \$TMPDIR" "filed" \
  "$(jq -r '.patterns["tmpdir-free"].state' "$TMP_MI/ov-tmpdir.json")"
assert_eq "#788 meta-issue: no staging file is left beside the overrides file" "0" \
  "$(set -- "$TMP_MI"/.overrides*; [ -e "$1" ] && echo 1 || echo 0)"
rm -rf "$TMP_MI"

# ────────────────────────────────────────────────────────────────────────────
# filing-decisions.sh — the executable owner of the Step 8c cap decision and of
# the three report fields whose producers were missing (issue #788).
# ────────────────────────────────────────────────────────────────────────────
# Sourced inside a subshell, like run.sh's render-report.sh blocks: a sourced
# file COMPLETING fires this module's own `trap ... RETURN`, which would delete
# $RL_TMP out from under every later assertion. `set +e` inside keeps the
# harness's own semantics so one failing command cannot silently skip the rest
# of the block. assert_eq records through $RESULTS_FILE, so a subshell's results
# still count.
#
# The helper itself sets NO shell options — deliberately, because the
# orchestrator sources it at top level and a leaked `set -euo pipefail` would
# abort the retrospective run on a later benign non-zero. That property is
# asserted below rather than relied on here.
(
set +e
# shellcheck source=../../filing-decisions.sh
. "$REPO_ROOT/lib/filing-decisions.sh"
set +e

# Cap arms, in the order the helper evaluates them. Each row drives ONE arm with
# every other cap slack, so a mis-ordered check changes exactly one expectation.
assert_eq "#788 caps: per-run cap withholds" "max_issues_per_run" \
  "$(devflow_filing_cap_verdict open 3 3 0 2 0 10)"
assert_eq "#788 caps: per-category cap withholds" "max_open_per_category" \
  "$(devflow_filing_cap_verdict open 0 3 2 2 0 10)"
assert_eq "#788 caps: total-open cap withholds a non-regressed pattern" "max_open_issues" \
  "$(devflow_filing_cap_verdict open 0 3 0 2 10 10)"
assert_eq "#788 caps: nothing withholds → file" "file" \
  "$(devflow_filing_cap_verdict open 0 3 0 2 0 10)"
# The regressed bypass, and its two limits: it bypasses max_open_issues ONLY.
assert_eq "#788 caps: regressed bypasses max_open_issues" "file" \
  "$(devflow_filing_cap_verdict regressed 0 3 0 2 10 10)"
assert_eq "#788 caps: regressed still honours max_issues_per_run" "max_issues_per_run" \
  "$(devflow_filing_cap_verdict regressed 3 3 0 2 0 10)"
assert_eq "#788 caps: regressed still honours max_open_per_category" "max_open_per_category" \
  "$(devflow_filing_cap_verdict regressed 0 3 2 2 0 10)"
# Arm ORDER: with the per-run cap AND the per-category cap both breached, the
# per-run cap must be the reported one. A swapped pair flips this value while
# every single-arm row above stays green.
assert_eq "#788 caps: per-run is evaluated before per-category" "max_issues_per_run" \
  "$(devflow_filing_cap_verdict open 3 3 2 2 0 10)"
assert_eq "#788 caps: per-category is evaluated before total-open" "max_open_per_category" \
  "$(devflow_filing_cap_verdict open 0 3 2 2 10 10)"
# Fail-closed: an underived count withholds rather than filing on unknown input.
assert_eq "#788 caps: empty count fails closed (withholds)" "invalid-operand" \
  "$(devflow_filing_cap_verdict open "" 3 0 2 0 10)"
assert_eq "#788 caps: non-numeric count fails closed (withholds)" "invalid-operand" \
  "$(devflow_filing_cap_verdict open abc 3 0 2 0 10)"
assert_eq "#788 caps: wrong argument count fails closed (withholds)" "invalid-operand" \
  "$(devflow_filing_cap_verdict open 0 3)"

# ── The cap COMPARANDS (issue #788) ──────────────────────────────────────────
# The two counts the verdict above compares are derived here, not by inline jq
# in the skill: a mis-shaped count decides whether an issue is filed, and inline
# jq in a prose surface is a decision the suite cannot catch defeated.
RL_CAPOV="$RL_TMP/capcounts.json"
printf '%s' '{"schema_version":2,"patterns":{"a":{"state":"filed","meta_issues":[{"number":1,"state":"filed"},{"number":2,"state":"filed"},{"number":3,"state":"fixed"}]},"b":{"state":"filed","meta_issues":[{"number":4,"state":"filed"}]},"c":{"state":"declined","meta_issues":[{"number":5,"state":"declined"}]}},"dismissed":{}}' > "$RL_CAPOV"
assert_eq "#788 counts: total open = filed entries across every record" "3" \
  "$(devflow_open_filed_total "$RL_CAPOV")"
assert_eq "#788 counts: a closed entry does not consume a cap slot" "1" \
  "$(devflow_open_filed_in_category "$RL_CAPOV" b)"
assert_eq "#788 counts: per-category counts only that record's filed entries" "2" \
  "$(devflow_open_filed_in_category "$RL_CAPOV" a)"
assert_eq "#788 counts: a record with no filed entry counts 0" "0" \
  "$(devflow_open_filed_in_category "$RL_CAPOV" c)"
assert_eq "#788 counts: a slug with no record at all counts 0" "0" \
  "$(devflow_open_filed_in_category "$RL_CAPOV" never-seen)"
# Fail CLOSED: an unestablished count is EMPTY, never 0. A laundered 0 would
# report an empty backlog and file straight past both caps.
printf '%s' 'not json at all' > "$RL_TMP/cap-malformed.json"
assert_eq "#788 counts: a malformed overrides file yields empty, not 0" "" \
  "$(devflow_open_filed_total "$RL_TMP/cap-malformed.json")"
assert_eq "#788 counts: an absent overrides file yields empty, not 0" "" \
  "$(devflow_open_filed_total "$RL_TMP/no-such-file.json")"
assert_eq "#788 counts: an absent file yields empty for the per-category count too" "" \
  "$(devflow_open_filed_in_category "$RL_TMP/no-such-file.json" a)"
# Composition: that empty count reaches the verdict as `invalid-operand`, so an
# underived backlog withholds instead of filing. This is the join the two
# helpers exist to make safe.
assert_eq "#788 counts: an underived total withholds at the verdict" "invalid-operand" \
  "$(devflow_filing_cap_verdict open 0 3 0 2 "$(devflow_open_filed_total "$RL_TMP/no-such-file.json")" 10)"
assert_eq "#788 counts: a derived total files when it is under the cap" "file" \
  "$(devflow_filing_cap_verdict open 0 3 0 2 "$(devflow_open_filed_total "$RL_CAPOV")" 10)"
assert_eq "#788 counts: a derived total withholds when it reaches the cap" "max_open_issues" \
  "$(devflow_filing_cap_verdict open 0 3 0 2 "$(devflow_open_filed_total "$RL_CAPOV")" 3)"

# ── The helper leaks no shell options into the shell that sources it ─────────
# Step 8c/9 source this file at TOP LEVEL so its functions persist. An earlier
# `set -euo pipefail` in it leaked into the orchestrator, where a later benign
# non-zero (a grep that matches nothing) would have aborted the whole run.
# Asserted at the observable surface — the caller's own shell state — rather
# than by grepping the source for the string.
for _rl_opt in errexit nounset pipefail; do
  assert_eq "#788 filing-decisions: sourcing leaks no ${_rl_opt} into the caller" "clean" \
    "$(bash -c ". '$REPO_ROOT/lib/filing-decisions.sh'; if [[ -o $_rl_opt ]]; then echo leaked; else echo clean; fi")"
done
# The consequence, at the surface that matters: a benign non-zero after sourcing
# does not abort the sourcing shell.
assert_eq "#788 filing-decisions: a benign non-zero after sourcing does not abort the caller" "survived" \
  "$(bash -c ". '$REPO_ROOT/lib/filing-decisions.sh'; false; echo survived")"

# Liveness capture: the `liveness:` line actionable-patterns.sh writes to stderr
# is what the report's liveness line renders from.
printf 'noise\n::warning::actionable-patterns: something\nliveness: 3 suppressed pattern(s) at/above min_occurrences, highest foo\n' > "$RL_TMP/live.err"
assert_eq "#788 liveness: the stderr line is extracted for the report" \
  "3 suppressed pattern(s) at/above min_occurrences, highest foo" \
  "$(devflow_liveness_warning "$RL_TMP/live.err")"
printf 'noise only\n::warning::unrelated\n' > "$RL_TMP/noliveness.err"
assert_eq "#788 liveness: a run that emitted none yields empty (section omitted)" "" \
  "$(devflow_liveness_warning "$RL_TMP/noliveness.err")"
assert_eq "#788 liveness: an absent capture file yields empty, not an abort" "" \
  "$(devflow_liveness_warning "$RL_TMP/does-not-exist.err")"

# Won't-fix re-raise: only a NOT_PLANNED closure qualifies. DUPLICATE is also a
# `declined` transition but records no won't-fix judgement to re-raise.
printf '%s' '{"schema_version":2,"patterns":{"np":{"state":"declined","meta_issues":[{"number":1,"state":"declined","state_reason":"NOT_PLANNED"}]},"dup":{"state":"declined","meta_issues":[{"number":2,"state":"declined","state_reason":"DUPLICATE"}]},"done":{"state":"fixed","meta_issues":[{"number":3,"state":"fixed","state_reason":"COMPLETED"}]}},"dismissed":{}}' > "$RL_TMP/refiled.json"
assert_eq "#788 re-raise: a NOT_PLANNED closure is named" '["np"]' \
  "$(devflow_declined_refiled "$RL_TMP/refiled.json" '["np","dup","done"]')"
assert_eq "#788 re-raise: a DUPLICATE closure is NOT named" '[]' \
  "$(devflow_declined_refiled "$RL_TMP/refiled.json" '["dup"]')"
assert_eq "#788 re-raise: a pattern not filed this run is not named" '[]' \
  "$(devflow_declined_refiled "$RL_TMP/refiled.json" '[]')"
assert_eq "#788 re-raise: an unreadable overrides file yields [] (section omitted)" '[]' \
  "$(devflow_declined_refiled "$RL_TMP/no-such-overrides.json" '["np"]')"
# ...but never SILENTLY: an empty section from a producer failure and one from a
# genuinely empty result read identically, and the won't-fix re-raise is the
# decision this design promises to surface rather than bury.
assert_eq "#788 re-raise: the unreadable-file degrade emits a breadcrumb" "true" \
  "$(devflow_declined_refiled "$RL_TMP/no-such-overrides.json" '["np"]' 2>&1 >/dev/null \
     | grep -q 'NOT evidence that nothing was re-raised' && echo true || echo false)"
# The readable-but-MALFORMED file takes the other degrade path (the jq abort),
# which the unreadable-file arm above never reaches.
printf '%s' '{"patterns": not json at all' > "$RL_TMP/refiled-bad.json"
assert_eq "#788 re-raise: a readable-but-malformed overrides file still yields []" '[]' \
  "$(devflow_declined_refiled "$RL_TMP/refiled-bad.json" '["np"]' 2>/dev/null)"
assert_eq "#788 re-raise: the malformed-file degrade emits its own breadcrumb" "true" \
  "$(devflow_declined_refiled "$RL_TMP/refiled-bad.json" '["np"]' 2>&1 >/dev/null \
     | grep -q 'could not derive the won' && echo true || echo false)"

# Per-pattern filing outcome / withheld_by on the unfiltered view.
printf '%s' '[{"tag":"filed-one","occurrence_count":5,"status":"regressed"},{"tag":"held","occurrence_count":2,"status":"open"},{"tag":"quiet","occurrence_count":1,"status":"open"}]' > "$RL_TMP/pfull.json"
RL_ANN="$(devflow_annotate_patterns "$RL_TMP/pfull.json" '["filed-one"]' '[{"tag":"held","cap":"max_open_issues"}]')"
assert_eq "#788 annotate: a filed pattern carries filing_outcome" "issue filed" \
  "$(printf '%s' "$RL_ANN" | jq -r '.[] | select(.tag=="filed-one") | .filing_outcome')"
assert_eq "#788 annotate: a withheld pattern carries the cap that withheld it" "max_open_issues" \
  "$(printf '%s' "$RL_ANN" | jq -r '.[] | select(.tag=="held") | .withheld_by')"
assert_eq "#788 annotate: a withheld pattern does not also say 'withheld' twice" "null" \
  "$(printf '%s' "$RL_ANN" | jq -r '.[] | select(.tag=="held") | .filing_outcome')"
assert_eq "#788 annotate: an untouched pattern still carries an outcome" "not filed" \
  "$(printf '%s' "$RL_ANN" | jq -r '.[] | select(.tag=="quiet") | .filing_outcome')"
# The pattern view is the report's SUBSTANCE, so — unlike the optional re-raise
# section above — its producer fails LOUD and prints NOTHING. Step 9 guards with
# `: "${PATTERNS_JSON:?…}"`, which tests for the empty string: a degrade to `[]`
# would sail through it, render_report would compute patterns_n = 0, and a
# producer failure would render as a genuinely quiet week — the exact misreading
# this issue exists to eliminate. Both failure arms are pinned.
assert_eq "#788 annotate: an unreadable pattern view prints NOTHING (not [])" "" \
  "$(devflow_annotate_patterns "$RL_TMP/no-such-pfull.json" '[]' '[]' 2>/dev/null)"
assert_eq "#788 annotate: the unreadable arm exits non-zero" "true" \
  "$(devflow_annotate_patterns "$RL_TMP/no-such-pfull.json" '[]' '[]' >/dev/null 2>&1; [ $? -ne 0 ] && echo true || echo false)"
assert_eq "#788 annotate: the unreadable arm names the quiet-week hazard" "true" \
  "$(devflow_annotate_patterns "$RL_TMP/no-such-pfull.json" '[]' '[]' 2>&1 >/dev/null \
     | grep -q 'quiet week' && echo true || echo false)"
printf '%s' '[{"tag":"x"' > "$RL_TMP/pfull-bad.json"
assert_eq "#788 annotate: a malformed pattern view prints NOTHING (not [])" "" \
  "$(devflow_annotate_patterns "$RL_TMP/pfull-bad.json" '[]' '[]' 2>/dev/null)"
assert_eq "#788 annotate: the malformed arm exits non-zero so the caller's :? fires" "true" \
  "$(devflow_annotate_patterns "$RL_TMP/pfull-bad.json" '[]' '[]' >/dev/null 2>&1; [ $? -ne 0 ] && echo true || echo false)"
# Control: the SAME guard shape on a well-formed view still yields a real array,
# so the two assertions above pin the failure arms and not a broken helper.
assert_eq "#788 annotate: a well-formed view still annotates (control)" "3" \
  "$(devflow_annotate_patterns "$RL_TMP/pfull.json" '["filed-one"]' '[]' | jq 'length')"
assert_eq "#788 annotate: every pattern in the view survives the join" "3" \
  "$(printf '%s' "$RL_ANN" | jq -r 'length')"

# ── End-to-end: a real Step-9 summary renders every section ──────────────────
# This is the assertion that would have caught the dead wiring: it drives
# render-report.sh from a summary built by the SAME producers Step 9 calls,
# rather than from a hand-built fixture that supplies the keys directly.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_SUM="$(jq -nc \
    --argjson patterns "$RL_ANN" \
    --arg liveness_warning "$(devflow_liveness_warning "$RL_TMP/live.err")" \
    --argjson declined_refiled "$(devflow_declined_refiled "$RL_TMP/refiled.json" '["np"]')" \
    --argjson withheld_patterns '[{"tag":"held","cap":"max_open_issues"}]' \
    '{prs_scanned:1,clean_count:0,analyzed_count:1,patterns:$patterns,
      liveness_warning:$liveness_warning,declined_refiled:$declined_refiled,
      withheld_patterns:$withheld_patterns}')"
  RL_OUT="$(devflow_render_report "$RL_SUM")"
  assert_eq "#788 e2e: the liveness section renders from the Step-6 capture" "true" \
    "$(case "$RL_OUT" in *"## Liveness warning"*"highest foo"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 e2e: the won't-fix re-raised section names the pattern" "true" \
    "$(case "$RL_OUT" in *"Won't-fix patterns re-raised this run"*'`np`'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 e2e: the per-pattern filing outcome renders inline" "true" \
    "$(case "$RL_OUT" in *'`filed-one`'*"issue filed"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 e2e: the per-pattern withholding cap renders inline" "true" \
    "$(case "$RL_OUT" in *'`held`'*"withheld by \`max_open_issues\`"*) echo true ;; *) echo false ;; esac)"
  # Negative control on the same shape: a summary whose producers yielded nothing
  # omits both optional sections, so the assertions above pin real content rather
  # than a section header that is always present.
  RL_EMPTY="$(devflow_render_report '{"prs_scanned":1,"patterns":[],"liveness_warning":"","declined_refiled":[]}')"
  assert_eq "#788 e2e: no liveness capture → the section is omitted" "false" \
    "$(case "$RL_EMPTY" in *"## Liveness warning"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 e2e: no re-raised pattern → the section is omitted" "false" \
    "$(case "$RL_EMPTY" in *"Won't-fix patterns re-raised"*) echo true ;; *) echo false ;; esac)"
)
)

# ── Remaining coverage gaps raised in review ────────────────────────────────
# state_reason is what distinguishes a won't-fix (NOT_PLANNED) from a duplicate
# closure downstream, so the reconciler must record it per entry, not just the
# `declined` state both closures share.
printf '%s' "$(rl_record np-reason 502)" > "$RL_TMP/sr1.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/sr1.json" >/dev/null 2>&1
assert_eq "#788 reconcile: a NOT_PLANNED entry records its state_reason" "NOT_PLANNED" \
  "$(jq -r '.patterns["np-reason"].meta_issues[0].state_reason' "$RL_TMP/sr1.json")"
printf '%s' "$(rl_record dup-reason 503)" > "$RL_TMP/sr2.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/sr2.json" >/dev/null 2>&1
assert_eq "#788 reconcile: a DUPLICATE entry records its own distinct state_reason" "DUPLICATE" \
  "$(jq -r '.patterns["dup-reason"].meta_issues[0].state_reason' "$RL_TMP/sr2.json")"
# An entry that reopens must not keep a stale closure reason: state_reason is
# cleared on the OPEN arm, so a later read cannot see a won't-fix that no longer
# holds.
printf '%s' '{"schema_version":2,"patterns":{"reopened":{"state":"declined","fixed_at":"2026-06-02T00:00:00Z","provenance":null,"meta_issues":[{"number":504,"url":"https://o/r/issues/504","state":"declined","closedAt":"2026-06-02T00:00:00Z","state_reason":"NOT_PLANNED"}]}},"dismissed":{}}' > "$RL_TMP/sr3.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/sr3.json" >/dev/null 2>&1
assert_eq "#788 reconcile: reopening an entry clears its stale state_reason" "null" \
  "$(jq -r '.patterns["reopened"].meta_issues[0].state_reason' "$RL_TMP/sr3.json")"

# Prefetch HIT path: every reconcile assertion above runs against a stub whose
# `issue list` returns [], so only the by-number fallback leg is exercised. This
# stub answers the prefetch instead and makes `issue view` FAIL, so a transition
# here can only have come from the prefetch — the primary leg, otherwise
# untested. (Attributing the leg is the point: without the failing `view`, a
# broken prefetch would silently fall back and the assertion would stay green.)
cat > "$RL_TMP/gh-prefetch.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  echo '[{"number":601,"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-06-11T00:00:00Z"},{"number":602,"state":"OPEN","stateReason":null,"closedAt":null}]'
  exit 0
fi
# The fallback leg must NOT be able to satisfy these — any transition below is
# attributable to the prefetch alone.
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then echo 'prefetch-test: view must not be reached' >&2; exit 1; fi
exit 1
STUB
chmod +x "$RL_TMP/gh-prefetch.sh"
printf '%s' "$(rl_record prefetch-closed 601)" > "$RL_TMP/pf1.json"
DEVFLOW_GH="$RL_TMP/gh-prefetch.sh" bash "$RL_PS" reconcile "$RL_TMP/pf1.json" >/dev/null 2>&1
assert_eq "#788 prefetch hit: a COMPLETED row transitions from the prefetch alone" "fixed" \
  "$(jq -r '.patterns["prefetch-closed"].state' "$RL_TMP/pf1.json")"
assert_eq "#788 prefetch hit: fixed_at comes from the prefetch row's closedAt" "2026-06-11T00:00:00Z" \
  "$(jq -r '.patterns["prefetch-closed"].fixed_at' "$RL_TMP/pf1.json")"
# Positive control on the same fixture+stub: a slug the prefetch page does NOT
# cover makes no transition here, because the fallback leg is unavailable. This
# is what proves the two assertions above were satisfied by the prefetch rather
# than by a permissive stub answering everything.
printf '%s' "$(rl_record prefetch-missing 999)" > "$RL_TMP/pf2.json"
DEVFLOW_GH="$RL_TMP/gh-prefetch.sh" bash "$RL_PS" reconcile "$RL_TMP/pf2.json" >/dev/null 2>&1
assert_eq "#788 prefetch miss + unavailable fallback → no transition (control)" "filed" \
  "$(jq -r '.patterns["prefetch-missing"].state' "$RL_TMP/pf2.json")"

# NOTE (deliberately untested): actionable-patterns.sh's `_ELIGIBLE_N` guard is
# defense-in-depth for a path that is UNREACHABLE through the script's own
# control flow — the `OUTPUT="$( ... )" || { ...; exit 1; }` assignment above it
# terminates the run when jq fails, and a jq that succeeds always prints an
# array, so `$OUTPUT` is never empty-with-rc-0 at that point. A test asserting
# the guard would be vacuous (verified: it stays green against a mutant that
# removes the guard entirely), so none is written here rather than banking a
# passing assertion that proves nothing. If a future edit makes `$OUTPUT`
# reachable while empty, that edit owns the test.

# ── First-run v2 stub, both writers (absent + empty overrides) ───────────────
# Two independent writers stub an absent/empty overrides file, and both must stub
# the v2 shape: a regression to the v1 literal (`{"schema_version":1,...}`, no
# `patterns` map) would leave the first run of a fresh consumer writing lifecycle
# entries into a file the migrator would later re-migrate.
rm -f "$RL_TMP/stub-absent.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag stubbed --slug stubbed --category stubbed --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/stub-absent.json" >/dev/null 2>&1
assert_eq "#891 first-run stub: meta-issue stubs an ABSENT overrides file at v3" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/stub-absent.json")"
assert_eq "#788 first-run stub: the meta-issue stub carries a patterns map (not the v1 shape)" "object" \
  "$(jq -r '.patterns | type' "$RL_TMP/stub-absent.json")"
: > "$RL_TMP/stub-empty.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag stubbed --slug stubbed --category stubbed --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/stub-empty.json" >/dev/null 2>&1
assert_eq "#891 first-run stub: meta-issue stubs an EMPTY overrides file at v3" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/stub-empty.json")"
assert_eq "#788 first-run stub: the empty-file stub carries a dismissed map" "object" \
  "$(jq -r '.dismissed | type' "$RL_TMP/stub-empty.json")"
# actionable-patterns.sh stubs into its OWN temp rather than the caller's path, so
# its stub is pinned behaviorally: whatever it writes must be indistinguishable
# from the canonical v2 empty file on the same input. (This discriminates any stub
# whose SHAPE changes the derivation; a differently-versioned stub that computes
# identically is outside what a behavioral pin can see, and is stated here rather
# than implied.)
printf '%s' '{"schema_version":2,"patterns":{},"dismissed":{}}' > "$RL_TMP/stub-canon.json"
RL_STUB_CANON="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/stub-canon.json" --full 2>/dev/null)"
rm -f "$RL_TMP/stub-none.json"
RL_STUB_ABSENT="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/stub-none.json" --full 2>/dev/null)"
: > "$RL_TMP/stub-zero.json"
RL_STUB_ZERO="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/stub-zero.json" --full 2>/dev/null)"
assert_eq "#788 first-run stub: actionable-patterns on an ABSENT overrides file matches the canonical v2 empty file" \
  "$RL_STUB_CANON" "$RL_STUB_ABSENT"
assert_eq "#788 first-run stub: actionable-patterns on an EMPTY overrides file matches the canonical v2 empty file" \
  "$RL_STUB_CANON" "$RL_STUB_ZERO"
# Positive control: that canonical output is non-empty, so the two equality
# assertions above compare real derivations rather than two empty strings.
assert_eq "#788 first-run stub: the compared canonical output is non-empty (control)" "true" \
  "$([ -n "$RL_STUB_CANON" ] && echo true || echo false)"

# ── OPEN arm wins over a contradictory stateReason ───────────────────────────
# GitHub can return a REOPENED issue that still carries the previous closure's
# `stateReason`/`closedAt`. The arm order (state == OPEN checked BEFORE any
# stateReason arm) is what makes such a row reopen rather than stay closed; a
# reordering would derive `declined` from the stale reason and suppress the
# pattern forever.
cat > "$RL_TMP/gh-contradict.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  echo '{"number":'"$3"',"state":"OPEN","stateReason":"NOT_PLANNED","closedAt":"2026-06-09T00:00:00Z"}'
  exit 0
fi
exit 1
STUB
chmod +x "$RL_TMP/gh-contradict.sh"
printf '%s' "$(rl_record contradictory 610)" > "$RL_TMP/contradict.json"
DEVFLOW_GH="$RL_TMP/gh-contradict.sh" bash "$RL_PS" reconcile "$RL_TMP/contradict.json" >/dev/null 2>&1
assert_eq "#788 arm order: state OPEN wins over a stale NOT_PLANNED stateReason" "filed" \
  "$(jq -r '.patterns["contradictory"].meta_issues[0].state' "$RL_TMP/contradict.json")"
assert_eq "#788 arm order: the OPEN arm clears the contradictory closedAt" "null" \
  "$(jq -r '.patterns["contradictory"].meta_issues[0].closedAt' "$RL_TMP/contradict.json")"
assert_eq "#788 arm order: the record derives filed, not declined" "filed" \
  "$(jq -r '.patterns["contradictory"].state' "$RL_TMP/contradict.json")"

# ── _atomic_write's write-failure arm names the destination ──────────────────
# Fault-injected via a PATH-shimmed `mv` that always fails: the staging file is
# created and filled, so this reaches the rename arm specifically (the mktemp arm
# would abort earlier and emit its own distinct message). The guarantee under
# test is the pair the AC states — a SPECIFIC ::error:: naming the path, and the
# previous file left byte-unchanged.
mkdir -p "$RL_TMP/shim"
printf '#!/usr/bin/env bash\nexit 1\n' > "$RL_TMP/shim/mv"
chmod +x "$RL_TMP/shim/mv"
printf '%s' "$(rl_record failwrite 501)" > "$RL_TMP/failwrite.json"
cp "$RL_TMP/failwrite.json" "$RL_TMP/failwrite-before.json"
PATH="$RL_TMP/shim:$PATH" DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile \
  "$RL_TMP/failwrite.json" >/dev/null 2>"$RL_TMP/failwrite.err"; RL_FW_RC=$?
assert_eq "#788 atomic write: a failed rename exits non-zero" "true" \
  "$([ "$RL_FW_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 atomic write: the ::error:: NAMES the destination path" "true" \
  "$(grep -q "failed to write ${RL_TMP}/failwrite.json" "$RL_TMP/failwrite.err" && echo true || echo false)"
assert_eq "#788 atomic write: the previous file is left byte-unchanged" "true" \
  "$(diff -q "$RL_TMP/failwrite-before.json" "$RL_TMP/failwrite.json" >/dev/null 2>&1 && echo true || echo false)"
# Control on the same fixture WITHOUT the shim: the reconcile does write, so the
# byte-unchanged assertion above pins the failure path and not an inert fixture.
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/failwrite.json" >/dev/null 2>&1
assert_eq "#788 atomic write: the same fixture DOES change without the failing mv (control)" "false" \
  "$(diff -q "$RL_TMP/failwrite-before.json" "$RL_TMP/failwrite.json" >/dev/null 2>&1 && echo true || echo false)"

# ── meta-issue: a failed rename still reports the issue as filed ─────────────
# Same shim, the other writer. The issue WAS created; aborting under `set -e`
# before Step 3 would report a real issue as unfiled — the one misstatement this
# loop must never make — so the rename is guarded and routes into the recovery
# branch, which exits 0 with the URL and an ::error:: naming the overrides file.
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/mv-fail.json"
RL_MVOUT="$(PATH="$RL_TMP/shim:$PATH" DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" \
  --tag mvfail --slug mvfail --category mvfail --title T --body-file "$RL_TMP/mi-body.md" \
  --overrides "$RL_TMP/mv-fail.json" 2>"$RL_TMP/mv-fail.err")"; RL_MV_RC=$?
assert_eq "#788 meta-issue: a failed record rename still exits 0" "0" "$RL_MV_RC"
assert_eq "#788 meta-issue: a failed record rename still prints the filed issue URL" "https://github.com/o/r/issues/777" "$RL_MVOUT"
assert_eq "#788 meta-issue: the failed record write reports 'issue WAS filed'" "true" \
  "$(grep -q 'issue WAS filed' "$RL_TMP/mv-fail.err" && echo true || echo false)"

# ── meta-issue: the in-place update clears stale closure fields ──────────────
# Re-filing against a still-open issue re-asserts "this entry is open", so the
# entry's closure fields must be cleared alongside `state:"filed"` — the same
# field set pattern-state.sh's OPEN transition writes. Left behind, a `filed`
# entry would carry a closure timestamp until a later reconcile happened to
# clear it, and any reader keying off those fields would see a closed entry.
printf '%s' '{"schema_version":3,"patterns":{"stale-close":{"category":"stale-close","state":"fixed","fixed_at":"2026-06-01T00:00:00Z","provenance":"p","meta_issues":[{"number":777,"url":"https://github.com/o/r/issues/777","state":"fixed","closedAt":"2026-06-01T00:00:00Z","fixed_at":"2026-06-01T00:00:00Z","state_reason":"COMPLETED"}]}},"dismissed":{}}' > "$RL_TMP/stale.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag stale-close --slug stale-close --category stale-close --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/stale.json" >/dev/null 2>&1
assert_eq "#788 meta-issue in-place: the re-filed entry is marked filed" "filed" \
  "$(jq -r '.patterns["stale-close"].meta_issues[0].state' "$RL_TMP/stale.json")"
assert_eq "#788 meta-issue in-place: the stale closedAt is cleared" "null" \
  "$(jq -r '.patterns["stale-close"].meta_issues[0].closedAt' "$RL_TMP/stale.json")"
assert_eq "#788 meta-issue in-place: the stale entry fixed_at is cleared" "null" \
  "$(jq -r '.patterns["stale-close"].meta_issues[0].fixed_at' "$RL_TMP/stale.json")"
assert_eq "#788 meta-issue in-place: the stale state_reason is cleared" "null" \
  "$(jq -r '.patterns["stale-close"].meta_issues[0].state_reason' "$RL_TMP/stale.json")"
assert_eq "#788 meta-issue in-place: the update did not append a duplicate entry" "1" \
  "$(jq -r '.patterns["stale-close"].meta_issues | length' "$RL_TMP/stale.json")"

# ── A failed label apply still consumes cap budget ───────────────────────────
# Label stamping is best-effort and must never abort a filing — but the converse
# matters just as much for the caps: the issue exists, so the lifecycle entry
# that the cap counts must still be written. A filing that silently wrote no
# record would leave the cap under-counting and the loop over-filing.
cat > "$RL_TMP/gh-nolabel.sh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[]' ;;
  *"issue create"*) echo 'https://github.com/o/r/issues/778' ;;
  *"issue comment"*) echo ok ;;
  *"/labels"*) echo 'label apply failed' >&2; exit 1 ;;
  *) echo '' ;;
esac
STUB
chmod +x "$RL_TMP/gh-nolabel.sh"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/nolabel.json"
DEVFLOW_GH="$RL_TMP/gh-nolabel.sh" bash "$RL_MI" --tag nolabel --slug nolabel --category nolabel --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/nolabel.json" >/dev/null 2>&1; RL_NL_RC=$?
assert_eq "#788 label failure: the filing still exits 0" "0" "$RL_NL_RC"
assert_eq "#788 label failure: the lifecycle entry the caps count is still written" "1" \
  "$(jq -r '.patterns["nolabel"].meta_issues | length' "$RL_TMP/nolabel.json")"
assert_eq "#788 label failure: that entry counts as filed against the caps" "filed" \
  "$(jq -r '.patterns["nolabel"].meta_issues[0].state' "$RL_TMP/nolabel.json")"

# ── A prefetch row no record references creates no phantom pattern ───────────
# The prefetch is a `--label Retrospective` page, so it returns rows for issues
# this file has no record of (another slug's issue, a hand-filed one). The
# reconciler must consume it as a LOOKUP TABLE keyed by the records it already
# holds — an implementation that iterated the prefetch instead would mint a
# patterns{} key per row, and compute-patterns.jq would surface each as a pattern.
printf '%s' "$(rl_record prefetch-closed 601)" > "$RL_TMP/phantom.json"
DEVFLOW_GH="$RL_TMP/gh-prefetch.sh" bash "$RL_PS" reconcile "$RL_TMP/phantom.json" >/dev/null 2>&1
assert_eq "#788 prefetch: an unreferenced row mints no patterns{} key" "1" \
  "$(jq -r '.patterns | length' "$RL_TMP/phantom.json")"
assert_eq "#788 prefetch: the only key is the one the record already held" "prefetch-closed" \
  "$(jq -r '.patterns | keys[0]' "$RL_TMP/phantom.json")"
# Control: row 602 IS in the prefetch page this run consumed, so its absence
# above is the reconciler declining to mint it, not a page that never named it.
assert_eq "#788 prefetch: the unreferenced row 602 is present in the fixture page (control)" "true" \
  "$("$RL_TMP/gh-prefetch.sh" issue list | jq 'any(.[]; .number==602)')"

# ── the derivation survives a malformed agent-written categories row ─────────
# retrospectives.jsonl is written by an LLM subagent, so a scalar `categories`
# or a non-string member is an ordinary slip. Unguarded it aborts the WHOLE
# weekly derivation over one row ("Cannot iterate over string" / "explode input
# must be a string"), losing every other pattern with it.
RL_CAT_ENTRIES='{"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":"not-an-array"}
{"kind":"implementation","pr":2,"merged_at":"2026-01-02T00:00:00Z","verdict":"imperfect","categories":[7,"good-tag"]}
{"kind":"implementation","pr":3,"merged_at":"2026-01-03T00:00:00Z","verdict":"imperfect","categories":["good-tag"]}'
RL_CAT_VIEW="$(rl_cp "$RL_CAT_ENTRIES" '{"schema_version":2,"patterns":{},"dismissed":{}}' 2>"$RL_TMP/cat.err")"; RL_CAT_RC=$?
assert_eq "#788 categories: a malformed row does not abort the derivation" "0" "$RL_CAT_RC"
assert_eq "#788 categories: the well-formed tag beside it is still derived" "2" \
  "$(printf '%s' "$RL_CAT_VIEW" | jq -r '.["good-tag"].occurrence_count // "MISSING"')"
assert_eq "#788 categories: the non-string member is dropped, not slugified" "false" \
  "$(printf '%s' "$RL_CAT_VIEW" | jq -r 'has("7")')"

# ── a non-string fixed_at cannot silently drive the regressed arm ────────────
# jq's `>` is a TOTAL order and never errors, so a hand-edited non-string
# fixed_at does not fail loudly — it decides the arm. `false` sorts below every
# timestamp and would force `regressed`; a non-date string can pin a pattern at
# `fixed` forever. Both must read as absent instead.
RL_FT_ENTRY='{"kind":"implementation","pr":9,"merged_at":"2026-02-01T00:00:00Z","verdict":"imperfect","categories":["ft"]}'
assert_eq "#788 fixed_at: a boolean fixed_at does not force 'regressed'" "fixed" \
  "$(rl_cp "$RL_FT_ENTRY" '{"schema_version":2,"dismissed":{},"patterns":{"ft":{"state":"fixed","fixed_at":false,"meta_issues":[]}}}' 2>/dev/null | jq -r '.ft.status')"
# Control on the same fixture: a REAL older timestamp does derive regressed, so
# the assertion above pins the type guard and not an arm that never fires.
assert_eq "#788 fixed_at: a real older timestamp DOES derive regressed (control)" "regressed" \
  "$(rl_cp "$RL_FT_ENTRY" '{"schema_version":2,"dismissed":{},"patterns":{"ft":{"state":"fixed","fixed_at":"2026-01-01T00:00:00Z","meta_issues":[]}}}' 2>/dev/null | jq -r '.ft.status')"

# ── meta-issue refuses to stamp v2 on an unmigrated v1 file ──────────────────
# The lifecycle write sets `.schema_version = 2` and performs NO v1 conversion.
# Stamping the version it did not perform is permanent silence via this PR's own
# writer: _migrate gates on `schema_version == 1`, so once the file claims v2 the
# migration never runs again and every loop-written v1 `dismissed{}` entry is
# frozen as a human-owned permanent suppression — the exact failure #788 exists
# to end. It must decline the record (taking the issue-WAS-filed recovery) rather
# than convert a file it is not the migrator for.
printf '%s' '{"schema_version":1,"dismissed":{"legacy-slug":{"dismissed_by":"retrospective-weekly","meta_issue":"https://github.com/o/r/issues/5"}}}' \
  > "$RL_TMP/mi-v1.json"
cp "$RL_TMP/mi-v1.json" "$RL_TMP/mi-v1-before.json"
RL_MIV1_OUT="$(DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag legacy-slug --slug legacy-slug --category legacy-slug \
  --title T --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi-v1.json" 2>"$RL_TMP/mi-v1.err")"; RL_MIV1_RC=$?
assert_eq "#788 meta-issue: a v1 overrides file still exits 0 (the issue WAS filed)" "0" "$RL_MIV1_RC"
assert_eq "#788 meta-issue: a v1 overrides file still prints the filed issue URL" "true" \
  "$(case "$RL_MIV1_OUT" in *"/issues/"*) echo true ;; *) echo false ;; esac)"
assert_eq "#891 meta-issue: it leaves the non-v3 file BYTE-unchanged, never stamped" "true" \
  "$(cmp -s "$RL_TMP/mi-v1.json" "$RL_TMP/mi-v1-before.json" && echo true || echo false)"
assert_eq "#788 meta-issue: the refusal names the unmigrated schema as the cause" "true" \
  "$(grep -q 'schema_version' "$RL_TMP/mi-v1.err" && echo true || echo false)"
# Control on the same invocation shape: a v3 file DOES get the lifecycle record,
# so the three assertions above pin the schema guard and not a broken fixture.
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/mi-v3.json"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag ok-slug --slug ok-slug --category ok-slug \
  --title T --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/mi-v3.json" >/dev/null 2>&1
assert_eq "#891 meta-issue: a v3 file still receives its lifecycle record (control)" "filed" \
  "$(jq -r '.patterns["ok-slug"].state // "MISSING"' "$RL_TMP/mi-v3.json")"

# ── the filing-volume cap keys, swept over the adversarial config-shape matrix ─
# CLAUDE.md's best-effort-parser rule governs every config value that turns into
# a decision, and these turn into the filing budget. The boundary that
# matters is COMPOSED — config-get.sh's coercion feeding devflow_filing_cap_verdict
# — so drive both together and assert the verdict token each shape produces.
# Two arms are silent-laundering RESIDUALS of config-get.sh's repo-wide coercion,
# not of this PR's code: they are pinned here (not fixed here) so the behaviour is
# visible and a future change to that coercion turns the desk RED instead of
# silently re-tuning the filing budget.
(
  . "$REPO_ROOT/lib/filing-decisions.sh"
  mkdir -p "$RL_TMP/cfg/.prflow"
  # rl_cap_token <json-value-for-max_issues_per_run> -> the verdict token
  # filed_this_run=0 against the resolved cap, every other operand slack, so the
  # token reflects the CAP's usability and nothing else.
  rl_cap_token() {
    printf '{"prflow_retrospective":{"max_issues_per_run":%s}}' "$1" > "$RL_TMP/cfg/.prflow/config.json"
    local cap
    # The fixture is selected by config-get.sh's THIRD POSITIONAL argument. A
    # `CONFIG_FILE=` env prefix is inert here — the script takes no such variable —
    # and reading as an explicit selection while the cwd silently did the selecting
    # is what makes an environment-shifted rerun mysterious.
    cap="$(cd "$RL_TMP/cfg" && \
             "$REPO_ROOT/scripts/config-get.sh" '.prflow_retrospective.max_issues_per_run' 3 .prflow/config.json 2>/dev/null)"
    devflow_filing_cap_verdict open 0 "$cap" 0 99 0 99 2>/dev/null
  }
  # scalar — the ordinary shape
  assert_eq "#788 cap-shape: a scalar cap is usable" "file" "$(rl_cap_token 3)"
  # valid-falsy 0 — the operator's legitimate "file nothing this run" off-switch.
  # It must survive as a real 0 (filed_this_run=0 >= 0 withholds), never be
  # laundered into the default 3.
  assert_eq "#788 cap-shape: an explicit 0 is a real off-switch, not the default" "max_issues_per_run" "$(rl_cap_token 0)"
  # valid-falsy false — coerces to the string "false", correctly unusable
  assert_eq "#788 cap-shape: a false cap is rejected, not treated as 0" "invalid-operand" "$(rl_cap_token false)"
  # object / multi-element array / non-numeric string — all correctly unusable
  assert_eq "#788 cap-shape: an object cap is rejected" "invalid-operand" "$(rl_cap_token '{}')"
  assert_eq "#788 cap-shape: a multi-element array cap is rejected" "invalid-operand" "$(rl_cap_token '[3,4]')"
  assert_eq "#788 cap-shape: a non-numeric string cap is rejected" "invalid-operand" "$(rl_cap_token '"abc"')"
  # missing / null — fall back to the declared default, which is usable
  printf '{"prflow_retrospective":{}}' > "$RL_TMP/cfg/.prflow/config.json"
  assert_eq "#788 cap-shape: a missing cap falls back to the default" "file" \
    "$(devflow_filing_cap_verdict open 0 "$(cd "$RL_TMP/cfg" && "$REPO_ROOT/scripts/config-get.sh" '.prflow_retrospective.max_issues_per_run' 3 .prflow/config.json 2>/dev/null)" 0 99 0 99 2>/dev/null)"
  assert_eq "#788 cap-shape: a null cap falls back to the default" "file" "$(rl_cap_token null)"
  # RESIDUALS (pinned, not fixed — config-get.sh coercion is repo-wide and out of
  # this PR's scope). Both launder a wrong-typed value into a REAL filing budget:
  assert_eq "#788 cap-shape RESIDUAL: a single-element array is laundered into that cap" "file" "$(rl_cap_token '[3]')"
  assert_eq "#788 cap-shape RESIDUAL: an explicit empty string falls back to the default" "file" "$(rl_cap_token '""')"
  # An unusable cap must NAME itself — a run that files nothing has to say why.
  RL_CAP_ERR="$(devflow_filing_cap_verdict open 0 '[object Object]' 0 99 0 99 2>&1 >/dev/null)"
  assert_eq "#788 cap-shape: the unusable cap breadcrumb names the operand" "true" \
    "$(case "$RL_CAP_ERR" in *"'max_issues_per_run' operand is not a non-negative integer"*) echo true ;; *) echo false ;; esac)"
)

# ── #894 audit_bundle_cap: validation, composed config boundary, selection ────
# The Stage B fetch bound. Validation and selection live in
# lib/audit-bundle-selection.sh (the skill fence resolves the cap via config-get.sh
# and passes it in). Drive the validator over every JSON shape the key can hold —
# both directly and COMPOSED with config-get.sh, since that is the boundary the
# skill fence actually exercises — and drive the selector for order and cardinality.
(
  # shellcheck source=../../audit-bundle-selection.sh
  . "$REPO_ROOT/lib/audit-bundle-selection.sh"
  mkdir -p "$RL_TMP/abc/.prflow"
  # rl_abc_raw <config-value> -> the config-get.sh-coerced string the fence passes.
  # The fixture is selected by config-get.sh's THIRD POSITIONAL argument (a
  # `CONFIG_FILE=` env prefix would be inert — the script reads no such variable).
  rl_abc_raw() {
    printf '{"prflow_retrospective":{"audit_bundle_cap":%s}}' "$1" > "$RL_TMP/abc/.prflow/config.json"
    (cd "$RL_TMP/abc" && \
       "$REPO_ROOT/scripts/config-get.sh" '.prflow_retrospective.audit_bundle_cap' 10 .prflow/config.json 2>/dev/null)
  }
  # rl_abc_token <config-value> -> "cap:<n>" when validated, "REJECT" when the
  # validator fails closed. Composes config-get.sh -> devflow_validate_audit_bundle_cap.
  rl_abc_token() {
    local raw v
    raw="$(rl_abc_raw "$1")"
    if v="$(devflow_validate_audit_bundle_cap "$raw" 2>/dev/null)"; then echo "cap:$v"; else echo "REJECT"; fi
  }
  # positive integer -> used as the cap
  assert_eq "#894 cap: a positive integer is the cap" "cap:5" "$(rl_abc_token 5)"
  # 0 / negative -> REJECT (deliberately unlike the filing caps where 0 is an off-switch)
  assert_eq "#894 cap: 0 is rejected (would starve Stage B), not an off-switch" "REJECT" "$(rl_abc_token 0)"
  assert_eq "#894 cap: a negative value is rejected" "REJECT" "$(rl_abc_token -3)"
  # boolean false/true, object, multi-array, non-numeric string, 3.5 -> REJECT
  assert_eq "#894 cap: a false cap is rejected" "REJECT" "$(rl_abc_token false)"
  assert_eq "#894 cap: a true cap is rejected (coerces to the string 'true')" "REJECT" "$(rl_abc_token true)"
  assert_eq "#894 cap: an object cap is rejected" "REJECT" "$(rl_abc_token '{}')"
  assert_eq "#894 cap: a multi-element array cap is rejected" "REJECT" "$(rl_abc_token '[3,4]')"
  assert_eq "#894 cap: a non-numeric string cap is rejected" "REJECT" "$(rl_abc_token '"abc"')"
  assert_eq "#894 cap: a non-integer number cap is rejected" "REJECT" "$(rl_abc_token 3.5)"
  # missing / null / empty-string / empty-array -> config-get resolves to the default 10
  rl_abc_missing() {
    printf '{"prflow_retrospective":{}}' > "$RL_TMP/abc/.prflow/config.json"
    local raw v
    raw="$(cd "$RL_TMP/abc" && "$REPO_ROOT/scripts/config-get.sh" '.prflow_retrospective.audit_bundle_cap' 10 .prflow/config.json 2>/dev/null)"
    if v="$(devflow_validate_audit_bundle_cap "$raw" 2>/dev/null)"; then echo "cap:$v"; else echo "REJECT"; fi
  }
  assert_eq "#894 cap: a missing key falls back to the default 10" "cap:10" "$(rl_abc_missing)"
  assert_eq "#894 cap: a null cap falls back to the default 10" "cap:10" "$(rl_abc_token null)"
  assert_eq "#894 cap: an explicit empty string falls back to the default 10" "cap:10" "$(rl_abc_token '""')"
  assert_eq "#894 cap: an empty array falls back to the default 10" "cap:10" "$(rl_abc_token '[]')"
  # RESIDUAL (pinned, not fixed — config-get.sh coercion is repo-wide): a
  # single-element array is laundered into that scalar cap, exactly like the filing caps.
  assert_eq "#894 cap RESIDUAL: a single-element array is laundered into that cap" "cap:3" "$(rl_abc_token '[3]')"
  # NUMERIC-STRING rows. A hand-written JSON *string* is coerced verbatim by
  # config-get.sh, so an all-digit string reaches the validator indistinguishable
  # from a real number. A canonical one is a legitimate cap; a LEADING-ZERO one is
  # not a canonical JSON integer literal (its `--argjson` meaning downstream is
  # parser-dependent: jq 1.7 coerces `08` to 8 while a strict parser rejects it),
  # so it fails CLOSED here rather than reaching the selector.
  assert_eq "#894 cap: a canonical numeric STRING is the cap" "cap:5" "$(rl_abc_token '"5"')"
  assert_eq "#894 cap: a leading-zero numeric string '08' is rejected" "REJECT" "$(rl_abc_token '"08"')"
  assert_eq "#894 cap: a leading-zero numeric string '007' is rejected" "REJECT" "$(rl_abc_token '"007"')"
  assert_eq "#894 cap: an all-zeros '00' is rejected" "REJECT" "$(rl_abc_token '"00"')"
  # Attribute each rejection to the guard that made it — a bare REJECT cannot tell
  # the leading-zero arm from the starvation arm ten lines away.
  RL_ABC_LZ_ERR="$(devflow_validate_audit_bundle_cap 007 2>&1 >/dev/null)"
  assert_eq "#894 cap: the leading-zero breadcrumb names the key and the canonical-literal reason" "true" \
    "$(case "$RL_ABC_LZ_ERR" in *".prflow_retrospective.audit_bundle_cap"*"no leading zero"*"canonical JSON integer literal"*) echo true ;; *) echo false ;; esac)"
  RL_ABC_00_ERR="$(devflow_validate_audit_bundle_cap 00 2>&1 >/dev/null)"
  assert_eq "#894 cap: an all-zeros value takes the STARVATION arm, not the leading-zero arm" "true" \
    "$(case "$RL_ABC_00_ERR" in *"starve Stage B"*) echo true ;; *) echo false ;; esac)"
  RL_ABC_NEG_ERR="$(devflow_validate_audit_bundle_cap "-1" 2>&1 >/dev/null || true)"
  assert_eq "#894 cap: a NEGATIVE takes the generic residual arm, not the starvation arm" "false" \
    "$(case "$RL_ABC_NEG_ERR" in *"starve Stage B"*) echo true ;; *) echo false ;; esac)"
  # ABSENT CONFIG FILE — the second cause the empty-read breadcrumb names, and the
  # one arm the two composed helpers above never reach (both write a config first).
  rl_abc_nofile() {
    local raw v
    rm -rf "$RL_TMP/abc-nofile"; mkdir -p "$RL_TMP/abc-nofile"
    raw="$(cd "$RL_TMP/abc-nofile" && "$REPO_ROOT/scripts/config-get.sh" '.prflow_retrospective.audit_bundle_cap' 10 .prflow/config.json 2>/dev/null)"
    if v="$(devflow_validate_audit_bundle_cap "$raw" 2>/dev/null)"; then echo "cap:$v"; else echo "REJECT"; fi
  }
  assert_eq "#894 cap: an ABSENT config file falls back to the default 10" "cap:10" "$(rl_abc_nofile)"
  # A JSON `[null]` — the array sibling of the null row, which config-get.sh
  # comma-joins to the empty string and so resolves to the default.
  assert_eq "#894 cap: a [null] cap falls back to the default 10" "cap:10" "$(rl_abc_token '[null]')"
  # An EMPTY resolver output (a read failure) is rejected, naming both causes.
  assert_eq "#894 cap: an empty resolver output is a read failure, rejected" "REJECT" \
    "$(if devflow_validate_audit_bundle_cap "" >/dev/null 2>&1; then echo "cap"; else echo REJECT; fi)"
  RL_ABC_ERR="$(devflow_validate_audit_bundle_cap "" 2>&1 >/dev/null)"
  assert_eq "#894 cap: the empty-read breadcrumb names both malformed-config and resolver-failure" "true" \
    "$(case "$RL_ABC_ERR" in *"malformed .prflow/config.json"*"resolver failure"*) echo true ;; *) echo false ;; esac)"
  RL_ABC_ZERO_ERR="$(devflow_validate_audit_bundle_cap 0 2>&1 >/dev/null)"
  assert_eq "#894 cap: the zero-cap breadcrumb names the key and the starvation reason" "true" \
    "$(case "$RL_ABC_ZERO_ERR" in *".prflow_retrospective.audit_bundle_cap"*"starve Stage B"*) echo true ;; *) echo false ;; esac)"

  # Selection: most-recent-first (occurrences[] arrives ascending by ts), and the
  # emitted ORDER is asserted, not just the set.
  #
  # rl_abs_join collapses the emitted lines with bash builtins rather than
  # `tr '\n' ' ' | sed 's/ $//'`. `tr`/`sed` are not preflight-guaranteed, and this
  # value IS the comparand the order assertion decides on: with either tool absent
  # the pipeline empties it, and while that fails CLOSED against a non-empty expected
  # literal, deriving a comparand through a non-preflight PATH tool is the shape
  # CLAUDE.md's guard-class 2 bars — in test code as much as in shipped code.
  rl_abs_join() {  # stdin -> the non-empty lines, space-joined
    local l out=""
    while IFS= read -r l; do
      [ -n "$l" ] || continue
      out="${out:+$out }$l"
    done
    printf '%s' "$out"
  }
  RL_ABC_PAT='{"occurrences":[{"pr":10,"ts":"2020-01-01"},{"pr":20,"ts":"2020-02-01"},{"pr":30,"ts":"2020-03-01"},{"pr":40,"ts":"2020-04-01"}]}'
  assert_eq "#894 select: the most-recent CAP prs, descending ts" "40 30" \
    "$(devflow_select_audit_bundles 2 "$RL_ABC_PAT" | rl_abs_join)"
  assert_eq "#894 select: cap >= occurrences returns all, still descending ts" "40 30 20 10" \
    "$(devflow_select_audit_bundles 10 "$RL_ABC_PAT" | rl_abs_join)"
  assert_eq "#894 select: an empty occurrences array selects nothing" "" \
    "$(devflow_select_audit_bundles 3 '{"occurrences":[]}')"
  assert_eq "#894 select: an absent occurrences key selects nothing" "" \
    "$(devflow_select_audit_bundles 3 '{}')"
  # A LEGITIMATE empty selection exits 0 — the positive control that makes the
  # failure rows below meaningful (a helper that always failed would pass them too).
  devflow_select_audit_bundles 3 '{"occurrences":[]}' >/dev/null 2>&1
  assert_eq "#894 select: a legitimate empty selection exits 0" "0" "$?"

  # FAILURE ARM (issue #894 fix pass). Empty stdout is a legitimate return, so a
  # silent failure would be indistinguishable from "this pattern has no
  # occurrences" — and the caller converts an empty selection into a blocker
  # blaming `gh`, misdiagnosing a config-/corpus-shape defect as a network failure.
  # Every bad-operand shape must therefore exit NON-ZERO with a breadcrumb that
  # ATTRIBUTES the rejection to the guard that made it, not merely fail.
  rl_abs_fail() {  # <cap> <pattern> -> "rc=<n> stdout=[<out>]"
    local out rc
    out="$(devflow_select_audit_bundles "$1" "$2" 2>/dev/null)"; rc=$?
    echo "rc=$rc stdout=[$out]"
  }
  assert_eq "#894 select FAIL: an empty pattern is a failure, not an empty selection" "rc=1 stdout=[]" \
    "$(rl_abs_fail 3 '')"
  assert_eq "#894 select FAIL: a present-but-non-array occurrences is a failure" "rc=1 stdout=[]" \
    "$(rl_abs_fail 3 '{"occurrences":{"a":1}}')"
  assert_eq "#894 select FAIL: a non-object pattern is a failure" "rc=1 stdout=[]" \
    "$(rl_abs_fail 3 '5')"
  assert_eq "#894 select FAIL: malformed JSON is a failure" "rc=1 stdout=[]" \
    "$(rl_abs_fail 3 '{"occurrences":')"
  # A non-canonical cap must be refused HERE too — the caller must pass the
  # validated cap, and `007` would otherwise reach `--argjson` where its meaning is
  # parser-dependent.
  assert_eq "#894 select FAIL: a leading-zero cap is refused by the selector too" "rc=1 stdout=[]" \
    "$(rl_abs_fail 007 "$RL_ABC_PAT")"
  assert_eq "#894 select FAIL: an empty cap is refused" "rc=1 stdout=[]" \
    "$(rl_abs_fail '' "$RL_ABC_PAT")"
  assert_eq "#894 select FAIL: a zero cap is refused" "rc=1 stdout=[]" \
    "$(rl_abs_fail 0 "$RL_ABC_PAT")"
  RL_ABS_ERR_EMPTY="$(devflow_select_audit_bundles 3 '' 2>&1 >/dev/null || true)"
  assert_eq "#894 select FAIL: the empty-pattern breadcrumb names the misreading it prevents" "true" \
    "$(case "$RL_ABS_ERR_EMPTY" in *"EMPTY pattern JSON"*"no occurrences"*) echo true ;; *) echo false ;; esac)"
  RL_ABS_ERR_SHAPE="$(devflow_select_audit_bundles 3 '{"occurrences":{"a":1}}' 2>&1 >/dev/null || true)"
  assert_eq "#894 select FAIL: the shape breadcrumb names the offending operand, not gh" "true" \
    "$(case "$RL_ABS_ERR_SHAPE" in *"occurrences is not an array"*) echo true ;; *) echo false ;; esac)"
  RL_ABS_ERR_CAP="$(devflow_select_audit_bundles 007 "$RL_ABC_PAT" 2>&1 >/dev/null || true)"
  assert_eq "#894 select FAIL: the cap breadcrumb names the validator as the source of a good cap" "true" \
    "$(case "$RL_ABS_ERR_CAP" in *"non-canonical cap"*"devflow_validate_audit_bundle_cap"*) echo true ;; *) echo false ;; esac)"

  # A malformed occurrence element is dropped BEFORE the most-recent-N slice, so it
  # neither reaches the caller as a phantom `pr-null` path nor consumes a cap slot
  # that would otherwise hold a real fetchable occurrence.
  RL_ABS_NULLPAT='{"occurrences":[{"pr":10,"ts":"2020-01-01"},{"pr":null,"ts":"2020-02-01"},{"ts":"2020-03-01"},{"pr":40,"ts":"2020-04-01"}]}'
  assert_eq "#894 select: a null/absent .pr never renders as a 'null' PR number" "false" \
    "$(case "$(devflow_select_audit_bundles 4 "$RL_ABS_NULLPAT")" in *null*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 select: a malformed element does not consume a cap slot" "40 10" \
    "$(devflow_select_audit_bundles 2 "$RL_ABS_NULLPAT" | rl_abs_join)"

  # ALL-ZEROS cap shapes. `00`/`000` are non-canonical exactly as `007` is, and the
  # selector's own guard must reject them with its ATTRIBUTED breadcrumb — not let
  # them reach `--argjson`, where jq's parse error surfaces under the GENERIC
  # "could not select occurrence PRs" wording and misattributes a config-shape
  # defect. An enumerated guard (`0*[1-9]*|0`) admitted exactly these two.
  assert_eq "#894 select FAIL: an all-zeros '00' cap is refused" "rc=1 stdout=[]" \
    "$(rl_abs_fail 00 "$RL_ABC_PAT")"
  assert_eq "#894 select FAIL: an all-zeros '000' cap is refused" "rc=1 stdout=[]" \
    "$(rl_abs_fail 000 "$RL_ABC_PAT")"
  RL_ABS_ERR_00="$(devflow_select_audit_bundles 00 "$RL_ABC_PAT" 2>&1 >/dev/null || true)"
  assert_eq "#894 select FAIL: '00' is ATTRIBUTED to the cap guard, not to a generic jq failure" "true" \
    "$(case "$RL_ABS_ERR_00" in *"non-canonical cap"*"devflow_validate_audit_bundle_cap"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 select FAIL: '00' does NOT surface the generic could-not-select breadcrumb" "false" \
    "$(case "$RL_ABS_ERR_00" in *"could not select occurrence PRs"*) echo true ;; *) echo false ;; esac)"

  # SUCCESS-PATH stderr contamination. The jq call merges stderr into the capture so
  # the failure arm can quote a diagnostic; on a ZERO exit any warning jq wrote is in
  # that capture too and would flow into the caller's `for n in $SELECTED_PRS` as a
  # phantom PR number. Drive it with a stub jq that exits 0 while writing a warning.
  cat > "$RL_TMP/jq-warn.sh" <<'RLJQW'
#!/usr/bin/env bash
echo "jq: warning: something looked odd" >&2
echo 42
exit 0
RLJQW
  chmod +x "$RL_TMP/jq-warn.sh"
  RL_ABS_WARN_RC="$(DEVFLOW_JQ="$RL_TMP/jq-warn.sh" devflow_select_audit_bundles 3 "$RL_ABC_PAT" >/dev/null 2>&1; echo $?)"
  assert_eq "#894 select: a zero-exit jq that also wrote to stderr fails CLOSED, not a phantom PR" "1" \
    "$RL_ABS_WARN_RC"
  RL_ABS_WARN_OUT="$(DEVFLOW_JQ="$RL_TMP/jq-warn.sh" devflow_select_audit_bundles 3 "$RL_ABC_PAT" 2>/dev/null || true)"
  assert_eq "#894 select: the contaminated line never reaches the caller as a selection" "" \
    "$RL_ABS_WARN_OUT"
  RL_ABS_WARN_ERR="$(DEVFLOW_JQ="$RL_TMP/jq-warn.sh" devflow_select_audit_bundles 3 "$RL_ABC_PAT" 2>&1 >/dev/null || true)"
  assert_eq "#894 select: the contamination breadcrumb names the phantom-PR risk it prevents" "true" \
    "$(case "$RL_ABS_WARN_ERR" in *"non-numeric output line"*"phantom occurrence PR"*) echo true ;; *) echo false ;; esac)"
  # POSITIVE CONTROL on the same stub shape: a stub that exits 0 and writes ONLY a
  # number is accepted, so the row above pins the contamination guard rather than
  # "any stub jq fails".
  cat > "$RL_TMP/jq-clean.sh" <<'RLJQC'
#!/usr/bin/env bash
echo 42
exit 0
RLJQC
  chmod +x "$RL_TMP/jq-clean.sh"
  assert_eq "#894 select CONTROL: a clean zero-exit stub is accepted (the guard is not 'all stubs fail')" "42" \
    "$(DEVFLOW_JQ="$RL_TMP/jq-clean.sh" devflow_select_audit_bundles 3 "$RL_ABC_PAT" 2>/dev/null || true)"

  # RESIDUAL ARM: a jq failure that writes NO diagnostic — the `${out:-…}` fallback,
  # which no other row reaches (every failure above comes from a real jq that does
  # write one).
  cat > "$RL_TMP/jq-silent.sh" <<'RLJQS'
#!/usr/bin/env bash
exit 3
RLJQS
  chmod +x "$RL_TMP/jq-silent.sh"
  RL_ABS_SILENT_ERR="$(DEVFLOW_JQ="$RL_TMP/jq-silent.sh" devflow_select_audit_bundles 3 "$RL_ABC_PAT" 2>&1 >/dev/null || true)"
  assert_eq "#894 select: a silent jq failure still names the absence of a diagnostic" "true" \
    "$(case "$RL_ABS_SILENT_ERR" in *"jq produced no diagnostic"*) echo true ;; *) echo false ;; esac)"

  # ── #894 the NO-DISPATCH FLOOR, the load-bearing safety property ────────────
  # devflow_audit_dispatch_ok is what stops an evidence-free GitHub issue being
  # filed for a pattern Stage B never saw a bundle for. It is a FUNCTION rather than
  # an inline `[ "$delivered" -eq 0 ]` precisely so this decision has an owner the
  # suite drives; the SKILL.md fence keys its `dispatch` carrier off it, and 8b/8c
  # dispatch and file only patterns whose carrier is still 1.
  rl_dispatch() {  # <delivered> -> "ok" | "excluded"
    if devflow_audit_dispatch_ok "$1" 2>/dev/null; then echo ok; else echo excluded; fi
  }
  assert_eq "#894 floor: one delivered bundle is enough to dispatch" "ok" "$(rl_dispatch 1)"
  assert_eq "#894 floor: many delivered bundles dispatch" "ok" "$(rl_dispatch 10)"
  assert_eq "#894 floor BOUNDARY: zero delivered is excluded from 8b/8c" "excluded" "$(rl_dispatch 0)"
  # Unknown is not zero, and it is also not evidence: an unestablished count fails
  # CLOSED (excluded), never dispatching on a count nobody established.
  assert_eq "#894 floor: an EMPTY delivered count fails closed, not open" "excluded" "$(rl_dispatch '')"
  assert_eq "#894 floor: a non-numeric delivered count fails closed" "excluded" "$(rl_dispatch 'x')"
  assert_eq "#894 floor: a negative delivered count fails closed" "excluded" "$(rl_dispatch '-1')"
  RL_DISPATCH_ERR="$(devflow_audit_dispatch_ok '' 2>&1 >/dev/null || true)"
  assert_eq "#894 floor: the unestablished-count breadcrumb names what it refuses to assume" "true" \
    "$(case "$RL_DISPATCH_ERR" in *"non-count delivered value"*"unestablished"*) echo true ;; *) echo false ;; esac)"
  # A legitimate exclusion writes NO ::error:: — the zero case is an ordinary
  # outcome, not a malfunction, so it must not pollute the run's error stream.
  RL_DISPATCH_ZERO_ERR="$(devflow_audit_dispatch_ok 0 2>&1 >/dev/null || true)"
  assert_eq "#894 floor: a legitimate zero-delivered exclusion emits no ::error::" "" \
    "$RL_DISPATCH_ZERO_ERR"

  # ── #894 resolve-jq.sh-not-sourceable arm (sibling precedent: render-report.sh) ─
  # A copied/vendored deployment without lib/ must fall back to a bare `jq` with a
  # breadcrumb rather than aborting the sourcing caller under set -e.
  rm -rf "$RL_TMP/abs-lone"; mkdir -p "$RL_TMP/abs-lone"
  cp "$REPO_ROOT/lib/audit-bundle-selection.sh" "$RL_TMP/abs-lone/audit-bundle-selection.sh"
  # `unset DEVFLOW_JQ` inside the child: an inherited value would satisfy the `:=`
  # fallback and make the row pass without the fallback ever running.
  RL_ABS_LONE_OUT="$(bash -c 'unset DEVFLOW_JQ; set -euo pipefail; . "$1/audit-bundle-selection.sh"; printf "%s" "${DEVFLOW_JQ:-EMPTY}"' _ "$RL_TMP/abs-lone" 2>"$RL_TMP/abs-lone.err")"
  assert_eq "#894 lone-deploy: sourcing without a resolve-jq.sh sibling still leaves DEVFLOW_JQ non-empty" "true" \
    "$(case "$RL_ABS_LONE_OUT" in ''|EMPTY) echo false ;; *) echo true ;; esac)"
  RL_ABS_LONE_ERR="$(<"$RL_TMP/abs-lone.err")"
  assert_eq "#894 lone-deploy: the fallback leaves a breadcrumb naming the override" "true" \
    "$(case "$RL_ABS_LONE_ERR" in *"resolve-jq.sh could not be sourced"*"DEVFLOW_JQ"*) echo true ;; *) echo false ;; esac)"

  # ── #894 the `blockers` slurp SHAPE, a repaired latent run-killer ────────────
  # Every `blockers+=(…)` append in Step 9's producer is RAW PROSE, so the array must
  # be slurped with the raw `-sRc split` shape, never the JSON `-sc '.'` one. Under
  # `-sc '.'` a prose element is a jq PARSE ERROR: blockers.json is left empty by the
  # already-truncating `> file` redirect, the Step 9 empty-file guard fires, and the
  # run aborts having lost every blocker. Step 8a makes that path frequently reached,
  # so a silent revert to `-sc '.'` reinstates a run-killer on ordinary runs. Drive
  # BOTH shapes over the same realistic prose element: the old one must fail, the
  # shipped one must round-trip.
  RL_BLK_PROSE='Pattern x: occurrence PR #7 bundle could not be fetched — gh: not logged in — excluded from Stage B evidence'
  RL_BLK_OLD_RC="$(printf '%s\n' "$RL_BLK_PROSE" | "${DEVFLOW_JQ:-jq}" -sc '.' >/dev/null 2>&1; echo $?)"
  assert_eq "#894 blockers: the OLD -sc '.' slurp really does fail on a prose element (the defect)" "false" \
    "$(case "$RL_BLK_OLD_RC" in 0) echo true ;; *) echo false ;; esac)"
  RL_BLK_NEW="$(printf '%s\n' "$RL_BLK_PROSE" | "${DEVFLOW_JQ:-jq}" -sRc 'split("\n") | map(select(. != ""))' 2>/dev/null || true)"
  assert_eq "#894 blockers: the shipped raw slurp round-trips the prose element verbatim" "true" \
    "$(case "$RL_BLK_NEW" in '["Pattern x: occurrence PR #7 bundle could not be fetched — gh: not logged in — excluded from Stage B evidence"]') echo true ;; *) echo false ;; esac)"
  # The empty-array case both shapes must agree on: `[]`, never empty output — an
  # empty file is what trips Step 9's guard.
  assert_eq "#894 blockers: an empty blockers array still slurps to a non-empty []" "[]" \
    "$(printf '%s\n' "" | "${DEVFLOW_JQ:-jq}" -sRc 'split("\n") | map(select(. != ""))' 2>/dev/null || true)"
)

# ── #894 render-report: Regressed patterns, Filing queue, truncation sections ─
(
  . "$REPO_ROOT/lib/render-report.sh"
  # Regressed patterns — derived from .patterns where status==regressed, with the
  # cumulative-state body and the omit-when-none idiom.
  RL_REG="$(devflow_render_report '{"prs_scanned":1,"patterns":[{"tag":"reg-a","occurrence_count":4,"status":"regressed","category":"tooling-gap"},{"tag":"open-b","occurrence_count":1,"status":"open"}]}')"
  assert_eq "#894 regressed: the section lists a regressed pattern" "true" \
    "$(case "$RL_REG" in *"## Regressed patterns"*'`reg-a`'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 regressed: the body states the state is cumulative" "true" \
    "$(case "$RL_REG" in *"## Regressed patterns"*"cumulative"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 regressed: a non-regressed pattern is not listed under it" "false" \
    "$(case "$RL_REG" in *"## Regressed patterns"*'`open-b`'*) echo true ;; *) echo false ;; esac)"
  RL_NOREG="$(devflow_render_report '{"prs_scanned":1,"patterns":[{"tag":"open-b","occurrence_count":1,"status":"open"}]}')"
  assert_eq "#894 regressed: the section is omitted when nothing is regressed" "false" \
    "$(case "$RL_NOREG" in *"## Regressed patterns"*) echo true ;; *) echo false ;; esac)"

  # Filing queue — N/M, at-capacity, unavailable, one-key, neither-key.
  RL_FQ="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"12","filing_queue_max":"10"}')"
  assert_eq "#894 queue: renders N/M with the at-capacity suffix when N>=M" "true" \
    "$(case "$RL_FQ" in *"## Filing queue"*"filing queue: 12/10 open — at capacity"*) echo true ;; *) echo false ;; esac)"
  RL_FQ2="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"3","filing_queue_max":"10"}')"
  assert_eq "#894 queue: no capacity suffix when N<M" "true" \
    "$(case "$RL_FQ2" in *"filing queue: 3/10 open"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 queue: N<M carries no ' — at capacity'" "false" \
    "$(case "$RL_FQ2" in *"at capacity"*) echo true ;; *) echo false ;; esac)"
  RL_FQZ="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"0","filing_queue_max":"10"}')"
  assert_eq "#894 queue: an established 0 renders 0, not unavailable" "true" \
    "$(case "$RL_FQZ" in *"filing queue: 0/10 open"*) echo true ;; *) echo false ;; esac)"
  RL_FQU="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"","filing_queue_max":"10"}')"
  assert_eq "#894 queue: an unestablished N renders 'unavailable', never 0" "true" \
    "$(case "$RL_FQU" in *"filing queue: unavailable/10 open"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 queue: an unestablished operand yields no capacity suffix" "false" \
    "$(case "$RL_FQU" in *"at capacity"*) echo true ;; *) echo false ;; esac)"
  RL_FQ1="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"5"}')"
  assert_eq "#894 queue: exactly one operand key present still renders the line" "true" \
    "$(case "$RL_FQ1" in *"## Filing queue"*"filing queue: 5/unavailable open"*) echo true ;; *) echo false ;; esac)"
  RL_FQ0="$(devflow_render_report '{"prs_scanned":1,"patterns":[]}')"
  assert_eq "#894 queue: omitted only when NEITHER operand key is present (old summary)" "false" \
    "$(case "$RL_FQ0" in *"## Filing queue"*) echo true ;; *) echo false ;; esac)"

  # Truncation section — delivered/total, the fetch-failure gap named separately,
  # and the omit-when-none idiom.
  RL_TR="$(devflow_render_report '{"prs_scanned":1,"truncations":[{"tag":"tg-x","delivered":8,"total":40,"selected":10}]}')"
  assert_eq "#894 truncation: the section names delivered-of-total" "true" \
    "$(case "$RL_TR" in *"Stage B evidence truncated"*'`tg-x`'*"received 8 of 40"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 truncation: names the fetch-failure gap when delivered<selected" "true" \
    "$(case "$RL_TR" in *"2 selected bundle(s) failed to fetch"*) echo true ;; *) echo false ;; esac)"
  RL_TR2="$(devflow_render_report '{"prs_scanned":1,"truncations":[{"tag":"tg-y","delivered":10,"total":40,"selected":10}]}')"
  assert_eq "#894 truncation: no fetch-failure clause when delivered==selected" "false" \
    "$(case "$RL_TR2" in *"failed to fetch"*) echo true ;; *) echo false ;; esac)"
  RL_TR0="$(devflow_render_report '{"prs_scanned":1,"patterns":[]}')"
  assert_eq "#894 truncation: the section is omitted when nothing was truncated" "false" \
    "$(case "$RL_TR0" in *"Stage B evidence truncated"*) echo true ;; *) echo false ;; esac)"

  # The at-capacity BOUNDARY N == M — the definitional case `-ge` exists for.
  # Without it, mutating `-ge` to `-gt` leaves the suite green while the report
  # stops warning exactly when the queue fills.
  RL_FQEQ="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"10","filing_queue_max":"10"}')"
  assert_eq "#894 queue BOUNDARY: N == M is at capacity" "true" \
    "$(case "$RL_FQEQ" in *"filing queue: 10/10 open — at capacity"*) echo true ;; *) echo false ;; esac)"
  RL_FQLT="$(devflow_render_report '{"prs_scanned":1,"filing_queue_open":"9","filing_queue_max":"10"}')"
  assert_eq "#894 queue BOUNDARY: N == M-1 is NOT at capacity (the negative control)" "false" \
    "$(case "$RL_FQLT" in *"at capacity"*) echo true ;; *) echo false ;; esac)"

  # `delivered == 0` — the shape the new no-dispatch path produces, and the one a
  # reader most needs to read correctly; plus `delivered == total` and a
  # `selected`-absent entry, neither of which any row above drives.
  RL_TRZ="$(devflow_render_report '{"prs_scanned":1,"truncations":[{"tag":"tg-z","delivered":0,"total":40,"selected":10}]}')"
  assert_eq "#894 truncation: delivered == 0 renders received-0-of-total plus the full fetch-failure gap" "true" \
    "$(case "$RL_TRZ" in *"received 0 of 40 occurrence bundles (10 selected bundle(s) failed to fetch)"*) echo true ;; *) echo false ;; esac)"
  RL_TRE="$(devflow_render_report '{"prs_scanned":1,"truncations":[{"tag":"tg-e","delivered":40,"total":40,"selected":40}]}')"
  assert_eq "#894 truncation: delivered == total still renders its row (the producer gates the entry, not the renderer)" "true" \
    "$(case "$RL_TRE" in *'`tg-e`'*"received 40 of 40"*) echo true ;; *) echo false ;; esac)"
  RL_TRNS="$(devflow_render_report '{"prs_scanned":1,"truncations":[{"tag":"tg-n","delivered":3,"total":9}]}')"
  assert_eq "#894 truncation: an absent 'selected' degrades to 0, so no fetch-failure clause is invented" "false" \
    "$(case "$RL_TRNS" in *"failed to fetch"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 truncation: an absent 'selected' still renders delivered-of-total" "true" \
    "$(case "$RL_TRNS" in *'`tg-n`'*"received 3 of 9"*) echo true ;; *) echo false ;; esac)"

  # MALFORMED-CONTAINER / MALFORMED-ELEMENT matrix for the new sections. The
  # renderer's comments claim these degrade rather than abort; lib/render-report.sh
  # sets `set -euo pipefail` at FILE SCOPE, so under a caller that inherits it an
  # unguarded probe aborts the render MID-REPORT, silently dropping every later
  # section. Each row therefore asserts a LATER section still renders — the
  # observable a mid-report abort destroys.
  #
  # The render MUST run in a fresh bash that sources the file, so the file-scope
  # `set -e` is live: this module's own shell runs with `set +e`, where an aborting
  # probe merely yields an empty section and every row would pass vacuously against
  # a de-guarded renderer. Verified by mutation: removing a probe's
  # `2>/dev/null || true` turns these rows RED only in the fresh-bash form.
  rl_rr_out() {  # <summary-json> -> the report a fresh set -e bash produced ("" on abort)
    bash -c '. "$1/render-report.sh"; devflow_render_report "$2"' _ "$REPO_ROOT/lib" "$1" 2>/dev/null || true
  }
  rl_rr_survives() {  # <summary-json> -> true when the report reached "Issues filed"
    local out
    out="$(rl_rr_out "$1")"
    case "$out" in *"## Issues filed"*) echo true ;; *) echo false ;; esac
  }
  assert_eq "#894 malformed: a non-array .patterns does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"patterns":"nope"}')"
  assert_eq "#894 malformed: a scalar element inside .patterns does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"patterns":[7,{"tag":"ok","occurrence_count":1,"status":"regressed"}]}')"
  assert_eq "#894 malformed: a non-string .status does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"patterns":[{"tag":"ok","occurrence_count":1,"status":{"x":1}}]}')"
  assert_eq "#894 malformed: a non-array .truncations does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"truncations":"nope"}')"
  assert_eq "#894 malformed: a scalar element inside .truncations does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"truncations":[7,{"tag":"ok","delivered":1,"total":2,"selected":1}]}')"
  assert_eq "#894 malformed: a non-string .tag inside .truncations does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"truncations":[{"tag":{"x":1},"delivered":1,"total":2,"selected":1}]}')"
  assert_eq "#894 malformed: non-numeric truncation counts do not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"truncations":[{"tag":"ok","delivered":"a","total":[2],"selected":null}]}')"
  assert_eq "#894 malformed: a null .truncations does not abort the render" "true" \
    "$(rl_rr_survives '{"prs_scanned":1,"truncations":null}')"

  # PRODUCER <-> RENDERER FIELD COUPLING. The Step 8a producer writes exactly
  # {tag, delivered, total, selected}; the renderer reads those four names. A rename
  # on either side is silent — the section keeps rendering, just with a degraded
  # value — so pin each name by driving an entry where ONLY that key is renamed and
  # asserting the observable it feeds disappears.
  assert_eq "#894 coupling: renaming 'selected' silently kills the fetch-failure clause" "false" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"truncations":[{"tag":"cp","delivered":2,"total":9,"selected_count":8}]}')" in *"failed to fetch"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 coupling: the same entry WITH 'selected' does render the clause (positive control)" "true" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"truncations":[{"tag":"cp","delivered":2,"total":9,"selected":8}]}')" in *"6 selected bundle(s) failed to fetch"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 coupling: renaming 'delivered' degrades the delivered count to 0" "true" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"truncations":[{"tag":"cp","delivered_count":2,"total":9,"selected":2}]}')" in *"received 0 of 9"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 coupling: renaming 'total' degrades the total to 0" "true" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"truncations":[{"tag":"cp","delivered":2,"occurrence_total":9,"selected":2}]}')" in *"received 2 of 0"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 coupling: renaming 'tag' falls back to (unnamed) rather than dropping the row" "true" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"truncations":[{"pattern":"cp","delivered":2,"total":9,"selected":2}]}')" in *'`(unnamed)`'*"received 2 of 9"*) echo true ;; *) echo false ;; esac)"
  # These two rows go through the FRESH-BASH helper like every sibling above. Called
  # directly under `|| true`, bash suspends errexit for the whole call, so `set -e`
  # is inert and the rows would pass against a de-guarded renderer — vacuous by this
  # block's own stated criterion.
  RL_FQNS="$(rl_rr_out '{"prs_scanned":1,"filing_queue_open":{"a":1},"filing_queue_max":[2]}')"
  assert_eq "#894 malformed: non-string filing-queue operands render unavailable, not an abort" "true" \
    "$(case "$RL_FQNS" in *"filing queue: unavailable/unavailable open"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 malformed: an at-capacity comparison is never attempted on a non-numeric operand" "false" \
    "$(case "$RL_FQNS" in *"at capacity"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 malformed: non-string filing-queue operands do not abort the render mid-report" "true" \
    "$(case "$RL_FQNS" in *"## Issues filed"*) echo true ;; *) echo false ;; esac)"

  # LEADING-ZERO filing-queue operands. `"max_open_issues": "08"` is hand-writable
  # and config-get.sh passes a JSON string through verbatim, so `08` reaches the
  # renderer. `test` evaluates numeric operands under shell arithmetic, where `08`
  # is an illegal octal literal: an all-digit-only guard admits it, `[ 9 -ge 08 ]`
  # writes `value too great for base` and returns non-true, and ` — at capacity`
  # is silently SUPPRESSED on a queue that is at capacity.
  RL_FQLZ="$(rl_rr_out '{"prs_scanned":1,"filing_queue_open":"08","filing_queue_max":"10"}')"
  assert_eq "#894 queue: a leading-zero N is unestablished, not a laundered octal" "true" \
    "$(case "$RL_FQLZ" in *"filing queue: unavailable/10 open"*) echo true ;; *) echo false ;; esac)"
  RL_FQLZM="$(rl_rr_out '{"prs_scanned":1,"filing_queue_open":"12","filing_queue_max":"08"}')"
  assert_eq "#894 queue: a leading-zero M is unestablished, not a laundered octal" "true" \
    "$(case "$RL_FQLZM" in *"filing queue: 12/unavailable open"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 queue: a leading-zero operand yields no at-capacity claim either way" "false" \
    "$(case "${RL_FQLZ}${RL_FQLZM}" in *"at capacity"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 queue: a leading-zero operand does not abort the render" "true" \
    "$(case "$RL_FQLZ" in *"## Issues filed"*) echo true ;; *) echo false ;; esac)"
  # A bare `0` is still established — the guard rejects a leading zero, not zero.
  assert_eq "#894 queue: a bare 0 is still an established count, not collapsed with '08'" "true" \
    "$(case "$(rl_rr_out '{"prs_scanned":1,"filing_queue_open":"0","filing_queue_max":"10"}')" in *"filing queue: 0/10 open"*) echo true ;; *) echo false ;; esac)"

  # The at-capacity line reports STATE, and `max_open_issues` is not absolute:
  # lib/filing-decisions.sh lets a `regressed` pattern bypass it. Without the note a
  # reader takes ` — at capacity` as "nothing was filed".
  assert_eq "#894 queue: at capacity names the regressed bypass, so the ceiling is not read as absolute" "true" \
    "$(case "$RL_FQEQ" in *"at capacity"*"regressed"*"bypasses this ceiling"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#894 queue: the bypass note is absent when the queue is NOT at capacity" "false" \
    "$(case "$RL_FQ2" in *"bypasses this ceiling"*) echo true ;; *) echo false ;; esac)"
  # NOTE on the ONE malformed shape deliberately NOT driven here: a valid-JSON
  # NON-OBJECT summary (`[]`), where jq's `has()` is undefined. It is unreachable at
  # the Filing-queue probe — the PRE-EXISTING `.prs_scanned` probe near the top of
  # devflow_render_report aborts first on that input (`Cannot index array with
  # string "prs_scanned"`), so no assertion here can distinguish a guarded
  # Filing-queue probe from an unguarded one. The type test and the degrade guard on
  # that probe are kept for consistency with every sibling probe in the function —
  # not because this input can reach them — and that limit is stated rather than
  # covered by a row that would pass either way.
)

# ── the cap comparands survive ONE malformed lifecycle record ────────────────
# overrides.json is hand-editable, and compute-patterns.jq/_migrate were both
# explicitly hardened against a non-object record. These two readers of the SAME
# file were not: `(.patterns // {})[] | (.meta_issues // [])[]` aborts jq on a
# scalar record ("Cannot index string with meta_issues"), the helper prints
# nothing, and devflow_filing_cap_verdict then returns invalid-operand for EVERY
# pattern — a run that files nothing, which is the #788 failure mode.
# A malformed shape must reach the fail-CLOSED arm (print nothing), never be
# filtered away into a real `0`. 0 is a USABLE count: it satisfies the caller's
# numeric guard, reports an empty backlog, and files right past BOTH caps — the
# unknown-laundered-as-zero failure the helper's own docstring forbids. Every row
# below asserts empty output AND the composed invalid-operand verdict, because
# the token is what the run actually acts on.
(
  . "$REPO_ROOT/lib/filing-decisions.sh"
  printf '%s' '{"schema_version":2,"dismissed":{},"patterns":{"good":{"state":"filed","meta_issues":[{"number":1,"state":"filed"},{"number":2,"state":"fixed"}]}}}' \
    > "$RL_TMP/caps-ok.json"
  # Positive control FIRST, on the well-formed fixture every row below corrupts:
  # a real count is derived and the verdict files, so each rejection that follows
  # pins the shape guard rather than an inert fixture.
  assert_eq "#788 caps: the well-formed fixture derives a real total (control)" "1" \
    "$(devflow_open_filed_total "$RL_TMP/caps-ok.json" 2>/dev/null)"
  assert_eq "#788 caps: the well-formed fixture derives a real per-category count (control)" "1" \
    "$(devflow_open_filed_in_category "$RL_TMP/caps-ok.json" good 2>/dev/null)"
  assert_eq "#788 caps: the control fixture's verdict is 'file', not a withhold" "file" \
    "$(devflow_filing_cap_verdict open 0 3 "$(devflow_open_filed_in_category "$RL_TMP/caps-ok.json" good 2>/dev/null)" 9 "$(devflow_open_filed_total "$RL_TMP/caps-ok.json" 2>/dev/null)" 9 2>/dev/null)"
  # rl_caps_closed <label> <patterns-json-value> — every malformed map/record/entry
  # shape must yield EMPTY from both helpers and invalid-operand from the verdict.
  rl_caps_closed() {
    printf '{"schema_version":2,"dismissed":{},"patterns":%s}' "$2" > "$RL_TMP/caps-bad.json"
    assert_eq "#788 caps: $1 unestablishes the total (empty, never 0)" "" \
      "$(devflow_open_filed_total "$RL_TMP/caps-bad.json" 2>/dev/null)"
    assert_eq "#788 caps: $1 composes to invalid-operand, so nothing files" "invalid-operand" \
      "$(devflow_filing_cap_verdict open 0 3 0 9 "$(devflow_open_filed_total "$RL_TMP/caps-bad.json" 2>/dev/null)" 9 2>/dev/null)"
  }
  # The map itself: the two rows CLAUDE.md's six-shape matrix requires and the
  # shadow pass found missing (a truthy non-object is NOT replaced by `// {}`).
  rl_caps_closed "an ARRAY patterns map" '[{"a":1}]'
  rl_caps_closed "a STRING patterns map" '"oops"'
  # A record, and a record's entry list, at the queried depth.
  rl_caps_closed "a non-object record" '{"good":"not-an-object"}'
  rl_caps_closed "a non-array meta_issues" '{"good":{"meta_issues":"nope"}}'
  rl_caps_closed "a non-object meta_issues entry" '{"good":{"meta_issues":["nope"]}}'
  # The per-category reader indexes ONE slug, so it must be corrupted AT that slug
  # to be exercised at all — a malformed SIBLING is never visited and would make
  # the assertion a tautology (the shadow pass proved that mutant survives).
  printf '%s' '{"schema_version":2,"dismissed":{},"patterns":{"good":"not-an-object","other":{"meta_issues":[]}}}' > "$RL_TMP/caps-cat.json"
  assert_eq "#788 caps: a malformed record AT THE QUERIED SLUG unestablishes the per-category count" "" \
    "$(devflow_open_filed_in_category "$RL_TMP/caps-cat.json" good 2>/dev/null)"
  printf '%s' '{"schema_version":2,"dismissed":{},"patterns":{"good":{"meta_issues":"nope"}}}' > "$RL_TMP/caps-cat2.json"
  assert_eq "#788 caps: a non-array meta_issues at the queried slug unestablishes it too" "" \
    "$(devflow_open_filed_in_category "$RL_TMP/caps-cat2.json" good 2>/dev/null)"
  # An ABSENT record is a legitimate 0 (this category has filed nothing) — the one
  # shape that must NOT fail closed, or every first filing in a category withholds.
  assert_eq "#788 caps: an absent record is a real 0, not unestablished" "0" \
    "$(devflow_open_filed_in_category "$RL_TMP/caps-ok.json" never-filed 2>/dev/null)"
  # The unestablished count must NAME itself.
  RL_CAPS_ERR="$(devflow_open_filed_total "$RL_TMP/caps-bad.json" 2>&1 >/dev/null)"
  assert_eq "#788 caps: the unestablished total breadcrumbs its cause" "true" \
    "$(case "$RL_CAPS_ERR" in *"UNESTABLISHED"*) echo true ;; *) echo false ;; esac)"
)

# ── render-report tolerates a malformed optional count key ───────────────────
# `// []` does not replace a truthy non-array value, so `length` aborts jq on a
# hand-corrupted `withheld_patterns`/`declined_refiled`. Under `set -e` an
# unguarded count would take the WHOLE report down over one malformed optional
# key; the guard degrades to omitting that one section.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_BAD="$(devflow_render_report '{"prs_scanned":7,"patterns":[],"withheld_patterns":true,"declined_refiled":true}' 2>/dev/null)"
  assert_eq "#788 render: a malformed withheld_patterns does not kill the report" "true" \
    "$(case "$RL_BAD" in *"scanned: 7"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: the malformed optional section is omitted, not half-rendered" "false" \
    "$(case "$RL_BAD" in *"withheld by a filing cap"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a malformed declined_refiled omits its section too" "false" \
    "$(case "$RL_BAD" in *"Won't-fix patterns re-raised"*) echo true ;; *) echo false ;; esac)"
)

# ── the malformed-count guard covers every non-array shape, not just booleans ──
# `length` only ERRORS on a boolean: a string, a number and an object all return
# a count (`"oops"|length` -> 4, `{"a":1}|length` -> 1). So a count guard written
# as `length` + a numeric case passes those three shapes straight through as a
# positive count, and the section's own element read — `.tag`, `.cap`,
# `sort_by` — is what aborts, AFTER the heading is already on stdout. Under this
# file's `set -euo pipefail` that kills the render mid-report and takes every
# LATER section (Blockers included) with it. Drive the three shapes the boolean
# case never reached, on the two keys whose absence must stay non-silent.
for RL_SHAPE in '"oops"' '5' '{"a":1}'; do
  (
    . "$REPO_ROOT/lib/render-report.sh"
    RL_NB="$(devflow_render_report "{\"prs_scanned\":7,\"patterns\":$RL_SHAPE,\"blockers\":[\"b1\"]}" 2>/dev/null)"
    assert_eq "#788 render: a non-array patterns ($RL_SHAPE) still renders the LATER blockers section" "true" \
      "$(case "$RL_NB" in *"b1"*) echo true ;; *) echo false ;; esac)"
    assert_eq "#788 render: a non-array patterns ($RL_SHAPE) omits the pattern section entirely" "false" \
      "$(case "$RL_NB" in *"Patterns this run"*) echo true ;; *) echo false ;; esac)"
  )
  (
    . "$REPO_ROOT/lib/render-report.sh"
    RL_NW="$(devflow_render_report "{\"prs_scanned\":7,\"patterns\":[],\"withheld_patterns\":$RL_SHAPE,\"blockers\":[\"b2\"]}" 2>/dev/null)"
    assert_eq "#788 render: a non-array withheld_patterns ($RL_SHAPE) still renders blockers" "true" \
      "$(case "$RL_NW" in *"b2"*) echo true ;; *) echo false ;; esac)"
    # The load-bearing half: the HEADING must not print either. Without this the
    # assertion above passes against a bare-`length` mutant that emits an empty
    # "## Patterns withheld by a filing cap" heading — a section that falsely
    # attests to having been rendered. (The shadow pass proved that mutant survived.)
    assert_eq "#788 render: a non-array withheld_patterns ($RL_SHAPE) omits its heading entirely" "false" \
      "$(case "$RL_NW" in *"withheld by a filing cap"*) echo true ;; *) echo false ;; esac)"
  )
done
# Positive control for the loop above: a WELL-FORMED withheld_patterns does render
# the heading and its row, so the three omission assertions pin the type guard and
# not a renderer that never emits the section at all.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_WOK="$(devflow_render_report '{"prs_scanned":7,"patterns":[],"withheld_patterns":[{"tag":"t1","cap":"max_open_issues"}]}' 2>/dev/null)"
  assert_eq "#788 render: a well-formed withheld_patterns renders its heading (control)" "true" \
    "$(case "$RL_WOK" in *"withheld by a filing cap"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a well-formed withheld_patterns renders its row (control)" "true" \
    "$(case "$RL_WOK" in *'`t1`'*"max_open_issues"*) echo true ;; *) echo false ;; esac)"
)
# The non-silent keys must still BREADCRUMB on these shapes — the warning arm was
# unreachable for them while `length` returned a count.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_STR_ERR="$(devflow_render_report '{"prs_scanned":7,"patterns":"oops","blockers":"nope"}' 2>&1 >/dev/null)"
  assert_eq "#788 render: a STRING patterns breadcrumbs like a boolean one does" "true" \
    "$(case "$RL_STR_ERR" in *"\`patterns\` key is malformed"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a STRING blockers breadcrumbs too" "true" \
    "$(case "$RL_STR_ERR" in *"\`blockers\` key is malformed"*) echo true ;; *) echo false ;; esac)"
)
# A well-formed array carrying ONE malformed element must degrade that element,
# not the section. Assert the RENDERED ENTRIES, not merely that a later section
# survives: the survives-only form is a tautology that passes with the element
# filter removed, with the failure suppression removed, and with both removed
# (the shadow pass measured all three mutants surviving).
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_ELEM="$(devflow_render_report '{"prs_scanned":7,"patterns":[{"tag":"good","occurrence_count":2},"junk"],"withheld_patterns":[{"tag":"w1","cap":"max_issues_per_run"},"junk"],"blockers":["b3"]}' 2>/dev/null)"
  assert_eq "#788 render: the well-formed sibling of a malformed element still renders" "true" \
    "$(case "$RL_ELEM" in *'`good`'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: the malformed element is dropped, not rendered raw" "false" \
    "$(case "$RL_ELEM" in *"junk"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: the withheld section's well-formed element survives too" "true" \
    "$(case "$RL_ELEM" in *'`w1`'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a malformed element does not truncate the report" "true" \
    "$(case "$RL_ELEM" in *"b3"*) echo true ;; *) echo false ;; esac)"
  # An abort INSIDE a well-formed object element (a string occurrence_count that
  # aborts sort_by) must be NAMED, never rendered as an empty section: the
  # key-level warning cannot fire for it, because the key genuinely IS an array.
  RL_FIELD_ERR="$(devflow_render_report '{"prs_scanned":7,"patterns":[{"tag":"a","occurrence_count":"3"}]}' 2>&1 >/dev/null)"
  RL_FIELD_OUT="$(devflow_render_report '{"prs_scanned":7,"patterns":[{"tag":"a","occurrence_count":"3"}]}' 2>/dev/null)"
  assert_eq "#788 render: a string occurrence_count still renders its row (total field read)" "true" \
    "$(case "$RL_FIELD_OUT" in *'`a`'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a string occurrence_count does not silently empty the section" "false" \
    "$(case "$RL_FIELD_ERR$RL_FIELD_OUT" in *"Patterns this run"*'`a`'*) echo false ;; *) echo true ;; esac)"
)
# `_None filed._` is a positive claim of fact and must never be printed off an
# unestablished count — that would have the report deny filings that did happen.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_NF_OUT="$(devflow_render_report '{"prs_scanned":7,"patterns":[],"intervention_issues":"boom"}' 2>/dev/null)"
  RL_NF_ERR="$(devflow_render_report '{"prs_scanned":7,"patterns":[],"intervention_issues":"boom"}' 2>&1 >/dev/null)"
  assert_eq "#788 render: a malformed intervention_issues does NOT claim '_None filed._'" "false" \
    "$(case "$RL_NF_OUT" in *"_None filed._"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: it breadcrumbs the refusal instead" "true" \
    "$(case "$RL_NF_ERR" in *"refusing to print"*) echo true ;; *) echo false ;; esac)"
  # Control: a genuinely empty array still gets the honest '_None filed._'.
  assert_eq "#788 render: an empty intervention_issues still says '_None filed._' (control)" "true" \
    "$(case "$(devflow_render_report '{"prs_scanned":7,"patterns":[],"intervention_issues":[]}' 2>/dev/null)" in *"_None filed._"*) echo true ;; *) echo false ;; esac)"
)

# ── _migrate's two failure arms ──────────────────────────────────────────────
# overrides.json is the file that gates whether an issue gets filed at all, and
# it is exactly the hand-corruptible input CLAUDE.md's best-effort-parser rule
# governs. Both arms must fail loud and leave the file byte-unchanged; a silent
# fall-through would let `run` proceed to _reconcile against a corrupt file.
printf '%s' 'this is not json {' > "$RL_TMP/mig-bad.json"
cp "$RL_TMP/mig-bad.json" "$RL_TMP/mig-bad-before.json"
bash "$RL_PS" migrate "$RL_TMP/mig-bad.json" >/dev/null 2>"$RL_TMP/mig-bad.err"; RL_MB_RC=$?
assert_eq "#788 migrate: a non-JSON overrides file exits non-zero" "true" \
  "$([ "$RL_MB_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 migrate: the non-JSON arm names the path" "true" \
  "$(grep -q "${RL_TMP}/mig-bad.json does not parse as JSON" "$RL_TMP/mig-bad.err" && echo true || echo false)"
assert_eq "#788 migrate: a non-JSON file is left byte-unchanged" "true" \
  "$(diff -q "$RL_TMP/mig-bad-before.json" "$RL_TMP/mig-bad.json" >/dev/null 2>&1 && echo true || echo false)"
# `run` must abort at migrate rather than reconciling a corrupt file.
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" run "$RL_TMP/mig-bad.json" >/dev/null 2>&1; RL_RB_RC=$?
assert_eq "#788 run: a non-JSON overrides file aborts before reconcile" "true" \
  "$([ "$RL_RB_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 run: the aborted run left the corrupt file byte-unchanged" "true" \
  "$(diff -q "$RL_TMP/mig-bad-before.json" "$RL_TMP/mig-bad.json" >/dev/null 2>&1 && echo true || echo false)"

# ── A migrated v1 URL with no parseable /issues/N yields number: null ─────────
# That entry can never resolve through either leg, so it keeps its state forever
# and suppresses its pattern indefinitely — the same silent exhaustion the
# liveness warning exists to surface. Pin the shape and the warning.
printf '%s' '{"schema_version":1,"dismissed":{"nonum":{"dismissed_at":"2026-06-03T00:00:00Z","dismissed_by":"retrospective-weekly","meta_issue":"https://github.com/o/r/pull/no-number-here"}}}' > "$RL_TMP/mig-nonum.json"
bash "$RL_PS" migrate "$RL_TMP/mig-nonum.json" >/dev/null 2>&1
assert_eq "#788 migrate: a URL with no /issues/N migrates to number: null" "null" \
  "$(jq -r '.patterns["nonum"].meta_issues[0].number' "$RL_TMP/mig-nonum.json")"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/mig-nonum.json" >/dev/null 2>"$RL_TMP/nonum.err"
assert_eq "#788 reconcile: a null-number entry applies no transition" "filed" \
  "$(jq -r '.patterns["nonum"].state' "$RL_TMP/mig-nonum.json")"
assert_eq "#788 reconcile: a null-number entry warns naming the slug" "true" \
  "$(grep -q 'nonum' "$RL_TMP/nonum.err" && echo true || echo false)"

# ── A wholly-failed by-number leg is a broken resolver, not N deleted issues ──
# Every fallback lookup failing means expired auth / rate limit / network / a
# drifted `gh --json` contract. Collapsing that into per-entry `unresolved` and
# returning 0 would report a systemically-failed reconcile as SUCCESS, and the
# Step 6 guard would wave it through.
cat > "$RL_TMP/gh-allfail.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
exit 1
STUB
chmod +x "$RL_TMP/gh-allfail.sh"
# TWO entries: the check requires a sample of at least two before inferring a
# systemic failure, because with one attempt "the resolver is broken" and "that
# issue was deleted" are indistinguishable — and the single-entry case has its
# own documented per-slug-warning behavior (asserted above).
printf '%s' '{"schema_version":2,"patterns":{"allfail":{"state":"filed","fixed_at":null,"provenance":"p","meta_issues":[{"number":701,"url":"https://o/r/issues/701","state":"filed","closedAt":null},{"number":704,"url":"https://o/r/issues/704","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/allfail.json"
cp "$RL_TMP/allfail.json" "$RL_TMP/allfail-before.json"
DEVFLOW_GH="$RL_TMP/gh-allfail.sh" bash "$RL_PS" reconcile "$RL_TMP/allfail.json" >/dev/null 2>"$RL_TMP/allfail.err"; RL_AF_RC=$?
# It DIAGNOSES without aborting: the per-slug warnings are an explicit acceptance
# criterion and run downstream, and aborting here would also discard every
# transition the prefetch resolved correctly for other patterns.
assert_eq "#788 resolver: a wholly-failed by-number leg still completes (rc 0)" "0" "$RL_AF_RC"
assert_eq "#788 resolver: it warns that this is a broken resolver, not deleted issues" "true" \
  "$(grep -q 'broken resolver' "$RL_TMP/allfail.err" && echo true || echo false)"
assert_eq "#788 resolver: the systemic summary does NOT suppress the per-slug warnings" "true" \
  "$(grep -q 'allfail' "$RL_TMP/allfail.err" && echo true || echo false)"
# Boundary control: ONE failing attempt is below the inference threshold, so it
# keeps the documented per-slug-warning behavior and does NOT become a systemic
# error. This is what pins the threshold rather than "any failure".
printf '%s' "$(rl_record onefail 705)" > "$RL_TMP/onefail.json"
DEVFLOW_GH="$RL_TMP/gh-allfail.sh" bash "$RL_PS" reconcile "$RL_TMP/onefail.json" >/dev/null 2>"$RL_TMP/onefail.err"; RL_1F_RC=$?
assert_eq "#788 resolver: a SINGLE failed lookup is not inferred systemic (control)" "0" "$RL_1F_RC"
assert_eq "#788 resolver: the single-failure case keeps its per-slug warning (control)" "true" \
  "$(grep -q 'onefail' "$RL_TMP/onefail.err" && echo true || echo false)"
# The entries stay `filed` (no transition was resolvable), but the reconcile
# itself completed rather than aborting.
assert_eq "#788 resolver: an unresolvable entry keeps its prior state" "filed" \
  "$(jq -r '.patterns["allfail"].state' "$RL_TMP/allfail.json")"
# Control: a PARTIAL failure stays the ordinary per-slug-warning path and still
# writes, so the assertions above pin "all failed", not "any failed".
cat > "$RL_TMP/gh-partial.sh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then echo '[]'; exit 0; fi
if [ "$1" = "issue" ] && [ "$2" = "view" ] && [ "$3" = "702" ]; then
  echo '{"number":702,"state":"CLOSED","stateReason":"COMPLETED","closedAt":"2026-06-07T00:00:00Z"}'; exit 0
fi
exit 1
STUB
chmod +x "$RL_TMP/gh-partial.sh"
printf '%s' '{"schema_version":2,"patterns":{"mixed":{"state":"filed","fixed_at":null,"provenance":"p","meta_issues":[{"number":702,"url":"https://o/r/issues/702","state":"filed","closedAt":null},{"number":703,"url":"https://o/r/issues/703","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/partial.json"
DEVFLOW_GH="$RL_TMP/gh-partial.sh" bash "$RL_PS" reconcile "$RL_TMP/partial.json" >/dev/null 2>&1; RL_PF_RC=$?
assert_eq "#788 resolver: a PARTIAL fallback failure still succeeds (control)" "0" "$RL_PF_RC"
assert_eq "#788 resolver: the resolvable entry still transitioned (control)" "fixed" \
  "$(jq -r '.patterns["mixed"].meta_issues[] | select(.number==702) | .state' "$RL_TMP/partial.json")"

# ── `reconcile` migrates a v1 file rather than writing a hybrid shape ─────────
# Before this, `reconcile` on a v1 file read an empty `.patterns`, applied
# nothing, and wrote back `schema_version: 1` PLUS an empty `patterns{}` — a
# shape neither version defines.
printf '%s' '{"schema_version":1,"dismissed":{"tooling-gap":{"dismissed_at":"2026-06-03T00:00:00Z","dismissed_by":"retrospective-weekly","meta_issue":"https://github.com/o/r/issues/504"}}}' > "$RL_TMP/recon-v1.json"
DEVFLOW_GH="$RL_TMP/gh-view.sh" bash "$RL_PS" reconcile "$RL_TMP/recon-v1.json" >/dev/null 2>&1
assert_eq "#891 reconcile: a v1 file is migrated at reconcile start (to v3)" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/recon-v1.json")"
assert_eq "#788 reconcile: the migrated record is then reconciled (504 is OPEN)" "filed" \
  "$(jq -r '.patterns["tooling-gap"].state' "$RL_TMP/recon-v1.json")"

# ── meta-issue.sh validates the number it derives from the created URL ────────
# The URL guard's `[0-9]*` is a GLOB — "a digit followed by anything" — so
# `/issues/12ab` passes it. Left unvalidated, the derived token reaches
# `--argjson num`, jq exits non-zero, and the run lands in the record-write
# recovery branch, blaming a WRITE failure for a malformed URL.
cat > "$RL_TMP/gh-badurl.sh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"issue list"*) echo '[]' ;;
  *"issue create"*) echo 'https://github.com/o/r/issues/12ab' ;;
  *"issue comment"*) echo ok ;;
  *"/labels"*) echo '{}' ;;
  *) echo '' ;;
esac
STUB
chmod +x "$RL_TMP/gh-badurl.sh"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/badurl.json"
DEVFLOW_GH="$RL_TMP/gh-badurl.sh" bash "$RL_MI" --tag badurl --slug badurl --category badurl --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/badurl.json" >/dev/null 2>"$RL_TMP/badurl.err"; RL_BU_RC=$?
assert_eq "#788 meta-issue: a non-numeric URL tail exits non-zero" "true" \
  "$([ "$RL_BU_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 meta-issue: the breadcrumb blames the URL, not a write failure" "true" \
  "$(grep -q 'does not end in a bare issue number' "$RL_TMP/badurl.err" && echo true || echo false)"
assert_eq "#788 meta-issue: a malformed URL is NOT misreported as a record-write failure" "false" \
  "$(grep -q 'lifecycle record could not be written' "$RL_TMP/badurl.err" && echo true || echo false)"

# ── The reconcile write refuses to transform a document that did not load ────
# On an empty slurp `$ov[0]` is null, and `null | .patterns = (…)` is LEGAL jq:
# it builds `{"patterns":{}}` and exits 0. That stub would reach _atomic_write
# and replace overrides.json — losing schema_version, every lifecycle record, and
# the hand-written `dismissed{}` map. Pin the assertion that stops it, using a
# DEVFLOW_JQ stub whose --slurpfile lands zero documents.
cat > "$RL_TMP/jq-emptyslurp.sh" <<'STUB'
#!/usr/bin/env bash
# Pass everything through to the real jq EXCEPT a --slurpfile of the overrides
# document, which is fed an empty file so the slurp lands zero values.
args=(); empty=""
for a in "$@"; do args+=("$a"); done
i=0
while [ $i -lt ${#args[@]} ]; do
  if [ "${args[$i]}" = "--slurpfile" ] && [ "${args[$((i+1))]}" = "ov" ]; then
    empty="$(mktemp)"; : > "$empty"; args[$((i+2))]="$empty"
  fi
  i=$((i+1))
done
jq "${args[@]}"; rc=$?
[ -n "$empty" ] && rm -f "$empty"
exit $rc
STUB
chmod +x "$RL_TMP/jq-emptyslurp.sh"
printf '%s' "$(rl_record slurpguard 501)" > "$RL_TMP/slurp.json"
cp "$RL_TMP/slurp.json" "$RL_TMP/slurp-before.json"
DEVFLOW_JQ="$RL_TMP/jq-emptyslurp.sh" DEVFLOW_GH="$RL_TMP/gh-view.sh" \
  bash "$RL_PS" reconcile "$RL_TMP/slurp.json" >/dev/null 2>"$RL_TMP/slurp.err"; RL_SG_RC=$?
assert_eq "#788 slurp guard: a document that did not load exits non-zero" "true" \
  "$([ "$RL_SG_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#788 slurp guard: the human-owned dismissed{} map survives byte-for-byte" "true" \
  "$(diff -q "$RL_TMP/slurp-before.json" "$RL_TMP/slurp.json" >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#788 slurp guard: the overrides file was NOT replaced by a {patterns:{}} stub" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/slurp.json")"

# ── actionable-patterns.sh rejects an unrecognized third argument ─────────────
# A near-miss silently yielded the FILTERED view, which the caller writes to
# patterns-full.json and the report renders under a heading promising the
# unfiltered picture — well-formed, non-empty, and wrong.
for _rl_bad_arg in '--ful' '-full' '--full=1' 'full'; do
  DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
    bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" "$_rl_bad_arg" >/dev/null 2>"$RL_TMP/arg.err"; _rl_arc=$?
  assert_eq "#788 --full: an unrecognized third arg '${_rl_bad_arg}' is rejected (rc 2)" "2" "$_rl_arc"
  assert_eq "#788 --full: the rejection names the offending argument '${_rl_bad_arg}'" "true" \
    "$(grep -q "unknown argument '${_rl_bad_arg}'" "$RL_TMP/arg.err" && echo true || echo false)"
done
# Controls on the same fixture: the exact literal and its absence both still work,
# so the rejections above pin the strictness and not a broken invocation.
DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" --full >/dev/null 2>&1; _rl_arc=$?
assert_eq "#788 --full: the exact literal is still accepted (control)" "0" "$_rl_arc"
DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/live-r.jsonl" "$RL_TMP/live-ov.json" >/dev/null 2>&1; _rl_arc=$?
assert_eq "#788 --full: omitting the third arg is still accepted (control)" "0" "$_rl_arc"

# ── The cap comparands fail closed but no longer fail SILENTLY ───────────────
# An empty comparand withholds EVERY pattern for the whole run via
# `invalid-operand`, so "filed nothing" must never be indistinguishable from
# "nothing to file". The empty stdout is the contract; the breadcrumb is new.
(
  set +e
  # shellcheck source=../../filing-decisions.sh
  . "$REPO_ROOT/lib/filing-decisions.sh"
  assert_eq "#788 comparand: an absent overrides file still prints NOTHING (fail closed)" "" \
    "$(devflow_open_filed_total "$RL_TMP/no-such-file.json" 2>/dev/null)"
  assert_eq "#788 comparand: the absent-file total names the invalid-operand consequence" "true" \
    "$(devflow_open_filed_total "$RL_TMP/no-such-file.json" 2>&1 >/dev/null \
       | grep -q 'withheld as invalid-operand' && echo true || echo false)"
  assert_eq "#788 comparand: the per-category absent-file arm breadcrumbs too" "true" \
    "$(devflow_open_filed_in_category "$RL_TMP/no-such-file.json" someslug 2>&1 >/dev/null \
       | grep -q 'withheld as invalid-operand' && echo true || echo false)"
  # Control: a well-formed file still yields a real count on stdout and no error,
  # so the empty-stdout assertions above pin the fail-closed arms rather than a
  # helper that never counts anything. (Self-contained fixture: two `filed`
  # entries across two records, plus a `fixed` one that must not be counted.)
  printf '%s' '{"schema_version":2,"patterns":{"p1":{"state":"filed","meta_issues":[{"number":1,"state":"filed"},{"number":2,"state":"fixed"}]},"p2":{"state":"filed","meta_issues":[{"number":3,"state":"filed"}]}},"dismissed":{}}' > "$RL_TMP/comparand-ok.json"
  assert_eq "#788 comparand: a well-formed file still yields its count (control)" "2" \
    "$(devflow_open_filed_total "$RL_TMP/comparand-ok.json" 2>/dev/null)"
  assert_eq "#788 comparand: the well-formed control emits no breadcrumb" "" \
    "$(devflow_open_filed_total "$RL_TMP/comparand-ok.json" 2>&1 >/dev/null)"
  # The liveness reader's missing-capture arm carries the same sentence.
  assert_eq "#788 liveness reader: a missing capture warns rather than reading as 'nothing suppressed'" "true" \
    "$(devflow_liveness_warning "$RL_TMP/no-such-capture.err" 2>&1 >/dev/null \
       | grep -q 'NOT evidence that nothing is suppressed' && echo true || echo false)"
)

# ── render-report breadcrumbs the two NON-optional malformed keys ─────────────
# A malformed `.patterns` otherwise renders a complete, plausible report with the
# section simply absent — indistinguishable from a week with no patterns, and the
# upstream `:?` guard cannot see it because the value is non-empty.
(
  . "$REPO_ROOT/lib/render-report.sh"
  RL_MALFORMED_ERR="$(devflow_render_report '{"prs_scanned":7,"patterns":true,"blockers":true}' 2>&1 >/dev/null)"
  assert_eq "#788 render: a malformed patterns key emits a breadcrumb naming it" "true" \
    "$(case "$RL_MALFORMED_ERR" in *'`patterns` key is malformed'*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: the patterns breadcrumb denies the quiet-week reading" "true" \
    "$(case "$RL_MALFORMED_ERR" in *"NOT evidence that there were no patterns"*) echo true ;; *) echo false ;; esac)"
  assert_eq "#788 render: a malformed blockers key breadcrumbs too" "true" \
    "$(case "$RL_MALFORMED_ERR" in *'`blockers` key is malformed'*) echo true ;; *) echo false ;; esac)"
  # Control: a well-formed summary emits neither breadcrumb.
  RL_CLEAN_ERR="$(devflow_render_report '{"prs_scanned":7,"patterns":[],"blockers":[]}' 2>&1 >/dev/null)"
  assert_eq "#788 render: a well-formed summary emits no malformed-key breadcrumb (control)" "false" \
    "$(case "$RL_CLEAN_ERR" in *'is malformed'*) echo true ;; *) echo false ;; esac)"
)

# ── Dedup keeps one unresolvable number below the systemic threshold ──────────
# Two records referencing the SAME unresolvable number must stay the per-slug
# warning path. Without `_seen`, that fixture flips to "every by-number lookup
# failed (2/2)" and hard-aborts a reconcile over one deleted issue.
printf '%s' '{"schema_version":2,"patterns":{"a":{"state":"filed","fixed_at":null,"provenance":"p","meta_issues":[{"number":900,"url":"https://o/r/issues/900","state":"filed","closedAt":null}]},"b":{"state":"filed","fixed_at":null,"provenance":"p","meta_issues":[{"number":900,"url":"https://o/r/issues/900","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/dedup.json"
DEVFLOW_GH="$RL_TMP/gh-allfail.sh" bash "$RL_PS" reconcile "$RL_TMP/dedup.json" >/dev/null 2>"$RL_TMP/dedup.err"; RL_DD_RC=$?
assert_eq "#788 dedup: two records sharing one unresolvable number is ONE attempt (rc 0)" "0" "$RL_DD_RC"
assert_eq "#788 dedup: that fixture is NOT inferred a systemic resolver failure" "false" \
  "$(grep -q 'broken resolver' "$RL_TMP/dedup.err" && echo true || echo false)"

# ── First-run: pattern-state materializes the v2 stub at the REAL path ───────
# The filing caps read that exact path and fail closed by printing nothing when
# it is missing, which withholds EVERY pattern as `invalid-operand`. Nothing else
# creates it first (actionable-patterns stubs only into its own temp dir;
# meta-issue writes the real stub but runs only AFTER a `file` verdict), so
# without this a fresh consumer repo would withhold everything, never file, never
# create the file, and repeat that forever.
rm -rf "$RL_TMP/fresh"; mkdir -p "$RL_TMP/fresh"
DEVFLOW_GH="$RL_TMP/gh-ap.sh" bash "$RL_PS" run "$RL_TMP/fresh/overrides.json" >/dev/null 2>&1
assert_eq "#788 first run: the stub is materialized at the real overrides path" "true" \
  "$([ -f "$RL_TMP/fresh/overrides.json" ] && echo true || echo false)"
assert_eq "#891 first run: the materialized stub is v3" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/fresh/overrides.json" 2>/dev/null)"
(
  set +e
  # shellcheck source=../../filing-decisions.sh
  . "$REPO_ROOT/lib/filing-decisions.sh"
  # The whole point: the comparand now reads a real 0 instead of empty, so the
  # first run can actually file instead of deadlocking on `invalid-operand`.
  assert_eq "#788 first run: the cap comparand reads 0, not empty" "0" \
    "$(devflow_open_filed_total "$RL_TMP/fresh/overrides.json" 2>/dev/null)"
  assert_eq "#788 first run: the cap verdict is 'file', not 'invalid-operand'" "file" \
    "$(devflow_filing_cap_verdict open 0 3 0 2 "$(devflow_open_filed_total "$RL_TMP/fresh/overrides.json" 2>/dev/null)" 10)"
)
# An EMPTY file takes the same arm as an absent one.
: > "$RL_TMP/fresh/empty.json"
DEVFLOW_GH="$RL_TMP/gh-ap.sh" bash "$RL_PS" run "$RL_TMP/fresh/empty.json" >/dev/null 2>&1
assert_eq "#891 first run: an EMPTY overrides file is stubbed to v3 too" "3" \
  "$(jq -r '.schema_version' "$RL_TMP/fresh/empty.json" 2>/dev/null)"

# ── Hand-corruptible input: wrong-shaped JSON must not abort the run ─────────
# `dismissed{}` is human-owned and hand-editable BY DESIGN, so a wrong-shaped
# value is an input the parser must survive under the adversarial-shape matrix,
# not a crash. Before this guard, a single string-valued entry aborted the whole
# migration (and therefore the whole weekly run).
printf '%s' '{"schema_version":1,"dismissed":{"handkey":"just a string","loopkey":{"dismissed_by":"retrospective-weekly","dismissed_at":"2026-01-01T00:00:00Z","meta_issue":"https://o/r/issues/5"}}}' > "$RL_TMP/shape1.json"
bash "$RL_PS" migrate "$RL_TMP/shape1.json" >/dev/null 2>&1; RL_S1_RC=$?
assert_eq "#788 shape: a non-object dismissed entry does not abort the migration" "0" "$RL_S1_RC"
assert_eq "#788 shape: the non-object hand-written entry is preserved verbatim" "true" \
  "$(jq -e '.dismissed | has("handkey")' "$RL_TMP/shape1.json" >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#788 shape: the loop-written entry beside it still converts" "true" \
  "$(jq -e '.patterns | has("loopkey")' "$RL_TMP/shape1.json" >/dev/null 2>&1 && echo true || echo false)"
# A `dismissed` that is itself a scalar aborts `to_entries` the same way.
printf '%s' '{"schema_version":1,"dismissed":"not a map"}' > "$RL_TMP/shape2.json"
bash "$RL_PS" migrate "$RL_TMP/shape2.json" >/dev/null 2>&1; RL_S2_RC=$?
assert_eq "#788 shape: a scalar dismissed map does not abort the migration" "0" "$RL_S2_RC"

# The same class, other reader: compute-patterns.jq indexes lifecycle records.
assert_eq "#788 shape: a non-object lifecycle record does not abort the derivation" "0" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["x"]}' \
      '{"schema_version":2,"patterns":{"foo":"oops"},"dismissed":{}}' >/dev/null 2>&1; echo $?)"
assert_eq "#788 shape: an ARRAY patterns map does not abort the derivation" "0" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["x"]}' \
      '{"schema_version":2,"patterns":[{"x":1}],"dismissed":"nope"}' >/dev/null 2>&1; echo $?)"
# Control: a well-formed record on the same path still derives its real status,
# so the guards above skip a wrong shape rather than neutering the reader.
assert_eq "#788 shape: a well-formed record still derives its status (control)" "filed" \
  "$(rl_cp '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["x"]}' \
      '{"schema_version":2,"patterns":{"x":{"state":"filed","fixed_at":null,"meta_issues":[]}},"dismissed":{}}' | jq -r '.x.status')"

# ── meta-issue: the post-creation bootstrap write cannot report a filed issue
#    as unfiled ─────────────────────────────────────────────────────────────
# The stub write and the `date` call both run AFTER `gh issue create` succeeded.
# Under `set -euo pipefail` an unguarded failure there aborts before Step 3
# prints the URL, so the orchestrator records a real issue as NOT filed.
mkdir -p "$RL_TMP/robase"
DEVFLOW_GH="$RL_TMP/gh-mi.sh" bash "$RL_MI" --tag bootfail --slug bootfail --category bootfail --title T \
  --body-file "$RL_TMP/mi-body.md" --overrides "$RL_TMP/robase/nodir/overrides.json" \
  >"$RL_TMP/boot.out" 2>"$RL_TMP/boot.err"; RL_BOOT_RC=$?
assert_eq "#788 bootstrap: a failed stub write still exits 0" "0" "$RL_BOOT_RC"
assert_eq "#788 bootstrap: a failed stub write still prints the filed issue URL" "https://github.com/o/r/issues/777" \
  "$(cat "$RL_TMP/boot.out")"
assert_eq "#788 bootstrap: the breadcrumb says the issue WAS filed" "true" \
  "$(grep -q 'issue WAS filed' "$RL_TMP/boot.err" && echo true || echo false)"

# ── AC 76 line-count evidence lives in the PR, NOT in this module ────────────
# A former assertion here compared `lib/test/run.sh`'s line count against
# `merge-base(origin/main, HEAD)`. It was SELF-INVALIDATING: once this change
# merges, the merge-base of any later branch already contains the reduction, so
# before == after and the assertion is RED on `main` forever after — taking the
# required `lib + python tests` check with it. It also asserted a property of one
# DIFF rather than of the product, which is not what a permanent suite tests, and
# its no-base-ref arm hard-FAILed on a shallow/remote-less clone instead of
# routing through the sanctioned `skip … host-capability …` helper.
# The reduction is real and is evidenced where diff properties belong — the PR
# description and the diffstat. A durable guard, if one is ever wanted, must be a
# checked-in CEILING pin (the issue-#656 enforcement-constant exception), never a
# comparison against a moving base ref.

# ════════════════════════════════════════════════════════════════════════════
# #891 — opaque filing key: category on the record, compose-filing-key.sh, and
# the per-category cap sum.
# ════════════════════════════════════════════════════════════════════════════
RL_CK="$REPO_ROOT/lib/compose-filing-key.sh"

# ── compose-filing-key.sh ────────────────────────────────────────────────────
# A short composition fits whole and is byte-identical to its own slugify pass.
RL_CK_SHORT="$(bash "$RL_CK" tooling-gap slow-suite 2>/dev/null)"
assert_eq "#891 compose: a short composition is joined with a single dash" "tooling-gap-slow-suite" "$RL_CK_SHORT"
assert_eq "#891 compose: the output is slugify-stable (equals its own canonicalization)" "$RL_CK_SHORT" \
  "$(printf '%s' "$RL_CK_SHORT" | jq -R -L "$LIB" 'include "slugify"; slugify' -r)"
assert_eq "#891 compose: the output is at most 40 chars and matches [a-z0-9-]+" "true" \
  "$([ "${#RL_CK_SHORT}" -le 40 ] && printf '%s' "$RL_CK_SHORT" | grep -qE '^[a-z0-9-]+$' && echo true || echo false)"
# Distinct subslugs (same category) → distinct keys.
assert_eq "#891 compose: distinct subslugs give distinct keys" "false" \
  "$([ "$(bash "$RL_CK" tooling-gap slow-suite)" = "$(bash "$RL_CK" tooling-gap flaky-order)" ] && echo true || echo false)"
# Non-canonical arguments are canonicalized separately, then joined.
assert_eq "#891 compose: arguments are canonicalized (mixed case / spaces)" "tooling-gap-slow-suite" \
  "$(bash "$RL_CK" 'Tooling Gap' 'Slow Suite' 2>/dev/null)"
# An over-long composition is truncated with a deterministic digest suffix.
RL_CK_LONG="$(bash "$RL_CK" tooling-gap 'this-is-a-very-long-subslug-that-easily-exceeds-the-forty-char-ceiling' 2>/dev/null)"
assert_eq "#891 compose: an over-long composition is at most 40 chars" "true" \
  "$([ "${#RL_CK_LONG}" -le 40 ] && echo true || echo false)"
assert_eq "#891 compose: the truncated key still matches [a-z0-9-]+" "true" \
  "$(printf '%s' "$RL_CK_LONG" | grep -qE '^[a-z0-9-]+$' && echo true || echo false)"
assert_eq "#891 compose: the digest suffix is deterministic (same args → same key)" "$RL_CK_LONG" \
  "$(bash "$RL_CK" tooling-gap 'this-is-a-very-long-subslug-that-easily-exceeds-the-forty-char-ceiling' 2>/dev/null)"
# The digest comes from python3/hashlib: poison sha256sum/shasum/md5/cksum on PATH
# (make them exit non-zero) and the SAME key is still produced.
mkdir -p "$RL_TMP/poison"
for _h in sha256sum shasum md5 cksum; do printf '#!/usr/bin/env bash\nexit 1\n' > "$RL_TMP/poison/$_h"; chmod +x "$RL_TMP/poison/$_h"; done
assert_eq "#891 compose: the digest survives a PATH with sha256sum/shasum/md5/cksum poisoned" "$RL_CK_LONG" \
  "$(PATH="$RL_TMP/poison:$PATH" bash "$RL_CK" tooling-gap 'this-is-a-very-long-subslug-that-easily-exceeds-the-forty-char-ceiling' 2>/dev/null)"
# An absent / empty / canonicalizes-to-empty argument exits non-zero with NO stdout.
RL_CK_MISS="$(bash "$RL_CK" tooling-gap 2>/dev/null)"; RL_CK_MISS_RC=$?
assert_eq "#891 compose: a missing second argument exits non-zero" "true" "$([ "$RL_CK_MISS_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#891 compose: a missing second argument prints nothing on stdout" "" "$RL_CK_MISS"
RL_CK_EMPTY="$(bash "$RL_CK" tooling-gap '' 2>/dev/null)"; RL_CK_EMPTY_RC=$?
assert_eq "#891 compose: an empty argument exits non-zero" "true" "$([ "$RL_CK_EMPTY_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#891 compose: an empty argument prints nothing" "" "$RL_CK_EMPTY"
RL_CK_CANON="$(bash "$RL_CK" '///' slow-suite 2>/dev/null)"; RL_CK_CANON_RC=$?
assert_eq "#891 compose: an argument canonicalizing to empty exits non-zero" "true" "$([ "$RL_CK_CANON_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#891 compose: the canonicalizes-to-empty case prints nothing" "" "$RL_CK_CANON"
# Regression: the SECOND argument canonicalizing to empty must also fail closed —
# a two-line jq capture would collapse trailing newlines and yield a bogus <cat>-<cat>
# key (the fail-open the per-argument canonicalization fixes).
RL_CK_SUBEMPTY="$(bash "$RL_CK" tooling-gap '###' 2>/dev/null)"; RL_CK_SUBEMPTY_RC=$?
assert_eq "#891 compose: a SECOND argument canonicalizing to empty exits non-zero" "true" "$([ "$RL_CK_SUBEMPTY_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#891 compose: the second-arg-empty case prints nothing (no bogus cat-cat key)" "" "$RL_CK_SUBEMPTY"
# A category whose OWN canonical form exceeds the ceiling exits non-zero, no stdout.
RL_CK_BIGCAT="$(bash "$RL_CK" 'this-category-name-is-far-too-long-to-fit-inside-the-forty-character-ceiling' sub 2>/dev/null)"; RL_CK_BIGCAT_RC=$?
assert_eq "#891 compose: an over-long category exits non-zero" "true" "$([ "$RL_CK_BIGCAT_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#891 compose: an over-long category prints nothing" "" "$RL_CK_BIGCAT"
# The digest arm's DISTINGUISHING property: two long compositions that share the
# truncated 31-char prefix but differ in the tail must produce DISTINCT keys — the
# whole reason the digest exists. An empty/constant digest would collapse them and
# still pass the ≤40/grammar/determinism checks above, so assert distinctness here.
RL_CK_L1="$(bash "$RL_CK" tooling-gap 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-tail-one' 2>/dev/null)"
RL_CK_L2="$(bash "$RL_CK" tooling-gap 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-tail-two' 2>/dev/null)"
assert_eq "#891 compose: two long inputs sharing a prefix give DISTINCT keys (digest present)" "false" \
  "$([ "$RL_CK_L1" = "$RL_CK_L2" ] && echo true || echo false)"
assert_eq "#891 compose: the truncated key ends in an 8-hex-char digest suffix" "true" \
  "$(printf '%s' "$RL_CK_L1" | grep -qE -- '-[0-9a-f]{8}$' && echo true || echo false)"
# Ceiling boundary (arm-1 vs arm-2 selection): a composition canonicalizing to
# exactly 40 chars is printed whole (no digest); one at 41 is truncated+digested.
# category 'cat' (3) + '-' (1) → subslug of 36 non-hex 'z' = 40 → whole; 37 = 41 →
# arm 2. Generate the subslugs by length (never hand-counted) so the boundary is
# exact; 'z' is non-hex so the digest-suffix grep can never false-match a whole key.
RL_CK_SUB36="$(printf 'z%.0s' $(seq 1 36))"
RL_CK_SUB37="$(printf 'z%.0s' $(seq 1 37))"
RL_CK_40="$(bash "$RL_CK" cat "$RL_CK_SUB36" 2>/dev/null)"
assert_eq "#891 compose: a 40-char composition is exactly 40 chars" "40" "${#RL_CK_40}"
assert_eq "#891 compose: a 40-char composition is printed WHOLE (no digest suffix)" "false" \
  "$(printf '%s' "$RL_CK_40" | grep -qE -- '-[0-9a-f]{8}$' && echo true || echo false)"
RL_CK_41="$(bash "$RL_CK" cat "$RL_CK_SUB37" 2>/dev/null)"
assert_eq "#891 compose: a 41-char composition is truncated with a digest (arm 2)" "true" \
  "$([ "${#RL_CK_41}" -le 40 ] && printf '%s' "$RL_CK_41" | grep -qE -- '-[0-9a-f]{8}$' && echo true || echo false)"

# ── slugify module: compute-patterns.jq and compose-filing-key.sh share ONE def.
# Behavioral parity: compose's output canonicalized through the module (the same
# def compute-patterns.jq includes) is unchanged.
assert_eq "#891 slugify-module: compose output round-trips through the shared def unchanged" "$RL_CK_SHORT" \
  "$(printf '%s' "$RL_CK_SHORT" | jq -R -L "$LIB" 'include "slugify"; slugify' -r)"
# The single-source contract is exercised behaviorally: both readers `include
# "slugify"` from lib/slugify.jq via -L, and every rl_cp assertion above (which
# fails at compile time if the include cannot resolve the def) plus this compose
# round-trip pass — so both resolve slugify from the shared module.

# ── compute-patterns.jq: attribution by stored category (opaque key) ─────────
RL_SUB_ENTRIES='{"kind":"implementation","pr":1,"merged_at":"2026-07-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}
{"kind":"implementation","pr":2,"merged_at":"2026-07-20T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}'
# A record keyed differently from its category, state fixed, with a post-fix occ → regressed.
RL_SUB_OV='{"schema_version":3,"patterns":{"tooling-gap--slow-suite":{"category":"tooling-gap","state":"fixed","fixed_at":"2026-07-05T00:00:00Z","provenance":"x","meta_issues":[{"number":900,"url":"u","state":"fixed","closedAt":"2026-07-05T00:00:00Z"}]}},"dismissed":{}}'
RL_SUB_VIEW="$(rl_cp "$RL_SUB_ENTRIES" "$RL_SUB_OV")"
assert_eq "#891 derive: a differently-keyed record attributes its category occurrences" "2" \
  "$(printf '%s' "$RL_SUB_VIEW" | jq -r '.["tooling-gap-slow-suite"].occurrence_count')"
assert_eq "#891 derive: the entry carries its attribution category" "tooling-gap" \
  "$(printf '%s' "$RL_SUB_VIEW" | jq -r '.["tooling-gap-slow-suite"].category')"
assert_eq "#891 derive: a differently-keyed fixed record regresses on a post-fix occurrence" "regressed" \
  "$(printf '%s' "$RL_SUB_VIEW" | jq -r '.["tooling-gap-slow-suite"].status')"
assert_eq "#891 derive: the corpus category claimed by the sub-pattern is suppressed" "false" \
  "$(printf '%s' "$RL_SUB_VIEW" | jq -e 'has("tooling-gap")' >/dev/null 2>&1 && echo true || echo false)"
# A differently-keyed FILED record does not duplicate its category's entry.
RL_FILED_OV='{"schema_version":3,"patterns":{"tooling-gap--slow-suite":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":901,"url":"u","state":"filed","closedAt":null}]}},"dismissed":{}}'
RL_FILED_VIEW="$(rl_cp "$RL_SUB_ENTRIES" "$RL_FILED_OV")"
assert_eq "#891 derive: a differently-keyed filed record derives filed" "filed" \
  "$(printf '%s' "$RL_FILED_VIEW" | jq -r '.["tooling-gap-slow-suite"].status')"
assert_eq "#891 derive: filed sub-pattern leaves exactly one entry for its category" "1" \
  "$(printf '%s' "$RL_FILED_VIEW" | jq -r '[to_entries[] | select(.value.category=="tooling-gap")] | length')"
# A bare-category record keeps its own entry even when a sub-pattern shares the category.
RL_BOTH_OV='{"schema_version":3,"patterns":{"tooling-gap":{"category":"tooling-gap","state":"fixed","fixed_at":"2026-07-05T00:00:00Z","provenance":"x","meta_issues":[]},"tooling-gap--slow-suite":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":902,"url":"u","state":"filed","closedAt":null}]}},"dismissed":{}}'
RL_BOTH_VIEW="$(rl_cp "$RL_SUB_ENTRIES" "$RL_BOTH_OV")"
assert_eq "#891 derive: a bare-category record keeps its own entry beside a sub-pattern" "true" \
  "$(printf '%s' "$RL_BOTH_VIEW" | jq -e 'has("tooling-gap") and has("tooling-gap-slow-suite")' >/dev/null 2>&1 && echo true || echo false)"
# A category no record claims still produces its own corpus entry.
RL_UNCLAIMED_OV='{"schema_version":3,"patterns":{},"dismissed":{}}'
assert_eq "#891 derive: an unclaimed category still produces its own entry" "2" \
  "$(rl_cp "$RL_SUB_ENTRIES" "$RL_UNCLAIMED_OV" | jq -r '.["tooling-gap"].occurrence_count')"
# A record whose stored category is a dismissed{} key derives dismissed, regardless of key.
RL_DIS_OV='{"schema_version":3,"patterns":{"tooling-gap--slow-suite":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"x","meta_issues":[]}},"dismissed":{"tooling-gap":{"dismissed_by":"a-human"}}}'
assert_eq "#891 derive: a record whose category is dismissed derives dismissed regardless of key" "dismissed" \
  "$(rl_cp "$RL_SUB_ENTRIES" "$RL_DIS_OV" | jq -r '.["tooling-gap-slow-suite"].status')"
# A present record with an unrecognized state derives open (unchanged fall-through).
RL_WEIRD_OV='{"schema_version":3,"patterns":{"tooling-gap--slow-suite":{"category":"tooling-gap","state":"weird","fixed_at":null,"provenance":"x","meta_issues":[]}},"dismissed":{}}'
assert_eq "#891 derive: a present record with an unrecognized state derives open" "open" \
  "$(rl_cp "$RL_SUB_ENTRIES" "$RL_WEIRD_OV" | jq -r '.["tooling-gap-slow-suite"].status')"

# ── derivation parity: a v2 fixture and its migrated-to-v3 form agree ─────────
RL_PAR_ENTRIES='{"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}
{"kind":"implementation","pr":2,"merged_at":"2026-04-10T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}'
printf '%s' '{"schema_version":2,"patterns":{"doc-accuracy":{"state":"filed","fixed_at":null,"provenance":"x","meta_issues":[{"number":9,"url":"u","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$RL_TMP/par-v2.json"
RL_PAR_V2VIEW="$(rl_cp "$RL_PAR_ENTRIES" "$(cat "$RL_TMP/par-v2.json")")"
cp "$RL_TMP/par-v2.json" "$RL_TMP/par-v3.json"
bash "$RL_PS" migrate "$RL_TMP/par-v3.json" >/dev/null 2>&1
RL_PAR_V3VIEW="$(rl_cp "$RL_PAR_ENTRIES" "$(cat "$RL_TMP/par-v3.json")")"
for _f in occurrence_count status first_seen last_seen; do
  assert_eq "#891 parity: doc-accuracy ${_f} matches pre/post migration" \
    "$(printf '%s' "$RL_PAR_V2VIEW" | jq -r ".[\"doc-accuracy\"].${_f}")" \
    "$(printf '%s' "$RL_PAR_V3VIEW" | jq -r ".[\"doc-accuracy\"].${_f}")"
done

# ── pattern-state migrate v2→v3 specifics ────────────────────────────────────
printf '%s' '{"schema_version":2,"patterns":{"tooling-gap":{"state":"declined","fixed_at":"2026-06-28T21:24:43Z","provenance":"2026-06-03T21:39:06Z","meta_issues":[{"number":113,"url":"u","state":"declined","closedAt":"2026-06-28T21:24:43Z"}]}},"dismissed":{"keepme":{"dismissed_by":"a-human"}}}' > "$RL_TMP/v2v3.json"
bash "$RL_PS" migrate "$RL_TMP/v2v3.json" >/dev/null 2>&1
assert_eq "#891 migrate v2→v3: schema_version becomes 3" "3" "$(jq -r '.schema_version' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: category equals the (canonical) key" "tooling-gap" "$(jq -r '.patterns["tooling-gap"].category' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: state is byte-unchanged" "declined" "$(jq -r '.patterns["tooling-gap"].state' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: fixed_at is byte-unchanged" "2026-06-28T21:24:43Z" "$(jq -r '.patterns["tooling-gap"].fixed_at' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: provenance is byte-unchanged" "2026-06-03T21:39:06Z" "$(jq -r '.patterns["tooling-gap"].provenance' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: meta_issues[0].number is byte-unchanged" "113" "$(jq -r '.patterns["tooling-gap"].meta_issues[0].number' "$RL_TMP/v2v3.json")"
assert_eq "#891 migrate v2→v3: the human dismissed{} entry survives byte-for-byte" "a-human" "$(jq -r '.dismissed["keepme"].dismissed_by' "$RL_TMP/v2v3.json")"
# Idempotent at v3.
cp "$RL_TMP/v2v3.json" "$RL_TMP/v2v3-before.json"
bash "$RL_PS" migrate "$RL_TMP/v2v3.json" >/dev/null 2>&1
assert_eq "#891 migrate: a second run over a v3 file is byte-identical" "true" \
  "$(cmp -s "$RL_TMP/v2v3-before.json" "$RL_TMP/v2v3.json" && echo true || echo false)"
# A NON-CANONICAL key → category is its slugified form.
printf '%s' '{"schema_version":2,"patterns":{"Tooling Gap":{"state":"fixed","fixed_at":null,"provenance":"x","meta_issues":[]}},"dismissed":{}}' > "$RL_TMP/noncanon.json"
bash "$RL_PS" migrate "$RL_TMP/noncanon.json" >/dev/null 2>&1
assert_eq "#891 migrate: a non-canonical key is stamped as its slugified category" "tooling-gap" \
  "$(jq -r '.patterns["Tooling Gap"].category' "$RL_TMP/noncanon.json")"
# A non-string category on a v2 record is repaired to the key AND warned (a v3
# file would be a migrate no-op, so the repair path is exercised from v2).
printf '%s' '{"schema_version":2,"patterns":{"rec-a":{"category":42,"state":"fixed","fixed_at":null,"provenance":"x","meta_issues":[]}},"dismissed":{}}' > "$RL_TMP/badcat2.json"
bash "$RL_PS" migrate "$RL_TMP/badcat2.json" 2>"$RL_TMP/badcat.err" >/dev/null
assert_eq "#891 migrate: a non-string category is repaired to the record key" "rec-a" \
  "$(jq -r '.patterns["rec-a"].category' "$RL_TMP/badcat2.json")"
# An explicit empty-string category takes the same repair-to-key + warning path.
printf '%s' '{"schema_version":2,"patterns":{"rec-b":{"category":"","state":"fixed","fixed_at":null,"provenance":"x","meta_issues":[]}},"dismissed":{}}' > "$RL_TMP/emptycat.json"
bash "$RL_PS" migrate "$RL_TMP/emptycat.json" 2>"$RL_TMP/emptycat.err" >/dev/null
assert_eq "#891 migrate: an empty-string category is repaired to the record key" "rec-b" \
  "$(jq -r '.patterns["rec-b"].category' "$RL_TMP/emptycat.json")"
assert_eq "#891 migrate: repairing an empty-string category also warns naming the record" "true" \
  "$(grep -q 'rec-b' "$RL_TMP/emptycat.err" && grep -q '::warning::' "$RL_TMP/emptycat.err" && echo true || echo false)"
assert_eq "#891 migrate: repairing a bad category emits a ::warning:: naming the record" "true" \
  "$(grep -q 'rec-a' "$RL_TMP/badcat.err" && grep -q '::warning::' "$RL_TMP/badcat.err" && echo true || echo false)"
# migrate over an absent / empty overrides path materializes a v3 stub.
bash "$RL_PS" migrate "$RL_TMP/absent-ov.json" >/dev/null 2>&1
assert_eq "#891 migrate: an absent path materializes a v3 stub" "3" "$(jq -r '.schema_version' "$RL_TMP/absent-ov.json")"
assert_eq "#891 migrate: the v3 stub has empty patterns{} and dismissed{}" "true" \
  "$(jq -e '(.patterns|length==0) and (.dismissed|length==0)' "$RL_TMP/absent-ov.json" >/dev/null 2>&1 && echo true || echo false)"

# ── filing-decisions: devflow_open_filed_for_category sums across records ─────
(
  set +e
  # shellcheck source=../../filing-decisions.sh
  . "$REPO_ROOT/lib/filing-decisions.sh"
  printf '%s' '{"schema_version":3,"patterns":{"tooling-gap--a":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"tooling-gap--b":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":2,"state":"filed"}]},"other":{"category":"other","state":"filed","meta_issues":[{"number":3,"state":"filed"}]}},"dismissed":{}}' > "$RL_TMP/percat.json"
  assert_eq "#891 for_category: sums filed entries across every record sharing the category" "2" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat.json" tooling-gap 2>/dev/null)"
  assert_eq "#891 for_category: an unclaimed category counts 0" "0" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat.json" nonesuch 2>/dev/null)"
  # The `state == "filed"` FILTER is load-bearing: a same-category record whose
  # meta-issue entry is `fixed` (a closed issue) must NOT consume a cap slot, so a
  # category with one filed + one fixed entry counts 1, not 2. (Without a non-filed
  # entry in the fixture a defect counting every state would pass vacuously.)
  printf '%s' '{"schema_version":3,"patterns":{"tg--open":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"tg--closed":{"category":"tooling-gap","state":"fixed","meta_issues":[{"number":2,"state":"fixed"}]}},"dismissed":{}}' > "$RL_TMP/percat-mixed.json"
  assert_eq "#891 for_category: only FILED entries count; a fixed entry does not consume a slot" "1" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-mixed.json" tooling-gap 2>/dev/null)"
  # A wrong-shaped record for an UNRELATED category unestablishes the requested count.
  printf '%s' '{"schema_version":3,"patterns":{"tooling-gap--a":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"broken":"not-an-object"},"dismissed":{}}' > "$RL_TMP/percat-broken.json"
  assert_eq "#891 for_category: a wrong-shaped unrelated record unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-broken.json" tooling-gap 2>/dev/null)"
  assert_eq "#891 for_category: a missing overrides file prints nothing (fail closed)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/no-such.json" tooling-gap 2>/dev/null)"

  # ── malformed-shape matrix (issue #891 review, finding 3) ──────────────────
  # This helper is a best-effort parser over a config JSON a human can hand-corrupt
  # and it DECIDES an emitted result (the max_open_per_category comparand), so the
  # CLAUDE.md convention requires the whole shape matrix be swept, not just the one
  # record-non-object arm above. Every row asserts the SAME fail-closed contract as
  # the arms above: empty stdout (UNESTABLISHED), never a laundered `0` and never an
  # under-count. Each fixture that can carry a legitimately-matching record does so,
  # so a defect that merely skipped the bad record would emit `1` and be caught.
  #
  # meta_issues is not an array.
  printf '%s' '{"schema_version":3,"patterns":{"tg--a":{"category":"tooling-gap","state":"filed","meta_issues":"nope"}},"dismissed":{}}' > "$RL_TMP/percat-mi-nonarray.json"
  assert_eq "#891 for_category: a non-array meta_issues unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-mi-nonarray.json" tooling-gap 2>/dev/null)"
  # A meta_issues ENTRY is not an object.
  printf '%s' '{"schema_version":3,"patterns":{"tg--a":{"category":"tooling-gap","state":"filed","meta_issues":["not-an-object"]}},"dismissed":{}}' > "$RL_TMP/percat-entry-nonobj.json"
  assert_eq "#891 for_category: a non-object meta_issues entry unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-entry-nonobj.json" tooling-gap 2>/dev/null)"
  # patterns{} is not an object.
  printf '%s' '{"schema_version":3,"patterns":[1,2],"dismissed":{}}' > "$RL_TMP/percat-patterns-nonobj.json"
  assert_eq "#891 for_category: a non-object patterns{} unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-patterns-nonobj.json" tooling-gap 2>/dev/null)"
  # The whole document is not an object (array form, and scalar form).
  printf '%s' '[1,2,3]' > "$RL_TMP/percat-top-array.json"
  assert_eq "#891 for_category: a top-level array unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-top-array.json" tooling-gap 2>/dev/null)"
  printf '%s' '"hello"' > "$RL_TMP/percat-top-scalar.json"
  assert_eq "#891 for_category: a top-level scalar unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-top-scalar.json" tooling-gap 2>/dev/null)"
  # An empty (truncated) file.
  : > "$RL_TMP/percat-empty.json"
  assert_eq "#891 for_category: an empty overrides file unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-empty.json" tooling-gap 2>/dev/null)"
  # Unparseable (not JSON at all).
  printf '%s' '{not json' > "$RL_TMP/percat-nonjson.json"
  assert_eq "#891 for_category: an unparseable overrides file unestablishes the count (empty, never 0)" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-nonjson.json" tooling-gap 2>/dev/null)"
  # A NON-STRING `category` on a structurally-valid record. Before the guard this
  # record passed every shape check and was then silently dropped by the select,
  # LOWERING the sum to 1 (an under-count files straight past the cap) instead of
  # unestablishing it. The fixture pairs the corrupt record with a legitimately
  # matching one precisely so the under-count is observable: without the guard this
  # arm reads `1`, with it, empty.
  printf '%s' '{"schema_version":3,"patterns":{"bad":{"category":42,"state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"tg--a":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":2,"state":"filed"}]}},"dismissed":{}}' > "$RL_TMP/percat-cat-number.json"
  assert_eq "#891 for_category: a numeric category unestablishes the count rather than under-counting" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-cat-number.json" tooling-gap 2>/dev/null)"
  # A null `category` takes the same arm.
  printf '%s' '{"schema_version":3,"patterns":{"bad":{"category":null,"state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"tg--a":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":2,"state":"filed"}]}},"dismissed":{}}' > "$RL_TMP/percat-cat-null.json"
  assert_eq "#891 for_category: a null category unestablishes the count rather than under-counting" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-cat-null.json" tooling-gap 2>/dev/null)"
  # An ABSENT `category` (a half-migrated v2 record) takes the same arm.
  printf '%s' '{"schema_version":3,"patterns":{"bad":{"state":"filed","meta_issues":[{"number":1,"state":"filed"}]},"tg--a":{"category":"tooling-gap","state":"filed","meta_issues":[{"number":2,"state":"filed"}]}},"dismissed":{}}' > "$RL_TMP/percat-cat-absent.json"
  assert_eq "#891 for_category: an absent category unestablishes the count rather than under-counting" "" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat-cat-absent.json" tooling-gap 2>/dev/null)"
  # The guard must not fire on the HAPPY path: an all-string-category document still
  # counts (otherwise the arms above would pass vacuously against a helper that
  # unestablishes everything).
  assert_eq "#891 for_category: the category-is-string guard does not fire on a well-formed document" "2" \
    "$(devflow_open_filed_for_category "$RL_TMP/percat.json" tooling-gap 2>/dev/null)"
)

# ── actionable-patterns emits the attribution category ───────────────────────
printf '%s\n' '{"kind":"implementation","pr":1,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}' > "$RL_TMP/cat-r.jsonl"
printf '%s' "$RL_SUB_OV" > "$RL_TMP/cat-ov.json"
RL_CATOUT="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" bash "$RL_AP" "$RL_TMP/cat-r.jsonl" "$RL_TMP/cat-ov.json" --full 2>/dev/null)"
assert_eq "#891 actionable: each emitted pattern object carries its attribution category" "tooling-gap" \
  "$(printf '%s' "$RL_CATOUT" | jq -r '.[] | select(.tag=="tooling-gap-slow-suite") | .category')"

# ── render-report: a differing key/category renders both; equal renders one ──
# Source render-report.sh inside the command-substitution subshell so its
# `set -euo pipefail` never leaks into this module shell (same discipline as the
# filing-decisions `( set +e; . )` blocks above).
RL_REND_DIFF="$( . "$REPO_ROOT/lib/render-report.sh"; devflow_render_report '{"patterns":[{"tag":"tooling-gap-slow-suite","category":"tooling-gap","occurrence_count":2,"status":"regressed"}]}' )"
assert_eq "#891 render: a row whose key differs from its category names both" "true" \
  "$(printf '%s' "$RL_REND_DIFF" | grep -qF '(category: `tooling-gap`)' && echo true || echo false)"
RL_REND_SAME="$( . "$REPO_ROOT/lib/render-report.sh"; devflow_render_report '{"patterns":[{"tag":"tooling-gap","category":"tooling-gap","occurrence_count":2,"status":"open"}]}' )"
assert_eq "#891 render: an equal key/category renders the single-name row (no category clause)" "false" \
  "$(printf '%s' "$RL_REND_SAME" | grep -qF '(category:' && echo true || echo false)"

# ════════════════════════════════════════════════════════════════════════════
echo "#893 Stage B findings: enrichment + select-findings + report"
# ════════════════════════════════════════════════════════════════════════════
RL_SF="$REPO_ROOT/lib/select-findings.sh"

# ── enrichment: occurrences carry per-occurrence summary/descriptors/SI ───────
RL_ENR_CORPUS='{"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"],"summary":"slow suite","descriptors":["d1"],"suggested_interventions":[{"summary":"si1"}]}'
RL_ENR_VIEW="$(rl_cp "$RL_ENR_CORPUS" '{"schema_version":3,"patterns":{},"dismissed":{}}')"
assert_eq "#893 enrich: occurrences carry per-occurrence summary" "slow suite" \
  "$(printf '%s' "$RL_ENR_VIEW" | jq -r '."tooling-gap".occurrences[0].summary')"
assert_eq "#893 enrich: occurrences carry per-occurrence descriptors" "d1" \
  "$(printf '%s' "$RL_ENR_VIEW" | jq -r '."tooling-gap".occurrences[0].descriptors[0]')"
assert_eq "#893 enrich: occurrences carry per-occurrence suggested_interventions" "si1" \
  "$(printf '%s' "$RL_ENR_VIEW" | jq -r '."tooling-gap".occurrences[0].suggested_interventions[0].summary')"

# ── enrichment: absent fields default without aborting ────────────────────────
RL_ENR_ABSENT='{"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"]}'
RL_ENR_AVIEW="$(rl_cp "$RL_ENR_ABSENT" '{"schema_version":3,"patterns":{},"dismissed":{}}')"; RL_ENR_ARC=$?
assert_eq "#893 enrich: an absent-field entry derives with exit 0" "0" "$RL_ENR_ARC"
assert_eq "#893 enrich: absent summary defaults to null" "null" \
  "$(printf '%s' "$RL_ENR_AVIEW" | jq -r '."tooling-gap".occurrences[0].summary')"
assert_eq "#893 enrich: absent descriptors defaults to []" "0" \
  "$(printf '%s' "$RL_ENR_AVIEW" | jq -r '."tooling-gap".occurrences[0].descriptors | length')"
assert_eq "#893 enrich: absent suggested_interventions defaults to []" "0" \
  "$(printf '%s' "$RL_ENR_AVIEW" | jq -r '."tooling-gap".occurrences[0].suggested_interventions | length')"

# ── enrichment: wrong-typed fields default without aborting; count unchanged ──
RL_ENR_BADSUM='{"kind":"implementation","pr":1,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"],"summary":123,"descriptors":"nope","suggested_interventions":"x"}'
RL_ENR_BVIEW="$(rl_cp "$RL_ENR_BADSUM" '{"schema_version":3,"patterns":{},"dismissed":{}}')"; RL_ENR_BRC=$?
assert_eq "#893 enrich: wrong-typed fields derive with exit 0" "0" "$RL_ENR_BRC"
assert_eq "#893 enrich: a wrong-typed summary defaults to null" "null" \
  "$(printf '%s' "$RL_ENR_BVIEW" | jq -r '."tooling-gap".occurrences[0].summary')"
assert_eq "#893 enrich: a wrong-typed summary leaves the occurrence present (count 1)" "1" \
  "$(printf '%s' "$RL_ENR_BVIEW" | jq -r '."tooling-gap".occurrence_count')"

# descriptors_for: a non-string element in .descriptors (a number, an object) is
# neither null nor "" and must not survive into the category-level union — only
# `select(. != null and . != "")` would let it through (a receiving-review
# reception fix, PR #904).
RL_ENR_MIXED='{"kind":"implementation","pr":2,"merged_at":"2026-01-01T00:00:00Z","verdict":"imperfect","categories":["tooling-gap"],"descriptors":["real descriptor",42,{"x":1},null,""]}'
RL_ENR_MVIEW="$(rl_cp "$RL_ENR_MIXED" '{"schema_version":3,"patterns":{},"dismissed":{}}')"
assert_eq "#893 descriptors_for: a non-string element is excluded from the category union" "1" \
  "$(printf '%s' "$RL_ENR_MVIEW" | jq -r '."tooling-gap".descriptors | length')"
assert_eq "#893 descriptors_for: the surviving element is the real string descriptor" "real descriptor" \
  "$(printf '%s' "$RL_ENR_MVIEW" | jq -r '."tooling-gap".descriptors[0]')"

# ── select-findings: helper setup ────────────────────────────────────────────
# TMP_SF is this block's runtime scratch handle (the same mktemp -d dir as $RL_TMP).
# The greps below read what THIS run produced — devflow_select_findings' captured
# stderr — not repository source, so they are executable helper-contract assertions
# rather than source-presence pins; the TMP_ prefix is pin-corpus-lint.py's own
# declaration for a runtime scratch haystack (see its raw-guard carve-out).
TMP_SF="$RL_TMP"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_SF/sf-ov.json"
# rl_sf <args...> — source select-findings inside a subshell (no set -e leak) and
# call devflow_select_findings; stdout is captured, stderr routed under $TMP_SF.
# shellcheck disable=SC1090  # $RL_SF is the select-findings.sh path under test
rl_sf() { ( . "$RL_SF"; devflow_select_findings "$@" ); }
# shellcheck disable=SC1090  # $RL_SF is the select-findings.sh path under test
rl_sf_projection() { ( . "$RL_SF"; devflow_projection_eligible_findings "$@" ); }

# Issue #1515: Stage B's filing boundary consumes structured projection state for
# every finding. One invalid finding is omitted without suppressing clean siblings.
printf '%s' '[{"subslug":"clean","title":"C","body":"b","evidence_prs":[1],"rationale":"r","projection_disposition":"represented","unmatched_desired_behavior":[]},{"subslug":"bad","title":"B","body":"b","evidence_prs":[2],"rationale":"r","projection_disposition":"represented","unmatched_desired_behavior":["missing outcome"]},{"subslug":"missing","title":"M","body":"b","evidence_prs":[3],"rationale":"r"}]' > "$TMP_SF/sf-projection.json"
RL_SF_PROJECTED="$(rl_sf_projection "$TMP_SF/sf-projection.json" 2>"$TMP_SF/sf-projection.err")"; RL_SF_PROJECTED_RC=$?
assert_eq "#1515 projection filter succeeds while omitting degraded findings" "0" "$RL_SF_PROJECTED_RC"
assert_eq "#1515 projection filter returns only represented plus zero-unmatched" "clean" \
  "$(printf '%s' "$RL_SF_PROJECTED" | jq -r '.[].subslug')"
assert_eq "#1515 projection filter durably reports unmatched and missing findings" "2" \
  "$(grep -c 'projection disposition is unusable' "$TMP_SF/sf-projection.err")"

# The withhold-everything arms: each must exit non-zero and emit nothing on stdout,
# so a regression flipping one to fail-open (empty array, rc 0) turns these RED.
printf '%s' '{"not":"an array"}' > "$TMP_SF/sf-projection-obj.json"
printf 'not json' > "$TMP_SF/sf-projection-garbage.json"
for _case in absent:"$TMP_SF/sf-projection-nonexistent.json" \
             empty-arg:"" \
             nonarray:"$TMP_SF/sf-projection-obj.json" \
             unparseable:"$TMP_SF/sf-projection-garbage.json"; do
  _label="${_case%%:*}"; _path="${_case#*:}"
  RL_SF_BAD="$(rl_sf_projection "$_path" 2>"$TMP_SF/sf-projection-$_label.err")"; RL_SF_BAD_RC=$?
  assert_eq "#1515 projection filter withholds on $_label input (non-zero)" "1" "$RL_SF_BAD_RC"
  assert_eq "#1515 projection filter emits no findings on $_label input" "" "$RL_SF_BAD"
  assert_eq "#1515 projection filter names the $_label withhold on its error channel" "1" \
    "$(grep -c 'withholding every finding' "$TMP_SF/sf-projection-$_label.err")"
done
# An unavailable predicate is the same withhold: copy select-findings.sh to a
# directory with no projection-gate.jq beside it and confirm it refuses.
mkdir -p "$TMP_SF/nogate" && cp "$REPO_ROOT"/lib/*.sh "$REPO_ROOT"/lib/*.jq "$TMP_SF/nogate/"
rm -f "$TMP_SF/nogate/projection-gate.jq"
RL_SF_NOGATE="$( ( # shellcheck disable=SC1090  # relocated copy under test
  . "$TMP_SF/nogate/select-findings.sh"; devflow_projection_eligible_findings "$TMP_SF/sf-projection.json" ) 2>"$TMP_SF/sf-projection-nogate.err")"
RL_SF_NOGATE_RC=$?
assert_eq "#1515 projection filter withholds when projection-gate.jq is unavailable" "1" "$RL_SF_NOGATE_RC"
assert_eq "#1515 projection filter emits no findings without its predicate" "" "$RL_SF_NOGATE"
assert_eq "#1515 projection filter names the missing predicate" "1" \
  "$(grep -c 'projection-gate.jq is unavailable' "$TMP_SF/sf-projection-nogate.err")"

RL_WEEKLY="$REPO_ROOT/skills/retrospective-weekly/SKILL.md"
_rl1515_weekly_boundary() {
  python3 - "$RL_WEEKLY" "$1" <<'PY'
import pathlib,re,sys
t=pathlib.Path(sys.argv[1]).read_text(); m=sys.argv[2]
if m=='remove-array': t=t.replace('devflow_projection_eligible_findings', 'projection_filter_REMOVED')
if m=='invert-array': t=t.replace('elif ! devflow_projection_eligible_findings', 'elif devflow_projection_eligible_findings')
if m=='remove-legacy': t=t.replace('-f $LIB/projection-gate.jq', '-f $LIB/projection-gate.REMOVED')
if m=='invert-legacy': t=t.replace('if ! $LIB/../scripts/run-jq.sh -e -f $LIB/projection-gate.jq', 'if $LIB/../scripts/run-jq.sh -e -f $LIB/projection-gate.jq')
a='elif ! devflow_projection_eligible_findings' in t and 'projection-filtered finding set' in t
l='if ! $LIB/../scripts/run-jq.sh -e -f $LIB/projection-gate.jq' in t and 'legacy Stage B result omitted' in t
print('bound' if a and l else 'caught')
PY
}
assert_eq "#1515 weekly boundary gates array and legacy results" "bound" "$(_rl1515_weekly_boundary live)"
for mutation in remove-array invert-array remove-legacy invert-legacy; do
  assert_eq "#1515 weekly production mutation $mutation is caught" "caught" "$(_rl1515_weekly_boundary "$mutation")"
done

# select: compose + descending evidence order + truncate top 3
printf '%s' '[{"subslug":"aa","title":"A","body":"b","evidence_prs":[1],"rationale":"r"},{"subslug":"bb","title":"B","body":"b","evidence_prs":[2,3,4],"rationale":"r"},{"subslug":"cc","title":"C","body":"b","evidence_prs":[5,6],"rationale":"r"},{"subslug":"dd","title":"D","body":"b","evidence_prs":[7],"rationale":"r"}]' > "$TMP_SF/sf-f4.json"
RL_SF_OUT="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf.err")"
assert_eq "#893 file: a fourth finding is truncated to the top three" "3" \
  "$(printf '%s' "$RL_SF_OUT" | jq 'length')"
assert_eq "#893 select: findings ordered descending by evidence-PR count (first is bb, 3 PRs)" "tooling-gap-bb" \
  "$(printf '%s' "$RL_SF_OUT" | jq -r '.[0].key')"
assert_eq "#893 file: the truncation drop is reported naming the pattern" "true" \
  "$(grep -qF 'dropping 1' "$TMP_SF/sf.err" && echo true || echo false)"
assert_eq "#893 select: a finding key is composed through the shipped composer" "true" \
  "$(printf '%s' "$RL_SF_OUT" | jq -e 'all(.[]; .key | test("^[A-Za-z0-9_-]+$"))' >/dev/null && echo true || echo false)"

# select: an illegal/empty subslug is dropped with a breadcrumb and the rest survive
printf '%s' '[{"subslug":"","title":"empty","body":"b","evidence_prs":[1],"rationale":"r"},{"subslug":"good","title":"G","body":"b","evidence_prs":[2],"rationale":"r"}]' > "$TMP_SF/sf-illegal.json"
RL_SF_ILL="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-illegal.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-ill.err")"
assert_eq "#893 select: an empty subslug is dropped, the rest survive" "1" \
  "$(printf '%s' "$RL_SF_ILL" | jq 'length')"
assert_eq "#893 select: the dropped finding leaves a named breadcrumb" "true" \
  "$(grep -qF 'absent or empty subslug' "$TMP_SF/sf-ill.err" && echo true || echo false)"

# inject: an instruction-shaped subslug is slugified or dropped, never obeyed
printf '%s' '[{"subslug":"drop table in:title `rm -rf`","title":"X","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-inject.json"
RL_SF_INJ="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-inject.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null)"
assert_eq "#893 inject: an instruction-shaped subslug yields a grammar-safe key (no qualifier/backtick)" "true" \
  "$(printf '%s' "$RL_SF_INJ" | jq -e 'all(.[]; .key | test("^[a-z0-9-]+$"))' >/dev/null && echo true || echo false)"

# select: equal token sets alias onto the existing key
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap-slow-suite":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":10,"url":"https://x/issues/10","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$TMP_SF/sf-alias-ov.json"
printf '%s' '[{"subslug":"suite-slow","title":"Aliased","body":"b","evidence_prs":[1,2],"rationale":"r"}]' > "$TMP_SF/sf-alias-f.json"
RL_SF_AL="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-alias-f.json" --overrides "$TMP_SF/sf-alias-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-al.err")"
assert_eq "#893 select: equal subslug token sets alias onto the existing key" "tooling-gap-slow-suite" \
  "$(printf '%s' "$RL_SF_AL" | jq -r '.[0].key')"
assert_eq "#893 select: the alias is reported" "true" \
  "$(grep -qF 'aliased finding' "$TMP_SF/sf-al.err" && echo true || echo false)"

# NEGATIVE CONTROL for the category-prefix collision: the alias signature is taken
# over the SUBSLUG, never the composed key. A full-key signature would collapse the
# category's own tokens into the comparison (`unique` drops the duplicate), making
# subslug `gap-slow` collide with the existing `tooling-gap-slow` record and merging
# two distinct sub-patterns onto one lifecycle record. It must coin its own key.
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap-slow":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":11,"url":"https://x/issues/11","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$TMP_SF/sf-collide-ov.json"
printf '%s' '[{"subslug":"gap-slow","title":"Distinct","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-collide-f.json"
RL_SF_CL="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-collide-f.json" --overrides "$TMP_SF/sf-collide-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-cl.err")"
assert_eq "#893 select: a subslug sharing a token with its category does NOT alias onto the existing record" "tooling-gap-gap-slow" \
  "$(printf '%s' "$RL_SF_CL" | jq -r '.[0].key')"
assert_eq "#893 select: the category-prefix collision emits no alias breadcrumb" "false" \
  "$(grep -qF 'aliased finding' "$TMP_SF/sf-cl.err" && echo true || echo false)"

# A record whose key does NOT carry the canonical `<category>-` prefix (a bare-category
# legacy filing) is not comparable by subslug and is never aliased onto.
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[]}},"dismissed":{}}' > "$TMP_SF/sf-bare-ov.json"
printf '%s' '[{"subslug":"tooling-gap","title":"X","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-bare-f.json"
assert_eq "#893 select: a bare-category legacy record is never aliased onto" "tooling-gap-tooling-gap" \
  "$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-bare-f.json" --overrides "$TMP_SF/sf-bare-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null | jq -r '.[0].key')"

# The grammar check runs on the FINAL key, after the alias. An existing record whose
# key is illegal (hand-edited, or an older/looser writer) must be DROPPED, not emitted
# — lib/meta-issue.sh refuses such a key, so emitting it turns a silent alias into a
# failed filing.
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap-slow!!!x":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[]}},"dismissed":{}}' > "$TMP_SF/sf-badkey-ov.json"
printf '%s' '[{"subslug":"slow-x","title":"X","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-badkey-f.json"
RL_SF_BK="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-badkey-f.json" --overrides "$TMP_SF/sf-badkey-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-bk.err")"
assert_eq "#893 select: an aliased-onto key outside the grammar is dropped, not emitted" "0" \
  "$(printf '%s' "$RL_SF_BK" | jq 'length')"
assert_eq "#893 select: the illegal aliased key drop names the grammar" "true" \
  "$(grep -qF 'falls outside the [A-Za-z0-9_-]+ grammar' "$TMP_SF/sf-bk.err" && echo true || echo false)"

# --dropped-file: the top-three truncation's drop count reaches a STRUCTURED channel,
# not only stderr — the orchestrator captures stdout, so a stderr-only notice can
# never reach the run report (the >3-findings disclosure would be undischarged).
rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 --dropped-file "$TMP_SF/sf-drop.json" >/dev/null 2>&1
assert_eq "#893 select: the truncation drop count is published to --dropped-file" "1" \
  "$(jq -r '.[0].dropped' "$TMP_SF/sf-drop.json" 2>/dev/null)"
assert_eq "#893 select: the dropped-file record names the pattern category" "tooling-gap" \
  "$(jq -r '.[0].category' "$TMP_SF/sf-drop.json" 2>/dev/null)"
assert_eq "#893 select: the dropped-file record carries the pre-truncation total" "4" \
  "$(jq -r '.[0].total' "$TMP_SF/sf-drop.json" 2>/dev/null)"
# Negative control: with no truncation the file is written as an EMPTY array, so an
# absent file is distinguishable from "nothing was dropped".
rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-alias-f.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 --dropped-file "$TMP_SF/sf-drop2.json" >/dev/null 2>&1
assert_eq "#893 select: no truncation writes an empty dropped-file array" "0" \
  "$(jq 'length' "$TMP_SF/sf-drop2.json" 2>/dev/null)"

# select: every cap decision comes from devflow_filing_cap_verdict (withhold on max_per_run 0)
RL_SF_CAP="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 0 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-cap.err")"
assert_eq "#893 select: a zero per-run cap withholds every finding" "0" \
  "$(printf '%s' "$RL_SF_CAP" | jq 'length')"
assert_eq "#893 select: the cap withhold names devflow_filing_cap_verdict's cap token" "true" \
  "$(grep -qF 'max_issues_per_run' "$TMP_SF/sf-cap.err" && echo true || echo false)"
# withheld-file discloses each cap-withheld finding as {tag, cap} for the report (#788)
rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 0 --max-per-cat 99 --max-open 99 --withheld-file "$TMP_SF/sf-wh.json" >/dev/null 2>&1
assert_eq "#893 select: cap-withheld findings are disclosed to the withheld-file as {tag,cap}" "max_issues_per_run" \
  "$(jq -r '.[0].cap' "$TMP_SF/sf-wh.json" 2>/dev/null)"

# select: the cap comparand GROWS incrementally within one call as findings are
# accepted (`_filed_here`), not evaluated once against the pre-call snapshot. Three
# legal findings (top-3-truncated from sf-f4.json: bb/3prs, cc/2prs, aa/1pr, ranked
# descending) against --max-per-run 2 must file exactly the first 2 by rank and
# withhold the 3rd — a regression that dropped the `_filed_here` increment would
# file all 3 past the cap (every existing cap test here is all-or-nothing and would
# not catch it).
RL_SF_MIDCAP="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 2 --max-per-cat 99 --max-open 99 --withheld-file "$TMP_SF/sf-midcap-wh.json" 2>/dev/null)"
assert_eq "#893 select: a mid-call cap (max-per-run 2 on 3 legal findings) files exactly 2" "2" \
  "$(printf '%s' "$RL_SF_MIDCAP" | jq 'length')"
assert_eq "#893 select: the mid-call cap files the top 2 by rank (bb then cc)" "tooling-gap-bb tooling-gap-cc" \
  "$(printf '%s' "$RL_SF_MIDCAP" | jq -r '[.[].key] | join(" ")')"
assert_eq "#893 select: the mid-call cap withholds exactly the 3rd-ranked finding (aa)" "1" \
  "$(jq 'length' "$TMP_SF/sf-midcap-wh.json" 2>/dev/null)"
assert_eq "#893 select: the withheld 3rd finding is named aa, not a wrong one" "tooling-gap-aa" \
  "$(jq -r '.[0].tag' "$TMP_SF/sf-midcap-wh.json" 2>/dev/null)"

# select: per-category comparand aggregates across a category's records (issue #891)
# Two filed records of one category, each holding one open issue → per-cat base is 2.
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap-a":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":1,"state":"filed"}]},"tooling-gap-b":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":2,"state":"filed"}]}},"dismissed":{}}' > "$TMP_SF/sf-agg-ov.json"
printf '%s' '[{"subslug":"cc","title":"C","body":"b","evidence_prs":[9],"rationale":"r"}]' > "$TMP_SF/sf-agg-f.json"
RL_SF_AGG="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-agg-f.json" --overrides "$TMP_SF/sf-agg-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 2 --max-open 99 2>/dev/null)"
assert_eq "#893 select: the per-category comparand aggregates (2 records hit max-per-cat 2 → withhold)" "0" \
  "$(printf '%s' "$RL_SF_AGG" | jq 'length')"

# select: an unmigrated/absent overrides file withholds and returns non-zero (no stdout)
printf '%s' '{"schema_version":2,"patterns":{},"dismissed":{}}' > "$TMP_SF/sf-v2.json"
RL_SF_V2="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-v2.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null)"; RL_SF_V2_RC=$?
assert_eq "#893 select: an unmigrated overrides file returns non-zero" "true" "$([ "$RL_SF_V2_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: an unmigrated overrides file emits nothing on stdout" "" "$RL_SF_V2"
RL_SF_ABS="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$RL_TMP/does-not-exist.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null)"; RL_SF_ABS_RC=$?
assert_eq "#893 select: an absent overrides file withholds (non-zero, no key coined)" "true" "$([ "$RL_SF_ABS_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: an absent overrides file emits nothing on stdout" "" "$RL_SF_ABS"

# select: an EMPTY (zero-byte, present) overrides file withholds distinctly from an
# absent one — the `[ ! -s ]` arm of the same guard.
: > "$TMP_SF/sf-empty-ov.json"
RL_SF_EMPTYOV="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-empty-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null)"; RL_SF_EMPTYOV_RC=$?
assert_eq "#893 select: a zero-byte overrides file withholds (non-zero)" "true" "$([ "$RL_SF_EMPTYOV_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: a zero-byte overrides file emits nothing on stdout" "" "$RL_SF_EMPTYOV"

# select: an UNREADABLE (present, non-zero-byte, permission-denied) overrides file
# withholds distinctly from absent/empty — the `[ ! -r ]` arm of the same guard.
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$TMP_SF/sf-unreadable-ov.json"
chmod 000 "$TMP_SF/sf-unreadable-ov.json"
if [ ! -r "$TMP_SF/sf-unreadable-ov.json" ]; then
    RL_SF_UNREAD="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-unreadable-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>/dev/null)"; RL_SF_UNREAD_RC=$?
    assert_eq "#893 select: an unreadable overrides file withholds (non-zero)" "true" "$([ "$RL_SF_UNREAD_RC" -ne 0 ] && echo true || echo false)"
    assert_eq "#893 select: an unreadable overrides file emits nothing on stdout" "" "$RL_SF_UNREAD"
else
    # Running as root (or on a filesystem where chmod 000 doesn't deny the owner's
    # own read) makes this arm unobservable — skip rather than assert a false premise.
    module_host_capability_skip "#893 select: an unreadable overrides file withholds" \
      "chmod 000 did not deny read access in this environment (root or a permissive filesystem)" 2
fi
chmod 644 "$TMP_SF/sf-unreadable-ov.json"

# select: a subslug that canonicalizes to the EMPTY STRING (pure punctuation, e.g.
# "!!!") is a genuine compose-filing-key.sh REJECTION (its own hard-reject arm,
# exit 2) — distinct from the missing/non-executable composer case tested above.
printf '%s' '[{"subslug":"!!!","title":"X","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-composereject.json"
RL_SF_CR="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-composereject.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-cr.err")"
assert_eq "#893 select: a subslug canonicalizing to empty is dropped (composer rejection)" "0" \
  "$(printf '%s' "$RL_SF_CR" | jq 'length')"
assert_eq "#893 select: the composer-rejection drop names compose-filing-key.sh as the source" "true" \
  "$(grep -qF 'compose-filing-key.sh rejected subslug' "$TMP_SF/sf-cr.err" && echo true || echo false)"

# select: the alias-DISTINCTNESS negative — the load-bearing half of the alias
# contract. A subslug differing from an existing record's subslug by even ONE
# token must stay DISTINCT and compose its own key, never alias onto it. Without
# this negative, a signature comparison that accidentally matched too broadly
# (e.g. dropped a token, or ignored word order in a way that over-collapses)
# would pass every existing alias-POSITIVE test while still merging distinct
# sub-patterns undetected.
printf '%s' '{"schema_version":3,"patterns":{"tooling-gap-slow-suite":{"category":"tooling-gap","state":"filed","fixed_at":null,"provenance":"2026-01-01T00:00:00Z","meta_issues":[{"number":12,"url":"https://x/issues/12","state":"filed","closedAt":null}]}},"dismissed":{}}' > "$TMP_SF/sf-distinct-ov.json"
printf '%s' '[{"subslug":"suite-slow-timeout","title":"Distinct","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-distinct-f.json"
RL_SF_DIST="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-distinct-f.json" --overrides "$TMP_SF/sf-distinct-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-dist.err")"
assert_eq "#893 select: a subslug differing by one token stays distinct (no alias)" "tooling-gap-suite-slow-timeout" \
  "$(printf '%s' "$RL_SF_DIST" | jq -r '.[0].key')"
assert_eq "#893 select: the distinct-subslug case emits no alias breadcrumb" "false" \
  "$(grep -qF 'aliased finding' "$TMP_SF/sf-dist.err" && echo true || echo false)"

# select: an unsourceable cap owner withholds and returns non-zero, printing nothing
# Copy select-findings WITHOUT filing-decisions.sh beside it → the source fails and
# the withhold stub takes over.
cp "$RL_SF" "$RL_TMP/orphan-select.sh"
RL_SF_ORPH="$( ( . "$RL_TMP/orphan-select.sh" 2>/dev/null; devflow_select_findings --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 ) 2>/dev/null )"; RL_SF_ORPH_RC=$?
assert_eq "#893 select: an unsourceable cap owner returns non-zero" "true" "$([ "$RL_SF_ORPH_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: an unsourceable cap owner emits nothing on stdout" "" "$RL_SF_ORPH"

# report: the intervention_issues emitter names each filed issue by key and category
RL_REND_KEY="$( . "$REPO_ROOT/lib/render-report.sh"; devflow_render_report '{"intervention_issues":[{"key":"tooling-gap-slow-suite","category":"tooling-gap","url":"https://x/issues/5"}]}' )"
assert_eq "#893 report: a filed issue is named by its filing key" "true" \
  "$(printf '%s' "$RL_REND_KEY" | grep -qF '`tooling-gap-slow-suite`' && echo true || echo false)"
assert_eq "#893 report: a filed issue names its category" "true" \
  "$(printf '%s' "$RL_REND_KEY" | grep -qF '(category: `tooling-gap`)' && echo true || echo false)"

# select: a finding with an absent/empty title or body is dropped, not filed with a
# silently-defaulted empty string (a receiving-review reception fix, PR #904).
printf '%s' '[{"subslug":"no-title","title":"","body":"b","evidence_prs":[1],"rationale":"r"},{"subslug":"no-body","title":"T","body":"","evidence_prs":[1],"rationale":"r"},{"subslug":"good","title":"T","body":"b","evidence_prs":[1],"rationale":"r"}]' > "$TMP_SF/sf-empty-tb.json"
RL_SF_ETB="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-empty-tb.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-etb.err")"
assert_eq "#893 select: a finding with an empty title is dropped, only the good one survives" "1" \
  "$(printf '%s' "$RL_SF_ETB" | jq 'length')"
assert_eq "#893 select: the surviving finding is the one with both title and body" "tooling-gap-good" \
  "$(printf '%s' "$RL_SF_ETB" | jq -r '.[0].key')"
assert_eq "#893 select: the empty-title drop names which field was missing" "true" \
  "$(grep -qF 'title empty: yes, body empty: no' "$TMP_SF/sf-etb.err" && echo true || echo false)"
assert_eq "#893 select: the empty-body drop names which field was missing" "true" \
  "$(grep -qF 'title empty: no, body empty: yes' "$TMP_SF/sf-etb.err" && echo true || echo false)"

# select: two findings that compose/alias onto the SAME key within one call are not
# both accepted — the second is dropped as a duplicate, not double-filed.
printf '%s' '[{"subslug":"dup-x","title":"First","body":"b","evidence_prs":[1],"rationale":"r"},{"subslug":"dup-x","title":"Second","body":"b","evidence_prs":[2],"rationale":"r"}]' > "$TMP_SF/sf-dupkey.json"
RL_SF_DUP="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-dupkey.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-dup.err")"
assert_eq "#893 select: a second finding composing to an already-accepted key is dropped" "1" \
  "$(printf '%s' "$RL_SF_DUP" | jq 'length')"
assert_eq "#893 select: the surviving finding is the first-accepted one" "First" \
  "$(printf '%s' "$RL_SF_DUP" | jq -r '.[0].title')"
assert_eq "#893 select: the duplicate-key drop leaves a named breadcrumb" "true" \
  "$(grep -qF 'was already accepted earlier in this same selection' "$TMP_SF/sf-dup.err" && echo true || echo false)"

# select: a missing/non-executable compose-filing-key.sh is reported as an
# infrastructure failure, not misdiagnosed as an illegal subslug — and withholds
# the whole pattern (return non-zero) rather than silently dropping one finding.
# Copy the WHOLE lib/ directory (so every sibling sourced by resolve-jq.sh /
# filing-decisions.sh resolves via the copy's own BASH_SOURCE) and delete just
# the composer from the copy.
RL_SF_NOCOMPOSER_DIR="$RL_TMP/nocomposer-lib"
cp -R "$REPO_ROOT/lib" "$RL_SF_NOCOMPOSER_DIR"
rm -f "$RL_SF_NOCOMPOSER_DIR/compose-filing-key.sh"
printf '%s' '[{"subslug":"good","title":"G","body":"b","evidence_prs":[2],"rationale":"r"}]' > "$TMP_SF/sf-onegood.json"
RL_SF_NC="$( ( . "$RL_SF_NOCOMPOSER_DIR/select-findings.sh"; devflow_select_findings --category tooling-gap --findings-file "$TMP_SF/sf-onegood.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 ) 2>"$TMP_SF/sf-nc.err" )"; RL_SF_NC_RC=$?
assert_eq "#893 select: a missing compose-filing-key.sh returns non-zero (withhold, not a per-finding drop)" "true" \
  "$([ "$RL_SF_NC_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: a missing compose-filing-key.sh emits nothing on stdout" "" "$RL_SF_NC"
assert_eq "#893 select: the missing-composer breadcrumb names it as unavailable, not an illegal subslug" "true" \
  "$(grep -qF 'compose-filing-key.sh' "$TMP_SF/sf-nc.err" && grep -qF 'unavailable' "$TMP_SF/sf-nc.err" && echo true || echo false)"
assert_eq "#893 select: the missing-composer breadcrumb never claims an illegal subslug" "true" \
  "$(grep -qF 'illegal subslug' "$TMP_SF/sf-nc.err" && echo false || echo true)"

# select: --filed-this-run is validated as a non-negative integer before feeding the
# `$(( filed_this_run + _filed_here ))` arithmetic — an empty value must withhold
# (return non-zero, no stdout), not be silently coerced to 0 by bash arithmetic.
RL_SF_BADFTR="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-illegal.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run "" --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-ftr.err")"; RL_SF_BADFTR_RC=$?
assert_eq "#893 select: an empty --filed-this-run returns non-zero" "true" \
  "$([ "$RL_SF_BADFTR_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: an empty --filed-this-run emits nothing on stdout" "" "$RL_SF_BADFTR"
assert_eq "#893 select: the empty --filed-this-run breadcrumb names the flag" "true" \
  "$(grep -qF -- '--filed-this-run is not a non-negative integer' "$TMP_SF/sf-ftr.err" && echo true || echo false)"

# select: rc-2 (wiring/argument fault) vs rc-1 (data/owner withhold) — Step 8c
# branches its blocker message on `_SF_RC -eq 2`, and every existing negative test
# only asserted `-ne 0`. Pin `-eq 2` on the missing-required-argument and
# unknown-argument paths, and `-eq 1` on the empty --filed-this-run path above,
# so a regression flipping either return code between 1 and 2 is caught rather
# than misreporting a wiring fault as ordinary back-pressure.
assert_eq "#893 select: an empty --filed-this-run returns exactly rc 2 (wiring fault), not rc 1" "2" "$RL_SF_BADFTR_RC"
RL_SF_MISSING="$(rl_sf --category tooling-gap --findings-file "" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-missing.err")"; RL_SF_MISSING_RC=$?
assert_eq "#893 select: a missing required --findings-file returns exactly rc 2" "2" "$RL_SF_MISSING_RC"
assert_eq "#893 select: a missing required --findings-file emits nothing on stdout" "" "$RL_SF_MISSING"
assert_eq "#893 select: the missing-argument breadcrumb names it" "true" \
  "$(grep -qF 'missing required argument' "$TMP_SF/sf-missing.err" && echo true || echo false)"
RL_SF_UNKNOWN="$(rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-f4.json" --overrides "$TMP_SF/sf-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 --bogus-flag x 2>"$TMP_SF/sf-unknown.err")"; RL_SF_UNKNOWN_RC=$?
assert_eq "#893 select: an unknown argument returns exactly rc 2" "2" "$RL_SF_UNKNOWN_RC"
assert_eq "#893 select: an unknown argument emits nothing on stdout" "" "$RL_SF_UNKNOWN"
assert_eq "#893 select: the unknown-argument breadcrumb names the flag" "true" \
  "$(grep -qF -- 'unknown argument '\''--bogus-flag'\''' "$TMP_SF/sf-unknown.err" && echo true || echo false)"
# rc-1 positive control on the SAME kind of split: the data/owner withhold path
# (absent overrides, already tested above) returns exactly rc 1, distinct from 2.
assert_eq "#893 select: an absent overrides file (data withhold) returns exactly rc 1, not rc 2" "1" "$RL_SF_ABS_RC"

# select: an alias-lookup jq EXECUTION ERROR (not a clean empty match) withholds
# the finding — fails CLOSED — rather than being coerced to "no existing record"
# and composing a fresh key past a real alias (a receiving-review reception fix,
# PR #904). A selective-fail jq shim fails ONLY the alias-lookup program (its
# distinctive `tokset` function name) and delegates every other jq call in the
# same run to the real jq — attributing the rejection to the alias lookup
# specifically, not to an earlier unrelated jq call in the same function.
cat > "$TMP_SF/selective-fail-jq.sh" <<'SHIM'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in
    *tokset*) echo "selective-fail-jq: forced failure for a tokset (alias-lookup) program" >&2; exit 1 ;;
  esac
done
exec jq "$@"
SHIM
chmod +x "$TMP_SF/selective-fail-jq.sh"
RL_SF_JQFAIL="$(DEVFLOW_JQ="$TMP_SF/selective-fail-jq.sh" rl_sf --category tooling-gap --findings-file "$TMP_SF/sf-alias-f.json" --overrides "$TMP_SF/sf-alias-ov.json" --status open --filed-this-run 0 --max-per-run 99 --max-per-cat 99 --max-open 99 2>"$TMP_SF/sf-jqfail.err")"; RL_SF_JQFAIL_RC=$?
assert_eq "#893 select: an alias-lookup jq failure returns non-zero (withhold)" "true" "$([ "$RL_SF_JQFAIL_RC" -ne 0 ] && echo true || echo false)"
assert_eq "#893 select: an alias-lookup jq failure emits nothing on stdout" "" "$RL_SF_JQFAIL"
assert_eq "#893 select: the alias-lookup jq failure breadcrumb names the alias lookup" "true" \
  "$(grep -qF 'alias-lookup query' "$TMP_SF/sf-jqfail.err" && echo true || echo false)"
# Positive control on the SAME fixture: with the real jq (no shim), this exact
# fixture aliases cleanly (already asserted above as "#893 select: equal subslug
# token sets alias onto the existing key") — so the failure above is attributable
# to the shim's forced jq error, not to some unrelated defect in the fixture.

# ────────────────────────────────────────────────────────────────────────────
# analyzed-digest.jq — Step-9 "Analyzed PRs" digest filter (issue #1870)
# ────────────────────────────────────────────────────────────────────────────
# ad_run <entries-jsonl> -> the digest selection ({pr,verdict,summary}[]) on stdout
ad_run() {
  printf '%s\n' "$1" | jq -sc -f "$LIB/analyzed-digest.jq"
}
# The clean rows are the crux: an analyst-graded clean (populated analysis fields)
# must appear in the digest; a gate-skipped clean (lib/clean-entry.jq defaults:
# categories/descriptors/suggested_interventions all empty) must not.
AD_ENTRIES='{"pr":1,"verdict":"imperfect","summary":"real finding","categories":["doc-accuracy"],"descriptors":["d"],"suggested_interventions":[]}
{"pr":2,"verdict":"blocked","summary":"blocked one","categories":[],"descriptors":[],"suggested_interventions":[]}
{"pr":3,"verdict":"clean","summary":"analyst graded clean","categories":["tooling-gap"],"descriptors":[],"suggested_interventions":[]}
{"pr":4,"verdict":"clean","summary":"gate-skipped clean","categories":[],"descriptors":[],"suggested_interventions":[]}'
AD_VIEW="$(ad_run "$AD_ENTRIES")"
assert_eq "#1870 analyzed-digest: imperfect entry included" "true" \
  "$(printf '%s' "$AD_VIEW" | jq -e 'any(.[]; .pr == 1)' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1870 analyzed-digest: blocked entry included" "true" \
  "$(printf '%s' "$AD_VIEW" | jq -e 'any(.[]; .pr == 2)' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1870 analyzed-digest: analyst-graded clean (populated fields) included" "true" \
  "$(printf '%s' "$AD_VIEW" | jq -e 'any(.[]; .pr == 3)' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1870 analyzed-digest: gate-skipped clean (empty fields) excluded" "false" \
  "$(printf '%s' "$AD_VIEW" | jq -e 'any(.[]; .pr == 4)' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1870 analyzed-digest: selection is exactly {pr,verdict,summary}" "pr summary verdict" \
  "$(printf '%s' "$AD_VIEW" | jq -r '.[0] | keys | sort | join(" ")')"
# A populated descriptors OR suggested_interventions alone also qualifies a clean grade.
AD_VIEW2="$(ad_run '{"pr":5,"verdict":"clean","summary":"only interventions","categories":[],"descriptors":[],"suggested_interventions":[{"kind":"x"}]}')"
assert_eq "#1870 analyzed-digest: clean with only suggested_interventions populated is included" "true" \
  "$(printf '%s' "$AD_VIEW2" | jq -e 'any(.[]; .pr == 5)' >/dev/null 2>&1 && echo true || echo false)"
# Parallel branch: descriptors alone also qualifies a clean grade (completes the OR matrix).
AD_VIEW2B="$(ad_run '{"pr":9,"verdict":"clean","summary":"only descriptors","categories":[],"descriptors":["d"],"suggested_interventions":[]}')"
assert_eq "#1870 analyzed-digest: clean with only descriptors populated is included" "true" \
  "$(printf '%s' "$AD_VIEW2B" | jq -e 'any(.[]; .pr == 9)' >/dev/null 2>&1 && echo true || echo false)"
# A malformed field alongside a valid populated one still qualifies: the per-field
# arrays guard tolerates the bad field while the good field includes the row.
AD_VIEW2C="$(ad_run '{"pr":10,"verdict":"clean","summary":"malformed+valid","categories":"oops","descriptors":["d"],"suggested_interventions":[]}')"
assert_eq "#1870 analyzed-digest: clean with one malformed field but another populated is included" "true" \
  "$(printf '%s' "$AD_VIEW2C" | jq -e 'any(.[]; .pr == 10)' >/dev/null 2>&1 && echo true || echo false)"
# A verdict outside {imperfect,blocked,clean} is excluded.
AD_VIEW4="$(ad_run '{"pr":11,"verdict":"skipped","summary":"unknown verdict","categories":["x"]}')"
assert_eq "#1870 analyzed-digest: an unknown verdict is excluded" "false" \
  "$(printf '%s' "$AD_VIEW4" | jq -e 'any(.[]; .pr == 11)' >/dev/null 2>&1 && echo true || echo false)"
# An empty entry stream yields an empty selection, not an error.
assert_eq "#1870 analyzed-digest: empty input yields []" "[]" \
  "$(printf '' | jq -sc -f "$LIB/analyzed-digest.jq")"
# Robustness: a malformed (non-array) analysis field on one row must not abort the
# whole filter — the well-formed imperfect row on the next line still comes through.
AD_VIEW3="$(ad_run '{"pr":6,"verdict":"clean","summary":"malformed","categories":"oops","descriptors":null,"suggested_interventions":[]}
{"pr":7,"verdict":"imperfect","summary":"ok"}')"
assert_eq "#1870 analyzed-digest: a malformed clean row is excluded, not fatal (imperfect row survives)" "true" \
  "$(printf '%s' "$AD_VIEW3" | jq -e '(any(.[]; .pr == 7)) and ((any(.[]; .pr == 6)) | not)' >/dev/null 2>&1 && echo true || echo false)"
# AC2: compute-patterns.jq still excludes a clean verdict from pattern occurrences.
# The clean fixture below yields occurrence_count 0.
AD_CP_CLEAN="$(cp_run '{"schema_version":2,"kind":"implementation","pr":8,"merged_at":"2026-05-01T00:00:00Z","verdict":"clean","categories":["tooling-gap"],"descriptors":["x"]}' '{"schema_version":2,"patterns":{},"dismissed":{}}')"
assert_eq "#1870 AC2: compute-patterns.jq excludes a clean verdict from occurrences" "true" \
  "$(printf '%s' "$AD_CP_CLEAN" | jq -e '.["tooling-gap"].occurrence_count == 0' >/dev/null 2>&1 && echo true || echo false)"

# ────────────────────────────────────────────────────────────────────────────
# #1828 cost-weighted ranking: compute-patterns.jq joins occurrences (by .pr)
# to experiment-records.jsonl efficiency_runs[].iterations, and actionable-patterns.sh
# ranks the emitted patterns by that cost aggregate.
# ────────────────────────────────────────────────────────────────────────────

# AC1: a covered pattern carries cost_mean_iterations (mean over covered occurrences)
# plus covered_occurrence_count. Two occurrences (PRs 1,2), iterations 2 and 4 → mean 3.
CP_COST="$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}
{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-02T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}' \
  '{"pr":1,"efficiency_runs":[{"iterations":2}]}
{"pr":2,"efficiency_runs":[{"iterations":4}]}')"
assert_eq "#1828 AC1: covered pattern carries cost_mean_iterations (mean of 2,4 = 3)" "3" \
  "$(printf '%s' "$CP_COST" | jq -r '.["incomplete-edit"].cost_mean_iterations')"
assert_eq "#1828 AC1: covered pattern carries covered_occurrence_count" "2" \
  "$(printf '%s' "$CP_COST" | jq -r '.["incomplete-edit"].covered_occurrence_count')"

# AC4: the cost signal is derived from efficiency_runs[].iterations and NEVER from
# post_bot_commits. PR 3 carries iterations 5 alongside a large post_bot_commits; the
# mean must be 5, not influenced by post_bot_commits.
CP_AC4="$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":3,"merged_at":"2026-04-03T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}' \
  '{"pr":3,"efficiency_runs":[{"iterations":5}],"post_bot_commits":99}')"
assert_eq "#1828 AC4: cost uses efficiency_runs iterations, not post_bot_commits" "5" \
  "$(printf '%s' "$CP_AC4" | jq -r '.["unverified-assumption"].cost_mean_iterations')"

# AC5: a pattern whose occurrences all lack coverage records the absence explicitly
# (null), never a cost of 0. Also proves an absent/malformed efficiency_runs value
# neither aborts the whole filter nor becomes a cost of 0 (Testing Strategy).
CP_UNCOV="$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":20,"merged_at":"2026-04-20T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}
{"schema_version":2,"kind":"implementation","pr":21,"merged_at":"2026-04-21T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}' \
  '{"pr":20,"efficiency_runs":[{"iterations":"oops"}]}
{"pr":21,"post_bot_commits":3}')"
assert_eq "#1828 AC5: all-uncovered pattern records absence (null cost), not 0" "true" \
  "$(printf '%s' "$CP_UNCOV" | jq -e '.["lenient-verdict"].cost_mean_iterations == null' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1828 AC5: all-uncovered pattern reports covered_occurrence_count 0" "0" \
  "$(printf '%s' "$CP_UNCOV" | jq -r '.["lenient-verdict"].covered_occurrence_count')"
assert_eq "#1828: a malformed/absent efficiency_runs does not abort the filter (occurrence_count intact)" "2" \
  "$(printf '%s' "$CP_UNCOV" | jq -r '.["lenient-verdict"].occurrence_count')"

# A partially-covered pattern: one covered occurrence (iterations 4) + one malformed
# → the mean is the covered value alone (not diluted toward 0 by the uncovered one),
# and covered_occurrence_count excludes the uncovered occurrence.
CP_PART="$(cp_run \
  '{"schema_version":2,"kind":"implementation","pr":30,"merged_at":"2026-04-30T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}
{"schema_version":2,"kind":"implementation","pr":31,"merged_at":"2026-05-01T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' \
  '{"schema_version":2,"patterns":{},"dismissed":{}}' \
  '{"pr":30,"efficiency_runs":[{"iterations":4}]}
{"pr":31,"efficiency_runs":[]}')"
assert_eq "#1828: partial coverage — mean is the covered value alone" "4" \
  "$(printf '%s' "$CP_PART" | jq -r '.["doc-accuracy"].cost_mean_iterations')"
assert_eq "#1828: partial coverage — covered_occurrence_count counts only covered" "1" \
  "$(printf '%s' "$CP_PART" | jq -r '.["doc-accuracy"].covered_occurrence_count')"

# AC2 + AC3: actionable-patterns.sh ranks covered patterns by descending cost, with a
# zero-coverage pattern last (still passing the unchanged min_occurrences gate). The
# experiment records live as a SIBLING of the retrospectives file.
mkdir -p "$RL_TMP/rank"
printf '%s\n' \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-02T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":3,"merged_at":"2026-04-03T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":4,"merged_at":"2026-04-04T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"kind":"implementation","pr":5,"merged_at":"2026-04-05T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"kind":"implementation","pr":6,"merged_at":"2026-04-06T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  '{"schema_version":2,"kind":"implementation","pr":7,"merged_at":"2026-04-07T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  > "$RL_TMP/rank/retrospectives.jsonl"
# incomplete-edit: 3 occ, cost 1 (low cost, high frequency).
# unverified-assumption: 2 occ, cost 5 (high cost, low frequency).
# lenient-verdict: 2 occ, NO coverage (PRs 6,7 have no experiment records).
printf '%s\n' \
  '{"pr":1,"efficiency_runs":[{"iterations":1}]}' \
  '{"pr":2,"efficiency_runs":[{"iterations":1}]}' \
  '{"pr":3,"efficiency_runs":[{"iterations":1}]}' \
  '{"pr":4,"efficiency_runs":[{"iterations":5}],"post_bot_commits":99}' \
  '{"pr":5,"efficiency_runs":[{"iterations":5}]}' \
  > "$RL_TMP/rank/experiment-records.jsonl"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/rank/ov.json"
RL_RANK="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/rank/retrospectives.jsonl" "$RL_TMP/rank/ov.json" 2>/dev/null)"
assert_eq "#1828 AC2: low-frequency high-cost pattern ranks above high-frequency low-cost; zero-coverage last" \
  "unverified-assumption|incomplete-edit|lenient-verdict" \
  "$(printf '%s' "$RL_RANK" | jq -r '[.[].tag] | join("|")')"
assert_eq "#1828 AC2/AC4: the high-cost pattern's cost aggregate is the iterations mean (5), not post_bot_commits" "5" \
  "$(printf '%s' "$RL_RANK" | jq -r '.[] | select(.tag=="unverified-assumption") | .cost_mean_iterations')"
assert_eq "#1828 AC3: the zero-coverage pattern still passes the min_occurrences gate (present)" "true" \
  "$(printf '%s' "$RL_RANK" | jq -e 'any(.[]; .tag=="lenient-verdict")' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1828: the zero-coverage pattern carries null cost, not 0" "true" \
  "$(printf '%s' "$RL_RANK" | jq -e '.[] | select(.tag=="lenient-verdict") | .cost_mean_iterations == null' >/dev/null 2>&1 && echo true || echo false)"

# AC2 tiebreaks: two COVERED patterns with EQUAL cost rank by occurrence count desc
# (exercises the -(.occurrence_count) covered tiebreak key, which distinct-cost fixtures
# leave dead), and two ZERO-COVERAGE patterns order among themselves by occurrence count
# desc (exercises the uncovered ordering with more than one uncovered pattern).
# Both pairs are chosen so the expected occurrence-count order OPPOSES the alphabetical
# key order (compute-patterns.jq emits corpus categories `unique`-sorted, and jq sort_by
# is stable, so an equal-key pair defaults to alphabetical order): the higher-occurrence
# member of each pair is the alphabetically LATER name, so removing/flipping the
# -(.occurrence_count) key flips each pair and fails the assertion — a real regression
# guard, not one coincidentally satisfied by the stable-sort default.
mkdir -p "$RL_TMP/rank2"
printf '%s\n' \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-02T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":3,"merged_at":"2026-04-03T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"kind":"implementation","pr":4,"merged_at":"2026-04-04T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"kind":"implementation","pr":5,"merged_at":"2026-04-05T00:00:00Z","verdict":"imperfect","categories":["unverified-assumption"]}' \
  '{"schema_version":2,"kind":"implementation","pr":6,"merged_at":"2026-04-06T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  '{"schema_version":2,"kind":"implementation","pr":7,"merged_at":"2026-04-07T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  '{"schema_version":2,"kind":"implementation","pr":8,"merged_at":"2026-04-08T00:00:00Z","verdict":"imperfect","categories":["lenient-verdict"]}' \
  '{"schema_version":2,"kind":"implementation","pr":9,"merged_at":"2026-04-09T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' \
  '{"schema_version":2,"kind":"implementation","pr":10,"merged_at":"2026-04-10T00:00:00Z","verdict":"imperfect","categories":["doc-accuracy"]}' \
  > "$RL_TMP/rank2/retrospectives.jsonl"
# unverified-assumption: 3 occ, cost 4 (covered; alphabetically LATER than incomplete-edit,
# so its higher occurrence count opposes the alphabetical default). incomplete-edit: 2 occ,
# cost 4 (covered, EQUAL cost -> ranks below unverified-assumption by occurrence count).
# lenient-verdict: 3 occ, uncovered (alphabetically LATER than doc-accuracy). doc-accuracy:
# 2 occ, uncovered (ranks below lenient-verdict by occurrence count).
printf '%s\n' \
  '{"pr":1,"efficiency_runs":[{"iterations":4}]}' \
  '{"pr":2,"efficiency_runs":[{"iterations":4}]}' \
  '{"pr":3,"efficiency_runs":[{"iterations":4}]}' \
  '{"pr":4,"efficiency_runs":[{"iterations":4}]}' \
  '{"pr":5,"efficiency_runs":[{"iterations":4}]}' \
  > "$RL_TMP/rank2/experiment-records.jsonl"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/rank2/ov.json"
RL_RANK2="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/rank2/retrospectives.jsonl" "$RL_TMP/rank2/ov.json" 2>/dev/null)"
assert_eq "#1828 AC2 tiebreak: equal-cost covered patterns order by occurrence count desc; multiple zero-coverage order by occurrence count desc (both pairs oppose the alphabetical default)" \
  "unverified-assumption|incomplete-edit|lenient-verdict|doc-accuracy" \
  "$(printf '%s' "$RL_RANK2" | jq -r '[.[].tag] | join("|")')"
assert_eq "#1828 AC2 tiebreak: both covered patterns share the equal cost aggregate (4)" "4|4" \
  "$(printf '%s' "$RL_RANK2" | jq -r '[.[] | select(.covered_occurrence_count > 0) | .cost_mean_iterations] | join("|")')"

# A present-but-unparseable experiment-records.jsonl (one malformed line) must NOT abort
# the weekly derivation: actionable-patterns.sh validates it, warns, and degrades to no
# coverage (rank by occurrence count) rather than letting the eager --slurpfile read take
# the whole run down. The cost source is best-effort — it only reorders, never admits.
mkdir -p "$RL_TMP/rank3"
printf '%s\n' \
  '{"schema_version":2,"kind":"implementation","pr":1,"merged_at":"2026-04-01T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  '{"schema_version":2,"kind":"implementation","pr":2,"merged_at":"2026-04-02T00:00:00Z","verdict":"imperfect","categories":["incomplete-edit"]}' \
  > "$RL_TMP/rank3/retrospectives.jsonl"
printf '%s\n' '{"pr":1,"efficiency_runs":[{"iterations":4}]}' 'this is not json' > "$RL_TMP/rank3/experiment-records.jsonl"
printf '%s' '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$RL_TMP/rank3/ov.json"
RL_RANK3="$(DEVFLOW_GH="$RL_TMP/gh-ap.sh" DEVFLOW_CONFIG_FILE="$REPO_ROOT/lib/test/fixtures/config.json" \
  bash "$RL_AP" "$RL_TMP/rank3/retrospectives.jsonl" "$RL_TMP/rank3/ov.json" 2>"$RL_TMP/rank3.err")"; RL_RANK3_RC=$?
assert_eq "#1828: a malformed experiment-records.jsonl does not abort the derivation (rc 0)" "0" "$RL_RANK3_RC"
assert_eq "#1828: a malformed experiment-records.jsonl still emits the pattern (degraded to uncovered)" "true" \
  "$(printf '%s' "$RL_RANK3" | jq -e 'any(.[]; .tag=="incomplete-edit" and .cost_mean_iterations == null and .covered_occurrence_count == 0)' >/dev/null 2>&1 && echo true || echo false)"
assert_eq "#1828: a malformed experiment-records.jsonl emits the specific breadcrumb naming the file" "true" \
  "$(grep -q 'experiment-records.jsonl.*does not parse as JSON' "$RL_TMP/rank3.err" && echo true || echo false)"

rm -rf "$RL_TMP"
trap - RETURN

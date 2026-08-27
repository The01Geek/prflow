# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable #431 experiment-records contract module (issue #746 tranche).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first (which defines the namespaced module pin API:
# devflow_module_pin_count / devflow_module_pin_unique / devflow_module_pin_present).
# This module uses assert_eq alone — the #431
# producer pins stay in lib/test/run.sh because they target files this helper does
# not own (see the DELIBERATELY PARTIAL EXTRACTION note below), so nothing here needs
# a pin primitive and it references NO monolith helper. Every path derives from LIB.
# It allocates no module-level fixture root (see the note below); it never invokes
# the runner or the full-suite boundary. The
# inventory in experiment-records.inventory.md maps the extracted coverage to its
# former run.sh location. Modules may not self-skip.
#
# DELIBERATELY PARTIAL EXTRACTION: the former section's trailing "#431 producer
# pins" block stays in lib/test/run.sh. Those five pins assert against
# lib/efficiency-trace.{jq,sh}, lib/open-state-pr.sh and the review-and-fix skill bundle — none of which is this
# assembler's own surface — and one of them binds the run.sh-global $MAXI_BUNDLE.
# So the #431 coverage-map label remains partially in run.sh and its owner stays
# `unmodularized`; that is a recorded decision, not an oversight.
#
# No private fixture root and no EXIT trap here, deliberately — same reasoning as
# review-trigger-helpers.sh: the extracted body owns and removes its own fixture tree
# exactly as it did inline in lib/test/run.sh, both callers already allocate and clean a
# boundary-owned scratch root, and a TMPDIR redirect could not contain a bare `mktemp -d`
# on macOS/BSD anyway.


# Drives the assembler over fixture stores with a DEVFLOW_GH stub (the stub
# contract) and a per-scenario repo-root, then asserts the joined record fields.
# The producer additions (config_fingerprint stamp, verification_evidence
# obligation, the finalize-summary denial line, the open-state-pr staging entry)
# carry ordinary executable assertions; those producer tests stay in
# lib/test/run.sh (see this module's header).
BXR="$LIB/../scripts/build-experiment-records.py"

if [ ! -x "$BXR" ]; then
  # The monolith recorded this arm with a raw `echo FAIL >> "$RESULTS_FILE"`; a
  # module reports through assert_eq instead, so the missing helper lands in the
  # tally as a NAMED red assertion rather than an anonymous one.
  assert_eq "#431: build-experiment-records.py present and executable at $BXR" "yes" "no"
else
  EXP="$(mktemp -d)"
  # ── DEVFLOW_GH stub: canned JSON per endpoint, sourced from env-pointed files so
  #    each scenario varies responses without rewriting the stub. `annotations`
  #    matched BEFORE `check-runs` (the annotations path contains both tokens).
  cat > "$EXP/gh" <<'STUB'
#!/usr/bin/env bash
j="$*"
# Argv log (issue #431 review — pin that --paginate reaches the check-runs call):
# when GH_ARGV_LOG is set, record each invocation's joined argv so a test can assert
# a specific flag was actually passed (the stub ignores flags, so a dropped
# paginate=True would otherwise stay green).
[ -n "$GH_ARGV_LOG" ] && printf '%s\n' "$j" >> "$GH_ARGV_LOG"
# Failure injection (issue #431 review — Fix C fetch-failed provenance): when the
# matching *_FAIL env is set, this endpoint's gh call exits NON-ZERO (transport /
# auth / rate-limit), which the assembler must record as "fetch-failed", NOT "absent".
# annotations matched before check-runs (the annotations path contains both tokens).
case "$j" in
  *"pr view"*)     [ -f "$PR_VIEW_JSON" ]  && cat "$PR_VIEW_JSON"  || echo '{}';               exit 0 ;;
  *reviews*)       [ -n "$REVIEWS_FAIL" ]   && { echo "gh: api error" >&2; exit 1; }; [ -f "$REVIEWS_JSON" ]  && cat "$REVIEWS_JSON"  || echo '[]';               exit 0 ;;
  *annotations*)   [ -n "$ANNOT_FAIL" ]     && { echo "gh: api error" >&2; exit 1; }; [ -f "$ANNOT_JSON" ]    && cat "$ANNOT_JSON"    || echo '[]';               exit 0 ;;
  *comments*)      [ -n "$COMMENTS_FAIL" ]  && { echo "gh: api error" >&2; exit 1; }; [ -f "$COMMENTS_JSON" ] && cat "$COMMENTS_JSON" || echo '[]';               exit 0 ;;
  *check-runs*)
    [ -n "$CHECKRUNS_FAIL" ] && { echo "gh: api error" >&2; exit 1; }
    # Sha-keyed fetch failure (issue #435 AC-2c): when CHECKRUNS_FAIL_SHA is set, fail the
    # check-runs fetch ONLY for the probed sha whose substring appears in the endpoint path,
    # so one probed sha can fetch-fail while the other serves CHECKRUNS_JSON. Empty/unset
    # CHECKRUNS_FAIL_SHA skips the case entirely (never `*""*`, which would match every sha).
    if [ -n "$CHECKRUNS_FAIL_SHA" ]; then
      case "$j" in *"$CHECKRUNS_FAIL_SHA"*) echo "gh: api error" >&2; exit 1 ;; esac
    fi
    # Sha-keyed response (PR #436 review — the cross-sha precedence fixture): when
    # CHECKRUNS_JSON2_SHA is set and the endpoint path contains it, serve CHECKRUNS_JSON2
    # instead of CHECKRUNS_JSON, so the two probed shas can carry DIFFERENT check-run
    # sets. Empty/unset skips the case entirely (same guard as CHECKRUNS_FAIL_SHA above).
    # Both sha knobs match by SUBSTRING of the endpoint path, so fixture shas must be
    # distinct and never a substring of each other (e.g. not `h1`/`h12`).
    if [ -n "$CHECKRUNS_JSON2_SHA" ]; then
      case "$j" in
        *"$CHECKRUNS_JSON2_SHA"*)
          [ -f "$CHECKRUNS_JSON2" ] && cat "$CHECKRUNS_JSON2" || echo '{"check_runs":[]}'
          exit 0 ;;
      esac
    fi
    [ -f "$CHECKRUNS_JSON" ] && cat "$CHECKRUNS_JSON" || echo '{"check_runs":[]}'
    exit 0 ;;
  *"repo view"*)   echo "owner/repo"; exit 0 ;;
  *)               echo '[]'; exit 0 ;;
esac
STUB
  chmod +x "$EXP/gh"

  # get.py: print a dotted-path field of the store line for a given PR.
  cat > "$EXP/get.py" <<'PY'
import json, sys
recs = {json.loads(l)["pr"]: json.loads(l) for l in open(sys.argv[1]) if l.strip()}
cur = recs.get(int(sys.argv[2]))
for k in sys.argv[3].split("."):
    if k == "":
        continue
    if k.lstrip("-").isdigit():
        cur = cur[int(k)] if isinstance(cur, list) else None
    else:
        cur = cur.get(k) if isinstance(cur, dict) else None
sys.stdout.write(cur if isinstance(cur, str) else json.dumps(cur))
PY

  exp_field() { python3 "$EXP/get.py" "$1" "$2" "$3"; }
  # exp_count_lines: number of non-empty JSONL lines in the store.
  # NOT `grep -c … || echo 0`: on an EMPTY store grep prints "0" AND exits 1, so the
  # fallback fires too and the helper emits "0\n0" — silently breaking any zero-row
  # assertion (which is exactly what a skipped-PR test asserts). Count in the shell.
  exp_count_lines() {
    local n=0 line
    [ -f "$1" ] || { printf '0\n'; return 0; }
    while IFS= read -r line || [ -n "$line" ]; do
      [ -n "${line//[[:space:]]/}" ] && n=$((n + 1))
    done < "$1"
    printf '%s\n' "$n"
  }

  # Seed one efficiency record. $1 dir, $2 filename, $3 slug, $4 synthesized(true/false),
  # $5 telemetry-json (the "telemetry" array), $6 fingerprint-json (or the literal null).
  seed_eff() {
    mkdir -p "$1"
    cat > "$1/$2" <<EOF
{"schema_version":1,"slug":"$3","generated_at":"2026-07-01T00:00:00Z","synthesized":$4,"iterations":1,"config_fingerprint":$6,"telemetry":$5}
EOF
  }

  # ── T1 full join ───────────────────────────────────────────────────────────
  R1="$EXP/r1"
  mkdir -p "$R1/.prflow/learnings"
  cat > "$R1/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":431,"issue":430,"merged_at":"2026-07-10T00:00:00Z","branch":"issue-431-foo","head_sha":"headsha431","merge_commit_sha":"mergesha431"}
EOF
  seed_eff "$R1/.prflow/logs/efficiency" "pr-431-run1.json" "pr-431" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":150,"calls":3}}}]' \
    '{"sha256":"fp431","partial":false,"salient":{"max_iterations":5}}'
  cat > "$EXP/reviews1.json" <<'EOF'
[{"state":"COMMENTED","submitted_at":"2026-07-09T10:00:00Z","commit_id":"headsha431","body":"## Verdict: APPROVE with notes (ok)\n\nreport"}]
EOF
  cat > "$EXP/comments1.json" <<'EOF'
[{"id":1,"created_at":"2026-07-09T10:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n<!-- prflow:review-seeded-head seededsha431 -->\n**Reviewed HEAD:** headsha431\n\n## Verdict: APPROVE with notes\n\n## Code Review Findings\n\n### 🔴 Critical\n1. crit\n\n### 🟠 Important / Major\n1. imp one\n2. imp two\n\n### 🟡 Suggestion / Minor\n1. nit\n"},{"id":2,"created_at":"2026-07-09T11:00:00Z","body":"<!-- devflow:review-progress run=2 -->\n<!-- prflow:review-seeded-head headsha431 -->\n**Reviewed HEAD:** decoyhead431\n\n## Verdict: REJECT\n\n## Code Review Findings\n\n### 🟠 Important / Major\n1. decoy only\n"}]
EOF
  cat > "$EXP/checkruns1.json" <<'EOF'
{"check_runs":[{"id":55,"name":"Devflow Review","output":{"summary":"verdict on PR\n\npermission_denials_count: unavailable"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews1.json" COMMENTS_JSON="$EXP/comments1.json" \
    CHECKRUNS_JSON="$EXP/checkruns1.json" \
    python3 "$BXR" --repo-root "$R1" --prs 431 >/dev/null 2>&1
  ST1="$R1/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T1: full-join verdict (shape-matched PR review)" "APPROVE with notes" "$(exp_field "$ST1" 431 verdict)"
  assert_eq "#431 T1: verdict provenance is pr-review" "pr-review" "$(exp_field "$ST1" 431 provenance.verdict)"
  assert_eq "#431 T1: Important-finding count joined via Reviewed HEAD == commit_id" "2" "$(exp_field "$ST1" 431 important_finding_count)"
  # AC4 of issue #1010: progress comments now ALSO carry the seed-time head key
  # `<!-- prflow:review-seeded-head <sha> -->`. The comment set above is a DECOY
  # pair — the real one records the review commit on its `Reviewed HEAD:` line
  # while carrying a different seeded head, and the decoy inverts that, carrying
  # the review commit on its SEEDED key and a different `Reviewed HEAD:`. A join
  # that confused the two keys would pick the decoy and report 1 Important
  # finding; the `Reviewed HEAD` join is unchanged, so it still reports 2.
  assert_eq "#431 T1(#1010): the seed-time head key does not capture the Reviewed HEAD join (decoy ignored)" "2" "$(exp_field "$ST1" 431 important_finding_count)"
  assert_eq "#431 T1: denial count carried verbatim from the summary path" "unavailable" "$(exp_field "$ST1" 431 permission_denials_count)"
  assert_eq "#431 T1: denial provenance is check-run-summary" "check-run-summary" "$(exp_field "$ST1" 431 provenance.permission_denials_count)"
  assert_eq "#431 T1: efficiency provenance found" "found" "$(exp_field "$ST1" 431 provenance.efficiency)"
  assert_eq "#431 T1: fingerprint sourced from the efficiency record" "efficiency-record" "$(exp_field "$ST1" 431 provenance.config_fingerprint)"
  assert_eq "#431 T1: per-run cost aggregated (tokens summed)" "150" "$(exp_field "$ST1" 431 efficiency_runs.0.cost.tokens)"
  assert_eq "#431 T1: one efficiency run listed" "1" "$(python3 -c 'import json,sys;print(len(json.loads([l for l in open(sys.argv[1])][0])["efficiency_runs"]))' "$ST1")"

  # ── T2 slug aggregation — both families, two run-ids, none discarded ─────────
  R2="$EXP/r2"
  mkdir -p "$R2/.prflow/learnings"
  cat > "$R2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":500,"issue":499,"merged_at":"2026-07-10T00:00:00Z","branch":"feature-x","head_sha":"h500","merge_commit_sha":"m500"}
EOF
  seed_eff "$R2/.prflow/logs/efficiency" "pr-500-runA.json" "pr-500" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' 'null'
  seed_eff "$R2/.prflow/logs/efficiency" "feature-x-runB.json" "feature-x" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R2" --prs 500 >/dev/null 2>&1
  ST2="$R2/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T2: both slug families aggregated (2 runs, none discarded)" "2" \
    "$(python3 -c 'import json,sys;print(len(json.loads([l for l in open(sys.argv[1])][0])["efficiency_runs"]))' "$ST2")"

  # ── T2b no efficiency record — outcome-only row ──────────────────────────────
  R2B="$EXP/r2b"
  mkdir -p "$R2B/.prflow/learnings"
  cat > "$R2B/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":600,"issue":599,"merged_at":"2026-07-10T00:00:00Z","branch":"nada","merge_commit_sha":"m600"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R2B" --prs 600 >/dev/null 2>&1
  ST2B="$R2B/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T2b: no efficiency record → outcome-only row, provenance absent" "absent" "$(exp_field "$ST2B" 600 provenance.efficiency)"
  assert_eq "#431 T2b: outcome-only row still keyed on the PR" "600" "$(exp_field "$ST2B" 600 pr)"

  # ── T3 verdict arms ──────────────────────────────────────────────────────────
  # 3b progress-comment fallback (no PR review with a ## Verdict:).
  R3B="$EXP/r3b"
  mkdir -p "$R3B/.prflow/learnings"
  cat > "$R3B/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":700,"merged_at":"2026-07-10T00:00:00Z","branch":"b700","merge_commit_sha":"m700"}
EOF
  cat > "$EXP/comments3b.json" <<'EOF'
[{"id":9,"created_at":"2026-07-09T10:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** h700\n\n## Verdict: REJECT (blocking)\n\n## Code Review Findings\n\n### 🟠 Important / Major\n1. only important\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments3b.json" \
    python3 "$BXR" --repo-root "$R3B" --prs 700 >/dev/null 2>&1
  ST3B="$R3B/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3b: verdict from progress-comment fallback" "REJECT" "$(exp_field "$ST3B" 700 verdict)"
  assert_eq "#431 T3b: verdict provenance is progress-comment" "progress-comment" "$(exp_field "$ST3B" 700 provenance.verdict)"
  assert_eq "#431 T3b: Important count from the fallback comment" "1" "$(exp_field "$ST3B" 700 important_finding_count)"

  # 3c null-verdict (#403 shape): no review, no verdict-bearing comment.
  R3C="$EXP/r3c"
  mkdir -p "$R3C/.prflow/learnings"
  cat > "$R3C/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":800,"merged_at":"2026-07-10T00:00:00Z","branch":"b800","merge_commit_sha":"m800"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R3C" --prs 800 >/dev/null 2>&1
  ST3C="$R3C/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3c: null verdict (#403) when neither review nor comment carries one" "null" "$(exp_field "$ST3C" 800 verdict)"
  assert_eq "#431 T3c: null-verdict provenance absent" "absent" "$(exp_field "$ST3C" 800 provenance.verdict)"

  # ── T4 unknown-is-not-zero (denial verbatim; no coercion to 0) ──────────────
  # 4b digit from the annotation fallback (no summary line).
  R4="$EXP/r4"
  mkdir -p "$R4/.prflow/learnings"
  cat > "$R4/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":900,"merged_at":"2026-07-10T00:00:00Z","branch":"b900","head_sha":"h900","merge_commit_sha":"m900"}
EOF
  cat > "$EXP/checkruns4.json" <<'EOF'
{"check_runs":[{"id":77,"name":"Devflow Review","output":{"summary":"an old-workflow summary with no denial line"}}]}
EOF
  cat > "$EXP/annot4.json" <<'EOF'
[{"message":"DevFlow: this run recorded 3 permission denial(s) — the engine attempted commands its tool profile does not grant."}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns4.json" ANNOT_JSON="$EXP/annot4.json" \
    python3 "$BXR" --repo-root "$R4" --prs 900 >/dev/null 2>&1
  ST4="$R4/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T4: digit denial count carried verbatim from the annotation path" "3" "$(exp_field "$ST4" 900 permission_denials_count)"
  # The provenance tag is a BARE, matchable token — every other inhabitant of this field
  # is one, and the coherence checker tests membership (`source in PROVENANCE_UNESTABLISHED`),
  # so an embedded caveat sentence would make the vocabulary a non-closed set no consumer
  # could match on equality (this assertion needed a glob before that fix — issue #431 review).
  assert_eq "#431 T4: annotation provenance is a bare, equality-matchable tag" "check-run-annotation" \
    "$(exp_field "$ST4" 900 provenance.permission_denials_count)"
  # The positive-only bias caveat is not lost — it moves to provenance.notes, where it belongs.
  assert_eq "#431 T4: the positive-only-bias caveat is recorded in provenance.notes" "yes" \
    "$(python3 -c 'import json,sys
r=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][0]
print("yes" if any("positive-count-only" in n for n in r["provenance"]["notes"]) else "no")' "$ST4")"
  # 4c unestablished (no summary line, no annotation) → null, NEVER 0.
  R4C="$EXP/r4c"
  mkdir -p "$R4C/.prflow/learnings"
  cat > "$R4C/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":901,"merged_at":"2026-07-10T00:00:00Z","branch":"b901","head_sha":"h901","merge_commit_sha":"m901"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R4C" --prs 901 >/dev/null 2>&1
  ST4C="$R4C/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T4: unestablished denial is null (never coerced to 0)" "null" "$(exp_field "$ST4C" 901 permission_denials_count)"
  # Pair the null with its provenance: exp_field prints "null" for a PR MISSING from the
  # store entirely, so the assertion above would pass vacuously if the row were dropped
  # (e.g. by a widened merged-state gate). The provenance assertion pins BOTH row existence
  # and the measured-absence-vs-unestablished distinction (issue #431 shadow).
  assert_eq "#431 T4: the null is a MEASURED absence on an existing row (not a missing row)" "absent" \
    "$(exp_field "$ST4C" 901 provenance.permission_denials_count)"

  # ── T5 telemetry_complete + idempotency ─────────────────────────────────────
  R5="$EXP/r5"
  mkdir -p "$R5/.prflow/learnings"
  cat > "$R5/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":950,"merged_at":"2026-07-10T00:00:00Z","branch":"complete","merge_commit_sha":"m950"}
{"schema_version":2,"kind":"implementation","pr":951,"merged_at":"2026-07-10T00:00:00Z","branch":"synth","merge_commit_sha":"m951"}
{"schema_version":2,"kind":"implementation","pr":952,"merged_at":"2026-07-10T00:00:00Z","branch":"unavailable","merge_commit_sha":"m952"}
EOF
  seed_eff "$R5/.prflow/logs/efficiency" "pr-950-r.json" "pr-950" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":42}}}]' 'null'
  seed_eff "$R5/.prflow/logs/efficiency" "pr-951-r.json" "pr-951" "true" \
    '[{"iter":1,"phases":{"phase3":{"tokens":42}}}]' 'null'
  seed_eff "$R5/.prflow/logs/efficiency" "pr-952-r.json" "pr-952" "false" \
    '[{"iter":1,"phases":"unavailable"}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R5" --prs 950,951,952 >/dev/null 2>&1
  ST5="$R5/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T5: complete record → telemetry_complete true" "true" "$(exp_field "$ST5" 950 efficiency_runs.0.telemetry_complete)"
  assert_eq "#431 T5: synthesized record → telemetry_complete false" "false" "$(exp_field "$ST5" 951 efficiency_runs.0.telemetry_complete)"
  assert_eq "#499 consumer: unavailable marker → telemetry_complete false" "false" "$(exp_field "$ST5" 952 efficiency_runs.0.telemetry_complete)"
  assert_eq "#499 consumer: unavailable marker contributes no cost figures" "null" "$(exp_field "$ST5" 952 efficiency_runs.0.cost)"
  # Idempotency: a second run is byte-identical and does not duplicate lines.
  BEFORE5="$(cat "$ST5")"
  N5A="$(exp_count_lines "$ST5")"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$R5" --prs 950,951,952 >/dev/null 2>&1
  AFTER5="$(cat "$ST5")"
  assert_eq "#431 T5: idempotent re-run is byte-identical" "yes" "$([ "$BEFORE5" = "$AFTER5" ] && echo yes || echo no)"
  assert_eq "#431 T5: idempotent re-run keeps one line per PR (3)" "$N5A" "$(exp_count_lines "$ST5")"
  assert_eq "#431 T5: three PRs recorded" "3" "$N5A"

  # ── T3d verdict-stub suffix strip (review Fix A) ─────────────────────────────
  # The engine's DEFAULT pr-review body is the stub form
  # "## Verdict: {VERDICT} — full report in PR comment" (skills/review/SKILL.md
  # Phase 4.4). Without the suffix strip the primary outcome variable would store
  # "APPROVE — full report in PR comment", matching zero rows in the operator's
  # verdict==APPROVE queries. Pin the bare token is stored.
  R3D="$EXP/r3d"
  mkdir -p "$R3D/.prflow/learnings"
  cat > "$R3D/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":710,"merged_at":"2026-07-10T00:00:00Z","branch":"b710","head_sha":"h710","merge_commit_sha":"m710"}
EOF
  cat > "$EXP/reviews3d.json" <<'EOF'
[{"state":"APPROVED","submitted_at":"2026-07-09T10:00:00Z","commit_id":"h710","body":"## Verdict: APPROVE — full report in PR comment"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3d.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3D" --prs 710 >/dev/null 2>&1
  ST3D="$R3D/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3d: pr-review stub body stores the bare verdict token (suffix stripped)" "APPROVE" "$(exp_field "$ST3D" 710 verdict)"
  assert_eq "#431 T3d: stub-form verdict provenance is pr-review" "pr-review" "$(exp_field "$ST3D" 710 provenance.verdict)"

  # ── T3e unparseable verdict provenance (review Fix A coherence) ──────────────
  # A completed review carries the "## Verdict:" marker inline in prose (not as a
  # `^## Verdict:` line, so it does not parse) and there is no progress-comment
  # fallback → verdict null with provenance "unparseable", NEVER "pr-review" over a
  # null value. (A whitespace-only line would NOT be unparseable — `\s` spans
  # newlines, so the parser would reach the next line's token.)
  R3E="$EXP/r3e"
  mkdir -p "$R3E/.prflow/learnings"
  cat > "$R3E/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":720,"merged_at":"2026-07-10T00:00:00Z","branch":"b720","head_sha":"h720","merge_commit_sha":"m720"}
EOF
  cat > "$EXP/reviews3e.json" <<'EOF'
[{"state":"COMMENTED","submitted_at":"2026-07-09T10:00:00Z","commit_id":"h720","body":"This body mentions ## Verdict: inline but has no real verdict line."}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3e.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3E" --prs 720 >/dev/null 2>&1
  ST3E="$R3E/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3e: unparseable pr-review verdict → null value" "null" "$(exp_field "$ST3E" 720 verdict)"
  assert_eq "#431 T3e: unparseable verdict provenance (not pr-review over a null)" "unparseable" "$(exp_field "$ST3E" 720 provenance.verdict)"

  # ── T3f first-completed-review-wins (multiple review runs) ───────────────────
  # Two completed verdict-bearing reviews; the EARLIEST by submitted_at wins.
  R3F="$EXP/r3f"
  mkdir -p "$R3F/.prflow/learnings"
  cat > "$R3F/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":730,"merged_at":"2026-07-10T00:00:00Z","branch":"b730","head_sha":"h730","merge_commit_sha":"m730"}
EOF
  cat > "$EXP/reviews3f.json" <<'EOF'
[{"state":"CHANGES_REQUESTED","submitted_at":"2026-07-09T12:00:00Z","commit_id":"h730","body":"## Verdict: APPROVE"},{"state":"CHANGES_REQUESTED","submitted_at":"2026-07-09T08:00:00Z","commit_id":"h730","body":"## Verdict: REJECT"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3f.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3F" --prs 730 >/dev/null 2>&1
  ST3F="$R3F/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3f: first-completed review wins (earliest submitted_at)" "REJECT" "$(exp_field "$ST3F" 730 verdict)"

  # ── T3g superseded progress comment (latest verdict-comment wins) ────────────
  # Two verdict-bearing progress comments; the LATER by created_at supersedes. The
  # fixture is DELIBERATELY out of created_at order (the winning APPROVE@12:00 listed
  # FIRST, the stale REJECT@08:00 last) so the `.sort(key=created_at)` is load-bearing:
  # without it, `vp[-1]` would pick the stale REJECT and the test would fail. (A
  # pre-sorted fixture would pass whether or not the sort ran — a vacuous guard.)
  R3G="$EXP/r3g"
  mkdir -p "$R3G/.prflow/learnings"
  cat > "$R3G/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":740,"merged_at":"2026-07-10T00:00:00Z","branch":"b740","head_sha":"h740","merge_commit_sha":"m740"}
EOF
  cat > "$EXP/comments3g.json" <<'EOF'
[{"id":2,"created_at":"2026-07-09T12:00:00Z","body":"<!-- devflow:review-progress run=2 -->\n**Reviewed HEAD:** h740\n\n## Verdict: APPROVE\n"},{"id":1,"created_at":"2026-07-09T08:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** h740old\n\n## Verdict: REJECT\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments3g.json" \
    python3 "$BXR" --repo-root "$R3G" --prs 740 >/dev/null 2>&1
  ST3G="$R3G/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3g: latest progress comment supersedes (not the stale one)" "APPROVE" "$(exp_field "$ST3G" 740 verdict)"

  # ── T3h #1030 producer marker: selection AND a distinguishable provenance ────
  # The verdict is read from the marker scripts/post-review-verdict.sh stamps, and the
  # provenance names which of the two sources answered — a census asking "was this
  # verdict producer-emitted or recovered from prose?" is exactly the question #1030's
  # own investigation had to answer by hand. Every body below is production-realistic:
  # the review carries one of the REAL census first lines (a body whose prose matches
  # NO verdict shape), so the marker is the only thing that can carry it.
  R3H="$EXP/r3h"
  mkdir -p "$R3H/.prflow/learnings"
  cat > "$R3H/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":770,"merged_at":"2026-07-10T00:00:00Z","branch":"b770","merge_commit_sha":"m770"}
EOF
  EXP_M_HEAD="5555555555555555555555555555555555555555"
  EXP_CENSUS_LINE="$(jq -r '[.rejects[] | select(.dismisser_prose_match | not)][0].first_line' "$LIB/test/fixtures/review-verdict-census.json")"
  jq -nc --arg b "<!-- prflow:review-verdict head=$EXP_M_HEAD verdict=REJECT -->"$'\n'"$EXP_CENSUS_LINE"$'\n\nfull report in the progress comment.' \
    '[{state:"CHANGES_REQUESTED",submitted_at:"2026-07-09T10:00:00Z",commit_id:"h770",body:$b}]' > "$EXP/reviews3h.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3h.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3H" --prs 770 >/dev/null 2>&1
  ST3H="$R3H/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h: a marker-carrying review body whose prose matches nothing yields the verdict" \
    "REJECT" "$(exp_field "$ST3H" 770 verdict)"
  assert_eq "#1030 T3h: the marker source is distinguishable from the prose source" \
    "pr-review-marker" "$(exp_field "$ST3H" 770 provenance.verdict)"
  # Negative control — the SAME body without the marker yields null/absent, which is the
  # measured under-reporting #1030 closes.
  R3H2="$EXP/r3h2"
  mkdir -p "$R3H2/.prflow/learnings"
  cat > "$R3H2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":771,"merged_at":"2026-07-10T00:00:00Z","branch":"b771","merge_commit_sha":"m771"}
EOF
  jq -nc --arg b "$EXP_CENSUS_LINE"$'\n\nfull report in the progress comment.' \
    '[{state:"CHANGES_REQUESTED",submitted_at:"2026-07-09T10:00:00Z",commit_id:"h771",body:$b}]' > "$EXP/reviews3h2.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3h2.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3H2" --prs 771 >/dev/null 2>&1
  ST3H2="$R3H2/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h control: the same body unmarked under-reports as null/absent" \
    "null-absent" "$(exp_field "$ST3H2" 771 verdict)-$(exp_field "$ST3H2" 771 provenance.verdict)"
  # The progress-comment surface carries the marker on the line after its run key, and
  # gets its OWN provenance tag distinct from the prose one.
  R3H3="$EXP/r3h3"
  mkdir -p "$R3H3/.prflow/learnings"
  cat > "$R3H3/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":772,"merged_at":"2026-07-10T00:00:00Z","branch":"b772","merge_commit_sha":"m772"}
EOF
  jq -nc --arg b '<!-- prflow:review-progress run=1 -->'$'\n'"<!-- prflow:review-verdict head=$EXP_M_HEAD verdict=APPROVE -->"$'\n''**Reviewed HEAD:** h772'$'\n\n'"$EXP_CENSUS_LINE" \
    '[{id:9,created_at:"2026-07-09T10:00:00Z",body:$b}]' > "$EXP/comments3h3.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments3h3.json" \
    python3 "$BXR" --repo-root "$R3H3" --prs 772 >/dev/null 2>&1
  ST3H3="$R3H3/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h: a marker on the progress comment yields the verdict and its own provenance" \
    "APPROVE-progress-comment-marker" "$(exp_field "$ST3H3" 772 verdict)-$(exp_field "$ST3H3" 772 provenance.verdict)"
  # A marker QUOTED below the scanned window is prose: the transitional line decides and
  # keeps the prose provenance, so a finding citing this contract cannot forge a source.
  R3H4="$EXP/r3h4"
  mkdir -p "$R3H4/.prflow/learnings"
  cat > "$R3H4/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":773,"merged_at":"2026-07-10T00:00:00Z","branch":"b773","merge_commit_sha":"m773"}
EOF
  jq -nc --arg b '## Verdict: APPROVE'$'\n''a finding quotes the contract:'$'\n'"<!-- prflow:review-verdict head=$EXP_M_HEAD verdict=REJECT -->" \
    '[{state:"COMMENTED",submitted_at:"2026-07-09T10:00:00Z",commit_id:"h773",body:$b}]' > "$EXP/reviews3h4.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3h4.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3H4" --prs 773 >/dev/null 2>&1
  ST3H4="$R3H4/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h: a marker quoted below the scanned window keeps the prose source" \
    "APPROVE-pr-review" "$(exp_field "$ST3H4" 773 verdict)-$(exp_field "$ST3H4" 773 provenance.verdict)"

  # Only the prflow: spelling is a marker. The devflow:review-verdict spelling can exist on
  # no persisted artifact (the marker postdates the rename), so it must fall through to the
  # prose arm rather than be honored as a producer stamp (issue #1030) — while #1003's dual
  # read on the review-PROGRESS run key, which this same record still resolves either way,
  # is untouched.
  R3H5="$EXP/r3h5"
  mkdir -p "$R3H5/.prflow/learnings"
  cat > "$R3H5/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":774,"merged_at":"2026-07-10T00:00:00Z","branch":"b774","merge_commit_sha":"m774"}
EOF
  jq -nc --arg b "<!-- devflow:review-verdict head=$EXP_M_HEAD verdict=REJECT -->"$'\n'"$EXP_CENSUS_LINE" \
    '[{state:"CHANGES_REQUESTED",submitted_at:"2026-07-09T10:00:00Z",commit_id:"h774",body:$b}]' > "$EXP/reviews3h5.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews3h5.json" COMMENTS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$R3H5" --prs 774 >/dev/null 2>&1
  ST3H5="$R3H5/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h: the devflow:review-verdict spelling is not honored as a marker" \
    "null-absent" "$(exp_field "$ST3H5" 774 verdict)-$(exp_field "$ST3H5" 774 provenance.verdict)"
  R3H6="$EXP/r3h6"
  mkdir -p "$R3H6/.prflow/learnings"
  cat > "$R3H6/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":775,"merged_at":"2026-07-10T00:00:00Z","branch":"b775","merge_commit_sha":"m775"}
EOF
  jq -nc --arg b '<!-- devflow:review-progress run=1 -->'$'\n'"<!-- prflow:review-verdict head=$EXP_M_HEAD verdict=REJECT -->"$'\n''**Reviewed HEAD:** h775' \
    '[{id:9,created_at:"2026-07-09T10:00:00Z",body:$b}]' > "$EXP/comments3h6.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments3h6.json" \
    python3 "$BXR" --repo-root "$R3H6" --prs 775 >/dev/null 2>&1
  ST3H6="$R3H6/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 T3h: the superseded review-progress run-key spelling still reaches the marker" \
    "REJECT-progress-comment-marker" "$(exp_field "$ST3H6" 775 verdict)-$(exp_field "$ST3H6" 775 provenance.verdict)"

  # ── T3f2 verdict fetch-failed provenance (review Fix C) ──────────────────────
  # Both the reviews and comments API calls FAIL (rc≠0) → verdict null with
  # provenance "fetch-failed" (unestablished), distinct from a genuinely-absent one.
  R3F2="$EXP/r3f2"
  mkdir -p "$R3F2/.prflow/learnings"
  cat > "$R3F2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":760,"merged_at":"2026-07-10T00:00:00Z","branch":"b760","head_sha":"h760","merge_commit_sha":"m760"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_FAIL=1 COMMENTS_FAIL=1 \
    python3 "$BXR" --repo-root "$R3F2" --prs 760 >/dev/null 2>&1
  ST3F2="$R3F2/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3f2: verdict null when the API call failed" "null" "$(exp_field "$ST3F2" 760 verdict)"
  assert_eq "#431 T3f2: fetch failure → provenance fetch-failed (not absent)" "fetch-failed" "$(exp_field "$ST3F2" 760 provenance.verdict)"

  # ── T4d denial fetch-failed provenance (review Fix C) ────────────────────────
  # The check-runs API call FAILS → denial null with provenance "fetch-failed",
  # never coerced to 0 and never laundered into "absent".
  R4D="$EXP/r4d"
  mkdir -p "$R4D/.prflow/learnings"
  cat > "$R4D/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":910,"merged_at":"2026-07-10T00:00:00Z","branch":"b910","head_sha":"h910","merge_commit_sha":"m910"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_FAIL=1 \
    python3 "$BXR" --repo-root "$R4D" --prs 910 >/dev/null 2>&1
  ST4D="$R4D/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T4d: denial null when the check-runs API call failed (never 0)" "null" "$(exp_field "$ST4D" 910 permission_denials_count)"
  assert_eq "#431 T4d: denial fetch failure → provenance fetch-failed (not absent)" "fetch-failed" "$(exp_field "$ST4D" 910 provenance.permission_denials_count)"

  # ── Tpag check-runs pagination — Devflow Review on page 2 (review Fix B) ──────
  # gh --paginate concatenates one {check_runs:[…]} object per page. The Devflow
  # Review check sits on the SECOND page; the merge across object pages must still
  # find it (an unpaginated read would miss it and record "absent").
  RPG="$EXP/rpg"
  mkdir -p "$RPG/.prflow/learnings"
  cat > "$RPG/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":920,"merged_at":"2026-07-10T00:00:00Z","branch":"b920","head_sha":"h920","merge_commit_sha":"m920"}
EOF
  cat > "$EXP/checkruns_pag.json" <<'EOF'
{"check_runs":[{"id":1,"name":"other-ci","output":{"summary":"no denial here"}}]}
{"check_runs":[{"id":2,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: 4"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns_pag.json" \
    python3 "$BXR" --repo-root "$RPG" --prs 920 >/dev/null 2>&1
  STPG="$RPG/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tpag: denial count found when Devflow Review is on check-runs page 2" "4" "$(exp_field "$STPG" 920 permission_denials_count)"
  assert_eq "#431 Tpag: paginated denial provenance is check-run-summary" "check-run-summary" "$(exp_field "$STPG" 920 provenance.permission_denials_count)"

  # ── Tpag2 --paginate actually reaches the check-runs call ────────────────────
  # The stub ignores flags, so Tpag alone would stay green if paginate=True were
  # dropped (real gh would then return only page 1 and miss Devflow Review). Pin
  # that the check-runs invocation carried --paginate by logging argv.
  RPG2="$EXP/rpg2"
  mkdir -p "$RPG2/.prflow/learnings"
  cat > "$RPG2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":921,"merged_at":"2026-07-10T00:00:00Z","branch":"b921","head_sha":"h921","merge_commit_sha":"m921"}
EOF
  GH_ARGV_LOG="$EXP/argv.log" GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RPG2" --prs 921 >/dev/null 2>&1
  if grep 'check-runs' "$EXP/argv.log" 2>/dev/null | grep -q -- '--paginate'; then
    assert_eq "#431 Tpag2: check-runs call carried --paginate" "yes" "yes"
  else
    assert_eq "#431 Tpag2: check-runs call carried --paginate" "yes" "no"
  fi

  # ── T435-1 same-line denial parse: blank label + next-line token → unparseable ──
  # The summary's `permission_denials_count:` label line is BLANK-valued and the NEXT line
  # begins with a non-space token. The pre-#435 `\s*(\S+)` regex spans the newline and captures
  # that next-line token verbatim as a fabricated count (check-run-summary provenance) — the
  # exact defect. The line-bound parse reads nothing from the label's own line, sees the label,
  # and resolves (None, "unparseable"). RED-first: against pre-#435 code the OBSERVED value is
  # the fabricated "NEXTTOKEN"/check-run-summary, turning these null/unparseable assertions
  # RED; GREEN after the fix (issue #435 AC-1).
  R435A="$EXP/r435a"
  mkdir -p "$R435A/.prflow/learnings"
  cat > "$R435A/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1001,"merged_at":"2026-07-10T00:00:00Z","branch":"b1001","head_sha":"h1001","merge_commit_sha":"m1001"}
EOF
  cat > "$EXP/checkruns435a.json" <<'EOF'
{"check_runs":[{"id":1,"name":"Devflow Review","output":{"summary":"verdict on PR\n\npermission_denials_count:\nNEXTTOKEN following line"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435a.json" \
    python3 "$BXR" --repo-root "$R435A" --prs 1001 >/dev/null 2>&1
  ST435A="$R435A/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 AC1: blank label value never captures the next line's token (null)" "null" "$(exp_field "$ST435A" 1001 permission_denials_count)"
  assert_eq "#435 AC1: blank-label summary resolves to unparseable, not check-run-summary" "unparseable" "$(exp_field "$ST435A" 1001 provenance.permission_denials_count)"

  # ── T435-2 garbage token → unparseable, and the annotation fallback is NOT consulted ─
  # A label line carrying a non-digit, non-`unavailable` token, every check-runs fetch
  # succeeding. The token is invalid, so phase 1 finds no valid token; a label WAS seen, so
  # phase 2 returns unparseable WITHOUT consulting the annotation fallback (AC-2). Asserted two
  # ways: the provenance, and — via GH_ARGV_LOG — that NO `check-runs/<id>/annotations` call was
  # made for this fixture. RED-first: pre-#435 code returns the verbatim "garbage" token.
  R435B="$EXP/r435b"
  mkdir -p "$R435B/.prflow/learnings"
  cat > "$R435B/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1002,"merged_at":"2026-07-10T00:00:00Z","branch":"b1002","head_sha":"h1002","merge_commit_sha":"m1002"}
EOF
  cat > "$EXP/checkruns435b.json" <<'EOF'
{"check_runs":[{"id":42,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: garbage"}}]}
EOF
  : > "$EXP/argv435b.log"
  GH_ARGV_LOG="$EXP/argv435b.log" GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435b.json" \
    python3 "$BXR" --repo-root "$R435B" --prs 1002 >/dev/null 2>&1
  ST435B="$R435B/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 AC2: garbage token → null (never carried verbatim)" "null" "$(exp_field "$ST435B" 1002 permission_denials_count)"
  assert_eq "#435 AC2: garbage token → unparseable provenance" "unparseable" "$(exp_field "$ST435B" 1002 provenance.permission_denials_count)"
  assert_eq "#435 AC2: annotation fallback NOT consulted when a label line was seen" "no" \
    "$(grep -q 'annotations' "$EXP/argv435b.log" && echo yes || echo no)"

  # ── T435-2b sibling recovery across two Devflow Review check-runs on the same sha ────
  # First check-run's summary label is malformed; the second's carries a digit token. Phase 1
  # scans both and returns the digit verbatim with provenance check-run-summary (AC-2b).
  R435C="$EXP/r435c"
  mkdir -p "$R435C/.prflow/learnings"
  cat > "$R435C/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1003,"merged_at":"2026-07-10T00:00:00Z","branch":"b1003","head_sha":"h1003","merge_commit_sha":"m1003"}
EOF
  cat > "$EXP/checkruns435c.json" <<'EOF'
{"check_runs":[{"id":10,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: garbage"}},{"id":11,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: 7"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435c.json" \
    python3 "$BXR" --repo-root "$R435C" --prs 1003 >/dev/null 2>&1
  ST435C="$R435C/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 AC2b: sibling recovery — digit token from the second check-run wins" "7" "$(exp_field "$ST435C" 1003 permission_denials_count)"
  assert_eq "#435 AC2b: sibling-recovery provenance is check-run-summary" "check-run-summary" "$(exp_field "$ST435C" 1003 provenance.permission_denials_count)"

  # ── T435-2c fetch-failed beats unparseable ──────────────────────────────────────────
  # Two probed shas (head then merge). The head sha's check-runs fetch FAILS; the merge sha's
  # label is malformed. Phase 2 precedence: any fetch failure → fetch-failed, ahead of the
  # unparseable a seen-but-malformed label would otherwise yield (AC-2c). CHECKRUNS_FAIL_SHA
  # fails only the head sha; CHECKRUNS_JSON (malformed label) serves the merge sha.
  R435D="$EXP/r435d"
  mkdir -p "$R435D/.prflow/learnings"
  cat > "$R435D/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1004,"merged_at":"2026-07-10T00:00:00Z","branch":"b1004","head_sha":"h1004head","merge_commit_sha":"m1004merge"}
EOF
  cat > "$EXP/checkruns435d.json" <<'EOF'
{"check_runs":[{"id":20,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: garbage"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435d.json" CHECKRUNS_FAIL_SHA="h1004head" \
    python3 "$BXR" --repo-root "$R435D" --prs 1004 >/dev/null 2>&1
  ST435D="$R435D/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 AC2c: a probed-sha fetch failure → null denial count" "null" "$(exp_field "$ST435D" 1004 permission_denials_count)"
  assert_eq "#435 AC2c: fetch-failed beats unparseable" "fetch-failed" "$(exp_field "$ST435D" 1004 provenance.permission_denials_count)"

  # ── T435-2d Unicode-digit token is rejected (isascii guard) → unparseable ────────────
  # _parse_denial_summary gates a valid token on `token.isascii() and token.isdigit()`, NOT a
  # bare isdigit()/\d — the issue-#435 hardening that stops a crafted historical summary from
  # smuggling a non-ASCII "digit" (e.g. `٣`, U+0663 ARABIC-INDIC DIGIT THREE) through as a
  # verbatim count. A label line carrying such a token is seen-but-invalid, so phase 2 resolves
  # (None, "unparseable") — never the token carried verbatim. Without this fixture a regression
  # to a bare isdigit() would ship green and re-open the exact fabrication window #435 closes
  # (bare isdigit()/int() accept `٣` and would carry it as a fabricated count). RED against a
  # bare-isdigit regression; GREEN against the shipped isascii-guarded parse.
  R435E="$EXP/r435e"
  mkdir -p "$R435E/.prflow/learnings"
  cat > "$R435E/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1005,"merged_at":"2026-07-10T00:00:00Z","branch":"b1005","head_sha":"h1005","merge_commit_sha":"m1005"}
EOF
  cat > "$EXP/checkruns435e.json" <<'EOF'
{"check_runs":[{"id":50,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: ٣"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435e.json" \
    python3 "$BXR" --repo-root "$R435E" --prs 1005 >/dev/null 2>&1
  ST435E="$R435E/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 AC2d: a Unicode-digit token is never carried verbatim (null)" "null" "$(exp_field "$ST435E" 1005 permission_denials_count)"
  assert_eq "#435 AC2d: Unicode-digit token → unparseable (isascii guard rejects it)" "unparseable" "$(exp_field "$ST435E" 1005 provenance.permission_denials_count)"

  # ── T435-2e cross-sha precedence: a LATER sha's valid summary beats an EARLIER sha's
  # annotation. Two probed shas (head then merge): the head sha's Devflow Review run is
  # old-era (no label line) and carries a genuine "recorded 5 permission denial(s)"
  # annotation; the merge sha's run carries a valid digit summary token. Phase 1 scans
  # EVERY probed sha's summaries before any annotation fallback, so the merge sha's 9 wins
  # with check-run-summary provenance and the annotations endpoint is never consulted. A
  # revert to the pre-#435 per-sha interleave (summaries then annotations, one sha at a
  # time) would instead return the head sha's annotation — 5, check-run-annotation — and
  # turn all three assertions RED (the intended precedence change _resolve_denials
  # documents; PR #436 review, mutation evidence recorded in the PR).
  R435F="$EXP/r435f"
  mkdir -p "$R435F/.prflow/learnings"
  cat > "$R435F/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1006,"merged_at":"2026-07-10T00:00:00Z","branch":"b1006","head_sha":"h1006head","merge_commit_sha":"m1006merge"}
EOF
  cat > "$EXP/checkruns435f-head.json" <<'EOF'
{"check_runs":[{"id":60,"name":"Devflow Review","output":{"summary":"an old-workflow summary with no denial line"}}]}
EOF
  cat > "$EXP/checkruns435f-merge.json" <<'EOF'
{"check_runs":[{"id":61,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: 9"}}]}
EOF
  cat > "$EXP/annot435f.json" <<'EOF'
[{"message":"DevFlow: this run recorded 5 permission denial(s) — the engine attempted commands its tool profile does not grant."}]
EOF
  : > "$EXP/argv435f.log"
  GH_ARGV_LOG="$EXP/argv435f.log" GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435f-head.json" \
    CHECKRUNS_JSON2_SHA="m1006merge" CHECKRUNS_JSON2="$EXP/checkruns435f-merge.json" \
    ANNOT_JSON="$EXP/annot435f.json" \
    python3 "$BXR" --repo-root "$R435F" --prs 1006 >/dev/null 2>&1
  ST435F="$R435F/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 cross-sha: the later sha's valid summary token wins verbatim" "9" "$(exp_field "$ST435F" 1006 permission_denials_count)"
  assert_eq "#435 cross-sha: provenance is check-run-summary (never the earlier sha's annotation)" "check-run-summary" "$(exp_field "$ST435F" 1006 provenance.permission_denials_count)"
  assert_eq "#435 cross-sha: the annotation fallback is never consulted mid-scan" "no" \
    "$(grep -q 'annotations' "$EXP/argv435f.log" && echo yes || echo no)"

  # ── T435-2f mixed-era suppression: malformed label + GENUINE sibling annotation ──────
  # The doubly-rare mixed-era shape _resolve_denials documents as a deliberate loss in the
  # safe direction (issue #435 gotcha): one Devflow Review run's label is malformed
  # (garbage) while a sibling old-era run (no label line) carries a genuine "recorded 3
  # permission denial(s)" annotation. A label WAS seen, so phase 2 resolves
  # (None, "unparseable") WITHOUT consulting the annotation fallback — the annotation's 3
  # is deliberately lost, never recovered into a possibly-wrong-era count. Differs from
  # T435-2 above, whose fixture has NO annotation anywhere: here a genuine annotation IS
  # present and WOULD be found were the fallback consulted (T4 proves that recovery path
  # live on this exact message shape), so this fixture pins the suppression as intended
  # behavior — a regression dropping the label_seen short-circuit returns
  # 3/check-run-annotation and turns all three assertions RED (PR #436 review, mutation
  # evidence recorded in the PR).
  R435G="$EXP/r435g"
  mkdir -p "$R435G/.prflow/learnings"
  cat > "$R435G/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1007,"merged_at":"2026-07-10T00:00:00Z","branch":"b1007","head_sha":"h1007","merge_commit_sha":"m1007"}
EOF
  cat > "$EXP/checkruns435g.json" <<'EOF'
{"check_runs":[{"id":70,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: garbage"}},{"id":71,"name":"Devflow Review","output":{"summary":"an old-workflow summary with no denial line"}}]}
EOF
  cat > "$EXP/annot435g.json" <<'EOF'
[{"message":"DevFlow: this run recorded 3 permission denial(s) — the engine attempted commands its tool profile does not grant."}]
EOF
  : > "$EXP/argv435g.log"
  GH_ARGV_LOG="$EXP/argv435g.log" GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435g.json" ANNOT_JSON="$EXP/annot435g.json" \
    python3 "$BXR" --repo-root "$R435G" --prs 1007 >/dev/null 2>&1
  ST435G="$R435G/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 mixed-era: a genuine sibling annotation is suppressed once a label was seen (null)" "null" "$(exp_field "$ST435G" 1007 permission_denials_count)"
  assert_eq "#435 mixed-era: the loss lands on unparseable, never a possibly-wrong-era annotation count" "unparseable" "$(exp_field "$ST435G" 1007 provenance.permission_denials_count)"
  assert_eq "#435 mixed-era: the annotation fallback is not consulted despite a recoverable annotation" "no" \
    "$(grep -q 'annotations' "$EXP/argv435g.log" && echo yes || echo no)"

  # ── T435-2g exotic line terminators: the parse is line-bound, not merely \n-bound ─────
  # A crafted summary carries the label followed by a BARE CR (no LF) and a digit on the
  # next visual line. The PR #436 fix-loop finding: `[^\S\n]*` excludes only `\n`, so it
  # consumed `\r`/`\f`/`\v`/NEL/LS/PS and `(\S*)` captured the next visual line's digit —
  # an all-ASCII-digit token that sailed through validation as a fabricated verbatim count.
  # The `[ \t]*` parse ends the capture at ANY non-space/tab whitespace: label seen, token
  # empty → (None, "unparseable"), never the fabricated 7. RED under a regression to the
  # `[^\S\n]*` whitespace-class form (mutation evidence in the PR: the reverted-regex
  # scratch copy returns 7/check-run-summary, turning both assertions RED).
  R435H="$EXP/r435h"
  mkdir -p "$R435H/.prflow/learnings"
  cat > "$R435H/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1008,"merged_at":"2026-07-10T00:00:00Z","branch":"b1008","head_sha":"h1008","merge_commit_sha":"m1008"}
EOF
  cat > "$EXP/checkruns435h.json" <<'EOF'
{"check_runs":[{"id":80,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count:\r7 next-visual-line"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435h.json" \
    python3 "$BXR" --repo-root "$R435H" --prs 1008 >/dev/null 2>&1
  ST435H="$R435H/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 line-terminators: a bare-CR next-visual-line digit is never captured (null)" "null" "$(exp_field "$ST435H" 1008 permission_denials_count)"
  assert_eq "#435 line-terminators: the CR-separated label resolves to unparseable, not check-run-summary" "unparseable" "$(exp_field "$ST435H" 1008 provenance.permission_denials_count)"

  # ── T435-2h apex precedence: a later sha's VALID token beats an earlier sha's fetch failure ─
  # The head sha's check-runs fetch FAILS; the merge sha's summary carries a valid digit.
  # Phase 1 finds the valid token, so phase 2 (where fetch-failed would win) never runs —
  # the apex of the precedence lattice ("Phase 2 runs only when phase 1 found no valid
  # token"). A plausible hardening regression — early-returning (None, "fetch-failed")
  # inside the phase-1 loop the moment a fetch fails — keeps every other fixture green
  # (T4d fails ALL fetches; T435-2c's surviving sha carries only garbage) while silently
  # nulling real counts whenever the head fetch transiently fails (PR #436 review;
  # mutation evidence in the PR: the early-return scratch copy returns null/fetch-failed,
  # turning both assertions RED).
  R435I="$EXP/r435i"
  mkdir -p "$R435I/.prflow/learnings"
  cat > "$R435I/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1009,"merged_at":"2026-07-10T00:00:00Z","branch":"b1009","head_sha":"h1009head","merge_commit_sha":"m1009merge"}
EOF
  cat > "$EXP/checkruns435i.json" <<'EOF'
{"check_runs":[{"id":90,"name":"Devflow Review","output":{"summary":"verdict\n\npermission_denials_count: 6"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435i.json" CHECKRUNS_FAIL_SHA="h1009head" \
    python3 "$BXR" --repo-root "$R435I" --prs 1009 >/dev/null 2>&1
  ST435I="$R435I/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 apex: a later sha's valid token wins over an earlier sha's fetch failure" "6" "$(exp_field "$ST435I" 1009 permission_denials_count)"
  assert_eq "#435 apex: its provenance is check-run-summary (fetch-failed never reached)" "check-run-summary" "$(exp_field "$ST435I" 1009 provenance.permission_denials_count)"

  # ── T435-2i within-one-summary recovery: garbage label line, then a valid one ─────────
  # A single check-run whose SUMMARY carries two label lines — the first malformed, the
  # second a valid digit. _parse_denial_summary's finditer loop continues past the invalid
  # match to the later valid one in the SAME summary (T435-2b pins the across-check-runs
  # analogue; this pins the within-summary path). RED under a finditer→first-match-only
  # regression (mutation evidence in the PR: the single-search scratch copy returns
  # null/unparseable, turning both assertions RED). Raised by 2/5 review agents.
  R435J="$EXP/r435j"
  mkdir -p "$R435J/.prflow/learnings"
  cat > "$R435J/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1010,"merged_at":"2026-07-10T00:00:00Z","branch":"b1010","head_sha":"h1010","merge_commit_sha":"m1010"}
EOF
  cat > "$EXP/checkruns435j.json" <<'EOF'
{"check_runs":[{"id":95,"name":"Devflow Review","output":{"summary":"permission_denials_count: garbage\npermission_denials_count: 4"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435j.json" \
    python3 "$BXR" --repo-root "$R435J" --prs 1010 >/dev/null 2>&1
  ST435J="$R435J/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 within-summary: a valid label line after a garbage one still recovers the digit" "4" "$(exp_field "$ST435J" 1010 permission_denials_count)"
  assert_eq "#435 within-summary: recovery provenance is check-run-summary" "check-run-summary" "$(exp_field "$ST435J" 1010 provenance.permission_denials_count)"

  # ── T435-2j fetch-failed beats a RECOVERABLE annotation (no label anywhere) ───────────
  # One probed sha's check-runs fetch FAILS; the other sha's Devflow Review run is old-era
  # (no label line) and a genuine "recorded 5 permission denial(s)" annotation IS
  # recoverable on it. Phase 2's `any_fetch_failed` check precedes the annotation loop, so
  # the result is (None, "fetch-failed") and the annotations endpoint is never consulted —
  # the failed fetch is exactly where an unseen valid token would sit, and a positive-only
  # annotation from a partial view must not launder that unknown into a possibly-wrong
  # count. A hoist regression — moving the annotation loop above the any_fetch_failed
  # check — returns 5/check-run-annotation with every OTHER fixture green (T4d fails ALL
  # fetches so the hoisted loop has nothing cached; T435-2c's fixture defines no
  # annotation, so nothing is recoverable there) — this fixture alone turns RED
  # (PR #436 shadow pass, raised by 2/5 agents; mutation evidence recorded in the PR).
  R435K="$EXP/r435k"
  mkdir -p "$R435K/.prflow/learnings"
  cat > "$R435K/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1011,"merged_at":"2026-07-10T00:00:00Z","branch":"b1011","head_sha":"h1011head","merge_commit_sha":"m1011merge"}
EOF
  cat > "$EXP/checkruns435k.json" <<'EOF'
{"check_runs":[{"id":97,"name":"Devflow Review","output":{"summary":"an old-workflow summary with no denial line"}}]}
EOF
  cat > "$EXP/annot435k.json" <<'EOF'
[{"message":"DevFlow: this run recorded 5 permission denial(s) — the engine attempted commands its tool profile does not grant."}]
EOF
  : > "$EXP/argv435k.log"
  GH_ARGV_LOG="$EXP/argv435k.log" GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns435k.json" CHECKRUNS_FAIL_SHA="h1011head" \
    ANNOT_JSON="$EXP/annot435k.json" \
    python3 "$BXR" --repo-root "$R435K" --prs 1011 >/dev/null 2>&1
  ST435K="$R435K/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#435 partial-fetch: a recoverable annotation never launders a fetch failure (null)" "null" "$(exp_field "$ST435K" 1011 permission_denials_count)"
  assert_eq "#435 partial-fetch: provenance is fetch-failed, never check-run-annotation" "fetch-failed" "$(exp_field "$ST435K" 1011 provenance.permission_denials_count)"
  assert_eq "#435 partial-fetch: the annotation fallback is never consulted on a partial view" "no" \
    "$(grep -q 'annotations' "$EXP/argv435k.log" && echo yes || echo no)"

  # ── T3h progress-comment coherence: unparseable fallback verdict (review Fix A) ─
  # A progress comment carries the "## Verdict:" marker inline (not a `^## Verdict:`
  # line) so it does not parse, and there is no PR review → verdict null with
  # provenance "unparseable", NEVER "progress-comment" over a null (the shadow-pass
  # sibling of the pr-review coherence fix).
  R3H="$EXP/r3h"
  mkdir -p "$R3H/.prflow/learnings"
  cat > "$R3H/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":750,"merged_at":"2026-07-10T00:00:00Z","branch":"b750","head_sha":"h750","merge_commit_sha":"m750"}
EOF
  cat > "$EXP/comments3h.json" <<'EOF'
[{"id":1,"created_at":"2026-07-09T10:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** h750\n\nThis comment mentions ## Verdict: inline but has no real verdict line.\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments3h.json" \
    python3 "$BXR" --repo-root "$R3H" --prs 750 >/dev/null 2>&1
  ST3H="$R3H/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 T3h: unparseable progress-comment verdict → null value" "null" "$(exp_field "$ST3H" 750 verdict)"
  assert_eq "#431 T3h: unparseable fallback provenance (not progress-comment over a null)" "unparseable" "$(exp_field "$ST3H" 750 provenance.verdict)"

  # ── Tmeta gh-fallback metadata fetch-failure → PR skipped (fail closed) ──────
  # No retrospective entry AND the gh pr-view call fails (rc≠0) → the merge state is
  # UNESTABLISHED. The store is keyed on MERGED PRs, so the run must NOT write a row
  # asserting a merge it never established: the merged-state gate skips the PR and
  # breadcrumbs why (naming the metadata provenance, "fetch-failed"). The old behavior —
  # writing a row with a null merged_at — is exactly the fabricated-row shape the gate
  # closes (issue #431 review).
  RMETA="$EXP/rmeta"
  mkdir -p "$RMETA/.prflow/learnings"
  : > "$RMETA/.prflow/learnings/retrospectives.jsonl"
  # PR_VIEW_FAIL routed through the stub's generic non-zero exit for pr view.
  cat > "$EXP/gh-metafail" <<'STUB2'
#!/usr/bin/env bash
case "$*" in
  *"pr view"*)   echo "gh: api error" >&2; exit 1 ;;
  *"repo view"*) echo "owner/repo"; exit 0 ;;
  *)             echo '[]'; exit 0 ;;
esac
STUB2
  chmod +x "$EXP/gh-metafail"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh-metafail" \
    python3 "$BXR" --repo-root "$RMETA" --prs 940 2>"$EXP/meta.err" >/dev/null
  RC_META=$?
  STMETA="$RMETA/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tmeta: unestablished merge state → NO row written (never a fabricated merged PR)" "0" \
    "$(exp_count_lines "$STMETA")"
  # An UNESTABLISHED merge state must reach the caller's failure channel. Excluding it
  # silently would be the unknown-collapsed-onto-a-value bug in the FLOW-CONTROL dimension:
  # a gh outage would drop PRs that no later incremental pass re-selects (they never enter
  # the store, and only stored/retrospective-listed PRs become candidates), while Step 6.5's
  # exit-code guard reported a clean run (issue #431 fix-delta gate).
  assert_eq "#431 Tmeta: an unestablished merge state exits 2 (never a silently-clean run)" "2" "$RC_META"
  assert_eq "#431 Tmeta: skip breadcrumb names the unestablished metadata provenance" "yes" \
    "$(grep -q 'fetch-failed' "$EXP/meta.err" && echo yes || echo no)"

  # ── Tretro a retrospective entry IS the merge proof — never re-derived from a field ──
  # lib/scan.sh builds retrospectives.jsonl from `gh pr list --state merged`, so an entry
  # exists ONLY for a merged PR. But `merged_at` is a PROXY its producer does not guarantee:
  # lib/fetch-pr-context.sh passes it as a shell `--arg`, so a failed extraction yields ""
  # (a shape lib/compute-patterns.jq already guards), and the retrospective SKILL's
  # LLM-authored JSON can omit the key outright. Gating the retro arm on that field would
  # drop a genuinely-merged PR carrying real cost and verdict data — PERMANENTLY, since a PR
  # absent from the store is re-selected and re-skipped every week. That is the #62/#98
  # operand-contract class: a guard whose accepted-input set is narrower than its consumer's
  # contract. The row MUST still be written (issue #431 fix-delta gate).
  RRT="$EXP/rretro"
  mkdir -p "$RRT/.prflow/learnings"
  cat > "$RRT/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1080,"merged_at":"","branch":"b1080","head_sha":"h1080","merge_commit_sha":"m1080"}
{"schema_version":2,"kind":"implementation","pr":1081,"branch":"b1081","head_sha":"h1081","merge_commit_sha":"m1081"}
EOF
  seed_eff "$RRT/.prflow/logs/efficiency" "pr-1080-r.json" "pr-1080" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":55}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RRT" --prs 1080,1081 >/dev/null 2>&1
  RC_RETRO=$?
  STRT="$RRT/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tretro: an empty merged_at on a RETROSPECTIVE entry still writes its row" "1080" \
    "$(exp_field "$STRT" 1080 pr)"
  assert_eq "#431 Tretro: its cost row is preserved (the data the old proxy-gate would have dropped)" "55" \
    "$(exp_field "$STRT" 1080 efficiency_runs.0.cost.tokens)"
  assert_eq "#431 Tretro: a retrospective entry with NO merged_at key at all still writes its row" "1081" \
    "$(exp_field "$STRT" 1081 pr)"
  assert_eq "#431 Tretro: and the run is a clean success (entry presence IS the merge proof)" "0" "$RC_RETRO"

  # ── Tmerged an OPEN PR named via --prs is skipped, never stored ───────────────
  # The store is keyed on MERGED PRs — that is what makes the abandoned-run exclusion (and
  # its documented cost-side survivorship bias) true. `--prs` is an operator handle that
  # can name ANY PR, so without the gate `--prs <open-pr>` would write a row with a null
  # merged_at, a still-accumulating cost list, and a verdict scraped from an in-flight
  # review — entering the store as a shipped PR and skewing the very cost-vs-outcome
  # comparison the store exists to make (issue #431 review).
  ROPEN="$EXP/ropen"
  mkdir -p "$ROPEN/.prflow/learnings"
  : > "$ROPEN/.prflow/learnings/retrospectives.jsonl"
  cat > "$EXP/prview-open.json" <<'EOF'
{"mergedAt":null,"mergeCommit":null,"headRefName":"open-branch","headRefOid":"hopen","closingIssuesReferences":[],"state":"OPEN"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" PR_VIEW_JSON="$EXP/prview-open.json" \
    python3 "$BXR" --repo-root "$ROPEN" --prs 990 2>"$EXP/open.err" >/dev/null
  RC_OPEN=$?
  STOPEN="$ROPEN/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tmerged: an OPEN PR named via --prs writes NO row (store is merged-PR-keyed)" "0" \
    "$(exp_count_lines "$STOPEN")"
  assert_eq "#431 Tmerged: skip breadcrumb states the merged-PR keying" "yes" \
    "$(grep -q 'keyed on merged PRs' "$EXP/open.err" && echo yes || echo no)"
  # An OBSERVED not-merged PR (the gh call SUCCEEDED and said so) is a clean, intentional
  # exclusion — exit 0. Contrast Tmeta, where the state could not be established at all
  # and the run must exit 2. The two must not be conflated in either direction.
  assert_eq "#431 Tmerged: an OBSERVED-open PR is a clean exclusion, so the run exits 0" "0" "$RC_OPEN"

  # ── Tdup duplicate efficiency records, SAME slug — never newest-wins ──────────
  RDUP="$EXP/rdup"
  mkdir -p "$RDUP/.prflow/learnings"
  cat > "$RDUP/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":930,"merged_at":"2026-07-10T00:00:00Z","branch":"b930","merge_commit_sha":"m930"}
EOF
  seed_eff "$RDUP/.prflow/logs/efficiency" "pr-930-runA.json" "pr-930" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":11}}}]' 'null'
  seed_eff "$RDUP/.prflow/logs/efficiency" "pr-930-runB.json" "pr-930" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":22}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RDUP" --prs 930 >/dev/null 2>&1
  STDUP="$RDUP/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tdup: two same-slug efficiency runs both listed (never newest-wins)" "2" \
    "$(python3 -c 'import json,sys;print(len(json.loads([l for l in open(sys.argv[1])][0])["efficiency_runs"]))' "$STDUP")"

  # ── Tann annotation-fetch failure → fetch-failed, not absent ─────────────────
  # The convergence-shadow class (issue #431 iter-3): the ANNOTATION sub-fetch read
  # through the ok-discarding _gh_json wrapper, so an annotations call that FAILED
  # (rc≠0) was laundered into a measured "absent" — asserting we looked and found no
  # denial count when in fact we never established one. The check-run exists and
  # carries NO summary count, so the annotation path is the only route to a value:
  # with it failing, the count is unestablished.
  RANN="$EXP/rann"
  mkdir -p "$RANN/.prflow/learnings"
  cat > "$RANN/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":960,"merged_at":"2026-07-10T00:00:00Z","branch":"b960","head_sha":"h960","merge_commit_sha":"m960"}
EOF
  cat > "$EXP/checkruns-ann.json" <<'EOF'
{"check_runs":[{"id":77,"name":"Devflow Review","output":{"summary":"no count line here"}}]}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    CHECKRUNS_JSON="$EXP/checkruns-ann.json" ANNOT_FAIL=1 \
    python3 "$BXR" --repo-root "$RANN" --prs 960 >/dev/null 2>&1
  STANN="$RANN/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tann: annotation fetch failure → denial provenance fetch-failed (not absent)" "fetch-failed" "$(exp_field "$STANN" 960 provenance.permission_denials_count)"
  assert_eq "#431 Tann: annotation fetch failure → denial value null (never a fabricated 0)" "null" "$(exp_field "$STANN" 960 permission_denials_count)"

  # ── Tnosha no probeable sha → no-sha (unestablished by cascade), not absent ───
  # A retrospective entry establishes the PR merged (so the merged-state gate admits it)
  # but carries NO head_sha / merge_commit_sha — the shape an older retrospective schema
  # leaves behind. There is then NOTHING to query the check-runs/config out of, so the
  # denial count and fingerprint are unestablished BY CASCADE — "no-sha" — never the
  # measured-and-found-nothing "absent" (issue #431 iter-3 shadow).
  RNS="$EXP/rnosha"
  mkdir -p "$RNS/.prflow/learnings"
  cat > "$RNS/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":970,"merged_at":"2026-07-10T00:00:00Z","branch":"b970"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RNS" --prs 970 >/dev/null 2>&1
  STNS="$RNS/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tnosha: no probeable sha → denial provenance no-sha (not absent)" "no-sha" "$(exp_field "$STNS" 970 provenance.permission_denials_count)"
  assert_eq "#431 Tnosha: no probeable sha → fingerprint provenance no-sha (not absent)" "no-sha" "$(exp_field "$STNS" 970 provenance.config_fingerprint)"
  assert_eq "#431 Tnosha: unestablished denial stays null" "null" "$(exp_field "$STNS" 970 permission_denials_count)"

  # ── Tnorepo unresolvable repo → no-repo on every gh-sourced join ──────────────
  # With no repo, NOTHING is queryable: the verdict, Important count, and denial count
  # are unestablished. Reading any of them as "absent" would assert a measurement the run
  # never made. The retrospective entry still joins locally (no gh needed), so the row is
  # written — a cost row with honestly-unestablished outcomes.
  RNR="$EXP/rnorepo"
  mkdir -p "$RNR/.prflow/learnings"
  cat > "$RNR/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":980,"merged_at":"2026-07-10T00:00:00Z","branch":"b980","head_sha":"h980","merge_commit_sha":"m980"}
EOF
  cat > "$EXP/gh-norepo" <<'STUB3'
#!/usr/bin/env bash
case "$*" in
  *"repo view"*) echo "gh: could not resolve repo" >&2; exit 1 ;;
  *)             echo "gh: no repo" >&2; exit 1 ;;
esac
STUB3
  chmod +x "$EXP/gh-norepo"
  GITHUB_REPOSITORY="" DEVFLOW_GH="$EXP/gh-norepo" \
    python3 "$BXR" --repo-root "$RNR" --prs 980 >/dev/null 2>&1
  STNR="$RNR/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tnorepo: unresolvable repo → verdict provenance no-repo (not absent)" "no-repo" "$(exp_field "$STNR" 980 provenance.verdict)"
  assert_eq "#431 Tnorepo: unresolvable repo → important-count provenance no-repo" "no-repo" "$(exp_field "$STNR" 980 provenance.important_finding_count)"
  assert_eq "#431 Tnorepo: unresolvable repo → denial provenance no-repo (not absent)" "no-repo" "$(exp_field "$STNR" 980 provenance.permission_denials_count)"
  assert_eq "#431 Tnorepo: unresolvable repo → row still written from the local retrospective join" "980" "$(exp_field "$STNR" 980 pr)"

  # ── Tcoh provenance-coherence invariant is ENFORCED, not merely documented ────
  # The record's type-level invariant: an UNESTABLISHED provenance
  # (fetch-failed/no-repo/no-sha) may never sit beside a non-null value — that pairing
  # would publish a fabricated measurement out of a join that never happened. Drive the
  # check directly with an incoherent record and assert it RAISES; then assert a
  # coherent record (same unestablished source, null value) passes, so the guard is not
  # merely rejecting everything.
  python3 - "$BXR" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)

# A COMPLETE record — every field _PROVENANCED_FIELDS governs, all null; fixtures override
# only the field under test. Completeness is load-bearing: the guard fails CLOSED on a
# missing governed key, so a partial dict would be rejected for THAT reason and a negative
# test would go green without ever exercising the coherence check it names (#431 review).
def full(prov, **over):
    rec = {f: None for fs in ber._PROVENANCED_FIELDS.values() for f in fs}
    rec.update(over)
    rec["provenance"] = prov
    return rec

# Attribute the rejection: more than one guard here can raise AssertionError, so a bare
# type check cannot tell the coherence check from the stale-map presence check. Pin the
# rejecting guard's own message.
def raises_with(record, needle):
    try:
        ber._assert_provenance_coherent(record)
    except AssertionError as e:
        return needle in str(e)
    return False

# A scalar join publishing a value out of an unqueryable source.
if not raises_with(full({"permission_denials_count": "no-sha"}, permission_denials_count=0),
                   "unqueryable join must never publish a value"):
    sys.exit(1)
# The one-to-MANY case: `retrospective` governs the four metadata fields, so back-filling
# e.g. `branch` from a slug heuristic while the metadata fetch failed must also raise.
# Today those fields are null on every unestablished path, so the invariant holds only by
# ACCIDENT there — checking them is what makes it hold by construction (#431 review).
if not raises_with(full({"retrospective": "fetch-failed"}, branch="guessed-from-slug"),
                   "unqueryable join must never publish a value"):
    sys.exit(1)
# Stale-map drift fails CLOSED: rename a governed field out of the record (i.e. forget to
# update _PROVENANCED_FIELDS) and the guard must RAISE, not silently stop governing it —
# the `.get()`-based check failed OPEN exactly here (#431 review Suggestion 2).
_stale = full({"verdict": "found"})
del _stale["verdict"]
if not raises_with(_stale, "_PROVENANCED_FIELDS is stale"):
    sys.exit(1)
# Positive control: the same unestablished sources beside NULL values must NOT raise, so
# the guard is discriminating rather than blanket-rejecting.
ber._assert_provenance_coherent(full({"permission_denials_count": "no-sha",
                                      "retrospective": "fetch-failed"}))
sys.exit(0)
PY
  # Capture rc on the line immediately after the heredoc: a later edit inserting ANY
  # command between the two would silently rewire `$?` to that command's status and make
  # the assertion pass unconditionally (issue #431 review).
  RC_COH=$?
  assert_eq "#431 Tcoh: unestablished provenance beside a non-null value raises (coherence enforced)" "0" "$RC_COH"

  # ── Tjoin the Reviewed-HEAD join actually SELECTS — not "first comment wins" ──
  # The headline join (review.commit_id == the comment's "Reviewed HEAD:" line) was
  # asserted by NAME only: every fixture with both a review and a findings-bearing comment
  # used the SAME sha on both sides, so a mutant replacing the join condition with `if
  # True:` stayed fully GREEN (verified). Drive the NON-matching head: a re-review posts a
  # fresh progress comment for HEAD hY while the first completed review sits at hX. The
  # count must be null/absent — a regression to "latest comment wins" would stamp a
  # SUPERSEDED run's finding count onto the PR, silently corrupting the primary outcome
  # variable (issue #431 convergence shadow).
  RJ="$EXP/rjoin"
  mkdir -p "$RJ/.prflow/learnings"
  cat > "$RJ/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1090,"merged_at":"2026-07-10T00:00:00Z","branch":"b1090","head_sha":"hX","merge_commit_sha":"m1090"}
EOF
  cat > "$EXP/reviews-join.json" <<'EOF'
[{"state":"COMMENTED","submitted_at":"2026-07-09T10:00:00Z","commit_id":"hX","body":"## Verdict: APPROVE"}]
EOF
  cat > "$EXP/comments-join.json" <<'EOF'
[{"id":21,"created_at":"2026-07-09T12:00:00Z","body":"<!-- devflow:review-progress run=2 -->\n**Reviewed HEAD:** hY\n\n## Code Review Findings\n\n### 🟠 Important / Major\n1. imp one\n2. imp two\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews-join.json" COMMENTS_JSON="$EXP/comments-join.json" \
    python3 "$BXR" --repo-root "$RJ" --prs 1090 >/dev/null 2>&1
  STJ="$RJ/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tjoin: a comment for a DIFFERENT head does not supply the count (superseded)" "null" \
    "$(exp_field "$STJ" 1090 important_finding_count)"
  assert_eq "#431 Tjoin: the unjoined count is provenance-absent, and the row still exists" "absent" \
    "$(exp_field "$STJ" 1090 provenance.important_finding_count)"
  # Positive control on the same fixture family: add a comment AT the review's head with a
  # DIFFERENT count. The join must SELECT it (1), not merely filter or take the first (2) —
  # this is what pins the join as a selection rather than an accident of ordering.
  RJ2="$EXP/rjoin2"
  mkdir -p "$RJ2/.prflow/learnings"
  cp "$RJ/.prflow/learnings/retrospectives.jsonl" "$RJ2/.prflow/learnings/retrospectives.jsonl"
  cat > "$EXP/comments-join2.json" <<'EOF'
[{"id":21,"created_at":"2026-07-09T12:00:00Z","body":"<!-- devflow:review-progress run=2 -->\n**Reviewed HEAD:** hY\n\n## Code Review Findings\n\n### 🟠 Important / Major\n1. imp one\n2. imp two\n"},{"id":22,"created_at":"2026-07-09T13:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** hX\n\n## Code Review Findings\n\n### 🟠 Important / Major\n1. only one\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/reviews-join.json" COMMENTS_JSON="$EXP/comments-join2.json" \
    python3 "$BXR" --repo-root "$RJ2" --prs 1090 >/dev/null 2>&1
  assert_eq "#431 Tjoin: the join SELECTS the comment matching the review's commit_id (1, not 2)" "1" \
    "$(exp_field "$RJ2/.prflow/learnings/experiment-records.jsonl" 1090 important_finding_count)"

  # ── Tprview an rc-0 unparseable `gh pr view` is UNESTABLISHED, not "not merged" ──
  # _gh_pr_meta is the one wrapper whose result feeds a FLOW-CONTROL decision, so laundering
  # an unparseable body into ok=True made the merged-state gate take the OBSERVED-not-merged
  # arm: the run breadcrumbed "observed not-merged", counted a clean skip and exited 0 — and
  # a merged PR was dropped from the store permanently while the retrospective reported a
  # clean run (issue #431 convergence shadow, reproduced against HEAD).
  RPV="$EXP/rprview"
  mkdir -p "$RPV/.prflow/learnings"
  : > "$RPV/.prflow/learnings/retrospectives.jsonl"
  cat > "$EXP/gh-prgarbage" <<'STUB5'
#!/usr/bin/env bash
case "$*" in
  *"pr view"*)   echo "<html>502 Bad Gateway</html>"; exit 0 ;;
  *"repo view"*) echo "owner/repo"; exit 0 ;;
  *)             echo '[]'; exit 0 ;;
esac
STUB5
  chmod +x "$EXP/gh-prgarbage"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh-prgarbage" \
    python3 "$BXR" --repo-root "$RPV" --prs 1100 2>"$EXP/prview.err" >/dev/null
  RC_PV=$?
  assert_eq "#431 Tprview: an rc-0 unparseable gh pr view exits 2 (unestablished, not 'not merged')" "2" "$RC_PV"
  assert_eq "#431 Tprview: it writes NO row (a merged PR is never silently dropped)" "0" \
    "$(exp_count_lines "$RPV/.prflow/learnings/experiment-records.jsonl")"
  assert_eq "#431 Tprview: and it is NOT breadcrumbed as an observed exclusion" "no" \
    "$(grep -q 'observed not-merged' "$EXP/prview.err" && echo yes || echo no)"

  # ── Tvocab the provenance vocabulary is CLOSED in code, not just in the comments ──
  # The coherence guard tests membership in PROVENANCE_UNESTABLISHED and would `continue`
  # past any value it does not recognize — so a typo'd tag ("fetch_failed") or a future
  # unestablished-meaning tag omitted from the tuple would silently bypass the check and
  # publish a fabricated measurement: the guard failing open exactly where it claims to
  # fail closed (issue #431 convergence shadow).
  python3 - "$BXR" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)

# A COMPLETE record (see Tcoh): the guard fails closed on a missing governed key, so a
# partial dict would be rejected by THAT check and this test would never reach the
# vocabulary check it names.
def full(prov, **over):
    rec = {f: None for fs in ber._PROVENANCED_FIELDS.values() for f in fs}
    rec.update(over)
    rec["provenance"] = prov
    return rec

# Attribute the rejection to the vocabulary check, not to some other AssertionError.
def raises_with(record, needle):
    try:
        ber._assert_provenance_coherent(record)
    except AssertionError as e:
        return needle in str(e)
    return False

# A TYPO'd unestablished tag must not slip through beside a published value.
if not raises_with(full({"permission_denials_count": "fetch_failed"}, permission_denials_count=0),
                   "unrecognized source"):
    sys.exit(1)
# Positive control: every LISTED tag is accepted, so the guard is discriminating rather
# than blanket-rejecting. (Note what this does and does not prove: it loops over the
# vocabulary itself, so it cannot show that every tag a RESOLVER emits is in the list —
# that direction is covered by the per-arm provenance assertions elsewhere in this block,
# each of which would raise here if its tag were missing from the vocabulary.)
for tag in ber.PROVENANCE_SOURCES:
    ber._assert_provenance_coherent(full({"verdict": tag}))
sys.exit(0)
PY
  RC_VOC=$?
  assert_eq "#431 Tvocab: an unrecognized provenance tag raises (the vocabulary is closed in code)" "0" "$RC_VOC"

  # ── Tstore the DESTINATION store is read STRICTLY — never truncated silently ──
  # main() does not append to the store, it REWRITES it from what the read returned, and
  # lib/open-state-pr.sh commits the result. So a tolerated read error is DESTRUCTIVE, not
  # merely lossy: one corrupt line (a half-written record from a killed prior run) would
  # silently DELETE every historical record the read could not account for, and ship the
  # truncation in the state PR. Fail closed instead (issue #431 review).
  RST="$EXP/rstore"
  mkdir -p "$RST/.prflow/learnings"
  cat > "$RST/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1010,"merged_at":"2026-07-10T00:00:00Z","branch":"b1010","merge_commit_sha":"m1010"}
EOF
  # A store carrying one good record and one corrupt line.
  printf '%s\n' '{"pr":1000,"verdict":"APPROVE"}' 'this is not json' \
    > "$RST/.prflow/learnings/experiment-records.jsonl"
  STORE_BEFORE="$(cat "$RST/.prflow/learnings/experiment-records.jsonl")"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RST" --prs 1010 >/dev/null 2>&1
  RC_STORE=$?
  assert_eq "#431 Tstore: a corrupt existing store line makes the run exit 2 (refuses to rewrite)" "2" "$RC_STORE"
  assert_eq "#431 Tstore: the store is left BYTE-IDENTICAL — the good record was not silently dropped" "yes" \
    "$([ "$STORE_BEFORE" = "$(cat "$RST/.prflow/learnings/experiment-records.jsonl")" ] && echo yes || echo no)"

  # A well-formed JSON line with no `pr` key is the same destructive shape: the rewrite is
  # keyed on `pr`, so such a line is not merely ignored — it is dropped from the output.
  RST2="$EXP/rstore2"
  mkdir -p "$RST2/.prflow/learnings"
  : > "$RST2/.prflow/learnings/retrospectives.jsonl"
  printf '%s\n' '{"verdict":"APPROVE","note":"no pr key"}' \
    > "$RST2/.prflow/learnings/experiment-records.jsonl"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RST2" --prs 1011 >/dev/null 2>&1
  assert_eq "#431 Tstore: a store line with no 'pr' key also fails closed (would be dropped by the rewrite)" "2" "$?"

  # ── Tunparse rc-0 with an unparseable body is UNESTABLISHED, not absent ───────
  # The gh call exits 0 but returns garbage (a truncated response, an HTML proxy error
  # page). Reading that as a successful measurement laundered it into "absent" — the
  # strong claim "we looked and it genuinely was not there" — which the coherence check
  # cannot catch, because the value is null while the provenance claims success.
  RUP="$EXP/runparse"
  mkdir -p "$RUP/.prflow/learnings"
  cat > "$RUP/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1020,"merged_at":"2026-07-10T00:00:00Z","branch":"b1020","head_sha":"h1020","merge_commit_sha":"m1020"}
EOF
  cat > "$EXP/gh-garbage" <<'STUB4'
#!/usr/bin/env bash
case "$*" in
  *"repo view"*) echo "owner/repo"; exit 0 ;;
  *reviews*)     echo "<html>502 Bad Gateway</html>"; exit 0 ;;
  *)             echo '[]'; exit 0 ;;
esac
STUB4
  chmod +x "$EXP/gh-garbage"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh-garbage" \
    python3 "$BXR" --repo-root "$RUP" --prs 1020 >/dev/null 2>&1
  STUP="$RUP/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tunparse: rc-0 unparseable body → verdict provenance fetch-failed (not absent)" "fetch-failed" "$(exp_field "$STUP" 1020 provenance.verdict)"
  assert_eq "#431 Tunparse: rc-0 unparseable body → verdict value stays null" "null" "$(exp_field "$STUP" 1020 verdict)"

  # ── Tdegraded a comment-sourced verdict recovered because the REVIEWS call failed ──
  # is not the same fact as one recovered because the reviews genuinely had none. The
  # authoritative surface was unreachable, so the comment verdict may predate final HEAD.
  RDG="$EXP/rdegraded"
  mkdir -p "$RDG/.prflow/learnings"
  cat > "$RDG/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1030,"merged_at":"2026-07-10T00:00:00Z","branch":"b1030","head_sha":"h1030","merge_commit_sha":"m1030"}
EOF
  cat > "$EXP/comments1030.json" <<'EOF'
[{"id":9,"created_at":"2026-07-09T10:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** h1030\n\n## Verdict: APPROVE\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_FAIL=1 COMMENTS_JSON="$EXP/comments1030.json" \
    python3 "$BXR" --repo-root "$RDG" --prs 1030 >/dev/null 2>&1
  STDG="$RDG/.prflow/learnings/experiment-records.jsonl"
  # A BARE tag — every inhabitant of a provenance field must be matchable on equality, or a
  # consumer testing `== "progress-comment"` silently misses every degraded row. (An earlier
  # revision of this very fix used a prose tag, reintroducing the exact defect it removed
  # from the denial tag — caught by the fix-delta gate.) The reason lives in provenance.notes.
  assert_eq "#431 Tdegraded: comment verdict used because reviews were unestablished is marked degraded" \
    "progress-comment-degraded" "$(exp_field "$STDG" 1030 provenance.verdict)"
  assert_eq "#431 Tdegraded: the degradation reason is recorded in provenance.notes" "yes" \
    "$(python3 -c 'import json,sys
r=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][0]
print("yes" if any("may predate the final reviewed HEAD" in n for n in r["provenance"]["notes"]) else "no")' "$STDG")"

  # ── Tdegraded-marker the SAME degradation, reached through the #1030 producer marker ──
  # Previously unreachable by the suite: both marker-arm cases resolved reviews_ok=true, so
  # the `progress-comment-marker-degraded` tag was never produced and the caller's
  # caveat-note condition was never exercised against it. That is the arm the guard rule
  # requires a test for — a new selection arm widened the input set while the downstream
  # note derivation still tested the OLD value on equality, so a degraded marker row shipped
  # WITHOUT the caveat its prose sibling gets. Assert BOTH halves: the distinguishable tag
  # AND the note, because the tag alone passed throughout the defect.
  RDGM="$EXP/rdegraded-marker"
  mkdir -p "$RDGM/.prflow/learnings"
  cat > "$RDGM/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1031,"merged_at":"2026-07-10T00:00:00Z","branch":"b1031","head_sha":"h1031","merge_commit_sha":"m1031"}
EOF
  jq -nc --arg b '<!-- prflow:review-progress run=1 -->'$'\n'"<!-- prflow:review-verdict head=$EXP_M_HEAD verdict=APPROVE -->"$'\n''**Reviewed HEAD:** h1031' \
    '[{id:9,created_at:"2026-07-09T10:00:00Z",body:$b}]' > "$EXP/comments1031.json"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_FAIL=1 COMMENTS_JSON="$EXP/comments1031.json" \
    python3 "$BXR" --repo-root "$RDGM" --prs 1031 >/dev/null 2>&1
  STDGM="$RDGM/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 Tdegraded-marker: an unreachable reviews call degrades the MARKER arm too" \
    "APPROVE-progress-comment-marker-degraded" \
    "$(exp_field "$STDGM" 1031 verdict)-$(exp_field "$STDGM" 1031 provenance.verdict)"
  assert_eq "#1030 Tdegraded-marker: the marker arm carries the same degradation caveat as its prose sibling" "yes" \
    "$(python3 -c 'import json,sys
r=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][0]
print("yes" if any("may predate the final reviewed HEAD" in n for n in r["provenance"]["notes"]) else "no")' "$STDGM")"
  # Negative control: with the reviews call REACHABLE the same comment yields the
  # undegraded tag and no caveat, so the assertions above are about the degradation and
  # not about the marker arm always carrying a note.
  RDGM2="$EXP/rdegraded-marker-ok"
  mkdir -p "$RDGM2/.prflow/learnings"
  cat > "$RDGM2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1032,"merged_at":"2026-07-10T00:00:00Z","branch":"b1032","head_sha":"h1032","merge_commit_sha":"m1032"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    REVIEWS_JSON="$EXP/does-not-exist" COMMENTS_JSON="$EXP/comments1031.json" \
    python3 "$BXR" --repo-root "$RDGM2" --prs 1032 >/dev/null 2>&1
  STDGM2="$RDGM2/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#1030 Tdegraded-marker control: a reachable reviews call yields the undegraded tag and no caveat" \
    "progress-comment-marker-no" \
    "$(exp_field "$STDGM2" 1032 provenance.verdict)-$(python3 -c 'import json,sys
r=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][0]
print("yes" if any("may predate the final reviewed HEAD" in n for n in r["provenance"]["notes"]) else "no")' "$STDGM2")"

  # ── Tmixed disagreeing per-run fingerprints → mixed-across-runs, never first-wins ──
  # config_fingerprint is the experiment's ATTRIBUTION KEY. A PR whose runs straddled a
  # config change must not be stamped with the older variant — that misattributes its
  # outcome in exactly the config-vs-outcome comparison the store exists to support.
  RMX="$EXP/rmixed"
  mkdir -p "$RMX/.prflow/learnings"
  cat > "$RMX/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1040,"merged_at":"2026-07-10T00:00:00Z","branch":"b1040","merge_commit_sha":"m1040"}
EOF
  seed_eff "$RMX/.prflow/logs/efficiency" "pr-1040-a.json" "pr-1040" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"sha256":"OLDFP","partial":false,"salient":{}}'
  seed_eff "$RMX/.prflow/logs/efficiency" "pr-1040-b.json" "pr-1040" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{"sha256":"NEWFP","partial":false,"salient":{}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX" --prs 1040 >/dev/null 2>&1
  STMX="$RMX/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tmixed: disagreeing run fingerprints → provenance mixed-across-runs (never first-wins)" \
    "mixed-across-runs" "$(exp_field "$STMX" 1040 provenance.config_fingerprint)"
  assert_eq "#431 Tmixed: disagreeing run fingerprints → record-level value is null" "null" \
    "$(exp_field "$STMX" 1040 config_fingerprint)"
  assert_eq "#431 Tmixed: per-run fingerprints are still preserved in efficiency_runs[]" "2" \
    "$(python3 -c 'import json,sys;print(len(json.loads([l for l in open(sys.argv[1])][0])["efficiency_runs"]))' "$STMX")"
  # Agreeing runs still publish the shared fingerprint (positive control — the guard is
  # discriminating, not blanket-nulling).
  RMX2="$EXP/rmixed2"
  mkdir -p "$RMX2/.prflow/learnings"
  cat > "$RMX2/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1041,"merged_at":"2026-07-10T00:00:00Z","branch":"b1041","merge_commit_sha":"m1041"}
EOF
  seed_eff "$RMX2/.prflow/logs/efficiency" "pr-1041-a.json" "pr-1041" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"sha256":"SAMEFP","partial":false,"salient":{}}'
  seed_eff "$RMX2/.prflow/logs/efficiency" "pr-1041-b.json" "pr-1041" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{"sha256":"SAMEFP","partial":false,"salient":{}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX2" --prs 1041 >/dev/null 2>&1
  assert_eq "#431 Tmixed: AGREEING run fingerprints still publish the shared value (positive control)" \
    "efficiency-record" "$(exp_field "$RMX2/.prflow/learnings/experiment-records.jsonl" 1041 provenance.config_fingerprint)"
  # Agreement is on sha256 — the IDENTITY — not on the whole {sha256,partial,salient}
  # envelope. `salient` is a projection of SALIENT_KEYS, an explicitly growable tuple: an
  # envelope comparison would make two runs against an UNCHANGED config compare unequal the
  # moment a fourth key is added, firing mixed-across-runs on a config change that never
  # happened and destroying the attribution axis it protects (issue #431 shadow).
  RMX3="$EXP/rmixed3"
  mkdir -p "$RMX3/.prflow/learnings"
  cat > "$RMX3/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1042,"merged_at":"2026-07-10T00:00:00Z","branch":"b1042","merge_commit_sha":"m1042"}
EOF
  seed_eff "$RMX3/.prflow/logs/efficiency" "pr-1042-a.json" "pr-1042" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"sha256":"SAMEFP","partial":false,"salient":{"max_iterations":5}}'
  seed_eff "$RMX3/.prflow/logs/efficiency" "pr-1042-b.json" "pr-1042" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{"sha256":"SAMEFP","partial":false,"salient":{"max_iterations":5,"a_new_salient_key":"x"}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX3" --prs 1042 >/dev/null 2>&1
  assert_eq "#431 Tmixed: same sha256 + a GROWN salient projection is NOT a config change" \
    "efficiency-record" "$(exp_field "$RMX3/.prflow/learnings/experiment-records.jsonl" 1042 provenance.config_fingerprint)"
  # An UNUSABLE identity must be NON-COMPARABLE, never equal-to-itself: two envelopes that
  # both LACK sha256 must not compare equal (None == None) and publish a confident
  # single-config attribution over runs that straddled a config change. That false
  # agreement is the dangerous direction — _index_efficiency copies config_fingerprint raw
  # out of arbitrary JSON, so a legacy/hand-edited record is squarely in scope (#431
  # fix-delta gate).
  RMX4="$EXP/rmixed4"
  mkdir -p "$RMX4/.prflow/learnings"
  cat > "$RMX4/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1043,"merged_at":"2026-07-10T00:00:00Z","branch":"b1043","merge_commit_sha":"m1043"}
EOF
  seed_eff "$RMX4/.prflow/logs/efficiency" "pr-1043-a.json" "pr-1043" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"partial":false,"salient":{"max_iterations":3}}'
  seed_eff "$RMX4/.prflow/logs/efficiency" "pr-1043-b.json" "pr-1043" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{"partial":false,"salient":{"max_iterations":9}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX4" --prs 1043 >/dev/null 2>&1
  ST_MX4="$RMX4/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tmixed: and no fingerprint is published from an unusable identity" "null" \
    "$(exp_field "$ST_MX4" 1043 config_fingerprint)"
  # An UNUSABLE identity is UNESTABLISHED — it is NOT a measured disagreement. Tagging it
  # `mixed-across-runs` would assert the runs straddled a config change: a fabricated fact,
  # collapsing unknown onto a real value in the very field this guard protects. (The fake
  # merge sha makes the fall-through recompute fail, so this lands on fetch-failed.)
  assert_eq "#431 Tmixed: an unusable identity is unestablished, NEVER a claimed config change" "no" \
    "$([ "$(exp_field "$ST_MX4" 1043 provenance.config_fingerprint)" = "mixed-across-runs" ] && echo yes || echo no)"
  assert_eq "#431 Tmixed: it falls through to the merge-commit recompute (unestablished there)" "fetch-failed" \
    "$(exp_field "$ST_MX4" 1043 provenance.config_fingerprint)"
  # The absurd shape that makes the mislabel unmistakable: ONE run cannot disagree with
  # itself, so a single sha256-less record must never read as "mixed across runs".
  RMX5="$EXP/rmixed5"
  mkdir -p "$RMX5/.prflow/learnings"
  cat > "$RMX5/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1044,"merged_at":"2026-07-10T00:00:00Z","branch":"b1044","merge_commit_sha":"m1044"}
EOF
  seed_eff "$RMX5/.prflow/logs/efficiency" "pr-1044-a.json" "pr-1044" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"partial":false,"salient":{"max_iterations":3}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX5" --prs 1044 >/dev/null 2>&1
  assert_eq "#431 Tmixed: a SINGLE sha256-less run is never 'mixed across runs' (it cannot disagree with itself)" "no" \
    "$([ "$(exp_field "$RMX5/.prflow/learnings/experiment-records.jsonl" 1044 provenance.config_fingerprint)" = "mixed-across-runs" ] && echo yes || echo no)"

  # An OBSERVED disagreement cannot be UN-observed by an unusable sibling. Gating the
  # disagreement check on "all identities usable" meant ids [X, Y, <unusable>] — a
  # demonstrated straddle — fell through and published a CONFIDENT merge-commit-config
  # attribution: adding a third, LESS informative run flipped the record from "refuses to
  # attribute" to "confidently attributed", while the code held positive evidence the runs
  # did not share one config (#431 delta review, reproduced). Give this fixture a REAL,
  # resolvable merge sha so the fall-through would genuinely succeed if it were taken —
  # otherwise the assertion could pass for the wrong reason.
  RMX6="$EXP/rmixed6"
  mkdir -p "$RMX6/.prflow/learnings"
  git init -q "$RMX6" 2>/dev/null
  git -C "$RMX6" config user.email t@t.t; git -C "$RMX6" config user.name t
  cat > "$RMX6/.prflow/config.json" <<'EOF'
{"prflow_review":{"verdict_severity_threshold":"important"},"prflow_review_and_fix":{"max_iterations":5}}
EOF
  git -C "$RMX6" add -A >/dev/null 2>&1
  git -C "$RMX6" commit -qm seed >/dev/null 2>&1
  MX6SHA="$(git -C "$RMX6" rev-parse HEAD)"
  cat > "$RMX6/.prflow/learnings/retrospectives.jsonl" <<EOF
{"schema_version":2,"kind":"implementation","pr":1045,"merged_at":"2026-07-10T00:00:00Z","branch":"b1045","merge_commit_sha":"$MX6SHA"}
EOF
  seed_eff "$RMX6/.prflow/logs/efficiency" "pr-1045-a.json" "pr-1045" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"sha256":"XXX","partial":false,"salient":{}}'
  seed_eff "$RMX6/.prflow/logs/efficiency" "pr-1045-b.json" "pr-1045" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{"sha256":"YYY","partial":false,"salient":{}}'
  seed_eff "$RMX6/.prflow/logs/efficiency" "pr-1045-c.json" "pr-1045" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":30}}}]' '{"partial":false,"salient":{}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX6" --prs 1045 >/dev/null 2>&1
  ST_MX6="$RMX6/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tmixed: an unusable sibling cannot UN-observe a real disagreement" \
    "mixed-across-runs" "$(exp_field "$ST_MX6" 1045 provenance.config_fingerprint)"
  assert_eq "#431 Tmixed: and no confident attribution is published over an observed straddle" "null" \
    "$(exp_field "$ST_MX6" 1045 config_fingerprint)"

  # The `unparseable` arm: a fingerprint was present but its identity could not be read, AND
  # there is no merge sha to recompute from. Both new fixtures above seed a merge sha, so
  # this arm was unreached — a mutant returning "no-sha" (or "mixed-across-runs") there
  # would have stayed GREEN (#431 delta review).
  RMX7="$EXP/rmixed7"
  mkdir -p "$RMX7/.prflow/learnings"
  cat > "$RMX7/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1046,"merged_at":"2026-07-10T00:00:00Z","branch":"b1046"}
EOF
  seed_eff "$RMX7/.prflow/logs/efficiency" "pr-1046-a.json" "pr-1046" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"partial":false,"salient":{}}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX7" --prs 1046 >/dev/null 2>&1
  assert_eq "#431 Tmixed: an unreadable identity with no sha to recompute from is 'unparseable'" \
    "unparseable" "$(exp_field "$RMX7/.prflow/learnings/experiment-records.jsonl" 1046 provenance.config_fingerprint)"
  # And `unparseable` is a MEMBER of the unestablished vocabulary, so the coherence guard
  # governs it by construction rather than by accident.
  python3 - "$BXR" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)
if "unparseable" not in ber.PROVENANCE_UNESTABLISHED:
    sys.exit(1)
try:
    ber._assert_provenance_coherent({"config_fingerprint": {"sha256": "x"},
                                     "provenance": {"config_fingerprint": "unparseable"}})
except AssertionError:
    sys.exit(0)
sys.exit(1)
PY
  RC_UNP=$?
  assert_eq "#431 Tmixed: 'unparseable' is governed by the unestablished null-only invariant" "0" "$RC_UNP"

  # A PRESENT-BUT-FALSY envelope ({}) is a CORRUPT identity, not an absent one. A truthiness
  # filter dropped it before the usability check ever saw it, so [{"sha256":"X"}, {}]
  # collapsed to the single usable "X" and published a confident attribution over a run with
  # NO established identity — while the evidentially identical [{"sha256":"X"},
  # {"sha256":null}] correctly fell through (#431 delta review).
  RMX8="$EXP/rmixed8"
  mkdir -p "$RMX8/.prflow/learnings"
  cat > "$RMX8/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1047,"merged_at":"2026-07-10T00:00:00Z","branch":"b1047"}
EOF
  seed_eff "$RMX8/.prflow/logs/efficiency" "pr-1047-a.json" "pr-1047" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' '{"sha256":"XXX","partial":false,"salient":{}}'
  seed_eff "$RMX8/.prflow/logs/efficiency" "pr-1047-b.json" "pr-1047" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":20}}}]' '{}'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX8" --prs 1047 >/dev/null 2>&1
  assert_eq "#431 Tmixed: a present-but-FALSY envelope is a corrupt identity, not a silent pass" "no" \
    "$([ "$(exp_field "$RMX8/.prflow/learnings/experiment-records.jsonl" 1047 provenance.config_fingerprint)" = "efficiency-record" ] && echo yes || echo no)"
  assert_eq "#431 Tmixed: no confident attribution over a run with no established identity" "null" \
    "$(exp_field "$RMX8/.prflow/learnings/experiment-records.jsonl" 1047 config_fingerprint)"
  # A NULL fingerprint, by contrast, is the legitimate pre-#431 shape — the run simply
  # stamped none — so it must NOT be treated as corrupt (T1/T5 fixtures rely on this).
  RMX9="$EXP/rmixed9"
  mkdir -p "$RMX9/.prflow/learnings"
  cat > "$RMX9/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1048,"merged_at":"2026-07-10T00:00:00Z","branch":"b1048"}
EOF
  seed_eff "$RMX9/.prflow/logs/efficiency" "pr-1048-a.json" "pr-1048" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMX9" --prs 1048 >/dev/null 2>&1
  assert_eq "#431 Tmixed: a NULL fingerprint is 'stamped none' (pre-#431), never a corrupt identity" "no-sha" \
    "$(exp_field "$RMX9/.prflow/learnings/experiment-records.jsonl" 1048 provenance.config_fingerprint)"

  # A merge-commit config that does not PARSE was retrieved and could not be read — that is
  # `unparseable`, never `absent` (which asserts "we looked and there genuinely was none").
  RMXA="$EXP/rmixedA"
  mkdir -p "$RMXA/.prflow/learnings"
  git init -q "$RMXA" 2>/dev/null
  git -C "$RMXA" config user.email t@t.t; git -C "$RMXA" config user.name t
  printf '{"prflow_review": {,,, BROKEN\n' > "$RMXA/.prflow/config.json"
  git -C "$RMXA" add -A >/dev/null 2>&1
  git -C "$RMXA" commit -qm seed >/dev/null 2>&1
  MXASHA="$(git -C "$RMXA" rev-parse HEAD)"
  cat > "$RMXA/.prflow/learnings/retrospectives.jsonl" <<EOF
{"schema_version":2,"kind":"implementation","pr":1049,"merged_at":"2026-07-10T00:00:00Z","branch":"b1049","merge_commit_sha":"$MXASHA"}
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RMXA" --prs 1049 >/dev/null 2>&1
  assert_eq "#431 Tmixed: a merge-commit config that does not parse is 'unparseable', never 'absent'" \
    "unparseable" "$(exp_field "$RMXA/.prflow/learnings/experiment-records.jsonl" 1049 provenance.config_fingerprint)"

  # ── Tfpfb the merge-commit-config fallback + the byte-identical contract ──────
  # This arm is the whole REASON config_fingerprint.py is a shared module: the reader
  # recomputes the fingerprint from the merge commit's config for records predating the
  # field, and the docstring claims the result is byte-identical to the producer's. That
  # claim was asserted nowhere. Drive the arm against a real git repo and assert the
  # reader's sha256 EQUALS the producer CLI's for the same config — that equality IS the
  # contract (issue #431 review).
  RFP="$EXP/rfp"
  mkdir -p "$RFP/.prflow/learnings"
  git init -q "$RFP" 2>/dev/null
  git -C "$RFP" config user.email t@t.t; git -C "$RFP" config user.name t
  cat > "$RFP/.prflow/config.json" <<'EOF'
{"prflow_review":{"verdict_severity_threshold":"important"},"prflow_review_and_fix":{"max_iterations":5}}
EOF
  git -C "$RFP" add -A >/dev/null 2>&1
  git -C "$RFP" commit -qm seed >/dev/null 2>&1
  FPSHA="$(git -C "$RFP" rev-parse HEAD)"
  cat > "$RFP/.prflow/learnings/retrospectives.jsonl" <<EOF
{"schema_version":2,"kind":"implementation","pr":1050,"merged_at":"2026-07-10T00:00:00Z","branch":"b1050","merge_commit_sha":"$FPSHA"}
EOF
  # An efficiency record with NO fingerprint (the pre-#431 shape) forces the fallback.
  seed_eff "$RFP/.prflow/logs/efficiency" "pr-1050-r.json" "pr-1050" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":10}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RFP" --prs 1050 >/dev/null 2>&1
  STFP="$RFP/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tfpfb: pre-field record → fingerprint recomputed from the merge commit's config" \
    "merge-commit-config" "$(exp_field "$STFP" 1050 provenance.config_fingerprint)"
  # The byte-identical claim: the READER's sha256 == the PRODUCER CLI's for the same file.
  PRODUCER_SHA="$(python3 "$LIB/../scripts/config_fingerprint.py" "$RFP/.prflow/config.json" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["sha256"])')"
  assert_eq "#431 Tfpfb: reader and producer agree byte-for-byte (the shared-module contract)" \
    "$PRODUCER_SHA" "$(exp_field "$STFP" 1050 config_fingerprint.sha256)"

  # ── Timp0 the Important count ZERO case — the modal clean-PR outcome ──────────
  # _count_important distinguishes None (no findings section → unparseable) from 0
  # (section present, no Important group — the engine omits empty groups). Every other
  # fixture has Important items, so the 0 path — what a clean review PR produces — was
  # unpinned. A regression returning None there would convert every clean PR's count from
  # a real 0 into an unparseable null, biasing the primary outcome variable toward
  # "only noisy PRs have counts".
  RI0="$EXP/rimp0"
  mkdir -p "$RI0/.prflow/learnings"
  cat > "$RI0/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1060,"merged_at":"2026-07-10T00:00:00Z","branch":"b1060","head_sha":"h1060","merge_commit_sha":"m1060"}
EOF
  cat > "$EXP/comments1060.json" <<'EOF'
[{"id":11,"created_at":"2026-07-09T10:00:00Z","body":"<!-- devflow:review-progress run=1 -->\n**Reviewed HEAD:** h1060\n\n## Verdict: APPROVE\n\n## Code Review Findings\n\n### 🟡 Suggestion / Minor\n1. a nit\n"}]
EOF
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    COMMENTS_JSON="$EXP/comments1060.json" REVIEWS_JSON="$EXP/does-not-exist" \
    python3 "$BXR" --repo-root "$RI0" --prs 1060 >/dev/null 2>&1
  STI0="$RI0/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Timp0: a findings section with no Important group → a REAL 0, not null" "0" \
    "$(exp_field "$STI0" 1060 important_finding_count)"
  assert_eq "#431 Timp0: the real 0 is sourced, not unparseable" "progress-comment" \
    "$(exp_field "$STI0" 1060 provenance.important_finding_count)"

  # ── Tslug branch-slug sanitization (`/` → `-`) actually resolves the cost rows ──
  # _slug_variants exists to resolve branch-family slugs. Every other fixture's branch is
  # already slug-shaped, so the sanitizing variants never did any work and a broken
  # replace() would ship green — silently vanishing every branch-family cost row (a pure
  # survivorship-bias corruption of the cost side).
  RSL="$EXP/rslug"
  mkdir -p "$RSL/.prflow/learnings"
  cat > "$RSL/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1070,"merged_at":"2026-07-10T00:00:00Z","branch":"feature/x","merge_commit_sha":"m1070"}
EOF
  seed_eff "$RSL/.prflow/logs/efficiency" "feature-x-run.json" "feature-x" "false" \
    '[{"iter":1,"phases":{"phase3":{"tokens":77}}}]' 'null'
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RSL" --prs 1070 >/dev/null 2>&1
  STSL="$RSL/.prflow/learnings/experiment-records.jsonl"
  assert_eq "#431 Tslug: a 'feature/x' branch resolves its sanitized 'feature-x' efficiency slug" "found" \
    "$(exp_field "$STSL" 1070 provenance.efficiency)"
  assert_eq "#431 Tslug: the branch-family cost row actually joined" "77" \
    "$(exp_field "$STSL" 1070 efficiency_runs.0.cost.tokens)"

  # ── Tpartial a PARTIAL assembly failure exits non-zero too ────────────────────
  # The caller's ONLY detection channel is the exit code (retrospective-weekly Step 6.5
  # runs `… || echo "failed" >&2` and turns that into a blocker note). An all-failed-only
  # guard left that check INERT for the dominant shape: 9 of 10 PRs raising still exited
  # 0, so the retrospective reported a clean run while most of the week's records were
  # never assembled (issue #431 review — a guard whose comparand the producer never emits
  # on the paths it now selects is a guard that fails open).
  RPT="$EXP/rpartial"
  mkdir -p "$RPT/.prflow/learnings"
  : > "$RPT/.prflow/learnings/retrospectives.jsonl"
  python3 - "$BXR" "$RPT" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)
real = ber.build_record
# PR 2001 assembles; PR 2002 raises. A PARTIAL failure.
def flaky(repo, root, idx, pr, retro):
    if pr == 2002:
        raise RuntimeError("boom")
    return {"schema_version": 1, "pr": pr, "provenance": {"notes": []}}
ber.build_record = flaky
sys.argv = ["ber", "--repo-root", sys.argv[2], "--prs", "2001,2002"]
rc = ber.main()
sys.exit(0 if rc == 2 else 1)
PY
  # Capture rc immediately (same footgun Tcoh documents — any command inserted between the
  # heredoc and the expansion would silently rewire `$?` and pass unconditionally).
  RC_PART=$?
  assert_eq "#431 Tpartial: a partial assembly failure exits 2 (not a silent success)" "0" "$RC_PART"
  assert_eq "#431 Tpartial: the PR that DID assemble is still written (prior lines preserved)" "1" \
    "$(exp_count_lines "$RPT/.prflow/learnings/experiment-records.jsonl")"

  # ── Tfail whole-batch assembly failure exits non-zero (review Fix D) ─────────
  # If EVERY candidate raises, the batch must NOT report success (exit 0) — a
  # systematic failure has to be loud so a best-effort caller surfaces it.
  RFAIL="$EXP/rfail"
  mkdir -p "$RFAIL/.prflow/learnings"
  : > "$RFAIL/.prflow/learnings/retrospectives.jsonl"
  python3 - "$BXR" "$RFAIL" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)
ber.build_record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
sys.argv = ["ber", "--repo-root", sys.argv[2], "--prs", "999"]
rc = ber.main()
sys.exit(0 if rc == 2 else 1)
PY
  assert_eq "#431 Tfail: all-candidates-failed batch exits non-zero (2), not a silent success" "yes" \
    "$([ $? -eq 0 ] && echo yes || echo no)"

  # ── T1826 per-iteration pass-through + superseded-branch detection (issue #1826) ──
  # j1826.py drives _efficiency_entry directly (the unit boundary) so the join half is
  # asserted per-AC without a gh stub. The producer's full per_iteration key set (from
  # lib/efficiency-trace.jq) is the fixture, so a dropped key is a visible failure.
  cat > "$EXP/j1826.py" <<'PY'
import copy, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
ber = importlib.util.module_from_spec(spec); spec.loader.exec_module(ber)
ef = ber._efficiency_entry
# The producer's per_iteration object (lib/efficiency-trace.jq record mode) — full key set.
SRC = [
    {"iter": 1, "loop_role": "detect", "synthesized": False, "phase3_dispatched": ["code-reviewer"],
     "phase3_dispatched_count": 1, "phase3_dispatched_present": True, "dispatched_effort_present": True,
     "agent_effort": {"code-reviewer": "high"}, "diff_profile": "engine_self_modifying",
     "verification_posture": "full", "checklist_lite_count": 2, "checklist_agent_count": 1,
     "fixes_applied": 0, "added_nothing": True, "agent_verdicts": {"code-reviewer": "applied-important"}},
    {"iter": 2, "loop_role": "fix", "synthesized": False, "phase3_dispatched": [],
     "phase3_dispatched_count": 0, "phase3_dispatched_present": True, "dispatched_effort_present": False,
     "agent_effort": {}, "diff_profile": None, "verification_posture": "narrow",
     "checklist_lite_count": 0, "checklist_agent_count": 0, "fixes_applied": 1, "added_nothing": False,
     "agent_verdicts": {}},
]
check = sys.argv[2]
if check == "verbatim":
    print("yes" if ef({"slug": "s", "per_iteration": SRC}, None)["per_iteration"] == SRC else "no")
elif check == "keyset":
    e = ef({"slug": "s", "per_iteration": SRC}, None)["per_iteration"]
    print("yes" if len(e) == len(SRC) and all(set(o) == set(s) for o, s in zip(e, SRC)) else "no")
elif check == "cut":
    print(json.dumps(ef({"slug": "s", "cut_candidate_min_dispatch": 4}, None)["cut_candidate_min_dispatch"]))
elif check == "cut-missing":
    print(json.dumps(ef({"slug": "s"}, None)["cut_candidate_min_dispatch"]))
elif check == "empty":
    print(json.dumps(ef({"slug": "s", "per_iteration": []}, None)["per_iteration"]))
elif check == "missing":
    print(json.dumps(ef({"slug": "s"}, None)["per_iteration"]))
elif check == "fieldloss":
    # The guard is deep-equality of the joined array to the source. Prove it PASSES on the
    # shipped join AND FIRES when ANY single per-iteration key is dropped (a non-vacuous guard).
    e = ef({"slug": "s", "per_iteration": SRC}, None)["per_iteration"]
    if e != SRC:
        print("no"); sys.exit(0)
    fires = True
    for k in list(SRC[0]):
        mut = copy.deepcopy(e); del mut[0][k]
        if mut == SRC:  # dropping k must break the equality the guard checks
            fires = False
    print("yes" if fires else "no")
elif check == "adversarial":
    # Every off-contract shape yields a defined list and no traceback (one bad record must
    # not detonate the whole store rewrite). object/scalar/false/missing -> []; a list is
    # carried verbatim whatever its members.
    ok = True
    for c in ({"a": 1}, 5, False, [1, 2], [{"iter": 1}]):
        try:
            v = ef({"slug": "s", "per_iteration": c}, None)["per_iteration"]
            if not isinstance(v, list):
                ok = False
        except Exception:
            ok = False
    for bad in ({"a": 1}, 5, False):
        if ef({"slug": "s", "per_iteration": bad}, None)["per_iteration"] != []:
            ok = False
    print("yes" if ok else "no")
elif check == "realshape":
    # A real-world per_iteration object whose checklist_skipped carries a value outside its
    # documented vocabulary is carried through UNCHANGED (the pass-through claims no cleanup).
    src = [{"iter": 1, "checklist_skipped": "budget-truncated-inline-review",
            "agent_verdicts": {"code-reviewer": "applied-important"}}]
    print("yes" if ef({"slug": "s", "per_iteration": src}, None)["per_iteration"] == src else "no")
PY
  assert_eq "#1826 AC1: per_iteration carried through the join VERBATIM" "yes" "$(python3 "$EXP/j1826.py" "$BXR" verbatim)"
  assert_eq "#1826 AC1: each per_iteration object keeps the source key set" "yes" "$(python3 "$EXP/j1826.py" "$BXR" keyset)"
  assert_eq "#1826 AC2: cut_candidate_min_dispatch carried through" "4" "$(python3 "$EXP/j1826.py" "$BXR" cut)"
  assert_eq "#1826 AC2: cut_candidate_min_dispatch absent -> null" "null" "$(python3 "$EXP/j1826.py" "$BXR" cut-missing)"
  assert_eq "#1826 AC3: empty per_iteration -> empty array" "[]" "$(python3 "$EXP/j1826.py" "$BXR" empty)"
  assert_eq "#1826 AC3: missing per_iteration key -> empty array" "[]" "$(python3 "$EXP/j1826.py" "$BXR" missing)"
  assert_eq "#1826 AC4: field-loss guard passes shipped + fires on ANY dropped key" "yes" "$(python3 "$EXP/j1826.py" "$BXR" fieldloss)"
  assert_eq "#1826 join: adversarial per_iteration shapes yield [] / verbatim, never a traceback" "yes" "$(python3 "$EXP/j1826.py" "$BXR" adversarial)"
  assert_eq "#1826 join: a real out-of-vocabulary per_iteration value is carried unchanged" "yes" "$(python3 "$EXP/j1826.py" "$BXR" realshape)"

  # ── T1826 integration: per_iteration + cut reach the store; other lines stay stable ──
  RJ="$EXP/rjoin"
  mkdir -p "$RJ/.prflow/learnings" "$RJ/.prflow/logs/efficiency"
  cat > "$RJ/.prflow/learnings/retrospectives.jsonl" <<'EOF'
{"schema_version":2,"kind":"implementation","pr":1826,"issue":1825,"merged_at":"2026-08-01T00:00:00Z","branch":"issue-1826-x","head_sha":"h1826","merge_commit_sha":"m1826"}
{"schema_version":2,"kind":"implementation","pr":1820,"issue":1819,"merged_at":"2026-07-30T00:00:00Z","branch":"issue-1820-x","head_sha":"h1820","merge_commit_sha":"m1820"}
EOF
  cat > "$RJ/.prflow/logs/efficiency/pr-1826-run1.json" <<'EOF'
{"schema_version":1,"slug":"pr-1826","synthesized":false,"iterations":2,"config_fingerprint":null,"cut_candidate_min_dispatch":3,"telemetry":[{"iter":1,"phases":{"p3":{"tokens":10}}}],"per_iteration":[{"iter":1,"diff_profile":"engine_self_modifying","agent_verdicts":{"code-reviewer":"applied-important"}},{"iter":2,"diff_profile":null,"agent_verdicts":{}}]}
EOF
  cat > "$RJ/.prflow/logs/efficiency/pr-1820-run1.json" <<'EOF'
{"schema_version":1,"slug":"pr-1820","synthesized":false,"iterations":1,"config_fingerprint":null,"cut_candidate_min_dispatch":null,"telemetry":[{"iter":1,"phases":{"p3":{"tokens":5}}}],"per_iteration":[]}
EOF
  STJ="$RJ/.prflow/learnings/experiment-records.jsonl"
  # First assemble both PRs, then simulate an "old" store whose 1820 line has NO per_iteration
  # in its efficiency_runs entry (re-canonicalized so a carried-verbatim rewrite is byte-equal).
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RJ" --prs 1826,1820 >/dev/null 2>&1
  assert_eq "#1826 AC1(int): per_iteration reaches the store entry" "yes" \
    "$([ "$(exp_field "$STJ" 1826 efficiency_runs.0.per_iteration.0.diff_profile)" = "engine_self_modifying" ] && echo yes || echo no)"
  assert_eq "#1826 AC2(int): cut_candidate_min_dispatch reaches the store entry" "3" \
    "$(exp_field "$STJ" 1826 efficiency_runs.0.cut_candidate_min_dispatch)"
  python3 - "$STJ" <<'PY'
import json, sys
p = sys.argv[1]
lines = [json.loads(l) for l in open(p) if l.strip()]
out = []
for rec in lines:
    if rec.get("pr") == 1820:
        for e in rec.get("efficiency_runs", []):
            e.pop("per_iteration", None)
    out.append(json.dumps(rec, sort_keys=True, separators=(",", ":")))
open(p, "w").write("\n".join(out) + "\n")
PY
  BEFORE1820="$(python3 "$EXP/get.py" "$STJ" 1820 "")"
  # Reprocess ONLY 1826; 1820 is already stored (not a candidate) so its line must not change.
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RJ" --prs 1826 >/dev/null 2>&1
  assert_eq "#1826 AC5: a stored line with no per_iteration data is left byte-identical" "yes" \
    "$([ "$BEFORE1820" = "$(python3 "$EXP/get.py" "$STJ" 1820 "")" ] && echo yes || echo no)"
  WHOLE_AFTER="$(cat "$STJ")"
  # AC6 idempotence: run again over the same inputs; the second run is byte-identical.
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RJ" --prs 1826 >/dev/null 2>&1
  assert_eq "#1826 AC6: a second assembler run is byte-identical to the first" "yes" \
    "$([ "$WHOLE_AFTER" = "$(cat "$STJ")" ] && echo yes || echo no)"

  # ── T1826 reader half: superseded-branch detection over real git orphan branches ──
  # Build a git repo, add telemetry records as orphan-branch commits (divergent by
  # construction — orphans share no ancestor), and read the assembler's stderr warning.
  mk_git_repo() {
    local repo="$1"
    mkdir -p "$repo/.prflow/learnings"
    printf '%s\n' '{"schema_version":2,"kind":"implementation","pr":1899,"issue":1898,"merged_at":"2026-08-01T00:00:00Z","branch":"b","head_sha":"h","merge_commit_sha":"m"}' \
      > "$repo/.prflow/learnings/retrospectives.jsonl"
    git -C "$repo" init -q
    git -C "$repo" config user.email t@e; git -C "$repo" config user.name t
    git -C "$repo" add -A; git -C "$repo" commit -qm init
    git -C "$repo" branch -M main
  }
  # $1 repo $2 branch $3 path-prefix $4.. record filenames (each seeded as a tiny record)
  seed_branch() {
    local repo="$1" branch="$2" prefix="$3"; shift 3
    git -C "$repo" checkout -q --orphan "$branch"
    git -C "$repo" rm -rqf --cached . >/dev/null 2>&1 || true
    find "$repo" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    mkdir -p "$repo/$prefix"
    local f
    for f in "$@"; do printf '{"schema_version":1,"slug":"%s"}\n' "${f%.json}" > "$repo/$prefix/$f"; done
    git -C "$repo" add -A; git -C "$repo" commit -qm "$branch"
    git -C "$repo" checkout -qf main
  }

  # Fixture: two divergent refs present; the superseded ref holds 2 records under
  # .devflow/ and a DECOY under .prflow/ (which the check must NOT count).
  RBP="$EXP/rbp"; mk_git_repo "$RBP"
  seed_branch "$RBP" prflow-telemetry .prflow/logs/efficiency canon-1.json
  seed_branch "$RBP" devflow-telemetry .devflow/logs/efficiency old-1.json old-2.json
  git -C "$RBP" checkout -q devflow-telemetry
  mkdir -p "$RBP/.prflow/logs/efficiency"; printf '{"slug":"decoy"}\n' > "$RBP/.prflow/logs/efficiency/decoy.json"
  git -C "$RBP" add -A; git -C "$RBP" commit -qm decoy; git -C "$RBP" checkout -qf main
  SUP_BEFORE="$(git -C "$RBP" rev-parse devflow-telemetry)"
  CANON_BEFORE="$(git -C "$RBP" rev-parse prflow-telemetry)"
  ERRBP="$EXP/errbp"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RBP" --prs 1899 2>"$ERRBP" >/dev/null
  assert_eq "#1826 AC9/AC11: both-present report names the superseded branch + its .devflow/ record count (decoy under .prflow/ ignored)" "yes" \
    "$(grep -q 'devflow-telemetry' "$ERRBP" && grep -q '2 efficiency records under .devflow/logs/efficiency/' "$ERRBP" && echo yes || echo no)"
  assert_eq "#1826 AC12: the both-present remedy is divergent-safe (copy across, never force-push the superseded ref onto the canonical one)" "yes" \
    "$(grep -qi 'Do NOT force-push' "$ERRBP" && grep -q 'copy the record files' "$ERRBP" && echo yes || echo no)"
  assert_eq "#1826 AC14: detection mutates no ref (superseded tip unchanged)" "$SUP_BEFORE" "$(git -C "$RBP" rev-parse devflow-telemetry)"
  assert_eq "#1826 AC14: detection mutates no ref (canonical tip unchanged)" "$CANON_BEFORE" "$(git -C "$RBP" rev-parse prflow-telemetry)"
  # AC14: the superseded records are NOT unioned into the index — the canonical branch has
  # exactly one record, so a run that ingested the superseded branch too would over-count.
  assert_eq "#1826 AC14: records ingested from exactly one branch (superseded not unioned)" "1" \
    "$(git -C "$RBP" ls-tree -r --name-only prflow-telemetry -- .prflow/logs/efficiency/ | grep -c '\.json$')"

  # Absent-canonical fixture: the superseded ref exists with the canonical one absent —
  # the pre-#1826 report keeps firing, now with the count and the fast-forward rename remedy.
  RAC="$EXP/rac"; mk_git_repo "$RAC"
  seed_branch "$RAC" devflow-telemetry .devflow/logs/efficiency a.json b.json c.json
  ERRAC="$EXP/errac"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RAC" --prs 1899 2>"$ERRAC" >/dev/null
  assert_eq "#1826 AC10: absent-canonical report still fires and names the count" "yes" \
    "$(grep -q '3 efficiency records under .devflow/logs/efficiency/' "$ERRAC" && echo yes || echo no)"
  assert_eq "#1826 AC10: absent-canonical remedy is the fast-forward rename push" "yes" \
    "$(grep -q 'git push origin devflow-telemetry:prflow-telemetry' "$ERRAC" && echo yes || echo no)"

  # Superseded absent: no report at all (output unchanged from today's).
  RSA="$EXP/rsa"; mk_git_repo "$RSA"
  seed_branch "$RSA" prflow-telemetry .prflow/logs/efficiency only.json
  ERRSA="$EXP/errsa"
  GITHUB_REPOSITORY=owner/repo DEVFLOW_GH="$EXP/gh" \
    python3 "$BXR" --repo-root "$RSA" --prs 1899 2>"$ERRSA" >/dev/null
  assert_eq "#1826 AC13: with the superseded branch absent, no stranded-record report is emitted" "yes" \
    "$(grep -qi 'devflow-telemetry' "$ERRSA" && echo no || echo yes)"

  # Fail-closed arm: the superseded ref is present but its tree cannot be read. The count must
  # WARN and return None (unestablished) — never a fabricated 0 that suppresses a real report.
  # Driven by monkeypatching _run (rev-parse present, ls-tree fails) since a genuinely corrupt
  # tree is impractical to fixture.
  python3 - "$BXR" <<'PY'
import contextlib, importlib.util, io, sys
spec = importlib.util.spec_from_file_location("ber", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def fake_run(cmd):
    if "ls-tree" in cmd:
        return 128, "", "fatal: not a tree object"
    return 0, "", ""  # rev-parse --verify --quiet -> superseded ref present
m._run = fake_run
err = io.StringIO()
with contextlib.redirect_stderr(err):
    result = m._count_superseded_efficiency("/nonexistent")
ok = (result is None
      and "could not be read" in err.getvalue()
      and "cannot establish how many records are stranded" in err.getvalue())
sys.exit(0 if ok else 1)
PY
  assert_eq "#1826: unreadable superseded tree warns + returns None (never a fabricated zero)" "yes" \
    "$([ $? -eq 0 ] && echo yes || echo no)"

  rm -rf "$EXP"
fi

# ── #431 config_fingerprint.py — direct unit coverage (partial fingerprint) ────
# The shared canonicalization module (SPDX, pure logic) had no direct test; the
# "partial fingerprint" edge the issue names lived only behind pre-baked fixtures.
CFP="$LIB/../scripts/config_fingerprint.py"
if [ -f "$CFP" ]; then
  cfp_check() { python3 - "$CFP" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("cfp", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
f = m.fingerprint_from_config
both = f({"prflow_review": {"a": 1}, "prflow_review_and_fix": {"max_iterations": 5}})
one = f({"prflow_review": {"a": 1}})
none = f({"unrelated": 1})
# order-independent canonicalization
a = f({"prflow_review": {"a": 1, "b": 2}, "prflow_review_and_fix": {"m": 3}})
b = f({"prflow_review_and_fix": {"m": 3}, "prflow_review": {"b": 2, "a": 1}})
# salient extraction lifts the named keys verbatim (the field an operator reads).
sal = f({"prflow_review_and_fix": {"max_iterations": 5, "unrelated": 9}})
ok = (
    both is not None and both["partial"] is False and
    one is not None and one["partial"] is True and
    none is None and
    a["sha256"] == b["sha256"] and
    both["sha256"] != one["sha256"] and
    sal["salient"] == {"max_iterations": 5}
)
sys.exit(0 if ok else 1)
PY
  }
  cfp_check
  assert_eq "#431 config_fingerprint: partial flag / None arm / canonical hash" "yes" \
    "$([ $? -eq 0 ] && echo yes || echo no)"
fi

# ── #2006 run_profile passthrough and PR-less exclusion ───────────────────────
# The join carries the run-profile floor's object through verbatim, reads an absent key
# as JSON null (a pre-change record), and keeps a PR-less implement record out of every
# PR's run list. That exclusion is keyed on `no_pr_reason` rather than the `issue-<N>`
# slug: `target_slugs` includes branch-name variants, so a branch literally named
# `issue-<N>` would make a name-based guard admit the record as one of that PR's runs.
if [ -f "$BXR" ]; then
  rp_check() { python3 - "$BXR" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bxr", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

pre = m._efficiency_entry({"slug": "pr-1"}, "r1")
profile = {"phase_durations_ms": {"Setup": 1000, "Review": "unestablished"},
           "final_status": "Complete", "prior_record_count": 0,
           "engine_outcome": "success"}
post = m._efficiency_entry({"slug": "pr-2", "run_profile": profile}, "r2")
prless = m._efficiency_entry(
    {"slug": "issue-9", "no_pr_reason": "no-closing-pr-found"}, "r3")
index = {"pr-2": [post], "issue-9": [prless]}
ok = (
    pre["run_profile"] is None and
    pre["no_pr_reason"] is None and
    post["run_profile"] == profile and
    post["run_profile"]["phase_durations_ms"]["Review"] == "unestablished" and
    prless["no_pr_reason"] == "no-closing-pr-found" and
    [r["slug"] for r in m._collect_efficiency(index, {"pr-2"})] == ["pr-2"] and
    m._collect_efficiency(index, {"issue-9"}) == []
)
sys.exit(0 if ok else 1)
PY
  }
  rp_check
  assert_eq "#2006 join: run_profile passes through verbatim, an absent key is null, and a PR-less record joins no PR" "yes" \
    "$([ $? -eq 0 ] && echo yes || echo no)"
fi

# A store mixing pre-change and post-change lines must not make actionable-patterns.sh
# emit a warning it does not emit on a store of pre-change lines alone — the additive
# fields are invisible to every one of its four warning conditions.
#
# Drive the script the way its own usage states — $1 retrospectives.jsonl, $2
# overrides.json, $3 optional --full — and place experiment-records.jsonl BESIDE the
# retrospectives file, which is where the script derives it from. An EXPERIMENTS_FILE
# passed through the environment is overwritten by that derivation, and passing --full as
# $1 makes both invocations fail identically, so a comparison built either way compares
# two failures and can never go red.
AP_SH="$LIB/actionable-patterns.sh"
if [ -f "$AP_SH" ]; then
  ER_PRE_LINE='{"schema_version":1,"pr":1,"issue":11,"branch":"b1","merged_at":"2026-07-01T00:00:00Z","verdict":"APPROVE","config_fingerprint":null,"efficiency_runs":[{"slug":"pr-1","run_id":"r1","cost":{"calls":1,"tokens":10,"wall_clock_s":1},"iterations":1}],"retrospective":null,"important_finding_count":0,"permission_denials_count":0,"provenance":{}}'
  ER_POST_LINE='{"schema_version":1,"pr":2,"issue":12,"branch":"b2","merged_at":"2026-07-02T00:00:00Z","verdict":"APPROVE","config_fingerprint":null,"efficiency_runs":[{"slug":"pr-2","run_id":"r2","cost":{"calls":1,"tokens":10,"wall_clock_s":1},"iterations":1,"run_profile":{"phase_durations_ms":{"Setup":1000},"final_status":"Complete","prior_record_count":0,"issue_number":12,"engine_outcome":"success"},"no_pr_reason":null}]}'
  ER_RETRO_LINE='{"pr":1,"issue":11,"branch":"b1","merged_at":"2026-07-01T00:00:00Z","verdict":"APPROVE","findings":[{"tag":"convention-violation","summary":"s"}]}'
  # actionable-patterns.sh looks up open issues for the cooldown check. That shells to
  # gh, which succeeds on an authenticated desk and fails on CI — aborting the script
  # under its `set -euo pipefail` and making BOTH compared runs fail identically, which
  # is precisely the vacuity the positive controls below exist to catch. Stub gh through
  # the documented DEVFLOW_GH override so the comparison is host-independent.
  ER_AP_GH="$(mktemp -d)/gh"
  printf '#!/usr/bin/env bash\nprintf %%s "[]"\n' > "$ER_AP_GH"
  chmod +x "$ER_AP_GH"

  er_ap_warnings() {
    # $1 = the experiment-records.jsonl content. Returns the ::warning:: count.
    local d
    d="$(mktemp -d)"
    printf '%s\n' "$ER_RETRO_LINE" > "$d/retrospectives.jsonl"
    printf '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$d/overrides.json"
    printf '%s' "$1" > "$d/experiment-records.jsonl"
    DEVFLOW_GH="$ER_AP_GH" GITHUB_REPOSITORY=owner/repo \
      bash "$AP_SH" "$d/retrospectives.jsonl" "$d/overrides.json" --full 2>&1 >/dev/null \
      | grep -c '::warning::actionable-patterns' || true
    rm -rf "$d"
  }
  ER_PRE_CONTENT="$ER_PRE_LINE
"
  ER_MIX_CONTENT="$ER_PRE_LINE
$ER_POST_LINE
"
  ER_W_PRE="$(er_ap_warnings "$ER_PRE_CONTENT")"
  ER_W_MIX="$(er_ap_warnings "$ER_MIX_CONTENT")"
  # Echo the script's EXIT STATUS over fixture $1. The control needs evidence the run
  # HAPPENED; asserting its stdout parses as a JSON array instead made the control
  # platform-dependent — it held on macOS and went RED on CI's Ubuntu, where this
  # no-patterns fixture prints nothing rather than an empty array.
  er_ap_rc() {
    local d rc=0
    d="$(mktemp -d)"
    printf '%s\n' "$ER_RETRO_LINE" > "$d/retrospectives.jsonl"
    printf '{"schema_version":3,"patterns":{},"dismissed":{}}' > "$d/overrides.json"
    printf '%s' "$1" > "$d/experiment-records.jsonl"
    DEVFLOW_GH="$ER_AP_GH" GITHUB_REPOSITORY=owner/repo \
      bash "$AP_SH" "$d/retrospectives.jsonl" "$d/overrides.json" --full >/dev/null 2>&1 || rc=$?
    rm -rf "$d"
    printf '%s' "$rc"
  }
  # Positive control: the fixture is otherwise valid and the script RUNS over it, emitting
  # its pattern array. Without this an equal warning count below could be two identical
  # failures agreeing rather than two real runs agreeing.
  assert_eq "#2006 mixed store: the pre-change fixture drives actionable-patterns.sh to a real run (positive control)" "0" \
    "$(er_ap_rc "$ER_PRE_CONTENT")"
  assert_eq "#2006 mixed store: the mixed fixture drives it to a real run too (positive control)" "0" \
    "$(er_ap_rc "$ER_MIX_CONTENT")"
  assert_eq "#2006 mixed store: actionable-patterns.sh emits no warning it does not emit on a pre-change store" \
    "$ER_W_PRE" "$ER_W_MIX"
  # And the corrupt-store arm still warns — proving the counter can go non-zero, so the
  # equality above is not passing merely because nothing is ever counted.
  assert_eq "#2006 mixed store: a corrupt store DOES warn (the counter is not inert)" "yes" \
    "$(test "$(er_ap_warnings 'not json at all
')" -gt 0 && echo yes || echo no)"
fi

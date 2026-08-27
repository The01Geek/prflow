# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable module for the review-evidence gate (issue #2075): the workflow-side
# gate script scripts/review-evidence-gate.py, driven by the focused python test
# lib/test/review_evidence_gate_test.py, and the new --evidence-gate-fail arm of
# scripts/flip-review-progress-failed.sh.
#
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module (the same contract
# review-trigger-helpers.sh documents). No private fixture root / EXIT trap here —
# the sections below allocate and remove their own scratch trees on their own clean
# paths, exactly as the extracted trigger-helper sections do.

# ────────────────────────────────────────────────────────────────────────────
echo "review-evidence-gate.py (#2075 — the whole gate decision, driven end to end)"
# ────────────────────────────────────────────────────────────────────────────
# One focused-python assertion runs the gate's unit + git-sandbox arm suite
# (classification reuse, the malformed-log matrix, and every pass/fail/
# unestablished/no-verdict arm). Its own output is echoed on failure.
REG_PY_OUT="$(mktemp)"
devflow_run_focused_python_test \
  "#2075 review-evidence-gate.py arm suite passes" \
  "$LIB/test/review_evidence_gate_test.py" "$REG_PY_OUT"
rm -f "$REG_PY_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "flip-review-progress-failed.sh --evidence-gate-fail (#2075 evidence-gate arm)"
# ────────────────────────────────────────────────────────────────────────────
# The dead-run backstop flips ONLY an interim (🚀) Status; the evidence-gate arm
# overrides that guard to rewrite a TERMINAL verdict comment to '❌ Review failed'
# when its posted verdict lacks phase-execution evidence. Driven against the same
# stubbed-gh + copied-workpad idiom the #1154 section uses.
REG_ROOT="$(mktemp -d)"
mkdir -p "$REG_ROOT/scripts" "$REG_ROOT/state"
cp "$LIB/../scripts/flip-review-progress-failed.sh" "$REG_ROOT/scripts/"
cp "$LIB/../scripts/workpad.py" "$REG_ROOT/scripts/"
REG_FLIP="$REG_ROOT/scripts/flip-review-progress-failed.sh"
REG_STATE="$REG_ROOT/state"
REG_MARK='<!-- prflow:review-progress run=REG2075-1 -->'
cat > "$REG_ROOT/gh" <<'STUB'
#!/usr/bin/env bash
j="$*"
if [[ "$j" == *"repo view"* ]]; then echo "owner/repo"; exit 0; fi
if [[ "$j" == *"-X PATCH"* ]]; then
  for a in "$@"; do
    case "$a" in body=@*) cp "${a#body=@}" "$REG_STATE/patched-body" ;; esac
  done
  echo p >> "$REG_STATE/patchlog"
  exit 0
fi
if [[ "$j" == *"issue comment"* ]]; then
  echo c >> "$REG_STATE/createlog"
  echo "https://github.com/owner/repo/pull/55#issuecomment-9090"
  exit 0
fi
if [[ "$j" == *"issues/comments/"* ]]; then cat "$REG_STATE/body"; exit 0; fi
if [[ "$j" == *"/comments"* ]]; then cat "$REG_STATE/comments.json"; exit 0; fi
echo '[]'
STUB
chmod +x "$REG_ROOT/gh"

# Seed the stub's world with a single comment (id 7) carrying BODYFILE's contents.
reg_seed() {  # <body-file>
  : > "$REG_STATE/patchlog"; : > "$REG_STATE/createlog"
  rm -f "$REG_STATE/patched-body"
  cp "$1" "$REG_STATE/body"
  python3 - "$1" "$REG_STATE/comments.json" <<'PY'
import json, sys
body = open(sys.argv[1], encoding="utf-8").read()
json.dump([{"id": 7, "body": body}], open(sys.argv[2], "w", encoding="utf-8"))
PY
}
# Trailing KEY=VALUE / flag args are passed to the flip helper positionally.
reg_run() {  # <pr> <marker> <cause> [4th-arg] -> stderr to state/err, prints rc
  local pr="$1" mark="$2" cause="$3" rc=0
  shift 3
  ( cd "$REG_ROOT" \
    && env DEVFLOW_GH="$REG_ROOT/gh" REG_STATE="$REG_STATE" \
           GITHUB_SERVER_URL=https://github.com GITHUB_REPOSITORY=owner/repo GITHUB_RUN_ID=2075 \
           bash "$REG_FLIP" "$pr" "$mark" "$cause" "$@" \
       >/dev/null 2>"$REG_STATE/err" ) || rc=$?
  echo "$rc"
}
reg_patches() { grep -c . "$REG_STATE/patchlog" 2>/dev/null || true; }

# A terminal (non-🚀) verdict comment: an APPROVE the run already wrote.
printf '%s\n' "$REG_MARK" '# PRFlow Review — PR #55' '' '**Status:** ✅ APPROVE' \
  > "$REG_ROOT/terminal.md"
# An interim comment, for the default-arm control.
printf '%s\n' "$REG_MARK" '# PRFlow Review — PR #55' '' '**Status:** 🚀 Reviewing' \
  > "$REG_ROOT/interim.md"

# Default arm (no 4th arg): a terminal verdict comment is LEFT UNTOUCHED.
reg_seed "$REG_ROOT/terminal.md"
assert_eq "#2075 flip: a terminal comment WITHOUT the flag exits 0" "0" \
  "$(reg_run 55 "$REG_MARK" 'hollow verdict')"
assert_eq "#2075 flip: a terminal comment WITHOUT the flag writes nothing (interim-only guard holds)" "0" \
  "$(reg_patches)"

# Evidence-gate arm: the same terminal comment IS rewritten to '❌ Review failed'.
reg_seed "$REG_ROOT/terminal.md"
assert_eq "#2075 flip: --evidence-gate-fail exits 0" "0" \
  "$(reg_run 55 "$REG_MARK" 'no phase-execution evidence' --evidence-gate-fail)"
assert_eq "#2075 flip: --evidence-gate-fail PATCHes the terminal comment exactly once" "1" \
  "$(reg_patches)"
assert_eq "#2075 flip: --evidence-gate-fail rewrites the Status to the failed state" "yes" \
  "$(grep -qF '**Status:** ❌ Review failed' "$REG_STATE/patched-body" && echo yes || echo no)"
assert_eq "#2075 flip: --evidence-gate-fail names the evidence-gate arm in its breadcrumb" "yes" \
  "$(grep -qF 'evidence-gate arm' "$REG_STATE/err" && echo yes || echo no)"

# Control: the default arm still flips an INTERIM comment (unchanged behavior).
reg_seed "$REG_ROOT/interim.md"
assert_eq "#2075 flip: an interim comment still flips under the default arm" "yes" \
  "$(reg_run 55 "$REG_MARK" 'job died' >/dev/null; grep -qF '**Status:** ❌ Review failed' "$REG_STATE/patched-body" && echo yes || echo no)"

# An unrecognized 4th argument is refused as a no-op (a typo cannot take a wrong arm).
reg_seed "$REG_ROOT/terminal.md"
assert_eq "#2075 flip: an unrecognized 4th argument exits 0" "0" \
  "$(reg_run 55 "$REG_MARK" 'x' --bogus-flag)"
assert_eq "#2075 flip: an unrecognized 4th argument writes nothing and names itself" "yes" \
  "$([ "$(reg_patches)" = 0 ] && grep -qF 'unrecognized 4th argument' "$REG_STATE/err" && echo yes || echo no)"

# Convergence: re-running the evidence-gate arm over a comment already carrying the
# terminal failed Status must not compound it — the second pass leaves the Status the
# same failed state, so a re-attempted or retried gate step cannot corrupt the record.
printf '%s\n' "$REG_MARK" '# PRFlow Review — PR #55' '' '**Status:** ❌ Review failed' \
  > "$REG_ROOT/failed.md"
reg_seed "$REG_ROOT/failed.md"
assert_eq "#2075 flip: --evidence-gate-fail over an already-failed comment exits 0" "0" \
  "$(reg_run 55 "$REG_MARK" 'no phase-execution evidence' --evidence-gate-fail)"
assert_eq "#2075 flip: --evidence-gate-fail re-run converges on one failed Status line" "1" \
  "$(grep -c '^\*\*Status:\*\* ❌ Review failed' "$REG_STATE/patched-body" 2>/dev/null || echo 0)"

rm -rf "$REG_ROOT"

# ────────────────────────────────────────────────────────────────────────────
echo "devflow.yml 'Review evidence gate' step shell (#2075 — the dismissal state-gate)"
# ────────────────────────────────────────────────────────────────────────────
# The step's fail arm decides, from the gate token alone, whether to dismiss the
# unbacked review: only a merge-gating state (APPROVED / CHANGES_REQUESTED) with a
# parsed review_id is dismissed, and a COMMENTED verdict is left to the durable
# comment. Nothing else exercises that shell, so a regression inverting the RSTATE
# gate — or mis-parsing review_id — would dismiss a human's live change-request, or
# silently leave an unbacked APPROVE standing.
RGS_ROOT="$(mktemp -d)"
# Slice the step's `run:` body out of the workflow and dedent it to a runnable script.
awk '
  index($0, "- name: Review evidence gate") { grab=1; next }
  grab && /^      - name: / { exit }
  grab && /^        run: \|/ { body=1; next }
  body && /^      [^ ]/ { exit }
  body { sub(/^          /, ""); print }
' "$LIB/../.github/workflows/devflow.yml" > "$RGS_ROOT/step.sh"
assert_eq "#2075 step: the 'Review evidence gate' run body was extracted" "yes" \
  "$([ -s "$RGS_ROOT/step.sh" ] && grep -qF 'review-evidence-gate:' "$RGS_ROOT/step.sh" && echo yes || echo no)"

# A sandbox holding every path the step probes, plus recording stubs on PATH.
rgs_sandbox() {  # $1 = the gate token line the stubbed gate script emits
  rm -rf "${RGS_ROOT:?}/wt" "${RGS_ROOT:?}/bin"
  mkdir -p "$RGS_ROOT/wt/.prflow/tmp" "$RGS_ROOT/wt/scripts" "$RGS_ROOT/bin" "$RGS_ROOT/tmp"
  : > "$RGS_ROOT/wt/.prflow/tmp/pre-inventory.json"
  : > "$RGS_ROOT/wt/scripts/review-evidence-gate.py"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$RGS_ROOT/wt/scripts/flip-review-progress-failed.sh"
  printf '%s\n' "$1" > "$RGS_ROOT/token"
  : > "$RGS_ROOT/ghlog"
  # python3 stub: stands in for the gate script, echoing the canned verdict + detail.
  printf '%s\n' '#!/usr/bin/env bash' 'cat "$RGS_ROOT/token"; echo "human detail line"' \
    > "$RGS_ROOT/bin/python3"
  # gh stub: records every invocation; the base-ref read returns a ref, writes succeed.
  printf '%s\n' '#!/usr/bin/env bash' 'echo "gh $*" >> "$RGS_ROOT/ghlog"' \
    'case "$*" in *"--jq .base.ref"*) echo main ;; esac' 'exit 0' > "$RGS_ROOT/bin/gh"
  printf '%s\n' '#!/usr/bin/env bash' 'echo "{}"' > "$RGS_ROOT/bin/jq"
  printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$RGS_ROOT/bin/git"
  chmod +x "$RGS_ROOT/bin/"* "$RGS_ROOT/wt/scripts/flip-review-progress-failed.sh"
}
rgs_run() {  # → echoes the step's exit status; side effects land in $RGS_ROOT/ghlog
  ( cd "$RGS_ROOT/wt" \
    && env RGS_ROOT="$RGS_ROOT" PATH="$RGS_ROOT/bin:$PATH" RUNNER_TEMP="$RGS_ROOT/tmp" \
           GH_TOKEN=x REPO=o/r CONTEXT_NUMBER=55 COMMAND='/prflow:review 55' \
           REVIEWER_LOGIN='prflow-reviewer[bot]' GITHUB_RUN_ID=1 GITHUB_RUN_ATTEMPT=1 \
           bash "$RGS_ROOT/step.sh" >"$RGS_ROOT/out" 2>"$RGS_ROOT/err" )
  echo $?
}
rgs_dismissed() { grep -c 'dismissals' "$RGS_ROOT/ghlog" 2>/dev/null || true; }

# APPROVED — merge-gating: the unbacked review IS dismissed and the job goes red.
rgs_sandbox 'fail missing=phase-entry-2 review_id=987 review_state=APPROVED'
assert_eq "#2075 step: a fail token exits 1 (the job goes red)" "1" "$(rgs_run)"
assert_eq "#2075 step: an APPROVED unbacked review is dismissed by its parsed id" "1" \
  "$(grep -c 'reviews/987/dismissals' "$RGS_ROOT/ghlog" || true)"

# CHANGES_REQUESTED — also merge-gating: dismissed.
rgs_sandbox 'fail missing=phase-entry-1 review_id=654 review_state=CHANGES_REQUESTED'
rgs_run >/dev/null
assert_eq "#2075 step: a CHANGES_REQUESTED unbacked review is dismissed" "1" \
  "$(grep -c 'reviews/654/dismissals' "$RGS_ROOT/ghlog" || true)"

# COMMENTED — NOT merge-gating: left to the durable comment, never dismissed.
rgs_sandbox 'fail missing=phase-entry-1 review_id=321 review_state=COMMENTED'
assert_eq "#2075 step: a COMMENTED verdict still exits 1" "1" "$(rgs_run)"
assert_eq "#2075 step: a COMMENTED verdict is NOT dismissed" "0" "$(rgs_dismissed)"

# No parsable review_id — nothing to dismiss; the durable comment stands alone.
rgs_sandbox 'fail missing=phase-entry-1 review_state=APPROVED'
rgs_run >/dev/null
assert_eq "#2075 step: an absent review_id dismisses nothing" "0" "$(rgs_dismissed)"

# A pass token: no dismissal, exit 0.
rgs_sandbox 'pass checklist-phases-ran'
assert_eq "#2075 step: a pass token exits 0" "0" "$(rgs_run)"
assert_eq "#2075 step: a pass token dismisses nothing" "0" "$(rgs_dismissed)"

# An unrecognized token (the shape an argparse exit-2 leaves behind, RESULT empty)
# is treated as unestablished — a warning, never a silent green pass.
rgs_sandbox ''
assert_eq "#2075 step: an empty gate output exits 0" "0" "$(rgs_run)"
assert_eq "#2075 step: an empty gate output is warned as unrecognized" "yes" \
  "$(grep -qF 'unrecognized gate output' "$RGS_ROOT/out" "$RGS_ROOT/err" && echo yes || echo no)"

# The durable comment leads with the human detail, not the raw machine token; the
# token survives as a trailing footer so it stays quotable from the comment itself.
rgs_sandbox 'fail missing=phase-entry-2 review_id=987 review_state=APPROVED'
rgs_run >/dev/null
assert_eq "#2075 step: the durable comment body leads with the human detail" "human detail line" \
  "$(head -1 "$RGS_ROOT/tmp/evidence-gate-body.md")"
assert_eq "#2075 step: the durable comment body keeps the machine token as a footer" "yes" \
  "$(grep -qF 'review_id=987 review_state=APPROVED' "$RGS_ROOT/tmp/evidence-gate-body.md" && echo yes || echo no)"

rm -rf "$RGS_ROOT"
unset -f rgs_sandbox rgs_run rgs_dismissed

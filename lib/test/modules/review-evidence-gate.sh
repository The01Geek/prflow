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

rm -rf "$REG_ROOT"

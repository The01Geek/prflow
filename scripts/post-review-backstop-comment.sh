#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-review-backstop-comment.sh — the review stall-backstop "post-and-annotate" glue
# (issue #414). Extracted from the near-identical inline blocks in
# .github/workflows/devflow.yml (and, before issue #936 withheld the auto PR-triggered
# review tier, .github/workflows/devflow-review.yml too). The ~40-line glue
# (from the decision parse onward) matched between the two blocks except: (1) the no-fire
# notice's PR reference — `${PR_NUMBER:-?}` in review.yml vs `${PR_NUMBER}` in devflow.yml,
# unified here to the `:-?` form; and (2) review.yml's glue carried a "Post the marker +
# the manual /devflow:review trigger" comment that devflow.yml's did not (now in this helper).
# Separately, devflow.yml's step keeps its own pre-glue — the empty-PR guard and the runtime
# HEAD_SHA derivation (with its own comment) — which stay in that workflow. Extracting the
# glue lets the suite DRIVE the notice-vs-warning selection instead of only presence-pinning a
# breadcrumb literal in each YAML (the scripts/describe-denial-count.sh precedent).
#
# Why a helper: the success-vs-warning selection is the load-bearing arm — a failed or
# absent POST must NEVER be annotated as a fired re-trigger (issue #408 review). Inline
# shell in YAML cannot be unit-tested; here lib/test/run.sh feeds a success breadcrumb and a
# silent POST and asserts the ::notice::/::warning:: flip.
#
# Owns the whole decision -> post -> annotate flow: resolves and calls
# request-review-backstop.sh (its decision contract is UNCHANGED — this helper only
# consumes its `decision=/reason=/attempt=/marker=` stdout), and on a `fire` decision
# composes the marker + /devflow:review re-trigger body and posts it via
# post-issue-comment.sh. Best-effort: ALWAYS exits 0; every no-fire / failure arm leaves a
# distinct GitHub-Actions annotation on stdout naming which condition fired, so the caller
# degrades to the pre-existing dead-end flip rather than silently claiming a fired resume.
#
# Inputs (env — the helper reads all six from its environment; how each is populated differs
# per call site: review.yml sets HEAD_SHA in the step env from the precheck job, while
# devflow.yml derives HEAD_SHA at runtime and passes it as a command-prefix env — the other
# five are step-env in both):
#   PR_NUMBER  HEAD_SHA  REPO  VERDICT  APP_TOKEN_PRESENT  GH_TOKEN
# Bundled-helper resolution is cwd-relative (vendored copy first), matching the workflows'
# repo-root cwd — so a consumer's .prflow/vendor/prflow/scripts/ copy wins. (Not git-root
# anchored: run from a subdirectory it would miss the vendored copy — the workflow steps
# always run at the repo root, so this is correct for the two call sites.)
set -uo pipefail

PR_NUMBER="${PR_NUMBER:-}"
HEAD_SHA="${HEAD_SHA:-}"

RRB=.prflow/vendor/prflow/scripts/request-review-backstop.sh
[ -f "$RRB" ] || RRB=scripts/request-review-backstop.sh
if [ ! -f "$RRB" ]; then
  echo "::warning::review stall backstop: request-review-backstop.sh absent at $RRB; no auto-resume (degrades to the pre-existing dead-end flip)."
  exit 0
fi
# The decision helper owns the whole fire/no-fire decision and always exits 0.
DECISION_OUT=$(VERDICT="${VERDICT:-}" HEAD_SHA="$HEAD_SHA" PR_NUMBER="$PR_NUMBER" \
               REPO="${REPO:-}" APP_TOKEN_PRESENT="${APP_TOKEN_PRESENT:-}" bash "$RRB") || true
# Parse the four `key=value` lines with bash builtins (while/case/${var#prefix}), NOT sed:
# DECISION selects the fire/no-fire branch, and a selection-deciding value must not be
# derived through a tool PRFlow's preflight does not guarantee (CLAUDE.md un-guaranteed-tool
# rule). An unparsed DECISION stays empty and takes the no-fire arm below — fail-closed.
DECISION=""; REASON=""; MARKER=""; ATTEMPT=""
while IFS= read -r _line; do
  case "$_line" in
    decision=*) DECISION="${_line#decision=}" ;;
    reason=*)   REASON="${_line#reason=}" ;;
    marker=*)   MARKER="${_line#marker=}" ;;
    attempt=*)  ATTEMPT="${_line#attempt=}" ;;
  esac
done <<EOF
$DECISION_OUT
EOF
if [ "$DECISION" != "fire" ]; then
  echo "::notice::review stall backstop: no auto-resume (reason: ${REASON:-unknown}); degraded to the dead-end flip for PR #${PR_NUMBER:-?}."
  exit 0
fi
# Post the marker + the manual `/devflow:review` trigger. The re-trigger goes through the
# SAME manual comment path a human would use, so the precheck's authorization and dedupe
# rules apply exactly as to a human's. Body via a file so newlines/backticks never traverse
# shell quoting. Guard mktemp distinctly (the implement-side sibling names this arm): a
# failed mktemp leaves BODY_FILE empty and the `> "$BODY_FILE"` write would then misdiagnose
# as a POST failure. Best-effort — degrade to the dead-end flip with an mktemp-specific
# breadcrumb, never a false "fired".
BODY_FILE="$(mktemp)" || {
  echo "::warning::review stall backstop: mktemp failed; cannot compose the re-trigger comment for PR #$PR_NUMBER (auto-resume did not fire; degrades to the dead-end flip)."
  exit 0
}
{
  printf '%s\n\n' "$MARKER"
  printf '**PRFlow review stall backstop** — this cloud review ended with no verdict for `%s`. Auto-resume attempt %s:\n\n' "$HEAD_SHA" "$ATTEMPT"
  printf '/devflow:review\n'
} > "$BODY_FILE"
POST=.prflow/vendor/prflow/scripts/post-issue-comment.sh
[ -f "$POST" ] || POST=scripts/post-issue-comment.sh
if [ ! -f "$POST" ]; then
  echo "::warning::review stall backstop: post-issue-comment.sh absent at $POST; re-trigger comment not posted for PR #$PR_NUMBER (auto-resume did not fire; degrades to the dead-end flip)."
  rm -f "$BODY_FILE"
  exit 0
fi
# post-issue-comment.sh is best-effort and ALWAYS exits 0, so its exit code is NOT a success
# signal — a failed POST would otherwise be annotated as a fired re-trigger, the silent
# no-fire this backstop exists to prevent (issue #408 review). Gate the success ::notice:: on
# the helper's exact success breadcrumb instead, mirroring the implement backstop's
# `grep -qxF "devflow: posted comment on #…"` check.
POST_OUT="$(bash "$POST" "$PR_NUMBER" "$BODY_FILE" 2>&1)"
printf '%s\n' "$POST_OUT"
rm -f "$BODY_FILE"
if printf '%s\n' "$POST_OUT" | grep -qxF "devflow: posted comment on #$PR_NUMBER"; then
  echo "::notice::review stall backstop: posted /devflow:review re-trigger (attempt ${ATTEMPT}) for PR #$PR_NUMBER."
else
  echo "::warning::review stall backstop: the /devflow:review re-trigger comment did NOT post for PR #$PR_NUMBER (auto-resume did not fire; degrades to the dead-end flip)."
fi
exit 0

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# dead-run-verdict-present.sh <repo> <pr_number> <engine_is_error>
#
# The verdict-presence gate for devflow.yml's dead-run review-progress backstop
# (issue #1172). The backstop's `Flip review-progress comment on dead run` step is
# `if: ${{ always() }}` and, since #1154, an UPSERT: on a clean-exit run it flips —
# or, finding no run-keyed comment, CREATES — a terminal `❌ Review failed`
# review-progress comment. It did that with NO verdict query at all, so a run that
# posted a verdict for the reviewed HEAD (measured: PR #1169 run 30772170838 posted
# APPROVED at 23:31:06, the backstop wrote "the run wrote no verdict" 19s later) had
# its verdict reported absent — 16 false banners vs 15 real verdicts in one day,
# 0 observed precision.
#
# This helper answers the one question the live path never asked: does a verdict
# EXIST for the reviewed HEAD? It reuses the already-shipped, HEAD-scoped,
# fail-closed sibling scripts/derive-review-verdict.sh — which reads BOTH channels
# scripts/post-review-verdict.sh writes: the formal review (reviews API) and THIS
# run's run-keyed prflow:review-progress comment (updated in the review POST-refused
# comment-fallback channel too) — and maps its `verdict_determined` output to one
# stdout token:
#   present  — a verdict was POSITIVELY determined for HEAD (approve or reject).
#              The caller suppresses the dead-run flip/create.
#   absent   — no verdict positively determined (genuinely verdict-less, an engine
#              error, an unresolvable HEAD/PR/REPO, or a failed/absent deriver).
#              The caller writes the banner as before.
#
# EVERY non-`present` path emits `absent`, so the gate FAILS TOWARD writing the
# banner: a genuinely verdict-less run still gets it (issue #1172 — "the fix must
# not be 'stop emitting it'"), and only a positively-observed verdict suppresses it.
# derive-review-verdict.sh short-circuits to incomplete on ENGINE_ERROR=true before
# any reviews query, so an engine-error run is `absent` here and still banners — the
# deliberately-scoped caveat recorded on issue #1172 (a verdict posted by a run that
# ALSO ended is_error is a separate question this evidence does not force).
#
# Arguments (positional; every one optional, absence fails closed to `absent`):
#   1  REPO            owner/name (devflow.yml passes github.repository)
#   2  PR_NUMBER       the reviewed pull request number (the flip step's TARGET_NUMBER)
#   3  ENGINE_IS_ERROR the step's parsed engine is_error ("true"/anything-else)
# GITHUB_RUN_ID (env) scopes derive-review-verdict.sh's comment fallback to this run.
# $DEVFLOW_GH overrides the gh binary (the same seam the rest of devflow uses).
#
# Always exits 0 — the backstop that consumes this must never change the invoking
# job's pass/fail result (it runs under always()), and this gate is best-effort:
# any failure fails toward the banner, never toward suppressing it.

set -uo pipefail

REPO="${1:-}"
PR_NUMBER="${2:-}"
ENGINE_IS_ERROR="${3:-false}"

emit_absent() { printf 'absent\n'; exit 0; }

_DRVP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DERIVER="$_DRVP_DIR/derive-review-verdict.sh"
if [ ! -f "$DERIVER" ] || [ ! -r "$DERIVER" ]; then
  # A partial-copy vendor deployment carrying this file without its sibling deriver
  # cannot establish verdict presence, so it fails toward the banner. Breadcrumb so
  # an operator can tell a missing-deriver degradation from a real no-verdict run.
  echo "dead-run-verdict-present: sibling derive-review-verdict.sh missing/unreadable at '$DERIVER' — cannot establish a verdict; reporting absent (the dead-run banner is NOT suppressed)" >&2
  emit_absent
fi

# Engine-error short-circuit (issue #1172's scoped caveat). derive-review-verdict.sh
# returns incomplete on ENGINE_ERROR=true in its step 1, BEFORE any query, so an
# engine-error run is always `absent` here (it still banners). Return now to skip the
# HEAD-sha gh round-trip and the deriver invocation entirely — the outcome is identical,
# and this makes the scoped caveat explicit rather than an emergent property of the
# deriver's own ordering.
if [ "$ENGINE_IS_ERROR" = "true" ]; then
  emit_absent
fi

# Resolve the gh binary through the same execution-verified resolver the deriver
# uses (guarded source — a partial copy without lib/resolve-gh.sh degrades to bare
# `gh` with a breadcrumb, never an empty DEVFLOW_GH that would misdirect the query).
# shellcheck source=../lib/resolve-gh.sh
. "$_DRVP_DIR/../lib/resolve-gh.sh" \
  || echo "dead-run-verdict-present: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi

# Resolve the reviewed HEAD sha from the PR. An issue-number target, a non-PR event,
# or a failed query yields an empty sha — which derive-review-verdict.sh fails closed
# on (incomplete/false), so the gate reports `absent` and the banner still writes.
HEAD_SHA=""
if [ -n "$REPO" ] && [ -n "$PR_NUMBER" ]; then
  HEAD_SHA="$("$DEVFLOW_GH" api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.sha' 2>/dev/null || true)"
fi

# Run the deriver. It emits two lines (verdict=…, verdict_determined=…) on stdout and
# always exits 0. Only a POSITIVELY-determined verdict suppresses the banner.
# The deriver's stderr is DELIBERATELY NOT suppressed: it emits a SPECIFIC breadcrumb
# for each fail-closed condition (reviews API query failed, empty HEAD_SHA, no verdict for
# HEAD, …) and for the non-terminating no-marked-review-names-HEAD diagnostic, and those
# are the diagnostic surface
# that lets an operator tell a genuine infrastructure failure apart from an expected
# verdict-less run on the common `absent` path. Only stdout is captured here (and by the
# workflow gate's own `$(…)`), so letting stderr flow reaches the step log without
# polluting GATE_OUT.
GATE_OUT="$(HEAD_SHA="$HEAD_SHA" ENGINE_ERROR="$ENGINE_IS_ERROR" PR_NUMBER="$PR_NUMBER" REPO="$REPO" \
  bash "$DERIVER" || true)"
case "$GATE_OUT" in
  *verdict_determined=true*)
    printf 'present\n'
    exit 0
    ;;
esac
emit_absent

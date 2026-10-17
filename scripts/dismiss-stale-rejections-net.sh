#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# dismiss-stale-rejections-net.sh <repo> <pr_number> <engine_is_error>
#
# The WORKFLOW-SIDE stale-REJECT dismissal net (issue #1175).
#
# Stale-REJECT dismissal normally happens in Phase 4.4, whose verdict post
# (scripts/post-review-verdict.sh) runs scripts/dismiss-stale-rejections.sh after an
# APPROVE. When the agent never reaches Phase 4.4
# — the exact clean-exit failure mode issue #1156 records — a subsequent APPROVE
# leaves the pull request sitting behind a superseded CHANGES_REQUESTED, with
# nothing else in the system able to clear it. This helper is the net devflow.yml's
# `command` job runs after the review engine to close that gap.
#
# It is a NET, not a replacement: dismiss-stale-rejections.sh is idempotent and only
# ever clears a SUPERSEDED review (a dismissed review becomes state DISMISSED and no
# longer matches; a review whose reviewed tree is still the current head is refused,
# never dismissed). It reads the reviewed tree from the verdict marker's `head=` when
# the review carries one and falls back to `commit_id` only for a markerless review
# (issue #1247), so Phase 4.4's run and this workflow run never double-dismiss
# or fight — the second pass over an already-dismissed review is a genuine no-op.
#
# THE GATE (issue #1175, the load-bearing part). The dismissal fires ONLY when the
# verdict for the reviewed HEAD was POSITIVELY DETERMINED as APPROVE. It reuses the
# already-shipped, HEAD-scoped, fail-closed scripts/derive-review-verdict.sh, whose
# `verdict_determined` output distinguishes "APPROVE was positively observed at this
# HEAD" from "APPROVE was DEFAULTED because a reviews query failed". Gating on
# `verdict_determined=true` is what makes a correlated GitHub API degradation unable
# to silently dismiss a live REJECT — the failure mode that makes an unconditional
# workflow-side dismissal WORSE than none at all. Every non-(determined-APPROVE)
# outcome REFUSES and says so on stdout/stderr, never failing silent (AC2). Because
# derive-review-verdict.sh short-circuits to incomplete on ENGINE_ERROR=true before
# any query, an engine-error run is `no-dismiss-undetermined` here and dismisses
# nothing.
#
# Arguments (positional; every one optional, absence fails closed to no dismissal):
#   1  REPO             owner/name (devflow.yml passes github.repository)
#   2  PR_NUMBER        the reviewed pull request number
#   3  ENGINE_IS_ERROR  the engine step's parsed is_error ("true"/anything-else)
# GITHUB_RUN_ID (env) scopes derive-review-verdict.sh's comment fallback to this run.
# $DEVFLOW_GH overrides the gh binary (the same seam the rest of devflow uses).
#
# Output (stdout, exactly one token, always emitted):
#   dismissed                — determined APPROVE; dismiss-stale-rejections.sh
#                              dismissed all its own superseded REJECT(s) (or found
#                              none outstanding — a clean no-op).
#   dismiss-refused          — determined APPROVE; dismiss ran but left at least one
#                              of its own REJECTs outstanding because it could not be
#                              shown superseded (dismiss exit 3, issue #1029).
#   dismiss-failed           — determined APPROVE; a dismiss query or a dismissal
#                              call failed (dismiss exit 1). A REJECT may still block.
#   no-dismiss-reject        — the verdict was positively a REJECT; the change-request
#                              must stand, so nothing is dismissed.
#   no-dismiss-undetermined  — the verdict was NOT positively determined (genuinely
#                              verdict-less, an engine error, an unresolvable
#                              HEAD/PR/REPO, or a failed reviews/comments query). The
#                              fail-closed arm: no dismissal on a defaulted verdict.
#   unavailable              — a required sibling helper (the deriver or the dismisser)
#                              is missing/unreadable in this deployment; nothing is
#                              dismissed (Phase 4.4 remains the only path).
#
# Always exits 0 — the workflow step that consumes this runs under always() and must
# never change the invoking job's pass/fail. It is best-effort: any failure refuses
# the dismissal (fails toward leaving a REJECT standing), never toward clearing one on
# an unestablished verdict.

set -uo pipefail

REPO="${1:-}"
PR_NUMBER="${2:-}"
ENGINE_IS_ERROR="${3:-false}"

emit() { printf '%s\n' "$1"; exit 0; }

_NET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DERIVER="$_NET_DIR/derive-review-verdict.sh"
DISMISSER="$_NET_DIR/dismiss-stale-rejections.sh"
if [ ! -f "$DERIVER" ] || [ ! -r "$DERIVER" ]; then
  echo "dismiss-stale-rejections-net: sibling derive-review-verdict.sh missing/unreadable at '$DERIVER' — cannot establish a verdict; refusing to dismiss (Phase 4.4 remains the only path)" >&2
  emit unavailable
fi
if [ ! -f "$DISMISSER" ] || [ ! -r "$DISMISSER" ]; then
  echo "dismiss-stale-rejections-net: sibling dismiss-stale-rejections.sh missing/unreadable at '$DISMISSER' — cannot dismiss; refusing (Phase 4.4 remains the only path)" >&2
  emit unavailable
fi

# Resolve the gh binary through the same execution-verified resolver the siblings
# use (guarded source — a partial copy without lib/resolve-gh.sh degrades to bare
# `gh` with a breadcrumb, never an empty DEVFLOW_GH that would misdirect the query).
# shellcheck source=../lib/resolve-gh.sh
. "$_NET_DIR/../lib/resolve-gh.sh" \
  || echo "dismiss-stale-rejections-net: resolve-gh.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'gh' (set DEVFLOW_GH to override)" >&2
if type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  DEVFLOW_GH="${DEVFLOW_GH:-gh}"
fi

# Resolve the reviewed HEAD sha from the PR (the deriver scopes its verdict to it).
# An issue-number target, a non-PR event, or a failed query yields an empty sha —
# which derive-review-verdict.sh fails closed on (incomplete/false), so the gate
# refuses. An engine-error run is refused before any round-trip (the deriver would
# short-circuit to incomplete anyway; returning here makes the caveat explicit).
if [ "$ENGINE_IS_ERROR" = "true" ]; then
  echo "dismiss-stale-rejections-net: the review engine ended in error (is_error=true) — no verdict for HEAD; refusing to dismiss." >&2
  emit no-dismiss-undetermined
fi

HEAD_SHA=""
if [ -n "$REPO" ] && [ -n "$PR_NUMBER" ]; then
  HEAD_SHA="$("$DEVFLOW_GH" api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.sha' 2>/dev/null || true)"
fi

# Run the deriver. It emits two lines (verdict=…, verdict_determined=…) on stdout and
# always exits 0. Its stderr is DELIBERATELY NOT suppressed — each fail-closed
# condition names itself there, which is the diagnostic surface that lets an operator
# tell a genuine API degradation from an expected verdict-less run.
GATE_OUT="$(HEAD_SHA="$HEAD_SHA" ENGINE_ERROR="$ENGINE_IS_ERROR" PR_NUMBER="$PR_NUMBER" REPO="$REPO" \
  bash "$DERIVER" || true)"

# Parse both fields with parameter expansion (builtins) — a value deciding this
# SELECTION never flows through a non-preflight PATH tool (CLAUDE.md guard-class 2).
VERDICT=""
DETERMINED=""
while IFS= read -r LINE; do
  case "$LINE" in
    verdict=*)            VERDICT="${LINE#verdict=}" ;;
    verdict_determined=*) DETERMINED="${LINE#verdict_determined=}" ;;
  esac
done <<< "$GATE_OUT"

# The gate: dismiss ONLY on a positively-determined APPROVE. Anything else refuses.
if [ "$DETERMINED" != "true" ]; then
  echo "dismiss-stale-rejections-net: the verdict for the reviewed HEAD was not positively determined (verdict='${VERDICT:-<none>}', verdict_determined='${DETERMINED:-<none>}') — refusing to dismiss on a defaulted/unestablished verdict (issue #1175)." >&2
  emit no-dismiss-undetermined
fi
if [ "$VERDICT" = "reject" ]; then
  echo "dismiss-stale-rejections-net: the verdict for the reviewed HEAD is a positively-determined REJECT — the change-request must stand; dismissing nothing." >&2
  emit no-dismiss-reject
fi
if [ "$VERDICT" != "approve" ]; then
  # Defensive: verdict_determined=true with a verdict that is neither approve nor
  # reject is a deriver contract violation, not a real state — refuse rather than
  # dismiss on an unrecognized token.
  echo "dismiss-stale-rejections-net: verdict_determined=true but the verdict token ('${VERDICT:-<none>}') is neither approve nor reject — refusing to dismiss on an unrecognized verdict." >&2
  emit no-dismiss-undetermined
fi

# Positively-determined APPROVE: run the dismisser and map its exit code to a token.
# The dismisser's OWN stdout (its per-review "Dismissed …" lines) is redirected to
# stderr so it reaches the step log without polluting THIS helper's stdout, which must
# carry exactly one token for the caller's `$(…)` capture. Its stderr flows through
# unchanged so its warnings/breadcrumbs are visible too.
DISMISS_RC=0
bash "$DISMISSER" "$PR_NUMBER" "$REPO" 1>&2 || DISMISS_RC=$?
case "$DISMISS_RC" in
  0) emit dismissed ;;
  3) emit dismiss-refused ;;
  *) emit dismiss-failed ;;
esac

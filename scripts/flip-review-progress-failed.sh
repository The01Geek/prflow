#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# flip-review-progress-failed.sh <pr_number> <marker> <cause>
#
# Best-effort backstop (issues #356 and #1154): when a review-engine run dies —
# the job fails, is cancelled, the runner is lost, or the step exits cleanly
# having written no verdict at all — leave THIS run's `prflow:review-progress`
# comment in the terminal `❌ Review failed` state so the pull request stops
# reading as a clean pass. This is the workflow-level mirror of the agent-side
# fatal-abort rule in skills/review/SKILL.md (the "Fatal review abort after
# seeding" clause). The `❌ Review failed` literal mirrors that skill. Marker
# ownership is split: seed-review-progress.sh derives the cloud marker, the
# skill composes only the local and helper-absent recovery forms, and the
# workflow rebuilds the cloud form passed here. Runtime parity tests keep those
# cloud forms aligned.
#
# The write is an UPSERT, not an update (issue #1154). A run that dies BEFORE
# the engine reaches its Phase 0.3.5 seed leaves no comment to flip, and the
# pre-#1154 comment-absent no-op left that pull request with nothing at all
# beside a green check — the same "a dead run reads as a pass" failure the flip
# exists to end. So a confirmed CLEAN absence now creates the comment in the
# terminal state instead of returning.
#
# Contract (mirrors ensure-label.sh / apply-labels.sh / post-issue-comment.sh):
#   - ALWAYS exits 0 — an upsert hiccup must never change the invoking job's or
#     step's exit code (finalize_check runs `set -euo pipefail` on a REQUIRED
#     check; devflow.yml's step runs `always()`).
#   - Emits exactly one stderr breadcrumb naming the arm it took — flipped,
#     created, status-already-terminal, no-Status-line, missing-args, or a
#     read/patch/create failure. Each arm names the SPECIFIC condition that
#     fired: a failed comment lookup is reported as a read failure, never as a
#     clean absence, so an operator is never told the comment does not exist
#     when the read merely failed; and a failed CREATE is reported as a create
#     failure, never as a read failure. Only `cmd_id`'s OWN rc 2 means "scanned
#     cleanly, none present" — `python3` also exits 2 when it cannot open the
#     script, and that is screened out below.
#   - Flips an EXISTING comment ONLY when its `**Status:**` line begins with
#     🚀 (interim) — anything else (a written verdict, an agent-side
#     `❌ Review failed`, any terminal glyph) is treated as terminal and left
#     byte-untouched, and NO second comment is created (fail closed to no
#     write). That is also what makes the upsert idempotent across job retries:
#     the second invocation resolves the comment the first one created, reads
#     its terminal Status, and writes nothing.
#   - The `--evidence-gate-fail` 4th argument (issue #2075) is the review-evidence
#     gate's arm: it overrides the interim-only guard for exactly one case — a run
#     that DID write a terminal verdict but whose posted verdict lacks
#     phase-execution evidence — rewriting that terminal Status to `❌ Review
#     failed` and reporting the `evidence-gate-flip` arm. Without it a hollow
#     verdict's terminal comment would keep reading as a pass. A re-run finds the
#     Status already `❌ Review failed` and leaves it failed (the Status is
#     convergent; the appended cause line is best-effort and not deduped).
#   - The run-keyed marker (`<!-- prflow:review-progress run=<id>-<attempt> -->`)
#     matches ONLY the current run's comment, so an earlier run's comment is
#     never read or modified — on the create path too, where the marker is
#     written as line 1 of the new body precisely so a later
#     `workpad.py id --marker` for this run resolves it (the scan matches a body
#     that STARTS WITH the marker).
#
# All GitHub access in this helper routes through workpad.py (id/body/patch/create),
# which honors DEVFLOW_GH. The workflow step may invoke the sibling marker-
# diagnosis helper afterward; that separate helper reads comments through the
# repository's gh resolver. The review comment's vocabulary is NOT workpad.py's
# (`Review failed` is unrecognized there and `--status` would stamp the wrong
# glyph), so the Status line is rewritten textually and the full body PATCHed —
# the same full-body-rewrite model the skill itself uses.
set -uo pipefail

PR="${1:-}"
MARKER="${2:-}"
CAUSE="${3:-review run ended without a verdict}"
# Optional 4th token (issue #2075). The default (absent) is the dead-run backstop above:
# flip ONLY an interim (🚀) Status, leave a terminal one untouched. `--evidence-gate-fail`
# is the review-evidence gate's arm — a run that DID write a terminal verdict but whose
# posted verdict lacks phase-execution evidence, so its terminal Status must still be
# rewritten to the failed state (the interim-only guard would otherwise leave the hollow
# verdict's comment reading as a pass). Any other 4th value is refused as a no-op so a
# typo cannot silently take the wrong arm.
EVIDENCE_GATE_FAIL=""
case "${4:-}" in
  '') ;;
  --evidence-gate-fail) EVIDENCE_GATE_FAIL=1 ;;
  *)
    echo "flip-review-progress-failed: unrecognized 4th argument '${4}' (expected --evidence-gate-fail or nothing) — no-op" >&2
    exit 0
    ;;
esac

# `workpad.py id` declares its issue arg `type=int`, so ARGPARSE also exits 2 on a
# usage error — the same code `cmd_id` uses for "scanned cleanly, no match". Keep the
# rc-2 arm below unambiguous by refusing a non-numeric PR here (a guard's accepted-input
# set must be a subset of its consumer's contract, not wider). Argparse is one of THREE
# non-cmd_id sources of rc 2; the other two — an unopenable/unreadable script — are
# screened just above the `id` call.
if [ -z "$PR" ]; then
  echo "flip-review-progress-failed: usage: flip-review-progress-failed.sh <pr_number> <marker> <cause>; empty pr number — no-op (a non-PR event, or an unresolved pr_number output)" >&2
  exit 0
fi
if [ -z "$MARKER" ]; then
  echo "flip-review-progress-failed: usage: flip-review-progress-failed.sh <pr_number> <marker> <cause>; empty marker — no-op (the caller failed to build the run-keyed marker)" >&2
  exit 0
fi
case "$PR" in
  *[!0-9]*)
    echo "flip-review-progress-failed: usage: pr number '${PR}' is not numeric — no-op (refusing it here keeps 'workpad.py id' rc 2 unambiguous: argparse also exits 2 on a usage error)" >&2
    exit 0
    ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKPAD="$HERE/workpad.py"

# Run link for the appended cause line (standard runner env; a local run leaves
# these empty). The reusable runner shares GITHUB_RUN_ID/ATTEMPT with the caller,
# so the URL points at the dead run.
if [ -n "${GITHUB_SERVER_URL:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
else
  RUN_URL="(run link unavailable)"
fi

# 1. Locate THIS run's comment. The run-keyed marker matches only the current
#    run, so a prior run's comment is never a candidate. `id`'s two failure
#    exits mean DIFFERENT things and must not share a breadcrumb: rc 2 is a
#    clean scan that found no comment (flag off, non-PR mode, /pr-description
#    runs, a run that died before the seed), while rc 1 is a gh-api/parse
#    failure that never established absence at all (rate limit, 403 token scope,
#    5xx). Only the FORMER authorizes the create arm below — creating on an
#    unestablished absence is how a duplicate comment gets posted — so each gets
#    its own arm. A read failure stays a best-effort no-op (exit 0); a clean
#    absence now writes.
#    workpad.py writes the SPECIFIC gh cause (rate limit, 403 token scope, 5xx) to
#    its own stderr, so capture it rather than 2>/dev/null-ing it away: without the
#    cause an operator staring at a frozen `🚀 Reviewing` comment cannot tell a
#    transient blip from a token-scope misconfiguration. Same intent as the stall
#    backstop's `tail -c 300 "$GH_ERRF"`, but read with bash builtins only — no
#    external `tail`/`tr`, whose absence on a stripped PATH would silently empty
#    the breadcrumb rather than surfacing an error.
WP_ERR="$(mktemp 2>/dev/null)" || WP_ERR=""
# Read+flatten $WP_ERR with builtins ($(<file), parameter expansion). Empty when the
# capture file could not be allocated — the breadcrumb then just omits the cause.
_wp_cause() {
  [ -n "$WP_ERR" ] && [ -s "$WP_ERR" ] || { printf '(cause unavailable)'; return 0; }
  local c; c="$(<"$WP_ERR")"; c="${c//$'\n'/ }"
  # Clamp explicitly: bash's `${c: -N}` does NOT behave like `tail -c N` — when the
  # string is SHORTER than N the negative offset lands before the start and bash
  # yields the EMPTY string (zsh clamps, bash does not). Unclamped, this dropped the
  # cause for exactly the short messages it exists to surface (a 403, a rate limit).
  [ "${#c}" -gt 300 ] && c="${c: -300}"
  printf '%s' "$c"
}
_wp_err_cleanup() { [ -n "$WP_ERR" ] && rm -f "$WP_ERR"; return 0; }
# rc 2 is only authoritative as "scanned cleanly, none present" when it came from
# `cmd_id` itself. `python3` ALSO exits 2 when it cannot open the script (a partial-copy
# vendor deployment: `can't open file … [Errno 2]`; a mode-000 file: `[Errno 13]`), which
# would otherwise land in the rc-2 arm and tell an operator the comment does not exist
# when the read never happened — precisely the misdirection the arm split exists to stop.
# A guard's accepted-input set must be a subset of its consumer's contract, so screen the
# interpreter-level rc 2 out BEFORE the arm split, two ways:
#   1. Share the consumer's own operation as the guard: the thing `python3` must open is
#      $WORKPAD, so test that directly rather than re-deriving the contract.
#   2. Backstop it on the observable that separates the two rc-2 sources: `cmd_id` exits 2
#      SILENTLY (see its `sys.exit(2)` — no stderr), while every interpreter-level rc 2
#      writes a diagnostic. So rc 2 with non-empty captured stderr is never a clean scan.
#      This relies on our ALWAYS passing an explicit `--marker`: `_workpad_marker` returns
#      immediately on an explicit marker, before the `.prflow/config.json` read that can
#      breadcrumb to stderr on a malformed/BOM config. A future caller that dropped
#      `--marker` could make a genuine clean scan write stderr and be misrouted here — so
#      keep the marker explicit, or narrow this discriminator to the interpreter's own
#      "can't open file" diagnostic.
# (2) degrades to (1) alone when $WP_ERR could not be allocated and stderr went to
# /dev/null — the common deploy case is still caught, and the residual is a no-flip no-op.
if [ ! -f "$WORKPAD" ] || [ ! -r "$WORKPAD" ]; then
  echo "flip-review-progress-failed: cannot read the helper's workpad.py sibling at '${WORKPAD}' (missing or unreadable — a partial vendor copy?) — read-failure no-op; PR #${PR}'s comment was never looked up, so its absence was NOT established" >&2
  _wp_err_cleanup
  exit 0
fi
CID="$(python3 "$WORKPAD" id "$PR" --marker "$MARKER" 2>"${WP_ERR:-/dev/null}")"
ID_RC=$?
if [ "$ID_RC" -eq 2 ] && [ -n "$WP_ERR" ] && [ -s "$WP_ERR" ]; then
  echo "flip-review-progress-failed: python3 exited 2 while looking up PR #${PR}'s review-progress comment, but wrote a diagnostic — an interpreter-level failure, not workpad.py's clean 'no match' (which exits 2 silently) — read-failure no-op; the comment's absence was NOT established. Cause: $(_wp_cause)" >&2
  _wp_err_cleanup
  exit 0
elif [ "$ID_RC" -eq 2 ]; then
  # 1b. CONFIRMED clean absence (issue #1154): the run died before the engine's
  #     Phase 0.3.5 seed, so there is nothing to flip. Create the comment in the
  #     terminal state rather than returning, or the pull request carries no
  #     trace of the dead run at all. The marker goes on line 1 — `cmd_id`'s scan
  #     matches a body that STARTS WITH the marker, so a later lookup for this
  #     same run (a retry of this very step) resolves the comment created here
  #     and takes the already-terminal arm instead of creating a second one.
  #     `--status` is deliberately NOT used: `Review failed` is not in
  #     workpad.py's recognized vocabulary and would stamp the wrong glyph, so
  #     the body is authored verbatim here exactly as the flip path rewrites it.
  _wp_err_cleanup
  NEWBODY="$(mktemp 2>/dev/null)" || {
    echo "flip-review-progress-failed: mktemp failed while composing the terminal review-progress comment for PR #${PR} — create-failure no-op; the dead run is NOT recorded on the pull request" >&2
    exit 0
  }
  {
    printf '%s\n' "$MARKER"
    printf '# PRFlow Review — PR #%s\n\n' "$PR"
    printf '%s\n\n' '**Status:** ❌ Review failed'
    printf '_Review run failed: %s — %s_\n' "${CAUSE//$'\n'/ }" "$RUN_URL"
  } > "$NEWBODY" || {
    echo "flip-review-progress-failed: could not write the terminal review-progress body for PR #${PR} — create-failure no-op; the dead run is NOT recorded on the pull request" >&2
    rm -f "$NEWBODY"
    exit 0
  }
  # Validate the printed id rather than trusting the exit status alone: a bare
  # success breadcrumb naming no comment is indistinguishable from a create that
  # silently posted nothing, which is the undiagnosable state this arm exists to
  # remove. Same non-empty check seed-review-progress.sh applies to its own
  # create arm.
  CREATE_ERR="$(mktemp 2>/dev/null)" || CREATE_ERR=/dev/null
  if NEW_CID="$(python3 "$WORKPAD" create "$PR" "$NEWBODY" 2>"$CREATE_ERR")" && [ -n "$NEW_CID" ]; then
    echo "flip-review-progress-failed: no prflow:review-progress comment for PR #${PR} (marker '${MARKER}', workpad.py id rc=2 — scanned cleanly, none present) — created comment #${NEW_CID} in the '❌ Review failed' state (${CAUSE})" >&2
  else
    # `cat` here is COSMETIC only — it folds workpad.py's own cause into the
    # breadcrumb. No arm was selected by it, and its absence on a stripped PATH
    # empties the clause rather than changing an outcome.
    echo "flip-review-progress-failed: no prflow:review-progress comment for PR #${PR} (marker '${MARKER}', scanned cleanly, none present) and workpad.py create failed or printed no comment id — create-failure no-op; the dead run is NOT recorded on the pull request. Cause: $(cat "$CREATE_ERR" 2>/dev/null)" >&2
  fi
  [ "$CREATE_ERR" = /dev/null ] || rm -f "$CREATE_ERR"
  rm -f "$NEWBODY"
  exit 0
elif [ "$ID_RC" -ne 0 ] || [ -z "$CID" ]; then
  echo "flip-review-progress-failed: could not look up PR #${PR}'s review-progress comment (marker '${MARKER}', workpad.py id rc=${ID_RC}) — read-failure no-op; the comment's absence was NOT established. Cause: $(_wp_cause)" >&2
  _wp_err_cleanup
  exit 0
fi

# 2. Read the current body (same stderr-capture discipline).
BODY="$(python3 "$WORKPAD" body "$CID" 2>"${WP_ERR:-/dev/null}")"
BODY_RC=$?
if [ "$BODY_RC" -ne 0 ] || [ -z "$BODY" ]; then
  echo "flip-review-progress-failed: could not read body of comment #${CID} for PR #${PR} (workpad.py body rc=${BODY_RC}) — read-failure no-op. Cause: $(_wp_cause)" >&2
  _wp_err_cleanup
  exit 0
fi
_wp_err_cleanup

# 3. Transform: flip the Status line ONLY when it begins with 🚀, and append a
#    one-line cause with the run link. Done in python3 (a hard dependency) so no
#    shell quoting traverses the markdown body and the 🚀 test is a literal byte
#    match, not a locale-dependent sed alternation. Prints a result token.
TMP="$(mktemp 2>/dev/null)" || {
  echo "flip-review-progress-failed: mktemp failed for PR #${PR} comment #${CID} — read/patch-failure no-op" >&2
  exit 0
}
RESULT="$(DEVFLOW_BODY="$BODY" DEVFLOW_CAUSE="$CAUSE" DEVFLOW_RUN_URL="$RUN_URL" \
  DEVFLOW_EVIDENCE_GATE_FAIL="$EVIDENCE_GATE_FAIL" \
  python3 - "$TMP" <<'PYEOF'
import os, re, sys
body = os.environ.get('DEVFLOW_BODY', '')
cause = os.environ.get('DEVFLOW_CAUSE', '')
run_url = os.environ.get('DEVFLOW_RUN_URL', '')
evidence_gate_fail = os.environ.get('DEVFLOW_EVIDENCE_GATE_FAIL', '') != ''
out_path = sys.argv[1]
m = re.search(r'^\*\*Status:\*\*[ \t]*(.*)$', body, re.MULTILINE)
if not m:
    print('NOSTATUS')
    sys.exit(0)
interim = m.group(1).lstrip().startswith('🚀')
# Default (dead-run backstop): fail closed and flip ONLY an interim (🚀) Status;
# anything else — a written verdict, an agent-side ❌ Review failed, any terminal
# glyph — is treated as terminal and left untouched. The --evidence-gate-fail arm
# (issue #2075) overrides that guard for exactly one case: a run that DID reach a
# terminal verdict but whose posted verdict lacks phase-execution evidence, so its
# terminal Status must still be rewritten to the failed state.
if not interim and not evidence_gate_fail:
    print('TERMINAL')
    sys.exit(0)
one_line_cause = ' '.join(cause.splitlines())
new_body = body[:m.start()] + '**Status:** ❌ Review failed' + body[m.end():]
new_body = new_body.rstrip('\n') + '\n\n' + \
    f'_Review run failed: {one_line_cause} — {run_url}_\n'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(new_body)
print('EVIDENCE_GATE_FLIP' if (not interim and evidence_gate_fail) else 'FLIP')
PYEOF
)"

case "$RESULT" in
  FLIP)
    if python3 "$WORKPAD" patch "$CID" "$TMP" >/dev/null 2>&1; then
      echo "flip-review-progress-failed: flipped PR #${PR} review-progress comment #${CID} to '❌ Review failed' (${CAUSE})" >&2
    else
      echo "flip-review-progress-failed: patch of comment #${CID} for PR #${PR} failed — read/patch-failure no-op (Status left unchanged)" >&2
    fi
    ;;
  EVIDENCE_GATE_FLIP)
    if python3 "$WORKPAD" patch "$CID" "$TMP" >/dev/null 2>&1; then
      echo "flip-review-progress-failed: flipped PR #${PR} review-progress comment #${CID} from a terminal verdict to '❌ Review failed' via the evidence-gate arm (${CAUSE})" >&2
    else
      echo "flip-review-progress-failed: evidence-gate patch of comment #${CID} for PR #${PR} failed — read/patch-failure no-op (Status left unchanged)" >&2
    fi
    ;;
  TERMINAL)
    echo "flip-review-progress-failed: PR #${PR} comment #${CID} Status is not 🚀 (already terminal) — no flip" >&2
    ;;
  NOSTATUS)
    echo "flip-review-progress-failed: PR #${PR} comment #${CID} has no Status line — no flip" >&2
    ;;
  *)
    echo "flip-review-progress-failed: transform of comment #${CID} for PR #${PR} produced no result — read/patch-failure no-op" >&2
    ;;
esac

rm -f "$TMP"
exit 0

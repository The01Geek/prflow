#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# seed-review-progress.sh PR_NUMBER MARKER BODY_FILE — find-or-create the review
# engine's per-run live-progress comment, and print an outcome line plus the
# authoritative marker on success (issues #857, #1054).
#
# CALLERS (issue #2073): the review engine's own Phase 0.3.5 seed, AND — on the
# devflow.yml command tier — the command job's seeding step, which invokes this helper
# BEFORE the agent starts and hands the reported id/marker/run link into the agent's
# prompt. The helper's find-or-resume arm makes the later agent-side invocation adopt
# the workflow-seeded comment rather than duplicating it, so the two callers converge on
# one comment. This helper is unchanged by that split.
#
# WHY A HELPER, not an inline fence (issue #857): the review engine's old seed was a
# `case` + `if`/`elif` compound in skills/review/SKILL.md carrying three screens
# (S1/S2/S3). The cloud review matcher refuses that compound outright — measured 8/8
# refusals across 6 PRs — so the screens never ran in cloud: the seed silently failed,
# `$WP` was never set, and the engine either lost the live comment entirely or
# improvised a shape that sometimes reached the `create` arm unable to tell a clean
# absence (cmd_id's silent exit 2) from an interpreter-level exit 2 — the exact
# duplicate-workpad failure issue #384 exists to prevent. Moving the find-or-create
# decision into this helper lets it run as a single-statement, leading-token
# invocation the matcher permits, and lets lib/test/run.sh drive every screen as
# ordinary shell (the same pattern as classify-id-exit.sh / describe-denial-count.sh).
#
# CONTRACT — exactly one outcome line per reachable path, plus a MARKER line and a RUNLINK
# line after each successful outcome (the RUNLINK line carries the compose-run-url.sh run
# link this run composed, issue #1536). The vocabulary is closed and has no silent path (a
# fence that prints NOTHING is therefore a harness refusal the caller routes to its fallback
# arm, never read as a create authorization):
#
#   stdout                                         exit  meaning
#   RESUME <id> + MARKER <...> + RUNLINK <...>      0     this run's comment already exists (cmd_id exit 0)
#   CREATED <id> + MARKER <...> + RUNLINK <...>     0     clean absence confirmed; comment created
#   SKIP not-numeric                    3     S1 refused a non-numeric PR number
#   SKIP no-run-key                     3     neither a usable GitHub run id nor the local
#                                             fallback marker slot was available
#   SKIP workpad-unreadable-script-dir  3     this helper's own directory could not be resolved,
#                                             so the workpad.py path cannot be derived
#   SKIP workpad-unreadable-file        3     S2 found workpad.py missing or unreadable
#   SKIP api-error-scratch-file         3     the scratch file for the id stderr capture
#                                             could not be created
#   SKIP api-error-id-empty-id          3     `id` exited 0 without printing a comment id
#   SKIP api-error-create-empty-id      3     `create` exited 0 without printing a comment id
#   SKIP api-error-create-failed        3     `create` failed after a confirmed clean absence
#   SKIP api-error-id-failed            3     `id` reported a real failure, or S3 rejected the
#                                             create arm (exit 2 WITH stderr)
#
# ONE TOKEN PER ARM, not one per screen (issue #871): the caller's only diagnostic channel
# for a refusal is the stdout token — the review engine's primary invocation redirects
# nothing, so this helper's stderr breadcrumb reaches a tool transcript but never the
# annotation the operator reads. A vocabulary that collapsed five distinct causes onto one
# `SKIP api-error` value therefore made a failed seed undiagnosable from the annotation
# alone. Every token shares the `SKIP ` prefix so the caller routes on the prefix and a
# later arm needs no second edit to the prompt surface; the qualifier after it is what
# attributes the refusal. Each arm's stderr breadcrumb is unchanged.
#
# This is the same token-line-plus-exit-code SHAPE the implement tier's helpers use, but
# with its OWN codes, and it matches neither of theirs: `scripts/classify-id-exit.sh` (the
# early workpad gate) prints `adopt`/`create`/`skip` and ALWAYS exits 0, while
# `scripts/resolve-existing-pr.sh` (the Phase 3.1 PR-resolution helper) is the one that
# distinguishes CREATE(2) from REFUSED(3). This helper uses 0 for both success tokens and 3
# for every SKIP. Read all three as separate contracts — do not align exit codes across them.
#
# The three screens keep the create arm reachable ONLY from cmd_id's own clean-absence
# exit:
#   (S1) A non-numeric PR number is refused BEFORE the id call, so argparse's own exit 2
#        (`id` declares `issue` as type=int) can never reach the arm split.
#   (S2) The workpad.py this helper would exec is verified readable BEFORE the id call, so
#        a broken deploy is refused with a breadcrumb naming its cause instead of reaching
#        the arm split at all. Note the precise mechanism: this helper execs the script
#        DIRECTLY through its own shebang (never `python3 <path>`), so a missing script
#        fails at exec with rc 127 and an unreadable one with rc 126 — neither is python3's
#        exit 2, so neither could reach the `-eq 2` clean-absence arm even without S2. What
#        S2 buys is therefore the SPECIFIC diagnosis (a partial vs a permission-broken
#        deploy), not exit-2 disambiguation; without it both collapse into the id-failure arm
#        (SKIP api-error-id-failed). Known limit: S2 tests `-r` only, so an exec-bit-stripped
#        copy is readable, fails exec with rc 126, and takes that arm.
#   (S3) cmd_id exits 2 SILENTLY (sys.exit(2)); every interpreter-level exit 2 writes a
#        diagnostic. So exit 2 with a NON-EMPTY captured stderr file is never a clean
#        scan — it routes to SKIP api-error-id-failed, never create. Emptiness is derived with
#        `[ -s <file> ]` alone; no arm-selection value is derived through cat/tr/sed/
#        wc/cut/head (a value that decides an arm must not flow through a
#        non-preflight-guaranteed PATH tool).
#
# Usage: seed-review-progress.sh PR_NUMBER MARKER BODY_FILE
set -uo pipefail

normalize_body() {
  local normalized_body="$1"
  local marker="$2"
  local body_file="$3"
  local error_file="$4"
  local run_link="$5"

  if [ -z "$normalized_body" ]; then
    echo "could not create a scratch file for the normalized review-progress body" >> "$error_file"
    return 1
  fi

  # Capture the status rather than negating the compound with `if ! { … } > "$normalized_body"`:
  # bash does not propagate a failed redirect on a compound command through `!` (issue #1524),
  # so the negated form returned success having written nothing when the redirect could not open.
  local first_line=true
  local body_line
  local normalize_rc=0
  {
    printf '%s\n' "$marker"
    while IFS= read -r body_line || [ -n "$body_line" ]; do
      if [ "$first_line" = true ]; then
        first_line=false
        case "$body_line" in
          '<!-- prflow:review-progress run='*|'<!-- devflow:review-progress run='*) continue ;;
        esac
      fi
      # Rewrite the `**Run:**` line to the helper-composed run link (issue #1536), so a
      # caller-authored placeholder — an unexpanded `$GITHUB_…` literal, a wrong owner, or a
      # stale `_(local run)_` — never survives into the created comment. The `case` glob is a
      # bash builtin (no PATH tool), and the run link came from compose-run-url.sh, the single
      # place it is composed. Preserve every other line verbatim.
      case "$body_line" in
        '**Run:**'*) printf '%s\n' "**Run:** $run_link"; continue ;;
      esac
      printf '%s\n' "$body_line"
    done < "$body_file"
  } > "$normalized_body" || normalize_rc=$?
  if [ "$normalize_rc" -ne 0 ]; then
    echo "could not normalize the review-progress body at '$body_file'" >> "$error_file"
    return 1
  fi
}

PR_NUMBER="${1:-}"
MARKER="${2:-}"
BODY_FILE="${3:-}"

# Cloud ownership (issue #1054): when GitHub supplies a non-blank run id, derive
# the marker here, at the helper boundary. The caller's positional marker remains
# the local-mode fallback only. Parameter substitution is a bash builtin, so a
# stripped PATH cannot turn a whitespace-only id into an authoritative key.
RUN_ID="${GITHUB_RUN_ID:-}"
RUN_ID_NONSPACE="${RUN_ID//[[:space:]]/}"
if [ -n "$RUN_ID_NONSPACE" ]; then
  RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
  MARKER="<!-- prflow:review-progress run=${RUN_ID}-${RUN_ATTEMPT} -->"
fi

# The workpad.py this helper drives lives beside it in scripts/. S2 screens THIS path.
# Check the directory resolution itself rather than appending to whatever it produced: an
# unreadable parent dir (or a runner that does not populate BASH_SOURCE) makes the
# substitution empty, and the unguarded form would then screen the literal `/workpad.py`
# and report a partial deploy — the right token with a diagnosis pointing at the wrong
# cause, which is exactly the debugging cost this helper exists to remove.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [ -z "$SCRIPT_DIR" ]; then
  echo "devflow review-seed: could not resolve this helper's own directory from '${BASH_SOURCE[0]:-<unset>}' — the workpad.py path cannot be derived (an unreadable parent directory, or a runner that does not populate BASH_SOURCE)" >&2
  echo "SKIP workpad-unreadable-script-dir"
  exit 3
fi
WORKPAD_PY="$SCRIPT_DIR/workpad.py"

# Compose THIS run's link once, at the helper boundary (issue #1536), from the single place
# it is composed: compose-run-url.sh, which lives beside this helper in scripts/. Its own
# guard fails closed to `_(local run)_` when the cloud env is partial, and it always exits 0
# printing one line, so a present helper yields a non-empty RUN_LINK on every path. Should the
# bundled helper be absent (a partial deploy), fall back to the same closed default rather
# than writing an empty `**Run:**` line. The RESUME and CREATED arms both report this literal
# on a `RUNLINK` line so the agent re-emits an observed value instead of guessing one.
RUN_LINK="$("$SCRIPT_DIR/compose-run-url.sh" 2>/dev/null)" || RUN_LINK=""
[ -n "$RUN_LINK" ] || RUN_LINK="_(local run)_"

# (S1) Refuse an empty or non-digit PR number before the id call. The `case` glob is a
# bash builtin (no PATH tool), so the screen holds even on a stripped-down host.
case "$PR_NUMBER" in
  ''|*[!0-9]*)
    echo "devflow review-seed: PR number '$PR_NUMBER' is not numeric — refusing the workpad.py id call (argparse would exit 2, indistinguishable from cmd_id's clean-absence exit 2)" >&2
    echo "SKIP not-numeric"
    exit 3 ;;
esac

# S3's emptiness discriminator SILENTLY DEPENDS on this: `--marker` short-circuits
# `_workpad_marker` before the `.prflow/config.json` read, and that read can breadcrumb
# to stderr. An empty MARKER would let the breadcrumb land in $ERRF on a genuine clean
# absence, so S3 would read the first write as an interpreter-level exit and route it to
# SKIP api-error-id-failed — fail-closed, but the live comment is lost with no explanation. Guard
# the assumption at the boundary rather than leaving it latent.
if [ -z "$MARKER" ]; then
  echo "devflow review-seed: no usable GitHub run id and no fallback marker were supplied — refusing the id call (an empty --marker lets a config breadcrumb reach stderr and defeat the exit-2 emptiness discriminator)" >&2
  echo "SKIP no-run-key"
  exit 3
fi

# (S2) The workpad.py about to exec must be a readable file, so a broken deploy is refused
# with a breadcrumb naming its cause rather than collapsing into the id-failure arm the raw
# exec failure (rc 127 missing / rc 126 unreadable) would otherwise take.
if [ ! -r "$WORKPAD_PY" ]; then
  if [ -e "$WORKPAD_PY" ]; then
    echo "devflow review-seed: workpad.py present but unreadable ([Errno 13]) at $WORKPAD_PY — a permission-broken deploy" >&2
  else
    echo "devflow review-seed: workpad.py not present ([Errno 2]) at $WORKPAD_PY — a partial deploy" >&2
  fi
  echo "SKIP workpad-unreadable-file"
  exit 3
fi

# (S3) Capture id's stderr to a file (never /dev/null) so exit 2 can be split by
# emptiness. Clean up on exit.
ERRF="$(mktemp 2>/dev/null)" || ERRF=""
if [ -z "$ERRF" ]; then
  echo "devflow review-seed: could not create a scratch file for the id stderr capture" >&2
  echo "SKIP api-error-scratch-file"
  exit 3
fi
NORMALIZED_BODY=""
trap 'rm -f "$ERRF" "${NORMALIZED_BODY:-}"' EXIT

# Branch on the id call's OWN exit status inline. A captured rc read in a LATER
# statement is dropped by some inline-bash runners (issue #284) — but this helper runs
# under its own shebang bash, so the concern is moot here; the inline form is kept for
# clarity and parity with the implement gate.
if WP="$("$WORKPAD_PY" id "$PR_NUMBER" --marker "$MARKER" 2>"$ERRF")"; then
  # exit 0 — this run's comment already exists. Validate the id is non-empty rather
  # than trusting the exit-0 contract: emitting a bare `RESUME ` would hand the caller
  # an empty $WP that every later `patch` call silently no-ops on — the frozen-comment
  # failure this helper exists to make diagnosable. Fail closed onto the shared token.
  if [ -z "$WP" ]; then
    echo "devflow review-seed: workpad.py id exited 0 but printed no comment id: $(cat "$ERRF" 2>/dev/null)" >&2
    echo "SKIP api-error-id-empty-id"
    exit 3
  fi
  echo "RESUME $WP"
  echo "MARKER $MARKER"
  echo "RUNLINK $RUN_LINK"
  exit 0
elif [ "$?" -eq 2 ] && [ ! -s "$ERRF" ]; then
  # exit 2 AND silent ⇒ cmd_id's clean absence. This run's first write: create it. The
  # helper owns the marker/body agreement: prepend the authoritative marker and
  # remove a caller-authored current or superseded marker from line one. Preserve
  # every other line verbatim (apart from normalizing a missing final newline).
  NORMALIZED_BODY="$(mktemp 2>/dev/null)" || NORMALIZED_BODY=""
  if normalize_body "$NORMALIZED_BODY" "$MARKER" "$BODY_FILE" "$ERRF" "$RUN_LINK" \
     && WP="$("$WORKPAD_PY" create "$PR_NUMBER" "$NORMALIZED_BODY" 2>>"$ERRF")"; then
    # Same non-empty validation as the RESUME arm above.
    if [ -z "$WP" ]; then
      echo "devflow review-seed: workpad.py create exited 0 but printed no comment id: $(cat "$ERRF" 2>/dev/null)" >&2
      echo "SKIP api-error-create-empty-id"
      exit 3
    fi
    echo "CREATED $WP"
    echo "MARKER $MARKER"
    echo "RUNLINK $RUN_LINK"
    exit 0
  fi
  # Fold the captured stderr into the breadcrumb (the inline seed this helper replaced
  # did the same): a refusal token with no underlying cause is exactly the
  # undiagnosable missing-comment failure issue #857 exists to eliminate. `cat` is used
  # for a COSMETIC diagnostic only — no arm was selected by it, and its absence empties
  # the clause rather than changing an outcome (the non-preflight-PATH-tool rule).
  echo "devflow review-seed: body normalization or workpad.py create failed after a confirmed clean absence: $(cat "$ERRF" 2>/dev/null)" >&2
  echo "SKIP api-error-create-failed"
  exit 3
else
  # A real gh-api/parse failure (exit 1), or exit 2 WITH stderr (an interpreter-level
  # exit, not cmd_id's clean scan). Skip to avoid a duplicate comment.
  # Same cosmetic-only stderr fold as the create arm above.
  echo "devflow review-seed: workpad.py id failed (exit != 0, or exit 2 with non-empty stderr — an interpreter-level exit, not cmd_id's clean scan): $(cat "$ERRF" 2>/dev/null)" >&2
  echo "SKIP api-error-id-failed"
  exit 3
fi

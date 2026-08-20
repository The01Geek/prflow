#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Resolve whether a LIGHT /devflow:* command (review, review-and-fix,
# pr-description) should run, which one, and on which issue/PR number.
#
# devflow.yml's command path runs claude-code-action in AGENT mode with an
# explicit synthesised `/prflow:<cmd> <n>` prompt (the detector emits the
# canonical /prflow: form regardless of which namespace the user typed). Agent mode needs no
# `@claude` phrase, so this never collides with Anthropic's stock claude.yml
# (TAG mode, keyed on `@claude`). Agent mode runs for ANY actor, so this script
# is the cost/authorization gate — same contract as resolve-implement-trigger.sh.
#
# /devflow:implement is intentionally NOT handled here — it's the heavy path
# (devflow-implement.yml). The workflow `if:` already excludes it; we re-exclude
# defensively below.
#
# Inputs (env): ACTOR, ALLOWED_BOTS, ALLOWED_USERS, REPO, GH_TOKEN,
#               TRIGGER_TEXT, CONTEXT_NUMBER
# Output (stdout; caller appends to $GITHUB_OUTPUT, tests assert directly):
#   should_run=true|false
#   command=/prflow:<cmd> <n>|""
set -euo pipefail

emit() { printf '%s=%s\n' "$1" "$2"; }

text="${TRIGGER_TEXT:-}"
context_number="${CONTEXT_NUMBER:-}"

# --- Self-trigger guard (runs BEFORE detection / authorization) -------------
# Defense-in-depth mirrored from resolve-implement-trigger.sh: decline any body
# that carries a DevFlow self-comment marker, so DevFlow's own marker-tagged
# comments (the review engine's run-keyed live progress comment, or an implement
# workpad) can never re-enter the gate — regardless of who authored them or what
# phrase they quote. The anchoring below is the authoritative gate for quoted
# prose; this guard cheaply catches DevFlow's own progress comment (whose
# narrative naturally quotes `/devflow:review`).
#
# The effective markers default to their built-in values (the run-keyed
# review-progress marker PREFIX `<!-- prflow:review-progress`, matching
# scripts/derive-review-verdict.sh's `<!-- prflow:review-progress run=<id>- -->`
# shape, and the workpad marker `<!-- prflow:workpad -->`, matching
# scripts/workpad.py's own fallback), so the guard protects a repo with no extra
# workflow wiring. Each is a literal substring match (`case`, not a regex), so a
# marker customized with regex-special characters still matches literally and a
# marker quoted/embedded anywhere in the body is still caught.
review_progress_marker="${SELF_REVIEW_PROGRESS_MARKER:-<!-- prflow:review-progress}"
workpad_marker="${SELF_WORKPAD_MARKER:-<!-- prflow:workpad -->}"
# PRFlow writes the current spelling; every artifact created before the rename carries the superseded one and no body is rewritten, so readers accept BOTH (issue #1003). A self-trigger guard that stops recognising a pre-rename marker fails
# OPEN — it silently no-ops and the Devflow-authored comment re-triggers a
# duplicate run — so each effective marker contributes its other-namespace twin
# too. The twin is DERIVED from the effective value, so a consumer-customised
# marker outside the namespace contributes only itself.
_ns_twin() {
  case "$1" in
    '<!-- prflow:'*) printf '%s\n' "<!-- devflow:${1#<!-- prflow:}" ;;
    '<!-- devflow:'*) printf '%s\n' "<!-- prflow:${1#<!-- devflow:}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
for marker in "$review_progress_marker" "$(_ns_twin "$review_progress_marker")" \
              "$workpad_marker" "$(_ns_twin "$workpad_marker")"; do
  [ -n "$marker" ] || continue
  case "$text" in
    *"$marker"*)
      echo "::warning::light /devflow:* trigger came from a Devflow-authored comment (self-comment marker '$marker' present); skipping (self-trigger guard)." >&2
      emit should_run false
      emit command ""
      exit 0
      ;;
  esac
done

# --- Command detection via the shared standalone-command detector -----------
# The detector is the single markdown-aware, anchored, fence-/indent-aware line
# scanner (scripts/detect-standalone-command.sh). The review_dedupe job in
# devflow.yml routes through the SAME script (issue #321), so the trigger gate
# and the dedupe matcher are a single source of truth and cannot drift. It fires
# only on a standalone command in ordinary comment
# text (most-specific-first: review-and-fix outranks review), declining a command
# that is merely quoted in prose, blockquoted, indented as code, or inside a
# fenced block — so a non-invoking mention in any comment/review body is declined
# regardless of who authored it (this covers the reported PR-review vector).
# Invoked via `bash` so a vendored copy that lost its executable bit still runs
# (same robustness rationale as devflow.yml's `bash "$RESOLVER"`). Guarded with
# `if !` so a MISSING/unrunnable detector (broken vendor deploy, absent awk) is
# declined fail-closed with a DISTINCT breadcrumb rather than aborting under
# `set -e` with only a generic bash error, or falling through to the misdirected
# "no standalone command" decline below that blames the comment text.
detector="$(dirname "$0")/detect-standalone-command.sh"
if ! det_out="$(printf '%s' "$text" | bash "$detector")"; then
  echo "::warning::standalone-command detector ('$detector') failed to run (missing/unrunnable, or awk unavailable); declining (fail-closed) — this is a BROKEN INSTALL, not a missing command." >&2
  emit should_run false
  emit command ""
  exit 0
fi
# Parse the detector's two `key=value` lines with BASH BUILTINS ONLY — a
# here-string (so the loop runs in THIS shell and the assignments survive),
# `while IFS= read -r`, `case`, and `${var#prefix}` stripping. CLAUDE.md's
# guard-class 2: a value that decides a SELECTION or an EMITTED result must not
# be derived through a non-preflight PATH tool, and lib/preflight.sh guarantees
# only git/gh/jq/python3 — NOT `sed`. Derived with `sed` inside a plain command
# substitution under `set -euo pipefail`, an absent `sed` exits 127 and aborts
# the resolver outright: NEITHER `should_run=` line is emitted, the caller
# appends nothing to $GITHUB_OUTPUT, and the downstream read is empty rather
# than a definite `false` — the same raw-abort failure class the `if !` guard
# above guards against, here in a trigger gate. Builtins cannot be absent, so this
# parse always resolves and always reaches one of the emits below. Mirrors the
# sibling resolve-implement-trigger.sh (issue #1032/#1042).
cmd=""
det_number=""
det_saw_command=false
while IFS= read -r det_line || [ -n "$det_line" ]; do
  case "$det_line" in
    command=*) cmd="${det_line#command=}"; det_saw_command=true ;;
    number=*)  det_number="${det_line#number=}" ;;
  esac
done <<< "$det_out"

# The detector's output contract is BOTH lines: its two `printf`s sit in an END
# block, which awk runs whether or not a command matched. No `command=` line at
# all therefore means the contract was violated — a truncated or foreign stdout
# from a tampered or half-written detector copy — which is a BROKEN INSTALL, not
# "no command present". Decline with its own breadcrumb so an unresolvable parse
# is never misreported as a clean no-command decline. (An absent `number=` line
# needs no such arm: it is indistinguishable in effect from the empty value the
# detector legitimately emits, and falls through to the context number below.)
if [ "$det_saw_command" != true ]; then
  echo "::warning::standalone-command detector ('$detector') emitted no 'command=' line (output-contract violation); declining (fail-closed) — this is a BROKEN INSTALL, not a missing command." >&2
  emit should_run false
  emit command ""
  exit 0
fi

if [ -z "$cmd" ]; then
  echo "::warning::No STANDALONE light /devflow:* command in trigger text (a command merely quoted in prose, blockquoted, indented, or fenced does not trigger); nothing to dispatch." >&2
  emit should_run false
  emit command ""
  exit 0
fi

# --- Light-command ALLOWLIST (fail-closed; heavy path is not a light command) -
# The shared detector is command-agnostic: since issue #1032 it also recognizes
# the heavy /devflow:implement token (so resolve-implement-trigger.sh can share
# the one matcher), and it may learn further heavy tokens later. This LIGHT
# resolver dispatches ONLY the three light commands; anything else the detector
# recognizes — /prflow:implement today, any future heavy token tomorrow — is
# declined here. An allowlist (not an implement-specific blocklist) keeps this
# fail-closed with no per-heavy-command maintenance: a standalone implement
# belongs to devflow-implement.yml, and the workflow `if:` already excludes it
# upstream, so this is the resolver backstop. The light path's OBSERVABLE
# behavior is UNCHANGED — implement declined with an empty `cmd` (no ladder
# entry) before #1032 and declines here now, both should_run=false — only the
# diagnostic differs.
case "$cmd" in
  /prflow:review|/prflow:review-and-fix|/prflow:pr-description) : ;;
  *)
    echo "::notice::'${cmd}' is not a light /devflow:* command (the heavy /devflow:implement path is devflow-implement.yml); nothing to dispatch here." >&2
    emit should_run false
    emit command ""
    exit 0
    ;;
esac

# --- Authorization (cost control: agent mode runs for any actor) ------------
# Shared with resolve-implement-trigger.sh — see scripts/authorize-actor.sh.
# shellcheck source=scripts/authorize-actor.sh
. "$(dirname "$0")/authorize-actor.sh"
authorize_actor

# shellcheck disable=SC2154  # authorized/deny_reason are set by authorize_actor (sourced above)
if [ "$authorized" != "true" ]; then
  echo "::warning::${cmd} requested by '${ACTOR:-}' $deny_reason; skipping (cost control)." >&2
  emit should_run false
  emit command ""
  exit 0
fi

# --- Target number resolution -----------------------------------------------
# A LIGHT command addresses the THREAD it was commented on, never a number typed
# in the command text: the detector still recognises a trailing number (so which
# comments fire is unchanged), but here that number is discarded in favour of the
# event's context number, so the workflow's PR-ness guard tests the same thread
# the acted-on number names, by construction (issue #1863). Discarding a typed
# number that carried a real intent silently would strand the person who typed
# it, so name both numbers on stderr (a run-log line) whenever one is discarded.
# resolve-implement-trigger.sh is the heavy path and deliberately keeps
# explicit-number-wins. Bash builtins only — a value that decides where a write
# lands must not flow through a non-preflight-guaranteed PATH tool.
if [ -n "$det_number" ]; then
  echo "::warning::${cmd} carries a trailing number ${det_number}, but a light command addresses the thread it was posted on; ignoring ${det_number} and using the thread's number ${context_number:-<none>}." >&2
fi
number="$context_number"

if ! [[ "$number" =~ ^[0-9]+$ ]]; then
  echo "::warning::Could not resolve an issue/PR number for ${cmd}; skipping." >&2
  emit should_run false
  emit command ""
  exit 0
fi

emit should_run true
emit command "$cmd $number"

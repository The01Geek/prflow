#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Resolve whether a /devflow:implement trigger should run, and on which issue.
#
# devflow-implement.yml runs claude-code-action in AGENT mode with an explicit,
# synthesised `/devflow:implement <n>` prompt. Agent mode does NOT need the
# `@claude` phrase, so Anthropic's stock claude.yml (tag mode, keyed on
# `@claude`) never double-fires on a bare `/devflow:implement <n>` comment. The
# trade-off: agent mode runs for ANY actor, so this script is the cost/
# authorization gate. The only trigger is a bare command in a real issue comment
# — never an issue description body, a PR comment, or a review (issues-only; see
# the IS_PULL_REQUEST guard below) — and there is no label path.
#
# Inputs (env):
#   ACTOR           triggering login (github.event.sender.login); a trailing
#                   `[bot]` suffix is tolerated.
#   ALLOWED_BOTS    comma-separated bare bot logins from config.
#   ALLOWED_USERS   comma-separated human logins ('*' = any collaborator).
#   REPO            owner/repo, for the collaborator-permission API call.
#   TRIGGER_TEXT    the issue-comment body that fired (never a description).
#   CONTEXT_NUMBER  the issue number the event is attached to: the fallback
#                   target when TRIGGER_TEXT has no explicit number.
#   SELF_COMMENT_MARKER  the repo's effective workpad marker. When TRIGGER_TEXT
#                   contains it (literal substring), the comment is one PRFlow
#                   posted itself (the workpad), so we decline — a self-trigger
#                   guard. Defaults to '<!-- prflow:workpad -->' when unset/empty
#                   (matching scripts/workpad.py's own fallback).
#   IS_PULL_REQUEST 'true' when the triggering thread is a pull request (the
#                   caller wires it from `github.event.issue.pull_request != null`).
#                   /devflow:implement is issue-only, so we decline on a PR — a
#                   resolver-level backstop for the gate `if:`'s PR filter. Any
#                   other value (including unset/empty) is treated as not-a-PR.
#   GH_TOKEN        token for `gh api` (collaborator check), set by the caller.
#
# Output: two `key=value` lines on stdout (the caller appends them to
# $GITHUB_OUTPUT; tests assert them directly):
#   should_run=true|false
#   number=<n>|""
#
# should_run is true ONLY when the actor is authorized AND a number resolves.
# Fails CLOSED on any ambiguity. Diagnostics go to stderr as ::warning:: lines.

set -euo pipefail

emit() { printf '%s=%s\n' "$1" "$2"; }

actor="${ACTOR:-}"
text="${TRIGGER_TEXT:-}"
context_number="${CONTEXT_NUMBER:-}"
# Effective workpad marker; defaults to workpad.py's own fallback so the guard
# protects repos with no config just the same.
marker="${SELF_COMMENT_MARKER:-<!-- prflow:workpad -->}"
# PRFlow writes the current spelling; every artifact created before the rename carries the superseded one and no body is rewritten, so readers accept BOTH (issue #1003). A self-trigger guard that stops recognising a pre-rename workpad
# marker fails OPEN — the guard silently no-ops and the comment re-triggers a
# duplicate cloud run — so the superseded spelling is matched too. It is
# derived from `marker` rather than hardcoded, so a consumer-customised marker
# outside the namespace still yields exactly one literal to match.
case "$marker" in
  '<!-- prflow:'*) marker_superseded="<!-- devflow:${marker#<!-- prflow:}" ;;
  '<!-- devflow:'*) marker_superseded="<!-- prflow:${marker#<!-- devflow:}" ;;
  *) marker_superseded="$marker" ;;
esac
# Pull-request context signal; anything other than the literal 'true' (including
# unset/empty) is treated as an issue thread, so a repo that doesn't wire it
# behaves exactly as before.
is_pull_request="${IS_PULL_REQUEST:-}"

# --- Self-trigger guard (runs BEFORE authorization / number resolution) -----
# PRFlow's own workpad comment quotes the literal phrase `/devflow:implement`
# (e.g. the "/devflow:implement run started" note) and carries no `@claude`, so
# it would otherwise re-enter the gate and fire a duplicate run on its own
# thread. The workpad always begins with the marker (workpad.py matches it with
# startswith); here we deliberately decline any comment that *contains* the
# marker anywhere — a broader check, so a quoted/embedded marker is still caught
# — regardless of actor (an allowed bot posts the workpad) or which phrase it
# quotes. Substring match — not a regex — so a customized marker with
# regex-special chars matches literally.
if [ -n "$marker" ]; then
  case "$text" in
    *"$marker"*|*"$marker_superseded"*)
      echo "::warning::/devflow:implement trigger came from a Devflow-authored comment (workpad marker present); skipping (self-trigger guard)." >&2
      emit should_run false
      emit number ""
      exit 0
      ;;
  esac
fi

# --- Pull-request-context guard (runs BEFORE authorization / number resolution)
# In GitHub's API a PR comment IS an issue_comment, so a comment on a pull
# request would otherwise fall back to the PR number and start a spurious run
# (e.g. the weekly audit-report comment, which quotes the literal phrase
# `/devflow:implement` in prose, re-entering the gate on the state PR).
# /devflow:implement is issue-only. The gate `if:` already filters PR comments
# (`github.event.issue.pull_request == null`); this is the fail-closed resolver
# backstop, deliberately placed before authorization and number resolution so a
# PR comment is declined regardless of who sent it or whether it carries an
# explicit number. Mirrors the self-trigger guard's structure above.
if [ "$is_pull_request" = "true" ]; then
  echo "::warning::/devflow:implement triggered from a pull-request comment; it runs on issues only — skipping (pull-request-context guard)." >&2
  emit should_run false
  emit number ""
  exit 0
fi

# --- Standalone-command detection via the shared markdown-aware detector -----
# Route through scripts/detect-standalone-command.sh — the SAME single scanner
# resolve-command-trigger.sh and devflow.yml's review_dedupe use (issue #321) —
# so /devflow:implement gets the identical fence/bareness awareness the light
# path already has, and a THIRD matcher (which could drift) is never written
# (issue #1032). Before this the resolver matched the token with a bare
# `grep -oiE`, so a comment merely QUOTING the command — in prose, a `>`
# blockquote, an indented/fenced code block — fired a full, expensive run. The
# detector is markdown-aware and fires only on a command that is the sole content
# of its own line, is fail-closed on an unbalanced fence, and emits
# `command=`/`number=` on stdout. Run BEFORE authorization (mirroring
# resolve-command-trigger.sh) so a non-triggering mention declines without a
# collaborator-API call — the authorization logic below is unchanged, only moved
# after this gate. Invoked via `bash` so a vendored copy that lost its executable
# bit still runs; guarded with `if !` so a MISSING/unrunnable detector (broken
# vendor deploy, absent awk) declines fail-closed with a DISTINCT breadcrumb
# rather than aborting under `set -e` or being misread as "no command present".
detector="$(dirname "$0")/detect-standalone-command.sh"
if ! det_out="$(printf '%s' "$text" | bash "$detector")"; then
  echo "::warning::standalone-command detector ('$detector') failed to run (missing/unrunnable, or awk unavailable); declining (fail-closed) — this is a BROKEN INSTALL, not a missing command." >&2
  emit should_run false
  emit number ""
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
# than a definite `false` — the one raw-abort mode the `if !` guard above
# exists to avoid, here in a trigger gate. Builtins cannot be absent, so this
# parse always resolves and always reaches one of the emits below.
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
  emit number ""
  exit 0
fi

# The detector recognizes every /(pr|dev)flow:* standalone command; accept ONLY
# /prflow:implement here. A non-implement standalone command, or NO standalone
# command at all (the token was merely quoted in prose, blockquoted, indented, or
# fenced, or the fence was unbalanced), declines — this is the fence/bareness
# guard the heavy path previously lacked (issue #1032).
if [ "$cmd" != "/prflow:implement" ]; then
  echo "::warning::No STANDALONE /devflow:implement command in trigger text (a token merely quoted in prose, blockquoted, indented, or fenced does not trigger); skipping." >&2
  emit should_run false
  emit number ""
  exit 0
fi

# --- Authorization (cost control: agent mode runs for any actor) ------------
# Shared with resolve-command-trigger.sh — see scripts/authorize-actor.sh.
# shellcheck source=scripts/authorize-actor.sh
. "$(dirname "$0")/authorize-actor.sh"
authorize_actor   # sets $authorized and $deny_reason from ACTOR/ALLOWED_BOTS/REPO

# shellcheck disable=SC2154  # authorized/deny_reason are set by authorize_actor (sourced above)
if [ "$authorized" != "true" ]; then
  echo "::warning::/devflow:implement requested by '$actor' $deny_reason; skipping (cost control)." >&2
  emit should_run false
  emit number ""
  exit 0
fi

# --- Target number resolution -----------------------------------------------
# The detector already returned the explicit number on the matched standalone
# `/devflow:implement <n>` line (optional leading #), if any; else fall back to
# the issue the event is attached to.
number="$det_number"
[ -z "$number" ] && number="$context_number"

if ! [[ "$number" =~ ^[0-9]+$ ]]; then
  echo "::warning::Could not resolve an issue number for /devflow:implement; skipping." >&2
  emit should_run false
  emit number ""
  exit 0
fi

emit should_run true
emit number "$number"

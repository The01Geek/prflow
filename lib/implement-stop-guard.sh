#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# implement-stop-guard.sh — local-tier Stop-hook backstop that keeps an in-flight
# /devflow:implement run from ending its turn while its GitHub issue workpad still
# carries an INTERIM Status (any phase word other than Complete/Blocked).
#
# Wired as a second `Stop` hook command in .claude/settings.json, beside
# `lib/efficiency-trace.sh --persist`. Reads the Stop-hook JSON payload (which
# carries `session_id`) from stdin.
#
# FAIL-CLOSED/FAIL-OPEN DECISION MATRIX — every path below is EITHER the one
# documented block (exit 2, the Stop-hook blocking code; sentinel written) OR an
# allow (exit 0 + a stderr breadcrumb naming that specific arm):
#
#   allow  config-source.sh unsourceable   cannot resolve the repo root; nothing to guard
#   allow  GITHUB_ACTIONS set              cloud tier has its own stall backstop
#   allow  no implement-active-* marker    the fast path every ordinary session takes:
#                                          checked by a pure-bash glob, so it spawns no
#                                          interpreter and queries no workpad
#   allow  python3 unavailable             cannot parse the payload or read a workpad
#   allow  stdin unparseable / no usable   covers empty stdin, non-JSON, a non-object
#          session_id                      value, an absent/blank/non-string session_id,
#                                          and a session_id unsafe as a filename component
#                                          — none of them let the sentinel be safely keyed
#   allow  this session's sentinel exists  at-most-one-block-per-session bound
#   allow  workpad.py absent/unreadable    every marker kept: an unopenable helper is
#                                          an infrastructure fault, NOT an absent workpad
#   allow  sentinel write fails            a sentinel-less block could re-block forever
#   allow  marker suffix non-numeric       shape not understood; never queried, never deleted
#   allow  workpad.py status exits 1 or 3  the workpad could not be read (unreadable /
#          (or any other non-{0,2} code)   gh transport-auth); never block on that
#   heal   workpad.py status -> terminal   delete the marker (best-effort), keep scanning —
#                                          REGARDLESS of which session owns the marker
#   heal   workpad.py status exits 2       no workpad on that issue: stale marker, same heal
#   allow  marker owned by another session interim workpad, BUT the marker's first line is a
#                                          well-formed session id that differs from this stop's
#                                          session_id: another live session owns the run, and a
#                                          non-owner can never drive its workpad terminal — so
#                                          print an issue+status breadcrumb (the "a run may be
#                                          stuck" signal survives), write NO sentinel, and keep
#                                          scanning; never block a non-owner
#   BLOCK  workpad.py status -> interim    write the sentinel, print the instruction, exit 2 —
#                                          when the marker is owned by THIS session, OR carries
#                                          no usable identity (empty/blank/unreadable/malformed
#                                          first line, incl. today's zero-byte marker: absent
#                                          identity FAILS CLOSED, blocking exactly as before)
#
# A heal whose `rm` fails says so and leaves the marker; it never reports a deletion that
# did not happen, and the next Stop event simply retries the heal.
#
# MARKER OWNERSHIP (issue #1222). The marker's first line records the runner session id of the
# implement run that created it (written by scripts/write-run-marker.py, which Phase 1.3 invokes
# on the local tier), or is empty on a runner that supplies no session id. Ownership is only ever compared LIKE WITH
# LIKE: a marker counts as another session's only when BOTH its recorded first line AND this
# stop's payload session_id are non-empty and well-formed under the filename-safe charset check
# below — any other combination fails closed and blocks as today. Evidence the two values are the
# same value on this runner: Claude Code exports CLAUDE_CODE_SESSION_ID (the writer's source) and
# it is byte-identical to the Stop payload's session_id (this guard's key) — observed directly
# (CLAUDE_CODE_SESSION_ID matched an existing stop-guard-<id> sentinel filename; issue #1222).
# On a runner that supplies no session id the writer leaves an empty marker and this guard keeps
# its pre-#1222 presence-only behavior.
#
# Why the workpad.py existence check is load-bearing: `python3 <script>` itself exits 2 when
# it cannot open the script, and argparse exits 2 on any usage error — the SAME code
# workpad.py uses for "this issue has no workpad". Without the check, a missing or renamed
# helper would be read as "stale marker" and DELETE it, silently disabling this backstop for
# a live run. The check removes the missing-file path; a future argparse-usage drift is
# caught instead by the real-workpad.py tests in lib/test/run.sh, which pin the CLI shape.
#
# The FIRST interim marker blocks and exits; any markers after it in scan order are
# re-scanned on a later Stop event, so their self-heal is deferred, never lost.
#
# The guard carries no test-only environment override: lib/test/run.sh drives it
# inside a real, throwaway git-inited sandbox, so devflow_repo_root() resolves there
# with no backdoor in production code.

set -uo pipefail

_GUARD_DIR="$(cd "$(dirname "$0")" && pwd)"

breadcrumb() { printf 'devflow: implement-stop-guard: %s\n' "$1" >&2; }

# ARM ORDER IS A HOT-PATH CONTRACT, not a stylistic choice. This hook runs at the
# turn-end of EVERY session in this repo, almost all of which have no implement run
# in flight. So the arms are ordered cheapest-decisive-first, and the two `python3`
# forks (session-id parse, workpad status) sit BELOW the pure-bash marker glob: an
# ordinary session must exit having spawned no interpreter and made no network call.
# Do not hoist the session-id parse above the glob — its only consumer is the
# sentinel path, which is meaningless when no marker exists.

# Drain stdin before any exit path so the harness's writing end never sees EPIPE.
STDIN_JSON="$(cat)"

if [ -n "${GITHUB_ACTIONS:-}" ]; then
  breadcrumb "GITHUB_ACTIONS is set (cloud tier, which has its own stall backstop) — allowing stop"
  exit 0
fi

# config-source.sh owns devflow_repo_root(). It sets `-euo pipefail` for its own
# sourcing chain, and a Stop hook must never inherit `-e`: any stray non-zero
# sub-command would abort mid-script and exit non-zero, which the hook contract
# reads as a BLOCK. Source it inside an `if` (errexit is suppressed there) and drop
# `-e` again immediately after.
# shellcheck source=config-source.sh
if ! . "$_GUARD_DIR/config-source.sh"; then
  set +e
  breadcrumb "could not source config-source.sh — allowing stop (fail open)"
  exit 0
fi
set +e

ROOT="$(devflow_repo_root)"
TMPDIR_DEVFLOW="$ROOT/.prflow/tmp"

# nullglob so an unmatched pattern yields an empty array rather than the literal
# pattern as a phantom filename.
shopt -s nullglob
MARKERS=("$TMPDIR_DEVFLOW"/implement-active-*)
shopt -u nullglob
if [ "${#MARKERS[@]}" -eq 0 ]; then
  breadcrumb "no .prflow/tmp/implement-active-* marker present — no implement run to guard, allowing stop"
  exit 0
fi

# A python3-less host gets its own breadcrumb: folding it into the parse arm below would
# point an operator at the hook payload when the real cause is a missing interpreter.
if ! command -v python3 >/dev/null 2>&1; then
  breadcrumb "python3 not found — cannot parse the hook payload or read a workpad, allowing stop (fail open)"
  exit 0
fi

# One python3 call covers every remaining "cannot key the sentinel" shape.
SESSION_ID="$(printf '%s' "$STDIN_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
sid = data.get("session_id") if isinstance(data, dict) else None
if not isinstance(sid, str) or not sid.strip():
    sys.exit(1)
sys.stdout.write(sid.strip())
' 2>/dev/null)"
# The session id becomes a filename component, so anything outside this charset —
# a path separator above all — is rejected rather than sanitized.
case "$SESSION_ID" in
  '' | *[!A-Za-z0-9._-]*)
    breadcrumb "stdin JSON was unparseable, or carried no usable session_id — allowing stop (fail open)"
    exit 0
    ;;
esac

SENTINEL="$TMPDIR_DEVFLOW/stop-guard-$SESSION_ID"
if [ -e "$SENTINEL" ]; then
  breadcrumb "this session was already blocked once (sentinel $SENTINEL exists) — allowing stop"
  exit 0
fi

WORKPAD_PY="$ROOT/scripts/workpad.py"

# See the header note: `python3 <script>` exits 2 on an unopenable script, which is exactly
# the code workpad.py uses for "no workpad on this issue" — the one arm that DELETES state.
# Refuse to query at all rather than let an unopenable helper heal away a live run's marker.
# `-r` as well as `-f`: a present-but-unreadable regular file passes `-f` yet still makes
# python3 exit 2, so testing existence alone would accept an input the consumer rejects.
if [ ! -f "$WORKPAD_PY" ] || [ ! -r "$WORKPAD_PY" ]; then
  breadcrumb "$WORKPAD_PY not found or not readable — cannot read any workpad, keeping every marker, allowing stop (fail open)"
  exit 0
fi

# heal_marker PATH ISSUE REASON — delete a marker and report honestly. A breadcrumb claiming
# "deleted" for a marker still on disk would report success for work that did not happen, so
# the outcome is read back from the filesystem rather than trusted from `rm`'s exit status
# (`rm -f` reports success for an already-absent target, and a read-only `.prflow/tmp` is a
# reachable failure the chmod-555 test exercises). Leaving the marker is harmless: the next
# Stop event re-reads the same terminal workpad and retries the heal.
heal_marker() {
  if rm -f "$1" 2>/dev/null && [ ! -e "$1" ]; then
    breadcrumb "issue #$2 $3 — deleted stale marker $1, continuing"
  else
    breadcrumb "issue #$2 $3 — but marker $1 could NOT be deleted (it remains on disk); continuing"
  fi
}

# `${MARKERS[@]+…}` because bash 3.2 (stock macOS) treats "${arr[@]}" on an EMPTY array as
# an unbound variable under `set -u` and aborts. The count guard above already returns
# early, so this only keeps a future reordering from detonating on the oldest supported bash.
for marker in ${MARKERS[@]+"${MARKERS[@]}"}; do
  [ -e "$marker" ] || continue   # concurrently self-healed by another session
  issue="${marker##*implement-active-}"
  case "$issue" in
    '' | *[!0-9]*)
      breadcrumb "marker $marker has a non-numeric issue suffix — skipping it, leaving it on disk"
      continue
      ;;
  esac

  # stdout only: workpad.py's own stderr flows through to ours rather than being
  # swallowed, so an unreadable-workpad cause stays visible.
  status_out="$(python3 "$WORKPAD_PY" status "$issue")"
  status_rc=$?

  case "$status_rc" in
    0)
      read -r status_class _ status_word <<<"$status_out"
      # Any terminal-family class heals the marker — the run has reached a
      # decided end. Since issue #1025 `workpad.py status` names each terminal
      # glyph (complete/blocked/failed/cancelled) instead of collapsing them to
      # `terminal`; the bare `terminal` token is retained as a legacy alias so an
      # un-upgraded workpad.py still heals here. Only 'interim' blocks.
      case "$status_class" in
        complete|blocked|failed|cancelled|terminal)
          heal_marker "$marker" "$issue" "workpad Status is terminal ($status_word)"
          continue
          ;;
      esac
      if [ "$status_class" != "interim" ]; then
        breadcrumb "issue #$issue: workpad.py status printed an unrecognized class '$status_class' — keeping marker, allowing stop (fail open)"
        continue
      fi
      # Interim: the one blocking arm — but first, marker ownership (issue #1222).
      # A marker owned by ANOTHER live session must not block this one: a non-owner
      # can never drive that run's workpad to a terminal Status, so the block is pure
      # noise that trains the operator to ignore the guard. Read the marker's first
      # line; the heal arms above never need it, so this read is confined to here.
      # An unreadable marker leaves MARKER_OWNER empty (the `-r` guard both silences
      # the redirect error and, together with the charset check, fails closed).
      MARKER_OWNER=""
      if [ -r "$marker" ]; then
        IFS= read -r MARKER_OWNER < "$marker" 2>/dev/null || true
      fi
      # Fail closed on any identity that is not usable like-with-like: an empty/blank
      # first line, or one carrying a char outside the filename-safe set, is treated as
      # NO owner and blocks as today (this is where a zero-byte legacy marker lands).
      case "$MARKER_OWNER" in
        '' | *[!A-Za-z0-9._-]*) MARKER_OWNER="" ;;
      esac
      # SESSION_ID is already non-empty and well-formed (validated above), so a
      # non-empty MARKER_OWNER here means both operands are usable — compare them.
      if [ -n "$MARKER_OWNER" ] && [ "$MARKER_OWNER" != "$SESSION_ID" ]; then
        breadcrumb "issue #$issue: workpad Status is interim ($status_word), but marker $marker is owned by another session ($MARKER_OWNER, not this stop's $SESSION_ID) — that session owns the run and only it can finalize; not blocking this stop (a run may still be stuck — see issue #$issue)"
        continue
      fi
      # Owned by THIS session, or the marker carries no usable identity: block.
      # A block without a sentinel could re-block this session on every subsequent
      # stop, so a failed sentinel write allows.
      if ! { mkdir -p "$TMPDIR_DEVFLOW" 2>/dev/null && : > "$SENTINEL" 2>/dev/null; }; then
        breadcrumb "could not write the sentinel $SENTINEL — allowing stop (fail open; a sentinel-less block could not be bounded to one)"
        exit 0
      fi
      {
        printf 'devflow: implement-stop-guard: BLOCKING this stop — issue #%s'"'"'s workpad Status is still "%s" (interim, not Complete or Blocked).\n' \
          "$issue" "$status_word"
        printf 'devflow: implement-stop-guard: If you are the /devflow:implement run for issue #%s, return to the phase that owns the remaining work and drive the workpad Status to a terminal value before ending your turn.\n' \
          "$issue"
        printf 'devflow: implement-stop-guard: If you are any other session, state that the PRFlow terminal-status guard blocked this stop and simply end your turn again — the sentinel admits the second stop.\n'
      } >&2
      exit 2
      ;;
    2)
      heal_marker "$marker" "$issue" "has no workpad (workpad.py status exited 2), so the marker was stale"
      continue
      ;;
    *)
      breadcrumb "issue #$issue: workpad.py status exited $status_rc — could not read the workpad, keeping marker, allowing stop (fail open)"
      continue
      ;;
  esac
done

breadcrumb "scanned every implement-active marker, none interim — allowing stop"
exit 0

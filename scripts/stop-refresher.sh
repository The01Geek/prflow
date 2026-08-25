#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# stop-refresher.sh — retire the detached credential refresher and surface its
# health at the job level (issue #487). Extracted from the workflows' inline
# `Stop credential refresher` step so the branch selection and the composed
# user-facing `::warning::` are drivable by the test suite (the CLAUDE.md
# inline-shell-extraction convention; scripts/describe-denial-count.sh precedent).
#
# It (a) kills the refresher by the pidfile the loop wrote, (b) tails the detached
# refresher's log into the step output — the refresher's own `::warning::` lines are
# INERT in a background process (GitHub Actions interprets `::warning::` only on a
# live step's stdout) — and (c) re-emits ONE real, live `::warning::` when the
# refresher was DEFEATED, so a run that silently lost its credentials is visible in
# the job UI without log archaeology.
#
# "Defeated" is decided honestly, avoiding the two failure modes a naive
# grep-for-any-failure gate has:
#   * never-started / crashed-before-first-cycle → the pidfile is ABSENT (the loop
#     writes it at startup), so a missing pidfile IS the defeat signal — this
#     catches a missing/unparseable vendored script (whose `bash: … .sh:` error the
#     warn-prefix grep would miss) and an early crash.
#   * died mid-run → the pidfile EXISTS but its pid is no longer running (`kill -0`
#     fails; same-user runner processes, so a liveness probe never EPERMs): a
#     refresher that logged `cycle OK` and then died (OOM-killed, reaped, crashed)
#     left the credentials going stale from that moment — defeat, regardless of the
#     last log line. An EMPTY pidfile is the same unverifiable-liveness class
#     (the loop writes its PID at startup, so an empty file is anomalous) — defeat.
#   * sustained vs. recovered failure → read the LAST `refresh-app-credentials:`
#     line: `cycle OK` means the most recent cycle refreshed the credentials (a
#     transient the backoff recovered from — do NOT warn); a `::warning::` last line
#     means the most recent cycle failed (a real stale-token risk — warn).
#
# Best-effort: ALWAYS exits 0 (a stop hiccup never fails the job).
#
# Env (all optional; defaults match the refresher + the workflow):
#   RUNNER_TEMP                 base dir for the default pidfile/log paths
#   DEVFLOW_REFRESH_PIDFILE     pidfile path (default $RUNNER_TEMP/devflow-refresh.pid)
#   DEVFLOW_REFRESH_LOG         log path     (default $RUNNER_TEMP/devflow-refresh.log)
#   DEVFLOW_REFRESH_STARTED     the Start step's `outcome` (success/failure/skipped/
#                               cancelled). An absent pidfile only means "defeated"
#                               when the Start step actually RAN (outcome success OR
#                               failure) — otherwise (skipped/cancelled: the job
#                               aborted upstream before the success()-gated Start
#                               step) a missing pidfile is EXPECTED, not a defeat, and
#                               warning would misattribute an unrelated early failure
#                               to the refresher.
#   DEVFLOW_REFRESH_SELFTEST_FAILED  marker written by the Start step's pre-launch
#                               self-test (issue #1882). When present, the job's
#                               failure is attributed to the signing fault rather
#                               than a never-started / stale-credential defeat.
#   DEVFLOW_REFRESH_REAP_GLOB   glob of job-scoped pidfiles for the cross-job reaper.
#                               When set, used VERBATIM (no conversion). When unset,
#                               derived from RUNNER_TEMP normalized to the running
#                               shell's POSIX form (issue #1925), reaping nothing when
#                               that value cannot be expressed as a POSIX glob root.
#   DEVFLOW_REFRESH_IDENTITY_SOURCE  reaper identity source: `auto` (default: /proc,
#                               then ps), `ps` (force the portable fallback), or
#                               `none` (force the unverifiable-pid skip). Test seam —
#                               no workflow sets it; the two non-auto arms are
#                               otherwise unreachable on a Linux runner.

set -uo pipefail

PIDFILE="${DEVFLOW_REFRESH_PIDFILE:-${RUNNER_TEMP:-/tmp}/devflow-refresh.pid}"
# The LOG path is job-scoped and passed EXPLICITLY from the Start step (issue
# #1882): its producer is the workflow redirect and its consumer is this default,
# two separately-upgrading artifacts, so neither infers the other's literal.
LOG="${DEVFLOW_REFRESH_LOG:-${RUNNER_TEMP:-/tmp}/devflow-refresh.log}"
STARTED="${DEVFLOW_REFRESH_STARTED:-success}"   # default success: a direct/test run has no gate
SELFTEST_FAILED="${DEVFLOW_REFRESH_SELFTEST_FAILED:-}"

# Ordered BEFORE the self-test attribution below, which exits 0: a job whose self-test
# failed still shares the runner with a prior job's orphan, and reaping is exactly the
# duty that must not be skipped on the self-hosted hosts this change targets.
# Cross-job reaper (issue #1882): job-scoping the pidfile removed the accidental
# cross-job kill a shared pidfile used to provide, so retire any OTHER job's
# refresher still looping on this runner — an orphan whose self-termination may
# have failed must not keep holding a live repository-write token. Every pidfile
# in the glob that is not this job's own is another job's by construction, so the
# reap decision is that name inequality plus the liveness and identity checks
# below — never a read of the orphan's job pointer.
if [ -n "${DEVFLOW_REFRESH_REAP_GLOB:-}" ]; then
  # An explicit pattern is authoritative and used exactly as given, with NO
  # conversion (issue #1925): the caller already chose the form its shell expresses.
  REAP_GLOB="$DEVFLOW_REFRESH_REAP_GLOB"
else
  # Normalize the derived temp dir to the running shell's POSIX form FIRST (issue
  # #1925): an unquoted glob consumes the backslashes of a Windows-form $RUNNER_TEMP,
  # so the raw value names nothing and the reaper silently sweeps zero files. Reap
  # nothing (empty pattern → the loop below is a no-op) rather than sweep the wrong
  # directory when the value cannot be brought to a POSIX glob root.
  _reap_base="${RUNNER_TEMP:-/tmp}"
  _reap_lib="$(dirname "${BASH_SOURCE[0]}")/../lib/normalize-path.sh"
  # shellcheck source=../lib/normalize-path.sh
  if [ -r "$_reap_lib" ] && . "$_reap_lib" 2>/dev/null && command -v devflow_normalize_path >/dev/null 2>&1; then
    _reap_base="$(devflow_normalize_path "$_reap_base")"
  else
    # The normalizer decides which directory is swept, so its absence is not a value
    # to guess past — reap nothing rather than sweep from an unnormalized value.
    echo "skipped cross-job orphan reap: could not source the path normalizer ($_reap_lib) to establish the reap directory from RUNNER_TEMP '${RUNNER_TEMP:-/tmp}' — nothing signalled (fail-safe)"
    _reap_base=""
  fi
  case "$_reap_base" in
    "") REAP_GLOB="" ;;
    # A drive-letter path with no WSL/MSYS signal, or a UNC path, survives
    # normalization still carrying a colon-drive or backslashes an unquoted glob
    # cannot express — refuse it rather than sweep nothing silently.
    [A-Za-z]:/*|[A-Za-z]:\\*|*\\*)
      echo "skipped cross-job orphan reap: RUNNER_TEMP '${RUNNER_TEMP:-/tmp}' could not be normalized into a POSIX glob root (resolved to '$_reap_base') — nothing signalled (fail-safe)"
      REAP_GLOB="" ;;
    *) REAP_GLOB="$_reap_base/devflow-refresh-*.pid" ;;
  esac
fi
# Intentional glob + word-split of the reap pattern.
# shellcheck disable=SC2086
for _rpf in $REAP_GLOB; do
  [ -f "$_rpf" ] || continue
  [ "$_rpf" = "$PIDFILE" ] && continue
  # Read the pid with the `read` BUILTIN, never `cat`: cat is not preflight-guaranteed,
  # and on a host lacking it every pidfile would read empty and be unlinked below as
  # stale — silently retiring the record of a LIVE orphan instead of signalling it.
  _ropid=""
  read -r _ropid 2>/dev/null < "$_rpf" || :
  # A stale pidfile (empty, or a pid that is no longer alive) is retired so no later
  # teardown re-consults it.
  if [ -z "$_ropid" ] || ! kill -0 "$_ropid" 2>/dev/null; then
    rm -f "$_rpf" 2>/dev/null || true
    continue
  fi
  # Confirm the LIVE pid is actually a refresher before signalling it. On a
  # long-lived self-hosted runner a dead refresher's pid can be recycled by an
  # unrelated process, so a blind kill would hit the wrong one. /proc (Linux and
  # MSYS2/Git-Bash, the native-Windows target) is the primary identity source and
  # `ps` the macOS/BSD fallback; a host that can establish NEITHER leaves _rcmd
  # empty and takes the fail-safe skip below — never signal an unverifiable pid.
  _rcmd=""
  case "${DEVFLOW_REFRESH_IDENTITY_SOURCE:-auto}" in
    # Forcing `ps`/`none` is how the two non-/proc arms get driven at all: CI runs on
    # Linux, where /proc is always readable, so without this seam neither the portable
    # fallback nor the unverifiable-pid skip is ever executed by a test.
    none) : ;;
    ps) command -v ps >/dev/null 2>&1 && _rcmd="$(ps -o args= -p "$_ropid" 2>/dev/null || true)" ;;
    *)
      if [ -r "/proc/$_ropid/cmdline" ]; then
        # bash strips the NUL separators, so the args concatenate. A host without `cat`
        # leaves _rcmd empty here, so the ps fall-through below is unconditional —
        # committing to /proc would make the reaper inert on a cat-less host.
        _rcmd="$(cat "/proc/$_ropid/cmdline" 2>/dev/null || true)"
      fi
      if [ -z "$_rcmd" ] && command -v ps >/dev/null 2>&1; then
        _rcmd="$(ps -o args= -p "$_ropid" 2>/dev/null || true)"
      fi ;;
  esac
  case "$_rcmd" in
    *refresh-app-credentials.sh*)
      # Gate the "reaped" breadcrumb on the kill actually succeeding — otherwise the
      # log asserts a retirement (EPERM, or the process exited in the window) that
      # did not happen. Unlink the pidfile only after a confirmed signal.
      if kill "$_ropid" 2>/dev/null; then
        rm -f "$_rpf" 2>/dev/null || true
        echo "reaped an orphaned credential refresher (pid $_ropid) from a prior job on this runner (pidfile $_rpf)"
      else
        echo "could not signal orphaned refresher pid $_ropid (pidfile $_rpf) — left for a later teardown"
      fi ;;
    "")
      echo "skipped orphan reap for pid $_ropid (pidfile $_rpf): its command line could not be established, so it cannot be confirmed a refresher (fail-safe: not signalled)" ;;
    *)
      echo "skipped orphan reap for pid $_ropid (pidfile $_rpf): the live process is not a credential refresher (pid reused); leaving the stale pidfile for review" ;;
  esac
done

# Self-test attribution (issue #1882): the Start step's synchronous pre-launch
# self-test failed the job BEFORE the detached launch, so the refresher never
# started by design. Name the signing fault instead of the did-not-start defeat
# and its stale-token impact clause — the credentials never went stale past the
# hour, the job failed at the signing gate.
if [ -n "$SELFTEST_FAILED" ] && [ -f "$SELFTEST_FAILED" ]; then
  echo "credential-refresher self-test failed before the detached launch: $(cat "$SELFTEST_FAILED" 2>/dev/null)"
  echo "::warning::the credential-refresher self-test failed the job (a signing fault on this host); the refresher was deliberately not started — this is a signing fault, not a stale-credential defeat"
  exit 0
fi

defeated=no
reason=""
# The impact clause of the final defeat warning. Defaults to BOTH surfaces (the common
# defeat cases leave git push AND gh calls on a stale token), but the surface-2-only
# divergence case below narrows it — there, git push (surface 1) stayed fresh and only the
# gh token file (surface 2) is stale, so claiming push may have used a stale token would
# misdirect the operator (PR #491 shadow review).
impact="git push / gh calls past ~60 min may have used a stale token"

if [ -f "$PIDFILE" ]; then
  # Same builtin-not-`cat` rule as the reaper below: a host without cat would read
  # every pidfile empty and report a spurious defeat instead of this job's real state.
  pid=""
  read -r pid 2>/dev/null < "$PIDFILE" || :
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    # Briefly wait for the signalled process to actually exit before tailing its log, so
    # an in-flight cycle's final lines land in the tail rather than racing it (no
    # correctness impact on the defeat decision — that already used the PRE-kill liveness
    # probe + last log line). Bounded (~5s) so a wedged process never stalls this
    # best-effort stop; the refresher's TERM trap exits it promptly in practice.
    _wait=0
    while [ "$_wait" -lt 50 ] && kill -0 "$pid" 2>/dev/null; do
      sleep 0.1
      _wait=$((_wait + 1))
    done
    echo "signalled credential refresher (pid $pid)"
  elif [ -n "$pid" ]; then
    # Pidfile present but the process is GONE: the refresher died after startup
    # (OOM-killed, reaped, crashed). Its last logged `cycle OK` proves nothing about
    # the window between that cycle and now — the credentials have been going stale
    # since the death. Genuine defeat; do NOT let a stale `cycle OK` mask it below.
    echo "refresher pidfile present but pid $pid is not running"
    defeated=yes
    reason="the refresher process died before job end (pidfile present, process gone)"
  else
    # Same unverifiable-liveness class: the loop writes its PID at startup, so an
    # empty pidfile is anomalous and the refresher's health cannot be confirmed.
    echo "refresher pidfile '$PIDFILE' is empty; nothing to signal"
    defeated=yes
    reason="the refresher pidfile is empty, so its health could not be verified"
  fi
elif [ "$STARTED" != skipped ] && [ "$STARTED" != cancelled ]; then
  # The Start step actually RAN (success OR failure — a hard Start-step failure means
  # the refresher genuinely never started) yet no pidfile exists → the refresher never
  # started or crashed before writing it (e.g. a missing/unparseable vendored script,
  # whose `bash: … .sh:` error the warn-prefix grep would miss). Genuine defeat. Keying
  # on "did it run" (not "did it succeed") is deliberate: a ran-and-failed Start is a
  # real never-started defeat, not an expected-absent-pidfile case.
  echo "no refresher pidfile at $PIDFILE"
  defeated=yes
  reason="the refresher did not start or crashed before writing its pidfile"
else
  # The Start step did NOT run (skipped/cancelled — the job aborted before reaching it),
  # so the missing pidfile is expected — do not misattribute an unrelated upstream
  # failure to the refresher.
  echo "refresher Start step did not run (outcome='$STARTED'); missing pidfile is expected, not a defeat"
fi

if [ -f "$LOG" ]; then
  echo "--- credential refresher log (tail) ---"
  tail -n 40 "$LOG" 2>/dev/null || true
  # Only consult the log for the sustained-vs-recovered decision when nothing has
  # decided defeat above (an absent pidfile, a dead pid, or an empty pidfile is a
  # more fundamental cause than any log line — a stale `cycle OK` must not mask it).
  # The `grep`/`tail` below derive the value that GATES the user-facing defeat
  # warning (guard-class-2), and neither is a lib/preflight.sh-guaranteed tool. On
  # a runner missing one this now FAILS CLOSED (issue #1882): treat the refresher
  # as defeated and warn, rather than emptying `last` into the do-nothing arm and
  # emitting nothing on exactly the non-Linux host class this change targets.
  if [ "$defeated" = no ]; then
    if ! command -v grep >/dev/null 2>&1 || ! command -v tail >/dev/null 2>&1; then
      defeated=yes
      reason="the text tools that read the refresher log (grep/tail) are unavailable, so the refresher's health could not be verified"
    else
    last="$(grep -E 'refresh-app-credentials:' "$LOG" 2>/dev/null | tail -n1)"
    case "$last" in
      *"cycle OK"*) : ;;                    # most recent cycle succeeded → creds fresh
      # Surface-2-only divergence: the cycle refreshed git push (surface 1) but failed to
      # write the gh token file (surface 2). This IS a defeat (the gh surface is stale until
      # the backoff re-converges), but push stayed fresh — so narrow the impact clause rather
      # than emit the generic "git push may be stale" (must precede the generic ::warning::
      # arm, which the divergence line also matches). The phrase is run_cycle's own.
      *"(surface 2) is now stale"*)
        defeated=yes
        reason="the most recent cycle left the gh token file (surface 2) stale while git push (surface 1) stayed fresh"
        impact="agent-side gh calls past ~60 min may have used a stale token (git push stayed fresh)" ;;
      *"::warning::"*) defeated=yes; reason="the most recent refresh cycle failed" ;;
      *) : ;;                               # no cycle outcome logged yet → nothing to assert
    esac
    fi
  fi
fi

if [ "$defeated" = yes ]; then
  echo "::warning::credential refresher may not have kept credentials fresh ($reason); $impact — see the refresher log tail above"
fi

exit 0

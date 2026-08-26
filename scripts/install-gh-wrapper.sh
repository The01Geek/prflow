#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# install-gh-wrapper.sh — the single checked-in gh-fresh wrapper installer that
# both writer workflows (devflow-implement.yml's claude job, devflow.yml's
# command job) invoke, replacing two byte-identical inline YAML step bodies
# (issue #533).
#
# What it installs: copies scripts/gh-fresh.sh into a wrapper directory as
# `gh`, records the job-start token's sha256 fingerprint (mode 0600 wherever
# POSIX mode bits can express it — not on a native-Windows python3, where the
# gate relaxes with a stderr breadcrumb, issue #690) for the
# wrapper's ambient-vs-chosen discrimination (issue #487), publishes the real
# gh's absolute path as DEVFLOW_GH_REAL via GITHUB_ENV, and prepends the
# wrapper directory to later steps' PATH via GITHUB_PATH.
#
# It deliberately publishes NO process-global DEVFLOW_GH (issue #533):
# GITHUB_ENV values persist into every later job step, and PRFlow's resolvers
# treat a non-empty DEVFLOW_GH as the strongest explicit override — so a
# workflow-level export leaks into the repository test process, where it
# outranks the PATH stubs the suite's fixtures install. Wrapper selection is
# PATH-scoped; DEVFLOW_GH stays an explicit caller/test injection seam.
#
# The fingerprint is computed with the preflight-guaranteed python3 hashlib —
# never sha256sum/shasum/awk, which the runner PATH does not guarantee and
# whose silent absence would ship an empty fingerprint (the CLAUDE.md
# guard-class-2 rule: a value that decides an emitted result must not be
# derived through a non-preflight PATH tool). The token is read from the
# APP_TOKEN environment value and piped via stdin; it never appears on an argv.
#
# Fail-closed contract: exactly seven setup outputs are validated in order,
# and the FIRST failure exits 1 with a diagnostic naming that output
# ("install-gh-wrapper: output N/7 FAILED: ... (slug)"), so the job stops
# before the agent ever runs against a half-installed wrapper. An output may
# carry more than one failure slug — output 5 distinguishes
# fingerprint-compute / fingerprint-nonempty / fingerprint-mode — and
# lib/test/run.sh pins the slugs literally (the AC22 umask mutation proof
# depends on fingerprint-mode specifically), so do not "normalize" them.
#
# Env contract:
#   APP_TOKEN                    required — the minted App token to fingerprint
#   GITHUB_ENV / GITHUB_PATH     required — the Actions environment files
#   RUNNER_TEMP                  required unless both path overrides are given
#   DEVFLOW_GH_WRAPDIR           override; default $RUNNER_TEMP/devflow-gh-bin
#   DEVFLOW_GH_FINGERPRINT_FILE  override; default $RUNNER_TEMP/devflow-gh-fingerprint
#                                (the same default gh-fresh.sh reads — a coupled
#                                default pinned by lib/test/run.sh)
#   DEVFLOW_GH_SOURCE_SH         override for the gh-fresh.sh source path

set -uo pipefail

fail() { printf 'install-gh-wrapper: %s\n' "$1" >&2; exit 1; }

# output 1/7 — an executable real gh, resolved BEFORE the wrapper dir reaches
# PATH (a name-based lookup after the prepend would recurse into the wrapper).
# Deliberately a bare `command -v gh`, NOT the lib/resolve-gh.sh resolver: the
# resolver's DEVFLOW_GH override outranks PATH by design, and honoring it here
# could capture the very wrapper this script installs (or any test override) as
# "the real gh" — the recursion this absolute capture exists to prevent. Tests
# steer this lookup with a PATH stub, the same seam production uses.
REAL_GH="$(command -v gh 2>/dev/null || true)"
# The [ -x ] half is defense-in-depth with no drivable test seam: bash's PATH
# search returns only executable regular files (a non-executable file or a
# directory named gh is skipped, rc 1 — verified empirically), so this arm can
# fire only on a permission flip between resolution and test.
[ -n "$REAL_GH" ] && [ -x "$REAL_GH" ] \
  || fail "output 1/7 FAILED: no executable real gh resolved (real-gh-resolve)"

# output 2/7 — a readable wrapper source. Vendored-or-repo fallback: a consumer
# checkout carries only the vendored copy; the source repo carries scripts/.
SRC="${DEVFLOW_GH_SOURCE_SH:-}"
if [ -z "$SRC" ]; then
  if [ -f .prflow/vendor/prflow/scripts/gh-fresh.sh ]; then SRC=.prflow/vendor/prflow/scripts/gh-fresh.sh
  elif [ -f scripts/gh-fresh.sh ]; then SRC=scripts/gh-fresh.sh
  fi
fi
[ -n "$SRC" ] && [ -r "$SRC" ] \
  || fail "output 2/7 FAILED: wrapper source gh-fresh.sh is not readable at the vendored or repo-relative path (wrapper-source-read)"

# output 3/7 — a creatable, writable wrapper directory.
if [ -z "${DEVFLOW_GH_WRAPDIR:-}" ] && [ -z "${RUNNER_TEMP:-}" ]; then
  fail "output 3/7 FAILED: RUNNER_TEMP is unset and no DEVFLOW_GH_WRAPDIR override was given (wrapdir-create)"
fi
WRAPDIR="${DEVFLOW_GH_WRAPDIR:-$RUNNER_TEMP/devflow-gh-bin}"
mkdir -p "$WRAPDIR" && [ -d "$WRAPDIR" ] && [ -w "$WRAPDIR" ] \
  || fail "output 3/7 FAILED: wrapper dir $WRAPDIR could not be created or is not writable (wrapdir-create)"

# output 4/7 — a successful copy carrying the executable bit. The regular-file
# check matters: `cp` into a directory that happens to occupy $WRAPDIR/gh would
# "succeed" while leaving no wrapper at the path later steps invoke.
cp "$SRC" "$WRAPDIR/gh" && chmod +x "$WRAPDIR/gh" \
  && [ -f "$WRAPDIR/gh" ] && [ -x "$WRAPDIR/gh" ] \
  || fail "output 4/7 FAILED: copying $SRC to $WRAPDIR/gh (or chmod +x) did not produce an executable wrapper file (wrapper-copy-exec)"

# output 5/7 — a non-empty job-start token fingerprint, mode-0600 on every host
# whose python3 reports a POSIX platform; on a native-Windows python3 (os.name
# == 'nt') mode bits cannot express that guarantee, so the mode assertion
# relaxes there and records on stderr that it could not be established (issue
# #690). Hashed with the preflight-guaranteed python3 hashlib (token via stdin,
# never argv).
[ -n "${APP_TOKEN:-}" ] \
  || fail "output 5/7 FAILED: APP_TOKEN is empty or unset — no token to fingerprint (fingerprint-compute)"
if [ -z "${DEVFLOW_GH_FINGERPRINT_FILE:-}" ] && [ -z "${RUNNER_TEMP:-}" ]; then
  fail "output 5/7 FAILED: RUNNER_TEMP is unset and no DEVFLOW_GH_FINGERPRINT_FILE override was given (fingerprint-compute)"
fi
FINGERPRINT_FILE="${DEVFLOW_GH_FINGERPRINT_FILE:-$RUNNER_TEMP/devflow-gh-fingerprint}"
( umask 077
  printf '%s' "$APP_TOKEN" \
    | python3 -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' \
    > "$FINGERPRINT_FILE"
) \
  || fail "output 5/7 FAILED: the python3 hashlib fingerprint computation errored (fingerprint-compute)"
[ -s "$FINGERPRINT_FILE" ] \
  || fail "output 5/7 FAILED: fingerprint file $FINGERPRINT_FILE is empty after the write (fingerprint-nonempty)"
# Mode check via python3 too (stat's -c/-f flags diverge GNU/BSD and stat is not
# preflight-guaranteed); an unreadable mode fails CLOSED with the same slug.
#
# The platform token and the mode value come from a SINGLE python3 invocation
# reading a SINGLE os.stat result, so the decision and the measurement can never
# be attributed to two different interpreters (issue #690). On a native-Windows
# CPython (os.name == 'nt') st_mode's permission bits are synthesized from the
# FILE_ATTRIBUTE_READONLY bit alone, so 600 is not a reachable value there and
# the strict comparison would reject every run — the gate relaxes on that
# platform and says so on stderr rather than asserting a guarantee it did not
# establish. os.chmod cannot repair it either (Windows honors only the
# read-only flag), which is why no chmod is introduced on this path: the
# umask 077 above stays the sole producer of the file's mode, keeping the
# suite's umask-mutation proof meaningful.
_fpcap="$(python3 -c 'import os,sys; print(os.name, oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])' "$FINGERPRINT_FILE" 2>/dev/null || true)"
# Split with bash builtins ONLY. Routing a security gate's verdict through a
# non-preflight PATH tool (the CLAUDE.md guard-class-2 rule) would empty the
# platform token on a host missing that tool and, because the relaxed arm is an
# allowlist test, silently re-select the strict arm on Windows — restoring the
# bug. The mode expansion deliberately keeps ALL trailing content beyond the
# first space, rather than silently discarding it, so a polluted capture is
# rejected along either of the routes below.
#
# Route one — the pollution leaves the mode field non-octal. A capture carrying
# an extra space-separated field lands here, and so does a multi-line capture
# (a shim printing a notice to stdout before the value), whose newline the mode
# field then carries. The octal test fails and the strict comparison runs.
#
# Route two — the pollution instead displaces the platform token while leaving
# a clean octal mode that is not the owner-only 600. The mode is octal, so the
# first route does not catch it; the platform-equality test then fails to match
# the displaced token and the strict comparison runs anyway.
#
# The one shape that passes is a space-free notice sitting ahead of a genuine
# owner-only 600: it takes the FIRST arm, on the measured mode value alone.
# That is safe, because the measured mode IS the guarantee here — the platform
# token is consulted only when the mode itself cannot supply one. So no blanket
# "every polluted capture is caught" is claimed: the suite pins that passing
# shape, and a stronger claim here would contradict a green assertion.
_fpos="${_fpcap%% *}"
_fpmode="${_fpcap#* }"
[ "$_fpcap" != "$_fpmode" ] || _fpmode=""   # no space in the capture => no mode field at all
# Non-empty AND solely octal digits, matching the shape oct(...)[2:] emits. The
# emptiness arm is load-bearing, not redundant: the bare glob *[!0-7]* is FALSE
# for the empty string, so an octal-shape test alone would send an absent mode
# field down the relaxed arm.
case "$_fpmode" in
  ''|*[!0-7]*) _fpmode_octal=no ;;
  *)           _fpmode_octal=yes ;;
esac
if [ "$_fpmode" = "600" ]; then
  :   # the owner-only guarantee is established; every platform passes on this value
elif [ "$_fpos" = "nt" ] && [ "$_fpmode_octal" = yes ]; then
  # Equality against the literal `nt`, NEVER a negated test against `posix`: a
  # negation would admit the EMPTY token an unreadable os.stat leaves behind,
  # turning the fail-closed unreadable-mode arm into a silent pass everywhere.
  #
  # This arm accepts ANY octal mode under `nt`, deliberately and with no value
  # floor: on that platform st_mode is synthesized from FILE_ATTRIBUTE_READONLY
  # alone, so the number carries no confidentiality meaning and a floor would
  # only re-break Windows the way the unconditional 600 comparison did. Do not
  # "helpfully" add one — the breadcrumb names the observed value instead.
  #
  # A plain stderr line is invisible in the Actions run summary, and this is a
  # security guarantee going unestablished, so under Actions it is ALSO emitted
  # as a ::warning:: annotation. The detail line keeps its bare
  # `install-gh-wrapper:` prefix on every tier (the seven-output diagnostic
  # vocabulary), so a local run gets exactly one clean line.
  [ -z "${GITHUB_ACTIONS:-}" ] \
    || echo "::warning::install-gh-wrapper: the owner-only (0600) mode guarantee for the token fingerprint file could not be established on this platform — see the install-gh-wrapper: detail line below" >&2
  echo "install-gh-wrapper: the owner-only (0600) mode guarantee could not be established for fingerprint file $FINGERPRINT_FILE on this platform (python3 reports os.name=nt, where POSIX mode bits are not expressible); observed (platform-synthesized) mode $_fpmode. Access to that file is left to whatever the filesystem's ACLs provide, which this script neither sets nor verifies." >&2
else
  fail "output 5/7 FAILED: fingerprint file $FINGERPRINT_FILE is mode ${_fpmode:-unreadable}, not 0600 (fingerprint-mode)"
fi

# output 6/7 — a writable GITHUB_ENV, receiving ONLY the real gh's absolute
# path. The wrapper resolves the real CLI through this seam; no DEVFLOW_GH is
# published (see the header).
{ [ -n "${GITHUB_ENV:-}" ] && echo "DEVFLOW_GH_REAL=$REAL_GH" >> "$GITHUB_ENV"; } \
  || fail "output 6/7 FAILED: GITHUB_ENV is unset or not appendable (github-env-write)"

# output 7/7 — a writable GITHUB_PATH, prepending the wrapper dir for later steps.
{ [ -n "${GITHUB_PATH:-}" ] && echo "$WRAPDIR" >> "$GITHUB_PATH"; } \
  || fail "output 7/7 FAILED: GITHUB_PATH is unset or not appendable (github-path-write)"

printf 'install-gh-wrapper: installed (wrapdir=%s real_gh=%s)\n' "$WRAPDIR" "$REAL_GH"

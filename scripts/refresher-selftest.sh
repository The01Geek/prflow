#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# refresher-selftest.sh — the credential refresher's synchronous pre-launch
# self-test (issue #1882). Each writer workflow's Start step runs this once,
# BEFORE it detaches the loop, so a host that cannot sign is loud immediately
# rather than after the job-start token's hour lapses. It signs a throwaway
# input with the real key on stdin (never argv, never disk) and routes the
# outcome to one of these arms:
#
#   * PASS (exit 0, emits a "self-test passed" line): the signer produced a
#     signature. The Start step launches the loop.
#   * JOB-FAULT (exit 3): a host-level fault no retry can clear — the signer
#     refusing the key, or the interpreter resolver reporting no interpreter or
#     one older than the required version. Emits a diagnostic and, when
#     DEVFLOW_REFRESH_SELFTEST_FAILED names a path, writes that marker so the
#     teardown attributes the job's failure to the signing fault rather than to
#     a never-started refresher. The Start step fails the job.
#   * WARN-CONTINUE (exit 0, emits a `::warning::`): the signer helper is absent
#     or unrunnable — an older vendored plugin slice that carries no signer. The
#     Start step launches the loop anyway; the two upgrade channels skew, and an
#     absent helper is not a host fault. Told apart from the refusing-signer arm
#     by the helper's presence and exit status, never by parsing its output.
#
# The self-test reaches no network and no GitHub API, so it neither needs nor
# carries a wall-clock bound, and no mint failure the detached loop's retry
# cycle absorbs (a rejected App id, a revoked key, an unreachable API) can reach
# the job-fault arm — those stay the loop's business.
#
# Overrides (verbatim, never probed — the DEVFLOW_REFRESH_MINT contract):
#   DEVFLOW_REFRESH_PYTHON             the interpreter resolver; its stdout is the
#                                      interpreter spec and its exit code the
#                                      resolver status (0 ok / 1 too-old / 3 none)
#   DEVFLOW_REFRESH_SIGNER             the signer helper path
#   DEVFLOW_REFRESH_SELFTEST_FAILED    marker file written on the job-fault arm

set -uo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_PY_LIB="$_HERE/../lib/resolve-python.sh"
SIGNER="${DEVFLOW_REFRESH_SIGNER:-$_HERE/sign-jwt-rs256.py}"
MARKER="${DEVFLOW_REFRESH_SELFTEST_FAILED:-}"
# The openssl-free signer invocation is shared with the mint (issue #1882).
# shellcheck source=../lib/refresher-sign.sh
. "$_HERE/../lib/refresher-sign.sh"

warn() { printf '::warning::refresher-selftest: %s\n' "$*" >&2; }

# Read the PEM key from stdin into shell memory only (never argv, never disk).
# Consumed by devflow_sign_jwt (sourced from lib/refresher-sign.sh) as a global.
# shellcheck disable=SC2034
KEY=""
# shellcheck disable=SC2034
IFS= read -r -d '' KEY || true

# Warn-and-continue arm: the signer helper is absent or not a readable file (an
# older vendored slice). Not a host fault — the Start step still launches.
if [ ! -f "$SIGNER" ]; then
  warn "signer helper not found at '$SIGNER' (older vendored plugin slice?) — launching the refresher without a pre-flight signer self-test"
  exit 0
fi

# The job-fault arm records the marker (when a path was given) and exits 3.
job_fault() {
  printf '::error::refresher-selftest: %s\n' "$1" >&2
  if [ -n "$MARKER" ]; then
    mkdir -p "$(dirname "$MARKER")" 2>/dev/null || true
    printf 'refresher-selftest: %s\n' "$1" > "$MARKER" 2>/dev/null || true
  fi
  exit 3
}

# Resolve the interpreter. resolve-python.sh echoes an invocation that may be two
# words (e.g. `py -3`), so capture it into a word-split array and invoke it as an
# array. The override wins verbatim (its stdout is the spec, its exit the status).
spec=""
prc=0
if [ -n "${DEVFLOW_REFRESH_PYTHON:-}" ]; then
  spec="$(eval "$DEVFLOW_REFRESH_PYTHON")"
  prc=$?
elif [ -r "$RESOLVE_PY_LIB" ]; then
  # shellcheck source=../lib/resolve-python.sh
  . "$RESOLVE_PY_LIB"
  spec="$(devflow_resolve_python)"
  prc=$?
else
  job_fault "no Python interpreter resolved: the resolver lib/resolve-python.sh was not readable at '$RESOLVE_PY_LIB'"
fi

case "$prc" in
  0) : ;;
  1) job_fault "the resolved Python interpreter '$spec' is older than the required version 3.11 — cannot sign; the previous credential is left in place" ;;
  *) job_fault "no Python interpreter resolved at all (consulted the resolver lib/resolve-python.sh at '$RESOLVE_PY_LIB') — cannot sign; the previous credential is left in place" ;;
esac

# Sign a throwaway input with the real key on stdin via the shared signer helper.
# A non-zero exit or empty stdout is the signer refusing the key — a host fault;
# its bounded, key-free diagnostic is surfaced.
if ! devflow_sign_jwt "$SIGNER" "$spec" selftest 1 2 || [ -z "$DEVFLOW_SIGN_STDOUT" ]; then
  job_fault "the signer refused the key at the JWT signing step: ${DEVFLOW_SIGN_STDERR:-(no diagnostic captured)}"
fi

printf 'refresher-selftest: self-test passed (the signer produced a signature)\n'
exit 0

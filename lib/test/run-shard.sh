#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Shard dispatcher for the concurrent CI job matrix (issue #877).
#
# The required merge-gate check `lib + python tests` used to be one sequential job
# running `bash lib/test/run.sh`. It is now satisfied by several shard
# jobs running concurrently, recombined by an aggregator job that keeps that exact
# name. This script is what one shard job runs: it maps a shard name to its work,
# captures the output, and writes a per-shard tally directory (via shard-tally.py)
# for the aggregator to download and recombine.
#
# The three tiers, deduplicated so nothing is counted twice across shards:
#   * the `monolith` shard runs run.sh with DEVFLOW_SKIP_SUITE_MODULES=1 AND
#     DEVFLOW_SKIP_PYTHON_POOL=1, i.e. every inline assertion EXCEPT the module tier
#     and the pooled Python suites;
#   * the `python-pool` shard runs those pooled Python suites — run.sh's own
#     membership, driven by run-python-pool.sh — concurrently with the monolith
#     instead of inside it, because the monolith measurably sat IDLE at the pool join
#     waiting for them (lib/test/profile-suite.py);
#   * each module shard runs `run-module.sh <id>` for the module ids in its group.
# The union of every module group is exactly the registered module set — no module
# is dropped (coverage is preserved), which lib/test/run.sh asserts against the
# registry.
#
# Usage:
#   bash lib/test/run-shard.sh <shard-name>     run a shard, write its tally dir
#   bash lib/test/run-shard.sh --list-shards    print every shard name (matrix source)
#   bash lib/test/run-shard.sh --modules-of S    print the module ids in shard S
#                                                (empty for the non-module shards)
#
# The tally directory is $DEVFLOW_SHARD_TALLY_DIR, defaulting to
# .prflow/tmp/shard-tally/<shard>. Exit status is the shard's own pass/fail state.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

# ── Shard → work map (single source of truth) ────────────────────────────────
# `monolith` and `python-pool` are the two non-module sentinels (each owns an EMPTY
# module group); every other shard names a space-separated module-id group. Keep the
# union of the module groups equal to the registered module set in
# scripts/workflow-flight-recorder-registry.json (asserted in run.sh).
#
# ORDER IS A COUPLED INVARIANT with .github/workflows/ci.yml's matrix list: run.sh
# compares the two sequences, so a shard added here must be added there in the same
# position (and vice versa) or the suite goes RED.
SHARD_NAMES="monolith python-pool modules-pin modules-large modules-rest"

_shard_modules() { # shard-name -> prints module ids (empty for the non-module shards)
  case "$1" in
    monolith)      printf '' ;;
    python-pool)   printf '' ;;
    modules-pin)   printf '%s' 'harness-python-guards' ;;
    modules-large) printf '%s' 'retrospective-lifecycle review-trigger-helpers create-issue-contract review-stall-backstop efficiency-trace-telemetry' ;;
    modules-rest)  printf '%s' 'workflow-flight-recorder review-and-fix-contract capability-profiles regenerate-artifacts installer-wiring prompt-extension-reader experiment-records issue-audit-state tier1-rename-migration parallel-suite-runner phase2-durability-checkpoint review-contract workpad-cli implement-contract' ;;
    *) return 2 ;;
  esac
}

_is_known_shard() { # shard-name -> rc 0 when known
  # _shard_modules is the single source of truth for the shard set: it returns rc 2
  # for an unknown shard and rc 0 (printing the group, empty for monolith) for a
  # known one, so membership derives from it rather than a second enumeration.
  _shard_modules "$1" >/dev/null 2>&1
}

# ── Query modes (used by the CI matrix and by run.sh's coupling assertions) ───
case "${1-}" in
  --list-shards)
    for s in $SHARD_NAMES; do printf '%s\n' "$s"; done
    exit 0
    ;;
  --modules-of)
    [ "$#" -ge 2 ] || { printf 'run-shard.sh: --modules-of requires a shard name\n' >&2; exit 2; }
    _is_known_shard "$2" || { printf 'run-shard.sh: unknown shard %s\n' "$2" >&2; exit 2; }
    mods="$(_shard_modules "$2")"
    [ -z "$mods" ] || printf '%s\n' $mods
    exit 0
    ;;
  --help|-h|'')
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  --*)
    printf 'run-shard.sh: unknown option %s\n' "$1" >&2
    exit 2
    ;;
esac

SHARD="$1"
_is_known_shard "$SHARD" || { printf 'run-shard.sh: unknown shard %s (known: %s)\n' "$SHARD" "$SHARD_NAMES" >&2; exit 2; }

TALLY_DIR="${DEVFLOW_SHARD_TALLY_DIR:-$REPO_ROOT/.prflow/tmp/shard-tally/$SHARD}"
mkdir -p "$TALLY_DIR" || { printf 'run-shard.sh: could not create tally dir %s\n' "$TALLY_DIR" >&2; exit 2; }
LOG_FILE="$TALLY_DIR/log.txt"

shard_rc=0
: > "$LOG_FILE"

MODS="$(_shard_modules "$SHARD")"
# Dispatch on the shard NAME, not on the emptiness of its module group: `monolith` and
# `python-pool` both own an empty group, so an emptiness test alone would silently run
# the whole monolith suite under the python-pool shard's name — double-counting every
# inline assertion into the aggregate.
case "$SHARD" in
  monolith)
    # The whole suite minus the module tier AND minus the pooled Python suites (dedup),
    # so it never re-runs work the modules-* / python-pool shards own.
    TIER=monolith
    printf 'run-shard.sh: monolith shard — bash lib/test/run.sh (DEVFLOW_SKIP_SUITE_MODULES=1 DEVFLOW_SKIP_PYTHON_POOL=1)\n'
    DEVFLOW_SKIP_SUITE_MODULES=1 DEVFLOW_SKIP_PYTHON_POOL=1 \
      bash "$SCRIPT_DIR/run.sh" >> "$LOG_FILE" 2>&1 || shard_rc=$?
    ;;
  python-pool)
    # The pooled Python suites run.sh skips under DEVFLOW_SKIP_PYTHON_POOL=1, over the
    # shared membership in module-harness.sh. Emits the same summary.sh contract the
    # monolith does, hence the same summary-parsing tier below under its own name.
    TIER=python-pool
    printf 'run-shard.sh: python-pool shard — bash lib/test/run-python-pool.sh\n'
    bash "$SCRIPT_DIR/run-python-pool.sh" >> "$LOG_FILE" 2>&1 || shard_rc=$?
    ;;
  *)
    # Module shard: run each module in the group; any module failure fails the shard.
    TIER=modules
    for mid in $MODS; do
      printf 'run-shard.sh: module %s — bash lib/test/run-module.sh %s\n' "$mid" "$mid"
      bash "$SCRIPT_DIR/run-module.sh" "$mid" >> "$LOG_FILE" 2>&1 || shard_rc=1
    done
    ;;
esac

# Echo the captured log so the shard job's own log carries the detail too.
cat "$LOG_FILE" || true

# Name the retained log's absolute path on the passing and failing shard exit, so a
# tail-piped reader re-reads it instead of re-executing (issue #1923); the CLAUDE.md
# tail-pipe bullet relies on this line, and builtins keep it off non-preflight tools.
LOG_FILE_ABS="$(cd "${LOG_FILE%/*}" && pwd -P)/${LOG_FILE##*/}"
printf 'run-shard.sh: retained log: %s\n' "$LOG_FILE_ABS"

# Fail the shard when the #671 plugin-validate gate self-skipped for CLI absence — a skip
# exits 0, so this is what stops a silent revert (issue #1830). Run on EVERY shard: do NOT
# scope to `monolith` by name (breaks migration-detection) nor widen past #671+CLI-absence (the #434 skip must not trip it).
if grep -Eq -- '#671 claude plugin validate --strict.*blocking-gate.*claude CLI not on PATH' "$LOG_FILE"; then
  printf '::error::run-shard.sh: the #671 plugin-validate gate self-skipped for CLI absence on shard %s — the claude CLI must be installed on whichever shard hosts that gate (see .github/workflows/ci.yml). Failing loudly rather than reverting the gate silently (issue #1830).\n' "$SHARD" >&2
  shard_rc=1
fi

# Extract the tally. shard-tally.py fails closed: a non-zero shard_rc with no
# parsed failure still records a failure, so a crashed shard never recombines green.
python3 "$SCRIPT_DIR/shard-tally.py" extract \
  --shard "$SHARD" --tier "$TIER" --log "$LOG_FILE" --rc "$shard_rc" --out "$TALLY_DIR"
extract_rc=$?

exit "$extract_rc"

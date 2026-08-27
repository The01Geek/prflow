#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# ---8<--- help-start
# In-run parallel full-suite coordinator for agent verification (issue #1086).
#
# CI already partitions this suite: `lib/test/run-shard.sh` maps a shard name to its
# work and several shard JOBS run concurrently on separate runners, recombined by
# `lib/test/shard-tally.py combine`. An agent's final verification gate had no such
# partition available — it ran `lib/test/run.sh` as one serial process — so every
# final and recovery pass paid the serial wall-clock and pushed the whole assertion
# stream back into model context.
#
# This script runs that SAME tested partition concurrently inside ONE checkout and
# prints a compact aggregate. It is the single agent-facing command shape:
#
#   lib/test/run-parallel.sh            run the suite in parallel, print the aggregate
#   lib/test/run-parallel.sh --preflight  run ONLY the read-only pre-launch checks (the
#                                         generated-artifact drift preflight, then the
#                                         cheap-lint gates), launch no shard, exit with
#                                         their verdict
#   lib/test/run-parallel.sh --help     this header
#
# `--preflight` exists for the #1132 shard-decomposition route: when the tier terminates the
# coordinator at its per-command execution ceiling, that route runs `lib/test/run-shard.sh
# <shard>` one shard at a time and recombines, and names `--preflight` once before its shard
# loop so the whole-suite result it produces carries the SAME pre-launch drift check the
# coordinator's own run does (issue #1288). It is read-only and sub-second — nowhere near the
# ceiling — and exits 0 to proceed (clean, or a fail-open inconclusive result) or non-zero on
# a positively-attributed drift, exactly as the coordinator's own pre-launch check decides.
#
# The bare form is the whole contract on purpose. Every environment assignment,
# redirect, background process, capacity decision and aggregation lives INSIDE this
# script, because the cloud permission matcher refuses caller-side assignment,
# redirect, pipeline and interpreter-prefix shapes even when the head is granted
# (issues #363/#401/#455). A caller that has to spell any of those to run the suite
# is a caller whose command is silently denied.
#
# `lib/test/run.sh` stays the serial primitive: the `monolith` shard runs it, and the
# documented uncovered-surface fallback still names it — and, mid-iteration on a tier
# where this coordinator meaningfully exceeds a single shard (the cloud implement tier),
# that `monolith` shard may stand in for the whole suite on a `run.sh`-resident surface
# (`lib/test/run-shard.sh monolith`), which never discharges the completion gate this
# script is (issue #1253; the operative rule lives in the prompt extensions). Focused
# modules (`lib/test/run-module.sh <id>`) stay the iteration default. This script is the
# FINAL gate, not the iteration loop.
#
# Differences from CI that the timing here does NOT let you infer:
#   * CI isolates each shard on its own runner; these shards share one host's CPU,
#     memory, checkout and process namespace.
#   * CI's wall-clock is the slowest RUNNER; this script's is the slowest shard
#     under contention with its siblings.
#
# Environment (all optional):
#   DEVFLOW_SUITE_PROCESS_BUDGET  positive integer; overrides the cpu probe (also the
#                                 test seam). Absent/nonnumeric/nonpositive OVERRIDE
#                                 falls through to the probe; a probe that yields no
#                                 positive integer fails closed to 1.
#   DEVFLOW_SHARD_DISPATCHER      path to a shard dispatcher other than the sibling
#                                 run-shard.sh (fixtures only).
#   DEVFLOW_ARTIFACT_PREFLIGHT    command for the read-only generated-artifact preflight
#                                 (issue #1244); defaults to the bundled
#                                 `regenerate-artifacts.py --preflight`. Set empty to skip
#                                 the preflight. Fixtures inject a stub here to drive its
#                                 clean/drift/uncheckable arms; the DEFAULT binding and the
#                                 verdict contract are driven end-to-end against the real
#                                 helper from lib/test/modules/regenerate-artifacts.sh.
#   DEVFLOW_RUFF_VERSION_PROBE    command behaving like `ruff --version` for the cheap-lint
#                                 ruff-version check (issue #2009); defaults to `ruff
#                                 --version`. Set empty to disable the check. Fixtures inject
#                                 a stub here to drive the skew/absent/non-executing arms.
#   TMPDIR                        parent of the per-shard scratch roots (always), and
#                                 the fallback run-root parent when the checkout root is
#                                 unusable (read-only, full, or name space exhausted).
#
# Exit status (coordinator run): 0 only when the aggregate is clean. Every named failure
# below exits non-zero with a `run-parallel:`-prefixed diagnostic naming what could not be
# done — including a shard whose process exited non-zero even when its tally reads clean.
# `--preflight` runs no shard and produces no aggregate, so it is governed by its own exit
# contract stated above (0 to proceed, non-zero on a positively-attributed drift), not by
# this sentence.
#
# KNOWN EXPOSURE, stated rather than assumed away: CI has only ever run these shards in
# SEPARATE checkouts on separate runners. Running them in one checkout under deliberate
# CPU saturation is new, and this coordinator isolates each shard's TMPDIR and tally
# directory but NOT repo-relative writes a shard's own assertions may make. A red result
# here that a serial `lib/test/run.sh` does not reproduce is therefore a signal to
# investigate the assertion's isolation or its slack budget — not something to re-run
# and hope on (this repository keeps no known-flake set).
# ---8<--- help-end

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

DISPATCHER="${DEVFLOW_SHARD_DISPATCHER:-$SCRIPT_DIR/run-shard.sh}"
TALLY_HELPER="$SCRIPT_DIR/shard-tally.py"

# Per detail class, not a shared budget — see shard-tally.py's --detail-cap.
DETAIL_CAP=20
# The largest total process budget this coordinator will schedule against, however
# many CPUs the host reports. Above this the shards contend more than they overlap,
# and the nested Python pool multiplies the pressure.
BUDGET_CEILING=8
# The most slots the nested `python-pool` reservation may take (its own width cap).
#
# Two, because the pool has exactly TWO members: `devflow_python_suite_pool_open` in
# lib/test/module-harness.sh registers `test_module_runner.py` and `test_python_scripts.py`
# and nothing else, and this reservation is what the shard exports as `DEVFLOW_POOL_WIDTH`.
# A cap above the membership therefore reserves slots the pool can never turn into a
# concurrent member, while the launch loop below still charges them against the budget —
# so the surplus is subtracted from the other shards and bought nothing.
#
# Measured, not inferred (issue #1180): the real scheduler was driven through its own two
# documented seams — `DEVFLOW_SUITE_PROCESS_BUDGET=4` to force the runner's budget, and
# `DEVFLOW_SHARD_DISPATCHER` pointed at a stub sleeping a time-scaled model of each shard's
# measured duration — on the host shape this coordinator actually runs on in the cloud,
# `ubuntu-latest` at 4 vCPU, i.e. `BUDGET = min(cpu_count, 8) = 4`. At ceiling 4 the
# reservation resolves to 3, `monolith` + `python-pool` fill all four slots and the
# remaining three shards serialize behind one freed slot: 11.4 min, over the tier's
# then-10-minute per-command ceiling (raised to 20 min by devflow-implement.yml in
# issue #1179; these figures are the #1180 measurement snapshot against the 10-min
# ceiling of the time, left unrewritten). At ceiling 2 a third shard launches at t=0 and the rest
# pipeline: 7.9 min. The packing change is what the focused module asserts; the minutes are
# a stub model that sleeps rather than consuming CPU, so they understate real contention and
# are recorded here as the measurement that justified the constant, not as a prediction.
#
# It is a global cap, so it also binds a host with more cores, where `BUDGET - 1` would
# otherwise have selected 3 or more. That is the same over-reservation argument, not a
# regression: the pool cannot run a third member on any host, and every slot the cap
# releases goes to a shard that can use it.
POOL_RESERVATION_CEILING=2

die() { # message
  printf 'run-parallel: %s\n' "$1" >&2
  exit 2
}

# ── Generated-artifact preflight — definition (read-only; issue #1244) ───────
# The read-only, sub-second drift check the coordinator runs before launching any
# shard. Factored into a function (issue #1288) so the SAME verdict interpretation
# serves both the coordinator's main flow below AND the standalone `--preflight`
# mode the #1132 shard-decomposition route names before its shard loop — that route
# runs `lib/test/run-shard.sh <shard>` one shard at a time and recombines, and would
# otherwise carry no pre-launch drift check at all. Keeping it here, in the one file
# that already owns the verdict contract, is what keeps that contract single-sourced
# rather than duplicated into a second coupled shell copy.
#
# A checked-in generated artifact can go stale from an ordinary prompt-surface edit, and
# before this the ONLY thing that reliably caught it was the ~13-minute suite (issue
# #1244, the run-30861787562 incident). `lib/test/regenerate-artifacts.py --preflight`
# runs the sub-second, READ-ONLY subset of the same generated-artifact registry and reports
# drift in well under a second, so a caller can refuse to launch rather than pay a whole
# suite run to discover it. The registry is the single source of truth: no artifact path and
# no command is hardcoded here, so the two cannot drift.
#
# DEVFLOW_ARTIFACT_PREFLIGHT is injectable like DEVFLOW_SHARD_DISPATCHER (the sibling test
# seam), so parallel-suite-runner.sh drives every arm from its synthetic trees. Set it empty
# to disable the preflight entirely. The default is the bundled helper's --preflight form,
# invoked directly (its exec bit is set) — word-split so the default expands to the script
# path plus its flag, and an override may be a whole command string, exactly the DISPATCHER
# idiom. `-` (not `:-`) so an explicitly-empty override DISABLES the preflight, while an
# unset variable takes the bundled default — the escape hatch the header documents.
#
# Returns 0 to PROCEED (every eligible artifact reconciled, OR a fail-open inconclusive
# result), and 1 on a positively-attributed drift — the caller decides the refusal action
# (the main flow and `--preflight` mode both `die`). Prints the drift report / inconclusive
# warning to stderr; a clean run is silent.
#
# SETTLED, not an oversight (raised and disposed on PR #1294): "clean" and "fail-open
# inconclusive/denied" share the return 0 / exit 0 code, so a caller reading ONLY the exit
# status cannot tell them apart. That IS the fail-open posture — an unusable check must
# never block — and the compensating control is the stderr channel above, which is silent
# on clean and warns by name on every inconclusive arm. A CLEAN run is therefore silent too,
# so silence alone does not distinguish clean from a matcher denial — the prompt-extension
# prose carries that ambiguity and its resolution (fall back and run the shards, which costs
# nothing on a clean tree), rather than this exit contract. Revisit only if a caller
# appears that must branch on the distinction and cannot read stderr.
_artifact_preflight() {
  local preflight_cmd preflight_out preflight_rc drift line
  preflight_cmd="${DEVFLOW_ARTIFACT_PREFLIGHT-$SCRIPT_DIR/regenerate-artifacts.py --preflight}"
  [ -n "$preflight_cmd" ] || return 0
  # shellcheck disable=SC2086  # deliberate word-split: a command plus its argument(s)
  preflight_out="$($preflight_cmd 2>&1)"
  preflight_rc=$?
  [ "$preflight_rc" -eq 0 ] && return 0
  # Refuse ONLY on a positively-attributed drift: exit 1 AND the preflight's own MACHINE
  # verdict line. Keying the refusal on the verdict (a bash-builtin read/case, never a
  # non-preflight PATH tool per CLAUDE.md guard-class 2) rather than on the exit code alone
  # is what makes a crash safe — the preflight itself routes a crashed row to UNCHECKABLE (a
  # traceback in any row → exit 2, never the drift verdict), and even a stub that exits 1
  # from a traceback carries no verdict line and takes the fail-open warn-and-proceed arm —
  # so an unusable check never blocks (only a detected drift does). Exit 2 (uncheckable),
  # rc 127 (refused/absent), and any other non-zero all fall through to that same arm.
  #
  # COUPLED CONTRACT, edited together with `lib/test/regenerate-artifacts.py`: the literal
  # below is that helper's `PREFLIGHT_VERDICT_PREFIX` + `drift`, and it is the ONLY thing
  # read here. The human remedy sentence the helper prints beside it is free prose with no
  # consumer. Matched LINE-EXACTLY (never as a substring of the blob) so a row diagnostic
  # that happens to quote the verdict — always indented or row-prefixed — cannot be mistaken
  # for the verdict itself. `lib/test/modules/regenerate-artifacts.sh` drives the real helper
  # end-to-end through this coordinator, so the pair goes RED together rather than drifting.
  drift=0
  while IFS= read -r line; do
    case "$line" in
      "regenerate-artifacts: preflight-verdict: drift") drift=1; break ;;
    esac
  done <<< "$preflight_out"
  if [ "$preflight_rc" -eq 1 ] && [ "$drift" -eq 1 ]; then
    printf '%s\n' "$preflight_out" >&2
    return 1
  fi
  printf 'run-parallel: WARNING: the generated-artifact preflight was inconclusive (exit %s, no drift verdict); proceeding\n' "$preflight_rc" >&2
  [ -z "$preflight_out" ] || printf '%s\n' "$preflight_out" >&2
  return 0
}

# ── Cheap-lint gate — definition (read-only; fail-fast before any shard) ─────
# Verdict contract, as `_artifact_preflight`: refuse ONLY on a positively-attributed
# finding, fail OPEN on anything leaving the check unusable. A clean gate is SILENT.
#
# Never key the refusal on the exit code: a Python traceback exits 1 exactly as a finding
# does, so the comparand is each lint's own completion sentinel, matched at the START of a
# line so the same text quoted inside an indented diagnostic row stays data.
#
# COUPLED CONTRACT — edit with the two lints: the sentinel literals below are their
# `audited N of M files` completion lines, and are the ONLY thing read here.
_cheap_lint_run() { # <label> <sentinel-prefix> <command string>
  local label="$1" sentinel="$2"; shift 2
  local cmd="$*" out rc line attributed
  [ -n "$cmd" ] || return 0
  # shellcheck disable=SC2086  # deliberate word-split: a command plus its argument(s)
  out="$($cmd 2>&1)"
  rc=$?
  [ "$rc" -eq 0 ] && return 0
  attributed=0
  while IFS= read -r line; do
    case "$line" in
      "$sentinel"*) attributed=1; break ;;
    esac
  done <<< "$out"
  if [ "$attributed" -eq 1 ]; then
    printf '%s\n' "$out" >&2
    printf 'run-parallel: the %s cheap-lint gate reported findings (see above); launching no shard — fix them and re-run\n' "$label" >&2
    return 1
  fi
  printf 'run-parallel: WARNING: the %s cheap-lint gate was inconclusive (exit %s, no completion sentinel); proceeding\n' "$label" "$rc" >&2
  [ -z "$out" ] || printf '%s\n' "$out" >&2
  return 0
}

# ── ruff-version cheap-lint check (issue #2009) ──────────────────────────────
# Refuse the launch ONLY on a positively-attributed version skew: a ruff on PATH reports a minor
# family differing from the family the lint manifest pins (the skew that reddens the #1621 gate
# on rule-set drift, not real findings). The expected family is read from the manifest at run
# time (no second copy here). Fail OPEN otherwise — warn-and-proceed when ruff is absent,
# non-executing, or reports an unparseable version; skip SILENTLY (no warning) when this checkout
# lacks the manifest or the helper. DEVFLOW_RUFF_VERSION_PROBE is the test seam; an
# explicitly-empty value disables the gate, as the `-` (never `:-`) siblings above.
_ruff_version_preflight() {
  local probe="${DEVFLOW_RUFF_VERSION_PROBE-ruff --version}"
  local manifest="$REPO_ROOT/.prflow/lint-manifest.json"
  local helper="$REPO_ROOT/scripts/ruff-version-skew.py"
  local out rc verdict
  [ -n "$probe" ] || return 0
  # Nothing to compare when this checkout lacks the manifest pin or the helper: skip silently.
  { [ -s "$manifest" ] && [ -r "$helper" ]; } || return 0
  # shellcheck disable=SC2086  # deliberate word-split: a probe command plus its argument(s)
  # Parse stdout only: rc is checked separately below, and folding stderr in could feed a
  # stray version-ish token to the helper's first-match parse and misattribute the family.
  out="$($probe 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'run-parallel: WARNING: the ruff-version cheap-lint check could not run ruff (absent or non-executing, exit %s); proceeding\n' "$rc" >&2
    return 0
  fi
  verdict="$(python3 "$helper" --manifest "$manifest" --reported "$out" 2>&1)"
  # Do NOT key the refusal on the helper's exit code — an uncaught traceback exits 1 exactly
  # as a skew does — so key on the helper's own `ruff-version-skew: SKEW` sentinel matched at
  # a line START instead (a crash prints none and fails open).
  local skew=0 line
  while IFS= read -r line; do
    case "$line" in
      'ruff-version-skew: SKEW'*) skew=1; break ;;
    esac
  done <<< "$verdict"
  if [ "$skew" -eq 1 ]; then
    printf '%s\n' "$verdict" >&2
    printf 'run-parallel: the ruff-version cheap-lint gate found a version skew (see above); launching no shard — install the pinned ruff and re-run\n' >&2
    return 1
  fi
  # No SKEW sentinel: a clean match is silent, an inconclusive/crash result fails open with
  # whatever the helper reported (never a refusal).
  [ -z "$verdict" ] || printf 'run-parallel: WARNING: the ruff-version cheap-lint check was inconclusive; proceeding\n%s\n' "$verdict" >&2
  return 0
}

# Returns 0 to PROCEED, 1 on the first positively-attributed finding; a refusal
# short-circuits so a second gate's output cannot bury the one that fired.
# Keep `-` (never `:-`) below, or an explicitly-empty override stops disabling its gate.
_cheap_lint_preflight() {
  _cheap_lint_run 'reference-size' 'lint-reference-size: audited ' \
    "${DEVFLOW_REFERENCE_SIZE_PREFLIGHT-python3 $SCRIPT_DIR/lint-reference-size.py}" || return 1
  _cheap_lint_run 'brand-sweep' 'lint-brand-devflow-sweep: audited ' \
    "${DEVFLOW_BRAND_SWEEP_PREFLIGHT-python3 $SCRIPT_DIR/lint-brand-devflow-sweep.py}" || return 1
  _ruff_version_preflight || return 1
  return 0
}

# The refusal message is identical on both routes, so it is spelled once. `die` exits 2.
_refuse_on_drift() {
  die "generated-artifact preflight reported drift (see above); launching no shard — regenerate the artifact(s) under their governing policy and re-run"
}

[ "$#" -le 1 ] || die "this command takes at most one argument (--help or --preflight) — the agent-facing command shape is the bare invocation"
case "${1-}" in
  '') ;;
  --preflight)
    # Standalone read-only preflight for the #1132 shard-decomposition route (issue #1288):
    # run the drift check, launch NO shard, and exit with the same verdict contract the
    # coordinator applies — 0 to proceed (clean or fail-open inconclusive), non-zero (via
    # die) on a positively-attributed drift. The route names this before its shard loop.
    _artifact_preflight || _refuse_on_drift
    # The same cheap-lint gates the coordinator applies, so a decomposed whole-suite result
    # carries the identical pre-launch verdict rather than rediscovering a sub-second
    # finding across the full shard partition.
    _cheap_lint_preflight || exit 2
    exit 0
    ;;
  --help|-h)
    # Delimited by sentinels rather than line numbers: a hardcoded `4,50p` range silently
    # truncates or overspills the moment any header line is added or removed, and nothing
    # would go red. `sed` is not preflight-guaranteed, so its absence is announced rather
    # than printing nothing and exiting 0.
    if ! sed -n '/^# ---8<--- help-start/,/^# ---8<--- help-end/{/---8<---/d;p;}' "$0" | sed 's/^# \{0,1\}//'; then
      printf 'run-parallel: could not render --help (sed is unavailable); read the header of %s instead\n' "$0" >&2
      exit 2
    fi
    exit 0
    ;;
  *)
    die "unknown argument '$1' — the agent-facing command shape is the bare invocation"
    ;;
esac

# ── Reentrancy ───────────────────────────────────────────────────────────────
# A shard runs modules, and a module that invoked THIS script against the real
# population would fork a whole second suite underneath a shard of the first. The
# guard is scoped to a real-population invocation: a fixture invocation naming its
# own dispatcher is exactly how the focused module exercises this coordinator, and
# refusing that would make the module untestable from inside the suite it verifies.
if [ -n "${DEVFLOW_PARALLEL_SUITE_ACTIVE:-}" ] && [ -z "${DEVFLOW_SHARD_DISPATCHER:-}" ]; then
  die "reentrancy: a parallel suite run is already active in this process tree; the real shard population must not be re-entered from inside a shard"
fi

# ── Shard population (derived, never copied) ─────────────────────────────────
[ -x "$DISPATCHER" ] || [ -r "$DISPATCHER" ] || \
  die "shard dispatcher is not readable: $DISPATCHER"
# The dispatcher's own stderr is deliberately NOT swallowed: this diagnostic names
# which step failed, and the dispatcher names why.
SHARDS="$(bash "$DISPATCHER" --list-shards)" || \
  die "shard dispatcher failed to list its shards: $DISPATCHER --list-shards"

SHARD_COUNT=0
SEEN_SHARDS=""
for shard in $SHARDS; do
  # Validate before the name reaches a path. A malformed name is a dispatcher
  # defect, and letting it through would silently create a run-root sibling
  # outside the layout the isolation argument below depends on.
  case "$shard" in
    ''|*[!a-z0-9-]*|-*) die "malformed shard name from the dispatcher: '$shard'" ;;
  esac
  # Uniqueness is the other half of that isolation argument, and its absence is
  # silent in the dangerous direction: two shards of the same name write ONE tally
  # directory and one log, `combine` reads that directory twice (doubling its counts
  # and satisfying --expect from a single shard), and the shard the typo displaced
  # never runs at all — coverage vanishes while the gate stays green.
  case " $SEEN_SHARDS " in
    *" $shard "*) die "duplicate shard name from the dispatcher: '$shard' — two shards would share one tally directory and a displaced shard would silently not run" ;;
  esac
  SEEN_SHARDS="$SEEN_SHARDS $shard"
  SHARD_COUNT=$((SHARD_COUNT + 1))
done
[ "$SHARD_COUNT" -gt 0 ] || \
  die "the shard dispatcher returned an empty population; refusing to report a clean suite over zero shards"

# ── Generated-artifact preflight — invocation (read-only; issue #1244) ───────
# The shared `_artifact_preflight` function (defined above, near `die`, so the same
# verdict interpretation also backs the `--preflight` mode the #1132 decomposition route
# names) runs the sub-second read-only drift check before a single shard launches, and
# the coordinator refuses to launch on a positively-attributed drift.
_artifact_preflight || _refuse_on_drift
# The cheap-lint gates run next, still before a single shard launches: both are read-only
# and sub-second, and either firing means the coordinator would have gone RED anyway.
_cheap_lint_preflight || exit 2

# ── Run root ─────────────────────────────────────────────────────────────────
# Fresh per invocation, so a stale sibling's tally directory can never be mistaken
# for this run's (the aggregation below also passes explicit paths, never a scan).
_try_run_root() { # parent -> prints a fresh writable run root, or returns 1
  local parent="$1" candidate n=0
  [ -n "$parent" ] || return 1
  mkdir -p "$parent" 2>/dev/null || return 1
  while [ "$n" -lt 50 ]; do
    candidate="$parent/run-$$-$n"
    # `mkdir` without -p is the atomic claim: it fails if the name already exists,
    # so two coordinators racing on the same parent cannot pick the same root.
    if mkdir "$candidate" 2>/dev/null; then
      # Existence is not writability (a read-only mount, a full quota): verify the
      # outcome the root stands in for rather than the precondition.
      if : > "$candidate/.writable" 2>/dev/null; then
        rm -f "$candidate/.writable"
        printf '%s\n' "$candidate"
        return 0
      fi
      rmdir "$candidate" 2>/dev/null || :
      return 1
    fi
    n=$((n + 1))
  done
  return 1
}

RUN_ROOT="$(_try_run_root "$REPO_ROOT/.prflow/tmp/parallel-suite")" || RUN_ROOT=""
if [ -z "$RUN_ROOT" ]; then
  RUN_ROOT="$(_try_run_root "${TMPDIR:-/tmp}/devflow-parallel-suite")" || RUN_ROOT=""
  [ -n "$RUN_ROOT" ] || \
    die "could not allocate a writable run root under $REPO_ROOT/.prflow/tmp/parallel-suite or ${TMPDIR:-/tmp}/devflow-parallel-suite (read-only, full, or name space exhausted)"
  printf 'run-parallel: checkout run root unusable; retained logs are under %s\n' "$RUN_ROOT" >&2
fi
mkdir -p "$RUN_ROOT/logs" "$RUN_ROOT/tally" 2>/dev/null || \
  die "could not create the run-root layout under $RUN_ROOT"

# Record this launch's checkout fingerprint for the same-tree failed-shard-only relaunch gate
# (issue #2008). Best-effort: the helper always writes the record and exits 0, so never let a
# fingerprint failure block the launch.
python3 "$TALLY_HELPER" record-fingerprint --out "$RUN_ROOT" || :

# The per-shard TMPDIRs live OUTSIDE the checkout, deliberately, even when the run root
# is inside it. A shard's own assertions build fixture trees with `mktemp -d`, and this
# suite has a whole class of them — the non-git-tree / bare-tree / pwd-fallback cases —
# whose premise is that the fixture is NOT inside a git working tree. Rooting TMPDIR at
# `$RUN_ROOT/tmp` put every such fixture inside this repository, so `git rev-parse
# --show-toplevel` resolved from it and the fallback under test never fired: measured,
# 129 failures across all five shards, none of them a real regression. Logs and tallies
# stay in the run root (they are the retained artifact); only the scratch moves out.
TEMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/devflow-parallel-tmp.XXXXXX")" || \
  die "could not allocate a per-shard temporary root under ${TMPDIR:-/tmp}"
_cleanup_temp_base() { [ -z "${TEMP_BASE:-}" ] || rm -rf "$TEMP_BASE"; }
trap _cleanup_temp_base EXIT

# ── Process budget ───────────────────────────────────────────────────────────
# The budget decides a SELECTION (how much overlaps), so it is derived through the
# preflight-guaranteed python3 and never a non-preflight PATH tool (CLAUDE.md
# guard-class 2). An override that is not a positive integer is not silently
# honoured; an unestablished probe fails closed to a serial-but-complete width 1.
BUDGET=""
case "${DEVFLOW_SUITE_PROCESS_BUDGET:-}" in
  ''|*[!0-9]*) : ;;
  *) [ "${DEVFLOW_SUITE_PROCESS_BUDGET}" -ge 1 ] && BUDGET="$DEVFLOW_SUITE_PROCESS_BUDGET" ;;
esac
if [ -z "$BUDGET" ]; then
  BUDGET="$(python3 -c 'import os; print(os.cpu_count() or 0)' 2>/dev/null)" || BUDGET=""
  case "$BUDGET" in
    ''|*[!0-9]*) BUDGET=1 ;;
    *) [ "$BUDGET" -ge 1 ] || BUDGET=1 ;;
  esac
  # Say so. Failing closed to width 1 is correct, but it costs the whole serial
  # wall-clock this coordinator exists to avoid, and a silent degrade leaves the
  # reader with no way to tell a one-core host from a broken `python3`.
  [ "$BUDGET" -gt 1 ] || \
    printf 'run-parallel: the python3 cpu probe established no usable count — running serially at width 1 (check that python3 resolves)\n' >&2
fi
[ "$BUDGET" -le "$BUDGET_CEILING" ] || BUDGET="$BUDGET_CEILING"

# The nested Python pool forks its own workers, so its slots are reserved OUT of the
# same total rather than added to it — otherwise the budget would bound only the
# top-level shards while the real process count ran to budget + pool width.
POOL_RESERVATION=$((BUDGET - 1))
[ "$POOL_RESERVATION" -ge 1 ] || POOL_RESERVATION=1
[ "$POOL_RESERVATION" -le "$POOL_RESERVATION_CEILING" ] || POOL_RESERVATION="$POOL_RESERVATION_CEILING"

_shard_cost() { # shard-name -> slots this shard occupies
  case "$1" in
    python-pool) printf '%s\n' "$POOL_RESERVATION" ;;
    *) printf '1\n' ;;
  esac
}

# ── Launch bookkeeping + signal handling ─────────────────────────────────────
# Job control gives each background shard its own process group, so a signal can be
# forwarded to the shard AND everything it forked (run.sh, run-module.sh, the pool
# workers) rather than to the shard shell alone.
set -m

# One list of `<pid>:<cost>:<shard>` triples rather than three positionally-coupled
# lists: a shard name is `[a-z0-9-]` by the validation above, so `:` cannot occur in a
# field, and keeping the three values in one record removes the index-alignment the
# separate lists had to maintain by hand.
RUNNING=""
USED_SLOTS=0
LAUNCHING=0
PENDING_SIGNAL=""
SIGNAL_HANDLED=0

_terminate_launched() { # signal
  local sig="$1" rec pid
  for rec in $RUNNING; do
    pid="${rec%%:*}"
    # Signal the GROUP first (the shard plus its descendants), then the leader, so a
    # shell without a usable group still receives it.
    kill -s "$sig" -- "-$pid" 2>/dev/null || :
    kill -s "$sig" "$pid" 2>/dev/null || :
  done
  for rec in $RUNNING; do
    pid="${rec%%:*}"
    kill -s KILL -- "-$pid" 2>/dev/null || :
    kill -s KILL "$pid" 2>/dev/null || :
    # Reap, so the coordinator never exits leaving its children unwaited.
    wait "$pid" 2>/dev/null || :
  done
  RUNNING=""
}

_on_signal() { # signal
  local sig="$1"
  # The fork-to-PID-registration window: a signal delivered between `&` and the
  # assignment of `$!` would otherwise terminate the parent with that child
  # unregistered, unreaped and still running. Park it and replay after registration.
  if [ "$LAUNCHING" -eq 1 ]; then
    PENDING_SIGNAL="$sig"
    return 0
  fi
  [ "$SIGNAL_HANDLED" -eq 0 ] || return 0
  SIGNAL_HANDLED=1
  trap '' HUP INT TERM
  printf 'run-parallel: received %s — terminating and reaping the launched shards\n' "$sig" >&2
  _terminate_launched "$sig"
  exit 1
}

trap '_on_signal HUP' HUP
trap '_on_signal INT' INT
trap '_on_signal TERM' TERM

# Reap every child that has already exited, freeing its slots and recording a non-zero
# status against its shard name. A still-live child is kept in the registry, so a signal
# arriving later still reaches it.
_reap_finished() {
  local rec pid cost name keep=""
  for rec in $RUNNING; do
    pid="${rec%%:*}"; cost="${rec#*:}"; cost="${cost%%:*}"; name="${rec##*:}"
    if kill -0 "$pid" 2>/dev/null; then
      keep="$keep $rec"
    else
      if wait "$pid"; then :; else
        SHARD_RCS="$SHARD_RCS $name=$?"
      fi
      USED_SLOTS=$((USED_SLOTS - cost))
    fi
  done
  RUNNING="$keep"
}

SHARD_RCS=""
LAUNCH_FAILURES=""

printf 'run-parallel: %d shard(s), process budget %d (python-pool reservation %d), run root %s\n' \
  "$SHARD_COUNT" "$BUDGET" "$POOL_RESERVATION" "$RUN_ROOT"

for shard in $SHARDS; do
  cost="$(_shard_cost "$shard")"
  # Defensive only, and deliberately kept: the reservation is bounded by the budget
  # above, so no current input reaches this clamp. It exists so a future cost rule that
  # exceeded the budget would still RUN the shard alone rather than deadlock the
  # scheduler — dropping coverage is the one outcome this coordinator may never trade
  # for speed.
  [ "$cost" -le "$BUDGET" ] || cost="$BUDGET"
  while [ "$USED_SLOTS" -gt 0 ] && [ $((USED_SLOTS + cost)) -gt "$BUDGET" ]; do
    _reap_finished
    [ $((USED_SLOTS + cost)) -le "$BUDGET" ] || sleep 0.05
  done

  shard_tally="$RUN_ROOT/tally/$shard"
  shard_tmp="$TEMP_BASE/$shard"
  shard_log="$RUN_ROOT/logs/$shard.log"
  if ! mkdir -p "$shard_tally" "$shard_tmp"; then
    LAUNCH_FAILURES="$LAUNCH_FAILURES $shard"
    printf 'run-parallel: shard %s — could not create its private tally/temp directories under %s\n' "$shard" "$RUN_ROOT" >&2
    continue
  fi

  LAUNCHING=1
  # Test seam for the fork-to-registration window (the sibling of
  # module-harness.sh's _devflow_test_pause_before_pid_capture): it holds the run
  # inside the LAUNCHING window so a signal can be delivered there deterministically,
  # and releases as soon as one has been parked. Unset in production, where the
  # window is the few instructions between the `&` and `$!` below.
  if [ -n "${DEVFLOW_TEST_LAUNCH_WINDOW_FILE:-}" ]; then
    printf 'launching\n' > "$DEVFLOW_TEST_LAUNCH_WINDOW_FILE" 2>/dev/null || :
    while [ ! -e "$DEVFLOW_TEST_LAUNCH_WINDOW_FILE.release" ] && [ -z "$PENDING_SIGNAL" ]; do :; done
  fi
  (
    # Each shard is its own process-group leader with a private TMPDIR and tally dir,
    # so sibling shards sharing this checkout cannot collide on either. The TMPDIR is
    # outside the checkout (see TEMP_BASE above) so a shard's own `mktemp -d` fixtures
    # are not inside a git working tree. The nested pool width is exported only to the
    # shard that owns the reservation.
    export TMPDIR="$shard_tmp"
    export DEVFLOW_SHARD_TALLY_DIR="$shard_tally"
    export DEVFLOW_PARALLEL_SUITE_ACTIVE=1
    if [ "$shard" = python-pool ]; then
      export DEVFLOW_POOL_WIDTH="$POOL_RESERVATION"
    fi
    exec bash "$DISPATCHER" "$shard" > "$shard_log" 2>&1
  ) &
  launched_pid=$!
  RUNNING="$RUNNING $launched_pid:$cost:$shard"
  USED_SLOTS=$((USED_SLOTS + cost))
  LAUNCHING=0
  [ -z "$PENDING_SIGNAL" ] || _on_signal "$PENDING_SIGNAL"
  printf 'run-parallel: launched shard %s (pid %s, %s slot(s))\n' "$shard" "$launched_pid" "$cost"
done

# Wait for the COMPLETE launched population PID by PID (portable: no `wait -n`), so
# aggregation never reads a tally a shard is still writing.
for rec in $RUNNING; do
  pid="${rec%%:*}"; name="${rec##*:}"
  if wait "$pid"; then :; else
    SHARD_RCS="$SHARD_RCS $name=$?"
  fi
done
RUNNING=""

# ── Aggregate ────────────────────────────────────────────────────────────────
# Explicit per-shard tally paths derived from the population this run launched —
# never `--scan`, whose parent directory would also admit a stale sibling run's
# tally and let it satisfy this invocation's --expect floor.
# An ARRAY, not a space-joined string: a checkout path containing a space (a WSL
# `/mnt/c/Users/First Last/...` tree is a supported tier) would word-split every entry,
# turning N real paths into more than N bogus ones — which satisfies `--expect`'s
# missing-shard floor from garbage and leaves only the unreadable-tally guard between
# the run and a vacuous pass.
TALLY_ARGS=()
EXPECTED=0
MISSING=""
for shard in $SHARDS; do
  case " $LAUNCH_FAILURES " in *" $shard "*) continue ;; esac
  EXPECTED=$((EXPECTED + 1))
  if [ -f "$RUN_ROOT/tally/$shard/summary" ]; then
    TALLY_ARGS+=("$RUN_ROOT/tally/$shard")
  else
    MISSING="$MISSING $shard"
  fi
done

AGGREGATE_RC=0
if [ -n "$LAUNCH_FAILURES" ]; then
  printf 'run-parallel: shard(s) failed to launch:%s\n' "$LAUNCH_FAILURES" >&2
  AGGREGATE_RC=1
fi
if [ -n "$MISSING" ]; then
  printf 'run-parallel: shard(s) produced no tally:%s — see the retained logs under %s\n' \
    "$MISSING" "$RUN_ROOT/logs" >&2
  AGGREGATE_RC=1
fi
if [ -n "$SHARD_RCS" ]; then
  # This must SET the failure, not merely report it. A shard killed AFTER
  # shard-tally.py wrote its tally but BEFORE run-shard.sh returned (the OOM killer
  # on a saturated host is the reachable case) leaves a complete, clean-looking tally
  # beside a non-zero status: `MISSING` never fires, `combine` sums a green tally, and
  # a printed-but-inert observation would let the run exit 0 while announcing that a
  # shard did not complete.
  printf 'run-parallel: shard process(es) exited non-zero:%s — refusing a clean aggregate over a shard that did not complete\n' "$SHARD_RCS" >&2
  AGGREGATE_RC=1
fi

# `--expect` is the missing-shard floor: it is the count this run actually launched,
# so a shard that died before writing its tally cannot be silently dropped.
#
# The expansion is the `${arr[@]+"${arr[@]}"}` guarded form (the idiom
# lib/implement-stop-guard.sh and scripts/build-denial-record.sh already use). TALLY_ARGS
# is empty whenever NO shard produced a tally — every shard failed to launch, or every one
# died before writing one — and on bash before 4.4 a bare `"${TALLY_ARGS[@]}"` under
# `set -u` aborts as an unbound variable, replacing the named diagnostics above with a raw
# interpreter error. The guard expands to nothing instead, so `combine` still runs against
# an `--expect` floor it cannot meet and the failure still reaches the aggregate below.
# This is about which diagnostic that host prints, not about the exit status — the abort
# was already non-zero. The window where it matters is bash 4.0 through 4.3:
# lib/test/module-harness.sh's top-level `declare -A` already needs 4.0 of every shard, and
# 4.4 is where the bare form stopped tripping `nounset`. On 4.4+ the two forms behave
# identically, so nothing on this repository's CI or desk tier changes.
# `--require-shards "$SHARDS"` reconciles the recombination against the TRUE partition by
# name, not just the `--expect` count (issue #1289): `$SHARDS` is the authoritative
# `--list-shards` population this coordinator enumerated, so a shard that never wrote a
# tally (launch failure, crash-before-upload) is named as missing in `combine`'s own output
# too — the count floor alone could be satisfied by a subset. This is additive to the
# `--expect`/`MISSING`/`SHARD_RCS` diagnostics above, never a replacement.
if ! python3 "$TALLY_HELPER" combine ${TALLY_ARGS[@]+"${TALLY_ARGS[@]}"} --expect "$EXPECTED" --require-shards "$SHARDS" --detail-cap "$DETAIL_CAP"; then
  AGGREGATE_RC=1
fi

printf '\n'
printf 'run-parallel: shard roster:%s\n' "$(printf ' %s' $SHARDS)"
printf 'run-parallel: retained logs: %s\n' "$RUN_ROOT/logs"
# issue #1808: placed before the AGGREGATE_RC branch below so the branch cannot skip it;
# do not compute it via date or another external program — keep the SECONDS builtin (AC2).
printf 'run-parallel: elapsed %ss\n' "$SECONDS"
if [ "$AGGREGATE_RC" -eq 0 ]; then
  printf 'run-parallel: aggregate CLEAN\n'
else
  printf 'run-parallel: aggregate FAILED — read the retained logs above rather than re-running\n' >&2
fi
exit "$AGGREGATE_RC"

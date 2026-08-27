#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Driver for the `python-pool` CI shard.
#
# WHY THIS SHARD EXISTS
#   lib/test/run.sh opens a bounded concurrent pool (issue #720) over the heavy
#   focused Python suites — test_module_runner.py and the four parts test_python_scripts.py
#   was split into (issue #2007) — early in
#   the file, and joins it at the tail so the Python work overlaps the shell assertions.
#   The overlap is not enough: profiling the `monolith` shard (lib/test/profile-suite.py)
#   measured the shell sitting IDLE at the join, waiting for Python work the shell had
#   already run out of assertions to hide behind. That idle time is pure wall-clock on
#   the shard that sets the CI ceiling, and the wall-clock of the required
#   `lib + python tests` check is its SLOWEST shard, not the sum.
#
#   So the pooled suites get their own concurrent shard. The monolith shard invokes
#   run.sh with DEVFLOW_SKIP_PYTHON_POOL=1 and skips both the open and the join; this
#   driver runs the same pool, over the same membership, in parallel with it.
#
# WHAT IS AND IS NOT DUPLICATED
#   Membership, the per-suite tally mode, and the self-tally reconciliation are NOT
#   copied here: they are devflow_python_suite_pool_open / devflow_python_suite_pool_join
#   in lib/test/module-harness.sh, the single definition this driver and run.sh share.
#   What is local to this file is only the tally plumbing a standalone driver must own —
#   its RESULTS_FILE, its assert_eq binding, and the summary render.
#
# ASSERTION ACCOUNTING
#   Every verdict reaches the same `N passed, M failed` contract lib/test/summary.sh
#   renders for run.sh, which is what lib/test/shard-tally.py reads (--tier python-pool).
#   The counts here are exactly the counts these suites contributed to the monolith
#   shard before the split — the same pool, the same modes, the same reconciliation —
#   so the recombined cross-shard tally is unchanged.
#
# Usage:  lib/test/run-python-pool.sh
# Exit status: 0 when nothing failed, 1 otherwise. A run that cannot establish its own
# tally aborts WITHOUT rendering a summary, so shard-tally.py records the fail-closed
# synthetic failure rather than recombining an unmeasured shard as green.

set -u

TEST_DIR="$(cd "$(dirname "$0")" && pwd -P)"

# shellcheck source=lib/test/summary.sh disable=SC1091
. "$TEST_DIR/summary.sh" || {
  printf 'run-python-pool.sh: could not source %s\n' "$TEST_DIR/summary.sh" >&2
  exit 2
}
# shellcheck source=lib/test/module-harness.sh disable=SC1091
. "$TEST_DIR/module-harness.sh" || {
  printf 'run-python-pool.sh: could not source %s\n' "$TEST_DIR/module-harness.sh" >&2
  exit 2
}
# Fail closed on the OUTCOME of the source, not merely on its exit status: a harness that
# sourced cleanly but no longer defines the shared pool entry points would otherwise leave
# this driver running nothing and reporting `0 passed, 0 failed` — a shard that recombines
# as green while its whole population silently vanished.
#
# `declare -F`, not `type`: `type` is satisfied by any PATH executable, alias or builtin of
# the same name, so a same-named binary on PATH could mask an undefined harness function and
# wave this gate through. Only a shell FUNCTION can be what the sourced harness defined.
for _fn in devflow_python_suite_pool_open devflow_python_suite_pool_join record_fail \
  devflow_render_test_summary devflow_render_failure_recap devflow_tally_is_derivable; do
  declare -F "$_fn" >/dev/null 2>&1 || {
    printf 'run-python-pool.sh: harness did not define %s\n' "$_fn" >&2
    exit 2
  }
done
unset _fn

RESULTS_FILE="$(mktemp "${TMPDIR:-/tmp}/devflow-python-pool-results.XXXXXX")" || {
  printf 'run-python-pool.sh: could not allocate the assertion tally\n' >&2
  exit 2
}
: > "$RESULTS_FILE"

_python_pool_cleanup() {
  rm -f "$RESULTS_FILE" "$RESULTS_FILE.names"
}
trap _python_pool_cleanup EXIT

# The same RESULTS_FILE + record_fail contract run.sh's assert_eq carries (lib/test/run.sh
# and lib/test/run-module.sh each bind their own for the same reason: the tally file and the
# failure-identifier record differ per driver). devflow_python_suite_pool_join calls this.
assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo PASS >> "$RESULTS_FILE"
    printf '  PASS  %s\n' "$name"
  else
    echo FAIL >> "$RESULTS_FILE"
    record_fail "$name"
    printf '  FAIL  %s\n         expected: %s\n         actual:   %s\n' \
      "$name" "$expected" "$actual"
  fi
}

echo "python-pool shard: concurrent focused Python suites (issue #720 pool membership)"
devflow_python_suite_pool_open
devflow_python_suite_pool_join

PASS=$(grep -c '^PASS$' "$RESULTS_FILE" || true)
FAIL=$(grep -c '^FAIL$' "$RESULTS_FILE" || true)
# The `|| true` above absorbs ONLY the benign empty-log case (grep -c still prints "0",
# rc 1). A real grep error (rc >= 2) prints nothing, leaving the value EMPTY — and an
# empty tally coerced to 0 downstream would render a clean-looking summary over a
# measurement that was never made. Unknown is not zero: refuse loudly, before rendering.
if ! devflow_tally_is_derivable "$PASS"; then
  printf 'ERROR: PASS tally underivable from %s (grep error, not an empty log) — refusing to render a summary over it\n' "$RESULTS_FILE"
  exit 1
fi
if ! devflow_tally_is_derivable "$FAIL"; then
  printf 'ERROR: FAIL tally underivable from %s (grep error, not an empty log) — refusing to render a summary over it\n' "$RESULTS_FILE"
  exit 1
fi
# A shard that recorded NO verdict at all is a fail-closed abort, not a `0 passed, 0
# failed` summary. That summary parses cleanly, so shard-tally.py would accept it and the
# aggregate would silently lose this shard's whole population while the required check
# stayed green — the exact laundering the split must not introduce. No floor NUMBER is
# checked (a checked-in count rots on every assertion added to either suite); the guard is
# structural: at least one verdict must exist for this driver to have run anything.
if [ "$((PASS + FAIL))" -eq 0 ]; then
  printf 'ERROR: the python-pool shard recorded ZERO verdicts — refusing to report an empty shard as a clean pass\n'
  exit 1
fi

echo
# No skip channel exists on this shard: the pool writes only PASS/FAIL verdicts and this
# driver defines no skip(), so the skip tally is a structural 0 rather than a derived one.
# Rendering it through the shared renderer keeps the summary line byte-identical to the
# contract shard-tally.py parses.
devflow_render_test_summary "$PASS" "$FAIL" 0 ""
devflow_render_failure_recap "$FAIL" "$RESULTS_FILE.names"
[ "$FAIL" -eq 0 ]

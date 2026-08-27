# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable focused module for the in-run parallel full-suite coordinator
# (`lib/test/run-parallel.sh`, issue #1086).
#
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. Modules may not self-skip.
#
# Everything here drives the coordinator against SYNTHETIC shard dispatchers planted
# in fixture trees. The real shard population is never launched from inside this
# module: a shard runs modules, so a real-population invocation here would fork a
# whole second suite underneath the shard running this file. That reentrancy is
# itself asserted below (the coordinator refuses it by name), and the serial-vs-
# parallel comparison over the real population deliberately lives outside the
# registered module set.
#
# `shard-tally.py` is NOT mocked — the fixture dispatchers write their tallies
# through the real extractor, so the aggregation contract under test is the shipped
# one.

PSR_COORD="$LIB/test/run-parallel.sh"
PSR_TALLY="$LIB/test/shard-tally.py"
# issue #1216: the exec shim that restores SIGINT/SIGQUIT (and the other default
# suite signals) before the coordinator's bash begins. The signal cases below
# background the coordinator under the module worker's job-control-off shell,
# which POSIX-forces SIGINT/SIGQUIT to SIG_IGN in the child; bash cannot un-ignore
# them, so without this shim the coordinator can never trap SIGINT and the INT
# cases fail (or hang in the launch window). The shim `execvp`s the coordinator,
# so `$!` still names it — the identity `kill -s "$sig" "$coord"` relies on. An
# absolute path so it resolves after the fixture `cd`s into its scratch tree.
PSR_SIGSHIM="$LIB/test/exec-with-default-signals.py"
PSR_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/devflow-psr.XXXXXX")"

# ── fixture builders ─────────────────────────────────────────────────────────
# A fixture tree is a miniature checkout: the coordinator anchors its REPO_ROOT to
# `<script dir>/../..`, so copying it into <tree>/lib/test gives that tree its own
# run root, and nothing here can write into the real checkout.
psr_make_tree() { # -> prints a fresh fixture tree root
  local tree
  tree="$(mktemp -d "$PSR_ROOT/tree.XXXXXX")"
  mkdir -p "$tree/lib/test"
  cp "$PSR_COORD" "$tree/lib/test/run-parallel.sh"
  cp "$PSR_TALLY" "$tree/lib/test/shard-tally.py"
  chmod +x "$tree/lib/test/run-parallel.sh"
  printf '%s\n' "$tree"
}

# A dispatcher that answers --list-shards from SYN_SHARDS, records a start/end
# timestamp plus its inherited TMPDIR and pool width, and writes a real tally.
psr_plant_dispatcher() { # tree
  local tree="$1"
  cat > "$tree/dispatch.sh" <<'PSR_EOF'
#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
case "${1-}" in
  --list-shards) printf '%s\n' ${SYN_SHARDS:-alpha beta python-pool}; exit 0 ;;
esac
S="$1"
D="${DEVFLOW_SHARD_TALLY_DIR:?}"
mkdir -p "$D"
if [ -n "${SYN_TRACE:-}" ]; then
  # Keyword only, no timestamp: `date +%s%N` is GNU-only (BSD/macOS emit a literal N),
  # and the overlap reader below counts start/end keywords, never a clock value.
  printf 'start %s\n' "$S" >> "$SYN_TRACE"
  printf 'env %s tmpdir=%s poolwidth=%s\n' "$S" "${TMPDIR:-}" "${DEVFLOW_POOL_WIDTH:-}" >> "$SYN_TRACE"
fi
sleep "${SYN_SLEEP:-0.4}"
[ -z "${SYN_TRACE:-}" ] || printf 'end %s\n' "$S" >> "$SYN_TRACE"
LOG="$D/log.txt"
printf 'assertion noise that must not be replayed\n2 passed, 0 failed\n' > "$LOG"
python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith \
  --log "$LOG" --rc 0 --out "$D" >/dev/null
PSR_EOF
  chmod +x "$tree/dispatch.sh"
}

# Count how many shards were live at once, from the trace's start/end ordering.
# Derived with bash builtins: the value decides an asserted operand, so it must not
# depend on a tool the project's preflight does not guarantee (CLAUDE.md guard-class 2).
psr_max_overlap() { # trace-file
  local line kind live=0 max=0
  while IFS= read -r line || [ -n "$line" ]; do
    kind="${line%% *}"
    case "$kind" in
      start) live=$((live + 1)); [ "$live" -le "$max" ] || max="$live" ;;
      end) live=$((live - 1)) ;;
      *) : ;;
    esac
  done < "$1"
  printf '%s\n' "$max"
}

# Print the recorded pool width for one shard ("(absent)" when the shard inherited none).
psr_pool_width_of() { # trace-file shard
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "env $2 "*)
        line="${line##*poolwidth=}"
        [ -n "$line" ] || line="(absent)"
        printf '%s\n' "$line"
        return 0
        ;;
    esac
  done < "$1"
  printf '(no-record)\n'
}

# The shards that were live before ANY shard had finished — i.e. the set the scheduler
# packed at t=0. Read from the trace's own ordering, which is causally safe rather than
# raced: a queued shard is launched only after `_reap_finished` observes a child's exit,
# and a child writes its `end` keyword before exiting, so no later launch can precede an
# earlier finish in this file. The ORDER within that set is not asserted anywhere (three
# shards racing to append are free to interleave); only its membership is.
psr_starts_before_first_end() { # trace-file -> space-joined shard names
  local line names=""
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "start "*) names="$names ${line#start }" ;;
      "end "*) break ;;
    esac
  done < "$1"
  printf '%s\n' "${names# }"
}

# Count lines in a file with builtins alone (same guard-class-2 reason as above).
psr_count_matching() { # file prefix
  local line n=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in "$2"*) n=$((n + 1)) ;; esac
  done < "$1"
  printf '%s\n' "$n"
}

# ── population, overlap, budget, and the nested-pool reservation ──────────────
PSR_T1="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T1"

PSR_TRACE="$PSR_T1/trace-8"
( cd "$PSR_T1" && SYN_TRACE="$PSR_TRACE" DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" \
    DEVFLOW_SUITE_PROCESS_BUDGET=8 bash lib/test/run-parallel.sh > "$PSR_T1/out-8" 2>&1 )
assert_eq "psr population: budget 8 → clean aggregate, exit 0" "0" "$?"
assert_eq "psr population: budget 8 → all three returned shards overlap" "3" \
  "$(psr_max_overlap "$PSR_TRACE")"
# The population must come FROM the dispatcher: assert the coordinator's own roster line
# for a dispatcher returning a NON-DEFAULT list, so a coordinator that carried a hardcoded
# shard list of its own could not satisfy it.
PSR_DERIVED="$(cd "$PSR_T1" && SYN_SHARDS="zeta eta" SYN_SLEEP=0.05 \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr population: the roster is the dispatcher's returned list, not a list of the coordinator's own" "yes" \
  "$(case "$PSR_DERIVED" in *"shard roster: zeta eta"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr population: a dispatcher-returned name the coordinator has never heard of still launches" "yes" \
  "$(case "$PSR_DERIVED" in *"launched shard zeta"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr population: the aggregate sums every shard's tally" "yes" \
  "$(case "$(cat "$PSR_T1/out-8")" in *"6 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"

# The nested Python pool's width is a RESERVATION out of the same total, exported to
# the shard that owns it and to no other — a sibling that also read a width would
# multiply the process count past the budget the scheduler thinks it is enforcing.
# The value is 2 rather than `BUDGET - 1` = 7 because POOL_RESERVATION_CEILING caps it, so
# this is also the assertion that the ceiling is applied at all.
assert_eq "psr population: python-pool receives the nested-pool reservation" "2" \
  "$(psr_pool_width_of "$PSR_TRACE" python-pool)"
assert_eq "psr population: a normal shard receives no pool reservation" "(absent)" \
  "$(psr_pool_width_of "$PSR_TRACE" alpha)"
# The two assertions above prove the coordinator routes the reservation to a shard NAMED
# `python-pool`, but they prove it against a synthetic dispatcher that hardcodes the name.
# Nothing else reconciles that literal with the real population, so renaming the shard in
# run-shard.sh would make the reservation inert while every synthetic case stayed green.
# This closes that half: the real dispatcher must still emit the name the routing is keyed
# on. `--list-shards` prints and exits, so it launches no suite from inside this module.
PSR_REAL_SHARDS="$(bash "$LIB/test/run-shard.sh" --list-shards 2>/dev/null)"
assert_eq "psr population: the real dispatcher still returns the shard name the pool reservation is keyed on" "yes" \
  "$(PSR_HIT=no
     while IFS= read -r l || [ -n "$l" ]; do
       case "$l" in python-pool) PSR_HIT=yes ;; esac
     done <<PSR_EOD
$PSR_REAL_SHARDS
PSR_EOD
     printf '%s\n' "$PSR_HIT")"
# Private per-shard TMPDIRs are what make one shared checkout safe for concurrent
# shards; two shards handed the same temp root would collide on every mktemp name.
assert_eq "psr population: each shard is handed its own private TMPDIR" "yes" \
  "$(PSR_TA=""; PSR_TB=""
     while IFS= read -r l || [ -n "$l" ]; do
       case "$l" in
         "env alpha "*) PSR_TA="${l#*tmpdir=}"; PSR_TA="${PSR_TA%% *}" ;;
         "env beta "*) PSR_TB="${l#*tmpdir=}"; PSR_TB="${PSR_TB%% *}" ;;
       esac
     done < "$PSR_TRACE"
     { [ -n "$PSR_TA" ] && [ -n "$PSR_TB" ] && [ "$PSR_TA" != "$PSR_TB" ]; } && echo yes || echo no)"
# The per-shard TMPDIR must be OUTSIDE the checkout, not merely distinct. A shard's own
# assertions build fixture trees with `mktemp -d`, and a whole class of this suite's
# checks (non-git tree, bare tree, pwd fallback) is premised on the fixture NOT being
# inside a git working tree. A TMPDIR under the run root put every such fixture inside
# this repository and made the fallback under test unreachable — 129 failures across all
# five shards, none of them a real regression. Assert the property, not the path shape.
assert_eq "psr population: each shard's TMPDIR is outside the checkout (a fixture tree there is not in a git work tree)" "yes" \
  "$(PSR_TA=""
     while IFS= read -r l || [ -n "$l" ]; do
       case "$l" in "env alpha "*) PSR_TA="${l#*tmpdir=}"; PSR_TA="${PSR_TA%% *}" ;; esac
     done < "$PSR_TRACE"
     case "$PSR_TA" in "$PSR_T1"/*) echo no ;; "") echo no ;; *) echo yes ;; esac)"
assert_eq "psr population: the run announces the budget and the reservation it resolved" "yes" \
  "$(case "$(cat "$PSR_T1/out-8")" in *"process budget 8 (python-pool reservation 2)"*) echo yes ;; *) echo no ;; esac)"

PSR_TRACE2="$PSR_T1/trace-2"
( cd "$PSR_T1" && SYN_TRACE="$PSR_TRACE2" DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" \
    SYN_SHARDS="alpha beta" DEVFLOW_SUITE_PROCESS_BUDGET=2 bash lib/test/run-parallel.sh >/dev/null 2>&1 )
assert_eq "psr population: budget 2 → the returned shards still overlap" "2" \
  "$(psr_max_overlap "$PSR_TRACE2")"

# Width one is the fail-closed floor: serial, and COMPLETE — never a reduced population.
PSR_TRACE1="$PSR_T1/trace-1"
( cd "$PSR_T1" && SYN_TRACE="$PSR_TRACE1" DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" \
    DEVFLOW_SUITE_PROCESS_BUDGET=1 bash lib/test/run-parallel.sh > "$PSR_T1/out-1" 2>&1 )
assert_eq "psr population: budget 1 → exit 0" "0" "$?"
assert_eq "psr population: budget 1 → strictly serial (never two shards live at once)" "1" \
  "$(psr_max_overlap "$PSR_TRACE1")"
assert_eq "psr population: budget 1 → still complete (every shard ran)" "3" \
  "$(psr_count_matching "$PSR_TRACE1" "start ")"
assert_eq "psr population: budget 1 → the aggregate is the same total as budget 8" "yes" \
  "$(case "$(cat "$PSR_T1/out-1")" in *"6 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"

# ── the packing at the runner's own budget (issue #1180) ─────────────────────
# The cloud runner resolves BUDGET = min(cpu_count, BUDGET_CEILING) = 4, and at that budget
# the nested-pool reservation decides how many shards fit at t=0: at a reservation of 3
# `monolith` (1 slot) + `python-pool` (3) fill all four and every remaining shard queues
# behind ONE freed slot; at 2 a third shard launches immediately and the rest pipeline. That
# is the whole substance of POOL_RESERVATION_CEILING, so it is asserted as the PACKING the
# real scheduler produces — driven here through the coordinator's documented dispatcher seam
# over the real shard names in the real launch order — and never as the constant's value,
# which a source pin could assert without exercising anything.
PSR_T1B="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T1B"
PSR_TRACE4="$PSR_T1B/trace-4"
( cd "$PSR_T1B" && SYN_TRACE="$PSR_TRACE4" DEVFLOW_SHARD_DISPATCHER="$PSR_T1B/dispatch.sh" \
    SYN_SHARDS="monolith python-pool modules-pin modules-large modules-rest" \
    DEVFLOW_SUITE_PROCESS_BUDGET=4 bash lib/test/run-parallel.sh > "$PSR_T1B/out-4" 2>&1 )
assert_eq "psr packing: budget 4 over the real roster → clean aggregate, exit 0" "0" "$?"
PSR_PACK4="$(psr_starts_before_first_end "$PSR_TRACE4")"
assert_eq "psr packing: budget 4 → THREE shards are live before any shard has finished" "3" \
  "$(PSR_N=0; for psr_s in $PSR_PACK4; do PSR_N=$((PSR_N + 1)); done; printf '%s\n' "$PSR_N")"
assert_eq "psr packing: budget 4 → monolith, python-pool and the next roster shard are those three" "yes" \
  "$(PSR_HIT=0
     for psr_s in $PSR_PACK4; do
       case "$psr_s" in monolith|python-pool|modules-pin) PSR_HIT=$((PSR_HIT + 1)) ;; esac
     done
     [ "$PSR_HIT" -eq 3 ] && echo yes || echo no)"
# Scope stated honestly: this one bounds the BUDGET, not the ceiling. Verified by mutation
# — at a reservation of 3 the peak is also three (the pool's slots free together and the
# last two shards join `modules-pin`), so only the two assertions above discriminate the
# ceiling. It is kept because it is the assertion that a repacking never oversubscribes.
assert_eq "psr packing: budget 4 → no fourth shard is ever admitted (the budget still binds)" "3" \
  "$(psr_max_overlap "$PSR_TRACE4")"
# Overlap is never bought with coverage: the repacking must still run the whole population.
assert_eq "psr packing: budget 4 → every shard in the roster still ran" "5" \
  "$(psr_count_matching "$PSR_TRACE4" "start ")"
assert_eq "psr packing: budget 4 → the aggregate sums all five shards" "yes" \
  "$(case "$(cat "$PSR_T1B/out-4")" in *"10 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"

# The budget is a decided value, so a non-positive-integer override must not be
# honoured silently and an unestablished probe must fail closed rather than open.
for psr_bad in "" "0" "-3" "two" "3.5"; do
  PSR_OUT="$(cd "$PSR_T1" && DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" SYN_SHARDS=alpha \
      DEVFLOW_SUITE_PROCESS_BUDGET="$psr_bad" bash lib/test/run-parallel.sh 2>&1)"
  assert_eq "psr population: override '$psr_bad' is rejected, the probe decides, and the run still completes" "yes" \
    "$(case "$PSR_OUT" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
done
PSR_OUT="$(cd "$PSR_T1" && DEVFLOW_SHARD_DISPATCHER="$PSR_T1/dispatch.sh" SYN_SHARDS=alpha \
    DEVFLOW_SUITE_PROCESS_BUDGET=999 bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr population: the budget is capped at eight however large the override" "yes" \
  "$(case "$PSR_OUT" in *"process budget 8 "*) echo yes ;; *) echo no ;; esac)"

# ── isolation: a stale sibling run's tally never satisfies this invocation ────
PSR_T2="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T2"
( cd "$PSR_T2" && DEVFLOW_SHARD_DISPATCHER="$PSR_T2/dispatch.sh" SYN_SHARDS="alpha beta" \
    SYN_SLEEP=0.05 bash lib/test/run-parallel.sh >/dev/null 2>&1 )
# The second run must allocate a DIFFERENT root, and must aggregate only its own
# tallies — a `--scan` of the shared parent would have admitted the first run's.
( cd "$PSR_T2" && DEVFLOW_SHARD_DISPATCHER="$PSR_T2/dispatch.sh" SYN_SHARDS="alpha beta" \
    SYN_SLEEP=0.05 bash lib/test/run-parallel.sh > "$PSR_T2/out-2" 2>&1 )
# Counted with a glob, not `ls | grep`: a glob cannot be defeated by a name `ls`
# renders oddly, and the count decides an asserted operand.
assert_eq "psr isolation: consecutive runs allocate distinct run roots" "2" \
  "$(cd "$PSR_T2" && PSR_N=0; for psr_d in .prflow/tmp/parallel-suite/run-*; do
       [ -d "$psr_d" ] && PSR_N=$((PSR_N + 1)); done; printf '%s\n' "$PSR_N")"
assert_eq "psr isolation: the second run aggregates only its own two shards" "yes" \
  "$(case "$(cat "$PSR_T2/out-2")" in *"combine: 2 shard(s): alpha, beta"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr isolation: the second run's total is its own, not the pair of runs'" "yes" \
  "$(case "$(cat "$PSR_T2/out-2")" in *"4 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
# A stale sibling planted with the CURRENT run's shard names still must not count.
mkdir -p "$PSR_T2/.prflow/tmp/parallel-suite/run-stale/tally/gamma"
printf 'shard\tgamma\npassed\t99\nfailed\t0\nskipped\t0\nrc\t0\n' \
  > "$PSR_T2/.prflow/tmp/parallel-suite/run-stale/tally/gamma/summary"
: > "$PSR_T2/.prflow/tmp/parallel-suite/run-stale/tally/gamma/skips"
: > "$PSR_T2/.prflow/tmp/parallel-suite/run-stale/tally/gamma/names"
( cd "$PSR_T2" && DEVFLOW_SHARD_DISPATCHER="$PSR_T2/dispatch.sh" SYN_SHARDS="alpha beta" \
    SYN_SLEEP=0.05 bash lib/test/run-parallel.sh > "$PSR_T2/out-3" 2>&1 )
assert_eq "psr isolation: a planted stale tally directory does not reach the aggregate" "yes" \
  "$(case "$(cat "$PSR_T2/out-3")" in *"4 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr isolation: the stale shard name is absent from the roster line" "yes" \
  "$(case "$(cat "$PSR_T2/out-3")" in *"combine: 2 shard(s): alpha, beta"*) echo yes ;; *) echo no ;; esac)"

# ── failure contract ─────────────────────────────────────────────────────────
PSR_T3="$(psr_make_tree)"
cat > "$PSR_T3/dispatch.sh" <<'PSR_EOF'
#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
case "${1-}" in
  --list-shards)
    case "${SYN_MODE:-}" in
      empty) exit 0 ;;
      badname) printf '%s\n' 'Bad/Name'; exit 0 ;;
      listfail) exit 3 ;;
      dup) printf '%s\n' alpha beta alpha ;;
      *) if [ -n "${SYN_SERIAL:-}" ]; then printf '%s\n' alpha beta gamma; else printf '%s\n' alpha beta; fi ;;
    esac
    exit 0 ;;
esac
S="$1"; D="${DEVFLOW_SHARD_TALLY_DIR:?}"; mkdir -p "$D"
case "${SYN_MODE:-}" in
  crash) [ "$S" = beta ] && { printf 'shard crashed\n' >&2; exit 7; } ;;
  notally-zero) [ "$S" = beta ] && exit 0 ;;
  # EVERY shard exits clean without a tally, so the coordinator reaches the aggregation
  # step with an empty tally-path list — the one input shape that expands an empty array.
  notally-all) exit 0 ;;
  nonzero) [ "$S" = beta ] && { printf '1 passed, 1 failed\n' > "$D/log.txt"
      python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith \
        --log "$D/log.txt" --rc 1 --out "$D" >/dev/null; exit 1; } ;;
  malformed) [ "$S" = beta ] && { printf 'shard\tbeta\npassed\tnot-a-number\n' > "$D/summary"; exit 0; } ;;
  skipdis) [ "$S" = beta ] && {
      printf 'shard\tbeta\npassed\t1\nfailed\t0\nskipped\t0\nrc\t0\n' > "$D/summary"
      printf 'a skip nothing announced\n' > "$D/skips"; : > "$D/names"; exit 0; } ;;
  killed-after-tally) [ "$S" = beta ] && {
      # The OOM-killer shape: the tally is complete and CLEAN, and the process then dies
      # non-zero. Nothing in the tally records the death, so only the coordinator's own
      # reading of the child's exit status can catch it.
      printf '1 passed, 0 failed\n' > "$D/log.txt"
      python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith \
        --log "$D/log.txt" --rc 0 --out "$D" >/dev/null
      exit 9; } ;;
esac
printf '1 passed, 0 failed\n' > "$D/log.txt"
python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith \
  --log "$D/log.txt" --rc 0 --out "$D" >/dev/null
PSR_EOF
chmod +x "$PSR_T3/dispatch.sh"

psr_fail_case() { # mode -> prints "<rc>|<combined output>"
  local mode="$1" out rc
  out="$(cd "$PSR_T3" && SYN_MODE="$mode" DEVFLOW_SHARD_DISPATCHER="$PSR_T3/dispatch.sh" \
    bash lib/test/run-parallel.sh 2>&1)"
  rc=$?
  printf '%s|%s' "$rc" "$out"
}

PSR_FC="$(psr_fail_case empty)"
assert_eq "psr failure: an empty shard population is refused, not reported clean" "yes" \
  "$(case "$PSR_FC" in 2\|*"empty population"*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case badname)"
assert_eq "psr failure: a malformed shard name is refused by name" "yes" \
  "$(case "$PSR_FC" in 2\|*"malformed shard name"*"Bad/Name"*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case listfail)"
assert_eq "psr failure: a dispatcher that cannot list its shards is refused by name" "yes" \
  "$(case "$PSR_FC" in 2\|*"failed to list its shards"*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case crash)"
assert_eq "psr failure: a crashed shard yields a nonzero aggregate" "yes" \
  "$(case "$PSR_FC" in 1\|*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: a crashed shard is named, with its exit status" "yes" \
  "$(case "$PSR_FC" in *"exited non-zero"*"beta=7"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: a shard that wrote no tally is named as such" "yes" \
  "$(case "$PSR_FC" in *"produced no tally"*beta*) echo yes ;; *) echo no ;; esac)"
# EVERY shard writing no tally is the boundary of the case above: the tally-path list the
# aggregation step passes is empty, so this is the shape that expands an empty array. The
# refusal must still come from the coordinator's own named diagnostic and the aggregate
# path, not from an interpreter-level abort. Scope stated honestly: on a bash 4.4+ host the
# guarded and bare expansions behave identically, so this covers the aggregation path
# rather than discriminating the guard — no host here can run the pre-4.4 arm.
PSR_FC="$(psr_fail_case notally-all)"
assert_eq "psr failure: every shard writing no tally still refuses through the named diagnostic" "yes" \
  "$(case "$PSR_FC" in 1\|*"produced no tally"*alpha*beta*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: that refusal reaches the aggregate line rather than aborting before it" "yes" \
  "$(case "$PSR_FC" in *"aggregate FAILED"*) echo yes ;; *) echo no ;; esac)"
# issue #1808: on the FAILED path the aggregate verdict goes to STDERR, so capture stdout
# ALONE — this proves the elapsed line still reaches stdout there; a 2>&1 capture would not.
PSR_FAIL_OUT="$(cd "$PSR_T3" && SYN_MODE=notally-all DEVFLOW_SHARD_DISPATCHER="$PSR_T3/dispatch.sh" bash lib/test/run-parallel.sh 2>/dev/null)"
assert_eq "psr failure: a failed run prints the coordinator's elapsed line to stdout (issue #1808)" "yes" \
  "$(case "$PSR_FAIL_OUT" in *"run-parallel: elapsed "[0-9]*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case nonzero)"
assert_eq "psr failure: a shard reporting a failed assertion fails the aggregate" "yes" \
  "$(case "$PSR_FC" in 1\|*"1 failed"*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case malformed)"
assert_eq "psr failure: a malformed tally fails closed with a PROBLEM naming it" "yes" \
  "$(case "$PSR_FC" in 1\|*PROBLEM*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case skipdis)"
assert_eq "psr failure: a skip-detail disagreement fails the aggregate" "yes" \
  "$(case "$PSR_FC" in 1\|*"disagrees with"*) echo yes ;; *) echo no ;; esac)"
# A shard killed AFTER writing a clean tally: the aggregate sums green and no shard is
# missing, so the child's exit status is the ONLY surviving signal. A coordinator that
# merely printed it would exit 0 while announcing that a shard did not complete.
PSR_FC="$(psr_fail_case killed-after-tally)"
assert_eq "psr failure: a shard killed after writing a clean tally still fails the aggregate" "1" \
  "${PSR_FC%%|*}"
assert_eq "psr failure: that shard's non-zero exit is named as the refusal reason" "yes" \
  "$(case "$PSR_FC" in *"exited non-zero"*"beta=9"*"refusing a clean aggregate"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: the killed shard's tally still summed green (so the exit status was the only signal)" "yes" \
  "$(case "$PSR_FC" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
# A duplicated shard name would put two processes in ONE tally directory, double-count it
# through --expect, and silently drop whichever shard the duplicate displaced.
PSR_FC="$(psr_fail_case dup)"
assert_eq "psr failure: a duplicated shard name is refused before anything is launched" "yes" \
  "$(case "$PSR_FC" in 2\|*"duplicate shard name"*alpha*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: the duplicate refusal launches no shard at all" "yes" \
  "$(case "$PSR_FC" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
# Launch failure: a shard whose private tally/temp directories cannot be created. The
# run root is fresh by construction, so the only honest way to reach this arm is to
# revoke write permission on it WHILE the coordinator is mid-launch — which the launch
# window seam makes deterministic: the first shard is held there, the test revokes, and
# the second shard's directory creation then fails.
PSR_T3B="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T3B"
PSR_LF_WIN="$PSR_T3B/lf-win"
# issue #1216: this backgrounded coordinator is DELIBERATELY not routed through
# the SIGINT-restoring shim (unlike the signalled cases below). It is released
# through its own window file and `wait`ed — it is never `kill`ed — so the
# inherited-SIG_IGN defect that shim fixes cannot reach it. Left unchanged so the
# launch-failure path under test stays byte-for-byte what it was.
( cd "$PSR_T3B" || exit 1
  export SYN_SHARDS="alpha beta" SYN_SLEEP=0.05 \
    DEVFLOW_TEST_LAUNCH_WINDOW_FILE="$PSR_LF_WIN" \
    DEVFLOW_SHARD_DISPATCHER="$PSR_T3B/dispatch.sh"
  exec bash lib/test/run-parallel.sh > "$PSR_T3B/lf-out" 2>&1 ) &
PSR_LF_PID=$!
while [ ! -e "$PSR_LF_WIN" ]; do sleep 0.01; done
PSR_LF_ROOT="$(cd "$PSR_T3B" && PSR_LAST=""; for psr_d in .prflow/tmp/parallel-suite/run-*; do
  [ -d "$psr_d" ] && PSR_LAST="$psr_d"; done; printf '%s\n' "$PSR_LAST")"
# Plant a regular FILE where the second shard's tally directory must go, rather than
# revoking write permission: a chmod is unenforced for a privileged user, so under a root
# CI container this assertion would go red for a host reason. `mkdir -p` over an existing
# non-directory fails for every user.
: > "$PSR_T3B/$PSR_LF_ROOT/tally/beta"
: > "$PSR_LF_WIN.release"
wait "$PSR_LF_PID"
assert_eq "psr failure: a launch failure yields a nonzero aggregate" "1" "$?"
PSR_LF_OUT="$(cat "$PSR_T3B/lf-out")"
assert_eq "psr failure: a shard whose private directories cannot be created is named" "yes" \
  "$(case "$PSR_LF_OUT" in *"could not create its private tally/temp directories"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: the un-launched shard is named in the launch-failure list" "yes" \
  "$(case "$PSR_LF_OUT" in *"failed to launch"*beta*) echo yes ;; *) echo no ;; esac)"

# The mid-loop reaper is a SECOND, independent copy of the status-capture logic: at the
# probed budget with two shards nothing ever queues, so every non-zero status above was
# collected by the final wait loop instead. Width 1 with three shards forces the failing
# shard to be reaped by the queueing loop — the exact path a broken `python3` probe
# degrades every real run to.
psr_fail_case_serial() { # mode -> prints "<rc>|<combined output>"
  local mode="$1" out rc
  out="$(cd "$PSR_T3" && SYN_MODE="$mode" SYN_SERIAL=1 DEVFLOW_SUITE_PROCESS_BUDGET=1 \
    DEVFLOW_SHARD_DISPATCHER="$PSR_T3/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
  rc=$?
  printf '%s|%s' "$rc" "$out"
}
PSR_FC="$(psr_fail_case_serial crash)"
assert_eq "psr failure: at width 1 a crashed shard reaped by the queueing loop still fails the aggregate" "1" \
  "${PSR_FC%%|*}"
assert_eq "psr failure: the queueing loop records the crashed shard's status by name" "yes" \
  "$(case "$PSR_FC" in *"exited non-zero"*"beta=7"*) echo yes ;; *) echo no ;; esac)"
PSR_FC="$(psr_fail_case_serial killed-after-tally)"
assert_eq "psr failure: at width 1 a shard killed after a clean tally still fails the aggregate" "1" \
  "${PSR_FC%%|*}"
assert_eq "psr failure: the queueing loop records that shard's exit status too" "yes" \
  "$(case "$PSR_FC" in *"beta=9"*"refusing a clean aggregate"*) echo yes ;; *) echo no ;; esac)"

# --expect is the missing-shard floor, and in the crash cases above two other mechanisms
# also force rc 1. Give it a case where it is the ONLY signal: a shard that writes no
# tally and exits ZERO — `MISSING` names it, but no non-zero status exists to catch it.
PSR_FC="$(psr_fail_case notally-zero)"
assert_eq "psr failure: a shard that writes no tally and exits ZERO still fails the aggregate" "1" \
  "${PSR_FC%%|*}"
assert_eq "psr failure: the missing-shard floor is what names it (no non-zero status exists to)" "yes" \
  "$(case "$PSR_FC" in *"expected 2 shard tally directories but found 1"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: that shard is reported as producing no tally" "yes" \
  "$(case "$PSR_FC" in *"produced no tally"*beta*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: no non-zero shard status is claimed for it" "yes" \
  "$(case "$PSR_FC" in *"exited non-zero"*) echo no ;; *) echo yes ;; esac)"

# A checkout path containing a space: the tally paths must reach `combine` as N distinct
# arguments, not as word-split fragments that satisfy the --expect floor from garbage.
PSR_T3C="$(mktemp -d "$PSR_ROOT/with space.XXXXXX")"
mkdir -p "$PSR_T3C/lib/test"
cp "$PSR_COORD" "$PSR_T3C/lib/test/run-parallel.sh"
cp "$PSR_TALLY" "$PSR_T3C/lib/test/shard-tally.py"
chmod +x "$PSR_T3C/lib/test/run-parallel.sh"
psr_plant_dispatcher "$PSR_T3C"
PSR_SPACE_OUT="$(cd "$PSR_T3C" && SYN_SHARDS="alpha beta" SYN_SLEEP=0.05 \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T3C/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr failure: a checkout path containing a space still aggregates cleanly" "yes" \
  "$(case "$PSR_SPACE_OUT" in *"4 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr failure: a space in the path produces no split/unreadable tally PROBLEM" "yes" \
  "$(case "$PSR_SPACE_OUT" in *PROBLEM*) echo no ;; *) echo yes ;; esac)"

# ── reentrancy ───────────────────────────────────────────────────────────────
PSR_T4="$(psr_make_tree)"
cat > "$PSR_T4/dispatch.sh" <<'PSR_EOF'
#!/usr/bin/env bash
set -u
case "${1-}" in --list-shards) printf '%s\n' alpha; exit 0 ;; esac
HERE="$(cd "$(dirname "$0")" && pwd -P)"
cd "$HERE" || exit 9
env -u DEVFLOW_SHARD_DISPATCHER bash lib/test/run-parallel.sh
PSR_EOF
chmod +x "$PSR_T4/dispatch.sh"
( cd "$PSR_T4" && DEVFLOW_SHARD_DISPATCHER="$PSR_T4/dispatch.sh" bash lib/test/run-parallel.sh \
    > "$PSR_T4/out" 2>&1 )
assert_eq "psr reentrancy: a real-population invocation from inside a shard is refused by name" "yes" \
  "$(case "$(cat "$PSR_T4"/.prflow/tmp/parallel-suite/run-*/logs/alpha.log)" in *reentrancy*) echo yes ;; *) echo no ;; esac)"
# The other limb of the same predicate, and the reason this module can run from inside a
# shard at all: a FIXTURE invocation naming its own dispatcher is exempt. Widening the
# guard to unconditional would make every assertion above unreachable, so pin the
# carve-out rather than leaving it to a suite-wide red to reveal.
PSR_T4B="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T4B"
PSR_CARVE="$(cd "$PSR_T4B" && DEVFLOW_PARALLEL_SUITE_ACTIVE=1 SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T4B/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr reentrancy: a fixture invocation naming its own dispatcher is exempt and still runs" "yes" \
  "$(case "$PSR_CARVE" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr reentrancy: the exempt invocation is not refused" "yes" \
  "$(case "$PSR_CARVE" in *reentrancy*) echo no ;; *) echo yes ;; esac)"

# ── signal handling: before and after PID registration ───────────────────────
PSR_T5="$(psr_make_tree)"
cat > "$PSR_T5/dispatch.sh" <<'PSR_EOF'
#!/usr/bin/env bash
set -u
case "${1-}" in --list-shards) printf '%s\n' alpha beta; exit 0 ;; esac
# A resistant child: it ignores the polite signals, so only the coordinator's
# escalation-and-reap can clear it.
trap '' HUP INT TERM
printf '%s\n' "$$" >> "${SYN_PIDFILE:?}"
sleep 30
PSR_EOF
chmod +x "$PSR_T5/dispatch.sh"

psr_signal_case() { # signal window(pre|post) -> prints "<rc>|<alive-count>|<acknowledged>"
  local sig="$1" window="$2" pidfile winfile coord rc alive=0 p ack=no
  pidfile="$PSR_T5/pids-$sig-$window"; winfile="$PSR_T5/win-$sig-$window"
  : > "$pidfile"; rm -f "$winfile" "$winfile.release"
  # `exec` is load-bearing: without it the backgrounded SUBSHELL is what `$!` names, so
  # the signal would reach that shell (dying 128+sig) and leave the coordinator running
  # as an orphan — the test would then measure the subshell's default disposition rather
  # than the coordinator's handler.
  if [ "$window" = pre ]; then
    ( cd "$PSR_T5" || exit 1
      export SYN_PIDFILE="$pidfile" DEVFLOW_TEST_LAUNCH_WINDOW_FILE="$winfile" \
        DEVFLOW_SHARD_DISPATCHER="$PSR_T5/dispatch.sh"
      exec python3 "$PSR_SIGSHIM" bash lib/test/run-parallel.sh > "$PSR_T5/out-$sig-$window" 2>&1 ) &
    coord=$!
    while [ ! -e "$winfile" ]; do sleep 0.01; done
  else
    ( cd "$PSR_T5" || exit 1
      export SYN_PIDFILE="$pidfile" DEVFLOW_SHARD_DISPATCHER="$PSR_T5/dispatch.sh"
      exec python3 "$PSR_SIGSHIM" bash lib/test/run-parallel.sh > "$PSR_T5/out-$sig-$window" 2>&1 ) &
    coord=$!
    # Wait until both shard children have published their PIDs, i.e. both are
    # registered. Counted with builtins, never a PATH tool (guard-class 2).
    while [ "$(psr_count_matching "$pidfile" "")" -lt 2 ]; do sleep 0.05; done
  fi
  kill -s "$sig" "$coord" 2>/dev/null || :
  wait "$coord"; rc=$?
  # Give the escalation a moment, then count survivors.
  sleep 0.5
  while IFS= read -r p || [ -n "$p" ]; do
    [ -z "$p" ] || { kill -0 "$p" 2>/dev/null && alive=$((alive + 1)); }
  done < "$pidfile"
  while IFS= read -r p || [ -n "$p" ]; do
    case "$p" in *"received $sig"*) ack=yes ;; esac
  done < "$PSR_T5/out-$sig-$window"
  printf '%s|%s|%s' "$rc" "$alive" "$ack"
}

for psr_sig in HUP INT TERM; do
  PSR_SC="$(psr_signal_case "$psr_sig" post)"
  assert_eq "psr signal: $psr_sig after registration → exits 1, acknowledges the signal, and every launched shard is reaped" \
    "1|0|yes" "$PSR_SC"
  # A signal delivered inside the LAUNCH WINDOW must be PARKED and REPLAYED, not dropped:
  # a coordinator that swallowed it would run the population to completion and exit 0,
  # which is what this comparison refuses (verified by mutation — deleting the replay
  # line turns this assertion RED). Scope stated honestly: the seam holds the run just
  # BEFORE the fork, so no child is registered yet and the survivor count is not a
  # discriminator here; this proves the park-and-replay path, not the narrower
  # between-`&`-and-`$!` instant, which no portable seam can hold open.
  PSR_SC="$(psr_signal_case "$psr_sig" pre)"
  assert_eq "psr signal: $psr_sig parked in the launch window is replayed, not swallowed" \
    "1|0|yes" "$PSR_SC"
done

# The third window: a signal arriving while a shard is QUEUED behind the budget. It lands
# in the slot-wait loop, where LAUNCHING is 0, so the handler itself is the one the `post`
# case already covers. What is distinct — and what neither case above can observe — is the
# QUEUE: a coordinator that returned to the scheduling loop would fork new shards while it
# was tearing the launched ones down. Budget 1 makes the state deterministic rather than
# timed: alpha holds the only slot for its full sleep, so beta is parked in the slot-wait
# for as long as the case needs, and one published PID is exactly the state under test.
PSR_Q_PIDS="$PSR_T5/pids-queued"; : > "$PSR_Q_PIDS"
( cd "$PSR_T5" || exit 1
  export SYN_PIDFILE="$PSR_Q_PIDS" DEVFLOW_SHARD_DISPATCHER="$PSR_T5/dispatch.sh" \
    DEVFLOW_SUITE_PROCESS_BUDGET=1
  exec python3 "$PSR_SIGSHIM" bash lib/test/run-parallel.sh > "$PSR_T5/out-queued" 2>&1 ) &
PSR_Q_COORD=$!
while [ "$(psr_count_matching "$PSR_Q_PIDS" "")" -lt 1 ]; do sleep 0.05; done
kill -s TERM "$PSR_Q_COORD" 2>/dev/null || :
wait "$PSR_Q_COORD"; PSR_Q_RC=$?
sleep 0.5
assert_eq "psr signal: a signal while a shard is queued behind the budget still exits 1" \
  "1" "$PSR_Q_RC"
assert_eq "psr signal: the queued shard is never launched after the signal" "yes" \
  "$(case "$(cat "$PSR_T5/out-queued")" in *"launched shard beta"*) echo no ;; *) echo yes ;; esac)"
assert_eq "psr signal: the shard that held the slot is still reaped" "0" \
  "$(PSR_N=0
     while IFS= read -r p || [ -n "$p" ]; do
       [ -z "$p" ] || { kill -0 "$p" 2>/dev/null && PSR_N=$((PSR_N + 1)); }
     done < "$PSR_Q_PIDS"
     printf '%s\n' "$PSR_N")"

# ── output contract: clean-run suppression, the detail cap, retained logs ─────
PSR_T6="$(psr_make_tree)"
cat > "$PSR_T6/dispatch.sh" <<'PSR_EOF'
#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
case "${1-}" in --list-shards) printf '%s\n' alpha; exit 0 ;; esac
S="$1"; D="${DEVFLOW_SHARD_TALLY_DIR:?}"; mkdir -p "$D"
LOG="$D/log.txt"
: > "$LOG"
i=0
while [ "$i" -lt 40 ]; do printf 'PASS  assertion-noise-%s\n' "$i" >> "$LOG"; i=$((i + 1)); done
if [ -n "${SYN_BULK:-}" ]; then
  printf '0 passed, 25 failed, 25 skipped\n' >> "$LOG"
  i=0; while [ "$i" -lt 25 ]; do printf '  SKIP  synthetic-skip-%s\n' "$i" >> "$LOG"; i=$((i + 1)); done
  printf 'Failure recap:\n' >> "$LOG"
  i=0; while [ "$i" -lt 25 ]; do printf '  - synthetic-failure-%s\n' "$i" >> "$LOG"; i=$((i + 1)); done
  # Echo the captured log the way the real dispatcher does, so the coordinator's
  # per-shard capture holds the complete detail the cap elides from the aggregate.
  cat "$LOG"
  python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith --log "$LOG" --rc 1 --out "$D" >/dev/null
  exit 1
fi
printf '3 passed, 0 failed\n' >> "$LOG"
cat "$LOG"
python3 "$HERE/lib/test/shard-tally.py" extract --shard "$S" --tier monolith --log "$LOG" --rc 0 --out "$D" >/dev/null
PSR_EOF
chmod +x "$PSR_T6/dispatch.sh"

PSR_CLEAN="$(cd "$PSR_T6" && DEVFLOW_SHARD_DISPATCHER="$PSR_T6/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr output: a clean run does not replay the shard's assertion log" "yes" \
  "$(case "$PSR_CLEAN" in *assertion-noise-*) echo no ;; *) echo yes ;; esac)"
assert_eq "psr output: a clean run states the combined result" "yes" \
  "$(case "$PSR_CLEAN" in *"3 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: a clean run emits the launch lifecycle breadcrumb" "yes" \
  "$(case "$PSR_CLEAN" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: a clean run names the shard roster" "yes" \
  "$(case "$PSR_CLEAN" in *"shard roster: alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: a clean run names the retained-log root" "yes" \
  "$(case "$PSR_CLEAN" in *"retained logs: "*/logs*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: a clean run says so" "yes" \
  "$(case "$PSR_CLEAN" in *"aggregate CLEAN"*) echo yes ;; *) echo no ;; esac)"
# issue #1808: capture stdout ALONE (not 2>&1) so this tests the elapsed line is on
# STDOUT — a 2>&1 capture would pass even if the line wrongly went to stderr.
PSR_CLEAN_OUT="$(cd "$PSR_T6" && DEVFLOW_SHARD_DISPATCHER="$PSR_T6/dispatch.sh" bash lib/test/run-parallel.sh 2>/dev/null)"
assert_eq "psr output: a clean run prints the coordinator's elapsed line to stdout (issue #1808)" "yes" \
  "$(case "$PSR_CLEAN_OUT" in *"run-parallel: elapsed "[0-9]*) echo yes ;; *) echo no ;; esac)"

PSR_BULK="$(cd "$PSR_T6" && SYN_BULK=1 DEVFLOW_SHARD_DISPATCHER="$PSR_T6/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
PSR_SKIP_LINES=0; PSR_FAIL_LINES=0
while IFS= read -r psr_line || [ -n "$psr_line" ]; do
  case "$psr_line" in
    "  SKIP  synthetic-skip-"*) PSR_SKIP_LINES=$((PSR_SKIP_LINES + 1)) ;;
    "  - synthetic-failure-"*) PSR_FAIL_LINES=$((PSR_FAIL_LINES + 1)) ;;
  esac
done <<PSR_BULK_EOF
$PSR_BULK
PSR_BULK_EOF
assert_eq "psr output: 25 skip entries render 20 detail lines (the enforcement cap)" "20" "$PSR_SKIP_LINES"
assert_eq "psr output: 25 failure entries render 20 detail lines (the enforcement cap)" "20" "$PSR_FAIL_LINES"
assert_eq "psr output: the capped skip class announces the omitted count" "yes" \
  "$(case "$PSR_BULK" in *"SKIP  (5 omitted"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: the capped failure class announces the omitted count" "yes" \
  "$(case "$PSR_BULK" in *"- (5 omitted"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr output: the announced tally is the FULL count, not the capped one" "yes" \
  "$(case "$PSR_BULK" in *"0 passed, 25 failed, 25 skipped"*) echo yes ;; *) echo no ;; esac)"
# The cap bounds what is RENDERED, never what is RETAINED.
PSR_BULK_LOG="$(cd "$PSR_T6" && PSR_LAST=""; for psr_d in .prflow/tmp/parallel-suite/run-*; do
  [ -d "$psr_d" ] && PSR_LAST="$psr_d"; done; printf '%s\n' "$PSR_LAST")/logs/alpha.log"
assert_eq "psr output: the complete synthetic log stays readable under the retained run root" "yes" \
  "$(cd "$PSR_T6" && [ -r "$PSR_BULK_LOG" ] && echo yes || echo no)"
assert_eq "psr output: every one of the 25 skip entries survives in the retained log" "25" \
  "$(cd "$PSR_T6" && psr_count_matching "$PSR_BULK_LOG" "  SKIP  synthetic-skip-")"

# ── run-shard.sh names the log it retained, on pass AND fail (issue #1923) ────
# A reader who tail-piped run-shard.sh's echoed log away (CLAUDE.md's `| tail -<n>`)
# must re-read the retained log, not re-execute the shard; assert it is named on both.
PSR_RS_TREE="$(mktemp -d "$PSR_ROOT/rs.XXXXXX")"
mkdir -p "$PSR_RS_TREE/lib/test"
cp "$LIB/test/run-shard.sh" "$PSR_RS_TREE/lib/test/run-shard.sh"
cp "$PSR_TALLY" "$PSR_RS_TREE/lib/test/shard-tally.py"
chmod +x "$PSR_RS_TREE/lib/test/run-shard.sh"
cat > "$PSR_RS_TREE/lib/test/run.sh" <<'PSR_EOF'
#!/usr/bin/env bash
if [ -n "${PSR_RS_FAIL:-}" ]; then printf '0 passed, 1 failed\n'; exit 1; fi
printf '1 passed, 0 failed\n'
PSR_EOF
chmod +x "$PSR_RS_TREE/lib/test/run.sh"
# One row per exit ("" = passing shard, "1" = failing via PSR_RS_FAIL): the fail case is
# not redundant — it catches a future edit that gates the printf behind a success-only
# path, which run-shard.sh must never do since the log is retained on both outcomes.
for psr_rs_fail in "" "1"; do
  [ -z "$psr_rs_fail" ] && psr_rs_label=passing || psr_rs_label=failing
  psr_rs_tally="$PSR_RS_TREE/tally-$psr_rs_label"
  psr_rs_out="$(cd "$PSR_RS_TREE" && PSR_RS_FAIL="$psr_rs_fail" DEVFLOW_SHARD_TALLY_DIR="$psr_rs_tally" \
    bash lib/test/run-shard.sh monolith 2>&1)"
  mkdir -p "$psr_rs_tally"
  psr_rs_exp="$(cd "$psr_rs_tally" && pwd -P)/log.txt"
  assert_eq "psr run-shard: a $psr_rs_label shard names its retained log by absolute path" "yes" \
    "$(case "$psr_rs_out" in *"retained log: $psr_rs_exp"*) echo yes ;; *) echo no ;; esac)"
done

# A RELATIVE tally dir must still yield an ABSOLUTE retained-log path — the guarantee
# issue #1923's AC names, and the one a `printf "$LOG_FILE"` regression (dropping the
# pwd -P canonicalization) would break while an already-absolute fixture stayed green.
PSR_RS_OUT_REL="$(cd "$PSR_RS_TREE" && DEVFLOW_SHARD_TALLY_DIR="rel-tally" \
  bash lib/test/run-shard.sh monolith 2>&1)"
assert_eq "psr run-shard: a relative tally dir still yields an absolute retained-log path" "yes" \
  "$(case "$PSR_RS_OUT_REL" in *"retained log: /"*) echo yes ;; *) echo no ;; esac)"

# ── shard-tally.py --detail-cap, driven directly ─────────────────────────────
# The coordinator only ever exercises cap 20. CI's aggregator omits the flag entirely,
# and "CI's output is unchanged" is the guarantee that carries the whole no-regression
# argument for that job — so the DEFAULT is asserted here, against the helper itself.
PSR_TD="$PSR_ROOT/tally-direct"
mkdir -p "$PSR_TD"
psr_plant_tally() { # dir n-entries
  local dir="$1" n="$2" i=0
  mkdir -p "$dir"
  printf 'shard\tsolo\npassed\t1\nfailed\t%s\nskipped\t%s\nrc\t0\n' "$n" "$n" > "$dir/summary"
  : > "$dir/skips"; : > "$dir/names"
  while [ "$i" -lt "$n" ]; do
    printf 'planted-skip-%s\n' "$i" >> "$dir/skips"
    printf 'planted-failure-%s\n' "$i" >> "$dir/names"
    i=$((i + 1))
  done
}
psr_plant_tally "$PSR_TD/t25" 25
PSR_UNCAPPED="$(python3 "$PSR_TALLY" combine "$PSR_TD/t25" --expect 1 2>&1)"
assert_eq "psr cap: the DEFAULT renders every skip entry (CI's aggregator omits the flag)" "25" \
  "$(PSR_N=0; while IFS= read -r l || [ -n "$l" ]; do case "$l" in "  SKIP  planted-skip-"*) PSR_N=$((PSR_N+1)) ;; esac; done <<PSR_EOD
$PSR_UNCAPPED
PSR_EOD
printf '%s\n' "$PSR_N")"
assert_eq "psr cap: the DEFAULT renders every failure entry" "25" \
  "$(PSR_N=0; while IFS= read -r l || [ -n "$l" ]; do case "$l" in "  - planted-failure-"*) PSR_N=$((PSR_N+1)) ;; esac; done <<PSR_EOD
$PSR_UNCAPPED
PSR_EOD
printf '%s\n' "$PSR_N")"
assert_eq "psr cap: the DEFAULT announces no omitted count at all" "yes" \
  "$(case "$PSR_UNCAPPED" in *omitted*) echo no ;; *) echo yes ;; esac)"
# Exactly at the cap: no omitted line may print for a population that fits.
psr_plant_tally "$PSR_TD/t20" 20
PSR_ATCAP="$(python3 "$PSR_TALLY" combine "$PSR_TD/t20" --expect 1 --detail-cap 20 2>&1)"
assert_eq "psr cap: a population exactly at the cap announces no omission" "yes" \
  "$(case "$PSR_ATCAP" in *omitted*) echo no ;; *) echo yes ;; esac)"
assert_eq "psr cap: a population exactly at the cap renders all of it" "20" \
  "$(PSR_N=0; while IFS= read -r l || [ -n "$l" ]; do case "$l" in "  SKIP  planted-skip-"*) PSR_N=$((PSR_N+1)) ;; esac; done <<PSR_EOD
$PSR_ATCAP
PSR_EOD
printf '%s\n' "$PSR_N")"
# The SAME boundary for the failure-recap class. `_render_detail` is one function, but the
# two classes are two call sites passing their own prefix and their own population, so the
# at-cap arm is asserted per class rather than inferred from the skip class alone.
assert_eq "psr cap: a failure population exactly at the cap renders all of it" "20" \
  "$(PSR_N=0; while IFS= read -r l || [ -n "$l" ]; do case "$l" in "  - planted-failure-"*) PSR_N=$((PSR_N+1)) ;; esac; done <<PSR_EOD
$PSR_ATCAP
PSR_EOD
printf '%s\n' "$PSR_N")"
# A negative cap is uncapped, matching the documented "0 or negative" contract.
PSR_NEGCAP="$(python3 "$PSR_TALLY" combine "$PSR_TD/t25" --expect 1 --detail-cap -1 2>&1)"
assert_eq "psr cap: a negative cap is uncapped, as documented" "yes" \
  "$(case "$PSR_NEGCAP" in *omitted*) echo no ;; *) echo yes ;; esac)"
# The cap must never touch the DECISION: a capped render of a failing population still
# exits non-zero, and the announced tally is still the full one.
python3 "$PSR_TALLY" combine "$PSR_TD/t25" --expect 1 --detail-cap 20 >/dev/null 2>&1
assert_eq "psr cap: capping the render never turns a failing aggregate green" "1" "$?"

# ── shard-tally.py --require-shards: partition reconciliation BY NAME (issue #1289) ──
# `--expect` is only a count floor; a caller's count is never reconciled against the true
# shard set, so `--expect 1` over one shard is byte-shaped like a complete run. Naming the
# partition makes a subset recombination fail closed NAMING the gap. Plant three clean,
# distinctly-named shard tallies to drive the check directly against the helper.
PSR_RS="$PSR_ROOT/require-shards"
psr_plant_named() { # dir shard-name
  mkdir -p "$1"
  printf 'shard\t%s\npassed\t1\nfailed\t0\nskipped\t0\nrc\t0\n' "$2" > "$1/summary"
  : > "$1/skips"; : > "$1/names"
}
psr_plant_named "$PSR_RS/alpha" alpha
psr_plant_named "$PSR_RS/beta" beta
psr_plant_named "$PSR_RS/gamma" gamma
# The full partition present and named: clean, and the trailing line STATES the covered
# population so a reader need not already know the partition.
PSR_RS_FULL="$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" "$PSR_RS/gamma" --expect 3 --require-shards "alpha beta gamma" 2>&1)"
assert_eq "psr require: the full named partition recombines clean" "0" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" "$PSR_RS/gamma" --expect 3 --require-shards "alpha beta gamma" >/dev/null 2>&1; echo $?)"
assert_eq "psr require: a covered partition names the population it claims to cover" "yes" \
  "$(case "$PSR_RS_FULL" in *"required partition covered (3 shard(s)): alpha, beta, gamma"*) echo yes ;; *) echo no ;; esac)"
# The issue's exact reproduction: a subset recombined while the caller supplies an --expect
# that its own dir count satisfies. The bare count passes; the by-name check fails closed
# NAMING the missing shards — the whole point of #1289.
PSR_RS_SUB="$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" --expect 1 --require-shards "alpha,beta,gamma" 2>&1)"
assert_eq "psr require: a subset that satisfies --expect still fails the by-name check" "1" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" --expect 1 --require-shards "alpha,beta,gamma" >/dev/null 2>&1; echo $?)"
assert_eq "psr require: the shortfall NAMES the absent shards" "yes" \
  "$(case "$PSR_RS_SUB" in *"required shard(s) absent from the recombined tallies: beta, gamma"*) echo yes ;; *) echo no ;; esac)"
# Comma and whitespace are both accepted separators, so `run-shard.sh --list-shards`
# output pastes in verbatim — the mixed-separator form parses to the same set.
assert_eq "psr require: comma and whitespace separators parse to the same partition" "0" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" "$PSR_RS/gamma" --expect 3 --require-shards "alpha, beta gamma" >/dev/null 2>&1; echo $?)"
# A read shard NOT in the required partition (a stray/typo'd tally dir) is flagged too.
PSR_RS_EXTRA="$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" --expect 2 --require-shards "alpha" 2>&1)"
assert_eq "psr require: an unexpected shard beside the required set fails closed" "1" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" --expect 2 --require-shards "alpha" >/dev/null 2>&1; echo $?)"
assert_eq "psr require: the unexpected shard is named" "yes" \
  "$(case "$PSR_RS_EXTRA" in *"shard 'beta' is present but not in the required partition"*) echo yes ;; *) echo no ;; esac)"
# The same tally handed twice (a caller typo doubling one dir) is caught as a duplicate,
# both by the named message AND by a non-zero exit (the "fails closed" half).
assert_eq "psr require: a shard recombined more than once is named" "yes" \
  "$(case "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/alpha" --expect 2 --require-shards "alpha" 2>&1)" in *"recombined more than once: alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr require: a shard recombined more than once fails closed (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/alpha" --expect 2 --require-shards "alpha" >/dev/null 2>&1; echo $?)"
# The membership-failure branch prints its own self-describing NOT-covered line to stderr
# (the negative counterpart of the covered line asserted above).
assert_eq "psr require: a membership failure states the partition it could NOT cover" "yes" \
  "$(case "$PSR_RS_SUB" in *"required partition NOT covered (alpha, beta, gamma)"*) echo yes ;; *) echo no ;; esac)"
# A non-empty but degenerate --require-shards (whitespace/separator-only — e.g. the #1132
# recipe pasting an EMPTY --list-shards) must NOT silently disable the by-name check: it
# fails closed, distinct from the empty-string opt-out. This closes the fail-open one layer out.
assert_eq "psr require: a separator-only value fails closed rather than silently disabling" "1" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" --expect 1 --require-shards ", ," >/dev/null 2>&1; echo $?)"
assert_eq "psr require: a whitespace-only value fails closed rather than silently disabling" "yes" \
  "$(case "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" --expect 1 --require-shards "   " 2>&1)" in *"names no shards"*) echo yes ;; *) echo no ;; esac)"
# _parse_shard_list keeps order-of-first-appearance and de-dups the REQUIRED value itself,
# so the covered line reads in the caller's stated order and a self-duplicated id is harmless.
assert_eq "psr require: the covered line preserves the caller's stated order" "yes" \
  "$(case "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" "$PSR_RS/gamma" --expect 3 --require-shards "gamma beta alpha" 2>&1)" in *"required partition covered (3 shard(s)): gamma, beta, alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr require: a self-duplicated required id de-dups to the real partition" "0" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" "$PSR_RS/beta" "$PSR_RS/gamma" --expect 3 --require-shards "alpha,alpha,beta,gamma" >/dev/null 2>&1; echo $?)"
# Omitting --require-shards leaves the existing output byte-shape unchanged — no partition
# line at all, so CI's aggregator (which never passes the flag) is unaffected.
assert_eq "psr require: omitting the flag prints no partition line (existing output unchanged)" "yes" \
  "$(case "$(python3 "$PSR_TALLY" combine "$PSR_RS/alpha" --expect 1 2>&1)" in *"required partition"*) echo no ;; *) echo yes ;; esac)"
# `--expect 0` stays the documented explicit opt-out and still routes through the
# zero-directories refusal (issue #1289 preserves this).
assert_eq "psr require: --expect 0 with zero dirs still refuses via the zero-dirs guard" "yes" \
  "$(case "$(python3 "$PSR_TALLY" combine --expect 0 2>&1)" in *"refusing to report a green gate over zero shards"*) echo yes ;; *) echo no ;; esac)"

# ── matcher shape: the bare cloud token, and the local DEVFLOW_BASH boundary ──
assert_eq "psr shape: the coordinator is executable" "yes" \
  "$([ -x "$PSR_COORD" ] && echo yes || echo no)"
PSR_T7="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T7"
# The cloud actor's whole command is the leading token and nothing else: caller-side
# assignment, redirect, pipeline, interpreter prefix and background syntax are each a
# shape the cloud matcher refuses even when the head is granted, so none is spelled here.
PSR_BARE="$(cd "$PSR_T7" && SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T7/dispatch.sh" ./lib/test/run-parallel.sh 2>&1)"
assert_eq "psr shape: the bare leading-token invocation is the complete command shape" "yes" \
  "$(case "$PSR_BARE" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr shape: one unknown argument is refused by name" "yes" \
  "$(cd "$PSR_T7" && case "$(./lib/test/run-parallel.sh --shards 2>&1)" in *"unknown argument"*) echo yes ;; *) echo no ;; esac)"
# A DIFFERENT guard with a DIFFERENT message: the arity check fires before the argument
# is ever classified, so a second argument cannot reach the unknown-argument arm above.
assert_eq "psr shape: a second argument is refused by the arity guard, not the unknown-argument arm" "yes" \
  "$(cd "$PSR_T7" && case "$(./lib/test/run-parallel.sh --help extra 2>&1)" in *"at most one argument"*) echo yes ;; *) echo no ;; esac)"
# The local tier reaches the SAME coordinator through an invocation-layer bash selector
# (this repository's `DEVFLOW_BASH` boundary). One selector stands in for WSL bash, Git
# Bash and MSYS2 bash alike — they differ only in WHICH bash the operator points at, and
# the coordinator reads no such variable itself, so three identically-bodied wrappers
# would be copies of one assertion rather than distinct cases.
printf '#!/usr/bin/env bash\nexec bash "$@"\n' > "$PSR_T7/selected-bash"
chmod +x "$PSR_T7/selected-bash"
PSR_SEL_OUT="$(cd "$PSR_T7" && SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T7/dispatch.sh" "./selected-bash" lib/test/run-parallel.sh 2>&1)"
assert_eq "psr shape: an invocation-layer bash selector reaches the coordinator unchanged" "yes" \
  "$(case "$PSR_SEL_OUT" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
# --help is the other documented half of the command shape, and its sed filter can fail
# OPEN (a renamed sentinel yields an empty selection and exit 0), so assert content.
PSR_HELP="$(cd "$PSR_T7" && ./lib/test/run-parallel.sh --help 2>&1)"; PSR_HELP_RC=$?
assert_eq "psr shape: --help exits 0" "0" "$PSR_HELP_RC"
assert_eq "psr shape: --help renders the operative budget contract, not an empty selection" "yes" \
  "$(case "$PSR_HELP" in *DEVFLOW_SUITE_PROCESS_BUDGET*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr shape: --help strips its own sentinel lines" "yes" \
  "$(case "$PSR_HELP" in *'---8<---'*) echo no ;; *) echo yes ;; esac)"

# An unreadable dispatcher is refused before anything is allocated.
assert_eq "psr shape: an unreadable shard dispatcher is refused by name" "yes" \
  "$(cd "$PSR_T7" && case "$(DEVFLOW_SHARD_DISPATCHER="$PSR_T7/no-such-dispatcher" ./lib/test/run-parallel.sh 2>&1)" in
       *"dispatcher is not readable"*) echo yes ;; *) echo no ;; esac)"

# ── run root: fallback, refusal, and exhaustion ──────────────────────────────
# A checkout whose `.prflow` path cannot hold the run root stands in for a read-only
# checkout: the mechanism under test is "the checkout root is unusable", and blocking
# it with a regular file is enforced for every user, where a chmod is not enforced for
# a privileged one — a probe that silently passes under root would be a vacuous guard.
PSR_T8="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T8"
: > "$PSR_T8/.prflow"
PSR_FALLBACK_TMP="$PSR_ROOT/fallback-tmp"; mkdir -p "$PSR_FALLBACK_TMP"
PSR_RR_OUT="$(cd "$PSR_T8" && SYN_SHARDS=alpha SYN_SLEEP=0.05 TMPDIR="$PSR_FALLBACK_TMP" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T8/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr run-root: an unusable checkout root falls back to TMPDIR and completes" "yes" \
  "$(case "$PSR_RR_OUT" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr run-root: the fallback is announced, not silent" "yes" \
  "$(case "$PSR_RR_OUT" in *"checkout run root unusable"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr run-root: the fallback root is under TMPDIR" "yes" \
  "$([ -d "$PSR_FALLBACK_TMP/devflow-parallel-suite" ] && echo yes || echo no)"
# Both roots unusable → a named diagnostic BEFORE any completion claim.
PSR_BAD_TMP="$PSR_ROOT/bad-tmp"; : > "$PSR_BAD_TMP"
PSR_RR_OUT="$(cd "$PSR_T8" && SYN_SHARDS=alpha TMPDIR="$PSR_BAD_TMP" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_T8/dispatch.sh" bash lib/test/run-parallel.sh 2>&1)"
assert_eq "psr run-root: with no writable root the run refuses by name" "yes" \
  "$(case "$PSR_RR_OUT" in *"could not allocate a writable run root"*) echo yes ;; *) echo no ;; esac)"
assert_eq "psr run-root: an unwritable root claims no result" "yes" \
  "$(case "$PSR_RR_OUT" in *passed,*) echo no ;; *) echo yes ;; esac)"
# Exhaustion: every candidate name this PID would try is already taken. `exec`
# preserves the PID, so the collision set is built deterministically rather than raced.
PSR_T9="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_T9"
PSR_RR_OUT="$(cd "$PSR_T9" && SYN_SHARDS=alpha TMPDIR="$PSR_BAD_TMP" bash -c '
  set -u
  n=0
  while [ "$n" -lt 50 ]; do
    mkdir -p ".prflow/tmp/parallel-suite/run-$$-$n"
    n=$((n + 1))
  done
  export DEVFLOW_SHARD_DISPATCHER="$PWD/dispatch.sh"
  exec bash lib/test/run-parallel.sh
' 2>&1)"
assert_eq "psr run-root: an exhausted candidate name space refuses by name" "yes" \
  "$(case "$PSR_RR_OUT" in *"could not allocate a writable run root"*) echo yes ;; *) echo no ;; esac)"

# ── Generated-artifact preflight (issue #1244) ───────────────────────────────
# The coordinator runs a read-only preflight before launching any shard, resolved through
# the DEVFLOW_ARTIFACT_PREFLIGHT override in the same style as DEVFLOW_SHARD_DISPATCHER, so
# every arm is drivable from a synthetic tree with an injected stub. Detected drift fails
# CLOSED (no shard launches); an inconclusive preflight fails OPEN (a warning, then the
# shards run).
#
# The refusal comparand is the preflight's MACHINE verdict line, whose producer is
# `lib/test/regenerate-artifacts.py` (`PREFLIGHT_VERDICT_PREFIX`). A stub here necessarily
# restates that literal, so a stub-only module could never catch the two files drifting
# apart — that binding is driven end-to-end against the REAL helper (and the real default
# resolution) from `lib/test/modules/regenerate-artifacts.sh`'s AP10 arms. What this module
# owns instead is the coordinator's own selection logic, including the two negative controls
# below that a stub is uniquely good at: the human remedy prose alone must NOT refuse, and
# neither must the verdict text quoted inside an indented row diagnostic.
PSR_STUBS="$PSR_ROOT/preflight-stubs"; mkdir -p "$PSR_STUBS"
psr_plant_preflight() {  # <name> <rc> <line...>   — writes an executable stub, echoes its path
  local name="$1" rc="$2"; shift 2
  local path="$PSR_STUBS/$name.sh" line
  {
    printf '#!/usr/bin/env bash\n'
    for line in "$@"; do printf 'printf "%%s\\n" %q\n' "$line"; done
    printf 'exit %s\n' "$rc"
  } > "$path"
  chmod +x "$path"
  printf '%s\n' "$path"
}

PSR_PF_CLEAN="$(psr_plant_preflight clean 0 \
  "[cloud-writer-manifest] clean" \
  "regenerate-artifacts: preflight-verdict: clean" \
  "regenerate-artifacts: preflight — every eligible artifact reconciled — exit 0")"
PSR_PF_DRIFT="$(psr_plant_preflight drift 1 \
  "[cloud-writer-manifest] DRIFT \`python3 lib/test/cloud_writer_contract.py verify\` exited 1" \
  "    governing policy: regenerate against the merged tree with \`python3 lib/test/cloud_writer_contract.py generate\`" \
  "regenerate-artifacts: preflight-verdict: drift" \
  "regenerate-artifacts: preflight detected drift — regenerate the artifact(s) above and commit before the suite run — exit 1")"
# Negative control 1: the HUMAN remedy sentence with no verdict line. The coordinator used
# to key its refusal on a substring of this prose, which made a reword in the producer file
# a silent fail-open. It must now warn and proceed.
PSR_PF_PROSE_ONLY="$(psr_plant_preflight prose-only 1 \
  "[cloud-writer-manifest] DRIFT \`python3 lib/test/cloud_writer_contract.py verify\` exited 1" \
  "regenerate-artifacts: preflight detected drift — regenerate the artifact(s) above and commit before the suite run — exit 1")"
# Negative control 2: the verdict TEXT quoted inside an indented row diagnostic, which is
# how a row's captured `output:` block reproduces whatever its generator printed. The
# comparand is line-exact, so this must not refuse either.
PSR_PF_QUOTED="$(psr_plant_preflight quoted-verdict 1 \
  "[capability-profile-literals] UNCHECKABLE \`python3 lib/generate-capability-profiles.py --check\` exited 1" \
  "    output: regenerate-artifacts: preflight-verdict: drift" \
  "regenerate-artifacts: preflight-verdict: uncheckable" \
  "regenerate-artifacts: preflight could not check at least one eligible artifact — exit 2")"
PSR_PF_EXIT2="$(psr_plant_preflight exit2 2 \
  "regenerate-artifacts: preflight-verdict: uncheckable" \
  "regenerate-artifacts: preflight could not check at least one eligible artifact — exit 2")"
PSR_PF_CRASH="$(psr_plant_preflight crash 1 \
  "Traceback (most recent call last):" \
  "  File \"regenerate-artifacts.py\", line 1, in <module>" \
  "RuntimeError: boom")"

PSR_PT="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_PT"

# AC4/AC1 — a clean preflight launches the shards and the run completes cleanly.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: a clean preflight exits 0" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: a clean preflight launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: a clean preflight completes the aggregate" "yes" \
  "$(case "$PSR_PF_OUT" in *"2 passed, 0 failed"*) echo yes ;; *) echo no ;; esac)"

# AC4 — detected drift refuses to launch: no shard, non-zero, remedy printed.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_DRIFT" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: detected drift exits non-zero" "yes" \
  "$([ "$PSR_PF_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "#1244 psr preflight: detected drift launches NO shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "#1244 psr preflight: detected drift prints the remedy and refuses by name" "yes" \
  "$(case "$PSR_PF_OUT" in *"launching no shard"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: detected drift echoes the failing row's report" "yes" \
  "$(case "$PSR_PF_OUT" in *"[cloud-writer-manifest] DRIFT"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: detected drift claims no aggregate" "yes" \
  "$(case "$PSR_PF_OUT" in *passed,*) echo no ;; *) echo yes ;; esac)"

# The refusal is keyed on the machine verdict LINE, not on the human remedy sentence beside
# it. Without this control the coordinator could go on matching that free prose and nothing
# would notice — which is the state this seam was in before: a reword in the producer file
# would have left it failing OPEN on genuine drift.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_PROSE_ONLY" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: the human remedy prose alone does NOT refuse (exit 0)" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: the human remedy prose alone still launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: the human remedy prose alone is reported inconclusive, never a refusal" "yes" \
  "$(case "$PSR_PF_OUT" in *"launching no shard"*) echo no ;; *"preflight was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# The verdict is matched LINE-EXACTLY: the same text reproduced inside an indented row
# diagnostic is data a generator printed, not this preflight's verdict, so it must not
# refuse. A substring match over the whole blob would fail CLOSED here on a run whose only
# real verdict was `uncheckable`.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_QUOTED" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: a verdict quoted inside a row diagnostic does NOT refuse (exit 0)" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: a verdict quoted inside a row diagnostic still launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: a verdict quoted inside a row diagnostic refuses nothing by name" "yes" \
  "$(case "$PSR_PF_OUT" in *"launching no shard"*) echo no ;; *) echo yes ;; esac)"

# AC5 — an exit-2 (uncheckable) preflight warns and proceeds; the shards still run.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_EXIT2" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: an exit-2 preflight still exits 0 (decided by the shards)" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: an exit-2 preflight still launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: an exit-2 preflight warns rather than blocks" "yes" \
  "$(case "$PSR_PF_OUT" in *"preflight was inconclusive (exit 2"*) echo yes ;; *) echo no ;; esac)"

# AC5 — a crashing preflight (traceback, exit 1, no drift marker) also warns and proceeds.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CRASH" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: a crashing preflight still exits 0 (decided by the shards)" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: a crashing preflight still launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: a crashing preflight is treated as inconclusive, not drift" "yes" \
  "$(case "$PSR_PF_OUT" in *"preflight was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# AC6 — an empty override disables the preflight entirely; the shards run with no warning.
PSR_PF_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_PF_RC=$?
assert_eq "#1244 psr preflight: an empty override disables the preflight (exit 0)" "0" "$PSR_PF_RC"
assert_eq "#1244 psr preflight: an empty override still launches the shard" "yes" \
  "$(case "$PSR_PF_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1244 psr preflight: an empty override emits no preflight warning" "yes" \
  "$(case "$PSR_PF_OUT" in *"generated-artifact preflight"*) echo no ;; *) echo yes ;; esac)"

# ── Standalone --preflight mode (issue #1288) ────────────────────────────────
# The #1132 shard-decomposition route names `run-parallel.sh --preflight` before its shard
# loop so the whole-suite result it produces carries the SAME pre-launch drift check the
# coordinator's own run does. It runs ONLY the preflight, launches no shard, and exits with
# the SAME verdict contract: 0 to proceed (clean or fail-open inconclusive), non-zero (die)
# on a positively-attributed drift. It reuses the same injected stubs as the coordinator
# arms above, needs no dispatcher (it exits before the shard population is derived), and
# shares the `_artifact_preflight` implementation, so this proves the standalone route is
# governed by the same single-sourced verdict interpretation.

# A clean preflight exits 0, launches NO shard, and produces no aggregate.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: a clean preflight exits 0" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: a clean preflight launches no shard" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "#1288 --preflight: a clean preflight reports no aggregate" "yes" \
  "$(case "$PSR_PFO_OUT" in *passed,*) echo no ;; *) echo yes ;; esac)"

# A positively-attributed drift refuses: non-zero, echoes the failing row's report, and
# refuses by name with the SAME 'launching no shard' contract the coordinator uses.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_DRIFT" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: detected drift exits non-zero" "yes" \
  "$([ "$PSR_PFO_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "#1288 --preflight: detected drift launches NO shard" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "#1288 --preflight: detected drift refuses by name" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launching no shard"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#1288 --preflight: detected drift echoes the failing row's report" "yes" \
  "$(case "$PSR_PFO_OUT" in *"[cloud-writer-manifest] DRIFT"*) echo yes ;; *) echo no ;; esac)"

# The refusal is keyed on the machine verdict LINE, never the human remedy prose beside it:
# a preflight that prints ONLY that prose (the historical fail-open regression the line-exact
# match was introduced to prevent) must proceed, not refuse. Ported to the standalone route
# too so a --preflight-only regression re-introducing substring matching is pinned here.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_PROSE_ONLY" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: the human remedy prose alone does NOT refuse (exit 0)" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: the human remedy prose alone is reported inconclusive, never a refusal" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launching no shard"*) echo no ;; *"preflight was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# The verdict is matched LINE-EXACTLY here too: the same text quoted inside an indented row
# diagnostic is data, not the verdict, so it must NOT refuse (fail-open, exit 0). The stub
# exits 1 with an `uncheckable` verdict, so it also takes the warn-and-proceed arm.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_QUOTED" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: a verdict quoted inside a row diagnostic does NOT refuse (exit 0)" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: a verdict quoted inside a row diagnostic refuses nothing by name" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launching no shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "#1288 --preflight: a verdict quoted inside a row diagnostic warns inconclusive" "yes" \
  "$(case "$PSR_PFO_OUT" in *"preflight was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# An exit-2 (uncheckable) preflight warns and proceeds (exit 0) — fail-open, same as the
# coordinator.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_EXIT2" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: an exit-2 preflight proceeds (exit 0)" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: an exit-2 preflight warns rather than refuses" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launching no shard"*) echo no ;; *"preflight was inconclusive (exit 2"*) echo yes ;; *) echo no ;; esac)"

# A crashing preflight (traceback, exit 1, no drift marker) is inconclusive, not drift.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CRASH" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: a crashing preflight proceeds (exit 0)" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: a crashing preflight is treated as inconclusive, not drift" "yes" \
  "$(case "$PSR_PFO_OUT" in *"launching no shard"*) echo no ;; *"preflight was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# An empty override disables the preflight entirely: exit 0, and no preflight output at all.
PSR_PFO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_PFO_RC=$?
assert_eq "#1288 --preflight: an empty override disables the preflight (exit 0)" "0" "$PSR_PFO_RC"
assert_eq "#1288 --preflight: an empty override emits no preflight output" "yes" \
  "$(case "$PSR_PFO_OUT" in *"generated-artifact preflight"*) echo no ;; *) echo yes ;; esac)"

# --preflight is a single known argument: a second argument is still refused by the arity
# guard, not misread as the preflight input.
assert_eq "#1288 --preflight: a second argument is refused by the arity guard" "yes" \
  "$(cd "$PSR_PT" && case "$(bash lib/test/run-parallel.sh --preflight extra 2>&1)" in *"at most one argument"*) echo yes ;; *) echo no ;; esac)"


# ── Cheap-lint gate preflight (fail-fast before the coordinator) ─────────────
# Contract under test: fail closed on an attributed finding, fail OPEN on anything that
# leaves a lint unusable, with the completion sentinel — not the exit code — as the
# comparand, matched at the start of a line. Keep the crash and quoted-sentinel controls:
# without them a comparand keyed on the exit code alone would still pass.
PSR_CL_CLEAN_RSZ="$(psr_plant_preflight cl-clean-rsz 0 \
  "lint-reference-size: audited 41 of 41 files [whole-tree]")"
PSR_CL_FIND_RSZ="$(psr_plant_preflight cl-find-rsz 1 \
  "skills/review-and-fix/references/shadow-review.md: 62810 bytes exceeds the 61750-byte ceiling — trim the file to at most 61750 bytes" \
  "lint-reference-size: audited 41 of 41 files [whole-tree]")"
PSR_CL_CRASH_RSZ="$(psr_plant_preflight cl-crash-rsz 1 \
  "Traceback (most recent call last):" \
  "RuntimeError: boom")"
PSR_CL_QUOTED_RSZ="$(psr_plant_preflight cl-quoted-rsz 1 \
  "    output: lint-reference-size: audited 41 of 41 files [whole-tree]" \
  "Traceback (most recent call last):")"
PSR_CL_EXIT2_RSZ="$(psr_plant_preflight cl-exit2-rsz 2 \
  "lint-reference-size: cannot read exemption record: boom")"
PSR_CL_CLEAN_BDS="$(psr_plant_preflight cl-clean-bds 0 \
  "lint-brand-devflow-sweep: audited 900 of 900 files")"
PSR_CL_FIND_BDS="$(psr_plant_preflight cl-find-bds 1 \
  "lint-brand-devflow-sweep: audited 900 of 900 files" \
  "  docs/new.md: brand-cased prose in a file with no pending_sweep_baseline entry")"

# A clean pair proceeds, launches the shards, and stays SILENT — the established contract.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CLEAN_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: a clean pair exits 0" "0" "$PSR_CL_RC"
assert_eq "cheap-lint gate: a clean pair launches the shard" "yes" \
  "$(case "$PSR_CL_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate: a clean pair emits no gate output" "yes" \
  "$(case "$PSR_CL_OUT" in *"cheap-lint gate"*) echo no ;; *) echo yes ;; esac)"

# A reference-size finding refuses BEFORE any shard launches, names the gate, and echoes
# the finding.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_FIND_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: a reference-size finding exits non-zero" "yes" \
  "$([ "$PSR_CL_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "cheap-lint gate: a reference-size finding launches NO shard" "yes" \
  "$(case "$PSR_CL_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "cheap-lint gate: a reference-size finding names the failing gate" "yes" \
  "$(case "$PSR_CL_OUT" in *"reference-size"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate: a reference-size finding names the remedy" "yes" \
  "$(case "$PSR_CL_OUT" in *"launching no shard"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate: a reference-size finding echoes the finding line" "yes" \
  "$(case "$PSR_CL_OUT" in *"exceeds the 61750-byte ceiling"*) echo yes ;; *) echo no ;; esac)"

# The same contract on the second lint: the gate is a SET, not one hardcoded lint.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CLEAN_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_FIND_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: a brand-sweep finding exits non-zero" "yes" \
  "$([ "$PSR_CL_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "cheap-lint gate: a brand-sweep finding launches NO shard" "yes" \
  "$(case "$PSR_CL_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "cheap-lint gate: a brand-sweep finding names its own gate" "yes" \
  "$(case "$PSR_CL_OUT" in *"brand-sweep"*) echo yes ;; *) echo no ;; esac)"

# A crashing lint (traceback, exit 1, NO completion sentinel) must NOT block the suite: an
# unusable check fails OPEN, exactly as the artifact preflight does.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CRASH_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: a crashing lint still exits 0 (decided by the shards)" "0" "$PSR_CL_RC"
assert_eq "cheap-lint gate: a crashing lint still launches the shard" "yes" \
  "$(case "$PSR_CL_OUT" in *"launched shard alpha"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate: a crashing lint is reported inconclusive, never a refusal" "yes" \
  "$(case "$PSR_CL_OUT" in *"launching no shard"*) echo no ;; *"was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# The sentinel is matched at the START of a line: the same text quoted inside an indented
# diagnostic is data, so a crash that happens to echo it must still fail OPEN.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_QUOTED_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: a sentinel quoted inside a diagnostic does NOT refuse (exit 0)" "0" "$PSR_CL_RC"
assert_eq "cheap-lint gate: a sentinel quoted inside a diagnostic refuses nothing by name" "yes" \
  "$(case "$PSR_CL_OUT" in *"launching no shard"*) echo no ;; *) echo yes ;; esac)"

# An exit-2 record error carries no completion sentinel either — warn and proceed.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_EXIT2_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: an exit-2 record error proceeds (exit 0)" "0" "$PSR_CL_RC"
assert_eq "cheap-lint gate: an exit-2 record error warns rather than blocks" "yes" \
  "$(case "$PSR_CL_OUT" in *"was inconclusive (exit 2"*) echo yes ;; *) echo no ;; esac)"

# An empty override disables that gate entirely, the documented escape hatch the artifact
# preflight also offers.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="" DEVFLOW_BRAND_SWEEP_PREFLIGHT="" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: an empty override disables the gate (exit 0)" "0" "$PSR_CL_RC"
assert_eq "cheap-lint gate: an empty override emits no gate output" "yes" \
  "$(case "$PSR_CL_OUT" in *"cheap-lint gate"*) echo no ;; *) echo yes ;; esac)"

# The artifact preflight still decides FIRST: a drift refusal is reported even when a cheap
# lint would also have fired, so the cheaper gate cannot mask the existing one.
PSR_CL_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_DRIFT" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_FIND_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_CL_RC=$?
assert_eq "cheap-lint gate: artifact drift still refuses first" "yes" \
  "$(case "$PSR_CL_OUT" in *"generated-artifact preflight reported drift"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate: artifact drift refusal launches no shard" "yes" \
  "$(case "$PSR_CL_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"

# ── Cheap-lint gate on the standalone --preflight route ──────────────────────
# The #1132 decomposition route must carry the SAME cheap gates, or a run that decomposes
# into shards keeps paying the whole partition to discover a sub-second finding.
PSR_CLO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CLEAN_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_CLO_RC=$?
assert_eq "cheap-lint gate --preflight: a clean pair exits 0" "0" "$PSR_CLO_RC"
assert_eq "cheap-lint gate --preflight: a clean pair launches no shard" "yes" \
  "$(case "$PSR_CLO_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"

PSR_CLO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_FIND_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_CLO_RC=$?
assert_eq "cheap-lint gate --preflight: a finding exits non-zero" "yes" \
  "$([ "$PSR_CLO_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "cheap-lint gate --preflight: a finding refuses by name" "yes" \
  "$(case "$PSR_CLO_OUT" in *"launching no shard"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate --preflight: a finding echoes the finding line" "yes" \
  "$(case "$PSR_CLO_OUT" in *"exceeds the 61750-byte ceiling"*) echo yes ;; *) echo no ;; esac)"

PSR_CLO_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CRASH_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="$PSR_CL_CLEAN_BDS" \
  bash lib/test/run-parallel.sh --preflight 2>&1)"; PSR_CLO_RC=$?
assert_eq "cheap-lint gate --preflight: a crashing lint proceeds (exit 0)" "0" "$PSR_CLO_RC"
assert_eq "cheap-lint gate --preflight: a crashing lint is inconclusive, not a refusal" "yes" \
  "$(case "$PSR_CLO_OUT" in *"launching no shard"*) echo no ;; *"was inconclusive (exit 1"*) echo yes ;; *) echo no ;; esac)"

# ── Real-helper coupling pin + default resolution ───────────────────────────
# The stub arms restate each sentinel themselves, so keep both real-helper arms: (a) pins
# the bundled-default resolution branch every override-injecting arm bypasses, and (b) pins
# the brand sentinel literal, which only a NON-ZERO exit reaches. Neither covers the other.
PSR_RH="$PSR_ROOT/real-helper"; mkdir -p "$PSR_RH"

# (a) Run this against the REAL checkout, never a synthetic tree: each lint loads sibling
# modules by path, so a copied fixture's hand-maintained dependency closure drifts into an
# inconclusive warning — a fail-OPEN result that would pass this arm for the wrong reason.
PSR_RH_TREE="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_RH_TREE"
PSR_RH_OUT="$(cd "$LIB/.." && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_RH_TREE/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_RH_RC=$?
# Assert nothing that a real finding in the developer's own tree would flip: with the
# overrides unset the real lints audit that tree, so an exit-0 or launched-shard assertion
# would go RED for whoever is mid-fix on a reference-size or brand finding.
# A default that did not resolve exits non-zero with NO sentinel, so it warns INCONCLUSIVE
# and still exits 0; pinning that warning's absence is what discriminates resolution.
assert_eq "cheap-lint gate real: the bundled default is not silently inconclusive" "yes" \
  "$(case "$PSR_RH_OUT" in *"cheap-lint gate was inconclusive"*) echo no ;; *) echo yes ;; esac)"
# Either outcome proves the default resolved and the gate reached a verdict.
assert_eq "cheap-lint gate real: the bundled default launched the shard or refused by name" "yes" \
  "$(case "$PSR_RH_OUT" in *"launched shard alpha"*|*"launching no shard"*) echo yes ;; *) echo no ;; esac)"
assert_eq "cheap-lint gate real: the bundled default exits 0 or the gate's refusal 2" "yes" \
  "$(case "$PSR_RH_RC" in 0|2) echo yes ;; *) echo no ;; esac)"

# The real coordinator allocates a real run root in this checkout; without this removal the
# tree accumulates one PID-keyed directory per module invocation, which the by-PID
# suite-process triage procedure then has to reason about.
PSR_RH_ROOT=""
while IFS= read -r PSR_RH_LINE; do
  case "$PSR_RH_LINE" in
    "run-parallel: retained logs: "*) PSR_RH_ROOT="${PSR_RH_LINE#run-parallel: retained logs: }" ;;
  esac
done <<< "$PSR_RH_OUT"
# Never widen this pattern: it is the only thing keeping the rm inside the run-root parent.
case "$PSR_RH_ROOT" in
  */.prflow/tmp/parallel-suite/run-*/logs) rm -rf "${PSR_RH_ROOT%/logs}" ;;
esac

# (b) Keep the fixture a git repo — the lint enumerates via `git ls-files` — and keep the
# brand literal assembled at run time: a verbatim occurrence here would itself become an
# unclassified finding in the real tree.
PSR_RH_BFX="$PSR_RH/brand-fixture"
python3 - "$PSR_RH_BFX" <<'PSR_BRAND_BUILD'
import json, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
(root / "docs").mkdir(parents=True, exist_ok=True)
(root / "lib" / "test").mkdir(parents=True, exist_ok=True)
brand = "Dev" + "Flow"          # assembled: a literal here would red the real tree
(root / "docs" / "unclassified.md").write_text(f"{brand} prose nobody classified\n", encoding="utf-8")
buckets = {"schema_version": 1,
           "frozen": {"transient_prefixes": [], "transient_exceptions": [],
                      "record_prefixes": [], "historical_files": [],
                      "tooling_files": [], "provenance": []},
           "pending_sweep_baseline": []}
(root / "lib" / "test" / "brand-devflow-buckets.json").write_text(
    json.dumps(buckets, indent=2) + "\n", encoding="utf-8")
subprocess.run(["git", "init", "-q"], cwd=root, check=True)
subprocess.run(["git", "add", "-A"], cwd=root, check=True)
PSR_BRAND_BUILD

# Control: the real lint really does find and really does emit its completion line here.
# Without this, a fixture that silently stopped producing a finding would leave the arm
# below passing for the wrong reason.
PSR_RH_BRAW="$(python3 "$LIB/test/lint-brand-devflow-sweep.py" --root "$PSR_RH_BFX" 2>&1)"; PSR_RH_BRC=$?
assert_eq "cheap-lint gate real: the brand fixture really produces a finding" "1" "$PSR_RH_BRC"
assert_eq "cheap-lint gate real: the real brand lint emits its completion line" "yes" \
  "$(case "$PSR_RH_BRAW" in "lint-brand-devflow-sweep: audited "*) echo yes ;; *) echo no ;; esac)"

# The pin: driven through the coordinator, the real lint's real output must be read as an
# attributed FINDING (refuse, launch nothing), never as inconclusive.
PSR_RH_OUT="$(cd "$PSR_PT" && DEVFLOW_ARTIFACT_PREFLIGHT="$PSR_PF_CLEAN" \
  DEVFLOW_REFERENCE_SIZE_PREFLIGHT="$PSR_CL_CLEAN_RSZ" \
  DEVFLOW_BRAND_SWEEP_PREFLIGHT="python3 $LIB/test/lint-brand-devflow-sweep.py --root $PSR_RH_BFX" \
  DEVFLOW_SHARD_DISPATCHER="$PSR_PT/dispatch.sh" SYN_SHARDS=alpha SYN_SLEEP=0.05 \
  bash lib/test/run-parallel.sh 2>&1)"; PSR_RH_RC=$?
assert_eq "cheap-lint gate real: the real brand sentinel is matched, so the gate refuses" "yes" \
  "$([ "$PSR_RH_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "cheap-lint gate real: the real brand finding launches NO shard" "yes" \
  "$(case "$PSR_RH_OUT" in *"launched shard"*) echo no ;; *) echo yes ;; esac)"
assert_eq "cheap-lint gate real: the real brand finding is attributed, not inconclusive" "yes" \
  "$(case "$PSR_RH_OUT" in *"was inconclusive"*) echo no ;; *"reported findings"*) echo yes ;; *) echo no ;; esac)"

# ── issue #2008: launch-time checkout fingerprint + fingerprint-gated same-tree relaunch ──
# A launch records the tree's checkout fingerprint so an environment-only fix can relaunch only
# the failed shards against a proven-identical tree (issue #2008).
PSR_FP="$PSR_ROOT/fingerprint"
mkdir -p "$PSR_FP"
# A stub fingerprint helper emitting a fixed, established five-field record. Equality is the
# whole contract, so opaque non-empty strings suffice and the fixture needs no git checkout.
PSR_FP_STUB="$PSR_FP/fp-ok.sh"
cat > "$PSR_FP_STUB" <<'PSR_EOF'
#!/usr/bin/env bash
printf '{"checkout_id":"/fix/.git","head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","index_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","tracked_digest":"cccccccccccccccccccccccccccccccccccccccc","untracked_digest":"dddddddddddddddddddddddddddddddddddddddd"}\n'
PSR_EOF
chmod +x "$PSR_FP_STUB"
# A stub whose fingerprint cannot be produced (the producer's fail-closed path).
PSR_FP_FAIL="$PSR_FP/fp-fail.sh"
cat > "$PSR_FP_FAIL" <<'PSR_EOF'
#!/usr/bin/env bash
printf 'checkout-fingerprint: simulated failure\n' >&2
exit 1
PSR_EOF
chmod +x "$PSR_FP_FAIL"

# AC1/AC2: record-fingerprint persists the established five-field record into a launch dir.
PSR_FP_OK="$PSR_FP/rec-ok"
DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_STUB" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_OK" >/dev/null 2>&1
assert_eq "psr fp: record-fingerprint writes fingerprint.json into the launch dir" "yes" \
  "$([ -f "$PSR_FP_OK/fingerprint.json" ] && echo yes || echo no)"
assert_eq "psr fp: the established record carries the producer's fingerprint verbatim" "yes" \
  "$(case "$(cat "$PSR_FP_OK/fingerprint.json" 2>/dev/null)" in *'"head":"aaaaaaaa'*'"untracked_digest":"dddddddd'*) echo yes ;; *) echo no ;; esac)"

# AC3: a launch whose fingerprint cannot be produced records it UNESTABLISHED, never omits it.
PSR_FP_UN="$PSR_FP/rec-un"
DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_FAIL" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_UN" >/dev/null 2>&1
assert_eq "psr fp: a failed producer still writes a fingerprint record (never omitted)" "yes" \
  "$([ -f "$PSR_FP_UN/fingerprint.json" ] && echo yes || echo no)"
assert_eq "psr fp: the record marks the fingerprint unestablished rather than inventing one" "yes" \
  "$(case "$(cat "$PSR_FP_UN/fingerprint.json" 2>/dev/null)" in *'"unestablished": true'*) echo yes ;; *) echo no ;; esac)"

# AC3 (rc-0-but-junk): a producer that exits 0 but prints non-established stdout (partial or
# garbage) still records UNESTABLISHED, exit 0 — never a partial/invented fingerprint (issue #2008).
PSR_FP_JUNK="$PSR_FP/fp-junk.sh"
cat > "$PSR_FP_JUNK" <<'PSR_EOF'
#!/usr/bin/env bash
printf 'not json at all\n'
exit 0
PSR_EOF
chmod +x "$PSR_FP_JUNK"
PSR_FP_JU="$PSR_FP/rec-junk"
assert_eq "psr fp: a producer exiting 0 with non-established stdout records unestablished (rc 0)" "0" \
  "$(DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_JUNK" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_JU" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: the rc-0-but-junk producer's record is unestablished, not the junk verbatim" "yes" \
  "$(case "$(cat "$PSR_FP_JU/fingerprint.json" 2>/dev/null)" in *'"unestablished": true'*) echo yes ;; *) echo no ;; esac)"

# The subprocess-spawn-failure arm: a non-existent helper is caught (OSError), recorded
# unestablished, exit 0 — never propagated so the launch is never blocked (issue #2008).
PSR_FP_NX="$PSR_FP/rec-nx"
assert_eq "psr fp: a non-existent fingerprint helper is caught and recorded unestablished (rc 0)" "0" \
  "$(DEVFLOW_FINGERPRINT_HELPER="$PSR_FP/does-not-exist.sh" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_NX" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: the non-existent-helper record is unestablished" "yes" \
  "$(case "$(cat "$PSR_FP_NX/fingerprint.json" 2>/dev/null)" in *'"unestablished": true'*) echo yes ;; *) echo no ;; esac)"

# The rc!=0 conjunct: a producer printing a well-formed five-field fingerprint but EXITING
# NON-ZERO must NOT be trusted — a failed producer's stale-but-valid output can never discharge
# the gate (guards the `returncode == 0 and ...` conjunct against a fail-open weakening).
PSR_FP_OKFAIL="$PSR_FP/fp-ok-but-fail.sh"
cat > "$PSR_FP_OKFAIL" <<'PSR_EOF'
#!/usr/bin/env bash
printf '{"checkout_id":"/fix/.git","head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","index_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","tracked_digest":"cccccccccccccccccccccccccccccccccccccccc","untracked_digest":"dddddddddddddddddddddddddddddddddddddddd"}\n'
exit 1
PSR_EOF
chmod +x "$PSR_FP_OKFAIL"
PSR_FP_OF="$PSR_FP/rec-okfail"
assert_eq "psr fp: a well-formed fingerprint from a non-zero-exit producer records unestablished (rc 0)" "0" \
  "$(DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_OKFAIL" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_OF" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: a non-zero-exit producer's well-formed output is NOT trusted (unestablished)" "yes" \
  "$(case "$(cat "$PSR_FP_OF/fingerprint.json" 2>/dev/null)" in *'"unestablished": true'*) echo yes ;; *) echo no ;; esac)"

# AC1 wiring: the coordinator records the fingerprint in its retained run root at launch.
PSR_FPC="$(psr_make_tree)"; psr_plant_dispatcher "$PSR_FPC"
( cd "$PSR_FPC" && SYN_SHARDS=alpha SYN_SLEEP=0.05 DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_STUB" \
    DEVFLOW_SHARD_DISPATCHER="$PSR_FPC/dispatch.sh" bash lib/test/run-parallel.sh >/dev/null 2>&1 )
PSR_FPC_FILE="$(find "$PSR_FPC/.prflow/tmp/parallel-suite" -name fingerprint.json 2>/dev/null | head -n 1)"
assert_eq "psr fp: the coordinator records a fingerprint in its retained run root" "yes" \
  "$([ -n "$PSR_FPC_FILE" ] && [ -f "$PSR_FPC_FILE" ] && echo yes || echo no)"
assert_eq "psr fp: the coordinator's recorded fingerprint is the launch tree's" "yes" \
  "$(case "$(cat "$PSR_FPC_FILE" 2>/dev/null)" in *'"head":"aaaaaaaa'*) echo yes ;; *) echo no ;; esac)"

# AC2 wiring: run-shard.sh records the fingerprint in its retained tally dir at launch. Drive
# the real run-shard.sh over a stub run.sh so the monolith shard is instant.
PSR_SH="$PSR_FP/shard-tree"
mkdir -p "$PSR_SH/lib/test"
cp "$LIB/test/run-shard.sh" "$PSR_SH/lib/test/run-shard.sh"
cp "$PSR_TALLY" "$PSR_SH/lib/test/shard-tally.py"
cat > "$PSR_SH/lib/test/run.sh" <<'PSR_EOF'
#!/usr/bin/env bash
printf '1 passed, 0 failed\n'
PSR_EOF
chmod +x "$PSR_SH/lib/test/run.sh"
PSR_SH_TALLY="$PSR_FP/shard-tally-out"
( cd "$PSR_SH" && DEVFLOW_SHARD_TALLY_DIR="$PSR_SH_TALLY" DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_STUB" \
    bash lib/test/run-shard.sh monolith >/dev/null 2>&1 )
assert_eq "psr fp: run-shard.sh records a fingerprint in its retained tally dir" "yes" \
  "$([ -f "$PSR_SH_TALLY/fingerprint.json" ] && echo yes || echo no)"
assert_eq "psr fp: run-shard.sh's recorded fingerprint is the established launch tree's" "yes" \
  "$(case "$(cat "$PSR_SH_TALLY/fingerprint.json" 2>/dev/null)" in *'"head":"aaaaaaaa'*) echo yes ;; *) echo no ;; esac)"

# Default-helper + producer coupling (issue #2008): a sixth producer field silently ignored by
# same-tree-eligible would judge two different trees ELIGIBLE (a false green at the gate), so pin
# that checkout-fingerprint.py emits EXACTLY the five fields _FINGERPRINT_FIELDS compares.
PSR_FP_DEFAULT="$PSR_FP/rec-default"
python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_DEFAULT" >/dev/null 2>&1
assert_eq "psr fp: record-fingerprint with the DEFAULT helper writes an established record from the real producer" "yes" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_FP_DEFAULT/fingerprint.json" --fresh "$PSR_FP_DEFAULT/fingerprint.json" >/dev/null 2>&1 && echo yes || echo no)"
assert_eq "psr fp: checkout-fingerprint.py emits exactly the five coupled fields" \
  "checkout_id head index_digest tracked_digest untracked_digest" \
  "$(python3 "$LIB/../scripts/checkout-fingerprint.py" 2>/dev/null | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin))))' 2>/dev/null)"

# AC7: same-tree-eligible — identical fingerprints are ELIGIBLE; a single differing field or an
# absent/unestablished recorded fingerprint is refused (fail-closed).
PSR_EL="$PSR_FP/elig"
mkdir -p "$PSR_EL"
cp "$PSR_FP_OK/fingerprint.json" "$PSR_EL/recorded.json"
cp "$PSR_FP_OK/fingerprint.json" "$PSR_EL/fresh.json"
assert_eq "psr fp: identical fingerprints are eligible for the same-tree relaunch (rc 0)" "0" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: an eligible comparison prints ELIGIBLE" "yes" \
  "$(case "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/fresh.json" 2>&1)" in *ELIGIBLE*) echo yes ;; *) echo no ;; esac)"
sed 's/"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/"head":"9999999999999999999999999999999999999999"/' "$PSR_EL/fresh.json" > "$PSR_EL/fresh-drift.json"
assert_eq "psr fp: one differing fingerprint field refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/fresh-drift.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: the refusal names the differing field" "yes" \
  "$(case "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/fresh-drift.json" 2>&1)" in *"field 'head' differs"*) echo yes ;; *) echo no ;; esac)"
# Reverse coupling: same-tree-eligible must compare ALL five fields, so drifting EACH one
# individually refuses. A field dropped from _FINGERPRINT_FIELDS would let its own drift pass
# ELIGIBLE (a false green), and only this per-field sweep — not a head-only drift — catches it.
for psr_fld in checkout_id head index_digest tracked_digest untracked_digest; do
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); d[sys.argv[2]]="drifted-"+sys.argv[2]; json.dump(d,open(sys.argv[3],"w"))' \
    "$PSR_EL/fresh.json" "$psr_fld" "$PSR_EL/fresh-$psr_fld.json"
  assert_eq "psr fp: drifting fingerprint field '$psr_fld' refuses the same-tree relaunch (rc 1)" "1" \
    "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/fresh-$psr_fld.json" >/dev/null 2>&1; echo $?)"
done
assert_eq "psr fp: an absent recorded fingerprint refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/does-not-exist.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: an unestablished recorded fingerprint is refused too (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_FP_UN/fingerprint.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
# The fresh side fails closed identically — an absent or unestablished FRESH fingerprint refuses.
assert_eq "psr fp: an absent fresh fingerprint refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/does-not-exist.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: the fresh-side refusal names the fresh fingerprint" "yes" \
  "$(case "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_FP_UN/fingerprint.json" 2>&1)" in *"fresh fingerprint"*) echo yes ;; *) echo no ;; esac)"
# A syntactically malformed (non-JSON) fingerprint on either side fails closed (rc 1): the
# best-effort writer can leave a truncated file, which must never be read as a match.
printf 'this is not json' > "$PSR_EL/malformed.json"
assert_eq "psr fp: a non-JSON recorded fingerprint refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/malformed.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: a non-JSON fresh fingerprint refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/recorded.json" --fresh "$PSR_EL/malformed.json" >/dev/null 2>&1; echo $?)"
# Invalid UTF-8 bytes raise UnicodeDecodeError (a ValueError, NOT an OSError), so a read
# guard catching OSError alone escapes as a traceback instead of the INELIGIBLE breadcrumb.
printf '\377\376\000bad' > "$PSR_EL/badutf8.json"
assert_eq "psr fp: an invalid-UTF-8 recorded fingerprint refuses the same-tree relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/badutf8.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: the invalid-UTF-8 refusal breadcrumbs rather than tracebacks" "yes" \
  "$(case "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/badutf8.json" --fresh "$PSR_EL/fresh.json" 2>&1)" in *Traceback*) echo no ;; *"INELIGIBLE: recorded fingerprint unreadable"*) echo yes ;; *) echo no ;; esac)"
# The guarded write path: when the record file cannot be written (here fingerprint.json is a
# pre-existing directory), record-fingerprint breadcrumbs and still exits 0 — never blocks a launch.
PSR_FP_RO="$PSR_FP/rec-ro"
mkdir -p "$PSR_FP_RO/fingerprint.json"
assert_eq "psr fp: a record-write failure still exits 0 (launch never blocked)" "0" \
  "$(DEVFLOW_FINGERPRINT_HELPER="$PSR_FP_STUB" python3 "$PSR_TALLY" record-fingerprint --out "$PSR_FP_RO" >/dev/null 2>&1; echo $?)"
assert_eq "psr fp: a same-tree comparison against an unwritten record fails closed (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_FP_RO/fingerprint.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
# Best-effort-parser matrix (issue #2008): a valid-JSON non-object, and a valid object missing
# fields, each fail closed (rc 1) — a partial or wrong-shaped record the writer could leave must
# never read as a match.
printf '[]' > "$PSR_EL/not-object.json"
assert_eq "psr fp: a valid-JSON non-object recorded fingerprint refuses the relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/not-object.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"
printf '{"checkout_id":"x","head":"y"}' > "$PSR_EL/partial.json"
assert_eq "psr fp: a fingerprint object missing fields refuses the relaunch (rc 1)" "1" \
  "$(python3 "$PSR_TALLY" same-tree-eligible --recorded "$PSR_EL/partial.json" --fresh "$PSR_EL/fresh.json" >/dev/null 2>&1; echo $?)"

# AC6: the same-tree recombination combines tallies from TWO different run roots and fails
# closed, NAMING the shard, on a missing or a duplicated shard of the required partition.
PSR_RRA="$PSR_FP/rootA/tally"; PSR_RRB="$PSR_FP/rootB/tally"
psr_plant_named "$PSR_RRA/alpha" alpha
psr_plant_named "$PSR_RRA/beta" beta
psr_plant_named "$PSR_RRB/gamma" gamma
assert_eq "psr fp: a same-tree recombination across two run roots is clean (rc 0)" "0" \
  "$(python3 "$PSR_TALLY" combine "$PSR_RRA/alpha" "$PSR_RRA/beta" "$PSR_RRB/gamma" --expect 3 --require-shards "alpha beta gamma" >/dev/null 2>&1; echo $?)"
PSR_RR_MISS="$(python3 "$PSR_TALLY" combine "$PSR_RRA/alpha" "$PSR_RRB/gamma" --expect 2 --require-shards "alpha beta gamma" 2>&1)"; PSR_RR_MISS_RC=$?
assert_eq "psr fp: a missing shard across run roots fails closed (rc 1)" "1" "$PSR_RR_MISS_RC"
assert_eq "psr fp: the missing shard is named across run roots" "yes" \
  "$(case "$PSR_RR_MISS" in *"required shard(s) absent from the recombined tallies: beta"*) echo yes ;; *) echo no ;; esac)"
psr_plant_named "$PSR_RRB/alpha" alpha
PSR_RR_DUP="$(python3 "$PSR_TALLY" combine "$PSR_RRA/alpha" "$PSR_RRB/alpha" "$PSR_RRA/beta" --expect 3 --require-shards "alpha beta" 2>&1)"; PSR_RR_DUP_RC=$?
assert_eq "psr fp: a shard appearing in two run roots fails closed (rc 1)" "1" "$PSR_RR_DUP_RC"
assert_eq "psr fp: the duplicated shard is named across run roots" "yes" \
  "$(case "$PSR_RR_DUP" in *"recombined more than once: alpha"*) echo yes ;; *) echo no ;; esac)"

rm -rf "$PSR_ROOT"

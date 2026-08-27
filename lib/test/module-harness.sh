#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Fail-closed boundary for sourceable modules used by the complete test suite.
#
# MODULE-AUTHORING NOTE (issue #746) — spell a re-derived repo root as the
# $LIB-relative assignment `REPO_ROOT="$LIB/.."`, NOT as run.sh's
# `REPO_ROOT="$(cd "$LIB/.." && pwd)"`. Both name the same directory at run time, but
# lib/test/pin-corpus-lint.py's path resolver understands a `VAR="$LIB/relative"`
# assignment and bails on anything containing a command substitution. Copy the
# substitution form and every pin targeting a REPO_ROOT-derived var silently becomes
# UNRESOLVED — surfaced on that lint's stderr but never asserted, so the pins are
# exempt from the pin-in-comment and wrapped-literal meta-guards while the suite stays
# green. Teaching the resolver that one idiom would be the deeper fix (not filed — so
# this note, not a tracked issue, is what keeps the spelling requirement discoverable).

# record_fail <name> — the failing assertion's IDENTIFIER record (issue #789), the FAIL
# sibling of skip()'s SKIPS_FILE. RESULTS_FILE carries only the bare `PASS`/`FAIL` verdict
# token, so a completed run's tally says how many assertions failed but never which — and
# recovering that meant scrolling ~47,600 lines of captured output or, worse, relaunching a
# ~10-minute suite. Every site that writes a FAIL to the tally calls this alongside that
# write — in run.sh, here, and inside a module or pooled worker, whose private record is
# folded into the parent's beside its verdict tally — so the record covers the STDERR half
# of the suite's bi-stream failure output as well as the stdout half, and the boundary
# channel too. The terminal `Failure recap` at the tail re-lists it.
#
# The record's path is DERIVED from RESULTS_FILE rather than held in a global of its own,
# and that is load-bearing: the probes and meta-guards divert a recorded FAIL away from the
# suite tally by rebinding the variable for one call (`RESULTS_FILE="$probe" assert_…`), so
# a derived sibling follows every such diversion automatically and a probe's internal FAIL
# can never leak into the real run's recap. A second global would have to be rebound at
# every diversion site, and the one that was missed would be silent.
#
# Sanitization is bash-builtin only (never tr/sed): this value is EMITTED, and CLAUDE.md
# guard-class 2 bars a non-preflight PATH tool from deciding an emitted result — an absent
# tool would empty the identifier silently. Tab/newline/CR collapse to a space so one
# failure is always one line, and an empty name degrades to the same "(unnamed check)"
# placeholder skip() uses rather than a blank recap bullet.
record_fail() {  # name
  local _rf_name="${1//[$'\t'$'\n'$'\r']/ }"
  [ -n "$_rf_name" ] || _rf_name="(unnamed check)"
  printf '%s\n' "$_rf_name" >> "$RESULTS_FILE.names"
}

# module_host_capability_skip <name> <reason> <assertions-covered>  (issue #838)
#
# The module-reachable skip surface, and the answer to #838's reachability question:
# a module still may not self-skip in general — it may only declare that THIS HOST
# cannot express a condition, which is the `host-capability` kind alone.
#
# What enforces that, precisely — no single mechanism covers it, so do not read any one
# of them as doing so. The fold below validates the KIND only: it rejects a record whose
# kind is not `host-capability`, and it cannot tell a record written through this wrapper
# from one a module produced by calling `skip` directly or by appending a hand-crafted
# line. Keeping the RAW helper out of a module's reach is instead the job of two other
# mechanisms: lib/test/run-module.sh overrides `skip` so that only THIS wrapper's
# sanction-marked, host-capability-kinded delegation folds into a visible skip while a raw
# `skip` a module invokes directly stays a fatal contract violation (issue #887), and
# lib/test/test_module_runner.py scans every shipped module for a command-position `skip`
# line. A module that defeats all three is out of scope — this is a test harness, not a
# sandbox.
#
# It emits nothing itself. It delegates to `skip`, and bash resolves that name at CALL
# time — so one definition drives both tiers with no divergent second message to keep in
# sync. Under the full-suite boundary `skip` is run.sh's real helper (the sole `#456`
# producer of the reserved `  NOTE ` line) writing to the private per-module tally that
# boundary binds and folds back; under lib/test/run-module.sh `skip` is that runner's
# override, which — because this wrapper delegates with the sanction marker set and a
# `host-capability` kind — records the declaration to the focused runner's private skip
# tally (issue #887) rather than aborting, and the runner folds it and applies the credit
# below after `wait`. The credit line runs on both tiers.
#
# <assertions-covered> is the number of assertions the guarded arm does not run on this
# host. The boundary credits it against the module's assertion floor so a host taking
# the arm reports a visible skip instead of tripping the floor with a count mismatch
# that reads like a regression. It is a declaration, not a measurement: the boundary
# validates it and fails closed on every shape it cannot use.
module_host_capability_skip() {  # name reason assertions-covered
  local _hcs_name="$1" _hcs_reason="$2" _hcs_credit="${3:-0}"
  # The command-scoped assignment marks THIS delegating call as the sanctioned
  # host-capability path for lib/test/run-module.sh's focused `skip` override (issue
  # #887): a raw `skip` a module invokes directly never carries the marker, so the
  # focused tier folds a host-capability declaration into a visible skip while a raw
  # self-skip stays a fatal contract violation. The assignment is temporary to the call
  # and restored after it, so nothing leaks past this line. run.sh's real `skip` (the
  # full-suite tier) does not read the marker, so full-suite behavior is unchanged.
  _DEVFLOW_SANCTIONED_HOST_CAPABILITY_SKIP=1 skip "$_hcs_name" host-capability "$_hcs_reason"
  # Recorded as ONE line — the boundary is the validator, so a malformed declaration is
  # rejected there with an attributable failure rather than repaired here. The only
  # transform is load-bearing and must stay: collapsing TAB/NL/CR to spaces keeps a
  # multi-line declaration ("2\n3") from splitting into two separately-valid credit
  # lines at the validator, which would launder it into 5 credits. The collapsed
  # result is not digits-only, so the validator still rejects it, attributably.
  #
  # The write is GUARDED, and the guard terminates rather than returning (issue #899
  # review). A dropped credit line is not a safe loss: the boundary's reject arm zeroes
  # the credit only when the total reaches MIN_ASSERTIONS, so losing SOME of several
  # credit lines can move a run from the rejected state (strict floor) into the accepted
  # state (lowered floor) — e.g. two arms crediting 2 and 5 against MIN=6 pass the reject
  # arm at 5 if the `2` write is lost, and the module then clears a floor of 1. That is
  # fail-OPEN in the one path whose entire purpose is to fail closed, so the write may
  # not be best-effort.
  #
  # Why `exit 1` and not this file's overwhelmingly more common `return 1`: every
  # `return 1` here lives in a function whose CALLER inspects the status (`|| return 1`,
  # `|| :`, an `if` head). This wrapper is invoked as a bare statement from a module arm,
  # and neither runner sets `-e` (both are `set -u` only — see the mktemp-guard note
  # above), so a nonzero return from here is discarded by every real call site and would
  # reproduce the very fail-open being closed. Termination is contained: on BOTH tiers
  # the module body runs inside the backgrounded worker subshell _devflow_supervise_module
  # launches, so this exits that worker alone — the full-suite boundary reports
  # "exited with status 1" as an attributable module FAIL and the focused runner fails the
  # module the same way. The blast radius is one module, never the suite. This file's other
  # `exit 1` sites (_devflow_module_supervisor_signal and _devflow_full_suite_signal)
  # terminate on the same basis, and the sibling SKIPS_FILE write in
  # lib/test/run-module.sh's focused `skip` override guards identically.
  if [ -n "${MODULE_SKIP_CREDIT_FILE:-}" ]; then
    printf '%s\n' "${_hcs_credit//[$'\t'$'\n'$'\r']/ }" >> "$MODULE_SKIP_CREDIT_FILE" || {
      printf 'FATAL: could not record host-capability skip credit\n' >&2; exit 1; }
  fi
}

# ── Inherited-DEVFLOW_GH fixture isolation (issue #533 AC13, generalized #695) ─
# The same clearing lib/test/run.sh performs in its preamble, performed here so
# EVERY caller that sources this harness — the complete suite AND the focused
# lib/test/run-module.sh runner — runs module bodies under identical isolation.
# The resolvers treat a non-empty DEVFLOW_GH as the strongest explicit override
# (no probe), so a value leaked in from the invoking environment would silently
# outrank every fixture-local PATH stub a module installs, making a focused run
# report environmental failures on a clean baseline. Both runners source this
# harness BEFORE any module body, so the clear always precedes module execution.
# Tests that exercise the override contract reintroduce their own value with a
# per-invocation `DEVFLOW_GH=… cmd` prefix, which is unaffected by this clear.
# Disclosed, never silent — and a no-op (no second breadcrumb) under run.sh,
# whose preamble already unset it before this file is sourced.
[ -n "${DEVFLOW_GH:-}" ] && printf 'module-harness.sh: clearing inherited DEVFLOW_GH=%s for module fixture isolation (issue #533 AC13); override-contract tests re-set their own value per-invocation\n' "$DEVFLOW_GH" >&2
unset DEVFLOW_GH

# ── Shared fixture helpers promoted from lib/test/run.sh (issue #695) ─────────
# These three were defined in the monolith and used by the installer/workflow-
# wiring coverage extracted into lib/test/modules/installer-wiring.sh. They are
# PROMOTED, not copied: lib/test/run.sh obtains them by sourcing this file, so no
# second definition exists anywhere in the tree (the coupled-mirror defect class).

# Extract one step's block from a workflow: from its `- name:` line to the
# next sibling step's `- name:` (6-space step indent, matching these workflows)
# OR the enclosing job's end (a 2-space-indented key, i.e. the next job) —
# without the job-boundary stop, a job's LAST named step would bleed into the
# following job's header and name-less steps, un-scoping the assertions run
# against the block. Matched with index() (literal substring), not a regex —
# the step names carry regex metacharacters ("(optional)").
mint_blk() {
  awk -v n="$1" '
    index($0, "- name: " n){f=1}
    f && /^      - name:/ && index($0, "- name: " n) == 0{exit}
    f && /^  [^ ]/{exit}
    f{print}' "$2"
}

# Allocate a temp file for a mutation proof, failing the SUITE (not vacuously passing) if
# mktemp fails. The anti-vacuity proofs build mutated temp copies; under `set -u`
# without `set -e` a bare `VAR="$(mktemp)"` failure would leave VAR empty, and a control
# that then reads an empty path silently degrades to its EXPECTED value (e.g. grep over ""
# prints 0, which a "expected 0" control accepts) — the anti-vacuity proof itself going
# vacuous, the exact class this helper exists to kill. On mktemp failure this records a
# suite FAIL under NAME, prints the human breadcrumb to STDERR (so it reaches the operator
# instead of being captured into the caller's `$(…)`), and prints the safe sink path
# `/dev/null` to STDOUT. The `/dev/null` is deliberate: an unguarded caller that then does
# `printf … > "$path"` or greps "$path" causes NO working-tree pollution and no spurious
# redirect error (an earlier form printed the breadcrumb itself, which a `> "$breadcrumb"`
# turned into a junk file in the repo cwd). The recorded FAIL still makes the suite go RED,
# so the proof remains fail-closed whether or not the caller checks the rc 1.
probe_tmp() {  # assertion-name -> prints a temp path (rc 0); on mktemp failure records a
               # suite FAIL, prints the breadcrumb to stderr, and prints /dev/null (rc 1)
  local t
  t="$(mktemp)" && { printf '%s\n' "$t"; return 0; }
  echo FAIL >> "$RESULTS_FILE"
  printf '  FAIL  %s — mktemp failed (mutation proof could not run; not a vacuous pass)\n' "$1" >&2
  record_fail "$1 — mktemp failed (mutation proof could not run)"
  printf '/dev/null\n'
  return 1
}

# Allocate a verified-isolated temp DIRECTORY for a git-mutating test, failing the
# SUITE (not vacuously, and NEVER in the real repo) if `mktemp -d` fails. The
# directory twin of probe_tmp. Callers live in lib/test/run.sh and in the sourcing
# modules under lib/test/modules/, not in this file: they run `git init/add/commit` — or a
# helper that commits via `git -C "$root"` — inside a throwaway repo. Under this
# harness's `set -u` WITHOUT `set -e`, a bare `DIR="$(mktemp -d)"` failure leaves DIR
# the empty string (set, not unset, so `set -u` does not abort), and BOTH `cd "$DIR"`
# AND `git -C "$DIR"` then silently operate on the CURRENT directory — the real repo —
# so the test's commit lands on the real branch. (`git -C ""` leaves the cwd unchanged
# per git(1)'s -C semantics; it is NOT safer than `cd ""`, which is why this guard
# protects the `git -C` sites too, not only the `cd` ones.)
#
# On `mktemp -d` failure (or an empty / non-directory result) this records a suite FAIL
# under NAME, prints the breadcrumb to STDERR (so it never lands in the caller's `$(…)`),
# and prints a guaranteed-non-directory sentinel path ROOTED AT /dev/null to STDOUT. The
# sentinel is the load-bearing safety: `cd`, `git -C`, and `mkdir -p` on any path under
# /dev/null all fail with ENOTDIR (kernel-enforced — even as root, since /dev/null can
# never become a directory), so an unguarded caller that then runs `git -C "$DIR" …`,
# `( cd "$DIR" && … )`, or `mkdir -p "$DIR/…"` fails CLOSED with ZERO real-repo mutation
# instead of falling back to the cwd. The recorded FAIL makes the suite go RED whether or
# not the caller checks the rc 1 — fail-closed either way (mirrors probe_tmp's /dev/null
# safe-sink discipline, applied to directories).
#
# Caller contract: callers do NOT each need to guard the return — routing the temp-dir
# allocation through this helper is sufficient. On `mktemp -d` failure the helper records
# ONE per-site suite FAIL with a site-named breadcrumb (that pair is the authoritative
# signal), and the sentinel makes every downstream `git -C`/`cd`/`mkdir` at an unguarded
# call site fail closed (ENOTDIR) on its own. An unguarded site's *subsequent* assertions
# may then go RED too (their setup didn't run) — that secondary cascade is harmless extra
# RED, never a real-repo mutation, and is the deliberate trade for keeping each call-site
# conversion a one-line change rather than wrapping every fixture in a guard.
# (`rgb_scan`, in lib/test/run.sh, guards explicitly only because it also needs to branch
# on `git init` success and clean up its dir; that extra guard is about cleanup, not safety.)
#
# Dependency: like assert_eq / probe_tmp, the failure path writes the FAIL via
# `echo FAIL >> "$RESULTS_FILE"`, so callers must have RESULTS_FILE in scope — it is set
# globally (the suite tally file) and never unset, so every call site qualifies. The #161
# AC3 probes (in lib/test/run.sh) deliberately override it per-call (`RESULTS_FILE=… git_sandbox …`) to divert the
# intentional FAIL into an isolated file; that is the only supported reason to rebind it.
git_sandbox() {  # assertion-name -> prints an isolated temp dir (rc 0); on mktemp -d
                 # failure records a suite FAIL, prints the breadcrumb to stderr, and
                 # prints the /dev/null-rooted sentinel (rc 1) so a downstream
                 # git -C / cd / mkdir fails CLOSED rather than hitting the real repo
  local d
  d="$(mktemp -d)" && [ -n "$d" ] && [ -d "$d" ] && { printf '%s\n' "$d"; return 0; }
  # The recap bullet names the INFRASTRUCTURE cause, not just the assertion: read from the
  # recap alone, a bare assertion name is indistinguishable from a genuine failure and sends
  # the reader to debug an assertion that never ran. (probe_tmp does the same.) The two
  # writes stay ADJACENT — the pairing the completeness guard scans for.
  echo FAIL >> "$RESULTS_FILE"
  record_fail "$1 — mktemp -d failed (git sandbox unavailable)"
  printf '  FAIL  %s — mktemp -d failed (git sandbox unavailable; git work aborted, not run in the real repo)\n' "$1" >&2
  printf '/dev/null/devflow-git-sandbox-unavailable\n'
  return 1
}

# Run a single assertion function against an ISOLATED results file and echo its verdict
# (PASS/FAIL) instead of recording it in the tally of whichever runner is executing. Used
# by the mutation proofs to actually exercise an assertion helper against a mutated target
# and confirm it goes RED, without that intentional RED counting as a failure. The
# `RESULTS_FILE=…` prefix on a function call sets the var only for that call's environment
# (functions are not special builtins), so the caller's RESULTS_FILE is untouched — the
# contract that keeps a module's executed-assertion count reflecting only real assertions.
probe_assert() {  # assertion-fn args... -> prints PASS or FAIL (the probed verdict)
  # Guard mktemp (the runners are `set -u` without `set -e`, so a bare failure would not
  # abort): an empty $probe would make `tail ""` error and the probe echo empty, surfacing
  # as a MISLEADING wrong-verdict mismatch instead of an environment failure. Emit a
  # distinct breadcrumb token so the cause is unambiguous — note it surfaces as an
  # `assert_eq` mismatch (expected PASS/FAIL, got PROBE_MKTEMP_FAILED), not a recorded
  # FAIL, so the proof still goes RED but via the comparison rather than the tally.
  # DETAILS_FILE is redirected alongside RESULTS_FILE because run-module.sh's assert_eq
  # writes a failure-recap row there on FAIL. Isolating only the tally would keep the
  # probed RED out of the assertion count but still surface it in the focused runner's
  # "Failure recap", reading as a real failure. run.sh's assert_eq has no DETAILS_FILE,
  # so the extra prefix is inert there.
  local probe; probe="$(mktemp)" || { echo "PROBE_MKTEMP_FAILED"; return 0; }
  RESULTS_FILE="$probe" DETAILS_FILE="$probe.details" "$@" >/dev/null 2>&1
  tail -n 1 "$probe"
  # `$probe.names` is run.sh's record_fail sibling (issue #789): because its path is derived
  # from RESULTS_FILE, the diversion above sends the probed assertion's identifier there too
  # — which is exactly the isolation wanted (a probed FAIL never reaches the real run's
  # recap), but it means this cleanup owns the sibling as much as it owns `$probe.details`.
  rm -f "$probe" "$probe.details" "$probe.names"
}

# ── Namespaced module pin/count/mutation helpers (issue #577) ────────────────
# Shared reusable pin machinery for sourceable contract modules, so a module
# carries NO private copy of it. Caller contract: RESULTS_FILE is set and assert_eq
# is defined (both runner paths — run-module.sh and the full-suite boundary below —
# provide them). These helpers perform synchronous cleanup and install NO traps
# (the sourcing module owns the sole EXIT trap over its private temp root).
#
# devflow_module_pin_count LITERAL FILE
#   Fixed-string occurrence counter over FILE, via CHECKED python3 (a hard preflight
#   prerequisite). Prints an established non-negative integer and returns 0 ONLY
#   after a successful readable scan. On ANY failure — an unreadable file, a missing
#   or failed python3 interpreter, or malformed counter output — it prints the
#   sentinel `unestablished` (NEVER `0`) to stdout, writes a specific breadcrumb to
#   stderr, and returns 1. Returning `unestablished` rather than `0` is the whole
#   point: a fail-open `grep … || n=0` counter returns 0 on failure, so a
#   zero-expected assertion (`assert_eq … 0 "$(counter …)"`) passes vacuously; here
#   the failure value is not a number, so every consuming assertion — assert_eq or
#   the pin helpers below — records a FAIL through the assertion channel and a
#   zero-expected assertion turns RED. That is how read/interpreter/malformed-output
#   failures are recorded through the assertion channel instead of returning zero.
devflow_module_pin_count() { # literal file
  local literal="$1" file="$2" out rc
  if [ ! -f "$file" ] || [ ! -r "$file" ]; then
    printf 'unestablished\n'
    printf 'devflow-module-count: unreadable file: %s\n' "$file" >&2
    return 1
  fi
  # Literal + path pass as argv (never interpolated into the program text), so a
  # literal containing quotes, `$`, or backticks cannot re-enter shell or Python
  # parsing. A non-UTF-8 read or any interpreter fault surfaces as rc != 0 below.
  out="$(python3 -c '
import sys
with open(sys.argv[1], encoding="utf-8") as fh:
    text = fh.read()
print(sum(line.count(sys.argv[2]) for line in text.splitlines()))
' "$file" "$literal" 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'unestablished\n'
    printf 'devflow-module-count: python3 counter failed (rc=%s) on: %s\n' "$rc" "$file" >&2
    return 1
  fi
  case "$out" in
    ''|*[!0-9]*)
      printf 'unestablished\n'
      printf 'devflow-module-count: malformed counter output %s on: %s\n' "${out:-(empty)}" "$file" >&2
      return 1
      ;;
  esac
  printf '%s\n' "$out"
}

# devflow_module_pin_unique NAME LITERAL FILE
#   Exactly-one presence pin: PASS iff LITERAL occurs exactly once in FILE. An
#   unestablished count fails the assert_eq (RED), never passes as a bare "1".
devflow_module_pin_unique() { # name literal file
  assert_eq "$1" "1" "$(devflow_module_pin_count "$2" "$3")"
}

# devflow_module_pin_present NAME LITERAL FILE
#   At-least-one presence pin: PASS iff LITERAL occurs one or more times in FILE
#   (for values that legitimately recur, where an exactly-one pin would be wrong).
#   Folds an unestablished count to "no" so it fails closed (RED), never vacuously.
devflow_module_pin_present() { # name literal file
  local n
  n="$(devflow_module_pin_count "$2" "$3")"
  case "$n" in
    ''|*[!0-9]*) assert_eq "$1" "yes" "no"; return 0 ;;
  esac
  [ "$n" -ge 1 ] && assert_eq "$1" "yes" "yes" || assert_eq "$1" "yes" "no"
}

_devflow_valid_result_count() {
  local tally_file="${1:-$RESULTS_FILE}" invalid_count count grep_rc
  [ -f "$tally_file" ] && [ -r "$tally_file" ] || return 1

  grep_rc=0
  invalid_count="$(grep -cEv '^(PASS|FAIL)$' "$tally_file")" || grep_rc=$?
  [ "$grep_rc" -le 1 ] || return 1
  [ "$invalid_count" -eq 0 ] || return 1

  grep_rc=0
  count="$(grep -cE '^(PASS|FAIL)$' "$tally_file")" || grep_rc=$?
  [ "$grep_rc" -le 1 ] || return 1
  printf '%s\n' "$count"
}

# _devflow_echo_capture <path> — echo a captured test output, indented four spaces.
#
# Pure-bash indent: piping through sed (a non-preflight PATH tool) would lose the whole
# captured traceback when sed is absent — the diagnostics must never fail open even though
# the verdicts that consume them fail closed. It writes to STDOUT, so a failing check's
# header and its traceback stay on one stream instead of interleaving; callers that print
# a header before calling this must print it to stdout too. (`_devflow_pool_reap` keeps
# its own inline copy — it echoes a pooled suite's output from a different code path and
# was not part of this change.)
_devflow_echo_capture() {  # path
  local _devflow_line
  if [ ! -r "$1" ]; then
    # Never silent: an empty diagnostic body would leave the reader unable to tell "the
    # check printed nothing" from "the capture vanished".
    printf '    (no captured output: %s is missing or unreadable)\n' "$1"
    return 0
  fi
  while IFS= read -r _devflow_line || [ -n "$_devflow_line" ]; do
    printf '    %s\n' "$_devflow_line"
  done < "$1"
}

devflow_run_focused_python_test() { # assertion-name script-path output-path
  local assertion_name="$1" script_path="$2" output_path="$3" test_rc

  # PYTHON_COLORS=0 keeps the captured diagnostics deterministic: a host that
  # forces color (FORCE_COLOR) would otherwise interleave ANSI codes into the
  # traceback text that downstream assertions and human readers match against.
  if PYTHON_COLORS=0 python3 "$script_path" > "$output_path" 2>&1; then
    test_rc=0
  else
    test_rc=$?
    _devflow_echo_capture "$output_path"
  fi
  assert_eq "$assertion_name" "0" "$test_rc"
}

# devflow_run_sharded_python_test <assertion-name> <script-path> <capture-dir> [full|smoke]
#
# The concurrent sibling of devflow_run_focused_python_test (issue #870): it runs ONE
# python3 unittest file as many bounded-concurrency selector processes and folds every
# one of them into a SINGLE assert_eq. The single-assertion shape is a contract, not a
# style choice — a module's emitted tally is compared for equality against the assertion
# floor carried in scripts/workflow-flight-recorder-registry.json AND in run.sh's
# devflow_run_full_suite_module operand, so a per-unit assertion would move the tally
# with the host's cpu_count and break that triple on every runner of a different width.
#
# Scheduling is a DYNAMIC work queue, not a precomputed partition, and that is the
# design's core: this file's per-test cost spans two orders of magnitude, so any static
# split — round-robin, contiguous, or by class — floors the wall clock at whichever
# bucket happens to collect the heaviest tests. A queue needs no cost knowledge and no
# cost cache, self-corrects on any host, and re-balances for free when a test is added,
# renamed, or made slower. Its cost is one interpreter start per test instead of one per
# worker, which is a few seconds of CPU spread across the workers.
#
# KNOWN CEILING, so nobody re-derives it from a disappointing measurement: a greedy queue
# dispatches in enumeration order, which is alphabetical, so a long-running test that
# sorts late starts late and its duration lands past the point where the other workers
# have drained. The wall clock therefore floors at roughly (dispatch time of the longest
# test + its duration), not at total/width. Beating that needs longest-first scheduling,
# which needs per-test durations — knowledge this driver deliberately does not carry and
# could not use anyway on the CI runners this exists to speed up, where any duration
# cache starts cold on every run. Making the individual fixtures cheaper is the lever
# that moves this ceiling.
#
# Concurrency comes from _devflow_pool_resolve_width, the same resolver devflow_pool_open
# uses, so this file carries one width policy rather than two. In-flight work never
# exceeds it: a module already runs concurrently with the suite's open pool, so going
# wider would trade the serial time saved for CPU and IO contention. KNOWN LIMITATION —
# the two mechanisms share that width POLICY but not one width BUDGET, so peak process
# count while the suite's pool is open is the pool's in-flight count plus this width. A
# shared budget is the deeper design; it is not reachable while the pool emits one
# RESULTS_FILE verdict per member (which would break the tally triple above) and is
# opened by run.sh, which may not name this module's subject file at all.
#
# Every failure mode below fails closed — a unit is never silently green — and each
# arm carries its own breadcrumb naming which condition fired. The one worth stating
# outright is the lossy-schedule regression: a scheduler that quietly skips work makes
# the suite go green having tested less, so the executed total is checked against the
# enumerated one. That sum decides the emitted verdict, so it is accumulated with bash
# builtins and never through a non-preflight PATH tool (CLAUDE.md guard-class 2).
#
# Workers are launched WITHOUT a new process group (no `set -m`, no setsid) so they stay
# in the module worker's group and _devflow_terminate_process_group's group-wide signal
# delivery reaches them. Each unit's exit status is recorded by the unit itself into its
# own `.rc` file rather than inferred from a bare `wait`, which returns 0 regardless of
# what its children did and so surfaces no failure at all.
#
# Four DEVFLOW_TEST_SHARD_* hooks exist so lib/test/test_module_harness.py can drive arms
# that are otherwise unreachable from a test; each is read at exactly one site below.
#   DEVFLOW_TEST_SHARD_PYTHON          substitutes the interpreter used for the UNIT
#                                      launches only, never the enumeration (spawn-failure
#                                      and no-parseable-count arms).
#   DEVFLOW_TEST_SHARD_DROP_ONE        skips DISPATCHING one unit while the collection loop
#                                      still visits it, so that unit records no `.rc`
#                                      (missing-status arm).
#   DEVFLOW_TEST_SHARD_SKIP_ONE        skips one unit in BOTH loops, so every collected unit
#                                      has a `.rc` and the shortfall surfaces only in the
#                                      dispatched/executed-vs-enumerated comparison — the
#                                      arm DROP_ONE cannot reach, because the missing-`.rc`
#                                      arm populates `failure` first.
#   DEVFLOW_TEST_SHARD_FORCE_SERIAL_REAP  forces the pre-bash-4.3 specific-pid reap branch
#                                      on a modern shell (the driver's only index
#                                      arithmetic).
# PRECONDITION: capture-dir must be a FRESH, exclusively-owned, writable directory. The
# collection loop trusts every unit-<n>.out{,.err,.rc} it finds there, so a reused
# directory feeds a prior call's results into this call's count and defeats the
# executed-vs-enumerated check. The one shipped call site allocates a per-call `mktemp -d`.
#
# OPTIONAL FOURTH ARGUMENT — the population mode (issue #890). This is where the mode's
# meaning is defined; the module call site (lib/test/modules/harness-python-guards.sh)
# points here rather than restating it.
#
# COUPLED SITES for the `bound_note` sentence below: it is not decoration — it is the only
# signal a caller has that a run took the bounded path, and it is asserted in
# lib/test/test_module_harness.py (both its presence on a bounded run and its absence on a
# full one) and in lib/test/test_module_runner.py, whose assertRegex on it is what stops
# dropped flag plumbing from silently restoring a duplicate execution. Reword it and
# reconcile those.
#   full  — the default, applied when the argument is absent OR empty, so a caller that
#           says nothing (or forwards an unset variable) always gets every test.
#   smoke — enumerate only the FIRST test of each test CLASS that the loader produced a test
#           for. The enumerate → dispatch → collect → fold path is exercised in full and one
#           test of each such class runs; only the per-test repetition drops. It exists for a
#           caller that drives a file purely to prove the driver drives it. Note what this
#           does NOT claim: a class the loader yields no test for (no `test_`-prefixed
#           methods) contributes nothing to enumerate in either mode, so `smoke` does not
#           reach it — the bound is over the loader's output, not over the file's classes.
#   anything else — fails CLOSED: nothing is enumerated, nothing runs, and the call records
#           a FAIL naming the bad value, so a typo can never read as a bounded pass.
devflow_run_sharded_python_test() { # assertion-name script-path capture-dir [full|smoke]
  local assertion_name="$1" script_path="$2" capture_dir="$3"
  local mode="${4:-full}"
  local unit_python="${DEVFLOW_TEST_SHARD_PYTHON:-python3}"
  local width total dispatched=0 executed=0 launched=0 reaped=0 reap_any failure=""
  local plan_out plan_err index unit_rc unit_ran num cap bound_note=""
  local -a ids=() pids=()

  case "$mode" in
    full) ;;
    smoke) bound_note=", BOUNDED smoke subset — the full population did NOT run" ;;
    *)
      # Refuse before enumeration or dispatch, carrying the `devflow shard driver:` prefix
      # this function's terminal failure report also uses.
      printf '    devflow shard driver: unrecognized population mode %s (expected full or smoke)\n' \
        "$mode"
      assert_eq "$assertion_name" "" \
        "unrecognized population mode '$mode' (expected full or smoke)"
      return
      ;;
  esac

  width="$(_devflow_pool_resolve_width)"
  # `wait -n` (reap any one job) exists from bash 4.3. BASH_VERSINFO is a shell builtin,
  # so this decides the reaping strategy without a non-preflight PATH tool.
  # DEVFLOW_TEST_SHARD_FORCE_SERIAL_REAP forces the pre-4.3 branch on a modern shell so
  # lib/test/test_module_harness.py can drive its pids[]/reaped bookkeeping — otherwise
  # that arm, which holds the driver's only index arithmetic, ships unexercised
  # everywhere the suite runs.
  reap_any=""
  if [ -z "${DEVFLOW_TEST_SHARD_FORCE_SERIAL_REAP:-}" ] &&
     { [ "${BASH_VERSINFO[0]:-0}" -gt 4 ] ||
       { [ "${BASH_VERSINFO[0]:-0}" -eq 4 ] && [ "${BASH_VERSINFO[1]:-0}" -ge 3 ]; }; }; then
    reap_any=1
  fi
  plan_out="$capture_dir/unit-plan.out"
  plan_err="$capture_dir/unit-plan.err"

  # Enumerate the file's test IDs from the loader rather than a frozen list, so a newly
  # added class is scheduled (and counted) without editing this driver. In `full` mode the
  # printed count IS "the number an unsharded run would execute" — derived by collection
  # only, never by a second full serial run, which would cost exactly what this saves. In
  # `smoke` mode it is the number of test classes the loader produced at least one test for
  # (see the mode contract above for why that is not the same as the file's class count),
  # and the executed-vs-enumerated check
  # below is unchanged: it compares against whatever this enumeration decided, so a
  # bounded run still fails closed on dropped work.
  if ! PYTHON_COLORS=0 python3 - "$script_path" "$mode" > "$plan_out" 2> "$plan_err" <<'DEVFLOW_SHARD_ENUM'
import importlib.util
import pathlib
import sys
import unittest

path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("devflow_shard_enum_probe", path)
if spec is None or spec.loader is None:
    print("could not load %s as a python module" % path, file=sys.stderr)
    raise SystemExit(1)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

loader = unittest.TestLoader()
suite = loader.loadTestsFromModule(module)
# Both checks are kept deliberately, and NEITHER is dead: on a raising `load_tests`,
# loadTestsFromModule records an entry here AND substitutes a _FailedTest placeholder into
# the suite, so the two arms are first and second line of defense over one input. Removing
# this one is observable — the _FailedTest scan still refuses, but the diagnostic text is
# lost (mutation-verified against test_a_collection_time_load_error_fails_closed, which
# pins that text). This value is the total the whole fail-closed contract is measured
# against, so it is cheaper to refuse twice than to trust a placeholder as a real test.
if loader.errors:
    for entry in loader.errors:
        print(entry, file=sys.stderr)
    raise SystemExit(1)


def flatten(item):
    if isinstance(item, unittest.TestSuite):
        for child in item:
            yield from flatten(child)
    else:
        yield item


# Validated by the caller's own `case`, so an unexpected value cannot reach here.
smoke = sys.argv[2] == "smoke"

selectors = []
seen_classes = set()
prefix = spec.name + "."
for test in flatten(suite):
    if type(test).__name__ == "_FailedTest":
        print("unloadable test entry: %s" % test.id(), file=sys.stderr)
        raise SystemExit(1)
    # Grouping on the live class object rather than on a substring of the identifier: it
    # is exact by construction, so a nested or same-named class cannot collapse into a
    # sibling's group. Enumeration order is preserved, so the bound is deterministic.
    if smoke:
        if type(test) in seen_classes:
            continue
        seen_classes.add(type(test))
    identifier = test.id()
    if identifier.startswith(prefix):
        identifier = identifier[len(prefix):]
    selectors.append(identifier)

if not selectors:
    print("no tests were enumerated in %s" % path, file=sys.stderr)
    raise SystemExit(1)
print("\n".join(selectors))
DEVFLOW_SHARD_ENUM
  then
    failure="the unsharded test count could not be established — enumerating $script_path failed"
    _devflow_echo_capture "$plan_err"
  fi

  if [ -z "$failure" ]; then
    while IFS= read -r num || [ -n "$num" ]; do
      [ -n "$num" ] && ids+=("$num")
    done < "$plan_out"
    total="${#ids[@]}"
    # BACKSTOP, not the primary zero-test guard: the enumerator already exits 1 on an
    # empty selector list, so a file with no tests reaches the enumeration-failure arm
    # above and never this one. This arm covers the residual shape that refusal cannot —
    # an enumerator that exits 0 having written nothing readable (a truncated or
    # unreadable plan file). It is therefore not driven by the no-tests fixture in
    # lib/test/test_module_harness.py, which exercises the enumerator's own refusal.
    [ "$total" -gt 0 ] || \
      failure="the enumeration of $script_path reported zero tests"
  fi

  if [ -z "$failure" ]; then
    # One unit per test, at most $width in flight. Each unit records its OWN exit status
    # into <capture>.rc from inside the background subshell, so a status is attributed to
    # its unit by file rather than by racing to match a pid against `wait`'s return.
    for ((index = 0; index < total; index++)); do
      if [ -n "${DEVFLOW_TEST_SHARD_DROP_ONE:-}" ] && [ "$index" -eq 0 ]; then continue; fi
      if [ -n "${DEVFLOW_TEST_SHARD_SKIP_ONE:-}" ] && [ "$index" -eq 0 ]; then continue; fi
      # Reap ONE unit per freed slot, ignoring its exit status — a unit's authoritative
      # status is the one it wrote to its own .rc file, which the collection loop below
      # reads. Two spellings are deliberately NOT used here. `wait -n || wait` reaps the
      # whole pool whenever the reaped unit exited non-zero (because `wait -n` returns
      # that status), which still bounds concurrency but schedules in batched waves
      # instead of a rolling queue. A bare `wait -n` fails open instead: the builtin
      # arrived in bash 4.3, and on an older shell it reaps NOTHING, so the gate would
      # never block and the fan-out would be unbounded. Hence the version check, with a
      # specific-pid wait as the pre-4.3 fallback — bounded, at the cost of head-of-line
      # blocking behind a slow unit.
      while [ "$launched" -ge "$width" ]; do
        if [ -n "$reap_any" ]; then
          wait -n 2>/dev/null || true
        else
          wait "${pids[reaped]}" 2>/dev/null || true
          reaped=$((reaped + 1))
        fi
        launched=$((launched - 1))
      done
      cap="$capture_dir/unit-$index.out"
      (
        # stdout and stderr are captured SEPARATELY, and that separation is load-bearing:
        # the count below is parsed from the stderr capture alone. A unit's stdout is
        # block-buffered to a file and flushed at interpreter exit — i.e. AFTER unittest's
        # unbuffered stderr summary — so a merged capture lets a test that prints a line
        # of the runner's shape land last and win the parse, inflating the executed count
        # in the one direction the aggregate comparison cannot catch.
        PYTHON_COLORS=0 "$unit_python" "$script_path" "${ids[index]}" > "$cap" 2> "$cap.err"
        printf '%s\n' "$?" > "$cap.rc"
      ) &
      pids[dispatched]=$!
      launched=$((launched + 1))
      dispatched=$((dispatched + 1))
    done
    wait

    for ((index = 0; index < total; index++)); do
      # SKIP_ONE alone elides the unit here too, leaving every VISITED unit with a `.rc`
      # so `failure` is still empty when the count comparison below runs. DROP_ONE
      # deliberately does NOT, which is what makes the two hooks reach different arms.
      if [ -n "${DEVFLOW_TEST_SHARD_SKIP_ONE:-}" ] && [ "$index" -eq 0 ]; then continue; fi
      cap="$capture_dir/unit-$index.out"
      if [ ! -e "$cap.rc" ]; then
        # The unit's subshell died before recording its status (OOM, a group signal, a
        # fork failure, an unwritable capture dir). Skipping it silently would leave the
        # aggregate count as its only backstop, and that count is a sum — another unit
        # over-reporting would mask this one entirely. Fail it by name instead.
        [ -n "$failure" ] || failure="${ids[index]} recorded no exit status"
        printf '    %s recorded no exit status (its worker died before writing one)\n' \
          "${ids[index]}"
        continue
      fi
      unit_rc=""
      IFS= read -r unit_rc < "$cap.rc" || unit_rc=""
      case "$unit_rc" in
        ''|*[!0-9]*) unit_rc=1 ;;
      esac
      # Parsed from the STDERR capture only (see the launch above for why), taking the
      # last match: unittest emits this line near the end of its own stderr, followed by
      # a blank line and OK/FAILED.
      unit_ran=""
      if [ -r "$cap.err" ]; then
        while IFS= read -r num || [ -n "$num" ]; do
          case "$num" in
            "Ran "*" test"*)
              num="${num#Ran }"
              num="${num%% *}"
              case "$num" in
                ''|*[!0-9]*) : ;;
                *) unit_ran="$num" ;;
              esac
              ;;
          esac
        done < "$cap.err"
      fi
      if [ "$unit_rc" -ne 0 ]; then
        [ -n "$failure" ] || failure="${ids[index]} exited $unit_rc"
        printf '    %s exited %s:\n' "${ids[index]}" "$unit_rc"
        _devflow_echo_capture "$cap.err"
        _devflow_echo_capture "$cap"
      fi
      # Each unit runs exactly ONE selector, so its count is exactly 1 — asserted
      # per-unit rather than only in the sum. A per-unit equality cannot be compensated
      # by another unit over-reporting, which is the shape a sum-only check misses.
      if [ "$unit_ran" != "1" ]; then
        [ -n "$failure" ] || \
          failure="${ids[index]} reported '${unit_ran:-no}' executed test(s), expected exactly 1"
        printf '    %s reported %s executed test(s), expected exactly 1\n' \
          "${ids[index]}" "${unit_ran:-no parseable count}"
      else
        executed=$((executed + unit_ran))
      fi
    done

    if [ -z "$failure" ] && { [ "$executed" -ne "$total" ] || [ "$dispatched" -ne "$total" ]; }; then
      failure="the schedule dropped work — dispatched $dispatched and executed $executed of $total enumerated tests"
    fi
  fi

  # Logged on the clean path too: a silent no-op is indistinguishable from a driver that
  # never ran, so the reader can always see how much of the file actually executed. The
  # bound clause is part of that same statement rather than a separate line: a bounded run
  # is a materially different claim from a full one, and a caller (or a human reading a
  # log) must not be able to see the tally without seeing that it was bounded.
  printf '  %s: executed %s test(s) across %s concurrent worker(s) (%s enumerated%s)\n' \
    "${script_path##*/}" "$executed" "$width" "${total:-unestablished}" "$bound_note"
  # On stdout, with the tally line above it and the per-unit captures below: the whole
  # report stays on one stream, which is the stream discipline _devflow_echo_capture's
  # header states and the reason a reader never sees a diagnosis detached from evidence.
  [ -z "$failure" ] || printf '    devflow shard driver: %s\n' "$failure"
  assert_eq "$assertion_name" "" "$failure"
}

_devflow_record_module_failure() {  # [identifier]
  if ! printf 'FAIL\n' >> "$MODULE_FAILURES_FILE"; then
    printf 'ERROR: could not record boundary failure in %s\n' \
      "$MODULE_FAILURES_FILE" >&2
    return 1
  fi
  # A boundary failure reaches the suite tally through MODULE_FAILURES_FILE, not through
  # RESULTS_FILE, so it bypasses the FAIL-site pairing record_fail is called at everywhere
  # else — and would have been counted-but-unnamed in the #789 recap. Record its identifier
  # here, at the single chokepoint every boundary failure passes through, so the pairing
  # holds for this channel by construction rather than by a per-caller edit. The optional
  # argument keeps every existing zero-argument call site valid: an omitted identifier
  # degrades to record_fail's own "(unnamed check)" placeholder, never to no bullet at all.
  record_fail "${1-module boundary failure}"
}

devflow_fold_module_failures() { # current-failure-count
  local current_failures="$1" invalid_count module_failures grep_rc

  case "$current_failures" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ -f "$MODULE_FAILURES_FILE" ] && [ -r "$MODULE_FAILURES_FILE" ] || return 1

  grep_rc=0
  invalid_count="$(grep -cv '^FAIL$' "$MODULE_FAILURES_FILE")" || grep_rc=$?
  [ "$grep_rc" -le 1 ] || return 1
  [ "$invalid_count" -eq 0 ] || return 1

  grep_rc=0
  module_failures="$(grep -c '^FAIL$' "$MODULE_FAILURES_FILE")" || grep_rc=$?
  [ "$grep_rc" -le 1 ] || return 1
  printf '%s\n' "$((current_failures + module_failures))"
}

_devflow_test_write_pid() { # path pid owner
  local path="$1" pid="$2" owner="$3"
  [ -n "$path" ] || return 0
  if ! printf '%s\n' "$pid" > "$path"; then
    printf 'devflow-test: could not record %s PID in %s\n' "$owner" "$path" >&2
    return 1
  fi
}

_devflow_test_ensure_cleanup_marker() { # path marker owner
  local path="$1" marker="$2" owner="$3" line
  [ -n "$path" ] || return 0
  if [ -f "$path" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      [ "$line" != "$marker" ] || return 0
    done < "$path"
  fi
  if ! printf '%s\n' "$marker" >> "$path"; then
    printf 'devflow-test: could not append %s cleanup marker to %s\n' \
      "$owner" "$path" >&2
    return 1
  fi
}

_devflow_test_append_cleanup_marker() { # path
  _devflow_test_ensure_cleanup_marker "$1" "runner-cleanup" "runner"
}

# devflow_module_build_bundle LABEL OUTPUT_FILE MEMBER...
#   Module-side skill-bundle builder (issue #746). Concatenates every MEMBER into
#   OUTPUT_FILE, one trailing newline per member, so a content-survival pin can
#   target the whole bundle rather than guessing which reference a sentence lives
#   in. Deliberately NOT a relocation of the monolith's `_build_skill_bundle`:
#   that one reports a bad member by writing `FAIL` straight into the caller's
#   `$RESULTS_FILE`, a raw-tally side effect a module must not perform. Here an
#   unusable member (missing, empty, unreadable, or a failed append) is reported
#   through `assert_eq`, the module contract's only sanctioned failure channel, so
#   the member's absence lands in the tally as a named RED assertion rather than
#   an anonymous one. Fails LOUD per member and keeps going, so one missing
#   reference does not mask the next; returns 1 when any member failed.
devflow_module_build_bundle() { # label output-file member...
  local label="$1" out="$2" member="" rc=0
  shift 2
  : > "$out" || {
    assert_eq "$label output file writable" "yes" "no"
    return 1
  }
  for member in "$@"; do
    if [ -r "$member" ] && [ -s "$member" ] && cat "$member" >> "$out"; then
      printf '\n' >> "$out"
    else
      # Named per member: a bare "bundle failed" cannot tell the reader WHICH
      # reference vanished, which is the whole diagnostic value of failing loud.
      assert_eq "$label member usable: $member" "usable" "missing-empty-or-unreadable"
      rc=1
    fi
  done
  return "$rc"
}

devflow_module_allocate_owned_directory() { # mktemp-template
  local template="$1" candidate="" candidate_physical="" existing=""
  local existing_physical=""
  local -a preexisting=()
  case "$template" in
    *XXXXXX) ;;
    *)
      printf 'devflow: invalid private-directory template: %s\n' "$template" >&2
      return 1
      ;;
  esac

  # Snapshot the template namespace before allocation. Standard mktemp creates
  # a fresh directory atomically; a shadowed or broken implementation must not
  # be allowed to hand cleanup a caller-owned directory that merely has the
  # expected name and parent.
  for existing in "${template%XXXXXX}"??????; do
    [ -d "$existing" ] && [ ! -L "$existing" ] || continue
    existing_physical="$(cd "$existing" 2>/dev/null && pwd -P)" || continue
    preexisting+=("$existing_physical")
  done

  candidate="$(mktemp -d "$template")" || return 1
  if [ -d "$candidate" ] && [ ! -L "$candidate" ]; then
    candidate_physical="$(cd "$candidate" 2>/dev/null && pwd -P)" || \
      candidate_physical=""
    for existing_physical in "${preexisting[@]}"; do
      if [ -n "$candidate_physical" ] && \
        [ "$candidate_physical" = "$existing_physical" ]; then
        printf 'devflow: allocator returned a pre-existing directory: %s\n' \
          "$candidate" >&2
        return 1
      fi
    done
  fi
  printf '%s\n' "$candidate"
}

_devflow_cleanup_module_scratch() { # scratch-root
  local scratch_root="$1"
  [ -n "$scratch_root" ] || return 0
  # This path is allocated by the boundary itself. Validate its generated leaf
  # before the recursive fallback so a corrupted variable cannot widen cleanup.
  case "${scratch_root##*/}" in
    devflow-module-scratch.??????) ;;
    *)
      printf 'devflow: refusing invalid module scratch root: %s\n' \
        "$scratch_root" >&2
      return 1
      ;;
  esac
  if { [ -e "$scratch_root" ] || [ -L "$scratch_root" ]; } && \
    ! rm -rf "$scratch_root"; then
    printf 'devflow: could not remove module scratch root: %s\n' \
      "$scratch_root" >&2
    return 1
  fi
  _devflow_test_ensure_cleanup_marker \
    "${DEVFLOW_TEST_MODULE_CLEANUP_MARKER:-}" "module-cleanup" "module" || return 1
}

_devflow_validate_module_scratch() { # scratch-root
  local scratch_root="$1" expected_parent actual_parent
  case "$scratch_root" in
    /*) ;;
    *) return 1 ;;
  esac
  case "${scratch_root##*/}" in
    devflow-module-scratch.??????) ;;
    *) return 1 ;;
  esac
  [ -d "$scratch_root" ] && [ ! -L "$scratch_root" ] || return 1
  expected_parent="$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)" || return 1
  actual_parent="$(cd "$scratch_root/.." 2>/dev/null && pwd -P)" || return 1
  [ "$actual_parent" = "$expected_parent" ]
}

_devflow_discard_unvalidated_owned_directory() { # path leaf-prefix expected-parent
  local path="$1" leaf_prefix="$2" expected_parent="$3"
  local expected_physical="" actual_physical=""
  [ -n "$path" ] || return 0
  case "${path##*/}" in
    "${leaf_prefix}"??????) ;;
    *) return 0 ;;
  esac
  [ -d "$path" ] && [ ! -L "$path" ] || return 0
  expected_physical="$(cd "$expected_parent" 2>/dev/null && pwd -P)" || return 0
  actual_physical="$(cd "$path/.." 2>/dev/null && pwd -P)" || return 0
  [ "$actual_physical" = "$expected_physical" ] || return 0
  if ! rmdir -- "$path"; then
    printf 'devflow: could not discard unsafe private directory: %s\n' \
      "$path" >&2
    return 1
  fi
}

_devflow_discard_unvalidated_module_scratch() { # scratch-root
  local scratch_root="$1"
  # A rejected allocator value is removed only when it still has the exact
  # generated leaf shape and physical parent. Invalid names and traversal-shaped
  # paths are left untouched because the boundary cannot prove ownership.
  _devflow_discard_unvalidated_owned_directory "$scratch_root" \
    "devflow-module-scratch." "${TMPDIR:-/tmp}"
}

_devflow_test_read_pid() { # path
  local path="$1" pid=""
  [ -n "$path" ] && [ -r "$path" ] || return 1
  IFS= read -r pid < "$path" || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  printf '%s\n' "$pid"
}

_devflow_terminate_process_group() { # signal leader-pid grace-seconds
  local signal_name="$1" leader_pid="$2" grace_seconds="$3"
  local watchdog_pid="" monitor_was_on=0 child_rc=0
  case "$leader_pid" in
    ''|*[!0-9]*) return 0 ;;
  esac

  kill -s "$signal_name" -- "-$leader_pid" 2>/dev/null || :
  case "$-" in
    *m*) monitor_was_on=1 ;;
    *) set -m ;;
  esac
  (
    trap '' HUP INT TERM
    sleep "$grace_seconds"
    kill -s KILL -- "-$leader_pid" 2>/dev/null || :
  ) &
  watchdog_pid=$!
  [ "$monitor_was_on" -eq 1 ] || set +m

  if wait "$leader_pid" 2>/dev/null; then
    child_rc=0
  else
    child_rc=$?
  fi
  # The watchdog has its own process group, so cancellation terminates it and
  # its foreground sleep before the watchdog leader is reaped.
  kill -s KILL -- "-$watchdog_pid" 2>/dev/null || :
  kill -s KILL "$watchdog_pid" 2>/dev/null || :
  wait "$watchdog_pid" 2>/dev/null || :
  return "$child_rc"
}

_devflow_module_supervisor_signal() { # signal
  local signal_name="$1" escalation_timer_pid="" escalation_watchdog_pid=""
  if [ "${worker_launching:-0}" -eq 1 ]; then
    worker_pending_signal="$signal_name"
    return 0
  fi
  trap '' HUP INT TERM
  if [ -n "${supervisor_pid:-}" ]; then
    # The supervisor, worker, and foreground helpers share this group. The
    # supervisor ignores the forwarded copy while the worker/module traps run.
    kill -s "$signal_name" -- "-$supervisor_pid" 2>/dev/null || :
  fi
  if [ -n "${worker_pid:-}" ]; then
    sleep 1 >/dev/null 2>&1 &
    escalation_timer_pid=$!
    (
      trap '' HUP INT TERM
      while kill -0 "$escalation_timer_pid" 2>/dev/null; do :; done
      kill -s KILL -- "-$supervisor_pid" 2>/dev/null || :
    ) >/dev/null 2>&1 &
    escalation_watchdog_pid=$!
    wait "$worker_pid" 2>/dev/null || :
    worker_pid=""
    kill -s KILL "$escalation_timer_pid" "$escalation_watchdog_pid" \
      2>/dev/null || :
    wait "$escalation_timer_pid" 2>/dev/null || :
    wait "$escalation_watchdog_pid" 2>/dev/null || :
  fi
  exit 1
}

# Run a module body behind a shell that remains responsive while the body is
# blocked in a foreground helper. The boundary's job control gives the
# supervisor a private module group; disabling nested job control keeps the
# worker and its helpers in that group for bounded forwarding and escalation.
_devflow_supervise_module() { # body-function supervisor-pid-file worker-pid-file
  local body_function="$1" supervisor_pid_file="$2" worker_pid_file="$3"
  local supervisor_pid=""
  local worker_pid="" worker_pending_signal="" worker_launching=1
  local monitor_was_on=0 worker_rc=0
  # Bound the supervisor-PID rendezvous by WALL-CLOCK time, not an iteration
  # count. The former cap of 300 attempts consumed ~3s of `sleep 0.01`, but each
  # iteration also forks twice (the $() poll subshell and the `sleep` process),
  # so the real wall-clock cost scaled with per-fork overhead: ~3.5s on Linux and
  # enough slower on macOS (where fork/exec is costlier) to exceed the harness
  # test's 5s ceiling even though the rendezvous still failed boundedly — a
  # desk-only RED for macOS contributors, green on Linux CI (issue #641). A time
  # budget makes the bound platform-independent: the loop stops within
  # rendezvous_deadline_seconds regardless of how many polls fit in that window.
  # SECONDS is a bash builtin timer that costs no per-poll fork; its integer-
  # second granularity means the deadline actually fires anywhere in
  # [rendezvous_deadline_seconds-1, rendezvous_deadline_seconds) after the reset,
  # depending on the sub-second phase of the SECONDS=0 assignment — bounded
  # either way. rendezvous_max_polls is a fail-closed backstop that guarantees
  # termination even if SECONDS never advances (a backward system-clock step —
  # e.g. an NTP correction — after the reset would otherwise hang the loop with
  # no timeout breadcrumb): it is set far above the polls a healthy clock fits in
  # the deadline (~300 at the 10ms cadence), so it never fires first in normal
  # operation and only bounds the clock-stall case. Callers MUST run the
  # supervisor in a backgrounded ( ) subshell (both production callers do —
  # module-harness.sh full-suite and run-module.sh focused) so the non-local
  # SECONDS=0 reset stays contained to the supervisor and has no caller-visible
  # effect; a `local SECONDS` cannot be used because that strips the special
  # timer attribute.
  local rendezvous_deadline_seconds=3 rendezvous_polls=0 rendezvous_max_polls=1000

  trap '_devflow_module_supervisor_signal HUP' HUP
  trap '_devflow_module_supervisor_signal INT' INT
  trap '_devflow_module_supervisor_signal TERM' TERM
  SECONDS=0
  while ! supervisor_pid="$(_devflow_test_read_pid "$supervisor_pid_file" 2>/dev/null)"; do
    rendezvous_polls=$((rendezvous_polls + 1))
    if [ "$SECONDS" -ge "$rendezvous_deadline_seconds" ] || \
      [ "$rendezvous_polls" -ge "$rendezvous_max_polls" ]; then
      printf 'devflow: module supervisor PID rendezvous timed out: %s\n' \
        "$supervisor_pid_file" >&2
      trap - HUP INT TERM
      return 1
    fi
    sleep 0.01
  done
  case "$-" in
    *m*) monitor_was_on=1 ;;
    *) : ;;
  esac
  # Launch the worker while nested job control is disabled. Otherwise a shell
  # with a controlling TTY assigns the worker a second PGID before its body can
  # run set +m, outside the supervisor group used for forwarding and escalation.
  set +m
  _devflow_module_worker_entry() {
    # The supervisor needs one worker process group containing both the shell
    # and every foreground helper it starts. Disable nested job control inside
    # the worker so those helpers do not split into untracked process groups.
    set +m
    "$body_function"
  }
  _devflow_module_worker_entry &
  worker_pid=$!
  worker_launching=0
  [ "$monitor_was_on" -eq 0 ] || set -m
  _devflow_test_write_pid "$worker_pid_file" "$worker_pid" "module worker" || :
  _devflow_test_write_pid "${DEVFLOW_TEST_MODULE_WORKER_PID_FILE:-}" \
    "$worker_pid" "module worker" || :
  if [ -n "$worker_pending_signal" ]; then
    _devflow_module_supervisor_signal "$worker_pending_signal"
  fi
  if wait "$worker_pid"; then
    worker_rc=0
  else
    worker_rc=$?
  fi
  worker_pid=""
  trap - HUP INT TERM
  return "$worker_rc"
}

_devflow_test_pause_before_pid_capture() { # state-file
  local state_file="$1"
  [ -n "$state_file" ] || return 0
  if ! printf 'launched\n' > "$state_file"; then
    printf 'devflow-test: could not publish launch-window state: %s\n' \
      "$state_file" >&2
    return 1
  fi
  while [ ! -e "$state_file.release" ]; do
    # The hook must not become a second launch barrier after the runner has
    # already captured a pending signal for immediate replay.
    if [ -n "${MODULE_PENDING_SIGNAL:-}" ] || \
      [ -n "${module_pending_signal:-}" ]; then
      return 0
    fi
  done
}

_devflow_cleanup_full_suite_tally() { # tally-path
  local tally_path="$1"
  [ -n "$tally_path" ] || return 0
  # The `.names` sibling is record_fail's identifier record for this tally (issue #789),
  # already folded into the parent's record by the caller; remove it with the tally it
  # belongs to rather than leaving it in TMPDIR. `rm -f` on an absent sibling is a no-op,
  # so a module that recorded no failure costs nothing here.
  if ! rm -f "$tally_path" "$tally_path.names"; then
    printf 'devflow: could not remove private module tally: %s\n' "$tally_path" >&2
    return 1
  fi
  _devflow_test_append_cleanup_marker \
    "${DEVFLOW_TEST_RUNNER_CLEANUP_MARKER:-}" || return 1
}

_devflow_restore_signal_traps() { # saved-hup saved-int saved-term
  local saved_hup="$1" saved_int="$2" saved_term="$3"
  trap - HUP INT TERM
  # `trap -p` produced these commands in this shell; evaluating that shell-owned
  # representation preserves the caller's exact quoting and action text.
  [ -z "$saved_hup" ] || eval "$saved_hup"
  [ -z "$saved_int" ] || eval "$saved_int"
  [ -z "$saved_term" ] || eval "$saved_term"
}

# ── Run-wide live-child registry (issue #720) ────────────────────────────────
# _devflow_full_suite_signal was once a single scalar child slot (module_pid +
# module_scratch_root + module_results_file locals), so one delivered signal
# terminated ONE process group. The bounded Python-suite pool keeps several
# children live at once — and keeps them live across a module boundary that
# installs its own copy of these same traps — so a single delivered signal must
# terminate EVERY live child's group before the handler exits. This registry is
# that run-wide set: both devflow_run_full_suite_module (a single-element set)
# and devflow_pool_open register their children here, and the shared handler
# forwards to every entry. Indexed pid list + associative scratch/tally maps,
# initialized at source time so `set -u` never trips on the first ${#...[@]}.
_DEVFLOW_LIVE_CHILD_PIDS=()
declare -A _DEVFLOW_LIVE_CHILD_SCRATCH=()
declare -A _DEVFLOW_LIVE_CHILD_TALLY=()
# Newline-separated private skip records per child (issue #838) — see
# _devflow_register_live_child's optional trailing arguments.
declare -A _DEVFLOW_LIVE_CHILD_SKIPRECS=()

# ── Bounded concurrent Python-suite pool state (issue #720) ───────────────────
# The pool opens at one call site (devflow_pool_open), stays open while the main
# shell runs the last module boundary and ~2000 lines of assertions, and joins at
# another (devflow_pool_join) — so its state is module-global, not call-local.
# _DEVFLOW_POOL_LAUNCHING / _DEVFLOW_POOL_PENDING_SIGNAL are the pool's launch-window guard,
# the sibling of devflow_run_full_suite_module's module_launching / pending slot.
_DEVFLOW_POOL_OPEN=0
_DEVFLOW_POOL_WIDTH=0
_DEVFLOW_POOL_LAUNCHING=0
_DEVFLOW_POOL_PENDING_SIGNAL=""
_DEVFLOW_POOL_SAVED_HUP=""
_DEVFLOW_POOL_SAVED_INT=""
_DEVFLOW_POOL_SAVED_TERM=""
_DEVFLOW_POOL_PENDING_NAMES=()
_DEVFLOW_POOL_PENDING_SCRIPTS=()
_DEVFLOW_POOL_PENDING_MODES=()
_DEVFLOW_POOL_INFLIGHT_PIDS=()
declare -A _DEVFLOW_POOL_PID_NAME=()
declare -A _DEVFLOW_POOL_PID_SCRIPT=()
declare -A _DEVFLOW_POOL_PID_MODE=()
declare -A _DEVFLOW_POOL_PID_SCRATCH=()
declare -A _DEVFLOW_POOL_PID_TALLY=()
declare -A _DEVFLOW_POOL_PID_OUTPUT=()
# Per self-tally suite (keyed by name): the PASS/FAIL line count it contributed to
# RESULTS_FILE, and its own `N passed, M failed` summary line — captured at reap so
# lib/test/run.sh can assert, positionally against that line, that a self-tally
# suite's whole assertion count reached RESULTS_FILE (issue #720; a uniformly
# dropped verdict is caught even though the width-1/width-N equality would agree).
declare -A _DEVFLOW_POOL_SELFTALLY_LINES=()
declare -A _DEVFLOW_POOL_SELFTALLY_SUMMARY=()

# The two trailing arguments are OPTIONAL and default empty, so the pooled call site's
# three-argument form is unchanged. They carry the issue-#838 private skip records, which
# have no cleanup helper of their own (unlike the scratch root and the result tally) and
# would otherwise be the only allocations the signal path leaks.
_devflow_register_live_child() { # pid scratch-root tally-file [skips-file] [credit-file]
  local pid="$1"
  _DEVFLOW_LIVE_CHILD_PIDS+=("$pid")
  _DEVFLOW_LIVE_CHILD_SCRATCH["$pid"]="$2"
  _DEVFLOW_LIVE_CHILD_TALLY["$pid"]="$3"
  _DEVFLOW_LIVE_CHILD_SKIPRECS["$pid"]="${4:-}"$'\n'"${5:-}"
}

_devflow_deregister_live_child() { # pid
  local pid="$1" p
  local -a keep=()
  # Rebuild the pid list without $pid. The [ -gt 0 ] guard keeps an empty
  # "${keep[@]}" expansion off bash 4.0–4.3's set -u trap (same discipline as
  # _suite_cleanup's own length guards in lib/test/run.sh).
  if [ "${#_DEVFLOW_LIVE_CHILD_PIDS[@]}" -gt 0 ]; then
    for p in "${_DEVFLOW_LIVE_CHILD_PIDS[@]}"; do
      [ "$p" = "$pid" ] || keep+=("$p")
    done
  fi
  if [ "${#keep[@]}" -gt 0 ]; then
    _DEVFLOW_LIVE_CHILD_PIDS=("${keep[@]}")
  else
    _DEVFLOW_LIVE_CHILD_PIDS=()
  fi
  unset '_DEVFLOW_LIVE_CHILD_SCRATCH[$pid]'
  unset '_DEVFLOW_LIVE_CHILD_TALLY[$pid]'
  unset '_DEVFLOW_LIVE_CHILD_SKIPRECS[$pid]'
}

_devflow_full_suite_signal() { # signal
  local signal_name="$1" pid scratch tally skiprecs skiprec
  # The launch-window guard now covers BOTH the single-module launch
  # (module_launching, a devflow_run_full_suite_module local) AND the pool launch
  # (_DEVFLOW_POOL_LAUNCHING, a global): a signal delivered mid-launch, before the
  # child pid is registered, is stashed for replay by whichever launcher is active
  # rather than lost. Writing both pending slots is harmless — each launcher reads
  # only its own.
  if [ "${module_launching:-0}" -eq 1 ] || [ "${_DEVFLOW_POOL_LAUNCHING:-0}" -eq 1 ]; then
    module_pending_signal="$signal_name"
    _DEVFLOW_POOL_PENDING_SIGNAL="$signal_name"
    return 0
  fi
  # Ignore a second delivery while forwarding, boundedly reaping, and cleaning.
  trap '' HUP INT TERM
  # Forward to every live child's process group and clean its scratch/tally. This
  # single loop subsumes the former single module_pid slot (registered as a
  # one-element set by devflow_run_full_suite_module) and every pooled child.
  if [ "${#_DEVFLOW_LIVE_CHILD_PIDS[@]}" -gt 0 ]; then
    for pid in "${_DEVFLOW_LIVE_CHILD_PIDS[@]}"; do
      [ -n "$pid" ] || continue
      _devflow_terminate_process_group "$signal_name" "$pid" 3 || :
      scratch="${_DEVFLOW_LIVE_CHILD_SCRATCH[$pid]:-}"
      tally="${_DEVFLOW_LIVE_CHILD_TALLY[$pid]:-}"
      [ -z "$scratch" ] || _devflow_cleanup_module_scratch "$scratch" || :
      [ -z "$tally" ] || _devflow_cleanup_full_suite_tally "$tally" || :
      # The issue-#838 private skip records have no cleanup helper of their own, so they
      # are removed here directly. Read line by line (a bash builtin) rather than by word
      # splitting, so a TMPDIR containing spaces cannot turn one path into two.
      skiprecs="${_DEVFLOW_LIVE_CHILD_SKIPRECS[$pid]:-}"
      while IFS= read -r skiprec; do
        [ -n "$skiprec" ] || continue
        rm -f "$skiprec" || :
      done <<< "$skiprecs"
    done
    _DEVFLOW_LIVE_CHILD_PIDS=()
  fi
  # The boundary owns only these temporary signal traps. Leave the caller's EXIT
  # trap installed so its top-level registry cleanup still runs on this exit.
  exit 1
}

# Return contract: rc 0 means the boundary HANDLED the module (including a
# failing module — the failure is recorded in MODULE_FAILURES_FILE); rc 1 means
# the boundary-failure channel itself is unusable and the caller must abort.
# rc 0 is NOT "module passed" — always fold MODULE_FAILURES_FILE afterwards.
devflow_run_full_suite_module() { # module-path module-name minimum-assertions
  local module_path="$1" module_name="$2" minimum_assertions="$3"
  local module_results_file="" module_scratch_root="" module_group_pid_file=""
  local module_worker_pid_file=""
  local module_skips_file="" module_skip_credit_file=""
  local skip_credit_total=0 effective_minimum=0 skip_records_lost=0 credited_clause=""
  local _fold_line="" _credit_line="" _fold_rest="" _fold_name="" _fold_reason=""
  local module_pid="" module_rc=0 assertion_count=0 boundary_rc=0
  local module_launching=0 module_pending_signal="" tally_valid=1
  local saved_hup saved_int saved_term monitor_was_on=0

  # Module-tier selector for the concurrent CI job matrix (issue #877). When
  # DEVFLOW_SKIP_SUITE_MODULES=1 the full-suite runner delegates the whole module
  # tier to separate shard jobs (each invoking `run-module.sh <id>` for its group),
  # so the monolith shard runs run.sh's inline assertions WITHOUT the modules and
  # nothing is double-counted across shards. The dedup is what turns the split into
  # a wall-clock win; without it the monolith shard would re-run every module.
  # An early return records nothing (no result, no boundary failure, no skip credit),
  # so the tail's grep -c derivations and devflow_fold_module_failures stay clean —
  # the module's assertions and its minimum_assertions floor are enforced instead in
  # its own shard by run-module.sh. Unset/any-other value is byte-identical to before
  # (the full suite runs every module), so a plain `bash lib/test/run.sh` is unchanged.
  if [ "${DEVFLOW_SKIP_SUITE_MODULES:-}" = 1 ]; then
    return 0
  fi

  case "$minimum_assertions" in
    ''|*[!0-9]*|????????*)
      _devflow_record_module_failure "test module $module_name — invalid minimum assertion count" || return 1
      printf '  FAIL  test module %s — invalid minimum assertion count: %s\n' \
        "$module_name" "$minimum_assertions" >&2
      return 0
      ;;
  esac
  if [ "$minimum_assertions" -lt 1 ] || [ "$minimum_assertions" -gt 1000000 ]; then
    _devflow_record_module_failure "test module $module_name — invalid minimum assertion count" || return 1
    printf '  FAIL  test module %s — invalid minimum assertion count: %s\n' \
      "$module_name" "$minimum_assertions" >&2
    return 0
  fi

  if ! _devflow_valid_result_count >/dev/null; then
    _devflow_record_module_failure "test module $module_name — result tally unreadable before module execution" || return 1
    printf '  FAIL  test module %s — result tally unreadable before module execution\n' "$module_name" >&2
    return 0
  fi

  if [ ! -f "$module_path" ] || [ ! -r "$module_path" ]; then
    _devflow_record_module_failure "test module $module_name — missing or unreadable" || return 1
    printf '  FAIL  test module %s — missing or unreadable: %s\n' "$module_name" "$module_path" >&2
    return 0
  fi

  if ! module_results_file="$(mktemp "${TMPDIR:-/tmp}/devflow-module-tally.XXXXXX")"; then
    _devflow_record_module_failure "test module $module_name — could not allocate private result tally" || return 1
    printf '  FAIL  test module %s — could not allocate private result tally\n' \
      "$module_name" >&2
    return 0
  fi
  # The module's PRIVATE skip tally and its declared assertion credits (issue #838).
  # Allocated in the parent so the `(...)` subshell below inherits the paths by closure,
  # exactly as module_results_file is — no new IPC mechanism, and the fold after `wait`
  # mirrors the `.names` fold. Allocation failure fails closed like the result tally's.
  if ! module_skips_file="$(mktemp "${TMPDIR:-/tmp}/devflow-module-skips.XXXXXX")"; then
    _devflow_cleanup_full_suite_tally "$module_results_file" || :
    _devflow_record_module_failure "test module $module_name — could not allocate private skip tally" || return 1
    printf '  FAIL  test module %s — could not allocate private skip tally\n' \
      "$module_name" >&2
    return 0
  fi
  if ! module_skip_credit_file="$(mktemp "${TMPDIR:-/tmp}/devflow-module-credits.XXXXXX")"; then
    rm -f "$module_skips_file" || :
    _devflow_cleanup_full_suite_tally "$module_results_file" || :
    _devflow_record_module_failure "test module $module_name — could not allocate private skip-credit record" || return 1
    printf '  FAIL  test module %s — could not allocate private skip-credit record\n' \
      "$module_name" >&2
    return 0
  fi
  if ! module_scratch_root="$(devflow_module_allocate_owned_directory \
    "${TMPDIR:-/tmp}/devflow-module-scratch.XXXXXX")"; then
    rm -f "$module_skips_file" "$module_skip_credit_file" || :
    _devflow_cleanup_full_suite_tally "$module_results_file" || :
    _devflow_record_module_failure "test module $module_name — could not allocate private scratch root" || return 1
    printf '  FAIL  test module %s — could not allocate private scratch root\n' \
      "$module_name" >&2
    return 0
  fi
  if ! _devflow_validate_module_scratch "$module_scratch_root"; then
    _devflow_discard_unvalidated_module_scratch "$module_scratch_root" || :
    module_scratch_root=""
    rm -f "$module_skips_file" "$module_skip_credit_file" || :
    _devflow_cleanup_full_suite_tally "$module_results_file" || :
    _devflow_record_module_failure "test module $module_name — allocated an unsafe private scratch root" || return 1
    printf '  FAIL  test module %s — allocated an unsafe private scratch root\n' \
      "$module_name" >&2
    return 0
  fi
  module_group_pid_file="$module_scratch_root/supervisor.pid"
  module_worker_pid_file="$module_scratch_root/worker.pid"

  saved_hup="$(trap -p HUP)"
  saved_int="$(trap -p INT)"
  saved_term="$(trap -p TERM)"
  trap '_devflow_full_suite_signal HUP' HUP
  trap '_devflow_full_suite_signal INT' INT
  trap '_devflow_full_suite_signal TERM' TERM
  _devflow_test_write_pid "${DEVFLOW_TEST_RUNNER_PID_FILE:-}" "$$" \
    "full-suite runner" || :

  case "$-" in
    *m*) monitor_was_on=1 ;;
    *) set -m ;;
  esac
  module_launching=1
  (
    # Consumed by the sourced module in the worker.
    # shellcheck disable=SC2034
    DEVFLOW_MODULE_OWNED_SCRATCH_ROOT="$module_scratch_root"
    # Nest every module's ordinary TMPDIR allocations below the boundary root,
    # including modules that do not consume the DevFlow-specific ownership hint.
    TMPDIR="$module_scratch_root"
    export TMPDIR
    # Invoked indirectly by the supervisor helper.
    # shellcheck disable=SC2329
    _devflow_full_suite_module_body() {
      # Keep the full-suite boundary's fail direction identical to the focused
      # runner even when a future caller does not enable nounset globally.
      set -u
      # The module receives RESULTS_FILE by contract, and — since issue #838 — a
      # PRIVATE skip tally plus a private skip-credit record, never the independent
      # boundary-failure channel or the shared suite tallies. The skip binding is
      # private for the same reason the result tally is: the parent validates and
      # folds it after `wait`, so a module cannot write the shared tally directly and
      # cannot launder a `blocking-gate` skip into it.
      # The private worker intentionally shadows the caller tally.
      # shellcheck disable=SC2030
      RESULTS_FILE="$module_results_file"
      # shellcheck disable=SC2030
      SKIPS_FILE="$module_skips_file"
      # Consumed by module_host_capability_skip in the sourced module.
      # shellcheck disable=SC2034,SC2030
      MODULE_SKIP_CREDIT_FILE="$module_skip_credit_file"
      # Heavy-unit population (issue #890). When the full suite runs a module at all — it
      # does not under DEVFLOW_SKIP_SUITE_MODULES=1, the monolith CI shard's selector — it
      # always runs the full population, and this is an unconditional assignment rather
      # than an environment-derived default so an inherited MODULE_HEAVY_UNIT_MODE cannot
      # shrink what the suite executes. The focused runner's --heavy-units flag is the only
      # thing that ever selects `smoke`.
      # shellcheck disable=SC2034,SC2030
      MODULE_HEAVY_UNIT_MODE=full
      unset MODULE_FAILURES_FILE
      # shellcheck source=/dev/null disable=SC1090
      . "$module_path"
    }
    _devflow_supervise_module _devflow_full_suite_module_body \
      "$module_group_pid_file" "$module_worker_pid_file"
  ) &
  _devflow_test_pause_before_pid_capture \
    "${DEVFLOW_TEST_LAUNCH_WINDOW_FILE:-}" || :
  module_pid=$!
  _devflow_test_write_pid "$module_group_pid_file" "$module_pid" \
    "module supervisor" || :
  # Register this single child in the run-wide registry (a one-element set) so the
  # generalized signal handler forwards to it exactly as it did through the former
  # module_pid scalar slot (issue #720). Registered after the pid is known so a
  # signal that arrives before this point is caught by the module_launching guard.
  _devflow_register_live_child "$module_pid" "$module_scratch_root" \
    "$module_results_file" "$module_skips_file" "$module_skip_credit_file"
  module_launching=0
  [ "$monitor_was_on" -eq 1 ] || set +m
  _devflow_test_write_pid "${DEVFLOW_TEST_MODULE_PID_FILE:-}" "$module_pid" \
    "full-suite module" || :
  if [ -n "$module_pending_signal" ]; then
    _devflow_full_suite_signal "$module_pending_signal"
  fi
  if wait "$module_pid"; then
    module_rc=0
  else
    module_rc=$?
  fi
  # Deregister on the no-signal path: the child is reaped, so a late signal must
  # not try to terminate its (now-recycled) pid or double-clean its scratch/tally
  # (the normal cleanup below owns that). The signal path never reaches here — it
  # exit 1s the whole runner after cleaning every registered child.
  _devflow_deregister_live_child "$module_pid"
  module_pid=""

  if ! assertion_count="$(_devflow_valid_result_count "$module_results_file")"; then
    tally_valid=0
    _devflow_record_module_failure "test module $module_name — result tally unreadable after module execution" || boundary_rc=1
    printf '  FAIL  test module %s — result tally unreadable after module execution\n' "$module_name" >&2
  fi

  # This is the caller tally, not the worker shadow.
  # shellcheck disable=SC2031
  if [ "$tally_valid" -eq 1 ] && ! cat "$module_results_file" >> "$RESULTS_FILE"; then
    _devflow_record_module_failure "test module $module_name — could not append private result tally" || boundary_rc=1
    printf '  FAIL  test module %s — could not append private result tally\n' \
      "$module_name" >&2
  fi
  # Fold the worker's IDENTIFIER record (issue #789) beside its verdict tally. The worker
  # rebinds RESULTS_FILE to its private tally, and record_fail derives its path from that
  # binding — so a module assertion's identifier lands in "$module_results_file.names",
  # which nothing read until this fold. Without it the recap counts every module failure
  # and names none of them: the largest population in the suite would reach the reader only
  # as the renderer's unnamed-shortfall line. Guarded on non-empty because a module with no
  # failures writes no sibling at all, and `cat` of a missing file is an error, not a no-op.
  if [ -s "$module_results_file.names" ] && ! cat "$module_results_file.names" >> "$RESULTS_FILE.names"; then
    _devflow_record_module_failure "test module $module_name — could not append private failure-identifier record" || boundary_rc=1
    printf '  FAIL  test module %s — could not append private failure-identifier record\n' \
      "$module_name" >&2
  fi
  # ── Fold the worker's PRIVATE skip tally (issue #838) ────────────────────────
  # Read line by line with bash builtins rather than grep/awk: this loop decides both
  # an EMITTED result (which skips reach the shared tally) and a SELECTION (the floor
  # the assertion count is compared against), and CLAUDE.md guard-class 2 bars deriving
  # either through a tool the preflight does not guarantee — an absent tool would empty
  # the stream and silently grant a clean pass.
  #
  # Only `host-capability` is folded — this arm is the validator the wrapper's contract
  # defers to, so a module reaching past the wrapper to record a `blocking-gate` skip is
  # rejected here instead of laundering a gate it skipped for itself.
  # `-s` distinguishes "no skips recorded" (the overwhelmingly common case, and a clean
  # no-op) from a file that exists with content. A file that is non-empty but UNREADABLE
  # is neither: the redirect below fails, the loop body never runs, and the skips and
  # their credits would vanish silently — so the readability of each record is checked
  # before it is consumed, rather than inferred from the existence check.
  if [ -s "$module_skips_file" ] && [ ! -r "$module_skips_file" ]; then
    _devflow_record_module_failure "test module $module_name — private skip tally is unreadable" || boundary_rc=1
    printf '  FAIL  test module %s — private skip tally is unreadable\n' "$module_name" >&2
    # The credit half of the record is only legitimate BECAUSE the skip half is visible:
    # crediting the floor while the skips themselves never reached the tally is exactly
    # the laundering this channel exists to prevent (fewer assertions, no skip shown, no
    # floor trip — a clean-looking run). Forfeit every credit when the skips are lost.
    skip_records_lost=1
  elif [ -s "$module_skips_file" ]; then
    while IFS= read -r _fold_line || [ -n "$_fold_line" ]; do
      [ -n "$_fold_line" ] || continue
      case "$_fold_line" in
        "host-capability"$'\t'*)
          # Re-impose skip()'s field shape rather than re-appending the line verbatim.
          # Binding the child a real SKIPS_FILE means skip() is no longer the only writer,
          # so the "exactly three TAB-separated fields" invariant it maintained by
          # construction now has a second, unsanitized producer — and lib/test/summary.sh
          # field-splits each line on TAB, so an extra TAB would render a skip's fields
          # transposed and an embedded CR would ride into the summary. Splitting and
          # re-emitting keeps that shape a property of the fold, not of the writer's
          # goodwill. A newline cannot appear inside a line `read` returned, so only TAB
          # and CR need collapsing. All bash builtins (guard-class 2).
          _fold_rest="${_fold_line#host-capability$'\t'}"
          _fold_name="${_fold_rest%%$'\t'*}"
          if [ "$_fold_rest" = "$_fold_name" ]; then
            _fold_reason=""
          else
            _fold_reason="${_fold_rest#*$'\t'}"
          fi
          if ! printf 'host-capability\t%s\t%s\n' \
            "${_fold_name//[$'\t'$'\r']/ }" "${_fold_reason//[$'\t'$'\r']/ }" \
            >> "$SKIPS_FILE"; then
            _devflow_record_module_failure "test module $module_name — could not append private skip tally" || boundary_rc=1
            printf '  FAIL  test module %s — could not append private skip tally\n' \
              "$module_name" >&2
            # A skip that never reached the shared tally forfeits every credit, exactly as
            # the unreadable-record arm above does and for the same reason: crediting the
            # floor while the skip itself is invisible is the laundering this channel
            # exists to prevent. The append arm lost the skip the same way, so it must
            # reach the same verdict.
            skip_records_lost=1
          fi
          ;;
        *)
          _devflow_record_module_failure "test module $module_name — recorded a non-host-capability skip (a module may not self-skip)" || boundary_rc=1
          printf '  FAIL  test module %s — recorded a non-host-capability skip (a module may not self-skip): %s\n' \
            "$module_name" "$_fold_line" >&2
          ;;
      esac
    done < "$module_skips_file"
  fi

  # Sum the declared assertion credits. A credit is a DECLARATION the module makes about
  # how many assertions its gated arm did not run; every NON-BLANK shape this cannot use
  # grants ZERO and records an attributable failure, so a malformed declaration can never
  # buy floor relief. (A blank line is not a declaration at all: it is skipped, granting
  # zero and recording nothing — the one shape that grants nothing without a failure.)
  # Arithmetic stays in bash builtins for the same guard-class-2 reason.
  # The `-s`/`-r` pair is the same check the skip tally above uses, for the reason stated
  # there: an unreadable record must not read as "nothing was recorded".
  if [ -s "$module_skip_credit_file" ] && [ ! -r "$module_skip_credit_file" ]; then
    _devflow_record_module_failure "test module $module_name — private skip-credit record is unreadable" || boundary_rc=1
    printf '  FAIL  test module %s — private skip-credit record is unreadable\n' "$module_name" >&2
  elif [ -s "$module_skip_credit_file" ]; then
    while IFS= read -r _credit_line || [ -n "$_credit_line" ]; do
      [ -n "$_credit_line" ] || continue
      case "$_credit_line" in
        # Digits only, and short enough that the arithmetic below cannot overflow —
        # the same bounded-digit shape the minimum-assertions validation above uses.
        ''|*[!0-9]*|????????*)
          _devflow_record_module_failure "test module $module_name — malformed skip-assertion credit" || boundary_rc=1
          printf '  FAIL  test module %s — malformed skip-assertion credit: %s\n' \
            "$module_name" "$_credit_line" >&2
          ;;
        # `10#` forces base 10: a leading-zero shape (010, 08) is a decimal credit,
        # never an octal reinterpretation or a "value too great for base" abort.
        *) skip_credit_total=$((skip_credit_total + 10#$_credit_line)) ;;
      esac
    done < "$module_skip_credit_file"
  fi

  # A credit that meets or exceeds the floor would leave nothing for the floor to
  # assert, so it is rejected and the RAW minimum stands — fail closed toward the
  # stricter bound, never the permissive one.
  # A lost skip record forfeits every credit (see the unreadable arm above), so the
  # raw floor stands and the shortfall is reported rather than credited away.
  if [ "$skip_records_lost" -ne 0 ]; then
    skip_credit_total=0
  elif [ "$skip_credit_total" -ge "$minimum_assertions" ]; then
    _devflow_record_module_failure "test module $module_name — skip-assertion credit $skip_credit_total meets or exceeds the assertion floor $minimum_assertions" || boundary_rc=1
    printf '  FAIL  test module %s — skip-assertion credit %s meets or exceeds the assertion floor %s\n' \
      "$module_name" "$skip_credit_total" "$minimum_assertions" >&2
    skip_credit_total=0
  fi
  effective_minimum=$((minimum_assertions - skip_credit_total))

  if ! rm -f "$module_skips_file" "$module_skip_credit_file"; then
    _devflow_record_module_failure "test module $module_name — could not remove private skip records" || boundary_rc=1
    printf '  FAIL  test module %s — could not remove private skip records\n' \
      "$module_name" >&2
  fi
  module_skips_file=""
  module_skip_credit_file=""

  if ! _devflow_cleanup_module_scratch "$module_scratch_root"; then
    _devflow_record_module_failure "test module $module_name — could not remove private scratch root" || boundary_rc=1
    printf '  FAIL  test module %s — could not remove private scratch root\n' \
      "$module_name" >&2
  fi
  module_scratch_root=""
  if ! _devflow_cleanup_full_suite_tally "$module_results_file"; then
    _devflow_record_module_failure "test module $module_name — could not remove private result tally" || boundary_rc=1
    printf '  FAIL  test module %s — could not remove private result tally\n' \
      "$module_name" >&2
  fi
  module_results_file=""

  if [ "$module_rc" -ne 0 ]; then
    _devflow_record_module_failure "test module $module_name — exited with status $module_rc" || boundary_rc=1
    printf '  FAIL  test module %s — exited with status %s\n' "$module_name" "$module_rc" >&2
  fi
  if [ "$tally_valid" -eq 1 ] && [ "$assertion_count" -eq 0 ]; then
    _devflow_record_module_failure "test module $module_name — executed zero assertions" || boundary_rc=1
    printf '  FAIL  test module %s — executed zero assertions\n' "$module_name" >&2
  elif [ "$tally_valid" -eq 1 ] && [ "$assertion_count" -lt "$effective_minimum" ]; then
    # The floor is compared against the effective minimum so a host that could not
    # express a gated arm's condition reports its visible skip rather than a count
    # mismatch that reads like a regression. The credited clause is appended only when a
    # credit was actually granted, so an uncredited run's message stays byte-identical to
    # the pre-#838 text while a credited run's reader sees both bounds.
    credited_clause=""
    [ "$skip_credit_total" -gt 0 ] &&
      credited_clause=" (effective $effective_minimum after $skip_credit_total credited skip assertions)"
    _devflow_record_module_failure "test module $module_name — executed $assertion_count assertions; minimum is $minimum_assertions$credited_clause" || boundary_rc=1
    printf '  FAIL  test module %s — executed %s assertions; minimum is %s%s\n' \
      "$module_name" "$assertion_count" "$minimum_assertions" "$credited_clause" >&2
  fi
  # Keep the boundary traps installed through both cleanup attempts and their
  # associated failure recording.
  _devflow_restore_signal_traps "$saved_hup" "$saved_int" "$saved_term"
  return "$boundary_rc"
}

# ── Bounded concurrent Python-suite pool (issue #720) ─────────────────────────
# A generalization of devflow_run_full_suite_module from one child to a bounded
# set: it reuses that function's scratch/tally/trap-restore machinery and the same
# _devflow_supervise_module process-group launch, but keeps several suites live at
# once behind a width limit. It is opened at one call site and joined at another
# so the long pole overlaps the module boundary and the shell tail; it installs NO
# EXIT trap of its own (lib/test/run.sh's single `trap _suite_cleanup EXIT` stays
# the sole EXIT handler) and cleans every temporary it creates on its own path.
#
# Membership modes:
#   single-verdict  — the suite reports one exit status; the pool writes exactly
#                     one PASS/FAIL line to its private tally from that status
#                     (mirrors devflow_run_focused_python_test's assert_eq name 0 rc).
#   self-tally      — the suite emits one PASS/FAIL per assertion itself, into the
#                     tally path the pool exports as DEVFLOW_POOL_TALLY_FILE.
#
# Width override: the single named environment variable DEVFLOW_POOL_WIDTH takes
# precedence over the cpu_count probe when it is a positive integer; otherwise the
# width is min(os.cpu_count(), 4), falling back to 1 when that probe yields no
# positive integer. Because the cap decides a selection, it is derived through the
# preflight-guaranteed python3 (never a non-preflight PATH tool — CLAUDE.md
# guard-class 2) and a non-positive-integer probe fails closed to width 1.
_devflow_pool_resolve_width() {
  local override="${DEVFLOW_POOL_WIDTH:-}" probe
  case "$override" in
    ''|*[!0-9]*) : ;;
    *) if [ "$override" -ge 1 ]; then printf '%s\n' "$override"; return 0; fi ;;
  esac
  # DEVFLOW_TEST_POOL_CPU_PROBE substitutes the probe's OUTPUT (not a different
  # command) so a test can exercise the empty / 0 / non-numeric fallback arms;
  # +x honors an explicitly-empty injected value.
  if [ -n "${DEVFLOW_TEST_POOL_CPU_PROBE+x}" ]; then
    probe="$DEVFLOW_TEST_POOL_CPU_PROBE"
  else
    probe="$(python3 -c 'import os; print(min(os.cpu_count() or 1, 4))' 2>/dev/null)" || probe=""
  fi
  case "$probe" in
    ''|*[!0-9]*) printf '1\n'; return 0 ;;
  esac
  [ "$probe" -ge 1 ] && printf '%s\n' "$probe" || printf '1\n'
}

_devflow_pool_pending_shift() {
  local -a n=() s=() m=() ; local i
  if [ "${#_DEVFLOW_POOL_PENDING_NAMES[@]}" -gt 1 ]; then
    for ((i=1; i<${#_DEVFLOW_POOL_PENDING_NAMES[@]}; i++)); do
      n+=("${_DEVFLOW_POOL_PENDING_NAMES[$i]}")
      s+=("${_DEVFLOW_POOL_PENDING_SCRIPTS[$i]}")
      m+=("${_DEVFLOW_POOL_PENDING_MODES[$i]}")
    done
  fi
  if [ "${#n[@]}" -gt 0 ]; then
    _DEVFLOW_POOL_PENDING_NAMES=("${n[@]}"); _DEVFLOW_POOL_PENDING_SCRIPTS=("${s[@]}"); _DEVFLOW_POOL_PENDING_MODES=("${m[@]}")
  else
    _DEVFLOW_POOL_PENDING_NAMES=(); _DEVFLOW_POOL_PENDING_SCRIPTS=(); _DEVFLOW_POOL_PENDING_MODES=()
  fi
}

_devflow_pool_inflight_remove() { # pid
  local pid="$1" p ; local -a keep=()
  if [ "${#_DEVFLOW_POOL_INFLIGHT_PIDS[@]}" -gt 0 ]; then
    for p in "${_DEVFLOW_POOL_INFLIGHT_PIDS[@]}"; do
      [ "$p" = "$pid" ] || keep+=("$p")
    done
  fi
  if [ "${#keep[@]}" -gt 0 ]; then
    _DEVFLOW_POOL_INFLIGHT_PIDS=("${keep[@]}")
  else
    _DEVFLOW_POOL_INFLIGHT_PIDS=()
  fi
}

_devflow_pool_output_has_rendezvous_timeout() { # output-file
  local f="$1" line
  [ -n "$f" ] && [ -r "$f" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *"module supervisor PID rendezvous timed out"*) return 0 ;;
    esac
  done < "$f"
  return 1
}

# The per-suite worker body: run the suite and record its verdict(s) into the
# private tally. Runs inside the supervised worker (single-verdict) or directly
# (serial retry). Fails CLOSED: a non-zero exit always yields at least one FAIL
# line, even for a self-tally suite that crashed mid-run after recording only
# PASS lines (a nonzero exit with no FAIL recorded would otherwise mask the crash).
_devflow_pool_run_one() { # name script mode tally
  local name="$1" script="$2" mode="$3" tally="$4" rc _hasfail=0 _l
  case "$mode" in
    self-tally)
      DEVFLOW_POOL_TALLY_FILE="$tally" PYTHON_COLORS=0 python3 "$script"
      rc=$?
      if [ "$rc" -ne 0 ]; then
        while IFS= read -r _l || [ -n "$_l" ]; do
          [ "$_l" = "FAIL" ] && { _hasfail=1; break; }
        done < "$tally" 2>/dev/null
        # Self-tally backstop: the worker exited non-zero but recorded no FAIL of its own.
        # The identifier goes to the SAME sibling the fold below reads, so this parent-written
        # verdict is named like a worker-written one (issue #789) — the tally and the record
        # must always be written as a pair, whichever side writes them.
        [ "$_hasfail" -eq 1 ] || { printf 'FAIL\n' >> "$tally"; printf '%s\n' "pool suite $name — worker exited $rc with no verdict recorded" >> "$tally.names"; }
      fi
      ;;
    *)
      PYTHON_COLORS=0 python3 "$script"
      rc=$?
      # single-verdict mode: the parent writes the suite's one verdict. A FAIL owes an
      # identifier in the sibling the fold reads, same pairing rule as everywhere else.
      if [ "$rc" -eq 0 ]; then printf 'PASS\n' >> "$tally"; else printf 'FAIL\n' >> "$tally"; printf '%s\n' "pool suite $name — exited $rc" >> "$tally.names"; fi
      ;;
  esac
  return "$rc"
}

# Serial fallback for a suite whose supervisor PID rendezvous timed out under pool
# saturation (issue #720 AC): re-run it directly with no supervisor and no process
# group, so a transient rendezvous timeout is absorbed rather than recorded as a
# suite failure. Writes verdict(s) to the same private tally, and its combined stdout
# to the caller-provided OUTPUT path so the reap's self-tally summary capture still
# sees the suite's `N passed, M failed` line after a retry (issue #720 review — a
# retried self-tally suite would otherwise lose its summary and the run.sh coverage
# cross-check would inject a spurious FAIL). The reap prints OUTPUT on failure, so this
# does not print it itself.
_devflow_pool_run_serial() { # name script mode tally output
  local name="$1" script="$2" mode="$3" tally="$4" out="$5" rc
  [ -n "$out" ] || out=/dev/null
  # Test hook: record that the serial-retry path ACTUALLY executed, so a forced-timeout
  # test asserts the retry ran rather than passing vacuously when the timeout was never
  # triggered/detected (issue #720 review).
  [ -z "${DEVFLOW_TEST_POOL_RETRY_MARKER:-}" ] || \
    printf '%s\n' "$name" >> "$DEVFLOW_TEST_POOL_RETRY_MARKER" 2>/dev/null || :
  ( _devflow_pool_run_one "$name" "$script" "$mode" "$tally" ) > "$out" 2>&1
  rc=$?
  return "$rc"
}

_devflow_pool_launch_suite() { # name script mode attempt
  local name="$1" script="$2" mode="$3" attempt="$4"
  local tally scratch output group_pid_file worker_pid_file monitor_was_on=0 pid
  if ! tally="$(mktemp "${TMPDIR:-/tmp}/devflow-pool-tally.XXXXXX")"; then
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — could not allocate private tally\n' "$name" >&2
    record_fail "pool suite $name — could not allocate private tally"
    return 0
  fi
  # A failed output-capture mktemp falls back to /dev/null, which for a self-tally suite
  # means its `N passed, M failed` summary is never captured — the reap then records a
  # "#720 ... could not capture its summary line" FAIL that reads like a capture-logic
  # bug rather than the real cause (output tempfile allocation failed under TMPDIR
  # exhaustion/quota). Breadcrumb the real cause so that eventual FAIL is actionable
  # (best-effort: continue with /dev/null; the FAIL is fail-closed over-reporting).
  if ! output="$(mktemp "${TMPDIR:-/tmp}/devflow-pool-out.XXXXXX")"; then
    output=/dev/null
    printf 'devflow-pool: suite %s — output-capture tempfile allocation failed (TMPDIR full/quota?); a self-tally summary will be uncapturable and recorded as a FAIL downstream\n' "$name" >&2
  fi
  if ! scratch="$(devflow_module_allocate_owned_directory \
    "${TMPDIR:-/tmp}/devflow-module-scratch.XXXXXX")"; then
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — could not allocate private scratch root\n' "$name" >&2
    record_fail "pool suite $name — could not allocate private scratch root"
    rm -f "$tally"; [ "$output" = /dev/null ] || rm -f "$output"
    return 0
  fi
  if ! _devflow_validate_module_scratch "$scratch"; then
    _devflow_discard_unvalidated_module_scratch "$scratch" || :
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — allocated an unsafe private scratch root\n' "$name" >&2
    record_fail "pool suite $name — allocated an unsafe private scratch root"
    rm -f "$tally"; [ "$output" = /dev/null ] || rm -f "$output"
    return 0
  fi
  group_pid_file="$scratch/supervisor.pid"
  worker_pid_file="$scratch/worker.pid"

  case "$-" in
    *m*) monitor_was_on=1 ;;
    *) set -m ;;
  esac
  _DEVFLOW_POOL_LAUNCHING=1
  (
    # Each pooled suite gets its own TMPDIR pointed at its private scratch root, so
    # every mktemp-derived temporary it (or a run-module.sh it drives) allocates is
    # isolated from the other pooled suites and from the main shell.
    TMPDIR="$scratch"
    export TMPDIR
    # Deliberately do NOT export DEVFLOW_MODULE_OWNED_SCRATCH_ROOT here (unlike
    # devflow_run_full_suite_module, which does so for the sourced shell MODULE it
    # runs): a pooled member is a standalone python3 suite that never consumes that
    # hint, and test_module_runner.py in particular EXERCISES the harness code keyed
    # on it — an inherited value would point that code at the suite's own live TMPDIR
    # and its cleanup would delete the scratch out from under the running suite
    # (issue #720). Unset any inherited value so a nested harness the suite drives
    # never sees a stale one.
    unset DEVFLOW_MODULE_OWNED_SCRATCH_ROOT
    # shellcheck disable=SC2329
    _devflow_pool_suite_body() {
      set -u
      _devflow_pool_run_one "$name" "$script" "$mode" "$tally"
    }
    _devflow_supervise_module _devflow_pool_suite_body \
      "$group_pid_file" "$worker_pid_file"
  ) > "$output" 2>&1 &
  pid=$!
  # Forced-timeout hook (issue #720 AC test): skip the supervisor PID-file write on
  # attempt 1 so the rendezvous deliberately times out and the serial-retry path is
  # exercised. Normal launches write it exactly as devflow_run_full_suite_module does.
  if [ "${DEVFLOW_POOL_FORCE_RENDEZVOUS_TIMEOUT:-}" = "$name" ] && [ "$attempt" -eq 1 ]; then
    :
  else
    _devflow_test_write_pid "$group_pid_file" "$pid" "pool supervisor" || :
  fi
  _DEVFLOW_POOL_INFLIGHT_PIDS+=("$pid")
  _DEVFLOW_POOL_PID_NAME["$pid"]="$name"
  _DEVFLOW_POOL_PID_SCRIPT["$pid"]="$script"
  _DEVFLOW_POOL_PID_MODE["$pid"]="$mode"
  _DEVFLOW_POOL_PID_SCRATCH["$pid"]="$scratch"
  _DEVFLOW_POOL_PID_TALLY["$pid"]="$tally"
  _DEVFLOW_POOL_PID_OUTPUT["$pid"]="$output"
  # Register in the run-wide live-child registry BEFORE clearing the launch-window
  # guard, mirroring devflow_run_full_suite_module's register-before-unguard ordering
  # (issue #720). A HUP/INT/TERM delivered in the window between the guard clear and
  # this registration would otherwise see both launch guards at 0 and this just-forked
  # pid still absent from _DEVFLOW_LIVE_CHILD_PIDS, so _devflow_full_suite_signal would
  # terminate the already-registered children and exit while this child is left running
  # orphaned against the checkout. With the guard still 1 across this registration, such
  # a signal is stashed in _DEVFLOW_POOL_PENDING_SIGNAL and replayed just below.
  _devflow_register_live_child "$pid" "$scratch" "$tally"
  _DEVFLOW_POOL_LAUNCHING=0
  [ "$monitor_was_on" -eq 1 ] || set +m
  if [ -n "$_DEVFLOW_POOL_PENDING_SIGNAL" ]; then
    _devflow_full_suite_signal "$_DEVFLOW_POOL_PENDING_SIGNAL"
  fi
}

_devflow_pool_launch_next() {
  local name="${_DEVFLOW_POOL_PENDING_NAMES[0]}"
  local script="${_DEVFLOW_POOL_PENDING_SCRIPTS[0]}"
  local mode="${_DEVFLOW_POOL_PENDING_MODES[0]}"
  _devflow_pool_pending_shift
  _devflow_pool_launch_suite "$name" "$script" "$mode" 1
}

_devflow_pool_reap() { # pid rc
  local pid="$1" rc="$2" _l _pool_count="" _hasfail=0
  local name="${_DEVFLOW_POOL_PID_NAME[$pid]:-?}"
  local script="${_DEVFLOW_POOL_PID_SCRIPT[$pid]:-}"
  local mode="${_DEVFLOW_POOL_PID_MODE[$pid]:-}"
  local scratch="${_DEVFLOW_POOL_PID_SCRATCH[$pid]:-}"
  local tally="${_DEVFLOW_POOL_PID_TALLY[$pid]:-}"
  local output="${_DEVFLOW_POOL_PID_OUTPUT[$pid]:-}"
  _devflow_deregister_live_child "$pid"
  _devflow_pool_inflight_remove "$pid"

  # A supervisor PID rendezvous timeout (rc != 0, empty tally, timeout marker in
  # the captured output) is absorbed by re-running the suite serially, not recorded
  # as a suite failure.
  if [ "$rc" -ne 0 ] && [ ! -s "$tally" ] && \
    _devflow_pool_output_has_rendezvous_timeout "$output"; then
    [ -z "$scratch" ] || _devflow_cleanup_module_scratch "$scratch" || :
    scratch=""
    # Reuse $output (truncated) as the serial retry's capture so the self-tally summary
    # capture below still sees the retried suite's `N passed, M failed` line — nulling
    # it here would drop the summary and inject a spurious FAIL (issue #720 review).
    if [ -n "$output" ] && [ "$output" != /dev/null ]; then
      : > "$output" 2>/dev/null || :
    elif ! output="$(mktemp "${TMPDIR:-/tmp}/devflow-pool-out.XXXXXX")"; then
      output=/dev/null
      printf 'devflow-pool: suite %s — retry output-capture tempfile allocation failed (TMPDIR full/quota?); a self-tally summary will be uncapturable and recorded as a FAIL downstream\n' "$name" >&2
    fi
    _devflow_pool_run_serial "$name" "$script" "$mode" "$tally" "$output"
    rc=$?
  fi

  # Every pooled verdict reaches PASS/FAIL through RESULTS_FILE, after validation.
  # _devflow_valid_result_count both validates the tally grammar (PASS/FAIL lines
  # only) AND prints the PASS+FAIL line count — capture that count rather than
  # re-grepping for the self-tally cross-check below.
  if _pool_count="$(_devflow_valid_result_count "$tally")"; then
    if ! cat "$tally" >> "$RESULTS_FILE"; then
      printf 'FAIL\n' >> "$RESULTS_FILE"
      printf '  FAIL  pool suite %s — could not append private tally to results\n' "$name" >&2
      record_fail "pool suite $name — could not append private tally to results"
    fi
    # The pooled suite's identifier record (issue #789), folded for the same reason as the
    # sourced-module fold above: the worker's record_fail wrote into "$tally.names" because
    # RESULTS_FILE was rebound to "$tally", and only this fold puts those names in front of
    # the reader. Guarded on non-empty — a clean pooled suite writes no sibling.
    if [ -s "$tally.names" ] && ! cat "$tally.names" >> "$RESULTS_FILE.names"; then
      printf 'FAIL\n' >> "$RESULTS_FILE"
      printf '  FAIL  pool suite %s — could not append private failure-identifier record\n' "$name" >&2
      record_fail "pool suite $name — could not append private failure-identifier record"
    fi
  else
    _pool_count=""
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — private tally missing/unreadable after execution\n' "$name" >&2
    record_fail "pool suite $name — private tally missing/unreadable after execution"
  fi

  # Fail-closed guards mirroring devflow_run_full_suite_module (issue #720 review): a
  # NONZERO worker exit not already reflected as a FAIL — a kill/crash the rendezvous
  # branch did not absorb, whose worker never reached _devflow_pool_run_one's own
  # fail-closed append — and a validated-but-EMPTY tally (zero assertions) each record a
  # FAIL, so a killed or silently-empty pooled suite can never vanish with '0 failed'.
  if [ "$rc" -ne 0 ]; then
    _hasfail=0
    while IFS= read -r _l || [ -n "$_l" ]; do
      [ "$_l" = "FAIL" ] && { _hasfail=1; break; }
    done < "$tally" 2>/dev/null
    if [ "$_hasfail" -eq 0 ]; then
      printf 'FAIL\n' >> "$RESULTS_FILE"
      printf '  FAIL  pool suite %s — worker exited with status %s (no verdict recorded)\n' "$name" "$rc" >&2
      record_fail "pool suite $name — worker exited with status $rc (no verdict recorded)"
    fi
  elif [ "$_pool_count" = "0" ]; then
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — executed zero assertions\n' "$name" >&2
    record_fail "pool suite $name — executed zero assertions"
  fi

  if [ "$rc" -ne 0 ] && [ -n "$output" ] && [ -f "$output" ]; then
    while IFS= read -r _l || [ -n "$_l" ]; do printf '    %s\n' "$_l"; done < "$output"
  fi

  # Capture the self-tally count/summary before cleanup so run.sh can assert the
  # whole assertion count reached RESULTS_FILE (issue #720). The line count reuses
  # the validated count above; an invalid tally leaves it empty (surfaced as
  # 'unestablished' by the run.sh assertion rather than a fabricated 0).
  if [ "$mode" = "self-tally" ]; then
    _DEVFLOW_POOL_SELFTALLY_LINES["$name"]="$_pool_count"
    if [ -n "$output" ] && [ -f "$output" ]; then
      _DEVFLOW_POOL_SELFTALLY_SUMMARY["$name"]="$(grep -E '^[0-9]+ passed, [0-9]+ failed' "$output" 2>/dev/null | tail -1)"
    fi
  fi

  # A scratch-cleanup failure records a FAIL, matching devflow_run_full_suite_module's
  # boundary (issue #720 review): a pooled suite that leaks an undeletable scratch tree
  # is a real fault, not a silent best-effort skip.
  if [ -n "$scratch" ] && ! _devflow_cleanup_module_scratch "$scratch"; then
    printf 'FAIL\n' >> "$RESULTS_FILE"
    printf '  FAIL  pool suite %s — could not remove private scratch root\n' "$name" >&2
    record_fail "pool suite $name — could not remove private scratch root"
  fi
  [ -z "$tally" ] || rm -f "$tally" "$tally.names"   # .names: the #789 identifier sibling, folded above
  [ -n "$output" ] && [ "$output" != /dev/null ] && rm -f "$output"
  unset '_DEVFLOW_POOL_PID_NAME[$pid]' '_DEVFLOW_POOL_PID_SCRIPT[$pid]' \
    '_DEVFLOW_POOL_PID_MODE[$pid]' '_DEVFLOW_POOL_PID_SCRATCH[$pid]' \
    '_DEVFLOW_POOL_PID_TALLY[$pid]' '_DEVFLOW_POOL_PID_OUTPUT[$pid]'
}

# Open the pool: resolve width, save+install the HUP/INT/TERM traps, and launch up
# to `width` suites. Args are triples: name script mode (mode ∈ single-verdict |
# self-tally). The remaining suites, if any, launch during join as slots free.
devflow_pool_open() { # name1 script1 mode1 [name2 script2 mode2 ...]
  _DEVFLOW_POOL_PENDING_NAMES=(); _DEVFLOW_POOL_PENDING_SCRIPTS=(); _DEVFLOW_POOL_PENDING_MODES=()
  _DEVFLOW_POOL_INFLIGHT_PIDS=()
  _DEVFLOW_POOL_PENDING_SIGNAL=""
  _DEVFLOW_POOL_WIDTH="$(_devflow_pool_resolve_width)"
  while [ "$#" -ge 3 ]; do
    _DEVFLOW_POOL_PENDING_NAMES+=("$1")
    _DEVFLOW_POOL_PENDING_SCRIPTS+=("$2")
    _DEVFLOW_POOL_PENDING_MODES+=("$3")
    shift 3
  done
  _DEVFLOW_POOL_SAVED_HUP="$(trap -p HUP)"
  _DEVFLOW_POOL_SAVED_INT="$(trap -p INT)"
  _DEVFLOW_POOL_SAVED_TERM="$(trap -p TERM)"
  trap '_devflow_full_suite_signal HUP' HUP
  trap '_devflow_full_suite_signal INT' INT
  trap '_devflow_full_suite_signal TERM' TERM
  _DEVFLOW_POOL_OPEN=1
  # In-flight children never exceed the resolved width: launch min(width, count).
  while [ "${#_DEVFLOW_POOL_PENDING_NAMES[@]}" -gt 0 ] && \
    [ "${#_DEVFLOW_POOL_INFLIGHT_PIDS[@]}" -lt "$_DEVFLOW_POOL_WIDTH" ]; do
    _devflow_pool_launch_next
  done
}

# Join the pool: reap every in-flight child (launching pending suites as slots free
# so the width limit still holds), append each verdict to RESULTS_FILE, then restore
# the caller's signal traps. Installs no EXIT trap; leaves _suite_cleanup the sole
# EXIT handler. Must be called before the RESULTS_FILE tally is counted.
devflow_pool_join() {
  [ "${_DEVFLOW_POOL_OPEN:-0}" -eq 1 ] || return 0
  local pid rc
  while [ "${#_DEVFLOW_POOL_INFLIGHT_PIDS[@]}" -gt 0 ]; do
    pid="${_DEVFLOW_POOL_INFLIGHT_PIDS[0]}"
    if wait "$pid"; then rc=0; else rc=$?; fi
    _devflow_pool_reap "$pid" "$rc"
    if [ "${#_DEVFLOW_POOL_PENDING_NAMES[@]}" -gt 0 ]; then
      _devflow_pool_launch_next
    fi
  done
  _devflow_restore_signal_traps "$_DEVFLOW_POOL_SAVED_HUP" \
    "$_DEVFLOW_POOL_SAVED_INT" "$_DEVFLOW_POOL_SAVED_TERM"
  _DEVFLOW_POOL_OPEN=0
}

# ── The suite's PRODUCTION Python-suite pool: membership + reconciliation ────
# (Issue #720 opened the pool; the CI shard split moved where it is driven.)
#
# The five heavy focused Python suites the complete suite drives CONCURRENTLY —
# test_module_runner.py plus the four test_python_scripts parts (issue #2007). Their
# membership, each one's tally mode, and the self-tally reconciliation live here — in
# ONE place — because two callers drive them, and a second copy of the membership list
# is the coupled-mirror hazard at its worst: a suite added to one caller and not the
# other would run locally and silently never run in CI (or the reverse), with every
# tally staying green because the missing suite's assertions simply never appear.
#
#   * lib/test/run.sh opens the pool early and joins at the tail, so the Python work
#     overlaps ~2000 lines of shell assertions — a local full run pays only the idle
#     remainder at the join, not the suites' whole cost;
#   * lib/test/run-python-pool.sh is the dedicated CI shard's driver — it has nothing
#     to overlap, so it opens and joins back-to-back.
#
# Both entry points no-op under DEVFLOW_SKIP_PYTHON_POOL=1 (what the monolith shard
# sets), so exactly one shard runs these suites per CI run and nothing is
# double-counted — the same dedup argument DEVFLOW_SKIP_SUITE_MODULES makes for the
# module tier.
#
# test_module_harness.py is deliberately NOT a member — see its serial driver site in
# run.sh: it asserts on the SIGINT disposition its children inherit, which a pooled
# fork under job control off would corrupt.

# The selector decision, in ONE place. rc 0 = run the pool, rc 1 = this shard's work
# belongs to the `python-pool` shard instead.
#
# The gate lives HERE, inside the entry points below, rather than as an `if` at each
# call site: a call-site `if` is a decision the suite can only reach by running the
# whole of run.sh (~6 minutes), so in practice it would ship untested, and an inverted
# one fails in the two worst directions — double-counting both suites into the
# aggregate, or dropping both from a local full run with no floor to notice. As a
# predicate with one home, every arm is drivable directly, which is exactly how
# DEVFLOW_SKIP_SUITE_MODULES is gated inside devflow_run_full_suite_module.
#
# Only the exact value `1` disables, matching that sibling: any other value (including
# `0`, `yes`, and empty) runs the pool, so a half-set variable never silently drops
# coverage.
devflow_python_pool_enabled() {
  [ "${DEVFLOW_SKIP_PYTHON_POOL:-}" = 1 ] && return 1
  return 0
}

# The script paths are anchored on THIS file's directory (BASH_SOURCE self-anchoring,
# the local-tier idiom) rather than on a caller-supplied root, so no caller can hand
# the pool a wrong base and have a real suite degrade into a missing-script failure.
devflow_python_suite_pool_open() {
  devflow_python_pool_enabled || return 0
  local _pp_dir
  _pp_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || return 1
  devflow_pool_open \
    "test_module_runner.py" "$_pp_dir/test_module_runner.py" single-verdict \
    "test_python_scripts.py" "$_pp_dir/test_python_scripts.py" self-tally \
    "test_python_scripts_part2.py" "$_pp_dir/test_python_scripts_part2.py" self-tally \
    "test_python_scripts_part3.py" "$_pp_dir/test_python_scripts_part3.py" self-tally \
    "test_python_scripts_part4.py" "$_pp_dir/test_python_scripts_part4.py" self-tally
}

# The four self-tally parts test_python_scripts.py was split into (issue #2007), the
# member set devflow_python_suite_pool_join reconciles. Sourced by run.sh's
# _pps_reconcile_probe too, so it is a shared definition rather than a second literal.
DEVFLOW_PYTHON_SELFTALLY_MEMBERS=(
  "test_python_scripts.py"
  "test_python_scripts_part2.py"
  "test_python_scripts_part3.py"
  "test_python_scripts_part4.py"
)

# Join the production pool and reconcile the self-tally contribution (issue #720):
# test_python_scripts.py's contribution to RESULTS_FILE must equal the assertion count
# it reports on its own `N passed, M failed` summary line — parsed POSITIONALLY from
# that line (field 1 = passed, field 3 = failed), never a checked-in total, so a
# UNIFORMLY dropped verdict is caught even though the width-1/width-N equality gate
# would agree. The self-tally line count and summary were captured at reap.
#
# Calls assert_eq, which each caller defines against the same RESULTS_FILE +
# record_fail contract; the name resolves at call time.
devflow_python_suite_pool_join() {
  devflow_python_pool_enabled || return 0
  local _ps_member _ps_lines _ps_summary _ps_total
  devflow_pool_join
  # Reconcile every split part's self-tally contribution (issue #2007 generalized the
  # single-member #720 check to the four parts) — each part's RESULTS_FILE contribution
  # must equal the passed+failed it reports on its own summary line.
  for _ps_member in "${DEVFLOW_PYTHON_SELFTALLY_MEMBERS[@]}"; do
    _ps_lines="${_DEVFLOW_POOL_SELFTALLY_LINES[$_ps_member]:-}"
    _ps_summary="${_DEVFLOW_POOL_SELFTALLY_SUMMARY[$_ps_member]:-}"
    if [ -n "$_ps_summary" ]; then
      # Positional parse with bash word-splitting (not awk — a value feeding an assertion,
      # kept off non-preflight PATH tools per guard-class 2): "N passed, M failed".
      # shellcheck disable=SC2086
      set -- $_ps_summary
      _ps_total=$(( ${1:-0} + ${3:-0} ))
      assert_eq "#720 $_ps_member: RESULTS_FILE contribution equals its summary passed+failed" \
        "$_ps_total" "${_ps_lines:-unestablished}"
    else
      # Summary not captured (e.g. a rendezvous-retry emptied the captured output): record
      # a FAIL rather than silently skipping the coverage check.
      echo FAIL >> "$RESULTS_FILE"
      record_fail "#720 $_ps_member: summary line not captured"
      printf '  FAIL  #720 %s: could not capture its summary line to verify RESULTS_FILE contribution\n' "$_ps_member" >&2
    fi
  done
}

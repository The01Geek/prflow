# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable harness-python-guards contract module (issue #707).
#
# It carries the driver blocks for the monolith-only Python guards whose subject is
# a single code unit and whose verification is self-contained, so a change scoped to
# one of them is verifiable in seconds with
# `lib/test/run-module.sh harness-python-guards` instead of the complete suite.
#
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. This module uses assert_eq (caller-provided, per that
# contract — both run.sh and run-module.sh define it) plus the harness helpers
# lib/test/module-harness.sh defines — devflow_run_sharded_python_test,
# devflow_run_focused_python_test, and devflow_module_allocate_owned_directory — and
# references NO helper that lives ONLY in lib/test/run.sh. The module owns its
# private fixture root and cleanup; it never invokes the runner or the full-suite
# boundary. The inventory in harness-python-guards.inventory.md maps the extracted
# coverage to its former run.sh locations and records the deliberate exclusions.
# Modules may not self-skip.
# The `trap _hpg_cleanup EXIT` below relies on a sourcing contract: both callers
# (module-harness.sh's full-suite boundary and run-module.sh) source this module
# inside a ( ... ) subshell, so the trap fires at subshell exit and cannot clobber
# the runner's own EXIT handling. Do not source this module directly in a runner's
# top-level shell without restoring the trap.

# Allocate through the harness's shared owned-directory allocator (template validation
# plus the pre-existing-directory rejection a bare `mktemp -d` cannot make) rather than
# re-implementing that check here.
_hpg_tmp_root="$(devflow_module_allocate_owned_directory \
  "${TMPDIR:-/tmp}/devflow-harness-python-guards.XXXXXX")" || {
  printf 'could not allocate harness-python-guards fixture\n' >&2
  return 1
}
_hpg_cleanup() {
  rm -rf "$_hpg_tmp_root"
}
trap _hpg_cleanup EXIT

# ────────────────────────────────────────────────────────────────────────────
echo "#600 create-issue audit-prompt renderer (render-audit-prompt.py)"
# ────────────────────────────────────────────────────────────────────────────
# R1..R12 are unit-driven in lib/test/test_render_audit_prompt.py (renderer over
# mktemp fixture trees + a delivery-equivalence matrix that drives the real
# load-prompt-extension.sh). The two greps below are SOURCE-SHAPE pins that
# backstop test_R9_statelessness (which is the outcome check — it observes that no
# file was written and no stdin was read). A source scan cannot see a write routed
# through subprocess/shutil/os.write or a variable-mode Path.open, so these pins
# catch the obvious reintroduction and R9 catches the behavior.
RAP_ROOT="$(mktemp -d "$_hpg_tmp_root/rap.XXXXXX")" || {
  printf 'could not allocate the #600 render-audit-prompt fixture\n' >&2
  return 1
}
# Shared runner, for the reasons stated in the #527 block below: it surfaces the captured
# traceback on a RED, applies the PYTHON_COLORS=0 determinism guard, and removes the
# positional `$?` read a later inserted statement would silently re-point at another command.
devflow_run_focused_python_test "#600 render-audit-prompt: focused Python tests pass" \
  "$LIB/test/test_render_audit_prompt.py" "$RAP_ROOT/rap-unit.out"
assert_eq "#600 render-audit-prompt writes no file (stateless)" "0" \
  "$(grep -cE "open\([^)]*['\"][wax]|\.write_text\(|\.write_bytes\(" "$LIB/../scripts/render-audit-prompt.py" || true)"
assert_eq "#600 render-audit-prompt reads no stdin (stateless)" "0" \
  "$(grep -cE 'sys\.stdin|(^|[^a-zA-Z_])input\(' "$LIB/../scripts/render-audit-prompt.py" || true)"
rm -rf "$RAP_ROOT"

VB_ROOT="$(mktemp -d "$_hpg_tmp_root/vb.XXXXXX")" || {
  printf 'could not allocate the #527 verification-baseline fixture\n' >&2
  return 1
}

# ────────────────────────────────────────────────────────────────────────────
echo "verification-launch baseline analyzer (issue #527, Wave 1)"
# ────────────────────────────────────────────────────────────────────────────
# Route through the shared focused-Python-test runner rather than a bare redirect +
# positional `$?`: the runner surfaces the captured traceback on a RED (the old form wrote
# the capture and then removed it unread, leaving only "expected 0, got 1" in the module
# whose whole purpose is fast diagnosable iteration) and applies its PYTHON_COLORS=0
# determinism guard. It also removes the positional `$?` read, which a later inserted
# statement would silently re-point at the wrong command.
devflow_run_focused_python_test "verification baseline: focused Python tests pass" \
  "$LIB/test/test_verification_baseline.py" "$VB_ROOT/vb-unit.out"
# The analyzer is offline (AC #527-2: read-only, launches no verification
# command and invokes no repository-provided executable) — no subprocess call
# site in the module. (It imports workflow_flight_recorder, which itself uses
# subprocess for read-only git; the analyzer never calls those functions.)
assert_eq "verification baseline: analyzer invokes no subprocess" "0" \
  "$(grep -cE 'subprocess\.(run|Popen|call|check_output|check_call)' "$LIB/../scripts/verification_baseline.py" || true)"
# Widened evasion sweep (PR #531 review): the dotted-call pin alone is evadable
# by `from subprocess import run`, `subprocess.getoutput`, `os.system`,
# `os.popen`, or `pty.spawn` — none of which it matches. The module legitimately
# imports no subprocess machinery at all, so pin the absence of every spelling.
assert_eq "verification baseline: no subprocess import or shell-out spelling" "0" \
  "$(grep -cE '(^|[^a-zA-Z_])(import subprocess|from subprocess import|os\.system|os\.popen|getoutput|check_output|pty\.spawn|import pty)' "$LIB/../scripts/verification_baseline.py" || true)"
# Registry coupled pins (the test_workflow_flight_recorder registry test asserts
# the 5-workflow set; these pin the #527 additions the analyzer depends on).
assert_eq "verification baseline: registry has the review first-message forms" "1" \
  "$(grep -cF '"/devflow:review", "/review"' "$LIB/../scripts/workflow-flight-recorder-registry.json" || true)"
assert_eq "verification baseline: registry has the cloud_mappings section" "1" \
  "$(grep -cF '"cloud_mappings"' "$LIB/../scripts/workflow-flight-recorder-registry.json" || true)"

rm -rf "$VB_ROOT"

VF_ROOT="$(mktemp -d "$_hpg_tmp_root/vf.XXXXXX")" || {
  printf 'could not allocate the #528 verification-flight fixture\n' >&2
  return 1
}

# ────────────────────────────────────────────────────────────────────────────
echo "single-flight verification coordination ledger (issue #528, Wave 2)"
# ────────────────────────────────────────────────────────────────────────────
# Shared runner, for the reasons stated in the #527 block above.
devflow_run_focused_python_test "verification flight: focused Python tests pass" \
  "$LIB/test/test_verification_flight.py" "$VF_ROOT/vf-unit.out"
# The coordinator is data-only (AC #528-1): it launches no subprocess, spawns no
# shell, and runs no git — it never becomes a shell-command bypass. Pin the
# absence of every subprocess / shell-out / exec spelling.
#
# The spelling list is NOT written here. It is read from the single source of
# truth — BANNED_EXEC_SPELLINGS in lib/test/test_verification_flight.py — so this
# shell sweep and the Python guard cannot drift into disagreeing coverage (the
# earlier hand-copied 10-alternative regex was a strict subset of the Python-side
# list, so each guard certified the contract against the other's blind spot).
# python3 is a hard preflight prerequisite, so deriving the list is safe here.
VF_SRC="$LIB/../scripts/verification-flight.py"
VF_SPELLINGS="$(python3 - "$LIB/test/test_verification_flight.py" <<'VFEOF'
import ast, sys

# Derive ATOMICALLY: collect the whole tuple first, and only then print. A
# print-as-you-go loop fails OPEN on a partial derivation — a tuple element that is
# not a bare string literal (a concatenation, an f-string, a name) raises partway
# through, the elements already printed survive in the caller's variable, and a
# non-empty check waves the truncated list through as if coverage were complete.
# Anything unexpected exits non-zero with an empty stdout instead, so the caller's
# fail-closed check fires.
spellings = []
found = False
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        getattr(t, "id", "") == "BANNED_EXEC_SPELLINGS" for t in node.targets
    ):
        found = True
        if not isinstance(node.value, ast.Tuple):
            sys.exit("BANNED_EXEC_SPELLINGS is not a tuple literal")
        for elt in node.value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                sys.exit("BANNED_EXEC_SPELLINGS holds a non-string-literal element")
            spellings.append(elt.value)
if not found:
    sys.exit("BANNED_EXEC_SPELLINGS assignment not found")
print("\n".join(spellings))
VFEOF
)"
# Fail closed: an empty derivation would make every membership test below vacuous.
assert_eq "verification flight: banned-spelling list derived from its single source" "yes" \
  "$([ -n "$VF_SPELLINGS" ] && echo yes || echo no)"
# Fail closed on a PARTIAL derivation too: the derived line count must equal the
# tuple's own element count, so a silently-truncated list cannot pass the non-empty
# check above. (Deriving the expected count independently, from a plain literal
# count over the source, keeps this from being a self-referential tautology.)
VF_TUPLE_LEN="$(python3 - "$LIB/test/test_verification_flight.py" <<'VFLEN'
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        getattr(t, "id", "") == "BANNED_EXEC_SPELLINGS" for t in node.targets
    ):
        print(len(node.value.elts))
        break
VFLEN
)"
assert_eq "verification flight: banned-spelling derivation is complete (no partial truncation)" \
  "$VF_TUPLE_LEN" "$(printf '%s\n' "$VF_SPELLINGS" | grep -c .)"
# The exec sweep is factored into ONE function that both the real zero-expecting assertion AND
# the #719 positive control below invoke, so the control drives the REAL counting code path
# rather than a second copy of it. A duplicate control loop would prove only that grep -cF
# counts fixed strings while a regression in the real loop (an inverted case arm, a dropped
# `+ 1`, a swept-file swap) escaped — the exact duplicate-mirror blind spot #719 removed from
# the run.sh retired-convention control. The per-spelling hit diagnostic goes to STDERR (a
# RED-path breadcrumb) so it never pollutes the count captured from stdout.
_vf_exec_sweep_count() {  # swept-file ; spelling stream on stdin -> prints the hit count
  local _f="$1" _sp _hits=0
  while IFS= read -r _sp; do
    [ -n "$_sp" ] || continue
    case "$(grep -cF -- "$_sp" "$_f" || true)" in
      0) : ;;
      *) _hits=$((_hits + 1)); printf '  exec-sweep hit: %s\n' "$_sp" >&2 ;;
    esac
  done
  printf '%s\n' "$_hits"
}
VF_EXEC_HITS="$(printf '%s\n' "$VF_SPELLINGS" | _vf_exec_sweep_count "$VF_SRC")"
assert_eq "verification flight: no subprocess / shell-out / exec spelling" "0" "$VF_EXEC_HITS"
# #719 positive control: the zero-expecting exec sweep above is only meaningful if its COUNTING
# half is live — a broken counter (a mistyped grep, an empty spelling stream, a swallowed loop)
# would pass the "expected 0" sweep by counting nothing, certifying a coordinator it never read.
# Plant EVERY derived spelling into a scratch copy of the real coordinator and require the SAME
# `_vf_exec_sweep_count` function the real assertion runs to count each, so a regression in the
# sweep's counting code turns BOTH red. The comparand (VF_TUPLE_LEN) is derived independently
# from the tuple, not from the sweep, so this is not a self-referential tautology.
VF_PLANT="$(mktemp "$VF_ROOT/vf-plant.XXXXXX")" || {
  printf 'could not allocate the #528 positive-control fixture\n' >&2
  return 1
}
cat "$VF_SRC" > "$VF_PLANT"
while IFS= read -r _vf_spelling; do
  [ -n "$_vf_spelling" ] || continue
  printf '%s\n' "$_vf_spelling" >> "$VF_PLANT"
done <<VFPLANT
$VF_SPELLINGS
VFPLANT
VF_PLANT_HITS="$(printf '%s\n' "$VF_SPELLINGS" | _vf_exec_sweep_count "$VF_PLANT")"
assert_eq "#528 banned-exec sweep positive control: every planted spelling is counted (counting half is live)" \
  "$VF_TUPLE_LEN" "$VF_PLANT_HITS"
rm -f "$VF_PLANT"
# The exact, exhaustive state set is a coupled invariant with the helper source
# and the docs — pin the full declared membership (the grep literals enforce exact
# content) so a dropped/renamed state goes RED.
assert_eq "verification flight: ALL_STATES declares the active set" "1" "$(grep -cF '"claimed", "running"' "$VF_SRC" || true)"
assert_eq "verification flight: TERMINAL_STATES declares every terminal state" "1" \
  "$(grep -cF '"passed", "failed", "timed_out", "cancelled", "stale", "incomplete"' "$VF_SRC" || true)"

# Coupled grant invariant (issue #528 AC): the vendored-literal helper grant must
# land in BOTH the implement profile (inline Implement review pass) and the light
# manual-comment profile (manual Review-and-Fix), and must NOT be added to the
# read-only reviewer profile (standalone CI-grounded Review creates no flight).
assert_eq "#528 coupled: devflow-implement.yml grants verification-flight.py by vendored path" "1" \
  "$(grep -cF 'Bash(.prflow/vendor/prflow/scripts/verification-flight.py:*)' "$LIB/../.github/workflows/devflow-implement.yml" || true)"
assert_eq "#528 coupled: devflow.yml (manual review listener) grants verification-flight.py by vendored path" "1" \
  "$(grep -cF 'Bash(.prflow/vendor/prflow/scripts/verification-flight.py:*)' "$LIB/../.github/workflows/devflow.yml" || true)"
assert_eq "#528 coupled: devflow-runner.yml (read-only reviewer) grants NO verification-flight flight helper" "0" \
  "$(grep -cF 'verification-flight.py' "$LIB/../.github/workflows/devflow-runner.yml" || true)"

rm -rf "$VF_ROOT"

# ────────────────────────────────────────────────────────────────────────────
echo "receiving-review session artifact producer (issue #668)"
# ────────────────────────────────────────────────────────────────────────────
RI_LIB="$LIB/../scripts/reception_identity.py"
RR_CLI="$LIB/../scripts/reception-record.py"
RI_ROOT="$(mktemp -d "$_hpg_tmp_root/ri.XXXXXX")" || {
  printf 'could not allocate the #668 reception-identity capture root\n' >&2
  return 1
}
# Shared runner, for the reasons stated in the #527 block above.
devflow_run_focused_python_test "reception identity: focused Python tests pass (library + CLI + flight extension)" \
  "$LIB/test/test_reception_identity.py" "$RI_ROOT/ri-unit.out"
# The library is an importable, non-executable stdlib-only routine (AC1): no exec bit,
# no PyYAML import, no gh call, no network call.
assert_eq "reception identity: library carries no executable bit" "no" \
  "$([ -x "$RI_LIB" ] && echo yes || echo no)"
assert_eq "reception identity: CLI carries the executable bit" "yes" \
  "$([ -x "$RR_CLI" ] && echo yes || echo no)"
assert_eq "reception identity: library imports no PyYAML" "0" \
  "$(grep -cE '(^|[^a-zA-Z_])(import yaml|from yaml import)' "$RI_LIB" || true)"
# The gh-call sweep's boundary is `(^|[^a-zA-Z_])gh ` — a deliberate BSD-PORTABILITY delta from
# the `\bgh \b` word-boundary spelling: BSD `grep -E` (macOS) does not honor GNU's `\b`
# word-boundary escape, so `\bgh \b` matches nothing there and the guard fails OPEN on exactly
# the platform CLAUDE.md's portability convention targets. `(^|[^a-zA-Z_])` is the portable
# left-boundary and the trailing space is the right one; the behavior is identical to `\bgh \b`
# on a leading-token `gh ` call and is portable across GNU and BSD grep.
assert_eq "reception identity: library makes no gh call" "0" \
  "$(grep -cE '"gh"|(^|[^a-zA-Z_])gh ' "$RI_LIB" || true)"
# #719: the comment above enumerates four AC1 properties (no exec bit, no PyYAML import, no gh
# call, no network call); the fourth had no assertion, so the enumeration over-claimed its own
# coverage. Pin the network-call absence — but NOT by enumerating banned modules: a banned-list
# alternation accepts a SUPERSET of what it names, so every stdlib network module the list omits
# (smtplib, ftplib, asyncio, xmlrpc, telnetlib, …) fails OPEN, which is the guard-accepts-more-
# than-its-consumer class CLAUDE.md warns about. Pin the library's ENTIRE import set instead —
# an exact-match allowlist fails CLOSED: any added import, network or otherwise, turns this RED
# and must be re-adjudicated. ast.walk covers function-level imports too, so a lazily-imported
# network module cannot slip past a top-level-only scan. python3 is a hard preflight prerequisite
# and any failure yields empty output, which mismatches and goes RED (never a silent pass).
assert_eq "reception identity: library imports exactly the permitted stdlib set (no network module)" \
  "__future__ os shutil subprocess tempfile" \
  "$(python3 -c 'import ast,sys
mods=set()
for n in ast.walk(ast.parse(open(sys.argv[1], encoding="utf-8").read())):
    if isinstance(n, ast.Import):
        mods.update(a.name.split(".")[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom):
        mods.add((n.module or "").split(".")[0])
print(" ".join(sorted(mods)))' "$RI_LIB" 2>/dev/null || true)"
# The CLI imports the library rather than re-implementing the derivation (AC2): exactly one
# copy of the identity format ships. Pin the import and the absence of a second write-tree.
assert_eq "reception identity: CLI imports the library (single derivation implementation)" "1" \
  "$(grep -cF 'import reception_identity' "$RR_CLI" || true)"
assert_eq "reception identity: CLI does not re-implement write-tree" "0" \
  "$(grep -cF 'write-tree' "$RR_CLI" || true)"
rm -rf "$RI_ROOT"

# ────────────────────────────────────────────────────────────────────────────
echo "#798 pin-corpus protected-asset classifier"
# ────────────────────────────────────────────────────────────────────────────
# The production classifier is a maintainer-run census instrument, not a suite
# gate. Its focused unit tests are self-contained: synthetic tracked populations
# exercise parsing and classification, while one live-corpus arm proves the
# committed adjudications still close every row without writing the inventory.
_HPG_CLASSIFIER_OUT="$(mktemp "$_hpg_tmp_root/classifier-unit.XXXXXX")" || {
  printf 'could not allocate the #798 classifier unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test \
  "#798 pin-corpus classifier: focused Python tests pass" \
  "$LIB/test/test_pin_corpus_classifier.py" \
  "$_HPG_CLASSIFIER_OUT"
assert_eq "#798 pin-corpus classifier remains maintainer-run (no run.sh invocation)" \
  "0" "$(grep -cF 'pin-corpus-classifier.py' "$LIB/test/run.sh" || true)"
rm -f "$_HPG_CLASSIFIER_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "#810 pin-corpus wording-only authoring gate"
# ────────────────────────────────────────────────────────────────────────────
# These focused tests drive the same path-aware parser, registry-closed source
# population, classification-preserving move logic, and fail-closed worktree setup
# that run.sh's blocking `pin-corpus-lint.py mutation-routing-worktree` gate
# consumes. run.sh carries several production pin-corpus-lint.py subcommands, so
# the gate is named by subcommand rather than by position or by breadth.
# Sharded rather than run as one serial process (issue #870): as measured on the
# issue-#870 baseline (CI run 30295235589, post-#866 tree), this file was the single
# largest serial block in the required CI check, and its heaviest class pays a
# git-init-and-commit corpus fixture per test. What makes sharding safe here is the
# tests' mutual independence — no shared filesystem state; every filesystem-touching
# test allocates its own temp dir and passes an explicit cwd — a property
# test_pin_corpus_lint.py's own docstring states as a requirement. The modules those
# tests drive do hold process-global memos, which that docstring covers in the same
# place, and it takes two limbs rather than one. The per-source parse memos are keyed
# on the presented bytes — the census memos additionally on the source's name, the
# linter memos on the text alone (issue #956's two bundle-membership parses additionally
# on the caller's lib path) — and on no repo_root or filesystem state, so a hit
# answers for exactly what the caller presented; the bundle resolver's glob expansion
# stays OUTSIDE its memo to keep that true. _load_mutation_census_module is
# the second limb: it takes no arguments at all, so its safety rests not on its key but
# on the module it returns mutating nothing after import beyond those same key-pure
# memos — its other module-level objects, the compiled-regex dicts among them, are
# built once at import and never written to.
# Either way a shard's ordering cannot change an outcome. Keep the statements together.
_HPG_PIN_LINT_SHARDS="$(mktemp -d "$_hpg_tmp_root/pin-lint-shards.XXXXXX")" || {
  printf 'could not allocate the #810 pin-lint shard capture directory\n' >&2
  return 1
}
# This is the module's heaviest unit by a wide margin, and it used to execute TWICE per CI
# run: once as the `modules-pin` shard, and once inside the `monolith` shard, because
# lib/test/test_module_runner.py is a pooled suite and its CONTRIBUTING-step-8 real-runner
# meta-test drives this whole module end-to-end through lib/test/run-module.sh. That second
# execution was the critical path of the required check (issue #890). The population is
# therefore chosen by whichever runner sourced this module — see
# devflow_run_sharded_python_test for what each mode means — and only the meta-test's
# `run-module.sh --heavy-units smoke` selects the bounded one. An unset value forwards as
# empty, which the driver defaults to `full`, so a runner that sets nothing runs everything.
devflow_run_sharded_python_test \
  "#810 pin-corpus authoring gate: focused Python tests pass" \
  "$LIB/test/test_pin_corpus_lint.py" \
  "$_HPG_PIN_LINT_SHARDS" \
  "${MODULE_HEAVY_UNIT_MODE-}"
# The module-driven-only invariant for this suite — no run.sh invocation, exactly
# one driving module file — is now asserted generically for every
# MODULE_DRIVEN_SUITES member by scan_routing_violations in
# lib/test/test_module_runner.py (issue #867), driven from the tuple itself.
#
# The per-file assertion that used to sit here is retired for a TRADE, not a pure
# superset. Broader: the claim now covers every module-driven suite instead of
# this one, adds the exactly-one-owning-module direction, and extends the search
# domain to lib/test/modules/*.sh and lib/test/module-harness.sh — the residual
# the retired assertion named as its own. Narrower: it matches the $LIB-anchored
# quoted invocation shape, so a run.sh line spelling the path some other way
# (unquoted, via ${LIB}, or repo-relative) is a NEW accepted residual the retired
# basename grep would have caught. That narrowing is what buys immunity to a bare
# comment mention, which the basename grep could not distinguish from a driver.
# Neither guard reaches a driver invoked from lib/test/run-module.sh.
rm -rf "$_HPG_PIN_LINT_SHARDS"

# ────────────────────────────────────────────────────────────────────────────
echo "#810 red-on-removal retirement manifest"
# ────────────────────────────────────────────────────────────────────────────
# The retirement census is a permanent executable contract: one test regenerates
# the exact 113-call historical population and its dispositions from the frozen
# source revision; the other proves the current classifier corpus remains closed.
_HPG_RETIREMENT_OUT="$(mktemp "$_hpg_tmp_root/retirement-manifest-unit.XXXXXX")" || {
  printf 'could not allocate the #810 retirement-manifest unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test \
  "#810 red-on-removal retirement manifest: focused Python tests pass" \
  "$LIB/test/test_red_on_removal_retirement_manifest.py" \
  "$_HPG_RETIREMENT_OUT"
rm -f "$_HPG_RETIREMENT_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "#810 residual pin-retirement manifests"
# ────────────────────────────────────────────────────────────────────────────
# This one focused driver verifies both the historical 242-site residual-prose
# contract and the 141-site residual-required-copy retirement contract, including
# their frozen selectors, retained boundary adjudications, and current realizations.
_HPG_RESIDUAL_PROSE_OUT="$(mktemp "$_hpg_tmp_root/residual-prose-manifest-unit.XXXXXX")" || {
  printf 'could not allocate the #810 residual-prose manifest unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test \
  "#810 residual pin-retirement manifests: focused Python tests pass" \
  "$LIB/test/test_residual_prose_retirement_manifest.py" \
  "$_HPG_RESIDUAL_PROSE_OUT"
rm -f "$_HPG_RESIDUAL_PROSE_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "#985 opt-in suite wall-clock profiler (profile-suite.py)"
# ────────────────────────────────────────────────────────────────────────────
# The profiler is an opt-in maintainer diagnostic — lib/test/run.sh never invokes it —
# so nothing in the suite exercised its parsing/attribution layer until issue #985. Its
# focused unit tests are self-contained: the three regexes, the feed/close attribution
# ledger, the report's malformed-input degrade contract and the signal-status
# translation all run over synthetic fixtures plus one real short-lived child process.
# Shared runner, for the reasons stated in the #527 block above.
_HPG_PROFILE_SUITE_OUT="$(mktemp "$_hpg_tmp_root/profile-suite-unit.XXXXXX")" || {
  printf 'could not allocate the #985 profile-suite unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test "#985 suite profiler: focused Python tests pass" \
  "$LIB/test/test_profile_suite.py" "$_HPG_PROFILE_SUITE_OUT"
rm -f "$_HPG_PROFILE_SUITE_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "issue #591: coverage-map ratchet guard"
# ────────────────────────────────────────────────────────────────────────────
# Live-tree ratchet: the guard enumerates git-tracked depth-1 lib/scripts units
# and cross-references lib/test/modules/coverage-map.json + the registry. A new code
# unit shipped without a coverage decision — or a stale/misfiled/wrong-shape map —
# turns THIS suite RED (git + python3 only; guard-class 2). Its arms are exercised
# with synthetic fixtures by test_coverage_map_guard.py below.
COVERAGE_GUARD_OUT="$(python3 "$LIB/test/coverage_map_guard.py" "$LIB/.." 2>&1)"
COVERAGE_GUARD_RC=$?
assert_eq "#591 coverage-map guard: shipped tree + map is clean" "0" "$COVERAGE_GUARD_RC"
[ "$COVERAGE_GUARD_RC" -eq 0 ] || while IFS= read -r _cg_line || [ -n "$_cg_line" ]; do printf '    %s\n' "$_cg_line"; done <<< "$COVERAGE_GUARD_OUT"
# Reuse the shared focused-Python-test runner (module-harness.sh, sourced above)
# rather than re-implementing its capture/assert/indent idiom — it also applies the
# PYTHON_COLORS=0 determinism guard the hand-rolled form dropped.
_CG_UNIT_OUT="$(mktemp "$_hpg_tmp_root/cg-unit.XXXXXX")" || {
  printf 'could not allocate the #591 coverage-map unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test "#591 coverage-map guard: focused Python tests pass" \
  "$LIB/test/test_coverage_map_guard.py" "$_CG_UNIT_OUT"
rm -f "$_CG_UNIT_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "issue #1194: coverage-map merge tooling (JSON-aware driver + retention check)"
# ────────────────────────────────────────────────────────────────────────────
# The coverage map is two large string-sorted JSON objects, so two branches that each
# ADD a distinct adjacent key conflict textually and a take-one-side resolution silently
# drops the other's entry. Two mechanisms close the class: a JSON-aware git merge driver
# (unions the objects per key, conflicts only on a genuine same-key divergence) and a
# CI-side key-retention check (fails on a key/content dropped relative to the merge base,
# covering the 30-odd non-derivable run_sh_blocks keys no coverage arm inspects). The
# focused test drives the driver against REAL offline `git merge`s (registering the driver
# in each throwaway repo's own local config, never the developer's global config) and the
# retention core over every loss shape, with the AC5 mutation arms recorded in-test.
_CG_MERGE_OUT="$(mktemp "$_hpg_tmp_root/cg-merge-unit.XXXXXX")" || {
  printf 'could not allocate the #1194 coverage-map merge unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test "#1194 coverage-map merge tooling: focused Python tests pass" \
  "$LIB/test/test_coverage_map_merge.py" "$_CG_MERGE_OUT"
rm -f "$_CG_MERGE_OUT"

# ────────────────────────────────────────────────────────────────────────────
echo "issue #1287: assertion-floor retention check (lowered floor is a declared act)"
# ────────────────────────────────────────────────────────────────────────────
# A test module's assertion floor lives in two coupled sites — `minimum_assertions` in
# the flight-recorder registry and the run.sh call-site literal. The suite enforces they
# AGREE and that a tally is not BELOW them, but only the `exact`-policy modules get a
# measured equality (reconcile-module-floors.py / test_module_runner.py). For the modules
# carrying no `assertion_floor_policy` — named by that property, never counted, since the
# population changes as modules are added and re-policed — a coordinated LOWERING of both
# sites is green everywhere, silently shedding coverage. The CI-side diff-time gate (assertion-floor-retention-check.py) makes
# a decrease a declared act, for EVERY registered module. The focused test drives its pure
# core (detect_decreases / classify_outcome) over every decrease, retirement,
# malformed-comparand, escape-hatch and arm-order shape, plus the CLI end-to-end against a
# real offline git repository.
_AFR_OUT="$(mktemp "$_hpg_tmp_root/afr-unit.XXXXXX")" || {
  printf 'could not allocate the #1287 assertion-floor retention unit-test capture\n' >&2
  return 1
}
devflow_run_focused_python_test "#1287 assertion-floor retention check: focused Python tests pass" \
  "$LIB/test/test_assertion_floor_retention.py" "$_AFR_OUT"
rm -f "$_AFR_OUT"

# ── Planted-defect positive control (issue #707 AC) ──────────────────────────
# #719: describe the two assertions above ACCURATELY. The FIRST — the shipped-tree
# clean check (`#591 coverage-map guard: shipped tree + map is clean`) — is a
# clean-tree assertion that on its own cannot distinguish "the guard verified a
# clean tree" from "the guard silently reported nothing", because a live green tells
# the reader nothing about whether the guard could still observe a defect. The
# SECOND — the focused unit test `test_coverage_map_guard.py` — is NOT in that
# position: it already carries planted-defect arms over synthetic fixtures (as the
# control below it does), so it does distinguish the two states for the guard's arms.
# This control closes the remaining gap for the module's LIVE-TREE path specifically —
# it plants a real coverage-map drift and requires the module to observe it. The mutation is
# applied ONLY to a synthetic git repository under this module's private fixture
# root; the shipped tree and its tracked coverage-map are never written to (the
# in-place mutation hazard of issues #201/#218). The pair is deliberate: the
# undrifted fixture must be CLEAN, so the RED below is attributable to the planted
# drift rather than to fixture noise.
_hpg_cg_fixture="$_hpg_tmp_root/cg-planted"
mkdir -p "$_hpg_cg_fixture/lib/test/modules" "$_hpg_cg_fixture/scripts"
: > "$_hpg_cg_fixture/lib/planted-drift.sh"
: > "$_hpg_cg_fixture/lib/test/run.sh"
printf '%s\n' '{"schema_version": 1, "test_modules": {}}' \
  > "$_hpg_cg_fixture/scripts/workflow-flight-recorder-registry.json"
# One template for both arms, parameterized on the ONLY field that differs (`files`).
# Two hand-written copies of the map schema would let the control arm and the drift arm
# diverge in some other key, which would make the control pass — or fail — for a reason
# unrelated to the planted drift, defeating its whole purpose.
_hpg_write_map() {  # files-object -> writes the fixture's coverage map in CANONICAL form
  # Canonical serialization (issue #1065): the guard now asserts the on-disk map is
  # byte-identical to `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)`
  # + one trailing newline (arm 11). A raw single-line printf would trip that arm and
  # break the #707 clean control below, so the template is re-serialized canonically.
  printf '{"schema_version": 1, "files": %s, "run_sh_blocks": {}, "non_code_exempt": ["scripts/workflow-flight-recorder-registry.json", "lib/test/modules/coverage-map.json"], "exempt_subtrees": ["lib/test/"], "generated_by": "harness-python-guards planted-defect fixture"}\n' \
    "$1" | python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(sys.stdin), indent=2, sort_keys=True, ensure_ascii=False)+"\n")' \
    > "$_hpg_cg_fixture/lib/test/modules/coverage-map.json"
}
# Undrifted map: the planted unit is listed, so the guard must report nothing.
_hpg_write_map '{"lib/planted-drift.sh": {"owner": "unmodularized", "note": ""}}'
# `git ls-files` is an index read, so staging is enough — no commit, no identity
# config, no history. A fixture whose git setup fails must not silently degrade
# into a vacuous control, so the setup outcome is asserted before the arms run.
# Ambient git configuration is neutralized: a global `core.excludesFile` matching the
# planted path, or an `init.templateDir`, would change what `git ls-files` reports WITHOUT
# changing either command's exit status — the drift arm would then pass for the wrong
# reason. And the setup assertion checks the OUTCOME the arms depend on (the planted unit
# is actually tracked), never merely that the commands exited 0 (guard-class 1).
_hpg_cg_setup=fail
git -c core.excludesFile=/dev/null -c init.templateDir= -C "$_hpg_cg_fixture" init -q >/dev/null 2>&1 \
  && git -c core.excludesFile=/dev/null -C "$_hpg_cg_fixture" add -A >/dev/null 2>&1 \
  && case "$(git -C "$_hpg_cg_fixture" ls-files)" in *"lib/planted-drift.sh"*) _hpg_cg_setup=ok ;; esac
assert_eq "#707 planted-defect control: fixture repository was created and the planted unit is tracked" "ok" "$_hpg_cg_setup"
_hpg_cg_clean_out="$(python3 "$LIB/test/coverage_map_guard.py" "$_hpg_cg_fixture" 2>&1)"
_hpg_cg_clean_rc=$?
assert_eq "#707 planted-defect control: the undrifted fixture is clean (control arm)" "0" "$_hpg_cg_clean_rc"
assert_eq "#707 planted-defect control: the undrifted fixture reports no violation" "" "$_hpg_cg_clean_out"
# Plant the drift: drop the tracked unit from `files`, which is exactly the
# ratchet arm the live-tree invocation above exists to enforce.
_hpg_write_map '{}'
_hpg_cg_drift_out="$(python3 "$LIB/test/coverage_map_guard.py" "$_hpg_cg_fixture" 2>&1)"
_hpg_cg_drift_rc=$?
assert_eq "#707 planted-defect control: the planted coverage-map drift turns the guard RED" "yes" \
  "$([ "$_hpg_cg_drift_rc" -ne 0 ] && echo yes || echo no)"
assert_eq "#707 planted-defect control: the RED names the drifted unit" "yes" \
  "$(case "$_hpg_cg_drift_out" in *"lib/planted-drift.sh"*) echo yes ;; *) echo no ;; esac)"

# ── Arm 11 canonical-form positive control (issue #1065) ─────────────────────
# The guard now asserts the on-disk map is byte-identical to its canonical
# serialization, so ordering/formatting drift (a merge-conflict resolution, a hand
# edit) fails at the point of introduction instead of being silently rewritten later
# by an unrelated author's --fix. Same fixture discipline as #707: a canonically-
# serialized map must be CLEAN, so the RED is attributable to the planted drift rather
# than fixture noise. The planted unit is re-listed so `files` is complete and only the
# SERIALIZATION differs between the two arms — the drift the arm exists to catch leaves
# the parsed value unchanged, so every presence/ownership arm still passes.
_hpg_write_map '{"lib/planted-drift.sh": {"owner": "unmodularized", "note": ""}}'
_hpg_cg_canon_out="$(python3 "$LIB/test/coverage_map_guard.py" "$_hpg_cg_fixture" 2>&1)"
_hpg_cg_canon_rc=$?
assert_eq "#1065 canonical-form control: a canonically-serialized map is clean (control arm)" "0" "$_hpg_cg_canon_rc"
assert_eq "#1065 canonical-form control: the canonical fixture reports no violation" "" "$_hpg_cg_canon_out"
# Plant serialization drift: rewrite the SAME parsed value with non-canonical bytes
# (compact, no indent, no trailing newline). `git ls-files` is unaffected (the path
# stays tracked) and the guard reads the working-tree bytes, so only arm 11 can catch it.
python3 -c 'import json,sys; p=sys.argv[1]; v=json.load(open(p,encoding="utf-8")); open(p,"w",encoding="utf-8").write(json.dumps(v,sort_keys=True,ensure_ascii=False))' \
  "$_hpg_cg_fixture/lib/test/modules/coverage-map.json"
_hpg_cg_canon_drift_out="$(python3 "$LIB/test/coverage_map_guard.py" "$_hpg_cg_fixture" 2>&1)"
_hpg_cg_canon_drift_rc=$?
assert_eq "#1065 canonical-form control: non-canonical serialized bytes turn the guard RED" "yes" \
  "$([ "$_hpg_cg_canon_drift_rc" -ne 0 ] && echo yes || echo no)"
assert_eq "#1065 canonical-form control: the RED names arm 11" "yes" \
  "$(case "$_hpg_cg_canon_drift_out" in *"[arm11]"*) echo yes ;; *) echo no ;; esac)"
rm -rf "$_hpg_cg_fixture"

# ────────────────────────────────────────────────────────────────────────────
echo "implement run evaluation instruments (issue #2006)"
# ────────────────────────────────────────────────────────────────────────────
# Without these four drivers the test files exist and pass by hand but the SUITE
# never runs them, so a regression in any of the five instruments ships green.
_ire_out="$(mktemp -d)"
devflow_run_focused_python_test "implement run evaluation: derive-run-profile focused Python tests pass" \
  "$LIB/test/test_derive_run_profile.py" "$_ire_out/derive.out"
devflow_run_focused_python_test "implement run evaluation: implement-timeline focused Python tests pass" \
  "$LIB/test/test_implement_timeline.py" "$_ire_out/timeline.out"
devflow_run_focused_python_test "implement run evaluation: implement-run-report focused Python tests pass" \
  "$LIB/test/test_implement_run_report.py" "$_ire_out/report.out"
devflow_run_focused_python_test "implement run evaluation: implement-benchmark focused Python tests pass" \
  "$LIB/test/test_implement_benchmark.py" "$_ire_out/benchmark.out"
rm -rf "$_ire_out"

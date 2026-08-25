# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable Tier-1 rename/migration contract module (issue #1002).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first (which defines the namespaced module pin API:
# devflow_module_pin_count / devflow_module_pin_unique / devflow_module_pin_present).
# This module uses assert_eq plus the `_t1_*` domain-private helpers defined below —
# it references NO monolith helper. The module owns its private fixture root and
# cleanup; it never invokes the runner or the full-suite boundary. The inventory in
# tier1-rename-migration.inventory.md records the module's provenance. Modules may
# not self-skip.
# The `trap _t1_cleanup EXIT` below relies on a sourcing contract: both callers
# (module-harness.sh's full-suite boundary and run-module.sh) source this module
# inside a ( ... ) subshell, so the trap fires at subshell exit and cannot clobber
# the runner's own EXIT handling. Do not source this module directly in a runner's
# top-level shell without restoring the trap.
#
# WHAT THIS MODULE OWNS. The subjects of issue #1002's Tier 1 migration:
#   lib/rename-map.json                 the single source of the rename map
#   lib/resolve-state-dir.sh + lib/state_dir.py
#                                       the state-directory contract (a coupled pair)
#   scripts/config-get.sh               the superseded-key probe
#   scripts/scaffold-config.sh          the config-key migration, its gate, the guard
#   scripts/migrate-consumer-tier1.sh   the all-or-nothing consumer migration
# Every assertion is behavioural: a helper is driven file-in/file-out over a fixture
# consumer tree and judged on its exit code, its emitted report, and the resulting
# BYTES. There is no wording-only pin here (issues #375/#666/#810).

T1_MAP="$LIB/rename-map.json"
T1_STATE_SH="$LIB/resolve-state-dir.sh"
# The python sibling (lib/state_dir.py) is imported through PYTHONPATH="$LIB"
# rather than invoked by path, so it needs no path variable here.
T1_CFGGET="$LIB/../scripts/config-get.sh"
T1_SCAFFOLD="$LIB/../scripts/scaffold-config.sh"
T1_MIGRATE="$LIB/../scripts/migrate-consumer-tier1.sh"
T1_EXAMPLE="$LIB/../.prflow/config.example.json"
T1_SCHEMA="$LIB/../.prflow/config.schema.json"

_t1_tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-tier1-rename.XXXXXX")" || {
  printf 'could not allocate tier1-rename-migration fixture\n' >&2
  return 1
}
_t1_cleanup() {
  chmod -R u+w "$_t1_tmp_root" 2>/dev/null || true
  rm -rf "$_t1_tmp_root"
}
trap _t1_cleanup EXIT

# A fresh fixture repo root. Every fixture lives under the module's own temp root, so
# no assertion here can reach the live checkout. `mktemp -d` rather than an incrementing
# counter: this helper is always called through a command substitution, whose subshell
# would discard a counter increment and hand every fixture the SAME directory — the
# fixtures would then contaminate each other and the failures would read as defects in
# the code under test.
_t1_root() {
  mktemp -d "$_t1_tmp_root/rXXXXXX"
}

# Content-addressed whole-tree digest, .git pruned. Byte-identity is asserted over
# BYTES rather than over a list of paths, because a partial write would still satisfy
# a path list. The walk is rooted at the module's own fixture root, never at the
# repository root.
# tree-walk-ok: enumerates a module-owned mktemp fixture tree (never the repository
# root), so it cannot descend into a sibling git worktree; issue #711's hazard does
# not arise and git ls-files cannot see an unversioned fixture.
_t1_snap() {
  ( cd "$1" || return 0
    # The walk is confined by the `cd` above to the module's own mktemp fixture root.
    _t1_paths="$(find . -path ./.git -prune -o \( -type f -o -type l \) -print)"  # tree-walk-ok: rooted at a module-owned mktemp fixture tree, never the repository root, so it cannot descend into a sibling git worktree (issue #711) and git ls-files cannot see an unversioned fixture
    printf '%s\n' "$_t1_paths" \
      | LC_ALL=C sort \
      | while IFS= read -r f; do
          [ -n "$f" ] || continue
          printf '%s %s\n' "$f" "$(shasum "$f" 2>/dev/null | cut -d' ' -f1)"
        done | shasum | cut -d' ' -f1 ) 2>/dev/null
}

# yes/no over "does this text contain that literal", so an assertion reads as a
# behaviour rather than as a grep.
_t1_has() {
  case "$1" in
    *"$2"*) printf 'yes' ;;
    *) printf 'no' ;;
  esac
}

# A consumer repository on the SUPERSEDED layout, carrying one of every artifact the
# atomic unit touches plus a frozen record whose bytes must survive.
_t1_old_consumer() {
  local r; r="$(_t1_root)"
  mkdir -p "$r/.devflow/vendor/devflow/scripts" "$r/.devflow/learnings" \
           "$r/.github/workflows" "$r/.claude-plugin"
  cat > "$r/.devflow/config.json" <<'T1_CFG'
{
  "base_branch": "main",
  "devflow": { "allowed_bots": "botA", "workpad_marker": "<!-- devflow:workpad -->" },
  "devflow_implement": { "effort": "low" },
  "devflow_review": { "max_iterations": 9 },
  "devflow_version": "0123456789abcdef0123456789abcdef01234567",
  "workflows": { "devflow": true, "devflow-review": false }
}
T1_CFG
  printf 'echo vendored\n' > "$r/.devflow/vendor/devflow/scripts/x.sh"
  printf '{"frozen":"record"}\n' > "$r/.devflow/learnings/r.jsonl"
  printf 'run: .devflow/vendor/devflow/scripts/x.sh\n' > "$r/.github/workflows/devflow.yml"
  printf '{"plugins":[{"name":"prflow","source":"./.devflow/vendor/devflow"}]}\n' \
    > "$r/.claude-plugin/marketplace.json"
  printf '%s' "$r"
}

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 A. the rename map is the single source every site resolves against"
# ────────────────────────────────────────────────────────────────────────────
# The map is machine-readable and every consuming site agrees with it. A site that
# carried its own literal copy would drift silently, which is the defect issue #988's
# one-owner criterion exists to stop.
assert_eq "#1002 rename map parses as JSON" "yes" \
  "$(python3 -c 'import json,sys; json.load(open(sys.argv[1])); print("yes")' "$T1_MAP" 2>/dev/null || printf 'no')"

_t1_map_keys="$(python3 -c '
import json,sys
m=json.load(open(sys.argv[1]))
print(" ".join(sorted(m["config_keys"])))' "$T1_MAP" 2>/dev/null)"
assert_eq "#1002 the map declares exactly the seven superseded top-level keys" \
  "devflow devflow_implement devflow_retrospective devflow_review devflow_review_and_fix devflow_runner devflow_version" \
  "$_t1_map_keys"

assert_eq "#1002 every mapped target is the prflow_ sibling of its source" "ok" \
  "$(python3 -c '
import json,sys
m=json.load(open(sys.argv[1]))["config_keys"]
bad=[k for k,v in m.items() if v != k.replace("devflow","prflow",1)]
print("ok" if not bad else "bad:"+",".join(bad))' "$T1_MAP" 2>/dev/null)"

# The two state-directory resolvers are a coupled pair, and both are pinned against
# the map. Driving all three is what makes the coupling enforced rather than asserted.
# shellcheck source=../../resolve-state-dir.sh
_t1_sh_names="$( . "$T1_STATE_SH" >/dev/null 2>&1; printf '%s %s' \
  "${PRFLOW_STATE_DIR_CURRENT:-UNSET}" "${PRFLOW_STATE_DIR_SUPERSEDED:-UNSET}")"
_t1_map_names="$(python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))["paths"]["state_dir"]
print(p["current"], p["superseded"])' "$T1_MAP" 2>/dev/null)"
assert_eq "#1002 the SHELL state-dir resolver agrees with the rename map" \
  "$_t1_map_names" "$_t1_sh_names"

_t1_py_names="$(PYTHONPATH="$LIB" python3 -c '
import state_dir
print(state_dir.STATE_DIR_CURRENT, state_dir.STATE_DIR_SUPERSEDED)' 2>/dev/null)"
assert_eq "#1002 the PYTHON state-dir resolver agrees with the rename map" \
  "$_t1_map_names" "$_t1_py_names"

assert_eq "#1002 the two state-dir resolvers agree with EACH OTHER (coupled pair)" \
  "$_t1_sh_names" "$_t1_py_names"

_t1_vendor="$(python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))["paths"]["vendor_dir"]
print(p["superseded"], p["current"])' "$T1_MAP" 2>/dev/null)"
assert_eq "#1002 the map declares the vendored-path rename at both levels" \
  ".devflow/vendor/devflow .prflow/vendor/prflow" "$_t1_vendor"

# #1041: the two workflows.* sub-keys are NO LONGER frozen — they migrate behind the
# scaffold freshness gate via the map's workflows_config_keys section. frozen.config_keys
# is now empty (it still exists so the enumerated frozen set has a home), and the two
# renames live in workflows_config_keys.
assert_eq "#1041 the map no longer freezes the workflows.* config sub-keys" "yes" \
  "$(python3 -c '
import json,sys
f=json.load(open(sys.argv[1]))["frozen"]["config_keys"]
print("yes" if f==[] else "no:"+",".join(f))' "$T1_MAP" 2>/dev/null)"
assert_eq "#1041 the map declares the two workflows.* renames in workflows_config_keys" \
  "devflow->prflow devflow-review->prflow-review" \
  "$(python3 -c '
import json,sys
w=json.load(open(sys.argv[1]))["workflows_config_keys"]
print(" ".join(f"{k}->{v}" for k,v in w.items()))' "$T1_MAP" 2>/dev/null)"

assert_eq "#1002 the map declares a four-member atomic unit" "4" \
  "$(python3 -c '
import json,sys
print(len(json.load(open(sys.argv[1]))["atomic_unit"]))' "$T1_MAP" 2>/dev/null)"

assert_eq "#1002 the atomic unit names exactly the four members the migration applies" \
  "marketplace-source-rewrite state-dir-move version-pin-advance workflow-content-rewrite" \
  "$(python3 -c '
import json,sys
print(" ".join(sorted(r["id"] for r in json.load(open(sys.argv[1]))["atomic_unit"])))' "$T1_MAP" 2>/dev/null)"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 B. the shipped config vocabulary carries no superseded top-level key"
# ────────────────────────────────────────────────────────────────────────────
for _t1_f in "$T1_SCHEMA" "$T1_EXAMPLE"; do
  _t1_label="${_t1_f##*/}"
  assert_eq "#1002 $_t1_label declares no top-level property beginning 'devflow'" "none" \
    "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
props = d.get("properties", d) if sys.argv[2]=="schema" else d
bad=[k for k in props if k.startswith("devflow")]
print(",".join(bad) if bad else "none")' "$_t1_f" "$( [ "$_t1_label" = "config.schema.json" ] && echo schema || echo plain )" 2>/dev/null)"
done

# #1041: the workflows block now declares the RENAMED sub-keys. Renaming these was the
# single most damaging edit available (`.workflows.devflow // false` silently disables
# everything), which is why they moved only behind the fail-closed freshness gate and in
# lockstep with the shipped workflows' inline jq — never as a bare sweep.
assert_eq "#1041 config.schema.json declares the renamed workflows.{prflow,prflow-review}" \
  "prflow prflow-review" \
  "$(python3 -c '
import json,sys
print(" ".join(json.load(open(sys.argv[1]))["properties"]["workflows"]["properties"]))' "$T1_SCHEMA" 2>/dev/null)"

assert_eq "#1041 config.example.json carries the renamed workflows.prflow toggle" "yes" \
  "$(python3 -c '
import json,sys
w=json.load(open(sys.argv[1])).get("workflows",{})
print("yes" if "prflow" in w and "prflow-review" in w and "devflow" not in w else "no")' "$T1_EXAMPLE" 2>/dev/null)"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 C. state-directory resolution and its LOUD transitional fallback"
# ────────────────────────────────────────────────────────────────────────────
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>"$_t1_tmp_root/e1" )"
assert_eq "#1002 shell: the canonical directory resolves when present" "$_t1_r/.prflow" "$_t1_out"
assert_eq "#1002 shell: resolving the canonical directory emits NO breadcrumb" "" \
  "$(cat "$_t1_tmp_root/e1")"

_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.devflow"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>"$_t1_tmp_root/e2" )"
assert_eq "#1002 shell: falls back to the superseded directory when only it is present" \
  "$_t1_r/.devflow" "$_t1_out"
assert_eq "#1002 shell: the superseded fallback breadcrumbs, naming the remedy" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/e2")" '/prflow:init')"
assert_eq "#1002 shell: the breadcrumb names the superseded directory it read" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/e2")" '.devflow/')"

_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow" "$_t1_r/.devflow"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>"$_t1_tmp_root/e3" )"
assert_eq "#1002 shell: with BOTH present the canonical directory wins" "$_t1_r/.prflow" "$_t1_out"
assert_eq "#1002 shell: with BOTH present there is no breadcrumb (nothing was superseded)" "" \
  "$(cat "$_t1_tmp_root/e3")"

_t1_r="$(_t1_root)"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>"$_t1_tmp_root/e4" )"
assert_eq "#1002 shell: with NEITHER present the canonical path is handed back" \
  "$_t1_r/.prflow" "$_t1_out"
# A fresh repository is not a stale one. Breadcrumbing here would train an operator to
# ignore the one line that matters.
assert_eq "#1002 shell: a fresh repository earns NO breadcrumb" "" "$(cat "$_t1_tmp_root/e4")"

# A plain FILE or a dangling symlink at either name is not a state directory.
_t1_r="$(_t1_root)"; : > "$_t1_r/.prflow"; mkdir -p "$_t1_r/.devflow"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>/dev/null )"
assert_eq "#1002 shell: a FILE at the canonical name is not a state directory" \
  "$_t1_r/.devflow" "$_t1_out"

_t1_r="$(_t1_root)"; ln -s "$_t1_r/nowhere" "$_t1_r/.prflow"; mkdir -p "$_t1_r/.devflow"
# shellcheck source=../../resolve-state-dir.sh
_t1_out="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>/dev/null )"
assert_eq "#1002 shell: a DANGLING symlink at the canonical name is not a state directory" \
  "$_t1_r/.devflow" "$_t1_out"

# The Python sibling answers identically on every row — that is what makes the pair
# coupled rather than merely parallel.
for _t1_case in canonical superseded both neither; do
  _t1_r="$(_t1_root)"
  case "$_t1_case" in
    canonical)  mkdir -p "$_t1_r/.prflow"; _t1_want="$_t1_r/.prflow" ;;
    superseded) mkdir -p "$_t1_r/.devflow"; _t1_want="$_t1_r/.devflow" ;;
    both)       mkdir -p "$_t1_r/.prflow" "$_t1_r/.devflow"; _t1_want="$_t1_r/.prflow" ;;
    neither)    _t1_want="$_t1_r/.prflow" ;;
  esac
  # shellcheck source=../../resolve-state-dir.sh
  _t1_sh="$( . "$T1_STATE_SH" >/dev/null 2>&1; prflow_state_dir "$_t1_r" 2>/dev/null )"
  _t1_py="$(PYTHONPATH="$LIB" python3 -c '
import state_dir,sys
sys.stdout.write(state_dir.resolve_state_dir(sys.argv[1]))' "$_t1_r" 2>/dev/null)"
  assert_eq "#1002 python: $_t1_case resolves to the same directory the shell chose" \
    "$_t1_want" "$_t1_py"
  assert_eq "#1002 coupled pair: shell and python agree on the $_t1_case row" \
    "$_t1_sh" "$_t1_py"
done

_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.devflow"
_t1_pyerr="$(PYTHONPATH="$LIB" python3 -c '
import state_dir,sys
state_dir.resolve_state_dir(sys.argv[1])' "$_t1_r" 2>&1 >/dev/null)"
assert_eq "#1002 python: the superseded fallback breadcrumbs, naming the remedy" "yes" \
  "$(_t1_has "$_t1_pyerr" '/prflow:init')"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 D. config-get.sh superseded-key probe (absent vs present-and-empty)"
# ────────────────────────────────────────────────────────────────────────────
# The resolver collapses {absent, null, present-and-empty} onto one empty stdout, so a
# breadcrumb sited at that gate would fire on a key a consumer deliberately set to "".
# The probe re-reads and distinguishes them. These rows are the six-shape config matrix
# the repository's best-effort-parser convention requires, applied to the superseded key.
_t1_cfg() { printf '%s' "$2" > "$_t1_tmp_root/cfg$1.json"; printf '%s' "$_t1_tmp_root/cfg$1.json"; }

_t1_f="$(_t1_cfg 1 '{"devflow":{"allowed_bots":"botA"}}')"
_t1_out="$("$T1_CFGGET" .prflow.allowed_bots FALLBACK "$_t1_f" 2>"$_t1_tmp_root/pe1")"; _t1_rc=$?
assert_eq "#1002 probe: absent new key + present superseded key emits the breadcrumb" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe1")" 'superseded counterpart')"
assert_eq "#1002 probe: the breadcrumb names BOTH the requested and the superseded key" "yes yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe1")" '.prflow.allowed_bots') $(_t1_has "$(cat "$_t1_tmp_root/pe1")" '.devflow.allowed_bots')"
assert_eq "#1002 probe: the breadcrumb names the remedy" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe1")" '/prflow:init')"
assert_eq "#1002 probe: the default is still emitted and the exit code is unchanged" "FALLBACK 0" \
  "$_t1_out $_t1_rc"

# The valid-falsy rows. A present new key holding "", false, 0 or null is a deliberate
# consumer value, not an un-migrated config, and must NOT breadcrumb.
for _t1_val in '""' 'false' '0' 'null'; do
  _t1_f="$(_t1_cfg 2 "{\"prflow\":{\"allowed_bots\":$_t1_val},\"devflow\":{\"allowed_bots\":\"botA\"}}")"
  "$T1_CFGGET" .prflow.allowed_bots FALLBACK "$_t1_f" >/dev/null 2>"$_t1_tmp_root/pe2"
  assert_eq "#1002 probe: a new key present and holding $_t1_val emits NO breadcrumb" "" \
    "$(cat "$_t1_tmp_root/pe2")"
done

# Negative control: the breadcrumb is conditioned on the SUPERSEDED key's presence, not
# on every miss. Without this row the probe could fire on any absent key and still pass.
_t1_f="$(_t1_cfg 3 '{"docs":{"internal":"D"}}')"
"$T1_CFGGET" .prflow.allowed_bots FALLBACK "$_t1_f" >/dev/null 2>"$_t1_tmp_root/pe3"
assert_eq "#1002 probe: both keys absent emits NO breadcrumb (negative control)" "" \
  "$(cat "$_t1_tmp_root/pe3")"

# First-segment-only mapping: no deeper segment is rewritten.
_t1_f="$(_t1_cfg 4 '{"devflow_implement":{"stall_backstop":{"enabled":true}}}')"
"$T1_CFGGET" .prflow_implement.stall_backstop.enabled X "$_t1_f" >/dev/null 2>"$_t1_tmp_root/pe4"
assert_eq "#1002 probe: only the FIRST dot-path segment is mapped" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe4")" '.devflow_implement.stall_backstop.enabled')"

# A deeper segment that happens to contain the old brand is not a superseded key.
_t1_f="$(_t1_cfg 5 '{"prflow":{"devflow_note":"x"}}')"
"$T1_CFGGET" .prflow.devflow_note MISS "$_t1_f" >/dev/null 2>"$_t1_tmp_root/pe5"
assert_eq "#1002 probe: a deeper segment carrying the old brand is not rewritten" "" \
  "$(cat "$_t1_tmp_root/pe5")"

# Wrong-type and malformed rows: a diagnostic must never break the read it diagnoses.
_t1_f="$(_t1_cfg 6 '{"devflow":"a scalar, not an object"}')"
"$T1_CFGGET" .prflow.allowed_bots D "$_t1_f" >/dev/null 2>&1; _t1_rc=$?
assert_eq "#1002 probe: a superseded key holding a scalar still exits 0 with the default" "0" "$_t1_rc"

_t1_f="$(_t1_cfg 7 '["an","array","root"]')"
"$T1_CFGGET" .prflow.allowed_bots D "$_t1_f" >/dev/null 2>&1; _t1_rc=$?
assert_eq "#1002 probe: a non-object config root still exits 0 with the default" "0" "$_t1_rc"

_t1_f="$(_t1_cfg 8 '{bad json')"
"$T1_CFGGET" .prflow.allowed_bots D "$_t1_f" >/dev/null 2>"$_t1_tmp_root/pe8"; _t1_rc=$?
assert_eq "#1002 probe: malformed JSON keeps exit 2 (the documented parse-error code)" "2" "$_t1_rc"
assert_eq "#1002 probe: malformed JSON emits no superseded-key breadcrumb (no key established)" "no" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe8")" 'superseded counterpart')"

# The no-default path: exit 1 AND still breadcrumb. Requires a repo-root-anchored run,
# because the 3-argument form cannot express "config file, no default".
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow"
printf '%s' '{"devflow":{"allowed_bots":"botA"}}' > "$_t1_r/.prflow/config.json"
( cd "$_t1_r" && "$T1_CFGGET" .prflow.allowed_bots ) >/dev/null 2>"$_t1_tmp_root/pe9"; _t1_rc=$?
assert_eq "#1002 probe: the no-default path keeps exit 1" "1" "$_t1_rc"
assert_eq "#1002 probe: the breadcrumb is written on the no-default path too" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe9")" 'superseded counterpart')"

# A key found under its NEW name resolves normally and says nothing.
_t1_f="$(_t1_cfg 9 '{"prflow":{"allowed_bots":"botNEW"}}')"
_t1_out="$("$T1_CFGGET" .prflow.allowed_bots D "$_t1_f" 2>"$_t1_tmp_root/pe10")"; _t1_rc=$?
assert_eq "#1002 probe: a migrated key resolves to its value, exit 0, no breadcrumb" "botNEW 0 " \
  "$_t1_out $_t1_rc $(cat "$_t1_tmp_root/pe10")"

# config-get.sh resolving a consumer still on the superseded DIRECTORY.
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.devflow"
printf '%s' '{"prflow":{"allowed_bots":"legacyBot"}}' > "$_t1_r/.devflow/config.json"
_t1_out="$( cd "$_t1_r" && "$T1_CFGGET" .prflow.allowed_bots NONE 2>"$_t1_tmp_root/pe11" )"
assert_eq "#1002 config-get reads through to the superseded state directory" "legacyBot" "$_t1_out"
assert_eq "#1002 config-get breadcrumbs when it read the superseded state directory" "yes" \
  "$(_t1_has "$(cat "$_t1_tmp_root/pe11")" 'superseded .devflow/ state directory')"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 E. scaffold-config.sh: key migration, its gate, and the anti-graft guard"
# ────────────────────────────────────────────────────────────────────────────
_t1_seven='{"devflow":{"allowed_bots":"botA"},"devflow_implement":{"effort":"low"},"devflow_retrospective":{"min_occurrences":7},"devflow_review":{"max_iterations":9},"devflow_review_and_fix":{"fix_severity_threshold":"critical"},"devflow_runner":{"effort":"low"},"devflow_version":"abc123"}'

# A scaffolder fixture: a repo whose shipped workflows are FRESH, so the gate passes.
_t1_scaffold_root() {
  local r; r="$(_t1_root)"
  mkdir -p "$r/.prflow" "$r/.github/workflows"
  printf '%s' "$1" > "$r/.prflow/config.json"
  printf '%s' "$r"
}

_t1_r="$(_t1_scaffold_root "$_t1_seven")"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
_t1_keys="$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(",".join(sorted(k for k in d if k.startswith(("devflow","prflow")))))' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 scaffolder: with the gate satisfied every superseded key is renamed" \
  "prflow,prflow_implement,prflow_retrospective,prflow_review,prflow_review_and_fix,prflow_runner,prflow_version" \
  "$_t1_keys"
assert_eq "#1002 scaffolder: the consumer VALUES are carried across byte-for-byte" \
  "botA low 7 9 critical low abc123" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d["prflow"]["allowed_bots"], d["prflow_implement"]["effort"],
      d["prflow_retrospective"]["min_occurrences"], d["prflow_review"]["max_iterations"],
      d["prflow_review_and_fix"]["fix_severity_threshold"], d["prflow_runner"]["effort"],
      d["prflow_version"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 scaffolder: it reports one line per migrated key" "7" \
  "$(printf '%s\n' "$_t1_out" | grep -c 'migrated superseded config key')"
assert_eq "#1002 scaffolder: it reports the version pin without gating on it" "yes" \
  "$(_t1_has "$_t1_out" 'plugin version pin is')"

# The GATE. A shipped workflow still reading a superseded name refuses the migration.
_t1_r="$(_t1_scaffold_root "$_t1_seven")"
printf 'run: jq -r ".devflow.allowed_bots"\n' > "$_t1_r/.github/workflows/devflow.yml"
_t1_before="$(shasum "$_t1_r/.prflow/config.json" | cut -d' ' -f1)"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 scaffolder gate: a stale SHIPPED workflow refuses the migration" "yes" \
  "$(_t1_has "$_t1_out" 'NOT migrating superseded config keys')"
assert_eq "#1002 scaffolder gate: the refusal names the stale file" "yes" \
  "$(_t1_has "$_t1_out" 'devflow.yml')"
assert_eq "#1002 scaffolder gate: the refusal names install.sh --apply as the remedy" "yes" \
  "$(_t1_has "$_t1_out" 'install.sh --apply')"
assert_eq "#1002 scaffolder gate: nothing was migrated" "yes" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print("yes" if all(k in d for k in ("devflow","devflow_version")) else "no")' "$_t1_r/.prflow/config.json" 2>/dev/null)"
# THE ANTI-GRAFT GUARD on the refusal path: the deep merge must not create a new-name
# block holding example defaults beside the surviving superseded one. This is the
# dominant silent-revert hazard (#988 finding 1) and the reason the guard keys on the
# ORIGINAL config rather than on whether the migration ran.
assert_eq "#1002 anti-graft: on the REFUSAL path no prflow_* key is grafted" "none" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
g=[k for k in d if k.startswith("prflow")]
print(",".join(sorted(g)) if g else "none")' "$_t1_r/.prflow/config.json" 2>/dev/null)"

# The same guard on the DEGRADED path where jq is unusable.
_t1_r="$(_t1_scaffold_root "$_t1_seven")"
printf 'run: jq -r ".devflow.allowed_bots"\n' > "$_t1_r/.github/workflows/devflow.yml"
_t1_out="$(DEVFLOW_JQ="$_t1_tmp_root/no-such-jq" "$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 anti-graft: with jq unusable the backfill is skipped, and it says so" "yes" \
  "$(_t1_has "$_t1_out" 'no usable jq')"
assert_eq "#1002 anti-graft: on the jq-unusable path no prflow_* key is grafted" "none" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
g=[k for k in d if k.startswith("prflow")]
print(",".join(sorted(g)) if g else "none")' "$_t1_r/.prflow/config.json" 2>/dev/null)"

# NEGATIVE CONTROL for the gated set: a stale RETAINED (unshipped) workflow must NOT
# refuse. install.sh cannot refresh those files, so gating on one would block the
# migration forever. This row is what pins the gated set to the two shipped filenames.
_t1_r="$(_t1_scaffold_root "$_t1_seven")"
printf 'run: .devflow/vendor/devflow/scripts/x.sh\n' > "$_t1_r/.github/workflows/devflow-runner.yml"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 scaffolder gate: a stale RETAINED workflow does NOT refuse the migration" "no" \
  "$(_t1_has "$_t1_out" 'NOT migrating superseded config keys')"
assert_eq "#1002 scaffolder: the retained unshipped workflow is REPORTED by name instead" "yes" \
  "$(_t1_has "$_t1_out" 'devflow-runner.yml is present')"
assert_eq "#1002 scaffolder: the migration proceeded despite the retained file" "yes" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print("yes" if "prflow" in d and "devflow" not in d else "no")' "$_t1_r/.prflow/config.json" 2>/dev/null)"

# The retained-file report fires on EVERY run, including one where the config has
# already migrated — otherwise it falls silent on the run after the one that mattered.
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 scaffolder: the retained-file report persists after the config migrated" "yes" \
  "$(_t1_has "$_t1_out" 'devflow-runner.yml is present')"

# Both-present, new block equal to the shipped example default: the superseded value
# wins and the superseded block goes.
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow" "$_t1_r/.github/workflows"
python3 -c '
import json,sys
ex=json.load(open(sys.argv[1]))
json.dump({"devflow_review":{"max_iterations":42},"prflow_review":ex["prflow_review"]},
          open(sys.argv[2],"w"), indent=2)' "$T1_EXAMPLE" "$_t1_r/.prflow/config.json"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 both-present (example-valued): the SUPERSEDED value wins" "42" \
  "$(python3 -c '
import json,sys
print(json.load(open(sys.argv[1]))["prflow_review"]["max_iterations"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 both-present (example-valued): the superseded block is removed" "False" \
  "$(python3 -c '
import json,sys
print("devflow_review" in json.load(open(sys.argv[1])))' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 both-present (example-valued): the run reports that it did so" "yes" \
  "$(_t1_has "$_t1_out" 'still held the shipped example default')"

# Both-present, new block DIFFERING from the example: a deliberate consumer edit a
# rename must not discard. Neither block changes and the conflict names both exits.
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow" "$_t1_r/.github/workflows"
printf '%s' '{"devflow_review":{"max_iterations":42},"prflow_review":{"max_iterations":99}}' \
  > "$_t1_r/.prflow/config.json"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 both-present (differing): NEITHER block is changed" "42 99" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d["devflow_review"]["max_iterations"], d["prflow_review"]["max_iterations"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 both-present (differing): the conflict is reported" "yes" \
  "$(_t1_has "$_t1_out" 'NOT migrating devflow_review')"
assert_eq "#1002 both-present (differing): the report names BOTH resolutions available" "yes yes" \
  "$(_t1_has "$_t1_out" 'delete the devflow_review block') $(_t1_has "$_t1_out" 'delete the prflow_review block')"

# Idempotency: a config already on the new names is left byte-identical.
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.prflow" "$_t1_r/.github/workflows"
cp "$T1_EXAMPLE" "$_t1_r/.prflow/config.json"
_t1_before="$(shasum "$_t1_r/.prflow/config.json" | cut -d' ' -f1)"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1002 scaffolder: an already-migrated config is left byte-identical" \
  "$_t1_before" "$(shasum "$_t1_r/.prflow/config.json" | cut -d' ' -f1)"
assert_eq "#1002 scaffolder: an already-migrated config produces no migration lines" "0" \
  "$(printf '%s\n' "$_t1_out" | grep -cE 'migrated superseded config key|NOT migrating')"

# The scaffolder operates IN PLACE on a superseded directory rather than scaffolding a
# second one beside it — the worst outcome available here.
_t1_r="$(_t1_root)"; mkdir -p "$_t1_r/.devflow" "$_t1_r/.github/workflows"
printf '%s' '{"devflow":{"allowed_bots":"botA"}}' > "$_t1_r/.devflow/config.json"
"$T1_SCAFFOLD" "$_t1_r" >/dev/null 2>&1
assert_eq "#1002 scaffolder: it does NOT create a second state directory beside a superseded one" "no" \
  "$( [ -d "$_t1_r/.prflow" ] && printf 'yes' || printf 'no' )"
assert_eq "#1002 scaffolder: it migrated the config IN PLACE in the superseded directory" "yes" \
  "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print("yes" if "prflow" in d else "no")' "$_t1_r/.devflow/config.json" 2>/dev/null)"

# ────────────────────────────────────────────────────────────────────────────
echo "#1041 E2. the workflows.* sub-keys migrate behind the SAME freshness gate"
# ────────────────────────────────────────────────────────────────────────────
_t1_wf_workflows() { python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))["workflows"]))' "$1" 2>/dev/null; }
# FRESH shipped workflows (none present -> gate passes): both sub-keys rename and the
# deliberate valid-falsy `false`/`true` toggles are carried across verbatim (AC4, #312).
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":false,"devflow-review":true}}')"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1041 workflows migration: both sub-keys rename and the valid-falsy false/true survive" \
  '{"prflow": false, "prflow-review": true}' "$(_t1_wf_workflows "$_t1_r/.prflow/config.json")"
# AC2/AC3: a STALE shipped workflow whose superseded read is `.workflows.devflow` (the
# #1041 staleness trigger, previously exempted by a `workflows` lookbehind) REFUSES the
# migration and names install.sh --apply; the nested anti-graft guard keeps the consumer's
# valid-falsy toggle from being shadowed by a grafted example default -- so a stale consumer
# is never silently disabled. Asserted end-to-end on the resulting config bytes.
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":false,"devflow-review":true}}')"
printf 'run: jq -r ".workflows.devflow // false"\n' > "$_t1_r/.github/workflows/devflow-implement.yml"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1041 gate: a workflow still reading .workflows.devflow refuses the migration" "yes" \
  "$(_t1_has "$_t1_out" 'NOT migrating superseded config keys')"
assert_eq "#1041 gate: the refusal names install.sh --apply as the remedy" "yes" \
  "$(_t1_has "$_t1_out" 'install.sh --apply')"
assert_eq "#1041 gate: the superseded workflows.* toggles survive unchanged and NO prflow* is grafted (not silently disabled)" \
  '{"devflow": false, "devflow-review": true}' "$(_t1_wf_workflows "$_t1_r/.prflow/config.json")"
# NEGATIVE CONTROL: the SAME config with a FRESH workflow (reads .workflows.prflow) lets
# the migration proceed -- proving the gate is what refused above, not some other block.
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":false,"devflow-review":true}}')"
printf 'run: jq -r ".workflows.prflow // false"\n' > "$_t1_r/.github/workflows/devflow-implement.yml"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1041 gate negative control: a fresh workflow lets the workflows.* migration proceed" \
  '{"prflow": false, "prflow-review": true}' "$(_t1_wf_workflows "$_t1_r/.prflow/config.json")"

# ADVERSARIAL SHAPE MATRIX for the NEW nested code path (CLAUDE.md best-effort-parser
# discipline: the nested migrate_keys("workflows.") and its jq anti-graft twin must not
# detonate or mangle a hand-corruptible workflows block). Fresh workflows so the gate
# passes; every row asserts exit 0 and the correct nested outcome.
_t1_nested_has_prflow() { python3 -c 'import json,sys
w=json.load(open(sys.argv[1])).get("workflows")
print("yes" if isinstance(w,dict) and "prflow" in w else "no")' "$1" 2>/dev/null; }
# (i) non-object workflows (scalar / array / null): both guards (python isinstance, jq
# type=="object") skip it, so it carries through with NO nested migration and NO crash.
for _t1_wfshape in '"nope"' '[1,2]' 'null'; do
  _t1_r="$(_t1_scaffold_root "{\"workflows\":$_t1_wfshape}")"
  _t1_rc=0; "$T1_SCAFFOLD" "$_t1_r" >/dev/null 2>&1 || _t1_rc=$?
  assert_eq "#1041 shape matrix: a non-object workflows ($_t1_wfshape) is exit 0 with no nested migration and no crash" \
    "0|no" "$_t1_rc|$(_t1_nested_has_prflow "$_t1_r/.prflow/config.json")"
done
# (ii) ONLY one sub-key present: it migrates (false preserved) and the OTHER is backfilled
# from the shipped example default (a new key the consumer never set) -- never grafted over
# the migrated one, and never coercing the migrated false.
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":false}}')"
"$T1_SCAFFOLD" "$_t1_r" >/dev/null 2>&1
assert_eq "#1041 shape matrix: a single present sub-key migrates (false preserved); the other backfills from the example" \
  '{"prflow": false, "prflow-review": false}' "$(_t1_wf_workflows "$_t1_r/.prflow/config.json")"
# (iii) nested both-present CONFLICT (new key differs from the shipped example default): a
# deliberate consumer edit the rename must not discard -- neither key changes, the conflict
# is reported naming the nested path.
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":true,"prflow":false}}')"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1041 shape matrix: nested both-present differing is reported as a conflict naming workflows.devflow" "yes" \
  "$(_t1_has "$_t1_out" 'NOT migrating workflows.devflow')"
assert_eq "#1041 shape matrix: nested conflict keeps BOTH sub-keys unchanged (no deliberate edit discarded)" \
  'true|false' \
  "$(python3 -c 'import json,sys;w=json.load(open(sys.argv[1]))["workflows"];print(str(w.get("devflow")).lower()+"|"+str(w.get("prflow")).lower())' "$_t1_r/.prflow/config.json" 2>/dev/null)"
# (iv) nested both-present EXAMPLE-VALUED graft (the migrate_keys second pass, "workflows."
# prefix): the new key equals the shipped example default, so it was grafted, not authored --
# the superseded value wins and is written at the new key's position.
_t1_r="$(_t1_scaffold_root '{"workflows":{"devflow":false,"prflow":true}}')"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1041 shape matrix: nested example-valued graft -> the superseded value wins (prflow=false), devflow dropped" \
  'no|false' \
  "$(python3 -c 'import json,sys;w=json.load(open(sys.argv[1]))["workflows"];print(("yes" if "devflow" in w else "no")+"|"+str(w.get("prflow")).lower())' "$_t1_r/.prflow/config.json" 2>/dev/null)"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 F. migrate-consumer-tier1.sh: the atomic unit"
# ────────────────────────────────────────────────────────────────────────────
# PREVIEW writes nothing. install.sh upgrades are dry-run by default, so this is the
# mode every existing consumer meets first, and a report claiming a migration a
# preview never performed is the failure this row exists to catch.
_t1_r="$(_t1_old_consumer)"; _t1_before="$(_t1_snap "$_t1_r")"
_t1_out="$("$T1_MIGRATE" "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 migrate: a preview exits 0" "0" "$_t1_rc"
assert_eq "#1002 migrate: a preview leaves the repository byte-identical" \
  "$_t1_before" "$(_t1_snap "$_t1_r")"
assert_eq "#1002 migrate: the preview says nothing was written" "yes" \
  "$(_t1_has "$_t1_out" 'nothing was written')"
assert_eq "#1002 migrate: the preview is labelled distinctly from an applied run" "yes no" \
  "$(_t1_has "$_t1_out" 'PREVIEW') $(_t1_has "$_t1_out" 'APPLIED')"
assert_eq "#1002 migrate: the preview enumerates all four members of the atomic unit" "4" \
  "$(printf '%s\n' "$_t1_out" | grep -c 'will migrate')"

# APPLY: every member lands together.
_t1_r="$(_t1_old_consumer)"
_t1_out="$("$T1_MIGRATE" --apply --pin v9.9.9 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 migrate: an apply exits 0" "0" "$_t1_rc"
assert_eq "#1002 migrate: the applied run is labelled distinctly from a preview" "yes no" \
  "$(_t1_has "$_t1_out" 'APPLIED') $(_t1_has "$_t1_out" 'nothing was written')"
assert_eq "#1002 migrate member 1: the state directory moved" "yes yes" \
  "$( [ -d "$_t1_r/.prflow" ] && printf 'yes' || printf 'no' ) $( [ -d "$_t1_r/.devflow" ] && printf 'no' || printf 'yes' )"
assert_eq "#1002 migrate member 1: the inner vendored directory moved too" "yes" \
  "$( [ -d "$_t1_r/.prflow/vendor/prflow" ] && printf 'yes' || printf 'no' )"
assert_eq "#1002 migrate member 2: the workflow body no longer names the superseded path" "no" \
  "$(_t1_has "$(cat "$_t1_r/.github/workflows/devflow.yml")" '.devflow/vendor/devflow')"
assert_eq "#1002 migrate member 3: the marketplace source points at the current vendor dir" \
  "./.prflow/vendor/prflow" \
  "$(python3 -c '
import json,sys
print(json.load(open(sys.argv[1]))["plugins"][0]["source"])' "$_t1_r/.claude-plugin/marketplace.json" 2>/dev/null)"
assert_eq "#1002 migrate member 4: the version pin is renamed AND advanced to the given ref" "v9.9.9" \
  "$(python3 -c '
import json,sys
print(json.load(open(sys.argv[1]))["prflow_version"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 migrate member 4: the superseded pin key is gone" "False" \
  "$(python3 -c '
import json,sys
print("devflow_version" in json.load(open(sys.argv[1])))' "$_t1_r/.prflow/config.json" 2>/dev/null)"
# The whole-tree emptiness assertion the acceptance criterion asks for: a post-migration
# consumer contains NO reference to the old vendored path, anywhere.
assert_eq "#1002 migrate: no file in the migrated tree names the superseded vendored path" "0" \
  "$(grep -rl '\.devflow/vendor/devflow' "$_t1_r" 2>/dev/null | grep -cv '/\.git/')"
assert_eq "#1002 migrate: the staging directory and the commit journal are both removed" "no no" \
  "$( [ -e "$_t1_r/.prflow.migrate-stage" ] && printf 'yes' || printf 'no' ) $( [ -e "$_t1_r/.prflow.migrate-journal" ] && printf 'yes' || printf 'no' )"
# FROZEN controls over the migrated tree.
assert_eq "#1002 migrate FROZEN: workflows.{devflow,devflow-review} survive the migration" \
  "devflow devflow-review" \
  "$(python3 -c '
import json,sys
print(" ".join(json.load(open(sys.argv[1]))["workflows"]))' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 migrate FROZEN: the workpad marker VALUE is not rewritten" "<!-- devflow:workpad -->" \
  "$(python3 -c '
import json,sys
print(json.load(open(sys.argv[1]))["prflow"]["workpad_marker"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
assert_eq "#1002 migrate FROZEN: the workflow FILENAMES are unchanged" "yes" \
  "$( [ -f "$_t1_r/.github/workflows/devflow.yml" ] && printf 'yes' || printf 'no' )"
assert_eq "#1002 migrate FROZEN: a learnings record moves with its bytes intact" '{"frozen":"record"}' \
  "$(cat "$_t1_r/.prflow/learnings/r.jsonl" 2>/dev/null)"

# Idempotency: a second run over a migrated tree is a byte-identical no-op.
_t1_before="$(_t1_snap "$_t1_r")"
_t1_out="$("$T1_MIGRATE" --apply --pin v9.9.9 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 migrate: a re-run over a migrated tree exits 0" "0" "$_t1_rc"
assert_eq "#1002 migrate: a re-run over a migrated tree changes nothing" \
  "$_t1_before" "$(_t1_snap "$_t1_r")"
assert_eq "#1002 migrate: a re-run says the tree is already migrated" "yes" \
  "$(_t1_has "$_t1_out" 'ALREADY MIGRATED')"

# A repository with no state directory at all is a first-time install, not an
# un-migrated consumer — a distinct report, never "migrated 0 items".
_t1_r="$(_t1_root)"
_t1_out="$("$T1_MIGRATE" --apply --pin v1 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 migrate: a repository with no state directory exits 0" "0" "$_t1_rc"
assert_eq "#1002 migrate: it is reported as nothing-to-migrate, not as a migration" "yes no" \
  "$(_t1_has "$_t1_out" 'NOTHING TO MIGRATE') $(_t1_has "$_t1_out" 'APPLIED')"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 G. the atomic unit is ALL-OR-NOTHING (per-member induced blockers)"
# ────────────────────────────────────────────────────────────────────────────
# THE LOAD-BEARING FAMILY. One arm per member of the atomic unit: make THAT member
# alone unsatisfiable, run the migration, and assert the whole set was refused and the
# repository is byte-identical. Four RED arms if the apply is not transactional — which
# is what makes "no member can be applied without the others" an executable claim
# rather than a prose one.
_t1_blocked_member() {
  local member="$1" r before after out rc
  r="$(_t1_old_consumer)"
  set -- --apply --pin v9.9.9
  case "$member" in
    state-dir-move)             mkdir -p "$r/.prflow.migrate-stage" ;;
    workflow-content-rewrite)   chmod a-w "$r/.github/workflows/devflow.yml" ;;
    marketplace-source-rewrite) chmod a-w "$r/.claude-plugin/marketplace.json" ;;
    version-pin-advance)        set -- --apply ;;
  esac
  before="$(_t1_snap "$r")"
  out="$("$T1_MIGRATE" "$@" "$r" 2>&1)"; rc=$?
  after="$(_t1_snap "$r")"
  chmod -R u+w "$r" 2>/dev/null || true
  assert_eq "#1002 all-or-nothing [$member]: the run REFUSES" "1" "$rc"
  assert_eq "#1002 all-or-nothing [$member]: the repository is byte-identical" "$before" "$after"
  assert_eq "#1002 all-or-nothing [$member]: the report names the blocked member" "yes" \
    "$(_t1_has "$out" "$member")"
  assert_eq "#1002 all-or-nothing [$member]: the state directory did NOT move" "yes no" \
    "$( [ -d "$r/.devflow" ] && printf 'yes' || printf 'no' ) $( [ -d "$r/.prflow" ] && printf 'yes' || printf 'no' )"
  assert_eq "#1002 all-or-nothing [$member]: the marketplace source was NOT rewritten" "yes" \
    "$(_t1_has "$(cat "$r/.claude-plugin/marketplace.json" 2>/dev/null)" '.devflow/vendor/devflow')"
}
for _t1_m in state-dir-move workflow-content-rewrite marketplace-source-rewrite version-pin-advance; do
  _t1_blocked_member "$_t1_m"
done

# A tree carrying BOTH directories is mid-migration or hand-migrated: refuse rather
# than move one inside the other (a bare `mv` would nest them).
_t1_r="$(_t1_old_consumer)"; mkdir -p "$_t1_r/.prflow"
_t1_before="$(_t1_snap "$_t1_r")"
_t1_out="$("$T1_MIGRATE" --apply --pin v1 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 all-or-nothing: both directories present REFUSES" "1" "$_t1_rc"
assert_eq "#1002 all-or-nothing: both directories present leaves the tree byte-identical" \
  "$_t1_before" "$(_t1_snap "$_t1_r")"
assert_eq "#1002 all-or-nothing: the both-present refusal states the two operator exits" "yes yes" \
  "$(_t1_has "$_t1_out" 'merge the two directories') $(_t1_has "$_t1_out" 'delete the incomplete')"

# A leftover commit journal means a previous run died inside the destructive window.
# That is detectable and refused, rather than silently half-done.
_t1_r="$(_t1_old_consumer)"; : > "$_t1_r/.prflow.migrate-journal"
_t1_before="$(_t1_snap "$_t1_r")"
_t1_out="$("$T1_MIGRATE" --apply --pin v1 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 all-or-nothing: a leftover commit journal REFUSES" "1" "$_t1_rc"
assert_eq "#1002 all-or-nothing: a leftover journal leaves the tree byte-identical" \
  "$_t1_before" "$(_t1_snap "$_t1_r")"
assert_eq "#1002 all-or-nothing: the journal refusal names the journal path" "yes" \
  "$(_t1_has "$_t1_out" '.prflow.migrate-journal')"

# A stale-but-unparseable marketplace.json is a blocker, not a silent skip.
_t1_r="$(_t1_old_consumer)"
printf '%s' '{"plugins":[{"source":"./.devflow/vendor/devflow" BROKEN' \
  > "$_t1_r/.claude-plugin/marketplace.json"
_t1_before="$(_t1_snap "$_t1_r")"
_t1_out="$("$T1_MIGRATE" --apply --pin v1 "$_t1_r" 2>&1)"; _t1_rc=$?
assert_eq "#1002 all-or-nothing: a stale but unparseable marketplace.json REFUSES" "1" "$_t1_rc"
assert_eq "#1002 all-or-nothing: the unparseable-marketplace refusal is byte-identical" \
  "$_t1_before" "$(_t1_snap "$_t1_r")"
assert_eq "#1002 all-or-nothing: the refusal names JSON validity as the cause" "yes" \
  "$(_t1_has "$_t1_out" 'not valid JSON')"

# The migration reports what it could NOT migrate, naming each item individually.
_t1_r="$(_t1_old_consumer)"
printf 'run: .devflow/vendor/devflow/scripts/filter-runner-tools.sh\n' \
  > "$_t1_r/.github/workflows/devflow-runner.yml"
_t1_out="$("$T1_MIGRATE" "$_t1_r" 2>&1)"
assert_eq "#1002 migrate: an unshipped retained workflow is named in the could-not-migrate report" "yes" \
  "$(_t1_has "$_t1_out" 'could not migrate')"
assert_eq "#1002 migrate: the could-not-migrate entry names the specific file" "yes" \
  "$(_t1_has "$_t1_out" 'devflow-runner.yml')"

# ────────────────────────────────────────────────────────────────────────────
echo "#1002 H. the workflow config-job per-family fail-loud guard"
# ────────────────────────────────────────────────────────────────────────────
# The trigger-time channel reads config through inline jq and never through
# config-get.sh, so the resolver's breadcrumb cannot reach it. The selector is driven
# directly over the adversarial shape matrix, because a grep-pin on the ::error::
# literal is not coverage of the branch that chooses it.
_t1_guard='if type != "object" then $fams | split(" ") | join(" ") else ($fams | split(" ")) - [keys[]] | join(" ") end'
_t1_fams="prflow prflow_version"
_t1_missing() { printf '%s' "$1" | jq -r --arg fams "$_t1_fams" "$_t1_guard" 2>/dev/null; }

assert_eq "#1002 family guard: every family present reports nothing missing" "" \
  "$(_t1_missing '{"prflow":{},"prflow_version":"x"}')"
assert_eq "#1002 family guard: an un-migrated config reports BOTH families missing" \
  "prflow prflow_version" "$(_t1_missing '{"devflow":{},"devflow_version":"x"}')"
assert_eq "#1002 family guard: one absent family is named alone" "prflow_version" \
  "$(_t1_missing '{"prflow":{}}')"
# FAMILY granularity, not leaf: the schema marks none of the optional leaves required,
# so a consumer who never set one must be unaffected.
assert_eq "#1002 family guard: a present family with absent optional leaves is silent" "" \
  "$(_t1_missing '{"prflow":{},"prflow_version":""}')"
assert_eq "#1002 family guard: a present family holding null is silent (the key exists)" "" \
  "$(_t1_missing '{"prflow":null,"prflow_version":"x"}')"
# Fail CLOSED on every non-object root: a hand-corrupted config must not read as clean.
for _t1_shape in '["a"]' '"hello"' 'null' '42'; do
  assert_eq "#1002 family guard: a non-object root ($_t1_shape) fails closed" \
    "prflow prflow_version" "$(_t1_missing "$_t1_shape")"
done

# The guard is wired into both SHIPPED workflows, on the same side of the enable gate
# as the pre-existing allowed_bots guard (an intentionally-disabled repo is never
# failed). Asserted by driving the file's own text for the ordering relationship.
for _t1_wf in devflow devflow-implement; do
  _t1_body="$(cat "$LIB/../.github/workflows/$_t1_wf.yml" 2>/dev/null)"
  assert_eq "#1002 family guard: $_t1_wf.yml carries the per-family guard" "yes" \
    "$(_t1_has "$_t1_body" 'MISSING_FAMILIES')"
  assert_eq "#1002 family guard: $_t1_wf.yml gates it on the workflow being enabled" "yes" \
    "$(_t1_has "$_t1_body" 'if [ "$ENABLED" = "true" ]; then')"
  assert_eq "#1002 family guard: $_t1_wf.yml routes the operator to /prflow:init" "yes" \
    "$(_t1_has "$_t1_body" 'run /prflow:init to migrate the whole Tier 1 set')"
done

# ────────────────────────────────────────────────────────────────────────────
echo "#1041 E3. the silent-disable skew guard, deliberately NOT gated on the enable read"
# ────────────────────────────────────────────────────────────────────────────
# Tier 4 renamed the ENABLE key itself. While workflows.devflow was frozen, a refreshed
# shipped workflow and the config key could never skew; the rename removed that guarantee.
# install.sh's workflow copy loop is PER FILE over an install_managed that deliberately
# PRESERVES a hand-edited workflow, so refreshing one shipped workflow while the other
# stays hand-edited on the superseded key makes scaffold-config.sh's freshness gate refuse
# the config migration — correctly — and leaves the refreshed file reading workflows.prflow
# against a config that still carries workflows.devflow. ENABLED resolves absent -> false
# and every trigger silently no-ops. The per-family guard above CANNOT report that: it sits
# inside `if [ "$ENABLED" = "true" ]`, the very gate this skew forces shut. So the guard
# under test is computed from the config alone.
#
# The program is READ OUT OF THE SHIPPED WORKFLOW rather than transcribed here, so these
# rows drive the bytes that actually run and no copy can drift away from them.
_t1_skew_prog() {  # $1 = shipped workflow id -> that file's own guard program
  python3 - "$LIB/../.github/workflows/$1.yml" <<'PY'
import re, sys
for line in open(sys.argv[1], encoding="utf-8"):
    if "SUPERSEDED_ENABLE=" in line and "jq -r " in line:
        found = re.search(r"jq -r '(.*)'\)\s*$", line.strip())
        if found:
            sys.stdout.write(found.group(1))
        break
PY
}
_t1_skew_impl="$(_t1_skew_prog devflow-implement)"
_t1_skew_cmd="$(_t1_skew_prog devflow)"
assert_eq "#1041 skew guard: the program is extractable from BOTH shipped workflows and is byte-identical (so the rows below drive what really runs)" "yes" \
  "$([ -n "$_t1_skew_impl" ] && [ "$_t1_skew_impl" = "$_t1_skew_cmd" ] && echo yes || echo no)"
_t1_skew() { printf '%s' "$1" | jq -r "$_t1_skew_impl" 2>/dev/null; }

# THE REACHABLE DEFECT: superseded key present and intended ON, current key absent.
# `true` is the error arm — the run fails loudly instead of doing nothing quietly.
assert_eq "#1041 skew guard: superseded key true + current key absent selects the ERROR arm" \
  "true" "$(_t1_skew '{"workflows":{"devflow":true}}')"
# String-truthiness mirrors the enable read (`// false` then a literal `true` compare), so a
# string "true" is just as enabled and just as silenced.
assert_eq "#1041 skew guard: a STRING \"true\" selects the error arm too (mirrors the enable read)" \
  "true" "$(_t1_skew '{"workflows":{"devflow":"true"}}')"
# VALID-FALSY (issue #312): a deliberate false already meant off, so the outcome still
# matches intent — warning arm, never a failed run. `has()` is what keeps this row
# distinguishable from an absent key; `//` would collapse the two.
assert_eq "#1041 skew guard: a deliberate false is reported as itself, not collapsed into absent" \
  "false" "$(_t1_skew '{"workflows":{"devflow":false}}')"
assert_eq "#1041 skew guard: an explicit null is likewise reported as itself (has() semantics)" \
  "null" "$(_t1_skew '{"workflows":{"devflow":null}}')"
# NO SKEW: the current key exists, so the enable read resolves and nothing is silenced —
# including a migrated config that is deliberately turned OFF, which must not be failed.
assert_eq "#1041 skew guard: current key present alongside the superseded one is silent" "" \
  "$(_t1_skew '{"workflows":{"devflow":true,"prflow":false}}')"
assert_eq "#1041 skew guard: a fully migrated config is silent" "" \
  "$(_t1_skew '{"workflows":{"prflow":true}}')"
assert_eq "#1041 skew guard: a deliberately-disabled MIGRATED config is silent (never failed)" "" \
  "$(_t1_skew '{"workflows":{"prflow":false}}')"
assert_eq "#1041 skew guard: neither key present is silent" "" \
  "$(_t1_skew '{"workflows":{}}')"
# Malformed shapes fail OPEN here on purpose: a corrupt config is the pre-existing
# per-family guard's subject, and this one must not crash the filter or invent a verdict.
for _t1_skewshape in '{"workflows":"all of them"}' '{"workflows":["a"]}' '{"workflows":42}' '["a"]' '"hello"' 'null' '42'; do
  assert_eq "#1041 skew guard: a malformed shape ($_t1_skewshape) yields no verdict rather than crashing" "" \
    "$(_t1_skew "$_t1_skewshape")"
done

# The ORDERING property that makes the guard work at all: it must sit OUTSIDE (and before)
# the enable gate. Asserted positionally on each shipped file, because a later edit that
# tucked it inside `if [ "$ENABLED" = "true" ]` would leave every row above still green
# while the guard became unreachable on exactly the configs it exists to catch.
for _t1_wf in devflow devflow-implement; do
  assert_eq "#1041 skew guard: $_t1_wf.yml computes it BEFORE the enable gate, so the gate cannot suppress it" "outside-gate" \
    "$(python3 - "$LIB/../.github/workflows/$_t1_wf.yml" <<'PY'
import sys
guard = gate = None
for i, line in enumerate(open(sys.argv[1], encoding="utf-8")):
    if guard is None and "SUPERSEDED_ENABLE=$(" in line:
        guard = i
    if gate is None and 'if [ "$ENABLED" = "true" ]; then' in line:
        gate = i
if guard is None or gate is None:
    print("MISSING guard=%s gate=%s" % (guard, gate))
else:
    print("outside-gate" if guard < gate else "inside-or-after-gate")
PY
)"
  _t1_body="$(cat "$LIB/../.github/workflows/$_t1_wf.yml" 2>/dev/null)"
  assert_eq "#1041 skew guard: $_t1_wf.yml states the consequence and the remedy an operator can act on" "yes yes" \
    "$(_t1_has "$_t1_body" 'resolves as DISABLED and every trigger silently does nothing') $(_t1_has "$_t1_body" 'prflow-new sidecar')"
done

# A GUARD MUST NOT DEFEAT ANOTHER GUARD. The freshness gate above decides staleness by
# searching a shipped workflow for a DOTTED read of the superseded key, and it does not
# distinguish code from comments. The skew guard is a diagnostic ABOUT that key, so the
# obvious way to write it — naming the key in dotted form in the jq program, an error
# message, or even the comment explaining this hazard — marks BOTH shipped workflows
# permanently stale. Every consumer's config-key migration then refuses forever, which is
# strictly worse than the silent disable the guard was added to catch. That regression was
# made and caught here; this drives the gate's REAL scanner, read out of scaffold-config.sh
# rather than re-expressed, over the shipped pair.
_t1_gate_scan="$(python3 - "$LIB/../scripts/scaffold-config.sh" "$LIB/../.github/workflows/devflow.yml" "$LIB/../.github/workflows/devflow-implement.yml" <<'PY'
import re, sys
# Lift the gate's own KEY/BARE patterns out of the shipped scanner, so this can never
# assert against a stale copy of the rule it is checking.
source = open(sys.argv[1], encoding="utf-8").read()
pats = re.findall(r"^(KEY|BARE) = re\.compile\(r\"(.*)\"\)$", source, re.M)
if len(pats) != 2:
    print("UNEXTRACTABLE")
    raise SystemExit
compiled = [re.compile(body) for _, body in pats]
stale = []
for path in sys.argv[2:]:
    text = open(path, encoding="utf-8").read()
    if any(p.search(text) for p in compiled):
        stale.append(path.rsplit("/", 1)[-1])
print(" ".join(stale) if stale else "clean")
PY
)"
assert_eq "#1041 skew guard: both shipped workflows still scan CLEAN under the freshness gate's own patterns — a diagnostic naming the superseded key in dotted form would wedge every consumer's migration" \
  "clean" "$_t1_gate_scan"
# Positive control: the extraction really can report staleness, so "clean" above is a
# measurement and not an unconditional string.
assert_eq "#1041 skew guard: that scan DOES flag a workflow carrying a dotted superseded read (so the clean result is not vacuous)" \
  "stale" "$(printf 'run: jq -r ".workflows.devflow // false"\n' | python3 -c '
import re, sys
source = open(sys.argv[1], encoding="utf-8").read()
pats = re.findall(r"^(KEY|BARE) = re\.compile\(r\"(.*)\"\)$", source, re.M)
compiled = [re.compile(body) for _, body in pats]
text = sys.stdin.read()
print("stale" if any(p.search(text) for p in compiled) else "clean")
' "$LIB/../scripts/scaffold-config.sh")"

# ────────────────────────────────────────────────────────────────────────────
echo "#1083 E4. the stray-superseded-family detector, deliberately NOT gated on the enable read"
# ────────────────────────────────────────────────────────────────────────────
# #1068 corrected every instruction that named a dead grant key but deliberately left the
# DETECTION gap: the MISSING_FAMILIES set-difference (section H) only fires when a canonical
# family is ABSENT, so a config carrying a correct prflow family PLUS a stray superseded
# top-level family passes silently — the stray family's keys resolve to their `// default`
# everywhere and any grant/allowlist-narrowing/provider-selection written there evaporates.
# This detector warns on exactly that half-migrated shape. Like the #1041 skew guard it lives
# OUTSIDE the enable gate (a disabled repo mid-migration must still be told), and the selector
# is driven directly over the adversarial shape matrix — a grep-pin on the ::warning:: literal
# is not coverage of the branch that chooses it.
#
# The jq program is READ OUT OF THE SHIPPED WORKFLOW rather than transcribed here, so these
# rows drive the bytes that actually run and no copy can drift away from them.
_t1_stray_prog() {  # $1 = shipped workflow id -> that file's own STRAY_FAMILIES jq program
  python3 - "$LIB/../.github/workflows/$1.yml" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
# Capture the multi-line program between `STRAY_FAMILIES=$(echo "$CONFIG_JSON" | jq -r '`
# and its terminating `')`.
m = re.search(r"STRAY_FAMILIES=\$\(echo \"\$CONFIG_JSON\" \| jq -r '(.*?)'\)", text, re.S)
if m:
    sys.stdout.write(m.group(1))
PY
}
_t1_stray_impl="$(_t1_stray_prog devflow-implement)"
_t1_stray_cmd="$(_t1_stray_prog devflow)"
assert_eq "#1083 stray-family detector: the program is extractable from BOTH shipped workflows and is byte-identical (so the rows below drive what really runs)" "yes" \
  "$([ -n "$_t1_stray_impl" ] && [ "$_t1_stray_impl" = "$_t1_stray_cmd" ] && echo yes || echo no)"
_t1_stray() { printf '%s' "$1" | jq -r "$_t1_stray_impl" 2>/dev/null; }

# THE REACHABLE DEFECT: a canonical family present beside a stray superseded one — the exact
# population MISSING_FAMILIES passes silently. The stray family is named so the operator can act.
assert_eq "#1083 stray-family detector: a stray superseded family beside a canonical one is named" \
  "devflow" "$(_t1_stray '{"prflow":{},"devflow":{}}')"
# One warning per stray family: multiple strays are all reported, space-joined for the loop.
assert_eq "#1083 stray-family detector: every stray family present is reported" \
  "devflow devflow_version" "$(_t1_stray '{"prflow":{},"prflow_version":"x","devflow":{},"devflow_version":"y"}')"
# The 'canonical present' discriminator uses the same prflow* SHAPE, so any migrated family
# beside a stray one arms the detector — not just the specific prflow/prflow_version pair.
assert_eq "#1083 stray-family detector: any prflow* family counts as the canonical neighbour" \
  "devflow_review" "$(_t1_stray '{"prflow_implement":{},"devflow_review":{}}')"
# VALID-FALSY (issue #312): presence is read from `keys`, never the value, so a stray family
# deliberately holding false/0/"" is STILL detected — a `//`-based read would collapse it to absent.
assert_eq "#1083 stray-family detector: a stray family holding a valid-falsy value is still detected" \
  "devflow" "$(_t1_stray '{"prflow":{},"devflow":false}')"
assert_eq "#1083 stray-family detector: a stray family holding 0 is still detected" \
  "devflow_runner" "$(_t1_stray '{"prflow":{},"devflow_runner":0}')"
# The fully-UN-migrated shape (no canonical neighbour) is the loud MISSING_FAMILIES gate's
# subject — this detector stays silent so the two do not double-diagnose the same config.
assert_eq "#1083 stray-family detector: an un-migrated config (no canonical family) is silent" "" \
  "$(_t1_stray '{"devflow":{},"devflow_version":"x"}')"
assert_eq "#1083 stray-family detector: a fully-migrated config is silent" "" \
  "$(_t1_stray '{"prflow":{},"prflow_version":"x"}')"
assert_eq "#1083 stray-family detector: an empty object is silent" "" \
  "$(_t1_stray '{}')"
# Non-object roots fail SAFE (empty, no crash): a hand-corrupted config is the loud
# per-family guard's subject, and this advisory detector must not detonate the filter.
for _t1_strayshape in '["a"]' '"hello"' 'null' '42'; do
  assert_eq "#1083 stray-family detector: a non-object root ($_t1_strayshape) yields no verdict rather than crashing" "" \
    "$(_t1_stray "$_t1_strayshape")"
done

# NEGATIVE CONTROL on the shape's SCOPE: it matches a top-level config FAMILY, so a frozen
# devflow-prefixed name that is not one must not be flagged even sitting at the top level
# beside a canonical family. The marketplace name is the canonical example (it is in the
# rename map's own frozen.identifiers). Without this the rows above prove only that the shape
# is wide enough, never that it is narrow enough.
assert_eq "#1083 stray-family detector: a frozen devflow-prefixed name that is NOT a top-level family is not flagged" "" \
  "$(_t1_stray '{"prflow":{},"devflow-marketplace":{}}')"
# ...and the control is LIVE: the same config plus a real stray family still fires, so the row
# above cannot pass merely because the detector went silent altogether.
assert_eq "#1083 stray-family detector: the frozen-name control is live (a real stray beside it still fires)" \
  "devflow_review" "$(_t1_stray '{"prflow":{},"devflow-marketplace":{},"devflow_review":{}}')"

# DERIVATION FROM THE RENAME INVENTORY: the workflow's inline jq cannot read
# lib/rename-map.json at runtime (the checkout may not carry it), so the detector matches by
# SHAPE and this desk-time row reconciles that shape against the map's config_keys.
#
# The patterns are EXTRACTED FROM THE SHIPPED JQ PROGRAM, never transcribed here: a row that
# re-implemented the shape in its own Python would reconcile the map against a COPY, which is
# the guard-reads-a-copy defect this repo calls unverified-assumption. Extraction failure
# prints MISSING rather than falling back to a default, because an empty pattern matches
# everything and would pass vacuously.
#
# Be exact about what derivation buys, because it is NOT "this row now catches any shape
# change" — measured against the three mutation classes:
#   NARROWING  (`^devflow_`, which stops covering the bare `devflow` family) — caught HERE, and
#              only because the pattern is derived; a transcribed copy left this row green.
#   WIDENING   (`^devflow`) — NOT caught here. It still covers every map entry and still misses
#              every prflow* key, so all three directions below stay satisfied. It is caught by
#              the frozen-name negative control above, which drives the real jq and goes RED
#              because `devflow-marketplace` starts being flagged.
#   CANONICAL PROBE broken (the neighbour test respelled) — caught by neither of those two; the
#              `un-migrated config is silent` row above is what goes RED.
# So over-reach is bounded behaviorally and under-reach is bounded here; neither row is
# sufficient alone, and this comment is the record of which covers which.
#
# Three directions, so the row states the shape's intended TOP-LEVEL-FAMILY scope:
#   ALL-SUPERSEDED-MATCH  every superseded family the map lists matches the shape
#   NO-CURRENT-MATCH      no current (prflow*) key does
#   FROZEN-EXCLUDED(N)    none of the N frozen CONFIG KEYS does. N is in the expected value on
#                         purpose: Tier 4 emptied frozen.config_keys, so this direction is
#                         vacuous today and the count makes that visible instead of hiding it
#                         — and adding a frozen config key changes the expected string, which
#                         is the deliberate review point vacuity would otherwise cost.
# Scoped to frozen.CONFIG_KEYS and not to frozen.identifiers on purpose: `devflow_module_pin_*`
# is a frozen identifier that DOES match the shape by design, and rightly so — it is not a
# top-level config key, so the detector never sees it. Widening this row to every frozen name
# would assert something false.
assert_eq "#1083 stray-family detector: the shape read OUT OF THE SHIPPED jq matches every superseded config family in the rename map, no current key, and no frozen config key" \
  "ALL-SUPERSEDED-MATCH NO-CURRENT-MATCH FROZEN-EXCLUDED(0)" \
  "$(python3 - "$LIB/../lib/rename-map.json" "$_t1_stray_impl" <<'PY'
import json, re, sys
# argv, not stdin: the heredoc IS this process's stdin (python3 reads its own program from
# `-`), so a piped program would arrive empty and every direction below would pass vacuously.
prog = sys.argv[2]
# Each pattern comes out of its own unambiguous position in the shipped program: the canonical
# probe sits in `any($k[]; test(...))`, the superseded filter in `select(test(...))`.
canon = re.search(r'any\(\$k\[\];\s*test\("([^"]+)"\)\)', prog)
sup = re.search(r'select\(\s*test\("([^"]+)"\)\s*\)', prog)
if not canon or not sup:
    print("MISSING canonical=%s superseded=%s" % (bool(canon), bool(sup)))
    raise SystemExit(0)
sup_re = re.compile(sup.group(1))
m = json.load(open(sys.argv[1]))
ck = m["config_keys"]
frozen = m.get("frozen", {}).get("config_keys", [])
print(("ALL-SUPERSEDED-MATCH" if all(sup_re.search(k) for k in ck) else "SUPERSEDED-MISS"),
      ("NO-CURRENT-MATCH" if not any(sup_re.search(v) for v in ck.values()) else "CURRENT-MATCHED"),
      (("FROZEN-EXCLUDED(%d)" if not any(sup_re.search(k) for k in frozen)
        else "FROZEN-MATCHED(%d)") % len(frozen)))
PY
)"

# Wired into both SHIPPED workflows, and — like the #1041 skew guard — computed BEFORE the
# enable gate, so an intentionally-disabled repository mid-migration is still warned. Asserted
# positionally on each shipped file: an edit that tucked it inside `if [ "$ENABLED" = "true" ]`
# would leave every row above green while the detector went dark on disabled configs.
for _t1_wf in devflow devflow-implement; do
  _t1_body="$(cat "$LIB/../.github/workflows/$_t1_wf.yml" 2>/dev/null)"
  assert_eq "#1083 stray-family detector: $_t1_wf.yml carries the detector" "yes" \
    "$(_t1_has "$_t1_body" 'STRAY_FAMILIES=$(')"
  assert_eq "#1083 stray-family detector: $_t1_wf.yml routes the operator to /prflow:init" "yes" \
    "$(_t1_has "$_t1_body" 'Run /prflow:init to migrate the Tier 1 config keys')"
  assert_eq "#1083 stray-family detector: $_t1_wf.yml computes it BEFORE the enable gate" "outside-gate" \
    "$(python3 - "$LIB/../.github/workflows/$_t1_wf.yml" <<'PY'
import sys
detector = gate = None
for i, line in enumerate(open(sys.argv[1], encoding="utf-8")):
    if detector is None and "STRAY_FAMILIES=$(" in line:
        detector = i
    if gate is None and 'if [ "$ENABLED" = "true" ]; then' in line:
        gate = i
if detector is None or gate is None:
    print("MISSING detector=%s gate=%s" % (detector, gate))
else:
    print("outside-gate" if detector < gate else "inside-or-after-gate")
PY
)"
done

# COUPLED MIRROR: the two shipped workflows carry the SAME block, byte for byte. The row above
# only proves the extracted jq program matches; the block is more than the program — the arm
# that selects the emit, the operator-facing message, and the comment stating why no dotted or
# bare superseded literal may appear here. A drift confined to any of those would leave every
# row above green while the two shipped workflows diagnosed the same config differently (or one
# of them re-introduced a literal the freshness gate marks stale). Digested, not compared
# in-place, so a failure names WHICH file drifted rather than dumping both blocks.
_t1_stray_block() {  # $1 = shipped workflow id -> sha256 of that file's whole detector block
  python3 - "$LIB/../.github/workflows/$1.yml" <<'PY'
import hashlib, sys
lines = open(sys.argv[1], encoding="utf-8").readlines()
start = next((i for i, l in enumerate(lines) if "# STRAY SUPERSEDED FAMILY DETECTION" in l), None)
if start is None:
    sys.exit(0)
# The block ends at its own terminating `fi` (the guard around the per-family emit loop).
end = next((i for i in range(start, len(lines)) if lines[i].strip() == "fi"), None)
if end is None:
    sys.exit(0)
sys.stdout.write(hashlib.sha256("".join(lines[start:end + 1]).encode("utf-8")).hexdigest()[:16])
PY
}
_t1_stray_blk_cmd="$(_t1_stray_block devflow)"
_t1_stray_blk_impl="$(_t1_stray_block devflow-implement)"
assert_eq "#1083 stray-family detector: the WHOLE block (comment, jq, selecting arm, message) is byte-identical across both shipped workflows" \
  "identical" \
  "$( [ -n "$_t1_stray_blk_cmd" ] && [ "$_t1_stray_blk_cmd" = "$_t1_stray_blk_impl" ] && echo identical \
      || printf 'DRIFT devflow=%s devflow-implement=%s' "${_t1_stray_blk_cmd:-MISSING}" "${_t1_stray_blk_impl:-MISSING}" )"

# ────────────────────────────────────────────────────────────────────────────
echo "#1004 J. the frozen out-of-repo DEVFLOW_* identifier inventory"
# ────────────────────────────────────────────────────────────────────────────
# Tier 3 records the consumer-facing DEVFLOW_* names that are NOT renamed, and derives a
# consumer advisory from that record. Two guarantees, kept apart because their remedies
# differ: the criterion still selects exactly the recorded population (remedy: a human
# adjudication) and the generated advisory region still matches the record (remedy: re-run
# the generator). Everything below drives lib/generate-env-freeze-advisory.py
# file-in/exit-code-out — no assertion here pins the advisory's wording.
T1_ENVGEN="$LIB/generate-env-freeze-advisory.py"

# ── J1 — the criterion, run over THIS checkout, agrees with the record ──────
# The live arm, and what makes the recorded population DERIVED rather than transcribed: a
# workflow that starts reading a new vars./secrets. DEVFLOW_* name, or a recorded name
# whose read side goes away, turns this red until someone adjudicates it.
assert_eq "#1004 the criterion run over the live tree matches the recorded population" "0" \
  "$(python3 "$T1_ENVGEN" --audit --repo-root "$LIB/.." >/dev/null 2>&1; printf '%s' $?)"

_t1_env_live="$(python3 "$T1_ENVGEN" --derive --repo-root "$LIB/.." 2>/dev/null)"
_t1_env_sel() { # <name> -> yes when the live arms select it
  case "$_t1_env_live" in
    "$1	"*|*"
$1	"*) printf 'yes' ;;
    *) printf 'no' ;;
  esac
}

# The three names issue #1004 calls out, each asserted against the LIVE arms rather than
# against the record — so the record cannot make itself right.
assert_eq "#1004 A1 selects DEVFLOW_REVIEWER_APP_ID (the gating half of the reviewer pair)" \
  "yes" "$(_t1_env_sel DEVFLOW_REVIEWER_APP_ID)"
assert_eq "#1004 the arms DO select DEVFLOW_PROMPT_EXTENSION_ROOT, so excluding it is an adjudication and not an oversight" \
  "yes" "$(_t1_env_sel DEVFLOW_PROMPT_EXTENSION_ROOT)"
assert_eq "#1004 the arms do NOT select DEVFLOW_CONFIG_FILE (declared in no consumer document)" \
  "no" "$(_t1_env_sel DEVFLOW_CONFIG_FILE)"

# The record's two halves stay disjoint, and the excluded set is exactly what is recorded.
# The set literal below IS the enforcement (issue #656's enforcement-constant exception): an
# exclusion added without a human adjudication moves it, so it is deliberately transcribed
# rather than derived. Count-free by construction — adding a row edits the literal, never a
# tally in the assertion name (the PR-#553 self-referential-count rot class).
assert_eq "#1004 no name is both consumer-facing and adjudicated out" "disjoint" \
  "$(python3 -c '
import json,sys
b=json.load(open(sys.argv[1]))["frozen"]["env_identifiers"]
both=set(r["name"] for r in b["identifiers"])&set(r["name"] for r in b["adjudicated_out"])
print(" ".join(sorted(both)) or "disjoint")' "$T1_MAP" 2>/dev/null)"
assert_eq "#1004 the adjudicated-out set is exactly the names the record excludes" \
  "DEVFLOW_CONFIG_FILE DEVFLOW_PROMPT_EXTENSION_ROOT DEVFLOW_REFRESH_REAP_GLOB DEVFLOW_REFRESH_SELFTEST_FAILED DEVFLOW_TRIGGERING_USER" \
  "$(python3 -c '
import json,sys
b=json.load(open(sys.argv[1]))["frozen"]["env_identifiers"]
print(" ".join(sorted(r["name"] for r in b["adjudicated_out"])))' "$T1_MAP" 2>/dev/null)"

# ── J2 — a synthetic tree drives each arm in isolation ─────────────────────
# Minimal fixtures rather than copies of the checkout: the arms then run on inputs whose
# whole population is known, so a passing assertion cannot be an accident of what the real
# tree happens to contain.
_t1_env_fixture() { # <root> <workflow-body> <consumer-doc-body> <shipped-reader-body>
  local r="$1"
  mkdir -p "$r/.github/workflows" "$r/docs/internal" "$r/lib"
  printf '%s\n' "$2" > "$r/.github/workflows/devflow.yml"
  printf 'name: b\n' > "$r/.github/workflows/devflow-implement.yml"
  printf '%s\n' "$3" > "$r/README.md"
  printf 'placeholder\n' > "$r/docs/internal/install.md"
  printf '%s\n' "$4" > "$r/install.sh"
  ( cd "$r" && git init -q . && git add -A . ) >/dev/null 2>&1
}

# The fixture map. Built by python3 so the required-field shape is produced once and
# mutated per arm, rather than hand-spelled across near-identical heredocs.
_t1_env_map() { # <root> <consumer-facing csv> <adjudicated-out csv> [field-to-blank]
  python3 - "$1" "$2" "$3" "${4:-}" <<'T1ENVPY'
import json, pathlib, sys
root, ins, outs, blank = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]


def row(name):
    r = {"name": name, "arm": "A1", "channel": "cloud", "kind": "repository variable",
         "set_where": "GitHub settings", "read_as": "vars." + name,
         "failure_visibility": "silent", "failure_mode": "the gate goes false"}
    if blank:
        r[blank] = ""
    return r


block = {
    "freeze_version": 1,
    "policy": "an inventory of names not to rename",
    "criterion": {"A1": "cloud", "A2": "operator",
                  "shipped_workflows": ["devflow.yml", "devflow-implement.yml"],
                  "consumer_docs": ["README.md", "docs/internal/install.md"]},
    "pair_asymmetry": "the variable half fails silent",
    "identifiers": [row(n) for n in ins.split(",") if n],
    "adjudicated_out": [{"name": n, "selected_by": "A2", "decided_by": "doc-declaration",
                         "verdict": "OUT", "evidence": "internal"} for n in outs.split(",") if n],
}
p = pathlib.Path(root, "lib")
p.mkdir(parents=True, exist_ok=True)
(p / "rename-map.json").write_text(
    json.dumps({"frozen": {"env_identifiers": block}}), encoding="utf-8")
T1ENVPY
}

_t1_env_wf='jobs:
  a:
    runs-on: ${{ vars.DEVFLOW_ALPHA && 1 || 2 }}
    steps:
      - if: ${{ vars.DEVFLOW_ALPHA != '"''"' }}
        env:
          K: ${{ secrets.DEVFLOW_BETA }}'
_t1_env_doc='Set DEVFLOW_HATCH to override.'
_t1_env_reader='V="${DEVFLOW_HATCH:-default}"'

_t1_env_r1="$(_t1_root)"
_t1_env_fixture "$_t1_env_r1" "$_t1_env_wf" "$_t1_env_doc" \
  "$_t1_env_reader"$'\n''U="${DEVFLOW_UNDOCUMENTED:-x}"'
_t1_env_map "$_t1_env_r1" "DEVFLOW_ALPHA,DEVFLOW_BETA,DEVFLOW_HATCH" ""
_t1_env_d1=""
while IFS='	' read -r _t1_env_n _t1_env_a; do
  [ -n "$_t1_env_n" ] || continue
  _t1_env_d1="${_t1_env_d1:+$_t1_env_d1 }$_t1_env_n:$_t1_env_a"
done <<T1ENVEOF
$(python3 "$T1_ENVGEN" --derive --repo-root "$_t1_env_r1" 2>/dev/null)
T1ENVEOF
assert_eq "#1004 the arms select A1's two workflow names and A2's documented override, with the selecting arm" \
  "DEVFLOW_ALPHA:A1 DEVFLOW_BETA:A1 DEVFLOW_HATCH:A2" "$_t1_env_d1"
assert_eq "#1004 A2 does not select an ambient read no consumer document declares" "no" \
  "$(_t1_has "$_t1_env_d1" 'DEVFLOW_UNDOCUMENTED')"

# The advisory is rendered INTO a document A2 scans, and it names the very identifiers it
# excludes — so without this the generated output feeds its own derivation and a name
# recorded as adjudicated-out is re-selected by the sentence explaining its exclusion.
# Drive it directly: a doc whose ONLY mention of a read name sits inside the region.
_t1_env_r0="$(_t1_root)"
_t1_env_fixture "$_t1_env_r0" "$_t1_env_wf" "a consumer document mentioning nothing" \
  "$_t1_env_reader"
_t1_env_map "$_t1_env_r0" "DEVFLOW_ALPHA,DEVFLOW_BETA" ""
{ printf '<!-- prflow-env-freeze:begin freeze_version=1 sha256=%064d (x) -->\n' 0
  printf 'DEVFLOW_HATCH is deliberately not on this list.\n'
  printf '<!-- prflow-env-freeze:end -->\n'; } > "$_t1_env_r0/README.md"
assert_eq "#1004 a name declared ONLY inside the generated region is not selected by A2" "no" \
  "$(_t1_has "$(python3 "$T1_ENVGEN" --derive --repo-root "$_t1_env_r0" 2>/dev/null)" 'DEVFLOW_HATCH')"
assert_eq "#1004 stripping the region leaves the rest of that document scannable" "0" \
  "$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r0" >/dev/null 2>&1; printf '%s' $?)"

# ── J3 — the audit fails in BOTH directions, and says which ────────────────
# A selected name the record does not carry at all: the shape a new vars.DEVFLOW_* in a
# shipped workflow produces.
_t1_env_map "$_t1_env_r1" "DEVFLOW_ALPHA,DEVFLOW_HATCH" ""
_t1_env_o1="$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r1" 2>&1)"; _t1_env_rc1=$?
assert_eq "#1004 audit: an unadjudicated selected name fails" "1" "$_t1_env_rc1"
assert_eq "#1004 audit: it names the unadjudicated name with the add direction" "yes" \
  "$(_t1_has "$_t1_env_o1" '+ DEVFLOW_BETA')"
assert_eq "#1004 audit: it routes the remedy to an adjudication, not to a regeneration" "yes" \
  "$(_t1_has "$_t1_env_o1" 'adjudicate each into')"

# The other direction: a recorded consumer-facing name the arms no longer select, which
# leaves a consumer warned about a name nothing reads.
_t1_env_map "$_t1_env_r1" "DEVFLOW_ALPHA,DEVFLOW_BETA,DEVFLOW_HATCH,DEVFLOW_GHOST" ""
_t1_env_o2="$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r1" 2>&1)"; _t1_env_rc2=$?
assert_eq "#1004 audit: a recorded name the criterion no longer selects fails" "1" "$_t1_env_rc2"
assert_eq "#1004 audit: it names the stale name with the remove direction" "yes" \
  "$(_t1_has "$_t1_env_o2" '- DEVFLOW_GHOST')"

# An adjudicated_out entry is EXEMPT from the still-selected requirement: a name belongs
# there precisely because an arm may not select it (DEVFLOW_CONFIG_FILE is that case), so
# requiring it to stay selected would invert the block's meaning.
_t1_env_map "$_t1_env_r1" "DEVFLOW_ALPHA,DEVFLOW_BETA,DEVFLOW_HATCH" "DEVFLOW_NEVER_SELECTED"
assert_eq "#1004 audit: an adjudicated-out name the arms never select is clean" "0" \
  "$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r1" >/dev/null 2>&1; printf '%s' $?)"

# ── J4 — the record fails CLOSED on an incomplete row ──────────────────────
# A row with a blank failure mode is the defect this advisory exists to prevent (AC2:
# without it the advisory raises salience on every name while withholding that most fail
# silently). It must be an INPUT failure, never a rendered blank cell.
for _t1_env_f in failure_mode failure_visibility set_where; do
  _t1_env_r2="$(_t1_root)"
  _t1_env_fixture "$_t1_env_r2" "$_t1_env_wf" "$_t1_env_doc" "$_t1_env_reader"
  _t1_env_map "$_t1_env_r2" "DEVFLOW_ALPHA" "" "$_t1_env_f"
  _t1_env_o3="$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r2" 2>&1)"; _t1_env_rc3=$?
  assert_eq "#1004 a row with an empty $_t1_env_f is an input failure (exit 2), not drift" \
    "2" "$_t1_env_rc3"
  assert_eq "#1004 the empty-$_t1_env_f diagnosis names the field" "yes" \
    "$(_t1_has "$_t1_env_o3" "$_t1_env_f")"
done

# An unreadable or malformed map is exit 2 as well: exit 1 would tell a batched artifact
# pass to regenerate from the very file the generator could not read.
_t1_env_r3="$(_t1_root)"
_t1_env_fixture "$_t1_env_r3" "$_t1_env_wf" "$_t1_env_doc" "$_t1_env_reader"
printf 'not json\n' > "$_t1_env_r3/lib/rename-map.json"
assert_eq "#1004 a malformed rename map is exit 2, never exit 1" "2" \
  "$(python3 "$T1_ENVGEN" --audit --repo-root "$_t1_env_r3" >/dev/null 2>&1; printf '%s' $?)"
rm -f "$_t1_env_r3/lib/rename-map.json"
assert_eq "#1004 an absent rename map is exit 2, never exit 1" "2" \
  "$(python3 "$T1_ENVGEN" --check --repo-root "$_t1_env_r3" >/dev/null 2>&1; printf '%s' $?)"

# ── J5 — the generated advisory region ─────────────────────────────────────
assert_eq "#1004 the shipped advisory region matches the record" "0" \
  "$(python3 "$T1_ENVGEN" --check --repo-root "$LIB/.." >/dev/null 2>&1; printf '%s' $?)"

# Region identity is asserted by ROUND TRIP over a fixture rather than by grepping the
# shipped document: render into a placeholder, prove --check is clean, hand-edit one body
# line, prove --check reports it. That covers the generator and its checker together.
_t1_env_r4="$(_t1_root)"
_t1_env_fixture "$_t1_env_r4" "$_t1_env_wf" "$_t1_env_doc" "$_t1_env_reader"
_t1_env_map "$_t1_env_r4" "DEVFLOW_ALPHA,DEVFLOW_BETA,DEVFLOW_HATCH" ""
{ printf 'intro\n\n'
  printf '<!-- prflow-env-freeze:begin freeze_version=0 sha256=%064d (placeholder) -->\n' 0
  printf '<!-- prflow-env-freeze:end -->\n\ntail\n'; } > "$_t1_env_r4/docs/internal/cloud-setup.md"
assert_eq "#1004 the generator writes the region into a placeholder" "0" \
  "$(python3 "$T1_ENVGEN" --repo-root "$_t1_env_r4" >/dev/null 2>&1; printf '%s' $?)"
assert_eq "#1004 the freshly generated region passes its own check" "0" \
  "$(python3 "$T1_ENVGEN" --check --repo-root "$_t1_env_r4" >/dev/null 2>&1; printf '%s' $?)"
_t1_env_rendered="$(cat "$_t1_env_r4/docs/internal/cloud-setup.md")"
assert_eq "#1004 the rendered region names every recorded identifier" "yes yes yes" \
  "$(_t1_has "$_t1_env_rendered" 'DEVFLOW_ALPHA') $(_t1_has "$_t1_env_rendered" 'DEVFLOW_BETA') $(_t1_has "$_t1_env_rendered" 'DEVFLOW_HATCH')"
assert_eq "#1004 the rendered region carries each row's failure mode" "yes" \
  "$(_t1_has "$_t1_env_rendered" 'the gate goes false')"
assert_eq "#1004 the rendered region states where the consumer sets each name" "yes" \
  "$(_t1_has "$_t1_env_rendered" 'GitHub settings')"
# The deliverable's defining property: an inventory, never a rename table. No row may
# render a PRFLOW_ counterpart for a frozen name — a rename column here would be read as an
# instruction, and following it degrades a consumer's install SILENTLY.
assert_eq "#1004 the rendered region proposes no PRFLOW_ counterpart for a frozen name" "no" \
  "$(_t1_has "$_t1_env_rendered" 'PRFLOW_ALPHA')"
assert_eq "#1004 the rendered region carries the do-not-rename instruction" "yes" \
  "$(_t1_has "$_t1_env_rendered" 'Do not rename them')"

assert_eq "#1004 the tamper fixture was applied" "done" \
  "$(python3 - "$_t1_env_r4/docs/internal/cloud-setup.md" <<'T1ENVTAMPER'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
lines = p.read_text(encoding="utf-8").split("\n")
for i, line in enumerate(lines):
    if line.startswith("> **These names are frozen"):
        lines[i] = "> hand-edited"
        break
else:
    print("marker-absent")
    raise SystemExit(0)
p.write_text("\n".join(lines), encoding="utf-8")
print("done")
T1ENVTAMPER
)"
_t1_env_o4="$(python3 "$T1_ENVGEN" --check --repo-root "$_t1_env_r4" 2>&1)"; _t1_env_rc4=$?
assert_eq "#1004 a hand-edited region is reported as drift (exit 1)" "1" "$_t1_env_rc4"
assert_eq "#1004 the drift report names the regeneration remedy" "yes" \
  "$(_t1_has "$_t1_env_o4" 'remedy: python3 lib/generate-env-freeze-advisory.py')"

# The banner is the region's only anchor, so a lost or duplicated one must fail CLOSED
# rather than let the generator guess where the region starts and overwrite prose.
for _t1_env_case in absent duplicate; do
  _t1_env_r5="$(_t1_root)"
  _t1_env_fixture "$_t1_env_r5" "$_t1_env_wf" "$_t1_env_doc" "$_t1_env_reader"
  _t1_env_map "$_t1_env_r5" "DEVFLOW_ALPHA" ""
  if [ "$_t1_env_case" = absent ]; then
    printf 'no region here\n' > "$_t1_env_r5/docs/internal/cloud-setup.md"
  else
    { printf '<!-- prflow-env-freeze:begin freeze_version=1 sha256=%064d (x) -->\n' 0
      printf '<!-- prflow-env-freeze:end -->\n'
      printf '<!-- prflow-env-freeze:begin freeze_version=1 sha256=%064d (x) -->\n' 0
      printf '<!-- prflow-env-freeze:end -->\n'; } > "$_t1_env_r5/docs/internal/cloud-setup.md"
  fi
  assert_eq "#1004 a $_t1_env_case begin banner fails closed (exit 2) rather than guessing" "2" \
    "$(python3 "$T1_ENVGEN" --repo-root "$_t1_env_r5" >/dev/null 2>&1; printf '%s' $?)"
done

# ── J6 — install.sh's advisory is gated to the upgrade population ──────────
# Issue #1004 measured that a cloud-only consumer never runs /prflow:init, so the advisory
# is not delivered there. install.sh is the cloud tier's only executable touchpoint, and
# the selector below keeps it from firing at a first-time installer who has not created any
# of these names yet. Both arms driven, including the negative controls.
_t1_env_installer_arm() { # <install-state> -> whatever the installer emits
  DEVFLOW_SELFTEST=1 . "$LIB/../install.sh" >/dev/null 2>&1
  devflow_report_env_identifier_freeze "$1" 2>&1
}
_t1_env_upgrade="$(_t1_env_installer_arm 'an existing')"
assert_eq "#1004 install.sh warns an EXISTING installation not to rename these names" "yes" \
  "$(_t1_has "$_t1_env_upgrade" 'DEVFLOW_* names are unchanged and must stay that way')"
assert_eq "#1004 the installer advisory routes to the generated inventory" "yes" \
  "$(_t1_has "$_t1_env_upgrade" 'docs/internal/cloud-setup.md')"
assert_eq "#1004 the installer advisory states that renaming fails silently" "yes" \
  "$(_t1_has "$_t1_env_upgrade" 'SILENTLY')"
assert_eq "#1004 install.sh stays SILENT for a first-time install (nothing is actionable yet)" \
  "" "$(_t1_env_installer_arm 'a first-time')"
assert_eq "#1004 install.sh stays silent for an unestablished install state" "" \
  "$(_t1_env_installer_arm '')"


# ────────────────────────────────────────────────────────────────────────────
echo "#1028 K. the superseded VALUE / nested-key migration, and what deliberately stays"
# ────────────────────────────────────────────────────────────────────────────
# Axis 2 of issue #1028. The key migration in block E renames TOP-LEVEL KEYS and stops
# there, so a consumer config kept the superseded product name in four more places:
# the `agent_overrides` `devflow:<leaf>` keys, the `workpad_marker` value, and the
# `docs.labels` / `deferred.labels` provenance-label values. lib/migrate-config-values.py
# renames those and reports what deliberately STAYS. Every assertion is behavioural: the
# helper is driven file-in/file-out over a fixture config and judged on its exit code, its
# emitted report and the resulting BYTES — no source-text pin (issues #375/#666/#810). The
# adversarial input-shape matrix leads, per CLAUDE.md's best-effort-parser rule.
T1_VALMIG="$LIB/migrate-config-values.py"
T1_TRIGGER="$LIB/../scripts/resolve-implement-trigger.sh"

# Runs the helper over a fixture config. Sets _t1_v_rc / _t1_v_rec / _t1_v_in / _t1_v_out.
# Called as a STATEMENT, never through a command substitution: a subshell would discard
# the output-path assignment every following assertion reads.
#   $1 the config JSON   $2 (optional) the example path; pass a bogus one to drive the
#      example-unreadable arm, an empty string to drive the example-omitted arm
_t1_v_run() {
  local d ex
  d="$(_t1_root)"
  ex="${2-$T1_EXAMPLE}"
  _t1_v_in="$d/in.json"
  _t1_v_out="$d/out.json"
  printf '%s' "$1" > "$_t1_v_in"
  _t1_v_rc=0
  _t1_v_rec="$(python3 "$T1_VALMIG" "$_t1_v_in" "$_t1_v_out" "$T1_MAP" "$ex" 2>/dev/null)" || _t1_v_rc=$?
}

# The JSON value at a dotted path in the migrated config, or the literal ABSENT. Read out
# of the written BYTES, so an assertion is about what a consumer would actually get.
_t1_v_get() {
  python3 -c '
import json, sys
node = json.load(open(sys.argv[1]))
for seg in sys.argv[2].split("."):
    if not isinstance(node, dict) or seg not in node:
        print("ABSENT"); raise SystemExit(0)
    node = node[seg]
print(json.dumps(node, ensure_ascii=False, sort_keys=True))' "$_t1_v_out" "$1" 2>/dev/null
}

# The key list of an object at a dotted path, IN FILE ORDER — a rename must keep an entry
# where it was, so the consumer diff reads as a rename rather than a reshuffle.
_t1_v_keys() {
  python3 -c '
import json, sys
node = json.load(open(sys.argv[1]))
for seg in sys.argv[2].split("."):
    if not isinstance(node, dict) or seg not in node:
        print("ABSENT"); raise SystemExit(0)
    node = node[seg]
print(",".join(node) if isinstance(node, dict) else "NOT-AN-OBJECT")' "$_t1_v_out" "$1" 2>/dev/null
}

_t1_v_wrote() { [ -f "$_t1_v_out" ] && printf 'yes' || printf 'no'; }

# — Rule 1: the `agent_overrides` namespace —
_t1_v_run '{"prflow_review":{"agent_overrides":{"default":{"effort":"low"},"devflow:code-reviewer":{"model":"mine"}}}}'
assert_eq "#1028 override key: renamed to the current namespace, keeping its position" \
  "0|default,prflow:code-reviewer" "$_t1_v_rc|$(_t1_v_keys prflow_review.agent_overrides)"
assert_eq "#1028 override key: the consumer VALUE is carried across untouched" \
  '{"model": "mine"}' "$(_t1_v_get 'prflow_review.agent_overrides.prflow:code-reviewer')"
assert_eq "#1028 override key: the rename is REPORTED, never silent" "yes yes" \
  "$(_t1_has "$_t1_v_rec" 'CHANGED') $(_t1_has "$_t1_v_rec" 'devflow:code-reviewer -> prflow:code-reviewer')"

# — Rule 2: the workpad marker. A PREFIX rule, per the rename map's own `match` for that
#   identifier, so a customised marker keeps its own leaf and a marker outside the
#   namespace is untouched. —
_t1_v_run '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->"}}'
assert_eq "#1028 workpad marker: the namespace prefix is rewritten" \
  '"<!-- prflow:workpad -->"' "$(_t1_v_get prflow.workpad_marker)"
_t1_v_run '{"prflow":{"workpad_marker":"<!-- devflow:my-own-pad -->"}}'
assert_eq "#1028 workpad marker: a customised marker keeps its own leaf" \
  '"<!-- prflow:my-own-pad -->"' "$(_t1_v_get prflow.workpad_marker)"
_t1_v_run '{"prflow":{"workpad_marker":"<!-- house:pad -->"}}'
assert_eq "#1028 workpad marker: one outside the marker namespace is left alone" \
  '"<!-- house:pad -->"' "$(_t1_v_get prflow.workpad_marker)"

# The pass takes NO freshness gate, so it works on a tree whose TOP-LEVEL key migration
# was refused and whose blocks are therefore still keyed under the superseded names.
_t1_v_run '{"devflow":{"workpad_marker":"<!-- devflow:workpad -->"},"devflow_review":{"agent_overrides":{"devflow:comment-analyzer":{}}}}'
assert_eq "#1028 no freshness gate: an un-migrated tree (blocks still under the superseded top-level names) still migrates" \
  '"<!-- prflow:workpad -->"|prflow:comment-analyzer' \
  "$(_t1_v_get devflow.workpad_marker)|$(_t1_v_keys devflow_review.agent_overrides)"

# — Rules 3 and 4: the provenance label inside the comma-separated label lists —
_t1_v_run '{"deferred":{"labels":"DevFlow,Deferred"},"docs":{"labels":"Documented"}}'
assert_eq "#1028 deferred.labels: the provenance entry is renamed and the rest of the list kept" \
  '"PRFlow,Deferred"' "$(_t1_v_get deferred.labels)"
assert_eq "#1028 docs.labels: an unrelated label value is untouched" \
  '"Documented"' "$(_t1_v_get docs.labels)"
_t1_v_run '{"docs":{"labels":" DevFlow , Documented "}}'
assert_eq "#1028 labels: the whitespace around a renamed entry is preserved" \
  '" PRFlow , Documented "' "$(_t1_v_get docs.labels)"
# ENTRY-WISE, never substring: a labels value is a list of label NAMES, so a label that
# merely contains the word — or spells it differently — is a different label.
_t1_v_run '{"docs":{"labels":"DevFlow-legacy,My DevFlow Label,devflow"}}'
assert_eq "#1028 labels: entry-wise, not substring — a label that merely CONTAINS the word is left alone" \
  '"DevFlow-legacy,My DevFlow Label,devflow"' "$(_t1_v_get docs.labels)"
# A collision here is the SAME label twice, not a conflicting edit: collapse it, keeping
# the first occurrence's position.
_t1_v_run '{"deferred":{"labels":"PRFlow,DevFlow,Deferred"}}'
assert_eq "#1028 labels: a rename that would duplicate an entry BEFORE it collapses instead" \
  '"PRFlow,Deferred"' "$(_t1_v_get deferred.labels)"
# Symmetric: a current-spelled entry sitting AFTER the superseded one collapses it just the
# same. A backward-only check would emit `Deferred,PRFlow,PRFlow` here.
_t1_v_run '{"deferred":{"labels":"Deferred,DevFlow,PRFlow"}}'
assert_eq "#1028 labels: a rename that would duplicate an entry AFTER it collapses too" \
  '"Deferred,PRFlow"' "$(_t1_v_get deferred.labels)"
_t1_v_run '{"deferred":{"labels":"DevFlow,DevFlow"}}'
assert_eq "#1028 labels: two superseded entries collapse onto one current entry" \
  '"PRFlow"' "$(_t1_v_get deferred.labels)"

# — The both-present conflict rule, mirroring block E's top-level shape —
_t1_v_run '{"prflow_review":{"agent_overrides":{"devflow:code-reviewer":{"model":"mine"},"prflow:code-reviewer":{"model":"theirs"}}}}'
assert_eq "#1028 both-present AUTHORED: the key is refused and BOTH entries survive" \
  "devflow:code-reviewer,prflow:code-reviewer" "$(_t1_v_keys prflow_review.agent_overrides)"
assert_eq "#1028 both-present AUTHORED: neither value is clobbered" \
  '{"model": "mine"}|{"model": "theirs"}' \
  "$(_t1_v_get 'prflow_review.agent_overrides.devflow:code-reviewer')|$(_t1_v_get 'prflow_review.agent_overrides.prflow:code-reviewer')"
assert_eq "#1028 both-present AUTHORED: the refusal is REPORTED, not silent" "yes yes" \
  "$(_t1_has "$_t1_v_rec" 'CONFLICT') $(_t1_has "$_t1_v_rec" 'prflow:code-reviewer')"
assert_eq "#1028 both-present AUTHORED: an unrelated key in the same block still migrates" \
  "devflow:code-reviewer,prflow:code-reviewer,prflow:comment-analyzer" \
  "$( _t1_v_run '{"prflow_review":{"agent_overrides":{"devflow:code-reviewer":{"model":"mine"},"prflow:code-reviewer":{"model":"theirs"},"devflow:comment-analyzer":{}}}}'; _t1_v_keys prflow_review.agent_overrides)"

# The GRAFTED case: the current-spelled entry still holds the shipped example default, so
# the scaffolder deep merge added it rather than the consumer authoring it. Built FROM the
# example rather than transcribing its value, which would rot the moment the example moves.
_t1_v_graft="$(python3 -c '
import json, sys
ao = json.load(open(sys.argv[1]))["prflow_review"]["agent_overrides"]
print(json.dumps({"prflow_review": {"agent_overrides": {
    "devflow:code-reviewer": {"model": "mine"},
    "prflow:code-reviewer": ao["prflow:code-reviewer"]}}}))' "$T1_EXAMPLE" 2>/dev/null)"
_t1_v_run "$_t1_v_graft"
assert_eq "#1028 both-present GRAFTED: the graft is resolved in place, one entry survives" \
  "prflow:code-reviewer" "$(_t1_v_keys prflow_review.agent_overrides)"
assert_eq "#1028 both-present GRAFTED: the consumer value wins over the shipped example default" \
  '{"model": "mine"}' "$(_t1_v_get 'prflow_review.agent_overrides.prflow:code-reviewer')"
# Without a readable example the grafted-versus-authored question cannot be answered, so
# the conservative arm is taken: refuse, keep both, report.
_t1_v_run "$_t1_v_graft" "$_t1_tmp_root/no-such-example.json"
assert_eq "#1028 both-present with the example UNREADABLE: refuse rather than guess" \
  "devflow:code-reviewer,prflow:code-reviewer" "$(_t1_v_keys prflow_review.agent_overrides)"

# — WHAT MUST NOT MOVE. Each of these breaks something if renamed, so byte-identity is
#   asserted on the resulting config, not merely "the migration did not say so". —
_t1_v_run '{"workflows":{"devflow":false,"devflow-review":true},"prflow":{"allowed_bots":"devflow-autopilot","workpad_marker":"<!-- devflow:workpad -->"},"prflow_implement":{"allowed_tools":["Bash(/home/runner/work/devflow-autopilot/devflow-autopilot/scripts/apply-labels.sh:*)","Bash(scripts/apply-labels.sh:*)"]}}'
assert_eq "#1028 frozen: the workflows.* toggle keys survive byte-identical (renaming one reads as disabled)" \
  '{"devflow": false, "devflow-review": true}' "$(_t1_v_get workflows)"
assert_eq "#1028 frozen: an allowed_bots GitHub login is not renamed (renaming it breaks authorization)" \
  '"devflow-autopilot"' "$(_t1_v_get prflow.allowed_bots)"
assert_eq "#1028 frozen: an absolute workspace grant path is not rewritten (it names the consumer own repository)" \
  '["Bash(/home/runner/work/devflow-autopilot/devflow-autopilot/scripts/apply-labels.sh:*)", "Bash(scripts/apply-labels.sh:*)"]' \
  "$(_t1_v_get prflow_implement.allowed_tools)"
assert_eq "#1028 frozen: and the migration still did its own job in that same config" \
  '"<!-- prflow:workpad -->"' "$(_t1_v_get prflow.workpad_marker)"

# — VALID-FALSY. A deliberate false / 0 / empty string keeps its meaning; nothing is
#   coerced onto a default by an `// default`-style extraction (issue #312). —
_t1_v_run '{"prflow":{"workpad_marker":"","allowed_bots":""},"deferred":{"labels":""},"docs":{"internal_enabled":false,"labels":"DevFlow"},"telemetry":{"max_rows":0}}'
assert_eq "#1028 valid-falsy: an explicit empty string, false and 0 all survive as themselves" \
  '""|""|false|0' \
  "$(_t1_v_get prflow.workpad_marker)|$(_t1_v_get deferred.labels)|$(_t1_v_get docs.internal_enabled)|$(_t1_v_get telemetry.max_rows)"
assert_eq "#1028 valid-falsy: the rename still applies to the real value beside them" \
  '"PRFlow"' "$(_t1_v_get docs.labels)"

# — IDEMPOTENT: a second run over the migrated config writes the same bytes and reports
#   no further rename. —
_t1_v_run '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->"},"prflow_review":{"agent_overrides":{"devflow:code-reviewer":{"model":"mine"}}},"deferred":{"labels":"DevFlow,Deferred"},"workflows":{"devflow":true}}'
_t1_v_first="$_t1_v_out"
_t1_v_second="$(_t1_root)/second.json"
_t1_v_rerec="$(python3 "$T1_VALMIG" "$_t1_v_first" "$_t1_v_second" "$T1_MAP" "$T1_EXAMPLE" 2>/dev/null)"
assert_eq "#1028 idempotent: a second run produces a BYTE-identical config" "yes" \
  "$(cmp -s "$_t1_v_first" "$_t1_v_second" && printf 'yes' || printf 'no')"
assert_eq "#1028 idempotent: and reports no further rename" "no" "$(_t1_has "$_t1_v_rerec" 'CHANGED')"

# — ADVERSARIAL SHAPE MATRIX over a config a human can hand-corrupt: object / array /
#   scalar / wrong-typed / missing at every level the pass reads. Exit 0, no crash, no
#   rename, and the malformed value left exactly as found. —
_t1_v_run '{"prflow":"scalar","prflow_review":{"agent_overrides":42},"docs":[],"deferred":{"labels":7},"workflows":"nope"}'
assert_eq "#1028 shape matrix: scalar / array / wrong-typed blocks are exit 0 and change nothing" \
  '0|"scalar"|42|[]|7' \
  "$_t1_v_rc|$(_t1_v_get prflow)|$(_t1_v_get prflow_review.agent_overrides)|$(_t1_v_get docs)|$(_t1_v_get deferred.labels)"
_t1_v_run '{"prflow_review":{"agent_overrides":{"devflow:x":"scalar-value","default":[1,2]}}}'
assert_eq "#1028 shape matrix: a non-object override VALUE is still renamed and carried across as-is" \
  'prflow:x,default|"scalar-value"' \
  "$(_t1_v_keys prflow_review.agent_overrides)|$(_t1_v_get 'prflow_review.agent_overrides.prflow:x')"
_t1_v_run '{}'
assert_eq "#1028 shape matrix: an empty config is exit 0 with an EMPTY report (nothing to say)" \
  "0|" "$_t1_v_rc|$_t1_v_rec"

# INPUT FAILURES: exit 2 and NOTHING written, so a caller can never mistake a failed read
# for a clean no-op and overwrite a config from it.
_t1_v_run '[1,2,3]'
assert_eq "#1028 input failure: a JSON array config is exit 2 and nothing is written" "2|no" \
  "$_t1_v_rc|$(_t1_v_wrote)"
_t1_v_run '{not valid json'
assert_eq "#1028 input failure: invalid JSON is exit 2 and nothing is written" "2|no" \
  "$_t1_v_rc|$(_t1_v_wrote)"
_t1_v_missing="$(_t1_root)"
_t1_v_rc=0
python3 "$T1_VALMIG" "$_t1_v_missing/absent.json" "$_t1_v_missing/o.json" "$T1_MAP" "$T1_EXAMPLE" >/dev/null 2>&1 || _t1_v_rc=$?
assert_eq "#1028 input failure: an absent config is exit 2 and nothing is written" "2|no" \
  "$_t1_v_rc|$([ -f "$_t1_v_missing/o.json" ] && printf 'yes' || printf 'no')"
# The rename map is the SINGLE SOURCE for every spelling this pass rewrites, so an
# unreadable one refuses the whole pass rather than falling back to a second copy.
printf '%s' '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->"}}' > "$_t1_v_missing/in.json"
_t1_v_rc=0
python3 "$T1_VALMIG" "$_t1_v_missing/in.json" "$_t1_v_missing/o2.json" "$_t1_v_missing/no-map.json" "$T1_EXAMPLE" >/dev/null 2>&1 || _t1_v_rc=$?
assert_eq "#1028 input failure: an unreadable rename map refuses the pass (no rename without its single source)" "2|no" \
  "$_t1_v_rc|$([ -f "$_t1_v_missing/o2.json" ] && printf 'yes' || printf 'no')"

# A PARTIAL DEPLOYMENT cannot resolve the accepted subagent namespaces, so the override arm
# is skipped — but NOT silently: a run that renamed the marker and the labels and quietly
# left the override keys alone would read as a migration that half-worked with no reason
# given. Simulated by staging the helper beside its lib/ siblings WITHOUT the plugin
# manifest the identity reader needs, which is exactly what a truncated install looks like.
_t1_v_partial="$(_t1_root)"
mkdir -p "$_t1_v_partial/lib"
cp "$T1_VALMIG" "$LIB/plugin_identity.py" "$LIB/plugin-identity.json" "$T1_MAP" "$_t1_v_partial/lib/"
printf '%s' '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->"},"prflow_review":{"agent_overrides":{"devflow:code-reviewer":{"model":"mine"}}},"deferred":{"labels":"DevFlow"}}' \
  > "$_t1_v_partial/in.json"
_t1_v_rc=0
_t1_v_rec="$(python3 "$_t1_v_partial/lib/migrate-config-values.py" "$_t1_v_partial/in.json" \
  "$_t1_v_partial/out.json" "$_t1_v_partial/lib/rename-map.json" "$T1_EXAMPLE" 2>/dev/null)" || _t1_v_rc=$?
_t1_v_out="$_t1_v_partial/out.json"
assert_eq "#1028 partial deployment: exit 0 and the other arms still migrate" \
  '0|"<!-- prflow:workpad -->"|"PRFlow"' \
  "$_t1_v_rc|$(_t1_v_get prflow.workpad_marker)|$(_t1_v_get deferred.labels)"
assert_eq "#1028 partial deployment: the override key is left as it was" \
  "devflow:code-reviewer" "$(_t1_v_keys prflow_review.agent_overrides)"
assert_eq "#1028 partial deployment: the skipped arm is DISCLOSED, never silent" "yes yes" \
  "$(_t1_has "$_t1_v_rec" 'NOTE') $(_t1_has "$_t1_v_rec" 'agent_overrides')"

# A rename map whose `frozen` block is the wrong TYPE must not traceback: an uncaught error
# after the migrated file is written but before the caller is told to swap it in would
# silently discard a migration the same run just reported.
_t1_v_badmap="$(_t1_root)/bad-map.json"
python3 -c '
import json, sys
m = json.load(open(sys.argv[1]))
m["frozen"] = "not-an-object"
json.dump(m, open(sys.argv[2], "w"))' "$T1_MAP" "$_t1_v_badmap"
_t1_v_badroot="$(_t1_root)"
printf '%s' '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->"},"workflows":{"devflow":true}}' \
  > "$_t1_v_badroot/in.json"
_t1_v_rc=0
_t1_v_rec="$(python3 "$T1_VALMIG" "$_t1_v_badroot/in.json" "$_t1_v_badroot/out.json" \
  "$_t1_v_badmap" "$T1_EXAMPLE" 2>/dev/null)" || _t1_v_rc=$?
_t1_v_out="$_t1_v_badroot/out.json"
assert_eq "#1028 wrong-typed frozen block: exit 0, the rename still applies, no residual notice" \
  '0|"<!-- prflow:workpad -->"|no' \
  "$_t1_v_rc|$(_t1_v_get prflow.workpad_marker)|$(_t1_has "$_t1_v_rec" 'ADVISORY')"

# — THE RESIDUAL NOTICE IS RETIRED (#1041). With the workflows.* sub-keys no longer
#   frozen (frozen.config_keys is now empty), the value pass has no frozen config key to
#   report, so it emits NO residual advisory. The DEVFLOW_* environment freeze reminder is
#   owned canonically by lib/generate-env-freeze-advisory.py (single source), not restated
#   by this pass. The value pass STILL leaves the workflows.* keys untouched — their
#   migration is the scaffold freshness gate's job, exercised in the scaffold-integration
#   block below. —
_t1_v_run '{"workflows":{"devflow":true,"devflow-review":false}}'
assert_eq "#1041 residual notice retired: the value pass emits no ADVISORY for the workflows.* keys" "no" \
  "$(_t1_has "$_t1_v_rec" 'ADVISORY')"
assert_eq "#1041 residual notice retired: and leaves the workflows.* keys byte-identical (gate territory, not this pass)" \
  '{"devflow": true, "devflow-review": false}' "$(_t1_v_get workflows)"
_t1_v_run '{"prflow":{"workpad_marker":"<!-- prflow:workpad -->"}}'
assert_eq "#1041 residual notice retired: a config carrying no superseded value draws no notice" "no" \
  "$(_t1_has "$_t1_v_rec" 'ADVISORY')"

# — SELF-TRIGGER GUARD. Renaming the configured marker must not stop the guard matching a
#   PRE-rename workpad: it derives the superseded spelling from the configured one, and a
#   guard that stopped matching would fail OPEN into a duplicate cloud run. Driven with an
#   unauthorized actor and no repo, so the arm under test resolves before any gh call. —
_t1_v_guard() { # <configured marker> <comment body> -> yes|no (did the guard decline?)
  local err
  err="$(SELF_COMMENT_MARKER="$1" TRIGGER_TEXT="$2" ACTOR="nobody" ALLOWED_BOTS="" \
    ALLOWED_USERS="" REPO="" CONTEXT_NUMBER="7" IS_PULL_REQUEST="false" \
    bash "$T1_TRIGGER" 2>&1 >/dev/null || true)"
  _t1_has "$err" 'self-trigger guard'
}
assert_eq "#1028 self-trigger guard: with the MIGRATED marker configured a pre-rename workpad is still declined" "yes" \
  "$(_t1_v_guard '<!-- prflow:workpad -->' 'note <!-- devflow:workpad --> quoting the implement command')"
assert_eq "#1028 self-trigger guard: and so is a post-rename workpad" "yes" \
  "$(_t1_v_guard '<!-- prflow:workpad -->' 'note <!-- prflow:workpad --> quoting the implement command')"
assert_eq "#1028 self-trigger guard: an ordinary human comment is NOT declined by it" "no" \
  "$(_t1_v_guard '<!-- prflow:workpad -->' 'please run the implement command on 7')"

# — SCAFFOLDER INTEGRATION. install.sh --apply and the init skill each call this one
#   scaffolder, so siting the pass here also reaches a consumer running the cloud tier
#   alone, which never invokes the local-tier init skill (the #1004 constraint). —
_t1_r="$(_t1_scaffold_root '{"prflow":{"workpad_marker":"<!-- devflow:workpad -->","allowed_bots":"devflow-autopilot"},"prflow_review":{"agent_overrides":{"devflow:code-reviewer":{"model":"mine"}}},"deferred":{"labels":"DevFlow,Deferred"},"docs":{"labels":"DevFlow"},"workflows":{"devflow":false,"devflow-review":false}}')"
_t1_out="$("$T1_SCAFFOLD" "$_t1_r" 2>&1)"
assert_eq "#1028 scaffold integration: the value migration runs end-to-end and says so" "yes" \
  "$(_t1_has "$_t1_out" 'migrated superseded config value')"
assert_eq "#1028 scaffold integration: all four renames land in the written config" \
  '<!-- prflow:workpad --> prflow:code-reviewer PRFlow,Deferred PRFlow' \
  "$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
ao = d["prflow_review"]["agent_overrides"]
print(d["prflow"]["workpad_marker"],
      ",".join(sorted(k for k in ao if k.endswith("code-reviewer"))),
      d["deferred"]["labels"], d["docs"]["labels"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
# #1041: the workflows.* toggles now MIGRATE through the same scaffold (fresh shipped
# workflows read .workflows.prflow, so the freshness gate passes), carrying their
# valid-falsy `false` values across verbatim — never coerced to a default. The bot login
# still survives untouched.
assert_eq "#1041 scaffold integration: the workflows.* toggles migrate (false preserved) and the bot login survives" \
  '{"prflow": false, "prflow-review": false}|devflow-autopilot' \
  "$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(json.dumps(d.get("workflows"), sort_keys=True) + "|" + d["prflow"]["allowed_bots"])' "$_t1_r/.prflow/config.json" 2>/dev/null)"
cp "$_t1_r/.prflow/config.json" "$_t1_tmp_root/scaffold-first.json"
"$T1_SCAFFOLD" "$_t1_r" >/dev/null 2>&1
assert_eq "#1028 scaffold integration: a second scaffold leaves the config BYTE-identical" "yes" \
  "$(cmp -s "$_t1_tmp_root/scaffold-first.json" "$_t1_r/.prflow/config.json" && printf 'yes' || printf 'no')"
assert_eq "#1028 scaffold integration: an already-current config draws no rename line" "no" \
  "$("$T1_SCAFFOLD" "$(_t1_scaffold_root '{"prflow":{"workpad_marker":"<!-- prflow:workpad -->"}}')" 2>&1 \
    | { grep -q 'migrated superseded config value' && printf 'yes' || printf 'no'; })"

# — The migration helper's TRACKED MODE (issue #1312 residual) —
# install.sh gates the atomic Tier-1 migration on
# `[ -x "$SRC/scripts/migrate-consumer-tier1.sh" ]` and falls through to a warning when
# that test fails, so a lost executable bit silently no-ops the whole migration in every
# consumer. install.sh is a NAMED RESIDUAL of lib/test/lint-executable-helper-mode.py
# (its `$SRC` anchor is positively runtime — a materialized source tree, not this
# checkout), so this module owns that helper's mode. The INDEX mode is what ships, hence
# `git ls-files -s` rather than a filesystem stat; the field is split with a bash builtin
# read (not `cut`, a non-preflight PATH tool).
_t1_index_mode() {
  local mode _rest
  read -r mode _rest < <(git -C "$LIB/.." ls-files -s -- "$1" 2>/dev/null)
  printf '%s' "${mode:-ABSENT}"
}
assert_eq "#1312 migrate-consumer-tier1.sh is tracked executable (install.sh -x-gates it)" \
  "100755" "$(_t1_index_mode scripts/migrate-consumer-tier1.sh)"

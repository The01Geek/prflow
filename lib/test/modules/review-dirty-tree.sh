# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable focused module for the review engine's dirty-tree backstop helper
# scripts/review-dirty-tree.sh (issues #2082, #216, #484, #1470, #192; extracted
# into this module by issue #2109). Contract: the caller sets LIB and RESULTS_FILE,
# defines assert_eq, and sources lib/test/module-harness.sh first. This module uses
# assert_eq plus the harness's git_sandbox / probe_tmp / module_host_capability_skip
# helpers — it references NO monolith helper, owns no private trap, and self-skips
# only through the sanctioned host-capability path. The inventory in
# review-dirty-tree.inventory.md records the module's provenance.
#
# WHAT THIS MODULE OWNS. The committed dirty-tree helper scripts/review-dirty-tree.sh
# and its real runtime behaviour (issue #2082). Every assertion is behavioural: the
# helper is driven directly (`bash "$RDT" snapshot|compare-and-restore OID`, setting
# the GIT_SNAP_BEFORE/GIT_SNAP_AFTER env seam it retains internally) against real
# throwaway git repositories allocated by the harness's git_sandbox — the git plumbing
# under test is not mocked — and judged on the resulting working-tree state and the
# helper's stderr breadcrumbs and exit code. There is no wording-only pin here
# (issues #375/#666/#810). The skill<->helper wiring and fence-shape prose pins stay in
# lib/test/run.sh: those assert the review bundle's prose, not the helper's behaviour.

REPO_ROOT="$LIB/.."
RDT="$REPO_ROOT/scripts/review-dirty-tree.sh"

# Host-capability probe: several arms drive symlink-attack scenarios (a stale/raced
# symlink at the snapshot path). A host that cannot create symlinks genuinely cannot run
# those arms, so they route through module_host_capability_skip rather than a raw skip.
_RDT_SYMLINK_OK=0
_rdt_probe="$(mktemp -d 2>/dev/null)" || _rdt_probe=""
if [ -n "$_rdt_probe" ] && ln -s target "$_rdt_probe/link" 2>/dev/null && [ -L "$_rdt_probe/link" ]; then
  _RDT_SYMLINK_OK=1
fi
[ -n "$_rdt_probe" ] && rm -rf "$_rdt_probe"

# ── Helper existence + main() CLI dispatch (AC4: a malformed invocation never restores) ──
assert_eq "#2082 backstop: the committed helper exists and is executable" "yes" \
  "$([ -f "$RDT" ] && [ -x "$RDT" ] && echo yes || echo no)"
assert_eq "#2082 helper main(): no subcommand exits 2" "2" \
  "$(bash "$RDT" 2>/dev/null; echo $?)"
assert_eq "#2082 helper main(): an unknown subcommand exits 2" "2" \
  "$(bash "$RDT" bogus-subcommand 2>/dev/null; echo $?)"
assert_eq "#2082 helper main(): compare-and-restore with an empty OID exits 2 (AC4 authorizer required)" "2" \
  "$(bash "$RDT" compare-and-restore '' 2>/dev/null; echo $?)"
assert_eq "#2082 helper main(): compare-and-restore with no OID exits 2" "2" \
  "$(bash "$RDT" compare-and-restore 2>/dev/null; echo $?)"
assert_eq "#2082 helper main(): snapshot with an extra argument exits 2" "2" \
  "$(bash "$RDT" snapshot extra-arg 2>/dev/null; echo $?)"

# ── Snapshot behaviour — stale-symlink removal, authenticated -z capture, no sentinel ──
# (symlink-attack arm: needs symlink support to build the stale/raced snapshot symlink).
if [ "$_RDT_SYMLINK_OK" = 1 ]; then
  DT_S="$(git_sandbox "#484 before-snapshot stale-symlink repo")"
  if [ -d "$DT_S" ]; then
    git -C "$DT_S" init -q
    DT_S_B="$DT_S/before"; DT_S_V="$(probe_tmp "#484 before-snapshot stale-symlink target")"
    printf 'target sentinel' > "$DT_S_V"; ln -s "$DT_S_V" "$DT_S_B"
    DT_S_OID="$(cd "$DT_S" && GIT_SNAP_BEFORE="$DT_S_B" bash "$RDT" snapshot 2>/dev/null)"
    assert_eq "#484 before-snapshot: stale symlink is removed without clobbering its target" \
      "target sentinel" "$(cat "$DT_S_V")"
    assert_eq "#216 before-snapshot: real -z capture produces an authenticated regular file" "yes" \
      "$([ -f "$DT_S_B" ] && [ ! -L "$DT_S_B" ] && [ -n "$DT_S_OID" ] && [ "$DT_S_OID" = "$(git hash-object "$DT_S_B")" ] && echo yes || echo no)"
    assert_eq "#216 before-snapshot: successful capture does not leave the disabled sentinel" "no" \
      "$([ -e "$DT_S/.prflow/tmp/review-dirty-tree-disabled" ] && echo yes || echo no)"
    rm -rf "$DT_S" "$DT_S_V"
  fi

  DT_SR="$(git_sandbox "#484 before-snapshot symlink-race repo")"
  if [ -d "$DT_SR" ]; then
    git -C "$DT_SR" init -q
    DT_SR_B="$DT_SR/before"; DT_SR_V="$(probe_tmp "#484 before-snapshot symlink-race target")"
    DT_SR_BIN="$DT_SR/bin"; mkdir -p "$DT_SR_BIN"
    printf 'target sentinel' > "$DT_SR_V"
    DT_REAL_GIT="$(command -v git)"
    printf '%s\n' '#!/usr/bin/env bash' \
      'if [ "${1:-}" = status ]; then' \
      '  rm -f "$GIT_SNAP_BEFORE"; ln -s "$DT_RACE_TARGET" "$GIT_SNAP_BEFORE"' \
      'fi' \
      'exec "$DT_REAL_GIT" "$@"' > "$DT_SR_BIN/git"
    chmod +x "$DT_SR_BIN/git"
    ( cd "$DT_SR" && PATH="$DT_SR_BIN:$PATH" DT_REAL_GIT="$DT_REAL_GIT" \
        DT_RACE_TARGET="$DT_SR_V" GIT_SNAP_BEFORE="$DT_SR_B" bash "$RDT" snapshot ) >/dev/null 2>&1
    assert_eq "#484 before-snapshot: a race-swapped symlink disables the backstop" "yes" \
      "$([ -f "$DT_SR/.prflow/tmp/review-dirty-tree-disabled" ] && echo yes || echo no)"
    assert_eq "#484 before-snapshot: symlink-race target remains untouched" \
      "target sentinel" "$(cat "$DT_SR_V")"
    rm -rf "$DT_SR" "$DT_SR_V"
  fi
else
  module_host_capability_skip "#484 before-snapshot stale/race symlink arms" \
    "host cannot create symlinks; the snapshot-side symlink-attack arms cannot run here" 5
fi

# Build a fresh sandbox repo with a committed spaced-path file + a plain file (fail-closed
# on mktemp -d failure via git_sandbox's /dev/null sentinel — a caller's `[ -d ]` guard skips).
dt_make_repo() {  # -> prints repo dir
  local d; d="$(git_sandbox "#216 backstop fixture")" || { printf '%s\n' "$d"; return 1; }
  git -C "$d" init -q; git -C "$d" config user.email t@t; git -C "$d" config user.name t
  printf orig > "$d/my file.txt"; printf plain > "$d/plain.txt"
  git -C "$d" add -A; git -C "$d" commit -qm init
  printf '%s\n' "$d"
}
# Case A — spaced-path modify with `-z` snapshots: RESTORED (GREEN).
DT_A="$(dt_make_repo)"
if [ -d "$DT_A" ]; then
  DT_A_B="$(probe_tmp "#216 case-A before")"; DT_A_AF="$(probe_tmp "#216 case-A after")"
  git -C "$DT_A" status --porcelain -z > "$DT_A_B"
  DT_A_OID="$(git hash-object "$DT_A_B")"
  printf changed > "$DT_A/my file.txt"
  git -C "$DT_A" status --porcelain -z > "$DT_A_AF"
  ( cd "$DT_A" && GIT_SNAP_BEFORE="$DT_A_B" GIT_SNAP_AFTER="$DT_A_AF" bash "$RDT" compare-and-restore "$DT_A_OID" ) >/dev/null 2>&1
  assert_eq "#216 backstop: a spaced-path agent modification is restored (-z snapshots)" \
    "orig" "$(cat "$DT_A/my file.txt" 2>/dev/null)"
  rm -rf "$DT_A" "$DT_A_B" "$DT_A_AF"
fi
# Case C — true staged rename: SURFACED, NOT auto-restored (the file stays renamed).
DT_C="$(dt_make_repo)"
if [ -d "$DT_C" ]; then
  DT_C_B="$(probe_tmp "#216 case-C before")"; DT_C_AF="$(probe_tmp "#216 case-C after")"
  git -C "$DT_C" status --porcelain -z > "$DT_C_B"
  DT_C_OID="$(git hash-object "$DT_C_B")"
  git -C "$DT_C" mv "plain.txt" "renamed plain.txt"
  git -C "$DT_C" status --porcelain -z > "$DT_C_AF"
  ( cd "$DT_C" && GIT_SNAP_BEFORE="$DT_C_B" GIT_SNAP_AFTER="$DT_C_AF" bash "$RDT" compare-and-restore "$DT_C_OID" ) >/dev/null 2>&1
  assert_eq "#216 backstop: a true rename is surfaced-not-restored (renamed file remains)" \
    "plain" "$(cat "$DT_C/renamed plain.txt" 2>/dev/null)"
  assert_eq "#216 backstop: a true rename leaves the original path removed (not auto-recreated)" \
    "no" "$([ -e "$DT_C/plain.txt" ] && echo yes || echo no)"
  rm -rf "$DT_C" "$DT_C_B" "$DT_C_AF"
fi
# Case D — the CENTRAL by-path safety property: an already-modified path is left untouched
# while a DIFFERENT path an agent newly dirtied during the window IS restored.
DT_D="$(dt_make_repo)"
if [ -d "$DT_D" ]; then
  DT_D_B="$(probe_tmp "#216 case-D before")"; DT_D_AF="$(probe_tmp "#216 case-D after")"
  printf 'concurrent edit' > "$DT_D/my file.txt"   # orchestrator's OWN edit — dirty BEFORE dispatch
  git -C "$DT_D" status --porcelain -z > "$DT_D_B"
  DT_D_OID="$(git hash-object "$DT_D_B")"
  printf 'agent edit' > "$DT_D/plain.txt"          # a DIFFERENT path an agent dirties DURING the window
  git -C "$DT_D" status --porcelain -z > "$DT_D_AF"
  ( cd "$DT_D" && GIT_SNAP_BEFORE="$DT_D_B" GIT_SNAP_AFTER="$DT_D_AF" bash "$RDT" compare-and-restore "$DT_D_OID" ) >/dev/null 2>&1
  assert_eq "#216 backstop: an already-dirty path (clean->dirty BEFORE dispatch) is NOT clobbered by the restore" \
    "concurrent edit" "$(cat "$DT_D/my file.txt" 2>/dev/null)"
  assert_eq "#216 backstop: a newly-dirtied path (dirtied DURING the window) IS restored to HEAD" \
    "plain" "$(cat "$DT_D/plain.txt" 2>/dev/null)"
  rm -rf "$DT_D" "$DT_D_B" "$DT_D_AF"
fi
# Case D2 — checkout cannot remove an untracked file; the post-restore tree-state check must
# surface that residual instead of trusting checkout's failure.
DT_D2="$(dt_make_repo)"
if [ -d "$DT_D2" ]; then
  DT_D2_B="$(probe_tmp "#192 case-D2 before")"; DT_D2_AF="$(probe_tmp "#192 case-D2 after")"
  TMP_D2_ERR="$(probe_tmp "#192 case-D2 stderr")"
  git -C "$DT_D2" status --porcelain -z > "$DT_D2_B"
  DT_D2_OID="$(git hash-object "$DT_D2_B")"
  printf 'agent-created' > "$DT_D2/untracked.txt"
  git -C "$DT_D2" status --porcelain -z > "$DT_D2_AF"
  ( cd "$DT_D2" && GIT_SNAP_BEFORE="$DT_D2_B" GIT_SNAP_AFTER="$DT_D2_AF" bash "$RDT" compare-and-restore "$DT_D2_OID" ) >/dev/null 2>"$TMP_D2_ERR"
  assert_eq "#192 backstop: an untracked dispatch-window file is never auto-deleted" \
    "agent-created" "$(cat "$DT_D2/untracked.txt")"
  # Two single-quoted greps (never one double-quoted literal wrapping the single-quoted path,
  # which the mutation-routing classifier mis-parses as a raw source-presence pin): together they
  # verify the breadcrumb NAMES the offending path — a broken/empty $p interpolation fails the
  # untracked.txt grep, which the suffix-only check alone would pass GREEN.
  assert_eq "#192 backstop: failed restore is detected from live tree state and breadcrumbed" "yes" \
    "$(grep -qF untracked.txt "$TMP_D2_ERR" && grep -qF 'still dirty after restore attempt' "$TMP_D2_ERR" && echo yes || echo no)"
  rm -rf "$DT_D2" "$DT_D2_B" "$DT_D2_AF" "$TMP_D2_ERR"
fi
# Case E — a truncated non-NUL BEFORE record must fail closed (leftover-record check).
DT_E="$(dt_make_repo)"
if [ -d "$DT_E" ]; then
  DT_E_B="$(probe_tmp "#484 case-E before")"; DT_E_AF="$(probe_tmp "#484 case-E after")"
  printf ' M my file.txt' > "$DT_E_B"                 # deliberately missing the required NUL
  DT_E_OID="$(git hash-object "$DT_E_B")"
  printf 'concurrent edit' > "$DT_E/my file.txt"      # must never be restored from HEAD
  printf 'agent edit' > "$DT_E/plain.txt"
  git -C "$DT_E" status --porcelain -z > "$DT_E_AF"
  ( cd "$DT_E" && GIT_SNAP_BEFORE="$DT_E_B" GIT_SNAP_AFTER="$DT_E_AF" bash "$RDT" compare-and-restore "$DT_E_OID" ) >/dev/null 2>&1
  assert_eq "#484 backstop: truncated BEFORE snapshot fails closed without clobbering an existing edit" \
    "concurrent edit" "$(cat "$DT_E/my file.txt" 2>/dev/null)"
  assert_eq "#484 backstop: truncated BEFORE snapshot skips all restoration" \
    "agent edit" "$(cat "$DT_E/plain.txt" 2>/dev/null)"
  rm -rf "$DT_E" "$DT_E_B" "$DT_E_AF"
fi
# Case D3 — the same central by-path property on a GLOB-metacharacter and a NEWLINE-containing
# pathname (a membership test rewritten to `[[ $bp == ${rec:3} ]]` would clobber these while
# leaving the spaced fixtures GREEN).
DT_D3="$(dt_make_repo)"
if [ -d "$DT_D3" ]; then
  DT_D3_B="$(probe_tmp "#1470 case-D3 before")"; DT_D3_AF="$(probe_tmp "#1470 case-D3 after")"
  DT_D3_NL="$(printf 'new\nline.txt')"
  printf brack > "$DT_D3/g[ab].txt"; printf nl > "$DT_D3/$DT_D3_NL"; printf star > "$DT_D3/f*.txt"
  git -C "$DT_D3" add -A; git -C "$DT_D3" commit -qm special
  printf 'concurrent edit' > "$DT_D3/g[ab].txt"   # orchestrator's OWN edit — glob metacharacters
  printf 'concurrent nl' > "$DT_D3/$DT_D3_NL"     # orchestrator's OWN edit — embedded newline
  git -C "$DT_D3" status --porcelain -z > "$DT_D3_B"
  DT_D3_OID="$(git hash-object "$DT_D3_B")"
  printf 'agent edit' > "$DT_D3/f*.txt"           # a DIFFERENT glob path dirtied DURING the window
  git -C "$DT_D3" status --porcelain -z > "$DT_D3_AF"
  ( cd "$DT_D3" && GIT_SNAP_BEFORE="$DT_D3_B" GIT_SNAP_AFTER="$DT_D3_AF" bash "$RDT" compare-and-restore "$DT_D3_OID" ) >/dev/null 2>&1
  assert_eq "#1470 backstop: an already-dirty GLOB-metacharacter path is NOT clobbered by the restore" \
    "concurrent edit" "$(cat "$DT_D3/g[ab].txt" 2>/dev/null)"
  assert_eq "#1470 backstop: an already-dirty NEWLINE-containing path is NOT clobbered by the restore" \
    "concurrent nl" "$(cat "$DT_D3/$DT_D3_NL" 2>/dev/null)"
  assert_eq "#1470 backstop: a newly-dirtied glob-metacharacter path IS restored to HEAD" \
    "star" "$(cat "$DT_D3/f*.txt" 2>/dev/null)"
  rm -rf "$DT_D3" "$DT_D3_B" "$DT_D3_AF"
fi
# DEFERRAL (#1470 review, Important 2 — `set -u` guard coverage): the `${before_paths[@]+…}`
# guard still carries no dedicated RED-mutation test. Its context changed with issue #2082:
# the logic is now the committed helper scripts/review-dirty-tree.sh, which DOES `set -u`, so
# the guard is exercised whenever the restore set is empty (the pre-#2082 note assumed
# otherwise). (1) Bash stopped erroring on `"${empty[@]}"` under `set -u` in 4.4, so the guard
# is a no-op on every bash the suite runs (CI ubuntu 5.x; maintainer host PATH bash 5.3) — a
# committed case cannot go RED there, and a vacuous guard is what this suite's mutation-check
# discipline forbids. (2) Measured on bash 3.2.57, removing the guard fails CLOSED and loud
# under the helper's `set -u`: `unbound variable` on stderr and the helper aborts before
# restoring anything, so no concurrent edit is clobbered.
# Case F — OID-authentication positive control: the authentic object ID proceeds into restore,
# preserving an already-dirty path while restoring the agent-introduced path.
DT_F="$(dt_make_repo)"
if [ -d "$DT_F" ]; then
  DT_F_B="$(probe_tmp "#484 case-F before")"; DT_F_AF="$(probe_tmp "#484 case-F after")"
  printf 'concurrent edit' > "$DT_F/my file.txt"
  git -C "$DT_F" status --porcelain -z > "$DT_F_B"
  DT_F_OID="$(git hash-object "$DT_F_B")"
  printf 'agent edit' > "$DT_F/plain.txt"
  ( cd "$DT_F" && GIT_SNAP_BEFORE="$DT_F_B" GIT_SNAP_AFTER="$DT_F_AF" bash "$RDT" compare-and-restore "$DT_F_OID" ) >/dev/null 2>&1
  assert_eq "#484 backstop auth positive control: authentic OID preserves the pre-existing edit" \
    "concurrent edit" "$(cat "$DT_F/my file.txt" 2>/dev/null)"
  assert_eq "#484 backstop auth positive control: authentic OID permits snapshot-delta restore" \
    "plain" "$(cat "$DT_F/plain.txt" 2>/dev/null)"
  rm -rf "$DT_F" "$DT_F_B" "$DT_F_AF"
fi
# Case G — a forged regular baseline (replaced after recording its OID) authorizes nothing.
DT_G="$(dt_make_repo)"
if [ -d "$DT_G" ]; then
  DT_G_B="$(probe_tmp "#484 case-G before")"; DT_G_AF="$(probe_tmp "#484 case-G after")"
  DT_G_ERR="$(probe_tmp "#484 case-G stderr")"
  printf 'concurrent edit' > "$DT_G/my file.txt"
  git -C "$DT_G" status --porcelain -z > "$DT_G_B"
  DT_G_OID="$(git hash-object "$DT_G_B")"
  printf 'agent edit' > "$DT_G/plain.txt"
  printf '' > "$DT_G_B"  # forged regular-file baseline
  ( cd "$DT_G" && GIT_SNAP_BEFORE="$DT_G_B" GIT_SNAP_AFTER="$DT_G_AF" bash "$RDT" compare-and-restore "$DT_G_OID" ) >/dev/null 2>"$DT_G_ERR"
  assert_eq "#484 backstop auth: forged regular baseline cannot clobber the pre-existing edit" \
    "concurrent edit" "$(cat "$DT_G/my file.txt" 2>/dev/null)"
  assert_eq "#484 backstop auth: forged regular baseline skips all restoration" \
    "agent edit" "$(cat "$DT_G/plain.txt" 2>/dev/null)"
  assert_eq "#484 backstop auth: forged regular baseline emits the integrity breadcrumb" "yes" \
    "$(grep -qF 'scratch integrity failure, nothing auto-restored' "$DT_G_ERR" && echo yes || echo no)"
  rm -rf "$DT_G" "$DT_G_B" "$DT_G_AF" "$DT_G_ERR"
fi
# Case H — a symlink baseline is rejected before hashing/comparison and its target is untouched
# (symlink-attack arm).
if [ "$_RDT_SYMLINK_OK" = 1 ]; then
  DT_H="$(dt_make_repo)"
  if [ -d "$DT_H" ]; then
    DT_H_TARGET="$(probe_tmp "#484 case-H symlink target")"; DT_H_B="$DT_H/before-link"
    DT_H_AF="$(probe_tmp "#484 case-H after")"; DT_H_ERR="$(probe_tmp "#484 case-H stderr")"
    printf 'target sentinel' > "$DT_H_TARGET"; ln -s "$DT_H_TARGET" "$DT_H_B"
    DT_H_OID="$(git hash-object "$DT_H_TARGET")"
    printf 'agent edit' > "$DT_H/plain.txt"
    ( cd "$DT_H" && GIT_SNAP_BEFORE="$DT_H_B" GIT_SNAP_AFTER="$DT_H_AF" bash "$RDT" compare-and-restore "$DT_H_OID" ) >/dev/null 2>"$DT_H_ERR"
    assert_eq "#484 backstop auth: symlink baseline skips restoration" \
      "agent edit" "$(cat "$DT_H/plain.txt" 2>/dev/null)"
    assert_eq "#484 backstop auth: symlink baseline target is never modified" \
      "target sentinel" "$(cat "$DT_H_TARGET" 2>/dev/null)"
    assert_eq "#484 backstop auth: symlink baseline emits the tamper breadcrumb" "yes" \
      "$(grep -qF 'possible scratch tampering, nothing auto-restored' "$DT_H_ERR" && echo yes || echo no)"
    rm -rf "$DT_H" "$DT_H_TARGET" "$DT_H_AF" "$DT_H_ERR"
  fi
else
  module_host_capability_skip "#484 case-H symlink baseline arm" \
    "host cannot create symlinks; the symlink-baseline arm cannot run here" 3
fi
# Case I — an attacker-controlled stale AFTER symlink must be removed before the status
# redirect opens (symlink-attack arm).
if [ "$_RDT_SYMLINK_OK" = 1 ]; then
  DT_I="$(dt_make_repo)"
  if [ -d "$DT_I" ]; then
    DT_I_B="$(probe_tmp "#484 case-I before")"; DT_I_AF="$DT_I/after-link"
    DT_I_TARGET="$(probe_tmp "#484 case-I stale-after target")"
    git -C "$DT_I" status --porcelain -z > "$DT_I_B"
    DT_I_OID="$(git hash-object "$DT_I_B")"
    printf 'target sentinel' > "$DT_I_TARGET"; ln -s "$DT_I_TARGET" "$DT_I_AF"
    ( cd "$DT_I" && GIT_SNAP_BEFORE="$DT_I_B" GIT_SNAP_AFTER="$DT_I_AF" bash "$RDT" compare-and-restore "$DT_I_OID" ) >/dev/null 2>&1
    assert_eq "#484 after-snapshot: stale symlink is removed before capture, so its target is not clobbered" \
      "target sentinel" "$(cat "$DT_I_TARGET")"
    rm -rf "$DT_I" "$DT_I_B" "$DT_I_AF" "$DT_I_TARGET"
  fi
else
  module_host_capability_skip "#484 case-I stale-after symlink arm" \
    "host cannot create symlinks; the stale-after-symlink arm cannot run here" 1
fi
# Case J — a symlink swapped into the AFTER path while `git status` runs is rejected as a
# snapshot failure (symlink-attack arm, PATH-shimmed git).
if [ "$_RDT_SYMLINK_OK" = 1 ]; then
  DT_J="$(dt_make_repo)"
  if [ -d "$DT_J" ]; then
    DT_J_B="$(probe_tmp "#484 case-J before")"; DT_J_AF="$DT_J/after"
    DT_J_TARGET="$(probe_tmp "#484 case-J symlink-race target")"
    DT_J_ERR="$(probe_tmp "#484 case-J stderr")"; DT_J_BIN="$DT_J/bin"; mkdir -p "$DT_J_BIN"
    git -C "$DT_J" status --porcelain -z > "$DT_J_B"
    DT_J_OID="$(git hash-object "$DT_J_B")"
    printf 'agent edit' > "$DT_J/plain.txt"; printf 'target sentinel' > "$DT_J_TARGET"
    DT_REAL_GIT="$(command -v git)"
    printf '%s\n' '#!/usr/bin/env bash' \
      'if [ "${1:-}" = status ]; then' \
      '  rm -f "$GIT_SNAP_AFTER"; ln -s "$DT_RACE_TARGET" "$GIT_SNAP_AFTER"' \
      'fi' \
      'exec "$DT_REAL_GIT" "$@"' > "$DT_J_BIN/git"
    chmod +x "$DT_J_BIN/git"
    ( cd "$DT_J" && PATH="$DT_J_BIN:$PATH" DT_REAL_GIT="$DT_REAL_GIT" \
        DT_RACE_TARGET="$DT_J_TARGET" GIT_SNAP_BEFORE="$DT_J_B" GIT_SNAP_AFTER="$DT_J_AF" \
        bash "$RDT" compare-and-restore "$DT_J_OID" ) >/dev/null 2>"$DT_J_ERR"
    assert_eq "#484 after-snapshot: race-swapped symlink skips restoration" \
      "agent edit" "$(cat "$DT_J/plain.txt")"
    assert_eq "#484 after-snapshot: race-swapped symlink emits the attributable capture-failure breadcrumb" "yes" \
      "$(grep -qF 'could not create a regular working-tree snapshot after the Phase 3.1 dispatch' "$DT_J_ERR" && echo yes || echo no)"
    assert_eq "#484 after-snapshot: symlink-race target remains untouched" \
      "target sentinel" "$(cat "$DT_J_TARGET")"
    rm -rf "$DT_J" "$DT_J_B" "$DT_J_AF" "$DT_J_TARGET" "$DT_J_ERR"
  fi
else
  module_host_capability_skip "#484 case-J after-snapshot race-swap symlink arm" \
    "host cannot create symlinks; the after-snapshot symlink-race arm cannot run here" 3
fi
# Case SK — a disabled sentinel short-circuits compare-and-restore (disabled-sentinel arm).
DT_SK="$(dt_make_repo)"
if [ -d "$DT_SK" ]; then
  DT_SK_B="$(probe_tmp "#2082 sentinel-skip before")"; DT_SK_AF="$(probe_tmp "#2082 sentinel-skip after")"
  git -C "$DT_SK" status --porcelain -z > "$DT_SK_B"
  DT_SK_OID="$(git hash-object "$DT_SK_B")"
  printf 'agent edit' > "$DT_SK/plain.txt"
  mkdir -p "$DT_SK/.prflow/tmp"; printf '%s\n' disabled > "$DT_SK/.prflow/tmp/review-dirty-tree-disabled"
  ( cd "$DT_SK" && GIT_SNAP_BEFORE="$DT_SK_B" GIT_SNAP_AFTER="$DT_SK_AF" bash "$RDT" compare-and-restore "$DT_SK_OID" ) >/dev/null 2>&1
  assert_eq "#2082 backstop: a disabled sentinel short-circuits compare-and-restore (agent edit NOT restored)" \
    "agent edit" "$(cat "$DT_SK/plain.txt" 2>/dev/null)"
  rm -rf "$DT_SK" "$DT_SK_B" "$DT_SK_AF"
fi
# Case SC — the INNER changed-paths-write scratch guard fails CLOSED (scratch-alloc arm).
DT_SC="$(dt_make_repo)"
if [ -d "$DT_SC" ]; then
  DT_SC_B="$(probe_tmp "#2082 scratch-alloc before")"; DT_SC_AF="$(probe_tmp "#2082 scratch-alloc after")"
  DT_SC_ERR="$(probe_tmp "#2082 scratch-alloc stderr")"
  git -C "$DT_SC" status --porcelain -z > "$DT_SC_B"
  DT_SC_OID="$(git hash-object "$DT_SC_B")"
  printf 'agent edit' > "$DT_SC/plain.txt"
  mkdir -p "$DT_SC/.prflow/tmp/review-dirty-tree-changed-paths"   # a dir where the helper needs to write a file
  ( cd "$DT_SC" && GIT_SNAP_BEFORE="$DT_SC_B" GIT_SNAP_AFTER="$DT_SC_AF" bash "$RDT" compare-and-restore "$DT_SC_OID" ) >/dev/null 2>"$DT_SC_ERR"
  assert_eq "#2082 backstop: scratch-allocation failure fails closed (agent edit NOT restored)" \
    "agent edit" "$(cat "$DT_SC/plain.txt" 2>/dev/null)"
  assert_eq "#2082 backstop: scratch-allocation failure emits the distinct breadcrumb" "yes" \
    "$(grep -qF 'could not allocate repo-local scratch files' "$DT_SC_ERR" && echo yes || echo no)"
  rm -rf "$DT_SC" "$DT_SC_B" "$DT_SC_AF" "$DT_SC_ERR"
fi
# Case MK — the compare-and-restore function-entry `mkdir -p .prflow/tmp` guard fails CLOSED.
DT_MK="$(dt_make_repo)"
if [ -d "$DT_MK" ]; then
  DT_MK_B="$(probe_tmp "#2082 mkdir-guard before")"; DT_MK_AF="$(probe_tmp "#2082 mkdir-guard after")"
  DT_MK_ERR="$(probe_tmp "#2082 mkdir-guard stderr")"
  git -C "$DT_MK" status --porcelain -z > "$DT_MK_B"
  DT_MK_OID="$(git hash-object "$DT_MK_B")"
  printf 'agent edit' > "$DT_MK/plain.txt"
  printf blocker > "$DT_MK/.prflow"   # a regular file where the helper needs the .prflow/tmp dir
  ( cd "$DT_MK" && GIT_SNAP_BEFORE="$DT_MK_B" GIT_SNAP_AFTER="$DT_MK_AF" bash "$RDT" compare-and-restore "$DT_MK_OID" ) >/dev/null 2>"$DT_MK_ERR"
  assert_eq "#2082 backstop: uncreatable .prflow/tmp fails closed (agent edit NOT restored)" \
    "agent edit" "$(cat "$DT_MK/plain.txt" 2>/dev/null)"
  assert_eq "#2082 backstop: uncreatable .prflow/tmp emits the distinct mkdir-guard breadcrumb" "yes" \
    "$(grep -qF 'could not create .prflow/tmp for the dirty-tree compare/restore' "$DT_MK_ERR" && echo yes || echo no)"
  rm -rf "$DT_MK" "$DT_MK_B" "$DT_MK_AF" "$DT_MK_ERR"
fi
# Case MKS — the SNAPSHOT-side function-entry mkdir guard fails CLOSED (prints NO OID).
DT_MKS="$(dt_make_repo)"
if [ -d "$DT_MKS" ]; then
  DT_MKS_B="$(probe_tmp "#2082 snapshot mkdir-guard before")"; DT_MKS_ERR="$(probe_tmp "#2082 snapshot mkdir-guard stderr")"
  printf blocker > "$DT_MKS/.prflow"   # a regular file where the helper needs the .prflow/tmp dir
  DT_MKS_OUT="$( cd "$DT_MKS" && GIT_SNAP_BEFORE="$DT_MKS_B" bash "$RDT" snapshot 2>"$DT_MKS_ERR" )"
  assert_eq "#2082 snapshot: uncreatable .prflow/tmp prints NO object ID (failed snapshot)" \
    "" "$DT_MKS_OUT"
  assert_eq "#2082 snapshot: uncreatable .prflow/tmp emits the distinct mkdir-guard breadcrumb" "yes" \
    "$(grep -qF 'working-tree snapshot not taken' "$DT_MKS_ERR" && echo yes || echo no)"
  rm -rf "$DT_MKS" "$DT_MKS_B" "$DT_MKS_ERR"
fi
# Case PR — the post-restore confirmation read fails CLOSED on its OWN exit status (PATH-shimmed git).
DT_PR="$(dt_make_repo)"
if [ -d "$DT_PR" ]; then
  DT_PR_B="$(probe_tmp "#2082 post-restore-confirm before")"; DT_PR_AF="$(probe_tmp "#2082 post-restore-confirm after")"
  DT_PR_ERR="$(probe_tmp "#2082 post-restore-confirm stderr")"; DT_PR_BIN="$DT_PR/bin"; mkdir -p "$DT_PR_BIN"
  git -C "$DT_PR" status --porcelain -z > "$DT_PR_B"
  DT_PR_OID="$(git hash-object "$DT_PR_B")"
  printf 'agent edit' > "$DT_PR/plain.txt"          # a real divergence, so the restore loop is reached
  git -C "$DT_PR" status --porcelain -z > "$DT_PR_AF"
  DT_REAL_GIT="$(command -v git)"
  printf '%s\n' '#!/usr/bin/env bash' \
    'if [ "${1:-}" = status ]; then' \
    '  for a in "$@"; do [ "$a" = "-z" ] && exec "$DT_REAL_GIT" "$@"; done' \
    '  for a in "$@"; do [ "$a" = "--" ] && exit 3; done' \
    'fi' \
    'exec "$DT_REAL_GIT" "$@"' > "$DT_PR_BIN/git"
  chmod +x "$DT_PR_BIN/git"
  ( cd "$DT_PR" && PATH="$DT_PR_BIN:$PATH" DT_REAL_GIT="$DT_REAL_GIT" \
      GIT_SNAP_BEFORE="$DT_PR_B" GIT_SNAP_AFTER="$DT_PR_AF" bash "$RDT" compare-and-restore "$DT_PR_OID" ) >/dev/null 2>"$DT_PR_ERR"
  assert_eq "#2082 backstop: an unverifiable post-restore git status (rc≠0) fails closed with the distinct breadcrumb" "yes" \
    "$(grep -qF 'post-restore state could not be confirmed (git status rc' "$DT_PR_ERR" && echo yes || echo no)"
  rm -rf "$DT_PR" "$DT_PR_B" "$DT_PR_AF" "$DT_PR_ERR"
fi
# Case CE — the cmp-error (rc>=2) branch fails CLOSED (PATH-shimmed cmp exits 2).
DT_CE="$(dt_make_repo)"
if [ -d "$DT_CE" ]; then
  DT_CE_B="$(probe_tmp "#2082 cmp-error before")"; DT_CE_AF="$(probe_tmp "#2082 cmp-error after")"
  DT_CE_ERR="$(probe_tmp "#2082 cmp-error stderr")"; DT_CE_BIN="$DT_CE/bin"; mkdir -p "$DT_CE_BIN"
  git -C "$DT_CE" status --porcelain -z > "$DT_CE_B"
  DT_CE_OID="$(git hash-object "$DT_CE_B")"
  printf 'agent edit' > "$DT_CE/plain.txt"          # a real divergence, so the branch is reached
  printf '%s\n' '#!/usr/bin/env bash' 'exit 2' > "$DT_CE_BIN/cmp"   # comparison ERROR, not "differ"
  chmod +x "$DT_CE_BIN/cmp"
  ( cd "$DT_CE" && PATH="$DT_CE_BIN:$PATH" GIT_SNAP_BEFORE="$DT_CE_B" GIT_SNAP_AFTER="$DT_CE_AF" bash "$RDT" compare-and-restore "$DT_CE_OID" ) >/dev/null 2>"$DT_CE_ERR"
  assert_eq "#2082 backstop: a cmp comparison error fails closed (agent edit NOT restored)" \
    "agent edit" "$(cat "$DT_CE/plain.txt" 2>/dev/null)"
  assert_eq "#2082 backstop: a cmp comparison error emits the distinct rc-bearing breadcrumb" "yes" \
    "$(grep -qF 'could not compare the before/after working-tree snapshots (cmp errored' "$DT_CE_ERR" && echo yes || echo no)"
  rm -rf "$DT_CE" "$DT_CE_B" "$DT_CE_AF" "$DT_CE_ERR"
fi
# Case MB — the genuinely-MISSING before-snapshot disjunct fails CLOSED (truncated-snapshot family).
DT_MB="$(dt_make_repo)"
if [ -d "$DT_MB" ]; then
  DT_MB_B="$DT_MB/nonexistent-before"; DT_MB_AF="$(probe_tmp "#2082 missing-before after")"
  DT_MB_ERR="$(probe_tmp "#2082 missing-before stderr")"
  git -C "$DT_MB" status --porcelain -z > "$DT_MB_AF"   # produce a real OID from a real snapshot
  DT_MB_OID="$(git hash-object "$DT_MB_AF")"
  printf 'agent edit' > "$DT_MB/plain.txt"
  ( cd "$DT_MB" && GIT_SNAP_BEFORE="$DT_MB_B" GIT_SNAP_AFTER="$DT_MB_AF" bash "$RDT" compare-and-restore "$DT_MB_OID" ) >/dev/null 2>"$DT_MB_ERR"
  assert_eq "#2082 backstop: a genuinely-missing before-snapshot fails closed (agent edit NOT restored)" \
    "agent edit" "$(cat "$DT_MB/plain.txt" 2>/dev/null)"
  assert_eq "#2082 backstop: a genuinely-missing before-snapshot emits the missing/tampered breadcrumb" "yes" \
    "$(grep -qF 'the before-dispatch snapshot is missing or no longer a regular non-symlink file' "$DT_MB_ERR" && echo yes || echo no)"
  rm -rf "$DT_MB" "$DT_MB_AF" "$DT_MB_ERR"
fi

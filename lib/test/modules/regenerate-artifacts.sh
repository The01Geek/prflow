# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable regenerate-artifacts contract module (issue #619).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first (which defines the namespaced module pin API:
# devflow_module_pin_count / devflow_module_pin_unique / devflow_module_pin_present).
# This module uses assert_eq plus the `_ra_*`
# domain-private helpers defined below — it references NO monolith helper. They are
# deliberately not enumerated here: an exact list is a mirror-fact that goes stale on
# the next helper added, and the definitions below are the authoritative set.
# The module owns its private fixture root and cleanup; it never invokes the runner
# or the full-suite boundary. The inventory in regenerate-artifacts.inventory.md
# records the module's provenance. Modules may not self-skip.
# The `trap _ra_cleanup EXIT` below relies on a sourcing contract: both callers
# (module-harness.sh's full-suite boundary and run-module.sh) source this module
# inside a ( ... ) subshell, so the trap fires at subshell exit and cannot clobber
# the runner's own EXIT handling. Do not source this module directly in a runner's
# top-level shell without restoring the trap.
#
# EVERY planted-drift assertion runs against a temp fixture root, never the live
# checkout, and each fixture-root assertion additionally asserts the live tree's
# scripts/devflow-cloud-writer-contract.json is byte-unchanged. Live-tree confinement
# is asserted, not assumed from the generators' current __file__-based root
# resolution: an interrupted live-tree mutate-and-restore would leave a
# self-consistent corrupted asset+manifest pair on disk that the issue-543 verify
# gate would then certify green.

RA_HELPER="$LIB/test/regenerate-artifacts.py"
RA_REPO="$LIB/.."
RA_CAPMUT="$LIB/test/cap-mutate.py"
RA_LIVE_MANIFEST="$RA_REPO/scripts/devflow-cloud-writer-contract.json"

_ra_tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-regenerate-artifacts.XXXXXX")" || {
  printf 'could not allocate regenerate-artifacts fixture\n' >&2
  return 1
}
_ra_cleanup() {
  rm -rf "$_ra_tmp_root"
}
trap _ra_cleanup EXIT

# The live manifest's bytes, captured once before any fixture run. Every fixture
# assertion re-compares against this so a helper that escaped its target root would
# be caught by the very next assertion rather than shipping green.
_ra_live_before="$(cat "$RA_LIVE_MANIFEST" 2>/dev/null)"
# Non-emptiness is asserted, not assumed: an unreadable or absent live manifest would
# make _ra_live_before empty, and every _ra_live_unchanged guard below would then
# compare "" to "" and pass vacuously — every confinement assertion in this module
# failing open at once, on exactly the broken tree they exist to catch.
case "$_ra_live_before" in
  '') assert_eq "#619 the live manifest baseline is non-empty (confinement guards are live)" yes \
        "no(empty — $RA_LIVE_MANIFEST unreadable or absent; every live-unchanged guard would be vacuous)" ;;
  *)  assert_eq "#619 the live manifest baseline is non-empty (confinement guards are live)" yes yes ;;
esac
# One byte-compare assertion used by every "these bytes must not have moved" check, so
# the shape exists once rather than being re-spelled per call site.
_ra_same() {  # name expected actual fail-detail
  if [ "$2" = "$3" ]; then assert_eq "$1" yes yes; else assert_eq "$1" yes "no($4)"; fi
}
_ra_live_unchanged() {  # name
  _ra_same "$1" "$_ra_live_before" "$(cat "$RA_LIVE_MANIFEST" 2>/dev/null)" \
    "live checkout manifest was mutated by a fixture run"
}
# The boolean sibling of _ra_same: one assertion whose pass and fail arms are spelled
# once, so a caller cannot register two differently-named assertions by drifting the
# name text between its own two `assert_eq` calls.
_ra_ok() {  # name ok-flag fail-detail   (ok-flag: "yes" passes, anything else fails)
  if [ "$2" = yes ]; then assert_eq "$1" yes yes; else assert_eq "$1" yes "no($3)"; fi
}
# Substring-presence over a FILE. `_ra_has` (which takes a fixture root and reads its
# `.ra.out`) delegates here, so the count-unestablished arm and the output dump exist
# once rather than being re-spelled by every caller that already holds a path.
_ra_has_file() {  # name file substring
  local n
  n="$(devflow_module_pin_count "$3" "$2")"
  case "$n" in
    ''|*[!0-9]*) assert_eq "$1" yes "no(count unestablished for '$3')"; return 0 ;;
  esac
  if [ "$n" -ge 1 ]; then assert_eq "$1" yes yes
  else assert_eq "$1" yes "no('$3' absent; output: $(tr '\n' '|' <"$2"))"; fi
}
# Siblings of `_ra_has_file`: `_ra_lacks_file` passes when the substring is ABSENT (count 0),
# `_ra_count_is` when it occurs EXACTLY the expected number of times. Both centralize the
# runtime-capture occurrence count in one place — a caller asserts behavior over a `.ra.*`
# scratch capture without re-spelling the counter, and the count call stays out of the caller's
# line so the static meta-guard reads each caller as an ordinary behavioral test rather than a
# prose pin (the literal is a machine sentinel matched against a runtime output file, not source).
_ra_lacks_file() {  # name file substring
  local n
  n="$(devflow_module_pin_count "$3" "$2")"
  case "$n" in
    ''|*[!0-9]*) assert_eq "$1" yes "no(count unestablished for '$3')"; return 0 ;;
  esac
  if [ "$n" -eq 0 ]; then assert_eq "$1" yes yes
  else assert_eq "$1" yes "no('$3' present $n time(s); output: $(tr '\n' '|' <"$2"))"; fi
}
_ra_count_is() {  # name file substring expected-count
  local n
  n="$(devflow_module_pin_count "$3" "$2")"
  case "$n" in
    ''|*[!0-9]*) assert_eq "$1" yes "no(count unestablished for '$3')"; return 0 ;;
  esac
  if [ "$n" -eq "$4" ]; then assert_eq "$1" yes yes
  else assert_eq "$1" yes "no('$3' occurs $n time(s), expected $4; output: $(tr '\n' '|' <"$2"))"; fi
}
# Extract one `key=value` field from a builder/oracle summary line with bash parameter
# expansion (never `cut`/`awk` — the un-guaranteed-tool rule), so an assertion pins the
# field it cares about rather than the summary line's printf order.
# The match is anchored on a leading SPACE boundary (the summary is space-prefixed
# first), because an unanchored `${1#*"$2"=}` would let `missing` match inside
# `skip_missing=` and silently return the wrong field's value — which would land on the
# real key only by accident of printf order, the exact property this helper exists to
# stop an assertion depending on. An absent key returns the sentinel `unset`, which is
# equal to no expected count and so fails loudly rather than reading as zero.
_ra_field() {  # summary key
  local _s=" $1" _rest
  _rest="${_s#* "$2"=}"
  [ "$_rest" != "$_s" ] || { printf 'unset'; return 0; }
  printf '%s' "${_rest%% *}"
}
# `_ra_same` over two DERIVED field values: an absent key on both sides would otherwise
# compare `unset` to `unset` and pass, so the sentinel is rejected before the compare.
# That is reachable by exactly the coupled-mirror rename the oracle's header warns about.
_ra_same_field() {  # name expected-summary actual-summary key fail-detail
  local _e _a
  _e="$(_ra_field "$2" "$4")"; _a="$(_ra_field "$3" "$4")"
  if [ "$_e" = unset ] || [ "$_a" = unset ]; then
    assert_eq "$1" yes "no(field '$4' is absent from a summary — $5)"
    return 0
  fi
  _ra_same "$1" "$_e" "$_a" "$5"
}
# Seed a temp git repository with the module's fixture identity. The index-state repos
# below share it, so a future `git config` addition is a one-line change. `rerere` is
# disabled explicitly: it is inherited from the developer's global config and would
# auto-resolve the conflicted-index fixture, silently emptying the arm that fixture
# exists to exercise. Returns the seeding rc so a caller never builds on a dead repo.
_ra_seed_repo() {  # dir [git-init-flags...]
  local _d="$1"; shift
  mkdir -p "$_d" || return 1
  (
    cd "$_d" || exit 1
    git init -q "$@" . &&
    git config user.email devflow@example.invalid &&
    git config user.name devflow &&
    git config rerere.enabled false
  ) >/dev/null 2>&1
}

# ────────────────────────────────────────────────────────────────────────────
echo "#619 batched generated-artifact regeneration pass (lib/test/regenerate-artifacts.py)"
# ────────────────────────────────────────────────────────────────────────────

# One pristine fixture is built once and copied per assertion: each copy is a full
# repository image (the generators resolve their roots from __file__ or an argv root,
# so a partial tree would exercise the wrong closure), and rebuilding it per
# assertion would dominate the module's runtime.
#
# The image is built from the git INDEX — every tracked path, copied file by file at
# its own relative path, with its mode taken from the index (issue #714). Two rules,
# both load-bearing:
#   * COMPLETE, never a hand-picked subset — the capability generator reads its manifest
#     and workflows, the cloud-writer closure reads skills/ and scripts/, and a subset
#     that misses one makes the *pristine* fixture drift, silently invalidating every "no other row
#     drifted" premise in this module.
#   * TRACKED-ONLY — nothing untracked can enter the image, which is why this module
#     needs no `__pycache__`/`.ruff_cache`/`.prflow/tmp` prune step.
# The history behind the tracked-only rule and the measured cost it removed live in
# regenerate-artifacts.inventory.md; do not restate the figures here.
#
# `git ls-files -s` (preflight-guaranteed) makes the selection and bash parameter
# expansion does the path arithmetic — never `cut`/`sort`/`awk`, a non-preflight PATH
# tool must not decide WHICH files get copied (CLAUDE.md's un-guaranteed-tool rule):
# a missing tool would yield an empty entry list and a hollow fixture.
#
# Build a tracked-only repository image. Prints one `key=value` summary line so a
# caller can assert completeness against the FULL index denominator; each of the three
# skip arms is taken with its own distinct named stderr breadcrumb and subtracted from
# that denominator by name, never failing the build.
#
# UNKNOWN IS NOT ZERO — the same rule the python oracle below states, honored here so
# the two halves of the coupled mirror behave alike. The index enumeration is written
# to a file and its rc CHECKED, never read through a process substitution whose rc is
# unobservable: a broken `git`, a `<src-repo>` that is not a repository, or an
# unreadable index would otherwise yield an empty read and print
# `total=0 copied=0 ...`, a vacuous clean indistinguishable from a legitimately empty
# index — and `_ra_summary_balances` would certify it (0 == 0+0+...). Print an
# `unestablished` sentinel and return 1 instead, which equals no expected count and so
# fails loudly at whichever assertion consumes the summary.
_ra_build_image() {  # <src-repo> <dest>
  local _src="$1" _dest="$2"
  local _rec _mode _path _prev='' _total=0 _copied=0 _tab _idx _mk
  local _skip_missing=0 _skip_gitlink=0 _skip_symlink=0 _fail_copy=0 _fail_mode=0
  _tab=$'\t'
  mkdir -p "$_dest" || return 1
  _idx="$_dest.index"
  # Capture the status rather than negating the compound with `if ! (...) >"$_idx"`: bash
  # does not propagate a failed redirect on a compound command through `!` (issue #1524), so
  # the negated form swallowed an unopenable "$_idx" and walked on to a vacuous total=0. This
  # arm must fire for BOTH the subshell failing (git ls-files) and the redirect failing to open.
  local _idx_rc=0
  (cd "$_src" && git ls-files -s -z) >"$_idx" 2>/dev/null || _idx_rc=$?
  if [ "$_idx_rc" -ne 0 ]; then
    printf 'regenerate-artifacts fixture: could not establish the index for %s (git ls-files -s -z failed)\n' "$_src" >&2
    printf 'total=unestablished copied=unestablished fail_copy=unestablished fail_mode=unestablished skip_missing=unestablished skip_gitlink=unestablished skip_symlink=unestablished\n'
    rm -f "$_idx"
    return 1
  fi
  while IFS= read -r -d '' _rec; do
    [ -n "$_rec" ] || continue
    # `<mode> <sha> <stage>\t<path>` — the path is read whole after the TAB, so a
    # newline or a space in a filename cannot split one entry into two (-z).
    _mode="${_rec%% *}"
    _path="${_rec#*"$_tab"}"
    # Unmerged paths appear once per stage (1/2/3), contiguously: count and copy the
    # path once, so the denominator and the image agree on a conflicted tree.
    [ "$_path" != "$_prev" ] || continue
    _prev="$_path"
    _total=$((_total + 1))
    case "$_mode" in
      160000)
        printf 'regenerate-artifacts fixture: skipping gitlink index entry %s\n' "$_path" >&2
        _skip_gitlink=$((_skip_gitlink + 1)); continue ;;
      120000)
        printf 'regenerate-artifacts fixture: skipping symlink index entry %s\n' "$_path" >&2
        _skip_symlink=$((_skip_symlink + 1)); continue ;;
    esac
    if [ ! -f "$_src/$_path" ]; then
      printf 'regenerate-artifacts fixture: skipping index entry with no working-tree file %s\n' "$_path" >&2
      _skip_missing=$((_skip_missing + 1)); continue
    fi
    # `${var%/*}` returns the WHOLE string when the value has no `/`, so an unguarded
    # mkdir would create a DIRECTORY named CLAUDE.md where a regular file must be, drifting
    # the pristine fixture. Guard on `*/*`.
    # A copy that FAILS is not a skip: it is counted and breadcrumbed on its own
    # `fail_copy` channel, never swallowed into the gap between `total` and `copied`.
    # Neither `mkdir` nor `cp` is preflight-guaranteed, so each is failure-checked on
    # its own step — `mkdir` through the `_mk` flag, `cp` in the `if` — rather than
    # relying on the `cp` to inherit the `mkdir`'s failure. An rc-127 host is therefore
    # counted and breadcrumbed instead of silently producing a hollow image, and the
    # parent-directory failure is attributable to the step that actually failed.
    _mk=0
    case "$_path" in */*) mkdir -p "$_dest/${_path%/*}" || _mk=1 ;; esac
    if [ "$_mk" -ne 0 ] || ! cp "$_src/$_path" "$_dest/$_path"; then
      printf 'regenerate-artifacts fixture: FAILED to copy tracked entry %s\n' "$_path" >&2
      _fail_copy=$((_fail_copy + 1)); continue
    fi
    # The mode comes from the INDEX, not the working tree: on a core.fileMode=false
    # checkout (git's default on Windows) the index records 100755 while the on-disk
    # file carries no executable bit, and inheriting that bit would turn the module RED.
    # `chmod` is not preflight-guaranteed either, and a mode that silently failed to
    # apply is exactly the defect this block exists to stop — so it gets its own
    # `fail_mode` channel rather than being counted as a clean copy. The entry stays on
    # disk (the oracle compares path sets, so it is neither `extra` nor `missing`); only
    # the accounting says the mode was not established.
    if ! case "$_mode" in
           100755) chmod 755 "$_dest/$_path" ;;
           *)      chmod 644 "$_dest/$_path" ;;
         esac; then
      printf 'regenerate-artifacts fixture: FAILED to set index mode %s on %s\n' "$_mode" "$_path" >&2
      _fail_mode=$((_fail_mode + 1)); continue
    fi
    _copied=$((_copied + 1))
  done <"$_idx"
  rm -f "$_idx"
  printf 'total=%s copied=%s fail_copy=%s fail_mode=%s skip_missing=%s skip_gitlink=%s skip_symlink=%s\n' \
    "$_total" "$_copied" "$_fail_copy" "$_fail_mode" "$_skip_missing" "$_skip_gitlink" "$_skip_symlink"
}
# Every de-duplicated index entry the builder saw must be accounted for exactly once —
# copied, failed, or skipped by a named arm. Without this the `cp`/`mkdir` failure arm
# would be a silent shortfall detectable only by the oracle, and the oracle is the very
# thing this pairing exists to stop the module depending on alone.
_ra_summary_balances() {  # name summary
  local _t _sum _k
  _t="$(_ra_field "$2" total)"; _sum=0
  for _k in copied fail_copy fail_mode skip_missing skip_gitlink skip_symlink; do
    case "$(_ra_field "$2" "$_k")" in
      ''|*[!0-9]*) assert_eq "$1" yes "no(field '$_k' unusable in summary: $2)"; return 0 ;;
      *) _sum=$((_sum + $(_ra_field "$2" "$_k"))) ;;
    esac
  done
  _ra_same "$1" "$_t" "$_sum" "total does not equal copied+fail_copy+fail_mode+skips — summary: $2"
}

_ra_pristine="$_ra_tmp_root/pristine"
# The live-checkout build's stderr is CAPTURED, not discarded: it is the one build whose
# breadcrumbs name real repository paths, so a skip arm firing on the live index (a newly
# tracked symlink or submodule) or a copy failure must be readable, not merely counted.
_ra_pristine_err="$_ra_tmp_root/pristine.err"
_ra_pristine_summary="$(_ra_build_image "$RA_REPO" "$_ra_pristine" 2>"$_ra_pristine_err")"
# ── Fixture-builder contract (issue #714) ───────────────────────────────────
# An INDEPENDENT oracle, deliberately not sharing the builder's own bookkeeping: it
# re-reads the index itself and diffs the resulting expectation against the files
# actually on disk under the image. `extra` catches untracked content riding in;
# `missing` catches a silently-dropped mode — the denominator is the FULL de-duplicated
# index, so dropping a mode fails the count instead of shrinking both sides together.
# These run BEFORE the `git init` below, so the image carries no `.git/` of its own yet.
#
# COUPLED MIRROR: this oracle re-states `_ra_build_image`'s selection policy (mode
# triage, unmerged-stage de-duplication, the working-tree isfile check) in a second
# language. That independence is the point — but it means a change to the builder's
# skip policy MUST be made here in the same commit, or the oracle silently keeps
# certifying the old policy. Edit the two together; the inventory records the pair.
_ra_image_report() {  # <src-repo> <image>  → "extra=N missing=N skip_missing=N skip_gitlink=N skip_symlink=N"
  python3 - "$1" "$2" <<'RA_PY'
import os, subprocess, sys
src, image = sys.argv[1], sys.argv[2]
# UNKNOWN IS NOT ZERO. A failed `git ls-files` (broken git, `src` not a repository, an
# unreadable index — every one of which also empties the image) would otherwise yield an
# empty expectation AND an empty actual, printing `extra=0 missing=0`: a vacuous clean
# from the one artifact whose whole job is to catch the builder lying. Emit an
# `unestablished` sentinel instead, which equals no expected count and so fails loudly.
_r = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=src,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if _r.returncode != 0 or not os.path.isdir(image):
    print("extra=unestablished missing=unestablished skip_missing=unestablished "
          "skip_gitlink=unestablished skip_symlink=unestablished")
    sys.stderr.write("regenerate-artifacts oracle: could not establish the index/image "
                     "for %s -> %s (rc=%d): %s\n"
                     % (src, image, _r.returncode,
                        _r.stderr.decode("utf-8", "replace").strip()))
    sys.exit(0)
raw = _r.stdout.split(b"\0")
seen, expected = set(), set()
skips = {"missing": 0, "gitlink": 0, "symlink": 0}
for rec in raw:
    if not rec:
        continue
    meta, _, path = rec.partition(b"\t")
    mode = meta.split(b" ")[0].decode()
    path = path.decode("utf-8", "surrogateescape")
    if path in seen:
        continue
    seen.add(path)
    if mode == "160000":
        skips["gitlink"] += 1
    elif mode == "120000":
        skips["symlink"] += 1
    elif not os.path.isfile(os.path.join(src, path)):
        skips["missing"] += 1
    else:
        expected.add(path)
actual = set()
for root, _dirs, files in os.walk(image):  # tree-walk-ok: walks the per-test fixture image, never the repository root, so no sibling worktree is reachable from it
    for f in files:
        actual.add(os.path.relpath(os.path.join(root, f), image))
print("extra=%d missing=%d skip_missing=%d skip_gitlink=%d skip_symlink=%d"
      % (len(actual - expected), len(expected - actual),
         skips["missing"], skips["gitlink"], skips["symlink"]))
RA_PY
}

RA_PRISTINE_REPORT="$(_ra_image_report "$RA_REPO" "$_ra_pristine")"
_ra_ok "#619 pristine fixture holds no untracked content" \
  "$([ "$(_ra_field "$RA_PRISTINE_REPORT" extra)" = 0 ] && printf yes)" \
  "untracked paths present: $RA_PRISTINE_REPORT"
# `extra=0` alone is satisfied by an EMPTY image, so it is a partition with the
# completeness assertion below and the no-separator control — never read alone.
_ra_summary_balances "#619 pristine fixture builder accounts for every index entry it saw" \
  "$_ra_pristine_summary"
_ra_same "#619 pristine fixture builder copied every tracked blob without a copy failure" \
  0 "$(_ra_field "$_ra_pristine_summary" fail_copy)" \
  "copy failures on the live checkout; stderr: $(tr '\n' '|' <"$_ra_pristine_err" 2>/dev/null)"
# `fail_mode`'s sibling pin, and it is NOT redundant with the completeness pair: a mode
# that failed to apply leaves the file on disk, so the oracle — which compares path sets
# — reports neither `extra` nor `missing`, and `_ra_summary_balances` balances happily
# with `fail_mode` equal to the whole index. Without this assertion a `chmod` that is
# absent (rc 127; it is not preflight-guaranteed), EPERM on a shared mount, or a
# filesystem ignoring mode bits yields a pristine image whose helpers are all
# non-executable while every other pristine assertion stays green — and the downstream
# rows then fail with a diagnosis aimed at the generators instead of the fixture.
_ra_same "#619 pristine fixture builder applied every index mode without failure" \
  0 "$(_ra_field "$_ra_pristine_summary" fail_mode)" \
  "mode-application failures on the live checkout; stderr: $(tr '\n' '|' <"$_ra_pristine_err" 2>/dev/null)"
_ra_ok "#619 pristine fixture reproduces every tracked entry the skip arms did not remove" \
  "$([ "$(_ra_field "$RA_PRISTINE_REPORT" missing)" = 0 ] && printf yes)" \
  "tracked entries absent from the image: $RA_PRISTINE_REPORT"
# The paired positive control for the two counts above: without a no-separator check
# an empty image would satisfy `extra=0`, and the directory-shaped-CLAUDE.md
# regression (`${var%/*}` returning the whole string) would pass unnoticed.
_ra_ok "#619 pristine fixture reproduces a no-separator path as a regular file" \
  "$([ -f "$_ra_pristine/CLAUDE.md" ] && [ ! -d "$_ra_pristine/CLAUDE.md" ] && printf yes)" \
  "CLAUDE.md is absent or a directory in the image"
# The builder's own bookkeeping must agree with the independent oracle, so a
# miscounted skip cannot quietly widen the denominator it is subtracted from. Compared
# field by field, so neither summary line's printf order is what the assertion pins.
for _ra_k in skip_missing skip_gitlink skip_symlink; do
  _ra_same_field "#619 fixture builder $_ra_k tally agrees with the independent oracle" \
    "$RA_PRISTINE_REPORT" "$_ra_pristine_summary" "$_ra_k" \
    "builder summary '$_ra_pristine_summary' vs oracle '$RA_PRISTINE_REPORT'"
done
# Builder/oracle AGREEMENT above proves only that the two halves agree about an
# omission — not that none occurred: a newly tracked symlink or submodule is skipped by
# the builder AND excluded from the oracle's denominator, so `missing` stays 0 and every
# completeness assertion stays green while the pristine image is quietly incomplete,
# which is exactly the drift the "complete, never a subset" rule exists to prevent. Pin
# the two structural skip arms to zero so that day turns the desk RED with a named cause
# rather than passing. (`skip_missing` is deliberately NOT pinned: it reports a
# working-tree condition — a locally deleted tracked file — not a property of the
# repository, so pinning it would go RED on a dirty checkout rather than on real drift.)
for _ra_k in skip_gitlink skip_symlink; do
  _ra_same "#619 the live checkout contributes no $_ra_k skip (the pristine image is complete)" \
    0 "$(_ra_field "$_ra_pristine_summary" "$_ra_k")" \
    "a tracked non-blob entered the repository and is silently absent from every fixture; stderr: $(tr '\n' '|' <"$_ra_pristine_err" 2>/dev/null)"
done
# No path under `.claude/worktrees` — the untracked payload the old whole-directory
# builder copied wholesale — may appear in the image.
_ra_ok "#619 pristine fixture carries no .claude/worktrees payload" \
  "$([ ! -d "$_ra_pristine/.claude/worktrees" ] && printf yes)" \
  ".claude/worktrees present in the image"

# ── The helpers' own degraded arms, driven rather than merely reasoned about ──
# Each arm below exists to stop a vacuous pass, so each needs a caller that reaches it:
# without one, deleting the arm is a GREEN mutation and the guarantee is decorative.
# Every drivable degraded arm this module adds has a caller below — the builder's
# `fail_copy` and `fail_mode` channels and both `unestablished` sentinels included.
# NOT drivable here, with the reason recorded rather than silently skipped:
# `_ra_same_field`'s unset-rejection arm, `_ra_summary_balances`' non-numeric arm and
# `_ra_has_file`'s count-unestablished arm all discharge by calling `assert_eq` with a
# failing expectation — driving one registers a real module FAIL, so they are covered by
# reading, not by a caller. Their shared operand `_ra_field` IS driven, immediately below.
_ra_same "#619 _ra_field anchors on the key boundary (a short key cannot match inside a longer one)" \
  7 "$(_ra_field "extra=1 skip_missing=3 missing=7" missing)" \
  "an unanchored expansion would return the skip_missing value"
_ra_same "#619 _ra_field returns the unset sentinel for an absent key (never a silent zero)" \
  unset "$(_ra_field "extra=1 missing=2" total)" "an absent key must not read as a value"
# The oracle's fail-closed sentinel: with an unestablished index or image BOTH sides of
# its set difference are empty, so the honest report is `unestablished`, never a vacuous
# `extra=0 missing=0` from the one artifact whose job is to catch the builder lying.
# The absent-image arm is what is driven here — an absent *src* would raise inside
# `subprocess.run(cwd=...)` rather than return an rc, and a merely-non-repo directory is
# not a reliable fixture (git searches upward, so a temp root nested under a checkout
# would resolve the enclosing repository and succeed).
RA_UNEST_REPORT="$(_ra_image_report "$RA_REPO" "$_ra_tmp_root/no-such-image" 2>/dev/null)"
_ra_same "#619 the oracle reports unestablished (never a vacuous extra=0) when the image cannot be established" \
  unestablished "$(_ra_field "$RA_UNEST_REPORT" extra)" "report: $RA_UNEST_REPORT"
# The builder's matching arm — the bash half of the coupled mirror honoring the same
# rule. Without it a failed enumeration prints `total=0 copied=0 ...`, which
# `_ra_summary_balances` then certifies as balanced (0 == 0+0+...).
_ra_unest_summary="$(_ra_build_image "$_ra_tmp_root/no-such-src" "$_ra_tmp_root/unestimg" 2>/dev/null)"
_ra_same "#619 the fixture builder reports unestablished (never a vacuous total=0) when the index cannot be read" \
  unestablished "$(_ra_field "$_ra_unest_summary" total)" "summary: $_ra_unest_summary"
# #1524 — the redirect-open half of the index-write guard, distinct from the #619
# subshell-failure half above. Here `git ls-files` SUCCEEDS (the src is a real repo) and
# only the `> "$_idx"` redirect fails, because "$_dest.index" is pre-created as a directory
# (never openable for `>` truncation, so this is deterministic and uid-independent). On the
# pre-#1524 code the failed redirect was swallowed — bash does not propagate a failed
# redirect on a compound command through `!` — so the builder walked on and printed a
# vacuous `total=0` instead of the unestablished sentinel.
_ra_ridx_dest="$_ra_tmp_root/ridximg"
mkdir -p "$_ra_ridx_dest.index"
_ra_ridx_summary="$(_ra_build_image "$RA_REPO" "$_ra_ridx_dest" 2>/dev/null)"
_ra_same "#1524 the fixture builder reports unestablished (never a vacuous total=0) when the index redirect cannot be opened though git ls-files itself succeeds" \
  unestablished "$(_ra_field "$_ra_ridx_summary" total)" "summary: $_ra_ridx_summary"
# The `fail_copy` channel, driven: a regular file sitting where a nested entry's parent
# directory must go makes `mkdir -p` fail, so the entry is counted and breadcrumbed on
# its own channel instead of vanishing into the gap between `total` and `copied`.
_ra_fc="$_ra_tmp_root/fcrepo"
_ra_ok "#619 copy-failure fixture repository seeded" "$(_ra_seed_repo "$_ra_fc" && printf yes)" \
  "git init/config failed; the fail_copy arm would run against a dead repo"
(
  cd "$_ra_fc" || exit 1
  mkdir -p nested
  printf 'blocked\n' > nested/inner.txt
  printf 'fine\n' > ok.txt
  git add -A
  git commit -q -m seed
) >/dev/null 2>&1
_ra_fc_img="$_ra_tmp_root/fcimg"
_ra_fc_err="$_ra_tmp_root/fc.err"
mkdir -p "$_ra_fc_img"
: > "$_ra_fc_img/nested"   # a FILE where the entry's parent directory must be created
_ra_fc_summary="$(_ra_build_image "$_ra_fc" "$_ra_fc_img" 2>"$_ra_fc_err")"
_ra_has_file "#619 fixture builder breadcrumbs a tracked entry it could not copy" \
  "$_ra_fc_err" "FAILED to copy tracked entry nested/inner.txt"
for _ra_k in "fail_copy 1" "copied 1" "total 2"; do
  _ra_kn="${_ra_k%% *}"; _ra_kv="${_ra_k##* }"
  _ra_same "#619 fixture builder counts a copy failure on its own channel ($_ra_kn)" \
    "$_ra_kv" "$(_ra_field "$_ra_fc_summary" "$_ra_kn")" "summary: $_ra_fc_summary"
done
_ra_summary_balances "#619 a copy failure still balances the builder's own accounting" \
  "$_ra_fc_summary"
# The `fail_mode` channel, driven. `chmod` is shadowed by a stub that exits 1, for the
# duration of ONE build only: the assignment and the `hash -r` (bash caches resolved
# command paths, so an already-hashed chmod would bypass the new PATH) both live inside
# the command substitution's subshell, so nothing leaks into the rest of the module.
# A PATH stub — rather than an unwritable directory — is what reproduces the rc-127
# absent-`chmod` host the block's comment claims to cover, and it needs no privilege.
_ra_fm="$_ra_tmp_root/fmrepo"
_ra_ok "#619 mode-failure fixture repository seeded" "$(_ra_seed_repo "$_ra_fm" && printf yes)" \
  "git init/config failed; the fail_mode arm would run against a dead repo"
(
  cd "$_ra_fm" || exit 1
  printf 'x\n' > only.txt
  git add -A
  git commit -q -m seed
) >/dev/null 2>&1
_ra_cmstub="$_ra_tmp_root/chmodstub"
mkdir -p "$_ra_cmstub"
printf '#!/bin/sh\nexit 1\n' > "$_ra_cmstub/chmod"
chmod 755 "$_ra_cmstub/chmod"   # the real chmod, before anything is shadowed
_ra_fm_err="$_ra_tmp_root/fm.err"
_ra_fm_summary="$(PATH="$_ra_cmstub:$PATH"; hash -r 2>/dev/null; _ra_build_image "$_ra_fm" "$_ra_tmp_root/fmimg" 2>"$_ra_fm_err")"
_ra_has_file "#619 fixture builder breadcrumbs an index mode it could not apply" \
  "$_ra_fm_err" "FAILED to set index mode 100644 on only.txt"
# `copied 0` is the load-bearing half: a mode that did not apply must NOT be counted as
# a clean copy, which is the whole reason this channel is separate from `fail_copy`.
for _ra_k in "fail_mode 1" "copied 0" "fail_copy 0" "total 1"; do
  _ra_kn="${_ra_k%% *}"; _ra_kv="${_ra_k##* }"
  _ra_same "#619 fixture builder counts a mode failure on its own channel ($_ra_kn)" \
    "$_ra_kv" "$(_ra_field "$_ra_fm_summary" "$_ra_kn")" "summary: $_ra_fm_summary"
done
_ra_summary_balances "#619 a mode failure still balances the builder's own accounting" \
  "$_ra_fm_summary"
# The stub was scoped to the substitution above; prove it did not leak, or every
# later arm's mode expectations would be silently measuring the stub instead.
_ra_ok "#619 the chmod stub did not leak past the mode-failure build" \
  "$(case "$(command -v chmod)" in *chmodstub*) ;; *) printf yes ;; esac)" \
  "chmod still resolves to the stub after the scoped build"

# The index-state arms are exercised against a REAL git index in a temp repository,
# never a stubbed `git ls-files` — that is the boundary each of these proves.
_ra_ix="$_ra_tmp_root/ixrepo"
_ra_ok "#619 index-state fixture repository seeded" \
  "$(_ra_seed_repo "$_ra_ix" && printf yes)" \
  "git init/config failed; every index-state arm below would run against a dead repo"
# Symlink capability probe (issue #714 review). A `core.symlinks=false` checkout —
# Windows/Git Bash without the symlink privilege, the same host class the
# `core.fileMode false` reproduction below deliberately accommodates — turns `ln -s`
# into a plain file copy, so git would record 100644 and the symlink arm would go RED
# claiming the builder mis-triaged a symlink it was never given. Probe the host once and
# gate only the symlink rows on it: an unsupported host omits `link.md` entirely (so
# `copied` is unchanged at 5) and records a visible host-capability note rather than a
# false failure. The gitlink arm needs no probe — it synthesizes its 160000 entry with
# `update-index --cacheinfo` instead of requiring a real submodule checkout.
_ra_symlink_ok=no
if ln -s TOP.md "$_ra_tmp_root/.ra-symlink-probe" 2>/dev/null &&
   [ -L "$_ra_tmp_root/.ra-symlink-probe" ]; then
  _ra_symlink_ok=yes
fi
rm -f "$_ra_tmp_root/.ra-symlink-probe" 2>/dev/null || :
# On a symlink-incapable host the gated arm below (the `if [ "$_ra_symlink_ok" = yes ]`
# block) omits its two assertions. Route that condition through the accounted skip
# channel issue #838 added — `module_host_capability_skip` — so such a host yields a
# VISIBLE host-capability skip whose declared credit (2, the count of assertions the
# gated arm does not run) reconciles the module's assertion floor, rather than the silent
# stderr breadcrumb and smaller assertion set the #456 accounting cannot see (issue #856).
# The credit MUST equal the number of assertions inside the gated arm below.
[ "$_ra_symlink_ok" = yes ] ||
  module_host_capability_skip "#619 regenerate-artifacts symlink index-entry rows" \
    "this filesystem/checkout cannot create a symlink, so a 120000 index entry cannot be built" 2
mkdir -p "$_ra_ix/sub dir"
(
  cd "$_ra_ix" || exit 1
  printf 'top\n' > TOP.md
  printf 'nested\n' > "sub dir/with space.txt"
  # A NEWLINE in a filename is the load-bearing half of the `-z` claim: without -z the
  # space case still works (the path is taken whole after the TAB) but this one splits
  # one index entry into two. The space fixture alone cannot catch that mutation.
  printf 'newline\n' > "$(printf 'new\nline.txt')"
  : > empty.txt
  printf '#!/bin/sh\n' > exec.sh
  chmod 755 exec.sh
  printf 'gone\n' > deleted.txt
  [ "$_ra_symlink_ok" = yes ] && ln -s TOP.md link.md || :
  git add -A
  git commit -q -m seed
  # Tracked-then-deleted WITHOUT `git rm`: the index still lists it, the working tree
  # does not carry it.
  rm -f deleted.txt
  # core.fileMode=false is git's default on Windows: the index keeps 100755 while the
  # on-disk bit is dropped. Reproduce that exact disagreement here.
  git config core.fileMode false
  chmod 644 exec.sh
) >/dev/null 2>&1
_ra_ix_img="$_ra_tmp_root/iximg"
_ra_ix_err="$_ra_tmp_root/ix.err"
_ra_ix_summary="$(_ra_build_image "$_ra_ix" "$_ra_ix_img" 2>"$_ra_ix_err")"

# Each arm's breadcrumb is asserted as its OWN distinct string — that is what stops one
# arm silently covering another.
_ra_has_file "#619 fixture builder breadcrumbs the index entry with no working-tree file" \
  "$_ra_ix_err" "skipping index entry with no working-tree file deleted.txt"
if [ "$_ra_symlink_ok" = yes ]; then
  _ra_has_file "#619 fixture builder breadcrumbs the symlink index entry" \
    "$_ra_ix_err" "skipping symlink index entry link.md"
  _ra_ok "#619 fixture builder omits the skipped symlink entry from the image" \
    "$([ ! -e "$_ra_ix_img/link.md" ] && printf yes)" "the skipped symlink was materialized"
fi
_ra_ok "#619 fixture builder omits the skipped no-working-tree-file entry from the image" \
  "$([ ! -e "$_ra_ix_img/deleted.txt" ] && printf yes)" \
  "a skipped entry was materialized"
_ra_expect_symlink=0
[ "$_ra_symlink_ok" = yes ] && _ra_expect_symlink=1 || :
for _ra_k in "skip_missing 1" "skip_gitlink 0" "skip_symlink $_ra_expect_symlink"; do
  _ra_kn="${_ra_k%% *}"; _ra_kv="${_ra_k##* }"
  _ra_same "#619 fixture builder subtracts $_ra_kn from the denominator by name" \
    "$_ra_kv" "$(_ra_field "$_ra_ix_summary" "$_ra_kn")" "summary: $_ra_ix_summary"
done
RA_IX_REPORT="$(_ra_image_report "$_ra_ix" "$_ra_ix_img")"
_ra_ok "#619 fixture builder skip arms leave no completeness gap" \
  "$([ "$(_ra_field "$RA_IX_REPORT" extra)" = 0 ] && [ "$(_ra_field "$RA_IX_REPORT" missing)" = 0 ] && printf yes)" \
  "$RA_IX_REPORT"
# Positive control for the pair above: `extra=0 missing=0` is also what an EMPTY index
# against an empty image reports, so pin the count of blobs this fixture actually has
# (TOP.md, sub dir/with space.txt, new\nline.txt, empty.txt, exec.sh — deleted.txt and
# link.md are the two skipped arms).
_ra_same "#619 the index-state fixture image is non-empty (completeness pair is live)" \
  5 "$(_ra_field "$_ra_ix_summary" copied)" "summary: $_ra_ix_summary"
_ra_summary_balances "#619 index-state fixture builder accounts for every index entry it saw" \
  "$_ra_ix_summary"
_ra_ok "#619 fixture builder reproduces a path containing a newline (the -z contract)" \
  "$([ -f "$_ra_ix_img/$(printf 'new\nline.txt')" ] && printf yes)" \
  "a newline-bearing tracked path was split or lost — the -z read is not holding"
# Modes come from the index even though the working-tree bit disagrees.
_ra_ok "#619 fixture builder sets modes from the index (100755 stays executable)" \
  "$([ -x "$_ra_ix_img/exec.sh" ] && printf yes)" \
  "exec.sh is not executable in the image; the working-tree bit was inherited"
_ra_ok "#619 fixture builder sets modes from the index (100644 stays non-executable)" \
  "$([ ! -x "$_ra_ix_img/TOP.md" ] && printf yes)" "TOP.md is executable in the image"
# Boundary paths: no directory component, a space in the path, and a zero-byte file.
for _ra_case in "TOP.md" "sub dir/with space.txt" "empty.txt"; do
  _ra_ok "#619 fixture builder reproduces boundary path: $_ra_case" \
    "$([ -f "$_ra_ix_img/$_ra_case" ] && printf yes)" "absent from the image"
done
_ra_ok "#619 fixture builder reproduces a tracked empty file with zero bytes" \
  "$([ -f "$_ra_ix_img/empty.txt" ] && [ ! -s "$_ra_ix_img/empty.txt" ] && printf yes)" \
  "empty.txt is absent or non-empty"
# Gitlink arm: a synthetic 160000 index entry, added with update-index so no real
# submodule checkout is required.
_ra_gl="$_ra_tmp_root/glrepo"
_ra_ok "#619 gitlink fixture repository seeded" "$(_ra_seed_repo "$_ra_gl" && printf yes)" \
  "git init/config failed; the gitlink arm would run against a dead repo"
(
  cd "$_ra_gl" || exit 1
  printf 'x\n' > keep.txt
  git add -A
  git commit -q -m seed
  git update-index --add --cacheinfo 160000,"$(git rev-parse HEAD)",vendored
) >/dev/null 2>&1
_ra_gl_summary="$(_ra_build_image "$_ra_gl" "$_ra_tmp_root/glimg" 2>"$_ra_tmp_root/gl.err")"
_ra_has_file "#619 fixture builder breadcrumbs the gitlink index entry" \
  "$_ra_tmp_root/gl.err" "skipping gitlink index entry vendored"
for _ra_k in "copied 1" "skip_gitlink 1" "skip_missing 0" "skip_symlink 0"; do
  _ra_kn="${_ra_k%% *}"; _ra_kv="${_ra_k##* }"
  _ra_same "#619 fixture builder skips a gitlink without failing the build ($_ra_kn)" \
    "$_ra_kv" "$(_ra_field "$_ra_gl_summary" "$_ra_kn")" "summary: $_ra_gl_summary"
done
# Unmerged index: the same path at stages 1/2/3 contributes exactly once.
_ra_cf="$_ra_tmp_root/cfrepo"
_ra_ok "#619 unmerged-index fixture repository seeded" \
  "$(_ra_seed_repo "$_ra_cf" -b main && printf yes)" \
  "git init/config failed; the unmerged-stage arm would run against a dead repo"
(
  cd "$_ra_cf" || exit 1
  printf 'base\n' > c.txt; git add -A; git commit -q -m base
  git checkout -q -b other
  printf 'other\n' > c.txt; git add -A; git commit -q -m other
  git checkout -q main
  printf 'mine\n' > c.txt; git add -A; git commit -q -m mine
  git merge other
) >/dev/null 2>&1
# PRECONDITION, asserted rather than assumed: `total 1` / `copied 1` is ALSO what a
# clean single-file repo reports, so without proving the index really is unmerged this
# arm would keep passing while exercising no de-duplication at all — a future git that
# auto-resolves, or an inherited rerere, would empty it silently. Count the stage-2/3
# rows `git ls-files -u` reports for the conflicted path (bash builtin arithmetic; no
# `wc`, which is not preflight-guaranteed and must not decide an emitted value).
_ra_cf_unmerged=0
while IFS= read -r _ra_line; do
  [ -n "$_ra_line" ] && _ra_cf_unmerged=$((_ra_cf_unmerged + 1))
done < <(cd "$_ra_cf" && git ls-files -u 2>/dev/null)
_ra_ok "#619 the unmerged-index fixture really has a conflicted path (de-dup arm is live)" \
  "$([ "$_ra_cf_unmerged" -ge 2 ] && printf yes)" \
  "git ls-files -u reported $_ra_cf_unmerged stage rows; the merge did not conflict, so the de-duplication below would be vacuous"
_ra_cf_err="$_ra_tmp_root/cf.err"
_ra_cf_summary="$(_ra_build_image "$_ra_cf" "$_ra_tmp_root/cfimg" 2>"$_ra_cf_err")"
for _ra_k in "total 1" "copied 1"; do
  _ra_kn="${_ra_k%% *}"; _ra_kv="${_ra_k##* }"
  _ra_same "#619 fixture builder de-duplicates unmerged index stages ($_ra_kn)" \
    "$_ra_kv" "$(_ra_field "$_ra_cf_summary" "$_ra_kn")" \
    "expected one entry, got '$_ra_cf_summary'; stderr: $(tr '\n' '|' <"$_ra_cf_err" 2>/dev/null)"
done

# A fixture must be a git repository: coverage_map_guard.py enumerates the tracked
# surface with `git ls-files`. The synthetic origin/main ref keeps the fixture a
# faithful image of a real checkout.
(
  cd "$_ra_pristine" || exit 1
  git init -q . 2>/dev/null
  git config user.email devflow@example.invalid
  git config user.name devflow
  git add -A 2>/dev/null
  git commit -q -m fixture 2>/dev/null
  git update-ref refs/remotes/origin/main HEAD 2>/dev/null
) >/dev/null 2>&1

_ra_fixture() {  # <dest>
  cp -R "$_ra_pristine" "$1"
}

# Re-reconcile the cloud-writer closure in a fixture after planting a change that also
# moves a reached asset, so a downstream judgment assertion is attributable to the row
# under test rather than to incidental manifest drift.
_ra_reconcile() {  # <root>
  # rc is CHECKED, not swallowed: if the reconcile step silently fails, the manifest row
  # stays drifted and the downstream assertion becomes attributable to that row instead of
  # the one under test — a vacuous pass wearing a green tick. Surface it as a named failure
  # rather than letting the caller's assertion misreport what it measured.
  if ! ( cd "$1" && python3 lib/test/cloud_writer_contract.py generate >/dev/null 2>&1 ) >/dev/null 2>&1; then
    assert_eq "#619 fixture reconcile succeeded for ${1##*/}" yes \
      "no(cloud-writer generate failed; downstream assertions would be misattributed)"
  fi
}

# Run the helper against a target root, capturing combined output and rc into
# per-fixture files. The helper is invoked by its LIVE path with --repo-root pointed
# at the fixture, which is exactly how the suite drives its failure arms.
# `--with-floors` is passed here so every existing row-integration fixture keeps
# exercising the opt-in exact-module-floors row; `_ra_run_default` below drives the
# default pass, which reports that row as not measured instead of running it.
_ra_run() {  # <root>
  python3 "$RA_HELPER" --repo-root "$1" --with-floors >"$1/.ra.out" 2>&1
  printf '%s\n' "$?" >"$1/.ra.rc"
}
_ra_run_default() {  # <root>
  python3 "$RA_HELPER" --repo-root "$1" >"$1/.ra.out" 2>&1
  printf '%s\n' "$?" >"$1/.ra.rc"
}
_ra_rc() { cat "$1/.ra.rc"; }
_ra_has() {  # name root substring   (the fixture-root form of _ra_has_file)
  _ra_has_file "$1" "$2/.ra.out" "$3"
}

# The registry's row names, declared ONCE and consumed by both the A1 clean-line loop
# and the A4 --list loop — adding a row must not mean editing two lists.
RA_ROW_NAMES="capability-profile-literals plugin-identity-regions coverage-map-ratchet exact-module-floors"

# Batched-pass fixtures exercise row dispatch and outcome classification many times. The
# reconciler's own focused Python suite below drives its real subprocess protocol; these
# surrounding full-tree fixtures substitute only the expensive module runner and return
# each fixture registry's live floor, keeping the row clean without duplicating eleven
# module populations in every unrelated artifact-row scenario.
RA_FLOOR_RUNNER="$_ra_tmp_root/floor-runner.sh"
# shellcheck disable=SC2016  # these single-quoted arguments are the generated runner's source; expansion belongs to that later process
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'module_id=""; supplied_registry=""' \
  'while [ "$#" -gt 0 ]; do' \
  '  case "$1" in --registry) supplied_registry="$2"; shift 2 ;; --log-dir) shift 2 ;; --heavy-units) shift 2 ;; *) module_id="$1"; shift ;; esac' \
  'done' \
  'python3 - "$PWD/scripts/workflow-flight-recorder-registry.json" "$module_id" "$supplied_registry" <<'"'"'PY'"'"'' \
  'import json, os, sys' \
  '# Honor --registry the way the real runner does. Discarding it would leave the' \
  '# reconciler free to stop passing a lowered measurement registry at all while every' \
  '# fixture here stayed green — the lowering step untested by the very fixtures that' \
  '# depend on it. The SUPPLIED registry is what proves the floor was lowered; the' \
  '# measurement itself is still derived from the live fixture registry, because these' \
  '# fixtures assert the reconciler reacts to a floor delta, not to the sentinel 1.' \
  'supplied = sys.argv[3]' \
  'if not supplied:' \
  '    print("fixture runner: --registry was not supplied", file=sys.stderr); raise SystemExit(9)' \
  'if json.load(open(supplied))["test_modules"][sys.argv[2]]["minimum_assertions"] != 1:' \
  '    print("fixture runner: measurement floor was not lowered", file=sys.stderr); raise SystemExit(9)' \
  'registry = json.load(open(sys.argv[1]))' \
  'floor = registry["test_modules"][sys.argv[2]]["minimum_assertions"] + int(os.environ.get("DEVFLOW_FLOOR_TEST_DELTA", "0"))' \
  'print(f"Module {sys.argv[2]}: {floor} passed, 0 failed")' \
  'PY' > "$RA_FLOOR_RUNNER"
chmod 755 "$RA_FLOOR_RUNNER"
export DEVFLOW_RECONCILE_MODULE_FLOORS_RUNNER="$RA_FLOOR_RUNNER"

# The four files `lib/generate-plugin-identity.py` bakes a region into. Declared once and
# consumed by the A3 write-scope snapshot and the A3b drift arm below. All four are listed
# even though only three carry a conflict-path line: write scope is about what the helper
# may TOUCH, which is every region file, while the conflict oracle is about which row owns a
# path — and `devflow-runner.yml` is owned there by the capability row (see the registry's
# disclosed residual).
RA_IDENT_REGION_FILES=".github/actions/vendor-plugin/vendor-slice.sh install.sh .github/workflows/devflow-runner.yml scripts/resolve-extra-plugins.sh"
_ra_ident_regions() {  # <root> — the concatenated bytes of every baked identity region file
  local _root="$1" _f
  for _f in $RA_IDENT_REGION_FILES; do cat "$_root/$_f"; done
}

# ── A1 — clean-tree run: exit 0 with a per-row clean line for every row ──────
# Run against a PRISTINE FIXTURE, never the live checkout. Two reasons, both real:
# (1) the opt-in exact-module-floors row WRITES scripts/workflow-flight-recorder-registry.json
#     and lib/test/run.sh, so a live run would mutate tracked files in the developer's tree
#     as a test side effect — invisible on a reconciled tree, a silent regeneration on
#     exactly the drifted tree this helper exists to detect;
# (2) the live tree's cleanliness is a property of whatever branch the suite runs on,
#     not of the helper — a branch legitimately editing a generated artifact's source
#     makes its row emit JUDGMENT, so a live per-row `clean` assertion would go RED for
#     reasons unrelated to the code under test.
# The fixture is committed with origin/main == HEAD, so every row is clean BY
# CONSTRUCTION. The live tree keeps its non-mutating coverage in A4 (`--list` launches
# no row) and in the suite's own artifact gates.
RA_A1="$_ra_tmp_root/a1"; _ra_fixture "$RA_A1"
# `--with-floors`, so the loop below covers EVERY registered row including the opt-in
# one; the default pass's own reporting of that row is pinned in the opt-in block below.
RA_CLEAN_OUT="$(python3 "$RA_HELPER" --repo-root "$RA_A1" --with-floors 2>&1)"; RA_CLEAN_RC=$?
assert_eq "#619 A1 clean-tree run exits 0" "0" "$RA_CLEAN_RC"
for _row in $RA_ROW_NAMES; do
  case "$RA_CLEAN_OUT" in
    *"[$_row] clean"*) assert_eq "#619 A1 clean-tree row reports clean: $_row" yes yes ;;
    *) assert_eq "#619 A1 clean-tree row reports clean: $_row" yes "no(no clean line for $_row)" ;;
  esac
done
_ra_live_unchanged "#619 A1 live manifest byte-unchanged after the clean run"

# ── A3 — a judgment drift in ONE invocation: judgment item, write scope honored ─
RA_A3="$_ra_tmp_root/a3"; _ra_fixture "$RA_A3"
python3 "$RA_CAPMUT" "$RA_A3" profiles-extra-key >/dev/null 2>&1 \
  || assert_eq "#619 A3 planted capability drift applied" yes "no(cap-mutate failed)"
# Byte snapshots of every judgment-gated artifact: the helper must not write ANY of
# them. This is the write-scope guarantee stated as a negative assertion, taken with
# the suppressed input (planted drift) present rather than on a clean tree.
RA_A3_WF="$(cat "$RA_A3/.github/workflows/devflow-runner.yml" "$RA_A3/.github/workflows/devflow.yml" \
            "$RA_A3/.github/workflows/devflow-implement.yml" "$RA_A3/.github/workflows/matcher-probe.yml")"
RA_A3_LOCK="$(cat "$RA_A3/lib/review-profile.tokens")"
RA_A3_COVMAP="$(cat "$RA_A3/lib/test/modules/coverage-map.json")"
RA_A3_IDENT="$(_ra_ident_regions "$RA_A3")"
_ra_run "$RA_A3"
assert_eq "#619 A3 capability drift exits 1" "1" "$(_ra_rc "$RA_A3")"
_ra_has "#619 A3 one invocation reports the capability judgment item" "$RA_A3" \
  "[capability-profile-literals] JUDGMENT"
_ra_has "#619 A3 the capability item names its governing policy" "$RA_A3" \
  "update lib/review-profile.tokens when the resolved review list widens"
_ra_cmp() {  # name expected root-relative-file
  _ra_same "$1" "$2" "$(cat "$RA_A3/$3")" "$3 was written by a judgment row"
}
RA_A3_WF_NOW="$(cat "$RA_A3/.github/workflows/devflow-runner.yml" "$RA_A3/.github/workflows/devflow.yml" \
                "$RA_A3/.github/workflows/devflow-implement.yml" "$RA_A3/.github/workflows/matcher-probe.yml")"
_ra_same "#619 A3 write scope: the four workflow files are byte-unchanged" \
  "$RA_A3_WF" "$RA_A3_WF_NOW" "a workflow was written by a judgment row"
_ra_cmp "#619 A3 write scope: lib/review-profile.tokens is byte-unchanged" "$RA_A3_LOCK" lib/review-profile.tokens
# The coverage-map ratchet is a judgment row like every other, so its artifact is
# equally in the never-written set — omitting it left one registered judgment row's
# write scope unasserted.
_ra_cmp "#619 A3 write scope: the coverage map is byte-unchanged" "$RA_A3_COVMAP" lib/test/modules/coverage-map.json
# The plugin-identity row is a judgment row too, so its four baked region files join the
# never-written set. Without this, the row could silently acquire a write path (its
# generator's bare form rewrites all four) and the write-scope guarantee would be false for
# a quarter of the registry while every other assertion here stayed green.
_ra_same "#619 A3 write scope: the four baked identity regions are byte-unchanged" \
  "$RA_A3_IDENT" "$(_ra_ident_regions "$RA_A3")" "an identity region was written by a judgment row"
_ra_live_unchanged "#619 A3 live manifest byte-unchanged after the capability-drift run"

# ── A3b — plugin-identity drift is SEEN by the batched pass ─────────────────────
# The regression this row was added for: before it existed the batched pass reported
# `all artifacts reconciled — exit 0` on a tree whose identity regions were stale, so the
# drift survived until a full suite run turned RED on the #927 G2 gate minutes later.
# The drift is planted in the SOURCE (lib/plugin-identity.json) with the regions left
# alone, which is exactly the shape an identity edit produces before its regeneration.
RA_A3B="$_ra_tmp_root/a3b"; _ra_fixture "$RA_A3B"
python3 - "$RA_A3B" <<'RA_A3B_PLANT' >/dev/null 2>&1 \
  || assert_eq "#619 A3b planted identity drift applied" yes "no(plant failed)"
import json, sys
p = sys.argv[1] + "/lib/plugin-identity.json"
d = json.load(open(p))
d["plugin_aliases"] = list(d.get("plugin_aliases", [])) + ["devflow-a3b-alias"]
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
RA_A3B_PLANT
# Positive control: the planted drift must actually be drift. Without it a plant that
# silently no-opped would leave the assertions below measuring a clean tree.
( cd "$RA_A3B" && python3 lib/generate-plugin-identity.py --check ) >/dev/null 2>&1
assert_eq "#619 A3b the plant really drifts the baked regions" "1" "$?"
RA_A3B_IDENT="$(_ra_ident_regions "$RA_A3B")"
_ra_run "$RA_A3B"
assert_eq "#619 A3b identity drift exits 1" "1" "$(_ra_rc "$RA_A3B")"
_ra_has "#619 A3b the identity drift is reported as a judgment item" "$RA_A3B" \
  "[plugin-identity-regions] JUDGMENT"
# The drift diagnostic, not merely the row name: a row that exited 1 for any reason would
# satisfy the line above, so pin the generator's own drift wording too.
_ra_has "#619 A3b the identity item carries the generator's drift diagnostic" "$RA_A3B" \
  "baked identity region(s) differ from"
_ra_has "#619 A3b the identity item names its governing policy" "$RA_A3B" \
  "rewrite the baked regions with"
_ra_same "#619 A3b write scope: the identity regions stay unwritten on the drift run" \
  "$RA_A3B_IDENT" "$(_ra_ident_regions "$RA_A3B")" "the identity row wrote its own artifact"
_ra_live_unchanged "#619 A3b live manifest byte-unchanged after the identity-drift run"

# A broken region BANNER is an input failure, not drift: the generator cannot locate the
# region it would rewrite, so reporting it as a judgment item would aim the remedy
# ("re-run the generator") at a file the generator has already refused to parse.
RA_A3C="$_ra_tmp_root/a3c"; _ra_fixture "$RA_A3C"
python3 - "$RA_A3C" <<'RA_A3C_PLANT' >/dev/null 2>&1 \
  || assert_eq "#619 A3c planted banner corruption applied" yes "no(plant failed)"
import sys
p = sys.argv[1] + "/install.sh"
t = open(p).read().replace("# devflow-plugin-identity:begin", "# NOT-A-BANNER", 1)
open(p, "w").write(t)
RA_A3C_PLANT
_ra_run "$RA_A3C"
assert_eq "#619 A3c a corrupt identity banner routes to the infrastructure state (exit 2)" \
  "2" "$(_ra_rc "$RA_A3C")"
_ra_has "#619 A3c the corrupt banner is attributed to its ROW as an input failure" "$RA_A3C" \
  "[plugin-identity-regions] INFRASTRUCTURE"
_ra_has "#619 A3c the corrupt banner is NOT dressed up as drift" "$RA_A3C" \
  "reporting an input failure, not drift"

# ── A4 — --list names every artifact ────────────────────────────────────────
RA_LIST="$(python3 "$RA_HELPER" --list 2>&1)"; RA_LIST_RC=$?
assert_eq "#619 A4 --list exits 0" "0" "$RA_LIST_RC"
for _row in $RA_ROW_NAMES; do
  case "$RA_LIST" in
    *"artifact	$_row	"*) assert_eq "#619 A4 --list names artifact: $_row" yes yes ;;
    *) assert_eq "#619 A4 --list names artifact: $_row" yes "no($_row absent from --list)" ;;
  esac
done

# ── AP — read-only preflight mode (issue #1244) ──────────────────────────────
# The preflight runs ONLY the preflight-eligible rows, read-only, and refuses (exit 1)
# only on a positively-attributed drift. Every arm runs against a temp fixture, never the
# live checkout, for the same confinement reason A1 does.
_ra_preflight() {  # <root>
  python3 "$RA_HELPER" --preflight --repo-root "$1" >"$1/.rap.out" 2>&1
  printf '%s\n' "$?" >"$1/.rap.rc"
}
_ra_prc() { cat "$1/.rap.rc"; }

# AP1 — clean fixture: exit 0, writes nothing, one clean line per eligible row, and the
# ineligible exact-module-floors row is never touched (AC1/AC2).
RA_AP1="$_ra_tmp_root/ap1"; _ra_fixture "$RA_AP1"
RA_AP1_MAN_BEFORE="$(cat "$RA_AP1/scripts/devflow-cloud-writer-contract.json")"
_ra_preflight "$RA_AP1"
assert_eq "#1244 AP1 clean fixture preflight exits 0" "0" "$(_ra_prc "$RA_AP1")"
_ra_same "#1244 AP1 preflight writes nothing (manifest byte-unchanged)" \
  "$RA_AP1_MAN_BEFORE" "$(cat "$RA_AP1/scripts/devflow-cloud-writer-contract.json")" \
  "the read-only preflight mutated the manifest"
for _erow in capability-profile-literals plugin-identity-regions coverage-map-ratchet env-freeze-advisory-region; do
  case "$(cat "$RA_AP1/.rap.out")" in
    *"[$_erow] clean"*) assert_eq "#1244 AP1 eligible row reports clean: $_erow" yes yes ;;
    *) assert_eq "#1244 AP1 eligible row reports clean: $_erow" yes "no(no clean line for $_erow)" ;;
  esac
done
# The ineligible row's argv (reconcile-module-floors.py, a WRITING 7.8-min check) must
# never be invoked, so neither its name nor its script appears in the preflight output.
case "$(cat "$RA_AP1/.rap.out")" in
  *exact-module-floors*|*reconcile-module-floors*) assert_eq "#1244 AP1 preflight never runs the ineligible exact-module-floors row" yes "no(ineligible row referenced in preflight output)" ;;
  *) assert_eq "#1244 AP1 preflight never runs the ineligible exact-module-floors row" yes yes ;;
esac

# AP3 — --list reports eligibility per row, and the ineligible row is declared ineligible.
case "$RA_LIST" in
  *"preflight	exact-module-floors	ineligible	"*) assert_eq "#1244 AP3 --list declares exact-module-floors ineligible" yes yes ;;
  *) assert_eq "#1244 AP3 --list declares exact-module-floors ineligible" yes "no(exact-module-floors not declared ineligible)" ;;
esac
for _erow in capability-profile-literals plugin-identity-regions coverage-map-ratchet env-freeze-advisory-region; do
  case "$RA_LIST" in
    *"preflight	$_erow	eligible	"*) assert_eq "#1244 AP3 --list declares eligible: $_erow" yes yes ;;
    *) assert_eq "#1244 AP3 --list declares eligible: $_erow" yes "no($_erow not declared eligible)" ;;
  esac
done

# AP4 — an eligible judgment row that cannot be checked routes to exit 2 (UNCHECKABLE),
# driven by the REAL preflight (not a coordinator stub). A malformed lib/capability-profiles.json
# makes `generate-capability-profiles.py --check` exit 1 with its `manifest malformed JSON:`
# infra-marker, which the preflight classifies UNCHECKABLE. No row drifts, so exit 2.
RA_AP4="$_ra_tmp_root/ap4"; _ra_fixture "$RA_AP4"
printf 'not valid json {' > "$RA_AP4/lib/capability-profiles.json"
RA_AP4_MAN_BEFORE="$(cat "$RA_AP4/scripts/devflow-cloud-writer-contract.json")"
_ra_preflight "$RA_AP4"
assert_eq "#1244 AP4 an uncheckable eligible row exits 2" "2" "$(_ra_prc "$RA_AP4")"
_ra_has_file "#1244 AP4 the uncheckable row is reported UNCHECKABLE" "$RA_AP4/.rap.out" \
  "[capability-profile-literals] UNCHECKABLE"
_ra_has_file "#1244 AP4 the exit-2 summary names an uncheckable artifact" "$RA_AP4/.rap.out" \
  "could not check at least one eligible artifact"
_ra_same "#1244 AP4 preflight writes nothing on the uncheckable arm" \
  "$RA_AP4_MAN_BEFORE" "$(cat "$RA_AP4/scripts/devflow-cloud-writer-contract.json")" \
  "the read-only preflight mutated the manifest on the uncheckable arm"

# AP6 — a crashing judgment generator (a traceback, exit 1, NO row infra-marker) routes to
# UNCHECKABLE, not DRIFT. capability-profile-literals deliberately omits the traceback marker
# from its batched-pass infra_markers, so this exercises the preflight's OWN universal
# traceback→UNCHECKABLE guard (issue #1244 fail-open contract): without it this crash would be
# misclassified DRIFT and the coordinator would block the whole suite.
RA_AP6="$_ra_tmp_root/ap6"; _ra_fixture "$RA_AP6"
cat > "$RA_AP6/lib/generate-capability-profiles.py" <<'PY'
#!/usr/bin/env python3
raise RuntimeError("simulated generator crash")
PY
chmod 755 "$RA_AP6/lib/generate-capability-profiles.py"
_ra_preflight "$RA_AP6"
assert_eq "#1244 AP6 a crashing judgment generator exits 2 (UNCHECKABLE, not drift)" "2" "$(_ra_prc "$RA_AP6")"
_ra_has_file "#1244 AP6 the crash is reported as a crash, not drift" "$RA_AP6/.rap.out" \
  "reporting a crash or input failure, not drift"
case "$(cat "$RA_AP6/.rap.out")" in
  *"preflight detected drift"*) assert_eq "#1244 AP6 a crash is never reported as drift" yes "no(a crash was misclassified as drift)" ;;
  *) assert_eq "#1244 AP6 a crash is never reported as drift" yes yes ;;
esac

# AP8 — a JUDGMENT row's own DRIFT arm, which is the preflight's primary detection path.
# Every eligible row is a judgment row carrying no `preflight_positive_marker`, so drift is
# reached by the terminal fall-through in `run_preflight_row` — the arm that fires when the
# exit is in-set, non-clean, and matches NO infra marker and NO traceback. Every other AP
# arm reaches a different branch: AP4 drives a judgment row's infra-marker arm, AP6 drives a
# crash. So without this arm the fall-through could be inverted to "not drift" and the whole
# module would stay green while genuine drift silently launched the suite.
#
# The plant is the A3b shape — an identity SOURCE edit with the baked regions left stale —
# because it is a NON-CRASHING content drift: the generator runs to completion and reports
# its own diagnostic, which is what distinguishes this arm from every crash arm above.
RA_AP8="$_ra_tmp_root/ap8"; _ra_fixture "$RA_AP8"
python3 - "$RA_AP8" <<'RA_AP8_PLANT' >/dev/null 2>&1 \
  || assert_eq "#1244 AP8 planted identity drift applied" yes "no(plant failed)"
import json, sys
p = sys.argv[1] + "/lib/plugin-identity.json"
d = json.load(open(p))
d["plugin_aliases"] = list(d.get("plugin_aliases", [])) + ["devflow-ap8-alias"]
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
RA_AP8_PLANT
# Positive control, in two parts, because the arm under test is selected by what the
# generator did NOT print as much as by its exit code. (1) the plant must really drift —
# otherwise every assertion below measures a clean tree; (2) the generator's output must
# carry none of this row's infra markers and no traceback — otherwise the run lands on the
# UNCHECKABLE arm AP4/AP6 already cover and the fall-through stays undriven.
RA_AP8_PROBE="$( cd "$RA_AP8" && python3 lib/generate-plugin-identity.py --check 2>&1 )"
assert_eq "#1244 AP8 the plant really drifts the baked regions (exit 1)" "1" "$?"
_ra_ok "#1244 AP8 the drift carries NO infra marker and no traceback (so the judgment fall-through is the branch under test)" \
  "$(case "$RA_AP8_PROBE" in
       *"Traceback (most recent call last)"*|*"banner(s); expected exactly 1"*|*"after its begin banner"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "the planted drift matched an UNCHECKABLE marker, so this arm would measure AP4/AP6's branch instead"
RA_AP8_IDENT="$(_ra_ident_regions "$RA_AP8")"
_ra_preflight "$RA_AP8"
assert_eq "#1244 AP8 a judgment row's content drift exits 1" "1" "$(_ra_prc "$RA_AP8")"
_ra_has_file "#1244 AP8 the drifting judgment row is reported DRIFT by name" \
  "$RA_AP8/.rap.out" "[plugin-identity-regions] DRIFT"
_ra_has_file "#1244 AP8 the judgment drift carries the generator's own drift diagnostic" \
  "$RA_AP8/.rap.out" "baked identity region(s) differ from"
_ra_has_file "#1244 AP8 the judgment drift names its governing policy" \
  "$RA_AP8/.rap.out" "rewrite the baked regions with"
_ra_has_file "#1244 AP8 the judgment drift prints the drift summary line" \
  "$RA_AP8/.rap.out" "preflight detected drift"
# The machine verdict line is what the coordinator actually reads (AP10 drives that end to
# end); assert it here too so a judgment-row drift is proven to emit the refusal contract
# and not merely the human sentence beside it.
_ra_has_file "#1244 AP8 the judgment drift emits the machine drift verdict the coordinator reads" \
  "$RA_AP8/.rap.out" "regenerate-artifacts: preflight-verdict: drift"
_ra_ok "#1244 AP8 a judgment drift never reports the uncheckable summary" \
  "$(case "$(cat "$RA_AP8/.rap.out")" in
       *"could not check at least one eligible artifact"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "a positively-detected judgment drift was reported as uncheckable, which fails OPEN"
_ra_same "#1244 AP8 preflight writes nothing on the judgment-drift arm" \
  "$RA_AP8_IDENT" "$(_ra_ident_regions "$RA_AP8")" \
  "the read-only preflight rewrote the identity regions it reported as drifted"
_ra_live_unchanged "#1244 AP8 live manifest byte-unchanged after the judgment-drift preflight"

# AP9 — the machine verdict line exists for all three verdicts, so a consumer never has to
# re-derive "checked and clean" from "could not check" out of an exit code alone. Read off
# the fixtures already run above rather than re-running them.
_ra_has_file "#1244 AP9 a clean preflight emits the clean verdict line" \
  "$RA_AP1/.rap.out" "regenerate-artifacts: preflight-verdict: clean"
_ra_has_file "#1244 AP9 an uncheckable preflight emits the uncheckable verdict line" \
  "$RA_AP4/.rap.out" "regenerate-artifacts: preflight-verdict: uncheckable"
# The verdicts are mutually exclusive: a clean run that also emitted the drift verdict would
# make the coordinator refuse on a reconciled tree.
_ra_ok "#1244 AP9 a clean preflight emits no drift verdict" \
  "$(case "$(cat "$RA_AP1/.rap.out")" in
       *"preflight-verdict: drift"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "the clean run emitted the drift verdict, which would make the coordinator refuse to launch"
_ra_ok "#1244 AP9 an uncheckable preflight emits no drift verdict (it must fail OPEN)" \
  "$(case "$(cat "$RA_AP4/.rap.out")" in
       *"preflight-verdict: drift"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "an unestablished check emitted the drift verdict, which would block the suite on nothing"

# ── AP10 — the coordinator end-to-end against the REAL preflight (issue #1244) ─
# The `parallel-suite-runner` module drives every coordinator arm through an INJECTED stub,
# so two things stayed unasserted there and are asserted here instead, in the one module
# that owns a full checkout image:
#   * the DEFAULT binding — nothing pinned that an unset DEVFLOW_ARTIFACT_PREFLIGHT resolves
#     to the bundled helper at all. Emptying that default, or renaming the helper, left the
#     feature absent from every real run with the whole suite green.
#   * the CROSS-FILE verdict contract — the coordinator's refusal comparand is produced in
#     `regenerate-artifacts.py`, and every stub hardcoded its own copy of it, so the two
#     could drift apart with nothing red.
# The dispatcher stays stubbed (the shard seam is orthogonal, and a real population here
# would fork a second suite); the PREFLIGHT is the real one, resolved by default.
_ra_plant_dispatcher() {  # <fixture-root> — a shard dispatcher that writes one real tally
  cat > "$1/ra-dispatch.sh" <<'RA_DISPATCH_EOF'
#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
case "${1-}" in
  --list-shards) printf '%s\n' alpha; exit 0 ;;
esac
D="${DEVFLOW_SHARD_TALLY_DIR:?}"
mkdir -p "$D"
LOG="$D/log.txt"
printf '2 passed, 0 failed\n' > "$LOG"
python3 "$HERE/lib/test/shard-tally.py" extract --shard "$1" --tier monolith \
  --log "$LOG" --rc 0 --out "$D" >/dev/null
RA_DISPATCH_EOF
  chmod +x "$1/ra-dispatch.sh"
}

# AP10a — the drifted tree from AP8, run through the coordinator with NO override: the real
# default preflight must be reached, must detect the judgment-row drift, and the coordinator
# must refuse to launch. This single arm binds all three surfaces — default resolution,
# the real Python producer's verdict, and the shell comparand that reads it.
_ra_plant_dispatcher "$RA_AP8"
RA_AP10_OUT="$( cd "$RA_AP8" && DEVFLOW_SHARD_DISPATCHER="$RA_AP8/ra-dispatch.sh" \
  bash lib/test/run-parallel.sh 2>&1 )"; RA_AP10_RC=$?
_ra_ok "#1244 AP10a the coordinator refuses (non-zero) on real drift with the DEFAULT preflight" \
  "$([ "$RA_AP10_RC" -ne 0 ] && printf yes || printf no)" \
  "the coordinator exited 0 on a drifted tree; output: $(printf '%s' "$RA_AP10_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP10a the coordinator launches NO shard on real drift" \
  "$(case "$RA_AP10_OUT" in *"launched shard"*) printf no ;; *) printf yes ;; esac)" \
  "a shard was launched despite detected drift; output: $(printf '%s' "$RA_AP10_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP10a the coordinator refuses by name" \
  "$(case "$RA_AP10_OUT" in *"launching no shard"*) printf yes ;; *) printf no ;; esac)" \
  "the refusal message is absent; output: $(printf '%s' "$RA_AP10_OUT" | tr '\n' '|')"
# The real helper's own row line, echoed by the coordinator: this is what proves the
# DEFAULT resolved to the bundled helper rather than to nothing (an empty default warns and
# proceeds, printing no row line at all).
_ra_ok "#1244 AP10a the echoed report is the REAL helper's row output, not a stub's" \
  "$(case "$RA_AP10_OUT" in *"[plugin-identity-regions] DRIFT"*) printf yes ;; *) printf no ;; esac)" \
  "the coordinator printed no real preflight row line, so the default binding was not exercised"
_ra_ok "#1244 AP10a the coordinator never treated the real drift as inconclusive" \
  "$(case "$RA_AP10_OUT" in *"preflight was inconclusive"*) printf no ;; *) printf yes ;; esac)" \
  "real drift took the fail-OPEN arm; output: $(printf '%s' "$RA_AP10_OUT" | tr '\n' '|')"

# AP10b — the reconciled counterpart, so AP10a's refusal is attributable to the planted
# drift and not to the coordinator refusing on every fixture. A clean tree with the same
# real default preflight launches the shard and completes.
RA_AP10B="$_ra_tmp_root/ap10b"; _ra_fixture "$RA_AP10B"; _ra_plant_dispatcher "$RA_AP10B"
RA_AP10B_OUT="$( cd "$RA_AP10B" && DEVFLOW_SHARD_DISPATCHER="$RA_AP10B/ra-dispatch.sh" \
  bash lib/test/run-parallel.sh 2>&1 )"; RA_AP10B_RC=$?
_ra_same "#1244 AP10b a reconciled tree with the DEFAULT preflight exits 0" "0" "$RA_AP10B_RC" \
  "output: $(printf '%s' "$RA_AP10B_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP10b a reconciled tree still launches its shard" \
  "$(case "$RA_AP10B_OUT" in *"launched shard alpha"*) printf yes ;; *) printf no ;; esac)" \
  "no shard launched on a clean tree; output: $(printf '%s' "$RA_AP10B_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP10b a reconciled tree emits no preflight warning and no refusal" \
  "$(case "$RA_AP10B_OUT" in
       *"generated-artifact preflight"*|*"launching no shard"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "a clean real preflight was reported as inconclusive or refused; output: $(printf '%s' "$RA_AP10B_OUT" | tr '\n' '|')"
# AP10c/AP10d — the STANDALONE `--preflight` route (issue #1288) against the same REAL
# default preflight, mirroring AP10a/AP10b. The `parallel-suite-runner` module drives every
# `--preflight` arm through an injected stub, so the same two surfaces AP10a exists to bind
# for the coordinator were unbound for this route: that an unset DEVFLOW_ARTIFACT_PREFLIGHT
# resolves to the bundled helper on the `--preflight` case at all, and that the cross-file
# verdict contract holds there. The route runs no shard, so no dispatcher is planted — a
# launched shard would itself be a failure, and is asserted against.
RA_AP10C_OUT="$( cd "$RA_AP8" && bash lib/test/run-parallel.sh --preflight 2>&1 )"; RA_AP10C_RC=$?
_ra_ok "#1288 AP10c --preflight refuses (non-zero) on real drift with the DEFAULT preflight" \
  "$([ "$RA_AP10C_RC" -ne 0 ] && printf yes || printf no)" \
  "--preflight exited 0 on a drifted tree; output: $(printf '%s' "$RA_AP10C_OUT" | tr '\n' '|')"
_ra_ok "#1288 AP10c --preflight refuses by name" \
  "$(case "$RA_AP10C_OUT" in *"launching no shard"*) printf yes ;; *) printf no ;; esac)" \
  "the refusal message is absent; output: $(printf '%s' "$RA_AP10C_OUT" | tr '\n' '|')"
# The real helper's own row line: this is what proves the DEFAULT resolved to the bundled
# helper on the `--preflight` case rather than to nothing (an empty default warns, proceeds,
# and prints no row line at all).
_ra_ok "#1288 AP10c the echoed report is the REAL helper's row output, not a stub's" \
  "$(case "$RA_AP10C_OUT" in *"[plugin-identity-regions] DRIFT"*) printf yes ;; *) printf no ;; esac)" \
  "--preflight printed no real preflight row line, so the default binding was not exercised"
_ra_ok "#1288 AP10c --preflight never treated the real drift as inconclusive" \
  "$(case "$RA_AP10C_OUT" in *"preflight was inconclusive"*) printf no ;; *) printf yes ;; esac)" \
  "real drift took the fail-OPEN arm; output: $(printf '%s' "$RA_AP10C_OUT" | tr '\n' '|')"
_ra_ok "#1288 AP10c --preflight launches NO shard on real drift" \
  "$(case "$RA_AP10C_OUT" in *"launched shard"*) printf no ;; *) printf yes ;; esac)" \
  "a shard was launched by the standalone route; output: $(printf '%s' "$RA_AP10C_OUT" | tr '\n' '|')"

# AP10d — the reconciled counterpart (the positive control on the same fixture shape), so
# AP10c's refusal is attributable to the planted drift rather than to `--preflight` refusing
# on every tree. Reuses AP10b's already-reconciled fixture; its planted dispatcher is
# irrelevant here because this route exits before the shard population is derived.
RA_AP10D_OUT="$( cd "$RA_AP10B" && bash lib/test/run-parallel.sh --preflight 2>&1 )"; RA_AP10D_RC=$?
_ra_same "#1288 AP10d --preflight on a reconciled tree with the DEFAULT preflight exits 0" \
  "0" "$RA_AP10D_RC" "output: $(printf '%s' "$RA_AP10D_OUT" | tr '\n' '|')"
_ra_ok "#1288 AP10d --preflight on a reconciled tree emits no warning and no refusal" \
  "$(case "$RA_AP10D_OUT" in
       *"generated-artifact preflight"*|*"launching no shard"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "a clean real preflight was reported as inconclusive or refused; output: $(printf '%s' "$RA_AP10D_OUT" | tr '\n' '|')"
_ra_ok "#1288 AP10d --preflight on a reconciled tree launches no shard and claims no aggregate" \
  "$(case "$RA_AP10D_OUT" in *"launched shard"*|*passed,*) printf no ;; *) printf yes ;; esac)" \
  "the standalone route produced shard or aggregate output; output: $(printf '%s' "$RA_AP10D_OUT" | tr '\n' '|')"

_ra_live_unchanged "#1244 AP10 live manifest byte-unchanged after the coordinator integration arms"

# ── AP11 — an exit OUTSIDE the row's declared `exits` set ────────────────────
# `run_preflight_row` compares the observed exit against the row's declared `exits` BEFORE any
# clean / positive-marker / infra-marker / traceback classification, and routes an out-of-set
# exit to UNCHECKABLE. Every AP arm above drives an IN-SET exit (0 or 1), so this was the one
# classification branch nothing reached — and it is the most expensive one to get wrong in the
# wrong direction: it is fail-OPEN by contract, so miswiring it to return drift would make the
# coordinator fail CLOSED and refuse the whole suite over a result the preflight never
# established (the "unknown is not zero" collapse, at suite scale).
#
# The row is `env-freeze-advisory-region`, whose registry entry deliberately leaves 2 outside
# its declared set so its generator's own INPUT failures land on this branch; the stub below
# fixes the exit at 3 so AP11a measures the classification rather than any generator's
# behavior.
#
# The declared set is read from the FIXTURE's own registry rather than transcribed here: the
# controls below have to establish that a probe's exit really is outside the set
# `run_preflight_row` compares against, and a hardcoded `0 1` would go on asserting that after
# a registry edit widened the set — leaving these arms silently measuring the in-set path.
_ra_declared_exits() {  # <root> <row-name> — space-separated declared exit codes
  python3 - "$1" "$2" <<'RA_EXITS_EOF'
import importlib.util, sys

spec = importlib.util.spec_from_file_location(
    "ra_registry", sys.argv[1] + "/lib/test/regenerate-artifacts.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(" ".join(str(c) for row in mod.ROWS if row["name"] == sys.argv[2] for c in row["exits"]))
RA_EXITS_EOF
}
# "yes" when <rc> is absent from the space-separated <declared-set>. Spelled once so both
# sub-arms ask the question identically.
_ra_rc_out_of_set() {  # <declared-set> <rc>
  local _code
  # An unreadable registry yields an EMPTY set, which would make the loop below vacuous and
  # report "out of set" for every rc — this control failing open on exactly the broken tree it
  # exists to catch. Report it unestablished so the caller's assertion goes RED instead.
  case "$1" in '') printf 'unestablished'; return 0 ;; esac
  for _code in $1; do
    if [ "$_code" = "$2" ]; then printf no; return 0; fi
  done
  printf yes
}

# AP11a — out-of-set exit, target PRESENT: UNCHECKABLE, and no absent-target sub-clause.
RA_AP11A="$_ra_tmp_root/ap11a"; _ra_fixture "$RA_AP11A"
cat > "$RA_AP11A/lib/generate-env-freeze-advisory.py" <<'PY'
#!/usr/bin/env python3
raise SystemExit(3)
PY
chmod 755 "$RA_AP11A/lib/generate-env-freeze-advisory.py"
RA_AP11A_EXITS="$(_ra_declared_exits "$RA_AP11A" env-freeze-advisory-region)"
# Positive control, in four parts, because this arm is selected by the exit CODE alone and a
# stub that missed the shape would land on a neighbouring branch with every assertion below
# still green: (1) the declared set was actually read, (2) the stub really exits 3, (3) 3
# really is outside that set, and (4) the stub prints no traceback — otherwise the UNCHECKABLE
# verdict could be coming from the universal traceback marker AP6/AP7 already cover.
_ra_ok "#1244 AP11a the row's declared exit set is established (the out-of-set control is live)" \
  "$([ -n "$RA_AP11A_EXITS" ] && printf yes || printf no)" \
  "the declared exits could not be read from the fixture registry, so the control below would be vacuous"
RA_AP11A_PROBE="$( cd "$RA_AP11A" && python3 lib/generate-env-freeze-advisory.py --check 2>&1 )"
RA_AP11A_PRC=$?
assert_eq "#1244 AP11a the stubbed generator really exits 3" "3" "$RA_AP11A_PRC"
_ra_ok "#1244 AP11a the stub's exit really is OUTSIDE the row's declared set" \
  "$(_ra_rc_out_of_set "$RA_AP11A_EXITS" "$RA_AP11A_PRC")" \
  "exit $RA_AP11A_PRC is inside the declared set ($RA_AP11A_EXITS), so the in-set path is what would be measured"
_ra_ok "#1244 AP11a the stub prints no traceback (so the out-of-set branch, not the traceback marker, decides)" \
  "$(case "$RA_AP11A_PROBE" in *"Traceback (most recent call last)"*) printf no ;; *) printf yes ;; esac)" \
  "the stub emitted a traceback, so this arm would measure the universal traceback marker instead"
_ra_ok "#1244 AP11a the row's target is PRESENT (so the absent-target sub-clause must not render)" \
  "$([ -f "$RA_AP11A/lib/generate-env-freeze-advisory.py" ] && printf yes || printf no)" \
  "the generator is missing, so this arm is AP11c's absent-target case rather than the present-target one"
RA_AP11A_MAN_BEFORE="$(cat "$RA_AP11A/scripts/devflow-cloud-writer-contract.json")"
RA_AP11A_REGION_BEFORE="$(cat "$RA_AP11A/docs/internal/cloud-setup.md")"
_ra_preflight "$RA_AP11A"
# Exit 2 is the coordinator's fail-OPEN signal; exit 1 would be the refusal. AP11b drives that
# consequence end to end.
assert_eq "#1244 AP11a an out-of-set exit exits 2 (UNCHECKABLE, the coordinator's fail-open signal)" \
  "2" "$(_ra_prc "$RA_AP11A")"
_ra_has_file "#1244 AP11a the out-of-set row is reported UNCHECKABLE by name" \
  "$RA_AP11A/.rap.out" "[env-freeze-advisory-region] UNCHECKABLE"
# The row name and exit code alone do not discriminate — a row routed here by any other arm
# would satisfy them — so pin the diagnostic only this branch can emit.
_ra_has_file "#1244 AP11a the diagnostic names the out-of-set exit as the reason" \
  "$RA_AP11A/.rap.out" "outside its declared set"
_ra_has_file "#1244 AP11a the exit-2 summary the coordinator reads is printed" \
  "$RA_AP11A/.rap.out" "could not check at least one eligible artifact"
_ra_has_file "#1244 AP11a the machine uncheckable verdict is emitted" \
  "$RA_AP11A/.rap.out" "regenerate-artifacts: preflight-verdict: uncheckable"
RA_AP11A_OUT="$(cat "$RA_AP11A/.rap.out")"
_ra_ok "#1244 AP11a an out-of-set exit is never reported as drift" \
  "$(case "$RA_AP11A_OUT" in
       *"preflight-verdict: drift"*|*"preflight detected drift"*|*"[env-freeze-advisory-region] DRIFT"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "an unestablished result was classified as drift, which fails CLOSED and blocks the whole suite"
_ra_ok "#1244 AP11a the absent-target sub-clause does NOT render while the target exists" \
  "$(case "$RA_AP11A_OUT" in *"(target absent:"*) printf no ;; *) printf yes ;; esac)" \
  "the sub-clause rendered for a target that is present, so it discriminates nothing in AP11c"
_ra_same "#1244 AP11a preflight writes nothing on the out-of-set arm (manifest)" \
  "$RA_AP11A_MAN_BEFORE" "$(cat "$RA_AP11A/scripts/devflow-cloud-writer-contract.json")" \
  "the read-only preflight mutated the manifest on the out-of-set arm"
_ra_same "#1244 AP11a preflight writes nothing on the out-of-set arm (the row's own artifact)" \
  "$RA_AP11A_REGION_BEFORE" "$(cat "$RA_AP11A/docs/internal/cloud-setup.md")" \
  "the read-only preflight rewrote the advisory region of the row it could not check"
_ra_live_unchanged "#1244 AP11a live manifest byte-unchanged after the out-of-set preflight"

# AP11b — the coordinator's response to that same tree, end to end with NO
# DEVFLOW_ARTIFACT_PREFLIGHT override, so the REAL default preflight is what it reads. This is
# the limb the fail-open contract is actually about: an unestablished row must warn and launch,
# never refuse. AP10a proves this same coordinator DOES refuse on real drift, so a green result
# here is attributable to the classification rather than to a coordinator that never refuses.
_ra_plant_dispatcher "$RA_AP11A"
RA_AP11B_OUT="$( cd "$RA_AP11A" && DEVFLOW_SHARD_DISPATCHER="$RA_AP11A/ra-dispatch.sh" \
  bash lib/test/run-parallel.sh 2>&1 )"; RA_AP11B_RC=$?
_ra_same "#1244 AP11b the coordinator proceeds (exit 0) despite the unestablished row" \
  "0" "$RA_AP11B_RC" "output: $(printf '%s' "$RA_AP11B_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP11b the coordinator still launches its shard" \
  "$(case "$RA_AP11B_OUT" in *"launched shard alpha"*) printf yes ;; *) printf no ;; esac)" \
  "no shard launched on an unestablished preflight; output: $(printf '%s' "$RA_AP11B_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP11b the coordinator warns that the preflight was inconclusive, naming its exit" \
  "$(case "$RA_AP11B_OUT" in *"preflight was inconclusive (exit 2, no drift verdict)"*) printf yes ;; *) printf no ;; esac)" \
  "the fail-open warning is absent or misreports the exit, so the operator is not told the check never ran; output: $(printf '%s' "$RA_AP11B_OUT" | tr '\n' '|')"
_ra_ok "#1244 AP11b the coordinator never refuses over the unestablished row" \
  "$(case "$RA_AP11B_OUT" in *"launching no shard"*) printf no ;; *) printf yes ;; esac)" \
  "the coordinator refused the whole suite over a result the preflight never established; output: $(printf '%s' "$RA_AP11B_OUT" | tr '\n' '|')"

# AP11c — the `(target absent: …)` sub-clause. `run_preflight_row` derives the target from the
# row's own preflight argv (its first non-flag argument) and appends the sub-clause only when
# that path is missing from the tree — the renamed-or-deleted-generator case, the one shape
# where "outside its declared set" alone would send the reader hunting for a bug inside a
# generator that is not there. Deleting the generator is also HOW the out-of-set exit arises
# here: python3 itself refuses to open the file, so the exit code is not under this test's
# control, which is why the control below establishes it against the registry rather than
# assuming a value.
RA_AP11C="$_ra_tmp_root/ap11c"; _ra_fixture "$RA_AP11C"
rm -f "$RA_AP11C/lib/generate-env-freeze-advisory.py"
_ra_ok "#1244 AP11c the row's target really is absent" \
  "$([ -e "$RA_AP11C/lib/generate-env-freeze-advisory.py" ] && printf no || printf yes)" \
  "the generator is still present, so the sub-clause under test cannot render"
RA_AP11C_EXITS="$(_ra_declared_exits "$RA_AP11C" env-freeze-advisory-region)"
_ra_ok "#1244 AP11c the row's declared exit set is established (the out-of-set control is live)" \
  "$([ -n "$RA_AP11C_EXITS" ] && printf yes || printf no)" \
  "the declared exits could not be read from the fixture registry, so the control below would be vacuous"
RA_AP11C_PROBE_RC=0
( cd "$RA_AP11C" && python3 lib/generate-env-freeze-advisory.py --check ) >/dev/null 2>&1
RA_AP11C_PROBE_RC=$?
_ra_ok "#1244 AP11c running the absent generator really exits OUTSIDE the declared set" \
  "$(_ra_rc_out_of_set "$RA_AP11C_EXITS" "$RA_AP11C_PROBE_RC")" \
  "exit $RA_AP11C_PROBE_RC is inside the declared set ($RA_AP11C_EXITS), so the out-of-set branch is not the one under test"
RA_AP11C_MAN_BEFORE="$(cat "$RA_AP11C/scripts/devflow-cloud-writer-contract.json")"
RA_AP11C_REGION_BEFORE="$(cat "$RA_AP11C/docs/internal/cloud-setup.md")"
_ra_preflight "$RA_AP11C"
assert_eq "#1244 AP11c an absent target also exits 2 (UNCHECKABLE)" "2" "$(_ra_prc "$RA_AP11C")"
_ra_has_file "#1244 AP11c the absent-target row is reported UNCHECKABLE by name" \
  "$RA_AP11C/.rap.out" "[env-freeze-advisory-region] UNCHECKABLE"
_ra_has_file "#1244 AP11c the sub-clause renders and names the missing target" \
  "$RA_AP11C/.rap.out" "(target absent: lib/generate-env-freeze-advisory.py)"
_ra_has_file "#1244 AP11c the absent-target diagnostic still names the out-of-set exit" \
  "$RA_AP11C/.rap.out" "outside its declared set"
_ra_ok "#1244 AP11c an absent target is never reported as drift" \
  "$(case "$(cat "$RA_AP11C/.rap.out")" in
       *"preflight-verdict: drift"*|*"preflight detected drift"*|*"[env-freeze-advisory-region] DRIFT"*) printf no ;;
       *) printf yes ;;
     esac)" \
  "a missing generator was reported as reconcilable drift, aiming the remedy at a script that is not there"
_ra_same "#1244 AP11c preflight writes nothing on the absent-target arm (manifest)" \
  "$RA_AP11C_MAN_BEFORE" "$(cat "$RA_AP11C/scripts/devflow-cloud-writer-contract.json")" \
  "the read-only preflight mutated the manifest on the absent-target arm"
_ra_same "#1244 AP11c preflight writes nothing on the absent-target arm (the row's own artifact)" \
  "$RA_AP11C_REGION_BEFORE" "$(cat "$RA_AP11C/docs/internal/cloud-setup.md")" \
  "the read-only preflight rewrote the advisory region while its generator was absent"
_ra_live_unchanged "#1244 AP11c live manifest byte-unchanged after the absent-target preflight"

# The row integration itself has two non-clean states. A measured raise is a mechanical
# reconciliation that changes the registry and `run.sh`; a measured decrease is a non-writing
# judgment. The fake runner above supplies the actual summary boundary while these fixtures
# exercise the batched row's snapshots, exit mapping, and report.
RA_1055_RAISE="$_ra_tmp_root/issue-1055-raise"; _ra_fixture "$RA_1055_RAISE"
RA_1055_RAISE_REG_BEFORE="$(cat "$RA_1055_RAISE/scripts/workflow-flight-recorder-registry.json")"
RA_1055_RAISE_RUN_BEFORE="$(cat "$RA_1055_RAISE/lib/test/run.sh")"
DEVFLOW_FLOOR_TEST_DELTA=1 _ra_run "$RA_1055_RAISE"
assert_eq "#1055 a measured floor raise makes the batched pass action-required" \
  "1" "$(_ra_rc "$RA_1055_RAISE")"
_ra_has "#1055 the batched row reports its measured reconciliation" "$RA_1055_RAISE" \
  "[exact-module-floors] RECONCILED"
_ra_ok "#1055 the measured raise updates the registry" \
  "$([ "$RA_1055_RAISE_REG_BEFORE" != "$(cat "$RA_1055_RAISE/scripts/workflow-flight-recorder-registry.json")" ] && printf yes)" \
  "the registry did not change"
_ra_ok "#1055 the measured raise updates the coupled run.sh sites" \
  "$([ "$RA_1055_RAISE_RUN_BEFORE" != "$(cat "$RA_1055_RAISE/lib/test/run.sh")" ] && printf yes)" \
  "run.sh did not change"

RA_1055_LOWER="$_ra_tmp_root/issue-1055-lower"; _ra_fixture "$RA_1055_LOWER"
RA_1055_LOWER_REG_BEFORE="$(cat "$RA_1055_LOWER/scripts/workflow-flight-recorder-registry.json")"
RA_1055_LOWER_RUN_BEFORE="$(cat "$RA_1055_LOWER/lib/test/run.sh")"
DEVFLOW_FLOOR_TEST_DELTA=-1 _ra_run "$RA_1055_LOWER"
assert_eq "#1055 a measured floor decrease makes the batched pass action-required" \
  "1" "$(_ra_rc "$RA_1055_LOWER")"
_ra_has "#1055 the batched row reports the decrease as judgment" "$RA_1055_LOWER" \
  "[exact-module-floors] JUDGMENT"
_ra_same "#1055 a refused decrease leaves the registry byte-unchanged" \
  "$RA_1055_LOWER_REG_BEFORE" \
  "$(cat "$RA_1055_LOWER/scripts/workflow-flight-recorder-registry.json")" \
  "the registry changed on a decrease"
_ra_same "#1055 a refused decrease leaves run.sh byte-unchanged" \
  "$RA_1055_LOWER_RUN_BEFORE" "$(cat "$RA_1055_LOWER/lib/test/run.sh")" \
  "run.sh changed on a decrease"

# ── The exact-module-floors row is OPT-IN, and its omission is on the record ──
# The default pass must not run the one row whose check runs the real focused module
# runners. It is reported as not measured rather than silently dropped: a pass that says
# nothing about a row it did not run is indistinguishable from one that found it clean.
RA_OPTIN="$_ra_tmp_root/optin-default"; _ra_fixture "$RA_OPTIN"
RA_OPTIN_REG_BEFORE="$(cat "$RA_OPTIN/scripts/workflow-flight-recorder-registry.json")"
RA_OPTIN_RUN_BEFORE="$(cat "$RA_OPTIN/lib/test/run.sh")"
DEVFLOW_FLOOR_TEST_DELTA=1 _ra_run_default "$RA_OPTIN"
assert_eq "#optin the default pass exits 0 over a floor delta it did not measure" \
  "0" "$(_ra_rc "$RA_OPTIN")"
_ra_has "#optin the default pass records the unmeasured row and names the flag" \
  "$RA_OPTIN" "[exact-module-floors] not measured -- pass --with-floors"
_ra_same "#optin the default pass leaves the registry byte-unchanged" \
  "$RA_OPTIN_REG_BEFORE" \
  "$(cat "$RA_OPTIN/scripts/workflow-flight-recorder-registry.json")" \
  "the default pass wrote a floor it never measured"
_ra_same "#optin the default pass leaves the coupled run.sh byte-unchanged" \
  "$RA_OPTIN_RUN_BEFORE" "$(cat "$RA_OPTIN/lib/test/run.sh")" \
  "the default pass wrote a coupled floor site it never measured"

# The paired positive control on the SAME fixture: without it, a `--with-floors` that had
# become a no-op would satisfy every arm above. The floor runner here is the fixture stub
# driven by DEVFLOW_FLOOR_TEST_DELTA, not the real modules.
RA_OPTIN_ON="$_ra_tmp_root/optin-with-floors"; _ra_fixture "$RA_OPTIN_ON"
RA_OPTIN_ON_REG_BEFORE="$(cat "$RA_OPTIN_ON/scripts/workflow-flight-recorder-registry.json")"
DEVFLOW_FLOOR_TEST_DELTA=1 _ra_run "$RA_OPTIN_ON"
_ra_has "#optin --with-floors runs the measurement the default pass reported unmeasured" \
  "$RA_OPTIN_ON" "[exact-module-floors] RECONCILED"
assert_eq "#optin the measuring pass is action-required over the same floor delta" \
  "1" "$(_ra_rc "$RA_OPTIN_ON")"
_ra_ok "#optin --with-floors raises the measured floor in the registry" \
  "$([ "$RA_OPTIN_ON_REG_BEFORE" != "$(cat "$RA_OPTIN_ON/scripts/workflow-flight-recorder-registry.json")" ] && printf yes)" \
  "the measuring pass left the registry byte-unchanged"

# ── The ordering guard: never measure a tree this pass already reported red ──
# The coverage-map drift below makes an EARLIER row emit an exit-1-forcing judgment item,
# so the opt-in row is skipped even under the flag — measuring a tree that is about to
# change costs minutes and answers a question about the wrong tree.
RA_OPTIN_RED="$_ra_tmp_root/optin-after-red"; _ra_fixture "$RA_OPTIN_RED"
printf '# scratch\n' > "$RA_OPTIN_RED/lib/uncovered-helper-optin.sh"
( cd "$RA_OPTIN_RED" && git add -A && git commit -q -m "plant coverage drift" ) >/dev/null 2>&1
_ra_reconcile "$RA_OPTIN_RED"
RA_OPTIN_RED_REG_BEFORE="$(cat "$RA_OPTIN_RED/scripts/workflow-flight-recorder-registry.json")"
DEVFLOW_FLOOR_TEST_DELTA=1 _ra_run "$RA_OPTIN_RED"
_ra_has "#optin the ordering guard's positive control: an earlier row reported red" \
  "$RA_OPTIN_RED" "[coverage-map-ratchet] JUDGMENT"
assert_eq "#optin a pass whose earlier row went red is still action-required" \
  "1" "$(_ra_rc "$RA_OPTIN_RED")"
_ra_has "#optin --with-floors skips the measurement on an already-red tree" \
  "$RA_OPTIN_RED" "[exact-module-floors] not measured -- an earlier row already reported"
_ra_same "#optin the skipped measurement writes no floor on an already-red tree" \
  "$RA_OPTIN_RED_REG_BEFORE" \
  "$(cat "$RA_OPTIN_RED/scripts/workflow-flight-recorder-registry.json")" \
  "the skipped measurement wrote a floor anyway"

# The guard's SECOND disjunct, independent of the judgment-item one above: an earlier row
# that hit the INFRASTRUCTURE state also makes this tree unmeasurable. Stripping .git makes
# coverage-map-ratchet report an input failure (the A5g technique) with no judgment item
# raised, so a regression narrowing the guard to `forces_one` alone fails only here.
RA_OPTIN_INFRA="$_ra_tmp_root/optin-after-infrastructure"; _ra_fixture "$RA_OPTIN_INFRA"
rm -rf "$RA_OPTIN_INFRA/.git"
RA_OPTIN_INFRA_REG_BEFORE="$(cat "$RA_OPTIN_INFRA/scripts/workflow-flight-recorder-registry.json")"
DEVFLOW_FLOOR_TEST_DELTA=1 _ra_run "$RA_OPTIN_INFRA"
_ra_has "#optin the infrastructure disjunct's positive control: an earlier row went INFRASTRUCTURE" \
  "$RA_OPTIN_INFRA" "[coverage-map-ratchet] INFRASTRUCTURE"
assert_eq "#optin a pass whose earlier row hit INFRASTRUCTURE exits 2" \
  "2" "$(_ra_rc "$RA_OPTIN_INFRA")"
_ra_has "#optin --with-floors skips the measurement after an INFRASTRUCTURE row" \
  "$RA_OPTIN_INFRA" "[exact-module-floors] not measured -- an earlier row already reported"
_ra_same "#optin the skipped measurement writes no floor after an INFRASTRUCTURE row" \
  "$RA_OPTIN_INFRA_REG_BEFORE" \
  "$(cat "$RA_OPTIN_INFRA/scripts/workflow-flight-recorder-registry.json")" \
  "the skipped measurement wrote a floor anyway"

RA_1055_PARTIAL="$_ra_tmp_root/issue-1055-partial"; _ra_fixture "$RA_1055_PARTIAL"
cat > "$RA_1055_PARTIAL/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
from pathlib import Path

path = Path("scripts/workflow-flight-recorder-registry.json")
path.write_bytes(path.read_bytes() + b"\n")
PY
chmod 755 "$RA_1055_PARTIAL/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1055_PARTIAL"
assert_eq "#1055 a partial coupled raise is infrastructure, never reconciled" \
  "2" "$(_ra_rc "$RA_1055_PARTIAL")"
_ra_has "#1055 a partial coupled raise names the incomplete write set" \
  "$RA_1055_PARTIAL" "changed only a subset of its declared outputs"

# The sibling of the partial case, and the one the classifier's own comment calls the
# dangerous shape: a clean exit that mutated EVERY declared output but announced no
# raise. Without the marker requirement this reads as a successful reconciliation and
# the mutated coupled floors are committed.
RA_1055_SILENT="$_ra_tmp_root/issue-1055-silent-write"; _ra_fixture "$RA_1055_SILENT"
cat > "$RA_1055_SILENT/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
from pathlib import Path

for target in ("scripts/workflow-flight-recorder-registry.json", "lib/test/run.sh"):
    path = Path(target)
    path.write_bytes(path.read_bytes() + b"\n")
PY
chmod 755 "$RA_1055_SILENT/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1055_SILENT"
assert_eq "#1055 a silent full write is infrastructure, never reconciled" \
  "2" "$(_ra_rc "$RA_1055_SILENT")"
_ra_has "#1055 a silent full write is reported as unattributable" \
  "$RA_1055_SILENT" "without announcing a raise"

# ── #1498 — the three unreached _monotonic_outcome classes and the clean text ──
# Each plants a stand-in reconcile-module-floors.py (the RA_1055_PARTIAL/SILENT shape,
# with RA_FLOOR_RUNNER still exported as the stub floor runner) so the batched row's
# exact-module-floors classifier is driven to one specific outcome without running the
# eleven real module measurements. Each pins the class's own distinguishing text AND the
# batched pass's resulting exit code (2 for the three INFRASTRUCTURE classes, 0 for clean).

# (1) A declared coupled output left absent after the run → INFRASTRUCTURE (exit 2). The
# stand-in exits 0 (inside the row's `clean`/`exits`) but removes one declared output, so
# the after-snapshot sees it absent — the branch checked before the clean/changed logic.
RA_1498_ABSENT="$_ra_tmp_root/issue-1498-absent-output"; _ra_fixture "$RA_1498_ABSENT"
cat > "$RA_1498_ABSENT/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
from pathlib import Path

# Remove one declared coupled output so the row's after-snapshot reads it as absent.
Path("lib/test/run.sh").unlink()
PY
chmod 755 "$RA_1498_ABSENT/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1498_ABSENT"
assert_eq "#1498 a declared output left absent is infrastructure (exit 2)" \
  "2" "$(_ra_rc "$RA_1498_ABSENT")"
_ra_has "#1498 the row reports the declared output(s) left absent" \
  "$RA_1498_ABSENT" "left declared output(s) absent"

# (2) A non-clean exit that nonetheless mutated a declared output → INFRASTRUCTURE (exit
# 2), the classifier's most alarming state. The stand-in exits 1 (inside `exits`, outside
# `clean`) after appending a byte to one coupled output.
RA_1498_REFUSAL="$_ra_tmp_root/issue-1498-refusal-mutated"; _ra_fixture "$RA_1498_REFUSAL"
cat > "$RA_1498_REFUSAL/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
import sys
from pathlib import Path

path = Path("scripts/workflow-flight-recorder-registry.json")
path.write_bytes(path.read_bytes() + b"\n")
sys.exit(1)
PY
chmod 755 "$RA_1498_REFUSAL/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1498_REFUSAL"
assert_eq "#1498 a non-clean run that mutated declared outputs is infrastructure (exit 2)" \
  "2" "$(_ra_rc "$RA_1498_REFUSAL")"
_ra_has "#1498 the row reports a mutation despite the refusal contract" \
  "$RA_1498_REFUSAL" "despite its refusal contract"

# (3) A non-clean exit that wrote nothing and announced no recognized refusal marker →
# INFRASTRUCTURE (exit 2). The stand-in exits 1, changes nothing, prints nothing.
RA_1498_NOMARKER="$_ra_tmp_root/issue-1498-no-marker"; _ra_fixture "$RA_1498_NOMARKER"
cat > "$RA_1498_NOMARKER/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
import sys

sys.exit(1)
PY
chmod 755 "$RA_1498_NOMARKER/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1498_NOMARKER"
assert_eq "#1498 a non-clean run with no refusal marker is infrastructure (exit 2)" \
  "2" "$(_ra_rc "$RA_1498_NOMARKER")"
_ra_has "#1498 the row reports the absent non-writing refusal marker" \
  "$RA_1498_NOMARKER" "recognized non-writing refusal marker"

# (3b) #2121 — the install-state mechanical row's exit-1 arm: a traceback-class exit printing
# no `cloud-writer-contract:` marker routes to INFRASTRUCTURE (exit 2), never a judgment item.
RA_2121_IS_EXIT1="$_ra_tmp_root/issue-2121-install-state-exit1"; _ra_fixture "$RA_2121_IS_EXIT1"
cat > "$RA_2121_IS_EXIT1/lib/generate-install-state.py" <<'PY'
#!/usr/bin/env python3
import sys

sys.exit(1)
PY
_ra_run "$RA_2121_IS_EXIT1"
assert_eq "#2121 an install-state exit 1 with no marker is infrastructure (exit 2)" \
  "2" "$(_ra_rc "$RA_2121_IS_EXIT1")"
_ra_has "#2121 the install-state row reports the absent marker as infrastructure" \
  "$RA_2121_IS_EXIT1" "[install-state] INFRASTRUCTURE exited 1 with no"

# (4) AC4 — the clean class's OWN text. The stand-in exits 0 and changes nothing, so the
# monotonic classifier reports every measured tally matching both floors and the batched
# pass exits 0. (The A1 prefix loop above still covers the live tree; this pins the text.)
RA_1498_CLEAN="$_ra_tmp_root/issue-1498-clean-text"; _ra_fixture "$RA_1498_CLEAN"
cat > "$RA_1498_CLEAN/lib/test/reconcile-module-floors.py" <<'PY'
#!/usr/bin/env python3
# Clean: exit 0, change nothing.
PY
chmod 755 "$RA_1498_CLEAN/lib/test/reconcile-module-floors.py"
_ra_run "$RA_1498_CLEAN"
assert_eq "#1498 a clean measured tally exits 0" \
  "0" "$(_ra_rc "$RA_1498_CLEAN")"
_ra_has "#1498 the clean class pins its own text" \
  "$RA_1498_CLEAN" "clean — every measured tally matches both floors"

RA_A5P="$_ra_tmp_root/a5p"; _ra_fixture "$RA_A5P"
# A judgment item AND an infrastructure failure in one run: exit 2 takes precedence.
# Plant coverage-map drift (an uncovered helper) for the JUDGMENT half, and remove the
# capability generator for the INFRASTRUCTURE half.
printf '# scratch\n' > "$RA_A5P/lib/uncovered-helper-a5p.sh"
( cd "$RA_A5P" && git add -A && git commit -q -m "plant coverage drift" ) >/dev/null 2>&1
_ra_reconcile "$RA_A5P"
rm -f "$RA_A5P/lib/generate-capability-profiles.py"
_ra_run "$RA_A5P"
# Positive control for the precedence claim (guard-class shape 3). The rc assertion
# below passes on the infrastructure condition ALONE — `main()` returns 2 whenever
# `infrastructure` is set, regardless of `forces_one` — so without establishing that a
# judgment item was ALSO present, the arm measures a plain exit-2 run and would stay
# green if the coverage row silently stopped reporting drift for this edit shape. Pin the
# judgment row's own attributed signal first, so precedence is what is actually tested.
_ra_has "#619 A5p the concurrent judgment item is present (precedence positive control)" \
  "$RA_A5P" "[coverage-map-ratchet] JUDGMENT"
assert_eq "#619 A5 exit 2 takes precedence over a concurrent judgment item" "2" "$(_ra_rc "$RA_A5P")"
_ra_live_unchanged "#619 A5p live manifest byte-unchanged after the precedence run"

# ── A5s — an argparse USAGE error exits 2 and runs no row ────────────────────
# The helper's exit-contract docstring makes a positive claim about this boundary
# (rc 2, before any row runs, with no row report). An untested documented claim in a
# file this module content-pins elsewhere is a documented-falsehood risk.
RA_A5S="$_ra_tmp_root/a5s"; _ra_fixture "$RA_A5S"
python3 "$RA_HELPER" --repo-root "$RA_A5S" --no-such-flag \
  >"$RA_A5S/.ra.out" 2>&1; printf '%s\n' "$?" >"$RA_A5S/.ra.rc"
assert_eq "#619 A5s an unknown flag exits 2" "2" "$(_ra_rc "$RA_A5S")"
case "$(cat "$RA_A5S/.ra.out")" in
  *"regenerate-artifacts: "*)
    assert_eq "#619 A5s the usage error emits no row report" yes \
      "no(a row report accompanied the usage error)" ;;
  *) assert_eq "#619 A5s the usage error emits no row report" yes yes ;;
esac
_ra_live_unchanged "#619 A5s live manifest byte-unchanged after the usage-error run"

# ── A5b — a launched command exiting OUTSIDE its declared set is exit 2 ──────
RA_A5B="$_ra_tmp_root/a5b"; _ra_fixture "$RA_A5B"
printf 'import sys\nsys.exit(3)\n' > "$RA_A5B/lib/test/coverage_map_guard.py"
_ra_run "$RA_A5B"
assert_eq "#619 A5b an out-of-declared-set exit routes to exit 2, never clean" "2" "$(_ra_rc "$RA_A5B")"
_ra_has "#619 A5b the out-of-set exit names the declared set" "$RA_A5B" "outside its declared set"
_ra_live_unchanged "#619 A5b live manifest byte-unchanged after the out-of-set run"

# ── A5c — the OSError LAUNCH-FAILURE branch (distinct from A5's declared-set arm) ─
# A5 exercises an absent *script* (the interpreter exits 2, caught by the declared-set
# check). Nothing reached the helper's `except OSError` arm, so a regression that
# swallowed a launch failure — or returned "clean" from it — would have shipped green.
# A nonexistent --repo-root makes subprocess.run itself raise (the cwd does not exist),
# which is the only shape that reaches that branch.
RA_A5C="$_ra_tmp_root/a5c-does-not-exist"
python3 "$RA_HELPER" --repo-root "$RA_A5C" >"$_ra_tmp_root/a5c.out" 2>&1; printf '%s\n' "$?" >"$_ra_tmp_root/a5c.rc"
assert_eq "#619 A5c an unlaunchable command (nonexistent root) exits 2" "2" "$(cat "$_ra_tmp_root/a5c.rc")"
# Presence, not an exact count: every command row fails to launch under a nonexistent
# root, so the line legitimately appears once per command row — pinning the current
# number would be a mirror-fact that rots the moment a row is added.
devflow_module_pin_present "#619 A5c the launch failure is named as such" \
  'INFRASTRUCTURE the command failed to launch' "$_ra_tmp_root/a5c.out"  # runtime-pin-ok: target is a runtime scratch-root output file, unresolvable by the static meta-guard
_ra_live_unchanged "#619 A5c live manifest byte-unchanged after the launch-failure run"

# ── A5d — the coverage-map row's JUDGMENT arm (its drift path was unexercised) ───
# Every other judgment row had its JUDGMENT line and policy string pinned; this one was
# reachable only via A1 (clean) and A5b (out-of-set), so a typo in its exits/clean tuple
# would have turned every real ratchet failure into a spurious exit 2 unnoticed.
RA_A5D="$_ra_tmp_root/a5d"; _ra_fixture "$RA_A5D"
printf '# scratch\n' > "$RA_A5D/lib/uncovered-helper-619.sh"
( cd "$RA_A5D" && git add -A && git commit -q -m "plant coverage drift" ) >/dev/null 2>&1
_ra_reconcile "$RA_A5D"
_ra_run "$RA_A5D"
_ra_has "#619 A5d planted coverage-map drift raises the ratchet judgment item" "$RA_A5D" \
  "[coverage-map-ratchet] JUDGMENT"
_ra_has "#619 A5d the ratchet item names its governing policy" "$RA_A5D" \
  "add the missing coverage rows per the issue-591 ratchet"
assert_eq "#619 A5d the ratchet judgment item forces exit 1" "1" "$(_ra_rc "$RA_A5D")"
_ra_live_unchanged "#619 A5d live manifest byte-unchanged after the ratchet-drift run"

# ── A5g — a judgment row's INPUT failure routes to INFRASTRUCTURE, not to a judgment ──
# Both judgment generators exit 1 for an unusable input as well as for real drift, so
# without a discriminator an unmeasurable tree is reported as "go edit your coverage
# rows" — telling the agent to fix a measurement that never happened. Stripping .git
# from the fixture makes coverage_map_guard emit its `[input-error]` prefix; the row
# must report INFRASTRUCTURE (exit 2), never a JUDGMENT item (exit 1).
RA_A5G="$_ra_tmp_root/a5g"; _ra_fixture "$RA_A5G"; rm -rf "$RA_A5G/.git"
_ra_run "$RA_A5G"
assert_eq "#619 A5g a judgment row's input failure exits 2, never 1" "2" "$(_ra_rc "$RA_A5G")"
_ra_has "#619 A5g the input failure is attributed to its row as INFRASTRUCTURE" "$RA_A5G" \
  "[coverage-map-ratchet] INFRASTRUCTURE"
_ra_has "#619 A5g the input failure is named as an input failure, not drift" "$RA_A5G" \
  "reporting an input failure, not drift"
_ra_has "#619 A5g the run does NOT tell the agent to resolve a ratchet judgment item" "$RA_A5G" \
  "the artifact was NOT checked"
_ra_live_unchanged "#619 A5g live manifest byte-unchanged after the input-failure run"

# ── A5j — an UNREADABLE coverage-map is infrastructure, not "add the missing rows" ──
# A5g covers the guard's [input-error] (git) path. An absent/malformed coverage-map
# takes a DIFFERENT path ([arm4]/[arm8]) and arm 4 RETURNS before every map-dependent
# arm — so an unreadable map both suppresses every real violation and, unmarked, would
# be reported as a judgment item telling the agent to add rows to the very file the
# guard just said it could not read.
RA_A5J="$_ra_tmp_root/a5j"; _ra_fixture "$RA_A5J"
rm -f "$RA_A5J/lib/test/modules/coverage-map.json"
_ra_run "$RA_A5J"
assert_eq "#619 A5j an unreadable coverage-map exits 2, never 1" "2" "$(_ra_rc "$RA_A5J")"
_ra_has "#619 A5j the unreadable map is matched by its own arm4 marker" "$RA_A5J" \
  "matched '[arm4] '"
_ra_live_unchanged "#619 A5j live manifest byte-unchanged after the unreadable-map run"

# ── A5k — a MALFORMED capability manifest is infrastructure, not "regenerate" ──
# The generator raises GenError and exits 1 for an unreadable/malformed manifest —
# byte-identically to a real token drift. Unmarked, the row would report a judgment
# item telling the agent to regenerate from the very file the generator could not
# parse, and the pass would record `run` for a row that was never checked. This row
# was the only judgment row shipping without infra_markers.
RA_A5K="$_ra_tmp_root/a5k"; _ra_fixture "$RA_A5K"
printf '{ not json at all\n' > "$RA_A5K/lib/capability-profiles.json"
_ra_run "$RA_A5K"
assert_eq "#619 A5k a malformed capability manifest exits 2, never 1" "2" "$(_ra_rc "$RA_A5K")"
_ra_has "#619 A5k the malformed manifest is attributed to its own row" "$RA_A5K" \
  "[capability-profile-literals] INFRASTRUCTURE"
# The RENDERED discriminator, not the bare payload: `manifest malformed JSON:` also
# appears in the row's echoed command output, so pinning it would pass even if
# _marker_hit returned None and the row was classified JUDGMENT. The `matched '...'`
# wording is emitted ONLY by run_row's marker-hit branch.
_ra_has "#619 A5k the malformed manifest is matched by its own marker" "$RA_A5K" \
  "matched 'manifest malformed JSON:'"
_ra_live_unchanged "#619 A5k live manifest byte-unchanged after the malformed-manifest run"

# ── A5f — default_repo_root anchors its probe to THIS checkout, not the process cwd ──
# The helper's one write target is a tracked file, so a root resolved from an unrelated
# repository would regenerate that repository's manifest. Nothing exercised the anchor:
# every other arm passes --repo-root explicitly, so deleting `cwd=str(here)` left all
# assertions green. Run --list with NO --repo-root from inside an unrelated git repo and
# assert the capability row's conflict-path set — derived from the generator's REGIONS
# under the RESOLVED root — is still DevFlow's own workflow literals.
RA_A5F="$_ra_tmp_root/a5f-unrelated"; mkdir -p "$RA_A5F"
( cd "$RA_A5F" && git init -q . && git config user.email a@b.c && git config user.name t \
  && printf 'x\n' > f.txt && git add -A && git commit -q -m unrelated ) >/dev/null 2>&1
if ( cd "$RA_A5F" && python3 "$RA_HELPER" --list ) > "$RA_A5F/list.out" 2>"$RA_A5F/list.err"; then
  assert_eq "#619 A5f --list succeeds from the unrelated repo" yes yes
else
  assert_eq "#619 A5f --list succeeds from the unrelated repo" yes \
    "no(rc!=0; stderr: $(tr '\n' '|' <"$RA_A5F/list.err"))"
fi
assert_eq "#619 A5f --list from an unrelated repo still resolves THIS checkout's root" "1" \
  "$(devflow_module_pin_count 'conflict-path	capability-profile-literals	.github/workflows/devflow-runner.yml' "$RA_A5F/list.out")"
# Deliberately the bare tab-prefixed path: this catches an unrelated-repo file leaking onto
# ANY emitted line (an artifact, conflict-path, or conflict-sibling line, under any row).
assert_eq "#619 A5f the unrelated repo contributes no emitted path" "0" \
  "$(devflow_module_pin_count '	f.txt' "$RA_A5F/list.out")"
_ra_live_unchanged "#619 A5f live manifest byte-unchanged after the unrelated-repo run"

# ── A5o — an UNRESOLVABLE module registry is infrastructure, not "add the rows" ─
# The coverage row's `[arm8] ` marker was declared but unpinned (issue #624): A5j drives
# the sibling `[arm4] ` (coverage-map) leg only. Arm 8 is the registry leg. The fixture
# plants ABSENCE (`rm -f`) rather than an unreadable file, because the guard renders both
# through the same `[arm8] registry unreadable: …` text and absence needs no permission
# bits — the same determinism reason A5m plants malformed JSON. Either way the guard exits
# 1, byte-identically to a real ratchet violation, so without the marker the row would
# report a judgment item telling the agent to add coverage rows keyed on a registry the
# guard could not read.
RA_A5O="$_ra_tmp_root/a5o"; _ra_fixture "$RA_A5O"
rm -f "$RA_A5O/scripts/workflow-flight-recorder-registry.json"
_ra_run "$RA_A5O"
assert_eq "#624 A5o an unreadable module registry exits 2, never 1" "2" "$(_ra_rc "$RA_A5O")"
_ra_has "#624 A5o the unreadable registry is attributed to its own row" "$RA_A5O" \
  "[coverage-map-ratchet] INFRASTRUCTURE"
# The RENDERED discriminator (`matched '…'` is emitted ONLY by run_row's marker-hit
# branch), never the bare payload — which also appears in the row's echoed command output
# and would therefore pass with the marker deleted and the row classified JUDGMENT. Same
# discipline as A5k/A5m.
_ra_has "#624 A5o the unreadable registry is matched by its own arm8 marker" "$RA_A5O" \
  "matched '[arm8] '"
_ra_live_unchanged "#624 A5o live manifest byte-unchanged after the unreadable-registry run"

# ── Behaviorally significant helper-content contracts ──────────────────────
devflow_module_pin_unique "#619 the helper header carries the registration rule" 'A PR that adds a checked-in generated artifact gated by the suite adds a row to this registry in the same PR.' "$RA_HELPER"
assert_eq "#619 the helper is stdlib-only (imports no yaml module)" "0" \
  "$(devflow_module_pin_count 'import yaml' "$RA_HELPER")"
RA_DECLARED_WRITES="$(python3 - "$RA_HELPER" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("regenerate_artifacts", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
paths = set()
for row in module.ROWS:
    writes = row.get("writes", ())
    paths.update((writes,) if isinstance(writes, str) else writes)
print("\n".join(sorted(paths)))
PY
)"
assert_eq "#619 writing rows expose their complete output set through the registry" \
  '.prflow/install-state.json
lib/test/run.sh
scripts/workflow-flight-recorder-registry.json' "$RA_DECLARED_WRITES"

# ════════════════════════════════════════════════════════════════════════════
# #655 — the registry as the merge-conflict oracle
# ════════════════════════════════════════════════════════════════════════════
# A merge conflict in a checked-in generated artifact must be regenerated or its source
# reconciled, never hand-merged: hand-merged bytes match no source of truth, and the row's
# own gate then reports them as drift with a remedy pointed at the wrong file. The registry
# emits the artifact PATHS, the resolution CLASS, and the RECIPE so a conflict rule can key
# on `--list` at runtime and never hardcode a path or a command.
#
# The live `--list` output (captured in A4) as a FILE, because the harness pin API reads a
# path. Every arm below matches through that API rather than a `case` glob: a `case` pattern
# with two `*` wildcards spans LINES in a multi-line string, so `*"conflict-path	"*"	$1"*`
# would match one row's name against another row's path — a false green on exactly the
# coverage property this block calls load-bearing. devflow_module_pin_count is line-scoped
# and count-returning, so neither that cross-row match nor an unanchored suffix
# (`by-hand` matching `by-hand-ish`) survives it.
RA_C_LIST_F="$_ra_tmp_root/c655-live-list.txt"
printf '%s\n' "$RA_LIST" > "$RA_C_LIST_F"

# One fixture root shared by the fail-closed registry mutation arms below. Each arm
# writes a distinct helper copy outside the root and invokes it with --repo-root pointed
# here, so no arm's mutation is visible to another.
RA_C_SHARED="$_ra_tmp_root/c655-shared"; _ra_fixture "$RA_C_SHARED"
RA_C_MUT=0

# ── (a) every registered row emits a conflict-class line with an IN-SET value ────
# Derived from RA_ROW_NAMES (the registry's own roster, already coupled to `--list` by
# A4), so a newly-registered row that forgets its class is caught here rather than
# silently omitted from a hand-maintained list.
for _row in $RA_ROW_NAMES; do
  # Sum the three in-set spellings through the line-scoped counter: exactly one must match.
  # A `case` glob would accept an unanchored suffix (`by-hand-ish`) and, with two wildcards,
  # match across LINES — see the RA_C_LIST_F note above.
  _ra_c_inset=0
  for _cls in regenerate reconcile-source by-hand; do
    _ra_c_inset=$((_ra_c_inset + $(devflow_module_pin_count "conflict-class	$_row	$_cls" "$RA_C_LIST_F")))
  done
  assert_eq "#655 --list emits exactly one in-set conflict-class for: $_row" "1" "$_ra_c_inset"
  # One conflict-recipe line per row, non-empty — the recipe the conflict rule follows.
  case "$(sed -n "s/^conflict-recipe	${_row}	//p" "$RA_C_LIST_F")" in
    '') assert_eq "#655 --list emits a non-empty conflict-recipe for: $_row" yes \
          "no(absent or empty)" ;;
    *)  assert_eq "#655 --list emits a non-empty conflict-recipe for: $_row" yes yes ;;
  esac
done

# ── (b) each class assignment is checked in executable output ───────────────────
_ra_class_is() {  # row expected-class
  assert_eq "#655 conflict-class assignment: $1 -> $2" "1" \
    "$(devflow_module_pin_count "conflict-class	$1	$2" "$RA_C_LIST_F")"
}
_ra_class_is capability-profile-literals reconcile-source
_ra_class_is coverage-map-ratchet        by-hand
# by-hand, not reconcile-source: this row's two declared outputs are hand-authored files
# in which it owns only a single numeric token per exact module, so a conflict in either
# is hand-merged deliberately and the floors re-measured — never blind-regenerated.
_ra_class_is exact-module-floors          by-hand

# ── (c) the conflict-path set covers EVERY known generated artifact ──────────────
# This is the property without which the whole rule is inert: the rule matches a
# conflicted path against these lines, so an artifact absent from the set falls through
# to the hand-merge default — the exact failure the rule exists to prevent. The list is
# the audit's own enumeration of the repo's generated artifacts, deliberately independent
# of the registry (a registry-derived list could only certify its own completeness).
# Row-agnostic on purpose (the audit asks "is this artifact covered", not "by which row"),
# so it counts LINES ending in the path via a tab-anchored suffix strip rather than a
# two-wildcard `case` that could pair one row's name with another row's path.
_ra_conflict_path_covered() {  # artifact-path
  local n
  n="$(sed -n "s/^conflict-path	[^	]*	//p" "$RA_C_LIST_F" | grep -cx -F -- "$1")"
  case "$n" in
    ''|*[!0-9]*) assert_eq "#655 conflict-path covers the generated artifact: $1" yes \
                   "no(count unestablished — sed/grep absent)" ;;
    0) assert_eq "#655 conflict-path covers the generated artifact: $1" yes \
         "no($1 is a generated artifact but no conflict-path line names it; a conflict there would take the hand-merge default)" ;;
    *) assert_eq "#655 conflict-path covers the generated artifact: $1" yes yes ;;
  esac
}
_ra_conflict_path_covered lib/capability-profiles.json
_ra_conflict_path_covered lib/test/modules/coverage-map.json
_ra_conflict_path_covered scripts/workflow-flight-recorder-registry.json
_ra_conflict_path_covered lib/test/run.sh
# The generated workflow literals, sourced from the generator's own REGIONS rather than
# re-enumerated in the registry. Pinned by their real paths here so a REGIONS rename that
# silently empties the derivation is caught.
_ra_conflict_path_covered .github/workflows/devflow-runner.yml
_ra_conflict_path_covered .github/workflows/devflow.yml
_ra_conflict_path_covered .github/workflows/devflow-implement.yml
_ra_conflict_path_covered .github/workflows/matcher-probe.yml
# The baked plugin-identity regions. `.github/workflows/devflow-runner.yml` also carries one
# and is already asserted above — it is covered by the CAPABILITY row, since a path resolves
# to exactly one class and that file's capability region claimed it first. The registry
# records that shared ownership as a disclosed residual; the audit's job here is only that
# every generated artifact is reachable by SOME conflict-path line, which it is.
_ra_conflict_path_covered .github/actions/vendor-plugin/vendor-slice.sh
_ra_conflict_path_covered install.sh
_ra_conflict_path_covered scripts/resolve-extra-plugins.sh

# ── (d) each regenerate/reconcile-source recipe names a command the TOOL really has ──
# A substring pin ("the recipe mentions 'generate'") stays green when the subcommand is
# renamed in the tool and the recipe goes dead. So the needle is checked against the
# tool's REAL interface: its `--help` text, or — for the capability generator, which has
# no argparse and rejects `--help` — an actual fixture run of the bare write form.
_ra_recipe_names() {  # row needle
  case "$(sed -n "s/^conflict-recipe	${1}	//p" "$RA_C_LIST_F")" in
    *"$2"*) printf 'yes' ;;
    *) printf 'no' ;;
  esac
}
# `--help` is captured from a FIXTURE copy so a mutated-tool arm below can rename the flag
# without touching the live checkout.
# The third argument is a `case` GLOB, not a plain substring, because a bare
# `*--write-baseline*` also matches `--write-baseline-renamed` — so the renamed-flag
# mutation would stay green and the pin would prove nothing. Callers append a `[!-]`
# boundary class so a longer flag with the same prefix does NOT satisfy the check.
# argparse's help is ANSI-colored here, so the boundary character is commonly an escape
# byte rather than a space; `[!-]` accepts either and only excludes the hyphen that a
# renamed sibling flag would carry.
_ra_tool_has_flag() {  # root tool-relative-path case-glob
  # shellcheck disable=SC2254  # the expansion IS the pattern — see the note above.
  case "$(cd "$1" && python3 "$2" --help 2>&1)" in
    $3) printf 'yes' ;;
    *) printf 'no' ;;
  esac
}
# The `--help` probes run against the LIVE checkout: argparse prints usage and exits before
# any repo I/O, so they cannot mutate anything and need no copy. The capability generator's
# BARE form is the one arm that writes (it rewrites the five workflow literal regions), so it
# alone gets a private fixture — stated here because it is otherwise invisible why one of
# these two probes is different.
RA_IFACE="$_ra_tmp_root/iface"; _ra_fixture "$RA_IFACE"
# The capability generator has no argparse (it rejects `--help`), so its interface is
# established by RUNNING the bare write form the recipe names against a fixture: an exit
# outside {0} — or an "unknown argument" breadcrumb — means the recipe names a dead form.
RA_CAPGEN_OUT="$(cd "$RA_IFACE" && python3 lib/generate-capability-profiles.py 2>&1)"; RA_CAPGEN_RC=$?
case "$RA_CAPGEN_RC/$RA_CAPGEN_OUT" in
  0/*unknown\ argument*|[!0]/*)
    assert_eq "#655 recipe interface: the capability generator's bare write form really runs" yes \
      "no(rc=$RA_CAPGEN_RC; output: $RA_CAPGEN_OUT)" ;;
  *) assert_eq "#655 recipe interface: the capability generator's bare write form really runs" yes yes ;;
esac
assert_eq "#655 recipe interface: the capability recipe names the generator and both coupled files" \
  "yes/yes/yes" \
  "$(_ra_recipe_names capability-profile-literals 'lib/generate-capability-profiles.py')/$(_ra_recipe_names capability-profile-literals 'lib/capability-profiles.json')/$(_ra_recipe_names capability-profile-literals 'lib/review-profile.tokens')"
# The identity recipe names the generator, and that generator's REAL interface is checked
# the same way — against its `--help`, not against a substring of the recipe. This one has
# argparse, so the probe is the cheap `--help` form rather than the capability row's
# fixture run. `[!-]` keeps `--check` from being satisfied by a longer `--check-something`.
assert_eq "#655 recipe interface: the identity recipe names the generator and both identity sources" \
  "yes/yes/yes" \
  "$(_ra_recipe_names plugin-identity-regions 'lib/generate-plugin-identity.py')/$(_ra_recipe_names plugin-identity-regions 'lib/plugin-identity.json')/$(_ra_recipe_names plugin-identity-regions '.claude-plugin/plugin.json')"
assert_eq "#655 recipe interface: the identity generator really declares the --check flag the row runs" \
  "yes" "$(_ra_tool_has_flag "$RA_REPO" lib/generate-plugin-identity.py '*--check[!-]*')"

# ── (e) exactly ONE conflict-sibling line, naming the reviewer lock ──────────────
assert_eq "#655 --list emits exactly one conflict-sibling line" "1" \
  "$(devflow_module_pin_count 'conflict-sibling	' "$RA_C_LIST_F")"
assert_eq "#655 the conflict-sibling line names the reviewer lock as by-hand" "1" \
  "$(devflow_module_pin_count 'conflict-sibling	capability-profile-literals	lib/review-profile.tokens	by-hand' "$RA_C_LIST_F")"

# ── (f) a conflict_class outside the closed set FAILS CLOSED ─────────────────────
# The bind-time validation raises, so `--list` never emits an unknown class a consumer
# would have no route for. Driven end-to-end: rc must be exactly 2 and the breadcrumb must
# name the offending value, not merely traceback anonymously.
# Both bind-time invariants take the same five steps (mutate the helper, run --list against
# the shared root, require exit 2, then pin the breadcrumb), so they share a helper —
# the same two-call-sites threshold at which this module already extracts one.
# #659 review (Important 3 + 4): this asserted only NON-ZERO, which could not tell exit 2
# (INFRASTRUCTURE — nothing was checked) from exit 1 (a resolvable "action required" item).
# That mattered in both directions. The bind-time arms genuinely exited 1 — the module-level
# raise ran before the `__main__` exit-2 net could catch it — silently contradicting this
# module's own EXIT CONTRACT; and the emit-time duplicate-path arm, which DID reach the net,
# would have stayed green if it ever regressed to 1. The helper now routes the bind-time
# raise to exit 2 (`_validate_registry`), so every arm below is exit 2 and this pins it.
_ra_bind_fails_closed() {  # label mutation needle...
  local label="$1" mutation="$2" mut _rc
  shift 2
  RA_C_MUT=$((RA_C_MUT + 1))
  mut="$_ra_tmp_root/c655-mut-$RA_C_MUT.py"
  sed -E "$mutation" "$RA_HELPER" > "$mut"
  python3 "$mut" --list --repo-root "$RA_C_SHARED" >"$mut.out" 2>&1
  _rc=$?
  assert_eq "#655 $label fails closed (exit 2 INFRASTRUCTURE, never 1)" "2" "$_rc"
  for _needle in "$@"; do
    case "$(devflow_module_pin_count "$_needle" "$mut.out")" in
      ''|*[!0-9]*) assert_eq "#655 $label breadcrumb names: $_needle" yes "no(count unestablished)" ;;
      0) assert_eq "#655 $label breadcrumb names: $_needle" yes "no(absent from the breadcrumb)" ;;
      *) assert_eq "#655 $label breadcrumb names: $_needle" yes yes ;;
    esac
  done
}
_ra_bind_fails_closed "an out-of-set conflict_class" \
  's/"conflict_class": "regenerate"/"conflict_class": "hand-wave"/' \
  "'hand-wave'" "which is outside"
_ra_bind_fails_closed "an empty recipe" \
  's/^        "policy": "add the missing coverage rows.*$/        "policy": "",/' \
  "empty recipe (policy)"
# issue #1244: preflight eligibility is declared data, validated at bind time.
# A non-bool `preflight_eligible` fails closed. `"preflight_eligible": False` occurs
# exactly once (the ineligible exact-module-floors row); `0` is not a bool in Python.
_ra_bind_fails_closed "a non-bool preflight_eligible" \
  's/"preflight_eligible": False/"preflight_eligible": 0/' \
  "not a bool"
# `opt_in` is optional, but a PRESENT non-bool must fail closed too: a truthy string
# would silently opt its row out of the default pass with no flag able to opt it back
# in. `"opt_in": True` occurs exactly once (the exact-module-floors row).
_ra_bind_fails_closed "a non-bool opt_in" \
  's/"opt_in": True/"opt_in": "yes"/' \
  "declares opt_in 'yes'" "not a bool"

# ── (f2) an underivable region set exits 2 (INFRASTRUCTURE), never 1 ────────────
# `_capability_region_targets` documents that it RAISES rather than returning a partial set, and
# that the top-level net routes the raise to the exit-2 infrastructure state. This arm covers the
# raise that happens DURING a run (the region set is derived under the target root, so it cannot
# be validated at import); the (f) arms above cover the import-time bind validation, which since
# the #659 review reaches the same exit 2 via `_validate_registry`'s routed raise rather than the
# exit 1 a bare module-level raise produced. The distinction is this repo's unchecked-vs-resolvable
# discriminator (the same reason a dozen sibling arms pin "exits 2, never 1"): an exit 1 here
# would tell the agent a conflicted artifact is resolvable when the path set was never derived,
# which is exactly the fail-open the shipped rule's "when --list cannot run" default exists to stop.
_ra_region_fails_infra() {  # label fixture-mutation-command
  local label="$1" dest
  dest="$_ra_tmp_root/c655-regions-$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '-')"
  rm -rf "$dest"; _ra_fixture "$dest"
  ( cd "$dest" && eval "$2" ) >/dev/null 2>&1
  python3 "$RA_HELPER" --list --repo-root "$dest" >"$dest/.ra.out" 2>&1
  printf '%s\n' "$?" >"$dest/.ra.rc"
  assert_eq "#655 $label exits 2 (infrastructure), never 1" "2" "$(_ra_rc "$dest")"
  _ra_has "#655 $label is named as an infrastructure failure" "$dest" "INFRASTRUCTURE"
}
# An ABSENT generator: the import itself cannot resolve.
_ra_region_fails_infra "an absent capability generator" \
  "rm -f lib/generate-capability-profiles.py"
# A generator that imports cleanly but declares NO regions: the fail-closed arm inside the
# derivation, distinct from the absent-file arm above (a short list must not read as a clean one).
_ra_region_fails_infra "an empty generator REGIONS list" \
  "sed -E 's/^REGIONS = \\[\$/REGIONS = []  # mutated/' lib/generate-capability-profiles.py > .rg.tmp && mv .rg.tmp lib/generate-capability-profiles.py"

# ── (f3) a row declaring no path source, and a path claimed by TWO rows, fail closed ──
# Both are the same fail-open one level in: without them a misregistered row reaches a consumer
# either with no path at all, or with a path resolving to two contradictory classes the rule has
# no stated tiebreak for. `_ra_bind_fails_closed` drives each end-to-end (non-zero exit plus the
# breadcrumb that names the offence), so neither can regress to a silent listing.
_ra_bind_fails_closed "an empty conflict_paths tuple" \
  's/"conflict_paths": \("lib\/test\/modules\/coverage-map.json",\)/"conflict_paths": ()/' \
  "declares an empty conflict_paths" "at least one conflict path"
# #659 review (Suggestion 1): a path emitted as BOTH a conflict-path and a conflict-sibling
# hands the shipped rule two contradictory classes — the sibling's own fourth field vs the
# owning row's — with no tiebreak, the same fail-open a two-row duplicate is. Point the
# coverage-map row at the capability row's coupled sibling to drive it.
_ra_bind_fails_closed "a path claimed as both a conflict-path and a coupled sibling" \
  's/"conflict_paths": \("lib\/test\/modules\/coverage-map.json",\)/"conflict_paths": ("lib\/review-profile.tokens",)/' \
  "is claimed by both" "coupled by-hand sibling" "exactly one conflict class"
_ra_bind_fails_closed "a row declaring no conflict-path source" \
  's/"conflict_paths": \("lib\/test\/modules\/coverage-map.json",\),//' \
  "declares no conflict-path source" "coverage-map-ratchet"
# The live registry must actually satisfy the uniqueness invariant the emit enforces — the
# positive control, so the arms above are not the only evidence that duplicates are impossible.
assert_eq "#655 no conflict-path value is claimed by more than one row (live registry)" "" \
  "$(sed -n 's/^conflict-path	[^	]*	//p' "$RA_C_LIST_F" | sort | uniq -d)"

# ── (g) the recipe is a SINGLE source: `policy`, read by BOTH consumers ──────────
# A parallel `conflict_recipe` field would let the batched pass and the conflict rule
# drift — the coupled-mirror hazard. Two halves: no such field exists, and the string the
# batched pass prints as `governing policy:` is byte-identical to the `conflict-recipe`
# line for the same row.
assert_eq "#655 no parallel conflict_recipe field exists (the recipe is the reused policy)" "0" \
  "$(devflow_module_pin_count 'conflict_recipe' "$RA_HELPER")"
# A3 already ran a fixture whose capability row emitted a JUDGMENT with its governing
# policy; compare that rendered text against this row's conflict-recipe line. Both are
# derived from the live registry, so a split into two fields breaks the equality.
RA_C655G_RECIPE="$(sed -n 's/^conflict-recipe	capability-profile-literals	//p' "$RA_C_LIST_F")"
case "$RA_C655G_RECIPE" in
  '') assert_eq "#655 the capability conflict-recipe is non-empty (single-source test is live)" yes \
        "no(empty — the comparison below would be vacuous)" ;;
  *)  assert_eq "#655 the capability conflict-recipe is non-empty (single-source test is live)" yes yes ;;
esac
_ra_has "#655 the batched pass prints the SAME recipe string as governing policy" "$RA_A3" \
  "governing policy: $RA_C655G_RECIPE"

# ── Surface-presence pins: the rule copies and the arm pointers ──────────────────
# `assert_pin_unique`-class presence checks (no mutation obligation): these assert that a
# coupled prose mirror is present and identical, not that a behavior flips.
RA_EXT_DIR="$RA_REPO/.prflow/prompt-extensions"
RA_RULE_HEADING='## Merge conflicts in generated artifacts'
# Issue #1055 retargeted the oracle literal onto the granted direct leading-token form.
# The pin is RETAINED, not retired: this literal has no row in the frozen census, which is
# CONTRIBUTING.md's arm 0 — the census cannot answer, so the pin stays. The per-extension
# head/shape extraction added below is the stronger executable guarantee (an
# inline-backtick or interpreter-head regression fails it and a rewording does not), but
# it is additive, not an authorization to drop an unadjudicated divergence check.
devflow_module_pin_unique "#1055 the implement conflict oracle uses the granted direct head" \
  'lib/test/regenerate-artifacts.py --list' "$RA_EXT_DIR/implement.md"  # structural-pin-ok: cross-file-phase-contract -- the cloud-only config grant and prompt invocation must stay coupled
for _ext in review-and-fix receiving-code-review; do
  devflow_module_pin_unique "#655 the conflict rule has its own section in $_ext.md" \
    "$RA_RULE_HEADING" "$RA_EXT_DIR/$_ext.md"  # runtime-pin-ok: target path interpolates the `for _ext …` loop var, unresolvable by the static meta-guard
done
# Spelled out per file rather than driven from the loop above: a declared structural pin
# must name a target the #810 static scanner can open, and a loop-interpolated path is
# unresolvable to it.
devflow_module_pin_unique "#655 the conflict rule cites --list as the oracle in review-and-fix.md" \
  'lib/test/regenerate-artifacts.py --list' "$RA_EXT_DIR/review-and-fix.md"  # structural-pin-ok: cross-file-phase-contract -- the cloud-only config grant and prompt invocation must stay coupled
devflow_module_pin_unique "#655 the conflict rule cites --list as the oracle in receiving-code-review.md" \
  'lib/test/regenerate-artifacts.py --list' "$RA_EXT_DIR/receiving-code-review.md"  # structural-pin-ok: cross-file-phase-contract -- the cloud-only config grant and prompt invocation must stay coupled
# Byte-identity across the three copies: extract each section (heading to the next `## `)
# and require all three to be equal. A per-file presence pin cannot catch a copy that
# drifted in its body.
_ra_rule_body() {  # file
  # All three copies carry the granted direct leading-token form, so the section is
  # compared verbatim — no normalization stands between the copies.
  sed -n "/^${RA_RULE_HEADING}\$/,/^## /p" "$1" | sed '$d'
}
RA_RULE_IMPL="$(_ra_rule_body "$RA_EXT_DIR/implement.md")"
case "$RA_RULE_IMPL" in
  '') assert_eq "#655 the extracted conflict-rule section is non-empty (identity test is live)" yes \
        "no(empty — the byte-identity comparisons below would be vacuous)" ;;
  *)  assert_eq "#655 the extracted conflict-rule section is non-empty (identity test is live)" yes yes ;;
esac
assert_eq "#655 the conflict rule is byte-identical in review-and-fix.md" \
  "$RA_RULE_IMPL" "$(_ra_rule_body "$RA_EXT_DIR/review-and-fix.md")"
assert_eq "#655 the conflict rule is byte-identical in receiving-code-review.md" \
  "$RA_RULE_IMPL" "$(_ra_rule_body "$RA_EXT_DIR/receiving-code-review.md")"
# The rule lives OUTSIDE the Batched-artifact-regeneration section: that section's trigger
# is post-edit/pre-suite, which no in-run conflict arm ever routes through — placing the
# rule only there is what would leave the conflict handler unwired.
assert_eq "#655 the conflict rule is its own top-level section, not nested under Batched" "1" \
  "$(devflow_module_pin_count "$RA_RULE_HEADING" "$RA_EXT_DIR/implement.md")"
# The narrow prompt-mass conflict sentence is retired in favour of the generalized rule;
# a surviving second statement of the same decision is the coupled-mirror defect.
assert_eq "#655 the superseded narrow prompt-mass conflict sentence is gone" "0" \
  "$(devflow_module_pin_count 'Resolve such a conflict by regenerating the complete' "$RA_EXT_DIR/implement.md")"
# #659 review (Suggestion 5): the replacement sentence points at the rule by PROSE TITLE. The
# heading's existence is pinned above, and the sentence's existence is implied by the retirement
# pin above — but nothing bound the two, so renaming the heading would leave the pointer aiming
# at a section that no longer exists while both pins stayed green. Derive the cross-reference
# needle FROM the heading constant (strip the `## `) rather than re-spelling the title, so the
# two cannot drift: a rename must update the pointer or this goes RED.
assert_eq "#655 implement.md's cross-reference names the rule's actual heading literal" "1" \
  "$(devflow_module_pin_count "under the ${RA_RULE_HEADING#\#\# } section" "$RA_EXT_DIR/implement.md")"

# The generic, repo-agnostic pointer each in-run conflict arm carries. It names no
# DevFlow-internal helper, so it stays correct in the vendored/shipped surfaces.
# The pointer carries its own fail-closed default: without one it states a prohibition the agent
# has no way to evaluate in a repo with no guidance, and falls through to the surrounding
# resolve-it-yourself arm — hand-merging exactly what the sentence forbids.
RA_ARM_POINTER='if you cannot establish whether the conflicted file is generated, stop and mark it needs-human-reconciliation rather than hand-merging'
devflow_module_pin_unique "#655 the implement checkpoint CONFLICT arm carries the generic pointer" \
  "$RA_ARM_POINTER" "$RA_REPO/skills/implement/phases/phase-1-setup.md"
devflow_module_pin_unique "#655 the review-and-fix CONFLICT arm carries the generic pointer" \
  "$RA_ARM_POINTER" "$RA_REPO/skills/review-and-fix/references/fixing.md"
devflow_module_pin_unique "#655 the receiving-code-review branch-update arm carries the generic pointer" \
  "$RA_ARM_POINTER" "$RA_REPO/skills/receiving-code-review/SKILL.md"
# The vendored skill ships to consumers, so its pointer must name no DevFlow-internal
# helper — the same repo-agnostic boundary its upstream MIT body already carries.
assert_eq "#655 the vendored receiving-code-review pointer names no DevFlow-internal helper" "0" \
  "$(devflow_module_pin_count 'regenerate-artifacts.py' "$RA_REPO/skills/receiving-code-review/SKILL.md")"

# The reconciler's transactional and refusal semantics are exercised in Python so the
# fixtures can compare both complete post-images without reproducing JSON handling in shell.
devflow_run_focused_python_test "#1055 measured floor reconciliation focused tests pass" \
  "$LIB/test/test_reconcile_module_floors.py" "$_ra_tmp_root/floor-reconcile-unit.out"

# Exercise the same command-head and command-shape analyzers that guard cloud prompt
# bundles. The generated baseline deliberately does not grant this self-repository path;
# the resolved runtime profile adds `.prflow/config.json`'s repository-local extras.
RA_1055_PROMPT="$_ra_tmp_root/issue-1055-direct-head.md"
RA_1055_RESOLVED="$_ra_tmp_root/issue-1055-resolved-allowlist.txt"
"$RA_REPO/scripts/load-prompt-extension.sh" implement \
  --section '## Batched artifact regeneration' > "$RA_1055_PROMPT"
"$RA_REPO/scripts/load-prompt-extension.sh" implement \
  --section '## Merge conflicts in generated artifacts' >> "$RA_1055_PROMPT"
RA_1055_HEADS="$(python3 "$LIB/test/extract-command-heads.py" heads "$RA_1055_PROMPT")"
# ONE line, not one per fence: `heads` prints a sorted SET of head NAMES, so the two
# fences in these sections — `…regenerate-artifacts.py` and `…regenerate-artifacts.py
# --list` — share a head name and can only ever collapse to a single line. A two-line
# expectation is unsatisfiable, not merely unmet.
assert_eq "#1055 the batched helper is extracted as a direct command head" \
  'lib/test/regenerate-artifacts.py' "$RA_1055_HEADS"
# The combined extraction above cannot tell "both sections fenced" from "one fenced, one
# still in inline backticks" — the set collapses either way, so reverting EITHER fence
# would leave it green. Extract every (extension, section) pair on its own instead. This
# is the assertion that actually holds the matcher-visibility fix, and it is what replaced
# the retired wording pins over these sentences: an inline-backtick mention yields NO head
# and an interpreter head yields `python3`, so either regression fails here, while a
# reworded sentence — which changes no executable property — does not.
# Each pair is spelled out because the two sections no longer live on the same extension
# set: receiving-code-review is loaded by dispatched subagents and carries the conflict
# rule alone, so a batched pass cannot be re-run inside the orchestrator's own iteration.
for _ra_1055_pair in \
  'implement|## Batched artifact regeneration' \
  'implement|## Merge conflicts in generated artifacts' \
  'review-and-fix|## Batched artifact regeneration' \
  'review-and-fix|## Merge conflicts in generated artifacts' \
  'receiving-code-review|## Merge conflicts in generated artifacts'; do
  _ra_1055_ext="${_ra_1055_pair%%|*}"
  _ra_1055_section="${_ra_1055_pair#*|}"
  "$RA_REPO/scripts/load-prompt-extension.sh" "$_ra_1055_ext" --section "$_ra_1055_section" \
    > "$_ra_tmp_root/issue-1055-section.md"
  assert_eq "#1055 $_ra_1055_ext.md '$_ra_1055_section' fences the granted direct head" \
    'lib/test/regenerate-artifacts.py' \
    "$(python3 "$LIB/test/extract-command-heads.py" heads "$_ra_tmp_root/issue-1055-section.md")"
  python3 "$LIB/test/extract-command-shapes.py" --profile implement \
    "$_ra_tmp_root/issue-1055-section.md" > "$_ra_tmp_root/issue-1055-section-shapes.out" 2>&1
  assert_eq "#1055 $_ra_1055_ext.md '$_ra_1055_section' is clean under implement shape rules" \
    "0" "$?"
done

# The batched pass must NOT reach a dispatched reception subagent: each one re-ran the
# multi-minute pass inside the orchestrator's own iteration. Asserted at the loader's
# executable boundary — an empty section extraction — rather than by grepping wording.
"$RA_REPO/scripts/load-prompt-extension.sh" receiving-code-review \
  --section '## Batched artifact regeneration' \
  > "$_ra_tmp_root/issue-1055-rcr-batched.md" 2>/dev/null || :
assert_eq "#optin receiving-code-review carries no batched-regeneration section" \
  "" "$(cat "$_ra_tmp_root/issue-1055-rcr-batched.md")"
RA_1055_BASE_UNGRANTED="$(python3 "$LIB/test/extract-command-heads.py" ungranted \
  "$RA_1055_PROMPT" "$RA_REPO/.github/workflows/devflow-implement.yml" tools-line)"
assert_eq "#1055 the generated consumer baseline does not grant the self-repository helper" \
  "lib/test/regenerate-artifacts.py" "$RA_1055_BASE_UNGRANTED"
{
  # The implement allowlist is the single `TOOLS='...'` line in the hoisted
  # `Resolve allowed-tools` step (issue #1170); concatenate it with the config
  # so the whole-file parse below sees the base grants PLUS the config extras.
  grep -E "^[[:space:]]*TOOLS='" "$RA_REPO/.github/workflows/devflow-implement.yml"
  cat "$RA_REPO/.prflow/config.json"
} > "$RA_1055_RESOLVED"
RA_1055_RESOLVED_UNGRANTED="$(python3 "$LIB/test/extract-command-heads.py" ungranted \
  "$RA_1055_PROMPT" "$RA_1055_RESOLVED")"
assert_eq "#1055 the resolved implement profile grants the direct batched helper head" \
  "" "$RA_1055_RESOLVED_UNGRANTED"
python3 "$LIB/test/extract-command-shapes.py" --profile implement "$RA_1055_PROMPT" \
  > "$_ra_tmp_root/issue-1055-shapes.out" 2>&1
RA_1055_SHAPE_RC=$?
assert_eq "#1055 the direct helper invocation is clean under implement shape rules" \
  "0" "$RA_1055_SHAPE_RC"
RA_1055_MODE="$(git -C "$RA_REPO" ls-files -s -- lib/test/regenerate-artifacts.py)"
RA_1055_MODE="${RA_1055_MODE%% *}"
assert_eq "#1055 the batched helper is executable in the Git index" "100755" "$RA_1055_MODE"

RA_1055_CHILD_PROMPT="$_ra_tmp_root/issue-1055-child-head.md"
printf '%s\n' '```bash' 'lib/test/cloud_writer_contract.py generate' '```' > "$RA_1055_CHILD_PROMPT"
RA_1055_CHILD_UNGRANTED="$(python3 "$LIB/test/extract-command-heads.py" ungranted \
  "$RA_1055_CHILD_PROMPT" "$RA_1055_RESOLVED")"
assert_eq "#1055 the matcher-visible profile does not grant the subprocess-only child" \
  "lib/test/cloud_writer_contract.py" "$RA_1055_CHILD_UNGRANTED"
assert_eq "#1055 the exact-floor recipe routes through the granted batch entry point" \
  "yes" "$(_ra_recipe_names exact-module-floors 'lib/test/regenerate-artifacts.py')"
assert_eq "#1055 the exact-floor recipe does not expose its subprocess-only child" \
  "no" "$(_ra_recipe_names exact-module-floors 'python3 lib/test/reconcile-module-floors.py')"

# #2121 — install-state detection AND repair route through the batched helper, not the
# generator head.
assert_eq "#2121 install-state detection/repair routes through the granted batch entry point" \
  "yes" "$(_ra_recipe_names install-state 'lib/test/regenerate-artifacts.py')"
assert_eq "#2121 the install-state recipe does not expose the generator head directly" \
  "no" "$(_ra_recipe_names install-state 'python3 lib/generate-install-state.py --check')"

# ── #1206 — the coupled-site registry (issue #1206) ──────────────────────────
# `--list` prints a coupled-site registry AFTER everything it printed before, so a person
# or an automated run can ask "what else must change when I edit X?" read-only. RA_LIST
# (captured at A4) is the live `--list` output; RA_LIST_RC its exit code.

# (a) — AC1/AC8(a): the addition leaves the pre-existing output byte-for-byte unchanged.
# Emit with an EMPTIED table and compare against the live list with its coupled-site lines
# stripped: if the two match, nothing above the coupled-site block moved.
RA_1206_EMPTY_EMIT="$(python3 - "$RA_HELPER" "$RA_REPO" <<'RA_1206_EMPTY'
import contextlib, importlib.util, io, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ra1206empty", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.COUPLED_SITES = ()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    mod.emit_list(Path(sys.argv[2]).resolve())
sys.stdout.write(buf.getvalue())
RA_1206_EMPTY
)"
RA_1206_LIST_NOCOUPLED="$(printf '%s\n' "$RA_LIST" | grep -v '^coupled-site')"
_ra_same "#1206 (a) an empty COUPLED_SITES leaves the artifact/conflict/preflight output unchanged" \
  "$RA_1206_LIST_NOCOUPLED" "$RA_1206_EMPTY_EMIT" \
  "adding the coupled-site registry changed a line printed before it"
# And the coupled-site lines really are LAST: nothing above them in the live list is a
# coupled-site line (the empty-table compare above only proves the non-coupled lines match).
RA_1206_FIRST_COUPLED="$(printf '%s\n' "$RA_LIST" | grep -n '^coupled-site' | head -1 | cut -d: -f1)"
RA_1206_LAST_PREFLIGHT="$(printf '%s\n' "$RA_LIST" | grep -n '^preflight	' | tail -1 | cut -d: -f1)"
_ra_ok "#1206 (a) the coupled-site block prints after the preflight block" \
  "$([ -n "$RA_1206_FIRST_COUPLED" ] && [ -n "$RA_1206_LAST_PREFLIGHT" ] && [ "$RA_1206_FIRST_COUPLED" -gt "$RA_1206_LAST_PREFLIGHT" ] && printf yes || printf no)" \
  "a coupled-site line printed before the last preflight line"

# (b) — AC8(b): the new lines print in the documented tab-separated shape, and each
# required entry (AC5/AC6/AC7) is present with its class, original, and partners.
_ra_has_file "#1206 (b) AC5 the EXTRAS entry prints in the documented shape" "$RA_C_LIST_F" \
  "coupled-site	matcher-probe-extras	allowlist-mirror	.prflow/config.json	"
_ra_has_file "#1206 (b) AC5 the EXTRAS partner is the matcher-probe workflow" "$RA_C_LIST_F" \
  "coupled-site-partner	matcher-probe-extras	.github/workflows/matcher-probe.yml"
_ra_has_file "#1206 (b) AC6 the _WSR_SWEPT_RELPATHS entry is present" "$RA_C_LIST_F" \
  "coupled-site	wsr-swept-relpaths	frozen-old-paths	lib/test/run.sh	"
_ra_has_file "#1206 (b) AC7 the rename-map readers entry names lib/rename-map.json" "$RA_C_LIST_F" \
  "coupled-site	rename-map-readers	single-source-readers	lib/rename-map.json	"
_ra_has_file "#1206 (b) AC7 a rename-map reader partner is a shipped workflow config job" "$RA_C_LIST_F" \
  "coupled-site-partner	rename-map-readers	.github/workflows/devflow.yml"
_ra_has_file "#1206 (b) AC7 the deliberate state-dir mirror entry is present" "$RA_C_LIST_F" \
  "coupled-site	rename-map-state-dir-mirror	deliberate-mirror	lib/rename-map.json	"
_ra_has_file "#1206 (b) AC7 the state-dir mirror names lib/state_dir.py" "$RA_C_LIST_F" \
  "coupled-site-partner	rename-map-state-dir-mirror	lib/state_dir.py"

# AC6/AC4 exemption, observed LIVE: the old-path entry names a `.devflow/` path that does
# NOT exist in the tree, yet `--list` still exits 0 — the holds_old_paths marker exempts it.
assert_eq "#1206 (b) AC4/AC6 --list still exits 0 despite the old-path entry" "0" "$RA_LIST_RC"
_ra_has_file "#1206 (b) AC6 the old-path partner is emitted verbatim" "$RA_C_LIST_F" \
  "coupled-site-partner	wsr-swept-relpaths	.devflow/prompt-extensions/implement.md"

# (c) — AC3/AC8(c): a structurally-bad entry raises at import; a script run routes that to
# the exit-2 infrastructure state naming the bad entry, never a shortened list called
# success. Driven end-to-end through the shared `_ra_bind_fails_closed` harness.
_ra_bind_fails_closed "a coupled-site entry with an empty coupling_class" \
  's/"coupling_class": "allowlist-mirror"/"coupling_class": ""/' \
  "'matcher-probe-extras'" "non-empty string"
# AC3: a NON-DICT entry (a bare string, a stray tuple, None) is rejected as a ValueError
# naming its index — not as the AttributeError/TypeError a `.get` on a non-mapping would
# raise, which the import-time net (ValueError only) would let out as an exit-1 traceback
# instead of the documented exit-2 INFRASTRUCTURE routing. The index is the only handle:
# such a row has no `name` to be reported by.
_ra_bind_fails_closed "a non-dict coupled-site entry is rejected" \
  's/^COUPLED_SITES = \($/COUPLED_SITES = ("stray-string",/' \
  "index 0" "must be a dict"
_ra_bind_fails_closed "a duplicate coupled-site name" \
  's/"name": "rename-map-state-dir-mirror"/"name": "rename-map-readers"/' \
  "declared more than once"

# (d) — AC4/AC8(d): an entry naming a path absent from the tree is a loud exit-2 failure
# naming BOTH the entry and the path. The check runs when the list is printed (`--repo-root`
# points at a fixture root here). `#` sed delimiter because the paths carry `/`.
_ra_bind_fails_closed "a coupled-site entry naming a missing path" \
  's#"original": ".prflow/config.json"#"original": ".prflow/nonexistent-xyz.json"#' \
  "matcher-probe-extras" ".prflow/nonexistent-xyz.json" "absent from the tree"
# AC4/AC6: removing the holds_old_paths marker EXPOSES the old paths to the existence
# check — proving the marker (not a hardcoded path list) is what exempts them.
_ra_bind_fails_closed "removing holds_old_paths exposes the old paths to the AC4 check" \
  's/"holds_old_paths": True,//' \
  "wsr-swept-relpaths" ".devflow/prompt-extensions/implement.md" "absent from the tree"
# AC4: the holds_old_paths marker exempts only the PARTNERS — the `original` is a live file
# and stays existence-checked even on an old-path entry. A missing `original` on the
# holds_old_paths entry still fails closed (this would PASS under a whole-entry skip). `#`
# sed delimiter because the paths carry `/`.
_ra_bind_fails_closed "an old-path entry with a missing original still fails the AC4 check" \
  's#"original": "lib/test/run.sh"#"original": "lib/test/nonexistent-run.sh"#' \
  "wsr-swept-relpaths" "lib/test/nonexistent-run.sh" "absent from the tree"
# AC3: a non-bool holds_old_paths is rejected at import — a truthy STRING must not silently
# disable the AC4 existence check (the fail-open guard-class CLAUDE.md warns about).
_ra_bind_fails_closed "a non-bool holds_old_paths is rejected" \
  's/"holds_old_paths": True,/"holds_old_paths": "yes",/' \
  "wsr-swept-relpaths" "not a bool"
# AC3: an entry with an empty partners tuple is rejected — a coupled site with no partner
# records no coupling. matcher-probe-extras' partners is a single-line tuple, so this
# mutation is unambiguous.
# The `(`/`)` are escaped: `_ra_bind_fails_closed` runs `sed -E`, so bare parens are ERE
# grouping metacharacters, not literals.
_ra_bind_fails_closed "a coupled-site entry with no partners is rejected" \
  's#"partners": \(".github/workflows/matcher-probe.yml",\),#"partners": (),#' \
  "matcher-probe-extras" "one or more partner"

# ── #1457 — per-row progress lines, a per-row declared bound, and the timeout ─────
# The batched pass emits an attributed progress line as a row starts and completes
# (AC1, STDERR), a `timeout_seconds` int is declared per registry row and validated at import
# (AC2), a bounded-out row is terminated with its whole process group (AC6) and reported
# by name as an exit-2 INFRASTRUCTURE outcome (AC4), and a `DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS`
# override replaces every bound / is refused when malformed (AC5).

# AC1 — progress on STDERR, report byte-shape unchanged on STDOUT. Split the streams (the
# `_ra_run*` wrappers merge them with 2>&1, which cannot show the separation this asserts).
RA_1457_A1="$_ra_tmp_root/i1457-a1"; _ra_fixture "$RA_1457_A1"
python3 "$RA_HELPER" --repo-root "$RA_1457_A1" >"$RA_1457_A1/.ra.out" 2>"$RA_1457_A1/.ra.err"
printf '%s\n' "$?" >"$RA_1457_A1/.ra.rc"
assert_eq "#1457 AC1 the clean default pass still exits 0" "0" "$(_ra_rc "$RA_1457_A1")"
_ra_has_file "#1457 AC1 a row start line names the row on STDERR" "$RA_1457_A1/.ra.err" \
  "regenerate-artifacts: row capability-profile-literals: start"
_ra_has_file "#1457 AC1 a row done line names the row on STDERR" "$RA_1457_A1/.ra.err" \
  "regenerate-artifacts: row capability-profile-literals: done"
_ra_has_file "#1457 AC1 a second row is progress-reported too" "$RA_1457_A1/.ra.err" \
  "regenerate-artifacts: row plugin-identity-regions: start"
_ra_has_file "#1457 AC1 the stdout report keeps its clean line" "$RA_1457_A1/.ra.out" \
  "[capability-profile-literals] clean"
_ra_lacks_file "#1457 AC1 progress is NOT written to stdout (report flush is byte-for-byte)" \
  "$RA_1457_A1/.ra.out" 'regenerate-artifacts: row '
_ra_lacks_file "#1457 AC3 no timeout fires on the clean tree" \
  "$RA_1457_A1/.ra.err" 'TIMED OUT'

# AC2 — a `timeout_seconds` int is declared per registry row, validated at import exactly as
# `preflight_eligible` is. Driven through the same fail-closed harness the #655/#1244 bind
# arms use: an absent field, a non-int, and a bool (an int subclass) each raise, routed to
# exit 2 and named by row. Each mutated literal is unique to one row.
_ra_bind_fails_closed "a row missing timeout_seconds" \
  '/"timeout_seconds": 32,/d' \
  "capability-profile-literals" "not an int"
_ra_bind_fails_closed "a non-int timeout_seconds" \
  's/"timeout_seconds": 31,/"timeout_seconds": "soon",/' \
  "coverage-map-ratchet" "not an int"
_ra_bind_fails_closed "a bool timeout_seconds (an int subclass) is rejected" \
  's/"timeout_seconds": 550,/"timeout_seconds": True,/' \
  "exact-module-floors" "not an int"
# #2121 — a non-positive timeout is a mis-typed field, not a 0/negative wall.
_ra_bind_fails_closed "a zero timeout_seconds is rejected" \
  's/"timeout_seconds": 32,/"timeout_seconds": 0,/' \
  "capability-profile-literals" "not a positive int"
_ra_bind_fails_closed "a negative timeout_seconds is rejected" \
  's/"timeout_seconds": 22,/"timeout_seconds": -1,/' \
  "plugin-identity-regions" "not a positive int"


# AC4/AC5/AC6 — a bounded-out row: fast judgment rows are trivial exit-0 stubs; the
# env-freeze-advisory-region generator is a sleeper spawning a child and recording both PIDs.
# The DEFAULT pass runs with a 5s override — above the stubs' cold-start, below the 120s sleeper.
RA_1457_TO="$_ra_tmp_root/i1457-timeout"; _ra_fixture "$RA_1457_TO"
for _stub in lib/generate-capability-profiles.py lib/generate-plugin-identity.py lib/test/coverage_map_guard.py; do
  printf '%s\n' 'import sys' 'sys.exit(0)' > "$RA_1457_TO/$_stub"
done
# shellcheck disable=SC2016  # single-quoted Python source; expansion belongs to that later process
printf '%s\n' \
  'import os, subprocess, time' \
  'child = subprocess.Popen(["sleep", "120"])' \
  'open(os.path.join(os.getcwd(), ".ra_slow_pids"), "w").write("%d\n%d\n" % (os.getpid(), child.pid))' \
  'time.sleep(120)' > "$RA_1457_TO/lib/generate-env-freeze-advisory.py"
DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS=5 python3 "$RA_HELPER" --repo-root "$RA_1457_TO" \
  >"$RA_1457_TO/.ra.out" 2>"$RA_1457_TO/.ra.err"
printf '%s\n' "$?" >"$RA_1457_TO/.ra.rc"
assert_eq "#1457 AC4 a timed-out row routes to INFRASTRUCTURE exit 2" "2" "$(_ra_rc "$RA_1457_TO")"
_ra_has_file "#1457 AC4 the timeout report is attributed to the slow row" "$RA_1457_TO/.ra.out" \
  "[env-freeze-advisory-region] INFRASTRUCTURE"
_ra_has_file "#1457 AC4 the timeout report states the exceeded bound" "$RA_1457_TO/.ra.out" \
  "exceeded its declared bound of 5s"
_ra_has_file "#1457 AC4 the timeout is announced on the STDERR progress stream" "$RA_1457_TO/.ra.err" \
  "regenerate-artifacts: row env-freeze-advisory-region: TIMED OUT after 5s"
_ra_count_is "#1457 AC4 exactly one INFRASTRUCTURE line (no other row blamed on stdout)" \
  "$RA_1457_TO/.ra.out" '] INFRASTRUCTURE' 1
_ra_count_is "#1457 AC4 exactly one TIMED OUT line (no other row blamed on stderr)" \
  "$RA_1457_TO/.ra.err" 'TIMED OUT' 1
# AC6 — the whole process tree died: the sleeper's recorded child PID (never pgrep -f) is
# gone after the bounded process-group kill. Give the SIGKILL a moment to reap.
sleep 1
RA_1457_PIDS="$RA_1457_TO/.ra_slow_pids"
if [ -f "$RA_1457_PIDS" ]; then
  RA_1457_PARENT="$(sed -n 1p "$RA_1457_PIDS")"
  RA_1457_CHILD="$(sed -n 2p "$RA_1457_PIDS")"
  _ra_ok "#1457 AC6 the timed-out row's child process is gone" \
    "$({ [ -n "$RA_1457_CHILD" ] && ! kill -0 "$RA_1457_CHILD" 2>/dev/null; } && printf yes || printf no)" \
    "a descendant of the timed-out row survived the process-group kill"
  _ra_ok "#1457 AC6 the timed-out row's own generator process is gone" \
    "$({ [ -n "$RA_1457_PARENT" ] && ! kill -0 "$RA_1457_PARENT" 2>/dev/null; } && printf yes || printf no)" \
    "the timed-out row's own process survived"
else
  assert_eq "#1457 AC6 the sleeper recorded its PIDs" yes "no(.ra_slow_pids absent — sleeper never launched)"
fi

# AC5 — a malformed override is refused loudly (exit 2 + a message naming the var and value),
# never silently ignored. Reuse the fixture; the refusal returns before the row loop runs.
env DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS=x python3 "$RA_HELPER" --repo-root "$RA_1457_TO" \
  >"$RA_1457_TO/.ra.mal.out" 2>"$RA_1457_TO/.ra.mal.err"
printf '%s\n' "$?" >"$RA_1457_TO/.ra.mal.rc"
assert_eq "#1457 AC5 a malformed override is refused loudly (exit 2)" "2" "$(cat "$RA_1457_TO/.ra.mal.rc")"
_ra_has_file "#1457 AC5 the refusal names the override var and the bad value" "$RA_1457_TO/.ra.mal.err" \
  "DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS='x' is not an integer"

# AC5 — a parseable but non-positive value (the second refusal arm) is refused loudly too,
# named as not a POSITIVE integer, so a `0`/`-5` operator slip cannot silently disable bounding.
env DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS=0 python3 "$RA_HELPER" --repo-root "$RA_1457_TO" \
  >"$RA_1457_TO/.ra.zero.out" 2>"$RA_1457_TO/.ra.zero.err"
printf '%s\n' "$?" >"$RA_1457_TO/.ra.zero.rc"
assert_eq "#1457 AC5 a non-positive override is refused loudly (exit 2)" "2" "$(cat "$RA_1457_TO/.ra.zero.rc")"
_ra_has_file "#1457 AC5 the non-positive refusal names the var and the bad value" "$RA_1457_TO/.ra.zero.err" \
  "DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS='0' is not a positive integer"

# AC5 — an EMPTY override behaves as unset (this repo's DEVFLOW_* rule): the clean fixture
# runs its declared bounds, exits 0, and no row is bounded out.
env DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS= python3 "$RA_HELPER" --repo-root "$RA_1457_A1" \
  >"$RA_1457_A1/.ra.empty.out" 2>"$RA_1457_A1/.ra.empty.err"
printf '%s\n' "$?" >"$RA_1457_A1/.ra.empty.rc"
assert_eq "#1457 AC5 an empty override behaves as unset (clean pass exits 0)" "0" "$(cat "$RA_1457_A1/.ra.empty.rc")"
_ra_lacks_file "#1457 AC5 an empty override does not bound any row out" \
  "$RA_1457_A1/.ra.empty.err" 'TIMED OUT'

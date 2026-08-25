# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable implement-contract contract module (issue #1934).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. The module owns its private fixture root and
# cleanup; it never invokes the runner or the full-suite boundary. Modules may not
# self-skip. The inventory in implement-contract.inventory.md maps the extracted coverage to its
# former lib/test/run.sh locations.
# Coverage (extracted from lib/test/run.sh, issue #1934):
#   skills/implement issue-body cache no-refetch lint (#693): lib/test/lint-issue-body-refetch.py driven over the real tree and the fixture --files-from arm.
#
# The trap below relies on the sourcing contract: both callers (module-harness.sh and
# run-module.sh) source this module inside a ( ... ) subshell, so the EXIT trap fires
# at subshell exit and cannot clobber the runner's own EXIT handling.
_m1934_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-implement-contract.XXXXXX")" || {
  printf 'could not allocate implement-contract fixture root\n' >&2
  return 1
}
_m1934_cleanup() { rm -rf "$_m1934_root"; }
trap _m1934_cleanup EXIT
# Redirect every `mktemp`/`mktemp -d` the extracted blocks allocate under the module's
# owned root, so all block fixtures are cleaned by the single trap above.
TMPDIR="$_m1934_root"
export TMPDIR

echo "#693 issue-body cache: no cut-over site re-fetches the body"
IBR_LINT="$LIB/test/lint-issue-body-refetch.py"
IBR_FX="$LIB/test/fixtures/issue-body-refetch"

# Real-tree run: clean now, plus a POSITIVE tally so a collapsed audited set can't read as clean.
IBR_OUT="$(python3 "$IBR_LINT" 2>&1)"; IBR_RC=$?
assert_eq "#693 scanner: clean on the tree as it stands" "rc=0" \
  "$([ "$IBR_RC" -eq 0 ] && printf 'rc=0' || printf 'rc=%s | %s' "$IBR_RC" "$IBR_OUT")"
assert_eq "#693 scanner: the real-tree run audited a positive number of files" "yes" \
  "$(printf '%s' "$IBR_OUT" | python3 -c 'import re,sys
m = re.search(r"audited (\d+) of", sys.stdin.read())
print("yes" if m and int(m.group(1)) > 0 else "no")')"

# Fixture-driven behavior over --files-from. The fixtures live under lib/test/ (unreachable from
# the default enumeration); their in-list paths are laid out under skills/implement/ so is_audited()
# selects them.
ibr_run() {  # <root> <path…> -> "rc=<n>|<stdout+stderr>"
  local root="$1"; shift
  local list out rc
  list="$(probe_tmp '#693 fixture list')" || return 0
  printf '%s\n' "$@" > "$list"
  out="$(python3 "$IBR_LINT" --root "$root" --files-from "$list" 2>&1)"; rc=$?
  rm -f "$list"
  printf 'rc=%s|%s' "$rc" "$out"
}

# Discrimination: the §1.1 producer fetch is the named in-file allowance — a green run over
# it (plus a clean file) proves the guard discriminates. Issue #1554 retired the §4.1 gate's
# own allowance with the fence that needed it, so the docgate fixture went with it.
assert_eq "#693 scanner: the §1.1 producer fetch is not flagged" \
  "rc=0|lint-issue-body-refetch: audited 2 of 2 files" \
  "$(ibr_run "$IBR_FX" skills/implement/clean.md skills/implement/producer.md)"
# The producer's MIGRATED spelling (issue #1633) writes to the absolute path the
# precondition printed, so the line carries the `<absolute-cache-path>` placeholder
# instead of the cache path — a separate allowance literal, driven on its own file so
# neither spelling's allowance can go vacuous behind the other.
assert_eq "#693 scanner: the migrated §1.1 producer spelling is not flagged" \
  "rc=0|lint-issue-body-refetch: audited 1 of 1 files" \
  "$(ibr_run "$IBR_FX" skills/implement/producer-migrated.md)"

# Planted-defect positive control, one per detected form (the coverage-claim rule).
while IFS=: read -r _ibr_file _ibr_slug _ibr_what; do
  [ -n "$_ibr_file" ] || continue
  assert_eq "#693 scanner: flags the $_ibr_what form ($_ibr_file)" "yes" \
    "$(case "$(ibr_run "$IBR_FX" "$_ibr_file")" in *"|$_ibr_file:"*"($_ibr_slug)"*) echo yes ;; *) echo no ;; esac)"
done <<'IBR_VIOLATIONS'
skills/implement/v-ghview-body.md:gh-issue-view-body:gh issue view requesting body
skills/implement/v-ghview-nojson.md:gh-issue-view-no-json:gh issue view with no --json
skills/implement/v-ghapi-body.md:gh-api-issue-body:gh api issue-body read
skills/implement/v-parseacs-issue.md:parse-acs-issue:parse-acs.py --issue
skills/implement/v-preflight-issue.md:preflight-issue:preflight.py --issue
skills/implement/v-wrapped.md:gh-issue-view-body:a line-wrapped detected form
IBR_VIOLATIONS

# An all-unaudited population is a zero tally at exit 0 (never a silent clean over nothing).
assert_eq "#693 scanner: an all-unaudited population is a zero tally at exit 0" \
  "rc=0|lint-issue-body-refetch: audited 0 of 0 files" \
  "$(ibr_run "$IBR_FX" other/foo.md)"

# Fail-closed arms (mirroring the #664 sibling, since the scaffolding is a deliberate mirror):
# an audited path that cannot be READ is named on stderr and, when it is the whole population,
# fails closed — "audited nothing" must never print the same thing as "audited everything, clean".
assert_eq "#693 scanner: an unreadable audited path is named, not silently skipped" "yes" \
  "$(case "$(ibr_run "$IBR_FX" skills/implement/no-such-file.md)" in *"SKIPPED skills/implement/no-such-file.md"*) echo yes ;; *) echo no ;; esac)"
assert_eq "#693 scanner: a wholly unreadable population fails closed rather than reporting clean" "rc=1|0 of 1" \
  "$(ibr_run "$IBR_FX" skills/implement/no-such-file.md | python3 -c 'import re,sys
t = sys.stdin.read()
m = re.search(r"audited (\d+ of \d+)", t)
print("rc=" + re.match(r"rc=(\d+)", t).group(1) + "|" + (m.group(1) if m else "no-tally"))')"
# An empty pre-filter enumeration fails closed with its own breadcrumb (never a silent exit 0).
assert_eq "#693 scanner: an empty enumeration fails closed with its own breadcrumb" "yes" \
  "$(case "$(ibr_run "$IBR_FX")" in "rc=0"*) echo "no: exited 0" ;; *"yielded zero paths"*) echo yes ;; *) echo no ;; esac)"

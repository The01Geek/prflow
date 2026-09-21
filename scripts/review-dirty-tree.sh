#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# review-dirty-tree.sh SUBCOMMAND … — the review engine's dirty-tree backstop
# (issue #2082). Snapshots the working tree before the Phase 3.1 review-agent
# dispatch and compares/restores after it, so advisory review agents cannot
# leave a mutation behind. Owns the whole snapshot/authenticate/compare/restore
# loop that used to live inline in skills/review/phases/phase-3-agents.md §3.1/§3.2.
#
# WHY A HELPER, not an inline fence (issue #2082): the fence was written with
# `${GIT_SNAP_BEFORE:-…}` expansions and `>` redirects, and the cloud permission
# matcher denies any command carrying those shapes — so on every review iteration
# the whole statement was refused before it ran, the backstop was silently absent,
# and the run paid a denial. As a committed helper invoked by its granted vendored
# literal as a leading token with literal arguments, the fence shrinks to a shape the
# matcher permits while the observable behaviour is byte-identical on every tier.
#
# The `GIT_SNAP_BEFORE`/`GIT_SNAP_AFTER` env seam is retained INTERNALLY (default
# `.prflow/tmp/review-dirty-tree-{before,after}`) so the project's own test suite can
# point the snapshot files at per-test temp paths — including the symlink-attack
# security tests; the emitted skill command no longer mentions those variables.
#
# The object ID that AUTHORISES a restore is held by the orchestrator (printed by
# `snapshot`) and passed back to `compare-and-restore` as a literal argument — never
# read from agent-writable scratch (issue #2082 AC4). The `entry-close` arm (issue #898)
# is the one exception by design: it reads the OID file the loop already persists and
# re-reads for compaction resilience, adding no trust boundary the loop does not carry.
#
# CONTRACT — subcommands (each takes OPTIONAL trailing literal path operands BEFORE AFTER DISABLED,
# issue #513 — precedence arg > GIT_SNAP_* env seam > default for BEFORE/AFTER; DISABLED has no env
# rung, so its precedence is arg > default; a caller uses them to point a nested
# window's scratch at per-dispatch files without a leading VAR= assignment the cloud matcher denies):
#   snapshot [BEFORE AFTER DISABLED]
#     Capture the authenticated `-z` before-snapshot to $GIT_SNAP_BEFORE. On success
#     print the snapshot's git object ID on stdout and exit 0; the orchestrator records
#     it as {GIT_SNAP_BEFORE_OID}. On failure emit a `::warning::` breadcrumb on stderr,
#     print NO object ID on stdout, and exit 0 (the orchestrator treats an absent OID as a
#     failed snapshot). It also writes the fixed repo-local disabled sentinel
#     (.prflow/tmp/review-dirty-tree-disabled) WHEN the scratch dir is writable — the sole
#     exception is a failure to create .prflow/tmp itself, where no sentinel is possible;
#     compare-and-restore then still fails closed via its missing-before-snapshot arm.
#   compare-and-restore OID [BEFORE AFTER DISABLED]
#     Compare the after-snapshot against the before-snapshot authenticated to OID and
#     restore only the snapshot-delta paths (a path under .prflow/tmp is never restored, and a
#     ??->staged transition is in-scope dirt, not already-dirty). Short-circuits on the disabled
#     sentinel, emitting a DISABLED/SKIPPED breadcrumb.
#     Emits the same `::warning::` breadcrumbs the inline fence did. Exit 0.
#   engine-setup ARGS… / engine-return ARGS… / view-materialize ARGS…
#     The review engine's one-call setup, return-file assembly, and commit-bound source-view
#     materialization (issue #851), hosted here because this head is granted on every tier;
#     the work and the argument contract live in the sibling review-engine-io.py. engine-setup
#     takes the `snapshot` LAST — after the diff cache is published, before the engine dispatches
#     any child — and its object ID reaches stdout only. Exit: the sibling's (0 ok/empty, 1 stop,
#     2 usage).
#   loop-setup [--pr N] / branch-sync --pr N
#     The review-and-fix loop's one-call setup and PR-head branch-sync (issue #894), hosted
#     here for the same granted-head reason; the work lives in the sibling review-loop-io.py.
#     loop-setup: this host runs compose-run-key.sh and the four config-get.sh reads (so the
#     producer executes no .sh, AC5) and hands the values and exit codes to the producer, which
#     applies the loop's clamps/breadcrumbs, resolves slug and run_dir by the same rule
#     engine-setup uses, creates the run dir, persists loop-setup.json and prints one JSON line;
#     it runs no gh. branch-sync: the producer runs the git/gh reads and prints the comparison —
#     no checkout, no git-state change. Exit: the sibling's (0 ok, 1 error, 2 usage).
#   entry-open --run-root DIR --entry step1|shadow --iteration N
#   entry-close --run-root DIR --entry step1|shadow --iteration N --head SHA --branch NAME
#     The review-and-fix loop's per-engine-entry bracket (issue #898), one call each side of a
#     dispatch, printing one JSON line on stdout. entry-open deletes DIR/diff.patch and every
#     DIR/batch-*.patch (the re-entrant freshness deletion), takes the `snapshot` to
#     .prflow/tmp/review/dt-<s1|shadow>-N-{before,after,disabled} and writes the object ID to
#     .prflow/tmp/review/dt-<s1|shadow>-N-oid.txt — the same files the loop's fallback fences
#     use, so either side of the bracket interoperates with the fence form of the other.
#     Line: {status:"ok", entry, iteration, cache_deleted:[…], snapshot:"taken"|"disabled", oid,
#     oid_file}. entry-close runs the post-return branch guard (`git rev-parse --abbrev-ref HEAD`
#     against --branch; on inequality the line is {status:"branch-mismatch", branch, expected},
#     on a failed or empty read {status:"branch-unestablished", expected} — nothing else runs on
#     either), then reads the OID file the open arm wrote (the loop's own persisted copy of the
#     ID `snapshot` printed — this arm, unlike a direct compare-and-restore, takes no OID
#     operand), checks the outer disabled sentinel and
#     runs `compare-and-restore` for the entry's files, classifying its breadcrumbs into
#     restore: "clean" | "restored" | "not-restored" | "blocked" (an OID file missing or empty,
#     a missing/forged before file, a SKIPPED/DISABLED/still-dirty breadcrumb, the outer
#     sentinel present, or an unrecognized breadcrumb — fail closed), then runs the sibling
#     loop-verdict-marker.py `write-active-entry-binding` and `check-evidence` with the same
#     operands and relays check-evidence's line-1 first token, exit code and line as
#     evidence:{token, exit, line} ("" / the observed code when the marker is absent). Line:
#     {status:"ok", branch, restore, restore_detail:[…], evidence:{…}}. Errors print
#     {status:"error", step, reason}: `arguments`/`run-root` exit 2; `cache` (a survivor after
#     deletion) exit 1. `iteration` and `evidence.exit` are JSON numbers, `cache_deleted` and
#     `restore_detail` arrays, every other field a string.
#
# Portability: bash 3.2 / BSD userland, no GNU-only flags (indexed-array linear scan,
# never `declare -A`; NUL-safe `read -r -d ''`).

set -u

SNAP_BEFORE="${GIT_SNAP_BEFORE:-.prflow/tmp/review-dirty-tree-before}"
SNAP_AFTER="${GIT_SNAP_AFTER:-.prflow/tmp/review-dirty-tree-after}"
DISABLED_SENTINEL=".prflow/tmp/review-dirty-tree-disabled"
OUTER_DISABLED_SENTINEL="$DISABLED_SENTINEL"
ENGINE_IO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/review-engine-io.py"
LOOP_IO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/review-loop-io.py"
# The loop-setup host runs compose-run-key.sh and config-get.sh itself (issue #894); the
# producer never executes a .sh (AC5). Both resolve script-relative by default; the
# LOOP_COMPOSE_RUN_KEY / LOOP_CONFIG_GET env seam is retained INTERNALLY so the project's
# own suite can point them at per-test stubs, exactly like the GIT_SNAP_* seam above — the
# emitted skill command names neither.
LOOP_COMPOSE_RUN_KEY="${LOOP_COMPOSE_RUN_KEY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/compose-run-key.sh}"
LOOP_CONFIG_GET="${LOOP_CONFIG_GET:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/config-get.sh}"
# The entry bracket's evidence half (issue #898) runs the sibling marker script; the
# LOOP_VERDICT_MARKER env seam is retained INTERNALLY so the suite can point it at a stub,
# exactly like GIT_SNAP_*; the emitted skill command never names it.
LOOP_VERDICT_MARKER="${LOOP_VERDICT_MARKER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/loop-verdict-marker.py}"

cmd_snapshot() {
  if ! mkdir -p .prflow/tmp 2>/dev/null; then
    # Distinct root-cause breadcrumb: without this, an unwritable .prflow/tmp surfaces only as the
    # generic snapshot-creation failure below, misattributing a filesystem fault to git/status.
    echo "::warning::devflow review: could not create .prflow/tmp (permissions/read-only-fs/disk-full?); working-tree snapshot not taken, dirty-tree backstop DISABLED for this dispatch — no after-compare, no auto-restore" >&2
    return 0
  fi
  # Snapshot to a NUL-delimited (`-z`) FILE with UNQUOTED paths: plain `--porcelain` C-quotes a
  # spaced path (`"my file.txt"`) into a silent `git checkout` no-op, and `-z` NUL bytes cannot
  # live in a `$(...)` variable — so use a file, not a variable.
  if rm -f "$SNAP_BEFORE" "$DISABLED_SENTINEL" 2>/dev/null &&
     git status --porcelain -z > "$SNAP_BEFORE" &&
     [ -f "$SNAP_BEFORE" ] &&
     [ ! -L "$SNAP_BEFORE" ] &&
     git hash-object "$SNAP_BEFORE"; then
    :
  else
    # Snapshot failed: do NOT fall through with an empty baseline — an empty BEFORE reads every
    # dirty path as agent-introduced and would `git checkout` the orchestrator's own edits. Fail
    # closed via the fixed repo-local sentinel (it survives the Agent boundary; a variable would not).
    echo "::warning::devflow review: could not create a regular working-tree snapshot before dispatch (stale-path removal, git status, or regular-file validation failed); dirty-tree backstop DISABLED for this dispatch — no after-compare, no auto-restore" >&2
    rm -f "$SNAP_BEFORE" 2>/dev/null
    printf '%s\n' disabled > "$DISABLED_SENTINEL"
  fi
  # Enforce the documented "exit 0 on failure" contract explicitly: without this the function's
  # status is the last command's (the sentinel-write redirect), so a failed redirect would return
  # non-zero and diverge from the guarantee callers rely on.
  return 0
}

cmd_compare_and_restore() {
  local OID="$1"
  if ! mkdir -p .prflow/tmp 2>/dev/null; then
    # Distinct root-cause breadcrumb (mirrors cmd_snapshot): an unwritable .prflow/tmp would
    # otherwise surface only as the generic after-snapshot failure, misattributing a filesystem fault.
    echo "::warning::devflow review: could not create .prflow/tmp for the dirty-tree compare/restore (permissions/read-only-fs/disk-full?); comparison SKIPPED this dispatch — nothing auto-restored" >&2
    return 0
  fi
  if [ -f "$DISABLED_SENTINEL" ]; then
    # before-snapshot failed in snapshot (already surfaced there); backstop disabled this dispatch.
    # Emit an explicit breadcrumb (issue #513): a parent that gates on skip/disabled output cannot
    # tell this DISABLED short-circuit from a silent successful compare without one.
    echo "::warning::devflow review: the dirty-tree backstop was DISABLED for this dispatch (before-snapshot could not be taken); dirty-tree comparison SKIPPED — nothing auto-restored" >&2
  elif [ ! -f "$SNAP_BEFORE" ] ||
       [ -L "$SNAP_BEFORE" ]; then
    echo "::warning::devflow review: the before-dispatch snapshot is missing or no longer a regular non-symlink file; dirty-tree verification SKIPPED this dispatch — possible scratch tampering, nothing auto-restored" >&2
  elif [ "$(git hash-object "$SNAP_BEFORE" 2>/dev/null)" != "$OID" ]; then
    echo "::warning::devflow review: the before-dispatch snapshot no longer matches its orchestrator-held object ID; dirty-tree verification SKIPPED this dispatch — scratch integrity failure, nothing auto-restored" >&2
  elif ! rm -f "$SNAP_AFTER" 2>/dev/null ||
       ! git status --porcelain -z > "$SNAP_AFTER" ||
       [ ! -f "$SNAP_AFTER" ] ||
       [ -L "$SNAP_AFTER" ]; then
    # After-snapshot failed. Do NOT misattribute a git failure as an agent mutation or
    # restore off an empty AFTER — surface a DISTINCT, attributable breadcrumb instead.
    echo "::warning::devflow review: could not create a regular working-tree snapshot after the Phase 3.1 dispatch (stale-path removal, git status, or regular-file validation failed); dirty-tree verification SKIPPED this dispatch — this is NOT an agent mutation" >&2
    rm -f "$SNAP_AFTER" 2>/dev/null
  else
    # Compare the two NUL-delimited (`-z`) snapshots. `cmp` rc: 0 identical, 1 differ, >=2 ERROR.
    # An error must NOT be read as "the tree diverged" and drive a restore off a comparison that
    # never succeeded — fail closed with a distinct, attributable breadcrumb.
    cmp -s "$SNAP_BEFORE" "$SNAP_AFTER"; cmp_rc=$?
    if [ "$cmp_rc" -ge 2 ]; then
      echo "::warning::devflow review: could not compare the before/after working-tree snapshots (cmp errored, rc=$cmp_rc); dirty-tree comparison SKIPPED this dispatch — this is NOT an agent mutation, nothing auto-restored" >&2
    elif [ "$cmp_rc" -eq 1 ]; then
      # Restore set computed BY PATH COLUMN (status prefix stripped), never by whole record — so a
      # path the orchestrator already modified is never checked out even if an agent flips its status
      # byte. Rename/copy (`R`/`C`, a two-record shape) is surfaced, never auto-restored.
      mkdir -p .prflow/tmp
      rm -f ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      if ! printf '%s' '' > ".prflow/tmp/review-dirty-tree-changed-paths" ||
         ! printf '%s' '' > ".prflow/tmp/review-dirty-tree-renamed-paths"; then
        # Repo-local scratch allocation failed (quota/perms). Do NOT proceed: an unbuilt BEFORE
        # membership set reports every path absent and fails OPEN (every dirty path, incl.
        # the orchestrator's own edits, treated as newly-dirty and restored). Fail closed with a
        # distinct breadcrumb and restore nothing.
        echo "::warning::devflow review: could not allocate repo-local scratch files for the dirty-tree restore; dirty-tree restore SKIPPED this dispatch — this is NOT an agent mutation, nothing auto-restored" >&2
        rm -f ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      else
        # BEFORE membership set: every path (incl. rename new+orig), prefix-stripped. `read -r -d ''`
        # reads NUL records so a spaced/special path never splits. Indexed array + linear scan, never
        # `declare -A` (the associative form is bash 4+; this must run under bash 3.2).
        before_extract_rc=0
        before_orig=0
        before_paths=()
        before_untracked=()   # paths whose BEFORE status was ?? — a ??->staged transition (issue #513) is in-scope dirt, not already-dirty
        rec=
        while IFS= read -r -d '' rec; do
          if [ "$before_orig" = 1 ]; then
            before_orig=0
            before_paths+=("$rec")
            continue
          fi
          case "${rec:0:1}" in [RC]) before_orig=1 ;; esac   # index column (X) only: the two-record shape is emitted iff X is R/C
          case "${rec:0:2}" in '??') before_untracked+=("${rec:3}") ;; esac
          before_paths+=("${rec:3}")
        done < "$SNAP_BEFORE" || before_extract_rc=$?
        [ -z "$rec" ] || before_extract_rc=65
        if [ "$before_extract_rc" -ne 0 ]; then
          echo "::warning::devflow review: could not extract the before-snapshot path set (rc=$before_extract_rc); dirty-tree restore SKIPPED this dispatch — nothing auto-restored" >&2
        else
          # AFTER: a rename/copy is surfaced-not-restored; a normal entry is classified by a
          # whole-record exact-string scan of `before_paths` (`[ "$bp" = "${rec:3}" ]`), so a
          # spaced/newline/glob path matches only itself. Absent from BEFORE → restore set; present in
          # BEFORE → not restored, EXCEPT a ??->staged(A) transition, which the in_scope check below
          # treats as in-scope dirt (reverting that check to a member-only test reintroduces the Case-UA bug).
          after_extract_rc=0
          after_orig=0
          rec=
          while IFS= read -r -d '' rec; do
            if [ "$after_orig" = 1 ]; then after_orig=0; continue; fi
            case "${rec:0:1}" in   # index column (X) only: a rename/copy (X = R/C) emits the two-record shape
              [RC]) printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-renamed-paths" || { after_extract_rc=$?; break; }; after_orig=1; continue ;;
            esac
            # Never restore scratch under .prflow/tmp (issue #513): a parent's own in-window OID/snapshot
            # files live there, so restoring them would delete the outer window's own bookkeeping.
            case "${rec:3}" in .prflow/tmp|.prflow/tmp/*) continue ;; esac
            member=0
            for bp in ${before_paths[@]+"${before_paths[@]}"}; do   # `${a[@]+…}` so an empty set is not an unbound-variable error under `set -u`
              if [ "$bp" = "${rec:3}" ]; then member=1; break; fi
            done
            # In-scope: absent from BEFORE (newly dirtied), or a ??->A transition (before_untracked, above) —
            # without the AFTER-index-A check a whole-string membership match would mask ??->A as already-dirty.
            in_scope=0
            if [ "$member" -eq 0 ]; then
              in_scope=1
            elif [ "${rec:0:1}" = "A" ]; then
              for up in ${before_untracked[@]+"${before_untracked[@]}"}; do
                if [ "$up" = "${rec:3}" ]; then in_scope=1; break; fi
              done
            fi
            if [ "$in_scope" -eq 1 ]; then
              printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-changed-paths" || { after_extract_rc=$?; break; } # newly dirtied or ??->A → restore set
            fi
          done < "$SNAP_AFTER" || after_extract_rc=$?
          [ -z "$rec" ] || after_extract_rc=65
          if [ "$after_extract_rc" -ne 0 ]; then
            echo "::warning::devflow review: could not extract the after-snapshot restore set (rc=$after_extract_rc); dirty-tree restore SKIPPED this dispatch — nothing auto-restored" >&2
          else
            RENAMED_NAMES=$(tr '\0' ' ' < ".prflow/tmp/review-dirty-tree-renamed-paths")
            if [ ! -s ".prflow/tmp/review-dirty-tree-changed-paths" ]; then
              if [ -n "$RENAMED_NAMES" ]; then
                # The only divergence is a rename/copy: surfaced, never auto-restored (index surgery needed).
                echo "::warning::devflow review: a Phase 3.1 review-agent dispatch renamed/copied tracked path(s) [ ${RENAMED_NAMES}]; not auto-restored (a staged rename needs index surgery) — left for the Step 2.6 shadow and the human" >&2
              else
                # Divergence with an EMPTY restore set and no rename — the by-path set can be empty
                # from an already-dirty path's status-byte change, a dirty->clean transition, or a
                # divergence confined to skipped .prflow/tmp scratch; the cause cannot be determined here.
                echo "::warning::devflow review: a Phase 3.1 review-agent dispatch diverged the working tree but the by-path restore set is empty (an already-dirty path's status byte changed, a dirty->clean transition, or the only differing paths were skipped .prflow/tmp scratch — the cause cannot be determined here); nothing auto-restored — left for the Step 2.6 shadow and the human" >&2
              fi
            else
              # Restore the snapshot-delta paths per-path from HEAD — NOT `git checkout -- "$p"`, which
              # restores from the INDEX and re-materializes a STAGED mutation while exiting 0 (fail-open).
              # Trust the TREE STATE not the exit code: re-check `git status` and breadcrumb iff still dirty (an untracked file is never auto-deleted).
              CHANGED_NAMES=$(tr '\0' ' ' < ".prflow/tmp/review-dirty-tree-changed-paths")
              echo "::warning::devflow review: a Phase 3.1 review-agent dispatch modified the working tree (advisory review agents must never mutate it); affected paths: [ ${CHANGED_NAMES}]${RENAMED_NAMES:+ (plus surfaced-not-restored rename/copy: [ ${RENAMED_NAMES}])}; recording an Important finding and attempting best-effort restore of the snapshot delta (per-path outcome in the warnings below)" >&2
              while IFS= read -r -d '' p; do
                [ -n "$p" ] || continue
                restore_err=$(git checkout HEAD -- "$p" 2>&1)
                # Check the confirmation read's OWN exit status, not just its output: a failed
                # `git status` prints nothing and would otherwise read as "clean, restore confirmed"
                # (fail-open). `if !` fails closed — an unverifiable state is reported, never assumed OK.
                if ! post_status=$(git status --porcelain -- "$p" 2>/dev/null) || [ -n "$post_status" ]; then
                  echo "::warning::devflow review: path '$p' still dirty after restore attempt, or its post-restore state could not be confirmed (git status rc≠0) (e.g. an untracked or staged-new file the agent created — never auto-deleted; git said: ${restore_err:-none}) — left as-is for human inspection" >&2
                fi
              done < ".prflow/tmp/review-dirty-tree-changed-paths"
            fi
          fi
        fi
        rm -f ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      fi
    fi
    # cmp_rc == 0: the snapshots are identical — nothing changed during the dispatch window.
    rm -f "$SNAP_AFTER" 2>/dev/null
  fi
  # Clean up fixed repo-local snapshot state after the dispatch.
  rm -f "$SNAP_BEFORE" "$DISABLED_SENTINEL" 2>/dev/null
  # Enforce the documented always-exit-0 contract explicitly (symmetric with cmd_snapshot): without
  # this the function's status is the cleanup rm's, which can return non-zero (RO fs / immutable bit).
  return 0
}

cmd_engine_setup() {
  local record oid rc=0
  record="$(python3 "$ENGINE_IO" setup-prepare "$@")" || rc=$?
  case "$record" in
    record:*) ;;
    *)
      # `empty`, a fail-closed stop, or a usage error: the sibling already said which.
      [ -n "$record" ] && printf '%s\n' "$record"
      return "$rc"
      ;;
  esac
  oid="$(cmd_snapshot)"
  python3 "$ENGINE_IO" setup-emit --record "${record#record:}" --snapshot-oid "$oid"
}

cmd_loop_setup() {
  # Shell-only work here (issue #894 AC5): the run key from compose-run-key.sh (passed
  # through verbatim, empty when it printed nothing) and the four config reads. Each config
  # read is --scalar (so an array/object resolves as unset, never coerced to a scalar). The
  # three int/enum reads carry NO default, so the producer distinguishes a resolver failure
  # (rc 2) from an absent key (rc 1) from a present value (rc 0) and applies each key's own
  # clamp/default. The telemetry read DOES pass the `true` default, mirroring the pre-#894
  # loop-exit.md `config-get.sh ... true` read: config-get.sh owns the schema default (true)
  # and the #2035 telemetry.enabled master inheritance on the miss path, so a default-config
  # repo (key unset) resolves to true, not the producer's fail-closed false — keeping
  # telemetry (the effectiveness trace and permission-denial forensics) ON by default. Read
  # each rc on its own line: `local x=$(…)` would mask the substitution's status behind
  # `local`'s own.
  local run_key mi mi_rc ft ft_rc fb fb_rc et et_rc
  run_key="$("$LOOP_COMPOSE_RUN_KEY")" || run_key=""
  mi="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.max_iterations)"; mi_rc=$?
  ft="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.fix_severity_threshold)"; ft_rc=$?
  fb="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.fix_below_threshold_iterations)"; fb_rc=$?
  et="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.efficiency_telemetry_enabled true)"; et_rc=$?
  python3 "$LOOP_IO" loop-setup \
    --run-key "$run_key" \
    --cfg-max-iterations "$mi" --cfg-max-iterations-rc "$mi_rc" \
    --cfg-fix-severity-threshold "$ft" --cfg-fix-severity-threshold-rc "$ft_rc" \
    --cfg-fix-below-threshold-iterations "$fb" --cfg-fix-below-threshold-iterations-rc "$fb_rc" \
    --cfg-efficiency-telemetry-enabled "$et" --cfg-efficiency-telemetry-enabled-rc "$et_rc" \
    "$@"
}

# ── entry-open / entry-close (issue #898): the fix loop's per-entry bracket ──────────────
# One JSON line per call. Every value reaches python3 as an argv token (`key=value`; an `@key=`
# value is a newline-joined list, a `#key=` value an integer), so no bash-side escaping exists.
emit_json() {
  python3 -c '
import json, sys
sys.stdout.reconfigure(newline="\n")
out = {}
for tok in sys.argv[1:]:
    key, _, val = tok.partition("=")
    if key.startswith("@"):
        out[key[1:]] = [] if val == "" else val.split("\n")
    elif key.startswith("#"):
        out[key[1:]] = int(val)
    elif key.startswith("%"):
        out[key[1:]] = json.loads(val)
    else:
        out[key] = val
print(json.dumps(out))
' "$@"
}

entry_error() {  # STEP REASON EXIT
  emit_json status=error "step=$1" "reason=$2"
  return "$3"
}

# Parse the bracket's named operands into ENTRY_RUN_ROOT / ENTRY_KIND / ENTRY_ITER / ENTRY_HEAD /
# ENTRY_BRANCH and derive the entry's scratch paths. `$1` names the arm (open|close) so the
# close-only operands are required only there. Prints the error line itself; returns 2 on a
# usage error so the caller can `return` it.
parse_entry_args() {
  local arm="$1"; shift
  ENTRY_RUN_ROOT=""; ENTRY_KIND=""; ENTRY_ITER=""; ENTRY_HEAD=""; ENTRY_BRANCH=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --run-root)  [ "$#" -ge 2 ] || { entry_error arguments "--run-root needs a value" 2; return 2; }; ENTRY_RUN_ROOT="$2"; shift 2 ;;
      --entry)     [ "$#" -ge 2 ] || { entry_error arguments "--entry needs a value" 2; return 2; }; ENTRY_KIND="$2"; shift 2 ;;
      --iteration) [ "$#" -ge 2 ] || { entry_error arguments "--iteration needs a value" 2; return 2; }; ENTRY_ITER="$2"; shift 2 ;;
      --head)      [ "$#" -ge 2 ] || { entry_error arguments "--head needs a value" 2; return 2; }; ENTRY_HEAD="$2"; shift 2 ;;
      --branch)    [ "$#" -ge 2 ] || { entry_error arguments "--branch needs a value" 2; return 2; }; ENTRY_BRANCH="$2"; shift 2 ;;
      *) entry_error arguments "unknown operand '$1'" 2; return 2 ;;
    esac
  done
  # An unsubstituted `<placeholder>` in any operand is a prose slot the caller never filled.
  case "${ENTRY_RUN_ROOT}${ENTRY_KIND}${ENTRY_ITER}${ENTRY_HEAD}${ENTRY_BRANCH}" in
    *'<'*|*'>'*) entry_error arguments "an operand carries an unsubstituted <placeholder>" 2; return 2 ;;
  esac
  case "$ENTRY_KIND" in
    step1)  ENTRY_TAG=s1 ;;
    shadow) ENTRY_TAG=shadow ;;
    *) entry_error arguments "--entry must be step1 or shadow (got '${ENTRY_KIND}')" 2; return 2 ;;
  esac
  case "$ENTRY_ITER" in
    ''|*[!0-9]*|0*) entry_error arguments "--iteration must be a positive integer (got '${ENTRY_ITER}')" 2; return 2 ;;
  esac
  if [ "$arm" = close ]; then
    case "$ENTRY_HEAD" in
      *[!0-9a-f]*|'') entry_error arguments "--head must be a 40-hex commit id" 2; return 2 ;;
    esac
    [ "${#ENTRY_HEAD}" -eq 40 ] || { entry_error arguments "--head must be a 40-hex commit id" 2; return 2; }
    [ -n "$ENTRY_BRANCH" ] || { entry_error arguments "--branch needs a non-empty value" 2; return 2; }
  fi
  [ -n "$ENTRY_RUN_ROOT" ] || { entry_error run-root "--run-root is required" 2; return 2; }
  [ -d "$ENTRY_RUN_ROOT" ] || { entry_error run-root "run root '${ENTRY_RUN_ROOT}' is not a directory" 2; return 2; }
  SNAP_BEFORE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-before"
  SNAP_AFTER=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-after"
  DISABLED_SENTINEL=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-disabled"
  ENTRY_OID_FILE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-oid.txt"
  return 0
}

cmd_entry_open() {
  parse_entry_args open "$@" || return $?
  local f deleted="" survivor="" oid snapshot nl=$'\n'
  # Re-entrant freshness: the entry's Phase 0.2 rebuilds the cache at HEAD. Deleting an absent
  # cache is a no-op, so the first entry needs no special arm. Deletion only — never a rebuild.
  for f in "$ENTRY_RUN_ROOT/diff.patch" "$ENTRY_RUN_ROOT"/batch-*.patch; do
    [ -e "$f" ] || continue
    rm -f "$f"
    deleted="${deleted}${deleted:+$nl}${f#"$ENTRY_RUN_ROOT"/}"
  done
  for f in "$ENTRY_RUN_ROOT/diff.patch" "$ENTRY_RUN_ROOT"/batch-*.patch; do
    [ -e "$f" ] && survivor="${f#"$ENTRY_RUN_ROOT"/}"
  done
  if [ -n "$survivor" ]; then
    entry_error cache "cache file '${survivor}' survived deletion" 1
    return 1
  fi
  # The entry's scratch lives under .prflow/tmp/review/ (cmd_snapshot creates only .prflow/tmp).
  mkdir -p .prflow/tmp/review 2>/dev/null || :
  oid="$(cmd_snapshot)"
  if [ -n "$oid" ]; then snapshot=taken; else snapshot=disabled; fi
  # The OID file is what entry-close (and the fallback compare fence) reads back after the
  # dispatch — written empty on a disabled snapshot so the close arm fails closed on it.
  if ! printf '%s' "$oid" > "$ENTRY_OID_FILE"; then
    echo "::warning::devflow review: could not write ${ENTRY_OID_FILE}; the close arm will read it as missing and block" >&2
  fi
  emit_json status=ok "entry=$ENTRY_KIND" "#iteration=$ENTRY_ITER" "@cache_deleted=$deleted" \
    "snapshot=$snapshot" "oid=$oid" "oid_file=$ENTRY_OID_FILE"
}

cmd_entry_close() {
  parse_entry_args close "$@" || return $?
  local branch oid restore="" detail="" token="" mexit=0 line="" rc nl=$'\n'
  # 1. Post-return branch guard: nothing else runs on a mismatch (the loop takes the guard's
  #    mismatch arms and re-runs this call once on its restored arm).
  if ! branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || [ -z "$branch" ]; then
    # An unreadable checkout is neither a match nor a mismatch (error-handling.md's
    # *unestablished* reading): the loop stops, never checks anything out.
    emit_json status=branch-unestablished "expected=$ENTRY_BRANCH"
    return 0
  fi
  if [ "$branch" != "$ENTRY_BRANCH" ]; then
    emit_json status=branch-mismatch "branch=$branch" "expected=$ENTRY_BRANCH"
    return 0
  fi
  # 2. Compare-and-restore against the persisted OID, fail closed on every missing operand.
  #    The compare prints nothing on stdout, so its stderr breadcrumbs are captured in a
  #    variable — no scratch file is created between the before and after snapshots.
  if [ ! -f "$ENTRY_OID_FILE" ] || [ -L "$ENTRY_OID_FILE" ]; then
    restore=blocked; detail="OID file ${ENTRY_OID_FILE} is missing"
  elif ! oid="$(cat "$ENTRY_OID_FILE" 2>/dev/null)" || [ -z "$oid" ]; then
    restore=blocked; detail="OID file ${ENTRY_OID_FILE} is empty or unreadable"
  elif [ -e "$OUTER_DISABLED_SENTINEL" ]; then
    restore=blocked; detail="outer sentinel ${OUTER_DISABLED_SENTINEL} present at compare start"
  else
    detail="$(cmd_compare_and_restore "$oid" 2>&1)"
    case "$detail" in
      '') restore=clean ;;
      *SKIPPED*|*DISABLED*|*'still dirty after restore attempt'*) restore=blocked ;;
      *'nothing auto-restored'*|*'not auto-restored'*) restore=not-restored ;;
      *'modified the working tree'*) restore=restored ;;
      *) restore=blocked ;;   # an unrecognized breadcrumb never reads as clean
    esac
  fi
  # 3. Evidence: bind, then grade, relaying check-evidence's line 1 and exit code verbatim.
  rc=0
  line="$(python3 "$LOOP_VERDICT_MARKER" write-active-entry-binding --run-root "$ENTRY_RUN_ROOT" \
    --entry "$ENTRY_KIND" --iteration "$ENTRY_ITER" --head "$ENTRY_HEAD" 2>&1)" || rc=$?
  if [ "$rc" -eq 0 ]; then
    line="$(python3 "$LOOP_VERDICT_MARKER" check-evidence --run-root "$ENTRY_RUN_ROOT" \
      --entry "$ENTRY_KIND" --iteration "$ENTRY_ITER" --head "$ENTRY_HEAD" 2>/dev/null)" || mexit=$?
    line="${line%%"$nl"*}"
    token="${line%% *}"
  else
    # The binding refused (an unrecovered other-entry grade, a missing marker, argparse): relay
    # its first output line so the loop's recovery narrative names the cause; no token.
    mexit="$rc"
    line="write-active-entry-binding exited ${rc}: ${line%%"$nl"*}"
  fi
  emit_json status=ok "branch=$branch" "restore=$restore" "@restore_detail=$detail" \
    "%evidence=$(emit_json "token=$token" "#exit=$mexit" "line=$line")"
}

main() {
  if [ "$#" -lt 1 ]; then
    echo "usage: review-dirty-tree.sh snapshot [BEFORE AFTER DISABLED] | compare-and-restore OID [BEFORE AFTER DISABLED]" >&2
    return 2
  fi
  case "$1" in
    snapshot)
      # Optional literal path operands (issue #513) point scratch at per-dispatch files without a
      # leading VAR= assignment, which the cloud matcher denies. Precedence: see the CONTRACT docstring.
      if [ "$#" -eq 1 ]; then
        :
      elif [ "$#" -eq 4 ] && [ -n "$2" ] && [ -n "$3" ] && [ -n "$4" ]; then
        SNAP_BEFORE="$2"; SNAP_AFTER="$3"; DISABLED_SENTINEL="$4"
      else
        echo "usage: review-dirty-tree.sh snapshot [BEFORE AFTER DISABLED]" >&2
        return 2
      fi
      cmd_snapshot
      ;;
    compare-and-restore)
      # The restore-authorising object ID is a required literal argument held by the
      # orchestrator — never recovered from agent-writable scratch (issue #2082 AC4).
      # Optional trailing before/after/disabled operands mirror snapshot (issue #513).
      if [ "$#" -eq 2 ] && [ -n "$2" ]; then
        :
      elif [ "$#" -eq 5 ] && [ -n "$2" ] && [ -n "$3" ] && [ -n "$4" ] && [ -n "$5" ]; then
        SNAP_BEFORE="$3"; SNAP_AFTER="$4"; DISABLED_SENTINEL="$5"
      else
        echo "usage: review-dirty-tree.sh compare-and-restore OID [BEFORE AFTER DISABLED]" >&2
        return 2
      fi
      cmd_compare_and_restore "$2"
      ;;
    engine-setup)
      shift
      cmd_engine_setup "$@"
      ;;
    engine-return)
      shift
      python3 "$ENGINE_IO" return "$@"
      ;;
    view-materialize)
      # issue #851 source-view producer (placement rationale in the header block above).
      shift
      python3 "$ENGINE_IO" view-materialize "$@"
      ;;
    loop-setup)
      # issue #894 fix-loop one-call setup (host/sibling split in cmd_loop_setup below).
      shift
      cmd_loop_setup "$@"
      ;;
    branch-sync)
      # issue #894 Step 0.5 PR-head comparand read: no checkout, no git-state change.
      shift
      python3 "$LOOP_IO" branch-sync "$@"
      ;;
    entry-open)
      # issue #898 fix-loop entry bracket (contract in the header block above).
      shift
      cmd_entry_open "$@"
      ;;
    entry-close)
      shift
      cmd_entry_close "$@"
      ;;
    *)
      echo "review-dirty-tree.sh: unknown subcommand '$1' (expected: snapshot | compare-and-restore | engine-setup | engine-return | view-materialize | loop-setup | branch-sync | entry-open | entry-close)" >&2
      return 2
      ;;
  esac
}

main "$@"

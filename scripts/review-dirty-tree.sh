#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# review-dirty-tree.sh SUBCOMMAND … — the review engine's dirty-tree backstop
# (issue #2082). Owns the whole snapshot/authenticate/compare/restore loop: Phase 0.2's
# engine-setup takes the snapshot before the engine dispatches any agent and the
# Phase 3.2 fence runs the compare, so the window covers the agents dispatched between
# the two and none dispatched later (Phase 4.1's re-verification).
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
# read from agent-writable scratch (issue #2082 AC4). The loop's `entry-close` is the one
# exception by design: it reads the OID file entry-open wrote, adding no trust boundary the
# loop does not carry.
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
#   engine-setup ARGS… / engine-brief ARGS… / engine-return ARGS…
#     The review engine's one-call setup, review brief and return-file assembly, hosted here because this head is granted on every
#     tier; the work and the argument contract live in the sibling review-engine-io.py. engine-setup
#     reads `.base_branch` through config-get.sh and, without --run-id, mints the run key through
#     compose-run-key.sh (the same seams loop-setup uses), then takes the `snapshot` LAST — after
#     the diff cache and views are published, before the engine dispatches any child — and its
#     object ID reaches stdout only. Exit: the sibling's (0 ok/empty, 1 stop, 2 usage).
#   loop-setup [--pr N] / branch-sync --pr N
#     The review-and-fix loop's one-call setup and PR-head branch-sync (issue #894), hosted
#     here for the same granted-head reason; the work lives in the sibling review-loop-io.py.
#     loop-setup: this host runs compose-run-key.sh and the four config-get.sh reads (so the
#     producer executes no .sh, AC5) and hands the values and exit codes to the producer, which
#     applies the loop's clamps/breadcrumbs, resolves slug and run_dir by the same rule
#     engine-setup uses, creates the run dir, persists loop-setup.json and prints one JSON line;
#     it runs no gh. branch-sync: the producer runs the git/gh reads and prints the comparison —
#     no checkout, no git-state change. Exit: the sibling's (0 ok, 1 error, 2 usage).
#   entry-open --contract 3 --run-root DIR --entry step1|shadow --iteration N
#   entry-close --contract 3 --run-root DIR --entry step1|shadow --iteration N --branch NAME
#     The review-and-fix loop's per-engine-entry bracket (issue #898), one call each side of a
#     dispatch, printing one JSON line on stdout. Shadow entry-open first removes DIR-shadow;
#     then entry-open deletes the entry's stale inputs
#     and outputs — DIR/diff.patch, every DIR/batch-*.patch, iteration N's
#     checklist-iter-N.json / checklist-iter-N.items / verification-iter-N.json, DIR/verdicts/iter-N/, every
#     DIR/p3-*.md, DIR/phase-log, DIR/verdict-body.md, DIR/verdict-draft.md,
#     DIR/review-wp-draft.md and the entry's DIR/engine-return-<entry>-iter-N.json — so
#     the entry's Phase 0.2 rebuilds the diff at HEAD and
#     entry-close grades only what this entry wrote; then takes the `snapshot` to
#     .prflow/tmp/review/dt-<s1|shadow>-N-{before,after,disabled}, writes the object ID to
#     .prflow/tmp/review/dt-<s1|shadow>-N-oid.txt, the working-tree and index tree IDs to
#     .prflow/tmp/review/dt-<s1|shadow>-N-content.txt (empty when they cannot be recorded, the
#     cause then in dt-<s1|shadow>-N-content-err.txt) and HEAD to …-head.txt, and on a step1
#     entry at N >= 2 runs review-loop-io.py `prior`. Line: {status:"ok", entry, iteration,
#     cache_deleted:[…], snapshot:"taken"|"disabled", oid, oid_file, prior:{…}|null}.
#     entry-close is the sibling review-loop-io.py `entry-close` (branch guard, the restore of
#     tracked files the engine changed, shadow migration from DIR-shadow into DIR, the retained
#     evidence copies, the engine return's grade and the entry's evidence grade).
#     Errors print {status:"error", step, reason}: `arguments`/`run-root` exit 2;
#     `cache` (a survivor after deletion), `content` (a content record it can neither replace
#     nor clear), `head` (HEAD not recorded), `run-dir` (shadow removal/migration failed) and
#     `repo-root` (git or the environment unavailable) exit 1. Migration errors retain the restoration fields; an unestablished dirty check
#     still requires the loop to stop. Without `--contract 3` both arms
#     refuse (exit 2).
#
# Portability: bash 3.2 / BSD userland, no GNU-only flags (indexed-array linear scan,
# never `declare -A`; NUL-safe `read -r -d ''`).

set -u

SNAP_BEFORE="${GIT_SNAP_BEFORE:-.prflow/tmp/review-dirty-tree-before}"
SNAP_AFTER="${GIT_SNAP_AFTER:-.prflow/tmp/review-dirty-tree-after}"
DISABLED_SENTINEL=".prflow/tmp/review-dirty-tree-disabled"
ENGINE_IO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/review-engine-io.py"
LOOP_IO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/review-loop-io.py"
# The loop-setup host runs compose-run-key.sh and config-get.sh itself (issue #894); the
# producer never executes a .sh (AC5). Both resolve script-relative by default; the
# LOOP_COMPOSE_RUN_KEY / LOOP_CONFIG_GET env seam is retained INTERNALLY so the project's
# own suite can point them at per-test stubs, exactly like the GIT_SNAP_* seam above — the
# emitted skill command names neither.
LOOP_COMPOSE_RUN_KEY="${LOOP_COMPOSE_RUN_KEY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/compose-run-key.sh}"
LOOP_CONFIG_GET="${LOOP_CONFIG_GET:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/config-get.sh}"

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
    echo "::warning::devflow review: could not create a regular working-tree snapshot after this dispatch window (stale-path removal, git status, or regular-file validation failed); dirty-tree verification SKIPPED this dispatch — this is NOT an agent mutation" >&2
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
          case "${rec:0:2}" in [RC]?|?[RC]) before_orig=1 ;; esac   # either column: a work-tree (intent-to-add) rename is also two records
          case "${rec:0:2}" in '??') before_untracked+=("${rec:3}") ;; esac
          before_paths+=("${rec:3}")
        done < "$SNAP_BEFORE" || before_extract_rc=$?
        [ -z "$rec" ] || before_extract_rc=65
        if [ "$before_extract_rc" -ne 0 ]; then
          echo "::warning::devflow review: could not extract the before-snapshot path set (rc=$before_extract_rc); dirty-tree restore SKIPPED this dispatch — nothing auto-restored" >&2
        else
          # Deliberately unlike review-loop-io.py `_engine_records` (which resets a rename's original): left for a human.
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
            case "${rec:0:2}" in   # either column: a work-tree (intent-to-add) rename is also two records
              [RC]?|?[RC]) printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-renamed-paths" || { after_extract_rc=$?; break; }; after_orig=1; continue ;;
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
                echo "::warning::devflow review: this dispatch window renamed/copied tracked path(s) [ ${RENAMED_NAMES}]; not auto-restored — left as-is for human inspection" >&2
              else
                # Divergence with an EMPTY restore set and no rename — the by-path set can be empty
                # from an already-dirty path's status-byte change, a dirty->clean transition, or a
                # divergence confined to skipped .prflow/tmp scratch; the cause cannot be determined here.
                echo "::warning::devflow review: this dispatch window diverged the working tree but the by-path restore set is empty (an already-dirty path's status byte changed, a dirty->clean transition, or the only differing paths were skipped .prflow/tmp scratch — the cause cannot be determined here); nothing auto-restored — left as-is for human inspection" >&2
              fi
            else
              # Restore the snapshot-delta paths per-path from HEAD — NOT `git checkout -- "$p"`, which
              # restores from the INDEX and re-materializes a STAGED mutation while exiting 0 (fail-open).
              # Trust the TREE STATE not the exit code: re-check `git status` and breadcrumb iff still dirty (an untracked file is never auto-deleted).
              CHANGED_NAMES=$(tr '\0' ' ' < ".prflow/tmp/review-dirty-tree-changed-paths")
              echo "::warning::devflow review: this dispatch window modified the working tree (advisory review agents must never mutate it); affected paths: [ ${CHANGED_NAMES}]${RENAMED_NAMES:+ (plus surfaced-not-restored rename/copy: [ ${RENAMED_NAMES}])}; attempting best-effort restore of the snapshot delta (a path the restore leaves dirty is named below)" >&2
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
  # The host runs the .sh work (the producer executes none): the configured base read, and
  # the run key when the caller passed no --run-id.
  local record oid rc=0 a cfg cfg_rc=0 run_key key_rc=0 have_run_id=0
  for a in "$@"; do case "$a" in --run-id|--run-id=*) have_run_id=1 ;; esac; done
  cfg="$("$LOOP_CONFIG_GET" --scalar .base_branch main)" || cfg_rc=$?
  set -- "$@" --cfg-base-branch "$cfg" --cfg-base-branch-rc "$cfg_rc"
  if [ "$have_run_id" -eq 0 ]; then
    run_key="$("$LOOP_COMPOSE_RUN_KEY")" || key_rc=$?
    set -- "$@" --run-id "$run_key" --run-key-rc "$key_rc"
  fi
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
  # clamp/default. The effectiveness read DOES pass the `false` fallback: an unset key
  # then resolves to false at rc 0 (opt-in default) instead of the miss path, so the
  # producer prints no "not configured; using default" breadcrumb every run; config-get.sh
  # still applies the #2035 telemetry.enabled master inheritance on that path. Read
  # each rc on its own line: `local x=$(…)` would mask the substitution's status behind
  # `local`'s own.
  local run_key mi mi_rc ft ft_rc fb fb_rc et et_rc
  run_key="$("$LOOP_COMPOSE_RUN_KEY")" || run_key=""
  mi="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.max_iterations)"; mi_rc=$?
  ft="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.fix_severity_threshold)"; ft_rc=$?
  fb="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.fix_below_threshold_iterations)"; fb_rc=$?
  et="$("$LOOP_CONFIG_GET" --scalar .prflow_review_and_fix.efficiency_telemetry_enabled false)"; et_rc=$?
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

# Parse entry-open's named operands into ENTRY_RUN_ROOT / ENTRY_KIND / ENTRY_ITER and derive the
# entry's scratch paths. Prints the error line itself; returns 2 on a usage error.
parse_entry_args() {
  local contract=""
  ENTRY_RUN_ROOT=""; ENTRY_KIND=""; ENTRY_ITER=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --contract)  [ "$#" -ge 2 ] || { entry_error arguments "--contract needs a value" 2; return 2; }; contract="$2"; shift 2 ;;
      --run-root)  [ "$#" -ge 2 ] || { entry_error arguments "--run-root needs a value" 2; return 2; }; ENTRY_RUN_ROOT="$2"; shift 2 ;;
      --entry)     [ "$#" -ge 2 ] || { entry_error arguments "--entry needs a value" 2; return 2; }; ENTRY_KIND="$2"; shift 2 ;;
      --iteration) [ "$#" -ge 2 ] || { entry_error arguments "--iteration needs a value" 2; return 2; }; ENTRY_ITER="$2"; shift 2 ;;
      *) entry_error arguments "unknown operand '$1'" 2; return 2 ;;
    esac
  done
  [ "$contract" = 3 ] || { entry_error arguments "--contract 3 is required (this helper retired the earlier entry-open contracts)" 2; return 2; }
  # An unsubstituted `<placeholder>` in any operand is a prose slot the caller never filled.
  case "${ENTRY_RUN_ROOT}${ENTRY_KIND}${ENTRY_ITER}" in
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
  [ -n "$ENTRY_RUN_ROOT" ] || { entry_error run-root "--run-root is required" 2; return 2; }
  [ -d "$ENTRY_RUN_ROOT" ] || { entry_error run-root "run root '${ENTRY_RUN_ROOT}' is not a directory" 2; return 2; }
  SNAP_BEFORE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-before"
  SNAP_AFTER=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-after"
  DISABLED_SENTINEL=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-disabled"
  ENTRY_OID_FILE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-oid.txt"
  ENTRY_HEAD_FILE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-head.txt"
  ENTRY_CONTENT_FILE=".prflow/tmp/review/dt-${ENTRY_TAG}-${ENTRY_ITER}-content.txt"
  return 0
}

# Write the entry's content record: "<working-tree tree> <index tree>". `git stash create` prints
# nothing when no tracked path but a submodule differs from HEAD; then HEAD's tree and the index's
# own, so a staged gitlink is not read as an engine change. Never `git commit-tree`: with no
# identity configured it can fail, where `git stash create` falls back to a built-in one (an
# empty `user.name` fails both). A record it can neither replace nor clear fails the entry (`content`,
# exit 1), since entry-close would restore to an earlier run's content.
record_entry_content() {
  local stash wt="" idx="" cause="" said="" err="${ENTRY_CONTENT_FILE%.txt}-err.txt" errto
  rm -f "$ENTRY_CONTENT_FILE" "$err" 2>/dev/null
  # A redirect that cannot be opened skips its command, so an unwritable err file goes unused.
  errto="$err"
  : 2>/dev/null > "$err" || errto=/dev/null
  if ! stash="$(git stash create 2>"$errto")"; then
    cause='git stash create failed'; IFS= read -r said 2>/dev/null < "$errto" || :
  elif [ -n "$stash" ]; then
    { wt="$(git rev-parse --verify -q "${stash}^{tree}")" && idx="$(git rev-parse --verify -q "${stash}^2^{tree}")"; } \
      || cause='git rev-parse could not resolve the stash trees'
  elif ! wt="$(git rev-parse --verify -q 'HEAD^{tree}')"; then
    cause="git rev-parse could not resolve HEAD's tree"
  elif ! idx="$(git write-tree 2>"$errto")"; then
    cause='git write-tree failed'; IFS= read -r said 2>/dev/null < "$errto" || :
  fi
  if [ -z "$cause" ]; then
    if printf '%s %s\n' "$wt" "$idx" 2>/dev/null > "$ENTRY_CONTENT_FILE"; then
      rm -f "$err" 2>/dev/null
      return 0
    fi
    cause='the record write failed'
  fi
  printf '%s\n' "${cause}${said:+: $said}" 2>/dev/null > "$err" || :
  : 2>/dev/null > "$ENTRY_CONTENT_FILE"
  if [ -f "$ENTRY_CONTENT_FILE" ] && [ -s "$ENTRY_CONTENT_FILE" ]; then
    entry_error content "could not replace or clear ${ENTRY_CONTENT_FILE}, which may hold an earlier run's content" 1
    return 1
  fi
  echo "::warning::devflow review: could not record the working-tree and index content in ${ENTRY_CONTENT_FILE} (${cause}${said:+: $said}); entry-close falls back to the status snapshot alone" >&2
  return 0
}

cmd_entry_open() {
  parse_entry_args "$@" || return $?
  local f deleted="" survivor="" oid snapshot nl=$'\n' r="$ENTRY_RUN_ROOT" n="$ENTRY_ITER"
  if [ "$ENTRY_KIND" = shadow ]; then
    python3 "$LOOP_IO" shadow-open --run-root "$r" || return $?
  fi
  # Freshness: the entry's Phase 0.2 rebuilds the diff at HEAD, and the entry's own checklist,
  # item files, verification, verifier files, Phase 3 blocks, phase-log records, report drafts,
  # report and return file replace this iteration's, so entry-close grades only what this entry
  # wrote.
  # Deleting an absent file is a no-op; deletion only.
  for f in "$r/diff.patch" "$r"/batch-*.patch "$r/checklist-iter-$n.json" "$r/checklist-iter-$n.items" \
           "$r/verification-iter-$n.json" "$r/verdicts/iter-$n" "$r"/p3-*.md "$r/phase-log" \
           "$r/verdict-body.md" "$r/verdict-draft.md" "$r/review-wp-draft.md" \
           "$r/engine-return-$ENTRY_KIND-iter-$n.json"; do
    [ -e "$f" ] || continue
    rm -rf "$f"
    deleted="${deleted}${deleted:+$nl}${f#"$r"/}"
    [ -e "$f" ] && survivor="${f#"$r"/}"
  done
  if [ -n "$survivor" ]; then
    entry_error cache "cache file '${survivor}' survived deletion" 1
    return 1
  fi
  # The entry's scratch lives under .prflow/tmp/review/ (cmd_snapshot creates only .prflow/tmp).
  mkdir -p .prflow/tmp/review 2>/dev/null || :
  oid="$(cmd_snapshot)"
  if [ -n "$oid" ]; then snapshot=taken; else snapshot=disabled; fi
  # The OID file is what entry-close reads back after the dispatch — written empty on a
  # disabled snapshot so the close arm reports that no snapshot was taken.
  if ! printf '%s' "$oid" > "$ENTRY_OID_FILE"; then
    echo "::warning::devflow review: could not write ${ENTRY_OID_FILE}; the close arm cannot verify this entry's snapshot" >&2
  fi
  record_entry_content || return 1
  # The HEAD the engine must produce its diff at; entry-close compares the return against it.
  if ! git rev-parse HEAD > "$ENTRY_HEAD_FILE"; then
    entry_error head "could not record HEAD in ${ENTRY_HEAD_FILE}" 1
    return 1
  fi
  local prior=null prior_rc=0
  if [ "$ENTRY_KIND" = step1 ] && [ "$n" -ge 2 ]; then
    prior="$(python3 "$LOOP_IO" prior --run-root "$r" --iteration "$n")" || prior_rc=$?
    case "$prior" in
      '{"diff_head"'*) : ;;
      *) prior="{\"diff_head\": null, \"findings\": null, \"count\": 0, \"warnings\": [\"the prior-iteration reader printed no record (exit ${prior_rc})\"]}" ;;
    esac
  fi
  emit_json status=ok "entry=$ENTRY_KIND" "#iteration=$ENTRY_ITER" "@cache_deleted=$deleted" \
    "snapshot=$snapshot" "oid=$oid" "oid_file=$ENTRY_OID_FILE" "%prior=$prior"
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
    engine-brief)
      shift
      python3 "$ENGINE_IO" brief "$@"
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
      python3 "$LOOP_IO" entry-close "$@"
      ;;
    *)
      echo "review-dirty-tree.sh: unknown subcommand '$1' (expected: snapshot | compare-and-restore | engine-setup | engine-brief | engine-return | loop-setup | branch-sync | entry-open | entry-close)" >&2
      return 2
      ;;
  esac
}

main "$@"

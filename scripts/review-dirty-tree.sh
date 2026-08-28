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
# read from agent-writable scratch (issue #2082 AC4).
#
# CONTRACT — subcommands:
#   snapshot
#     Capture the authenticated `-z` before-snapshot to $GIT_SNAP_BEFORE. On success
#     print the snapshot's git object ID on stdout and exit 0; the orchestrator records
#     it as {GIT_SNAP_BEFORE_OID}. On failure write the fixed repo-local disabled
#     sentinel (.prflow/tmp/review-dirty-tree-disabled) plus a `::warning::` breadcrumb
#     on stderr and exit 0 with NO object ID on stdout (the orchestrator treats an
#     absent OID as a failed snapshot).
#   compare-and-restore OID
#     Compare the after-snapshot against the before-snapshot authenticated to OID and
#     restore only the snapshot-delta paths. Short-circuits on the disabled sentinel.
#     Emits the same `::warning::` breadcrumbs the inline fence did. Exit 0.
#
# Portability: bash 3.2 / BSD userland, no GNU-only flags (indexed-array linear scan,
# never `declare -A`; NUL-safe `read -r -d ''`).

set -u

SNAP_BEFORE="${GIT_SNAP_BEFORE:-.prflow/tmp/review-dirty-tree-before}"
SNAP_AFTER="${GIT_SNAP_AFTER:-.prflow/tmp/review-dirty-tree-after}"
DISABLED_SENTINEL=".prflow/tmp/review-dirty-tree-disabled"

cmd_snapshot() {
  mkdir -p .prflow/tmp
  # Snapshot captured to a NUL-delimited (`-z`) temp FILE — UNQUOTED paths, so a
  # spaced/special filename is a real pathspec compare-and-restore can restore (plain
  # `--porcelain` C-quotes it — `"my file.txt"` — a silent `git checkout` no-op). `-z`
  # NUL bytes can't live in a bash `$(...)` variable, so the snapshot is a file.
  if rm -f "$SNAP_BEFORE" "$DISABLED_SENTINEL" 2>/dev/null &&
     git status --porcelain -z > "$SNAP_BEFORE" &&
     [ -f "$SNAP_BEFORE" ] &&
     [ ! -L "$SNAP_BEFORE" ] &&
     git hash-object "$SNAP_BEFORE"; then
    :
  else
    # Snapshot failed (index.lock, corrupt index, FS/OOM). Do NOT fall through with an
    # empty baseline — an empty BEFORE reads every dirtied path as "agent-introduced" and
    # authorizes `git checkout` against the orchestrator's OWN live edits. Fail closed:
    # disable the backstop for this dispatch (compare-and-restore short-circuits on the
    # sentinel) with an attributable breadcrumb. A fixed repo-local sentinel survives the
    # Agent-tool boundary; shell variables do not.
    echo "::warning::devflow review: could not create a regular working-tree snapshot before dispatch (stale-path removal, git status, or regular-file validation failed); dirty-tree backstop DISABLED for this dispatch — no after-compare, no auto-restore" >&2
    rm -f "$SNAP_BEFORE" 2>/dev/null
    printf '%s\n' disabled > "$DISABLED_SENTINEL"
  fi
}

cmd_compare_and_restore() {
  local OID="$1"
  mkdir -p .prflow/tmp
  if [ -f "$DISABLED_SENTINEL" ]; then
    : # before-snapshot failed in snapshot (already surfaced there); backstop disabled this dispatch
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
      # The snapshots differ — the tree changed during the dispatch window. The restore set is
      # computed BY PATH COLUMN (status prefix stripped from each `-z` record), NOT by whole
      # record: a path the orchestrator had ALREADY modified before dispatch is never checked out
      # even if an agent changed its status byte (` M f` -> `MM f`). Each `-z` record is `XY <path>`
      # (NUL-terminated, UNQUOTED); a rename/copy emits TWO records — `R  <new>` then a bare `<old>`
      # continuation — which the read loops consume rather than mis-stripping. The restore set is
      # `paths in AFTER, absent from BEFORE, NOT rename/copy entries`; rename/copy entries are
      # surfaced separately, never auto-restored (index surgery needed).
      mkdir -p .prflow/tmp
      rm -f ".prflow/tmp/review-dirty-tree-before-paths" ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      if ! printf '%s' '' > ".prflow/tmp/review-dirty-tree-before-paths" ||
         ! printf '%s' '' > ".prflow/tmp/review-dirty-tree-changed-paths" ||
         ! printf '%s' '' > ".prflow/tmp/review-dirty-tree-renamed-paths"; then
        # Repo-local scratch allocation failed (quota/perms). Do NOT proceed: an unbuilt BEFORE
        # membership set reports every path absent and fails OPEN (every dirty path, incl.
        # the orchestrator's own edits, treated as newly-dirty and restored). Fail closed with a
        # distinct breadcrumb and restore nothing.
        echo "::warning::devflow review: could not allocate repo-local scratch files for the dirty-tree restore; dirty-tree restore SKIPPED this dispatch — this is NOT an agent mutation, nothing auto-restored" >&2
        rm -f ".prflow/tmp/review-dirty-tree-before-paths" ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      else
        # 1. BEFORE membership set: every path (incl. rename new + orig), prefix stripped and NUL-
        #    delimited. `read -r -d ''` reads NUL records so a spaced/special path never splits.
        #    Indexed array + linear scan, never `declare -A`: the associative form is bash 4+ and
        #    this must run under bash 3.2.
        before_extract_rc=0
        before_orig=0
        before_paths=()
        rec=
        while IFS= read -r -d '' rec; do
          if [ "$before_orig" = 1 ]; then
            before_orig=0
            before_paths+=("$rec")
            printf '%s\0' "$rec" >> ".prflow/tmp/review-dirty-tree-before-paths" || { before_extract_rc=$?; break; }
            continue
          fi
          case "${rec:0:1}" in [RC]) before_orig=1 ;; esac   # index column (X) only: the two-record shape is emitted iff X is R/C
          before_paths+=("${rec:3}")
          printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-before-paths" || { before_extract_rc=$?; break; }
        done < "$SNAP_BEFORE" || before_extract_rc=$?
        [ -z "$rec" ] || before_extract_rc=65
        if [ "$before_extract_rc" -ne 0 ]; then
          echo "::warning::devflow review: could not extract the before-snapshot path set (rc=$before_extract_rc); dirty-tree restore SKIPPED this dispatch — nothing auto-restored" >&2
        else
          # 2. AFTER: rename/copy → surfaced-not-restored (renamed-paths file); a normal entry
          #    classified by its BEFORE membership. Membership is a whole-record exact-string scan
          #    over the `before_paths` array built above — `[ "$bp" = "${rec:3}" ]` compares the
          #    complete path, so a spaced/newline/glob-character pathname matches itself and
          #    nothing else. TWO outcomes only: present in BEFORE (already dirty) → never restore;
          #    absent from BEFORE → newly dirtied → restore set. The scan is bash builtins, so it
          #    cannot fail while the pipeline keeps running and misreport "absent → restore".
          after_extract_rc=0
          after_orig=0
          rec=
          while IFS= read -r -d '' rec; do
            if [ "$after_orig" = 1 ]; then after_orig=0; continue; fi
            case "${rec:0:1}" in   # index column (X) only: a rename/copy (X = R/C) emits the two-record shape
              [RC]) printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-renamed-paths" || { after_extract_rc=$?; break; }; after_orig=1; continue ;;
            esac
            member=0
            for bp in ${before_paths[@]+"${before_paths[@]}"}; do   # `${a[@]+…}` so an empty set is not an unbound-variable error under `set -u`
              if [ "$bp" = "${rec:3}" ]; then member=1; break; fi
            done
            if [ "$member" -eq 1 ]; then
              : # present in BEFORE (already dirty) → never restore
            else
              printf '%s\0' "${rec:3}" >> ".prflow/tmp/review-dirty-tree-changed-paths" || { after_extract_rc=$?; break; } # absent from BEFORE → newly dirtied → restore set
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
                # Divergence with an EMPTY restore set and no rename — the cause cannot be determined
                # here (`cmp` cannot distinguish an already-dirty path's status-byte change from a
                # dirty->clean / removed-path transition). Nothing auto-restored.
                echo "::warning::devflow review: a Phase 3.1 review-agent dispatch diverged the working tree but the by-path restore set is empty (an already-dirty path's status byte changed, or a dirty->clean transition — the cause cannot be determined here); nothing auto-restored — left for the Step 2.6 shadow and the human" >&2
              fi
            else
              # The changed-paths file holds the snapshot delta (paths clean at snapshot, now dirty,
              # non-rename), NUL-delimited and UNQUOTED so a spaced/special path is a real pathspec.
              # Restore is best-effort, per-path, fed via `read -r -d ''` so a special-char pathname
              # never word-splits. Restore from HEAD (NOT `git checkout -- "$p"`, which restores from
              # the INDEX and re-materializes a STAGED agent mutation while exiting 0 — a fail-open).
              # Then trust the TREE STATE, not the exit code: re-run `git status --porcelain -- "$p"`
              # and emit the per-path breadcrumb iff STILL dirty, so an untracked or staged-new file
              # the agent created is surfaced per-path and never falsely reported as restored.
              CHANGED_NAMES=$(tr '\0' ' ' < ".prflow/tmp/review-dirty-tree-changed-paths")
              echo "::warning::devflow review: a Phase 3.1 review-agent dispatch modified the working tree (advisory review agents must never mutate it); affected paths: [ ${CHANGED_NAMES}]${RENAMED_NAMES:+ (plus surfaced-not-restored rename/copy: [ ${RENAMED_NAMES}])}; recording an Important finding and attempting best-effort restore of the snapshot delta (per-path outcome in the warnings below)" >&2
              while IFS= read -r -d '' p; do
                [ -n "$p" ] || continue
                restore_err=$(git checkout HEAD -- "$p" 2>&1)
                if [ -n "$(git status --porcelain -- "$p")" ]; then
                  echo "::warning::devflow review: path '$p' still dirty after restore attempt (e.g. an untracked or staged-new file the agent created — never auto-deleted; git said: ${restore_err:-none}) — left as-is for human inspection" >&2
                fi
              done < ".prflow/tmp/review-dirty-tree-changed-paths"
            fi
          fi
        fi
        rm -f ".prflow/tmp/review-dirty-tree-before-paths" ".prflow/tmp/review-dirty-tree-changed-paths" ".prflow/tmp/review-dirty-tree-renamed-paths" 2>/dev/null
      fi
    fi
    # cmp_rc == 0: the snapshots are identical — nothing changed during the dispatch window.
    rm -f "$SNAP_AFTER" 2>/dev/null
  fi
  # Clean up fixed repo-local snapshot state after the dispatch.
  rm -f "$SNAP_BEFORE" "$DISABLED_SENTINEL" 2>/dev/null
}

main() {
  if [ "$#" -lt 1 ]; then
    echo "usage: review-dirty-tree.sh snapshot | compare-and-restore OID" >&2
    return 2
  fi
  case "$1" in
    snapshot)
      if [ "$#" -ne 1 ]; then
        echo "usage: review-dirty-tree.sh snapshot" >&2
        return 2
      fi
      cmd_snapshot
      ;;
    compare-and-restore)
      # The restore-authorising object ID is a required literal argument held by the
      # orchestrator — never recovered from agent-writable scratch (issue #2082 AC4).
      if [ "$#" -ne 2 ] || [ -z "$2" ]; then
        echo "usage: review-dirty-tree.sh compare-and-restore OID" >&2
        return 2
      fi
      cmd_compare_and_restore "$2"
      ;;
    *)
      echo "review-dirty-tree.sh: unknown subcommand '$1' (expected: snapshot | compare-and-restore)" >&2
      return 2
      ;;
  esac
}

main "$@"

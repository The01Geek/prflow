#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# migrate-telemetry-branch.sh — move a consumer's cost/effectiveness records from a
# pre-rename `devflow-telemetry` branch onto the branch PRFlow now writes to (issue #336).
#
# It restages each record from its old `.devflow/logs/` path to the current
# `.prflow/logs/` path and hands the staging root to the writer's OWN persist function
# (devflow_telemetry_persist_tree), so the store check, worktree degrade, CI push gate,
# compare-and-swap, push retry and breadcrumbs are the writer's, not a second copy. It
# is best-effort and exit-0 (like scripts/ensure-label.sh), deliberately NOT a member of
# the fail-closed Tier 1 atomic unit, because it needs the remote.
#
# Callers: `/prflow:init` and `install.sh --apply` run it once after the Tier 1 migration
# reports; `lib/efficiency-trace.sh`'s do_persist runs it with --backstop before its first
# append when the source branch still exists on the remote and the push gate passes.
#
# First, the in-place arm (issue #337) rewrites a resolved telemetry branch whose tip still
# carries `.devflow/logs/` records — a kept `devflow-telemetry` name or a hand-renamed branch — to
# the matching `.prflow/logs/` paths in one commit on the same branch. persist_tree only adds
# paths and refuses such a branch, so this arm builds its own commit, then runs the writer's store
# check on it. --backstop skips the arm, so a writable run never rewrites branch history.
#
# Usage: migrate-telemetry-branch.sh TARGET_REPO_ROOT [--backstop]
#   TARGET_REPO_ROOT  the repository whose records are migrated. REQUIRED: lib/config-source.sh
#                     fixes the config path from the current directory's git top level at source
#                     time and honors no operand, so the helper cd's into this root BEFORE
#                     sourcing lib/telemetry-branch.sh.
#   --backstop        skip the in-place arm (the efficiency-trace.sh persist backstop).
# Exit code: always 0 (best-effort), except 2 for a bad argument shape.
set -uo pipefail

report() { printf 'migrate-telemetry-branch: %s\n' "$1"; }
warn()   { printf 'migrate-telemetry-branch: %s\n' "$1" >&2; }
die()    { printf 'migrate-telemetry-branch: %s\n' "$1" >&2; exit 2; }

# devflow_telemetry_commit_id (sourced from lib/telemetry-branch.sh below) resolves each ref to
# a commit ID so no `<ref>:<path>` git argument built here has a slash left of the colon — Git
# Bash (MSYS) rewrites such an argument and the lookup fails on Windows (issue #578). It prints
# nothing and stays rc 0 when the ref does not resolve, so a bare `VAR="$(…)"` assignment yields
# an empty value here (this script runs `set -uo pipefail`) and never aborts a `set -e` caller of
# the sourced lib; every call site below treats an EMPTY value as "did not resolve" rather than
# building `:<path>` from it.

# Self-directory anchor, dirname-free (dirname is not a preflight-guaranteed tool).
SELF_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
RENAME_MAP="$SELF_DIR/../lib/rename-map.json"

USAGE="usage: migrate-telemetry-branch.sh TARGET_REPO_ROOT [--backstop]"
[ "$#" -le 2 ] || die "too many arguments ($USAGE)"
IN_PLACE=yes
if [ "$#" -eq 2 ]; then
  [ "$2" = "--backstop" ] || die "unknown argument '$2' ($USAGE)"
  IN_PLACE=no
fi
TARGET_ROOT="${1:-}"
[ -n "$TARGET_ROOT" ] || die "a target repository root is required ($USAGE)"
[ -d "$TARGET_ROOT" ] || die "target repository root '$TARGET_ROOT' is not a directory"

# cd first, THEN source: config-source.sh (sourced by telemetry-branch.sh) fixes the config
# path from the current git top level at source time and honors no operand.
cd "$TARGET_ROOT" || die "could not cd into target repository root '$TARGET_ROOT'"
# shellcheck source=/dev/null
. "$SELF_DIR/../lib/telemetry-branch.sh" || { warn "could not source lib/telemetry-branch.sh beside the helper — skipping migration this run"; exit 0; }

# ── Read the superseded (source) branch name from the rename map. A value that decides a
# branch must not be derived through a non-preflight PATH tool; python3 is preflight-guaranteed.
if ! command -v python3 >/dev/null 2>&1; then
  report "python3 is not on PATH — the source telemetry branch name was not read; skipping migration this run"
  exit 0
fi
SOURCE_BRANCH="$(PRFLOW_RENAME_MAP="$RENAME_MAP" python3 -c '
import json, os, sys
sys.stdout.reconfigure(newline="\n")
try:
    with open(os.environ["PRFLOW_RENAME_MAP"], encoding="utf-8") as fh:
        m = json.load(fh)
    for e in m.get("identifiers", []):
        if e.get("id") == "telemetry-branch":
            v = e.get("superseded", "")
            if isinstance(v, str):
                sys.stdout.write(v)
            break
except Exception:
    pass
' 2>/dev/null || true)"
if [ -z "$SOURCE_BRANCH" ]; then
  report "could not read the superseded telemetry branch name from lib/rename-map.json — skipping migration this run"
  exit 0
fi

TARGET_BRANCH="$(devflow_telemetry_branch 2>/dev/null || true)"
if [ -z "$TARGET_BRANCH" ]; then
  report "could not resolve the current telemetry branch name — skipping migration this run"
  exit 0
fi

# ── Telemetry master switch: do nothing when telemetry.enabled is the JSON boolean false.
# telemetry-master-off.py exits 0 only for an explicit false; 1 = on; 2/other = present-but-
# unreadable, which fails safe ON (persist as if on), matching do_persist's convention.
_TMO_RC=0
python3 "$SELF_DIR/telemetry-master-off.py" "${_DEVFLOW_CONFIG:-}" >/dev/null 2>&1 || _TMO_RC=$?
if [ "$_TMO_RC" -eq 0 ]; then
  report "telemetry.enabled is false — skipping migration this run"
  exit 0
fi

# ── CI push authorization: an unpushed migration on an ephemeral CI checkout is lost, so on a
# CI runner without an affirmative DEVFLOW_TELEMETRY_PUSH the read-only tier pays no probe.
if ! _devflow_telemetry_should_push; then
  report "GITHUB_ACTIONS is set without an affirmative DEVFLOW_TELEMETRY_PUSH — a migration would not be pushed on this ephemeral checkout; skipping migration this run"
  exit 0
fi

HAVE_ORIGIN=no
git remote get-url origin >/dev/null 2>&1 && HAVE_ORIGIN=yes

# ── In-place arm (issue #337): relocate the resolved branch's own .devflow/logs/ records.
# rc 0 = nothing left to rewrite (relocated, already current, absent, or diverged with no legacy
# record on either tip); rc 1 = refused, not published, or published without advancing the local
# ref, after one report line.
# tip_has_legacy COMMIT — rc 0 when COMMIT holds a .devflow/logs/ path; rc 1 when it holds none.
# An unreadable tree also returns 0, so the caller refuses rather than guessing it is current.
tip_has_legacy() {
  local names
  names="$(git ls-tree -r --full-tree --name-only "$1" -- .devflow/logs 2>/dev/null)" || return 0
  [ -n "$names" ]
}
relocate_in_place() {
  local remote_tip="" local_tip="" base="" lsr_rc=0 listing line path sha mapped mapped_sha
  local legacy=() legacy_meta=() current=() current_sha=() i j idx tree new push_err upd_err tab
  tab="$(printf '\t')"
  if [ "$HAVE_ORIGIN" = yes ]; then
    GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin "refs/heads/${TARGET_BRANCH}" >/dev/null 2>&1 || lsr_rc=$?
    case "$lsr_rc" in
      0)
        if ! GIT_TERMINAL_PROMPT=0 git fetch -q --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" 2>/dev/null; then
          report "could not fetch '$TARGET_BRANCH' from origin (offline or auth) — skipping migration this run"
          return 1
        fi
        remote_tip="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/remotes/origin/${TARGET_BRANCH}")"
        if [ -z "$remote_tip" ]; then
          report "could not resolve the fetched '$TARGET_BRANCH' tip to a commit — skipping migration this run"
          return 1
        fi
        ;;
      2) ;;
      *)
        report "could not query origin for '$TARGET_BRANCH' (offline or auth) — skipping migration this run"
        return 1
        ;;
    esac
  fi
  local_tip="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/heads/${TARGET_BRANCH}")"

  # Rewrite on top of the newer tip; a local ref that diverged from the remote is left alone.
  if [ -n "$remote_tip" ] && [ -n "$local_tip" ] && [ "$remote_tip" != "$local_tip" ]; then
    if git merge-base --is-ancestor "$local_tip" "$remote_tip" 2>/dev/null; then
      base="$remote_tip"
    elif git merge-base --is-ancestor "$remote_tip" "$local_tip" 2>/dev/null; then
      base="$local_tip"
    else
      # Neither tip holds a .devflow/logs/ record: nothing to rewrite, so leave the diverged
      # branch to the writer's own fetch/re-parent in the source migration below.
      if ! tip_has_legacy "$local_tip" && ! tip_has_legacy "$remote_tip"; then
        return 0
      fi
      report "the local and remote '$TARGET_BRANCH' tips have diverged — not rewriting its record paths; no changes made"
      return 1
    fi
  else
    base="${remote_tip:-$local_tip}"
  fi
  [ -n "$base" ] || return 0

  if ! listing="$(git -c core.quotePath=false ls-tree -r --full-tree "$base" 2>/dev/null)"; then
    report "could not read the tip tree of '$TARGET_BRANCH' — not rewriting its record paths; no changes made"
    return 1
  fi
  # Each line is `<mode> <type> <sha>\t<path>`; a quoted (special-character) path is foreign.
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    path="${line#*"$tab"}"
    case "$path" in
      .prflow/logs/*) current+=("$path"); current_sha+=("${line%%"$tab"*}") ;;
      .devflow/logs/*) legacy+=("$path"); legacy_meta+=("${line%%"$tab"*}") ;;
      *)
        report "'$TARGET_BRANCH' holds a path under neither .devflow/logs/ nor .prflow/logs/ ('$path') — refusing to rewrite or migrate onto it; no changes made"
        return 1
        ;;
    esac
  done <<EOF
$listing
EOF
  [ "${#legacy[@]}" -gt 0 ] || return 0

  # A mapped path the branch already holds must carry the same blob, or one record would be dropped.
  # Read from the listing above, so a failed lookup is never mistaken for an absent path.
  for ((i = 0; i < ${#legacy[@]}; i++)); do
    mapped=".prflow/${legacy[$i]#.devflow/}"
    sha="${legacy_meta[$i]##* }"
    for ((j = 0; j < ${#current[@]}; j++)); do
      [ "${current[$j]}" = "$mapped" ] || continue
      mapped_sha="${current_sha[$j]##* }"
      if [ "$mapped_sha" != "$sha" ]; then
        report "'$TARGET_BRANCH' holds both '${legacy[$i]}' and a differing '$mapped' — refusing to rewrite, which would drop one of them; no changes made"
        return 1
      fi
    done
  done

  if devflow_telemetry_branch_checked_out "$TARGET_ROOT" "refs/heads/${TARGET_BRANCH}"; then
    report "'$TARGET_BRANCH' is checked out in a worktree — not rewriting its record paths; no changes made"
    return 1
  fi
  if ! mkdir -p "${TARGET_ROOT}/.prflow/tmp" 2>/dev/null; then
    report "could not create .prflow/tmp/ for the temp index — not rewriting '$TARGET_BRANCH'; no changes made"
    return 1
  fi
  idx="${TARGET_ROOT}/.prflow/tmp/telemetry-relocate-index-$$-${RANDOM}-${SECONDS}"
  # Each record keeps its blob (bytes unchanged) and its sub-path; only the prefix changes.
  tree="$(
    export GIT_INDEX_FILE="$idx"
    git read-tree "$base" 2>/dev/null || exit 1
    for ((i = 0; i < ${#legacy[@]}; i++)); do
      git update-index --add --cacheinfo "${legacy_meta[$i]%% *},${legacy_meta[$i]##* },.prflow/${legacy[$i]#.devflow/}" 2>/dev/null || exit 1
      git update-index --force-remove -- "${legacy[$i]}" 2>/dev/null || exit 1
    done
    git write-tree 2>/dev/null
  )" || tree=""
  rm -f "$idx" 2>/dev/null || true
  new=""
  if [ -n "$tree" ]; then
    new="$(GIT_AUTHOR_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_AUTHOR_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
      GIT_COMMITTER_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_COMMITTER_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
      git commit-tree "$tree" -p "$base" -m "chore: relocate telemetry records from .devflow/logs/ to .prflow/logs/" 2>/dev/null || true)"
  fi
  if [ -z "$new" ]; then
    report "could not build the relocation commit for '$TARGET_BRANCH' (object-store write failed); no changes made"
    return 1
  fi
  if ! devflow_telemetry_verify_store "$TARGET_ROOT" "$new"; then
    report "the relocated '$TARGET_BRANCH' tree failed the telemetry store check; no changes made"
    return 1
  fi

  if [ "$HAVE_ORIGIN" = yes ]; then
    # Fast-forward-only push: a concurrent writer's newer remote tip rejects it.
    if ! push_err="$(GIT_TERMINAL_PROMPT=0 git push -q origin "${new}:refs/heads/${TARGET_BRANCH}" 2>&1)"; then
      report "could not push the relocated '$TARGET_BRANCH' ($push_err) — the branch is unchanged; re-run /prflow:init to retry"
      return 1
    fi
    git update-ref "refs/remotes/origin/${TARGET_BRANCH}" "$new" 2>/dev/null || true
  fi
  if [ -n "$local_tip" ]; then
    if ! upd_err="$(git update-ref "refs/heads/${TARGET_BRANCH}" "$new" "$local_tip" 2>&1)"; then
      report "relocated '$TARGET_BRANCH' as $new but could not advance its local ref ($upd_err) — advance it by hand with: git update-ref refs/heads/$TARGET_BRANCH $new"
      return 1
    fi
  fi
  report "relocated ${#legacy[@]} record(s) on '$TARGET_BRANCH' from .devflow/logs/ to .prflow/logs/ in one commit"
  return 0
}

if [ "$IN_PLACE" = yes ]; then
  relocate_in_place || exit 0
fi

if [ "$SOURCE_BRANCH" = "$TARGET_BRANCH" ]; then
  if [ "$IN_PLACE" = yes ]; then
    report "telemetry.branch is the superseded name '$SOURCE_BRANCH' — no separate branch to migrate from"
  else
    report "telemetry.branch is the superseded name '$SOURCE_BRANCH' — only /prflow:init or install.sh --apply rewrites its record paths; no changes made"
  fi
  exit 0
fi

report "migrating telemetry records from '$SOURCE_BRANCH' onto '$TARGET_BRANCH'"

SOURCE_REMOTE_REF=""   # set to the remote-tracking ref when the remote holds the source
SOURCE_LOCAL_REF=""    # set to refs/heads/<source> when a local ref exists

# Probe the remote for the source branch with an EXACT ref match (exit 0 present, 2 absent,
# anything else unestablished).
SOURCE_ON_REMOTE=no
if [ "$HAVE_ORIGIN" = yes ]; then
  _LSR_RC=0
  GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin "refs/heads/${SOURCE_BRANCH}" >/dev/null 2>&1 || _LSR_RC=$?
  case "$_LSR_RC" in
    0)
      SOURCE_ON_REMOTE=yes
      if GIT_TERMINAL_PROMPT=0 git fetch -q --no-tags origin "+refs/heads/${SOURCE_BRANCH}:refs/remotes/origin/${SOURCE_BRANCH}" 2>/dev/null; then
        # Resolve to a commit ID right after the ref is set (empty → could not resolve, handled below).
        SOURCE_REMOTE_REF="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/remotes/origin/${SOURCE_BRANCH}")"
        if [ -z "$SOURCE_REMOTE_REF" ]; then
          report "could not resolve the fetched source branch '$SOURCE_BRANCH' to a commit — skipping migration this run"
          exit 0
        fi
      else
        report "could not fetch the source branch '$SOURCE_BRANCH' from origin (offline or auth) — skipping migration this run"
        exit 0
      fi
      ;;
    2) SOURCE_ON_REMOTE=no ;;
    *)
      report "could not query origin for the source branch '$SOURCE_BRANCH' (offline or auth) — skipping migration this run"
      exit 0
      ;;
  esac
fi

# The local source ref, if any, is always part of the source tree (local wins on a shared path).
# Resolve to a commit ID (empty when the branch is absent).
SOURCE_LOCAL_REF="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/heads/${SOURCE_BRANCH}")"

if [ -z "$SOURCE_REMOTE_REF" ] && [ -z "$SOURCE_LOCAL_REF" ]; then
  report "no source branch '$SOURCE_BRANCH' on the remote or locally; nothing to migrate"
  exit 0
fi

# ── Enumerate the source path set (remote ∪ local). Refuse any path outside .devflow/logs/.
# Assign the refs' paths via command substitution and dedup+classify over a heredoc — a pipe into
# the loop would run it in a subshell and lose the RECORD_PATHS the current shell must keep.
_DTM_ALL=""
if [ -n "$SOURCE_REMOTE_REF" ]; then
  _DTM_ALL="${_DTM_ALL}$(git ls-tree -r --name-only "$SOURCE_REMOTE_REF" 2>/dev/null)
"
fi
if [ -n "$SOURCE_LOCAL_REF" ]; then
  _DTM_ALL="${_DTM_ALL}$(git ls-tree -r --name-only "$SOURCE_LOCAL_REF" 2>/dev/null)
"
fi

RECORD_PATHS=()
_DTM_SEEN=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  case "$_DTM_SEEN" in
    *"|${p}|"*) continue ;;
  esac
  _DTM_SEEN="${_DTM_SEEN}|${p}|"
  case "$p" in
    .devflow/logs/*) RECORD_PATHS+=("$p") ;;
    *)
      report "source branch '$SOURCE_BRANCH' holds a path outside .devflow/logs/ ('$p') — refusing to migrate; no changes made"
      exit 0
      ;;
  esac
done <<EOF
$_DTM_ALL
EOF

if [ "${#RECORD_PATHS[@]}" -eq 0 ]; then
  report "source branch '$SOURCE_BRANCH' holds no records under .devflow/logs/; nothing to migrate"
  exit 0
fi

# ── Resolve the target tip currently knowable, for collision detection: the fetched remote
# target tip when the remote holds it, else the local target ref if one exists.
# Resolve the target tip to a commit ID (empty when no tip is knowable).
TARGET_TIP_REF=""
if [ "$HAVE_ORIGIN" = yes ] && GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin "refs/heads/${TARGET_BRANCH}" >/dev/null 2>&1; then
  if GIT_TERMINAL_PROMPT=0 git fetch -q --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" 2>/dev/null; then
    TARGET_TIP_REF="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/remotes/origin/${TARGET_BRANCH}")"
  fi
fi
if [ -z "$TARGET_TIP_REF" ]; then
  TARGET_TIP_REF="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/heads/${TARGET_BRANCH}")"
fi

# ── Stage each record at its mapped path, skipping (with one warning per path) any the target
# tip already holds. A per-process staging root under the ignored .prflow/tmp/.
STAGING_ROOT="${TARGET_ROOT}/.prflow/tmp/telemetry-migrate-stage-$$-${RANDOM}-${SECONDS}"
if ! mkdir -p "$STAGING_ROOT" 2>/dev/null; then
  report "could not create the staging root under .prflow/tmp/ — skipping migration this run"
  exit 0
fi
_dtm_cleanup() { rm -rf "$STAGING_ROOT" 2>/dev/null || true; }
trap _dtm_cleanup EXIT

MAPPED_PATHS=()   # staged AND kept-collision mapped paths only, for the landed-push check;
                  # an unreadable record is excluded so it never triggers a false "push did not
                  # land" report (issue #578).
STAGED_ANY=no
UNREADABLE_COUNT=0   # listed records skipped because their content could not be read
for p in "${RECORD_PATHS[@]}"; do
  mapped=".prflow/${p#.devflow/}"
  # Collision: the target already holds this mapped path → keep the target's file, warn, skip.
  # A collided record is kept (staged by neither side), so it counts toward the landed-push
  # check but not toward the unreadable count.
  if [ -n "$TARGET_TIP_REF" ] && git cat-file -e "${TARGET_TIP_REF}:${mapped}" 2>/dev/null; then
    warn "target already holds '$mapped' — keeping the target's file (the source branch's differing copy, if any, is not migrated)"
    MAPPED_PATHS+=("$mapped")
    continue
  fi
  # Content: local ref wins on a path present in both.
  src_ref=""
  if [ -n "$SOURCE_LOCAL_REF" ] && git cat-file -e "${SOURCE_LOCAL_REF}:${p}" 2>/dev/null; then
    src_ref="$SOURCE_LOCAL_REF"
  elif [ -n "$SOURCE_REMOTE_REF" ] && git cat-file -e "${SOURCE_REMOTE_REF}:${p}" 2>/dev/null; then
    src_ref="$SOURCE_REMOTE_REF"
  fi
  # A record the source branch LISTS but whose content cannot be read (an unresolvable source
  # lookup, or a failed content read) is warned and counted — not skipped silently, which left
  # the "no commit needed" line unable to tell "everything already migrated" from "nothing could
  # be read" (issue #578). It is left out of MAPPED_PATHS so the landed-push check ignores it.
  if [ -z "$src_ref" ]; then
    warn "could not read '$p' from the source branch — skipping just this record"
    UNREADABLE_COUNT=$((UNREADABLE_COUNT + 1))
    continue
  fi
  if ! mkdir -p "${STAGING_ROOT}/${mapped%/*}" 2>/dev/null; then
    warn "could not create the staging directory for '$mapped' — skipping just this record"
    UNREADABLE_COUNT=$((UNREADABLE_COUNT + 1))
    continue
  fi
  if git show "${src_ref}:${p}" > "${STAGING_ROOT}/${mapped}" 2>/dev/null; then
    STAGED_ANY=yes
    MAPPED_PATHS+=("$mapped")
  else
    warn "could not read '$p' from the source branch — skipping just this record"
    rm -f "${STAGING_ROOT}/${mapped}" 2>/dev/null || true
    UNREADABLE_COUNT=$((UNREADABLE_COUNT + 1))
  fi
done

# ── Hand the staging root to the writer's own persist function.
_PERSIST_RC=0
devflow_telemetry_persist_tree "$TARGET_ROOT" "$STAGING_ROOT" || _PERSIST_RC=$?

if [ "$_PERSIST_RC" -eq 1 ] || [ "$_PERSIST_RC" -eq 2 ]; then
  # Degraded (1) or staging-only (2): the writer already relayed its own ::warning::. Leave
  # the source branch in place; the next authorized persist retries.
  report "the telemetry write did not land cleanly (writer returned $_PERSIST_RC) — leaving the source branch '$SOURCE_BRANCH' in place; the writer's warning above names the cause"
  exit 0
fi

# One or more listed records could not be read: the migration is incomplete, so keep the source
# branch for a manual retry and print the unreadable count instead of the "no commit needed" or
# landed-push lines — neither of which can tell "everything already migrated" from "nothing could
# be read" (issue #578). Collided records the target already holds were staged by neither side
# and are not counted. Runs before the origin check so the line prints with or without a remote.
if [ "$UNREADABLE_COUNT" -gt 0 ]; then
  report "could not read $UNREADABLE_COUNT listed record(s) from the source branch — the migration is incomplete, so leaving the source branch '$SOURCE_BRANCH' in place; inspect the unreadable paths named in the warnings above, then delete '$SOURCE_BRANCH' by hand once resolved (git branch -D '$SOURCE_BRANCH', and git push origin --delete '$SOURCE_BRANCH' if it is on the remote)"
  exit 0
fi

# _PERSIST_RC is 0 and every listed record was readable — but 0 also covers an idempotent no-op
# and an empty staging root, so it is NOT evidence of a landed push. STAGED_ANY=no here therefore
# means every record already sat at its mapped path. Establish the push landed before any delete.
if [ "$STAGED_ANY" = no ]; then
  report "no commit needed — every record already sits at its mapped path on '$TARGET_BRANCH'"
fi

if [ "$HAVE_ORIGIN" != yes ]; then
  # No 'origin' remote: persist_tree advanced the LOCAL target ref and relayed its own
  # no-remote warning. There is nothing to establish against and no remote source to delete;
  # the local source ref stays in place (AC8).
  exit 0
fi

# Fetch the remote target tip and confirm it holds every record's mapped path.
if ! GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin "refs/heads/${TARGET_BRANCH}" >/dev/null 2>&1; then
  report "the remote holds no '$TARGET_BRANCH' branch after the persist — the push did not land; leaving the source branch '$SOURCE_BRANCH' in place"
  exit 0
fi
if ! GIT_TERMINAL_PROMPT=0 git fetch -q --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" 2>/dev/null; then
  report "could not fetch the remote '$TARGET_BRANCH' tip to confirm the push landed — leaving the source branch '$SOURCE_BRANCH' in place"
  exit 0
fi
# Resolve the fetched landed tip to a commit ID (empty → could not confirm, handled below).
LANDED_TIP="$(devflow_telemetry_commit_id "$TARGET_ROOT" "refs/remotes/origin/${TARGET_BRANCH}")"
if [ -z "$LANDED_TIP" ]; then
  report "could not resolve the fetched '$TARGET_BRANCH' tip to confirm the push landed — leaving the source branch '$SOURCE_BRANCH' in place"
  exit 0
fi
for mapped in "${MAPPED_PATHS[@]}"; do
  if ! git cat-file -e "${LANDED_TIP}:${mapped}" 2>/dev/null; then
    report "the remote '$TARGET_BRANCH' tip lacks '$mapped' — the push did not land every record; leaving the source branch '$SOURCE_BRANCH' in place"
    exit 0
  fi
done

# ── The push landed. Delete the source branch: remote first, then the local ref.
if [ "$SOURCE_ON_REMOTE" = yes ]; then
  _DEL_ERR="$(GIT_TERMINAL_PROMPT=0 git push origin --delete "$SOURCE_BRANCH" 2>&1)" || {
    warn "could not delete the remote source branch '$SOURCE_BRANCH' ($_DEL_ERR) — leaving both refs in place; the records are already on '$TARGET_BRANCH'. Delete it manually with: git push origin --delete $SOURCE_BRANCH"
    exit 0
  }
fi

if [ -n "$SOURCE_LOCAL_REF" ]; then
  _LDEL_ERR="$(git branch -D "$SOURCE_BRANCH" 2>&1)" || {
    # Find the worktree path the source ref is checked out in, with bash builtins only —
    # this path is EMITTED, so it must not be derived through a non-preflight PATH tool.
    _WT_LIST="$(git worktree list --porcelain 2>/dev/null || true)"
    _WT_PATH=""
    _wt_cur=""
    while IFS= read -r _wt_line; do
      case "$_wt_line" in
        "worktree "*) _wt_cur="${_wt_line#worktree }" ;;
        "branch refs/heads/${SOURCE_BRANCH}") _WT_PATH="$_wt_cur" ;;
      esac
    done <<EOF
$_WT_LIST
EOF
    if [ -n "$_WT_PATH" ]; then
      warn "could not delete the local ref '$SOURCE_BRANCH' ($_LDEL_ERR) — it is checked out at '$_WT_PATH'; remove that worktree first with: git worktree remove $_WT_PATH"
    else
      warn "could not delete the local ref '$SOURCE_BRANCH' ($_LDEL_ERR) — leaving the local ref in place"
    fi
    exit 0
  }
fi

report "migration complete — records are on '$TARGET_BRANCH' and the source branch '$SOURCE_BRANCH' was deleted"
exit 0

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
# reports; `lib/efficiency-trace.sh`'s do_persist runs it as a backstop before its first
# append when the source branch still exists on the remote and the push gate passes.
#
# Usage: migrate-telemetry-branch.sh TARGET_REPO_ROOT
#   TARGET_REPO_ROOT  the repository whose records are migrated. REQUIRED: lib/config-source.sh
#                     fixes the config path from the current directory's git top level at source
#                     time and honors no operand, so the helper cd's into this root BEFORE
#                     sourcing lib/telemetry-branch.sh.
# Exit code: always 0 (best-effort), except 2 for a bad argument shape.
set -uo pipefail

report() { printf 'migrate-telemetry-branch: %s\n' "$1"; }
warn()   { printf 'migrate-telemetry-branch: %s\n' "$1" >&2; }
die()    { printf 'migrate-telemetry-branch: %s\n' "$1" >&2; exit 2; }

# Self-directory anchor, dirname-free (dirname is not a preflight-guaranteed tool).
SELF_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
RENAME_MAP="$SELF_DIR/../lib/rename-map.json"

TARGET_ROOT="${1:-}"
[ -n "$TARGET_ROOT" ] || die "a target repository root is required (usage: migrate-telemetry-branch.sh TARGET_REPO_ROOT)"
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

# ── Same-name shape is a separately filed defect (a telemetry.branch set to the old name):
# report it and change nothing.
if [ "$SOURCE_BRANCH" = "$TARGET_BRANCH" ]; then
  report "telemetry.branch is set to the superseded name '$SOURCE_BRANCH' — source and target are the same branch, which is out of scope for this migration (filed separately); no changes made"
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

report "migrating telemetry records from '$SOURCE_BRANCH' onto '$TARGET_BRANCH'"

SOURCE_REMOTE_REF=""   # set to the remote-tracking ref when the remote holds the source
SOURCE_LOCAL_REF=""    # set to refs/heads/<source> when a local ref exists
HAVE_ORIGIN=no
git remote get-url origin >/dev/null 2>&1 && HAVE_ORIGIN=yes

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
        SOURCE_REMOTE_REF="refs/remotes/origin/${SOURCE_BRANCH}"
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
if git rev-parse --verify --quiet "refs/heads/${SOURCE_BRANCH}" >/dev/null 2>&1; then
  SOURCE_LOCAL_REF="refs/heads/${SOURCE_BRANCH}"
fi

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
TARGET_TIP_REF=""
if [ "$HAVE_ORIGIN" = yes ] && GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin "refs/heads/${TARGET_BRANCH}" >/dev/null 2>&1; then
  if GIT_TERMINAL_PROMPT=0 git fetch -q --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" 2>/dev/null; then
    TARGET_TIP_REF="refs/remotes/origin/${TARGET_BRANCH}"
  fi
fi
if [ -z "$TARGET_TIP_REF" ] && git rev-parse --verify --quiet "refs/heads/${TARGET_BRANCH}" >/dev/null 2>&1; then
  TARGET_TIP_REF="refs/heads/${TARGET_BRANCH}"
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

MAPPED_PATHS=()   # every record's mapped path (staged AND kept-collision), for the landed-push check
STAGED_ANY=no
for p in "${RECORD_PATHS[@]}"; do
  mapped=".prflow/${p#.devflow/}"
  MAPPED_PATHS+=("$mapped")
  # Collision: the target already holds this mapped path → keep the target's file, warn, skip.
  if [ -n "$TARGET_TIP_REF" ] && git cat-file -e "${TARGET_TIP_REF}:${mapped}" 2>/dev/null; then
    warn "target already holds '$mapped' — keeping the target's file (the source branch's differing copy, if any, is not migrated)"
    continue
  fi
  # Content: local ref wins on a path present in both.
  src_ref=""
  if [ -n "$SOURCE_LOCAL_REF" ] && git cat-file -e "${SOURCE_LOCAL_REF}:${p}" 2>/dev/null; then
    src_ref="$SOURCE_LOCAL_REF"
  elif [ -n "$SOURCE_REMOTE_REF" ] && git cat-file -e "${SOURCE_REMOTE_REF}:${p}" 2>/dev/null; then
    src_ref="$SOURCE_REMOTE_REF"
  fi
  [ -n "$src_ref" ] || continue
  if ! mkdir -p "${STAGING_ROOT}/${mapped%/*}" 2>/dev/null; then
    warn "could not create the staging directory for '$mapped' — skipping just this record"
    continue
  fi
  if git show "${src_ref}:${p}" > "${STAGING_ROOT}/${mapped}" 2>/dev/null; then
    STAGED_ANY=yes
  else
    warn "could not read '$p' from the source branch — skipping just this record"
    rm -f "${STAGING_ROOT}/${mapped}" 2>/dev/null || true
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

# _PERSIST_RC is 0 here — but that also covers an idempotent no-op and an empty staging root,
# so it is NOT evidence of a landed push. Establish the push landed before any delete.
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
LANDED_TIP="refs/remotes/origin/${TARGET_BRANCH}"
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

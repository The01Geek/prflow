#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scrub-transcript.sh — scrub a run's execution transcript for upload as a run
# artifact, and advertise the scrubbed path ONLY when it is safe to upload
# (issue #1064 D4). This is the suite-drivable home of the transcript channel's
# scrub / non-empty gate / caveat-prepend / fail-closed SELECTION, so that logic is
# NOT duplicated inline across the engine workflows (the coupled-mirror hazard
# CLAUDE.md warns of). The credential blocklist itself is the shared
# scripts/scrub-credentials.sh (one implementation, every channel).
#
# Usage: scrub-transcript.sh <execution_file> <out_file> [<store_root>] [<stamp>]
#   <execution_file>  steps.claude.outputs.execution_file path (may be absent).
#   <out_file>        where the scrubbed execution-file transcript is written.
#   <store_root>      the CLI session store root ($CLAUDE_CONFIG_DIR/projects, else
#                     $HOME/.claude/projects) — read ONLY when <execution_file> is absent.
#   <stamp>           a file the workflow wrote just before the Claude step; only session
#                     files newer than it are eligible (issue #342).
#
# Sources, in order: when <execution_file> exists the transcript is that file, scrubbed
# exactly as before and the store is NEVER read (AC3). When it does NOT (a cancelled or
# signal-killed run), the CLI's own session files for THIS run are the fallback: every
# regular `.jsonl` under <store_root> newer than <stamp> whose first `cwd`-bearing record
# equals $GITHUB_WORKSPACE, so another job's or another repo's sessions on a reused runner
# are excluded. Prints ONE `source=` line (`execution-file`|`native-session`|`none`) before
# any `path=` line; an older vendored helper prints no `source=` line, which is how the
# workflow tells it apart from a new helper that found nothing.
#
# Prints `path=<file-or-dir>` to stdout ONLY when scrubbed output was produced AND its
# caveat header was prepended; the workflow gates its upload step on that line. FAILS
# CLOSED (a `::notice::`/`::warning::` and NO path) on every other arm, and ALWAYS exits 0
# (best-effort — an always() step is never aborted). The caveat is a `#`-comment FIRST line
# so scripts/context_eval_shared.py (which strips only leading `#` lines) still reads the
# artifact; it also names the source so a reader sees which transcript this is.

set -uo pipefail

_ST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRUBBER="$_ST_DIR/scrub-credentials.sh"
NORMALIZE="$_ST_DIR/../lib/normalize-path.sh"

EXECUTION_FILE="${1:-}"
OUT="${2:-}"
STORE_ROOT_RAW="${3:-}"
STAMP_RAW="${4:-}"

# source= MUST precede any path= line (AC5), so every terminal arm routes through here.
emit() {
  printf 'source=%s\n' "$1"
  [ -n "${2:-}" ] && printf 'path=%s\n' "$2"
}

# scrub_and_caveat <src> <dest> <caveat>: scrub <src> through the shared blocklist and write
# <dest> as the caveat line followed by the scrubbed body. This is the ONE home of the
# scrub / non-empty gate / caveat-prepend sequence — both the execution-file arm and the
# native-session loop call it, so the two cannot drift. Returns 1 (scrub failed), 2 (empty
# scrub), 3 (caveat write failed) as DISTINCT codes so each caller keeps AC4's distinct
# no-upload breadcrumb; the caller owns the breadcrumb and the fail-closed cleanup.
scrub_and_caveat() {
  local src="$1" dest="$2" caveat="$3" tmp="$2.body"
  if ! bash "$SCRUBBER" < "$src" > "$tmp" 2>/dev/null; then rm -f "$tmp" 2>/dev/null; return 1; fi
  if [ ! -s "$tmp" ]; then rm -f "$tmp" 2>/dev/null; return 2; fi
  if { printf '%s\n' "$caveat" > "$dest" && cat "$tmp" >> "$dest"; }; then
    rm -f "$tmp" 2>/dev/null
    return 0
  fi
  rm -f "$tmp" 2>/dev/null
  return 3
}

if [ -z "$OUT" ]; then
  # No output path is a mis-invocation, not one of the enumerated no-upload arms — keep the
  # historical warning-and-exit so a 2-arg-missing call still advertises nothing.
  echo "::warning::scrub-transcript: no output path given; nothing uploaded (fail-closed)" >&2
  exit 0
fi

if [ -n "$EXECUTION_FILE" ] && [ -f "$EXECUTION_FILE" ]; then
  # Execution-file source (today's behavior). The project store is NEVER read here (AC3).
  if [ ! -f "$SCRUBBER" ]; then
    echo "::warning::scrub-transcript: $SCRUBBER missing (a vendored tree pinned to an older prflow_version); NOT uploading the unscrubbed execution file (fail-closed)" >&2
    emit none
    exit 0
  fi
  # scrub-credentials.sh fails closed (non-zero, no output) when sed cannot run, so a
  # non-zero exit means DO NOT UPLOAD.
  SHAPES="$(bash "$SCRUBBER" --shapes 2>/dev/null || printf 'a fixed set of credential shapes\n')"
  CAVEAT="# DEVFLOW SCRUB CAVEAT: best-effort blocklist redacted ${SHAPES}. This blocklist is INCOMPLETE — other third-party credential shapes may remain. Treat this artifact as sensitive."
  scrub_and_caveat "$EXECUTION_FILE" "$OUT" "$CAVEAT"
  rc=$?
  case $rc in
    0) echo "::warning::transcript scrub is a best-effort blocklist covering ${SHAPES}; it is INCOMPLETE for third-party credential shapes — treat the uploaded artifact as sensitive." >&2
       emit execution-file "$OUT" ;;
    1) echo "::warning::transcript scrub failed (scrub-credentials.sh non-zero); NOT uploading the unscrubbed execution file (fail-closed)." >&2
       emit none ;;
    2) echo "::notice::scrubbed transcript is empty; nothing to preserve (no upload)." >&2
       emit none ;;
    *) echo "::warning::transcript caveat-header write failed; NOT uploading the transcript (fail-closed)." >&2
       emit none ;;
  esac
  exit 0
fi

# ── Native-session fallback: the action wrote no execution file (cancel/kill), so upload
# the CLI's own session transcript for THIS run rather than losing it (issue #342).
if [ ! -f "$SCRUBBER" ]; then
  echo "::warning::scrub-transcript: $SCRUBBER missing (a vendored tree pinned to an older prflow_version); NOT uploading any session transcript (fail-closed)" >&2
  emit none
  exit 0
fi
if [ -z "$STORE_ROOT_RAW" ] || [ -z "$STAMP_RAW" ]; then
  echo "::notice::no execution file and no session-store operand (store root/stamp); nothing to preserve (no upload)." >&2
  emit none
  exit 0
fi

# Normalize the store root, stamp and workspace for a Windows runner (passthrough on Linux/macOS);
# comparing an un-normalized cwd against a normalized workspace mis-rejects every file on a Git
# Bash runner (issue #342 Windows residual, diagnosable via the rejected-files notice below).
# shellcheck source=/dev/null
[ -f "$NORMALIZE" ] && . "$NORMALIZE"
STORE_ROOT="$STORE_ROOT_RAW"
STAMP="$STAMP_RAW"
WS="${GITHUB_WORKSPACE:-}"
HAS_NORMALIZE=0
if command -v devflow_normalize_path >/dev/null 2>&1; then
  HAS_NORMALIZE=1
  STORE_ROOT="$(devflow_normalize_path "$STORE_ROOT_RAW")"
  STAMP="$(devflow_normalize_path "$STAMP_RAW")"
  WS="$(devflow_normalize_path "${GITHUB_WORKSPACE:-}")"
fi

if [ ! -f "$STAMP" ]; then
  echo "::notice::no execution file and the transcript stamp file is absent ($STAMP); selecting nothing from the store (no upload)." >&2
  emit none
  exit 0
fi
if [ ! -d "$STORE_ROOT" ]; then
  echo "::notice::no execution file and the project store root is absent ($STORE_ROOT); nothing to preserve (no upload)." >&2
  emit none
  exit 0
fi

# python3 (a preflight-guaranteed tool, never `find`) selects regular `.jsonl` files newer
# than the stamp and reads each one's first `cwd`-bearing record; the workspace match is
# decided in bash so both cwd forms pass through devflow_normalize_path identically.
SEL="$(STORE_ROOT="$STORE_ROOT" STAMP="$STAMP" python3 - <<'PY'
import os, json, sys
sys.stdout.reconfigure(newline="\n")
root = os.environ["STORE_ROOT"]
try:
    smt = os.stat(os.environ["STAMP"]).st_mtime
except OSError:
    sys.exit(0)
for dirpath, dirnames, filenames in os.walk(root):
    dirnames.sort()
    for name in sorted(filenames):
        if not name.endswith(".jsonl"):
            continue
        full = os.path.join(dirpath, name)
        if os.path.islink(full) or not os.path.isfile(full):
            continue
        try:
            if not (os.stat(full).st_mtime > smt):
                continue
        except OSError:
            continue
        cwd = ""
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict) and isinstance(rec.get("cwd"), str):
                        cwd = rec["cwd"]
                        break
        except OSError:
            pass
        sys.stdout.write(full + "\t" + cwd + "\n")
PY
)"

SELECTED_ABS=()
SELECTED_REL=()
REJECTED=0
FIRST_CWD=""
while IFS=$'\t' read -r abspath cwd; do
  [ -z "$abspath" ] && continue
  ncwd="$cwd"
  if [ -n "$cwd" ] && [ "$HAS_NORMALIZE" = 1 ]; then
    ncwd="$(devflow_normalize_path "$cwd")"
  fi
  if [ -n "$WS" ] && [ "$ncwd" = "$WS" ]; then
    # Strip the store root and the encoded project directory (the first component), keeping
    # the nesting below it so <session>.jsonl lands at the output root and
    # <session>/subagents/<id>.jsonl beneath it.
    rel="${abspath#"$STORE_ROOT"/}"
    rel="${rel#*/}"
    SELECTED_ABS+=("$abspath")
    SELECTED_REL+=("$rel")
  else
    REJECTED=$((REJECTED + 1))
    [ -z "$FIRST_CWD" ] && [ -n "$cwd" ] && FIRST_CWD="$cwd"
  fi
done <<< "$SEL"

if [ "${#SELECTED_ABS[@]}" -eq 0 ]; then
  if [ "$REJECTED" -gt 0 ]; then
    echo "::notice::no execution file; $REJECTED session file(s) newer than the stamp but none names this job's workspace (first cwd observed: '${FIRST_CWD:-none}'; workspace: '$WS'); nothing uploaded." >&2
  else
    echo "::notice::no execution file and no session file newer than the stamp; nothing to preserve (no upload)." >&2
  fi
  emit none
  exit 0
fi

# The output dir has NO component beginning with `.`: actions/upload-artifact@v4 skips a
# dot-prefixed folder by default, and `if-no-files-found: ignore` would then hide the
# resulting empty upload.
OUTDIR="${RUNNER_TEMP:-/tmp}/prflow-native-transcript"
rm -rf "$OUTDIR" 2>/dev/null
if ! mkdir -p "$OUTDIR"; then
  echo "::warning::could not create the native-transcript output directory ($OUTDIR); NOT uploading (fail-closed)." >&2
  emit none
  exit 0
fi
SHAPES="$(bash "$SCRUBBER" --shapes 2>/dev/null || printf 'a fixed set of credential shapes\n')"
CAVEAT="# DEVFLOW SCRUB CAVEAT (native-session): best-effort blocklist redacted ${SHAPES}. This blocklist is INCOMPLETE — other third-party credential shapes may remain. Treat this artifact as sensitive."

# Scrub top-level `<session>.jsonl` files (rel with no `/`) before any `subagents/` file — the
# order issue #342 mandates. The upload is all-or-nothing: any per-file failure discards OUTDIR
# and a scrub cut short by the cancel window uploads nothing, so this order never ships a partial.
ORDER=()
for i in "${!SELECTED_REL[@]}"; do
  case "${SELECTED_REL[$i]}" in */*) : ;; *) ORDER+=("$i") ;; esac
done
for i in "${!SELECTED_REL[@]}"; do
  case "${SELECTED_REL[$i]}" in */*) ORDER+=("$i") ;; esac
done

for i in "${ORDER[@]}"; do
  src="${SELECTED_ABS[$i]}"
  dest="$OUTDIR/${SELECTED_REL[$i]}"
  if ! mkdir -p "$(dirname "$dest")"; then
    echo "::warning::could not create the output nesting for a native-session file; NOT uploading (fail-closed)." >&2
    rm -rf "$OUTDIR" 2>/dev/null
    emit none
    exit 0
  fi
  scrub_and_caveat "$src" "$dest" "$CAVEAT"
  rc=$?
  case $rc in
    0) : ;;
    1) echo "::warning::native-session scrub failed on a file (scrub-credentials.sh non-zero); NOT uploading (fail-closed)." >&2
       rm -rf "$OUTDIR" 2>/dev/null; emit none; exit 0 ;;
    2) echo "::notice::a scrubbed native-session file is empty; nothing to preserve (no upload)." >&2
       rm -rf "$OUTDIR" 2>/dev/null; emit none; exit 0 ;;
    *) echo "::warning::native-session caveat-header write failed; NOT uploading (fail-closed)." >&2
       rm -rf "$OUTDIR" 2>/dev/null; emit none; exit 0 ;;
  esac
done

echo "::warning::transcript scrub is a best-effort blocklist covering ${SHAPES}; it is INCOMPLETE for third-party credential shapes — treat the uploaded artifact as sensitive." >&2
emit native-session "$OUTDIR"
exit 0

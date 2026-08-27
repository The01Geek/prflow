#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# collect-staged-telemetry.sh <repo_root> <dest>
#
# The upload-side (PR-head, read-only review tier) half of the telemetry relay (issue #489, AC2).
# Consolidate every staged telemetry subtree — <repo_root>/.prflow/tmp/telemetry-stage-*/.prflow/logs
# (left in place by lib/efficiency-trace.sh's staging-only `--persist`) — into <dest>/.prflow/logs,
# preserving the `.prflow/logs/…`-relative paths, so the caller can upload <dest> as one workflow
# artifact for the trusted pusher to download.
#
# Extracted from the workflow's inline shell so lib/test/run.sh can drive it (the repo's
# inline-shell-extraction convention). This collection is BEST-EFFORT: the trusted pusher
# re-validates every entry all-or-nothing (scripts/validate-telemetry-artifact.sh), so a miss
# here can never let an unadmitted path reach the branch — it only affects what is uploaded.
#
# stdout: prints `1` when at least one staged tree was collected (the caller's "something to
# upload" signal), otherwise nothing. Always exits 0 (best-effort).

set -uo pipefail

ROOT="${1:-}"
DEST="${2:-}"
if [ -z "$ROOT" ] || [ -z "$DEST" ]; then
  echo "collect-staged-telemetry: usage: collect-staged-telemetry.sh <repo_root> <dest>" >&2
  exit 0
fi

# Telemetry master switch (issue #2035); contract in telemetry-master-off.py.
# No `dirname`: lib/preflight.sh does not guarantee it. Keep the case guard —
# `%/*` is a NO-OP on a slash-free argv0, emptying the anchor to the script name.
case "${BASH_SOURCE[0]}" in
  */*) _CST_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _CST_DIR="$(pwd)" ;;
esac
# Resolve the config through the same override-then-state-dir ladder --persist
# uses, so the two gates agree on which file to read; hardcoding `.prflow/` here
# would split them on a consumer mid-migration from `.devflow/`.
if [ -z "${DEVFLOW_CONFIG_FILE:-}" ] && [ -r "$_CST_DIR/../lib/resolve-state-dir.sh" ]; then
  # shellcheck source=../lib/resolve-state-dir.sh
  . "$_CST_DIR/../lib/resolve-state-dir.sh" 2>/dev/null || true
fi
if [ -n "${DEVFLOW_CONFIG_FILE:-}" ]; then
  _CST_CFG="$DEVFLOW_CONFIG_FILE"
elif command -v prflow_state_dir >/dev/null 2>&1; then
  _CST_CFG="$(prflow_state_dir "$ROOT")/config.json"
else
  _CST_CFG="$ROOT/.prflow/config.json"
fi
if [ ! -f "$_CST_DIR/telemetry-master-off.py" ]; then
  echo "::warning::collect-staged-telemetry: telemetry-master-off.py not found beside this script — the telemetry.enabled master switch was NOT consulted; collecting as if telemetry were on (issue #2035)" >&2
elif ! command -v python3 >/dev/null 2>&1; then
  echo "::warning::collect-staged-telemetry: python3 not on PATH — the telemetry.enabled master switch was NOT consulted; collecting as if telemetry were on (issue #2035)" >&2
else
  _CST_RC=0
  # Capture the interpreter's stderr rather than discarding it: the predicate is
  # silent on every verdict, so ANY stderr means it did not run (a truncated or
  # unreadable copy), which python3 reports with the same 1 and 2 the verdicts use.
  _CST_ERR="$(python3 "$_CST_DIR/telemetry-master-off.py" "$_CST_CFG" 2>&1 >/dev/null)" || _CST_RC=$?
  if [ "$_CST_RC" -eq 0 ] && [ -z "$_CST_ERR" ]; then
    echo "::warning::collect-staged-telemetry: telemetry.enabled is false — collecting nothing this run (issue #2035)" >&2
    exit 0
  elif [ -n "$_CST_ERR" ]; then
    echo "::warning::collect-staged-telemetry: '$_CST_DIR/telemetry-master-off.py' could not be run — the telemetry.enabled master switch was NOT consulted; collecting as if telemetry were on (issue #2035)" >&2
  elif [ "$_CST_RC" -eq 2 ]; then
    echo "::warning::collect-staged-telemetry: config '$_CST_CFG' exists but could not be read or parsed — the telemetry.enabled master switch was NOT consulted; collecting as if telemetry were on (issue #2035)" >&2
  fi
fi

rm -rf "$DEST" 2>/dev/null || true
mkdir -p "$DEST" || { echo "::warning::collect-staged-telemetry: could not create dest '$DEST'; nothing collected" >&2; exit 0; }

# `saw_stage` records that a staging tree with records existed; `found` records that at
# least one was actually copied. Keeping them distinct lets the caller tell "there was
# genuinely nothing staged" apart from "records existed but every copy failed" — the two
# must not collapse to one "nothing to upload" message (a copy failure is telemetry loss,
# not an empty run).
saw_stage=
found=
for stage in "$ROOT"/.prflow/tmp/telemetry-stage-*/; do
  [ -d "$stage" ] || continue                 # unmatched glob: the literal path is not a dir
  [ -d "${stage}.prflow/logs" ] || continue  # a staging root that produced no records
  saw_stage=1
  # Merge this stage's .prflow/logs subtree into the consolidated dest (records from multiple
  # retained staging roots land under one tree; same-named files simply overwrite).
  if mkdir -p "$DEST/.prflow/logs" && cp -R "${stage}.prflow/logs/." "$DEST/.prflow/logs/"; then
    found=1
  else
    echo "::warning::collect-staged-telemetry: failed to copy '${stage}.prflow/logs' into the upload tree (best-effort; skipping)" >&2
  fi
done

if [ -n "$found" ]; then
  printf '1\n'   # the caller's "something to upload" signal
elif [ -n "$saw_stage" ]; then
  # Staged records existed but none could be collected — name that distinctly, so the
  # caller's "nothing to upload" path never misreports a copy failure as an empty run.
  echo "::warning::collect-staged-telemetry: staged telemetry records existed but none could be copied into the upload tree (see the copy warnings above); nothing uploaded this run — the records were NOT staged empty, the collection failed" >&2
fi
exit 0

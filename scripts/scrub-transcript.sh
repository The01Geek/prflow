#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scrub-transcript.sh — scrub a claude-code-action execution file for upload as a
# run artifact, and advertise the scrubbed path ONLY when it is safe to upload
# (issue #1064 D4). This is the suite-drivable home of the transcript channel's
# scrub / non-empty gate / caveat-prepend / fail-closed SELECTION, so that logic is
# NOT triplicated inline across devflow-runner.yml, devflow-implement.yml and
# devflow.yml (the coupled-mirror hazard CLAUDE.md warns of). The credential blocklist
# itself is the shared scripts/scrub-credentials.sh (one implementation, both channels).
#
# Usage: scrub-transcript.sh <execution_file> <out_file>
#   <execution_file>  steps.claude.outputs.execution_file path.
#   <out_file>        where the scrubbed, caveat-prepended transcript is written.
#
# Prints `path=<out_file>` to stdout ONLY when the scrubbed output is non-empty AND the
# caveat header was prepended successfully — the workflow gates its upload step on that
# line. Prints a `::notice::`/`::warning::` breadcrumb otherwise and NO path line.
# FAILS CLOSED: an absent file, a scrub that cannot run, an empty scrub, or a failed
# caveat write all advertise NOTHING (an unscrubbed or half-written file is never
# uploaded). Always exits 0 (best-effort — an always() step is never aborted).
#
# The caveat header (a `#`-comment line) is prepended so a human reading the artifact
# sees the incomplete-blocklist disclosure first; it deliberately makes the `.json`-named
# artifact non-strict-JSON. The shared transcript reader in scripts/context_eval_shared.py
# is the automated JSON consumer (used by the context-cost instruments,
# scripts/implement-timeline.py and scripts/extract-execution-cost.py) and strips leading
# `#` lines only, so the caveat must stay a `#`-prefixed FIRST line.

set -uo pipefail

_ST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRUBBER="$_ST_DIR/scrub-credentials.sh"

EXECUTION_FILE="${1:-}"
OUT="${2:-}"

if [ -z "$OUT" ]; then
  echo "::warning::scrub-transcript: no output path given; nothing uploaded (fail-closed)" >&2
  exit 0
fi
if [ -z "$EXECUTION_FILE" ] || [ ! -f "$EXECUTION_FILE" ]; then
  echo "::notice::execution file absent; no transcript to preserve." >&2
  exit 0
fi
if [ ! -f "$SCRUBBER" ]; then
  echo "::warning::scrub-transcript: $SCRUBBER missing (a vendored tree pinned to an older prflow_version); NOT uploading the unscrubbed execution file (fail-closed)" >&2
  exit 0
fi

# Scrub to $OUT via the shared blocklist. scrub-credentials.sh fails closed (non-zero,
# no output) when sed cannot run, so a non-zero exit here means DO NOT UPLOAD.
if ! bash "$SCRUBBER" < "$EXECUTION_FILE" > "$OUT" 2>/dev/null; then
  echo "::warning::transcript scrub failed (scrub-credentials.sh non-zero); NOT uploading the unscrubbed execution file (fail-closed)." >&2
  rm -f "$OUT" 2>/dev/null
  exit 0
fi
if [ ! -s "$OUT" ]; then
  echo "::notice::scrubbed transcript is empty; nothing to preserve (no upload)." >&2
  rm -f "$OUT" 2>/dev/null
  exit 0
fi

# One source of truth for the caveat wording — the shared helper names the shapes.
SHAPES="$(bash "$SCRUBBER" --shapes 2>/dev/null || printf 'a fixed set of credential shapes\n')"
CAVEAT="# DEVFLOW SCRUB CAVEAT: best-effort blocklist redacted ${SHAPES}. This blocklist is INCOMPLETE — other third-party credential shapes may remain. Treat this artifact as sensitive."
echo "::warning::transcript scrub is a best-effort blocklist covering ${SHAPES}; it is INCOMPLETE for third-party credential shapes — treat the uploaded artifact as sensitive." >&2
HDR="$OUT.hdr"
if { printf '%s\n' "$CAVEAT" > "$HDR" && cat "$OUT" >> "$HDR" && mv "$HDR" "$OUT"; }; then
  printf 'path=%s\n' "$OUT"
else
  rm -f "$HDR" 2>/dev/null
  echo "::warning::transcript caveat-header write failed; NOT uploading the transcript (fail-closed)." >&2
fi
exit 0

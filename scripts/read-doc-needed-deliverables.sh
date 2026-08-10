#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# read-doc-needed-deliverables.sh — read one issue's Documentation-Needed
# deliverable paths and report the outcome as an observable token (issue #1554).
#
# Why a helper rather than inline shell in the phase file: Phase 4.1 Stage 1 and
# Stage 2 both need this read, and inline shell in agent-executed prose has no
# executable boundary the suite can drive, so its retry and fail-closed arms were
# reachable by no test. Here lib/test/run.sh drives every arm directly, and the
# caller reads the deliverable list from this command's stdout rather than from a
# shell variable that does not survive to the next tool call.
#
# TOKEN VOCABULARY (closed; line 1 of stdout is always one of these):
#
#   deliverables       the body was read and the extraction returned >=1 path
#   no-deliverables    the body was read and the extraction returned no path
#   body-read-failed   both `gh issue view` attempts failed
#   extract-failed     both extractor attempts failed
#
# EXIT STATUSES (closed; one status per token, success disjoint from failure):
#
#   0   deliverables       |  11  body-read-failed
#   10  no-deliverables    |  12  extract-failed
#
# A usage error (a missing or non-numeric issue number) prints NO token and exits
# 2, which is outside the closed set above and is the caller's residual arm — as
# is any status this header does not pair with the token that was printed.
#
# Usage: read-doc-needed-deliverables.sh <issue-number>
# stdout: line 1 = the token; on `deliverables`, one path per line after it.
#
# Failing the read means the deliverable list is UNKNOWN, never empty: a caller
# that treats a failure token as `no-deliverables` waves the gate through exactly
# when it could not read what the gate enforces. `gh` writes HTTP error bodies to
# stdout, so the read is judged by its own exit status, never by the capture being
# non-empty.
#
# Test seams, both honoured verbatim with no probe: DEVFLOW_GH (the shared
# resolver's own override) selects the `gh` binary, and
# DEVFLOW_DOC_NEEDED_EXTRACTOR selects the extractor, so the suite can drive the
# extractor-failure arm without a failing `gh`.

set -uo pipefail

ISSUE="${1:-}"
case "$ISSUE" in
  '' | *[!0-9]*)
    echo "devflow: read-doc-needed-deliverables.sh: usage: read-doc-needed-deliverables.sh <issue-number>" >&2
    exit 2
    ;;
esac

# Pure-bash directory derivation (no `dirname`), matching the resolver family.
case "${BASH_SOURCE[0]}" in
  */*) _RDND_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _RDND_DIR="$(pwd)" ;;
esac

# shellcheck source=../lib/resolve-gh.sh
. "$_RDND_DIR/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

EXTRACTOR="${DEVFLOW_DOC_NEEDED_EXTRACTOR:-$_RDND_DIR/extract-doc-needed-paths.sh}"

DEVFLOW_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SCRATCH="$DEVFLOW_ROOT/.prflow/tmp"
BODY_FILE="$SCRATCH/devflow-docgate-body-$ISSUE.txt"
GH_ERR_FILE="$SCRATCH/devflow-docgate-gh.err"

# An unusable scratch leaf leaves the body unread, which is a read failure and
# never an empty deliverable list.
if ! mkdir -p "$SCRATCH"; then
  echo "devflow: could not create $SCRATCH for the Documentation Needed gate" >&2
  printf '%s\n' body-read-failed
  exit 11
fi
rm -f "$BODY_FILE" "$GH_ERR_FILE"

# Read and retry, each attempt judged by its own exit status inline.
if ! "$DEVFLOW_GH" issue view "$ISSUE" --json body --jq '.body' > "$BODY_FILE" 2>"$GH_ERR_FILE" \
   && ! "$DEVFLOW_GH" issue view "$ISSUE" --json body --jq '.body' > "$BODY_FILE" 2>"$GH_ERR_FILE"; then
  printf '%s\n' body-read-failed
  exit 11
fi

if ! DOC_NEEDED_PATHS="$("$EXTRACTOR" < "$BODY_FILE")" \
   && ! DOC_NEEDED_PATHS="$("$EXTRACTOR" < "$BODY_FILE")"; then
  printf '%s\n' extract-failed
  exit 12
fi

if [ -z "$DOC_NEEDED_PATHS" ]; then
  printf '%s\n' no-deliverables
  exit 10
fi

printf '%s\n' deliverables
printf '%s\n' "$DOC_NEEDED_PATHS"
exit 0

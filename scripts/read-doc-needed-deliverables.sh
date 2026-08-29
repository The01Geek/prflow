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
# TOKEN VOCABULARY (closed):
#
#   deliverables       the body was read and the extraction returned >=1 path
#   no-deliverables    the body was read and the extraction returned no path
#   body-read-failed   the body could not be read — the gh resolver was
#                      unsourceable, the scratch leaf was uncreatable, or both
#                      `gh issue view` attempts failed
#   extract-failed     both extractor attempts failed
#
# EXIT STATUSES (closed; one status per token, success disjoint from failure):
#
#   0   deliverables       |  11  body-read-failed
#   10  no-deliverables    |  12  extract-failed
#
# A usage error (a missing or non-numeric issue number) prints NO token and exits
# 64 (EX_USAGE), which is outside the closed set above and is the caller's residual
# arm — as is any status this header does not pair with the token that was printed.
# 64 rather than 2 keeps the arm from colliding with `scripts/preflight.py`'s
# three-class contract, where 2 means BLOCKED — a decided answer, not a bad call.
#
# Usage: read-doc-needed-deliverables.sh <issue-number>
#
# STDOUT SHAPE — each line is SELF-IDENTIFYING BY PREFIX, never by position:
#
#   docgate-outcome: <token>     exactly one, on every non-usage exit
#   docgate-suppressed: <span>   at most one, after the outcome line and only on a
#                                success token — the FIRST span the extractor
#                                suppressed, with the breadcrumb's surrounding
#                                backticks removed (issue #2129)
#   docgate-path: <path>         zero or more, one per deliverable, after the
#                                outcome line and only on `deliverables`
#
# The prefixes are load-bearing, not decoration. The caller is an agent reading a
# tool result that merges this command's stdout with the stderr of `gh` and of the
# extractor — and the extractor emits a `suppressed a span` breadcrumb on stderr for
# exactly the adversarial bodies this gate exists to handle. A positional "line 1 is
# the token" contract would read that breadcrumb as the token on a read that
# succeeded, and would read an interleaved stderr line as a deliverable path. This
# helper captures the extractor's stderr to a scratch file, forwards it UNCHANGED to
# its own stderr (so the merged stream still carries every breadcrumb), and relays
# the first `suppressed a span` breadcrumb's span onto stdout as the self-identifying
# `docgate-suppressed: ` line above, so Phase 4.1 records a real span rather than a
# scripted once-per-run note (issue #2129).
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

set -u

ISSUE="${1:-}"
case "$ISSUE" in
  '' | *[!0-9]*)
    echo "devflow: read-doc-needed-deliverables.sh: usage: read-doc-needed-deliverables.sh <issue-number>" >&2
    exit 64
    ;;
esac

# Pure-bash directory derivation (no `dirname`), matching the resolver family.
case "${BASH_SOURCE[0]}" in
  */*) _RDND_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _RDND_DIR="$(pwd)" ;;
esac

# Guarded source with an OUTCOME check (never a bare `[ -f ]` precondition, which
# proves the path exists and nothing about whether the function is callable). The
# resolver owns every fallback, including the bare-`gh` one, so this caller invents
# none: an unsourceable resolver is a packaging fault, and reporting it as its own
# breadcrumb plus the read-failure token beats naming GitHub for it.
# shellcheck source=../lib/resolve-gh.sh
if [ -f "$_RDND_DIR/../lib/resolve-gh.sh" ] \
   && . "$_RDND_DIR/../lib/resolve-gh.sh" \
   && type devflow_resolve_gh >/dev/null 2>&1; then
  : "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
else
  echo "devflow: lib/resolve-gh.sh is not sourceable beside read-doc-needed-deliverables.sh (partial deployment) — the issue body cannot be read" >&2
  printf 'docgate-outcome: %s\n' body-read-failed
  exit 11
fi

EXTRACTOR="${DEVFLOW_DOC_NEEDED_EXTRACTOR:-$_RDND_DIR/extract-doc-needed-paths.sh}"

DEVFLOW_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SCRATCH="$DEVFLOW_ROOT/.prflow/tmp"
BODY_FILE="$SCRATCH/devflow-docgate-body-$ISSUE.txt"

# An unusable scratch leaf leaves the body unread, which is a read failure and
# never an empty deliverable list.
if ! mkdir -p "$SCRATCH"; then
  echo "devflow: could not create $SCRATCH for the Documentation Needed gate" >&2
  printf 'docgate-outcome: %s\n' body-read-failed
  exit 11
fi
# Drop any stale capture first, so a body left by a prior invocation can never be
# extracted from after a read that failed.
rm -f "$BODY_FILE"

# Read and retry, each attempt judged by its own exit status inline. gh's stderr
# is deliberately NOT captured to a file: it flows to the caller, where the run
# can actually read why a failed read failed. The prefixed stdout shape above is
# what keeps that interleaving from corrupting the outcome the caller reads.
if ! "$DEVFLOW_GH" issue view "$ISSUE" --json body --jq '.body' > "$BODY_FILE" \
   && ! "$DEVFLOW_GH" issue view "$ISSUE" --json body --jq '.body' > "$BODY_FILE"; then
  printf 'docgate-outcome: %s\n' body-read-failed
  exit 11
fi

# Capture the extractor's stderr to a scratch file so its `suppressed a span`
# breadcrumb can be parsed (issue #2129) — the breadcrumb is the only channel that
# names the span. The file is TRUNCATED (not appended) on each attempt, so a retry
# overwrites the prior attempt's stderr rather than accumulating it.
EXTRACTOR_ERR="$SCRATCH/devflow-docgate-extractor-err-$ISSUE.txt"
rm -f "$EXTRACTOR_ERR"

# _rdnd_relay_extractor_stderr — forward the captured extractor stderr UNCHANGED to
# this helper's own stderr (so the merged tool result still carries every
# breadcrumb the caller relied on), and set SUPPRESSED_SPAN to the FIRST
# `suppressed a span` breadcrumb's span text with the breadcrumb's surrounding
# backticks removed. Bash builtins only (`case`, `while IFS= read -r`, `${var#…}`/
# `${var%…}`): the value decides an emitted stdout line, so it must not depend on a
# tool lib/preflight.sh does not guarantee.
SUPPRESSED_SPAN=""
_rdnd_relay_extractor_stderr() {
  [ -f "$EXTRACTOR_ERR" ] || return 0
  local _line _span
  while IFS= read -r _line; do
    printf '%s\n' "$_line" >&2
    case "$_line" in
      *"suppressed a span"*)
        if [ -z "$SUPPRESSED_SPAN" ]; then
          # Parses suppress_span() in extract-doc-needed-paths.sh: first backtick to
          # last, so a backtick added to that breadcrumb's text relays the wrong span.
          _span="${_line#*\`}"
          _span="${_span%\`}"
          SUPPRESSED_SPAN="$_span"
        fi
        ;;
    esac
  done < "$EXTRACTOR_ERR"
}

if ! DOC_NEEDED_PATHS="$("$EXTRACTOR" < "$BODY_FILE" 2>"$EXTRACTOR_ERR")" \
   && ! DOC_NEEDED_PATHS="$("$EXTRACTOR" < "$BODY_FILE" 2>"$EXTRACTOR_ERR")"; then
  _rdnd_relay_extractor_stderr
  printf 'docgate-outcome: %s\n' extract-failed
  exit 12
fi

_rdnd_relay_extractor_stderr

if [ -z "$DOC_NEEDED_PATHS" ]; then
  printf 'docgate-outcome: %s\n' no-deliverables
  [ -n "$SUPPRESSED_SPAN" ] && printf 'docgate-suppressed: %s\n' "$SUPPRESSED_SPAN"
  exit 10
fi

printf 'docgate-outcome: %s\n' deliverables
[ -n "$SUPPRESSED_SPAN" ] && printf 'docgate-suppressed: %s\n' "$SUPPRESSED_SPAN"
# Read line-wise rather than word-splitting, so a path carrying whitespace stays
# one deliverable instead of becoming several.
printf '%s\n' "$DOC_NEEDED_PATHS" | while IFS= read -r _rdnd_path; do
  printf 'docgate-path: %s\n' "$_rdnd_path"
done
exit 0

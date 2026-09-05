#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compose-run-key.sh — print the review engine's per-run scratch key (issue #64).
#
# WHY A HELPER, not an agent-composed string: the review loop's scratch run key was
# derived in agent prose from a leading `VAR=` shell assignment carrying a command
# substitution — a shape the cloud command matcher refuses before it runs, printing
# nothing, so the agent held no computed key and scoped its scratch under a guess. This
# helper is the SINGLE place the scratch run key is composed; its consumers
# (skills/review-and-fix/references/loop-control.md, skills/review/phases/phase-0-setup.md)
# observe THIS helper's stdout instead of composing their own, so there is nothing left
# for the agent to invent. The progress-comment marker keeps its own derivation in
# scripts/seed-review-progress.sh; this helper owns only the scratch run key.
#
# CONTRACT — one line on stdout:
#   <GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>   exit 0, when GITHUB_RUN_ID has a non-whitespace
#                                          character (the attempt reads as 1 when
#                                          GITHUB_RUN_ATTEMPT is unset or empty; a
#                                          runner-supplied value is used verbatim, never
#                                          rewritten). This is the same identity
#                                          lib/efficiency-trace.sh keys its floors on.
#   local-<UTC timestamp>-1                exit 0, when GITHUB_RUN_ID is unset, empty, or
#                                          whitespace-only; timestamp formatted %Y%m%dT%H%M%SZ.
# On the local arm, when `date -u` fails the helper prints nothing to stdout, writes one
# breadcrumb line to stderr, and exits 1 — a run key is never guessed downstream.
#
# The cloud arm is bash parameter substitution only — no tr/sed/cut/printf-format tricks —
# because lib/preflight.sh guarantees only git/gh/jq/python3 and a value deciding an emitted
# result must not route through a non-preflight PATH tool that fails open (CLAUDE.md).
set -uo pipefail

run_id="${GITHUB_RUN_ID:-}"
run_attempt="${GITHUB_RUN_ATTEMPT:-}"

# A whitespace-only GITHUB_RUN_ID is treated as absent (fail closed to the local arm),
# matching scripts/seed-review-progress.sh's own `${RUN_ID//[[:space:]]/}` normalization so
# the two derivations agree on "what counts as a usable cloud run." The `//[[:space:]]/`
# strip is applied to the emptiness TEST only; the emitted key uses the original value.
if [ -n "${run_id//[[:space:]]/}" ]; then
  printf '%s\n' "${run_id}-${run_attempt:-1}"
else
  if ! ts="$(date -u +%Y%m%dT%H%M%SZ)"; then
    echo "compose-run-key.sh: date -u failed; cannot compose a local run key" >&2
    exit 1
  fi
  printf '%s\n' "local-${ts}-1"
fi
exit 0

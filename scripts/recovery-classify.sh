#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# recovery-classify.sh — pure classifier for the cloud /prflow:implement Spot-reclaim
# recovery job (issue #258).
#
# When a heavy `claude` job ends `cancelled` or `failure`, a downstream recovery
# job must decide WHY before it acts: an intentional human cancellation stays a
# decided terminal end (never auto-resumed), while an EC2 Spot reclaim — proven by
# an authenticated, exactly-bound reclaim marker the in-job watcher posted while the
# runner was still alive — takes the existing capped resume path. Everything else is
# unclassifiable and gets no reclaim-specific recovery. This helper is the decision
# *core*, deliberately extracted from the workflow YAML so the test suite can drive
# its decision branches deterministically with normalized inputs — it does NO I/O (no
# gh/jq/network); the caller derives every input from the paginated Actions jobs
# API, the Checks annotations API, and the reclaim-marker comment before calling.
#
# Usage:
#   recovery-classify.sh HUMAN_CANCEL_ANNOTATION MARKER_PRESENT MARKER_AUTHOR_OK \
#                        MARKER_REPO_MATCH MARKER_RUN_ID_MATCH \
#                        MARKER_RUN_ATTEMPT_MATCH MARKER_JOB_ID_MATCH
#
# Every argument is a pre-normalized flag: ONLY the exact literal string "true"
# counts as true; every other value (empty, missing, "false", "1", "TRUE", an
# unrecognized token) is treated as false. This is the fail-safe direction — a
# false positive on `reclaim` is the dangerous outcome (it would auto-resume an
# intentionally-cancelled run), so anything not provably true fails toward
# `unclassifiable`. HUMAN_CANCEL_ANNOTATION is not a free pass: when a full valid
# marker is also present, an ambiguous (non-"true") human-cancel flag falls through
# to `reclaim` — the dangerous direction. This pure helper cannot re-derive the
# annotation, so the caller carries the obligation to normalize HUMAN_CANCEL_ANNOTATION
# at least as robustly as the binding flags, preferring to over-report human-cancel.
#
#   HUMAN_CANCEL_ANNOTATION  "true" when the check-run annotations carry the
#                            platform's EXPLICIT human-cancellation text (e.g.
#                            "The run was canceled by @<user>"). A generic platform
#                            annotation ("The operation was canceled.") is NOT
#                            explicit and the caller passes "false" for it.
#   MARKER_PRESENT           "true" when a structurally valid reclaim-marker comment
#                            was found on the issue at all.
#   MARKER_AUTHOR_OK         "true" when that comment's API-reported author is a
#                            trusted bot (user.type == "Bot"), read from the API
#                            response and never from a claim in the marker body — so
#                            a marker from a human author never reclaims. The caller
#                            cannot pin one fixed bot login: the in-job watcher posts
#                            the marker with the consumer's own App token when one is
#                            configured (the only setup in which the downstream
#                            resume, itself App-token-gated, can fire) and with
#                            github-actions[bot] otherwise, so the trusted login
#                            varies by consumer. A byte-identical marker from a
#                            DIFFERENT trusted App installed on the repo is therefore
#                            an accepted residual, bounded by the lifetime attempt cap
#                            and requiring a second issues:write App already on the
#                            repo.
#   MARKER_REPO_MATCH        "true" when the marker's repo binding equals the run
#                            under evaluation.
#   MARKER_RUN_ID_MATCH      "true" when the marker's run-id binding matches.
#   MARKER_RUN_ATTEMPT_MATCH "true" when the marker's run-attempt binding matches
#                            (a foreign attempt — e.g. an above-one on-demand retry
#                            — never reclaims).
#   MARKER_JOB_ID_MATCH      "true" when the marker's job-id binding matches.
#
# Prints exactly one decision token to stdout and exits 0:
#   human-cancel    explicit human-cancellation annotation present. This OUTRANKS a
#                   valid reclaim marker (a maintainer who explicitly cancelled
#                   wins over any pre-existing reclaim evidence) — no resume.
#   reclaim         no explicit human cancellation AND a present, bot-authored
#                   marker bound to the exact repo, run, attempt, and job.
#   unclassifiable  every remaining input — no marker, wrong author, any single
#                   binding mismatch, or any malformed flag. No reclaim-specific
#                   recovery.
set -uo pipefail

human_cancel="${1-}"
marker_present="${2-}"
author_ok="${3-}"
repo_match="${4-}"
run_id_match="${5-}"
run_attempt_match="${6-}"
job_id_match="${7-}"

# AC10: human-cancel outranks reclaim — this check must stay ahead of the reclaim block.
if [ "$human_cancel" = "true" ]; then
  echo human-cancel
  exit 0
fi

# All six conditions must hold for reclaim; never loosen this AND to an OR — any
# non-"true" must fall through to unclassifiable (a false reclaim auto-resumes a cancel).
if [ "$marker_present" = "true" ] \
  && [ "$author_ok" = "true" ] \
  && [ "$repo_match" = "true" ] \
  && [ "$run_id_match" = "true" ] \
  && [ "$run_attempt_match" = "true" ] \
  && [ "$job_id_match" = "true" ]; then
  echo reclaim
  exit 0
fi

echo unclassifiable
exit 0

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compose-run-url.sh — print the review progress comment's `**Run:**` link (issue #1536).
#
# WHY A HELPER, not an agent-composed string: the review progress comment's run link was
# assembled in agent prose from an unobservable shell assignment, so the agent filled it in
# from a guess — yielding a wrong repository owner or an unexpanded literal on real runs. This
# helper is the SINGLE place the run link is composed; both consumers (skills/review/SKILL.md
# and scripts/seed-review-progress.sh) observe THIS helper's stdout instead of composing their
# own, so there is nothing left for the agent to invent.
#
# CONTRACT — one line on stdout, exit 0 on every path:
#   [View run](<server>/<repo>/actions/runs/<id>)   when GITHUB_SERVER_URL, GITHUB_REPOSITORY,
#                                                    and GITHUB_RUN_ID are ALL non-empty
#   _(local run)_                                    when ANY one of them is empty/unset
#
# The guard fails CLOSED: with a single segment empty it prints `_(local run)_` rather than a
# URL carrying an empty segment (`https://…//actions/runs/…` or a run id-less tail), so a
# partial cloud environment never yields a broken link. The composition is bash parameter
# substitution only — no tr/sed/cut/printf-format tricks — because lib/preflight.sh guarantees
# only git/gh/jq/python3 and a value deciding the emitted result must not route through a
# non-preflight PATH tool that fails open by yielding an empty string (CLAUDE.md).
set -uo pipefail

server="${GITHUB_SERVER_URL:-}"
repo="${GITHUB_REPOSITORY:-}"
run_id="${GITHUB_RUN_ID:-}"

if [ -n "$server" ] && [ -n "$repo" ] && [ -n "$run_id" ]; then
  printf '%s\n' "[View run](${server}/${repo}/actions/runs/${run_id})"
else
  printf '%s\n' "_(local run)_"
fi
exit 0

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scrub-credentials.sh — the SINGLE shared credential-shape scrub (issue #1064 D4).
# Reads text on stdin, writes the scrubbed text to stdout, and is the one
# implementation BOTH durable channels that persist harness-side text use:
#   1. the execution-transcript artifact (devflow-runner.yml + the live tiers), and
#   2. the denied-command text a denial record persists (scripts/build-denial-record.sh).
# Extracting it here means the blocklist is maintained in one place rather than
# copied inline across three workflows (the coupled-mirror hazard CLAUDE.md warns of).
#
# THE SCRUB IS A BLOCKLIST, THEREFORE INCOMPLETE. It redacts four credential SHAPES
# (see $SHAPES below); a novel third-party credential shape can survive. Every
# consumer must disclose that caveat in whatever it persists — never claim redaction.
#
# FAIL CLOSED (issue #1064 AC4). If `sed` cannot run — absent from PATH, or it exits
# non-zero on the input — this helper writes NOTHING to stdout and exits NON-ZERO, so
# the caller persists nothing rather than an unscrubbed payload. `sed` is NOT a
# preflight prerequisite (lib/preflight.sh guarantees only git/gh/jq/python3), so its
# absence is a real, handled arm, not a theoretical one. This scrub is a REDACTING
# TRANSFORM, not a selection/emission value, so `sed -E` is the sanctioned carve-out
# to the guard-class-2 builtins-only rule (CLAUDE.md / issue #1064 AC9) — its absence
# fails closed, which is exactly what that rule requires of the exception.
#
# PORTABLE (issue #1064 AC10): `sed -E` (POSIX/BSD-safe) — never GNU `sed -r`/`grep -P`.
# The header NAME is matched case-insensitively with an explicit per-letter class
# (`[Aa][Uu]…`) rather than the GNU-only `I` flag, because actions/checkout's
# git-auth-helper persists the extraheader as UPPERCASE `AUTHORIZATION:`.
#
# Usage:
#   scrub-credentials.sh            # stdin -> scrubbed stdout; exit 0 ok, non-zero fail-closed
#   scrub-credentials.sh --shapes   # print the one-line human name of the redacted shapes
#
# The `--shapes` mode is the single source of truth for the caveat wording, so a
# channel's artifact caveat and its log warning cannot drift from the actual rules.

set -uo pipefail

# One source of truth for the four redacted shapes (GitHub tokens/PATs is one family
# spanning the two gh[pousr]_/github_pat_ rules), interpolated into every caller's
# caveat + warning so they cannot disagree with the rules below.
SHAPES="GitHub tokens/PATs, Anthropic keys, Bearer Authorization headers, and basic Authorization headers"

if [ "${1:-}" = "--shapes" ]; then
  printf '%s\n' "$SHAPES"
  exit 0
fi

# Probe sed runnability first (network/auth-free) so an absent/broken sed fails closed
# with a breadcrumb rather than an unscrubbed passthrough. `printf | sed` over a tiny
# fixed input: a working sed echoes it back; anything else is treated as unavailable.
if ! printf 'x\n' | sed -E 's/x/x/' >/dev/null 2>&1; then
  echo "devflow: scrub-credentials.sh: sed is not runnable (not on PATH, or failed the probe) — refusing to emit unscrubbed text (fail-closed)" >&2
  exit 3
fi

# The blocklist, single-sourced here (originally devflow-runner.yml's inline scrub, issue
# #409 item 4 for the two Authorization forms; the Authorization rules have since diverged).
# Never list `\` inside the two Authorization bracket expressions and never relax `{4,}`
# back to `+`: a POSIX bracket expression takes `\` as a set member, so the token match
# swallows a following JSON escape backslash, and `+` matches a bare `//` as a token.
if ! sed -E \
  -e 's/gh[pousr]_[A-Za-z0-9_]{20,}/[REDACTED-GH-TOKEN]/g' \
  -e 's/github_pat_[A-Za-z0-9_]{20,}/[REDACTED-GH-PAT]/g' \
  -e 's/sk-ant-[A-Za-z0-9_-]{20,}/[REDACTED-ANTHROPIC-KEY]/g' \
  -e 's/([Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn][":[:space:]]*)[Bb]earer [A-Za-z0-9._~+/=-]{4,}/\1Bearer [REDACTED]/g' \
  -e 's/([Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn][":[:space:]]*)[Bb]asic [A-Za-z0-9+/=]{4,}/\1basic [REDACTED]/g'; then
  echo "devflow: scrub-credentials.sh: sed exited non-zero on the input — emitting nothing (fail-closed)" >&2
  exit 4
fi
exit 0

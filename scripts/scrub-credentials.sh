#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scrub-credentials.sh — the SINGLE shared credential-shape scrub (issue #1064 D4).
# Reads text on stdin, writes the scrubbed text to stdout, and is the one
# implementation BOTH durable channels that persist harness-side text use:
#   1. the execution-transcript artifact (the live tiers), and
#   2. the denied-command text a denial record persists (scripts/build-denial-record.sh).
# Extracting it here means the blocklist is maintained in one place rather than
# copied inline across three workflows (the coupled-mirror hazard CLAUDE.md warns of).
#
# THE SCRUB IS A BLOCKLIST, THEREFORE INCOMPLETE. It redacts a fixed set of credential
# SHAPES (see $SHAPES below); a novel third-party credential shape can survive. Every
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

# One source of truth for the redacted shapes (GitHub tokens/PATs is one family
# spanning the two gh[pousr]_/github_pat_ rules), interpolated into every caller's
# caveat + warning so they cannot disagree with the rules below.
SHAPES="GitHub tokens/PATs, Anthropic keys, Bearer Authorization headers, basic Authorization headers, AWS access key IDs, npm tokens, Slack tokens, GitLab tokens, connection-string passwords, Password=/Pwd= values, and PEM private keys"

if [ "${1:-}" = "--shapes" ]; then
  printf '%s\n' "$SHAPES"
  exit 0
fi

# Probe sed runnability first (network/auth-free) so an absent/broken sed fails closed
# with a breadcrumb rather than an unscrubbed passthrough. `printf | sed` over a tiny
# fixed input: a working sed echoes it back; anything else is treated as unavailable.
if ! printf 'x\n' | sed -E 's/x/x/' >/dev/null 2>&1; then
  echo "prflow: scrub-credentials.sh: sed is not runnable (not on PATH, or failed the probe) — refusing to emit unscrubbed text (fail-closed)" >&2
  exit 3
fi

# Never widen these two token groups to match a bare `\` and never relax `{4,}` back to `+`:
# a bare `\` swallows the JSON escape before a closing quote and truncates the document, while
# `+` matches the bare `//` of a recorded `sed 's/AUTHORIZATION: basic //'` as if it were a token.
# The value-matching rules further down never consume a `"` or a bare `\`, so a rule stops before a
# JSON `\"` boundary instead of swallowing it and truncating the document. The URL/connection-string
# password and Password=/Pwd= rules match a NEGATED class that excludes the value's terminator
# (`@`, or `;`/whitespace per the issue's Password= criterion) plus `"` and `\`, ALTERNATED with the
# `\\` and `\/` escape UNITS (exactly as the Bearer/basic rules do) — so a JSON-escaped backslash or
# slash INSIDE the secret is redacted while a lone `\"` boundary is still left intact. The whole
# secret is redacted — a `:`, `#`, `/`, `@` or `,` INSIDE the value included — while the escape and
# string boundaries survive. The URL password class deliberately KEEPS `/`: `X:Y/Z@W` is structurally
# ambiguous between a `user:password@host` whose password contains `/` and a `host:port/path@ref`
# with no credential, so this fail-closed scrub redacts through the `@` in both — over-redacting a
# rare non-secret token is acceptable; leaking a password that contains a `/` is not. The PEM rule anchors on BOTH
# markers: a POSITIVE base64 class plus the `\n`/`\r`/`\/`/`\\` escape UNITS between `-----BEGIN … PRIVATE
# KEY-----` and the matching `-----END … PRIVATE KEY-----`, so redaction stops AT the end marker and
# any content after it (a thinking block's trailing prose) survives (AC1). A second BEGIN-anchored
# rule (base64 body only, no bare space) fails closed on a truncated key with no END marker, stopping
# at the first non-base64 byte so it cannot eat surrounding prose. The `\/` and `\\` units (like the
# Bearer/basic rules) keep a `/`-escaped base64 body fully redacted, and keep a body whose
# newlines are DOUBLY escaped (`\\n`, the shape a JSON document embedded as a string inside
# another JSON document takes) redacted through its END marker instead of leaking from the first
# `\\` onward. `\\` is a TWO-backslash unit, so a lone `\` before a closing `\"` is still left to
# the document and the transcript stays parseable. Their `#` delimiter carries the
# literal `/` a URL or base64 value contains without escaping it.
if ! sed -E \
  -e 's/gh[pousr]_[A-Za-z0-9_]{20,}/[REDACTED-GH-TOKEN]/g' \
  -e 's/github_pat_[A-Za-z0-9_]{20,}/[REDACTED-GH-PAT]/g' \
  -e 's/sk-ant-[A-Za-z0-9_-]{20,}/[REDACTED-ANTHROPIC-KEY]/g' \
  -e 's#([Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn][":[:space:]]*)[Bb][Ee][Aa][Rr][Ee][Rr] ([A-Za-z0-9._~+/=-]|\\\\|\\/){4,}#\1Bearer [REDACTED]#g' \
  -e 's#([Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn][":[:space:]]*)[Bb][Aa][Ss][Ii][Cc] ([A-Za-z0-9+/=]|\\\\|\\/){4,}#\1basic [REDACTED]#g' \
  -e 's#-----BEGIN[ A-Za-z0-9]*PRIVATE KEY-----([A-Za-z0-9+/=]|\\n|\\r|\\/|\\\\)*-----END[ A-Za-z0-9]*PRIVATE KEY-----#[REDACTED-PRIVATE-KEY]#g' \
  -e 's#-----BEGIN[ A-Za-z0-9]*PRIVATE KEY-----([A-Za-z0-9+/=]|\\n|\\r|\\/|\\\\)*#[REDACTED-PRIVATE-KEY]#g' \
  -e 's/(AKIA|ASIA)[A-Z0-9]{16}/[REDACTED-AWS-ACCESS-KEY-ID]/g' \
  -e 's/npm_[A-Za-z0-9]{20,}/[REDACTED-NPM-TOKEN]/g' \
  -e 's/xox[abposr]-[A-Za-z0-9-]{10,}/[REDACTED-SLACK-TOKEN]/g' \
  -e 's/glpat-[A-Za-z0-9_-]{20,}/[REDACTED-GITLAB-TOKEN]/g' \
  -e 's#(://[A-Za-z0-9._~%+-]*:)([^@"[:space:]\\]|\\\\|\\/)+@#\1[REDACTED-URL-PASSWORD]@#g' \
  -e 's#([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]=|[Pp][Ww][Dd]=)([^;"[:space:]\\]|\\\\|\\/)+#\1[REDACTED-PASSWORD]#g'; then
  echo "prflow: scrub-credentials.sh: sed exited non-zero on the input — emitting nothing (fail-closed)" >&2
  exit 4
fi
exit 0

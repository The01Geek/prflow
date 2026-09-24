#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# extract-denied-command-line.sh — pull the `permission_denials_commands:` line's
# value out of extract-execution-shape.sh's rendered block (issue #908 review,
# Important finding #3: this SELECTION lived only as an inline `case`/here-string
# loop in devflow-runner.yml's `denied-commands` step, covered only by an
# invocation pin rather than a suite-drivable helper).
#
# Uses only a bash builtin `case` over a line read with `while IFS= read -r` (never
# sed/grep) — CLAUDE.md guard-class 2: a value that decides a SELECTION must not be
# derived through a non-preflight PATH tool. Mirrors the
# scripts/surface-execution-diagnostics.sh `_publish_denials()` prefix-extraction
# pattern for the sibling `permission_denials_count` line.
#
# Usage: extract-denied-command-line.sh EES_RC <<< "$BLOCK"
#   EES_RC  extract-execution-shape.sh's captured exit status (an integer). A
#           nonzero value means the block must NOT be parsed — a truncated/partial
#           line would otherwise be published as authoritative.
#   stdin   the rendered block (extract-execution-shape.sh's stdout).
# Prints two lines to stdout and always exits 0:
#   line 1: "found" | "not-found" | "rc-nonzero"
#   line 2: the extracted value (only when line 1 is "found"; empty otherwise)

set -u

EES_RC="${1:-0}"

if [ "$EES_RC" -ne 0 ]; then
  printf 'rc-nonzero\n\n'
  exit 0
fi

_found=0
_value=""
while IFS= read -r _line; do
  _line="${_line%$'\r'}"  # a CRLF block (native Windows jq.exe upstream)
  case "$_line" in
    "permission_denials_commands: "*)
      _value="${_line#permission_denials_commands: }"
      _found=1
      break
      ;;
  esac
done

if [ "$_found" -eq 1 ]; then
  printf 'found\n%s\n' "$_value"
else
  printf 'not-found\n\n'
fi
exit 0

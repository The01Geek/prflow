#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compare-crlf.sh — CRLF-insensitive whole-file text comparison with bash builtins ONLY.
#
# The comparison DECIDES a stop (install.sh's installer self-check refuses a mismatched
# apply) and a warning (scaffold-config.sh's stale-copy scan), so it must never route
# through cmp/tr/sed: none is a preflight-guaranteed tool, and a host missing one would
# silently read as a match and skip the stop it is meant to fire.
#
# COUPLED SITE: install.sh carries an inline duplicate of these functions. It cannot source
# this file — a pre-fix release tree ($SRC) lacks lib/compare-crlf.sh, and a `curl … | bash`
# installer has nothing on disk to source — so edit this file and install.sh together.

# All CR bytes removed from $1, printed with no trailing newline. `${var//$'\r'/}` is a
# bash builtin parameter expansion; no external tool runs.
devflow_strip_cr() { printf '%s' "${1//$'\r'/}"; }

# True when files $1 and $2 have identical bytes after CR removal. `read -r -d ''` reads to
# EOF (the NUL delimiter is absent from text) into the variable, returning non-zero at EOF —
# hence `|| :` — while still populating it; an unreadable/absent file yields an empty string.
devflow_files_match_crlf_insensitive() {
  local _a="" _b=""
  IFS= read -r -d '' _a < "$1" 2>/dev/null || :
  IFS= read -r -d '' _b < "$2" 2>/dev/null || :
  [ "$(devflow_strip_cr "$_a")" = "$(devflow_strip_cr "$_b")" ]
}

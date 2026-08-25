#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# normalize-path.sh — convert a Windows-form path (`C:\...` or `C:/...`) into
# the POSIX form the CURRENTLY RUNNING shell expects: WSL bash wants
# /mnt/c/..., Git Bash / MSYS2 wants /c/... (issue #247). Runner-provided
# paths (for example the skill-dir anchor a non-Claude-Code runner reports)
# can arrive in Windows form; handing such a path to a POSIX shell fails.
#
# Non-Windows-form input passes through unchanged and consults no tool — zero
# behavior change on Linux/macOS/cloud. UNC paths (`\\server\share\...`) are
# deliberately out of scope: they do not match the drive-letter form and pass
# through unchanged (the documented residual — a skill anchor is never UNC).
#
# NOTE (bootstrap constraint): a skill-dir anchor cannot source this helper —
# the anchor is what LOCATES lib/ in the first place. The skills carry no shell
# mirror of this chain (issue #275: multi-statement inline blocks are defeated
# by some runners' inline-bash variable stripping), and since issue #1856 they
# no longer restate this helper's tool-less drive-letter arithmetic either. The
# shared "Portable helper anchor" paragraph (canonical copy skills/docs/SKILL.md,
# replicated 17-way and identity-pinned by lib/test/run.sh's P4 loop) now
# instructs the agent to run one standalone wslpath/cygpath probe and then
# VALIDATE the located directory against the filesystem; create-issue's variant
# runs the same probe (also without a drive-letter fallback) but keeps its
# degrade-never-block carve-out instead of validating — so this helper's
# tool-less drive-letter arithmetic is no longer mirrored in either and changing
# it obliges no edit to those copies. The wslpath/cygpath tool-first tier stays
# loosely mirrored (create-issue names it; run.sh's T5/T5c pin it), so a change
# to THAT tier still touches create-issue.
#
# Defines a function only; it deliberately does NOT set -e/-u so it is safe to
# source into a caller with its own shell options.

# devflow_normalize_path <path> — echo the POSIX-form equivalent of <path>.
#
# Resolution order (tool-first, because only the tool knows the mount scheme
# with certainty; the env-detected translation is the documented best-effort
# residual):
#   1. `wslpath -u`  (WSL — preferred when present)
#   2. `cygpath -u`  (Git Bash / MSYS2)
#   3. env-detected manual translation:
#        `uname -r` contains "microsoft"  → WSL-style  /mnt/c/...
#        MSYSTEM set (non-empty)          → MSYS-style /c/...
#   4. no tool and no env signal → echo the input unchanged, with a one-line
#      stderr breadcrumb (stderr only — command substitution captures stdout,
#      so the echoed value stays clean).
# Always returns rc 0 (best-effort — the caller always gets a usable string).
devflow_normalize_path() {
  local input="$1" drive rest _np
  # Inline regex literal, kept form-identical to the SKILL.md mirror so the
  # coupled sites diff cleanly.
  if [[ ! "$input" =~ ^[A-Za-z]:[\\/] ]]; then
    printf '%s\n' "$input"
    return 0
  fi
  # Capture the tool's output and echo it only on SUCCESS with NON-EMPTY
  # output (the same form as the SKILL.md mirror): a tool that prints partial
  # output and exits non-zero must not contaminate the caller's command
  # substitution, and a tool that exits 0 printing nothing must not turn the
  # path into the empty string ("the caller always gets a usable string") —
  # both fall through to the next tier.
  if command -v wslpath >/dev/null 2>&1 && _np="$(wslpath -u "$input" 2>/dev/null)" && [ -n "$_np" ]; then
    printf '%s\n' "$_np"
    return 0
  fi
  if command -v cygpath >/dev/null 2>&1 && _np="$(cygpath -u "$input" 2>/dev/null)" && [ -n "$_np" ]; then
    printf '%s\n' "$_np"
    return 0
  fi
  # `|| drive=""` keeps the "safe to source under set -e" contract (header): a
  # bare `drive=$(… | tr …)` would let a tr-less pipeline's non-zero status abort
  # a set -e caller BEFORE the empty-drive fail-closed guard below runs.
  drive="$(printf '%s' "${input%%:*}" | tr '[:upper:]' '[:lower:]' 2>/dev/null)" || drive=""
  if [ -z "$drive" ]; then
    # tr unavailable (degenerate PATH): never emit a corrupted /mnt//... path —
    # fall to the documented unchanged-with-breadcrumb residual.
    printf 'devflow: could not normalize Windows-form path "%s" (drive-letter lowercasing failed — tr unavailable?) — using it unchanged\n' "$input" >&2
    printf '%s\n' "$input"
    return 0
  fi
  rest="${input#?:}"
  rest="${rest//\\//}"
  if uname -r 2>/dev/null | grep -qi microsoft; then
    printf '/mnt/%s%s\n' "$drive" "$rest"
    return 0
  fi
  if [ -n "${MSYSTEM:-}" ]; then
    printf '/%s%s\n' "$drive" "$rest"
    return 0
  fi
  printf 'devflow: could not normalize Windows-form path "%s" (no wslpath/cygpath and no WSL/MSYS environment signal) — using it unchanged\n' "$input" >&2
  printf '%s\n' "$input"
  return 0
}

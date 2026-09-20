#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# detect-ancestor-config.sh — the nested-repository detection for PRFlow's SHELL
# readers under the SHARED REPO-ROOT CONFIG CONTRACT (issue #12). Its Python
# sibling is lib/ancestor_config.py; the two are a COUPLED PAIR and are edited
# together, because a `.sh` cannot be exec'd from the Python readers on Windows
# ([WinError 193], the issue-#275 rule) and a `.py` cannot be sourced into a shell.
# lib/test/test_python_scripts_part4.py drives both and asserts the emitted line
# is byte-identical across the two.
#
# WHY. A contract member resolves its DEFAULT `.prflow/` path from
# `git rev-parse --show-toplevel`, which returns the NEAREST git root. In a
# nested/submodule checkout, or a monorepo whose `.prflow/` is not at the git
# root, that root carries no `.prflow/` and every `// default` extraction
# silently returns the built-in default — the consumer's config looks honored
# while it is not. This detection makes that one shape LOUD; it changes no
# resolution, so every reader returns exactly what it returned before.
#
# Detection only fires on the ambiguous shape: the resolved root carries NEITHER
# `.prflow/` NOR the transitional `.devflow/`, AND a directory strictly above it
# carries a `.prflow/`. A root that carries either name is configured and earns
# no line, whatever its ancestors hold.
#
# Defines/assigns only; deliberately no set -e/-u — safe to source into a caller
# with its own shell options.

# prflow_ancestor_config_dir <dir>
#   Prints the NEAREST directory strictly above <dir> that carries a `.prflow/`
#   DIRECTORY, or nothing. Always exit 0.
#
#   The walk stops at the filesystem root, and `[ -d ]` is the whole test: a
#   `.prflow` that is a regular file or a dangling symlink is not a config
#   directory, and an ancestor the process cannot stat reads as not carrying one
#   rather than aborting the reader. Pure bash builtins (parameter expansion and
#   the `[` test) — a missing `sed`/`cut` cannot silently skip the detection.
prflow_ancestor_config_dir() {
  local dir="${1:-}" parent
  # Normalise trailing slashes, keeping a lone "/" intact, so "/a/b/" and "/a/b"
  # walk identically.
  while [ "${#dir}" -gt 1 ] && [ "${dir%/}" != "$dir" ]; do dir="${dir%/}"; done
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    case "$dir" in
      */*) parent="${dir%/*}"; [ -n "$parent" ] || parent="/" ;;
      *) return 0 ;;  # a bare relative component has no ancestor to walk
    esac
    dir="$parent"
    if [ -d "${dir%/}/.prflow" ]; then
      printf '%s' "$dir"
      return 0
    fi
  done
  return 0
}

# prflow_warn_ancestor_config <repo_root> <reader> <remedy>
#   Writes the one-line breadcrumb to STDERR when <repo_root> is the ambiguous
#   nested shape, and nothing otherwise. Always exit 0, and never touches stdout:
#   several callers capture a reader's stdout as a value, and a polluted capture
#   becomes a wrong value downstream.
#
#   <remedy> names the reader's OWN supported explicit override. A reader with
#   none passes the empty string and the line says so rather than advertising a
#   flag that does not exist.
prflow_warn_ancestor_config() {
  local root="${1:-}" reader="${2:-prflow}" remedy="${3:-}" ancestor
  [ -n "$root" ] || return 0
  [ -d "${root}/.prflow" ] && return 0
  [ -d "${root}/.devflow" ] && return 0
  ancestor="$(prflow_ancestor_config_dir "$root")"
  [ -n "$ancestor" ] || return 0
  [ -n "$remedy" ] || remedy="this reader has no explicit override — run it from the repository that owns the config"
  printf "%s: repo root '%s' has no .prflow/, but ancestor '%s' does — reading built-in defaults, not that config; to use it, %s.\n" \
    "$reader" "$root" "$ancestor" "$remedy" >&2
  return 0
}

#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Shared builder for a synthetic `devflow_copy_slice` SOURCE tree (issue #1388).
#
# Sourced by every fixture that vendors the plugin out of a stub tree. The member
# list is derived from vendor-slice.sh by lib/test/slice-source-members.py rather
# than transcribed here, so adding an entry to the slice's `cp` list does not
# require a matching edit in each fixture — without that, the slice's `set -e` cp
# aborts before the vendored tree lands and every such fixture goes red at once.
#
# Each created directory gets a placeholder file: git does not track empty
# directories, so a fixture that is cloned would otherwise lose the member it
# just created. Callers overwrite any member they assert on (plugin.json above
# all) after calling this.

# Build a slice source tree at $1. Every member vendor-slice.sh copies is created,
# directories carrying a placeholder file and JSON files carrying `{}`. Returns
# non-zero without creating anything when the member list cannot be established —
# a fixture built against an empty list would pass vacuously.
devflow_build_slice_source_fixture() {
  local root="$1" repo="${2:-.}" members kind path
  [ -n "$root" ] || { echo "devflow_build_slice_source_fixture: no root given" >&2; return 2; }
  members="$(python3 "$repo/lib/test/slice-source-members.py" "$repo")" || return $?
  [ -n "$members" ] || { echo "devflow_build_slice_source_fixture: empty member list" >&2; return 2; }
  while IFS="$(printf '\t')" read -r kind path; do
    [ -n "$path" ] || continue
    case "$kind" in
      dir)
        mkdir -p "$root/$path"
        # `.placeholder` rather than a typed name: no member's own consumer reads
        # it, and a typed one (a stray .md under skills/) would join a population
        # some other assertion enumerates.
        : > "$root/$path/.placeholder"
        ;;
      file)
        mkdir -p "$root/$(dirname "$path")"
        printf '{}' > "$root/$path"
        ;;
      *) echo "devflow_build_slice_source_fixture: unknown kind '$kind'" >&2; return 2 ;;
    esac
  done <<EOF
$members
EOF
}

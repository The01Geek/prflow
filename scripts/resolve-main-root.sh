#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-main-root.sh — print the absolute path of the MAIN working-tree root.
#
# Prints the main repo root when run from inside a linked git worktree (e.g. a
# Claude worktree under `.claude/worktrees/<name>/`), the repo root when run from
# a normal single-tree checkout, and falls back to `pwd` (with a specific stderr
# breadcrumb) when git is unavailable, the cwd is not a git repo, the main
# repo is bare, or the resolved root no longer exists on disk. Like
# `scripts/ensure-label.sh` / `scripts/apply-labels.sh`, this
# is a best-effort helper: it ALWAYS exits 0, so a resolution hiccup can never
# abort the caller — but it leaves a specific stderr breadcrumb on the fallback
# path so a real failure is visible rather than silently swallowed.
#
# This is a DISTINCT resolution from the `.prflow/` repo-root anchoring used by
# config-get.sh / config-source.sh / workpad.py (issue #295), which resolve the
# *nearest* git root via `git rev-parse --show-toplevel` — that returns the
# WORKTREE when inside one, which is deliberately NOT what this helper wants. The
# main worktree is always the first record of `git worktree list --porcelain`
# (portable to git >= 2.7). `git` is invoked directly here, matching
# `lib/config-source.sh` (git is not part of the `resolve-*.sh` binary-resolver
# family).
set -uo pipefail

# `git worktree list --porcelain` groups records (one per worktree) separated by
# blank lines; the FIRST record is always the main worktree, whose `worktree`
# attribute line carries its absolute path. Empty output means git failed / the
# cwd is not a repo — main_root ends up empty and we fall back to pwd below.
#
# The first record is parsed with BASH BUILTINS ONLY — `while IFS= read -r`,
# `case`, and `${var#prefix}` (issue #795). `lib/preflight.sh` guarantees only
# git/gh/jq/python3+PyYAML, so `head`/`sed`/`grep` are NOT guaranteed on the host:
# under a PATH holding only `git` and `bash` the previous pipeline emitted
# `command not found` and yielded an EMPTY main_root, silently falling back to
# `pwd` — and `pwd` inside a linked worktree is the WORKTREE root, not the main
# root, so the bound draft root this value decides would have been wrong with no
# error. A value that decides a selection must not be derived through a
# non-preflight PATH tool.
porcelain="$(git worktree list --porcelain 2>/dev/null)"
main_root=""
saw_bare=0
while IFS= read -r line; do
    # The blank line terminates the FIRST record — the same scope the previous
    # `head -n 1` / `sed -n '1,/^$/p'` pair inspected.
    [ -n "$line" ] || break
    case "$line" in
        # A BARE main repo lists its first record with a `bare` attribute and a
        # worktree path pointing at the bare git dir, which is not a usable
        # working tree — treat it as unresolved and fall back to pwd (the
        # degenerate case).
        bare) saw_bare=1 ;;
        # First `worktree `-prefixed line in the record wins. This is a deliberate,
        # scoped DIVERGENCE from the retired `head -n 1`, which took record 1's
        # literal first line whatever it was: on output whose first record does not
        # OPEN with `worktree ` the old form yielded that foreign line as the path
        # (garbage, then a pwd fallback) while this one finds the real one. git
        # always opens a record with `worktree `, so the two agree on every output
        # git actually produces — the divergence is confined to input git does not
        # emit, and there the new form is the more robust of the two.
        'worktree '*) [ -n "$main_root" ] || main_root="${line#worktree }" ;;
    esac
done <<EOF
$porcelain
EOF

if [ "$saw_bare" -eq 1 ]; then
    main_root=""
fi

if [ -n "$main_root" ] && [ -d "$main_root" ]; then
    printf '%s\n' "$main_root"
else
    echo "prflow: resolve-main-root: could not determine the main working-tree root (git unavailable, not a git repo, a bare main repo, or the resolved root no longer exists) — falling back to '$(pwd)'" >&2
    pwd
fi

exit 0

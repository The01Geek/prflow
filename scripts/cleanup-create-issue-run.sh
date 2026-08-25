#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Remove a completed create-issue run's per-run scratch, keyed to the recorded
# slug under `<root>/.prflow/tmp/create-issue/<slug>/`. Keying on the slug (never a
# pattern or age sweep) is what leaves a concurrent run's or another producer's
# artifacts untouched. Best-effort: it runs after issue creation and never blocks it.
#
# Usage: cleanup-create-issue-run.sh --slug <slug> [--root <path> ...]
set -u

prog=cleanup-create-issue-run.sh
slug=""
roots=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    # `shift; [ … ] && shift` consumes the value only when one is present. A bare
    # `shift 2` on a trailing valueless flag exceeds $# and fails without moving it,
    # spinning this loop forever — breaking the best-effort/never-blocks contract.
    --slug) slug="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
    --root) roots+=("${2:-}"); shift; [ "$#" -gt 0 ] && shift ;;
    *) printf '%s: warning: ignoring unexpected argument %s\n' "$prog" "$1" >&2; shift ;;
  esac
done

# An empty or path-unsafe slug would make the run dir collapse to the shared
# `create-issue/` namespace root; refusing it (delete nothing, exit 0) is what makes
# the empty/unset-handle case non-destructive.
if [ -z "$slug" ]; then
  printf '%s: no slug (empty-handle); nothing removed\n' "$prog" >&2
  exit 0
fi
if ! [[ "$slug" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  printf '%s: refusing unsafe slug %s; nothing removed\n' "$prog" "$slug" >&2
  exit 0
fi

for root in "${roots[@]:-}"; do
  [ -n "$root" ] || continue
  base="$root/.prflow/tmp/create-issue"
  target="$base/$slug"
  if [ -d "$target" ]; then
    if rm -rf -- "$target"; then
      printf '%s: removed run dir %s\n' "$prog" "$target" >&2
    else
      printf '%s: warning: could not remove %s\n' "$prog" "$target" >&2
    fi
  fi
  # The slug pointer is slug-independent-named and shared, so remove it only when it
  # still holds THIS run's slug — never a concurrent run's rebind. Read it with a bash
  # builtin, not `tr`/`cut` (non-preflight tools whose absence would silently misread).
  ptr="$base/issue-run-slug"
  if [ -f "$ptr" ]; then
    # A pointer written without a trailing newline makes `read` return non-zero at
    # EOF AFTER assigning the slug — `|| ptr_slug=""` would then blank a good read and
    # silently skip the removal, so keep the assigned value (`|| :`) and pre-init for
    # the genuinely-unreadable case.
    ptr_slug=""
    IFS= read -r ptr_slug < "$ptr" 2>/dev/null || :
    if [ "$ptr_slug" = "$slug" ]; then
      rm -f -- "$ptr" && printf '%s: removed slug pointer %s\n' "$prog" "$ptr" >&2
    fi
  fi
done

exit 0

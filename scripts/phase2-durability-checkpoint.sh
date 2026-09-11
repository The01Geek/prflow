#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Phase 2 mid-run durability checkpoint (issue #1139).
#
# Historically an implement run held every change it made in an uncommitted
# working tree until Phase 2 §2.5 — Phase 2's only commit and push — so a run that
# terminated before §2.5 lost all of it. This helper is the executable durability
# step the Phase 2 prose now invokes at each sub-step boundary (and §2.5 itself) so
# work already produced survives on the run's own remote branch — the branch the
# §1.4 resume path already reads.
#
# Contract (leading-token invocation; the message is $1, the rest are explicit
# pathspecs):
#
#   phase2-durability-checkpoint.sh <commit-message> <path> [<path> ...]
#
# Behavior:
#   - Staging is EXPLICITLY SCOPED. The helper stages ONLY the named paths via
#     `git add -- <paths>`. It NEVER stages with `git add -A`, `git add .`, or
#     intent-to-add, and it REFUSES the whole CLASS of arguments that stage more
#     than the caller named (AC6 — see `_is_whole_tree_arg` for the class and its
#     deliberate exclusions): an unscoped stage would defeat §2.2's sweep guidance
#     and the fix loop's explicit-path scoping, and would carry unrelated
#     untracked files into pushed history.
#   - Staging is TOLERANT of already-staged deletions (issue #250). A named path
#     git already holds a staged DELETION under — a `git mv` source or a `git rm`
#     target that no longer exists in the worktree — is accepted rather than failing
#     the batch `git add`. The acceptance is deletion-specific: a path whose add fails
#     but whose only staged change is a non-deletion still fails closed (exit 4), so
#     stale staged content can never ride into the commit while the checkpoint reports
#     success.
#   - Rename SOURCES are paired into the commit (issue #250). git records a rename as
#     a staged deletion of the source plus a staged addition of the destination; when
#     the caller names only the destination, the helper pairs the source (as the
#     root-relative magic pathspec `:/<source>`) so the rename lands as ONE commit
#     rather than leaving the source deletion behind. A guard-excluded workflow source
#     is not paired.
#   - Deletions LEFT BEHIND are reported (issue #250). After the commit — and on both
#     exit-0 no-commit arms — each tracked deletion the checkpoint did not commit,
#     staged in the index or unstaged in the working tree, is named once on stderr as
#     `deletion left uncommitted: <path>`. The exit code is unchanged; the explicit-
#     scoping rule is unchanged (an unnamed deletion that pairs with no named rename
#     stays out of the commit and is reported, never swept in).
#   - Cloud-tier workflow-edit guard (AC4). On a run whose credential cannot push
#     `.github/workflows/` — cloud tier (GITHUB_ACTIONS=true) with DEVFLOW_APP_ID
#     empty/unset, i.e. the GITHUB_TOKEN fallback — the helper DETECTS any named
#     path under the repo's own `.github/workflows/` and does NOT stage it (nor
#     commit it), emitting a breadcrumb per excluded path. It matches the repo's
#     own workflows dir only, never a vendored `.prflow/vendor/.../.github/...`
#     path. Only the detect-and-do-not-stage half lives here; the guard's
#     coupled-file enumeration and 2.2.5 scope-adjustment routing stay Phase 2
#     prose. DISCLOSED LIMIT: the match is on the RELATIVE `.github/workflows/`
#     spelling after every leading `./` is stripped, so an absolute path, a
#     `../`-reaching form, and the bare directory `.github/workflows` (no trailing
#     slash) are not matched — the same spelling-only limit `_is_whole_tree_arg`
#     discloses for AC6. This half is defense-in-depth behind the Phase 2 prose's
#     revert, which remains the primary control. A workflow commit that slips this
#     spelling guard is not self-limiting: because the helper never amends or rebases,
#     the rejected commit stays in local history and this checkpoint plus every later
#     checkpoint push fails loudly until an operator repairs that branch history.
#   - No empty commit (AC3/AC8). When nothing is staged after filtering — a
#     boundary reached with no new work, or every named path excluded by the
#     guard — the helper makes NO commit. It exits 0 ONLY after reconfirming the
#     branch tip is on the remote (HEAD == @{u}); a tip that never landed reports
#     not-durable (exit 3) instead. That makes "exit 0 means the work so far is
#     durable" unconditionally true rather than true only by induction over
#     correct prior calls.
#   - Landing verification (AC7). After pushing, the helper treats the push as
#     landed ONLY when `git rev-parse HEAD` equals `git rev-parse @{u}`, mirroring
#     skills/implement/references/doc-deliverable-self-heal.md. A rejected
#     non-fast-forward leaves the two unequal and is reported as a failure to land
#     (exit 3). Push output such as `Everything up-to-date` is not itself decisive:
#     it takes exit 3 only when the comparison still shows that the checkpoint commit
#     did not reach the tracked branch.
#   - History is never rewritten: no amend, no rebase, no force-push (AC5). Proof
#     content stays out of history by ORDERING — the Phase 2 prose invokes this
#     helper only after §2.1.5 proof edits are reverted, and explicit scoping
#     means an unnamed proof file is never staged regardless.
#
# Exit codes:
#   0  committed+pushed+landed, OR a clean no-op whose branch tip is already on the
#      remote (in both cases: the work up to this boundary is durable)
#   2  usage error (missing message, no pathspec, or a forbidden non-path token —
#      the refused class is `_is_whole_tree_arg`'s, which is broader than the
#      stage-all spellings alone: option-shaped tokens and git magic pathspecs too)
#   3  the work up to this boundary is not on the remote — a push that did not land,
#      or a no-op boundary whose branch tip is not at @{u} (either case including
#      no upstream configured)
#   4  a git operation failed (add/commit/not a repo)

set -u

_bc() { printf 'phase2-durability-checkpoint: %s\n' "$1" >&2; }

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
  _bc "usage: phase2-durability-checkpoint.sh <commit-message> <path> [<path> ...]"
  exit 2
fi
MESSAGE="$1"
shift

# A checkpoint with a message but ZERO pathspecs is a usage error, never a clean
# no-op: the documented contract makes at least one path mandatory, and the caller
# prose acts only on a NON-ZERO exit. An argument list that expands empty — an
# unmatched glob, an empty variable expansion — would otherwise report success with
# nothing committed, which is exactly the silent mid-run work loss #1139 exists to
# prevent. The exit-0 no-op stays reserved for the genuine named-but-unchanged case
# (and for a named path the workflow-edit guard excluded).
if [ "$#" -eq 0 ]; then
  _bc "no pathspec given — at least one explicit path is required: phase2-durability-checkpoint.sh <commit-message> <path> [<path> ...]"
  exit 2
fi

# Does this argument stage MORE than the caller named (AC6)? Returns 0 to refuse it,
# 1 when it is a concrete path. A class test, deliberately not a denylist of tokens,
# because a denylist leaves the same defect one spelling away. Three shapes qualify:
#   - option-shaped — `git add`'s `-A`/`-u`/`-N`/`--all`/`--update`/`--intent-to-add`
#     all begin with `-`;
#   - a git magic pathspec — `:/` (repo root), `:(glob)…`, `:(top)…` all begin with `:`;
#   - a whole-tree spelling — an argument built ONLY out of the path-navigation
#     characters `.` and `/` and/or the match-everything wildcard `*`. `git add` is
#     recursive over a directory, so `.`, `./`, `.//`, `./.` and `././` each stage a
#     whole tree (as does `..` from a subdirectory); and a plain — non-`:(glob)` —
#     pathspec wildcard matches across `/`, so `*`, `**`, `./*` and `**/*` do too. The
#     empty string lands in this arm as well: it names nothing, and git rejects it as
#     a pathspec.
# Deliberately NOT in the class, each because it names what the caller asked for or
# because a spelling test cannot decide it:
#   - a caller-named directory (`scripts/`, trailing slash included) — recursive by
#     design, and explicitly scoped to what the caller named;
#   - a partial glob (`scripts/*`, `[a-z]*`) — it matches a subset, not the tree;
#   - a path reaching the repo root the long way round (an absolute `/abs/repo`, or
#     `../<repo>`), which needs resolution against `git rev-parse --show-toplevel`
#     rather than inspection of the spelling.
# Accepted false refusal: a pathological real filename made only of those characters
# (a file literally named `...` or `*`) is refused. No such path is nameable by the
# Phase 2 prose that invokes this helper.
_is_whole_tree_arg() {  # <arg>
  case "$1" in
    -* | :*) return 0 ;;
  esac
  case "$1" in
    *[!./*]*) return 1 ;;   # holds at least one ordinary path character
    *) return 0 ;;          # empty, or nothing but `.`, `/` and `*`
  esac
}

KEEP=()
GUARD_ACTIVE=no
if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ -z "${DEVFLOW_APP_ID:-}" ]; then
  GUARD_ACTIVE=yes
fi

# Returns 0 when the guard is active AND the path normalizes to a repo-own `.github/workflows/`
# path (every leading `./` stripped — a single `${arg#./}` would leave `././…` prefixed and slip
# the guard). A pure predicate reused by the named-arg filter and the rename-source pairing (#250).
_guard_excludes() {  # <path>
  [ "$GUARD_ACTIVE" = yes ] || return 1
  local norm="$1"
  while [ "$norm" != "${norm#./}" ]; do norm="${norm#./}"; done
  case "$norm" in
    .github/workflows/*) return 0 ;;
    *) return 1 ;;
  esac
}

# The workflow-edit guard's NOT-staging breadcrumb, emitted verbatim at both guard
# sites (the named-argument filter and the rename-source pairing) — the module greps
# this literal, so keep the two sites byte-identical by sourcing them from here.
_guard_skip_msg() {  # <path>
  _bc "workflow-edit guard: NOT staging '$1' (cloud tier, DEVFLOW_APP_ID empty — the GITHUB_TOKEN fallback cannot push .github/workflows/). Defer it via the Phase 2.2.5 scope-adjustment."
}

# Report each tracked deletion this checkpoint did not commit — staged or unstaged — one stderr
# line per path (issue #250); exit code is the caller's, this only prints. `--no-renames` forces
# every deletion to list as D so one that git would otherwise pair into a rename R is still reported.
_report_residue() {
  local p
  while IFS= read -r p; do
    [ -n "$p" ] && _bc "deletion left uncommitted: $p"
  done < <(git diff --cached --no-renames --name-only --diff-filter=D)
  while IFS= read -r p; do
    [ -n "$p" ] && _bc "deletion left uncommitted: $p"
  done < <(git diff --no-renames --name-only --diff-filter=D)
}

for arg in "$@"; do
  # Explicit paths only (AC6): every argument must name a concrete path, or it would
  # stage more than the caller named and defeat §2.2's sweep-scoping and the fix
  # loop's explicit-path scoping. This is a CLASS test, not a denylist of tokens —
  # `_is_whole_tree_arg` states the class and what it deliberately leaves out.
  if _is_whole_tree_arg "$arg"; then
    _bc "refusing non-path staging argument '$arg' — staging must be explicitly scoped to concrete file paths (AC6)."
    exit 2
  fi
  # Cloud-tier workflow-edit guard: on a run whose GITHUB_TOKEN fallback cannot push
  # .github/workflows/, do not stage a repo-own workflow path. A vendored
  # .prflow/vendor/… path is not the repo's own and is not guarded.
  if _guard_excludes "$arg"; then
    _guard_skip_msg "$arg"
    continue
  fi
  KEEP+=("$arg")
done

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  _bc "not inside a git repository — cannot checkpoint"
  exit 4
fi

# A no-op boundary still owes the caller the durability claim its exit 0 makes. The
# caller acts only on a NON-ZERO exit, so an exit 0 has to mean "the work up to this
# boundary is on the remote" — not merely "I made no commit just now". Without this the
# guarantee holds only by INDUCTION over correct prior calls: a branch tip that never
# landed (a prior checkpoint's push silently failed, or the run never pushed) would be
# reported durable by every subsequent no-op boundary. Returns 0 when the tip is on the
# remote, 3 when it is not — the same not-landed code the post-push verification uses,
# so the caller's "act on a non-zero exit" rule needs no new arm.
#
# TWO DISCLOSED LIMITS on the strength of that exit-0 claim. It is a claim about the
# LOCAL remote-tracking ref, not a live remote read:
#   1. `@{u}` is stale by construction — nothing here fetches. If the remote branch is
#      deleted or rewound after a successful push, this reports the tip durable when it
#      is not. Closing that would cost a `git fetch`/`git ls-remote` at every boundary.
#   2. A path excluded by the workflow-edit guard above is deliberately NOT committed,
#      so exit 0 means "everything STAGEABLE up to this boundary is on the remote" — a
#      guard-excluded path's own content is withheld by design and is not covered.
# So read exit 0 as a claim over the stageable set against the local tracking ref, not
# as an unconditional durability proof over every named path.
_tip_is_on_remote() {  # <no-op description, for the breadcrumb>
  local local_head upstream
  local_head="$(git rev-parse HEAD 2>/dev/null)"
  upstream="$(git rev-parse '@{u}' 2>/dev/null)"
  if [ -z "$upstream" ]; then
    _bc "$1, but no upstream is configured for the current branch — cannot confirm the work so far is on the remote; treating as NOT durable."
    return 3
  fi
  if [ "$local_head" != "$upstream" ]; then
    _bc "$1, but the branch tip is NOT on the remote: HEAD ($local_head) != @{u} ($upstream) — earlier work is not durable."
    return 3
  fi
  return 0
}

if [ "${#KEEP[@]}" -eq 0 ]; then
  _report_residue
  _tip_is_on_remote "nothing to checkpoint (no stageable paths after the workflow-edit guard); no commit made" || exit 3
  _bc "nothing to checkpoint (no stageable paths after the workflow-edit guard); no commit made, branch tip already on the remote"
  exit 0
fi

# Explicitly-scoped staging (never `git add -A`/`.`). When the batch fails, retry per path add-first,
# then accept an already-staged DELETION only (deletion-specific via --diff-filter=D, so stale
# non-deletion staged content can't ride in while the checkpoint reports success); else exit 4 (#250).
if ! git add -- "${KEEP[@]}" 2>/dev/null; then
  for p in "${KEEP[@]}"; do
    add_err="$(git add -- "$p" 2>&1)" && continue
    if [ -n "$(git diff --cached --no-renames --name-only --diff-filter=D -- "$p")" ]; then
      continue
    fi
    _bc "git add failed for path: $p: $add_err"
    _bc "git add failed for the named paths; no commit made"
    exit 4
  done
fi

# Pair rename sources (issue #250): git stages a rename as source-deletion + dest-addition, so a
# commit naming only the destination drops the source deletion. Pair each source as root-relative
# `:/<source>` (a bare source fails from a subdirectory). NAMED_DESTS uses a bash-3.2 read loop, not `mapfile`.
PAIRED=()
NAMED_DESTS=()
while IFS= read -r _nd; do
  NAMED_DESTS+=("$_nd")
done < <(git diff --cached --name-only -- "${KEEP[@]}")
while IFS=$'\t' read -r rstatus rsrc rdst; do
  case "$rstatus" in R*) ;; *) continue ;; esac
  paired=no
  for d in ${NAMED_DESTS[@]+"${NAMED_DESTS[@]}"}; do
    if [ "$d" = "$rdst" ]; then paired=yes; break; fi
  done
  [ "$paired" = yes ] || continue
  if _guard_excludes "$rsrc"; then
    _guard_skip_msg "$rsrc"
    continue
  fi
  PAIRED+=(":/$rsrc")
done < <(git diff --cached -M --name-status)

# No empty commit (AC3/AC8): NAMED_DESTS holds the staged names under KEEP, so its emptiness is
# the no-op signal. A deletion left behind is still reported (issue #250).
if [ "${#NAMED_DESTS[@]}" -eq 0 ]; then
  _report_residue
  _tip_is_on_remote "no staged changes at this boundary; no commit made (no empty commit)" || exit 3
  _bc "no staged changes at this boundary; no commit made (no empty commit), branch tip already on the remote"
  exit 0
fi

# Commit only the named paths and any paired rename source (path-scoped), so unrelated pre-staged
# content stays out instead of riding in on a whole-index commit (AC6). PAIRED is expanded through
# the `${arr[@]+…}` guard so an empty array does not abort under `set -u` on bash < 4.4.
if ! git commit -q -m "$MESSAGE" -- "${KEEP[@]}" ${PAIRED[@]+"${PAIRED[@]}"}; then
  _bc "git commit failed"
  exit 4
fi

# Report any deletion this commit left behind (issue #250) — a `git rm`/plain-`rm`
# deletion the caller did not name, or a guard-excluded rename source.
_report_residue

# Push, then verify the push actually landed. The push exit and output feed the
# breadcrumb; the HEAD==@{u} comparison is the authoritative landing decision.
PUSH_OUT="$(git push 2>&1)"
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
  _bc "git push returned non-zero: ${PUSH_OUT}"
fi

LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
UPSTREAM="$(git rev-parse '@{u}' 2>/dev/null)"
if [ -z "$UPSTREAM" ]; then
  _bc "no upstream configured for the current branch; cannot confirm the checkpoint landed — treating as NOT landed. (${PUSH_OUT})"
  exit 3
fi
if [ "$LOCAL_HEAD" != "$UPSTREAM" ]; then
  _bc "checkpoint did NOT land: HEAD ($LOCAL_HEAD) != @{u} ($UPSTREAM). Push output: ${PUSH_OUT}"
  exit 3
fi

_bc "checkpoint landed: $LOCAL_HEAD pushed to @{u}"
exit 0

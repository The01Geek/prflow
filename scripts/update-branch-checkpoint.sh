#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# update-branch-checkpoint.sh — reconcile the current feature branch with the
# configured base branch at a checkpoint (issue #448).
#
# The whole mechanical sequence lives here — off-switch read, pre-state guards,
# fetch, behind-by derivation, base merge, push, and the push-race recovery arm —
# so a cloud-tier call site invokes ONE granted leading-token command instead of a
# chain of individually-granted git verbs (the cloud allowlists grant no inline
# `git rev-list`, so the behind-by derivation and the base merge must both run inside
# this helper's own subprocess rather than at a call site; issue #363). Every recovery
# arm stays deterministic and suite-driveable instead of agent-improvised. (The cloud
# allowlists DO grant `Bash(git merge:*)` — but only for the agent-level `git merge
# --abort` the conflict-resolution contract prescribes at a call site, not for the
# checkpoint's own base merge, which runs here inside the helper.)
#
# Operates on the CURRENT checkout (HEAD's branch). Reads base_branch and the
# off-switch through config-get.sh; calls neither `gh` nor `jq`, so it sources
# neither lib/resolve-gh.sh nor lib/resolve-jq.sh.
#
# Guard-class 2 (issue #448 AC + CLAUDE.md): every value that decides a branch or
# an emitted token is derived from git exit codes/output, config-get.sh (python3),
# and bash builtins — no tr/sed/wc/cut/head in any selection path.
#
# stdout carries EXACTLY the one outcome token. git's own chatter (`git merge`
# prints "Merge made by …" / conflict summaries to stdout, `git reset` prints
# "HEAD is now at …") would otherwise pollute the token stream, so fd 1 is
# rebound to stderr for the whole script and the token is emitted on the saved
# real-stdout fd 3 via emit().
#
# HOW A CALLER MATCHES THE TOKEN (binding on every call site, issue #779): compare the
# FIRST WHITESPACE-DELIMITED FIELD of the emitted line, never the line as a whole — `UPDATED`
# is emitted as `UPDATED <behind>` (e.g. `UPDATED 3`), so a whole-line equality test against
# `UPDATED` is false for every real merge — misgrading the successful-merge case in whichever
# direction the call site's routing then takes (at checkpoints 1-3, treating a landed merge as
# degraded-and-continue; at checkpoint 4's publish gate, blocking the publish on exactly the
# runs that in fact reconciled).
# And "the helper reported nothing" is NOT observable as "no output at all": fd 1 is rebound to
# stderr below, so git's own chatter interleaves with the token and a successful invocation is
# never silent — the observable discriminator is that NO line's leading word is a member of the
# token set enumerated here.
#
# Outcome contract — exactly one token on stdout, matching exit code:
#   UP_TO_DATE         exit 0  behind-by 0; tree untouched
#   UPDATED <behind>   exit 0  merged and pushed (incl. via push-race recovery)
#   DISABLED           exit 0  off-switch; tree untouched
#   CONFLICT           exit 2  base merge left in progress (MERGE_HEAD present);
#                              conflicted paths + resolution contract on stderr
#   UNVERIFIED         exit 3  base_branch read, fetch, or behind-by derivation failed;
#                              dirty tree; detached HEAD / no branch; or no reachable
#                              merge base — nothing merged, never a blind merge
#   PUSH_REJECTED      exit 4  push refused twice (or a conflicted integrate); the local
#                              branch is restored to its pre-checkpoint SHA and a breadcrumb
#                              names the cause. The restore is attempted, NOT guaranteed: if
#                              `git reset --hard` itself fails (locked index, invalid SHA),
#                              the token is still PUSH_REJECTED but the breadcrumb is a
#                              `WARNING …the restore to pre-checkpoint SHA … failed — the
#                              tree may still carry the base-merge commit`. A caller that
#                              routes PUSH_REJECTED to "record and continue" MUST read that
#                              WARNING and hard-stop instead: `git status` is clean on that
#                              path (the divergence is in COMMITTED history), so no
#                              clean-tree backstop downstream can see it.
#   MERGE_IN_PROGRESS  exit 5  MERGE_HEAD existed at invocation; nothing touched

set -u

# Rebind stdout→stderr; keep the real stdout on fd 3 for token emission only.
exec 3>&1 1>&2
emit() { printf '%s\n' "$1" >&3; }

# Resolve the sibling config-get.sh inline via bash parameter expansion (never a
# non-preflight PATH tool). When BASH_SOURCE carries no slash (bare-name exec),
# `%/*` leaves it unchanged, so fall back to the current directory.
_self="${BASH_SOURCE[0]}"
case "$_self" in
  */*) _self_dir="${_self%/*}" ;;
  *)   _self_dir="." ;;
esac
CONFIG_GET="$_self_dir/config-get.sh"

# (1) Off-switch. Disabled exactly when config-get.sh serializes the value to the
# string `false`: an explicit JSON `false`, or a value that serializes identically —
# the JSON string "false", or [false] (config-get comma-joins arrays). A missing
# file/key, empty string, or any other value leaves it enabled (issue #312
# valid-falsy: the documented off-switch genuinely disables, and near-false shapes
# fail toward "off" — the pre-feature status quo — never toward a surprise merge).
# The `|| true` is deliberate here: if the resolver hard-fails, the base_branch read
# below fails the same way and stops the run (UNVERIFIED) before any fetch or merge.
enabled="$("$CONFIG_GET" .prflow_implement.update_branch_checkpoints "" 2>/dev/null || true)"
if [ "$enabled" = "false" ]; then
  emit "DISABLED"
  exit 0
fi

# (2) Pre-state guards — run BEFORE any fetch or merge.
# MERGE_HEAD at invocation → do not absorb an abandoned resolution into an ordinary
# commit; hard-stop so the caller resolves it deliberately.
if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
  echo "update-branch-checkpoint: a merge is already in progress (MERGE_HEAD present) — resolve or abort it deliberately (git merge --abort), never absorb it into an ordinary commit" >&2
  emit "MERGE_IN_PROGRESS"
  exit 5
fi
# Uncommitted tracked changes → never layer a base merge over dirty work.
#
# UNTRACKED files are deliberately NOT pre-checked here (PR #451 review, deferred with
# reason). A blanket "any untracked file → refuse" guard would reject nearly every real run
# (build artifacts, .prflow/tmp/ markers, editor scratch), and a *targeted* collision
# predicate would have to re-derive git's own merge-overwrite semantics — the guard-drift
# class this repo bans (CLAUDE.md "Adding a guard…"; the accepted-input set of a hand-rolled
# predicate is never an exact match for the consumer's). git already owns that contract: an
# untracked path colliding with an incoming base path makes `git merge` refuse BEFORE
# touching anything, leaving no MERGE_HEAD, so the merge-failure arm at the foot of this file
# emits UNVERIFIED with the tree, HEAD, and the untracked file all untouched — and git's own
# precise "The following untracked working tree files would be overwritten by merge: <paths>"
# reaches stderr un-suppressed (fd 1 is rebound), with that arm's breadcrumb naming
# untracked-overwrite among the candidate causes. The gap is therefore diagnostic precision
# (no dedicated token/message), never a fail-open. Revisit if a call site ever needs to
# BRANCH on untracked-collision as a distinct outcome rather than record UNVERIFIED.
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  echo "update-branch-checkpoint: working tree has uncommitted tracked changes — refusing to fetch or merge over a dirty tree; commit or stash first" >&2
  emit "UNVERIFIED"
  exit 3
fi

# (3) Derive the base branch. A read that FAILS (config-get.sh rc≠0 — corrupt
# .prflow/config.json, missing python3) is UNVERIFIED, never a silent fallback:
# falling back to main on a hard failure would merge-and-push the WRONG base on any
# repo whose real base_branch is not main — a fail-open direction the file's other
# guards rule out. config-get's own stderr passes through (fd 1 is already rebound),
# so the breadcrumb below can point at the real cause. A read that SUCCEEDS but
# returns empty falls back to main (the Phase 3.1 fail-closed empty-read pattern).
if ! BASE="$("$CONFIG_GET" .base_branch main)"; then
  echo "update-branch-checkpoint: could not read base_branch (config-get.sh failed; see its error above) — nothing merged" >&2
  emit "UNVERIFIED"
  exit 3
fi
[ -n "$BASE" ] || BASE=main

# Record the pre-checkpoint SHA and the current branch for the recovery/restore arms.
PRE_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [ -z "$PRE_SHA" ] || [ -z "$BRANCH" ] || [ "$BRANCH" = "HEAD" ]; then
  echo "update-branch-checkpoint: could not resolve HEAD SHA or a branch name (detached HEAD or corrupt repo) — nothing merged" >&2
  emit "UNVERIFIED"
  exit 3
fi

# (4) Fetch the base with an explicit destination refspec, so refs/remotes/origin/$BASE
# is created/updated regardless of the checkout's CONFIGURED fetch refspec: a bare
# `git fetch origin $BASE` only updates the remote-tracking ref opportunistically via
# that configured refspec, and on a checkout whose refspec is genuinely scoped to the
# feature ref, origin/$BASE would never materialize and every checkpoint would degrade
# to UNVERIFIED. The leading `+` permits a forced update of the tracking ref
# (defense-in-depth; identical behavior on an ordinary wildcard-refspec clone).
if ! git fetch origin "+refs/heads/$BASE:refs/remotes/origin/$BASE"; then
  echo "update-branch-checkpoint: could not fetch origin/$BASE (network/auth or wrong base_branch) — nothing merged" >&2
  emit "UNVERIFIED"
  exit 3
fi

# (5) Behind-by via git rev-list; validate as a non-negative integer with a bash
# builtin case (guard-class 2 — never wc/cut).
BEHIND="$(git rev-list --count "HEAD..origin/$BASE" 2>/dev/null || true)"
case "$BEHIND" in
  '' | *[!0-9]*)
    echo "update-branch-checkpoint: could not derive behind-by count from HEAD..origin/$BASE — nothing merged" >&2
    emit "UNVERIFIED"
    exit 3
    ;;
esac

# (6) Already current.
if [ "$BEHIND" -eq 0 ]; then
  emit "UP_TO_DATE"
  exit 0
fi

# --- restore the branch to its pre-checkpoint SHA and terminate PUSH_REJECTED with the
# given breadcrumb (shared by every push-race reject arm). ---
_reject_restore() {  # message
  # Surface the restore's own failure rather than asserting a restore that did not
  # happen: a swallowed `git reset --hard` failure (a locked index, an invalid PRE_SHA)
  # would otherwise leave the breadcrumb claiming "branch restored" while the tree still
  # carries the base-merge commit — the exact silent divergence PUSH_REJECTED exists to
  # rule out. The token stays PUSH_REJECTED (the push WAS rejected), but the breadcrumb
  # is honest about the tree's actual state.
  if git reset --hard "$PRE_SHA" >/dev/null 2>&1; then
    echo "$1" >&2
  else
    echo "update-branch-checkpoint: WARNING push rejected AND the restore to pre-checkpoint SHA $PRE_SHA failed — the tree may still carry the base-merge commit; resolve manually before the next push. ($1)" >&2
  fi
  emit "PUSH_REJECTED"
  exit 4
}

# --- push the merged branch to an EXPLICITLY RESOLVED destination ref. ---
#
# Never a bare `git push` here. Two distinct shapes break it, and both are shapes the
# checkpoint genuinely runs on:
#
#   (1) NO upstream. Phase 1.4's checkpoint fires on EVERY §1.4 arm (issue #779) — the
#       adopted-branch arm including the linked-worktree signal, a branch a local run created
#       and has NOT pushed; the new-branch arm, whose branch `git checkout -b` has only just
#       cut and which has no upstream at all; and the landed-resume arm — and Phase 1.5's
#       `git push -u origin HEAD` runs *after* it in every one of them. `push.default=simple`
#       refuses without an upstream, the recovery arm then cannot fetch a remote ref that does
#       not exist, and _reject_restore rolls the base merge back: a false PUSH_REJECTED that
#       SILENTLY DISCARDS the merge — a no-op on the exact path the feature exists for.
#   (2) An upstream whose REMOTE ref is named differently from the local branch. Under
#       `push.default=simple` a bare `git push` does not "honor" it — it FAILS:
#       `fatal: The upstream branch of your current branch does not match the name of your
#       current branch.` (verified). So the same false-PUSH_REJECTED-and-discard follows.
#
# Resolve the destination ONCE, from git CONFIG — not from the `@{upstream}` tracking ref —
# and use that single resolved (remote, ref) pair in EVERY arm: the push, the push-race
# recovery fetch, and the retry. Resolving it in one place is the point: an earlier revision
# fixed only the push and left the recovery arm keyed on the local `$BRANCH`, so a push race
# on a name-mismatched checkout still fetched a ref that does not exist and discarded the
# merge — the same defect, one arm over.
#
# Config, not `@{upstream}`, because `git rev-parse --abbrev-ref @{upstream}` is lossy and
# lies in three verified ways:
#   * it FAILS (rc 128) when the upstream is configured but its remote-tracking ref has been
#     pruned — so the branch would be misreported as having "no upstream" and pushed to a
#     stray same-named ref while reporting UPDATED;
#   * its `<remote>/<ref>` short form cannot be split safely: a remote may itself contain a
#     slash (`git remote add my/fork` is accepted), so a `%%/`-split mis-parses it;
#   * a LOCAL upstream (`branch.<name>.remote = .`) abbreviates with no remote prefix at all.
# `branch.<name>.remote` gives the exact remote (slashes and all) and `branch.<name>.merge`
# is already a full `refs/heads/…`, so neither needs parsing. Both reads are pure git +
# bash builtins (guard-class 2 — never cut/sed).
#
# KNOWN LIMITATION (deliberate — hence the breadcrumb below names the ref it pushed to): with
# no usable upstream the helper cannot know the intended remote ref, so it assumes
# `local branch name == remote ref name` — the PRFlow convention, and byte-for-byte what
# Phase 1.5's own `git push -u origin HEAD` does. A checkout whose local name deliberately
# differs from its PR target ref (a shepherd worktree checked out as `worktree-pr-N` against
# `issue-N-…`) MUST set an upstream before the checkpoint runs; otherwise this arm pushes to
# `origin/<local name>` — a ref nothing is watching — and reports UPDATED.
PUSH_REMOTE="$(git config --get "branch.$BRANCH.remote" 2>/dev/null || true)"
PUSH_REF="$(git config --get "branch.$BRANCH.merge" 2>/dev/null || true)"
# A local upstream (`.`) has no remote to push to; treat it as "no usable upstream".
case "$PUSH_REMOTE" in .) PUSH_REMOTE="" ;; esac
if [ -n "$PUSH_REMOTE" ] && [ -n "$PUSH_REF" ]; then
  PUSH_SET_UPSTREAM=0
else
  PUSH_REMOTE=origin
  PUSH_REF="refs/heads/$BRANCH"
  PUSH_SET_UPSTREAM=1
  echo "update-branch-checkpoint: branch $BRANCH has no usable upstream (an adopted branch not yet pushed) — pushing to $PUSH_REMOTE/$BRANCH and setting it as the upstream. If this branch's PR target ref is NOT named '$BRANCH', set the correct upstream and re-run: this push would otherwise land on a ref nothing is watching." >&2
fi

# --- push HEAD to the resolved destination. `HEAD:<full ref>` also removes the
# same-named-tag src-refspec ambiguity a bare `"$BRANCH"` src would carry. ---
_do_push() {
  if [ "$PUSH_SET_UPSTREAM" -eq 1 ]; then
    git push -u "$PUSH_REMOTE" "HEAD:$PUSH_REF"
  else
    git push "$PUSH_REMOTE" "HEAD:$PUSH_REF"
  fi
}

# --- push helper: push the merged branch; on a non-fast-forward refusal, run the
# push-race recovery arm exactly once. Emits the final token and exits. ---
_push_or_recover() {
  if _do_push; then
    emit "UPDATED $BEHIND"
    exit 0
  fi
  # Push refused. The common cause is a non-fast-forward race (the remote ref advanced during
  # the run), which the integrate-and-retry below recovers; but a network/auth/hook/protected-
  # branch refusal reaches here too, so the breadcrumb stays cause-neutral rather than
  # asserting "remote advanced" as fact. Integrate the SAME resolved destination ref the push
  # targets (preserving the base-merge commit) and retry the push exactly once — a non-race
  # refusal simply fails the retry too and terminates in the honest PUSH_REJECTED/restore arm.
  echo "update-branch-checkpoint: push refused; integrating $PUSH_REMOTE/$PUSH_REF (in case the remote ref advanced) and retrying the push once" >&2
  # Fetch the destination ref by its full name and merge FETCH_HEAD — never a reconstructed
  # `origin/<local branch>` remote-tracking name, which is exactly what broke on a
  # name-mismatched checkout. FETCH_HEAD is the ref we just fetched, so the merge cannot
  # target a different one, and this needs no assumption about the checkout's configured
  # fetch refspec covering the branch.
  git fetch "$PUSH_REMOTE" "$PUSH_REF" || _reject_restore "update-branch-checkpoint: could not fetch $PUSH_REMOTE/$PUSH_REF to integrate; branch restored to pre-checkpoint SHA"
  if ! git merge --no-edit FETCH_HEAD; then
    # A conflicted integrate is aborted and the branch restored — this is remote
    # divergence, never the base-merge CONFLICT contract.
    git merge --abort >/dev/null 2>&1 || true
    _reject_restore "update-branch-checkpoint: integrating $PUSH_REMOTE/$PUSH_REF conflicted (remote divergence); merge aborted and branch restored to pre-checkpoint SHA"
  fi
  if _do_push; then
    emit "UPDATED $BEHIND"
    exit 0
  fi
  _reject_restore "update-branch-checkpoint: push refused twice; branch restored to pre-checkpoint SHA so no unpushed divergence remains"
}

# --- base-merge conflict emitter (shared by the direct and post-unshallow arms). ---
_emit_conflict() {
  {
    echo "update-branch-checkpoint: base merge of origin/$BASE conflicted. Conflicted paths:"
    git diff --name-only --diff-filter=U
    echo "Resolution contract: resolve the conflicts, run the project test suite, git add + git commit to conclude the merge, push, and re-run the changed-contract sweep. If the suite fails, git merge --abort and hard-stop."
  } >&2
  emit "CONFLICT"
  exit 2
}

# --- merge origin/$BASE and dispatch: a clean merge pushes (or recovers) and exits; a
# conflict emits CONFLICT and exits. It RETURNS to the caller only when the merge failed
# WITHOUT creating a MERGE_HEAD — the no-merge-base case the shallow-history arm handles. ---
_merge_and_dispatch() {
  if git merge --no-edit "origin/$BASE"; then
    _push_or_recover
  fi
  if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
    _emit_conflict
  fi
}

# (6.5) Register the coverage-map JSON-aware merge driver so an adjacent-key
# coverage-map.json insertion unions instead of routing to CONFLICT below (issue #2025).
# Guard on the .gitattributes DECLARATION, never driver-file existence: a moved driver
# here must warn, not silently revert every checkpoint merge to git's line-based merge,
# and the vendored copy in a consumer repo (no declaration) must stay silent. Fail-soft.
_ubc_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$_ubc_root" ] && [ -f "$_ubc_root/.gitattributes" ]; then
  _ubc_map_driver_declared=0
  # Match merge=coverage-map-json as a whole space-delimited attribute (pad the line so a
  # start/end token still matches); skip comment lines. Never `for word in $line` — a
  # gitattributes pattern like `*.sh` would glob-expand.
  while IFS= read -r _ubc_ga_line || [ -n "$_ubc_ga_line" ]; do
    case "$_ubc_ga_line" in '#'*) continue ;; esac
    case " $_ubc_ga_line " in
      *' merge=coverage-map-json '*) _ubc_map_driver_declared=1; break ;;
    esac
  done < "$_ubc_root/.gitattributes"
  if [ "$_ubc_map_driver_declared" -eq 1 ]; then
    _ubc_driver="$_ubc_root/lib/test/coverage-map-merge-driver.py"
    if [ ! -f "$_ubc_driver" ]; then
      echo "update-branch-checkpoint: coverage-map merge driver declared in .gitattributes but $_ubc_driver is missing — skipping registration; the base merge falls back to git's line-based merge" >&2
    elif ! python3 "$_ubc_driver" --register >/dev/null 2>&1; then
      echo "update-branch-checkpoint: coverage-map merge driver registration ($_ubc_driver --register) exited non-zero — the base merge falls back to git's line-based merge" >&2
    fi
  fi
fi

# (7) Merge the base.
_merge_and_dispatch

# (8) Shallow-history arm: no merge base was reachable (the merge above returned without a
# MERGE_HEAD). Unshallow exactly once and retry the merge once; an unrecoverable history is
# a clean UNVERIFIED with the tree untouched. Target the base with the same explicit
# destination refspec as step 4: a depth-limited cloud checkout DOWNLOADS only
# the feature ref's history, so a bare `git fetch --unshallow origin` need not deepen the
# base ref and the merge base could still lie beyond the shallow boundary — the explicit
# refspec both deepens the right ref and keeps origin/$BASE resolution independent of the
# checkout's configured fetch refspec.
# git's stderr is NOT suppressed (symmetric with the primary fetch at step 4): a real
# transient failure here (network drop, expired token, 5xx) would otherwise collapse into
# the cause-neutral "no reachable merge base" breadcrumb below, and that breadcrumb's own
# "see the git error above" promise would point at a suppressed error. On a genuinely
# complete (non-shallow) repo git prints "--unshallow on a complete repository does not make
# sense" and exits non-zero — expected noise on the no-merge-base path, not a real failure.
if git fetch --unshallow origin "+refs/heads/$BASE:refs/remotes/origin/$BASE" >/dev/null; then
  # Re-derive behind-by now that base history is complete — a shallow view undercounts it,
  # so the pre-unshallow BEHIND would publish a confidently-low UPDATED count. Keep the old
  # value if re-derivation fails (guard-class 2 — bash `case` builtin, never wc/cut).
  BEHIND_FULL="$(git rev-list --count "HEAD..origin/$BASE" 2>/dev/null || true)"
  case "$BEHIND_FULL" in '' | *[!0-9]*) : ;; *) BEHIND="$BEHIND_FULL" ;; esac
  _merge_and_dispatch
fi

# `_merge_and_dispatch` returns here on ANY base-merge failure that left no MERGE_HEAD —
# no reachable merge base, unrelated histories, or (after the unshallow retry) a still-
# unextendable shallow history. git's own `fatal:` line already printed to stderr above
# (fd 1 is rebound to stderr), so this breadcrumb stays cause-neutral rather than asserting
# "shallow history" as the sole cause of a failure that may be unrelated-histories.
echo "update-branch-checkpoint: could not complete a base merge with origin/$BASE — the merge could not start or found no merge base (unrelated histories, a shallow history that could not be extended, or untracked files the merge would overwrite; see the git error above) — nothing merged" >&2
emit "UNVERIFIED"
exit 3

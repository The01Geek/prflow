#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# telemetry-branch.sh — persist DevFlow observability artifacts to a dedicated,
# long-lived ORPHAN branch (default `prflow-telemetry`, name from the
# `telemetry.branch` config key) WITHOUT ever touching the current branch, HEAD,
# the default branch, or the TRACKED working tree. Writes go entirely through git
# plumbing against the object store (hash-object → write-tree → commit-tree) and
# a compare-and-swap ref advance, then a fetch → re-parent → push retry loop.
# This is the SINGLE code path both local and cloud persistence use (issue #441):
# the ambient git credential is the only environment-specific input — the push
# lives here, not in the workflow.
#
# Sourced by lib/efficiency-trace.sh (and any future persist caller). Every
# function is BEST-EFFORT: it NEVER aborts the caller and always leaves a
# ::warning:: breadcrumb on a degradation, mirroring the ensure-label.sh /
# apply-labels.sh exit-0 contract. When the branch cannot be pushed (no remote,
# offline, read-only fork-PR token, missing permission, read-only review
# profile) the LOCAL ref still advances and the run proceeds. On the LOCAL tier
# that means nothing is lost — the next persist carries it. On an EPHEMERAL CI
# runner it does not: the checkout is destroyed at teardown, so an unpushable run's
# records are LOST. The breadcrumbs say so when GITHUB_ACTIONS is set rather than
# reassuring an operator whose data is already gone (see the retention note below).
#
# Selection-deciding values (whether to append, whether a store is valid, whether
# a worktree holds the ref) are derived with `git` + bash builtins only — never a
# non-preflight PATH tool (`grep`/`sed`/`tr`/…) whose absence would silently
# empty the value and corrupt the decision (CLAUDE.md guard-class 2).

# Guard against double-source: idempotent when a caller sources this file more
# than once (e.g. efficiency-trace.sh sources it, and a test sources it directly).
# The `_DEVFLOW_TELEMETRY_BRANCH_SOURCED` sentinel it reads is set at the very END
# of this file, deliberately — see the note there.
if [ -n "${_DEVFLOW_TELEMETRY_BRANCH_SOURCED:-}" ]; then
  return 0 2>/dev/null || true
fi

# devflow_conf comes from config-source.sh. Source it if the caller has not
# already (efficiency-trace.sh sources it first, so this is a no-op there; a
# standalone/test source of THIS file still resolves the config key).
if ! command -v devflow_conf >/dev/null 2>&1; then
  # shellcheck source=lib/config-source.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config-source.sh" 2>/dev/null || true
fi

# Committer identity for telemetry commits. Deterministic (not the developer's
# git config) so `git commit-tree` NEVER aborts on a checkout with no configured
# user.email (issue #441 AC8) and the orphan branch's history is uniform. These
# are exported into the commit-tree call only.
_DEVFLOW_TELEMETRY_IDENT_NAME="github-actions[bot]"
_DEVFLOW_TELEMETRY_IDENT_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
# The commit subject is a COUPLED literal. Its real mirror sites are `lib/test/run.sh` (which
# pins it) and `skills/review/SKILL.md` (whose Phase 0.2 awk-filter rationale names this exact
# subject as the pre-#441 legacy commit it guards against). It is NOT referenced by the
# workflows or by docs/ — this diff removed the in-workflow commit path, so naming those here
# would send a maintainer following the coupled-invariant rule to two directories with no hits,
# while omitting the SKILL.md mirror that does exist.
_DEVFLOW_TELEMETRY_COMMIT_MSG="chore: persist review-and-fix observability artifacts"
# Bounded retry caps — enough to survive a burst of parallel writers without
# looping forever on a persistently-diverging ref or an unpushable remote.
_DEVFLOW_TELEMETRY_CAS_TRIES=5
# The top-level keys lib/efficiency-trace.sh's floors add to a record, and the ONLY keys a
# staged copy differs from base by. The concurrent-push union merge re-applies exactly
# these onto the fetched base; a floor whose key is missing here has that key silently
# dropped whenever a competing writer forces that path, so a new floor adds its key here.
_DEVFLOW_TELEMETRY_FLOOR_KEYS_JSON='["harness_cost","permission_denials","run_profile","issue_number","no_pr_reason"]'
_DEVFLOW_TELEMETRY_PUSH_TRIES=4

# Every push-failure breadcrumb ends by saying the records are "retained on the local ref".
# That is true — and genuinely reassuring — on the LOCAL tier, where the ref survives and the
# next persist carries it. It is FALSE on an ephemeral CI runner: the checkout is destroyed at
# teardown, so on a read-only/fork-PR token, a missing permission, or an auth failure the run's
# records are LOST, not retained. Issue #441 made that path more reachable, not less (it removed
# the `source == "review"` skip, so standalone /devflow:review runs — which execute under the
# deliberately read-only review profile — now reach it routinely). A breadcrumb that reassures
# an operator their data is safe when it is already gone is worse than no breadcrumb, so append
# the truth for the environment we are actually in. Keyed on GITHUB_ACTIONS: a run-scoped
# observable, no new tool dependency.
_devflow_telemetry_retention_note() {
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    printf '%s' " — NOTE: on this ephemeral CI runner the local ref does NOT survive teardown, so these records are LOST for this run, not retained"
  fi
}

# Decide whether --persist may PUSH this run, or must only STAGE (issue #469 AC5).
# The failure direction is deliberately asymmetric by tier:
#   - OFF CI (GITHUB_ACTIONS unset/empty) → push, unchanged: the local Stop hook
#     carries no job env, and a local ref survives to the next persist anyway, so
#     the historical push-by-default behavior is preserved.
#   - ON CI → push ONLY when the workflow AFFIRMATIVELY sets the observable push
#     operand DEVFLOW_TELEMETRY_PUSH (`1`/`true`). Absent, empty, or any
#     non-affirmative value FAILS CLOSED to staging-only. The operand must reach
#     this hook from the JOB ENVIRONMENT (the base-branch .claude/settings.json is
#     restored identically in every claude-code-action job, so a value baked into
#     the hook command could not distinguish the read-only review tier from a
#     writable one). The writable tiers set DEVFLOW_TELEMETRY_PUSH=1 at job level;
#     the read-only review tier deliberately does not, so it stages, and the trusted
#     telemetry-push relay (not this read-only job; telemetry-push.yml, issue #489)
#     performs the branch push from the uploaded staged artifacts.
# rc 0 = push; rc 1 = stage-only.
_devflow_telemetry_should_push() {
  [ -n "${GITHUB_ACTIONS:-}" ] || return 0
  case "${DEVFLOW_TELEMETRY_PUSH:-}" in
    1|true|TRUE|True|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# Resolve the telemetry branch name (config .telemetry.branch, default
# prflow-telemetry). An empty/absent key → the default (a string key, so the
# #312 valid-falsy trap does not apply — an empty branch name is never a valid
# selection).
devflow_telemetry_branch() {
  # Memoized: the branch name is invariant for a process, and devflow_conf shells
  # to python3 (+ an mktemp) on every call, so a discovery --persist over M run
  # dirs would otherwise do M+ identical config reads. Resolve once, cache.
  if [ -z "${_DEVFLOW_TELEMETRY_BRANCH_CACHE:-}" ]; then
    local b=""
    if command -v devflow_conf >/dev/null 2>&1; then
      b="$(devflow_conf '.telemetry.branch' 'prflow-telemetry')"
    fi
    [ -n "$b" ] || b="prflow-telemetry"
    # Validate the CONFIGURED name is actually usable as a branch ref before it is
    # interpolated into refs/heads/<b>, a push refspec, and refs/remotes/origin/<b>.
    # The schema says `"type": "string"`, but a schema is not a runtime guard: a
    # hand-edited config can carry a space, a `..`, or a wrong-typed value the
    # resolver stringifies. git then refuses the update-ref with `refusing to update
    # ref with bad name`, which is neither a CAS race nor a disk fault — so without
    # this check it lands in the terminal arm whose breadcrumb names ONLY lock /
    # read-only / disk causes, and the operator is never pointed at the config key
    # that actually caused it — on every run (PR #442 review). Fail back to the
    # default so telemetry still persists, and say exactly which key to fix.
    if ! git check-ref-format --branch "$b" >/dev/null 2>&1; then
      echo "::warning::telemetry-branch: config key 'telemetry.branch' resolved to '${b}', which git rejects as a branch name (git check-ref-format); falling back to 'prflow-telemetry' — fix .prflow/config.json to persist to your intended branch" >&2
      b="prflow-telemetry"
    fi
    # What actually makes this memo work is `do_persist` SEEDING it in the parent shell before
    # anything forks — not this `export`. A `$(devflow_telemetry_branch)` call site runs in a
    # command substitution, and a subshell's export never reaches its parent, so without that
    # seed each sibling subshell re-resolved from scratch: the config was re-read once per fork
    # and, on an invalid value, the check-ref-format breadcrumb printed once per fork (three
    # times in a single --persist). The export is still correct — a child that re-sources this
    # lib inherits the resolved value — but the seed is the load-bearing half. Keep both, and
    # keep the seed in do_persist.
    export _DEVFLOW_TELEMETRY_BRANCH_CACHE="$b"
  fi
  printf '%s\n' "$_DEVFLOW_TELEMETRY_BRANCH_CACHE"
}

# The full ref the telemetry branch name maps to (refs/heads/<branch>). Owned by
# the lib so no consumer re-derives `refs/heads/$(devflow_telemetry_branch)`.
devflow_telemetry_ref() {
  printf 'refs/heads/%s\n' "$(devflow_telemetry_branch)"
}

# Verify an EXISTING ref is a telemetry store: its tip tree must hold only
# `.prflow/logs/`-shaped paths. An ABSENT ref returns 0 (a fresh orphan store is
# about to be created). A non-conforming tip returns 1 with a breadcrumb, so the
# write skips rather than committing onto a same-named branch a consumer uses for
# something else (AC4). Pure `case` matching — no grep (selection decision).
devflow_telemetry_verify_store() {
  local root="$1" ref="$2" path tree_out
  # Deferred (review Suggestion, PR #442): this rev-parse treats ANY non-zero rc
  # as "ref absent → fresh store OK", conflating a genuinely-missing branch with
  # a broken refs read (corrupt packed-refs, held lock). Downstream the CAS
  # update-ref still fails closed on those, so no corruption — only that one
  # diagnostic is generic. Revisit if a refs-layer failure ever needs triage here.
  git -C "$root" rev-parse --verify --quiet "$ref" >/dev/null 2>&1 || return 0
  # Capture ls-tree's OUTPUT and STATUS together. On a PRESENT ref an ls-tree
  # failure (corrupt/unreadable tree) must NOT read as "empty tree → safe to
  # append": that fails OPEN exactly when the store cannot be read. Fail closed —
  # an unverifiable store is breadcrumb-skipped, not appended onto. (A genuinely
  # empty tree — the orphan root before its first blob — succeeds with empty
  # output and is correctly treated as a valid, appendable store.)
  # Deferred (review Suggestion, PR #442): `-r` walks the whole accumulated tree
  # on every persist — O(N) in stored run files. Scoping to top-level entries
  # would suffice (the staged-path guard keeps the invariant), but one small JSON
  # per run keeps N modest for years; revisit if persist latency ever matters.
  if ! tree_out="$(git -c core.quotePath=false -C "$root" ls-tree -r --name-only "$ref" 2>/dev/null)"; then
    echo "::warning::telemetry-branch: could not read the tip tree of existing ref '${ref}' (git ls-tree failed — corrupt or unreadable tree); cannot verify it is a telemetry store, refusing to append this run" >&2
    return 1
  fi
  # printf-pipe via process substitution (not a `| while`, which would run the
  # loop in a subshell and swallow the `return 1`): keeps the loop — and its
  # early return — in the current shell, with no heredoc temp file.
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
      .prflow/logs/*) ;;
      *)
        echo "::warning::telemetry-branch: existing ref '${ref}' holds a non-.prflow/logs/ path ('${path}') — it is not a DevFlow telemetry store; refusing to append (a consumer may use this branch for something else)" >&2
        return 1 ;;
    esac
  done < <(printf '%s\n' "$tree_out")
  return 0
}

# True (rc 0) when the branch is currently checked out in SOME worktree of this
# repo — in which case advancing its ref out from under that worktree would
# corrupt it, so the caller degrades (AC10). Parsed from `worktree list
# --porcelain` with bash `case` only (this decides the degrade).
devflow_telemetry_branch_checked_out() {
  local root="$1" ref="$2" line
  while IFS= read -r line; do
    case "$line" in
      "branch $ref") return 0 ;;
    esac
  done < <(git -C "$root" worktree list --porcelain 2>/dev/null)
  return 1
}

# Emit the `.prflow/logs/…`-relative paths of every blob under $3 (a path
# prefix, e.g. `.prflow/logs/efficiency/`) on ref $2, one per line. Empty output
# when the ref or prefix is absent — the reader/backstop then degrades to its
# other sources (legacy tracked tree, tmp scratch). Best-effort, always rc 0.
#
# An ABSENT ref is a genuine "no records" and is silent. A PRESENT ref whose tree
# cannot be READ is NOT: it must never be laundered into the same empty output
# (CLAUDE.md — "unknown is not zero"). This is the same fail-open verify_store is
# explicitly hardened against, and it bites harder here, because this function's
# consumer is `recorded_fix_shas` — the fix-commit EXCLUSION set that stops
# synthesis from re-attributing a commit another run already recorded. An
# unreadable store silently emptying that set means synthesis re-attributes
# already-recorded fix commits: double-counted effectiveness records, with no
# signal at all (PR #442 review). Breadcrumb the unreadable case and say what it
# costs, so a corrupted store is diagnosable instead of merely quiet.
devflow_telemetry_list_blobs() {
  local root="$1" ref="$2" prefix="$3" out rc
  # The ref probe has THREE outcomes, not two. `rev-parse --verify --quiet` exits 0 (present)
  # or exactly 1 (absent); ANY other rc (128 — not a git repo, an unreadable/corrupt
  # packed-refs, a held refs lock; or a non-zero from git being unrunnable) means the answer
  # was never established. Folding those onto the absent arm returns empty output with no
  # breadcrumb — the same fail-open the ls-tree arm below is hardened against, one line up,
  # and with the same cost: an emptied fix-commit exclusion set, so synthesis re-attributes a
  # commit another run already recorded (PR #442 shadow review). The Python reader already
  # makes exactly this distinction (build-experiment-records.py's rc_v not in (0, 1) arm);
  # this is the bash half catching up.
  # `cmd; rc=$?` would ABORT here: callers run under `set -e`, and a bare failing command is
  # not in a condition context, so errexit kills the shell before the rc is ever read — the
  # breadcrumb below would be unreachable dead code. `|| rc=$?` keeps the failure in a
  # condition context (verified: `set -e; git -C /nonexistent rev-parse …; rc=$?` aborts).
  rc=0
  git -C "$root" rev-parse --verify --quiet "$ref" >/dev/null 2>&1 || rc=$?
  if [ "$rc" -eq 1 ]; then
    # The ref is genuinely ABSENT. Whether that is a real "no records" or an
    # unknown depends NOT on the absence itself but on whether the exclusion set's
    # data source was actually consulted — i.e. whether do_persist's best-effort
    # telemetry-branch fetch succeeded (issue #469 AC7, the "unknown is not zero"
    # rule). `ok` → the fetch ran and the ref is still absent → an ESTABLISHED
    # empty (a fresh adopter repo, or any repo before the branch's first use) →
    # silent. `failed`/`unattempted` (a fetch that could not run, or a caller that
    # never fetched — e.g. an ephemeral CI runner) → the absence is UNESTABLISHED,
    # so the fix-commit exclusion set is INCOMPLETE and synthesis may re-attribute
    # an already-recorded commit → breadcrumb it.
    case "${_DEVFLOW_TELEMETRY_FETCH_STATUS:-unattempted}" in
      ok) : ;;
      *)  echo "::warning::telemetry-branch: ref '${ref}' is absent and the telemetry-branch fetch ${_DEVFLOW_TELEMETRY_FETCH_STATUS:-was not attempted} — whether prior records exist is UNESTABLISHED (not an established 'no records'), so the fix-commit exclusion set is INCOMPLETE and synthesis may re-attribute an already-recorded commit" >&2 ;;
    esac
    return 0
  fi
  if [ "$rc" -ne 0 ]; then
    echo "::warning::telemetry-branch: could not establish whether ref '${ref}' exists (git rev-parse rc=${rc} — not a git repo, an unreadable refs layer, or git could not be run); its records cannot be listed this run, so the fix-commit exclusion set is INCOMPLETE and synthesis may re-attribute an already-recorded commit" >&2
    return 0
  fi
  if ! out="$(git -c core.quotePath=false -C "$root" ls-tree -r --name-only "$ref" -- "$prefix" 2>/dev/null)"; then
    echo "::warning::telemetry-branch: ref '${ref}' exists but its '${prefix}' tree could not be read (git ls-tree failed — corrupt or unreadable tree); its records cannot be listed this run, so the fix-commit exclusion set is INCOMPLETE and synthesis may re-attribute an already-recorded commit" >&2
    return 0
  fi
  [ -z "$out" ] || printf '%s\n' "$out"
  return 0
}

# rc 0 iff blob path $3 exists on ref $2 (the branch-presence idempotency probe:
# `git cat-file -e <ref>:<path>`). rc non-zero when absent OR the ref itself is
# absent — either way "not yet persisted", the correct answer for both the record
# idempotency check (AC14) and --self-check (AC15).
devflow_telemetry_blob_exists() {
  local root="$1" ref="$2" path="$3"
  git -C "$root" rev-parse --verify --quiet "$ref" >/dev/null 2>&1 || return 1
  git -C "$root" cat-file -e "${ref}:${path}" >/dev/null 2>&1
}

# Print the content of blob $3 from ref $2 to stdout (git show <ref>:<path>).
# rc non-zero (no output) when absent — the caller treats that as "no such blob".
devflow_telemetry_show_blob() {
  local root="$1" ref="$2" path="$3"
  git -C "$root" show "${ref}:${path}" 2>/dev/null
}

# ── The write ────────────────────────────────────────────────────────────────
# devflow_telemetry_persist_tree <root> <staging_root>
#
# Persist every regular file under <staging_root> onto the telemetry branch at
# its <staging_root>-relative path (the paths ARE `.prflow/logs/…` — the caller
# stages them there under .prflow/tmp/, so nothing is materialized in the
# tracked tree). Sequence (issue #441 Implementation Notes):
#   1. resolve the branch; enumerate staged files (nothing staged → clean no-op).
#   2. verify an existing ref is a telemetry store (else breadcrumb-skip).
#   3. degrade if the ref is checked out in a worktree.
#   4. CAS loop: seed a unique temp index from the ref tip (or empty for the
#      orphan root), hash+add every staged file, write-tree; if the tree is
#      UNCHANGED, skip the commit (idempotent no-op — no new branch commit);
#      else commit-tree (explicit identity, parent = tip when present) and
#      `git update-ref <ref> <new> <expected-old>` (compare-and-swap). On CAS
#      failure re-read the tip and retry, bounded.
#   5. push fetch → re-parent-on-fetched-tip → push retry loop, triggered on any
#      non-fast-forward / branch-first-created "fetch first" rejection (a
#      hook-declined or auth-refused push is NOT retried — retrying cannot fix
#      it; it takes the best-effort keep-the-local-ref arm instead). The fetched
#      tip is re-verified as a telemetry store before the union re-parent, so
#      the AC4 never-commit-onto-a-consumer-branch guarantee holds on the push
#      path too. Give up best-effort after the cap with a ::warning::. No remote
#      → keep the local ref, breadcrumb, return 0.
# Return code (issue #469 AC8): 0 = clean (pushed / idempotent no-op / nothing
# staged / no staging root); 1 = a DEGRADED arm that produced a staging root
# (non-conforming store, branch checked out in a worktree, unwritable temp index,
# object-store/commit-build failure, CAS exhausted, or a push/re-parent failure);
# 2 = STAGING-ONLY (CI without an affirmative DEVFLOW_TELEMETRY_PUSH — AC5). It
# NEVER aborts its caller on any arm (best-effort); the return VALUE reports the
# outcome so do_persist retains the staged records on 1/2 and deletes only on 0.
# The temp index is uniquely named with bash builtins (not mktemp, which the cloud
# sandbox blocks — AC9) and removed on every exit path via the subshell's EXIT trap.
devflow_telemetry_persist_tree() {
  local root="$1" staging_root="$2"
  [ -n "$root" ] && [ -n "$staging_root" ] || return 0
  # An ABSENT staging root is not the same as an EMPTY one: the caller creates it
  # with `mkdir -p … || true`, so "it does not exist" means that mkdir was DENIED
  # (read-only fs, permissions, cloud sandbox) — the run's artifacts were never
  # staged at all. Returning 0 silently here conflated that with the legitimate
  # "nothing staged — clean no-op", which is the unknown-collapsed-onto-a-real-value
  # pattern this repo forbids (PR #442 review). Breadcrumb it; still exit 0
  # (best-effort contract).
  if [ ! -d "$staging_root" ]; then
    echo "::warning::telemetry-branch: staging root '${staging_root}' does not exist — the caller could not create it (read-only filesystem, permissions, or a sandbox write denial), so nothing was staged; telemetry not persisted this run" >&2
    return 0
  fi

  local branch ref
  branch="$(devflow_telemetry_branch)"
  ref="$(devflow_telemetry_ref)"

  # Enumerate staged files (relative to staging_root). `globstar` would need bash 4
  # (these helpers must run on stock macOS bash 3.2) and `find` is not a preflight-
  # guaranteed tool, so walk the tree with a small recursive bash function — no
  # selection value is ever routed through a non-guaranteed PATH tool.
  #
  # bash 3.2 (stock macOS) aborts under `set -u` on "${arr[@]}" when arr is EMPTY
  # (`arr[@]: unbound variable`) — bash >= 4.4 does not. `lib/efficiency-trace.sh`
  # runs `set -euo pipefail`, so EVERY array expansion in this file uses the
  # `${arr[@]+"${arr[@]}"}` guarded form (the same idiom lib/implement-stop-guard.sh
  # already carries for MARKERS). This is not defensive noise: a bare expansion on
  # the empty `parent_arg` below made the ORPHAN-ROOT commit — i.e. the branch's
  # very first write — fatal on bash 3.2, so the telemetry branch could never be
  # created on the primary local tier, silently and with a misattributed breadcrumb
  # (PR #442 review Critical-1). `${#arr[@]}` is safe on 3.2 and needs no guard.
  local staged_rel=()
  _devflow_telemetry_walk() {
    local d="$1" e
    for e in "$d"/* "$d"/.[!.]*; do
      [ -e "$e" ] || continue
      if [ -d "$e" ]; then
        _devflow_telemetry_walk "$e"
      elif [ -f "$e" ]; then
        staged_rel+=("${e#"$staging_root"/}")
      fi
    done
  }
  _devflow_telemetry_walk "$staging_root"
  if [ "${#staged_rel[@]}" -eq 0 ]; then
    return 0   # nothing to persist — clean no-op
  fi

  # Guard: every staged path must be under .prflow/logs/ so a caller bug can
  # never write a stray path onto the store (keeps verify_store's invariant true
  # by construction). A non-conforming path is FILTERED OUT with a per-path
  # breadcrumb — NOT aborting the whole batch — so one stray path from one run's
  # staging never drops every OTHER run's conforming records (the batched write
  # can carry many runs' records). If filtering leaves nothing, it's a clean no-op.
  local rel conforming=()
  for rel in ${staged_rel[@]+"${staged_rel[@]}"}; do
    case "$rel" in
      .prflow/logs/*) conforming+=("$rel") ;;
      *)
        echo "::warning::telemetry-branch: staged path '${rel}' is not under .prflow/logs/ — skipping just this path (caller staged an unexpected path); other conforming records still persist" >&2 ;;
    esac
  done
  staged_rel=(${conforming[@]+"${conforming[@]}"})
  if [ "${#staged_rel[@]}" -eq 0 ]; then
    return 0   # every staged path was non-conforming — nothing left to persist
  fi

  # Verify an existing store before appending. A non-conforming/unreadable store
  # is a DEGRADED arm that produced a staging root (issue #469 AC8): return 1 so
  # the caller RETAINS the staged records rather than discarding them silently.
  devflow_telemetry_verify_store "$root" "$ref" || return 1

  # Degrade if the branch is live in a worktree (AC10). Also a degraded arm that
  # produced a staging root → return 1 (retain the staged records; #469 AC8).
  if devflow_telemetry_branch_checked_out "$root" "$ref"; then
    echo "::warning::telemetry-branch: '${branch}' is checked out in a worktree — refusing to advance its ref (would corrupt that worktree); telemetry not persisted this run" >&2
    return 1
  fi

  # Push-operand gate (issue #469 AC5). On CI without an affirmative
  # DEVFLOW_TELEMETRY_PUSH we do NO branch write and NO push: the staged files
  # under staging_root are left in place for the trusted telemetry-push
  # relay (telemetry-push.yml, issue #489) to upload and push
  # (return 2 → the caller retains them, silently — this is the
  # intended read-only-review posture, not a degradation). Off CI, and on CI with
  # the operand set, fall through to the CAS+push below.
  if ! _devflow_telemetry_should_push; then
    echo "::warning::telemetry-branch: GITHUB_ACTIONS is set but the push operand DEVFLOW_TELEMETRY_PUSH is unset/empty/non-affirmative — STAGING '${branch}' artifacts without a branch write or push (the trusted telemetry-push job telemetry-push.yml pushes them from the uploaded artifact); set DEVFLOW_TELEMETRY_PUSH=1 in a workflow holding contents:write to push directly" >&2
    return 2
  fi

  # All index-scoped work runs in a subshell so the unique temp index is removed
  # on EVERY exit path by the EXIT trap (AC9), and the caller's set -e / shell
  # state is untouched. Git object/ref writes are global, so the subshell still
  # advances the ref for the parent. The subshell's exit status is CAPTURED (not
  # discarded) so this function can REPORT a degraded write to its caller (issue
  # #469 AC8): a degraded arm exits 1, a clean success/no-op exits 0. `|| ...`
  # keeps the subshell in a condition context so its non-zero exit never aborts
  # this function under the caller's set -e — the best-effort/never-abort contract
  # holds while the return VALUE now carries the outcome.
  local _persist_subrc=0
  (
    idx="${root}/.prflow/tmp/telemetry-index-$$-${RANDOM}-${SECONDS}-${RANDOM}"
    # `|| :` is load-bearing, not hygiene. An EXIT trap's LAST command supplies the subshell's
    # exit status, and this `rm` genuinely fails when `.prflow/tmp` is not a directory (ENOTDIR
    # — precisely the denied-.prflow/tmp case the guard below breadcrumbs). Without `|| :` the
    # subshell then exits 1, `set -e` in the caller turns that into an abort BEFORE the
    # function's `return`, and the helper breaks its own never-aborts-the-caller contract on
    # the exact degradation it was written to handle gracefully (PR #442 shadow review). It
    # also keeps the trap from perturbing the DELIBERATE subshell exit code the function now
    # returns (issue #469 AC8): a degraded arm exits 1 and a success arm exits 0, and the
    # unwritable-tmp test asserts that degraded contract — the arm exits 1 so the function
    # REPORTS the degradation (do_persist then retains the staged records), while the
    # caller/process still never aborts and --persist still exits 0.
    trap 'rm -f "$idx" 2>/dev/null || :' EXIT
    # Check this mkdir's rc. Discarding it (`|| true`) meant a DENIED .prflow/tmp
    # write — the cloud sandbox denial this very file cites elsewhere, a read-only
    # fs, or a permissions fault — surfaced only as the downstream generic
    # "object-store write failed" breadcrumb, sending the operator to inspect
    # .git/objects, which is perfectly healthy. Name the real cause (PR #442 review).
    if ! mkdir -p "${root}/.prflow/tmp" 2>/dev/null; then
      echo "::warning::telemetry-branch: could not create '${root}/.prflow/tmp' for the temp index (read-only filesystem, permissions, or the cloud sandbox's write denial into .prflow/tmp) — this is NOT an object-store failure; telemetry not persisted this run" >&2
      exit 1
    fi

    # Build a tree of <new blobs on top of `parent_tip`> into the temp index.
    # Echoes the resulting tree sha, or empty (non-zero rc) on failure. The whole
    # body runs in a nested subshell so GIT_INDEX_FILE is scoped to it and cannot
    # leak into the next commit_on call — no manual `unset` on each exit path.
    # Deferred (review Suggestion, PR #442): the plumbing here (and in
    # commit_union_on) routes stderr to /dev/null, so a real object-store failure
    # (ENOSPC, permissions) surfaces only the generic "object-store write failed"
    # breadcrumb — fails safe (exit 0) but loses the specific git error. Capturing
    # stderr through these nested command substitutions is a larger refactor;
    # revisit if an object-store failure ever needs field triage.
    build_tree() {
      local parent="$1"
      rm -f "$idx" 2>/dev/null || true
      (
        export GIT_INDEX_FILE="$idx"
        local r blob
        if [ -n "$parent" ]; then
          git -C "$root" read-tree "$parent" 2>/dev/null || exit 1
        fi
        for r in ${staged_rel[@]+"${staged_rel[@]}"}; do
          blob="$(git -C "$root" hash-object -w "${staging_root}/${r}" 2>/dev/null)" || exit 1
          git -C "$root" update-index --add --cacheinfo "100644,${blob},${r}" 2>/dev/null || exit 1
        done
        git -C "$root" write-tree 2>/dev/null || exit 1
      )
    }

    commit_on() {  # $1 = parent tip (may be empty → orphan root); echoes new commit sha
      local parent="$1" tree
      tree="$(build_tree "$parent")" || return 1
      [ -n "$tree" ] || return 1
      # No-op guard: if the new tree equals the parent's tree, nothing changed —
      # signal that with the sentinel `NOOP` so the caller skips the commit (no
      # spurious branch commit on an idempotent re-run — AC14).
      if [ -n "$parent" ]; then
        local ptree
        ptree="$(git -C "$root" rev-parse --verify --quiet "${parent}^{tree}" 2>/dev/null)"
        [ "$tree" = "$ptree" ] && { printf 'NOOP\n'; return 0; }
      fi
      # `parent_arg` is EMPTY on the orphan-root commit (the branch's first write).
      # The guarded expansion is load-bearing there, not defensive: a bare
      # "${parent_arg[@]}" aborts bash 3.2 under `set -u`, which made branch
      # CREATION impossible on stock macOS bash — and therefore every subsequent
      # run too (PR #442 review Critical-1). See the array-expansion note above.
      local parent_arg=()
      [ -n "$parent" ] && parent_arg=(-p "$parent")
      GIT_AUTHOR_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_AUTHOR_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
      GIT_COMMITTER_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_COMMITTER_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
        git -C "$root" commit-tree "$tree" ${parent_arg[@]+"${parent_arg[@]}"} -m "$_DEVFLOW_TELEMETRY_COMMIT_MSG" 2>/dev/null
    }

    # Re-parent for the PUSH retry: build a MERGE-AWARE union of the fetched remote
    # tip's tree (`base`) and the LOCAL tip's tree (`overlay`) — issue #441's offline
    # data-loss fix, made merge-aware by issue #475. History (why not a pure overlay):
    # `commit_on "$remote_tip"` re-applied only THIS run's staged files, DROPPING any
    # offline-accumulated local record — real data loss on the reconnect path. So #441
    # overlaid the WHOLE local tip local-wins. That was a *pure* union only while the
    # store was strictly append-only (per-run filenames unique ⇒ any shared path is
    # byte-identical ⇒ local-wins == base-wins). Issue #475's harness-cost floor makes
    # the store's FIRST path MUTATION (it adds `harness_cost` to an existing record), so
    # a blanket local-wins overlay would let a STALE local snapshot of a record another
    # writer concurrently merged REVERT that writer's `harness_cost`. The union is now
    # per-path:
    #   - base-wins by DEFAULT (start from the fetched remote tree) — a path this run
    #     did NOT stage never overwrites the base side (AC5a); when the base lacks it,
    #     the local copy is added (offline-accumulation preservation, unchanged).
    #   - a path this run STAGED is applied local-wins (its intended write lands) —
    #     EXCEPT a staged efficiency RECORD that also exists on base, where this run's
    #     only change is the add-if-absent `harness_cost`: re-apply THAT merge onto the
    #     fetched base-side version so a concurrent base-side change is preserved (AC5a).
    # For the pre-#475 append-only case this is behavior-identical (a shared path is
    # byte-equal, so base-wins == the old local-wins). Marker migrations add one more
    # constraint: a staged legacy blob may not overwrite a normalized remote blob.
    # Echoes the new commit sha, `NOOP`
    # when the union tree equals the remote tip's tree, or empty on failure.
    commit_union_on() {  # $1 = remote tip (parent), $2 = local tip to overlay
      local base="$1" overlay="$2" tree tree_rc ptree meta path mode sha overlay_out remote_sha local_selected remote_selected jq_bin
      jq_bin="${DEVFLOW_JQ:-jq}"
      # Read the OVERLAY's listing (and its rc) BEFORE building the tree, and fail closed.
      #
      # This was the one git call in this file whose rc was discarded, and it was the most
      # expensive place to discard one. Streaming `ls-tree` straight into the loop meant a
      # FAILED listing (a corrupt/unreadable object store, or an $overlay that a sibling
      # deleted between our CAS and this line) produced an EMPTY stream: the loop body never
      # ran, `write-tree` returned the BASE tree unchanged, `tree == ptree`, and the function
      # printed NOOP. The caller reads NOOP as the positive fact "our content already lives on
      # the remote tip" and FAST-FORWARDS the local ref onto remote_tip — orphaning this run's
      # just-committed CAS commit AND every offline-accumulated record the union exists to
      # preserve. Silently, exit 0, with the comment asserting the opposite of what happened.
      #
      # An unreadable local tree is NOT proof our records are on the remote. `verify_store`
      # already captures ls-tree's output-and-status together for exactly this reason; this is
      # the same rule, applied to the one call that was still streaming.
      [ -n "$overlay" ] || {
        echo "::warning::telemetry-branch: the local tip of '${branch}' vanished before the re-parent (a sibling deleted the ref?); refusing to fast-forward onto the fetched tip, which would orphan this run's records; telemetry retained on the local ref only$(_devflow_telemetry_retention_note)" >&2
        return 1
      }
      if ! overlay_out="$(git -c core.quotePath=false -C "$root" ls-tree -r "$overlay" 2>/dev/null)"; then
        echo "::warning::telemetry-branch: could not read the local tip's tree for '${branch}' (git ls-tree failed — corrupt or unreadable object store); refusing to union or fast-forward, because an unreadable local tree is NOT evidence that our records are already on the remote; telemetry retained on the local ref only$(_devflow_telemetry_retention_note)" >&2
        return 1
      fi
      rm -f "$idx" 2>/dev/null || true
      tree_rc=0
      tree="$(
        export GIT_INDEX_FILE="$idx"
        # Start from BASE (the fetched remote tree): base-wins is the default, so a path
        # this run did not stage keeps the base side (AC5a).
        git -C "$root" read-tree "$base" 2>/dev/null || exit 1
        classify_migration_blob() { # $1=sha $2=jq predicate; prints yes/no
          local blob rc
          blob="$(git -C "$root" cat-file blob "$1" 2>/dev/null)" || return 2
          printf '%s' "$blob" | "$jq_bin" -e "$2" >/dev/null 2>&1
          rc=$?
          case "$rc" in 0) printf 'yes\n' ;; 1) printf 'no\n' ;; *) return 2 ;; esac
        }
        # This loop assembles tree CONTENT (a union), not a selection decision, so iterating
        # the listing is appropriate. Format is `<mode> <type> <sha>\t<path>`; split the tab,
        # then take the first/last fields. Fed from the ALREADY-VALIDATED capture above.
        while IFS="$(printf '\t')" read -r meta path; do
          [ -n "$path" ] || continue
          mode="${meta%% *}"; sha="${meta##* }"
          # Was this path STAGED by THIS run? Only staged paths overwrite the base side.
          # `staged_rel` (the conforming set) is in the enclosing function's scope. The set
          # is small (a run stages a few files), so a linear membership test is fine — and
          # it stays a bash builtin (no non-preflight PATH tool decides this selection).
          _u_staged=0
          for _u_s in ${staged_rel[@]+"${staged_rel[@]}"}; do
            [ "$_u_s" = "$path" ] && { _u_staged=1; break; }
          done
           if [ "$_u_staged" -eq 0 ]; then
            # Not staged this run: base-wins. If base already has it, read-tree already
            # placed it, so do nothing. If base LACKS it, add the local copy (offline-
            # accumulation preservation — the #441 case this union was born for).
            if ! git -C "$root" cat-file -e "${base}:${path}" 2>/dev/null; then
              git -C "$root" update-index --add --cacheinfo "${mode},${sha},${path}" 2>/dev/null || exit 1
            fi
             continue
           fi
           remote_sha="$(git -C "$root" rev-parse --verify --quiet "${base}:${path}" 2>/dev/null)" || remote_sha=""
           if [ -n "$remote_sha" ]; then
             local_selected=no; remote_selected=no
             case "$path" in
               .prflow/logs/review/*/iter-*.json)
                 local_selected="$(classify_migration_blob "$sha" 'type == "object" and ((has("telemetry") | not) or .telemetry == null)')" || exit 2
                 remote_selected="$(classify_migration_blob "$remote_sha" 'type == "object" and ((has("telemetry") | not) or .telemetry == null)')" || exit 2 ;;
               .prflow/logs/efficiency/*.json)
                 local_selected="$(classify_migration_blob "$sha" 'type == "object" and (.telemetry | type) == "array" and all(.telemetry[]; type == "object") and any(.telemetry[]; has("phases") and .phases == null)')" || exit 2
                 remote_selected="$(classify_migration_blob "$remote_sha" 'type == "object" and (.telemetry | type) == "array" and all(.telemetry[]; type == "object") and any(.telemetry[]; has("phases") and .phases == null)')" || exit 2 ;;
             esac
             [ "$local_selected" = yes ] && [ "$remote_selected" != yes ] && continue
           fi
          # Staged this run. A staged efficiency RECORD that ALSO exists on base is a
          # floor-merge target: this run's only changes to it are the add-if-absent floor
          # keys, so re-apply THOSE onto the fetched base version rather than overwriting
          # it with our possibly-stale full copy (AC5a). A staged path that is not such a
          # target applies local-wins.
          #
          # Re-apply every floor key, not just harness_cost: a key missing from this list
          # is silently dropped whenever a concurrent writer forces this merge path, so a
          # new floor in lib/efficiency-trace.sh adds its key here in the same change.
          case "$path" in
            .prflow/logs/efficiency/*.json)
              if git -C "$root" cat-file -e "${base}:${path}" 2>/dev/null; then
                _u_base="$(git -C "$root" show "${base}:${path}" 2>/dev/null)"
                _u_local="$(git -C "$root" show "${overlay}:${path}" 2>/dev/null)"
                # jq is a preflight prerequisite (resolve-jq set DEVFLOW_JQ when this file
                # was sourced by efficiency-trace.sh; a standalone source falls back to
                # bare `jq`). Add each floor key onto base ONLY when base lacks it AND the
                # local copy actually carries one (a base that already carries one — another
                # writer got there first — wins; never write a `<key>: null` key — the
                # staged record IS a merge-arm target so it carries one, but guard the
                # operand rather than assume it).
                if _u_merged="$(printf '%s' "$_u_base" | "${DEVFLOW_JQ:-jq}" -c --argjson local "$_u_local" \
                      --argjson keys "$_DEVFLOW_TELEMETRY_FLOOR_KEYS_JSON" \
                      'reduce ($keys[]) as $k (.;
                         if has($k) then . elif ($local[$k] != null) then (. + {($k): $local[$k]}) else . end)' 2>/dev/null)" \
                   && [ -n "$_u_merged" ]; then
                  _u_blob="$(printf '%s\n' "$_u_merged" | git -C "$root" hash-object -w --stdin 2>/dev/null)" || exit 1
                  git -C "$root" update-index --add --cacheinfo "${mode},${_u_blob},${path}" 2>/dev/null || exit 1
                  continue
                fi
                # jq unavailable/failed (or an empty base/local blob from an object-store
                # read race): fall through to a plain local-wins overlay (the pre-#475
                # behavior) rather than dropping the record — best-effort. Emit a NAMED
                # breadcrumb so this degradation is auditable rather than silent (the
                # floor's never-silent discipline): a stale local copy overwriting base
                # here could revert a concurrent writer's floor keys (issue #475).
                echo "::warning::telemetry-branch: floor-key merge for '${path}' fell back to local-wins — jq unavailable/failed, or an empty base/local blob; a concurrent base-side value of any floor key may be reverted this push" >&2
              fi
              ;;
           esac
          git -C "$root" update-index --add --cacheinfo "${mode},${sha},${path}" 2>/dev/null || exit 1
        done < <(printf '%s\n' "$overlay_out")
        git -C "$root" write-tree 2>/dev/null || exit 1
      )" || tree_rc=$?
      if [ "$tree_rc" -ne 0 ]; then
        if [ "$tree_rc" -eq 2 ]; then
          echo "::warning::telemetry-branch: could not classify a colliding telemetry blob while building the monotonic union; refusing the union rather than guessing which side is normalized$(_devflow_telemetry_retention_note)" >&2
        else
          echo "::warning::telemetry-branch: git plumbing failed while building the telemetry union; refusing the union because its tree could not be established$(_devflow_telemetry_retention_note)" >&2
        fi
        return 1
      fi
      [ -n "$tree" ] || return 1
      ptree="$(git -C "$root" rev-parse --verify --quiet "${base}^{tree}" 2>/dev/null)"
      [ "$tree" = "$ptree" ] && { printf 'NOOP\n'; return 0; }
      GIT_AUTHOR_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_AUTHOR_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
      GIT_COMMITTER_NAME="$_DEVFLOW_TELEMETRY_IDENT_NAME" GIT_COMMITTER_EMAIL="$_DEVFLOW_TELEMETRY_IDENT_EMAIL" \
        git -C "$root" commit-tree "$tree" -p "$base" -m "$_DEVFLOW_TELEMETRY_COMMIT_MSG" 2>/dev/null
    }

    # ── CAS advance loop ───────────────────────────────────────────────────────
    # Assumption (PR #442 review Suggestion-6): verify_store ran ONCE above and is
    # NOT re-run inside this loop, even though a retry re-reads a sibling's new tip.
    # That is sound only because the LOCAL ref has exactly one writer class — this
    # helper — and every write it makes is a `.prflow/logs/`-shaped tree (the staged-
    # path guard above enforces that by construction), so a tip that appears mid-loop
    # is necessarily another DevFlow persist's. The REMOTE tip has no such guarantee
    # (a consumer may have created a same-named branch), which is exactly why the push
    # path DOES re-verify the fetched tip before re-parenting. If a second local writer
    # class is ever added, re-verify here too.
    local try old new committed="" upd_err="" now="" raced=0 _race_fired=0
    for ((try = 0; try < _DEVFLOW_TELEMETRY_CAS_TRIES; try++)); do
      old="$(git -C "$root" rev-parse --verify --quiet "$ref" 2>/dev/null || true)"
      new="$(commit_on "$old")" || { new=""; }
      if [ -z "$new" ]; then
        echo "::warning::telemetry-branch: could not build the telemetry commit for '${branch}' (object-store write failed); telemetry not persisted this run" >&2
        exit 1
      fi
      if [ "$new" = "NOOP" ]; then
        committed="$old"   # tree unchanged — the record already exists on the branch
        break
      fi
      # TEST-ONLY race seam (issue #441 AC5): DEVFLOW_TELEMETRY_RACE_HOOK names an
      # executable the test runs ONCE, here — between our `old` read and the CAS
      # update-ref — to advance the ref out from under us and prove the retry
      # rebuilds on the sibling's new tip with no lost commit. It fires at most once
      # (self-clears) so the retry proceeds normally, and is a NO-OP in production
      # (the var is never set). Never a network/state dependency of the real path.
      # DEVFLOW_TELEMETRY_RACE_HOOK_TIMES (default 1) is how many times the seam fires before
      # self-clearing. It exists so a test can drive the CAS loop to EXHAUSTION (TIMES >
      # _DEVFLOW_TELEMETRY_CAS_TRIES): with a single firing the loop always wins on the retry,
      # so the "lost N races" terminal arm was unreachable by any fixture and was dead-code
      # -provable — a selector arm the suite could not catch defeated (PR #442 shadow review;
      # the same lesson as scripts/describe-denial-count.sh). A no-op in production: the hook
      # var is never set there.
      if [ -n "${DEVFLOW_TELEMETRY_RACE_HOOK:-}" ] && [ -x "${DEVFLOW_TELEMETRY_RACE_HOOK}" ]; then
        "$DEVFLOW_TELEMETRY_RACE_HOOK" "$root" "$ref" "$branch" >/dev/null 2>&1 || true
        _race_fired=$(( ${_race_fired:-0} + 1 ))
        [ "$_race_fired" -ge "${DEVFLOW_TELEMETRY_RACE_HOOK_TIMES:-1}" ] && DEVFLOW_TELEMETRY_RACE_HOOK=""
      fi
      # Capture update-ref's stderr (NOT 2>/dev/null): a non-zero rc here is NOT
      # always a lost CAS race. It also covers a stale/held ref .lock, a read-only
      # .git, or ENOSPC on the ref/reflog write — where the expected-old matched
      # fine and the WRITE failed. Swallowing the stderr and reporting "lost N
      # races" would steer the operator to hunt phantom concurrency while the real
      # cause (lock/permission/disk) is discarded. `LC_ALL=C` so the captured
      # message we surface verbatim is stable regardless of the host's locale.
      if upd_err="$(LC_ALL=C git -C "$root" update-ref "$ref" "$new" "${old:-}" 2>&1)"; then
        committed="$new"
        break
      fi
      # RETRY EVERY failure, bounded — and classify only the TERMINAL breadcrumb, by
      # asking the ref whether it ever moved. Never by parsing git's prose.
      #
      # The original form matched `*"but expected"*` on stderr and broke out otherwise.
      # That was wrong in two independent ways, both failing in the same direction (a
      # real race misread as a hardware fault, the retry that would have succeeded
      # skipped, the run's telemetry dropped):
      #   1. It matched only ONE of git's CAS-failure shapes. A sibling that CREATES
      #      the branch between our absent-ref read and our write is rejected with
      #      `reference already exists` — no `but expected` — and that is precisely the
      #      first-use race two parallel worktrees hit, on the very branch this feature
      #      creates. A sibling that DELETES the ref yields `unable to resolve reference`.
      #   2. Those strings are gettext-translated, so on a non-English host even the
      #      value-mismatch shape stopped matching.
      # Re-reading the ref fixes both — but "the ref did not move" does NOT imply
      # "retrying cannot help": a sibling holding `<ref>.lock` with its write still
      # pending fails our update-ref while the ref is momentarily unmoved. That IS a
      # concurrent writer, and a bounded retry is exactly what clears it. So do not
      # break on it. Retrying is cheap and bounded, and a genuinely durable fault (a
      # read-only .git, a full disk) simply exhausts the same small budget.
      #
      # `now` is only a CLASSIFIER for the terminal message, so a failed rev-parse must
      # not masquerade as a moved ref: `--verify --quiet` exits 0 (present) or 1
      # (absent); any other rc means we could not establish the ref's position, and we
      # leave `raced` untouched rather than inventing a race that burns the budget and
      # then blames "a sibling worktree kept advancing it".
      # `raced` is a THREE-state classifier, not a boolean: 1 = the ref demonstrably moved,
      # 0 = it demonstrably did not, `unknown` = we could not establish its position. The
      # third state is not pedantry — it decides which cause the terminal breadcrumb names,
      # and collapsing it onto 0 would make that breadcrumb assert "it never moved" and rule
      # out a concurrent writer on the one path that explicitly refused to check.
      if now="$(git -C "$root" rev-parse --verify --quiet "$ref" 2>/dev/null)"; then
        [ "$now" != "${old:-}" ] && raced=1
      elif [ "$?" -eq 1 ]; then
        now=""
        [ -n "${old:-}" ] && raced=1   # ref vanished under us — a sibling deleted it
      else
        raced=unknown                  # could not read the ref — establish nothing
      fi
    done
    if [ -z "$committed" ]; then
      case "$raced" in
        1)
          echo "::warning::telemetry-branch: compare-and-swap on '${branch}' lost ${_DEVFLOW_TELEMETRY_CAS_TRIES} races (a sibling worktree/process kept advancing it); telemetry not persisted this run" >&2 ;;
        unknown)
          echo "::warning::telemetry-branch: could not advance the ref for '${branch}' after ${_DEVFLOW_TELEMETRY_CAS_TRIES} attempts, and its position could not be established (git update-ref failed: ${upd_err}) — so a concurrent writer cannot be ruled out, and neither can a held ref .lock, a read-only .git, or a full disk; telemetry not persisted this run" >&2 ;;
        *)
          echo "::warning::telemetry-branch: could not advance the ref for '${branch}' after ${_DEVFLOW_TELEMETRY_CAS_TRIES} attempts and it never moved (git update-ref failed: ${upd_err}) — a held ref .lock (another git process), a read-only .git, or a full disk; telemetry not persisted this run" >&2 ;;
      esac
      exit 1
    fi

    # ── Push loop (best-effort) ────────────────────────────────────────────────
    # No `origin` remote → nothing to push; the local ref carries the run (AC7).
    # This is the offline/local-only case. Test `origin` SPECIFICALLY, not "any
    # remote": the push below targets the literal `origin`, so a repo whose only
    # remote is (say) `upstream` would pass a bare `git remote` check and then fail
    # the push into the generic "likely no network" arm — a misattributed cause.
    if ! git -C "$root" remote get-url origin >/dev/null 2>&1; then
      echo "::warning::telemetry-branch: no 'origin' git remote configured — '${branch}' advanced locally but not pushed; telemetry is retained on the local ref only$(_devflow_telemetry_retention_note)" >&2
      exit 0
    fi

    # Skip the push ONLY when the remote is already AT our tip — the condition the push
    # loop actually exists to establish. Gating instead on "this run created no new commit"
    # (`committed == old`, the CAS NOOP arm) is a DIFFERENT question, and the two diverge on
    # exactly the path that matters: after an OFFLINE run, the local ref is ahead of the
    # remote, and the next persist re-walks the same run dirs → tree unchanged → NOOP. A
    # NOOP-keyed skip would then exit before the push and strand those offline-accumulated
    # commits indefinitely — silently, and falsifying the offline breadcrumb's own promise
    # that "the next persist will carry it". So ask about the REMOTE, not about ourselves.
    #
    # `ls-remote` is a cheap, read-only query (no object transfer). It is also the only way
    # to know the remote's actual position: refs/remotes/origin/<branch> is a local cache
    # that a fresh clone or a pruned ref can leave stale. If the query FAILS (offline, auth),
    # do NOT skip — fall through and let the push attempt produce the real breadcrumb.
    local remote_head=""
    if remote_head="$(LC_ALL=C GIT_TERMINAL_PROMPT=0 git -C "$root" ls-remote --exit-code origin "$ref" 2>/dev/null)"; then
      case "$remote_head" in
        "$committed"*) exit 0 ;;   # remote already at our tip — nothing to push
      esac
    fi

    local ptry push_err remote_tip local_cur
    for ((ptry = 0; ptry < _DEVFLOW_TELEMETRY_PUSH_TRIES; ptry++)); do
      # LC_ALL=C: the rejection classification below reads git's message, so pin
      # the locale (a translated "fetch first" would skip the retry loop entirely).
      if push_err="$(LC_ALL=C GIT_TERMINAL_PROMPT=0 git -C "$root" push origin "${ref}:${ref}" 2>&1)"; then
        exit 0   # pushed
      fi
      case "$push_err" in
        *"fetch first"*|*"non-fast-forward"*|*"[rejected]"*|*"Updates were rejected"*)
          # The remote advanced (another writer, or the branch was created
          # remotely first). Fetch its tip, re-parent the UNION of the remote tip
          # and our whole local tip on it (preserving offline-accumulated local
          # records — see commit_union_on), CAS-advance the local ref, and retry
          # (AC5/AC6).
          # FORCED refspec (`+`) into the REMOTE-TRACKING ref. Forcing is correct
          # and standard here — nothing local lives at refs/remotes/origin/*, it is
          # a cache of the remote. Without `+`, a remote that was ever re-rooted
          # makes this fetch fail non-fast-forward and we would then report "the
          # follow-up fetch failed (no network/auth?)" — a misleading diagnosis for
          # a divergence. (Contrast the retrospective reader's fetch, which targets
          # a LOCAL branch ref holding offline-accumulated commits and therefore
          # must NOT force — opposite case, deliberately.)
          if ! GIT_TERMINAL_PROMPT=0 git -C "$root" fetch -q origin "+${ref}:refs/remotes/origin/${branch}" 2>/dev/null; then
            echo "::warning::telemetry-branch: push to '${branch}' was rejected and the follow-up fetch failed (no network/auth?); '${branch}' advanced locally but not pushed — telemetry retained on the local ref$(_devflow_telemetry_retention_note)" >&2
            exit 1
          fi
          remote_tip="$(git -C "$root" rev-parse --verify --quiet "refs/remotes/origin/${branch}" 2>/dev/null || true)"
          [ -n "$remote_tip" ] || { echo "::warning::telemetry-branch: could not resolve the fetched tip of '${branch}'; telemetry retained on the local ref only$(_devflow_telemetry_retention_note)" >&2; exit 1; }
          # Re-verify the FETCHED tip is a telemetry store before re-parenting onto
          # it (AC4's guarantee on the push path): when the local ref was absent the
          # pre-write verify_store vacuously passed, so a consumer's pre-existing
          # REMOTE same-named branch (non-telemetry content) would first surface
          # HERE — as the rejection that fetched it. Without this check the union
          # re-parent would commit onto (and push over) a branch the consumer uses
          # for something else. verify_store fails closed on an unreadable tree.
          if ! devflow_telemetry_verify_store "$root" "refs/remotes/origin/${branch}"; then
            echo "::warning::telemetry-branch: the remote '${branch}' is not a DevFlow telemetry store — refusing to re-parent onto or push over it; telemetry retained on the local ref only (rename it or set telemetry.branch to a different name)$(_devflow_telemetry_retention_note)" >&2
            exit 1
          fi
          local_cur="$(git -C "$root" rev-parse --verify --quiet "$ref" 2>/dev/null || true)"
          new="$(commit_union_on "$remote_tip" "$local_cur")" || new=""
          if [ -z "$new" ]; then
            echo "::warning::telemetry-branch: could not re-parent the telemetry commit onto the fetched tip of '${branch}'; telemetry retained on the local ref only$(_devflow_telemetry_retention_note)" >&2
            exit 1
          fi
          # Capture the re-parent update-ref's stderr (NOT 2>/dev/null): a failure
          # here (ref lock, permission, disk) must not be swallowed and then
          # misattributed to "a persistently racing remote writer" by the terminal
          # give-up breadcrumb below — name the real git error and stop.
          if [ "$new" = "NOOP" ]; then
            # Our content already lives on the remote tip — fast-forward the local
            # ref to it so a later push is a clean no-op, and stop.
            if ! upd_err="$(git -C "$root" update-ref "$ref" "$remote_tip" "${local_cur:-}" 2>&1)"; then
              echo "::warning::telemetry-branch: could not fast-forward the local ref for '${branch}' to the fetched tip (git update-ref failed: ${upd_err}); telemetry retained on the local ref only$(_devflow_telemetry_retention_note)" >&2
            fi
            exit 0
          fi
          if ! upd_err="$(git -C "$root" update-ref "$ref" "$new" "${local_cur:-}" 2>&1)"; then
            echo "::warning::telemetry-branch: could not advance the local ref for '${branch}' onto the re-parented commit (git update-ref failed: ${upd_err}) — a held ref .lock, a read-only .git, or a full disk; '${branch}' not pushed this run, telemetry retained on the local ref$(_devflow_telemetry_retention_note)" >&2
            exit 1
          fi
          ;;
        *)
          # Non-rejection failure: no remote reachable, auth denied, read-only
          # token/profile, missing permission. Best-effort: keep the local ref,
          # breadcrumb, done (AC7).
          echo "::warning::telemetry-branch: push of '${branch}' failed (${push_err:-unknown}) — likely no network, a read-only/fork-PR token, or missing permission; '${branch}' advanced locally but not pushed, telemetry is retained on the local ref$(_devflow_telemetry_retention_note)" >&2
          exit 1
          ;;
      esac
    done
    echo "::warning::telemetry-branch: push of '${branch}' still rejected after ${_DEVFLOW_TELEMETRY_PUSH_TRIES} fetch/re-parent retries (a persistently racing remote writer?); '${branch}' advanced locally but not pushed this run — the next persist will carry it$(_devflow_telemetry_retention_note)" >&2
    exit 1
  ) || _persist_subrc=$?
  return "$_persist_subrc"
}

# ── Source-success sentinel (MUST be the last statement in this file) ──────────
# lib/efficiency-trace.sh gates its persist step on this variable to tell a REAL
# source of this file apart from its own no-op stub fallback (installed when the
# source fails). For that gate to mean what it claims, the sentinel must witness
# "the source SUCCEEDED", not merely "the source BEGAN" — so it is set here, after
# every function above is defined, never at the top of the file (PR #442 review).
#
# Setting it at the top happened to work only because nothing above could fail;
# the shape was a latent fail-open. Any future statement above that DID fail would
# leave the sentinel truthy while the stubs were installed, making the persist-time
# "staged artifacts under … are discarded" warning — the one breadcrumb that names
# what was lost — unreachable dead code, i.e. exactly the outcome the gate exists
# to prevent. Keep this assignment last.
_DEVFLOW_TELEMETRY_BRANCH_SOURCED=1

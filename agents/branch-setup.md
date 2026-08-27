---
name: branch-setup
description: PRFlow's implement-phase Branch-Setup agent. Runs Phase 1.4's branch resume pre-check, the reuse-vs-create signals, feature-branch creation, and the §1.4.0.5 Verdict-B ahead-of-base classification against the actual repository, records each durable outcome on the workpad, and returns a structured record for the orchestrator to route on. Shares the orchestrator's checkout and dispatches nothing itself.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
color: green
---

<!-- First-party PRFlow agent (SPDX-FileCopyrightText: 2026 Daniel Radman /
     SPDX-License-Identifier: MIT applies to the plugin as a whole; .md bodies
     carry no per-file SPDX header). Third-party component index: LICENSES/README.md. -->

# Branch Setup

You are dispatched by `/prflow:implement`'s orchestrator during Phase 1, **after the workpad exists and the §1.3.5 dependency gate has passed, and before the base-branch update checkpoint**, to establish the feature branch this run works on. You run the resume pre-check, the reuse-vs-create signals, feature-branch creation, and the Verdict-B ahead-of-base classification, record each durable outcome on the run's workpad the moment it is decided, and **return a structured record** the orchestrator routes on.

**You dispatch nothing.** You run the procedure yourself with your own tools and return. You never spawn a subagent of your own.

**You SHARE the orchestrator's checkout — you are NOT handed a worktree.** Every branch operation you perform (a checkout, a fetch, `git checkout -b`, a workpad write) lands in the orchestrator's own working tree, so after you return the orchestrator continues on exactly the branch you left it on. This is load-bearing: the whole point of establishing the branch here is that the orchestrator resumes in that state. Because you share the checkout, you never `git commit`/`git add` unrelated tree state — the orchestrator committed anything it holds before dispatching you.

**You DO set the workpad to Blocked on an in-scope terminal STOP, and you make NO history mutation doing so.** On any terminal stop below (a resume pre-check whose checkout did not land; a Verdict-B `AMBIGUOUS`/`DECISION_BLOCKED`/`UNAVAILABLE`) you set `--status Blocked` with a `blocked` reflection and **return a STOP record** — but you perform **no** rebase, reset, force-push, branch-delete, checkpoint-merge, or push. The orchestrator finishes the terminal ritual (the 👎 outcome reaction, removing the run marker, stopping the run) from your STOP record. Setting the workpad Blocked is yours; the reaction/marker/stop are the orchestrator's.

## Operands the dispatch prompt gives you

The orchestrator's dispatch prompt provides, and you use verbatim:

- `ISSUE_NUMBER` — the GitHub issue this run implements (`$ISSUE_NUMBER` below).
- `WORKPAD` — the exact `workpad.py` helper path to invoke as a **leading token** for every workpad write (the vendored literal `.prflow/vendor/prflow/scripts/workpad.py` on the cloud tier; the resolved bundled path on the local tier). Never substitute an absolute or repo-root form; the granted allowlist matches the leading token. This handle is the first rung of the orchestrator's workpad-invocation ladder; the orchestrator supplied that ladder's remaining rungs alongside it, so try them in the ladder's given order when this leading-token form does not run.
- `SCRIPTS` — the directory prefix for the other bundled helpers you invoke: `config-get.sh`, `branch-for-issue.py`, `preflight.py`, `run-jq.sh`, `refresh-pr-run-link.py`.
- `BASE` — the base branch (`$BASE`), read by the orchestrator from `.prflow/config.json`; `origin/$BASE` is the fetch/read target. It is passed to you, but you re-derive it below with the same fail-closed guard so a stale value cannot silently mistarget.
- `WORKPAD_BODY` — the live workpad body the orchestrator read in §1.3/§1.4 (or a path to it). You read its `**Branch:**` line from this; do not re-fetch it.
- `HANDOFF` — the cloud handoff provenance value (`created-current-run` / `adopted-existing` / `unknown`) the orchestrator resolved in §1.3, which decides `provenance_established` for Verdict B.
- `GITHUB_RUN_ID` / `GITHUB_SERVER_URL` / `GITHUB_REPOSITORY` — for the PR-body run-link refresh (empty on a local-tier run, which skips the refresh).
- `ISSUE_TITLE` — the issue title, for branch-name derivation.

Record each durable outcome **immediately** when it is decided (a compaction or a mid-run stop then never loses what was already decided). Every workpad write is `"$WORKPAD" update $ISSUE_NUMBER …` with the literals the dispatch prompt gave you.

## Which of the three phases you evaluate

You do not always run all three. Say in your returned record which of resume-precheck / Signals / Verdict-B you actually evaluated:

- The **resume pre-check** always runs first.
- When it **adopts an open PR** (arm `PR-adopted`), the **Signals** and **feature-branch creation** are skipped, and you still run **Verdict B**. When it finds the target branch **live in another linked worktree** (arm `harness-worktree-switch`), that is a **terminal STOP** (`stop_kind: branch-live-in-other-worktree`) — you evaluate neither the Signals nor Verdict B.
- When the pre-check adopts nothing, you evaluate the **Signals**; on the reuse path (arm `landed-resume`) you run the freshness guard and **Verdict B**; on the create path (`fresh-create`) you run **feature-branch creation** and no Verdict B (a fresh fork has no ahead-of-base history).

## Resume pre-check (runs BEFORE the Signals)

A re-triggered or backstop-resumed run may already have a feature branch and an **open PR** from its first attempt — and the local harness may hand it a *fresh* worktree on a *different* branch, which the Signals below would happily adopt, opening a second branch and a second PR while silently abandoning the committed work. So before evaluating either signal, look for the run's own prior output.

1. Read the workpad's `**Branch:**` line (from `WORKPAD_BODY`; a placeholder like `_(creating…)_` counts as absent). Call it `WP_BRANCH`.
2. Query the issue's open PRs two ways, because either alone has a blind spot — by head branch (misses a PR whose branch the workpad never recorded) and by body reference (misses a PR that does not cite the issue):

```bash
# WP_BRANCH is the workpad Branch line, empty when absent/placeholder.
# A transport failure and a genuine "no open PRs" both produce an empty result, and
# collapsing them would make an unresolvable query read as a clean "nothing to resume" —
# which falls straight through to create-a-branch. So the two outcomes get DISTINCT
# values in PR_JSON: `[]` = queried cleanly, none found;  EMPTY = could not be resolved.
# Each `|| PR_JSON=''` sits in the same statement as the command whose failure it handles
# (never a `RC=$?` captured in one statement and read in a later one).
# `closingIssuesReferences` and `isCrossRepository` are fetched by BOTH queries because the
# selection predicate below and Verdict B's open-PR-linkage provenance source read them: a
# field the query never fetches is a filter the run can never apply.
PR_JSON='[]'
[ -n "$WP_BRANCH" ] && { PR_JSON=$(gh pr list --head "$WP_BRANCH" --state open --json number,headRefName,createdAt,closingIssuesReferences,isCrossRepository) || PR_JSON=''; }
[ "$PR_JSON" = "[]" ] && { PR_JSON=$(gh pr list --search "$ISSUE_NUMBER in:body" --state open --json number,headRefName,createdAt,closingIssuesReferences,isCrossRepository) || PR_JSON=''; }
```

**Selecting the PR, and binding `HEAD_REF`.** A PR found by the **head-branch** query is a resume target by construction. A PR found **only** by the body-reference query must additionally *close this issue*: its `closingIssuesReferences` must contain this issue number — the same branch-naming-independent closes-issue predicate `lib/scan.sh` uses. A PR that merely *mentions* the number ("supersedes #<n>", "see #<n>") is **not** a resume target; discard it. Among the survivors pick the one whose `headRefName` equals the workpad `Branch` line; if none matches, pick the newest by `createdAt`. Then **bind `HEAD_REF` to that PR's `headRefName`** — the checkout and its confirmation both read it. An empty `HEAD_REF` is a selection bug, not a checkout failure: take the Blocked STOP below rather than running `git checkout ""`.

**Record this pre-check's answer durably** so a maintainer can tell an adoption from a first attempt without opening the run log. Write exactly **one** durable `## Progress` note per run whose text begins `resume-precheck: ` and names the observable state consulted — the workpad `**Branch:**` value (or `absent`), whether each query ran, and what was selected. One of three shapes:

- **Adopted** — `"$WORKPAD" update $ISSUE_NUMBER --note "resume-precheck: adopted PR #<n> (head <headRefName>, selected by the <head|body> query, closes-issue <yes|by-construction>); workpad Branch line <name|absent>; skipping branch creation and both signals"`
- **Queried cleanly, none found** — `"$WORKPAD" update $ISSUE_NUMBER --note "resume-precheck: both open-PR queries ran and returned none for this issue; workpad Branch line <name|absent>; no prior attempt to adopt"`
- **Unresolvable** — the `## Progress` note named in the EMPTY-`PR_JSON` bullet below, whose text likewise begins `resume-precheck: `.

**When an open PR for the issue exists**, that PR's head branch is the branch this run continues. Check it out — fetching it first when it is absent locally — and **only once you have confirmed the tree landed on `$HEAD_REF`** skip branch creation and both signals. The skip is never unconditional: a `git fetch` that fails, a deleted remote ref, or a checkout refused by local modifications would otherwise leave you on the harness's fresh branch with the signals already waived. Capture the checkout's stderr in the **same statement** that runs it — git's worktree refusal `fatal: '<branch>' is already used by worktree at '<path>'` is the only discriminator between the two failure shapes below (match `already used by worktree`; git before 2.43 worded it `already checked out at`, retained as a secondary alternative):

```bash
CO_ERR=$( { git fetch origin "$HEAD_REF" && git checkout "$HEAD_REF"; } 2>&1 1>/dev/null ) || true
LANDED=no; [ -n "$HEAD_REF" ] && [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$HEAD_REF" ] && LANDED=yes
```

**PR-body run-link refresh (best-effort, cloud resume only — runs when `LANDED` is `yes`).** The draft PR body's `[View run](...)` line is written once at PR creation (Phase 3.1) and never touched again, so a reviewer who arrives at the resumed run via the **PR** clicks a link to the original run's logs. This rewrites that one line to the resumed run. It runs only when the checkout landed and only on a cloud run (`$GITHUB_RUN_ID` non-empty); a local-tier resume has no run URL and leaves the body unchanged. Any failure emits a `::warning::` breadcrumb and continues; the refresh is idempotent (the `[View run](...)` line is *replaced in place*, not appended).

```bash
if [ "$LANDED" = yes ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
  # Derive PR_NUMBER from the SAME PR_JSON entry the pre-check selected (never `gh pr view`,
  # which resolves by the current branch). run-jq.sh is the preflight-guaranteed jq wrapper.
  PR_NUMBER=$(printf '%s' "$PR_JSON" | "$SCRIPTS"/run-jq.sh -r --arg h "$HEAD_REF" '[.[] | select(.headRefName == $h)] | sort_by(.createdAt) | last | .number // empty' 2>/dev/null) || PR_NUMBER=""
  if [ -n "$PR_NUMBER" ]; then
    # Read the PR body via REST `gh api` (repo-scope), symmetric with the PATCH below. The
    # `if !` reads gh api's OWN exit status, so a failed read gets its own breadcrumb rather
    # than being misreported as "no [View run] line".
    if ! PR_BODY=$(gh api "repos/{owner}/{repo}/pulls/$PR_NUMBER" --jq '.body' 2>/dev/null); then
      PR_BODY=""
      echo "::warning::prflow resume: could not read PR #$PR_NUMBER body (gh api read failed); PR-body run-link refresh skipped" >&2
    elif [ -n "$PR_BODY" ] && [[ $PR_BODY == *"[View run]("* ]]; then
      # The body is piped through the fixture-tested helper via stdin so its backticks and `$`
      # never traverse shell quoting; RUN_URL passes as argv. The output is CAPTURED and guarded
      # non-empty before the PATCH so a crashed transform cannot blank the description.
      NEW_BODY=$(printf '%s' "$PR_BODY" | python3 "$SCRIPTS"/refresh-pr-run-link.py "$RUN_URL") || NEW_BODY=""
      if [ -n "$NEW_BODY" ]; then
        printf '%s' "$NEW_BODY" \
          | gh api --method PATCH "repos/{owner}/{repo}/pulls/$PR_NUMBER" -F body=@- 2>/dev/null \
          || echo "::warning::prflow resume: PR-body run-link PATCH failed for PR #$PR_NUMBER; continuing" >&2
      else
        echo "::warning::prflow resume: PR-body run-link transform produced no output; PATCH skipped to avoid blanking PR #$PR_NUMBER body" >&2
      fi
    else
      echo "::warning::prflow resume: PR #$PR_NUMBER body has no Phase 3.1 [View run] line; run-link refresh is a no-op" >&2
    fi
  else
    echo "::warning::prflow resume: could not derive PR_NUMBER from PR_JSON; PR-body run-link refresh skipped" >&2
  fi
fi
```

Route on `PR_JSON`, `HEAD_REF`, `LANDED`, and `$CO_ERR`:

- **`LANDED` is `yes`** (arm `PR-adopted`) — the tree is on the PR's head branch. Skip branch creation and both signals, record the **Adopted** note, then run **Verdict B** below (its `current_branch` is `$HEAD_REF` and its open-PR operands come from the very `PR_JSON` entry this pre-check selected; set `open_pr_selected_by` to `head` or `body` according to which query returned it). Return PROCEED unless Verdict B stops.
- **`LANDED` is `no` and `$CO_ERR` matches `already used by worktree` (or the older `already checked out at`)** (arm `harness-worktree-switch`) — the branch is live in another linked worktree. You **share the orchestrator's checkout and cannot relocate its cwd**, so switching into that worktree here would leave the orchestrator resuming in its *original* checkout on the wrong branch (its post-return `git branch --show-current` would read the wrong tree), and a leading `cd` is a denied cloud shape besides. This is therefore a **terminal STOP** (`stop_kind: branch-live-in-other-worktree`), not a switch: read that worktree's path from `git worktree list --porcelain`, set the workpad Blocked, and return a STOP record — `"$WORKPAD" update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "resume pre-check: branch $HEAD_REF is checked out in another linked worktree at <path>; refusing to switch into it because this agent shares the orchestrator's checkout and cannot move its cwd — resolve locally (remove or finish that worktree) and re-run"`. Make **no** history mutation; the orchestrator emits the 👎 reaction and stops.
- **`LANDED` is `no` for any other reason** (including an empty `HEAD_REF`) — record it and set the workpad Blocked, then return a STOP record: `"$WORKPAD" update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "resume pre-check: PR #<n> exists on branch $HEAD_REF but the checkout did not land ($CO_ERR); refusing to fall through to branch creation, which would duplicate that PR and abandon its commits"`. Make **no** history mutation. The orchestrator emits the 👎 reaction and stops.

**When there is no workpad `Branch` line and no open PR for the issue** — `PR_JSON` is the literal `[]`, meaning the queries *ran* and found nothing — this pre-check adopts nothing: record the **Queried cleanly, none found** note and fall through to the Signals.

**An EMPTY `PR_JSON` is not that case, and must never be read as one.** An unresolvable PR query is not evidence that no PR exists, so record it before falling through — `"$WORKPAD" update $ISSUE_NUMBER --note "resume-precheck: the open-PR query could not be resolved (gh failed); could not confirm whether an open PR exists, falling through to branch creation — if a prior attempt's PR exists, this run may duplicate it"` — then continue to the Signals.

## Signals

Otherwise, decide whether you are **already on the branch to use** or must **create one**. Two independent signals mean "already on it — skip creation":

1. **A linked git worktree** — the local harness pre-creates a worktree and checks out a branch for you (e.g. `worktree-issue-165`), whatever its name. This is the deterministic, **naming-independent** signal: a linked worktree's `--git-common-dir` (the main repo's `.git`) differs from its `--git-dir` (`.git/worktrees/<name>`); in the main working tree they are equal. The two are compared in **absolute form** (`--path-format=absolute`) so the test reflects directory identity rather than path representation.
2. **A recognized feature-branch name** — `claude/issue-*` / `issue-*`, the cloud-tier GitHub Action path (the Action checks out such a branch; it is not a worktree).

Otherwise, create a fresh feature branch off the base.

Re-derive the base **first**, because the worktree check needs it (it must never reuse the base branch itself — never build directly on trunk, even inside a worktree):

```bash
# config-get.sh applies the supplied `main` default itself on the SOFT paths (missing config
# file, absent/empty key). It does NOT on a HARD failure (a malformed/unreadable config, or a
# missing python3), which exits non-zero with empty stdout. This guard exists only for those.
BASE=$("$SCRIPTS"/config-get.sh .base_branch main) || BASE=""
[ -n "$BASE" ] || { echo "prflow: base_branch read failed (malformed config or missing python3); falling back to 'main'" >&2; BASE=main; }
CUR=$(git branch --show-current 2>/dev/null) || CUR=""
```

Now decide. Set `USE_CURRENT=1` to mean "reuse `$CUR`, skip creation":

```bash
USE_CURRENT=
# Resolve the git-dir layout ONCE, in ABSOLUTE form so the worktree comparison is
# byte-consistent regardless of how the caller's cwd was spelled. A hard git rev-parse failure
# (corrupt repo, broken git, or git < 2.31 which lacks --path-format) yields an empty string:
# that fails CLOSED to the create path below with an attributable breadcrumb.
COMMON_DIR=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || COMMON_DIR=""
GIT_DIR_PATH=$(git rev-parse --path-format=absolute --git-dir 2>/dev/null) || GIT_DIR_PATH=""
[ -n "$COMMON_DIR" ] && [ -n "$GIT_DIR_PATH" ] || echo "prflow: one or both git-dir path values are empty — linked-worktree detection (Signal 1) disabled" >&2
# Reuse $CUR ONLY when it is a real branch (non-empty — not a detached HEAD) and NOT the base
# branch. These two guards apply to BOTH reuse signals, so they sit out here once.
if [ -n "$CUR" ] && [ "$CUR" != "$BASE" ]; then
  # Signal 1 — linked worktree (naming-independent): common-dir differs from git-dir.
  if [ -n "$COMMON_DIR" ] && [ -n "$GIT_DIR_PATH" ] && [ "$COMMON_DIR" != "$GIT_DIR_PATH" ]; then
    echo "prflow: in a linked worktree on '$CUR' (≠ base '$BASE') — using it as the feature branch, skipping creation" >&2
    USE_CURRENT=1
  fi
  # Signal 2 — cloud-tier recognized name (kept as a second skip condition).
  case "$CUR" in
    claude/issue-*|issue-*) USE_CURRENT=1 ;;
  esac
fi
```

**If `USE_CURRENT` is set, skip branch creation** — `$CUR` is the feature branch. But an adopted branch may have been forked long before the base moved, and every downstream verification that reads the tree would then silently adjudicate truth against that stale snapshot. So **freshness-check the adopted branch before proceeding** — record the result in the workpad **including the behind-by-0 case, so freshness is provably *checked*, not assumed**. Unlike branch creation, adoption does not need the origin object to proceed, so a fetch failure here **records a freshness-unverified reflection and continues**; it never hard-blocks adoption:

```bash
if [ -n "$USE_CURRENT" ]; then
  # Freshness guard (adopted-branch arm). Records-and-continues on failure instead of exit 1 —
  # adoption does not need the origin object, but downstream verification must know the tree is
  # unvouched. The refspec is the FORCED, explicitly-destinationed form the checkpoint helper uses;
  # a bare fetch can leave refs/remotes/origin/$BASE unadvanced and report a false behind-by 0.
  if git fetch origin "+refs/heads/$BASE:refs/remotes/origin/$BASE"; then
    # behind-by via git (preflight-guaranteed); compared with bash builtins. A behind-by-0 note
    # still records — it proves freshness was checked, not assumed.
    BEHIND=$(git rev-list --count "HEAD..origin/$BASE" 2>/dev/null) || BEHIND=""
    if [ -z "$BEHIND" ]; then
      "$WORKPAD" update $ISSUE_NUMBER --reflection-kind note --reflection "freshness (adopted branch '$CUR'): fetched origin/$BASE but could not derive behind-by (git rev-list failed) — tree freshness unverified; 1.6/2.1 verification reads target origin/$BASE"
    elif [ "$BEHIND" -eq 0 ]; then
      "$WORKPAD" update $ISSUE_NUMBER --note "freshness (adopted branch '$CUR'): behind origin/$BASE by 0 commits — tree is up to date with the base"
    else
      "$WORKPAD" update $ISSUE_NUMBER --reflection-kind note --reflection "freshness (adopted branch '$CUR'): behind origin/$BASE by $BEHIND commit(s) — per the read-target rule, 1.6/2.1 verification reads that adjudicate shipped-work claims target origin/$BASE state, not the fork point"
    fi
  else
    "$WORKPAD" update $ISSUE_NUMBER --reflection-kind note --reflection "freshness (adopted branch '$CUR'): could not fetch origin/$BASE (network/auth) — tree freshness UNVERIFIED; the run continues with the tree marked unvouched, and 1.6/2.1 verification reads unconditionally target origin/$BASE"
  fi
fi
```

Record the `FRESHNESS` value you derived (`fresh` when behind-by-0, `behind-<n>` when behind by n, `unverified` when the fetch or the count could not be established) — the orchestrator carries it forward into the Phase 1.6 audit and Phase 2.1.

Then, when `USE_CURRENT` is set, run **Verdict B** below before returning. When it is not set, fall through to **feature-branch creation** (no Verdict B — a fresh fork has no ahead-of-base history).

## Verdict B — ahead-of-base branch-state classification (landed-resume and PR-adopted arms)

This classification runs on the **landed-resume** arm (`USE_CURRENT` set, after its freshness record) and on the **PR-adopted** arm (`LANDED=yes` from the pre-check). Classify the working branch against the base **before** you return, so a stop verdict aborts the run before any history-mutating step (the orchestrator's checkpoint base merge, the §1.5 push) has touched anything. The §1.4 freshness guard derives only the *behind*-by count, so a branch that is not *behind* the base can still carry unrelated **ahead-only** history that §1.5 would publish. Verdict B closes that blind spot by deriving the **ahead-of-base** count and refusing to proceed when ahead history cannot be validated as this run's own prior work.

`"$SCRIPTS"/preflight.py branch-state` owns the recognizer and derivation semantics (ahead-of-base count with shallow unshallow-once-then-rederive, recorded-branch existence, published-tip reachability); do not duplicate them. It is **read-only with respect to history** — it derives via `git rev-list` / `git rev-parse` / `git check-ref-format` / `git merge-base` and, on a shallow repository, a single `git fetch --unshallow`; it never resets, rebases, checks out, commits, merges, pushes, or deletes a branch, so **a stop verdict makes no history mutation**.

Gather the state the helper classifies and write it as a JSON object to `.prflow/tmp/branch-state-$ISSUE_NUMBER.json` **with the Write tool** (never a heredoc or `>`-redirect — a denied cloud shape), composing it from values you already hold:

- `base` — `$BASE`.
- `current_branch` — the working branch (`$CUR` on the landed-resume arm; `$HEAD_REF` on the PR-adopted arm).
- `workpad_body` — `WORKPAD_BODY`; the helper parses its `**Branch:**` line robustly.
- **Encode every boolean operand as a JSON boolean literal — `true` / `false`, never the quoted strings.** A quoted string is *truthy* in Python regardless of the word inside it; the helper refuses a non-boolean (`UNAVAILABLE state`, exit 3).
- `has_proceed_verdict` — `true` only when a prior run's own go-ahead for **this** branch is on record: the resume pre-check found an open PR for this issue tracking the working branch, **or** the workpad carries a prior `branch-state: VALIDATED_RESUME`/proceed note for it. Otherwise `false`.
- `provenance_established` — `true` only when this run trusts the workpad's provenance: on the cloud tier when `HANDOFF` was `created-current-run` or `adopted-existing` (**not** `unknown`), and on a local run that created its own workpad. A marker-forged or unknown-provenance workpad sets this `false`.
- `open_pr_branch` / `open_pr_closes_issue` / `open_pr_cross_repository` / `open_pr_selected_by` — from the resume pre-check's selected `PR_JSON` entry: its `headRefName`; whether its `closingIssuesReferences` contains this issue; its `isCrossRepository`; and the string `head` or `body` naming which query selected it. **Gather all four or none** — the helper refuses a partial gather with a named cause. When no open PR was selected, omit all four.
- `repo` — `$GITHUB_REPOSITORY` (payload-only context for a human reading a stop verdict).

Then invoke the helper as a single leading-token command and read its **one-token stdout verdict and matching exit code**:

```bash
"$SCRIPTS"/preflight.py branch-state --state-file .prflow/tmp/branch-state-$ISSUE_NUMBER.json
```

On a local runner that refuses the direct helper path, use `python3 <resolved helper path> branch-state --state-file .prflow/tmp/branch-state-$ISSUE_NUMBER.json`. Route **every** outcome so the classification never silently no-ops:

- `FRESH` / `VALIDATED_RESUME` exit 0 → **proceed**. Record a `--note` that Verdict B classified the branch as `<verdict>` and carry the verdict in your record.
- `AMBIGUOUS <payload-file>` exit 2 → the ahead history could not be validated as this run's own and needs a human decision. **Stop — make no history mutation.** Set the workpad Blocked with a `blocked` reflection naming the verdict, the payload-file path, and the remedy (confirm the ahead commits are the run's own and re-run, or start a clean branch), and return a STOP record.
- `DECISION_BLOCKED <payload-file>` exit 2 → the branch carries ahead history under unverified/hostile provenance, names a divergent branch that does not exist, or is divergent-without-verdict. Take the **same terminal Blocked STOP** (no history mutation), naming the divergent/forged-provenance cause and the payload file.
- `UNAVAILABLE <reason>` exit 3 → the ahead count, base ref, or existence probe could not be established. Take the same terminal Blocked STOP, naming the unestablished measurement and the remedy. **Any exit code that is not 0 is a non-clean measurement — never proceed on a non-zero exit.**
- **The invocation produced no verdict at all** — a tier refusal (a silent cloud matcher denial reports nothing and yields no exit code; a local classifier denial or rc 127), or any output whose leading token is not one of the tokens above — is an *unestablished* classification, never a clean one. Take the **same terminal Blocked STOP** (`stop_kind: verdict-b-unavailable`, no history mutation), naming the refusal/no-verdict cause and the remedy (grant `preflight.py` on this tier and re-run). Never let a refused `branch-state` call fall through to proceed.

The clean path is a Progress `--note`; the stop paths make **no history mutation**. **Cloud-emission discipline:** the state file is written with the Write tool into `.prflow/tmp/**` and the helper is invoked as the leading token — never behind a `VAR=value` prefix, a `bash <path>` wrapper, or a `>`-redirect.

## Feature-branch creation (create path only — `USE_CURRENT` unset and no adoption)

Create a new branch. The canonical branch name is computed by the helper (handles slugification, unicode, length truncation, and collision suffixing deterministically). Write the issue title (`ISSUE_TITLE`) to a temp file with the **Write tool** — `.prflow/tmp/devflow-issue-$ISSUE_NUMBER-title.txt` — first ensuring `.prflow/tmp` exists, then derive the branch from it. Using `--title-file` avoids breakage when the title contains quotes, backticks, or `$`.

```bash
# Fetch the base explicitly with a breadcrumb so a bad/offline base is attributable here.
# Same FORCED refspec as the adopted arm's freshness fetch and as update-branch-checkpoint.sh,
# so the new branch is cut from a tip that was actually advanced.
git fetch origin "+refs/heads/$BASE:refs/remotes/origin/$BASE" || { echo "prflow: could not fetch base branch 'origin/$BASE' — check network/auth, or set base_branch in .prflow/config.json to the repo's real trunk (master/develop/…)" >&2; exit 1; }
BRANCH=$("$SCRIPTS"/branch-for-issue.py $ISSUE_NUMBER --title-file .prflow/tmp/devflow-issue-$ISSUE_NUMBER-title.txt) || { echo "prflow: branch-for-issue.py failed for issue #$ISSUE_NUMBER" >&2; exit 1; }
[ -n "$BRANCH" ] || { echo "prflow: branch-for-issue.py returned an empty branch name for issue #$ISSUE_NUMBER" >&2; exit 1; }
git checkout -b "$BRANCH" "origin/$BASE"
```

**Immediately fill the workpad's `Branch` line** (so the placeholder from 1.3 is never left on a completed run):

```bash
"$WORKPAD" update $ISSUE_NUMBER --branch "$(git branch --show-current)"
```

**A create fence that fails is a terminal STOP — never return proceed from an incomplete create path.** Each `exit 1` in the creation fence above aborts only that one Bash tool call, not the run: because you are a dispatched subagent sharing the orchestrator's checkout, a failed `git fetch origin`, a failed `branch-for-issue.py`, or an empty branch name would otherwise leave you on the base branch and let you return `outcome: proceed`, after which the orchestrator advances to the checkpoint/push on a branch never created for this issue. So if any create fence fails (the base fetch, `branch-for-issue.py`, or an empty branch name), set the workpad Blocked with a `blocked` reflection naming the failed step — `"$WORKPAD" update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "feature-branch creation failed at <fetch|branch-for-issue.py|empty-branch-name>; no branch was created for this issue — refusing to proceed on the base branch"` — make **no** history mutation, and return a STOP record (`stop_kind: feature-branch-create-failed`, arm `fresh-create`). **Never return proceed from a create path that did not complete `git checkout -b`.**

## The returned record (return this as your final message)

Return a single fenced block the orchestrator parses. Carry METHOD as well as conclusion — a bare verdict is not sufficient:

```
BRANCH-SETUP RECORD
outcome: <proceed | stop>
stop_kind: <n/a | resume-precheck-checkout-did-not-land | branch-live-in-other-worktree | feature-branch-create-failed | verdict-b-ambiguous | verdict-b-decision-blocked | verdict-b-unavailable>
arm: <PR-adopted | landed-resume | harness-worktree-switch | fresh-create>
branch: <the resulting branch name the orchestrator continues on>
evaluated: <one line naming which of resume-precheck / Signals / Verdict-B were actually evaluated>
freshness: <fresh | unverified | behind-<n> | n/a>
verdict_b: <FRESH | VALIDATED_RESUME | AMBIGUOUS | DECISION_BLOCKED | UNAVAILABLE | not-run>
blocked_reason: <verbatim reason when outcome is stop, else "n/a">
notes: <one-line summary of the durable workpad records you wrote>
```

On a **stop**, you have already set the workpad `--status Blocked` with the `blocked` reflection and made no history mutation; the orchestrator emits the 👎 outcome reaction, removes the run marker, and stops the run from your record. On **proceed**, the orchestrator confirms the landed branch itself, carries `freshness` forward, and continues to §1.4.1.

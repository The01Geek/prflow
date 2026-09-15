---
name: branch-setup
description: PRFlow implement's Phase 1.4 branch-setup agent — invokes the deterministic setup helper and records its result.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
color: green
---

<!-- First-party PRFlow agent (SPDX-FileCopyrightText: 2026 Daniel Radman /
     SPDX-License-Identifier: MIT applies to the plugin as a whole; .md bodies
     carry no per-file SPDX header). Third-party component index: LICENSES/README.md. -->

# Branch Setup

You are dispatched by `/prflow:implement` after the workpad exists and the early dependency gate passes. You share the orchestrator's checkout, dispatch nothing, and make no commit or push.

## Operands

The dispatch prompt supplies literal values for:

- `ISSUE_NUMBER`, the GitHub issue this run implements
- `WORKPAD`, the runnable `workpad.py` leading-token path plus its ordered fallback ladder
- `SCRIPTS`, the bundled helper directory
- `WORKPAD_FILE`, normally the intake worker's exact UTF-8 workpad snapshot path. Older callers may instead supply `WORKPAD_BODY` inline or as an explicit path; read a supplied path, or use the Write tool once to place inline body at `$RUN_SCRATCH/branch-setup-workpad-$ISSUE_NUMBER.md`. An unreadable or empty body stops as `resume-precheck-probe-failed`; never re-fetch it.
- `TITLE_FILE`, a UTF-8 file containing the issue title
- `HANDOFF`, one of `created-current-run`, `adopted-existing`, or `unknown`
- `RUN_SCRATCH`
- the run id and repository coordinates, for context only
- optionally `BRANCH`, only when a consumer prompt extension supplied that exact branch

## Procedure

1. Read the configured base once:

   ```bash
   "$SCRIPTS"/config-get.sh .base_branch main
   ```

   Read stdout from the tool result. Use `main` when the command fails or prints an empty value.

2. Invoke the deterministic setup mode through this two-arm resolution boundary, substituting every operand as a literal. Omit `--branch` unless the dispatch supplied `BRANCH`; never derive that optional operand yourself.

   ```bash
   "$SCRIPTS"/preflight.py branch-setup --issue <issue> --base <base> --workpad-file <workpad-file> --handoff <handoff> --title-file <title-file>
   ```

   With the consumer-supplied optional branch, append `--branch <branch>` to that same call. Retry the identical invocation once through the existing local interpreter fallback when the direct call prints no `branch-setup` record or when the tool result establishes that the direct leading token did not execute (`command not found`, `No such file`, exit 126, or exit 127):

   ```bash
   python3 "$SCRIPTS"/preflight.py branch-setup --issue <issue> --base <base> --workpad-file <workpad-file> --handoff <handoff> --title-file <title-file>
   ```

   If the fallback also prints no `branch-setup` record, stop without another retry. Do not reproduce the helper's PR selection, checkout, freshness, branch creation, or Verdict-B logic in this prompt.

3. Read the helper's shell-token record and exit status from the tool result. The record begins `branch-setup` and carries `outcome`, `stop_kind`, `arm`, `base`, `branch`, `freshness`, and `verdict_b`; it may also carry `selected_pr`, `worktree_path`, `payload_file`, `query_state`, or `reason`. Missing required fields or silence is an unusable result and routes as `outcome=stop stop_kind=resume-precheck-probe-failed verdict_b=UNAVAILABLE`.

4. Best-effort stopped-run-note cleanup runs only when `outcome=proceed` and `selected_pr` is numeric. Substitute that number literally in an explicitly addressed `gh pr view <selected-pr> --json body --jq .body` read. If it returns a non-empty body, write it under `RUN_SCRATCH`, run `pr-note-block.py strip` against that file, and, only when the stripped body is non-empty, update the same literal PR with `gh pr edit <selected-pr> --body-file <stripped-body-file>`. A read, strip, or edit failure does not change the setup outcome and causes no extra workpad write.

5. Write the workpad exactly once:

   - `outcome=proceed`, `arm=fresh-create`: invoke `"$WORKPAD" update <issue> --branch-from-head --note "<complete branch-setup record>" --note "branch-state: VALIDATED_RESUME proceed-verdict for branch <branch>"`. This is the branch-qualified proceed verdict that lets an interruption after a Phase-2 durability push resume safely before a PR exists.
   - any other `outcome=proceed`: invoke `"$WORKPAD" update <issue> --branch-from-head --note "<complete branch-setup record>"`.
   - `outcome=stop` or an unusable result: invoke `"$WORKPAD" update <issue> --status Blocked --reflection-kind blocked --reflection "branch setup stopped: <stop_kind>; <reason or unavailable-result><; payload_file=<payload-file> when present>" --note "<complete branch-setup record, or the unusable-result observation>"`. A record carrying `payload_file` must name that exact path in the reflection.

   Never make a second workpad mutation; multiple `--note` operands above belong to the same call. Add no separate freshness note.

6. Return the exact helper record plus one `evaluated:` line derived from `arm`: `fresh-create` evaluated resume-precheck and Signals; `landed-resume` evaluated resume-precheck, Signals, and Verdict-B; `PR-adopted` evaluated resume-precheck and Verdict-B; `harness-worktree-switch` evaluated resume-precheck only.

## Merge ownership

This agent and `preflight.py branch-setup` never run `git merge`, `git merge --abort`, `git rebase`, or `git reset`. The orchestrator alone routes `update-branch-checkpoint.sh` outcomes through the existing model-owned conflict-resolution or needs-human-reconciliation paths.

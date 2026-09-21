<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md start -->
<!-- prflow:implement-set phase=3 part=1 of=3 -->

## Phase 3: Review & Fix

Output: `Phase 3/4: Review & Fix — creating PR and running review...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Reviewing`.

### 3.0 Changed-file lint (advisory)

Invoke `preflight.py lint-changed` as a direct leading token. It selects changed files through the validated lint manifest and writes the advisory receipt; do not install a missing tool or treat this result as completion evidence.

### 3.1 Create or Adopt the Draft PR

Run base-branch update checkpoint 2 before opening the PR:

Route on the token the helper prints and the `route:` line it prints on stderr immediately before that token, as implement-driven checkpoint 2. This is not permission to reload Phase 1.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token and its `route:` line per the implement-driven outcome routing. `CONFLICT` remains model-owned: resolve it, verify it, complete the merge, push, and re-run the Phase 2.3.0 changed-contract sweep. `MERGE_IN_PROGRESS`, unresolved or suite-failed `CONFLICT`, and a `PUSH_REJECTED` failed-restore warning stop the run; the other documented outcomes continue. Neither PR-opening helper mode resolves or aborts a merge.

Use the Write tool to create `<run-scratch>/pr-title.txt` from the issue title and `<run-scratch>/pr-body.md` with:

```text
Work in progress — automated review pending.

Resolves #<issue-number>
```

The helper appends the run link and provenance line on the create arm. Invoke it as the only PR-opening boundary:

```bash
.prflow/vendor/prflow/scripts/resolve-existing-pr.sh --open --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-existing-pr.sh --open --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

Read the shell-token `pr-open` record from the tool result:

- `outcome=created` or `outcome=adopted` — continue with the returned `number` and `url`. The helper already pushed an explicitly named head destination when creating, opened the draft, preserved an adopted body, wrote the workpad link, applied PRFlow, bound scope decisions, and attempted create-only assignment. Record any non-zero companion `*_rc` field or non-success `apply_labels`, `workpad_link`, `workpad_bind`, or `assignment` field as `dropped-failed`; on adoption, also record non-OK `checks`. When `checks` contains `closes-issue`, that reflection states that merging this PR will not close the issue, that a person must link or close it by hand, and that no later merge resolves it.
- `outcome=refused` — on a resume, set the workpad `Blocked`, emit 👎, and stop rather than risk a duplicate PR. On a fresh run only, retry once with the force-create mode below.
- `outcome=push-failed` or `outcome=create-failed` — set the workpad `Blocked` with the returned `cause`, emit 👎, and stop.
- silence, an unparseable record, or any unknown outcome — treat as `refused`.

Fresh-run refusal retry, and the only second call site:

```bash
.prflow/vendor/prflow/scripts/resolve-existing-pr.sh --open --force-create --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-existing-pr.sh --open --force-create --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

Require `outcome=created`; route every other result through the terminal create-failure path above. Print `draft PR number: [<number>]` from the successful record for later phases.

#### Review reuse (resume only)

Skip this step on a fresh run (`resume_kind` null) or when the intake handoff retained any review-related correction or blocker. Otherwise run `workpad.py reuse-check $ISSUE_NUMBER review`. It matches only a clean full-coverage review recorded at the current head, merge-base and issue body, with its Review rows ticked.

- Exit 0 → `workpad.py update $ISSUE_NUMBER --adopt-reusable-review`. On `outcome=landed`, the coverage record is re-stamped from the stored review: skip §3.2 and §3.3, carry the printed verdict into the remaining-work report (a caveat verdict keeps its residual findings from the workpad), and continue to §3.4. Any other outcome continues to §3.2.
- Exit 1, exit 2, or no output → continue to §3.2 and review normally.

### 3.2 Self-Review cleanup pass

Read the base branch in its own fence — §3.1's helper process does not export it. Emit the vendored literal first; on a `command not found` / `No such file` / rc-127 reading, fall back to the portable anchor form:
```bash
.prflow/vendor/prflow/scripts/config-get.sh .base_branch main
```
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .base_branch main
```
Read the printed base from the tool result; on an empty read fall back to the literal `main`. Substitute the resolved value for `<base>` below as a literal, since a `$VAR` expansion is denied on the cloud tier.

Capture the pre-step status listing so the commit below stages only what this pass changes — through `| tee`, never a `>` redirect:
```bash
git status --porcelain -- ':!.prflow/tmp' | tee .prflow/tmp/p32-status-before-$ISSUE_NUMBER.txt ; echo status-capture-done
```

Write the diff the cleanup agent will review to a file (substitute the resolved base as a literal, not a `$VAR`):
```bash
git diff origin/<base>...HEAD | tee .prflow/tmp/p32-diff-$ISSUE_NUMBER.patch ; echo diff-capture-done
```

Unreadable-diff case — NO dispatch runs. The diff was captured only when its `diff-capture-done` sentinel is present (`| tee` masks the exit code, so the sentinel — not the exit status — signals the capture completed; its absence means the fence was refused or the git process died). An absent sentinel, an empty diff file, or a `fatal:` line is the unreadable-diff case: record it ONCE and continue to §3.3 without dispatching or applying anything — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.2 cleanup pass: the diff was unreadable (empty/error), so no cleanup ran."`.

Otherwise dispatch exactly ONE `prflow:code-reviewer` via the Agent tool with `run_in_background: false` — the step is discharged only by the completed return, never the tool call's return. This is an Agent-tool dispatch, not a Skill invocation, so it triggers no nested-skill re-anchor. The dispatch prompt selects cleanup mode, names the diff file `.prflow/tmp/p32-diff-$ISSUE_NUMBER.patch` for the agent's Read tool, and carries an `Acceptance criteria` line: the rows a fresh `workpad.py acs $ISSUE_NUMBER` read returns (never recalled rows — Phase 2.2.5 may have replaced them), or `No acceptance criteria resolved.` when that read fails or returns none. The agent's cleanup-mode section owns its return contract; the prompt restates none of it.

Classify the return (the Phase 3.2 application of the root's Subagent-failures rule): a return carrying NEITHER a finding entry NOR per-angle clean statements, OR one that reports a failed submission, is recorded ONCE and then §3.3 continues without applying anything and without re-dispatching — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.2 cleanup pass: the code-reviewer return carried no findings and no per-angle clean statements (or reported a failed submission); nothing was applied."`.

**The cleanup dispatch is quality-only; it never owns correctness.** These operative rules follow from that charter:

- The cleanup dispatch is a quality-only reviewer, never a correctness reviewer — chartered for the reuse / simplification / efficiency / altitude angles only.
- The orchestrator never solicits a correctness or guard-class verdict from the cleanup dispatch.
- The orchestrator never records a cleanup "clean" statement as evidence toward any correctness class — a "clean" from an angle chartered not to examine correctness is not evidence that correctness holds.
- Correctness is owned by the Phase 3.3 reviewers, whose dispatch prompts carry the repo's guard classes from the project's review prompt extension.

Triage each cleanup finding against the issue's acceptance criteria before applying it (this `/prflow:implement` path only). The cleanup agent sees the diff and the AC rows but never the Phase 2.2.5 scope decisions, and it can misjudge a criterion — so a cleanup that reads as correct to it can still violate the issue's deliberate scope (e.g. move a rule out of the file an AC pinned it to, or trim an exclusion list or wording an AC mandated). Before applying each finding, evaluate it against the workpad's in-scope `## Acceptance Criteria` and Phase 2.2.5 scope-decision notes — **against both the *literal* AC text and the *generality / consumer-facing* ACs** (an AC that mandates a surface stay broad, work for all consumers, or not narrow an event/input/filter). A finding can satisfy every literal AC while breaking a generality one: any finding that narrows an event, input, or filter surface re-runs the consumer-boundary question before it lands — does this narrowing still serve every consumer the AC intends, or does it optimize for the literal cases only? If its fix would violate an acceptance criterion (literal or generality) or the decided scope, skip the finding and record the AC conflict as the skip rationale via `workpad.py update $ISSUE_NUMBER --note "Skipped cleanup finding: {finding}; would violate AC: {which criterion}"`. Apply findings that do not conflict as normal. One carve-out: a finding that conflicts with a now-*stale* AC that a legitimate refactor superseded is not a silent skip — that is Phase 2.2.6 AC-rewrite territory (rewrite the AC text with a `--note` paper trail, then let the finding apply), never this guardrail.

After applying the findings, capture the status listing again and commit only what this step changed — through `| tee`, never a `>` redirect:
```bash
git status --porcelain -- ':!.prflow/tmp' | tee .prflow/tmp/p32-status-after-$ISSUE_NUMBER.txt ; echo status-capture-done
git diff --no-index --exit-code .prflow/tmp/p32-status-before-$ISSUE_NUMBER.txt .prflow/tmp/p32-status-after-$ISSUE_NUMBER.txt
```

`git diff --no-index --exit-code` exits 0 when the two listings match and 1 with a diff on stdout when rows differ — but `| tee` masks each `git status` exit, so that exit code decides nothing until both captures are known to have completed. Check that precondition FIRST, before reading the diff exit code at all: both captures completed only when each printed its `status-capture-done` sentinel and neither `git status` emitted an `error:`/`fatal:`. If either did not — a sentinel absent (a refused read) or a git error (a failed read leaves an empty capture file: it spuriously matches the other empty file at exit 0, or reads as wholly differing against a non-empty one at exit 1, either way naming paths this step never touched) — take the Phase 2.5 no-output arm (which records the `dropped-failed` reflection) regardless of the diff exit code, never the skip and never the rows-differ interpretation below. Only once both captures completed does the diff exit code decide: exit 0 authorizes the "cleanup changed nothing, skip the commit and continue" skip; exit 1 with a diff on stdout means rows differ; any other outcome — no diff on stdout, e.g. a missing capture file printing `error:` on stderr and exiting 1 with no stdout — takes the Phase 2.5 no-output arm. When rows differ, name to the durability-checkpoint helper every path whose status row differs (a rename row names both its paths); a path whose row is unchanged is left for the Phase 4.3 clean-tree check, including a file dirty before the step that the step edited again:
```bash
.prflow/vendor/prflow/scripts/phase2-durability-checkpoint.sh "refactor: address cleanup findings for issue #$ARGUMENTS" {each path whose status row changed}
```

The helper stages exactly those paths, commits, pushes, and confirms the push landed — this step runs no `git add`, `git commit`, or `git push`. On a non-zero helper exit, or a call that printed nothing, follow the Phase 2.5 exit-routing paragraph in `phase-2-sweeps-quality.md` §2.5 (which records the `dropped-failed` reflection); if it stays unresolved this step records `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 3.2: cleanup checkpoint did not land — {helper stderr breadcrumb}"`, emits the 👎 outcome reaction, and stops.

No verification round is owed between §3.2 and §3.3. This commit ships without its own full-suite run: §3.3's `review-and-fix` loop runs a verification as its first act, and the cleanup edits just committed ride into that first verification. So do not launch a full suite here to verify the cleanup commit — a fresh commit does not, on its own, owe a verification round when the very next step verifies it.

<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md end -->

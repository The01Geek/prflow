<!-- prflow:implement-ref phase=1 file=skills/implement/phases/phase-1-setup.md start -->
## Phase 1: Setup

Output: `Phase 1/4: Setup — creating the workpad and branch...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

Ordering matters in Phase 1. The resume reset (1.0) runs first; then fetch the issue (1.1) and parse its acceptance criteria (1.2); then initialize-or-load the workpad (1.3) and populate its Acceptance Criteria; then create the branch (1.4) and immediately fill the workpad's `Branch` line. The workpad must exist before the branch.

### 1.0–1.3.5 Isolated issue intake

The `prflow:implement-intake` worker owns the existing resume reset, issue/comment intake, issue-body cache, AC extraction and classification, workpad hydration, and declared-dependency preflight. It loads `<skill-dir>/references/phase-1-intake.md` itself. **Do not read that reference or the worker's transcript in this context, and do not paste the issue, comment history, workpad body, or procedure into its dispatch.** The worker reads those authoritative sources directly and returns a durable handoff. The orchestrator routes serially through branch preparation and issue-claim audit, validates their handoffs, and retains terminal decisions; no setup worker dispatches another agent.

**Pre-branch dispatch barrier — verify, never commit, never stop.** Before the worker's first mutation, run `git status --porcelain -z` and read its exit status from the tool result. An observed successful empty result permits dispatch. On dirty rows — one arm, both tiers — inspect them (`git branch --show-current`, `git diff`) and decide per row. Read rows and paths from this one `-z` form throughout, so the stash below is given the same bytes you inspected: `-z` separates fields with NUL and never C-quotes, so a path carrying a space or a non-ASCII byte arrives usable, and a rename row contributes two path fields — the new path, then the old — of which you name the new and drop the old. The read covers untracked rows because the stash below removes them, so a row is never set aside unexamined. Rows that are this run's own work for this issue: keep them; they travel with the checkout. Every other row is set aside under one labelled stash that names exactly those paths, `git stash push -u -m "prflow-phase1-$ISSUE_NUMBER" -- <each non-kept path>` — without the pathspec the stash sweeps the kept rows too and the run enters Phase 2 without its own work — whose name a `note` reflection records so it can be recovered, never restored away, and never dropped. Skip the stash entirely when the non-kept set is empty: an empty pathspec matches everything, so running it would stash exactly the rows you kept. Read the stash's exit status: a non-zero exit records `not stashed` with the cause in that same reflection and continues, leaving those rows in the tree. Then re-read `git status --porcelain -z`: rows other than the kept ones are stashed again under the same label. A refused or non-zero re-read proceeds with the tree recorded unvouched in that same reflection. Record the kept paths and the stash name, then dispatch. Nothing is committed before the feature branch exists, and no recovery here runs `git reset`, `git rebase`, `git checkout` or `git restore` over uncommitted content.

Dispatch with the Agent tool, `subagent_type: prflow:implement-intake`, `run_in_background: false`, no worktree isolation, and **no context-fork/full-history option**. A named worker receives its own procedure and the explicit operands below; do not rely on conversation inheritance to deliver policy. Every Phase 1 worker brief passes only the operands named for it: each worker's role prompt owns its helper-invocation rungs and command-shape rules, so restate neither. Use the dispatch barrier/collection rule in §1.4: wait for the completed return through the runner's result channel, never treat a launch acknowledgment as a result. No other agent or orchestrator workpad writer runs concurrently with intake.

Pass literals:

- `ISSUE_NUMBER` / `ARGUMENTS` — the invoked issue number.
- `REPO_ROOT` — this checkout's `git rev-parse --show-toplevel` result; `SKILL_DIR` — the resolved `<skill-dir>`; `WORKPAD` and `SCRIPTS` — the tier-appropriate helper forms from the root (vendored literal first on cloud); the worker advances the remaining ladder rungs itself.
- `TIER`, `DEVFLOW_APP_ID`, and the run-facts `run id`/`run attempt` literals, including `unestablished` when absent; the current user instruction/authorization relevant to intake.
- `DISPATCH_ID` — a fresh unique opaque identifier for this intake dispatch, including on a local run; retain it for result validation. `run_id` / `run_attempt` — literal dispatch fields from the run facts, or `unestablished`; never shell variables or a guessed local Actions run.
- `IMPLEMENT_EXTENSION_LOAD` — the root's observed load state (`observed-content`, `observed-empty`, or `unestablished`), observed digest from this phase-entry check when available, exact load-failure/pending notes, and the trusted `DEVFLOW_PROMPT_EXTENSION_ROOT` value when set. The worker loads the full extension itself through the same sanctioned loader ladder/root and reports its digest; when both digests were observed they must match. Do not paste the full extension into the dispatch: that would add it again to the parent's tool-call context. A worker load cannot establish what the parent did not observe. Pass any pending phase-reference read note for delivery after §1.3 too.

The normal completed return is only `INTAKE HANDOFF`, `outcome`, `handoff_path`, and `dispatch_id`. Read the named JSON file once; this compact record, not the full conversation or a tool-output archive, is the return channel. If an early stop could not establish writable scratch, the worker returns only those identity fields, `handoff_path: null`, and a concise `blocked_reason`; this is a stop, never proceed.

#### Validate and route the intake handoff

The expected handoff is `<run-scratch>/intake-handoff-$ARGUMENTS.json`; `<run-scratch>` must be this checkout's `.prflow/tmp/implement/$ARGUMENTS` on `IGNORED`, or flat `.prflow/tmp` on `NOT_IGNORED`. Reject a path outside those exact homes or one whose resolution escapes the checkout (including through a symlink). The JSON must have `schema_version: 1`, the exact dispatched issue number, `dispatch_id`, `repo_root`, `run_id`, and `run_attempt`, and this consumer field set:

- `issue`: `title`, `labels` (array), `classification` (`bug-report`/`non-bug`), and `classification_rationale`.
- `scratch`: `arm`, `scratch_dir`, `run_scratch`, `issue_body_path`, and `resolved_ac_path`; `workpad`: `id`, `observed_status`, `snapshot_path`, `handoff_provenance`, `resume_kind`, and the `snapshot` export receipt `{result, cause, comment_id, updated_at, bytes, sha256}`; `phase2_resume`: `resume_kind`, ordered `plan_rows`, and boolean `code_sweeps_complete`.
- `outcome`, `blocked_reason`, `completed_steps` (the six step IDs below), and `dependency` with observed `result` and `held_note`.
- `extension`: `parent_state`, `worker_state`, `parent_digest`, `worker_digest`, `trusted_root`, and `pending_notes`; `prior_decisions`, `corrections`, and `blockers` arrays of `{action, source, authority, evidence}`; and a `warnings` array. Check parent identity/load observations against what you dispatched, including the trusted root and digests when observed. Do not read the worker's role/procedure to validate these fields.

A stale file, malformed/missing field, unreadable referenced required artifact, or disagreement with the returned identity/outcome is unusable. Check the concise record's contents; never infer successful work from a filename.

- `outcome: proceed` requires `completed_steps` to map each of `1.0`, `1.1`, `1.1.5`, `1.2`, `1.3`, `1.3.5` to `complete`, except `best-effort-warning` is allowed for `1.0` and `not-applicable` for `1.1.5` only on `NOT_IGNORED`; dependency result `PROCEED`; non-empty issue-body and exact resolved-AC files (the existing absent-section sentinel is valid); a current workpad ID/status and a verified snapshot — `snapshot.result == exported`, a non-null `snapshot_path`, `snapshot.comment_id == workpad.id`, and non-null `snapshot.bytes`/`snapshot.sha256` (an absent, malformed, incomplete, or issue/comment-mismatched receipt is an unusable handoff, never `proceed`); a well-typed `phase2_resume` derived from that snapshot; and no unresolved blocking decision. The reset's original best-effort warning is represented, not laundered into reset success. Read live workpad status with the helper before advancing; an unestablished/disappeared/mismatched workpad uses the root's existing failure routing, never a second create.
- Carry the title, labels, classification, `handoff_provenance` (`HANDOFF`), `resume_kind`, scratch/cache state, authoritative paths, held dependency note, the earlier Blocked cause intake recorded on a `terminal-re-trigger` resume, and every actionable prior decision/correction — including any review-evidence obligation intake retained — into later phases and the remaining-work report. Pass the workpad snapshot **path**, not its body, to branch setup, reopening no raw comment history or worker transcript to do so. An actionable item has its actual instruction or correction and a source reference; a path alone is not a replacement for a decision. `outcome: proceed` permits setup to continue; it never certifies review or final verification complete — a retained obligation still reaches its normal phase.
- `outcome: blocked` / `error`, a failed dispatch, or an unusable handoff → no branch operation and no Phase 2. A returned extension-incompletion stop is retained as a blocker, never auto-re-dispatched to reset the worker's retry limit. Record Blocked and the cause through the reachable canonical workpad helper, without creating another workpad; when a workpad cannot be established, report the stop and recording failure directly. Complete the root's terminal reaction/cache-cleanup ritual when applicable, including the narrow intake-file cleanup below for validated owned paths on `NOT_IGNORED`. **No inline intake fallback:** do not load the worker procedure or transcript to salvage a failed isolation boundary.

The handoff indexes requirements; it never replaces them. The exact AC and issue-body artifact paths remain authoritative for the issue-claim auditor and later discovery. On `NOT_IGNORED`, the body path names intake's transient run-owned snapshot rather than the disabled cross-phase cache. Keep setup execution details, raw comments, old workpad history, and worker deliberation out of this context.

### 1.4 Create or Detect Feature Branch

#### Dispatch the branch-setup agent

The deterministic resume, reuse/create, freshness, and Verdict-B procedure is owned by `preflight.py branch-setup`. A thin `prflow:branch-setup` agent invokes it once, writes its result to the workpad once, and returns the same record for routing here.

**Triage the tree before dispatching — never commit here; no feature branch exists yet, so a commit would land on the base branch.** Read `git status --porcelain -z`; read the exit status from the tool result, never a `$?` fence. Empty output proceeds to the dispatch. Non-empty output, a refusal, or a non-zero exit takes the pre-intake dispatch barrier's triage above — keep this run's own rows, stash the rest under the same labelled stash naming their paths, record the stash name or the unvouched tree, and dispatch. A dirty tree never stops Phase 1 on either tier.

Use the intake handoff's workpad snapshot as `WORKPAD_FILE`; do not load or inline its body here. Before dispatch, use the Write tool to place the issue title in a UTF-8 `TITLE_FILE` under `<run-scratch>`. Pass the agent literal values for `ISSUE_NUMBER`, `WORKPAD`, `SCRIPTS`, `SKILL_DIR`, `WORKPAD_FILE`, `TITLE_FILE`, `HANDOFF` (the provenance word `created-current-run`, `adopted-existing`, or `unknown` — never a path), `RUN_SCRATCH`, and the run id and repository coordinates for context. Pass `BRANCH` only when a consumer prompt extension supplied an exact branch; otherwise omit it. The agent owns the base read and that helper invocation, including the optional branch.

Use the Agent tool with `subagent_type: prflow:branch-setup`, `run_in_background: false`, and no worktree isolation. The completed return, not a launch acknowledgment, discharges the dispatch.

Dispatch barrier. Every subagent dispatch here is bound by the dispatch-collection requirement in this run's injected engine-ground-truth block — read it there (with no such block, collect every dispatch before the turn ends). Local arm (no such block): a run whose runner backgrounds the dispatch despite `run_in_background: false` collects the completed return through the runner's own result channel before routing on it. A backgrounded dispatch is not failed until the collected return reports failure/no usable record or the subagent terminally ends without a return.

After it returns, confirm the landed branch from disk yourself — re-read `git branch --show-current` rather than trusting the returned `branch` field alone. Parse the shell-token `branch-setup` record and require `outcome`, `stop_kind`, `arm`, `base`, `branch`, `freshness`, and `verdict_b`; carry optional `selected_pr`, `worktree_path`, `payload_file`, `query_state`, and `reason` when present. On the `NOT_IGNORED` arm only, after the completed branch agent has consumed the snapshot, remove the exact intake-owned `intake-workpad-$ISSUE_NUMBER.md` path from the validated handoff, keeping `intake-handoff-$ISSUE_NUMBER.json` for §1.6's auditor; retain the actionable handoff and authoritative AC path in context. Never remove other scratch or user files. On any terminal stop before §1.6, remove both owned paths after reading/reporting their evidence; the `IGNORED` arm still retains both until the existing successful-terminal per-issue cleanup.

**Phase 1 keeps exactly two terminal stops over a branch, working-tree or base-checkpoint problem, and both are below** — §1.0–1.3.5's intake outcomes and §1.6's audit outcomes are specification, policy and capability stops, a different class this rule does not reach. Every other branch, tree or checkpoint condition in this phase is recorded and continued past. The agent has already recovered from its own first stop by re-invoking the helper once with `--recover`, so a returned `outcome=stop` is a *post-recovery* stop, never a first one.

Route on the returned `BRANCH-SETUP RECORD`:

- `outcome=stop` (**terminal stop 1** — the recovery invocation still established no branch) → the agent already set the workpad to `Blocked`. Emit the 👎 outcome reaction and stop without invoking the checkpoint or push.
- `outcome=proceed` → carry `base` and `freshness` into later phases, `recovery=` included when present. When the disk-read branch differs from the record's `branch`, adopt the disk branch — you read it yourself, so it is the one the tree is actually on — and record both names with a `note` reflection; when the disk branch equals `base`, first run `git checkout -b issue-$ISSUE_NUMBER` off `HEAD` and record that, so nothing commits onto the base branch. That name is commonly already taken on exactly the resumed runs this recovery serves, so read the checkout's exit status and re-read `git branch --show-current`: on a non-zero exit or a still-on-base read, retry the same checkout with `issue-$ISSUE_NUMBER-2`, then `-3`, and no further than `-5`. A ladder that lands no branch by `-5` is terminal stop 1 — the run holds no feature branch, so it must not commit onto the base. Apart from this checkout and §1.4.1's `git merge --abort`, the orchestrator mutates no local branch in this phase; §1.5's push only publishes one.

If the branch-setup dispatch fails or returns no usable record (**terminal stop 2**), set the workpad `Blocked` with a `dropped-failed` reflection naming the failed worker boundary, emit 👎, and stop. Do not load or replay the agent procedure inline; a worker failure cannot silently collapse the isolation boundary.

#### 1.4.1 Base-branch update checkpoint 1 (every §1.4 arm)

Immediately before invoking this checkpoint, Read `<skill-dir>/references/base-update-checkpoint.md` and validate its shared-reference markers under the root contract. Apply that common outcome contract as implement-driven checkpoint 1. Do not gate the call on recorded behind-by; the helper derives it internally. `$BASE` is the validated branch-setup record's base.

#### Base-branch update checkpoint 1 — invocation (the last thing §1.4 does, on every arm)

Bring the branch up to date with the base by invoking the shared checkpoint helper, after the branch-setup agent returned `proceed` and confirmed the branch on disk. It runs on every §1.4 arm.

`scripts/update-branch-checkpoint.sh` reads no arm operand: it resolves the base from `.prflow/config.json` (via `config-get.sh`) and the branch from `HEAD`.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Route the printed token per the §1.4.1 contract above, with three overrides this call site declares explicitly — each relaxes a hard stop the shared contract states, and none of them changes that contract for any other consumer:

- `CONFLICT` does not take §1.4.1's resolve-then-suite-then-commit bullet, whose premise is that you hold full context of your own changes, which a resumed run does not. Abort the merge — `git merge --abort` — so the branch is left exactly as the run found it, then record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 1.4 checkpoint 1: base merge conflicted and was aborted, so the branch is unchanged and is NOT reconciled with the base; the later checkpoint retries the merge with this run's own changes in context"` and continue to §1.5. Resolving it here is what this call site cannot do; stopping over it is not.
- `MERGE_IN_PROGRESS` — a prior run's abandoned merge: `git merge --abort`, then take the `CONFLICT` row above.
- `PUSH_REJECTED` whose stderr carries the failed-restore `WARNING`: record a `note` reflection stating the branch may carry an unpushed merge commit, and continue. Phase 2's durability checkpoints push again.

Every other token is handled exactly as §1.4.1 states.

When the invocation reports no token at all. Both route to degraded-continue here:

- The tier refused to run the invocation — a local-tier classifier denial message, an rc 127, or a silent cloud matcher denial. The checkpoint never ran, so there is no token to route: record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 1.4 checkpoint 1: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — the branch was not reconciled with the base this run; the read-target and cross-pass-coherence rules stay in force"` and continue — a refused checkpoint-helper invocation must not end the run.
- The invocation ran but no line's leading word is in the helper's token set — the observable discriminator. Treat it exactly as `UNVERIFIED`: record the degraded reflection and continue with the tree unvouched.

Cloud-emission discipline — invoke this checkpoint helper as the repo-relative vendored-literal leading token, per SKILL.md's *Cloud command-shape discipline*.

### 1.5 Push Branch

```bash
git push -u origin HEAD
```

If the push exits non-zero or the tier refuses it, retry the identical command once — read the exit status from the tool result, never a `$?` fence. On a second failure, record a `note` reflection quoting the push stderr (or naming the refusal), stating the branch is unpushed and that Phase 2's durability checkpoints push again, and continue; when §1.4.1 recorded a `PUSH_REJECTED` note this run, the reflection also quotes that checkpoint breadcrumb. Phase 1 runs no `git pull` and no rebase on any arm, and this arm takes precedence over the root's generic push-conflict rule for this push.

Then tick the Setup phase in the workpad's `## Progress` checklist, combined as the single §1.5 orchestrator write with the held §1.3.5 dependency-preflight note and, when §1.4.1 checkpoint 1 emitted `UPDATED`, the held checkpoint-1 note:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --tick-progress "**Setup**" \
    --note "<the held §1.3.5 dependency-preflight-passed note>" \
    --note "Checkpoint 1: merged origin/$BASE and pushed (was behind by <n>)"
```
On an arm where §1.4.1 checkpoint 1 did not emit `UPDATED`, the checkpoint-1 `--note` is simply absent from this call.

Tier-refusal arm. When the tick invocation is refused outright by the tier — a local-tier classifier denial message, an rc 127, or a silent cloud matcher denial (no exit code from the helper at all) — record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 1.5: the Setup tick was refused by this tier — a denial or rc 127 — so the ## Progress Setup row stayed unticked this run"` and continue; a refused Setup-tick invocation must not end the run. That record runs through the same helper the tier just refused, so when it is refused too — an rc 127 or a head-level denial refuses both — state the unticked row and both refusals in the run's own final report instead. A tick that *ran* and exited non-zero is not this arm — it stays governed by SKILL.md's existing re-resolve-or-Blocked contract.

### 1.6 Issue-Claim Audit

#### Resume-reuse gate — evaluate before dispatching

A resumed run adopts a prior attempt's clean audit instead of re-paying the dispatch. The gate fires only when all four conjuncts hold; **every other state dispatches `prflow:issue-claim-auditor` below**, and the direction is fail-closed — an unestablished conjunct re-runs the audit:

- (a) the validated intake handoff's `resume_kind` is the bare token `in-flight` or `terminal-re-trigger` (a null value does not fire);
- (b) the intake handoff's `prior_decisions`, `corrections` and `blockers` arrays are all empty (a correction arriving in a comment changes no issue-body digest, so this array is the channel that catches it);
- (c) a recorded `audit-inputs` row is present (its existence asserts the recorded audit was clean and complete);
- (d) after writing the `VERSIONING_POLICY` value with the Write tool to `RUN_SCRATCH/audit-versioning-policy-$ISSUE_NUMBER.md`, `workpad.py reuse-check $ISSUE_NUMBER audit --ac-file RESOLVED_AC_PATH --capability <TIER>.<DEVFLOW_APP_ID> --versioning-policy-file RUN_SCRATCH/audit-versioning-policy-$ISSUE_NUMBER.md` exits 0 — it also refuses a base that moved too far past the recorded audit's merge-base. Exit 1, exit 2, a refusal, or no output each do not fire.

On a fire, skip the dispatch, record `workpad.py update $ISSUE_NUMBER --note "Phase 1.6 reuse gate: fired (resume-kind <kind> + recorded clean audit matches the live inputs); skipping the issue-claim-auditor dispatch and adopting the recorded audit"`, and continue to Phase 2 with an adopted audit whose actionable set is empty (no `AUDIT_HANDOFF_PATH` exists). On a no-fire whose cause is an unestablished check (exit 2, refusal, or no output), record a best-effort `--note` naming the failed check so an operator can tell an unestablished state from a decided no-fire; that note never changes the decision.

Dispatch `prflow:issue-claim-auditor` serially after branch preparation completes, with `run_in_background: false`, no worktree isolation, and no context fork. The worker dispatches nothing and owns the complete claim-check procedure, fresh-tree rules, external-fact rechecks, non-terminal workpad records, record validation, and audit artifacts. Do not read its role/procedure or transcript here, and do not paste issue/workpad bodies, handoff arrays, raw history, or tool output into the dispatch or return.

Pass literal `ISSUE_NUMBER`, a fresh `DISPATCH_ID`, `WORKPAD`, `SCRIPTS`, `SKILL_DIR`, `REPO_ROOT`, the validated `RUN_SCRATCH`, `ISSUE_BODY_PATH`, `RESOLVED_AC_PATH`, `INTAKE_HANDOFF_PATH`, `BASE`, `FRESHNESS`, `TIER`, `DEVFLOW_APP_ID`, issue title/labels, and `VERSIONING_POLICY`. The three content operands are paths to exact authoritative artifacts on every scratch arm; the worker never re-fetches the issue or receives an inline copy.

Collect the completed return through the runner's result channel. The only normal return is `ISSUE-CLAIM-AUDIT HANDOFF`, `outcome`, `handoff_path`, and `dispatch_id`. Read the named JSON file once. Require its path to be the exact `RUN_SCRATCH/issue-claim-audit-handoff-$ISSUE_NUMBER.json` without escaping the checkout; `schema_version: 1`; exact dispatch identity, issue, repository, base, and freshness; well-typed outcome/routing arrays; run-owned record/projection paths; all seven pass dispositions; and observed record/projection validation. For `proceed`, both validations and the non-terminal workpad write must be established successful, the projection must be `represented` with an empty unmatched array, and no unresolved blocker may remain. A stale, malformed, mismatched, unreadable, or path-escaping handoff is unusable.

Retain the exact resolved AC artifact plus every actionable prior decision, correction, superseding assumption, external-fact result, deferred workflow criterion, wrongly excluded surface, and unresolved blocker with its evidence reference. These compact handoff fields cross into Phase 2 without loading the full audit record into this context.

Route only on the validated handoff:

- `proceed` continues to Phase 2.
- `blocked-specification` records `Blocked` naming every exact unmatched Desired Behavior statement, emits 👎, and stops without synthesizing an AC.
- `blocked-policy` records `Blocked` with `blocked_reason` verbatim, emits 👎, and stops.
- `blocked-capability` records `Blocked` with `issue-claim audit (execution-capability): every in-scope acceptance criterion requires editing .github/workflows/`, naming the credential boundary, emits 👎, and stops without a PR.
- `error`, a failed dispatch, or an unusable handoff records `Blocked` with a `dropped-failed` reflection naming the worker or validation boundary, emits 👎, and stops. **No inline audit fallback:** never load or replay the worker procedure in the orchestrator.

The `error`, failed-dispatch and unusable-handoff arms complete no auditor write, so their `Blocked` write additionally carries `--record-audit-inputs not-reusable`, stripping any stale clean row so a later resume cannot adopt it. The `blocked-specification`, `blocked-policy` and `blocked-capability` arms need no such addition — the auditor already wrote `not-reusable` on those completing arms.

On `NOT_IGNORED`, remove the retained intake handoff and any `RUN_SCRATCH/audit-versioning-policy-$ISSUE_NUMBER.md` on every arm here, a gate fire and a failed dispatch included, and after the validated audit handoff has been read remove only its audit record and projection files at their validated exact paths. On `proceed`, retain the compact audit handoff and resolved-AC artifact until Phase 2's planning consumers have read them, and retain the intake-owned issue-body artifact through Phase 4's by-path child handoffs; on a terminal audit outcome, remove those three validated files now. The orchestrator already removed the intake workpad file. Retain all artifacts on `IGNORED` until the existing successful-terminal cleanup.

<!-- prflow:implement-ref phase=1 file=skills/implement/phases/phase-1-setup.md end -->

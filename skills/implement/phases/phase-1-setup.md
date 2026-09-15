<!-- prflow:implement-ref phase=1 file=skills/implement/phases/phase-1-setup.md start -->
## Phase 1: Setup

Output: `Phase 1/4: Setup — creating the workpad and branch...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

Ordering matters in Phase 1. The resume reset (1.0) runs first; then fetch the issue (1.1) and parse its acceptance criteria (1.2); then initialize-or-load the workpad (1.3) and populate its Acceptance Criteria; then create the branch (1.4) and immediately fill the workpad's `Branch` line. The workpad must exist before the branch.

### 1.0–1.3.5 Isolated issue intake

The `prflow:implement-intake` worker owns the existing resume reset, issue/comment intake, issue-body cache, AC extraction and classification, workpad hydration, and declared-dependency preflight. It loads `<skill-dir>/references/phase-1-intake.md` itself. **Do not read that reference or the worker's transcript in this context, and do not paste the issue, comment history, workpad body, or procedure into its dispatch.** The worker reads those authoritative sources directly and returns a durable handoff. The orchestrator routes serially through branch preparation and issue-claim audit, validates their handoffs, and retains terminal decisions; no setup worker dispatches another agent.

**Pre-branch dispatch barrier — verify, never commit.** Before the worker's first mutation, run `git status --porcelain --untracked-files=no` and read its exit status from the tool result. Only an observed successful empty result permits dispatch. A dirty tree, refused read, non-zero exit, or unobserved result stops before intake; report the rows or unestablished tree state and the remedy (commit or stash the existing work, then re-trigger). Do not commit, reset, stash, create a workpad merely to report this failure, or dispatch a worker on it. No feature branch has been established yet.

Dispatch with the Agent tool, `subagent_type: prflow:implement-intake`, `run_in_background: false`, no worktree isolation, and **no context-fork/full-history option**. A named worker receives its own procedure and the explicit operands below; do not rely on conversation inheritance to deliver policy. Use the dispatch barrier/collection rule in §1.4: wait for the completed return through the runner's result channel, never treat a launch acknowledgment as a result. No other agent or orchestrator workpad writer runs concurrently with intake.

Pass literals:

- `ISSUE_NUMBER` / `ARGUMENTS` — the invoked issue number.
- `REPO_ROOT` — this checkout's `git rev-parse --show-toplevel` result; `SKILL_DIR` — the resolved `<skill-dir>`; `WORKPAD`, its invocation-ladder rungs, and `SCRIPTS` — the tier-appropriate helper forms from the root (vendored literal first on cloud, never an interpreter-leading cloud command).
- `TIER`, `DEVFLOW_APP_ID`, and the run-facts `run id`/`run attempt` literals, including `unestablished` when absent; the current user instruction/authorization relevant to intake, including whether a previous Blocked pause was explicitly cleared. Never infer that clearance merely from an automated re-trigger.
- `DISPATCH_ID` — a fresh unique opaque identifier for this intake dispatch, including on a local run; retain it for result validation. `run_id` / `run_attempt` — literal dispatch fields from the run facts, or `unestablished`; never shell variables or a guessed local Actions run.
- `IMPLEMENT_EXTENSION_LOAD` — the root's observed load state (`observed-content`, `observed-empty`, or `unestablished`), observed digest from this phase-entry check when available, exact load-failure/pending notes, and the trusted `DEVFLOW_PROMPT_EXTENSION_ROOT` value when set. The worker loads the full extension itself through the same sanctioned loader ladder/root and reports its digest; when both digests were observed they must match. Do not paste the full extension into the dispatch: that would add it again to the parent's tool-call context. A worker load cannot establish what the parent did not observe. Pass any pending phase-reference read note for delivery after §1.3 too.

The normal completed return is only `INTAKE HANDOFF`, `outcome`, `handoff_path`, and `dispatch_id`. Read the named JSON file once; this compact record, not the full conversation or a tool-output archive, is the return channel. If an early stop could not establish writable scratch, the worker returns only those identity fields, `handoff_path: null`, and a concise `blocked_reason`; this is a stop, never proceed.

#### Validate and route the intake handoff

The expected handoff is `<run-scratch>/intake-handoff-$ARGUMENTS.json`; `<run-scratch>` must be this checkout's `.prflow/tmp/implement/$ARGUMENTS` on `IGNORED`, or flat `.prflow/tmp` on `NOT_IGNORED`. Reject a path outside those exact homes or one whose resolution escapes the checkout (including through a symlink). The JSON must have `schema_version: 1`, the exact dispatched issue number, `dispatch_id`, `repo_root`, `run_id`, and `run_attempt`, and this consumer field set:

- `issue`: `title`, `labels` (array), `classification` (`bug-report`/`non-bug`), and `classification_rationale`.
- `scratch`: `arm`, `scratch_dir`, `run_scratch`, `issue_body_path`, and `resolved_ac_path`; `workpad`: `id`, `observed_status`, `snapshot_path`, `handoff_provenance`, `resume_kind`, and the `snapshot` export receipt `{result, cause, comment_id, updated_at, bytes, sha256}`; `phase2_resume`: `resume_kind`, ordered `plan_rows`, and boolean `code_sweeps_complete`.
- `outcome`, `blocked_reason`, `question`, `completed_steps` (the six step IDs below), and `dependency` with observed `result` and `held_note`.
- `extension`: `parent_state`, `worker_state`, `parent_digest`, `worker_digest`, `trusted_root`, and `pending_notes`; `prior_decisions`, `corrections`, and `blockers` arrays of `{action, source, authority, evidence}`; and a `warnings` array. Check parent identity/load observations against what you dispatched, including the trusted root and digests when observed. Do not read the worker's role/procedure to validate these fields.

A stale file, malformed/missing field, unreadable referenced required artifact, or disagreement with the returned identity/outcome is unusable. Check the concise record's contents; never infer successful work from a filename.

- `outcome: proceed` requires `completed_steps` to map each of `1.0`, `1.1`, `1.1.5`, `1.2`, `1.3`, `1.3.5` to `complete`, except `best-effort-warning` is allowed for `1.0` and `not-applicable` for `1.1.5` only on `NOT_IGNORED`; dependency result `PROCEED`; non-empty issue-body and exact resolved-AC files (the existing absent-section sentinel is valid); a current workpad ID/status and a verified snapshot — `snapshot.result == exported`, a non-null `snapshot_path`, `snapshot.comment_id == workpad.id`, and non-null `snapshot.bytes`/`snapshot.sha256` (an absent, malformed, incomplete, or issue/comment-mismatched receipt is an unusable handoff, never `proceed`); a well-typed `phase2_resume` derived from that snapshot; and no unresolved blocking decision. The reset's original best-effort warning is represented, not laundered into reset success. Read live workpad status with the helper before advancing; an unestablished/disappeared/mismatched workpad uses the root's existing failure routing, never a second create.
- Carry the title, labels, classification, `handoff_provenance` (`HANDOFF`), `resume_kind`, scratch/cache state, authoritative paths, held dependency note, and every actionable prior decision/correction — including any review-evidence obligation intake retained — into later phases and the remaining-work report. Pass the workpad snapshot **path**, not its body, to branch setup, reopening no raw comment history or worker transcript to do so. An actionable item has its actual instruction or correction and a source reference; a path alone is not a replacement for a decision. `outcome: proceed` permits setup to continue; it never certifies review or final verification complete — a retained obligation still reaches its normal phase.
- `outcome: needs-confirmation` returns the exact pending question and prior Blocked reflections to this orchestrator. On the local tier ask the user and pause here; on the cloud tier stop at Blocked naming the unresolved human decision. An automatic re-trigger never answers it. Only after explicit confirmation may a new intake dispatch proceed, with that confirmation as an operand; do not silently turn the stopped record into `proceed`.
- `outcome: blocked` / `error`, a failed dispatch, or an unusable handoff → no branch operation and no Phase 2. A returned extension-incompletion stop is retained as a blocker, never auto-re-dispatched to reset the worker's retry limit. Record Blocked and the cause through the reachable canonical workpad helper, without creating another workpad; when a workpad cannot be established, report the stop and recording failure directly. Complete the root's terminal reaction/cache-cleanup ritual when applicable, including the narrow intake-file cleanup below for validated owned paths on `NOT_IGNORED`. **No inline intake fallback:** do not load the worker procedure or transcript to salvage a failed isolation boundary.

The handoff indexes requirements; it never replaces them. The exact AC and issue-body artifact paths remain authoritative for the issue-claim auditor and later discovery. On `NOT_IGNORED`, the body path names intake's transient run-owned snapshot rather than the disabled cross-phase cache. Keep setup execution details, raw comments, old workpad history, and worker deliberation out of this context.

### 1.4 Create or Detect Feature Branch

#### Dispatch the branch-setup agent

The deterministic resume, reuse/create, freshness, and Verdict-B procedure is owned by `preflight.py branch-setup`. A thin `prflow:branch-setup` agent invokes it once, writes its result to the workpad once, and returns the same record for routing here.

**Verify the tree clean before dispatching — never commit here; no feature branch exists yet, so a commit would land on the base branch.** Read `git status --porcelain --untracked-files=no`. Empty output proceeds to the dispatch. On non-empty output — or a status read the tier refuses or that exits non-zero, naming the tree state unestablished — set the workpad `Blocked` with a `blocked` reflection listing the rows and the remedy (commit or stash them, then re-trigger), emit the 👎 outcome reaction and stop; read the exit status from the tool result, never a `$?` fence. A resumed local run already on the issue's branch takes this arm too.

Use the intake handoff's workpad snapshot as `WORKPAD_FILE`; do not load or inline its body here. Before dispatch, use the Write tool to place the issue title in a UTF-8 `TITLE_FILE` under `<run-scratch>`. Pass the agent literal values for `ISSUE_NUMBER`, `WORKPAD` (including its ordered fallback ladder), `SCRIPTS`, `WORKPAD_FILE`, `TITLE_FILE`, `HANDOFF`, `RUN_SCRATCH`, and the run id and repository coordinates for context. Pass `BRANCH` only when a consumer prompt extension supplied an exact branch; otherwise omit it. The agent derives the base once with `config-get.sh .base_branch main` and invokes:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/preflight.py branch-setup --issue <issue> --base <base> --workpad-file <workpad-file> --handoff <handoff> --title-file <title-file>
```

The optional consumer branch adds `--branch <branch>` to that same call. Use the Agent tool with `subagent_type: prflow:branch-setup`, `run_in_background: false`, and no worktree isolation. The completed return, not a launch acknowledgment, discharges the dispatch.

Dispatch barrier. Every subagent dispatch here is bound by the dispatch-collection requirement in this run's injected engine-ground-truth block — read it there (with no such block, collect every dispatch before the turn ends). Local arm (no such block): a run whose runner backgrounds the dispatch despite `run_in_background: false` collects the completed return through the runner's own result channel before routing on it. A backgrounded dispatch is not failed until the collected return reports failure/no usable record or the subagent terminally ends without a return.

After it returns, confirm the landed branch from disk yourself — re-read `git branch --show-current` rather than trusting the returned `branch` field alone. Parse the shell-token `branch-setup` record and require `outcome`, `stop_kind`, `arm`, `base`, `branch`, `freshness`, and `verdict_b`; carry optional `selected_pr`, `worktree_path`, `payload_file`, `query_state`, and `reason` when present. On the `NOT_IGNORED` arm only, after the completed branch agent has consumed the snapshot, remove the exact intake-owned `intake-workpad-$ISSUE_NUMBER.md` and `intake-handoff-$ISSUE_NUMBER.json` paths from the validated handoff; retain the actionable handoff and authoritative AC path in context. Never remove other scratch or user files. On a terminal intake/branch stop, remove these same two owned paths after reading/reporting their evidence, except a local `needs-confirmation` pause retains them until explicit confirmation and redispatch or cancellation. The `IGNORED` arm retains both durable files until the existing successful-terminal per-issue cleanup.

Route on the returned `BRANCH-SETUP RECORD`:

- `outcome=stop` → the agent already set the workpad to `Blocked`. Emit the 👎 outcome reaction and stop without invoking the checkpoint or push.
- `outcome=proceed` → carry `base` and `freshness` into later phases. Require the disk-read branch to equal the record's `branch`; on `fresh-create`, also require it to be non-empty and different from `base`. A failed check is a terminal `Blocked` stop before any checkpoint or push.

If the branch-setup dispatch fails or returns no usable record, set the workpad `Blocked` with a `dropped-failed` reflection naming the failed worker boundary, emit 👎, and stop. Do not load or replay the agent procedure inline; a worker failure cannot silently collapse the isolation boundary.

#### 1.4.1 Base-branch update checkpoint 1 (every §1.4 arm)

Immediately before invoking this checkpoint, Read `<skill-dir>/references/base-update-checkpoint.md` and validate its shared-reference markers under the root contract. Apply that common outcome contract as implement-driven checkpoint 1. Do not gate the call on recorded behind-by; the helper derives it internally. `$BASE` is the validated branch-setup record's base.

#### Base-branch update checkpoint 1 — invocation (the last thing §1.4 does, on every arm)

Bring the branch up to date with the base by invoking the shared checkpoint helper, after the branch-setup agent returned `proceed` and confirmed the branch on disk. It runs on every §1.4 arm.

`scripts/update-branch-checkpoint.sh` reads no arm operand: it resolves the base from `.prflow/config.json` (via `config-get.sh`) and the branch from `HEAD`.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Route the printed token per the §1.4.1 contract above, with one call-site-specific override:

- `CONFLICT` at this call site routes to `Blocked` as needs-human-reconciliation on every arm — it does not take §1.4.1's resolve-then-suite-then-commit bullet, whose premise is that you hold full context of your own changes, which a resumed run does not. Abort the merge first — `git merge --abort` — so the branch is left exactly as the run found it; an abandoned `MERGE_HEAD` would make the *next* run's checkpoint 1 emit `MERGE_IN_PROGRESS` and re-Block. Then record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 1.4 checkpoint 1: base merge conflicted; this call site routes CONFLICT to needs-human-reconciliation on every arm because the landed-resume arm cannot be distinguished here. The merge was aborted, so the branch is unchanged — merge the base into this branch and push, then re-trigger (on the cloud tier the run's working tree is ephemeral, so resolve it locally rather than on the runner)"`, emit the 👎 outcome reaction, and stop.

Every other token is handled exactly as §1.4.1 states, including the `PUSH_REJECTED` failed-restore hard stop.

When the invocation reports no token at all. Both route to degraded-continue here:

- The tier refused to run the invocation — a local-tier classifier denial message, an rc 127, or a silent cloud matcher denial. The checkpoint never ran, so there is no token to route: record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 1.4 checkpoint 1: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — the branch was not reconciled with the base this run; the read-target and cross-pass-coherence rules stay in force"` and continue — a refused checkpoint-helper invocation must not end the run.
- The invocation ran but no line's leading word is in the helper's token set — the observable discriminator. Treat it exactly as `UNVERIFIED`: record the degraded reflection and continue with the tree unvouched.

Cloud-emission discipline — invoke this checkpoint helper as the repo-relative vendored-literal leading token, per SKILL.md's *Cloud command-shape discipline*.

### 1.5 Push Branch

```bash
git push -u origin HEAD
```

If the push exits non-zero or the tier refuses it, set the workpad `Blocked` with a `blocked` reflection quoting the push stderr (or naming the refusal) and stating the branch was not pushed, emit the 👎 outcome reaction, and stop — read the exit status from the tool result, never a `$?` fence. Phase 1 runs no `git pull` and no rebase on any arm, and this arm takes precedence over the root's generic push-conflict rule for this push; when §1.4.1 recorded a `PUSH_REJECTED` note this run, the reflection also quotes that checkpoint breadcrumb.

Then tick the Setup phase in the workpad's `## Progress` checklist, combined as the single §1.5 orchestrator write with the held §1.3.5 dependency-preflight note and, when §1.4.1 checkpoint 1 emitted `UPDATED`, the held checkpoint-1 note:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --tick-progress "workpad" \
    --note "<the held §1.3.5 dependency-preflight-passed note>" \
    --note "checkpoint 1: merged origin/$BASE and pushed (was behind by <n>)"
```
On an arm where §1.4.1 checkpoint 1 did not emit `UPDATED`, the checkpoint-1 `--note` is simply absent from this call.

Tier-refusal arm. When the tick invocation is refused outright by the tier — a local-tier classifier denial message, an rc 127, or a silent cloud matcher denial (no exit code from the helper at all) — record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 1.5: the Setup tick was refused by this tier — a denial or rc 127 — so the ## Progress Setup row stayed unticked this run"` and continue; a refused Setup-tick invocation must not end the run. That record runs through the same helper the tier just refused, so when it is refused too — an rc 127 or a head-level denial refuses both — state the unticked row and both refusals in the run's own final report instead. A tick that *ran* and exited non-zero is not this arm — it stays governed by SKILL.md's existing re-resolve-or-Blocked contract.

### 1.6 Issue-Claim Audit

Dispatch `prflow:issue-claim-auditor` serially after branch preparation completes, with `run_in_background: false`, no worktree isolation, and no context fork. The worker dispatches nothing and owns the complete claim-check procedure, fresh-tree rules, external-fact rechecks, non-terminal workpad records, record validation, and audit artifacts. Do not read its role/procedure or transcript here, and do not paste issue/workpad bodies, raw history, or tool output into the dispatch or return.

Pass literal `ISSUE_NUMBER`, a fresh `DISPATCH_ID`, `WORKPAD` plus its rung order, `SCRIPTS`, `REPO_ROOT`, the validated `RUN_SCRATCH`, `ISSUE_BODY_PATH`, `RESOLVED_AC_PATH`, `BASE`, `FRESHNESS`, `TIER`, `DEVFLOW_APP_ID`, issue title/labels, `VERSIONING_POLICY`, and the intake handoff's complete prior-decision, correction, and unresolved-blocker arrays with their evidence references. Both content operands are paths to exact authoritative artifacts on every scratch arm; the worker never re-fetches the issue or receives an inline copy.

Collect the completed return through the runner's result channel. The only normal return is `ISSUE-CLAIM-AUDIT HANDOFF`, `outcome`, `handoff_path`, and `dispatch_id`. Read the named JSON file once. Require its path to be the exact `RUN_SCRATCH/issue-claim-audit-handoff-$ISSUE_NUMBER.json` without escaping the checkout; `schema_version: 1`; exact dispatch identity, issue, repository, base, and freshness; well-typed outcome/routing arrays; run-owned record/projection paths; all seven pass dispositions; and observed record/projection validation. For `proceed`, both validations and the non-terminal workpad write must be established successful, the projection must be `represented` with an empty unmatched array, and no unresolved blocker may remain. A stale, malformed, mismatched, unreadable, or path-escaping handoff is unusable.

Retain the exact resolved AC artifact plus every actionable prior decision, correction, superseding assumption, external-fact result, deferred workflow criterion, wrongly excluded surface, and unresolved blocker with its evidence reference. These compact handoff fields cross into Phase 2 without loading the full audit record into this context.

Route only on the validated handoff:

- `proceed` continues to Phase 2.
- `blocked-specification` records `Blocked` naming every exact unmatched Desired Behavior statement, emits 👎, and stops without synthesizing an AC.
- `blocked-policy` records `Blocked` with `blocked_reason` verbatim, emits 👎, and stops.
- `blocked-capability` records `Blocked` with `issue-claim audit (execution-capability): every in-scope acceptance criterion requires editing .github/workflows/`, naming the credential boundary, emits 👎, and stops without a PR.
- `error`, a failed dispatch, or an unusable handoff records `Blocked` with a `dropped-failed` reflection naming the worker or validation boundary, emits 👎, and stops. **No inline audit fallback:** never load or replay the worker procedure in the orchestrator.

On `NOT_IGNORED`, after the validated audit handoff has been read, remove only its audit record and projection files at their validated exact paths. On `proceed`, retain the compact audit handoff and resolved-AC artifact until Phase 2's planning consumers have read them, and retain the intake-owned issue-body artifact through Phase 4's by-path child handoffs; on a terminal audit outcome, remove those three validated files now. The orchestrator already removed the intake workpad/handoff files after branch setup consumed them. Retain all artifacts on `IGNORED` until the existing successful-terminal cleanup.

<!-- prflow:implement-ref phase=1 file=skills/implement/phases/phase-1-setup.md end -->

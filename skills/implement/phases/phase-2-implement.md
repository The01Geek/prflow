<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-implement.md start -->
<!-- prflow:implement-set phase=2 part=1 of=3 -->

## Phase 2: Discover, Plan & Implement

Output: `Phase 2/4: Discover, Plan & Implement...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

Configuration. This phase reads the internal-documentation root from the `.docs.internal` key of `.prflow/config.json`, resolved through `config-get.sh` in §2.1's exploration-map step below. Bind that resolved value to `[[INTERNAL_DOC_LOCATION]]` and use the placeholder wherever this file names the configured internal-docs root.

Update the workpad: `workpad.py update $ISSUE_NUMBER --status Discovering --note "Entered Phase 2"`.

### 2.0 Resume-idempotency gate (runs BEFORE §2.1)

A stalled cloud run that `prflow_implement.stall_backstop` auto-resumes re-enters Phase 1, adopts the branch/PR (§1.4), hydrates the workpad, then walks linearly into this phase. The Phase 2 subagents produce ephemeral, read-only, in-context output and the restored §2.1/§2.2 procedure carries no dispatch-idempotency directive, so without this gate a resumed run re-runs the full discovery/architecture pass over work a prior attempt already committed — wasted budget, and divergence risk if the re-plan drifts from shipped work.

Read the durable inputs from the Phase 1 intake reader's printed `phase2_resume` field and the Phase 1 audit reader's printed output — both already resident from Phase 1; read no handoff file here to obtain them. Intake derived the resume object from the exact live workpad snapshot and preserved `resume_kind`, every ordered `## Plan` checkbox row, and the boolean `code_sweeps_complete`. Read those compact fields once; the orchestrator carries them, not raw setup history, audit procedure, or the full workpad body, across this boundary. Before deciding, re-read only the live workpad Status with `workpad.py status $ISSUE_NUMBER` and require the same current issue/workpad identity already validated in Phase 1. This compact check preserves current-state fail-closed behavior without reloading comments, reflections, or setup notes.

The read fails closed. A refused/no-output/non-zero Status read, a missing or mismatched handoff identity, an absent or duplicated `phase2_resume` object, **no audit reader output held and no recorded §1.6 adoption** (an adopted audit legitimately has no handoff — its empty actionable set stands in, and satisfies the reference's conjunct (c)), a non-array/empty `plan_rows`, a non-boolean `code_sweeps_complete`, or a `resume_kind` outside `in-flight` / `terminal-re-trigger` / null routes to the gate-does-not-fire path so full §2.1/§2.2 discovery runs. An absent handoff with no recorded adoption still fails closed. Record a `--note` naming the failed compact-state check, so an operator can distinguish unestablished state from a decided no-fire:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 2 §2.0: compact resume state unusable ({which check failed}); gate not fired, running full §2.1/§2.2 discovery"
```

The note is best-effort and never changes the decision: on the very path where the workpad is unreadable it may itself fail, and a failed note still leaves the gate un-fired with full discovery running.

Load trigger. When `phase2_resume.resume_kind` equals the bare token `in-flight` or `terminal-re-trigger`, read this gate's reference. That value is resident before Phase 2 starts, so decide the load before this phase's entry `workpad.py update --status Discovering` call and issue the read in that call's turn, costing no round trip. A run whose reference loads reads the §2.2.6 reference in that same turn too: a fired gate skips the §2.2.4 plan write yet still runs §2.2.6.

**Procedure:** `<skill-dir>/references/phase-2-0-resume-gate.md`, read by the gated load protocol in phase-2-sweeps-contract.md. It carries the gate's three conjuncts, its skip and onward routing, and the resumed-run criterion re-derivation.

No fire → full discovery. A null `resume_kind`, a value outside that pair, or a compact state that never established routes here: follow no reference and run the full §2.1 discovery / §2.2 architecture pass below unchanged. So does a fresh run, and — after the reference's conjunct tests — a run that died mid-§2.1 before §2.2.4's `--replace-plan-file`, a terminal re-trigger whose plan inputs do not match, or a Plan that does not represent the compact decision/correction context.

### 2.0.5 Durability checkpoints (mandatory — bound mid-Phase-2 work loss to ~10 minutes)

Take a durability checkpoint at each Phase 2 sub-step boundary you cross before §2.5 — after §2.1 discovery, after §2.1.5, after §2.2 planning, and after §2.4 — and, because §2.3 routinely runs longer than that window on its own, additionally at each §2.3.x sweep boundary (a §2.3.x checkpoint removes nothing from a later sweep's operand — the §2.3 preamble covers why). The ~10-minute window is a design target that sizes *where* checkpoints go, not a wall-clock assertion; a boundary reached in seconds needs no distinct checkpoint (an empty checkpoint is a no-op, never a requirement). The §2.1/§2.1.5/§2.2 boundaries usually stage nothing, so durable work begins at §2.3.

Every checkpoint — and §2.5's own final commit — goes through the bundled helper. Invoke it as the command's leading token (per the *Cloud helper-invocation form* in `SKILL.md`), naming the files you produced since the previous checkpoint:

```bash
.prflow/vendor/prflow/scripts/phase2-durability-checkpoint.sh "feat: implement issue #$ARGUMENTS — {short description} (checkpoint)" {path} {path...}
```

- Explicit paths only. Name the files you produced since the last checkpoint — including the old path of any rename and each deleted path — and the helper stages exactly those (`git add -- …`), refusing `git add -A`/`git add .`/intent-to-add; when you name only a rename's new path the helper pairs the old path into the commit, and it reports on stderr any tracked deletion you left uncommitted. §2.5 goes through this same helper and is therefore explicitly scoped too — it is the run's *comprehensive-enumeration* point, not a sweep: a path you touch but never name at an earlier checkpoint stays non-durable until you name it there, and a path you never name at any checkpoint including §2.5 is never committed at all (the disclosed residual the Phase 4.3 clean-tree backstop surfaces) — a disclosed limit, not a defect.
- **Proof edits never enter history.** **Never checkpoint while an unreverted §2.1.5 temporary proof edit is in the working tree** — revert proof edits first, or simply never *name* a proof file. The helper rewrites no pushed history (no amend, no rebase, no force-push), so proof content kept out by ordering never has to be removed later.
- The helper owns the §2.5 workflow-edit guard's detect-and-do-not-stage half. On a cloud run whose `DEVFLOW_APP_ID` is empty (the `GITHUB_TOKEN` fallback) it will not stage a repo-own `.github/workflows/` path named in the relative `.github/workflows/…` spelling, so an earlier checkpoint cannot commit a workflow file the fallback credential cannot push. The match is spelling-only (the helper's own disclosed limit): an absolute path, a `../`-reaching form, and the bare directory `.github/workflows` with no trailing slash are not matched. §2.5 owns the guard's other half — the revert-and-route: the coupled-file enumeration and the 2.2.5 scope-adjustment routing stay your responsibility there, and because the helper never reverts the workflow file, an unreverted one still sits in the tree for the Phase 4.3 clean-tree backstop.
- A checkpoint that does not land is not success. The helper treats the push as landed only when `git rev-parse HEAD` equals `git rev-parse @{u}` after pushing (mirroring `skills/implement/references/doc-deliverable-self-heal.md` step 4), and exits non-zero when they differ — a rejected non-fast-forward is one example that leaves them unequal. Push output such as `Everything up-to-date` is not itself decisive; it is exit 3 only when the comparison still shows that the checkpoint commit did not reach the tracked branch. On a non-zero exit, resolve it (rebase/re-push, or defer a workflow edit) before continuing; a still-local commit is not durable.
- Idempotent. A checkpoint with nothing new makes no commit, so a resumed run adopting the branch sees the prior content exactly once. Exit 0 always means the same thing — the work up to this boundary is on the remote. A no-op boundary earns that 0 only after the helper reconfirms `HEAD` equals `@{u}`; a branch tip that never landed (an earlier push that silently failed) exits 3 instead, so a run cannot be told "durable" by a chain of no-ops sitting on unpushed work.

Workpad boundary delivery. After each boundary's checkpoint push lands, one combined `workpad.py update $ISSUE_NUMBER` delivers every accruable mutation since the previous delivery — a mutation accrues only when no consumer reads its timing; one you cannot so classify is delivered immediately.

Immediate (existing call sites): every `--reflection`/`--reflection-kind`, `--record-*`, `--checkpoint`, terminal `--status` (`Blocked` included), and `--expect-*`-guarded call, plus the criterion-route ledger, test-first, sweep-selection, §2.2.7 coupled-site-map, and `§2.3 operand ledger:` notes. Accruing: per-step `--tick-plan` ticks, the §2.2 `--status Planning`/§2.3 `--status Implementing` flips (folded onto the boundary call after each former site — safe: `scripts/workpad.py` maps `Discovering`/`Planning`/`Implementing` to one Progress phase), and post-hoc evidence notes (sweep results). Derive `--tick-plan` from durable state, not memory: re-read `## Plan` and tick steps whose work the just-checkpointed commits contain (the §2.0 re-verification), so compaction loses no tick; an accrued note so lost is accepted like crash loss. An empty-no-op boundary delivers nothing and carries accruals forward; §2.5 always delivers. Read the outcome line and act on its remedy — an unresolved tick keeps the retick path.

Cloud-emission discipline. Invoke the helper as the repo-relative vendored literal leading token — never `bash <path>`, never a `VAR=value` prefix, never a leading `cd` (see `SKILL.md`'s *Cloud command-shape discipline*). Substitute `$ARGUMENTS`/the paths as literals when you emit the command.

### 2.1 Discovery

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway); it is deliberately not restated here.

Use the Agent tool with `subagent_type: prflow:code-explorer` and `run_in_background: false` to explore the codebase and understand the system as it relates to the issue.

Read `ISSUE_BODY_PATH` and `RESOLVED_AC_PATH` from the validated intake handoff once at this entry. These are the exact requirement artifacts the intake and audit workers consumed; load them instead of the setup workpad snapshot or its historical notes. A missing, unreadable, empty, or path-mismatched artifact is unestablished requirements and routes to Blocked, never an inferred empty issue.

The issue body is a starting point, not the source of truth. Treat its problem framing, any stated root cause, and its Technical Context as a strong lead to *verify* — never fact to implement on faith. The explorer (and the architect in Path B) confirm the issue's claims against the actual code; where a descriptive claim (current behavior, the stated root cause) diverges from the code, the code wins — but the code wins over a descriptive claim only when the code being read is verified fresh (see the Fresh-tree verification rules below). Subject to that freshness qualifier: surface the divergence in the workpad and plan from what the code shows, rather than implementing a claim the code contradicts.

Fresh-tree verification rules (coupled mirror of the Phase 1 issue-claim-auditor worker — same rules, stated at both sites; do not paraphrase one from the other). When an adopted branch was freshness-checked in Phase 1.4, its verification reads obey the two rules `agents/issue-claim-auditor.md` states verbatim:

- Read-target rule. When the adopted branch is behind `origin/$BASE` (`$BASE` is the base from the branch-setup record's `base:` line) — unconditionally when Phase 1.4 marked freshness unverified, and equally when no freshness record is present — a code-wins read that adjudicates a shipped-work claim targets `origin/$BASE` state, never the unfetched fork point. The working branch is reconciled at the Phase 1.4 update-branch checkpoint; this read-target rule remains in force whenever that checkpoint is neither `UPDATED` nor `UP_TO_DATE`.
- Cross-pass coherence rule. Before any "shipped/landed in PR #N" claim is REFUTED from tree reads, resolve PR #N's merge state and `merge_commit_sha` (the SHA is the response's `.mergeCommit.oid`) with a read-only `gh pr view N --json state,mergeCommit`; when the PR is MERGED and `git merge-base --is-ancestor <merge_commit_sha> HEAD` reports the merge commit is not an ancestor of the current checkout, the verdict is "checkout stale — refresh and re-verify", never "code wins". Every indeterminate outcome (a shallow history where the ancestor check errors, a failed `gh pr view`) takes the same stale-suspect verdict — a refutation requires a positively-fresh tree.

Know the one specification channel. The issue's *narrative* — Problem Statement, Current Behavior, User Impact, Technical Context, and the Implementation Notes prose (including its `Documentation Needed` bullet) — is a non-authoritative starting point to verify, not a mandate. Desired Behavior is authoritative intent; Acceptance Criteria are its exhaustive, merge-gated projection. Phase 1 must stop for author refinement when an independently verifiable Desired Behavior obligation is not represented in that projection. Once Phase 1 passes, implement and review use the resolved Acceptance Criteria as the sole formal specification; they do not copy Desired Behavior into the workpad, infer a new criterion, or create a second checklist source. The "code wins" rule above applies to descriptive claims only — it never overrides the prescriptive intent or its criteria. "Non-authoritative" means the narrative cannot be used to narrow or suppress required work — *not* "ignore it": verify each narrative claim, but never let a wrong or contradictory narrative talk you out of work the authoritative intent and shipped diff warrant. The one exception is a `Documentation Needed` block whose first content token is exactly `none` (case-insensitive, with at most one trailing `,.;:`, or `none` standing alone) as recognized by `scripts/extract-doc-needed-paths.sh`: that standalone-`none` is the writer's up-front statement that the block names no documentation deliverables, not narrative invoked afterward to escape work the block already required, so honoring it does not breach the prohibition above.

Pick the exploration map first. Resolve the internal-docs root in the orchestrator, before composing the dispatch prompt — `code-explorer` declares no `Bash` tool, so a helper invocation embedded in its prompt is unexecutable text:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/
```

Read the printed value from the tool result, bind it to `[[INTERNAL_DOC_LOCATION]]` (the Configuration note above), and substitute it as a literal where the dispatch prompt below names it. Then scan the issue body for path mentions (`.github/workflows/`, `.claude/`, `scripts/`, `cron/`, `tools/`, etc.) or a section headed "Technical Context", "Relevant files", "Files to touch", "Files to change", or "Implementation files"; collect those paths as `PRIMARY_PATHS`. `PRIMARY_PATHS` supplements the documentation map — it never replaces it: demoting the docs to a gap-filler whenever an issue names a code path would switch the documentation-as-map step off on most issues.

Pass the following prompt:
- The GitHub issue title and labels inline (the code-explorer dispatch, on every arm)
- `ISSUE_BODY_PATH` and `RESOLVED_AC_PATH` from the validated intake handoff plus `AUDIT_HANDOFF_PATH` from the validated audit return, instructing the subagent to Read those exact artifacts with its Read tool. On a Phase 1.6 reuse-gate fire there is no `AUDIT_HANDOFF_PATH`; the adopted audit's empty actionable set stands in, so pass no audit path and apply no audit-derived items. Pass paths, never their contents. The first is the cache on `IGNORED` and intake's transient run-owned snapshot on `NOT_IGNORED`; all were read-validated before dispatch. From the audit handoff, apply every actionable prior decision/correction, superseding assumption, external-fact result, and wrongly excluded surface with its source/authority/evidence; do not treat validation metadata as a requirement.
- Explicit instruction: "Start by reading `[[INTERNAL_DOC_LOCATION]]/index.md` — the documentation root's routing map — and follow its links to the pages covering this issue's area; when no `index.md` exists, read the relevant files under `[[INTERNAL_DOC_LOCATION]]` directly. {When `PRIMARY_PATHS` is non-empty, additionally: Also read these issue-named paths first: `PRIMARY_PATHS`. Read both — the named paths and the documentation map; neither replaces the other.} Use the documentation as a map to guide your code exploration, verifying any documentation claim you rely on against the source — the code is authoritative where they disagree. Then explore the actual code guided by those findings. Return per your Output Guidance in `agents/code-explorer.md`."

Documentation updates are handled in Phase 4 by a general-purpose subagent that invokes the `prflow:docs` skill. Do not edit `.docs.internal` here; if the explorer surfaced outdated or missing docs, that signal carries forward in your context to Phase 4.1 where the subagent will act on it. This ownership is why an acceptance criterion satisfied by a `docs/…` edit is not authored here. Phase 3.3's review-and-fix loop may author it; the Phase 3.4 gate defers whatever it did not, to Phase 4.1 — the deadline and backstop, not the exclusive author (see phase-3-ac-gate.md's *Documentation-AC deferral* rule and phase-4-finalization.md §4.1's discharge step).

### 2.1.5 Reproduce-First Gate (only when the recorded classification is bug-report)

This gate fires on the **recorded content classification** from Phase 1.3 (the `classification: ` workpad note), not the `bug` label. If that classification is non-bug, skip this step entirely and continue to 2.2.

If the recorded classification is bug-report, you must capture a *reproduction signal* before planning a fix. A reproduction signal is any one of:

- a new failing test in the diff that exercises the bug,
- a quoted error log / stack trace from a real run, or
- a recorded shell command (with output) that demonstrates the failure.

Write the evidence with the **Write tool** to `<run-scratch>/repro-${ISSUE_NUMBER}.md` (ensure the `<run-scratch>` directory exists first — this is a prose directive with no fence to hold a `mkdir`), then: `workpad.py update $ISSUE_NUMBER --status Reproducing --set-reproduction-file <run-scratch>/repro-${ISSUE_NUMBER}.md --tick-progress "Reproduction captured" --note "Captured reproduction signal"`. (The helper inserts `## Reproduction` after `## Acceptance Criteria` if it doesn't yet exist.)

Temporary proof edits are allowed when they raise confidence in the reproduction (e.g. inserting a `console.log`, hardcoding a request payload, tweaking a build input). Every temporary proof edit MUST be reverted before the next durability checkpoint (§2.0.5) — at the latest, before the implementation commit in 2.5. A proof edit still present when an earlier checkpoint names its file enters pushed history that nothing later rewrites. The fact that you made a proof edit must also be recorded in the workpad's `Reproduction` section.

Phase 2.2 cannot start until the workpad's `Reproduction` section is populated. If you cannot reproduce the bug: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Cannot reproduce: {obstacle}"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop the run — do not invent a fix.

### 2.2 Assess Complexity & Plan

Accrue `--status Planning` for the next boundary delivery (§2.0.5), not its own call.

Using the explorer's findings (and the reproduction signal, for bugs), evaluate the issue complexity:

Simple issues (implement directly — skip architect):
- Single-module changes (e.g., add a field, fix a bug, update a config)
- Clear solution described in the issue body
- No architectural decisions needed

Complex issues (use architect subagent):
- Cross-module changes affecting multiple subsystems
- New features requiring design decisions
- Changes to interfaces, data models, or system architecture
- Ambiguous requirements needing breakdown into tasks

Take Path B when any Complex bullet holds. A touched-file count above five also takes Path B unless the issue enumerates those files and prescribes the same mechanical edit in each; otherwise take Path A.

#### Path A: Simple issue

Output: `Skipping architect — issue is straightforward. Implementing directly.`

Plan the implementation inline using the explorer's findings. Identify which files to create/modify and what changes to make.

#### Path B: Complex issue

Use the Agent tool with `subagent_type: prflow:code-architect` and `run_in_background: false` to design the implementation.

Pass it:
- The GitHub issue title and labels inline (the code-architect dispatch, on every arm)
- `ISSUE_BODY_PATH` and `RESOLVED_AC_PATH` from intake plus `AUDIT_HANDOFF_PATH` from the audit worker, instructing the subagent to Read all three; never paste their contents. Apply the audit handoff's actionable decisions/corrections and audit-result arrays to the blueprint with their source/authority/evidence. On a Phase 1.6 reuse-gate fire no `AUDIT_HANDOFF_PATH` exists; the adopted audit's empty actionable set stands in, so pass no audit path and apply no audit-derived items.
- The explorer's distilled findings as inline context, prefixed with: "The code-explorer analyzed the current codebase and produced the following findings:"

The architect returns a focused blueprint (files to create/modify, component designs, data flows, build sequence). Hold this blueprint in your context — do NOT commit it (it is a temporary working artifact).

Re-derive a subagent's numbers before you rely on them. This applies to explorer analysis and architect blueprint alike, on Path A and Path B.

- Scope. Independently re-derive any quantitative claim a Phase-2 subagent produced before that claim feeds a plan step, a gate, or a budget decision. A volunteered number that feeds no decision is treated as unverified, and the absence of an `(unverified estimate)` marker waives nothing for a decision-feeding claim.
- Absence. A subagent's claim of absence — no match, no duplicate, nothing found — is unestablished the same way: re-run its cited command yourself before relying on it, since a fabricated or narrowed-search absence lets a missed coupled site through.
- Channel. Re-derive through a preflight-guaranteed channel — `python3` (granted in the cloud implement profile; invoked helper-by-path on the local tier) — never an ad-hoc non-preflight PATH tool such as `wc`/`tr`/`cut`/`head`, whose host divergence is the measurement bug this obligation guards against.
- Channel exception. Where the number's downstream consumer defines its own standalone-invocable counter, that counter is the channel and takes precedence over the ad-hoc never-list. But a counter embedded inside a larger artifact (a test-suite-internal function) is not mirrored inline — the claim resolves to unverified instead.
- Unresolvable claims. A claim whose re-derivation channel is unavailable, or whose producer stated no operands and counting rule to re-derive against, resolves to unverified, never to confirmed.
- Unverified does not block. An unverified decision-feeding claim feeds the decision only with its `(unverified estimate)` marker propagated into the plan step and workpad entry that consumed it.
- Record the status. When a Phase-2 subagent quantitative claim reaches the workpad Plan, record its re-derived-or-unverified status in the workpad entry itself, so the marker survives context compaction and stall-backstop resume.

#### 2.2.4 Reuse & Altitude gate (mandatory, before the plan is written)

Two of the cleanup lenses that the Phase 3.2 cleanup pass would otherwise flag — reuse and altitude — are *design* decisions. Apply both to the plan (from either path) before you write it to the workpad:

1. Reuse. For every piece of new code the plan proposes (a helper, a parser, a validator, a state shape, an API client), grep the shared/utility modules and the files adjacent to the change for something that already does the job. If it exists, the plan reuses the existing helper by `file:line` rather than re-implementing it; new code is justified only when no existing implementation fits.

   Key the search on the job, not on the syntax you intend to write. Build the query from what the code will *do* — the endpoint it calls, the API or operation name, the shape of the data it handles, the domain noun it works on (an illustrative floor, not a closed list) — never from the tokens, flags, or idiom of the implementation you have already decided to write. A query keyed on your intended shape can only *confirm* that decision: an existing helper doing the same job in a different idiom matches none of your syntax and stays invisible, so the search returns a clean zero that means nothing.

   Disconfirmation check (a precondition on running the search). Before you run the query, test it against one question: *would this match an implementation of the same job written in a different idiom?* When it would not, the query is keyed on your syntax rather than the job — re-key it on the job and re-run. This adds no search in the ordinary case; a re-keyed re-run is required only on the units where this check fails.

   Record a zero match bounded to what you searched. A reuse search that returns nothing is recorded as bounded to the predicates you actually searched — "no candidate matched `<predicates searched>`" — never as a bare claim of absence, which would state as verified a finding the search cannot support. Carry those predicates in the same plan step that consumes the reuse result (the step naming what to reuse or build).
2. Altitude. Check that each planned change sits at the right depth, not as a fragile bandaid — a pile of special cases layered on shared infrastructure is the signal that the fix isn't deep enough, so prefer generalizing the underlying mechanism over stacking special cases. Wherever the plan reaches for a special-case patch, ask whether the shared mechanism should change instead and re-aim the plan there.

Fold the result into the plan before the plan write below — this is a planning gate, not a code edit: name the helpers to reuse (with `file:line`) in the relevant plan steps, and pick the altitude before writing the steps.

After planning (either path), write the plan steps as `- [ ]` checkboxes with the **Write tool** to `<run-scratch>/plan-${ISSUE_NUMBER}.md` (ensure the `<run-scratch>` directory exists first — a prose directive with no fence to hold a `mkdir`), then `workpad.py update $ISSUE_NUMBER --replace-plan-file <run-scratch>/plan-${ISSUE_NUMBER}.md --record-plan-inputs`. The flag binds the Plan to the live issue body for a later terminal re-trigger's §2.0 check.

On the intake `NOT_IGNORED` arm, after every planned Phase 2 consumer has completed its Read, remove only the validated transient `acs-$ISSUE_NUMBER.md` and `issue-claim-audit-handoff-$ISSUE_NUMBER.json` paths. Retain the validated `ISSUE_BODY_PATH` through Phase 4's two by-path child handoffs so neither child needs an inline body; remove it in the successful-terminal cleanup. The `IGNORED` arm keeps its cached/run artifacts for that same cleanup. Never remove a path not named and validated by the intake/audit handoffs.

#### 2.2.5 Scope-Adjustment Rule (multi-PR issues)

If discovery and planning revealed that the issue's deliverables span more than fits in a single PR (e.g., a phased cleanup, a multi-stage migration, or any issue whose acceptance criteria explicitly enumerate work for several future PRs), you must narrow the workpad's `## Acceptance Criteria` to only the items this PR will deliver before continuing to 2.3. Otherwise the Phase 3.4 gate will reject your run for criteria that are out-of-scope by design, and the run will stop without ever reaching Phase 4.

Capability-blocked ACs are a sanctioned trigger too. Beyond phased/oversized work, this rule also fires when the run-facts block reads `tier: cloud` and `DEVFLOW_APP_ID: absent` — the built-in `GITHUB_TOKEN` fallback, whose credential cannot push workflows (a `DEVFLOW_APP_ID: present` carries a workflow-capable App token and does NOT trigger this; a `local` tier and an **`unestablished`** `DEVFLOW_APP_ID` do not either) — for any acceptance criterion that requires editing the repo's own `.github/workflows/` (or a file coupled to that edit, such as a coupled test-suite pin asserting workflow content), which that `GITHUB_TOKEN` fallback cannot push. Two sources feed this trigger, and you must check both here — Phase 1.6's execution-capability pass (Pass 5) flags the ACs whose workflow-residence is visible in their own text, but that flag is *provisional*: now that planning has produced a concrete diff, re-evaluate it against what the plan will actually touch and also catch any AC whose workflow-residence surfaced only during planning (its text never named `.github/workflows/`, but the plan reveals it must edit one). Route every capability-blocked AC — flagged-by-Pass-5 or discovered here — through the steps below before Phase 2.3 writes any code (never after a rejected push): narrow to the pushable subset, and record the `GITHUB_TOKEN`-fallback workflows-scope boundary (run-facts `DEVFLOW_APP_ID: absent` — no workflow-capable App token) as the deferral reason in the `--note` so Phase 4.0's follow-up can state that landing the deferred work needs a workflows-capable (human/PAT, or App-configured cloud) push. And if Phase 2.3 code-writing *itself* later reveals a required `.github/workflows/` edit that neither Pass 5 nor this plan-time re-check caught (planning was incomplete), re-apply this scope-adjustment then, before committing — a workflow-file edit must never be committed and pushed by the bot on a run whose run-facts block reads `tier: cloud` and `DEVFLOW_APP_ID: absent` (the `GITHUB_TOKEN` fallback).

Empty pushable subset ⇒ take the Blocked path here, do not narrow-and-proceed. When narrowing would leave the pushable subset empty — *every* remaining in-scope AC is capability-blocked, whether that was already known at Phase 1.6 Pass 5 or is only discovered here (at 2.2.5 against the concrete diff) or during the 2.3 re-route — do not narrow to nothing and continue into implementation/PR creation. There is no shippable work, so take the Phase 1 Blocked path executably at this point: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Issue-claim audit (execution-capability): every in-scope acceptance criterion requires editing .github/workflows/, which this cloud run's GITHUB_TOKEN fallback (no workflow-capable App token; run-facts DEVFLOW_APP_ID: absent) cannot push — must be implemented by a workflows-capable run (a human/PAT, or a cloud run with the PRFlow App configured). Re-dispatch there; no PR opened"`, emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference), and stop the run.

Steps when scoping down:

1. Write the narrowed AC list (only in-scope checkboxes, verbatim) with the **Write tool** to `<run-scratch>/narrowed-acs-${ISSUE_NUMBER}.md` (ensure the `<run-scratch>` directory exists first — a prose directive with no fence to hold a `mkdir`).
2. Apply the change atomically:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
       --replace-acs-file <run-scratch>/narrowed-acs-${ISSUE_NUMBER}.md \
       --scope-decision-deferred <PR> "{the deferred criterion's text, verbatim}" \
       --note "Scope decision: {which subset this PR delivers}. Deferred (verbatim): {list}. Will be tracked in follow-up issue(s) filed in Phase 4.0."
   ```

Pass one `--scope-decision-deferred` per deferred criterion, in the same call as `--replace-acs-file`, so the narrowing and its machine-readable record land together; the review engine reads that record, never the free-text `--note`. `<PR>` is this run's draft PR number once §3.1 has run (a Phase 3.4 return here) — the `number` of its `pr-open` record, or the workpad `**PR:**` line when that record is no longer in context — and `pending` before §3.1, which binds only the records already written when it runs.

This is not "inventing" criteria (forbidden by 1.4) — the deferred items are preserved verbatim in the workpad notes (`--note`), which stays the human-readable record, and carried forward by Phase 4.0.

If you are unsure whether to scope down, prefer a single fully-in-scope PR. Only re-scope when the issue body itself describes phased work, the diff would otherwise exceed reasonable PR size, or Phase 1.6 Pass 5 flagged a capability-blocked AC on a cloud-tier run (the credential-boundary trigger above).

#### 2.2.6 AC-Plan reconciliation (rewrite surface details, never relax intent)

Predicate. Fires when the plan you settled on — or a later refactor in the Phase 3.2 cleanup pass or /prflow:review-and-fix (3.3) — names different identifiers (job, file path, function, command) for the *same underlying behavior* than an acceptance criterion does, leaving the literal AC text stale and Phase 3.4 rejecting a strictly-correct refactor. You may rewrite the affected AC in the workpad only if the rewritten text verifies the same observable outcome with the new identifiers; never relax what's verified. A run that rewrites no criterion reads nothing here unless its §2.0 reference loaded.

**Procedure:** `<skill-dir>/references/phase-2-2-6-ac-plan-reconciliation.md`, read by the gated load protocol in phase-2-sweeps-contract.md — issued in the same assistant turn as §2.2.4's plan write, or with the §2.0 reference on a run whose §2.0 reference loads.

If the rewrite would relax the AC (drop a guarantee, weaken a check, remove a verification surface), STOP — apply 2.2.5 (defer the AC to a follow-up issue) or revert the structural change instead.

#### 2.2.7 Pre-flight coupled-site map (before any Phase 2.3 edit)

When the plan touches a value, contract, or literal that lives in more than one place — the class the §2.3 "Sweep selection" preamble defines by *what the change replicates across sites, not whether it is code* — list those other places before you start editing, not after. The §2.3 relocation and contract-completeness sweeps make this same check *after* the edits are written.

Enumerate the sites with searches you actually run, in the granted forms and preference order the §2.3 preamble already lists, and record both the commands you ran and what they found before the first edit as **one workpad `--note` per search (or per coupled site)** — never a single large note, so each note stays within the workpad's 2,048-byte per-note budget. Do not attest a search you did not run.

A search that errors, is refused, or otherwise cannot be confirmed to have run is a gap, not evidence of no other places: record it as a gap naming that command, and build the map only from searches that observably ran — a refused search never counts as "there were no other places." Apply the §2.3 preamble's "confirm the search actually ran" rule here to tell an honest zero-match from a search that never ran.

If your project publishes a coupled-site registry — a checked-in list of which sites must change together — consult it as well; a project that publishes none is simply unconstrained by it.

<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-implement.md end -->

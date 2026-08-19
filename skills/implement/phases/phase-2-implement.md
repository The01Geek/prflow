<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-implement.md start -->
<!-- prflow:implement-set phase=2 part=1 of=3 -->

## Phase 2: Discover, Plan & Implement

Output: `Phase 2/4: Discover, Plan & Implement...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

Configuration. This phase reads the internal-documentation root from the `.docs.internal` key of `.prflow/config.json`, resolved through `config-get.sh` in the Phase 2 explicit-instruction block below. Bind that resolved value to `[[INTERNAL_DOC_LOCATION]]` and use the placeholder wherever this file names the configured internal-docs root.

Update the workpad: `workpad.py update $ISSUE_NUMBER --status Discovering --note "entered Phase 2"`.

### 2.0 Resume-idempotency gate (runs BEFORE §2.1)

A stalled cloud run that `prflow_implement.stall_backstop` auto-resumes re-enters Phase 1, adopts the branch/PR (§1.4), hydrates the workpad, then walks linearly into this phase. The Phase 2 subagents produce ephemeral, read-only, in-context output and the restored §2.1/§2.2 procedure carries no dispatch-idempotency directive, so without this gate a resumed run re-runs the full discovery/architecture pass over work a prior attempt already committed — wasted budget, and a divergence risk if the fresh re-plan drifts from already-shipped work.

Read the two durable inputs first. Both live in the workpad body; read it through the same already-granted shape §1.3/`SKILL.md` use for re-run context. Resolve the workpad comment ID first, as a single-statement helper invocation:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py id $ISSUE_NUMBER
```

Read the printed comment ID and the exit status from the tool result — as `phase-4-documentation.md` §4.0 does — never a captured shell variable and never a command substitution nesting one call inside another. Then read the body in a second single-statement invocation, substituting that comment ID as a decimal literal where `<comment-id>` appears:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py body <comment-id>
```

`workpad.py body`/`id` are `python3` (a preflight-guaranteed tool); read the printed body yourself and decide the two conjuncts from it — never derive the decisive value through a non-preflight PATH tool (`tr`/`sed`/`grep`/`wc`), which fails open to an empty value and mis-selects.

The read fails closed, and an unestablished measurement is distinguishable from a decided no-fire. The identity read's outcome is judged from the `id` tool result — a refused or no-output invocation, a non-zero exit, or an empty printed comment ID is an **unestablished** measurement, never a decided answer: route it to the gate-does-not-fire path so full §2.1/§2.2 discovery runs, and never substitute an empty or absent comment ID into the `body` call. Likewise treat any unusable body read — a failed or empty `body`, a body carrying no `## Plan` section, or a duplicated `## Plan` — as the gate does not fire: full §2.1/§2.2 discovery runs. Judge each body conjunct from the printed body itself. Record a `--note` naming the failed read, so an operator can tell an *unreadable workpad* from a *decided* no-fire:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 2 §2.0: workpad read unusable ({which read failed}); gate not fired, running full §2.1/§2.2 discovery"
```

The note is best-effort and never changes the decision: on the very path where the workpad is unreadable this write may itself fail, and a failed note still leaves the gate un-fired with full discovery running.

Fire the gate when, and only when, BOTH conjuncts hold:

- (a) `resume-kind: in-flight`. The most recent `resume-kind:` note in `## Progress` (written by Phase 1.3 at triage) reads `in-flight`. Compare by exact value, never by containment: the note's text after `resume-kind: ` must be the bare token `in-flight` with nothing else following it. A containment test would arm this conjunct on any longer string merely *including* the token — an unsubstituted template that `--note` accepts verbatim — firing the gate on the terminal re-trigger it exists to block. **Fail-closed:** an absent, unparseable, or non-`in-flight` marker (including `fresh`, `terminal-re-trigger`, and any value carrying extra text) reads as not in-flight, so the gate does not fire and full discovery runs. Conjunct (a) is load-bearing because Phase 1.3 does not reset `## Plan` on any resume: keying on the Plan alone would fire the gate on a stale all-`- [x]` Plan surviving a terminal re-trigger and re-ship the old implementation for the changed issue.
- (b) A committed, non-placeholder `## Plan`. The `## Plan` body differs from the sole seed placeholder `- [ ] _(planning in progress)_` (the `new-body` seed in `scripts/workpad.py`, replaced by §2.2.4's `--replace-plan-file`) — i.e. it holds at least one real Plan step row in any checkbox state, both `- [ ]` and `- [x]` counting. Both box states count because `--tick-plan` overwrites a plan row `- [ ]`→`- [x]` as steps complete, so a `- [ ]`-only discriminator would miss a run that finished implementing then stalled in Phase 3 or Phase 4.

Conjunct (a) reads a workpad-derived classification, never observable repository state. Phase 1.3 derives the marker from the workpad alone and emits one of exactly three bare tokens; §1.4's resume pre-check — which reads the issue's open pull requests and governs branch adoption — feeds nothing into it. So a run whose §1.4 pre-check adopted a prior attempt's branch still presents whatever token Phase 1.3 decided (commonly `fresh`, when the prior attempt's workpad writes were dropped) and this gate does not fire for it: full discovery runs over the adopted branch, and conjunct (b) fails independently there, because a workpad that recorded no classification recorded no Plan either.

On a gate fire, skip the Phase 2.1 `code-explorer` discovery dispatch and the Phase 2.2 `code-architect` dispatch plus re-planning (§2.2's Path A / Path B planning through §2.2.4's Reuse & Altitude gate — the range ends at the §2.2.4 plan write), and build on the committed `## Plan` and the §1.4-adopted branch state instead of re-discovering the system from scratch. Record the decision — `workpad.py update $ISSUE_NUMBER --note "Phase 2 §2.0 resume gate: fired (resume-kind in-flight + committed Plan present); skipping code-explorer/code-architect re-dispatch and building on the committed Plan"`. Then:

- The skip is scoped to the two DISPATCHES, never to a Blocked-capable gate that sits between them. §2.1.5 (the Reproduce-First gate) lives inside the §2.1–§2.2 range but is not skipped: it re-runs idempotently against the committed workpad (a populated `## Reproduction` section makes it a no-op; an absent one still Blocks on a bug-report classification). Skipping it would bypass a stop condition whose designed outcome is `Blocked`, letting a resumed run that cannot reproduce proceed to implementation and PR.
- Still run §2.2.5 (Scope-Adjustment) and §2.2.6 (AC-Plan reconciliation) idempotently before §2.3. The gate's skip is scoped to *re-derivation*, never to the post-plan-write mandatory steps: the Plan is written by §2.2.4 before §2.2.5/§2.2.6, so "Plan present" cannot prove those two ran. §2.2.5 on a cloud `GITHUB_TOKEN`-fallback run narrows capability-blocked ACs and can take the empty-pushable-subset Blocked path, so skipping it would push a resumed run into implementation and PR creation for work that should have Blocked or been deferred. Both read the committed workpad ACs, so re-executing them is idempotent.
- Still re-verify against a fresh tree. The gate builds on the Plan and re-verifies what is already implemented and what remains against a freshly-read tree — the fresh-tree read-target and cross-pass-coherence rules stated in §2.1 remain in force; the gate never substitutes blind trust in a stale Plan for those freshness rules (a resumed run's tree can have advanced since the first attempt).
- Onward routing — and the second thing an all-ticked Plan cannot prove. When the committed Plan is entirely `- [x]` and the fresh-tree re-verification confirms nothing remains to implement, do not re-run §2.3 implementation or §2.5's commit of already-shipped work. But an all-`- [x]` Plan is not evidence that §2.4 Test or the mandatory §2.3.x sweeps ran — Plan rows are *implementation* steps ticked by `--tick-plan` as §2.3 proceeds, while §2.4 and the sweeps run afterwards and are recorded separately by §2.5's `--tick-progress "code + sweeps"`. So read that durable Progress row from the same workpad body this gate already fetched: when `code + sweeps` is unticked, run §2.4 and the §2.3.x sweeps before leaving Phase 2 (both are idempotent), and tick it — skipping them would fail *open* toward "shipped but never verified". Tick the `**Implement**` Progress row before exiting either way. Then exit to Phase 3, the linear next phase, where §3.1 adopts the §1.4-detected open PR and §3.3 review + the §3.4 AC gate re-run as the merge gate requires. Never route past Phase 3 to Phase 4 on the strength of an existing PR: the PR is created at §3.1 *before* §3.3/§3.4, so its existence is not evidence review completed. When un-ticked Plan steps remain, resume implementing exactly those in §2.3.

This gate covers the Phase 2 subagent dispatches only; Phase 3's inline review-engine subagents run under the Skill-tool `review-and-fix` and are out of scope here.

No fire → full discovery. When either conjunct fails — a fresh run, a run that died mid-§2.1 before §2.2.4's `--replace-plan-file`, or a terminal re-trigger — this gate is a no-op and the full §2.1 discovery / §2.2 architecture pass below runs unchanged.

### 2.0.5 Durability checkpoints (mandatory — bound mid-Phase-2 work loss to ~10 minutes)

Take a durability checkpoint at each Phase 2 sub-step boundary you cross before §2.5 — after §2.1 discovery, after §2.1.5, after §2.2 planning, and after §2.4 — and, because §2.3 routinely runs longer than that window on its own, additionally at each §2.3.x sweep boundary. The §2.3.x sweeps read the branch-delta operand defined in phase-2-sweeps-contract.md's §2.3 preamble (the merge base → working-tree delta), not the uncommitted diff, so a checkpoint taken at a §2.3.x boundary removes nothing from a later sweep's operand. The ~10-minute window is a design target that sizes *where* checkpoints go, not a wall-clock assertion; a boundary reached in seconds needs no distinct checkpoint (an empty checkpoint is a no-op, never a requirement). In practice the §2.1/§2.1.5/§2.2 boundaries produce little or no *stageable repo content* — discovery/architecture output is ephemeral in-context and plan/reproduction artifacts live under gitignored `.prflow/tmp/` — so those checkpoints are usually empty no-ops; the durable work begins at §2.3.

Every checkpoint — and §2.5's own final commit — goes through the bundled helper. Invoke it as the command's leading token (per the *Cloud helper-invocation form* in `SKILL.md`), naming the files you produced since the previous checkpoint:

```bash
.prflow/vendor/prflow/scripts/phase2-durability-checkpoint.sh "feat: implement issue #$ARGUMENTS — {short description} (checkpoint)" {path} {path...}
```

- Explicit paths only. Name the files you produced since the last checkpoint; the helper stages exactly those (`git add -- …`) and refuses `git add -A`/`git add .`/intent-to-add. §2.5 goes through this same helper and is therefore explicitly scoped too — it is the run's *comprehensive-enumeration* point, not a sweep: a path you touch but never name at an earlier checkpoint stays non-durable until you name it there, and a path you never name at any checkpoint including §2.5 is never committed at all (the disclosed residual the Phase 4.3 clean-tree backstop surfaces) — a disclosed limit, not a defect.
- **Proof edits never enter history.** **Never checkpoint while an unreverted §2.1.5 temporary proof edit is in the working tree** — revert proof edits first, or simply never *name* a proof file. The helper rewrites no pushed history (no amend, no rebase, no force-push), so proof content kept out by ordering never has to be removed later.
- The helper reaches the §2.5 workflow-edit guard. It owns the cloud-tier workflow-edit guard's detect-and-do-not-stage half: on a cloud run whose `DEVFLOW_APP_ID` is empty (the `GITHUB_TOKEN` fallback) it will not stage a repo-own `.github/workflows/` path named in the relative `.github/workflows/…` spelling, so an earlier checkpoint cannot commit a workflow file the fallback credential cannot push. The match is spelling-only (the helper's own disclosed limit): an absolute path, a `../`-reaching form, and the bare directory `.github/workflows` with no trailing slash are not matched, so your revert — not this guard — remains the primary control. The guard's coupled-file enumeration and its 2.2.5 scope-adjustment routing stay your responsibility (§2.2.5 / §2.5) — only the detect-and-do-not-stage half lives in the helper.
- A checkpoint that does not land is not success. The helper treats the push as landed only when `git rev-parse HEAD` equals `git rev-parse @{u}` after pushing (mirroring `skills/implement/references/doc-deliverable-self-heal.md` step 4), and exits non-zero when they differ — a rejected non-fast-forward is one example that leaves them unequal. Push output such as `Everything up-to-date` is not itself decisive; it is exit 3 only when the comparison still shows that the checkpoint commit did not reach the tracked branch. On a non-zero exit, resolve it (rebase/re-push, or defer a workflow edit) before continuing; a still-local commit is not durable.
- Idempotent. A checkpoint with nothing new makes no commit, so a resumed run adopting the branch sees the prior content exactly once. Exit 0 always means the same thing — the work up to this boundary is on the remote. A no-op boundary earns that 0 only after the helper reconfirms `HEAD` equals `@{u}`; a branch tip that never landed (an earlier push that silently failed) exits 3 instead, so a run cannot be told "durable" by a chain of no-ops sitting on unpushed work.

Cloud-emission discipline. Invoke the helper as the repo-relative vendored literal leading token — never `bash <path>`, never a `VAR=value` prefix, never a leading `cd` (see `SKILL.md`'s *Cloud command-shape discipline*). Substitute `$ARGUMENTS`/the paths as literals when you emit the command.

### 2.1 Discovery

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway); it is deliberately not restated here.

Use the Agent tool with `subagent_type: prflow:code-explorer` to explore the codebase and understand the system as it relates to the issue.

The issue body is a starting point, not the source of truth. Treat its problem framing, any stated root cause, and its Technical Context as a strong lead to *verify* — never fact to implement on faith. The explorer (and the architect in Path B) confirm the issue's claims against the actual code; where a descriptive claim (current behavior, the stated root cause) diverges from the code, the code wins — but the code wins over a descriptive claim only when the code being read is verified fresh (see the Fresh-tree verification rules below). Subject to that freshness qualifier: surface the divergence in the workpad and plan from what the code shows, rather than implementing a claim the code contradicts.

Fresh-tree verification rules (coupled mirror of Phase 1.6 — same rules, stated at both sites; do not paraphrase one from the other). When an adopted branch was freshness-checked in Phase 1.4, its verification reads obey the two rules Phase 1.6 (phases/phase-1-setup.md) states verbatim:

- Read-target rule. When the adopted branch is behind `origin/$BASE` (per Phase 1.4's recorded behind-by count) — unconditionally when Phase 1.4 marked freshness unverified, and equally when no freshness record is present at all (Phase 1.4's workpad write is best-effort, so an absent record means freshness was never established, not that the tree is fresh: a missing record reads as unverified, never as behind-by-0) — a code-wins read that adjudicates a shipped-work claim targets `origin/$BASE` state (`git show origin/$BASE:<path>`, and tree reads only after reconciling with the fetched base), never the unfetched fork point. This rule governs which ref verification *reads*; the working branch is instead reconciled at the Phase 1.4 update-branch checkpoint (`scripts/update-branch-checkpoint.sh`, the sanctioned reconciliation point — phase-1-setup.md §1.4.1), and this read-target rule (with the cross-pass-coherence rule below) remains in force whenever that checkpoint's outcome is neither `UPDATED` nor `UP_TO_DATE` — i.e. the branch is still behind or its freshness is unverified.
- Cross-pass coherence rule. Before any "shipped/landed in PR #N" claim is REFUTED from tree reads, resolve PR #N's merge state and `merge_commit_sha` (the SHA is the response's `.mergeCommit.oid`) with a read-only `gh pr view N --json state,mergeCommit`; when the PR is MERGED and `git merge-base --is-ancestor <merge_commit_sha> HEAD` reports the merge commit is not an ancestor of the current checkout, the verdict is "checkout stale — refresh and re-verify", never "code wins". Every indeterminate outcome (a shallow history where the ancestor check errors, a failed `gh pr view`) takes the same stale-suspect verdict — a refutation requires a positively-fresh tree.

Know the one specification channel. The issue's *narrative* — Problem Statement, Current Behavior, User Impact, Technical Context, and the Implementation Notes prose (including its `Documentation Needed` bullet) — is a non-authoritative starting point to verify, not a mandate. Desired Behavior is authoritative intent; Acceptance Criteria are its exhaustive, merge-gated projection. Phase 1 must stop for author refinement when an independently verifiable Desired Behavior obligation is not represented in that projection. Once Phase 1 passes, implement and review use the resolved Acceptance Criteria as the sole formal specification; they do not copy Desired Behavior into the workpad, infer a new criterion, or create a second checklist source. The "code wins" rule above applies to descriptive claims only — it never overrides the prescriptive intent or its criteria. "Non-authoritative" means the narrative cannot be used to narrow or suppress required work — *not* "ignore it": verify each narrative claim, but never let a wrong or contradictory narrative talk you out of work the authoritative intent and shipped diff warrant. The one exception is a `Documentation Needed` block whose first content token is exactly `none` (case-insensitive, with at most one trailing `,.;:`, or `none` standing alone) as recognized by `scripts/extract-doc-needed-paths.sh`: that standalone-`none` is the writer's up-front statement that the block names no documentation deliverables, not narrative invoked afterward to escape work the block already required, so honoring it does not breach the prohibition above.

Pick the exploration map first. Default is `.docs.internal`. Override it when the issue scope sits outside app code — scan the issue body for path mentions (`.github/workflows/`, `.claude/`, `scripts/`, `cron/`, `tools/`, etc.) or a section headed "Technical Context", "Relevant files", "Files to touch", "Files to change", or "Implementation files"; collect those paths as `PRIMARY_PATHS` and instruct the explorer to read them first, falling back to `.docs.internal` only for gaps. Otherwise `PRIMARY_PATHS` stays empty and the default applies.

Pass the following prompt:
- The GitHub issue title and labels inline (the code-explorer dispatch, on every arm)
- The issue body by hand-off, not paste: when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing the subagent to Read that file directly with its Read tool, and do not paste the body into the prompt. Only ship this line when you confirmed the §1.1 write landed — `code-explorer` declares no `Bash` tool and cannot fetch the body itself, so on the degraded arm where no cache was written you must instead paste the full issue body inline (the earlier behavior), never an `Issue body path:` line to a file that does not exist.
- Explicit instruction: "Start by reading {PRIMARY_PATHS if non-empty, otherwise the internal documentation path from `.prflow/config.json` via `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`} and read relevant files under that path to understand the system architecture and identify which modules and files are relevant to this issue. Use the documentation as a map to guide your code exploration. Then explore the actual code guided by those findings. Return a distilled summary of: relevant files, current behavior, patterns used, dependencies, and anything the implementer needs to know."

Documentation updates are handled in Phase 4 by a general-purpose subagent that invokes the `prflow:docs` skill. Do not edit `.docs.internal` here; if the explorer surfaced outdated or missing docs, that signal carries forward in your context to Phase 4.1 where the subagent will act on it. This ownership is why an acceptance criterion satisfied by a `docs/…` edit is deferred, not authored here or in Phase 3: the Phase 3.4 gate recognizes such a doc-AC and leaves it for Phase 4.1 to discharge (see phase-3-review.md §3.4's *Documentation-AC deferral* rule and phase-4-documentation.md §4.1's discharge step).

### 2.1.5 Reproduce-First Gate (only when the recorded classification is bug-report)

This gate fires on the **recorded content classification** from Phase 1.3 (the `classification: ` workpad note), not the `bug` label. If that classification is non-bug, skip this step entirely and continue to 2.2.

If the recorded classification is bug-report, you must capture a *reproduction signal* before planning a fix. A reproduction signal is any one of:

- a new failing test in the diff that exercises the bug,
- a quoted error log / stack trace from a real run, or
- a recorded shell command (with output) that demonstrates the failure.

Write the evidence with the **Write tool** to `.prflow/tmp/repro-${ISSUE_NUMBER}.md` (ensure the `.prflow/tmp` directory exists first — this is a prose directive with no fence to hold a `mkdir`), then: `workpad.py update $ISSUE_NUMBER --status Reproducing --set-reproduction-file .prflow/tmp/repro-${ISSUE_NUMBER}.md --tick-progress "reproduction captured" --note "captured reproduction signal"`. (The helper inserts `## Reproduction` after `## Acceptance Criteria` if it doesn't yet exist.)

Temporary proof edits are allowed when they raise confidence in the reproduction (e.g. inserting a `console.log`, hardcoding a request payload, tweaking a build input). Every temporary proof edit MUST be reverted before the next durability checkpoint (§2.0.5) — at the latest, before the implementation commit in 2.5. A proof edit still present when an earlier checkpoint names its file enters pushed history that nothing later rewrites. The fact that you made a proof edit must also be recorded in the workpad's `Reproduction` section.

Phase 2.2 cannot start until the workpad's `Reproduction` section is populated. If you cannot reproduce the bug: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "cannot reproduce: {obstacle}"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop the run — do not invent a fix.

### 2.2 Assess Complexity & Plan

`workpad.py update $ISSUE_NUMBER --status Planning`.

Using the explorer's findings (and the reproduction signal, for bugs), evaluate the issue complexity:

Simple issues (implement directly — skip architect):
- Single-module changes (e.g., add a field, fix a bug, update a config)
- Clear solution described in the issue body
- No architectural decisions needed
- Touches ≤ 5 files

Complex issues (use architect subagent):
- Cross-module changes affecting multiple subsystems
- New features requiring design decisions
- Changes to interfaces, data models, or system architecture
- Ambiguous requirements needing breakdown into tasks

#### Path A: Simple issue

Output: `Skipping architect — issue is straightforward. Implementing directly.`

Plan the implementation inline using the explorer's findings. Identify which files to create/modify and what changes to make.

#### Path B: Complex issue

Use the Agent tool with `subagent_type: prflow:code-architect` to design the implementation.

Pass it:
- The GitHub issue title and labels inline (the code-architect dispatch, on every arm)
- The issue body by hand-off, not paste: when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing the subagent to Read that file directly with its Read tool, and do not paste the body into the prompt. Only ship this line when you confirmed the §1.1 write landed — `code-architect` declares no `Bash` tool and cannot fetch the body itself, so on the degraded arm where no cache was written you must instead paste the full issue body inline (the earlier behavior), never an `Issue body path:` line to a file that does not exist.
- The explorer's distilled findings as inline context, prefixed with: "The code-explorer analyzed the current codebase and produced the following findings:"

The architect returns a focused blueprint (files to create/modify, component designs, data flows, build sequence). Hold this blueprint in your context — do NOT commit it (it is a temporary working artifact).

Re-derive a subagent's numbers before you rely on them. This applies to explorer analysis and architect blueprint alike, on Path A and Path B.

- Scope. Independently re-derive any quantitative claim a Phase-2 subagent produced before that claim feeds a plan step, a gate, or a budget decision. A volunteered number that feeds no decision is treated as unverified, and the absence of an `(unverified estimate)` marker waives nothing for a decision-feeding claim.
- Channel. Re-derive through a preflight-guaranteed channel — `python3` (granted in the cloud implement profile; invoked helper-by-path on the local tier) — never an ad-hoc non-preflight PATH tool such as `wc`/`tr`/`cut`/`head`, whose host divergence is the measurement bug this obligation guards against.
- Channel exception. Where the number's downstream consumer defines its own standalone-invocable counter, that counter is the channel and takes precedence over the ad-hoc never-list. But a counter embedded inside a larger artifact (a test-suite-internal function) is not mirrored inline — the claim resolves to unverified instead.
- Unresolvable claims. A claim whose re-derivation channel is unavailable, or whose producer stated no operands and counting rule to re-derive against, resolves to unverified, never to confirmed.
- Unverified does not block. An unverified decision-feeding claim feeds the decision only with its `(unverified estimate)` marker propagated into the plan step and workpad entry that consumed it.
- Record the status. When a Phase-2 subagent quantitative claim reaches the workpad Plan, record its re-derived-or-unverified status in the workpad entry itself, so the marker survives context compaction and stall-backstop resume.

#### 2.2.4 Reuse & Altitude gate (mandatory, before the plan is written)

Two of the cleanup lenses that the Phase 3.2 `/simplify` pass would otherwise flag — reuse and altitude — are *design* decisions. Apply both to the plan (from either path) before you write it to the workpad:

1. Reuse. For every piece of new code the plan proposes (a helper, a parser, a validator, a state shape, an API client), grep the shared/utility modules and the files adjacent to the change for something that already does the job. If it exists, the plan reuses the existing helper by `file:line` rather than re-implementing it; new code is justified only when no existing implementation fits.

   Key the search on the job, not on the syntax you intend to write. Build the query from what the code will *do* — the endpoint it calls, the API or operation name, the shape of the data it handles, the domain noun it works on (an illustrative floor, not a closed list) — never from the tokens, flags, or idiom of the implementation you have already decided to write. A query keyed on your intended shape can only *confirm* that decision: an existing helper doing the same job in a different idiom matches none of your syntax and stays invisible, so the search returns a clean zero that means nothing.

   Disconfirmation check (a precondition on running the search). Before you run the query, test it against one question: *would this match an implementation of the same job written in a different idiom?* When it would not, the query is keyed on your syntax rather than the job — re-key it on the job and re-run. This adds no search in the ordinary case; a re-keyed re-run is required only on the units where this check fails.

   Record a zero match bounded to what you searched. A reuse search that returns nothing is recorded as bounded to the predicates you actually searched — "no candidate matched `<predicates searched>`" — never as a bare claim of absence, which would state as verified a finding the search cannot support. Carry those predicates in the same plan step that consumes the reuse result (the step naming what to reuse or build).
2. Altitude. Check that each planned change sits at the right depth, not as a fragile bandaid — a pile of special cases layered on shared infrastructure is the signal that the fix isn't deep enough, so prefer generalizing the underlying mechanism over stacking special cases. Wherever the plan reaches for a special-case patch, ask whether the shared mechanism should change instead and re-aim the plan there.

Fold the result into the plan before the plan write below — this is a planning gate, not a code edit: name the helpers to reuse (with `file:line`) in the relevant plan steps, and pick the altitude before writing the steps.

After planning (either path), write the plan steps as `- [ ]` checkboxes with the **Write tool** to `.prflow/tmp/plan-${ISSUE_NUMBER}.md` (ensure the `.prflow/tmp` directory exists first — a prose directive with no fence to hold a `mkdir`), then `workpad.py update $ISSUE_NUMBER --replace-plan-file .prflow/tmp/plan-${ISSUE_NUMBER}.md`.

#### 2.2.5 Scope-Adjustment Rule (multi-PR issues)

If discovery and planning revealed that the issue's deliverables span more than fits in a single PR (e.g., a phased cleanup, a multi-stage migration, or any issue whose acceptance criteria explicitly enumerate work for several future PRs), you must narrow the workpad's `## Acceptance Criteria` to only the items this PR will deliver before continuing to 2.3. Otherwise the Phase 3.4 gate will reject your run for criteria that are out-of-scope by design, and the run will stop without ever reaching Phase 4.

Capability-blocked ACs are a sanctioned trigger too. Beyond phased/oversized work, this rule also fires on a cloud-tier run whose credential cannot push workflows — `GITHUB_ACTIONS=true` and `DEVFLOW_APP_ID` empty/unset, i.e. the built-in `GITHUB_TOKEN` fallback (a cloud run with `DEVFLOW_APP_ID` **set** carries a workflow-capable App token seeded into checkout and does NOT trigger this; a local/interactive run does not either) — for any acceptance criterion that requires editing the repo's own `.github/workflows/` (or a file coupled to that edit, such as a coupled test-suite pin asserting workflow content), which that `GITHUB_TOKEN` fallback cannot push. Two sources feed this trigger, and you must check both here — Phase 1.6's execution-capability pass (Pass 5) flags the ACs whose workflow-residence is visible in their own text, but that flag is *provisional*: now that planning has produced a concrete diff, re-evaluate it against what the plan will actually touch and also catch any AC whose workflow-residence surfaced only during planning (its text never named `.github/workflows/`, but the plan reveals it must edit one). Route every capability-blocked AC — flagged-by-Pass-5 or discovered here — through the steps below before Phase 2.3 writes any code (never after a rejected push): narrow to the pushable subset, and record the `GITHUB_TOKEN`-fallback workflows-scope boundary (`DEVFLOW_APP_ID` empty — no workflow-capable App token) as the deferral reason in the `--note` so Phase 4.0's follow-up can state that landing the deferred work needs a workflows-capable (human/PAT, or App-configured cloud) push. And if Phase 2.3 code-writing *itself* later reveals a required `.github/workflows/` edit that neither Pass 5 nor this plan-time re-check caught (planning was incomplete), re-apply this scope-adjustment then, before committing — a workflow-file edit must never be committed and pushed by the bot on a cloud-tier run whose `DEVFLOW_APP_ID` is empty (the `GITHUB_TOKEN` fallback).

Empty pushable subset ⇒ take the Blocked path here, do not narrow-and-proceed. When narrowing would leave the pushable subset empty — *every* remaining in-scope AC is capability-blocked, whether that was already known at Phase 1.6 Pass 5 or is only discovered here (at 2.2.5 against the concrete diff) or during the 2.3 re-route — do not narrow to nothing and continue into implementation/PR creation. There is no shippable work, so take the Phase 1 Blocked path executably at this point: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "issue-claim audit (execution-capability): every in-scope acceptance criterion requires editing .github/workflows/, which this cloud run's GITHUB_TOKEN fallback (no workflow-capable App token; DEVFLOW_APP_ID unset) cannot push — must be implemented by a workflows-capable run (a human/PAT, or a cloud run with the DevFlow App configured). Re-dispatch there; no PR opened"`, emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference), and stop the run.

Steps when scoping down:

1. Write the narrowed AC list (only in-scope checkboxes, verbatim) with the **Write tool** to `.prflow/tmp/narrowed-acs-${ISSUE_NUMBER}.md` (ensure the `.prflow/tmp` directory exists first — a prose directive with no fence to hold a `mkdir`).
2. Apply the change atomically:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
       --replace-acs-file .prflow/tmp/narrowed-acs-${ISSUE_NUMBER}.md \
       --scope-decision-deferred pending "{the deferred criterion's text, verbatim}" \
       --note "scope decision: {which subset this PR delivers}. Deferred (verbatim): {list}. Will be tracked in follow-up issue(s) filed in Phase 4.0."
   ```

Pass one `--scope-decision-deferred pending "<the deferred criterion's text, verbatim>"` per deferred criterion, in the same call as `--replace-acs-file`, so the narrowing and its machine-readable record land together. The PR literal is `pending` here because §3.1 has not yet opened the draft PR, and §3.1 binds every `pending` record to the real number the moment it exists. The review engine reads this machine-readable record and never the free-text `--note`.

This is not "inventing" criteria (forbidden by 1.4) — the deferred items are preserved verbatim in the workpad notes (`--note`), which stays the human-readable record, and carried forward by Phase 4.0.

If you are unsure whether to scope down, prefer a single fully-in-scope PR. Only re-scope when the issue body itself describes phased work, the diff would otherwise exceed reasonable PR size, or Phase 1.6 Pass 5 flagged a capability-blocked AC on a cloud-tier run (the credential-boundary trigger above).

#### 2.2.6 AC-Plan reconciliation (rewrite surface details, never relax intent)

Some ACs name specific identifiers (job names, file paths, function names, command names). If the plan you settled on — or a later refactor in /simplify (3.2) or /prflow:review-and-fix (3.3) — uses different identifiers for the *same underlying behavior*, the literal AC text becomes stale and Phase 3.4 will reject a strictly-correct refactor. You may rewrite the affected AC in the workpad only if the rewritten text verifies the same observable outcome with the new identifiers; never relax what's verified.

Reconciliation steps:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --rewrite-ac "{OLD AC substring}" "{NEW AC substring replacement}" \
    --scope-decision-rewritten pending "{FULL OLD criterion text, verbatim}" "{FULL NEW criterion text, verbatim}" \
    --note "AC rewrite: {old verbatim} → {new}. Motivated by: {structural change}"
```

Pass `--scope-decision-rewritten pending "{FULL OLD criterion text, verbatim}" "{FULL NEW criterion text, verbatim}"` in the same call as `--rewrite-ac`, so the text change and its machine-readable record land together. The PR literal is `pending` for the same reason as in 2.2.5 — §3.1 binds it once the draft PR exists — and the review engine reads that record rather than the free-text `--note`, which carries no criterion identifier.

The two flags deliberately take different text — never "simplify" them into the same value. `--rewrite-ac` performs an *in-place substring replacement* inside the criterion, so its first argument may be any distinguishing fragment. `--scope-decision-rewritten`'s OLD value is stored normalized and is later matched by the review engine as a whole-criterion equality lookup against the full issue-body criterion — so a fragment there simply fails to match, and the criterion is reported to the merge-gating reviewer as an unexplained dropped criterion. Pass the criterion's *entire* text as it stands immediately before the rewrite, and its entire text as it will read after.

Why the workpad criterion set is trustworthy as a review comparand, and what falsifies it. The review engine may treat the workpad's `## Acceptance Criteria` as authoritative because every writer that changes the set's membership or a criterion's text either emits a scope-decision record or can only ever widen the set — never narrow it:

- Record-emitting writers: §2.2.5's `--replace-acs-file` narrowing, and the `--rewrite-ac` call sites (this one, and phase-3-review.md §3.4's retroactive `(post-merge)` retag).
- Widening-only writers: phase-1-setup.md §1.2's two `--replace-acs-file` mirrors — the fresh-workpad mirror and the resume-path mirror — which need no record because each sets the workpad's section equal to the issue body's criteria; that is never a narrowing, so `_acs_pr_identity_ok`'s superset early-return (`workpad_norm >= issue_norm`) accepts it with no record to explain.
- No record needed: `--tick-ac` and `--tick-ac-n` change only box state, which the engine's normalized comparison already ignores.

The assumption is falsified if any writer path can change the set's membership or a criterion's text without emitting a scope-decision record.

Known residual — the resume-path mirror. A resumed run re-mirrors the issue's section wholesale while a prior run's §2.2.5 scope-decision records still sit in `## Progress`. The *set* stays safe (a superset of the issue body — nothing dropped), but those surviving records describe deferrals the live set no longer reflects. So a resumed run re-derives its acceptance criteria from the issue and re-applies any narrowing that still holds through §2.2.5 — never treating a stale record as a live description of the current set.

`--rewrite-ac` preserves the box state (don't tick during the rewrite — Phase 3.4 will tick via `--tick-ac-n` later). This is not scope adjustment — the rewritten AC is still gated in 3.4.

**When the rewrite records a design *deviation* (the plan intentionally diverges from what an AC prescribed), also leave an in-repo breadcrumb comment at the deviation site.** The workpad `--note`/AC-rewrite paper trail lives only on the issue, and blinded shadow reviewers (Phase 3.3's fix loop deliberately withholds loop history) never see it, so a signed-off deviation gets independently re-raised as a finding iteration after iteration. To make the sign-off travel in repo content the reviewer *does* see, add a short comment at the deviating code site naming the parent issue and pointing at the workpad record — e.g. `# Deviates from issue #<N>'s prescribed <X>: <one-line why>; see the workpad AC-rewrite note.` (A pure surface-identifier rewrite with no behavioral deviation needs no such comment; this obligation is scoped to a *deviation*.)

If the rewrite would relax the AC (drop a guarantee, weaken a check, remove a verification surface), STOP — apply 2.2.5 (defer the AC to a follow-up issue) or revert the structural change instead.

#### 2.2.7 Pre-flight coupled-site map (before any Phase 2.3 edit)

When the plan touches a value, contract, or literal that lives in more than one place — the class the §2.3 "Sweep selection" preamble defines by *what the change replicates across sites, not whether it is code* — list those other places before you start editing, not after. The §2.3 relocation and contract-completeness sweeps make this same check *after* the edits are written.

Enumerate the sites with searches you actually run, in the granted forms and preference order the §2.3 preamble already lists, and record both the commands you ran and what they found through a workpad `--note` before the first edit. Do not attest a search you did not run.

A search that errors, is refused, or otherwise cannot be confirmed to have run is a gap, not evidence of no other places: record it as a gap naming that command, and build the map only from searches that observably ran — a refused search never counts as "there were no other places." Apply the §2.3 preamble's "confirm the search actually ran" rule here to tell an honest zero-match from a search that never ran.

If your project publishes a coupled-site registry — a checked-in list of which sites must change together — consult it as well; a project that publishes none is simply unconstrained by it.

<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-implement.md end -->

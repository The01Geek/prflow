---
name: create-issue
description: Use when a rough user story, bug report, feature idea, piece of feedback, or an implementation plan should be recorded as a GitHub issue — "file a ticket for this", "open an issue", "write this up for the backlog", "we should track this", "log this bug", "spec this out as a ticket so we can pick it up later" — i.e. the user wants it tracked rather than built right now. For exploring or designing the work itself, reach for a brainstorming or planning skill first; this skill records the outcome as an issue.
argument-hint: <user-story>
---
**Portable helper anchor (single-statement).** This skill invokes helpers bundled beside it — `load-prompt-extension.sh`, `issue-audit-state.py` (the audit-lifecycle state owner), `resolve-main-root.sh`, `ensure-label.sh`, `apply-labels.sh`. Resolve the skill directory **inline, in the same statement that uses it**, as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`: the `:-` form uses `$CLAUDE_SKILL_DIR` only when it is set **and non-empty**, because the observed non-Claude-Code failure is an *empty* variable, not an unset one. Otherwise substitute the base directory this runner reports in context — e.g. a `Base directory for this skill:` line. **Never capture the anchor into a shell variable that a later statement reads**: some runners' inline-bash marshaling drops a variable assigned in an earlier statement of the same command.

**Normalize a Windows-form base directory before substituting it** — a POSIX shell cannot use `C:\...` as-is. Run one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) and use its output **only if the command succeeds and prints a non-empty path — otherwise fall through to the drive-letter rules exactly as if the tool were absent**. With neither tool: lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and turn backslashes into `/`. Neither WSL nor MSYS2: use the path unchanged and report that it could not be normalized. These are `lib/normalize-path.sh`'s rules restated as prompt-time prose, because the anchor is what locates `lib/`.

**An unresolvable anchor degrades; it never stops the run** — unlike the other skills' fail-closed stop, an anchor failure must never block issue *creation*. Proceed and let the underlying "No such file" error surface: a `/prflow:docs-verify` pass whose anchor cannot resolve takes Step 1's degraded arm, and an `issue-audit-state.py` call that produces no contract output routes to Step 3.6's `state-owner unavailable` fallback.

**Consumer prompt extension (load first).** Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh create-issue
```

Four outcomes. A **missing helper path** (`No such file`, exit 127, or the platform equivalent — e.g. `The system cannot find the path specified` on Windows shells, or a localized message) is the anchor-resolution failure above — fix the anchor, do not report a missing extension. Otherwise, on a **non-zero exit** where the helper runs but fails, a consumer extension exists but could not be loaded: surface its stderr message, never silently proceed as if none existed. **Exit 0 with text** is consumer-owned customization under `.prflow/prompt-extensions/` — treat it as instructions appended to the end of this skill's own prompt for this run. **Exit 0, no output**: proceed unchanged.

## Prerequisites

If `$ARGUMENTS` is empty, ask the user to describe their user story, bug report, or feature idea before proceeding.

## Core principle

**An issue is the output of resolved decisions — not a place to park unresolved ones.**

Every decision a developer would otherwise have to guess at MUST be resolved by asking the user *before* the issue is written. Whatever the user genuinely will not or cannot resolve goes into one explicit **Blocked** section — never disguised as an "option", a "recommended approach", an "Open Question", a default, or conditional wording scattered through the body.

## Completion checklist (do this first)

This skill is a **pipeline that ends with a created GitHub issue and a *gated* offer to start implementation** — the offer is presented, or a one-line reason is printed for why it was withheld — not with a documentation report. Before doing anything else, set up progress tracking for exactly the seven items below using the task-tracking tool the runner exposes — `TodoWrite` (Claude Code), `TaskCreate`/`TaskUpdate` (newer Claude Code sessions), or `update_plan` (Codex CLI) — and, when the runner exposes no task-tracking tool or the exposed one is disabled or unusable, use the inline checklist fallback in `references/fallback-no-task-tool.md`, loaded per the routing table below:

1. Run Step 1's selected arm and write its evidence artifact
2. Clarify the user story until the **Definition of Ready** is met (Step 2)
3. Draft the issue and pass the **no-options gate** (Step 3)
4. Steelman the draft against the code, revise, and re-pass the no-options gate (Step 3.5)
5. Audit the draft in a fresh context, act on the verdict, and re-gate any revision (Step 3.6)
6. Present the rendered issue, get the user's explicit confirmation, then create it (Step 4, sub-steps 1–5)
7. After creation succeeds, run the gated implement-offer step — present the offer, or print the withheld-offer reason (Step 4, sub-step 6)

Mark each item `in_progress` when you start and `completed` only when done — the canonical status vocabulary; a task tool whose status fields differ uses its nearest equivalents, and the inline fallback expresses the same transitions with the three status markers `references/fallback-no-task-tool.md` defines. **The issue is created only after the user explicitly confirms the rendered draft (todo 6) — never before.** A finished `/prflow:docs-verify` report is only todo 1. Unconfirmed, the pipeline is paused at todo 6, not complete — a valid waiting state, never a reason to create the issue anyway. Todo 7 runs only after a successful creation: it is the post-creation hand-off, not a gate on creating the issue.

## Reference routing

The per-step procedures and the conditional fallback arms live in `references/`, loaded at their trigger. **Build a reference's path from this skill's directory per the *Portable helper anchor* rules above and read it with the runner's file-read tool** — never a new shell invocation. A load is accepted only when the file's **first line is its `start` boundary marker and its last line is the matching `end` marker**, each naming that file's own path, with exactly one of each.

**Every load failure degrades, and no failure arm terminates the run.** On an unreadable or absent file, an empty file, a missing / duplicated / foreign-path marker, or a truncated read, emit an in-chat breadcrumb naming the file and the failure kind, then continue on that row's named degraded behavior below. The five non-degradable invariants stated after this table hold on every degraded arm.

| Load trigger | File | Marker contract | Degraded behavior on a failed load |
| --- | --- | --- | --- |
| Step 2 entry | `references/step-2-clarify.md` | `step=2` | Clarify from the Definition-of-Ready summary in the completion checklist, asking via the runner's user-question tool; record the derivation in chat when it cannot be written to disk, and report the reduced clarification |
| Step 3 drafting entry | `references/issue-template.md` | `step=issue-template` | Say so in chat, draft against the section list in the completion checklist above, and re-gate the body inline per Step 3's rule; if a loaded prompt extension points into the unreadable template, record that referenced rule as `unestablished` and omit any draft assertion governed by it — never treat the pointer itself as proof that the unavailable rule passed; because the template also carries the exact `gh issue create` recipe, do not improvise the invocation — pass the body through a non-empty-guarded `--body-file`, never a pipe; filing is not blocked and the degradation is reported |
| Step 3.5 entry | `references/step-3-5-steelman.md` | `step=3.5` | Verify the draft's load-bearing claims and file references against the code inline, and report the steelman as reduced in chat |
| Any revise-and-re-gate site | `references/revision-delta.md` | `step=revision-delta` | Re-gate the revision under Step 3 and report that the delta walk was unavailable |
| Step 3.6 entry | `references/step-3-6-audit.md` | `step=3.6` | Audit the rendered draft yourself in chat for exactly one round, keep the findings in chat, ask the user once whether to continue, and mark the audit summary line as degraded |
| Step 4 entry | `references/step-4-present-create.md` | `step=4` | Render the full draft in chat, carry the audit summary line, and create only on the user's explicit approval — the invariants below |
| No task-tracking tool is exposed, or the exposed one is disabled or unusable | `references/fallback-no-task-tool.md` | `step=fallback-no-task-tool` | Track the seven checklist items as a re-rendered in-chat block and report that the state-file mirror was unavailable |
| A write or delete under `.prflow/tmp/` fails because the filesystem is read-only | `references/fallback-read-only-sandbox.md` | `step=fallback-read-only-sandbox` | Post the affected artifact as a visible in-chat block in the current turn and distrust any on-disk copy |
| `query-arm` answers a non-file arm, a dispatch retry escalates, or no subagent tool is exposed | `references/fallback-audit-dispatch-arms.md` | `step=fallback-audit-dispatch-arms` | Audit the rendered draft in chat for that round and mark the audit summary line as degraded |
| The state owner produces no contract output, or a mutation fails to establish or persist state | `references/fallback-state-owner-unavailable.md` | `step=fallback-state-owner-unavailable` | Run one in-chat audit round, offer one continue/decline choice, and proceed only on the user's explicit election |
| `query-boundary` reports any trigger component (`t1=`, `t2=`, `coverage=`, `calibration=`) at `hold`, or an `unledgered_revise` round | `references/fallback-audit-boundary-offer.md` | `step=fallback-audit-boundary-offer` | Offer one more audit round in chat naming the trigger that fired, honour an explicit decline, and name the offer's outcome in the audit summary line — recording neither `record-offer` nor the boundary `record-override`, so the round falls outside the ceiling accounting and a REVISE-carrying draft clears approval through Step 4's file-anyway election |
| Adjudicating a second-or-later audit round | `references/fallback-audit-round-reconciliation.md` | `step=fallback-audit-round-reconciliation` | Adjudicate this round's findings against the `query-findings` read-back alone and report that the cross-round reconciliation discipline was unavailable |
| A staged `apply` answers `agree=no`, a landed re-check disagrees, or a `reason=foreign-nonce` answer is read back from `query-draft-binding` or `query-findings` | `references/fallback-draft-write-recovery.md` | `step=fallback-draft-write-recovery` | On a write disagreement report `--write-landed no` to `query-arm` and present from the in-context bytes; on a drifted nonce report the drift to the user and compose no path from the answer — never `--write-landed no`, which no failed write supports |
| The leading-token `config-get.sh .workflows.prflow` read is denied or fails | `references/fallback-implement-offer-tier-read.md` | `step=fallback-implement-offer-tier-read` | Withhold the implement offer, naming *tier state unestablished* as the one-line withheld-offer reason — never *config unreadable*, which the degraded read never established |
| The issue involves user-visible UI changes | `references/fallback-visual-specification.md` | `step=fallback-visual-specification` | Verify the visual details with the user inline before finalizing the draft and report that the visual-specification guidance was unavailable |
| `record-return` classifies a round `no-parseable-verdict` on absent or mismatched carriage evidence, the instruction-file generation exits non-zero or empty, or the audit-prompt render produces no output or misplaced markers | `references/fallback-audit-evidence-degraded.md` | `step=fallback-audit-evidence-degraded` | Name the arm that fired in the in-chat audit summary line and proceed to presentation with that disclosure, attempting no `record-degraded` call — the summary line is the required surface, and filing is never blocked |

## Non-degradable invariants

These five hold on every path, including every degraded arm above, and are load-independent of any reference:

1. **The issue is created only after the user explicitly approves the full rendered draft in chat.** The full title and body are rendered verbatim in your message first; an earlier "just create it", a complete Step 2, or a paused pipeline is never a substitute for approval of *this* draft.
2. **The no-options gate** (stated under Step 3 below) passes on the body that is shown and on every revision of it.
3. **The audit summary line is mandatory and always renders** — even on a clean `VERDICT: FILE` with zero findings. A skipped or degraded audit is **never silent**; the summary line is the evidence the audit ran and which arm it took.
4. **The reserved `PRFlow` provenance label is applied best-effort after creation, and any degradation is reported explicitly** — a label hiccup never blocks creation, and a `PRFlow` label that could not be applied is named in the final outcome rather than passed over.
5. **The self-assignment election runs after approval and before creation, on every path including every degraded arm.** After the user approves the full rendered draft and before any `gh issue create`, ask whether to assign the new issue to the user: an explicit **yes** adds `--assignee "@me"`, an explicit **no** creates it unassigned, and silence or any non-yes/non-no reply pauses and re-asks — no issue-creation command runs until the answer is an explicit yes or no. This election belongs to the interactive create path only; a draft-only request never reaches it.

## Subagent dispatch is user-requested here (injection-condition clause)

Invoking `/prflow:create-issue` **is** the user's request for subagent dispatch at this skill's two dispatch sites — the Step 1 `/prflow:docs-verify` peers and the Step 3.6 fresh-context audit subagent — thereby satisfying any injected "do not call the AgentTool unless the user requested it" condition there and nowhere else. It changes no degradation arm above: a dispatch that fails, is unavailable, or is refused still degrades onto its named fallback, and nothing blocks issue creation.

## Steps

### Step 1: Assess current state (read-only)

Dispatch `/prflow:docs-verify --report-only` peers on the topic extracted from the user story.

**Bind the slug, then clear state — before any dispatch.** Bind this run's kebab-case slug here; no later step binds one. Delete any `.prflow/tmp/issue-step1-<slug>.md`, and delete-and-rewrite the fixed slug-independent pointer `.prflow/tmp/issue-run-slug` holding this slug. Both deletes run on every path including the degraded one; a failed delete leaves a possibly-stale leftover and routes to `references/fallback-read-only-sandbox.md`'s distrust-the-on-disk-copy row. The pointer, like the evidence artifact, is anchored to the working directory (the worktree cwd), **not** to `resolve-main-root.sh`'s MAIN_ROOT, and its content is exactly one kebab-case slug on one line. Later sites lacking the slug read that pointer; a pointer that is absent, unreadable, **empty, whitespace-only, or not that single-slug shape** is recorded **unestablished** and routes to the title-derived fallback `references/step-4-present-create.md` retains — never a slug composed from a partial read. **Disclosed residual:** the pointer carries no run-identity token, so a concurrent run in the same checkout overwrites it and its only reader — having lost turn-one context — holds no comparand that would detect the swap.

**Two arms, selected before any dispatch** by a pre-pass operand: the duty-floor duties you judge the topic to engage. Derive it — and any value deciding which leg ran — with python3 or bash builtins, never `tr`, `sed`, `wc`, `cut` or `head`, which preflight does not guarantee and whose absence fails open.

- **Shallow** — fewer than the full floor, and the arm for a topic engaging **no** duty: **one** dispatched peer over the **union** of the deep legs, enumerated from the git index.
- **Deep** — the **full** floor, entered directly: **two parallel** dispatched peers over those legs separately.

Both arms dispatch rather than run inline, so survey tool output stays in a peer's context; no git history is read.

**Legs disjoint by construction:** the location resolved from `.docs.internal`, and the tracked tree **minus that location's subtree** — never an assertion they are already disjoint. Both enumerate from the index, and each reaches its peer as docs-verify's **search-space operand**, never as dispatch-prompt prose its own contract overrides. The duty floor, not the space's size, bounds each peer.

**The orchestrator reconciles both returns.** An empty documentation leg is an **established absence only when the location itself is absent**. Record **unestablished** when the location exists and the read fails, and equally when it exists and reads cleanly yet holds **no git-index entries** (an absolute path, a parent escape, a symlink, an untracked docs tree — the schema forbids none), so claim no documentation coverage rather than a clean absence. **Unequal returns** — one peer returning, one failing — degrade to the surviving leg with a breadcrumb naming the failed leg, never reporting a partial verification as complete. An **incomplete return** — one that succeeds but omits or malforms its duty statuses, or omits a bearing observation for a duty it reported `judged-not-engaged` — records that duty **unestablished** with a breadcrumb naming the missing field, never a discharged floor.

**Escalation** shallow→deep is the verdict token's **only** role, never the arm selector. Escalate on drift or a missing document, on an **unestablished** duty, and on any **judged-not-engaged** duty whose returned bearing observation is non-empty **once the producer's explicit `none-observed` token is excluded** — that field is always present, so escalate on any value other than `none-observed` and record **unestablished** (which escalates) when it is absent or unparseable. That comparand is a field of the report you receive, so the pre-pass judgement does not gate it.

**Evidence artifact.** The **orchestrator — never a peer** — writes the returned evidence (reconciled, on the deep arm) to `.prflow/tmp/issue-step1-<slug>.md`, anchored to the working directory, on **both** arms before Step 1 returns. Peers write nothing. Those findings stay resident in your context and durably held in that artifact, so Step 3 draws on them **by pointer and does not re-quote the findings block into its own output**, which only inflates runtime main-thread context. Step 2's evidence bundle and an escalating deep arm read the artifact.

**Degraded arm.** A failed, unavailable, or rejected pass — or one whose helper anchor cannot resolve — degrades to a **bounded inline verification** with a breadcrumb naming the failure kind, marks its evidence **degraded**, and writes its own output to the same artifact path. It never terminates the run and never presents a half-verification as whole.

**Completion-wait discipline (mandatory, mirroring Step 3.6's synchronous dispatch).** The docs-verify findings report must be **complete and captured before the first Step 2 clarification question** — and, on a run so complete it asks **zero** clarifying questions, **before Step 3 drafting begins**. When a runner executes `/prflow:docs-verify` as a subagent, **that dispatch blocks on the completed result**, and a **launch acknowledgment is never treated as the findings report**. Never open Step 2 clarification or Step 3 drafting on the strength of "docs-verify is running": questions that arrive before the code findings grounding them interrogate the user prematurely.

### Step 2: Clarify until the Definition of Ready is met

Load `references/step-2-clarify.md` per the routing table above and follow it exactly, on every entry into this step.

### Step 3: Draft the issue and pass the no-options gate

**Precondition — the Step 2 derivation-artifact gate applies here too, unconditionally.** Drafting happens on every run but clarification does not, so this is the unconditional backstop for a story so fully specified that the Step 2 gate's first-question trigger never fired. Before drafting, confirm `.prflow/tmp/issue-derivation-<slug>.md` exists and holds *this run's* derivation — **or, in a read-only sandbox, rely solely on the visible inline-in-chat stand-in re-posted in this turn and do not trust any on-disk file (it can only be a stale leftover)**. If the artifact is missing or you cannot confirm it is this run's, the independent-derivation pass was skipped — **stop and run it now (Step 2) before drafting.** **This equally gates the `## Evidence bundle`:** it must be present and axis-complete against the effective list recomputed here (the second, unconditional site of the *Bundle-coverage gate*); if it is missing or an axis has no entry, stop and run the evidence-bundle sub-pass now before drafting.

Draft the issue **from the context you already hold** — the documentation findings from Step 1 (relevant files, current behavior, any drift) and the decisions from Step 2 — doing only targeted verification reads where a specific claim needs confirming. Do not re-explore the whole codebase; the findings are your map, resident in context and durably held in `.prflow/tmp/issue-step1-<slug>.md`, so reference them **by pointer** and **do not re-emit the findings block into your drafting output**. (User-facing decision inputs — the surviving audit findings quoted for the user's Step 3.6/Step 4 election — are authoritative and exempt.)

Before composing the draft prose, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it (an issue is change-describing prose). Per this skill's degrade-never-terminate contract, a failed load emits a breadcrumb naming the file and the failure kind and you draft without it.

Load `references/issue-template.md` per the routing table above and follow it for the required section structure, the **no-options rule**, the quality checklist, and autolink hygiene, on every entry into this step. Key rules:

- **No-options gate (run before showing the draft):** re-read the rendered body. Outside the `## 🚫 Blocked` section — and outside the Implementation Notes `Relevant files` block, which the scan skips by location exactly as it skips `## 🚫 Blocked` — it must contain **no** unresolved-decision language — no "or", "either", "alternatively", "could", "we might", "TBD", "option", "approach A vs B", "(optional)"-for-undecided, "e.g. X or Y" where X and Y are competing choices. Each acceptance criterion is one concrete unconditional assertion. If you find any such language, you skipped a decision: either ask the user now, or move it to the Blocked section. Do not proceed to Step 4 until the body is clean.

Drafting produces a candidate issue **in your message only** — nothing is posted to GitHub in this step. Posting happens in Step 4, and only after the user confirms — but first the draft must survive Step 3.5.


### Step 3.5: Steelman the draft against the code (mandatory, before the user sees it)

Load `references/step-3-5-steelman.md` per the routing table above and follow it exactly, on every entry into this step.

### Step 3.6: Fresh-context audit (mandatory, before the user sees it)

Load `references/step-3-6-audit.md` per the routing table above and follow it exactly, on every entry into this step.

### Step 4: Review with the user, then create

Load `references/step-4-present-create.md` per the routing table above and follow it exactly, on every entry into this step.

---

User Story (rough draft): $ARGUMENTS

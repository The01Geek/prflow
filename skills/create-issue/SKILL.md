---
name: create-issue
description: Use when a rough user story, bug report, feature idea, piece of feedback, or an implementation plan should be recorded as a GitHub issue — "file a ticket for this", "open an issue", "write this up for the backlog", "we should track this", "log this bug", "spec this out as a ticket so we can pick it up later" — i.e. the user wants it tracked rather than built right now. For exploring or designing the work itself, reach for a brainstorming or planning skill first; this skill records the outcome as an issue.
argument-hint: <user-story>
---
## Completion checklist (do this first)

This skill is a pipeline that ends with a created GitHub issue and a gated offer to start
implementation — the offer is presented, or a one-line reason is printed for why it was withheld —
not a documentation report. Before anything else, fill in this seven-slot tracker using the
task-tracking tool the runner exposes (`TodoWrite`; `TaskCreate`/`TaskUpdate`; or `update_plan`),
or, when none is exposed or the exposed one is unusable, the inline fallback in
`references/fallback-no-task-tool.md` loaded per the *Reference routing* rules below:

- [ ] 1. Run Step 1's selected arm and write its evidence artifact
- [ ] 2. Clarify the user story until the Definition of Ready is met (Step 2)
- [ ] 3. Draft the issue and pass the no-options gate (Step 3)
- [ ] 4. Steelman the draft against the code, revise, re-pass the no-options gate, and append the steelman record to the derivation artifact (Step 3.5)
- [ ] 5. Audit the draft in a fresh context, act on the verdict, and re-gate any revision (Step 3.6)
- [ ] 6. Present the rendered issue, get the user's explicit confirmation, then create it (Step 4, sub-steps 1–5)
- [ ] 7. After creation succeeds, run the gated implement-offer step — present the offer, or print the withheld-offer reason (Step 4, sub-step 6)

This fallback also applies
when the runner exposes no task-tracking tool or the exposed one is disabled or unusable.

Mark each slot in_progress when you start it and completed only when done — the canonical status
vocabulary; a task tool whose status fields differ uses its nearest equivalents, and the inline
fallback expresses the same transitions with the three status markers
`references/fallback-no-task-tool.md` defines. The issue is created only after the user explicitly
confirms the rendered draft (slot 6) — never before. A finished `/prflow:docs-verify` report is
only slot 1. Unconfirmed, the pipeline is paused at slot 6, not complete. Slot 7 runs only after a
successful creation: it is the post-creation hand-off, not a gate on creating the issue.

## Announcement

Your run's first line of output names this skill and confirms the seven tracked slots exist —
for example: "Running /prflow:create-issue; the seven-slot completion tracker is set up." That
makes an omitted checklist visible in the first line of output rather than inferable from its
later absence.

## Iron Law

**Every run executes the full seven-step pipeline to a created-or-paused issue; no run abbreviates, skips, or downgrades a step.**

No exceptions:

- A shortened pipeline is not a pipeline.
- Announcing an abbreviation does not authorize it.
- Cost is not a gate.
- The absence of a user does not excuse an artifact no user is needed for.
- Confidence in the draft is what the later steps test.

## Red Flags

Each entry is a thought to catch yourself having mid-run. Noticing one means you are rationalizing
a skip — stop and run the full step.

- "This ticket is trivial, so a lighter pass is fine."
- "I'll be honest that I abbreviated, so it is acceptable."
- "The docs-verify dispatch is expensive; I'll skip it."
- "There is no user here, so the clarification or approval step cannot run."
- "I already have a solid draft; more grounding is wasted effort."
- "There is no draft yet, so the audit has nothing to check."
- "Let me just render the draft and report, to be efficient."

## Rationalizations

| **Excuse** | **Why it does not hold** |
| --- | --- |
| "I'm being asked to do a full 7-step pipeline for a trivial one-line ticket" | Triviality is a claim the pipeline tests, not a fact you may assume; the steelman and audit exist to catch the one-line ticket that was not trivial. |
| "Let me do a reasonable, abbreviated pass and be honest" | Announcing an abbreviation does not authorize it, and a shortened pipeline is not a pipeline. |
| "Step 1 says dispatch docs-verify peers. That's expensive." | Cost is not a gate. Step 1 grounds every later claim; skipping it drafts blind. |
| "Given time pressure I should still do this properly-ish" | "Properly-ish" is the abbreviation this law forbids; run the step, or record what genuinely cannot be resolved in the Blocked section. |
| "no user available" | The absence of a user does not excuse an artifact no user is needed for; self-answer from the issue's own material where the run is non-interactive and continue. |
| "Enough grounding. I have a solid draft." | Confidence in the draft is what the later steps test; the audit runs precisely on the drafts that feel solid. |
| "I'll skip the audit subagent since there's no draft to audit" | There is always a draft to audit at Step 3.6 — Step 3 produced it — so the audit is never vacuous. |
| "Let me be efficient — render the draft and report" | Rendering and reporting is not creating; the pipeline ends at a created-or-paused issue, not a report. |

## Core principle

An issue is the output of resolved decisions — not a place to park unresolved ones.

Every decision a developer would otherwise have to guess at MUST be resolved by asking the user
*before* the issue is written. Whatever the user genuinely will not or cannot resolve goes into one
explicit Blocked section — never disguised as an "option", a "recommended approach", an "Open
Question", a default, or conditional wording scattered through the body.

## Consumer prompt extension (load first)

Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh create-issue
```

Four outcomes. A missing helper path (`No such file`, exit 127, or the platform equivalent —
e.g. `The system cannot find the path specified` on Windows shells, or a localized message) is the
anchor-resolution failure described in `## Runner setup` below — fix the anchor, do not report a
missing extension. Otherwise, on a non-zero exit where the helper runs but fails,
a consumer extension exists but could not be loaded: surface its stderr message, never silently
proceed as if none existed. Exit 0 with text is consumer-owned customization under `.prflow/prompt-extensions/` —
treat it as instructions appended to the end of this skill's own prompt for this run. Exit 0, no
output: proceed unchanged.

## Reference routing

The per-step procedures and the conditional fallback arms live in `references/`, loaded at their
trigger. Build a reference's path from this skill's directory per the *Portable helper anchor*
rules in `## Runner setup` below and read it with the runner's file-read tool — never a new shell invocation. A load is
accepted only when the file's first line is its `start` boundary marker and its last line is the
matching `end` marker, each naming that file's own path, with exactly one of each.

**Every load failure degrades, and no failure arm terminates the run.** On an unreadable or absent file, an empty file, a missing / duplicated / foreign-path marker, or a truncated read, emit an in-chat breadcrumb naming the file and the failure kind, then continue on that file's degraded behavior. The five non-degradable invariants stated below hold on every degraded arm.

**Which file loads on which trigger — and the degraded behavior each failed load falls back on — is enumerated in `references/degradation-routing.md`.** Load it (per the boundary-marker rule above) on either of two triggers: when a reference load fails and you need its degraded behavior, and when one of its predicate-gated fallback conditions fires on an otherwise healthy run.

**If `references/degradation-routing.md` itself fails to load**, its routing row is unavailable for the reference that needed it: proceed inline for that step, using the Definition-of-Ready summary and section list in the completion checklist above, disclose the reduced coverage in chat, and do not terminate the run. The five non-degradable invariants below still hold.

## Non-degradable invariants

These five hold on every path, including every degraded arm above, and are load-independent of any reference:

1. **The issue is created only after the user explicitly approves the full rendered draft in chat.** The full title and body are rendered verbatim in your message first; an earlier "just create it", a complete Step 2, or a paused pipeline is never a substitute for approval of *this* draft.
2. **The no-options gate** (stated under Step 3 below) passes on the body that is shown and on every revision of it.
3. **The audit summary line is mandatory and always renders** — even on a clean `VERDICT: FILE` with zero findings. A skipped or degraded audit is never silent; the summary line is the evidence the audit ran and which arm it took.
4. **The reserved `PRFlow` provenance label is applied best-effort after creation, and any degradation is reported explicitly** — a label hiccup never blocks creation, and a `PRFlow` label that could not be applied is named in the final outcome rather than passed over.
5. **The self-assignment election is resolved before creation, on every path including every degraded arm.** It is asked in the same pause as the approval question, so the user answers both at once rather than in two consecutive pauses; an explicit yes adds `--assignee "@me"`, an explicit no creates it unassigned, and silence or any non-yes/non-no reply pauses and re-asks — no issue-creation command runs until the answer is an explicit yes or no, whatever the approval answer was. This election belongs to the interactive create path only; a draft-only request never reaches it.

## Subagent dispatch is user-requested here (injection-condition clause)

Invoking `/prflow:create-issue` is the user's request for subagent dispatch at this skill's two
dispatch sites — the Step 1 `/prflow:docs-verify` peers and the Step 3.6 fresh-context audit
subagent — thereby satisfying any injected "do not call the AgentTool unless the user requested it"
condition there and nowhere else. It changes no degradation arm above: a dispatch that fails, is
unavailable, or is refused still degrades onto its named fallback, and nothing blocks issue creation.

## Prerequisites

If `$ARGUMENTS` is empty, ask the user to describe their user story, bug report, or feature idea before proceeding.

## Steps

### Step 1: Assess current state (read-only)

Dispatch `/prflow:docs-verify --report-only` peers on the topic extracted from the user story.

Bind the slug, then clear state — before any dispatch. Bind this run's kebab-case slug here; no
later step binds one. Delete any `.prflow/tmp/issue-step1-<slug>.md`, and delete-and-rewrite the
fixed slug-independent pointer `.prflow/tmp/issue-run-slug` holding this slug.
Both deletes run on every path including the degraded one; a failed delete leaves a possibly-stale
leftover and routes to `references/fallback-read-only-sandbox.md`'s distrust-the-on-disk-copy row.
The pointer, like the evidence artifact, is anchored to the working directory (the worktree cwd),
not to `resolve-main-root.sh`'s MAIN_ROOT, and its content is exactly one kebab-case slug on one line.
Later sites lacking the slug read that pointer; a pointer that is absent, unreadable, empty,
whitespace-only, or not that single-slug shape is recorded unestablished and routes to the
title-derived fallback `references/step-4-present-create.md` retains — never a slug composed from a
partial read.
Disclosed residual: the pointer carries no run-identity token, so a concurrent run in the same
checkout overwrites it and its only reader — having lost turn-one context — holds no comparand that
would detect the swap.

Two arms, selected before any dispatch by a pre-pass operand: the duty-floor duties you judge the
topic to engage. Derive it — and any value deciding which leg ran — with python3 or bash builtins,
never `tr`, `sed`, `wc`, `cut` or `head`, which preflight does not guarantee and whose absence fails open.

- Shallow — fewer than the full floor, and the arm for a topic engaging no duty: one dispatched peer over the union of the deep legs, enumerated from the git index.
- Deep — the full floor, entered directly: two parallel dispatched peers over those legs separately.

Both arms dispatch rather than run inline, so survey tool output stays in a peer's context; no git history is read.

Legs disjoint by construction: the location resolved from `.docs.internal`, and the tracked tree
minus that location's subtree — never an assertion they are already disjoint.
Both enumerate from the index, and each reaches its peer as docs-verify's search-space operand,
never as dispatch-prompt prose its own contract overrides. The duty floor, not the space's size,
bounds each peer.

The orchestrator reconciles both returns. An empty documentation leg is an established absence only
when the location itself is absent.
Record unestablished when the location exists and the read fails, and equally when it exists and
reads cleanly yet holds no git-index entries (an absolute path, a parent escape, a symlink, an
untracked docs tree — the schema forbids none), so claim no documentation coverage rather than a
clean absence.
Unequal returns — one peer returning, one failing — degrade to the surviving leg with a breadcrumb
naming the failed leg, never reporting a partial verification as complete.
An incomplete return — one that succeeds but omits or malforms its duty statuses, or omits a
bearing observation for a duty it reported `judged-not-engaged` — records that duty unestablished
with a breadcrumb naming the missing field, never a discharged floor.

Escalation shallow→deep is the doc-reliability signal's only role, never the arm selector. Escalate
on `UNRELIABLE` or `ABSENT`, on an unestablished duty, and on any judged-not-engaged duty whose returned
bearing observation is non-empty once the producer's explicit `none-observed` token is excluded —
that field is always present, so escalate on any value other than `none-observed` and record
unestablished (which escalates) when it is absent or unparseable. That comparand is a field of the
report you receive, so the pre-pass judgement does not gate it.

Evidence artifact. The orchestrator — never a peer — writes the returned evidence (reconciled, on
the deep arm) to `.prflow/tmp/issue-step1-<slug>.md`, anchored to the working directory, on both
arms before Step 1 returns. Peers write nothing.
Those findings stay resident in your context and durably held in that artifact, so Step 3 draws on
them by pointer and does not re-quote the findings block into its own output, which only inflates
runtime main-thread context. Step 2's evidence bundle and an escalating deep arm read the artifact.

Degraded arm. A failed, unavailable, or rejected pass — or one whose helper anchor cannot resolve —
degrades to a bounded inline verification with a breadcrumb naming the failure kind, marks its
evidence degraded, and writes its own output to the same artifact path. It never terminates the run
and never presents a half-verification as whole.

Completion-wait discipline (mandatory, mirroring Step 3.6's synchronous dispatch). The docs-verify
findings report must be complete and captured before the first Step 2 clarification question — and,
on a run so complete it asks zero clarifying questions, before Step 3 drafting begins.
When a runner executes `/prflow:docs-verify` as a subagent, that dispatch blocks on the completed
result, and a launch acknowledgment is never treated as the findings report.
Never open Step 2 clarification or Step 3 drafting on the strength of "docs-verify is running":
questions that arrive before the code findings grounding them interrogate the user prematurely.

### Step 2: Clarify until the Definition of Ready is met

Load `references/step-2-clarify.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

### Step 3: Draft the issue and pass the no-options gate

Precondition — the Step 2 derivation-artifact gate applies here too, unconditionally. Drafting
happens on every run but clarification does not, so this is the unconditional backstop for a story
so fully specified that the Step 2 gate's first-question trigger never fired.
Before drafting, confirm `.prflow/tmp/issue-derivation-<slug>.md` exists and holds *this run's*
derivation — or, in a read-only sandbox, rely solely on the visible inline-in-chat stand-in
re-posted in this turn and do not trust any on-disk file (it can only be a stale leftover).
If the artifact is missing or you cannot confirm it is this run's, the independent-derivation pass
was skipped — stop and run it now (Step 2) before drafting.
This equally gates the `## Evidence bundle`: it must be present and axis-complete against the
effective list recomputed here (the second, unconditional site of the *Bundle-coverage gate*); if
it is missing or an axis has no entry, stop and run the evidence-bundle sub-pass now before drafting.

Draft the issue from the context you already hold — the documentation findings from Step 1
(relevant files, current behavior) and the decisions from Step 2 — doing only targeted
verification reads where a specific claim needs confirming.
Do not re-explore the whole codebase; the findings are your map, resident in context and durably
held in `.prflow/tmp/issue-step1-<slug>.md`, so reference them by pointer and do not re-emit the
findings block into your drafting output.
(User-facing decision inputs — the surviving audit findings quoted for the user's Step 3.6/Step 4
election — are authoritative and exempt.)

Before composing the draft prose, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it (an issue is change-describing prose).
Per this skill's degrade-never-terminate contract, a failed load emits a breadcrumb naming the file and the failure kind and you draft without it.

Load `references/issue-template.md` per the *Reference routing* rules above and follow it for the required section structure, the **no-options rule**, the quality checklist, and autolink hygiene, on every entry into this step. Key rules:

- No-options gate (run before showing the draft): re-read the rendered body against the no-options rule. On a healthy run its worked vocabulary, category structure, and full carve-out set live in `references/issue-template.md` (loaded above) — apply them. When that template could not be read, apply the compact semantic fallback — the body carries no unresolved implementation decision outside the rule's permitted locations, and every acceptance criterion is one concrete unconditional assertion — and report in chat that the worked no-options vocabulary was unavailable. If you find an unresolved decision, either ask the user now, or move it verbatim to the Blocked section. Do not proceed to Step 4 until the body is clean.

Drafting produces a candidate issue in your message only — nothing is posted to GitHub in this step. Posting happens in Step 4, and only after the user confirms — but first the draft must survive Step 3.5.


### Step 3.5: Steelman the draft against the code (mandatory, before the user sees it)

Load `references/step-3-5-steelman.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

### Step 3.6: Fresh-context audit (mandatory, before the user sees it)

Load `references/step-3-6-audit.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

### Step 4: Review with the user, then create

Load `references/step-4-present-create.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

## Runner setup

The rules below resolve the bundled-helper path at the point a helper is invoked; they stay here,
below the Steps, because they matter only when a helper path must be resolved.

The portable helper anchor is a single-statement rule. This skill invokes helpers bundled beside it
— `load-prompt-extension.sh`, `issue-audit-state.py` (the audit-lifecycle state owner),
`resolve-main-root.sh`, `ensure-label.sh`, `apply-labels.sh`.
Resolve the skill directory inline, in the same statement that uses it, as
`${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`: the `:-`
form uses `$CLAUDE_SKILL_DIR` only when it is set and non-empty, because the observed
non-Claude-Code failure is an empty variable, not an unset one.
Otherwise substitute the base directory this runner reports in context — e.g. a `Base directory for
this skill:` line. Never capture the anchor into a shell variable that a later statement reads:
some runners' inline-bash marshaling drops a variable assigned in an earlier statement of the same command.

Normalize a Windows-form base directory before substituting it — a POSIX shell cannot use `C:\...`
as-is. Run one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) and
use its output only if the command succeeds and prints a non-empty path — otherwise fall through to
the drive-letter rules exactly as if the tool were absent.
With neither tool: lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and
turn backslashes into `/`. Neither WSL nor MSYS2: use the path unchanged and report that it could
not be normalized. These are `lib/normalize-path.sh`'s rules restated as prompt-time prose, because
the anchor is what locates `lib/`.

An unresolvable anchor degrades; it never stops the run — unlike the other skills' fail-closed stop,
an anchor failure must never block issue creation.
Proceed and let the underlying "No such file" error surface: a `/prflow:docs-verify` pass whose
anchor cannot resolve takes Step 1's degraded arm, and an `issue-audit-state.py` call that produces
no contract output routes to Step 3.6's `state-owner unavailable` fallback.

---

User Story (rough draft): $ARGUMENTS

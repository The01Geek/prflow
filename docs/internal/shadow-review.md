# The `/prflow:review-and-fix` shadow review pass

**Skill:** `skills/review-and-fix/references/shadow-review.md` (Step 2.6 *Shadow review*),
`skills/review-and-fix/references/loop-exit.md` (the Loop Exit *Coverage → Shadow agreement*
section and the chat-output `{shadow status}` rendering) — the step references the thin
`skills/review-and-fix/SKILL.md` root routes to (issue #530)

This doc captures the mechanics of the shadow review pass and the portability constraint that
shapes its design, so the constraint is not re-derived (or re-broken) by a future maintainer who
sees "just run the engine in a fresh subagent" as the obvious simplification. It is not.

Existence-only pin findings use the canonical protected-asset classification documented in
[`docs/internal/implement-skill.md`](implement-skill.md#protected-asset-taxonomy-for-existence-only-pins).

## What the shadow pass is, and why it exists

`/prflow:review-and-fix` wraps `/prflow:review`'s four-phase engine in a fix loop. The loop runs
up to a configurable number of iterations — `prflow_review_and_fix.max_iterations` (default 5),
resolved once at loop start — before exiting with its latest verdict; the shadow pass below is not
counted toward that cap. Which findings the loop routes to the fixer is itself configurable via
`prflow_review_and_fix.fix_severity_threshold` (default `important`): every finding at or above the
threshold (`critical` > `important` > `suggestion`) is fixed and the rest are parked as advisory,
except that every finding that drove the engine's REJECT (at or above
`prflow_review.verdict_severity_threshold`, or via a threshold-independent REJECT class such as the
self-contradicting-diff carve-out) is always in the fix set — so no configuration produces
a REJECT the fixer is configured to ignore. Iterations
inside that loop **share state**: the orchestrator's context window carries prior findings, fix
decisions, and pushback history forward across iterations. That shared state is useful for fixing
(it lets later iterations skip what was already considered) but it **biases** the loop toward
accepting its own prior conclusions — the engine increasingly treats things as "already considered"
rather than re-examining them.

The shadow pass at Step 2.6 is the loop's **audit**: before the loop declares convergence on a
non-REJECT verdict, the engine runs **again** with the loop's accumulated state withheld, and the
two results are compared. This **convergence-time** trigger fires only when the tentative final
verdict is non-REJECT (APPROVE family); a REJECT verdict skips it and goes straight to Loop Exit.
On an `engine_self_modifying` PR the shadow *also* fires on an **early** trigger — once after
iteration 1, regardless of that iteration's verdict (including REJECT) — feeding any new blinded
findings into iteration 2; non-`engine_self_modifying` PRs keep the convergence-time trigger only.
The early pass reuses the same blinded fan-out and is itself uncounted toward the iteration cap (a
promoted iteration 2 it spawns counts, like any promotion). This mirrors what
experienced users already do manually — run `/prflow:review <PR>` after `/prflow:review-and-fix`
— and folds that independent re-review into the loop so a disagreement feeds one more iteration
instead of being left for the human to discover. It directly targets the empirically-observed
"a manual review finds things the fix loop missed" pattern.

## The portability constraint: keep the shadow to a single subagent layer

The natural-looking implementation — dispatch one `general-purpose` subagent and tell it to "run
the whole engine in your fresh context" — **does not work portably**, and the failure is silent.

`/prflow:review`'s engine *fans out to subagents*: Phase 1, Phase 1.5, and Phase 3 dispatch
reviewer/verifier subagents, and Phase 2 dispatches for its agent-path checklist items. A subagent
dispatching its own subagents works on Claude Code today, but **nested dispatch is not portable
across harnesses**: on a harness that withholds it the capability is absent as a *missing tool*,
never an error, so granting the `Agent` tool to the shadow subagent cannot restore it.

So on such a harness a single shadow subagent told to run the engine reaches Phase 3, finds it
cannot launch the reviewer fan-out, and **silently flattens to a degraded single-agent self-check**
that returns a plausible clean `APPROVE`. The audit never actually runs — and a degraded self-check
re-deriving the loop's own answer is the exact false-convergence the step exists to prevent. This
was the danger investigated under issue #57 — real, but wrongly recorded as a fixed harness
property; the actual constraint is cross-harness portability, which warrants keeping the shadow to a
single subagent layer.

### Nested dispatch across harnesses (the single home of this table)

This page is the one place the cross-harness picture and the version facts below are recorded; the
other internal pages point here rather than restate them.

| harness | nested dispatch |
|---|---|
| Claude Code | yes, default depth 3 |
| Copilot CLI | yes, default depth 4 |
| Cursor >=2.5 | yes, capped at exactly 2 launch levels |
| Codex CLI v2 | undocumented |
| VS Code Copilot | only with `chat.subagents.allowInvocationsFromSubagents`, off by default |
| Gemini CLI | no — documented hard block |

Version facts (Claude Code): v2.1.217 disabled nested dispatch by default; v2.1.219 re-enabled it at
depth 3, controlled by `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (counting layers below the main
conversation; a value of 1 disables). Because the capability varies by harness and by version, the
one-subagent-layer rule is a portability floor rather than a claim that nesting never works.

**The fix: the PARENT orchestrator runs the shadow fan-out itself.** The parent *can* dispatch
subagents, so it re-runs `/prflow:review`'s Phases 0 through 4.3 inline — resolving the engine
directory via the ordered, repo-root-anchored candidate list (repo-root `skills/review`, then the
`.prflow/vendor/prflow/` and superseded `.devflow/vendor/devflow/` vendored layouts), binding the
bundle to that located directory, `Read`ing its `SKILL.md` in full under Step 1's completeness
predicate, walking its gated phase references under `phases/` (re-deriving bundle identity and clearing each reference's boundary contract at every entry — a shadow entry is a phase entry), and running every
Phase-3 reviewer normally. (Reading the engine as an inline procedure, rather than invoking it via
the `Skill` tool, is deliberate: `Skill` would run the engine end-to-end including Phase 4.4's
GitHub post, and the loop posts no formal review and no verdict comment. The shadow stops before
Phase 4.4.)
Because it reuses Phase 3.1's launch list and per-agent prompts verbatim, the shadow exercises the
**same reviewer set** a standalone `/prflow:review` would on this diff.

## The dirty-tree backstop: review agents never mutate the working tree

The fan-out the parent runs (and the shadow re-runs verbatim) dispatches advisory reviewers over a
diff. Those agents must be **read-only with respect to the working tree** — a reviewer that edits a
tracked file, runs a live half-revert and forgets to restore it, or stages a change leaves the
orchestrator's tree silently corrupted, which can flip the orchestrator's *own* `assert_pin_unique`
checks to a phantom RED (the failure observed in the `/prflow:implement 186` run). Two coupled
layers close that hole.

**The contract.** Every Phase 3 reviewer covered by this dirty-tree contract must never modify
working-tree source files, the index, HEAD, or branch state. The five fan-out agents
— `code-reviewer`, `silent-failure-hunter`, `comment-analyzer`, `type-design-analyzer`, and
`pr-test-analyzer` — perform any mutation/half-revert verification **on a temporary copy made with
`mktemp`, never in place**. The vendored `requesting-code-review` final pass runs under profiles
where `mktemp` and `git worktree add` are not uniformly available, so it does not attempt mutation
verification; it uses granted read-only history commands and reports the verification limitation
to the orchestrator instead.

**The deterministic backstop (shared engine — the Phase 3 reference under `skills/review/phases/`,
steps 3.1/3.2).** Independently of agent
compliance, the shared engine snapshots the tree with `git status --porcelain -z` immediately
**before** the Phase 3.1 batch (into a temp file — `-z` output carries NUL bytes a bash `$(...)`
variable cannot hold). The snapshot is a fixed repo-local `.prflow/tmp/` file so it survives
the Agent-tool boundary without an unavailable `mktemp` capture. The engine compares it **after**
the batch returns. Before each snapshot write it removes the prior path object, validates a
regular non-symlink result, and retains its object ID only in orchestrator state. Restore scratch is removed before reuse; truncated NUL records and failed path writes skip restoration rather
than treating an empty set as permission to clobber existing edits. On divergence it records an Important
finding with an attributable breadcrumb (never silently discarded) and **restores only the snapshot
delta** — paths clean at snapshot time that became dirty during the dispatch window — computed *by
path column* (status prefix stripped from each `-z` record), so a path the orchestrator had already
modified is left to the human rather than clobbered. The restore is `git checkout HEAD -- <path>`
(from **HEAD**, so a *staged* agent mutation is undone rather than re-materialized from the index),
followed by a tree-state re-check that trusts the re-checked status, not the exit code: a path still
dirty afterward (an untracked or staged-new file) is surfaced per-path, never falsely reported as
restored.

**Why `-z` matters.** Plain `git status --porcelain` **C-quotes** a path containing a space or
special character (`"my file.txt"`); that quoted token is not a real pathspec, so `git checkout`
matches nothing and the restore is a **silent no-op** while reporting success. `git status
--porcelain -z` emits the path **unquoted and NUL-delimited**, so a spaced/special filename is
restored correctly. A rename/copy under `-z` is a two-record shape (`R  <new>\0<old>\0`); the
snapshot read loops consume the bare orig-path continuation rather than mis-parsing it
(the final restore loop only ever sees the rename-free delta set).

**Fail-closed and read-only-profile no-op.** Both snapshots are rc-checked: a failed before-snapshot
**disables** the backstop for that dispatch (it never restores off an empty baseline, which would
authorize `git checkout` against the orchestrator's own live edits), and a failed after-snapshot is
surfaced as a *distinct* breadcrumb rather than misattributed as an agent mutation. In the read-only
`/prflow:review` profile the agents are **contractually read-only** and normally leave matching
snapshots; the backstop still detects a contract violation and also earns its keep in the write-enabled `/prflow:review-and-fix` and
`/prflow:implement` tiers — including the shadow pass, which re-runs these phases verbatim.

**Residuals it does NOT auto-restore.** (1) A **true rename/copy** (status `R`/`C`) — undoing a
staged rename safely needs index surgery, so it is *surfaced* (named in a breadcrumb) and left for
the human + the shadow. (2) An agent's further edit to an **already-dirty path that does not change
its status byte** — it produces an identical `-z` record, so the divergence test cannot detect it.
Both residuals fall to the shadow pass + the post-shadow edit gate.

## Where independence comes from: per-reviewer prompt blinding, not subagent-context isolation

The old design's independence story was "the shadow subagent's fresh context window has no access
to the loop's state." Once the parent runs the fan-out, **the parent's own context is no longer
blind** — it carries the iter history. Independence therefore moves into the **reviewer prompts**.
Prior-findings leakage is one channel. Topic-priming is a second, distinct channel: even without pasted
findings, an orchestrator-added request to focus or prioritize a surface steers what the reviewer looks
for. This is the **inverse** of the loop's normal iter-N≥2 fix-delta handoff:

- The shadow does **not** run the fix-delta handoff and does **not** pass `prior_phase3_findings` /
  `prior_checklist` / `fix_files` into any shadow phase.
- The shadow does **not** prepend `/prflow:review`'s Phase 3.1 "Prior-findings context (fix-loop
  callers only)" block to any reviewer prompt, and passes `"none"` for the general-purpose
  final-pass reviewer's "Prior-iteration findings (already considered, look for new)" line. That
  "already considered" handoff is correct for a normal fix iteration but **defeats the shadow's
  purpose** — reintroducing it turns the audit back into a self-check.

Every shadow-pass subagent prompt the parent composes uses the engine's verbatim per-agent prompt,
plus consumer prompt-extension text whose provenance is classified before any shadow dispatch, plus only the
shadow engine's own run-scoped full-diff artifacts and permitted repository paths. Provenance-clean
extension text is permitted composition; extension text that fails either check remains loaded but
is recorded as an addendum, so it cannot produce an attested clean result. This covers Phase 1 checklist-generators, the
Phase 1.5 deduper, Phase 2 agent-mode verifiers, Phase 3 reviewers including the final-pass reviewer,
and tripwire-widened late dispatches under either shadow trigger. The parent adds no focus,
prioritization, or scoping clause. The Step 3.5 fix-delta gate and Loop Exit post-shadow delta-review
are explicitly delta-scoped by design, so their delta scope is not an addendum.

Extension provenance is checked without a base-ref read: `git status --porcelain -- <path>` must
exit successfully with empty output, and the readable run-cached changed-file list must omit the
extension path. That limitation now defines what the check is *for*. Where the dispatching
environment materializes prompt extensions from a trusted base ref before the review begins — as the
cloud tiers that run the review engine do (issue #874, extended to `devflow.yml`'s shipped `command`
job by issue #1075) — provenance is enforced structurally and these checks add nothing. They remain
the sole provenance control on a run whose environment materializes no such trusted directory: a
local or interactive run, where nothing is materialized and Step 0.5's pull-request-head checkout
lands in the very working tree the loader reads; and a dispatching environment that does point the
loader at a trusted directory but whose bundled loader is too old to honor that pointer and
therefore still resolves the working tree. Read them as covering that case only, never as covering
the structural boundary. The control stays advisory: the extension is still
loaded when either check fails or either operand cannot be established, but the local-status,
reviewed-diff, or provenance-not-established failure is named in `prompt_addenda`. An error or
unreadable input never defaults to provenance-clean.
Likewise, the only permitted diff files are Phase 0.2's `diff.patch` and Phase 1's batch slices as the
shadow engine produced them for the full diff. A regenerated, filtered, or subsetted artifact set is
topic steering moved to another channel and is recorded as an addendum.

**Blinding boundary (stated as a contract).** In addition to the prompt classes and permitted
composition above, no shadow prompt carries a workpad path or workpad content. The workpad holds
exactly the loop state this blinding
withholds (iteration history, fix decisions, prior findings), so passing a workpad path — or pasted
workpad content — into a shadow prompt would re-open that channel and turn the audit back into a
self-check. This matters more now that the engine hands diffs to Phase 1 and Phase 3 agents **by
file reference** (the generator receives a `Diff path:` to its batch slice, not inline content, so
the diff never transits the orchestrator's context): the reference-based handoff must not become a
leak channel for the loop state the blinding withholds — the artifacts it hands shadow prompts are
diff files and repo paths only.

**Why the shadow still re-Reads the engine fresh (read-reuse was considered and rejected).** Step
2.6 keeps its mandatory fresh re-Read of the Review bundle (`skills/review/SKILL.md` plus each `phases/*.md` reference it enters) on every shadow pass; skipping it
when the diff does not touch the engine file was considered and **rejected**. The reuse premise —
that Step 1's Read is still verbatim in the parent's context at Step 2.6 — is unverifiable from
skill prose: context compaction on a long run can replace the verbatim copy with a lossy summary,
and the cloud tier's auto-resume machinery restarts runs in a *fresh* context where the Step-1 read
never happened. Executing the engine from a possibly-degraded memory violates the "Read on every
Step 1; never improvise" rule that exists because paraphrase drift caused real historical
divergence, and the failure mode — a silently improvised audit — is invisible. The tokens it would
save are the smallest lever available and do not justify an unverifiable precondition, so the
fresh re-Read stays.

## The honest-degradation fail-safe: coverage is a positively-verified assertion

A degraded pass must **never** clear a PR with a clean verdict. The guard is the shadow block's
`coverage` field, recorded on the workpad (`.prflow/tmp/review/<slug>/<run-id>/iter-<N>.json`, run-scoped):

- **`coverage: "full"` is something the parent *proves*, not the default-on-no-error.** Before it
  may set `"full"`, the parent computes the **expected reviewer roster** for this run and confirms
  the dispatched roster (`reviewers_dispatched`) covers it. The expected roster
  (`expected_reviewers`) is recorded on **every** outcome — including not-verified — so the
  Coverage section can explain *why* a shortfall was a shortfall, and so a gated-out analyzer is
  never confused with a dropped reviewer.
- **The expected roster is mechanical**, and computed from the **shadow's own** Phase 0.5
  classification (the shadow re-runs Phases 0–4.3, producing its own `diff_profile` — a post-fix
  diff can legitimately flip `has_new_types` or the test predicate, so validate against *that*,
  not the loop's last-iter profile):
  - the four **always-on** agents — `prflow:code-reviewer`,
    `prflow:silent-failure-hunter`, `prflow:comment-analyzer`,
    `prflow:requesting-code-review` — unconditionally; **plus**
  - `prflow:type-design-analyzer` iff `has_new_types` is true, and
    `prflow:pr-test-analyzer` iff the test-relevance predicate matches, per
    `/prflow:review`'s Phase 3.1 gates.

  Match a roster member by the agent it names, not by the namespace prefix it is spelled with:
  the pre-rename `devflow:code-reviewer` / `devflow:requesting-code-review` spellings are still
  accepted `agent_overrides` keys and denote the same always-on reviewers as their canonical
  `prflow:` forms, so an override written either way reprices the same roster member and neither
  spelling changes who is expected to return.
- **`engine_self_modifying` adds and removes nothing here.** That flag is a checklist-only
  override — it forces the full checklist but no Phase 3 agent; the four always-on agents are
  roster members on every profile and the two structural-applicability gates decide the rest —
  so the expected roster is still "four always-on + each analyzer whose gate is true." Do not
  force the analyzers into the expected roster on an engine-self-modifying diff; that would
  manufacture a phantom shortfall.
- **`prflow:requesting-code-review` is an always-on shadow-roster member.** The final-pass
  reviewer is a first-party PRFlow skill, so it is always present wherever PRFlow runs — there is
  no companion-plugin-unavailable fall-back to apply. It is an always-on roster member, so a shadow
  pass that dispatched only the other three always-on reviewers (or whose final-pass result was lost)
  is a coverage shortfall like any other. The shadow never declares full coverage on a three-of-four
  roster.
- **A structurally-valid but evidence-empty reviewer response counts as "did not return cleanly."**
  Full coverage requires that every dispatched reviewer returned a result that positively shows it
  ran (an assessment/verdict plus a `defect_signature` on every finding). A reviewer that errored
  internally yet emitted `{findings: []}` with no assessment is not a clean reviewer.
- **Checklist skip is not a coverage shortfall — but a *narrowing* skip is tripped.** If the
  shadow's own Phase 0.5 sets `checklist_skipped = "intentional"` (a `small_diff` + `config_only`
  diff), Phase 1+2 don't run and the shadow's Phase-2 fails are empty *by design*. Coverage is about
  the reviewer roster, not the checklist; record `checklist_skipped` on the block so a reader doesn't
  mistake an empty Phase-2 result for a re-audited checklist axis. The risk a mis-set skip drops the
  checklist axis while the roster join still reads `"full"` is closed by a checklist-axis analogue of
  the roster tripwire below: the shadow's skip is honored **only** when the loop's last-iter
  `checklist_skipped` is *also exactly* `"intentional"`. Every other comparand value trips and forces
  Phase 1+2 to run: the loop *ran* the checklist (`null` — the canonical narrowing), the loop's
  checklist generation *failed* (`"failure"` — it never audited the axis either, so a skip on top
  would leave it unaudited), or the comparand is absent/unparseable/unreadable (fails closed like the
  roster tripwire). Only a skip both profiles independently judged legitimate is honored.
- **Dispatched is not collected — a 1:1 join is required.** `coverage: "full"` requires not only
  that the expected roster was *dispatched* but that each dispatched identifier maps to exactly one
  *collected and successfully-parsed* result — concretely, the per-reviewer assessment/verdict
  evidence captured for that identifier (the positive-return assessment/verdict prose plus a
  `defect_signature` on every finding, the same evidence the coverage bar above names). A
  dispatched-but-lost result (launched, never collected, or unparseable — including an
  evidence-empty return) is a shortfall like a never-dispatched one. "It's in
  `reviewers_dispatched`" is not evidence the reviewer ran.
- **A too-narrow self-classification cannot silently shrink the reviewer roster.** Because the
  expected roster is computed from the shadow's *own* Phase 0.5, an under-classification would shrink
  the expected and dispatched rosters in lockstep and still read `"full"`. A tripwire compares the
  shadow's own expected gated analyzers against the gated analyzers the loop's last iter actually
  launched — read from the recorded `phase3_dispatched` roster, **not** from `diff_profile` (the
  persisted profile carries `has_new_types` but not the test-relevance predicate, so a profile-vs-
  profile check would be blind to a narrowed `pr-test-analyzer`; the dispatched roster records the
  post-gate launch of *both* analyzers): a narrowing divergence widens *both* the expected roster and
  the dispatch to the union of both sides' gated analyzers; a *missing* last-iter `phase3_dispatched`
  (it is a best-effort field) has no second operand to union against, so it trips to the **full gated
  roster** (both gated analyzers) instead. Either way the widening is fail-closed, so a dropped
  analyzer surfaces as a shortfall rather than passing as full. (This guards the gated-*analyzer* dimension; the parallel risk that a mis-set skip drops the
  *checklist* axis is closed by the checklist-skip tripwire above — the two together cover both ways
  a too-narrow self-classification could otherwise read `"full"`.)
- **Block presence is verified, not assumed, before "shadow agreed" fires.** The Step 2.6 workpad
  append is best-effort and can be lost. Outcome 1 (the "shadow agreed" path) re-reads the appended
  block from disk and confirms a present `coverage: "full"` block before committing; a lost write
  falls through to not-verified, exactly as the Loop Exit render sites already fail closed on a
  missing block.

When the fan-out cannot complete — the `Agent` tool is unavailable, the engine SKILL.md is
unreadable or its completeness is unestablished per Step 1, the shadow's Phase 0.5 can't classify the
diff, a reviewer returned nothing / garbage /
evidence-empty, or the dispatched roster falls short for any reason — the parent does **not** fall
back to a single-agent pass and does **not** report a clean verdict. It records
`coverage: "not_verified"` with a `reason` naming what was missing and takes **outcome 3** of
Step 2.6's Decide step: the loop's tentative verdict stands but is reported as *unverified*, never
as agreement.

**`not_verified` is a consequence, never a choice (issue #1230).** A run may not elect it as a budget
decision. A run under cost pressure that could dispatch the shadow dispatches it, and a fan-out that
*was* dispatched and fell short records `not_verified` and its true cause, cost included — the
coverage record reports coverage, not blame. What is refused is a budget or elective cause offered in
place of a dispatch that was never attempted, and a run that never dispatched may not report its
result as independently audited. A run that *cannot* dispatch at all has a named legal state to enter
(issue #1490), so a cost-pressured run is never left reading the prohibition with no state to enter:
a workpad-holding caller (the `/prflow:implement` orchestrator) stops at a non-terminal or `Blocked`
status naming what prevented the fan-out — budget exhaustion included — and a caller with no workpad
(standalone `/prflow:review-and-fix`) reports non-convergence and posts no clean approve-family
verdict. The rule binds the local and cloud tiers identically. The decision
was settled empirically: on the run for issue #1466 (PR #1468) an orchestrator elected `not_verified`
under budget pressure and disclosed it honestly; the shadow, run afterwards on that same converged and
unchanged diff, returned 12 findings with zero overlap with the loop's own pass, four of them genuine
fail-opens in already-shipped code — blinding, not freshness, is what the pass buys, since those
defects were in code the first pass had itself written and blessed. Those counts are a **past-time
snapshot** of that one run, not a live measurement — they are not re-derivable and a later editor
should not refresh them. Enforcement at the
terminal-status boundary is a separate concern tracked by #1453; the rule here is stated on the prompt
surfaces and asserts no terminal-status routing of its own.

**The refusal is no longer shadow-scoped (issue #1489).** #1230 stated it only for the Step 2.6
shadow pass, but a run cannot establish its own remaining context on **any** tier, so a self-assessed
budget or context state is an *unestablished measurement*, never a fact, and never a basis for a
verification decision. The prohibition now binds **every** mandated verification step of the fix loop
and of implement Phase 3 — the reviewer roster, the checklist generate/dedupe/verify steps, the
bounded re-review, and the shadow — with no tier-specific carve-out: none may be skipped, narrowed,
deferred or degraded on a self-assessed budget premise. The legal exit is unchanged and stated where
each refusal lives: perform the step, or stop at a non-terminal/`Blocked` status naming the step not
performed. Because the reduction is *chosen* inside the dispatch-deciding phase references
(`skills/review/phases/phase-2-verification.md` for the checklist, `phase-3-agents.md` for the
roster), each states this application of the general rule at its own decision point, so the rule is
loaded where a run elects the reduction rather than in a phase it has already left.

One bounded exception applies before outcome 3 is recorded (Step 2.6's *Transient vs. structural*
rule): a **single** dispatched reviewer that returned garbage / empty while the rest of the roster
returned cleanly gets **exactly one** targeted re-dispatch first; only if that retry also fails (or
does not return) is `not_verified` recorded. That single retry is **global to the whole shadow pass**
(the initial fan-out and any tripwire-widened late reviewer dispatches share the one budget) and
covers **Phase-3 reviewers only** — Phase 1+2 work a tripped checklist re-run forces is engine phase
dispatch, not a reviewer retry. (A forced checklist re-audit that cannot complete still fails closed:
it surfaces as a Phase-2 INCONCLUSIVE, which drives the shadow's verdict to REJECT per the engine's
verdict mapping, which the loop promotes into another iteration — so a degraded re-audit never reads
clean.) **Structural** failures (the `Agent` tool unavailable,
the engine SKILL.md unreadable or its completeness unestablished per Step 1, Phase 0.5 unable to
classify) and any **multi-reviewer** failure are
immediate `not_verified` with no retry — they will not recover on a re-run. This is a single bounded
retry, not a fall-back to the lenient "treat as inconclusive and proceed" path.

### Fail-closed on coverage, block presence, and prompt composition

Coverage remains a pure reviewer-roster measurement. Prompt composition is fail-closed as a separate operand:

1. **Value:** any `coverage` other than a positively-verified `"full"` — including `"not_verified"`,
   `null`, unset, or unrecognized — is treated as `"not_verified"` everywhere downstream.
2. **Block presence:** the Step 2.6 workpad append is best-effort and can fail. If the final
   verdict is non-REJECT but **no** iteration has a `shadow` block at all, that is treated exactly
   as not-verified.
3. **Prompt composition:** clean convergence and the clean-agreement renders require a present block
   carrying both `coverage: "full"` and `prompt_addenda: "none"`. An addenda array names the recorded
   additions in the not-verified rendering; an absent field renders `attestation not recorded`, never
   an accusation of steering. Outcome 1 re-reads both persisted operands, repairing an absent
   attestation once only while the composing context can still record the truthful value.

The attestation never gates outcome 2 and never changes `coverage`. A full-roster pass that surfaces
new Critical/Important findings promotes them unchanged even with addenda, preserving the attestation
on the block. A full-roster pass with nothing to promote but no `"none"` attestation keeps
`coverage: "full"`, records `verdict: null` and a reason, and follows the outcome-3 downstream
treatment: the tentative verdict stands but is not independently verified.

The chat headline and the report's `## Coverage → Shadow agreement` section both state explicitly
whether the shadow ran with full coverage and attested prompt composition or was not verified,
rendering `shadow agreed, full coverage` only for a present block with both required operands and
`shadow agreement not verified` otherwise (dropping
the absolute "All checks approved." / "with caveats." clause when not verified, so the headline
never overclaims relative to its own parenthetical). The separate
`APPROVE WITH UNRESOLVED SHADOW FINDINGS` verdict — outcome 2 hitting the iteration cap — *normally*
carries `coverage: "full"` (the shadow ran fully and *disagreed*) and uses its own dedicated line; it
is never routed through the `{shadow status}` template. That dedicated line carries its own
render-time coverage assertion: an ordinary shadow promotion reads the promotion-triggering block
one iteration back, while a parked-class sweep finding discovered at the cap reads the current triggering iteration.
The selected block was written by the same best-effort append that can be lost, so when it is absent
or not `"full"` the line falls back to a not-verified rendering rather than asserting a shadow result
the persisted record can't back. An addenda array or absent attestation on the selected block adds a
caveat to the dedicated line and Coverage entry without changing the verdict. The headline and the
report's Coverage section both pin to that same selected block (never an earlier iteration's block)
and evaluate the lost-write branch before the `"full"` branch, so a lost selected block can't make
the report read "full coverage" while the headline reads "not verified."

`APPROVE WITH UNRESOLVED SHADOW FINDINGS` is terminal *for the loop* — it is at the iteration cap and
will not re-review itself. The ordinary shadow-promotion arm carries unresolved Important findings;
the sweep-at-cap arm carries unresolved non-Critical siblings at or above `$FIX_THRESHOLD` (which can
include Suggestion when that threshold is configured). They surface only in chat and the report's
arm-specific section: `## Unresolved Shadow Findings` for an ordinary shadow promotion, or
`## Unresolved Parked-Class Sweep Findings` for sweep-at-cap. A wrapping orchestrator (e.g. `/prflow:implement`) that
chooses to *fix* those findings must re-establish independent coverage by re-running the loop once
over the fix delta; it must not resolve them with an unreviewed final commit. Otherwise the very edit
that answers the shadow ships with no independent eyes on it — the gap this contract closes.

## Calibration: "shadow agreed, full coverage" is not "nothing left to find"

The in-loop shadow pass **narrows** the gap between the fix loop's self-assessment and an
independent review — it does not **close** it. Read the strongest possible shadow result,
`shadow agreed, full coverage`, for exactly what it asserts: *a fresh in-loop sample, run with the
loop's prior findings withheld from each reviewer prompt, surfaced nothing new this pass.* It does
**not** assert that there is nothing left to find.

Two structural reasons the gap persists:

- **It is one sample, not a different reviewer population.** The shadow re-runs the *same* engine
  and the *same* reviewer roster the loop already used; blinding the prompts removes the
  *already-considered* bias but not the reviewers' shared blind spots. A genuinely independent
  standalone `/prflow:review` — a separate session, separate accumulated context — samples the
  space differently and routinely finds things a single in-loop re-sample does not.
- **The shadow runs against the loop's own accumulated context.** The parent orchestrator that runs
  the fan-out still carries the iter history; only the per-reviewer prompts are blind. That residual
  shared state is a far smaller bias than a degraded single-agent self-check, but it is not zero.

**Evidence.** On PR #58 (issue #57) itself — the PR that made the shadow pass parent-orchestrated and
fail-closed — the in-loop shadow agreed with full coverage, yet a subsequent standalone
`/prflow:review` run surfaced several hardening items the in-loop shadow had not caught (none Critical;
they became the follow-up tracked in issue #61). That is the calibration in a single data point:
"shadow agreed, full coverage" meant the in-loop re-sample found nothing new, **not** that the PR
was exhaustively reviewed.

The practical consequence: a clean shadow result is a real signal that the loop converged honestly,
but the human gate — and, for a formal merge signal, a separate `/prflow:review <PR>` run — remains
the exhaustiveness check. A clean shadow *raises confidence* in that gate's outcome; it is never a
criterion for *waiving* it. Treat the separate independent review as the default, not as something a
clean shadow makes optional.

### The highest-risk clean shadow: a diff that changes the review/coverage/gate logic itself

The generic calibration above has a sharpest edge, and it is the one this loop keeps getting wrong:
**when the diff is `engine_self_modifying` and what it modifies is the review engine's own
coverage-, gate-, or shadow-pass logic, a clean in-loop shadow is the *least* trustworthy clean
shadow there is — never read it as sufficient, and require a separate standalone `/prflow:review`
before merge.** The "shared blind spot" of the two bullets above is not a constant here; it is
maximal precisely on this diff shape, because the reviewers are being asked to audit the very
gate/coverage logic the change is rewriting, using a roster that shares whatever blind spot the new
logic is supposed to close. A fail-open hole in a new tripwire, an under-specified verdict-precedence
rule, a coverage join that reads `"full"` over a roster that silently shrank — these are exactly the
defects a clean shadow is structurally weakest at catching, because catching them requires reasoning
*about* the gate rather than *through* it.

This is not hypothetical and not a one-off:

- **PR #62 (issue #61), the hardening spec for the shadow-coverage invariants themselves.** The
  in-loop shadow reported clean; a subsequent standalone `/prflow:review` returned **REJECT** on a
  Critical fail-open — the roster too-narrow tripwire keyed on the wrong persisted signal (it
  compared `diff_profile`, which never stored the test-relevance predicate, so a narrowed
  `pr-test-analyzer` gate read `coverage: "full"` over a shrunken roster). It took twelve substantive
  human follow-up commits across two review cycles to actually defend `coverage: "full"`. The clean
  shadow was honest about what it asserts (the in-loop re-sample found nothing new) and useless as a
  merge signal for this diff shape.
- **PR #104 (issue #100), the `scan.sh` retrospectives-decode hardening.** A finding *both* review
  passes flagged — the `_decode_existing` zero-record breadcrumb over-claims "from non-empty content"
  on the `download_url` transport, which has no non-empty precondition — was parked as a non-blocking
  advisory and shipped unfixed, with no test pinning the `download_url` empty/whitespace-body shape.
  Parking advisories is legitimate by design (see "Advisory findings" in the skill), but on an
  engine-self-modifying diff a *repeatedly-flagged* breadcrumb-accuracy defect in the engine's own
  best-effort parser is the bug class CLAUDE.md singles out — it warrants fixing or an explicit
  standalone-review pass, not silent advisory carry-through.

So the rule, stated operationally: **a clean in-loop shadow does not clear an `engine_self_modifying`
diff that touches review/coverage/gate logic for merge — schedule the separate standalone
`/prflow:review` and resolve its findings first.** The standalone review is mandatory here, not
"default but waivable on a clean shadow." **The `engine_self_modifying` set that keys this rule is the three-arm one Phase 0.5 defines** — DevFlow's own source (`skills/**`/`agents/**`/`lib/**`), a prompt extension under the `.prflow/`/`.devflow/` state directory ending in `.md` at any depth, and a file whose basename is `CLAUDE.md` at any depth — so this highest-risk-clean-shadow rule now **does** fire on a diff that edits the review engine's own appended prompt (a prompt extension) or its root instruction file (`CLAUDE.md`), which it did not before that set was widened. (This narrows nothing for ordinary product-code diffs,
where the shared-blind-spot risk is lower and the standalone review remains the *recommended*
default rather than a hard pre-merge gate — see the Counterfactual note this calibration was
strengthened under.) The two sub-patterns above both fall under the `lenient-verdict` category (a gate ran and returned an
approve-family verdict while a defect it should have caught shipped — for PR #62 the in-loop shadow's
clean verdict over a Critical the standalone review later flagged; for PR #104 a repeatedly-flagged
advisory parked and shipped unfixed); this calibration addresses the dominant one (the
engine-self-modifying clean shadow that a real gate later caught). It does **not** change the advisory-parking mechanics themselves — a repeatedly-flagged
advisory on an engine diff is surfaced here as a case the mandatory standalone review must catch, not
re-litigated as a new auto-fix rule.

### The mechanical layer beneath this calibration (issue #155)

The calibration above is a *judgment* rule — read a clean shadow skeptically on an
engine-self-modifying diff, and route to a standalone review. PR #154 showed why judgment alone is
not enough: its in-loop shadow agreed with full coverage, and it *still* shipped a **vacuous drift
guard** — a `grep -qF` whole-file scan pinned to a literal that also appeared outside the gate, so the
guard stayed GREEN even with the gate it claimed to protect deleted. Wherever a deterministic check is
possible, the defense is now **mechanical**: it lives in `lib/test/run.sh` and fires whenever the suite
runs (CI on every push, or locally) — not in real time mid-loop — so it catches the regression at
suite/CI time no matter whether the loop that produced the diff was driven by the skill or by hand:

- **Target-uniqueness guard (`assert_pin_unique`).** Every SKILL presence-pin across the suite now
  asserts its literal occurs *exactly once* in the resolved SKILL — a duplicated or absent literal fails
  the suite, closing the whole-file-scan hole that let PR #154's guard pass. Originally scoped to the
  park-calibration region, the enforcement is now **repo-wide** (issue #157): the raw `grep -qF`
  presence-pins throughout `lib/test/run.sh` were converted to `assert_pin_unique`, and the guards that
  genuinely can't route through it (non-unique-by-design count assertions, absence pins, case-insensitive
  or loop-variable targets, `--`-leading literals) each carry a `# raw-guard-ok: <reason>` allowlist
  marker. A repo-wide self-scanning meta-test (`count_unallowlisted_raw_skill_guards`) fails if a
  *single-line, echo-driven* raw `grep`-based SKILL guard — any flag spelling, against a `_SKILL` var, a
  `SKILL_`-suffixed loop var, or a literal `…/SKILL.md` path — exists anywhere in the suite without either
  routing through the helper or carrying a properly-formatted allowlist marker. An in-region control
  (`count_region_nonhelper_stmts`) additionally requires every park-calibration region statement to route
  through the helper. The scan itself cannot go vacuous because the pre-existing #155 marker-presence pins
  (the `PARKCAL_GUARD_REGION` BEGIN/END `pin_count == 1` asserts) fail closed if the region markers are
  deleted — `region_lines()` is merely the shared extractor, not the fail-closed control. All are
  mutation-proven: the suite goes RED on a deliberately non-unique pin, on an unallowlisted raw bypass
  guard anywhere in the suite, and on a deleted region marker. Scope caveat: the audit covers
  SKILL-*targeted* guards (a grep against a `_SKILL`/`SKILL_` var or a `…/SKILL.md` path); an identical
  vacuous-whole-file-presence guard against a non-SKILL target is out of scope.
- **Sentinel-completeness signal.** The park-calibration gate (Step 2.6) records a mandatory
  `## Devflow Reflection` bullet on every run — a re-grade routing or the gate-clean sentinel.
  `lib/test/run.sh` pins that sentinel contract, and the `/prflow:review-and-fix` Loop-Exit machinery
  now treats an APPROVE-family conclusion with **no** sentinel/re-grade bullet as *non-convergence* (the
  gate did not run to completion). Combined with the explicit firing-site handoffs at Decide outcome 1
  and the Step 4.5 early-exit, a manually-driven loop can no longer reach an APPROVE-family verdict while
  silently skipping the gate.

These are a *backstop beneath* the prose calibration, not a replacement for it: the mechanical guards
catch a vacuous guard or a skipped gate deterministically, but the judgment rule above — read a clean
engine-self-modifying shadow skeptically and run the standalone review — still governs the cases no
local check can decide. The target-uniqueness guard is also the deterministic, guarantee-class form of
the prose "pin a *target-unique* phrase" advice in the mutation-check rule.

The test-first rule carries two further requirements beyond "break it and watch it go
RED," shared between the implement gate (`skills/implement/phases/phase-2-sweeps-contract.md`)
and the fix loop (`skills/review-and-fix/references/fixing.md` Step 3). First,
**bake the behavioral proof into the suite**: exercise the rendered interface or
machine-observable contract with an ordinary executable test, break the behavior in
a scratch fixture, and observe that test go RED. Wording-only presence pins remain
prohibited. A permitted static machine-boundary pin carries
`# structural-pin-ok: <category> -- <non-empty rationale>` with a category from the
closed structural set. The retired mutation-taking helper census and checked-in
inventory must remain empty, and enumeration failures fail closed.
Second, **confirm the guard
registered**: a green suite is not evidence a guard *ran*, so after adding any guard, confirm its named
assertion appears in the run as a PASS *and* that the suite's assertion count rose by what was added — a
guard that silently no-ops (an assertion helper invoked before it is defined, a test file the runner
never sources, a setup probe that returns success on failure) asserts nothing while the suite stays
green.

### Calibration is symmetric: the under-grade gate and the over-grade gate are two halves of one defense

The calibration above is about the loop grading a finding **too low** (a real defect parked as a note that a later standalone review re-raises). That is one direction; the loop can also grade a finding **too high**, and the engine defends both directions with a matched pair of gates in `skills/review-and-fix/references/shadow-review.md` that share one root idea — *never trust an emitted severity without a recorded technical evaluation against the finding's observable fail-direction and impact*:

- **Under-grade — the park-calibration gate**, on the **approve** path (before a Decide outcome-1 / Step 4.5 early-exit conclusion). It re-reads parked findings against the under-grade shapes and **promotes** any it catches back through Step 2.5 → Step 3, so a substantive finding cannot ride out as a note.
- **Over-grade — the over-grade calibration gate**, on the **promote** path (before a Decide outcome-2 promotion fires on an emitted `Critical`/`Important` shadow finding). It **flags** a suspected over-grade against the *observable* over-grade shapes, whose **single definition** lives in the shared engine (`skills/review/phases/phase-4-verdict.md` Phase 4.1.5, *Over-grade advisory annotation*) and is consumed by both skills rather than forked — read the numbered shapes and their fail-direction qualifications there, which is what the shape ordinals below refer to — so the loop does not spend a full extra engine pass (a promoted iteration plus a re-shadow) on an unexamined label.

**Standalone `/prflow:review` annotates, but never demotes (issue #195).** The over-grade shapes are defined once in the shared engine (`skills/review/phases/phase-4-verdict.md` Phase 4.1.5), so standalone `/prflow:review` — which runs the same Phases 0–4.3 but has **no fixer** to record a `severity-calibrated` evaluation — applies the same shapes as an **advisory annotation only**: it appends a "suspected over-grade: shape *n* — observable fail-direction is *X*" note to the matching finding's line in its report and **leaves the verdict computation untouched** — with one deterministic exception (the behavior-inert prose cap, below). For the advisory-annotation shapes the annotation never demotes a finding, never alters its severity, and never clears or downgrades a REJECT — a flagged `Critical` still drives REJECT. Its sole guarantee is to let a human reading a bare standalone-review REJECT distinguish a genuine blocker from a diminishing-returns over-grade without re-deriving the calibration. The full **flag-and-record** gate (recorded evaluation required, non-convergence enforcement) remains fix-loop-only, because only the loop has a fixer to record the evaluation.

**One deterministic exception — the behavior-inert prose cap.** Shape 2's behavior-inert sub-case is a *classification* rule, not an advisory annotation: a finding whose sole observable impact is the prose itself, on prose that cannot change what the program does, is deterministically capped at Suggestion/Minor and does **not** drive a Phase 4.2 REJECT, regardless of the grade a review agent assigned — and **whether the diff touched the line is not part of the keying**, so a stale ordinal count in a `lib/test/run.sh` comment is graded on whether its own truth value can change what the program does, not on whether this diff happened to touch it and not on the kind of file it sits in. **The first conjunct is keyed on the finding's *subject*:** where what the finding disputes is what a mechanism *covers* — a lint's audited population, a guard's exception net, a validation loop's type coverage, a registry's own descriptive claim about its coverage — the subject is that missing coverage, so the finding is graded on its functional severity and is never capped, including when the gap is described inside a comment or docstring. The limbs still decide each such finding and they fail closed when inertness cannot be established — `run.sh` also carries tool-read comments (`# structural-pin-ok:`, `# raw-guard-ok:`, `# tree-walk-ok:`) that limb one excludes. **`skills/review/phases/phase-4-verdict.md` Phase 4.1.5 is the authoritative definition of behavior-inertness — its subject test and its two limbs are not restated here.** This does not reopen the #195 lenient-verdict hole, because the cap decides, from the finding's subject and that surface's stated consumers under those two limbs, whether the disputed sentence's truth value can change what the program does — never the merits or severity of the finding: a finding carrying any behavioral fail-direction is graded by that fail-direction and is never capped. Standalone `/prflow:review` applies the cap as a classification; `/prflow:review-and-fix`'s Step 2.6 honors it by recording the required `severity-calibrated` evaluation deterministically (evidence = the deterministic behavior-inert prose cap), so a capped finding cannot drive a Decide-outcome-2 promotion.

**The truthfulness partner — the pre-verdict truthfulness sweep (Phase 4.1.6).** The behavior-inert prose cap governs an inaccurate line on prose that cannot change what the program does, diff-touched or not (≤ Suggestion, and so no REJECT at the default `critical` threshold); its partner over prose that *can* change behavior is the **truthfulness sweep**. Shape 2 explicitly **excludes** a false-against-HEAD diff-added/modified doc line, comment, example, or command-form from the cosmetic-wording class — that is a truthfulness defect (a `documented_falsehood`), not a demotable Suggestion — and the sweep enforces it: after the over-grade scan and before the verdict, it runs over **every** Phase-3 finding **regardless of severity chip** (it does *not* inherit the over-grade scan's Critical/Important/Major scope, because a mis-filed falsehood lands at Suggestion). It is **promote-only** — for a finding whose subject is a diff-added/modified artifact, a claim **demonstrated** false against HEAD is routed into the Phase 4.2 self-contradicting-diff carve-out (REJECT) independent of the producing agent's framing and chip — unless the prose is behavior-inert, which the cap covers and the carve-out's scope excludes — while an inconclusive check leaves the finding exactly as filed; it never demotes, downgrades, or clears anything, and a clean pass emits a visible `truthfulness sweep: no finding promoted` line. The sweep also carries a **diff-scan input** — an *intra-diff contradiction scan* that, independent of any finding, cross-products the diff's added absolute claims (a universal — "every", "never", "is caught by the same rule") against its added-or-retained limitation notes about the **same symbol** and files a contradicting pair as a non-demotable `documented_falsehood`; this closes the PR #340 case where a diff published an absolute claim while retaining a contradicting limitation and no agent flagged it, so a per-finding sweep had nothing to iterate over. Like the cap, it is single-sourced in `skills/review/phases/phase-4-verdict.md` Phase 4.1.5/4.1.6 and inherited by both `/prflow:review` and `/prflow:review-and-fix` through the shared engine. This is the same promote-only asymmetry as the under-grade gate: the engine promotes on demonstrated evidence, never auto-demotes on suspicion.

The two gates are deliberately **asymmetric in action but symmetric in intent**. The under-grade gate *promotes*; the over-grade gate **flags and requires a recorded technical evaluation — it never auto-demotes** (the deterministic behavior-inert prose cap above is not a counterexample: it supplies the required recorded evaluation deterministically from the cap's stated properties, rather than from a re-judgment of the finding's merits — so it never auto-demotes an unexamined *suspected* grade), because silently demoting a wrongly-suspected over-grade would re-open the lenient-verdict hole the rest of the engine exists to close. The shared mechanism that makes both auditable is **recording the per-finding technical evaluation as evidence**: the over-grade gate's required artifact is a structured `fix_decisions` entry (`decision: "severity-calibrated"`, citing the observable fail-direction/impact and the calibrated grade), and a flagged promote-path finding with no such recorded evaluation is treated as **non-convergence** at Loop Exit — so a run that skipped the calibration discipline is detectable by the absence of the evidence rather than dependent on actor diligence. This mechanizes the `receiving-code-review` **symmetric-severity-calibration principle** (a genuine finding can be over-graded; calibrate severity against observable fail-direction/impact in both directions): the principle *states* the discipline engine-agnostically, the gate *enforces* it.

Empirically (issue #155 / PR #156), a high-verbosity reviewer — `silent-failure-hunter` — repeatedly over-graded fail-closed, diagnostic-only defects `Critical`/`Important` in a single run; the over-grade gate makes the technical evaluation that catches such labels a recorded, detectable engine step rather than a matter of actor diligence.

## The fix-delta verification gate (Step 3.5) — a complementary, per-iteration check (issue #159)

The shadow pass audits the **whole diff** at **convergence** (and, on an `engine_self_modifying` PR, also once after iteration 1 via the early trigger). That leaves one gap it cannot close cheaply: a regression introduced by **a fix itself**, in the iteration that produced it. A fix is new code; it can ship a fresh `unverified-assumption` / #62/#98 instance — a guard whose accepted-input set is **wider than its downstream consumer's contract**, so it fails open exactly where it claims to fail closed. Caught only by a whole-diff shadow pass, such a regression forces the shadow to *promote* a costly extra iteration (PR #153 took three iterations for one issue because iterations 1–2 each re-introduced a weaker-contract guard in their own fix). **Step 3.5** front-loads that detection: after each iteration's fix commit — **every iteration, unconditionally** — the parent dispatches a **blinded subagent** that re-reviews **only that iteration's cumulative fix delta** (`git diff <iter_fix_base>..HEAD`, the iteration's first-fix parent through HEAD, so an inner re-fix can't split the fix across separately-reviewed commits) plus the consumer code it touches, with the loop's prior findings/fix decisions/fixer reasoning withheld — the same blinding model as the shadow's per-reviewer prompts. **"Every iteration, unconditionally" means the gate is not gated on the verdict — it does not manufacture a delta where none exists:** an iteration in which **Step 3 applied no fixes** has no fix delta, so the gate, and every check it carries, **skips** for that iteration and the loop proceeds to Step 4. Its three checks are the #62/#98 operand-contract check (the fix's guard accepted-input set must be a *subset* of its consumer's contract — see the **share-the-contract / parse-don't-validate** principle in `receiving-code-review`), an adversarial input-shape matrix, and the **added-assertion attribution check**. The third asks, of **each assertion the fix delta adds**, whether the assertion *as reported* singles out the regression its own name and description claim it catches — reporting three outcomes: an assertion that would **not change state under the named regression**, one that would **change state under a cause other than** it (typically because the change it depends on destroys the anchor it keys on rather than the behavior it names), and one whose **reported identity does not distinguish it from a sibling arm**, so a result is not attributable to one. An added assertion whose target cannot be read is reported **unestablished**, never clean, and the dispatch scope admits a bounded read of each added assertion's target for that check alone. A new Critical/Important gate finding from the first two checks first passes the over-grade calibration gate (flag + recorded `severity-calibrated` evaluation, never auto-demote), and a re-affirmed one routes back into the same iteration's fix step (capped at 2 inner attempts, then promoted to a cap-counting iteration; at the cap it rides into the shadow's whole-diff audit and a `## Devflow Reflection` bullet). An added-assertion finding is not severity-routed: the assertion is corrected in the same iteration as a swept sibling, or recorded through the item 5 pushback flow, and that disposition **inherits** the same 2-attempt cap, cap-counting promotion, and at-cap shadow carry — so the terminate-under-the-cap guarantee holds for every check the gate carries. Like the shadow, the gate and its inner attempts do **not** count toward `max_iterations`, and a gate-subagent failure gets one bounded re-dispatch before the loop records `fix-delta not verified` and proceeds (a deterministic delta-base failure gets a distinct breadcrumb, no retry). The Step 2.6 shadow pass and the post-shadow edit gate are **unchanged** by Step 3.5.

## Non-blocking severity-aware exit in `/prflow:implement` (issue #159)

`/prflow:implement`'s Phase 3.3 used to treat `APPROVE WITH UNRESOLVED SHADOW FINDINGS` (and a non-clean bounded re-review) as a hard **Blocked** stop — aborting the whole lifecycle after the "two consecutive non-clean passes" of the capped run plus its one bounded re-review. That was too aggressive: it discarded a review-ready PR over findings that, after over-grade calibration, are frequently advisory. Phase 3.3 is now **severity-aware**: only a *genuine unresolved Critical* (or an unparseable/ungradeable verdict, fail-closed) takes the Blocked path; a residual of only advisory / Suggestion / `severity-calibrated`-down / deferrable-Important findings **soft-proceeds** — surfaced durably (workpad `### ⚠️ Action required` reflections, and the PR body where a deferrals manifest exists) while the run continues to Phase 4. The PR ships review-ready, not auto-merged; the human merger decides. This preserves the human gate without throwing away completed work over diminishing-returns nits.

### The completeness critic and the mechanism-scoped re-sweep (issue #167)

PR #164 converged to a clean in-loop self-APPROVE, and a later standalone `/prflow:review` flagged two Important findings the loop had missed — each a recurring high-risk class this section is about: a **vacuous or incomplete audit**, and a **stale comment after a mechanism change**. Two mechanical checks now target them directly. Each is calibrated, not catch-all — read the guarantee-scope paragraphs below for exactly what each does and does not assert.

**The completeness critic (shared engine — the Phase 3 reference under `skills/review/phases/`, step 3.1.5).** When Phase 0.5 classifies the diff as `detect_all_audit` — it adds or changes a scanner / audit / coverage-invariant that *enumerates a population* and *asserts a completeness property* over it — Phase 3.1.5 forces a completeness-critic pass. The pass re-enumerates the audit's target population **by a signal other than the audit's own pattern** and emits a finding for any member of that independent enumeration the audit does not cover. It lives in the shared Phases 0–4.3, so standalone `/prflow:review` and the `/prflow:review-and-fix` fix loop both apply it. It is the engine's answer to the circular-completeness trap: a "detect-all" claim cannot be self-certified by the audit making it — the PR #62 too-narrow tripwire and the PR #154 vacuous drift-guard were both this shape, certified clean by their own output.

*Guarantee scope.* The critic catches an audit that is **not a superset of a genuinely independent enumeration**. **It does not prove the audit is exhaustive:** the independent enumeration is itself reviewer judgment and can share a blind spot with the audit. A clean critic result means "the audit covers everything a second, structurally different enumeration found," not "nothing is uncovered." Like a clean shadow above, it **narrows** the circular-completeness gap; it does not close it.

**The mechanism-scoped self-authored-claim re-sweep (fix loop — `skills/review-and-fix/references/fixing.md` Step 3).** After a fix changes a mechanism (a guard, predicate, exclusion, or helper that comments describe), the fix loop re-runs the `prflow:comment-analyzer` agent over **every** comment describing that mechanism — located by the mechanism's identifiers across the touched files, not limited to the fix's own diff hunks — and treats a comment that still describes the pre-change mechanism as a finding. It **reuses the existing comment-analyzer (no new agent)** and lives only in the fix loop, since standalone review applies no fixes — so the shared engine carries no paraphrase of it.

*Guarantee scope.* The re-sweep covers comments describing the **changed** mechanism within the **touched** files. **It is not a repo-wide comment audit:** it does not catch drift in files the fix never touched, nor a claim that names no shared identifier. It closes the "spot-checked the fix's own hunks and missed a stale comment elsewhere in the same file" gap — nothing wider.

**Parked-class sweep (fix loop — convergence entries).** The fix-triggered class generalization above cannot help when every finding is parked and no fix occurs. Before the convergence-time shadow, the fix loop now derives parked classes from its advisory decisions, unactioned Suggestion/Minor findings, and Yes-downgrade deferrals; it excludes recorded false claims, generalizes the remaining findings by `defect_signature.kind` (routing a missing kind through a bounded `unknown-kind` semantic batch), and scans only the PR diff plus fix-touched files. Every sibling is registered in the triggering iteration's `phase3_findings` before shadow comparison. Siblings at or above `$FIX_THRESHOLD` enter a counted promoted iteration; below-threshold siblings remain visible with a distinct sweep marker. Site overlap—not free-text kind equality—deduplicates cross-producer results.

*Guarantee scope.* This is a class-primed enumeration over known parked classes, not a second independent review. Semantic enumeration is bounded and batched; a failed dispatch is retried once and then reported as not verified. A per-class, clean, not-verified, or downgrade-path-not-applicable Reflection sentinel makes a skipped sweep fail closed at Loop Exit. Running before shadow is deliberate: the blinded pass judges the registered post-sweep population instead of rediscovering siblings one at a time.

### Evidence-aware post-shadow grading of parked findings (issue #557)

A shadow re-raise of an already-parked finding used to re-litigate the parking on **severity alone** — the park-calibration gate declared a last-iteration re-raise mis-graded *at any severity*, and an earlier-iteration parked finding the engine did not re-emit slipped into Decide outcome 2 as "new" and promoted at Important or above. Either arm re-parks the finding on the same rationale in the promoted iteration, the loop re-shadows, and the cycle can repeat until the iteration cap absorbs it — burning promoted iterations (each a full re-shadow) and `APPROVE WITH UNRESOLVED SHADOW FINDINGS` noise on findings the shadow merely *corroborated*. Severity comparison cannot separate corroboration (the shadow independently reached the same parking-worthy judgment on the same evidence) from escalation (the shadow saw something new); only comparing the **evidence** on both sides can.

The fix, in the Park-calibration gate (fix-loop only — the shared `/prflow:review` engine is untouched), grades below-verdict-threshold shadow re-raises on evidence:

- **Precedence.** The scoped sweep-sibling carve-out is evaluated **first**, byte-unchanged; a re-raise it claims never enters the evidence classification. (The carve-out covers the current convergence's registered siblings; a sibling parked at a *prior* convergence flows to the evidence classification.)
- **Scope boundary.** Only re-raises **below** `prflow_review.verdict_severity_threshold` are graded on evidence. A re-raise at or above the threshold drives the blinded shadow's own Phase 4.2 verdict to REJECT, and shadow-REJECT handling is deliberately untouched — such re-raises promote today and keep promoting. The self-contradicting-diff REJECT class keeps today's path at any severity too. The three under-grade shapes (a fail-open guard or coverage hole, an overclaiming breadcrumb/error, and a deferral the matcher will not honor) remain unconditional mis-grade triggers whatever the evidence relation.
- **Populations and pairing.** The parked side is the **reconciled parked population** — the gate's three re-read populations (advisory-parked rows, unactioned Suggestion/Minor findings, Yes-downgrade deferrals) across **all** iterations, **minus** any member a later iteration applied or promoted-and-fixed (the *survived-unfixed reconciliation*, so a fixed-then-regressed defect's re-raise is never read as a preserved parking). A single amendment to Step 2.6's Parse-and-compare novelty definition makes a shadow finding that Phase-3.2-pairs to a member's **parking-time record** count as **overlap, not new** — feeding the `comparison` counts, outcome 1's subset test, and outcome 2's trigger coherently, and routing the pair to the evidence classification. It mirrors the parked-class sweep's registration goal but via a novelty-rule amendment (registration would duplicate carried-forward entries). Populations split into **rationale-bearing** (advisory-parked, Yes-downgrade, `settled-by-disclosure` foreclosures, the sweep sibling) and **rationale-less** (unactioned Suggestion/Minor, row-less or bearing a below-threshold producer row).
- **Taxonomy and operands.** Each pair receives exactly one of five relations — **equivalent**, **strengthened**, **contradicted** (requires a recorded parking rationale, so unreachable for the rationale-less class), **materially different**, **ambiguous**. Rationale-bearing pairs read a structured `parking_evidence {basis, failing_input, source, finding_ref}` object written at parking time by each of its four producers (Step 2.5 demotion; Step 3's item-5 pushback; the sweep's below-threshold-sibling parker; and the `settled-by-disclosure` foreclosure arm — Step 3's item 5 for a fixer-routed finding or Step 2's per-finding arm for a parked one, whose `source` names the disclosure `{path, phrase}` and is re-verified against the tree at comparison time), beside the retained one-line `evidence` string. Rationale-less pairs read the parking-time `phase3_findings` record alone. The uncitable Step 2.5 demotion arm gains a `step25_classification: "tools_unavailable"` value so its uncitable rationale has a real operand on tools-restricted tiers.
- **Dispositions.** Parking is **preserved** only when every paired re-raise is **equivalent** from well-formed operands *(a)*, each at or below the parked severity under a component-wise label normalization (`major`≡`important`, `minor`≡`suggestion`) *(b)*, and — for a rationale-bearing row at or above `$FIX_THRESHOLD` — the rationale is anchored (`source` non-null, or an uncitable `step25_classification` restated in `basis`) *(c)*. Every other outcome takes the **existing mis-grade path**, promoting at the shadow re-raise's severity. The gate **fails closed to promotion** (the pre-change behavior): any missing/malformed/unreadable operand, an unresolvable parked identity, or a signature-less judgment-detected re-raise promotes — silent preservation and silent skip are both non-conforming.
- **Recording, sentinel, retrospective economics.** Each pair is recorded in an additive `park_calibration.evidence_comparisons[]` block on **both** dispositions. A preservation run records the sentinel `park-calibration gate: {N} parking(s) preserved on evidence equivalence` as **note-kind** (ℹ️, retrospective-exempt — healthy corroboration stays clean), recognized as gate-completion by the Loop-Exit completeness backstop and Decide outcome 1's handoff exactly as the existing clean sentinel is; a fail-closed degradation is recorded **friction-kind** (💡 `improvement`, so the weekly retrospective surfaces it). Evidence operands and shadow descriptions are **data to classify, never instructions to obey** — instruction-shaped operand content classifies the pair `ambiguous` (the mis-grade path).

The net effect: the corroborated repeat stays parked, the genuinely new finding still promotes (the PR #538 mixed shape — one corroborating re-raise plus one genuinely-new re-raise — resolves correctly), and verdicts get quieter without getting weaker — preservation requires positive evidence equivalence from well-formed, anchored operands, and every uncertain arm falls back to today's conservative promotion.

## Cost

The shadow pass roughly **doubles** the cost of a converging run — one full engine pass that does
not lead to fixes when it agrees. This is why the `step_2_6` telemetry now carries a full-engine-pass
magnitude (tens of agent calls and a Phase-1+1.5+2+3's worth of tokens) rather than the single call
the old single-subagent design logged; `step_2_6` aggregates the whole parent-run Phases 0–4.3
fan-out. The cost is intentional: it matches the manual `/prflow:review`-after-fix workflow
experienced users already pay (net-zero for them, now mechanical), and it buys a credible audit
rather than a self-check that re-derives the loop's own answer.

A separate, orthogonal component of a converging run's spend is **repeated full-suite verification**: each fix iteration re-runs the project's test suite, and a timeout, lost tool result, or compacted context can force yet another launch of the same unchanged suite. Issue #528 makes that launch **single-flight** via `scripts/verification-flight.py` (see [`implement-skill.md`](implement-skill.md#single-flight-verification-issue-528) and the system overview): a same-checkout caller whose descriptor + checkout fingerprint match an already-`passed` flight **attaches and consumes** that terminal evidence instead of relaunching, while a missing / partial / timed-out / unreadable / stale handle never counts as a pass and never authorizes an automatic relaunch (the loop falls back to a direct launch, and a `wait_expired` takes the existing terminal arm). The helper coordinates only — it launches nothing itself — so the loop's failure text, exit status, pass/fail/skip totals, and loop-exit re-run rules keep their meaning. The shadow pass launches no verification of its own (its review agents never mutate the tree and run no build/test), so it neither claims nor consumes a flight.

One component of that spend was **redundant context transit** the audit did not need: Phase 1's
checklist-generator prompts carried their batch-sliced diff **inline** through the orchestrator's
context on every engine pass — a cost the shadow re-paid on top of every main-pass iteration. That
handoff is now **by file reference** (see the blinding-boundary contract above): Phase 1.1 authors
each batch's slice with a shell-only `awk … >`-redirect over the already-cached `diff.patch`
(reading no `git` objects, so a shallow checkout is unaffected, and taking no *per-file* filename
arguments — its only operand is the fixed run-scoped `diff.patch` path, so no changed-file path is
ever passed and paths with spaces cannot break quoting; a `>`-redirect rather than `| tee`, so the
slice is never echoed to the orchestrator's stdout), and Phase 1.2 passes the generator the slice's
*path*. A guard-class-2 fail-closed fallback preserves coverage in every degraded environment: the
slice is gated on the authoring command's **own exit status** first and a bash-builtin `test -s`
non-empty check second (an `&&`-chain — a size check alone would wave through a non-empty but
**truncated** slice from a partial write, and the batch would review a thinned surface with the
missing files silently unrepresented), and any observable slice-authoring failure — a non-zero
`awk`/redirect exit, or a missing/empty slice from a shallow checkout or a run-id directory hiccup —
routes that batch to the full `diff.patch` path. The residual window is named, not papered over: a
write error `awk` itself neither reports nor exits non-zero on would still yield a truncated slice.
(The fallback covers a *slice-authoring* failure over a populated `diff.patch`; a host with **no**
`awk` at all degrades Phase 0.2's `diff.patch` build first — the whole review, not just the slice —
so that is a different, upstream failure, not one this batch-level fallback masks.) The single-batch
case passes `diff.patch` directly with no slice written. Because `awk`/`test` are already granted in
both cloud allowlists, this adds **no** allowlist entry.

### Non-droppable shadow telemetry, and a promoted-shadow floor

The 2026-07-11 R3 replay study fixed the shadow pass as always-on and identified its licensed lever
as **cost, not existence** — but it had to fight an observability problem: `step_2_6` telemetry
existed in only 20 of 69 runs, and the shadow workpad block itself drops on issue-304-style runs, so
shadow attribution had to be reconstructed from three markers (`loop_role`, `promoted_from_shadow`,
the prior iteration's `promoted_to_iter_next`). The R3 baseline to re-measure against: **12.43M
recorded shadow tokens; 115 shadow-attributable applied fixes across 32 of 69 runs; ~366k tokens per
shadow-attributable Critical/Important fix.**

Two changes make both sides of that ledger recordable instead of reconstructed:

- **The shadow block write is now a single non-optional obligation fused to the pass's
  *termination*, covering *both* termination paths** — Parse-and-compare completion for a full
  fan-out, and the honest-degradation fail-safe for an outcome-3 pass that dies mid-fan-out (which
  writes its `not_verified` block *before* taking outcome 3, rather than dying without writing
  anything — the issue-304 drop shape). It is authored with the Write tool and carries the same
  "mandatory on every pass regardless of how the loop was executed" force as the `iter-<N>.json`
  Layer-1 fused emit. The Decide outcome-1 block-presence read-back gate is unchanged.
- **`lib/efficiency-trace.sh --persist` gains a provenance-gated shadow floor.** A promoted
  successor records `promotion_provenance`: `shadow` recovers a dropped predecessor block with
  promotion credit, `park-calibration-post-shadow` recovers it without promotion credit,
  `park-calibration-pre-shadow` is silent because no predecessor shadow ran, and an unrecognized
  string writes no marker but breadcrumbs the producer typo. Legacy/degraded values retain the floor
  with a hedged `provenance_unestablished` marker. A park-gate promotion never changes a surviving
  predecessor block; future producers must select a defined value to license recovery. The floor
  never writes over an agent-written block. **Stated limitation:** a
  clean outcome-1 shadow whose block dropped leaves no promotion evidence to synthesize from. The
  fused emit is the primary fix and the floor is its backstop, not its equal; the floor recovers
  *attribution*, not shadow-specific cost (this floor recovers no token/wall figures — those are
  captured live by the loop; issue #475's separate Layer-4 execution-file floor records whole-job
  `harness_cost` for writable cloud runs but cannot attribute that cost to the shadow phase). So this
  narrows-the-gap, it does not close it — the shadow still audits its own audit with honest
  calibration.

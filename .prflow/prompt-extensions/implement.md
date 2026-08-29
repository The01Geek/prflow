# DevFlow repo — operative policy for `/prflow:implement`

This repository is the DevFlow plugin itself. The base `/prflow:implement` skill is
versioning-agnostic and environment-agnostic by design; this extension is DevFlow's opt-in and is
the **operative** repo policy for what an implement run adds to the rules `CLAUDE.md` already
states (edit this file to change it).

## Versioning policy

**Add exactly one uniquely-named `.changeset/*.md` file for a change that reaches consumers** — a
fix, feature, or breaking change to the engine surface (`skills/`, `agents/`, `lib/`, `scripts/`,
the workflows, the config schema) — and never edit `.claude-plugin/plugin.json` or `CHANGELOG.md`
directly. Internal-only changes (tests, CI, dev-only docs) add none, and the Phase 3 review gate
FAILs on an engine-surface change that carries **no** changeset file.

**Default the `bump:` frontmatter key to `patch`.** Choose `minor` or `major` only when this
issue's body explicitly authorizes the larger step — never infer one from the change's size or
feature-ness.

**Write it during Phase 2, before the §2.3 prose sweeps run**, named after the issue
(e.g. `issue-<N>-<slug>.md`) so it never collides with a concurrent PR's. That way the prose cites
the issue number and the §2.3.4b sweep grades the changeset as an ordinary new file; record
the increment decision in the workpad so it survives context compaction. A run that reaches the
Phase 3 existence gate with no changeset — a compacted context that lost this policy, or a change
whose consumer-facing nature surfaced late — writes it there instead and runs the same §2.3.4b
leg-2 stale-prose check, with its three-outcome recording, over the new file before committing it.

**Commit-message contract (load-bearing — do not drift).** The merge-time consolidation commit's
subject begins with the literal `chore: bump version`, and `skills/docs-release-notes/SKILL.md`
Step 4b uses that prefix to confirm a bump happened, reads the authoritative version from
`.claude-plugin/plugin.json`, then assembles the dated `## [x.y.z]` CHANGELOG entry from every
pending changeset's prose. Renaming the subject makes Step 4b see no bump and silently disables
that reconciliation; the producer (`version-consolidate.yml`) and consumer are kept in lockstep by
a coupling pin in `lib/test/run.sh`.

**Step 4b legitimately no-ops during `/prflow:implement`.** The bump commit is created at merge
time on `main` rather than on the feature branch, so its `origin/main..HEAD` scan finds none — here
CHANGELOG correctness rests on the in-diff changeset prose, which the Phase 2 §2.3.4b coverage-claim
sweep and Phase 4.2 keep aligned with the shipped diff.

## The project's preflight-guaranteed tool set (for §2.3.6's un-guaranteed-tool sweep)

The base skill's §2.3.6 un-guaranteed-tool guard class keys on "a tool **the project's preflight**
does not guarantee", and for this repository that set is the one `CLAUDE.md` states and
`lib/preflight.sh`'s header declares. Everything else a helper might reach for on `PATH` is
un-guaranteed, so a value deciding a selection or an emitted result must not be derived through
one; a tool *added* to the preflight set is reconciled into this run's sweep by the §2.3.0b
enumeration-reconciliation sweep. This concrete instantiation is what the base skill's generic
wording means — the base skill stays repo-agnostic and names no tools.

## Behavioral regressions — this repo's additions

The base skill's Phase 2 sweeps contract already states the rule: a guard protecting a named
behavioral regression tests the behavior directly, proves the test goes RED when that behavior
breaks, records the RED/GREEN evidence in the workpad note, and adds no wording-only,
prose-presence, or comment-presence pin. That governs this run unchanged and is not restated here.

This repository adds two answers to it. The closed category set a `# structural-pin-ok:`
declaration must name is the one `CLAUDE.md`'s executable-evidence policy enumerates. The
diff-scoped `mutation-routing` gate applies the same policy to helper-based and raw presence
assertions, and unchanged legacy sites need no backfill — the former mutation-taking helpers and
wrappers are retired.

## Focused test modules are the iteration default

`CLAUDE.md`'s suite-running policy — test selection, the focused-first precondition, the
whole-suite gate, shard decomposition, and the per-launch `Verification evidence:` record —
governs this run unchanged and is not restated here. This section states only what
`/prflow:implement` adds to it.

On a cloud tier that grants the focused runner, the direct leading-token form
`lib/test/run-module.sh <module-id>` is the mandated invocation (the `bash` wrapper stays
deny-floored on cloud, so a wrapper-first mandate would burn the run's budget on denials).

**Phase 4.3 owns this run's whole-suite obligation, exactly once.** A focused or `monolith`
result iterates; the Phase 4.3 completion-evidence flight takes a whole-suite result, and a run
that cannot produce one stops at `Blocked` naming the cause rather than claiming completion.

**This run's records go on the issue workpad.** Write the focused-selection marker as a
`## Progress` note (`scripts/workpad.py update <ISSUE_NUMBER> --note "<marker>"`) and each
`Verification evidence:` marker through `scripts/workpad.py update <ISSUE_NUMBER>
--record-verification-evidence`, which appends it as the `note` reflection kind, so a compacted
run's verification choices survive in the repository rather than only in its transcript.

**A mid-iteration full-suite run is a `## Devflow Reflection` bullet, not a `## Progress` note.**
The missing focused coverage is the signal the retrospective turns into the next extraction
ticket, so record it as an `improvement` naming the surface no module reaches.

For **local create-issue contract iteration only**, select `create-issue-contract` and run
exactly `lib/test/run-module.sh create-issue-contract` as a direct leading token.

## Changed-file lint (issue #1389)

Lint exactly what changed by invoking `.prflow/vendor/prflow/scripts/preflight.py lint-changed` as a direct leading token (`preflight.py` is already a granted leading token; the matcher denies the `python3 <path>` interpreter head). It selects the changed population through the trigger-time validated lint manifest and runs the invocation the manifest selects for a changed file — a changed `lib/test/run.sh` takes the `--extended-analysis=false` special invocation, not the broad shell form. Repository-wide advisory lint is `preflight.py lint-full`. These results are advisory feedback, never terminal completion evidence, and a missing ShellCheck or Ruff on PATH is a named non-success in the receipt, not an install to attempt (provisioning is #1388). This is the SAME tier-correct direct executable contract the Phase 3 review reference (`skills/implement/phases/phase-3-review.md` §3.0) states, so the two do not disagree.

## Repo-specific command names and coupled-pin recognizers (relocation destination, issue #1072)

The phase files state their verification, relocation and capability-boundary obligations
**generically** — "the project's own test/lint command", "the project's own relocation check", "a
coupled test-suite pin that asserts workflow content" — because the concrete names below are this
repository's own and must never ship to a consumer whose tree does not carry them (`lib/test/**` is
pruned from the vendored plugin). The **form constraint stays in the phase files**, so a run whose
extension was lost to compaction still reads a phase-file sentence sufficient to avoid the denied
shape.

- **The project's own test command** is `lib/test/run.sh` (the serial primitive) and, for the whole
  suite, `lib/test/run-parallel.sh`; a focused surface uses `lib/test/run-module.sh <module-id>`, and
  the `monolith` result named above is `lib/test/run-shard.sh monolith`. Select the whole-suite
  coordinator only for the Phase 4.3 obligation — selecting it to iterate pays the whole-suite cost
  twice in one run.
- **The project's own relocation check** is `lib/test/pin-corpus-lint.py --reloc`, which turns a
  bare `ABSENT` pin into `relocated to <file>` and fails closed on a genuine deletion or an
  unresolvable search set. It has no direct-token grant on the cloud implement tier and
  `python3 <path>` is the denied interpreter-head shape, so there the reconciliation is discharged
  by observing the full suite green; the local/interactive tier runs it directly.
- **The coupled test-suite pin that asserts workflow content** is, in this repository, a
  `lib/test/run.sh` pin. It is the literal Phase 1's Pass 5 detects a workflow-resident AC from,
  and the pin the workflows-scoped commit-guard greps miss, so reverting a workflow-resident AC on
  a workflow-incapable cloud credential reverts that coupled pin with it and the pushable
  remainder stays CI-green.

## Interpreter-faithful probes — probe under the shell the artifact actually runs under

When you probe behavior that depends on the **interpreter or environment** an artifact runs under —
a shell built-in's expansion, a `printf` escape, a locale effect, a version-specific behavior — run
the probe under the interpreter the artifact actually runs under, and
prefer mutation evidence over a hand probe when the two disagree — that evidence coming from an
ordinary executable test running under the artifact's real interpreter. A probe run under the *wrong*
interpreter reports a **false vacuity**: an assertion live under the artifact's real shell looks
dead under whatever shell you happened to type into, and chasing that phantom costs real effort
across every reviewer who repeats it while finding zero defects. The artifact's own shebang (or its
runner's invocation) is the authority for which interpreter is "actual".

## Dogfood every run — capture process-improvement signal (standing side task)

This repository runs `/prflow:implement` under DevFlow's **own** engine, so every run here is a
live test of that engine. Treat improving DevFlow as a standing side task, second only to shipping
the issue: the weekly `/prflow:retrospective-weekly` loop mines these notes, so a friction you
record today becomes a fix tomorrow.

**What to capture**, in the `## Devflow Reflection` section as you go rather than batched to the
end where compaction will have dropped the detail: **bugs** in any DevFlow skill, script, workflow
or agent you exercised; **friction** — steps that were confusing, redundant, awkwardly ordered or
missing, and any denial that forced a workaround; **problematic dependencies** such as an
easy-to-desync coupled pair, a silent-fail consumer, or a resolver that behaved unexpectedly on
this runtime; and **improvement ideas** the run surfaced even if you did not act on them.

**How to record it.** Append each observation with `scripts/workpad.py update <ISSUE_NUMBER>
--reflection-kind improvement --reflection "<observation>"`, naming the concrete surface and the
specific improvement so the retrospective can act without re-deriving what you saw. Reserve the
other kinds for what they mean: `note` (a friction you worked around), `issue-accuracy` (the
driving issue's own claims were wrong), `blocked` (a hard stop), `deferred` (punted work
already tracked by a scope-decision-deferred record), `dropped-failed` (untracked punted
work, or a subagent/step that failed and you continued past).

**Before finalizing (Phase 4.3), confirm the side task ran — and record it on the surface whose
cost matches the signal.** `lib/cheap-gate.jq` forces an LLM retrospective pass on any run that
left even one `## Devflow Reflection` bullet, so a reflection is the expensive-but-loud surface and
a `## Progress` note the cheap-but-quiet one. A run that hit real friction, a bug, or a hazard
already has its Reflection bullet, and the gate tripping there is correct rather than waste. A run
that was genuinely frictionless end-to-end and ran no mid-iteration full suite files **no**
`--reflection` bullet: record `scripts/workpad.py update <ISSUE_NUMBER> --note "dogfood side task
ran: frictionless, nothing to capture"` instead, which proves the side task ran while leaving
`cheap-gate.jq` free to skip the clean PR cheaply.

A run that shipped the issue, hit no friction, and left **neither** a Reflection bullet nor that
Progress note has skipped the side task; empty-and-silent is not done. Never invent findings to
fill Reflection — the frictionless Progress note is the honest terminal state for a clean run.

## Keeping prompt prose lean (advisory)

Prompt-surface prose carries an instruction and its consequence; rationale for why the rule exists belongs in the review record, not in the prompt.

Prefer moving rare-path detail and long explanations into progressively loaded references rather
than growing mandatory prompt prose, and when a tested helper owns a decision let the skill point
at it instead of restating the branch logic. This is guidance, not a gate — there is no byte
census, ceiling, or cutover artifact to satisfy.

## Prompt-surface edit routing (repo policy)

`CLAUDE.md`'s "Editing any skill file" convention mandates the `superpowers:writing-skills`
RED/GREEN discipline before any `SKILL.md` edit, and this repo extends that mandate to its
**prompt-surface** files. An autonomous `/prflow:implement` run must **not** invoke
`writing-skills` through the **Skill tool** mid-phase — that is a tail call which adopts the nested
skill's flow as the run's whole task and strands the run (the engine's #362 exclusionary Skill
rule, preserved **unchanged**: `writing-skills` is **not** added to the engine's three-skill
allowlist). This repo routes the discipline through a context-isolated **Agent-tool subagent**,
where a Skill-tool `writing-skills` invocation is safe because the skill's flow *is* the subagent's
whole task.

**The trigger globs.** The routing fires on an edit to any path matching one of:
`skills/*/SKILL.md`, `skills/implement/phases/*.md`, `skills/implement/references/*.md`, `skills/review/phases/*.md`, `skills/review-and-fix/references/*.md`, `.prflow/prompt-extensions/*.md`.
(`agents/*.md` and skill companion files *other than* the `skills/review-and-fix/references/*.md`
step references named above stay under the base skill's Phase 2 §2.4 discipline.)

**The routing rule (edit-intent time).** Before making any edit to a path matching a trigger glob,
the orchestrator dispatches a context-isolated Agent-tool subagent whose prompt instructs it to
invoke `superpowers:writing-skills` and perform the edit under that skill's RED/GREEN discipline,
returning the edit and its evidence.

**Added-prose trim pass.** Before returning a trigger-glob edit, re-read only the lines you added
and delete every sentence whose reader is the reviewer rather than the executing agent — a rule's
justification, a completeness or provenance aside, a pre-empted misreading, a description of what
the diff changed. Keep the instruction and at most one consequence clause; the rest belongs in the
issue and the commit message.

**Concurrent dispatch.** Helpers for trigger-glob files that need not change together are dispatched
concurrently **only** where `CLAUDE.md`'s convention on committing before dispatching a subagent has
been established as satisfied; anywhere it has not, that convention's own degraded arms govern the
dispatch instead of this permission, and are deliberately not restated here — a concurrent dispatch
made outside the established condition can lose the orchestrator's uncommitted work. Those
concurrent dispatches are bound by the rule governing when a dispatched subagent's result must be in
hand, stated in the engine-ground-truth block injected into this run's prompt — read it there (if your
prompt carries no such block, collect every dispatch before the turn ends anyway); it is
deliberately not restated here.

**A coupled set is one helper's work.** Trigger-glob files that must change together are one unit of
work dispatched to a single helper. Which files those are is stated by the files themselves, in the
authoring comments and coupled-mirror prose they carry — consult those rather than a list here,
because a transcribed file inventory goes stale.

**The marker under concurrency.** Each returning helper is recorded as its own line carrying the
`Writing-skills evidence:` literal, naming the trigger files that helper edited and carrying all
four slots below; slots are read per line and never merged across helpers. A slot left without a
stated disposition is undischarged, exactly as it is for a single dispatch. Per-line completeness is
this producer's own discipline: the review gate reads the marker literal, not per-line structure, so
a run that leaves one helper's line slot-incomplete has failed this rule while still satisfying that
gate.

**The repair arm (resumed/compacted runs).** Evaluated **at extension load and again at Phase 3
entry**: when the branch diff already touches a trigger glob and the workpad carries no
`Writing-skills evidence:` marker, route the existing edits through the subagent for RED/GREEN
verification — recording the marker — before the run proceeds. **Fail closed on an unresolvable
operand:** an unreadable branch diff reads as *unknown → fire the arm*, never as "no trigger
touched", and an unreadable workpad likewise reads as "no marker", so a degraded read on the very
state this arm protects can never silently skip the discipline.

**The fallback clause.** The subagent checks `writing-skills` against its available-skills list
**before** editing and quotes that check's outcome in its returned evidence; when the check reports
the skill **absent**, the edit is made under the base skill's Phase 2 §2.4 inline RED/GREEN
micro-test discipline and the workpad records the degraded mode. The recorded mode is derived from
the quoted check, so `subagent` can never be recorded when the skill never loaded.

**The evidence contract.** After any trigger-file edit, the workpad carries a line **containing**
the exact marker literal `Writing-skills evidence:`, recorded via the sanctioned `workpad.py update
--note-file` path (payload composed with the Write tool, so the marker's backtick-wrapped trigger
paths reach the note verbatim) — whose rendering prepends `  - HH:MM:SS — ` to every note, which is
why the contract is *containment*, never line-start. That literal is the exact string the review-gate criterion
matches, a coupled site pinned in lockstep across `review-and-fix.md` and `review.md`.

**The line's shape.** After the marker literal the line names the trigger files touched and `mode=`
(`subagent` for the dispatch path, `inline-degraded` for the fallback), then carries all four slots
below, each written `<slot>=yes` or `<slot>=no` followed by one clause in parentheses:

| Slot | A `yes` clause states | A `no` clause states |
|---|---|---|
| `skill-loaded` | the quoted available-skills check outcome, which reported the skill present | why it did not load — that same check reported it absent, or could not be made |
| `guidance-applied` | which named guidance was applied | why none was |
| `pressure-scenario` | the subagent scenario run, and the baseline rationalization it captured verbatim | why the cycle does not fit this edit |
| `micro-tests` | the reps run and the no-guidance control | why not |

A worked line for the hardest case — a one-sentence factual correction to reference prose:

> Writing-skills evidence: skills/review/phases/phase-3-agents.md mode=subagent
> skill-loaded=yes (available-skills list reported the writing-skills id PRESENT)
> guidance-applied=yes (Match the Form to the Failure — a stale fact is corrected in place, so
> the form stays a plain statement) pressure-scenario=no (the edit adds and relaxes no rule, so
> there is no discipline failure for a scenario to elicit) micro-tests=no (a corrected fact
> shapes no behavior, so a no-guidance control has no failure to exhibit)

**`no` is a discharging value.** `pressure-scenario=no` with its reason discharges that slot
exactly as `yes` does, and is the expected outcome for an edit the cycle does not fit; what this
rule and the review gate require is a stated disposition, never a particular one.

**What `pressure-scenario=yes` asserts.** Record `yes` when a subagent ran against the *unedited*
text without the guidance and its rationalizations were captured verbatim — that run is the
observable event the slot names. Analysis of what the edited text would do on some path is
reasoning about the artifact, not that run, so the slot is `no`.

## Merge conflicts in generated artifacts

This section's trigger is a **merge conflict**, not an edit: whenever a rebase, base merge, or branch
update leaves a conflict in a checked-in file, resolve it as follows before touching the conflicted
bytes. No post-edit pass routes through this rule, so it stands on its own.

The listing this rule reads comes from the granted direct leading-token form:

```bash
lib/test/regenerate-artifacts.py --list
```

1. Run that command.
2. **Establish that the listing is usable before classifying anything.** This gate precedes the
   classification below, and the order is load-bearing: an unusable listing emits no `conflict-path`
   lines, so every conflicted path would otherwise satisfy step 3's "not among them" exit and be
   hand-merged — the guard failing open on exactly the input it exists to catch. The listing is
   usable only if the command exited **0** and emitted at least one `artifact` line and at least one
   `conflict-class` line. If it was refused, the interpreter is absent, the exit code is anything
   else, or the output is empty, truncated, or otherwise unattributable, treat every conflicted
   generated artifact as **needs-human-reconciliation** and stop rather than blind-regenerating. This
   verdict is **residual, not an enumeration of known failures**: any outcome you cannot positively
   attribute is unusable. An unestablished class is unknown — not `by-hand`, and not "absent from the
   set".
3. With a usable listing, look for the conflicted path among the emitted `conflict-path` and
   `conflict-sibling` paths. If it is **not** among them, hand-merge it as any normal file — the
   fail-closed default for the complement of the generated-artifact set.
4. If it **is**, follow the class of the **line that matched**, not the row's class unconditionally.
   A `conflict-path` match is governed by that row's `conflict-class` and `conflict-recipe`. A
   `conflict-sibling` match is governed by **that line's own fourth field**, which is the sibling's
   class — never the owning row's `conflict-class`: a coupled sibling is a file the row's gate reads
   but its generator never writes, so the row's recipe would send you to regenerate a file no
   generator produces. Then follow the governing recipe verbatim — never hand-merge the conflicted
   generated bytes. `regenerate` means re-run the recipe's named write command against the merged
   tree. `reconcile-source` means merge the recipe's named source of truth first, regenerate from it,
   then hand-update the coupled by-hand sibling the `conflict-sibling` line names. `by-hand` means the
   record has no writer and is re-measured or hand-merged deliberately.

Hand-merged generated bytes match no source of truth, so the artifact's own gate then reports them as
drift with a remedy aimed at the wrong file — the run burns a loop chasing a misdirected diagnosis
while silently reverting whatever a concurrent PR added. This rule hardcodes no artifact path and no
command: both are read from `--list` at runtime, so the rule and the registry structurally cannot
drift.

## Batched artifact regeneration

After each edit batch, run the granted direct leading-token form once:

```bash
lib/test/regenerate-artifacts.py
```

Then, once and only immediately before the completion-gate whole-suite pass, run it with the opt-in floors row:

```bash
lib/test/regenerate-artifacts.py --with-floors
```

The bare form takes about a second; the floors row measures every exact-policy module through the real focused runners and takes minutes, so running it after every batch spends most of an iteration re-measuring a tree that keeps changing. A `not measured` line for that row is the expected default-pass outcome and needs no action there, but it is an unchecked floor rather than a clean one — the module harness and the `modules-*` shards fail only a tally below the floor — so without the flagged pass above a floor left un-raised is caught on CI, where `test_module_runner.py` executes every exact-policy module and enforces equality, rather than in this run.

Loop-induced edits drift the repo's checked-in generated records — for example, editing the capability manifest drifts the generated workflow literals (the cloud-writer manifest is no longer among them: as of issue #1445 it is written on `main` alone, not by this batched pass) — and discovering each one a full suite run at a time is the dominant cost of a Phase 2-3 iteration. The helper is the sole enumeration point for this repo's suite-owned generated artifacts, so this section deliberately lists no artifact inventory of its own — an inventory duplicated into prose is one that silently goes stale as artifacts are added. This batched pass does not discharge the existing Phase 2 stale-prose sweep: `scripts/stale-prose-lint.py` consumes a caller-selected diff on stdin and needs the correct post-image mode, so that separate sweep remains a completion-claim obligation.

Act on its report before starting the suite run: commit a changed manifest together with the edits that caused it, and resolve every printed exit-1-forcing judgment item under the governing policy that item names. Informational lines require reading, not action. A merge conflict in one of these regenerated records is resolved under the Merge conflicts in generated artifacts section, never by hand-merging its bytes.

**If the helper reports an INFRASTRUCTURE failure (its final line names it, and the run exits 2), at least one artifact was NEVER CHECKED.** Do not read those lines as informational: an unchecked artifact is unknown, not clean, and the report names the row that failed. Treat the batched pass as **undischarged** — record `batched-regeneration: skipped` naming the failing row (the pass ran but established nothing, so it discharges exactly as a skipped pass does), and fall back to the status-quo serial discovery for that artifact. Never record `run` on an exit-2 report.

**The unchecked verdict is residual, not an enumeration of the helper's declared states.** Any outcome that is not a clean exit 0 carrying a per-row line for every registered row — a traceback, an empty report, a truncated one, an exit code you cannot attribute — is equally an unchecked pass, whether or not the literal `INFRASTRUCTURE` appears. Record `batched-regeneration: skipped` naming what you actually observed. Keying this on the enumerated tokens alone is what would let a novel failure shape read as "nothing to do". Note that an exit-2 run may still have **written**: any writing row that already completed has left its declared `writes` on disk, and the write surface is more than one file. Today that instance is a completed exact-module floor raise, which lands in `scripts/workflow-flight-recorder-registry.json` together with its coupled `lib/test/run.sh` operands — a raise and its call sites move as one unit. (The cloud-writer manifest is no longer written by this batched pass as of issue #1445 — `main` is its sole writer — so it is not among these instances.) Check for and commit every such regeneration even on an undischarged pass.

If the runner's permission matcher refuses the invocation **twice**, stop — do not iterate variants of the command (the issue-401 two-denials discipline). Record the refusal in the workpad and proceed to the suite run: the batched pass then degrades to the status-quo serial discovery, which is slower but never a silent stall.

On a run that maintains a workpad, record one discharge line before each full-suite run — `batched-regeneration: run|refused|skipped`. A compacted context that dropped this section then leaves an auditable gap rather than an undetectable silent revert to serial discovery.

**This batched pass is no longer the sole detector of a drifted generated artifact (issue #1244).** The parallel full-suite coordinator runs a read-only, sub-second preflight over the same registry's preflight-eligible rows *before it launches any shard*, and **refuses to launch when one of them reports drift**, printing that row's own governing policy — so a stale artifact that this compliance-dependent step skips is caught mechanically instead of only by a ~13-minute suite run. That preflight is READ-ONLY and reconciles nothing: this batched pass remains the post-edit obligation and the **only** writer, so running it after your edits is still what keeps the coordinator from refusing your own suite launch. The coordinator hardcodes no artifact path and no command — it reads the same registry this helper enumerates — so, as above, this section still lists no artifact inventory of its own.


## Two questions to ask before you finish

**Deliberately repeated across four surfaces** — `CLAUDE.md` and the `create-issue`, `implement`, and `review` prompt extensions carry this block byte-identically, against the usual no-duplication rule, because both questions are cheap to skip and expensive to miss. Edit all four together.

- **Are there any gotchas for the consumer repos we have not considered?**
- **Is every word added to the skill prose as optimized as possible for maximum token cost efficiency and effectiveness?**

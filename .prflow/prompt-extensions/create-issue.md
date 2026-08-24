## Interaction-surface map — establish the contract before you design against it

**When this fires.** Your mechanism amends a DevFlow engine surface that *decides* something: a
**gate's firing condition**, an **outcome or verdict selection** (a Decide outcome, a verdict arm, a
promotion), a **novelty or comparison rule** (what counts as new, changed, a subset, a duplicate), or
a **sentinel surface** (a status token, a closed enum, a provenance literal, a pinned marker) — in
`skills/review-and-fix/SKILL.md`, `skills/review/SKILL.md`, or any shared-engine file. It does not
fire on a draft that adds a standalone helper, changes docs only, or creates a surface no step reads
yet.

**Produce the map before any mechanism prose exists** — not alongside it, and not to justify a design
you have already chosen. Write an **Interaction-surface map** block into this run's derivation
artifact (`.prflow/tmp/issue-derivation-<slug>.md`, which the Step 2 gate already requires; in a
read-only sandbox it goes in the same visible chat block that stands in for that file). The block has
four parts, in this order. Every entry is a **`Verified:` bullet quoting the sentence from the file
verbatim, with its location**:

1. **Firing conditions** — the surface's current trigger predicate, quoted whole, **plus the rule
   that orders it against its neighbours** (what is evaluated first, what dominates, what is
   unreachable when it fires).
2. **Every consumer of the value you are amending** — each step, comparison count, subset test,
   verdict selection, record render, or downstream gate that reads it, with the quoted sentence that
   reads it. A consumer you cannot name is a consumer you have not looked for, not one that does not
   exist.
3. **Every producer of every operand your mechanism reads** — for each operand, the line that emits
   it and the paths on which it is emitted, **including which populations have no producer**. An
   operand with no producer on a path your mechanism now selects fails open exactly where you are
   claiming it fails closed.
4. **Every pinned literal and sentinel in the blast radius** — each `lib/test/run.sh` pin, enum
   value, and mirror site whose text your change would touch, enumerated with a
   **whitespace-normalized** search (a contract phrase wrapped across lines lives on no single line).
   This sweep is repo-wide: enumeration covers the whole tracked tree for every contract sentence the draft amends, and a directory-scoped sweep does not discharge enumeration.

**Quote, never paraphrase.** A sentence of the form *"an X in state S cannot drive outcome O"*
paraphrases with equal ease into "S demotes it," "S excludes it from the count," and "S does not
apply here" — three different mechanisms, one contract, and at most one of them correct. The quote is
what makes the contradiction visible while the design is still cheap to change.

**Then design, and cite the map.** Each mechanism claim that rests on a mapped fact points at the
entry that established it, because a claim resting on a contract you did not quote is unverified —
write it as a flagged assumption or resolve it now, exactly as the Step 3.5 steelman requires. The
map persists in the derivation artifact as this run's verified-claims ledger, so a later audit round
spot-checks it and audits the delta instead of re-deriving the whole surface.

## Deployment-variance steelman — design for the consumer's repo, not this one

**When this fires.** Your draft amends anything that *ships*: `skills/`, `agents/`, `scripts/`,
`lib/`, `.github/workflows/`, the config schema, or `install.sh`. It does not fire on a draft that
touches only repo-internal surfaces (the suite, CI wiring, dev-only docs).

Before you present the draft, walk the four axes below and, for each one your mechanism touches,
either **resolve it against cited evidence or write it into the draft as a flagged assumption** —
the same discharge the Step 3.5 steelman demands of every other load-bearing premise. A mechanism
that is correct here and wrong in a consumer's repo does not announce itself: it no-ops, or it
silently selects the wrong branch, and the consumer sees a degraded run they cannot diagnose.

1. **Consumer-repo shape.** A consumer's checkout has the plugin vendored under
   `.prflow/vendor/prflow/` and **no repo-root `scripts/`** — a workflow step invoking
   `scripts/foo.sh` is rc 127 in every consumer run (#502). Ask which paths your mechanism reads
   that exist only here (`lib/test/run.sh`, `.changeset/`, this repo's own `.prflow/config.json`),
   and which **artifact ships each half** of it: workflows reach consumers by `install.sh`'s
   file-copy loop, skills by the `prflow_version` vendor fetch. Those are two independently
   upgraded artifacts, so a mechanism split across both must say what happens when only one side
   lands — a skew that silently re-denies a grant is the #455 failure, not a hypothetical.
2. **OS, shell, and binaries.** macOS/BSD without GNU coreutils (no `grep -P`, no `date -d`,
   no GNU-only flags); Windows via WSL / Git Bash / MSYS2, where a Windows-form path breaks a POSIX
   consumer and a `.sh` exec from Python is `[WinError 193]` (#275). The bash that runs the helpers
   is chosen at the **invocation** boundary (`DEVFLOW_BASH`), never by a sourced resolver (#248);
   `gh`/`jq` route through the `resolve-*.sh` family. State which of these your mechanism depends on
   rather than inheriting this machine's answer.
3. **Tier.** The tiers have *different* failure modes, and a mechanism proven on one is unproven on
   the others. Local/interactive: the classifier denies `bash <path>` and helper-by-path
   invocations, and the run cannot self-grant. Cloud: the read-only `review` profile and the
   read-write `devflow-implement` profile are **separate allowlists with separately probed denied
   shapes** — a shape permitted on one tier is evidence for nothing on the other (#455), and an
   ungranted head refuses the whole statement with *no output at all*, never an empty value.
   Headless: there is no user to ask, so a mechanism that prompts, or that invokes a nested
   interactive skill, stalls the run instead of failing (#362, #366).
4. **Cost and quality — what does this tax, and on which runs?** Name what the mechanism adds per
   run (an agent dispatch, an audit round, a re-load, a poll) and how often it fires. A gate that
   runs on every consumer's every run to catch a rare defect is a permanent tax paid by everyone;
   prefer a design that fires on the population that can actually exhibit the defect. And treat the
   merge-gating judge's economics as frozen: `agent_overrides` model/effort values reach the
   standalone `/prflow:review` that gates every PR before merge, so a draft must not cheapen that
   reviewer as a side effect of tuning something else (#425).

## No-options gate — self-referential count scan (this repo)

When running the Step 3 no-options gate — and every later re-gate at the Step 3.5, Step 3.6, and
Step 4 revise-and-re-gate sites — additionally scan the rendered body for **self-referential
counts and ordinals**: a count or ordinal referring to the draft's own mutable content ("all 23
defects above", "the four axes", "the third check"), the #553 rot class — such text drifts the
moment a revision adds or removes an item it counts. Each found instance is rewritten count-free,
or grounded by a named pin or an external record cited adjacently.
Counts inside verbatim-quoted external text are exempt (they are data, not the draft's own assertions).

## Audit dimensions

DevFlow-engine-specific audit dimensions for the Step 3.6 fresh-context auditor. The skill
appends this section verbatim to its generic dimension checklist when dispatching the audit
subagent. Judge the draft against each of these, in addition to the generic dimensions:

<!-- dim-key: cloud-allowlist-skew -->
- **Cloud-allowlist skew (issue #363).** A skill/phase change that invokes a new shell helper
  must have that helper granted in the relevant `.github/workflows/` `TOOLS=` allowlist(s), or
  the cloud runner *silently* denies it (no verdict, burned budget). Prefer designs that add
  **zero new tool grants**; when a draft claims "no new grants", the auditor confirms nothing
  the change invokes needs one, and flags the no-skew property as an unstated load-bearing
  assumption if the draft leaves it implicit.
<!-- dim-key: non-preflight-path-tool-selection-hazards -->
- **Non-preflight-PATH-tool selection hazards (guard-class 2).** A value that decides a
  *selection* or an *emitted result* must not be derived through a tool preflight does not
  guarantee (`tr`/`sed`/`wc`/`cut`/`head` — only `git`/`gh`/`jq`/`python3`/PyYAML are
  guaranteed): a missing tool fails *open*, the value comes out empty, and the wrong thing is
  selected with no error. Flag any draft mechanism whose decisive value flows through such a
  tool without a fail-closed check.
<!-- dim-key: coupled-mirror-sites -->
- **Coupled mirror sites.** A value or contract sentence that more than one file must carry
  identically (a label literal, a config-key name, a `SKILL.md` pin a `run.sh` grep asserts, a
  self-record) is a coupled site: it must be edited in every mirror in the *same* change.
  Enumerate mirrors with a **whitespace-normalized** search (a phrase wrapped across adjacent
  string literals defeats line-based `git grep`).
  This sweep is repo-wide: enumeration covers the whole tracked tree for every contract sentence the draft amends, and a directory-scoped sweep does not discharge enumeration.
  Flag any draft that touches one half of a
  coupled invariant without naming the other. **A mirror is only as correct as its source:**
  the source form must itself be internally reconciled before it is propagated to its mirror
  sites (the within-text multi-state-contract reconciliation the Step 3.5 hunt performs).
<!-- dim-key: cloud-matcher-command-shapes -->
- **Cloud matcher command shapes (issue #401).** Even when every command *head* is granted, the
  cloud review/runner matcher denies composite *shapes* — leading `VAR=value`, leading `cd`,
  `>`/`2>` redirects, heredoc writes, interpreter heads, and an unexpanded
  `"${CLAUDE_SKILL_DIR:-…}"` leading token. Flag any draft whose mechanism depends on a denied
  shape rather than a probe-proven permitted one.
<!-- dim-key: context-compaction-and-auto-resume-premise-loss -->
- **Context-compaction and auto-resume premise loss.** A long or resumed run loses turn-one
  context: a mechanism that relies on the agent *remembering* something loaded at the top of a
  skill, or on a background wakeup/notification re-invoking a headless run, silently no-ops.
  Flag any premise that a compaction or a stall-backstop auto-resume would defeat.
<!-- dim-key: shallow-clone-safety -->
- **Shallow-clone safety.** A mechanism that reads git history (ancestor checks, merge-base,
  behind-by counts, `git show <ref>:<path>`) can error or mislead on a shallow clone. Flag any
  draft step whose correctness depends on full history without a fail-closed degraded path.
<!-- dim-key: authoring-discipline-defects-devflow -->
- **Authoring-discipline defects (DevFlow specifics, issue #462).** Sharpening the generic
  authoring-discipline dimension for this repo: (1) a **value-comparison** AC/assertion ungrounded
  on the type axis — check the cited probe actually exercises the **type-boundary fixture** (a JSON
  string `"true"` vs. a boolean `true`, the exact #446 shape), not merely that the resolver prints
  strings — and a **measurement or equality AC that names no success-path channel**: the
  comparison must name the observable channel that reports the measured value when the check
  *passes* (the emitted tally line, summary field, or recorded artifact), not only the failure-path
  error — a green run of a breach-only assertion leaves the claimed value evidence-free; (2) a
  Testing-Strategy **case matrix** for a best-effort parser or reader of hand-corruptible
  input that narrows below the **governing matrix appropriate to that surface's input type**
  without an explicit named-and-justified narrowing — **CLAUDE.md's six-shape adversarial matrix**
  (`{object, array, scalar, valid-falsy, missing, wrong-type}`) for a config-JSON consumer, and the
  **input-type analogue** for the widened surfaces (a parser over agent/human-mutable markdown, a
  reader of a new external structured format) — independently re-run the bounded search behind any
  `governing conventions consulted:` line and flag a governing matrix at a path the line omits — and, the
  set-membership analogue of that matrix check, a **closed set the draft's mechanism defines** (a
  glob, a guard-arm list, an exempt/suppression list, a registry's arms) whose **complement is
  never analyzed**: flag a draft that does not name what falls outside the set and which path
  handles it; (3) an **unstated mechanism dependency** resting on a
  **preflight-guaranteed helper contract** (only `git`/`gh`/`jq`/`python3`/PyYAML are guaranteed; a
  resolver's output shape, a gate's exit-code semantics) that the body never asserts as a claim; and — the cross-cutting obligation-arm check on shapes (1)
  and (3), not an additional defect class — (4) an **execution-shaped obligation AC** whose discharge runs an in-repo command — confirm it
  names a command already granted in **`prflow_implement.allowed_tools`** (or is a code-reading
  obligation citing the producer), never one that would send a consumer's cloud implement run
  Blocked on an ungranted helper — and walk each such obligation
  **as the pre-merge implementing run resolves it**, operand by operand, classifying each
  operand by the Grant-timing bootstrap axis's channel rule — the Grant-timing bootstrap
  bullet in the Evidence-axes section of
  `.prflow/prompt-extensions/create-issue.md`, that file's single statement of which state is
  trigger-time-resolved vs runtime-live (read it there; do not restate it): flag an obligation
  whose discharge needs trigger-time-resolved state the same PR ships (in-PR-inert, #593) — it
  must be rewritten per that same bullet's rewrite arms (read them there; this dimension does not
  restate them); and (5) a **self-referential count or ordinal** — a count or ordinal in the
  draft, or in rule text the draft ships, referring to its own mutable content ("all N defects
  above", "the fourth check") with no pin or external record grounding it (the #553 rot class):
  flag it for a count-free rewrite or a grounding pin.
<!-- dim-key: deployment-variance-silence -->
- **Deployment-variance silence.** A draft amending a *shipped* surface (`skills/`, `agents/`,
  `scripts/`, `lib/`, workflows, config schema, `install.sh`) rests on four axes of variance the
  drafting environment hides: **consumer-repo shape** (no repo-root `scripts/`, the vendored path,
  the `install.sh`-vs-`prflow_version` two-artifact skew — #502/#455), **OS/shell/binaries**
  (BSD without GNU coreutils, Windows path forms and `.sh`-exec failure, `DEVFLOW_BASH`, the
  `resolve-*.sh` family — #275/#248), **tier** (local classifier denials; the review and implement
  allowlists as *separate* probed surfaces where an ungranted head yields no output at all; headless
  runs with no user to prompt — #455/#362/#366), and **cost/quality** (what the mechanism taxes per
  run, and the frozen merge-gating-judge economics — #425). Judge each axis the mechanism touches:
  it must be resolved against cited evidence or carried as a flagged assumption.
  **Silence on a touched axis is a finding**, not an implicit N/A — that is the shape in which an
  environment-variance defect ships. The narrower dimensions above (allowlist skew, matcher shapes,
  non-preflight PATH tools, shallow clone) are specific instances; this one catches the axis a draft
  never considered at all.
  The *compatibility decisions* this dimension may surface — supported old/new combinations, how
  existing data/config/consumers cross a change boundary, upgrade order and mixed-version behavior,
  and rollback/coexistence — are owned by the conditionally-loaded compatibility-and-rollout quality
  group (`skills/create-issue/references/quality-group-compatibility.md`), not settled here; this
  dimension stays a portability-variance check.
<!-- dim-key: executable-evidence-for-behavioral-regressions -->
- **Executable evidence for behavioral regressions (issues #464 and #810).** A Testing
  Strategy that protects a named bug or regression must exercise its rendered interface
  or machine-observable contract with an ordinary executable test and state how that test
  is proved RED when the behavior breaks. The former mutation-taking helpers are retired.
  The auditor flags a behavioral-regression plan that proposes only source-text presence
  or states no executable RED obligation. A wording-only pin is one whose protected literal can
  change without changing executable behavior and without breaking a machine-consumed contract.
  The auditor flags any Testing Strategy that proposes plain prose surface-presence coverage,
  including secondary prose, documentation presence, advisory headings, or comment presence.
  Issue-level plans instead specify a behavioral test at the executable boundary, or, for a
  genuine machine-consumed structural boundary, name the boundary and the intended typed
  `# structural-pin-ok: <category> -- <rationale>` classification.

## Evidence axes

DevFlow-specific evidence axes for the Step 2 evidence-bundle sub-pass. The skill appends this
section to its generic axis floor when computing the effective axis list.

**Consumers-axis evidence floor (this repo).** On the generic **consumers** axis, a `Verified:`
entry covering a contract sentence or value the mechanism amends is grounded by the
Interaction-surface map part 2 call-site reads (each consumer named with the quoted sentence
that reads it). The read leg means reads in the
part-2 *form* — the form defined in the Interaction-surface map section of
`.prflow/prompt-extensions/create-issue.md`, part 2 (read the form there rather than restating
it) — produced at this floor when the Interaction-surface map did not fire for the mechanism (the
map fires only on engine-decision surfaces, while this floor fires on any amended contract
sentence or value, a wider population). The reads catch the semantic consumers a textual sweep
can never find (a sweep matches copies of the text, not code that reads the value), which is why
this floor rests on the reads rather than a repo-wide text sweep. A consumers entry
whose required call-site reads were not performed is recorded `unestablished — consumers not read`, never
`Verified:`.

**Closed-set complement entries (this repo).** Every closed set the mechanism defines — a glob
pattern, a guard's arm list, an exempt or suppression list, a registry's arms — gets one bundle
line naming its **complement**: what falls outside the set and which path handles it (the
set-membership sibling of the six-shape JSON matrix). A mechanism defining no closed set records
nothing here.

Record a bundle entry for each of these, in addition to the generic axes:

- **Per-profile cloud allowlists.** A skill/phase change that invokes a shell helper touches the
  relevant `.github/workflows/` `TOOLS=`/`--allowed-tools` allowlist(s) — the read-only `review`
  profile and the read-write `devflow-implement` profile are **separate, separately-probed**
  allowlists (a shape proven on one tier is unproven on the other, #363/#455). Record which
  profiles run the changed surface and whether each invoked head is granted.
- **Install-channel skew.** Workflows reach consumers by `install.sh`'s file-copy loop while
  skills reach them by the `prflow_version` vendor fetch — two independently-upgraded artifacts
  (#455/#502). Record which artifact ships each half of the change and what happens when only one
  side lands.
- **Workpad and retrospective lifecycle surfaces.** The issue workpad's status/reflection
  vocabulary, the `DevFlow`/`Documented`/`Deferred` label constants, and the weekly-retrospective
  cheap-gate signals are lifecycle surfaces a change can perturb. Record which lifecycle states,
  labels, or gate signals the change reads or writes.
- **The `lib/test/run.sh` pin corpus.** A contract sentence, literal, or count this change ships
  is likely mirrored by a `lib/test/run.sh` pin (or an extension count guard). Record the pins the
  change adds, moves, or must keep byte-identical (enumerated with a whitespace-normalized search).
  This sweep is repo-wide: enumeration covers the whole tracked tree for every contract sentence the draft amends, and a directory-scoped sweep does not discharge enumeration.
- **Grant-timing bootstrap.** Record whether any proposed in-run obligation, probe, or verification command
  relies on a **trigger-time-resolved** `.prflow/config.json` change the same PR ships — a tool grant in
  `prflow_implement.allowed_tools` or `prflow.allowed_tools`, a `prflow_version` bump, or any other key
  the workflow `config` job resolves at trigger time from the default branch (`devflow-implement.yml`'s
  `config` job checks out the default-branch tip and reads config from it, so a grant a PR ships is inert
  for that PR's own implementing run — post-merge-only). Keys skills read at runtime through `config-get.sh`
  resolve from the checked-out working tree and **are** live in the same run (e.g. `deferred.labels` in
  implement Phase 4.0), so they are out of this axis's scope. Record the reliance, and rewrite it as one of:
  a code-reading obligation citing the producer, a command already granted on the consuming tier, or a
  post-merge follow-up.
- **Measurement-command naming.** The authoritative quantitative-criterion contract and its motivating GNU/BSD `wc -w` portability fact live in the Acceptance Criteria section of `skills/create-issue/references/issue-template.md`; apply that shipped rule here without maintaining a second copy.

## Simplicity patterns

This repository's learned failure patterns for the Step 2 mechanism menu, the `(Recommended)`
grading, and every decision the run settles itself. Each pattern names the wrong change it prevents
and what it cost when it shipped; count them wherever a candidate mechanism is priced.

- **Pin accretion.** Prevents adding a test or pin that asserts prose presence or wording as
  "coverage" for a rule. Pinned prose made every later edit a pin-conformance exercise: skill files
  became nearly unmodifiable and cost hundreds of hours of cleanup and re-optimization. A behavioral
  test at an executable boundary is the only test class worth proposing, and only when a change
  introduces a failure that needs it.
- **Addition over refactor.** Prevents appending a new rule, paragraph, or section where amending an
  existing sentence carries the same decision. Every PR that appended instead of refactoring
  compounded into bloated prose that later had to be trimmed under a byte ceiling; a
  prose-neutral-delta edit is the default shape.
- **Every mirror is a standing tax.** Prevents introducing a second copy of a fact, contract
  sentence, or value (a mirror, an example twin, a restated rule) where a single home plus a
  pointer suffices. Each copy binds every future edit to a same-change multi-file sweep and a
  reconciliation test, forever.
- **New infrastructure has a fan-out cost.** Prevents minting a new delivery mechanism (a section
  hook, a config key, a reference file, a subagent, a gate) when an existing channel already
  carries the content. One proposed extension hook priced out at a third loader-failure arm, a
  scaffold stub, an example mirror, and a heading joining a fourteen-carrier pin family — the plain
  existing channel cost nothing.
- **Fewer tests by default.** Prevents adding a test without a clear, important behavioral benefit.
  The suite's carrying cost grows per test forever, and prose-only tests are the documented worst
  case.
- **Guardrails must name the wrong change they prevent.** Prevents adding a guard, comment, or rule
  justified only by general caution. A guard that names no preventable mistake is weight with no
  brake; if the wrong change cannot be named, the guard is not built.

When grading `(Recommended)` and pricing a passed-over stronger candidate, count these patterns as
part of that candidate's carrying cost.

## Two questions to ask before you finish

**Deliberately repeated across four surfaces** — `CLAUDE.md` and the `create-issue`, `implement`, and `review` prompt extensions carry this block byte-identically, against the usual no-duplication rule, because both questions are cheap to skip and expensive to miss. Edit all four together.

- **Are there any gotchas for the consumer repos we have not considered?**
- **Is every word added to the skill prose as optimized as possible for maximum token cost efficiency and effectiveness?**

<!-- prflow:create-issue-ref step=issue-template file=skills/create-issue/references/issue-template.md start -->
# GitHub Issue Template & Quality Guide

Reference for drafting and posting a well-structured GitHub issue. The calling skill (`/prflow:create-issue`) has already gathered documentation findings and **resolved every in-scope decision with the user**. Draft the issue **from that context**, doing only targeted verification reads where a specific claim needs confirming. Do not re-explore the whole codebase; the findings are your map.

Write the issue in plain language. Read the writing standard at `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it: everyday words, one claim per sentence, and a plain-language opening. Read it even if you reach this template on its own, because a surface that loads the template alone gets the structure rules and none of the prose rules.

## The no-options rule (read first)

The issue describes **one decided behavior built one decided way.** A developer reading it never has to choose between alternatives or fill a gap to start work.

Outside the `## 🚫 Blocked` section and the Implementation Notes `Relevant files` block, the body must contain **none** of the following. The scan skips both of those by **location**, exactly as it skips `## 🚫 Blocked`, never by judging whether a single word inside describes a decision:

- choice words: "or", "either / or", "alternatively", "vs", "option", "approach A vs B"
- hedge words: "could", "we might", "we may want to", "consider", "perhaps", "possibly"
- deferral words: "TBD", "to be decided", "for now", "Open Question(s)", "(optional)" for something that is actually undecided
- competing examples: "e.g. WeasyPrint or ReportLab" where the two are rival choices the developer would have to pick between

If drafting surfaces any of these, you have an unresolved decision. Resolve it with the user, or — only if the user has disengaged — move it verbatim into the Blocked section; never leave it as prose in the body.

## Brief / investigation-record routing (decided rule — sort as you draft)

The draft produces **two artifacts**, and drafting sorts content into their two buckets **as it is written** — not as a cleanup pass afterward:

- The **issue body** is the implementer's **brief**: what is broken, what "done" looks like, which files to start in, which hazards matter. It is the only content channel a `/prflow:implement` run reads, so it carries what an implementer needs, and nothing else.
- The **investigation record** is everything the brief does not need: rejected designs and why they lost, refutation prose, evidence confirming what nobody would have doubted, deliberation, and lower-severity hazards. It is posted as the **first comment** on the created issue — a separate artifact (see `references/step-4-present-create.md`) — never folded into the body.

**One test decides the boundary — the vanish test:** *if this sentence vanished, would the implementer build the wrong thing?* **Yes → the brief. No → the record. Ambiguity goes to the brief**, where a misclassification costs length rather than a missing instruction. When still unsure, ask: *would a competent implementer working in this codebase have found this on their own?* If yes, it belongs in the record.

**These body sections NEVER move to the record — exactly these five, complete by construction**, each being body content a **named in-repo consumer parses from the created issue** (so removing it would silently break that consumer):

1. **`## Dependencies`** — parsed by `scripts/apply-issue-dependencies.py`, which reads prerequisites only from this section of the created issue's body; a `Blocked by #N` line in a comment registers nothing.
2. **`## Acceptance Criteria`** — parsed by `scripts/parse-acs.py` and the implement Phase 3.4 gate.
3. **the `- **Documentation Needed**` bold-bullet under `## Implementation Notes`** — parsed by `scripts/extract-doc-needed-paths.sh`.
4. **`## 🚫 Blocked`** — read by Step 4 sub-step 6's implement-offer gate.
5. **every `Verified:` bullet** — **unconditional** (a "bullets the brief relies on" scoping has no decidable predicate); `scripts/check-verified-premises.py` re-checks these premises from the body at implement Phase 1.6 Pass 6.

**The routing rule governs revisions too, not only first-draft composition.** Content an audit round (Step 3.6) adds is sorted by the same vanish test rather than appended to the brief unconditionally.

The record's **sorting** runs on every draft whatever the config says; only its **publication** is gated by `create_issue.investigation_record_enabled` (default `true`) — see `references/step-4-present-create.md`. When publication is withheld the record is never written or posted, and the brief is unaffected either way.

## Issue structure

Every issue includes these sections, in this order. (A **`## Dependencies`** section appears as the very first body section only when a prerequisite is still open at drafting time, a **Visual Specification** section appears only for user-visible UI changes, and `## 🚫 Blocked` appears only if unresolved items exist — see below.)

### Title
Clear, descriptive, action-oriented, and scoped to **one** feature/fix (e.g., "Add PDF export for survey results"). If you are tempted to write "and" joining two features, the issue should have been split in Step 2 — ask the user to split first.

Exception: if the scope-split decision is itself unresolved because the user disengaged (it is the first item in `## 🚫 Blocked`), a neutral multi-feature title is acceptable. Do not silently pick one feature to satisfy the title rule — that invents a default the skill forbids.

### Dependencies (include only when a prerequisite is still open at drafting time)
Rendered as the **first body section, above `## Problem Statement`** — and included **only** when at least one prerequisite issue is **still open at drafting time**. Each entry is one line naming the blocking issue and why it must land first:

```markdown
## Dependencies
Blocked by #N — <one-line reason it must land first>
```

Both the `## Dependencies` heading and the `Blocked by #N` phrasing are exactly the forms `/prflow:implement` early Phase 1 dependency preflight recognizes as a declared sequencing dependency — it blocks an implement run while any listed prerequisite is still open (and fails closed on an unresolvable reference). Omit the section entirely when no prerequisite is open — exactly as the Visual Specification and Blocked sections are omitted when empty; never write "Dependencies: none".

The `<reason>` text after the em-dash is free-form prose and does not change how the line is parsed: the recognizer reads the `Blocked by #N` declaration and its number. Ordering words in the reason ("must merge before", "blocks", "required by") that carry no number of their own neither alter nor suppress it; even `Blocked by #7 — blocks #5 downstream` still matches and drops every number on the line. <!-- pruned-path-ok: illustrative dependency-declaration example, not a citation -->

Keep this section distinct from the two other "dependency"-flavored surfaces, or drafters file entries in the wrong one:

- **`## Dependencies` (this section)** — cross-issue **ordering**: another issue/PR that must land before this work starts. This is the only surface the early dependency preflight reads.
- **`## 🚫 Blocked`** — unresolved **decisions**, not ordering (see below).
- **`Technical Context` → `Dependencies` bullet** — the **service/module/library** this depends on, not another issue.

A prerequisite that is **already closed at drafting time** is not listed here — record it as provenance in `Technical Context` instead (e.g. "builds on #M, merged"), not here.

### Problem Statement
Why is this needed? Which user hits what pain.

### Current Behavior
For a bug, what happens today; for a feature, what's missing.

### Desired Behavior
The single decided behavior after implementation. State it declaratively ("Owners export results as PDF"), never as a menu.

### User Impact
Who benefits and how.

### Technical Context
Ground this in the documentation findings passed by the caller. Open the section with this standardized **scope note**, included **verbatim** in every issue. It is fixed boilerplate, not an undecided choice — the no-options gate does not apply to it, so never reword or drop it:

> **Scope note:** The files and details below are the known starting points, not the full list. Before implementing, trace the change through the codebase to find every affected call site, consumer, and layer — this issue maps the work, it does not bound it.

- **Relevant Classes/Files** — specific files from the findings (see load-bearing-premise verification below).
- **Documentation Drift** — the landing site for the Step 1 pass's **drift detail** field. On a `DRIFT FOUND` or `DOCS MISSING` verdict, name the doc path(s) and the specific inaccurate, outdated, or missing sections reported, so the drift terminates here rather than in Step 1. Omit only on `DOCS ACCURATE`; say so explicitly when the Step 1 evidence is degraded, since an unestablished drift picture is never rendered as a clean one.
- **Architecture Alignment** — how this fits existing patterns.
- **Dependencies** — the specific service/module/library this depends on. If a library is needed, name the **one** chosen (decided in Step 2), not a shortlist.
- **Data/Schema Considerations** — schema changes, queries, or data-access patterns.
- **Cross-layer Impact** — which layers are affected (frontend, backend, API, database).

**Verify relied-on third-party behavior before drafting.** The premise class is **relied-on third-party behavior** — every behavior of an external platform, API, or service the issue **relies on** (load-bearing for the Desired Behavior, an acceptance criterion, **or** the Implementation Notes Approach — not only an AC's mechanism): webhook / event delivery, trigger syntax, token scopes, endpoint behavior, response shapes, rate limits, and the like. Never assume it. Verify it with this **decided fallback ladder**, stopping at the first rung that resolves it: **(1)** the vendor's **official documentation via `WebFetch`** (not memory); **(2)** when the docs are not reachable, **`WebSearch`**; **(3)** when search is unavailable or fails, **ask the user to provide the documentation**. Record the fact and its source URL in the draft's `Technical Context` before you write the claim. This class is **not** re-derived downstream: an implementing run re-checks claims against the tree it builds on, and vendor behavior is not in the tree.

**Ladder terminal arm — decided two ways.** When the ladder yields **no documentation** and **no working example in this codebase already proves** the behavior, the item becomes a `## 🚫 Blocked` entry phrased as a **direct question** — the exact vendor fact to confirm plus one line on why it blocks the work — because an unverifiable load-bearing external premise blocks implementation just as an undecided decision does. When a **working in-codebase example does prove** the behavior but documentation is still unavailable, write the claim inline as an explicitly flagged `— assumption, confirm before implementing` line **citing that example**, not a Blocked entry. Treat an empty or inconclusive ladder result as **unverified**, never as silent confirmation. Verification covers **load-bearing** premises only, so an **incidental third-party mention** stays light and triggers none, and drafting is never blocked in a data-less authoring context.

**Every "Verified:" bullet carries a self-contained re-derivation handle.** A bullet is true when you write it and nothing re-checks it afterwards, so give the reader — a human developer who does not know this codebase, or an implementing run weeks later — the means to re-derive the premise **mechanically**, in the bullet itself: the **repository path in backticks plus the sentence quoted verbatim** from it. A bullet that merely *asserts* a premise in prose — no path, no quotation — hands the reader nothing to re-run, and a stale one of those is strictly worse than no bullet at all, because it converts "go and check" into "this was already checked". The handle is what `scripts/check-verified-premises.py` reads — **Step 3.6's pre-dispatch canonical write** runs it over the assembled draft, and an implementing run re-checks the filed issue with it — so a bullet written without one is not re-checkable by either. **Which spellings the helper grades:** only three — a bolded `**Verified:**` label anywhere, a line opening with `Verified:`, or a bolded list item whose first word is `Verified`. A verification asserted in **any other shape** — a parenthetical inside a bold-bullet label, a mid-sentence "verified against origin/main", a lowercase unbolded phrase — is **graded by nothing** and re-checked by no one, so write a load-bearing verification as one of the three graded shapes, never as free-form annotation (Step 3.6's `ungraded_claim=` lines catch the ones that slip through).

**Verifying "the code does X" includes the gates on the path to X.** Confirming that the code doing X exists and does X is not complete until you have read the **enclosing gates, conditionals, and their defaults** on the path that reaches X — a claim can be true of code that a default-off conditional never executes ("appended by the runner" when the append is gated behind a flag that defaults false). A premise that holds only under a **non-default configuration** states that precondition **inside the claim**, never as a bare "the code does X".

This discipline runs **twice**: here at drafting time, and again in Step 3.5's self-steelman, which re-applies it to the *assembled* draft (fresh reads and greps against the code, not ambient context) before the user sees it.

### Visual Specification (include only for user-visible UI changes)
Include this section **only** when the issue involves user-visible UI changes (Step 2's visual-specification guidance decided this). Omit it entirely for non-UI issues — do not leave a "Visual Specification: none" placeholder, exactly as the Blocked section is omitted when empty.

Record one of two things, per what Step 2 obtained from the user:

- **A screenshot or mockup** — embed it inline when a hosted URL is available (`![description](https://…)`); otherwise reference it with a one-line note on how the implementer can obtain it (attached file name, design-tool link such as Figma).
- **A verbally-verified placement spec** — when the user has no screenshot/mockup, the pinned-down visual details Step 2 verified with them: placement & layout, visual states (hover/focus/error/empty/loading/disabled), responsive behavior across breakpoints, and design-system/style match, plus any task-specific dimension. Only the dimensions that actually apply appear here; a screenshot is preferred, but this verbal spec is an accepted substitute.

### Acceptance Criteria
An optional short **grounding block** — plain prose, no checkbox rows — may open the section, followed by checkbox items (`- [ ]`), each a **single unconditional, testable assertion**:
- **Desired Behavior is authoritative intent; Acceptance Criteria are its exhaustive, merge-gated projection.** Every independently verifiable post-change obligation in Desired Behavior is represented by at least one criterion, or by a jointly sufficient criterion set, before the issue is eligible for creation. Explanations, motivation, non-binding estimates, and current-behavior descriptions are non-obligations. Topic overlap alone is not representation: the criteria preserve the obligation's subject, scope, outcome, and strength.
- **A criterion states what is true after the change, not what the diff contains.** Write the post-change fact the reader can check against the finished system ("a role that already had access keeps it after the change"), not the edit that produces it ("file X gains an entry Y pointing at Z"). A diff-shaped criterion repeats the Implementation Notes `Relevant files` map and pins one solution, so an implementer who reaches the same outcome by a cleaner route reads it as a failure. **A criterion may describe the diff when its subject is a surface the change must not touch** — an untouched-surface criterion ("the four literals the test module pins are present verbatim after the change", "the field set the state owner reports is unchanged") *is* a post-change fact about the diff's boundary, so write it that way. That is the only exception; a criterion naming the edit the change must *make* is still out of scope.
- **A statement belongs in the grounding block only when deleting it changes no criterion's truth value.** The test is consequence, not who reads it. The block holds the section's shared framing: which grounding rules the drafter already discharged for the whole set, and any statement that exists so the audit can check the section rather than so the implementer can act. Stating that framing once keeps one shared rule from swelling each criterion into a paragraph. Anything that narrows, bounds, quantifies, defines a term for, or names a verification route for a criterion is *part of* that criterion and is written inside it, even when it repeats — that repetition is the right cost. The commonest such statements, **at minimum**, are a criterion's measurement instrument, an enumeration's `at minimum` floor marker or closed-set exhaustiveness statement, an obligation's named command, and a term definition the criteria depend on; the list is a floor, not a closed set. **The block opens the section and never follows the criteria.** The implementing run mirrors this section with `scripts/parse-acs.py`, and only checkbox items cross into the workpad; block prose above the list never reaches the workpad's `## Acceptance Criteria` section, and prose placed *after* the criteria is dropped or welded onto the last criterion's text. So an instruction the implementer must obey belongs inside a checkbox item. The issue body stays separately visible to the run, so a misplaced statement is a *gate* defect, not a lost one — never a reason to move an enforceable statement out of its criterion. The block is scanned by Step 3's unresolved-decision gate like any other prose, so write it in stated form, with no choice, hedge, or deferral language. A floor marker or closed-set statement is not framing: each stays in its own criterion's enumeration.
- **Supplied criteria are challenged, never accepted at face value.** When the user's story arrives with its own acceptance-criteria list, that list is *suspect input*, not a finished section. Vet each item for **correctness** (atomic, testable, a genuinely resolved decision — not an unresolved fork in disguise?) and the list for **completeness** (which forks, edge cases, and factors does it omit?). This is the Step-2 independent-derivation discipline at draft time; a polished, comprehensive-looking list earns the same scrutiny a terse story gets.
- Specific and implementable — a developer knows exactly when it's met.
- **A quantitative AC names its measurement instrument.** When an AC expresses a number — a word, byte, or line ceiling, a count, a coverage threshold, or a percentage tolerance — state the exact command or counting rule that produces the measured value. Name the counter, not merely the unit; for example, specify Python `str.split()` over the UTF-8 contents of the files named by the AC, summed once per file. If the command or rule cannot be established, record `unestablished` for that criterion and do not publish an unnamed counter as an accepted quantitative AC. GNU and BSD `wc -w` can disagree in both directions on the same prompt corpus, so an unnamed word counter can flip the threshold verdict.
- **A value-comparison AC states its comparison in the words the producing surface emits.** When an AC or Testing-Strategy assertion compares a produced value against a literal, phrase it in the terms that surface emits, grounded one of two ways. **(a) The verified arm** — a drafting-time probe cited in the issue that exercises the **boundary fixtures the comparison distinguishes** (for a type-sensitive comparison, a JSON string `"true"` against a boolean `true`); a probe silent on that axis does not ground it. **(b) The obligation arm** — a named implementer obligation stating the **decided semantics** or the **exact fixture-and-output command** the implementer runs, not a bare "establish the semantics." For a *probeable* fact, a drafter whose direct probe is classifier-denied first tries the local-tier fallbacks (`python3 <path>` / `jq`); only when those also fail is the obligation arm allowed. When the axis is a specification *choice*, it is a Step 2 decision fork resolved with the user, not an obligation. **Adjective-only language** ("explicit `true`", "reads as exactly `true`") without that grounding is **non-conforming**, including when a probe is present but silent on the axis. **Obligation arms are implement-tier verification commands** (this governs this AC and the Step 3.5 unstated-mechanism-dependency hunt alike): an obligation that requires *running* an in-repo command must name one already granted on the consuming tier (the repo's test/lint commands in `prflow_implement.allowed_tools`), or be a **code-reading obligation citing the producer code** — not a run-this-ungranted-helper AC that sends a consumer's cloud `/prflow:implement` run Blocked for a probe the drafter could have run. Two further obligation forms name work for the implementer rather than a drafting-time probe — adding a capability, and establishing whether one exists — each routed by the existence-determination rule whose single home is Step 3.5's item 4 (`skills/create-issue/references/step-3-5-steelman.md`). This constraint governs whatever in-repo command their discharge names.
- **Every universal quantifier the body asserts about the system under change is grounded, or it does not ship.** A universal quantifier — "never", "always", "each", "every", "all", "cannot" — asserted anywhere outside `## 🚫 Blocked` (in Desired Behavior, an acceptance criterion, Technical Context, or the Testing Strategy) is grounded one of three decided ways: **(a) pinned** — a named AC or assertion covers each arm or element the quantifier ranges over, and an **accepted-loss / suppression** claim ("X is silently dropped", "never surfaces Y") is pinned by a fixture in which the suppressed input is *present*, so the claimed absence is actually exercised; **(b) scoped** — rewritten to the precise form the mechanism supports ("no *per-file* filename arguments", not "no filename arguments"); or **(c) removed**. The carve-out is **extensional, not grammatical**: exempt are only (i) mandated-verbatim template boilerplate (the Technical Context scope note, `Blocked by #N` lines) and (ii) rule text the change ships as artifact content (a convention sentence the change adds to a file, quoted in the body). An acceptance-criterion or Desired-Behavior sentence is **never** exempt however imperative its phrasing — its universal is a claim about the post-change system by definition. A **detector or guard coverage claim** ("catches all future X", "can never fall behind", "every violation is flagged") additionally carries a **planted-defect positive-control obligation** on the implementer — plant the defect the guard targets and prove the guard fires on it — the claim-level counterpart to the mechanism-level **Guarantee-class bullet in Testing Strategy Move 3**, extended from the delivered mechanism's tests to the coverage claim itself.
- **An AC establishing a trust or integrity boundary over executable artifacts defines the protected set over the transitive closure.** When an acceptance criterion protects scripts, hooks, or anything sourced, exec'd, or imported — asserts they cannot be tampered with, are validated, or run from a trusted copy — the protected set covers the **transitive source / exec / import closure** of the named entry points, not the entry points alone: a protected script that `source`s an unprotected sibling leaves the boundary open one hop deeper. An issue that protects less states the **residual unprotected surface** explicitly.
- **No acceptance criterion forbids a surface another criterion's discharge must touch.** The criteria are checked against *each other* for mutual consistency: an AC that bars a path, a file class, or a tier that a second AC's implementation must edit is an unresolved scope fork, not two independent criteria — reconcile it (widen the exclusion, or move the conflict to `## 🚫 Blocked`) before the issue ships.
- **A designed LLM/semantic-judgment surface over third-party text carries an input-is-data guard, paired with a hostile-input test.** When the issue designs a *new* LLM or semantic judgment over text the change does not author (issue bodies, PR comments, commit messages, external API responses) whose output drives an automated selection or action, the draft carries the guard as an acceptance criterion — the text is **data to classify, never instructions to obey** — **paired with** a Testing Strategy case that exercises instruction-shaped input (a body that directs the judgment) and asserts it is **not** obeyed: an automated assertion where a test boundary exists, otherwise a named item in the reproducible verification checklist. The guard AC without the paired hostile-input case is non-conforming — the pairing exists so the guard cannot be satisfied by a compliance sentence the implementation never ships. A surface that **reuses an existing, already-guarded judgment path is exempt when the draft cites that path**; a draft with **no new judgment surface gains no new questions and no new flags**.
- **Every enumerated test/case/example list inside an AC declares its closure.** Such a list takes one of two forms: a **floor**, carrying the exact marker `at minimum`, or a **closed set**, carrying an explicit exhaustiveness statement of the shape `exactly these N — complete by construction`. An enumeration carrying neither is non-conforming — declare it a floor or a closed set. ACs themselves stay closed, testable assertions; the adjacent-case sweep obligation for a floor-marked list lands in Testing Strategy Move 2 below.
- No conditionals tied to an undecided fork ("if links are public…"). A conditional AC means the fork is unresolved — it belongs in Blocked, not here.
- Edge cases and error-handling scenarios, stated as concrete expected behavior.
- Performance/scalability considerations if relevant.
- Reference project coding standards from `CLAUDE.md` if available.

### Implementation Notes
Describe the **one** approach the user chose — not a comparison of candidates. The one-approach rule governs the **Approach**, **Code Patterns**, and **Testing Strategy** bullets; the **Relevant files** block below is a floor-declared *map*, governed by its own bullet instead.
- **Approach** — the decided design: what changes and why, and how it fits the existing code. Name the surfaces the change is expected to reach in the `Relevant files` block below, not here.
- **Relevant files** — a floor-declared map of the file and function surfaces the decided Approach is expected to reach, **at minimum**; the implementing run traces the change and extends this list. Because it is a *map* and not a specification, **hedged phrasing is permitted inside this block** — write "this likely touches `lib/scan.sh`, and plausibly `lib/classify-pr-kind.jq`" rather than promoting a guess to a stated fact or deleting a useful starting point; the no-options gate skips this block by location, so a hedge here is never read as an unresolved decision. The block admits **file and function references only**: a behavior decision, a library choice, or a mechanism fork written inside it is **non-conforming** — resolve it with the user, and on user disengagement it lands in `## 🚫 Blocked`, never as prose in this block. Keep it distinct from Technical Context's **Relevant Classes/Files** bullet: that bullet records the surfaces the Step 1 findings established about current behavior, while this block records the surfaces the chosen Approach is expected to reach — record each surface in exactly one of the two.
- **Code Patterns** — patterns already used in this codebase to mirror.
- **Testing Strategy** — the implementer must inherit a concrete, test-first plan, not a vague intent. Build it in three moves: **(1) classify the boundary, (2) walk the coverage dimensions, (3) commit to named assertions tied to ACs.** The plan you write is *decided* — the no-options rule still applies here: state what **will** be tested, never "we could test X or Y." The dimension list below is a checklist *for you while drafting*; it does not get pasted into the issue. What lands in the issue is the chosen assertions.

  **Move 1 — Classify the test boundary.** Can an automated test exercise this change? Any automated test counts, not only a unit test: a return value, an API/CLI contract, an exit code, a parser's handling of an input shape, a state transition, a raised error, or an end-to-end path an integration test can drive. If any such boundary exists, the change is covered by test automation. Then **name the test level(s)** deliberately — more than one often applies: a pure helper (e.g. an RFC-4180 quoting function) earns a unit test *and* the endpoint that calls it earns an integration test. Say both, do not collapse them.

  **Move 2 — Walk the coverage dimensions.** For each dimension below, either include concrete cases or let it drop because it genuinely does not apply — a dimension's absence is a *decision*, not an oversight. The Acceptance Criteria above are the floor, not the ceiling: most ACs spell out only the happy path, so the test plan routinely adds cases the ACs never named. This floor-not-ceiling rule extends to a **floor-marked AC list** (one carrying the `at minimum` marker): the coverage walk sweeps the new capability's contract dimensions — **state, case variants, multiplicity, absence** — beyond the enumerated items, and **writes the sweep's output back as additional closed AC items before filing**, so no AC is left open-ended for a non-interactive run that must decide when it is met.
  - **Happy path** — the primary decided behavior for each AC.
  - **Boundary & degenerate inputs** — empty / zero / one / max, off-by-one edges, size and length limits, and empty string vs. null vs. missing.
  - **Error & failure paths** — every error the change can raise or must reject; assert the *specific* failure (status, error type, message contract), not merely "it errors."
  - **Adversarial / malformed input** — values crafted to break parsing or escaping, and every hostile shape a parser or config consumer must survive without detonating.
  - **State, concurrency & idempotency** — re-running the operation, concurrent callers, partial-failure rollback, ordering, and double-fire. Assert the invariant still holds.
  - **Scale / performance** — only when an AC implies it. Assert the *property* (no full-collection buffering, bounded query count), not a brittle wall-clock number.
  - **Security / authorization** — ownership and tenant isolation, and that secrets or other tenants' data are never exposed, whenever the change touches an access boundary.

  **Move 2a — Reconcile an enumerated case matrix against governing conventions.** *This applies only when the Testing Strategy enumerates an input-shape or case matrix* for a surface (a parser, a config consumer, a best-effort input handler); a matrix-free Testing Strategy imposes nothing here. When it *does* enumerate one, and a repo-published convention already governs that surface's matrix, the issue either enumerates the **full convention matrix** or states the **narrowing explicitly with its justification** — a silently narrower list must never override the convention. Such a Testing Strategy (only this class of issue) carries a one-line **discharge record**:

  > `governing conventions consulted: <sources cited by path, or "none found; searched <the bounded list>">`

  The search is **bounded to a named list** — `CLAUDE.md`, `CONTRIBUTING.md`, and testing guidance under the repo's configured internal-docs path — with the **consumer prompt extension** as the override point naming where that repo's conventions live; cite sources by path when found. The record is a **claim to verify, not an attestation to accept**: the Step 3.6 auditor re-runs the search and flags the line when a governing matrix sits at a path the line omits, never on a judgment call about what counts as governing — **except on Step 3.6's degraded inline arm, where no auditor re-runs it and the record is attestation-only**, which that arm's mandatory `degraded` audit-summary marker already signals.

  **Move 2a also fires on *introduction*, not only on narrowing.** An issue that introduces a **reader of input the repo does not itself produce** — historical records, user- or reporter-controlled text, an external structured format, agent- or human-mutable markdown — **enumerates that input's malformed / boundary shape matrix in the Testing Strategy**, appropriate to the input's type, including **at least one production-realistic fixture** (a real captured record, not only a hand-built well-formed token). A deliberately narrower enumeration states its **justification**. A **blanket testing-scope waiver** ("this artifact has no desk test", "the parser itself is untested") is **non-conforming**; a conforming waiver states what **inside the exempted artifact remains governed** — which behavior is still covered, and by what.

  **Move 3 — Commit to named assertions.**
  - **Every AC maps to at least one named assertion, and every assertion maps back to an AC** — no orphans in either direction; **and every state a multi-state contract enumerates maps to ≥1 AC** (a status enum, an outcome-token set, an error/exit-code set, or a state-machine node — the *contract-enumeration* sense of "state", distinct from the runtime *State, concurrency & idempotency* coverage dimension above). If an AC cannot be pinned by any assertion, it is not testable as written: tighten it, or it belongs in `## 🚫 Blocked`.
  - Each assertion is **test-first**: written before the code, it must fail first *for the right reason* — and spell that reason out. For a *feature*, the right reason is that the behavior does not exist yet. **For a bug fix, the right reason is that the test reproduces the reported defect** — the regression test must fail against today's code by exhibiting the exact wrong behavior (the dropped last row, the off-by-one), then pass after the fix. "Behavior doesn't exist yet" is the wrong framing for a bug; the wrong behavior already exists.
  - **A mechanical claim is verified-or-obligation, never a bare prediction.** When an assertion states a mechanical outcome — "running X reports Y", "the extractor/grep/command emits Z", "this must fail RED reporting W" — take exactly one of two decided forms: **(a) verified** — you actually ran the extraction/grep/command while drafting the issue and cite its **observed** output, or **(b) an obligation** — write it as a requirement on the implementer ("the pin must cover X"), **never** a prediction of the specific result Y/Z/W you did not execute. An unverified mechanical prediction reads exactly like a decided requirement and sends the implementer to re-derive (or encode) a falsehood. The same discipline governs **Relevant Classes/Files line anchors**: cite the symbol or section, not a `file:line` number, which rots between drafting and implementation.
  - Name the **fixtures / test doubles** the failing test needs, and what must **not** be mocked — never mock the unit under test or the boundary the assertion is proving.
  - **Don't test the framework.** Assert observable behavior (the CSV bytes round-trip through a standard parser, the row count, the raised error type), not internal wiring or library internals (a specific transport header the framework sets, a private call count) *unless that wiring is itself the AC*.
  - **Guarantee-class changes** (the deterministic backstop / hook / gate mechanisms on the Step 2 strength ladder): the test must prove the guarantee holds **on the path where the actor skipped the manual step** — that is the entire reason the mechanism exists. Assert it fires (and is idempotent) when a human or agent *forgot* the cooperative step, not only when everyone cooperated.

  **If no automated test applies** — the deliverable is prose, marketing copy, pure config with no consumer behavior, or a DSL with no observable boundary — say so with the one-line reason, then give the stand-in as a **reproducible verification**: a numbered manual checklist or an adversarial trace of the input shapes the change must survive, each item tied to an AC and concrete enough that a second reviewer reaches the same verdict. "Confirmed by review" alone is not a plan — state *what* the reviewer checks and *how they know it passed.*
- **Documentation Needed** — what doc updates the change requires. Write each deliverable as one bare backticked path per span (`` `docs/foo.md` ``); command and grant literals in this block (`` `bash ./run-tests.sh` ``, `` `Bash(x.sh:*)` ``) are never deliverables and are suppressed by the path extractor. To declare that **no** documentation is needed, open the block with the standalone word `none` (optionally followed by one of `,.;:`) — e.g. `none.` — and then explain why, naming any already-correct file freely; the extractor examines only that first `none` and does not turn a path you mention afterward into a mandatory deliverable. The word must stand alone: an ordinary sentence opening `None of these …` is not the declaration and still extracts its paths.
- **Potential Gotchas** — pitfalls and architectural constraints (these are warnings, not unresolved choices).

### 🚫 Blocked — resolve before implementation (include only if non-empty)
The **only** place unresolved decisions may appear. Include this section when the user disengaged in Step 2 leaving Definition-of-Ready items open — **or** when the relied-on third-party-behavior ladder (see *Technical Context* above) terminates with a load-bearing external premise that is neither documentation-verified nor proven by an in-repo example: that ladder-produced vendor-behavior question is the one Blocked entry class not arising from user disengagement. Each item is a direct question plus one line on why it blocks work:

```markdown
## 🚫 Blocked — resolve before implementation
- **Link access model?** Public-with-token or login-required — changes the data model and
  the security review. Implementation cannot start until this is chosen.
```

Do not soften these into "options" or attach a default. If this section is empty, omit it entirely — do not write "Open Questions: none".

## Full-stack awareness

When a feature touches the frontend, trace the data flow back to the backend changes it needs (new endpoints, schema changes, service methods, updated responses). When it touches the backend, ask whether the frontend must change to consume the new data. Map the whole path from database through API to UI; a UI-only description produces an incomplete issue.

## Quality checklist (verify before posting)

- [ ] Title is clear, action-oriented, and scoped to one feature/fix
- [ ] Problem statement explains the "why" and names who benefits
- [ ] Desired Behavior is stated as one decided behavior, not a menu
- [ ] Technical Context opens with the standardized scope note, included verbatim
- [ ] Technical context cites real file paths / class names from this project
- [ ] Open cross-issue prerequisites are listed in `## Dependencies` as `Blocked by #N — <reason>` lines, per the *Dependencies* section above
- [ ] For a user-visible UI change, the Visual Specification section carries what that section above requires; non-UI issues omit it entirely
- [ ] Acceptance criteria are measurable, testable, and unconditional
- [ ] Each AC states what is true after the change rather than what the diff contains (untouched-surface shape excepted) — *Acceptance Criteria*, first bullet
- [ ] Criterion apparatus is sorted by the consequence test and the grounding block opens the section — *Acceptance Criteria*, grounding-block bullet
- [ ] Quantitative ACs name their measurement instrument — *Acceptance Criteria*
- [ ] Value-comparison ACs/assertions are grounded by a boundary-covering probe or a named implementer obligation carrying its execution-tier constraint — *Acceptance Criteria*
- [ ] Every universal quantifier the body asserts about the system under change, outside `## 🚫 Blocked`, is pinned, scoped, or removed — *Acceptance Criteria*
- [ ] No AC forbids a surface (a path, a file class, a tier) that another AC's discharge must touch — the ACs are mutually consistent
- [ ] An AC establishing a trust/integrity boundary over executable artifacts defines the protected set over the transitive source/exec/import closure of its entry points, or states the residual unprotected surface explicitly
- [ ] A Testing Strategy enumerating a case matrix for a convention-governed surface carries the full matrix (or a named, justified narrowing) and its `governing conventions consulted:` line — *Implementation Notes*, Move 2a
- [ ] The draft's own unstated mechanism dependencies have their existence determined and are routed per Step 3.5's item 4 (`skills/create-issue/references/step-3-5-steelman.md`), an undetermined one recording **not established**
- [ ] Every relied-on third-party behavior went through the WebFetch → WebSearch → ask-the-user ladder with its source recorded, or became a Blocked question / flagged assumption — *Technical Context*
- [ ] Every "Verified:" bullet carries a self-contained re-derivation handle — the repository path in backticks plus the sentence quoted verbatim from it
- [ ] A premise verified as "the code does X" was read with its enclosing gates/conditionals and their defaults on the path to X, and any claim that holds only under a non-default configuration states that precondition inside the claim
- [ ] A designed LLM/semantic-judgment surface over third-party text carries the input-is-data guard AC paired with a hostile-input Testing Strategy case — or cites the already-guarded judgment path it reuses; a draft with no such surface adds nothing here
- [ ] Every enumerated test/case/example list inside an AC declares its form (`at minimum` floor marker or an explicit closed-set statement), and each floor-marked list has had Move 2's coverage sweep written back as closed AC items
- [ ] Implementation notes describe a single chosen approach (the `Relevant files` block excepted — a floor-declared map, hedges permitted)
- [ ] Testing Strategy runs all three moves and names test-first assertions, every AC mapped to at least one assertion and no orphans — bug fixes reproduce the defect first; guarantee-class changes test the skipped-step path; or it names a reproducible stand-in verification
- [ ] **No-options gate passed**: no choice/hedge/deferral language outside `## 🚫 Blocked` and the Implementation Notes `Relevant files` block
- [ ] Any unresolved decision is in `## 🚫 Blocked`, phrased as a question — nowhere else
- [ ] Edge cases and error handling are considered
- [ ] Architecture constraints are explicitly noted
- [ ] Documentation references are accurate

## GitHub autolink hygiene

The body is posted to GitHub, which turns `#`-number into a link. Never put a bare `#` before a number unless it is a real issue or PR reference — GitHub renders `#2` as a link <!-- pruned-path-ok: illustrative autolink-rendering example, not a citation --> to issue/PR 2 and misleads readers. For an ordinal, count, or list position, spell it out ("item 2", "step 3"). Genuine references like `#123` stay as-is. <!-- pruned-path-ok: illustrative autolink example, not a citation -->

## Posting the issue

**Precondition:** only run this after the user has seen the rendered issue and explicitly approved creating it (Step 4 of the calling skill). Never post a draft the user has not confirmed.

Create the issue **directly**, sourcing the body from the **single presentation source** — the same bytes the user approved. Which source depends on the epoch's arm:

**Consume the self-assignment answer.** Step 4 sub-step 5 obtains the user's answer to *"Assign this issue to you?"* before any creation command runs. Substitute `<assignee-args>` into the `gh issue create` call on **both** arms below: on an explicit **yes** it is the token pair `--assignee "@me"` (in the same create call, no post-create edit); on an explicit **no** it is **empty**, preserving unassigned creation byte-for-byte. Never invoke a creation command before that answer is an explicit yes or no — silence or any non-yes/non-no reply pauses and re-asks (Step 4 sub-step 5).

**On a file-arm epoch**, the body comes from the gated canonical file, via the state owner's gated `emit-body` emitter (neither a query nor a mutation: unlike a query it does not always exit 0 — it refuses with a non-zero exit and empty stdout). **Do not pipe it into `gh`**:

```bash
# WRONG — a refused emit-body exits non-zero with EMPTY stdout, and without pipefail
# `gh` still runs and creates an EMPTY-BODIED issue:
#   python3 .../issue-audit-state.py emit-body "<slug>" ... | gh issue create --body-file -
```

Instead emit to a temp file, **guard it non-empty, and only then post** — so a refusal stops creation rather than filing an empty issue. Do it in **one single statement** (a shell variable set in one statement and read in a later one of the same inline command is stripped by some runners' marshaling), and go through a file rather than a `"$(…)"` capture, whose trailing-newline stripping and re-added `printf '%s\n'` newline change the posted bytes against the recorded body-only digest. The file round-trip is **byte-exact**. Substitute `<main-root>` with the main working-tree root Step 4 sub-step 2 resolved via `resolve-main-root.sh` — a cwd-relative `.prflow/tmp/` may not exist inside a linked worktree. Hand the guarded file to `gh` via `--body-file <path>`, not re-piped through `cat`, whose absence would feed `gh` empty stdin; this temp file IS the gated `emit-body` output, so the never-`--body-file` rule does not apply here:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py emit-body "<slug>" --nonce "<nonce>" --draft-file "<absolute issue-draft-<slug>.md path>" > "<main-root>/.prflow/tmp/issue-body-<slug>.md" && test -s "<main-root>/.prflow/tmp/issue-body-<slug>.md" && gh issue create --title "Action-oriented title here" --body-file "<main-root>/.prflow/tmp/issue-body-<slug>.md" <assignee-args>
```

**On an embed- or inline-arm epoch** there is no trustworthy canonical file, so the body is re-emitted from context through a quoted heredoc (quoted so backticks and `$` in the markdown are not expanded). This is a **disclosed residual**, not the preferred path — the re-emission is not byte-identical-by-construction the way `emit-body` is:

The body below is a complete example to imitate. Study its shape and its plain voice, and do not copy its words into a real issue.

```bash
gh issue create --title "Action-oriented title here" <assignee-args> --body-file - <<'BODY'
## Problem Statement
Survey owners cannot share results with people who do not use the tool. The only way to hand someone a result set is a link that needs an account to open, so an owner who wants to email results to an outside manager cannot.

## Current Behavior
Results appear only on the web results page. There is no export of any kind, so an owner who needs an offline copy takes one screenshot per chart.

## Desired Behavior
An owner opens a finished survey and clicks Export as PDF. The tool builds a PDF holding every chart and table from the results page, in the same order, and downloads it. It opens in any PDF reader with no account.

## User Impact
Survey owners can share results with people outside the tool and keep an offline copy. Nobody else changes how they work.

## Technical Context

> **Scope note:** The files and details below are the known starting points, not the full list. Before implementing, trace the change through the codebase to find every affected call site, consumer, and layer — this issue maps the work, it does not bound it.

- Relevant Classes/Files — the report service that returns the results object, and the results page handler that renders it.
- Architecture Alignment — a new handler beside the results handler, not a change to how results are computed.
- Dependencies — one PDF-rendering library, chosen in planning.
- Data/Schema Considerations — none; the export reads existing data and stores nothing.
- Cross-layer Impact — a new backend endpoint and one button on the results page.

## Acceptance Criteria
- [ ] An owner viewing a finished survey sees an Export as PDF button.
- [ ] Clicking the button downloads a PDF that contains every chart and table shown on the results page, in the same order.
- [ ] The PDF opens in a standard reader without signing in.

## Implementation Notes
- Approach — add one export endpoint that reuses the results object and renders it to PDF, and one button that calls it.
- Relevant files — the results page handler and a new export handler beside it.
- Testing Strategy — one test drives the endpoint against a survey with two charts and asserts the PDF holds both, in order; a second test asserts the endpoint refuses a survey that is not finished.
BODY
```

**Do NOT add labels** — never pass `--label`. Step 4 applies the reserved `PRFlow` provenance label after creation, so passing it on the create call is redundant.

`gh issue create` prints the new issue URL on success. Report that URL back to the caller.

<!-- prflow:create-issue-ref step=issue-template file=skills/create-issue/references/issue-template.md end -->

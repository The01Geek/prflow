<!-- prflow:spec-ref step=3.5 file=skills/spec/references/step-3-5-self-audit.md start -->

### Step 3.5: Self-audit the draft against the code (mandatory, before the user sees it)

*"Self-audit this. Did we miss anything?"* — run that challenge against your own draft every run,
immediately after the no-options gate passes and before Step 4 presents anything.

This is a **code-grounded verification loop, not a re-read**. **Definition of verified**: an item is
verified only by a read made during this run — your own tool read, or a dispatched agent's returned
result naming the locator and quoting the text its read returned — whose returned text covers the
item's locator in the file as it still stands and confirms the item; a draft locator needs a read of
the draft's current bytes. For a recorded-input fact, the source or retained payload read under the
rule `references/issue-template.md` states for it counts as the file. A `check-verified-premises.py`
`state=holds` row shows only that the quoted text occurs in the cited file; its item still needs
such a read. An item no such read covers and confirms is unverified, whatever you recall; close it
with a targeted `Read` or `Grep`, never a full re-exploration.

1. Re-read the rendered draft end-to-end as an adversarial reviewer whose job is to find what is
   wrong or missing, not to admire what is right.
2. Verify each load-bearing claim, file reference, and acceptance criterion against the code. Every
   named file/path exists as named; every "the code currently does X" claim is confirmed by reading
   the code that does X; every AC is checked to be assertable against the code surface it names.
   Match the verification method to the claim class, by the clauses below; mechanical claims,
   recorded-input facts, occurrence counts and coupled-site lists, data-entity changes and replaced
   gates are verified against the rules `references/issue-template.md` states for them.

   Evaluate the assembled draft against the premises and contracts triggers in
   `skills/spec/SKILL.md`'s advanced quality-guidance routing table. At this pass, treat any
   internal code-behavior premise as uncertain premises-group applicability, even when the draft
   identifies no gated path. For these two groups, load any reference required by that routing and
   not already loaded; re-apply each loaded group's rules to verified reads, preserving
   each rule's applicability condition.

   Guard-claim grounding (mandatory). Read **Guard claims** in `references/issue-template.md`'s
   Acceptance Criteria section. A criterion resting on such a claim not verified under that rule and
   the definition above is treated as an
   **unverified premise to resolve before the draft is presented** — reported and revised under item
   5's revise-and-re-gate loop, never accepted on a peer's say-so whether one peer reported the
   guard or two.

   Universal-quantifier sweep (mandatory): scan every universal claim the assembled draft asserts
   about the system under change outside `## 🚫 Blocked`, found by what it asserts, never by keyword
   alone, and confirm each is grounded under **Universal claims** in
   `references/quality-group-contracts.md` (loaded per *Reference routing* if absent). A universal
   claim the draft keeps that describes existing behavior needs verifying under the definition
   above, with every clause of the text that confirms it read when that text has more than one,
   whichever way that section grounds it; one about current code so verified counts as scoped under
   that section, and one not so verified is ungrounded. Rewrite or ground any ungrounded quantifier in item
   5's revision; in approved or prescribed-verbatim wording, route that decision fork through
   `references/revision-delta.md`'s *Revision rule*.

   Request-origin sweep (mandatory). A criterion's admissibility test is stated once in
   `references/issue-template.md`'s Acceptance Criteria contract (**omit/merge/add**); read it there
   rather than restating it. Scan every acceptance criterion and every named Testing-Strategy
   assertion the assembled draft asserts, and grade each against that whole rule. The *request* is
   the words the filer actually supplied — Step 1's captured request and any Step 2 clarifications
   recorded in this run's derivation artifact — never the drafted issue restating them back. When
   this run cannot establish the request from that artifact — the unestablished-request case that
   rule defines — record that state in the summary and report each criterion and named assertion
   that rests on no change-introduced failure. Otherwise report each guarantee nobody asked for that
   the rule omits, including the plausible, individually defensible one (a startup-time
   validation, a "no such module exists" negative, a proof-of-extensibility stub), a preservation
   the change does not reach, and one the project's guidance already requires of every change. Except
   that last kind, a criterion or assertion that pins the change's own new behavior against
   regression, or covers an error path the change itself adds, rests on a change-introduced failure
   and is not reported, however far it sits from the request's own words. The drafter revises the
   reported items away under item 5's existing revise-and-re-gate loop, none when the request is
   unestablished; this sweep refuses no draft.

   Check `Verified:` bullets against **Re-derivation handles** in
   `references/quality-group-premises.md`. Step 3.6 alone runs and routes the premise-handle and
   acceptance-criteria parseability helpers; their commands live in `references/step-3-6-audit.md`.
3. Hunt for what the draft omits.

   Produce the projection disposition first, using the definition opening
   `references/issue-template.md`'s Acceptance Criteria section. Account for every Desired Behavior
   statement as `represented`, `unmatched`, or `non-obligation` under that definition. The
   disposition is `represented` only when the unmatched set is empty. Otherwise, revise the
   author-owned criteria under item 5 and re-check before creation.

   Check the draft against `references/issue-template.md`'s `Relevant files` and
   **Multi-state contracts** rules and the body against its rule for text with more than one clause,
   arm or ordered step, and apply its **AC mutual consistency — reconcile shared cases** rule to
   `## Acceptance Criteria`, `## Desired Behavior` and `## Implementation Notes`.

   When this run reached an implementation-approach question, a self-answered one included, check
   the draft, the record bucket and the `Considered-and-rejected:` line against the elected option's
   items in the latest *Option check* record and each rejection reason it marked not established; with
   that record absent, unreadable, not in the form Step 2's *Option check* requires, not covering
   the elected approach, or a subagent reply that check sends to your own check, list those items
   yourself under
   `references/step-2-clarify.md`'s *Option check* (`references/degradation-routing.md`'s
   clarification-fallback copy when that file did not load) and say so in the summary. An item or
   draft-stated limit meeting `references/step-2-clarify.md`'s *Settled approach* re-ask rule
   (the fallback's *Settled approach* copy when that file did not load) reopens the approach
   question. Each other item is handled by the draft, stated as an accepted limit, or stated as
   not established; revise any other under item 5.
4. Sweep the draft's own unstated mechanism dependencies (mandatory). Beyond the *stated* premises
   checked in step 2, name each in-repo capability the mechanism assumes and the behavior its
   consumer needs: a helper's exit code, a resolver's output shape, a gate's semantics. Include
   existence-shaped dependencies — a renderer mode, persisted field, subcommand, flag or config key
   — even when treated as ordinary machinery. Identify the producer and the consuming step before
   deciding how to establish the dependency.

   Determine existence, then route. For each enumerated dependency, first determine whether the
   depended-on capability is in the tree at drafting time — by a targeted `Read`/`Grep` applied to
   *is this here* rather than *what does this do* — and pick the discharge route from that
   determination. The determination's domain is the tree the drafter is authoring against; a
   capability the plugin itself provides is outside that domain when the plugin tree is absent,
   because a thin consumer install leaves the vendored tree untracked and materializes it at
   runtime. Resolve the plugin tree as the root of the plugin this run is executing from, before
   reading the search: the runner-reported absolute skill base directory's grandparent, consulted
   first. <!-- prflow:skill-dir-reported-base-first --> When the runner reports no base directory,
   the refusable fallback is an inline
   `echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"`
   whose printed path's grandparent is the root. Name no repository-root candidate and no
   vendored-root candidate: a capability whose producing surface would live in the plugin tree
   routes to that surface when a resolved plugin root exists, and otherwise to the single degraded
   outcome *plugin root unestablished* — a run on which neither channel yields a directory records a
   plugin-provided capability as not established, naming that channel, never present or absent,
   whatever the hit count. The determination has exactly three outcomes, complete by construction:

   - present — found and read in its producing surface, not merely mentioned in documentation,
     comments or fixtures. Establish the behavior the consumer needs, not just the capability's
     existence: apply **Value semantics** and **Enclosing gates** in
     `references/quality-group-premises.md`, loading it per *Reference routing* if needed. Discharge
     the dependency by a cited probe (a "Verified:" bullet citing observed output) or, when that
     probe is denied or unavailable on the drafting tier, an implementer-obligation AC naming the
     behavior to establish. A capability reachable only under non-default configuration is present
     with that precondition.
   - absent — the drafter named the producing surface that would own the capability (renderer, state
     owner, config schema, subcommand dispatch table) and, by reading it, established it is not
     there. **Promotion to absent requires that named-and-read producing surface *and* an executed
     search grounding
     it** — a zero-hit search alone never promotes, and a denied or unavailable search records not established even when the producing surface was read. That search is an executed **whitespace-normalized**
     search, here required to be repo-wide — a directory-scoped search does not establish an absence
     — and no citation of the command or its hit list is required in the issue body. Disposition,
     which the drafter states: inside this issue's scope, an implementer-obligation AC naming adding
     the capability as new work (stating the build, not implying a confirmation); outside scope,
     re-derive the mechanism under item 5. For that unresolved scope question, these dispositions
     override the ask-or-leave test: ask through Step 2's clarification routes; on disengagement or
     a non-interactive run, record the question with its one-line reason in `## 🚫 Blocked`, even
     when the underlying choice is routine implementer judgment. An absent determination never
     expands the issue's scope without that expansion being written down.
   - not established — any reading that is neither of the above (a zero-hit search with no producing
     surface read; a search denied or unsearchable at drafting time; a plugin-provided capability
     with no plugin tree present; ambiguous evidence). Recorded as itself — why it could not be made
     — not as a "Verified:" claim, and as neither of the other two. Discharged by an
     implementer-obligation AC whose first named unit of work is establishing whether the capability
     exists, naming a termination arm for every way that unit of work can end: proceed on the
     remaining criteria when it proves present; build it under this issue when it proves absent and
     in this issue's scope; file the build as deferred work through the existing deferred-follow-up
     path when it proves absent and out of this issue's scope; and, when the run cannot establish
     existence either, record the run Blocked on the criteria that depend on it rather than
     proceeding as though it were present. Write those arms as the obligation's own procedure, never
     as competing options for the drafter to resolve.

   The obligation-AC dispositions above are governed by **Obligation execution tier** in
   `references/quality-group-contracts.md`, which states its own reach over them — pointed at, not
   restated here. That group is conditionally loaded, so when an obligation arm fires and it is not
   already loaded, load it per the *Reference routing* rules before minting the obligation AC. A
   draft whose mechanism enumerates no dependencies performs no existence determination.

   Extend the sweep to stated-but-unbound inputs (mandatory): a mechanism input the draft describes
   by *role* — "the value the caller already tracks", "the branch diff it already has" — with no
   named referent is bound to a named variable, artifact, or file with a cited code reference
   proving it exists at the consuming site; when drafting cannot establish that binding, the draft
   carries an implementer-obligation AC naming the binding as work, never an unbound role
   description that expands to nothing at implement time.
5. Load `references/revision-delta.md` and apply its revision rule before editing for each finding.
   Fix the flaw yourself now (a request-origin report under an unestablished request is not a flaw)
   unless that rule routes a decision to the user; never present a fixable flaw as a question on
   an unrevised draft. Re-run the Step 3 no-options gate on the revision and
   run **Revision-delta verification**.
6. Report the outcome in your next message as a summary: each finding and what was revised for it;
   each check left unfinished and each checked item left unverified, by locator; each dependency not
   established and why; the request as unestablished when the request-origin sweep recorded that
   state; and, when Step 2's loader-failure arm fired, the evidence axes as floor-only-degraded. A
   check that found nothing needs no line. With nothing to report: "self-audit: no findings, nothing
   unverified, no revisions needed".

Only a draft that has survived this step — revised and re-gated if anything was found — proceeds to
Step 3.6.

<!-- prflow:spec-ref step=3.5 file=skills/spec/references/step-3-5-self-audit.md end -->

<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md start -->

### Revision-delta verification (shared procedure)

This procedure runs **at every revision event** — before any presentation of the revised draft. (A
"revision event" is one revise-and-re-gate occurrence; a multi-finding `VERDICT: REVISE` is one
event spanning several edits.)

**Revision rule.** Before editing for a finding or user request, route a genuinely unresolved
decision fork — including excluding a requested case or changing approved or prescribed-verbatim
wording — through `references/step-2-clarify.md`'s **One decided behavior per fork** and
clarification routes. Apply *Settled approach* in `references/step-2-clarify.md`, or its copy in
`references/degradation-routing.md`'s clarification fallback if `step-2-clarify.md` did not load; a
re-ask it requires goes through Step 2 before any edit for that finding. When the user keeps
approved or prescribed-verbatim wording at a fork, append `kept at fork: "<the wording>"` to a
`## Revision-delta record` section of this run's derivation artifact `.prflow/tmp/spec/<slug>/issue-derivation-<slug>.md`, creating the section on the first
line written (on a filesystem that refuses the append, follow
`references/fallback-read-only-sandbox.md`); wording no such line quotes is not kept. Apply the
routing rule below to the settled change, then run the verification steps on the edits.

Apply `references/issue-template.md`'s *Brief / investigation-record routing* to the attacked text
before composing a repair, whether or not the finding supplies one. Delete an attacked criterion the
template's omit/merge/add rule refuses, with its Desired Behavior sentence unless the request names
it or another criterion projects it. Move other attacked text the routing rule sends to the record,
or delete it if refuted. When that resolves the finding, leave no replacement in the brief; do not
replace a false incidental statement with a true incidental statement. For content the brief needs,
repair the remaining defect by changing the existing statement before adding explanation; add only
obligations needed to close that defect. Check places sharing the defect and route additions by the
same template rule. Replace prose the revision makes false or supersedes, and consolidate copies
serving no distinct role while retaining required projections, machine-consumer copies and
load-bearing findings.

A finding that a heuristic lists, misses or wrongly decides a case is answered by restating its
rule, failure direction or limit, never by adding the case, or refuted because the rule already
decides the case correctly.

The tests this rule applies, one line each, with `references/issue-template.md` their home:

- Vanish test's question: *if this sentence vanished, would the implementer build the wrong thing?*
- Never moved to the record: `## Dependencies`, `## Acceptance Criteria`, the `Documentation Needed`
bullet and `## 🚫 Blocked`.
- Reserved-surface check, which text moving to the record also passes: no consumer requires it in
the body.
- Admissibility test's two origins: the request named the guarantee, or a failure the change
introduces requires it; an unestablished request refuses nothing.

1. **Verify what the edit introduces.** Take the facts from the edit's own text, never from an
auditor's list: each mechanism, lifecycle rule, execution-tier assumption, dependency, universal
guarantee, file reference, value comparison and other load-bearing claim it introduces or changes, a
removal included. A wording fix, citation or narrowing that introduces no fact has nothing to
verify; a replacement stating current behavior, a universal or an environment-dependent claim does.
An item that adds a mechanism, changes what an amended rule outputs, redefines a term, or defines a
closed set first applies the *Bundle currency* update in `references/step-2-clarify.md` to the
bundle entries it touches, or re-marks them `unestablished — superseded by <the item>`. For each
introduced item, and each criterion or Verified: bullet relying on an entry updated or re-marked,
re-evaluate the premises and contracts triggers using Step 3.5 item 2's applicability rule; load a
newly required group per *Reference routing* before re-applying its applicable rules. Verify each
item with the delta-scoped reuse of the two existing Step 3.5 disciplines, referenced by discipline
name, never copied as a list: the load-bearing-claim premise verification of Step 3.5's item 2
(value-comparison grounding in `references/quality-group-contracts.md`; conditional-path and
value-semantics reading and the relied-on-third-party documentation ladder in
`references/quality-group-premises.md` — these groups loaded and re-applied under item 2's
routing; universal-quantifier grounding in item 2 itself; occurrence-count and recorded-input
grounding in `references/issue-template.md`) and the unstated-mechanism-dependency sweep of
Step 3.5's item 4 (with its existence-determination step and its stated-but-unbound-input binding
clause) — each item verified per the *Definition of verified* in `references/step-3-5-self-audit.md`. An item left refuted or
unverified does not land: its fact is removed from the edit or rewritten so the edit introduces
nothing unverified.
2. **Check the draft's consistency** on every revision, including one introducing no fact. Apply the
template's **AC mutual consistency — reconcile shared cases** rule to each addition, change or
removal and every statement whose meaning depends on it; a deletion an auditor proposes takes the
same check as your own edit. When a condition, outcome or exception changes, reconcile its dependent
statements together. Cover the finding's or request's triggering case and an existing case whose
behavior must remain unchanged. Check error paths and empty or absent inputs; give each obligation
an end condition. Apply Step 3.5 item 3's projection check: no Desired Behavior obligation remains
`unmatched`. Every accepted limit (a case the mechanism knowingly leaves uncovered) is stated by
each Desired Behavior sentence and criterion covering it; a user-decided narrowing is settled
behavior, not a limit. A disagreement, missing end condition or unpropagated limit is a
draft-consistency conflict. This reuses the existing checks on affected behavior; it does not re-run
Step 3.5.
3. Fix what point 2 finds inline under the revision rule, re-run the Step 3 no-options gate, and
check the fix under points 1 and 2, covering only its own edits; the loop ends when no
draft-consistency conflict remains outside wording a `kept at fork:` line quotes. This is the same
inline-revise shape as Step 3.5's item 5.

<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md end -->

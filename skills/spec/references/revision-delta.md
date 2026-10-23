<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md start -->

### Revision-delta verification (shared procedure)

This procedure runs **at every revision event** — before any presentation of the revised draft. (A
"revision event" is one revise-and-re-gate occurrence; a multi-finding `VERDICT: REVISE` is one
event spanning several edits.)

**Revision rule.** A finding meeting *Settled approach*'s re-ask rule in
`references/step-2-clarify.md` takes that re-ask through Step 2 before any edit for it, removal
included. After that re-ask, or immediately for any other finding, apply
`references/issue-template.md`'s *Brief / investigation-record routing* to
attacked text other than a case addition (below), whether or not the finding supplies a repair.
Delete an attacked criterion the template's omit/merge/add rule refuses, with its Desired Behavior
sentence unless the request names it or another criterion projects it. Without asking, move other
attacked text the routing rule sends to the record, or delete it if refuted; leave no replacement
in the brief and do not replace a false incidental statement with
a true incidental statement. This routing removes no never-moved section, approved or
prescribed-verbatim wording, and answers no user change request.

Among fixes this procedure permits, a finding or user change request is a decision for the user when
two or more fixes would build different things (a different outcome, scope, or file or consumer carrying the
change), the ask-or-leave test does not leave the choice to the implementer, and no request text or
recorded user answer chooses between them; a limit the change could raise, such as a byte budget,
never chooses, and a fix you cannot tell builds something different is asked. Excluding a requested
case and changing approved or prescribed-verbatim wording are also the user's. Route each decision
through `references/step-2-clarify.md`'s **One decided behavior per fork** and clarification routes;
a non-interactive run records it in `## 🚫 Blocked`. A fork a finding's fix raises about how a case
is handled includes an option to leave that case uncovered: remove only the text that exists for
that case and state the case as an accepted limit only in the criterion carrying it, wording each
Desired Behavior sentence covering it so it does not claim the case. When the user keeps approved or prescribed-verbatim wording at a
fork, append `kept at fork: "<the wording>"` to a `## Revision-delta record` section of this run's
derivation artifact `.prflow/tmp/spec/<slug>/issue-derivation-<slug>.md`, creating the section on the first
line written (on a filesystem that refuses the append, follow
`references/fallback-read-only-sandbox.md`); wording no such line quotes is not kept.

**Repair.** When no decision remains for the user, amend the affected statements and add only
obligations needed for the fix or requested change; add no reason clause the vanish test would remove.

For each finding you fix, search the draft and every file the finding cites
for other instances of the defect by its identifiers, literal text and subject words, read the hit
lines, opening surrounding text only where a hit needs it, and correct the draft for each instance;
search no other file and edit no repository file. When either search required by this procedure
fails, is refused, returns cut-short output or has no search tool to run on, disclose the affected
revision's unverified reach at its next presentation: the Step 3.5 summary, the statement under
`references/step-3-6-audit-dispatch.md`'s *After the round*, or beside Step 4's audit summary line,
whether or not a draft-check report still stands.
Route additions by the same template rule. Replace prose the revision makes false or supersedes, and
consolidate copies serving no distinct role while retaining required projections, machine-consumer
copies and load-bearing findings. Then run the verification steps on the edits.

A finding against a case addition — a case, clause, criterion or obligation you wrote in an earlier
revision event of this run to answer a finding that a case was missing, unhandled or had no
outcome, never text recording a user's answer or requested change — is answered by removing that
addition, with each statement that exists only to serve it and that the request does not name, and
stating the case as an accepted limit, even when a failure the change introduces requires the
addition (the admissibility test's second origin). Only when removing it would drop a case the
request names, repair the addition in place under **Repair** above. An
addition that fixed a contradiction or a missing end condition is not a case addition, nor is a
rewrite of first-draft text or text you cannot place or cannot tell is one. Against other text or
an addition repaired in place, a finding that a rule lists, misses or wrongly decides a case is
answered by restating its rule, failure direction or limit, stating the case as an accepted limit,
asking the user, or refuting it because the rule already decides the case correctly, never by adding
an arm or case the request does not name, except a missing member of a set whose members can all be
listed when the rule as stated already decides its outcome. Add such a member without asking;
a member needing a new outcome takes the decision test above. A case the request names is added.

The tests this rule applies, one line each, with `references/issue-template.md` their home:

- Vanish test's question: *if this sentence vanished, would the implementer build the wrong thing?*
- Never moved to the record: `## Dependencies`, `## Acceptance Criteria`, the `Documentation Needed`
bullet and `## 🚫 Blocked`.
- Reserved-surface check, which text moving to the record also passes: no consumer requires it in
the body.
- Admissibility test's three origins: the request named the guarantee, a failure the change
introduces requires it, or it carries an accepted limit the issue states; an unestablished request
refuses nothing.

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
(value-comparison and universal-claim grounding in `references/quality-group-contracts.md`; conditional-path and
value-semantics reading and the relied-on-third-party documentation ladder in
`references/quality-group-premises.md` — these groups loaded and re-applied under item 2's
routing; occurrence-count and recorded-input
grounding in `references/issue-template.md`) and the unstated-mechanism-dependency sweep of
Step 3.5's item 4 (with its existence-determination step and its stated-but-unbound-input binding
clause) — each item verified per the *Definition of verified* in `references/step-3-5-self-audit.md`. An item left refuted or
unverified does not land: its fact is removed from the edit or rewritten so the edit introduces
nothing unverified.
2. **Check the draft's consistency** on every revision, including one introducing no fact. Apply the
template's **AC mutual consistency — reconcile shared cases** rule to each addition, change or
removal and every statement whose meaning depends on it; a deletion an auditor proposes takes the
same check as your own edit. When a condition, outcome, exception, premise or universal claim
changes or is refuted, search the draft for every statement relying on it and reconcile them
together. Cover the finding's or request's triggering case and an existing case whose
behavior must remain unchanged. Check error paths and empty or absent inputs; give each obligation
an end condition. Apply Step 3.5 item 3's projection check: no Desired Behavior obligation remains
`unmatched`. Every accepted limit (a fact about the finished change's behavior the issue keeps: a
case the change knowingly leaves uncovered, or a decision not to change or test something) is
carried and stated only by a criterion under `references/issue-template.md`'s *Accepted limits*,
and no Desired Behavior sentence claims its case; a user-decided narrowing is an accepted limit
carried by a criterion. A disagreement, missing end condition, limit stated outside its criterion or
Desired Behavior sentence claiming a limit's case is a
draft-consistency conflict. This reuses the existing checks on affected behavior; it does not re-run
Step 3.5.
3. Fix what point 2 finds inline under the revision rule, re-run the Step 3 no-options gate, and
check the fix under points 1 and 2, covering only its own edits; the loop ends when no
draft-consistency conflict remains outside wording a `kept at fork:` line quotes. This is the same
inline-revise shape as Step 3.5's item 5.

<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md end -->

<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md start -->

### Revision-delta verification (shared procedure)

This procedure runs **at every revision event** — before any presentation of the revised draft. (A
"revision event" is one revise-and-re-gate occurrence; a multi-finding `VERDICT: REVISE` is one
event spanning several edits.)

**Revision rule.** A finding meeting the root's Step 2 *Re-ask* rule takes that re-ask before any
edit for it, removal included.
Apply `references/issue-template.md`'s *Brief / investigation-record routing* to attacked text
other than a case addition (below), even when the finding supplies a repair.

- Delete an attacked criterion the template's omit/merge/add rule refuses, and its Desired Behavior sentence
  unless the request names it or another criterion projects it; for a criterion refused because a
  rule the implementing run already follows requires its guarantee, the request naming it or that
  rule keeps no sentence.
- Without asking, move text routed out of the brief to the record, or delete it if the routing
  omits it or a finding refutes it.
  Leave no replacement; never replace a false incidental statement with a true incidental statement.

These actions remove no never-moved section or approved or prescribed-verbatim wording, and
answer no user change request.

Among fixes this procedure permits, a finding or user change request is a decision for the user when
two or more fixes would build different things (a different outcome, scope, or file or consumer carrying the
change), the ask-or-leave test does not leave the choice to the implementer, and no request text or
recorded user answer chooses between them; a limit the change could raise, such as a byte budget,
never chooses, and a fix you cannot tell builds something different is asked. Excluding a requested
case and changing approved or prescribed-verbatim wording are also the user's. Ask each such decision
directly under the root's Step 2 ask budget. A fork a finding's fix raises about how a case
is handled includes an option to leave that case uncovered: remove only the text that exists for
that case and state the case as an accepted limit only in the criterion carrying it, wording each
Desired Behavior sentence covering it so it does not claim the case. When the user keeps approved or prescribed-verbatim wording at a
fork, append `kept at fork: "<the wording>"` to a `## Revision-delta record` section of this run's
derivation artifact `.prflow/tmp/spec/<slug>/issue-derivation-<slug>.md`, creating the section on the first
line written (on a filesystem that refuses the append, follow
`references/fallback-read-only-sandbox.md`); wording no such line quotes is not kept.

**Repair.** When no decision remains for the user, amend the affected statements and add only
obligations needed for the fix or requested change; add no reason clause the vanish test would remove.
When the current and earlier findings you hold show the same design element, first-draft text
included, repeatedly repaired and support a concrete removal or reuse of it, weigh that candidate
before repairing it again: it is simpler only when it keeps the requested behavior and recorded
decisions and constraints and leaves less work overall, never when it moves required handling
elsewhere. A simpler candidate takes the decision test above like any other fix; recurrence adds no
re-ask. Otherwise, repair as above.

For each finding you fix, search the draft for other instances of the defect by its identifiers,
literal text and subject words, and correct the draft for each instance, which counts as text the
finding attacks;
search no other file and edit no repository file. When that search
fails, is refused, returns cut-short output or has no search tool to run on, disclose the affected
revision's unverified reach at its next presentation, under
`references/step-3-6-audit-dispatch.md`'s *After the round* or beside Step 4's audit summary line,
whether or not a draft-check report still stands.
Route additions by the same template rule. Replace prose in the draft or record bucket that the
revision makes false or supersedes, and consolidate copies serving no distinct role while retaining
required projections, machine-consumer copies and load-bearing findings. Then run the verification steps on the edits.

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
- Never moved to the record: `## Dependencies`, `## Acceptance Criteria` and `## 🚫 Blocked`.
- Reserved-surface check, which text leaving the brief also passes: no consumer requires it in the
body.
- Admissibility test's three origins: the request named the guarantee, a failure the change
introduces requires it, or it carries an accepted limit the issue states; a documentation update
the template's **Documentation criteria** rule omits (read it there if unloaded) is omitted whatever its origin,
as is a guarantee **omit/merge/add** omits because a rule the implementing run already follows requires it (read it there if unloaded);
an unestablished request refuses nothing.

1. **Verify what the edit introduces.** Take the facts from the edit's own text, never from an
auditor's list: each mechanism, lifecycle rule, execution-tier assumption, dependency, universal
guarantee, file reference, value comparison and other load-bearing claim it introduces or changes, a
removal included. A wording fix, citation or narrowing that introduces no fact has nothing to
verify; a replacement stating current behavior, a universal or an environment-dependent claim does.
For each
introduced item,
re-evaluate whether `references/quality-group-premises.md` and
`references/quality-group-contracts.md` apply, treating any internal code-behavior premise as uncertain premises-group applicability, even
when the draft identifies no gated path, and any universal claim about the system under change
outside `## 🚫 Blocked` as uncertain contracts-group applicability; load a newly required group per
*Reference routing* before re-applying its applicable rules, preserving each rule's applicability
condition. Verify each item against those groups' rules (value-comparison and universal-claim
grounding in `references/quality-group-contracts.md`; conditional-path and value-semantics reading
and the relied-on-third-party documentation ladder in `references/quality-group-premises.md`) and
the claim-class rules `references/issue-template.md` states (mechanical claims, occurrence counts
and coupled-site lists, data-entity changes and replaced gates); when the edit adds a guard claim
load `references/quality-group-premises.md` for its **Guard claims** rule, and when it adds a
recorded-input fact load `references/quality-group-rule-text.md` for its recorded-input rules, each item verified per the *Definition of verified* in `references/standards.md`. An item left refuted or
unverified does not land: its fact is removed from the edit or rewritten so the edit introduces
nothing unverified.
2. **Check the draft's consistency** on every revision, including one introducing no fact. Apply the
template's **AC mutual consistency — reconcile shared cases** rule to each addition, change or
removal and every statement whose meaning depends on it; a deletion an auditor proposes takes the
same check as your own edit. When a condition, outcome, exception, premise or universal claim is
added, changes or is refuted, search the draft and record bucket for every statement relying on it
or stating the same case, whatever its section, and reconcile them together. Cover the finding's
or request's triggering case and an existing case whose behavior must remain unchanged. Check
error paths and empty or absent inputs; give each obligation an end condition. Under the projection
definition opening `references/issue-template.md`'s Acceptance Criteria section, no Desired
Behavior obligation is left without a criterion. Every accepted limit (a
case the change knowingly leaves uncovered, or a decision not to change or test something) is
carried and stated only by a criterion under `references/issue-template.md`'s *Accepted limits*,
and no Desired Behavior sentence claims its case; a user-decided narrowing is an accepted limit
carried by a criterion. A disagreement, missing end condition, limit stated outside its criterion or
Desired Behavior sentence claiming a limit's case is a
draft-consistency conflict.
3. Fix what point 2 finds inline under the revision rule, re-run the Step 3 no-options gate, and
check the fix under points 1 and 2, covering only its own edits; the loop ends when no
draft-consistency conflict remains outside wording a `kept at fork:` line quotes.

<!-- prflow:spec-ref step=revision-delta file=skills/spec/references/revision-delta.md end -->

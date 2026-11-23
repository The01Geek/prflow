<!-- prflow:spec-ref step=standards file=skills/spec/references/standards.md start -->

### Draft standards

Check the draft for the mistakes drafts most often make:

- Overstatement: a claim about every, any, all or none, or a prediction, that says more than a hand-back states.
- A statement about current code, or about what something does when it runs, that no hand-back states as established, the request's account of it included unless attributed to the requester; one it marks not established written past its established level.
- Two statements or criteria that give the same case different outcomes, or two criteria that cannot both hold: walk each criterion against every other one.
- A search or sweep criterion ("no reference to X remains", "every Y has Z") that another criterion, or a file the change itself must add or keep (its tests, fixtures, migration, changelog or docs), would make fail: check it against each of them and write the exemption into the criterion.
- A check, gate or stop condition the draft adds (a count before a step runs, a precondition, a guard) that does not say what happens on each of its outcomes, or whose trigger does not cover every value the reports show the behavior can take.
- A fact the run holds (a condition the request states, a user answer, a hand-back fact, a run's choice) that the draft drops, contradicts, or carries though it no longer applies to the chosen approach.
- A Desired Behavior obligation that no acceptance criterion carries.
- A promised outcome that an existing check, gate or step which runs earlier would stop.
- A relied-on limit (`references/shared-rules.md`) the run established that the draft omits, states only as out of scope, or leaves away from that requirement (the root's *Relied-on limits*).

Surplus text (a criterion the change does not need, a restated rule, run history) is not on this list: the leanness pass looks for it.

When the repository's spec extension has an `## Audit dimensions` section, also check the draft against each dimension this prints, the text every auditor is given:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh spec --section '## Audit dimensions'
```

A failed run, or no output, leaves the check to the list above; say so in its chat line.

Fix each one under `references/revision-delta.md`, preferring to delete or narrow text over adding it. Then say in one chat line what you changed, or that nothing needed changing.

**Definition of verified**: an item is
verified only by a read made during this run and returned by a dispatched worker, or made by you where the root has you do a worker's or auditor's job, naming the locator
and quoting the text its read returned, in its hand-back, its report file or an audit return (your
own read of this run's draft counts for a locator in it), whose returned text covers the item's locator in the file as it
still stands and confirms the item; a draft locator needs a read of the draft's current bytes. For a
recorded-input fact, the source or retained payload counts as the file. A `check-verified-premises.py`
`state=holds` row shows only that the quoted text occurs in the cited file; its item still needs
such a read. An item no such read covers and confirms is unverified, whatever you recall; state it at
the level that is established, or close it as the root's *No fact-check before drafting* allows,
never with any other read of consumer source by you.

<!-- prflow:spec-ref step=standards file=skills/spec/references/standards.md end -->

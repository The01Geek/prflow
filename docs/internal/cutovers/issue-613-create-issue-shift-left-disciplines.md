---
schema: 1
kind: growth
---
# Issue #613 — create issue shift left disciplines (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `.prflow/prompt-extensions/create-issue.md`

## Justification

- These mandatory bytes move five defect classes from the create-issue pipeline's most expensive
  seat — a Step 3.6 audit round, which costs a fresh subagent dispatch, finding verification, a
  revision, and a re-gate — to Step 2 and Step 3, where the design is still cheap to change. The
  classes are the ones the #591 drafting run's steelman and audit rounds actually caught:
  consumer/mirror enumerations grounded in file reads rather than executed sweeps, closed sets
  defined with no complement analysis, execution-shaped obligations walked against the merged tree
  instead of the pre-merge implementing run, measurement assertions observable only on their
  failure path, and self-referential counts that rot on revision.
- The growth rides the extension's existing sections rather than new bullets: the two evidence
  rules are `## Evidence axes` section prose, the remaining disciplines are appended inside the
  existing authoring-discipline `## Audit dimensions` bullet, and only the no-options-gate scan is a new
  section — which sits outside both hook sections, so neither hook's extracted payload grows by a
  bullet. The two section bullet-count pins (9 dimensions, 5 axes) are byte-unchanged.
- Ownership does not transfer and no prose is superseded: every rule is a new obligation with no
  prior owner, so no pin is retired and no cutover disposition applies.

---
schema: 1
kind: growth
---
# Issue #656 — prompt mass growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `CLAUDE.md`

## Justification

- Issue #656's AC8 requires the general authoring rule to be recorded in `CLAUDE.md`
  Conventions: *prefer generated evidence over exact checked-in numbers, EXCEPT where an exact
  literal is itself the enforcement.* The rule governs what a future author does **before**
  they write a figure, so it has to be resident where authoring decisions are made — a
  reference the author only reads after already hand-transcribing a number would fire too
  late to prevent the defect it exists to prevent.
- The bullet is not relocatable under the "Prose cutover" rule. That rule authorizes removing
  decision-owning mandatory prose only once an executable helper is the **sole tested owner of
  the decision on every path**. Here the new helper (`lib/test/rb-figure-partition.py`) owns
  *detection* — it REDs on a governed figure that is in neither the live-reconciled nor the
  registered-exempt set — but the **classification** it depends on is author judgment the tool
  cannot make: whether a given literal is a live measurement, a past-time snapshot, an
  enforcement constant, or a future target is precisely what a human decides when registering
  the exemption. The tool enforces the partition; the prose is the only owner of how to
  partition. So the prose stays mandatory.
- The steelmanned exception is carried in the bullet rather than dropped, and that is the part
  that earns its bytes. A bare "always generate figures" rule would demand vacuous or
  impossible guards — a historical measurement cannot be re-derived, an enforcement constant
  *is* the comparand the check reads, and pinning a future target traps the very change that
  moves it. Stating the three sanctioned exception classes inline is what keeps the rule
  applicable instead of routinely violated, and each is one clause, not a paragraph.
- The bullet was **tightened before landing**: the first draft cost +1372 bytes and the shipped
  form costs **+1063**, a ~22% reduction taken by cutting mechanism narration (the
  `_rb_words`/positional-cell walkthrough) down to a bare pointer at the reference
  implementation, while preserving every element AC8 mandates — the rule, the three-class
  steelmanned exception, the per-exemption rationale requirement, and the never-machine-render
  provenance rule for frozen figures. The mechanism detail lives in the code and in
  `docs/review-bundle-budget.md`, which is where a reader who needs it already looks.
- No other mandatory-surface file grew: the census reports `CLAUDE.md` as the single changed
  row. The rest of the change is test infrastructure (`lib/test/`) and the budget record, none
  of which is a prompt-mass census member.

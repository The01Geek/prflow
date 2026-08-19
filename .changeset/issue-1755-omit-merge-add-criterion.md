---
bump: patch
type: Changed
---

- **`/prflow:create-issue` now grades every candidate acceptance criterion through an omit/merge/add test before adding it.** The always-loaded acceptance-criteria contract states one rule: a candidate that is not admissible is omitted, a candidate an existing same-evidence criterion can carry is merged into it, and only a candidate that is neither is added — and each added criterion records a one-line disposition in the run's `.prflow/tmp/` derivation artifact, which Step 4 confirms against the drafted criteria before presentation. The admissibility test moves into that contract from the Step 3.5 steelman (which now points at it), and the conditionally-loaded quality groups and the audit-adjudication revise step carry a pointer to it, so a run that loads no quality group still gets the rule. Nothing here refuses, blocks, or pauses a draft, and no count or threshold gates anything. (#1766)

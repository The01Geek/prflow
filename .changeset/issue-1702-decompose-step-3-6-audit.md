---
bump: patch
type: Changed
---

- **Decompose the create-issue Step 3.6 audit reference below the single-read ceiling.** The 72 KB `step-3-6-audit.md` is split into a small entry reference plus an ordered set of cohesive procedure members (shared procedures, dispatch, adjudication), each under a 55,000-byte authoring limit with the combined source bytes held within the pre-refactor total. The size lint enforces both the per-member ceiling and the aggregate budget, the audit-lifecycle checker and the create-issue routing/marker contracts resolve across the declared member manifest, the context evaluator verifies equal case identities before comparing median runtime main-thread cost, and the obsolete size exemption is retired — restoring a durable fresh-context audit path that no longer depends on one runner's tokenization margin. (#1704)

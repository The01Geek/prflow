---
bump: patch
type: Changed
---

- **Removed unnecessary rationale prose from the `/prflow:implement` skill.** The skill drops 9,444 bytes (1.8%), from 516,979 to 507,535, across 18 of its 20 files. The bar for this pass was deliberately conservative: a consequence was removed only when it directed no action and stated no fact used anywhere else, and anything potentially needed was retained. Most of what went is design history, provenance notes and duplicated motivation rather than consequence prose in the strict sense. Every instruction, routing target, condition, threshold, arm, ordering and output shape is unchanged, all 513 test-asserted literals are intact, and the cross-pass coherence rule's two coupled mirror sites remain byte-identical.

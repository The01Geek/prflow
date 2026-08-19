---
bump: patch
type: Changed
---

- **Removed rationale prose from the `/prflow:create-issue` skill and its 27 references.** The corpus drops 23,697 bytes (6.4%), from 369,588 to 345,891, across 25 of 28 files. The sweep deletes only sentences and clauses whose sole job is to explain why a rule exists or what breaks if it is skipped; every operative instruction, routing target, condition, threshold, arm, ordering and output shape is retained, as are all boundary markers, renderer slot tokens and the reconciled degradation-routing table. Rationale that states a runner, host or install fact available nowhere else in the skill was kept, along with the plain-language authoring guidance protected by consumer feedback. Three files came back unchanged because every sentence in them is an arm or a condition.

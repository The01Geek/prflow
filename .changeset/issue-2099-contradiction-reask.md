---
bump: patch
---

Re-ask the checklist verifier once when a FAIL asserts the code is correct but leaves the property unproven (#2099).

`scripts/normalize-verdicts.py` now treats a well-typed `inaccuracy_scope: "generated_claim_text"` paired with boolean `property_proven: false` as a contradiction rather than a settled verdict: when property-not-proven is the sole real-value blocker, the item draws exactly one pinned auxiliary re-ask through the existing channel instead of terminating as normalization-ineligible. A re-ask that positively proves the property normalizes the FAIL through the unchanged five-conjunct predicate; any other outcome leaves the raw FAIL standing, so review strictness is unchanged for every real defect. The two verifier-contract mirrors (`skills/review/phases/phase-2-verification.md`, `agents/checklist-verifier.md`) now state the coherence rule so verifiers stop emitting the contradictory pair as a settled answer.

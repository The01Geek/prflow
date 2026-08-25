---
bump: patch
type: Fixed
---

- **The review-coverage `roster` axis is now cross-checked against a per-member shadow enumeration instead of being a self-report.** `scripts/workpad.py` gains a `--record-roster-member` flag and a `_review_roster_incoherence` validator (checked at write time and at the `Status: Complete` read-time gate): `roster=complete` is refused unless every always-on shadow reviewer is recorded `dispatched` and no member is `missing`, while a member excluded by its applicability gate (`gated-off`) does not block complete, and `roster=short` must name a missing member. The fix loop now records the enumeration alongside the coverage record, and the shipped prose states that the in-loop Phase 3 roster and the shadow roster are separate, non-substitutable obligations. So a shadow narrower than the expected roster can no longer record `roster=complete`. (#1945)

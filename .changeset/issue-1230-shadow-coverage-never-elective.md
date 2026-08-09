---
bump: patch
type: Changed
---

- **The fix loop's shadow pass can no longer be skipped as a budget decision.** `coverage: "not_verified"` is now stated to be never elective — a consequence of a shadow shortfall rather than a cost lever — so a run that cannot afford the pass dispatches it anyway, a fan-out that ran and fell short records the shortfall whatever its cause, and a run that never dispatched stops at a non-terminal or `Blocked` status instead of reporting `Complete`. `/prflow:implement`'s Phase 3.3 wording, which described that path as something the loop chose, now describes it as the shortfall it is. (#1474)

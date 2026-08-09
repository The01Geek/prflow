---
bump: patch
type: Changed
---

- **The fix loop's shadow pass can no longer be skipped as a budget decision.** `shadow-review.md` now states that `coverage: "not_verified"` is never elective: it is produced only by the conditions the honest-degradation fail-safe enumerates, whose trailing residual is a degradation bucket rather than an opt-out. A run under cost pressure dispatches the shadow; one that genuinely cannot dispatch stops at a non-terminal or `Blocked` status naming budget exhaustion instead of writing `Complete` over an invented degradation cause. The rule binds the local and cloud tiers identically. `/prflow:implement`'s Phase 3.3 wording, which described the not-verified path as something the loop chose, now describes it as the shortfall it is. (#1474)

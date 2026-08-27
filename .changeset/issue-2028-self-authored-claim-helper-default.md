---
bump: patch
type: Changed
---

- **Self-authored-claim sweep traces an invoked helper's default invocation mode.** Step 2 of
  the Phase 2 self-authored-claim reconciliation sweep (`skills/implement/phases/phase-2-sweeps-quality.md`)
  now directs a claim about how an invoked helper runs by default to that helper's argument parsing
  and environment-variable defaults, not only its documented purpose, so a claim that holds only
  under a non-default flag is caught at commit time as a divergence. (#2032)

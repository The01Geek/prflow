---
bump: patch
type: Fixed
---

- **Give the fix loop's in-flight dispatch discriminator a durable operand.** The
  `pending_dispatch` stamp now records an `issued_by` field (the stamping reference's own
  `current_step`), so the fix loop's always-resident re-read rule decides its firing predicate
  and its absent-operand arm from the run-scoped `iter-<N>.json` alone rather than from the
  orchestrator's live context. A record written before this change (no `issued_by`) fails
  closed rather than reading as loop-issued. (#1788)

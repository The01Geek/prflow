---
bump: patch
type: Added
---

- **Decompose the `null` review-verdict residual into a per-agent disposition.** The review-agent
  efficiency record now carries, beside each agent's derived verdict, a `disposition`
  (`returned` / `failed` / `silent` / `unestablished`) and a `fix_decisions` roll-up, so a silent
  reviewer is distinguishable from one that failed and from one whose findings were all deferred.
  The residual is decomposed only over an established roster; a roster-absent or historical record
  reads as disposition-unestablished rather than silently shrinking the null denominator. Adds the
  `phase3_failed_agents` iteration field (the sink for a non-returning agent) and persists the
  shadow pass's per-reviewer assessment. (#1956)

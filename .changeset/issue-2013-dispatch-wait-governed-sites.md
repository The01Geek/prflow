---
bump: patch
type: Changed
---

- **State the subagent-dispatch wait behaviorally at the three governed implement dispatch sites.** The §1.4 branch-setup, §1.6 issue-claim-auditor, and §4.0 deferral-drafter dispatches now say the dispatch is discharged only by the subagent's completed return (with `run_in_background: false` named as the mechanism, not the wait), and each carries the same Dispatch-barrier pointer as Phase 2.1 (with its collect-every-dispatch local arm), extended at these sites with a local-arm clause that routes a runner-backgrounded dispatch to collect the completed return before routing and keeps the inline fallback from firing beside a still-running subagent in the shared checkout. (#2037)

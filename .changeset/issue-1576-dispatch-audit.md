---
bump: patch
type: Changed
---

- **`/prflow:implement` Phase 1.6 now dispatches the Issue-Claim Audit to a subagent.** The audit's pass procedure (count/enumeration, negative-scope, policy, execution-capability, verified-premise) moved out of `phase-1-setup.md` into the new first-party `issue-claim-auditor` subagent, which shares the run's checkout, writes the same per-pass workpad notes and reflections, and returns a structured record; the orchestrator keeps every decision, including the two terminal Blocked stops. This shrinks the re-read `phase-1-setup.md` while preserving audit behavior. (#1583)

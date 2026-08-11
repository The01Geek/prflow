---
bump: patch
type: Changed
---

- **Phase 3.4's Acceptance Criteria Gate now dispatches two fresh-context verifiers instead of resolving inline.** An `ac-evidence-verifier` establishes each in-scope criterion's verification evidence (the only one that runs an in-env verification command or touches single-flight) and an `ac-claim-verifier` checks the shipped code against each criterion's literal claim and executes nothing. The orchestrator reconciles the two per-criterion reports through `scripts/reconcile-ac-verifiers.py` — agreement records that status, any disagreement records `unestablished` (which blocks as an unmet criterion blocks), and a `satisfied` never lands without an evidence pointer — then drives the existing routing from the reconciled record. A verification command that passes while its assertions test a different claim than the criterion states no longer yields a satisfied status. (#1579)

---
bump: patch
type: Added
---

- **The `issue-claim-auditor` now states a disposition per chartered pass, enforced by a deterministic validator.** Its returned ISSUE-CLAIM-AUDIT RECORD carries a `pass<N>_disposition: ran|skipped (reason)` line for each chartered pass, and the Phase 1.6 routing runs `scripts/validate-issue-claim-audit.py` over the record before honouring `outcome: proceed`: a pass whose disposition is absent, `skipped`, malformed, or names a pass outside the charter turns the audit into a visible §1.6 refusal (naming the pass) instead of a silently-skipped pass that wastes a whole implement run. Mirrors the Named-steps contract the two AC verifiers already carry. (#1938)

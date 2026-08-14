---
bump: patch
---

Make create-issue's Testing Strategy a residual-risk supplement instead of a mirror of every acceptance criterion, and move exhaustive criterion-level verification accounting into the implement Phase 2 test-first gate.

`skills/create-issue/references/issue-template.md` Move 3 no longer requires the issue body to restate a named test for every already-clear acceptance criterion; it records only cases that add information beyond the criteria (bug reproduction, hostile-input pairing, new-mutable-input-reader matrices with their `governing conventions consulted:` record, guarantee-class skipped-step paths, retry/idempotency), each naming the risk it covers and the contract it protects — or, when none exists, one concise statement that the acceptance criteria fully express the verification contract. The Acceptance Criteria remain the exhaustive, merge-gated specification.

`skills/implement/phases/phase-2-sweeps-contract.md` gains a criterion-lifecycle accounting step: before any implementation code, the test-first gate enumerates every resolved workpad acceptance-criterion row and records each one's verification-lifecycle route (testable → named RED/GREEN assertion; genuinely-untestable Phase 2 deliverable → Phase 2.4 trace; documentation criterion → Phase 3.4 deferral then Phase 4.1 discharge; genuinely-live → the existing `(post-merge)` disposition) through the existing workpad note channel, exposing any uncovered criterion before implementation begins. See PR #1685.

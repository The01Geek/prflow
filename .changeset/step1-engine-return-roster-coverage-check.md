---
bump: patch
type: Changed
---

- **The fix loop's Step 1 engine-subagent return is now checked for Phase-3 roster coverage, symmetric with the Step 2.6 shadow entry.** `/prflow:review-and-fix`'s Step 1 previously accepted a `fanned-out` return whose required fields were merely present, so a subagent that under-fanned Phase 3 and returned a self-consistent `phase3_dispatched` read as well-formed on the primary merge-gating verdict path. The parent now computes the expected Phase-3 roster from the **returned** `diff_profile` (never the loop's last-iter profile) and treats a `phase3_dispatched` short of it as a not-well-formed return, which falls back to the existing inline path and runs the engine in the parent. No return field, status value, or config key is added, and the shadow's tripwire, 1:1 join, and `expected_reviewers` persistence remain shadow-only. (#1883)

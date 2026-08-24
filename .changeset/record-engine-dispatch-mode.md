---
bump: patch
type: Added
---

- **The fix loop now records how each review-engine entry ran.** `/prflow:review-and-fix`'s iteration record `iter-<N>.json` gains a top-level `dispatch_mode` for the Step 1 engine entry and a `shadow.dispatch_mode` for the Step 2.6 shadow entry, each carrying the entry's returned `fanned-out` or `unavailable`, or `null` when the value was not established. The fields are additive and conditional — every existing reader takes named keys and `ITER_EXPECTED_FIELDS` excludes them — so a run that silently fell back to running the engine inline is now distinguishable from a dispatched one without raw-transcript inspection. (#PRNUM)

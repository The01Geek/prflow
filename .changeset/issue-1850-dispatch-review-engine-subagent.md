---
bump: patch
type: Changed
---

- **The fix loop now dispatches the review engine as a subagent at both its engine entries.** `/prflow:review-and-fix`'s Step 1 and the Step 2.6 shadow pass each dispatch the review engine into an Agent-tool subagent that runs Phases 0 through 4.3 and fans out the Phase 3 roster from its own context, returning `dispatch_mode: fanned-out` with its results handed back by a file path; when the subagent holds no delegation tool it returns `dispatch_mode: unavailable` and the parent runs the engine inline exactly as before. This keeps the engine's instruction text out of the orchestrator's resident prefix on `/prflow:implement` runs, cutting the per-turn cache-read cost, with no change to review coverage. The fix loop stays the sole writer of `iter-<N>.json`. (#1883)

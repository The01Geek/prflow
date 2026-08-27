---
bump: patch
type: Fixed
---

- **Close the stale `diff.patch` reuse hazard in re-entrant review-engine entries.** In the
  `/prflow:review-and-fix` loop, every engine entry after the run's first — a Step 1 iteration
  from iteration 2 on, and every Step 2.6 shadow entry, on both dispatch arms — now deletes the
  run-scoped `diff.patch` and its Phase 1 batch slices immediately before dispatch, so the
  entry's own Phase 0.2 regenerates the diff at the current HEAD rather than reviewing a stale
  cache produced at a previous HEAD. Each re-entrant entry's return record carries the HEAD sha
  its Phase 0.2 produced the diff at, and the parent fails a missing or mismatched sha through
  the entry's existing failure handling. The shadow dispatch now carries the held `run_id` and,
  in PR mode, `head_override = local` as its Phase 0.2 caller inputs, and the Loop Exit
  widens-surface guard fails closed when the cached diff is absent instead of reading it as an
  empty diff. (#2057)

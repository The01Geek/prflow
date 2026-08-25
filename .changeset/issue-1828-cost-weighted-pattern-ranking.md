---
bump: patch
type: Changed
---

- **The weekly retrospective now ranks recurring patterns by rework cost, not frequency alone.**
  `lib/compute-patterns.jq` joins pattern occurrences to their PR's
  `efficiency_runs[].iterations` in the experiment records and derives a per-pattern cost
  aggregate (the mean over covered occurrences) plus the covered-occurrence count it was
  computed from; `lib/actionable-patterns.sh` then emits patterns ranked by descending cost,
  breaking ties by occurrence count, with zero-coverage patterns ranked last. The
  `min_occurrences` admission gate is unchanged, and a pattern with no covered occurrences
  records the absence as a null cost rather than a fabricated zero, so the fixed filing budget
  buys more rework reduction per week. (#1949)

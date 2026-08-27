<!-- prflow:implement-ref step=2.3.7 file=skills/implement/references/sweep-2-3-7-collection-cardinality.md start -->

#### 2.3.7 Collection-cardinality sweep (mandatory whenever the change adds a collection output with ordering, dedup, or aggregation logic)

No other 2.3.x sweep owns a collection output whose value depends on cardinality: a sorted list, a deduped set, a grouped or counted tally, a tie-broken ranking. That logic is invisible to a single-element test — one element is already sorted, already unique, already its own tally — so a happy-path test with one input passes while the ordering comparator, the dedup key, and the aggregation step are never exercised. The bug (a wrong or absent sort key, a dedup keyed on the wrong field, an off-by-one tally) ships clean and surfaces only when a review pass's test-coverage analysis, or a real multi-element input, finally hits it.

For each collection output the diff adds whose value depends on order, dedup, or aggregation, before running tests:

1. Identify it as cardinality-sensitive. A pass-through collection that neither sorts, dedups, nor aggregates is out of scope — it has no cardinality-sensitive logic to exercise.
2. The change carries a multi-element test case that exercises that logic: elements whose order matters (so a wrong or absent comparator is caught) and duplicates that must collapse (so a broken dedup key is caught). A single-element happy-path test does not discharge this sweep — it exercises none of the cardinality-sensitive logic.
3. When no automated test can drive the output (the deliverable is prose, an embedded DSL, or otherwise un-drivable per Phase 2.4), the obligation becomes the Phase 2.4 adversarial dry-trace run over a multi-element input — trace the ordering/dedup/aggregation step against at least two elements including a duplicate, never a single-element trace.

This multi-element ceremony is one of the three items waivable under the §2.3 test-authoring proportionality waiver: when writing it would balloon the test diff out of proportion to the change, ship the covering RED-first test and record the waiver instead. The covering RED-first test stays mandatory; only the multi-element cardinality case is waived.

Treat a cardinality-sensitive collection output shipped with only a single-element test as a defect in **this** PR, not a `pr-test-analyzer` finding to be caught downstream.

<!-- prflow:implement-ref step=2.3.7 file=skills/implement/references/sweep-2-3-7-collection-cardinality.md end -->

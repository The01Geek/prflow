---
bump: patch
type: Changed
---

- **Widen the implement silent-failure sweep to reach a default read of an unmeasured value.** The Phase 2.3.6 sweep's opening site list now also names a default-valued read of an absent, empty, or never-measured operand feeding a value the change measures, aggregates, or reports — a read that raises no error and skips no failing op, so the error-handling constructs the list already named never reached it. The section's existing fail-open and report-the-unverifiable rules then govern the newly-reachable site. (#1912)

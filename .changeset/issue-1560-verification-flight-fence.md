---
bump: patch
type: Changed
---

- **`/prflow:implement` Phase 4.3 now carries a complete, copy-pasteable fenced call site for
  the final-tree verification flight**, including the `claim` declaration template, which the
  shipped prompt surface did not previously document. The span no longer restates what
  `scripts/verification-flight.py` documents about itself, and its two dangling
  scope/parallelization pointers now state their own rules. (#1560)

---
bump: patch
---

Sweep batch 1 of the remaining brand-cased `DevFlow` prose to `PRFlow` (issue #1985, PR #1992): rename the product-name occurrences in 24 comment/docstring/prose files (`scripts/`, `lib/`, `docs/internal/shadow-review.md`, `.changeset/README.md`) and drain them from `pending_sweep_baseline` in `lib/test/brand-devflow-buckets.json`, dropping the baseline from 166 to 143 files. The swept files were selected to contain only current-product occurrences; the frozen buckets are unchanged (the baseline diff only removes drained pending entries) and the reconciling lint stays green. The remaining files — including those whose `DevFlow` is semantically frozen and those under `skills/`/`agents/`/prompt-extensions — are deferred to follow-up batches.

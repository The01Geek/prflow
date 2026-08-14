---
bump: patch
---

`/prflow:pr-description` now emits the `Generated via /prflow:implement (...)` provenance line as the last line of the PR body, below `<!-- PR_BODY_END -->`, instead of preserving it wherever it was found. The Phase 3.1 draft body carries no body markers, so the regenerator's no-markers rule had been hoisting the line to the top of the regenerated description.

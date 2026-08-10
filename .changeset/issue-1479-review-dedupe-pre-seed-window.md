---
bump: patch
type: Changed
---

- **`review_dedupe` now documents its pre-seed window and records the decided in-window behavior.** `scripts/dedupe-review-command.sh`'s header states that a peer review run's `prflow:review-progress` comment does not exist for a period after that run starts (a dated ~141 s observation on PR #1469), that the detector fails open through that window, and that fail-open is the decided behavior — chosen over an absence-keyed suppression (no liveness bound to age out) and a head-blind thread scope (both ruled out) — so the window is a transient timing exposure, not a numbered accepted cost. The internal docs now state duplicate suppression as conditioned on a published in-flight progress comment, and a negative-control test pins the fail-open outcome against a future widening of the `isprogress` filter. No behavior change to the shipped detector. (#1573)

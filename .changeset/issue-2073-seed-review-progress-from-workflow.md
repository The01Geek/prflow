---
bump: patch
---

Seed the review run's live-progress comment from the `devflow.yml` command job before the agent starts (issue #2073). The command job now runs a seeding step — ordered before the prompt-composition step, screening the same review commands the dead-run flip step screens, gated on `prflow_review.live_progress_comment_enabled`, and composing a seed body carrying the two `review_dedupe` machine-read keys — that invokes `scripts/seed-review-progress.sh` and hands the seeded comment id, marker, and run link into the agent's prompt. The review engine holds those pre-seeded values and composes no second marker; its Phase 0.3.5 seed stays the fallback for installs whose workflow predates the step. A failure in the seeding step warns and continues, so it degrades to the prior agent-side behavior instead of failing the review run.

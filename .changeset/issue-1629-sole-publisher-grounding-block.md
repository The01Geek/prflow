---
bump: patch
type: Added
---

- **State the sole-publisher rule in every review run's injected grounding block.** A new
  review-only section of `scripts/render-grounding-block.sh` (gated on the derived
  `REVIEWED_COMMIT=yes` selector) now tells every standalone review run that a verdict reaches
  the pull request only through Phase 4.4's emitter, and that a self-composed verdict comment is
  not a verdict — so a run that skipped the Phase 4.4 reference cannot mistake a hand-posted
  comment for an approval. The Phase 4.4 routing-table row of `skills/review/SKILL.md` now states
  that constraint rather than only the goal, and `scripts/measure-verdict-post-gap-rate.sh`
  measures the occurrence rate against a per-review-run denominator. (#1631)

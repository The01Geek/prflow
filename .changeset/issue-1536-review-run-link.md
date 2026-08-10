---
bump: patch
type: Fixed
---

- **Fix the agent-fabricated `**Run:**` link in review progress comments.** The review
  progress comment's run link was assembled from an unobservable shell assignment, so the
  reviewing agent filled it in from a guess — producing wrong-owner or unexpanded-literal
  links. A new `scripts/compose-run-url.sh` helper is now the single place the run link is
  composed; `scripts/seed-review-progress.sh` rewrites the created comment's `**Run:**` line
  to that value and reports it on a `RUNLINK` line, and `skills/review/SKILL.md` observes the
  helper's output instead of composing its own URL. `/prflow:review-and-fix` inherits the fix.
  (#1558)

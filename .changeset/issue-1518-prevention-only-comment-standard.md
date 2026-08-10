---
bump: patch
type: Changed
---

- **Adopt a prevention-only comment standard for added/changed comments.** The `/prflow:implement` §2.3 comment-discipline authoring rule now survives a comment inline only when a competent agent would otherwise make a specific, nameable wrong change at that line or at a named coupled site; comments are written as the prohibition and its consequence, capped at three physical source lines, with everything else routed to the project's internal documentation or deleted. Two always-on §2.3.4a commit-time steps (prevention and cross-comment restatement) and one `Suggestion`-graded `comment-analyzer` review criterion enforce it, and the reliably-loaded `CLAUDE.md` summary is reconciled to match. (#1556)

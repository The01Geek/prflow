---
bump: patch
type: Changed
---

- **Trimmed non-operative prose from the `/prflow:review` engine.** The review engine's root
  and phase references carried maintainer notes, provenance, design rationale, and repeated
  statements of the same rule, all of which cost tokens on every review run and ship verbatim
  into consumer repositories. Removed roughly 12KB — about 12% of the engine root — with no
  change to any rule a run acts on.

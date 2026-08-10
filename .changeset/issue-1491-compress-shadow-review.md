---
bump: patch
---

Editorially compress the review-and-fix engine's Step 2.6 shadow-review reference under the instruction-plus-consequence prose rule. Justification prose, superseded design notes, and maintainer asides are removed from `skills/review-and-fix/references/shadow-review.md`, and the dangling `fixing.md` pointer to the deleted Cost note goes with them. The removals are prose-only: the shadow pass's behavior is unchanged, and the 16 suite-pinned literals resident in the file survive verbatim and uniquely. The file is loaded into the fix loop's own context at Step 2.6 and again on the `engine_self_modifying` early trigger, so the reduction lowers the context cost of every converging run.

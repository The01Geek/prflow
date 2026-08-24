---
bump: patch
type: Added
---

- **The review-and-fix efficiency trace now reports recurring defect kinds.** For each run, the
  trace names every `defect_signature.kind` that appeared in the findings of three separate
  iterations, together with the iterations it appeared in — surfacing a fix loop stuck patching
  the same defect shape. A finding whose signature is absent or malformed is rendered under an
  explicit `unknown` label rather than dropped, and a run whose iteration records carry no
  signature at all renders the field as `unestablished` rather than an empty set. The fix-loop
  guidance points the fixer at that report as a signal to model the artifact rather than extend
  an enumeration. (#1903)

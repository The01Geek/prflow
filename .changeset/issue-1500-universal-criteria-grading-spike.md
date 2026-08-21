---
bump: patch
type: Added
---

- **Spike doc: grading a universal acceptance criterion against the surface at HEAD.** Added `docs/internal/universal-criteria-grading-spike.md`, an investigation-and-design document for how the review engine should grade an `issue_acceptance` criterion that quantifies over every unit of a named surface. It measures how often such criteria occur and how large the named surfaces are, decides whether a new `criterion_scope` checklist-item field is needed, specifies an opt-in advisory channel and config gate, and records a live normalization hazard on the existing `issue_acceptance` path. No engine file changes. (#1500)

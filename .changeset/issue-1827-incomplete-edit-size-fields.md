---
bump: patch
type: Added
---

- **Retrospective Stage A entries now carry `additions`, `deletions`, and `changed_files`,
  echoed from the context bundle.** The Stage A output schema and `lib/clean-entry.jq` preserve
  those fields (additive under the existing `schema_version` 3); an entry written by a producer that
  lacks them still cleans without error. Adds `docs/internal/incomplete-edit-cost-analysis.md`,
  which analyzes the `incomplete-edit` cohort against `efficiency_runs[].iterations` and finds
  the current durable records insufficient to decide whether the category is predictable at
  declare-done. (#1944)

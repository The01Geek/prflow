---
bump: patch
type: Added
---

- **Retrospective entries now record `analysis_provenance`.** A live Stage A retrospective run
  records an `analysis_provenance` object — booleans `bundle_diff_present`,
  `bundle_workpad_body_present`, and `bundle_issue_comments_present` — on the entries it writes
  (both the gate-skipped clean-path entry in `lib/clean-entry.jq` and an LLM-judged entry),
  each reflecting what the analyst's context bundle actually contained. The field names match
  the existing backfill cohort's, so diff-present and diff-absent entries can be segmented
  rather than pooled indistinguishably; `schema_version` is bumped to 3. Existing entries are
  left byte-unchanged. (#1950)

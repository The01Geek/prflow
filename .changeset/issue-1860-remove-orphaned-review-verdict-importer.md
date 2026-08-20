---
bump: patch
type: Removed
---

- **Remove the orphaned review-verdict handoff importer.** With the trusted-emitter
  orchestration (#1385) closed as not planned, `scripts/import-review-verdict-handoff.py`
  and its test suite guarded a handoff contract nothing invoked, so they read as live
  security infrastructure while being dead code. Deletes the importer and its focused test,
  and unwires the suite block, coverage-map entry, test-file enumeration, and the
  `Bash(lib/test/test_import_review_verdict_handoff.py:*)` grant (in `.prflow/config.json`
  and the coupled `matcher-probe.yml` mirror). The importer is recoverable from git history
  if a trusted-emitter design is revived. (#1864)

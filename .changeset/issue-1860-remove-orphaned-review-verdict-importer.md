---
bump: patch
type: Removed
---

- **Remove the orphaned review-verdict handoff importer.** With the trusted-emitter
  orchestration (#1385) closed as not planned, the handoff importer script added by #1314
  Part 1 and its focused test guarded a contract nothing invoked, so they read as live
  security infrastructure while being dead code. Deletes the importer script and its test,
  and unwires the suite block, coverage-map entry, test-file enumeration, and the suite-grant
  token (in `.prflow/config.json` and its coupled `matcher-probe.yml` mirror) that existed
  only for them. The importer is recoverable from git history if a trusted-emitter design is
  revived. (#1864)

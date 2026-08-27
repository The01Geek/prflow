---
bump: patch
type: Fixed
---

- **Treat an empty `permission_denials` array as a measured zero in the denial-count extractors.** On claude-code CLI 2.1.247 the execution file carries a `permission_denials` array (empty on a clean run) and no `permission_denials_count` field, so `scripts/surface-execution-diagnostics.sh` and `scripts/build-denial-record.sh` reported every clean run's count as `unavailable` instead of `0`. Both extractors now treat the presence of a `permission_denials` array as a measurement (an empty or all-non-object array yields `0`), keep the `unavailable` sentinel only for a file carrying neither carrier, and emit a shape-drift warning when a result event is present but the count is still unknown. The `devflow-runner.yml` output mapping moves to the documented string-equality form so a published `0` survives. (#2068)

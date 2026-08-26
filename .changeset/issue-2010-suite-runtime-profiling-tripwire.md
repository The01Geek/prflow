---
bump: patch
type: Added
---

- **Weekly retrospective loop now consumes test-suite runtime trend.** Two steps were added to
  the `retrospective-weekly` skill: a suite-profiling pass that runs the existing profiler,
  ranks the slowest sections, labels, and assertions, and files targeted retire/speed-up/extract
  follow-up issues for the top offenders; and a ceiling tripwire that reads the coordinator's
  latest `run-parallel: elapsed` figure from CI job logs and files (or annotates an already-open)
  suite-runtime maintenance issue when it crosses 85% of `BASH_MAX_TIMEOUT_MS`. Both steps only
  read figures and file issues — neither gates a run on suite duration. (#2015)

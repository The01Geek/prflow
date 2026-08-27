---
bump: patch
type: Fixed
---

- **The suite's `#1621` ruff Python-lint gate now selects a candidate whose `major.minor`
  family matches the pinned `.prflow/lint-manifest.json` ruff version, instead of the first
  runnable candidate.** With a readable manifest pin, a stale off-family `ruff` first on PATH
  no longer decides the lint when an in-family one is reachable via `python3 -m ruff`; when
  neither candidate matches the
  family the gate self-skips (kind `blocking-gate`) rather than linting under the wrong rule
  set, and an unreadable manifest pin keeps today's first-runnable selection. The suite also
  reconciles the implement workflow's own `ruff==` install spec to the manifest family, and the
  lint-tool provisioning script deletes a stale off-version binary from its install directory on
  the unsupported-platform degrade path before that directory is added to `PATH`. (#2051)

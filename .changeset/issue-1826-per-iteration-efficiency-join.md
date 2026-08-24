---
bump: patch
type: Changed
---

- **The experiment-record join now carries each run's `per_iteration` array and
  `cut_candidate_min_dispatch` through verbatim, and reports efficiency records stranded on the
  superseded telemetry branch.** `build-experiment-records.py`'s `_efficiency_entry` shaper passed
  neither field into `efficiency_runs[]`, so per-reviewer/loop-position forensics never reached the
  tracked store; the shaper now passes both through unchanged (a missing or non-list `per_iteration`
  normalizes to `[]`). The reader's stranded-record detection previously fired only when the
  canonical `prflow-telemetry` branch was absent and looked under the wrong path; it now fires
  whether the canonical branch is present or absent, counts records under the pre-rename
  `.devflow/logs/efficiency/` path the superseded branch actually uses, and names a divergent-safe
  remedy (a copy-across, never a destructive force-push) when both branches are present. Detection
  only — the assembler still ingests from exactly one branch and mutates no ref. (#1909)

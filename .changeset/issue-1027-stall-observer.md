---
bump: patch
type: Added
---

- **Add an out-of-band, report-only stall observer for in-flight implement runs.** A new scheduled workflow (`.github/workflows/stall-observer.yml`) and pure decision helper (`scripts/stall-observer-scan.py`) read each open PRFlow issue's workpad `**Last updated:**` time against an advisory staleness threshold and surface "silent for N minutes; last checkpoint X" as a job annotation + step summary — the in-job stall backstop runs only after the agent step returns, so it structurally cannot observe a still-running job. The observer never kills or re-dispatches a run (so it cannot race the backstop's resume arm); the threshold is advisory-only and configurable via `prflow_implement.stall_observer.advisory_threshold_minutes` (default 90, provisional), and the observer is gated by `prflow_implement.stall_observer.enabled`. Plugin-internal in this release (not shipped to consumer repos). (#1783)

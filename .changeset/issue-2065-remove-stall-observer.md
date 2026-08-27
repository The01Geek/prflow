---
bump: patch
type: Removed
---

- **Removed the report-only stall-observer workflow, its scan helper, and its two `prflow_implement.stall_observer` config keys.** The scheduled observer never reported the still-running stalls it was built to catch, so `.github/workflows/stall-observer.yml`, `scripts/stall-observer-scan.py`, and the `enabled` / `advisory_threshold_minutes` keys were deleted; the in-job `prflow_implement.stall_backstop` is untouched. The workflow was never shipped to consumer repositories, so no installed consumer loses a running mechanism. (#2069)

---
bump: patch
type: Added
---

- **Every cloud implement run now persists a joined per-run record, and three new
  maintainer instruments read the measurements around it.** The per-run efficiency record
  on the telemetry branch gains a `run_profile` key carrying per-phase durations derived
  from the run's workpad Progress timestamps, the workpad's final status word, the count
  of prior implement records for the same issue, the issue number, and the engine step's
  own outcome read from the workflow step context. A run that ends with no resolvable PR —
  which previously persisted nothing at all — now gets an issue-keyed record naming why no
  PR resolved, onto which the existing cost, denial and profile floors attach unchanged.
  `scripts/implement-run-report.py` renders per-run rows and aggregates from those records
  (and the weekly retrospective's new implement-runtime trend section), and
  `scripts/implement-benchmark.py` compares two configuration cohorts, withholding its
  verdict on a thin cohort or one containing a REJECT. Alongside them
  `scripts/implement-timeline.py` reports per-phase, per-step and per-activity wall-clock
  from a run's execution-transcript artifact, which is a separate channel from the per-run
  record. An unestablished figure is recorded as `unestablished` and excluded from every
  aggregate rather than counted as zero. (#2017)
- **Fixed: the concurrent-push merge onto the telemetry branch dropped every floor key but
  one.** When a competing writer forced the union merge, `lib/telemetry-branch.sh`
  re-applied only `harness_cost` onto the fetched base, silently discarding
  `permission_denials`. The floor keys are now a single declared list the merge program is
  built from. (#2017)

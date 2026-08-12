---
bump: patch
type: Changed
---

- **`/prflow:create-issue` Step 3.5 now leaves a durable record and Step 3.6 gates on it.** The
  steelman summary Step 3.5 already composes is persisted as a numbered `### pass <n>` entry to a
  `## Steelman record` section of the run's derivation artifact before the step returns, and Step
  3.6 confirms at its entry that this run's latest entry exists before dispatching the audit —
  stopping to run Step 3.5 when it does not, at most once per entry, blocking only the audit
  dispatch and never issue creation. The revision-delta evidence line is persisted the same way to
  its own `## Revision-delta record` section, with no confirmation attached. No new artifact path,
  helper, or capability grant is introduced. (#1647)

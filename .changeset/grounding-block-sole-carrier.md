---
bump: minor
---

Make the injected engine-ground-truth block the single home of the cloud headless-wait
discipline, and make the channel that delivers it fail loudly.

The rule that a cloud run must never end its turn with a dispatched subagent still pending
lived in three places — both engine roots and the injected block — and had drifted between
them. Consolidating onto one copy was only safe once the renderer stopped degrading
silently, so this lands in that order:

- Every workflow that runs an engine now validates the vendored renderer after
  vendor-materialization and fails **before** launching the agent, extending the existing
  incomplete-vendor guard. The composer's four degraded arms emit `::error::` and exit
  non-zero instead of warning and continuing, reversing its documented always-exits-0
  contract with its callers updated in lockstep.
- The command tier composed a block only for `/prflow:review` — a trailing space excluded
  `/prflow:review-and-fix`, the command that fans out the most parallel subagents. All
  three dispatched commands now receive one, through a new `generic` renderer mode that
  omits the CI-results section. `/prflow:review-and-fix` takes `generic` rather than
  `review` deliberately: the CI section instructs the agent to cite CI as authoritative
  test evidence, which contradicts that tier's own rule that no loop cites CI for its own
  progress.
- The dispatch-barrier pointers across both engines now name the injected block rather than
  an engine-root path, and state the safe default when no block is present.

**Consumer-visible behaviour change:** a repository whose vendored plugin tree is missing
the renderer previously ran degraded, with only a warning in the Actions log; it now fails
the job with an error naming the remedy. The vendored tree is materialized per run, so this
surfaces a broken install rather than creating one.

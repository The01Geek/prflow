---
bump: patch
type: Added
---

- **Job-level prompt-extension / skill-body arrival enforcement.** A cloud implement run now
  establishes — on a channel independent of the delivery channel under test — whether the
  consumer prompt extension (and, by the durable evidence its loaded body must produce, the
  skill body itself) actually reached the agent, and no longer reports `Complete` when it did
  not. A new `scripts/prompt-extension-arrival.py` reads the extension root directly
  (resolving the same canonical `.prflow/` root the `load-prompt-extension.sh` ladder resolves)
  and classifies each
  surface as `arrived` / `absent` / `unestablished`; `devflow-implement.yml` records that
  expectation before the agent runs and reconciles it against the run's durable workpad after,
  failing the job with an `::error::` (noting that `permission_denials_count` is blind to a lost
  skill-body load) and flipping the workpad `Status` off `Complete` when arrival is
  unestablished. (#1970)

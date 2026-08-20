---
bump: patch
type: Fixed
---

- **Comment-triggered light commands (`/prflow:review`, `/prflow:review-and-fix`,
  `/prflow:pr-description`) now address the thread they were posted on, ignoring any trailing
  number in the command text.** `scripts/resolve-command-trigger.sh` previously preferred the
  typed number, so the workflow's PR-ness guard and the number its steps acted on could diverge
  since #1858 — silently withholding the verdict-reach record (#1156) and the superseded-REJECT
  dismissal net (#1175) from pull requests that really were reviewed. The resolver now emits the
  event's own thread number and writes a run-log line naming any discarded number. (#1874)

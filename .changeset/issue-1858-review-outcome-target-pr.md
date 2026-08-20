---
bump: patch
type: Fixed
---

- **Record the review outcome against the reviewed PR, not the commented-on one.** Three `command`-job steps in `.github/workflows/devflow.yml` — the review stall backstop, the Phase 4.4 verdict-emitter reach record, and the superseded-REJECT dismissal net — read their pull-request number straight from the triggering event, so a `/prflow:review <n>` typed on a different thread resumed, recorded, or dismissed against the commented-on PR rather than the reviewed one. Each step now derives the number from the resolved command's trailing number and falls back to the event's only when the command carries none — the same bash-builtins-only derivation the dead-run flip step already performs. (#1858)

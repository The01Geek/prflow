---
bump: patch
type: Added
---

- **Added a Skill-tool body-delivery probe for the two cloud tiers.** Two sibling jobs in
  `.github/workflows/matcher-probe.yml` (`skill-body-load-review-probe`,
  `skill-body-load-implement-probe`) load the real plugin and invoke the Skill tool once per
  engine root under `show_full_output: true`, and a new unit-tested helper
  `scripts/skill-body-load-probe-verdict.py` derives a per-root delivered-whole /
  short-delivery / unestablished verdict from the Skill `tool_result` in the execution file —
  never model text. `docs/internal/skill-body-load-delivery.md` gains a session-B record whose
  four cloud verdicts are `unestablished` until a maintainer dispatches the jobs. No
  `skills/**` or `agents/**` file changes, so consumers receive nothing. (#1618)

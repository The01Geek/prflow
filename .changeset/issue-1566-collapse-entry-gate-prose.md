---
bump: patch
type: Changed
---

- **Collapse the duplicated per-phase entry-gate prose in the implement orchestrator.** `skills/implement/SKILL.md` now states its phase entry-gate rule once, in the preamble, and routes each of the four phases from that single statement, instead of restating a near-identical entry-gate paragraph in every phase stub. The shipped orchestrator every implement run loads is shorter, and editing the gate rule is a one-place change. (#1585)

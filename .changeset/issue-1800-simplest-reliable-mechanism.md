---
bump: patch
type: Changed
---

- **create-issue clarification now selects for the simplest reliable mechanism at every decision point.** The solution-space rule weighs mechanism strength over two axes — the guarantee it enforces and the long-term cost it leaves behind — while still surfacing the strongest viable candidate. A single simplest-reliable rule makes the simplest mechanism that reliably solves the problem a mandatory menu/answer entry and the selection rule for decisions a run may settle without asking, and the implementation-approach recommendation now defaults to the weakest mechanism class whose single-failure consequence the problem tolerates (pricing the strongest passed-over candidate, overridable by a consumer extension's own policy, and not reopened by later steelman/audit passes except on a verified must-revise defect). The approach question opens with the run's problem framing and a passed-over-candidate trace line rides into the investigation record. (#1802)

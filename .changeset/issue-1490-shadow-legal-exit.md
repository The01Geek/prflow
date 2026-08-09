---
bump: patch
type: Fixed
---

- **Name the legal exit for a run that cannot dispatch the Step 2.6 shadow.** The never-elective paragraph in `skills/review-and-fix/references/shadow-review.md` now names the state a run enters when it cannot fan out — a workpad-holding caller stops at a non-terminal or `Blocked` status naming what prevented the fan-out, and a caller with no workpad reports non-convergence and posts no clean approve-family verdict — so a cost-pressured run is never left reading a prohibition with no legal state to enter. The `skills/review-and-fix/SKILL.md` failure-map row is reconciled with the rewritten paragraph in the same change. (#1490)

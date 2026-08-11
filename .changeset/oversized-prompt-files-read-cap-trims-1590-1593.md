---
bump: patch
type: Fixed
---

- **Four oversized prompt files load whole again.** `skills/implement/phases/phase-1-setup.md`, `skills/implement/phases/phase-4-documentation.md`, `skills/review-and-fix/references/fixing.md` and `skills/review-and-fix/references/shadow-review.md` had each grown past the Read tool's per-call token cap, so a run could no longer see both ends of the file and the boundary-marker check gating them failed. Each is trimmed with its behavior unchanged, so the implement phases and fix-loop steps they gate clear that check again. (#1590, #1591, #1592, #1593)

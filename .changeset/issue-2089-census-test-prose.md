---
bump: patch
type: Changed
---

- **Extend the Phase 2 self-authored-claim census (§2.3.4a) to test prose, and record its
  counts on the workpad.** The claim-census surface list in
  `skills/implement/phases/phase-2-sweeps-quality.md` now names test prose — test names, test
  titles, and assertion messages that promise behavior — alongside internal docs, external
  docs, and code comments, so a false behavioral claim carried by a test name is reconciled in
  Phase 2 rather than surfacing later as a review-time `documented_falsehood` finding. The
  census also logs one workpad note per run recording the count of claims listed and the count
  traced, including on the clean path where nothing diverges, so a skipped shallow census is
  distinguishable from a clean one. The fix loop inherits both changes through
  `skills/review-and-fix/references/fixing.md` §3b's existing pointer, unedited. The
  `docs/internal/implement-skill.md` and `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` descriptions
  of the sweep are reconciled to match. (#2091)

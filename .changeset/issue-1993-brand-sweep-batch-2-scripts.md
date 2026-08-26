---
bump: patch
type: Changed
---

- **Continue the brand-cased `DevFlow`→`PRFlow` prose sweep (batch 2).** Rewrote the
  ordinary renameable brand-cased `DevFlow` prose to `PRFlow` in 24 `scripts/`
  comment and docstring files and reseeded `pending_sweep_baseline` in
  `lib/test/brand-devflow-buckets.json` to drop the drained files; the reconciling
  lint stays clean. No frozen identifier, filename, or pinned literal changed
  spelling. (#1995)

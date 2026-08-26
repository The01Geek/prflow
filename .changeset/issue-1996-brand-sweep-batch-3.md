---
bump: patch
type: Changed
---

- **Continue the brand-cased `DevFlow`→`PRFlow` prose sweep (batch 3).** Rewrote the
  ordinary renameable brand-cased `DevFlow` prose to `PRFlow` in four fully-cleared
  comment-only files (`lib/preflight.sh`, `requirements.txt`, `.gitignore`,
  `.prflow/tool-presets.json`) and reseeded `pending_sweep_baseline` in
  `lib/test/brand-devflow-buckets.json` to drop the drained files; the reconciling
  lint stays clean. No frozen identifier, filename, or pinned literal changed
  spelling. (#1999)

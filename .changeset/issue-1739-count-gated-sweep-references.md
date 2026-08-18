---
bump: patch
type: Changed
---

- **`scripts/implement-context-eval.py` counts gated Phase 2.3 sweep-reference reads toward
  the `phase2` context axis.** The eval measures how many times an implement run reads each
  phase file; once the eight conditional Phase 2.3 sweeps move into gated references named
  `skills/implement/references/sweep-*.md` (PR #1736), a run reads those on top of the phase
  files. The instrument now recognizes a `sweep-*.md` basename and counts it toward `phase2`
  through a new `_phase_label_for_read` helper, matched by basename shape (not a transcribed
  list, so a ninth sweep is counted with no second edit) exactly as `PHASE_FILES` matches —
  the same file resolves at a repo-relative path locally and a vendored path on the cloud
  tier. `PHASE_FILES` stays the exact `skills/implement/phases/*.md` mirror its coupling test
  pins, so the measurement no longer under-reports a run's real per-run context cost. (#1746)

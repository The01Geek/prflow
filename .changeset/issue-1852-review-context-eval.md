---
bump: patch
type: Added
---

- **Added `scripts/review-context-eval.py`, a maintainer-only instrument that measures what entering the review engine costs.** It walks a saved Claude Code transcript directory and reports, per run, how many times each engine file (`skills/review/**`, `skills/review-and-fix/**`) was read, attributes every read to the context that made it (distinguishing a main-thread read from a subagent read), and gives the peak accumulated context of each context that read one. It is the third of DevFlow's transcript-walking context instruments and reuses their streaming, per-record-degradation, symlink-escape and determinism design; no skill, workflow, or suite gate invokes it. (#1887)

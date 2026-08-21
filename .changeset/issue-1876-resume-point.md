---
bump: patch
type: Changed
---

- **Phase 3's mid-phase re-anchor now restores its step position from a compact resume-point record instead of re-reading every phase reference file.** `/prflow:implement` records its resume point on the workpad before invoking a nested skill — through `scripts/workpad.py`'s new `--record-resume-point` write flag and `resume-point` read-back subcommand, a keyed-checkpoint namespace read by no verdict or gate — and after the return re-reads only the one member of the phase's reference set that holds it, re-reading any other member when it reaches that member. The displacement defence is kept, because the file the run resumes from is still read fresh. (#1880)

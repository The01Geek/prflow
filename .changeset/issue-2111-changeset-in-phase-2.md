---
bump: patch
type: Changed
---

- **The implement run writes its changeset in Phase 2, before the prose sweeps.** DevFlow's versioning policy now orders the changeset written during Phase 2, before the §2.3 sweeps run, so the §2.3.4b coverage-claim sweep grades it as an ordinary new file, and the changeset prose cites the issue number. A run that reaches the Phase 3 existence gate without one writes it there and runs the same §2.3.4b leg-2 check before committing. The shipped `phase-3-ac-gate.md` versioning step keeps its existence gate and states no changeset timing of its own. (#2111)

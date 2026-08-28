---
bump: patch
type: Changed
---

- **The implement run writes its changeset in Phase 2, before the prose sweeps.** DevFlow's versioning policy now writes the changeset during Phase 2, so the coverage-claim sweep grades it before commit, and its prose cites the issue number. (#2111)

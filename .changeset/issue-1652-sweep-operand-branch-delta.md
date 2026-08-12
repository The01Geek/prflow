---
bump: patch
type: Fixed
---

- **Phase 2 §2.3 sweeps now grade the whole branch delta, not the uncommitted remainder.** The
  diff-consuming `/prflow:implement` §2.3.x sweeps previously read `git diff HEAD` / `git diff
  --staged`, which the mandatory §2.0.5 durability checkpoint empties by committing each boundary's
  work — so a sweep graded a near-empty operand and recorded a clean pass while real findings sat in
  a committed hunk it never read. The §2.3 sweep operand is now defined once as the merge-base →
  working-tree branch delta (base from `.base_branch`, ref `origin/<base>`), with a degraded arm
  where it cannot be computed and a ground-once ledger bounding repeated work across boundaries.
  (#1654)

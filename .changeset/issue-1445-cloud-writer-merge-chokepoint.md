---
bump: patch
type: Changed
---

- **The cloud-writer contract manifest is no longer a per-branch merge chokepoint.** `main` is
  now the sole writer of `scripts/devflow-cloud-writer-contract.json`: the merge-to-main job
  regenerates it from the merged tree immediately before its version-bump commit, and the
  `regenerate-artifacts.py` batched-pass row plus the per-branch `verify` drift gate were
  removed. Two concurrent prompt-surface PRs that edit the same or adjacent pinned files no
  longer conflict in the manifest, and neither has to re-run whole-suite verification because
  the other merged first. A new CI-side merge-base check
  (`lib/test/cloud-writer-retention-check.py`) fails a feature branch that mutates the artifact
  by hand, so a divergent pair between the pinned bytes and their published digests cannot be
  produced *by hand-authored branch mutation*; a merge that edits a pinned file but ships no
  changeset still leaves the manifest stale until the next changeset-bearing merge, which
  remains a documented review-gate residual. The manifest keeps its path and shape, so the consumer-facing validator, the vendor
  slice, the coverage map and the install path are unchanged. (#1571)

---
bump: patch
type: Fixed
---

- **Standalone cloud review now grades the reviewed PR head, not the default branch.** On the shipped `devflow.yml` review tier every checkout is pinned to the default branch, so claim verification read default-branch bytes — it could FAIL a claim about a line the pull request added ("missing") and silently PASS a claim about content the pull request removed, corrupting a merge-gating verdict in both directions. The displaced-path routing contract is generalized to a diff-touched arm: in standalone PR-number mode a claim about a path the reviewed diff touches is now verified against the reviewed head's bytes through `git show $PR_HEAD_SHA:<path>` (a base-state claim through `$PR_BASE_SHA`), the working tree never moves, and a path the diff does not touch keeps its working-tree read; a routed read of an unresolvable (e.g. fork) head grades INCONCLUSIVE rather than falling back to the wrong bytes. Phase 0 additionally records whether the working tree matched the reviewed head. The change ships zero new tool grants. (#1910)

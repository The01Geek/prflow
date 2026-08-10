---
bump: patch
---

Trim two single-sourced blocks from `/prflow:implement`'s Workpad Reference: the
`Helper invariants baked into the script:` list, which the orchestrator is told it need not
enforce, and the workpad markdown skeleton fence, whose sole producer is
`scripts/workpad.py new-body`. The `## Progress` row texts that `--tick-progress` matches and
the rule keeping `## Acceptance Criteria` outside any `<details>` block survive inline, as does the
marker-first invariant for the two paths that write a whole body by hand. The surrounding narration
is condensed with it: reflection rendering is now carried solely by the `--reflection-kind` CLI-table
row, and the run-link derivation solely by Phase 1.3, whose legacy-workpad migration now renders its
`## Progress` section from `workpad.py new-body` instead of splicing the deleted fence.

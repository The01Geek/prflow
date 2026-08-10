---
bump: patch
---

Trim two single-sourced blocks from `/prflow:implement`'s Workpad Reference: the
`Helper invariants baked into the script:` list, which the orchestrator is told it need not
enforce, and the workpad markdown skeleton fence, whose sole producer is
`scripts/workpad.py new-body`. The `## Progress` row texts that `--tick-progress` matches and
the rule keeping `## Acceptance Criteria` outside any `<details>` block survive inline.

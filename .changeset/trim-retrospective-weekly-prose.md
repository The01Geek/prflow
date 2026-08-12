---
bump: patch
type: Changed
---

- **Trimmed justification prose from the `/prflow:retrospective-weekly` skill.** The
  orchestrator body now carries each instruction with at most one sentence naming what
  breaks if it is skipped, per the repository's instruction-plus-consequence prose rule:
  derivations, design narrative, provenance, reviewer pre-emption, and restatements of
  facts already stated elsewhere in the file were removed. Every operative instruction,
  decision rule, stop condition, command fence, flag and declaration marker is unchanged,
  so run behavior is identical. `SKILL.md` drops from 83,427 to 70,113 bytes.

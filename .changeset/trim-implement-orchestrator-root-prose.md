---
bump: patch
type: Changed
---

- **Trimmed redundant prose from the `/prflow:implement` orchestrator root.** `skills/implement/SKILL.md` loads in full on every implement run, so duplicated rules, derivations of rules the agent only needs the conclusion of, maintainer-only coupling notes, and architecture narration were paid for on each one. The root drops from 9073 to 7923 words (-12.7%) with no rule removed: the standalone subagent rule folds into the injection-condition clause that already restated it verbatim, the nested-procedure and Skill-tool re-anchors merge into one trigger keeping both anchors, the two Phase 4 subagent re-anchors merge keeping both dispatch points and resume targets, and the reflection-kind routing table, the sole-delivery-channel rule, best-effort workpad uniqueness, the two-denials rule and the replay carve-out are each now stated once. Two stale cross-references are corrected: the workpad marker lookup happens in Phase 1.3, not 1.2, and the completion checklist no longer points at a renamed heading.

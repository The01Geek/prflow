---
bump: patch
type: Changed
---

- **Trimmed redundant prose from the `/prflow:implement` orchestrator root.** `skills/implement/SKILL.md` loads in full on every implement run, so duplicated rules, derivations of rules the agent only needs the conclusion of, maintainer-only coupling notes, and architecture narration were paid for on each one. The root drops from 9073 to 8083 words (-10.9%, -6,673 bytes) with no rule removed: the standalone subagent rule folds into the injection-condition clause that already restated it verbatim, the two Phase 4 subagent re-anchors merge into one trigger keeping both dispatch points and both resume targets, and the reflection-kind routing table, the sole-delivery-channel rule, best-effort workpad uniqueness, the two-denials rule and the replay carve-out are each now stated once. Every literal pinned by the test suite is carried verbatim by the trimmed prose, so `lib/test/run.sh` is unchanged. Two stale cross-references are corrected: the workpad marker lookup happens in Phase 1.3, not 1.2, and the completion checklist no longer points at a renamed heading.

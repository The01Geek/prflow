---
bump: patch
type: Changed
---

- **Phase 4.2 (Generate PR Description) now runs in a dispatched subagent.** The implement engine's PR-description generation and its three-class claim audit are dispatched to one Agent-tool subagent (mirroring Phase 4.1's docs subagent) instead of reading the branch diff inline in the orchestrator's context, so the diff stays out of the main thread. `pr-description` is now named only in the dispatch-authorization sentence, the workpad no longer carries a PR-description extension row, and Phase 4.2's subagent return has its own re-anchor. (#1584)

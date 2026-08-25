---
bump: patch
type: Changed
---

- **`/prflow:implement` Phase 4 now resumes directly after a documentation or PR-description subagent returns.** These are Agent-tool dispatches whose returns enter the orchestrator's context as a report only, so the run proceeds to the next sub-step without re-reading the whole phase file — dropping the repeated full re-read that runs were truncating. The prompt-extension re-load still fires at both boundaries, and the full re-read stays mandatory at every phase entry, every mid-phase Skill-tool return, and the nested-skill completion re-anchor. (#1954)

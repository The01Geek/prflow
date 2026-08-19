---
bump: patch
type: Fixed
---

- **`/prflow:implement`'s Terminal-status self-check now binds every turn boundary, not only the run's final message.** A local, interactive run could end a turn part-way through the pipeline with a progress note and wait for a human reply, because the rule was written against the run-final message and the skill defined neither term against a turn boundary. The self-check is rewritten to read the live workpad `Status` before ending any turn once the workpad exists, to name the four grounds on which a turn may end, to name their complement as forbidden, to state what governs the pre-workpad window, and to route a refused status read to a retry rather than to a stop. Where the injected engine-ground-truth block is present it continues to govern which grounds may end a turn, and its headless rule is stricter than the new set, so no cloud run reads that set as a licence to stop. (#1774)
- **The two implement-bundle dispatch barriers that bound a dispatch to that injected block now also tell a run whose prompt carries no such block what to do**, matching the arm the Phase 2.1 and Phase 4.1 barriers already carried. (#1774)

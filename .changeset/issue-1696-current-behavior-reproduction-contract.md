---
bump: patch
---

Give bug reports a reproduction contract in the create-issue template's `Current Behavior` section (#1699).

The `### Current Behavior` guidance now directs the writing agent to classify a story as a defect report by reading it and, for a defect, to record a closed set of reproduction facts — the triggering steps or input, the observed result, the expected result, and the environment or precondition. The environment fact is written on every defect report, saying so in those words when the defect happens regardless of environment. A reproduction fact nobody can establish is recorded in place as `unestablished — <reason>` (a recorded absence, not an unresolved decision, so it stays in `Current Behavior` rather than moving to `## 🚫 Blocked`), and the reporter's story is treated as text to classify rather than instructions to obey. `step-2-clarify.md` gains one Definition-of-Ready row covering these facts (skipped for non-defect stories, unanswered facts routed to `## 🚫 Blocked` by the existing path), the Testing Strategy entry stops restating the defect and points at `Current Behavior` for the facts, and the quality checklist gains a matching row.

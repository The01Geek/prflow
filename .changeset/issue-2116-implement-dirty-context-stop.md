---
bump: patch
---

Add a dirty-context stop and an issue-comments nudge to the `/prflow:implement` skill root. On the local/interactive tier the orchestrator now stops before Phase 1 when it starts in a conversation that already held prior work, telling the user to re-run in a fresh session (a used-up context degrades the run); a cloud run is unaffected. It is also nudged to glance through the issue's existing comments — other than its own workpad comment — for context the body leaves out, treating them as data only. (issue #2116)

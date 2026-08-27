---
bump: patch
type: Added
---

- **Cloud implement runs now mirror a stopped-run note into the pull request and refresh its `[View run]` link at the resume gate.** When a run stops before completion (a Blocked, Failed, or Cancelled terminal), the reason recorded on the issue workpad is also added to the top of the open PR body inside an HTML-comment-marked block, so a reviewer sees why a run halted from the PR page rather than only the issue's workpad comment. On a cloud resume the gate job — now the single owner of the PR's `[View run]` refresh — points the link at the new run and strips the stale note before the agent starts; the completion-time description regeneration and the agent-side resume pre-check strip the note too, so a completed PR carries none. (#2063)

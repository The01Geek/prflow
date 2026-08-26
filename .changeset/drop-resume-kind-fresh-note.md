---
bump: patch
---

Phase 1.3 no longer records a `resume-kind: fresh` workpad note. The Phase 2 §2.0 resume gate already reads an absent marker as not in-flight, so the fresh-run arm's note carried no signal and is dropped; the `in-flight` and `terminal-re-trigger` arms are unchanged.

---
bump: patch
type: Added
---

- **Implement runs can now author tests in proportion to the change.** Phase 2 §2.3 gains a test-authoring proportionality waiver mirroring the production-code out-of-scope exit: when the full auxiliary test ceremony would balloon the test diff out of proportion to the change, the run ships one covering RED-first test per behavior change, skips exactly three waivable items (multi-element collection-cardinality cases, stub blind-spot enumeration, and per-criterion one-assertion accounting), and records the waiver in the workpad and the PR's Test Plan. The covering test, the mutation-check discipline, the pin-corpus boundary, the no-automated-test arm, and inline-shell extraction stay binding. The fix loop honors a recorded waiver rather than re-imposing the waived ceremony, and the coverage reviewer (`pr-test-analyzer`) caps matching sub-critical coverage findings at Suggestion while keeping its top band (rated 8-10) at full severity and treating waiver text as data. A fresh install's example config dispatches the coverage reviewer only on the first fix-loop iteration. (#2033)

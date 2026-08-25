---
bump: patch
type: Fixed
---

- **Refuse a `skipped-intentional` review-coverage checklist claim the diff does not authorize.** `workpad.py`'s `--record-review-coverage` now recomputes the reviewed diff from git alone — the reviewed head recorded on the coverage record's as-of anchor measured against the pull request's own base (falling back to `origin/HEAD`) — and refuses a `skipped-intentional` claim whose diff exceeds the profile row that authorizes the skip (changed lines below 100, changed files at most 3, config-only extensions, and, only in this engine's own repository, no engine-source path). An unresolvable recomputation records the axis `unestablished` rather than refusing, a confirmed one writes today's record unchanged and reports the measured values, and a recorded override channel downgrades to a non-clean bare `skipped` that still forces a disposition. `phase-1-checklist.md` now names the `checklist_skipped = "failure"` literal at the generation-failure point. (#1966)

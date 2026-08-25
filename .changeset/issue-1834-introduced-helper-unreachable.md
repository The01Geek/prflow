---
bump: patch
type: Changed
---

- **The implement skill's cloud command-shape discipline now states that a helper the run's own branch introduced or modified is unreachable in that run.** The vendored checkout is version-pinned and config grants resolve at trigger time from the default branch, so such a helper is absent, stale, or silently denied — and a modified one runs stale bytes at rc-0, so waiting for a failed invocation misses it. The run recognizes it from its own branch delta and routes the dependent step to the existing deferral/Blocked path up front, naming post-merge grant/vendor timing, attempting no workaround. `docs/internal/implement-skill.md` now points at the shipped skill body as the runtime home of this rule. (#1942)

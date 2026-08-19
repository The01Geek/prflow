---
bump: patch
type: Changed
---

- **`/prflow:create-issue` Step 1 now starts with the shallow arm and reaches the deep arm only by escalation.** The pre-dispatch arm-selection judgement is removed: every dispatching run surveys the union of the two legs with one peer, and the deep two-peer split runs only when the shallow report's existing escalation triggers (a doc-reliability `UNRELIABLE`/`ABSENT`, an unestablished duty, or a judged-not-engaged duty whose bearing observation is not `none-observed`) fire. This makes one agent the default cost where the deep arm — the effective default on a substantive topic, since its pre-dispatch judgement almost always read full-floor — paid for two, with unchanged verification coverage. (#1805)

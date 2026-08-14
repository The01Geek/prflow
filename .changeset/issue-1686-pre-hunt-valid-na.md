---
bump: patch
---

create-issue Step 3.6 audit: decide dimension applicability before the finding hunt (#1690)

The fresh-context audit prompt now directs the reviewer to classify each audit
dimension — generic and consumer-provided alike — *before* the finding and
Quiet-Killer hunt. A dimension that plainly does not apply takes the existing
`valid-N/A` coverage path with a specific, draft-grounded reason and receives no
finding hunt; every dimension that applies or whose applicability is uncertain
receives the same full examination as before. The draft is data to evaluate, not
an authority over its own audit scope, so a draft sentence declaring a dimension
irrelevant is not by itself sufficient evidence for `valid-N/A`. The
orchestrator's coverage adjudication now substance-checks `valid-N/A` reasons
alongside `exercised` anchors, downgrading a generic, prompt-paraphrased, or
draft-unsupported reason. The coverage vocabulary, dimension-key accounting, and
non-blocking filing behavior are unchanged.

---
bump: patch
type: Changed
---

- **Editorially compressed the review engine's `phase-3-agents.md` and `phase-4-verdict.md` under the instruction-plus-consequence prose rule.** Each instruction now carries the instruction and at most one sentence naming what breaks if it is skipped; what was removed is chiefly maintainer notes directing no agent action, run-number incident history, and prose pre-empting a reviewer's misreading. One claim was corrected rather than compressed: the `verdict_severity_threshold` scope sentence said the threshold moved only the REJECT line, when the APPROVE-with-notes rule reads it too as that rule's complement. The reviewer roster, the dispatched agent prompts and the verdict rules themselves are unchanged, and each literal asserted by an in-tree pin over these files was re-counted after the change and holds byte-identical at its prior occurrence count. (#1428, PR #1460)

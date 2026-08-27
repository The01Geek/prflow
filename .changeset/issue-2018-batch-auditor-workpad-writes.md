---
bump: patch
type: Changed
---

- **Batch the issue-claim auditor's workpad writes into one update call.** The
  `issue-claim-auditor` agent now composes each pass record as its pass completes and holds it,
  delivering the accrued records in one batched `workpad.py update` invocation at audit end —
  plus one further call per additional reflection kind, since one update applies a single
  `--reflection-kind` — instead of one network round trip per pass; an audit that ends at a stop
  arm folds its accrued records into the same terminating update. Note texts and reflection kinds are unchanged, so
  workpad-reading consumers see identical content. (#2022)

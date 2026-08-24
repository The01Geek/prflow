---
bump: patch
type: Fixed
---

- **A raw `FAIL` on an issue acceptance criterion is never stored as a `PASS`.**
  `scripts/normalize-verdicts.py` now treats an item whose `category` is `issue_acceptance`
  as a real-value normalization blocker. Such items satisfy the first two normalization
  conjuncts structurally — the checklist generator defaults them to
  `claim_provenance: generated_paraphrase` and they are never `lite`-eligible, so they always
  run in `agent` mode — which left only the verifier's own self-reported `property_proven` /
  `inaccuracy_scope` fields between a failing acceptance criterion and a silently stored pass
  that Phase 4.2 rule 1 would never see. (#1907)

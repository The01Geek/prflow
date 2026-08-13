---
bump: patch
type: Fixed
---

- **The Phase 3.4 acceptance-criteria claim verifier now grades a measurement criterion instead of blocking it.** `agents/ac-claim-verifier.md` gained a third recognised criterion shape: for a criterion whose verification names a measuring instrument (a `wc -c` byte count, a `git merge-base`-driven list comparison), the verifier grades whether that instrument measures the criterion's literal claim — a fitting instrument is `satisfied`, a mismatched one is `unmet` — and no longer reports `unestablished` merely because producing the measured value would require execution. Previously such a criterion fell through to the `unestablished` fallback, which the reconciler turned into a blocking result for a criterion the evidence verifier had already established as met. (#1665)

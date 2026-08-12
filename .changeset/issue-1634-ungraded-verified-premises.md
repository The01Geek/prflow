---
bump: patch
type: Fixed
---

- **Report ungraded "verified against X" annotations in the verified-premise pass.** `scripts/check-verified-premises.py` now runs a second, non-adjudicating pass that reports every collocation-family phrase ("verified against", "confirmed against", "checked against", "verified at drafting time") found in a premise-bearing region of an issue body (the `Current Behavior`, `Technical Context`, and `Implementation Notes` sections plus every heading line) that no recognised `Verified:` marker span already covers and that is not inside code, as `ungraded_claim=…` lines plus an `UNGRADED_CLAIMS total=…` summary. The pass mints no verdict, moves no exit code, and shares no token with the adjudicated vocabulary, so no already-filed issue changes verdict. The implement-side Pass 6 records each detection as an `issue-accuracy` observation (never a refutation) and no longer treats such an annotation as licensing a skipped investigation, and `/prflow:create-issue` resolves each detection before presenting a draft. (#1639)

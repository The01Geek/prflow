---
bump: patch
type: Fixed
---

- **Pass the draft PR number to the Phase 3.3 fix loop so it runs in PR mode.** `/prflow:implement` Phase 3.3 now passes the draft PR number as a bare leading numeric token to `review-and-fix`, so the fix loop runs against the PR the run owns instead of in current-branch mode, and it states an omit-the-token arm for when Phase 3.1 printed no number. Both engine roots' Input paragraphs bind `$PR_NUMBER` to a bare numeric token so a `--issue` value is not mistaken for it, and the fix loop's Step 0.5 answers an absent `checkout-rc=` token with its existing head-ref/head-commit assertion so the newly-enabled gate does not stop the loop on the cloud implement tier where `gh pr checkout` is ungranted. (#1641)

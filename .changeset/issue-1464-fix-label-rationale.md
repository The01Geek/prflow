---
bump: patch
type: Fixed
---

- **Corrected the stale labeling rationale in the create-issue issue template.** The "Posting the issue" section of `skills/create-issue/references/issue-template.md` no longer attributes label application to maintainers; it now points to Step 4, which applies the reserved `PRFlow` provenance label after creation, so passing `--label` on the create call is redundant. (#1480)

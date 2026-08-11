---
bump: patch
type: Fixed
---

- **Phase 1.6's issue-claim-auditor dispatch now binds a distinct `REPO_ROOT` operand.** `phase-1-setup.md` previously folded the checkout root into the `SCRIPTS` bullet, which the auditor's own operand list never named, so Pass 6's `--repo-root "$REPO_ROOT"` could resolve empty and route to its fail-closed default. `SCRIPTS` and `REPO_ROOT` are now separate, explicitly bound operands in both `phase-1-setup.md` and `agents/issue-claim-auditor.md`. (PR #1583 review, Important-1)

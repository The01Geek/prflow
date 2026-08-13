---
title: "Review and Fix"
description: "Review a pull request or branch, apply authorized corrections and record verification."
---

Use this workflow when you explicitly authorize PRFlow to assess changes and commit corrections. It changes the active branch and can push when requested. The result is corrections followed by recorded verification, or a report naming unresolved findings.

```text
/prflow:review-and-fix 123
```

The optional arguments are `[pull request number] [--push-each-iteration] [--issue N]`. Omit the pull request number to use the current branch. Use `--issue N` when the review should verify a specific issue's acceptance criteria.

## Edit Authority and Target Boundaries

This workflow applies fixes directly in the active session. It creates commits as it converges.

In pull request mode, PRFlow checks out the pull request head and verifies both the branch name and head commit before it reviews or edits. A dirty working tree that prevents checkout stops the run. In current-branch mode, commits land on the checked-out branch.

Use assessment-only [Review](/docs/workflows/review) when you do not want branch changes.

## Iterations and Severity Routing

The loop runs the full review engine, verifies each finding, fixes the actionable set and reviews the new commit again. The default cap is five iterations. Configure `prflow_review_and_fix.max_iterations` to change it.

The default fix threshold is `important`:

- Critical and Important findings route to the fixer.
- Suggestion findings stay advisory unless the threshold is changed to `suggestion`.
- A threshold of `critical` routes only Critical findings to the fixer.

PRFlow can push back on a finding when the code disproves it. It can also defer a real finding when the documented deferral rules apply. Test failures introduced by a fix must be corrected before the loop continues.

## Push Behavior

Fix commits stay local by default. Add `--push-each-iteration` to push each completed fix iteration and the final loop state to the feature branch.

The flag does not post a formal verdict. It only keeps the remote branch and its continuous integration runs current.

## Shadow Review

Before an approval-side conclusion, PRFlow runs a separate shadow review over the candidate. The shadow pass reports which planned reviewers completed and any known coverage gaps. A run with no reported gap still does not prove that the review found every defect.

Shadow agreement narrows the chance of a false clean result. It does not replace a human review or create a formal merge signal.

## Formal Review Boundary

Review-and-fix skips the standalone review workflow's attempt to post a formal verdict. Its final verdict, completed-reviewer list and known gaps go to chat. A standalone pull-request run can maintain its own progress comment, but that comment is not a substitute for a formal GitHub review. When implementation runs this loop inline, the review stages appear in the issue workpad instead of a separate pull-request progress comment.

Run an independent assessment after the fixes converge:

```text
/prflow:review 123
```

That standalone run reviews the resulting pull request head and attempts to post the formal merge signal. If GitHub refuses it, PRFlow reports the fallback channel and that the merge signal is missing. Neither workflow merges the pull request.

## Related Articles

- [Review](/docs/workflows/review)
- [Implement an Issue](/docs/workflows/implement)
- [Configuration Settings](/docs/configuration/settings)

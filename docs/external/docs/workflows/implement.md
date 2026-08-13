---
title: "Implement an Issue"
description: "Turn an existing GitHub issue into a review-ready or draft pull request with recorded verification evidence."
---

Use this workflow when you have an open GitHub issue with actionable acceptance criteria. It can create a branch, commit and push changes and create or update a pull request. The result is a review-ready or draft pull request with recorded verification evidence, or a Blocked result naming the required human action.

```text
/prflow:implement 123
```

The example uses Claude Code syntax. Use `/prflow/implement 123` in GitHub Copilot CLI or `$prflow:implement 123` in Codex CLI.

## What PRFlow Does

PRFlow runs all four implementation phases:

1. Fetch the issue, parse its acceptance criteria and create or resume its workpad.
2. Create or adopt the issue branch, discover the affected code, plan the change, implement it and test it.
3. Open a draft pull request, simplify the change and run the review-and-fix loop.
4. File required follow-up issues, update documentation, refresh the pull request description and finalize the run.

The issue defines the intended outcome. Before implementation begins, PRFlow checks that its acceptance criteria represent every independently testable outcome in Desired Behavior. An uncovered outcome blocks the run for issue refinement instead of becoming an inferred criterion or being omitted from review. PRFlow also verifies the issue's repository claims against the current tree before using them as implementation instructions.

## Branch and Workpad Behavior

The workpad is the single GitHub issue comment that records the run's branch, status, plan, progress, mirrored acceptance criteria and notable problems. A resumed run updates the same workpad instead of creating another one.

PRFlow checks for an existing open pull request before it creates a branch. It can adopt a validated issue branch or resume the pull request head.

PRFlow stops before changing existing branch history when:

- It finds commits on the feature branch that are not in the base branch and cannot link them to the issue.
- It cannot establish evidence linking the workpad to this issue and pull request.
- It cannot resolve the base reference.
- A merge is already in progress.

If a previous workpad is Blocked, a local run surfaces the reason and waits for confirmation before it proceeds.

## Dependencies and Other Blockers

PRFlow stops early when an issue declares an open `Blocked by #N` dependency. It also stops when the dependency state cannot be established.

Later blockers include a failing in-scope acceptance criterion, an ungranted verification command and an unresolved Critical review finding. Final-tree verification that does not produce a clean result in the run environment also blocks completion. Before publishing, PRFlow also confirms the local branch tip has reached the remote; if a commit was made but not pushed and a push does not land it, the run stops with a Blocked result rather than publishing a pull request whose description cites a commit the remote does not have.

Continuous integration remains a post-pull-request merge gate. It does not replace verification inside the implementation run.

## Draft Pull Request and Review

The pull request is created as a draft before the review phase. PRFlow runs a simplification pass and the review-and-fix loop while the pull request is still a draft.

Non-Critical residual findings can be surfaced for human review after bounded re-review. A genuine unresolved Critical finding blocks the run.

PRFlow never merges the pull request.

## Acceptance Criteria and Deferred Work

Every in-scope acceptance criterion must be supported by a passing test, a documented manual check or a code reference. A criterion that requires a real deployed environment stays unticked and appears in the pull request's Post-Merge Verification section.

When a multi-pull-request issue deliberately defers criteria, Phase 4 files follow-up issues before finalization. Review findings that are intentionally deferred also receive follow-up issues and are disclosed in the pull request description. Deferral does not silently mark the work complete.

## Ready or Draft Outcome

The `prflow_implement.implement_pr_state` setting controls the final pull request state:

- `ready_for_review` is the default. PRFlow runs `gh pr ready` after final verification.
- `draft` leaves the pull request as a draft for a human to publish later.

The workpad can reach Complete in either case. If publication was requested but failed, the workpad records the failure and the pull request stays unpublished until a human resolves it.

Human reviewers and repository protections own the merge decision. PRFlow prepares the branch and evidence, but it does not approve or merge its own work.

## Related Articles

- [Review](/docs/workflows/review)
- [Review and Fix](/docs/workflows/review-and-fix)
- [Cloud Runs](/docs/runs/cloud/index)
- [Configuration Settings](/docs/configuration/settings)

---
title: "Workflows"
description: "Pick the PRFlow workflow that matches the outcome you want and the edit authority you are willing to grant."
---

Pick the smallest PRFlow workflow that produces the outcome you need with the least edit authority.

PRFlow commands are Claude Code skills. You run them as `/prflow:<skill>` in Claude Code, and you run four of them by leaving a comment on a GitHub issue or pull request. See [Local Runs](/docs/runs/local/index) and [Cloud Runs](/docs/runs/cloud/index) for the difference.

![A map of PRFlow skills grouped by outcome. The core delivery skills are prflow:create-issue, prflow:implement, prflow:review and prflow:review-and-fix. Supporting skills are prflow:pr-description, prflow:docs and prflow:retrospective-weekly.](/images/workflow-skill-map.svg)

## The Delivery Path

These four workflows carry a piece of work from an idea to a pull request a human can merge.

<CardGroup cols={2}>
  <Card title="Create an Issue" icon="circle-plus" href="/docs/workflows/create-issue">
    Turn a rough idea or bug report into one approved GitHub issue. Creates nothing until you approve the final draft.
  </Card>
  <Card title="Implement an Issue" icon="code" href="/docs/workflows/implement">
    Turn an open issue into a pull request. Creates a branch, commits code and docs, pushes and opens a pull request.
  </Card>
  <Card title="Review" icon="magnifying-glass" href="/docs/workflows/review">
    Assess a pull request or branch and return a verdict. Never edits the reviewed tree.
  </Card>
  <Card title="Review and Fix" icon="wrench" href="/docs/workflows/review-and-fix">
    Assess the same way, then correct what it finds. Commits to the active branch.
  </Card>
</CardGroup>

## Supporting Workflows

<CardGroup cols={2}>
  <Card title="Pull Request Description" icon="file-lines" href="/docs/workflows/pr-description">
    Write or refresh a pull request body from the current branch.
  </Card>
  <Card title="Documentation" icon="book" href="/docs/workflows/documentation">
    Keep developer docs, public docs and release notes in step with the code.
  </Card>
  <Card title="Weekly Retrospective" icon="arrows-rotate" href="/docs/workflows/retrospective-weekly">
    Learn from recently merged pull requests and file the findings for human triage.
  </Card>
</CardGroup>

## Choose a Workflow

Read down the "Your goal" column until you find your case.

| Your goal | Use | What it may change |
| --- | --- | --- |
| Record work instead of building it now | [Create an Issue](/docs/workflows/create-issue) | Creates one GitHub issue, after you approve the draft |
| Complete an issue that already exists | [Implement](/docs/workflows/implement) | Branch, commits, push, one draft pull request |
| Get an opinion on a pull request or branch | [Review](/docs/workflows/review) | Nothing in the reviewed tree |
| Get the problems found and corrected | [Review and Fix](/docs/workflows/review-and-fix) | Commits on the active branch |
| Make a pull request body match the code | [Pull Request Description](/docs/workflows/pr-description) | The pull request body only |
| Catch documentation up with a change | [Documentation](/docs/workflows/documentation) | The documentation files you select |
| Find recurring delivery problems | [Weekly Retrospective](/docs/workflows/retrospective-weekly) | Learning records, one state pull request, new issues |

<Note>
  `review` and `review-and-fix` share the same review engine and produce the same findings. The difference is authority: `review` reports, `review-and-fix` edits. Use `review-and-fix` only when you want PRFlow to change your branch.
</Note>

## What No Workflow Does

No PRFlow workflow merges a pull request, and none of them approves its own work. Merge stays with your reviewers and your branch protection rules. See [Human Control](/docs/concepts/human-control).

## Related Articles

- [Command Reference](/docs/reference/command-reference)
- [The Lifecycle of a Change](/docs/concepts/lifecycle)
- [Local Runs](/docs/runs/local/index)
- [Cloud Runs](/docs/runs/cloud/index)

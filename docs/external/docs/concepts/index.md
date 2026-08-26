---
title: "How PRFlow Works"
description: "Understand PRFlow's lifecycle, progress records, verification, review system, security posture and human control points."
---

Understand how PRFlow moves a request through an established repository while keeping human control, durable progress and independent review.

PRFlow is an orchestrated delivery workflow. It turns a GitHub issue into a branch and a progress record, builds a draft pull request, verifies and reviews the change, updates documentation and hands the result to a person. It does not merge.

## Core Concepts

<CardGroup cols={2}>
  <Card title="The PRFlow Lifecycle" icon="route" href="/docs/concepts/lifecycle">
    The seven stages an issue passes through, and the gates that can stop a run at each one.
  </Card>
  <Card title="Workpads and Resume" icon="clipboard-list" href="/docs/concepts/workpads-and-resume">
    The progress comment PRFlow writes on the issue, and which work survives an interruption.
  </Card>
  <Card title="How PRFlow Verifies a Change" icon="flask" href="/docs/concepts/verification">
    What "recorded verification evidence" means, and why an unknown result is never a pass.
  </Card>
  <Card title="The Review System" icon="magnifying-glass" href="/docs/concepts/review-system">
    The reviewers PRFlow runs, the verdict it reports and what drives a rejection.
  </Card>
  <Card title="Security and Trust" icon="shield-halved" href="/docs/concepts/security">
    What PRFlow can write, who can start a run and where a cloud run reads its rules from.
  </Card>
  <Card title="Human Control" icon="user-check" href="/docs/concepts/human-control">
    Every approval, permission and merge boundary that stays with people.
  </Card>
</CardGroup>

## A Useful Vocabulary

- **Run:** One execution of a PRFlow skill against a repository and, for implementation, a GitHub issue.
- **Workpad:** The issue comment that records implementation progress, acceptance criteria and durable notes.
- **Checkpoint:** A workpad update, or a scoped commit and push, that reduces how much progress an interrupted run has to reconstruct.
- **Verification evidence:** The record of which checks a run executed and what each one returned. See [How PRFlow Verifies a Change](/docs/concepts/verification).
- **Review-ready:** The workflow finished and recorded its available verification and review evidence. It is not a guarantee of correctness and it is not permission to merge without review.

<Note>
  Claude Code is the documented client. Every command on this site is written as `/prflow:<skill>`, for example `/prflow:implement 123`.
</Note>

---
title: "Workpads and Resume"
description: "Understand PRFlow's recorded progress and interruption boundaries."
---

PRFlow records durable implementation progress so a paused, stopped or retriggered run can continue without reconstructing the work from scratch.

![The prflow:implement skill resumes from two kinds of recovery evidence: the GitHub issue workpad and the remote branch. A Blocked workpad causes PRFlow to surface the recorded cause. If matching open work exists, PRFlow adopts it, inspects the current tree and repeats blocking checks.](/images/workpad-resume.svg)

## The Workpad

An implementation run maintains exactly one dedicated progress comment on its GitHub issue. This workpad is the human-readable progress record for the run.

It records:

- The current lifecycle status and feature branch.
- The pull-request link after one exists.
- The implementation plan and progress checklist.
- The issue's acceptance criteria and their checked state.
- Reproduction evidence for bug reports.
- Blockers, deferrals, dropped work and other reflections a human should inspect.

PRFlow updates the same comment instead of posting a new progress comment at each step. The inline review-and-fix phase also records its review stages in this workpad instead of opening a separate progress comment on the draft pull request. A local run creates the workpad as its first GitHub write. A cloud run can create an initial version before implementation begins, then fill it in during setup.

## How Resume Finds Prior Work

On a later implementation command, PRFlow reads the existing workpad before planning. It also queries open pull requests associated with the issue.

When it can establish a matching open pull request, it adopts that pull request's head branch. A recorded, in-progress plan can let the run skip repeated discovery. PRFlow still checks the current tree and repeats any check that can block the run.

If the workpad is already `Blocked`, PRFlow surfaces the recorded cause instead of silently continuing through it. Resolve the cause and confirm the next step before proceeding.

## Code Checkpoints

The workpad preserves decisions and status. Commits and pushes preserve code.

During implementation, PRFlow creates scoped code checkpoints at major substep and verification boundaries. It stages only explicitly named paths and creates a commit when there is new work. It then checks that the pushed commit reached the tracked remote branch.

These checkpoints reduce the amount of work an interrupted run must repeat. They do not make every moment durable.

## What a Checkpoint Does Not Guarantee

- Analysis that exists only in the active session is not durable by itself.
- Edits made after the latest successful commit and push can still be lost with an interrupted environment.
- A workpad update can fail during a GitHub outage, so the branch and repository state must still be inspected on resume.
- A checkpoint cannot prove that tests are correct, that a review found every defect or that a later default-branch change will merge cleanly.
- Local runs do not gain the cloud workflow's bounded automatic resume behavior. Run the implementation command again when a local session stops.

Treat the workpad and remote branch as recovery evidence, not as a transaction log. Review them together before deciding what a resumed run should do.

## Terminal States

- **Complete:** The run finished its configured lifecycle and recorded final verification evidence.
- **Blocked:** A dependency, acceptance criterion, repository condition or verification requirement needs human action.
- **Failed or Cancelled:** A cloud backstop recorded that the run did not reach a normal terminal result.

The pull request remains under human control in every state.

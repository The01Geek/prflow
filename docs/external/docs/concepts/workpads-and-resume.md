---
title: "Workpads and Resume"
description: "Read the progress comment PRFlow writes on an issue, and understand which work survives an interruption."
---

PRFlow records durable progress on the issue, so a paused, stopped or retriggered run can continue instead of rebuilding the work from scratch.

![The prflow:implement skill resumes from two kinds of recovery evidence: the GitHub issue workpad and the remote branch. A Blocked workpad causes PRFlow to surface the recorded cause. If matching open work exists, PRFlow adopts it, inspects the current tree and repeats blocking checks.](/images/workpad-resume.svg)

## The Workpad

The **workpad** is a progress comment PRFlow writes on the GitHub issue. It is the human-readable record of the run. PRFlow edits that same comment as the run proceeds instead of posting a new comment at each step.

This is what one looks like partway through a run:

```markdown
# PRFlow Workpad — Issue #123

**Status:** 🚀 Implementing
**Branch:** issue-123-retry-on-timeout
**Run:** https://github.com/acme/api/actions/runs/1234567890
**PR:** https://github.com/acme/api/pull/456
**Last updated:** 2026-08-26 09:14 UTC

## Progress
- [x] **Setup** — branch & workpad
- [ ] **Implement**
  - [x] reproduction captured (bug issues only)
  - [ ] code + sweeps
- [ ] **Review**
  - [ ] `/simplify`
  - [ ] `review-and-fix`
  - [ ] acceptance-criteria gate
- [ ] **Documentation**
- [ ] **PR marked ready**

## Plan
- [x] Add a bounded retry around the upstream call
- [ ] Cover the timeout path with a test

## Acceptance Criteria
- [ ] A request that times out is retried at most three times

## Devflow Reflection
```

### The Header Fields

| Field | What it tells you |
| --- | --- |
| `Status` | The run's current state, with a glyph in front of it. |
| `Branch` | The feature branch the run is working on. |
| `Run` | A link to the job log for the run. Open this when you want to see what the run actually did. |
| `PR` | A link to the pull request, once one exists. Before that it reads `_not yet created_`. |
| `Last updated` | When PRFlow last edited the comment. |

<Note>
  On a local run there is no job to link to, so `Run` will not point at a cloud job log.
</Note>

### The Sections

- **Progress** — the run's own checklist, one row per stage. The `reproduction captured` row appears only on issues classified as bug reports.
- **Plan** — the implementation plan, ticked as it is carried out.
- **Acceptance Criteria** — the issue's criteria, mirrored here and ticked as each one is verified.
- **Devflow Reflection** — blockers, deferrals, dropped work and anything else a person should read before merging. It is collapsed by default. **This heading deliberately keeps the older spelling.** It is not a typo and renaming it would break the tools that read the section.
- **Reproduction** — reproduction evidence, on bug issues.

## Status Words and Glyphs

The `Status` line carries a glyph and a status word. The glyph tells you the shape of the state at a glance and the word tells you where the run is.

| Glyph | Meaning | Status words |
| --- | --- | --- |
| 🚀 | Running | `Setup`, `Discovering`, `Reproducing`, `Planning`, `Implementing`, `Reviewing`, `Documenting` |
| 🎉 | Finished its configured lifecycle | `Complete` |
| 👎 | Stopped and needs a person | `Blocked` |
| 💥 | The run did not reach a normal end | `Failed` |
| 🛑 | The run was cancelled | `Cancelled` |

Three of those glyphs — 🚀, 🎉 and 👎 — also appear as a reaction on the comment that started the run, so you can see a run's outcome without opening the workpad. `Failed` and `Cancelled` are written by a cloud backstop when a run dies or is cancelled, and they have no matching reaction.

<Tip>
  A workpad that still shows a 🚀 status long after the run should have ended usually means the run stopped without writing its own terminal state. Open the `Run` link and read the job log.
</Tip>

## One Comment Per Run, Best Effort

PRFlow aims to keep a single progress comment per issue and it identifies that comment by a marker rather than by who wrote it. That is a best-effort convention, not a concurrency guarantee. Two runs started against the same issue at the same time can both write, and nothing in the design prevents a duplicate progress comment from appearing.

<Warning>
  Do not treat the presence of exactly one workpad as proof that only one run touched the issue. If you see two, read both and check the `Run` links before deciding which one reflects the current branch.
</Warning>

## How Resume Finds Prior Work

On a later implementation command, PRFlow reads the existing workpad before it plans anything. It also queries the open pull requests linked to the issue.

When it can establish a matching open pull request, it adopts that pull request's head branch. A recorded, in-progress plan can let the run skip repeated discovery. PRFlow still inspects the current tree and repeats any check that can block the run.

If the workpad is already `Blocked`, PRFlow surfaces the recorded cause instead of continuing through it. Resolve the cause first.

## Code Checkpoints

The workpad preserves decisions and status. Only commits and pushes preserve code.

During implementation PRFlow creates scoped checkpoints at stage boundaries. It stages **only paths it names explicitly**, creates a commit when there is new work and then confirms the pushed commit actually reached the remote branch.

Those checkpoints reduce how much an interrupted run has to repeat. They do not make every moment durable.

## What a Checkpoint Does Not Guarantee

- A file that is never named at any checkpoint is never committed. Staging is deliberately explicit — PRFlow never stages everything in the working tree — so a file that no checkpoint names stays uncommitted and is lost with the environment.
- Analysis that exists only in the live session is not durable on its own.
- Edits made after the last successful commit and push can still be lost if the environment is interrupted.
- A workpad update can fail during a GitHub outage, so the branch and repository state still have to be inspected on resume.
- A checkpoint cannot prove that the tests are right, that the review found every defect or that the branch will still merge cleanly later.
- A local run does not get the cloud workflow's bounded automatic resume. Run the command again when a local session stops.

Treat the workpad and the remote branch as recovery evidence, not as a transaction log. Read them together before deciding what a resumed run should do.

## Terminal States

- **Complete:** The run finished its configured lifecycle and recorded its verification evidence.
- **Blocked:** A dependency, an acceptance criterion, a repository condition or a verification requirement needs a person.
- **Failed** or **Cancelled:** A cloud backstop recorded that the run did not reach a normal end.

The pull request stays under human control in every one of those states.

## Related Documentation

- [The PRFlow Lifecycle](/docs/concepts/lifecycle)
- [How PRFlow Verifies a Change](/docs/concepts/verification)
- [Implement an Issue](/docs/workflows/implement)
- [Cloud Run Recovery](/docs/runs/cloud/recovery)

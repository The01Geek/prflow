---
title: "Implement an Issue"
description: "Turn an open GitHub issue into a draft pull request with recorded verification evidence."
---

Use this workflow when an open GitHub issue describes work you want built.

It creates a branch, commits and pushes changes and opens a pull request. The result is a pull request with recorded verification evidence, or a Blocked result that names the human action needed to continue.

## Run It

<Steps>
  <Step title="Pick an open issue">
    You need the issue number. The issue does not have to be perfect, but the more precisely it states the outcome you want, the closer the result lands. See [Create an Issue](/docs/workflows/create-issue) for how PRFlow writes one.
  </Step>
  <Step title="Start the run">
    In Claude Code:

    ```text
    /prflow:implement 123
    ```

    Or, if you installed the cloud tier, leave this as a comment on issue 123 itself:

    ```text
    /prflow:implement 123
    ```

    The comment form works on an issue only, not on a pull request. Only a comment body triggers a run, so a command written in the issue description starts nothing.
  </Step>
  <Step title="Watch the workpad">
    Within a minute or two, a comment appears on the issue. This is the workpad: the single place the run records what it is doing. It is created before any code is written and updated in place for the rest of the run.
  </Step>
  <Step title="Read the result">
    The run ends with the workpad at one of the terminal statuses below and, on success, a pull request linked from the workpad's `PR:` line.
  </Step>
</Steps>

### What the Workpad Looks Like

The freshly created workpad is a checklist of the whole run. For example:

```markdown
# PRFlow Workpad — Issue #123

**Status:** 🚀 Setup
**Branch:** `issue-123-prevent-duplicate-release-comments`
**Run:** _(local run)_
**PR:** _not yet created_
**Last updated:** 2026-08-26 09:14 UTC

## Progress
- [ ] **Setup** — branch & workpad
  - 09:14:22 — /prflow:implement run started
- [ ] **Implement**
  - [ ] code + sweeps
- [ ] **Review**
  - [ ] `/simplify`
  - [ ] `review-and-fix`
  - [ ] acceptance-criteria gate
- [ ] **Documentation**
- [ ] **PR marked ready**

## Plan
- [ ] _(planning in progress)_

## Acceptance Criteria
_(pending — mirrored from the issue when the run begins)_
```

The `Status` line is the fastest way to read a run. It moves through Setup, Discovering, Reproducing, Planning, Implementing, Reviewing and Documenting, and ends at one of four terminal words:

| Status | Glyph | Meaning |
| --- | --- | --- |
| Complete | 🎉 | The run finished everything it owed. |
| Blocked | 👎 | The run stopped on purpose and recorded why. A human decides what happens next. |
| Failed | 💥 | The run itself broke. |
| Cancelled | 🛑 | The run was stopped before it finished. |

The branch is named `issue-<number>-<title-slug>`, with a date suffix added when that name is already taken.

<Tip>
  A run you interrupt is resumable. Start it again with the same issue number and it adopts the same branch, the same workpad and the same pull request instead of creating a second set. See [Workpads and Resume](/docs/concepts/workpads-and-resume).
</Tip>

## What PRFlow Does

The run has four phases:

1. Fetch the issue, parse its acceptance criteria and create or resume its workpad.
2. Create or adopt the issue branch, explore the affected code, plan the change, write it and test it.
3. Open a draft pull request, simplify the change and run the review-and-fix loop.
4. File any required follow-up issues, update documentation, refresh the pull request description and finish.

The issue defines the intended outcome. Before implementation starts, PRFlow checks the issue's own claims about the repository against the current tree rather than trusting them, and it checks that the acceptance criteria cover every independently testable outcome the issue's Desired Behavior section states. An outcome no criterion covers stops the run for issue refinement. PRFlow never invents a criterion to fill the gap.

## Bug Reports Must Be Reproduced First

<Warning>
  When PRFlow classifies an issue as a bug report, reproducing the defect is a hard gate, not a best effort. If it cannot reproduce the bug, the run stops at Blocked and records the obstacle. It does not proceed to write a fix for a defect it never observed.
</Warning>

PRFlow decides "is this a bug report?" from what the issue's title and body describe, not from the `bug` label and not from a sentence in the issue telling it how to classify. A reproduction is one of three things: a failing test, a quoted error log or a recorded shell command. Whichever it captures is written into a `## Reproduction` section of the workpad, and planning cannot start until that section has content.

If the reproduction was not a failing test, PRFlow writes one before it writes the fix, and confirms it fails for the right reason first.

## Acceptance Criteria Decide What Gets Checked

Before the documentation stage, every in-scope acceptance criterion must be supported by a passing test, a documented manual check or a code reference. Two independent checkers run in a fresh context and have to agree; if they disagree, the criterion counts as unestablished and blocks, exactly as a failing one would.

A criterion that can only be confirmed in a real deployed environment stays unticked and moves to the pull request's Post-Merge Verification section.

<Warning>
  An issue with no acceptance criteria does not fail this gate — it passes it, because there is nothing to check. A prose-only issue therefore gets a run with no criteria gate at the end of it. If you want that gate to mean something, write acceptance criteria in the issue. PRFlow still stops when the issue's Desired Behavior section states a testable outcome no criterion covers, but an issue that states no such outcomes leaves nothing to compare against.
</Warning>

When a large issue deliberately defers some criteria to a later pull request, PRFlow files follow-up issues before it finishes and discloses them in the pull request description. Deferral never marks the work complete quietly.

## When a Run Stops

A Blocked result is a normal outcome, not a crash. The workpad's status becomes `👎 Blocked` and the reason is recorded in the workpad. No pull request is published, so nothing half-finished reaches your reviewers.

PRFlow stops before touching existing history when:

- The feature branch has commits that are not in the base branch and cannot be linked to the issue.
- It cannot establish that the workpad belongs to this issue and pull request.
- It cannot resolve the base reference.
- A merge is already in progress.

It stops early when the issue declares an open `Blocked by #N` dependency, or when it cannot establish whether that dependency is still open.

Later stopping points include a bug it could not reproduce, an acceptance criterion that fails or cannot be established, a verification command the run is not permitted to execute and an unresolved Critical review finding. Before publishing, PRFlow also confirms the branch tip reached the remote; if a commit was made but never landed there, the run stops rather than publish a pull request whose description cites a commit the remote does not have.

<Accordion title="What to do about a Blocked run">
  Read the reason on the workpad first — it names the specific obstacle.

  - **Cannot reproduce.** Add the missing detail to the issue: the exact trigger, the environment, the observed and expected behavior. Then run the command again.
  - **An uncovered outcome in Desired Behavior.** The workpad quotes the exact sentence no criterion covers. Add a criterion for it, or narrow the Desired Behavior section.
  - **An open dependency.** Close or unblock the prerequisite issue, then run again.
  - **A verification command that is not permitted.** Grant it in your tool-permission settings. See [Tool Permissions](/docs/configuration/tool-permissions).

  Running the command again after the fix resumes the same workpad and the same branch. It does not start over.
</Accordion>

Continuous integration is a post-pull-request merge gate. It never stands in for the verification the run does inside its own environment.

## Draft Pull Request and Review

The pull request is opened as a draft, titled with the issue title, before the review phase begins. PRFlow runs a simplification pass and then the review-and-fix loop while the pull request is still a draft, so your reviewers see the converged state rather than every intermediate one.

Non-Critical findings that survive bounded re-review are surfaced for human judgment. A genuine unresolved Critical finding blocks the run.

## Ready or Draft

The `prflow_implement.implement_pr_state` setting decides the final state:

- `ready_for_review` — the default. PRFlow marks the pull request ready after final verification.
- `draft` — the pull request stays a draft for a human to publish.

The workpad can reach Complete either way. If publication was requested and failed, the workpad records the failure and the pull request stays a draft until a human resolves it.

Human reviewers and your branch protection rules own the merge decision. PRFlow prepares the branch and the evidence. It does not approve or merge its own work.

## Related Articles

- [Review](/docs/workflows/review)
- [Review and Fix](/docs/workflows/review-and-fix)
- [Workpads and Resume](/docs/concepts/workpads-and-resume)
- [Verification](/docs/concepts/verification)
- [Implementation Settings](/docs/configuration/implementation)

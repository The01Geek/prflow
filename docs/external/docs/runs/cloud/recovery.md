---
title: "Cloud Recovery"
description: "Read a stopped PRFlow cloud run's recorded state and decide how to resume it."
---

Work out what a stopped cloud run had finished, and restart it without losing that work.

## Start With the Recorded State

Every implementation run keeps one workpad comment on the issue. Every review keeps one progress comment on the pull request. Read that comment first, then cross-check it against the linked Actions run, the current pull-request head and the remote branch.

<Note>
  The workpad is a progress record, not a transaction log. It tells you the run's last known state, not every action the run took.
</Note>

## Read the Status Glyph

The workpad's `Status` line starts with one glyph. The glyph is the authoritative signal. PRFlow also mirrors 🚀, 🎉 and 👎 as a reaction on the comment that started the run, but that reaction is best effort, so trust the `Status` line over it.

| **Glyph** | **Status** | **What It Means** | **Can It Be Resumed?** |
| --- | --- | --- | --- |
| 🚀 | Running | The run is in some phase and never reached an ending. This is the state a stalled or interrupted run is left in. | Yes. This is the one state a resume is for. |
| 🎉 | Complete | PRFlow finished its own lifecycle. | No, and it does not need to be. |
| 👎 | Blocked | A prerequisite or a verification needs a person. The run ended on purpose. | Only after you clear the named blocker. |
| 💥 | Failed | The run dead-ended and the workflow recorded it. | Yes, after you fix the cause. |
| 🛑 | Cancelled | Someone or something cancelled the run. | Yes, but only if you start it again yourself. |

<Warning>
  🎉 Complete does not mean the pull request was merged, and it is not a promise that the change is correct. Read the diff and the review before you merge.
</Warning>

<Warning>
  **A cancelled run is a decided ending, not a stall.** PRFlow's stall backstops deliberately do not resume it. They flip the workpad to 🛑 Cancelled, post no comment and consume no resume attempt. If you want the work to continue, post the original command again yourself.
</Warning>

## Recover a Stopped Run

<Steps>
  <Step title="Read the Last Workpad Note and the Matching Actions Step">
    The workpad names the phase it stopped in. Open the linked Actions run and read the step that failed or was still running.
  </Step>
  <Step title="Check the Environment Before You Change Code">
    Most stopped runs are environment problems, not code problems. Check model authentication, runner prerequisites and `.prflow/config.json` first. See [Cloud Setup](/docs/runs/cloud/setup) and [Cloud Runners](/docs/runs/cloud/runners).
  </Step>
  <Step title="Fix the Named Blocker, or Confirm the Failure Was Transient">
    A 👎 Blocked workpad names what it needs. A 💥 Failed run needs a cause you can point at in the log.
  </Step>
  <Step title="Post the Original Command Again">
    Add the same standalone comment on the same thread. For example, on the issue:

    ```text
    /prflow:implement 123
    ```
  </Step>
  <Step title="Confirm the New Run Adopted the Existing Work">
    The new run should reuse the same workpad comment on the issue and record whether it resumed unfinished work or started from a terminal state. For a review, confirm the progress comment names the current pull-request head.
  </Step>
</Steps>

## What Survives an Interruption

Implementation pushes its progress at branch checkpoints, so a later run can adopt the existing branch and pull request.

- Work committed at a checkpoint survives.
- Work done after the last pushed checkpoint can still be lost.
- A run interrupted before its first checkpoint may have left no branch changes at all.

## When PRFlow Retries by Itself

A configured stall backstop can post a bounded resume request for a run still showing 🚀. It is limited on purpose, by `prflow_implement.stall_backstop.max_resume_attempts`, which defaults to `2`.

It stops rather than looping when the attempt cap is exhausted, when authentication is unavailable or when it cannot read the run's state. In each of those cases the workflow reports the failure.

<Warning>
  Do not repeatedly retry a failure that reproduces exactly. A deterministic failure will fail again and each attempt costs a full run. Match the symptom to a cause in [Cloud-Run Problems](/docs/troubleshooting/cloud-runs) first.
</Warning>

## Related Pages

<CardGroup cols={2}>
  <Card title="Workpads and Resume" icon="clipboard" href="/docs/concepts/workpads-and-resume">
    How a workpad records progress and how a later run adopts it.
  </Card>
  <Card title="Cloud-Run Problems" icon="triangle-exclamation" href="/docs/troubleshooting/cloud-runs">
    Symptom-by-symptom fixes for cloud runs that do not start or do not finish.
  </Card>
</CardGroup>

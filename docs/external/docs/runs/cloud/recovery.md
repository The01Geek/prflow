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
    The workpad names the phase it stopped in. Open the linked Actions run and read the step that failed or was still running. When a run stops before completion, PRFlow also mirrors that reason to the top of the open pull request, so you can see why it halted from the PR page. On a resume the run's `[View run]` link on the PR is refreshed to the new run and the stale note removed before the resumed run starts, so a completed PR carries none.
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

If the runner itself disappears mid-run — for example a self-hosted or cloud host that is reclaimed or shut down — the run cannot finish its own cleanup. On the cloud implementation tier a separate recovery job reconciles that lost run for you: when the implementation job ends `failure` or `cancelled`, PRFlow classifies why the runner died and acts on it. A lost `failure` job is resumed with a bounded `/prflow:implement` request, subject to the same attempt cap as any other resume; a `cancelled` run you did not resume is a decided ending and is flipped to 🛑 Cancelled with no resume; and a resume that cannot proceed — because the attempt cap is spent, or because no App token is configured to re-trigger the run — is terminalized to 💥 Failed instead of being left 🚀 Running. Each comment the recovery job writes carries one line naming what actually happened to the runner: the job's conclusion, its capacity type (the runner's `spot=` value, or `unknown`), its runner name, and the failure message GitHub reported. If the recovery job cannot act, treat the run exactly like any other stalled 🚀 run above: read the workpad, then post the original command again to resume from the last checkpoint.

For one specific infrastructure case — an **EC2 Spot runner reclaim** — PRFlow can positively confirm that the interruption was a reclaim, if you opt in. Set `prflow_implement.spot_interruption_watcher.enabled` to the JSON boolean `true` for a repository whose implementation job runs on a Linux EC2 Spot runner (the watcher is Linux-only and off by default). When enabled, a background watcher notices the Spot interruption notice while the runner is still alive and records a durable reclaim marker, so the recovery job can name the loss as a confirmed EC2 Spot reclaim rather than a generic runner loss. A cancellation you initiated is never mistaken for a reclaim; a runner loss PRFlow cannot positively identify as a reclaim is still resumed as above, but its comment names the real conclusion instead of claiming a Spot reclaim.

## When PRFlow Retries by Itself

A configured stall backstop can post a bounded resume request for a run still showing 🚀. It is limited on purpose, by `prflow_implement.stall_backstop.max_resume_attempts`, which defaults to `2`.

After any failed agent step PRFlow posts a bounded `/prflow:implement` resume — the same capped resume it uses for any interrupted 🚀 run — unless you have opted into deferring to a runner retry (below). A rate-limit or provider failure resumes the same way; the attempt cap is what bounds a resume that lands on a still-exhausted limit. When the resume cap is already spent, PRFlow marks the workpad 💥 Failed with the reason on one line instead of looping.

`prflow_implement.stall_backstop.defer_to_runner_retry` governs whether a failed step is deferred to your runner's own retry instead of resumed by PRFlow. Set it to the JSON boolean `true` when your runner retries a failed job on its own (for example RunsOn with `retry=when-interrupted`): PRFlow then defers, leaving the workpad in progress, posting one short informational comment, and letting the runner's retry resume from the last checkpoint, so the two recovery mechanisms never drive the same issue at once. Leave it at the default `false` on any runner without job-level retry — the backstop then resumes the failure itself, and setting it `true` there would leave the run waiting on a retry that never comes.

It stops rather than looping when the attempt cap is exhausted, when authentication is unavailable or when it cannot read the run's state. In each of those cases the workflow reports the failure.

Each resume or failure comment is short and names why the run died on one line — for example a usage-limit rejection versus a genuine stall — so you can tell at a glance whether retrying will hit the same limit. The full engine diagnostics, including a scrubbed excerpt of the error text, stay in the run log and the run's step summary rather than the comment.

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

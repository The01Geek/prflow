---
title: "Cloud Runs"
description: "Run PRFlow from authorized GitHub comments through repository automation."
---

Let authorized collaborators start PRFlow from a GitHub comment, with no local Claude Code session open.

A cloud command passes through an authorization gate before the agent job starts. The gate holds narrow GitHub permissions. The agent job then receives the model credentials and the repository permissions you configured. Maintainer-controlled workflow files and `.prflow/config.json` define both jobs. The run writes its work to a branch, a workpad, a pull request or a review.

![A cloud command moves from a GitHub comment through an authorization gate with narrow GitHub permissions, then into an agent job with model credentials and configured repository permissions. The agent job produces a branch, workpad, pull request or review for a person to review and merge.](/images/cloud-run-trust-boundary.svg)

## What a Fresh Installation Ships

A fresh installation adds two workflow files, and they answer four comment commands:

| **Comment Command** | **Where You Post It** | **What It Produces** |
| --- | --- | --- |
| `/prflow:implement 123` | A comment on the issue. | A feature branch and a pull request that resolves the issue. |
| `/prflow:review` | A comment on a pull request's **Conversation** tab. | A review verdict. It changes no code. |
| `/prflow:review-and-fix` | A comment on a pull request's **Conversation** tab. | Review findings plus fixes pushed to the pull-request branch. |
| `/prflow:pr-description` | A comment on a pull request's **Conversation** tab. | A written or updated pull-request description. |

<Warning>
  No cloud run merges a pull request. Every command ends with work a person still has to read, approve and merge.
</Warning>

<Note>
  Automatic pull-request-triggered review is not included in a fresh installation. If you want a review to be requested without anyone typing a comment, add the workflow on [Request a Review Automatically on Green CI](/docs/runs/cloud/auto-review).
</Note>

## Set Up Cloud Runs

<Steps>
  <Step title="Install the Cloud Tier">
    Run the installer from the repository root. See [Cloud Installation](/docs/runs/cloud/installation).
  </Step>
  <Step title="Add Authentication and Project Setup">
    Add the model credential, review `.prflow/config.json` and declare how the runner is provisioned. See [Cloud Setup](/docs/runs/cloud/setup).
  </Step>
  <Step title="Choose a Runner">
    Keep the default GitHub-hosted Linux runner, or point the workflows at your own. See [Cloud Runners](/docs/runs/cloud/runners).
  </Step>
  <Step title="Learn the Comment Triggers">
    Learn the exact comment format and who is allowed to use it. See [Cloud Triggers](/docs/runs/cloud/triggers).
  </Step>
  <Step title="Try a Low-Stakes Run">
    Use a throwaway pull request or a small issue before you rely on the automation.
  </Step>
</Steps>

## Keep It Running

<CardGroup cols={2}>
  <Card title="Updates" icon="arrow-up" href="/docs/runs/cloud/updates">
    Move an existing installation to a newer release without losing your configuration.
  </Card>
  <Card title="Recovery" icon="life-ring" href="/docs/runs/cloud/recovery">
    Read a workpad status and resume a run that stopped before it finished.
  </Card>
</CardGroup>

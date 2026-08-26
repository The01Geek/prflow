---
title: "Cloud Setup"
description: "Configure cloud authentication, repository settings and runtime provisioning."
---

Complete the secrets, variables and repository settings a first PRFlow cloud run needs.

## Add Model Authentication

The default Anthropic route needs one repository or environment secret:

```text
CLAUDE_CODE_OAUTH_TOKEN
```

Add it under **Settings → Secrets and variables → Actions → Secrets**. GitHub's built-in `GITHUB_TOKEN` handles GitHub operations and needs no setup.

<Note>
  A fully provider-routed installation can use `DEVFLOW_PROVIDER_API_KEY` instead. Route every active section before you remove `CLAUDE_CODE_OAUTH_TOKEN`. A partly routed installation may need both secrets, because each section chooses its route independently. See [Providers](/docs/configuration/providers).
</Note>

## Review Repository Configuration

The installer creates `.prflow/config.json`. Commit it, because the workflows read it from the repository, not from your machine.

At minimum, review:

- `base_branch` and `claude_model`.
- `prflow.allowed_users` and `prflow.allowed_bots`, which decide who may start a run.
- The `setup` block, for runtimes and install commands.
- `prflow.allowed_tools` and `prflow_implement.allowed_tools`, for repository-specific commands.
- `workflows.prflow`, which enables the shipped command and implementation paths.

Running `/prflow:init` after an installation or an upgrade is recommended. It adds newly scaffolded settings without replacing values you already set, and it detects common project tools.

## Provision the Runtime

PRFlow prepares the runner in this order:

1. Set up Python.
2. Set up Node.js.
3. Set up PHP.
4. Start the service containers named in `setup.services`, using Docker.
5. Run each `setup.install` line from the repository root.

Keep Python 3.11 or newer and PyYAML available even in a project that is not written in Python, because PRFlow's own cloud helpers need them.

<Warning>
  Provisioning a command does not grant the agent permission to run it. Add the command to the correct allowlist as a separate step. See [Runtime Setup](/docs/configuration/runtime-setup) and [Tool Permissions](/docs/configuration/tool-permissions).
</Warning>

## Optional GitHub App

The default path needs no GitHub App. Add one when a cloud implementation run has to push changes under `.github/workflows/`, when you want a dedicated automation identity or when a configured stall backstop has to post a resume comment that starts another run.

| **Kind** | **Name** |
| --- | --- |
| Repository or organization variable | `DEVFLOW_APP_ID` |
| Repository or organization secret | `DEVFLOW_APP_PRIVATE_KEY` |

Install the App on the repository with `Contents: write`, `Workflows: write`, `Pull requests: write`, `Issues: write` and `Actions: read`.

An unset App falls back to `GITHUB_TOKEN`. A configured but invalid App fails loudly at the token-creation step.

## Optional Reviewer App

This is a second, separate GitHub App, used only by the `/prflow:review` comment command.

| **Kind** | **Name** |
| --- | --- |
| Repository variable | `DEVFLOW_REVIEWER_APP_ID` |
| Repository secret | `DEVFLOW_REVIEWER_PRIVATE_KEY` |

Install it on the repository with a narrower permission set than the primary App: `Contents: read`, `Issues: read`, `Pull requests: write` and `Actions: read`. It reads the repository, the issue and CI results, and it posts comments and formal reviews. It cannot push.

Why a second App exists: GitHub does not let an identity approve or request changes on its own pull request. When the same identity both authors a pull request and reviews it, the formal review cannot be recorded.

<Warning>
  **If you do not configure this App, review attribution falls back to the default Actions identity, `github-actions[bot]`.** An approval from `github-actions[bot]` does not satisfy a branch-protection rule that requires approving reviews. Configure the reviewer App if you rely on that rule.
</Warning>

Two details are easy to miss:

- `/prflow:review-and-fix` and `/prflow:pr-description` do not use the reviewer App. They push or author content, so they stay on the primary App token.
- Both halves of the pair matter, and they fail differently. If the **variable** is missing or misspelled, the reviewer step is skipped silently, exactly as if you had chosen not to configure it. If the variable resolves but the **secret** is wrong, the step fails loudly.

## Run a Smoke Test

Open a throwaway pull request and add this as a comment of its own on the **Conversation** tab:

```text
/prflow:review
```

You should see three things: a 🚀 reaction added to your own comment as an acknowledgement, a new workflow run under the **Actions** tab and a progress comment on the pull request that PRFlow rewrites as it works. The progress comment ends with the full report and an APPROVE or REJECT verdict.

The reaction is best effort. Its absence is a weak signal on its own, so check the **Actions** tab before you conclude that nothing started.

If nothing happens at all, the most common causes are an unauthorized commenter and a comment that is not on a line of its own. See [Cloud Triggers](/docs/runs/cloud/triggers) and [Cloud-Run Problems](/docs/troubleshooting/cloud-runs).

For implementation, use a low-risk issue and follow [Cloud Triggers](/docs/runs/cloud/triggers).

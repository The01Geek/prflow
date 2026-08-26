---
title: "Local Runs"
description: "Run PRFlow interactively from a Claude Code session in your own checkout."
---

Run PRFlow directly from Claude Code. A local run is the fastest way to start, and it needs no GitHub Actions workflow and no repository secret.

## Run Your First Local Command

<Steps>
  <Step title="Open Claude Code Inside the Repository">
    Start the session from anywhere inside the target Git checkout.

    ```bash
    cd ~/code/acme-api
    claude
    ```
  </Step>
  <Step title="Enter a Namespaced Command">
    Every PRFlow command starts with `/prflow:`.

    ```text
    /prflow:implement 123
    ```
  </Step>
  <Step title="Answer the Permission Prompts">
    Claude Code asks before it edits files, runs a command or calls `gh`. Approve only what the workflow needs. See [Local Permissions](/docs/runs/local/permissions).
  </Step>
  <Step title="Watch the Run Report Its Progress">
    An implementation run leaves three things behind:

    - A workpad comment on issue 123, which it keeps updated as it works.
    - A feature branch named after the issue, such as `issue-123-add-retry-to-webhook-client`.
    - A pull request that links back to the issue.

    The workpad's `Status` line carries a glyph: 🚀 while the run is still working, then 🎉 Complete, 👎 Blocked, 💥 Failed or 🛑 Cancelled.
  </Step>
</Steps>

<Warning>
  🎉 Complete means PRFlow finished its own lifecycle. It does not mean the pull request was merged, and it is not a guarantee that the change is correct. Read the review and the diff before you merge.
</Warning>

## What a Local Run Uses

- The repository and Git root discovered from the current directory.
- Your authenticated GitHub CLI identity.
- The tests, linters and development tools already installed on the machine.
- Claude Code's permission system and your answers to it.
- Built-in configuration defaults, plus `.prflow/config.json` overrides when the file is present.

Repository initialization with `/prflow:init` is recommended so you can customize behavior, but a local run works without it.

## When to Run Locally

<CardGroup cols={2}>
  <Card title="Interactive Decisions" icon="comments">
    Answer clarification questions while the work is still in progress.
  </Card>
  <Card title="Tight Permission Control" icon="shield-check">
    Approve each tool request as it happens instead of granting a standing allowlist.
  </Card>
  <Card title="Local-Only Workflows" icon="wrench">
    Create issues, initialize configuration, update documentation and run the weekly retrospective. None of these has a cloud trigger.
  </Card>
  <Card title="A Trusted Environment" icon="laptop">
    Use services, credentials and development tools that are already set up on your workstation.
  </Card>
</CardGroup>

## Next Steps

- Read the [commands and arguments](/docs/runs/local/client-commands) each workflow accepts.
- Review the [local permission boundaries](/docs/runs/local/permissions).
- Understand [working-directory and Git-root behavior](/docs/runs/local/working-directory) before you run from a subdirectory or a monorepo.

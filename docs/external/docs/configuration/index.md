---
title: "Configuration"
description: "Learn where PRFlow's settings live, when you need them and which page documents each family."
---

Start here to find out what PRFlow reads from your repository and which page documents the setting you need.

## Where Configuration Lives

PRFlow reads one file: `.prflow/config.json` at the root of your repository. It is plain JSON and it is committed, so your whole team and every cloud run see the same values.

Two other files sit beside it and are not settings:

- `.prflow/config.example.json` is the scaffolded reference copy. It shows the shape of every section.
- `.prflow/prompt-extensions/` holds [prompt extensions](/docs/configuration/prompt-extensions), which are instructions rather than values.

Run [`/prflow:init`](/docs/getting-started/initialization) to create the file. It writes the file when it is absent and adds newly scaffolded keys to an existing file without replacing values or arrays you already set.

## When You Need a Config File

<CardGroup cols={2}>
  <Card title="Local Runs" icon="terminal" href="/docs/runs/local/index">
    Work with no config file at all. Every setting falls back to a built-in default. Add the file when you want to change one.
  </Card>
  <Card title="Cloud Runs" icon="cloud" href="/docs/runs/cloud/index">
    Require the file, committed to your default branch. A cloud workflow reads it to decide whether it may run at all.
  </Card>
</CardGroup>

Cloud workflows resolve their settings from the default branch at the moment a run is triggered. A pull request that changes such a setting does not change its own run. The new value applies after the pull request merges.

## A Starter Config

This is a complete, valid config file. It enables the cloud workflow, names the base branch and grants one test command to the implementation path:

```json
{
  "$schema": "./config.schema.json",
  "base_branch": "main",
  "claude_model": "claude-opus-5",
  "prflow_implement": {
    "allowed_tools": [
      "Bash(npm test:*)"
    ]
  },
  "workflows": {
    "prflow": true
  }
}
```

Expected result: local commands keep working exactly as before, cloud runs are enabled for authorized users and a cloud implementation run may invoke `npm test`. Every key not listed keeps its default.

## Setting Families

<CardGroup cols={2}>
  <Card title="All Settings A to Z" icon="list" href="/docs/configuration/settings">
    Every setting name in alphabetical order with the page that documents it. Start here when you know the key.
  </Card>
  <Card title="Core Settings" icon="sliders" href="/docs/configuration/core-settings">
    Base branch, model, who may trigger a cloud run and which workflows are enabled.
  </Card>
  <Card title="Implementation" icon="code" href="/docs/configuration/implementation">
    Pull request state, branch checkpoints, stall handling and verification reuse.
  </Card>
  <Card title="Review" icon="magnifying-glass" href="/docs/configuration/review">
    Verdict thresholds, fix routing, progress comments and retained legacy settings.
  </Card>
  <Card title="Review Agents" icon="users" href="/docs/configuration/review-agents">
    Per-agent model, effort and iteration overrides inside the review engine.
  </Card>
  <Card title="Prompt Extensions" icon="file-pen" href="/docs/configuration/prompt-extensions">
    Your team's own instructions, appended to a command on every run.
  </Card>
  <Card title="Model Providers" icon="network-wired" href="/docs/configuration/providers">
    Route cloud execution through a gateway or Amazon Bedrock.
  </Card>
  <Card title="Runtime Setup" icon="server" href="/docs/configuration/runtime-setup">
    Languages, service containers and install commands for the cloud runner.
  </Card>
  <Card title="Tool Permissions" icon="lock" href="/docs/configuration/tool-permissions">
    The repository commands a cloud agent is allowed to run.
  </Card>
  <Card title="Documentation and Retrospectives" icon="book" href="/docs/configuration/documentation-and-retrospectives">
    Documentation paths, deferred-issue labels and weekly retrospective limits.
  </Card>
  <Card title="Observability and Privacy" icon="shield-halved" href="/docs/configuration/observability-and-privacy">
    Diagnostics, transcript artifacts, denied-command records and telemetry storage.
  </Card>
</CardGroup>

## Treat Configuration as Code

<Warning>
  Several settings decide what a cloud agent may run and who may start it. `prflow.allowed_users`, every `allowed_tools` array and every `setup.install` line grant execution or access. Review a change to them as carefully as a change to a workflow file.
</Warning>

Validate the JSON before you commit it. Cloud config loading checks that the file is valid JSON, but it does not run a full schema check, so a misspelled key can pass unnoticed and leave the default in place.

Next: find your setting in [All Settings A to Z](/docs/configuration/settings), or read [Core Settings](/docs/configuration/core-settings) first if you are setting the file up for the first time.

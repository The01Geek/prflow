---
title: "Running PRFlow Locally: Commands and Arguments"
description: "Learn the PRFlow command syntax, the arguments each workflow accepts and which workflows only run locally."
---

Use the right command syntax and the right arguments when you run PRFlow from Claude Code.

## One Syntax

Every PRFlow command has the same shape:

```text
/prflow:<skill> [arguments]
```

Replace `<skill>` with a workflow name such as `implement`, `review` or `init`. A worked example:

```text
/prflow:implement 123
```

Claude Code shows the matching skill as you type `/prflow:`. If nothing appears, the session was started before the plugin finished installing. Start a new session and try again. See [Installation](/docs/getting-started/installation).

<Warning>
  Always include the `prflow` namespace. Names such as `review` and `init` can collide with commands built into a coding client, and a bare name can start a different tool with different behavior.
</Warning>

<Note>
  PRFlow's documented syntax describes Claude Code. The plugin has also been verified to work in GitHub Copilot CLI, Codex CLI, Codex Desktop and VS Code agent modes. Those clients name and invoke plugin commands their own way, so follow each client's own documentation for its prefix.
</Note>

## Commands and Their Arguments

Arguments follow the skill name, separated by spaces. Square brackets below mean the argument is optional.

| **Command** | **Arguments** | **What It Does** |
| --- | --- | --- |
| `/prflow:create-issue` | `<user story>` | Turns a rough description into a written GitHub issue. |
| `/prflow:implement` | `<issue-number>` | Turns an existing issue into a branch and a pull request. |
| `/prflow:review` | `[pr-number] [--issue N]` | Reviews a pull request or the current branch and reports a verdict. |
| `/prflow:review-and-fix` | `[pr-number] [--push-each-iteration] [--issue N]` | Reviews, applies fixes and repeats until the verdict is clean. |
| `/prflow:pr-description` | `[issue-number]` | Writes or updates the pull-request description for the current branch. |
| `/prflow:docs` | none | Updates internal docs, external docs and release notes together. |
| `/prflow:docs-verify` | `<topic>` | Checks whether the documentation for one named topic is accurate. |
| `/prflow:retrospective-weekly` | none | Runs the weekly self-improvement loop over recently merged pull requests. |
| `/prflow:init` | none | Scaffolds or refreshes this repository's `.prflow/` configuration. |

The narrower documentation commands `docs-sync-internal`, `docs-sync-external`, `docs-bootstrap-internal`, `docs-bootstrap-external` and `docs-release-notes` take no arguments either. See [Workflow Guides](/docs/workflows/index) for what each one produces.

<Accordion title="Argument Conventions in Detail">
  - **A bare number is a pull-request or issue number.** In `/prflow:review` and `/prflow:review-and-fix`, only a bare number binds the pull-request number. A number that follows `--issue` is never read as the pull-request number.
  - **Omit the number to work on the current branch.** `/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description` fall back to the branch you have checked out, compared against the configured base branch.
  - **`--issue N` names the issue whose acceptance criteria the review reads.** Use it when the pull request does not already point at the right issue.
  - **`--push-each-iteration` pushes each completed fix cycle, and the final loop state, to the feature branch.** Without it a local fix run commits but never pushes, so the fixes stay on your machine.
  - **`/prflow:implement` needs an issue number.** It reads that issue's body as the specification.
</Accordion>

## Which Commands Run Only Locally

A fresh cloud installation answers four comment commands. Everything else in the table above is local-only.

<CardGroup cols={2}>
  <Card title="Available Locally and in the Cloud" icon="cloud">
    `implement`, `review`, `review-and-fix` and `pr-description`.
  </Card>
  <Card title="Local Only" icon="terminal">
    `create-issue`, `init`, the whole `docs` family and `retrospective-weekly`.
  </Card>
</CardGroup>

Two differences matter when you move between the two:

- **A cloud comment command ignores a trailing number.** `/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description` always act on the thread they were posted on. Locally, a bare number selects a different pull request.
- **`/prflow:implement` in the cloud runs only from a comment on an issue.** A comment on a pull request never starts one.

See [Cloud Triggers](/docs/runs/cloud/triggers) for the full comment rules.

## Use the Current Namespace

Write new commands with the `/prflow:` spelling. The older `/devflow:` spelling is still accepted as a compatibility alias for GitHub comment triggers, where it is normalized to the current form. Do not use it in new documentation, scripts or automation.

---
title: "Running PRFlow Locally: Commands and Arguments"
description: "Learn the PRFlow skill syntax in Claude Code and Codex, the arguments each workflow accepts and which workflows only run locally."
---

Use the right skill syntax and arguments when you run PRFlow from Claude Code or Codex.

## Choose Your Client's Syntax

The skill name stays `prflow:<skill>`. The client decides how you select it.

<Tabs>
  <Tab title="Claude Code">
    Enter the skill as a slash command:

    ```text
    /prflow:implement 123
    ```

    Expected result: Claude Code's completion menu offers the matching PRFlow skill as you enter `/prflow:`.
  </Tab>
  <Tab title="Codex CLI">
    Mention the skill with `$`, or enter `/skills` and select it from the picker:

    ```text
    $prflow:implement 123
    ```

    Expected result: Codex attaches `prflow:implement` to the request and follows that skill. The ordinary `/` completion menu contains built-in Codex commands, so `/implement` and `/prflow:implement` do not select the plugin skill.
  </Tab>
  <Tab title="ChatGPT Desktop App">
    In a Codex chat, mention the skill with `$`:

    ```text
    $prflow:implement 123
    ```

    Expected result: the composer attaches the `prflow:implement` skill. Selecting `@prflow` names the plugin on ChatGPT surfaces; it is not the Codex skill-name menu.
  </Tab>
</Tabs>

Codex can also select a skill implicitly. For example, `Use PRFlow to implement GitHub issue 123` matches the installed `prflow:implement` skill without an explicit mention.

<Warning>
  Always include the `prflow` namespace when you select a skill explicitly. Names such as `review` and `init` can collide with built-in client commands and start different behavior.
</Warning>

## Commands and Their Arguments

Arguments follow the skill name, separated by spaces. Square brackets below mean the argument is optional.

| **Skill** | **Arguments** | **What It Does** |
| --- | --- | --- |
| `prflow:spec` (alias `prflow:create-issue`) | `<user story>` | Turns a rough description into a written GitHub issue. `spec` is the preferred name; `create-issue` is a transitional alias that forwards to it. |
| `prflow:implement` | `<issue-number>` | Turns an existing issue into a branch and a pull request. |
| `prflow:review` | `[pr-number] [--issue N]` | Reviews a pull request or the current branch and reports a verdict. |
| `prflow:review-and-fix` | `[pr-number] [--push-each-iteration] [--issue N]` | Reviews, applies fixes and repeats until the verdict is clean. |
| `prflow:pr-description` | `[issue-number]` | Writes or updates the pull-request description for the current branch. |
| `prflow:docs` | none | Updates internal docs, external docs and release notes together. |
| `prflow:docs-verify` | `<topic>` | Checks whether the documentation for one named topic is accurate. |
| `prflow:retrospective-weekly` | none | Runs the weekly self-improvement loop over recently merged pull requests. |
| `prflow:init` | none | Scaffolds or refreshes this repository's `.prflow/` configuration. |

The narrower documentation commands `docs-sync-internal`, `docs-sync-external`, `docs-bootstrap-internal`, `docs-bootstrap-external` and `docs-release-notes` take no arguments either. See [Workflow Guides](/docs/workflows/index) for what each one produces.

<Accordion title="Argument Conventions in Detail">
  - **A bare number is a pull-request or issue number.** In `prflow:review` and `prflow:review-and-fix`, only a bare number binds the pull-request number. A number that follows `--issue` is never read as the pull-request number.
  - **Omit the number to work on the current branch.** `prflow:review`, `prflow:review-and-fix` and `prflow:pr-description` fall back to the branch you have checked out, compared against the configured base branch.
  - **`--issue N` names the issue whose acceptance criteria the review reads.** Use it when the pull request does not already point at the right issue.
  - **`--push-each-iteration` pushes each completed fix cycle, and the final loop state, to the feature branch.** Without it a local fix run commits but never pushes, so the fixes stay on your machine.
  - **`prflow:implement` needs an issue number.** It reads that issue's body as the specification.
</Accordion>

## Which Commands Run Only Locally

A fresh cloud installation answers four comment commands. Everything else in the table above is local-only.

<CardGroup cols={2}>
  <Card title="Available Locally and in the Cloud" icon="cloud">
    `implement`, `review`, `review-and-fix` and `pr-description`.
  </Card>
  <Card title="Local Only" icon="terminal">
    `spec` (alias `create-issue`), `init`, the whole `docs` family and `retrospective-weekly`.
  </Card>
</CardGroup>

Two differences matter when you move between the two:

- **A cloud comment command ignores a trailing number.** `/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description` always act on the thread they were posted on. Locally, a bare number selects a different pull request.
- **`/prflow:implement` in the cloud runs only from a comment on an issue.** A comment on a pull request never starts one.

See [Cloud Triggers](/docs/runs/cloud/triggers) for the full comment rules.

## Use the Current Namespace

Use the `prflow:` namespace for local skills: `/prflow:` in Claude Code and `$prflow:` in Codex. GitHub comment triggers continue to use `/prflow:`. The older `/devflow:` spelling is still accepted as a compatibility alias for GitHub comment triggers, where it is normalized to the current form. Do not use it in new documentation, scripts or automation.

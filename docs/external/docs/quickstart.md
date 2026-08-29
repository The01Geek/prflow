---
title: "Quickstart"
description: "Install PRFlow and turn your first issue into a review-ready pull request."
---

Go from nothing installed to a pull request you can review. Allow about 10 minutes, plus the time PRFlow spends on the change itself.

For the longer explanation behind each step, follow [Getting Started](/docs/getting-started/index) instead.

## Before You Start

You need a GitHub repository you can push to, Claude Code and five tools on your `PATH`.

```bash
git --version
gh --version
jq --version
python3 --version
bash --version
gh auth status
```

Python must be 3.11 or newer, and `bash` must be a POSIX Bash. On macOS, `/usr/bin/python3` is often 3.9 — check with `python3 -VV` and install a newer Python if needed. On Windows, use WSL Bash, Git Bash or MSYS2 Bash.

`gh auth status` must report an account that can read issues and create branches, comments and pull requests in the repository you plan to change.

<Note>
  PRFlow does not need a configuration file to run locally. Every setting has a built-in default.
</Note>

## 1. Install the Plugin

```bash
claude plugin marketplace add The01Geek/prflow
claude plugin install prflow@devflow-marketplace
```

The marketplace is named `devflow-marketplace` on purpose. The plugin is named `prflow`.

Start a new Claude Code session, then confirm the commands are available by entering `/prflow:` in the prompt. You should see the PRFlow commands offered as completions.

## 2. Set Up Your Repository

From anywhere inside the repository you want to change:

```text
/prflow:init
```

This step is recommended, not required. It writes `.prflow/config.json`, detects the build, test and lint tools your project already uses, grants them to PRFlow and checks your prerequisites. It finishes by reporting the dependency check:

```text
devflow preflight: all dependencies present.
```

If a tool is missing, initialization tells you which one and what to install. The configuration it already wrote is kept, so you install the tool and continue.

Review the diff before you commit it. `/prflow:init` does not commit anything for you.

## 3. Create an Issue

Skip this if you already have an issue with clear acceptance criteria.

```text
/prflow:create-issue Add a --retain-days option so completed run logs can be kept for 30 days
```

PRFlow reads your repository, asks the questions it cannot answer from the code, then saves the issue draft to a file and shows you its path (print the full draft in chat on request). Nothing is created until you approve that exact draft.

Approve it, and PRFlow creates the issue and tells you its number.

<Tip>
  Acceptance criteria are what PRFlow checks its own work against later. An issue with none still runs, but there is nothing for that check to test. Keep them in the draft.
</Tip>

## 4. Implement It

Replace `123` with your issue number.

```text
/prflow:implement 123
```

PRFlow creates a branch named `issue-123-<title-slug>`, then posts a single progress comment to the issue and keeps it updated for the whole run. That comment is the workpad. Abridged, it looks like this:

```markdown
# PRFlow Workpad — Issue #123

**Status:** 🚀 Implementing
**Branch:** `issue-123-add-retain-days-option`
**Run:** _(local run)_
**PR:** _not yet created_
**Last updated:** 2026-08-26 09:41 UTC

## Progress
- [x] **Setup** — branch & workpad
- [ ] **Implement**
  - [x] code + sweeps
- [ ] **Review**
  - [ ] `/simplify`
  - [ ] `review-and-fix`
  - [ ] acceptance-criteria gate
- [ ] **Documentation**
- [ ] **PR marked ready**
```

The status glyph tells you where the run stands at a glance:

| Glyph | Meaning |
| --- | --- |
| 🚀 | Running. The word beside it names the current stage. |
| 🎉 | Complete. The run finished its lifecycle and recorded its evidence. |
| 👎 | Blocked. Something needs a person. The reason is recorded in the workpad. |
| 💥 | Failed. A cloud run ended without a normal result. |
| 🛑 | Cancelled. |

When the run finishes, you have a branch, a pull request that closes the issue and a workpad recording what was verified and anything PRFlow could not settle.

## 5. Review and Merge

Read the pull request the way you would read a colleague's: the code, the tests, the documentation and the acceptance-criteria evidence in the workpad.

For a second opinion from a fresh review with no memory of building the change:

```text
/prflow:review 123
```

That returns findings and a verdict. Then merge it yourself. PRFlow never merges.

## If a Run Stops

A run that ends with 👎 **Blocked** is telling you something specific. Common causes are an issue that depends on another open issue, a bug PRFlow could not reproduce, an acceptance criterion that does not pass, or a verification command it is not permitted to run.

Read the reason in the workpad, resolve it and run the same command again. PRFlow picks up from the last recorded checkpoint.

[Troubleshooting](/docs/troubleshooting/implementation) covers each cause and its fix.

## What to Read Next

<CardGroup cols={2}>
  <Card title="Workflows" icon="route" href="/docs/workflows/index">
    Every command, what it is allowed to change and when to use it.
  </Card>
  <Card title="How PRFlow Works" icon="diagram-project" href="/docs/concepts/index">
    The lifecycle, the review system and where your control points are.
  </Card>
  <Card title="Configuration" icon="sliders" href="/docs/configuration/index">
    Set the base branch, tool permissions, review thresholds and documentation paths.
  </Card>
  <Card title="Cloud Runs" icon="cloud" href="/docs/runs/cloud/index">
    Start PRFlow from a GitHub comment instead of your terminal.
  </Card>
</CardGroup>

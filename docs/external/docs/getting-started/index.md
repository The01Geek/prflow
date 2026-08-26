---
title: "Getting Started"
description: "Install PRFlow, set up a repository and turn your first issue into a review-ready pull request."
---

This section takes you from an empty machine to your first PRFlow pull request.

PRFlow is a plugin for [Claude Code](https://code.claude.com). It takes a GitHub issue and carries it through planning, implementation, verification, review and documentation, then leaves you a pull request. You keep final review and merge control. PRFlow never merges the pull request for you.

PRFlow works best in an established repository, where a change has to follow architecture, tests and documentation conventions that already exist.

<Tip>
  If you want the shortest possible path, read the [Quickstart](/docs/quickstart) first. It covers install and first run on one page. Come back here when you want the detail behind each step.
</Tip>

## Follow the Steps in Order

<CardGroup cols={2}>
  <Card title="Requirements" icon="list-check" href="/docs/getting-started/requirements">
    The tools PRFlow needs on your machine and the GitHub access it needs on your account.
  </Card>
  <Card title="Installation" icon="download" href="/docs/getting-started/installation">
    Add the marketplace and install the plugin in Claude Code.
  </Card>
  <Card title="Initialization" icon="sliders" href="/docs/getting-started/initialization">
    Run `/prflow:init` to scaffold repository configuration and detected tool permissions.
  </Card>
  <Card title="First Run" icon="rocket" href="/docs/getting-started/first-run">
    Run `/prflow:implement` on a real issue and read the progress workpad it writes.
  </Card>
  <Card title="Updates" icon="arrows-rotate" href="/docs/getting-started/updates">
    Move an existing installation to a newer release, locally and in the cloud.
  </Card>
  <Card title="Migrate from DevFlow" icon="right-left" href="/docs/getting-started/migrate-from-devflow">
    Move a repository that was set up before the PRFlow rename.
  </Card>
</CardGroup>

## Choose Where Runs Execute

[Local runs](/docs/runs/local/index) use the tools, credentials and permission system already present in Claude Code. They are the fastest way to start, and nothing else is required.

[Cloud runs](/docs/runs/cloud/index) use GitHub Actions and repository credentials, so a run can start from a comment on an issue. Add them after the local workflow fits your team.

## Related Documentation

- [How PRFlow Works](/docs/concepts/index)
- [Workflow Guides](/docs/workflows/index)
- [Troubleshooting](/docs/troubleshooting/index)

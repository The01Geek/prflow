---
title: "Installation"
description: "Install the PRFlow plugin in Claude Code."
---

Install the PRFlow plugin so its skills are available in Claude Code.

The plugin is named `prflow`. Its marketplace keeps the name `devflow-marketplace` on purpose, so do not rename it. PRFlow depends on no companion plugin.

If you already installed DevFlow, follow [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow) instead of this page.

## Install the Plugin

<Steps>
  <Step title="Add the Marketplace">
    Run this in your terminal:

    ```bash
    claude plugin marketplace add The01Geek/prflow
    ```
  </Step>
  <Step title="Install PRFlow">
    ```bash
    claude plugin install prflow@devflow-marketplace
    ```

    The plugin name and the marketplace name are different on purpose. Enter both exactly as shown.
  </Step>
  <Step title="Confirm the Skills Are Loaded">
    Start a new Claude Code session, then enter `/` and look for the `prflow` skills, such as `/prflow:init` and `/prflow:implement`.

    If they do not appear, the session was started before the install finished. Start another session.
  </Step>
</Steps>

The interactive `/plugin` manager offers the same marketplace and install actions if you prefer to work in a menu.

<Note>
  **Other agent clients.** Claude Code plugins are largely compatible with other agent clients, and PRFlow has been verified to work in GitHub Copilot CLI, Codex CLI, Codex Desktop and VS Code agent modes. Each client installs and names plugins differently, so follow that client's own plugin-installation instructions. PRFlow's documented commands and syntax describe Claude Code.
</Note>

## What Installation Does Not Do

Installing the plugin does not create repository configuration and does not install system packages. Two things are still yours to do:

- Install the [local requirements](/docs/getting-started/requirements) yourself. The plugin manager never runs `pip`, `brew` or `apt`.
- Run [initialization](/docs/getting-started/initialization) in each repository you want PRFlow to work in. This step is recommended. Local runs still work on built-in defaults without it.

## Next Steps

<CardGroup cols={2}>
  <Card title="Requirements" icon="list-check" href="/docs/getting-started/requirements">
    Confirm Git, the GitHub CLI, `jq`, Python and a POSIX bash shell are ready.
  </Card>
  <Card title="Initialization" icon="sliders" href="/docs/getting-started/initialization">
    Scaffold `.prflow/` configuration for the repository.
  </Card>
  <Card title="First Run" icon="rocket" href="/docs/getting-started/first-run">
    Turn a real issue into a pull request.
  </Card>
  <Card title="Updates" icon="arrows-rotate" href="/docs/getting-started/updates">
    Move to a newer PRFlow release later.
  </Card>
</CardGroup>

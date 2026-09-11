---
title: "Installation"
description: "Install the PRFlow plugin in Claude Code or Codex."
---

Install the PRFlow plugin so its skills are available in Claude Code, Codex CLI or Codex in the ChatGPT desktop app.

The plugin is named `prflow`. Its marketplace keeps the name `devflow-marketplace` on purpose, so do not rename it. PRFlow depends on no companion plugin.

If you already installed DevFlow, follow [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow) instead of this page.

## Install the Plugin

<Tabs>
  <Tab title="Claude Code">
    <Steps>
      <Step title="Add the Marketplace">
        Run this in your terminal:

        ```bash
        claude plugin marketplace add The01Geek/prflow
        ```

        Expected result: Claude Code reports that it added the `devflow-marketplace` marketplace.
      </Step>
      <Step title="Install PRFlow">
        ```bash
        claude plugin install prflow@devflow-marketplace
        ```

        Expected result: Claude Code reports `prflow@devflow-marketplace` as installed.
      </Step>
      <Step title="Confirm the Skills Are Loaded">
        Start a new Claude Code session, then enter `/prflow:`. The completion menu should include skills such as `/prflow:init` and `/prflow:implement`.
      </Step>
    </Steps>

    The interactive `/plugin` manager offers the same marketplace and install actions.
  </Tab>

  <Tab title="Codex CLI">
    <Steps>
      <Step title="Add the Marketplace">
        ```bash
        codex plugin marketplace add The01Geek/prflow
        ```

        Expected result: Codex reports the configured marketplace as `devflow-marketplace`.
      </Step>
      <Step title="Install PRFlow">
        ```bash
        codex plugin add prflow@devflow-marketplace
        ```

        Expected result: Codex reports the plugin ID as `prflow@devflow-marketplace`.
      </Step>
      <Step title="Confirm the Plugin Is Enabled">
        ```bash
        codex plugin list --marketplace devflow-marketplace --json
        ```

        Expected result: the PRFlow entry contains `"installed": true` and `"enabled": true`.
      </Step>
      <Step title="Start a New Session">
        Run `codex`, then enter `/skills` and select `prflow:implement`, or enter `$prflow:implement 123` directly.
      </Step>
    </Steps>

    You can also enter `/plugins` inside Codex CLI to browse the configured marketplace and enable or disable PRFlow.
  </Tab>

  <Tab title="ChatGPT Desktop App">
    First add the marketplace with Codex CLI:

    ```bash
    codex plugin marketplace add The01Geek/prflow
    ```

    Expected result: Codex reports the configured marketplace as `devflow-marketplace`.

    Restart the ChatGPT desktop app, open **Plugins**, select the `devflow-marketplace` source, open **PRFlow** and select **Install**. Start a new Codex chat after installation. In the Codex composer, enter `$prflow:implement 123` to select the skill explicitly.
  </Tab>
</Tabs>

The plugin name and marketplace name are different on purpose. Enter both exactly as shown. See [Commands and Arguments](/docs/runs/local/client-commands) for the invocation syntax on each client.

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

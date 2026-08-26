---
title: "Installation"
description: "Install the PRFlow plugin in Claude Code, GitHub Copilot CLI or Codex CLI."
---

Install the PRFlow plugin to make its skills available in your coding client. Repository initialization is a separate, recommended step.

The plugin is named `prflow`. Its marketplace intentionally keeps the `devflow-marketplace` name. PRFlow has no companion-plugin dependencies.

If you previously installed DevFlow, follow [Migrate From DevFlow](/docs/getting-started/migrate-from-devflow) instead.

## Install in Your Client

Add the marketplace, then install PRFlow:

<Tabs>
  <Tab title="Claude Code">
    ```bash
    claude plugin marketplace add The01Geek/prflow
    claude plugin install prflow@devflow-marketplace
    ```

    The interactive `/plugin` manager provides equivalent marketplace and installation actions. Start a new Claude Code session if the PRFlow skills do not appear immediately.
  </Tab>
  <Tab title="GitHub Copilot CLI">
    ```bash
    copilot plugin marketplace add The01Geek/prflow
    copilot plugin install prflow@devflow-marketplace
    ```

    Start a new GitHub Copilot CLI session after installation.
  </Tab>
  <Tab title="Codex CLI">
    ```bash
    codex plugin marketplace add The01Geek/prflow
    codex plugin add prflow@devflow-marketplace
    ```

    Start a new Codex CLI session after installation.
  </Tab>
</Tabs>

## Continue Setup

Plugin installation does not create repository configuration or install system packages. Before the first run:

1. Confirm the [local requirements](/docs/getting-started/requirements).
2. Run [initialization](/docs/getting-started/initialization) if you want a configurable repository scaffold and detected tools.
3. Follow the [first-run guide](/docs/getting-started/first-run).

See [Updates](/docs/getting-started/updates) when you need a newer plugin release.

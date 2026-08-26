---
title: "Migrate from DevFlow"
description: "Update the renamed PRFlow plugin and migrate existing local and cloud repositories safely."
---

PRFlow is the new name for the DevFlow plugin. After updating the plugin, migrate each existing repository once. The marketplace keeps its original `devflow-marketplace` name, so do not remove or rename it.

If you are installing the plugin for the first time, follow [Installation](/docs/getting-started/installation) instead.

## Claude Code: Quick Migration

Choose one method. Option 1 is shorter and recommended.

### Option 1: Run the Complete Command Sequence

Open Claude Code in a repository that uses DevFlow, then run each command in order:

```text
/plugin marketplace update devflow-marketplace
/plugin install prflow@devflow-marketplace
/reload-plugins
/prflow:init
```

Follow the agent's instructions until initialization is complete. Then review the repository diff before committing it.

### Option 2: Use the Plugin Manager

1. Open Claude Code in a repository that uses DevFlow.
2. Enter `/plugin` and select **Marketplaces**.
3. Select `devflow-marketplace` and update it.
4. Run `/reload-plugins` or restart Claude Code.
5. Run the repository migration and follow the agent's instructions:

   ```text
   /prflow:init
   ```

   The agent may ask questions, request permission to make changes or give you additional setup steps. Continue until the agent confirms initialization is complete.

6. Review the repository diff before committing it.

**Important:** Local `/devflow:*` commands do not remain after the plugin rename. Use `/prflow:*` for every local PRFlow skill.

## Claude Code in VS Code

Claude Code CLI and the VS Code extension share plugin configuration.

1. Open the Claude Code panel in VS Code.
2. Enter `/plugins` to open **Manage plugins**.
3. Select **Marketplaces** and click the refresh icon for `devflow-marketplace`.
4. Restart Claude Code when the extension prompts you.
5. Run `/prflow:init` from the repository you want to migrate. Follow the agent's instructions until initialization is complete.

If PRFlow does not appear, use [option 1](#option-1-run-the-complete-command-sequence) in VS Code's integrated terminal.

## GitHub Copilot CLI

Copilot does not rename the installed plugin automatically, so replace DevFlow with PRFlow.

Run:

```bash
copilot plugin marketplace update devflow-marketplace
copilot plugin uninstall devflow
copilot plugin install prflow@devflow-marketplace
```

Start a new Copilot CLI session in each repository that needs migration and run:

```text
/prflow/init
```

Follow the agent's instructions until initialization is complete.

Copilot CLI separates the plugin and skill names with `/`. Claude Code uses the equivalent `/prflow:init` spelling with `:`.

## GitHub Copilot in VS Code

Agent Plugins in VS Code are a preview feature. The simplest path is to migrate with Copilot CLI first; VS Code discovers CLI-installed plugins automatically.

After completing the [Copilot CLI migration](#github-copilot-cli):

1. Open the VS Code **Extensions** view.
2. Enter `@agentPlugins` in the search field.
3. Find PRFlow under installed Agent Plugins and make sure it is enabled.
4. In Copilot Chat, enter `/` and select PRFlow's `init` skill.
5. Follow the agent's instructions until initialization is complete.

To manage PRFlow entirely in VS Code, add `The01Geek/prflow` to `chat.plugins.marketplaces`, run **Extensions: Check for Extension Updates**, then replace DevFlow with PRFlow in the `@agentPlugins` view.

If PRFlow does not appear, check that your organization allows Agent Plugins and `chat.plugins.enabled` is on. As a fallback, run `/prflow/init` from Copilot CLI in the integrated terminal.

## Codex CLI

Codex CLI does not rename the installed plugin automatically, so replace DevFlow with PRFlow. Update the marketplace and install PRFlow with the same commands the [installation guide](/docs/getting-started/installation) uses:

```bash
codex plugin marketplace add The01Geek/prflow
codex plugin add prflow@devflow-marketplace
```

If a DevFlow-named plugin is still installed, remove it with your Codex CLI version's plugin-management command; see the Codex CLI plugin documentation for the exact syntax.

Start a new Codex CLI session in each repository that needs migration and run the `init` skill (Codex CLI spells it `$prflow:init`). Follow the agent's instructions until initialization is complete.

## What `init` Changes

Run `init` once in every repository configured before the rename, including repositories that use GitHub Actions. It first applies these rename changes together:

- Moves `.devflow/` to `.prflow/` and updates the vendored plugin path.
- Renames supported top-level configuration keys.
- Updates workflow contents that refer to the old state directory, vendored path or configuration keys.
- Updates the repository's local marketplace reference.
- Updates the plugin name and version pin.

PRFlow applies these changes together or not at all. If it reports a blocker, the rename changes nothing. Follow the reported fix instead of moving files or rewriting workflow paths by hand.

After the rename attempt, `init` continues with normal setup and may update other files. Always review the final diff, even if the rename was refused.

After a successful migration:

1. Review `git status` and the complete diff.
2. Confirm that your custom settings were preserved.
3. Commit the repository migration through your normal review process.
4. For cloud repositories, merge the migration before expecting GitHub Actions to use the new paths and configuration keys.

## Optional Product-Name Sweep

After the rename succeeds, `/prflow:init` may offer to update remaining DevFlow product-name references. This step is optional.

**Privacy note:** The sweep reads tracked, untracked and git-ignored files, which may contain secrets or private data. Their contents may enter the model's context. Declining the sweep does not affect the completed migration.

## Cloud Tier Checks

Cloud users should also review:

- Any workflow files PRFlow reports as rewritten.
- Any warning about a retained custom workflow that the PRFlow installer does not maintain.
- The migrated `workflows.prflow` and `workflows.prflow-review` configuration toggles.
- The repository's PRFlow version pin and vendored path, if the committed-vendor installation mode is used.

Existing cloud automation may keep using `/devflow:implement` or `/devflow:review`. Use `/prflow:implement` and `/prflow:review` for new comments.

## Names That Intentionally Stay the Same

Do not perform a repository-wide search-and-replace. These names deliberately retain the DevFlow spelling:

- **Marketplace:** `devflow-marketplace` remains the marketplace identifier. The installed plugin is `prflow@devflow-marketplace`.
- **Environment variables and secrets:** Keep every documented `DEVFLOW_*` name. PRFlow does not read a corresponding `PRFLOW_*` name.
- **Workflow file names:** Existing files such as `devflow.yml` and `devflow-implement.yml` keep their names. Their contents are migrated.
- **Cloud command compatibility:** Supported GitHub comment commands accept both the `/devflow:` and `/prflow:` namespaces.

## Verify the Migration

The migration is complete when:

- The client lists `prflow` as the installed plugin.
- The PRFlow `init` skill is available under the spelling used by your client.
- The repository contains `.prflow/` and no `.devflow/` directory remains.
- The migration diff contains the expected moves and rewrites, with your custom values intact.
- Cloud workflow checks pass after the migration reaches the default branch.

Messages you may see:

- **`ALREADY MIGRATED`:** `.prflow/` exists and `.devflow/` does not. No rename changes were made on this run.
- **`REFUSED`:** The rename changed nothing, but `init` may still perform other setup. Review the final diff and resolve reported blockers before retrying.

## Related Documentation

- [Installation](/docs/getting-started/installation)
- [Cloud setup](/docs/runs/cloud/setup)
- [Claude Code plugin management](https://code.claude.com/docs/en/discover-plugins)
- [GitHub Copilot CLI plugins](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing)
- [Agent Plugins in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-plugins)

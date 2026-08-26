---
title: "Migrate from DevFlow"
description: "Move a repository that was set up before the DevFlow-to-PRFlow rename."
---

PRFlow is the new name for the DevFlow plugin. Update the plugin once, then migrate each existing repository once.

The marketplace keeps its original `devflow-marketplace` name, so do not remove or rename it.

If you are installing for the first time, follow [Installation](/docs/getting-started/installation) instead. Nothing on this page applies to you.

## Update the Plugin

<Steps>
  <Step title="Refresh the Marketplace">
    ```bash
    claude plugin marketplace update devflow-marketplace
    ```
  </Step>
  <Step title="Install PRFlow">
    ```bash
    claude plugin install prflow@devflow-marketplace
    ```
  </Step>
  <Step title="Start a New Session">
    Start a new Claude Code session so the renamed skills load. The interactive `/plugin` manager offers the same marketplace and install actions if you prefer a menu.
  </Step>
</Steps>

<Warning>
  The `/devflow:*` skill names do not survive the rename in your editor. Use `/prflow:*` for every local PRFlow skill from now on.
</Warning>

Claude Code's CLI and its VS Code extension share plugin configuration, so updating in one updates the other. If PRFlow does not appear in VS Code, run the two commands above in VS Code's integrated terminal and restart Claude Code.

## Migrate Each Repository

Run this once in every repository that was configured before the rename, including repositories that use GitHub Actions:

```text
/prflow:init
```

Initialization performs the rename first, before it scaffolds anything. It changes these five things:

- Moves `.devflow/` to `.prflow/` and updates the vendored plugin path.
- Renames the supported top-level configuration keys.
- Updates workflow contents that name the old state directory, vendored path or configuration keys.
- Updates the repository's local marketplace reference.
- Updates the plugin name and version pin.

<Note>
  These changes are applied together or not at all. If any precondition fails, the migration changes nothing and the repository stays byte-for-byte as it was. Follow the reported fix rather than moving files or rewriting workflow paths by hand — a half-migrated repository fails silently instead of loudly.
</Note>

After the rename attempt, initialization continues with its normal setup and may change other files. Review the final diff either way, including when the rename was refused.

## Messages You May See

| **Message** | **What It Means** |
| --- | --- |
| `APPLIED` | Every part of the rename landed together. The diff is large but mechanical. |
| `ALREADY MIGRATED` | The repository is already on the current layout. Nothing changed. |
| `REFUSED` | The rename changed nothing. Initialization may still perform other setup. Resolve the reported blockers, then run it again. |
| `NOTHING TO MIGRATE` | No PRFlow or DevFlow state directory was found. This is a first-time install, not a migration. |
| `could not migrate …` | A specific file the migration does not own, usually a workflow the installer does not ship. Update or remove it by hand. |

## After a Successful Migration

<Steps>
  <Step title="Read the Full Diff">
    Check `git status` and every changed file.
  </Step>
  <Step title="Confirm Your Settings Survived">
    Your configuration values, tuned arrays and custom workflow content should all still be there.
  </Step>
  <Step title="Commit Through Your Normal Process">
    The migration is an ordinary commit and should get an ordinary review.
  </Step>
  <Step title="Merge Before Expecting Cloud Runs to Change">
    GitHub Actions uses the new paths and configuration keys only once the migration reaches your default branch.
  </Step>
</Steps>

## Optional Product-Name Sweep

After the rename succeeds, `/prflow:init` may offer to update remaining `DevFlow` product-name mentions in your own files. This step is optional and is separate from the migration.

<Warning>
  **Privacy note.** The sweep reads tracked, untracked and ignored files, which may hold secrets or private data, and their contents may enter the model's context. Declining the sweep does not affect the migration, which is already complete.
</Warning>

## Cloud Repositories

If your repository uses the cloud tier, also review:

- Any workflow file the migration reports as rewritten.
- Any warning about a retained workflow the PRFlow installer does not maintain.
- The migrated `workflows.prflow` and `workflows.prflow-review` configuration toggles.
- The version pin and vendored path, if you use the committed-vendor installation mode.

Existing automation may still post `/devflow:implement` or `/devflow:review` comments. Those keep working. Use `/prflow:implement` and `/prflow:review` in new comments.

## Names That Intentionally Stay the Same

<Warning>
  Do not run a repository-wide search and replace. Several names keep the DevFlow spelling on purpose, and renaming one of them removes a setting rather than moving it — usually without any error.
</Warning>

| **Name** | **Why It Stays** |
| --- | --- |
| `devflow-marketplace` | The marketplace identifier. The installed plugin is `prflow@devflow-marketplace`. |
| `DEVFLOW_*` environment variables and secrets | PRFlow reads no `PRFLOW_*` equivalent. An unresolvable variable looks exactly like one you never set. |
| Workflow file names such as `devflow.yml` | The file names stay. Their contents are migrated. |
| The `/devflow:` comment namespace | Cloud comment commands accept both `/devflow:` and `/prflow:`. |

## Verify the Migration

The migration is complete when all of the following are true:

- Claude Code lists `prflow` as the installed plugin.
- `/prflow:init` is available in a new session.
- The repository contains `.prflow/` and no `.devflow/` directory remains.
- The diff holds the expected moves and rewrites, with your custom values intact.
- Cloud workflow checks pass after the migration reaches the default branch.

## Related Documentation

- [Installation](/docs/getting-started/installation)
- [Initialization](/docs/getting-started/initialization)
- [Cloud Setup](/docs/runs/cloud/setup)
- [Updates](/docs/getting-started/updates)

---
title: "Updates"
description: "Move an existing PRFlow installation to a newer release, locally and in the cloud."
---

Update the plugin on your machine and the cloud files in your repository. They are two separate paths, and you update them separately.

## Update the Local Plugin

<Steps>
  <Step title="Refresh the Marketplace">
    ```bash
    claude plugin marketplace update devflow-marketplace
    ```
  </Step>
  <Step title="Update the Plugin">
    ```bash
    claude plugin update prflow@devflow-marketplace
    ```

    The interactive `/plugin` manager offers the same actions in a menu.
  </Step>
  <Step title="Start a New Session">
    Start a new Claude Code session if the updated skills do not appear.
  </Step>
  <Step title="Re-Run Initialization">
    In each repository, enter:

    ```text
    /prflow:init
    ```

    This backfills configuration keys the new release added, refreshes `.prflow/config.schema.json` and adds any newly shipped prompt-extension examples. Your existing values and arrays are kept. Review the diff before you commit it.
  </Step>
</Steps>

## Update the Cloud Files

A default cloud installation has two parts that update independently:

- The workflows and composite actions committed in your repository.
- The plugin content fetched at the `prflow_version` ref recorded in `.prflow/config.json`.

Update both together by re-running the installer.

### Preview, Then Apply

Download the installer at the ref you want, read it, then run the copy you read. With the file saved as `devflow-install.sh`:

```bash
DEVFLOW_REF=<newer-ref> bash devflow-install.sh
DEVFLOW_REF=<newer-ref> bash devflow-install.sh --apply
```

<Note>
  **An upgrade is a dry run by default.** The first command writes nothing to your repository. It prints the full plan and a unified diff of every byte the upgrade would change, working against a sandbox copy. Nothing reaches the repository until you re-run with `--apply`.

  A first-time install is different. With no PRFlow files present, the installer applies immediately. Pass `--dry-run` to force a preview there too.
</Note>

The installer executes the file you downloaded, so read it before you run it, and fetch it at a pinned tag or commit rather than a moving branch.

### Your Edits Are Never Overwritten

The installer records the exact bytes it wrote for each file it owns. On the next run it compares:

- **Unchanged since the installer wrote it.** The file is updated in place.
- **You edited it.** The file is preserved exactly as you left it, and the new version is written beside it as `<path>.prflow-new` for you to merge by hand. The installer reports each file it preserved.
- **The installer cannot tell.** A file with no recorded fingerprint, or one it could not read, is preserved the same way and reported with the reason.
- **You deleted it.** The file is recreated.

<Warning>
  A `.prflow-new` file is a real file sitting inside your `.github/` directory, and it is not merged for you. If you leave it there, treat the workflow beside it as still carrying your old version. The installer adds an ignore rule so a later `git add -A` cannot commit the sidecar by accident.
</Warning>

`.prflow/config.json` is never rewritten by this mechanism at all. Only newly added keys are backfilled into it.

### The Version Pin

The installer re-stamps `prflow_version` when the existing value is empty or looks like a commit SHA. A tag or branch name you set deliberately is preserved, so move that value yourself when you want a newer one.

A committed-vendor installation, created with `DEVFLOW_VENDOR=1`, stores the plugin tree in the repository and ignores `prflow_version`. Re-run the installer with the same vendor mode to refresh that tree.

### After the Upgrade

Review and commit the resulting diff. A fresh cloud installation maintains `devflow.yml` and `devflow-implement.yml`. An older repository can still hold a workflow the installer no longer ships. The installer reports such a file by name and never removes it without explicit direction, because no future installer run can refresh it either.

See [Cloud Runs](/docs/runs/cloud/updates) for the complete cloud update path.

## Related Documentation

- [Initialization](/docs/getting-started/initialization)
- [Cloud Installation](/docs/runs/cloud/installation)
- [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow)
- [Release Notes](/release-notes)

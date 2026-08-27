---
title: "Cloud Updates"
description: "Preview, apply and review a PRFlow cloud-tier update without losing your configuration."
---

Move an existing cloud installation to a newer PRFlow release, and keep the settings you changed.

The installer is review-first on an update: it previews by default, and it never silently overwrites a file you edited.

## Update in Three Steps

<Note>
  The examples below pin `v2.34.50`. Replace it with the tag you are moving to, from the [releases page](https://github.com/The01Geek/prflow/releases).
</Note>

<Steps>
  <Step title="Preview the Update">
    Download the newer installer and pass the same new tag as the payload.

    ```bash
    curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.35.10/install.sh -o devflow-install.sh
    # read devflow-install.sh, then:
    DEVFLOW_REF=v2.35.10 bash devflow-install.sh
    ```

    On an existing installation this runs in dry-run mode. It does not intentionally change your repository, though it can create temporary files, and it does execute the script you downloaded. Read that file before you run it.
  </Step>
  <Step title="Apply It">
    ```bash
    DEVFLOW_REF=v2.35.10 bash devflow-install.sh --apply
    ```

    This refreshes the managed workflows, the composite actions and the configuration schema. It backfills newly added configuration keys and preserves the values and arrays you already set.
  </Step>
  <Step title="Review Before Committing">
    ```bash
    git status
    git diff
    ```

    Look for two things: changes under `.github/` that you accept, and any file ending in `.prflow-new`. The next section explains those.
  </Step>
</Steps>

## Resolve Preserved Files

The installer records a digest for each file it manages, in `.prflow/install-manifest.json`. On an update it decides file by file:

| **State of the File** | **What the Installer Does** |
| --- | --- |
| Unchanged since it was installed | Replaces it with the new version. |
| Modified locally | Preserves your version. |
| No verifiable recorded digest | Preserves your version. |

Whenever it preserves your version, it writes the proposed replacement beside it as `<path>.prflow-new`.

<Steps>
  <Step title="Compare Each Sidecar">
    ```bash
    git status --porcelain --ignored | grep '.prflow-new'
    diff .prflow/config.schema.json .prflow/config.schema.json.prflow-new
    ```

    An empty list from the first command means nothing was preserved and there is nothing to merge.
  </Step>
  <Step title="Merge What You Need by Hand">
    Copy the changes you want into the file you maintain.
  </Step>
  <Step title="Delete the Sidecar">
    Remove each `.prflow-new` file once you have merged it. Sidecars are ignored by Git, so a broad `git add -A` will not commit them by accident.
  </Step>
</Steps>

<Warning>
  If Python cannot run, the installer cannot compare managed files or write the provenance manifest. It preserves every existing artifact and writes sidecars instead of risking your work. That is safe but it means nothing was updated in place. Fix Python, then run the same update again.
</Warning>

## Keep the Workflow and the Version Pin Together

In a thin install, `prflow_version` in `.prflow/config.json` decides which plugin the installed workflows fetch at run time. The installer re-stamps an empty or SHA-shaped value to the commit it installed, and preserves a value you set by hand, such as a tag or a branch name.

<Warning>
  Updating only the workflow files, or only `prflow_version`, can leave two halves of one feature out of sync. Run the installer with the new tag and review the resulting pin in the same change.
</Warning>

A current example makes the risk concrete. The skills that read `.prflow/prompt-extensions/` ship inside the plugin, while the permission entries their delivery needs ship in the workflow files. Raising only `prflow_version` leaves that delivery unpermitted, and a refused delivery is not reported as a failure. The run looks normal and quietly applies less of your configuration.

<Note>
  In a vendored install, `prflow_version` is ignored. The committed `.prflow/vendor/prflow/` tree supplies the runtime, so update that tree instead.
</Note>

## After the Update

Run `/prflow:init` locally in the repository. It backfills newly added settings into `.prflow/config.json` without replacing the values you set. Then try one low-stakes command, such as `/prflow:review` on a throwaway pull request, before you rely on the automation again.

If something stops working after an update, see [Cloud-Run Problems](/docs/troubleshooting/cloud-runs) and [Cloud Recovery](/docs/runs/cloud/recovery).

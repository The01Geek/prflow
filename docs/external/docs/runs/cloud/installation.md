---
title: "Cloud Installation"
description: "Install PRFlow's GitHub Actions workflows from a matching version reference."
---

Add PRFlow's optional GitHub Actions tier to a repository. Skip this page if you only run PRFlow locally.

## Before You Start

- Work in a Git repository and run the installer from its root.
- Install `git`.
- Install Python 3.11 or newer. The installer uses Python to compare managed files and record their provenance. Without it, it preserves existing files rather than risk overwriting your work.

## Install From a Release Tag

<Note>
  The examples below pin `v2.34.50`. Replace it with the tag you want to install, from the [releases page](https://github.com/The01Geek/prflow/releases). Pin a tag rather than a branch, so the bytes you read are the bytes that run.
</Note>

<Steps>
  <Step title="Download the Installer">
    ```bash
    curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.34.57/install.sh -o devflow-install.sh
    ```
  </Step>
  <Step title="Read the File Before Running It">
    This script writes workflow files and configuration into your repository. Open `devflow-install.sh` and read it first.
  </Step>
  <Step title="Run It With the Same Tag">
    The URL selects the installer. `DEVFLOW_REF` selects the payload it installs. Use the same value in both places.

    ```bash
    DEVFLOW_REF=v2.34.57 bash devflow-install.sh
    ```

    A first installation applies immediately. Add `--dry-run`, or set `DEVFLOW_DRY_RUN=1`, to preview instead.
  </Step>
  <Step title="Review the Result">
    ```bash
    git status
    git diff
    ```

    You should see new files under `.github/workflows/`, `.github/actions/` and `.prflow/`, listed in the next section. Commit only after the files and permissions match your repository policy.
  </Step>
</Steps>

<Warning>
  A tag is not an immutable byte pin. Use the same verified commit SHA in both the URL and `DEVFLOW_REF` when you need immutability. Leaving `DEVFLOW_REF` unset selects the moving `main` branch.
</Warning>

## What a First Install Creates

- `.github/workflows/devflow.yml` for the comment commands `/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description`.
- `.github/workflows/devflow-implement.yml` for `/prflow:implement`.
- `.github/actions/read-project-config`, `.github/actions/setup-project-env` and `.github/actions/vendor-plugin`.
- `.claude-plugin/marketplace.json`.
- `.prflow/config.json`, `.prflow/config.schema.json`, `.prflow/.gitignore` and prompt-extension examples.
- `.prflow/install-manifest.json`, when Python can record managed-artifact digests.
- `.prflow/lint-manifest.json` and `.prflow/install-state.json`, which let implementation runs provision their lint tools from a verified, digest-bound set before the agent starts.
- Repository ignore rules for installer sidecar files.

<Note>
  A fresh installation does not receive an automatic pull-request review workflow. That tier is withdrawn from new installs. Use a collaborator's `/prflow:review` comment, or add the workflow described in [Request a Review Automatically on Green CI](/docs/runs/cloud/auto-review).
</Note>

## Choose an Install Mode

<Tabs>
  <Tab title="Thin Install (Default)">
    The workflows fetch the plugin at run time into `.prflow/vendor/prflow/`, using the `prflow_version` pin in `.prflow/config.json`. The fetched tree is ignored and is not committed.

    ```bash
    DEVFLOW_REF=v2.34.57 bash devflow-install.sh
    ```

    Choose this for a small install diff and a small update diff.
  </Tab>
  <Tab title="Vendored Install">
    The plugin tree is committed to your repository instead.

    ```bash
    DEVFLOW_VENDOR=1 DEVFLOW_REF=v2.34.57 bash devflow-install.sh
    ```

    Choose this when you want no run-time fetch and want the plugin bytes auditable in your own history. Expect a much larger install and update diff.
  </Tab>
</Tabs>

Continue with [Cloud Setup](/docs/runs/cloud/setup).

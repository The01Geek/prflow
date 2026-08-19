---
title: "Cloud Installation"
description: "Install PRFlow's GitHub Actions workflows from matching version references."
---

Add PRFlow's optional GitHub Actions tier to a repository when your team needs cloud runs. Local plugin users do not need this installer.

## Prerequisites

Use a Git repository and run the installer from its root. Install `git` before starting. A working Python 3.11 or newer is strongly recommended because the installer uses it to compare managed files and record their provenance.

## Install From a Release Tag

1. Download the installer from the current release tag.

   ```bash
   curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.33.20/install.sh -o devflow-install.sh
   ```

2. Read `devflow-install.sh` before running it.
3. Run the downloaded file with the same tag in `DEVFLOW_REF`.

   ```bash
   DEVFLOW_REF=v2.33.20 bash devflow-install.sh
   ```

4. Review the result with `git status` and `git diff`.
5. Commit only after the generated files and permissions match your repository policy.

The URL and `DEVFLOW_REF` select the same release tag. A tag is not an immutable byte pin. Use the same verified commit SHA in both places when immutability is required. Leaving `DEVFLOW_REF` unset selects the moving `main` branch.

## Understand First-Install Behavior

A first installation applies immediately unless you pass `--dry-run` or set `DEVFLOW_DRY_RUN=1`. It creates or updates these public installation surfaces:

- `.github/workflows/devflow.yml` for authorized comment commands.
- `.github/workflows/devflow-implement.yml` for issue implementation.
- `.github/actions/read-project-config`, `.github/actions/setup-project-env` and `.github/actions/vendor-plugin`.
- `.claude-plugin/marketplace.json`.
- `.prflow/config.json`, `.prflow/config.schema.json`, `.prflow/.gitignore` and prompt-extension examples.
- `.prflow/install-manifest.json`, when Python can record managed-artifact digests.
- Repository ignore rules for installer sidecars.

Fresh installations do not receive `devflow-review.yml`, `devflow-runner.yml` or `telemetry-push.yml`. Automatic pull-request-triggered review is withdrawn from new installs. Use a collaborator's `/prflow:review` comment instead.

## Choose an Install Mode

The default is a thin install. The workflows fetch the plugin at runtime into `.prflow/vendor/prflow/` using the pinned `prflow_version`. The fetched tree is ignored and is not committed.

Set `DEVFLOW_VENDOR=1` to commit the plugin tree instead:

```bash
DEVFLOW_VENDOR=1 DEVFLOW_REF=v2.33.20 bash devflow-install.sh
```

Vendored mode avoids a runtime fetch and makes the plugin bytes auditable in the repository. It also creates a much larger install and update diff.

Continue with [Cloud Setup](/docs/runs/cloud/setup).

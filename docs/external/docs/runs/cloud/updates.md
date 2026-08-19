---
title: "Cloud Updates"
description: "Preview, apply and review PRFlow cloud-tier updates with a review-first process."
---

Move an existing cloud installation to a newer PRFlow release without losing repository-specific configuration.

## Preview an Update

Download the newer installer and use the same new release tag for its payload:

```bash
curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.33.26/install.sh -o devflow-install.sh
# review devflow-install.sh, then:
DEVFLOW_REF=v2.33.26 bash devflow-install.sh
```

An existing installation runs in dry-run mode by default. The installer does not intentionally change the target repository in this mode. It can create temporary files, and it still executes the downloaded installer. Inspect and verify the file before running it.

## Apply the Update

After reviewing the preview, apply the same payload:

```bash
DEVFLOW_REF=v2.33.26 bash devflow-install.sh --apply
```

Review `git status` and `git diff` before committing. Re-running the installer refreshes managed workflows, actions and the schema. It backfills newly scaffolded config keys while preserving existing values and arrays.

## Resolve Preserved Files

The installer records managed-artifact digests in `.prflow/install-manifest.json`. On an update:

- An unchanged managed file can be replaced with the new version.
- A locally modified file is preserved.
- A file with no verifiable recorded digest is preserved.
- The proposed replacement is written beside a preserved file as `<path>.prflow-new`.

Compare each sidecar with the file you maintain. Merge the needed changes by hand, then remove the sidecar. Sidecars are ignored so a broad `git add -A` does not commit them accidentally.

If Python cannot run, the installer cannot compare managed files or write the provenance manifest. It preserves existing artifacts and writes sidecars rather than risk overwriting local work. Fix Python, then run the same update again.

## Keep Runtime and Workflow Pins Together

In thin mode, `prflow_version` controls the plugin fetched by the installed workflows. The installer re-stamps an empty or SHA-shaped value to the commit it installed. It preserves a hand-set non-SHA value such as a tag or branch.

Updating only the workflows or only `prflow_version` can leave two halves of a feature out of sync. Prefer running the installer with the new tag and reviewing the resulting pin in the same change.

Prompt-extension delivery is a current example. The skills that consume `.prflow/prompt-extensions/` ship in the plugin, while the permission entries their delivery mechanisms need ship in the workflow files. Bumping only `prflow_version` leaves a mechanism unpermitted, and a refused delivery is not reported as a failure.

In vendored mode, `prflow_version` is ignored because the committed `.prflow/vendor/prflow/` tree supplies the runtime.

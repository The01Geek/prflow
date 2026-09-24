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

    This backfills configuration keys the new release added, refreshes `.prflow/config.schema.json`, and adds any newly shipped prompt-extension `.md.example` files — refreshing an existing example whose content is out of date, while never creating one beside a live `<skill>.md`. Your existing values and arrays are kept. Review the diff before you commit it.
  </Step>
</Steps>

## Update the Cloud Files

A default cloud installation has two parts that update independently:

- The workflows and composite actions committed in your repository.
- The plugin content fetched at the `prflow_version` ref recorded in `.prflow/config.json`.

Update both together by re-running the installer.

### Preview, Then Apply

Download the installer **again at the ref you are moving to** — do not re-run an installer you saved from an earlier release. Each release ships its own `install.sh` logic, so a saved copy applies an older release's install steps to the newer files. Fetch it at the release tag, read it, then run the copy you read:

```bash
curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/<newer-ref>/install.sh -o devflow-install.sh
# read devflow-install.sh, then:
DEVFLOW_REF=<newer-ref> bash devflow-install.sh
DEVFLOW_REF=<newer-ref> bash devflow-install.sh --apply
```

<Note>
  **An upgrade is a dry run by default.** The first command writes nothing to your repository. It prints the full plan and a unified diff of the bytes the upgrade would change, working against a sandbox copy. The diff leaves out the ephemeral `tmp/` scratch folder and the vendored plugin tree under each state directory (`.prflow/` and the older `.devflow/`), and if it meets a file it cannot open — a dangling symlink or a path the platform cannot read — it lists that file as an `UNREADABLE` row and adds a line counting how many could not be compared, instead of stopping. Nothing reaches the repository until you re-run with `--apply`.

  A first-time install is different. With no PRFlow files present, the installer applies immediately. Pass `--dry-run` to force a preview there too.
</Note>

The installer executes the file you downloaded, so read it before you run it, and fetch it at a pinned tag or commit rather than a moving branch.

<Warning>
  **The installer refuses to run a mismatched copy.** Before it writes anything, it compares its own bytes against the `install.sh` of the release it just fetched (line-ending differences are ignored). If they differ, an apply-mode run (`--apply`, or a first-time install) stops before touching your repository and prints the command that downloads the matching installer. A dry run prints the same warning and still shows the plan. Set `DEVFLOW_ALLOW_INSTALLER_DRIFT=1` to install with the mismatched copy anyway. A `curl … | bash` run, or a release that ships no `install.sh`, cannot compare and prints one line noting the self-check was skipped, then continues.
</Warning>

If a stale installer copy (`install.sh`, `devflow-install.sh`, or `prflow-install.sh`) sits committed at your repository root, `/prflow:init` and the installer's scaffolding step also warn about it and print the download command for the current release.

### Your Edits Are Never Overwritten

The installer records the exact bytes it wrote for each file it owns. On the next run it compares:

- **Unchanged since the installer wrote it.** The file is updated in place.
- **You edited it.** The file is preserved exactly as you left it, and the new version is written beside it as `<path>.prflow-new` for you to merge by hand. The installer reports each file it preserved.
- **The installer cannot tell.** A file with no recorded fingerprint, or one it could not read, is preserved the same way and reported with the reason.
- **You deleted it.** The file is recreated.

<Warning>
  A `.prflow-new` file is a real file sitting inside your `.github/` directory, and it is not merged for you. If you leave it there, treat the workflow beside it as still carrying your old version. The installer adds an ignore rule so a later `git add -A` cannot commit the sidecar by accident.

  **After you merge or adopt a sidecar, re-run the installer in apply mode** (`--apply`, or `DEVFLOW_APPLY=1` for a `curl | bash` invocation). Merging changes the file's bytes, so the digest the installer recorded goes stale — and for a file the cloud implement gate depends on (`.github/workflows/devflow-implement.yml`, the `setup-project-env` action, or `.prflow/lint-manifest.json`) a stale `.prflow/install-state.json` marker makes the implement run refuse to start on every run until you re-apply. Only the re-apply rebinds the marker to your merged bytes; the apply that preserved the file already warned you and named each affected sidecar.
</Warning>

`.prflow/config.json` is never rewritten by this mechanism at all. Only newly added keys are backfilled into it.

### The Version Pin

The installer re-stamps `prflow_version` when the existing value is empty, looks like a commit SHA, or matches the pin a previous install or `/prflow:init` recorded in `.prflow/install-manifest.json` (commit that file). Any other tag or branch name you set is preserved, so move that value yourself when you want a newer one. One exception: if your manifest predates that record, a release tag older than the one it last noted is advanced once. The installer never moves its own `vX.Y.Z` pin to an older `vX.Y.Z` release: if it reports that it is not downgrading, restart Claude Code so the updated plugin loads, then run `/prflow:init` again.

A committed-vendor installation, created with `DEVFLOW_VENDOR=1`, stores the plugin tree in the repository and ignores `prflow_version`. So the ignored pin does not drift unnoticed, each cloud run compares the committed copy's version against `prflow_version` and annotates any drift: a `::warning::` when `prflow_version` is an exact three-part semver tag (`v<x.y.z>`) that does not match the committed version, and a `::notice::` for any other `prflow_version` — a branch, a SHA, a partial or non-standard semver ref (`v1.2`, `v2.45.0-rc1`), or empty (or the committed `plugin.json` is unreadable). The check is advisory only and never changes which copy runs. Re-run the installer to refresh that tree: an apply run that finds a git-tracked `.prflow/vendor/prflow/` treats the repository as vendor mode, replaces the committed tree with the fetched release's plugin files, keeps `/vendor/` out of `.prflow/.gitignore`, and logs how to switch to a thin install — so CI stops running the old plugin after an upgrade.

### After the Upgrade

Review and commit the resulting diff. A fresh cloud installation maintains `devflow.yml` and `devflow-implement.yml`. An older repository can still hold a workflow the installer no longer ships. The installer reports such a file by name and never removes it without explicit direction, because no future installer run can refresh it either.

See [Cloud Runs](/docs/runs/cloud/updates) for the complete cloud update path.

## Related Documentation

- [Initialization](/docs/getting-started/initialization)
- [Cloud Installation](/docs/runs/cloud/installation)
- [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow)
- [Release Notes](/release-notes)

# Installation and updates

This page explains how PRFlow is installed, initialized, and updated without losing repository configuration.

## Current behavior

The local install adds the PRFlow marketplace and plugin to Claude Code. `/prflow:init` scaffolds or refreshes `.prflow/config.json` and its schema while preserving existing configuration values. The cloud install uses `install.sh` to place the workflows, actions, configuration, and optional vendored plugin material into the repository.

The installer supports a thin deployment that pins the plugin reference and a vendored deployment that commits the plugin tree. Re-running the installer is designed to backfill new configuration keys without clobbering existing values.

## The withheld automatic-review tier

The automatic pull-request-triggered review tier is withheld from this release (issue #936), so a fresh installation receives none of its workflow files. A repository that installed the tier before it was withheld keeps it; re-running `install.sh` leaves those files in place and reports them. To remove it, re-run with `--remove-withheld-review-tier` (equivalently `DEVFLOW_REMOVE_WITHHELD_REVIEW_TIER=1`), which deletes the three workflow files (`devflow-review.yml`, `devflow-runner.yml`, `telemetry-push.yml`, signature-guarded so a same-named workflow of your own is never deleted) and turns off `workflows["prflow-review"]` in `.prflow/config.json`. Removing the `Devflow Review` context from any branch protection rule that requires it stays a manual step the installer cannot perform.

Independently of that opt-in, every apply run strips the withheld tier's now-dead settings — `prflow_review.require_up_to_date`, `prflow_review.require_ci_green`, and the `prflow_runner` section — from the consumer's `.prflow/config.json` (issue #2071). Those settings are inert in a fresh install whether or not the consumer keeps the tier, so the strip is unconditional; it leaves the file untouched and warns rather than failing when it cannot safely edit the config (no working `python3`, or a malformed/non-object shape).

## Why it works this way

Installation has two distinct responsibilities: making the local command available and materializing the cloud runtime. Keeping configuration preservation and plugin materialization explicit lets a repository review the changes and choose whether to track a moving marketplace or a pinned/vendored ref.

## Boundaries and failure paths

- `/plugin install` does not install every runtime dependency; run the repository preflight and follow its output.
- A config value is preserved unless the documented migration rule explicitly owns that field.
- The cloud workflow must not read privileged configuration from an untrusted pull-request head.
- A vendored deployment must contain the helpers and prompt surfaces required by the installed workflows.

## Source of truth

- `install.sh` — cloud install and update behavior.
- `skills/init/SKILL.md` and `scripts/scaffold-config.sh` — local initialization and configuration scaffolding.
- `.prflow/config.example.json` and `.prflow/config.schema.json` — configuration defaults and schema.
- `.github/actions/vendor-plugin/` — cloud materialization.
- [`docs/internal/install.md`](../install.md) — detailed installer and migration evidence.

## Related topics

- [Cloud runs](cloud-runs.md)
- [Command permissions](command-permissions.md)
- [Documentation](../skills/documentation.md)

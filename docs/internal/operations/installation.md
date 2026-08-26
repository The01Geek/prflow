# Installation and updates

This page explains how PRFlow is installed, initialized, and updated without losing repository configuration.

## Current behavior

The local install adds the PRFlow marketplace and plugin to Claude Code. `/prflow:init` scaffolds or refreshes `.prflow/config.json` and its schema while preserving existing configuration values. The cloud install uses `install.sh` to place the workflows, actions, configuration, and optional vendored plugin material into the repository.

The installer supports a thin deployment that pins the plugin reference and a vendored deployment that commits the plugin tree. Re-running the installer is designed to backfill new configuration keys without clobbering existing values.

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

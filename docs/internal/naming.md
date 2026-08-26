# DevFlow and PRFlow — one product, two spellings

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page explains why the repository uses two names. DevFlow and PRFlow are the same product: PRFlow is the current, consumer-facing name, and DevFlow is the earlier spelling that survives in specific frozen places for compatibility. A reader who meets both names is looking at one system, not two.

## What is current

- The plugin's published name is `prflow` (`.claude-plugin/plugin.json`).
- The live command namespace is `/prflow:<command>`. The `/devflow:<command>` spellings are permanently accepted aliases per `CLAUDE.md`'s rename bullets — treat them as an alias, never as a separate command set.
- The state directory is `.prflow/`, and the vendored plugin path is `.prflow/vendor/prflow/`.
- New runs stamp the `PRFlow` provenance label; selectors still accept the superseded `DevFlow` spelling so no history is dropped.

## What stays DevFlow, deliberately

`lib/rename-map.json` is the single source for what is renamed and what is frozen; this list is a non-authoritative summary of its `frozen` block:

- The `.github/workflows/` filenames (`devflow.yml`, `devflow-implement.yml`, `devflow-runner.yml`, `telemetry-push.yml`).
- The `DEVFLOW_*` environment variables and secrets — no `PRFLOW_*` read side exists, so respelling one silently deletes the setting.
- The `devflow-marketplace` marketplace name, the `devflow_*` internal shell function names, `devflow_module_pin_*`, and the `devflow:<agent>` subagent-override namespace.
- The byte contents of the historical records under `.prflow/learnings/` and `.prflow/logs/`.
- The file `DEVFLOW_SYSTEM_OVERVIEW.md` keeps its name because machine readers pin its exact path.

## The rule for writers

When writing new prose or code, use PRFlow and the `/prflow:` spelling. Never "helpfully" sweep a frozen DevFlow name to PRFlow — read `lib/rename-map.json` first; a frozen name that is renamed stops resolving rather than moving.

## Source of truth

- `lib/rename-map.json` — the rename map and the frozen inventory.
- `CLAUDE.md` — the rename-tier bullets summarizing what moved in each tier.
- `.claude-plugin/plugin.json` — the published plugin name.

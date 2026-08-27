# Cloud runs

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page explains the optional GitHub Actions tier and the trust boundaries that govern it.

## Current behavior

The cloud tier runs supported PRFlow commands in GitHub Actions. Workflows materialize the pinned plugin, provision the configured runtime, resolve the trusted configuration inputs, establish the allowed command surface, and launch the appropriate skill. Writer jobs and read-only review jobs have different permissions and responsibilities.

Cloud setup is optional. The local tier remains the default path and does not require the cloud workflows. A repository can configure runners, secrets, runtime provisioning, model providers, and workflow toggles through `.prflow/config.json` and repository settings.

## Why it works this way

Cloud execution combines automation with repository credentials, so the workflow must separate trusted base configuration from pull-request content and keep read-only and writer jobs distinct. The explicit provisioning and allowlist steps make the runtime reproducible and auditable.

## Boundaries and failure paths

- The cloud tier does not inherit a local working-directory or permission assumption.
- A missing trusted configuration or plugin helper fails closed or degrades only through the documented workflow arm.
- Read-only review jobs must not gain writer credentials merely to run a test or publish a result.
- A third-party provider is optional and must remain within the provider and secret contract.

## Source of truth

- `.github/workflows/devflow.yml`, `.github/workflows/devflow-implement.yml`, and `.github/workflows/devflow-runner.yml` — cloud jobs and trust boundaries.
- `.github/workflows/mintlify-check.yml` — advisory Mintlify validation on public-doc pull requests (not a required check).
- `.github/workflows/telemetry-push.yml` — the telemetry relay retained for already-installed consumers of the withheld automatic-review tier.
- `.github/actions/setup-project-env/` and `.github/actions/vendor-plugin/` — runtime setup and materialization.
- `install.sh` — consumer workflow installation.
- `.prflow/config.schema.json` — cloud configuration keys.
- [`docs/internal/cloud-setup.md`](../cloud-setup.md) — detailed setup and migration evidence.
- [`docs/internal/architecture/execution-model.md`](../architecture/execution-model.md) — shared execution boundary.

## Related topics

- [Workflow triggers](../workflows/triggers.md)
- [Command permissions](command-permissions.md)
- [Installation](installation.md)

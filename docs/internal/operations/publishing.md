# Documentation publishing

This page explains how the public documentation site is sourced, validated, and kept separate from internal documentation.

## Current behavior

Customer-facing documentation is published from `docs/external/` through the repository's Mintlify configuration. The external tree has its own landing page, navigation, styles, images, and public guides. Internal maintainer material under `docs/internal/` is not part of the published site.

Before merge, the publishing configuration and external page structure are validated so a documentation change does not silently produce a missing page or an invalid navigation entry.

## Why it works this way

Internal pages contain implementation evidence and rationale for coding agents. Public pages need a different audience, vocabulary, and security boundary. Keeping the trees sibling and separately published lets internal synchronization remain detailed without making private maintenance material customer-facing.

## Boundaries and failure paths

- Internal docs are not a fallback source for a broken public navigation entry.
- Public documentation changes belong to the external documentation workflow.
- A page that is not in the external navigation can still be tracked but is not discoverable through the intended public path.
- Publishing validation must report missing or malformed configuration rather than treating an absent site build as success.

## Source of truth

- `docs/external/docs.json` — public navigation and site configuration.
- `docs/external/index.mdx` and `docs/external/docs/` — public pages.
- `.github/workflows/ci.yml` and `lib/test/run.sh` — the CI entrypoint and executable documentation/site validation guards.
- [`docs/internal/mintlify-publishing.md`](../mintlify-publishing.md) — internal publishing contract.
- [Documentation workflows](../skills/documentation.md) — internal/external ownership boundary.

## Related topics

- [Internal documentation architecture](../architecture/internal-documentation-architecture.md)
- [Installation](installation.md)

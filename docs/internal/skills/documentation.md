# Documentation workflows

This page explains how internal, external, and release-note documentation are separated and coordinated.

## Current behavior

The repository treats `docs/internal/` and `docs/external/` as sibling documentation products. Internal pages explain the system to maintainers and coding agents. External pages are customer-facing output published through the external documentation site. Release notes and changelog entries are separate deliverables.

The internal synchronization workflow reads the configured internal path and updates only that root. The external synchronization workflow reads the internal material as source context, then writes customer-facing output under the external root. A documentation pass can identify impact on both products, but each product is updated by its own workflow.

## Why it works this way

Internal documentation contains maintainer rationale, implementation boundaries, probes, and historical evidence that should not be shipped as customer guidance. Keeping the roots separate lets agents use the full internal source without leaking private design material into the public site.

## Boundaries and failure paths

- Do not use `docs/external/` as internal source material when the topic is implementation behavior.
- Do not copy internal-only details into public pages without rewriting them for the customer audience.
- A configured documentation path must be resolved before claiming the target was updated.
- A documentation obligation that cannot be verified remains unestablished.

## Source of truth

- `skills/docs-sync-internal/SKILL.md` — internal documentation review and edit contract.
- `skills/docs-sync-external/SKILL.md` — public documentation alignment contract.
- `skills/docs-release-notes/SKILL.md` — release-note and changelog contract.
- `.prflow/config.json` and `scripts/config-get.sh` — documentation path configuration.
- [`docs/internal/index.md`](../index.md) — internal documentation routing.

## Related topics

- [Implement documentation](implement-documentation.md)
- [Publishing](../operations/publishing.md)
- [Internal documentation architecture](../architecture/internal-documentation-architecture.md)

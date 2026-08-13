# Implement documentation

This page explains how the final implement phase determines which documentation must change and how it prevents a completed implementation from leaving its docs behind.

## Current behavior

Phase 4 discovers documentation obligations from the issue, the changed implementation, and the configured documentation paths. It reads the internal documentation location from `.prflow/config.json`, keeps internal and external documentation as separate products, and applies the required documentation workflow before finalization.

The internal documentation path is `docs/internal/` in this repository. Customer-facing material belongs under `docs/external/` and follows the external documentation workflow. A change can require both surfaces, but one surface cannot silently substitute for the other.

## Why it works this way

Documentation is part of the delivery contract because a developer needs to understand the shipped behavior after the implementation run ends. Resolving the path from configuration keeps the workflow portable while the sibling-directory boundary prevents internal maintainer material from leaking into customer-facing output.

## Boundaries and failure paths

- Documentation-needed discovery is not satisfied by a prose claim that docs were updated; the configured path and actual changed files must be checked.
- Internal synchronization operates only within the internal documentation root.
- External documentation is a separate output tree and must be handled by its own workflow.
- A missing or unreadable documentation obligation is reported rather than silently treated as complete.

## Source of truth

- `skills/implement/phases/phase-4-documentation.md` — final documentation phase.
- `skills/docs-sync-internal/SKILL.md` and `skills/docs-sync-external/SKILL.md` — internal and external synchronization contracts.
- `scripts/config-get.sh` — configured documentation path resolution.
- `scripts/extract-doc-needed-paths.sh` and `scripts/read-doc-needed-deliverables.sh` — documentation obligation extraction.
- `.prflow/config.json` and `.prflow/config.schema.json` — repository documentation settings.

## Related topics

- [Documentation](documentation.md)
- [Operations publishing](../operations/publishing.md)
- [Internal documentation architecture](../architecture/internal-documentation-architecture.md)

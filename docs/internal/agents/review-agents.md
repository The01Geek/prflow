# Review agents

This page explains the review-agent roster, role boundaries, and model/effort override behavior.

## Current behavior

The review engine dispatches specialized agents for checklist generation, checklist deduplication, checklist verification, code review, comment analysis, test analysis, silent-failure analysis, and type-design analysis. The exact roster and dispatch conditions live in the executable agent definitions and review phases.

Per-agent overrides are keyed by the configured agent identifier. The review configuration can select a model and effort for an eligible reviewer, while the engine applies the override only at the process-start or dispatch boundary supported by that tier.

## Why it works this way

Specialized roles make the review surface explicit and let the engine ask different agents to look for different failure classes. Keeping the roster and override resolution deterministic prevents a configuration label from silently selecting the wrong agent or applying effort at a point the runtime does not honor.

## Boundaries and failure paths

- An unknown or unsupported agent identifier must not silently become a different reviewer.
- An override that the selected model cannot accept is rejected or degraded according to the configuration contract, not treated as applied.
- The configured roster is not the same as the set dispatched in every phase; gating may omit a reviewer for a particular diff.
- A self-reported effort value is evidence about the agent's report, not an automatic measurement of platform behavior.

## Source of truth

- `agents/*.md` — agent definitions and role prompts.
- `skills/review/SKILL.md` and `skills/review/phases/` — dispatch and phase routing.
- `.prflow/config.json` and `.prflow/config.schema.json` — override shape and accepted configuration.
- [`docs/internal/review-agent-overrides.md`](../review-agent-overrides.md) — detailed resolution and version-skew evidence.
- [`docs/internal/agents-seam-probe.md`](../agents-seam-probe.md) — measured effort-seam evidence.

## Related topics

- [Review](../skills/review.md)
- [Review-and-fix](../skills/review-and-fix.md)
- [Agent runtime](agent-runtime.md)

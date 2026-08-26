# Shadow review

This page explains the independent shadow pass that corroborates a review-and-fix result.

## Current behavior

The shadow pass runs a separate review of the post-fix state. It uses a blinded prompt surface and a separate reviewer context so the shadow reviewer does not simply repeat the primary review's findings. Its coverage result is positively verified; missing coverage, missing blocks, or malformed composition are treated as failures of the shadow evidence rather than clean agreement.

The shadow pass can identify additional findings or corroborate the primary review. A clean shadow result means the shadow pass found no additional actionable issue in its covered surface; it does not prove that the code is defect-free.

## Why it works this way

The primary loop can share assumptions with the agent that made or fixed the change. An independent pass provides a second perspective while preserving an honest limit on what two model reviews can establish.

## Boundaries and failure paths

- A shadow reviewer cannot use the engine's own fan-out path as a substitute for independent coverage.
- A missing or partial shadow roster is not full coverage.
- The shadow pass never changes the working tree.
- Shadow agreement narrows risk but never closes the gap to a human review.

## Source of truth

- `skills/review-and-fix/SKILL.md` and `skills/review-and-fix/references/` — loop and shadow dispatch contracts.
- `.prflow/prompt-extensions/review-and-fix.md` — repository-specific shadow constraints.
- `agents/` — reviewer definitions used by the primary and shadow surfaces.
- [`docs/internal/shadow-review.md`](../shadow-review.md) — detailed mechanism, calibration, and cost evidence.

## Related topics

- [Review-and-fix](../skills/review-and-fix.md)
- [Review agents](review-agents.md)
- [Improvement loops](../improvement-loops/index.md)

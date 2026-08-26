# `/prflow:review`

This page explains the comprehensive review skill and how its engine reaches a verdict.

## Current behavior

`/prflow:review` classifies the diff, builds or reads the verification checklist, dispatches specialized review agents, aggregates their evidence, and emits a terminal verdict. The caller selects one progress surface through an internal binding. Exact `workpad` routes phase boundaries to the existing issue workpad and suppresses the PR progress comment. Every other value retains the standalone behavior: in PR mode, when enabled, the engine maintains a live progress comment whose content comes from the review run.

The review engine is a bundle of the root skill, reference procedures, reviewer agents, scripts, and configured permission profiles. A reviewer result is evidence for a developer's decision; it is not an automatic merge action.

## Why it works this way

Independent checklist generation, specialized review, mechanical corroboration, and final aggregation reduce reliance on one model pass. The engine keeps the verdict contract explicit so downstream workflows can distinguish approval, rejection, incompleteness, and unavailable evidence.

## Boundaries and failure paths

- A missing engine reference, missing verdict marker, or unavailable required evidence is not an approval.
- The progress-surface binding is internal. Public `--issue`, push flags, PR mode, and workpad presence do not select it.
- A no-verdict exit writes a terminal `❌` signal to the selected surface and never creates a different fallback surface.
- Review agents are scoped by the review engine's dispatch rules and configured model/effort overrides.
- Cloud command permissions and prompt grounding are part of the execution contract.
- The shadow review is a separate corroborating pass; it narrows risk but does not prove that no defect remains.

## Source of truth

- `skills/review/SKILL.md` — review command and engine contract.
- `skills/review/phases/` — phase and verdict procedures.
- `agents/` — review-agent definitions.
- `scripts/derive-review-verdict.sh`, `scripts/seed-review-progress.sh`, and `scripts/post-review-verdict.sh` — verdict and progress artifacts.
- [`docs/internal/agents/review-agents.md`](../agents/review-agents.md) and [`docs/internal/agents/shadow-review-overview.md`](../agents/shadow-review-overview.md) — agent behavior and independent shadow coverage.

## Related topics

- [Review-and-fix](review-and-fix.md)
- [Review agents](../agents/review-agents.md)
- [Shadow review](../agents/shadow-review-overview.md)
- [Command permissions](../operations/command-permissions.md)

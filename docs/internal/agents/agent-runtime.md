# Agent runtime and execution artifacts

This page explains how dispatched agents start, what runtime artifacts expose, and which measurements are still limited or unestablished.

## Current behavior

The review and implementation flows dispatch agents from the repository's agent definitions. The runtime produces execution artifacts and, on supported paths, records tool-use and token/cost information independently of an agent's prose. The repository also carries a seam probe for whether a startup agent definition forwards an effort setting into a runtime dispatch.

Execution-file shape and startup-seam evidence are separate observations. A harness-recorded event can establish that a dispatch or artifact was created without establishing that a model setting changed the agent's reasoning behavior.

## Why it works this way

Keeping runtime evidence separate from agent self-report makes it possible to distinguish what the harness observed from what an agent claimed about its own configuration. That distinction prevents a probe from becoming a stronger guarantee than its signal supports.

## Boundaries and failure paths

- An absent execution artifact is not a zero-cost or zero-dispatch result.
- A self-reported effort value is lower-confidence than a harness-recorded dispatch or tool-use event.
- Local and cloud execution artifacts have different retention and shape assumptions.
- A probe result is evidence for the measured seam only; it does not automatically authorize production wiring.

## Source of truth

- `agents/*.md` — dispatchable agent definitions.
- `skills/review/SKILL.md` and `skills/implement/SKILL.md` — dispatch call sites and phase context.
- `.github/workflows/agents-seam-probe.yml` and `.github/workflows/matcher-probe.yml` — probe workflows.
- `scripts/extract-execution-cost.py` and related execution readers — harness artifact handling.
- [`docs/internal/agents-seam-probe.md`](../agents-seam-probe.md) and [`docs/internal/execution-file-shape.md`](../execution-file-shape.md) — detailed evidence.

## Related topics

- [Review agents](review-agents.md)
- [Agent permissions](agent-permissions.md)
- [Improvement loops](../improvement-loops/index.md)

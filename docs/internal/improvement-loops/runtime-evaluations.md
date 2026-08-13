# Runtime evaluations

This page explains the repository's measurements of prompt delivery, runtime context, and review wording.

## Current behavior

The repository contains maintainer and CI-adjacent instruments for create-issue and implement runtime context, skill-body delivery, and review-and-fix wording. These instruments measure specific populations and loader paths; they do not automatically become runtime gates merely because they produce a number.

Each evaluation records its population, measurement method, provenance, and known limits. A figure without a re-derivable comparand is not used as a current invariant.

## Why it works this way

Prompt size, delivered context, and model behavior are related but not identical. Separating those measurements prevents maintainers from optimizing a static byte count while missing a loader truncation, a repeated re-read, or a wording effect in a fresh-context sample.

## Boundaries and failure paths

- An evaluation instrument that is not called by a runtime path is not a runtime gate.
- A self-report is weaker evidence than a harness-recorded event.
- A measurement over one tier, runner, or corpus does not establish behavior for every tier or future corpus.
- An absent transcript or corpus is reported as unavailable rather than measured as zero.

## Source of truth

- `scripts/create-issue-context-eval.py` and `scripts/implement-context-eval.py` — context instruments.
- `scripts/workflow_flight_recorder.py` — transcript and workflow evidence.
- `scripts/prompt-surface-growth.py` — prompt-surface measurement.
- `lib/test/` evaluation guards and fixtures — reproducibility checks.
- `docs/internal/skill-body-load-delivery.md` — skill delivery evidence.
- `docs/internal/implement-context.md` and `docs/internal/review-and-fix-split-wording-study.md` — detailed studies.

## Related topics

- [Skill loading](../skills/skill-loading.md)
- [Efficiency telemetry](efficiency-telemetry.md)
- [Workflow flight recorder](workflow-flight-recorder.md)

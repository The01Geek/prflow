# Calibration and adjudication

This page explains how PRFlow calibrates advisory and invalid findings before making them durable and user-visible.

## Current behavior

The create-issue audit state records the adjudication path, classifies recoverable findings, registers failure modes, and evaluates the shipped mechanism against a defined corpus. Calibration evidence is kept separate from the deterministic state record so maintainers can see which part is machine-enforced and which part still needs judgment.

## Why it works this way

Advisory and invalid findings are easy to misclassify as either blockers or noise. A calibration record makes the intended grading lifecycle explicit, names the observable for each failure mode, and prevents an unmeasured judgment from being presented as a deterministic guarantee.

## Boundaries and failure paths

- An advisory grade is not a clean implementation result.
- An invalid grade must be grounded in the adjudication path rather than a missing signal.
- A calibration corpus result is evidence for the tested population, not a universal proof about future inputs.
- Any unfilled measurement obligation remains visible as unestablished.

## Source of truth

- `scripts/issue-audit-state.py` — state and adjudication data.
- `skills/create-issue/references/step-3-6-audit.md` and `skills/create-issue/references/step-4-present-create.md` — audit lifecycle.
- `skills/create-issue/references/fallback-state-owner-unavailable.md` — degraded state handling.
- [`docs/internal/advisory-adjudication-calibration.md`](../advisory-adjudication-calibration.md) — corpus, failure-mode, and latency evidence.

## Related topics

- [Create issue](../skills/create-issue.md)
- [Runtime evaluations](runtime-evaluations.md)

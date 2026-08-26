# Implement verification

This page explains the verification responsibilities inside `/prflow:implement`, including focused iteration, whole-suite completion evidence, and failure handling.

## Current behavior

The implement flow selects verification according to the active tier and the changed surface. Focused checks support intermediate iteration. A whole-suite result, or the tier-specific equivalent defined by the implementation contract, is required before the run can report completion.

Verification evidence is recorded through the workpad and verification-flight mechanisms. The run distinguishes a passing result from a skipped, denied, incomplete, or otherwise unestablished result. The evidence record carries the command or check identity so a later phase can audit what actually ran.

## Why it works this way

Focused checks make iteration practical, but they cover only the selected surface. Completion gates need a result that covers the full required population for the tier; treating a focused or unavailable result as a whole-suite pass would hide unverified behavior.

## Boundaries and failure paths

- A nonzero failure tally, nonempty skip population, nonzero coordinator status, absent run, or still-running result is not a completion pass.
- A denied command must be retried through its documented permitted form or recorded as unestablished.
- The local and cloud tiers do not necessarily use the same signal to discharge the whole-suite gate.
- Verification-flight state is shared state; stale or unavailable state must fail closed rather than authorize duplicate or missing verification.

## Source of truth

- `skills/implement/phases/phase-1-setup.md`, `skills/implement/phases/phase-2-implement.md`, and `skills/implement/phases/phase-3-review.md` — phase-level verification routing.
- `scripts/verification-flight.py` — single-flight state and records.
- `scripts/check-completion-evidence.py` — completion-evidence validation.
- `lib/test/run.sh`, `lib/test/run-parallel.sh`, and `lib/test/run-module.sh` — suite and focused-check entry points.
- [`docs/internal/implement-skill.md`](../implement-skill.md) — detailed gate and sweep evidence.
- [`docs/internal/operations/verification-policy.md`](../operations/verification-policy.md) and [`docs/internal/claude-md-tiered-suite-rationale.md`](../claude-md-tiered-suite-rationale.md) — tiered suite-running policy and rationale.

## Related topics

- [Implement](implement.md)
- [Implement documentation](implement-documentation.md)
- [Command permissions](../operations/command-permissions.md)
- [Improvement loops](../improvement-loops/index.md)

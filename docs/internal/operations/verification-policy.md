# Tiered verification policy

This page explains which verification signal discharges each completion boundary.

## Current behavior

Focused checks are used for intermediate iteration. They do not discharge a whole-suite completion gate. The local/interactive repository tier reads the required CI result for the pushed commit at its completion boundary. The cloud implement tier establishes the whole-suite result in its own environment or through its complete shard partition. The standalone review and fix loops retain their own verification contracts.

The full suite is coordinated through the parallel runner and its shard/tally helpers. A nonzero failure tally, nonempty skip population, nonzero exit status, absent result, or still-running result is unestablished rather than a clean completion.

## Why it works this way

The local and cloud tiers have different abilities to push and wait for CI. A tier-specific gate prevents a local run from claiming an in-environment result it did not use and prevents a cloud run from outsourcing its own verification to a later merge check.

## Boundaries and failure paths

- A focused result is useful iteration evidence but never a completion substitute.
- An unavailable or denied command must be recorded with the strongest reachable substitute and its residual gap.
- A skipped check is not a clean suite pass.
- The selected tier and command determine which result is authoritative; do not copy the local rule into a consumer skill body.

## Source of truth

- `CLAUDE.md` — repository-wide tier ladder and completion-gate policy.
- `lib/test/run-parallel.sh`, `lib/test/run-shard.sh`, and `lib/test/shard-tally.py` — whole-suite coordination.
- `scripts/verification-flight.py` and `scripts/check-completion-evidence.py` — in-run evidence records.
- `skills/implement/phases/phase-2-implement.md` and `skills/implement/phases/phase-3-review.md` — command-specific verification use.
- [`docs/internal/claude-md-tiered-suite-rationale.md`](../claude-md-tiered-suite-rationale.md) — detailed rationale and evidence.

## Related topics

- [Implement verification](../skills/implement-verification.md)
- [Execution model](../architecture/execution-model.md)
- [Command permissions](command-permissions.md)

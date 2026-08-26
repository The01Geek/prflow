# `/prflow:review-and-fix`

This page explains the correction loop that reviews a change, applies authorized fixes, and verifies the result before handing control back to the developer.

## Current behavior

The loop reuses the review engine, records findings and fix decisions, applies the authorized corrections, and re-runs the relevant review and verification steps until it reaches a terminal outcome or its configured iteration limit. It distinguishes findings that are fixed, deferred, advisory, invalid, or still blocking.

The loop can run as part of `/prflow:implement` or as a standalone command. An implement caller binds the shared engine to the issue-workpad progress surface, while a standalone PR-mode loop keeps the run-keyed PR progress comment. Its prompt extension and reference files define the loop-specific obligations that do not belong in the shared review engine.

## Why it works this way

A review that only reports findings leaves the developer with the cleanup work. The loop makes correction part of the workflow while retaining independent verification and explicit deferral records for findings that cannot be resolved in the current change.

## Boundaries and failure paths

- A clean review result does not authorize skipping the fix-delta or verification checks required by the loop.
- A deferred finding must remain visible with its reason and follow-up path.
- A loop that cannot establish its review or verification evidence must not report a clean terminal outcome.
- The implement-origin signal is caller-held state. The loop must not infer it from `--issue`, `--push-each-iteration`, PR mode, or an existing workpad.
- The terminal review row is ticked at Loop Exit. Re-entry may replay an already-ticked declared row without rewriting the workpad.
- The shadow pass is independent of the fixing agent and does not close the gap by itself.

## Source of truth

- `skills/review-and-fix/SKILL.md` — loop lifecycle and terminal mapping.
- `skills/review-and-fix/references/` — loop-step procedures and deferral handling.
- `.prflow/prompt-extensions/review-and-fix.md` — repository-specific loop constraints.
- `scripts/file-deferrals.py`, `scripts/match-deferrals.py`, and `scripts/workpad.py` — durable finding and state handling.
- [`docs/internal/agents/shadow-review-overview.md`](../agents/shadow-review-overview.md) — independent post-loop coverage.

## Related topics

- [Review](review.md)
- [Review agents](../agents/review-agents.md)
- [Improvement loops](../improvement-loops/index.md)

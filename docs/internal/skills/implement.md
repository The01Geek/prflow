# `/prflow:implement`

This page explains the implement orchestrator's four-phase lifecycle and the boundaries an agent must understand before changing it.

## Current behavior

`/prflow:implement` carries an approved issue through four mandatory phases:

1. Setup hydrates or creates the run state, establishes the branch, and performs the early preconditions.
2. Discover, plan, and implement reads the repository, writes the implementation and tests, and records the workpad state.
3. Review and fix runs the review loop and applies authorized corrections until the loop reaches a terminal outcome.
4. Documentation updates the required internal or external documentation and finalizes the pull request state.

The orchestrator is thin at the root. Phase-specific behavior is loaded from `skills/implement/phases/` and shared helpers under `scripts/` and `lib/`. The workpad is the durable handoff between phases and resumes. During Phase 3, the orchestrator keeps review progress on that issue workpad, even when the shared review engine is operating on the draft pull request.

## Why it works this way

Separating setup, implementation, review, and documentation keeps each phase's gates explicit. The phase boundaries let a resumed run re-establish its state instead of assuming that an earlier conversational turn or a partial tool call completed the work.

## Boundaries and failure paths

- All four phases are required; a successful earlier phase does not authorize skipping a later phase.
- Phase-specific references and guards are part of the executable contract. A change to a phase must update the corresponding reference and tests together.
- A missing, malformed, or stale workpad state is a condition to resolve or report, not a reason to infer progress.
- Verification evidence must be read before a completion claim; a focused result does not automatically discharge a whole-suite gate.

## Source of truth

- `skills/implement/SKILL.md` — root orchestrator and phase contract.
- `skills/implement/phases/` — phase procedures and handoffs.
- `scripts/workpad.py` — durable workpad operations.
- `scripts/phase2-durability-checkpoint.sh` and `scripts/update-branch-checkpoint.sh` — state and branch checkpoints.
- [`docs/internal/implement-skill.md`](../implement-skill.md) — detailed sweep, verification, and finalization evidence.

## Related topics

- [Implement verification](implement-verification.md)
- [Implement documentation](implement-documentation.md)
- [Delivery lifecycle](../workflows/delivery-lifecycle.md)
- [Workpad and resume](../workflows/workpad-and-resume.md)

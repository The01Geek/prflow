# Workpad and resume behavior

This page explains how PRFlow carries state across phases, comments, and resumed runs.

## Current behavior

The implement and review workflows write durable workpad or progress artifacts that identify the run, its phase, its status, its evidence, and its next handoff. Resume logic reads those artifacts and the current repository state before continuing; it does not assume that the last assistant message or a stale comment proves the run completed.

Workpad comments are also part of the trigger boundary. The workflow distinguishes a PRFlow workpad from a user-issued command so the system does not self-trigger from its own progress output.

## Why it works this way

Long-running agent workflows cross context, tool, and process boundaries. A durable state record makes progress inspectable and gives a resumed run a concrete comparand for deciding whether it can continue, must re-run a gate, or must stop.

## Boundaries and failure paths

- A missing, malformed, or mismatched workpad is unestablished state.
- A terminal status without its required evidence is not a completed run.
- A progress comment is not a substitute for the workpad's machine-readable state.
- Concurrent runs are deduped or reconciled according to the command and run identity; a later comment cannot silently rewrite an earlier run's evidence.

## Source of truth

- `scripts/workpad.py` — workpad parsing, writing, ticking, and terminal-state validation.
- `skills/implement/SKILL.md` and `skills/review/SKILL.md` — run-specific artifacts.
- `scripts/update-branch-checkpoint.sh` and `scripts/verification-flight.py` — checkpoint and verification state.
- `.github/workflows/devflow.yml` and `.github/workflows/devflow-implement.yml` — cloud persistence and resume entry points.
- [`docs/internal/workflow-triggers.md`](../workflow-triggers.md) — comment and dedupe behavior.

## Related topics

- [Implement](../skills/implement.md)
- [Review-and-fix](../skills/review-and-fix.md)
- [Delivery lifecycle](delivery-lifecycle.md)

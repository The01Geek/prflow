# PRFlow execution model

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page explains the boundaries that shape how PRFlow runs. Read it before changing tier selection, workpad state, branch transitions, cloud trust, or completion evidence.

## Current behavior

PRFlow has a local or interactive tier and an optional cloud tier. The local tier runs the skills in the developer's coding client. The cloud tier runs supported commands through GitHub Actions and must establish its own checkout, credentials, prompt inputs, allowed tools, and verification evidence.

The workflow state is carried through explicit artifacts rather than an assumption that the main conversation will remember every prior step. The implement path uses a workpad and branch checkpoints to carry progress across phases and resumes. Review paths use their own progress and verdict records.

The execution environment is part of the contract. A command that works in the local tier is not automatically valid in the cloud tier because command permissions, working-directory behavior, available helpers, and trust boundaries differ.

## Why it works this way

Explicit state and checkpoints make a brownfield workflow resumable and auditable. Tier-specific verification prevents a local convenience from being mistaken for evidence that a headless cloud run actually established.

The cloud boundary keeps untrusted pull-request content from silently choosing privileged workflow configuration. Prompt material, helper paths, credentials, and command grants are therefore treated as separate inputs with explicit ownership.

## Boundaries and failure paths

- A missing or stale state artifact must be treated as unestablished rather than inferred from a nearby comment or an earlier run.
- A command denied by the cloud matcher is not evidence that the command failed in the code; the caller must use the documented command shape or stop with the permission gap exposed.
- A verification result from a focused test is not interchangeable with the whole-suite completion evidence required by the active tier.
- A working-directory assumption must be checked against the tier contract before a path-sensitive command is added.

## Source of truth

- `skills/implement/phases/` — implement-phase orchestration, one file per phase surface: `phase-1-setup.md`, `phase-2-implement.md` with the `phase-2-sweeps-contract.md` and `phase-2-sweeps-quality.md` sweep contracts, `phase-3-review.md`, `phase-3-fix-loop.md`, `phase-3-ac-gate.md`, and `phase-4-documentation.md`; `skills/implement/references/` holds the predicate-gated references those phases load.
- `skills/review/SKILL.md` and `skills/review-and-fix/SKILL.md` — review execution and loop behavior.
- `scripts/workpad.py` — workpad state and durable record operations.
- `scripts/update-branch-checkpoint.sh` — branch checkpoint behavior.
- `scripts/verification-flight.py` — verification-flight state and evidence.
- `.github/workflows/devflow.yml` and `.github/workflows/devflow-implement.yml` — cloud execution paths.
- [`docs/internal/operations/working-directory.md`](../operations/working-directory.md) — working-directory contract.
- [`docs/internal/operations/command-permissions.md`](../operations/command-permissions.md) — command grant and shape contract.

## Related topics

- [System overview](system-overview.md)
- [Workpad and resume](../workflows/workpad-and-resume.md)
- [Cloud runs](../operations/cloud-runs.md)
- [Command permissions](../operations/command-permissions.md)
- [Working directory](../operations/working-directory.md)

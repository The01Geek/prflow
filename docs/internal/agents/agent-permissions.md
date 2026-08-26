# Agent permissions

This page explains what dispatched agents may write and how permission evidence is established.

## Current behavior

Agent permissions are determined by the active execution tier, the workflow's allowed tools, and the command shape presented to the harness. The repository carries explicit probes for dispatched-agent writes into the run's scratch area. A successful probe establishes the tested path and tier; it does not widen permissions for unrelated paths or commands.

Cloud workflows use the allowed-tool profile and command-shape contract as a trust boundary. Local sessions may have different classifier behavior, so a command must be checked against the tier in which it will run.

## Why it works this way

Agents need enough write access to record their authorized artifacts, but broad write permissions would make the review and cloud trust boundaries difficult to audit. Narrow, probed permissions make the allowed surface visible and keep denied operations fail-closed.

## Boundaries and failure paths

- A denied command is not a code failure; it is an execution-shape or grant failure that must be surfaced.
- A write probe proves only its exact path, tier, and invocation shape.
- A permission fallback must not be described as a successful write.
- The review tier remains read-only where its workflow contract says it is read-only.

## Source of truth

- `.github/workflows/devflow.yml`, `.github/workflows/devflow-implement.yml`, and `.github/workflows/devflow-runner.yml` — tier-specific workflow permissions.
- `lib/capability-profiles.json` and `lib/generate-capability-profiles.py` — generated command grants.
- `lib/test/extract-command-heads.py` and `lib/test/extract-command-shapes.py` — desk-time grant and shape guards.
- [`docs/internal/subagent-write-probe.observed.md`](../subagent-write-probe.observed.md) — write-probe evidence.
- [`docs/internal/operations/command-permissions.md`](../operations/command-permissions.md) — shared command boundary.

## Related topics

- [Command permissions](../operations/command-permissions.md)
- [Agent runtime](agent-runtime.md)
- [Cloud runs](../operations/cloud-runs.md)

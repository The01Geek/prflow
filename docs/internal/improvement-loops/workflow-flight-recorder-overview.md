# Workflow flight recorder

This page explains the local workflow flight recorder used to measure how workflows are entered and resumed.

## Current behavior

The recorder observes local Claude project transcripts and writes privacy-aware start manifests. A maintainer explicitly imports a session to create a sensitive, byte-verified run bundle. The analyzer selects registered workflow invocations, classifies relationships conservatively, and requires repeated independent occurrences before treating a pattern as recurring.

Analysis is read-only. The recorder does not file issues automatically and does not treat two occurrences from one session as independent evidence.

## Why it works this way

Performance and workflow research needs a durable, reproducible record, but transcript contents can contain sensitive repository material. Separating metadata observation, explicit import, and read-only analysis limits collection while keeping recurrence claims auditable.

## Boundaries and failure paths

- A missing native transcript or unimported session is missing evidence, not a clean no-occurrence result.
- A short alias or embedded invocation is accepted only when the registry and corroborating evidence support it.
- The recorder's analyzer does not infer a code behavior that the source event does not show.
- Active recovery remains a separate gate from passive inventory.

## Source of truth

- `scripts/workflow_flight_recorder.py` — event parsing, inventory, import, and analysis.
- `.claude/settings.json` and hook configuration — local observation wiring.
- `scripts/workflow-flight-recorder-registry.json` — registered workflows.
- [`docs/internal/workflow-flight-recorder.md`](../workflow-flight-recorder.md) — detailed lifecycle, privacy, and validation evidence.

## Related topics

- [Runtime evaluations](runtime-evaluations.md)
- [Workpad and resume](../workflows/workpad-and-resume.md)

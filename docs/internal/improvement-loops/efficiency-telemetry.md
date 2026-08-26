# Efficiency telemetry

This page explains how PRFlow records the effectiveness and cost of review-agent work so maintainers can improve the system without turning telemetry into a workflow gate.

## Current behavior

Review-and-fix records per-iteration workpad data and derives an effectiveness trace for dispatched reviewers. Durable records are persisted through the configured telemetry path, with recovery and synthesis rules for degraded runs. Cost and token evidence can come from harness artifacts rather than agent self-report on supported cloud paths.

Telemetry is configuration-controlled and best effort. A telemetry failure does not abort the review loop, but the missing record remains a measurable gap rather than a zero-valued result.

## Why it works this way

The improvement loop needs evidence about which review steps found unique defects, corroborated findings, or added noise. Keeping that evidence outside the completion gate prevents observability outages from changing product behavior while preserving a trail for maintainers.

## Boundaries and failure paths

- An absent iteration record is not evidence that no reviewer ran.
- Synthesized records carry different provenance from agent-written records.
- A cost floor from a harness artifact does not establish the full effectiveness record.
- The standalone review and auto-review paths have different telemetry availability.

## Source of truth

- `lib/efficiency-trace.sh` — persistence and recovery.
- `skills/review-and-fix/SKILL.md` — per-iteration recording obligations.
- `.prflow/config.schema.json` — telemetry configuration.
- `scripts/build-experiment-records.py` — unified experiment records.
- [`docs/internal/efficiency-trace.md`](../efficiency-trace.md) — detailed schema and evidence.

## Related topics

- [Review-and-fix](../skills/review-and-fix.md)
- [Agent runtime](../agents/agent-runtime.md)
- [Runtime evaluations](runtime-evaluations.md)

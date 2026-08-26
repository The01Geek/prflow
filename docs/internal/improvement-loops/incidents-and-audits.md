# Incidents and audits

This page collects current conclusions from outages, prompt-surface audits, and other maintainer investigations that affect how the system should be changed.

## Current behavior

An incident or audit record is evidence about a specific observed failure, population, or migration. The canonical page states the current consequence and points to the detailed record, source, and guard. Historical timing, probe output, and abandoned alternatives remain in the reference or cutover record.

The internal docs use these records to prevent a future change from reintroducing a known failure, not to turn every historical observation into a permanent system rule.

## Why it works this way

Maintainers need the reason behind an unusual guard or boundary, but an incident report should not become the only place current behavior is documented. Separating the current consequence from the historical evidence makes both retrieval and future validation clearer.

## Boundaries and failure paths

- An incident conclusion applies only to the measured surface and population unless the source establishes a wider rule.
- A probe that was not dispatched or whose signal was inconclusive remains unestablished.
- A historical workaround is not a current recommendation without a current source and guard.

## Source of truth

- `lib/test/` guards and probe fixtures — executable audit checks.
- `.github/workflows/matcher-probe.yml` and other probe workflows — re-runnable evidence sources.
- [`docs/internal/review-skill-load-outage-2026-08.md`](../review-skill-load-outage-2026-08.md) — incident and outage records.
- [`docs/internal/claude-md-extension-audit-consumers.md`](../claude-md-extension-audit-consumers.md), [`docs/internal/claude-md-extension-audit-coupled-sites.md`](../claude-md-extension-audit-coupled-sites.md), and [`docs/internal/claude-md-extension-audit-duplicates.md`](../claude-md-extension-audit-duplicates.md) — prompt-surface audit evidence.
- [`docs/internal/cutovers/`](../cutovers/index.md) — historical implementation records.

## Related topics

- [Prompt surfaces](../architecture/prompt-surfaces.md)
- [Calibration and adjudication](calibration-and-adjudication.md)
- [Command permissions](../operations/command-permissions.md)

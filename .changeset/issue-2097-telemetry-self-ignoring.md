---
bump: patch
type: Fixed
---

- **The verification-flight coordinator's telemetry directories are now self-ignoring.** Both
  telemetry write paths (`scripts/verification-flight.py`'s shared `_emit_telemetry` and the
  `event` subcommand's appender) drop a `.gitignore` containing `*` into the output directory
  before the first telemetry file lands there, so an installed consumer whose scaffolded ignore
  rule covers `.prflow/tmp/` but not the logs dir no longer sees the coordinator dirty — and
  self-invalidate — the tree it just certified. When the guard cannot be written the telemetry write is skipped rather than
  left to dirty the tree; the ledger state directory is deliberately untouched. (#2101)

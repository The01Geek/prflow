---
bump: patch
type: Added
---

- **Add a clock-authored `event` subcommand to `scripts/verification-flight.py` and instrument the Phase 2 and Phase 3 boundaries with it.** The subcommand appends a `{"event": …, "recorded_at": …}` record — timestamped from the helper's own clock — to an append-only JSONL log under `.prflow/logs/phase-events/`, and always exits 0 so a failed write only breadcrumbs and never blocks the run. The implement Phase 2 durability-checkpoint boundaries and the Phase 3 `/simplify`, reviewer-dispatch/return, and shadow-entry boundaries now emit one such event, so a long or expensive implement run's interior timeline is reconstructible from disk. (#1961)

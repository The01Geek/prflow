---
bump: patch
---

Suite scans #141/#142 now exclude `.prflow/learnings/` — the backfilled experiment-record store carries migrated pre-internalization telemetry whose `per_iteration` names old namespaced agent ids verbatim, an append-only historical record the scans must not force a rewrite of.

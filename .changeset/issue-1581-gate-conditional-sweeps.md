---
bump: patch
---

Predicate-gate the eight conditional Phase 2.3 verification sweeps in `/prflow:implement`.

Each of 2.3.0, 2.3.0a, 2.3.0b, 2.3.0c, 2.3.0d, 2.3.1, 2.3.2 and 2.3.7 now keeps its trigger and a
resident predicate statement in its phase file and carries its procedure in its own reference under
`skills/implement/references/`, read only when that sweep's own predicate fires. A run that fires one
or two conditional sweeps no longer holds all eight procedures resident. The six always-firing sweeps
— 2.3.3, 2.3.4, 2.3.4a, 2.3.4b, 2.3.5 and 2.3.6 — are unchanged and stay resident.

Sweep execution is unchanged: the orchestrator runs every sweep itself, and no sweep is dispatched to
a subagent. A reference read that fails is recorded and the run continues to the next sweep rather
than halting Phase 2.

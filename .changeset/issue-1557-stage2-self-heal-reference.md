---
bump: patch
---

`/prflow:implement` Phase 4.1 Stage 2 now reaches its documentation-deliverable self-heal repair
through a gated reference, `skills/implement/references/doc-deliverable-self-heal.md`, read only when
a named deliverable is absent from the run's cumulative diff. The enforcement decision — satisfied
versus absent, and the undeliverable-path `Blocked` terminal — stays resident in the phase file, so a
failed reference load costs the run its repair and never its gate: every named path is still evaluated
and `Documentation` is still not ticked for one that cannot be delivered.

---
bump: patch
type: Changed
---

- **Consolidate Phase 2's workpad writes onto the durability-checkpoint boundaries.** `/prflow:implement` now accrues Phase 2's timing-insensitive workpad mutations — the per-step `--tick-plan` ticks, the mid-Phase-2 `--status Planning`/`--status Implementing` flips, and post-hoc evidence notes such as sweep-result notes — and delivers them as one combined `workpad.py update` per durability-checkpoint boundary, after that boundary's checkpoint push, re-deriving each tick from durable state so a context compaction loses none. Records whose timing a consumer reads (reflections, `--record-*`/`--checkpoint`, terminal `--status`, `--expect-*`-guarded calls, and the ledger/selection notes) keep their immediate call sites. The §2.0 resume arm now re-verifies each un-ticked Plan step against the fresh tree and ticks those already present rather than re-implementing already-committed work. (#2047)

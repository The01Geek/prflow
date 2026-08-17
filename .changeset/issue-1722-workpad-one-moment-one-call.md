---
bump: patch
type: Changed
---

- **Workpad mutations belonging to one moment are now issued as one `workpad.py update`
  call.** The CLI already accepted repeated and combined mutations in a single atomic PATCH,
  but the shipped prose had runs issue them one per sub-step, so a run spent a full
  round-trip of resident context on each extra bookkeeping call. `skills/implement/SKILL.md`
  now carries the rule, naming the sequential/atomic mechanism — one invocation, one PATCH —
  and the cases that stay their own call: mutations *unrelated* to what a structural-abort
  flag writes, whose abort PATCHes nothing and drops them — what one re-send restores may
  still ride along — a second `--reflection-kind`, anything across a durability checkpoint,
  and a staged decision point. Phase 1.3 and the Phase 3 fix-loop exit are folded accordingly. No
  change to `scripts/workpad.py`'s flag surface. (#1732)
- **The review engine's progress-tick rule now forbids only what it needs to.**
  `skills/review/SKILL.md`'s update protocol previously banned batching boundary ticks
  outright; it now forbids ticking a boundary that has not completed, and permits batching
  the ticks of boundaries that have all completed into one sequential call. A call reporting
  a non-`none` remedy is reported as not having recorded those rows rather than read as a
  landed tick; the file's existing best-effort rule still governs the failure direction.
  (#1732)

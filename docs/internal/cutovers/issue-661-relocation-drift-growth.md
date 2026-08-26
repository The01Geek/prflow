---
schema: 1
kind: growth
---
# Issue #661 — relocation drift growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/implement/phases/phase-2-implement.md` — mandatory row, +2893 bytes (baseline 88043 → 90936).

## Justification

Issue #661 hardens the Phase 2.3.0 changed-contract sweep to arm on relocation of a prose
literal, heading, section, or file path — not only a code symbol — the single-branch
relocation-drift class that leaves an orphaned `run.sh` pin / docs reference (issue #530/PR #539
is the archetype). The added bytes are a new operative sweep sub-procedure (recover what moved
from the working-tree diff's deletion hunks or a `git diff --name-status` rename/deletion entry;
enumerate the old-location citations in both forms — whitespace-normalized content quotes and
vacated-path/anchor names; reconcile each against the destination). This is operative decision
logic an implementer must execute at the sweep point on every consuming path (every tier runs
the shared implement engine), so it belongs on the mandatory path, not a conditionally-loaded
reference: an implementer who does not read it will not recognize a prose relocation as a
contract change and will ship the orphaned citation. No prose was removed or relocated (this is
a pure additive growth), so no `cutover`/`trim`/`relocate` coverage is required.

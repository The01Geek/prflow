---
bump: patch
---

Gate the `/prflow:implement` phase-reference reads behind boundary markers (issue #1551, PR #1569). Each file under `skills/implement/phases/` now carries a self-naming `<!-- prflow:implement-ref phase=N file=… start/end -->` marker as its literal first and last line, and `skills/implement/SKILL.md` gains a *Phase-reference boundary contract* — an eight-shape accept-or-reject taxonomy with per-shape `boundary:` stop labels, a plugin-relative path comparison rule, and an out-of-band repair route — referenced from all eight phase-file read sites (the four entry gates, the phase-reference preamble, and the three always-loaded re-anchors). A partial or mis-routed phase read now halts the phase with a named stop label instead of being executed as if correct.

Rows 1–7 of the taxonomy are a required copy of the canonical failure-shape rows in `skills/review/SKILL.md`'s *Reference boundary contract* (with a reciprocal pointer added there); row 8 makes the mis-routed read explicit. `lib/test/run.sh` asserts the on-disk markers for each registered phase stem, driven from the existing `IMPL_PHASE_STEMS` list, and `scripts/devflow-cloud-writer-contract.json` records the post-change SHA-256 of each phase file. The runtime honoring of these markers is agent-executed prompt prose and carries no automated test, by design.

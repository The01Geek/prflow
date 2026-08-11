---
bump: patch
---

Route each `/prflow:implement` phase to an ordered set of phase files rather than a single
file. `phase-2-implement.md` and `phase-3-review.md` each became three siblings small enough
to return whole from a single read, so a phase entry no longer risks a truncated read that the
command's own entry gate is required to stop on. The gate reaches every member in a stated
order, each member clears the boundary contract on its own, and a run holding fewer members
than its phase routes to halts with an attributable stop label instead of proceeding on a
partial phase. The consumer prompt-extension ladder still runs once per phase entry.

The `/prflow:review-and-fix` loop's read-completeness predicate now spans that set, telling a
member it never read apart from one it read whole that carries no sweeps, and reporting the
sweeps unrunnable rather than complete whenever it cannot establish that every member arrived
whole.

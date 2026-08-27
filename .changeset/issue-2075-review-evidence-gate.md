---
bump: patch
type: Added
---

- **Fail the cloud review job when a posted verdict lacks phase-execution evidence.** A new
  job-level gate (`scripts/review-evidence-gate.py`, wired into `.github/workflows/devflow.yml`)
  compares a cloud `/prflow:review` or `/prflow:review-and-fix` run's posted verdict against
  machine-readable evidence that the engine's phases ran — a run-scoped phase log the review
  engine's entry gate now writes a per-phase line to (plus a checklist-generator double-failure
  record and a Phase 0.3.6 fast-path hit record). A run that posted a
  merge-gating verdict whose diff required the checklist phases, but whose attributed run root
  holds no such phase log, turns the job red, flips its progress comment to the failed state,
  leaves a durable comment, and dismisses the unbacked review; the legitimate skip arms stay
  green and an unestablishable evidence state is a warning, neither pass nor failure. The gate
  reuses `scripts/workpad.py`'s own diff classification rather than copying it, and the review
  capability profile is unchanged. (#2077)

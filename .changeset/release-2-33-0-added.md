---
bump: minor
type: Added
---

- **Feature release 2.33.0 — the boundary-marker read contract, a fresh-context implement
  pipeline, and a rewritten `/prflow:create-issue`.** This entry announces the work that
  shipped as tags `v2.32.1` through `v2.32.96` between 2026-08-10 and 2026-08-17; each
  underlying change keeps its own PR-cited entry below, and nothing here is new code. Patch
  bumps are tagged but not announced, so this is the release note for that whole series.
- **Oversized prompt files now fail closed instead of executing a truncated read.** Every
  `/prflow:implement` phase reference, the `/prflow:review` engine's phase files and the
  `/prflow:create-issue` references carry a self-naming boundary marker as their literal
  first and last line, and each read site clears an accept-or-reject taxonomy with named stop
  labels. A partial or mis-routed read halts the phase rather than being run as if correct.
  `lib/test/lint-reference-size.py` additionally turns the suite red when a gated reference or
  skill root grows past the single-read ceiling, so the failure is caught at the desk.
- **A CI-derived completion-evidence record is accepted at the terminal `Complete` gate.** A
  run that established a green required check for the commit it pushed can record that reading
  through `workpad.py --record-completion-evidence-ci` instead of an in-environment suite pass,
  validated offline against a clean tree at the recorded head.
- **`/prflow:init` offers to bootstrap internal documentation.** A consent-gated step reads the
  configured docs locations, classifies each, and — when internal docs are missing — dispatches
  one scoped `/prflow:docs-bootstrap-internal` subagent. It never runs the external bootstrap
  and commits nothing.
- **`/prflow:create-issue` gained a Step 3.5 unrequested-guarantee sweep with a durable record
  that Step 3.6 gates on**, applicability-gated compatibility and rollout sections, and a
  provider-neutral A/B benchmark harness for measuring drafting changes.
- **Every review run's injected grounding block now states the sole-publisher rule**, so a run
  cannot mistake an unmarked review for one the engine posted.

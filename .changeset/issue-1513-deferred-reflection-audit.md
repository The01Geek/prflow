---
bump: patch
type: Fixed
---

- **Detect a `deferred` reflection that no channel filed.** A `--reflection-kind deferred`
  reflection renders as an actionable ("⚠️ Action required") deferral but has no filing path of
  its own, so an implement run could report a finding as handled-by-deferral while nothing
  tracked it. A new `scripts/workpad.py deferred-reflection-audit` backstop, wired into implement
  Phase 4.0.6, surfaces a `deferred` reflection that no tracked deferral record (a
  scope-decision-deferred record or a deferrals-manifest entry) backs, instead of letting the run
  silently pass completion. The reflection-kind routing rule now reserves `deferred` for punts
  already tracked by one of those records; an untracked punt uses `dropped-failed`. (#1787)

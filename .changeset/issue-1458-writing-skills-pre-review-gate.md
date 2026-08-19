---
bump: patch
type: Added
---

- **Enforce the `Writing-skills evidence:` marker as a pre-review gate.** The implement skill's
  Phase 3 now runs a mechanical precondition (§3.2.5) before requesting review: when the branch
  diff touches a prompt-surface trigger-glob path and no `Writing-skills evidence:` marker is
  present on the workpad or PR body, the run stops and names the routing rule as the remedy rather
  than leaving it to a review-time finding. The check is presence-only — a recorded marker
  discharges it whatever its dispositions read — and the review engine's own marker check stays as
  a backstop for a marker that is present but malformed. (#1791)

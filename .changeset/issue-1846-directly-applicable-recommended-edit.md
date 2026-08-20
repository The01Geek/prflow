---
bump: patch
type: Changed
---

- **Tighten the create-issue audit's per-finding recommended-edit bar.** The audit prompt
  template's per-finding bar (and its restatement in the no-finding-cap paragraph) now requires
  each finding's recommended edit to be directly applicable without drafter authorship: the full
  replacement text written out verbatim, and where the remedy is a command the complete runnable
  command, never more than one branch and never a placeholder for a value the auditor established
  during its own verification; a finding whose replacement the auditor cannot supply states that
  inability explicitly in the recommendation slot. This stops audit rounds that attack text the
  drafter authored from an underspecified recommendation. (#1846)

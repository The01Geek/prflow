---
bump: patch
type: Changed
---

- **Let the Stage A retrospective analyst grade an analyzed PR `clean`.** `skills/retrospective/SKILL.md` widens the Stage A verdict vocabulary from `imperfect`/`blocked` to `clean`/`imperfect`/`blocked`: `clean` is the grade when every mechanical signal is spotless (`post_bot_commits` 0, `ci_failures_during_pr` 0, `review_comments_count` 0, `review_reject_outstanding` false, `ci_status_unknown` false, `workpad_final_status` `Complete`) and the analysis finds no shipped defect, and the neither-fits default now resolves to `clean` under those spotless signals and to `imperfect` otherwise. The analysis still runs and records its learnings, so the verdict becomes an outcome measure again instead of a self-report. The cheap gate, `lib/compute-patterns.jq` (analyst-graded `clean` entries still contribute no pattern occurrences), and `lib/clean-entry.jq` are unchanged. (#1865)

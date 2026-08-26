---
bump: patch
type: Fixed
---

- **Close the two review-coverage self-excuse holes at the workpad `Complete` gate (#1990).** `scripts/workpad.py` now refuses a `--record-review-coverage` write whose `dispatch` is `attempted` and whose roster is a measured value unless per-member `--record-roster-member` rows corroborate that the always-on reviewers were dispatched (`[review-coverage-dispatch-uncorroborated]`), and `--review-coverage-disposition` takes a middle `<cause-class>` operand drawn from a closed vocabulary — `environment-denial` (corroborated by a recorded `missing` roster row) or `dispatched-but-lost`. A budget or elective cause is not in that vocabulary, so a run that dropped a review component to save budget, or judged its partial pass adequate, can no longer record a disposition and stops at `Blocked` (`[review-coverage-cause-inadmissible]`).

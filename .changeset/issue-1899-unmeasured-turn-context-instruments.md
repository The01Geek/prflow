---
bump: patch
type: Fixed
---

- **Context instruments report an unmeasured turn as unestablished, not zero.**
  `scripts/create_issue_eval.py` and `scripts/implement-context-eval.py` no longer record a
  real `0` for a turn whose usage object established no residency sub-field (absent, empty,
  all-null, or all-non-finite), which had dragged the reported peak and median below the
  true context used. Such a turn is now tallied in `usage_missing_turns` and excluded from the
  peak population, matching the `scripts/review-context-eval.py` reference. A bare `Infinity`
  token count — which the JSON reader accepts — is treated as an unmeasured turn rather than
  raising `OverflowError` and aborting the whole measurement, and `create_issue_eval.py`'s
  `_median` now refuses an empty population like both siblings. (#1918)

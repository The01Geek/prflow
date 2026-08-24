---
bump: patch
type: Changed
---

- **Single-sourced the shared transcript-walking helpers in the context-cost instruments.**
  Five helpers were duplicated across `scripts/create_issue_eval.py`,
  `scripts/implement-context-eval.py` and `scripts/review-context-eval.py` —
  `_iter_session_files`, `_median`, `_context_tokens`, the per-field usage reader, and the
  `UNESTABLISHED` sentinel. They now have one definition in a new
  `scripts/context_eval_shared.py` that each instrument imports, so a fix lands once instead of
  drifting across three private copies (the drift that produced #1899's defect). (#1926)

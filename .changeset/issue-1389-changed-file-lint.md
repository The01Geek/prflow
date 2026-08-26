---
bump: patch
type: Added
---

- **Changed-file advisory lint via `preflight.py lint-changed` / `lint-full`.** A new
  `scripts/lint_changed.py` layer computes the NUL-safe changed-file population (committed
  merge-base→HEAD, staged, unstaged, and untracked records) with base64url-canonical path
  identity, distinguishes established-nonempty / established-empty / unestablished outcomes,
  and selects per-file lint invocations through the validated lint manifest — a changed
  `lib/test/run.sh` takes its `--extended-analysis=false` special invocation rather than the
  broad shell form. Assembled argv carries a `--` end-of-options separator before the first
  selected path, and one atomic receipt is written per invocation under
  `.prflow/tmp/lint/<run-id>/<attempt>/<op>-<seq>.json`. In-session results are advisory
  feedback, never terminal completion evidence. (#1972)

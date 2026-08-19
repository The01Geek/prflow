---
bump: patch
type: Fixed
---

- **A provider's declared `effort_supported: false` now reaches the in-session per-agent effort
  decision.** The cloud workflows export their already-resolved provider capability to the review
  job's environment as `PRFLOW_EFFORT_SUPPORTED`, and `resolve-review-overrides.py` reads that
  variable by default (an explicit `--effort-supported` flag still wins; an absent or unrecognized
  value falls back to `true`, the Anthropic path). Previously the resolver defaulted to `true` with
  no caller, so a capability-restricted provider's per-agent effort fell back as if the provider
  accepted it. (#1772)

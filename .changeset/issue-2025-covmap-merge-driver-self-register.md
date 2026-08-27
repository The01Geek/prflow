---
bump: patch
type: Fixed
---

- **`update-branch-checkpoint.sh` now self-registers the coverage-map JSON-aware merge driver before its base merge.** When the checkout's `.gitattributes` declares `merge=coverage-map-json`, the checkpoint helper registers the driver in local git config so an adjacent-key `lib/test/modules/coverage-map.json` conflict is unioned rather than routed to `CONFLICT` and Blocking the run. The block is guarded on the declaration and fail-soft: a consumer checkout carrying no such declaration stays silent, and a missing driver or a failed registration warns once to stderr and falls back to git's line-based merge, leaving the helper's outcome token and exit status unchanged. (#2044)

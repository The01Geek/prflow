---
bump: patch
---

Sweep brand-cased `DevFlow` prose to `PRFlow` across the in-scope Batch 5 area (issue #2020): `docs/**`, the tracked root files (`install.sh`, `CLAUDE.md`, `README.md`), `scripts/**`, and `lib/**` excluding `lib/test/**`. Semantically-frozen occurrences (two-spelling explainers, superseded-spelling references, the `DevFlow-Reviewer` App name, provenance-selector literals, test-pinned user-facing strings, and the deliberately-kept `DevFlow Weekly Report` heading) are reclassified into `lib/test/brand-devflow-buckets.json` frozen buckets rather than rewritten. No consumer-facing runtime behaviour changes.

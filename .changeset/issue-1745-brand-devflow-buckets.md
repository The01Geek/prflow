---
bump: patch
---

Add a machine-checkable bucket classification for the brand-cased `DevFlow`
occurrences in the tracked tree, enforced by a fail-closed reconciling lint
(`lib/test/lint-brand-devflow-sweep.py`, data in `lib/test/brand-devflow-buckets.json`).
The lint derives its population via `git ls-files`, classifies an occurrence into a
frozen bucket (append-only record contents, historical CHANGELOG, the superseded
provenance-label value, this feature's own tooling) or a per-file pending-sweep baseline,
and turns the suite RED on an unclassified/new occurrence or a stale assignment in either
direction — so the `devflow` → `PRFlow` rename residue cannot re-accumulate (PR #1973,
issue #1745). The actual prose sweep of the pending renameable population is deferred to a
follow-up that drains the baseline to empty.

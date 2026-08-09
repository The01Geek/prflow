---
bump: patch
---

Unify the `load-prompt-extension.sh` failure contract across all eight shipped ladder call sites: the three docs skills (`docs-sync-internal`, `docs-sync-external`, `docs-release-notes`) now scope the anchor-resolution arm to an exhausted ladder and carry the permission-denial arm that records a refused load as **unestablished** rather than as a repo with no extension.

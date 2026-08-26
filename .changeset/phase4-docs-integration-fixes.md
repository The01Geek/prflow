---
bump: patch
---

Fix three Phase 4.1 documentation-pass integration bugs: honor `docs.external_enabled: false` instead of blocking on the unused `.docs.external` key, align the release-notes/changelog config defaults with the `prflow:docs-release-notes` child skill so an unconfigured repo's release note is staged rather than dropped, and give the docs-sync-internal prompt extension's public-doc-impact handoff a concrete named shape the external step can consume.

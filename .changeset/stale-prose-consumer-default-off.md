---
bump: patch
type: Changed
---

- **Fresh installs now scaffold `prflow_review.stale_prose.enabled` to `false`.** The Phase 0.6
  stale counted-prose lint is tuned to prose idioms common in the PRFlow repository itself, and
  its false-positive carry-forward join only honours payloads from an allowed bot author — so on
  the local and standalone review paths a consumer has no working way to make an adjudication
  stick, and every false positive re-fires each run. The resolver semantics are unchanged: an
  absent key still resolves enabled, and only an explicit `false` disables, so an existing
  consumer's config is untouched by the scaffold backfill. Set the key to `true` to opt back in.
  The `/prflow:implement` Phase 2.3.4 sweep runs the same helper and is not governed by this key.

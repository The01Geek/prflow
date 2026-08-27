---
bump: patch
type: Changed
---

- **`verification-flight.py --help` now answers the claim-schema and exit-code questions.** The
  top-level help epilog states the meaning of each exit code, and `claim --help` states the
  required keys of the claim declaration (rendered from the module's own `_PROFILE_REQUIRED` and
  `_CHECKOUT_REQUIRED` constants so help cannot drift from the validator) plus the attach
  semantics, so a run learns the interface in one help read instead of grepping the source. The
  stale attach-path comment now names `skills/review-and-fix/references/fixing.md`. No tool grant
  is added. (#2036)

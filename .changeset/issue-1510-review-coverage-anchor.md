---
bump: patch
type: Fixed
---

- **Stamp an as-of anchor on the review-coverage record.** The record `scripts/workpad.py` writes
  now carries the reviewed head SHA it was derived from and the UTC time it was written, and a
  carried coverage gap is worded as a statement about the run's own review pass at that anchor
  rather than the pull request's final review state — so a later standalone review that closes the
  gap no longer leaves the workpad record reading stale. Records written before this change,
  without the anchor fields, still parse. (#1951)

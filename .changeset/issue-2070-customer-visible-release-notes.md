---
bump: patch
type: Added
---

- **Changesets can drive the release-notes page at merge time.** A changeset marked
  `customer-visible: true` now has its prose reused verbatim as an entry in
  `docs/external/release-notes.md` under the merge date's heading, written in the same
  `chore: bump version` commit that updates the CHANGELOG. An unmarked changeset is unchanged
  (CHANGELOG only), and this repository's docs pass no longer authors release-notes entries.
  (#2086)

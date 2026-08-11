---
bump: patch
---

- Cap boundary-gated references and skill roots at 61,750 bytes — 95% of the reader's
  25,000-token Read cap, converted at the floor of the measured bytes-per-token densities.
  Above that cap a single read returns a file's `start` marker and no `end` marker, the
  `truncated` shape `/prflow:implement`, `/prflow:review`, `/prflow:review-and-fix` and
  `/prflow:docs-verify` treat as fail-closed, so growth past it previously reached an author
  with no signal at edit time and none in CI. (#1599)
- Derive the covered population by reading each file rather than from a checked-in path
  list, covering both boundary-marker families and every skill root, so a new skill and a
  newly-gated reference need no second edit. (#1599)
- Carry the files already over the ceiling as expiring exemptions in
  `lib/test/reference-size-exemptions.json` rather than a permanent allowance: an exemption
  names one file, is refused for any file outside the record's frozen roster, and turns the
  suite red once its file drops to or under the ceiling. (#1599)

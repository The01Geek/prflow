---
bump: patch
type: Changed
---

- **The reference boundary contract now recovers a gated reference the reader can only deliver in pages.** Each gate's contract gains a paged-read recovery step that reads a partial-view / `offset`-`limit` delivery forward to the whole document and applies the marker checks over the assembled document, so an over-budget-but-intact reference loads instead of being misread as damage. An undeliverable or unclassifiable read still takes each surface's existing fail-closed or degrade outcome, and a genuinely damaged file still fails the gate. (#1784)

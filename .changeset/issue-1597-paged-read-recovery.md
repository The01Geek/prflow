---
bump: patch
type: Changed
---

- **A gated reference the reader can only deliver in pages now loads instead of failing the boundary gate.** Each boundary contract gains a paged-read recovery step: it pages a partial-view / `offset`-`limit` delivery forward to the whole document, then runs the marker checks over the assembled result. A read that cannot be completed, a gap in the page sequence, and a genuinely damaged file each still take the gate's existing fail-closed or degrade outcome. (#1784)

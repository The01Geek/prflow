---
bump: patch
---

`workpad.py patch` no longer duplicates a leading marker kind that only the caller supplied: a composed body carrying one kind twice inside the two-line scan window now keeps its first copy alone, the same first-wins rule already applied to a kind the live comment body also carries.

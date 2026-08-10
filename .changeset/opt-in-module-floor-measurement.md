---
bump: patch
---

Make the batched artifact pass cheap by default: the multi-minute `exact-module-floors`
row is opt-in behind `--with-floors`, its omission is printed rather than inferred from
silence, it is skipped when an earlier row already reported the tree red, and its
measurements now run through a bounded worker pool instead of strictly serially.

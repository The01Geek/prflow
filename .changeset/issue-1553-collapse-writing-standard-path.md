---
bump: patch
type: Changed
---

- **Collapse the writing-standard path and failed-load arm to the always-resident contract.** The four `skills/implement/phases/*.md` files each kept a full copy of the anchored `lib/writing-standard.md` path and its failed-load arm; each now keeps only its per-phase trigger sentence, with the path and arm single-sourced to the implement skill's own Reflection style contract. (#1563)

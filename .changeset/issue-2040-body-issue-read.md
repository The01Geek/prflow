---
bump: patch
type: Added
---

- **`workpad.py body --issue <n>` reads a workpad by issue number in one call.** The new arm resolves the workpad comment through the same marker scan `id`/`status` use and prints its body verbatim, exiting 0 on success, 2 when no workpad exists, and 3 on a read failure — so skill prose no longer spends a `workpad.py id` call plus a hand-carried comment id per read-back. Six two-call read-back sites collapse to the single call. The positional `body <comment-id>` form stays byte-compatible, and its failure now names the operand kind (a comment id) and points at `body --issue <n>`, so passing an issue number no longer fails with a bare, unexplained 404. (#2046)

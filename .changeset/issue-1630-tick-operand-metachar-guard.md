---
bump: patch
type: Fixed
---

- **`/prflow:implement` Phase 1.5 now ticks the Setup workpad row with the ampersand-free operand `workpad` instead of `branch & workpad`.** The old operand carried a shell metacharacter (`&`) that the local auto-mode classifier refused, leaving the Setup `## Progress` row unticked mid-run. `workpad` resolves to exactly one unticked row, matches the current row and any future rename, and carries no shell metacharacter. §1.5 also gains a tier-refusal arm (mirroring §1.4's): a tick invocation refused outright by the tier records a `note`-kind reflection and continues rather than routing to Blocked, distinguished from a tick that ran and exited non-zero. A new assertion in the issue-#1462 test block guards the class — no quoted `--tick-progress` operand under `skills/implement/` may carry a character from `` & ; | $ ` ( ) < > ``. (#1630)

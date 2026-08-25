---
bump: patch
type: Added
---

- **The implement workpad's terminal `--status Complete` gate now refuses a resolved-but-unrecorded prompt-extension row.** A `prompt extension resolved:` row that is unticked and carries no `state not established` note now blocks Complete (naming each offending row), mirroring the existing unticked-acceptance-criteria hard-fail; a ticked row, an unticked row with its note, and a pre-#1462 workpad carrying no such rows all pass, and `Blocked`/`Failed` are unchanged. This restores the unticked-row signal issue #1462 built the rows for. (#1943)

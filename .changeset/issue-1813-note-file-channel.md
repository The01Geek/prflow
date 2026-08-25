---
bump: patch
type: Added
---

- **`workpad.py update` gains a `--note-file <path>` channel.** It reads a `## Progress` note's text verbatim as UTF-8 from a file (or stdin via `-`), mirroring `--reflection-file`, so a note containing backticks, `$`, or double quotes survives byte-identical instead of being mangled by shell interpolation — and the worktree-isolated tier gains a working channel for such notes. An empty, whitespace-only, or unreadable payload is refused with a `--note-file`-named error before any PATCH; it combines with inline `--note`, appending after the inline notes. (#1947)

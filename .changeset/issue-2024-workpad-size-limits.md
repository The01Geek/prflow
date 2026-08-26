---
bump: patch
type: Fixed
---

- **Refuse an oversize workpad write before it reaches the GitHub comment cap.** `scripts/workpad.py`
  now rejects a single caller-supplied Progress note over 2,048 UTF-8 bytes and any update whose
  resulting comment body would exceed GitHub's 65,536-byte comment limit, each with a message naming
  the measured byte count and the limit it broke. A size refusal is not buffered for replay, and
  buffer-replayed and tool-composed rows stay exempt from the per-note budget, so a note that predated
  this change can no longer wedge a workpad into being permanently unwritable. (#2026)

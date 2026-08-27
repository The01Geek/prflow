---
bump: patch
type: Fixed
---

- **`workpad.py update` now accepts `--note-file` and `--reflection-file` more than once**, appending one bullet per payload in command-line order instead of silently keeping only the last path. Each payload is measured on its own against the per-note byte budget, and the stdin form `-` may be used at most once per flag. A call passing either flag once is unchanged. (#2078)

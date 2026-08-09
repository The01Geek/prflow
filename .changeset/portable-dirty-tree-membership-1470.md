---
bump: patch
---

Review engine: the Phase 3.2 dirty-tree backstop's BEFORE-membership test is now pure bash
(an exact-string scan over an indexed array) instead of a GNU-only `grep` NUL-mode invocation,
so the value that decides which paths get restored no longer depends on a non-preflight PATH
tool or a GNU-specific flag. Behaviour is unchanged for spaced, newline and glob-character
pathnames.

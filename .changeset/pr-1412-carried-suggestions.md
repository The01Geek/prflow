---
bump: patch
---

Stale-prose lint: the module-header recognition-tier spec now names `_COUNT_NOUNS` — the constant the widened noun set is actually interpolated from — instead of `_COUNT_RE`, and states it without a transcribed count that rots when a noun is added. Adds discriminating unit coverage for the `§` / `.` / `-` members of `_NUM_LOOKBEHIND`, which were live but unasserted (only the `#` member was covered).

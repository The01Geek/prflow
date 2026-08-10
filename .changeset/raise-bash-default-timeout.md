---
bump: patch
---

Raise `BASH_DEFAULT_TIMEOUT_MS` to 600000 ms on the cloud implement and command tiers. Issue #1179 raised only `BASH_MAX_TIMEOUT_MS`, leaving every Bash call that requests no timeout of its own dying at Claude Code's 120000 ms default and being re-issued — measured at 480 s of pure waste in one 87-minute implement run. The suite now asserts, per claude-code-action step, that the default is present, integer-valued, above the CLI default and strictly below that step's own ceiling.

---
bump: patch
---

A `workpad.py update` that reaches its own exit path now closes with one
machine-readable stderr line, `workpad.py update: outcome=<token> remedy=<token>`,
drawn from a closed set of seven outcome and six remedy tokens. (An argparse
rejection or `--help` terminates before the subcommand runs and emits none.) The
existing prose lines are unchanged and still precede it, so the human-readable
detail — which tick missed, which precondition disagreed, which Status read-back
state occurred — is intact, and exit codes are unchanged.

`/prflow:implement`'s workpad verification prose becomes a token-to-remedy lookup
instead of the narrative stderr shapes an agent had to match. That closes a real
gap: the shape list it replaces routed the exit-4 precondition mismatches into a
catch-all whose remedy was to re-issue the call — the one action that overwrites
live workpad state with the stale state the guard had just refused.

---
bump: patch
type: Fixed
---

- **The implement skill now documents a no-shell fallback ladder for its `workpad.py` call sites, so a run that genuinely cannot execute the program stops at Blocked instead of hand-writing a Complete that skips the finishing checks.** `skills/implement/SKILL.md` states once that `workpad.py` is a Python program needing no shell (only Python 3.11+, an authenticated `gh`, and `scripts/section_parse.py` for the section-reading subcommands), the invocation rungs to try in order (vendored path, portable anchor, and — local/interactive tier only — the `python3` interpreter against each), the rung-failure and re-read-before-retrying-a-write rules, and the Blocked-plus-skip-record outcome that leaves the workpad status untouched. The two workpad-writing subagents each state their pre-resolved handle is the ladder's first rung, and the hand-rolled `gh api` PATCH passage keeps its marker-preservation rule but loses its standing as a way to write the terminal status. (#1673)

---
bump: patch
type: Fixed
---

Fix the ScheduleWakeup `--disallowedTools` probe verdict helper
(`scripts/schedulewakeup-probe-verdict.py`) reading a `ToolSearch` query that names
ScheduleWakeup as a real ScheduleWakeup tool-call attempt. The attempt predicate now keys on
the recorded `tool_use` name rather than substring-matching the input JSON, and a ship verdict
(`DENIED`/`REMOVED`) now requires positive `permission_denials` evidence instead of presumptive
absence — a run with both controls but no attempt and no denial resolves `INCONCLUSIVE`. The
withdrawn `MEASURED AVAILABLE` citation is corrected in `matcher-probe.yml` and the internal
docs, and two new `matcher-probe.yml` probe arms (a re-invocation arm without `--disallowedTools`
and a `CLAUDE_CODE_DISABLE_CRON=1` cloud arm) are added for a post-merge re-measurement (#1937).

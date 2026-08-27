---
bump: patch
type: Added
---

- **`telemetry.enabled` master config key.** Set `telemetry.enabled` to the JSON boolean `false` in `.prflow/config.json` to turn off PRFlow's optional telemetry in one switch: the five default-true telemetry sub-keys (`prflow_review_and_fix.efficiency_telemetry_enabled`, `prflow.execution_diagnostics_enabled`, `prflow.execution_denial_commands_enabled`, `prflow_review.live_progress_comment_enabled`, `create_issue.investigation_record_enabled`) resolve to disabled wherever their own key is absent, and the review-and-fix workpad-copy push to the telemetry branch is skipped. A sub-key set explicitly always wins over the master, and only the JSON boolean `false` disables — every other state (including a string `"false"`, a corrupt config, or a resolver error) leaves telemetry on, matching the existing gates' fail-safe direction. (#2041)

---
bump: patch
type: Added
---

- **`telemetry.enabled` master config key.** Set `telemetry.enabled` to the JSON boolean `false` in `.prflow/config.json` to turn off PRFlow's enrolled optional telemetry in one switch: the five default-true telemetry sub-keys (`prflow_review_and_fix.efficiency_telemetry_enabled`, `prflow.execution_diagnostics_enabled`, `prflow.execution_denial_commands_enabled`, `prflow_review.live_progress_comment_enabled`, `create_issue.investigation_record_enabled`) resolve to disabled wherever their own key does not resolve to a value (absent, JSON null, or an empty string), and the review-and-fix workpad-copy push to the telemetry branch is skipped. `prflow.execution_transcript_artifact_enabled` is not enrolled — it already defaults to `false`. A sub-key set to a value that resolves always wins over the master for those five resolver reads, while the telemetry-branch push reads the master alone. Only the JSON boolean `false` disables — every other state (including a string `"false"`, a corrupt config, or a resolver error) leaves telemetry on, matching the existing gates' fail-safe direction. (#2041)

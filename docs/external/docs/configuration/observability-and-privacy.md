---
title: "Observability and Privacy"
description: "Configure diagnostics, transcript artifacts, denied-command records and telemetry storage."
---

Balance useful cloud-run diagnostics against the sensitivity of prompts, repository content and command text.

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and privacy note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow.execution_diagnostics_enabled` | Boolean | `true` | Cloud model jobs. Prints summary and denial detail to logs and the job summary. It uploads no artifact and does not change pass or fail. | `"execution_diagnostics_enabled": true` |
| `prflow.execution_transcript_artifact_enabled` | Boolean | Runtime and scaffold: `false` | Cloud model jobs. When true, uploads a scrubbed transcript artifact with seven-day retention. Treat it as sensitive. | `"execution_transcript_artifact_enabled": false` |
| `prflow.execution_denial_commands_enabled` | Boolean | `true` | Cloud model jobs. Controls durable scrubbed command text only. Denial count and tool names remain available when a record can be built. | `"execution_denial_commands_enabled": false` |
| `prflow_review_and_fix.efficiency_telemetry_enabled` | Boolean | `true` | Local and cloud review-and-fix. False also prevents denied-command records from being persisted on the telemetry branch. | `"efficiency_telemetry_enabled": true` |
| `telemetry.branch` | String branch name | `prflow-telemetry` | Writable runs persist observability records to this long-lived orphan branch. Exclude it from broad push-triggered CI. | `"branch": "prflow-telemetry"` |

## Know What Persists

- Execution diagnostics are enabled by default. They remain in Actions logs and the job summary.
- Full transcript artifacts are disabled by default.
- Scrubbed denied-command text is enabled by default and can persist on the telemetry branch.
- Denial count and tool identifiers are not controlled by the command-text toggle.
- Effectiveness records are enabled by default.

The transcript and command scrubber is an incomplete blocklist. It covers common GitHub tokens, Anthropic keys and Bearer or basic Authorization headers, whose scheme keyword is matched whatever its casing. An Authorization value shorter than four characters is left alone, so a literal command such as `sed 's/AUTHORIZATION: basic //'` is not mistaken for a credential. Other credential shapes can remain. A scrub failure prevents the affected text from being uploaded or persisted.

**Warning:** A successful scrub does not prove that output is secret-free.

- Transcript artifacts and denied-command records use the scrubber.
- Actions diagnostics can still contain truncated tool input. Treat those logs as sensitive.

Use repository access controls and artifact retention as part of the privacy decision. Set both text-bearing options to false when even scrubbed prompt or command content is unacceptable:

```json
{
  "prflow": {
    "execution_diagnostics_enabled": true,
    "execution_transcript_artifact_enabled": false,
    "execution_denial_commands_enabled": false
  },
  "prflow_review_and_fix": {
    "efficiency_telemetry_enabled": true
  },
  "telemetry": {
    "branch": "prflow-telemetry"
  }
}
```

Disabling denied-command text does not disable ordinary log diagnostics. Disable `execution_diagnostics_enabled` separately for quieter logs.

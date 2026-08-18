---
title: "Review Settings"
description: "Configure review verdicts, fix routing, progress and legacy automatic-review controls."
---

Tune the shared review engine and the local review-and-fix loop to match your repository's risk and verification needs.

## Review Engine

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review.verdict_severity_threshold` | `critical`, `important` or `suggestion` | `critical` | Standalone review and review-and-fix review pass. Lowering the threshold makes more findings reject. | `"verdict_severity_threshold": "critical"` |
| `prflow_review.live_progress_comment_enabled` | Boolean | `true` | Pull-request review. When true, each run maintains its own progress comment. Comment writes are best effort. | `"live_progress_comment_enabled": true` |
| `prflow_review.stale_prose.enabled` | Boolean | Fallback `true`; scaffold: `false`. Anything except explicit false enables | Shared review engine. Fresh installs scaffold this off, because the check is tuned to prose idioms that are common in the PRFlow repository itself and its false-positive suppression channel only works for bot-authored review comments. Set it to true to enable the automatic check for prose that contains stale numeric claims. | `"enabled": false` |
| `prflow_review.stale_prose.severity` | `critical`, `important` or `suggestion` | `important` | Shared review engine. The chosen severity participates in verdict computation. | `"severity": "important"` |

## Review and Fix

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review_and_fix.fix_severity_threshold` | `critical`, `important` or `suggestion` | `important` | Local review-and-fix and implementation's inline fix loop. Findings severe enough to cause a rejection remain eligible for correction at every value. | `"fix_severity_threshold": "important"` |
| `prflow_review_and_fix.max_iterations` | Integer one or greater | `5`; values below one clamp to one | Review-and-fix. Higher values can increase cost. | `"max_iterations": 5` |
| `prflow_review_and_fix.efficiency_telemetry_enabled` | Boolean | `true` | Review-and-fix. False disables the effectiveness record and prevents denied-command records from being persisted on the telemetry branch. | `"efficiency_telemetry_enabled": true` |
| `prflow_review_and_fix.efficiency_cut_candidate_min_dispatch` | Integer one or greater | `3` | Cross-run analysis. It is recorded for later analysis and does not cut an agent during the current run. | `"efficiency_cut_candidate_min_dispatch": 3` |
| `receiving_review.fix_severity_threshold` | `critical`, `important` or `suggestion` | `critical` | Direct use of the receiving-code-review skill only. The review-and-fix loop uses its own threshold. | `"fix_severity_threshold": "critical"` |

## Retained Legacy Automatic-Review Settings

Fresh installs do not include automatic pull-request-triggered review. These settings remain only so repositories that installed the withdrawn tier continue to validate. Keep them at their scaffolded values unless you are maintaining such an installation and accept its documented limitations.

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Legacy tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review.require_up_to_date` | Boolean | `true` | Withheld automatic-review caller only. No effect in fresh installs. | `"require_up_to_date": true` |
| `prflow_review.require_ci_green` | Boolean | `true` | Withheld automatic-review caller only. No effect in fresh installs. | `"require_ci_green": true` |
| `prflow_review.stall_backstop.enabled` | Boolean | `true` | Withheld automatic-review path and limited manual failure recovery. A resume also needs an App and allowed bot identity. | `"enabled": true` |
| `prflow_review.stall_backstop.max_resume_attempts` | Integer zero or greater | `2` | Retained review backstop. `0` disables resume while retaining detection. | `"max_resume_attempts": 2` |
| `prflow_runner.effort` | `low`, `medium`, `high`, `xhigh` or `max` | Scaffold: `low` | Withheld reusable runner. No effect in fresh installs. | `"effort": "low"` |
| `prflow_runner.provision_env` | Boolean | Runtime false; scaffold: `false` | Withheld runner. Enabling runs pull-request code with provisioned tools under a privileged workflow. | `"provision_env": false` |

Provider and allowed-tool settings for `prflow_runner` are listed in [Providers](/docs/configuration/providers) and [Tool Permissions](/docs/configuration/tool-permissions), with the same legacy label.

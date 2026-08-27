---
title: "Implementation Settings"
description: "Configure implementation output, checkpoints, stalls and verification reuse."
---

Tune `/prflow:implement` behavior and coordinate verification when multiple agents share the same checkout.

## Implementation Settings

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_implement.effort` | `low`, `medium`, `high`, `xhigh` or `max` | Scaffold: `low`; absent runtime fallback: `high` | Local and cloud implementation. Higher values can increase cost and latency. | `"effort": "low"` |
| `prflow_implement.implement_pr_state` | `ready_for_review` or `draft` | `ready_for_review`; invalid values also publish | Implementation. `draft` leaves the completed pull request for a human to publish. PRFlow never merges it. | `"implement_pr_state": "draft"` |
| `prflow_implement.update_branch_checkpoints` | Boolean | `true`; only an explicit false disables | Implementation and pushed fix-loop checkpoints. Merges the configured base into the feature branch at defined boundaries. | `"update_branch_checkpoints": true` |
| `prflow.publish_model_effort` | Boolean | `true`; only an explicit JSON false disables | Governs the provenance line for every command that emits one — the `/prflow:implement` draft pull request and the `/prflow:create-issue` issue alike: when false the line names the plugin version alone, suppressing the model and effort clause. The version is always published. Only the JSON boolean `false` disables it; the string `"false"` and the array `[false]` do not. Supersedes the former per-command key in the `prflow_implement` section, which is now read by nothing. | `"publish_model_effort": true` |
| `prflow_implement.stall_backstop.enabled` | Boolean | `true`; unrecognized values enable | Cloud implementation. When false, an interim run can end without an automatic resume or loud failure. | `"enabled": true` |
| `prflow_implement.stall_backstop.max_resume_attempts` | Integer zero or greater | `2`; invalid values use `2` | Cloud implementation. `0` detects and fails without resuming. Each resume can incur another run. | `"max_resume_attempts": 2` |
| `prflow.attribute_commits_to_triggerer` | Boolean | Runtime and scaffold: `false` | Cloud writer jobs. Applies only to verified human users and changes Git metadata, not the push credential. Trigger-time and post-merge-only. | `"attribute_commits_to_triggerer": true` |
| `verification_flight.enabled` | Boolean | `true` | Local implementation and inline review-and-fix. Disabling reuse does not turn a missing or stale record into a pass. | `"enabled": true` |

<Note>
  `prflow_implement.effort` has no default in the schema, so the scaffolded value and the fallback differ. `/prflow:init` writes `"effort": "low"`. When the key is absent, the shipped implementation workflow resolves it to `high`, the same fallback `prflow.effort` uses. Removing the key raises effort rather than lowering it.
</Note>

<Warning>
  `prflow.attribute_commits_to_triggerer` records the person who triggered the run as the author of the commits PRFlow pushes. It changes Git metadata only. The push still uses the workflow's own credential, so this setting does not grant or transfer any access. Enable it knowing that a commit will carry a name that did not write the code.
</Warning>

<Accordion title="Settings you rarely need to change">
  | **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and note** | **Example** |
  | --- | --- | --- | --- | --- |
  | `verification_flight.lease_seconds` | Integer zero or greater | `900` | Reserved for future use. Changing this setting has no effect in the current release. | `"lease_seconds": 900` |
  | `verification_flight.wait_timeout_seconds` | Integer zero or greater | Scaffold: `600` | Reserved for future use. Changing this setting has no effect in the current release. | `"wait_timeout_seconds": 600` |
</Accordion>

Provider and model overrides for implementation are documented in [Model Providers](/docs/configuration/providers). Implementation tool grants are documented in [Tool Permissions](/docs/configuration/tool-permissions). To give implementation runs a repository-specific rule, such as the verification command they must use, write a [prompt extension](/docs/configuration/prompt-extensions).

## Valid Implementation Example

```json
{
  "prflow": {
    "attribute_commits_to_triggerer": false,
    "publish_model_effort": true
  },
  "prflow_implement": {
    "effort": "low",
    "implement_pr_state": "ready_for_review",
    "update_branch_checkpoints": true,
    "stall_backstop": {
      "enabled": true,
      "max_resume_attempts": 2
    }
  },
  "verification_flight": {
    "enabled": true,
    "lease_seconds": 900,
    "wait_timeout_seconds": 600
  }
}
```

Expected result: an implementation run works at low effort, keeps the feature branch current with the base branch at checkpoints, publishes the finished pull request for review and resumes at most twice if a cloud run stalls.

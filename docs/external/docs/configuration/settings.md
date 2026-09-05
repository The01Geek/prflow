---
title: "All Settings A to Z"
description: "Look up any PRFlow setting name and jump to the page that documents it."
---

Find any `.prflow/config.json` setting by name. Every setting PRFlow reads is listed here once, in alphabetical order, with the page that gives its type, accepted values, default and security note.

Search this page for the key you have. If you are choosing settings rather than looking one up, start at [Configuration](/docs/configuration/index).

## How to Read a Setting Name

A name such as `prflow_implement.stall_backstop.max_resume_attempts` is a path through the JSON file. Each dot is one level deeper. Written out, that setting is:

```json
{
  "prflow_implement": {
    "stall_backstop": {
      "max_resume_attempts": 2
    }
  }
}
```

Expected result: a stalled cloud implementation run is resumed at most twice. Every other setting keeps its default, because a key you leave out is a key PRFlow falls back on.

A name containing `<name>`, such as `providers.<name>.auth`, means you choose that part yourself. It is the name you give your own provider entry.

## Index

| Setting | Documented on | What it controls |
| --- | --- | --- |
| `$schema` | [Core Settings](/docs/configuration/core-settings) | Editor validation only. Ignored at runtime. |
| `base_branch` | [Core Settings](/docs/configuration/core-settings) | The branch reviews and implementation work from. |
| `claude_model` | [Core Settings](/docs/configuration/core-settings) | The model every section uses unless it overrides it. |
| `create_issue.investigation_record_enabled` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Whether the investigation record is posted with a new issue. |
| `deferred.labels` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Labels applied to follow-up issues for deferred work. |
| `docs.changelog_file` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | The changelog the release-note pass reconciles against. |
| `docs.external` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Where public documentation lives. |
| `docs.external_enabled` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Whether the combined docs pass covers public docs. |
| `docs.internal` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Where developer documentation lives. |
| `docs.internal_enabled` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Whether the combined docs pass covers developer docs. |
| `docs.labels` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Labels applied after the documentation pass. |
| `docs.release_notes_file` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | The customer-facing release-notes file. |
| `prflow.allowed_bots` | [Core Settings](/docs/configuration/core-settings) | Which automation identities may trigger a cloud run. |
| `prflow.allowed_tools` | [Tool Permissions](/docs/configuration/tool-permissions) | Extra commands granted to the general cloud command path. |
| `prflow.allowed_users` | [Core Settings](/docs/configuration/core-settings) | Which people may trigger a cloud run. |
| `prflow.attribute_commits_to_triggerer` | [Implementation](/docs/configuration/implementation) | Whose name appears as the author of cloud commits. |
| `prflow.claude_model` | [Model Providers](/docs/configuration/providers) | Model override for the general cloud command path. |
| `prflow.effort` | [Core Settings](/docs/configuration/core-settings) | Reasoning effort for the general cloud command path. |
| `prflow.execution_denial_commands_enabled` | [Observability and Privacy](/docs/configuration/observability-and-privacy) | Whether denied command text is recorded. |
| `prflow.execution_diagnostics_enabled` | [Observability and Privacy](/docs/configuration/observability-and-privacy) | Whether run diagnostics are printed to the logs. |
| `prflow.execution_transcript_artifact_enabled` | [Observability and Privacy](/docs/configuration/observability-and-privacy) | Whether a scrubbed transcript is uploaded as an artifact. |
| `prflow.provider` | [Model Providers](/docs/configuration/providers) | Provider route for the general cloud command path. |
| `prflow.publish_model_effort` | [Implementation](/docs/configuration/implementation) | Whether the provenance line names the model and effort. |
| `prflow.workpad_marker` | [Core Settings](/docs/configuration/core-settings) | The marker that identifies a workpad comment. |
| `prflow_implement.allowed_tools` | [Tool Permissions](/docs/configuration/tool-permissions) | Extra commands granted to implementation runs. |
| `prflow_implement.claude_model` | [Model Providers](/docs/configuration/providers) | Model override for implementation runs. |
| `prflow_implement.effort` | [Implementation](/docs/configuration/implementation) | Reasoning effort for implementation runs. |
| `prflow_implement.implement_pr_state` | [Implementation](/docs/configuration/implementation) | Whether the finished pull request is published or left as a draft. |
| `prflow_implement.provider` | [Model Providers](/docs/configuration/providers) | Provider route for implementation runs. |
| `prflow_implement.stall_backstop.enabled` | [Implementation](/docs/configuration/implementation) | Whether a stalled cloud run is detected after the agent step. |
| `prflow_implement.stall_backstop.max_resume_attempts` | [Implementation](/docs/configuration/implementation) | How many times a stalled run may be resumed. |
| `prflow_implement.update_branch_checkpoints` | [Implementation](/docs/configuration/implementation) | Whether the base branch is merged in at checkpoints. |
| `prflow_retrospective.audit_bundle_cap` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How many pull request records inform one pattern. |
| `prflow_retrospective.audit_model` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | The model used for the audit stage. |
| `prflow_retrospective.cooldown_days` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How long before a recent pattern may be filed again. |
| `prflow_retrospective.diff_byte_cap` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | The size above which a diff is left out of analysis. |
| `prflow_retrospective.enabled` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Declares whether the weekly loop is in use. |
| `prflow_retrospective.implementation_branch_prefix` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | A branch prefix that helps select pull requests. |
| `prflow_retrospective.max_issues_per_run` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How many issues one retrospective run may file. |
| `prflow_retrospective.max_open_issues` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How many retrospective issues may be open at once. |
| `prflow_retrospective.max_open_per_category` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How many may be open in one category. |
| `prflow_retrospective.max_prs_per_run` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | A soft cap on scanned pull requests. |
| `prflow_retrospective.min_occurrences` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | How often a pattern must recur before it is filed. |
| `prflow_retrospective.retrospective_model` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | The model used for the analysis stage. |
| `prflow_retrospective.watched_authors` | [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives) | Whose pull requests the weekly loop scans. |
| `prflow_review.agent_overrides` | [Review Agents](/docs/configuration/review-agents) | Per-agent `model`, `effort` and `iterations` overrides, plus a `default` entry. |
| `prflow_review.live_progress_comment_enabled` | [Review](/docs/configuration/review) | Whether a run keeps a live progress comment. |
| `prflow_review.require_ci_green` | [Review](/docs/configuration/review) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_review.require_up_to_date` | [Review](/docs/configuration/review) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_review.stale_prose.enabled` | [Review](/docs/configuration/review) | Whether the stale-prose check runs. |
| `prflow_review.stale_prose.severity` | [Review](/docs/configuration/review) | The severity a stale-prose finding carries. |
| `prflow_review.stall_backstop.enabled` | [Review](/docs/configuration/review) | Whether the live no-verdict stall backstop is enabled (retained; not part of the removed tier). |
| `prflow_review.stall_backstop.max_resume_attempts` | [Review](/docs/configuration/review) | How many times a stalled review may be resumed. |
| `prflow_review.verdict_severity_threshold` | [Review](/docs/configuration/review) | The severity at which findings turn the verdict into a rejection. |
| `prflow_review_and_fix.efficiency_cut_candidate_min_dispatch` | [Review](/docs/configuration/review) | A threshold recorded for later cross-run analysis. |
| `prflow_review_and_fix.efficiency_telemetry_enabled` | [Review](/docs/configuration/review) and [Observability and Privacy](/docs/configuration/observability-and-privacy) | Whether the effectiveness record is written. |
| `prflow_review_and_fix.fix_severity_threshold` | [Review](/docs/configuration/review) | The severity at which a finding is eligible for a fix. |
| `prflow_review_and_fix.max_iterations` | [Review](/docs/configuration/review) | How many fix-loop iterations may run. |
| `prflow_runner.allowed_tools` | [Tool Permissions](/docs/configuration/tool-permissions) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_runner.claude_model` | [Model Providers](/docs/configuration/providers) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_runner.effort` | [Review](/docs/configuration/review) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_runner.provider` | [Model Providers](/docs/configuration/providers) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_runner.provision_env` | [Review](/docs/configuration/review) | Removed (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. |
| `prflow_version` | [Core Settings](/docs/configuration/core-settings) | The plugin version a thin cloud install fetches. |
| `providers.<name>.auth` | [Model Providers](/docs/configuration/providers) | How the route authenticates. |
| `providers.<name>.base_url` | [Model Providers](/docs/configuration/providers) | The endpoint that receives model requests. |
| `providers.<name>.effort_supported` | [Model Providers](/docs/configuration/providers) | Whether the route accepts an effort value. |
| `providers.<name>.env` | [Model Providers](/docs/configuration/providers) | Environment variables exported for the job. |
| `providers.<name>.timeout_ms` | [Model Providers](/docs/configuration/providers) | The request timeout for the route. |
| `receiving_review.fix_severity_threshold` | [Review](/docs/configuration/review) | The fix threshold for direct use of the review-reception command. |
| `setup.claude_code_executable` | [Runtime Setup](/docs/configuration/runtime-setup) | A preinstalled client path to use instead of auto-install. |
| `setup.git_dir_pin` | [Runtime Setup](/docs/configuration/runtime-setup) | Pins the Git directory for cloud jobs. |
| `setup.git_work_tree_pin` | [Runtime Setup](/docs/configuration/runtime-setup) | Pins the Git work tree for cloud jobs. |
| `setup.install` | [Runtime Setup](/docs/configuration/runtime-setup) | Shell commands run on the runner before the agent starts. |
| `setup.node_version` | [Runtime Setup](/docs/configuration/runtime-setup) | The Node.js version to install. |
| `setup.node_working_directory` | [Runtime Setup](/docs/configuration/runtime-setup) | Where Node.js detection and caching look. |
| `setup.php_extensions` | [Runtime Setup](/docs/configuration/runtime-setup) | Extra PHP extensions to install. |
| `setup.php_tools` | [Runtime Setup](/docs/configuration/runtime-setup) | Extra PHP tools to install. |
| `setup.php_version` | [Runtime Setup](/docs/configuration/runtime-setup) | The PHP version to install. |
| `setup.python_version` | [Runtime Setup](/docs/configuration/runtime-setup) | The Python version to install. |
| `setup.services` | [Runtime Setup](/docs/configuration/runtime-setup) | Service containers started for the job. Each entry takes `name`, `image`, `ports`, `env` and `options`. |
| `telemetry.branch` | [Observability and Privacy](/docs/configuration/observability-and-privacy) | The branch that stores run records. |
| `verification_flight.enabled` | [Implementation](/docs/configuration/implementation) | Whether a clean verification result may be reused. |
| `verification_flight.lease_seconds` | [Implementation](/docs/configuration/implementation) | Reserved for future use. |
| `verification_flight.wait_timeout_seconds` | [Implementation](/docs/configuration/implementation) | Reserved for future use. |
| `workflows.prflow` | [Core Settings](/docs/configuration/core-settings) | Whether the shipped cloud workflows may run. |
| `workflows.prflow-review` | [Core Settings](/docs/configuration/core-settings) | Retained legacy setting for the withdrawn automatic-review tier. |

## Not on This Page

Skill extensions are files, not settings. They live under `.prflow/skill-extensions/` and are documented on [Skill Extensions](/docs/configuration/skill-extensions).

Credentials are never settings. Store them as GitHub Actions secrets, described in [Cloud Setup](/docs/runs/cloud/setup).

## Read Defaults Correctly

<Note>
  The value the scaffold writes and the value an absent key falls back to can differ. `/prflow:init` writes `prflow.effort: "low"`, while an absent `prflow.effort` falls back to `high`. Each family page names both whenever they differ, so read the fallback column rather than assuming the scaffolded file shows the default.
</Note>

Unknown top-level keys are tolerated so that an older config keeps working after an update. Nested sections have closed schemas, so an editor flags an unknown key inside one. Cloud config loading checks that the file is valid JSON, but it does not run a full schema check.

## A Setting Is Only Half the Answer

Some behavior is not configurable by a value at all:

- To make PRFlow follow a house rule, write a [prompt extension](/docs/configuration/skill-extensions).
- To let a cloud agent run one of your commands, grant it under [Tool Permissions](/docs/configuration/tool-permissions).
- To change who may start a run, see [Core Settings](/docs/configuration/core-settings) and [Human Control](/docs/concepts/human-control).

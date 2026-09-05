---
title: "Documentation and Retrospectives"
description: "Configure documentation paths, deferred-issue labels and retrospective limits."
---

Adapt PRFlow's documentation pass and local weekly retrospective to your repository's documentation layout and improvement process.

## Documentation and Deferrals

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `docs.internal` | String path | `docs/internal/` | Docs skills and implementation docs pass. Keep inside the repository. | `"internal": "docs/internal/"` |
| `docs.external` | String path | `docs/external/` | Docs skills and implementation docs pass. Do not place confidential source material here. | `"external": "docs/external/"` |
| `docs.internal_enabled` | Boolean | `true` | Combined docs pass. Direct invocation of the focused skill is unaffected. | `"internal_enabled": true` |
| `docs.external_enabled` | Boolean | `true` | Combined docs pass. Direct invocation of the focused skill is unaffected. | `"external_enabled": true` |
| `docs.release_notes_file` | String path | `docs/external/release-notes.md` | Release-note skill. This is customer-facing output. | `"release_notes_file": "docs/external/release-notes.md"` |
| `docs.changelog_file` | String path | `CHANGELOG.md` | Release-note reconciliation. | `"changelog_file": "CHANGELOG.md"` |
| `docs.labels` | Comma-separated string | `Documented` | Implementation applies labels best effort after the docs pass. | `"labels": "Documented,Shipped"` |
| `deferred.labels` | Comma-separated string | `PRFlow,Deferred` | Follow-up issue filing. Labels are applied best effort. | `"labels": "PRFlow,Deferred"` |
| `create_issue.investigation_record_enabled` | Boolean | `true` | `/prflow:create-issue` publication gate. Publication is withheld only when the value reads as the literal `false`. Sorting the draft into the implementer brief (issue body) and the investigation record is unaffected either way; when `false`, the record comment is not posted. | `"investigation_record_enabled": true` |

## Weekly Retrospective

These settings tune the retrospective loop's behavior on every tier — the local `/prflow:retrospective-weekly` command and the shipped scheduled workflow alike. Every key below sits inside the `prflow_retrospective` object. The table identifies settings that are currently declarative rather than enforced.

The shipped `devflow-retrospective.yml` workflow runs the same loop on a weekly schedule. It is a separate opt-in gated by its own key, `workflows["prflow-retrospective"]` (a JSON boolean, disabled by default) — **not** by `prflow_retrospective.enabled`, which stays declarative. See [Weekly Retrospective](/docs/workflows/retrospective-weekly) for the workflow, its triggers, and its state-PR guard.

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Security or cost note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_retrospective.enabled` | Boolean | Scaffold: `true` | Declarative in the current release. Setting it to false does not prevent direct invocation of `retrospective-weekly`. | `"enabled": true` |
| `prflow_retrospective.retrospective_model` | String model identifier | Scaffold: `claude-sonnet-5` | Controls analysis cost and capability. | `"retrospective_model": "claude-sonnet-5"` |
| `prflow_retrospective.audit_model` | String model identifier | Scaffold: `claude-opus-5` | Controls audit cost and capability. | `"audit_model": "claude-opus-5"` |
| `prflow_retrospective.implementation_branch_prefix` | String | `claude/` | Helps select pull requests. Labels and linked issues can also select them. | `"implementation_branch_prefix": "claude/"` |
| `prflow_retrospective.watched_authors` | Array of login strings | Falls back to `prflow.allowed_bots` | Restricts the primary author population. | `"watched_authors": ["my-bot"]` |

<Accordion title="Limits on what one retrospective run may file">
  | **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Security or cost note** | **Example** |
  | --- | --- | --- | --- | --- |
  | `prflow_retrospective.min_occurrences` | Positive integer | `2` | Higher values require more repetition before filing. | `"min_occurrences": 2` |
  | `prflow_retrospective.cooldown_days` | Nonnegative integer | `3` | Limits repeat filing for a recent open issue. | `"cooldown_days": 3` |
  | `prflow_retrospective.max_issues_per_run` | Nonnegative integer | `3` | Caps new retrospective issues per run. | `"max_issues_per_run": 3` |
  | `prflow_retrospective.max_open_issues` | Nonnegative integer | `10` | Limits the total number of open retrospective issues unless a previously fixed pattern has recurred. | `"max_open_issues": 10` |
  | `prflow_retrospective.max_open_per_category` | Nonnegative integer | `2` | Limits the number of open retrospective issues in one category. | `"max_open_per_category": 2` |
  | `prflow_retrospective.max_prs_per_run` | Positive integer | `500` | Soft cap on scanned pull requests. | `"max_prs_per_run": 500` |
  | `prflow_retrospective.audit_bundle_cap` | Positive integer | `10` | Limits how many pull request records are considered for each recurring pattern. Zero and negative values are rejected. | `"audit_bundle_cap": 10` |
  | `prflow_retrospective.diff_byte_cap` | Positive integer bytes | `204800` | Large diffs are omitted from the pull request information used for retrospective analysis. | `"diff_byte_cap": 204800` |

  These limits keep one run from filing a burst of issues into your tracker. Raise them only after you have read what a run files at the default settings.
</Accordion>

## Valid Example

```json
{
  "docs": {
    "internal": "docs/internal/",
    "external": "docs/external/",
    "internal_enabled": true,
    "external_enabled": true,
    "release_notes_file": "docs/external/release-notes.md",
    "changelog_file": "CHANGELOG.md",
    "labels": "Documented"
  },
  "deferred": {
    "labels": "PRFlow,Deferred"
  },
  "create_issue": {
    "investigation_record_enabled": true
  },
  "prflow_retrospective": {
    "enabled": true,
    "retrospective_model": "claude-sonnet-5",
    "audit_model": "claude-opus-5",
    "implementation_branch_prefix": "claude/",
    "min_occurrences": 2,
    "cooldown_days": 3,
    "max_issues_per_run": 3,
    "max_open_issues": 10,
    "max_open_per_category": 2,
    "max_prs_per_run": 500,
    "diff_byte_cap": 204800,
    "audit_bundle_cap": 10
  }
}
```

Expected result: the documentation pass writes developer docs under `docs/internal/`, public docs under `docs/external/` and release notes into `docs/external/release-notes.md`, labels the issue `Documented` when it finishes, files deferred work as issues labeled `PRFlow` and `Deferred`, and a weekly retrospective run files at most three issues.

To change how the documentation pass writes, rather than where it writes, use a [prompt extension](/docs/configuration/skill-extensions) for `docs`.

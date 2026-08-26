---
title: "Core Settings"
description: "Configure repository defaults, cloud authorization and shared command behavior."
---

Configure the repository defaults, authorization rules and shared behavior used by PRFlow's local and cloud paths.

## Everyday Settings

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `base_branch` | String branch name | Runtime and scaffold: `main` | Review and implementation base. Confirm the branch exists. | `"base_branch": "main"` |
| `claude_model` | String model identifier | Runtime and scaffold: `claude-opus-5` | Global model. Cloud workflows reject an empty value or one that begins with `-`. | `"claude_model": "claude-opus-5"` |
| `prflow.allowed_bots` | Comma-separated string | `claude,dependabot` | All cloud gates. List only automation identities that may incur runs. | `"allowed_bots": "claude,dependabot,my-app"` |
| `prflow.allowed_users` | `*` or comma-separated logins | `*` | All cloud gates. Humans must also have write, maintain or admin access. | `"allowed_users": "octocat,maintainer"` |
| `prflow.effort` | `low`, `medium`, `high`, `xhigh` or `max` | Scaffold: `low`; absent runtime fallback: `high` | General cloud command workflow. Provider routes omit effort unless the provider supports it. | `"effort": "low"` |
| `workflows.prflow` | Boolean | Scaffold: `true`; absent workflow read resolves disabled | Both fresh-install cloud workflows. Keep config committed or triggers cannot enable. | `"prflow": true` |

<Warning>
  `prflow.allowed_users` decides who can spend money and change your repository from a comment. The default `*` allows any collaborator with write, maintain or admin access. Narrow it to named logins on a repository whose collaborator list is wider than the set of people you want triggering runs.

  `prflow.allowed_bots` is separate and is not covered by `allowed_users`. Adding an automation identity there lets that automation start runs on its own.
</Warning>

<Note>
  `prflow.effort` is the clearest case where the scaffolded file and the runtime fallback differ. `/prflow:init` writes `"effort": "low"`, but a config with no `prflow.effort` key at all resolves to `high`. Deleting the key does not restore the scaffolded value.
</Note>

<Accordion title="Settings you rarely need to change">
  | **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
  | --- | --- | --- | --- | --- |
  | `$schema` | String path or URL | Scaffold: `./config.schema.json` | Editor only. It is ignored at runtime. | `"$schema": "./config.schema.json"` |
  | `prflow_version` | String tag, branch or commit SHA | Scaffold: empty; installer normally stamps a commit SHA | Thin cloud installs only. An empty runtime pin fails rather than tracking `main`. Vendored mode ignores it. | `"prflow_version": "v2.31.31"` |
  | `prflow.workpad_marker` | Nonempty string marker | `<!-- prflow:workpad -->` | Implementation state and self-trigger guard. Changing it can make older workpads undiscoverable. | `"workpad_marker": "<!-- prflow:workpad -->"` |
  | `workflows.prflow-review` | Boolean | Scaffold: `false` | **Retained legacy setting.** It enables nothing in a fresh install because the automatic-review files are not shipped. Existing installations that retained those files remain exposed to their documented defects. | `"prflow-review": false` |

  `prflow_version` is normally stamped by the installer. Change it by hand only to pin or roll back a cloud install deliberately. See [Cloud Updates](/docs/runs/cloud/updates).

  If a warning about the retained automatic-review tier applies to your repository, see [Remove the Withdrawn Automatic-Review Tier](/docs/configuration/review#remove-the-withdrawn-automatic-review-tier).
</Accordion>

## Valid Core Example

```json
{
  "$schema": "./config.schema.json",
  "base_branch": "main",
  "claude_model": "claude-opus-5",
  "prflow_version": "v2.31.31",
  "prflow": {
    "allowed_bots": "claude,dependabot",
    "allowed_users": "octocat,maintainer",
    "workpad_marker": "<!-- prflow:workpad -->",
    "effort": "low"
  },
  "workflows": {
    "prflow": true,
    "prflow-review": false
  }
}
```

Expected result: cloud runs are enabled, only `octocat` and `maintainer` may trigger one, and every run works from `main` with `claude-opus-5` at low effort.

Use [Model Providers](/docs/configuration/providers) for `prflow.provider` and `prflow.claude_model`. Use [Tool Permissions](/docs/configuration/tool-permissions) for `prflow.allowed_tools`. To add house rules that no setting expresses, write a [prompt extension](/docs/configuration/prompt-extensions).

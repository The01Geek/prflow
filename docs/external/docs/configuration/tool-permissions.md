---
title: "Tool Permissions"
description: "Grant repository commands to the correct PRFlow execution path."
---

Grant cloud agents only the repository-specific test, lint, build or deployment commands their work requires.

Installation and runtime provisioning do not grant command execution. PRFlow appends configured entries to a built-in allowlist; configured arrays do not replace the base profile.

<Warning>
  Every entry you add lets an agent run that command against your repository, with whatever the runner environment can reach. A broad pattern such as `Bash(npm run:*)` grants every script in `package.json`, including one added later by a pull request. Grant the narrowest command that does the job, and review a change to these arrays as carefully as a change to a workflow file.
</Warning>

| **Setting** | **Type and accepted values** | **Fallback** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow.allowed_tools` | Array of claude-code-action tool strings | Empty array adds nothing | General cloud command workflow. It does not apply to implementation. | `["Bash(npm test:*)"]` |
| `prflow_implement.allowed_tools` | Array of claude-code-action tool strings | Empty array adds nothing | Shipped implementation path. It does not inherit `prflow.allowed_tools`. | `["Bash(npm test:*)"]` |
| `prflow_runner.allowed_tools` | Array of claude-code-action tool strings | Empty array adds nothing | **Removed** (issue #2071) from the shipped schema/example; stripped from a consumer config on the next installer apply. Where the withheld runner is still installed it is read only when `prflow_runner.provision_env` is true, and built-in restrictions still apply. | `["Bash(npm test:*)"]` |

## Grant Commands per Path

List the leading command and arguments directly. Add the same entry under every path that needs it:

```json
{
  "prflow": {
    "allowed_tools": [
      "Bash(npm test:*)",
      "Bash(npm run lint:*)"
    ]
  },
  "prflow_implement": {
    "allowed_tools": [
      "Bash(npm test:*)",
      "Bash(npm run lint:*)"
    ]
  }
}
```

Expected result: a cloud implementation run and a cloud command run may each invoke `npm test` and `npm run lint`. Any other command stays denied.

The two shipped allowlists are independent. Neither inherits from the other. A command provisioned by `setup.install` can still be denied if it is absent from the active tier's list.

Use the narrowest leading command that performs the needed check. PRFlow's built-in restrictions can deny compound shell wrappers and raw `bash`, `sh`, `zsh`, `eval`, `exec`, `source` or `sudo` commands even when a broader entry appears in the configuration.

## Plan Grants Before the Work

<Note>
  Cloud workflows resolve grants at trigger time from the default branch. A pull request that adds its own permission cannot use that permission during the same run. The grant becomes effective after merge.
</Note>

If a required verification command is not granted, implementation marks that verification blocked. It does not treat CI as an in-run substitute. Merge the narrow grant first, then retry the work that needs it.

Naming a command in a [prompt extension](/docs/configuration/skill-extensions) does not grant it. If your extension tells a run to use `make verify`, add `Bash(make verify:*)` here as well.

---
title: "Cloud-Run Problems"
description: "Diagnose comment authorization, authentication, runners, runtime setup, stale pins and interrupted workflows."
---

Diagnose a GitHub Actions run that failed or an authorized comment that did not start one. Each section opens with the signal to look for and a command you can run as-is; `gh` fills the `{owner}/{repo}` placeholders from the repository's git remote.

## A Comment Did Not Trigger

**Signal:** the comment received no 🚀 reaction. That usually means parsing or authorization declined before the agent job started.

List the most recent gate runs to see whether the workflow fired at all:

```bash
gh run list --workflow devflow.yml --limit 5
```

Confirm all of these conditions:

- The command is the first recognized standalone command in the comment.
- It is not quoted, fenced, indented as code or embedded in prose.
- `/prflow:implement` is on a regular issue, not a pull request.
- `/prflow:review` is on the pull request's **Conversation** tab.
- The comment does not contain `@claude`.
- `workflows.prflow` is true in committed config.

## The Actor Is Unauthorized

**Signal:** the gate job's log records a decline reason such as `is not in the configured allowed_users allowlist` or `is not an allowed bot or write/admin/maintain collaborator`.

Check the exact permission GitHub reports for the commenting account:

```bash
gh api repos/{owner}/{repo}/collaborators/<login>/permission --jq .permission
```

Humans must match `prflow.allowed_users` and have write, maintain or admin repository permission. Bots must match `prflow.allowed_bots`. Check the exact login, including the configured bare bot name.

An API or permission lookup failure declines the run. Fix the gate job's token permissions or transient GitHub access, then retry.

## Model Authentication Fails

**Signal:** on a provider route, the run stops with an error of the form `::error::.prflow/config.json section '<section>' selects provider '<name>' but the DEVFLOW_PROVIDER_API_KEY repository secret is empty.`

List the secrets the workflow can see:

```bash
gh secret list
```

On the default route, confirm `CLAUDE_CODE_OAUTH_TOKEN` is present in the workflow's repository or environment secrets. On a provider route, confirm the section names a valid provider and `DEVFLOW_PROVIDER_API_KEY` is present.

A partially routed installation can need both credentials. A fully provider-routed installation can omit OAuth only when every active model-running section is routed.

## The Job Is Queued Indefinitely

**Signal:** the run sits in **Queued** with no error. GitHub queues an unmatched runner label set without raising a configuration error; an invalid JSON array instead fails earlier with a visible `fromJSON` error.

Compare `DEVFLOW_RUNNER`'s label array against the labels of your registered runners:

```bash
gh api repos/{owner}/{repo}/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

The JSON label array must match all labels on an online self-hosted runner that is registered, online and eligible for the repository.

## Setup Fails Before the Agent Starts

**Signal:** a provisioning step before the agent step is the first failure in the run.

Read only the failing steps' logs:

```bash
gh run view <run-id> --log-failed
```

Confirm the runner has bash, `git`, `gh`, `jq`, Python 3.11 or newer and Docker when services require it. Check `setup` values and commands in their documented order.

On self-hosted Windows, preinstall Claude Code and set `setup.claude_code_executable`. If Python exists without the `python3` command, install the supported shim on the runner.

## A Tool Is Installed but Denied

**Signal:** the run's execution diagnostics (in the job log and run summary) report a nonzero permission-denial count, while the tool itself is present on the runner.

Provisioning and command authorization are separate. Add a narrow tool entry to the active workflow's allowlist. The general cloud-command and implementation allowlists do not inherit from each other. Merge the grant before expecting it in a new run.

## Plugin Vendoring Fails

**Signal:** the run stops with an error of the form `::error::incomplete vendor: missing after materialization: <files>`, or an earlier loud failure naming an empty `prflow_version`.

In thin mode, confirm `prflow_version` is nonempty and resolves to a tag, branch or commit in `The01Geek/prflow`. An empty pin fails loudly to prevent mutable-main drift. A stale pin can also omit a helper required by newer workflow bytes.

Re-run the installer with a current release tag and apply the update so workflow files and the runtime pin move together. If a locally edited workflow was preserved, merge its `.prflow-new` sidecar by hand.

## The Run Stopped Without Finishing

**Signal:** the workpad or review-progress comment shows a non-complete status, or the run ended with no verdict.

Read the failing steps and the execution diagnostics:

```bash
gh run view <run-id> --log-failed
```

Use the workpad or review-progress comment to distinguish Blocked, Failed, Cancelled and still-interim state. Inspect execution diagnostics for permission denials. Correct the cause before posting the command again.

Implementation retries reuse the workpad and pushed branch checkpoints. Review retries target the current pushed head. See [Cloud Recovery](/docs/runs/cloud/recovery) for the recovery sequence.

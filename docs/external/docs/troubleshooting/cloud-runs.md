---
title: "Cloud-Run Problems"
description: "Diagnose a GitHub Actions run that failed, or an authorized comment that started no run."
---

Match the signal you can see to an entry below, run its command as-is, then apply its fix. `gh` fills the `{owner}/{repo}` placeholders from the repository's git remote.

<AccordionGroup>

<Accordion title="A comment did not trigger a run">

**Signal:** the comment received no 🚀 reaction. That usually means parsing or authorization declined before the agent job started.

PRFlow's commands are split across two workflow files, so list the right one. The filenames deliberately keep the older `devflow` prefix.

The implement command runs from `devflow-implement.yml`:

```bash
gh run list --workflow devflow-implement.yml --limit 5
```

The review, review-and-fix and pr-description commands run from `devflow.yml`:

```bash
gh run list --workflow devflow.yml --limit 5
```

An empty list for the workflow you expected means the trigger never fired at all. Confirm all of these:

- The command is the first recognized standalone command in the comment.
- It is not quoted, fenced, indented as code or wrapped in prose.
- `/prflow:implement` is on a regular issue, not on a pull request.
- `/prflow:review` is on the pull request's **Conversation** tab.
- The comment does not contain `@claude`.
- `workflows.prflow` is true in the committed configuration.

</Accordion>

<Accordion title="The actor is unauthorized">

**Signal:** the gate job's log records a decline reason such as `is not in the configured allowed_users allowlist` or `is not an allowed bot or write/admin/maintain collaborator`.

Check the exact permission GitHub reports for the commenting account:

```bash
gh api repos/{owner}/{repo}/collaborators/<login>/permission --jq .permission
```

A human must match `prflow.allowed_users` and hold write, maintain or admin permission on the repository. A bot must match `prflow.allowed_bots`. Check the exact login, including the bare bot name as configured.

An API or permission lookup that fails declines the run. Fix the gate job's token permissions or the transient GitHub access problem, then try again.

</Accordion>

<Accordion title="Model authentication fails">

**Signal:** on a provider route, the run stops with an error of the form `::error::.prflow/config.json section '<section>' selects provider '<name>' but the DEVFLOW_PROVIDER_API_KEY repository secret is empty.`

List the secrets the workflow can see:

```bash
gh secret list
```

On the default route, confirm `CLAUDE_CODE_OAUTH_TOKEN` is present in the repository or environment secrets. On a provider route, confirm the section names a valid provider and that `DEVFLOW_PROVIDER_API_KEY` is present.

A partly routed installation can need both credentials. A fully provider-routed installation can omit the OAuth token only when every section that runs a model is routed.

</Accordion>

<Accordion title="The job is queued indefinitely">

**Signal:** the run sits in **Queued** with no error. GitHub queues an unmatched runner label set without raising a configuration error. An invalid JSON array fails earlier instead, with a visible `fromJSON` error.

Compare the `DEVFLOW_RUNNER` label array against the labels of your registered runners:

```bash
gh api repos/{owner}/{repo}/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

Every label in the JSON array must appear on one self-hosted runner that is registered, online and eligible for this repository.

</Accordion>

<Accordion title="Setup fails before the agent starts">

**Signal:** a provisioning step before the agent step is the first failure in the run.

Read only the failing steps' logs:

```bash
gh run view <run-id> --log-failed
```

Confirm the runner has bash, `git`, `gh`, `jq`, Python 3.11 or newer, and Docker when services need it. Check the `setup` values and commands in their documented order.

On a self-hosted Windows runner, preinstall Claude Code and set `setup.claude_code_executable`. If Python exists without a `python3` command, install the supported shim on the runner — see [Installation Problems](/docs/troubleshooting/installation).

</Accordion>

<Accordion title="A tool is installed but denied">

**Signal:** the run's execution diagnostics, in the job log and the run summary, report a nonzero permission-denial count while the tool itself is present on the runner.

Read the count and the denied names:

```bash
gh run view <run-id> --log | grep -i "denial"
```

Provisioning and command authorization are separate concerns. Installing a tool does not permit it. Add a narrow tool entry to the allowlist for the path that needs it: `prflow_implement.allowed_tools` for an implementation run, `prflow.allowed_tools` for the light command path. The two do not inherit from each other.

<Warning>
Merge the grant before you expect it in a run. The workflow reads these settings from the default branch at trigger time, so a grant added by a pull request does not apply to that pull request's own run.
</Warning>

</Accordion>

<Accordion title="Plugin vendoring fails">

**Signal:** the run stops with an error of the form `::error::incomplete vendor: missing after materialization: <files>`, or an earlier loud failure naming an empty `prflow_version`.

Read the pin the run used:

```bash
jq -r '.prflow_version' .prflow/config.json
```

In thin mode, `prflow_version` must be nonempty and must resolve to a tag, branch or commit in `The01Geek/prflow`. An empty pin fails loudly, to stop the installation drifting with a moving branch. A stale pin can also omit a helper that newer workflow bytes call.

Re-run the installer with a current release tag and apply the update, so the workflow files and the runtime pin move together. If a locally edited workflow was preserved, merge its `.prflow-new` sidecar by hand — then **re-run the installer once more in apply mode** (`--apply`, or `DEVFLOW_APPLY=1` for a `curl | bash` invocation). Merging the sidecar changes the workflow's bytes, and for `.github/workflows/devflow-implement.yml` (or the `setup-project-env` action, or `.prflow/lint-manifest.json`) a stale `.prflow/install-state.json` marker makes the implement run refuse to start on every run until that re-apply rebinds the marker to the merged bytes.

</Accordion>

<Accordion title="The run stopped without finishing">

**Signal:** the workpad or the review-progress comment shows a status that is not Complete, or the run ended with no verdict.

Read the failing steps and the execution diagnostics:

```bash
gh run view <run-id> --log-failed
```

Use the workpad or the review-progress comment to tell Blocked, Failed, Cancelled and still-running apart. Look at the execution diagnostics for permission denials. Correct the cause before you post the command again.

An implementation retry reuses the workpad and any pushed branch checkpoint. A review retry targets the current pushed head. See [Cloud Recovery](/docs/runs/cloud/recovery) for the full sequence.

</Accordion>

</AccordionGroup>

## Related Articles

- [Cloud Runs](/docs/runs/cloud/index)
- [Triggers](/docs/runs/cloud/triggers)
- [Runners](/docs/runs/cloud/runners)
- [Cloud Recovery](/docs/runs/cloud/recovery)

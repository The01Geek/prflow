---
title: "Cloud Runners"
description: "Select and provision GitHub-hosted or self-hosted runners for PRFlow cloud jobs."
---

Keep PRFlow on the default GitHub-hosted Linux runner, or move every job to a runner you control.

## Select a Runner

Every job in the three shipped workflows (`devflow.yml`, `devflow-implement.yml`, `devflow-retrospective.yml`) runs on `ubuntu-latest` by default. One GitHub Actions variable, `DEVFLOW_RUNNER`, changes all of them at once.

Set it under **Settings → Secrets and variables → Actions → Variables**.

| **Value** | **Result** |
| --- | --- |
| Unset or empty | `ubuntu-latest`, the standard GitHub-hosted Linux runner. |
| `windows-latest` | The single runner label you named. |
| `["self-hosted","windows","PRFlow"]` | A runner matching every label in the JSON array. |
| A value starting with `[` that is not valid JSON | Workflow evaluation fails with a `fromJSON` error. |

Keep the `DEVFLOW_` prefix exactly as written. There is no `PRFLOW_RUNNER` alias.

## Send the Light Jobs to a Cheaper Runner

A second optional variable, `DEVFLOW_LIGHT_RUNNER`, moves the *light* (mostly one-core) jobs onto a cheaper runner while the heavy jobs stay on `DEVFLOW_RUNNER`. It takes the same value shapes — a bare label or a JSON label array.

The light jobs are, in `devflow.yml`: `config`, `review_dedupe`, `gate`, `review_finalize`, and the `command` job when the triggering comment is a standalone `/prflow:review`. In `devflow-implement.yml`: `config` and `gate`. Everything else keeps `DEVFLOW_RUNNER` — a `/prflow:review-and-fix` or `/prflow:pr-description` `command` job, the implement `claude` job (which runs the test suite, and since issue #402 prefers its own optional `DEVFLOW_IMPLEMENT_RUNNER`, falling back to `DEVFLOW_RUNNER`), and every `devflow-retrospective.yml` job.

When `DEVFLOW_LIGHT_RUNNER` is unset or empty, each light job falls back to the `DEVFLOW_RUNNER` chain — `DEVFLOW_RUNNER`'s value, or `ubuntu-latest` when that is also unset. Set nothing new and no job moves.

## Give Standalone Review Its Own Runner

A third optional variable, `DEVFLOW_REVIEW_RUNNER`, applies to one job: the `command` job on a standalone `/prflow:review`. It is preferred over `DEVFLOW_LIGHT_RUNNER` there and takes the same value shapes. Use it when that job is worth its own machine but the one-core helpers are not — a standalone review is model-API-bound, so it wants a long-lived, uninterrupted box rather than a fast one, and the helpers around it finish in about a minute.

Unset or empty, the expression falls through to the `DEVFLOW_LIGHT_RUNNER` chain and then the `DEVFLOW_RUNNER` chain, so setting nothing moves nothing.

<Warning>
  The light jobs still carry secrets: the standalone-review job runs your model-provider API key (under the read-only reviewer identity) and the helper jobs mint the GitHub App token. If you self-host `DEVFLOW_RUNNER` for network isolation, pointing `DEVFLOW_LIGHT_RUNNER` at a GitHub-hosted runner runs those secrets outside that boundary. Keep the light runner inside the same fleet unless a GitHub-hosted light runner is acceptable for those secrets.
</Warning>

<Warning>
  A label set that no registered runner matches does not fail. GitHub leaves the job queued forever with no error message. If a run never starts and the **Actions** tab shows it as queued, compare your label array against your runner's registered labels first.
</Warning>

<Warning>
  If the variable name is misspelled or deleted, the expression falls back to `ubuntu-latest` and every job silently moves to a GitHub-hosted runner. That job carries your GitHub App private key and your model-provider API key in its environment. If you self-host for network isolation or compliance, check the runner label on a run after any change to this variable.
</Warning>

## Provision a Self-Hosted Runner

Install these before you point PRFlow at the runner:

- `git`.
- GitHub CLI (`gh`).
- `jq`.
- Python 3.11 or newer, available as `python3`.
- A POSIX bash on `PATH`.
- `openssl`, `curl` and `nohup`. The long-run credential refresher needs all three.
- Docker, when `setup.services` or your own checks need it.

Confirm the set in one pass on the runner:

```bash
for t in git gh jq python3 bash openssl curl nohup; do
  command -v "$t" >/dev/null && echo "ok   $t" || echo "MISSING $t"
done
python3 --version
```

Every line should read `ok`, and the version should be 3.11 or higher. Fix each `MISSING` line before you continue.

<Note>
  The shipped workflows upload their execution transcript with `actions/upload-artifact@v7`, which requires **Actions Runner 2.327.1 or newer** (Node 24). A GitHub-hosted runner meets this floor automatically; a self-hosted runner older than 2.327.1 must be upgraded, or the upload step fails.
</Note>

<AccordionGroup>
  <Accordion title="Windows Runners">
    The workflows force `bash` for their `run:` steps, so install Git Bash or an equivalent POSIX bash. If Python is available only as `python` or `py -3`, run the shipped shim provisioner once on the runner, from a checkout that has the plugin tree:

    ```bash
    bash .prflow/vendor/prflow/scripts/provision-python3-shim.sh --apply
    ```

    It refuses to create a shim when no compatible interpreter is present, so a clean exit means the runner is ready.

    PRFlow cannot make its job credential files owner-only on Windows, because Windows ignores POSIX file modes. Those files live in the runner's temporary directory under its work directory. Isolation is your host setup:

    - Run each runner service under its own account. Register it with `--windowslogonaccount`, because the default `NETWORK SERVICE` account is shared by every service that uses it.
    - Restrict each runner's work directory to that account and administrators. With the service stopped, run:

    ```powershell
    icacls "C:\actions-runner-1\_work" /grant:r "RUNNERHOST\runner-1:(OI)(CI)M" "BUILTIN\Administrators:(OI)(CI)F"
    icacls "C:\actions-runner-1\_work" /inheritance:r
    icacls "C:\actions-runner-1\_work"
    ```

    The first command grants the runner account Modify, which it needs to run jobs. The second removes every inherited entry. The third displays the result, which should list only those two entries.

    Runner services that share one account also share that account's `.claude/settings.json`, and each can read the others' job credential files.
  </Accordion>
  <Accordion title="Executables in Nonstandard Locations">
    Set `DEVFLOW_GH`, `DEVFLOW_JQ` or `DEVFLOW_BASH` only when the working executable is somewhere the normal search path does not reach. A correct `PATH` is simpler and less likely to drift.
  </Accordion>
</AccordionGroup>

## Interruptible (Spot) Capacity

Self-hosted heavy runners on interruptible capacity (for example EC2 Spot) trade cost for the chance that the provider reclaims the instance mid-run. If that happens to a long `/prflow:implement` job, the runner disappears before the job finishes and the run ends without completing. A recovery job then reconciles the lost run automatically: it resumes a failed run with a bounded request, terminalizes it to 💥 Failed when it cannot resume, and names the real cause of the loss in its comment. For a Linux EC2 Spot runner you can additionally opt in to confirmed reclaim detection by setting `prflow_implement.spot_interruption_watcher.enabled` to `true`, so a reclaim is named as such rather than as a generic runner loss. See [Cloud Recovery](/docs/runs/cloud/recovery) for what survives an interruption, the recovery job, the opt-in Spot watcher, and how to pick the work back up.

## Use Claude Code on Windows

The action's bundled Claude Code installer is Unix-only. On a self-hosted Windows runner, install Claude Code yourself and point `.prflow/config.json` at it:

```json
{
  "setup": {
    "claude_code_executable": "C:\\Users\\runner\\.local\\bin\\claude.exe"
  }
}
```

Use a single-line path, with the backslashes escaped as shown. An absent or empty value uses automatic installation. A value PRFlow rejects produces a warning in the run log and falls back to automatic installation.

<Note>
  This is a trigger-time setting. It takes effect only after the configuration change is merged into your default branch, not while it sits in a pull request.
</Note>

## Avoid Two Configuration Traps

Leave `setup.git_dir_pin` and `setup.git_work_tree_pin` at `false` unless you have validated their constraints:

- `git_dir_pin` is not honored by implementation runs and can misdirect repository-root configuration reads. When it is enabled and an implement run ignores it, the run summary now carries a `::warning::` naming the suppression, so the divergence from your config is visible rather than silent.
- `git_work_tree_pin` breaks remote marketplace cloning. It suits a local-only marketplace list and nothing else.

<Warning>
  PRFlow can send jobs to any runner you configure, but it is not certified for every non-Linux environment. Run one complete workflow end to end on the target runner before you treat it as production-ready.
</Warning>

Continue with [Cloud Triggers](/docs/runs/cloud/triggers).

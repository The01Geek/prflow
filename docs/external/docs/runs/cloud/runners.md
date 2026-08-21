---
title: "Cloud Runners"
description: "Select and provision GitHub-hosted or self-hosted runners for PRFlow."
---

Move PRFlow jobs from the default GitHub-hosted Linux runner to a compatible self-hosted or custom runner.

## Select a Runner

Every job in the two shipped workflows uses `ubuntu-latest` by default. Set the GitHub Actions variable `DEVFLOW_RUNNER` to select another runner for all of them.

| **Value** | **Result** |
| --- | --- |
| Unset or empty | `ubuntu-latest` |
| `windows-latest` | One runner label |
| `["self-hosted","windows","PRFlow"]` | A runner matching every label in the JSON array |
| A value beginning with `[` that is invalid JSON | Workflow evaluation fails with a `fromJSON` error |

Set it under **Settings → Secrets and variables → Actions → Variables**. Keep the `DEVFLOW_` name. No `PRFLOW_RUNNER` alias exists.

## Provision a Self-Hosted Runner

Install these prerequisites before selecting the runner:

- `git`.
- GitHub CLI (`gh`).
- `jq`.
- Python 3.11 or newer, available as `python3`.
- A POSIX bash on `PATH`.
- `openssl`, `curl`, and `nohup` — the long-run credential refresher hard-requires all three.
- Docker when `setup.services` or repository checks need it.

The workflows force `bash` for `run:` steps. On Windows, install Git Bash or an equivalent POSIX bash. If Python is available only as `python` or `py -3`, run the shipped `scripts/provision-python3-shim.sh --apply` once on the runner. Use `DEVFLOW_GH`, `DEVFLOW_JQ` or `DEVFLOW_BASH` only when the working executables are in nonstandard locations.

## Use Claude Code on Windows

The action's bundled Claude Code installer is Unix-only. Preinstall Claude Code on a self-hosted Windows runner and set `setup.claude_code_executable` to the single-line path of `claude.exe`.

```json
{
  "setup": {
    "claude_code_executable": "C:\\Users\\runner\\.local\\bin\\claude.exe"
  }
}
```

An absent or empty value uses automatic installation. A rejected value warns and falls back to automatic installation. This trigger-time setting takes effect after its configuration change merges.

## Avoid Runner Selection Traps

A self-hosted label array must match a registered runner's labels. GitHub leaves an unmatched job queued rather than failing it.

Leave `setup.git_dir_pin` and `setup.git_work_tree_pin` at `false` unless you have validated their documented constraints. `git_dir_pin` is not honored by implementation and can misdirect repository-root config reads. `git_work_tree_pin` breaks remote marketplace cloning and is appropriate only for a local-only marketplace list.

PRFlow can send jobs to the configured runner, but it is not certified for every non-Linux environment. Run one complete shipped workflow on the target runner before treating it as production-ready.

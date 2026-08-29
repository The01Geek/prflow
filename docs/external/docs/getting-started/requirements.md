---
title: "Requirements"
description: "Prepare the local tools and GitHub access that PRFlow needs."
---

Get your workstation ready for local PRFlow runs. Cloud runs use a separate [environment and runner setup path](/docs/runs/cloud/setup).

## Required Local Tools

Install Claude Code, then make these tools available on `PATH`:

| **Requirement** | **Why PRFlow Needs It** |
| --- | --- |
| Claude Code | Loads and runs the PRFlow plugin skills. |
| Git | Reads repository history and manages the feature branch. |
| GitHub CLI (`gh`) | Reads and writes issues, pull requests and reviews. Authenticate it with `gh auth login`. |
| `jq` | Processes the JSON that PRFlow's helpers pass between steps. |
| Python 3.11 or newer, available as `python3` | Runs the configuration, workpad and verification helpers. |
| POSIX bash | Runs PRFlow's shell helpers. `sh`, Dash and PowerShell alone are not substitutes. |

<Note>
  Claude Code is the client PRFlow documents. Other agent clients can load the plugin as well. See the compatibility note on the [installation page](/docs/getting-started/installation).
</Note>

The repository must be a Git repository connected to GitHub. Your GitHub identity needs enough access to read the issue and to create branches, issue comments and pull requests.

PRFlow avoids GNU-only command flags, so the standard macOS and BSD command-line tools work.

## Check Your Machine

Run these commands and read the versions they print:

```bash
git --version
gh --version
jq --version
python3 --version
bash --version
gh auth status
```

On a macOS workstation with everything installed, the first four print something like this:

```
git version 2.50.1 (Apple Git-155)
gh version 2.96.0 (2026-07-02)
jq-1.7.1-apple
Python 3.14.6
```

Your exact version numbers will differ. What matters is that every command prints a version instead of `command not found`, that Python reports 3.11 or newer and that `gh auth status` reports a logged-in account.

PRFlow also ships a preflight check, which [initialization](/docs/getting-started/initialization) runs for you. When every dependency is present it prints one line:

```
devflow preflight: all dependencies present.
```

If Python cannot import PyYAML but everything else is present, it prints a different line and still succeeds:

```
devflow preflight: required dependencies present; PyYAML advisory (see above).
```

<Note>
  The preflight tool keeps the older `devflow` spelling in its own output. That is expected and is not a sign of a stale install.
</Note>

## macOS Ships an Older Python

macOS includes `python3` at `/usr/bin/python3`, and on current releases that interpreter is Python 3.9. PRFlow needs 3.11 or newer. If a newer Python is installed but `/usr/bin/python3` comes first on `PATH`, PRFlow's preflight reports the version failure even though a suitable Python exists on the machine.

Check which interpreter actually answers, and what else is available:

```bash
python3 -VV
which -a python3
```

On a machine where a newer Python is installed and correctly ordered, the result looks like this:

```
Python 3.14.6 (main, Jun 10 2026, 10:03:53) [Clang 21.0.0 (clang-2100.0.123.102)]
/opt/homebrew/bin/python3
/usr/bin/python3
```

The first line is the version that will run. The list shows every `python3` on `PATH` in the order the shell searches them. If `/usr/bin/python3` is first and reports 3.9, install a newer Python and put it ahead of `/usr/bin` on `PATH`.

## PyYAML Is Advisory for Local Runs

PyYAML is recommended but is not a hard local prerequisite. Install it with:

```bash
python3 -m pip install 'PyYAML>=6'
```

Name the package rather than pointing `pip` at a requirements file. A requirements file resolves against your current working directory, so in a Python project you would install that project's dependencies by mistake.

Without PyYAML, one helper cannot apply severity demotions from deferred-findings blocks in pull-request bodies. The review continues with the findings intact. That can surface and fix more findings than you intended, so installing PyYAML avoids unnecessary churn.

PyYAML stays required for PRFlow's own test suite, its continuous integration and the cloud tiers.

## Windows Bash Choices

On Windows, use any one of these POSIX bash environments:

- Windows Subsystem for Linux (WSL) bash
- Git Bash
- MSYS2 bash

PRFlow does not require one specific choice. Set the `DEVFLOW_BASH` environment variable when you need to select the bash executable explicitly:

```bash
export DEVFLOW_BASH=/path/to/bash
```

<Warning>
  `DEVFLOW_BASH` keeps the `DEVFLOW_` prefix on purpose. PRFlow reads no `PRFLOW_BASH` equivalent, so renaming the variable removes the setting instead of moving it, and it does so silently.
</Warning>

A PowerShell-only host with none of these bash environments cannot run PRFlow's shell helpers. Windows may also expose Python as `python` or `py -3` with no `python3` command at all. Follow [installation troubleshooting](/docs/troubleshooting/installation) if the preflight reports that case.

## Let Initialization Check the Environment

The recommended [`init` skill](/docs/getting-started/initialization) runs the bundled preflight after it scaffolds the repository files. A missing tool is reported with a remedy, and the scaffold that was already written stays in place.

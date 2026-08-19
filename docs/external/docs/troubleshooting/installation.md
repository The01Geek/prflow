---
title: "Installation Problems"
description: "Fix plugin loading, missing prerequisites, Windows shims and cloud installer sidecars."
---

Restore missing plugin commands or resolve installer prerequisites that prevent PRFlow from starting.

## PRFlow Commands Do Not Appear

Confirm that the plugin is `prflow` and the intentionally retained marketplace name is `devflow-marketplace`.

For Claude Code:

```bash
claude plugin marketplace add The01Geek/prflow
claude plugin install prflow@devflow-marketplace
```

Then run `/reload-plugins` or restart Claude Code. If the marketplace is stale, run:

```bash
claude plugin marketplace update devflow-marketplace
claude plugin update prflow@devflow-marketplace
```

For GitHub Copilot CLI, use `copilot plugin marketplace add`, `copilot plugin install`, `copilot plugin marketplace update` and `copilot plugin update`. For Codex CLI, use `codex plugin marketplace add`, `codex plugin add` and `codex plugin marketplace upgrade`.

## Preflight Reports a Missing Tool

PRFlow requires working `git`, `gh`, `jq` and Python 3.11 or newer available as `python3`. Run the bundled preflight from a PRFlow source or vendored checkout:

```bash
bash lib/preflight.sh
```

Install every dependency it reports. A local-only PyYAML gap is advisory, but install it to restore all helper behavior:

```bash
python3 -m pip install PyYAML
```

Cloud workflows provision PyYAML through their configured setup. Keep the scaffolded Python install line unless you replace it with an equivalent.

## Windows Has Python but Not `python3`

If `python` or `py -3` reports Python 3.11 or newer, create the supported shim from a PRFlow checkout:

```bash
bash scripts/provision-python3-shim.sh --apply
```

Run the preflight again. The provisioner refuses to create a shim when no compatible interpreter exists.

## Windows Resolves the Wrong `gh` or `jq`

PRFlow probes `gh` and `gh.exe`, and likewise `jq` and `jq.exe`, for a runnable binary. Set an override when PATH still selects the wrong executable:

```bash
export DEVFLOW_GH=gh.exe
export DEVFLOW_JQ=jq.exe
```

If shell helpers are not running under a POSIX bash, install WSL bash, Git Bash or MSYS2 bash and set `DEVFLOW_BASH` at the invocation boundary.

## A Windows Helper Crashed on an Em-dash or Emoji

PRFlow's first-party Python helpers force their standard output and standard error to UTF-8 on their entry path, so non-ASCII output (an em-dash, an emoji) no longer raises an encoding error on a Windows host whose default codec is not UTF-8. If an older version crashes this way, update PRFlow. On Linux and macOS, where the default codec is already UTF-8, this is a no-op.

## The Cloud Installer Preserved a File

A line naming `PRESERVED` means the installer could not prove that the existing file was untouched. It leaves the original in place and writes the new bytes to `<path>.prflow-new`.

Compare the sidecar, merge the intended changes into your maintained file and remove the sidecar. Do not commit sidecars. If every file was preserved because Python could not run, fix Python and repeat the update for a real provenance comparison.

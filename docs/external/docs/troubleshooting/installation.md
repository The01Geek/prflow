---
title: "Installation Problems"
description: "Fix missing PRFlow commands, an old Python, missing tools and preserved installer files."
---

Match the message you see to an entry below, run its diagnostic command, then apply its fix.

<AccordionGroup>

<Accordion title="PRFlow commands do not appear in Claude Code">

**Symptom:** typing `/prflow:` offers no PRFlow commands, or the client answers that the command is unknown.

Claude Code is the documented client. List what the client has loaded:

```bash
claude plugin list
```

The plugin is `prflow`. The marketplace keeps the older name `devflow-marketplace` on purpose, so that name is not a sign of a stale install. If the plugin is absent, add the marketplace and install it:

```bash
claude plugin marketplace add The01Geek/prflow
claude plugin install prflow@devflow-marketplace
```

Then run `/reload-plugins` or restart Claude Code. If the plugin is present but out of date, refresh both the marketplace and the plugin:

```bash
claude plugin marketplace update devflow-marketplace
claude plugin update prflow@devflow-marketplace
```

</Accordion>

<Accordion title="devflow preflight: Python 3.11+ required (found Python 3.9.6)">

**Symptom:** on macOS the preflight prints a line of this form, even though you believe you installed a newer Python.

macOS ships an older Python as `python3` at `/usr/bin/python3`. On current releases that interpreter is Python 3.9. PRFlow needs Python 3.11 or newer. When a newer Python is installed but the system one comes first on `PATH`, PRFlow still resolves the old one.

Check which interpreter PRFlow will find, and every `python3` on your `PATH`:

```bash
python3 -VV
which -a python3
```

If the first line reports 3.11 or newer, the gap is elsewhere. If it reports 3.9, install a newer Python and put it ahead of `/usr/bin` on your `PATH`. Homebrew installs it as:

```bash
brew install python@3.13
```

Open a new shell, run `python3 -VV` again and confirm the version changed. Then run `/prflow:init` to repeat the check.

<Warning>
Do not delete or replace `/usr/bin/python3`. macOS uses it, and removing it can break other software on the machine. Change the order of `PATH` instead.
</Warning>

</Accordion>

<Accordion title="devflow preflight: missing required tool">

**Symptom:** the preflight prints one or more `devflow preflight:` lines and exits non-zero.

PRFlow requires working `git`, `gh`, `jq` and Python 3.11 or newer reachable as `python3`. Run the check the supported way:

```
/prflow:init
```

Initialization scaffolds the repository files and then runs the bundled preflight for you, reporting each gap with its remedy. The scaffold it already wrote stays in place even when the preflight reports a gap.

On a GitHub Actions runner, or in a repository that commits the vendored plugin tree, the same check is available directly:

```bash
.prflow/vendor/prflow/lib/preflight.sh
```

Install every dependency the check reports. A missing PyYAML is advisory on a local run: the preflight prints `devflow preflight: required dependencies present; PyYAML advisory (see above).` and still exits 0, but one severity helper is degraded until you install it:

```bash
python3 -m pip install PyYAML
```

Name the package. Do not install from a requirements file, because that path resolves against your own working directory and installs your project's dependencies instead.

</Accordion>

<Accordion title="Windows has Python but no python3 command">

**Symptom:** the preflight prints `devflow preflight: no working 'python3' on PATH, but a compatible Python (>=3.11) is available as ...`.

Confirm which Python the shell can reach:

```bash
py -3 -VV
python -VV
```

If either reports 3.11 or newer, install the supported `python3` shim so PRFlow's helpers resolve it:

```bash
.prflow/vendor/prflow/scripts/provision-python3-shim.sh --apply
```

Run the preflight again. The provisioner refuses to create a shim when no compatible interpreter exists, so a refusal means you still need a newer Python.

</Accordion>

<Accordion title="Windows resolves the wrong gh or jq">

**Symptom:** the preflight reports no working `gh` or no working `jq`, and names a resolved path that does not execute. A non-executable shim shadowing the real tool causes this.

Show every candidate the shell can see:

```bash
which -a gh
which -a jq
```

PRFlow probes `gh` and `gh.exe`, and likewise `jq` and `jq.exe`, and picks the first one that actually runs. Set an override when `PATH` still selects the wrong executable:

```bash
export DEVFLOW_GH=gh.exe
export DEVFLOW_JQ=jq.exe
```

An override is used verbatim and is never probed, so point it at an executable you have confirmed. If the shell helpers are not running under a POSIX bash at all, install WSL bash, Git Bash or MSYS2 bash and set `DEVFLOW_BASH` where you invoke PRFlow.

</Accordion>

<Accordion title="A Windows helper crashed on an em-dash or emoji">

**Symptom:** a PRFlow Python helper stops with a character-encoding error on a Windows host.

PRFlow's own Python helpers force their standard output and standard error to UTF-8 on their entry path, so non-ASCII output no longer raises an encoding error. If you see this, you are running an older version. Update the plugin:

```bash
claude plugin update prflow@devflow-marketplace
```

On Linux and macOS the default codec is already UTF-8, so this never applies.

</Accordion>

<Accordion title="The installer preserved a file instead of updating it">

**Symptom:** installer output names a file as `PRESERVED`, and a new file appears beside it with a `.prflow-new` suffix.

The installer could not prove the existing file was untouched since it wrote it, so it left your copy in place and wrote the new bytes to the sidecar.

<Steps>
  <Step title="Compare the two files">
    ```bash
    diff <path> <path>.prflow-new
    ```
  </Step>
  <Step title="Merge the changes you want into your maintained file">
    Keep your local edits. Take the new behavior from the sidecar.
  </Step>
  <Step title="Delete the sidecar">
    ```bash
    rm <path>.prflow-new
    ```
    Never commit a sidecar. A committed sidecar is dead weight and confuses the next update.
  </Step>
  <Step title="Re-run the installer in apply mode">
    ```bash
    DEVFLOW_REF=<same-ref> bash devflow-install.sh --apply
    ```
    Merging or adopting a sidecar changes the file's bytes, so the digest the installer recorded for it is now stale. For a workflow the cloud implement gate depends on — `.github/workflows/devflow-implement.yml`, the `setup-project-env` action, or `.prflow/lint-manifest.json` — a stale `.prflow/install-state.json` marker makes the implement run refuse to start on every run until you re-apply. Re-running the installer in apply mode (`--apply`, or `DEVFLOW_APPLY=1` for a `curl | bash` invocation) rebinds the marker to your merged bytes. The apply that preserved the file already warned you of this and named each affected sidecar.
  </Step>
</Steps>

If every file was preserved, Python probably could not run during the update, so the installer could not compare anything. Fix Python, then run the update again for a real comparison.

</Accordion>

</AccordionGroup>

## Related Articles

- [Requirements](/docs/getting-started/requirements)
- [Installation](/docs/getting-started/installation)
- [Initialization](/docs/getting-started/initialization)
- [Updates](/docs/getting-started/updates)

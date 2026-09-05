---
title: "Cloud Setup"
description: "Configure cloud authentication, repository settings and runtime provisioning."
---

Complete the secrets, variables and repository settings a first PRFlow cloud run needs.

## Add Model Authentication

The default Anthropic route needs one repository or environment secret:

```text
CLAUDE_CODE_OAUTH_TOKEN
```

Add it under **Settings → Secrets and variables → Actions → Secrets**. GitHub's built-in `GITHUB_TOKEN` handles GitHub operations and needs no setup.

<Note>
  A fully provider-routed installation can use `DEVFLOW_PROVIDER_API_KEY` instead. Route every active section before you remove `CLAUDE_CODE_OAUTH_TOKEN`. A partly routed installation may need both secrets, because each section chooses its route independently. See [Providers](/docs/configuration/providers).
</Note>

## Review Repository Configuration

The installer creates `.prflow/config.json`. Commit it, because the workflows read it from the repository, not from your machine.

At minimum, review:

- `base_branch` and `claude_model`.
- `prflow.allowed_users` and `prflow.allowed_bots`, which decide who may start a run.
- The `setup` block, for runtimes and install commands.
- `prflow.allowed_tools` and `prflow_implement.allowed_tools`, for repository-specific commands.
- `workflows.prflow`, which enables the shipped command and implementation paths.

Running `/prflow:init` after an installation or an upgrade is recommended. It adds newly scaffolded settings without replacing values you already set, detects common project tools, and — when the config enables a workflow tier — runs `install.sh --apply` itself to place or refresh the cloud-tier `.github/workflows/` files, so you can initialize and install the workflows in one step.

## Provision the Runtime

PRFlow prepares the runner in this order:

1. Set up Python.
2. Set up Node.js.
3. Set up PHP.
4. Start the service containers named in `setup.services`, using Docker.
5. Run each `setup.install` line from the repository root.

Keep Python 3.11 or newer and PyYAML available even in a project that is not written in Python, because PRFlow's own cloud helpers need them.

<Warning>
  Provisioning a command does not grant the agent permission to run it. Add the command to the correct allowlist as a separate step. See [Runtime Setup](/docs/configuration/runtime-setup) and [Tool Permissions](/docs/configuration/tool-permissions).
</Warning>

## Optional GitHub App

The default path needs no GitHub App. Add one when a cloud implementation run has to push changes under `.github/workflows/`, when you want a dedicated automation identity or when a configured stall backstop has to post a resume comment that starts another run.

| **Kind** | **Name** |
| --- | --- |
| Repository or organization variable | `DEVFLOW_APP_ID` |
| Repository or organization secret | `DEVFLOW_APP_PRIVATE_KEY` |

Install the App on the repository with `Contents: write`, `Workflows: write`, `Pull requests: write`, `Issues: write` and `Actions: read`.

An unset App falls back to `GITHUB_TOKEN`. A configured but invalid App fails loudly at the token-creation step.

## Optional Reviewer App

This is a second, separate GitHub App, used only by the `/prflow:review` comment command.

| **Kind** | **Name** |
| --- | --- |
| Repository variable | `DEVFLOW_REVIEWER_APP_ID` |
| Repository secret | `DEVFLOW_REVIEWER_PRIVATE_KEY` |

Install it on the repository with a narrower permission set than the primary App: `Contents: read`, `Issues: read`, `Pull requests: write` and `Actions: read`. It reads the repository, the issue and CI results, and it posts comments and formal reviews. It cannot push.

Why a second App exists: GitHub does not let an identity approve or request changes on its own pull request. When the same identity both authors a pull request and reviews it, the formal review cannot be recorded.

<Warning>
  **If you do not configure this App, review attribution falls back to the default Actions identity, `github-actions[bot]`.** An approval from `github-actions[bot]` does not satisfy a branch-protection rule that requires approving reviews. Configure the reviewer App if you rely on that rule.
</Warning>

Two details are easy to miss:

- `/prflow:review-and-fix` and `/prflow:pr-description` do not use the reviewer App. They push or author content, so they stay on the primary App token.
- Both halves of the pair matter, and they fail differently. If the **variable** is missing or misspelled, the reviewer step is skipped silently, exactly as if you had chosen not to configure it. If the variable resolves but the **secret** is wrong, the step fails loudly.

## Why these settings are still called `DEVFLOW_*` — and what happens if you rename them

The product was renamed DevFlow → PRFlow, and the rename stopped at the repository's own
files: the state directory, the vendored plugin path and the config keys moved, and
`/prflow:init` migrates all four together. The **variables, secrets and environment
overrides below did not move**, and they are not going to move on their own.

They live outside the repository — in GitHub's settings and in your shell profile — so
nothing PRFlow ships can migrate them. More to the point, **nothing in PRFlow reads a
`PRFLOW_*` equivalent**: every one of these names is read under its `DEVFLOW_` spelling
and under no other. So renaming one is not a migration. It is a deletion.

**It is also, in almost every case, a *silent* deletion.** GitHub has no concept of "this
variable used to be called something else": an unresolvable `vars.X` evaluates to the
empty string, which is exactly what a variable you deliberately never configured
evaluates to. Every gate that reads one takes its "not configured" arm, every job
falls back to its default, and the run goes **green** — under a degraded identity, or on
a runner you did not choose. The advisory below therefore states, for each name, what
renaming it actually does.

If the brand inconsistency bothers you, the answer is a future PRFlow release that
accepts both spellings — not a rename you perform yourself today.

{/* prflow-env-freeze:begin freeze_version=1 sha256=e70e9b7b2538a8c12229e6aa8e311ed66d4afdbbd5c207ecdebb42d97c879e52 (generated by lib/generate-env-freeze-advisory.py -- do not hand-edit; source: lib/rename-map.json frozen.env_identifiers) */}
> **These names are frozen. Do not rename them.** PRFlow reads each one under its `DEVFLOW_` spelling and under no other spelling — there is no `PRFLOW_*` equivalent anywhere in the plugin. Renaming one of these does not move a setting; it removes it.

**The two GitHub App pairs fail asymmetrically.** The asymmetry inverts what a careful consumer would guess. Rename the SECRET alone and the mint step fails loudly — you find out immediately. Rename the VARIABLE alone and nothing fails: the mint is gated on `vars.<NAME> != ''`, an unresolvable name reads exactly like `deliberately not configured`, so every job falls back to `steps.app-token.outputs.token \|\| secrets.GITHUB_TOKEN` and the run goes GREEN under a degraded identity. Rename BOTH — the natural thing to do, since they are one setting in the consumer's head — and the variable's silent skip gates off the secret's loud guard, so the loud half never runs. The safe rename order is therefore the one nobody would guess, which is the reason this block exists.

#### Set in GitHub — repository or organization settings

You set these under **Settings → Secrets and variables → Actions**. PRFlow can only read them.

| Identifier | Where you set it | Renaming it fails | What renaming it does |
|---|---|---|---|
| `DEVFLOW_APP_ID` | repository or organization variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent | Silent feature loss, the largest blast radius here. Every mint gate reads `vars.DEVFLOW_APP_ID != ''`, so an unresolvable name turns every gate false and every consumer falls back to `steps.app-token.outputs.token \|\| secrets.GITHUB_TOKEN`. The run stays green. What breaks is all downstream and none of it names the cause: pushes touching `.github/workflows/` are rejected with `refusing to allow a GitHub App to create or update workflow ... without workflows permission` (which reads as a missing App permission, and the App permission is fine); the credential refresher still reports `credential refresher started (detached)` while its empty-input arm writes `cannot mint` into a redirected log nobody reads, so long implement runs die on an expired token with no trace; and PR authorship and review attribution move to `github-actions[bot]`, which does not satisfy a branch-protection required-approval rule. |
| `DEVFLOW_APP_PRIVATE_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud, but only while its paired variable still resolves | The mint step fails loudly with an unusable private key — provided `vars.DEVFLOW_APP_ID` still resolves and the step therefore runs at all. Rename the variable as well and the gate is already false, the mint never executes, and this loud guard is gated off: see `pair_asymmetry`. |
| `DEVFLOW_REVIEWER_APP_ID` | repository variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent | Silent identity reversion. This is the GATING half of the reviewer pair: unresolvable, the reviewer mint is skipped exactly as if you had chosen not to configure a reviewer App, and review attribution falls back to the default token. Nothing reports it, and a branch-protection rule that requires an approval from a non-`github-actions[bot]` identity silently stops being satisfiable. |
| `DEVFLOW_REVIEWER_PRIVATE_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud, but only while its paired variable still resolves | The reviewer mint fails loudly with an unusable private key — provided `vars.DEVFLOW_REVIEWER_APP_ID` still resolves. Rename the variable too and the gate is false, the mint is skipped, and the loud guard never runs: see `pair_asymmetry`. |
| `DEVFLOW_PROVIDER_API_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud on the provider path; unread otherwise | If a config section sets `provider`, the run refuses with an `::error::` naming DEVFLOW_PROVIDER_API_KEY — the one cloud row that fails loudly on its own. If no section routes through a third-party provider the secret is never read, so a rename is invisible until the day you opt into provider routing, at which point the error names a secret you believe you have set. |
| `DEVFLOW_RUNNER` | repository or organization variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent **⚠ highest severity** | SILENT RUNNER RELOCATION, and the highest-severity outcome in this table. Unresolvable, the expression takes its `\|\| 'ubuntu-latest'` arm and EVERY job silently moves to a GitHub-hosted runner. That same job carries `secrets.DEVFLOW_APP_PRIVATE_KEY` and `secrets.DEVFLOW_PROVIDER_API_KEY` in its environment — so a consumer who self-hosts for network isolation or compliance has their GitHub App private key and their model-provider API key executed OUTSIDE the boundary they chose self-hosting for. Nothing errors, no job fails, and no log line names the cause; the only visible difference is the runner label in a page nobody re-reads after setup. Note the contrast with a MIS-SET value: a `DEVFLOW_RUNNER` that begins `[` but is not valid JSON fails loud at evaluation time. It is the name going missing, not the value being wrong, that is silent. |
| `DEVFLOW_LIGHT_RUNNER` | repository or organization variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent | SILENT RUNNER RELOCATION of the light jobs only. The name going missing does not error: each light expression takes its DEVFLOW_RUNNER-chain fallback arm, so the light jobs revert to wherever DEVFLOW_RUNNER points (or ubuntu-latest when that too is unset) — exactly the pre-opt-in placement. The visible symptom is a helper job billing an 8-core minute again, never a job failure or a log line naming the cause. As for DEVFLOW_RUNNER, a MIS-SET value that begins `[` but is not valid JSON fails loud at evaluation time; it is the name going missing, not the value being wrong, that is silent. |

#### Set on your machine — shell profile or install one-liner

You set these in your own environment. Every one resolves through a `${NAME:-…}`-style default, so a name that stops resolving is byte-identical to one that was never set.

| Identifier | Where you set it | Renaming it fails | What renaming it does |
|---|---|---|---|
| `DEVFLOW_BASH` | environment variable — your shell profile, or the invocation that launches the runner | silent | Silent reversion to whichever bash the host happens to select. On a healthy POSIX-bash host that is a no-op, so the rename looks successful; on the Windows host the override existed for, the shell helpers go back to running under whatever the launcher picks, and the preflight remedy naming WSL/Git Bash/MSYS2 bash returns. |
| `DEVFLOW_GH` | environment variable — your shell profile | silent | Silent PATH reversion, and the worst kind of silent: on a host where the probe already finds a working `gh` the rename changes nothing observable, so the consumer concludes it worked. On the Windows/WSL host the override existed for, it silently restores the shadowing-`gh` bug the override was added to route around — a present-but-unrunnable `gh` shim is selected again, and every `gh` call degrades to its best-effort empty-result path. |
| `DEVFLOW_JQ` | environment variable — your shell profile | silent | Silent PATH reversion, identical in shape to DEVFLOW_GH: a no-op on a host whose probe already resolves a working `jq`, so the rename appears to have worked, and a silent return of the shadowed-binary problem on the host that needed the override. |
| `DEVFLOW_REF` | environment variable (install-time) — the install one-liner — `DEVFLOW_REF=<tag> bash devflow-install.sh` | silent | Silent un-pin. Unresolvable, install.sh takes its `:-main` default and clones mutable `main` instead of the tag you named. The install succeeds, reports a version, and stamps `prflow_version` — with a ref you did not choose. A consumer pinning a known-good release to avoid an upgrade gets the upgrade, and the only evidence is the version the installer echoes. *Dual role:* Also an INTERNAL input: `.github/actions/vendor-plugin/action.yml` assigns DEVFLOW_REF for vendor-slice.sh's fetch branch, sourced from the consumer's `prflow_version`. That internal producer never reaches install.sh, so the name is consumer-facing here and internal there. It is not purely one or the other. |
| `DEVFLOW_SRC` | environment variable (install-time) — the install one-liner — `DEVFLOW_SRC=<dir> bash devflow-install.sh` — to install from an already-materialized plugin tree instead of cloning | silent | Silent reversion to a network clone. Unresolvable, install.sh's `[ -n ... ]` guard is false and it clones from GitHub instead of installing from the local tree you pointed at — an air-gapped or offline install then fails to fetch, and a pinned local tree is silently replaced by whatever the clone resolves. *Dual role:* Also set INTERNALLY by `/prflow:init`'s workflow-install step, which passes the installed plugin tree as DEVFLOW_SRC so install.sh installs from it with no network clone. That producer does reach install.sh, but a consumer running install.sh by hand still sets it themselves, so the name is consumer-facing here and internally supplied there. |
| `DEVFLOW_VENDOR` | environment variable (install-time) — the install one-liner — `DEVFLOW_VENDOR=1 bash devflow-install.sh` | silent | Silent mode reversion to a thin install. The plugin tree stops being committed and is fetched at runtime instead, which is the opposite of what a consumer who set this wanted — typically an air-gapped or supply-chain-pinned repository. The installer says `thin install: the plugin is fetched at runtime`, which is a truthful line that reads as normal output rather than as a setting having been lost. |
| `DEVFLOW_DRY_RUN` | environment variable (install-time) — the install one-liner — `DEVFLOW_DRY_RUN=1 bash devflow-install.sh` | silent, and the only row that WRITES as a result | The only name here whose rename causes a WRITE. On a FIRST-TIME install the default mode is apply, so the preview you explicitly asked for silently becomes an apply and the installer writes to your repository. (On an existing install the default is already preview, so there the rename is a silent no-op.) The equivalent flag `--dry-run` is unaffected — an unknown flag is rejected outright, which is exactly the loudness the environment channel lacks. |
| `DEVFLOW_APPLY` | environment variable (install-time) — the install one-liner — `DEVFLOW_APPLY=1 bash devflow-install.sh` | silent | Silent no-write on an upgrade. An existing install defaults to preview, so the upgrade you believe you applied only previewed: the repository is unchanged and keeps running the previous workflows and the previous pin. The run exits 0 and its last line is the ordinary dry-run notice. The equivalent `--apply` flag is unaffected. |

Not on this list and wondering why: `DEVFLOW_PROMPT_EXTENSION_ROOT` is written by the cloud workflows that run the review engine and never set by you, and `DEVFLOW_CONFIG_FILE` is an internal seam that has never been published as a consumer setting. Both are recorded with their reasoning in `lib/rename-map.json`.
{/* prflow-env-freeze:end */}

## Run a Smoke Test

Open a throwaway pull request and add this as a comment of its own on the **Conversation** tab:

```text
/prflow:review
```

You should see three things: a 🚀 reaction added to your own comment as an acknowledgement, a new workflow run under the **Actions** tab and a progress comment on the pull request that PRFlow rewrites as it works. The progress comment ends with the full report and an APPROVE or REJECT verdict.

The reaction is best effort. Its absence is a weak signal on its own, so check the **Actions** tab before you conclude that nothing started.

If nothing happens at all, the most common causes are an unauthorized commenter and a comment that is not on a line of its own. See [Cloud Triggers](/docs/runs/cloud/triggers) and [Cloud-Run Problems](/docs/troubleshooting/cloud-runs).

For implementation, use a low-risk issue and follow [Cloud Triggers](/docs/runs/cloud/triggers).

# PRFlow — agentic coding that ships on real codebases

[![PRFlow — Ship the PR, not the cleanup. A Claude Code plugin that turns one request into one merge-ready pull request across four phases: Setup (/prflow:create-issue), Implement (/prflow:implement), Review & fix (/prflow:review-and-fix), and Document (/prflow:docs).](docs/ship-pr.png)](https://prflow.ai/)

[![Release verification](https://github.com/The01Geek/prflow/actions/workflows/distribution-verify.yml/badge.svg)](https://github.com/The01Geek/prflow/actions/workflows/distribution-verify.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Built on Claude Code](https://img.shields.io/badge/built%20on-Claude%20Code-d97757.svg)

**AI coding agents dazzle on a demo repo, then stall on a real ticket in a large production codebase.** PRFlow is the Claude Code plugin that closes that gap — it carries one feature request all the way to a **complete, tested, reviewed, documented pull request**, so you do the final review and merge, not the cleanup.

<a name="install"></a>

## Quick start

> [!TIP]
> **Just ask your agent.** Paste this into Claude Code and it handles step 1 for you — the install, the setup, and the PATH dependencies `/plugin install` doesn't cover. Then ship your first PR with step 2.
>
> ```text
> Read https://github.com/The01Geek/prflow#quick-start and install PRFlow and its dependencies.
> ```

**1. Install and set up** — run these commands in order:

```bash
claude plugin marketplace add The01Geek/prflow
claude plugin install prflow@devflow-marketplace
claude /prflow:init   # launches Claude Code and scaffolds your config
```

**2. Ship a PR** — turn a feature request into a reviewed, documented pull request:

```text
/prflow:create-issue <user_story>
/prflow:implement <issue_number>
```

The local tier runs **with zero configuration** — every value already has a built-in default. `/prflow:init` is recommended: it registers the marketplace so Claude Code keeps the plugin auto-updated (an unpinned registration that tracks the plugin repo's default branch) and writes a `.prflow/config.json` you can tweak. See **[Installing and updating](https://prflow.ai/docs/getting-started/installation)** for the full options and [Requirements](#requirements) for the handful of tools it expects on your PATH.

## Why PRFlow

- **Ships the whole PR, not a fragment** — grounded in *your* architecture and patterns, with the tests the change actually needs, on production code. [How it's different →](#how-its-different)
- **Review that fixes what it finds — and audits itself** — the review-and-fix loop applies fixes and re-reviews until it approves, then a structurally-independent **shadow pass** re-checks the approval. [Skills and agents →](#skills-and-agents)
- **Docs stay in sync** — internal docs, external docs, and release notes kept aligned with the code in the same run.
- **It learns every week** — a [retrospective loop](#the-self-improving-loop) reads the trail of merged PRs and files human-reviewed issues that prevent the next recurring failure.
- **Zero-config to start** — the local tier runs entirely inside Claude Code with no infrastructure; an optional [cloud tier](https://prflow.ai/docs/runs/cloud/setup) runs it autonomously on GitHub.

> ▶ **[Read the PRFlow documentation →](https://prflow.ai/docs)**

<details>
<summary>Contents</summary>

- [How it's different](#how-its-different)
- [Who it's for](#who-its-for)
- [The workflow, end to end](#the-workflow-end-to-end)
- [Requirements](#requirements)
- [Skills and agents](#skills-and-agents)
- [Project configuration](#project-configuration)
- [The self-improving loop](#the-self-improving-loop)
- [Learn more](#learn-more)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)

</details>

## How it's different

The thesis isn't code generation — it's **disciplined, auditable AI software delivery at production scale.** A single LLM pass is variable; PRFlow's architecture is built around *not trusting any single pass*.

- **✓ Works on real codebases, not just pet projects.** Unlike a raw agent that drafts part of the change and stops, PRFlow delivers the full round — grounded in your architecture and patterns, with the tests the change needs — on production code.
- **✓ Review that fixes what it finds.** It doesn't just hand you a list. The **review-and-fix loop** applies the fixes and re-reviews, iterating until it approves — backed by independent verification checklists, a panel of specialized reviewers, mechanical corroboration, and a **shadow pass** (a second, structurally-independent review that re-checks the approval before it stands). The shadow pass **narrows the gap to a standalone review; it never closes it.**
- **✓ It learns.** Every run leaves a trail — a **PRFlow Reflection** logging assumptions and anything unverified, an **effectiveness trace** of which steps earned their keep, living docs, and a **weekly retrospective** that opens the smallest fix preventing the next recurring failure.

PRFlow delivers a **review-ready** PR for your final human review and merge — it is **not auto-merged**.

## Who it's for

A developer or team shipping in a **large, business-grade codebase**, already on Claude Code + GitHub, who wants agentic coding to complete a real ticket — branch, tests, review, docs — not just draft a snippet.

## The workflow, end to end

The intended way to drive PRFlow — from a feature request to a reviewed pull request:

```text
   you: a feature request
       │
/prflow:create-issue   →  explore codebase → implementation options → detailed GitHub issue
       │
/prflow:implement      →  architect → code → build/test → /prflow:review-and-fix loop → /prflow:docs
       │
/prflow:review         →  (optional) independent, comprehensive check → PR ready for developer hand-off
       │
   you: final review & merge
```

1. **Create the issue.** `/prflow:create-issue Add CSV export to the reports page` interviews you until the issue is unambiguous, shows you the draft, and files it **only after you confirm**. Say it lands as **#42**.
2. **Start implementation.** Run `/prflow:implement 42` in Claude Code — or, on the cloud tier, comment `/prflow:implement 42` on the issue (`gh issue comment 42 --body '/prflow:implement 42'`). Because *you* posted the comment, GitHub fires the workflow natively (no `@claude`, bot comment or PAT needed — see [cloud triggers](https://prflow.ai/docs/runs/cloud/triggers#implement-an-issue)).
3. **PRFlow implements it.** It creates a branch, plans against your codebase, writes the code and tests, opens a **draft PR**, self-reviews with `/simplify`, runs `/prflow:review-and-fix`, files follow-up issues for deferred findings, updates the docs, and flips the PR to **ready**.
4. **Review and merge.** On the cloud tier, `/prflow:review` runs as a gate and posts its verdict on the PR. You do the final human review and merge.

> The cloud tier (steps 2–4 running automatically on GitHub) needs only a `CLAUDE_CODE_OAUTH_TOKEN` secret **by default** (routing a workflow through an optional third-party model provider adds one more, `DEVFLOW_PROVIDER_API_KEY`) — see [Cloud setup](https://prflow.ai/docs/runs/cloud/setup). Everything else runs locally inside Claude Code with no infrastructure.

## Requirements

**Local tier** — these must be on your PATH (in a checkout of this repo, `bash lib/preflight.sh` checks all of them for you):

- **`git`** and **[`gh`](https://cli.github.com)** (GitHub CLI, authenticated via `gh auth login`) — you most likely already have these.
- **`jq`** — JSON wrangling inside the skills.
- **Python 3.11+** — the config resolver and most helper scripts are Python. Config itself is JSON, read with the standard library alone.
- **PyYAML 6 or newer** — `python3 -m pip install 'PyYAML>=6'`. **The step people miss:** `/plugin install` never runs `pip`, so install it yourself. Name the package rather than reaching for `-r requirements.txt`: that path resolves against *your* working directory, not the plugin cache, so in a Python project it installs your project's dependencies instead. On the local tier PyYAML is an **advisory** dependency — `bash lib/preflight.sh` reports a missing PyYAML and still exits 0 (see below).

`git`, `gh`, `jq` and `python3` are not optional — the core skills call them directly, and a missing one is a hard stop. Shell helpers avoid GNU-only flags, so macOS/BSD work without GNU coreutils.

**PyYAML is on the list, but it is the one item that degrades rather than breaks** — worth knowing before you block an install on it. Exactly one runtime helper imports it, `match-deferrals.py`, and only lazily, on the path where a pull-request body already carries a deferred-findings block. Without PyYAML that helper exits with an error the review engine logs and steps over, continuing with **all findings intact**; what you lose is the severity demotion of findings you previously deferred, which fails in the safe direction — it surfaces more, never fewer findings. That safety is not free: because the re-surfaced findings are re-fixed (not merely reported) in `/prflow:review-and-fix` and in `/prflow:implement`'s inline fix loop, a PyYAML-less run can churn on work a prior run deliberately deferred behind follow-up issues. Implement, review, docs and config all work without it. On the local tier `bash lib/preflight.sh` reports a missing PyYAML as an **advisory** gap and exits 0 — it prints a distinct advisory final line naming the `pip install` remedy rather than treating the gap as a hard stop. (The test suite, CI, and the cloud tiers still require it.)

On **Windows** any POSIX **bash** works — **WSL bash**, **Git Bash**, or **MSYS2 bash** (PRFlow mandates none); point PRFlow at the one you want with **`DEVFLOW_BASH`**, and in a checkout of this repo `bash lib/preflight.sh` prints a `devflow-bash:` breadcrumb confirming which bash is in use (a host with *no* POSIX bash at all is out of scope). A non-executable `gh` or `jq` shim can also shadow the real binary on `PATH`; PRFlow resolves the first `gh`/`gh.exe` (and `jq`/`jq.exe`) that actually runs (execution-verified via the shared `lib/resolve-bin.sh` resolver), and you can force a specific binary by setting **`DEVFLOW_GH`** / **`DEVFLOW_JQ`** to the working one. Windows-form paths are normalized to the running shell's POSIX form by `lib/normalize-path.sh`. PRFlow's first-party Python helpers also force their stdout/stderr to UTF-8 on a non-UTF-8 default codec, so an em-dash or emoji in a helper's output never crashes it on a Windows host (e.g. a cp1252 codec). See [Installation problems](https://prflow.ai/docs/troubleshooting/installation) for Windows and missing-dependency guidance.

**Cloud tier** — nothing to install on your machine; the GitHub Actions runner provisions its own toolchain. By default every job runs on `ubuntu-latest`, but the runner is configurable via the `DEVFLOW_RUNNER` repository/organization variable (a bare label or a JSON label array), which dispatch-enables **self-hosted / Windows runners** — read [Cloud setup](https://prflow.ai/docs/runs/cloud/setup) before treating a non-Linux runner as production-ready.

### Withheld: automatic review on pull request

One cloud-tier feature was **withdrawn before this release rather than shipped**: the
workflow that ran `/prflow:review` automatically on every pull request. Reviewing it
turned up a design flaw we chose not to patch — its caller triggered on `pull_request`,
called a reusable workflow with `secrets: inherit`, checked out the pull-request head,
and had no actor-authorization gate, so a fork could reach a privileged job. Rather than
harden a feature we were not confident in, we removed it. The two issues describing the
flaw ([#930](https://github.com/The01Geek/prflow/issues/930),
[#920](https://github.com/The01Geek/prflow/issues/920)) are closed as *not planned*
because **the feature they describe no longer exists** — not because the problem was
dismissed.

**If you are installing PRFlow now, there is nothing to do.** A fresh install never
receives those workflow files, so the flaw is not reachable. Review still works: a
repository collaborator comments `/prflow:review` on a pull request and the review runs,
gated by an actor-authorization check. An outside fork contributor cannot self-trigger one.
You can *additionally* configure an automatic `/prflow:review` request after CI passes; see
[Cloud triggers](https://prflow.ai/docs/runs/cloud/triggers). Automatic requests must exclude
fork pull requests before any token is minted.

**If you installed an earlier version that did ship the tier,** you still have the files
and re-running the installer deliberately leaves them alone. To remove them, run
`install.sh --apply --remove-withheld-review-tier`, which deletes
`.github/workflows/devflow-review.yml`, `devflow-runner.yml` and `telemetry-push.yml` and
sets `workflows["prflow-review"]` to `false` in `.prflow/config.json`. Then remove the
`Devflow Review` context from any branch protection rule or ruleset that requires it —
no installer can do that step for you, and skipping it wedges every later pull request
behind a required check nothing will report. After removal, use the supported review commands
in [Cloud triggers](https://prflow.ai/docs/runs/cloud/triggers).

## Skills and agents

| Skill | What it does |
|---|---|
| `/prflow:implement <issue#>` | Full 4-phase lifecycle: issue → branch → plan → implement → test → draft PR → `/simplify` → `/prflow:review-and-fix` → file follow-up issues → docs → ready PR |
| `/prflow:review [PR#]` | Comprehensive review — verification checklist + the first-party `prflow:` review agents & the first-party `prflow:requesting-code-review` final-pass reviewer; returns APPROVE/REJECT |
| `/prflow:review-and-fix [PR#]` | `/prflow:review` plus an automatic fix loop (default 5 iterations) that writes a deferrals manifest at exit |
| `/prflow:pr-description [issue#]` | Generate/update the PR description from the branch diff |
| `/prflow:docs` | Orchestrate the three doc steps in one session |
| `/prflow:docs-sync-internal` · `-sync-external` · `-release-notes` | Update internal docs, align external docs, generate release notes |
| `/prflow:docs-verify <topic>` · `-bootstrap-internal` · `-bootstrap-external` | Verify one topic; stand up internal/external docs from scratch |
| `/prflow:create-issue` | Rough idea → well-structured GitHub issue |
| `/prflow:init` | One-time setup: scaffold `.prflow/config.json` + refresh the schema |
| `/prflow:retrospective-weekly` | The weekly self-improvement loop ([details](#the-self-improving-loop)) |

**Agents** (`agents/`): the review-engine trio `checklist-generator`, `checklist-deduper`, and `checklist-verifier` build, dedupe, and verify the review engine's verification checklist; the `/prflow:implement` `code-explorer` and `code-architect` handle discovery and planning; and the five `pr-review-toolkit` reviewers (`code-reviewer`, `comment-analyzer`, `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`) run the deep-dive review passes.

> **Namespacing matters where names collide with built-ins.** `/review`, `/init`, and `/security-review` are *built-in* Claude Code commands — always use the `/prflow:`-prefixed form to reach PRFlow's engine (a bare `/review` reaches Claude Code's reviewer, not PRFlow's). **Local slash commands are `/prflow:` only** — the plugin was renamed from `devflow`, and the old `/devflow:*` local commands do not survive that rename. **Cloud comment triggers still accept both**: a GitHub comment reading `/devflow:implement 42` or `/prflow:implement 42` fires the same workflow, so existing automation and muscle memory keep working there. Either way the trigger is a **bare** comment (no `@claude`), so PRFlow coexists with Anthropic's Claude GitHub App, which owns plain `@claude` mentions and `/security-review`.

> **No companion plugins.** PRFlow declares **zero** companion-plugin dependencies — `/plugin install prflow@devflow-marketplace` resolves on its own, with no `claude-plugins-official` prerequisite and none of the old `dependency-unsatisfied` Errors-tab friction. Every external asset its engine once dispatched is now a first-party PRFlow file: the `pr-review-toolkit` review agents and the `feature-dev` `code-explorer`/`code-architect` subagents under `agents/`, and the `superpowers` final-pass reviewer (`requesting-code-review`) and fix-loop `receiving-code-review` skills under `skills/` — all hard-forked with upstream licenses retained verbatim under `LICENSES/`. See [Installation](https://prflow.ai/docs/getting-started/installation). `/simplify` is a built-in Claude Code skill.

## Project configuration

The local tier needs **no config** — every value has a built-in default. To customize, run `/prflow:init` to scaffold `.prflow/config.json` from PRFlow's shipped template (it never clobbers a config you've filled in) and refresh `.prflow/config.schema.json` (your editor reads it for autocomplete + field descriptions).

Common keys the skills read: documentation paths (`docs.internal`, `docs.external`, `docs.release_notes_file`, `docs.changelog_file`, `docs.labels`), the workpad marker (`prflow.workpad_marker`), the bot allowlist (`prflow.allowed_bots`), the review base (`base_branch`), retrospective settings (`prflow_retrospective.*`), and — cloud tier only — runtime provisioning (`setup.*`) and the plugin ref (`prflow_version`). See [Configuration settings](https://prflow.ai/docs/configuration/settings).

## The self-improving loop

Every bot-authored PR leaves evidence — review comments, post-bot commits, CI signals, workpad state. Once a week, **`/prflow:retrospective-weekly`** reads the accumulated trail, finds failure patterns that recur, and files a **human-reviewed** issue proposing the smallest change that would prevent the next occurrence (a CLAUDE.md tweak, a skill rewrite, a missing doc, a new lint rule). You triage it, and it runs through the normal implement → review pipeline like any other change.

```text
/prflow:retrospective-weekly
```

Run it interactively from the repo root, ideally weekly; it confirms a clean default branch, runs the full pipeline, and prints a status report with the issues to triage. Deterministic scripts handle all scanning, gating, and git/issue mechanics — the LLM is invoked **only** at the two genuine-judgment points (per-PR retrospective and per-pattern issue-spec drafting). The loop **proposes, it does not dispose**: it files one well-formed GitHub issue per actionable pattern and lets the normal implement → review pipeline execute it, rather than auto-editing the repo.

See [PRFlow workflows](https://prflow.ai/docs/workflows) for the supported user-facing workflow guides.

## Learn more

- **[Public documentation](https://prflow.ai/docs)** — installation, workflows, local and cloud runs, configuration and troubleshooting.
- **[Installing and updating](https://prflow.ai/docs/getting-started/installation)** — supported clients, initialization and updates.
- **[Cloud setup](https://prflow.ai/docs/runs/cloud/setup)** — credentials and repository setup for autonomous runs.
- **[Review and fix](https://prflow.ai/docs/workflows/review-and-fix)** · **[Review-agent configuration](https://prflow.ai/docs/configuration/review-agents)** · **[Cloud triggers](https://prflow.ai/docs/runs/cloud/triggers)**
- **[Releases](https://github.com/The01Geek/prflow/releases)** — release history, with notes at [prflow.ai](https://prflow.ai/release-notes).

## Repository layout

```text
.claude-plugin/   # plugin.json (no companion-plugin dependencies) + marketplace.json (this repo is its own marketplace)
skills/           # one SKILL.md per command (/prflow:implement, /prflow:review, /prflow:docs, …)
agents/           # 15 subagents: the review-engine trio, the implement-phase agents, and 5 pr-review-toolkit reviewers
scripts/          # Python + shell CLIs (workpad.py, config-get.sh, match-deferrals.py, …)
lib/              # retrospective-loop helpers (*.sh, *.jq) and preflight.sh
.github/          # optional cloud tier: workflows + composite actions (incl. vendor-plugin)
.prflow/          # config.example.json, config.schema.json, tool-presets.json, lint-manifest.json, install-state.json
.release/         # per-release provenance: source.json + a SHA-256 for every published file
docs/             # source for https://prflow.ai
LICENSES/         # third-party licences for the vendored skills and agents
install.sh        # one-command cloud-tier install/update (thin by default; DEVFLOW_VENDOR=1 to commit the plugin)
```

Skills reference bundled helpers via the portable single-statement anchor (`$CLAUDE_SKILL_DIR` on Claude Code, with a runner-reported base-directory fallback on other agentic CLIs) so they resolve from any install location and runner.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Daniel Radman.

**Third-party components.** PRFlow redistributes several agents and skills authored by others,
which remain under their own upstream licenses (Apache-2.0 from Anthropic's `feature-dev` and
`pr-review-toolkit` plugins; MIT from Jesse Vincent's `superpowers`) and have been modified by
PRFlow. [`LICENSES/README.md`](LICENSES/README.md) maps each vendored file to its upstream
project, license, and copyright holder; the full license texts are in [`LICENSES/`](LICENSES).

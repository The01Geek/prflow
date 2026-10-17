# Security Policy

## Reporting a vulnerability

If you discover a security issue in PRFlow, please report it privately rather
than opening a public issue. Use GitHub's **private vulnerability reporting**
(the "Report a vulnerability" button under the repository's *Security* tab), or
email **daniel@radman.ai**. You'll get an acknowledgement within a few days.

Please include reproduction steps and the affected version or commit.

## Scope and considerations

PRFlow runs as a Claude Code plugin and, optionally, as a set of GitHub Actions
workflows. A few areas warrant care:

- **Cloud tier credentials.** The optional GitHub Actions automation uses a
  Claude Code OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) by default. Never commit it.
  Store it as an encrypted GitHub Actions secret. See <https://prflow.ai/docs/runs/cloud/setup>.
  Routing a workflow section through an optional third-party model provider adds
  one more secret, `DEVFLOW_PROVIDER_API_KEY` (the provider API key) — same
  handling: never commit it, store it as an encrypted Actions secret, and prefer
  a key scoped/guardrailed to the intended provider. Review that provider's
  data-retention and training policy before the first run — prompts routed
  through it leave Anthropic's infrastructure.
- **`config.json` is committed, not gitignored.** PRFlow's cloud tier reads it
  from the committed tree, so the scaffolded `.prflow/.gitignore` ignores only
  `tmp/` and leaves `config.json` tracked. Because it is committed, keep secrets
  out of it — it holds only non-secret environment configuration (project/board
  IDs, model names). Store credentials as encrypted GitHub Actions secrets, never
  in `config.json`.
- **In a repository where PRFlow is installed, the retrospective's learnings store is published on the telemetry branch.** The
  retrospective loop's records (`retrospectives.jsonl`, `experiment-records.jsonl`,
  `overrides.json`) and its weekly reports are pushed to `.prflow/logs/learnings/`
  on the telemetry branch (default `prflow-telemetry`), readable by anyone who can
  read the repository; the `.prflow/learnings/` working copy is gitignored. Keep
  host-local and owner-identifying data — operator home-directory paths, account
  names, machine layout — out of them. The corpus is meant to record the bot's
  unsanitized friction (CI-runner paths and repo-relative paths included), so
  `lib/materialize-retrospectives.sh` rewrites operator home-directory prefixes to
  `~` on the merge write path as a backstop; do not rely on it to catch secrets.
- **Skills run shell commands.** PRFlow's skills execute `git`, `gh`, `jq`, and
  bundled Python helpers. Review the skills you install, as you would any plugin.
- **The retrospective loop opens issues and pushes the telemetry branch** on the
  configured repository: its steps save the learnings store to the telemetry branch and
  file each recurring pattern as an issue for human triage. The one-time learnings
  migration (`/prflow:init`, `install.sh --apply`) only stages a removal from the
  default branch for a human to commit.

## Supported versions

PRFlow follows semantic versioning. Security fixes target the latest released
minor version.

---
bump: minor
type: Security
---

- **Provider `env` map keys are now name-filtered before export.** The cloud "Inject provider
  endpoint" step already validated each `providers.<name>.env` key's *shape*; it now also
  refuses the run (fail loud, `::error::` naming the offending key, before any `$GITHUB_ENV`
  write) when a key's name is a credential (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`,
  `AWS_BEARER_TOKEN_BEDROCK`), a name that would shadow the job environment or its Actions
  plumbing (`PATH`, `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_ENV`, `GITHUB_OUTPUT`, `GITHUB_PATH`),
  an interpreter or loader hook that would run code in every later job step (`BASH_ENV`, `ENV`,
  `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES`, `NODE_OPTIONS`, `PYTHONPATH`), or
  `CLAUDE_CODE_SUBAGENT_MODEL` (which flattens the `agent_overrides` review roster to one
  model). The match is case-insensitive. The config schema no longer suggests
  `CLAUDE_CODE_SUBAGENT_MODEL` as an example key. **Action required on upgrade:** a
  `providers.<name>.env` map naming any of the above — including `CLAUDE_CODE_SUBAGENT_MODEL`,
  which the schema recommended until this release — now fails the run until the key is removed;
  use `ANTHROPIC_DEFAULT_HAIKU_MODEL` to map only the background model. (#1781)

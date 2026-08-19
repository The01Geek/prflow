---
bump: patch
type: Security
---

- **Provider `env` map keys are now name-filtered before export.** The cloud "Inject provider
  endpoint" step already validated each `providers.<name>.env` key's *shape*; it now also
  refuses the run (fail loud, `::error::` naming the offending key, before any `$GITHUB_ENV`
  write) when a key's name is a credential (`ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK`), a name that would
  shadow the job environment (`PATH`, `GITHUB_TOKEN`), or `CLAUDE_CODE_SUBAGENT_MODEL` (which
  flattens the `agent_overrides` review roster to one model). The match is case-insensitive.
  The config schema no longer suggests `CLAUDE_CODE_SUBAGENT_MODEL` as an example key. (#1781)

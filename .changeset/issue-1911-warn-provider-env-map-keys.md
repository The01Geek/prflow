---
bump: patch
type: Added
---

- **Warn when a provider `env` map sets a key that silently overrides a dedicated field or the job environment.** The provider-endpoint injection step in the cloud workflows now prints a single `::warning::` when a provider's `env` map names `ANTHROPIC_BASE_URL`, `API_TIMEOUT_MS`, `HOME`, or `RUNNER_TEMP`, naming every matched key. Matching is case-folded and whole-name, mirroring the existing deny guard. The `env` map's value still takes effect — the warning is advisory and never refuses the run — so no existing provider configuration changes behavior. (#1919)

---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` Step 1 now names how to resolve the internal-documentation location, so a run no longer misreads `.docs.internal` as a missing file and reports a false "no documentation."** The Step 1 leg-partition passage previously named the setting as a bare `.docs.internal` token with no resolver, config file, or default — so a run could read it as a filename, find none, and report an established absence. The passage now names `scripts/config-get.sh` reading `.prflow/config.json` with the `docs/internal/` default, states that a resolution yielding no usable location (a non-zero exit, an empty print, or a non-path value) records the documentation leg unestablished rather than an established absence, states the assumed-default behavior when the resolver cannot run at all, and places each leg inside its peer's docs-verify invocation as the `--search-space` operand. (#1763)

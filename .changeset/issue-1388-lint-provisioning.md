---
bump: patch
type: Added
---

- **Provision the bounded lint toolchain before the model runs.** The installer now ships the
  lint manifest and publishes a digest-bound compatibility marker (`.prflow/install-state.json`)
  only after validating the staged tuple of manifest, readers, setup action, and implement
  workflow. `setup-project-env` gains a closed `lint_mode` input (`provision` installs the
  manifest's ShellCheck/Ruff set run-local, digest- and version-verified, before the Claude
  action; `none` does no lint work and validates no manifest; an unknown value is refused), wired
  `none`/`provision`/`none` across `devflow.yml`/`devflow-implement.yml`/`devflow-runner.yml`. The
  review runner hardens its setup invocation by materializing trusted base-ref bytes over the
  composite-action directory before it runs, so the read-only review job executes the base-ref
  action body rather than a PR-head edit, and CI validates and exercises the candidate manifest
  with no repository write credentials. (#1963)

---
bump: patch
type: Changed
---

- **Adopt ruff 0.16.x for Python linting.** The CI ruff pin advances from `0.15.*` to
  `0.16.*` across the coupled workflow pin sites (the `ci.yml` lint and shard jobs and
  `devflow-implement.yml`). `ruff.toml` gains four documented-convention ignores — `TRY004`
  and `SIM115` globally, and `PLC3002`/`SIM117` scoped per-file to `lib/test/**` — carrying
  one-line rationales, and the tree is brought clean under the new version (a mechanical
  `--fix` pass plus by-hand triage of the residual findings). No `exclude`/`extend-exclude`/
  `force-exclude` key is added, so the `#1621` `--no-force-exclude` gate stays meaningful. (#1997)

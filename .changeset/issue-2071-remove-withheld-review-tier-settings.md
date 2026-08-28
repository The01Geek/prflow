---
bump: patch
---

Remove the withheld automatic-review tier's dead configuration settings and correct the internal documentation that still described that tier as live (issue #2071, PR #2081).

`prflow_review.require_up_to_date`, `prflow_review.require_ci_green`, and the whole `prflow_runner` section are not read by anything a fresh install ships, so they are deleted from `.prflow/config.schema.json`, `.prflow/config.example.json`, and this repository's own `.prflow/config.json`. `scripts/detect-project-tools.sh` no longer writes a `prflow_runner` allowlist, and `install.sh` now strips those three settings from a consumer's `.prflow/config.json` on every apply run — fail-closed on a malformed config or a host with no working python3, and preserving every other key including `workflows.prflow-review`. The retained review-trigger helper scripts and `devflow-runner.yml` are unchanged; `lib/rename-map.json` keeps its `devflow_runner` → `prflow_runner` migration mapping and now records the confirmation-gated condition under which those retained helpers may finally be deleted.

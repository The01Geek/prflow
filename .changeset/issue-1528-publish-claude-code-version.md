---
bump: patch
type: Added
---

- **Every live run now publishes its `claude_code_version` from the execution file's `system/init` record.** `scripts/surface-execution-diagnostics.sh` reuses `lib/probe-observation.sh`'s `devflow_probe_cli_version` to read the CLI build directly in-job — no 7-day transcript artifact and no `execution_transcript_artifact_enabled` opt-in — rendering it into the diagnostics block (including the incomplete-run branch that carries an init record but no result event), publishing `claude_code_version` to `GITHUB_OUTPUT`, and emitting a `::notice::` naming the resolved version so a live run records the build it actually ran on. An absent or unreadable init record resolves to the literal `unavailable` — never an empty or zero value — and a `GITHUB_OUTPUT` write failure leaves a stderr breadcrumb rather than a silent empty output, mirroring the sibling `permission_denials_count` channel. Among the init fields only this low-sensitivity version scalar is value-published; the others stay type-only behind `scripts/extract-execution-shape.sh`'s redaction boundary, which is unchanged. (#1786)

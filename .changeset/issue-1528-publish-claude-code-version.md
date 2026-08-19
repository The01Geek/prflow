---
bump: patch
type: Added
---

- **Every live run now publishes its `claude_code_version` from the execution file's `system/init` record.** `scripts/surface-execution-diagnostics.sh` reuses `lib/probe-observation.sh`'s `devflow_probe_cli_version` to read the CLI build directly in-job — no 7-day transcript artifact and no `execution_transcript_artifact_enabled` opt-in — rendering it into the diagnostics block, publishing `claude_code_version` to `GITHUB_OUTPUT`, and emitting a `::notice::` naming the resolved version so a live run records the build it actually ran on. An absent or unreadable record reports the literal `unavailable`, never an empty or zero value. Among the init fields only this low-sensitivity version scalar is value-published; the others stay type-only behind `scripts/extract-execution-shape.sh`'s redaction boundary, which is unchanged. (#1786)

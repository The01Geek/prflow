---
bump: patch
type: Changed
---

- **One provenance signature, one switch, across `/prflow:implement` and `/prflow:create-issue`.** `scripts/render-pr-provenance-line.py` now takes the command name as a required `--command` argument and returns the finished line in Markdown italics, so both commands paste one set of bytes: a draft pull request opened by `/prflow:implement` and an issue created by `/prflow:create-issue` each end with `_Generated via <command> (v<version>[, <model>][, <effort>])_`. The switch that gates the model and effort clause moves from `prflow_implement.publish_model_effort` to `prflow.publish_model_effort`, so one key now governs the clause for every command that emits the line. The old `prflow_implement.publish_model_effort` spelling is read by nothing after this change and nothing reports it as stale, so a repository that had set it to the JSON boolean `false` has its model and effort clause re-enabled with no message — on pull requests as before, and now on issues too — from the first run after the upgrade; move the key to `prflow` to keep it off. (#1810)

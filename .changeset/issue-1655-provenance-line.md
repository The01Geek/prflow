---
bump: patch
---

Name the running plugin version, model, and effort in the implement PR provenance line.

A `/prflow:implement` run's draft PR body now carries a provenance line naming the plugin
build that executed the run — for example `Generated via /prflow:implement (v2.32.70,
claude-opus-5, high)` — with the model and reasoning effort added when they can be
established. A new bundled helper `scripts/render-pr-provenance-line.py` renders the line:
the version from the plugin manifest resolved beside the helper, the effort from
`CLAUDE_EFFORT`, and the model from the session transcript's most recent assistant record.
An unestablished value is omitted rather than guessed, so a run with no readable source
renders the version alone. The new `prflow_implement.publish_model_effort` config key (default
true) lets a repository suppress the model and effort clause while keeping the version.

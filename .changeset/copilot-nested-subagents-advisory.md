---
bump: patch
type: Added
---

- **`/prflow:init` now advises enabling VS Code Copilot's nested-subagent setting.** When the run is under a VS Code Copilot harness, init recommends turning on `chat.subagents.allowInvocationsFromSubagents` (off by default) so a subagent can dispatch its own subagents, giving review agents better context isolation; with it off a subagent silently does that work inline instead of erroring. (#1877)

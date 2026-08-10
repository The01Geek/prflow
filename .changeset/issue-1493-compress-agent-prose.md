---
bump: patch
type: Changed
---

- **Editorially compressed the checklist-trio and feature-dev subagent bodies under the instruction-plus-consequence prose rule.** Trimmed rationale, restated instructions, and consequence-doubling prose from the `checklist-generator`, `checklist-verifier`, `checklist-deduper`, and `code-architect` bodies, while preserving the behavioral rules and machine-consumed output fields those agents rely on. Each dispatched subagent reads less prose per invocation, both here and where the bodies ship to consumers. (#1521)

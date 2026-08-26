---
bump: patch
---

Harden the /prflow:docs router for the tiers it actually runs on: the two config-gate reads become direct leading-token invocations (the former `VAR=$(…)` capture is silently refused by the cloud matcher and worktree-isolated sessions), the prompt-extension load gains the vendored-literal-first three-tier ladder with the unestablished arm, each step now ends in a declared outcome (completed / skipped / failed / unestablished) that the Final Summary reports alongside the carried-forward public-doc impact list, and Step 3's ungated status is stated with its rationale.

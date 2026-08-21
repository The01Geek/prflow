---
bump: patch
type: Fixed
---

- **Reframe the nested-subagent-dispatch constraint as cross-harness portability.** The shadow-review and docs-verify prose previously stated that a subagent cannot dispatch its own subagents as a fixed harness property; nested dispatch is in fact available on some harnesses and withheld on others. The shipped `skills/**` bodies now give cross-harness portability as the reason for keeping dispatch to a single subagent layer and name the failure mode as silent flattening — an absent tool rather than an error — while the internal docs single-home the harness capability table and version facts. (#1879)

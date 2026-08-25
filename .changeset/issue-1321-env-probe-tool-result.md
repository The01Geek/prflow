---
bump: patch
type: Fixed
---

- **`env-propagation-probe-verdict.py` now reads hop one from Action 2's `tool_result` output.** The verdict helper derived hop values only from `tool_use` inputs, where hop one's variable is unexpanded by design, so hop one was reported only if the model's manual echo-back landed — leaving run 30956039324's genuine reading (recorded in Action 2's Bash `tool_result` output) invisible and the verdict stuck at INCONCLUSIVE. `collect` now also reads `tool_result` outputs; the `_OBSERVED` guard is unweakened, since unexpanded instruction text lives only in a `tool_use` input. (#1955)

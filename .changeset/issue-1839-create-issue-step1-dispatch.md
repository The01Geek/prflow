---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` Step 1 now makes its docs-verify peer dispatch executable.** Step 1
  asserted that each leg reaches its peer as a real `--search-space <pathspec>` operand and that
  the dispatch waits synchronously, but gave the orchestrator no form to carry either out — so a
  peer could silently run under the defaults (collapsing the deep-arm leg disjointness) and a
  background fork could die on resume. Step 1 now names the Agent-tool synchronous dispatch form
  (background dispatch excluded, mirroring Step 3.6), instructs the orchestrator to place each
  leg's pathspec as a literal `--search-space <pathspec>` operand in the invocation arguments, and
  requires each peer to confirm in its return the operand it ran under — recording a leg
  unestablished when it does not. The degrade-never-block contract is unchanged. (#1953)

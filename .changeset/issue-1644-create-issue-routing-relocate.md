---
bump: patch
type: Changed
---

- **Relocated the `/prflow:create-issue` reference-routing table off the always-read skill root.** The routing table now lives in a new gated reference, `skills/create-issue/references/degradation-routing.md`, read only when a reference load fails or a predicate-gated fallback fires; the skill root keeps the load contract, the boundary-marker rule, a pointer to the new file, a self-contained terminal-fallback rule, and the five non-degradable invariants. The routing rows move verbatim and the root's load contract is unchanged — the `create-issue-contract` test module confirms each routed reference still resolves and the relocated table is intact — so the command reads roughly 5,000 fewer bytes of prompt (24,690 → 19,926 for the root) with the same behavior. (#1648)

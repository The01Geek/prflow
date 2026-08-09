---
bump: patch
---

Scope the fix loop's always-resident re-read rule to the dispatches its own active reference stamped, so the returns produced by the review engine's own phases, while the loop executes the engine inline, no longer read as re-read triggers — the engine's own phase procedure governs its phases. The loop's own stamped dispatches keep firing the rule, the Step 2.6 shadow fan-out among them, and so does the handback that ends an engine entry. Without the scope the rule could be read as re-reading `loop-control.md` after every dispatch return an engine entry produces.

---
bump: patch
---

Scope the fix loop's always-resident re-read rule to the dispatches its own active reference issued. The rule previously fired after **every** `Agent`/`Task`/`Skill`-tool return while executing a reference, which left it open whether the 10–40 dispatch returns the review engine's own phases produce inside a Step 1 or Step 2.6 engine entry re-read `loop-control.md` each time. The amended rule states its firing scope explicitly and names the review engine's phase entry-gate as what governs those engine-issued returns, so a Phase 3 reviewer's return no longer reads as a fix-loop re-read trigger. The durable-operand contract is unchanged: `current_step`, `current_substep` and `pending_dispatch` remain the step predicate, agent recall is still excluded, and the absent-operand fail-closed arm still applies.

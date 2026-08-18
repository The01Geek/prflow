<!-- prflow:implement-ref step=2.3.1 file=skills/implement/references/sweep-2-3-1-orphaned-setup.md start -->

#### 2.3.1 Orphaned-setup sweep (mandatory whenever the change deletes code)

Removing a call site, a UI block, a branch, or a whole function almost always strands the *setup lines* that fed it — a service-locator/dependency fetch, a query or record lookup, a computed local, an import or `use` clause — whose only consumer was the code you just deleted. These survive `git diff` review because nothing is *syntactically* broken; the line is simply dead.

After every deletion, before running tests, do this sweep:

1. List the functions/methods/templates your diff removed lines from (the §2.3 sweep operand, defined in the §2.3 preamble in phase-2-sweeps-contract.md).
2. For each one, re-read the **whole** surrounding function in its post-edit state.
3. Delete any local that is now assigned but never read, and any import / `use` clause / dependency declaration that lost its only consumer.
4. If something is *still* used elsewhere in the function, leave it; this sweep removes only genuinely-orphaned lines, never live ones — and never touch functions the diff didn't already modify.

Treat a leftover orphaned setup line as a defect in **this** PR, not a pre-existing-dead-code excuse — if the diff touched the function, the function leaves clean.

<!-- prflow:implement-ref step=2.3.1 file=skills/implement/references/sweep-2-3-1-orphaned-setup.md end -->

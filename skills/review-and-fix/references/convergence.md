# Reference: Convergence Check (Step 4.5)

### Step 4.5: Convergence check (iteration 2 onward)

Before looping back to Step 1 from iteration N ≥ 2, decide whether iteration N+1 would be a no-op. Count only applied Critical/Important fixes whose delta changes product or runtime code (a signature, predicate, guard, control flow or data shape) — a test, pin, comment or documentation change never counts, nor does a sweep fold-in of that shape. Converged when all three hold:

1. Few fixes: fewer than 3 such fixes this iteration.
2. Small fix-diff: fewer than 30 changed lines of such code in this iteration's fix commits (start from `git diff HEAD~{commits_this_iter}..HEAD --shortstat` and subtract the excluded hunks).
3. No new findings: no corroborated or confirmed Critical/Important finding in iteration N's Phase 3 that is not the same finding (Phase 3.2's same-finding rule) as one of N-1's (carried advisory findings are not new).

An operand you cannot establish fails its condition.

REJECT rule: convergence never bypasses an unresolved REJECT. When iteration N's verdict is REJECT and its Step 3 applied a fix to an id in the `reject_drivers` or `criterion_exempt` of the engine return it routed on, the rule fails — as it does when Step 3 applied a fix and `reject_drivers` (absent included) or the fix rows cannot be established — so iteration N+1 reviews that fix.

All three hold and the REJECT rule passes → exit early with iteration N's verdict as the tentative final verdict. A non-REJECT verdict takes the convergence entry: the parked-class sweep (`pre-fix-gates.md`) when parked findings exist, the Park-calibration gate, then Step 2.6, before Loop Exit; a REJECT goes to Loop Exit. Output: `Converged after iteration N — fewer than 3 small fixes applied and no new findings.` Otherwise loop back to Step 1 for iteration N+1; `$MAX_ITERS` still ends the loop.

<!-- END convergence.md -->

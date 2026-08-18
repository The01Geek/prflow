# Reference: Convergence Check (Step 4.5)

### Step 4.5: Convergence check (skip when about to start iteration 2)

Before looping back to Step 1, evaluate whether iter N+1 is likely to be a no-op. If it is, exit the loop early with iter N's current state. Convergence check is inactive on the iter-1 → iter-2 transition (no previous iteration to compare against). **On that iter-1 → iter-2 transition, run the Step 2.6 *early shadow trigger* first** (see "Early shadow trigger (`engine_self_modifying`, after iteration 1)") — it fires only on an `engine_self_modifying` PR whose iteration 1 routed to fixes without the convergence-time shadow already running, and any new findings it surfaces promote iteration 2 before this convergence check resumes at the iter-2 → iter-3 decision. Starting at the iter-2 → iter-3 decision, check all three:

1. Few fixes. Iter N applied fewer than 3 Critical/Important code fixes in Step 3 (counting one fix per finding addressed). Weigh convergence by severity and surface, not by raw fix count: a fix counts toward this tally only when it is an applied Critical or Important finding *and* its delta changes product/runtime code (a signature, a predicate, a guard, control flow, a data shape). Fixes whose delta is entirely test, coverage-pin, comment, or documentation changes do not count here — so an iteration whose whole delta is that polish (e.g. a drip of pin/comment/doc corrections) satisfies this condition even at ≥3 such fixes.
2. Small fix-diff. The Critical/Important code portion of the diff produced by this iteration's fix commits is fewer than 30 changed lines — measure the same code-only surface condition 1 counts, excluding test/pin/comment/doc lines (`git diff HEAD~{commits_this_iter}..HEAD --shortstat` is the starting figure; subtract the test/pin/comment/doc hunks when classifying). A large iteration that is entirely test/pin/comment/doc polish is small by this measure.
3. No new findings. No new corroborated/confirmed Critical or Important finding emerged in iter N's Phase 3 vs iter N-1's Phase 3. (Advisory findings carried over from Step 2.5 don't count as new.)

Sweep-driven fold-in edits (the one defining clause for conditions 1–2). A code-shaped 3b fold-in edit — a fix a Phase 2.3 authoring-side sweep surfaced and item 3b folded into this iteration — is graded by the fixer against item 2's observable fail-direction/impact rubric, recorded as a `severity-calibrated`-shaped `fix_decisions` entry with the sweep as its source, and that recorded grade then tallies under conditions 1–2 exactly as any graded fix does. A test/pin/comment/doc-shaped fold-in is excluded under the existing clause, exactly as any test/pin/comment/doc delta is. This defines the operand a sweep-driven fold-in was previously left as — with a named, durable grade producer — and widens no exclusion.

If all three hold → exit the loop early. The remaining unresolved findings (skipped via pushback in Step 3, or advisory from Step 2.5) are the *final* output of the run; iterating further wouldn't change them. Use iter N's current verdict as the tentative final verdict and, when it is non-REJECT and parked findings exist, **run the parked-class sweep before the shadow**. Then first run the Park-calibration gate on this early-exit path (it is part of Step 2.6, non-REJECT only) and proceed to **Step 2.6: Shadow review** before Loop Exit. The shadow pass still runs on early-exit convergence: it corroborates the post-sweep state and confirms the stop is genuine. Output: `Converged after iteration N — fewer than 3 small fixes applied and no new findings; running parked-class sweep and shadow review before final verdict.`

If any condition fails → loop back to Step 1 for iter N+1.

Note: convergence is *not* a way around an unresolved REJECT. If iter N's verdict is REJECT due to stuck/pushed-back findings, the shadow pass and Loop Exit's verdict flow still fire (a REJECT-on-convergence-exit goes straight to Loop Exit; Step 2.6 only runs when the tentative verdict is non-REJECT). Early exit just means "iterating won't help" — the human gate still applies.

---


<!-- END convergence.md -->

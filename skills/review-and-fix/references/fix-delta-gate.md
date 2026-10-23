# Reference: Fix-delta Verification Gate (Step 3.5)

### Step 3.5: Fix-delta verification gate (before Step 4 / the convergence check)

After each iteration's Step 3 fix commit, run this blinded gate before Step 4. Without a fix commit, skip it. Its inner re-fix attempts do not count toward `$MAX_ITERS`.

Dispatch one **Agent-tool subagent**, `subagent_type: prflow:fix-delta-reviewer`, with only `Repository: <absolute path from git rev-parse --show-toplevel>`, `Base: <iter_fix_base>` (parent of this iteration's first fix commit, including on re-gates), `Head: HEAD`, and, when the latest full `review-and-fix` load was `content-present` and printed a `sha256=… bytes=…` digest, `Policy loader: <the resolved path it ran>` and `Policy digest: <that digest>`. Never the extension text, findings or fixer reasoning. It returns `fix-delta review: verified` or `not verified (…)`, then `- <severity> | <check> | <path>:<line> | <evidence>` per finding.

Route by effective severity after Step 3 item 2's calibration:
- Critical/Important, except `added-assertion`: Step 3 re-fix → re-gate, capped at 2 inner attempts. Past the cap, start a normal Step 1 re-review counting toward `$MAX_ITERS`, with `loop_role: "fix"`; retain the finding in the reflection and in any Step 2.6 shadow reached by ordinary routing.
- Suggestion/Minor from those checks, at every threshold: Step 3 re-fix → re-gate under the same cap, without the over-grade gate, starting no iteration. A re-gate returning a finding the fixer declined this iteration (the same finding by Phase 3.2's same-finding rule) copies that decline's disposition, skipping Step 3. Open when the cap is spent, not declined: `decision: "pushed_back"`, `skip_category: "uncategorized"`, `evidence` stating the cap was spent with it open.
- `added-assertion`, including `unestablished:`: correct like an item-3 sibling or push back through item 5, under the same cap, promotion and at-cap carry.

For every returned finding, append its next `D-<k>` row to `fix_decisions`, counting from 1 across this iteration's attempts; keep earlier rows after an empty re-gate. Store `original_severity`, `source_file`, `claim_text` and the disposition's fields. A Step 3 calibration adds `calibrated_severity` and its evidence to that same row; retain both through the final disposition. Combine calibration and disposition evidence without changing a leading `criterion conflict:` prefix.

Effective severity is `original_severity`, or `calibrated_severity` with Step 3's behavioral evidence. Fixing, pushback, deferral or parking is not calibration. Missing or unknown severity routes as Critical/Important.

Undispatchable: `fix-delta not verified (subagent dispatch unavailable)`. Error or missing status: re-dispatch once with the same prompt; second failure or `not verified`: record `fix-delta not verified`, still routing listed findings. Unresolved `iter_fix_base`: no retry; record `fix-delta gate could not compute the delta (iter_fix_base unresolved) — gate disabled this run, shadow is the backstop`. Continue with shadow as backstop.

Write `reference_reads.fix_delta: {status, outcome, reason}` in `iter-<N>.json` via root *Lifecycle*: `verified` has null reason and the first applicable outcome across all attempts: `promoted`, `pushed_back`, `refixed`, `clean`. `not_verified` has null outcome and its failure breadcrumb. Add a `## PRFlow Reflections` bullet for re-fixes, promotions, every pushback, not-verified results, or a `content-present` full load that printed no `sha256=… bytes=…` digest, even on a finding-free clean gate; other finding-free clean gates need none. Report pushbacks even when promotion wins; item 6 owns the iteration note.

After the last gate commit, add `iteration_head` (`git rev-parse HEAD`) beside the 40-hex `fix_commit_sha`. Run Step 3 item 6's `--push-each-iteration` checkpoint for every outcome before Step 4 or promoted Step 1.

<!-- END fix-delta-gate.md -->

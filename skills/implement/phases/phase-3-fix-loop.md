<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-fix-loop.md start -->
<!-- prflow:implement-set phase=3 part=2 of=3 -->

## Phase 3: Review & Fix — the fix loop (dispatched worker)

### 3.3 Review & Fix

When §3.1's review reuse adopted a completed review, skip this section and continue to Phase 3.4.

Phase 3.3 runs in a fresh `review-fix-worker` subagent that shares this checkout. The worker owns the entire relocated procedure — the pre-loop status capture, the `review-and-fix` loop and its `--push-each-iteration` commits, the observability-persistence backstop, the post-return branch guard, the loop-verdict-marker routing, the coverage-record stamp and per-member enumeration, the in-loop roster reflection, the three Review extension-row ticks, the residual flush, the bounded re-review, the severity-aware exit, the soft-proceed, and the Blocked path. That procedure lives in `<skill-dir>/references/phase-3-3-review-fix.md`; you do **not** read it here and you do **not** replay it inline on any outcome. You load only these dispatch, handoff-validation, and continuation instructions.

**Commit before dispatch (shared checkout).** The worker edits and commits into this same checkout, so establish a clean tracked tree first: read `git status --porcelain --untracked-files=no` and commit any uncommitted change through the sanctioned durability-checkpoint helper before dispatching — a subagent dispatched over uncommitted work can lose it. Read the exit status from the tool result; on a refused or non-zero read, record it and take the Blocked path below rather than dispatching over an unestablished tree.

**Dispatch the worker.** Use the Agent tool with `subagent_type: prflow:review-fix-worker`, `run_in_background: false`, and no worktree isolation. Mint a fresh unique `DISPATCH_ID` for this dispatch and retain it for handoff validation. Pass the worker these literals you already hold: `ISSUE_NUMBER` (the caller-held implement-origin signal — the worker binds `progress_surface = workpad` from it, never from the public `--issue` argument or workpad existence); `DRAFT_PR` as the Phase 3.1 `draft PR number: [<n>]` result with its disposition (`numbered` with the digits, else `empty-brackets` or `absent` — the worker takes the omit-the-token arm itself); `FEATURE_BRANCH` (the workpad `**Branch:**` row); `DISPATCH_ID`, the run-facts `run id`/`run attempt` (`unestablished` when absent), `TIER`, and `DEVFLOW_APP_ID`; `REPO_ROOT` (this checkout's `git rev-parse --show-toplevel`), `SKILL_DIR` (the resolved `<skill-dir>`), `WORKPAD` with its invocation ladder, and `SCRIPTS`; `IMPLEMENT_EXTENSION_LOAD` (the observed load state, digest, pending notes, and trusted `DEVFLOW_PROMPT_EXTENSION_ROOT` when set); the canonical issue/workpad references; and the actionable prior decisions, corrections, and active user constraints with their sources. Do not paste the issue body, comment history, or workpad body into the dispatch — the worker reads those authoritative sources itself.

**Dispatch barrier.** This dispatch is bound by the dispatch-collection requirement in this run's injected engine-ground-truth block — read it there (with no such block, collect the completed return before the turn ends). Wait for the worker's completed return through the runner's result channel; a launch acknowledgment is never the return. The worker's return is only the `REVIEW-FIX HANDOFF` envelope (`outcome`, `handoff_path`, `dispatch_id`); read the named JSON file, not the worker's transcript or tool history.

**Validate the handoff before continuing.** The worker's evidence is accepted only from this dispatch and from artifact paths contained in this checkout, so validate it before acting — never infer successful work from the envelope alone. Author nothing; run the reader over the returned `handoff_path`, substituting the checkout root, the `DISPATCH_ID` you minted, and the issue number as literals. Emit the granted vendored literal first:
```bash
.prflow/vendor/prflow/scripts/validate-review-fix-handoff.py --handoff-file <handoff_path> --checkout-root <repo-root> --dispatch-id <dispatch-id> --issue-number <issue-number>
```
On a `command not found` / `No such file` / rc-127 reading, fall back to the portable anchor form:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/validate-review-fix-handoff.py --handoff-file <handoff_path> --checkout-root <repo-root> --dispatch-id <dispatch-id> --issue-number <issue-number>
```
Read the exit code from the tool result. Only exit 0 (a conforming handoff whose identity matches this dispatch and whose artifact paths resolve inside the checkout) is usable. Exit 2 (a shape/enum/type fault, an identity mismatch — a stale or duplicate return — an incomplete return, or an artifact path escaping the checkout) and exit 3 (the handoff file was unreadable, empty, or not valid JSON) each mean the return is unusable. Where neither rung of the reader ran (no output at all — a matcher refusal), the return is likewise unusable and unestablished, never a pass.

**Route on the validated handoff's `outcome`:**

- `proceed` (validator exit 0) → the worker completed the review — the clean-completion or soft-proceed path — and already stamped the coverage record, ticked the three Review extension rows and the `review-and-fix` gate, and surfaced any residual findings on the workpad. Carry its `unresolved_findings` forward for the human merge decision and continue to Phase 3.4; do not re-stamp coverage or re-run the loop.
- `blocked` / `error` (validator exit 0) → the worker already set `Status: Blocked` and emitted the 👎 outcome reaction for its own cause (a genuine unresolved Critical, an `engine-root: incomplete`/`evidence-missing` terminal, a twice-refused `review-and-fix` Skill call, or an extension/credential failure). Stop; do not replay Phase 3.3 inline. A returned extension-incompletion stop is retained as a blocker, never auto-re-dispatched to reset the worker's retry limit.
- An unusable return (validator exit 2 or 3, a stale/mismatched-identity or escaping-path rejection, a missing `handoff_path`, or no reader output at all) → record an actionable blocker naming what the reader reported, set `Status: Blocked` with a `blocked` reflection, emit the 👎 outcome reaction, and stop. The parent does **not** take over the loop or reconstruct the worker's state; a failed worker boundary is an explicit non-success, not a fallback to inline execution.

<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-fix-loop.md end -->

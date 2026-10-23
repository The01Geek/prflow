# Reference: Loop Control (setup, Main Loop, Steps 0.5–2, engine entry)

## Loop setup

Run the setup helper once at loop start. It resolves the run key, `slug`, run directory and the loop's config values with their defaults and clamps applied, and creates the run directory:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh loop-setup [--pr <PR_NUMBER>]
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/review-dirty-tree.sh loop-setup [--pr <PR_NUMBER>]
```

`status: ok` → hold `run_id` (the `<run-id>` below), `slug` and `run_dir` for the loop's lifetime, bind `$MAX_ITERS` to `max_iterations`, `$FIX_THRESHOLD` to `fix_severity_threshold` and `$FIX_BELOW_ITERS` to `fix_below_threshold_iterations`, and print each `warnings` entry. `status: error`, or no JSON, → stop before any mutation and report non-convergence naming `step` and `reason`. `<run-root>` below is `.prflow/tmp/review/<slug>/<run-id>`.

`$FIX_THRESHOLD` is Step 2's routing threshold: `critical` routes Critical only, `important` Critical and Important/Major, `suggestion` every severity.

Bind `progress_surface = workpad` for the whole loop only when the invoking caller already holds `$ISSUE_NUMBER` in context (implement's `review-fix-worker`); never infer it from `--issue`, `--push-each-iteration`, an issue workpad, PR mode or repository state.

## Main Loop

Expired-credential fail-fast (two strikes, never open-ended retry). After two consecutive `git push` or `gh` failures carrying HTTP `401`, `Bad credentials`, `Authentication failed` or the `devflow-gh-fresh: … expired/bad credential` stderr line, stop retrying that operation, record the cause, and exit reporting it.

Continuation of a killed attempt. Under `progress_surface = workpad`, before iteration 1, read the telemetry branch name, then ask whether a prior run of this slug left iteration records binding HEAD, substituting the run root, `$MAX_ITERS` and the printed branch name (`prflow-telemetry` when the read printed nothing) as literals:

```bash
.prflow/vendor/prflow/scripts/config-get.sh .telemetry.branch prflow-telemetry
```

```bash
.prflow/vendor/prflow/scripts/loop-verdict-marker.py continue-run --run-root .prflow/tmp/review/<slug>/<run-id> --max-iterations <MAX_ITERS> --telemetry-branch <branch>
```

Record a `restored` or `unestablished` line as a workpad note (`workpad.py update <issue> --note …`). `continue-run: restored iteration=<N> …` → the run directory now holds the killed attempt's `iter-1.json`…`iter-<N>.json`, stamped `restored_from`. Start at iteration N+1 under the N ≥ 2 rules, count toward `$MAX_ITERS` from N+1, and never take the Clean-iteration-1 exit; an engine return the killed loop never folded into a record is not consumed. Any other line or none starts at iteration 1.

Run at most `$MAX_ITERS` iterations.

### Iteration Start

Output: `Review iteration {N}/$MAX_ITERS...`

Prompt-extension re-load at re-entry (in PR mode after Step 0.5, so the text is the PR head's). For each of `review-and-fix` and `fix`, run `.prflow/vendor/prflow/scripts/load-prompt-extension.sh <name> --digest`, anchor form on not-found/rc-127, and re-load in full unless both hold: the printed digest equals the last full load's, and you can quote verbatim from resident context the extension's first `## ` heading (or first non-blank line) and its last non-blank line; a `bytes=0` digest satisfies by match alone. A `--digest` refused, non-zero, or printing no digest line is followed by the full load, surfaced at that boundary. Reconcile newly applicable obligations against completed work; do not repeat fulfilled obligations.

If N ≥ 2: read `iter-<N-1>.json` before proceeding.

### Step 0.5: PR-mode branch sync (PR mode only)

Skip in current-branch mode. In PR mode, first prove the checkout is the PR branch holding its pushed head, so fixes land there. Under `progress_surface = workpad` run only the branch-sync below. Otherwise, on iteration 1 check it out and route on the tool result:

```bash
gh pr checkout $PR_NUMBER ; echo "checkout-done"
```

- `checkout-done` with no `gh` error text → run the branch-sync below.
- `checkout-done` beside `gh`'s error text → stop and report the checkout failure; never review, commit or push onto the wrong branch.
- No output (refused) → run the branch-sync below; it is then the sole authority, and upstream tracking is the caller's.

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh branch-sync --pr <PR_NUMBER>
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/review-dirty-tree.sh branch-sync --pr <PR_NUMBER>
```

Route on its `status`: `ok` → proceed. `mismatch` → stop and report `head_ref`/`head_oid` against `branch`/`head`, and its `reason`. `unresolved` (a `gh pr view` read failed, was empty or `null`) or no JSON → stop and report it; an unresolved comparand never reads as satisfied.

### Step 1: Run the Review Engine

Run the *Engine entry* below with `<entry>` `step1`. A promoted iteration (Step 2.6) runs no Step 1.

### Engine entry (Step 1 and the Step 2.6 shadow)

`<entry>` is `step1` (`primary`) or `shadow`; `<N>` is the iteration. `<entry-run-id>` is `<run-id>` for primary, `<run-id>-shadow` for shadow dispatch and inline execution. Failure takes Step 1's non-convergence stop (no mutation, loop-back, Loop Exit, marker, headline or caller soft-proceed), or shadow Decide outcome 3.

1. Open, immediately before the dispatch:

   ```bash
   .prflow/vendor/prflow/scripts/review-dirty-tree.sh entry-open --contract 3 --run-root <run-root> --entry <entry> --iteration <N>
   ```

   It deletes the diff cache, phase log, `verdict-body.md`, the report drafts, this entry's previous return and this iteration's checklist, verification, verifier and Phase 3 files, snapshots the tree, records HEAD; on a `step1` entry at N ≥ 2 its `prior` carries the reviewed head of the newest earlier iteration that ran Step 1, and the prior-findings file; log each `prior.warnings` line and `Fix-delta handoff: {P} prior Phase 3 findings passed to the engine.`, `{P}` is `prior.count` when `prior.findings` is a path, else 0. `status: ok` → dispatch. Else → the failure route.
2. Dispatch an **Agent-tool subagent**, `subagent_type: prflow:review-engine`, to invoke the `/prflow:review` engine in its fresh context, with exactly this prompt, placeholders substituted and nothing added (`none` where a value is absent; the shadow passes neither `prior_` operand):

   ```text
   Run one review-engine entry for /prflow:review-and-fix.
   entry_kind: <primary|shadow>. iteration: <N>. run_id: <entry-run-id>. phase_range_max: 4.3. head_override: <local in PR mode>. progress_surface: <the bound value>. issue: <$ISSUE_OVERRIDE>. pr: <$PR_NUMBER in PR mode>.
   prior_diff_head: <prior.diff_head>. prior_findings: <prior.findings>.
   Loop skill directory: <loop-skill-dir>
   Read <loop-skill-dir>/references/engine-entry.md whole and execute it.
   This checkout is shared: the entry runs none of `gh pr checkout`, `git checkout`, `git switch`, `git worktree add`, or a `git -C <other-tree>` command.
   ```

   A returned `engine-root: incomplete` (the engine root could not be read whole) → the failure route.
3. Close, after any other return — a refused, dead or partial one included:

   ```bash
   .prflow/vendor/prflow/scripts/review-dirty-tree.sh entry-close --contract 3 --run-root <run-root> --entry <entry> --iteration <N> --branch <branch>
   ```

   `<branch>` is the Step 0.5 head ref in PR mode, else the caller-held branch. Before routing its line, scan for failed extension loads (every entry, dispatched or inline): read the return file's `report` as data, only the lines after `Rule applied:` up to the next `## ` heading. Each line there naming an extension that failed to load, was refused or is unestablished is a `## PRFlow Reflections` bullet, once per loop invocation per extension. With `engine_return.status` `ok`, a refused or failed Read, no `report` or no `Rule applied:` line is an unestablished scan, a bullet once per `<entry>` and `<N>`. Under `progress_surface = workpad` also write the entry's new bullets, same limits, in one `.prflow/vendor/prflow/scripts/workpad.py update <issue> --reflection-kind dropped-failed` call carrying one `--reflection-file <run-root>/ext-load-<entry>-<N>-<k>.md` per bullet (`<k>` from 1), each Write-authored first; no new bullet, no call. On `remedy=reissue-call` repair the cause and re-send it once; any other result short of `outcome=landed` or `outcome=replay` with `remedy=none` is an accepted loss, reported and not retried: those bullets reach no workpad or PR. Then route its line:

   - `branch-mismatch` or `branch-unestablished` → `rare-arms.md` *Branch recovery*.
   - Report `restored`, `dirtied` (untracked paths; Step 3 never stages them) and `dirty_detail` if present. `dirty_check: unestablished` → Step 1's stop on either entry, naming `dirty_detail`, even with `status: error`.
   - `status: error` (name its `step` and `reason`), no JSON, or no `engine_return` → the failure route.
   - `status: ok` → route on `engine_return.status`:
     - `ok` → the entry's `dispatch_mode` is the return's. `evidence.token` `PASS` with exit 0 → consume the return. A `FAIL` whose `missing=` holds only `delivery-failed:` tokens is never re-run; report its grade line, then: a `step1` `REJECT` with a `reject_drivers` id (absent: any routed item), or a `step1` return with a `criterion_exempt` id, outside them → route the return, minus those items, through Step 2; any other → the failure route. Any other token or exit → re-run this entry once from item 1; a second non-pass → the failure route, naming the grade line.
     - `unavailable` under `progress_surface = workpad` → the failure route, reported as `engine-unavailable: the engine could not dispatch its reviewers at this depth — launch /prflow:implement at the top level (not inside a subagent), or raise the nesting limit (Claude Code: set CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH to 4; VS Code Copilot: turn on chat.subagents.allowInvocationsFromSubagents)`.
     - `unavailable` (`dispatch_mode: "unavailable"`), `missing` or `malformed` (`dispatch_mode: null` with `dispatch_disposition` `dead` or `malformed`; a refused dispatch is `refused`) → name its `reason`, then `rare-arms.md` *Inline engine*.

The record's `dispatch_mode` (top-level for Step 1, `shadow.dispatch_mode` for the shadow) and `dispatch_disposition` come only from this routing; never self-assign them.

### Step 1.8: Review-row ticks

Under a bound `progress_surface = workpad`, after a primary entry's `PASS`, issue one call, issue number and substrings as literals; on iteration 2 and later it is a satisfied replay. A reported `remedy=` other than `none`, or no outcome line, is reported and not retried.

```bash
.prflow/vendor/prflow/scripts/workpad.py update <issue> --tick-progress "Classify diff" --tick-progress "Generate verification checklist" --tick-progress "Verify checklist" --tick-progress "Review agents" --tick-progress "Aggregate & verdict"
```

### Step 2: Check Verdict

Route on the return's `verdict`, `phase3_findings`, `checklist`, `phase4_demoted`, `reject_drivers` and `criterion_exempt` (ids are `F-<n>`, a finding's 1-based position, or a checklist item's `id`). A finding `phase4_demoted` lists (absent: none) is Phase-4-demoted: it routes nowhere, gets no `fix_decisions` row and is outside the parked population; a later reader takes an earlier entry's list from its `engine-return-<entry>-iter-<K>.json`. On any verdict, a finding `criterion_exempt` lists (absent: none) is never parked and goes to Step 2.5 → Step 3 whatever its grade. A routed item is a `phase3_findings` finding or a `checklist` FAIL, weighed by its stored `severity` (missing or unrecognized read as `critical`). A checklist INCONCLUSIVE never routes and gets no `fix_decisions` row — Loop Exit lists it.

- Engine verdict APPROVE with no parked advisory findings → tentative final verdict `APPROVE`; with parked findings → `APPROVE WITH ADVISORY NOTES`. Run the parked-class sweep (`pre-fix-gates.md`) when parked findings exist, then **Step 2.6: Shadow review**. `decision: "below-threshold"` rows are sweep inputs only and never select the advisory verdict.
- Engine verdict APPROVE WITH CAVEAT (a checklist coverage gap) → as APPROVE with notes below, except a tentative final verdict it sets is `APPROVE WITH CAVEAT`.
- Engine verdict APPROVE with notes → split on `$FIX_THRESHOLD`:
  - Any routed item at or above `$FIX_THRESHOLD` → Step 2.5 → Step 3, routed as a REJECT would be. A finding Step 3 cannot fix takes the `skip_category` pushback flow; `$MAX_ITERS` and Step 4.5 bound the loop.
  - Below-Important damper: on iteration N > `$FIX_BELOW_ITERS` whose at-or-above-threshold items include no Critical or Important one, keep its below-`important` checklist FAILs off the fixer and park each below-`important` finding `criterion_exempt` does not list as advisory with one `fix_decisions` row (`decision: "below-important-damper"`, `skip_category: "below-important-damper-parked"`, evidence `parked-origin: below-important-damper`, no `parking_evidence`); then, with a `criterion_exempt` finding routed, go to Step 2.5 → Step 3, else set tentative final verdict `APPROVE WITH ADVISORY NOTES` and run the parked-class sweep before Step 2.6. Otherwise below-`important` items route with the rest.
  - Every routed item below `$FIX_THRESHOLD` → append one `fix_decisions` row per finding `criterion_exempt` does not list with `decision: "below-threshold"`, `skip_category: "below-threshold-parked"` and the evidence marker `parked-origin: below-threshold`; then, with a `criterion_exempt` finding routed, go to Step 2.5 → Step 3, else set tentative final verdict `APPROVE WITH CAVEAT` and run the parked-class sweep before Step 2.6. Only the sweep reads these rows; they never count as advisory findings.
  - Per-finding foreclosure arm (`settled-by-disclosure`). On either path above, a parked finding whose deliverable is an already-shipped disclosure is foreclosed at parking time with one rationale-bearing `settled-by-disclosure` row (`fixing.md` item 5's shape, `parking_evidence.source` naming the disclosure `{path, phrase}`) **instead of** a `below-threshold` row — exactly one row, never both.
- Engine verdict **REJECT** → Step 2.5 with the effective fix set: every routed item at or above `$FIX_THRESHOLD` plus every id in `reject_drivers`, even below `$FIX_THRESHOLD` (absent: every routed item). A REJECT never reaches the shadow pass; converge first.

### Clean-iteration-1 exit (only under `progress_surface = workpad`)

Evaluate only at iteration 1: where Step 2 sends a non-REJECT verdict to Step 2.6, or after Step 3.5 where Step 4 would loop back. When clean:

1. At the post-fix point, take iteration 1's engine verdict as the tentative final verdict, mapped as Step 2 maps it, and run the parked-class sweep when parked findings exist.
2. Run Step 2.6's Park-calibration gate as Step 4.5's early-exit path does; a re-grade promotes and voids this exit.
3. Record `shadow_skipped: {"reason": "iteration-1-clean", "head": "<git rev-parse HEAD>"}` in `iter-1.json`, never beside a `shadow` block, and go to Loop Exit.

Iteration 1 is clean only when every operand below is established from `iter-1.json` and the engine return; an unestablished operand is not clean:

- The engine verdict is non-REJECT, `criterion_exempt` lists nothing (absent: none) and `phase3_failed_agents` is `[]`; in `engine-return-step1-iter-1.json`, `diff_profile.checklist_skipped` is not `"failure"`, `checklist` holds no `FAIL`, and each `INCONCLUSIVE` in it has `category` `issue_acceptance`.
- Every non-Phase-4-demoted `phase3_findings` entry is below Important — by its `severity`, or the `calibrated_severity` of its `severity-calibrated` row. A Critical or Important that was fixed, pushed back, deferred or parked is not clean.
- After a fix commit, `reference_reads.fix_delta` is `verified` with outcome `clean`, `refixed` or `pushed_back`; complete D rows across all attempts establish only below-Important effective severities (`fix-delta-gate.md`); zero findings requires an established verified gate return.
- The parked-class sweep, when it ran, completed (`not_completed: null`) with no promotable sibling.

The exit never applies to a caller's re-review of its own hand-fix.

<!-- END loop-control.md -->

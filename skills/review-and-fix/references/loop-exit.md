# Reference: Loop Exit

## Loop Exit

### Deferrals manifest

Write unresolved deferrals from `fix_decisions` through final iteration `<N>`; the helper applies matching and supersession rules:

```bash
.prflow/vendor/prflow/scripts/loop-verdict-marker.py build-deferrals --run-root .prflow/tmp/review/<slug>/<run-id> --iteration <N>
```

`status: ok` → print each `warnings` entry; each `rejected` entry stays an unresolved finding and gets a `## PRFlow Reflections` bullet `deferral {iter}:{finding_id} left out: {reason}`, plus its `file` and `lines` when present, and a warning ending `not carried` gets the bullet `deferrals manifest incomplete: <warning>`. Anything else → the bullet `deferrals manifest not written: <reason>`; continue. It files no issue and edits no PR body.

### Verdict → chat output

No verdict is posted to GitHub; the final report — the engine report with its `## Code Review Findings`, plus `## Advisory Findings`, `## Coverage` and `## Unresolved Shadow Findings` where they apply — goes to chat.

Over-grade gate non-convergence. A promote-path `Critical`/`Important` finding the over-grade gate flagged with no recorded `severity-calibrated` evaluation blocks any clean APPROVE-family verdict; at the iteration cap it surfaces through `APPROVE WITH UNRESOLVED SHADOW FINDINGS` (or REJECT if Critical), never silently dropped.

Parked-class sweep completeness (conclusions through a convergence entry only): when the run has parked findings, the concluding iteration's record holds a `parked_class_sweep` object; a parked population that could not be established counts as non-empty. Otherwise complete the sweep first.

Render the mechanical half, `<N>` the final iteration, `<the loop result>` the result mapped below, `<dispatch>` whether this run launched the Step 2.6 fan-out (`attempted`, `never` or `unestablished`), and one `--not-verified` per gate that did not complete: `fix-delta gate` (any iteration's `reference_reads.fix_delta.status` is `not_verified`), `parked-class sweep (<cause>)` (a non-null `parked_class_sweep.not_completed`), `deferrals manifest` (a `deferrals manifest` bullet above); omit it when none:

```bash
.prflow/vendor/prflow/scripts/loop-verdict-marker.py render-exit --contract 2 --run-root .prflow/tmp/review/<slug>/<run-id> --iteration <N> --result "<the loop result>" --shadow-dispatch <dispatch> [--not-verified "<gate>"]...
```

It writes the `## Coverage` section to `coverage_path`; print each `warnings` entry. A non-empty `incomplete` names a step to finish first (`park_calibration`: run Step 2.6's Park-calibration gate), then re-render; when it cannot run, the not-verified rendering stands. `status: ok` → line 1 of the chat output is `marker`, and `{shadow status}` below is `shadow_status`. Anything else, or no output → emit no approval headline: report `evidence-missing: <run root> — <its detail or reason, else no output>` as line 1 and stop. Only Decide outcome 2's promoted iteration, which re-shadows, fixes a final-shadow finding; never flush a fix after the verdict.

- APPROVE: `Review passed after {N} iteration(s) ({shadow status}). All checks approved.`
- APPROVE WITH ADVISORY NOTES: `Review passed after {N} iteration(s) ({shadow status}) with {M} advisory finding(s) parked for human review. See report.` The headline advisory count excludes `decision: "below-threshold"` rows.
- APPROVE WITH CAVEAT (an engine APPROVE WITH CAVEAT / APPROVE with notes, or a Step 2.6 outcome-1 `shadow_verdict` of APPROVE WITH CAVEAT): `Review passed after {N} iteration(s) ({shadow status}) with caveats. See report.`
- APPROVE WITH UNRESOLVED SHADOW FINDINGS (iteration-cap outcome 2):
  - Ordinary arm: `Review converged after {N} iteration(s) but a final shadow pass surfaced {K} new Important finding(s) that the loop could not address within the iteration cap. See report.`
  - Sweep-at-cap arm: `Review converged after {N} iteration(s) but the parked-class sweep registered {K} promotable sibling finding(s) that the loop could not address within the iteration cap. See report.` `{K}` and the list come from the current iteration's unfixed promotable `parked_class_sweep` siblings.
- REJECT (the cap reached or a convergence exit still REJECT, or a shadow Critical at the cap): `Review still has findings after {N} iteration(s). Remaining issues require manual review:` then the unresolved findings, then — with `$PR_NUMBER` — `To post this verdict as a formal merge signal (e.g. a blocking --request-changes review), run \`/prflow:review {PR_NUMBER}\` — it performs an independent re-review and posts the result.`, or without it `To post this verdict as a formal merge signal once a PR exists, push the branch and open a PR, then run \`/prflow:review <PR>\` — it performs an independent re-review and posts the result.`

When `{shadow status}` is not verified, replace the trailing `All checks approved.` / `with caveats.` with `See report.` Add the `coverage_path` file's `## Coverage` section after the engine report's `## Code Review Findings`.

### Persist and checkpoint

Persist this run's records to the telemetry branch (exit 0 by contract; a degraded persist prints a warning):

```bash
.prflow/vendor/prflow/lib/efficiency-trace.sh --persist --workpad-dir ".prflow/tmp/review/<slug>/<run-id>" --slug "<slug>"
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --persist --workpad-dir ".prflow/tmp/review/<slug>/<run-id>" --slug "<slug>"
```

In PR mode with `--push-each-iteration` (and unless `prflow_implement.update_branch_checkpoints` is off), refresh the terminal pushed state with the checkpoint helper and handle its token as Step 3 item 6 does:

```bash
.prflow/vendor/prflow/scripts/update-branch-checkpoint.sh
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

### Tick the final Blueprint row

As the last terminal step, on every termination that reaches it (converged, capped or final REJECT), tick the row `Run complete — everything this run owed`: under `progress_surface = workpad`, `.prflow/vendor/prflow/scripts/workpad.py update <issue> --tick-progress "Run complete"` with the issue number as a literal; otherwise, with `$PR_NUMBER`, tick it in this run's progress comment. An already-ticked row is the expected no-op.

<!-- END loop-exit.md -->

# Reference: Fixing (Step 3)

### Step 3: Fix Findings

Read `<loop-skill-dir>/../fix/references/fix-discipline.md` under the *Reference-loading contract* before any fix; its severity, fix, claim, acceptance-criteria, test and deferral rules govern every item below. In this loop its "linked issue's acceptance criteria" are the engine return's `acceptance_criteria` (on the inline arm, your Phase 0.4 value), and its "caller's decision record" is this iteration's `fix_decisions`. Step 3 takes Step 2's routed checklist FAILs, the Step 2.5 survivors and Step 3.5's routed findings; item 2 evaluates each.

Apply the discipline's *Tests* rule at fix-authoring time. Choose verification for the changed behavior, including existing coverage or a bounded direct check when sufficient; do not recreate a test obligation removed under that policy. Honor explicit repository requirements and agreed criteria. Report chosen evidence and material limits in the loop's output on every progress surface; item 4 reports test execution, and item 6 adds the workpad note when applicable.

For a consequential prompt change, a failed check of the verification chosen above keeps the finding open. Record a denied, unavailable or inconclusive check as unverified; use another sufficient check when available. At the finding's resolution decision, if the required outcome remains unestablished, stop at non-convergence naming the finding and missing evidence. A quiet Step 3.5 or shadow review does not supply that evidence. An incidental finding that remains unfixed follows item 5 (`uncategorized`, `finding_id: null` when it has no assigned ID). Preserve historical waivers as prior decisions, not new test requirements.

#### 1. Reading the findings

1. Read all findings before fixing anything.

#### 2. Technical evaluation

2. Evaluate each finding:
   - A checklist FAIL: read the cited source and the requirement the claim rests on yourself. A defect → fix; a requirement the code need not meet → item-5 `claim-quality`; a misread → item-5 pushback; a read settling none → item-5 `uncategorized` naming what it could not settle.
   - Critical/Important, or listed in the `criterion_exempt` of the engine return it was routed from (on a shadow-promoted iteration, the shadow's, matched by its row's `shadow_finding_id`; a row without one, or an unreadable return, counts as listed): valid here → fix; otherwise item-5 pushback (be slow to dismiss external-tool claims surviving Step 2.5). Record a *Severity* change on D rows per `fix-delta-gate.md`; otherwise `{finding_id, decision: "severity-calibrated", source_file, claim_text, original_severity, calibrated_severity, evidence}`.
   - Any other Suggestion/Minor finding you evaluate, routed or not: fix it unless its item-5 row records one of these decline reasons, and only these: a cited source span shows the code already correct (`claim-quality`; for a fix the discipline's *Writing the fix* rule rules out — a branch, flag, warning or fallback for an input no caller sends — `evidence` names the absent caller); the fix needs a design decision the issue, its criteria and the code leave open, `evidence` naming it (unclear → fix); a criterion conflict (below); the fix would make an earlier `applied` finding hold again (below); another rule in this file, the loop or the discipline gives it a different outcome, the row naming that rule; an instruction you are bound by (the project's agent instructions file, a loaded skill extension) forbids it, `evidence` quoting it; `out-of-scope`; `already-tracked`. The design-decision and instruction reasons are `uncategorized`. Polish, low priority, clarity only, fix size, a prose or byte budget, or "no reader" naming no absent caller declines nothing.
   - A finding that would change documented behavior (a reclassification, a "should be X not Y", a contradicted invariant): verify it against the doc, comment or spec first. Contradicting the source of truth → item-5 `claim-quality` pushback citing it; consistent → apply it, citing the source in its `fix_decisions` row.
   - A fix the discipline declines because it would weaken or contradict a criterion is recorded as an item-5 pushback (`skip_category: claim-quality`, `evidence` beginning `criterion conflict:` and quoting that criterion's full line, checkbox marker excluded) instead of a PR-body `Disputed criterion` line. It stands only when `evidence` names what in the quoted criterion the fix would weaken or contradict; a conflict you cannot name is no decline, and the fix is applied unless another decline reason above holds (a Critical/Important finding: unless it is invalid here). No other row cites a criterion as its reason, and an empty `acceptance_criteria` (`""`) applies none of this. A finding a prior iteration's criterion-conflict row declined → `rare-arms.md` *Criterion conflicts* only when that row's `evidence` meets this naming test; otherwise evaluate it afresh.
   - Before an edit deletes or rewrites text in a file, check the `description` of each `phase3_findings` row in this run's earlier `iter-<K>.json` records whose `fix_decision` is `applied` and whose `defect_signature.file` is that file, and the `claim_text` of each `applied` `fix_decisions` row there with `finding_id: null` and that `source_file` (an unreadable record carries nothing; name it in the loop's output). An edit that would make one hold again is reworked; if no edit clears both, it is not made and the current finding is pushed back under item 5 as `uncategorized`, evidence naming iteration K's finding.
   - For each file this iteration's fixes edit, once its other fixes (item-4 failure fixes included) are in the working tree and before item 6 commits, re-check each `fix_decisions` row in this run's earlier `iter-<K>.json` records with `decision: pushed_back`, `skip_category: uncategorized` and that `source_file` — any severity, a checklist FAIL included — from its `claim_text` and `evidence`. Not being routed never holds: skip a row recording only that, and judge one giving other reasons on those. When several rows name the same finding (the same `source_file` and `claim_text`, or one row's reason only pointing at another), the latest iteration's row decides. A row with no reason has none; an unreadable record carries nothing and is named, as above. A defect still present in that tree is fixed in this commit, its class under item 3, unless the row's reason is a decline reason above that still holds there. A fix records an `applied` row with `finding_id: null` and the earlier row's `source_file` and `claim_text`, which then follows every `applied` rule and sends the iteration back through item 4. Left on its recorded reason: no new row. Left on another decline reason: that reason's row, with `finding_id: null` and the earlier row's `source_file` and `claim_text`.

#### 3. Class-wide fixes

3. Fix one finding at a time, then its class under the discipline's bounded coupled-site search. Fix every related sibling this iteration, applying item 2 to each, and record any you deliberately leave through item 5, never as `out-of-scope`. Edit with the Edit tool (Write only for a new file; generators, formatters and `git mv`/`git rm` exempt), never `sed -i` or a `python3` script. When a defect kind has recurred across three iterations, stop extending the enumeration the fix keeps patching and model the artifact the rule is written against.

#### 4. Running tests

4. Run tests after all fixes, the narrowest covering test before the broadest; the project's test and lint commands are in its `CLAUDE.md`, README or configuration. A runner naming a retained log is re-read, not re-run. Fix every failure before continuing.

   Report the run in the loop's output as `pass` / `fail` / `skipped` (a skip with its reason: a no-fix iteration, an ungranted suite command). A suite that passes while a check inside it self-skipped is not a clean pass: detect such checks from the runner's own tally and skip lines, never from the exit code, and name each check, kind and reason in the loop's output.

   Establish a result from the runner's terminal summary line where it prints one, else from its exit status. A command that never ran (refused, denied) or is still running has no result.

   Single flight. When `config-get.sh .verification_flight.enabled true` does not print `false`, record each suite run through `verification-flight.py` (`claim` with the `candidate_identity` `reception-record.py record` prints, `mark-running`, the unchanged command, `finish --result passed|failed|timed_out|cancelled`), carrying the owner token from `claim`'s output between calls. Reuse another run's result only when `status` reports `reuse_ready: true` for this checkout; anything else launches the suite.

   Apply the discipline's targeted mutation rule only when needed. For an in-place mutation, first save a byte-identical copy at `.prflow/tmp/in-place/<repo-relative path>` and report its original `git hash-object --no-filters` ID in the loop's output; under `progress_surface = workpad`, also write it in an immediate workpad note. Confirm the copy has that ID; if the comparison fails, delete the new copy and report `unrunnable: no byte-identical copy`, without mutating. Wait for tests using the file to finish before mutating. After the focused check, revert the exact mutation and verify the ID before another edit or deleting the copy. Restore the verified copy on mismatch; an unresolved mismatch stops at non-convergence naming the file and both IDs. Settle every copy before committing. Confirm any new test is collected and checks the intended behavior; a wording-only pin needs no automatic replacement.

#### 5. Tracking pushbacks

5. **Track pushbacks.** For each skipped finding or FAIL, record `{finding_id, source_file, claim_text, skip_category, evidence}` in `fix_decisions` with `"decision": "pushed_back"`; a deferral row (`claim-quality` / `out-of-scope` / `already-tracked`) also carries `parking_evidence`, its `source` the citation the category requires. A finding below `verdict_severity_threshold` whose deliverable is an **already-shipped disclosure** and that is not in the `reject_drivers` of the engine return this iteration routes on (absent: every routed item drives) is recorded once instead of a fix, as a `settled-by-disclosure` row whose `parking_evidence.source` is the disclosure's repo path and a short phrase quoted from it. `skip_category` is one of:

   ##### `skip_category` enum (authoritative)

   | Value | Meaning | Required `evidence` | Deferral row? |
   | --- | --- | --- | --- |
   | `claim-quality` | The verifier's evidence is correct in form but the code is fine. | The source span proving it. | **Yes** |
   | `out-of-scope` | The flagged lines are pre-existing code this PR does not modify, or a separate concern. | `git blame` / `git log -S` or the diff. | **Yes** |
   | `already-tracked` | A separate issue or PR addresses the defect. | The issue/PR number. | **Yes** |
   | `uncategorized` | None of the above: any real-but-unfixed defect. | Why it was not fixed in-loop. | No |
   | `advisory-parked` | Written by Step 2.5: web verification refuted or could not confirm it. | The demotion reason. | No |
   | `below-threshold-parked` | Written by Step 2's all-below-threshold arm: a parked-class sweep input only. | Exact marker `parked-origin: below-threshold`. | No |
   | `below-important-damper-parked` | Written by Step 2's below-Important damper: an advisory finding. | Exact marker `parked-origin: below-important-damper`. | No |
   | `settled-by-disclosure` | Written by this step (fixer-routed foreclosure) or by Step 2's per-finding foreclosure arm: answered by an already-shipped disclosure, never re-attempted. | The disclosure's repo path and phrase, in `parking_evidence.source`. | No |

   Inside the loop this rule replaces the discipline's `Finding rejected` rule. When you record a `claim-quality` row whose `evidence` does not begin `criterion conflict:`, write its `Finding rejected` line by the discipline's PR-body write path, unless the body already holds it, only when `$PR_NUMBER` is bound and `--push-each-iteration` is in effect; otherwise, or when that write fails, put the line in the loop's output instead. When a later iteration promotes or fixes such a row under those same conditions, delete the PR body's `Finding rejected` line quoting its finding by the discipline's deletion path, reporting a line it cannot delete as not deleted.

#### 6. Committing fixes

6. Commit fixes before re-running the review, after item 2's re-check of earlier declines. Stage only the files this iteration's fixes touched, by explicit path enumerated with `git status --porcelain` — never `git add -A` or `git add .` — and never a path an `entry-close` listed in `dirtied`. First settle every file `find .prflow/tmp/in-place/ ! -type d` prints (item 4): compare the file's ID first and delete the copy only on a match with the recorded original ID; otherwise stop at non-convergence without changing either file, naming the file and both IDs (or the unavailable ID). Unless the `find` exits 0 or reports the directory missing, stop at non-convergence.
   ```bash
   git add <file1> <file2> …   # the specific files this fix touched — never `git add -A` / `git add .`
   git commit -m "fix: address review findings (iteration {N})"
   ```
   A `git commit` that exits non-zero is fixed and retried; once it exits 0, capture `git rev-parse HEAD` as `fix_commit_sha` and immediately write the record (item 7) as one step — the workpad emit is fused to this fix-commit moment, never deferred.

   Run Step 3.5 (inner re-fixes return here unpushed), writing `reference_reads.fix_delta`; add `iteration_head`; with `--push-each-iteration`, checkpoint/push below. Under `progress_surface = workpad`, note: `iteration <N> <first 12 of fix_commit_sha>: verification <checks, results and limits>, fix-delta <outcome or not verified>, suite <result>`; append every gate pushback's D id and reason, even when the outcome is `promoted`.

   With `--push-each-iteration`, once per fix-applying iteration bring the branch up to date with the base and push through the shared checkpoint helper, alone in its fence — never chain a bare `git push` after it:
   ```bash
   .prflow/vendor/prflow/scripts/update-branch-checkpoint.sh
   ```
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
   ```
   Follow the `route:` line it prints on stderr before its token, recording outcomes on the issue workpad and taking its Blocked stops when implement-driven, else in the loop's output with the loop's stop-and-report. Only these tokens push:
   - `UPDATED` — the helper already pushed the fix and the base merge. Do not push again.
   - `UP_TO_DATE` / `DISABLED` / `UNVERIFIED` — push the fix commit now (`UNVERIFIED` also records its breadcrumb).
   - `PUSH_REJECTED` — the helper retried and restored the branch; do not push. Continue, unless stderr carries the failed-restore `WARNING`, which stops the run.
   - `CONFLICT` or `MERGE_IN_PROGRESS` — `rare-arms.md` *CONFLICT checkpoint*.

   A reception pass that pushes uses an explicit destination ref (`git push origin HEAD:refs/heads/<the PR's head ref>`), never a bare `git push` or `git push -u origin <branch>`; this does not govern the implement Phase 1.5 `git push -u origin HEAD`. A failed push is reported in chat and never aborts the loop. Without the flag, skip the checkpoint and the push.

#### 7. Iteration record

7. Install `iter-<N>.json` by the root *Lifecycle* record write — a non-optional emit on every iteration, a degraded or hand-run engine path included; the `--persist` synthesis floor is no license to skip it. It carries every schema key this iteration produced; the root *Field rules* state what each holds. On a `fanned-out` Step 1, `lib/efficiency-trace.sh --persist` fills `fix_files`, `checklist`, `diff_profile`, `phase3_dispatched`, `expected_reviewers` and `cap_drops` from that return and `fix_commit_sha`; on any other arm write them yourself (`fix_files` from `git diff --name-only <fix_commit_sha>~1 <fix_commit_sha>`, `[]` without a fix commit).

<!-- END fixing.md -->

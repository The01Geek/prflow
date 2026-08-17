<!-- prflow:implement-ref step=4.1 file=skills/implement/references/doc-deliverable-self-heal.md start -->

### 4.1 Stage 2 — Self-Heal an Absent Documentation Deliverable

Reached only from Stage 2's absent-path arm, once per named path that arm found absent from the diff; the caller keeps the enforcement decision and owns the `Blocked` terminal, so nothing here writes a run status.

1. **Derive the missing update from the issue body's `**Documentation Needed**` prose.** If the correct content for this path cannot be derived from it, report that back to the caller and stop.

2. **Perform the update**, then record it on the workpad. Emit the granted vendored literal as the leading token first, substituting the path as a literal:
   ```bash
   .prflow/vendor/prflow/scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1 self-heal: <path> absent from diff; performed update from Documentation Needed prose"
   ```
   On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1 self-heal: <path> absent from diff; performed update from Documentation Needed prose"
   ```

   If neither invocation runs, continue to step 3 and name the unrecorded note in the step 5 report — the note is an audit record, not the repair.

3. **Commit and push**, each its own single statement. Stage the resolved repository path(s) you actually edited — for a bare-filename deliverable that is the path the edit landed at, not the bare token, and it includes any coupled file the repair touched — never `git add -A` or `git add .`; an unsubstituted placeholder or a pathspec matching no file makes `git add` exit non-zero and stage nothing at all, so the commit reports nothing to commit and the step-4 re-check fails:
   ```bash
   git add "<edited-repository-path>" # repeat this quoted operand once per edited path
   ```
   ```bash
   git commit -m "docs: self-heal Documentation Needed deliverable for issue #$ISSUE_NUMBER"
   ```
   ```bash
   git push
   ```

4. **Re-check against the remote.** Read each result from the tool output, never a captured shell variable. Confirm the commit and the push both reported success, then confirm the local branch is in sync with its upstream — the two readings below must be equal, and an unequal or unavailable pair means the repair did not reach the remote:
   ```bash
   git rev-parse HEAD
   ```
   ```bash
   git rev-parse @{u}
   ```
   Then re-run the helper-driven diff check for this path exactly as Stage 2 does — the deliverables helper, then the cumulative diff — and apply Stage 2's satisfied-versus-absent rule. Only a path now present in the re-checked diff counts as satisfied. When that re-check cannot be established — the deliverables helper returns a token other than `deliverables` or `no-deliverables`, or the diff recompute exits non-zero — write no run status here: treat this path as not repaired and report the observed token or exit status to the caller, whose **Shared read contract** arms route that outcome naming what was observed — the content-derivation terminal would instead record a cause the operator cannot act on.

5. **Report the per-path outcome to the caller** — repaired-and-verified, or not repaired naming which of steps 1–4 failed or could not be established, plus any step-2 workpad note that went unrecorded.

<!-- prflow:implement-ref step=4.1 file=skills/implement/references/doc-deliverable-self-heal.md end -->

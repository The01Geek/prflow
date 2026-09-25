<!-- prflow:implement-ref step=4.1 file=skills/implement/references/doc-deliverable-self-heal.md start -->

### 4.1 Stage 2 — Self-Heal an Absent Documentation Deliverable

Reached only from Stage 2's absent-path arm, once per named path that arm judged absent; the caller keeps the enforcement decision and owns the `Blocked` terminal, so nothing here writes a run status.

1. **Derive the missing update from the issue body's `**Documentation Needed**` prose.** If the correct content for this path cannot be derived from it, skip steps 2–4 for **this path only** and report it as not repaired at step 5.

2. Perform the update — the documentation deliverable's own content only; if deriving that content reveals an implementation-code change is warranted, do not make that edit — report it (path and unperformed change) to the caller at step 5 for a `note`-kind reflection, and continue repairing the documentation. Then record the update on the workpad. Emit the granted vendored literal as the leading token first, substituting the path as a literal:
   ```bash
   .prflow/vendor/prflow/scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1 self-heal: <path> not delivered by this docs pass; performed update from Documentation Needed prose"
   ```
   On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1 self-heal: <path> not delivered by this docs pass; performed update from Documentation Needed prose"
   ```

   If neither invocation runs, continue to step 3 and name the unrecorded note in the step 5 report — the note is an audit record, not the repair.

3. Commit and push, each its own single statement. Stage the resolved repository path(s) you actually edited — for a bare-filename deliverable that is the path the edit landed at, not the bare token, and it includes any coupled file the repair touched — never `git add -A` or `git add .`; an unsubstituted placeholder or a pathspec matching no file makes `git add` exit non-zero and stage nothing at all, so the commit reports nothing to commit and the step-4 re-check fails:
   ```bash
   git add "<edited-repository-path>" # repeat this quoted operand once per edited path
   ```
   ```bash
   git commit -m "docs: self-heal Documentation Needed deliverable for issue #$ISSUE_NUMBER"
   ```
   ```bash
   git push
   ```

4. **Re-check against the remote.** Read each result from the tool output, never a captured shell variable. Confirm the commit and the push both reported success, then compare the two readings below: an **unequal or unavailable** pair means the repair did not reach the remote — a comparison against the local remote-tracking ref, which this procedure does not fetch, so a remote branch deleted or rewound after a successful push still reads as landed.
   ```bash
   git rev-parse HEAD
   ```
   ```bash
   git rev-parse @{u}
   ```
   Then re-check this path against the pass range only — recompute Stage 2's `"<pre-docs-head>..HEAD"` diff with the SHA Stage 2 substituted for `<pre-docs-head>` (its fallback read included) and apply its bare-filename/exact-match rule to this path alone; only a path now present in that range counts as satisfied. The caller established this path's obligation and no re-read of the issue body retires it: if a deliverables re-read happens for any reason, a reading of `no-deliverables`, or of `deliverables` over a set omitting this path, still means not repaired. Take none of Stage 2's terminal arms and not its no-op arm from inside this reference — no run-status write, no outcome reaction, no stop, and no tick of `Documentation` — because either abandons the caller's remaining absent paths mid-loop. A pass-range recompute that exits non-zero or has no such SHA (Stage 2's HEAD read failed), and any deliverables token other than `deliverables` or `no-deliverables`, each mean not repaired: carry the observed exit status or token into the step 5 report and continue.

5. Report the per-path outcome to the caller — repaired-and-verified, naming the resolved repository path the repair landed at (for a bare-filename deliverable that path, never the bare token); or not repaired naming which of steps 1–4 failed or could not be established, plus any step-2 workpad note that went unrecorded. Also report any implementation-code change discovered per step 2 (path and unperformed change) so the caller records it as a `note` reflection under the Finalization boundary.

<!-- prflow:implement-ref step=4.1 file=skills/implement/references/doc-deliverable-self-heal.md end -->

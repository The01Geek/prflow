<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md start -->

## Phase 3: Review & Fix

Output: `Phase 3/4: Review & Fix — creating PR and running review...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Reviewing`.

### 3.0 Changed-file lint (advisory)

Invoke `preflight.py lint-changed` as a direct leading token. It selects changed files through the validated lint manifest and writes the advisory receipt; do not install a missing tool or treat this result as completion evidence.

### 3.1 Create or Adopt the Draft PR

Run base-branch update checkpoint 2 before opening the PR:

Route on the token the helper prints and the `route:` line it prints on stderr immediately before that token, as implement-driven checkpoint 2. This is not permission to reload Phase 1.

```bash
.prflow/vendor/prflow/scripts/update-branch-checkpoint.sh
```

On exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token and its `route:` line per the implement-driven outcome routing. On `UPDATED <n>`, apply the root *Prompt-extension re-load at re-entry* rule before the PR title and body write below. `CONFLICT` remains model-owned: resolve it, verify it, complete the merge, push, apply that rule, then re-run the Phase 2.3.0 changed-contract sweep. `MERGE_IN_PROGRESS`, unresolved or suite-failed `CONFLICT`, and a `PUSH_REJECTED` failed-restore warning stop the run; `UP_TO_DATE`, `DISABLED`, `UNVERIFIED` and `PUSH_REJECTED` with the branch restored continue without the re-load check. Neither PR-opening helper mode resolves or aborts a merge.

Use the Write tool to create `<run-scratch>/pr-title.txt` from the issue title and `<run-scratch>/pr-body.md` with:

```text
Work in progress — automated review pending.

Resolves #<issue-number>
```

The helper appends the run link and provenance line on the create arm. Invoke it as the only PR-opening boundary:

```bash
.prflow/vendor/prflow/scripts/resolve-existing-pr.sh --open --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-existing-pr.sh --open --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

Read the shell-token `pr-open` record from the tool result:

- `outcome=created` or `outcome=adopted` — continue with the returned `number` and `url`. The helper already pushed an explicitly named head destination when creating, opened the draft, preserved an adopted body, wrote the workpad link, applied PRFlow, bound scope decisions, and attempted create-only assignment. Record any non-zero companion `*_rc` field or non-success `apply_labels`, `workpad_link`, `workpad_bind`, or `assignment` field as `dropped-failed`; on adoption, also record non-OK `checks`. When `checks` contains `closes-issue`, that reflection states that merging this PR will not close the issue, that a person must link or close it by hand, and that no later merge resolves it.
- `outcome=refused` — on a resume, set the workpad `Blocked`, emit 👎, and stop rather than risk a duplicate PR. On a fresh run only, retry once with the force-create mode below.
- `outcome=push-failed` or `outcome=create-failed` — set the workpad `Blocked` with the returned `cause`, emit 👎, and stop.
- silence, an unparseable record, or any unknown outcome — treat as `refused`.

Fresh-run refusal retry, and the only second call site:

```bash
.prflow/vendor/prflow/scripts/resolve-existing-pr.sh --open --force-create --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-existing-pr.sh --open --force-create --issue <issue-number> --title-file <title-file> --body-file <body-file>
```

Require `outcome=created`; route every other result through the terminal create-failure path above. Print `draft PR number: [<number>]` from the successful record for later phases.

#### Review reuse (resume only)

Skip this step on a fresh run (`resume_kind` null) or when the intake handoff retained any review-related correction or blocker. Otherwise run `workpad.py reuse-check $ISSUE_NUMBER review`. It matches only a clean full-coverage review recorded at the current head, merge-base and issue body, with its Review rows ticked.

- Exit 0 → `workpad.py update $ISSUE_NUMBER --adopt-reusable-review`. On `outcome=landed`, the coverage record is re-stamped from the stored review: skip §3.3's dispatch, carry the printed verdict into the remaining-work report (a caveat verdict keeps its residual findings from the workpad), perform the `phase-3-fix-loop.md` read for §3.3's CI-verdict read, then the `phase-3-ac-gate.md` read, and continue to §3.4. Any other outcome continues to §3.3.
- Exit 1, exit 2, or no output → continue to §3.3 and review normally.

<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md end -->

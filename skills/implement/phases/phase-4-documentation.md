<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md start -->
## Phase 4: Documentation

Output: `Phase 4/4: Documentation — updating docs and finalizing PR...`

### Dispatch finalization

The `prflow:implement-finalization` worker owns §4.0 through §4.3's tip-landed gate, loading `<skill-dir>/references/phase-4-finalization.md` itself. Keep that procedure, its child reports, workpad history, and worker transcript in the worker's context. This parent receives a compact result and retains publication and terminal handling below.

Dispatch with the Agent tool, `subagent_type: prflow:implement-finalization`, `run_in_background: false`, in this checkout with no worktree isolation and no context-fork/full-history option. Collect the completed result through the runner's native return channel; a launch acknowledgment is not a result. Perform no concurrent checkout mutation or workpad write while it runs.

Pass literal operands:

- `ISSUE_NUMBER` / `ARGUMENTS`, `PR_NUMBER`, `PR_URL`, `REPO_ROOT`, recorded `BRANCH`, current `ENTRY_HEAD`, base branch, `TIER`, run id / attempt (explicitly `unestablished` when absent), and a fresh `DISPATCH_ID` retained for validation.
- `SKILL_DIR`, `SCRIPTS`, `WORKPAD` and its invocation ladder, scratch arm/home and `RUN_SCRATCH`, `ISSUE_BODY_PATH` (required while a by-path child remains unfinished), issue title and current workpad ID. A targeted §4.3 resume after both children completed needs no deleted issue-body artifact. Resolved AC and intake-handoff paths are optional provenance only: earlier steps intentionally remove them on `NOT_IGNORED`; the worker reads current AC facts from the canonical workpad. Send paths, not issue/workpad bodies.
- Current actionable requirements, prior decisions, corrections, blockers and user constraints with their source references; review result, review-coverage/disposition evidence references and pending notes; checkpoint state and verification candidate/flight references. An unavailable operand is explicitly unestablished, never an invented success.
- `IMPLEMENT_EXTENSION_LOAD`: this entry's observed state/digest, unresolved load notes and trusted `DEVFLOW_PROMPT_EXTENSION_ROOT` when set. Include the run's injected engine-ground-truth block and its run-specific capability/verification constraints, with their source and observation state. Preserve the applicable verification mode, command and completion-evidence requirements from known consumer policy; explicitly name anything unestablished. Do not paste the root skill, phase procedures, or earlier conversation as the dispatch.

Append the identity/routing/evidence field bullets from **Validate the finalization result** below as the return contract; send no publication procedure.

### Validate the finalization result

The completed return is one compact JSON object with the contract below. It is returned directly, with evidence retained on the canonical workpad and referenced artifacts; no handoff file is written after final-tree verification, including on `NOT_IGNORED`.

- Identity: `schema_version: 1`, exact `dispatch_id`, `repo_root`, `issue_number`, `pr_number`, `pr_url`, `run_id`, `run_attempt`, `entry_head`, `workpad_id`; `branch` and `final_head` are the worker's final observed checkout values.
- Routing: `outcome` (`proceed`, `blocked`, `needs-confirmation`, `needs-recovery`, `error`), concise `reason`, exact pending `question` or null, `extension` (parent/worker states and digests, trusted root, pending notes), `warnings` and `unresolved_obligations` with source references. Stop records use null for unobserved values.
- Evidence: `steps` lists each owned step (§4.0, §4.0.5, §4.0.6, §4.1, §4.2, §4.3) with its observed disposition and workpad/artifact reference; `checkpoint4` carries its observed token and any admitted degradation; `verification` carries the recorded completion-evidence family, final candidate SHA, record/flight/run reference and successful workpad recording outcome; `review_coverage` carries the exact record and any required `{gap, cause_class, reason}` dispositions; `tip_landed` carries the observed outcome, comparands and any recorded degradation. Preserve a failed-and-continued step as that disposition, never rename it successful.

Reject a missing, malformed, stale, wrong-identity, incomplete or contradictory result; do not load the worker procedure/transcript or full workpad to reconstruct it. A `proceed` result requires every owned step accounted for under its existing procedure, recorded final-tree completion evidence, an admissible coverage record/dispositions, a passed or explicitly admitted checkpoint/tip degradation, and no unresolved blocking obligation. Validate the echoed parent state/digest and trusted root against the dispatch; compare digests only when both parent and worker observed them. An actual digest/root mismatch is an error. Preserve an unestablished load with its note and unticked-row disposition; it is not an empty extension or a successful load. A returned extension-incompletion stop is retained as a blocker, never auto-re-dispatched to reset the worker's retry limit. The worker must still establish the applicable verification policy and final-tree evidence before proceeding.

Before publication, independently read `git rev-parse --show-toplevel`, `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD`, `git status --porcelain`, and live workpad status through its helper. Require the dispatched checkout, the returned final HEAD/branch, an observed empty clean-tree result and an observed `interim` workpad status class from a successful helper call. An observed terminal class (`complete`, `blocked`, `failed` or `cancelled`) stops publication: preserve that status and perform the root's terminal handling without replaying finalization. A named branch must equal the recorded branch; a detached result is admissible only when the worker's existing tip gate recorded that detached arm with its required evidence. Require the verification candidate SHA to equal that final HEAD. Carry the validated coverage dispositions to the finalize call below. These checks bind the return; the existing workpad completion gate remains authoritative.

On a changed/unestablished checkout, unestablished workpad status, unusable result, failed dispatch, or `blocked`/`error`, record Blocked through the reachable workpad helper unless the live status is already terminal, then perform the root's terminal handling. Do not replay Phase 4 inline. `needs-confirmation` returns the exact question to this parent: ask and pause locally, or stop Blocked on cloud; no worker can supply human approval. `needs-recovery` returns the named missing canonical operand to root recovery; retain the worker's completed-step references and resume only the unmet step after recovery, never repeat already-landed filing/docs/description work blindly. A new dispatch uses a new ID and current HEAD. No publication follows a stopped result.

After a validated `proceed`, continue directly below; do not reload the phase or extension merely because the worker returned. Keep the compact warnings and required dispositions for the final workpad note and user report.

**Publish decision — `implement_pr_state`.** Resolve it as a single command and read the printed value from the tool result (default `ready_for_review`; a hard read failure — non-zero exit or no output — falls back to `ready_for_review`). Publish **only** when the value is not the exact literal `draft` — a missing key, empty string, or any unrecognized value publishes.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_implement.implement_pr_state ready_for_review
```

Carry an outcome value — one of `draft` | `published` | `publish_failed` — that the finalize wording below reads. Route on the resolved value read from the tool result:

- exactly `draft` — leave the PR the draft from Phase 3.1: do not run `gh pr ready`, post no additional comment to the PR thread, and set the outcome to `draft`.
- anything else — run `gh pr ready` and read its exit status from the tool result:
  ```bash
  gh pr ready
  ```
  - exit 0 — outcome `published`.
  - non-zero — `gh pr ready` returns non-zero on any *already non-draft* PR, so confirm the real state before concluding failure:
    ```bash
    gh pr view --json isDraft --jq '.isDraft'
    ```
    Read the printed value: exactly `false` → the PR is already non-draft → outcome `published` (idempotent re-run). Anything else, an error, or no output at all → outcome `publish_failed` (still a draft, or the state could not be confirmed) — fail closed, never record `published` on an unestablished read.

Then finalize the workpad — tick the final `## Progress` item and flip `Status` to `Complete` in every case; only the `--note` wording differs. Pick the `--note` by the outcome you carried:

- `draft` outcome → `--note "/prflow:implement run finished, PR left as draft per implement_pr_state=draft: <PR_URL>"`
- `published` outcome → `--note "/prflow:implement run finished, PR published (gh pr ready): <PR_URL>"`
- `publish_failed` outcome → `--note "/prflow:implement run finished, but gh pr ready FAILED — PR is still a draft, or its state could not be confirmed: <PR_URL>"` and emit a separate `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "gh pr ready failed at Phase 4.3 — PR left unpublished despite implement_pr_state not being draft; publish it manually (gh pr ready) so the cloud review and CI ready_for_review listener fire"` call. It is a `dropped-failed` reflection, so it goes in its own `update` call — separate from the `note`-kind finalize below — because one `--reflection-kind` applies to the whole call.

Substitute the outcome-specific `--note` above into the finalize call. The `--tick-progress "PR marked ready"` argument MUST match the `## Progress` row label owned by `scripts/workpad.py`. Consume the outcome line per the failure-isolation contract — only `remedy=none` or `remedy=reset-status` is cleanly Complete, and an absent line means the write did not land. The token tells the failures apart: (1) `remedy=retick-named-rows` / `remedy=retick-and-reset-status`, a volatile tick miss (body PATCHed, Status flipped, only the "PR marked ready" row still `- [ ]`) → re-tick just that row, adding `--status=Complete` again when the remedy names it; (1a) `outcome=precondition-mismatch` (`remedy=re-resolve-state`) → re-read the live workpad and re-decide, never re-send; (2) `outcome=not-persisted` (`remedy=reissue-call`), a structural abort (NO PATCH, Status NOT flipped) when a non-post-merge `## Acceptance Criteria` row is still unticked, or the review-coverage record is unestablished / a recorded gap / undispatched / boilerplate → resolve per Phase 3.4 (`--tick-ac-n {N}` or the Blocked path) or stamp/disposition the record per §3.3 (the undispatched arm has no in-run remedy → Blocked), THEN re-issue; never retry verbatim. (Post-merge AC rows never trip this; an unticked `## Plan` row or an un-mirrored AC placeholder only warns.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --status=Complete \
    --tick-progress "PR marked ready" \
    --note "{outcome-specific note above}" \
    [--review-coverage-disposition <gap> <cause-class> "<reason>" ...repeat per gap] \
    [--reflection-kind note --reflection "{noteworthy event}" ...repeat --reflection per event]
```

Add one `--reflection` flag per noteworthy event a human should know for troubleshooting: a failed step that was skipped, a subagent that returned no useful output, a permission denial, a test you couldn't run, an ambiguity you resolved with an assumption, or any deviation from the planned flow. Kind each by the reflection style contract's routing rule (see `skills/implement/SKILL.md`); genuinely actionable failures are emitted at the point they occur with `--reflection-kind dropped-failed` so they land under `### ⚠️ Action required`. `--reflection` is repeatable so all the same-kind events land in a single atomic update.

Finally, emit the 🎉 outcome reaction on the triggering comment (see *Outcome reaction* in the Workpad Reference) in every case, then output the PR URL and a one- or two-line summary of what was accomplished (state whether the PR was published, left a draft, or whether `gh pr ready` failed).

<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md end -->

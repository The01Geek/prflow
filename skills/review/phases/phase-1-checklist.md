<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md start -->
## Phase 1: Verification Checklist Generation

Output: `Phase 1/4: Generating verification checklist...`

Skip this entire phase (and Phase 2) when Phase 0.5 set `checklist_skipped = "intentional"` (small_diff AND config_only). Proceed directly to Phase 3. The verdict rule in 4.2 distinguishes this intentional skip from a checklist-gen failure.

### 1.1 Determine batching

Count the changed files. If 10 or fewer, launch one checklist-generator agent. If more than 10, split into batches of 10 (in Phase 0.3 document order), one agent per batch.

Hand off each batch's slice by file reference, not inline content — the `{DIFF_PATH}` pattern Phase 3 uses, extended to Phase 1. The slice content must never transit the orchestrator's context (that inline transit is the per-pass cost this removes, re-paid on every engine and shadow pass). Author each slice as a file on disk, passing the generator its *path*:

- Single batch (≤10 files): pass the cached full diff path `.prflow/tmp/review/<slug>/<run-id>/diff.patch` (from Phase 0.2) directly — **write no slice file.** There is only one batch, so its slice *is* the full diff.
- Multiple batches (>10 files): author each batch's slice from the already-cached `diff.patch` (never a fresh `git`/`gh` fetch — no `git` object access, so a shallow consumer checkout is unaffected). Phase 0.3 derived the file list from `diff.patch`'s `^diff --git` headers in document order, so batch _k_ (1-based) is exactly the _k_-th run of 10 `diff --git` sections — a numeric range taking no per-file filename arguments: its only operand is the fixed run-scoped `diff.patch` path, so no changed-file path is ever passed and spaces cannot break quoting. For batch _k_, with `s=(k-1)*10+1` and `e=k*10`, stream sections _s_ through _e_ through `tee` into the slice and read the printed section count from that invocation's own tool result — the engine root's shape discipline prefers `tee` to a `>` redirect, whose permitted rows were measured at older action/CLI versions and are unconfirmed since:

  ```bash
  awk -v s=1 -v e=10 '/^diff --git/{n++} n>=s && n<=e' .prflow/tmp/review/<slug>/<run-id>/diff.patch | tee .prflow/tmp/review/<slug>/<run-id>/batch-1.patch | grep -c '^diff --git'
  ```

  The `tee` stage authors the slice without the content passing through this orchestrator, so the by-reference handoff above holds for the authoring step too. Read the printed section count and confirm the slice landed:

  ```bash
  grep -c '^diff --git' .prflow/tmp/review/<slug>/<run-id>/batch-1.patch
  ```

  This exact recipe remains pinned by its behavioral fixture. Its evidence is recipe-specific; it is not a universal claim about other authoring shapes.

Fail-closed fallback. `awk` is not a preflight-guaranteed tool, so a batch's slice is usable only when both counts hold — the streamed count printed by the `tee` statement equals the number of files this batch owns, and the count taken from the authored file equals it too. Count the file, do not merely test that it is non-empty: `tee` keeps copying to stdout when its write fails, so the streamed count is satisfied by a slice that landed truncated or empty, and a non-emptiness test waves through a non-empty but thinned slice — the batch would then review a surface with missing files silently unrepresented. When either count falls below this batch's file total, or no count is printed at all, fall back to passing the full `diff.patch` path for that batch (coverage preserved, savings forfeited), and record the fallback in the run's telemetry notes (`step_2_6`/`phase_1` in `/prflow:review-and-fix`; chat in standalone). A fallback batch relies on the generator's retained scope instruction (items only for this batch's listed files) so the full diff cannot inflate cross-batch duplicates.

Because the pipeline reports its last stage's status, `awk`'s own exit status is not the discriminator here; the two counts are. Together they detect a truncation that crosses a header boundary and a failed or truncated write of the slice itself. The residual is the same one Phase 0.2 names: a truncation *within* a section, after its `diff --git` header and before its body, satisfies both counts with a thinned final section.

Tell each batch which files sibling batches handle, so it does not generate items for them.

Merge the resulting checklists by concatenating all items. If batching ran (>1 batch), proceed to Phase 1.5: Dedup before renumbering. If only one batch ran, renumber IDs sequentially (`VC-1`, `VC-2`, ...) and skip Phase 1.5.

In-batch sanity dedup still applies before Phase 1.5 hands the array off:
1. Same-claim dedup: drop items that make the same claim about the same `source_file`. "Same claim" = same defect/contract under scrutiny, not identical wording (e.g., the same path/format assertion in both batches → keep one). When Phase 1.5 runs this is mostly a no-op — the deduper does the heavy lifting via `claim_signature`.
2. Cross-cutting theme dedup: repo-wide checks — e.g. license/SPDX header conventions, naming or branding rules, `.gitignore` anchoring — should appear at most once each in the merged list, not per batch. Their category is "api_contract" by convention.

### 1.1.5 Cap and prioritize

If the merged-and-deduped checklist exceeds **100** items, sort by priority and keep the top 100:
1. `issue_acceptance` items — items whose claim cites an issue acceptance criterion (highest yield — these failing means the PR doesn't deliver the feature).
2. `absolute_claim` items (a diff-added universal the reviewer must *falsify* by constructing the offending input — the highest-value target because reading it confirms nothing; see `agents/checklist-generator.md`).
3. `dependency_interaction` items (cross-boundary contracts — highest drift risk).
4. `test_mock_alignment` items (mocks-vs-real divergence, a classic PR-killer).
5. `api_contract` items.
6. `data_format_assumption` items.

Sub-cap on rank 1: `issue_acceptance` items occupy **at most 25** of the 100 kept items, and the remaining 75 are filled from ranks 2 through 6 in the order above. Without this sub-cap an issue carrying dozens of criteria lets rank 1 consume the whole cap and evict the `absolute_claim`, `dependency_interaction`, and `test_mock_alignment` items this section calls the load-bearing signal — rank 1 had no producer until Phase 1.2 gained its acceptance-criteria block, so the eviction is a new hazard, not a historical one. An `issue_acceptance` item dropped by this sub-cap is counted in the drop summary's `by_category` map under the `issue_acceptance` key exactly like any other drop.

Drop items below the cap — a cost cap: every item triggers a verifier subagent in Phase 2. Medium PRs have produced 150+ items on doc-heavy diffs, but the load-bearing signal (cross-boundary contracts, mock-vs-real divergence, issue acceptance) is usually captured well within 100. Announce the cap in chat: `Capped checklist at 100 of {N} items (dropped {M} items by category: dependency_interaction: K1, api_contract: K2, ...; issue_acceptance kept: {A} of 25; priority kept: issue-acceptance, dependency_interaction, ...).` so the reader sees which categories took the hit, not merely that coverage was truncated. That announcement reports the `issue_acceptance kept: {A} of 25` count alongside the per-category drops, so a reader sees the sub-cap acting rather than inferring it. (In `/prflow:review-and-fix` mode this data also lands in the workpad's `cap_drops` block and the report's `## Coverage` section; in standalone `/prflow:review` runs the chat announcement is the only surface.)

Record what was dropped. When the cap fires, return a per-category summary of dropped items so the orchestrator can surface coverage gaps (the fix-loop wrapper also records it in the workpad — see `cap_drops` in `/prflow:review-and-fix`'s workpad schema). Compute and return alongside the truncated checklist:

```json
{
  "count": M,
  "by_category": {
    "dependency_interaction": K1,
    "api_contract": K2,
    "test_mock_alignment": K3,
    "data_format_assumption": K4,
    "...": "..."
  }
}
```

where `M` is the total dropped count (`N - 100`) and per-category counts sum to `M`. If the cap did not fire, return `{"count": 0, "by_category": {}}`. The orchestrator stores this for the `## Coverage` report section in `/prflow:review-and-fix` and the standalone `/prflow:review` chat announcement.

### 1.2 Launch checklist-generator agent(s)

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway); it is deliberately not restated here.

Use the Agent tool with `subagent_type: "prflow:checklist-generator"`. First resolve overrides for `prflow:checklist-generator` per Per-Subagent Model/Effort Overrides above, applying any resolved `model` as the Agent tool's `model` override.

Pass the following prompt — carrying the slice's file path (from Phase 1.1), never inline diff content:
```
The diff you must analyze is cached on disk. Read it directly with your Read tool — it is NOT inlined here.

Diff path: {SLICE_PATH}
  (In a >1-batch run this is your batch's slice — only your batch's files. On the fail-closed fallback, or in a single-batch run, it is the full cached diff `.prflow/tmp/review/<slug>/<run-id>/diff.patch`.)

Changed files to analyze:
{paste the file list here}

Generate the verification checklist ONLY for the changed files listed above — even if the diff at that path contains other files (a fallback slice is the full diff). Return the JSON array in a ```json code fence.
```
Substitute `{SLICE_PATH}` with the batch's slice path (`.prflow/tmp/review/<slug>/<run-id>/batch-<k>.patch`), or the full `diff.patch` path on a single-batch run or the Phase 1.1 fail-closed fallback. In a >1-batch run, also name the sibling batches' files (per Phase 1.1).

If `issue_context` is not empty, append this to the prompt:

```
The following GitHub issue describes the intended behavior for this PR. In addition to code-correctness items, include checklist items that verify the PR implements the key requirements from the issue's summary and desired behavior sections. Focus on functional requirements — not stylistic suggestions or background context in the issue.

<issue>
Title: {issue_title}
Body (first 200 lines):
{truncated_issue_body}
</issue>
```

If `acceptance_criteria` is not empty, append this to the prompt as well — this block and the `issue_context` block above are gated independently, and neither block's absence suppresses the other:

```
The block below is this PR's specification — not background, and not the narrative issue body. It carries the acceptance criteria resolved for this run (Phase 0.4), already post-merge-filtered and rendered box-neutral. Emit one checklist item per criterion listed below, each tagged `"category": "issue_acceptance"`, with a claim that cites that criterion. The `<issue>` block above, when present, is background that orients you; this block is what the PR must deliver.

<acceptance_criteria source="{acceptance_criteria_source}">
{acceptance_criteria}
</acceptance_criteria>
```

If the caller is `/prflow:review-and-fix` on iteration N≥2 (the fix-loop wrapper supplies `prior_checklist` from `iter-<N-1>.json`), append this to the prompt:

```
This is iteration N (N≥2) of an auto-fix loop. The previous iteration's verification checklist is supplied below. Operate in variance-recovery mode per your agent contract (Step 2b):

- Generate claims NOT already present in the prior checklist (dedup against `claim_signature`).
- Prioritize claim categories that are underrepresented in the prior iteration.
- The goal is variance recovery — surfacing what a second-look pass would catch — NOT re-litigation of items already considered.

Return an empty JSON array `[]` if a second pass surfaces nothing new.

<prior_checklist iteration="N-1">
{paste the iter-(N-1) checklist JSON — id, category, claim, source_file, claim_signature, verdict}
</prior_checklist>
```

### 1.3 Parse the checklist

Extract the JSON array from the agent's response (look for the ```json code fence).

If the agent fails or returns malformed JSON, retry once. If it fails again, log: "Verification checklist generation failed. Proceeding with existing agents only." Set a `checklist_skipped` flag and skip to Phase 3.

Store the parsed checklist items for Phase 1.5 (if batched) or Phase 2 (if single-batch).

Output: `Generated {N} verification checklist items.`

---

## Phase 1.5: Dedup (only when Phase 1 ran in >1 batch)

When Phase 1 ran a single generator batch, skip this phase entirely — there are no cross-batch duplicates to resolve.

When Phase 1 ran in 2+ batches, dedupe via the `prflow:checklist-deduper` agent, not manually. Manual cross-batch dedup is bias-prone (real-run telemetry: collapsing ~70 items to ~40 by hand consistently dropped 3–6 distinct items per run).

Output: `Phase 1.5/4: Deduping checklist across {B} batches...`

### 1.5.1 Launch the deduper agent

Use the Agent tool with `subagent_type: "prflow:checklist-deduper"`. Resolve overrides for `prflow:checklist-deduper` per Per-Subagent Model/Effort Overrides above, applying any resolved `model` as the Agent tool's `model` override.

Concatenate the raw checklist items from all batches into a single JSON array. Preserve each item's original `id` and tag it with its source batch so traceability survives — prefix each `id` with `batch{K}:` (e.g. `batch1:VC-3`, `batch2:VC-1`) before passing to the deduper.

Pass the following prompt:
```
Here is the concatenated raw checklist from {B} generator batches. Merge duplicates per your dedup rules and return the deduped JSON array. Preserve `merged_from` provenance on every surviving item.

<raw_checklist>
{paste the JSON array of all items from all batches, with batch-prefixed ids}
</raw_checklist>
```

### 1.5.2 Parse the deduped checklist

Extract the JSON array from the deduper's response (look for the ```json code fence). The output array uses fresh sequential IDs (`VC-1`, `VC-2`, ...) and records `merged_from` on each item.

If the deduper agent fails or returns malformed JSON, retry once. If it fails again, fall back to manual cross-batch dedup using the In-batch sanity dedup rules from Phase 1.1 — do NOT block the engine on dedup failure.

Output: `Deduped to {N_after} of {N_before} items.`
<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md end -->

<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md start -->
## Phase 1: Verification Checklist Generation

Output: `Phase 1/4: Generating verification checklist...`

Skip this entire phase (and Phase 2) when Phase 0.5 set `checklist_skipped = "intentional"` (small_diff AND config_only). Dispatch the prepared Phase 3.1 reviewers alone, then resume §3.1.5/§3.2. The verdict rule in 4.2 distinguishes this intentional skip from a checklist-gen failure.

### Work directory and assembly helper

Phase 1's intermediates live in `<work-dir>` = `.prflow/tmp/review/<slug>/<run-id>/phase1-<token>` — the setup record's `phase1_work_dir`, already created. Without a record, generate `<token>` — 8 or more unpredictable alphanumeric characters (the helper refuses fewer) — fresh at this phase entry and never reuse another entry's: a re-entrant entry shares `<run-id>` and `<N>`, and the token is what keeps it from reading this entry's files.

Checklist JSON is assembled by `scripts/normalize-verdicts.py checklist <op> …`, not re-typed by you — the refused-Write arm (§1.3) and **Helper unavailable** below are the two exceptions: generators Write their own batch files, the deduper names merge groups by id, and the helper carries, concatenates, merges, renumbers, caps, tags and writes the artifact. Emit the vendored literal `.prflow/vendor/prflow/scripts/normalize-verdicts.py checklist <op> …` as a single leading-token statement first; on a `command not found` / `No such file` / exit-127 reading, fall back to the portable anchor `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/normalize-verdicts.py checklist <op> …`; on a local-tier denial of the path-invoked form, `python3 <resolved helper path> checklist <op> …`. Substitute every operand literally (no `$VAR`, no redirect) and read the printed JSON object from the tool result — `ok` carries the outcome.

**Helper unavailable.** Only when the helper cannot run — every rung is refused, or it prints no JSON object — assemble by hand instead: Read the batch files, set aside every `issue_acceptance` hint, apply the §1.0, §1.5 and §1.1.5 rules to the rest, then append one `issue_acceptance` item per entry of `<run-dir>/criteria.json` — `verification_mode: "agent"`, `claim_provenance: "generated_paraphrase"`, the entry's `text` verbatim as `claim`, `claim_signature` `issue-acceptance-<criterion>`, and, from the first hint whose integer `criterion` matches, each of `source_file`, `source_line` and `verify_hint` it validly carries, with a `verify_hint` naming `<run-dir>/diff.patch` when it carries none — and Write the §1.6 artifact with the Write tool. The checklist-side acceptance count is that file's entry count. When that file is present but is not a non-empty array of `{"criterion": <integer>, "text": <non-empty string>}` objects numbered 1 to K in order, or is absent while `acceptance_criteria_count` is non-zero, append no `issue_acceptance` item and record `checklist_criteria_error` naming the failure.

**Integrity stop.** A helper that ran and returned `ok: false` is never hand-assembled around. `bad_batch` retries its generator (§1.3), `bad_groups` its deduper (§1.5.2), and `usage` means an operand is wrong — correct it and re-run. Any other `error` (`merge_invariant_violation`, `conservation_violation`, `bad_carried`, `artifact_write_unverified`, `helper_internal_error`) means the checklist's integrity is unestablished: log the `error` and its `detail` and take §1.3's double-failure arm.

### 1.0 Carry prior items forward (fix-loop callers only)

Skip this step unless `/prflow:review-and-fix` supplied both the iter-(N-1) checklist (`prior_checklist`) and that iteration's reviewed head (`prior_diff_head`). A standalone run, iteration 1, the Step 2.6 shadow, and an iteration whose predecessor was promoted or skipped Phase 1+2 each receive neither: they carry nothing forward and reuse no verdict.

Run `checklist carry <work-dir> <N> <prior_diff_head>` (the commit id as a literal). It reads the prior entry's snapshot pair in the run directory — `checklist-step1-iter-<N-1>.json` joined by `id` with the verdict rows of `verification-step1-iter-<N-1>.json` — or, with `--prior <path>`, that file's already-joined items; applies the rule and tags below; and writes `<work-dir>/carried.json`. An unusable snapshot carries nothing and prints `carry-forward: none (<file> <shape>)`; a citation split that cannot load prints `carry-forward: reuse off (<cause>)`, and one that fails on some items prints `carry-forward: reuse skipped for <n> item(s) (<ids>)`; affected items verify fresh. Log any of these.

The helper establishes the changed-file set — what moved between the prior iteration's reviewed head and this one — with `git diff --name-only --no-renames <prior_diff_head> HEAD`, and fails closed when it cannot: `prior_diff_head` does not resolve (as in a shallow cloud checkout), or the `git diff` exits non-zero. It then carries nothing and prints the breadcrumb `carry-forward: none (<cause>)` — log it. An exit-0 empty output is a genuinely empty changed set, not a failure. An absent `prior_diff_head` never reaches here — this step is skipped and the loop logs that cause itself.

**Carry a prior item** iff all three hold: its `category` is not `issue_acceptance`; its `source_file` is in this run's Phase 0.3 changed-file list; and its `source_file` is not in the changed-file set above. A carried item keeps its prior `id` and `claim_signature`. It reuses its prior PASS only when its verification row's `verdict` is `PASS` and every path its `file_checked` cites (the whole value, else each part split on `;`, `,` or ` and `, then on whitespace if every piece is tracked; anchor lists removed) is a regular file tracked at HEAD, spelled as git records it, and outside the changed-file set — evidence the collector's provenance gate can re-bind to this head; any other citation (`null`, free text, `./` or `..` spellings, a symlink, an untracked or changed path) verifies fresh. A reused PASS can still rest on an unchanged file whose cross-file dependency moved; Phase 3 over the whole diff is the check on that.

The carried items — never the full prior array — are the `prior_checklist` §1.2 hands the generator, by the `carried.json` path, so its signature drop reaches only carried claims and a claim about a changed file is emitted fresh.

§1.6 merges them back after §1.1.5: every carried item is appended to the capped new-item array, and each new item gets an `id` distinct from every carried `id`. Carried items are exempt from the 100-item cap, which applies to the generator's new items alone.

Every item is tagged:

| Item | Fields it carries |
|---|---|
| Carried, reusing its PASS | `reused_from_iter_prev: true`; `reused_from_iter` — the prior item's own `reused_from_iter` when it had one, else N-1; plus the row's `verdict`, `evidence`, `file_checked` and, when present, `raw_verdict`, `normalized`, `normalization_ineligible` and `view_revision` |
| Carried, not reusing | `reused_from_iter_prev: false`, no `reused_from_iter` and no prior verdict fields — Phase 2 verifies it fresh |
| Generator's new item | `reused_from_iter_prev: false`, no `reused_from_iter` |

Output the helper's `announce` line: `Carried {C} of {P} prior items forward ({R} reusing a prior PASS); generating the rest fresh.`

### 1.1 Determine batching

Count the changed files. If 10 or fewer, launch one checklist-generator agent. If more than 10, split into batches of 10 (in Phase 0.3 document order), one agent per batch.

Hand off each batch's slice by file reference, not inline content — the `{DIFF_PATH}` pattern Phase 3 uses, extended to Phase 1. The slice content must never transit the orchestrator's context. Each slice is a file on disk; the generator gets its *path*:

- Record arm (setup record present): its `batches` is the split — each entry's `first`..`last` are 1-based inclusive positions into the record's `files` (that batch's file list) and `slice` is `{SLICE_PATH}`; a single batch's `slice` is `diff.patch` itself. Author nothing. A batch whose `slice` is `unavailable` takes the fence arm below for that batch alone.
- Fence arm (no record): count the files yourself and author each slice:
  - Single batch (≤10 files): pass the cached full diff path `.prflow/tmp/review/<slug>/<run-id>/diff.patch` (from Phase 0.2) directly — **write no slice file.**
  - Multiple batches (>10 files): author each batch's slice from the already-cached `diff.patch` (never a fresh `git`/`gh` fetch). Phase 0.3 derived the file list from `diff.patch`'s `^diff --git` headers in document order, so batch _k_ (1-based) is exactly the _k_-th run of 10 `diff --git` sections — a numeric range taking no per-file filename arguments: its only operand is the fixed run-scoped `diff.patch` path, so no changed-file path is ever passed and spaces cannot break quoting. For batch _k_, with `s=(k-1)*10+1` and `e=k*10`, stream sections _s_ through _e_ through `tee` into the slice and read the printed section count from that invocation's own tool result:

  ```bash
  awk -v s=1 -v e=10 '/^diff --git/{n++} n>=s && n<=e' .prflow/tmp/review/<slug>/<run-id>/diff.patch | tee .prflow/tmp/review/<slug>/<run-id>/batch-1.patch | grep -c '^diff --git'
  ```

  Read the printed section count and confirm the slice landed:

  ```bash
  grep -c '^diff --git' .prflow/tmp/review/<slug>/<run-id>/batch-1.patch
  ```

Fail-closed fallback. `awk` is not a preflight-guaranteed tool, so a batch's slice is usable only when both counts hold — the streamed count printed by the `tee` statement equals the number of files this batch owns, and the count taken from the authored file equals it too. Count the file, do not merely test that it is non-empty. When either count falls below this batch's file total, or no count is printed at all, fall back to passing the full `diff.patch` path for that batch, and record the fallback in the run's telemetry notes (`step_2_6`/`phase_1` in `/prflow:review-and-fix`; chat in standalone).

Tell each batch which files sibling batches handle.

If batching ran (>1 batch), Phase 1.5 dedups across batches before §1.6 renumbers. If only one batch ran, skip Phase 1.5 — §1.6 renumbers IDs sequentially (`VC-1`, `VC-2`, ...). Same-claim and cross-cutting-theme duplicates are the generator's to avoid within a batch and the deduper's to merge across batches.

### 1.1.5 Cap and prioritize

§1.6's `finalize` applies this step. The population it caps is the generator's new non-acceptance items; §1.0's carried items and the acceptance items `finalize` builds from `criteria.json` are exempt and are appended after it. If that population exceeds **100** items, it keeps the top 100 by priority (a category outside the list ranks last):
1. `absolute_claim` items (a diff-added universal the reviewer must *falsify* by constructing the offending input; see `agents/checklist-generator.md`).
2. `dependency_interaction` items (cross-boundary contracts).
3. `test_mock_alignment` items (mocks-vs-real divergence).
4. `api_contract` items.
5. `data_format_assumption` items.

Items below the cap are dropped. Announce the cap in chat (the helper's `announce` carries the line): `Capped checklist at 100 of {N} items (dropped {M} items by category: dependency_interaction: K1, api_contract: K2, ...; priority kept: absolute_claim, dependency_interaction, ...).`, and separately `Itemized {K} acceptance criteria (no cap).` (In `/prflow:review-and-fix` mode this data also lands in the workpad's `cap_drops` block and the report's `## Coverage` section; in standalone `/prflow:review` runs the chat announcement is the only surface.)

Record what was dropped. When the cap fires, return a per-category summary of dropped items (the fix-loop wrapper also records it in the workpad — see `cap_drops` in `/prflow:review-and-fix`'s workpad schema) — the helper's `cap_drops` object, returned alongside the truncated checklist:

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

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

Use the Agent tool with `subagent_type: "prflow:checklist-generator"` and `run_in_background: false`, retries included. Resolve its overrides per Per-Subagent Model/Effort Overrides above, applying any resolved `model` as the Agent tool's `model` override. Compose the generator calls and Phase 3.1's prepared selected reviewer calls, the reviewer calls alone with `run_in_background: true`, before dispatch; emit them in the same message before any blocking collection. Keep the reviewer handles for §3.2; generator retries do not repeat that initial reviewer dispatch.

Pass the following prompt — carrying the slice's file path (from Phase 1.1), never inline diff content:
```
The diff you must analyze is cached on disk. Read it directly with your Read tool — it is NOT inlined here.

Diff path: {SLICE_PATH}
  (In a >1-batch run this is your batch's slice — only your batch's files. On the fail-closed fallback, or in a single-batch run, it is the full cached diff `.prflow/tmp/review/<slug>/<run-id>/diff.patch`.)

Output path: {OUT_PATH}

Head view: {§0.2.8 {VIEW_HEAD} (revision {VIEW_HEAD_REV}); else "none (read the working tree)"}

Changed files to analyze:
{paste the file list here}

Generate the verification checklist ONLY for the changed files listed above — even if the diff at that path contains other files (a fallback slice is the full diff). Write the JSON array to the output path with your Write tool and reply with the item count only.
```
Substitute `{SLICE_PATH}` with the batch's slice path (`.prflow/tmp/review/<slug>/<run-id>/batch-<k>.patch`), or the full `diff.patch` path on a single-batch run or the Phase 1.1 fail-closed fallback, `{OUT_PATH}` with `<work-dir>/batch-<k>.json` (`batch-1.json` on a single-batch run), and the `Head view` operands with §0.2.8's `{VIEW_HEAD}` and `{VIEW_HEAD_REV}` as literals — the generator reads the changed files from that view, not the checkout. In a >1-batch run, also name the sibling batches' files (per Phase 1.1).

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
The block below is this PR's specification — not background, and not the narrative issue body. It carries the acceptance criteria resolved for this run (Phase 0.4), already post-merge-filtered and rendered box-neutral. Criterion N is the N-th line below. For each criterion the diff touches, emit one location hint: an item tagged `"category": "issue_acceptance"` with the integer `"criterion": N`, a claim citing it, the `source_file`/`source_line` where the diff meets it, and a `verify_hint`. The review itemizes every criterion itself; a hint only locates one, so skip a criterion you cannot locate. The `<issue>` block above, when present, is background that orients you; this block is what the PR must deliver.

<acceptance_criteria source="{acceptance_criteria_source}">
{acceptance_criteria}
</acceptance_criteria>
```

If the caller is `/prflow:review-and-fix` on iteration N≥2 and §1.0 carried at least one item, append this to the prompt — it names §1.0's carried items by path, never the full iter-(N-1) array and never pasted:

```
This is iteration N (N≥2) of an auto-fix loop. The items carried forward from the previous iteration are in the JSON file named below — Read it. Operate in variance-recovery mode per your agent contract (Step 2b):

- Generate claims NOT already present in the prior checklist (dedup against `claim_signature`), except an `issue_acceptance` location hint, which you always emit fresh.
- Prioritize claim categories that are underrepresented in the prior iteration.
- The goal is variance recovery — surfacing what a second-look pass would catch — NOT re-litigation of items already considered.

Write an empty JSON array `[]` if a second pass surfaces nothing new.

Prior checklist path: {CARRIED_PATH}
```
Substitute `{CARRIED_PATH}` with `<work-dir>/carried.json`.

### 1.3 Collect the batches

Each generator Writes its array to its `{OUT_PATH}` and replies with a count, keeping the array out of your context. A generator whose Write was refused instead returns the array in a ```json code fence — Write that array verbatim to its `{OUT_PATH}`.

`checklist raw` (Phase 1.5) and `checklist finalize` (§1.6) validate every batch file and name a missing or malformed one — including one holding an item without a `claim` or `category` — in `bad_batches` with `error: "bad_batch"`. If the agent fails or its batch is reported bad, retry it once. If it fails again, log: "Verification checklist generation failed. Proceeding with existing agents only." Set `checklist_skipped = "failure"` and skip to Phase 3. On this double-failure arm append the record to the run-scoped phase log — `printf 'checklist-skip reason=failure\n' | tee -a .prflow/tmp/review/<slug>/<run-id>/phase-log` — so the workflow-side evidence gate reads this as a legitimate no-checklist arm rather than a hollow verdict.

Output (from §1.6's `announce`): `Generated {N} verification checklist items.`

---

## Phase 1.5: Dedup (only when Phase 1 ran in >1 batch)

When Phase 1 ran a single generator batch, skip this phase entirely.

When Phase 1 ran in 2+ batches, dedupe via the `prflow:checklist-deduper` agent, not manually.

Output: `Phase 1.5/4: Deduping checklist across {B} batches...`

### 1.5.1 Launch the deduper agent

First run `checklist raw <work-dir> <B>`: it concatenates the {B} batch files into `<work-dir>/raw.json`, giving each item the batch-tagged id `batch{K}:VC-{i}` (e.g. `batch1:VC-3`, `batch2:VC-1`).

Then use the Agent tool with `subagent_type: "prflow:checklist-deduper"` and `run_in_background: false`, its retry included. Resolve overrides for `prflow:checklist-deduper` per Per-Subagent Model/Effort Overrides above, applying any resolved `model` as the Agent tool's `model` override.

Pass the following prompt — the path, never the array:
```
The concatenated raw checklist from {B} generator batches is cached on disk. Read it with your Read tool — it is NOT inlined here.

Raw checklist path: {RAW_PATH}

Return the merge groups per your dedup rules.
```
Substitute `{RAW_PATH}` with `<work-dir>/raw.json`.

### 1.5.2 Record the merge groups

Extract the JSON array of merge groups from the deduper's response (look for the ```json code fence) and Write it verbatim to `<work-dir>/groups.json`; `[]` means nothing merged. §1.6 applies the groups — representative, provenance reconciliation, `merged_from`, fresh sequential IDs. It ignores an id `raw.json` lacks, and leaves unmerged — all members kept, a breadcrumb naming them — a group whose members share no `claim_signature`, no same-file same-category nearby range and no convention slug, since a kept duplicate costs one verifier and a wrongly merged member's claim leaves the checklist.

If the deduper agent fails or returns malformed JSON, or `finalize` reports `bad_groups`, re-run `checklist raw` and retry the deduper once. If it fails again, run §1.6's `finalize` with `--no-groups`, which merges identical `claim_signature` + `source_file` pairs only — do NOT block the engine on dedup failure.

Output (from §1.6's `announce`): `Deduped to {N_after} of {N_before} items.`

---

## Phase 1.6: Write the durable checklist artifact

Run `checklist finalize <work-dir> <N> <B>` (`<B>` the batch count). It assembles the final checklist array — post-dedup, post-cap, post-§1.0 merge and tagging, the exact array Phase 2 will verify — and writes it to `.prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json`, where `<slug>/<run-id>` is this run's run-scoped directory from Phase 0.2 and `<N>` is the engine iteration (`1` on a standalone `/prflow:review` run; the fix-loop-supplied iteration otherwise). Phase 2 reads this file, so a checklist-owing run that skips this step leaves Phase 2 with no checklist to verify. Before writing, the helper traces every generated item by id — each must sit in exactly one written or capped item's `merged_from` — checks the carried tail and `id` uniqueness, and reads the written file back; on a violation it writes no checklist and returns `ok: false` (Integrity stop above). An item missing `source_file`, `claim_signature` or a known `verification_mode` is kept and listed in `flagged_items`. **The file root is the array itself, never an object wrapping it** — a `{"checklist": [...]}` wrapper grades `review-artifact-malformed`, since the evidence gate reads the root and never unwraps. An empty array `[]` is a valid artifact — a generator that legitimately returns nothing still writes the file. This write happens on the single-batch, multi-batch, and all-lite paths alike. The `checklist_skipped = "failure"` double-failure arm (§1.3) writes NO artifact and keeps its existing `checklist-skip reason=failure` phase-log record instead.

`finalize` returns `issue_acceptance_count` (the acceptance items it built, one per `criteria.json` entry) and `criteria_error` (null, or why a present `criteria.json` could not be itemized). Hold them as `checklist_acceptance_count` and `checklist_criteria_error` for Phase 4; on the helper-unavailable arm, hold that arm's own count and error instead.

### 1.6.1 Update the progress comment (PR-comment surface)

When this run holds a live progress comment (`$WP` set), tick the Phase 1 Blueprint row once the checklist artifact is written; skip this step entirely when `$WP` is unset. A refused or failed command gets a `::warning::` and never stops the review. Emit the vendored literal `.prflow/vendor/prflow/scripts/workpad.py progress <comment-id> --tick "Generate verification checklist"` as a single leading-token statement first; on a `command not found` / `No such file` / exit-127 reading, fall back to the portable anchor `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py progress <comment-id> --tick "Generate verification checklist"` as a single leading-token statement.

Substitute `<comment-id>` with the held `$WP` value as a literal — never `$WP` in the command.
<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md end -->

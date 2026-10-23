<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md start -->
## Phase 1: Verification Checklist Generation

Output: `Phase 1/4: Generating verification checklist...`

When Phase 0.5 set `checklist_skipped = "intentional"` (small_diff AND config_only), run §1.0.5 first: when it adds the seed dispatch, clear `checklist_skipped` and run this phase and Phase 2. Otherwise skip both, §1.0 included: dispatch the prepared Phase 3.1 reviewers alone, then resume §3.1.5/§3.2. The verdict rule in 4.2 distinguishes this intentional skip from a checklist-gen failure.

`<work-dir>` is the setup record's `phase1_work_dir`. The helper assembles all checklist JSON; never re-type it. Read the JSON object each `checklist` call prints and output every `announce` line; `usage` means an operand is wrong — correct it and re-run.

### 1.0 Carry prior items forward (fix-loop iteration N≥2)

Only when `/prflow:review-and-fix` supplied `prior_diff_head` (for example, a standalone run, iteration 1 and the shadow receive none and carry nothing):

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py checklist carry <work-dir> <N> <prior_diff_head>
```

It writes `<work-dir>/carried.json`: the PASSes of the newest earlier iteration that ran Step 1 whose cited lines are provably unchanged, each reusing its verdict; nothing else carries (rules: the helper's docstring). Log every `carry-forward:` line it prints; any outcome but `ok: true` carries nothing. Carried items are exempt from the cap and keep their ids.

### 1.0.5 Seed the prior report's defects (PR mode)

On a `standalone` or `primary` entry in PR mode, never the shadow:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py checklist prior <work-dir> <PR> <N> --exclude-comment <comment-id>
```

`<comment-id>` is the held `$WP`; drop the flag when `$WP` is unset. It writes the PR's newest finished report by a trusted author to `<work-dir>/prior-report.md` and records the outcome for Phase 4. Log `prior_report` and `breadcrumbs`. A non-null `selected` adds §1.2's seed dispatch; any failure but `usage` adds none.

### 1.1 Batches

The setup record's `batches` is the split: batch k owns `files` rows `first`..`last`, and its `slice` is its diff (the whole `diff.patch` for one batch). A batch whose `slice` is `unavailable` takes the whole `diff.patch` plus a `Files:` line listing its rows' paths.

### 1.2 Launch the generators

In one message, launch one `prflow:checklist-generator` Agent call per batch (`run_in_background: false`, retries too, with the resolved `model` override) together with Phase 3.1's prepared reviewer calls (`run_in_background: true`; keep their handles for §3.2; a generator retry never repeats them). Keep each generator dispatch's Agent ID with its batch, or the seed, and attempt. Each generator's prompt is only:

```
Brief: {BRIEF_PATH}
Diff: {slice}
Output: <work-dir>/batch-<k>.json
```

On iteration N≥2 with a non-empty `carried.json`, add `Carried: <work-dir>/carried.json`.

When §1.0.5 selected a report, add one seed dispatch to the same message; never give the report or `seeded.json` to another generator. It is not a batch (`<B>` excludes it); retry it once when it fails or writes no `seeded.json`:

```
Seed mode. Prior report: <work-dir>/prior-report.md
Brief: {BRIEF_PATH}
Output: <work-dir>/seeded.json
```

With no brief, replace each prompt's `Brief:` line with `Brief: none` and `Head view: {VIEW_HEAD}`.

When no command-shape table reached you (the local tier, where Agent calls return before their result), end the message, and each §1.2 or §1.3 retry message, with one foreground Bash call (timeout 600000 ms) naming its batches, plus `seeded` with a seed dispatch:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py wait --verdicts-dir <work-dir> --expect batch-1 … batch-<B> --deadline 540
```

While a reply §1.3 collects is still missing, follow that wait with one foreground hold per message:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py wait --verdicts-dir <work-dir> --expect hold --deadline <s>
```

Each message's wait opens a 540-second window for the dispatches it launched, spent by that wait's `waited_s` and each later hold's; `<s>` is 30, or fewer when fewer remain of the latest window. That window ends when none remain, or when a hold prints a `waited_s` of 0 or none or a wait prints none; log any stderr a wait or hold printed. A call refused as `usage` ends no window: correct its operand and re-run.

### 1.3 Collect

Before §1.6, collect the reply of each batch's and the seed's current dispatch, counting a reply only for the dispatch whose Agent ID it carries; log "Late reply from an earlier dispatch of <batch k or the seed>; ignored." for an earlier attempt's reply. A generator Writes its array and replies with a count. A counted reply whose generator's Write was refused carries the array in a `json` fence: Write it verbatim to its output path. Locally, a generator whose reply is not in hand when the call ending its window returns has failed: log "Checklist generator for <batch k or the seed> sent no reply in its window; that dispatch may still write <its output path>."; retry none whose reply is missing before then. Retry a generator that fails, or whose batch `finalize` reports in `bad_batches`, once, sending retries together only when every awaited reply is in hand or its window has ended; a seed retry that fails stops blocking §1.6. If a batch fails again, log "Verification checklist generation failed. Proceeding with existing agents only.", set `checklist_skipped = "failure"`, record it, and skip to Phase 3:

```bash
printf 'checklist-skip reason=failure\n' | tee -a .prflow/tmp/review/<slug>/<run-id>/phase-log
```

### 1.6 Write the checklist artifact

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py checklist finalize <work-dir> <N> <B>
```

`<B>` is the batch count; `<N>` is the engine iteration (`1` on a standalone run). It merges identical claims across batches, drops new items restating a carried or seeded item, caps new non-acceptance items at 100 by category priority, builds one `issue_acceptance` item per `criteria.json` criterion, appends the seeded and carried items, and writes `.prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json` — the array Phase 2 verifies. Hold its `cap_drops`, `issue_acceptance_count` (as `checklist_acceptance_count`) and `criteria_error` (as `checklist_criteria_error`) for Phase 4. `bad_batch` takes §1.3's retry; any other `ok: false`, or no JSON, takes §1.3's double-failure arm, logging `error` and `detail`.

With `$WP` set, tick the progress row (a failure gets a `::warning::` and never stops the review):

```bash
.prflow/vendor/prflow/scripts/workpad.py progress <comment-id> --tick "Generate verification checklist"
```
<!-- prflow:review-ref phase=1 file=skills/review/phases/phase-1-checklist.md end -->

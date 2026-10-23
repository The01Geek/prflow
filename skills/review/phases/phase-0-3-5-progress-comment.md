<!-- prflow:review-ref phase=0.3.5 file=skills/review/phases/phase-0-3-5-progress-comment.md start -->

The engine keeps one `prflow:review-progress` PR comment per run, keyed by the run marker and updated in place: a blueprint up front, per-phase results, then the report. Every write is best-effort: report a failure and continue to the verdict.

Workflow pre-seed. When your prompt carries `Pre-seeded progress comment id`, `Pre-seeded progress comment marker` and `Pre-seeded run link` values, hold them as `$WP`, `$MARKER` and `$RUN_URL` and skip the seed.

Seed. Write the template below, from its H1, to `.prflow/tmp/review/<slug>/<run-id>/review-wp.md` with the Write tool, then run:

```bash
.prflow/vendor/prflow/scripts/seed-review-progress.sh <pr-number> <marker-slot> .prflow/tmp/review/<slug>/<run-id>/review-wp.md ; echo "seed-done"
```

Render `<marker-slot>` as `"<!-- prflow:review-progress run=<run-id> -->"` with the held run key (a cloud run's helper derives its own marker). `RESUME <id>` or `CREATED <id>`, one `MARKER <literal>` line, one `RUNLINK <literal>` line, `seed-done` and no stderr → hold `$WP`, `$MARKER` and `$RUN_URL` exactly as reported; on `CREATED` the helper wrote the marker as line 1 and the `**Run:**` line. A not-found reading takes the root's anchor retry. Any other reading — a `SKIP <reason>` line, no output, a malformed or missing line — leaves `$WP` unset: emit a `::warning::` quoting what you saw and continue without the comment; never retry it or create a comment by hand.

Rewrite. With `$WP` set, re-author `review-wp.md` (the held `$MARKER` as line 1, then the template from its H1) and run:

```bash
.prflow/vendor/prflow/scripts/workpad.py patch <wp> .prflow/tmp/review/<slug>/<run-id>/review-wp.md
```

`<wp>` is the held comment id. A non-zero exit → `::warning::` quoting its first stderr line; the review continues. Rewrite the whole body at the Phase 0.5 profile write and the Phase 4 report write; Phases 1–3 update rows in place with `workpad.py progress` in their own files. Substitute `{N}` (PR number), `{RUN_URL}` (the held `$RUN_URL` literal: a whole link, or `_(local run)_`), `{workpad.py now}` and `{SEEDED_HEAD}` — `$PR_API_HEAD_SHA` with one space either side; omit that line when the SHA is unresolved, and keep it unchanged in every rewrite (duplicate-review suppression reads it):

```markdown
# PRFlow Review — PR #{N}

<!-- prflow:review-seeded-head {SEEDED_HEAD} -->

**Status:** 🚀 Reviewing
**Diff profile:** _(pending Phase 0.5)_
**Run:** {RUN_URL}
**Reviewed HEAD:** _(set at Phase 4)_
**Last updated:** {workpad.py now}

## Blueprint
- [ ] Classify diff (Phase 0.5)
- [ ] Generate verification checklist (Phase 1)
- [ ] Verify checklist (Phase 2)
- [ ] Review agents (Phase 3)
- [ ] Aggregate & verdict (Phase 4)
- [ ] Run complete — everything this run owed

## Findings (live)
_(Phase-3 findings appear here as each agent returns.)_

## Verdict
_(pending)_
```

Update protocol. Tick each Blueprint row but the last as its phase completes, in order; the tick substrings are `Classify diff`, `Generate verification checklist`, `Verify checklist`, `Review agents` and `Aggregate & verdict`. One sequential call per tick, never in parallel (they lose writes). A `workpad.py progress` call that exits non-zero did not tick: say so and continue.

- Phase 0.5 → set `Diff profile`, tick the first row.
- Phase 4 → rewrite the whole body to `.prflow/tmp/review/<slug>/<run-id>/review-wp.md`, produced as Phase 4.1 produces `verdict-body.md`, from the draft `review-wp-draft.md` beside it, with `review-wp.md` in place of `verdict-body.md` throughout; a route leaving it unwritten runs `rm -f` on it and patches nothing. The body: the run key (line 1); the H1; the seeded-head line; the `Status`, `Run`, `Reviewed HEAD` and `Last updated` lines (drop `Diff profile`, whose content moves to `Run details`); `## Blueprint` with the fifth row ticked; the Phase 4.1 report from `## Verdict: …` through `## Issue Compliance` plus any extension-requested section, in place of `## Verdict`/`_(pending)_`; `## Findings (live)` holding one `<details><summary>Per-agent reports</summary>` block rebuilt from this pass's per-agent block files; then `## Run details`. Set `Status` to `❌ Changes requested at <first 7 characters of $PR_HEAD_SHA>` for REJECT or `✅ <verdict token as written> at <…>` otherwise; set the `Reviewed HEAD` line to the reviewed head SHA (`$PR_HEAD_SHA`) verbatim — experiment records join on it. Never write the verdict marker: `post-review-verdict.sh` stamps it after posting.
- Terminal completion → `post-review-verdict.sh` ticks `Run complete` when it posts the verdict (the fix loop ticks it at Loop Exit); never tick it yourself on a standalone run or re-post a verdict to fix an unticked row.
- No verdict → patch `Status` to `❌ Review failed` and replace `## Verdict` with a one-line `REVIEW INCOMPLETE — <reason>`, leaving the Blueprint ticks; with `$WP` unset, report `❌ Review incomplete — <reason>` in chat.
<!-- prflow:review-ref phase=0.3.5 file=skills/review/phases/phase-0-3-5-progress-comment.md end -->

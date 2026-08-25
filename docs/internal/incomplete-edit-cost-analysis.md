# Does `incomplete-edit` cost an extra iteration — and can the §2.3 record predict it?

Issue #1827 asked whether PRs later categorized `incomplete-edit` are distinguishable
at declare-done from a durable signal — specifically, whether they correlate with a
**narrower recorded §2.3 sweep selection, a missing selection record, or a declared
exemption**, using `efficiency_runs[].iterations` as the rework metric.

**Answer: the durable records are insufficient to decide it.** The rework metric covers
under half the cohort and is biased toward one era of PRs; over the covered subset the
`incomplete-edit` cohort's rework is indistinguishable from the rest of the store; and the
§2.3 sweep-selection records, though broadly present, carry no category-specific signal —
the weak directional associations that do appear are equally present in a non-cohort
control. The counts below establish each of these.

> **Snapshot provenance (past-time exemption).** Every figure here is a point-in-time
> snapshot of `.prflow/learnings/retrospectives.jsonl` and `.prflow/learnings/experiment-records.jsonl`
> as of 2026-08-25, plus a one-off read of the cohort's issue workpads. These are historical
> counts over an append-only store; nothing regenerates this page, so the numbers are recorded
> as a snapshot rather than machine-rendered, per `CLAUDE.md`'s generated-evidence convention.

## Method

- **Cohort.** Retrospective entries whose `categories` array contains `"incomplete-edit"`
  (array membership, not a substring match over prose): **109** entries, **108** carrying an
  `issue` number, merged between **2026-05-27 and 2026-08-07**.
- **Rework metric.** `efficiency_runs[].iterations` from `experiment-records.jsonl`, joined to
  the cohort by PR number; per PR the metric is the maximum non-null `iterations` across that
  PR's `efficiency_runs`. **The metric is never derived from `post_bot_commits`** — which open
  #1440 shows miscounts local-tier agent commits as human rework — nor from any other field.
- **§2.3 sweep-selection record.** The Phase 2.3 sweep-selection `--note` an implement run
  writes on its **issue** workpad (the requirement was introduced 2026-05-29, commit
  `9ba9c752e`, before nearly the entire cohort). Each covered-cohort issue's workpad was
  fetched and its sweep-selection note classified as present/absent and, when present,
  narrow (an `add-only` / "just the always-on sweeps" declaration) or broad.

## Finding 1 — the rework metric covers only 41% of the cohort, and that subset is biased

`efficiency_runs[].iterations` is populated for **45 of the 109** cohort PRs (**41.3%**). The
covered PRs are the early efficiency-experiment PRs (issue numbers ≈ 61–745); the metric was
never backfilled for the later cohort, so the covered subset is **not a representative sample**
of the cohort — it is one era of it. (Store-wide, the metric covers 175 of 489 entries, matching
the issue's stated "~175/489".)

## Finding 2 — over the covered subset, the cohort's rework matches the rest of the store

| Group (covered subset) | n | mean iterations | median |
|---|---|---|---|
| `incomplete-edit` cohort | 45 | **2.31** | 2 |
| non-`incomplete-edit` entries | 130 | **2.33** | 2 |
| all covered entries | 175 | 2.33 | 2 |

Using the durable metric the issue specifies, the `incomplete-edit` cohort is **not** more
expensive than the baseline — the +1-iteration gap the issue's premise rests on does not
reproduce. That premise came from a diff-size-quintile-stratified proxy that is not carried in
durable form and that the issue itself forbids reconstructing from `post_bot_commits`; the
newly-added `additions`/`deletions`/`changed_files` fields (this PR) will let a future run
re-stratify by size durably, but they are absent from every entry in the current store.

## Finding 3 — the §2.3 records carry no category-specific signal

Sweep-selection notes were extracted for the 45 covered-cohort issues and for a random
non-cohort control of 45 covered issues (seed 1827):

| | cohort (45) | control (45) |
|---|---|---|
| has a §2.3 sweep-selection note | 32 | 35 |
| no sweep-selection note | 13 | 10 |
| narrow note (of those with a note) | 11 / 32 (34%) | 17 / 35 (49%) |
| mean iterations — has note | 2.19 | 2.03 |
| mean iterations — narrow note | 2.36 | 2.18 |
| mean iterations — broad note | 2.10 | 1.89 |
| mean iterations — no note | 2.62 | 2.50 |

Two weak directional associations appear: a **missing** note tracks slightly higher rework
(no-note 2.62 vs has-note 2.19 in the cohort), and a **narrow** note tracks slightly higher
rework than a broad one (2.36 vs 2.10). But **both patterns appear equally in the non-cohort
control** (2.50 vs 2.03; 2.18 vs 1.89), so they are not specific to `incomplete-edit` — they
plausibly track "the run did less sweep bookkeeping" or "smaller diff" in general, not the
incomplete-edit failure mode. And the hypothesized direction is if anything reversed for
narrowness: the cohort has **fewer** narrow notes than the control (34% vs 49%), not more.

## Conclusion — insufficient to decide from durable records

The workpad records cannot decide whether `incomplete-edit` is predictable from a narrower,
missing, or exemption-declared §2.3 selection, for three compounding reasons the counts above
show: (1) the rework metric covers only 41% of the cohort and that subset is era-biased; (2)
over the covered subset there is no cohort rework effect at all to explain (2.31 vs 2.33); and
(3) the sweep-selection notes exist but their content is a free-text *selection commitment*
rather than a completeness measure, and the only associations extractable from them are weak,
small-n (cells of 10–20), and equally present in the non-cohort control.

**What would let a future pass decide it.** The three diff-size fields this PR adds to the Stage
A schema make size a durable control going forward, so once enough new entries accumulate the
size-stratified comparison the issue's premise used can be reproduced from the tree. Deciding
the §2.3-selection correlation additionally needs the sweep-selection commitment recorded as a
**structured field** (diff-shape classified, sweeps run, exemptions declared) rather than a
free-text `--note`, so that "narrower" is a mechanical join key instead of a manual reading.
Until both exist, the honest answer is that the current records do not distinguish an
`incomplete-edit` PR at declare-done.

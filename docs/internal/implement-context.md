# `/prflow:implement` runtime main-thread context: findings + eval

This document is the single source of truth for **what the `/prflow:implement`
skill's prompt text costs at runtime**, and for the behavioral instrument that
measures it. It is the implement-side counterpart of
[`docs/internal/create-issue-context.md`](create-issue-context.md) (issue #767), and
follows that document's practices: it separates static shipped size from runtime
context, it adds no size gate of its own, and it stamps every recorded measurement
with its provenance and marks it a past-time snapshot.

The instrument is `scripts/implement-context-eval.py` (stdlib-only Python), a
**maintainer/CI-adjacent instrument**. No skill, workflow, or suite gate invokes it for
a measurement or a threshold, on either the local or the cloud tier; the only automated
execution is its own focused unit test, `lib/test/test_implement_context_eval.py`, which
asserts parser behavior. It adds **no gate, ceiling, or size threshold** anywhere.

## Static shipped size vs. runtime main-thread context

Two quantities are easy to conflate; they are different, and only the second is what a
long implement run actually pays:

- **Static shipped size** — the on-disk line/byte count of the phase files
  (`skills/implement/phases/*.md`) and `skills/implement/SKILL.md` — two populations that
  reach a session by *different loaders*; see **Two loaders, not one** below. It is fixed at
  author time. Issue #1209 opened by observing these files had grown 19% in lines and
  30% in bytes in two weeks — a real signal that something is unmeasured, but *not* the
  cost a run pays, for the two reasons recorded as findings below. The word-budget
  apparatus that once measured static size was retired by issue #765; this document
  does **not** revive it, and the instrument described here adds no gate of its own.

  **Static shipped size IS gated, but by a reader-capability ceiling rather than an
  authoring budget (issue #1595).** `lib/test/lint-reference-size.py` fails the suite when
  a boundary-gated reference or a skill root exceeds 61,750 bytes and holds no live
  exemption in `lib/test/reference-size-exemptions.json`. Do not read that as
  issue #765's budget returning: the two answer different questions and only one is a
  judgment about prose. An **authoring budget** asks how long prose *ought* to be — a
  target someone chose, which is why #765 retired it. A **reader-capability ceiling** is a
  property of what the tool can return: above it the Read tool yields a file's `start`
  marker and no `end` marker on a file that is intact on disk — a read each boundary gate
  recovers by paging the file whole (the *paged-read recovery*), so an over-budget-but-intact
  reference loads instead of misreading as damage wherever the reader offers a continuation;
  one that truncates without offering a continuation still fails the gate. The ceiling is
  therefore derived from the reader's token cap, not from an opinion about length, and it
  says nothing about whether a shorter phase file would be better written.

  This skill's own files are the largest part of the exempted population: the phase files
  over the ceiling when the check landed carry expiring exemptions, and several more sit
  within tens of bytes of it, so ordinary prose added to one should expect to hit the
  ceiling. Read the current state from `lib/test/reference-size-exemptions.json` and
  `lib/test/lint-reference-size.py --print-population` rather than from a figure here —
  the roster shrinks as files are trimmed, and a transcribed size rots on the next trim.
- **Runtime main-thread context** — the live per-turn token weight the *orchestrator*
  (main thread) carries across a run's many turns and phase (re-)entries. It is measured
  per turn as `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
  This is the quantity `scripts/implement-context-eval.py` measures.

### Two loaders, not one — and they fail differently

Every byte figure on this page is measured with one instrument (`wc -c` on disk), which
makes it easy to read the files below as one population. They are not. The two halves of
the implement prompt surface arrive by **different loading mechanisms with different
failure modes**, and a size figure means something different for each:

| | `skills/implement/phases/*.md` | `skills/implement/SKILL.md` |
|---|---|---|
| Loader | the `Read` tool, once per phase entry | the Skill tool, or slash-command expansion for a `/prflow:implement` invocation |
| Known ceiling | **25,000 tokens, per read** — observed, and `phase-1-setup.md` has tripped it | **none found** at or below 83,427 file bytes — observed 2026-08-11, one tier, one runner version |
| Failure mode | **truncates legibly** — `Read` emits `showing lines X-Y of Z … cap 25000` | delivers whole, or **aborts outright** returning no body; a *partial* delivery was probed for and not seen |
| Backstop | the fail-closed boundary contract (#1551) | none — no `SKILL.md` root carries boundary markers |

Two consequences for anyone citing the table below. First, **the `Read` cap is not evidence
about the Skill tool** and vice versa: the two coincidentally share the number 25,000 (the
Skill tool's is a combined *post-compaction re-attachment* budget, not an initial-load cap)
and govern nothing in common. Second, **neither number is a gate here** — this document adds
none, and the largest file in the table is a phase file that already exceeds the observed
`Read` cap, which is a real hazard tracked separately rather than something these figures
enforce.

The delivery evidence, its limits, and the proposed size guard it retargets are in
[`docs/internal/skill-body-load-delivery.md`](skill-body-load-delivery.md); the abort mode is
[`docs/internal/review-skill-load-outage-2026-08.md`](review-skill-load-outage-2026-08.md).

## Two findings the obvious "whole-prompt sum" framing gets wrong

These are the two corrections issue #1209 records as **findings, not background**. Each
rests on specific entry-gate text in `skills/implement/SKILL.md`, quoted here.

### Finding 1 — the phase files are loaded one phase's set per phase entry, not all together

`skills/implement/SKILL.md` states the phase entry-gate rule once, in its preamble, and
routes every phase from that single statement. Since issue #1606 a phase routes to an
**ordered set** of reference files rather than to one file, so the entry gate reads, verbatim:

> **Each phase routes to an ordered SET of reference files, not to one file.** At the start
> of **every** phase, before taking any action in it, `Read` every member of that phase's set
> under `<skill-dir>/phases/`, in the order stated here, and follow them exactly …

followed by a table pairing each phase with its ordered set. Phase 1 and Phase 4 hold one
member each; Phases 2 and 3 hold three each.

A run enters one phase at a time and reads that phase's set when it does. It never holds
every phase's files at once. So the highest phase-file cost at any single phase entry is the
summed size of **whichever phase's set that entry loads** — with the always-loaded
`SKILL.md` resident alongside it. Optimising against the whole-directory total would be
optimising a cost that does not exist; the per-phase set total is the real one, and it is
what bounds a phase entry.

**Phase-file size — past-time snapshot, NOT a live figure.** Generating revision
`2c85a931d`, captured 2026-08-11 (after issue #1582 moved Phase 1.4's branch
resume-precheck/Signals/creation/Verdict-B procedure out of `phase-1-setup.md` into the
dispatched `branch-setup` subagent, following #1576's earlier move of Phase 1.6's
Issue-Claim Audit procedure into `issue-claim-auditor`). These are on-disk `wc -c` byte
counts, quoted in KiB. They rot as the phase files change; re-derive them rather than
trusting these numbers.

| file | bytes | KiB | loader |
|---|---|---|---|
| `skills/implement/phases/phase-1-setup.md` | 68,901 | 67.3 | `Read` |
| `skills/implement/phases/phase-2-implement.md` | 134,965 | 131.8 | `Read` |
| `skills/implement/phases/phase-3-review.md` | 110,140 | 107.6 | `Read` |
| `skills/implement/phases/phase-4-documentation.md` | 75,922 | 74.1 | `Read` |
| **four-file sum** | **389,928** | **380.8** | — |
| `skills/implement/SKILL.md` (always resident) | 61,039 | 59.6 | Skill tool / slash-command expansion |

**The last row is not commensurable with the four above it** — same instrument, different
loader (see *Two loaders, not one*), so the four-file sum deliberately excludes it and the
whole-surface total it would produce answers no question about either mechanism. Note also
that these are *file* bytes: on a Skill-tool load the delivered payload is the file minus its
YAML frontmatter, about 400 bytes smaller at these sizes.

Re-derive with:

```
wc -c skills/implement/SKILL.md skills/implement/phases/*.md
```

At that snapshot the per-entry phase-file cost spans ~67–132 KiB, against a four-file
sum of ~381 KiB — the sum being the figure the framing above gets wrong.

### Finding 2 — the re-read on every re-entry and after every nested-skill return is the multiplier worth measuring

The same single entry-gate statement continues, verbatim:

> These reads are required **on every entry** — including a resumed or re-entrant run that
> picks up at a later phase — never relying on a read from an earlier phase or session.

and `skills/implement/SKILL.md`'s **Mid-phase re-anchor after a Skill-tool return**
rule adds, verbatim (since issue #1876 scoped it to the displaced member):

> after **every** Skill-tool return mid-phase — `simplify`, `review-and-fix`, or any
> other — read it back (`workpad.py resume-point`), re-`Read` **only the one member of
> the reference set under `<skill-dir>/phases/` holding it**, and resume …

So a run that bounces through Phase 3's fix loop pays for Phase 3's whole file set again on
every pass, and a run that calls out to a nested skill and returns pays for only the one
member of the phase's reference set holding its recorded resume point (issue #1876), not
the whole set. **How many times each phase file is re-read across a run — not how big
it is once — is the cost shape worth measuring.** This is precisely the axis the
instrument reports, and the one the create-issue instrument has no equivalent of.

## The behavioral eval

```
python3 scripts/implement-context-eval.py <transcript-dir>
```

A "run" is bounded by `attributionSkill` matching any declared `<ns>:implement` on
`type == "assistant"` records, with `isSidechain` (dispatched-subagent) records
excluded — the phase files are read by the orchestrator on the main thread, so a
subagent's reads and context are deliberately not counted. One session JSONL file with
at least one attributed main-thread turn yields one run; a resume into a separate
session file is reported as its own run (cross-session merging is out of scope).

It commits no transcript contents, embeds no owner-specific identifiers, streams records
rather than buffering a whole session, degrades per malformed record without detonating
(reporting what it skipped), is deterministic (re-running yields byte-identical output),
and never reads a file whose real path escapes the supplied corpus directory.

**Per-run metrics:** turn count; main-thread context measured per turn and reported as
peak and final context;
`compact_boundary` count; a count of attributed turns that carried no `usage` object
(`usage_missing_turns` — such a turn's residency was never recorded, so it is tallied
rather than folded in as a `0`, and a run whose every turn lacks usage reports its peak
as `unestablished`); and — reported **separately from the peak, because they are
different quantities** — a per-phase-file read count for each phase file the phases
directory holds, plus their per-run total. Reads are attributed to a phase by the file's
own stem, so the members of one phase's ordered set report under that phase's label rather
than each becoming an axis of its own. A phase-file read is a `Read` tool_use whose
`input.file_path` basename is one of those phase file names; the basename is matched
(not a full path) because the skill anchors the read at
`<skill-dir>/phases/phase-N-<name>.md`, which resolves to a local `skills/implement/…`
path on the interactive tier and a vendored `.prflow/vendor/prflow/skills/implement/…`
path on the cloud tier. The gated Phase 2.3 sweep references
(`skills/implement/references/sweep-*.md`, issue #1581) are also read on the main thread
when a sweep's predicate fires, so a read of one counts toward the `phase2` axis by
basename shape (`sweep-` prefix, `.md` suffix; issue #1739). That shape match is kept
separate from `PHASE_FILES`, which stays the exact `skills/implement/phases/*.md` mirror a
test pins, so widening the measured population never touches that pin.

It also reports two axes about *how the run spent its turns*, because a turn count alone
mis-attributes the work — one assistant turn can carry several tool calls, so a run that
batches its calls looks cheaper than one that does not while doing the same work:

- **Main-thread tool calls, bucketed by category.** The category list the instrument
  uses is exactly: `file_reads` (`Read`, `NotebookRead`), `file_edits_writes` (`Edit`,
  `MultiEdit`, `Write`, `NotebookEdit`), `shell_commands` (`Bash`, `BashOutput`,
  `KillShell`), `subagent_dispatches` (`Task`, `Agent`), `skill_invocations` (`Skill`),
  and `other` — the catch-all that takes every unmapped tool name so the buckets sum to
  the run's whole tool-call population and a new tool in a later harness release shows up
  as a rising `other` count rather than vanishing. The per-run total is reported beside
  the buckets.
- **The distribution of wall-clock gaps between consecutive main-thread tool calls** —
  the median, the maximum, and the total, never a mean alone, because a mean hides the
  tail that dominates a long run. This is the axis that separates time a run spent
  thinking from time it spent waiting on the harness.

  **Disclosed proxy: the gaps are measured at TURN granularity, not per call.** A
  transcript record carries one `timestamp` however many `tool_use` blocks its turn
  holds, so a per-call gap is not observable from this data at all. What the instrument
  measures is the gap between consecutive main-thread turns that issued at least one
  tool call — a turn batching four calls contributes one point, not four. Consequently
  `total_seconds / total_tool_calls` is not a per-call latency and should not be read as
  one. This is disclosed in the same sense as the cross-session bound above.

  A tool-bearing turn whose record carries no usable timestamp is counted in the skip
  accounting under `unusable_timestamp` and **never** contributes a zero gap. It is also
  counted per run (`unusable_timestamp_turns`), and a run's `tool_call_gaps` always
  carries a `spans_dropped_turns` flag, `true` when that count is non-zero. The flag
  marks *any* dropped turn in the run, not only one a reported interval spans — it
  deliberately over-warns rather than under-warns, because a dropped turn between two
  retained stamps has its gap computed straight across the hole and reported as a single
  interval, and the reader must be able to see which distribution that could have
  happened in. A run with fewer than
  two timestamped tool-bearing turns reports the three gap *statistics*
  (`median_seconds`, `max_seconds`, `total_seconds`) as `unestablished` rather than `0`;
  `count` is a real measurement and reads `0`.

**Aggregate summary:** run count; corpus total of usage-missing turns; median and max
peak context (over the runs with a measured peak — a usage-less run is counted in
`run_count` but excluded from the peak population, never averaged in as a `0`); count of
runs exceeding 200K and 400K; per phase, the median, max, and corpus total read count,
plus the median and max per-run total phase reads; per tool category, the median, max and
corpus total call count, plus the median and max per-run total tool calls; the corpus total of turns dropped from
the gap population for an unusable timestamp; and, for the
gap axis, the median and max of the per-run maximum gap, the median and max of the
per-run total gap, and the corpus total — a run with no measured gap is excluded from
those populations exactly as a usage-less run is excluded from the peak population. Every
run-derived field reads `unestablished` (never `0`) on an empty run population;
`run_count` is the one field whose `0` is a measurement. None of these is a gate,
ceiling, threshold, or budget — they are instrument outputs.

## Explicit non-goal: splitting the phase files by tier

A tier-conditional split of each phase file into a "cloud" version and a "local" version
is a **declared non-goal** of issue #1209, recorded here with its three reasons so it is
not re-proposed.

**This does not refuse a size-driven split into siblings, which is a different mechanism.**
Issue #1606 split two phase files into entry-gate-registered siblings so each returns whole
from a single read; every member is unconditional and every run reads the whole set, so no
run ever executes a phase from a variant selected for it. The non-goal below is about
*conditional* selection between variants — which is what introduces the failure modes it
enumerates — not about how many files a phase's procedure occupies.

1. **The three existing load-on-demand systems fail in deliberately chosen directions.**
   The review engine's phase bundle fails **closed** (an unreadable reference stops the
   run); implement's own phase read is itself a marker-gated, load-on-demand system that
   likewise fails **closed** (issue #1551 — a phase file whose boundary markers are absent,
   partial, or name a different phase halts that phase under a `boundary:` stop label
   rather than executing a bad body); and the create-issue skill deliberately degrades
   **open** (issue #614 — a failed read leaves a breadcrumb and the run continues, because
   nothing may block issue creation). Adding a tier dimension on top of any of them creates
   a new way to halt a working run, or a new way to silently skip a phase.
2. **A wrong-tier read cannot fail closed.** Detecting the current tier from inside
   prompt text is unreliable, and the failure is undetectable: reading the cloud file
   while local *succeeds*, and reading the local file while cloud *succeeds*. Both reads
   succeed, so there is no error for a gate to catch — and a gate can only fail closed on
   a read that fails.
3. **It doubles the surface two other things must keep consistent** — `install.sh` and
   the vendor slice. Neither enumerates phase files today (`install.sh` ships workflows
   and config and pulls the plugin tree by version pin;
   `.github/actions/vendor-plugin/vendor-slice.sh` copies `skills/` wholesale), which is
   precisely why a split is cheap to *introduce* and expensive to *keep honest*: the
   duplicated file would ship with no edit to either, so nothing would flag a tier
   variant that had silently drifted from its sibling, and the shipped-surface audits
   (`lib/test/lint-shipped-pruned-path.py`, the anchor-fallback lint) would each grow a
   tier dimension to cover both copies.

If a future measurement shows a split is worth it, that is a separate issue with
evidence behind it.

## Baselines

### Fixture-derived reconciliation (CI-reconcilable — reproduce it, no figure recorded)

The committed synthetic corpus under `lib/test/fixtures/implement-eval/corpus/` is a
CI-reconcilable check, not a real-run snapshot. `lib/test/test_implement_context_eval.py`
re-derives every expected figure directly from the fixtures rather than hard-coding it,
so changing a fixture updates the assertion. Reproduce it with:

```
python3 scripts/implement-context-eval.py lib/test/fixtures/implement-eval/corpus --format json
```

These are synthetic transcripts chosen to exercise the parser (main-thread filtering,
the sidechain exclusion, phase-file basename matching including a vendored path, a
run over 200K, and a phase-3 re-entry); they are **not** a measurement of any real
`/prflow:implement` run.

### Real corpus snapshot (maintainer measurement obligation — UNFILLED)

No real-corpus snapshot has been captured yet. When a maintainer captures one, record it
here stamped with its provenance — the generating revision, the capture date, and the
corpus size (run count) — and mark it clearly as a **past-time snapshot**, not a live
figure, exactly as `docs/internal/create-issue-context.md`'s "Corpus-derived headline
snapshot" section does. Re-derive any figure with the command above rather than trusting a copied
number; a figure a reader treats as current rots the moment the measured thing changes.

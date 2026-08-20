# `/prflow:create-issue` runtime main-thread context: determination + eval

This document is the single source of truth (SSOT, per issue #762) for **how the
`/prflow:create-issue` orchestrator spends runtime main-thread context**, and for
the behavioral instrument that measures it. `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` §11 carries a one-line pointer here, not a copy.

## Verified-premise grading and the drafting-side duty for ungraded claims

`scripts/check-verified-premises.py` runs at Step 3.6's pre-dispatch canonical write over the
assembled draft (the same helper the implement side re-runs at Phase 1.6). **Which spellings it
grades:** only its marker's three arms — the pure bolded `**Verified**` / `**Verified:**` label
anywhere in the body, a line or list item opening with `Verified:`, and a bolded run opening a list
item whose first word is `Verified`. A verification asserted in **any other shape** — a parenthetical
inside a bold-bullet label, a mid-sentence "verified against origin/main", a lowercase unbolded
phrase — is **graded by nothing**: the marker never sees it, so nothing re-checks it when the issue
is later implemented, and a premise wearing the costume of a verified one without being graded is
worse than no premise at all.

The helper's second, **non-adjudicating** pass surfaces these: it reports every collocation-family
phrase ("verified against", "confirmed against", "checked against", "verified at drafting time") in a
premise-bearing region as an `ungraded_claim=…` line. **The drafting-side duty** (stated in
`skills/create-issue/references/step-3-5-steelman.md` and executed at
`skills/create-issue/references/step-3-6-audit.md`): resolve **every** ungraded detection before the
draft is presented to the user — either rewrite the annotation as a `Verified:` bullet carrying a
re-derivation handle (so the implement side can re-check it), or restate it as ordinary unverified
prose (so it makes no verification claim at all). Resolving it at authoring time is cheap; a filed
issue's ungraded annotation misleads both the implementing run and the reviewer.

## Static shipped size vs. runtime main-thread context

Two quantities are easy to conflate; they are different, and only the second is
what a long create-issue run actually pays:

- **Static shipped size** — the on-disk word/byte count of the skill files
  (`SKILL.md` + the `references/*.md`). It is fixed at author time and equals runtime
  context only for a single, no-repeat, no-compaction pass — which a multi-round
  create-issue run is not. The word-budget apparatus that measured this quantity was
  retired by issue #766; this document does **not** revive it and adds **no** new
  static word-count or prompt-length gate of its own. **The two file populations in that
  count reach a session by different loaders** — the `references/*.md` by the `Read` tool,
  whose observed **25,000-token per-read cap truncates legibly** — the cap that
  drove issue #1702 to decompose the Step 3.6 audit into an entry plus three
  members, each under the ceiling, after `references/step-3-6-audit.md` had grown
  past it; `SKILL.md` by the Skill tool or
  slash-command expansion, for which **no initial-load ceiling was found** at or below
  83,427 file bytes (2026-08-11, one tier). So any figure summing the two — such as the
  302,500 B → 288,788 B delta recorded under issue #1372 below — is a single static-size
  quantity and is **not** a statement about either loading mechanism's headroom. The
  delivery record is [`docs/internal/skill-body-load-delivery.md`](skill-body-load-delivery.md).

  **Static shipped size IS gated, but by a reader-capability ceiling rather than an
  authoring budget (issue #1595).** `lib/test/lint-reference-size.py` fails the suite when a
  boundary-gated reference or a skill root exceeds 61,750 bytes and holds no live exemption —
  and this skill's `references/*.md` are in that population. The Step 3.6 audit was
  once carried as an exemption; issue #1702 decomposed it into an entry plus three
  members (each under the ceiling), **retired that exemption** from
  `lib/test/reference-size-exemptions.json`, and added a per-member 55,000-byte limit
  plus an aggregate source-byte budget over the manifest's population
  (`lib/test/create-issue-step-3-6-members.json`). Issue #1752 then restructured **which**
  members a run reads and when: the entry `references/step-3-6-audit.md` now loads the shared
  member (part 1) unconditionally to run the run bootstrap, and defers the dispatch and
  adjudication members (parts 2 and 3, audit-only) to load as a pair **only when a user
  elects an audit round** at the Step 4 pre-approval pause — so the default run that elects
  no round never reads them. The aggregate stayed within budget across the move
  (70,461 ≤ 72,458). Do not read it as issue #766's
  budget returning: an authoring budget asks how long prose *ought* to be, while this is a
  property of what the reader can return in one call. The distinction is recorded at length
  in [`implement-context.md`](implement-context.md).
- **Runtime main-thread context** — the live per-turn token weight the *orchestrator*
  (main thread) carries across a run's many turns: clarification rounds, revision
  loops, up to three user-chosen audit rounds plus one confirming round — at most
  four discovery-class rounds, each **offered before it opens** at the Step 4
  pre-approval pause (issue #1751), where a satisfied user elects none and the
  default run pays zero audit rounds — plus the issue-#792 exact-byte pass
  funded from its own slot outside that cap, and staged re-writes. Since issue
  #1751 there is no free first round: `_funded_rounds` funds only a round a
  recorded `record-offer --accepted` election paid for, the automatic re-audit
  after a `REVISE` verdict is abolished (`_MAX_AUTOMATIC_REAUDITS` is `0`,
  `next_action` always answers `revise-then-evaluate-offer`), and a zero-round
  `user-decline` still grounds eligibility, binds a decline-bound creation epoch,
  and emits the body. It is measured per turn as
  `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. This is the
  quantity `scripts/create-issue-context-eval.py` measures, and the cost that drives
  the long-run latency and session-cap pressure issue #767 targets.

The distinction mirrors an earlier precedent that separated static size from
execution-weighted traffic; it is restated here directly (as a standalone concept)
rather than by cross-referencing a budget doc #766 removed, and it does not reuse the
"budget" name.

**`attributionSkill` identifies both measured threads, but their costs remain separate.** A run exists when a session file contains a non-sidechain `type == "assistant"` record attributed to any declared `<namespace>:create-issue` identity. Those records supply the orchestrator's main-thread context axis. Attributed `isSidechain` assistant usage is no longer excluded: the evaluator assigns the auditor's full token cost to the most recent `issue-audit-state.py record-dispatch --round N` marker, and separately reports cost that had no matching round. Other dispatched subagents remain outside these axes unless the transcript attributes them to create-issue. A file containing only sidechain records is skipped and makes the sum-based paired comparison unestablished rather than silently deflating it.

## The behavioral eval

`scripts/create-issue-context-eval.py` (stdlib-only Python, mirroring
`scripts/workpad.py`) is a **maintainer/CI-adjacent instrument, never invoked by the
skill's runtime path** (neither the local nor the cloud tier), so it needs **no** new
cloud-workflow tool grant. Legacy mode takes a transcript-directory path as an argument:

```bash
python3 scripts/create-issue-context-eval.py \
  lib/test/fixtures/create-issue-eval/corpus --format json
```

The legacy JSON contract remains exactly the top-level `runs`, `summary`, and `skipped` fields. Raw mode reads transcript and optional state artifacts only. It never reads a draft or rubric, and it never emits transcript, draft, or finding bodies.

### Run-addressable manifest analysis

Manifest mode is exposed by the reusable `scripts.create_issue_eval` module. This committed-fixture example analyzes two bounded occurrences without provider access:

```bash
python3 -c 'import json; from scripts.create_issue_eval import build_manifest_report; print(json.dumps(build_manifest_report("lib/test/fixtures/create-issue-eval/manifests/two-occurrences.json"), indent=2, sort_keys=True))'
```

A schema-1 manifest contains `schema_version`, a `benchmark_id`, a declared `root`, and a non-empty `runs` list. Each run declares `run_id`, `configuration`, `scenario_id`, positive `repetition`, `transcript`, `state_file`, `occurrence`, `checkpoints`, `provenance`, and optionally `rubric`. Occurrence identity is the unique `(session_id, occurrence_id)` pair. `start_event` and `end_event` are zero-based inclusive indexes into nonblank transcript records. `boundary_confidence` is exactly `exact`, `approximate`, or `unknown`; unknown boundaries require `end_event: null` and `duration_ms: null`, while known boundaries require an ordered integer end. The `duration_ms` key is always present, but a number alone does not establish comparable duration: paired statistics require exact boundaries.

`checkpoints` names an initial draft, an ordered `revisions` list, and a final draft. Every transcript, state, checkpoint, and rubric path is realpath-resolved beneath the declared root; lexical and symlink escapes fail with `path_escape`. Provenance requires `repo_sha`, `skill_fingerprint`, `prompt_fingerprint`, `model`, `effort`, `output_style`, and `provider`. A pair compares only when repository, prompt, model, effort, output style, and provider match across its two runs, and each configuration keeps one repository SHA and skill fingerprint across its population. Unknown non-identity metadata is retained for forward compatibility.

Manifest reports add `schema_version`, `benchmark_id`, `manifest_provenance`, and `comparison` around the run, summary, and skip records. Each run receives checkpoint metrics, owner-validated audit outcomes, and a schema-1 grade when a rubric is declared. The deterministic rubric tests required and forbidden concept alternatives, required and forbidden Markdown headings, the expected `Blocked` heading state, and the expected bug-reproduction contract state. Every assertion has exactly `text`, `passed`, and `evidence`. The shipped issue template records the reproduction facts as prose inside `Current Behavior` and ships no reproduction-named heading, so the reproduction axis is not a heading probe: the rubric declares the evidence in `bug_reproduction_any_of`, and the grade searches for it inside `Current Behavior` first, then a reproduction-named section. A rubric that expects the contract while declaring no alternative is refused rather than graded as universally missing. The paired quality gate passes only when the candidate preserves or improves the baseline pass rate, introduces no new forbidden-concept failure, and introduces no new forbidden-section failure; issue length and finding count are measurements, not grade operands.

### Paired case-identity gate and the median-within-baseline verdict (issue #1702)

Because the Step 3.6 decomposition adds bounded file reads at audit entry, a paired fixed-corpus evaluation must prove those reads do not increase runtime main-thread token cost — and it must compare like against like. (Since issue #1752 those dispatch/adjudication reads land only on a run that elects an audit round; a declined run pays only the always-loaded shared member, so the reads this gate weighs are now scoped to elected-round runs.) `scripts/create_issue_eval.py` (the implementation behind `scripts/create-issue-context-eval.py`) gained an **AC10 case-identity gate**: before it compares a baseline population against a revised one, it verifies that both sides carry **equal case identities and equal counts**, and it **fails closed** when a case is missing on one side, duplicated, or split by a resume — so a comparison can only proceed over an identical case/run population on both sides. Once that identity check passes, the paired comparison emits the **median runtime main-thread token cost** for the post-baseline and revised runs and a **revised-median-within-baseline verdict** (the revised median must not exceed the baseline). This is the runtime half of the #1702 fix, kept separate from the per-file and aggregate *static* byte guards described above.

The legacy corpus invocation above — not the run-addressable manifest example — is the measurement command for **every** figure this document reports.
Running it with no corpus present exits non-zero with a diagnostic naming the missing
path — it never emits a silently-empty baseline. It commits no transcript contents,
embeds no owner-specific identifiers, streams records rather than buffering a whole
session, degrades per malformed record without detonating (reporting what it skipped),
is deterministic (re-running yields byte-identical output), and never reads a file
whose real path escapes the supplied corpus directory.

**Per-run metrics:** turn count; per-turn main-thread context; peak and final context; total output tokens; `compact_boundary` count; dispatch rounds; per-round, attributed, and unrounded auditor cost; sidechain record attribution counts; reopen count; the two redundant-addition metrics below; and, in manifest mode, checkpoint/draft metrics, audit outcomes, formal grade, provenance, occurrence identity, and duration metadata.

**Aggregate summary (exactly these fields, complete by construction):** `run_count`, `state_established`, `finding_count`, `median_peak_context`, `max_peak_context`, `runs_over_200k`, `runs_over_400k`, `median_repeated_read_count`, `median_reemission_count`, `median_attributed_auditor_cost`, `median_unrounded_auditor_cost`, `total_unrounded_auditor_cost`, `median_auditor_cost_discovery`, `median_auditor_cost_targeted`, `total_sidechain_records_seen`, `total_sidechain_records_attributed`, `total_record_reopen`, `scope_escape_count`, `scope_escape_unattributable`, `post_filing_escapes`, and `wall_clock`. Run-derived fields are `unestablished` for an empty population except the measured `run_count: 0`. State-derived fields can still establish against a valid state file. `post_filing_escapes` and `wall_clock` are deliberately `unestablished` on this instrument.

### The two redundant-addition metrics

- **repeated-Read** — a `Read` tool_use whose `input.file_path` repeats within the run
  returning content **byte-identical to any content already seen for that path** (a
  re-fetch of already-resident bytes). A repeated Read whose content is **new for the
  path** fetches new bytes, is authoritative, and is **not** counted. **Fail closed:**
  when a Read's `tool_result`
  content is absent or truncated for a record, that occurrence is counted as
  authoritative, never folded into the redundant count.
- **re-emission** — a large (≥ 500-char) assistant text block whose exact bytes were
  already produced earlier in the run (as assistant output or a resident tool_result):
  an output restatement of already-produced content.

## Determination: authoritative vs. redundant additions

The transcript of a create-issue run is **append-only and non-compacting** (the corpus
below shows zero `compact_boundary` events in any run), so nothing "shed" is ever
evicted — the reducible quantity is **redundant future additions**, not a duplicate
resident copy. Each appended-content class is classified below.

### Redundant additions (a later re-fetch/re-emission of already-resident content)

| Class | Canonical durable copy that already holds it | Safely removable here? |
| --- | --- | --- |
| **Re-emission (re-quotation) of an already-produced large block** in the orchestrator's own output — an already-produced Step 1 findings block, an already-produced summary | Step 1 findings: the `.prflow/tmp/issue-step1-<slug>.md` artifact; finding-ledger data: the `issue-audit-state-<slug>.json` field reachable via `query-findings`; the Step 3.5 steelman summary: the `## Steelman record` section of `.prflow/tmp/issue-derivation-<slug>.md` | **Yes** — removed (see below). Its content is already resident from an earlier append; removing the re-quote touches neither compaction recovery nor a mutable file, and needs no new mechanism. |
| **Reference-body re-Read on step re-entry** (a large `references/*.md` re-Read "on every entry into this step") | The reference file on disk | **No — deferred.** It is *compaction insurance*: on a smaller-context consumer model a compaction evicts the body and the re-Read is the recovery. A static instruction cannot tell a compacting run from a non-compacting one, so safe removal needs an in-run compaction-detection signal this issue does not build. Filed as a follow-up. |

### Authoritative (in-thread presence is load-bearing — must NOT be removed)

- The **live draft under construction**.
- The **current turn's user answer** and the active step's **decision inputs** — including the surviving audit findings **quoted verbatim** for the user's Step 3.6 / Step 4 election, and the advisory/invalid records rendered before the approval election.
- A **reference body re-Read as compaction insurance** (see the deferred row above).
- Any **re-Read of a mutated artifact** — the draft file rewritten each revision round, the Step 1 artifact written then re-read by a later step — which fetches **new** bytes and is authoritative, not a redundant re-fetch.

## The reduction (safely-removable class only)

The safely-removable class — **re-emission of an already-produced large block in the
orchestrator's own output** — is eliminated by instruction: the create-issue skill now
directs the orchestrator to **reference already-resident/durable content by pointer
rather than re-quoting it**. The edited sites are:

- `skills/create-issue/SKILL.md` — Step 1's evidence-artifact instruction and Step 3's
  drafting rule: the Step 1 findings stay resident and durably held in
  `.prflow/tmp/issue-step1-<slug>.md`; Step 3 references them by pointer and does not
  re-emit the findings block into its drafting output.
- `skills/create-issue/references/step-3-6-audit.md` — a runtime-context discipline note
  beside the read-back mandate: consult the `query-findings` read-back and the
  `.prflow/tmp/issue-audit-<slug>.md` artifact by pointer; do not re-emit an
  already-produced findings block into the orchestrator's own reasoning output. The
  user-facing surfaces (findings quoted verbatim for the user, rendered adjudication
  records) are explicitly exempt — they are authoritative decision inputs.

No decision-owning mandatory prose is **removed** by this change — the edits *constrain
how* resident content is referenced, adding no new owner of a workflow decision and
removing none — so no `docs/internal/cutovers/` artifact is required (the helper-cutover
convention triggers only when an executable helper becomes the sole tested owner of a
decision, which is not the case here).

### Preservation (code-reading obligation + reproducible check)

The reduction is an instruction-level change to the LLM orchestrator that no
`issue-audit-state.py`-driven suite test can witness (that tool is unchanged by this
issue). Preservation is discharged as follows, and **no audit finding, evidence
provenance, user decision, draft identity, or state-machine authority is removed or
weakened**:

1. **Code-reading obligation (confirmed).** Each removed re-emission's content stays
   resident and reachable from its named durable copy at the point of use:
   - Step 1 findings: `skills/create-issue/SKILL.md` Step 1 states the orchestrator
     writes the reconciled evidence to `.prflow/tmp/issue-step1-<slug>.md` on **both**
     arms before Step 1 returns (the write-on-every-path contract), so Step 3 always has
     the durable copy to reference. Confirmed by reading that Step 1 producer.
   - Finding-ledger data: `scripts/issue-audit-state.py` remains the ledger owner and
     `query-findings` its authoritative read-back (`grep -c query-findings
     scripts/issue-audit-state.py` → 8), unchanged by this issue; the audit reference
     still mandates deciding "against that read-back, never against context recall."
     Confirmed by reading the state owner and the audit reference.
2. **Reproducible check (numbered, tied to the ACs).** A run relying on the durable
   copies reaches the same audit ledger and verdicts:
   - **Check 1 (ledger read-back path unchanged).** `git diff` on
     `scripts/issue-audit-state.py` for this change is empty — the ledger, `query-findings`,
     and every re-gate decision are byte-identical; the reduction touched only prose in
     `SKILL.md` / `step-3-6-audit.md`. So the audit ledger a run reaches is unchanged.
   - **Check 2 (durable copies still written/queried).** The Step 1 artifact write and
     the `query-findings` read-back sites are unchanged by this change (the edits add
     pointer language beside them, never remove them), so the content the removed
     re-quote used to carry is still produced and still reachable.
   - **Check 3 (transcript-level reduction is detectable).** The eval's committed
     synthetic before/after fixture pair
     (`lib/test/fixtures/create-issue-eval/{before,after}`) reports a strictly lower
     peak context and re-emission count on the after-fixture — demonstrating the eval
     *detects* a modeled reduction (a unit property that passes by construction). It is
     **not** claimed as proof that the shipped skill edit reduces real runs.

## Baselines

### Corpus-derived headline snapshot (documented past-time snapshot — NOT live)

The corpus that produced these figures lives only on the maintainer's machine, so
**no CI check can re-derive them**. They are a documented past-time snapshot, stamped
with provenance, and are **never** presented as a live-generated figure. No
partition/exempt-registry guard is built for this figure (the `#656` `rb-figure-partition.py`
apparatus was removed by #766); the snapshot's integrity rests on its stamped provenance.

| Field | Value |
| --- | --- |
| Generating instrument | `scripts/create-issue-context-eval.py` (drafting-time analyzer of record) |
| Generating revision | `06eecc51975233911594656843ec0e50ac8b4822` (issue #767 branch base) |
| Capture date | 2026-07-24 |
| Corpus size | 451 sessions (342 mention create-issue); **157** bounded create-issue runs |
| Median peak main-thread context | **121K** tokens |
| Max peak main-thread context | **924K** tokens |
| Runs exceeding 200K | **30** of 157 |
| Runs exceeding 400K | **9** of 157 |
| `compact_boundary` events (any run) | **0** |

### Fixture-derived companion figure (CI-reconcilable — verified live)

Distinct from the snapshot above, a figure CI *can* re-derive from the committed
synthetic transcripts in `lib/test/fixtures/create-issue-eval/corpus/` is asserted
**live** by the eval's own test
(`lib/test/test_create_issue_context_eval.py::HappyPathTest`): over that fixture corpus
the aggregate is `median_peak_context = 64000`, `max_peak_context = 250000`,
`runs_over_200k = 1`. If the fixtures change, the test re-derives and the assertion
tracks them — it is never hand-transcribed.

### Real before/after reduction (maintainer measurement obligation — NOT a CI gate)

The **actual** guard against a no-op reduction is a maintainer **before/after corpus
measurement**: a create-issue run captured **before** the skill edit and one **after**,
each a documented past-time snapshot, with the after-run's redundant-addition metric
(or peak context on a comparable run) strictly lower. The corpus is not present in CI,
so this is a recorded maintainer measurement obligation, not a CI gate: **a skill edit
whose real before/after shows no decrease is reverted or deferred, never shipped as a
reduction.** The synthetic fixture is not this guard — it only proves the eval detects
a modeled reduction.

**Status for the issue-795 change: no measurement is due on THIS axis, and the row below
is therefore unfilled by decision rather than by omission.** The obligation above binds a
skill edit *shipped as a peak-context reduction*; #795 is shipped as a state-owner
**round-trip** reduction, measured on its own axis in the section below, and it claims no
decrease in peak context or re-emissions. An unfilled row is only honest when its
not-due-ness is stated — a bare template reads as a dropped obligation, which is exactly
how a reviewer read it.

> Maintainer before/after record (to be filled when a change IS shipped as a peak-context
> reduction; unfilled above means no such change is pending, never that one skipped it):
> - before: run `<id>`, captured `<date>`, peak `<N>`, re-emissions `<M>`
> - after:  run `<id>`, captured `<date>`, peak `<N'>`, re-emissions `<M'>`  (must be strictly lower)

### Step 3.6 round kinds (issue #793) — maintainer measurement obligation, UNFILLED

A third axis on the same corpus: what a **claim-scoped** later round costs against the cold
whole-draft round it replaces. Issue #793 made the round kind tool-owned, so a later round
re-checks the enumerated already-raised claims over the tool-derived changed-section set instead
of re-establishing the whole draft and the whole repository from scratch.

**No CI check re-derives the figures below, and none can.** The auditor's cost is spent in a
sidechain the committed fixtures only model; capturing an after-corpus requires running the
instrument over real transcripts produced by the merged change, which no command granted during
implementation can do. This is therefore a recorded **maintainer measurement obligation**, filled
**post-merge by the maintainer**, not in the implementing PR — and the obligation is the guard:
**a measurement showing no decrease means the change is reverted or deferred, never shipped as a
reduction.**

The row is unfilled **by pendency, not by omission**: the measurement is due and has not yet been
taken. That is a different state from the #795 row above, which is unfilled *by decision* because
no measurement is due on its axis — a bare template with neither statement is how a dropped
obligation reads.

> Maintainer before/after record (to be filled post-merge from a real create-issue corpus):
> - before: run `<id>`, captured `<date>`, rounds `<N>`, attributed auditor tokens/round `<T>`, findings `<F>`
> - after:  run `<id>`, captured `<date>`, rounds `<N'>`, attributed auditor tokens/round `<T'>`, findings `<F'>`  (`T'` must be strictly lower on the scoped rounds)
> - escaped-defect proxies: `record-reopen` count `<R>`; later-round must-revise findings whose quoted draft line falls inside an earlier scoped round's recorded scope `<S>` (with its unattributable denominator `<D>`); post-filing class — reported `unestablished`, never a number

**The instrument that produces these figures is built (issue #889).**
`scripts/create-issue-context-eval.py` now attributes the auditor's own `isSidechain`
`usage` records to rounds, derives round boundaries from the transcript's own
`issue-audit-state.py record-dispatch --round N` records (the state file supplies only the
round→kind labelling, the per-round scope, the per-round **selecting reason** (issue #1103) and
the per-finding quoted draft line, best-effort —
every degraded state-file shape yields `unestablished` figures with a stderr breadcrumb, never a
number and never a crash), reports the per-kind auditor-cost medians and a per-run per-round
breakdown carrying each round's recorded kind **and the reason its kind was selected** — a round
whose record carries no reason (a pre-#1103 round) reads `unestablished`, never a guessed value —
and accepts a `--before`/`--after` operand pair with
paired deltas: three corpus-wide sums, each named `total_` for that reason — total attributed
auditor cost, total peak context, total round count — plus `mean_peak_context_per_run`, the
**per-run-normalized** context axis (each side's sum divided by its own `run_count`, so a
population difference between the two corpora cannot enter it) and `finding_count`, which is a
**state-file** axis rather than a corpus sum (it totals one state file's ledger entries, independent
of either corpus's run count) and so carries no `total_` marker (**never latency**). Each of the three sum-based
deltas reads `unestablished` when either corpus is empty **or under-counted on any loss channel** —
an unwalkable directory, an escaped or unreadable session file, a session file carrying only auditor
sidechain records, or a malformed record inside a counted run — because each of those deflates the
sums, and `finding_count` reads `unestablished` when either side's state file could not be read.
Wall-clock is **not** a measured axis on this tier — it is reported `unestablished`,
citing the local-tier row in [`docs/internal/efficiency-trace.md`](efficiency-trace.md), rather than
asserted as something the orchestrator observes; and no cost figure is sourced from a value the
orchestrator volunteers (the harness emits the same `usage` data deterministically). The
main-thread context figures are a **secondary** axis and are never the sole basis of the reduction
claim.

**Only one of the three escaped-defect proxies yields a measured number today, and the instrument
says so rather than reporting one it cannot establish.** The `record-reopen` count is derived from
the transcript and is genuinely measured. The post-filing class is a *declared* class the instrument
reports `unestablished` by construction (an escaped defect found after the issue is filed is outside
any transcript or state file it reads). The **scope-escape** proxy needs two draft-space coordinates,
and as of issue #1105 both have a producer: the per-finding `quoted_draft_line` is ingested from the
ledger's optional `<status>@<n>: <summary>` line and persisted by `scripts/issue-audit-state.py`, and
`record-dispatch` now records a `draft_lines` span on a targeted round's `scope` beside the existing
`{basis_digest, sections, claim_ids}`. The span is the **convex hull** `[min_start, max_end]` over the
changed sections' draft-line extents in the canonical draft — a single `(start, end)` the reader tests
with `any(s <= line <= e)`, deliberately over-approximating a disjoint changed set so it over-counts
escapes rather than under-counting them (the safe direction). The proxy's predicate is about the
**span, not the round**: it reports `unestablished` — **not** the `0` that would read as "no defects
escaped scope" — on a state file carrying **any targeted round whose recorded scope yields no usable
`draft_lines` span**. That still fires for a **pre-#1105** targeted round (recorded before the
producer landed), or a span that is wrong-typed or inverted, so a partial comparison never launders
into a real-looking number; but a targeted round dispatched under the current code fills the comparand
and yields a real count. A state carrying **no targeted round at all** is a third case and reports a
genuine, established `0` — nothing can escape a scope that was never dispatched.

`lib/test/test_create_issue_context_eval.py` asserts the reduction **live** from the committed
synthetic before/after fixtures under `lib/test/fixtures/create-issue-eval/{before,after}-rounds/`
(plus their `states/` labelling) with a **strict inequality**, so a modeled reduction the
instrument can detect is CI-reconcilable — distinct from the real-corpus figures below, which
remain a **maintainer measurement obligation** because capturing an after-corpus requires running
the instrument over real transcripts produced by the merged change, which no command granted during
implementation can do. The obligation is still the guard: a real-corpus measurement showing no
decrease means the change is reverted or deferred, never shipped as a reduction.

### Step 3.6 state-owner round-trips (issue #795)

A separate axis from the peak-context measurement above, on the same corpus: how many times
a run *talks to* the Step 3.6 state owner, and how often it gets the call wrong on the first
try. Both halves are recorded here because the lifecycle reaches consumer repos by the
`prflow_version` vendor fetch, so a per-round reduction reaches them too.

**Before — the stamped baseline.** Measured over the 57 create-issue runs recorded on the
maintainer's machine between 2026-07-19 and 2026-07-24, selected from 6,033 transcripts. A
past-time snapshot: it is not re-derived, and it is never machine-rendered, because
overwriting it would falsify the record it exists to be.

| metric | before |
| --- | --- |
| median `issue-audit-state.py` shell calls per run | 27 |
| share of a run's median 125 Bash calls | 18.6% |
| state-owner shell calls per audit round | 6.2 |
| state-owner invocations per audit round | 13.0 |
| runs hitting ≥1 accidental caller-contract failure | 38 of 57 (67%) |
| runs calling `--help` mid-run to rediscover the contract | 18 of 57 (32%) |
| accidental failures immediately followed by the same subcommand succeeding | 42 of 63 (67%) |
| missing-`--round` share of all accidental failures | 24 of 63 (38%) |

**After — the structural change, and what is measurable today.** The per-round *mandated*
call list is the figure this change moves, and it is **derived live, not transcribed**:
`lib/test/check-audit-lifecycle-contracts.py` extracts it from the shipped prose and
`lib/test/run.sh` prints it on every green run as
`MEASURE  #795 create-issue Step 3.6: unconditional_call_count=… registered_subcommand_count=…`.
Read the current figure there rather than from a number copied into this page.

**A live figure moves for two reasons, and only one of them is this change.** Issue #1466
raised the derived count by three — `query-round-kind` once and `record-staged-write` twice
— by *repairing the sequence prose*, which had omitted three positions the run always
executed. That rise is a documentation correction, not a regression in the reduction below:
no call was added to the run. Read a MEASURE line taken after #1466 against that corrected
baseline; comparing it to a figure recorded before the repair overstates the per-round list
by exactly those three. Three reductions compose into the reduction **#795** made:

- The four back-to-back boundary reads (`query-triggers`, `query-convergence`,
  `query-coverage`, `query-calibration`) collapse to one `query-boundary` call plus the
  `query-coverage` call that is still needed for its per-dimension rows — **four Bash
  round-trips become two**.
- The standalone `python3 -c` `dispatch-pointer:` extraction is gone: the generator emits
  the line on its own stderr — **one process spawn and one Bash round-trip removed per
  round**.
- A forgotten `--round` on any of the five state-determined subcommands no longer costs a
  corrective round-trip at all, and the dispatch-routing answers that name a call now
  render the flag in `needs=` on the arms where the measured trap bit — the 24-of-63
  missing-`--round` class.

**Issue #1803 shrinks the protocol again — a further live-figure move, not a regression.**
Every subcommand that prints a `next_call=` line now also prints a **summary-block** line
between its decided answer line and the `next_call=` line — a compact fixed subset of the
`query-summary` fields (enumerated in the tool's `--help`) — so the clean path reads the
state it needs from the call it just made instead of issuing a standalone `query-summary`
read-back. Dropping that read lowers the per-run mandated `unconditional_call_count` from
13 to 12; that figure is derived live by `lib/test/check-audit-lifecycle-contracts.py` and
printed on the same `MEASURE` line, so read it there rather than from a number copied here.
`record-finding-evidence` also gained a batched `--finding-evidence-records-file` form that
records a whole round's finding evidence from one JSON file (each entry keeping its own
completeness verdict), replacing one call per finding — a saving the mandated-call figure
does not capture, since it counts the once-per-run mandated calls, not the per-finding
calls a multi-finding round makes.

**The real-corpus "after" figure is a post-merge measurement, and is deliberately not
filled in here.** Re-running the same transcript analysis today would re-read the same
corpus — every one of those 57 runs executed the *pre*-change lifecycle, so the analysis
would reproduce the "before" column exactly and report a change of zero. The honest
"after" requires create-issue runs made *with* this change, which cannot exist before it
merges. Fill the row below from a re-run of the same analysis over a post-merge window of
comparable size.

**Reproduction recipe (post-merge).** No committed script produces this table — the before
column came from an ad-hoc analysis, and naming a script here that does not exist would be
worse than naming none. The recipe is therefore stated as its inputs, which is what makes
the re-run comparable:

- **Corpus root:** the maintainer machine's `~/.claude*/projects/**/*.jsonl` transcripts
  (the same root `scripts/inventory-workflow-transcripts.py` walks).
- **Selection predicate:** transcripts containing a `/prflow:create-issue` invocation whose
  run reached Step 3.6, restricted to a contiguous post-merge date window; take a window
  large enough to yield a run count of the same order as the before column's 57.
- **Metric definitions:** identical to the before table's row labels — a "state-owner shell
  call" is one Bash invocation whose command names `issue-audit-state.py`; an "invocation"
  counts each subcommand within it; an "accidental caller-contract failure" is a non-zero
  exit whose stderr carries a `_fail(...)` breadcrumb; "per audit round" divides by the
  count of distinct `--round` values recorded in that run's state file.

> Maintainer post-merge record (fill from a post-merge corpus window):
> - after: window `<start>`→`<end>`, runs `<n>`, median state-owner shell calls per run `<N>`,
>   per-round shell calls `<R>`, runs hitting ≥1 accidental failure `<F>` of `<n>`,
>   missing-`--round` failures `<M>`  (each must be strictly lower than the before column)

### Gating rarely-taken procedural arms (issue #1372) — static delta recorded, runtime after-side UNMEASURED

Six rarely-taken procedural arms moved out of the always-loaded
`skills/create-issue/references/step-*.md` files into six new
`references/fallback-*.md` files, each reached only by its own routing-table
predicate in `skills/create-issue/references/degradation-routing.md` (the routing
table's home since issue #1644 relocated it off the always-read root) — the same gating the pre-existing
fallbacks already used. The routing table is the defining enumeration of that set
and of each member's predicate; see also
[`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md) §11.

**What is measured: static shipped size only.** The clean-run *unconditional* load —
`SKILL.md` plus the references a default path (no fallback predicate firing) reads —
drops from **302,500 B to 288,788 B**. Per the first section of this document that is
**static shipped size, not runtime main-thread context**, and it is recorded here as a
static byte delta and nothing more. It is **not** a word-count or prompt-length gate:
the #766 apparatus stays retired and this change revives no part of it. Re-derive the
figure from the routing table and the on-disk reference files rather than treating the
two byte counts as anything a check enforces.

**What is NOT measured: the runtime after-side.** No runtime main-thread-context
measurement of this change exists. `scripts/create-issue-context-eval.py` can only
measure runs that executed the *post*-change skill, which cannot exist before this
merges — the same constraint the #793 and #795 sections state. The obligation and its
guard are unchanged and apply here: **a change shipped as a context reduction whose
real before/after shows no decrease is reverted or deferred, never shipped as a
reduction.** This change's static delta does not discharge that obligation, and the
row below is unfilled **by pendency, not by omission**.

**Before-side snapshot (documented past-time snapshot — do not re-derive or overwrite).**
Captured on the maintainer's machine; the after-side must be taken against the
**identical** corpus root and the same instrument, or the comparison is not one.

| Field | Value |
| --- | --- |
| Generating instrument | `scripts/create-issue-context-eval.py` |
| Generating revision | `a75578da` |
| Corpus root | `~/.claude-2/projects/<this repository's project slug>` |
| Bounded create-issue runs | **224** |
| Median peak main-thread context | **115,174** tokens |
| Max peak main-thread context | **924,039** tokens |

> Maintainer post-merge record (fill from post-merge runs against the identical corpus
> root above, using the same instrument; unfilled means the measurement is still due):
> - after: captured `<date>`, runs `<n>`, median peak `<N'>`, max peak `<M'>`
>   (median peak must be strictly lower than the before row for this to stand as a
>   runtime reduction)

## Explicitly out of scope / deferred (follow-ups)

- **The mechanical "escaped-information" number is not required and not delivered.** The
  corpus cannot deliver it (zero compactions means no post-compaction loss to detect,
  and re-derivation detection needs semantic diffing). Preservation is expressed as the
  code-reading obligation above. LLM-assisted semantic-loss detection over transcripts
  is recorded as an explicit follow-up.
- **The reference-body re-Read on step re-entry is not removed here** — it is compaction
  insurance whose safe removal would need a reliable in-run compaction-detection signal,
  which is out of scope per the problem statement. Recorded as a follow-up.

Both follow-ups are filed as GitHub issues by the implementing run:

- **#774** — safe removal of the reference-body re-Read needs an in-run compaction-detection signal.
- **#775** — LLM-assisted semantic-loss detection over transcripts (the mechanical escaped-information number is not deliverable from this corpus).

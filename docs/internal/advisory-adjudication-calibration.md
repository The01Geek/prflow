<!--
SPDX-FileCopyrightText: 2026 Daniel Radman
SPDX-License-Identifier: MIT
-->

# Advisory / invalid adjudication calibration — decision record (issue #743)

This is the Stage 1 evidence record for making Step 3.6's advisory and invalid grades
**durable, user-visible, and calibration-checked before convergence**. It establishes the
grading lifecycle from the code, classifies the recoverable corpus, registers the failure
modes with a detection observable per mode, bounds the calibration layer's added latency, and
records the evaluation set the shipped mechanism was run against. It is written first; Stages 2
(the deterministic recording floor) and 3 (the calibration layer) cite it.

Everything the shipped mechanism does lives in `scripts/issue-audit-state.py`,
`skills/create-issue/references/step-3-6-audit.md`, and
`skills/create-issue/references/step-4-present-create.md`; the fallback degradation is in
`skills/create-issue/references/fallback-state-owner-unavailable.md`. No cloud workflow
executes this skill (`grep -rn create-issue .github/workflows/` hits only `ci.yml`'s
test-module list), so the only execution environments are the local/interactive tier and
non-Claude-Code runners, and the suite that verifies it runs through `lib/test/run.sh`.

## 1. The adjudication-path map (verified against source)

Each stage below quotes the operative contract sentence verbatim and cites the producer
surface. The quotes are read from the source at implement time; a later edit that moves one is
reconciled by the Phase 2.3.0 relocation sweep, not by this doc going stale silently.

- **Adjudication** — `skills/create-issue/references/step-3-6-audit.md`: "verify and adjudicate
  every returned finding into exactly one bounded class: **must-revise** = a verified
  correctness, safety, implementability, unresolved-decision, or load-bearing-premise defect;
  **advisory** = a valid improvement not required for a truthful, buildable issue;
  **invalid/unverified** = rejected or insufficiently evidenced." The producer is
  `cmd_record_adjudication` in `scripts/issue-audit-state.py`.
- **Per-finding recording (must-revise ledger)** — `cmd_record_adjudication` /
  `_ingest_ledger`: "A `REVISE` adjudication with a settled unresolved count additionally
  records the round's per-finding ledger … by passing `--ledger-stdin`." Before issue #743 the
  advisory and invalid classes had **no** per-finding recording path at all — they were bare
  counts (`rnd['advisory_count']`, `rnd['invalid_count']`).
- **Per-finding recording (advisory/invalid, new in #743)** — `cmd_record_adjudication` reads
  `--advisory-records-file` / `--invalid-records-file` through `_ingest_adjudication_records`,
  and `_validate_adjudication_records` re-enforces the shape at the read boundary. Records live
  on the round object as `advisory_records` / `invalid_records` and carry `summary`,
  `rationale`, `impact_class`, optional `evidence`, and the `auditor_block` byte-preserved up
  to the evidence cap (a longer block is truncated with the truncation disclosed in the stored bytes).
- **Reconciliation** — `skills/create-issue/references/fallback-audit-round-reconciliation.md`
  (loaded from `step-3-6-audit.md`'s *Reconciliation across rounds* section): the four-arm
  recurrence classification ("A fresh finding … A recurrence of a previously-RESOLVED entry …
  A recurrence of a still-UNRESOLVED prior entry … A recurrence of an INVALIDATED entry"). These arms classify against *ledgered*
  entries; advisory/invalid records are a durable **recording** floor, not a second
  reconciliation surface (this issue deliberately does not widen the reconciliation arms — see
  §3, mode "inconsistent re-grading").
- **Triggers** — `evaluate_triggers` / `cmd_query_triggers`, whose answer shape is
  `t1=hold|not-hold t2=hold|not-hold coverage=hold|not-hold calibration=hold|not-hold reason=…`.
  Since issue #795 the skill no longer calls `query-triggers` standalone at the boundary: the four
  back-to-back boundary reads collapsed to one composite `query-boundary` call, which folds this
  answer in (`query-triggers` survives as a tool surface answering exactly as before — the collapse
  is at the call site, not in the tool's surface). The `calibration=` field (issue #743) is a
  never-blocking sibling of T1/T2 and coverage, produced by the same one evaluation.
- **Convergence** — `evaluate_convergence`: "A converged run is one with ZERO effective
  unresolved must-revise axis-attributable findings … Advisory and invalid/unverified findings
  do not block convergence." The calibration layer does **not** change this: it never redefines
  `evaluate_convergence` and never gates it.
- **Eligibility** — `evaluate_eligibility`: `approve` "answers `eligible` on exactly two grounds
  … (a) a completed `VERDICT: FILE` round whose identity holds … (b) an explicitly recorded
  override that is still current." The calibration layer never adds a ground and never withholds
  one — "**Filing is never blocked on any arm.**"
- **Approval election** — `step-4-present-create.md`: "resolve the re-audit offer BEFORE asking
  for approval … Approval is solicited only on bytes eligible in `approve` mode." Issue #743
  inserts the per-finding disclosure block **before** the approval question, then the run reports
  the rendering with `record-adjudication-render`.
- **Summary rendering** — `cmd_query_summary` / `summary_fields`: the mandatory one-line audit
  summary. Issue #743 adds `calibration_backing`, `adjudication_render`, and `calibration_trigger`
  as space-free tokens **before** the contractually-trailing `attestation=` field, and leaves the
  existing class counts (`advisory`, `invalid`) unchanged.

## 2. Corpus classification (recoverable advisory/invalid grades)

The corpus is the machine-local, gitignored, ephemeral set of
`.prflow/tmp/issue-audit-state-*.json` state files and `.prflow/tmp/issue-audit-*.md` report
artifacts on the implementing machine. Per the AC it is re-inventoried at implement time, and a
thin corpus is recorded as found — corpus size never fails a criterion.

**Inventory result (2026-07-23, the implementing machine):** the corpus is **empty**. `ls
.prflow/tmp/issue-audit-state-*.json` and `ls .prflow/tmp/issue-audit-*.md` each return zero
files. The issue's Problem Statement records a drafting-machine tally (13 state files, 55
adjudicated rounds, 5 advisory grades, 1 invalid grade); **none of those files exists on this
implementing machine** — they are drafting-machine-local and were never committed (the state
tree is gitignored). This divergence is recorded as an issue-accuracy note in the run workpad.

- **Legitimately-non-blocking grades recovered here:** none (empty corpus).
- **Likely-under-graded grades recovered here:** none (empty corpus).
- **Unrecoverable grades, with the recorded reason for loss:** the drafting machine's 5 advisory
  + 1 invalid grades are unrecoverable **on this machine** because their state/report files are
  machine-local and gitignored (never in the committed tree), so a fresh checkout / cloud run /
  different desk holds none of them. The issue's own record of the one surviving full-text
  specimen — "Advisory: extensionless `gh` versus native-Windows PATHEXT, **unverified**", an
  advisory grade recorded on evidence the report itself called unverified — is the motivating
  live specimen this change closes (see §3, mode "advisory-grading a finding whose evidence is
  absent); it is quoted from the issue, not re-derived, because the file holding it is absent
  here.

Because no real corpus grade is recoverable here, the failure-mode register in §3 is derived
from the **code and the issue's recorded specimen**, and the evaluation set in §5 exercises each
mode against the shipped mechanism through **driven fixture runs** (the AC's stated substitute
for a thin/absent corpus).

## 3. Failure-mode register

Each mode names the detection observable the shipped mechanism (or a register-named check) gives
it. "Observable" means a value a reader — the maintainer, the suite, or a later review — can read
off the tool's own surfaces.

| # | Failure mode | Detection observable |
| --- | --- | --- |
| M1 | **Under-grading an execution-blocking finding to advisory** | The record's `impact_class` is an impact-bearing tag (`implementation-correctness`/`scope`/`safety`/`verifiability`) with an empty `evidence` field → `query-calibration` answers `calibration_backing=under-evidenced calibration_trigger=yes` and names the id in `unevidenced=`; the boundary offer discloses it before the approval election. |
| M2 | **Grading a finding invalid with no recorded evidence** | An invalid record is durable and read back by `query-adjudication-records` with `evidence_state=absent`; the record's `rationale` (required, refused when empty) is the recorded justification, and the defect's re-entry channel (the fresh-entry reconciliation arm) stays open. |
| M3 | **Wording evasion** (grading the auditor's hedged phrasing, not the verified impact) | The `auditor_block` is stored **byte-preserved up to the evidence cap** (a longer block is truncated with the truncation disclosed in the stored bytes) beside the grader's `summary`/`rationale`, so any later review has the auditor's own words to compare the grade against — the comparand is the auditor's, not a grader-selected excerpt. Read back by `query-adjudication-records`. |
| M4 | **Decomposition evasion** (splitting one blocking defect across several individually-minor findings) | Each split records its own durable per-finding record with its own `auditor_block`; the read-back exposes the full set on one round for a reviewer to recognize the shared defect, rather than collapsing them to a single advisory integer. |
| M5 | **Inconsistent re-grading of a recurring finding after a draft revision** | Each round's advisory/invalid records are durable and round-scoped; `query-adjudication-records --round N` reads each round's set independently, so a later round's re-grade is a recorded, comparable record rather than a silent overwrite (the must-revise reconciliation arms remain the ledger's channel). |
| M6 | **Conflicting evidence between two probes for one finding collapsing silently to one side** | The existing `record-finding-evidence` / `evidence_conflicts` channel refuses a last-write-wins overwrite of a differing probe (`evidence-overwrite-differs`) and surfaces both keys in `conflict=`; the calibration layer does not weaken it. |
| M7 | **Advisory-grading a finding whose evidence is absent** (the corpus's live specimen) | Exactly M1's observable for an impact-bearing tag; for a `clearly-optional` tag the grade is disclosed to the user (the per-finding rendering) but does not fire the trigger, so an *optional* improvement with no evidence is visible-but-non-blocking while an *impact-bearing* one is named. |
| M8 | **Classification evasion** (mis-tagging an impact-bearing finding into `clearly-optional` so the teeth never fire) | The per-finding rendering shows the user the `impact_class` tag beside the auditor's own `auditor_block`, so a mis-tag is visible to the human before approval — the tag is disclosed, not hidden, and the auditor's words are the comparand that exposes a mismatch between the verified impact and the chosen tag. |

**Mode-to-observable completeness:** every mode above names an observable that is a real tool
surface (`query-calibration`, `query-adjudication-records`, `record-finding-evidence`) or the
per-finding rendering the Step-4 presentation now performs. M8 (classification evasion) is the
mode the tool alone cannot *decide* — a tool cannot know the "true" impact class — so its
observable is **disclosure to the human**, which is the honest ceiling for a self-grading check
and is named as such rather than overclaimed.

## 4. Acceptable per-run added-latency bound

The bound is counted per **clean run** — an ordinary run that reaches the approval election —
in two currencies: added **state-owner calls** and added **subagent dispatches**.

**Bound:** the calibration layer adds **at most 3 state-owner calls and 0 subagent dispatches**
per clean run.

**Justification (one paragraph):** the calibration layer is a tool-side derivation over records
the run already had to produce, so it needs no new subagent (the expensive currency) at all —
its only cost is a handful of cheap CLI reads/writes. A clean run that recorded advisory/invalid
grades adds: (1) `query-adjudication-records` once, to read the records back for the Step-4
per-finding rendering; (2) `record-adjudication-render` once, to report that rendering landed;
and (3) `query-calibration` once, to read the never-blocking disclosure trigger for the boundary
offer. `record-adjudication` itself is the **same** call it always was (it gains file arguments,
not a new invocation), and a run that recorded **no** advisory/invalid grades adds **zero** of
these (the pre-#743 call shape is byte-identical). Three cheap tool calls and no dispatch is a
proportionate price for making every self-grade reviewable and every impact-bearing under-graded
finding disclosed.

**Shipped measured figures against the bound:** on a clean run holding advisory/invalid records,
the shipped layer adds **3 state-owner calls** (`query-adjudication-records`,
`record-adjudication-render`, `query-calibration`) and **0 subagent dispatches** — at the bound,
not over it. On a clean run with no advisory/invalid grade it adds **0 and 0**.

## 5. Evaluation set (driven against the shipped mechanism)

Evidence forms are decided per scenario class so every scenario is dischargeable on a headless
run. The **tool-observable** halves discharge as CLI-driven fixture runs in the suite sandbox —
each is a **named assertion** in `lib/test/test_python_scripts.py`'s `#743` block (reproducible
with `python3 lib/test/test_python_scripts.py`) or the `lib/test/run.sh` `cli_roundtrip`
lifecycle. The **chat-surface** halves — the rendering and election behavior — discharge as a
prose walkthrough here whose self-attestation residual is named in §6.

| Scenario | Expected outcome | Evidence (driven fixture run) |
| --- | --- | --- |
| **S1** — a correctly graded advisory (optional, evidenced) converges cleanly, visible to the user, no added question | `calibration_backing=clear calibration_trigger=no`; the boundary offer does not fire on the calibration ground | `#743: an evidenced impact-bearing advisory + reported render clears the trigger`; chat-half: the per-finding rendering shows the optional finding, no calibration question asked (walkthrough, §6) |
| **S2** — an execution-blocking finding graded advisory is named before approval, not silently converged past | `calibration_backing=under-evidenced calibration_trigger=yes unevidenced=<id>`; the boundary offer discloses the id before the election | tool-half: `#743: calibration is under-evidenced with the unevidenced impact-bearing id named`; chat-half: the offer names the finding (walkthrough, §6) |
| **S3** — an invalid grade records its rationale, and the defect's re-entry channel stays open | the invalid record is read back with its rationale; the fresh-entry reconciliation arm is unchanged | `#743: read-back returns one line per record (2 advisory + 1 invalid)` + the `--record-class invalid` narrowing row; the reconciliation-arm prose in `fallback-audit-round-reconciliation.md` is unchanged |
| **S4** — two conflicting evidence records for one finding surface both values, resolve only by verification | `record-finding-evidence` refuses the overwrite (`evidence-overwrite-differs`) and `query-finding-evidence` names both in `conflict=` | the existing `#704` conflict rows (`evidence_conflicts`), untouched by this change |
| **S5** — re-grading a recurring finding after a revision yields consistent durable records, no double-count, no silent loss | each round's `advisory_records`/`invalid_records` are round-scoped and read back per round | `#743: read-back --record-class narrows to one class` + the round-scoped read in `cmd_query_adjudication_records`; multi-round harness in the smoke record |
| **S6** — one wording-evasion + one decomposition-evasion attempt each land on the register observable | the `auditor_block` is byte-preserved up to the evidence cap (M3) and every split records its own record (M4), both read back | `#743: read-back JSON-encodes the multi-line auditor_block onto one line` (M3); the 3-record read-back row (M4) |
| **S7** — an impact-bearing finding tagged `clearly-optional` lands on the classification-evasion observable | the tag is disclosed to the user beside the auditor's own `auditor_block` (M8); tool-side the tag is stored verbatim and read back | tool-half: the `impact_class`/`impact_bearing` fields in the read-back row; chat-half: the per-finding rendering shows the tag beside the auditor block (walkthrough, §6) |

**Mode-to-scenario map (the evaluation set closes over the register):** M1 → S2; M2 → S3; M3 →
S6; M4 → S6; M5 → S5; M6 → S4; M7 → S2 (impact-bearing) and S1 (optional, the complement); M8 →
S7. Every register mode is covered by at least one scenario.

## 6. Self-attestation residual (named, not hidden)

The tool cannot observe chat. Two behaviors therefore rest on a **reported** observation rather
than a tool-checked fact, and the residual is named here rather than pretended away:

- **The Step-4 pre-approval rendering** is reported to the state owner via
  `record-adjudication-render --landed yes` (the `--write-landed` reported-observation pattern).
  The tool records `adjudication_render=reported`; it cannot verify that the run actually rendered
  the records in chat. **The guard against a false report:** an **un**reported rendering is
  surfaced (never silently passed) — `adjudication_render=unreported` on `query-summary` /
  `query-calibration`, and the calibration trigger holds while the rendering is unreported — so a
  run that skips the report cannot converge past the disclosure surface silently. A run that
  *falsely* reports a rendering it did not perform is the irreducible residual: no CLI over a
  state file can observe the chat surface. This is the same residual shape the issue-#709
  steering gate and the coverage render report carry.
- **The chat-surface halves of S1/S2/S6/S7** (the actual rendering text and the offer wording
  the user sees) are discharged as the prose walkthrough in §5's chat-half column plus this
  named residual, mirroring the Stage-2 residual-naming shape. The **tool-observable** halves of
  every scenario are real suite assertions and carry no residual.

## 7. Pre-change-state fixture provenance

The AC requires a committed pre-change-shape fixture taken through every new read and write path,
landing on one decided, tested arm. On this implementing machine **no real corpus capture exists**
(§2), so — per the AC's stated substitute — the pre-change shape is generated by driving the
**pre-change** state-owner shape through the read paths in the suite sandbox: a round record
carrying **no** `advisory_records` / `invalid_records` / `adjudication_render` keys (the exact
shape every pre-#743 round has). The `#743 read-boundary control` assertion in
`lib/test/test_python_scripts.py` builds such a round and confirms it **validates**, and the
`#743: pre-change round (no *_records keys) reads records=none` and `… derives calibration
unestablished / trigger no` assertions confirm the new read paths land on their decided arm
(`records=none`, `calibration_backing=unestablished`) — never an unhandled traceback and never a
silent reinterpretation of the absent records as under-evidenced. This provenance — a
suite-sandbox scripted pre-change shape, not a sanitized real capture — is recorded here in place
of source-capture field-parity because no source capture is available on this machine.

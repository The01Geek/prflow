---
schema: 1
kind: growth
---
# Issue #743 — advisory adjudication calibration growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/create-issue/references/step-3-6-audit.md` — mandatory row, +3450 bytes (baseline 74760 → 78210).
  (The receiving-review fix pass added +112 bytes to qualify the `auditor_block` byte-preservation prose
  against the 4,096-char evidence cap — a documentation-truthfulness correction, not new obligation prose.)
- `skills/create-issue/references/step-4-present-create.md` — mandatory row, +958 bytes (baseline 39324 → 40282).

(`skills/create-issue/references/fallback-state-owner-unavailable.md` also grew +478 bytes, but it is a `reference`-class conditional file, not a mandatory row, so it needs no growth coverage here.)

## Justification

Issue #743 makes Step 3.6's advisory and invalid adjudication grades **durable, user-visible,
and calibration-checked before convergence** — new operative obligations an implementer must
execute on the create-issue Step 3.6 → Step 4 path, so the prose belongs on the mandatory path,
not a conditionally-loaded reference.

The `step-3-6-audit.md` growth is operative decision logic at the adjudication and boundary-offer
execution points: (a) the per-finding-records obligation — a non-zero `--advisory`/`--invalid`
count **requires** a matching `--advisory-records-file`/`--invalid-records-file` (JSON, one object
per finding with a summary, rationale, impact-class tag, optional evidence, and the auditor's
byte-preserved finding block), with the count-mismatch and field refusals named; (b) the
calibration paragraph — the impact-bearing predicate over `{implementation-correctness, scope,
safety, verifiability}` with `clearly-optional` as the complement, the `query-calibration`
disclosure trigger, and its membership in the single at-most-once boundary offer beside
`coverage=`, all never-blocking; (c) the `query-triggers` `calibration=` field, the lifecycle
diagram (`record-adjudication-render` / `query-calibration`), and the read-back query enumeration.
An implementer who does not read these at the adjudication point cannot record a reviewable
advisory grade or disclose an under-evidenced impact-bearing one — the exact seam the
fresh-context auditor was bought for. The `step-4-present-create.md` growth is the pre-approval
per-finding disclosure block the user must see before the approval election (summary, rationale,
impact-class tag, and the auditor's own words beside the grader's restatement), plus its
reported-observation report via `record-adjudication-render`. It sits at the Step 4 presentation
execution point and gates nothing — but an implementer who skips it renders no disclosure, so it
is mandatory-path operative prose, not rare-path explanation.

Growth was minimized under the create-issue word budget's remedy ladder (redundant parentheticals
trimmed first) before the default-path word ceiling was renegotiated 33,917 → 34,800 words as a
historical departure recorded in `create-issue-budget.md`. The subsystem was later retired, as
recorded in `CHANGELOG.md`. No
prose was removed or relocated (this is a pure additive growth), so no `cutover`/`trim`/`relocate`
coverage is required.

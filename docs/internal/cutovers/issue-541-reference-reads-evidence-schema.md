---
schema: 1
kind: growth
---
# Issue #541 — reference reads evidence schema (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/review-and-fix/SKILL.md` (+34 bytes) — the root `### Schema` block gains the
  `sweep_defs_read` and `sweep_evidence` unconditional fields and the `reference_reads`
  conditional field; the `fix-delta-gate.md` failure-map row's stale "the formal
  `reference_reads.fix_delta` field is the #541 follow-up" parenthetical is rewritten to
  state what now ships. The net is small because the review-round-2 fix that added the
  mandated `reason` key to the `reference_reads` example was paid for by trimming an
  inline `park_calibration` comment whose content `loop-control.md` already owns
  authoritatively — keeping the initial load inside its ceiling without renegotiating it.
- `skills/review-and-fix/references/error-handling.md` (+66 bytes) — the synthesized-record
  enumeration now points at `ITER_SYNTH_EXPECTED_FIELDS` instead of restating a field list
  that the evidence-field addition had made stale.
- `skills/review-and-fix/references/loop-exit.md` (−39 bytes) and
  `skills/implement/phases/phase-3-review.md` (+85 bytes) — the same stale five-field
  enumeration, replaced by the same pointer. Both were already stale before this change;
  they are reconciled here because the changeset claims the schema is reconciled across
  every surface that defines it, and a surviving mirror would make that claim false.
- `skills/review-and-fix/references/fixing.md` (+2118 bytes) — item 7's "Conditional
  gate/sweep fields" paragraph gains the authoritative `reference_reads` specification
  (conditional contract, registry keying, shape, the `status`/`outcome`/`reason` semantics
  with both `not_verified` arms named, and the APPROVE-family prohibition).
- `skills/review-and-fix/references/fix-delta-gate.md` (+955 bytes) — the Step 3.5 gate
  gains its durable-record producer obligation: persist the gate outcome into
  `reference_reads.fix_delta`, covering the clean / refixed / promoted / both-failure-arm
  paths and preserving the two failure arms' distinct breadcrumbs in `reason`. *(Past-time snapshot: this records the two arms as of issue #541. Issue #816 added a third `not_verified` producer — an added assertion whose target could not be read — so the live rule, stated in `skills/review-and-fix/references/fixing.md` item 7, now covers three arms.)*

## Deferred (recorded, not silently dropped)

- `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` §16's synthesis-floor narrative still enumerates the
  synthesized record as `iter` / `fix_commit_sha` / `fix_files` / `loop_role` /
  `synthesized: true`. That enumeration is now **incomplete** — the floor additionally stamps
  `sweep_defs_read`, `sweep_evidence`, and `reference_reads` with
  `{"status": "unrecoverable", "reason": …}` — though not *wrong*: all five listed members are
  still present, and the three new ones are explicit unrecoverable-provenance placeholders
  rather than recovered data.
- It is deferred for a mechanical reason, not an editorial one. The enumeration sits inside a
  ~700-word single-line paragraph, so any edit to it drags the whole paragraph into the diff,
  where the #434 stale-prose lint's R3b count-locked rule resolves a **pre-existing** two-item
  "both" claim in that same paragraph against an adjacent block it reads as carrying three
  assertions, turning the blocking-gate self-scan RED. Isolated mechanically: with that one
  file reverted the self-scan exits 0, and the file alone reproduces the failure. Fixing it
  would mean rewriting an unrelated narrative paragraph this change did not author, to satisfy
  a lint heuristic.
- The changeset's "reconciled across every surface that defines it" claim is unaffected: the
  *defining* surfaces are `fixing.md` item 7, the root `### Schema` block,
  `ITER_EXPECTED_FIELDS` / `ITER_SYNTH_EXPECTED_FIELDS`, and the writer's jq object — all
  reconciled here, as are `loop-exit.md`, `error-handling.md`, `phase-3-review.md`, and the
  `synthesize_iter_workpads` header in `lib/efficiency-trace.sh`. The overview's entry is a
  narrative *restatement*, not a defining surface. The authoritative synthesized-record shape
  is documented in full in [`docs/internal/efficiency-trace.md`](../efficiency-trace.md).

## Justification

These bytes are the *specification* of a record field, and a record field's specification
has to sit where the writer and the gate are, not in a conditional reference — a producer
that must be read only when someone goes looking for it is a producer that silently does
not run.

Three properties make the growth load-bearing rather than editorial:

1. **The field had a behavioral outcome but no schema.** Issue #530 shipped the fix-delta
   gate's fail-closed outcome (not-verified prohibits a clean approve) *behaviorally*,
   deliberately deferring the formal field to keep the split PR reviewable. That left a
   real defect surface: the outcome existed with no durable record, so nothing downstream
   could read it and the SKILL.md failure-map row carried a parenthetical promising a
   follow-up. The prose added here is what closes that gap; removing it would return the
   run to an outcome nothing records.

2. **`fixing.md` item 7 calls itself the authoritative record shape.** A conditional field
   specified anywhere else would contradict that claim. The `sweep_defs_read` /
   `sweep_evidence` half is not new prose at all in spirit — those fields were already
   mandated by item 7 and pinned by the #478 assertions; this change reconciles them into
   the schema block and `ITER_EXPECTED_FIELDS` so item 7, the schema block,
   `ITER_EXPECTED_FIELDS`, and the writer's jq object finally agree. The
   growth is the cost of making an existing, already-written contract *checkable*.

3. **The producer obligation must sit at the execution point it gates.** Per the
   operand-trace sweep's stated-policy rule, a policy described only in a thematic section
   leaves the agent reaching the enforcement point with nothing to execute. The
   `fix-delta-gate.md` bytes are the obligation placed at the gate itself, which is
   precisely where an agent-executed policy has to live to fire at all.

No ownership transferred and no prose was superseded, so this is `growth`, not `cutover`:
no executable helper took over a decision the prose previously owned. The new machine-side
enforcement (`ITER_EXPECTED_FIELDS` / `ITER_SYNTH_EXPECTED_FIELDS` membership, the
`--self-check` consumer, and the `lib/test/run.sh` LR_SCHEMA guard and its `#541` pin block)
*complements* the prose rather than replacing
it — the prose states the contract the agent must execute; the tests keep the four mirror
sites from drifting apart. Nothing was removed, so there are no retired pins to account for.

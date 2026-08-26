---
schema: 1
kind: growth
---

# Issue #609 — per-agent effort observability: mandatory prompt growth

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

## Files

- `skills/review-and-fix/SKILL.md` (25,673 → 25,989 bytes): the `### Schema` block gains the
  unconditional `dispatched_effort` top-level key (with a one-entry example) plus its mention in
  the **Field semantics** enumeration — required so the #170 single-source pin
  (`ITER_EXPECTED_FIELDS` ↔ schema equality) holds for the new required iter-workpad field.
- `skills/review-and-fix/references/loop-control.md` (36,686 → 37,844 bytes): one compact
  *Schema field semantics* paragraph defining `dispatched_effort` — entry shape, the
  capture-at-each-dispatch-phase recipe (`resolve-review-overrides.py --effort-json`), the
  `effective`-stays-null contract, and the absent-field degradation.

(`skills/review-and-fix/references/fixing.md` also grew by 240 bytes for the item-7 write-list
mention, but it is a `reference`-class row — untolled, listed here only for completeness.)

## Justification

These bytes are the producer half of issue #609's acceptance criteria: the per-run efficiency
record's `agent_effort[]` block can only cover the Phase-1/1.5/2 checklist agents if the loop
persists a per-dispatch-phase effort roster, and the field's schema membership plus its
capture/write semantics are precisely the prose that makes the producer emit it. The schema key
must live in the always-loaded root (the #170 pin equates the root schema with
`ITER_EXPECTED_FIELDS`), and the capture semantics belong on the loop-control mandatory path
because every iteration's dispatch phases read it. The review-and-fix initial-load ceiling was
renegotiated 5,510 → 5,540 words in the same change (see `docs/review-and-fix-budget.md`).

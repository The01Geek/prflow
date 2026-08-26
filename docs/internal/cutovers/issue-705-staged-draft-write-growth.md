---
schema: 1
kind: growth
---
# Issue #705 — staged draft write growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/create-issue/references/step-3-6-audit.md`
- `skills/create-issue/references/step-4-present-create.md`

## Justification

- Issue #705 makes every canonical-draft write durable: it stages the intended bytes to a
  nonce-keyed on-disk artifact, replaces the canonical file in one atomic `os.replace`, and
  re-digests the result to prove the replace landed. The new mandatory bytes are the
  orchestrator-executed half of that mechanism — the *Staged canonical-draft write* shared
  procedure (stage → optional `record-revision --stdin-digest` from the staged bytes → apply
  with `--expect-digest` → recovery on disagreement → cross-turn landed re-check → the
  multi-finding-wave and resolution-gate rules) stated once in `step-3-6-audit.md`.
- None of it is relocatable to a rare-path reference: every step fires at an execution point
  the orchestrator reaches mid-procedure on the **normal** path — the pre-dispatch write, the
  presentation write, and the iterate-on-feedback overwrite all run on ordinary runs — so the
  "Prose cutover" rule's relocation licence does not apply. The bundled helper
  `scripts/stage-draft-write.py` owns the atomic replace and the digest comparison, and
  `issue-audit-state.py record-revision` now *enforces* the file-arm `--stdin-digest` requirement,
  but the *sequencing* of those calls across the three write sites and the recovery routing are
  orchestrator judgment the tools cannot make, so the prose is the owner and stays mandatory.
- The procedure is stated once as a named shared procedure and referenced by name from the
  three write sites rather than duplicated, which is the smallest mandatory footprint that still
  places each obligation at the execution point it gates — the same shared-procedure discipline
  the *Ledger maintenance after a revision* section already uses.
- The Step 4 references (`step-4-present-create.md`) grow only by two by-name pointer sentences
  at the presentation and iterate write sites; the substantive procedure lives once in
  `step-3-6-audit.md`. The root-plus-references total moves 25,814 → 27,198 and the default-path
  measured 29,973 → 31,202, both recorded in `create-issue-budget.md`; no ceiling is raised.

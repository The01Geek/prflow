---
schema: 1
kind: growth
---
# Issue #668 — reception artifacts growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/receiving-code-review/SKILL.md`

## Justification

- Issue #668 gives the Reception Preflight a machine-readable producer: one
  `reception-record.py record` session-artifact write that derives the
  content-based candidate identity, mints the claim-context nonce, and records
  both to the gitignored session directory. The block therefore grows from nine
  facts to eleven — candidate identity (fact 10) and claim-context token (fact
  11) — and each addition is the smallest form that discharges its acceptance
  criterion.
- The added mandatory bytes are the operative half of that mechanism and are not
  relocatable to a progressively-loaded reference: they fire at execution points
  the preflight reaches inline. Specifically — the two enumerated facts and their
  block-template rows (the eleven-fact completeness-by-construction claim is a
  decision the render owns), the single new prescribed command in the read-only
  fence, the per-fact source rule that binds facts 10/11 to the one gitignored
  write and states the establishing predicate and its `missing` arm, and the
  degraded-arm bullet that makes an unproducible artifact an explicit `missing`
  render rather than a silent skip. None of these is a standing caution the
  orchestrator could carry unprompted; each is a conditional keyed to an
  observable predicate — the invocation exited 0 and its stdout parsed as a JSON
  object carrying both values, or it did not.
- Round-2 review growth (+797 bytes total) is the cost of making that predicate
  actually observable. The shipped wording keyed the `missing` arm on the helper
  "producing no output", which no failure path satisfies — every failure path
  writes a `{"ok": false, "reason": …}` record to stderr — so the arm was
  unreachable and a fact could render `established` against a value the run never
  derived. Replacing it with the exit-status-plus-stdout-parse predicate, and
  directing the reader to surface a non-null `rebound_from` in fact 10's value,
  cannot be expressed in fewer bytes than the vaguer text they replace; both were
  written as in-place sentence rewrites rather than added paragraphs. A further
  in-place clause names the reason source when no `{"ok": false}` record was
  written at all — three of the enumerated causes (an absent helper, a denied
  invocation, an unavailable interpreter) produce no such record, so without it
  the reason text was unspecified for exactly those arms.
- The read-only contract is amended in place rather than evaded: the mutate
  sentence is rescoped from `worktree files` to `tracked content`, and the one
  gitignored session-artifact write is named as permitted text. That is a
  clause-level edit, not a new paragraph, and it keeps the section's stated
  contract true instead of resting the write on omission.
- The editing gate is untouched: neither new fact's status can bar it, so the
  growth adds observability facts without widening the gate's bar condition.

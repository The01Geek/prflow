---
schema: 1
kind: growth
---
# Issue #1053 — focused first precondition growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Per-file byte deltas for every mandatory prompt surface this change grows, counted with
`python3` at this change's HEAD against `main`. This is a **past-time snapshot** — the figures
are the growth measured at authoring time, not a live-rendered or re-derivable-current value.

- `.prflow/prompt-extensions/implement.md` — +2,578 bytes (49,677 → 52,255).
- `.prflow/prompt-extensions/review-and-fix.md` — +2,685 bytes (34,756 → 37,441).
- `.prflow/prompt-extensions/receiving-code-review.md` — +1,764 bytes (18,941 → 20,705).
- `skills/implement/phases/phase-2-implement.md` — +359 bytes (131,129 → 131,488).
- `skills/implement/phases/phase-3-review.md` — +419 bytes (93,733 → 94,152).
- `skills/implement/phases/phase-4-documentation.md` — +495 bytes (105,847 → 106,342).
- `skills/review-and-fix/references/fixing.md` — +1,184 bytes (70,520 → 71,704).

The three prompt extensions carry the bulk: `implement.md` gains the focused-first precondition
paragraph (single-sourced there) and the single-turn push/verify reword; `review-and-fix.md` and
`receiving-code-review.md` each carry a coupled real copy of both rules with same-commit
reconciliation authoring comments. The four shipped skill files carry the smaller repo-agnostic
additions — the narrowest-test-first sentence (phase-2), the in-env-pass establishment sentence
(phase-3), the final-verification reconciliation sentence (phase-4), and the new suite-result
establishment bullet (`fixing.md`). `CLAUDE.md` and `CONTRIBUTING.md` carry only compact pointers
and are records rather than mandatory prompt surfaces, so they are outside this snapshot's
population.

## Justification

Both new rules strengthen existing sentences rather than introduce new concepts, and the
precondition reuses the existing `## Devflow Reflection` bullet mechanism with no new lifecycle
vocabulary and no new counter. The precondition and single-turn mandate are load-bearing at the
execution point they gate — a focused-first rule stated as advice was the permissive wording this
change replaces — so the growth buys an obligation that could not be moved to a rare-path
reference without losing the moment it must fire. The two prompt extensions are separately-loaded
surfaces (the #1076 shape) and `receiving-code-review.md` is additionally consumer-facing, so the
coupled real copies are required rather than collapsible to a pointer; `CLAUDE.md` and
`CONTRIBUTING.md` point instead, keeping the mirror count at two real copies plus two pointers.

---
schema: 1
kind: growth
---
# Issue #754 — scaffold reuse growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Mandatory prompt rows that grew in this change:

- `skills/implement/phases/phase-2-implement.md` — +1,115 bytes (92,267 → 93,382)
- `skills/receiving-code-review/SKILL.md` — +1,036 bytes (54,855 → 55,891)

(`skills/review-and-fix/references/fixing.md` also grew, +1,110 bytes 66,618 → 67,728, but it is
a `reference`-class row in `lib/test/prompt-mass-manifest.json` — its movement is visible in the
baseline diff and untolled by the Review gate, so it is not listed as a mandatory growth here. It
is instead tolled by the word-denominated `#530` review-and-fix budget, reconciled in
`docs/review-and-fix-budget.md`.)

## Justification

Issue #754 names the residual reuse gap the focused-module iteration default (#707) and §2.2.4's
production-code *Reuse & Altitude gate* leave open: a throwaway verification rig built mid-iteration
to exercise code in isolation (a scratch repo, a fixture config, an interpreter/CLI wrapper) is
neither production code nor a pre-registered focused module, so no existing rule tells a run to keep
and reuse a still-valid one — each RED/GREEN cycle rebuilds it from scratch.

The repair is one short advisory line on each of three verification/fix-iteration surfaces. Two of
them are mandatory-path (`phase-2-implement.md` §2.3, where rigs are built during RED/GREEN
iteration; `receiving-code-review/SKILL.md`'s Verification Gate, the vendored reception discipline),
so the bytes have to land on the mandatory surface — the guidance is inert unless it enters the
model's context at the point rigs are actually built. Each line's clauses are acceptance criteria of
the issue, not elaboration:

1. **Keep-and-reuse** the rig instead of rebuilding a still-valid one.
2. **Record its location** on the channel that surface actually has (a workpad `--note` on the
   implement surface; a run-persisted channel *when the consumer flow offers one* on the vendored
   body, else reuse bounded to a single un-compacted span).
3. **Revalidate before reuse** — reuse only after confirming the rig still exercises the current
   code shape; rebuild when that shape changed, so a rig keyed to a superseded shape is never
   silently reused into a false pass.
4. **Ignored-path placement** — keep the rig under an already-ignored scratch path so the terminal
   `git add -A` never stages it (a nested `git init` rig would otherwise land as a gitlink).
5. **Illustrative-open rig set** — the rig types are a floor, not a closed list.

The lines are deliberately per-surface adapted (not byte-identical), mirroring how the focused-module
sections are adapted rather than mirrored; the vendored `receiving-code-review` copy is strictly
repo-agnostic (no repo-internal path or step number). No new gate, command, config key, or tool
grant is added — this is advisory prose at the same altitude as the rules it sits beside.

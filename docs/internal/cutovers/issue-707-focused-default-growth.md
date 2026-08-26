---
schema: 1
kind: growth
---
# Issue #707 — focused default growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Mandatory prompt rows that grew in this change:

- `.prflow/prompt-extensions/implement.md` — +2,520 bytes (35,956 → 38,476)
- `.prflow/prompt-extensions/review-and-fix.md` — +1,246 bytes (21,074 → 22,320)
- `.prflow/prompt-extensions/receiving-code-review.md` — +733 bytes (14,395 → 15,128)
- `CLAUDE.md` — +1,156 bytes (71,436 → 72,592)

Coupled ceiling renegotiation this growth forced (the `#530 budget` block in `lib/test/run.sh`
and its mirror cells in `docs/review-and-fix-budget.md`):

- initial load (root + always-loaded extensions) 8,686 → **9,007** (measured 9,003)
- maximum active step (initial load + `shadow-review.md`) 20,025 → **20,346** (measured 20,342)

The plugin-root ceiling (3,567) is untouched — this change edits no `skills/review-and-fix/`
file.

## Justification

Issue #707 inverts a verification default that is stated on the mandatory path, so the bytes
have to land there: an agent decides whether to run the full suite *while iterating*, before
any reference could be loaded conditionally, and the surface that states the rule is the same
surface the decision is read from.

The bytes buy four things the retired one-sentence rule did not state, and each is an
acceptance criterion of the issue rather than elaboration:

1. **The inverted default** — a focused pass covering the changed surface is sufficient for an
   intermediate commit or push, and a mid-iteration full-suite run happens only when no focused
   module or path covers the changed surface. One sentence cannot carry both the permission and
   its limit without the second clause, and the RED/GREEN micro-test showed the permission
   alone leaves the "is an intermediate commit a gated event?" question unresolved.
2. **The parallelized final gate** — push to trigger CI *and* start the local full run at the
   same time, with the push not gated on the local run, and the local run still authoritative.
   That is three separate obligations (start both, do not block, whose signal wins); dropping
   any one of them either re-serializes the gate or silently promotes CI over the local run.
3. **The preserved guarantees** — the `CLAUDE.md` lint gates and the issue-#456 skip accounting
   are restated verbatim so the relaxation is scoped to *when* the suite runs, never to *what*
   counts as clean.
4. **The unweakened cloud rule** — `review-and-fix.md` and `implement.md` each restate that the
   cloud `/prflow:implement` in-env gate (issue #405) is unchanged and never waits on or cites
   CI. Without it, the parallel-push allowance reads as tier-agnostic and would license exactly
   the CI-citing behavior #405 forbids.

`implement.md` additionally carries the reflection obligation the issue mandates (a full-suite
run records a `## Devflow Reflection` bullet saying why it was necessary), which is what makes a
mid-iteration full run an auditable decision rather than a silent reversion to the retired
default.

The policy is stated on **both** always-loaded extensions of the review-and-fix bundle
(`review-and-fix.md` and `receiving-code-review.md` — the latter always-loaded since issue
#620), so it lands on the initial load twice. The `receiving-code-review.md` copy is an
*adaptation*, not a mirror, per that file's own stated convention, and it is already the
shortest statement of the rule that keeps the reception/shepherd tier self-contained.

The `CLAUDE.md` growth is the coupled-mirror half: its tiered-runner convention had to state the
same rule (with a pointer naming the extensions as the operative statement), or the two
artifacts would disagree — the desync class the repo's coupled-invariant rule exists to stop.

Each surface was written to its operative minimum first; only then were the two ceilings
renegotiated to the measurement plus the repo's usual ~4 words of headroom (the #556/#619/#618
precedent), and the decision recorded here.

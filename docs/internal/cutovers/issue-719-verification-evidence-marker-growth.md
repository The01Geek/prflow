---
schema: 1
kind: growth
---
# Issue #719 — verification evidence marker growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Mandatory prompt rows that grew in this change:

- `.prflow/prompt-extensions/implement.md` — +3,420 bytes (38,476 → 41,896)
- `.prflow/prompt-extensions/review-and-fix.md` — +1,752 bytes (22,320 → 24,072)
- `.prflow/prompt-extensions/receiving-code-review.md` — +1,603 bytes (15,128 → 16,731)

Coupled ceiling renegotiation this growth forced (the `#530 budget` block in `lib/test/run.sh`
and its mirror cells in `docs/review-and-fix-budget.md`):

- initial load (root + always-loaded extensions) 9,007 → **9,468** (measured 9,464)
- maximum active step (initial load + `shadow-review.md`) 20,346 → **20,807** (measured 20,803)

The plugin-root ceiling (3,567) is untouched — this change edits no `skills/review-and-fix/`
file; `implement.md` grew too but is not on the `#530` always-loaded surface (it is measured only
by the `prompt-mass-census.py` byte mirror).

## Justification

Issue #719 repairs the unobservable claim gate that #707's parallelized final gate introduced
(finding 1). #707 removed the serialization that made the full-suite run self-evident ("the push
is NOT gated on the local run finishing") and replaced it with a purely observational rule, but
never stated *how* the concurrent run is made observable — so a refused launch's natural terminal
was "pushed / nothing-to-read / claim-made", with every mutation pin green because the sentence
was intact. The repair states the mechanism on the mandatory path, so the bytes have to land
there: the decision to capture and record is read from the same always-loaded surface that states
the parallel-push allowance.

The bytes buy artifact vocabulary the retired observational rule did not state, and each clause is
an acceptance criterion of the issue rather than elaboration:

1. **The capture-to-a-named-file mechanism** — on the local/interactive tier the run captures its
   parallel full-suite launch to a named file under `.prflow/tmp/`, so a launch that never
   started is observable as an **absent capture file**.
2. **The `Verification evidence:` marker** — recorded in the workpad through `scripts/workpad.py`
   with the run's pass/fail/skip tallies and the captured file's path, so a completion claim
   without the marker is an inspectable defect rather than an indistinguishable one.
3. **The `note` reflection kind** — the only kind `lib/cheap-gate.jq` does not treat as friction,
   so the marker does not itself flip an otherwise-clean run.
4. **The fallback channel** — workpad by default, PR description when there is no workpad, and an
   explicit "unrecordable" terminal when there is neither, so a reception pass with no linked issue
   is covered rather than stalled.
5. **The honest scope** — artifact vocabulary plus a captured artifact, *not* runtime enforcement;
   `lib/cheap-gate.jq` is deliberately not wired to the marker (its population is predominantly
   cloud runs this local/interactive scoping excludes), and runtime enforcement is deferred to the
   named follow-up issue #730.

Deleting the undefined `or path` disjunct (finding 2) trims a few words back on the same surfaces,
but the marker prose dominates, so the net always-loaded surface grew and the two `#530` ceilings
were renegotiated to the fresh measurement plus the repo's usual ~4-word margin. The prose was
written to its operative minimum before the ceilings were moved.

---
schema: 1
kind: growth
---
# Issue #730 — verification evidence advisory growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Mandatory prompt rows that grew in this change (the identical tier-scoped advisory block added to
both shipped review-engine extensions):

- `.prflow/prompt-extensions/review.md` — +3,428 bytes (3,280 → 6,708)
- `.prflow/prompt-extensions/review-and-fix.md` — +3,428 bytes (24,072 → 27,500)

Coupled ceiling renegotiations this growth forced:

- **Review-and-fix bundle (`#530 budget` in `lib/test/run.sh` + `docs/review-and-fix-budget.md`):**
  the block lands on `review-and-fix.md`, an always-loaded surface, taking it 3,573 → 4,046 words.
  - initial load (root + always-loaded extensions) 9,468 → **9,941** (measured 9,937)
  - maximum active step (initial load + `shadow-review.md`) 20,807 → **21,280** (measured 21,276)
- **Review engine bundle (`#618 AC3` in `lib/test/run.sh` + `docs/review-bundle-budget.md`):** the
  block lands on `review.md`, on the shipped-default per-pass path, taking `_rb_shipped_w`
  30,016 → 30,549.
  - shipped-default per-pass path ceiling 30,076 → **30,609** (measured 30,549, + the fixed
    60-word margin)

The plugin-root ceilings (review-and-fix 3,567; review-engine AC2 8,500) are untouched — this
change edits no `skills/` file. `lib/cheap-gate.jq` gained only a head comment recording why it
stays unwired to the marker, and is not a mandatory prompt row.

## Justification

Issue #730 is the deferred follow-up to #719. Where #719 added the `Verification evidence:` marker
and its capture mechanism to the *recording* surfaces, #730 adds the **consuming** half: a
tier-scoped, **non-blocking** review-engine advisory that surfaces a local/interactive
completion/PR-ready claim made with no captured verification run. Because the review engine is
shared, the advisory has to be stated on both extension surfaces that the two review paths load —
`review.md` (standalone `/prflow:review`) and `review-and-fix.md` (the fix loop) — so the bytes
land on both.

Each clause of the added block is an acceptance criterion of the issue rather than elaboration, and
none can be dropped or shortened past its operative minimum without failing a `run.sh` pin:

1. **Input population** — the two durable per-PR surfaces (the linked issue's workpad and the PR
   description) the marker is recorded on, reusing the fetch channel the `Writing-skills evidence:`
   gate already opens.
2. **Tier discriminator** — classify each PR from the workpad `## Progress` section: a
   `gha:` checkpoint marks a cloud run (silent); its absence marks local/interactive (the only
   population the advisory acts on), because cloud runs verify in-env under issue #405 and carry no
   capture obligation.
3. **By-classification behavior** — silent on cloud; on a local/interactive PR carrying a
   completion claim, silent when the marker is present on either surface and one non-blocking
   advisory finding when it is absent from both.
4. **Covered population** — a local Phase-3 inline review, a local `/prflow:review-and-fix` given a
   PR, and a direct-reception marker in the PR body; a current-branch run with no PR/issue is out
   of scope (no durable surface to read).
5. **Accepted residual** — a cloud run on a legacy workpad lacking a canonical `## Progress`
   section writes no checkpoint and is misclassified local/interactive, yielding a false advisory;
   because the finding is non-blocking this is low-cost and accepted rather than guarded.

The advisory is explicitly **advisory**: it never raises the verdict to FAIL/REJECT on its own. The
prose was written to its operative minimum before the three ceilings were renegotiated to the fresh
measurements plus the repo's usual margins (~4 words for the `#530` load/max-step ceilings; the
fixed 60-word margin for the `#618` shipped-default ceiling).

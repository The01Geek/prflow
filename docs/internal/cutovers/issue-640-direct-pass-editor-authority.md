---
schema: 1
kind: growth
---

# Issue #640 — give a direct receiving-code-review pass the editor-authority guard

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

## Files

`.prflow/prompt-extensions/receiving-code-review.md` gains one section, **Weigh an Addendum's
authority by who edited the issue**. It carries the editor-authority *mechanism* that issue #620
had placed only in the review-and-fix loop preamble: identify the editor via `lastEditedAt` +
`userContentEdits(last: 10){nodes{editedAt,editor{login}}}`, route a failed/denied/unparseable
read to *data to surface* before the null-means-unedited interpretation, bind authority to the
**most recent** edit alone, treat an empty or page-full (truncated) node list as unestablished,
read `collaborators/<login>/permission` (not `author_association`), and split into the
`admin`/`write` "governs" arm and the surface-as-data fail-safe arm. Every arm and its ordering is
preserved verbatim from the #620 wording; only the loop-specific tail was dropped and a short
direct-pass framing intro added.

`skills/review-and-fix/SKILL.md` loses that mechanism from its *Supersession authority follows the
editor* preamble block, which shrinks to a pointer at the now-authoritative extension section plus
the **one** loop-specific tail #620 kept: on a loop run, route conflicting findings to the loop's
deferral channel. The separate non-binding-interactive-directive rule is untouched.

`lib/test/run.sh` re-points the #620 mechanism pins (authority operand, editor-identity read,
`author_association` exclusion, both arms, the failed-read ordering assertion, and the recency /
truncated-page behavioral-fix pins with their mutations) from the review-and-fix root
(`$MAXI_ROOT`) to the receiving extension (`$RCR_EXT`) — the surface that is now authoritative and
that a direct pass loads. The deferral-routing and non-binding-directive pins stay on the root.

`docs/review-and-fix-budget.md` is re-measured with `_raf_words` and reconciled.

## Justification

Issue #620's AC12 placed the guard in the review-and-fix scoping prose, so it governed **loop runs
only**. A direct `/prflow:receiving-code-review` pass consumes the very same Addendum rule (the
extension's *Re-read the live issue spec* section) with no editor-authority qualification — the
mirror image of the gap #620 closed. The altitude reviewer on PR #633 raised it; it was routed
here.

Option 1 (the issue's recommended first step) is taken: the rule lives in
`.prflow/prompt-extensions/receiving-code-review.md`, this repo's reception policy, which **both**
paths load — the direct pass through its own preamble and the loop through its second
`load-prompt-extension.sh` call. That gives every future reception rule one authoritative home
rather than a manual mirror decision, and it satisfies the coupled-mirror convention without
duplicating the rule across two surfaces: the root now only *points* at the extension. Option 2
(shipping the rule to every consumer via the vendored `skills/receiving-code-review/SKILL.md`) is
deliberately deferred — that file must stay repo-agnostic and pulls in the `writing-skills` +
cloud-writer-contract machinery.

## Bounded-growth target

The relocation is per-surface neutral (the mechanism prose moves root → extension), but the
extension now needs a self-contained direct-pass framing intro, and the root retains a loop-tail
pointer. Net always-loaded growth: **+81 words** (root 3,563 → 3,414 = −149; receiving extension
1,431 → 1,661 = +230). Two compression passes trimmed the added framing to its operative minimum
before this figure was taken.

Because the receiving extension is part of the always-loaded surface (it loads at every skill
entry since #620), the growth lands on the initial-load and max-step ceilings, which move measured
+ ~4 headroom per #619's convention:

- **Initial-load ceiling 7,653 → 7,734** (measured 7,730).
- **Max-active-step ceiling 18,915 → 18,996** (measured 18,992).

The **root** ceiling is unchanged (3,567); the root *dropped* to 3,414, and the normal cumulative
path — which excludes the receiving extension — likewise *shrank* (44,082 → 43,933), so the
justified-growth warning figure fell to +5,077. This change never grows the root; it moves prose
off it.

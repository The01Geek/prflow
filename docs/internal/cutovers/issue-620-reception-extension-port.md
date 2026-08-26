---
schema: 1
kind: growth
---

# Issue #620 — reception-extension port and unconditional load

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

## Files

`.prflow/prompt-extensions/receiving-code-review.md` gains two sections. **Focused test modules
in direct reception passes** ports the module-iteration rule that already governs the loop path,
adapted for direct passes (the direct leading-token runner form leads) and deferring to the
review-and-fix extension's own section on loop runs. **Push form in reception passes** ports the
explicit-destination-ref rule and names the two non-conforming forms with their rationales,
including the operator record that `git push -u origin <branch>` has pushed straight to main from
a `.claude/worktrees/` checkout under `push.default=upstream`.

`skills/review-and-fix/SKILL.md` gains a second `load-prompt-extension.sh` call and the scoping
prose that governs how loop runs consume the loaded text — reference resolution, non-binding
interactive directives, and the supersession-authority guard.

This extension is now **mandatory prompt surface**: it loads on every `/prflow:review-and-fix`
entry that goes through the skill preamble — the standalone loop, the implement Phase 3 inline
run, and the Step 2.6 shadow entry. The documented Skill-denied fallback, where Phase 3 reads the
engine straight from the tree, bypasses the preamble and is unchanged by this issue. The vendored
`skills/receiving-code-review/SKILL.md` stays repo-agnostic and is unchanged; the sources of
record (`.prflow/prompt-extensions/review-and-fix.md`'s focused-modules section and
`skills/review-and-fix/references/fixing.md` Step 3 item 6) are unchanged.

## Justification

Both rules were already proven, codified, and tested on the fix-loop path, and both were being
re-derived per reception pass: repeated full-suite runs to read back a handful of figures, and
stranded or misdirected pushes from shepherd worktrees. Porting them costs bytes once; the
alternative — per-rule byte-mirroring into the already-loaded review-and-fix extension — delivers
today's two rules at zero new load but leaves every future reception rule dependent on a manual
mirror decision, which is the silent-absence failure this change exists to close.

The load is unconditional rather than gated because a conditional load reintroduces exactly that
failure: a rule that reaches the loop only when someone remembers to route it there.

## Bounded-growth target

The issue targeted 450 `_raf_words` for the two new sections plus the scoping prose.
**Shipped: 683.** The target was renegotiated more than once, and every move is recorded here rather than
folded away, because a bound that silently tracks its subject has stopped bounding anything.

1. **450 → 600.** The prose reached 590 after two compression passes from 649, and every remaining
   clause is mandated by AC1, AC2, AC4 or AC12's at-minimum lists — 450 is unreachable without
   dropping mandated content. Reconciled under the implement skill's Phase 2.2.6 rule; recorded in
   the issue workpad as an AC-rewrite note and an `issue-accuracy` reflection.
2. **600 → 630, for a correctness fix.** The external `writing-skills` RED/GREEN pass this repo's
   prompt-surface routing mandates found that the supersession guard named an operand it could not
   obtain: it keyed authority on the *editor's* `author_association`, but GitHub exposes no
   association for an edit — `gh issue view --json` has no such field at all, and the REST payload's
   `author_association` describes the **issue author**. Verified directly against the live API.
3. **630 → 660, and the first root-ceiling move (3,500 → 3,515).** The review's own checklist
   verifier and `silent-failure-hunter` then showed the *repaired* guard still had no mechanism for
   the predicate gating it — nothing told the run how to determine whether a body edit was made by a
   third party — so the routing was undetermined and the guard could fail open on exactly the input
   it exists to catch. The fix names a verified mechanism (`lastEditedAt` plus
   `userContentEdits{editor{login}}` via `gh api graphql`, then `collaborators/<login>/permission`)
   and an explicit permission mapping, since `author_association` values do not denote write access
   — `MEMBER` in particular does not. A second review iteration then found the repaired mechanism
   still had an open arm: a non-null `lastEditedAt` with an empty or page-full (truncated) editor
   list would have read as authority established from a partial history, so that state now routes to
   the unestablished arm. A third iteration closed the last open arm: the identity read itself can
   fail, and an empty/denied/rate-limited `gh api graphql` response is indistinguishable from a
   genuine null `lastEditedAt`, so a failed, denied, or unparseable read now routes to the
   data-to-surface arm **before** the null-means-unedited interpretation is reached — without that
   ordering the guard failed open exactly where it claimed to fail closed. Every API shape named was
   checked live before being written. The accumulated prose no longer fit under the 3,500 root
   ceiling, which moved to 3,515.
4. **The failed-read arm was widened to cover the PERMISSION read too, word-neutrally (no ceiling
   move).** The prior wording's failure arm reached only the identity read, so a failed permission
   read — a 403 is the *expected* response on the read-only reviewer tier, whose token lacks the push
   access that endpoint requires; 404 and rate-limit/transport failures land there too — matched
   neither the `admin`/`write` arm nor the "unidentified editor" catch-all, leaving the routing
   undetermined on exactly the input the guard exists to catch. The arm now names both reads and is
   stated before the `admin`/`write` branch, and the catch-all admits an absent or unreadable
   permission explicitly. Paid for by compression elsewhere in the same paragraph: the root
   word count was unchanged (+19 bytes, an audited mandatory-prose growth reflected in
   `lib/test/prompt-mass-baseline.json`), so no ceiling moved.

5. **660 → 683, and a second root-ceiling move (the ceiling now stands at 3,567, which also absorbs
   root growth arriving from `main`).** A later review round found the
   repaired guard still fail-open in one dimension: it weighed the editor logins as a *set*, so an
   Addendum written by an unprivileged editor read as an authoritative operator amendment whenever
   any `admin`/`write` login merely co-occurred in the truncated ten-node edit history — again the
   exact input the guard exists to catch. Authority is now bound to the most recent edit alone (the
   node with the latest `editedAt`), which required adding `editedAt` to the query and restating the
   weighing clause.

Every move after the first is correctness winning over a word target, and each is recorded with its
cause rather than folded away. Compression absorbed the first two entirely; the third and the fifth each required
touching the root ceiling. The root now sits at 3,563 of 3,567 — the same
~4-word margin the other two ceilings carry, so a future addition to this preamble meets all three
at once rather than any one of them first.

## Budget renegotiation

The receiving extension is now always-loaded, so the **initial-load** and **max-active-step**
measures became three-term sums.

| Quantity | Before | After | Ceiling before → after |
| --- | ---: | ---: | --- |
| Plugin root | 3,213 | 3,563 | 3,500 → 3,567 |
| Initial load | 5,686 (root + extension) | 7,649 (root + always-loaded extensions) | 5,690 → 7,653 |
| Max active step | 16,948 | 18,911 | 17,000 → 18,915 |

All three ceilings now carry ~4 words of headroom over their measurements — following issues
#556 and #619, because a ceiling set exactly at the measurement makes the next one-sentence edit a
budget breach. Recorded in `docs/review-and-fix-budget.md`'s maintainer note.

**Absorbed from `main` after the figures above were first set: issue #642's review-and-fix
extension reword (2,646 → 2,655 words), which had already moved the initial-load and max-step
ceilings to 5,887 / 17,149 on `main`.** Merging it raised both of this issue's measures by the same
9 words — initial load 7,640 → 7,649, max active step 18,902 → 18,911 — so the two ceilings were
re-measured to 7,653 / 18,915, preserving the ~4-word margin. The **root** ceiling is untouched
(3,567): #642 did not change `skills/review-and-fix/SKILL.md`. Recorded here rather than folded
away, per this section's own rule — a merge-driven move is still a move.

The **cumulative-path** and **growth-delta** arithmetic excludes the receiving extension —
rationale in the budget doc's Counting method, mirrored in `lib/test/run.sh`'s `#530 budget`
block. Those figures still move (44,082 and +5,226) because the root itself grew by the loader
call and its scoping prose.

Growth is bounded by design: the two new sections state rules and cite their sources of record
rather than restating them, and neither duplicates an artifact or module inventory into prose.

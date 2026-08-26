---
schema: 1
kind: growth
---

# Issue #655 — the artifact registry as the merge-conflict oracle

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

## Files

`.prflow/prompt-extensions/review-and-fix.md` and
`.prflow/prompt-extensions/receiving-code-review.md` — the two always-loaded members of this
bundle — each gain the byte-identical `## Merge conflicts in generated artifacts` section
(`.prflow/prompt-extensions/implement.md` gains the same section, but it is not on this bundle's
surface). `skills/review-and-fix/references/fixing.md` gains the one-sentence repo-agnostic
pointer in its `CONFLICT` arm — as do the other two in-run conflict arms,
`skills/implement/phases/phase-1-setup.md` (the Checkpoint `CONFLICT` arm) and
`skills/receiving-code-review/SKILL.md` (the "Update the Branch First" merge-conflict clause);
`fixing.md` is singled out above only because it is the arm on *this* bundle's surface, not
because it is the complete arm set.

## Justification

### What moved

Two mandatory-surface ceilings for the review-and-fix bundle were renegotiated:

| ceiling | before | after | measured after |
| --- | --- | --- | --- |
| root + always-loaded extensions (initial load) | 7,734 | 8,686 | 8,682 |
| root + always-loaded extensions + max active step | 18,996 | 19,948 | 19,944 |

The plugin-root ceiling (3,567) is **unchanged** — the root gained no words. Every renegotiated
ceiling carries the repo's usual ~4 words over the measurement, for the reason #556/#619/#618
recorded: a ceiling set exactly at the measurement makes the next one-sentence edit a breach.

### Why the growth was taken

Issue #655 requires a generalized regenerate-on-conflict rule, stated **byte-identically** in its
own top-level section of all three PRFlow prompt extensions (`implement.md`,
`review-and-fix.md`, `receiving-code-review.md`). Since issue #620 **two** of those three —
`review-and-fix.md` and `receiving-code-review.md` — sit on this bundle's always-loaded surface,
so the rule lands on the initial load twice. The measured cost is +952 words on the initial load and,
transitively, on the max-active-step figure (measured against the tree merged with `main`, whose
issue #640 had already moved the ceilings to 7,734 / 18,996).

The section could not be shrunk past its operative minimum without dropping something AC7 pins:
it must cite `regenerate-artifacts.py --list` as the oracle, match the conflicted path against the
emitted `conflict-path` **and** `conflict-sibling` paths, read the matched row's `conflict-class`
**and** `conflict-recipe`, and state **both** fail-closed defaults — the hand-merge default for a
path not among those emitted, and the needs-human-reconciliation default for a `--list` that
cannot run at all. Each of those is a distinct decision the rule routes; removing any one leaves a
route the run has no answer for, which is the inert-guard defect the issue's own operand-trace
analysis identifies.

Splitting the rule across the three extensions was not available either: AC7 requires the three
copies to be byte-identical, and a suite pin extracts each section body and asserts that identity,
so per-file abridgement would turn the coupling RED by construction.

### What the growth buys

A merge conflict in a checked-in generated artifact previously had no rule at all beyond a single
artifact's worth of guidance (the prompt-mass baseline sentence, now retired to a pointer). A
hand-merged generated artifact produces bytes matching no source of truth; the artifact's own gate
then reports it as drift with a remedy aimed at the wrong file, so the run burns a loop on a
misdirected diagnosis while silently reverting whatever grant or row a concurrent PR added. The
rule replaces that with a runtime lookup against the registry, hardcoding no artifact path and no
command — so the rule and the registry structurally cannot drift.

### Scope note — what "hardcodes no path and no command" means

The rule names one command: `lib/test/regenerate-artifacts.py --list` (issue #1055 moved it off the
`python3` interpreter head, which the cloud implement matcher denies). That is the oracle's
entry point, not an artifact-specific command, and naming it is unavoidable — a rule that named no
entry point could not be executed. What the rule hardcodes nowhere is any **artifact** path or any
**per-artifact** regeneration command: both are read from `--list` at runtime, which is the property
that keeps the rule and the registry from drifting. These three extensions are PRFlow-repo-scoped
consumer config and are never vendored to a third party, so the reference leaks to no consumer; the
three in-run arm pointers, which *do* ship, name no helper at all.

### Coupled sites reconciled in this change

- `lib/test/run.sh` — `RAF_LOAD_CEIL` / `RAF_MAXSTEP_CEIL` constants and their renegotiation note.
- `docs/review-and-fix-budget.md` — the ceilings table, the header prose ceilings, the maintainer
  note, and every Measured cell the `#530`/`#620` blocks bind (the two extension rows, the
  initial-load, bundle, cumulative-path and max-active-step rows, the `fixing.md` reference row,
  the net-reduction figure, and the cumulative growth delta).
- This artifact.

---
schema: 1
kind: relocate
---
# Issue #614 — create issue thin root relocate (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Source rows

- `skills/create-issue/SKILL.md` (mandatory, `create-issue-flow`) — the monolithic body,
  166,802 bytes / 24,473 words before this change. Every step procedure, the two shared
  procedures, and every conditional fallback arm lived here and loaded on every run,
  including the arms whose predicate could not fire.

## Destinations

The root is retained as an always-loaded thin orchestration surface; nothing is deleted.
Each destination is reached through the root's routing table at its stated load trigger,
behind a first-line/last-line boundary-marker entry gate that degrades best-effort.

Mandatory-at-entry step references (`create-issue-flow`, `mandatory` — a file loaded
unconditionally on the normal path per the manifest's own `classification_rule`). Note
`revision-delta.md` is grouped with the conditional references below, not here: it loads at a
revision event, a predicate that never fires on a run whose steelman and audit find nothing:

- `skills/create-issue/SKILL.md` — retained root: the portable-anchor preamble, the
  extension load, Prerequisites, the core principle, the completion checklist, Step 1,
  Step 3's drafting rules and no-options gate, the routing table, the entry-gate rule,
  and the four non-degradable invariants. 2,732 words.
- `skills/create-issue/references/step-2-clarify.md` — Step 2 in full: the Definition of
  Ready, the independent-derivation pass, the evidence-bundle sub-pass and its gates, the
  visual-specification guidance, and the clarification/disengagement machinery. 4,673 words.
- `skills/create-issue/references/step-3-5-steelman.md` — the Step 3.5 code-grounded
  verification loop. 2,133 words.
- `skills/create-issue/references/step-3-6-audit.md` — the Step 3.6 audit lifecycle, the
  state-owner contract, the call sequence, and the shared Ledger-maintenance procedure.
  7,701 words.
- `skills/create-issue/references/step-4-present-create.md` — Step 4's presentation gate,
  the confirmation gate, the iterate-on-feedback loop, creation, the `DevFlow` provenance
  stamp, and the gated implement offer. 5,362 words.

Conditional references (new group `create-issue-conditional`, `reference` — genuinely
conditional files, each loaded only when its predicate fires):

- `skills/create-issue/references/revision-delta.md` — the shared Revision-delta
  verification procedure. 922 words. Trigger: any revise-and-re-gate site.

- `skills/create-issue/references/fallback-no-task-tool.md` — the inline-checklist and
  state-file fallback. 540 words. Trigger: no usable task-tracking tool.
- `skills/create-issue/references/fallback-read-only-sandbox.md` — the consolidated
  read-only-sandbox arms (the derivation artifact, the derivation gate's inline stand-in,
  the audit report artifact, and the presentation gate). 334 words. Trigger: a
  `.prflow/tmp/` write or delete is refused.
- `skills/create-issue/references/fallback-audit-dispatch-arms.md` — the embed arm and its
  sentinel carriage check, the `DRAFT-UNREADABLE` and same-arm retry escalations, and the
  degraded inline arm. 669 words. Trigger: a non-file audit arm, a retry escalation, or no
  exposed subagent tool.
- `skills/create-issue/references/fallback-state-owner-unavailable.md` — the two routing
  classes, the two exits that route elsewhere, and the bounded one-round conduct. 748
  words. Trigger: the state owner produces no contract output, or a mutation cannot
  establish or persist state.

`skills/create-issue/references/issue-template.md` and
`skills/create-issue/references/audit-prompt-template.md` are **byte-unchanged**: the split
neither moved nor rewrote them.

## Conservation

Relocated prose moves **verbatim** apart from extraction-seam splices. Post-split total
(root + all 9 references) is 25,814 words; subtracting the 985 words of itemized structural
overhead the split is required to add (boundary markers 108, routing table 325, entry-gate
prose 155, non-degradable-invariants block 175, seam pointers 222) leaves 24,829 against a
pre-split baseline of 24,473 — **+1.45%**, inside the ±2% tolerance. The measurements and
decision context were captured in the now-retired [`create-issue-budget.md`](create-issue-budget.md)
record; the subsystem's retirement is recorded in `CHANGELOG.md`.

The always-loaded surface drops from 24,473 words to 2,732, and a default-path run — task
tool usable, writable filesystem, file-arm dispatch, state owner available — no longer loads
the 2,291 words of fallback prose it previously carried on every run.

---
schema: 1
kind: growth
---
# Issue #708 — audit coverage growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Mandatory prompt rows that grew in this change:

- `skills/create-issue/references/audit-prompt-template.md` — +2,082 bytes (11,351 → 13,433)
- `skills/create-issue/references/step-3-6-audit.md` — +1,137 bytes (67,283 → 68,420)

Both figures are measured against `origin/main` **after** merging it into this branch, so they
are this change's own contribution and not the merge's.

The default-path ceiling **was** renegotiated, as a merge collision and at the operator's
direction (`create-issue-budget.md`, the 2026-07-22 PR #728 decision row):

- root 2,732 (ceiling 2,754, **unchanged**)
- default path 32,475 → **32,619**; ceiling 32,491 → **34,249** (measured + the full AC6 5% maximum)
- root + all 9 references 27,989 → **28,133** (`CI614_TOTAL_RECORDED` re-recorded)

This change's own coverage prose fits inside the pre-merge ceiling on its own branch — it landed
at exactly 31,262 there. The overrun appears only when `main`'s #704/#706 union (which had itself
re-recorded the ceiling to 32,491 with 16 words of headroom) is merged in, so no single change is
responsible for it. The operator authorized the full 5% maximum rather than another 16-word margin
that the next PR would collide with immediately; the ratchet resumes at once and this is not a
precedent for single-change growth.

`audit-prompt-template.md` is renderer-owned and is **not** on the default-path operand, which is
why the larger of the two growths costs the budget nothing.

## Justification

Issue #708 makes Step 3.6 audit coverage a positive, falsifiable, per-dimension assertion. Two
surfaces have to carry bytes, and neither can be deferred behind a load trigger:

1. **`audit-prompt-template.md`** — the auditor's return contract. A per-dimension coverage
   return that the auditor is never asked for cannot be recorded, so the requirement has to be
   in the rendered prompt itself. These bytes are off the default-path budget by construction
   (the renderer reads the template; the orchestrator's default read set does not).

2. **`step-3-6-audit.md`** — the orchestrator's own procedure. The two data-dependent checks
   (the anchor is not byte-identical to the dimension's rendered prompt text; a quoted draft
   line provably appears in the draft) can only run where the draft and the authoritative
   dimension enumeration are both held, which is the orchestrator, before any reference could
   be loaded conditionally.

What landed there is the *compressed* residue of a ~2,600-byte first draft. Everything the
state owner already enforces was cut rather than restated — the closed outcome set, the
text-only anchor floor, the floor-failure downgrade to `unestablished`, the summary-line fields,
and the offer cap all live in `scripts/issue-audit-state.py` and its tests, per the repo's
helper-cutover convention. The full narration lives in `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` §11.
What remains on the mandatory path is only what the orchestrator must *decide*: when to
enumerate, what to check against the re-read draft, what to adjudicate, what to record, and
that `coverage=hold` joins the single existing boundary offer rather than adding a second pause.

## Stated residual — what `coverage-backed` does and does not claim

`--expected-keys` and `--render` are **orchestrator-supplied**: the state owner holds no
template, so it enforces totality against the keyset it is *given*, not against the
renderer's output. An orchestrator that passed only the keys the auditor returned would make
totality vacuous. What the tool does close: it refuses an unenumerated key, synthesizes every
missing enumerated key as `unestablished`, and persists the supplied keyset
(`coverage_expected`) so the claim is auditable after the fact. So `coverage-backed` means
*evidence of the required shape was present and survived the floor and the orchestrator's
adjudication* — never certified scrutiny. That bound is the issue's own stated honesty scope.

## Residual

As shipped, the default path measures **32,619** against the renegotiated **34,249** ceiling — about
1,630 words (~5% of the measurement) of headroom, which is the full AC6 5% maximum the operator
authorized in this change. That margin is a one-time renegotiation, not a standing allowance for
single-change growth: the ratchet-down-only rule resumes immediately, so a later measured reduction
lowers the recorded ceiling, and the next contributor adding to a default-path member should still
prefer shedding prose over spending the margin. Re-measure with the suite's python3 word-split
(`ci614_words` in `lib/test/modules/create-issue-contract.sh`), never `wc -w`; these figures are
historical. The retired budget record is `create-issue-budget.md`, and `CHANGELOG.md` records the
subsystem's retirement.

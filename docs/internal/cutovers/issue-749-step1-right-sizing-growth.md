---
schema: 1
kind: growth
---
# Issue #749 — step1 right sizing growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/create-issue/SKILL.md` — +3,963 bytes (17,926 → 21,889).
- `skills/docs-verify/SKILL.md` — +3,839 bytes (12,284 → 16,123).
- `skills/create-issue/references/step-2-clarify.md` — +1,214 bytes (31,085 → 32,299).
- `skills/create-issue/references/fallback-read-only-sandbox.md` — +960 bytes (4,099 → 5,059).
- `skills/create-issue/references/issue-template.md` — +446 bytes (46,674 → 47,120).
- `skills/create-issue/references/step-4-present-create.md` — +351 bytes (40,282 → 40,633).
- `skills/create-issue/references/step-3-6-audit.md` — +320 bytes (78,210 → 78,530).
- `skills/create-issue/references/fallback-no-task-tool.md` — +295 bytes (3,693 → 3,988).
- `skills/create-issue/references/audit-prompt-template.md` — +143 bytes (21,767 → 21,910).
- `skills/create-issue/references/fallback-audit-dispatch-arms.md` — +67 bytes (6,083 → 6,150).
- `CLAUDE.md` — +219 bytes (75,804 → 76,023).

The growth concentrates in two roots. `skills/create-issue/SKILL.md` gains Step 1's arm set,
its pre-pass selection operand, the disjoint-leg partition with its reconciliation and three
`.docs.internal` degenerate cases, the unequal-return degradation, the escalation-only verdict
role, the slug binding with its run pointer, and the degraded arm. `skills/docs-verify/SKILL.md`
gains the duty floor as report-only mode's breadth bound, per-duty statuses with bearing
observations, the no-nested-dispatch rule, and the `--search-space` operand its two execution
steps now read.

The reference deltas are consequences, not new ownership: the out-of-bounds enumerations widen
by one artifact (three files), the slug binding is *removed* from three references and deferred
to Step 1, the drift-detail landing site is declared in the issue template, and the read-only
sandbox arm names the two new artifacts. `CLAUDE.md`'s delta is the budget bullet's legality-band
mirror, which a ceiling renegotiation is explicitly permitted to edit.

No mandatory row is reduced or relocated, and no prose ownership transfers away from an existing
surface, so `growth` is the only audited decision this diff needs.

## Justification

Step 1's new prose cannot move behind a load trigger. Every sentence of it decides what the
orchestrator does *before* the first dispatch — which arm runs, over which legs, with which
operand, having bound which slug. A reference load is itself a decision made after that point,
so a conditionally-loaded Step 1 would have to be read on the default path anyway, which is the
definition of mandatory.

It also cannot be discharged by a helper. The repo's cutover bar requires a sole tested owner on
every path that consumed the prose, and there is no executable owner available here: the pre-pass
judgement of engaged duties is a model judgement over a topic, and the reconciliation of two peer
returns is a judgement over free-text reports. `lib/test/modules/create-issue-contract.sh`'s
`#749` block pins each of those contracts and proves each behavioral pin RED under a mutation
that re-introduces the guarded defect — that is coverage of the contract, not an owner that could
replace it.

The peer's half is likewise irreducible. The duty floor has to be stated in
`skills/docs-verify/SKILL.md` because the peer, not the caller, is what bounds the survey once it
is running; stating it only in Step 1's dispatch prose is exactly the override-by-prompt that
AC4 forbids, since the peer's own contract wins.

The cost is bounded and paid for. Both create-issue ceilings were renegotiated by explicit human
authorization in the same change, and the legality band widened 5% → 10% after the previous band
was consumed to ~0.8% root / ~1.5% default-path headroom. These figures are historical; see
[`create-issue-budget.md`](create-issue-budget.md) for the retained context and `CHANGELOG.md` for
the subsystem's retirement. `skills/docs-verify/SKILL.md` is loaded on
the default path but sits outside both ceiling operands: it is dispatched into a peer's context
and never read into the orchestrator's, so its growth costs the caller nothing.

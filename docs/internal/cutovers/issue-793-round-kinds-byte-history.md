---
schema: 1
kind: cutover
---

# Cutover record — issue #793: tool-owned round kinds and a durable byte history

**What changed.** `/prflow:create-issue`'s Step 3.6 rounds stopped all being the same round.
The round **kind** joins the arm as a second tool-owned per-round dispatch dimension:
`scripts/issue-audit-state.py` derives it from recorded facts (`select_round_kind`), answers it
read-only (`query-round-kind`), and `record-dispatch` requires `--kind` and refuses any kind other
than the one the tool selects at that moment. A `targeted` round re-checks the enumerated
already-raised claims over the tool-derived changed-section set instead of re-deriving the whole
draft and the whole repository; a `discovery` round is the cold whole-draft round that always
existed. `scripts/stage-draft-write.py`'s `stage --path` became a base the helper completes with
the staged bytes' own digest, which is what gives the run the durable byte history a delta needs.
The efficiency axis this addresses, and the maintainer measurement obligation for it, live in
[`create-issue-context.md`](../create-issue-context.md), which is the single source of truth for
that axis; no figure from it is restated here.

## Superseded prose, deleted in the same change

The *Prose cutover* convention retains policy, invocation contracts and stop conditions in the
skill and removes operative decision logic once an executable helper is its sole tested owner.
One passage class left `skills/create-issue/references/step-3-6-audit.md` on that rule:

- **The single-artifact staging contract.** The skill used to state that the staging path is
  nonce-keyed and that "no delete step exists at all" *because* no prior run's artifact is
  reachable — prose describing a one-slot artifact. `stage` now owns path resolution end to end
  (the digest is computed from stdin inside the helper, and each shell fence is a fresh process,
  so no caller can compose the leaf), and `record-staged-write`/`query-staged-write` own recovering
  the artifact's name across turns. The skill retains what remains policy: which call to make and
  when, and the `state-owner unavailable` arm's reduced-durability disclosure. `stage-draft-write.py`
  and `issue-audit-state.py` are the sole tested owners.

**Deliberately NOT cut over.** The selection logic itself never entered the skill: no prose states
which conditions select which kind. That is the point of the design — the skill obeys
`query-round-kind`'s answer exactly as it obeys `query-arm`'s, and a second copy of the five
conditions in prompt prose is precisely the drift the query-then-obey shape exists to prevent.

## The three refusals, and why each is where it is

The mechanism refuses in three places rather than one, and the split is decided rather than
incidental:

1. **`write-dispatch-scope` refuses** unless the tool currently selects `targeted`. This stops the
   scoped artifact from existing at all on a run that should take a cold round.
2. **`record-dispatch` refuses** a kind other than the selected one (`kind-mismatch`) and a scope
   file whose recorded basis digest does not equal the bytes the dispatch audits
   (`scope-basis-mismatch`). The second is the only guard that sees a byte edit landing between
   selection and dispatch — the skill re-runs the Step 3 gate in that window, and carriage,
   regeneration and steering all still pass over superseded regions.
3. **`render-audit-prompt.py` refuses** an empty claim set. This one is not redundant with (1): it
   stops a *hand-made* scope file from rendering a round that would pass vacuously.

## The freezing constraint, stated once

The file-arm instruction file is regenerated at return time and digest-compared over a **closed**
recorded input tuple, and a divergence is **sticky** (`any_dispatch_diverged`, which
`_steering_established` treats as terminal). So the scoped payload could not ride as an unrecorded
render argument, and could not be read from live run state: post-close status mutations would give
the return-time regeneration a different ledger than dispatch saw, and every scoped round would
diverge. Both payloads therefore travel in one dispatch-scope file whose **path and content
digest** both join the recorded tuple. That is what lets a scoped round establish steering on the
same terms a cold one does, rather than being pushed onto the override path by its own
optimisation.

## Budget separation, and the constant that was left alone

The confirming whole-draft round that follows an all-`addressed` scoped round is funded from
`_MAX_CONFIRMING_ROUNDS`, its own counter. At the time of this change `_MAX_AUTOMATIC_REAUDITS` was
left **unchanged** at 1, and the reason was a second reader rather than caution: besides the spend
predicate, `next_action` compares against it to choose between running another round now and asking
the user first, so raising it would move one whole audit round out of the user's decision on
**every** run — including every embed-arm, inline-arm and empty-delta run that can never take a
scoped round and would pay a full cold round for no saving. Issue #827, which proposed raising it
from 1 to 2, was closed as not planned in favour of that position.

**Superseded by issue #1751.** `_MAX_AUTOMATIC_REAUDITS` is now `0`: the automatic re-audit after a
`REVISE` verdict is abolished, `next_action` always falls through to `revise-then-evaluate-offer`,
and `revise-and-reaudit` is unreachable — every audit round is now offered to the user before it
opens, so the "second reader" reasoning above resolves the same way in the opposite direction (the
skill spends no round the user did not elect). **`_MAX_CONFIRMING_ROUNDS` stays 1** across that
change: the confirming round completes the evidence for a scoped round the user already elected, so
it is not the skill spending a round on its own initiative, and on a run that elects nothing there
is no scoped round and the counter never spends.

## Deferred with this change

Acceptance criteria 48–59 — the `scripts/create-issue-context-eval.py` measurement instrument
(sidechain attribution, round-boundary derivation from the transcript's own `record-dispatch`
records, the best-effort state-file reader, the before/after operands, the per-kind medians, the
three escaped-defect proxies, and the ledger's quoted-draft-line field with its fixture pair) —
are deferred to the follow-up **issue #889**. The seam is a genuine prerequisite one: every deferred criterion
reads a round kind that this change had to record first, so the instrument could not have been
written before the mechanism landed.

<!-- prflow:create-issue-ref step=fallback-state-owner-unavailable file=skills/create-issue/references/fallback-state-owner-unavailable.md start -->

## Fallback — `state-owner unavailable`

Exactly 2 classes route here, and nothing else:

1. The tool invocation produces no contract output at all — the interpreter is absent, the invocation is denied, or it crashes.
2. A mutation exits non-zero because the tool cannot establish or persist this run's state. This environmental class is defined by a principle, not an enumerated list: it is any breadcrumb from persisting or loading the state that is not a nonce mismatch — a persistence, draft-file-read, git-execution or leftover-delete failure, and every load-time state error the tool raises when reading the existing state file, whether physical (missing — `no state file … run init first` — empty, unparseable JSON, or otherwise unreadable) or semantic (it parses but fails the tool's own schema validation, with a breadcrumb naming a *recorded* field that is corrupt or outside its canonical set, e.g. `the creation record names an attestation status outside … 'maybe'` or `round N findings_count -1 is not a non-negative integer`). The tool collapses any such state to *unestablished*, so the run's lifecycle state cannot be trusted → this fallback.

Discriminator against Route B below: a `_validate` breadcrumb is about the *on-disk state* the tool loaded (Route C); an argument-validation breadcrumb is about a value *this skill just supplied on the command line* (Route B) — a state file whose recorded `findings_count` is `-1` is corrupt state, whereas `record-return --findings-count -1` is a bad argument you passed. Route by whose input is bad: the loaded state, or the call you just made.

## The two exits that route elsewhere

Two other non-zero mutation exits route elsewhere, never here, so every breadcrumb has exactly one route (the three destinations partition the mutation exits):

- An illegal-transition or transition-legality rejection — a breadcrumb the tool raises from its OWN transition logic rather than from loading the state, refusing an illegal state move (a nonce mismatch included, as well as a re-init over recorded rounds, already-frozen attestation, or a record against a missing/closed round or a missing creation epoch) → obey `query-next-action` instead, per the contract above. Never re-issue the illegal move, and never route it to the fallback — that would turn the tool's fail-closed refusal into a licence to improvise around it.
- A caller-contract / input-validation rejection — a breadcrumb naming a bad *argument this skill supplied* (a negative `--findings-count`, an unknown `--marker`, an out-of-order or unfunded `--round`, a `user-decline` override missing its `--surface`, a `cap-reached` recorded before the ceiling) → the state owner is fully available and correctly rejecting a malformed call, so correct the offending argument and re-issue the identical call. Never route it here (that would degrade the lifecycle for a fixable argument) and never treat it as an illegal transition.
  This route also covers an OMITTED operand the state cannot resolve, not only a bad one. Where a state-defaulted `--round` is omitted on a run whose state does not uniquely determine a round, the mutation exits non-zero naming the ambiguity: nothing is wrong with the *loaded state* and no illegal transition was attempted, so the remedy is the sibling of correcting a wrong argument — name the round explicitly and re-issue the identical call. The widening is over mutation exits only; `query-next-action` answers an unresolvable round with a decided `reason=` token at exit 0 and never routes anywhere.

## What the fallback does

On the `state-owner unavailable` fallback (the two classes above), run exactly one audit round (a fresh-context dispatch where a subagent tool exists; the inline template where none does), keep the findings and verdict in-chat, offer exactly one continue/decline choice, and proceed to presentation only on the user's explicit election — which on this path is inherently the recorded-in-chat override. The audit summary line carries the distinct marker **`state-owner unavailable`**.

Steering-absence is unestablished on this path too, and the line says so — the state owner is what regenerates the canonical instructions and owns the comparison, so with it unavailable no round can establish the property. Render the `audit independence unestablished` marker beside the `state-owner unavailable` one rather than omitting it, and never let this path's in-chat election read as a coverage-backed clean audit.

The obligations degrade to this arm's existing bounded behavior: the tool-enforced per-finding advisory/invalid records, their pre-approval rendering report, and the calibration layer are **unavailable** here. Disclose that in-chat and grade advisory/invalid findings in the single in-chat round without a tool-enforced record.

## Entering after a completed round

Entered after ≥1 completed round, the fallback sources that round's findings and verdict from the query surface whenever any query still answers — queries are read-only, so a mutation-persistence failure leaves them answering — and never from memory. When no query answers and the findings are no longer in context (compaction), dispatch the single fresh round instead; when that dispatch is also impossible, the single continue/decline offer names the unrecoverable state explicitly. A findings summary reconstructed from memory and presented as a round's real findings is never a legal discharge.

The `state-owner unavailable` marker is **distinct from `degraded`**, which keeps its existing meaning — the inline audit arm — and the two never substitute for one another. A fallback lifecycle is **never silent**: the mandatory-summary-line contract holds here exactly as everywhere else.

<!-- prflow:create-issue-ref step=fallback-state-owner-unavailable file=skills/create-issue/references/fallback-state-owner-unavailable.md end -->

<!-- prflow:create-issue-ref step=fallback-audit-boundary-offer file=skills/create-issue/references/fallback-audit-boundary-offer.md start -->

## The Step 3.6 → Step 4 boundary offer

`references/step-3-6-audit-adjudication.md` loads this file when its unconditional `query-boundary` call reports a trigger component at `hold`, or when it found an `unledgered_revise` round. Read that answer back rather than re-calling it.

Its trigger component answers `t1=hold|not-hold t2=hold|not-hold coverage=hold|not-hold calibration=hold|not-hold reason=…`.

- T1 consumes the RUN-WIDE EFFECTIVE unresolved must-revise count — the ledger entries still unresolved across every recorded ledger, with resolved, invalidated and superseded entries excluded — not the count frozen at round close and not the raw `VERDICT: REVISE` token: it holds only when at least one effective unresolved must-revise finding remains.
- T2 holds on the fail-closed `unadjudicated-round` arm — a completed REVISE round whose post-adjudication unresolved-must-revise count is absent, whether never adjudicated or adjudicated with an unestablished count — and on its other arms: when a revision postdates the latest completed round, on a `no-verdict` round, on a `FILE`/`REVISE` round whose steering was not established (`reason=steering-unestablished`), and when lifecycle state is unestablished/unknown, with the reason surfaced.

  For an unusable targeted return, ownership is sequential: while whole-draft confirmation capacity remains, `query-next-action` owns the `confirm-whole-draft` transition; once that capacity is exhausted, this T2 boundary offer owns the pause. An exhausted unusable targeted return fires T2 with `reason=targeted-return-unusable` and routes through this existing boundary election. Do not invent a new eligibility token or override: an explicit decline or the existing `cap-reached` route enables the later sanctioned filing election.
- `query-convergence` reports whether the run has converged, answering `converged=<yes|no> reason=<token or empty> basis=<adjudicated|resolution|resolution-stale|none> unledgered_revise=<comma-separated rounds or none>`. A converged run is one with zero run-wide effective unresolved must-revise axis-attributable findings, reached either because its final accepted, post-adjudication verdict is `VERDICT: FILE` (basis `adjudicated`), or because every recorded ledger entry was settled post-close by a self-verified resolution or invalidation (basis `resolution`, or `resolution-stale` when a later revision postdates an entry's verification). Advisory and invalid findings do not block convergence, and an unestablished effective count is not converged.

While any of the four trigger components holds, this file's grounds join Step 4 sub-step 3a's single pre-approval audit-round offer — asked once, after the rendered draft has been shown and before approval is requested. Offer one more audit round via the runner's user-question tool, naming which trigger fired (and naming the unestablished state when `reason=state-unestablished` — unknown is not zero).

Name the resolution-cleared state when it is the one you are in. When T2 alone holds and `query-convergence` answers a resolution basis (`basis=resolution`, and the `basis=resolution-stale` variant equally), the offer states plainly that the revised bytes have not been re-audited and the findings are self-verified fixed. On the stale variant, add that at least one of those verifications predates a later revision.

One further arm you must check yourself. A `REVISE` round adjudicated with an `unestablished` count records no ledger. `query-convergence` names those rounds directly, in its `unledgered_revise=` field — a comma-separated list of the completed rounds adjudicated `REVISE` that recorded no ledger, or the literal `none`. Read that field; never infer the set yourself. When `query-convergence` answers `basis=resolution` (or `resolution-stale`) and `unledgered_revise=` names any round, treat the run as warranting one more audit round and offer it on that ground, naming exactly the rounds that field lists.

Conducting the offer. It is outside the Step 2 clarification budget and draws nothing from it, and pausing for the answer is the same sanctioned waiting state as the Step 4 confirmation gate. Record the outcome with `record-offer` (`--accepted` on "yes") and obey it: the tool owns the per-run ceiling and refuses an accepted offer past it, so never count rounds yourself.

- On "yes", run the full round: verify findings against the code, revise, re-run the Step 3 no-options gate, then run **Revision-delta verification** before re-evaluating the triggers.
- On "no" — an explicit decline through the question tool, or one of Step 2's three explicit disengagement replies — record it with `record-override --kind user-decline --surface t1t2-boundary` and proceed to Step 4 with surviving findings quoted verbatim.
- When the tool refuses the offer because the ceiling is reached, record `record-override --kind cap-reached` and proceed; the summary line names the ceiling.
- A silent non-response follows the existing Step 2 silent-non-response rule: pause and re-ask in the final chat message; never dispatch and never proceed on silence.

These grounds are one input to Step 4 sub-step 3a's single audit-round offer, never a second question of their own: the boundary grounds above, a post-revision re-audit, an unsteered re-dispatch (`reason=steering-unestablished`), and the final-byte trigger (`query-final-byte`) are all asked through that one offer, and exactly one offer fires per pause. Sub-step 3a states the precedence when several grounds hold at once, and each ground keeps the recording channel named here — this file's `record-offer` / `record-override --surface t1t2-boundary` pair among them.

<!-- prflow:create-issue-ref step=fallback-audit-boundary-offer file=skills/create-issue/references/fallback-audit-boundary-offer.md end -->

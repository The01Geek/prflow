# Cutover record — issue #792: final-byte audit coverage

**What changed.** `/prflow:create-issue`'s Step 3.6 audit lifecycle gained a reported axis
answering whether the bytes that would actually be **filed** carry a `VERDICT: FILE` from a round
dispatched against those exact bytes, plus an exact-byte safety pass offered at the last moment
that question can be answered truthfully.

## Why a new axis rather than an extension of an existing one

Three surfaces already looked like they could carry this, and each was rejected for a stated
reason. Recording those reasons here is the point of this file: a later change that "unifies" one
of them would reintroduce exactly the conflation this issue removed.

| Candidate | Why not |
| --- | --- |
| The creation attestation | Its comparand is deliberately the digest of the bytes the creation will **actually post**, so a legitimate override filing attests `match` against bytes the audited round never covered. It proves **identity**, never **audit coverage** — collapsing the two is the defect. |
| `evaluate_convergence` / `query-convergence` | Folding audit *reach* into a findings-based convergence answer is the axis conflation the shipped coverage precedent (#708) already avoided, and a new field there breaks every whole-line assertion over that query at once. |
| `evaluate_triggers` / `query-triggers` | Its Step 3.6 → Step 4 boundary consumer applies *"While **any** holds, offer one more audit round"* at the **pre-presentation** pause, where the bytes are not yet final — a fifth field there would fire the pass at the wrong moment. Its answer shape is fixed by whole-line comparands besides. |

The axis is instead modelled on the shipped **coverage-backing** axis (#708): reported on every
arm, offer-bearing, and gating nothing. It diverges from that precedent in exactly one place —
**offer transport**. Coverage joins the boundary offer; final-byte coverage is answered on its own
`query-final-byte`, because the boundary fires before the bytes are final.

## The four terms of `covered`, and the four things that never set it

`covered` inherits **all four** terms of the shipped clean test, not only the two that are about
bytes, because the axis reports what the engine would actually ground on:

1. the newest completed verdict-bearing round carries `VERDICT: FILE` (a newer completed `REVISE`
   revokes it, exactly as `evaluate_eligibility`'s clean scan does);
2. the digest recorded at that round's dispatch equals the current canonical-file digest;
3. no recorded revision postdates that round; and
4. that round's steering-absence was **established** — the engine already refuses to ground on a
   round whose independence could not be established, so the axis reports `uncovered` there, which
   is precisely the round the exact-byte pass exists to offer against.

The complement of the following set is what `covered` means. None of these is read anywhere in
`evaluate_final_byte_coverage`:

- a creation **attestation** — tamper evidence over the posted bytes, not audit coverage of them;
- a **`cap-reached`** override — it records that a ceiling was reached, not a verdict;
- a **`user-decline`** override — a user's election to file is not an auditor's reading of the
  bytes;
- a clean round whose **steering-absence was never established** (term 4).

`unestablished` is **not** `uncovered`, and it covers exactly four states: no readable, owned
lifecycle state exists at all (an unreadable/corrupt record, or a foreign nonce the caller
collapsed to `None`); no completed file-arm verdict-bearing round exists; the canonical file could
not be digested; or the query was supplied no draft digest. A trigger phrased as "not `covered`" would fire on states where an accepted round
cannot change the answer — funding nothing and leaving the run with no next action.

## Why the selector reads the newest **file-arm verdict-bearing** round

`_final_byte_round` deliberately is not `last_completed`. `_clean_identity`'s byte-identity test
reads a recorded dispatch digest solely under `attempts[-1]['arm'] == 'file'`, so reading the run's
latest completed round instead would let a pass whose pre-dispatch write failed — and therefore
landed on the embed arm — downgrade a known `uncovered` to `unestablished` and consume the slot on
a read-only host. That is the one degradation the offer must survive. Revocation by a newer
verdict-bearing `REVISE` on **any** arm is applied by the derivation rather than the selector, so
the selector keeps answering with a round whose digest can actually be compared.

## The slot, and why it is keyed to the bytes rather than the run

The dedicated slot sits **outside `_USER_ROUND_CAP`**. That is the whole point: the run this pass
is promised for is the one that legitimately spent every discovery round, and `cmd_record_offer`
hard-refuses at that ceiling. `cap-reached` is not a grant either — `cmd_record_override` refuses
a premature record and then pins the counter *to* the ceiling.

The slot is spent **per canonical digest**, so re-arming falls out of the existing digest
comparison with no revision hook at all: Step 4's iterate loop repeats until the user approves, and
a pass taken on bytes the user then edits must not leave the bytes actually filed unofferable.
`_FINAL_BYTE_PASS_CAP` is what bounds that re-arming of **honoured** passes, since the loop can
return to the election any number of times. It does not bound a run whose every pass *degrades* — a
refund returns that headroom by design — so a second, absolute `_FINAL_BYTE_GRANT_CAP` bounds
total grants and stops a refund→re-arm→refund livelock on a host where the pre-dispatch write
always fails.

The two ceilings **disclose differently**, and conflating them is the trap. `final_byte_exhausted`
is derived from the *honoured-pass* cap alone — `max(0, granted − refunds) >= _FINAL_BYTE_PASS_CAP`
— so a run stopped by the **grant** ceiling renders `final_byte_exhausted=no`: on an all-degrading
host every grant is refunded, the effective count never leaves `0`, and that is precisely why the
pass cap cannot bound that loop and this second ceiling has to exist. `_row792_grant_ceiling` pins
that `no` on exactly this state. The grant ceiling is therefore a **livelock backstop with no
dedicated summary-exhaustion signal**: its stop is disclosed on `record-final-byte-offer`'s stderr
breadcrumb, carrying the registered `final-byte-grant-ceiling-reached` token. What the summary line
still guarantees at *either* ceiling is the coverage field at its **true** value — not that the
value is `uncovered`, since an honoured pass that reached the pass cap may legitimately have made
the bytes `covered`. The guarantee is that a run whose bytes a ceiling left unaudited files
reporting `final_byte_coverage=uncovered`, never silently clean.

A pass that closes **without a file-arm verdict** refunds the slot — and the refund is recorded on
a **separate** `final_byte_refunds` term rather than by decrementing the grant counter. That split
is load-bearing and was a live defect the review pass caught: `final_byte_passes_used` is a
*funding* term (it is in `_ROUND_BUDGETS`, and `_funded_rounds` compares against the monotonically
growing `len(doc['rounds'])`; issue #1751 dropped the free `1 +` term from `_funded_rounds`, so a
round is now funded only by a recorded `record-offer --accepted` election and the default run funds
none — the comparison itself is unchanged), so decrementing it retracts budget for a round already opened —
re-arming the offer while hard-refusing the replacement dispatch as unfunded, on exactly the two
states the dedicated slot exists to keep fundable. `final_byte_passes_used` therefore counts grants
a round *did or will* claim: a refund never touches it, and it is decremented on exactly one class
of event — the retraction of an **outstanding** grant no dispatch ever consumed (a decline, or a
recorded revision that supersedes the bytes it was accepted for). Such a grant funded no round, so
removing it keeps the funding sum equal to what the rounds list actually needs. Refunds are
subtracted from the **cap** comparison only, because a degraded round was not a pass. One condition covers all three
degradations the round can take — a failed pre-dispatch write (the round lands on the embed arm), a
return carrying no parseable verdict, and a `VERDICT: DRAFT-UNREADABLE` return once its one
re-dispatch is exhausted — because the offer's own precondition is that an accepted round could
honour it, and a verdict-less round did not.

## The pass must be dispatched with its instruction file

Because `covered` inherits all four terms of the clean test — steering included — a pass dispatched
without `--instructions-file`/`--instructions-draft-path` records `steering_reason=inputs-unrecorded`
and the field reports `uncovered` whatever verdict comes back. Such a pass burns a slot and a
dispatch and can never make the bytes `covered`. The skill prose therefore names those inputs
explicitly rather than leaving "an ordinary whole-draft round through the existing file-arm
machinery" to imply them. This was caught by a review iteration whose test row dispatched the pass
without them and could not reach the headline `covered` state.

## Two things the decline must not be

The decline is recorded on a **dedicated channel the override-validity gate cannot see**.
`_valid_override` ignores the surface token entirely and answers `eligible ground=override` on any
current digest-matching override, so routing "skip the optional safety pass" through
`_OVERRIDE_KINDS` would make it byte-indistinguishable from the deliberately narrow election to
file bytes the audit never cleared. It also never routes through `record-offer`, which would
refuse at the user-round ceiling — the ask must be one the run can actually honour.

## Why an accepted pass retires neither the coverage nor the calibration axis

Both selectors now resolve to `_last_discovery_round` — the newest completed round that is
**not** a final-byte pass. (Named for the concept rather than the exclusion, so a second
non-discovery round kind extends the predicate instead of falsifying the name.)
Recording coverage on the pass itself would not have sufficed: `_coverage_round` returns nothing
unless the latest completed round's outcome is literally `FILE`, so a pass returning `REVISE` would
**erase** an earlier round's coverage evidence rather than re-derive it, and any superseding
adjudication retires the calibration axis. The pass is a whole-draft safety re-read of
already-audited bytes, not a new discovery round.

## Schema

`SCHEMA_VERSION` is **held at 3**. `_validate` treats a version mismatch as a hard refusal with no
migration path, so a bump would strand every run in flight at upgrade time with `init --force` —
which destroys the lifecycle record — as its only recovery. Every added field is additive and read
with a default (`final_byte_passes_used`, `final_byte_refunds`, `final_byte_slot_digest`,
`final_byte_pending`, and the per-round `final_byte_pass` / `final_byte_pass_digest` fields), none
joins `_REQUIRED_TOP`, and `_validate` rejects no unknown
extra key — so a state file written by the new build loads unchanged under the old one, and a run
in flight across the upgrade reports the axis as `unestablished` rather than failing to load. Both
new counters join the integer-shape check at the read boundary, so a wrong-typed value is refused
before any of their consumers reads it, and the two new digest fields are shape-checked on the same
rule as their siblings — a non-string would not crash the comparisons they feed, it would silently
answer the wrong way.

## Coupled sites edited in the same change

- `scripts/issue-audit-state.py` — the derivation, the trigger, the producer, the query, the
  funding test, the refund, the two selector exclusions, `_EVENTS`/`TRANSITIONS`/`_RESULTS`/
  `_TRANSITION_REASONS`/`_PROTOCOL_TOKENS`/`_SUMMARY_FIELDS`. The `/simplify` pass additionally
  single-sourced two enumerations this change would otherwise have duplicated — `_ROUND_BUDGETS`
  (read by both `_validate`'s integer-shape loop and `_funded_rounds`) and `final_byte_passes`
  (read by the slot predicate, the summary's two slot fields, the producer's ceiling refusal and
  the trigger query) — and cut `cmd_query_eligibility` and `cmd_query_summary` over to the shared
  `resolve_draft_digest`, which this change had otherwise made a third copy of the #562
  bound-file-precedence rule. That cutover is byte-output-identical (the `query:` breadcrumb the
  suite pins is unchanged).
- `skills/create-issue/references/step-4-present-create.md` — the sub-step-4 exclusivity sentence
  (now a suppression), the sub-step-5 subsumption, the approval-election evaluation point, the
  return-handling carve-out, and the summary-line field enumeration.
- `skills/create-issue/references/step-3-6-audit-adjudication.md` — the second live copy of the
  one-offer-per-pause contract, the closed Queries enumeration, and the canonical call-sequence
  line. (Issue #1702's Step 3.6 decomposition moved this contract text out of the entry reference
  `step-3-6-audit.md` into the `step-3-6-audit-adjudication.md` member; the pointer is updated here
  accordingly.)
- `lib/test/test_python_scripts.py` — the behavioral rows, plus the two **perturbed comparands**
  this change was obliged to re-derive: the hand-transcribed `_TRANSITION_ROWS` (locked against the
  module table by both length and in-order content) and the order-locked `query-summary` field-run
  ending `… calibration_trigger=no bound_root=`.

The whole-line `query-triggers` comparands are deliberately **not** in that set — the trigger is
answered on its own query, so that query's answer shape is untouched.

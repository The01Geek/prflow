# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Draft-root binding and the mutation/query command
implementations.

Part 3 of the `/prflow:spec` audit-lifecycle state owner. The CLI entry and
the two-class contract live in `scripts/issue-audit-state.py`, which imports this module
and re-exports every name in `__all__`; issue #567 split the bodies out so each source
file loads in one whole-file Read. This module adds no behavior of its own.
"""

from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path

from issue_audit_state_state import (
    _ACTION_NOT_A_CALL,
    _DISPATCH_ROUTE,
    _all_entries,
    _binding,
    _bound_draft_file,
    _check_nonce,
    _checked_kind,
    _checked_kind_reason,
    _checked_next_call,
    _coverage_anchor_floor,
    _effective_unresolved,
    _final_byte_honoured,
    _find_round,
    _funded_rounds,
    _last_scoped_round,
    _last_whole_draft_round,
    _ledger,
    _next_call_invocation,
    _reconstruct_dispatch_bytes,
    _RenderRefusal,
    _require_named_round,
    _revision_postdates,
    _round_kind,
    _targeted_confirmation_needed,
    _unestablished,
    classify_return,
    completed_rounds,
    evaluate_calibration,
    evaluate_calibration_trigger,
    evaluate_convergence,
    evaluate_coverage,
    evaluate_eligibility,
    evaluate_final_byte_coverage,
    final_byte_passes,
    last_completed,
    load_state,
    parse_dispatch_scope,
    revision_ordinal,
    save_state,
    select_round_kind,
)
from issue_audit_state_vocab import (
    _COVERAGE_ANCHORED,
    _COVERAGE_OUTCOMES,
    _DISCOVERY_FIRST_ROUND_REASON,
    _EMBED_MARKER_TEXT,
    _EMBED_MARKER_TOKENS,
    _FINAL_BYTE_REFUNDS_KEY,
    _IMPACT_CLASSES,
    _LEDGER_INGESTED_RESOLVED,
    _LEDGER_PREFIXES,
    _MAX_AUTOMATIC_REAUDITS,
    _MAX_CONFIRMING_ROUNDS,
    _NEXT_CALL_EXCLUDED,
    _PRE_REVISION,
    _SETTLING_KEYS,
    _STEERING_SUMMARY,
    _STEERING_SUMMARY_REASONS,
    _UNESTABLISHED,
    _VERDICTS,
    SCHEMA_VERSION,
    StateError,
    _bound_evidence,
    _DigestError,
    _fail,
    _forged_protocol_token,
    _is_bound_path,
    _record_splitting_char,
    _require,
    hash_bytes,
    split_body,
    state_path,
)


def _dispatch_next_call(cmd_name, slug, nonce, action, arm=None, marker=None, kind=None,
                        state=None):
    """Render the `record-dispatch` invocation an answer token routes to.

    issue #793: `--kind` is now REQUIRED on `record-dispatch`, so it must reach this
    rendered line or the suggestion refuses the moment it is copied — precisely the
    forgotten-flag failure the #795 answer-line contract removed. It is a STATE-DERIVABLE
    operand (the tool owns the selection), so it renders FILLED wherever the caller could
    establish it, and bare in `needs=` only where it could not.
    """
    if arm is None:
        arm, marker = _DISPATCH_ROUTE.get(action, (None, None))
    if arm is None:
        return _unestablished('dispatch-arm-unestablished')
    if kind is None and state is not None:
        # A retry re-dispatches an OPEN round, so the kind it must carry is the one that
        # round recorded — resolvable from state, therefore rendered FILLED rather than
        # left bare in `needs=`. Without this the two `query-next-action` retry routes
        # published a suggestion missing an argparse-required flag.
        # `.get` rather than `[...]`: this renderer runs over caller-supplied state that
        # need not carry every key, and a KeyError here would abort the whole answer
        # line rather than degrading to a bare `--kind` in `needs=`.
        _open = [r for r in (state.get('rounds') or [])
                 if isinstance(r, dict) and r.get('outcome') is None]
        if _open:
            kind = _round_kind(_open[-1])
    operands = [('--nonce', nonce), ('--arm', arm), ('--kind', kind)]
    if marker is not None:
        operands.append(('--marker', marker))
    if kind == 'targeted':
        # `--scope-file` is conditionally required (enforced in `cmd_record_dispatch`, not
        # by argparse), so it is invisible to any reconciliation reading `required=True`
        # off the subparser — exactly the shape that made the file arm publish a suggestion
        # refusing the moment it was copied. The path is the caller's to supply, so it
        # renders bare and lands in `needs=`.
        operands.append(('--scope-file', None))
    if arm == 'file':
        # `record-dispatch` requires `--draft-file` on the file arm, but the requirement is
        # ARM-CONDITIONAL and enforced in `cmd_record_dispatch`, not by argparse — so it is
        # invisible to any reconciliation that reads `required=True` off the subparser.
        # Without this the file arm, the most common lifecycle path, published a suggestion
        # that refuses the moment it is copied. The path is the caller's to supply, so it
        # renders bare and lands in `needs=` like every other caller-supplied operand.
        operands.append(('--draft-file', None))
    operands.append(('--round', None))
    return _next_call_invocation(cmd_name, f'record-dispatch {slug}', operands)


def _resolve_next_call(cmd_name, state, slug, nonce, **ctx):
    """The next legal invocation after `cmd_name`, as one of the three sanctioned shapes.

    THIS LINE IS A GENERATED SUGGESTION THE CALLER REVIEWS BEFORE RUNNING, never an
    instruction, and it never overrides the mandated next step where the two disagree.
    """
    try:
        return _checked_next_call(_next_call_body(cmd_name, state, slug, nonce, **ctx))
    except _RenderRefusal as exc:
        return _checked_next_call(_unestablished(exc.token))


def _next_call_body(cmd_name, state, slug, nonce, **ctx):
    if state is None:
        return _unestablished('state-unestablished')
    if nonce is None:
        # NOT `foreign-nonce`: nothing foreign was supplied. `query-nonce` registers no
        # `--nonce` (it exists to recover one after a compaction), so it reached here with
        # None and published a mismatch diagnosis directly beneath its own correct answer —
        # telling a caller their nonce was wrong at the exact moment it handed them the
        # right one. Separate the two so each reason names what actually happened.
        return _unestablished('nonce-unsupplied')
    if state.get('nonce') != nonce:
        return _unestablished('foreign-nonce')

    # --- the dispatch-routing answers -------------------------------------------------
    if cmd_name == 'query-arm':
        # The fresh-round answer. `query-arm` has just printed the arm it decided; the
        # round is the caller's to supply on `record-dispatch`, so it is rendered bare.
        return _dispatch_next_call(cmd_name, slug, nonce, None,
                                   arm=ctx.get('arm'), marker=ctx.get('marker'),
                                   kind=ctx.get('kind'), state=state)
    if cmd_name == 'query-next-action':
        action = ctx.get('action')
        if action in _DISPATCH_ROUTE:
            return _dispatch_next_call(cmd_name, slug, nonce, action, state=state)
        if action in _ACTION_NOT_A_CALL:
            return _unestablished(_ACTION_NOT_A_CALL[action])
        # No answer token to route on. Name the ambiguity the command itself reported
        # where it has one, so the two lines agree rather than the second going generic.
        return _unestablished(ctx.get('ambiguity') or 'next-action-unestablished')

    # --- the lifecycle chain ----------------------------------------------------------
    if cmd_name == 'init':
        return _next_call_invocation(cmd_name, f'query-arm {slug}', [
            ('--nonce', nonce), ('--write-landed', None), ('--draft-file', None)])
    if cmd_name == 'record-dispatch':
        # The mandated next step is dispatching the auditor, not a tool call.
        return _unestablished('auditor-dispatch')
    if cmd_name == 'record-return':
        rnd = ctx.get('round')
        if rnd is None:
            return _unestablished('round-unestablished')
        return _next_call_invocation(cmd_name, f'record-adjudication {slug}', [
            ('--nonce', nonce), ('--round', rnd), ('--verdict', None),
            ('--must-revise', None), ('--advisory', None), ('--invalid', None),
            ('--unresolved-must-revise', None)])
    if cmd_name == 'record-adjudication':
        rnd = ctx.get('round')
        return _next_call_invocation(cmd_name, f'record-coverage {slug}', [
            ('--nonce', nonce), ('--round', rnd), ('--render', None),
            ('--expected-keys', None), ('--coverage-stdin', None)])
    if cmd_name == 'record-coverage':
        rnd = ctx.get('round')
        return _next_call_invocation(cmd_name, f'query-next-action {slug}', [
            ('--nonce', nonce), ('--round', rnd)])
    if cmd_name in ('query-triggers', 'query-convergence'):
        # Both feed the single boundary offer, which is a user interaction.
        return _unestablished('boundary-offer')
    if cmd_name == 'query-calibration':
        # The mandated next step is rendering the advisory/invalid records to the user —
        # the very observation `record-adjudication-render --landed` attests to.
        return _unestablished('advisory-record-rendering')
    if cmd_name == 'record-adjudication-render':
        return _next_call_invocation(cmd_name, f'query-final-byte {slug}', [
            ('--nonce', nonce), ('--draft-file', ctx.get('draft_file'))])
    if cmd_name == 'query-final-byte':
        return _next_call_invocation(cmd_name, f'query-eligibility {slug}', [
            ('--nonce', nonce), ('--mode', 'approve'),
            ('--draft-file', ctx.get('draft_file'))])
    if cmd_name == 'query-eligibility':
        # Presentation and the approval election are the user's.
        return _unestablished('user-approval')
    if cmd_name == 'record-creation-epoch':
        return _next_call_invocation(cmd_name, f'emit-body {slug}', [
            ('--nonce', nonce), ('--draft-file', ctx.get('draft_file'))])
    if cmd_name == 'record-creation-attestation':
        return _next_call_invocation(cmd_name, f'query-summary {slug}',
                                     [('--nonce', nonce)])
    if cmd_name == 'query-summary':
        # Terminal: the run's last mandated state-owner call.
        return 'next_call=none'
    if cmd_name == 'query-draft-binding':
        if ctx.get('bound'):
            return _unestablished('draft-write')
        return _next_call_invocation(cmd_name, f'record-draft-binding {slug}', [
            ('--nonce', nonce), ('--path', None), ('--tier', None)])
    if cmd_name == 'record-draft-binding':
        # Answers `draft-write`, not a state-owner call: the next mandated step writes the
        # draft with a different tool. Rendering a `record-staged-write` invocation here
        # would skip the staging step the sequence mandates before that call.
        return _unestablished('draft-write')
    if cmd_name == 'record-revision':
        return _next_call_invocation(cmd_name, f'record-resolution {slug}', [
            ('--nonce', nonce), ('--round', None), ('--revision-ordinal', None),
            ('--resolved-ids', None)])
    if cmd_name == 'record-resolution':
        return _next_call_invocation(cmd_name, f'query-eligibility {slug}', [
            ('--nonce', nonce), ('--mode', 'iterate'),
            ('--draft-file', ctx.get('draft_file'))])
    if cmd_name == 'record-offer':
        return _unestablished('user-election')
    # Everything else — the recording side channels (`record-reopen`, `record-invalidate`,
    # `record-finding-evidence`, `record-write-failure`,
    # `record-override`, `record-final-byte-offer`) among them — mandates no single next
    # call: where the run goes next depends on where it already was, which the record
    # itself does not determine.
    return 'next_call=none'


# The closed key set the four context-producing commands may hand back. Checked at the
# producer, so a renamed or misspelled key is a loud AssertionError rather than a silent
# degradation to `next_call=unestablished` — the same invisibility this channel replaced a
# `setattr` side-channel to avoid.
_NEXT_CALL_CTX_KEYS = frozenset(
    ('nonce', 'arm', 'marker', 'action', 'ambiguity', 'bound', 'round', 'draft_file',
     # issue #793: `query-arm` derives the round kind alongside the arm, because the
     # `record-dispatch` invocation it renders now REQUIRES `--kind`.
     'kind'))


def _next_call_ctx(**ctx):
    """A command's own local decision, RETURNED to the `next_call=` resolver.

    Four commands decide something the resolver cannot re-read from the state file —
    `init`'s minted nonce, `query-arm`'s routed arm/marker, `query-next-action`'s answer
    token, and `query-draft-binding`'s bound/none answer. Rather than let those four emit
    inline (which would make the emission site 30-way and put the burden of "decided line
    first" on 30 separate hand-edits), each RETURNS this mapping and the single
    dispatch-level emitter reads it from `args.func(args)`.

    The return channel rather than a `setattr` side-channel on the argparse namespace: the
    ~34 commands that hand back nothing already return `None` implicitly, so they stay
    untouched either way — but a returned value makes the dataflow visible at both ends,
    where a string-keyed attribute stashed onto `args` is invisible to a reader and to any
    static check, and could be written after a `return` had already left the function.
    """
    unknown = sorted(set(ctx) - _NEXT_CALL_CTX_KEYS)
    if unknown:
        raise AssertionError(
            f'issue-audit-state: _next_call_ctx got unknown key(s) {unknown}; the resolver '
            f'reads only {sorted(_NEXT_CALL_CTX_KEYS)}, so an unlisted key would degrade '
            'silently to next_call=unestablished')
    return ctx


def _emit_next_call(cmd_name, args, ctx):
    """Print the trailing `next_call=` line — the FINAL stdout line of every subcommand
    outside `_NEXT_CALL_EXCLUDED`.

    Called from the dispatch wrapper in `main()` AFTER the command's own function has
    returned, which is what makes "the existing decided line is byte-identical and first"
    true by construction rather than by 30 correct hand-edits: no command's own `print()`
    is touched, and a command that refuses (`_fail` raises `SystemExit`) never reaches
    here, so a refusal still carries its exact non-zero-plus-breadcrumb shape.
    """
    if cmd_name in _NEXT_CALL_EXCLUDED:
        raise AssertionError(
            f'issue-audit-state: _emit_next_call called for {cmd_name!r}, which the '
            'three-armed exclusion predicate excludes from emitting next_call=')
    ctx = dict(ctx or {})
    ctx.setdefault('round', getattr(args, 'round', None))
    ctx.setdefault('draft_file', getattr(args, 'draft_file', None))
    # The POST-mutation state: re-read from disk after the command ran, so a mutation's
    # `next_call=` answers against what it just wrote. A read failure is not a crash —
    # `_query_state` is the read-only, never-raising accessor the queries already use, and
    # a `None` state resolves to `next_call=unestablished reason=state-unestablished`.
    state = _query_state(args.slug)
    # A command that MINTS or rewrites the run's nonce hands the value back through the
    # same context channel (`init` does — its `--nonce` is optional and drives cold-start
    # vs re-init, so the caller-supplied value is absent on the cold path and comparing it
    # would answer `foreign-nonce` about the run `init` just created). Reading it from the
    # context rather than testing `cmd_name` here keeps this emitter subcommand-agnostic:
    # a second nonce-minting subcommand needs no second `if cmd_name ==` arm.
    # Read EVERY namespace field the same guarded way (issue #795 review): `query-nonce`
    # registers no `--nonce` at all — it EXISTS to recover the nonce after a compaction — so
    # an unguarded `args.nonce` crashed the one call a lost run makes, breaking the query
    # class's exit-0 contract on the recovery path it exists for. The emitter must depend on no
    # parser shape it does not itself check; the resolver already answers `foreign-nonce` /
    # `state-unestablished` for an absent value.
    nonce = ctx.pop('nonce', None) or getattr(args, 'nonce', None)
    # issue #1803: block prints after the decided answer line(s) and before `next_call=`.
    # Guard the SECONDARY block so its data-shape failure never suppresses the primary next_call;
    # re-raise AssertionError so a contract bug stays loud in main()'s handler, never swallowed.
    try:
        _block = _summary_block_line(summary_fields(state))
    except AssertionError:
        raise
    except Exception as _exc:
        # Name the swallow on stderr: without it a `summary_fields` data-shape bug drops the
        # block for every caller with no signal, leaving the loss indistinguishable from a
        # subcommand that legitimately emits none.
        print(f'issue-audit-state: summary-block render failed ({type(_exc).__name__}: {_exc}); '
              'block omitted, next_call= stands', file=sys.stderr)
        _block = None
    if _block is not None:
        print(_block)
    print(_resolve_next_call(cmd_name, state, args.slug, nonce, **ctx))


def route_arm(write_landed, hash_ok, prior_unreadable):
    """Decide a dispatch's arm.

    Returns (arm, marker_token|None). The three embed markers are the ported entry
    conditions, preserved verbatim in `_EMBED_MARKER_TEXT`.

    The three inputs are not equals: `hash_ok` the tool observes itself, `prior_unreadable`
    it recorded at the previous return (`cmd_query_arm` reads it back rather than trusting
    the caller), and `write_landed` is the one genuinely orchestrator-reported fact — the
    tool does not own the draft write, so it cannot observe whether it landed.
    """
    if prior_unreadable:
        return 'embed', 'file-unreadable'
    if not write_landed:
        return 'embed', 'write-failed'
    if not hash_ok:
        # Delta 1: the digest-unrecorded entry now fires when the tool failed to
        # establish the file-arm comparand (its own hash of the draft file failed).
        return 'embed', 'digest-unrecorded'
    return 'file', None


# The audit-summary field set, named once. `summary_fields` answers on two independent
# branches (state-unestablished and ok), and the query surface renders the returned mapping
# key-by-key — so a field added to one branch and forgotten on the other is a KeyError at
# that surface, i.e. a query that cannot answer. Queries are contractually always-exit-0, so
# that is a two-class-contract violation, not a cosmetic slip. `_summary` is the ONE
# constructor both branches go through: it fails loudly, at the call, on a missing or unknown
# field, so the two branches cannot drift apart silently.
_SUMMARY_FIELDS = (
    'state', 'findings_count', 'revisions_applied', 'verdict', 'rounds_run',
    'consumer_dimensions_appended', 'degraded', 'user_declined', 'cap_reached',
    'markers', 'token', 'stale_token', 'reinit_forced', 'attestation',
    # Post-adjudication actionability of the LATEST completed round (issue #548): the
    # adjudicated verdict, the per-class counts, and the unresolved-must-revise count.
    'adjudicated_verdict', 'must_revise', 'advisory', 'invalid',
    'unresolved_must_revise',
    # issue #73: the round the verdict and every class-count field above are read from —
    # the latest completed WHOLE-DRAFT round (None until one completes; scoped_round is the
    # round they skip). A space-free token BEFORE `attestation`, the contractually-trailing field.
    'counts_round',
    # issue #793: the round number of the newest completed `targeted` round, or None. The
    # verdict and class-count fields above are read from the latest WHOLE-DRAFT round, so
    # a scoped round would otherwise be invisible on this line — reported here rather than
    # dropped. Renders as a space-free token BEFORE `attestation`, which stays the
    # contractually-trailing field the #546 CLI pins anchor on.
    'scoped_round',
    # issue #562: the bound draft root + its tier token, so the display renders the
    # `draft bound to worktree root` marker from the tool-emitted token rather than
    # from the orchestrator's recall.
    'bound_root', 'bound_tier',
    # issue #603: the run-wide EFFECTIVE unresolved count (what T1 and convergence now
    # consult) alongside the at-close count above, and the convergence basis token. Both
    # render as space-free tokens BEFORE `bound_root`, so `attestation` stays the
    # contractually-trailing field the #546 CLI pins anchor on.
    'effective_unresolved', 'convergence_basis',
    # issue #708: the run's coverage-backing and the coverage round's render state, so the
    # mandatory audit summary line carries the coverage evidence on EVERY arm and outcome —
    # a backed clean run, an unbacked clean run, and every degraded arm alike. Both render
    # as space-free tokens BEFORE `bound_root`, keeping `attestation` the trailing field.
    'coverage_backing', 'coverage_render', 'coverage_reason',
    # issue #743: the run's advisory-adjudication calibration backing, the render
    # reported-observation state, and the never-blocking disclosure trigger. All render as
    # space-free tokens BEFORE `attestation`, which stays the contractually-trailing field.
    'calibration_backing', 'adjudication_render', 'calibration_trigger',
    # issue #792: whether the bytes that would be FILED carry a verdict from a round
    # dispatched against those exact bytes, plus the dedicated slot's spend count and its
    # exhaustion. Reported on EVERY dispatch arm and every round count, including a run
    # whose audit took the degraded inline arm. `final_byte_coverage` renders immediately
    # before `bound_root`, keeping `attestation` the contractually-trailing field; the two
    # slot fields precede it so a run at the cap discloses the exhaustion on this line
    # rather than filing silently.
    'final_byte_passes', 'final_byte_exhausted', 'final_byte_coverage',
    # issue #709: the steering-absence establishment of the LATEST completed round and
    # the closed reason token behind it. Both render as space-free tokens BEFORE
    # `attestation`, which stays the contractually-trailing field.
    'steering', 'steering_reason',
)


# issue #1803: compact subset of `_SUMMARY_FIELDS` for the `summary-block` line. Never add a
# field whose value depends on `current_digest` (`token`, `final_byte_coverage`): the emit site
# holds no `--draft-file`, so it renders a None digest and would disagree with query-summary.
_SUMMARY_BLOCK_FIELDS = (
    'state', 'findings_count', 'revisions_applied', 'verdict', 'rounds_run',
    'consumer_dimensions_appended', 'degraded', 'user_declined', 'cap_reached',
    'markers', 'adjudicated_verdict', 'must_revise', 'advisory', 'invalid',
    'unresolved_must_revise', 'effective_unresolved', 'counts_round', 'scoped_round',
    'convergence_basis', 'steering', 'steering_reason', 'attestation',
)
_SUMMARY_BLOCK_BOOL_FIELDS = frozenset(
    ('consumer_dimensions_appended', 'degraded', 'user_declined', 'cap_reached'))
# Fail loudly at import on a non-subset member, mirroring `_summary`'s loud constructor: a name
# outside `_SUMMARY_FIELDS` would otherwise KeyError deep inside `_summary_block_line` on the
# always-exit-0 query path (a two-class-contract violation), never at this definition site.
assert set(_SUMMARY_BLOCK_FIELDS) <= set(_SUMMARY_FIELDS), (
    'issue-audit-state.py: _SUMMARY_BLOCK_FIELDS must be a subset of _SUMMARY_FIELDS')
assert _SUMMARY_BLOCK_BOOL_FIELDS <= set(_SUMMARY_BLOCK_FIELDS), (
    'issue-audit-state.py: _SUMMARY_BLOCK_BOOL_FIELDS must be a subset of _SUMMARY_BLOCK_FIELDS')


def _summary(**fields):
    missing = [k for k in _SUMMARY_FIELDS if k not in fields]
    unknown = [k for k in fields if k not in _SUMMARY_FIELDS]
    _require(not missing and not unknown,
             f'issue-audit-state: the audit-summary field set is fixed by _SUMMARY_FIELDS; '
             f'this branch omits {missing!r} and adds {unknown!r}. Every summary_fields '
             f'branch must answer with exactly the same fields, or the query surface that '
             f'renders them raises KeyError on the branch that forgot one.')
    return {k: fields[k] for k in _SUMMARY_FIELDS}


def _summary_block_line(fields):
    """Render the compact `_SUMMARY_BLOCK_FIELDS` subset as one `summary-block …` line.

    issue #1803: printed between a subcommand's decided answer line and its trailing
    `next_call=` line, so a caller reads the post-mutation state it needs from the call it
    just made rather than a standalone `query-summary` read-back. Reuses the same
    None/yes-no/`unestablished` conventions the `query-summary` surface uses, so the two
    surfaces cannot render one field two ways.
    """
    parts = []
    for k in _SUMMARY_BLOCK_FIELDS:
        v = fields[k]
        if k in _SUMMARY_BLOCK_BOOL_FIELDS:
            token = _yn(v)
        elif k == 'markers':
            token = ','.join(v) if v else 'none'
        elif k == 'effective_unresolved':
            token = ('none' if v is None and fields['adjudicated_verdict'] is None
                     else _render_count(v))
        else:
            token = 'none' if v is None else str(v)
        parts.append(f'{k}={token}')
    return 'summary-block ' + ' '.join(parts)


def summary_fields(state, current_digest=None, digest_failed=False):
    """The audit-summary-line field set, derived from recorded state.

    The eligibility token is DERIVED here rather than read back from state: queries
    are read-only, so nothing recorded it at issue time. A token is re-emitted only
    while its issuing ground still holds; once a later revision invalidates it — a
    FILE round's digest, an event-ordering ordinal, or a recorded override — the
    distinct stale-token marker is emitted, so a reader string-comparing the
    transcript's token against the state file sees a replayed pre-revision token fail
    to match.
    """
    if state is None:
        return _summary(state='unestablished', findings_count=None, revisions_applied=0,
                        verdict=None, rounds_run=0, consumer_dimensions_appended=False,
                        degraded=False, user_declined=False, cap_reached=False,
                        markers=[], token=None, stale_token=False, reinit_forced=False,
                        attestation=None, adjudicated_verdict=None, must_revise=None,
                        advisory=None, invalid=None, unresolved_must_revise=None,
                        counts_round=None, scoped_round=None,
                        bound_root=None, bound_tier=None,
                        effective_unresolved=None, convergence_basis='none',
                        coverage_backing='unestablished', coverage_render='none',
                        coverage_reason='state-unestablished',
                        calibration_backing='unestablished', adjudication_render='none',
                        calibration_trigger=False,
                        final_byte_passes=0, final_byte_exhausted=False,
                        final_byte_coverage='unestablished',
                        steering='unestablished', steering_reason=None)
    done = completed_rounds(state)
    # issue #86: none when ANY completed round lacks a tally (a pre-#86 round, or a
    # no-verdict close record-return never tallies) — summing only the tallied rounds
    # would present a partial sum as the run total. Empty `done` stays none, as before.
    if done and all(r.get('findings_count') is not None for r in done):
        _findings_count = sum(r['findings_count'] for r in done)
    else:
        _findings_count = None
    markers = []
    for r in state['rounds']:
        for mk in r.get('embed_markers', []):
            if mk not in markers:
                markers.append(mk)
    last = last_completed(state)
    # issue #793: the audit-summary verdict and class counts ground on the latest
    # WHOLE-DRAFT round, and the scoped round is named beside them. Both are resolved
    # ONCE here, for the same single-source reason the axes below cite: two independent
    # call sites could render a verdict and a scoped-round name describing different runs.
    whole = _last_whole_draft_round(state)
    _scoped = _last_scoped_round(state)
    # ONE convergence evaluation feeds both summary fields (issue #603): derived from two
    # independent call sites they could render two fields describing different states.
    _convergence = evaluate_convergence(state)
    # issue #708: one coverage evaluation feeds both coverage summary fields, for the same
    # single-source reason.
    _coverage = evaluate_coverage(state)
    # issue #743: one calibration evaluation feeds the backing + render summary fields and
    # the trigger, for the same single-source reason.
    _calibration = evaluate_calibration(state)
    # issue #792: ONE final-byte evaluation feeds the summary's coverage field, for the
    # same single-source reason as the three axes above — two independent call sites
    # could render a field describing a different state than the one the offer read.
    _final_byte = evaluate_final_byte_coverage(state, current_digest,
                                               digest_failed=digest_failed)
    # ONE read of the latest completed round's steering record feeds both summary
    # fields (issue #709): two independent three-way expressions could drift into
    # rendering a state and a reason that describe different things.
    _steer_rec = (last or {}).get('steering') or {}
    _require(_steer_rec.get('state', 'unestablished') in _STEERING_SUMMARY,
             f'issue-audit-state: the summary steering token '
             f'{_steer_rec.get("state")!r} is outside _STEERING_SUMMARY')
    _require(_steer_rec.get('reason', 'none') in _STEERING_SUMMARY_REASONS,
             f'issue-audit-state: the summary steering_reason token '
             f'{_steer_rec.get("reason")!r} is outside _STEERING_SUMMARY_REASONS')
    elig = evaluate_eligibility(state, 'approve', current_digest,
                                digest_failed=digest_failed)
    token = elig['token']
    stale = False
    if token is None and not digest_failed:
        # An undigestible draft is NOT evidence the token went stale — the stderr
        # breadcrumb names the real cause; rendering stale-token here would be the
        # same misattribution the draft-undigestible reason exists to prevent.
        # A token that was issued and is now invalidated should render stale-token, so
        # a reader string-comparing a replayed token still sees a positive mismatch.
        # TWO grounds can issue a token, so both must be able to stale it:
        #   - a clean FILE round (its token staled by a later revision), covered by the
        #     `any(outcome == 'FILE')` scan below; and
        #   - a recorded override invalidated by a later revision, which can exist on a
        #     REVISE or no-verdict epoch with NO FILE round in `done` at all, so the
        #     FILE scan alone missed it and rendered `token=none` — the override-ground
        #     fail-open this OR closes. Derived from STATE (an override recorded at a
        #     non-current ordinal), not from the eligibility reason alone: refusal
        #     precedence answers `no-verdict-round` before `stale-override` whenever
        #     the last completed round is verdict-less, so on a no-verdict epoch the
        #     reason never reads `stale-override` and a reason-only derivation rendered
        #     `token=none` there. The reason stays OR-ed in for the current-ordinal
        #     digest-mismatch case (a byte-distinct draft at the same ordinal), which
        #     the ordinal predicate cannot see.
        override_staled = (
            elig.get('reason') == 'stale-override'
            or any(ov.get('recorded_at_ordinal') != revision_ordinal(state)
                   for ov in state['overrides']))
        stale = any(r.get('outcome') == 'FILE' for r in done)
        if stale and not override_staled and current_digest is None:
            # One carve-out, scoped to the FILE-round ground only (never the override
            # ground, which the OR below restores): a file-arm clean epoch queried with
            # NO digest supplied was never compared at all — claiming stale there would
            # be the same misattribution in another coat.
            latest_clean = next((r for r in reversed(done)
                                 if r.get('outcome') == 'FILE'), None)
            if (latest_clean is not None
                    and latest_clean['attempts'][-1]['arm'] == 'file'
                    and not _revision_postdates(state, latest_clean)):
                # ...unless a recorded revision positively postdates the clean round —
                # that invalidation needs no digest comparison, so the stale marker
                # stays honest even when no draft file was supplied.
                stale = False
        stale = stale or override_staled
    return _summary(
        state='ok',
        findings_count=_findings_count,
        revisions_applied=revision_ordinal(state),
        # issue #793: the verdict and the class counts below read the latest WHOLE-DRAFT
        # round, never `last` — a `targeted` round's scoped result is not the run's
        # audit-summary verdict. `_scoped` names it separately so it stays visible.
        verdict=whole.get('outcome') if whole else None,
        rounds_run=len(state['rounds']),
        consumer_dimensions_appended=any(
            r.get('consumer_dimensions_appended') for r in state['rounds']),
        degraded=any(r.get('degraded') for r in state['rounds']),
        user_declined=any(o['kind'] == 'user-decline' for o in state['overrides']),
        cap_reached=any(o['kind'] == 'cap-reached' for o in state['overrides']),
        markers=[_EMBED_MARKER_TEXT[m] for m in markers],
        token=token,
        stale_token=stale,
        reinit_forced=bool(state.get('reinit_forced')),
        # The creation-attestation status is part of the audit-summary field set (a
        # mismatch is surfaced here, not only in record-creation-attestation's own
        # output): 'match' | 'mismatch' | 'attestation-unavailable' | 'none'.
        attestation=(state.get('creation') or {}).get('attestation') or 'none',
        # Post-adjudication actionability of the LATEST completed round (issue #548). Read
        # from that round only — the observables the reader checks against the artifact are
        # the final round's, not a cumulative sum. `None` on every field until adjudicated.
        adjudicated_verdict=(whole.get('adjudicated_verdict') if whole else None),
        must_revise=(whole.get('must_revise_count') if whole else None),
        advisory=(whole.get('advisory_count') if whole else None),
        invalid=(whole.get('invalid_count') if whole else None),
        unresolved_must_revise=(whole.get('unresolved_must_revise') if whole else None),
        # issue #73: the round the verdict and class counts above are read from — the same
        # `whole` round, named so the summary line can label its counts. None until a
        # whole-draft round completes.
        counts_round=(whole.get('round') if whole else None),
        # issue #793: the scoped round the fields above deliberately skip — named, not
        # dropped, so a reader sees that a targeted re-check ran.
        scoped_round=(_scoped.get('round') if _scoped else None),
        # issue #562: the bound root + tier token (None on an unbound run — an
        # embed/inline epoch that never bound a canonical file).
        bound_root=(_binding(state) or {}).get('path'),
        bound_tier=(_binding(state) or {}).get('tier'),
        # issue #603: the effective count is run-wide (it aggregates every ledger), not
        # the latest round's frozen tally above — the Step 4 summary line renders both so
        # a reader can see the at-close count AND what post-close settling left.
        effective_unresolved=_convergence['effective'],
        convergence_basis=_convergence['basis'],
        # issue #708: the run's coverage-backing and the coverage round's render state,
        # derived from the final accepted clean round. A distinct axis from convergence —
        # this derivation never feeds `effective_unresolved` or the convergence basis.
        coverage_backing=_coverage['backing'],
        coverage_render=_coverage['render'],
        # WHICH unestablished arm — a clean round whose coverage step never ran is
        # otherwise byte-identical on this line to a run with no clean round yet.
        coverage_reason=_coverage.get('reason') or 'none',
        # issue #743: the calibration backing, the render reported-observation state, and the
        # never-blocking disclosure trigger — derived from the final adjudicated round. A
        # distinct axis from convergence and coverage: this derivation never feeds
        # `effective_unresolved`, the convergence basis, or coverage backing.
        calibration_backing=_calibration['backing'],
        adjudication_render=_calibration['render'],
        calibration_trigger=evaluate_calibration_trigger(state, _calibration),
        # issue #792: the final-byte coverage axis and its dedicated slot. Derived from
        # the SAME digest/digest_failed operands the eligibility derivation above
        # consumes, so the summary can never report coverage over a different draft than
        # the one the approve gate grounded on. A distinct axis: this derivation never
        # feeds convergence, the coverage backing, or the calibration backing, and it
        # never gates `emit-body` or `query-eligibility`.
        final_byte_passes=final_byte_passes(state)[0],
        final_byte_exhausted=final_byte_passes(state)[1],
        final_byte_coverage=_final_byte['coverage'],
        # issue #709: the LATEST completed round's steering-absence establishment, read
        # from that round only — the property binds to the audited bytes, not to the run,
        # so a run-level roll-up would let a steered early round launder a later revision.
        # `unestablished` (with a `none` reason) is the honest answer when there is no
        # completed round, or when a completed round recorded no steering result at all.
        steering=_steer_rec.get('state', 'unestablished'),
        steering_reason=_steer_rec.get('reason'),
    )


# ── Command implementations ────────────────────────────────────────────────────

def _new_doc(slug, nonce):
    return {'schema_version': SCHEMA_VERSION, 'slug': slug, 'nonce': nonce,
            'reinit_forced': False, 'automatic_reaudits_used': 0, 'user_rounds_used': 0,
            # issue #792: the dedicated final-byte slot — a spend counter outside
            # `_USER_ROUND_CAP`, the refund counter that makes an unhonoured grant not
            # consume the cap, the canonical digest the slot is currently spent for
            # (None = unspent), and the outstanding-grant flag. All four are additive under
            # the UNCHANGED schema_version and read with a default everywhere, so a state
            # file written before this feature still loads and reports the axis as
            # `unestablished`. All four are seeded here rather than only the two the write
            # paths touch first, so the fresh-document shape is self-documenting in one
            # place — the defaults below are the same ones every reader already applies.
            'final_byte_passes_used': 0, 'final_byte_refunds': 0,
            'final_byte_slot_digest': None, 'final_byte_pending': False,
            'rounds': [], 'revisions': [], 'overrides': [], 'creation': None,
            # issue #562: the tiered draft-root binding (recorded once) and the
            # per-run canonical-write-failure log at the bound path.
            'draft_binding': None, 'write_failures': [],
            # issue #704: the dedicated per-finding evidence channel. Additive under the
            # UNCHANGED schema_version, so a state file written before this feature still loads.
            'finding_evidence': {}}


def cmd_init(args):
    load_error = None
    load_exc = None
    try:
        existing = load_state(args.slug)
    except StateError as exc:
        existing = None
        load_error = str(exc)
        # `load_state` chains the underlying OSError with `raise ... from exc`, so the
        # absence-vs-unreadable distinction survives on `__cause__`. Reading it here keeps
        # the discriminator on the failure that actually occurred rather than on a second,
        # error-swallowing filesystem probe.
        load_exc = exc.__cause__
    if args.nonce:
        if existing is None:
            # Carry the load failure's own detail: "no readable state file" alone would
            # mask a present-but-corrupt file behind a message recommending the
            # budget-resetting cold start.
            detail = f' (the load failed: {load_error})' if load_error else ''
            # ...and the REMEDY has to split with it. Both arms used to end in "omit
            # --nonce for a cold start", which is the routing-prose's Route-B shape (fix
            # the call you just made). That is right when the file is genuinely ABSENT,
            # and wrong when it is present-but-unreadable: there a cold start silently
            # discards recorded state, and the condition is squarely the routing prose's
            # Route C (a load-time state error). Discriminate on the file's existence,
            # which is the only operand that separates the two.
            # Discriminate on the load failure's own shape, NOT on a follow-up
            # `Path.exists()`: `exists()` swallows every OSError and returns False, so a
            # file present behind a permission-denied parent read as ABSENT and got routed
            # to the cold start this arm exists to prevent — a breadcrumb asserting the
            # absence of a file it names in the same sentence as unreadable. Only a genuine
            # FileNotFoundError is absence; every other load failure is present-but-unreadable.
            if load_error is not None and not isinstance(load_exc, FileNotFoundError):
                _fail('init', 'a nonce was supplied and a state file exists for slug '
                              f'{args.slug!r} but could not be read{detail}; this is a '
                              'state-owner-unavailable condition — do NOT cold-start over '
                              'it, since that would discard the recorded state')
            _fail('init', 'a nonce was supplied but no state file exists for '
                          f'slug {args.slug!r}{detail}; omit --nonce for a cold start')
        if existing['nonce'] != args.nonce:
            _fail('init', 'nonce mismatch — this call does not belong to the run that '
                          'owns this state file; refusing to re-init a foreign run')
        if existing['rounds'] and not args.force:
            _fail('init', 'a same-run re-init over recorded rounds is an illegal '
                          'transition without --force (it would hand this run a fresh '
                          'automatic budget silently)')
        # The attestation is forward-only tamper evidence: record-creation-epoch and
        # record-creation-attestation both refuse to overwrite a recorded match/mismatch,
        # through this same shared accessor. Re-init discards the whole document, so
        # without this third guard --force walked past both of them and query-summary then
        # rendered `attestation=none` — which the skill defines as "before any creation
        # attempt", indistinguishable from never-attempted. Unknown is not zero, and a
        # wiped mismatch must never read as an absent one.
        if _attestation_frozen(existing):
            _fail('init', 'a creation attestation is already recorded for this run; '
                          're-initialising would discard that forward-only tamper '
                          'evidence and render the summary as though no creation had '
                          'been attempted')
        doc = _new_doc(args.slug, args.nonce)
        # Sticky once set: a forced re-init wipes rounds, so a LATER same-nonce re-init
        # takes the no-rounds echo path (rounds now empty, so the --force guard above no
        # longer fires) and would otherwise recompute this as False — laundering the
        # budget-reset disclosure in two legal calls. Preserve a prior `reinit_forced`
        # so `query-summary` cannot lose the evidence that this run took a fresh budget.
        doc['reinit_forced'] = (bool(existing.get('reinit_forced'))
                                or bool(existing['rounds'] and args.force))
    else:
        # Cold start: the ported delete-leftover-first rule. Raises no alarm.
        doc = _new_doc(args.slug, secrets.token_hex(8))
        try:
            path = state_path(args.slug)
        except StateError as exc:
            # An unsafe slug must fail with the named breadcrumb BEFORE the delete-first
            # unlink can act on an escaped path.
            _fail('init', str(exc))
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _fail('init', f'could not delete leftover state at {path}: {exc}')
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('init', str(exc))
    print(f'nonce={doc["nonce"]}')
    # `init` mints the nonce, so it hands the value back rather than leaving the shared
    # emitter to special-case this subcommand's name (see `_next_call_ctx`).
    return _next_call_ctx(nonce=doc['nonce'])


def _load_for_mutation(prefix, slug, nonce):
    try:
        doc = load_state(slug)
        _check_nonce(doc, nonce)
    except StateError as exc:
        _fail(prefix, str(exc))
    return doc


def _attestation_frozen(doc):
    """True once the creation attestation is forward-only tamper evidence.

    The exemption set is the whole rule: `None` (nothing attested yet) and
    `attestation-unavailable` (the honest unknown — a failed fetch, which is NOT
    evidence about the body and so may be re-attested). Any other recorded value is a
    real comparison result (`match`/`mismatch`) and is frozen: overwriting it would
    discard the tamper evidence.

    One accessor, three callers — `init`'s re-init guard, `record-creation-epoch`'s
    rebind guard, and `record-creation-attestation`'s re-attest guard. They were three
    copy-pasted predicates that had to agree by hand: this repo's dominant defect class
    is exactly that shape (a coupled invariant whose mirror sites silently drift), and a
    single site that admits one extra value re-opens the wipe the other two refuse.
    """
    return (doc.get('creation') or {}).get('attestation') not in (
        None, 'attestation-unavailable')


def _permitted_retry_arms(rnd):
    """The arms a pending retry action permits, as a tuple.

    The pending action names the arm the retry was routed to; a mismatched arm would
    silently switch the carriage comparand class mid-round, so the set is closed.

    `dispatch-retry-same-arm` on a FILE-arm round additionally permits the embed arm.
    The canonical file can become unhashable between the return and the retry — the
    concurrent-overwrite/delete race this design contemplates and that `route_arm`
    exists to answer — and `query-arm` then routes the retry to embed. Without this
    escalation the run DEADLOCKS with no legal next call: the embed dispatch the tool
    itself just prescribed is refused as an illegal transition, the file dispatch
    cannot read the file, `query-next-action` re-answers the same spent token forever,
    and the skill is forbidden from improvising around an illegal transition or routing
    it to the unavailable fallback. The escalation is never silent — the embed arm
    requires `--marker` (enforced at the call site), so the entry cause is recorded in
    `embed_markers` and rendered in the audit summary, which is exactly how the sibling
    `dispatch-embed-retry` escalation already reports itself. It is deliberately NOT
    extended to an inline-arm round: inline is the terminal degraded arm, so there is
    nothing to escalate to.

    Disclosed residual: the escalation is permitted, not verified. The tool does not
    re-hash the file at dispatch to confirm it really is unhashable — doing so would
    re-race the very condition the escalation answers — so an orchestrator may take the
    embed arm on any file-arm same-arm retry and thereby self-downgrade from byte-bound
    file-identity to the weaker embed comparand. The entry marker is therefore
    orchestrator-asserted, not tool-observed. This is the same trust boundary
    `route_arm` already documents for `write_landed`, and it is bounded by the same
    disclosure: the downgrade is recorded and rendered, never silent.
    """
    same = rnd['attempts'][-1]['arm']
    permitted = {'dispatch-embed-retry': ('embed',),
                 'dispatch-inline-degraded': ('inline',),
                 'dispatch-retry-same-arm': (same,)}[rnd['pending']]
    if rnd['pending'] == 'dispatch-retry-same-arm' and same == 'file':
        permitted = permitted + ('embed',)
    return permitted


def _cross_check_kind(doc, args):
    """Refuse a dispatch whose declared kind is not the one the tool selects (issue #793).

    The exact sibling of the `write-path-mismatch` cross-check below, and for the same
    reason: the kind is TOOL-owned, so a caller that declares one is echoing an answer it
    was given, not making a decision. Left uncompared, a compacted context could dispatch
    `targeted` over a selection that had since fallen back to `discovery` — pointing the
    auditor at a delta the tool no longer stands behind while carriage, regeneration and
    steering all still pass.

    Returns the selection answer, so the scope cross-check below reuses it rather than
    re-deriving a second, possibly different one.
    """
    # A RETRY re-opens an already-open round, so its kind is a FACT that round already
    # recorded — not a fresh selection. Re-deriving it here would validate the retry
    # against a predicate about a round that does not exist yet, and a selection that
    # legitimately moved between the first attempt and the retry (a revision landed, the
    # byte history changed) would refuse the very re-dispatch the tool itself prescribed.
    # This mirrors how the arm already works: `_permitted_retry_arms(rnd)` reads the ROUND
    # for a retry, while `route_arm` decides only for a fresh one.
    open_round = _find_round(doc, args.round)
    if open_round is not None and open_round.get('outcome') is None:
        recorded = _round_kind(open_round)
        if args.kind != recorded:
            _fail('record-dispatch',
                  f'the declared kind {args.kind!r} is not the kind round {args.round} was '
                  f'opened with ({recorded!r}) (kind-mismatch): a retry re-dispatches the '
                  'round it is retrying, so it carries that round\'s kind')
        _rscope = open_round.get('scope') or {}
        return {'kind': recorded, 'reason': 'targeted-eligible',
                'claims': [(c, '') for c in (_rscope.get('claim_ids') or [])],
                'sections': list(_rscope.get('sections') or []),
                'basis_digest': _rscope.get('basis_digest'),
                # issue #1105: a retry re-dispatches an already-open round, so its span is
                # the FACT that round recorded, not a fresh derivation.
                'draft_lines': _rscope.get('draft_lines')}
    ans = select_round_kind(doc, args.draft_file)
    if args.kind != ans['kind']:
        _fail('record-dispatch',
              f'the declared kind {args.kind!r} is not the kind the tool selects for this '
              f'round ({ans["kind"]!r}, reason {ans["reason"]!r}) (kind-mismatch): the '
              'round kind is tool-owned — re-run query-round-kind and dispatch the kind it '
              'answers')
    return ans


def cmd_record_dispatch(args):
    doc = _load_for_mutation('record-dispatch', args.slug, args.nonce)
    _checked_kind(args.kind)
    if args.kind != 'targeted' and args.scope_file:
        # Structural, and hoisted above the cross-check for the same reason as the arm
        # refusal: a kind-mismatch would otherwise pre-empt it and name the wrong cause.
        _fail('record-dispatch',
              '--scope-file is a targeted-round input; a discovery round audits the whole '
              'draft and carries no scoped payload (scope-file-on-discovery)')
    if args.kind == 'targeted' and args.arm != 'file':
        # STRUCTURAL, so it precedes the kind cross-check: the scoped payload reaches the
        # auditor ONLY through the rendered instruction file, and that file exists only on
        # the file arm — the embed and inline arms are entered because the canonical write
        # already failed. A scoped dispatch there would record a round whose claims no
        # auditor can ever be shown. Checked first so the refusal names THAT, rather than
        # the cross-check refusing earlier with a less specific kind-mismatch.
        _fail('record-dispatch',
              f'a targeted round cannot dispatch on the {args.arm} arm '
              '(targeted-requires-file-arm): the scoped payload reaches the auditor only '
              'through the file-arm instruction file, so re-run query-round-kind — it '
              'selects discovery once the file arm is unavailable')
    _kind_answer = _cross_check_kind(doc, args)
    if args.kind == 'targeted':
        # A `targeted` dispatch carries its whole payload in the scope file, so the file is
        # required and its recorded BASIS is cross-checked against the bytes this dispatch
        # actually audits. The skill re-runs the Step 3 gate between selection and dispatch,
        # so a byte edit landing in that window would point the auditor at superseded
        # regions while every other check still passes — this is the only guard that sees it.
        if not args.scope_file:
            _fail('record-dispatch',
                  'a targeted dispatch requires --scope-file (the frozen dispatch-scope '
                  'file write-dispatch-scope produced); without it the round has no '
                  'recorded payload and its regeneration cannot reproduce (scope-file-missing)')
        try:
            _scope_bytes = Path(args.scope_file).read_bytes()
            _scope_digest = hash_bytes(_scope_bytes)
            _scope_basis, _, _ = parse_dispatch_scope(_scope_bytes)
        except OSError as exc:
            _fail('record-dispatch', f'could not read the dispatch-scope file '
                                     f'{args.scope_file}: {exc} (scope-file-unreadable)')
        except _DigestError as exc:
            _fail('record-dispatch', f'{exc} (scope-file-malformed)')
        if _scope_basis != _kind_answer['basis_digest']:
            _fail('record-dispatch',
                  f'the dispatch-scope file records basis digest {_scope_basis!r}, but the '
                  f'canonical draft now digests to {_kind_answer["basis_digest"]!r} '
                  '(scope-basis-mismatch): the draft changed between selection and '
                  'dispatch, so the recorded changed-section set names superseded regions '
                  '— re-run write-dispatch-scope against the current bytes')
    if args.arm == 'file':
        if not args.draft_file:
            _fail('record-dispatch', '--draft-file is required on the file arm')
        # Tiered-draft-root binding cross-check (issue #569): when the run has bound a
        # canonical-draft root (the first landed write records it via record-draft-binding)
        # and the skill reports where its write landed via --write-path, the reported path
        # MUST match the file the tool derives from the recorded binding
        # (`<bound-root>/.prflow/tmp/spec/<slug>/issue-draft-<slug>.md`, via _bound_draft_file). A
        # divergence is a strong signal that a compacted context drifted which file the
        # dispatch audits, so fail closed with the write-path-mismatch breadcrumb.
        #
        # SCOPE (do not overstate this guard): it validates the REPORTED path only. The bytes
        # digested below still come from the caller's --draft-file, which this command does
        # NOT resolve from the binding — unlike its siblings emit-body / query-eligibility /
        # query-summary, which all read through _bound_draft_file. So a caller that reports a
        # correct --write-path while passing a drifted --draft-file is still recorded. Closing
        # that is the bound-first reader reconciliation deferred with the strict half below.
        # The check is scoped to a bound run with
        # a reported write path — an unbound run (an embed/inline epoch that never bound a
        # canonical file) and a caller that omits --write-path both proceed unchanged, so
        # the cross-check is additive, never a new mandatory field on the file arm.
        #
        # An OMITTED --write-path is an opt-out; a PRESENT-BUT-EMPTY one is not. A caller that
        # composes this value from a shell-resolved root yields an empty string when that root
        # is unresolved — an *unestablished* report, which a truthiness test would silently
        # collapse onto "caller opted out" and disarm the check on exactly the drift it exists
        # to catch (the repo's unknown-is-not-zero rule). Refuse it by name instead. (This is
        # defense in depth, not a description of the shipped skill: spec substitutes an
        # already-resolved literal path here, so it is a hazard for other callers and runners.)
        #
        # NOTE (issue #569 scope split): making the binding itself REQUIRED on every file-arm
        # dispatch (fail-closed `binding-required-on-file-arm` when absent) is the strict half
        # deferred to a follow-up — it ripples into every pre-binding file-arm unit test's
        # bound-first reader setup and must land with that reconciliation, not this pass.
        if args.write_path is not None and not args.write_path.strip():
            _fail('record-dispatch',
                  'an empty --write-path is an unestablished report, not an opt-out '
                  '(write-path-empty): omit the flag entirely to skip the cross-check, or '
                  'report the absolute canonical-draft path the write landed at')
        if doc.get('draft_binding') is not None and args.write_path:
            expected_write_path = _bound_draft_file(doc, args.slug)
            if args.write_path != expected_write_path:
                _fail('record-dispatch',
                      f'the reported write path {args.write_path!r} does not match the bound '
                      f'canonical-draft file {expected_write_path!r} (write-path-mismatch): '
                      'the file arm must write and audit the draft at the bound root')
        try:
            data = Path(args.draft_file).read_bytes()
        except OSError as exc:
            _fail('record-dispatch', f'could not read draft file {args.draft_file}: {exc}')
    else:
        # The draft bytes are read from stdin, hoisted into main() above the section (issue
        # #1040) so this mutating handler performs no blocking sys.stdin read inside the
        # section. `_stdin_bytes_or_fail` reproduces the former in-handler guards verbatim:
        # a closed fd 0 and a read-time OSError each route through _fail with the same named
        # breadcrumb (never a raw traceback that would break the mutation contract).
        data = _stdin_bytes_or_fail(args, 'record-dispatch', 'draft bytes')
        if not data:
            _fail('record-dispatch', f'the {args.arm} arm requires the draft bytes on '
                                     'stdin; received none')
    try:
        digest = hash_bytes(data)
        body_digest = hash_bytes(split_body(data))
    except _DigestError as exc:
        _fail('record-dispatch', str(exc))
    attempt = {'arm': args.arm, 'digest': digest, 'body_digest': body_digest,
               'sentinel_open': None, 'sentinel_close': None,
               # issue #709: the canonical dispatch-instruction record. `None` means the
               # round had no hashable instruction file, which is UNESTABLISHED, never
               # established-clean by omission.
               'instructions': None}
    # issue #709 — the round's CLOSED regeneration inputs, recorded at dispatch. They are
    # what `record-return` re-runs the generator over, so an input the tool cannot record
    # fails the whole record CLOSED (no partial `instructions` object): without every
    # input the regeneration cannot happen at all, and a half-recorded object would make
    # the round look establishable when it is not. The draft TITLE is deliberately NOT
    # among them — the generator reads it from the draft file at `draft_path`, so no
    # drafter free text is stored here or crosses a regeneration argument.
    if not args.instructions_file and (args.instructions_draft_path
                                       or args.instructions_template):
        # The OTHER half of the pair, refused symmetrically. Accepting a lone
        # --instructions-draft-path silently recorded NO instructions object at all, so a
        # dispatch that lost only its --instructions-file argument looked like a
        # deliberate no-instruction-file round and reached the auditor's return as
        # `inputs-unrecorded` — an orchestrator arg-slip diagnosed as a design decision.
        # Refusing here names the slip at the site that can still fix it.
        _fail('record-dispatch', '--instructions-draft-path/--instructions-template '
                                 'require --instructions-file (the instruction file the '
                                 'auditor hashes); without it there is nothing to '
                                 'regenerate a comparand for')
    if args.instructions_file:
        if args.arm != 'file':
            _fail('record-dispatch', '--instructions-file is a file-arm input; the '
                                     f'{args.arm} arm has no hashable instruction file')
        if not args.instructions_draft_path:
            _fail('record-dispatch', '--instructions-file requires '
                                     '--instructions-draft-path (the exact --draft-path '
                                     'value the generator was invoked with); without it '
                                     'the canonical instructions cannot be regenerated')
        for _flag, _val in (('--instructions-file', args.instructions_file),
                            ('--instructions-draft-path', args.instructions_draft_path),
                            ('--instructions-template', args.instructions_template)):
            if _val is not None and not _is_bound_path(_val):
                _fail('record-dispatch', f'{_flag} {_val!r} is not a non-empty absolute '
                                         f'path free of newline/carriage-return bytes')
        # The attempt carries two draft-path facts that MUST name the same file: the
        # `--draft-file` whose bytes became `attempt['digest']` (the identity eligibility
        # binds to) and the `--instructions-draft-path` the regeneration reads the title
        # from. Left uncompared, a dispatch naming draft Y for identity and draft X for
        # the instructions regenerates cleanly, establishes steering, and grants the
        # coverage-backed clean ground for Y on the strength of an audit whose
        # instructions pointed at X — the fail-open shape the rest of this record closes.
        # Compare RESOLVED paths so a relative-vs-absolute or symlinked spelling of the
        # same file is not refused as a mismatch.
        try:
            _identity_draft = Path(args.draft_file).resolve()
            _instr_draft = Path(args.instructions_draft_path).resolve()
        except OSError as exc:
            _fail('record-dispatch', f'could not resolve the draft paths to compare '
                                     f'them: {exc}')
        if _identity_draft != _instr_draft:
            _fail('record-dispatch',
                  f'--instructions-draft-path {args.instructions_draft_path!r} names a '
                  f'different file than --draft-file {args.draft_file!r} '
                  '(instructions-draft-mismatch): the instructions must be generated '
                  'from the same draft whose bytes this round binds identity to')
        try:
            instructions_digest = hash_bytes(Path(args.instructions_file).read_bytes())
        except OSError as exc:
            _fail('record-dispatch', f'could not read the dispatch-instruction file '
                                     f'{args.instructions_file}: {exc}')
        except _DigestError as exc:
            _fail('record-dispatch', str(exc))
        attempt['instructions'] = {
            'digest': instructions_digest,
            'instructions_path': args.instructions_file,
            'draft_path': args.instructions_draft_path,
            'template_path': args.instructions_template,
            # issue #793 — the scope file's path AND content digest join the CLOSED
            # recorded tuple. Both, not just the path: the path alone would let the file's
            # bytes change after dispatch and still regenerate "cleanly", and the digest
            # alone would leave the return-time regeneration with nothing to read. Frozen
            # here, the return-time regeneration reproduces byte-identically from the
            # recorded tuple, so a scoped round establishes steering on the same terms a
            # cold one does — and a post-dispatch ledger mutation (a resolution, reopen or
            # invalidation) cannot move it, because nothing here reads the live ledger.
            # `None` on a discovery round, so every pre-#793 recorded tuple regenerates
            # unchanged.
            'scope_path': args.scope_file or None,
            'scope_digest': (_scope_digest if args.kind == 'targeted' else None),
        }
        # OBSERVE at dispatch whether the bytes on disk are what the generator emits
        # from these recorded inputs, and RECORD the answer. This is deliberately an
        # observation, never a refusal, and the PR-#718 review round is why.
        #
        # The problem it solves: the only comparison used to happen at record-return,
        # where any divergence surfaces as `instructions-object-id-mismatch` and is
        # reported to the user as STEERING. A host or write tool that alters the bytes on
        # the way to disk (CRLF translation, a trailing-newline normalization), or a
        # recorded input whose PATH SPELLING differs from the one the generator was given
        # (the rendered bytes embed `{INSTRUCTIONS_PATH}`/`{DRAFT_PATH}`/`{TEMPLATE_PATH}`
        # verbatim, and the draft-path cross-check above compares RESOLVED paths, so an
        # equivalent-but-differently-spelled path passes it and still renders different
        # bytes), then makes every round on that host report an attack that never
        # happened.
        #
        # Why it must NOT refuse — two independent reasons, both found by review:
        #   1. A genuinely STEERED file (hand-edited after generation) diverges here too,
        #      and the tool cannot tell it apart from a mangled write. A refusal would
        #      hand the orchestrator "re-write it verbatim from the generator stdout",
        #      which OVERWRITES THE EVIDENCE and lets the re-dispatch record a clean
        #      canonical round — laundering the exact integrity attack this mechanism
        #      exists to catch, with nothing persisted about the attempt.
        #   2. `_fail` exits before any state write, so the round never opens. That is a
        #      new hard stop on a legitimate host, against this change's own contract
        #      that filing is never blocked on any arm.
        # Recording instead keeps the durable trail (the divergence is a fact about the
        # round: `record-return` selects the `instructions-noncanonical-at-dispatch`
        # reason from it, which `query-summary` and the Step 4 audit-summary line then
        # render, so the attribution reaches the user and not just a stderr stream) and
        # blocks nothing. It
        # cannot fail open: the return-time regeneration still owns the verdict and still
        # refuses to establish steering on a mismatch.
        #
        # The recorded value is a closed three-token vocabulary, and the message names
        # the divergence WITHOUT asserting which cause produced it — the tool has not
        # established that, and asserting it is what sends an operator to the wrong remedy.
        try:
            _regen = regenerate_instructions_digest(args.slug, attempt['instructions'])
        except _DigestError as exc:
            # Could not run the comparison at all (an unreadable template, an unimportable
            # generator). NOT evidence of a bad write — but not evidence of a good one
            # either, so it is recorded as unverified rather than silently omitted.
            attempt['instructions']['dispatch_regeneration'] = 'unverified'
            print(f'record-dispatch: warning: could not regenerate the dispatch '
                  f'instructions to confirm the written file is canonical ({exc}); '
                  'recorded as dispatch_regeneration=unverified — the return-time '
                  'regeneration owns the verdict', file=sys.stderr)
        else:
            _diverged = _regen != instructions_digest
            attempt['instructions']['dispatch_regeneration'] = (
                'diverged' if _diverged else 'verified')
            if _diverged:
                print(f'record-dispatch: warning: the instruction file at '
                      f'{args.instructions_file} does not match a fresh regeneration from '
                      'the recorded inputs (recorded as dispatch_regeneration=diverged). '
                      'The round is recorded and filing is not blocked, but steering '
                      'cannot be established from it. This tool has NOT established which '
                      'cause produced the divergence; the reachable ones are (a) the bytes '
                      'were altered between the generator and the disk (a line-ending or '
                      'trailing-newline translation by the writing tool), (b) a recorded '
                      '--instructions-file / --instructions-draft-path / '
                      '--instructions-template spelling differs from the string passed to '
                      'dispatch-instructions (an equivalent path renders different bytes), '
                      'or (c) the file was edited after generation. Do NOT overwrite the '
                      'file before the cause is known: on (c) the written bytes are the '
                      'only evidence of the edit.', file=sys.stderr)
    if args.arm == 'embed':
        # Delta 3: the sentinels are generated by the tool at dispatch, not chosen ad
        # hoc by the orchestrator, so the carriage compare is against a recorded value.
        tag = secrets.token_hex(3).upper()
        attempt['sentinel_open'] = f'AUDIT-{tag}-OPEN'
        attempt['sentinel_close'] = f'AUDIT-{tag}-CLOSE'
    rnd = _find_round(doc, args.round)
    if rnd is None:
        expected = (doc['rounds'][-1]['round'] + 1) if doc['rounds'] else args.round
        if doc['rounds'] and args.round != expected:
            _fail('record-dispatch', f'round {args.round} is out of order (the last '
                                     f'recorded round is {doc["rounds"][-1]["round"]}; '
                                     f'the next round is {expected})')
        # A new round cannot open while an earlier one is still open: two concurrently
        # open rounds would let a later verdict close the wrong round's accounting, and
        # every budget/retry counter is per-round.
        if doc['rounds'] and doc['rounds'][-1].get('outcome') is None:
            _fail('record-dispatch',
                  f'round {doc["rounds"][-1]["round"]} is still open; record its return '
                  f'before dispatching round {args.round}')
        # issue #1104: the file-arm staged-write guarantee at DISPATCH — the sibling of
        # `record-revision`'s `file-arm-requires-stdin-digest` refusal (issue #705), enforced
        # by the tool rather than carried by prose a context compaction can evict. Without
        # the record the loss is SILENT by design: `select_round_kind`'s condition 3 has no
        # operand, and a missing operand degrades the selection to `discovery` rather than
        # aborting the run, so every later round pays for a cold whole-draft audit and
        # nothing says why. Refused before any mutation of `doc`, the round stays
        # dispatchable — the caller records the staged write and re-issues the identical call.
        #
        # The predicate is `_reconstruct_dispatch_bytes`, the same reader condition 3 uses:
        # a weaker digest-membership test would admit a recorded pair whose artifact is gone
        # or whose bytes no longer hash to it, satisfying the guard while leaving the
        # selection to fail on the very same run.
        #
        # The FILE-arm scoping is what makes the guarantee safe to require at all: `route_arm`
        # selects `file` only when the canonical write landed, and the degraded arms it and
        # `next_action` route to instead are reached precisely when the run has no trustworthy
        # canonical file to have staged. The fresh-dispatch scoping is structural — the
        # predicate is `_find_round` having answered `None` — because a retry re-dispatches an
        # already-open round whose bytes may legitimately have moved, and refusing it would
        # refuse the re-dispatch the tool itself prescribed.
        #
        # SCOPE, stated so the breadcrumb is not read as more than it is: this establishes
        # recoverability AT DISPATCH. It does not make the artifact durable — a later
        # overwrite or sweep can still strand the record, and condition 3 then answers
        # `dispatch-bytes-unrecoverable` exactly as before.
        if args.arm == 'file' and _reconstruct_dispatch_bytes(doc, digest) is None:
            _fail('record-dispatch',
                  f'the draft bytes this dispatch audits (digest {digest!r}) are not '
                  'recoverable from the run\'s recorded byte history '
                  '(file-arm-requires-staged-write): stage those exact bytes and record the '
                  'staged write for them (stage-draft-write.py stage, then record-staged-write '
                  '--path <the resolved artifact> --digest <that digest>), then re-issue this '
                  'identical record-dispatch call. Without a recorded staged write a later '
                  'round cannot reconstruct these bytes at all, so every scoped-round delta '
                  'silently falls back to a whole-draft audit. Recording it is necessary, '
                  'not sufficient: this check reads the artifact now, so one later '
                  'overwritten or swept still strands the record.')
        # Spend the automatic re-audit budget HERE, where the round actually opens.
        # A new round whose predecessor closed REVISE is the automatic re-audit while the
        # budget is unspent; once it is spent, a further round can only be a user-chosen
        # one (whose ceiling `record-offer` enforces). Deriving this from recorded facts
        # keeps the orchestrator from having to declare which budget a round draws on.
        prev = doc['rounds'][-1] if doc['rounds'] else None
        # issue #792: a round the accepted final-byte offer funded. The flag is CONSUMED
        # here (popped), so it arms exactly the next round the offer paid for and cannot
        # silently mark a later one. `_fail` below exits without saving, so a popped flag
        # on a refused dispatch is never persisted.
        final_byte_pass = bool(doc.pop('final_byte_pending', False))
        # The DERIVED automatic-re-audit spend must not fire for a final-byte pass. That
        # spend is derived from recorded facts — a predecessor whose outcome is REVISE —
        # and the pass's own headline case is a run that converged on self-verified
        # resolutions over exactly such a round. Unguarded, an accepted pass would
        # increment BOTH counters and hand the run a phantom third round the widened
        # funding test then admits with no offer behind it.
        # `targeted_return_unusable` sits BESIDE `outcome`, so without the third clause an
        # unusable targeted REVISE pays for a CONFIRMATION out of the automatic pool,
        # leaving `confirming_rounds_used` at 0 and the boundary election unreachable.
        if (not final_byte_pass
                and prev is not None and prev.get('outcome') == 'REVISE'
                and not _targeted_confirmation_needed(prev)
                and doc.get('automatic_reaudits_used', 0) < _MAX_AUTOMATIC_REAUDITS):
            doc['automatic_reaudits_used'] = doc.get('automatic_reaudits_used', 0) + 1
        # The confirming round spends its own counter. Fund exactly what `next_action`
        # schedules: targeted FILE, or an unusable targeted terminal return of either
        # verdict shape, while a dedicated slot remains. A final-byte pass stays excluded.
        elif (not final_byte_pass
                and prev is not None
                and _targeted_confirmation_needed(prev)
                and doc.get('confirming_rounds_used', 0) < _MAX_CONFIRMING_ROUNDS):
            doc['confirming_rounds_used'] = doc.get('confirming_rounds_used', 0) + 1
        # Round funding: every round past the initial one is funded by the automatic
        # budget spent above, an accepted user-chosen offer (record-offer), or an accepted
        # final-byte offer (record-final-byte-offer --accepted, issue #792). Opening
        # an unfunded round would hand the run re-audits the cap never sees.
        if len(doc['rounds']) >= _funded_rounds(doc):
            _fail('record-dispatch',
                  f'round {args.round} is not funded: the automatic budget is spent '
                  f'and no accepted user-chosen round funds it (record-offer '
                  f'--accepted first)')
        rnd = {'round': args.round, 'attempts': [], 'no_parseable_retry_used': False,
               'unreadable_retry_used': False, 'outcome': None, 'findings_count': None,
               'consumer_dimensions_appended': False, 'embed_markers': [],
               'degraded': False,
               # Post-adjudication payload (issue #548), filled by record-adjudication after
               # the round is accepted. `None` = not yet adjudicated (distinct from an
               # adjudicated-but-unestablished count, which is the literal _UNESTABLISHED).
               'adjudicated_verdict': None, 'must_revise_count': None,
               'advisory_count': None, 'invalid_count': None,
               'unresolved_must_revise': None,
               # issue #792: recorded on the round itself so the coverage and calibration
               # selectors can exclude it, and so the refund at return time knows which
               # rounds the dedicated slot paid for. An ORDINARY round in every other
               # respect — same dispatch vocabulary, same arms, same verdict set.
               'final_byte_pass': final_byte_pass,
               # The canonical digest the pass was funded on, so a refund re-arms the slot only
               # for those bytes. `None` on an ordinary round.
               'final_byte_pass_digest': (doc.get('final_byte_slot_digest')
                                          if final_byte_pass else None),
               # issue #793: the round kind, recorded exactly as the arm is. Every reader of
               # the run's latest completed round branches on this, so it is a per-round
               # fact rather than something re-derived later from inputs that have since
               # moved. A round record written before #793 carries none, and every reader
               # defaults it to `discovery` — the whole-draft treatment those rounds
               # actually had.
               'kind': _checked_kind(args.kind),
               # issue #1103: the reason the kind was selected, recorded per round beside
               # `kind` for exactly the reason `kind` is — a later reader must not
               # re-derive it from inputs (a revision, the byte history) that have since
               # moved, and the census that joins rounds to kinds must be able to say WHY
               # a cold round was cold rather than inferring it from a replay. Validated
               # against the closed vocabulary at the write boundary, the same guard
               # `kind` gets. A round record written before #1103 carries none, and every
               # reader reports its reason as UNESTABLISHED (never a guessed value) — the
               # additive-field-under-the-unchanged-schema-version precedent, so a
               # pre-change state file still loads.
               'kind_reason': _checked_kind_reason(_kind_answer['reason']),
               # The derived scope a targeted round was dispatched under, for the audit
               # trail. `None` on a discovery round.
               # `draft_lines` (issue #1105) is the convex-hull draft-line span over the
               # changed sections, in the two-element ordered-integer shape
               # `spec-context-eval.py`'s `_scope_draft_span` accepts. Frozen here
               # like the rest of the scope, so a post-dispatch ledger mutation cannot move
               # it. `None` (via `.get`) when the span could not be computed (e.g. an
               # all-deletion delta) or on a pre-#1105 recorded round, which keeps the
               # scope-escape proxy at its honest `unestablished`.
               'scope': ({'basis_digest': _kind_answer['basis_digest'],
                          'sections': _kind_answer['sections'],
                          'claim_ids': [c for c, _ in _kind_answer['claims']],
                          'draft_lines': _kind_answer.get('draft_lines')}
                         if args.kind == 'targeted' else None)}
        doc['rounds'].append(rnd)
        # issue #1103 — close the cross-check asymmetry. `_cross_check_kind` refuses a
        # caller that declares `targeted` over a fallen-back `discovery` selection, but
        # silently accepts a caller that declares the cold `discovery` one. Falling back to
        # the cold kind is CORRECT behaviour (refusing it would break every run that
        # legitimately cannot take a scoped round), so this stays a breadcrumb, never a
        # refusal — but the expensive whole-draft path announces itself at the moment it is
        # paid for rather than only in a later census. It fires for every discovery reason
        # EXCEPT the genuine first round (`no-round-dispatched`), so a run's legitimately
        # cold first round is silent while a fall-off is named.
        if (args.kind == 'discovery'
                and _kind_answer['reason'] != _DISCOVERY_FIRST_ROUND_REASON):
            sys.stderr.write(
                f'issue-audit-state.py record-dispatch: round {args.round} opened a '
                f'discovery (whole-draft) round because the tool selected discovery, '
                f'reason {_kind_answer["reason"]!r} (accepted-discovery-fallback) — the '
                f'cheaper targeted round was not eligible; this whole-draft audit is the '
                f'expensive path.\n')
    elif rnd.get('outcome') is not None:
        _fail('record-dispatch', f'round {args.round} is already closed with outcome '
                                 f'{rnd["outcome"]!r}; a dispatch cannot reopen it')
    elif rnd.get('pending') not in ('dispatch-embed-retry', 'dispatch-retry-same-arm',
                                    'dispatch-inline-degraded'):
        # An open round accepts a further dispatch only when a retry is actually
        # pending: an unrequested re-dispatch would append a second attempt whose
        # digest/sentinels silently become the carriage comparand.
        _fail('record-dispatch', f'round {args.round} is open awaiting its return; a '
                                 f're-dispatch was not requested')
    elif args.arm not in _permitted_retry_arms(rnd):
        # The pending action names the arm the retry was routed to; a mismatched arm
        # would silently switch the carriage comparand class mid-round.
        _fail('record-dispatch', f'the pending action {rnd["pending"]} does not permit '
                                 f'a dispatch on the {args.arm} arm')
    # This dispatch consumes any pending retry action: between this dispatch and its
    # record-return, next-action must answer round-open-awaiting-return, never re-issue
    # the already-spent retry (a duplicate dispatch would append a second attempt whose
    # digest/sentinels become the carriage comparand).
    if args.arm == 'embed' and not args.marker:
        # Every embed-arm entry carries its cause marker into the evidence surface; an
        # unmarked embed attempt would lose the entry diagnosis forever.
        _fail('record-dispatch', 'the embed arm requires --marker naming the entry cause')
    rnd['pending'] = None
    rnd['attempts'].append(attempt)
    # A divergence observed on ANY attempt of this round is sticky on the round. Without
    # it the observation is retry-erasable: `steering_state` reads only the LATEST
    # attempt, so a round whose first attempt diverged and whose retry verified would read
    # `established` with the earlier divergence surviving in the JSON and seen by nobody —
    # a narrower version of the same laundering the refusal design was killed for.
    if attempt['instructions'] and \
            attempt['instructions'].get('dispatch_regeneration') == 'diverged':
        rnd['any_dispatch_diverged'] = True
    if args.marker:
        if args.marker not in _EMBED_MARKER_TOKENS:
            _fail('record-dispatch', f'unknown embed marker {args.marker!r}')
        if args.marker not in rnd['embed_markers']:
            rnd['embed_markers'].append(args.marker)
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-dispatch', str(exc))
    out = (f'round={args.round} arm={args.arm} kind={args.kind} digest={digest} '
           f'body_digest={body_digest}')
    if attempt['instructions']:
        out += f' instructions_digest={attempt["instructions"]["digest"]}'
        # Surface the dispatch-time observation on the line the orchestrator reads, not
        # only on a stderr stream a caller may redirect: this is the site that can still
        # fix a mangled write or a mis-spelled recorded input.
        _dreg = attempt['instructions'].get('dispatch_regeneration')
        if _dreg is not None:
            out += f' dispatch_regeneration={_dreg}'
    if attempt['sentinel_open']:
        out += (f' sentinel_open={attempt["sentinel_open"]}'
                f' sentinel_close={attempt["sentinel_close"]}')
    print(out)


def cmd_record_return(args):
    doc = _load_for_mutation('record-return', args.slug, args.nonce)
    _require_named_round('record-return', doc, args)   # issue #795 state-defaulted --round
    rnd = _find_round(doc, args.round)
    if rnd is None:
        _fail('record-return', f'no dispatch recorded for round {args.round}; a verdict '
                               'cannot precede its dispatch')
    if rnd.get('outcome') is not None:
        _fail('record-return', f'round {args.round} already returned outcome '
                               f'{rnd["outcome"]!r}; a duplicate return is illegal')
    attempt = rnd['attempts'][-1]
    arm = attempt['arm']
    carriage_ok, carriage_cause = _carriage_ok(attempt, args)
    verdict = args.verdict
    cls = classify_return(arm, verdict, args.verdict is not None, carriage_ok)

    # issue #1103 — name the carriage cause on stderr, BESIDE the closed stdout contract
    # line (never inside it — that line has whole-line comparands, the #611 precedent this
    # follows), and only when carriage actually DROVE the classification: a parseable,
    # non-DRAFT-UNREADABLE verdict that classified `no-parseable-verdict` because the
    # carriage evidence was absent or mismatched. That predicate excludes the two returns
    # this breadcrumb must NOT claim carriage for — an absent/off-set verdict line (an
    # unparseable auditor return, which fails the `has_verdict_line`/`_VERDICTS` guards
    # first) and a `DRAFT-UNREADABLE` return (which carries no carriage by construction) —
    # so the three causes are distinguishable from each other. The stdout line and the
    # exit code are untouched: this writes only to stderr and changes no control flow.
    if (cls == 'no-parseable-verdict' and verdict in _VERDICTS
            and verdict != 'DRAFT-UNREADABLE' and not carriage_ok):
        # The remedy names the file-arm object id specifically (the spec dispatch
        # path); the embed arm's evidence is the sentinel pair, so its remedy names that.
        # Every caller-supplied value is rendered with `!r` so a newline or control byte
        # in it becomes an escaped literal INSIDE this one line and cannot forge a second
        # breadcrumb line (issue #1103 security row).
        if arm == 'file':
            _remedy = ('re-run record-return supplying --carriage-object-id with the '
                       'object id of the draft the auditor actually audited '
                       '(git hash-object --no-filters <draft>)')
            _supplied = f'--carriage-object-id {args.carriage_object_id!r}'
        else:
            _remedy = ('re-run record-return supplying --carriage-sentinel-open / '
                       '--carriage-sentinel-close quoting the exact sentinel pair the '
                       'dispatch embedded around the draft')
            _supplied = (f'--carriage-sentinel-open {args.carriage_sentinel_open!r} '
                         f'--carriage-sentinel-close {args.carriage_sentinel_close!r}')
        if carriage_cause == _CARRIAGE_ABSENT:
            sys.stderr.write(
                f'issue-audit-state.py record-return: round {rnd["round"]} returned a '
                f'parseable {verdict} verdict but NO carriage evidence, so it was '
                f'classified no-parseable-verdict (carriage-absent) — the verdict is not '
                f'a bad parse, the proof that the auditor read the dispatched bytes is '
                f'missing. Remedy: {_remedy}. Supplied: {_supplied}.\n')
        elif carriage_cause == _CARRIAGE_MISMATCH:
            # `_recorded` (the recorded comparand) is composed only here, on the mismatch
            # arm that actually renders it — the absent arm never references it.
            if arm == 'file':
                _recorded = f'the recorded dispatch digest {attempt["digest"]!r}'
            else:
                _recorded = (f'the recorded sentinels {attempt.get("sentinel_open")!r} / '
                             f'{attempt.get("sentinel_close")!r}')
            sys.stderr.write(
                f'issue-audit-state.py record-return: round {rnd["round"]} returned a '
                f'parseable {verdict} verdict whose carriage evidence DISAGREES with the '
                f'recorded dispatch, so it was classified no-parseable-verdict '
                f'(carriage-mismatch) — the auditor quoted evidence for different bytes '
                f'than this round dispatched. Remedy: {_remedy}. Supplied: {_supplied}; '
                f'expected {_recorded}.\n')

    # `pending` is ONE field holding at most one next action, not a set of mutually-exclusive
    # booleans. Three separate flags let the persisted state hold a genuine contradiction
    # (two pending arms true at once), with correctness resting silently on the read-order of
    # the consumer's if-chain; a single assignment site cannot express that state at all.
    rnd['pending'] = None
    if cls == 'accept-file':
        rnd['outcome'] = 'FILE'
    elif cls == 'accept-revise':
        rnd['outcome'] = 'REVISE'
    elif cls == 'retry-embed':
        if rnd.get('unreadable_retry_used'):
            # Exactly one DRAFT-UNREADABLE re-dispatch per round.
            cls = 'no-parseable-verdict'
        else:
            rnd['unreadable_retry_used'] = True
            rnd['pending'] = 'dispatch-embed-retry'
    if cls == 'no-parseable-verdict':
        # Read the retry flag BEFORE setting it: exactly one no-parseable-verdict retry
        # per round, and only a SECOND such completion routes to the inline degraded arm.
        # Setting and reading it in one branch would make the first completion look like
        # the second and skip the same-arm retry entirely.
        if rnd.get('no_parseable_retry_used'):
            if arm == 'inline':
                # The arm past both defined retries: the round closes verdict-less.
                rnd['outcome'] = 'no-verdict'
                rnd['pending'] = None
            else:
                rnd['pending'] = 'dispatch-inline-degraded'
        else:
            rnd['no_parseable_retry_used'] = True
            rnd['pending'] = 'dispatch-retry-same-arm'
    # issue #792: a final-byte pass that closes WITHOUT honouring the offer refunds the
    # dedicated slot, so the run keeps its safety pass rather than spending it on a
    # degradation. `final_byte_passes` clamps the resulting effective count at 0, pairing with
    # the read-boundary non-negative check on each term.
    if rnd.get('final_byte_pass') and _final_byte_honoured(rnd) is False:
        doc[_FINAL_BYTE_REFUNDS_KEY] = doc.get(_FINAL_BYTE_REFUNDS_KEY, 0) + 1
        # Re-arm the slot only for the bytes THIS pass was funded on. `record-final-byte-offer`
        # carries no round-open guard, so a later offer recorded against revised bytes can have
        # moved the slot on; clearing unconditionally would discard that newer spend and re-offer
        # the pass against bytes already offered. A round that records NO pass digest re-arms
        # unconditionally: the comparand is unavailable, so failing toward the re-arm returns the
        # safety pass the refund just paid for, where failing the other way would bank a refund
        # the run could never spend — a self-contradicting state nothing detects.
        _pass_digest = rnd.get('final_byte_pass_digest')
        _matched = doc.get('final_byte_slot_digest') == _pass_digest
        _rearmed = _pass_digest is None or _matched
        if _rearmed:
            doc['final_byte_slot_digest'] = None
        # ── C: the refund's two materially different outcomes are otherwise both SILENT and
        # mutually indistinguishable to the orchestrator that just closed the round. Reported on
        # stderr, not on the stdout line: that line is a closed contract with whole-line
        # comparands, and this repo's #611 precedent puts an additive diagnostic beside such a
        # line rather than in it.
        if _pass_digest is None:
            # Tested FIRST, ahead of `_matched`: with no pass digest recorded, `_matched` is
            # also True whenever the live slot digest is likewise None, so an `if _matched:`
            # arm ordered ahead of this one would claim the pass's bytes are known in exactly
            # the state where the comparand is absent. The two re-armed branches are NOT the
            # same state, and the message says so: here which bytes the pass covered is
            # exactly what is unknown.
            _fb_note = ('re-armed unconditionally — the pass recorded no digest to compare, so '
                        'the bytes it covered could not be established')
        elif _matched:
            _fb_note = 're-armed for the bytes the pass covered'
        else:
            _fb_note = ('was NOT re-armed — a later offer moved it to other bytes, so the '
                        'refunded headroom applies to those instead')
        sys.stderr.write(
            f'issue-audit-state.py record-return: final-byte-slot-refunded for round '
            f'{rnd["round"]}; the slot {_fb_note}\n')
    # Evidence from a REFUSED completion (failed carriage / no parseable verdict) is
    # never recorded: an unproven findings tally must not leak into the summary via a
    # later clean retry that omits its own count.
    if cls in ('accept-file', 'accept-revise'):
        # issue #709: establish steering-absence on the SAME guard the findings tally
        # uses. A refused completion (failed carriage / no parseable verdict) records
        # nothing, so its round keeps `steering: None` — read as unestablished by
        # `_steering_established`, never as clean.
        st_state, st_reason = steering_state(
            args.slug, attempt, args.instructions_object_id,
            args.extra_dispatch_content)
        # issue #718 laundering guard, folded to the single stored source (issue #709
        # shadow finding): a round on which ANY dispatch attempt diverged from its
        # canonical regeneration can never be `established`, regardless of what the
        # auditor's return quotes on a later clean attempt. Without this fold a
        # diverged-then-corrected round stores `established`, and the REPORT surfaces
        # (this record-return stdout line and the Step 4 audit-summary `steering=` token
        # in summary_fields) would assert `established` while the eligibility/triggers
        # gates — which read `_steering_established`, honoring the round-level sticky flag
        # — correctly withhold. Folding it into the stored record keeps all four consumers
        # (both gates and both report surfaces) in agreement by construction.
        if st_state == 'established' and rnd.get('any_dispatch_diverged'):
            st_state, st_reason = ('not-established',
                                   'instructions-noncanonical-at-dispatch')
        rnd['steering'] = {'state': st_state, 'reason': st_reason}
        # issue #86: require the tally on an accepted return — without it adjudication cannot
        # cross-check it and the summary drops the round from its sum. A refused completion
        # never reaches this block, so it stays exempt.
        if args.findings_count is None:
            _fail('record-return', 'an accepted return records no findings tally; pass '
                                   '--findings-count <n> counting every finding the auditor '
                                   'returned (findings-count-required)')
        if args.findings_count < 0:
            _fail('record-return', f'--findings-count {args.findings_count} is '
                                   'negative; a findings tally cannot be')
        rnd['findings_count'] = args.findings_count
        if args.consumer_dimensions_appended:
            rnd['consumer_dimensions_appended'] = True
        if _round_kind(rnd) == 'targeted':
            _ingest_targeted_verdicts(doc, rnd, args)
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-return', str(exc))
    _st = rnd.get('steering')
    out = (f'classification={cls} outcome={rnd["outcome"] or "pending"} '
           f'steering={_st["state"] if _st else "unestablished"} '
           f'steering_reason={_st["reason"] if _st else "none"}')
    if _round_kind(rnd) == 'targeted' and isinstance(rnd.get('claim_verdicts'), dict):
        _v = rnd['claim_verdicts']
        out += (f' addressed={sum(1 for x in _v.values() if x == "addressed")}'
                f' not_addressed={sum(1 for x in _v.values() if x != "addressed")}')
    print(out)


def _ingest_targeted_verdicts(doc, rnd, args):
    """Fold a `targeted` round's per-claim return into the EXISTING ledger (issue #793).

    The decided seam, and the reason it is a seam at all: a scoped round records **no
    ledger of its own**. Its per-claim return updates the entry each claim names —
    `not-addressed` leaves it unresolved or reopens it, `addressed` changes nothing,
    because resolution stays the drafter's own recorded verification and a re-check is not
    one. Without this, the shipped reconciliation discipline would list every re-checked
    defect on BOTH rounds' ledgers and the aggregate would count it once per listing — so a
    mechanism built to REDUCE rounds would inflate the very count that fires the offer for
    more of them, compounding with each scoped round.

    Fail-closed on every shape the auditor's return can take (issue #793): a claim the
    round dispatched but the return omits, and a claim returned with any value outside the
    closed two-member set, are both recorded `not-addressed`. Only a positively-returned
    `addressed` counts as addressed, and a claim id the round never dispatched is ignored
    rather than allowed to invent an entry.
    """
    dispatched = list((rnd.get('scope') or {}).get('claim_ids') or [])
    # A return that carries NO per-claim block at all is UNUSABLE, not a sweep of
    # not-addressed verdicts. The distinction is load-bearing in two directions: recording
    # every claim not-addressed would REOPEN every entry the drafter had resolved, and
    # recording them addressed would schedule confirmation on nothing. An absent block
    # therefore records the round as unusable and reopens nothing.
    if args.claim_verdicts is None or not args.claim_verdicts.strip():
        rnd['claim_verdicts'] = {}
        rnd['targeted_return_unusable'] = True
        if doc.get('confirming_rounds_used', 0) < _MAX_CONFIRMING_ROUNDS:
            route = 'the next action schedules whole-draft confirmation'
        else:
            route = ('confirmation capacity is exhausted, so the next action proceeds '
                     'to the disclosed boundary election')
        print('record-return: warning: a targeted round returned no per-claim block '
              '(--claim-verdicts absent or empty); the round is recorded UNUSABLE — no '
              f'ledger entry is reopened and {route}',
              file=sys.stderr)
        return
    returned = {}
    for line in args.claim_verdicts.splitlines():
        cid, _, value = line.strip().partition(' ')
        if not cid:
            continue
        value = value.strip()
        # DUPLICATES FAIL CLOSED. A dict assignment is last-wins, so a return saying
        # `1.1 not-addressed` and then `1.1 addressed` recorded ADDRESSED — scheduling the
        # confirming round and converging the run on a claim the auditor had just said was
        # not addressed. Any second mention that disagrees pins the claim to not-addressed.
        if cid in returned and returned[cid] != value:
            returned[cid] = 'not-addressed'
        else:
            returned[cid] = value
    verdicts = {}
    for cid in dispatched:
        value = returned.get(cid)
        verdicts[cid] = 'addressed' if value == 'addressed' else 'not-addressed'
    rnd['claim_verdicts'] = verdicts
    # Apply each `not-addressed` verdict to the entry its claim id names. `addressed`
    # deliberately writes nothing: it is a re-check passing, not a recorded verification.
    #
    # One flat pass, joining on the id `_enumerated_claims` itself minted rather than
    # re-deriving it by splitting the string back apart — the producer's construction is
    # the join key, so the two cannot drift.
    unaddressed = {cid for cid, value in verdicts.items() if value != 'addressed'}
    if unaddressed:
        ordinal = _settling_provenance(doc)
        for r, entry in _all_entries(doc):
            if (f'{r["round"]}.{entry["id"]}' in unaddressed
                    and entry.get('status') == 'resolved'):
                _reopen_entry(entry, ordinal)


def cmd_record_adjudication(args):
    """Record the post-adjudication actionability payload for a completed round (issue #548).

    Round acceptance and carriage validation remain record-return's completion boundary;
    this call records the orchestrator's reconciled judgment (the per-class counts and the
    unresolved-must-revise count) AFTER that boundary, before any T1/convergence/summary
    query. The raw auditor verdict stays recorded as provenance; a raw token never
    substitutes for adjudication, so the state owner accepts this payload only when the
    adjudicated verdict and the unresolved-must-revise count agree — checked when that count
    is established. A `FILE` verdict asserts convergence-worthiness, so it may NOT pair with
    an `unestablished` count (that is precisely a not-established state); a `REVISE` count may
    be `unestablished` (a verified finding may exist though the tally was not established), and
    that is the only verdict the `unestablished` count pairs with.
    """
    doc = _load_for_mutation('record-adjudication', args.slug, args.nonce)
    _require_named_round('record-adjudication', doc, args)   # issue #795 state-defaulted --round
    rnd = _find_round(doc, args.round)
    if rnd is None:
        _fail('record-adjudication', f'no round {args.round} recorded; an adjudication '
                                     'cannot precede its dispatch and return')
    # Write-once (issue #603 AC9), the treatment record-return, record-draft-binding,
    # record-creation-epoch and record-creation-attestation already have. Before this
    # guard a second call silently overwrote the round's payload, so a mis-keyed
    # adjudication could be papered over with no record that it happened — and the
    # post-close channels below could be bypassed entirely.
    # A FILE adjudication supersedes prior findings run-wide, so recording one BEHIND a
    # later completed round would retire findings raised AFTER it — and because the latest
    # round would still be REVISE, `_convergence_basis` would report the resulting clean
    # answer as `resolution`, attributing it to post-close settling that never happened.
    _latest = last_completed(doc)
    if (args.verdict == 'FILE' and _latest is not None
            and args.round < _latest['round']):
        _fail('record-adjudication',
              f'round {args.round} precedes the latest completed round '
              f'{_latest["round"]} (adjudication-out-of-order); a FILE adjudication '
              f'supersedes prior findings and cannot be recorded behind a later round')
    if rnd.get('adjudicated_verdict') is not None:
        _fail('record-adjudication',
              f'round {args.round} is already adjudicated '
              f'(adjudication-already-recorded); a round\'s adjudication is written '
              f'once — the post-close channels for its effective count are '
              f'record-resolution, record-reopen and record-invalidate')
    if rnd.get('outcome') not in ('FILE', 'REVISE'):
        # Only an accepted FILE/REVISE round carries findings to adjudicate — a no-verdict
        # or still-open round has none.
        _fail('record-adjudication', f'round {args.round} is not an accepted, completed '
                                     f'round (outcome {rnd.get("outcome")!r}); only a '
                                     f'FILE/REVISE round carries findings to adjudicate')
    for name, val in (('--must-revise', args.must_revise),
                      ('--advisory', args.advisory), ('--invalid', args.invalid)):
        if val < 0:
            _fail('record-adjudication', f'{name} {val} is negative; an actionability '
                                         'count cannot be')
    raw = args.unresolved_must_revise
    if raw == _UNESTABLISHED:
        unresolved = _UNESTABLISHED
        # A FILE verdict asserts convergence-worthiness, which an unknown unresolved count
        # cannot support: FILE means "zero unresolved must-revise findings", and an
        # unestablished count is precisely a not-established state, not a zero. Reject the
        # pairing so a self-inconsistent `FILE + unestablished` record can never reach the
        # summary/consumers. REVISE + unestablished is the only legal unestablished pairing.
        if args.verdict == 'FILE':
            _fail('record-adjudication', 'adjudicated verdict FILE cannot pair with an '
                                         f'{_UNESTABLISHED!r} unresolved must-revise count: '
                                         'a FILE verdict requires zero unresolved findings, '
                                         'and an unestablished count is not a zero')
    else:
        try:
            unresolved = int(raw)
        except ValueError:
            _fail('record-adjudication', f'--unresolved-must-revise {raw!r} is neither a '
                                         f'non-negative integer nor the literal '
                                         f'{_UNESTABLISHED!r}')
        if unresolved < 0:
            _fail('record-adjudication', f'--unresolved-must-revise {unresolved} is '
                                         f'negative; unknown is the literal '
                                         f'{_UNESTABLISHED!r}, never a negative count')
    # Agreement — only decidable when the count is a settled integer. An unestablished count
    # names an unknown, so it agrees with neither verdict and is not rejected here (the
    # convergence/T1 queries treat it as not-established, never as zero).
    if isinstance(unresolved, int):
        if args.verdict == 'FILE' and unresolved != 0:
            _fail('record-adjudication', f'adjudicated verdict FILE disagrees with '
                                         f'unresolved must-revise count {unresolved}: a '
                                         f'FILE verdict requires zero unresolved must-revise '
                                         f'findings')
        if args.verdict == 'REVISE' and unresolved < 1:
            _fail('record-adjudication', f'adjudicated verdict REVISE disagrees with '
                                         f'unresolved must-revise count {unresolved}: a '
                                         f'REVISE verdict requires at least one verified '
                                         f'unresolved must-revise finding')
        # Unresolved must-revise findings are a subset of the round's must-revise findings, so
        # the unresolved count can never exceed the total. A record that violates this is
        # self-inconsistent; reject it rather than let a nonsensical tally reach the summary.
        if unresolved > args.must_revise:
            _fail('record-adjudication', f'unresolved must-revise count {unresolved} exceeds '
                                         f'the must-revise total {args.must_revise}: unresolved '
                                         f'findings are a subset of must-revise findings')
    # ── Findings-count agreement (issue #86): the recorded tally must equal
    # must-revise+advisory+invalid — refuse a mismatch before any write. No tally (a pre-#86
    # round; only a FILE/REVISE round reaches here) → a stderr-only tally-unrecorded note.
    _tally = rnd.get('findings_count')
    if _tally is None:
        sys.stderr.write(
            f'issue-audit-state.py record-adjudication: round {args.round} carries no '
            f'recorded findings tally (tally-unrecorded); adjudicating without the '
            f'findings-count agreement check\n')
    else:
        _class_total = args.must_revise + args.advisory + args.invalid
        if _tally != _class_total:
            _fail('record-adjudication',
                  f'recorded findings tally {_tally} disagrees with the adjudicated class '
                  f'total {_class_total} (must_revise {args.must_revise} + advisory '
                  f'{args.advisory} + invalid {args.invalid}) (findings-count-mismatch); '
                  f'every returned finding lands in exactly one class')
    # ── The per-finding ledger (issue #603 AC1/AC20; #200 file transport) ─────────
    # A REVISE adjudication with a SETTLED count records one ledger entry per must-revise
    # finding. The ledger reaches the tool from a file the skill authors with its file-write
    # tool (issue #200), so a worktree-isolated session has one worktree-safe ledger location
    # and no shell heredoc. Recording is not skippable on that shape — a missing --ledger-file
    # is a refusal — which is the property that makes the run-wide aggregate and the
    # reconciliation discipline total over post-change rounds. A FILE verdict and a
    # `REVISE … unestablished` adjudication take no flag and record no ledger: their call
    # shapes stay byte-compatible with the pre-#603 CLI.
    ledger_shape = args.verdict == 'REVISE' and isinstance(unresolved, int)
    ledger = None
    if getattr(args, 'ledger_file', None) is not None:
        if not ledger_shape:
            _fail('record-adjudication',
                  '--ledger-file is only accepted on a REVISE adjudication with a '
                  'settled unresolved count (ledger-not-applicable); a FILE verdict and '
                  f'a REVISE + {_UNESTABLISHED!r} adjudication record no ledger')
        ledger = _ingest_ledger(args, args.must_revise, unresolved)
    elif ledger_shape:
        _fail('record-adjudication',
              f'a REVISE adjudication with a settled unresolved count requires '
              f'--ledger-file naming {args.must_revise} status-prefixed finding '
              f'summaries (ledger-required); the ledger is the durable identity record '
              f'the post-close resolution channels name entries from')
    # ── Per-finding advisory/invalid records (issue #743) ──────────────────────────
    # The deterministic recording floor: a non-zero --advisory/--invalid count REQUIRES a
    # matching per-finding records file (like --ledger-file's ledger-required floor), so the
    # floor is total over post-change rounds. A zero count with no file records nothing,
    # keeping the pre-#743 call shape byte-compatible for a round with no advisory/invalid
    # grade. A records file supplied against a zero count is refused by the count arm inside
    # the ingest helper. Both are resolved BEFORE any state write, so a refused call leaves
    # the round still adjudicable.
    adv_records = None
    if getattr(args, 'advisory_records_file', None) is not None:
        adv_records = _ingest_adjudication_records('advisory', args.advisory_records_file,
                                                   args.advisory)
    elif args.advisory > 0:
        _fail('record-adjudication',
              f'--advisory {args.advisory} requires --advisory-records-file supplying '
              f'{args.advisory} per-finding record(s) (advisory-records-required); every '
              f'advisory grade carries a durable per-finding record')
    inv_records = None
    if getattr(args, 'invalid_records_file', None) is not None:
        inv_records = _ingest_adjudication_records('invalid', args.invalid_records_file,
                                                   args.invalid)
    elif args.invalid > 0:
        _fail('record-adjudication',
              f'--invalid {args.invalid} requires --invalid-records-file supplying '
              f'{args.invalid} per-finding record(s) (invalid-records-required); every '
              f'invalid grade carries a durable per-finding record')
    rnd['adjudicated_verdict'] = args.verdict
    rnd['must_revise_count'] = args.must_revise
    rnd['advisory_count'] = args.advisory
    rnd['invalid_count'] = args.invalid
    rnd['unresolved_must_revise'] = unresolved
    if ledger is not None:
        rnd['findings'] = ledger
    # issue #743: the durable per-finding records, and the render observation seeded to its
    # honest default. The run reports the Step-4 pre-approval rendering via
    # record-adjudication-render; until it does, the summary and calibration surfaces read
    # `unreported` rather than letting an unrendered grade pass silently.
    if adv_records is not None:
        rnd['advisory_records'] = adv_records
    if inv_records is not None:
        rnd['invalid_records'] = inv_records
    if adv_records or inv_records:
        rnd['adjudication_render'] = 'unreported'
    # ── FILE supersession (issue #603 AC21) ───────────────────────────────────────
    # An auditor-accepted clean round is the strongest terminal, exactly as before this
    # change: recording a FILE adjudication marks every PRIOR unresolved entry
    # `superseded`, naming this round as the provenance. That preserves the pre-#603
    # latest-round-wins convergence semantics now that the count is run-wide — without it
    # an earlier round's stale bookkeeping would hold a clean re-audit hostage.
    superseded = 0
    if args.verdict == 'FILE':
        for _, entry in _all_entries(doc):
            if entry.get('status') == 'unresolved':
                # Clear-then-set, like every other status-change writer. Today this is a
                # no-op — the sweep filters on `unresolved`, whose legal settling set is
                # empty — but `_clear_settling`'s docstring claims a sufficiency that only
                # binds channels which CALL it, and this sweep is the one status-change
                # writer that did not. Widen the filter to retire `resolved` entries, or
                # give `unresolved` a legal settling key, and the sweep would carry a
                # `resolution_ordinal` onto a `superseded` entry — which the read boundary
                # then refuses on a file the tool itself just wrote, with every post-close
                # channel already refusing superseded entries, so nothing could repair it.
                _clear_settling(entry)
                entry['status'] = 'superseded'
                entry['supersession_round'] = args.round
                superseded += 1
    _save_or_fail('record-adjudication', doc, args.slug)
    print(f'adjudicated={args.verdict} unresolved={unresolved} '
          f'must_revise={args.must_revise} advisory={args.advisory} '
          f'invalid={args.invalid} superseded={superseded}')


def _read_stdin_lines(args, command, what, token):
    """Decode a quoted-heredoc line payload from the hoisted stdin buffer, or fail closed
    (issue #708). The raw byte read is hoisted into main() above the section (issue #1040)
    and consumed here via `_stdin_bytes_or_fail`, which reproduces the closed-fd and
    read-error breadcrumbs verbatim; the undecodable and empty arms stay here.

    ONE implementation of the fail-closed decode the line-oriented stdin transports share.
    Callers supply their own `command` (for the breadcrumb prefix), the human `what`
    they are reading, and the `token` their triage vocabulary uses, so every named
    breadcrumb stays exactly what it was when each caller inlined this block.

    The transport is deliberately line-oriented text, not a structured payload: the
    skill's fence pipes the lines through a QUOTED-delimiter heredoc, so the shell never
    expands the `$(...)`, backticks, and quotes that auditor-derived text routinely
    contains.

    Reading BYTES and decoding explicitly (rather than reading the text wrapper) is
    load-bearing: decoding INSIDE the read `try` would let a UnicodeDecodeError (a
    ValueError, not an OSError) escape as a raw traceback on routine input — text lifted
    from a terminal transcript carrying a mangled smart quote or a truncated multibyte
    char — breaking the mutation contract's named-breadcrumb half and leaving the skill's
    stderr triage nothing to match.

    Returns the non-blank lines. Never returns on any degraded shape.
    """
    data = _stdin_bytes_or_fail(args, command, f'the {what}')
    try:
        raw = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        _fail(command, f'the {what} is not valid UTF-8 text ({token}-undecodable): {exc}; '
                       f'reword the text in plain text and re-issue the call')
    if not raw.strip():
        _fail(command, f'--{token}-stdin was given but no {what} lines were received on '
                       f'stdin ({token}-empty)')
    return [ln for ln in raw.split('\n') if ln.strip()]


def _read_ledger_file_lines(path):
    """Read the finding ledger's non-blank lines from `--ledger-file`, or fail closed
    (issue #200).

    The ledger reaches record-adjudication from a file the skill authors with its
    file-write tool, giving a worktree-isolated session one worktree-safe ledger location
    and no shell heredoc. The read/decode arms mirror `_ingest_adjudication_records`
    (read bytes → OSError → `ledger-unreadable`; decode utf-8 → UnicodeDecodeError →
    `ledger-undecodable`); the empty arm and the non-blank line filtering match the stdin
    transport this replaced, so the same breadcrumbs and line rules a caller saw before
    still bind. Reading BYTES then decoding explicitly (rather than reading text) keeps a
    UnicodeDecodeError from escaping as a raw traceback on routine input — text lifted from
    a terminal transcript carrying a mangled smart quote or a truncated multibyte char.
    """
    try:
        raw_bytes = Path(path).read_bytes()
    except OSError as exc:
        _fail('record-adjudication',
              f'could not read the finding ledger file {path!r} (ledger-unreadable): {exc}')
    try:
        raw = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        _fail('record-adjudication',
              f'the finding ledger file is not valid UTF-8 text (ledger-undecodable): {exc}; '
              f'rewrite the ledger file as UTF-8 and re-issue the call')
    if not raw.strip():
        _fail('record-adjudication',
              f'--ledger-file {path!r} carries no finding ledger lines (ledger-empty)')
    return [ln for ln in raw.split('\n') if ln.strip()]


def _ingest_ledger(args, must_revise, unresolved):
    """Read `--ledger-file` and build the round's ledger, or fail closed.

    The transport is deliberately line-oriented text, not a structured payload: the skill
    authors the ledger lines to a file with its file-write tool (issue #200), so the shell
    never touches the `$(…)`, backticks, and quotes that auditor-derived summaries routinely
    contain, and a worktree-isolated session has one worktree-safe ledger location. A line
    byte-equal to nothing special truncates nothing here (the file transport has no
    delimiter to collide with); a miscount trips the `ledger-line-count` refusal below, and
    the decided recovery for a count or vocabulary refusal is the same — reword the summary
    and re-issue the call.

    The read/decode fail-closed arms live in `_read_ledger_file_lines`
    (`ledger-unreadable`/`ledger-undecodable`/`ledger-empty`), mirroring
    `_ingest_adjudication_records`; the line-count and vocabulary checks below are this
    command's own.
    """
    lines = _read_ledger_file_lines(args.ledger_file)
    if len(lines) != must_revise:
        _fail('record-adjudication',
              f'the ledger carries {len(lines)} finding summaries but the adjudication '
              f'names {must_revise} must-revise findings (ledger-line-count); one '
              f'status-prefixed line per must-revise finding is required')
    ledger = []
    for idx, line in enumerate(lines, start=1):
        status = None
        raw_draft_line = None
        for candidate in _LEDGER_PREFIXES:
            prefix = f'{candidate}: '
            if line.startswith(prefix):
                status, summary = candidate, line[len(prefix):]
                break
            # issue #889: a line may carry the draft line the auditor quoted as the
            # line it attacks, as an OPTIONAL `<status>@<n>: <summary>` coordinate. The
            # plain prefix is checked first, so a summary that itself begins `@n: ` is
            # never mis-captured. The coordinate is draft-space (a line number in the
            # draft), never a repository path:line. The ACCEPTED SET is the unpadded
            # decimal form only: the digits are captured as TEXT here so a zero-padded
            # `@007` can be refused loudly below rather than silently normalized to `7`
            # — a silent normalization accepts a coordinate the author did not write
            # and leaves no breadcrumb saying so.
            m = re.match(re.escape(candidate) + r'@(\d+): ', line)
            if m is not None:
                status, raw_draft_line = candidate, m.group(1)
                summary = line[m.end():]
                break
        if status is None:
            _fail('record-adjudication',
                  f'ledger line {idx} carries no status prefix (ledger-status-prefix); '
                  f'each line must begin with '
                  + ' or '.join(repr(f'{c}: ') for c in _LEDGER_PREFIXES)
                  + ' (an optional draft-line coordinate may follow the status as '
                    '`@<n>`)')
        summary = summary.strip()
        if not summary:
            _fail('record-adjudication',
                  f'ledger line {idx} carries an empty finding summary '
                  f'(ledger-empty-summary); a summary is the entry\'s identity anchor')
        splitter = _record_splitting_char(summary)
        if splitter is not None:
            _fail('record-adjudication',
                  f'ledger line {idx} contains the record-splitting character '
                  f'{splitter!r} (ledger-summary-control-char); a summary is one line of '
                  f'identity data — reword it without the embedded newline or carriage '
                  f'return and re-issue the call')
        forged = _forged_protocol_token(summary)
        if forged is not None:
            _fail('record-adjudication',
                  f'ledger line {idx} contains the protocol token {forged + "="!r} '
                  f'(ledger-protocol-vocabulary); ledger text is identity data, never '
                  f'protocol — reword the summary without the <field>= form and '
                  f're-issue the call')
        entry = {'id': idx, 'summary': summary, 'status': status,
                 'ingested_status': status}
        if raw_draft_line is not None:
            # The accepted set is the UNPADDED decimal form of a 1-based line number.
            # `@0` is refused as no line number; `@007` is refused as padded rather
            # than normalized to `7`.
            if len(raw_draft_line) > 1 and raw_draft_line.startswith('0'):
                _fail('record-adjudication',
                      f'ledger line {idx} carries a zero-padded draft-line coordinate '
                      f'@{raw_draft_line} (ledger-draft-line-format); write the 1-based '
                      f'draft line unpadded and re-issue the call')
            draft_line = int(raw_draft_line)
            if draft_line < 1:
                _fail('record-adjudication',
                      f'ledger line {idx} carries a non-positive draft-line coordinate '
                      f'@{draft_line} (ledger-draft-line-range); a quoted draft line is '
                      f'a 1-based line number in the draft')
            entry['quoted_draft_line'] = draft_line
        if status == 'resolved':
            entry['ingest_provenance'] = _LEDGER_INGESTED_RESOLVED
        ledger.append(entry)
    ingested_unresolved = sum(1 for e in ledger if e['status'] == 'unresolved')
    if ingested_unresolved != unresolved:
        _fail('record-adjudication',
              f'the ledger carries {ingested_unresolved} unresolved entries but the '
              f'adjudication names {unresolved} unresolved must-revise findings '
              f'(ledger-unresolved-count)')
    return ledger


def _ingest_adjudication_records(cls, path, count):
    """Read a class's per-finding advisory/invalid records from a JSON file, or fail closed.

    The deterministic recording floor (issue #743): every advisory and invalid grade a run
    records carries a durable per-finding record, so a self-grade is REVIEWABLE rather than
    an integer no reader can re-examine. Deliberately a FILE (issue #200 moved the ledger to
    a file too): the skill authors the JSON with the Write tool (no shell quoting) exactly
    as it authors the `--ledger-file` and `--reflection-file` payloads, giving a
    worktree-isolated session one worktree-safe records location. Each record's
    orchestrator-authored fields (`summary`, `rationale`, `impact_class`,
    optional `evidence`) follow the ledger refusal discipline; the auditor's returned finding
    block is stored VERBATIM under the evidence cap (the record-finding-evidence discipline) and neutralized at the
    print boundary, never reworded to satisfy a refusal — it is a comparand to preserve.

    `cls` is the class token (`advisory`/`invalid`), used as the breadcrumb prefix so every
    named refusal states which class detonated. Returns the list of records (each an object
    the read boundary re-validates), or never returns on any degraded shape.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        _fail('record-adjudication',
              f'could not read the {cls} records file {path!r} ({cls}-records-unreadable): '
              f'{exc}')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        _fail('record-adjudication',
              f'the {cls} records file is not valid UTF-8 ({cls}-records-undecodable): {exc}')
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail('record-adjudication',
              f'the {cls} records file is not valid JSON ({cls}-records-not-json): {exc}')
    if not isinstance(parsed, list):
        _fail('record-adjudication',
              f'the {cls} records file is not a JSON array ({cls}-records-not-list); one '
              f'object per {cls} finding is required')
    if len(parsed) != count:
        # BOTH directions in one arm: --<cls> N above the supplied record count and the
        # converse over-supply are the same self-inconsistent shape — the count and the
        # durable payload must agree exactly, or the floor is not total over the class.
        _fail('record-adjudication',
              f'--{cls} names {count} finding(s) but the {cls} records file supplies '
              f'{len(parsed)} ({cls}-records-count); the per-class count and the per-finding '
              f'records must agree exactly (neither over- nor under-supplied)')
    records = []
    for idx, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            _fail('record-adjudication',
                  f'{cls} record {idx} is not a JSON object ({cls}-record-not-object)')
        # summary and rationale: orchestrator-authored one-line identity data.
        entry = {'id': idx}
        for field in ('summary', 'rationale'):
            val = item.get(field)
            if not isinstance(val, str) or not val.strip():
                _fail('record-adjudication',
                      f'{cls} record {idx} has an empty or non-string {field} '
                      f'({cls}-empty-{field}); it is one line of identity data')
            val = val.strip()
            splitter = _record_splitting_char(val)
            if splitter is not None:
                _fail('record-adjudication',
                      f'{cls} record {idx} {field} contains the record-splitting character '
                      f'{splitter!r} ({cls}-{field}-control-char); reword it without the '
                      f'embedded newline or carriage return and re-issue the call')
            forged = _forged_protocol_token(val)
            if forged is not None:
                _fail('record-adjudication',
                      f'{cls} record {idx} {field} contains the protocol token '
                      f'{forged + "="!r} ({cls}-{field}-protocol-vocabulary); the field is '
                      f'identity data, never protocol — reword it without the <field>= form')
            entry[field] = val
        # impact_class: a value from the closed set, with clearly-optional as the complement.
        tag = item.get('impact_class')
        if tag not in _IMPACT_CLASSES:
            _fail('record-adjudication',
                  f'{cls} record {idx} names an impact_class outside the canonical set '
                  f'{_IMPACT_CLASSES} ({cls}-impact-class): {tag!r}')
        entry['impact_class'] = tag
        # evidence: OPTIONAL one-line orchestrator text. Absent/empty is legal — that is
        # precisely the under-evidenced state the calibration layer surfaces; when PRESENT it
        # follows the same one-line refusal discipline as summary/rationale.
        ev = item.get('evidence')
        if ev is not None:
            if not isinstance(ev, str):
                _fail('record-adjudication',
                      f'{cls} record {idx} evidence is not a string ({cls}-evidence-type)')
            ev = ev.strip()
            if ev:
                splitter = _record_splitting_char(ev)
                if splitter is not None:
                    _fail('record-adjudication',
                          f'{cls} record {idx} evidence contains the record-splitting '
                          f'character {splitter!r} ({cls}-evidence-control-char)')
                forged = _forged_protocol_token(ev)
                if forged is not None:
                    _fail('record-adjudication',
                          f'{cls} record {idx} evidence contains the protocol token '
                          f'{forged + "="!r} ({cls}-evidence-protocol-vocabulary)')
                entry['evidence'] = ev
        # auditor_block: the auditor's complete returned finding block, byte-preserved (the
        # comparand's extent is the auditor's, not a grader-selected excerpt). Stored VERBATIM
        # under the evidence cap and neutralized at print — never reworded to satisfy a refusal.
        block = item.get('auditor_block')
        if not isinstance(block, str) or not block.strip():
            _fail('record-adjudication',
                  f'{cls} record {idx} has an empty or non-string auditor_block '
                  f'({cls}-empty-auditor-block); the auditor-verbatim finding block is the '
                  f'comparand every later review compares the grade against')
        entry['auditor_block'] = _bound_evidence(block)
        records.append(entry)
    return records


def cmd_record_adjudication_render(args):
    """Record the run's observation that it rendered the round's advisory/invalid records to
    the user before the approval election (issue #743, the `--write-landed` pattern).

    The tool cannot observe chat, so this is a REPORTED observation, not a fact the tool
    checks: `--landed yes` records `reported`, `--landed no` records `unreported`. An
    unreported rendering is surfaced (never silently passed) through the calibration trigger
    and the summary. Idempotent: re-reporting the same value is a legal replay.
    """
    doc = _load_for_mutation('record-adjudication-render', args.slug, args.nonce)
    _require_named_round('record-adjudication-render', doc, args)   # issue #795 state-defaulted --round
    rnd = _find_round(doc, args.round)
    if rnd is None:
        _fail('record-adjudication-render', f'no round {args.round} recorded (no-such-round)')
    if rnd.get('adjudicated_verdict') is None:
        _fail('record-adjudication-render', f'round {args.round} is not adjudicated '
                                            f'(not-adjudicated); the render is reported after '
                                            f'adjudication records the findings to render')
    if not (rnd.get('advisory_records') or rnd.get('invalid_records')):
        _fail('record-adjudication-render', f'round {args.round} recorded no advisory or '
                                            f'invalid records to render (no-records)')
    rnd['adjudication_render'] = 'reported' if args.landed == 'yes' else 'unreported'
    _save_or_fail('record-adjudication-render', doc, args.slug)
    print(f'adjudication_render={rnd["adjudication_render"]} round={args.round}')


def cmd_record_coverage(args):
    """Record a round's per-dimension coverage outcomes (issue #708).

    Recorded on a completed (FILE/REVISE) round — the call sequence places it after
    adjudication, but only round COMPLETION is enforced here: one outcome per required audit
    dimension from the closed set `_COVERAGE_OUTCOMES`, each labeled with its stable
    renderer key. The auditor self-reports the outcomes and anchors as UNTRUSTED identity
    data (never instructions to obey); this call enforces the TEXT-ONLY floor on the anchor
    alone, and DOWNGRADES a floor-failing `exercised`/`valid-N/A` to `unestablished` (unknown
    is not zero) rather than rejecting the whole call — the data-dependent checks
    (byte-identity, cited-line existence) are the orchestrator's and already ran before this
    call. Write-once per round, like adjudication. `--render` records whether the auditor
    rendered every dimension (`full`) or a divergence narrowed the set (`degraded`).

    **Stated residual (the honesty scope this feature claims, and no more).** Both
    `--expected-keys` and `--render` are ORCHESTRATOR-SUPPLIED: the state owner holds no
    template and cannot re-derive the enumeration, so it enforces totality against the
    keyset it is GIVEN, not against the renderer's output. An orchestrator that passes only
    the keys the auditor returned makes totality vacuous. That seam is inherent to the
    tool/orchestrator split — what the tool can do, and does, is refuse an unenumerated key,
    synthesize every missing one as `unestablished`, and PERSIST the supplied keyset
    (`coverage_expected`) so the claim is auditable after the fact. `coverage-backed`
    therefore means evidence of the required shape was present and survived the floor and
    the orchestrator's adjudication — never certified scrutiny.
    """
    doc = _load_for_mutation('record-coverage', args.slug, args.nonce)
    _require_named_round('record-coverage', doc, args)   # issue #795 state-defaulted --round
    rnd = _find_round(doc, args.round)
    if rnd is None:
        _fail('record-coverage', f'no round {args.round} recorded; coverage cannot precede '
                                 'its dispatch and return')
    if rnd.get('outcome') not in ('FILE', 'REVISE'):
        _fail('record-coverage', f'round {args.round} is not an accepted, completed round '
                                 f'(outcome {rnd.get("outcome")!r}); only a FILE/REVISE '
                                 f'round carries dimensions to cover')
    if 'coverage' in rnd:
        _fail('record-coverage', f'round {args.round} already records coverage '
                                 f'(coverage-already-recorded); a round\'s coverage is '
                                 f'written once')
    expected = [k.strip() for k in args.expected_keys.split(',') if k.strip()]
    if not expected:
        _fail('record-coverage', '--expected-keys named no dimension keys '
                                 '(coverage-expected-empty); pass the enumerated keyset '
                                 'from `render-audit-prompt.py enumerate-dimensions`')
    if len(set(expected)) != len(expected):
        _fail('record-coverage', '--expected-keys repeats a dimension key '
                                 '(coverage-expected-duplicate); the enumeration is keyed '
                                 'and its keys are unique by construction')
    coverage = _ingest_coverage(args, expected)
    rnd['coverage'] = coverage
    # Persist the enumeration totality was checked against. The state owner cannot
    # re-derive it (it holds no template), so `--expected-keys` is an orchestrator-supplied
    # operand — recording it makes the claim AUDITABLE after the fact instead of leaving
    # only its effect. The residual is stated in the docstring and the growth artifact.
    rnd['coverage_expected'] = expected
    rnd['coverage_render'] = args.render
    _save_or_fail('record-coverage', doc, args.slug)
    # The echo carries only fields drawn from the tool's own printed vocabulary
    # (`_PROTOCOL_TOKENS`) — the per-outcome breakdown is read back through
    # `query-coverage`, so no per-outcome `<field>=` token (which would forge a protocol
    # word and broaden the anchor-refusal vocabulary) is introduced here. `outcome=` names
    # the outcomes recorded, comma-joined, as a value.
    outcomes = ','.join(e['outcome'] for e in coverage) or 'none'
    # A REVISE round's coverage is recorded but can never back the run (`_coverage_round`
    # selects the final accepted CLEAN round), so the echo says so rather than reading as
    # an unqualified success receipt for work no derivation will ever consume.
    backs = 'yes' if rnd.get('outcome') == 'FILE' else 'no'
    print(f'coverage_render={args.render} count={len(coverage)} outcome={outcomes} '
          f'backs_run={backs}')


def _ingest_coverage(args, expected_keys):
    """Read `--coverage-stdin` and build the round's coverage list, or fail closed.

    One line per required dimension: ``<key> <outcome> [anchor text...]`` — the key and
    outcome are the first two whitespace-delimited tokens; the anchor is the rest of the
    line (a quoted draft line plus one concern clause, for `exercised`; a one-line reason,
    for `valid-N/A`). Mirrors `_ingest_ledger`'s byte-read + fail-closed decode/empty arms;
    its own `--coverage-stdin` quoted-heredoc transport keeps auditor-derived anchor text
    from traversing shell quoting (the ledger moved to `--ledger-file` in issue #200; coverage
    keeps the stdin transport). An `exercised`/`valid-N/A` line whose anchor FAILS the text-only floor is
    DOWNGRADED to `unestablished` with its anchor dropped — never rejected (unknown is not
    zero, and the coverage record must stay total over required dimensions).
    """
    lines = _read_stdin_lines(args, 'record-coverage', 'coverage list', 'coverage')
    coverage = []
    seen = set()
    for idx, line in enumerate(lines, start=1):
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            _fail('record-coverage',
                  f'coverage line {idx} needs at least a key and an outcome '
                  f'(coverage-line-shape); the form is "<key> <outcome> [anchor]"')
        key, outcome = parts[0], parts[1]
        anchor = parts[2].strip() if len(parts) == 3 else None
        if outcome not in _COVERAGE_OUTCOMES:
            _fail('record-coverage',
                  f'coverage line {idx} names an outcome outside the canonical set '
                  f'{_COVERAGE_OUTCOMES} (coverage-outcome): {outcome!r}')
        if key in seen:
            _fail('record-coverage',
                  f'coverage line {idx} duplicates key {key!r} (coverage-duplicate-key)')
        seen.add(key)
        if outcome not in _COVERAGE_ANCHORED:
            anchor = None
        else:
            floor_err = _coverage_anchor_floor(anchor)
            if floor_err is not None:
                # Downgrade, never reject: unknown is not zero. A floor-failing anchor does
                # not back coverage, so the dimension records `unestablished` with no
                # anchor — and the CAUSE is breadcrumbed rather than collapsed onto the
                # outcome, so a reader can tell a tool-side text refusal (which the auditor
                # could fix by rewording) from the auditor's own substantive judgment.
                print(f'record-coverage: dimension {key!r} anchor fails the text-only floor '
                      f'({floor_err}); recorded unestablished', file=sys.stderr)
                outcome, anchor = 'unestablished', None
        # ONE append for all three arms — the entry shape has a single construction site,
        # so a later field cannot be added to two arms and missed on the third.
        coverage.append({'key': key, 'outcome': outcome, 'anchor': anchor})
    # TOTALITY over the authoritative enumeration (issue #708). `evaluate_coverage`'s
    # `all(...)` is vacuously true over a SHORT list, so without this a one-line return
    # against a twelve-dimension enumeration would derive `backed` — the mechanism passing
    # on exactly the input it exists to catch. A returned key outside the enumeration is
    # refused (the join has no dimension to attach it to); an enumerated key the auditor
    # returned no line for is synthesized `unestablished` — never dropped, never assumed
    # covered (unknown is not zero).
    unknown = [k for k in seen if k not in set(expected_keys)]
    if unknown:
        _fail('record-coverage',
              f'coverage names {len(unknown)} key(s) outside the authoritative enumeration '
              f'(coverage-unknown-key): {sorted(unknown)}; the auditor outcomes join the '
              f'enumerated dimensions by shared key, so an unenumerated key has no '
              f'dimension to attach to')
    for key in expected_keys:
        if key not in seen:
            coverage.append({'key': key, 'outcome': 'unestablished', 'anchor': None})
    return coverage


def cmd_query_coverage(args):
    """The run's coverage-backing, read back durably (issue #708).

    Read-only and exit-0 like its sibling queries, with the same inline fail-closed
    foreign-nonce answer. The FIRST line is the decided token line
    `coverage_backing=<token> coverage_render=<token>` — the orchestrator reads its
    coverage decision from state, never from context recall, so the decision survives a
    compaction. Subsequent lines (one per dimension of the coverage round) carry the durable
    per-dimension outcomes: `key=<k> outcome=<o> anchor=<text>` (anchor trailing, may
    contain spaces — the anchor floor bars it forging a `<field>=` token).
    """
    state = _query_state(args.slug)
    # The producer already owns the foreign-nonce answer, so it is not restated here; this
    # branch's only remaining job is to skip the per-dimension rows a foreign caller may
    # not read. The decided line is derived ONCE and handed to the producer, so the round
    # below and the tokens above still ride the same derivation (see the comment following).
    cov = None if (state is not None and state['nonce'] != args.nonce) \
        else evaluate_coverage(state)
    print(_coverage_backing_line(state, args.nonce, cov=cov))
    if cov is None:
        return
    # The coverage round rides on the SAME derivation that decided the tokens — deriving
    # it a second time would be two call sites that must agree on which round is
    # authoritative, the drift #603 removed from the summary fields.
    rnd = cov['round']
    if rnd is not None:
        for e in rnd.get('coverage') or []:
            anchor = e.get('anchor')
            trailer = f' anchor={anchor}' if anchor is not None else ''
            print(f'key={e["key"]} outcome={e["outcome"]}{trailer}')


def _coverage_backing_line(state, nonce, cov=None):
    """The `query-coverage` DECIDED FIRST line only (issue #795 hoist).

    `cov` is an optional PRE-DERIVED `evaluate_coverage(state)` — the same optional-operand
    shape `evaluate_calibration_trigger(state, cal)` already uses. `cmd_query_coverage`
    passes the derivation it needs anyway for the per-dimension rows, so the hoist adds no
    second call site that must agree on which round is authoritative; `query-boundary`
    omits it and the producer derives its own.

    Deliberately not the per-dimension rows: `cmd_query_coverage` prints a decided first
    line then one `key=… outcome=…` row per dimension, so there is no single line to match
    for that component. `query-boundary` carries only this decided line — what the boundary
    decision reads — and the procedure keeps calling `query-coverage` where the rows are
    needed, so the issue-#708 durable read-back is not truncated.
    """
    if state is not None and state['nonce'] != nonce:
        return 'coverage_backing=unestablished coverage_render=none reason=foreign-nonce'
    if cov is None:
        cov = evaluate_coverage(state)
    # `reason=` renders on EVERY arm (`none` when there is nothing to name): a
    # conditionally-present trailing field cannot be told from a truncated line.
    return (f'coverage_backing={cov["backing"]} coverage_render={cov["render"]} '
            f'reason={cov.get("reason") or "none"}')


# ── The post-close ledger channels (issue #603) ───────────────────────────────────
# record-adjudication is write-once, so these three are the only sanctioned ways to move
# an INDIVIDUAL entry after its round closes. They are not the only way a closed round's
# effective count changes: a LATER round's FILE adjudication reaches backwards through the
# supersession sweep in `cmd_record_adjudication`, retiring every prior unresolved entry
# run-wide. Write-once bars re-adjudicating the SAME round; it does not bar that first
# write on a later one. They share one resolution/validation
# spine: locate a ledgered round no later than the latest completed round, resolve the
# named ids against its ledger, refuse every illegal transition with a named breadcrumb,
# then re-derive and print the run-wide remaining count (never a caller-supplied tally —
# a recall-fabricated number is unrepresentable on these CLIs by construction).

def _ledgered_round(prefix, doc, round_no):
    """The named round's ledger, or fail closed naming why it has none."""
    rnd = _find_round(doc, round_no)
    if rnd is None:
        _fail(prefix, f'no round {round_no} recorded (unknown-round)')
    latest = last_completed(doc)
    if latest is None or round_no > latest['round']:
        _fail(prefix, f'round {round_no} is later than the latest completed round '
                      f'(round-not-completed); a round\'s findings are only nameable '
                      f'once it has closed')
    if rnd.get('adjudicated_verdict') is None:
        _fail(prefix, f'round {round_no} is not adjudicated (round-unadjudicated); its '
                      f'findings have no recorded ledger')
    ledger = _ledger(rnd)
    if ledger is None:
        _fail(prefix, f'round {round_no} carries no finding ledger (round-unledgered); a '
                      f'FILE round, a REVISE + {_UNESTABLISHED!r} round, and a '
                      f'pre-change round record none')
    return rnd, ledger


def _named_entries(prefix, ledger, raw_ids, flag):
    """Resolve a comma-separated id list against a ledger, or fail closed.

    Repeated ids collapse to ONE entry, first occurrence winning, so the order the
    caller named survives. The mutations are idempotent per entry, so a duplicate never
    corrupted state — but `record-reopen` and `record-invalidate` print
    `reopened=`/`invalidated=` from this list's length, and the skill parses those
    echoes, so an un-deduped list reported more entries moved than exist.
    `record-resolution` echoes no such count: it prints the frozen at-close tally and
    the run-wide re-derived `remaining=`, neither of which varies with `len(entries)`,
    so that channel is insensitive to duplicates. The de-duplication is nonetheless
    shared by all three channels, so the property holds for every id flag rather than
    only the ones whose echo happens to expose it.
    """
    ids = [tok.strip() for tok in (raw_ids or '').split(',') if tok.strip()]
    if not ids:
        _fail(prefix, f'{flag} named no ledger entries (empty-id-list)')
    by_id = {entry['id']: entry for entry in ledger}
    resolved = []
    seen = set()
    for tok in ids:
        try:
            eid = int(tok)
        except ValueError:
            _fail(prefix, f'{flag} names {tok!r}, which is not a ledger entry id '
                          f'(unknown-id)')
        if eid not in by_id:
            _fail(prefix, f'{flag} names entry id {eid}, which is not on the round\'s '
                          f'ledger (unknown-id)')
        if eid in seen:
            continue
        seen.add(eid)
        resolved.append(by_id[eid])
    return resolved


def _render_count(eff):
    """Render an effective count: the integer, else the literal `unestablished`.

    The single None -> token mapping, so the mutation echo lines and `query-summary`
    can never disagree about how an unestablished effective count prints.
    """
    return _UNESTABLISHED if eff is None else str(eff)


def _remaining(doc):
    """The run-wide effective remaining count, rendered for a mutation's echo line."""
    return _render_count(_effective_unresolved(doc))


def _save_or_fail(prefix, doc, slug):
    try:
        save_state(doc, slug)
    except StateError as exc:
        _fail(prefix, str(exc))


def _find_revision(doc, ordinal):
    """The recorded revision with this ordinal, or None. The `_find_round` sibling."""
    for rev in doc['revisions']:
        if rev.get('ordinal') == ordinal:
            return rev
    return None


def _settling_provenance(doc):
    """The provenance stamp a post-close status change carries: the current revision
    ordinal, else the `pre-revision` token when no revision is recorded yet."""
    return revision_ordinal(doc) or _PRE_REVISION


def _clear_settling(entry):
    """Drop EVERY settling-provenance key a previous status change left, so a later change
    never leaves a stale ordinal behind for `_settling_ordinal` to read.

    Deliberately not "only the keys reachable today". The invalidation keys are a no-op on
    the current channels (all three refuse an `invalidated` entry), and `supersession_round`
    is likewise unreachable today — each of the three post-close channels refuses a
    superseded entry before it arrives here, though NOT all by the same guard:
    `_refuse_terminal` in `record-resolution` and `record-invalidate`, and the separate
    `status != 'resolved'` (`not-resolved`) arm in `record-reopen`, which has no
    `_refuse_terminal` call site at all — but clearing them unconditionally is
    what makes this helper's sufficiency independent of which statuses a future post-close
    channel can act on — the alternative is a comment-enforced obligation on every such
    channel to remember to add its key here. `reopen_provenance` is the one deliberate
    exemption and is NOT cleared, because it is the entry's genuine regression history.
    Note the exemption is NOT "it can never be read stale": `_convergence_basis` reads
    `reopen_provenance` for every entry whose `_settling_ordinal` is non-None, which
    includes `invalidated` — so a resolve → reopen → invalidate sequence at one ordinal
    really does surface `basis=resolution-stale` off the residual copy. That is retained
    behavior, not an accident: an entry that regressed once has a genuine staleness
    history, and reporting it is the conservative direction. It is why the key is exempt
    from clearing rather than why clearing it would be harmless.

    The cleared set is `_SETTLING_KEYS`, shared with `_validate_ledger`'s residual-key
    arm, so the writer and the read boundary cannot drift apart.
    """
    for key in _SETTLING_KEYS:
        entry.pop(key, None)


def _refuse_terminal(prefix, entry):
    """Refuse a post-close mutation on a superseded entry (terminal by construction)."""
    if entry['status'] == 'superseded':
        _fail(prefix,
              f'entry {entry["id"]} is superseded by a FILE-adjudicated round '
              f'(entry-superseded); supersession is terminal')


def cmd_record_resolution(args):
    """Mark named ledger entries resolved against a recorded revision (issue #603 AC2/AC3).

    Cross-round resolution is deliberate and legal: any LEDGERED round up to the latest
    completed round is a valid target, so a fix that lands late still clears the round
    that found the defect — and a defect listed on two rounds' ledgers is cleared by
    naming its entry on each.
    """
    doc = _load_for_mutation('record-resolution', args.slug, args.nonce)
    rnd, ledger = _ledgered_round('record-resolution', doc, args.round)
    entries = _named_entries('record-resolution', ledger, args.resolved_ids,
                             '--resolved-ids')
    if not doc['revisions']:
        _fail('record-resolution',
              'no revision is recorded for this run (no-revision-recorded); a resolution '
              'binds the fix to the revision that landed it')
    named = _find_revision(doc, args.revision_ordinal)
    if named is None:
        _fail('record-resolution',
              f'--revision-ordinal {args.revision_ordinal} names no recorded revision '
              f'(unknown-revision-ordinal)')
    if named['after_round'] < args.round:
        _fail('record-resolution',
              f'--revision-ordinal {args.revision_ordinal} names a revision recorded '
              f'after round {named["after_round"]}, below round {args.round} '
              f'(revision-predates-round); a revision cannot have fixed a finding a '
              f'later round raised')
    for entry in entries:
        status = entry['status']
        if status == 'resolved':
            _fail('record-resolution', f'entry {entry["id"]} is already resolved '
                                       f'(already-resolved)')
        if status == 'invalidated':
            _fail('record-resolution',
                  f'entry {entry["id"]} is invalidated (entry-invalidated); an entry '
                  f'retired as misclassified is not resolved as a fix that happened')
        _refuse_terminal('record-resolution', entry)
    for entry in entries:
        _clear_settling(entry)
        entry['status'] = 'resolved'
        entry['resolution_ordinal'] = args.revision_ordinal
    _save_or_fail('record-resolution', doc, args.slug)
    frozen = rnd.get('unresolved_must_revise')
    print(f'round={args.round} revision_ordinal={args.revision_ordinal} '
          f'frozen={frozen} remaining={_remaining(doc)}')


def _reopen_entry(entry, ordinal):
    """Regress one settled ledger entry to `unresolved` (issues #603, #793).

    THE single producer of the resolved -> unresolved transition. Two call sites drive it
    now — `cmd_record_reopen` (the drafter's explicit honest-correction channel) and
    `_ingest_targeted_verdicts` (a scoped round returning `not-addressed`) — and they must
    perform the same clear-and-set: `_clear_settling`, then `status`, then
    `reopen_provenance`. An earlier form of the second site omitted `reopen_provenance`,
    leaving the entry with no regression stamp; every reader that distinguishes "never
    resolved" from "regressed" then saw a scoped-round reopen as the former, silently
    discarding the history that channel exists to record.
    """
    _clear_settling(entry)
    entry['status'] = 'unresolved'
    entry['reopen_provenance'] = ordinal


def cmd_record_reopen(args):
    """Mark named resolved entries unresolved again (issue #603 AC4).

    The honest correction channel the write-once adjudication guard would otherwise
    close: a fix that did not land, or a resolution recorded in error, re-holds T1 rather
    than being silently absorbed. Provenance is the CURRENT revision ordinal when at
    least one revision is recorded, else the literal `pre-revision` token — so a
    `resolved-at-adjudication` entry that turns out wrong BEFORE any revision exists is
    still honestly reopenable.
    """
    doc = _load_for_mutation('record-reopen', args.slug, args.nonce)
    _, ledger = _ledgered_round('record-reopen', doc, args.round)
    entries = _named_entries('record-reopen', ledger, args.ids, '--ids')
    for entry in entries:
        if entry['status'] != 'resolved':
            _fail('record-reopen',
                  f'entry {entry["id"]} is {entry["status"]}, not resolved '
                  f'(not-resolved); only a resolved entry can regress')
    ordinal = _settling_provenance(doc)
    for entry in entries:
        _reopen_entry(entry, ordinal)
    _save_or_fail('record-reopen', doc, args.slug)
    print(f'round={args.round} reopened={len(entries)} remaining={_remaining(doc)}')


def cmd_record_invalidate(args):
    """Retire named ledger entries as misclassified (issue #603 AC19).

    A finding adjudicated must-revise in error is retired as INVALID with a mandatory
    one-line reason and visible provenance — never laundered through record-resolution as
    a fix that never happened. An erroneous invalidation needs no amend path of its own:
    the defect re-enters through the recurrence-of-an-invalidated-entry arm as a fresh
    entry on a new round's ledger.
    """
    doc = _load_for_mutation('record-invalidate', args.slug, args.nonce)
    _, ledger = _ledgered_round('record-invalidate', doc, args.round)
    entries = _named_entries('record-invalidate', ledger, args.ids, '--ids')
    reason = (args.reason or '').strip()
    if not reason:
        _fail('record-invalidate', '--reason is empty (empty-reason); retiring a finding '
                                   'as misclassified requires a recorded rationale')
    # argv carries what a heredoc cannot: --reason reaches this guard with an embedded
    # newline intact, so the splitter check is not redundant with _ingest_ledger's.
    splitter = _record_splitting_char(reason)
    if splitter is not None:
        _fail('record-invalidate',
              f'--reason contains the record-splitting character {splitter!r} '
              f'(reason-control-char); the rationale is one line of identity data — '
              f'reword it without the embedded newline or carriage return and re-issue '
              f'the call')
    forged = _forged_protocol_token(reason)
    if forged is not None:
        _fail('record-invalidate',
              f'--reason contains the protocol token {forged + "="!r} '
              f'(reason-protocol-vocabulary); reword it without the <field>= form and '
              f're-issue the call')
    for entry in entries:
        if entry['status'] == 'invalidated':
            _fail('record-invalidate', f'entry {entry["id"]} is already invalidated '
                                       f'(already-invalidated)')
        _refuse_terminal('record-invalidate', entry)
    ordinal = _settling_provenance(doc)
    for entry in entries:
        _clear_settling(entry)
        entry['status'] = 'invalidated'
        entry['invalidation_reason'] = reason
        entry['invalidation_provenance'] = ordinal
    _save_or_fail('record-invalidate', doc, args.slug)
    print(f'round={args.round} invalidated={len(entries)} remaining={_remaining(doc)}')


def _load_generator():
    """Import `render-audit-prompt.py` as a module and return it (issue #709).

    The canonical dispatch-instruction generator is this tool's sibling in
    `scripts/`, resolved relative to THIS file (never the cwd), so the repo checkout
    and the vendored plugin layout resolve identically — the same anchoring the
    generator itself uses for its template.

    Imported rather than sub-processed: the generator is a pure function, so an
    in-process call keeps the regeneration Windows-safe (no `.sh` exec, #275; no
    interpreter-path guessing) and cannot inherit this process's argv. Its module
    name carries a dash, so it is loaded by file location rather than by `import`.
    Every module-body-execution failure that raises an `Exception` — file absent,
    unimportable (for any such reason its module body raises, not merely the import-shaped
    ones), or importable-but-missing either entry point this module calls — raises
    `_DigestError`
    so the caller records `regeneration-failed`; none of them may read as an established
    comparison, and none may escape as a traceback that would abort `record-return`
    before it saves the round. The two `BaseException` shapes a module body could raise
    — `SystemExit` and `KeyboardInterrupt` — are deliberately NOT absorbed: a generator
    that raises `SystemExit` at import time is a broken installation whose traceback the
    operator should see, and an interrupt must stay interruptible. The shipped generator
    raises its `SystemExit` only under `if __name__ == '__main__'`, so neither is reachable
    through this loader today.
    """
    import importlib.util
    path = Path(__file__).resolve().parent / 'render-audit-prompt.py'
    spec = importlib.util.spec_from_file_location('devflow_render_audit_prompt', path)
    if spec is None or spec.loader is None:
        raise _DigestError(f'could not load the dispatch-instruction generator at {path}')
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        # shape is the same decided outcome here (the comparand cannot be regenerated),
        # and narrowing to the import-shaped exceptions let a ValueError/NameError at
        # module scope escape as a traceback that aborted record-return mid-round.
        raise _DigestError(f'could not import the dispatch-instruction generator '
                           f'at {path}: {exc}') from exc
    for entry_point in ('instructions_bytes', 'default_template_path'):
        if not hasattr(mod, entry_point):
            raise _DigestError(f'the dispatch-instruction generator at {path} has no '
                               f'{entry_point} entry point')
    return mod


def regenerate_instructions_digest(slug, inputs):
    """Regenerate the canonical dispatch instructions and return their digest.

    This is the comparand the auditor's quoted object ID is matched against, and it is
    deliberately the FRESHLY-REGENERATED digest rather than the write-time digest the
    dispatch recorded. A hand-written *steered* instruction file that never went through
    the generator would hash equal to its own recorded digest — self-consistent and
    useless — so comparing against a regeneration from the round's closed inputs is what
    makes the check prove the dispatched file was canonical, not merely unchanged.

    The bytes hashed come from the generator's own `instructions_bytes`, which is the
    single owner of its on-disk framing and is what its CLI writes to stdout — therefore
    exactly what the orchestrator redirects into the instruction file. Replicating that
    framing here instead would make a change to the generator's output silently
    false-alarm every clean audit, which is why the producer owns it and a renderer test
    couples the two.
    """
    mod = _load_generator()
    try:
        template_path = (Path(inputs['template_path']) if inputs.get('template_path')
                         else mod.default_template_path())
    except Exception as exc:
        # failure resolving the comparand's template is a regeneration failure, never a
        # traceback out of record-return.
        raise _DigestError(f'could not resolve the dispatch-instruction template: '
                           f'{exc}') from exc
    try:
        draft_text = Path(inputs['draft_path']).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise _DigestError(f'could not read the draft file recorded as a regeneration '
                           f'input ({inputs["draft_path"]}): {exc}') from exc
    # issue #793 — the scope file is part of the CLOSED recorded tuple, so it is read here
    # (from the recorded path) and verified against the recorded digest before it can
    # influence a single rendered byte. Three decided arms, deliberately distinct:
    #   * no recorded scope     → a discovery round; render exactly as before (`None`), so
    #                             every pre-#793 recorded tuple regenerates byte-identically.
    #   * recorded but UNREADABLE → its own named failure, so the reader is sent at the
    #                             missing artifact rather than at the generator.
    #   * recorded and PRESENT but the bytes no longer hash to the recorded digest → the
    #                             tamper this freeze exists to catch; a distinct name again.
    # Nothing here reads the live ledger, which is what makes a post-dispatch resolution,
    # reopen or invalidation unable to move this regeneration.
    scope_text = None
    if inputs.get('scope_path'):
        try:
            scope_bytes = Path(inputs['scope_path']).read_bytes()
        except OSError as exc:
            raise _DigestError(
                f'could not read the dispatch-scope file recorded as a regeneration '
                f'input ({inputs["scope_path"]}): {exc}',
                reason='scope-file-unreadable') from exc
        if hash_bytes(scope_bytes) != inputs.get('scope_digest'):
            raise _DigestError(
                f'the dispatch-scope file at {inputs["scope_path"]} no longer matches the '
                'digest recorded at dispatch, so the payload the auditor was given is not '
                'the payload this round froze', reason='scope-file-tampered')
        try:
            scope_text = scope_bytes.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise _DigestError(f'the dispatch-scope file is not valid UTF-8: {exc}',
                               reason='scope-file-tampered') from exc
    try:
        rendered = mod.instructions_bytes(
            template_path, slug, inputs['draft_path'], inputs['instructions_path'],
            draft_text, scope_text)
    except Exception as exc:
        # not importable by name here without coupling to its module identity; every
        # failure lands on the same fail-closed `regeneration-failed` arm regardless of
        # type, so the broad catch is the DECIDED behavior rather than a swallowed error
        # (it re-raises as _DigestError, carrying the specific cause).
        raise _DigestError(f'the dispatch-instruction generator failed: {exc}') from exc
    return hash_bytes(rendered)


# ── Hoisted into this module by the issue #567 split ────────────────────────
# Each definition below stood after a caller the split separates it from, so it moved
# earlier to keep the sibling import graph acyclic. Bodies are unchanged.
def steering_state(slug, attempt, quoted_object_id, extra_dispatch_content):
    """Establish whether the auditor's instructions were canonical (issue #709).

    Returns `(state, reason)` with `state` in `_STEERING_STATES` and `reason` in
    `_STEERING_REASON_STATE`. The reason precedence below is DECIDED, not incidental: the
    most structural cause wins, so a run that never had an instruction file is never
    diagnosed as an ID mismatch.

    Fail-closed, exactly like `_carriage_ok`: an ABSENT quoted object ID and an ABSENT
    no-extra-content affirmation are treated as a mismatch and a positive report
    respectively. Absent evidence is never established-clean by omission — that is the
    fail-open hazard this whole surface exists to close.
    """
    if attempt['arm'] != 'file':
        return ('not-established', 'no-instructions-file')
    inputs = attempt.get('instructions')
    if not inputs:
        return ('not-established', 'inputs-unrecorded')
    try:
        canonical = regenerate_instructions_digest(slug, inputs)
    except _DigestError as exc:
        # Never silent: the specific regeneration cause reaches stderr even though the
        # recorded reason is the coarse closed token.
        print(f'record-return: steering-absence could not be established: {exc}',
              file=sys.stderr)
        # issue #793 — the two dispatch-scope arms carry their OWN reasons rather than
        # being folded into the coarse `regeneration-failed`. The distinction is the whole
        # point of the criterion: an absent scope file and a tampered one send a reader to
        # opposite remedies, and a reader pointed at the generator when the artifact was
        # merely deleted spends the debugging on the wrong module. The token rides on the
        # exception itself, set at the raise site — never recovered by matching the
        # message text, which a rewording would silently break.
        return ('not-established', getattr(exc, 'reason', None) or 'regeneration-failed')
    if not quoted_object_id:
        return ('not-established', 'instructions-object-id-absent')
    if quoted_object_id != canonical:
        # Attribute the mismatch honestly. When the DISPATCH-time regeneration already
        # disagreed, the divergence predates the auditor entirely — the file it read was
        # never regenerable — so reporting this as "the auditor read something else"
        # sends the reader at the auditor instead of at the write or the recorded inputs.
        # Both are fail-closed; they differ only in WHERE they send the reader, so the
        # distinction has to survive on the durable surface, not just on stderr — a
        # breadcrumb is lost to a redirect or a compacted context, and the user is
        # contractually pointed at the Step 4 audit-summary line, which renders the reason.
        if inputs.get('dispatch_regeneration') == 'diverged':
            print('record-return: the instruction file already failed its dispatch-time '
                  'regeneration (dispatch_regeneration=diverged), so this mismatch was '
                  'introduced at or before dispatch — not by the auditor. See the '
                  'record-dispatch warning for the causes this tool could not '
                  'distinguish.', file=sys.stderr)
            return ('not-established', 'instructions-noncanonical-at-dispatch')
        return ('not-established', 'instructions-object-id-mismatch')
    if extra_dispatch_content is None:
        return ('not-established', 'extra-dispatch-content-unreported')
    if extra_dispatch_content != 'no':
        return ('not-established', 'extra-dispatch-content')
    return ('established', 'canonical-match')
# issue #1103 — the carriage causes `_carriage_ok` distinguishes. The `ok` boolean is
# unchanged for `classify_return` (which still collapses both failure causes to the same
# fail-closed `no-parseable-verdict`); the CAUSE is what `cmd_record_return` renders as a
# distinct stderr breadcrumb, so an operand slip (absent evidence) is diagnosable apart
# from a genuine disagreement (mismatched evidence) and both apart from an unparseable
# auditor return. `None` accompanies `ok=True`; `'not-applicable'` accompanies the inline
# arm, which carries no auditor-quoted evidence to be absent or wrong.
# The closed cause set, enumerated so a reader can grep one symbol for the whole domain.
_CARRIAGE_ABSENT = 'absent'
_CARRIAGE_MISMATCH = 'mismatch'
_CARRIAGE_NOT_APPLICABLE = 'not-applicable'
def _carriage_ok(attempt, args):
    """Compare the auditor's quoted carriage evidence against recorded values.

    Returns `(ok, cause)`. `ok` is the fail-closed boolean `classify_return` consumes;
    absent evidence is treated exactly like mismatched evidence THERE — fail closed on
    missing evidence, so an auditor that quotes nothing cannot pass off an unproven
    verdict as a proven one. `cause` (issue #1103) preserves WHICH of the two produced a
    failure so `cmd_record_return` can render them as distinct breadcrumbs: `'absent'`
    when the evidence was not supplied, `'mismatch'` when it was supplied but disagreed
    with the recorded dispatch value, `None` when `ok`, and `'not-applicable'` on the
    inline arm (no carriage exists to prove).
    """
    if attempt['arm'] == 'file':
        if not args.carriage_object_id:
            return False, _CARRIAGE_ABSENT
        if args.carriage_object_id != attempt['digest']:
            return False, _CARRIAGE_MISMATCH
        return True, None
    if attempt['arm'] == 'embed':
        if not (args.carriage_sentinel_open and args.carriage_sentinel_close):
            return False, _CARRIAGE_ABSENT
        if (args.carriage_sentinel_open != attempt['sentinel_open']
                or args.carriage_sentinel_close != attempt['sentinel_close']):
            return False, _CARRIAGE_MISMATCH
        return True, None
    # The inline arm carries no auditor-quoted evidence: the orchestrator handed the
    # bytes to the auditor in its own context, so there is no carriage to prove.
    return True, _CARRIAGE_NOT_APPLICABLE
# Diagnostics already written to stderr this process, keyed by the exact (slug, message)
# pair. Deduping on the identity of the emitted line is what lets the duplicate-suppression
# be safe: see `_query_state`.
_STATE_BREADCRUMB_EMITTED = set()
def _query_state(slug):
    """Read the run's state, or None with a breadcrumb naming why (never a raise).

    A repeated read of the same file in one process emits its breadcrumb ONCE — the
    `next_call=` emitter's post-mutation re-read would otherwise put two consecutive
    copies of one diagnostic on a surface the state-owner-unavailable fallback routes on,
    which reads as two separate failures.

    The suppression is keyed on the **identity of the diagnostic actually emitted**, never
    on a caller-supplied flag (issue #795 shadow review). The previous `quiet=True`
    parameter suppressed the breadcrumb unconditionally at the emitter's call site, on the
    assumption that the command had already emitted the identical line. That holds for the
    QUERY class, whose handlers reach state through this function — but every MUTATION
    subcommand reaches state through `load_state`/`_fail` and never calls this at all, so
    for those ~20 subcommands the emitter's re-read was the FIRST read here and its
    suppression left `next_call=unestablished reason=state-unestablished` standing with no
    diagnosis of why. Keying on the emitted line closes that gap without reintroducing the
    doubled diagnostic: a genuine second read of an already-reported failure stays quiet,
    while a first-and-only read always speaks.
    """
    try:
        return load_state(slug)
    except StateError as exc:
        key = (slug, str(exc))
        if key not in _STATE_BREADCRUMB_EMITTED:
            _STATE_BREADCRUMB_EMITTED.add(key)
            sys.stderr.write(f'issue-audit-state.py query: state unestablished — {exc}\n')
        return None
def _yn(v):
    return 'yes' if v else 'no'
def _stdin_bytes_or_fail(args, command, phrase):
    """Return the hoisted stdin bytes, reproducing the guarded sites' fd-0-closed and
    read-error breadcrumbs verbatim (issue #1040). `phrase` is the exact wording each site
    used after `could not read ` (`draft bytes`, `revised bytes`, `the fetched body`, `the
    coverage list`) — the finding ledger moved off stdin to `--ledger-file` in issue #200.
    """
    if args._stdin_missing:
        _fail(command, f'could not read {phrase} from stdin: no stdin is attached '
                       f'(fd 0 is closed)')
    if args._stdin_error is not None:
        _fail(command, f'could not read {phrase} from stdin: {args._stdin_error}')
    return args._stdin_data


__all__ = [
    "_CARRIAGE_ABSENT",
    "_CARRIAGE_MISMATCH",
    "_CARRIAGE_NOT_APPLICABLE",
    "_NEXT_CALL_CTX_KEYS",
    "_STATE_BREADCRUMB_EMITTED",
    "_SUMMARY_BLOCK_BOOL_FIELDS",
    "_SUMMARY_BLOCK_FIELDS",
    "_SUMMARY_FIELDS",
    "_attestation_frozen",
    "_carriage_ok",
    "_clear_settling",
    "_coverage_backing_line",
    "_cross_check_kind",
    "_dispatch_next_call",
    "_emit_next_call",
    "_find_revision",
    "_ingest_adjudication_records",
    "_ingest_coverage",
    "_ingest_ledger",
    "_ingest_targeted_verdicts",
    "_ledgered_round",
    "_load_for_mutation",
    "_load_generator",
    "_named_entries",
    "_new_doc",
    "_next_call_body",
    "_next_call_ctx",
    "_permitted_retry_arms",
    "_query_state",
    "_read_ledger_file_lines",
    "_read_stdin_lines",
    "_refuse_terminal",
    "_remaining",
    "_render_count",
    "_reopen_entry",
    "_resolve_next_call",
    "_save_or_fail",
    "_settling_provenance",
    "_stdin_bytes_or_fail",
    "_summary",
    "_summary_block_line",
    "_yn",
    "cmd_init",
    "cmd_query_coverage",
    "cmd_record_adjudication",
    "cmd_record_adjudication_render",
    "cmd_record_coverage",
    "cmd_record_dispatch",
    "cmd_record_invalidate",
    "cmd_record_reopen",
    "cmd_record_resolution",
    "cmd_record_return",
    "regenerate_instructions_digest",
    "route_arm",
    "steering_state",
    "summary_fields",
]

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""State I/O, validation, pure decision functions and the
per-finding ledger.

Part 2 of the `/prflow:spec` audit-lifecycle state owner. The CLI entry and
the two-class contract live in `scripts/issue-audit-state.py`, which imports this module
and re-exports every name in `__all__`; issue #567 split the bodies out so each source
file loads in one whole-file Read. This module adds no behavior of its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

from issue_audit_state_vocab import (
    _ADJUDICATED_VERDICTS,
    _ADJUDICATION_RECORD_CLASSES,
    _ADJUDICATION_RENDER_STATES,
    _ARMS,
    _ATTESTATIONS,
    _CALIBRATION_BACKINGS,
    _CALLER_SUPPLIED_FLAGS,
    _CLAIM_VERDICTS,
    _CLASSIFICATIONS,
    _COVERAGE_ANCHOR_MAX,
    _COVERAGE_ANCHORED,
    _COVERAGE_BACKING_OUTCOMES,
    _COVERAGE_BACKINGS,
    _COVERAGE_OUTCOMES,
    _COVERAGE_RENDERS,
    _DISPATCH_REGENERATION,
    _DRAFT_TIERS,
    _ELIGIBILITY_REASONS,
    _EMBED_MARKER_TOKENS,
    _FINAL_BYTE_COVERAGE,
    _FINAL_BYTE_PASS_CAP,
    _FINAL_BYTE_REFUNDS_KEY,
    _GROUNDS,
    _IMPACT_BEARING_CLASSES,
    _IMPACT_CLASSES,
    _LEDGER_INGESTED_RESOLVED,
    _MAX_AUTOMATIC_REAUDITS,
    _MAX_CONFIRMING_ROUNDS,
    _NEXT_ACTIONS,
    _NEXT_CALL_REFUSALS,
    _NEXT_CALL_UNESTABLISHED_RE,
    _OVERRIDE_KINDS,
    _OVERRIDE_SURFACES,
    _PRE_REVISION,
    _REQUIRED_TOP,
    _ROUND_BUDGETS,
    _ROUND_IS_CALLER_INTENT,
    _ROUND_KIND_REASONS,
    _ROUND_KINDS,
    _ROUND_OUTCOMES,
    _STATE_OWNER_PLACEHOLDER,
    _STEERING_REASON_STATE,
    _STEERING_STATES,
    _UNESTABLISHED,
    _VERDICT_BEARING_OUTCOMES,
    _VERDICTS,
    SCHEMA_VERSION,
    TRANSITIONS,
    StateError,
    _DigestError,
    _fail,
    _forged_protocol_token,
    _is_bound_path,
    _record_splitting_char,
    _replace_with_retry,
    _require,
    _validate_finding_evidence,
    _validate_ledger,
    hash_bytes,
    state_path,
)


def _coverage_anchor_floor(text):
    """The text-only anchor floor (issue #708), as an error token or None.

    Split by where the operand lives: this is the TOOL-SIDE floor over the anchor text
    ALONE — non-empty, within the per-anchor length cap, no record-splitting byte, and no
    protocol-vocabulary `<field>=` token drawn from the tool's own printed surface. It
    reuses the ledger-anchor guard family (`_record_splitting_char` / `_forged_protocol_token`)
    so one closed vocabulary governs both — auditor-derived coverage text is identity data,
    never protocol and never an instruction to obey. The DATA-dependent checks (byte-identity
    against the rendered dimension text, and the cited-draft-line existence check) are the
    ORCHESTRATOR's, run against data the state owner does not hold; they are not enforced here.
    """
    if not isinstance(text, str) or not text.strip():
        return 'anchor-empty'
    if len(text) > _COVERAGE_ANCHOR_MAX:
        return 'anchor-over-cap'
    if _record_splitting_char(text) is not None:
        return 'anchor-control-char'
    if _forged_protocol_token(text) is not None:
        return 'anchor-protocol-vocabulary'
    return None


def _validate_coverage(rnd, num):
    """Re-enforce the per-dimension-coverage invariants at the READ boundary (issue #708).

    Absent is legal (a round records no coverage, and every pre-change round record none) —
    present-but-wrong-shape is corrupt, the same additive-optional pattern the per-finding
    ledger and `draft_binding` follow. Every violation raises StateError, collapsing the
    whole file to unestablished (the fail-closed environmental class), so a hand-corrupted
    coverage entry can never reach the derivation/trigger/summary as if established.
    """
    render = rnd.get('coverage_render')
    if render is not None and render not in _COVERAGE_RENDERS:
        raise StateError(f'round {num} names a coverage render outside the canonical set: '
                         f'{render!r}')
    if 'coverage' not in rnd:
        return
    if render is None:
        raise StateError(f'round {num} records coverage but no coverage_render; the render '
                         f'state is required whenever coverage is present (the derivation '
                         f'would otherwise default onto `full`, the one value that arms the '
                         f'coverage offer)')
    coverage = rnd.get('coverage')
    if not isinstance(coverage, list):
        raise StateError(f'round {num} coverage {coverage!r} is not a list')
    seen = set()
    for pos, entry in enumerate(coverage, start=1):
        if not isinstance(entry, dict):
            raise StateError(f'round {num} coverage entry {pos} is not an object')
        key = entry.get('key')
        if not isinstance(key, str) or not key.strip():
            raise StateError(f'round {num} coverage entry {pos} key {key!r} is not a '
                             f'non-empty string')
        if key in seen:
            raise StateError(f'round {num} coverage entry {pos} duplicates key {key!r}')
        seen.add(key)
        outcome = entry.get('outcome')
        if outcome not in _COVERAGE_OUTCOMES:
            raise StateError(f'round {num} coverage entry {pos} names an outcome outside '
                             f'the canonical set: {outcome!r}')
        anchor = entry.get('anchor')
        if outcome in _COVERAGE_ANCHORED:
            # An anchored outcome that reached persistence carries a floor-passing anchor:
            # ingestion downgrades a floor-failing exercised/valid-N/A to `unestablished`
            # BEFORE the write, so a hand-corrupted anchor on such an outcome is refused.
            err = _coverage_anchor_floor(anchor)
            if err is not None:
                raise StateError(f'round {num} coverage entry {pos} ({outcome}) anchor '
                                 f'fails the text-only floor ({err})')
        elif anchor is not None and not isinstance(anchor, str):
            raise StateError(f'round {num} coverage entry {pos} anchor {anchor!r} is not '
                             f'a string')
    # TOTALITY at the read boundary. Every per-entry invariant above is re-enforced, but
    # totality — the property that makes `backed` mean "every required dimension resolved"
    # — lives BETWEEN the list and the persisted enumeration, so it needs its own read-back:
    # `evaluate_coverage` derives `backed` from `all(...)` over the surviving entries, and a
    # hand-deleted `unestablished`/`skipped` entry leaves an all-backing list that would
    # launder a truncated coverage into `backed`. `record-coverage` writes `coverage` and
    # `coverage_expected` into the same round object in the same save, so an absent
    # enumeration beside a present coverage is itself corruption — refused, not tolerated.
    expected = rnd.get('coverage_expected')
    if expected is None:
        raise StateError(f'round {num} records coverage but no coverage_expected; the '
                         f'enumeration totality was checked against is written with the '
                         f'coverage itself, so its absence means the record is corrupt')
    if not isinstance(expected, list) or not expected or not all(
            isinstance(k, str) and k.strip() for k in expected):
        # A non-truthy (empty) list defeats totality vacuously: `all([])` is true and
        # `missing == []`, so an all-backing `coverage` beside `coverage_expected: []`
        # would launder into `backed`. Refused here, fail-closed to unestablished — the
        # record path already rejects an empty keyset (coverage-expected-empty), so at the
        # read boundary this is reachable only by direct state-file corruption.
        raise StateError(f'round {num} coverage_expected {expected!r} is not a non-empty '
                         f'list of non-empty strings')
    missing = [k for k in expected if k not in seen]
    if missing:
        raise StateError(f'round {num} coverage covers fewer dimensions than '
                         f'coverage_expected enumerates (missing {missing!r}); a truncated '
                         f'coverage list is never read as backed')


def _validate_adjudication_records(rnd, num):
    """Re-enforce the advisory/invalid per-finding record invariants at the READ boundary
    (issue #743).

    Absent is legal (a round records no advisory/invalid grades, and EVERY pre-change round
    records none — the decided pre-change-state arm) — present-but-wrong-shape is corrupt, the
    same additive-optional pattern the per-finding ledger and coverage follow. Every violation
    raises StateError, collapsing the whole file to unestablished (the fail-closed
    environmental class), so a hand-corrupted record can never reach the read-back, the
    calibration derivation, or the summary as if established.
    """
    render = rnd.get('adjudication_render')
    if render is not None and render not in _ADJUDICATION_RENDER_STATES:
        raise StateError(f'round {num} names an adjudication_render outside the canonical '
                         f'set: {render!r}')
    for cls in _ADJUDICATION_RECORD_CLASSES:
        records = rnd.get(f'{cls}_records')
        if records is None:
            continue
        if not isinstance(records, list):
            raise StateError(f'round {num} {cls}_records {records!r} is not a list')
        # Re-assert the record-time count<->records totality at the READ boundary, exactly as
        # `_validate_coverage` re-derives against `coverage_expected` (issue #743): ingestion
        # enforces `len(records) == --<cls>` bidirectionally, but the count is stored on the
        # round SEPARATELY from the records list, so a hand-deleted record would leave a
        # shorter list beside a stale count and could launder `under-evidenced` into `clear`
        # (a deleted impact-bearing unevidenced entry vanishes from the derivation). A round
        # that carries records ALWAYS carries the settled count beside them: `cmd_record_
        # adjudication` writes `<cls>_count` unconditionally and `<cls>_records` only when a
        # file was supplied, and every pre-#743 round carries neither — so a present records
        # list with an absent or non-int count is reachable only by the very corruption this
        # boundary defends against (delete BOTH the record and its count). Fail closed on it
        # rather than short-circuit past — a records list with no settled count is never read
        # as calibration-clear. The calibration axis is disclosure-only, but this file's read
        # boundary treats direct state corruption as in-scope.
        count = rnd.get(f'{cls}_count')
        if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0):
            raise StateError(f'round {num} {cls}_records is present but {cls}_count is '
                             f'{count!r} (records-without-count); a records list with no '
                             f'settled count is never read as calibration-clear')
        if len(records) != count:
            raise StateError(f'round {num} {cls}_records carries {len(records)} record(s) but '
                             f'{cls}_count is {count} (records-count-mismatch); a truncated '
                             f'records list is never read as calibration-clear')
        seen_ids = set()
        for pos, entry in enumerate(records, start=1):
            if not isinstance(entry, dict):
                raise StateError(f'round {num} {cls} record {pos} is not an object')
            rid = entry.get('id')
            if not isinstance(rid, int) or isinstance(rid, bool) or rid < 1:
                raise StateError(f'round {num} {cls} record {pos} id {rid!r} is not a '
                                 f'positive integer')
            if rid in seen_ids:
                raise StateError(f'round {num} {cls} record {pos} duplicates id {rid}')
            seen_ids.add(rid)
            for field in ('summary', 'rationale', 'auditor_block'):
                val = entry.get(field)
                if not isinstance(val, str) or not val.strip():
                    raise StateError(f'round {num} {cls} record {pos} {field} is missing or '
                                     f'not a non-empty string')
            # summary/rationale are one-line identity data — a record-splitting byte would
            # forge a LINE of the read-back surface. auditor_block is exempt: it is stored
            # VERBATIM and JSON-encoded at the print boundary, so its newlines render as
            # escaped bytes and cannot split a line.
            for field in ('summary', 'rationale'):
                if _record_splitting_char(entry[field]) is not None:
                    raise StateError(f'round {num} {cls} record {pos} {field} carries a '
                                     f'record-splitting byte')
            if entry.get('impact_class') not in _IMPACT_CLASSES:
                raise StateError(f'round {num} {cls} record {pos} names an impact_class '
                                 f'outside the canonical set: {entry.get("impact_class")!r}')
            ev = entry.get('evidence')
            if ev is not None and (not isinstance(ev, str)
                                   or _record_splitting_char(ev) is not None):
                raise StateError(f'round {num} {cls} record {pos} evidence {ev!r} is not a '
                                 f'one-line string')


def _validate(doc, slug):
    """Validate a loaded document, or raise StateError naming the specific violation.

    Malformed state collapses the WHOLE file to unestablished rather than trusting a
    valid prefix: a corrupted record means the writer's invariants did not hold, so
    no earlier record's grounding is trustworthy either. Unknown is not zero.
    """
    if not isinstance(doc, dict):
        raise StateError(f'top-level JSON is not an object (found {type(doc).__name__})')
    for key in _REQUIRED_TOP:
        if key not in doc:
            raise StateError(f'required key {key!r} is missing')
    if doc['schema_version'] != SCHEMA_VERSION:
        raise StateError(
            f'schema_version {doc["schema_version"]!r} in file, tool expects '
            f'{SCHEMA_VERSION} (no migration path)')
    if doc['slug'] != slug:
        raise StateError(f'slug mismatch: file holds {doc["slug"]!r}, asked for {slug!r}')
    if not isinstance(doc['nonce'], str) or not doc['nonce']:
        raise StateError('nonce is missing or not a non-empty string')
    for key in ('rounds', 'revisions', 'overrides'):
        if not isinstance(doc[key], list):
            raise StateError(f'{key!r} is not a list (found {type(doc[key]).__name__})')
    seen = set()
    last = 0
    for rnd in doc['rounds']:
        if not isinstance(rnd, dict):
            raise StateError('a round record is not an object')
        for key in ('round', 'attempts', 'outcome'):
            if key not in rnd:
                raise StateError(f'a round record is missing required key {key!r}')
        num = rnd['round']
        if not isinstance(num, int) or isinstance(num, bool):
            raise StateError(f'round number {num!r} is not an integer')
        if num in seen:
            raise StateError(f'duplicate round number {num}')
        if num <= last:
            raise StateError(f'out-of-order round number {num} (previous was {last})')
        seen.add(num)
        last = num
        if not isinstance(rnd['attempts'], list) or not rnd['attempts']:
            raise StateError(f'round {num} has no attempts recorded')
        for att in rnd['attempts']:
            if not isinstance(att, dict) or 'arm' not in att:
                raise StateError(f'round {num} has a malformed attempt record')
            if att['arm'] not in _ARMS:
                raise StateError(f'round {num} names an arm outside the canonical set: '
                                 f'{att["arm"]!r}')
            # Mutation paths index these unconditionally (_carriage_ok, creation-epoch):
            # a corrupted field must collapse HERE to a named breadcrumb, never surface
            # later as a raw KeyError traceback.
            for key in ('digest', 'body_digest'):
                val = att.get(key)
                if not isinstance(val, str) or not val:
                    raise StateError(f'round {num} has an attempt whose {key} is missing '
                                     f'or not a non-empty string')
            for key in ('sentinel_open', 'sentinel_close'):
                val = att.get(key)
                if val is not None and not isinstance(val, str):
                    raise StateError(f'round {num} has an attempt whose {key} is not a '
                                     f'string')
            # issue #709: the canonical dispatch-instruction record. `None` (or absent —
            # a v3 round dispatched with no instruction file) is legal and reads as
            # unestablished; a PRESENT record must be complete. `record-return` INDEXES
            # `draft_path` and `instructions_path` to regenerate the comparand, so a
            # half-recorded object would raise a KeyError at that mutation site instead
            # of collapsing here to a named breadcrumb. The other two are validated for a
            # different reason, stated so a later reader does not mistake them for
            # comparand inputs: `template_path` is read through `.get` (absent means the
            # generator's own default), and `digest` has no reader at all — it is the
            # dispatch-time diagnostic the `instructions_digest=` line prints, and it is
            # deliberately NOT the comparand (see `regenerate_instructions_digest`).
            instr = att.get('instructions')
            if instr is not None:
                if not isinstance(instr, dict):
                    raise StateError(f'round {num} has an attempt whose instructions '
                                     f'record is not an object')
                d = instr.get('digest')
                if not isinstance(d, str) or not d:
                    raise StateError(f'round {num} has an instructions record whose '
                                     f'digest is missing or not a non-empty string')
                for key in ('instructions_path', 'draft_path'):
                    if not _is_bound_path(instr.get(key)):
                        raise StateError(f'round {num} has an instructions record whose '
                                         f'{key} is not a non-empty absolute path free '
                                         f'of newline/carriage-return bytes')
                tmpl = instr.get('template_path')
                if tmpl is not None and not _is_bound_path(tmpl):
                    raise StateError(f'round {num} has an instructions record whose '
                                     f'template_path is not None and not a non-empty '
                                     f'absolute path free of newline/carriage-return '
                                     f'bytes')
                # issue #718: what the DISPATCH-time regeneration observed. Absent is
                # legal (a round recorded before this field existed); present must be one
                # of the closed three, so a hand-edited state cannot invent a reassuring
                # value and cannot spell `diverged` as something the reader ignores.
                dreg = instr.get('dispatch_regeneration')
                if dreg is not None and dreg not in _DISPATCH_REGENERATION:
                    raise StateError(f'round {num} has an instructions record whose '
                                     f'dispatch_regeneration is not one of '
                                     f'{sorted(_DISPATCH_REGENERATION)}')
        # issue #709: the round's steering-absence result. Absent/None is legal (a
        # refused completion, a degraded arm, a pre-#709 round) and reads as
        # unestablished; a present record must name a state AND a reason from the closed
        # sets, so a hand-corrupted `{'state': 'established'}` with a forged or missing
        # reason cannot walk the run past the gate that field exists to hold.
        steer = rnd.get('steering')
        if steer is not None:
            if not isinstance(steer, dict):
                raise StateError(f'round {num} has a steering record that is not an '
                                 f'object')
            if steer.get('state') not in _STEERING_STATES:
                raise StateError(f'round {num} names a steering state outside the '
                                 f'canonical set: {steer.get("state")!r}')
            if steer.get('reason') not in _STEERING_REASON_STATE:
                raise StateError(f'round {num} names a steering reason outside the '
                                 f'canonical set: {steer.get("reason")!r}')
            # The PAIR, not the two fields independently: a reason may carry exactly
            # one state, so a record pairing `established` with a refusal reason (or
            # the reverse) is refused here rather than reaching the eligibility gate.
            if _STEERING_REASON_STATE[steer['reason']] != steer['state']:
                raise StateError(
                    f'round {num} pairs steering state {steer["state"]!r} with reason '
                    f'{steer["reason"]!r}, which belongs to state '
                    f'{_STEERING_REASON_STATE[steer["reason"]]!r}')
        if rnd['outcome'] is not None and rnd['outcome'] not in _ROUND_OUTCOMES:
            raise StateError(f'round {num} names an outcome outside the canonical set: '
                             f'{rnd["outcome"]!r}')
        fc = rnd.get('findings_count')
        if fc is not None and (not isinstance(fc, int) or isinstance(fc, bool)
                               or fc < 0):
            raise StateError(f'round {num} findings_count {fc!r} is not a '
                             f'non-negative integer')
        # `pending` decides the next dispatch, so a hand-corrupted value outside the closed
        # answer set must fail closed here rather than reach the skill as an unroutable token.
        pend = rnd.get('pending')
        # The WRITER's domain, not the full answer vocabulary: record-return persists
        # only the three dispatch-* retry tokens (or None). A hand-corrupted
        # pending='proceed' would otherwise walk the orchestrator past an audit it
        # never received.
        if pend is not None and pend not in ('dispatch-embed-retry',
                                             'dispatch-retry-same-arm',
                                             'dispatch-inline-degraded'):
            raise StateError(f'round {num} names a pending action outside the canonical '
                             f'set: {pend!r}')
        # These per-round booleans DECIDE routing: the first two gate retries, while
        # `targeted_return_unusable` selects confirmation or the boundary election.
        # A hand-corrupted value must fail closed here for the same reason
        # `pending`/`findings_count`/`outcome` above do — a falsy-corrupted
        # `unreadable_retry_used` would admit a SECOND DRAFT-UNREADABLE re-dispatch,
        # breaching the "exactly one per round" bound (a fail OPEN this read boundary
        # exists to catch). The remaining flags feed the summary, so shape them too.
        for bkey in ('no_parseable_retry_used', 'unreadable_retry_used',
                     'degraded', 'consumer_dimensions_appended',
                     'targeted_return_unusable'):
            bval = rnd.get(bkey)
            if bval is not None and not isinstance(bval, bool):
                raise StateError(f'round {num} {bkey} {bval!r} is not a boolean')
        for mk in rnd.get('embed_markers', []):
            if mk not in _EMBED_MARKER_TOKENS:
                raise StateError(f'round {num} names an embed marker outside the '
                                 f'canonical set: {mk!r}')
        # issue #793 — the round KIND, validated here exactly as `arm` is, and for a
        # sharper reason than symmetry. `_round_kind` defaults an unrecognized value to
        # `discovery`, which is the PERMISSIVE direction: a corrupted kind would then
        # ground the clean scan, back the coverage axis and read as whole-draft evidence.
        # Defaulting is correct for an ABSENT field (a pre-#793 round genuinely was a
        # discovery round) but must never launder a PRESENT-but-unrecognized one, so the
        # read boundary refuses that here rather than leaving each reader to re-derive the
        # shape defensively. Same closed-set treatment `dispatch_regeneration` gets.
        rkind = rnd.get('kind')
        if rkind is not None and rkind not in _ROUND_KINDS:
            raise StateError(f'round {num} names a round kind outside the canonical '
                             f'set: {rkind!r} (expected one of {sorted(_ROUND_KINDS)})')
        # issue #1103 — the round-kind selecting reason, guarded here as fail-closed
        # write/read-boundary hygiene symmetric with `kind`: an off-vocabulary reason must
        # not persist through the state owner's own mutation loads. (Unlike `kind`, whose
        # downstream reader collapses the whole state on an unrecognized value, the eval's
        # `read_state` deliberately surfaces an unrecognized reason verbatim and names THIS
        # boundary as the one that refuses it — so this guard is the enforcement, not a
        # second reader re-checking.) An ABSENT reason is legal — a pre-#1103 round carries
        # none and its readers report UNESTABLISHED — so only a present, off-vocabulary
        # value raises.
        rkr = rnd.get('kind_reason')
        if rkr is not None and rkr not in _ROUND_KIND_REASONS:
            raise StateError(f'round {num} names a round-kind reason outside the '
                             f'canonical set: {rkr!r} (expected one of '
                             f'{sorted(_ROUND_KIND_REASONS)})')
        # The derived scope a targeted round was dispatched under. `claim_ids` is the sole
        # operand `_ingest_targeted_verdicts` reads, so a wrong-typed one would silently
        # ingest nothing and report every claim addressed.
        scope = rnd.get('scope')
        if scope is not None:
            if not isinstance(scope, dict):
                raise StateError(f'round {num} scope {scope!r} is not an object')
            cids = scope.get('claim_ids')
            if cids is not None and (not isinstance(cids, list)
                                     or not all(isinstance(c, str) for c in cids)):
                raise StateError(f'round {num} scope claim_ids {cids!r} is not a list '
                                 'of strings')
        # The per-claim verdict map. It decides which ledger entries a targeted return
        # reopens and whether the round reads as a clean sweep, so a corrupted map must
        # fail closed here rather than reaching those readers as though every claim came
        # back addressed.
        cv = rnd.get('claim_verdicts')
        if cv is not None:
            if not isinstance(cv, dict):
                raise StateError(f'round {num} claim_verdicts {cv!r} is not an object')
            for cid, val in cv.items():
                if not isinstance(cid, str) or val not in _CLAIM_VERDICTS:
                    raise StateError(
                        f'round {num} claim verdict {cid!r}={val!r} is outside the '
                        f'canonical set {sorted(_CLAIM_VERDICTS)}')
        # Post-adjudication payload (issue #548). T1, convergence, and the summary line
        # read these, so a hand-corrupted value must fail closed HERE — a bogus
        # adjudicated verdict or a negative count would otherwise reach the offer/convergence
        # decision as if established (unknown is not zero: an unestablished count is the
        # literal _UNESTABLISHED, never a coerced 0).
        av = rnd.get('adjudicated_verdict')
        if av is not None and av not in _ADJUDICATED_VERDICTS:
            raise StateError(f'round {num} names an adjudicated verdict outside the '
                             f'canonical set: {av!r}')
        for ckey in ('must_revise_count', 'advisory_count', 'invalid_count'):
            cval = rnd.get(ckey)
            if cval is not None and (not isinstance(cval, int) or isinstance(cval, bool)
                                     or cval < 0):
                raise StateError(f'round {num} {ckey} {cval!r} is not a non-negative '
                                 f'integer')
        umr = rnd.get('unresolved_must_revise')
        if umr is not None and umr != _UNESTABLISHED and (
                not isinstance(umr, int) or isinstance(umr, bool) or umr < 0):
            raise StateError(f'round {num} unresolved_must_revise {umr!r} is not a '
                             f'non-negative integer or the literal {_UNESTABLISHED!r}')
        # Re-assert the record-time verdict<->count agreement at the READ boundary, exactly as
        # the revision after_round<floor_round guard is re-checked here: cmd_record_adjudication
        # enforces FILE<=>0 / REVISE<=>>=1 and unresolved<=must_revise on write, but a
        # hand-corrupted state file must not smuggle a self-inconsistent payload (e.g.
        # adjudicated_verdict='FILE' with unresolved_must_revise=5) past that gate to reach
        # T1/convergence/summary as if established. Only enforce when both operands are present
        # and the count is settled — an _UNESTABLISHED count agrees with neither verdict and
        # (per the write path) can only accompany REVISE, which is checked too.
        if av is not None:
            if umr == _UNESTABLISHED and av == 'FILE':
                raise StateError(f'round {num} adjudicated verdict FILE cannot pair with an '
                                 f'{_UNESTABLISHED!r} unresolved must-revise count')
            if isinstance(umr, int) and not isinstance(umr, bool):
                if av == 'FILE' and umr != 0:
                    raise StateError(f'round {num} adjudicated verdict FILE disagrees with '
                                     f'unresolved_must_revise {umr} (FILE requires 0)')
                if av == 'REVISE' and umr < 1:
                    raise StateError(f'round {num} adjudicated verdict REVISE disagrees with '
                                     f'unresolved_must_revise {umr} (REVISE requires >= 1)')
                mrc = rnd.get('must_revise_count')
                if (isinstance(mrc, int) and not isinstance(mrc, bool)
                        and mrc >= 0 and umr > mrc):
                    raise StateError(f'round {num} unresolved_must_revise {umr} exceeds '
                                     f'must_revise_count {mrc} (unresolved is a subset)')
        # Per-finding ledger (issue #603). T1, convergence, query-findings and the summary
        # line all read these, so a hand-corrupted entry must fail closed HERE — a bogus
        # status or a resolution naming no recorded revision would otherwise reach the
        # convergence decision as if it were a verified fix.
        _validate_ledger(doc, rnd, num)
        # Per-dimension coverage (issue #708). The coverage derivation, the offer trigger,
        # and the summary line read these, so a hand-corrupted entry must fail closed HERE.
        _validate_coverage(rnd, num)
        # Per-finding advisory/invalid records (issue #743). The read-back, the calibration
        # derivation and trigger, and the summary line read these, so a hand-corrupted entry
        # must fail closed HERE rather than reach those surfaces as if established.
        _validate_adjudication_records(rnd, num)
    for ov in doc['overrides']:
        if not isinstance(ov, dict) or ov.get('kind') not in _OVERRIDE_KINDS:
            raise StateError('an override record names a kind outside the canonical set')
        surface = ov.get('surface')
        if surface is not None and surface not in _OVERRIDE_SURFACES:
            raise StateError(f'an override record names a surface outside the canonical '
                             f'set: {surface!r}')
        rao = ov.get('recorded_at_ordinal')
        if not isinstance(rao, int) or isinstance(rao, bool):
            raise StateError(f'an override record recorded_at_ordinal {rao!r} is not an '
                             f'integer')
        dd = ov.get('draft_digest')
        if dd is not None and (not isinstance(dd, str) or not dd):
            # Non-empty when present, mirroring the round `digest`/`body_digest` rule: an
            # empty bound digest would compare equal to an empty computed digest on the
            # override ground and ground eligibility on unaudited bytes (fail open).
            raise StateError('an override record draft_digest is not a non-empty string')
    # Read-surface fields the QUERIES consume must be shape-checked here too: a
    # corrupted revision record, counter, or creation record would otherwise crash a
    # query (AttributeError/TypeError), presenting a crashed read as a non-zero query
    # exit — the exact two-class-contract violation _validate exists to prevent.
    for i, rev in enumerate(doc['revisions']):
        if not isinstance(rev, dict):
            raise StateError('a revision record is not an object')
        for key in ('ordinal', 'after_round', 'floor_round'):
            val = rev.get(key)
            if not isinstance(val, int) or isinstance(val, bool):
                raise StateError(f'a revision record {key} {val!r} is not an integer')
        # revision_ordinal() is len(revisions); the stored ordinals must agree with it
        # (a 1..N chain) or the record tells a different story than the derivation.
        if rev['ordinal'] != i + 1:
            raise StateError(f'revision ordinal chain broken: position {i + 1} holds '
                             f'ordinal {rev["ordinal"]}')
        # Re-check record-revision's OWN guard at the read boundary, against the floor
        # that call recorded. `after_round` is the sole invalidation evidence on the
        # event-ordering ground (_revision_postdates keys eligibility and T2 on it), so a
        # value below the floor fails that guard OPEN — a revised, never-audited draft
        # answers eligible and emit-body emits it at exit 0. The write boundary refuses
        # that value, but this is the gate: a hand-corrupted record must not smuggle it
        # past, exactly as _valid_override re-checks its own write guards here.
        if rev['after_round'] < rev['floor_round']:
            raise StateError(
                f'revision {rev["ordinal"]} names after_round {rev["after_round"]} '
                f'below the floor {rev["floor_round"]} recorded with it (a value below '
                f'the last completed round fails the event-ordering staleness guard '
                f'open)')
        # issue #562: the revision bytes' stdin digest, when the revision was recorded
        # with its bytes. Non-empty-when-present (the round `digest` rule): the
        # post-revision `approve` ground compares it against a later landed dispatch
        # digest, and an empty one would compare equal to nothing meaningfully.
        sd = rev.get('stdin_digest')
        if sd is not None and (not isinstance(sd, str) or not sd):
            raise StateError(f'revision {rev["ordinal"]} stdin_digest is present but not '
                             f'a non-empty string')
    # issue #792: `final_byte_passes_used` joins the integer-shape check at the read
    # boundary, so a wrong-typed value is refused before any of its consumers reads it —
    # the coverage/trigger derivation, `record-dispatch`'s funding arithmetic, the
    # producer's ceiling refusal, and the refund. The `.get(key, 0)` default is what makes
    # the absent and valid-falsy-`0` shapes
    # both legal and identical: an unspent slot IS zero.
    for key in _ROUND_BUDGETS + (_FINAL_BYTE_REFUNDS_KEY,):
        val = doc.get(key, 0)
        if not isinstance(val, int) or isinstance(val, bool):
            raise StateError(f'{key} {val!r} is not an integer')
        if val < 0:
            raise StateError(f'{key} {val!r} is negative; a spend counter cannot be')
    # issue #792: the digest the final-byte slot is spent for. Absent/None = unspent.
    # Shape-checked like every other read-surface comparand: a non-string here would not
    # crash the `!=` comparison, it would silently answer "unspent" over a spent slot and
    # re-offer the pass against unchanged bytes.
    fbd = doc.get('final_byte_slot_digest')
    if fbd is not None and (not isinstance(fbd, str) or not fbd):
        raise StateError('final_byte_slot_digest is present but not a non-empty string')
    fbp = doc.get('final_byte_pending')
    if fbp is not None and not isinstance(fbp, bool):
        raise StateError(f'final_byte_pending {fbp!r} is not a boolean')
    # The per-round pass flag, read truthily by `_last_discovery_round`, `_final_byte_honoured`
    # and the refund. Shape-checked on the same rule as its document-level siblings: a truthy
    # non-boolean would silently mark an ordinary round as a pass and exclude it from both axis
    # selectors, which is a corrupted record reading as a decision rather than failing closed.
    for _r in doc['rounds']:
        fbf = _r.get('final_byte_pass')
        if fbf is not None and not isinstance(fbf, bool):
            raise StateError(f'round {_r.get("round")!r} final_byte_pass {fbf!r} is not a '
                             f'boolean')
        # The refund's OTHER comparand. Checked on the same rule and for the same reason as
        # `final_byte_slot_digest`: a non-string would not crash the `==`, it would silently
        # answer "different bytes" and skip the re-arm the refund just paid for.
        fbpd = _r.get('final_byte_pass_digest')
        if fbpd is not None and (not isinstance(fbpd, str) or not fbpd):
            raise StateError(f'round {_r.get("round")!r} final_byte_pass_digest {fbpd!r} is '
                             f'present but not a non-empty string')
    rf = doc.get('reinit_forced')
    if rf is not None and not isinstance(rf, bool):
        raise StateError(f'reinit_forced {rf!r} is not a boolean')
    creation = doc.get('creation')
    if creation is not None:
        if not isinstance(creation, dict):
            raise StateError('the creation record is not an object')
        # Shape-checked exactly like the sibling round/override/revision records. The
        # digest is the attestation's comparand: a non-string one does NOT crash the
        # compare, it silently loses it (`got == <non-str>` is False), so a corrupted
        # record would render a confident `attestation=mismatch` about a comparison
        # that never meaningfully happened — a guard failing open as misattribution
        # rather than closed. epoch_round/epoch_arm have no reader today, but they are
        # checked here on the same rule the sibling records follow: a later consumer
        # must inherit a validated record, not an unvalidated hole.
        digest = creation.get('body_only_digest')
        if not isinstance(digest, str) or not digest:
            raise StateError('the creation record body_only_digest is missing or not a '
                             'non-empty string')
        epoch_round = creation.get('epoch_round')
        # issue #1751: a decline-bound creation epoch has no round, so epoch_round is None
        # there; a round-bound epoch still records an integer.
        if epoch_round is not None and (not isinstance(epoch_round, int)
                                        or isinstance(epoch_round, bool)):
            raise StateError(f'the creation record epoch_round {epoch_round!r} is not an '
                             f'integer or None')
        epoch_arm = creation.get('epoch_arm')
        if epoch_arm not in _ARMS:
            raise StateError(f'the creation record names an epoch arm outside the '
                             f'canonical set: {epoch_arm!r}')
        att = creation.get('attestation')
        if att is not None and att not in _ATTESTATIONS:
            raise StateError(f'the creation record names an attestation status outside '
                             f'the canonical set: {att!r}')
    # issue #562: the tiered draft-root binding. Read by the digest/eligibility/
    # body-emission operations and by the binding/summary queries, so a hand-corrupted
    # record must fail closed HERE (a named breadcrumb collapsing the whole state to
    # unestablished), never surface later as a KeyError/AttributeError in a query that
    # is contractually always-exit-0.
    binding = doc.get('draft_binding')
    if binding is not None:
        if not isinstance(binding, dict):
            raise StateError('the draft_binding record is not an object')
        if not _is_bound_path(binding.get('path')):
            raise StateError('the draft_binding record path is missing or not an '
                             'absolute, single-line string')
        if binding.get('tier') not in _DRAFT_TIERS:
            raise StateError(f'the draft_binding record names a tier outside the '
                             f'canonical set: {binding.get("tier")!r}')
        nbr = binding.get('non_bound_root')
        # Absent (recorded None) is legal — the breadcrumb/no-answer/failed-.git-test
        # arm records no non-bound root; present-but-non-absolute is corrupt.
        if nbr is not None and not _is_bound_path(nbr):
            raise StateError('the draft_binding record non_bound_root is present but not '
                             'an absolute, single-line string')
    # issue #562: the canonical-write-failure log at the bound path. Each entry names the
    # revision ordinal whose overwrite failed (an int) — a bare integer list is enough
    # for the post-revision `approve` ground, which only asks "did the latest revision's
    # overwrite land".
    # issue #793 — the durable byte history. `_staged_artifacts` silently SKIPS a
    # malformed record (correct for a best-effort read), so without a boundary check a
    # corrupted history degrades to "no history", which selects `discovery` — safe, but
    # silently, and the operator never learns the history was corrupt. Refuse the wrong
    # SHAPE here and let the per-record skip handle only genuine partial data.
    sp = doc.get('staged_paths')
    if sp is not None:
        if not isinstance(sp, list):
            raise StateError(f'staged_paths is not a list (found {type(sp).__name__})')
        for i, rec in enumerate(sp, start=1):
            if not isinstance(rec, dict):
                raise StateError(f'staged_paths entry {i} is not an object')
    wf = doc.get('write_failures')
    # Absent is legal (a pre-binding or legacy record has none); present-but-non-list is
    # corrupt and fails closed like every other read-surface field.
    if wf is not None:
        if not isinstance(wf, list):
            raise StateError(f'write_failures is not a list (found {type(wf).__name__})')
        for entry in wf:
            if not isinstance(entry, int) or isinstance(entry, bool):
                raise StateError(f'a write_failures entry {entry!r} is not an integer')
    _validate_finding_evidence(doc)
    return doc


def validate_state_document(doc, slug):
    """Validate an in-memory state document through the complete owner boundary.

    Raises StateError on every untrustworthy shape. Returns the SAME object it was
    handed, not a copy — a caller that must not alias the validated document copies
    it itself.
    """
    return _validate(doc, slug)


def load_state(slug, root=None):
    """Load and validate. Raises StateError for every untrustworthy shape."""
    path = state_path(slug, root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise StateError(f'no state file at {path}; run init first') from exc
    except OSError as exc:
        raise StateError(f'state file at {path} is unreadable: {exc}') from exc
    if not raw.strip():
        raise StateError(f'state file at {path} is present but empty')
    try:
        doc = json.loads(raw.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StateError(f'state file at {path} is not parseable JSON: {exc}') from exc
    return _validate(doc, slug)


def save_state(doc, slug, root=None):
    """Persist atomically. Raises StateError when the state cannot be persisted."""
    path = state_path(slug, root)
    # Re-validate at the construction boundary: a mutation bug that assembled an
    # invalid document fails HERE, loudly, instead of persisting silently and
    # collapsing the whole file to unestablished at the next load.
    _validate(doc, slug)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Per-writer temp path (issue #1040): tempfile.mkstemp gives each writer a UNIQUE
        # temp name in the state file's own directory, so two concurrent writers never
        # share and truncate one deterministic path. The '.json.tmp' suffix is retained so
        # the existing #546 cleanup glob('*.json.tmp') still selects it. mkstemp sits inside
        # this try and below the mkdir: unlike the pure path computation it replaces it
        # touches the filesystem, so every OSError it raises (a missing parent, a read-only
        # filesystem, a permission denial, an exhausted disk) surfaces as the same
        # could-not-persist StateError below. mkstemp creates at 0600 and os.replace carries
        # that mode onto the state file — the decided per-user-artifact mode on POSIX.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.',
                                   suffix='.json.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(doc, indent=2, sort_keys=True) + '\n')
            # os.replace retried over PermissionError only (the Windows lock-free-reader
            # sharing violation); every other OSError propagates on the first attempt.
            _replace_with_retry(tmp, path)
        except OSError:
            # Best-effort cleanup of the partial temp file so a failed persist never leaves
            # a stray .json.tmp in the evidence-bearing tmp directory.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise StateError(f'could not persist state to {path}: {exc}') from exc
    return path


def _check_nonce(doc, nonce):
    if nonce != doc['nonce']:
        raise StateError(
            'nonce mismatch — this call does not belong to the run that owns this '
            f'state file (passed {nonce!r})')


# ── Pure decision functions ────────────────────────────────────────────────────

def classify_return(arm, verdict, has_verdict_line, carriage_ok):
    """Classify an auditor return. Retry precedence is fixed and lives here.

    A return that is both unreadable-prose and verdict-less is classified by the
    ABSENT VERDICT LINE — the absent line is tested before any arm/verdict rule, so
    the precedence cannot be reordered by accident. Absent carriage evidence is
    treated exactly like mismatched evidence.
    """
    if not has_verdict_line or verdict is None:
        return 'no-parseable-verdict'
    if verdict not in _VERDICTS:
        return 'no-parseable-verdict'
    if verdict == 'DRAFT-UNREADABLE':
        # Carriage evidence is not applicable: the auditor is reporting it could not
        # read the draft at all, so it has nothing to quote.
        return _legality(arm, verdict)
    if not carriage_ok:
        return 'no-parseable-verdict'
    return _legality(arm, verdict)


def _legality(arm, verdict):
    for r in TRANSITIONS:
        if r['condition'] == 'verdict-on-arm' and r['arm'] == arm and r['verdict'] == verdict:
            if r['result'] not in _CLASSIFICATIONS:
                raise AssertionError(
                    f'issue-audit-state: the verdict-on-arm row for arm={arm!r} '
                    f'verdict={verdict!r} names {r["result"]!r}, which is not a return '
                    f'classification in _CLASSIFICATIONS')
            return r['result']
    raise KeyError(f'no transition row for arm={arm!r} verdict={verdict!r}')


def completed_rounds(state):
    return [r for r in state['rounds'] if r.get('outcome') is not None]


def last_completed(state):
    done = completed_rounds(state)
    return done[-1] if done else None


def revision_ordinal(state):
    return len(state['revisions'])


def _revision_postdates(state, rnd):
    return any(rev.get('after_round', 0) >= rnd['round'] for rev in state['revisions'])


def _unresolved_int(rnd):
    """The round's adjudicated unresolved-must-revise count as a concrete int, else None.

    The count is meaningful ONLY post-adjudication, so a round whose `adjudicated_verdict`
    is absent has no established count regardless of any stored `unresolved_must_revise`
    value: `None` is returned first on that path. Keying on the verdict here — not solely on
    the count field — closes a co-presence gap a hand-corrupted state could open: a completed
    REVISE round hand-edited to carry `adjudicated_verdict = None` with a settled
    `unresolved_must_revise` of 0 would otherwise return that 0 as established, making T1 read
    it clean AND the `unadjudicated-round` T2 arm (guarded on `u is None`) NOT fire — the exact
    silent boundary-offer drop that arm exists to prevent (issue #548 re-review). Deriving
    "is the count established" from the verdict makes T1, the `unadjudicated-round` T2 arm, and
    `evaluate_convergence` (which already gates on `adjudicated_verdict` first) agree that a
    count without a verdict is unestablished — the write path never emits that pairing (an
    un-adjudicated round carries a `None` count), so the guard bites only corruption.

    Past that early return the round is adjudicated, and `None` still covers every remaining
    case that is NOT a settled integer: a round adjudicated but unestablished (the literal
    `_UNESTABLISHED`), or a stored `None`/non-int count. (A never-adjudicated round carries a
    `None` verdict, so it is caught by the early return above, not here.) A bool is not an int
    here (Python's `isinstance(True, int)` is True), so it is excluded explicitly. Non-negativity
    is enforced upstream by `_validate` (and by `cmd_record_adjudication` at the write boundary),
    so any stored int reaching here is already >= 0.
    """
    if rnd.get('adjudicated_verdict') is None:
        return None
    v = rnd.get('unresolved_must_revise')
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


# ── The per-finding ledger and the effective unresolved count (issue #603) ────────

def _ledger(rnd):
    """The round's per-finding ledger as a list, or None when the round carries none.

    A ledger is recorded only on a round adjudicated REVISE with a SETTLED count. A FILE
    round, a `REVISE … unestablished` round, and every pre-change round in an older state
    file are ledger-less — `None`, never an empty list, so callers can distinguish
    "no ledger" from "a ledger with nothing on it".
    """
    led = rnd.get('findings')
    return led if isinstance(led, list) else None


def _all_entries(state):
    """Every recorded ledger entry in the run, as `(round, entry)` pairs.

    The single run-wide traversal. Several consumers walk the ledgers, and stating "what
    is a ledger, and which rounds contribute" once here is what keeps them from drifting
    apart as the status set grows.
    """
    for rnd in state['rounds']:
        for entry in (_ledger(rnd) or []):
            yield rnd, entry


def _provenance_ordinal(value):
    """A provenance stamp as a comparable ordinal, or None when it names none.

    The `pre-revision` token counts as ordinal 0, so a stamp made before any revision
    existed is correctly older than every recorded revision.
    """
    if value == _PRE_REVISION:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _settling_ordinal(entry):
    """The revision ordinal an entry's post-close settling change was verified against.

    Only a post-close-settled entry has one: `resolved` (via record-resolution, or the
    ingestion provenance, which predates every revision) or `invalidated`. Stamps are
    compared through `_provenance_ordinal`, which owns the `_PRE_REVISION`-is-ordinal-0
    rationale. Returns None for an entry that is not post-close-settled (`unresolved`, and `superseded`, which rests on
    the auditor's own FILE verdict rather than on a self-attested change).
    """
    status = entry.get('status')
    if status == 'resolved':
        if entry.get('ingest_provenance') == _LEDGER_INGESTED_RESOLVED:
            return 0
        ordinal = entry.get('resolution_ordinal')
    elif status == 'invalidated':
        ordinal = entry.get('invalidation_provenance')
    else:
        return None
    return _provenance_ordinal(ordinal)


def _effective_unresolved(state):
    """The RUN-WIDE effective unresolved-must-revise count, or None when unestablished.

    The count is the number of ledger entries still `unresolved` across EVERY recorded
    ledger — resolved, invalidated, and superseded entries excluded — plus the latest
    completed round's adjudicated count when that round is REVISE-adjudicated but carries
    no ledger. That passthrough is what keeps a pre-change state file behaving exactly as
    it does today.

    Establishedness is delegated wholesale to `_unresolved_int` on the latest completed
    round, so this derivation returns None in exactly the places that one does (an
    un-adjudicated round, an `unestablished` count, a non-int count) and the
    `unadjudicated-round` T2 arm keeps its comparand. Unknown is not zero: a ledger that
    happens to sum to 0 never launders an unestablished latest round into a clean answer.

    Disclosed limitation, mandated by AC5: only the LATEST completed round's count is
    passed through, so unresolved findings from any **earlier** ledger-less round are
    invisible to the aggregate. Two distinct shapes reach that state, and the second is
    NOT a migration artifact — do not read this as legacy-only:
      * a PRE-CHANGE earlier round, written before ledgers existed; and
      * a post-change round adjudicated `REVISE` with an `unestablished` count, which
        `cmd_record_adjudication` accepts WITHOUT a ledger (the `--ledger-file`
        requirement is keyed on a SETTLED count), and which stops being the latest
        completed round as soon as a further round completes.
    So a run whose earlier round holds unestablished findings can report `converged=yes
    basis=resolution` once a later ledgered round settles. AC5 fixes this passthrough
    ("returns not-established exactly where `_unresolved_int` does today"), so the
    boundary is stated rather than silently widened here; re-auditing re-surfaces a
    genuinely unfixed defect onto a later ledgered round, which bounds the residual.
    """
    # issue #793 — DECIDED treatment: the seed is the latest WHOLE-DRAFT round. A
    # `targeted` round records no adjudication and no ledger of its own, so seeding from it
    # made `_unresolved_int` answer None and the run-wide count read unestablished the
    # moment a scoped round completed — turning a mechanism meant to reduce rounds into one
    # that erased the count driving convergence.
    last = _last_discovery_round(state)
    if last is None:
        return None
    frozen = _unresolved_int(last)
    if frozen is None:
        return None
    total = sum(1 for _, entry in _all_entries(state)
                if entry.get('status') == 'unresolved')
    if last.get('adjudicated_verdict') == 'REVISE' and _ledger(last) is None:
        total += frozen
    return total


def _convergence_basis(state, converged):
    """The basis token for a convergence answer, keyed on the LATEST accepted adjudication.

    `adjudicated` when the latest completed round is FILE-adjudicated — the auditor's own
    verdict vouches for the state, including everything that round superseded.
    `resolution` when the latest completed round is REVISE-adjudicated and the effective
    count reached zero through post-close status changes, and `resolution-stale` when any
    post-close-settled entry's settling provenance ordinal is BELOW the latest recorded
    revision ordinal — staleness judged PER ENTRY, so an interleaved
    resolve → revise → resolve run stays stale on the earlier entry's account, whose
    verification predates the intervening revision. `none` on every not-converged answer.

    Keying on the latest accepted adjudication rather than on the mere existence of
    post-close records is load-bearing: because a REVISE adjudication requires an
    unresolved count of at least 1, every ledger carries an unresolved entry at ingestion,
    so an existence-keyed rule would make `adjudicated` unreachable on any run that ever
    went REVISE.
    """
    if not converged:
        return 'none'
    # issue #793 — DECIDED treatment: `adjudicated` is a claim that an AUDITOR's whole-draft
    # verdict vouches for the state, so it is read off the latest WHOLE-DRAFT round. A
    # `targeted` round vouches only for the claims it re-checked over the span it was
    # scoped to, so reporting `basis=adjudicated` from one would attribute whole-draft
    # authority to a round that never read the whole draft.
    last = _last_discovery_round(state)
    if last is not None and last.get('adjudicated_verdict') == 'FILE':
        return 'adjudicated'
    latest_revision = revision_ordinal(state)
    for _, entry in _all_entries(state):
        settled_at = _settling_ordinal(entry)
        if settled_at is None:
            continue
        if settled_at < latest_revision:
            return 'resolution-stale'
        # A reopen RECORDS that the entry's previous settling did not hold, so re-settling it
        # against the very same (already-disproven) ordinal is not fresh evidence. Without
        # this, reopen -> re-resolve on the same ordinal converges on a plain `resolution`
        # basis and the reopen — the run's own contradiction of that ordinal — never reaches
        # the currency judgment.
        reopened_at = _provenance_ordinal(entry.get('reopen_provenance'))
        if reopened_at is not None and settled_at <= reopened_at:
            return 'resolution-stale'
    return 'resolution'


# ── Draft-root binding (issue #562) ──────────────────────────────────────────────

def _binding(state):
    """The recorded draft-root binding dict, or None when no write has bound one yet."""
    return (state or {}).get('draft_binding')


def _bound_path(state):
    """The absolute bound draft ROOT, or None when unbound. `_validate` proved it
    absolute at load. This is the root the display and `bound_root` report and the tier
    token classifies — NOT the draft file itself (see `_bound_draft_file`)."""
    b = _binding(state)
    return b['path'] if b else None


def _bound_draft_file(state, slug):
    """The absolute bound canonical draft FILE, or None when unbound.

    The binding records the bound *root* (`_bound_path`); the canonical draft file is
    that root joined with the fixed `.prflow/tmp/spec/<slug>/issue-draft-<slug>.md` subpath — the
    same path the skill writes and displays. The digest / eligibility / body-emitting
    readers resolve THIS from the recorded binding so a compacted context that hands a
    drifted `--draft-file` cannot redirect them; they fall back to the caller-supplied
    `--draft-file` only on an unbound run.
    """
    root = _bound_path(state)
    if root is None:
        return None
    return str(Path(root) / '.prflow' / 'tmp' / 'spec' / slug / f'issue-draft-{slug}.md')


def latest_revision_landed(state):
    """Three-way token for whether the latest revision's bytes landed at the bound path.

    Returns one of `'yes'` / `'no'` / `'unestablished'` (issue #1841 widened this from a
    boolean so the proven-failed arm and the cannot-prove arm stop sharing `'no'`):
      - `'yes'` — vacuously when no revision is recorded (nothing is unlanded), or when a
        **subsequent** recorded landed write at the bound path (a round-initiating file-arm
        dispatch record qualifies) carries a digest equal to the latest revision's recorded
        stdin digest — the clearing predicate that lets a recovered run re-enter the full
        file-arm contract (issue #562).
      - `'no'` — a recorded overwrite failure for the latest revision's ordinal proves the
        bytes did not land.
      - `'unestablished'` — the recorded state proves neither: no write-failure, but no
        subsequent matching dispatch to prove landing (the common `basis=resolution`
        terminal path), or the latest revision carries no stdin digest to match on.

    Two fail-closed conditions, both load-bearing:
      - A recorded overwrite failure for the latest revision (its ordinal in
        `write_failures`) means the bound file does NOT hold the revised bytes, so the
        revision has NOT landed — even if its stdin digest coincidentally equals some
        earlier audited dispatch's digest (the user revised back to bytes a prior round
        already saw). Without this the write-failure log and this predicate would be
        disconnected and a known-failed write could still read as landed. This check is
        deliberately checked BEFORE the clearing scan, so a recorded write-failure is
        **terminal for that ordinal**: the general clearing clause above does NOT re-fire
        for it — not even a genuinely subsequent matching dispatch clears a write-failed
        ordinal (the flag stays `not landed` until a *fresh* revision without a recorded
        failure supersedes it). This flag governs presentation source only; the `approve`
        eligibility ground recovers independently through its fresh-clean-round staleness
        gate (`_revision_postdates`): a subsequent clean round that no revision postdates
        re-enables the eligibility ground, so a recovered run still re-enters file-sourced
        creation there even while this flag stays conservatively `not landed`.
      - The matching dispatch must be **subsequent** — recorded in a round whose number
        is greater than the revision's `after_round` — so a *predating* dispatch that
        happens to share the digest never satisfies the clearing predicate. A revision
        with NO stdin digest (a legacy/embed-epoch revision) cannot be proven landed and
        reports `'unestablished'`, the conservative presentation choice — as does a latest
        revision with a digest but no subsequent matching dispatch.
    """
    revs = state['revisions']
    if not revs:
        return 'yes'
    latest = revs[-1]
    # The latest revision's ordinal is len(revs) (the 1..N chain). A recorded overwrite
    # failure for it PROVES it never landed -> 'no' (terminal for the ordinal, checked
    # before the clearing scan so a later matching dispatch never clears it).
    if len(revs) in (state.get('write_failures') or []):
        return 'no'
    want = latest.get('stdin_digest')
    if not want:
        return _UNESTABLISHED
    after = latest.get('after_round', 0)
    for rnd in state['rounds']:
        if rnd['round'] <= after:
            continue  # only a write recorded AFTER the revision proves it landed
        for att in rnd['attempts']:
            if att['arm'] == 'file' and att.get('digest') == want:
                return 'yes'
    return _UNESTABLISHED


def evaluate_triggers(state):
    """T1/T2, evaluated from recorded state.

    T1 (issue #548, comparand widened by #603) consumes the RUN-WIDE EFFECTIVE unresolved
    must-revise count (`_effective_unresolved`) — never the raw `VERDICT: REVISE` token, and
    no longer the count frozen at the latest completed round's close: it holds only when at
    least one unresolved must-revise finding remains across every recorded ledger (a settled
    count ≥ 1). An un-adjudicated or unestablished count does NOT hold T1 — a *verified*
    finding is required.
    T2 provides the fail-closed unknown-state coverage: it holds when a revision record
    postdates the last completed round's record; when the last completed round hit the
    verdict-less (`no-verdict`) terminal (the content is effectively unaudited); when a
    completed **REVISE** round's post-adjudication unresolved-must-revise count (this arm's own
    comparand — T1 itself reads the effective count since #603) is absent — whether the round was never adjudicated OR was adjudicated with an `unestablished`
    count (the pre-#548 raw-REVISE token fired the offer, so either low-evidence path must not
    silently drop it — the offer fires rather than being skipped, exactly the absent-comparand
    fail-closed the guard would otherwise fail open on); when an unusable targeted return has
    exhausted its dedicated whole-draft confirmation capacity; and whenever state is
    unestablishable (unknown is not zero). A naming `reason` is surfaced on the fail-closed
    arms that need one — `state-unestablished`, `no-verdict-round`, `unadjudicated-round`,
    `targeted-return-unusable`, and (issue #709) `steering-unestablished` — and is `None` when T2
    holds purely because a revision postdates a known, audited last round WHOSE steering-absence
    was established (the offer fires, but there is no anomaly to name). An un-adjudicated *FILE*
    round is none of the pre-#709 arms — its raw
    signal is clean and pre-#548 it fired no offer — so T2's behavior on it is unchanged EXCEPT
    where its steering-absence was not established, which is exactly what the #709 arm below
    names (the Quiet-Killer case: a clean round whose independence could not be established
    would otherwise withhold the clean ground with no user-facing offer).
    """
    if state is None:
        return {'t1': False, 't2': True, 'coverage': False, 'calibration': False,
                'reason': 'state-unestablished'}
    last = last_completed(state)
    if last is None:
        return {'t1': False, 't2': False, 'coverage': False, 'calibration': False,
                'reason': None}
    u = _unresolved_int(last)
    # issue #603: T1's comparand is the RUN-WIDE EFFECTIVE count, so a round whose ledger
    # entries the drafter verified fixed (or retired as invalid, or that a FILE re-audit
    # superseded) releases the trigger instead of holding it forever on a count frozen at
    # round close. `_effective_unresolved` delegates establishedness to `_unresolved_int`,
    # so it is None in exactly the same places — the `unadjudicated-round` T2 arm below
    # keeps reading `u` and its behavior is unchanged.
    eff = _effective_unresolved(state)
    t1 = eff is not None and eff >= 1
    t2 = _revision_postdates(state, last)
    reason = None
    if _targeted_return_unusable(last):
        # Confirmation owns this state while its slot remains; only exhaustion exposes
        # the disclosed election. Do not fall through to generic REVISE routing.
        if state.get('confirming_rounds_used', 0) >= _MAX_CONFIRMING_ROUNDS:
            t2 = True
            reason = 'targeted-return-unusable'
    elif last.get('outcome') == 'no-verdict':
        # The verdict-less terminal: T1 does not hold (there is no adjudicated must-revise
        # finding on an unaudited round), but the content is effectively unaudited, so T2 is
        # treated as holding and the boundary offer fires naming the state.
        t2 = True
        reason = 'no-verdict-round'
    elif last.get('outcome') == 'REVISE' and u is None:
        # A completed REVISE round whose POST-ADJUDICATION unresolved-must-revise count (this
        # arm's own comparand since #603 — T1 now reads the effective count) is absent — `_unresolved_int` returned None. That covers BOTH low-evidence
        # paths: the round was never adjudicated (`adjudicated_verdict is None`), OR it was
        # adjudicated with the literal `unestablished` count (a legal REVISE+unestablished
        # pairing `cmd_record_adjudication`/`_validate` both accept). Pre-#548 the raw REVISE
        # token fired T1 unconditionally, so on EITHER path the boundary offer would be SILENTLY
        # dropped without this arm — a guard failing open on exactly the unknown-count path it
        # exists to catch (unknown is not zero). Fail closed to the offer and surface the reason.
        # A clean FILE round left un-adjudicated is deliberately NOT this case (pre-#548 it fired
        # no offer either); a REVISE round adjudicated with a settled count >= 1 is caught by T1
        # above (u is not None), never here.
        t2 = True
        reason = 'unadjudicated-round'
    elif last.get('outcome') in ('FILE', 'REVISE') and not _steering_established(last):
        # issue #709 — the "Quiet Killer" arm. A round that returned `VERDICT: FILE` with
        # zero findings and no revision fires NONE of the arms above: T1 needs an
        # unresolved must-revise finding, and the two T2 arms above need a verdict-less or
        # an unadjudicated-REVISE round. So without this arm a steered-or-unestablished
        # clean round would withhold the clean ground SILENTLY, with no user-facing offer
        # to restore a verified-independent audit. Firing T2 routes it through the
        # existing boundary-offer surface, which never blocks filing: on decline the run
        # proceeds to presentation with the state disclosed.
        t2 = True
        reason = 'steering-unestablished'
    # issue #743: the calibration disclosure trigger is a never-blocking sibling of T1/T2 and
    # coverage on the SAME boundary offer, so it rides this one evaluation rather than a
    # second call the printer concatenates (the one-producer discipline).
    return {'t1': t1, 't2': t2, 'coverage': evaluate_coverage_trigger(state),
            'calibration': evaluate_calibration_trigger(state), 'reason': reason}


def _offer_withhold_reason(state):
    """The reason an accepted user audit round is WITHHELD, or None when it is not (issue #548).

    An adjudicated discovery REVISE round's unresolved must-revise findings must reach the
    draft before another audit is funded, so `record-offer --accepted` (and the Step 4 3a
    audit-round option it grounds) is withheld while the run's effective unresolved
    must-revise count holds (>= 1) and no revision record postdates the discovery round that
    raised those findings (`unresolved-revise-pending`). It fails closed — withholding
    `unestablished` — when that latest discovery round is adjudicated REVISE but its
    unresolved count is unestablished (the `unestablished` adjudication, which records no
    ledger), because unknown is not zero.

    The gate is scoped to a latest discovery round that is ADJUDICATED REVISE: an
    un-adjudicated round has raised no established findings yet (the round-funding gate, not
    this withhold, owns that mid-flow state), and a FILE round left nothing unresolved. The
    withhold is also NARROWER than T1: a revision postdating the raising round releases it
    even before the ledger entries are marked resolved, so the T2-after-revision offer on
    self-verified-but-not-re-audited bytes still fires. With no completed discovery round
    nothing has been raised, so the discovery-funding offer is never withheld — this must
    return None there or the first-ever audit round could never be funded.

    The single source of the withhold decision AND its reason token, so `_offer_withheld`
    and `_offer_line` never re-walk the ledger to re-derive one from the other.
    """
    raising = _last_discovery_round(state)
    if raising is None or raising.get('adjudicated_verdict') != 'REVISE':
        return None
    eff = _effective_unresolved(state)
    if eff is None:
        return 'unestablished'
    if eff < 1:
        return None
    if _revision_postdates(state, raising):
        return None
    return 'unresolved-revise-pending'


def _offer_withheld(state):
    """Whether an accepted user audit round must be withheld (issue #548) — the boolean
    view of `_offer_withhold_reason`."""
    return _offer_withhold_reason(state) is not None


def evaluate_convergence(state):
    """Whether the run has converged (issue #548).

    A converged run is one with ZERO effective unresolved must-revise axis-attributable
    findings — either because its final accepted, post-adjudication verdict is
    `VERDICT: FILE` (basis `adjudicated`), or because every recorded ledger entry was
    settled post-close by a self-verified resolution or invalidation (basis `resolution`,
    or `resolution-stale` when a later revision postdates an entry's verification).
    Advisory and invalid/unverified findings do not block convergence. A final round that
    is un-adjudicated, or whose unresolved-must-revise count is unestablished, is NOT
    converged (unknown is not zero); unestablishable state is not converged either.

    Budget legality is NOT read here and never was — it is enforced upstream at round
    funding (`_MAX_AUTOMATIC_REAUDITS` / `_USER_ROUND_CAP`); the pre-#603 wording claimed
    a budget clause this function does not compute (issue #603 AC7).
    """
    if state is None:
        return {'converged': False, 'reason': 'state-unestablished', 'basis': 'none',
                'effective': None}
    last = last_completed(state)
    if last is None:
        return {'converged': False, 'reason': 'no-completed-round', 'basis': 'none',
                'effective': None}
    if _targeted_return_unusable(last):
        # A scoped return whose per-claim block was unusable established nothing. Name
        # that durable fact directly instead of collapsing it into generic missing
        # adjudication; old records carry no flag and keep their historical answer.
        return {'converged': False, 'reason': 'targeted-return-unusable',
                'basis': 'none', 'effective': None}
    adjudicated = last.get('adjudicated_verdict')
    if adjudicated is None:
        return {'converged': False, 'reason': 'unadjudicated', 'basis': 'none',
                'effective': None}
    eff = _effective_unresolved(state)
    if eff is None:
        # Adjudicated but the count is the literal _UNESTABLISHED (or otherwise not a
        # settled int): unknown is not zero, so this is not a converged run.
        return {'converged': False, 'reason': 'unresolved-unestablished',
                'basis': 'none', 'effective': None}
    # issue #603: the count is the run-wide EFFECTIVE one, so a REVISE-latest run whose
    # ledgers were all settled post-close converges too — reported on a basis token that
    # keeps it distinguishable from an auditor-accepted FILE convergence.
    converged = eff == 0
    # `effective` rides along so a caller wanting BOTH the count and the basis — the
    # summary line does — derives them from ONE evaluation. Two independent call sites
    # could otherwise render two fields describing different states.
    return {'converged': converged,
            'reason': None if converged else 'unresolved-must-revise-remain',
            'basis': _convergence_basis(state, converged),
            'effective': eff}


def _coverage_round(state):
    """The final accepted round coverage-backing derives from, or None.

    Coverage attaches ONLY to a run whose final accepted round is a clean auditor
    `VERDICT: FILE` (issue #708): a no-clean-round convergence (the resolution-basis /
    resolution-stale path) carries no per-dimension coverage, so it derives
    `unestablished`. `last_completed` is the run's final accepted round; it is a
    coverage round only when its outcome is `FILE`.

    issue #792: "the run's final accepted round" excludes a final-byte exact-byte pass —
    see `_last_discovery_round` for why an accepted pass must not retire this
    axis. A run with no pass takes the identical answer, since the selector then reduces
    to `last_completed`.
    """
    if state is None:
        return None
    last = _last_discovery_round(state)
    if last is None or last.get('outcome') != 'FILE':
        return None
    return last


def evaluate_coverage(state):
    """The run's coverage-backing, derived from the final accepted clean round (issue #708).

    Returns `{'backing': <token>, 'render': <token>}`:
      - `backing` in `_COVERAGE_BACKINGS`. `backed` only when the final accepted round is
        a clean `FILE` round carrying a recorded coverage list in which EVERY entry is
        `exercised` or `valid-N/A`; `not-backed` when any surviving `skipped`/`unestablished`
        entry remains on that otherwise-clean round; `unestablished` when there is no clean
        auditor round to carry coverage, or the clean round recorded no coverage at all
        (unknown is never collapsed onto backed).
      - `render` in `('full', 'degraded', 'none')` — the coverage round's recorded render
        state, or `none` when there is no coverage round. A `degraded` render discloses but
        does not fire the coverage offer (that is the trigger's job).

    Coverage-backing is a DISTINCT axis from convergence: it never redefines
    `evaluate_convergence`, never gates `emit-body`/`query-eligibility`. Its only teeth are
    the coverage offer trigger.
    """
    if state is None:
        # The state could not be established at all (unreadable/corrupt — including a
        # `_validate_coverage` raise). Byte-identical to the two BENIGN unestablished arms
        # below unless the cause rides on the answering line, which is how a corrupt file
        # reads as "no coverage round yet" — so each arm names its own reason.
        return {'backing': 'unestablished', 'render': 'none', 'round': None,
                'reason': 'state-unestablished'}
    rnd = _coverage_round(state)
    if rnd is None:
        return {'backing': 'unestablished', 'render': 'none', 'round': None,
                'reason': 'no-clean-round'}
    coverage = rnd.get('coverage')
    if not coverage:
        # A clean round that recorded no coverage: unknown is not backed.
        return {'backing': 'unestablished', 'render': 'none', 'round': rnd,
                'reason': 'no-coverage-recorded'}
    backed = all(e.get('outcome') in _COVERAGE_BACKING_OUTCOMES for e in coverage)
    backing = 'backed' if backed else 'not-backed'
    # The closed backing vocabulary is asserted, not merely documented: a token typo'd
    # here would otherwise ship green, since nothing downstream re-checks it.
    assert backing in _COVERAGE_BACKINGS
    return {'backing': backing, 'render': rnd.get('coverage_render') or 'full',
            'round': rnd, 'reason': None}


def evaluate_coverage_trigger(state):
    """Whether the coverage offer trigger holds (issues #708, #1694).

    A sibling of T1/T2, routed through the existing offer machinery and the existing
    user-round cap. It fires on two grounds, both a clean `FILE` round whose mandated
    per-dimension coverage did not survive as evidence, recoverable by another audit round:

      - a genuinely-unbacked FULL-render clean audit — a `skipped`/empty/generic-adjudicated
        anchor on a dimension the auditor DID render (`not-backed` + `full`); and
      - a clean `FILE` round that recorded NO coverage at all (issue #1694), which
        `evaluate_coverage` reports as `unestablished`/`none`/`no-coverage-recorded`.

    Everything else stays disclosure-only: a legitimately narrowed (`degraded`) render
    CARRYING RECORDED COVERAGE discloses but never fires, so a consumer whose auditor takes
    a fallback rung is not offered-at every run — an EMPTY coverage list is the
    `no-coverage-recorded` arm whatever render token sits beside it, because
    `evaluate_coverage` tests emptiness before it reads the render. The OTHER
    `unestablished` reasons — no clean round (`no-clean-round`) and unreadable/corrupt/
    foreign state — never fire either. Filing is never blocked by this trigger.
    """
    cov = evaluate_coverage(state)
    return (cov['backing'] == 'not-backed' and cov['render'] == 'full') \
        or cov['reason'] == 'no-coverage-recorded'


def _final_byte_round(state):
    """The newest completed FILE-ARM VERDICT-BEARING round, or None (issue #792).

    Deliberately not `last_completed`: the axis reports what the engine would GROUND on,
    and `_clean_identity`'s byte-identity test reads a recorded dispatch digest solely
    under `attempts[-1]['arm'] == 'file'`. Reading the run's latest completed round
    instead would let a pass whose pre-dispatch write failed — and therefore landed on
    the embed arm — downgrade a known `uncovered` to `unestablished` and consume the slot
    on a read-only host, which is the one degradation the offer must survive.

    `no-verdict` rounds are skipped rather than terminating the scan: an inconclusive
    round is not a verdict about the bytes, so it neither establishes nor revokes
    coverage. A newer verdict-bearing REVISE on another arm DOES revoke, but that
    revocation is applied by the derivation below rather than by this selector, which
    answers one question only — which round carries the arm and digest terms.
    """
    if state is None:
        return None
    for rnd in reversed(completed_rounds(state)):
        if rnd.get('outcome') not in _VERDICT_BEARING_OUTCOMES:
            continue
        if rnd['attempts'][-1]['arm'] == 'file':
            return rnd
    return None


def _final_byte_revoked(state, rnd):
    """True when a verdict-bearing round NEWER than `rnd` closed REVISE.

    The same revocation `evaluate_eligibility`'s clean scan performs — the newest
    verdict-bearing round wins, and a later REVISE on ANY arm invalidates an older clean
    verdict over the same bytes. Applied here rather than inside `_final_byte_round` so
    the selector keeps answering with a file-arm round (whose digest can be compared)
    even when the revoking round is an embed/inline one.
    """
    # A single reverse pass, stopping at `rnd` itself. Comparing by IDENTITY rather than
    # `==` matters: two round records comparing equal by value would otherwise stop the
    # scan at the earlier one and silently widen the "newer" window.
    for other in reversed(completed_rounds(state)):
        if other is rnd:
            return False
        if other.get('outcome') == 'REVISE':
            return True
    return False


def _final_byte_answer(coverage, reason, rnd):
    """One decided final-byte answer, its token asserted against the closed set.

    Every `evaluate_final_byte_coverage` return goes through here, so the closed
    vocabulary is enforcement rather than documentation — a token typo'd in one arm would
    otherwise ship green, since nothing downstream re-checks it.
    """
    _require(coverage in _FINAL_BYTE_COVERAGE,
             f'issue-audit-state: the final-byte coverage token {coverage!r} is outside '
             f'_FINAL_BYTE_COVERAGE')
    return {'coverage': coverage, 'reason': reason, 'round': rnd}


def evaluate_final_byte_coverage(state, current_digest=None, digest_failed=False):
    """Whether the bytes that would be FILED carry a verdict from a round that saw them.

    A sibling of the shipped coverage axis (`evaluate_coverage`) in reporting and
    non-gating: answered on `query-summary` and on its own `query-final-byte`, never on
    `query-triggers`, never on `query-convergence`, and it gates neither `emit-body` nor
    `query-eligibility`. Its only teeth are the final-byte offer.

    Returns `{'coverage': <token in _FINAL_BYTE_COVERAGE>, 'reason': <str|None>,
    'round': <round|None>}`. The answer set is complete by construction — every path
    below returns exactly one of the three tokens.

    `covered` requires ALL FOUR terms of the shipped clean test, not merely the two that
    are about bytes, because the axis reports what the engine would ground on:
      1. the newest completed verdict-bearing round carries `VERDICT: FILE` (a newer
         completed `REVISE` revokes it, exactly as `evaluate_eligibility`'s clean scan
         does);
      2. the digest recorded at that round's dispatch equals the current canonical-file
         digest;
      3. no recorded revision postdates that round; and
      4. that round's steering-absence was ESTABLISHED — the engine already refuses to
         ground on a round whose independence could not be established, so the axis
         inherits that term and reports `uncovered` there, which is exactly the state
         the exact-byte pass exists to offer against.

    FOUR things never set it to `covered`, and the complement of that set is what
    `covered` means. A creation ATTESTATION never does — an attestation is tamper
    evidence over the bytes actually posted, not audit coverage of them. A `cap-reached`
    override never does — it records that a ceiling was reached, not a verdict. A
    `user-decline` override never does — a user's election to file is not an auditor's
    reading of the bytes. And a clean round whose steering-absence was never established
    never does, per term 4. None of the three records is read anywhere below; that is the
    non-substitutability, stated here and asserted in the suite.

    `unestablished` on exactly four states, complete by construction: no readable, owned
    lifecycle state exists at all (an unreadable/corrupt record, or a foreign nonce the
    caller collapsed to `None`); no completed file-arm verdict-bearing round exists; the
    canonical file could not be digested; or the query was supplied no draft digest, so
    the comparison was never made. An embed-arm or inline-arm LATEST round is NOT one of them — the selector reads the
    newest file-arm verdict-bearing round, so a run that already reported `uncovered`
    keeps reporting it. `unestablished` is not `uncovered`: the trigger below does not
    hold on it, so no offer fires that an accepted round could not honour.
    """
    if state is None:
        return _final_byte_answer('unestablished', 'state-unestablished', None)
    rnd = _final_byte_round(state)
    if rnd is None:
        return _final_byte_answer('unestablished', 'no-file-arm-verdict-round', None)
    if digest_failed:
        return _final_byte_answer('unestablished', 'draft-undigestible', rnd)
    if current_digest is None:
        return _final_byte_answer('unestablished', 'no-digest-supplied', rnd)
    if rnd.get('outcome') != 'FILE':
        return _final_byte_answer('uncovered', 'latest-verdict-revise', rnd)
    if _final_byte_revoked(state, rnd):
        return _final_byte_answer('uncovered', 'superseded-by-revise', rnd)
    if rnd['attempts'][-1].get('digest') != current_digest:
        return _final_byte_answer('uncovered', 'digest-mismatch', rnd)
    if _revision_postdates(state, rnd):
        return _final_byte_answer('uncovered', 'revision-postdates', rnd)
    if not _steering_established(rnd):
        return _final_byte_answer('uncovered', 'steering-unestablished', rnd)
    return _final_byte_answer('covered', None, rnd)


def _funded_rounds(doc):
    """How many rounds the recorded budgets fund: exactly the recorded spends.

    Issue #1751 removed the free `1 +` term: no round is funded by default, so the
    first fresh-context round opens only after a recorded election (`record-offer
    --accepted`, which bumps `user_rounds_used` in `_ROUND_BUDGETS`). A run that
    elects nothing funds zero rounds and never dispatches an auditor.
    """
    return sum(doc.get(k, 0) for k in _ROUND_BUDGETS)


def final_byte_passes(state):
    """`(used, exhausted)` for the dedicated final-byte slot — the single derivation.

    Several consumers read this pair — the slot predicate, the summary's two slot fields,
    the producer's ceiling refusal, the trigger query's rendering, and the offer producer's
    own output line — and the cap is a THRESHOLD: every one of those independent
    comparisons would have to be found together the first time the comparison changes, one
    of them deciding an offer and one deciding what the user reads before approving.
    """
    st = state or {}
    # EFFECTIVE passes: grants minus refunds. A pass that closed without honouring the offer was
    # not a pass, so it does not consume the cap — that is what makes the refund a real safety
    # pass rather than a re-armed trigger the cap immediately re-closes. Clamped at 0 so a
    # hand-corrupted refund count can never report a negative spend.
    used = max(0, st.get('final_byte_passes_used', 0) - st.get(_FINAL_BYTE_REFUNDS_KEY, 0))
    return (used, used >= _FINAL_BYTE_PASS_CAP)


def final_byte_slot_unspent(state, current_digest):
    """Whether the dedicated final-byte slot is unspent FOR THE CURRENT canonical digest.

    This is the single definition of "the slot is unspent"; every other mention points
    at it rather than restating it. Two terms, both necessary:

      - the slot's recorded spend digest is not the current canonical digest. Keying the
        spend to the BYTES rather than to the run is what re-arms it: Step 4's iterate
        loop repeats until the user approves, so a pass taken on bytes the user then
        edits must not leave the bytes actually filed unofferable. A recorded revision
        that changes the canonical digest therefore re-arms the slot with no revision
        hook at all — the comparison below simply stops matching.
      - the run is under `_FINAL_BYTE_PASS_CAP`. Re-arming is unbounded without it, since
        the loop can return to the election any number of times. See `_FINAL_BYTE_PASS_CAP`
        for what a run at the cap discloses.
    """
    if state is None:
        return False
    if final_byte_passes(state)[1]:
        return False
    spent_for = state.get('final_byte_slot_digest')
    return spent_for is None or spent_for != current_digest


def _final_byte_resolution_settled(state, rnd):
    """Suppress the final-byte OFFER when the drafter's own resolutions closed a round (#1771).

    True only when `rnd` closed non-FILE (a `latest-verdict-revise` selection), its
    steering-absence was ESTABLISHED, and the run converged on `basis=resolution` with zero
    effective unresolved findings — the common case a REVISE round whose findings the drafter
    then self-verified and resolved reaches. The final-byte offer exists to catch bytes no
    auditor read, but a second user pause there duplicates diligence already done, so the
    offer is withheld here while `evaluate_final_byte_coverage` still reports the bytes
    `uncovered` truthfully. Steering-established is required so a round whose independence
    could not be established still earns the offer. The FILE early-return is defensive: a
    steering-established FILE round reports `covered`, so the caller's `if holds` guard never
    reaches this helper for it — the return guards only against a future coverage-contract change.
    """
    if rnd is None or rnd.get('outcome') == 'FILE':
        return False
    if not _steering_established(rnd):
        return False
    conv = evaluate_convergence(state)
    return conv['converged'] and conv['basis'] == 'resolution'


def evaluate_final_byte_trigger(state, current_digest=None, digest_failed=False):
    """Whether the final-byte exact-byte offer holds (issue #792).

    Holds if and only if the reported coverage is `uncovered`, the dedicated slot is
    unspent for the current canonical digest, AND the offer is not suppressed by issue
    #1771's resolution-settled rule — never on `unestablished` (where an accepted round
    could not change the answer, so the offer would fund nothing and leave the run with no
    next action), never on `covered`.

    The #1771 suppression withholds the OFFER, not the coverage axis: when the run converged
    `basis=resolution` on a steering-established REVISE round's self-verified fixes, `holds`
    is False and the reason becomes `resolution-settled`, while `coverage` stays `uncovered`
    so the factual "were these bytes audited" report is not overwritten. See
    `_final_byte_resolution_settled`.

    Answered on its own `query-final-byte`, deliberately NOT appended to
    `query-triggers`: that query's Step 3.6 -> Step 4 boundary consumer applies
    "While ANY holds, offer one more audit round" at the PRE-PRESENTATION pause, where
    the bytes are not yet final — so a fifth field there would fire the pass at the wrong
    moment, and its answer shape is fixed by whole-line comparands besides.
    """
    fb = evaluate_final_byte_coverage(state, current_digest, digest_failed=digest_failed)
    holds = (fb['coverage'] == 'uncovered'
             and final_byte_slot_unspent(state, current_digest))
    reason = fb['reason']
    if holds and _final_byte_resolution_settled(state, fb['round']):
        holds, reason = False, 'resolution-settled'
    return {'holds': holds, 'coverage': fb['coverage'], 'reason': reason}


def _final_byte_honoured(rnd):
    """Did this round honour the final-byte offer? `None` while it is still open (#792).

    Three-valued deliberately: `None` means the round has not closed, and a pending retry
    must not trigger a refund that would hand the run a second slot while the first round
    is still open.

    A round honours the offer only by closing with a FILE-ARM VERDICT-BEARING outcome —
    the one condition that covers all three degradations the pass can take: a failed
    pre-dispatch write (the round lands on the embed arm, so the arm term fails), a return
    carrying no parseable verdict (outcome `no-verdict`), and a `VERDICT: DRAFT-UNREADABLE`
    return once its one re-dispatch is exhausted.
    """
    if rnd.get('outcome') is None:
        return None
    return (rnd['outcome'] in _VERDICT_BEARING_OUTCOMES
            and rnd['attempts'][-1]['arm'] == 'file')


def _last_discovery_round(state):
    """The newest completed DISCOVERY round — the run's latest WHOLE-DRAFT evidence.

    Named for the concept rather than the exclusion, so a second non-discovery round kind
    extends this predicate's body instead of falsifying its name. Issue #793 is that second
    kind, and it extends the body exactly as the name promised: a `targeted` round is
    excluded here for the same reason a final-byte pass is — it is not whole-draft
    evidence. It audited an enumerated claim set over a changed-section span, so treating it
    as the run's latest evidence would let a successful scoped round DEMOTE an established
    coverage backing, WIPE a recorded calibration signal, report `basis=adjudicated` over a
    draft nobody re-read, and ground the clean scan. Generalizing the exclusion once here
    is what keeps `_coverage_round` and `_calibration_round` from each needing their own
    special case.

    The coverage and calibration axes derive from "the run's final accepted round", and
    an accepted exact-byte pass would otherwise retire both: the coverage selector
    returns nothing unless the latest completed round's outcome is literally `FILE`, so a
    pass returning `REVISE` would ERASE an earlier round's coverage evidence rather than
    re-derive it, and any superseding adjudication retires the calibration axis. Recording
    coverage on the pass itself would not have sufficed for the same reason. The pass is
    a whole-draft safety re-read of already-audited bytes, not a new discovery round, so
    it is excluded from both selectors rather than allowed to supersede them.
    """
    if state is None:
        return None
    for rnd in reversed(completed_rounds(state)):
        if rnd.get('final_byte_pass'):
            continue
        if _round_kind(rnd) == 'targeted':      # issue #793
            continue
        return rnd
    return None


def _last_whole_draft_round(state):
    """The newest completed round that audited the WHOLE draft — the audit summary's ground.

    issue #793 — DECIDED treatment for `summary_fields`. A `targeted` round audits an
    enumerated claim set over a changed-section span, so its verdict and class counts
    describe a scoped re-check, not a draft anybody re-read end to end. Rendering them as
    the Step 4 audit summary would tell a reader a whole draft came back clean when none
    was audited — which is why the summary reads this selector and the scoped round is
    reported beside it under its own field rather than silently dropped.

    Deliberately NOT `_last_discovery_round`: that selector also excludes a final-byte
    exact-byte pass, because the coverage and calibration axes it feeds would be retired
    by one. For THIS reader a final-byte pass IS whole-draft evidence whose verdict issue
    #792 renders on purpose, so reusing that selector here would silently revert it. The
    two selectors therefore differ by exactly the final-byte clause, and each states why.
    """
    if state is None:
        return None
    for rnd in reversed(completed_rounds(state)):
        if _round_kind(rnd) == 'targeted':
            continue
        return rnd
    return None


def _last_scoped_round(state):
    """The newest completed `targeted` round, else None — the summary's separate name.

    The companion of `_last_whole_draft_round`: what that selector skips, this one names,
    so a scoped round the summary does not ground on is still visible to the reader.
    """
    if state is None:
        return None
    for rnd in reversed(completed_rounds(state)):
        if _round_kind(rnd) == 'targeted':
            return rnd
    return None


def _calibration_round(state):
    """The round the calibration axis derives from: the latest completed adjudicated round.

    Advisory/invalid records are the LATEST completed round's, exactly as the #548 summary
    reads the adjudicated verdict from `last_completed`: a run's calibration is the state of
    its final adjudication, not a cumulative roll-up, so a resolved earlier round does not
    keep a run under-evidenced.

    issue #792: "the latest completed adjudicated round" excludes a final-byte exact-byte
    pass — see `_last_discovery_round`. A run with no pass takes the identical
    answer, since the selector then reduces to `last_completed`.
    """
    if state is None:
        return None
    last = _last_discovery_round(state)
    if last is None or last.get('adjudicated_verdict') is None:
        return None
    return last


def evaluate_calibration(state):
    """The run's advisory-adjudication calibration, from the final adjudicated round (#743).

    Returns `{'backing', 'render', 'unevidenced', 'round', 'reason'}`:
      - `backing` in `_CALIBRATION_BACKINGS`. `under-evidenced` when the final adjudicated
        round carries at least one IMPACT-BEARING advisory record with no recorded evidence;
        `clear` when it carries advisory/invalid records and every impact-bearing advisory
        record is evidenced; `unestablished` when there is no adjudicated round, or that round
        carries no advisory/invalid records at all (unknown is never collapsed onto clear).
      - `render` — the round's reported-observation render state (`reported`/`unreported`), or
        `none` when there is no calibration round.
      - `unevidenced` — the sorted ids of the impact-bearing advisory records with no evidence.

    A DISTINCT axis from convergence and coverage: it never redefines evaluate_convergence and
    never gates emit-body/query-eligibility. Its only teeth are the calibration offer trigger,
    the disclosure surface, and the summary — filing is never blocked on any arm.

    Scoped to the FINAL adjudicated round by design (mirroring the coverage/summary
    `last_completed` scoping): a superseding later adjudication retires an earlier round's
    calibration trigger, so an under-evidenced impact-bearing advisory from an earlier round no
    longer fires the offer once a later round is adjudicated. This is a deliberate choice, not a
    dropped signal — the earlier round's per-finding records stay readable via
    `query-adjudication-records`; only the live disclosure trigger follows the latest round.
    """
    if state is None:
        return {'backing': 'unestablished', 'render': 'none', 'unevidenced': [],
                'round': None, 'reason': 'state-unestablished'}
    rnd = _calibration_round(state)
    if rnd is None:
        return {'backing': 'unestablished', 'render': 'none', 'unevidenced': [],
                'round': None, 'reason': 'no-adjudicated-round'}
    advisory = rnd.get('advisory_records') or []
    invalid = rnd.get('invalid_records') or []
    if not advisory and not invalid:
        # A round adjudicated with no advisory/invalid grades has nothing to calibrate.
        return {'backing': 'unestablished', 'render': 'none', 'unevidenced': [],
                'round': rnd, 'reason': 'no-records'}
    unevidenced = sorted(
        r['id'] for r in advisory
        if r.get('impact_class') in _IMPACT_BEARING_CLASSES
        and not (r.get('evidence') or '').strip())
    backing = 'under-evidenced' if unevidenced else 'clear'
    assert backing in _CALIBRATION_BACKINGS
    return {'backing': backing, 'render': rnd.get('adjudication_render') or 'unreported',
            'unevidenced': unevidenced, 'round': rnd, 'reason': None}


def evaluate_calibration_trigger(state, cal=None):
    """Whether the calibration disclosure offer trigger holds (issue #743).

    A never-blocking sibling of T1/T2 and the coverage trigger, routed through the same offer
    machinery and user-round cap. It fires when the run holds an impact-bearing advisory grade
    with no recorded evidence (`backing == 'under-evidenced'`), OR when it holds advisory/invalid
    records whose Step-4 rendering the run has not reported (`render != 'reported'`) — either is
    a grade that would otherwise reach the approval election undisclosed. A run whose records
    are all evidenced/optional AND reported rendered does not fire; a run with no records never
    fires. Filing is never blocked by this trigger — its teeth are disclosure only.

    `cal` may be a precomputed `evaluate_calibration(state)` result: the two callers that render
    the backing/render fields beside the trigger (`summary_fields`, `cmd_query_calibration`)
    pass the value they already hold, so the calibration derivation runs once, not twice.
    """
    if cal is None:
        cal = evaluate_calibration(state)
    if cal['backing'] == 'unestablished':
        return False
    return cal['backing'] == 'under-evidenced' or cal['render'] != 'reported'


def issue_token(nonce, ground, key):
    """The deterministic eligibility token.

    A pure function of the run nonce and the answering key, so repeated queries
    re-emit an identical token while any change of that key produces a different one.
    The key is the operand that actually answered: the digest on the file-identity
    ground and on a digest-bound (file-arm) override; the revision ordinal on the
    event-ordering ground and on an override with no digest bound, where no
    trustworthy canonical file exists to key on. `hashlib` rather than git: the token
    is not a content hash and the tool's only subprocess is git for object IDs.
    """
    material = f'{nonce}:{ground}:{key}'.encode()
    return 'eat_' + hashlib.sha256(material).hexdigest()[:16]


def _select_current_override(state, current_digest, *, unbound_ok, kinds=None):
    """The newest override current at the run's revision ordinal, or None.

    A bound override (a recorded `draft_digest`) is honoured only while that digest still
    matches `current_digest`; an unbound one only when `unbound_ok` holds. `kinds`, when
    given, restricts the search to overrides of those kinds. This one selector is shared by
    both `_valid_override` arms so the epoch-round and zero-round matching rules — which
    differ only in `kinds` and in when an unbound override is honoured — cannot drift apart.
    """
    now = revision_ordinal(state)
    for ov in reversed(state['overrides']):
        if kinds is not None and ov.get('kind') not in kinds:
            continue
        if ov.get('recorded_at_ordinal') != now:
            continue
        want = ov.get('draft_digest')
        if want is None:
            if not unbound_ok:
                continue
        elif want != current_digest:
            continue
        return ov
    return None


def _valid_override(state, current_digest):
    """The newest override still current, or None.

    An override is valid only while the revision ordinal recorded on it stays
    current, and — on a file-arm epoch — while the digest recorded on it still
    matches the draft. A later revision record invalidates every earlier override,
    and a stale override never re-arms.

    Two preconditions fail CLOSED here, mirroring the guards `record-override`
    applies at the write boundary. They are re-checked at this read boundary because
    this is the gate: a hand-edited state file, or a record written by an older
    build, must not smuggle an override past them.

      - No completed round no longer forbids EVERY override (issue #1751): a
        `user-decline` recorded on a zero-round run is the user's election to file
        unaudited and is honoured here, so `emit-body` can emit that run's body. A
        zero-round `cap-reached` stays incoherent — a ceiling cannot be reached before
        any round ran — so it is never honoured at zero rounds. The zero-round decline's
        binding mirrors the file-arm rule below: it is honoured only when its recorded
        digest still matches the draft, and an unbound (no-digest) decline is honoured
        only when the query supplies no canonical digest at all (the read-only sandbox);
        a query that DID supply canonical bytes against an unbound decline fails closed,
        because those bytes were never bound.
      - On a file-arm epoch an override carrying no digest was never compared against
        any bytes, so honouring it would pass a draft the tool never inspected. An
        absent comparand fails closed rather than skipping the comparison.
    """
    epoch = last_completed(state)
    if epoch is None:
        # Zero-round arm (issue #1751): only a current `user-decline` grounds eligibility
        # here, never a `cap-reached`. An unbound decline is honoured only when no
        # canonical digest was supplied (the read-only sandbox).
        return _select_current_override(
            state, current_digest, unbound_ok=current_digest is None,
            kinds=('user-decline',))
    # Off the file arm there is no trustworthy canonical file, so an unbound override is
    # honoured; on a file-arm epoch an unbound override was never byte-compared, so it fails
    # closed.
    file_arm_epoch = epoch['attempts'][-1]['arm'] == 'file'
    return _select_current_override(
        state, current_digest, unbound_ok=not file_arm_epoch)


_STALE_OVERRIDE_ELECTION = (
    're-present the revised draft and record a new override only on a fresh explicit '
    'user election through the offer surfaces (a fresh clean audit round is the other '
    'eligibility ground)'
)


def stale_override_remedy(state, current_digest):
    """The arm-selected recovery text for a `stale-override` refusal.

    The refusal itself is fail-closed and correct; what it lacked was a remedy, so an
    agent that hit it rediscovered the recovery by trial — costliest at `emit-body`,
    after the creation epoch is already recorded.

    **The arm is selected by the staling operand observed on the newest CURRENT-ORDINAL
    override, never by the epoch's query-time arm.** An override's digest binding is
    fixed at record time while the epoch arm is keyed at query time, so the two
    legitimately diverge — a file-write failure and embed retry landing between the
    record and the query leaves a digest-bound override on an embed-arm epoch. Keying
    on the epoch arm would name the wrong remedy on exactly that divergence.

      * arm a — a current-ordinal override whose recorded digest differs from the draft:
        the revision is NOT yet recorded, so lead with `record-revision`.
      * arm b — no current-ordinal override AND the newest override's recorded ordinal
        is LESS than the current revision ordinal: the revision is already recorded, so
        naming it again would send the caller to re-record state it already holds.
        Absence of a current-ordinal override does not select this arm on its own.
      * arm c (fail-safe) — every other skipped shape: a current-ordinal override whose
        digest binding could not be compared (it carries no digest on a file-arm epoch,
        OR no draft digest was supplied at query time), a future-ordinal record, or any
        further hand-edited / older-build shape. It makes NO claim about the revision
        state, because none was established.

    No arm names a bare `record-revision`-then-`record-override` pair: that sequence
    would re-arm a user election the user never made, which is the defect the skill's
    edit-sequencing rule exists to prevent. Arm a names `record-revision` only as a
    step that must be followed by a fresh election.
    """
    now = revision_ordinal(state)
    overrides = state.get('overrides') or []
    current = None
    for ov in reversed(overrides):
        if ov.get('recorded_at_ordinal') == now:
            current = ov
            break
    newest = overrides[-1] if overrides else None
    # Each branch selects only its CAUSE clause; the shared election clause is appended
    # once below, so "every arm ends in the election" is structural rather than a
    # convention each return site must separately remember. Arm c of the docstring is
    # implemented as separate branches with distinct causes (an unvalidatable
    # current-ordinal override; no current override at all), deliberately not renumbered
    # here.
    if (current is not None and current_digest is not None
            and current.get('draft_digest') not in (None, current_digest)):
        cause = ('the recorded override was digest-bound to draft bytes that have '
                 'since changed, so it no longer grounds eligibility; record the '
                 'revision with `record-revision`, then ')
    elif current is not None:
        # A current-ordinal override that is not digest-staled reached the refusal with
        # an uncomparable digest binding — the override carries none, or none was
        # supplied at query time. Either way the cause is unestablished, so claim
        # nothing about the revision state.
        cause = ('the recorded override could not be validated against the draft bytes, '
                 'so it no longer grounds eligibility; ')
    elif (newest is not None
            # `not isinstance(..., bool)` is load-bearing, not defensive noise: bool is a
            # subclass of int in Python, so a `true` ordinal in a hand-edited state file
            # passes a bare isinstance check and then compares as 1 — letting arm b assert
            # "the revision is already recorded" from a value that is not an ordinal at all.
            and isinstance(newest.get('recorded_at_ordinal'), int)
            and not isinstance(newest.get('recorded_at_ordinal'), bool)
            and newest['recorded_at_ordinal'] < now):
        cause = ('the revision is already recorded, which invalidated the earlier '
                 'override; ')
    else:
        cause = 'no recorded override is still current, so none grounds eligibility; '
    return cause + _STALE_OVERRIDE_ELECTION


def _emit_stale_override_remedy(prefix, elig, state, current_digest):
    """Write the arm-selected remedy to stderr beside a `stale-override` refusal.

    Called from the two REFUSAL surfaces only — `cmd_query_eligibility` and
    `cmd_emit_body` — never from the shared `evaluate_eligibility` they both call. The
    reason token's third reader, `summary_fields` (rendering `query-summary`), is a
    RENDERING surface, not a refusal: emitting from the shared evaluation would grow an
    unplanned stderr line on every summary render of a stale-override-shaped state.

    The `stale-override` test lives HERE rather than at each call site so the guard
    cannot be forgotten: a refusal surface added later calls this unconditionally and
    gets the remedy for free, instead of silently shipping without one.
    """
    if elig.get('reason') != 'stale-override':
        return
    sys.stderr.write(
        f'issue-audit-state.py {prefix}: {stale_override_remedy(state, current_digest)}\n')


# issue #82: this remedy must never read as an instruction to record an override with no
# user election — it points at the record of the user's OWN election, and the election
# precondition below is load-bearing (the rationale is in the emitter docstring below).
_UNAUDITED_REVISION_REMEDY = (
    'this draft carries no clean audit verdict, so eligibility grounds only on the '
    "user's own filing election: record it with `record-override --kind user-decline "
    '--surface step4-offer --draft-file <canonical>` — recorded only after the user '
    'elects *Create it as-is* or *File anyway* at sub-step 3a, never on this refusal '
    'itself (a fresh clean audit round is the other eligibility ground)'
)


def _emit_unaudited_revision_remedy(prefix, elig):
    """Write the `unaudited-revision` recovery to stderr beside that refusal (issue #82).

    Sibling of `_emit_stale_override_remedy`: self-guarded on the reason and called
    unconditionally at the two refusal surfaces (`cmd_query_eligibility`, `cmd_emit_body`),
    never from the shared `evaluate_eligibility` — so `query-summary`, the rendering
    surface, stays stderr-silent. Keeping the guard here (not at each call site) is what
    lets a refusal surface added later get the remedy for free instead of shipping without
    one, exactly as the stale-override twin does.
    """
    if elig.get('reason') != 'unaudited-revision':
        return
    sys.stderr.write(f'issue-audit-state.py {prefix}: {_UNAUDITED_REVISION_REMEDY}\n')


def _clean_identity(state, clean, current_digest):
    """The `(ground, key)` a clean round supplies on IDENTITY alone, or None.

    Identity only — the issue-#709 steering requirement is deliberately NOT folded in
    here, because two callers need the identity answer for opposite purposes: the clean
    grant (which additionally requires established steering) and the
    `steering-unestablished` refusal (which is the honest diagnosis only where identity
    already held). Sharing one operation is what keeps the refusal's stated precondition
    true by construction rather than by a comment claiming the two agree.

    file arm — issue #562 post-revision write-failure closure: byte-digest equality is
    not sufficient on its own. A recorded revision that postdates the clean round and
    whose overwrite FAILED leaves the bound file still holding the clean round's
    byte-identical bytes, so `recorded == current_digest` holds over bytes the user
    revised away. Require, in addition, that no revision postdates the clean round
    (mirroring the event-ordering ground). Equality can still hold WITH a postdating
    revision two ways — the write-failure case and a revise-back-to-clean case — and
    keying on the revision's existence, not its bytes, refuses both.

    other arms — the weaker event-ordering identity. Note that `evaluate_eligibility`
    reaches this ground only when steering was established, which the file-arm-only
    instruction file makes impossible on the embed/inline arms today; those arms
    therefore ground through the override election instead, which is the withhold-then-
    disclose outcome issue #709 specifies for them, not an accidental dead branch.
    """
    if clean is None:
        return None
    if clean['attempts'][-1]['arm'] == 'file':
        recorded = clean['attempts'][-1].get('digest')
        if (current_digest is not None and recorded == current_digest
                and not _revision_postdates(state, clean)):
            return ('file-identity', current_digest)
        return None
    if not _revision_postdates(state, clean):
        return ('event-ordering', str(revision_ordinal(state)))
    return None


def evaluate_eligibility(state, mode, current_digest=None, digest_failed=False):
    """Presentation eligibility.

    `approve` gates the presentation-for-approval of bytes with no pending re-audit
    offer, and the creation step itself. It answers `eligible` on exactly two grounds:
      (a) a completed `VERDICT: FILE` round whose identity holds for the current draft
          — on a file-arm round, its recorded dispatch digest equals the current
          canonical-file digest (an absent or unreadable file answers not-eligible —
          at the CLI with the distinct reason draft-undigestible — fail closed); on
          an embed-arm or inline-arm round, where no trustworthy canonical file exists,
          identity holds when no revision record postdates the round (the event-ordering
          ground — weaker than byte identity, and disclosed as such).
      (b) an explicitly recorded override that is still current.

    Ground (a) additionally requires, since issue #709, that the grounding round
    ESTABLISHED steering-absence — the auditor's quoted canonical-instruction-file
    object ID matched the freshly-regenerated canonical digest and it reported no extra
    dispatch content. That requirement is structurally PRIOR to the refusal chain below
    rather than a peer of it: it gates ground (a)'s own return, so it is reachable only
    where identity already held. Ground (b) is deliberately untouched — an explicit user
    override is a human decision that does not rest on the audit's independence.

    `iterate` covers only the in-loop re-presentation of a just-revised draft while its
    re-audit offer is pending. `iterate-ok` is never a ground for acting on approval and
    never a ground for creation.

    Reason precedence when several could apply is decided, not incidental:
      state-unestablished > draft-undigestible > steering-unestablished >
      no-verdict-round > no-digest-supplied > stale-override > unaudited-revision.

    `steering-unestablished` sits where it does because it is REACHABLE only when the
    clean round's IDENTITY already holds (same `_clean_identity` operation the grant
    consumes) and the override ground did not rescue it — so where it fires, the
    establishment really is the single missing property. The reasons after it stay
    reachable on their own states: a clean round with a postdating revision answers
    `unaudited-revision`, and a digest-less approve query answers `no-digest-supplied`,
    whether or not steering was established. Its position expresses specificity over
    states it genuinely diagnoses, not a blanket preemption of the chain below.

    `no-digest-supplied` outranks `stale-override` deliberately: an override queried
    with no draft digest was never compared, so nothing went stale — naming the
    caller's omission is the honest cause. See the refusal chain below.
    """
    if mode not in ('approve', 'iterate'):
        # The mode is a closed vocabulary like every other: an off-set value must
        # never silently take the permissive approve path.
        raise AssertionError(
            f'issue-audit-state: eligibility queried with mode {mode!r}, which is not '
            f"one of ('approve', 'iterate')")
    if mode == 'iterate':
        if state is None:
            return _no('state-unestablished')
        if revision_ordinal(state) >= 1:
            return {'answer': 'iterate-ok', 'reason': None, 'ground': None,
                    'token': None, 'ordinal': revision_ordinal(state)}
        return _no('no-revision-recorded')

    if state is None:
        return _no('state-unestablished')
    if digest_failed:
        # A supplied draft file that could not be read or hashed never grounds
        # eligibility on ANY ground (overrides included) — fail closed with the
        # distinct reason, never misattributed as unaudited-revision.
        return _no('draft-undigestible')

    clean = None
    for rnd in reversed(completed_rounds(state)):
        # issue #793 — a `targeted` round NEVER grounds this scan, in either direction. It
        # is skipped rather than treated as a verdict-bearing round: its FILE outcome is
        # not whole-draft evidence and must not become the clean ground, and its REVISE
        # outcome is a per-claim re-check that must not revoke an earlier whole-draft clean
        # verdict either. Skipping (rather than breaking) is deliberate and is why the
        # confirming round exists: the scan BREAKS on the first `REVISE`, so a rule that
        # merely stopped at a clean scoped round would land on the preceding `REVISE`,
        # break, and refuse `unaudited-revision` — reaching the clean ground needs a real
        # whole-draft round, which `next_action`'s `confirm-whole-draft` schedules.
        if _round_kind(rnd) == 'targeted':
            continue
        # The clean ground requires the NEWEST completed verdict-bearing round to be
        # FILE: a later completed REVISE round on the same bytes invalidates an older
        # clean verdict (probe-confirmed fail-open otherwise — the newest verdict wins).
        # The scan deliberately FALLS THROUGH a `no-verdict` round: an inconclusive
        # re-audit is not a revocation, so a clean verdict on unchanged bytes (digest
        # identity on the file arm; no later revision on embed/inline) still grounds
        # eligibility. This diverges from evaluate_triggers on purpose — T2 treats the
        # same trailing no-verdict round as "effectively unaudited" and fires the
        # boundary offer, so the inconclusive re-audit is surfaced to the user rather
        # than laundered, while eligibility on the previously-audited, unchanged bytes
        # is not revoked by inconclusiveness alone. Pinned in both directions in the
        # suite (no-verdict does not shadow; REVISE does).
        if rnd.get('outcome') == 'FILE':
            clean = rnd
            break
        if rnd.get('outcome') == 'REVISE':
            break

    # issue #709: the coverage-backed clean ground now requires steering-absence to have
    # been ESTABLISHED for the grounding round — the auditor's quoted instruction-file
    # object ID matched the freshly-regenerated canonical digest AND it reported no extra
    # dispatch content. This gate sits INSIDE the clean block, structurally prior to the
    # refusal chain below rather than as one more peer reason in it: the grant is
    # withheld at its own return, and the refusal below fires only where the clean
    # round's identity itself holds. That guard — not a claim that no other reason could
    # ever match the same state — is what keeps the diagnosis honest: `no-digest-supplied`
    # and `unaudited-revision` both DO require a clean round (see their own arms below),
    # so a precedence that preempted them unconditionally would misattribute a stale or
    # digest-less query to steering.
    #
    # Scope, stated so it is not over-read: only the CLEAN ground is withheld. The
    # override ground below is untouched, `emit-body`'s other paths are untouched, and
    # Step 4 still presents and files on the user's approval — filing is never blocked on
    # any arm. What is withheld is exactly the coverage-backed clean grounding.
    # `steering_ok` already implies `clean is not None`, so the guards below test it
    # alone rather than restating that fact at each site.
    steering_ok = clean is not None and _steering_established(clean)
    # The identity half is computed ONCE, by the shared helper, and consumed twice: here
    # for the grant, and by the #709 refusal below. A second hand-written copy of the
    # condition is what made the refusal claim "identity held" over states where it had
    # not (an unaudited revision, or a digest-less query), so the two now share one
    # operation by construction rather than by a comment asserting they agree.
    identity = _clean_identity(state, clean, current_digest)
    if steering_ok and identity is not None:
        return _yes(state, identity[0], identity[1])

    ov = _valid_override(state, current_digest)
    if ov is not None:
        # Key on whichever operand actually answered, per issue_token's contract. A
        # file-arm override is digest-bound (record-override enforces it), so the DIGEST
        # answered and the token must name it: keying on the revision ordinal alone
        # minted one identical token for byte-distinct drafts at the same ordinal —
        # exactly the replay the token exists to expose. Where no digest is bound (an
        # embed/inline epoch, which has no trustworthy canonical file), the ordinal is
        # what answered and remains the key.
        bound = ov.get('draft_digest')
        return _yes(state, 'override',
                    bound if bound is not None else str(revision_ordinal(state)))

    # issue #709 — checked here, immediately after the override ground could not rescue
    # it, and ONLY when the clean round's identity itself holds (`identity is not None`,
    # the same operation the grant above consumed). That guard is what makes the
    # diagnosis true rather than merely earliest: on a state where identity did NOT hold
    # — an unaudited revision postdating the clean round, or an approve query that
    # supplied no digest — the establishment is not "the single missing property", and
    # naming it here would send the reader to the wrong remedy while masking the real
    # one. Those states fall through to the chain below and answer `unaudited-revision`
    # / `no-digest-supplied` exactly as they did before #709.
    if identity is not None and not steering_ok:
        return _no('steering-unestablished')

    # Refusal precedence, decided (the docstring's tail, in the order checked below):
    # no-verdict-round > no-digest-supplied > stale-override > unaudited-revision.
    # `no-verdict-round` is scoped to the genuinely verdict-less states — nothing has
    # completed yet, or the last completed round hit the inline arm's verdict-less
    # terminal. A completed REVISE round is NOT verdict-less: a verdict exists, it is
    # merely not clean, so bytes carrying it refuse as `unaudited-revision` (the
    # motivating regression's own shape).
    last = last_completed(state)
    if last is None or last.get('outcome') == 'no-verdict':
        return _no('no-verdict-round')
    if state['overrides']:
        if current_digest is None and any(
                ov.get('draft_digest') for ov in state['overrides']
                if ov.get('recorded_at_ordinal') == revision_ordinal(state)):
            # A digest-bound override queried with NO digest was never compared:
            # nothing went stale — the caller omitted the draft file.
            return _no('no-digest-supplied')
        return _no('stale-override')
    if current_digest is None and clean is not None:
        arm = clean['attempts'][-1]['arm']
        if arm == 'file' and not _revision_postdates(state, clean):
            # A file-arm clean epoch queried with NO digest supplied was never
            # compared at all: refusing as unaudited-revision would assert a revision
            # that may not exist. Name the real cause.
            return _no('no-digest-supplied')
    return _no('unaudited-revision')


def _yes(state, ground, key):
    # The ground is printed and feeds the eligibility token's derivation, so an
    # off-vocabulary ground would mint a token no reader can attribute to a known ground.
    if ground not in _GROUNDS:
        raise AssertionError(
            f'issue-audit-state: eligibility answered on ground {ground!r}, which is not '
            f'in _GROUNDS')
    return {'answer': 'eligible', 'reason': None, 'ground': ground,
            'token': issue_token(state['nonce'], ground, key), 'key': key}


# The eligibility result is an UNTAGGED union of three shapes, discriminated by `answer`:
#   eligible    -> ground + token + key      (from _yes)
#   iterate-ok  -> ordinal                   (from the iterate branch above)
#   not-eligible-> reason                    (from _no)
# The variant-only keys (`key`, `ordinal`) are therefore absent on the other variants, and
# reading one off the wrong variant is a KeyError rather than a type error. Recorded as an
# accepted trade-off (raised on PR #552), NOT a live defect: every read of a variant-only key
# sits inside an arm that already discriminated on `answer` — see cmd_query_eligibility, whose
# `ordinal`/`key` reads are each guarded by their own answer check — and the suite drives all
# three variants. The discrimination is enforced by convention, not by the type; a dataclass
# or tagged union would make the illegal read unrepresentable. Revisit if a consumer reads a
# variant-only key OUTSIDE an answer-discriminated arm, or if a fourth variant is added (three
# is where hand-discrimination is still auditable at a glance).
def _no(reason):
    # Every refusal carries a machine-readable reason from the canonical set: the skill
    # routes on these tokens, so an unlisted one is a refusal it cannot act on.
    if reason not in _ELIGIBILITY_REASONS:
        raise AssertionError(
            f'issue-audit-state: eligibility refused with reason {reason!r}, which is not '
            f'in _ELIGIBILITY_REASONS')
    return {'answer': 'not-eligible', 'reason': reason, 'ground': None, 'token': None}


def next_action(state, round_no):
    """The retry/next-action answer for an open or just-closed round."""
    if state is None:
        return 'round-closed-no-verdict'
    rnd = _find_round(state, round_no)
    if rnd is None:
        return 'round-closed-no-verdict'
    outcome = rnd.get('outcome')
    # An unusable targeted return established no whole-draft evidence regardless of the
    # auditor's terminal verdict token. Confirm it while the dedicated slot remains; once
    # exhausted, hand off to the boundary query instead of spending another retry pool.
    if (_targeted_confirmation_needed(rnd)
            and state.get('confirming_rounds_used', 0) < _MAX_CONFIRMING_ROUNDS):
        return 'confirm-whole-draft'
    if _targeted_return_unusable(rnd):
        return 'proceed'
    if outcome == 'FILE':
        # issue #793 — a clean `targeted` round is CONFIRMED, not trusted. It audited a
        # claim set and a changed-section span, never the whole draft, so answering
        # `proceed` here would walk the run to Step 4 on evidence that was never
        # whole-draft. Schedule the confirming whole-draft round instead — once, from its
        # own counter; a second clean scoped round after the confirmation has already been
        # paid for answers `proceed` normally.
        # The shared predicate above owns the targeted fundable case. Once its budget is
        # spent, the usable scoped return proceeds because confirmation was already funded.
        return 'proceed'
    if outcome == 'REVISE':
        if state.get('automatic_reaudits_used', 0) < _MAX_AUTOMATIC_REAUDITS:
            return 'revise-and-reaudit'
        # The automatic budget is spent: revise, then evaluate the user-chosen-round
        # offer. The audit informs, it never deadlocks filing.
        return 'revise-then-evaluate-offer'
    if outcome == 'no-verdict':
        return 'round-closed-no-verdict'
    # `pending` is written by `record-return` from the round's own retry accounting; this
    # query only reads it, so the retry arm cannot be re-derived (and re-decided) differently
    # here than it was recorded. One field, one read — no order-dependent if-chain.
    # An open round with NO pending action is a dispatch whose return was never
    # recorded: answer the fail-closed awaiting token, never `proceed` (an orchestrator
    # in a confused mid-round state must not be told to walk past an audit it never
    # received).
    return _checked_action(rnd.get('pending') or 'round-open-awaiting-return')


def _checked_action(token):
    """Fail closed on an answer outside the canonical set.

    The skill is contractually required to obey this answer verbatim against a closed
    vocabulary it enumerates. An answer outside `_NEXT_ACTIONS` is therefore a token the
    skill has no route for — it would read as an unrecognized string mid-lifecycle. Making
    the set constrain the return keeps `_NEXT_ACTIONS` load-bearing rather than decorative.
    """
    if token not in _NEXT_ACTIONS:
        raise AssertionError(
            f'issue-audit-state: next_action produced {token!r}, which is not in '
            f'_NEXT_ACTIONS — the skill obeys this answer against a closed set')
    return token


def _round_kind(rnd):
    """A round's recorded kind, defaulting a pre-#793 record to `discovery`.

    The default is the only correct one: a round recorded before this field existed WAS a
    cold whole-draft derivation, so reading it as `discovery` describes what actually
    happened rather than papering over a missing value. Every reader goes through here, so
    the default is stated once instead of thirteen times.
    """
    if rnd is None:
        return None
    kind = rnd.get('kind')
    return kind if kind in _ROUND_KINDS else 'discovery'


def _targeted_return_unusable(rnd):
    """Whether a scoped round durably recorded an unusable per-claim return.

    The field is additive: pre-#1675 state has no key and reads false. Require the
    literal boolean rather than truthiness so a hand-corrupted string cannot force a
    boundary election.
    """
    return (_round_kind(rnd) == 'targeted'
            and rnd.get('targeted_return_unusable') is True)


def _targeted_confirmation_needed(rnd):
    """Whether a scoped terminal return needs whole-draft confirmation."""
    return (_round_kind(rnd) == 'targeted'
            and (rnd.get('outcome') == 'FILE' or _targeted_return_unusable(rnd)))


def _checked_kind(token):
    """Fail closed on a round kind outside the canonical set (issue #793).

    The exact sibling of `_checked_action` above, and for the same reason: `_ROUND_KINDS`
    is a closed vocabulary every consuming function branches on, so a kind outside it is
    one no consumer has a route for. Raising here keeps the tuple load-bearing rather than
    decorative — without it an unrecognized kind would fall through every `== 'targeted'`
    test and be treated as a whole-draft `discovery` round, which is the PERMISSIVE
    direction: it would ground the clean scan, back the coverage axis and render as
    whole-draft evidence on the strength of a round nobody can classify.
    """
    if token not in _ROUND_KINDS:
        raise AssertionError(
            f'issue-audit-state: round kind {token!r} is not in _ROUND_KINDS — every '
            f'consumer branches on this answer against a closed set')
    return token


def _checked_kind_reason(token):
    """Fail closed on a selection reason outside the canonical set (issue #793).

    `_no`'s sibling for the kind selector: the skill and the renderer route on these
    tokens, so an unlisted one is a reason neither can act on.
    """
    if token not in _ROUND_KIND_REASONS:
        raise AssertionError(
            f'issue-audit-state: round-kind selection answered reason {token!r}, which is '
            f'not in _ROUND_KIND_REASONS')
    return token


def _staged_artifacts(state):
    """The run's recorded byte history as `(digest, path)` pairs, newest last (issue #793).

    The history is what a `targeted` round's delta is computed against, and it exists only
    because `stage` now keys its artifact on the staged bytes' own digest AND records the
    resolved path durably. A malformed record is SKIPPED rather than raising: this is a
    best-effort read over a file a human can hand-edit, and a missing operand must degrade
    the selection to `discovery` (the expensive kind), never abort the run.
    """
    out = []
    for rec in (state.get('staged_paths') or []):
        if not isinstance(rec, dict):
            continue
        dig, path = rec.get('digest'), rec.get('path')
        if isinstance(dig, str) and dig and isinstance(path, str) and path:
            out.append((dig, path))
    return out


def _reconstruct_dispatch_bytes(state, digest):
    """The bytes a round dispatched, recovered from the byte history (issue #793).

    Returns the bytes, or `None` when they cannot be recovered. The lookup is by DIGEST —
    the artifact whose recorded digest equals the round's recorded dispatch digest — and
    the recovered bytes are RE-HASHED and compared to that same digest before they are
    returned. Trusting the recorded digest alone would accept an artifact whose bytes
    changed on disk after it was recorded, which is precisely the operand a delta must not
    be computed from: a wrong "before" side produces a wrong changed-section set and
    points the auditor at regions the revision never touched.

    A missing artifact is a MISSING OPERAND (`None` → the caller selects `discovery`),
    never a silently-wrong one.
    """
    if not isinstance(digest, str) or not digest:
        return None
    for dig, path in _staged_artifacts(state):
        if dig != digest:
            continue
        try:
            data = Path(path).read_bytes()
        except (OSError, ValueError):
            # `ValueError` is NOT redundant beside `OSError`: a recorded path carrying an
            # embedded NUL raises it out of `Path.read_bytes` before any syscall, and the
            # state file is hand-editable, so that path reaches here. Issue #1104 routed
            # this reader onto `record-dispatch`, a MUTATION whose contract forbids a raw
            # traceback — an uncaught raise there would break that contract on exactly the
            # corrupted input this best-effort read exists to survive.
            continue
        try:
            if hash_bytes(data) == digest:
                return data
        except _DigestError:
            continue
    return None


def _section_tokens(text):
    """Yield `(key, start_line, end_line, body_lines)` per `## ` section (issues #793/#1105).

    The single section scan `_sections` and `_section_line_spans` both derive from, so the
    occurrence-disambiguation keying and the `(preamble)` sentinel live in ONE place — a
    changed-section key resolves to the same section for the body map AND the span map,
    rather than by copy-paste fidelity between two parsers that must agree.

    Content before the first `## ` heading is collected under the sentinel key `(preamble)`,
    so an edit to the title or the opening lines is a changed section rather than an
    invisible one. Duplicate `## ` headings are ORDINARY in a hand-written draft
    (`## Notes`, `## Context`); keying on the heading alone let a later occurrence overwrite
    an earlier one, so an edit confined to the FIRST of two same-named sections disappeared
    from the delta entirely — producing a NARROWER scope that points the auditor away from
    the change, the opposite of this mechanism's fail-toward-the-expensive-kind direction.
    Disambiguate by occurrence so every section is its own comparand.

    `start_line`/`end_line` are 1-based inclusive and span the section INCLUDING its heading
    line (issue #1105 — an empty leading section clamps to `(start, start)`, the safe
    over-approximation); `body_lines` EXCLUDES the heading line, which is what `_sections`
    joins into the body string.
    """
    lines = text.splitlines()
    n = len(lines)
    seen = {}

    def _key(h):
        seen[h] = seen.get(h, 0) + 1
        return h if seen[h] == 1 else f'{h} #{seen[h]}'

    heading = '(preamble)'
    start = 1          # 1-based line of the section's first line
    body = []
    for i in range(n):
        if lines[i].startswith('## '):
            end = max(i, start)   # the line before this heading (1-based)
            yield _key(heading), start, end, body
            heading, body = lines[i].strip(), []
            start = i + 1
        else:
            body.append(lines[i])
    end = max(n, start)
    yield _key(heading), start, end, body


def _sections(text):
    """The draft's `## ` sections as an ordered `{heading: body}` mapping (issue #793).

    Derived from the shared `_section_tokens` scan, so its keying stays lockstep with
    `_section_line_spans` by construction rather than by hand.
    """
    return {key: '\n'.join(body) for key, _s, _e, body in _section_tokens(text)}


def _changed_sections(before, after):
    """The headings whose content differs between two draft states (issue #793).

    Raises `_DigestError` on undecodable input so the caller takes its `delta-error` arm:
    a delta that cannot be computed is UNESTABLISHED, and reading it as an empty set would
    say "nothing changed" about bytes nobody compared — the unknown-is-not-zero rule this
    repository applies everywhere else.

    A heading present on exactly one side counts as changed, so a section the revision
    ADDED or DELETED is in scope rather than silently absent from it.
    """
    try:
        a = _sections(before.decode('utf-8'))
        b = _sections(after.decode('utf-8'))
    except UnicodeDecodeError as exc:
        raise _DigestError(f'could not decode the draft bytes to compute the '
                           f'changed-section set: {exc}') from exc
    changed = [h for h in b if a.get(h) != b[h]]
    changed += [h for h in a if h not in b]
    return sorted(set(changed))


def _section_line_spans(text):
    """Each `## ` section's 1-based inclusive draft-line span, keyed as `_sections` keys.

    The line-number companion to `_sections` (issue #1105), derived from the same shared
    `_section_tokens` scan so a changed-section key resolves to the same section on both
    sides by construction. The scope-escape proxy needs a draft-line span for a scoped
    round, but the changed-section set names headings, not lines, so a changed heading is
    mapped back to the lines it occupies here.
    """
    return {key: (start, end) for key, start, end, _body in _section_tokens(text)}


def _scope_draft_lines(after_bytes, changed_sections):
    """The convex-hull draft-line span `[min_start, max_end]` over the changed sections.

    Issue #1105: the scope-escape proxy holds ONE `(start, end)` per round and tests
    `any(s <= line <= e)`, while the changed-section set is generally disjoint — so the
    recorded span is the convex hull over the changed sections' draft-line extents in the
    canonical (after) draft. That deliberately over-approximates a disjoint changed set,
    which over-counts escapes rather than under-counting them — the safe direction.

    Returns the two-element ordered-integer list `spec-context-eval.py` accepts, or
    `None` when no changed section has an extent in the after draft (an all-deletion delta,
    or undecodable bytes). `None` keeps the reader's honest `unestablished` rather than
    fabricating a span — the unknown-is-not-zero rule.
    """
    try:
        spans = _section_line_spans(after_bytes.decode('utf-8'))
    except UnicodeDecodeError:
        return None
    extents = [spans[h] for h in changed_sections if h in spans]
    if not extents:
        return None
    return [min(s for s, _ in extents), max(e for _, e in extents)]


def _enumerated_claims(state):
    """The run's live already-raised findings, as `(claim_id, summary)` pairs (issue #793).

    A claim id is `<round>.<entry id>`: entry ids are per-round positional (1..K, enforced
    by `_validate_ledger`), so a bare id would collide across rounds and let a return's
    verdict update the wrong ledger entry.

    EVERY earlier-round ledger entry is enumerated, regardless of status (issue #1105).
    The prior filter yielded only `unresolved` entries, but the shipped revision discipline
    records a resolution for every confirmed fix *before* the next round's kind is selected,
    so a run that fixes what it was told about and confirms the fixes emptied the very set a
    scoped round requires and dispatched every round cold — the better a run behaved, the
    more certainly it was ineligible. A resolved entry is also a self-attested fix produced
    by the same context that wrote the defect, which is exactly the claim a fresh-context
    auditor is best placed to falsify, so re-checking it is the point rather than waste. The
    drafter's own resolution becomes the input the round audits.

    Condition 4 in `select_round_kind` stays a real gate: a run with no earlier-round ledger
    entries at all still yields an empty set and selects the cold kind (`empty-claim-set`).

    The summary alone travels; no status, severity, disposition, prior verdict, rationale
    or evidence is read here, which is what keeps the caller physically unable to leak one —
    load-bearing under the widening, because a resolved claim that arrived carrying its
    prior verdict would be told the answer before it looked.
    """
    out = []
    for rnd, entry in _all_entries(state):
        out.append((f'{rnd["round"]}.{entry["id"]}', entry.get('summary') or ''))
    return out


def select_round_kind(state, canonical_path):
    """Derive the kind the NEXT round must take, from recorded facts alone (issue #793).

    Returns a dict carrying the kind, the reason token that selected it, the delta state
    and the enumerated claim ids — the read-only answer `query-round-kind` prints and
    `record-dispatch` cross-checks a caller's `--kind` against.

    **The selection fails toward the EXPENSIVE kind, never away from it.** `targeted` is
    selected only when all five conditions hold; every other input — including every
    unestablished one — selects `discovery` and names the failing condition. That
    direction is deliberate and is the whole safety argument for the mechanism: a
    wrongly-cold round costs tokens, while a wrongly-scoped round points the auditor at
    the wrong regions and returns a clean verdict over a draft nobody re-read.

    The conditions, complete by construction, in the order the code applies them:
      1. a recorded revision postdates the last completed round;
      2. that round's latest attempt was on the `file` arm (only there does a canonical
         file exist whose bytes the delta can be computed against);
      3. the round's dispatch bytes are recoverable from the byte history AND their
         recomputed digest equals the recorded dispatch digest;
      4. the enumerated claim set is non-empty (an empty set would make the round
         vacuously clean — the refusal `render-audit-prompt.py` also enforces);
      5. the computed changed-section set is non-empty and its computation did not error.

    Condition 5's basis — the digest of the canonical bytes the set was computed FROM — is
    answered as `basis_digest` and recorded on the scope file, because the skill re-runs
    the Step 3 gate between selection and dispatch: a byte edit landing in that window
    would point the auditor at superseded regions while carriage, regeneration and
    steering all still pass. `record-dispatch` refuses that dispatch by comparing its
    `--draft-file` digest against this basis.
    """
    def _answer(kind, reason, *, claims=None, sections=None, basis=None, draft_lines=None):
        # `claims` is the single representation; the ids are `[c for c, _ in claims]` at
        # the two sites that need them. Carrying a derived alias beside it made every
        # caller choose between two spellings of one fact.
        # `draft_lines` (issue #1105) is the convex-hull draft-line span over the changed
        # sections, recorded on a targeted round's frozen scope so the #889 scope-escape
        # proxy has its comparand. `None` on every non-targeted answer.
        return {'kind': _checked_kind(kind), 'reason': _checked_kind_reason(reason),
                'claims': list(claims or []),
                'sections': list(sections or []),
                'basis_digest': basis,
                'draft_lines': draft_lines}

    last = last_completed(state) if state is not None else None
    if last is None:
        # issue #1103 — split the old shared `no-completed-round` token into its two
        # materially different facts. `no-round-dispatched` is the genuine cold first
        # round (no round has been dispatched at all); `no-completed-round` is the
        # fall-off (a round WAS dispatched but never returned an outcome). The two are the
        # same kind but not the same fact, and the durable reason field records which.
        if state is None or not state.get('rounds'):
            return _answer('discovery', 'no-round-dispatched')
        return _answer('discovery', 'no-completed-round')
    if not _revision_postdates(state, last):
        return _answer('discovery', 'no-revision-after-round')
    attempts = last.get('attempts') or []
    if not attempts or attempts[-1].get('arm') != 'file':
        return _answer('discovery', 'not-file-arm')
    before = _reconstruct_dispatch_bytes(state, attempts[-1].get('digest'))
    if before is None:
        return _answer('discovery', 'dispatch-bytes-unrecoverable')
    claims = _enumerated_claims(state)
    if not claims:
        return _answer('discovery', 'empty-claim-set')
    try:
        if not canonical_path:
            # `--draft-file` is OPTIONAL off the file arm, and this selector runs on EVERY
            # dispatch — so an embed/inline dispatch arrives here with no path at all.
            # Raised (rather than tested inline) so it joins the one decided arm below:
            # without it `Path(None)` threw a raw TypeError out of a mutation command, on
            # exactly the arm the run falls back to when the canonical write has already
            # failed. Naming the cause keeps it distinguishable from an unreadable file.
            raise OSError('no canonical draft path was supplied')
        after = Path(canonical_path).read_bytes()
        basis = hash_bytes(after)
        sections = _changed_sections(before, after)
    except (OSError, TypeError, _DigestError):
        # An absent path, an unreadable canonical file and an undecodable one are the SAME
        # decided arm: the delta could not be computed, so it is unestablished. Never an
        # empty set. `TypeError` is caught alongside them so no future caller can
        # reintroduce the raw-traceback escape this arm exists to prevent.
        return _answer('discovery', 'delta-error', claims=claims)
    if not sections:
        return _answer('discovery', 'empty-delta', claims=claims, basis=basis)
    draft_lines = _scope_draft_lines(after, sections)
    return _answer('targeted', 'targeted-eligible', claims=claims, sections=sections,
                   basis=basis, draft_lines=draft_lines)


# The dispatch-scope file's format marker. Versioned so a future payload shape is a
# different marker rather than a silently-reinterpreted one, and carried as the file's
# first line so the renderer can refuse a file that is not one of these.
_SCOPE_MARKER = '<!-- prflow:dispatch-scope v1 -->'


def render_dispatch_scope(basis_digest, sections, claims):
    """The dispatch-scope file's bytes: the WHOLE `targeted` payload, in one artifact.

    Both payloads — the enumerated claims and the tool-derived changed-section set — travel
    here and nowhere else (issue #793). That is not tidiness: the file-arm instruction file
    is regenerated at return time and digest-compared over a CLOSED recorded tuple, and a
    divergence is sticky. A payload passed as an unrecorded render argument, or read from
    live run state, would make EVERY scoped round diverge — live ledger reads break it
    twice over, since post-close status mutations would give the return-time regeneration a
    different ledger than dispatch saw. Freezing the payload in a file whose path AND
    content digest both join the recorded tuple is what lets a scoped round establish
    steering on the same terms a cold one does.

    **The identity-data floor lives HERE, at the single write site**, so the closed
    protocol-token vocabulary stays in one module: the renderer imports stdlib only and the
    module dependency runs state-owner → renderer, so the refusal cannot be shared by
    import and must not be duplicated into a second, unlocked copy. A summary carrying a
    forged protocol token or a record-splitting byte is refused BEFORE it reaches the
    renderer.

    What is deliberately ABSENT is the point of the artifact: no status, no severity, no
    disposition, no prior verdict, no rationale and no evidence. The auditor learns what to
    CHECK, never what was CONCLUDED — the `fix_decision`-carrying shape this repository
    withholds from every independence-bearing pass.
    """
    lines = [_SCOPE_MARKER, f'basis_digest: {basis_digest}', 'sections:']
    for s in sections:
        lines.append(f'- {s}')
    lines.append('claims:')
    for cid, summary in claims:
        splitter = _record_splitting_char(summary)
        if splitter is not None:
            raise _DigestError(
                f'claim {cid} summary contains the record-splitting character '
                f'{splitter!r}; it would split one claim into two records in the '
                'rendered prompt')
        forged = _forged_protocol_token(summary)
        if forged is not None:
            raise _DigestError(
                f'claim {cid} summary contains the protocol token {forged + "="!r}; '
                'auditor-derived text may not forge a field of the tool\'s own printed '
                'surface')
        lines.append(f'- {cid} — {summary}')
    return ('\n'.join(lines) + '\n').encode('utf-8')


def parse_dispatch_scope(data):
    """Read a dispatch-scope file back into `(basis_digest, sections, claims)`.

    The renderer's own reader lives in `render-audit-prompt.py`; this one exists so the
    state owner can cross-check a dispatch's `--draft-file` digest against the recorded
    basis. Raises `_DigestError` on any shape outside the one `render_dispatch_scope`
    writes — a scope file is machine-written and machine-read, so a shape this does not
    recognize is a tampered or foreign artifact, never a dialect to accommodate.
    """
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise _DigestError(f'the dispatch-scope file is not valid UTF-8: {exc}') from exc
    lines = text.splitlines()
    if not lines or lines[0] != _SCOPE_MARKER:
        raise _DigestError('the dispatch-scope file does not open with its format marker')
    basis, sections, claims, mode = None, [], [], None
    for line in lines[1:]:
        if line.startswith('basis_digest: '):
            basis = line[len('basis_digest: '):].strip()
        elif line == 'sections:':
            mode = 'sections'
        elif line == 'claims:':
            mode = 'claims'
        elif line.startswith('- ') and mode == 'sections':
            sections.append(line[2:])
        elif line.startswith('- ') and mode == 'claims':
            body = line[2:]
            cid, _, summary = body.partition(' — ')
            claims.append((cid, summary))
        elif line.strip():
            raise _DigestError(f'unrecognized dispatch-scope line: {line!r}')
    if not basis:
        raise _DigestError('the dispatch-scope file records no basis digest')
    return basis, sections, claims


def _find_round(state, round_no):
    for r in state['rounds']:
        if r['round'] == round_no:
            return r
    return None


def _resolve_named_round(state, explicit_round):
    """Resolve the round a subcommand in `_ROUND_DEFAULTED` operates on (issue #795).

    Returns `(round_no, ambiguity_token)`. An explicit `--round` is honoured verbatim and
    validated downstream exactly as before — this resolver only supplies the number the
    state already uniquely determines when the caller omitted the flag.

    The state names exactly one candidate: the LAST recorded round. Every member of
    `_ROUND_DEFAULTED` targets it — `record-return` and `query-next-action` want it while
    it is open, and `record-adjudication` / `record-adjudication-render` /
    `record-coverage` want it once closed. Each caller then applies its OWN existing
    guard (duplicate-return, write-once adjudication, write-once coverage, the
    adjudicated-verdict precondition), so every refusal reachable on the explicit path
    stays reachable on the defaulted path — the resolver decides which round, never
    whether the transition is legal.

    `ambiguity_token` is non-None only where the state does NOT uniquely determine a
    round: there is no state at all, or no round has been recorded. Callers fail closed on
    it in their own class's shape — a mutation exits non-zero with a named breadcrumb and
    writes no state; a query still exits 0 and prints a decided answer carrying a
    `reason=` token.
    """
    if explicit_round is not None:
        return explicit_round, None
    if state is None:
        return None, 'state-unestablished'
    if not state.get('rounds'):
        return None, 'no-round-recorded'
    return state['rounds'][-1]['round'], None


def _require_named_round(prefix, doc, args):
    """Resolve a state-defaulted `--round` for a MUTATION, or fail closed (issue #795).

    Rebinds `args.round` to the resolved number and returns it, so every guard downstream
    runs against that number with its own breadcrumb text unchanged — which is what keeps
    every refusal reachable on the explicit path reachable on the defaulted path. It runs
    BEFORE the first guard and before any mutation of `doc`, so an ambiguity exits with no
    state write.

    The mutation members of `_ROUND_DEFAULTED` share this one call rather than each
    carrying its own copy of the breadcrumb: a four-way coupled literal drifts on the next
    edit. `query-next-action` deliberately does NOT use it — a query fails closed in its
    own class's shape (exit 0 plus a decided `reason=` token), never through `_fail`.
    """
    args.round, ambiguity = _resolve_named_round(doc, args.round)
    if ambiguity is not None:
        _fail(prefix, f'--round was omitted and the state does not uniquely determine a '
                      f'round ({ambiguity}); re-issue the call naming the round explicitly')
    return args.round


class _RenderRefusal(Exception):
    """A recorded value failed the `next_call=` render-boundary shape check."""

    def __init__(self, token):
        if token not in _NEXT_CALL_REFUSALS:
            raise AssertionError(
                f'issue-audit-state: _RenderRefusal({token!r}) is outside '
                '_NEXT_CALL_REFUSALS — the render boundary answers a closed set')
        super().__init__(token)
        self.token = token


# Flags whose rendered value is a filesystem path, and so must additionally satisfy the
# absolute-path shape `_is_bound_path` already enforces on the recorded binding.
_NEXT_CALL_PATH_FLAGS = ('--draft-file', '--path', '--instructions-file')

# Shell metacharacters refused outright in a rendered operand. The emitted line is a
# suggestion a human copies into a shell, so a recorded value carrying any of these would
# compose a command the state owner never intended.
_NEXT_CALL_METACHARACTERS = re.compile(r'[$`"\\;|&<>(){}\[\]*?!~\'\s]')


def _shape_check(flag, value):
    """Validate a state-derived operand before it is rendered into a `next_call=` line."""
    if isinstance(value, bool):
        # `bool` is an `int` subclass, so it would otherwise render as `True`/`False` —
        # neither of which is a legal operand value anywhere in this CLI.
        raise _RenderRefusal('render-value-not-a-string')
    if isinstance(value, int):
        # A round number is a legitimate state-derived integer operand; render its decimal
        # form, which by construction carries no newline and no metacharacter.
        return str(value)
    if not isinstance(value, str):
        raise _RenderRefusal('render-value-not-a-string')
    if _record_splitting_char(value) is not None:
        # The file's shared record-splitter predicate, not a private copy: the hazard is
        # identical (a value forging a LINE on the printed surface), so if that set ever
        # widens this boundary moves with the predicate's other callers.
        raise _RenderRefusal('render-value-carries-newline')
    if flag in _NEXT_CALL_PATH_FLAGS:
        if not _is_bound_path(value):
            raise _RenderRefusal('render-path-not-absolute')
        # A path legitimately carries `/` and, per `_is_bound_path`, may carry a SPACE — so
        # it cannot go through the metacharacter sweep below. It is SHELL-QUOTED instead of
        # exempted: the emitted line is a command a human pastes into a shell, so an
        # unquoted `/Users/jo/My Repos/d.md` would paste as two arguments and run a
        # different, wrong invocation. `shlex.quote` is a no-op on an ordinary path and
        # makes any other legal-but-awkward one paste back as the single argument recorded.
        # The newline/CR refusal above still binds and is not delegated to quoting.
        return shlex.quote(value)
    if _NEXT_CALL_METACHARACTERS.search(value):
        raise _RenderRefusal('render-value-carries-shell-metacharacter')
    return value


def _render_operand(target, flag, state_value):
    """Render one operand, or answer None meaning "bare, and named in `needs=`".

    `target` is the subcommand being RENDERED, never the one doing the rendering. The
    distinction is load-bearing and was got wrong: `_ROUND_IS_CALLER_INTENT` names the
    subcommands whose own `--round` is a branch discriminator (`record-dispatch`,
    `record-creation-epoch`), so keying it on the emitting command meant the guard could
    never fire — `query-arm` rendering a `record-dispatch` call filled `--round` from
    state and left it out of `needs=`, handing the caller a pre-decided branch, which is
    exactly the fail-open this class exists to prevent. It was inert only because every
    call site passes `None` for that operand today.

    Three outcomes, and the complement is decided rather than residual:
      * a member of `_CALLER_SUPPLIED_FLAGS` (or `--round` on a subcommand where it is
        the caller-intent operand) is always bare — never rendered with a value;
      * an operand the state holds is rendered filled, after `_shape_check`;
      * an operand in neither class — not caller-supplied, and not state-derivable — is
        also bare and named in `needs=`.
    """
    if flag in _CALLER_SUPPLIED_FLAGS:
        return None
    if flag == '--round' and target in _ROUND_IS_CALLER_INTENT:
        return None
    if state_value is None:
        return None
    return _shape_check(flag, state_value)


def _checked_next_call(line):
    """Fail closed on a `next_call=` answer outside the three sanctioned shapes.

    The same discipline `_checked_action` applies to `next_action`: the caller parses this
    line against a closed shape set, so a fourth shape would read as an unrecognized
    string mid-lifecycle. Constraining the resolver at its point of return is what keeps
    the shape set load-bearing rather than decorative.
    """
    if not (line == 'next_call=none'
            or _NEXT_CALL_UNESTABLISHED_RE.match(line)
            or line.startswith(f'next_call={_STATE_OWNER_PLACEHOLDER} ')):
        raise AssertionError(
            f'issue-audit-state: _resolve_next_call produced {line!r}, which matches none '
            'of the three sanctioned next_call shapes (an invocation line, next_call=none, '
            'or next_call=unestablished reason=<token>)')
    return line


def _next_call_invocation(cmd_name, subcommand, operands):
    """Compose an invocation line from `(flag, state_value)` pairs, in argument order.

    Every operand the state holds is filled; every caller-supplied or non-derivable one is
    rendered bare and collected into `needs=`. A `_RenderRefusal` from any operand aborts
    the whole line — a partially-rendered invocation would be worse than none, because the
    caller would run it.
    """
    parts, needs = [], []
    # The head of the subcommand being rendered — `_render_operand` classifies operands by
    # the TARGET, not by whoever is emitting the suggestion (see its docstring).
    target = subcommand.split(' ', 1)[0]
    for flag, state_value in operands:
        rendered = _render_operand(target, flag, state_value)
        if rendered is None:
            parts.append(flag)
            needs.append(flag)
        else:
            parts.append(f'{flag} {rendered}')
    # One token list, joined once. An earlier form built the line with an embedded
    # `" ".join(parts)` and squeezed doubled spaces afterwards — which both papered over the
    # empty-operand case and could have rewritten a legitimate double space inside a path
    # operand (`_shape_check` exempts paths from the metacharacter sweep).
    tokens = [f'next_call={_STATE_OWNER_PLACEHOLDER}', subcommand, *parts,
              f'needs={",".join(needs)}' if needs else 'needs=none']
    return ' '.join(tokens)


def _unestablished(reason):
    if reason not in _NEXT_CALL_REASONS:
        raise AssertionError(
            f'issue-audit-state: {reason!r} is not a member of _NEXT_CALL_REASONS — a '
            'reason token reaching the emitted surface must be declared, so a typo is a '
            'loud failure rather than an unknown-token branch at the caller')
    return f'next_call=unestablished reason={reason}'


# The dispatch-routing answers that mandate a `record-dispatch` call, and the arm (and
# marker, where the arm hard-requires one) each names. Translating an answer token into an
# invocation used to be prose work in a separately gated file; this table is what lets the
# tool publish the invocation instead. Each rendered answer names `--round` BARE — as does
# `query-arm`'s fresh-round answer — because the shipped procedure names those arms as
# where the forgotten-flag trap bites.
_DISPATCH_ROUTE = {
    'dispatch-embed-retry': ('embed', 'file-unreadable'),
    'dispatch-inline-degraded': ('inline', None),
}

# `dispatch-retry-same-arm` is DELIBERATELY absent from THIS table: the arm to retry is
# whichever the round already ran, which the table cannot name, so it is routed through
# `_ACTION_NOT_A_CALL` below to `unestablished reason=dispatch-arm-unestablished` rather
# than rendering a call with a guessed arm. It is not one of the routing answers that name
# `--round` bare — those are `query-arm`'s fresh-round answer plus this table's members.
# (Routing it explicitly is load-bearing: while it was merely absent it fell through to the
# generic `next-action-unestablished` tail, so the token the shipped procedure documents was
# never the token emitted.)

# Answer tokens whose mandated next step is NOT a tool call — a user interaction or a
# required verification — and the reason each answers with.
_ACTION_NOT_A_CALL = {
    'dispatch-retry-same-arm': 'dispatch-arm-unestablished',
    'proceed': 'boundary-offer',
    'revise-and-reaudit': 'verify-then-revise',
    'revise-then-evaluate-offer': 'verify-then-revise',
    'round-closed-no-verdict': 'round-closed-no-verdict',
    'round-open-awaiting-return': 'auditor-dispatch',
    # issue #793: the confirming whole-draft round routes through `query-arm` like any
    # fresh round rather than being rendered as a `record-dispatch` invocation here — the
    # arm is re-decided for it (the canonical file may have become unhashable since), and
    # `query-arm`'s own `next_call=` then renders the dispatch with the kind filled in.
    'confirm-whole-draft': 'dispatch-arm-unestablished',
}


# Every reason token the `next_call=unestablished` arm may carry, from ALL of its sources:
# the render-boundary refusals, the `_ACTION_NOT_A_CALL` values, the ad-hoc literals in
# `_next_call_body`, and `render-failed` (printed by `main()`'s broad catch). Collected into
# one closed set because `_checked_next_call` only shape-matches `[a-z0-9-]+`, so a typo
# (`state-unestablised`) sailed through and left a token-keyed caller on its unknown-token
# branch with nothing asserting the difference. Validated at `_unestablished()`, the single
# construction point, the way `_RenderRefusal` already validates its own token.
# Defined AFTER `_ACTION_NOT_A_CALL` because it composes it; `_unestablished` resolves this
# global at call time, so its own definition may sit above.
_NEXT_CALL_REASONS = frozenset(_NEXT_CALL_REFUSALS) | frozenset(_ACTION_NOT_A_CALL.values()) | {
    'advisory-record-rendering', 'auditor-dispatch', 'boundary-offer', 'draft-write',
    'foreign-nonce', 'nonce-unsupplied', 'no-round-recorded', 'render-failed',
    'round-unestablished', 'state-unestablished', 'user-approval', 'user-election',
    'next-action-unestablished', 'dispatch-arm-unestablished',
}


# ── Hoisted into this module by the issue #567 split ────────────────────────
# Each definition below stood after a caller the split separates it from, so it moved
# earlier to keep the sibling import graph acyclic. Bodies are unchanged.
def _steering_established(rnd):
    """True iff this round recorded an ESTABLISHED steering result.

    A round with no steering record at all answers False — the additive field means a
    pre-#709 round, a refused completion, or a degraded arm carries none, and every one
    of those is an unestablished property, never an established one.

    A round on which ANY dispatch attempt diverged from its canonical regeneration
    (issue #718) also answers False, regardless of what a later attempt recorded: the
    divergence is a fact about the round's instruction file, and letting a retry erase it
    would restore the laundering path the dispatch-time refusal was removed for.
    """
    if rnd.get('any_dispatch_diverged'):
        return False
    rec = rnd.get('steering')
    return isinstance(rec, dict) and rec.get('state') == 'established'


__all__ = [
    "_ACTION_NOT_A_CALL",
    "_DISPATCH_ROUTE",
    "_NEXT_CALL_METACHARACTERS",
    "_NEXT_CALL_PATH_FLAGS",
    "_NEXT_CALL_REASONS",
    "_SCOPE_MARKER",
    "_STALE_OVERRIDE_ELECTION",
    "_UNAUDITED_REVISION_REMEDY",
    "_RenderRefusal",
    "_all_entries",
    "_binding",
    "_bound_draft_file",
    "_bound_path",
    "_calibration_round",
    "_changed_sections",
    "_check_nonce",
    "_checked_action",
    "_checked_kind",
    "_checked_kind_reason",
    "_checked_next_call",
    "_clean_identity",
    "_convergence_basis",
    "_coverage_anchor_floor",
    "_coverage_round",
    "_effective_unresolved",
    "_emit_stale_override_remedy",
    "_emit_unaudited_revision_remedy",
    "_enumerated_claims",
    "_final_byte_answer",
    "_final_byte_honoured",
    "_final_byte_resolution_settled",
    "_final_byte_revoked",
    "_final_byte_round",
    "_find_round",
    "_funded_rounds",
    "_last_discovery_round",
    "_last_scoped_round",
    "_last_whole_draft_round",
    "_ledger",
    "_legality",
    "_next_call_invocation",
    "_no",
    "_offer_withheld",
    "_offer_withhold_reason",
    "_provenance_ordinal",
    "_reconstruct_dispatch_bytes",
    "_render_operand",
    "_require_named_round",
    "_resolve_named_round",
    "_revision_postdates",
    "_round_kind",
    "_scope_draft_lines",
    "_section_line_spans",
    "_section_tokens",
    "_sections",
    "_select_current_override",
    "_settling_ordinal",
    "_shape_check",
    "_staged_artifacts",
    "_steering_established",
    "_targeted_confirmation_needed",
    "_targeted_return_unusable",
    "_unestablished",
    "_unresolved_int",
    "_valid_override",
    "_validate",
    "_validate_adjudication_records",
    "_validate_coverage",
    "_yes",
    "classify_return",
    "completed_rounds",
    "evaluate_calibration",
    "evaluate_calibration_trigger",
    "evaluate_convergence",
    "evaluate_coverage",
    "evaluate_coverage_trigger",
    "evaluate_eligibility",
    "evaluate_final_byte_coverage",
    "evaluate_final_byte_trigger",
    "evaluate_triggers",
    "final_byte_passes",
    "final_byte_slot_unspent",
    "issue_token",
    "last_completed",
    "latest_revision_landed",
    "load_state",
    "next_action",
    "parse_dispatch_scope",
    "render_dispatch_scope",
    "revision_ordinal",
    "save_state",
    "select_round_kind",
    "stale_override_remedy",
    "validate_state_document",
]

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""The post-close ledger channels.

Part 4 of the `/prflow:spec` audit-lifecycle state owner. The CLI entry and
the two-class contract live in `scripts/issue-audit-state.py`, which imports this module
and re-exports every name in `__all__`; issue #567 split the bodies out so each source
file loads in one whole-file Read. This module adds no behavior of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from issue_audit_state_commands import (
    _attestation_frozen,
    _coverage_backing_line,
    _load_for_mutation,
    _next_call_ctx,
    _query_state,
    _render_count,
    _save_or_fail,
    _stdin_bytes_or_fail,
    _yn,
    route_arm,
    summary_fields,
)
from issue_audit_state_state import (
    _all_entries,
    _binding,
    _bound_draft_file,
    _check_nonce,
    _emit_stale_override_remedy,
    _emit_unaudited_revision_remedy,
    _find_round,
    _ledger,
    _offer_withheld,
    _offer_withhold_reason,
    _resolve_named_round,
    _staged_artifacts,
    completed_rounds,
    evaluate_calibration,
    evaluate_calibration_trigger,
    evaluate_convergence,
    evaluate_eligibility,
    evaluate_final_byte_trigger,
    evaluate_triggers,
    final_byte_passes,
    final_byte_slot_unspent,
    last_completed,
    latest_revision_landed,
    load_state,
    next_action,
    render_dispatch_scope,
    revision_ordinal,
    save_state,
    select_round_kind,
)
from issue_audit_state_vocab import (
    _ADJUDICATION_RECORD_CLASSES,
    _DRAFT_TIERS,
    _EVIDENCE_FIELDS,
    _EVIDENCE_OPTIONAL,
    _FINAL_BYTE_GRANT_CAP,
    _FINAL_BYTE_PASS_CAP,
    _IMPACT_BEARING_CLASSES,
    _USER_ROUND_CAP,
    StateError,
    _bound_evidence,
    _DigestError,
    _fail,
    _is_bound_path,
    _observed_divergent,
    evidence_completeness,
    evidence_conflicts,
    hash_bytes,
    hash_file,
    split_body,
)


def cmd_record_revision(args):
    doc = _load_for_mutation('record-revision', args.slug, args.nonce)
    # Do not route a zero-round state into the #705 file-arm guard below: with no round
    # there is no audit substrate to bind, and refusing here deadlocks the Step 4 iterate
    # loop so a recorded decline could never be invalidated by later bytes.
    zero_round = not doc['rounds']
    if not zero_round:
        # issue #705: the file-arm staged-write guarantee, enforced by the tool rather than
        # carried by prose a context compaction can evict. When the latest recorded round's
        # LAST dispatch attempt is on the file arm, the canonical draft file is currently the
        # audit substrate — so a revision recorded here MUST carry the intended-bytes digest,
        # or the post-revision write-failure closure (`latest_revision_landed`,
        # `record-write-failure`) has no durable comparand and cannot tell a landed replace
        # from a lost one. The predicate is the PER-ROUND shape
        # `rounds[-1]['attempts'][-1]['arm']`, deliberately NOT the eligibility site's
        # `file_arm_epoch` (which reads the creation-epoch round, a record that does not exist
        # at revision time). On the embed/inline arms the auditor was handed the bytes inline,
        # so there is no canonical file to bind and the bare (no-digest) call stays legal —
        # including a run whose earlier round dispatched on the file arm but whose latest round
        # fell back to embed. On the read-only arm no staging artifact can be written, but the
        # flag reads `sys.stdin.buffer`, never a file, so a run that merely cannot write a file
        # satisfies this guard by piping the intended bytes from context.
        if (doc['rounds'][-1]['attempts'][-1]['arm'] == 'file'
                and not getattr(args, 'stdin_digest', False)):
            _fail('record-revision',
                  'the latest recorded round dispatched on the file arm, so this revision must '
                  'carry the intended-bytes digest (file-arm-requires-stdin-digest): pipe the '
                  'revised title-and-body bytes to --stdin-digest. Without it the write-failure '
                  'closure has no durable comparand and a lost canonical replace cannot be '
                  'distinguished from a landed one.')
        # --after-round is the SOLE invalidation evidence on the event-ordering ground
        # (_revision_postdates keys eligibility and T2 on it), so a caller-supplied value
        # below the last completed round would fail that guard OPEN — a revised draft would
        # still answer eligible. Validate the operand against recorded facts: it must name
        # a round at or above the last completed one and no higher than the last recorded.
        last_num = doc['rounds'][-1]['round']
        lc = last_completed(doc)
        floor = lc['round'] if lc else 0
    else:
        last_num = 0
        floor = 0
    if args.after_round < floor or args.after_round > last_num:
        _fail('record-revision',
              f'--after-round {args.after_round} does not name a plausible round: the '
              f'last completed round is {floor} and the last recorded round is '
              f'{last_num} (a value below the last completed round would fail the '
              f'event-ordering staleness guard open)')
    # Persist the floor this call validated against, so _validate can re-check the same
    # rule at the READ boundary — the treatment _valid_override already gets, which
    # `after_round` did not inherit. The floor is NOT reconstructible at load: rounds
    # complete forward, so the CURRENT last-completed round is >= the floor that applied
    # when this revision was recorded, and re-deriving it would wrongly reject a
    # legitimately-older revision (recorded when only round 1 was complete, now with
    # round 3 complete). Recording it is what makes the invariant checkable later.
    # issue #562: when the revised bytes are piped on stdin (gated by an explicit flag so
    # a legacy caller that pipes nothing never blocks on a read), record their digest.
    # The post-revision `approve` closure and the landed-clearing predicate compare it
    # against a later landed file-arm dispatch digest, so a revision whose overwrite
    # failed cannot masquerade as audited bytes.
    stdin_digest = None
    if getattr(args, 'stdin_digest', False):
        # Revised bytes read from stdin, hoisted into main() above the section (issue
        # #1040); `_stdin_bytes_or_fail` reproduces the closed-fd and read-error breadcrumbs.
        data = _stdin_bytes_or_fail(args, 'record-revision', 'revised bytes')
        if not data:
            _fail('record-revision', '--stdin-digest was given but no revised bytes were '
                                     'received on stdin')
        try:
            stdin_digest = hash_bytes(data)
        except _DigestError as exc:
            _fail('record-revision', str(exc))
    rev = {'ordinal': len(doc['revisions']) + 1, 'after_round': args.after_round,
           'floor_round': floor}
    if stdin_digest is not None:
        rev['stdin_digest'] = stdin_digest
    # issue #792: a recorded revision supersedes the bytes an outstanding final-byte grant was
    # accepted for, so the grant is retracted here — exactly as the decline arm retracts one.
    # `record-dispatch` pops `final_byte_pending` at the top of its new-round branch WITHOUT
    # checking what funds that round, so an accept whose dispatch never happened (the
    # pre-dispatch canonical write failed — the degradation this feature is designed for) would
    # otherwise stamp the next ordinary, `record-offer`-funded discovery round as the pass:
    # double-funded, silently excluded from both axis selectors, and refunding a slot it never
    # drew from. The grant funded no round, so decrementing it keeps the funding sum consistent
    # with `len(doc['rounds'])`. The slot digest is left alone — the revision changes the
    # canonical digest, which re-arms the offer on its own.
    if doc.get('final_byte_pending'):
        doc['final_byte_pending'] = False
        doc['final_byte_passes_used'] = max(0, doc.get('final_byte_passes_used', 0) - 1)
    doc['revisions'].append(rev)
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-revision', str(exc))
    # The bare `ordinal=N` form is preserved for the no-byte-binding path (the legacy
    # contract); the stdin_digest field is appended only when a digest was recorded.
    out = f'ordinal={len(doc["revisions"])}'
    if stdin_digest is not None:
        out += f' stdin_digest={stdin_digest}'
    print(out)


def cmd_record_draft_binding(args):
    """Record the tiered draft-root binding, once per run (issue #562).

    The first landed canonical-draft write binds one absolute root for the rest of the
    run. Recorded two-rooted: the bound absolute ROOT (the readers join
    `.prflow/tmp/spec/<slug>/issue-draft-<slug>.md` onto it — see `_bound_draft_file`), its tier
    token, and the non-bound root (absolute when a resolver-answered tier-1 main root and
    a divergent tier-2 worktree root both exist; absent otherwise). Immutable — a second
    record is illegal, the forced-reinit path staying the only route to a fresh binding.
    """
    doc = _load_for_mutation('record-draft-binding', args.slug, args.nonce)
    if doc.get('draft_binding') is not None:
        _fail('record-draft-binding',
              'a draft-root binding is already recorded for this run '
              '(binding-already-recorded); it is immutable — a fresh binding requires the '
              'forced-reinit path (init --nonce --force)')
    if not _is_bound_path(args.path):
        _fail('record-draft-binding',
              f'the bound draft path {args.path!r} is not an absolute, single-line path '
              '(binding-path-not-absolute)')
    if not args.tier:
        _fail('record-draft-binding',
              'a bound-tier token is required (binding-tier-missing): one of '
              f'{", ".join(_DRAFT_TIERS)}')
    if args.tier not in _DRAFT_TIERS:
        _fail('record-draft-binding',
              f'the bound-tier token {args.tier!r} is outside the canonical set '
              f'(binding-tier-unknown): one of {", ".join(_DRAFT_TIERS)}')
    # An empty (or omitted) --non-bound-root is treated as "recorded absent" (the
    # breadcrumb/no-answer/failed-.git-test arm), so the skill can pass it unconditionally;
    # normalize once here.
    non_bound = args.non_bound_root or None
    if non_bound is not None and not _is_bound_path(non_bound):
        _fail('record-draft-binding',
              f'the non-bound root {non_bound!r} is present but not an absolute, '
              'single-line path (binding-nonbound-not-absolute)')
    doc['draft_binding'] = {
        'path': args.path,
        'tier': args.tier,
        'non_bound_root': non_bound,
    }
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-draft-binding', str(exc))
    b = doc['draft_binding']
    print(f'bound_path={b["path"]} tier={b["tier"]} '
          f'non_bound_root={b["non_bound_root"] or "none"}')


def cmd_query_round_kind(args):
    """Answer the kind the next round must take, read-only (issue #793).

    Prints the kind, the reason token that selected it, the delta state and the enumerated
    claim ids. Strictly read-only — it writes no state and no file — and it always exits 0
    once its arguments parse, exactly like every other query in this tool's read class. An
    unestablished input is answered as `discovery` with its failing condition named, never
    as a non-zero exit the caller has to interpret.

    The orchestrator obeys this answer; it never chooses a kind. The scope file a
    `targeted` round needs is written by `write-dispatch-scope`, deliberately a separate
    command, so this one can keep the read-only guarantee its class contract states.
    """
    state = _query_state(args.slug)
    if state is not None and state.get('nonce') != args.nonce:
        # A foreign nonce is not this run's state, so it must not answer for it. Reduced to
        # None so the ONE answer path below renders it — an arm that printed its own
        # hand-built line emitted a DIFFERENT field set (no `claim_ids=`) than the normal
        # arm, which is a shape a caller parsing this line cannot rely on.
        state = None
    ans = select_round_kind(state, args.draft_file)
    print(f'kind={ans["kind"]} reason={ans["reason"]} '
          f'sections={len(ans["sections"])} claims={len(ans["claims"])} '
          f'basis_digest={ans["basis_digest"] or "none"} '
          f'claim_ids={",".join(c for c, _ in ans["claims"]) or "none"}')


def cmd_write_dispatch_scope(args):
    """Write the round's frozen dispatch-scope file and report its identity (issue #793).

    Separate from `query-round-kind` because that query is contractually read-only, and
    separate from `record-dispatch` because the renderer must splice this file's content
    into the instruction file BEFORE the dispatch that hashes it.

    Refuses when the current selection is not `targeted` — including an empty claim set,
    which is the vacuous-pass shape the renderer refuses independently. Two refusals rather
    than one is deliberate: this one stops the artifact from existing at all, and the
    renderer's stops a hand-made one from rendering.
    """
    state = _query_state(args.slug)
    if state is None:
        _fail('write-dispatch-scope', 'the run state could not be established '
                                      '(state-unestablished)')
    if state.get('nonce') != args.nonce:
        _fail('write-dispatch-scope', 'the supplied nonce does not match this run '
                                      '(foreign-nonce)')
    ans = select_round_kind(state, args.draft_file)
    if ans['kind'] != 'targeted':
        _fail('write-dispatch-scope',
              f'the tool selects kind={ans["kind"]} reason={ans["reason"]} for the next '
              'round, so there is no scoped payload to write (kind-not-targeted)')
    try:
        data = render_dispatch_scope(ans['basis_digest'], ans['sections'], ans['claims'])
        digest = hash_bytes(data)
    except _DigestError as exc:
        _fail('write-dispatch-scope', str(exc))
    if not _is_bound_path(args.path):
        _fail('write-dispatch-scope',
              f'the scope path {args.path!r} is not a non-empty absolute path free of '
              'newline/carriage-return bytes (scope-path-not-absolute)')
    try:
        Path(args.path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.path).write_bytes(data)
    except OSError as exc:
        _fail('write-dispatch-scope', f'could not write the dispatch-scope file '
                                      f'{args.path}: {exc}')
    print(f'scope_path={args.path} scope_digest={digest} '
          f'basis_digest={ans["basis_digest"]} sections={len(ans["sections"])} '
          f'claims={len(ans["claims"])}')


def cmd_record_staged_write(args):
    """Record the RESOLVED path a `stage` landed at, durably (issue #793).

    `stage --path` is a base the helper completes with the staged bytes' digest, so the
    resolved leaf is known only to the process that computed it. That is fine within one
    turn and useless across turns — and the two things this run needs it for both happen
    across turns: the write-failure recovery arm must name the artifact to re-apply from
    after an interruption, and `select_round_kind` must reconstruct a round's dispatch
    bytes from the byte history. Recording it here is what makes the name survive a
    compaction, an interruption, and the death of the turn that produced it.

    The recorded digest must DESCRIBE the artifact, so it is re-derived from the file's
    own bytes and compared before anything is written. A pair recorded without that check
    is the one operand a changed-section delta must never be computed from: the delta's
    "before" side would be bytes nobody verified, and a wrong before-side points the
    auditor at regions the revision never touched while every downstream check still
    passes. This mirrors `apply`'s own `staged-digest-mismatch` refusal rather than
    inventing a second vocabulary for the same disagreement.

    Recording is idempotent on the `(path, digest)` pair: the history is a set of byte
    states, and a replayed record must not make one byte state read as two revisions.
    """
    doc = _load_for_mutation('record-staged-write', args.slug, args.nonce)
    if not _is_bound_path(args.path):
        _fail('record-staged-write',
              f'the staged path {args.path!r} is not a non-empty absolute path free of '
              'newline/carriage-return bytes (staged-path-not-absolute)')
    try:
        data = Path(args.path).read_bytes()
    except OSError as exc:
        _fail('record-staged-write',
              f'could not read the staging artifact {args.path}: {exc} '
              '(staged-artifact-unreadable)')
    try:
        actual = hash_bytes(data)
    except _DigestError as exc:
        _fail('record-staged-write', str(exc))
    if actual != args.digest:
        _fail('record-staged-write',
              f'the declared digest {args.digest!r} does not describe the bytes at '
              f'{args.path!r} (which hash to {actual!r}) (staged-digest-mismatch): the '
              'byte history is what a scoped round diffs against, so a pair that does not '
              'agree would compute a delta from bytes nobody verified')
    history = doc.setdefault('staged_paths', [])
    rec = {'path': args.path, 'digest': args.digest}
    if rec not in history:
        history.append(rec)
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-staged-write', str(exc))
    print(f'staged_write={args.path} digest={args.digest} recorded={len(history)}')


def cmd_query_staged_write(args):
    """Resolve a recorded staging artifact from state alone (issue #793).

    With `--digest`, answers the artifact recorded for THOSE bytes; without it, the newest
    recorded one. The digest form is what the write-failure recovery arm uses: a run
    holding several staged artifacts must re-apply the one that write recorded, not the
    newest on disk, and the revision's own recorded `stdin_digest` is precisely the value
    that names it.

    An unrecorded digest answers `none`. It never falls back to the newest artifact — a
    recovery arm handed the wrong bytes would replace the canonical file with a draft state
    the run never intended, which is worse than reporting that it cannot resolve one.
    """
    state = _query_state(args.slug)
    if state is None:
        print('staged_write=none digest=none reason=state-unestablished')
        return
    if state.get('nonce') != args.nonce:
        print('staged_write=none digest=none reason=foreign-nonce')
        return
    history = _staged_artifacts(state)
    if not history:
        print('staged_write=none digest=none reason=no-staged-write-recorded')
        return
    if args.digest:
        for dig, path in history:
            if dig == args.digest:
                print(f'staged_write={path} digest={dig}')
                return
        print('staged_write=none digest=none reason=digest-not-recorded')
        return
    dig, path = history[-1]
    print(f'staged_write={path} digest={dig}')


def cmd_record_write_failure(args):
    """Record a canonical-draft overwrite that failed to land at the bound path (#562).

    Each entry names the revision ordinal whose overwrite failed. `latest_revision_landed`
    reads this log: a recorded failure for the latest revision's ordinal makes it report
    unlanded, so the skill renders the presentation from the in-context revision bytes
    rather than the stale file — even when the revised bytes coincidentally hash to some
    earlier audited dispatch's digest. (The `approve` eligibility ground refuses the same
    write-failure shape independently, via `_revision_postdates`.)
    """
    doc = _load_for_mutation('record-write-failure', args.slug, args.nonce)
    # DEFERRED (issue #562 review, Suggestion): `--ordinal` is intentionally NOT validated
    # against the current revision chain here. A bogus/non-latest ordinal is recorded and
    # reported as success — but the effect is bounded and fails safe: `latest_revision_landed`
    # only consults `len(revs)`, and the `approve` eligibility gate backstops independently
    # via `_revision_postdates`, so a mis-supplied ordinal is a silent no-op, never a
    # fail-open. Strict chain-validation is withheld deliberately because the valid range is
    # not settled — a canonical-write failure at a round-initiating (non-revision) site is
    # also conceptually recordable here — so a `1..len(revisions)` guard risks over-rejecting
    # a legitimate entry. Revisit if a non-revision write-failure consumer is added.
    doc.setdefault('write_failures', []).append(args.ordinal)
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-write-failure', str(exc))
    print(f'write_failure_recorded ordinal={args.ordinal} '
          f'count={len(doc["write_failures"])}')


def _binding_line(state):
    """The binding query's single-line answer, from recorded facts (fail-closed).

    A crash is never the answer (the query exit contract): with no binding recorded it
    answers the decided `bound=none` token so the enumerations and fallback marker read
    a token, never a traceback.
    """
    b = _binding(state) if state is not None else None
    if not b:
        # `latest_revision_landed=yes` here is vacuous by construction, NOT a dropped
        # `latest_revision_landed(state)` call: an unbound run is an embed/inline epoch
        # that never bound a canonical file, so there is no bound-path write that could
        # fail to land. The bound branch below emits the real predicate.
        return 'bound=none tier=none non_bound_root=none latest_revision_landed=yes'
    return (f'bound={b["path"]} tier={b["tier"]} '
            f'non_bound_root={b["non_bound_root"] or "none"} '
            f'latest_revision_landed={latest_revision_landed(state)}')


def cmd_query_draft_binding(args):
    """Emit the recorded binding: bound path, tier token, non-bound root, landed flag."""
    state = _query_state(args.slug)
    # Nonce check inline like the sibling queries: a foreign-nonce query answers the
    # fail-closed token rather than a foreign run's binding.
    if state is not None and args.nonce and state.get('nonce') != args.nonce:
        sys.stderr.write('issue-audit-state.py query-draft-binding: nonce mismatch — '
                         'answering fail-closed\n')
        # Reuse the unbound answer shape (never drift a second copy) + the reason.
        print(f'{_binding_line(None)} reason=foreign-nonce')
        return
    # DEFERRED (issue #562 review, Suggestion): a genuinely-unbound run and an unestablished
    # (corrupt/unreadable) state both answer the identical fail-closed `bound=none …` token —
    # `_query_state` collapses "no state file" and "state failed validation" to the same None
    # (a pre-existing property shared by every sibling query). Distinguishing them with a
    # `reason=state-unestablished` clause would require reworking that shared `_query_state`
    # contract to signal absent-vs-corrupt to all callers, out of proportion for this
    # state-owner foundation. Both cases are correct and fail-closed today (bound=none);
    # revisit as a shared-query-surface seam if the caller needs the distinction.
    line = _binding_line(state)
    print(line)
    return _next_call_ctx(bound=not line.startswith('bound=none'))


def cmd_record_override(args):
    doc = _load_for_mutation('record-override', args.slug, args.nonce)
    digest = None
    if args.draft_file:
        try:
            digest = hash_file(args.draft_file)
        except _DigestError as exc:
            _fail('record-override', str(exc))
    if args.kind == 'user-decline' and not args.surface:
        _fail('record-override', 'a user-decline override must name the surface it was '
                                 'recorded at')
    # Validate the override against recorded facts, exactly as record-revision does with
    # --after-round: an override grounds eligibility, so an operand this path accepts
    # without checking is a gate that fails OPEN. Issue #1751 makes a zero-round
    # `user-decline` legitimate (the user declined every offer, so there is no audit but
    # the decline is the recorded election that grounds filing); a zero-round `cap-reached`
    # stays incoherent — a ceiling cannot be reached before any round ran — so it keeps
    # failing closed with the existing message.
    epoch = last_completed(doc)
    if epoch is None:
        if args.kind != 'user-decline':
            _fail('record-override',
                  'no round has completed, so there is no audit for an override to '
                  'override: recording one here would ground eligibility on a draft the '
                  'tool never audited')
        # Do not extend the file-arm bind check below to this arm: there is no epoch to
        # dereference at zero rounds, so it would refuse every declined run.
    elif epoch['attempts'][-1]['arm'] == 'file' and not digest:
        # --draft-file is optional in the argparse surface because the embed/inline arms
        # have no trustworthy canonical file to bind. On a file-arm epoch one exists, so
        # an unbound override would skip the byte comparison entirely and pass ANY bytes.
        # `not digest` (not `digest is None`) so an empty-string digest is refused too.
        _fail('record-override',
              'the current epoch is a file-arm round, so this override must bind the '
              'draft it permits: pass --draft-file (an override with no recorded digest '
              'is never compared against the draft, so it would permit any bytes)')
    doc['overrides'].append({'kind': args.kind, 'surface': args.surface,
                             'recorded_at_ordinal': len(doc['revisions']),
                             'draft_digest': digest})
    if args.kind == 'cap-reached':
        if doc.get('user_rounds_used', 0) < _USER_ROUND_CAP:
            _fail('record-override',
                  f'cap-reached recorded before the ceiling: user_rounds_used is '
                  f'{doc.get("user_rounds_used", 0)} of {_USER_ROUND_CAP} — a premature '
                  f'cap record would silently burn the remaining user rounds')
        doc['user_rounds_used'] = _USER_ROUND_CAP
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-override', str(exc))
    print(f'kind={args.kind} ordinal={len(doc["revisions"])} digest={digest or "none"}')


def cmd_record_degraded(args):
    doc = _load_for_mutation('record-degraded', args.slug, args.nonce)
    rnd = _find_round(doc, args.round)
    if rnd is None:
        _fail('record-degraded', f'no round {args.round} is recorded')
    rnd['degraded'] = True
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-degraded', str(exc))
    print(f'round={args.round} degraded=true reason={args.reason}')


def cmd_record_offer(args):
    doc = _load_for_mutation('record-offer', args.slug, args.nonce)
    used = doc.get('user_rounds_used', 0)
    if args.accepted:
        # issue #548: refuse (before the ceiling check, before the increment) while the last
        # completed discovery round's unresolved must-revise findings are unrevised, so an
        # accepted round cannot fund a re-audit on the same unrevised bytes. Same
        # fail-before-save_state shape as the ceiling refuse; the counter stays put.
        if _offer_withheld(doc):
            _fail('record-offer',
                  'the last completed audit round left unresolved must-revise findings that '
                  'are not yet revised, or their count is unestablished; apply and record the '
                  'revision before funding another audit round (unresolved-revise-pending)')
        if used >= _USER_ROUND_CAP:
            _fail('record-offer', f'user-chosen rounds are capped at {_USER_ROUND_CAP} '
                                  'per run; the ceiling is already reached')
        doc['user_rounds_used'] = used + 1
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-offer', str(exc))
    print(f'user_rounds_used={doc["user_rounds_used"]} cap={_USER_ROUND_CAP}')


def resolve_draft_digest(prefix, state_or_doc, args):
    """The current canonical draft digest, or `(None, digest_failed)`.

    The single owner of the issue-#562 precedence rule for the digest-reading surfaces that
    breadcrumb-and-continue: prefer the RECORDED bound draft file over the caller's
    `--draft-file`, so a compacted context that hands a drifted path cannot redirect which
    file the answer grounds on; fall back to `--draft-file` only on an unbound run.

    A digest failure is surfaced on stderr and never swallowed — a silent one would
    misattribute the resulting refusal (`unaudited-revision` rather than the honest
    `draft-undigestible`). Queries stay exit-0; this is a breadcrumb, not a failure exit.
    `prefix` names the calling command in that breadcrumb.

    Two digest-reading surfaces deliberately do NOT route through here, because their
    failure shape differs: `cmd_emit_body` reads the bytes it is about to emit and `_fail`s
    rather than breadcrumbing, and `cmd_record_creation_epoch` hashes the BODY-ONLY split of
    the file it is binding. Neither is covered by the precedence claim above.
    """
    source = _bound_draft_file(state_or_doc, args.slug) or args.draft_file
    if not source:
        return (None, False)
    try:
        return (hash_file(source), False)
    except _DigestError as exc:
        print(f'{prefix}: could not hash draft file {source}: {exc}', file=sys.stderr)
        return (None, True)


def cmd_record_final_byte_offer(args):
    """Record the outcome of the final-byte exact-byte offer (issue #792).

    The named producer that spends the dedicated slot. Deliberately NOT `record-offer`
    and deliberately NOT an override:

      - it never touches `user_rounds_used` and is never subject to `_USER_ROUND_CAP`, so
        the pass is fundable on a run whose user-round ceiling is already reached and on a
        run carrying a `cap-reached` override — the two states the dedicated slot exists
        to keep FUNDABLE (not the only states the offer fires in);
      - a DECLINE is recorded on this dedicated channel, which the override-validity gate
        cannot see. `_valid_override` ignores the surface token entirely and answers
        `eligible ground=override` on any current digest-matching override, so routing
        this decline through `_OVERRIDE_KINDS` would make "skip the optional safety pass"
        byte-indistinguishable from the deliberately narrow election to file bytes the
        audit never cleared. Recorded here, the decline grounds no eligibility answer.

    BOTH outcomes spend the slot for the current canonical digest, so the offer does not
    re-fire against unchanged bytes as Step 4's iterate loop returns to the approval
    election. Only an accept increments the pass counter and arms the next dispatch,
    because only an accept opens a round.
    """
    doc = _load_for_mutation('record-final-byte-offer', args.slug, args.nonce)
    digest, digest_failed = resolve_draft_digest('record-final-byte-offer', doc, args)
    if digest_failed:
        _fail('record-final-byte-offer',
              'the canonical draft file could not be hashed, so the slot cannot be keyed '
              'to the bytes this offer covered; fix the draft file and re-record')
    if digest is None:
        _fail('record-final-byte-offer',
              'no canonical draft digest is available (no recorded draft binding and no '
              '--draft-file); the final-byte slot is spent PER DIGEST and cannot be '
              'recorded without one')
    # These two refusal arms read the SHARED derivations rather than open-coding their terms, so
    # the producer and the read side can never disagree about whether the slot is spendable. They
    # are kept separate only to name distinct causes in the breadcrumb. Each of the three
    # LEGALITY refusals — these two plus the grant-ceiling arm further down, which reads the raw
    # grant count directly because no shared derivation exposes it — embeds its registered
    # transition reason token, so the message and the closed vocabulary cannot drift apart. The
    # two digest-availability refusals above are deliberately NOT in that set: an unhashable or
    # absent draft is a caller-input failure, not an illegal lifecycle transition, so it has no
    # transition row and no registered token to embed.
    if final_byte_passes(doc)[1]:
        _fail('record-final-byte-offer',
              f'(final-byte-pass-cap-reached) final-byte passes are capped at '
              f'{_FINAL_BYTE_PASS_CAP} per run; the ceiling is already reached, so this run '
              f'files with the coverage field reporting its true value and the exhaustion '
              f'disclosed on the summary line')
    if not final_byte_slot_unspent(doc, digest):
        _fail('record-final-byte-offer',
              '(final-byte-slot-already-spent) the final-byte slot is already spent for '
              'these exact bytes; it re-arms only when a recorded revision changes the '
              'canonical digest')
    doc['final_byte_slot_digest'] = digest
    # `final_byte_pending` is a SINGLE armed grant that `record-dispatch` pops exactly once.
    # An accept while one is already outstanding therefore ABSORBS it — re-pointing the armed
    # grant at these bytes — rather than incrementing again: a second increment would fund a
    # round no `final_byte_pass` flag could ever mark, which is precisely the phantom round the
    # funding test's own guard exists to prevent, and which no refund could reach. A DECLINE
    # clears the flag, so a stale arm from an abandoned accept can never mark a later, ordinary
    # round as the pass (which would silently exclude it from both axis selectors).
    grant = 'none'
    if args.accepted:
        if doc.get('final_byte_pending'):
            grant = 'absorbed'
        else:
            # The grant ceiling gates GRANTS ONLY — checked here, inside the accept arm, never
            # above both arms. Gating the decline too would make the offer unrecordable at the
            # ceiling: neither arm could be recorded, the slot would never be spent, and the
            # trigger would hold again on every return to the approval election — removing the
            # user's exit from the very loop this ceiling exists to bound, rather than
            # backstopping it.
            if doc.get('final_byte_passes_used', 0) >= _FINAL_BYTE_GRANT_CAP:
                _fail('record-final-byte-offer',
                      f'(final-byte-grant-ceiling-reached) this run has been granted '
                      f'{_FINAL_BYTE_GRANT_CAP} final-byte passes and no further pass can be '
                      f'granted; a refund returns honoured-pass headroom but the grant ceiling '
                      f'is absolute, so a host on which every pass degrades cannot loop here '
                      f'indefinitely. Decline the offer to proceed.')
            grant = 'new'
            doc['final_byte_passes_used'] = doc.get('final_byte_passes_used', 0) + 1
        doc['final_byte_pending'] = True
    elif doc.get('final_byte_pending'):
        # A decline over an OUTSTANDING grant retracts it. That grant funded no round — the
        # accept armed it and no dispatch consumed it — so the never-decrement-on-refund rule
        # above does not reach it, and leaving it would fund a phantom round that no ceiling saw,
        # that no `final_byte_pass` flag marks, and that no refund could ever reach.
        grant = 'retracted'
        doc['final_byte_passes_used'] = max(0, doc.get('final_byte_passes_used', 0) - 1)
        doc['final_byte_pending'] = False
    else:
        doc['final_byte_pending'] = False
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-final-byte-offer', str(exc))
    # No `slot=` field: both arms spend the slot, so the token could never vary — a
    # printed constant trains a reader to skip the line, and still costs a protocol-token
    # registration. `outcome=` is what actually distinguishes the two arms.
    print(f'final_byte_passes={final_byte_passes(doc)[0]} '
          f'cap={_FINAL_BYTE_PASS_CAP} '
          f'grant={grant} '
          f'outcome={"accepted" if args.accepted else "declined"}')


def cmd_query_final_byte(args):
    """The final-byte trigger, on its OWN query (issue #792).

    Single-line, decided output on every arm, exit 0 once the arguments parse, exactly
    like its siblings. See `evaluate_final_byte_trigger` for why this is answered here
    rather than on `query-triggers`.
    """
    state = _query_state(args.slug)
    # A foreign nonce collapses the state to unestablished and overrides only the REASON,
    # then falls through to the SINGLE formatter below — never a second hand-written copy
    # of the field run, which a sixth field would silently leave behind (the same
    # fall-through idiom `cmd_query_summary` uses).
    reason_override = None
    if state is not None and state['nonce'] != args.nonce:
        state, reason_override = None, 'foreign-nonce'
    digest, digest_failed = resolve_draft_digest('query-final-byte', state, args)
    t = evaluate_final_byte_trigger(state, digest, digest_failed=digest_failed)
    passes, exhausted = final_byte_passes(state)
    print(f'final_byte_trigger={"hold" if t["holds"] else "not-hold"} '
          f'final_byte_coverage={t["coverage"]} '
          f'final_byte_reason={reason_override or t["reason"] or "none"} '
          f'final_byte_passes={passes} '
          f'final_byte_exhausted={_yn(exhausted)}')


def _draft_body_digest(draft_file):
    """The body-only digest of a canonical draft file, or `_fail` on a read/hash error.

    Shared by both `record-creation-epoch` binding arms so their identical
    read->split->hash step and its refusal message cannot drift apart.
    """
    try:
        return hash_bytes(split_body(Path(draft_file).read_bytes()))
    except (OSError, _DigestError) as exc:
        _fail('record-creation-epoch',
              f'could not hash the draft file to bind the creation epoch: {exc}')


def _current_zero_round_decline(doc):
    """The current `user-decline` override on a zero-round state, or None (issue #1751).

    Only meaningful when no round has completed: it is what lets a declined run bind
    creation to its recorded election rather than to a round it never ran.
    """
    if last_completed(doc) is not None:
        return None
    now = revision_ordinal(doc)
    for ov in reversed(doc['overrides']):
        if ov.get('kind') == 'user-decline' and ov.get('recorded_at_ordinal') == now:
            return ov
    return None


def _record_decline_bound_epoch(doc, decline, args):
    """Bind creation to a zero-round user-decline (issue #1751).

    The epoch's arm is the decline's own file arm — a decline-bound epoch always supplies
    a canonical draft — and the body-only digest is recomputed from that draft at record
    time. It is NEVER inherited from the override's whole-file digest: that is a different
    split, so inheriting it would compare a whole-file hash against a body-only comparand
    and report a false `mismatch` on every declined run.
    """
    if _attestation_frozen(doc):
        _fail('record-creation-epoch',
              'an attestation is already recorded; re-binding the creation epoch would '
              'silently discard that tamper evidence')
    # Do not relax this into an unbound epoch when the decline itself is unbound: the
    # decline/draft digest match is enforced at the eligibility boundary (`_valid_override`),
    # which an epoch recorded with no comparand would leave with nothing to compare.
    if not args.draft_file:
        _fail('record-creation-epoch',
              'a decline-bound creation epoch must recompute the body-only digest from '
              'the canonical draft: pass --draft-file')
    body_only_digest = _draft_body_digest(args.draft_file)
    doc['creation'] = {'epoch_round': None, 'epoch_arm': 'file',
                       'body_only_digest': body_only_digest, 'attestation': None}
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-creation-epoch', str(exc))
    print(f'epoch_round=none body_digest={body_only_digest}')


def cmd_record_creation_epoch(args):
    doc = _load_for_mutation('record-creation-epoch', args.slug, args.nonce)
    rnd = _find_round(doc, args.round)
    if rnd is None:
        # issue #1751: a declined run has no round to bind, but its recorded user-decline
        # election grounds creation exactly as a completed round does. Any other no-round
        # state is the existing refusal.
        decline = _current_zero_round_decline(doc)
        if decline is not None:
            _record_decline_bound_epoch(doc, decline, args)
            return
        msg = f'no round {args.round} is recorded to bind creation to'
        newest = last_completed(doc)
        if newest is not None:
            # issue #82/#795: name the newest completed round in the refusal — never bind
            # it here. record-creation-epoch is _ROUND_IS_CALLER_INTENT; the caller re-issues.
            msg += f'; a run with completed rounds binds --round {newest["round"]}'
        _fail('record-creation-epoch', msg)
    if rnd.get('outcome') is None:
        _fail('record-creation-epoch', f'round {args.round} is still open; creation '
                                       'can only bind a completed round')
    if _attestation_frozen(doc):
        # attestation-unavailable is NOT tamper evidence (it is the honest unknown), so
        # a corrective retry may re-bind past it; match/mismatch stay frozen.
        _fail('record-creation-epoch',
              'an attestation is already recorded; re-binding the creation epoch would '
              'silently discard that tamper evidence')
    attempt = rnd['attempts'][-1]
    # The attestation comparand is the digest of the bytes the creation will ACTUALLY post,
    # not the audited round's dispatch digest. On a file-arm epoch the posting sources from
    # the current canonical file via emit-body, and eligibility may ground on a still-current
    # override whose bytes postdate the audited round (a user-elected "file anyway" over a
    # REVISE verdict) — so binding attempt['body_digest'] there would record the OLD audited
    # bytes and make the post-hoc attestation a structurally-guaranteed `mismatch` on a
    # legitimate override filing that GitHub stored faithfully (a false tamper signal, PR #552
    # review). Bind the current draft-file body digest instead, so the attestation compares
    # fetched-vs-posted like-for-like. On the file-identity ground the two are equal by
    # construction (eligibility required the file's full digest to equal the round's), so this
    # is a no-op there. On embed/inline epochs there is no trustworthy canonical file to point
    # at (the disclosed weaker-identity residual the module header describes), so the audited
    # round body digest remains the comparand and the attestation stays their detection surface.
    body_only_digest = attempt['body_digest']
    if args.draft_file and attempt['arm'] == 'file':
        body_only_digest = _draft_body_digest(args.draft_file)
    doc['creation'] = {'epoch_round': args.round, 'epoch_arm': attempt['arm'],
                       'body_only_digest': body_only_digest, 'attestation': None}
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-creation-epoch', str(exc))
    print(f'epoch_round={args.round} body_digest={body_only_digest}')


def cmd_record_creation_attestation(args):
    doc = _load_for_mutation('record-creation-attestation', args.slug, args.nonce)
    if not doc.get('creation'):
        _fail('record-creation-attestation', 'no creation epoch is recorded; there is '
                                             'nothing to attest against')
    if _attestation_frozen(doc):
        _fail('record-creation-attestation',
              'an attestation is already recorded for this epoch; the attestation is '
              'forward-only tamper evidence and cannot be overwritten')
    if args.attestation_unavailable:
        status = 'attestation-unavailable'
    else:
        # The fetched body is read from stdin, hoisted into main() above the section (issue
        # #1040); `_stdin_bytes_or_fail` reproduces the named closed-fd and read-error
        # breadcrumbs verbatim rather than letting a raw traceback break the mutation
        # contract on this tamper-detection surface (see record-dispatch's twin).
        data = _stdin_bytes_or_fail(args, 'record-creation-attestation', 'the fetched body')
        # Empty fetched bytes are COMPARED, not laundered into unavailable: an empty
        # created body from a successful fetch is exactly the empty-bodied-issue
        # failure the posting guard exists to catch, and the recorded digest makes the
        # compare well-defined either way. A genuinely failed fetch is the explicit
        # --attestation-unavailable flag, never inferred from emptiness.
        try:
            got = hash_bytes(data)
        except _DigestError as exc:
            _fail('record-creation-attestation', str(exc))
        status = 'match' if got == doc['creation']['body_only_digest'] else 'mismatch'
        if status == 'mismatch' and data.endswith(b'\n'):
            # Bounded, disclosed tolerance: gh/jq fetch framing appends exactly one
            # trailing newline the posted bytes never carried. Retry the compare
            # with ONE trailing newline stripped; anything else stays a mismatch.
            # Accepted residual: server-side trailing-whitespace normalization, or a
            # second framing newline, still renders a spurious `mismatch`. Widening
            # the tolerance would blunt the tamper-evidence surface, and the false
            # positive is loud and post-hoc (creation is never rolled back), so the
            # one-byte bound is kept.
            try:
                if hash_bytes(data[:-1]) == doc['creation']['body_only_digest']:
                    status = 'match'
                    print('record-creation-attestation: matched modulo the '
                          "fetch's single trailing newline", file=sys.stderr)
            except _DigestError:
                pass
    # Stored as the BARE status token — the summary field renders it verbatim into the
    # single-line key=value surface, so a nested object here would corrupt that line.
    doc['creation']['attestation'] = status
    try:
        save_state(doc, args.slug)
    except StateError as exc:
        _fail('record-creation-attestation', str(exc))
    print(f'attestation={status}')


def _record_one_finding_evidence(doc, round_, finding_id, supplied, prefix):
    """Store one finding's evidence entry under `<round>:<finding-id>`, applying the
    overwrite-conflict guard, and return `(key, completeness, missing)`.

    Shared by the single-finding and batched (`--finding-evidence-records-file`, issue #1803)
    `record-finding-evidence` forms, so both apply the identical conflict/carry-forward rules.
    `supplied` is the ordered `(field, value-or-None)` pairs; the caller saves the doc.
    """
    entry = {k: _bound_evidence(v) for k, v in supplied if v is not None}
    completeness, missing = evidence_completeness(entry)
    entry['completeness'] = completeness
    key = f'{round_}:{finding_id}'
    store = doc.setdefault('finding_evidence', {})
    prior = store.get(key)
    if prior is not None:
        # Last-write-wins would silently collapse two disagreeing probes of ONE finding to the
        # later value — the same one-sided resolution `evidence_conflicts` refuses across
        # findings. The compared identity is every `_EVIDENCE_FIELDS` value, not `observed`
        # alone (`completeness` needs no row — it is derived from those same fields):
        # two probes that disagree about WHERE the defect is (`locator`) or HOW it was
        # measured (`command`) while coincidentally producing the same bytes — routine for
        # low-entropy outputs like `0`, an empty result, or a single count line — are exactly
        # the disagreement this refusal exists to surface, and comparing only `observed` let
        # the first probe's locator, command and baseline vanish at `conflict=none`.
        # `observed` alone is judged by `_observed_divergent`, not plain inequality, so a pair
        # `_bound_evidence` truncated to byte-identical strings is refused too: the comparison
        # could not see the bytes past the cap, and unknown is never agreement. A byte-for-byte
        # identical, untruncated re-record stays a legal idempotent replay. `completeness`
        # needs no row of its own: it is derived from these same fields, so it cannot diverge
        # independently of them.
        #
        # An OMITTED field is not a disagreement. `_EVIDENCE_FIELDS` includes the optional
        # `baseline_identity`, which the module documents an auditor under the Step 3.6
        # information diet as unable to supply — so comparing a field absent from BOTH sides,
        # or newly absent on a replay that simply did not pass the flag, would refuse a probe
        # that observed nothing different and then tell the operator to invent a second
        # finding id, injecting a phantom finding into the ledger and into
        # `evidence_conflicts`' grouping.
        changed = [f for f in _EVIDENCE_FIELDS
                   # An OMITTED optional field is not a claim, so it cannot contradict one.
                   # Required fields keep comparing when absent — dropping one on a re-record
                   # loses the first probe's data, which is what this guard exists to stop.
                   if not (f in _EVIDENCE_OPTIONAL and f not in entry)
                   and (_observed_divergent(prior.get(f), entry.get(f)) if f == 'observed'
                        else prior.get(f) != entry.get(f))]
        # An exempted optional field is CARRIED FORWARD, never dropped. Skipping the
        # comparison is only half the rule: the write below replaces the whole entry, so a
        # replay that merely omitted the flag would delete the identity the first probe
        # recorded — at exit 0, with no breadcrumb. That is the same first-probe data loss
        # this guard exists to stop, arriving through the exemption instead of past it.
        #
        # Accepted consequence, named rather than left to be discovered: an optional value is
        # therefore WRITE-ONCE for the life of the key. Omitting the flag restores it and
        # supplying a different one is refused, so a probe that must RETRACT a wrong optional
        # value cannot do it through a replay — the decided recovery is to re-init the run,
        # never to file a phantom finding id. Reversing this would need an explicit clearing
        # flag; a bare omission must never mean "clear", which is the Critical this closes.
        for _opt in _EVIDENCE_OPTIONAL:
            if _opt not in entry and _opt in prior:
                entry[_opt] = prior[_opt]
        if changed:
            # Name every cause that applies, and ONLY what was actually established. Three
            # ways to get this wrong, all of them observed in this PR's own review rounds:
            # attaching the truncation clause to a locator-only divergence sends the reader
            # to a cap that was never hit; dropping the field list when truncation co-occurs
            # hides the real disagreement; and listing a truncation-only `observed` under
            # "differs" asserts a difference the comparison explicitly could NOT see —
            # `_observed_divergent` refused because unknown is never agreement, which is not
            # the same claim as "these differ". So `observed` is named as a difference only
            # when it genuinely differed, and the truncation is stated as its own clause.
            truncated_only = ('observed' in changed
                              and prior.get('observed') == entry.get('observed'))
            differing = [f for f in changed if not (f == 'observed' and truncated_only)]
            clauses = []
            if differing:
                clauses.append(f'differs in {",".join(differing)}')
            if truncated_only:
                clauses.append('could not establish `observed` equality (both observations '
                               'are truncated)')
            _fail(prefix, f'evidence-overwrite-differs: {key} already carries evidence that '
                          f'{" and ".join(clauses)}; record the second probe under its own '
                          f'finding id so the disagreement is surfaced, never overwritten')
    store[key] = entry
    return key, completeness, missing


def _ingest_finding_evidence_records(path):
    """Read a round's per-finding evidence records from a JSON file, or fail closed.

    issue #1803: the batched form of `record-finding-evidence` — one call records a whole
    round's evidence, mirroring the `--advisory-records-file` ingestion (issue #743). Each
    array object carries a required non-negative-int `finding_id` and the optional string
    fields `locator`/`command`/`observed`/`baseline_revision`/`baseline_identity`; an absent
    or empty content field is NOT refused (it records the entry `incomplete`, exactly as the
    per-finding form does), but a structurally malformed file, a duplicate finding id, or a
    non-string field IS. Returns the ordered list of validated record dicts.
    """
    prefix = 'record-finding-evidence'
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        _fail(prefix, f'could not read the finding-evidence records file {path!r} '
                      f'(finding-evidence-records-unreadable): {exc}')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        _fail(prefix, f'the finding-evidence records file is not valid UTF-8 '
                      f'(finding-evidence-records-undecodable): {exc}')
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(prefix, f'the finding-evidence records file is not valid JSON '
                      f'(finding-evidence-records-not-json): {exc}')
    if not isinstance(parsed, list):
        _fail(prefix, 'the finding-evidence records file is not a JSON array '
                      '(finding-evidence-records-not-list); one object per finding is required')
    if not parsed:
        _fail(prefix, 'the finding-evidence records file is an empty array '
                      '(finding-evidence-records-empty); a batched call records at least one '
                      'finding')
    records = []
    seen = set()
    for idx, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            _fail(prefix, f'finding-evidence record {idx} is not a JSON object '
                          f'(finding-evidence-record-not-object)')
        fid = item.get('finding_id')
        # bool is an int subclass — reject it explicitly so a JSON `true` is not read as id 1.
        if not isinstance(fid, int) or isinstance(fid, bool) or fid < 0:
            _fail(prefix, f'finding-evidence record {idx} has a missing or non-negative-int '
                          f'finding_id (finding-evidence-record-finding-id): {fid!r}')
        if fid in seen:
            _fail(prefix, f'finding-evidence record {idx} repeats finding_id {fid} '
                          f'(finding-evidence-records-duplicate-id); one record per finding id')
        seen.add(fid)
        rec = {'finding_id': fid}
        for field in ('locator', 'command', 'observed', 'baseline_revision',
                      'baseline_identity'):
            val = item.get(field)
            if val is not None and not isinstance(val, str):
                _fail(prefix, f'finding-evidence record {idx} field {field} is not a string '
                              f'(finding-evidence-record-field-type): {val!r}')
            rec[field] = val
        records.append(rec)
    return records


def cmd_record_finding_evidence(args):
    """Record one finding's reproducible evidence on the dedicated per-finding channel.

    Deliberately NOT `record-adjudication --ledger-file`: that transport carries a
    one-line summary and refuses newlines and `<field>=` tokens by contract, so multi-line
    observed output cannot ride on it. This channel is keyed by `<round>:<finding-id>`, caps
    each field, and stores the text VERBATIM as data — the print boundary, not a refusal, is
    where record-splitting bytes are neutralized. Instruction-shaped text is never
    neutralized and never needs to be: it is stored and printed as data, never executed.
    """
    prefix = 'record-finding-evidence'
    doc = _load_for_mutation(prefix, args.slug, args.nonce)
    # getattr, not attribute access: a hand-built caller namespace need not carry every parser
    # field, exactly as _emit_next_call reads its namespace fields (issue #795).
    if getattr(args, 'finding_evidence_records_file', None) is not None:
        # issue #1803: the batched form records a whole round's evidence from one file; the
        # per-finding flags are mutually exclusive with it, so a mixed call is a caller slip.
        conflicting = [name for name, present in (
            ('--finding-id', args.finding_id is not None),
            ('--locator', args.locator is not None),
            ('--command', args.command is not None),
            ('--baseline-revision', args.baseline_revision is not None),
            ('--baseline-identity', args.baseline_identity is not None),
            ('--observed-stdin', args.observed_stdin)) if present]
        if conflicting:
            _fail(prefix, f'--finding-evidence-records-file batches a whole round and takes '
                          f'none of the per-finding flags, but {",".join(conflicting)} '
                          f'{"was" if len(conflicting) == 1 else "were"} also passed '
                          f'(finding-evidence-records-mixed-form)')
        records = _ingest_finding_evidence_records(args.finding_evidence_records_file)
        lines = []
        for rec in records:
            supplied = (('locator', rec['locator']), ('command', rec['command']),
                        ('observed', rec['observed']),
                        ('baseline_revision', rec['baseline_revision']),
                        ('baseline_identity', rec['baseline_identity']))
            key, completeness, missing = _record_one_finding_evidence(
                doc, args.round, rec['finding_id'], supplied, prefix)
            lines.append(f'finding={key} completeness={completeness} '
                         f'missing={",".join(missing) if missing else "none"}')
        # Every finding is stored, then the doc is saved once — a conflict in any record
        # raises before the save, so the batch lands atomically or not at all.
        _save_or_fail(prefix, doc, args.slug)
        for line in lines:
            print(line)
        return
    if args.finding_id is None:
        _fail(prefix, 'record-finding-evidence needs --finding-id (one finding) or '
                      '--finding-evidence-records-file (a whole round); neither was passed '
                      '(finding-evidence-missing-finding-selector)')
    observed = None
    if args.observed_stdin:
        # Read from stdin, hoisted into main() above the section (issue #1040), and
        # consumed through the SHARED guard so a mid-read OSError and a closed fd 0 alike
        # name their own cause. Neither may reach the decode below as None: the OSError
        # would surface as a NoneType AttributeError that discards the real errno, and the
        # closed fd 0 did exactly that before this routing. An empty read is a different
        # thing entirely and still reaches the decode (see the note below it).
        raw = _stdin_bytes_or_fail(args, prefix, 'the observed output')
        # An empty read is NOT refused: issue #704 requires evidence that is absent or
        # incomplete to be RECORDED `incomplete` (never verified), which is what
        # `evidence_completeness` does with an empty `observed`. Refusing would record no
        # evidence at all and lose the finding's locator and command with it.
        try:
            observed = raw.decode('utf-8')
        except UnicodeDecodeError:
            _fail(prefix, 'evidence-undecodable: the observed output is not valid UTF-8')
    supplied = (('locator', args.locator), ('command', args.command),
                ('observed', observed), ('baseline_revision', args.baseline_revision),
                ('baseline_identity', args.baseline_identity))
    key, completeness, missing = _record_one_finding_evidence(
        doc, args.round, args.finding_id, supplied, prefix)
    _save_or_fail(prefix, doc, args.slug)
    print(f'finding={key} completeness={completeness} '
          f'missing={",".join(missing) if missing else "none"}')


def cmd_query_finding_evidence(args):
    """Read back per-finding evidence under the channel's own bounded encoding.

    Every stored field is JSON-encoded before printing, so an embedded newline in auditor
    text renders as escaped bytes on the finding's own line and cannot forge a LINE of this
    surface. That is this channel's answer to the hazard the ledger transport answers by
    refusal.

    The scope of the field half is narrower and stated exactly, because JSON quoting escapes
    newlines and quotes but NOT `=` or spaces. The three DECISION fields — `finding=`,
    `completeness=`, `conflict=` — are unforgeable structurally: each is emitted ahead of
    every auditor-controlled value and drawn from a closed domain (an `<int>:<int>` key, the
    two `evidence_completeness` literals, and keys of that same domain). The trailing
    `_EVIDENCE_FIELDS` values are QUOTED rather than delimited, so auditor text may contain a
    `<field>=`-shaped word INSIDE its quotes: read this line by its JSON quoting, never by
    splitting on whitespace and taking the first `<field>=` hit. The decision-fields-first
    ordering is load-bearing, not cosmetic — a field appended after the evidence values would
    end it — and is pinned by the `#704-25` row.
    """
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        print('evidence=none reason=foreign-nonce')
        return
    if state is None:
        print('evidence=none reason=state-unestablished')
        return
    store = state.get('finding_evidence') or {}
    want = str(args.round)
    round_scoped = {k: v for k, v in store.items() if k.split(':', 1)[0] == want}
    # Computed over the WHOLE round before any narrowing: a conflict is a relation between two
    # findings, so deriving it from a single-finding subset would report `conflict=none` by
    # construction — and that is the exact signal the proportionate-adjudication policy reads
    # to license a cheap replay.
    conflicts = evidence_conflicts(round_scoped)
    scoped = round_scoped if args.finding_id is None else {
        k: v for k, v in round_scoped.items() if k.split(':', 1)[1] == str(args.finding_id)}
    if not scoped:
        print('evidence=none')
        return
    for key in sorted(scoped, key=lambda k: int(k.split(':', 1)[1])):
        e = scoped[key]
        others = [k.split(':', 1)[1] for k in conflicts.get(key) or []]
        fields = ' '.join(f'{f}={json.dumps(e.get(f, ""))}' for f in _EVIDENCE_FIELDS)
        print(f'finding={key} completeness={e.get("completeness", "incomplete")} '
              f'conflict={",".join(others) if others else "none"} {fields}')


def cmd_query_adjudication_records(args):
    """Read back a round's advisory/invalid per-finding records (issue #743).

    A query-class command: exit 0 once arguments parse. One decided line per record, every
    auditor-controlled field JSON-encoded so an embedded newline in the auditor-verbatim block
    renders as escaped bytes and cannot forge a LINE of this surface (the finding-evidence
    print-boundary discipline this channel shares). The DECISION fields lead and are
    structurally unforgeable — `record_class`, `round`, `id`, `impact_class`, `impact_bearing`,
    `evidence_state` are each emitted ahead of every auditor-controlled value and drawn from a
    closed domain; the trailing QUOTED fields carry auditor text, and `summary` trails last,
    matching the query-findings line discipline. Read this line by its JSON quoting, never by
    splitting on whitespace and taking the first `<field>=` hit.
    """
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        print('records=none reason=foreign-nonce')
        return
    if state is None:
        print('records=none reason=state-unestablished')
        return
    rnd = _find_round(state, args.round)
    if rnd is None:
        print('records=none reason=no-such-round')
        return
    classes = (_ADJUDICATION_RECORD_CLASSES if args.record_class is None
               else (args.record_class,))
    lines = []
    for cls in classes:
        for entry in rnd.get(f'{cls}_records') or []:
            bearing = ('yes' if entry.get('impact_class') in _IMPACT_BEARING_CLASSES
                       else 'no')
            evstate = 'recorded' if (entry.get('evidence') or '').strip() else 'absent'
            lines.append(
                f'record_class={cls} round={args.round} id={entry["id"]} '
                f'impact_class={entry.get("impact_class")} impact_bearing={bearing} '
                f'evidence_state={evstate} '
                f'auditor_block={json.dumps(entry.get("auditor_block", ""))} '
                f'evidence={json.dumps(entry.get("evidence", ""))} '
                f'rationale={json.dumps(entry.get("rationale", ""))} '
                f'summary={json.dumps(entry.get("summary", ""))}')
    if not lines:
        print('records=none')
        return
    for line in lines:
        print(line)


def cmd_query_calibration(args):
    """Read the run's calibration backing, render state, and trigger (issue #743).

    `calibration_backing=<token> adjudication_render=<token> calibration_trigger=<yes|no>
    unevidenced=<ids|none> reason=<token>` — the orchestrator reads these to decide the
    never-blocking disclosure offer, exactly as it reads query-coverage for the coverage offer.
    A query-class command: exit 0 once arguments parse.
    """
    state = _query_state(args.slug)
    print(_calibration_line(state, args.nonce))


# The boundary components, in emission order, each paired with the producer that answers
# it. ONE ordering, not a constant and a separate local tuple that must agree.
_BOUNDARY_PRODUCERS = (
    ('triggers', lambda s, n: _triggers_line(s, n)),
    ('convergence', lambda s, n: _convergence_line(s, n)),
    ('coverage', lambda s, n: _coverage_backing_line(s, n)),
    ('calibration', lambda s, n: _calibration_line(s, n)),
    ('offer', lambda s, n: _offer_line(s, n)),  # issue #548: the audit-round withhold
)
_BOUNDARY_COMPONENTS = tuple(name for name, _ in _BOUNDARY_PRODUCERS)


def cmd_query_boundary(args):
    """The Step 3.6 → Step 4 boundary decision, in ONE read (issue #795).

    Carries the DECIDED FIRST LINE of the trigger, convergence, coverage, calibration, and
    offer answers — each byte-identical to the first line its individual query prints, one per
    line, in `_BOUNDARY_COMPONENTS` order. It composes those lines from the same hoisted
    producers the individual queries call, so the two can never drift.

    The individual queries survive and answer exactly as before; this is an additional
    read, never a replacement. It carries NO per-dimension coverage rows (see
    `_coverage_backing_line`), so the procedure keeps calling `query-coverage` where the
    rows are needed.

    PER-COMPONENT STATUS: when one component cannot be established, it is NAMED with its
    reason on a `component=<name> reason=<token>` line and no short answer is returned that
    a caller would read as complete — the other three still answer, because one malformed
    sub-derivation must not blind the boundary read to the components that are fine.
    """
    state = _query_state(args.slug)
    out = []
    for name, produce in _BOUNDARY_PRODUCERS:
        try:
            out.append(produce(state, args.nonce))
        except Exception as exc:
            # A DELIBERATELY broad catch, narrowly scoped to ONE producer call. The
            # producers read a document a human can hand-corrupt, and their failure modes
            # are open-ended (a missing key, a wrong-typed field, a value that will not
            # format). Narrowing the type here would let an unanticipated shape escape as a
            # traceback and break the query class's exit-0 contract — the opposite of
            # failing closed. Nothing is swallowed: the component is named on its own
            # `component=` line with the exception's own type as the reason token.
            # In POSITION, not appended after the answers: a failing component that moved
            # to the end would break the docstring's own "one per line, in
            # `_BOUNDARY_COMPONENTS` order" promise and make a positional read wrong.
            # The stdout token stays free of the exception TEXT (untrusted document
            # content must never reach the parsed surface), but the cause is not dropped:
            # its siblings (`_query_state`, `cmd_query_arm`) both keep the diagnosis on
            # stderr, and a bare `detail=KeyError` names no key, field, or round.
            sys.stderr.write(
                f'issue-audit-state.py query-boundary: component {name!r} could not be '
                f'established — {type(exc).__name__}: {exc}\n')
            out.append(f'component={name} reason=unestablished '
                       f'detail={type(exc).__name__}')
    for line in out:
        print(line)


def _calibration_line(state, nonce):
    """The `query-calibration` decided line (issue #795 hoist; see `_triggers_line`)."""
    if state is not None and state['nonce'] != nonce:
        return ('calibration_backing=unestablished adjudication_render=none '
                'calibration_trigger=no unevidenced=none reason=foreign-nonce')
    cal = evaluate_calibration(state)
    trig = 'yes' if evaluate_calibration_trigger(state, cal) else 'no'
    ids = ','.join(str(i) for i in cal['unevidenced']) if cal['unevidenced'] else 'none'
    return (f'calibration_backing={cal["backing"]} adjudication_render={cal["render"]} '
            f'calibration_trigger={trig} unevidenced={ids} '
            f'reason={cal.get("reason") or "none"}')


def _nonneg_int(text):
    """argparse type: a non-negative integer.

    The evidence key is `<round>:<finding-id>` and the read boundary requires `[0-9]+:[0-9]+`,
    so a negative value would persist a document that fails to load on every later subcommand
    — a run-wide lockout from one mistyped flag, in a component whose contract is that it
    never blocks issue creation. Constrain it at the boundary instead.
    """
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f'must be a non-negative integer, got {text!r}')
    return value


def cmd_emit_body(args):
    """Gated body emitter. Non-zero + EMPTY stdout when eligibility does not ground it."""
    try:
        doc = load_state(args.slug)
        _check_nonce(doc, args.nonce)
    except StateError as exc:
        _fail('emit-body', str(exc))
    # issue #562: resolve the draft file from the recorded binding when one exists — the
    # bound root is the single source of truth for which file is canonical, so a compacted
    # context that hands a drifted --draft-file cannot redirect the emit. Fall back to the
    # caller-supplied --draft-file only on an unbound run (an embed/inline epoch that never
    # bound a canonical file).
    source = _bound_draft_file(doc, args.slug) or args.draft_file
    try:
        raw = Path(source).read_bytes()
        digest = hash_bytes(raw)
    except (OSError, _DigestError) as exc:
        _fail('emit-body', f'could not hash the draft file: {exc}')
    elig = evaluate_eligibility(doc, 'approve', digest)
    if elig['answer'] != 'eligible':
        # issue #611: name the recovery at this refusal too. This is the costliest
        # point to rediscover it by trial — the creation epoch is already recorded —
        # so the remedy is emitted BEFORE _fail, which does not return. The helper
        # self-guards on the reason, so this call is unconditional.
        _emit_stale_override_remedy('emit-body', elig, doc, digest)
        _emit_unaudited_revision_remedy('emit-body', elig)
        _fail('emit-body', 'refusing to emit an unaudited body: eligibility answered '
                           f'not-eligible ({elig["reason"]})')
    body = split_body(raw)
    if not body:
        # Emitting an empty body on exit 0 would be indistinguishable from a successful
        # emit; an eligible draft with an empty body below its title must fail loudly
        # (the refusal signature: non-zero with EMPTY stdout) instead of stalling the
        # posting recipe undiagnosably.
        _fail('emit-body', 'the audited draft has an empty body below its title')
    sys.stdout.buffer.write(body)


def cmd_query_arm(args):
    hash_ok = True
    try:
        hash_file(args.draft_file)
    except _DigestError as exc:
        # Same breadcrumb discipline as the sibling queries: the CAUSE (missing file,
        # permission, git absent) must never be silently collapsed onto the
        # digest-unrecorded marker.
        print(f'query: could not hash draft file {args.draft_file}: {exc}',
              file=sys.stderr)
        hash_ok = False
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        # Every sibling query fails closed on a foreign nonce; this one must too, rather
        # than answering a routing decision for a run it does not belong to.
        print('arm=embed marker=digest-unrecorded reason=foreign-nonce')
        return
    # A prior within-round DRAFT-UNREADABLE is a fact the tool RECORDED at record-return
    # (`unreadable_retry_used` on the open round) — so read it rather than trusting the
    # caller to hand back something already written down. The reported flag is still OR'd
    # in so a caller that knows better than unestablished state is not overridden, but the
    # recorded fact alone is sufficient: this is what makes "decides from recorded facts"
    # true of the retry input rather than a claim the caller has to honor.
    prior_unreadable = bool(args.prior_unreadable)
    if state is not None and state['rounds']:
        last = state['rounds'][-1]
        if last.get('outcome') is None and last.get('unreadable_retry_used'):
            prior_unreadable = True
    arm, marker = route_arm(args.write_landed == 'yes', hash_ok, prior_unreadable)
    # issue #793 — the kind travels alongside the arm, because `--kind` is now REQUIRED on
    # `record-dispatch` and this is the command whose `next_call=` renders that invocation.
    # Deriving it here rather than leaving it bare is what keeps the rendered suggestion
    # runnable: a required flag the renderer omits is exactly the forgotten-flag failure
    # the #795 answer-line contract exists to prevent. An unestablished state answers
    # `None`, and `_render_operand` then renders the flag bare in `needs=` — the honest
    # shape, never a guessed kind.
    kind = None
    if state is not None:
        kind = select_round_kind(state, args.draft_file)['kind']
    print(f'arm={arm} marker={marker or "none"}')
    return _next_call_ctx(arm=arm, marker=marker, kind=kind)


def cmd_query_next_action(args):
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        print('action=round-closed-no-verdict reason=foreign-nonce')
        return
    # issue #795: `--round` is state-defaulted here. An ambiguity fails closed IN THIS
    # SUBCOMMAND'S OWN CLASS: a query still exits 0 and prints a DECIDED answer carrying a
    # `reason=` token, exactly as `cmd_query_arm` already answers `reason=foreign-nonce`.
    # A non-zero query exit after parsing would break "queries always exit 0 once their
    # arguments parse" and, since the fallback partition covers only non-zero MUTATION
    # exits, would present as that fallback's "no contract output" class — degrading a
    # whole run to one bounded in-chat round over a forgotten flag on a read.
    args.round, _amb = _resolve_named_round(state, args.round)
    if _amb is not None:
        print(f'action=round-closed-no-verdict reason={_amb}')
        return _next_call_ctx(action=None, ambiguity=_amb)
    action = next_action(state, args.round)
    print(f'action={action}')
    return _next_call_ctx(action=action)


def cmd_query_triggers(args):
    state = _query_state(args.slug)
    print(_triggers_line(state, args.nonce))


def cmd_query_offer(args):
    state = _query_state(args.slug)
    print(_offer_line(state, args.nonce))


def _offer_line(state, nonce):
    """The `query-offer` decided line (issue #548).

    Reports whether the Step 4 3a audit-round offer is withheld because the last completed
    discovery REVISE round's unresolved must-revise findings are unrevised (or their count
    is unestablished). `query-boundary` composes this exact line so 3a reads the withhold in
    the boundary read it already does. `reason` names why: `unresolved-revise-pending` for
    held-but-unrevised findings, `unestablished` on an unestablished count (unknown is not
    zero), `none` when the offer is not withheld, `foreign-nonce` for a foreign caller,
    `state-unestablished` when the run state could not be read at all — every non-`none`
    arm reports `offer_withheld=yes`, failing closed like the sibling boundary producers so
    an unreadable or foreign state is never misread as an open offer.
    """
    if state is None:
        return 'offer_withheld=yes reason=state-unestablished'
    if state['nonce'] != nonce:
        return 'offer_withheld=yes reason=foreign-nonce'
    reason = _offer_withhold_reason(state)
    if reason is not None:
        return f'offer_withheld=yes reason={reason}'
    return 'offer_withheld=no reason=none'


def _triggers_line(state, nonce):
    """The `query-triggers` decided line (issue #795 hoist).

    Hoisted so `query-boundary` composes this exact line rather than re-deriving it — the
    one-producer discipline the summary fields already follow. `cmd_query_triggers` prints
    it unchanged, so its stdout is byte-identical to before the hoist.
    """
    if state is not None and state['nonce'] != nonce:
        # Fail closed like the sibling queries, but NAME the cause: the state file is
        # valid, the caller is foreign — 'state-unestablished' would misattribute. The
        # coverage field stays present (not-hold) so the line shape is identical on every
        # arm and the orchestrator's hand-parse never sees a field appear/disappear.
        return ('t1=not-hold t2=hold coverage=not-hold calibration=not-hold '
                'reason=foreign-nonce')
    t = evaluate_triggers(state)
    reason = t['reason'] or ''
    # issue #708: the unbacked-coverage offer trigger is a sibling of T1/T2 on the SAME
    # boundary offer, so it is produced by the SAME evaluation rather than a second call
    # concatenated in the printer (the one-producer discipline #603 established for the
    # summary fields). `coverage=` renders BEFORE `reason=` so `reason` stays the trailing
    # field the orchestrator's parse already anchors on.
    # issue #743: the calibration disclosure trigger renders BEFORE `reason=` (which stays
    # the trailing field the orchestrator's parse anchors on), a sibling of `coverage=`.
    return (f't1={"hold" if t["t1"] else "not-hold"} '
            f't2={"hold" if t["t2"] else "not-hold"} '
            f'coverage={"hold" if t["coverage"] else "not-hold"} '
            f'calibration={"hold" if t["calibration"] else "not-hold"} reason={reason}')


def _unledgered_revise(state):
    """Completed rounds adjudicated REVISE that recorded NO ledger, comma-joined or `none`.

    The AC5 residual, made observable (issue #603, PR #612 review iteration 2). Such a
    round's findings never enter the run-wide effective count, and once a later ledgered
    round becomes the latest completed round neither T1 nor T2's `unadjudicated-round` arm
    (which reads only that latest round) can still see it — so the orchestrator has to
    check for it, and could not: no query named it.

    Two rejected approximations, both measured wrong against HEAD before this existed. A
    **gap in the round numbers `query-findings` returns** is blind to the base case, where
    the unledgered round is the FIRST one and its absence leaves no gap to see. Comparing
    the ledgered rounds against `rounds_run=` is worse in the other direction: that field
    is `len(state['rounds'])` — every RECORDED round, since `record-dispatch` adds one
    before any outcome exists — and it counts the two shapes that legitimately record no
    ledger (a FILE round, which records none precisely because it is clean, and a
    no-verdict round), so it fires on runs with no unestablished round at all and sends
    the orchestrator to name a round that does not exist.

    This predicate is exactly the residual: adjudicated REVISE, completed, no ledger.
    """
    out = [str(r.get('round')) for r in completed_rounds(state or {'rounds': []})
           if r.get('adjudicated_verdict') == 'REVISE' and _ledger(r) is None]
    return ','.join(out) if out else 'none'


def cmd_query_convergence(args):
    state = _query_state(args.slug)
    print(_convergence_line(state, args.nonce))


def _convergence_line(state, nonce):
    """The `query-convergence` decided line (issue #795 hoist; see `_triggers_line`)."""
    if state is not None and state['nonce'] != nonce:
        # Fail closed like the sibling queries, naming the cause: a foreign caller cannot
        # read a converged verdict off another run's state. The field set must stay
        # IDENTICAL to the answering arm's — a fail-closed answer that drops a field is a
        # different shape for a parser to handle, and `unledgered_revise=none` here means
        # "no rounds are named", which is exactly right when nothing was read.
        return 'converged=no reason=foreign-nonce basis=none unledgered_revise=none'
    c = evaluate_convergence(state)
    reason = c['reason'] or ''
    return (f'converged={"yes" if c["converged"] else "no"} reason={reason} '
            f'basis={c["basis"]} unledgered_revise={_unledgered_revise(state)}')


def _findings_line(rnd, entry):
    """One `query-findings` ledger line.

    Hoisted out of `cmd_query_findings` so the AC1 protocol-token coverage audit can see
    it. That audit resolves emission shapes structurally, and a list-comprehension literal
    printed through an `IfExp` was a shape it could not reach — so `id=`, `status=` and
    `summary=`, the very line the vocabulary refusal exists to protect, were in
    `_PROTOCOL_TOKENS` by hand alone with nothing proving it (PR #612 review iteration 2).
    A `return`ed literal in a named helper is a shape the audit already covers.
    """
    return (f'round={rnd["round"]} id={entry["id"]} '
            f'status={entry["status"]} summary={entry["summary"]}')


def cmd_query_findings(args):
    """One line per ledger entry across all rounds (issue #603 AC8).

    The orchestrator's reconciliation input: a DURABLE read-back of prior rounds'
    findings, never context recall, so the classification of a new finding against the
    prior ledgers survives a compaction. Read-only and exit-0 like its sibling queries,
    with the same inline fail-closed foreign-nonce answer (never the mutations'
    exception path, which would break the two-class contract).

    `summary=` is the FINAL field on every line because it is the one field whose value
    may contain spaces; the AC1 vocabulary refusal is what keeps that unambiguous, since
    no summary can carry a `<field>=` word of the tool's own printed surface. This is one of
    the tool's multi-line read-back queries, alongside the issue-#704
    `query-finding-evidence`.

    INVARIANT for any future field: `summary=` must REMAIN trailing. A field appended
    after it would end the unambiguous split — the reader could no longer tell a space
    inside the summary from the delimiter before the next field — and the vocabulary
    refusal does not rescue that, since it bars a summary from forging a field NAME, not
    from containing spaces. Pinned by the `#603-17/AC8` suite row.
    """
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        print('findings=none reason=foreign-nonce')
        return
    if state is None:
        print('findings=none reason=state-unestablished')
        return
    lines = [_findings_line(rnd, entry) for rnd, entry in _all_entries(state)]
    print('\n'.join(lines) if lines else 'findings=none')


def cmd_query_eligibility(args):
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        print('eligible=no reason=foreign-nonce')
        return
    # issue #562 precedence + the digest-failure breadcrumb, owned by the shared resolver.
    digest, digest_failed = resolve_draft_digest('query', state, args)
    r = evaluate_eligibility(state, args.mode, digest, digest_failed=digest_failed)
    if args.mode == 'iterate':
        if r['answer'] == 'iterate-ok':
            print(f'iterate=ok ordinal={r["ordinal"]}')
        else:
            print(f'iterate=no reason={r["reason"]}')
        return
    if r['answer'] == 'eligible':
        print(f'eligible=yes ground={r["ground"]} token={r["token"]} key={r["key"]}')
    else:
        print(f'eligible=no reason={r["reason"]}')
        # issue #611: the stdout token line above is the closed one-token contract and
        # stays byte-identical; the remedy is additive on stderr, matching this tool's
        # existing breadcrumb idiom (the `query: could not hash draft file ...` line).
        # The helper self-guards on the reason, so this call is unconditional.
        _emit_stale_override_remedy('query-eligibility', r, state, digest)
        _emit_unaudited_revision_remedy('query-eligibility', r)


def cmd_query_summary(args):
    state = _query_state(args.slug)
    if state is not None and state['nonce'] != args.nonce:
        # The rendered line stays the fail-closed unestablished shape, but the CAUSE is
        # named on stderr so a transcript reader can tell a foreign nonce from a
        # missing/corrupt record.
        print(f'query: nonce mismatch for slug {args.slug} (the state file is owned by '
              f'another run); answering unestablished', file=sys.stderr)
        state = None
    # Same resolver as query-eligibility, whose derivation this summary shares — so the
    # two can never ground on different files. The failure threads into the eligibility
    # derivation, so the summary can never render a live token the approve gate refuses.
    digest, digest_failed = resolve_draft_digest('query', state, args)
    f = summary_fields(state, digest, digest_failed=digest_failed)
    fc = 'none' if f['findings_count'] is None else str(f['findings_count'])
    token = f['token'] or ('stale-token' if f['stale_token'] else 'none')
    markers = ','.join(f['markers']) if f['markers'] else 'none'
    # The post-adjudication actionability fields render `none` before adjudication and
    # `unestablished` when the count could not be established (unknown is not zero).
    adj_v = f['adjudicated_verdict'] or 'none'
    mr = 'none' if f['must_revise'] is None else str(f['must_revise'])
    adv = 'none' if f['advisory'] is None else str(f['advisory'])
    inv = 'none' if f['invalid'] is None else str(f['invalid'])
    umr = 'none' if f['unresolved_must_revise'] is None else str(f['unresolved_must_revise'])
    # issue #603: `none` when the latest completed round is unadjudicated (or none exists);
    # `unestablished` when it IS adjudicated but the count could not be established (unknown
    # is not zero, exactly as `umr` one line above).
    eff_v = f['effective_unresolved']
    eff = 'none' if eff_v is None and f['adjudicated_verdict'] is None else _render_count(eff_v)
    # issue #562: the tool emits the bound root + the bound-tier TOKEN; the skill derives
    # the human `draft bound to worktree root` marker from `bound_tier=worktree-root`.
    # A space-containing marker value is deliberately NOT emitted here. bound_root itself
    # can contain a space (a real absolute path may — see _is_bound_path), so consumers
    # extract each field by its `key=` anchor, never by a positional whitespace split;
    # bound_tier and attestation stay space-free tokens found that way. These render
    # BEFORE `attestation`: attestation is the contractually-trailing final field (the
    # skill and the #546 suite anchor `attestation=<token>$` to end-of-line), so nothing
    # may follow it.
    print(f'state={f["state"]} findings_count={fc} '
          f'revisions_applied={f["revisions_applied"]} verdict={f["verdict"] or "none"} '
          f'rounds_run={f["rounds_run"]} '
          f'consumer_dimensions_appended={_yn(f["consumer_dimensions_appended"])} '
          f'degraded={_yn(f["degraded"])} user_declined={_yn(f["user_declined"])} '
          f'cap_reached={_yn(f["cap_reached"])} markers={markers} token={token} '
          f'reinit_forced={_yn(f["reinit_forced"])} '
          # Post-adjudication actionability fields (#548) and the bound-root fields (#562)
          # both precede `attestation` so that field stays the trailing token the #546 CLI
          # pins anchor on (`attestation=…$`).
          f'adjudicated_verdict={adj_v} must_revise={mr} advisory={adv} invalid={inv} '
          f'unresolved_must_revise={umr} '
          # issue #73: the round the class-count fields above are read from — a
          # space-free token before `attestation`, rendered next to `scoped_round` (the
          # round they skip). `none` until a whole-draft round completes.
          f'counts_round={f["counts_round"] if f["counts_round"] is not None else "none"} '
          # issue #793: the scoped round the five fields above deliberately skip. A
          # space-free token before `attestation`, which stays the trailing anchored
          # field. `none` when no targeted round completed — the common case.
          f'scoped_round={f["scoped_round"] if f["scoped_round"] is not None else "none"} '
          f'effective_unresolved={eff} '
          f'convergence_basis={f["convergence_basis"]} '
          # issue #708: the coverage-backing and render tokens — space-free, before
          # bound_root, so attestation stays the trailing anchored field.
          f'coverage_backing={f["coverage_backing"]} '
          f'coverage_render={f["coverage_render"]} '
          f'coverage_reason={f["coverage_reason"]} '
          # issue #743: the calibration axis — space-free tokens before bound_root, so
          # attestation stays the trailing anchored field.
          f'calibration_backing={f["calibration_backing"]} '
          f'adjudication_render={f["adjudication_render"]} '
          f'calibration_trigger={_yn(f["calibration_trigger"])} '
          # issue #792: the final-byte axis — space-free tokens, with
          # `final_byte_coverage` immediately before `bound_root` so `attestation` stays
          # the trailing anchored field. The two slot tokens precede it so a run at the
          # pass cap discloses its exhaustion here rather than filing silently.
          f'final_byte_passes={f["final_byte_passes"]} '
          f'final_byte_exhausted={_yn(f["final_byte_exhausted"])} '
          f'final_byte_coverage={f["final_byte_coverage"]} '
          f'bound_root={f["bound_root"] or "none"} bound_tier={f["bound_tier"] or "none"} '
          # issue #709: both steering tokens render HERE, before `attestation` — that
          # field is the contractually-trailing one (`attestation=…$`), so nothing may
          # follow it.
          f'steering={f["steering"]} '
          f'steering_reason={f["steering_reason"] or "none"} '
          f'attestation={f["attestation"] or "none"}')


def cmd_query_nonce(args):
    """Re-read the nonce from state — the compaction-recovery path.

    Recovery restores single-run continuity; it cannot discriminate a foreign
    same-slug run in the same cwd (the disclosed limitation).
    """
    state = _query_state(args.slug)
    print(f'nonce={state["nonce"] if state else "unknown"}')


__all__ = [
    "_BOUNDARY_COMPONENTS",
    "_BOUNDARY_PRODUCERS",
    "_binding_line",
    "_calibration_line",
    "_convergence_line",
    "_current_zero_round_decline",
    "_draft_body_digest",
    "_findings_line",
    "_ingest_finding_evidence_records",
    "_nonneg_int",
    "_offer_line",
    "_record_decline_bound_epoch",
    "_record_one_finding_evidence",
    "_triggers_line",
    "_unledgered_revise",
    "cmd_emit_body",
    "cmd_query_adjudication_records",
    "cmd_query_arm",
    "cmd_query_boundary",
    "cmd_query_calibration",
    "cmd_query_convergence",
    "cmd_query_draft_binding",
    "cmd_query_eligibility",
    "cmd_query_final_byte",
    "cmd_query_finding_evidence",
    "cmd_query_findings",
    "cmd_query_next_action",
    "cmd_query_nonce",
    "cmd_query_offer",
    "cmd_query_round_kind",
    "cmd_query_staged_write",
    "cmd_query_summary",
    "cmd_query_triggers",
    "cmd_record_creation_attestation",
    "cmd_record_creation_epoch",
    "cmd_record_degraded",
    "cmd_record_draft_binding",
    "cmd_record_final_byte_offer",
    "cmd_record_finding_evidence",
    "cmd_record_offer",
    "cmd_record_override",
    "cmd_record_revision",
    "cmd_record_staged_write",
    "cmd_record_write_failure",
    "cmd_write_dispatch_scope",
    "resolve_draft_digest",
]

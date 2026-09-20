# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Closed vocabularies, the transition table, process plumbing,
write serialization, digests and per-finding evidence.

Part 1 of the `/prflow:spec` audit-lifecycle state owner. The CLI entry and
the two-class contract live in `scripts/issue-audit-state.py`, which imports this module
and re-exports every name in `__all__`; issue #567 split the bodies out so each source
file loads in one whole-file Read. This module adds no behavior of its own.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.version_info < (3, 11):
    sys.stderr.write(
        'issue-audit-state.py: python3 >= 3.11 required (found '
        f'{sys.version_info.major}.{sys.version_info.minor})\n'
    )
    raise SystemExit(1)

# Bumped 1 → 2 for issue #562: the additive `draft_binding` / `write_failures` /
# revision-`stdin_digest` fields. The bump is deliberate even though those fields are
# additive-optional — a pre-change v1 state file answers through the existing
# schema-version-mismatch fail-closed matrix row (#546's matrix; no new versioning
# discipline is invented), forcing a re-init of any in-flight v1 run. Blast radius is
# small: these state files are ephemeral per-run scratch under .prflow/tmp/.
#
# Bumped 2 → 3 for issue #709: the additive per-attempt `instructions` record (the
# canonical dispatch-instruction digest plus the round's CLOSED regeneration inputs)
# and the per-round `steering` establishment result. Same reasoning as the 1 → 2 bump:
# additive-optional fields still get the bump so an in-flight v2 run re-inits through
# the existing schema-mismatch fail-closed matrix row rather than being read by code
# that would treat its absent steering record as an established one.
SCHEMA_VERSION = 3

# ── Canonical token sets ────────────────────────────────────────────────────────
# The transition table below may reference no token outside these sets; the
# import-time assert enforces that. Adding a lifecycle token means adding it here,
# which is what keeps the table and the vocabulary from drifting apart silently.

_EVENTS = (
    'init', 'dispatch', 'return', 'revision', 'override', 'degraded',
    'creation-epoch', 'creation-attestation', 'draft-binding', 'write-failure',
    # issue #792: the final-byte exact-byte safety pass. Its own event, deliberately NOT
    # an override kind — the read-side override-validity gate ignores the surface token
    # and grounds eligibility on any current digest-matching override, so routing a
    # "skip the optional safety pass" decline through `_OVERRIDE_KINDS` would make it
    # byte-indistinguishable from the narrow election to file bytes the audit never
    # cleared.
    'final-byte',
)
# These are bare-string tuples, not Enums — a deliberate, recorded trade-off (raised on
# PR #552 and deferred). The cost is real but narrow: because arms and verdicts are both
# plain `str`, a TRANSPOSED `classify_return(arm, verdict)` is not a type error. It does not
# fail open, though — a transposed call takes the verdict-not-in-_VERDICTS path and answers
# `no-parseable-verdict`, the same fail-CLOSED retry token an unreadable return earns, and
# every live caller passes these positionally from _validate'd state that already proved each
# field is in its canonical set. The benefit kept: these tuples ARE the vocabulary the
# import-time transition-table assert checks every row against, and membership tests
# (`x not in _ARMS`) read directly against the JSON state file's bare strings with no
# serialization layer. Revisit if either changes: (a) a caller starts passing an arm/verdict
# that did NOT come through _validate (e.g. a new CLI flag read straight into classify_return),
# or (b) a transposition ever survives to a wrong ANSWER rather than the closed retry token.
_ARMS = ('file', 'embed', 'inline')
# issue #793: the SECOND tool-owned per-round dispatch dimension, beside the arm. A round
# is either a cold whole-draft derivation (`discovery`) or a claim-scoped re-check of what
# a revision was supposed to fix (`targeted`). The set is closed and complete by
# construction: there are exactly two things a round can be for, and `_checked_kind` below
# refuses anything else rather than letting an unknown kind take a permissive path.
#
# The ORCHESTRATOR never chooses the kind. `select_round_kind` derives it from recorded
# facts and `record-dispatch` cross-checks the caller's `--kind` against that derivation,
# the same query-then-obey-then-cross-check shape the arm already uses — because the
# context that would let an orchestrator choose is exactly the anchored context a scoped
# audit exists to remove.
_ROUND_KINDS = ('discovery', 'targeted')
# The closed reason vocabulary `select_round_kind` answers alongside the kind. Every
# `targeted` condition that fails names ITSELF here, so a run that paid for a cold round
# can always say which condition sent it there rather than reporting a bare `discovery`.
_ROUND_KIND_REASONS = (
    # the one selecting reason for `targeted`
    'targeted-eligible',
    # one failing-condition token per `targeted` condition, plus the delta arms and the
    # no-round precondition. Deliberately count-free: a comment stating how many there are
    # rots on the next edit that adds one.
    #
    # issue #1103 — the no-round precondition is TWO materially different facts that shared
    # `no-completed-round` before: `no-round-dispatched` is the genuine cold FIRST round
    # (nothing has been dispatched yet — the legitimate reason a run's first round is a
    # whole-draft one, so `record-dispatch` announces NO fall-off for it), while
    # `no-completed-round` now names only the fall-off case (a round WAS dispatched but
    # never completed, so the next round pays for a cold audit a completed round would have
    # made cheaper). Splitting them is what lets the durable record — and the
    # accepted-discovery breadcrumb — tell a first round apart from a lost one.
    'no-round-dispatched',
    'no-completed-round',
    'no-revision-after-round',
    'not-file-arm',
    'dispatch-bytes-unrecoverable',
    'empty-claim-set',
    'empty-delta',
    'delta-error',
)
# issue #1103 — the ONE discovery reason that is NOT a fall-off: the genuine cold first
# round. `record-dispatch` announces the expensive whole-draft path for every OTHER
# discovery reason (each names a `targeted` precondition that failed) and stays silent for
# this one, so the accepted-`discovery` breadcrumb marks a round that could have been
# cheaper, never a first round that never could.
_DISCOVERY_FIRST_ROUND_REASON = 'no-round-dispatched'
# issue #793: the closed per-claim verdict set a `targeted` round's auditor returns —
# exactly two members, complete by construction. Anything else (a missing claim, an
# off-set value) is recorded `not-addressed`: only a positively-returned `addressed`
# counts, which is what stops an unusable return from reading as a clean sweep.
_CLAIM_VERDICTS = ('addressed', 'not-addressed')
_VERDICTS = ('FILE', 'REVISE', 'DRAFT-UNREADABLE')
_ROUND_OUTCOMES = ('FILE', 'REVISE', 'no-verdict')
# The subset of `_ROUND_OUTCOMES` that carries an auditor verdict about the bytes
# (issue #792). `no-verdict` is a COMPLETED outcome but not a verdict-bearing one — an
# inconclusive round neither establishes nor revokes coverage, and it is exactly why an
# accepted final-byte pass that closes verdict-less refunds its slot rather than
# consuming the run's one safety pass on a round that could not honour the offer.
_VERDICT_BEARING_OUTCOMES = ('FILE', 'REVISE')
# The post-adjudication verdict a completed round may carry (issue #548). Distinct from the
# raw auditor `--verdict` (`_VERDICTS`), which stays recorded as provenance: adjudication is
# the orchestrator's reconciled judgment over the round's findings, and a lifecycle input is
# accepted only when this verdict and the unresolved-must-revise count agree. `DRAFT-UNREADABLE`
# is not an adjudicated verdict — it names an unread draft, which carries no findings.
_ADJUDICATED_VERDICTS = ('FILE', 'REVISE')
# The literal a round records for its unresolved-must-revise count when the count could not be
# established (unknown is not zero — an unestablished count is never collapsed onto 0).
_UNESTABLISHED = 'unestablished'
# The closed set of return classifications. `classify_return` is validated against it, so a
# renamed classification fails loudly instead of routing a live return to a rule that no
# longer matches.
_CLASSIFICATIONS = ('accept-file', 'accept-revise', 'retry-embed', 'no-parseable-verdict')

# Every decided outcome a transition row may name. Declared independently of TRANSITIONS on
# purpose — the import-time assert compares the table against THIS, so it can actually fail.
_RESULTS = _CLASSIFICATIONS + (
    'nonce-minted', 'nonce-echoed', 'reinit-forced', 'illegal-reinit',
    'digest-recorded', 'sentinels-generated', 'illegal-dispatch',
    'illegal-return', 'ordinal-incremented', 'illegal-revision',
    'override-recorded', 'degraded-recorded', 'epoch-recorded', 'illegal-epoch',
    'match', 'mismatch', 'attestation-unavailable', 'illegal-attestation',
    'draft-binding-recorded', 'illegal-draft-binding', 'write-failure-recorded',
    # issue #792 final-byte slot results
    'final-byte-slot-spent', 'final-byte-slot-refunded', 'illegal-final-byte',
)

# The three embed-arm entry markers, preserved verbatim from the prose this module
# replaces. `lib/test/run.sh` pins the rendered text byte-for-byte: the audit summary
# line carries whichever of these the run entered the embed arm under.
# `digest-unrecorded`'s rendered text predates the cutover, while its trigger is now
# "the tool's own hash of the draft file failed" (see route_arm) — the wording is
# kept because marker strings are preserved verbatim by the extraction contract, and
# a failed hash does leave the digest unrecorded, so the text stays literally true.
_EMBED_MARKER_TOKENS = ('write-failed', 'file-unreadable', 'digest-unrecorded')
_EMBED_MARKER_TEXT = {
    'write-failed': 'draft embedded (file write failed)',
    'file-unreadable': 'draft embedded (file unreadable)',
    'digest-unrecorded': 'draft embedded (digest unrecorded)',
}

_ATTESTATIONS = ('match', 'mismatch', 'attestation-unavailable')
_OVERRIDE_KINDS = ('user-decline', 'cap-reached')
_OVERRIDE_SURFACES = (
    't1t2-boundary', 'step4-offer', 'step4-approval-after-exhausted-offer',
)
_DEGRADED_REASONS = ('no-subagent-tool', 'dispatch-error', 'no-parseable-verdict-exhausted',
                     # issue #709: the canonical dispatch-instruction generator could not
                     # be invoked or produced no usable output, so the round ran without a
                     # hashable instruction file.
                     'instructions-generation-failed')

# What the DISPATCH-time regeneration observed about the written instruction file
# (issue #718). `verified` — regenerated and matched. `diverged` — regenerated and did
# NOT match; the cause (a mangled write, a differently-spelled recorded input, or a
# post-generation edit) is NOT established by the tool, which is exactly why this is a
# recorded observation rather than a refusal. `unverified` — the regeneration could not
# run here at all. Absent means the round predates the field.
_DISPATCH_REGENERATION = ('verified', 'diverged', 'unverified')

# ── Steering-absence establishment (issue #709) ────────────────────────────────
# What the auditor was TOLD, recorded beside the existing carriage evidence for what
# the auditor READ. `established` means the auditor's quoted `git hash-object` ID for
# the canonical dispatch-instruction file equalled the digest of the FRESHLY-REGENERATED
# canonical instructions AND the auditor reported no extra dispatch content. Everything
# else is `not-established` — there is deliberately no third "unknown" state at the ROUND
# level, because absent evidence is treated exactly like mismatched evidence here for the
# same fail-closed reason `_carriage_ok` gives. (The SUMMARY surface does carry a third
# `unestablished` token, for the distinct case of no completed round to report on at all.)
_STEERING_STATES = ('established', 'not-established')
# Why, in refusal precedence order, mapped to the ONE state each reason may carry.
# A mapping rather than a flat tuple because `_validate` must reject a forged PAIR:
# checking state and reason membership independently would accept
# `{'state': 'established', 'reason': 'no-instructions-file'}` — precisely the
# hand-corrupted record the validator exists to stop from walking the run past the
# gate. `canonical-match` is the one establishing reason.
_STEERING_REASON_STATE = {
    # The arm never had a hashable instruction file — the embed and inline arms are
    # entered BECAUSE the canonical draft-file write already failed, so steering-absence
    # is unestablished BY CONSTRUCTION there. A designed consequence, not a gap.
    'no-instructions-file': 'not-established',
    # File arm, but the dispatch recorded no instruction digest / closed inputs, so the
    # tool cannot regenerate the comparand at all.
    'inputs-unrecorded': 'not-established',
    # The regeneration itself failed (generator unimportable, draft unreadable, template
    # unreadable, hashing failed). Unknown is not zero.
    'regeneration-failed': 'not-established',
    'instructions-object-id-absent': 'not-established',
    'instructions-object-id-mismatch': 'not-established',
    # The instruction file already failed its DISPATCH-time regeneration, so the
    # divergence predates the auditor entirely. Same fail-closed state, but a reason that
    # points at the write or the recorded inputs rather than at the auditor's reading —
    # and, unlike a stderr breadcrumb, it survives into `query-summary` and the Step 4
    # audit-summary line, which is the surface the user is actually pointed at.
    'instructions-noncanonical-at-dispatch': 'not-established',
    # issue #793 — the two dispatch-scope-file arms, deliberately DISTINCT from each other
    # and from `regeneration-failed`. A `targeted` round's payload is frozen in a scope
    # file whose digest the dispatch recorded, and the two ways that can go wrong send a
    # reader to opposite remedies:
    #   * the file is ABSENT or UNREADABLE at return time — a cleanup pass, a lost
    #     directory, a permission change. Nothing about the round's content is impeached;
    #     the operand is simply gone. Folding this into `regeneration-failed` would hide
    #     it among generator/template failures and point the reader at the generator.
    #   * the file is PRESENT but its bytes no longer hash to the recorded digest — the
    #     payload was edited after dispatch, which is the tamper this freeze exists to
    #     catch. That one routes through the ordinary `diverged` regeneration path.
    'scope-file-unreadable': 'not-established',
    'scope-file-tampered': 'not-established',
    # The auditor did not report the no-extra-content affirmation at all.
    'extra-dispatch-content-unreported': 'not-established',
    # The auditor reported that its dispatch message carried more than the pointer.
    'extra-dispatch-content': 'not-established',
    'canonical-match': 'established',
}
# The closed answer set for the SUMMARY-line steering token: the two round-level states
# plus `unestablished` for "no completed round, or a completed round that recorded no
# steering result". `summary_fields` asserts its derived token against this set, so the
# constant is load-bearing rather than a name that merely claims a coupling.
_STEERING_SUMMARY = _STEERING_STATES + ('unestablished',)
# ...and the reason's own closed answer set, for the same reason the state has one: a
# consumer parsing `steering_reason=` off the SUMMARY line needs something pinned to
# parse against. `none` is a summary-only member (no round ever RECORDS it) — it is
# what an unestablishable or not-yet-evaluated round renders, exactly as
# `unestablished` is the state's summary-only member.
_STEERING_SUMMARY_REASONS = tuple(_STEERING_REASON_STATE) + ('none',)
_NEXT_ACTIONS = (
    'dispatch-embed-retry', 'dispatch-retry-same-arm', 'dispatch-inline-degraded',
    'proceed', 'revise-and-reaudit', 'revise-then-evaluate-offer', 'round-closed-no-verdict',
    'round-open-awaiting-return',
    # issue #793: a clean `targeted` round is CONFIRMED, never trusted. It is not
    # whole-draft evidence, so it never grounds the clean scan — and the scan cannot simply
    # be taught to skip it, because it breaks on the first `REVISE` and would then refuse
    # rather than fall through. A confirming whole-draft round is scheduled instead, and it
    # needs a token of its own: `proceed` would walk the run to Step 4 on the strength of a
    # scoped round, and reusing `revise-and-reaudit` would make the run record a revision
    # that does not exist.
    'confirm-whole-draft',
)
_ELIGIBILITY_REASONS = (
    'unaudited-revision', 'stale-override', 'no-verdict-round', 'state-unestablished',
    'foreign-nonce', 'no-revision-recorded', 'draft-undigestible',
    'no-digest-supplied',
    # issue #709: draft identity held on the clean round, but steering-absence was not
    # established for it, so the coverage-backed clean ground is withheld.
    'steering-unestablished',
)
_GROUNDS = ('file-identity', 'event-ordering', 'override')

# ---------------------------------------------------------------------------
# issue #795 — round resolution and the `next_call=` answer channel.
# ---------------------------------------------------------------------------

# THE DECIDING RULE for whether `--round` carries a state-resolved default:
#
#   A default is supplied only where `--round` *names* a round the state uniquely
#   determines. Where it *selects* which operation runs, or names a round the caller
#   alone chooses, the flag keeps `required=True`.
#
# `_ROUND_DEFAULTED` is that closed set. Every other `--round` site retains
# `required=True`, in one of three retained groups named beside its own registration:
#   * dispatch-discriminator  — `record-dispatch` (`_find_round` reads it BEFORE any
#     validation and routes between opening a round and retrying an open one, so a
#     resolved number would decide an operation only the caller knows).
#   * caller-selected-round   — `record-creation-epoch` (which audited round creation
#     binds to) and `record-degraded` (whose required-ness is a shipped sentence in
#     `skills/spec/references/step-3-6-audit.md`).
#   * per-round-id-selector   — the cross-round channels whose `--ids` are per-round
#     `1..K`: `record-resolution`, `record-reopen`, `record-invalidate`,
#     `record-finding-evidence`, `query-finding-evidence`, `query-adjudication-records`.
#     A defaulted round there would resolve, reopen, or invalidate a *different,
#     existing, valid* entry with no id-unknown refusal to catch it.
_ROUND_DEFAULTED = (
    'query-next-action', 'record-return', 'record-adjudication',
    'record-adjudication-render', 'record-coverage',
)

# The fixed head placeholder a rendered `next_call=` invocation carries. The module never
# sees the runner-reported portable anchor (`CLAUDE_SKILL_DIR` is substituted at prompt
# time), a bare relative path would break from a subdirectory or a linked worktree, and a
# `sys.argv[0]` path would teach a NON-anchored invocation — the form this repo's anchor
# pins bar, and which those pins cannot see because tool stdout is not scanned. So the
# renderer emits the subcommand and operands only, behind this placeholder, and the
# procedure states that the caller substitutes its own anchored head.
_STATE_OWNER_PLACEHOLDER = '<state-owner>'

# The closed caller-supplied operand classes. A flag here is rendered BARE and named in
# `needs=`; the resolver never fills a value for it. Six classes, complete by construction
# — and the complement is decided rather than residual: an operand in none of them and not
# state-derivable is also rendered bare and named in `needs=` (see `_render_operand`).
_CALLER_SUPPLIED_FLAGS = {
    # 1. A reported observation. `--landed`'s own help states the governing reason:
    #    "the tool cannot observe chat, so this is a reported observation."
    '--landed', '--write-landed',
    # 2. An adjudication verdict or count.
    '--verdict', '--must-revise', '--advisory', '--invalid', '--unresolved-must-revise',
    # 3. An auditor-supplied identifier.
    '--carriage-object-id', '--carriage-sentinel-open', '--carriage-sentinel-close',
    '--instructions-object-id', '--extra-dispatch-content',
    # 4. A free-text reason or id list.
    '--reason', '--resolved-ids', '--ids',
    # 5. A caller-supplied payload flag (a stdin transport, or --ledger-file's path).
    '--ledger-file', '--coverage-stdin', '--stdin-digest',
    # 6. A caller-INTENT operand whose value selects which operation runs. `--round` is
    #    that operand on exactly the two subcommands named in `_ROUND_IS_CALLER_INTENT`;
    #    it is state-derivable elsewhere, so it is keyed by subcommand rather than
    #    listed flat here.
}

# Class 6's subcommand-keyed half (see `_CALLER_SUPPLIED_FLAGS`).
_ROUND_IS_CALLER_INTENT = ('record-dispatch', 'record-creation-epoch')

# The queries whose stdout is MULTI-LINE: each prints one decided line per record (an
# empty store printing a single `<noun>=none` token), or — for `query-coverage` and
# `query-boundary` — a decided first line followed by further lines. This set is the
# machine-consumed contract the module docstring's and the shipped skill's query-class
# enumerations are reconciled against.
_MULTILINE_READBACKS = (
    'query-findings', 'query-finding-evidence',
    'query-coverage', 'query-adjudication-records', 'query-boundary',
)

# THE `next_call=` EXCLUSION PREDICATE, three-armed. A subcommand emits `next_call=` only
# when its stdout is a SINGLE DECIDED LINE *and* the procedure does not consume that
# stdout by command substitution. The arms:
#   * payload stdout        — `emit-body`, whose stdout is the audited body bytes.
#   * multi-line stdout     — `_MULTILINE_READBACKS`.
#   * capture-consumed stdout — no current subcommand occupies this arm, but the
#     `MAIN_ROOT="$(…)"` fence shows it is a real shape a future addition would fall
#     into silently, which is why the predicate rather than this enumeration is what a
#     future emitter is measured against.
# The COMPLEMENT is decided, not residual: a subcommand in none of the three arms emits
# `next_call=`.
_NEXT_CALL_EXCLUDED = frozenset(
    ('emit-body',) + _MULTILINE_READBACKS
)

# The three sanctioned `next_call=` shapes, complete by construction. `_checked_next_call`
# constrains the resolver's return against them the way `_checked_action` constrains
# `next_action` against `_NEXT_ACTIONS`.
_NEXT_CALL_UNESTABLISHED_RE = re.compile(r'\Anext_call=unestablished reason=[a-z0-9-]+\Z')

# Refusal tokens the render boundary can answer with. Every operand taken from recorded
# state is shape-checked before rendering; a failing value yields
# `next_call=unestablished reason=<token>` rather than an emitted string. This is the
# render-boundary counterpart of the ledger channel's existing refusals.
_NEXT_CALL_REFUSALS = (
    'render-path-not-absolute', 'render-value-carries-newline',
    'render-value-carries-shell-metacharacter', 'render-value-not-a-string',
)

# The tiered canonical-draft-root binding (issue #562). A run binds exactly one
# successfully-writable draft root; `tier` names which ladder rung landed. The
# non-bound root is recorded verbatim when a resolver-answered tier-1 main root and a
# divergent tier-2 worktree root both exist, so the divergent-roots out-of-bounds
# enumerations can name the non-bound same-slug draft path. A closed token set —
# record-time validation (`record-draft-binding`) and `_validate` reject any value
# outside it. Unlike the transition-token sets, no import-time assert covers this set:
# it is not a transition-row column, so it is guarded at record time and in `_validate`
# only (the same footing as the embed markers and override kinds).
_DRAFT_TIERS = ('main-root', 'worktree-root')

# ── Per-finding ledger vocabulary (issue #603) ────────────────────────────────────
# A ledger entry's status. Closed set, guarded at record time and in `_validate` (the
# same footing as the embed markers and override kinds). `superseded` is TERMINAL: a
# FILE adjudication sweeps every prior unresolved entry into it, and the three
# post-close mutations refuse to touch it — so an auditor-accepted clean round
# converges the run regardless of earlier bookkeeping.
_LEDGER_STATUSES = ('unresolved', 'resolved', 'invalidated', 'superseded')

# The ingestion provenance stamped on an entry ingested ALREADY resolved (a `resolved: `
# line on the adjudication ledger). That shape is legal because record-adjudication
# accepts an unresolved count BELOW the must-revise total, so such an entry has no
# revision behind it — which is why `_PRE_REVISION` exists as its provenance ordinal.
_LEDGER_INGESTED_RESOLVED = 'resolved-at-adjudication'

# The provenance token standing in for ordinal zero: a post-close status change made
# before any revision was recorded. The staleness comparison counts it as 0.
_PRE_REVISION = 'pre-revision'

# The two statuses a `--ledger-file` line may ingest as. The line prefix IS the status
# followed by ": ", so the prefix is derived rather than stored beside it — one spelling,
# no way for the two halves to disagree.
_LEDGER_PREFIXES = ('unresolved', 'resolved')

# ── Per-dimension coverage vocabulary (issue #708) ─────────────────────────────────
# The closed set of coverage outcomes an auditor records per required audit dimension,
# guarded at record time and re-enforced at the read boundary in `_validate_coverage`.
# Complete by construction:
#   exercised    — the dimension was engaged, backed by a checkable anchor.
#   valid-N/A    — the draft plainly does not touch the dimension (a cheap one-line reason).
#   unestablished— the outcome could not be established (a degraded arm, a floor failure);
#                  unknown is never collapsed onto exercised or onto a clean backing.
#   skipped      — the auditor did not genuinely engage the dimension (the coverage gap).
_COVERAGE_OUTCOMES = ('exercised', 'valid-N/A', 'unestablished', 'skipped')
# The two outcomes that back coverage. A run is coverage-backed only when EVERY required
# dimension resolved to one of these with adjudication-surviving evidence — totality is
# enforced at record time against `--expected-keys`, the orchestrator's authoritative
# enumeration, by synthesizing `unestablished` for every enumerated key with no line.
_COVERAGE_BACKING_OUTCOMES = ('exercised', 'valid-N/A')
# The outcomes that require a non-empty anchor/reason passing the text-only floor. An
# `exercised` outcome whose anchor fails the floor is DOWNGRADED to `unestablished` at
# record time (unknown is not zero), never rejected. The two roles — what BACKS coverage
# and what CARRIES an anchor — are the same set by construction, so the coupling is
# spelled as an alias rather than a second literal that a later edit could silently
# desync (a divergence would be invisible: nothing compares the two).
_COVERAGE_ANCHORED = _COVERAGE_BACKING_OUTCOMES
# One structurally-enforced bound (issue #708): a hard per-anchor character cap over the
# quoted line plus one concern clause, so no single anchor can balloon. The state owner
# READ BOUNDARY rejects an over-cap anchor; at record time an over-cap anchor fails the
# floor and DOWNGRADES to `unestablished` like any other floor failure, never a rejection.
_COVERAGE_ANCHOR_MAX = 600
# The render state a coverage round records. `full` — the auditor rendered every dimension
# on the orchestrator's authoritative enumeration; `degraded` — a render divergence narrowed
# the auditor's dimension set (un-rendered dimensions record `unestablished`), which
# discloses but does NOT fire the coverage offer. (`none` is never RECORDED — it is the
# derivation's no-coverage-round token; see `evaluate_coverage`, whose choices this tuple
# does not gate.)
_COVERAGE_RENDERS = ('full', 'degraded')
# The run-level coverage-backing tokens the derivation reports and the summary renders.
_COVERAGE_BACKINGS = ('backed', 'not-backed', 'unestablished')

# ── Advisory/invalid per-finding adjudication records + calibration (issue #743) ─────
# The closed impact-class set every advisory/invalid per-finding record tags itself with.
# The first four are IMPACT-BEARING — an advisory grade on a finding bearing on any of them
# is convergence-safe only with recorded evidence (the Stage-3 calibration layer). The
# fifth, `clearly-optional`, is the recorded complement: a genuinely-optional improvement
# that stays on the existing non-blocking path and adds no user question on a clean run.
_IMPACT_BEARING_CLASSES = ('implementation-correctness', 'scope', 'safety', 'verifiability')
_IMPACT_OPTIONAL = 'clearly-optional'
_IMPACT_CLASSES = _IMPACT_BEARING_CLASSES + (_IMPACT_OPTIONAL,)
# The per-finding record classes record-adjudication ingests beside the must-revise ledger.
_ADJUDICATION_RECORD_CLASSES = ('advisory', 'invalid')
# The reported-observation states of the Step-4 pre-approval rendering. The tool cannot
# observe chat, so the run REPORTS whether it rendered the records to the user (the
# `--write-landed` reported-observation pattern). `unreported` is the honest default until
# the run reports the rendering; the summary and the calibration trigger surface an
# unreported rendering rather than letting it pass silently.
_ADJUDICATION_RENDER_STATES = ('reported', 'unreported')
# The run-level calibration-backing tokens the derivation reports and the summary renders.
# `clear` — every impact-bearing advisory record carries recorded evidence (or there are no
# impact-bearing advisory records); `under-evidenced` — at least one impact-bearing advisory
# record carries no evidence; `unestablished` — no adjudicated round with records to derive
# from. Calibration NEVER gates eligibility/emit-body (filing is never blocked on any arm):
# its only teeth are disclosure, the summary surface, and the never-blocking boundary offer.
_CALIBRATION_BACKINGS = ('clear', 'under-evidenced', 'unestablished')

# Every `key=` token this tool's queries and mutations PRINT. Ledger summaries and
# invalidation reasons are refused when they contain a word of the form `<token>=` drawn
# from this set: ledger text is identity data, never instruction and NEVER protocol, so
# auditor-derived text can never forge a field of the tool's own printed surface. One
# closed module-level list shared by ledger ingestion and the invalidation-reason
# refusal, so the two can never drift; a suite row asserts it covers every token the
# printers emit through a direct literal, a one-level helper return, or a line assembled
# into a local — the three emission shapes this module uses (a deeper helper chain would
# need a new arm in that row). Widening it beyond `query-findings`' own fields is deliberate — the
# never-protocol property must hold for the whole printed surface, not one line of it.
_PROTOCOL_TOKENS = (
    'action', 'adjudicated', 'adjudicated_verdict', 'advisory', 'anchor', 'arm',
    'attestation', 'backs_run',
    'baseline_identity', 'baseline_revision',
    'basis', 'body_digest', 'bound', 'bound_path', 'bound_root', 'bound_tier', 'cap',
    'cap_reached', 'claim', 'claims', 'class', 'classification', 'command', 'completeness',
    'conflict', 'consumer_dimensions_appended', 'converged', 'convergence_basis', 'count',
    'counts_round',
    'coverage', 'coverage_backing', 'coverage_reason', 'coverage_render',
    'degraded', 'digest', 'dispatch_regeneration', 'effective_unresolved', 'eligible',
    'epoch_round', 'evidence', 'finding', 'findings', 'findings_count', 'frozen', 'ground',
    'id', 'identity', 'instructions_digest',
    'invalid', 'invalidated', 'iterate', 'key', 'kind', 'latest_revision_landed',
    'locator', 'marker', 'markers', 'missing',
    'must_revise', 'non_bound_root', 'nonce', 'observed', 'offer_withheld', 'ordinal',
    'outcome', 'reason',
    'reinit_forced', 'remaining', 'reopened', 'revision', 'revision_ordinal',
    'revisions_applied',
    'round', 'rounds_run', 'scoped_round', 'sentinel_close', 'sentinel_open', 'state',
    'status',
    'stdin_digest', 'steering', 'steering_reason',
    'summary', 'superseded', 't1', 't2', 'tier', 'token',
    'unledgered_revise', 'unresolved',
    # issue #795: the tokens the trailing `next_call=` answer line emits, plus the
    # per-component status lines `query-boundary` prints when a component cannot be
    # established. Registered like every other printed field so auditor-derived text can
    # never forge one of the tool's own surface tokens.
    'next_call', 'needs', 'component', 'detail',
    'unresolved_must_revise', 'user_declined', 'user_rounds_used', 'verdict',
    # issue #743: tokens the advisory/invalid record read-back, the calibration query, and
    # the render report emit. Widening the vocabulary keeps auditor-derived summaries and
    # rationales unable to forge any of these fields of the tool's own printed surface.
    'adjudication_render', 'auditor_block', 'calibration', 'calibration_backing',
    'calibration_trigger',
    'evidence_state', 'impact_bearing', 'impact_class', 'landed', 'rationale',
    'record_class', 'records', 'unevidenced',
    # issue #792: the tokens the final-byte axis emits on `query-summary`, on
    # `query-final-byte`, and from `record-final-byte-offer`. Registered here so an
    # auditor-derived ledger summary, invalidation reason, or claim key can never forge a
    # field of the tool's own printed surface.
    'final_byte_coverage', 'final_byte_exhausted', 'final_byte_passes',
    'final_byte_reason', 'final_byte_trigger', 'grant',
    # issue #793: the tokens the durable byte history emits from `record-staged-write` and
    # `query-staged-write`. (`kind` and `digest` are already registered above, so the
    # round-kind answer adds no token of its own.) Registered for the same reason as every
    # entry here: an auditor-derived claim summary that could forge one of these would be
    # writing on the tool's own printed surface, and the dispatch-scope file the auditor
    # eventually reads is composed from exactly those summaries.
    'staged_write', 'recorded',
    # ...and the tokens the round-kind query and the dispatch-scope writer emit. `kind`
    # and `digest` were already registered above, so the tokens listed here are the
    # new ones.
    'claim_ids', 'sections', 'basis_digest', 'scope_path', 'scope_digest',
    # ...and the two counts record-return prints for a targeted round's per-claim sweep.
    'addressed', 'not_addressed',
)


# The settling-provenance keys `_clear_settling` drops, and the set each status may
# legally carry at the read boundary. Stated once so `_validate_ledger`'s residual-key
# arm and that helper cannot drift apart: `_clear_settling` clears every member, so any
# settling key a status is not listed with here is a shape the writer never emits.
# `supersession_round` is a member: it is written by a status change (the FILE sweep in
# `cmd_record_adjudication`) exactly like the others, so excluding it would have made
# `_clear_settling`'s status-agnostic sufficiency false in precisely the way its own
# docstring claims it is not — a future channel able to act on a `superseded` entry would
# carry the key onto the new status and the residual arm, which iterates this tuple,
# would not catch it (PR #612 review).
_SETTLING_KEYS = ('resolution_ordinal', 'ingest_provenance',
                  'invalidation_provenance', 'invalidation_reason',
                  'supersession_round')
_LEGAL_SETTLING_KEYS = {
    'unresolved': frozenset(),
    'superseded': frozenset(('supersession_round',)),
    'resolved': frozenset(('resolution_ordinal', 'ingest_provenance')),
    'invalidated': frozenset(('invalidation_provenance', 'invalidation_reason')),
}

# Fail FAST on the `_LEDGER_STATUSES` ↔ `_LEGAL_SETTLING_KEYS` coupling rather than fail
# LATE inside `_validate_ledger`. That arm indexes `_LEGAL_SETTLING_KEYS[status]` on a
# status already checked against `_LEDGER_STATUSES`, so a future status added to one
# constant and not the other would raise a raw `KeyError` from inside the read boundary —
# escaping the StateError→unestablished contract as an unhandled traceback on a state file
# the tool itself wrote. An import-time check turns that into a named startup failure at
# the desk, on the commit that introduces the drift. Deliberately not a bare `assert`
# (stripped under `python3 -O`) and deliberately not a `.get(status, frozenset())` default
# at the call site, which would silently accept the new status as carrying NO legal
# settling key — quietly wrong rather than loudly absent.
if set(_LEGAL_SETTLING_KEYS) != set(_LEDGER_STATUSES):
    raise RuntimeError(
        'issue-audit-state: _LEGAL_SETTLING_KEYS and _LEDGER_STATUSES have drifted '
        f'(symmetric difference {sorted(set(_LEGAL_SETTLING_KEYS) ^ set(_LEDGER_STATUSES))!r}); '
        'a ledger status must declare the settling-provenance keys it may legally carry')


def _forged_protocol_token(text):
    """The first protocol token `text` forges as a `<token>=` word, else None.

    Shared by ledger-summary ingestion, the invalidation-reason guard, and the claim-key
    guard, so one closed vocabulary governs every ingestion point that answers this hazard by
    REFUSAL. The per-finding evidence channel is deliberately not among them: it stores
    auditor text verbatim and answers the same hazard at its print boundary instead, so it
    consults no vocabulary. Deliberately count-free — an ordinal here rots on the next caller
    added. The decided recovery on a hit is to reword without the
    `<field>=` form and re-issue the call.

    The match is deliberately CASE-SENSITIVE: the capture is case-insensitive by character
    class, but `_PROTOCOL_TOKENS` holds the printers' exact lowercase spellings, so only a
    byte-identical token forges a field. `Status=x` prints as literal text and forges
    nothing, so refusing it would cost a legitimate summary for no safety gain.
    """
    for tok in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=', text or ''):
        if tok in _PROTOCOL_TOKENS:
            return tok
    return None


def _record_splitting_char(text):
    """The first record-splitting byte (`\\n` or `\\r`) in `text`, else None.

    The sibling of `_forged_protocol_token`: that guard stops auditor-derived text from
    forging a FIELD of the printed surface, this one stops it from forging a LINE. Both
    ledger summaries and invalidation reasons land in `query-findings`' `summary=<text>`
    trailing field (and in state a later round reconciles against), so an embedded CR or
    LF could visually clobber or split the reconciliation surface — the same reason
    `_is_bound_path` refuses both bytes in a bound path. The INGESTION callers
    (`_ingest_ledger`, `cmd_record_invalidate`) check the
    STRIPPED text, so a trailing
    CRLF from a Windows-shell heredoc is normalized away rather than refused and only an
    INTERIOR splitter is a hit there. The READ-BOUNDARY callers (`_validate_ledger`)
    pass stored text verbatim, where any splitter — a trailing one included — is corrupt
    state by construction, since the ingestion guards already stripped it before it was
    ever persisted. The decided recovery mirrors the vocabulary refusal: reword the text
    onto one line and re-issue the call.
    """
    for ch in ('\n', '\r'):
        if ch in (text or ''):
            return ch
    return None

# Ported budgets and bounds. These are the prose's numbers, preserved verbatim.
#
# Do not raise `_MAX_AUTOMATIC_REAUDITS` above zero: any non-zero value opens an audit
# round the user did not elect, which issue #1751 abolished. Its readers (`cmd_record_dispatch`'s
# spend predicate, `next_action`'s REVISE arm) are inert at zero, not dead — leave them.
_MAX_AUTOMATIC_REAUDITS = 0
_USER_ROUND_CAP = 3
# Do not zero `_MAX_CONFIRMING_ROUNDS` alongside `_MAX_AUTOMATIC_REAUDITS`, and do not
# fund the confirming round from the automatic pool: a clean `targeted` round never grounds
# the eligibility scan, so at zero a converged run clears approval only by file-anyway.
_MAX_CONFIRMING_ROUNDS = 1
# issue #792: the exact-byte final-byte pass draws on its OWN slot, outside
# `_USER_ROUND_CAP`, so a run that legitimately spent every discovery round still gets
# its safety pass. The slot is keyed to the canonical DIGEST rather than to the run, so
# a revision that changes the bytes re-arms it — and this cap is what bounds that
# re-arming of HONOURED passes, since Step 4's iterate loop can return to the approval
# election any number of times. It does NOT bound a run whose every pass degrades (a refund
# returns this headroom by design) — `_FINAL_BYTE_GRANT_CAP` below is what bounds that. A run
# at the cap files with the coverage field reporting its true value and the exhaustion
# disclosed on the summary line, never silently.
_FINAL_BYTE_PASS_CAP = 3
# The absolute ceiling on GRANTS. `_FINAL_BYTE_PASS_CAP` bounds *honoured* passes — a refund
# returns the headroom, which is what makes the safety pass real — but that alone does not bound
# a host where every pass degrades: refund -> re-arm -> offer -> dispatch -> refund never reaches
# the effective cap and inflates the funding sum each cycle. Each cycle is user-gated (a decline
# spends the slot without refunding), so this is a livelock the user can exit rather than an
# automatic one; the ceiling is the stop that does not depend on them exiting it. It is higher
# than the pass cap precisely so a run degrading occasionally still gets its full pass budget.
_FINAL_BYTE_GRANT_CAP = 6
# The round-funding budgets, enumerated ONCE. Two consumers read this set — `_validate`'s
# read-boundary integer-shape loop and `_funded_rounds` below — and a fourth budget added
# to only one of them fails silently in opposite directions (a round refused as unfunded,
# or a wrong-typed counter reaching the arithmetic unchecked). The counters themselves are
# deliberately NOT collapsed: each has its own cap, producer and re-arm rule, and the
# final-byte slot's whole point is that it sits outside `_USER_ROUND_CAP`. Only the
# enumeration is shared.
_ROUND_BUDGETS = ('automatic_reaudits_used', 'user_rounds_used', 'final_byte_passes_used',
                  # issue #793: the confirming whole-draft round's own counter. It joins
                  # the FUNDING enumeration (a confirming round is a real round the funding
                  # test must admit) while staying a separate counter with its own cap —
                  # exactly the shape `final_byte_passes_used` already established, and for
                  # the same reason: it must not compete with the shared automatic pool,
                  # which a run with two revision cycles exhausts before the confirming
                  # round is ever reached.
                  'confirming_rounds_used')
# `final_byte_passes_used` counts grants a round DID OR WILL claim. A REFUND must never
# decrement it: the granted round is already in `doc['rounds']` forever, and the funding test
# compares `len(doc['rounds'])` against `_funded_rounds`, so retracting a grant for an
# already-opened round leaves the run one round short of its own history and hard-refuses the
# replacement dispatch the refund just re-armed the offer for. The refund is recorded on this
# separate term instead, subtracted from the CAP comparison only (a degraded round was not a
# pass) and never from the funding sum. The counter IS decremented on exactly one class of
# event — the retraction of an OUTSTANDING grant that no dispatch ever consumed, by a decline or
# a recorded revision — which is consistent rather than contradictory: that grant funded no
# round, so removing it keeps the funding sum equal to what the rounds list actually needs. `_ROUND_BUDGETS` deliberately excludes it for the
# same reason — it is a cap-facing quantity, not a funding one — but it joins the read-boundary
# integer-shape check below on its own.
_FINAL_BYTE_REFUNDS_KEY = 'final_byte_refunds'
# The closed answer set of the final-byte coverage axis. Complete by construction: the
# derivation returns exactly one of these on every path, and asserts membership at its own
# return (the sibling `_COVERAGE_BACKINGS` discipline) — a token typo'd in a return dict
# would otherwise ship green, since nothing downstream re-checks it.
_FINAL_BYTE_COVERAGE = ('covered', 'uncovered', 'unestablished')

# ── The transition table (the vocabulary registry and lockstep record) ─────────────────
# One row per transition. The verdict-on-arm rows are consulted at runtime by
# _legality(); the other events' rows are the audited record of each cmd_* guard,
# kept honest by the tests' count-and-content lockstep rather than by a runtime read.
#
# This table is deliberately NOT a "single source of truth", and nothing here claims it is
# — read the split above literally. Only the verdict-on-arm rows decide anything at runtime;
# every other row is DOCUMENTATION of a guard that is hand-coded imperatively in its cmd_*
# function. Known, accepted limitation (raised on PR #552 and kept): a cmd_* guard edited
# without its row (or vice versa) can silently disagree, and the lockstep does not catch it
# — the lockstep checks table-vs-registry consistency, not table-vs-cmd_*-behavior.
# It is accepted rather than fixed because the fail-direction is bounded: the guards ARE the
# enforcement, so a drifted row cannot admit a wrong value, corrupt state, or skip a guard —
# it can only mislead a reader. That is a docs-accuracy risk, not a fail-open one.
# Revisit if any of these change: (a) a non-verdict-on-arm row acquires a runtime reader (at
# which point drift stops being cosmetic and this table must become authoritative for it),
# (b) a drift between a row and its guard actually reaches main, or (c) the cmd_* guards are
# reworked such that consulting legal/reason from the rows stops being a rewrite of each one.
# Every row names the tokens it references; the import-time
# assert below rejects any token outside its canonical set, so a renamed event, arm,
# verdict, reason or result token fails the import loudly instead of silently
# routing a lifecycle event to a rule that no longer matches. (Embed markers and
# override kinds are not transition-row columns, so the transition assert cannot name
# them; they are guarded independently — markers by the `_EMBED_MARKER_TEXT` ↔
# `_EMBED_MARKER_TOKENS` equality assert below, override kinds by argparse `choices=`
# and `_validate`.) The tests derive their
# expected row count from this table (`len(TRANSITIONS)`), so a row added here without
# a matching test row turns the suite RED.
#
# Columns: event, condition, arm, verdict, legal, result, reason
#   `arm`/`verdict` are None where the event does not discriminate on them.
#   `result` is the decided outcome token; `reason` is the breadcrumb/answer token
#   an illegal or refused transition carries.

_T = dict


def _row(event, condition, *, arm=None, verdict=None, legal=True, result=None, reason=None):
    return _T(event=event, condition=condition, arm=arm, verdict=verdict,
              legal=legal, result=result, reason=reason)


TRANSITIONS = (
    # init — the cold-start wipe is the ported delete-leftover-first rule and raises
    # no alarm; a same-run re-init is illegal absent an explicit force flag, so a
    # fresh automatic budget is never obtainable silently within a run.
    _row('init', 'cold-start-no-nonce', result='nonce-minted'),
    _row('init', 'same-run-nonce-no-rounds', result='nonce-echoed'),
    _row('init', 'same-run-nonce-over-rounds-unforced', legal=False,
         result='illegal-reinit', reason='reinit-requires-force'),
    _row('init', 'same-run-nonce-over-rounds-forced', result='reinit-forced'),
    _row('init', 'foreign-nonce', legal=False, result='illegal-reinit',
         reason='foreign-nonce'),

    # dispatch — one row per arm. The arm itself is decided by `query-arm` from
    # recorded facts alone; these rows say what a dispatch on each arm records.
    _row('dispatch', 'file-arm-write-landed', arm='file', result='digest-recorded'),
    _row('dispatch', 'embed-arm-entry', arm='embed', result='sentinels-generated'),
    _row('dispatch', 'inline-arm-entry', arm='inline', result='digest-recorded'),
    _row('dispatch', 'no-open-round', legal=False, result='illegal-dispatch',
         reason='round-not-open'),

    # return — the arm x verdict cross product, plus the carriage and verdict-line
    # rows. Retry precedence is fixed and lives in `_classify_return`: an absent
    # verdict line is classified by its absence before any arm/verdict rule applies.
    _row('return', 'verdict-on-arm', arm='file', verdict='FILE', result='accept-file'),
    _row('return', 'verdict-on-arm', arm='file', verdict='REVISE', result='accept-revise'),
    _row('return', 'verdict-on-arm', arm='file', verdict='DRAFT-UNREADABLE',
         result='retry-embed'),
    _row('return', 'verdict-on-arm', arm='embed', verdict='FILE', result='accept-file'),
    _row('return', 'verdict-on-arm', arm='embed', verdict='REVISE', result='accept-revise'),
    # DRAFT-UNREADABLE is legal only against a file-arm dispatch: on the embed arm the
    # auditor was handed the bytes inline, so it cannot truthfully report the draft
    # unreadable. Rejected as illegal and classified as a no-parseable-verdict
    # completion, never a second dispatch.
    _row('return', 'verdict-on-arm', arm='embed', verdict='DRAFT-UNREADABLE',
         legal=False, result='no-parseable-verdict', reason='unreadable-illegal-on-arm'),
    _row('return', 'verdict-on-arm', arm='inline', verdict='FILE', result='accept-file'),
    _row('return', 'verdict-on-arm', arm='inline', verdict='REVISE', result='accept-revise'),
    _row('return', 'verdict-on-arm', arm='inline', verdict='DRAFT-UNREADABLE',
         legal=False, result='no-parseable-verdict', reason='unreadable-illegal-on-arm'),
    _row('return', 'no-verdict-line', result='no-parseable-verdict'),
    # Absent carriage evidence is treated exactly like mismatched evidence: a FILE or
    # REVISE the auditor cannot prove it read is not a verdict, it is an unproven
    # claim, so it fails closed into the no-parseable-verdict retry accounting.
    _row('return', 'carriage-absent-or-mismatched', result='no-parseable-verdict'),
    _row('return', 'no-open-round', legal=False, result='illegal-return',
         reason='round-not-open'),
    _row('return', 'round-already-returned', legal=False, result='illegal-return',
         reason='duplicate-return'),

    # revision
    _row('revision', 'after-completed-round', result='ordinal-incremented'),
    _row('revision', 'no-rounds-recorded', legal=False, result='illegal-revision',
         reason='no-round-to-revise'),

    # override — the two kinds. Each is valid only while the revision ordinal (and,
    # on a file-arm epoch, the draft digest) recorded on it stays current.
    _row('override', 'user-decline-recorded', result='override-recorded'),
    _row('override', 'cap-reached-recorded', result='override-recorded'),

    # degraded
    _row('degraded', 'inline-arm-entered', arm='inline', result='degraded-recorded'),

    # creation
    _row('creation-epoch', 'bound-to-round', result='epoch-recorded'),
    _row('creation-epoch', 'no-round-recorded', legal=False, result='illegal-epoch',
         reason='no-round-to-bind'),
    _row('creation-attestation', 'body-matches', result='match'),
    _row('creation-attestation', 'body-mismatches', result='mismatch'),
    _row('creation-attestation', 'fetch-failed', result='attestation-unavailable'),
    _row('creation-attestation', 'no-epoch-recorded', legal=False,
         result='illegal-attestation', reason='no-epoch-to-attest'),
    # The attestation is tamper-evidence: once recorded it is forward-only. A second
    # attestation, and an epoch re-bind that would silently reset a recorded one,
    # are both illegal — a recorded mismatch must never be overwritable.
    _row('creation-attestation', 'already-recorded', legal=False,
         result='illegal-attestation', reason='attestation-already-recorded'),
    _row('creation-epoch', 'rebind-after-attestation', legal=False,
         result='illegal-epoch', reason='attestation-already-recorded'),

    # draft-binding (issue #562) — the tiered canonical-draft-root binding, recorded
    # exactly once per run by the first landed write. A second record is illegal (the
    # forced-reinit path stays the only route to a fresh binding); a non-absolute bound
    # path, a missing or unknown tier token, and a present-but-non-absolute non-bound
    # root each fail closed.
    _row('draft-binding', 'first-landed-write', result='draft-binding-recorded'),
    _row('draft-binding', 'already-recorded', legal=False,
         result='illegal-draft-binding', reason='binding-already-recorded'),
    _row('draft-binding', 'bound-path-not-absolute', legal=False,
         result='illegal-draft-binding', reason='binding-path-not-absolute'),
    _row('draft-binding', 'tier-missing', legal=False,
         result='illegal-draft-binding', reason='binding-tier-missing'),
    _row('draft-binding', 'tier-unknown', legal=False,
         result='illegal-draft-binding', reason='binding-tier-unknown'),
    _row('draft-binding', 'nonbound-not-absolute', legal=False,
         result='illegal-draft-binding', reason='binding-nonbound-not-absolute'),

    # write-failure (issue #562) — a canonical-draft overwrite that failed to land at
    # the bound path is recorded, so `latest_revision_landed` reports the latest revision
    # as unlanded and the presentation renders from the in-context revision bytes rather
    # than the stale file. (The dispatch write-path cross-check landed in issue #569 as an
    # additive guard in cmd_record_dispatch — it is not a transition row, so none is declared
    # for it here. The STRICT half — `binding-required-on-file-arm` — remains deferred.)
    _row('write-failure', 'recorded', result='write-failure-recorded'),

    # final-byte (issue #792) — the exact-byte safety pass offered immediately before the
    # Step 4 approval election, funded from its own slot outside `_USER_ROUND_CAP`. Both
    # outcomes SPEND the slot for the current canonical digest, so the offer cannot
    # re-fire against unchanged bytes as the iterate loop returns to the election; only an
    # accept increments the pass counter, because only an accept opens a round. The refund
    # row is the offer's own precondition made good: the offer promises a round that could
    # honour it, and a pass closing without a file-arm verdict did not.
    _row('final-byte', 'offer-accepted', result='final-byte-slot-spent'),
    _row('final-byte', 'offer-declined', result='final-byte-slot-spent'),
    _row('final-byte', 'slot-refunded-verdictless-pass',
         result='final-byte-slot-refunded'),
    _row('final-byte', 'slot-already-spent-for-digest', legal=False,
         result='illegal-final-byte', reason='final-byte-slot-already-spent'),
    _row('final-byte', 'pass-cap-reached', legal=False,
         result='illegal-final-byte', reason='final-byte-pass-cap-reached'),
    _row('final-byte', 'grant-ceiling-reached', legal=False,
         result='illegal-final-byte', reason='final-byte-grant-ceiling-reached'),
)


def _require(cond, msg):
    """An import-time invariant that survives `python3 -O` (a bare `assert` does not)."""
    if not cond:
        raise AssertionError(msg)


def _assert_transition_tokens():
    """Fail the import loudly when a transition names a token outside its set.

    A transition referencing an unknown event type, arm, verdict, reason or result
    token is a rule that can never fire — the exact silent-drift this module exists to
    remove from prose. Import fails rather than routing a live lifecycle event to a
    stale rule. (Embed markers and override kinds are not transition-row columns, so
    this assert cannot name them; they are guarded independently — see the
    `_EMBED_MARKER_TEXT`/`_EMBED_MARKER_TOKENS` equality assert and `_validate`.)
    """
    for r in TRANSITIONS:
        where = f"{r['event']}/{r['condition']}"
        _require(r['event'] in _EVENTS,
                 f'issue-audit-state: transition {where} names an event not in _EVENTS')
        _require(r['arm'] is None or r['arm'] in _ARMS,
                 f'issue-audit-state: transition {where} names an arm not in _ARMS: {r["arm"]}')
        _require(r['verdict'] is None or r['verdict'] in _VERDICTS,
                 f'issue-audit-state: transition {where} names a verdict not in _VERDICTS: '
                 f'{r["verdict"]}')
        _require(r['reason'] is None or r['reason'] in _ALL_REASONS,
                 f'issue-audit-state: transition {where} names a reason token not in the '
                 f'canonical reason sets: {r["reason"]}')
        # `_RESULTS` is declared INDEPENDENTLY of the table (never derived from it): an
        # assert whose comparand is built from the very rows it checks is a tautology that
        # cannot fail, which is a false signal of coverage rather than a guard.
        _require(r['result'] is None or r['result'] in _RESULTS,
                 f'issue-audit-state: transition {where} names a result not in _RESULTS: '
                 f'{r["result"]}')
    # The arm x verdict cross product must be total — an unrouted combination would
    # fall through to whatever the caller improvised, which is the prose failure mode.
    covered = {(r['arm'], r['verdict']) for r in TRANSITIONS
               if r['condition'] == 'verdict-on-arm'}
    _require(covered == {(a, v) for a in _ARMS for v in _VERDICTS},
             'issue-audit-state: the arm x verdict cross product is not total: missing '
             f'{ {(a, v) for a in _ARMS for v in _VERDICTS} - covered }')


# Reason tokens a transition row may carry: the eligibility reasons plus the
# transition-legality breadcrumbs.
_TRANSITION_REASONS = (
    'reinit-requires-force', 'foreign-nonce', 'round-not-open', 'duplicate-return',
    'unreadable-illegal-on-arm', 'no-round-to-revise', 'no-round-to-bind',
    'no-epoch-to-attest', 'attestation-already-recorded',
    # issue #562 draft-binding / write-failure legality breadcrumbs
    'binding-already-recorded', 'binding-path-not-absolute', 'binding-tier-missing',
    'binding-tier-unknown', 'binding-nonbound-not-absolute',
    # issue #792 final-byte slot legality breadcrumbs
    'final-byte-slot-already-spent', 'final-byte-pass-cap-reached',
    'final-byte-grant-ceiling-reached',
)
_ALL_REASONS = set(_ELIGIBILITY_REASONS) | set(_TRANSITION_REASONS)

_require(set(_EMBED_MARKER_TEXT) == set(_EMBED_MARKER_TOKENS),
         'issue-audit-state: _EMBED_MARKER_TEXT keys must exactly match _EMBED_MARKER_TOKENS: '
         f'{set(_EMBED_MARKER_TEXT) ^ set(_EMBED_MARKER_TOKENS)}')
_require(set(_ROUND_OUTCOMES) <= set(_VERDICTS) | {'no-verdict'},
         'issue-audit-state: _ROUND_OUTCOMES names an outcome that is neither a verdict '
         'nor the decided verdict-less terminal')
_assert_transition_tokens()


# ── Process plumbing ───────────────────────────────────────────────────────────

def _fail(prefix, msg, code=1):
    """Emit a named stderr breadcrumb and exit non-zero (the mutation contract)."""
    sys.stderr.write(f'issue-audit-state.py {prefix}: {msg}\n')
    raise SystemExit(code)


def _run(cmd, *, data=None):
    return subprocess.run(
        cmd, input=data, capture_output=True, check=True,
    )


@functools.lru_cache(maxsize=1)
def _repo_root():
    """The git repo root, or None. Native `git` subprocess — never a `.sh` exec (#275).

    Memoized: the value cannot change within a process (the cwd never moves mid-run), but
    `state_path()` is called by both `load_state` and `save_state`, so every mutation would
    otherwise re-spawn `git rev-parse` for the same answer. An explicit `root=` argument
    bypasses this entirely (the shell tests instead anchor by `git init`-ing each sandbox).
    """
    try:
        r = _run(['git', 'rev-parse', '--show-toplevel'])
    except (subprocess.CalledProcessError, OSError) as exc:
        # The anchor SELECTION is changing (cwd fallback): breadcrumb the cause so a
        # split-state mystery (state one directory up, fresh file here) is diagnosable.
        print(f'issue-audit-state.py: git rev-parse failed ({exc}); anchoring state '
              f'to the current directory', file=sys.stderr)
        return None
    root = r.stdout.decode('utf-8', 'replace').strip()
    return Path(root) if root else None


def state_path(slug, root=None):
    """`.prflow/tmp/spec/<slug>/issue-audit-state-<slug>.json`, anchored to the repo/worktree root.

    Deliberately NOT the main-worktree root the draft file uses: sharing one record
    across concurrent worktree runs would let a foreign cold-start wipe this run's state.
    """
    # The slug keys a filesystem path (guard-class 2): an escaping shape would read,
    # write, and — worst — cold-start-DELETE outside .prflow/tmp. Fail closed.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', slug or ''):
        raise StateError(f'slug {slug!r} is not a safe path segment '
                         f'([A-Za-z0-9][A-Za-z0-9._-]*)')
    base = root if root is not None else (_repo_root() or Path.cwd())
    return Path(base) / '.prflow' / 'tmp' / 'spec' / slug / f'issue-audit-state-{slug}.json'


def _host_abs_path(value, _pathmod=os.path):
    """True iff ``value`` is absolute per the interpreter's OWN path module.

    A leading ``/`` on POSIX; a drive-letter or UNC root on Windows (``C:\\``,
    ``C:/``, ``\\\\host\\share``). A rooted path naming no drive (``\\Users\\x``,
    ``/Users/x`` on Windows) is refused on EVERY supported interpreter: ``ntpath.isabs``
    classified that True before 3.13 and False from 3.13, so on a Windows-style
    module absoluteness additionally requires a non-empty drive — which makes the
    verdict version-stable instead of depending on that changed classification.
    Pure: no environment probe and no filesystem access. Mirrored verbatim by
    ``scripts/render-audit-prompt.py``'s ``_host_abs_path`` so both path checks
    agree on every input on every supported host (issue #1762 — edited together).
    """
    if not _pathmod.isabs(value):
        return False
    if _pathmod.sep == "\\":  # a Windows-style path module (ntpath)
        return _pathmod.splitdrive(value)[0] != ""
    return True


def _is_bound_path(p, _pathmod=os.path):
    """True iff `p` is a non-empty absolute path string with no embedded newline or CR.

    The binding is recorded and compared as an opaque string (Windows-safe, #275/#295):
    the tool never execs a `.sh` helper and never touches the filesystem to validate it.
    Absoluteness is the one structural check — a relative bound path would resolve
    differently at each write site and defeat the whole point of a bound root. An
    embedded newline OR carriage return is rejected: `recorded verbatim` means no
    normalization, not acceptance of record-splitting bytes that could forge a second
    field on readback. A space is NOT rejected — a real absolute path legitimately
    contains one (e.g. macOS `/Users/jo/My Repos/...`), so consumers of the space-
    delimited query lines must extract path fields by their `key=` anchor, never by a
    positional whitespace split.
    """
    return (isinstance(p, str) and bool(p) and _host_abs_path(p, _pathmod)
            and '\n' not in p and '\r' not in p)


# ── Issue #1040: write serialization via an exclusive-create sentinel ──────────────
# Two concurrent invocations for the same slug in one checkout must produce a state
# document reflecting one of them entirely and then the other entirely, never a mixture.
# The mechanism is an `os.open(O_CREAT|O_EXCL)` sentinel beside the state file (the
# single-owner pattern scripts/verification-flight.py already uses) plus a per-writer
# `tempfile.mkstemp` temp path in save_state. Read-only subcommands take no sentinel.
# Every failure the section raises is phrased as a `could not persist state to <file>:`
# StateError, so it lands in the existing cannot-persist-state routing class rather than
# opening a fourth mutation-exit destination.

# Test-only overrides so the shell-level tests drive the process boundary in
# milliseconds. NOT CLI flags and NOT read from .prflow/config.json — the shipped path has
# exactly one decided setting. The DEVFLOW_ prefix is the DECIDED choice (issue #1040):
# CLAUDE.md freezes that namespace pending the #1004 Tier-3 rename, so a PRFLOW_ spelling
# would be the one variable that ticket's sweep would miss. Both names are recorded in the
# #1040 changeset as members #1004 must migrate.
_IAS_ACQUIRE_WINDOW_ENV = 'DEVFLOW_IAS_ACQUIRE_WINDOW_S'
_IAS_STALE_AFTER_ENV = 'DEVFLOW_IAS_STALE_AFTER_S'


def _positive_env_float(name, default):
    """The override in `name` when it holds a usable positive number, else `default`.

    A value that is absent, empty, non-numeric, or non-positive alike is ignored and the
    shipped default applies — the closed set of rejected shapes stated by the acceptance
    criteria.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


# The sentinel body is `<pid> <owner-nonce>`, capped so a reader never pulls an unbounded
# file into memory and so a body longer than the cap is DETECTABLE rather than truncated
# into something that parses.
_SENTINEL_MAX_BYTES = 64
_SENTINEL_OWNER_HEX = 32  # os.urandom(16).hex()


def _read_sentinel_body(sentinel):
    """The sentinel's raw bytes, or None when the read failed. Raises nothing."""
    try:
        with open(sentinel, 'rb') as fh:
            # +1 so a body exceeding the cap is detectable rather than silently truncated.
            return fh.read(_SENTINEL_MAX_BYTES + 1)
    except OSError:
        return None


def _parse_sentinel_body(data):
    """`(pid, owner)` parsed from a sentinel body, each None when unestablished.

    The two fields are established INDEPENDENTLY and neither is inferred from the other.
    A body that is absent, empty, whitespace-only, or longer than `_SENTINEL_MAX_BYTES`
    yields `(None, None)`. A body carrying only a decimal pid — the shape a hand-planted
    sentinel produces, and the shape every writer produced before the owner nonce existed —
    yields that pid with `owner=None`, so such a sentinel can never be mistaken for one
    THIS process owns: `None` is the unestablished reading, and `__exit__` compares the
    owner for equality against a 32-hex-digit nonce it generated, which `None` never
    matches. The owner is shape-checked rather than merely non-empty, so a truncated or
    garbled field reads unestablished instead of being compared as data.
    """
    if data is None or len(data) > _SENTINEL_MAX_BYTES:
        return None, None
    fields = data.decode('utf-8', 'replace').split()
    if not fields:
        return None, None
    pid = fields[0] if re.fullmatch(r'[0-9]+', fields[0]) else None
    owner = None
    if len(fields) > 1 and re.fullmatch(rf'[0-9a-f]{{{_SENTINEL_OWNER_HEX}}}', fields[1]):
        owner = fields[1]
    return pid, owner


def _read_sentinel_pid(sentinel):
    """The pid recorded in the sentinel as a decimal string, or the literal
    `unestablished` when it cannot be established (see `_parse_sentinel_body`). Staleness
    is decided by mtime alone, so an unestablished pid never changes the
    acquire/refuse/break decision; it only shapes the breadcrumb. Surrounding whitespace
    is ignored, so a pid written with a trailing newline renders as the pid.
    """
    pid, _ = _parse_sentinel_body(_read_sentinel_body(sentinel))
    return pid if pid is not None else 'unestablished'


def _replace_with_retry(src, dst, *, attempts=5, delay=0.02):
    """`os.replace(src, dst)` with a bounded retry over `PermissionError` only.

    On Windows a `MoveFileEx`-backed replace onto a path a lock-free reader currently has
    open raises `PermissionError`; retry it briefly. Every OTHER `OSError` propagates on
    the first attempt, unchanged, so the existing `could not persist state to ` breadcrumb
    and its test row keep their shape. Exhausting the retries re-raises the last
    `PermissionError` for the caller to route.
    """
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


class _StateSection:
    """Serialize mutating state writes for one slug via an O_CREAT|O_EXCL sentinel.

    Entered around main()'s single dispatch site for every non-read-only subcommand, so a
    handler's `load_state` .. `save_state` runs under exclusion and the second writer's
    read happens after the first writer's write. No compare-and-swap token is needed
    because the load sits inside the section.

    STATED BOUND — exclusion is heartbeat-free, so it is bounded by `stale_after_s`. The
    holder does not refresh the sentinel's mtime while it works, so a mutation that stays
    inside the section for longer than `stale_after_s` can have its own sentinel judged
    abandoned and age-broken by a contending writer, and the two then overlap: the
    guarantee this class provides is therefore "serialized up to `stale_after_s` of
    occupancy", not unconditional mutual exclusion. That is ACCEPTED here rather than
    fixed, on two grounds. First, occupancy is a sub-second load-modify-save of one small
    JSON document — the section holds no network call, no subprocess, and no stdin read
    (main() hoists stdin above the section precisely so a handler cannot block on fd 0
    while holding it). Second, the owner NONCE written into the sentinel bounds the blast
    radius on the way out: __exit__ unlinks only a sentinel whose recorded owner is still
    the nonce this section wrote, so a holder whose sentinel was age-broken releases
    nothing and cannot strip the breaker's exclusion — it breadcrumbs instead. That second
    ground previously rested on the sentinel's `(st_dev, st_ino)`, which does NOT support
    it: the breaker unlinks our inode and creates its own file at the same path, and an
    inode-reusing filesystem may hand it the identity we recorded, so the identity check
    could match a file we do not own and unlink a live holder's sentinel. The nonce is
    generated per acquisition and never reissued by the kernel, so it answers the question
    the identity check only appeared to. Raising the bound by
    adding a heartbeat (a keepalive touch, or a refresh on a long operation) is a DESIGN
    CHANGE with its own failure modes, not a bug fix; do not introduce one without
    deciding that trade deliberately. The relation `stale_after_s < acquire_window_s` is
    the separate invariant that keeps a CRASHED writer from wedging the slug permanently;
    see the acquire loop.
    """

    def __init__(self, slug, root=None, *, acquire_window_s=45, stale_after_s=30):
        # Compose the sentinel FROM the resolved state path (string-concatenate '.lock',
        # never Path.with_suffix — a slug may itself contain a dot), so a run whose git
        # resolution degraded still locks the file it actually writes.
        self._state_path = state_path(slug, root)
        self._sentinel = str(self._state_path) + '.lock'
        self._parent = os.path.dirname(self._sentinel)
        self._acquire_window_s = _positive_env_float(
            _IAS_ACQUIRE_WINDOW_ENV, acquire_window_s)
        self._stale_after_s = _positive_env_float(_IAS_STALE_AFTER_ENV, stale_after_s)
        # The owner nonce written into the sentinel, set only once an acquisition fully
        # succeeded. None means this section holds nothing and must release nothing.
        self._token = None

    def _persist_error(self, detail):
        return StateError(f'could not persist state to {self._state_path}: {detail}')

    def _try_create(self):
        """Attempt the exclusive create once. True on success (ownership token recorded),
        False on contention (FileExistsError) or a missing parent. A read-only filesystem
        or permission denial raises a cannot-persist StateError immediately, since
        retrying a condition that does not clear only converts a named failure into a
        stall.
        """
        try:
            fd = os.open(self._sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        except FileNotFoundError:
            # A missing parent — not the immediate-raise class. Recreate and let the
            # bounded loop retry (should not recur, since __enter__ mkdir'd first).
            os.makedirs(self._parent, exist_ok=True)
            return False
        except OSError as exc:
            raise self._persist_error(
                f'could not create the audit-state section sentinel '
                f'{self._sentinel}: {exc}') from exc
        try:
            try:
                # A fresh unforgeable nonce per successful acquisition, written INTO the
                # sentinel so ownership can be re-established from content at release. The
                # pid stays first and unchanged — it is the breadcrumb operand, and a
                # hand-planted bare-pid sentinel must keep parsing as one.
                owner = os.urandom(_SENTINEL_OWNER_HEX // 2).hex()
                os.write(fd, f'{os.getpid()} {owner}'.encode('ascii'))
            finally:
                os.close(fd)
            self._token = owner
        except OSError as exc:
            # An OSError after the exclusive create succeeded (an ENOSPC on the body write,
            # an entropy or close failure) must still route as a cannot-persist StateError,
            # not escape as a raw traceback that breaks the mutation contract. `self._token`
            # is assigned only after the write and close both succeed, so a section that
            # failed here owns nothing and releases nothing. Best-effort unlink the partial
            # sentinel so it does not block later acquires until it ages out.
            try:
                os.unlink(self._sentinel)
            except OSError:
                pass
            raise self._persist_error(
                f'could not initialize the audit-state section sentinel '
                f'{self._sentinel}: {exc}') from exc
        return True

    def _break_if_stale(self):
        """When the held sentinel's mtime age exceeds stale_after_s, re-stat it and unlink
        it only while the observed mtime is unchanged from the one judged stale, then
        re-attempt the exclusive create EXACTLY ONCE. True iff the break-and-recreate
        acquired the section. A changed mtime, a vanished sentinel, or a losing re-create
        each return False → the ordinary retry loop.
        """
        try:
            first = os.stat(self._sentinel)
        except OSError:
            return False  # vanished/unstattable — a create will win next iteration
        age = time.time() - first.st_mtime
        if age <= self._stale_after_s:
            return False
        pid = _read_sentinel_pid(self._sentinel)
        try:
            second = os.stat(self._sentinel)
        except OSError:
            return False
        if second.st_mtime != first.st_mtime:
            return False  # a live holder touched it between judging and unlinking
        try:
            os.unlink(self._sentinel)
        except OSError as exc:
            # Both unlink sites catch every OSError (a directory planted at the path, a
            # permission-denied parent, a Windows sharing violation), not only
            # FileNotFoundError. A failing break unlink returns the mutation to its
            # ordinary retry loop.
            sys.stderr.write(
                f'issue-audit-state.py: could not break the stale audit-state sentinel '
                f'{self._sentinel} (pid {pid}, age {age:.0f}s): {exc}\n')
            return False
        sys.stderr.write(
            f'issue-audit-state.py: broke a stale audit-state sentinel {self._sentinel} '
            f'(pid {pid}, age {age:.0f}s) and proceeded\n')
        return self._try_create()

    def __enter__(self):
        # Create the parent directory BEFORE the first exclusive-create so a fresh clone,
        # a fresh adopter checkout, and a bare test sandbox — none of which carry the
        # ignored state tmp directory — acquire instead of raising on FileNotFoundError.
        # An OSError here (a non-directory occupies the path, a permission-denied parent)
        # routes as a cannot-persist StateError, not a raw traceback — the section's
        # single-failure-vocabulary contract holds on the setup path too.
        try:
            os.makedirs(self._parent, exist_ok=True)
        except OSError as exc:
            raise self._persist_error(
                f'could not create the audit-state section directory '
                f'{self._parent}: {exc}') from exc
        deadline = time.monotonic() + self._acquire_window_s
        while True:
            if self._try_create():
                return self
            if self._break_if_stale():
                return self
            if time.monotonic() >= deadline:
                # Under the shipped bound relation (window > stale) an abandoned sentinel is
                # always broken strictly inside the window, so this arm is unreachable; it
                # is the fail-closed arm for a host whose overrides invert the relation. The
                # state file is left byte-identical (only the sentinel was ever touched).
                pid = _read_sentinel_pid(self._sentinel)
                raise self._persist_error(
                    f'the audit-state section sentinel {self._sentinel} is held by pid '
                    f'{pid} and was not released within {self._acquire_window_s:g}s')
            time.sleep(0.02)

    def __exit__(self, exc_type, exc, tb):
        # Ownership-checked release on EVERY exit path — the mutation succeeding,
        # save_state raising, and the handler raising. Best-effort and total: a failing
        # unlink never replaces an in-flight exception (the section's own outcome and its
        # routed `could not persist state to ` breadcrumb stand), and the release failure
        # is reported beside it. Returning False never suppresses that exception.
        #
        # Ownership is decided by the owner NONCE this section wrote into the sentinel, and
        # deliberately NOT by the sentinel's `(st_dev, st_ino)`. An identity check is
        # forgeable by the kernel: after an age break the breaker unlinks our inode and
        # O_EXCL-creates its own file at the same path, and on an inode-reusing filesystem
        # (ext4 and friends) it may be handed the SAME `(st_dev, st_ino)` we recorded at
        # acquire — so an identity comparison would match and this section would unlink the
        # LIVE holder's sentinel, precisely the outcome the check exists to prevent. A
        # 128-bit nonce is not reissued by the kernel, so content equality answers "is this
        # still the file I created?" where identity equality only answers "does this file
        # occupy the slot mine did?".
        if self._token is None:
            return False  # never acquired — this section owns nothing to release
        try:
            with open(self._sentinel, 'rb') as fh:
                body = fh.read(_SENTINEL_MAX_BYTES + 1)
        except FileNotFoundError:
            return False  # already gone (age-broken by another process) — clean exit
        except OSError as exc2:
            sys.stderr.write(
                f'issue-audit-state.py: could not read the audit-state sentinel '
                f'{self._sentinel} on release: {exc2}\n')
            return False
        if _parse_sentinel_body(body)[1] == self._token:
            try:
                os.unlink(self._sentinel)
            except OSError as exc2:
                sys.stderr.write(
                    f'issue-audit-state.py: could not unlink the audit-state sentinel '
                    f'{self._sentinel} on release: {exc2}\n')
        else:
            # After an age break the file here belongs to the breaker; unlinking it by
            # path would strip a live holder's exclusion. Leave it and breadcrumb that
            # this section's own sentinel was broken by another process.
            sys.stderr.write(
                f"issue-audit-state.py: this section's own audit-state sentinel "
                f'{self._sentinel} was broken by another process; leaving the current '
                f'file in place\n')
        return False


# ── Digests ────────────────────────────────────────────────────────────────────

class _DigestError(Exception):
    """Raised by every digest helper below when a digest cannot be established.

    Defined ahead of its first raise: the raises are all inside function bodies, so a
    later definition would still bind at call time, but a reader auditing whether the
    fail-closed digest paths are real should not have to scroll past the raise to find
    the type.
    """

    # issue #793: an optional closed REASON token, set at the raise site. `steering_state`
    # used to recover this by string-prefixing the message it had itself raised, so a
    # reworded message silently degraded a named scope-file arm to the coarse
    # `regeneration-failed`. An attribute couples the two by construction.
    reason = None

    def __init__(self, *args, reason=None):
        super().__init__(*args)
        if reason is not None:
            self.reason = reason


def hash_bytes(data):
    """Hash bytes with `git hash-object --stdin --no-filters`.

    ONE filter-free mode at every compare site. The path-mode form is never used
    anywhere in this module: it applies clean/CRLF content filters, so under
    `core.autocrlf=true` (or `* text=auto`) it returns a different object ID than
    stdin-mode does for the same bytes — and a dispatch digest that disagrees with an
    eligibility digest on the same file would refuse an untouched clean draft. The
    surviving audit-prompt template instructs the auditor to use `--no-filters` for
    exactly this reason, so all three digests agree byte-for-byte on every host.
    """
    try:
        r = _run(['git', 'hash-object', '--stdin', '--no-filters'], data=data)
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode('utf-8', 'replace').strip()
        raise _DigestError(f'git hash-object failed: {err}') from exc
    except OSError as exc:
        raise _DigestError(f'could not execute git: {exc}') from exc
    oid = r.stdout.decode('ascii', 'replace').strip()
    if not oid:
        # `_DigestError` is otherwise raised only on a non-zero exit / OSError, but a
        # shimmed or broken `git` can exit 0 with empty stdout. An empty object ID must
        # never read as a successful digest: `''` compares equal to another `''` on the
        # override ground (`_valid_override`'s `want != current_digest`), which would
        # ground eligibility on unaudited bytes. Fail closed at the single source that
        # feeds every compare site rather than trusting each site to reject `''`.
        raise _DigestError('git hash-object returned an empty object id on exit 0')
    return oid


def hash_file(path):
    """Hash a file's bytes, read in binary. Raises _DigestError when unreadable.

    The breadcrumb names no file ROLE: callers pass arbitrary anchors, and a message calling
    a measured source file "the draft file" sends the reader looking for the wrong artifact.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise _DigestError(f'could not read {path}: {exc}') from exc
    return hash_bytes(data)


# ── issue #704: per-finding evidence ──
#
# An additive payload extending this state owner rather than a new helper: it must survive a
# context compaction and be read back by the drafting, steelman, audit, and adjudication
# stages, which is the same durability argument that put the per-finding ledger here (#603).

# The evidence fields the per-finding completeness check requires. `baseline_identity` is
# deliberately NOT required: an auditor running under the Step 3.6 information diet can
# capture the base revision it read, but the state file that holds per-claim identities is
# out of bounds to it, so requiring an identity would make every auditor-supplied evidence
# item incomplete by construction.
_EVIDENCE_REQUIRED = ('locator', 'command', 'observed', 'baseline_revision')
_EVIDENCE_OPTIONAL = ('baseline_identity',)
_EVIDENCE_FIELDS = _EVIDENCE_REQUIRED + _EVIDENCE_OPTIONAL
# Import-time coupling: `cmd_record_finding_evidence`
# carries an omitted OPTIONAL field forward AFTER deriving `completeness` from the REQUIRED ones,
# which is only sound while the two sets are disjoint. Overlap them and the stored completeness
# would silently disagree with the record it was derived from.
assert not (set(_EVIDENCE_REQUIRED) & set(_EVIDENCE_OPTIONAL)), (
    'issue-audit-state.py: _EVIDENCE_REQUIRED and _EVIDENCE_OPTIONAL must stay disjoint')
# Bounded encoding, half one: a length cap, so a hostile or runaway auditor return cannot
# grow the state file without bound. Truncation is DISCLOSED in the stored bytes rather than
# silent, so a replay driven from truncated evidence can tell it is reading a prefix.
_EVIDENCE_MAX_CHARS = 4096
# Derived from the cap, never restated: a hand-copied number here would make the DISCLOSURE
# lie the moment the cap moved, which is the one thing a truncation notice must never do.
_EVIDENCE_TRUNCATION_MARK = (
    f'…[truncated by issue-audit-state.py at {_EVIDENCE_MAX_CHARS} chars]')


def _bound_evidence(text):
    """Cap one evidence field, disclosing any truncation in the stored bytes."""
    if text is None:
        return None
    if len(text) <= _EVIDENCE_MAX_CHARS:
        return text
    return text[:_EVIDENCE_MAX_CHARS] + _EVIDENCE_TRUNCATION_MARK


def evidence_completeness(entry):
    """`(completeness, missing)` — `complete` only when every required field is present
    AND established (a field holding the literal `unestablished` counts as missing).

    Absent-or-incomplete is recorded as `incomplete` and NEVER as verified: the adjudication
    policy routes an incomplete item to full independent verification, so a defaulted-away
    missing field would silently buy a cheap replay the evidence never earned.
    """
    missing = [f for f in _EVIDENCE_REQUIRED
               if not isinstance(entry.get(f), str) or not entry[f].strip()
               # `unestablished` is this module's ONE spelling of an unresolvable
               # measurement, and the auditor bar instructs an auditor to report a field it
               # could not establish that way. A string-shape test alone would grade that
               # `complete` and buy the cheap replay — the unknown-is-not-a-value
               # collapse this module refuses everywhere it reads a recorded
               # `unestablished` marker.
               or entry[f].strip() == _UNESTABLISHED]
    return ('incomplete' if missing else 'complete'), missing


def _observed_divergent(a, b):
    """True when two evidence items' observed outputs must be treated as disagreeing.

    Plain inequality is not sufficient: `_bound_evidence` caps each field, so two probes
    whose outputs diverge only PAST the cap are stored as byte-identical truncated strings
    and would compare equal — silently erasing the conflict and buying the cheap replay that
    "a conflict never collapses silently to either value" exists to deny. So a pair whose
    observed values are equal but BOTH truncated is reported as divergent: the comparison
    could not see the bytes that would decide it, and unknown is never agreement.
    """
    if a != b:
        return True
    # Gated on the LENGTH `_bound_evidence` truncation actually produces, not on the suffix
    # alone: the mark is a fixed literal an auditor's own observed output can end with without
    # ever having been capped, and a suffix-only test lets that text force a refusal on a
    # byte-identical replay and manufacture a conflict between two agreeing probes.
    return (len(a or '') == _EVIDENCE_MAX_CHARS + len(_EVIDENCE_TRUNCATION_MARK)
            and (a or '').endswith(_EVIDENCE_TRUNCATION_MARK))


def evidence_conflicts(store):
    """Map each evidence key to the sorted keys it CONFLICTS with, else an empty list.

    Two items conflict when they cite the same locator AND ran the same command but report
    different observed output — two probes that disagree. The command is part of the key
    deliberately: two findings legitimately probing one `path:line` with *different*
    commands normally produce different output without disagreeing about anything, and
    treating that as a conflict would force full re-verification on every such pair.

    The conflict is surfaced for verification and never auto-resolved by picking one value
    (#704 AC10): both observed values stay recorded and both keys name each other, so no
    reader can collapse the pair silently.
    """
    by_probe = {}
    for key, entry in store.items():
        if entry.get('locator'):
            by_probe.setdefault((entry['locator'], entry.get('command')), []).append(key)
    out = {k: [] for k in store}
    for group in by_probe.values():
        for key in group:
            out[key] = sorted(
                other for other in group
                if other != key and _observed_divergent(store[other].get('observed'),
                                                        store[key].get('observed')))
    return out


def _validate_finding_evidence(doc):
    """Re-enforce the per-finding evidence shape at the READ boundary.

    The stored text is auditor-derived, so it is DATA: unlike the one-line ledger summary
    transport — which refuses newlines and `<field>=` tokens because it lands unencoded in a
    printed field — this channel accepts those bytes and answers them at the print
    boundary with its own bounded JSON encoding — at the exact scope `#704-25` pins: a
    record-splitting byte cannot forge a LINE, and the decision fields cannot be forged
    because they precede every auditor value, but a `<field>=`-shaped token INSIDE a quoted
    evidence value is not neutralized for a whitespace-splitting reader, which is why that
    line must be parsed by its JSON quoting. What is validated here is the CONTAINER
    (keys, types, caps), never the text's content.
    """
    store = doc.get('finding_evidence')
    if store is None:
        return
    if not isinstance(store, dict):
        raise StateError(f'finding_evidence payload {store!r} is not an object')
    for key, entry in store.items():
        if not isinstance(key, str) or not re.fullmatch(r'[0-9]+:[0-9]+', key or ''):
            raise StateError(f'finding-evidence key {key!r} is not <round>:<finding-id>')
        if not isinstance(entry, dict):
            raise StateError(f'finding-evidence {key!r} is not an object')
        for field in _EVIDENCE_FIELDS:
            val = entry.get(field)
            if val is not None and not isinstance(val, str):
                raise StateError(f'finding-evidence {key!r} {field} {val!r} is not a string')
            if isinstance(val, str) and len(val) > _EVIDENCE_MAX_CHARS + len(
                    _EVIDENCE_TRUNCATION_MARK):
                raise StateError(f'finding-evidence {key!r} {field} exceeds the '
                                 f'{_EVIDENCE_MAX_CHARS}-char bound')
        # `completeness` GATES the verification scope (a `complete` item buys the cheap
        # locator replay), so it is never trusted as stored: its CONTAINER is validated here
        # like any other decided field, and its VALUE is re-derived below rather than read —
        # which is what keeps a hand-edited `complete` beside blank required fields from
        # buying a relaxation the evidence never earned.
        comp = entry.get('completeness')
        if comp not in ('complete', 'incomplete'):
            raise StateError(f'finding-evidence {key!r} completeness {comp!r} is outside the '
                             f'canonical set')
        derived = evidence_completeness(entry)[0]
        if comp != derived:
            # RE-DERIVED, never rejected: `completeness` is a pure function of the fields
            # beside it, so the derivation is authoritative and the stored value carries no
            # information the recompute lacks. Raising here would be fail-closed in the wrong
            # direction — the document stops loading, and EVERY later mutation of the run
            # (`record-return`, `record-adjudication`, `emit-body`) exits non-zero over one
            # unrelated evidence item, which is the run-wide lockout `_nonneg_int` names as
            # the thing this component must never do. It is reachable without any hand edit:
            # a rule change to `evidence_completeness` (this PR made one) re-derives a
            # different answer for a record the previous build wrote. Recomputing keeps the
            # whole guarantee the raise was protecting — a hand-edited `complete` beside
            # blank fields still cannot buy the cheap replay, because the stored value is
            # never what is used.
            sys.stderr.write(
                f'issue-audit-state.py: finding-evidence {key!r} stored completeness '
                f'{comp!r}; re-derived {derived!r} and using the derived value\n')
            entry['completeness'] = derived


def split_body(raw):
    """Return the draft body below the title heading, as bytes.

    The body-only digest is what a created issue's fetched body is attested against,
    so the split rule is decided rather than heuristic:
      * leading blank lines are skipped when looking for the title;
      * the title is a level-1 (`# `) heading — a bare `#` line is accepted as a
        title too — and only the first non-blank line is ever inspected; a `##`
        there means there is no title, and any later heading is ordinary body
        content;
      * when no title heading is found the whole content is the body;
      * blank separator lines between the title and the body are dropped;
      * line endings are preserved verbatim (bytes throughout, never decoded), so a
        CRLF draft attests against its own bytes rather than a normalized copy.
    """
    lines = raw.splitlines(keepends=True)
    if not lines:
        return raw
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first >= len(lines):
        return raw
    candidate = lines[first].strip()
    if candidate != b'#' and not candidate.startswith(b'# '):
        return raw
    j = first + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    return b''.join(lines[j:])


# ── State I/O ──────────────────────────────────────────────────────────────────

class StateError(Exception):
    """State that cannot be trusted or safely persisted.

    Raised for three causes, deliberately sharing one fail-closed treatment (queries
    answer state-unestablished; mutations exit non-zero with the breadcrumb): a state
    file that cannot be trusted (unreadable, unparseable, foreign, or shape-invalid),
    a slug that is not a safe path segment (refused before any filesystem I/O), and a
    state document that could not be persisted.
    """


_REQUIRED_TOP = ('schema_version', 'slug', 'nonce', 'rounds', 'revisions', 'overrides')


def _validate_ledger(doc, rnd, num):
    """Re-enforce the per-finding-ledger invariants at the READ boundary (issue #603).

    Scope, stated exactly: every invariant the ingestion boundary enforces is re-enforced
    here, over the settling-provenance surface `_SETTLING_KEYS` names. The one key outside
    that surface is `reopen_provenance`, which is deliberately exempt from clearing (see
    `_clear_settling`) as the entry's genuine regression history — a residual copy IS
    readable, by `_convergence_basis`, and its absence-shape is NOT enforced here. Read
    "every invariant" as bounded by that stated exemption, not as coverage of every key an
    entry could physically carry.

    Absent is legal (a FILE round, a `REVISE … unestablished` round, and every
    pre-change round record no ledger) — present-but-wrong-shape is corrupt, the same
    pattern `draft_binding` and `write_failures` follow. Every violation raises
    StateError, which collapses the whole file to unestablished: the skill's fallback
    triage reads that as the ENVIRONMENTAL class, distinct from an argument-validation
    breadcrumb about a value the caller just supplied.
    """
    if 'findings' not in rnd:
        return
    ledger = rnd.get('findings')
    if not isinstance(ledger, list):
        raise StateError(f'round {num} findings ledger {ledger!r} is not a list')
    av = rnd.get('adjudicated_verdict')
    umr = rnd.get('unresolved_must_revise')
    if av != 'REVISE' or not isinstance(umr, int) or isinstance(umr, bool):
        raise StateError(f'round {num} carries a findings ledger but is not adjudicated '
                         f'REVISE with a settled unresolved count')
    mrc = rnd.get('must_revise_count')
    if len(ledger) != mrc:
        raise StateError(f'round {num} findings ledger holds {len(ledger)} entries but '
                         f'must_revise_count is {mrc!r}')
    revision_ordinals = set()
    for rev in doc.get('revisions') or []:
        if isinstance(rev, dict) and isinstance(rev.get('ordinal'), int):
            revision_ordinals.add(rev['ordinal'])
    file_rounds = {r.get('round') for r in doc.get('rounds') or []
                   if isinstance(r, dict) and r.get('adjudicated_verdict') == 'FILE'}
    ingested_unresolved = 0
    for pos, entry in enumerate(ledger, start=1):
        if not isinstance(entry, dict):
            raise StateError(f'round {num} findings entry {pos} is not an object')
        if entry.get('id') != pos:
            raise StateError(f'round {num} findings ids are not the sequence 1..K: '
                             f'position {pos} holds id {entry.get("id")!r}')
        summary = entry.get('summary')
        if not isinstance(summary, str) or not summary.strip():
            raise StateError(f'round {num} findings entry {pos} summary {summary!r} is '
                             f'not a non-empty string')
        splitter = _record_splitting_char(summary)
        if splitter is not None:
            raise StateError(f'round {num} findings entry {pos} summary contains the '
                             f'record-splitting character {splitter!r}')
        forged = _forged_protocol_token(summary)
        if forged is not None:
            raise StateError(f'round {num} findings entry {pos} summary contains the '
                             f'protocol token {forged + "="!r}')
        status = entry.get('status')
        if status not in _LEDGER_STATUSES:
            raise StateError(f'round {num} findings entry {pos} names a status outside '
                             f'the canonical set: {status!r}')
        # issue #889: the optional quoted-draft-line coordinate. Absent is legal (a
        # finding the auditor did not anchor to a draft line); present-but-wrong-shape
        # is corrupt, the same absent-legal / present-validated pattern the other
        # per-finding fields follow.
        qdl = entry.get('quoted_draft_line')
        if qdl is not None and (not isinstance(qdl, int) or isinstance(qdl, bool)
                                or qdl < 1):
            raise StateError(f'round {num} findings entry {pos} quoted_draft_line '
                             f'{qdl!r} is not a positive integer')
        ingested = entry.get('ingested_status')
        if ingested not in ('unresolved', 'resolved'):
            raise StateError(f'round {num} findings entry {pos} ingested_status '
                             f'{ingested!r} is outside the ingestion set')
        if ingested == 'unresolved':
            ingested_unresolved += 1
        # The ingestion provenance is what excuses a `resolved` entry from naming a revision
        # ordinal, so it must be legal ON THIS ENTRY — the write path emits it only alongside
        # an ingested-resolved status, and `_clear_settling` pops it on every later change.
        # Uncoupled, a hand-forged provenance on an ingested-UNRESOLVED entry passes every
        # other arm and drops the finding out of the effective count, converging the run on a
        # finding that was never fixed.
        prov = entry.get('ingest_provenance')
        if prov is not None and (prov != _LEDGER_INGESTED_RESOLVED or ingested != 'resolved'):
            raise StateError(f'round {num} findings entry {pos} carries ingest provenance '
                             f'{prov!r} but was ingested {ingested!r}')
        # Read-boundary mirror of `_clear_settling`'s writer set. It re-enforces the FULL
        # set of keys that helper clears, keyed on the status, rather than only the keys
        # a resolved/invalidated entry happens to read back: a partial check leaves a
        # reader/writer asymmetry where a residual `invalidation_reason` (or an
        # `ingest_provenance` a reopen should have popped) survives load on a status the
        # writer never emits it for. Coupled site — a key added to `_clear_settling`
        # belongs in `_LEGAL_SETTLING_KEYS` in the same change.
        residual = sorted(k for k in _SETTLING_KEYS
                          if k in entry and k not in _LEGAL_SETTLING_KEYS[status])
        if residual:
            raise StateError(f'round {num} findings entry {pos} is {status} but retains '
                             f'the settling provenance key {residual[0]!r}')
        if status == 'resolved':
            # `_LEGAL_SETTLING_KEYS` is a MEMBERSHIP test, so it cannot express that the
            # two resolved-provenance keys are mutually exclusive. They are: the writer
            # pops `ingest_provenance` (via `_clear_settling`) before setting
            # `resolution_ordinal`, so an entry carrying both is writer-unreachable — but
            # representable by hand, and on such an entry the ingest short-circuit below
            # would skip the recorded-revision check entirely (PR #612 review). Refuse the
            # combination rather than silently disabling the check it bypasses.
            if ('ingest_provenance' in entry and 'resolution_ordinal' in entry):
                raise StateError(f'round {num} findings entry {pos} is resolved but '
                                 f'carries both settling-provenance keys '
                                 f'(ingest_provenance and resolution_ordinal); they are '
                                 f'mutually exclusive by construction')
            if entry.get('ingest_provenance') != _LEDGER_INGESTED_RESOLVED:
                ordinal = entry.get('resolution_ordinal')
                if ordinal not in revision_ordinals:
                    raise StateError(
                        f'round {num} findings entry {pos} is resolved but its '
                        f'resolution ordinal {ordinal!r} names no recorded revision')
        if status == 'invalidated':
            reason = entry.get('invalidation_reason')
            if not isinstance(reason, str) or not reason.strip():
                raise StateError(f'round {num} findings entry {pos} is invalidated but '
                                 f'carries no non-empty reason')
            if _record_splitting_char(reason) is not None:
                raise StateError(f'round {num} findings entry {pos} invalidation reason '
                                 f'contains a record-splitting character')
            if _forged_protocol_token(reason) is not None:
                raise StateError(f'round {num} findings entry {pos} invalidation reason '
                                 f'contains a protocol token')
            prov = entry.get('invalidation_provenance')
            if prov != _PRE_REVISION and prov not in revision_ordinals:
                raise StateError(f'round {num} findings entry {pos} invalidation '
                                 f'provenance {prov!r} names no recorded revision')
        if status == 'superseded' and entry.get('supersession_round') not in file_rounds:
            raise StateError(f'round {num} findings entry {pos} is superseded but its '
                             f'provenance {entry.get("supersession_round")!r} names no '
                             f'FILE-adjudicated round')
        reopen = entry.get('reopen_provenance')
        if reopen is not None and reopen != _PRE_REVISION and (
                reopen not in revision_ordinals):
            raise StateError(f'round {num} findings entry {pos} reopen provenance '
                             f'{reopen!r} names no recorded revision')
    if ingested_unresolved != umr:
        raise StateError(f'round {num} findings ledger ingested {ingested_unresolved} '
                         f'unresolved entries but unresolved_must_revise is {umr}')


__all__ = [
    "SCHEMA_VERSION",
    "TRANSITIONS",
    "_ADJUDICATED_VERDICTS",
    "_ADJUDICATION_RECORD_CLASSES",
    "_ADJUDICATION_RENDER_STATES",
    "_ALL_REASONS",
    "_ARMS",
    "_ATTESTATIONS",
    "_CALIBRATION_BACKINGS",
    "_CALLER_SUPPLIED_FLAGS",
    "_CLAIM_VERDICTS",
    "_CLASSIFICATIONS",
    "_COVERAGE_ANCHORED",
    "_COVERAGE_ANCHOR_MAX",
    "_COVERAGE_BACKINGS",
    "_COVERAGE_BACKING_OUTCOMES",
    "_COVERAGE_OUTCOMES",
    "_COVERAGE_RENDERS",
    "_DEGRADED_REASONS",
    "_DISCOVERY_FIRST_ROUND_REASON",
    "_DISPATCH_REGENERATION",
    "_DRAFT_TIERS",
    "_ELIGIBILITY_REASONS",
    "_EMBED_MARKER_TEXT",
    "_EMBED_MARKER_TOKENS",
    "_EVENTS",
    "_EVIDENCE_FIELDS",
    "_EVIDENCE_MAX_CHARS",
    "_EVIDENCE_OPTIONAL",
    "_EVIDENCE_REQUIRED",
    "_EVIDENCE_TRUNCATION_MARK",
    "_FINAL_BYTE_COVERAGE",
    "_FINAL_BYTE_GRANT_CAP",
    "_FINAL_BYTE_PASS_CAP",
    "_FINAL_BYTE_REFUNDS_KEY",
    "_GROUNDS",
    "_IAS_ACQUIRE_WINDOW_ENV",
    "_IAS_STALE_AFTER_ENV",
    "_IMPACT_BEARING_CLASSES",
    "_IMPACT_CLASSES",
    "_IMPACT_OPTIONAL",
    "_LEDGER_INGESTED_RESOLVED",
    "_LEDGER_PREFIXES",
    "_LEDGER_STATUSES",
    "_LEGAL_SETTLING_KEYS",
    "_MAX_AUTOMATIC_REAUDITS",
    "_MAX_CONFIRMING_ROUNDS",
    "_MULTILINE_READBACKS",
    "_NEXT_ACTIONS",
    "_NEXT_CALL_EXCLUDED",
    "_NEXT_CALL_REFUSALS",
    "_NEXT_CALL_UNESTABLISHED_RE",
    "_OVERRIDE_KINDS",
    "_OVERRIDE_SURFACES",
    "_PRE_REVISION",
    "_PROTOCOL_TOKENS",
    "_REQUIRED_TOP",
    "_RESULTS",
    "_ROUND_BUDGETS",
    "_ROUND_DEFAULTED",
    "_ROUND_IS_CALLER_INTENT",
    "_ROUND_KINDS",
    "_ROUND_KIND_REASONS",
    "_ROUND_OUTCOMES",
    "_SENTINEL_MAX_BYTES",
    "_SENTINEL_OWNER_HEX",
    "_SETTLING_KEYS",
    "_STATE_OWNER_PLACEHOLDER",
    "_STEERING_REASON_STATE",
    "_STEERING_STATES",
    "_STEERING_SUMMARY",
    "_STEERING_SUMMARY_REASONS",
    "_T",
    "_TRANSITION_REASONS",
    "_UNESTABLISHED",
    "_USER_ROUND_CAP",
    "_VERDICTS",
    "_VERDICT_BEARING_OUTCOMES",
    "StateError",
    "_DigestError",
    "_StateSection",
    "_assert_transition_tokens",
    "_bound_evidence",
    "_fail",
    "_forged_protocol_token",
    "_host_abs_path",
    "_is_bound_path",
    "_observed_divergent",
    "_parse_sentinel_body",
    "_positive_env_float",
    "_read_sentinel_body",
    "_read_sentinel_pid",
    "_record_splitting_char",
    "_replace_with_retry",
    "_repo_root",
    "_require",
    "_row",
    "_run",
    "_validate_finding_evidence",
    "_validate_ledger",
    "evidence_completeness",
    "evidence_conflicts",
    "hash_bytes",
    "hash_file",
    "split_body",
    "state_path",
]

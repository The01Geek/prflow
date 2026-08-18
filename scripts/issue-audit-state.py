#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""State owner for the `/devflow:create-issue` fresh-context audit lifecycle.

The audit lifecycle — rounds, verdicts, revisions, bounded retries, user-chosen
rounds, overrides and presentation eligibility — used to live as procedural prose
in `skills/create-issue/SKILL.md`, re-derived by an LLM on every turn. Deterministic
transition logic does not belong on an instruction-following surface: this module
owns it, and the skill records events through it and obeys its answers (issue #546).

WHAT THIS OWNS vs. WHAT THE SKILL KEEPS. This module owns transition legality,
round numbering, budget/retry accounting, arm routing, digest computation and
comparison, sentinel generation and comparison, T1/T2 evaluation, override records,
presentation eligibility and the audit-summary field set. The skill keeps the audit
*reasoning* — the audit-prompt template, dimension checklist, information diet,
out-of-bounds lists, extension forwarding — plus the subagent dispatch, the
`VERDICT:` token parse (semantic extraction is LLM work; this module then validates
the token fail-closed against its closed set), the draft-file writes, and every user
interaction. This module never posts an issue.

TWO-CLASS CLI CONTRACT (the skill branches on exactly this):
  * Query subcommands ALWAYS exit 0 once their arguments parse (an argparse usage
    error — a missing required flag or an unknown one — exits 2 before the query logic
    runs) and answer on stdout with a decided single
    answer line — fail-closed answers included — except for the multi-line read-back
    queries `query-findings`, `query-finding-evidence`,
    `query-coverage`, and `query-adjudication-records`, which each print one decided line
    per record (an empty store prints the single line `findings=none` /
    `evidence=none` / `records=none`), and the composite `query-boundary`, which prints
    one decided line per boundary component. Since issue #795 most subcommands print a
    SECOND and final line, `next_call=` (see `_resolve_next_call`); the decided answer
    line above is unchanged and stays FIRST, and `_NEXT_CALL_EXCLUDED` names the
    subcommands that print no such line. A crashed read is never
    presented as a value. Queries are strictly READ-ONLY: the tool-unavailability fallback depends
    on a mutation-persistence failure still leaving the queries answering, so no
    query may write. This is why the eligibility token is *derived* on demand rather
    than persisted at issue time.
  * Mutation subcommands exit non-zero with a specific named stderr breadcrumb, for
    an illegal transition and for an unpersistable state alike.
  * `emit-body` is neither: it is a gated emitter. It exits 0 with the audited body
    bytes when eligibility grounds them, and non-zero with EMPTY stdout otherwise —
    so on the file-identity ground a caller that ignores the exit code cannot post an
    unaudited body. A file-arm override is digest-bound too (`record-override` requires
    the draft there), so that ground byte-binds what it emits exactly as file-identity
    does. On the event-ordering ground, and on an override recorded over an embed/inline
    epoch, the gate refuses bytes a recorded revision has staled but cannot byte-bind
    what it emits (those grounds record no trustworthy digest, because no trustworthy
    canonical file exists to record one from — the disclosed weaker identity); the
    post-hoc creation attestation is the detection surface for that residual.

WINDOWS-SAFETY (#275/#295): this module never executes a `.sh` helper ([WinError 193])
and reads no config file. Its only subprocess is native `git`, and its state file is
anchored to the git repo root (falling back to the cwd) — deliberately NOT to the main
worktree root the draft file uses via `resolve-main-root.sh`. That divergence is
load-bearing and must not be unified: main-root anchoring would share one record across
concurrent worktree runs, letting a foreign delete-first wipe this run's state.
"""

import argparse
import functools
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
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
#     `skills/create-issue/references/step-3-6-audit.md`).
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
    # 5. A stdin-payload flag.
    '--ledger-stdin', '--coverage-stdin', '--stdin-digest',
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

# The two statuses a `--ledger-stdin` line may ingest as. The line prefix IS the status
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
    'coverage', 'coverage_backing', 'coverage_reason', 'coverage_render',
    'degraded', 'digest', 'dispatch_regeneration', 'effective_unresolved', 'eligible',
    'epoch_round', 'evidence', 'finding', 'findings', 'findings_count', 'frozen', 'ground',
    'id', 'identity', 'instructions_digest',
    'invalid', 'invalidated', 'iterate', 'key', 'kind', 'latest_revision_landed',
    'locator', 'marker', 'markers', 'missing',
    'must_revise', 'non_bound_root', 'nonce', 'observed', 'ordinal', 'outcome', 'reason',
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
# `_MAX_AUTOMATIC_REAUDITS` is DECIDED ZERO by issue #1751: no audit round the skill did
# not elect ever opens, so the automatic re-audit is abolished rather than merely capped.
# Its readers are `cmd_record_dispatch`'s spend predicate — where `used < 0` is never true,
# so the derived automatic spend is inert without being removed — and `next_action`, whose
# REVISE arm now always falls through to `revise-then-evaluate-offer` (the automatic
# `revise-and-reaudit` token is thereby unreachable, which is correct: it named the very
# automatic behaviour this change abolishes). Zeroing it is the strongest form of the
# documented principle that the user, not the skill, spends the tokens: issue #827 (which
# proposed RAISING it, closed not-planned) and issue #1751 (which zeroed it) both rest on
# that principle. The confirming round #793 introduces is funded from
# `_MAX_CONFIRMING_ROUNDS` below and is untouched here.
_MAX_AUTOMATIC_REAUDITS = 0
_USER_ROUND_CAP = 3
# issue #793: the confirming whole-draft round that follows an all-`addressed` `targeted`
# round draws on its OWN counter, never the shared automatic pool. That separation is
# forced, not stylistic: the automatic pool is a single shared budget, and walking it with
# the shipped ceiling of one shows round 2 funded off round 1's `REVISE` and driving the
# counter to its ceiling — so round 3 is ALREADY refused. A confirming round after a clean
# scoped round therefore has no automatic funding available at any position, not merely at
# a second revision cycle. One is enough: the confirming round is whole-draft evidence, so
# a run needs at most one per scoped round that came back clean.
#
# Issue #1751 deliberately leaves this at one, NOT zero. The confirming round completes the
# evidence for a scoped round the user already elected, so it is user-elected work being
# finished, never the skill spending a round on its own initiative — the thing #1751
# abolishes. It is also load-bearing: a clean scoped round never grounds the eligibility
# scan (which skips `targeted` rounds), so without it a converged run would clear approval
# only through the file-anyway election. A run that elects nothing has no scoped round, so
# this counter never spends there.
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
        cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
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
    """`.prflow/tmp/issue-audit-state-<slug>.json`, anchored to the repo/worktree root.

    Deliberately NOT the main-worktree root the draft file uses: sharing one record
    across concurrent worktree runs would let a foreign cold-start wipe this run's state.
    """
    # The slug keys a filesystem path (guard-class 2): an escaping shape would read,
    # write, and — worst — cold-start-DELETE outside .prflow/tmp. Fail closed.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', slug or ''):
        raise StateError(f'slug {slug!r} is not a safe path segment '
                         f'([A-Za-z0-9][A-Za-z0-9._-]*)')
    base = root if root is not None else (_repo_root() or Path.cwd())
    return Path(base) / '.prflow' / 'tmp' / f'issue-audit-state-{slug}.json'


def _is_bound_path(p):
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
    return (isinstance(p, str) and bool(p) and os.path.isabs(p)
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
        `cmd_record_adjudication` accepts WITHOUT a ledger (the `--ledger-stdin`
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
    that root joined with the fixed `.prflow/tmp/issue-draft-<slug>.md` subpath — the
    same path the skill writes and displays. The digest / eligibility / body-emitting
    readers resolve THIS from the recorded binding so a compacted context that hands a
    drifted `--draft-file` cannot redirect them; they fall back to the caller-supplied
    `--draft-file` only on an unbound run.
    """
    root = _bound_path(state)
    if root is None:
        return None
    return str(Path(root) / '.prflow' / 'tmp' / f'issue-draft-{slug}.md')


def latest_revision_landed(state):
    """True when the latest recorded revision's bytes have landed at the bound path.

    Vacuously true when no revision is recorded (nothing is unlanded). Otherwise the
    latest revision counts as landed once a **subsequent** recorded landed write at the
    bound path (a round-initiating file-arm dispatch record qualifies) carries a digest
    equal to that revision's recorded stdin digest — the clearing predicate that lets a
    recovered run re-enter the full file-arm contract (issue #562).

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
        fails closed to `not landed`, the conservative presentation choice.
    """
    revs = state['revisions']
    if not revs:
        return True
    latest = revs[-1]
    # The latest revision's ordinal is len(revs) (the 1..N chain). A recorded overwrite
    # failure for it means it never landed.
    if len(revs) in (state.get('write_failures') or []):
        return False
    want = latest.get('stdin_digest')
    if not want:
        return False
    after = latest.get('after_round', 0)
    for rnd in state['rounds']:
        if rnd['round'] <= after:
            continue  # only a write recorded AFTER the revision proves it landed
        for att in rnd['attempts']:
            if att['arm'] == 'file' and att.get('digest') == want:
                return True
    return False


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


def evaluate_final_byte_trigger(state, current_digest=None, digest_failed=False):
    """Whether the final-byte exact-byte offer holds (issue #792).

    Holds if and only if the reported coverage is `uncovered` AND the dedicated slot is
    unspent for the current canonical digest — never on `unestablished` (where an
    accepted round could not change the answer, so the offer would fund nothing and
    leave the run with no next action), never on `covered`.

    Answered on its own `query-final-byte`, deliberately NOT appended to
    `query-triggers`: that query's Step 3.6 -> Step 4 boundary consumer applies
    "While ANY holds, offer one more audit round" at the PRE-PRESENTATION pause, where
    the bytes are not yet final — so a fifth field there would fire the pass at the wrong
    moment, and its answer shape is fixed by whole-line comparands besides.
    """
    fb = evaluate_final_byte_coverage(state, current_digest, digest_failed=digest_failed)
    holds = (fb['coverage'] == 'uncovered'
             and final_byte_slot_unspent(state, current_digest))
    return {'holds': holds, 'coverage': fb['coverage'], 'reason': fb['reason']}


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
    material = f'{nonce}:{ground}:{key}'.encode('utf-8')
    return 'eat_' + hashlib.sha256(material).hexdigest()[:16]


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
        # canonical digest was supplied; a bound one only when its digest still matches.
        now = revision_ordinal(state)
        for ov in reversed(state['overrides']):
            if ov.get('kind') != 'user-decline':
                continue
            if ov.get('recorded_at_ordinal') != now:
                continue
            want = ov.get('draft_digest')
            if want is None:
                if current_digest is not None:
                    continue
            elif want != current_digest:
                continue
            return ov
        return None
    file_arm_epoch = epoch['attempts'][-1]['arm'] == 'file'
    now = revision_ordinal(state)
    for ov in reversed(state['overrides']):
        if ov.get('recorded_at_ordinal') != now:
            continue
        want = ov.get('draft_digest')
        if want is None:
            if file_arm_epoch:
                continue
        elif want != current_digest:
            continue
        return ov
    return None


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
            end = i if i >= start else start   # the line before this heading (1-based)
            yield _key(heading), start, end, body
            heading, body = lines[i].strip(), []
            start = i + 1
        else:
            body.append(lines[i])
    end = n if n >= start else start
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

    Returns the two-element ordered-integer list `create-issue-context-eval.py` accepts, or
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


def _summary(**fields):
    missing = [k for k in _SUMMARY_FIELDS if k not in fields]
    unknown = [k for k in fields if k not in _SUMMARY_FIELDS]
    _require(not missing and not unknown,
             f'issue-audit-state: the audit-summary field set is fixed by _SUMMARY_FIELDS; '
             f'this branch omits {missing!r} and adds {unknown!r}. Every summary_fields '
             f'branch must answer with exactly the same fields, or the query surface that '
             f'renders them raises KeyError on the branch that forgot one.')
    return {k: fields[k] for k in _SUMMARY_FIELDS}


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
                        scoped_round=None,
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
    # Cumulative across every round this run: "how many things did the auditors
    # collectively flag", not merely the last round's tally.
    counts = [r['findings_count'] for r in done if r.get('findings_count') is not None]
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
        findings_count=sum(counts) if counts else None,
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
        # (`<bound-root>/.prflow/tmp/issue-draft-<slug>.md`, via _bound_draft_file). A
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
        # defense in depth, not a description of the shipped skill: create-issue substitutes an
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
               # `create-issue-context-eval.py`'s `_scope_draft_span` accepts. Frozen here
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
        # The remedy names the file-arm object id specifically (the create-issue dispatch
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
        if args.findings_count is not None:
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
    # ── The per-finding ledger (issue #603 AC1/AC20) ──────────────────────────────
    # A REVISE adjudication with a SETTLED count records one ledger entry per must-revise
    # finding. The flag gate mirrors record-revision's `--stdin-digest`: the tool never
    # performs a BARE stdin read, so a legacy caller that pipes nothing can never block.
    # Recording is not skippable on that shape — its absence is a refusal — which is the
    # property that makes the run-wide aggregate and the reconciliation discipline total
    # over post-change rounds. A FILE verdict and a `REVISE … unestablished` adjudication
    # take no flag, read no stdin, and record no ledger: their call shapes stay
    # byte-compatible with the pre-#603 CLI.
    ledger_shape = args.verdict == 'REVISE' and isinstance(unresolved, int)
    ledger = None
    if getattr(args, 'ledger_stdin', False):
        if not ledger_shape:
            _fail('record-adjudication',
                  '--ledger-stdin is only accepted on a REVISE adjudication with a '
                  'settled unresolved count (ledger-not-applicable); a FILE verdict and '
                  f'a REVISE + {_UNESTABLISHED!r} adjudication record no ledger')
        ledger = _ingest_ledger(args, args.must_revise, unresolved)
    elif ledger_shape:
        _fail('record-adjudication',
              f'a REVISE adjudication with a settled unresolved count requires '
              f'--ledger-stdin carrying {args.must_revise} status-prefixed finding '
              f'summaries (ledger-required); the ledger is the durable identity record '
              f'the post-close resolution channels name entries from')
    # ── Per-finding advisory/invalid records (issue #743) ──────────────────────────
    # The deterministic recording floor: a non-zero --advisory/--invalid count REQUIRES a
    # matching per-finding records file (like --ledger-stdin's ledger-required floor), so the
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


def _ingest_ledger(args, must_revise, unresolved):
    """Read `--ledger-stdin` and build the round's ledger, or fail closed.

    The transport is deliberately line-oriented text, not a structured payload: the
    skill's fence pipes the lines through a QUOTED-delimiter heredoc (`<<'LEDGER-EOF'`),
    so the shell never expands the `$(…)`, backticks, and quotes that auditor-derived
    summaries routinely contain. A summary line byte-equal to the delimiter truncates the
    stream, which is caught downstream (typically by the `ledger-line-count` refusal below,
    though a truncation leaving the count intact trips a different arm); the decided
    recovery for that and for a vocabulary refusal is the same — reword the summary and
    re-issue the call.

    The byte read and its two fail-closed checks mirror record-revision's — a closed fd
    (CPython sets `sys.stdin` to None, so an attribute access would otherwise leak a raw
    traceback) and a read error. The undecodable-payload and empty-payload arms are this
    command's own: record-revision hashes the bytes and never decodes them, so it has no
    decode step to mirror.
    """
    lines = _read_stdin_lines(args, 'record-adjudication', 'finding ledger', 'ledger')
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
    an integer no reader can re-examine. Deliberately a FILE, not stdin: record-adjudication
    already reads stdin for `--ledger-stdin`, and a process has one stdin — the skill authors
    the JSON with the Write tool (no shell quoting) exactly as it authors a `--reflection-file`
    payload. Each record's orchestrator-authored fields (`summary`, `rationale`, `impact_class`,
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
    for `valid-N/A`). Mirrors `_ingest_ledger`'s byte-read + fail-closed decode/empty arms
    and its quoted-heredoc transport, so auditor-derived anchor text never traverses shell
    quoting. An `exercised`/`valid-N/A` line whose anchor FAILS the text-only floor is
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
    except Exception as exc:  # noqa: BLE001 - a module body may raise anything; every
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
    except Exception as exc:  # noqa: BLE001 - same decided arm as the render below: any
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
    except Exception as exc:  # noqa: BLE001 - the generator's own RenderError type is
        # not importable by name here without coupling to its module identity; every
        # failure lands on the same fail-closed `regeneration-failed` arm regardless of
        # type, so the broad catch is the DECIDED behavior rather than a swallowed error
        # (it re-raises as _DigestError, carrying the specific cause).
        raise _DigestError(f'the dispatch-instruction generator failed: {exc}') from exc
    return hash_bytes(rendered)


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


def cmd_record_revision(args):
    doc = _load_for_mutation('record-revision', args.slug, args.nonce)
    # issue #1751 zero-round arm: a run whose user declined every audit offer has no round
    # but can still revise its draft in the Step 4 iterate loop — the revision bumps the
    # ordinal, invalidating the recorded decline exactly as it invalidates a decline
    # recorded after a round. Without it the iterate loop deadlocks and a decline can never
    # be invalidated by later bytes. On a zero-round state there is no file-arm substrate to
    # bind, so the #705 guarantee below does not apply, and the only plausible --after-round
    # value is 0 (floor and ceiling both 0); the shared tail records the revision.
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
    `.prflow/tmp/issue-draft-<slug>.md` onto it — see `_bound_draft_file`), its tier
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
            f'latest_revision_landed={_yn(latest_revision_landed(state))}')


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
        # A zero-round user-decline binds to the canonical draft's digest where one was
        # supplied (--draft-file) and records unbound where none exists, mirroring the
        # arm-scoped binding the file-arm epoch case applies below. There is no epoch to
        # dereference, so the file-arm bind check below is skipped for this arm.
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
    if not args.draft_file:
        _fail('record-creation-epoch',
              'a decline-bound creation epoch must recompute the body-only digest from '
              'the canonical draft: pass --draft-file')
    try:
        raw = Path(args.draft_file).read_bytes()
        body_only_digest = hash_bytes(split_body(raw))
    except (OSError, _DigestError) as exc:
        _fail('record-creation-epoch',
              f'could not hash the draft file to bind the creation epoch: {exc}')
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
        _fail('record-creation-epoch', f'no round {args.round} is recorded to bind '
                                       'creation to')
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
        try:
            raw = Path(args.draft_file).read_bytes()
            body_only_digest = hash_bytes(split_body(raw))
        except (OSError, _DigestError) as exc:
            _fail('record-creation-epoch',
                  f'could not hash the draft file to bind the creation epoch: {exc}')
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


def cmd_record_finding_evidence(args):
    """Record one finding's reproducible evidence on the dedicated per-finding channel.

    Deliberately NOT `record-adjudication --ledger-stdin`: that transport carries a
    one-line summary and refuses newlines and `<field>=` tokens by contract, so multi-line
    observed output cannot ride on it. This channel is keyed by `<round>:<finding-id>`, caps
    each field, and stores the text VERBATIM as data — the print boundary, not a refusal, is
    where record-splitting bytes are neutralized. Instruction-shaped text is never
    neutralized and never needs to be: it is stored and printed as data, never executed.
    """
    prefix = 'record-finding-evidence'
    doc = _load_for_mutation(prefix, args.slug, args.nonce)
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
    entry = {k: _bound_evidence(v) for k, v in supplied if v is not None}
    completeness, missing = evidence_completeness(entry)
    entry['completeness'] = completeness
    key = f'{args.round}:{args.finding_id}'
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
)
_BOUNDARY_COMPONENTS = tuple(name for name, _ in _BOUNDARY_PRODUCERS)


def cmd_query_boundary(args):
    """The Step 3.6 → Step 4 boundary decision, in ONE read (issue #795).

    Carries the DECIDED FIRST LINE of the trigger, convergence, coverage, and calibration
    answers — each byte-identical to the first line its individual query prints, one per
    line, in `_BOUNDARY_COMPONENTS` order. It composes those lines from the same hoisted
    producers the individual queries call, so the two can never drift.

    The four individual queries survive and answer exactly as before; this is an additional
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
        except Exception as exc:  # noqa: BLE001 - see below
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


def _yn(v):
    return 'yes' if v else 'no'


def cmd_query_nonce(args):
    """Re-read the nonce from state — the compaction-recovery path.

    Recovery restores single-run continuity; it cannot discriminate a foreign
    same-slug run in the same cwd (the disclosed limitation).
    """
    state = _query_state(args.slug)
    print(f'nonce={state["nonce"] if state else "unknown"}')


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser():
    """Build and return the fully-registered argument parser.

    Hoisted out of `main()` (issue #795) so the registered subcommand set — a
    MACHINE-CONSUMED contract, not prose — is readable without running the CLI. The
    docstring/prose reconciliation guards compare their enumerations against
    `build_parser()._subparsers`-derived choices rather than grepping for a sentence,
    which is what makes those guards assertions about the contract rather than about
    wording.
    """
    p = argparse.ArgumentParser(
        prog='issue-audit-state.py',
        description='State owner for the /devflow:create-issue fresh-context audit '
                    'lifecycle. Queries always exit 0 once the arguments parse and '
                    'print a decided answer line; '
                    'mutations exit non-zero with a named breadcrumb. Most subcommands '
                    'print a second and final next_call= line naming the next legal '
                    'invocation; it is a generated suggestion the caller reviews, never '
                    'an instruction, and the decided answer line stays first.')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init', help='Start a run: mint a nonce (cold start deletes any '
                                    'leftover same-slug state), or re-init this run.')
    s.add_argument('slug')
    s.add_argument('--nonce', help='This run nonce; omit for a cold start.')
    s.add_argument('--force', action='store_true',
                   help='Permit a same-run re-init over recorded rounds (recorded as '
                        'reinit-forced).')
    s.set_defaults(func=cmd_init)

    s = sub.add_parser('record-dispatch', help='Record an audit round dispatch and its '
                                               'draft digest.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: dispatch-discriminator
    s.add_argument('--arm', choices=_ARMS, required=True)
    s.add_argument('--kind', choices=_ROUND_KINDS, required=True,
                   help='The round kind (issue #793), REQUIRED and tool-owned: run '
                        'query-round-kind and pass the kind it answers. Any other kind is '
                        'refused (kind-mismatch) — the caller echoes this answer, it never '
                        'decides it.')
    s.add_argument('--scope-file',
                   help='Required on a targeted round (issue #793): the absolute path of '
                        'the frozen dispatch-scope file write-dispatch-scope produced. Its '
                        'path AND content digest join the closed recorded regeneration '
                        'tuple, and its recorded basis digest is cross-checked against the '
                        'bytes this dispatch audits (scope-basis-mismatch). Refused on a '
                        'discovery round, which carries no scoped payload.')
    s.add_argument('--write-path', help='Optional at THIS CLI boundary (issue #569): the '
                   'absolute canonical-draft file path the skill observed its write land '
                   'at. When the run has a recorded draft-root binding and this is '
                   'passed, it is cross-checked against the bound canonical file '
                   '(write-path-mismatch on divergence). Omitted, or on an unbound run, '
                   'the dispatch proceeds unchanged; an empty value is refused '
                   '(write-path-empty) rather than read as an opt-out. Ignored on the '
                   'embed and inline arms. Two layers, deliberately distinct (issue '
                   '#1695): optional here for compatibility, but the live create-issue '
                   'file-arm caller is required to forward the bound canonical path — '
                   'omission bypasses only the reported-path cross-check, it is not a '
                   'sanctioned opt-out for that workflow.')
    s.add_argument('--draft-file', help='Required on the file arm; bytes on stdin '
                                        'otherwise.')
    s.add_argument('--instructions-file', help='File arm only (issue #709): the absolute '
                   'path of the canonical dispatch-instruction file the orchestrator '
                   'wrote from `render-audit-prompt.py dispatch-instructions`. Recording '
                   'it (with --instructions-draft-path) is what makes steering-absence '
                   'establishable for this round; omitting it leaves the round '
                   'unestablished, never established-clean.')
    s.add_argument('--instructions-draft-path', help='Required with --instructions-file: '
                   'the exact absolute --draft-path value the generator was invoked with. '
                   'It is a CLOSED regeneration input — record-return re-runs the '
                   'generator over it (reading the draft title from that file) to '
                   'reproduce the canonical bytes.')
    s.add_argument('--instructions-template', help='Optional closed regeneration input: '
                   'an absolute --template-file override the generator was invoked with. '
                   'Omit to record the generator default.')
    s.add_argument('--marker', choices=_EMBED_MARKER_TOKENS,
                   help='The embed-arm entry marker, when entering the embed arm.')
    s.set_defaults(func=cmd_record_dispatch)

    s = sub.add_parser('record-return', help="Record an auditor's return: verdict, "
                                             'findings and carriage evidence.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--claim-verdicts', default=None,
                   help='Targeted rounds only (issue #793): the auditor\'s per-claim block, '
                        'one "<claim-id> <addressed|not-addressed>" per line. A dispatched '
                        'claim omitted here, or returned with any value outside that closed '
                        'set, is recorded not-addressed — only a positively-returned '
                        '"addressed" counts as addressed.')
    s.add_argument('--round', type=int, required=False, default=None)
                   # issue #795: state-defaulted (_ROUND_DEFAULTED) — the state's last
                   # recorded round uniquely names it; the command's own guards still bind.
    s.add_argument('--verdict', choices=_VERDICTS,
                   help='Omit when the return carried no parseable VERDICT line.')
    s.add_argument('--findings-count', type=int)
    s.add_argument('--consumer-dimensions-appended', action='store_true')
    s.add_argument('--carriage-object-id', help='The object ID the auditor quoted '
                                                '(file arm).')
    s.add_argument('--carriage-sentinel-open')
    s.add_argument('--carriage-sentinel-close')
    s.add_argument('--instructions-object-id', help='Issue #709: the object ID the '
                   'auditor quoted for the canonical dispatch-instruction FILE it read. '
                   'Compared against the freshly-regenerated canonical digest. An absent '
                   'value is treated exactly like a mismatched one (fail closed).')
    s.add_argument('--extra-dispatch-content', choices=('yes', 'no'),
                   help='Issue #709: the auditor\'s best-effort report of whether its '
                        'dispatch message carried anything beyond the generated pointer. '
                        'Omitted reads as unreported, which does NOT establish '
                        'steering-absence. Its silence is not a proof — a positive report '
                        'withholds the clean ground, but a `no` only narrows the '
                        'un-hashable pointer channel, it does not prove it clean.')
    s.set_defaults(func=cmd_record_return)

    s = sub.add_parser('record-adjudication',
                       help='Record a completed round\'s post-adjudication actionability '
                            'payload (issue #548).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=False, default=None)
                   # issue #795: state-defaulted (_ROUND_DEFAULTED) — the state's last
                   # recorded round uniquely names it; the command's own guards still bind.
    s.add_argument('--verdict', choices=_ADJUDICATED_VERDICTS, required=True,
                   help='The adjudicated verdict (FILE or REVISE); the raw auditor token '
                        'stays recorded separately as provenance.')
    s.add_argument('--must-revise', type=int, required=True,
                   help='Count of verified must-revise findings.')
    s.add_argument('--advisory', type=int, required=True,
                   help='Count of advisory findings.')
    s.add_argument('--invalid', type=int, required=True,
                   help='Count of invalid/unverified findings.')
    s.add_argument('--unresolved-must-revise', required=True,
                   help="A non-negative integer, or the literal 'unestablished' when the "
                        'count could not be established (unknown is not zero).')
    s.add_argument('--ledger-stdin', action='store_true',
                   help='Required on a REVISE adjudication with a settled unresolved '
                        'count (#603): read exactly --must-revise status-prefixed '
                        "one-line finding summaries on stdin (each 'unresolved: <text>' "
                        "or 'resolved: <text>') and record them as the round's findings "
                        'ledger. Flag-gated like --stdin-digest, so the tool never '
                        'performs a bare stdin read. A FILE verdict and a REVISE + '
                        "'unestablished' adjudication take no flag and record no ledger.")
    s.add_argument('--advisory-records-file',
                   help='Path to a JSON array of per-finding ADVISORY records (issue #743), '
                        'required whenever --advisory > 0 (advisory-records-required) and '
                        'refused against --advisory 0. Each object carries a one-line '
                        '`summary`, a one-line `rationale`, an `impact_class` from '
                        + repr(_IMPACT_CLASSES) + ', an optional one-line `evidence`, and the '
                        "auditor's returned finding block byte-preserved up to the evidence "
                        'cap in `auditor_block` (multi-line; a longer block is truncated with '
                        'the truncation disclosed in the stored bytes). The count must match '
                        '--advisory exactly.')
    s.add_argument('--invalid-records-file',
                   help='Path to a JSON array of per-finding INVALID records (issue #743), '
                        'same shape and discipline as --advisory-records-file, required '
                        'whenever --invalid > 0 (invalid-records-required).')
    s.set_defaults(func=cmd_record_adjudication)

    s = sub.add_parser('record-adjudication-render',
                       help='Report that the round\'s advisory/invalid records were rendered '
                            'to the user before approval (issue #743, the --write-landed '
                            'reported-observation pattern).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=False, default=None)
                   # issue #795: state-defaulted (_ROUND_DEFAULTED) — the state's last
                   # recorded round uniquely names it; the command's own guards still bind.
    s.add_argument('--landed', choices=('yes', 'no'), required=True,
                   help='yes records `reported`, no records `unreported`; the tool cannot '
                        'observe chat, so this is a reported observation. An unreported '
                        'rendering is surfaced through the calibration trigger and summary.')
    s.set_defaults(func=cmd_record_adjudication_render)

    s = sub.add_parser('query-adjudication-records',
                       help='Read back a round\'s advisory/invalid per-finding records '
                            '(issue #743). Exit 0 once arguments parse; one decided line per '
                            'record, auditor fields JSON-encoded, summary trailing.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--record-class', choices=_ADJUDICATION_RECORD_CLASSES,
                   help='Restrict to one class; omit to read both.')
    s.set_defaults(func=cmd_query_adjudication_records)

    s = sub.add_parser('query-calibration',
                       help='Read the run\'s advisory-adjudication calibration backing, '
                            'render state, and never-blocking disclosure trigger (issue '
                            '#743). Exit 0 once arguments parse.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_calibration)

    s = sub.add_parser('record-coverage',
                       help="Record a completed round's per-dimension coverage outcomes "
                            '(issue #708).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=False, default=None)
                   # issue #795: state-defaulted (_ROUND_DEFAULTED) — the state's last
                   # recorded round uniquely names it; the command's own guards still bind.
    s.add_argument('--render', choices=_COVERAGE_RENDERS, required=True,
                   help="'full' when the auditor rendered every dimension on the "
                        "orchestrator's authoritative enumeration; 'degraded' when a render "
                        'divergence narrowed the auditor set (un-rendered dimensions record '
                        'unestablished; a degraded render discloses but never fires the '
                        'coverage offer).')
    s.add_argument('--expected-keys', required=True,
                   help="The AUTHORITATIVE enumerated dimension keys, comma-separated, as "
                        "printed by `render-audit-prompt.py enumerate-dimensions` (issue "
                        "#708). Coverage must be TOTAL over this set: an enumerated key "
                        "the auditor returned no line for is synthesized as unestablished "
                        "(unknown is not zero), and a returned key outside the set is "
                        "refused. Without it a truncated return would derive `backed` "
                        "vacuously — `all()` over a short list is trivially true.")
    s.add_argument('--coverage-stdin', action='store_true', required=True,
                   help='Read one line per required dimension on stdin: '
                        '"<key> <outcome> [anchor]", outcome in '
                        + repr(_COVERAGE_OUTCOMES) + '. An exercised/valid-N/A anchor '
                        'failing the text-only floor is downgraded to unestablished.')
    s.set_defaults(func=cmd_record_coverage)

    s = sub.add_parser('record-revision', help='Record that the draft was revised.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--after-round', type=int, required=True)
    s.add_argument('--stdin-digest', action='store_true',
                   help='Read the revised bytes on stdin and record their digest (#562); '
                        'used by the post-revision write-failure closure. Omit to record a '
                        'revision with no byte binding (a legacy/embed-epoch revision).')
    s.set_defaults(func=cmd_record_revision)

    s = sub.add_parser('record-resolution',
                       help='Mark named ledger entries resolved against a recorded '
                            'revision (#603).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True,  # issue #795 retained: per-round-id-selector
                   help='Any ledgered round up to the latest completed round; '
                        'cross-round resolution lets a late fix clear the round that '
                        'found the defect.')
    s.add_argument('--revision-ordinal', type=int, required=True,
                   help='The recorded revision ordinal that landed the fix.')
    s.add_argument('--resolved-ids', required=True,
                   help='Comma-separated ledger entry ids the per-finding verification '
                        'confirmed fixed.')
    s.set_defaults(func=cmd_record_resolution)

    s = sub.add_parser('record-reopen',
                       help='Mark named resolved ledger entries unresolved again (#603).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--ids', required=True,
                   help='Comma-separated ledger entry ids that regressed.')
    s.set_defaults(func=cmd_record_reopen)

    s = sub.add_parser('record-invalidate',
                       help='Retire named ledger entries as misclassified, with a '
                            'mandatory reason (#603).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--ids', required=True,
                   help='Comma-separated ledger entry ids adjudicated must-revise in '
                        'error.')
    s.add_argument('--reason', required=True,
                   help='One line naming why the finding was misclassified; refused when '
                        'empty, when it carries a newline or carriage return, or when it '
                        'carries a protocol `<field>=` token.')
    s.set_defaults(func=cmd_record_invalidate)

    s = sub.add_parser('query-round-kind',
                       help='Answer the kind the next round must take (#793), with the '
                            'reason token that selected it, the delta state and the '
                            'enumerated claim ids. Read-only; always exits 0.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--draft-file', required=True,
                   help='The canonical draft file whose current bytes form the "after" '
                        'side of the changed-section delta.')
    s.set_defaults(func=cmd_query_round_kind)

    s = sub.add_parser('write-dispatch-scope',
                       help='Write the round\'s frozen dispatch-scope file (#793) carrying '
                            'the enumerated claims and the changed-section set, floored '
                            'against forged protocol tokens. Refused unless the tool '
                            'selects a targeted round.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--draft-file', required=True,
                   help='The canonical draft file the delta is computed against.')
    s.add_argument('--path', required=True,
                   help='The absolute path to write the dispatch-scope file at.')
    s.set_defaults(func=cmd_write_dispatch_scope)

    s = sub.add_parser('record-staged-write',
                       help='Record the RESOLVED path a stage landed at, durably (#793), so '
                            'a later turn recovers the artifact name from state rather than '
                            'from the staging turn stdout.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--path', required=True,
                   help='The RESOLVED staging artifact path stage reported (absolute).')
    s.add_argument('--digest', required=True,
                   help='The staged bytes object id stage reported. Re-derived from the '
                        'artifact and refused when it does not describe those bytes.')
    s.set_defaults(func=cmd_record_staged_write)

    s = sub.add_parser('query-staged-write',
                       help='Resolve a recorded staging artifact from state alone (#793): '
                            'with --digest the artifact recorded for those bytes, otherwise '
                            'the newest recorded one. Prints staged_write=<path>|none.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--digest',
                   help='Resolve the artifact recorded for these bytes (the revision '
                        'stdin_digest on the recovery arm). Omit for the newest recorded.')
    s.set_defaults(func=cmd_query_staged_write)

    s = sub.add_parser('record-draft-binding',
                       help='Record the tiered canonical-draft-root binding, once per run '
                            '(#562): the bound absolute path, its tier token, and the '
                            'non-bound root.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--path', required=True,
                   help='The absolute root directory under which the canonical draft '
                        '.prflow/tmp/issue-draft-<slug>.md was written (the landed root).')
    s.add_argument('--tier', help='The bound-tier token: main-root or worktree-root.')
    s.add_argument('--non-bound-root',
                   help='The divergent non-bound root, absolute, when both a '
                        'resolver-answered main root and a divergent worktree root exist; '
                        'pass empty or omit to record it absent.')
    s.set_defaults(func=cmd_record_draft_binding)

    s = sub.add_parser('record-write-failure',
                       help='Record a canonical-draft overwrite that failed to land at '
                            'the bound path (#562).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--ordinal', type=int, required=True,
                   help='The revision ordinal whose overwrite failed.')
    s.set_defaults(func=cmd_record_write_failure)

    s = sub.add_parser('record-override', help='Record an override permitting '
                                               'presentation without a clean verdict.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--kind', choices=_OVERRIDE_KINDS, required=True)
    s.add_argument('--surface', choices=_OVERRIDE_SURFACES)
    s.add_argument('--draft-file', help='Binds the override to the current draft digest '
                                        'on a file-arm epoch.')
    s.set_defaults(func=cmd_record_override)

    s = sub.add_parser('record-degraded', help='Record that a round ran the inline '
                                               'degraded audit arm.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: caller-selected-round
    s.add_argument('--reason', choices=_DEGRADED_REASONS, required=True)
    s.set_defaults(func=cmd_record_degraded)

    s = sub.add_parser('record-offer', help='Record a user-chosen-round offer outcome.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--accepted', action='store_true')
    s.set_defaults(func=cmd_record_offer)

    s = sub.add_parser('record-final-byte-offer',
                       help='Record the final-byte exact-byte offer outcome (#792). '
                            'Spends the dedicated slot for the current canonical digest '
                            'on BOTH arms; --accepted additionally funds one round '
                            'outside the user-round cap. A decline is recorded HERE, '
                            'never as a user-decline override.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--accepted', action='store_true')
    s.add_argument('--draft-file',
                   help='The canonical draft file the slot is keyed to; a recorded draft '
                        'binding wins over it.')
    s.set_defaults(func=cmd_record_final_byte_offer)

    s = sub.add_parser('record-creation-epoch', help='Bind creation to a completed round; '
                                                     'on the file arm bind the digest of '
                                                     'the bytes actually being posted.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=True)  # issue #795 retained: caller-selected-round
    s.add_argument('--draft-file', help='The canonical draft file the file-arm posting '
                                        'sources from. On a file-arm epoch it binds the '
                                        'body digest of the bytes emit-body will actually '
                                        'post, so the post-hoc attestation compares '
                                        'like-for-like even on an override filing; absent, '
                                        'or on an embed/inline epoch, the audited round '
                                        'body digest is used.')
    s.set_defaults(func=cmd_record_creation_epoch)

    s = sub.add_parser('record-creation-attestation',
                       help='Compare a fetched created-issue body against the epoch '
                            'body digest (bytes on stdin).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--attestation-unavailable', action='store_true',
                   help='The fetch failed; report unavailable, never a pass.')
    s.set_defaults(func=cmd_record_creation_attestation)

    s = sub.add_parser(
        'record-finding-evidence',
        help='Record one finding\'s reproducible evidence (locator, command, observed '
             'output, captured baseline) on the dedicated per-finding channel keyed by '
             'finding id — never the one-line `record-adjudication --ledger-stdin` summary '
             'transport, which refuses newlines and `<field>=` tokens. The text is stored '
             'verbatim as DATA and is never executed; a missing required field records the '
             'item `incomplete`, never verified.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=_nonneg_int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--finding-id', type=_nonneg_int, required=True)
    s.add_argument('--locator')
    s.add_argument('--command')
    s.add_argument('--baseline-revision')
    s.add_argument('--baseline-identity',
                   help='The content identity the auditor captured, recorded verbatim as '
                        'DATA. It is deliberately NOT cross-checked against any stored '
                        'record: the auditor cannot read the state file, so an '
                        'identity it supplies is a claim to verify, not a key to join on.')
    s.add_argument('--observed-stdin', action='store_true',
                   help='Read the observed output from stdin (multi-line is legal here).')
    s.set_defaults(func=cmd_record_finding_evidence)

    s = sub.add_parser(
        'query-finding-evidence',
        help='Read back per-finding evidence. Every field is JSON-encoded at the print '
             'boundary, so record-splitting auditor text cannot forge a line, and the '
             'decision fields (finding=, completeness=, conflict=) cannot be forged because '
             'they precede every auditor-controlled value and come from closed domains. The '
             'trailing evidence values are quoted rather than delimited, so parse this line '
             'by its JSON quoting, never by splitting on whitespace. Two items citing one '
             'locator AND running the same command, with differing '
             'observed output, are surfaced as `conflict=<ids>`, never auto-resolved; '
             'conflicts are derived over the whole round, so narrowing with --finding-id '
             'still reports a conflicting sibling.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=_nonneg_int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--finding-id', type=_nonneg_int)
    s.set_defaults(func=cmd_query_finding_evidence)

    s = sub.add_parser('emit-body', help='Emit the audited body bytes; refuses with '
                                         'empty stdout when not eligible.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--draft-file', required=True)
    s.set_defaults(func=cmd_emit_body)

    s = sub.add_parser('query-arm', help='Decide a dispatch arm from recorded facts.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--write-landed', choices=('yes', 'no'), required=True)
    s.add_argument('--draft-file', required=True)
    s.add_argument('--prior-unreadable', action='store_true')
    s.set_defaults(func=cmd_query_arm)

    s = sub.add_parser('query-next-action', help='The retry/next-action answer for a '
                                                 'round.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=int, required=False, default=None)
                   # issue #795: state-defaulted (_ROUND_DEFAULTED) — the state's last
                   # recorded round uniquely names it; the command's own guards still bind.
    s.set_defaults(func=cmd_query_next_action)

    s = sub.add_parser('query-boundary',
                       help='The Step 3.6 to Step 4 boundary decision in one read: the '
                            'decided line of the trigger, convergence, coverage and '
                            'calibration answers, one per line.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_boundary)

    s = sub.add_parser('query-triggers', help='Evaluate the T1 and T2 offer triggers.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_triggers)

    s = sub.add_parser('query-convergence',
                       help='Whether the run has converged: zero EFFECTIVE unresolved '
                            'must-revise findings, reported with the basis it rests on '
                            '(#548/#603).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_convergence)

    s = sub.add_parser('query-findings',
                       help='One line per per-finding ledger entry across all rounds '
                            '(#603); the durable reconciliation read-back.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_findings)

    s = sub.add_parser('query-coverage',
                       help="The run's coverage-backing, derived from the final accepted "
                            'clean round (#708); the durable coverage read-back.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_coverage)

    s = sub.add_parser('query-final-byte',
                       help='Whether the final-byte exact-byte offer holds (#792): the '
                            'reported coverage of the bytes that would be FILED, and '
                            'whether the dedicated slot is unspent for them. Its OWN '
                            'query, never appended to query-triggers.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--draft-file',
                   help='The canonical draft file whose digest the coverage comparison '
                        'and the slot are keyed to; a recorded draft binding wins over '
                        'it. With neither, the axis answers unestablished and the '
                        'trigger does not hold.')
    s.set_defaults(func=cmd_query_final_byte)

    s = sub.add_parser('query-eligibility', help='Presentation eligibility in approve or '
                                                 'iterate mode.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--mode', choices=('approve', 'iterate'), required=True)
    s.add_argument('--draft-file')
    s.set_defaults(func=cmd_query_eligibility)

    s = sub.add_parser('query-summary', help='The audit-summary-line fields.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--draft-file')
    s.set_defaults(func=cmd_query_summary)

    s = sub.add_parser('query-draft-binding',
                       help='Emit the recorded tiered draft-root binding (#562): bound '
                            'path, tier token, non-bound root, and the latest-revision '
                            'landed flag. Fail-closed bound=none when unbound.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_draft_binding)

    s = sub.add_parser('query-nonce', help='Re-read this run nonce from state (recovery '
                                           'after context compaction).')
    s.add_argument('slug')
    s.set_defaults(func=cmd_query_nonce)

    return p


def registered_subcommands():
    """The subcommand names the parser actually exposes (issue #795)."""
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public accessor
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return frozenset(action.choices)
    raise AssertionError('issue-audit-state: build_parser() registered no subparsers')


# ── Issue #1040: read-only predicate + hoisted stdin read ─────────────────────────
# The read-only predicate decides which subcommands skip the critical section. It is the
# existing naming rule (a name beginning `query-`) plus the non-query read surface
# already in _NEXT_CALL_EXCLUDED — it introduces no new closed set. Its complement is
# proved fail-closed against handler source by lib/test/check-audit-lifecycle-contracts.py.
_READONLY_EXTRA = frozenset(('emit-body',))


def _is_read_only(cmd):
    """True iff `cmd` acquires no sentinel (issue #1040)."""
    return cmd.startswith('query-') or cmd in _READONLY_EXTRA


def _selects_stdin(args):
    """Whether the parsed args select a stdin payload for this command (issue #1040).

    The read is hoisted to main() above the section, so this must mirror each handler's
    OWN arg-based read trigger exactly — a flag for the four flag-gated payloads, and the
    arm for record-dispatch (embed/inline draft bytes) and record-creation-attestation
    (the fetched body). The scope is larger than the four stdin flags the issue enumerated
    (record-dispatch, record-creation-attestation, and record-finding-evidence also read
    stdin), and the hoist covers all of them so no handler performs a sys.stdin read.
    """
    cmd = getattr(args, 'cmd', None)
    if cmd == 'record-dispatch':
        # The draft bytes are read from stdin on every arm EXCEPT the file arm (which reads
        # `--draft-file`). The gate is the arm, not the presence of --draft-file: an
        # embed/inline dispatch may still carry a --draft-file argument yet reads stdin.
        return getattr(args, 'arm', None) != 'file'
    if cmd == 'record-creation-attestation':
        return not getattr(args, 'attestation_unavailable', False)
    if cmd == 'record-revision':
        return bool(getattr(args, 'stdin_digest', False))
    if cmd == 'record-adjudication':
        return bool(getattr(args, 'ledger_stdin', False))
    if cmd == 'record-coverage':
        return bool(getattr(args, 'coverage_stdin', False))
    if cmd == 'record-finding-evidence':
        return bool(getattr(args, 'observed_stdin', False))
    return False


def _read_stdin_once(args):
    """Hoist the single stdin read above main()'s dispatch and the critical section (issue
    #1040), so no handler blocks on stdin inside the section and the section's duration is
    bounded by one small-document read-modify-write. Records the payload (or the fd-0-closed
    / read-error condition) on `args` for the handler to consume; reads nothing when the
    parsed args select no payload. The existing per-handler absent-stdin guard moves with
    the read (see `_stdin_bytes_or_fail`), so its behavior and breadcrumb are unchanged.
    """
    args._stdin_data = None
    args._stdin_missing = False
    args._stdin_error = None
    if not _selects_stdin(args):
        return
    if sys.stdin is None:
        args._stdin_missing = True
        return
    try:
        args._stdin_data = sys.stdin.buffer.read()
    except OSError as exc:
        args._stdin_error = exc


def _stdin_bytes_or_fail(args, command, phrase):
    """Return the hoisted stdin bytes, reproducing the guarded sites' fd-0-closed and
    read-error breadcrumbs verbatim (issue #1040). `phrase` is the exact wording each site
    used after `could not read ` (`draft bytes`, `revised bytes`, `the fetched body`, `the
    finding ledger`, `the coverage list`).
    """
    if args._stdin_missing:
        _fail(command, f'could not read {phrase} from stdin: no stdin is attached '
                       f'(fd 0 is closed)')
    if args._stdin_error is not None:
        _fail(command, f'could not read {phrase} from stdin: {args._stdin_error}')
    return args._stdin_data


def main():
    args = build_parser().parse_args()
    # Hoist stdin ABOVE the section (issue #1040): read any payload the parsed args select
    # before dispatch, so a mutating handler's stdin read never blocks inside the section.
    _read_stdin_once(args)
    if _is_read_only(args.cmd):
        # Read-only subcommands acquire no sentinel and are unaffected by one being held.
        ctx = args.func(args)
    else:
        # Wrap the single dispatch site so the handler's load_state..save_state runs under
        # exclusion. A section acquisition failure raises a cannot-persist StateError, which
        # routes through _fail exactly like every other could-not-persist breadcrumb (no new
        # mutation-exit class). __exit__ runs the ownership-checked release on every path.
        try:
            with _StateSection(args.slug):
                ctx = args.func(args)
        except StateError as exc:
            _fail(args.cmd, str(exc))
    # issue #795 — the SINGLE `next_call=` emission site. It runs after the command's own
    # function returned, so every existing decided line stays byte-identical and first, and
    # a refusal (which raises `SystemExit` out of `_fail`) never reaches here.
    if args.cmd not in _NEXT_CALL_EXCLUDED:
        try:
            _emit_next_call(args.cmd, args, ctx)
        except Exception as exc:  # noqa: BLE001 - see below
            # DELIBERATELY broad, and never a swallow. By this point the decided answer
            # line is already printed and any mutation is already persisted, so an
            # exception escaping here would exit non-zero on a call that SUCCEEDED — and
            # the whole CLI is contract-typed on that exit code: a caller reads a non-zero
            # query as the fallback's "no contract output" class and a non-zero mutation as
            # an illegal transition or an unpersistable state, so it would retry or degrade
            # over work that actually landed. `next_call=` is a generated suggestion; its
            # failure is named on stderr and the decided answer stands.
            # Emit the `unestablished` shape rather than NOTHING. The contract this
            # channel publishes is that every non-excluded subcommand's FINAL stdout line
            # is one of exactly three shapes; printing no line at all left a caller
            # parsing that final line reading whatever the command's own last decided line
            # happened to be, which is not a `next_call=` answer and carries no reason. A
            # render failure is precisely an unestablished next call, so say so on the
            # channel the caller reads, and keep the diagnosis on stderr.
            print('next_call=unestablished reason=render-failed')
            # Two DIFFERENT conditions reach this handler, and collapsing them onto one
            # message hid the worse one (issue #795 shadow review). An ordinary exception
            # is a data/environment problem: the state held something unrenderable. An
            # `AssertionError` here comes from this module's own self-checks —
            # `_checked_next_call`'s three-shape contract and `_unestablished`'s closed
            # reason vocabulary — and means the TOOL is wrong, not the input. Both must
            # still exit 0 for the reason above, so the only channel left to distinguish
            # them is the message; give the contract violation a distinctive, greppable
            # marker so it is visible in a transcript and assertable by the suite, rather
            # than reading as one more environment hiccup.
            if isinstance(exc, AssertionError):
                sys.stderr.write(
                    f'issue-audit-state.py {args.cmd}: CONTRACT VIOLATION in the next_call= '
                    f'channel — {exc}. This is a defect in issue-audit-state.py itself, not '
                    'a problem with your state or arguments; the decided answer above stands '
                    'and this call succeeded, but the suggestion channel is unsound and '
                    'should be reported.\n')
            else:
                sys.stderr.write(
                    f'issue-audit-state.py {args.cmd}: the next_call= suggestion could not be '
                    f'rendered ({type(exc).__name__}: {exc}); the decided answer above stands '
                    'and this call succeeded\n')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""State owner for the `/prflow:spec` fresh-context audit lifecycle.

The audit lifecycle — rounds, verdicts, revisions, bounded retries, user-chosen
rounds, overrides and presentation eligibility — used to live as procedural prose
in `skills/spec/SKILL.md`, re-derived by an LLM on every turn. Deterministic
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
    line above is unchanged and stays FIRST; since issue #1803 a `summary-block` line — a
    compact fixed `_SUMMARY_BLOCK_FIELDS` subset of the `query-summary` fields — prints
    between the decided answer line(s) and that final `next_call=` line, so a caller reads
    post-mutation state from the call it just made. "Line(s)": the batched
    `record-finding-evidence` form prints one decided `finding=` line per finding, and the
    block follows the LAST of them. `_NEXT_CALL_EXCLUDED` names the
    subcommands that print neither the summary-block nor the `next_call=` line. A crashed read is never
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

# The whole original import block stays here even for a module only a sibling now
# calls: in-repo consumers load THIS path and reach the standard library through
# the module namespace (`module.tempfile.mkstemp`), so a dropped name is a broken
# seam rather than a tidied import.
import argparse
import functools  # noqa: F401
import hashlib  # noqa: F401
import json  # noqa: F401
import os
import re  # noqa: F401
import secrets  # noqa: F401
import shlex  # noqa: F401
import subprocess  # noqa: F401
import sys
import tempfile  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The section bodies live in these siblings (issue #567: so that every source file
# of this helper loads in one whole-file Read). Every name they export is
# re-exported here, because in-repo consumers load THIS path with
# `spec_from_file_location` and read the names off the module object they get back.
# Import order is alphabetical for the import linter and carries no meaning: the
# four `__all__` sets are disjoint, so no name is shadowed.
from issue_audit_state_channels import *
from issue_audit_state_commands import *
from issue_audit_state_state import *
from issue_audit_state_vocab import *

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
        description=(
            'State owner for the /prflow:spec fresh-context audit lifecycle. '
            'Queries always exit 0 once the arguments parse and print a decided answer '
            'line; mutations exit non-zero with a named breadcrumb. Most subcommands then '
            'print, as their final stdout line, a next_call= line naming the next legal '
            'invocation; between the decided answer line(s) (the first of which stays first) '
            'and that final '
            'next_call= line they print a summary-block line carrying a compact fixed subset '
            'of the query-summary fields (' + ', '.join(_SUMMARY_BLOCK_FIELDS) + '), so a '
            'caller reads post-mutation state from the call it just made. The derived counts '
            'differ in scope: verdict, adjudicated_verdict, must_revise, advisory, invalid '
            'and unresolved_must_revise all describe the single round named by counts_round '
            '(the latest completed whole-draft round, with a targeted round not selected); '
            'findings_count is the sum over all completed rounds when every one carries a '
            '--findings-count tally, and none when any completed round lacks one; and '
            'effective_unresolved is run-wide. next_call= is a '
            'generated suggestion the caller reviews, never an instruction.'))
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
                   '#1695): optional here for compatibility, but the live spec '
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
    s.add_argument('--findings-count', type=int,
                   help='Required on an accepted return (issue #86): the number of findings '
                        'the auditor returned — every numbered finding plus a qualifying '
                        'Quiet Killer and every out-of-scope finding, but not the '
                        '`Quiet Killer: none` form and not the COVERAGE block. Counted at '
                        'record-return before adjudication; record-adjudication requires it '
                        'to equal must-revise + advisory + invalid, since every returned '
                        'finding lands in exactly one class.')
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
    s.add_argument('--ledger-file',
                   help='Required on a REVISE adjudication with a settled unresolved '
                        'count (#603): a path to a file (issue #200) holding exactly '
                        '--must-revise status-prefixed one-line finding summaries (each '
                        "'unresolved: <text>' or 'resolved: <text>'), recorded as the "
                        "round's findings ledger. The skill authors the file with its "
                        'file-write tool, so a worktree-isolated session has one '
                        'worktree-safe ledger location and no shell heredoc. A FILE verdict '
                        "and a REVISE + 'unestablished' adjudication take no flag and record "
                        'no ledger.')
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
                        '.prflow/tmp/spec/<slug>/issue-draft-<slug>.md was written (the landed root).')
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

    s = sub.add_parser('record-creation-epoch', help='Bind creation to a completed round, '
                                                     'or (issue #1751) to a recorded '
                                                     'zero-round user-decline when no round '
                                                     'exists; on the file arm bind the digest '
                                                     'of the bytes actually being posted.')
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
             'finding id — never the one-line `record-adjudication --ledger-file` summary '
             'transport, which refuses newlines and `<field>=` tokens. The text is stored '
             'verbatim as DATA and is never executed; a missing required field records the '
             'item `incomplete`, never verified.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.add_argument('--round', type=_nonneg_int, required=True)  # issue #795 retained: per-round-id-selector
    s.add_argument('--finding-id', type=_nonneg_int,
                   help='One finding (single form); omit with --finding-evidence-records-file.')
    s.add_argument('--finding-evidence-records-file',
                   help="issue #1803: record a WHOLE round's finding evidence from one JSON "
                        'file (array of objects, each a non-negative-int finding_id plus the '
                        'optional string locator/command/observed/baseline_revision/'
                        'baseline_identity), mirroring --advisory-records-file. Mutually '
                        'exclusive with the per-finding flags; each entry gets its own '
                        'completeness verdict.')
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

    s = sub.add_parser('emit-body', help='Emit the audited body bytes (which start after '
                                         'the draft\'s single leading `# ` title heading); '
                                         'refuses with empty stdout when not eligible.',
                       description='Emit the audited body bytes, which start after the '
                                   'draft\'s single leading `# ` title heading; refuses '
                                   'with empty stdout when not eligible.')
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
                            'decided line of the trigger, convergence, coverage, '
                            'calibration and offer answers, one per line.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_boundary)

    s = sub.add_parser('query-triggers', help='Evaluate the T1 and T2 offer triggers.')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_triggers)

    s = sub.add_parser('query-offer',
                       help='Whether the Step 4 audit-round offer is withheld because the '
                            'last completed REVISE round is unrevised or its count is '
                            'unestablished (issue #548).')
    s.add_argument('slug')
    s.add_argument('--nonce', required=True)
    s.set_defaults(func=cmd_query_offer)

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
                            'landed token. Fail-closed bound=none when unbound.',
                       description='Emit the recorded tiered draft-root binding (#562): '
                            'bound path, tier token, non-bound root, and the '
                            'latest_revision_landed token, which is one of '
                            'yes/no/unestablished (#1841). Fail-closed bound=none when '
                            'unbound.')
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
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
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
    # record-adjudication no longer selects stdin: its ledger reaches it via --ledger-file
    # (issue #200), so it performs no hoisted stdin read at all.
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


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    _force_utf8_streams()
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
        except Exception as exc:
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

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Completion-evidence validator for receiving-review completion claims (issue #550).

A thin, deterministic, semantic-FREE check. It validates that a claimed-complete
receiving-code-review pass — a direct interactive session, or the autonomous
`/devflow:review-and-fix` loop at Loop Exit — is backed by current, producer-owned
evidence, and it prints exactly one verdict line:

    completion-check: <token> — <detail>

The token is one of exactly eight, evaluated in a fixed order with the FIRST
failing class emitted (presence/parseability/binding before any value compare):

    missing-evidence -> stale-candidate -> verification-not-pass ->
    skipped-checks-present -> undischarged-findings -> non-durable-deferral ->
    unverifiable-trace -> pass

Exit code 0 accompanies `pass` and ONLY `pass`; each of the seven non-pass tokens
exits 1; an internal failure exits 2 and prints NO verdict line (a stderr
breadcrumb is expected on that arm). Unknown never collapses onto pass: an operand
that is absent/unreadable/unparseable routes to `missing-evidence` before any value
comparison, and an unestablished check always yields a named non-pass token.

What this validator DOES NOT do (semantic-exclusion, issue #550): it re-grades no
severity, re-judges no fix, re-runs no test, and evaluates no finding content
beyond the presence and binding of its disposition trace. It validates references —
existence, parseability, identity-binding, set-emptiness, and trace presence.

Invariants (mirrors scripts/workpad.py's Windows-safe native-git pattern,
issues #275/#295, and scripts/file-deferrals.py's Python gh-caller pattern):
  * python3 standard-library only. No PyYAML import.
  * Candidate identity is re-derived at validation time by CALLING the shipped
    preflight producer (scripts/reception_identity.derive_candidate_identity) —
    one derivation routine, never a second implementation of the identity format.
  * git is invoked ONLY inside that imported derivation routine (native subprocess,
    argv list, no shell). This module spawns no subprocess of its own except the
    resolved `gh` on the remote-trace arm.
  * gh is read via the DEVFLOW_GH env override (defaulting to gh) with NO probe.
  * No decisive value is derived through a non-preflight PATH tool
    (`tr`/`sed`/`wc`/`cut`/`head`).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reception_identity as ri  # noqa: E402

# gh is read only on the remote-trace arm; the Python gh-caller pattern (no probe).
GH = os.environ.get("DEVFLOW_GH") or "gh"

# The eight tokens, in evaluation order (pass is the terminal affirmative).
TOK_PASS = "pass"
TOK_MISSING = "missing-evidence"
TOK_STALE = "stale-candidate"
TOK_NOT_PASS = "verification-not-pass"
TOK_SKIPPED = "skipped-checks-present"
TOK_UNDISCHARGED = "undischarged-findings"
TOK_NON_DURABLE = "non-durable-deferral"
TOK_UNVERIFIABLE = "unverifiable-trace"

# The closed token vocabulary: the terminal affirmative `pass` first, followed by
# the seven failing classes in the documented first-failing-class evaluation order;
# ALL_TOKENS closes the set so a raise-site typo cannot ship a garbage verdict line
# (mirrors verification-flight.py's ALL_STATES / _CodedError closed-vocabulary guard).
ORDERED_TOKENS = (
    TOK_PASS,
    TOK_MISSING,
    TOK_STALE,
    TOK_NOT_PASS,
    TOK_SKIPPED,
    TOK_UNDISCHARGED,
    TOK_NON_DURABLE,
    TOK_UNVERIFIABLE,
)
ALL_TOKENS = frozenset(ORDERED_TOKENS)

# A verification record satisfies the pass check when its result is one of these.
# Two honest producers write a verification record: the #528 flight handle records
# `result: "passed"`, while the review-and-fix `verification_evidence` records
# `result: "pass"`. Any other value (including "skipped", "fail", "failed") is a
# non-pass — the "unknown is never pass" rule at the value level.
PASS_RESULT_VALUES = frozenset({"pass", "passed"})

# Skip-kind vocabulary (issue #456). Only host-capability is a benign, surfaced-
# but-not-blocking skip; blocking-gate blocks, and an ABSENT/unrecognized kind is
# treated as blocking (fail-closed).
SKIP_KIND_HOST = "host-capability"
SKIP_KIND_BLOCKING = "blocking-gate"

# The four durable deferral channels (the skill's stated order of preference).
# _check_deferrals dispatches on the individual channel constants below, so no
# local/remote partition is materialized — ALL_CHANNELS is only the membership set.
CHANNEL_LOOP_RECORD = "loop-record"
CHANNEL_CODE_COMMENT = "code-comment"
CHANNEL_PR_THREAD = "pr-thread"
CHANNEL_FOLLOW_UP = "follow-up-issue"
ALL_CHANNELS = frozenset(
    {CHANNEL_LOOP_RECORD, CHANNEL_CODE_COMMENT, CHANNEL_PR_THREAD, CHANNEL_FOLLOW_UP}
)
# A manifest may DECLARE, once at top level, the durable channel its entries carry
# when they name none individually — the shape the fix loop's own run-scoped
# deferrals manifest emits (`default_channel: "loop-record"`: the manifest record
# IS the trace, so no per-entry channel adds information). The declaration is the
# only way an entry acquires a channel it does not state, so it never widens the
# guard: a manifest that declares nothing leaves every channel-less entry
# non-durable exactly as before, and a declaration outside ALL_CHANNELS is
# discarded rather than honored (fail-closed on a corrupt or hostile literal).
KEY_DEFAULT_CHANNEL = "default_channel"


class Verdict(Exception):
    """A resolved verdict — carries the token and the detail clause.

    Raised the instant a failing class resolves, so the first-failing-class
    ordering is expressed by control flow rather than by a scoreboard the caller
    could read out of order.
    """

    def __init__(self, token: str, detail: str):
        # Closed-vocabulary guard: a mistyped token is a programming error, not a
        # verdict to ship. Caught by main()'s broad handler → exit 2, no verdict line.
        if token not in ALL_TOKENS:
            raise ValueError(f"Verdict token {token!r} is not one of {sorted(ALL_TOKENS)}")
        super().__init__(token)
        self.token = token
        self.detail = detail


def _emit(token: str, detail: str) -> int:
    """Print the single verdict line and return the process exit code."""
    sys.stdout.write(f"completion-check: {token} — {detail}\n")
    return 0 if token == TOK_PASS else 1


# ─────────────────────────────────────────────────────────────────────────────
# Best-effort JSON-object reader (the six-shape adversarial matrix, CLAUDE.md)
# ─────────────────────────────────────────────────────────────────────────────
def _read_json_object(path: Path) -> "tuple[dict | None, str | None]":
    """Read a JSON *object* artifact. Returns (obj, None) or (None, reason).

    Every degraded shape — array, scalar, valid-falsy (`false`/`0`/`""`),
    wrong-type, absent, unreadable, empty/whitespace-only, truncated/non-UTF-8 —
    yields (None, <named reason>); no shape yields a value read as a valid record.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"unreadable:{exc.__class__.__name__}"
    if not raw.strip():
        return None, "empty"
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "malformed"
    if not isinstance(obj, dict):
        # array, scalar, and the valid-falsy JSON false/0/"" all land here.
        return None, "not_object"
    return obj, None


def _require_object(path_str: "str | None", label: str) -> dict:
    """Read a REQUIRED JSON object or raise a missing-evidence Verdict.

    A None path (the operand was not supplied where the context requires one) is
    itself missing-evidence — the empty-reference-set arm.
    """
    if not path_str:
        raise Verdict(TOK_MISSING, f"{label}: reference not supplied")
    obj, reason = _read_json_object(Path(path_str))
    if obj is None:
        raise Verdict(TOK_MISSING, f"{label}: {reason} ({path_str})")
    return obj


def _require_token_binding(obj: dict, label: str, context: str) -> None:
    """A session anchor must carry a claim_context_token equal to the operand.

    A wrong-session anchor is missing evidence for THIS claim, never a silent pass
    (the planted wrong-session fixture pins this). An absent token is also a
    binding failure — a required artifact with no discriminator cannot be bound.
    """
    tok = obj.get("claim_context_token")
    if not isinstance(tok, str) or not tok:
        raise Verdict(TOK_MISSING, f"{label}: no claim-context token to bind")
    if tok != context:
        raise Verdict(
            TOK_MISSING,
            f"{label}: claim-context token does not match this claim "
            f"(anchor bound to a different session)",
        )


def _check_rebind(obj: dict, label: str) -> None:
    """Guard the #668 rebind semantics — `rebound_from == "unknown"` is undetermined.

    The reception producer re-derives the identity on every record; when the prior
    artifact could not be read it reports `rebound_from: "unknown"`, meaning the
    rebind comparison **could not be made**. Undetermined is never continuity: an
    anchor whose rebind is unknown cannot be bound with confidence, so it is
    missing-evidence (never a silent pass). A concrete `rebound_from` value (an
    actual rebind against an edited tree) is left to the verification record's
    stale-candidate check — the tree moved, so the recorded verification identity
    differs from claim time. `null` (identity unchanged) and an absent field are the
    ordinary pass-arm inputs.
    """
    rebound = obj.get("rebound_from")
    if rebound == "unknown":
        raise Verdict(
            TOK_MISSING,
            f"{label}: rebind is undetermined (`rebound_from: \"unknown\"`) — the "
            f"prior identity could not be read, so continuity cannot be established",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Candidate-identity re-derivation (single source of truth — the #668 routine)
# ─────────────────────────────────────────────────────────────────────────────
def _claim_time_identity(claim_identity: "str | None", repo_root: "str | None") -> str:
    """The claim-time candidate identity.

    Re-derived at validation time by calling the shipped preflight producer, so
    the identity format has exactly one implementation. A test/loop may pin an
    explicit value (the loop passes what it computed); any other value routes
    through the same derivation routine. Shared by every context — the loop/direct
    `_validate` and the implement `validate_implement_completion` — so the "exactly
    one implementation" invariant holds across all callers.
    """
    if claim_identity:
        return claim_identity
    try:
        return ri.derive_candidate_identity(repo_root or os.getcwd())
    except ri.IdentityError as exc:
        # A derivation that cannot complete is an internal failure of the check
        # itself, not a verdict about the claim — exit 2, no verdict line.
        raise _Internal(f"identity_derivation:{exc.reason}")


class _Internal(Exception):
    """An internal failure of the validator — exit 2, no verdict line."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Individual class checks (each raises a Verdict on the first failure it finds)
# ─────────────────────────────────────────────────────────────────────────────
def _check_stale_candidate(vrecord: dict, claim_identity: str) -> None:
    """Token 3. The verification record's recorded candidate identity must equal
    the claim-time identity (byte comparison). Only the verification record
    carries this obligation; the session anchors are opening records and predate
    the fixes by definition, so they are never staleness-checked."""
    recorded = vrecord.get("candidate_identity")
    if not isinstance(recorded, str) or not recorded:
        # The record cited as current carries no comparable identity — treat as a
        # missing operand for the currency compare, routed before value tokens.
        raise Verdict(
            TOK_MISSING,
            "verification-record: no candidate_identity to compare against claim time",
        )
    if recorded != claim_identity:
        raise Verdict(
            TOK_STALE,
            "verification evidence predates the shipped candidate "
            "(recorded identity differs from claim-time content)",
        )


def _check_verification_pass(vrecord: dict) -> None:
    """Token 4. The record's result must be its producer's pass value."""
    result = vrecord.get("result")
    if result not in PASS_RESULT_VALUES:
        raise Verdict(
            TOK_NOT_PASS,
            f"verification result is {result!r}, not a pass",
        )


def _skip_label(entry: object) -> str:
    """The display label for one skipped-check entry (shared by the blocking-check
    and the pass-detail host quote, so the `(unnamed check)` fallback lives once)."""
    name = entry.get("check") if isinstance(entry, dict) else None
    return name if isinstance(name, str) and name else "(unnamed check)"


def _check_skipped_checks(vrecord: dict) -> None:
    """Token 5. A blocking-gate skip — or a skip with no/unknown kind (fail-closed)
    — is skipped-checks-present even when the result is a pass. host-capability
    skips are quoted in the detail but do NOT flip the token."""
    skips = vrecord.get("skipped_checks")
    if not skips:
        return
    if not isinstance(skips, list):
        # A wrong-typed skip set is an unclassifiable shape — fail closed.
        raise Verdict(
            TOK_SKIPPED,
            "verification record's skipped_checks is not a list (unclassifiable)",
        )
    blocking = []
    host = []
    for entry in skips:
        kind = entry.get("kind") if isinstance(entry, dict) else None
        label = _skip_label(entry)
        if kind == SKIP_KIND_HOST:
            host.append(label)
        elif kind == SKIP_KIND_BLOCKING:
            blocking.append(label)
        else:
            # Absent or unrecognized kind — treated as blocking (fail-closed),
            # naming the classification remedy.
            blocking.append(f"{label} [unclassified kind {kind!r}; classify it]")
    if blocking:
        detail = "blocking skips present: " + ", ".join(blocking)
        if host:
            detail += "; host-capability skips (surfaced): " + ", ".join(host)
        raise Verdict(TOK_SKIPPED, detail)
    # Only host-capability skips: surfaced, never laundered, token unaffected.
    # (The pass detail below quotes them; nothing to raise here.)


def _host_skip_detail(vrecord: dict) -> str:
    """A pass-detail fragment quoting any host-capability skips (surfaced)."""
    skips = vrecord.get("skipped_checks")
    if not isinstance(skips, list):
        return ""
    host = [
        _skip_label(e)
        for e in skips
        if isinstance(e, dict) and e.get("kind") == SKIP_KIND_HOST
    ]
    if host:
        return " (host-capability skips surfaced: " + ", ".join(host) + ")"
    return ""


def _check_undischarged_findings(args, findings_inventory: dict, ledger: dict) -> None:
    """Token 6. A finding in the round's effective fix set has no disposition trace.

    Scoped per context, because #668 landed a single append-only ledger whose
    finding ids the helper assigns:

      * Loop context: the effective fix set is exactly the inventory findings the
        loop flagged `in_fix_set` (its own routing already applied the threshold)
        plus any `reject_driver` — this validator re-grades no severity. Each must
        have a fix_decisions row (joined by finding id). Findings the loop did not
        flag are discharged by the engine's derived-disposition convention and need
        no row.
      * Direct context: the validator cannot enumerate which findings ought to
        carry a row (there is no independent inventory), so it checks the ledger's
        completeness attestation only — a claimed-complete session whose ledger
        carries ZERO dispositions is undischarged; per-finding coverage is NOT
        asserted, and the detail says so.
    """
    if args.context_mode == "direct":
        dispositions = ledger.get("findings")
        if not isinstance(dispositions, list) or not dispositions:
            raise Verdict(
                TOK_UNDISCHARGED,
                "direct session claims complete but its disposition ledger records "
                "zero dispositions (completeness attestation only; per-finding "
                "coverage is not asserted for a direct session)",
            )
        return

    # Loop context. The effective fix set is scoped by the LOOP's own routing, NOT
    # by this validator — the validator re-grades no severity (semantic-exclusion,
    # issue #550). The loop marks each inventory finding it routed into the fix set
    # with `in_fix_set: true` (or `reject_driver: true` for a REJECT-driver);
    # born-advisory below-threshold findings the loop did not route carry
    # in_fix_set falsy and are discharged by the engine's derived-disposition
    # convention. The validator checks only that every flagged-in-fix-set finding
    # carries a fix_decisions row.
    findings = findings_inventory.get("findings")
    if not isinstance(findings, list):
        raise Verdict(
            TOK_MISSING,
            "findings-inventory: `findings` is not a list",
        )
    decisions = ledger.get("fix_decisions")
    decided_ids = set()
    if isinstance(decisions, list):
        for d in decisions:
            if isinstance(d, dict) and isinstance(d.get("finding_id"), str):
                decided_ids.add(d["finding_id"])
    for f in findings:
        if not isinstance(f, dict):
            continue
        in_fix_set = bool(f.get("in_fix_set")) or bool(f.get("reject_driver"))
        if not in_fix_set:
            continue
        fid = f.get("finding_id")
        # An in-fix-set finding whose id is missing or non-string is a malformed
        # producer shape — fail CLOSED (unknown is never pass), never skip it, or a
        # producer bug that drops the id would silently exempt a routed finding.
        if not isinstance(fid, str) or not fid:
            raise Verdict(
                TOK_UNDISCHARGED,
                "an in-fix-set finding carries no usable string finding_id, so its "
                "disposition cannot be joined (malformed findings inventory)",
            )
        if fid not in decided_ids:
            raise Verdict(
                TOK_UNDISCHARGED,
                f"finding {fid} is in the loop's effective fix set but carries no "
                f"fix_decisions row",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Deferral-trace checks (tokens 7 and 8)
# ─────────────────────────────────────────────────────────────────────────────
def _own_repo(args) -> "str | None":
    """The `owner/repo` slug of the repository the validator runs in.

    Resolved through the resolved gh (`gh repo view`), NEVER through a non-preflight
    PATH tool. Used to distinguish a provable-absence 404 (own repo, read access
    established) from an unknown 404 (outside the credential's provable scope).
    A resolution failure returns None — every remote trace is then treated as
    outside provable scope (unverifiable, never provably-absent), the safe direction.
    """
    if args.own_repo:
        return args.own_repo
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [GH, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        slug = proc.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return slug or None


class _RemoteProbe(str, Enum):
    """Outcome of probing one remote trace target.

    A closed str-Enum: membership is the set of members below and nothing else,
    so an out-of-vocabulary outcome is unrepresentable rather than merely
    undocumented. The `str` mixin keeps every existing comparison and any string
    formatting behaving exactly as the prior class-of-constants did.
    """

    EXISTS = "exists"
    ABSENT = "absent"        # a definitive 404 (target does not exist)
    UNREACHABLE = "unreach"  # gh could not reach GitHub


def _probe_remote(args, path: str) -> _RemoteProbe:
    """Probe a remote GitHub API path (best-effort, via the resolved gh).

    Returns one of _RemoteProbe.{EXISTS, ABSENT, UNREACHABLE}. A 404 is ABSENT
    (the target does not exist for this read); any other non-zero that is not a
    clean 404 — and any exec failure — is UNREACHABLE (GitHub was not reached, so
    the target's existence is UNKNOWN, never proven absent).
    """
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [GH, "api", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return _RemoteProbe.UNREACHABLE
    if proc.returncode == 0:
        return _RemoteProbe.EXISTS
    # gh writes the HTTP status into stderr; a 404 is a definitive absence.
    err = proc.stderr or b""
    if b"404" in err or b"Not Found" in err:
        return _RemoteProbe.ABSENT
    return _RemoteProbe.UNREACHABLE


def _check_deferrals(args) -> str:
    """Tokens 7/8. Validate every deferral's durable trace.

    An absent --deferrals file is the producer's established zero-deferral state
    (the manifest omits the file when zero entries survive) — a pass-arm input,
    NOT missing-evidence. Returns a detail fragment (empty on a clean pass) or
    raises a Verdict on the first non-durable / unverifiable trace.

    Each entry's channel is its own `channel`, else the manifest's top-level
    `default_channel` declaration (see KEY_DEFAULT_CHANNEL) — the shape the fix
    loop's run-scoped deferrals manifest emits. An entry that resolves to no
    durable channel by either route is non-durable, unchanged.
    """
    if not args.deferrals:
        return ""
    dpath = Path(args.deferrals)
    if not dpath.exists():
        # Omit-on-zero: the established zero-deferral state.
        return ""
    obj, reason = _read_json_object(dpath)
    if obj is None:
        raise Verdict(TOK_MISSING, f"deferrals: {reason} ({args.deferrals})")
    entries = obj.get("deferrals")
    if entries is None:
        entries = obj.get("entries")
    if not isinstance(entries, list):
        raise Verdict(TOK_MISSING, "deferrals: no `deferrals` list in the manifest")
    if not entries:
        return ""

    # The manifest-level declaration (see KEY_DEFAULT_CHANNEL). Anything that is
    # not a string naming one of the four durable channels is discarded here, so
    # the per-entry membership test below stays the single acceptance point.
    declared = obj.get(KEY_DEFAULT_CHANNEL)
    if not isinstance(declared, str) or declared not in ALL_CHANNELS:
        declared = None

    own = None  # resolved lazily, only if a remote trace needs it
    # Collect each entry's failure and emit the LOWEST-RANKED class across ALL
    # entries — non-durable-deferral (token 7) precedes unverifiable-trace (token 8)
    # in the fixed order, so a provable non-durable failure is never masked by an
    # earlier-listed unverifiable one (first-failing-CLASS, not first-failing-entry).
    non_durable = None
    unverifiable = None
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                raise Verdict(TOK_NON_DURABLE, "a deferral entry is not an object")
            channel = entry.get("channel")
            if channel is None:
                channel = declared
            if channel not in ALL_CHANNELS:
                raise Verdict(
                    TOK_NON_DURABLE,
                    f"deferral {entry.get('finding_id')!r} cites no durable channel "
                    f"(channel={channel!r}; expected one of "
                    f"{'/'.join(sorted(ALL_CHANNELS))})",
                )
            if channel == CHANNEL_LOOP_RECORD:
                # The deferral record itself is the trace — its presence here is the
                # durable channel. Nothing further to check.
                continue
            if channel == CHANNEL_CODE_COMMENT:
                _check_code_comment(args, entry)
                continue
            # Remote channels (pr-thread / follow-up-issue).
            if own is None:
                own = _own_repo(args)
            _check_remote_trace(args, entry, own)
        except Verdict as v:
            if v.token == TOK_NON_DURABLE:
                if non_durable is None:
                    non_durable = v
            elif v.token == TOK_UNVERIFIABLE:
                if unverifiable is None:
                    unverifiable = v
            else:
                raise  # any other class is structural — surface it immediately
    if non_durable is not None:
        raise non_durable
    if unverifiable is not None:
        raise unverifiable
    return ""


def _check_code_comment(args, entry: dict) -> None:
    """A code-comment trace: the cited in-tree file must contain the cited marker."""
    ref = entry.get("ref") if isinstance(entry.get("ref"), dict) else {}
    rel = ref.get("file")
    marker = ref.get("marker")
    if not isinstance(rel, str) or not rel or not isinstance(marker, str) or not marker:
        raise Verdict(
            TOK_NON_DURABLE,
            f"deferral {entry.get('finding_id')!r} code-comment trace names no "
            f"file+marker",
        )
    base = Path(args.repo_root or os.getcwd())
    target = base / rel
    try:
        text = target.read_text("utf-8", errors="replace")
    except OSError:
        raise Verdict(
            TOK_NON_DURABLE,
            f"deferral {entry.get('finding_id')!r} code-comment trace points to "
            f"{rel}, which does not exist or is unreadable",
        )
    if marker not in text:
        raise Verdict(
            TOK_NON_DURABLE,
            f"deferral {entry.get('finding_id')!r} code-comment marker not found "
            f"at {rel}",
        )


def _check_remote_trace(args, entry: dict, own: "str | None") -> None:
    """A pr-thread / follow-up-issue trace.

    The cited target is probed via the resolved gh:
      * EXISTS      -> durable, pass-arm.
      * ABSENT (404) in the validator's OWN repo (read access established) ->
        provable absence -> non-durable-deferral (a fabricated citation is no trace).
      * ABSENT (404) OUTSIDE the credential's provable scope (another repo/tracker)
        -> unverifiable-trace (GitHub serves 404 for unauthorized reads too, so
        absence there is unknown, never proven).
      * UNREACHABLE -> unverifiable-trace (GitHub was not reached).
    """
    ref = entry.get("ref") if isinstance(entry.get("ref"), dict) else {}
    repo = ref.get("repo")
    api_path = ref.get("api_path")
    if not isinstance(api_path, str) or not api_path:
        raise Verdict(
            TOK_NON_DURABLE,
            f"deferral {entry.get('finding_id')!r} remote trace names no api_path",
        )
    outcome = _probe_remote(args, api_path)
    if outcome == _RemoteProbe.EXISTS:
        return
    if outcome == _RemoteProbe.UNREACHABLE:
        raise Verdict(
            TOK_UNVERIFIABLE,
            f"deferral {entry.get('finding_id')!r} remote trace could not be "
            f"checked (GitHub unreachable at validation time)",
        )
    if outcome != _RemoteProbe.ABSENT:
        # Defensive: _probe_remote is closed to the three outcomes and EXISTS /
        # UNREACHABLE are handled above, so this is unreachable today — but a stray
        # value must fail SAFE (unknown), never default into the provable-absence
        # arm below, which would emit a false fabrication accusation.
        raise Verdict(
            TOK_UNVERIFIABLE,
            f"deferral {entry.get('finding_id')!r} remote trace outcome was "
            f"indeterminate (probe returned no definitive result)",
        )
    # ABSENT (a definitive 404).
    in_own_scope = (
        isinstance(repo, str) and own is not None and repo == own
    )
    if in_own_scope:
        raise Verdict(
            TOK_NON_DURABLE,
            f"deferral {entry.get('finding_id')!r} remote trace dereferences to a "
            f"404 in this repository (provable absence — a fabricated citation is "
            f"no trace)",
        )
    raise Verdict(
        TOK_UNVERIFIABLE,
        f"deferral {entry.get('finding_id')!r} remote trace returned 404 outside "
        f"this credential's provable scope (absence there is unknown, not proven)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration — the fixed evaluation order
# ─────────────────────────────────────────────────────────────────────────────
def _validate(args) -> "tuple[str, str]":
    """Run the checks in order; return (token, detail). Raises _Internal on an
    internal failure (exit 2, no verdict line)."""
    context = args.context

    # A CI-derived record (issue #1898) supplies the stale-candidate and
    # verification-pass evidence in place of --verification-record: a reception or
    # fix-loop pass that pushed and read CI reaches the same validation the marker route
    # uses. When one is supplied, --verification-record is not required; the findings and
    # deferral classes below still run and can still refuse.
    ci_record = (
        _require_object(args.ci_record, "ci-record")
        if getattr(args, "ci_record", None) else None
    )

    # 1) missing-evidence — presence, parseability, and binding of the session
    #    anchors and the verification record, before ANY value comparison.
    if ci_record is None:
        vrecord = _require_object(args.verification_record, "verification-record")

    # The preflight identity artifact is a DIRECT-session anchor (the session's
    # opening record). The loop has no such anchor — the verification handle itself
    # carries the recorded candidate identity — so it is required and bound only for
    # a direct session. A session anchor is checked for its claim-context binding,
    # never for equality with claim-time identity (it predates the fixes by
    # definition).
    if args.context_mode == "direct":
        identity_artifact = _require_object(args.identity_artifact, "identity-artifact")
        _require_token_binding(identity_artifact, "identity-artifact", context)
        _check_rebind(identity_artifact, "identity-artifact")

    findings_inventory = _require_object(args.findings_inventory, "findings-inventory")
    _require_token_binding(findings_inventory, "findings-inventory", context)

    # The disposition ledger: for a direct session it IS the findings inventory
    # (reception-record.py's findings.json holds both); for the loop it is the
    # fix_decisions record. Default to the inventory when not separately supplied.
    if args.disposition_ledger:
        ledger = _require_object(args.disposition_ledger, "disposition-ledger")
    else:
        ledger = findings_inventory

    # 2/3/4) currency + pass + skips. On the CI route these three classes are decided
    # from the CI record by _validate_ci_record (issue #1898): stale-candidate (head vs
    # git HEAD over a clean tree) and verification-not-pass (every recorded conclusion a
    # success) map directly. The skipped-checks class is NOT APPLICABLE on the CI route —
    # a CI rollup carries no skip population this record could describe — so it is
    # deliberately not re-checked here; do not re-add a _check_skipped_checks call for the
    # CI branch, which has nothing to read.
    if ci_record is None:
        # Claim-time identity — re-derived (or pinned) — needed for the stale compare.
        claim_identity = _claim_time_identity(args.claim_identity, args.repo_root)
        _check_stale_candidate(vrecord, claim_identity)
        _check_verification_pass(vrecord)
        _check_skipped_checks(vrecord)
    else:
        _validate_ci_record(ci_record, args.repo_root)

    # 5) undischarged-findings — effective fix set vs disposition traces.
    _check_undischarged_findings(args, findings_inventory, ledger)

    # 6/7) deferral traces — non-durable / unverifiable.
    _check_deferrals(args)

    # pass — every class resolved affirmatively.
    detail = "all completion evidence current, bound, and durable"
    if ci_record is None:
        detail += _host_skip_detail(vrecord)
    return TOK_PASS, detail


# ─────────────────────────────────────────────────────────────────────────────
# Implement-completion context (issue #1087) — the stricter no-skip policy
# ─────────────────────────────────────────────────────────────────────────────
# The implement engine's terminal `workpad.py --status Complete` write is gated on
# a canonical verification-flight record (the #528 ledger handle) for the run's
# final in-env verification command. This context is STRICTER than the loop/direct
# contexts above: it admits NO skip population at all (not even host-capability),
# it requires the flight to be in the terminal `passed` STATE (not merely a `passed`
# result), and it requires a nonempty terminal-summary `command` and an integer `0`
# `exit_status`. It mints NO ninth token — every defect maps onto the closed
# ORDERED_TOKENS set, in the documented first-failing-class order
# (missing -> stale -> not-pass -> skipped).
FLIGHT_STATE_PASSED = "passed"


def _validate_implement_record(rec: dict, claim_identity: str) -> "tuple[str, str]":
    """The strict implement-completion checks over a flight record `rec`.

    Raises a Verdict on the first failing class; returns (TOK_PASS, detail) when the
    record is a current, skip-free, passed flight whose candidate identity equals the
    final tree. `claim_identity` is the freshly-derived current-tree identity.
    """
    # 1) missing-evidence — presence and shape of the terminal-summary operands.
    summary = rec.get("suite_summary")
    if not isinstance(summary, dict):
        raise Verdict(
            TOK_MISSING,
            "flight record carries no suite_summary object (terminal evidence absent)",
        )
    command = summary.get("command")
    if not isinstance(command, str) or not command.strip():
        raise Verdict(
            TOK_MISSING,
            "suite_summary.command is missing or not a nonempty string",
        )
    exit_status = summary.get("exit_status")
    # An integer, and NOT a bool (bool is an int subclass) and NOT the string "0":
    # only the JSON integer 0 is a pass, so a wrong-typed field is missing-evidence.
    if isinstance(exit_status, bool) or not isinstance(exit_status, int):
        raise Verdict(
            TOK_MISSING,
            f"suite_summary.exit_status is not a JSON integer ({exit_status!r})",
        )
    top_skips = rec.get("skipped_checks")
    if not isinstance(top_skips, list):
        # A wrong-typed skip set is an unclassifiable shape — fail closed as skipped.
        raise Verdict(
            TOK_SKIPPED,
            "flight record's top-level skipped_checks is not a list (unclassifiable)",
        )

    # 2) missing-identity + stale-candidate — reuse the shared check (a `str` record
    #    with no candidate_identity is TOK_MISSING; a mismatch is TOK_STALE).
    _check_stale_candidate(rec, claim_identity)

    # 3) verification-not-pass — the flight must be in the terminal `passed` STATE
    #    (not merely a `passed` result: any other state — claimed, running, failed,
    #    timed_out, cancelled, stale, incomplete — is non-pass), with a `passed`
    #    result (shared check) and a zero exit status.
    state = rec.get("state")
    if state != FLIGHT_STATE_PASSED:
        raise Verdict(
            TOK_NOT_PASS,
            f"flight state is {state!r}, not {FLIGHT_STATE_PASSED!r}",
        )
    _check_verification_pass(rec)
    if exit_status != 0:
        raise Verdict(
            TOK_NOT_PASS,
            f"suite_summary.exit_status is {exit_status}, not 0",
        )

    # 4) skipped-checks-present — the no-skip policy. The top-level list must be
    #    empty, and when the summary carries its own skipped_checks key it must be an
    #    empty list too (the top-level field is the one the finish path guarantees).
    if top_skips:
        raise Verdict(
            TOK_SKIPPED,
            f"flight records {len(top_skips)} skipped check(s); implement completion "
            f"requires an empty skip population",
        )
    if "skipped_checks" in summary:
        summary_skips = summary["skipped_checks"]
        if not isinstance(summary_skips, list) or summary_skips:
            raise Verdict(
                TOK_SKIPPED,
                "suite_summary.skipped_checks is present but not an empty list",
            )

    return TOK_PASS, "implement completion evidence current, passed, and skip-free"


def validate_implement_completion(
    record_path: "str | None",
    repo_root: "str | None" = None,
    claim_identity: "str | None" = None,
) -> "tuple[str, str]":
    """Importable entry point used lazily by scripts/workpad.py's terminal gate.

    Reads the canonical flight record at `record_path` and runs the strict
    implement-completion checks. Returns (token, detail) — `token == TOK_PASS`
    (== "pass") only when every class resolved affirmatively. A None/absent/
    unreadable/malformed/non-object record is TOK_MISSING. Raises _Internal only
    when the current-tree identity cannot be derived (an internal failure of the
    check itself, never a verdict about the run) — the caller aborts on that too.
    """
    try:
        rec = _require_object(record_path, "verification-flight")
        fresh = _claim_time_identity(claim_identity, repo_root)
        return _validate_implement_record(rec, fresh)
    except Verdict as v:
        return v.token, v.detail


# ─────────────────────────────────────────────────────────────────────────────
# CI-derived implement-completion context (issue #1611) — the local/interactive
# tier's second accepted evidence family
# ─────────────────────────────────────────────────────────────────────────────
# Issue #1607 made a CI reading this repository's local/interactive whole-suite
# completion gate, but the mechanical `--status Complete` gate could express only an
# in-environment verification-flight pass. This context is the second accepted
# family: a local run that established a green required check for the commit it
# pushed records that reading, and this validator accepts it — OFFLINE and
# DETERMINISTICALLY. It performs no network call and no `gh` invocation: the decision
# is a function of the record's fields, `git rev-parse HEAD`, and
# `git status --porcelain` alone. It mints NO ninth token; every refusal maps onto
# the closed ORDERED_TOKENS set in the same first-failing-class order the flight
# context uses (missing -> stale -> not-pass). A malformed field shape is
# missing-evidence; a SHA that does not match the current head, or a dirty tree, is
# stale-candidate; a non-success conclusion is verification-not-pass.
CI_SUCCESS_CONCLUSION = "success"
# The tier that OWNS the CI-derived evidence family. A cloud run owes an in-environment
# result (issue #1607), so a record whose tier is `cloud` — or which names no tier — is
# refused; `local` is the sole accepted value and any other value fails closed.
CI_LOCAL_TIER = "local"
CI_CLOUD_TIER = "cloud"
# The scalar string fields every CI record must carry. The check pairs are a separate
# non-empty `checks` list of {name, conclusion} objects, validated below.
_CI_REQUIRED_FIELDS = ("head_sha", "tier", "run_url")
# The single declared source of the required-check set is `.github/workflows/ci.yml`: the
# `name:` of every job marked with this line. The check-name literal lives only in ci.yml,
# so no second file restates the set (issue #1898).
_REQUIRED_CHECK_MARKER = "# prflow:required-check"


def _is_full_hex_sha(value: object) -> bool:
    """True only for exactly 40 lowercase-hex characters — the full head SHA shape.

    A 7-char abbreviation (the shape `gh run list` silently matches nothing on), a
    41-char string, and a 40-char string carrying an uppercase hex digit each return
    False, so the caller routes them to a non-pass token rather than a false pass.
    Hand-rolled rather than a regex because this module imports exactly the modules
    it imports today (issue #1611 AC) — no `import re`.
    """
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(c in "0123456789abcdef" for c in value)
    )


def _ci_git_read(repo_root: "str | None", argv: "list[str]") -> str:
    """Read `git <argv>` in `repo_root` through reception_identity's native-git reader
    (argv list, no shell, Windows-safe) — the module's single git-spawn routine, so
    the CI checks add no subprocess of their own and the module's "git only inside the
    derivation routine" invariant stays true. A git-not-found, exec error, non-zero
    exit, or undecodable output is an internal failure of the check itself — not a
    verdict about the record — so it is re-raised as `_Internal` (exit 2, no verdict
    line), exactly as the identity re-derivation maps `IdentityError`."""
    try:
        return ri._run_git_text(argv, repo_root or os.getcwd())
    except ri.IdentityError as exc:
        raise _Internal(f"ci_git:{exc.reason}")


def _required_checks(repo_root: "str | None") -> "frozenset[str]":
    """The required-check set, read from the single declared source
    `.github/workflows/ci.yml` under `repo_root`: the `name:` of every job marked with a
    `# prflow:required-check` line. An absent ci.yml declares no required checks (an empty
    set, so coverage is vacuous); an unreadable one is an internal failure of the check
    itself (`_Internal`, exit 2), never a silent empty set that would un-gate coverage."""
    path = Path(repo_root or os.getcwd()) / ".github" / "workflows" / "ci.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except OSError as exc:
        raise _Internal(f"required_checks:unreadable:{exc.__class__.__name__}")
    names: "set[str]" = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != _REQUIRED_CHECK_MARKER:
            continue
        # The next non-blank line is the marked job's `name:` mapping; take its value.
        for nxt in lines[i + 1:]:
            stripped = nxt.strip()
            if not stripped:
                continue
            if stripped.startswith("name:"):
                val = stripped[len("name:"):].strip().strip('"').strip("'")
                if val:
                    names.add(val)
            break
    return frozenset(names)


def _validate_ci_record(record: object, repo_root: "str | None") -> "tuple[str, str]":
    """The strict CI-derived completion checks over a decoded `record`.

    Raises a Verdict on the first failing class; returns (TOK_PASS, detail) when the
    record is a well-formed `local`-tier record whose recorded checks cover the required
    set with every conclusion a success, and whose head SHA equals `git rev-parse HEAD`
    over a clean tree. `record` is the already-decoded payload object (any JSON type); a
    non-object and each missing or malformed field are missing-evidence, so the caller may
    hand this any shape the best-effort payload decoder produced. The first-failing-class
    order is the module's own: missing-evidence -> stale-candidate -> verification-not-pass.
    """
    # 1) missing-evidence — object shape and the presence/shape of the scalar fields.
    if not isinstance(record, dict):
        raise Verdict(
            TOK_MISSING,
            "CI completion record is not a JSON object (unclassifiable payload)",
        )
    for field in _CI_REQUIRED_FIELDS:
        val = record.get(field)
        if not isinstance(val, str) or not val.strip():
            raise Verdict(
                TOK_MISSING,
                f"CI completion record field {field!r} is missing or not a "
                f"nonempty string",
            )
    head_sha = record["head_sha"]
    if not _is_full_hex_sha(head_sha):
        raise Verdict(
            TOK_MISSING,
            f"CI completion record head_sha is not exactly 40 lowercase hex "
            f"characters ({head_sha!r})",
        )

    # 2) missing-evidence — the tier must be `local`. A `cloud` tier owes an in-env
    #    result, and any other value (or the absent tier caught above) is refused,
    #    naming the tier so the refusal is legible.
    tier = record["tier"]
    if tier != CI_LOCAL_TIER:
        if tier == CI_CLOUD_TIER:
            raise Verdict(
                TOK_MISSING,
                "CI completion record tier is 'cloud' — a cloud run owes an "
                "in-environment result, not a CI-derived reading",
            )
        raise Verdict(
            TOK_MISSING,
            f"CI completion record tier is {tier!r}, not {CI_LOCAL_TIER!r}",
        )

    # 3) missing-evidence — a non-empty `checks` list of {name, conclusion} objects.
    checks = record.get("checks")
    if not isinstance(checks, list) or not checks:
        raise Verdict(
            TOK_MISSING,
            "CI completion record carries no nonempty 'checks' list of "
            "name/conclusion pairs",
        )
    for entry in checks:
        if not isinstance(entry, dict):
            raise Verdict(
                TOK_MISSING,
                "a CI completion 'checks' entry is not a JSON object",
            )
        name = entry.get("name")
        concl = entry.get("conclusion")
        if not isinstance(name, str) or not name.strip():
            raise Verdict(
                TOK_MISSING,
                "a CI completion check entry has no nonempty 'name'",
            )
        if not isinstance(concl, str) or not concl.strip():
            raise Verdict(
                TOK_MISSING,
                f"CI completion check {name!r} has no nonempty 'conclusion'",
            )

    # 4) missing-evidence — the recorded checks must cover the required-check set read
    #    from the single declared source (ci.yml), naming the first missing member.
    recorded_names = {e["name"] for e in checks}
    required = _required_checks(repo_root)
    missing = sorted(required - recorded_names)
    if missing:
        raise Verdict(
            TOK_MISSING,
            f"CI completion record does not cover required check {missing[0]!r} "
            "(declared in .github/workflows/ci.yml)",
        )

    # 5) stale-candidate — the recorded head must equal the current head over a
    #    clean tree, so the reading describes the tree being finalized.
    current_head = _ci_git_read(repo_root, ["rev-parse", "HEAD"]).strip()
    if head_sha != current_head:
        raise Verdict(
            TOK_STALE,
            "CI completion evidence predates the current head "
            "(recorded head_sha differs from git rev-parse HEAD)",
        )
    porcelain = _ci_git_read(repo_root, ["status", "--porcelain"])
    if porcelain.strip():
        raise Verdict(
            TOK_STALE,
            "the working tree is not clean at gate time "
            "(git status --porcelain is non-empty)",
        )

    # 6) verification-not-pass — every recorded conclusion must be a success.
    for entry in checks:
        if entry["conclusion"] != CI_SUCCESS_CONCLUSION:
            raise Verdict(
                TOK_NOT_PASS,
                f"CI check {entry['name']!r} conclusion is {entry['conclusion']!r}, "
                f"not {CI_SUCCESS_CONCLUSION!r}",
            )

    return TOK_PASS, (
        "CI-derived completion evidence current, clean, tier-scoped, and successful"
    )


def validate_implement_completion_ci(
    record: object,
    repo_root: "str | None" = None,
) -> "tuple[str, str]":
    """Importable entry point used lazily by scripts/workpad.py's terminal gate for
    the CI-derived evidence family (issue #1611).

    `record` is the decoded payload object (workpad.py decodes the marker payload and
    hands the result here). Returns (token, detail) — `token == TOK_PASS` only when
    every class resolved affirmatively. A non-object, a non-`local` tier, a checks list
    that does not cover the required set, and each missing/malformed field are TOK_MISSING;
    a stale head or dirty tree is TOK_STALE; any non-success conclusion is TOK_NOT_PASS.
    Raises `_Internal` (exit 2, no verdict) only when a git read or the required-check
    source read fails — an internal failure of the check, never a verdict about the record.
    """
    try:
        return _validate_ci_record(record, repo_root)
    except Verdict as v:
        return v.token, v.detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-completion-evidence.py",
        description="Validate receiving-review completion evidence (issue #550). "
        "Prints exactly one `completion-check: <token> — <detail>` line.",
    )
    parser.add_argument(
        "--context", required=False, default=None,
        help="The claim-context operand: the loop's run identifier, or the direct "
             "session's preflight-minted claim-context token (printed by the "
             "preflight at mint time; re-reading it from the cited artifacts is "
             "forbidden — that would compare an artifact with itself).",
    )
    parser.add_argument(
        "--context-mode", required=True, choices=("loop", "direct", "implement"),
        help="Which invocation context is claiming completion. Scopes the "
             "undischarged-findings check. `implement` validates a canonical "
             "verification-flight record under the stricter no-skip completion policy "
             "(issue #1087) and reads --flight-record instead of the session anchors.",
    )
    parser.add_argument(
        "--flight-record", default=None,
        help="implement context only: the canonical verification-flight record "
             "(.prflow/tmp/verification-flights/<flight-key>.json) to validate.",
    )
    parser.add_argument("--verification-record", default=None,
                        help="The current verification record (the #528 durable "
                             "status handle, or a verification_evidence record).")
    parser.add_argument("--identity-artifact", default=None,
                        help="The preflight identity artifact (session anchor).")
    parser.add_argument("--findings-inventory", default=None,
                        help="The findings inventory (session anchor). Loop: the "
                             "per-iteration Phase-3 findings union. Direct: the "
                             "disposition ledger (reception-record findings.json).")
    parser.add_argument("--disposition-ledger", default=None,
                        help="The round's disposition record. Loop: fix_decisions. "
                             "Direct: defaults to the findings inventory.")
    parser.add_argument("--deferrals", default=None,
                        help="The deferrals manifest. Absent/omitted file is the "
                             "established zero-deferral state (a pass-arm input).")
    parser.add_argument("--repo-root", default=None,
                        help="Repository root for re-deriving the claim-time "
                             "candidate identity and resolving code-comment traces "
                             "(default: the current working directory).")
    parser.add_argument("--claim-identity", default=None,
                        help="Pin the claim-time candidate identity (the loop "
                             "passes what it computed); default re-derives it.")
    parser.add_argument("--ci-record", default=None,
                        help="loop/direct context: a JSON CI-derived completion record "
                             "(tier + head_sha + run_url + a nonempty checks list). When "
                             "supplied, the stale-candidate and verification-pass classes "
                             "are decided from this record via the CI validator (issue "
                             "#1898) instead of --verification-record; the "
                             "undischarged-findings and deferral-durability classes still "
                             "run and can still refuse.")
    parser.add_argument("--own-repo", default=None,
                        help="Override the resolved owner/repo slug (tests).")
    return parser


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: "list[str] | None" = None) -> int:
    _force_utf8_streams()
    # The verdict line carries a U+2014 em-dash; force a UTF-8-capable stdout so a
    # non-pass verdict emitted from the except-Verdict handler below cannot raise an
    # UnicodeEncodeError under an ASCII/C-locale runner (the LC_ALL=C class this repo
    # documents) and escape uncaught. Best-effort: a non-reconfigurable stdout (a
    # test-substituted stream) is left as-is.
    _reconf = getattr(sys.stdout, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.context_mode == "implement":
            token, detail = validate_implement_completion(
                args.flight_record, args.repo_root, args.claim_identity,
            )
        else:
            token, detail = _validate(args)
        return _emit(token, detail)
    except Verdict as v:
        return _emit(v.token, v.detail)
    except _Internal as exc:
        sys.stderr.write(
            json.dumps({"ok": False, "internal_error": exc.reason}) + "\n"
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - contract: no bare traceback, no verdict line
        sys.stderr.write(
            json.dumps({"ok": False, "internal_error": f"unexpected:{exc.__class__.__name__}"})
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

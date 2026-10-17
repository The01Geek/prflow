#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Completion-evidence validators for an implement run (issues #550, #1087).

An importable library with no command line. `scripts/workpad.py`'s terminal
`--status Complete` gate loads it and calls one entry point per evidence family:

    validate_implement_completion           a verification-flight record
    validate_implement_completion_ci        a local-tier CI-derived record
    validate_implement_completion_cloud_ci  a cloud-CI evidence record

Each returns `(token, detail)`. The token is one of exactly five, evaluated in a
fixed order with the FIRST failing class returned (presence/parseability before
any value compare):

    missing-evidence -> stale-candidate -> verification-not-pass ->
    skipped-checks-present -> pass

Exceptions, all in a flight record: a `skipped_checks` that is not a list is
`skipped-checks-present` (the top-level one before the stale-candidate check runs),
and `state` and `result` are compared as values, so anything but the pass value,
absence included, is `verification-not-pass`.

Unknown never collapses onto pass: any other operand that is absent/unreadable/
unparseable is `missing-evidence` before any value comparison. An internal failure
of the check itself (the identity cannot be derived, a git or declared-source read fails) raises
`_Internal` instead of returning a token.

What this validator DOES NOT do (semantic-exclusion, issue #550): it re-grades no
severity, re-judges no fix and re-runs no test. It validates references —
existence, parseability, identity-binding and recorded results.

Invariants (mirrors scripts/workpad.py's Windows-safe native-git pattern,
issues #275/#295):
  * python3 standard-library only. No PyYAML import.
  * Candidate identity is re-derived at validation time by CALLING the shipped
    identity producer (scripts/reception_identity.derive_candidate_identity) —
    one derivation routine, never a second implementation of the identity format.
  * git is invoked ONLY inside the imported reception_identity routines (native
    subprocess, argv list, no shell). This module spawns no subprocess of its own
    and makes no network call.
  * No decisive value is derived through a non-preflight PATH tool
    (`tr`/`sed`/`wc`/`cut`/`head`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The shared per-shard provenance contract (issue #419). Importing this sibling — which may
# use `re` internally — keeps this module's own import set free of `import re` (see
# _is_full_hex_sha), so the offline digest/binding re-checks reuse one owned contract.
import ci_shard_provenance as csp
import reception_identity as ri

# The five tokens (pass is the terminal affirmative).
TOK_PASS = "pass"
TOK_MISSING = "missing-evidence"
TOK_STALE = "stale-candidate"
TOK_NOT_PASS = "verification-not-pass"
TOK_SKIPPED = "skipped-checks-present"

# The closed token vocabulary: the terminal affirmative `pass` first, followed by
# the four failing classes in the documented first-failing-class evaluation order;
# ALL_TOKENS closes the set so a raise-site typo cannot ship a garbage token
# (mirrors verification-flight.py's ALL_STATES / _CodedError closed-vocabulary guard).
ORDERED_TOKENS = (
    TOK_PASS,
    TOK_MISSING,
    TOK_STALE,
    TOK_NOT_PASS,
    TOK_SKIPPED,
)
ALL_TOKENS = frozenset(ORDERED_TOKENS)

# The one `result` value a verification-flight record carries when it passed (the
# #528 flight handle writes it). Any other value is a non-pass — the "unknown is
# never pass" rule at the value level.
PASS_RESULT = "passed"


class Verdict(Exception):
    """A resolved verdict — carries the token and the detail clause.

    Raised the instant a failing class resolves, so the first-failing-class
    ordering is expressed by control flow rather than by a scoreboard the caller
    could read out of order.
    """

    def __init__(self, token: str, detail: str):
        # Closed-vocabulary guard: a mistyped token is a programming error, not a
        # verdict to return.
        if token not in ALL_TOKENS:
            raise ValueError(f"Verdict token {token!r} is not one of {sorted(ALL_TOKENS)}")
        super().__init__(token)
        self.token = token
        self.detail = detail


# ─────────────────────────────────────────────────────────────────────────────
# Best-effort JSON-object reader (the six-shape adversarial matrix, CLAUDE.md)
# ─────────────────────────────────────────────────────────────────────────────
def _read_json_object(path: Path) -> tuple[dict | None, str | None]:
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
        obj = csp.loads_strict(raw.decode("utf-8"))
    except csp.DuplicateKeyError:
        return None, "duplicate_key"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "malformed"
    if not isinstance(obj, dict):
        # array, scalar, and the valid-falsy JSON false/0/"" all land here.
        return None, "not_object"
    return obj, None


def _require_object(path_str: str | None, label: str) -> dict:
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


# ─────────────────────────────────────────────────────────────────────────────
# Candidate-identity re-derivation (single source of truth — the #668 routine)
# ─────────────────────────────────────────────────────────────────────────────
def _claim_time_identity(claim_identity: str | None, repo_root: str | None) -> str:
    """The claim-time candidate identity.

    Re-derived at validation time by calling the shipped identity producer, so
    the identity format has exactly one implementation. A caller may pin an
    explicit value (`workpad.py --claim-identity`); any other value routes
    through the derivation routine.
    """
    if claim_identity:
        return claim_identity
    try:
        return ri.derive_candidate_identity(repo_root or os.getcwd())
    except ri.IdentityError as exc:
        # A derivation that cannot complete is an internal failure of the check
        # itself, not a verdict about the claim.
        raise _Internal(f"identity_derivation:{exc.reason}")


class _Internal(Exception):
    """An internal failure of the validator: raised to the caller, never a token."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Individual class checks (each raises a Verdict on the first failure it finds)
# ─────────────────────────────────────────────────────────────────────────────
def _check_stale_candidate(vrecord: dict, claim_identity: str) -> None:
    """The verification record's recorded candidate identity must equal the
    claim-time identity (byte comparison)."""
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
    """The record's result must be its producer's pass value."""
    result = vrecord.get("result")
    if result != PASS_RESULT:
        raise Verdict(
            TOK_NOT_PASS,
            f"verification result is {result!r}, not a pass",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Implement-completion context (issue #1087) — the no-skip policy
# ─────────────────────────────────────────────────────────────────────────────
# The implement engine's terminal `workpad.py --status Complete` write is gated on
# a canonical verification-flight record (the #528 ledger handle) for the run's
# final in-env verification command. It admits NO skip population at all (not even
# host-capability), it requires the flight to be in the terminal `passed` STATE (not
# merely a `passed` result), and it requires a nonempty terminal-summary `command`
# and an integer `0` `exit_status`. Every defect maps onto the closed
# ORDERED_TOKENS set, in the documented first-failing-class order
# (missing -> stale -> not-pass -> skipped).
FLIGHT_STATE_PASSED = "passed"


def _validate_implement_record(rec: dict, claim_identity: str) -> tuple[str, str]:
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
    record_path: str | None,
    repo_root: str | None = None,
    claim_identity: str | None = None,
) -> tuple[str, str]:
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
# is a function of the record's fields, `git rev-parse HEAD`, `git status --porcelain`,
# and the required-check set declared in `.github/workflows/ci.yml` alone. It mints no token of its own; every refusal maps onto
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
# `name:` of every job marked with this line, read by _required_checks (issue #1898).
_REQUIRED_CHECK_MARKER = "# prflow:required-check"

# ── issue #403: the cloud-CI completion-evidence family ──────────────────────
# A cloud implement run that verified through the existing CI suite records a
# structurally richer, distinctly-keyed evidence object than the local-tier CI record.
# The validator below dispatches on THIS shape (kind + schema_version), never on a bare
# `tier: "cloud"` string — merely allowing the cloud string would keep a record with no
# run/attempt/tested-tree/shard validation. The declared CI contract is
# `.github/workflows/ci.yml`: its workflow filename, its `# prflow:required-check` set
# (via _required_checks), and its `shard:` matrix (via _expected_shards).
CI_CLOUD_EVIDENCE_KIND = "cloud_ci_evidence"
# The one accepted schema version. Bumped to 2 by issue #419: version-1 evidence carried
# UNBOUND per-shard tallies, so a version-1 record is refused by name — never silently read
# (the reject-bool-as-int / accepted-versions pattern of scripts/verification-flight.py).
# Sourced from the shared contract so this consumer and the collector share one literal.
CI_CLOUD_EVIDENCE_SCHEMA_VERSION = csp.CLOUD_CI_EVIDENCE_SCHEMA_VERSION
# The workflow filename the cloud-CI contract binds to; a record naming any other
# workflow is foreign evidence and is refused. Sourced from the shared contract so this
# literal cannot drift from the producer's and collector's.
CI_CLOUD_WORKFLOW = csp.CI_WORKFLOW
# The scalar string fields a cloud-CI evidence record must carry (run_id/run_attempt are
# checked as integers separately). request_id is required so the per-shard provenance
# binding (issue #419) can cross-check each envelope against the record's own identity.
_CLOUD_CI_REQUIRED_SCALARS = ("repo", "workflow", "run_url", "head_sha", "request_id")
# The per-shard tally fields whose value must be a zero integer for a passing record.
_CLOUD_CI_ZERO_TALLY_FIELDS = ("failed", "skipped", "exit_status")


def _cloud_ci_int(value: object) -> bool:
    """True for a real JSON integer, rejecting bool (isinstance(True, int) is True in
    Python, so a `true`/`false` literal must never read as 1/0) — the no-coercion rule
    the issue's testing strategy names for the record's numeric tally fields."""
    return isinstance(value, int) and not isinstance(value, bool)


def _expected_shards(repo_root: str | None) -> frozenset[str]:
    """The declared shard population, read from the single declared source
    `.github/workflows/ci.yml` under `repo_root`: the inline `shard: [a, b, …]` matrix
    list. An absent ci.yml declares no shards (empty set — the caller refuses a record
    whose population disagrees); an unreadable one is an internal failure of the check
    itself (`_Internal`), never a silent empty set that would un-gate the
    population comparison. The matrix order follows lib/test/module_catalog.py's
    SHARD_NAMES, exposed by run-shard.sh --list-shards; this parse is set-valued."""
    path = Path(repo_root or os.getcwd()) / ".github" / "workflows" / "ci.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except OSError as exc:
        raise _Internal(f"expected_shards:unreadable:{exc.__class__.__name__}")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("shard:") or "[" not in stripped or "]" not in stripped:
            continue
        inside = stripped[stripped.index("[") + 1: stripped.rindex("]")]
        names = {part.strip() for part in inside.split(",") if part.strip()}
        if names:
            return frozenset(names)
    return frozenset()


def _validate_cloud_ci_record(record: object, repo_root: str | None) -> tuple[str, str]:
    """The strict cloud-CI completion checks over a decoded `record` (issue #403).

    Returns (TOK_PASS, detail) only for a well-formed `cloud_ci_evidence` record whose
    declared shard population equals the repo's declared set, whose every shard reports
    zero failed/skipped/exit and whose required checks cover the declared set with every
    conclusion a success, and whose head SHA equals `git rev-parse HEAD` over a clean tree.
    First-failing-class order is the module's own: missing-evidence -> stale-candidate ->
    verification-not-pass -> skipped-checks-present. A non-object and each missing/malformed
    field are missing-evidence, so the caller may hand this any decoded payload shape.
    The live run/attempt cross-checks against GitHub are the evidence collector's job (a
    separate, network-touching helper); this validator is offline and deterministic, so it
    binds the run to THIS tree through head==HEAD and to the declared contract through the
    workflow name, required-check set, and shard population."""
    # 1) missing-evidence — object shape, kind, schema version.
    if not isinstance(record, dict):
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record is not a JSON object (unclassifiable payload)")
    if record.get("kind") != CI_CLOUD_EVIDENCE_KIND:
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record kind is {record.get('kind')!r}, "
                      f"not {CI_CLOUD_EVIDENCE_KIND!r}")
    # schema_version must be a real integer equal to the accepted version. Route it
    # through _cloud_ci_int (which rejects bool AND float) before the equality compare, so
    # neither a bool nor a float equal to the accepted version reads as that version.
    _sv = record.get("schema_version")
    if not _cloud_ci_int(_sv) or _sv != CI_CLOUD_EVIDENCE_SCHEMA_VERSION:
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record schema_version is {_sv!r}, "
                      f"not the integer {CI_CLOUD_EVIDENCE_SCHEMA_VERSION}")

    # 2) missing-evidence — scalar string fields.
    for field in _CLOUD_CI_REQUIRED_SCALARS:
        val = record.get(field)
        if not isinstance(val, str) or not val.strip():
            raise Verdict(TOK_MISSING,
                          f"cloud-CI completion record field {field!r} is missing or not a "
                          f"nonempty string")
    if not _is_full_hex_sha(record["head_sha"]):
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record head_sha is not exactly 40 lowercase hex "
                      f"characters ({record['head_sha']!r})")
    # run_id / run_attempt — real integers, bool rejected.
    for field in ("run_id", "run_attempt"):
        if not _cloud_ci_int(record.get(field)):
            raise Verdict(TOK_MISSING,
                          f"cloud-CI completion record field {field!r} is missing or not an integer")

    # 3) missing-evidence — foreign-workflow binding.
    if record["workflow"] != CI_CLOUD_WORKFLOW:
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record workflow is {record['workflow']!r}, "
                      f"not the declared CI contract {CI_CLOUD_WORKFLOW!r} (foreign evidence)")

    # 4) missing-evidence — shard population equals the repo's declared set, and the shard
    #    tally dict's keys match the declared population exactly (no absent/extra shard).
    population = record.get("expected_shard_population")
    if not isinstance(population, list) or not population or \
            not all(isinstance(s, str) and s.strip() for s in population):
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record expected_shard_population is not a nonempty "
                      "list of shard names")
    declared = _expected_shards(repo_root)
    if set(population) != set(declared):
        extra = sorted(set(population) - set(declared))
        missing = sorted(set(declared) - set(population))
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record expected_shard_population does not match the "
                      f".github/workflows/ci.yml shard matrix (extra: {extra}; missing: {missing})")
    shards = record.get("shards")
    if not isinstance(shards, dict) or not shards:
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record carries no nonempty 'shards' tally object")
    shard_keys = set(shards.keys())
    if shard_keys != set(population):
        absent = sorted(set(population) - shard_keys)
        extra = sorted(shard_keys - set(population))
        detail = "cloud-CI completion record shards do not match the expected population"
        if absent:
            detail += f" (absent shard {absent[0]!r})"
        elif extra:
            detail += f" (foreign shard {extra[0]!r})"
        raise Verdict(TOK_MISSING, detail)
    # 4a) missing-evidence — per-shard provenance binding (issue #419): re-verify each retained
    #     envelope's digest over its retained summary and match every producer identity to the
    #     top-level identity, so an altered, mixed, or removed envelope/summary/tally refuses here.
    # run_attempt is validated per shard below (leftover rule), not as a flat exact-match
    # field — a Spot retry leaves survivor envelopes at an earlier attempt (issue #543).
    top_identity = (
        ("repo", record["repo"]),
        ("workflow", record["workflow"]),
        ("request_id", record["request_id"]),
        ("candidate_sha", record["head_sha"]),
        ("run_id", record["run_id"]),
    )
    top_attempt = record["run_attempt"]
    current_attempt_shards = 0
    for name, entry in shards.items():
        if not isinstance(entry, dict):
            raise Verdict(TOK_MISSING, f"cloud-CI shard {name!r} entry is not a JSON object")
        tally = entry.get(csp.SHARD_ENTRY_TALLY)
        if not isinstance(tally, dict):
            raise Verdict(TOK_MISSING,
                          f"cloud-CI shard {name!r} carries no 'tally' object")
        for tfield in ("passed", *_CLOUD_CI_ZERO_TALLY_FIELDS):
            if not _cloud_ci_int(tally.get(tfield)):
                raise Verdict(TOK_MISSING,
                              f"cloud-CI shard {name!r} tally field {tfield!r} is missing or not "
                              f"an integer")
        summary_text = entry.get(csp.SHARD_ENTRY_SUMMARY)
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise Verdict(TOK_MISSING,
                          f"cloud-CI shard {name!r} carries no retained summary_text")
        prov = entry.get(csp.SHARD_ENTRY_PROVENANCE)
        try:
            csp.validate_envelope(prov)
            parsed = csp.verify_summary_binding(prov, summary_text.encode("utf-8"))
        except csp.ProvenanceError as exc:
            raise Verdict(TOK_MISSING,
                          f"cloud-CI shard {name!r} provenance is invalid "
                          f"({exc.reason}: {exc.detail})")
        for tfield in ("passed", "failed", "skipped", "exit_status"):
            if parsed[tfield] != tally[tfield]:
                raise Verdict(TOK_MISSING,
                              f"cloud-CI shard {name!r} recorded tally {tfield}={tally[tfield]} "
                              f"disagrees with the retained summary ({parsed[tfield]})")
        if prov["shard"] != name:
            raise Verdict(TOK_MISSING,
                          f"cloud-CI shard {name!r} provenance names shard {prov['shard']!r}")
        for field, top in top_identity:
            if prov[field] != top:
                raise Verdict(TOK_MISSING,
                              f"cloud-CI shard {name!r} provenance {field}={prov[field]!r} does "
                              f"not match the evidence identity {top!r}")
        # run_attempt: accept the current attempt, or a strictly-earlier leftover (a Spot
        # retry reran only the interrupted shard); refuse one ahead of the record attempt.
        # Classified through the same shared predicate the collector uses (issue #543).
        prov_attempt = prov["run_attempt"]
        attempt_class = csp.classify_shard_attempt(prov_attempt, top_attempt)
        if attempt_class == csp.ATTEMPT_CURRENT:
            current_attempt_shards += 1
        elif attempt_class != csp.ATTEMPT_LEFTOVER:
            raise Verdict(TOK_MISSING,
                          f"cloud-CI shard {name!r} provenance run_attempt={prov_attempt!r} is "
                          f"neither the evidence attempt {top_attempt!r} nor an earlier leftover")

    # A record whose every shard is a leftover names no current-attempt evidence — refuse it,
    # mirroring the collector's whole-tree check (issue #543).
    if current_attempt_shards == 0:
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record has no shard at the evidence attempt "
                      f"{top_attempt!r}; a record of only leftover envelopes is not evidence")

    # 5) missing-evidence — required-check coverage from the declared source (ci.yml).
    checks = record.get("required_checks")
    if not isinstance(checks, list) or not checks:
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record carries no nonempty 'required_checks' list")
    for entry in checks:
        if not isinstance(entry, dict):
            raise Verdict(TOK_MISSING, "a cloud-CI required_checks entry is not a JSON object")
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            raise Verdict(TOK_MISSING, "a cloud-CI required_checks entry has no nonempty 'name'")
        if not isinstance(entry.get("conclusion"), str) or not entry["conclusion"].strip():
            raise Verdict(TOK_MISSING,
                          f"cloud-CI required check {entry.get('name')!r} has no nonempty "
                          f"'conclusion'")
    recorded_names = {e["name"] for e in checks}
    required = _required_checks(repo_root)
    # Fail closed on a required-check source that declares nothing: a present ci.yml whose
    # `# prflow:required-check` markers were removed or renamed would otherwise make the
    # coverage class pass vacuously (empty required set → empty `uncovered`), verifying
    # zero required checks. An empty declared set is unestablished, never a clean cover.
    if not required:
        raise Verdict(TOK_MISSING,
                      "cloud-CI completion record cannot be covered — .github/workflows/ci.yml "
                      "declares no '# prflow:required-check' jobs (required-check source empty)")
    uncovered = sorted(required - recorded_names)
    if uncovered:
        raise Verdict(TOK_MISSING,
                      f"cloud-CI completion record does not cover required check {uncovered[0]!r} "
                      "(declared in .github/workflows/ci.yml)")

    # 6) stale-candidate — the recorded head must equal the current head over a clean tree.
    current_head = _ci_git_read(repo_root, ["rev-parse", "HEAD"]).strip()
    if record["head_sha"] != current_head:
        raise Verdict(TOK_STALE,
                      "cloud-CI completion evidence predates the current head "
                      "(recorded head_sha differs from git rev-parse HEAD)")
    if _ci_git_read(repo_root, ["status", "--porcelain"]).strip():
        raise Verdict(TOK_STALE,
                      "the working tree is not clean at gate time "
                      "(git status --porcelain is non-empty)")

    # 7) verification-not-pass — a nonzero failed/exit tally or a non-success required-check
    #    conclusion. Matching check NAMES alone cannot discharge the record: the population
    #    and tally classes above must already have passed to reach here.
    for name, entry in shards.items():
        tally = entry[csp.SHARD_ENTRY_TALLY]
        if tally["failed"] != 0:
            raise Verdict(TOK_NOT_PASS,
                          f"cloud-CI shard {name!r} reports {tally['failed']} failed test(s)")
        if tally["exit_status"] != 0:
            raise Verdict(TOK_NOT_PASS,
                          f"cloud-CI shard {name!r} reports exit status {tally['exit_status']}")
    # Grade only the DECLARED required set. The collector records every job the run
    # reported, and ci.yml's pull_request-gated notification job is always `skipped` on a
    # workflow_dispatch run — grading the whole list refuses every real record. Coverage
    # (class 5 above) already proved each required check is present.
    for entry in checks:
        if entry["name"] not in required:
            continue
        if entry["conclusion"] != CI_SUCCESS_CONCLUSION:
            raise Verdict(TOK_NOT_PASS,
                          f"cloud-CI required check {entry['name']!r} conclusion is "
                          f"{entry['conclusion']!r}, not {CI_SUCCESS_CONCLUSION!r}")
    # Never drop this per-shard passed == 0 check: every declared shard owns a non-empty
    # test set, so a shard that executed nothing clears every zero failed/skipped/exit
    # class above and would otherwise read as a clean pass.
    for name, entry in shards.items():
        if entry[csp.SHARD_ENTRY_TALLY]["passed"] == 0:
            raise Verdict(TOK_NOT_PASS,
                          f"cloud-CI shard {name!r} reports zero passed tests "
                          "(the shard executed nothing — not a clean pass)")

    # 8) skipped-checks-present — a skipped test in any shard is never a clean pass.
    for name, entry in shards.items():
        if entry[csp.SHARD_ENTRY_TALLY]["skipped"] != 0:
            raise Verdict(TOK_SKIPPED,
                          f"cloud-CI shard {name!r} reports "
                          f"{entry[csp.SHARD_ENTRY_TALLY]['skipped']} skipped test(s)")

    return TOK_PASS, (
        "cloud-CI completion evidence current, clean, population-complete, and successful"
    )


def validate_implement_completion_cloud_ci(
    record: object,
    repo_root: str | None = None,
) -> tuple[str, str]:
    """Importable entry point used lazily by scripts/workpad.py's terminal gate for the
    cloud-CI evidence family (issue #403).

    `record` is the decoded payload object (workpad.py decodes the marker payload and hands
    the result here). Returns (token, detail) — `token == TOK_PASS` only when every class
    resolved affirmatively. Raises `_Internal` only when a git read or
    a declared-source read fails — an internal failure of the check, never a verdict about
    the record."""
    try:
        return _validate_cloud_ci_record(record, repo_root)
    except Verdict as v:
        return v.token, v.detail


def _is_full_hex_sha(value: object) -> bool:
    """True only for exactly 40 lowercase-hex characters — the full head SHA shape.

    A 7-char abbreviation (the shape `gh run list` silently matches nothing on), a
    41-char string, and a 40-char string carrying an uppercase hex digit each return
    False, so the caller routes them to a non-pass token rather than a false pass.
    Hand-rolled rather than a regex because this module carries no `import re`
    directly (issue #1611 AC); regex-needing checks live in the imported
    ci_shard_provenance sibling instead.
    """
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(c in "0123456789abcdef" for c in value)
    )


def _ci_git_read(repo_root: str | None, argv: list[str]) -> str:
    """Read `git <argv>` in `repo_root` through reception_identity's native-git reader
    (argv list, no shell, Windows-safe) — the module's single git-spawn routine, so
    the CI checks add no subprocess of their own and the module's "git only inside the
    derivation routine" invariant stays true. A git-not-found, exec error, non-zero
    exit, or undecodable output is an internal failure of the check itself — not a
    verdict about the record — so it is re-raised as `_Internal`, exactly as the
    identity re-derivation maps `IdentityError`."""
    try:
        return ri._run_git_text(argv, repo_root or os.getcwd())
    except ri.IdentityError as exc:
        raise _Internal(f"ci_git:{exc.reason}")


def _required_checks(repo_root: str | None) -> frozenset[str]:
    """The required-check set, read from the single declared source
    `.github/workflows/ci.yml` under `repo_root`: the `name:` of every job marked with a
    `# prflow:required-check` line. An absent ci.yml declares no required checks (an empty
    set, so coverage is vacuous); an unreadable one is an internal failure of the check
    itself (`_Internal`), never a silent empty set that would un-gate coverage."""
    path = Path(repo_root or os.getcwd()) / ".github" / "workflows" / "ci.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except OSError as exc:
        raise _Internal(f"required_checks:unreadable:{exc.__class__.__name__}")
    names: set[str] = set()
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


def _validate_ci_record(record: object, repo_root: str | None) -> tuple[str, str]:
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
    repo_root: str | None = None,
) -> tuple[str, str]:
    """Importable entry point used lazily by scripts/workpad.py's terminal gate for
    the CI-derived evidence family (issue #1611).

    `record` is the decoded payload object (workpad.py decodes the marker payload and
    hands the result here). Returns (token, detail) — `token == TOK_PASS` only when
    every class resolved affirmatively. A non-object, a non-`local` tier, a checks list
    that does not cover the required set, and each missing/malformed field are TOK_MISSING;
    a stale head or dirty tree is TOK_STALE; any non-success conclusion is TOK_NOT_PASS.
    Raises `_Internal` only when a git read or the required-check
    source read fails — an internal failure of the check, never a verdict about the record.
    """
    try:
        return _validate_ci_record(record, repo_root)
    except Verdict as v:
        return v.token, v.detail


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the entry path only, never at import (issue #1762)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


if __name__ == "__main__":
    _force_utf8_streams()
    print("check-completion-evidence.py: no command line; import the module", file=sys.stderr)
    sys.exit(2)

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Phase 2 sweep-evidence validator and summarizer (issue #438).

A deterministic, semantic-FREE record of what a `/prflow:implement` run's Phase 2
sweeps did: which sweeps were selected, each sweep's terminal outcome, and the
distinct corrections ("catches") each sweep owned. `scripts/workpad.py`'s
`--record-sweep-evidence` flag validates one record through `validate_sweep_evidence`
before it writes the machine marker; the `summarize` subcommand here measures the
retained workpad bodies afterward, counting one accepted result per run-and-sweep
identity — never interpreting prose.

Two consumers, one on-disk format: the base64url-unpadded JSON object rides a
`sweep-evidence:<run_identity>:<payload>` keyed-checkpoint marker inside a workpad's
`## Progress` section. `_MARKER_RE` below MUST agree with `scripts/workpad.py`'s
`_SWEEP_EVIDENCE_MARKER_RE`; the two are edited together (coupled site), and the
round-trip test writes a marker through `workpad.py` and reads it back here so a
drift between them fails a test rather than silently under-counting.

Invariants (mirror scripts/check-completion-evidence.py):
  * python3 standard-library only.
  * No decisive value is derived through a non-preflight PATH tool.
  * The validator makes no network call and spawns no subprocess.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "sweep-evidence"

# The closed terminal-outcome vocabulary — complete by construction (issue #438).
# A zero-catch `completed` result is distinct from a `degraded` or `unrunnable` one,
# and a selected sweep with no result at all is a separate, rejected condition
# (`missing-sweep-result`) the summarizer tallies as an incomplete run.
OUTCOMES = ("completed", "degraded", "unrunnable")
_OUTCOME_SET = frozenset(OUTCOMES)
# Import-time self-check (mirrors workpad._validate_review_coverage_axis_specs, which
# likewise uses an explicit raise, not a bare `assert` that `python3 -O` strips): a
# duplicate outcome literal is a programming error, never a shipped vocabulary.
if len(_OUTCOME_SET) != len(OUTCOMES):
    raise AssertionError("OUTCOMES must be unique")

# run_identity keys the marker and is the field a colon delimiter separates from the
# payload, so it admits neither a colon nor whitespace; the checkpoint-key grammar
# also admits it.
_RUN_IDENTITY_RE = re.compile(r"\A[A-Za-z0-9._-]+\Z")

# Marker grammar — MUST agree with scripts/workpad.py's _SWEEP_EVIDENCE_MARKER_RE
# (coupled site). Group 1 is the run identity, group 2 the base64url payload.
_MARKER_RE = re.compile(
    r"<!-- (?:pr|dev)flow:checkpoint sweep-evidence:([^:\s]+):([^\s]+?) -->"
)


# The closed vocabulary of rejection tokens `_Reject` may carry — every literal a
# `raise _Reject(...)` below names. A typo (`bad-catchs`) would otherwise construct a
# valid object and propagate as an accepted rejection token; the `__init__` self-check
# turns that into a loud programming error, mirroring the OUTCOMES frozenset guard above.
_REJECT_TOKENS = frozenset((
    "not-object", "wrong-kind", "unsupported-version", "bad-run-identity",
    "bad-diff-shape", "bad-selected-sweeps", "bad-results",
    "unknown-outcome", "duplicate-sweep-result", "unselected-sweep-result",
    "missing-sweep-result", "bad-catches", "owner-outside-selected",
    "owner-without-result", "owner-unrunnable", "evidence-less-catch", "second-owner",
))


class _Reject(Exception):
    """A resolved rejection — carries the token and a one-line detail."""

    def __init__(self, token: str, detail: str):
        # Explicit raise, not a bare `assert` (which `python3 -O` strips), so the
        # closed-vocabulary guard survives an optimized consumer interpreter.
        if token not in _REJECT_TOKENS:
            raise AssertionError(f"unknown _Reject token {token!r}")
        super().__init__(token)
        self.token = token
        self.detail = detail


def encode_payload(record: dict) -> str:
    """Encode a record dict as a base64url-unpadded token (matches workpad.py's
    `_encode_ci_payload`, so a payload round-trips through either producer)."""
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_payload(payload: object) -> tuple[dict | None, str]:
    """Decode a marker payload to `(record, breadcrumb)`. Best-effort, never raises:
    the record is a dict only when the breadcrumb is `ok`; otherwise the breadcrumb
    names the defect — `not-a-string`, `empty-payload`, `undecodable`,
    `falsy-payload` (JSON null/false/0/""), `array-payload`, `scalar-payload`."""
    if not isinstance(payload, str):
        return None, "not-a-string"
    if not payload:
        return None, "empty-payload"
    try:
        pad = "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + pad)
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, "undecodable"
    if isinstance(value, dict):
        return value, "ok"
    if not value:
        return None, "falsy-payload"
    if isinstance(value, list):
        return None, "array-payload"
    return None, "scalar-payload"


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_structure(record: object) -> tuple[list[str], list[dict]]:
    """Validate the record's shape and return (selected_sweeps, results). Raises
    `_Reject` on the first structural defect."""
    if not isinstance(record, dict):
        raise _Reject("not-object", "sweep-evidence record is not a JSON object")
    if record.get("kind") != KIND:
        raise _Reject("wrong-kind",
                      f"record kind is {record.get('kind')!r}, not {KIND!r}")
    sv = record.get("schema_version")
    # Reject bool (a JSON true/false must never read as 1/0) before the equality test.
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != SCHEMA_VERSION:
        raise _Reject("unsupported-version",
                      f"schema_version is {sv!r}, not the integer {SCHEMA_VERSION}")
    run_identity = record.get("run_identity")
    if not _nonempty_str(run_identity) or not _RUN_IDENTITY_RE.match(run_identity):
        raise _Reject("bad-run-identity",
                      f"run_identity {run_identity!r} is missing or not [A-Za-z0-9._-]+")
    if not _nonempty_str(record.get("diff_shape")):
        raise _Reject("bad-diff-shape", "diff_shape is missing or not a nonempty string")

    selected = record.get("selected_sweeps")
    if not isinstance(selected, list) or not selected \
            or not all(_nonempty_str(s) for s in selected):
        raise _Reject("bad-selected-sweeps",
                      "selected_sweeps is not a nonempty list of nonempty strings")
    if len(set(selected)) != len(selected):
        raise _Reject("bad-selected-sweeps", "selected_sweeps contains a duplicate id")

    results = record.get("results")
    if not isinstance(results, list):
        raise _Reject("bad-results", "results is not a list")
    for entry in results:
        if not isinstance(entry, dict):
            raise _Reject("bad-results", "a results entry is not a JSON object")
        if not _nonempty_str(entry.get("sweep_id")):
            raise _Reject("bad-results", "a results entry has no nonempty sweep_id")
        if entry.get("outcome") not in _OUTCOME_SET:
            raise _Reject("unknown-outcome",
                          f"results entry for {entry.get('sweep_id')!r} has outcome "
                          f"{entry.get('outcome')!r}, not one of {'/'.join(OUTCOMES)}")
    return selected, results


def _check_accounting(selected: list[str], results: list[dict],
                      catches: object) -> None:
    """Validate the selection/result/catch accounting. Raises `_Reject` on the first
    violation; a missing result is checked last so it alone marks an incomplete run."""
    selected_set = set(selected)
    outcome_of: dict[str, str] = {}
    for entry in results:
        sid = entry["sweep_id"]
        if sid in outcome_of:
            raise _Reject("duplicate-sweep-result",
                          f"results names sweep {sid!r} more than once")
        outcome_of[sid] = entry["outcome"]
        if sid not in selected_set:
            raise _Reject("unselected-sweep-result",
                          f"results names sweep {sid!r}, which is not in selected_sweeps")

    if not isinstance(catches, list):
        raise _Reject("bad-catches", "catches is not a list")
    owner_of: dict[str, str] = {}
    for entry in catches:
        if not isinstance(entry, dict):
            raise _Reject("bad-catches", "a catches entry is not a JSON object")
        cid = entry.get("catch_id")
        if not _nonempty_str(cid):
            raise _Reject("bad-catches", "a catches entry has no nonempty catch_id")
        owner = entry.get("discovered_by")
        if not _nonempty_str(owner):
            raise _Reject("bad-catches",
                          f"catch {cid!r} has no nonempty discovered_by")
        if owner not in selected_set:
            raise _Reject("owner-outside-selected",
                          f"catch {cid!r} is owned by {owner!r}, which is not in "
                          f"selected_sweeps")
        if owner not in outcome_of:
            raise _Reject("owner-without-result",
                          f"catch {cid!r} is owned by {owner!r}, which has no result")
        if outcome_of[owner] == "unrunnable":
            raise _Reject("owner-unrunnable",
                          f"catch {cid!r} is owned by {owner!r}, which was unrunnable")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence \
                or not all(_nonempty_str(e) for e in evidence):
            raise _Reject("evidence-less-catch",
                          f"catch {cid!r} carries no nonempty evidence reference")
        if cid in owner_of:
            # A catch reported by two sweeps is attributed exactly once, to the
            # earliest selected sweep that reported it; a second owner entry (a later
            # sweep claiming the same catch_id) is the violation the recorder rejects.
            raise _Reject("second-owner",
                          f"catch {cid!r} names a second owner {owner!r} "
                          f"(already owned by {owner_of[cid]!r})")
        owner_of[cid] = owner

    missing = [s for s in selected if s not in outcome_of]
    if missing:
        raise _Reject("missing-sweep-result",
                      f"selected sweep {missing[0]!r} has no result")


def validate_sweep_evidence(record: object) -> tuple[str, str]:
    """Importable entry point workpad.py's `--record-sweep-evidence` handler calls.

    Returns (token, detail): `('ok', …)` when the record is well-formed and its
    selection/result/catch accounting is self-consistent, else a named rejection
    token in the first-failing order the checks below run. Ownership resolution is
    within-record — a catch carries its single earliest owner — so the record alone
    is the operand.
    """
    try:
        selected, results = _check_structure(record)
        _check_accounting(selected, results, record.get("catches"))
    except _Reject as r:
        return r.token, r.detail
    return "ok", "sweep-evidence record well-formed and self-consistent"


# ─────────────────────────────────────────────────────────────────────────────
# Summarizer — measures retained workpad bodies (one accepted result per
# run-and-sweep identity), never interpreting prose.
# ─────────────────────────────────────────────────────────────────────────────
def _empty_counters() -> dict:
    return {"selected": 0, "completed": 0, "caught": 0,
            "owned_catches": 0, "degraded": 0, "unrunnable": 0}


def summarize_body(body: str) -> dict:
    """Measure one retained workpad body. Groups every sweep-evidence marker by run
    identity; a run identity carrying two DIFFERENT payloads is ambiguous and is
    excluded (`ambiguous_runs`); a record missing a selected sweep's result is an
    `incomplete_runs` entry; any other defect is tallied in `rejected_markers` under
    its breadcrumb (a decode breadcrumb, `identity-mismatch` when the marker key and
    the payload's run_identity differ, or the validator token). Only accepted runs
    reach `per_sweep`. Returns a deterministic summary."""
    by_run: dict[str, list[str]] = {}
    for run_identity, payload in _MARKER_RE.findall(body or ""):
        by_run.setdefault(run_identity, []).append(payload)

    per_sweep: dict[str, dict] = {}
    runs = 0
    ambiguous = 0
    incomplete = 0
    rejected: dict[str, int] = {}

    def counters(sweep_id: str) -> dict:
        return per_sweep.setdefault(sweep_id, _empty_counters())

    for run_identity in sorted(by_run):
        payloads = set(by_run[run_identity])
        if len(payloads) != 1:
            # Multiple distinct records for one run identity — ambiguous, never counted.
            ambiguous += 1
            continue
        record, token = decode_payload(next(iter(payloads)))
        if token == "ok" and record.get("run_identity") != run_identity:
            token = "identity-mismatch"
        if token == "ok":
            token, _ = validate_sweep_evidence(record)
        if token == "missing-sweep-result":
            incomplete += 1
            continue
        if token != "ok":
            rejected[token] = rejected.get(token, 0) + 1
            continue
        runs += 1
        selected = record["selected_sweeps"]
        outcome_of = {r["sweep_id"]: r["outcome"] for r in record["results"]}
        owned: dict[str, set] = {}
        for c in record["catches"]:
            owned.setdefault(c["discovered_by"], set()).add(c["catch_id"])
        for sweep_id in selected:
            ctr = counters(sweep_id)
            ctr["selected"] += 1
            outcome = outcome_of.get(sweep_id)
            if outcome == "completed":
                ctr["completed"] += 1
            elif outcome == "degraded":
                ctr["degraded"] += 1
            elif outcome == "unrunnable":
                ctr["unrunnable"] += 1
            n_owned = len(owned.get(sweep_id, ()))
            if n_owned:
                ctr["caught"] += 1
                ctr["owned_catches"] += n_owned

    # Run-wide distinct-catch total. Within a single record every catch_id has exactly
    # one owning sweep (the recorder rejects `second-owner`), and catch_ids are
    # run-scoped, so summing each sweep's `owned_catches` over all sweeps and all
    # accepted runs counts every recorded catch exactly once. Surfaced at the top level
    # so a retrospective consumer reads the run-wide yield directly rather than
    # re-summing `per_sweep`.
    total_owned_catches = sum(v["owned_catches"] for v in per_sweep.values())
    return {
        "runs": runs,
        "ambiguous_runs": ambiguous,
        "incomplete_runs": incomplete,
        "rejected_markers": {k: rejected[k] for k in sorted(rejected)},
        "total_owned_catches": total_owned_catches,
        "per_sweep": {k: per_sweep[k] for k in sorted(per_sweep)},
    }


def _cmd_summarize(args) -> int:
    try:
        body = Path(args.workpad_file).read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(
            f"sweep-evidence summarize: cannot read --workpad-file "
            f"{args.workpad_file!r} ({exc.__class__.__name__})\n")
        return 2
    summary = summarize_body(body)
    sys.stdout.write(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    return 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 at the CLI entry path (never at import: that would
    mutate the streams of any process importing this module for tests). Tolerates a
    stream with no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        prog="sweep-evidence.py",
        description="Validate or summarize Phase 2 sweep-evidence records (issue #438).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summarize",
                           help="Measure per-sweep yield over a retained workpad body.")
    p_sum.add_argument("--workpad-file", required=True,
                       help="Path to a retained workpad body to measure.")
    p_sum.set_defaults(func=_cmd_summarize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

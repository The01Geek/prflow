#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reconcile the two Phase-3.4 acceptance-criteria verifier reports (issue #1575).

Phase 3.4's Acceptance Criteria Gate dispatches two fresh-context verifiers — an
*evidence* verifier (which establishes each in-scope criterion's verification
evidence and is the only one that runs an in-env verification command) and a
*claim* verifier (which checks the shipped code against each criterion's literal
claim and executes nothing). This helper is the executable core the orchestrator
invokes to reconcile the two per-criterion reports into a single record it then
routes on. Making the reconciliation an executable helper — rather than
agent-executed prose — is what lets it carry regression coverage for the
3x3 status-pairing table below.

Reconciliation contract (one row per criterion, matched by 1-based `criterion`):

  - Both verifiers report the SAME status  -> that status is recorded.
  - Any disagreement                        -> `unestablished` is recorded.
  - A criterion present in only one report  -> the missing side is `unestablished`
    (fail closed), so the pair disagrees unless the present side also read
    `unestablished`.
  - A reconciled `satisfied` with NO evidence pointer from either verifier is
    downgraded to `unestablished`: a satisfied record never lands without an
    evidence pointer (issue #1575 AC6).

Blocking: `unmet` and `unestablished` both block; only `satisfied` does not.
`unestablished` blocking exactly as `unmet` blocks is the structural point of the
two-verifier design — a disagreement the orchestrator can act on.

Input: two JSON files, each a list of objects
    {"criterion": <int, 1-based>, "status": "satisfied|unmet|unestablished",
     "evidence": "<pointer string, optional>"}
An unrecognized/absent status is treated as `unestablished` (fail closed) rather
than crashing, because the reports are agent-authored.

Output: one JSON object on stdout —
    {"criteria": [ {"criterion", "evidence_status", "claim_status", "status",
                    "blocks", "evidence", "evidence_source"} ... ],
     "all_satisfied": <bool>, "blocking": [<criterion>, ...]}

Exit codes:
    0 — reconciliation produced (whether or not any criterion blocks)
    3 — a report file was unreadable, not valid JSON, or not a JSON list
"""

import argparse
import json
import sys

VALID_STATUSES = ("satisfied", "unmet", "unestablished")
BLOCKING_STATUSES = ("unmet", "unestablished")


def _normalize_status(value):
    """Map an agent-authored status onto the fixed vocabulary, fail-closed.

    An absent, non-string, or unrecognized status is `unestablished` — never
    silently coerced onto `satisfied`/`unmet`, which would let a malformed report
    tick or clear a criterion it never actually decided.
    """
    if isinstance(value, str) and value.strip().lower() in VALID_STATUSES:
        return value.strip().lower()
    return "unestablished"


def _evidence_of(record):
    if not isinstance(record, dict):
        return ""
    ev = record.get("evidence")
    return ev.strip() if isinstance(ev, str) else ""


def reconcile_one(evidence_status, claim_status, evidence_ptr, claim_ptr):
    """Reconcile one criterion's two verifier verdicts.

    Returns (status, evidence, evidence_source). `evidence_source` is one of
    "evidence", "claim", "both", or "" (empty when the reconciled status is not
    satisfied, or on the downgrade path).
    """
    e = _normalize_status(evidence_status)
    c = _normalize_status(claim_status)
    e_ptr = evidence_ptr.strip() if isinstance(evidence_ptr, str) else ""
    c_ptr = claim_ptr.strip() if isinstance(claim_ptr, str) else ""

    status = e if e == c else "unestablished"

    if status != "satisfied":
        return status, "", ""

    # Satisfied: require an evidence pointer from at least one verifier (AC6).
    if e_ptr and c_ptr:
        return "satisfied", "; ".join((e_ptr, c_ptr)), "both"
    if e_ptr:
        return "satisfied", e_ptr, "evidence"
    if c_ptr:
        return "satisfied", c_ptr, "claim"
    # Both verifiers said satisfied but neither supplied evidence — fail closed.
    return "unestablished", "", ""


def _index_by_criterion(records, side):
    """Index a report list by 1-based `criterion`. Fail closed on a bad shape."""
    by_num = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        num = rec.get("criterion")
        if isinstance(num, bool) or not isinstance(num, int):
            continue
        by_num[num] = rec
    return by_num


def reconcile(evidence_records, claim_records):
    """Reconcile two full verifier reports into the record the orchestrator routes on."""
    e_by = _index_by_criterion(evidence_records, "evidence")
    c_by = _index_by_criterion(claim_records, "claim")

    criteria_out = []
    blocking = []
    for num in sorted(set(e_by) | set(c_by)):
        e_rec = e_by.get(num)
        c_rec = c_by.get(num)
        # A criterion absent from one report fails closed to `unestablished` on
        # that side (it never voted), so the pair can only agree when the present
        # side also read `unestablished`.
        e_status = e_rec.get("status") if isinstance(e_rec, dict) else "unestablished"
        c_status = c_rec.get("status") if isinstance(c_rec, dict) else "unestablished"
        status, evidence, evidence_source = reconcile_one(
            e_status, c_status, _evidence_of(e_rec), _evidence_of(c_rec)
        )
        blocks = status in BLOCKING_STATUSES
        if blocks:
            blocking.append(num)
        criteria_out.append(
            {
                "criterion": num,
                "evidence_status": _normalize_status(e_status),
                "claim_status": _normalize_status(c_status),
                "status": status,
                "blocks": blocks,
                "evidence": evidence,
                "evidence_source": evidence_source,
            }
        )

    return {
        "criteria": criteria_out,
        "all_satisfied": len(blocking) == 0 and len(criteria_out) > 0,
        "blocking": blocking,
    }


def _load_report(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of verifier records")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reconcile the two Phase-3.4 AC verifier reports into one record."
    )
    parser.add_argument("--evidence-file", required=True,
                        help="JSON report from the evidence verifier")
    parser.add_argument("--claim-file", required=True,
                        help="JSON report from the claim verifier")
    args = parser.parse_args(argv)

    try:
        evidence_records = _load_report(args.evidence_file)
        claim_records = _load_report(args.claim_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Fail closed and name the cause: an unreadable/malformed report is an
        # unestablished measurement, never a silently-empty (and therefore
        # trivially-passing) reconciliation.
        print(f"reconcile-ac-verifiers: could not read a verifier report: {exc}",
              file=sys.stderr)
        return 3

    print(json.dumps(reconcile(evidence_records, claim_records), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  - A side that left any named step of its own charter undispositioned is forced
    to `unestablished` BEFORE the two statuses are paired (issue #1580), so an
    abbreviated check reconciles `unestablished` rather than riding the other
    verifier's agreement into `satisfied`. A stated `no` discharges its slot
    fully and changes no status by itself.

Blocking: `unmet` and `unestablished` both block; only `satisfied` does not.
`unestablished` blocking exactly as `unmet` blocks is the structural point of the
two-verifier design — a disagreement the orchestrator can act on.

Input: two JSON files, each a list of objects
    {"criterion": <int, 1-based>, "status": "satisfied|unmet|unestablished",
     "evidence": "<pointer string, optional>",
     "dispositions": {"<slot>": "yes|no (one-clause reason)", ...}}
An unrecognized/absent status is treated as `unestablished` (fail closed) rather
than crashing, because the reports are agent-authored. `dispositions` maps each
named step of that side's charter (`EVIDENCE_SLOTS` / `CLAIM_SLOTS`) to a value
of the form `yes|no (one-clause reason)` — the slot name is the KEY, never part
of the value. The verdict-plus-reason convention is the writing-skills evidence
marker's; the `<slot>=<verdict>` spelling that marker uses in prose is NOT the
shape here, and a value carrying it does not parse.

A verifier record may carry an optional `reason` (the evidence verifier attaches
`denied`/`failed`/`unresolved` to a non-satisfied criterion) which is passed
through on a blocking record, so the orchestrator routes the denied-command case
to its Blocked-naming-`allowed_tools` path from a field, not by sniffing free text.

Output: one JSON object on stdout —
    {"criteria": [ {"criterion", "evidence_status", "claim_status", "status",
                    "blocks", "reason", "evidence", "evidence_source",
                    "evidence_status_reported", "claim_status_reported",
                    "evidence_dispositions", "claim_dispositions",
                    "undischarged_slots"} ... ],
     "all_satisfied": <bool>, "blocking": [<criterion>, ...]}
The two disposition maps and `undischarged_slots` (side-qualified `<side>:<slot>`)
are carried out so the orchestrator records what each verifier did alongside the
reconciled verdict, rather than letting it die with the dispatch return. The two
`*_status_reported` fields carry what each side concluded BEFORE the slot gate
overrode it, so a criterion blocking on a real `unmet` stays distinguishable from
one blocking only on an attestation gap.

Exit codes:
    0 — reconciliation produced (whether or not any criterion blocks)
    3 — a report file was unreadable, not valid JSON, or not a JSON list
"""

import argparse
import json
import re
import sys

def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


VALID_STATUSES = ("satisfied", "unmet", "unestablished")
BLOCKING_STATUSES = ("unmet", "unestablished")

# Do not rename or drop a slot without the matching edit to the `| Slot |` table AND the
# worked example in agents/ac-evidence-verifier.md / agents/ac-claim-verifier.md: the
# gate would then check a slot the charter never asks for, blocking every criterion.
EVIDENCE_SLOTS = ("type-decided", "command-run", "single-flight", "evidence-recorded")
CLAIM_SLOTS = ("claim-traced", "command-source-read", "evidence-recorded")

# Do not widen the lookahead to admit `-` (`no-op, …` would discharge a slot), nor
# narrow it to whitespace-and-paren (`no, <reason>` would be rejected, hard-blocking a
# compliant criterion). Both directions are pinned.
_DISPOSITION_RE = re.compile(r"^(yes|no)(?=$|[\s(,;:.])(.*)$",
                             re.IGNORECASE | re.DOTALL)

# Do not simplify a slot read to `raw.get(slot)`: that collapses a JSON `null` onto an
# omitted key, and only the null is breadcrumbed as a stated-but-unparseable value.
_ABSENT = object()

# Do not compare this marker by truthiness: the key shares a namespace with
# agent-authored report fields, so a report could forge it and blank its own audit
# fields. The VALUE is identity-checked against the sentinel below.
_POISONED = "_reconcile_poisoned"
_POISON_TOKEN = object()

# The reason must carry at least one alphanumeric character. Testing only for emptiness
# would let a mechanical `yes .` or `yes -` discharge a slot with no clause behind it.
_REASON_SUBSTANTIVE_RE = re.compile(r"[^\W_]")


def parse_disposition(value):
    """Parse one slot value into `(verdict, reason)`, or `(None, "")` if undischarged.

    `no` is a fully discharging verdict — the gate asks for a *stated* disposition,
    never a particular one, so treating `no` as a failure would produce false `yes`.
    A reason that is absent or carries no alphanumeric character is undischarged,
    `yes` / `yes ()` / `yes .` alike: a verdict with no clause behind it attests to
    nothing an after-the-fact reader can weigh.
    """
    if not isinstance(value, str):
        return None, ""
    match = _DISPOSITION_RE.match(value.strip())
    if not match:
        return None, ""
    reason = match.group(2).strip()
    # Unwrap only a clause the outer parens actually enclose. Do not substitute a
    # `strip("()")` chain, which strips parens from each end independently and would
    # turn `((a))` into `a`, silently reshaping a malformed value into a well-formed
    # one rather than carrying it through as written.
    if (reason.startswith("(") and reason.endswith(")")
            and "(" not in reason[1:-1] and ")" not in reason[1:-1]):
        reason = reason[1:-1].strip()
    if not _REASON_SUBSTANTIVE_RE.search(reason):
        return None, ""
    return match.group(1).lower(), reason


def _dispositions_of(record, slots, side=""):
    """Return `(stated_map, undischarged_slots)` for one verifier record.

    Only the named `slots` are consulted, so an invented slot name cannot discharge a
    named one. A record that is not a dict, carries no `dispositions` object, or states
    a slot without a parseable verdict-plus-reason leaves that slot undischarged —
    silence about a step is never read as having performed it.

    Three shapes additionally get a stderr breadcrumb, matching `_index_by_criterion`'s
    convention: a slot stated but unparseable (a JSON `null` included), a `dispositions`
    value that is not an object, and a NON-EMPTY object sharing no key with the named
    slots. An omitted slot is deliberately silent — the status already carries it. The
    breadcrumbs are a human diagnostic on the run's stderr; no shipped step parses them.
    """
    who = side or "verifier"
    raw = record.get("dispositions", _ABSENT) if isinstance(record, dict) else _ABSENT
    if raw is not _ABSENT and not isinstance(raw, dict):
        print(f"reconcile-ac-verifiers: the {who} report's 'dispositions' is a "
              f"{type(raw).__name__}, not an object — scoring every slot undischarged",
              file=sys.stderr)
    if not isinstance(raw, dict):
        raw = {}
    elif raw and not any(slot in raw for slot in slots):
        print(f"reconcile-ac-verifiers: the {who} report's 'dispositions' names none of "
              f"the expected slots {list(slots)} (it names {sorted(raw)}) — scoring "
              f"every slot undischarged", file=sys.stderr)
    stated = {}
    undischarged = []
    for slot in slots:
        raw_value = raw.get(slot, _ABSENT)
        verdict, _reason = parse_disposition(
            None if raw_value is _ABSENT else raw_value)
        if verdict is None:
            undischarged.append(slot)
            if raw_value is not _ABSENT:
                print(f"reconcile-ac-verifiers: the {who} report states "
                      f"slot {slot!r} as {raw_value!r}, which is not a parseable "
                      f"'<yes|no> <reason>' disposition — scoring it undischarged",
                      file=sys.stderr)
        else:
            # The verbatim value, not the parsed reason: it is what the orchestrator
            # records durably, and a reader weighing an abbreviated check wants the
            # verifier's own words rather than this parser's normalization of them.
            stated[slot] = raw_value
    return stated, undischarged


def _side(record, slots, tag):
    """Resolve one side into `(status, reported_status, dispositions, undischarged)`.

    `reported_status` is what the side itself concluded, retained even when the slot
    gate overrides `status`. Without it a verifier that reported `unmet` with a real
    failing detail but omitted one slot is indistinguishable from one that concluded
    nothing, and the routing rule that fires only when a criterion blocks SOLELY on
    undischarged slots cannot decide its own precondition.

    Applied symmetrically to both sides so the per-side rules — the fail-closed status
    read for an absent record, and the #1580 downgrade for an undispositioned charter
    step — are stated once rather than mirrored in the caller's loop body.

    An ABSENT record — and equally a duplicate-poisoned one — reports no undischarged
    slots. Each is a vote the side never usably cast, already blocking on its own;
    naming its slots would send the orchestrator to re-dispatch a verifier to restate a
    record it never made, and would make those causes indistinguishable from a genuine
    attestation gap in the one field that routes the remedy.
    """
    if not isinstance(record, dict) or record.get(_POISONED) is _POISON_TOKEN:
        return "unestablished", "unestablished", {}, []
    dispositions, missing = _dispositions_of(record, slots, tag)
    reported = record.get("status")
    status = reported
    if missing:
        status = "unestablished"
        if _normalize_status(reported) != "unestablished":
            print(f"reconcile-ac-verifiers: the {tag} report concluded "
                  f"{_normalize_status(reported)!r} but left {len(missing)} slot(s) "
                  f"undischarged — forcing unestablished; the concluded status is "
                  f"retained as {tag}_status_reported", file=sys.stderr)
    return status, reported, dispositions, [f"{tag}:{slot}" for slot in missing]


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


# Structured, machine-routable reason the evidence verifier may attach to a
# non-satisfied criterion, so the orchestrator routes the denied-command case to the
# Blocked-naming-`allowed_tools` path from a field rather than by sniffing free text.
# It is a CLOSED vocabulary validated like `status`: an unrecognized value normalizes
# to "" (no reason) rather than passing through, so a consumer may rely on any non-empty
# `reason` being one of these tokens. The criterion still blocks on its `status`;
# `reason` only refines HOW the orchestrator routes the block.
EVIDENCE_REASONS = ("denied", "failed", "unresolved")


def _reason_of(record):
    """The record's `reason`, normalized to the closed `EVIDENCE_REASONS` set or ""."""
    if not isinstance(record, dict):
        return ""
    reason = record.get("reason")
    if not isinstance(reason, str):
        return ""
    normalized = reason.strip().lower()
    return normalized if normalized in EVIDENCE_REASONS else ""


def reconcile_one(evidence_status, claim_status, evidence_ptr, claim_ptr):
    """Reconcile one criterion's two verifier verdicts.

    Returns (status, evidence, evidence_source). `evidence_source` is one of
    "evidence", "claim", "both", or "" (empty only when neither verifier supplied a
    pointer). A blocking (`unmet`/`unestablished`) record keeps whatever pointer(s) the
    verifiers supplied — the failing detail the orchestrator's Blocked-path reflection
    names — rather than blanking it; only the AC6 no-evidence downgrade path is empty.
    """
    e = _normalize_status(evidence_status)
    c = _normalize_status(claim_status)
    e_ptr = evidence_ptr.strip() if isinstance(evidence_ptr, str) else ""
    c_ptr = claim_ptr.strip() if isinstance(claim_ptr, str) else ""

    status = e if e == c else "unestablished"

    if e_ptr and c_ptr:
        evidence, source = "; ".join((e_ptr, c_ptr)), "both"
    elif e_ptr:
        evidence, source = e_ptr, "evidence"
    elif c_ptr:
        evidence, source = c_ptr, "claim"
    else:
        evidence, source = "", ""

    # A satisfied record must carry a pointer from at least one verifier (AC6);
    # without one it fails closed to `unestablished`.
    if status == "satisfied" and not evidence:
        return "unestablished", "", ""
    return status, evidence, source


def _index_by_criterion(records, side):
    """Index a report list by 1-based `criterion`. Fail closed on a bad shape.

    `side` ("evidence"/"claim") names the report for the breadcrumbs below. A record
    that is not a dict, or whose `criterion` is absent/non-int/boolean, is dropped with
    a stderr breadcrumb (a criterion dropped from one side becomes a missing vote, which
    reconciles closed to `unestablished`). A **duplicate** `criterion` is poisoned to an
    evidence-less `unestablished` record rather than resolved last-wins, so a malformed
    report can never let a later `satisfied` overwrite an earlier `unmet`.
    """
    by_num = {}
    for rec in records:
        if not isinstance(rec, dict):
            print(f"reconcile-ac-verifiers: dropping a non-object record in the "
                  f"{side} report", file=sys.stderr)
            continue
        num = rec.get("criterion")
        if isinstance(num, bool) or not isinstance(num, int):
            print(f"reconcile-ac-verifiers: dropping a {side}-report record whose "
                  f"'criterion' is absent or not an integer ({num!r})", file=sys.stderr)
            continue
        if num in by_num:
            print(f"reconcile-ac-verifiers: duplicate criterion {num} in the {side} "
                  f"report — failing it closed to unestablished", file=sys.stderr)
            by_num[num] = {"criterion": num, "status": "unestablished",
                           _POISONED: _POISON_TOKEN}
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
        # Both per-side resolutions happen BEFORE the pairing: a criterion absent from
        # one report never voted, and a side that left a charter step undispositioned
        # has not established what it did. Resolving either after the pairing would let
        # an unattested or absent side ride the other verifier's agreement into
        # `satisfied` — the substitution issue #1580 exists to catch.
        e_status, e_reported, e_disp, e_undischarged = _side(
            e_rec, EVIDENCE_SLOTS, "evidence")
        c_status, c_reported, c_disp, c_undischarged = _side(
            c_rec, CLAIM_SLOTS, "claim")
        undischarged = e_undischarged + c_undischarged
        status, evidence, evidence_source = reconcile_one(
            e_status, c_status, _evidence_of(e_rec), _evidence_of(c_rec)
        )
        blocks = status in BLOCKING_STATUSES
        if blocks:
            blocking.append(num)
        # `reason` comes from the evidence side only — it is the sole verifier that
        # runs a command, so a `denied`/`failed` reason is its to report. It is carried
        # only on a blocking criterion (a satisfied one needs no routing refinement).
        reason = _reason_of(e_rec) if blocks else ""
        criteria_out.append(
            {
                "criterion": num,
                "evidence_status": _normalize_status(e_status),
                "claim_status": _normalize_status(c_status),
                "status": status,
                "blocks": blocks,
                "reason": reason,
                "evidence": evidence,
                "evidence_source": evidence_source,
                "evidence_status_reported": _normalize_status(e_reported),
                "claim_status_reported": _normalize_status(c_reported),
                "evidence_dispositions": e_disp,
                "claim_dispositions": c_disp,
                "undischarged_slots": undischarged,
            }
        )

    return {
        "criteria": criteria_out,
        "all_satisfied": len(blocking) == 0 and len(criteria_out) > 0,
        "blocking": blocking,
    }


def _load_report(path):
    """Load one verifier report, accepting either shape the verifiers may emit.

    A verifier prints `{"criteria": [ ... ]}` (its documented output), but the
    orchestrator may hand us the already-unwrapped `criteria` list; accept both so a
    faithful orchestrator is not defeated by which form it happened to write.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and isinstance(data.get("criteria"), list):
        return data["criteria"]
    if isinstance(data, list):
        return data
    raise ValueError(
        f"{path}: expected a JSON list of verifier records, or an object with a "
        f"'criteria' list")


def main(argv=None):
    _force_utf8_streams()
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

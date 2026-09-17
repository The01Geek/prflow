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

The reconciliation takes a third input: the orchestrator's tagged criteria list, whose
per-criterion `class` decides each criterion's *expected sides* — both verifiers for a
`command` criterion, the evidence verifier alone for a `non-command` one. The per-side slot
gate and the status pairing apply only to expected sides, and each record carries a
`missing_sides` list (the expected sides that returned no record) plus a single `remedy`
token the orchestrator routes on. Passing no criteria treats every reported criterion as
`command`, reproducing the pre-#439 two-verifier behavior.

Reconciliation contract (one row per criterion, matched by 1-based `criterion`):

  - `command` criterion — both sides expected:
    - Both verifiers report the SAME status  -> that status is recorded.
    - Any disagreement                        -> `unestablished` is recorded.
    - A criterion present in only one report  -> the missing side is `unestablished`
      (fail closed), so the pair disagrees unless the present side also read
      `unestablished`.
  - `non-command` criterion — evidence side alone expected: the recorded status IS the
    evidence side's status after its slot gate; a claim record present for it is ignored
    (with a stderr breadcrumb) and no claim slot appears in `undischarged_slots`.
  - A criterion in a report but ABSENT from the criteria file, or one poisoned by a duplicate
    listing, has no expected sides -> `unestablished`, `remedy` `judge`, whatever the reports
    say.
  - A reconciled `satisfied` with NO evidence pointer from either verifier is
    downgraded to `unestablished`: a satisfied record never lands without an
    evidence pointer (issue #1575 AC6).
  - A side that left any named step of its own charter undispositioned is forced
    to `unestablished` BEFORE the two statuses are paired (issue #1580), so an
    abbreviated check reconciles `unestablished` rather than riding the other
    verifier's agreement into `satisfied`. A stated `no` discharges its slot
    fully and changes no status by itself — with one exception: an evidence-side
    `command-run: no` under a `satisfied` status is forced to `unestablished` and
    stamped `reason: unexecuted` (issue #350), because a `satisfied` that ran no
    command rests on a read, not an executed and observed command.

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
of the value. A `<slot>=<verdict>` prose spelling is NOT the shape here, and a
value carrying it does not parse.

A verifier record may carry an optional `reason` (the evidence verifier attaches
`denied`/`failed`/`unresolved` to a non-satisfied criterion) which is passed
through on a blocking record, so the orchestrator routes the denied-command case
to its Blocked-naming-`allowed_tools` path from a field, not by sniffing free text.

Output: one JSON object on stdout —
    {"criteria": [ {"criterion", "evidence_status", "claim_status", "status",
                    "blocks", "reason", "remedy", "evidence", "evidence_source",
                    "stated_terms", "observed_value",
                    "evidence_status_reported", "claim_status_reported",
                    "evidence_dispositions", "claim_dispositions",
                    "missing_sides", "undischarged_slots"} ... ],
     "all_satisfied": <bool>, "blocking": [<criterion>, ...]}
The optional `stated_terms`/`observed_value` pair (issue #387) carries the evidence
verifier's recorded criterion terms and the value it observed in the shipped artifact; a
criterion that names a quantifier, scope, or literal value/set is `satisfied` only when they
match, unless the evidence report opts out with `quantified: false`.
The two disposition maps and `undischarged_slots` (side-qualified `<side>:<slot>`)
are carried out so the orchestrator records what each verifier did alongside the
reconciled verdict, rather than letting it die with the dispatch return. The two
`*_status_reported` fields carry what each side concluded BEFORE the slot gate
overrode it, so a criterion blocking on a real `unmet` stays distinguishable from
one blocking only on an attestation gap.

Exit codes:
    0 — reconciliation produced (whether or not any criterion blocks)
    3 — a report file, or the optional `--criteria-file`, was unreadable, not valid JSON, or
        not a bare JSON list
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
EVIDENCE_SLOTS = ("type-decided", "command-run", "claim-traced", "evidence-recorded")
CLAIM_SLOTS = ("claim-traced", "command-source-read", "evidence-recorded")

# The criterion class decides the verifier roster: a `command` criterion is checked by both
# verifiers (the merge script requires their agreement); a `non-command` criterion by the
# evidence verifier alone. An absent, non-string, or out-of-vocabulary class reconciles as
# `command` (the fail-safe default — doubt buys a second vote).
CLASS_VALUES = ("command", "non-command")

# The remedy vocabulary the reconciler emits per criterion, complete by construction; the
# phase prose routes each criterion from its token alone. Do not widen or reorder without the
# matching edit to `_remedy`'s ordered rule list and phase-3-ac-gate.md's routing lines.
REMEDY_VALUES = ("tick", "fix", "restate-evidence", "restate-claim", "rerun-evidence",
                 "rerun-claim", "redispatch-evidence", "blocked-grant", "judge")

# Identity-checked like `_POISON_TOKEN`, never by truthiness: a class value shares the
# criteria-file namespace, so a truthiness test would misclassify a real class or a forged marker.
_POISON_CLASS = object()

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
    (`reconcile` applies one exception on top of this generic parse: an evidence-side
    `command-run: no` under a `satisfied` status is forced to `unestablished` — see
    `_side` and the module docstring — but that is a reconcile-level rule, not a
    property of this parser.)
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
    """Resolve one side into `(status, reported_status, dispositions, undischarged, forced_reason)`.

    `reported_status` is what the side itself concluded, retained even when the slot
    gate overrides `status`. Without it a verifier that reported `unmet` with a real
    failing detail but omitted one slot is indistinguishable from one that concluded
    nothing, and the routing rule that fires only when a criterion blocks SOLELY on
    undischarged slots cannot decide its own precondition.

    `forced_reason` is the reason the reconciler itself stamps when it overrides the
    side's own status — currently only the issue #350 execution-backed downgrade's
    `"unexecuted"`, else `None`. It is threaded out so `reconcile` can give a
    reconciler-stamped reason precedence over any `reason` the record itself carried,
    and so `unexecuted` can never reach the orchestrator except from this stamp.

    Applied symmetrically to both sides so the per-side rules — the fail-closed status
    read for an absent record, and the #1580 downgrade for an undispositioned charter
    step — are stated once rather than mirrored in the caller's loop body; the #350
    execution-backed downgrade below is the one evidence-side-only rule, gated on
    `tag == 'evidence'`, so the claim side never sets `forced_reason`.

    An ABSENT record — and equally a duplicate-poisoned one — reports no undischarged
    slots. Each is a vote the side never usably cast, already blocking on its own;
    naming its slots would send the orchestrator to re-dispatch a verifier to restate a
    record it never made, and would make those causes indistinguishable from a genuine
    attestation gap in the one field that routes the remedy.
    """
    if not isinstance(record, dict) or record.get(_POISONED) is _POISON_TOKEN:
        return "unestablished", "unestablished", {}, [], None
    dispositions, missing = _dispositions_of(record, slots, tag)
    reported = record.get("status")
    status = reported
    forced_reason = None
    if missing:
        status = "unestablished"
        if _normalize_status(reported) != "unestablished":
            print(f"reconcile-ac-verifiers: the {tag} report concluded "
                  f"{_normalize_status(reported)!r} but left {len(missing)} slot(s) "
                  f"undischarged — forcing unestablished; the concluded status is "
                  f"retained as {tag}_status_reported", file=sys.stderr)
    # Execution-backed evidence gate (issue #350): an evidence-side `satisfied` whose
    # `command-run` verdict is `no` ran no command, so force `unestablished` here — before
    # pairing, leaving `missing`/undischarged_slots untouched (re-parse: `stated` dropped it).
    if tag == "evidence" and _normalize_status(reported) == "satisfied":
        verdict, _reason = parse_disposition(dispositions.get("command-run"))
        if verdict == "no":
            status = "unestablished"
            forced_reason = "unexecuted"
            print("reconcile-ac-verifiers: the evidence report concluded 'satisfied' "
                  "but its command-run slot is 'no' (ran no command) — forcing "
                  "unestablished and stamping reason 'unexecuted'; the concluded status "
                  "is retained as evidence_status_reported", file=sys.stderr)
    return (status, reported, dispositions,
            [f"{tag}:{slot}" for slot in missing], forced_reason)


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


def _pair_terms_of(record):
    """Return `(stated_terms, observed_value)` from one evidence record (issue #387).

    Same missing-and-wrong-type discipline as `_evidence_of`: a non-dict record, an
    absent key, or a non-string value reads as `None` (never coerced or defaulted), so a
    malformed report cannot smuggle a comparable pair. The value is NOT stripped — the
    equality the pair rule tests is between the verifier's own recorded strings.
    """
    if not isinstance(record, dict):
        return None, None
    stated = record.get("stated_terms")
    observed = record.get("observed_value")
    return (stated if isinstance(stated, str) else None,
            observed if isinstance(observed, str) else None)


def _quantified_false(record):
    """True only when the record's `quantified` is the JSON boolean `false` (issue #387).

    Identity-checked (`is False`), never by truthiness or `==`, exactly like `_POISON_TOKEN`:
    a JSON string `"false"`, `0`, `null`, or an absent key must NOT skip the pair rule — only
    the parsed JSON boolean does. `0 == False` is True in Python, so an `==` test would let a
    numeric `0` opt out, which the criterion forbids.
    """
    return isinstance(record, dict) and record.get("quantified") is False


def _pair_status(stated, observed):
    """The pair rule's status, complete by construction (issue #387 AC1).

    `unestablished` unless BOTH sides are strings; `satisfied` when they compare equal
    under `==`; `unmet` when both are strings and unequal.
    """
    if not isinstance(stated, str) or not isinstance(observed, str):
        return "unestablished"
    return "satisfied" if stated == observed else "unmet"


# Structured, machine-routable reason the evidence verifier may attach to a
# non-satisfied criterion, so the orchestrator routes the denied-command case to the
# Blocked-naming-`allowed_tools` path from a field rather than by sniffing free text.
# It is a CLOSED vocabulary validated like `status`: an unrecognized value normalizes
# to "" (no reason) rather than passing through, so a consumer may rely on any non-empty
# `reason` being one of these tokens. The criterion still blocks on its `status`;
# `reason` only refines HOW the orchestrator routes the block. `unexecuted` is a member
# of the set (so the orchestrator recognizes it), but it is RECONCILER-STAMPED ONLY: a
# verifier-supplied `unexecuted` is normalized to `unresolved` by `_reason_of` (issue
# #350), so `unexecuted` reaches the orchestrator only from `_side`'s own downgrade stamp.
EVIDENCE_REASONS = ("denied", "failed", "unresolved", "unexecuted")


def _reason_of(record):
    """The record's `reason`, normalized to the closed `EVIDENCE_REASONS` set or "".

    `unexecuted` is reserved for the reconciler's own execution-backed downgrade stamp
    (issue #350): a verifier that supplies it on its own record is normalized to
    `unresolved`, so a forged `unexecuted` can never masquerade as the reconciler's.
    """
    if not isinstance(record, dict):
        return ""
    reason = record.get("reason")
    if not isinstance(reason, str):
        return ""
    normalized = reason.strip().lower()
    if normalized == "unexecuted":
        return "unresolved"
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
        evidence, source = f"{e_ptr}; {c_ptr}", "both"
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


def parse_criteria(entries):
    """Parse the orchestrator-authored tagged-criteria list into `{num: class | _POISON_CLASS}`.

    Fail-closed exactly like `_index_by_criterion`: an entry that is not an object, or whose
    `criterion` is absent/boolean/not-int, is DROPPED with a stderr breadcrumb and contributes
    no expected sides (a report record for that number then reconciles `unestablished`/`judge`
    under the absent-from-criteria-file rule). A `class` that is absent, not a string, or
    outside `CLASS_VALUES` reconciles the criterion as `command` (the fail-safe default). A
    criterion number listed twice is POISONED — it contributes no expected sides and reconciles
    `unestablished`/`judge` whatever its reports say, so a malformed list can never buy a vote.
    """
    class_by_num = {}
    for entry in entries:
        if not isinstance(entry, dict):
            print("reconcile-ac-verifiers: dropping a non-object criteria entry",
                  file=sys.stderr)
            continue
        num = entry.get("criterion")
        if isinstance(num, bool) or not isinstance(num, int):
            print(f"reconcile-ac-verifiers: dropping a criteria entry whose 'criterion' is "
                  f"absent or not an integer ({num!r})", file=sys.stderr)
            continue
        if num in class_by_num:
            print(f"reconcile-ac-verifiers: criterion {num} listed twice in the criteria "
                  f"file — poisoning it (no expected sides)", file=sys.stderr)
            class_by_num[num] = _POISON_CLASS
            continue
        cls = entry.get("class")
        class_by_num[num] = cls if isinstance(cls, str) and cls in CLASS_VALUES else "command"
    return class_by_num


def _expected_sides(cls):
    """The verifier sides a criterion of class `cls` is checked by.

    A poisoned criterion (and, at the call site, one absent from the criteria file) has no
    expected sides. `non-command` is the evidence verifier alone; `command` (and the fail-safe
    default) is both. Returned in a fixed order so `missing_sides` never needs sorting.
    """
    if cls is _POISON_CLASS:
        return ()
    if cls == "non-command":
        return ("evidence",)
    return ("evidence", "claim")


def _load_criteria(path):
    """Load the orchestrator-authored tagged-criteria file — a BARE JSON list only.

    Unlike `_load_report`, the `{"criteria": [...]}` envelope the verifier reports use is NOT
    accepted here: the orchestrator authors this file, so a wrapped envelope is a malformed
    input, not a faithful alternate shape. A non-list top-level value raises (the caller maps
    it to exit 3), matching `_load_report`'s fail-closed unreadable-report arm.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a bare JSON list of tagged criteria (the wrapped "
            f"'{{\"criteria\": [...]}}' envelope is not accepted here)")
    return data


def _remedy(status, reason, expected, e_reported, c_reported, missing_sides, undischarged):
    """The single `remedy` token for one reconciled criterion.

    Derived in this order, first matching rule winning — the ordered rule list of AC9.
    `expected` scopes rules 3 and 6 to the criterion's own verifier roster, so a
    non-command criterion is never routed on a claim side it never had. Rules 4 and 6 emit the
    evidence-side token when both sides qualify; once that side is re-run, the next
    reconciliation emits the claim-side token (the side has dropped out of the qualifying set).
    """
    reported = {"evidence": e_reported, "claim": c_reported}
    if status == "satisfied":                                              # 1
        return "tick"
    if reason == "denied":                                                 # 2
        return "blocked-grant"
    if any(reported[s] == "unmet" for s in expected):                      # 3
        return "fix"
    if missing_sides:                                                      # 4
        return "rerun-evidence" if "evidence" in missing_sides else "rerun-claim"
    if reason == "unexecuted":                                             # 5
        return "redispatch-evidence"
    if undischarged and expected and all(                                  # 6
            reported[s] == "satisfied" for s in expected):
        return ("restate-evidence" if any(u.startswith("evidence:") for u in undischarged)
                else "restate-claim")
    return "judge"                                                         # 7


def reconcile(evidence_records, claim_records, criteria=None):
    """Reconcile two full verifier reports into the record the orchestrator routes on.

    `criteria` is the tagged criteria list's parsed `{num: class | _POISON_CLASS}` map (from
    `parse_criteria`). `None` is the back-compatible default: every criterion appearing in
    either report is treated as `command` (both sides expected), reproducing the pre-#439
    two-verifier reconciliation for callers that pass no criteria.
    """
    e_by = _index_by_criterion(evidence_records, "evidence")
    c_by = _index_by_criterion(claim_records, "claim")
    if criteria is None:
        class_by_num = {num: "command" for num in set(e_by) | set(c_by)}
    else:
        class_by_num = criteria

    criteria_out = []
    blocking = []
    for num in sorted(set(class_by_num) | set(e_by) | set(c_by)):
        e_rec = e_by.get(num)
        c_rec = c_by.get(num)
        in_criteria = num in class_by_num
        expected = _expected_sides(class_by_num.get(num)) if in_criteria else ()

        # missing_sides comes from record PRESENCE (never disposition contents): an absent
        # record and a present-but-empty one both reach `_side` with no slots, and only
        # presence tells the orchestrator a side owes a re-run rather than a restatement.
        missing_sides = [s for s in expected
                         if (e_rec if s == "evidence" else c_rec) is None]

        # Resolve only the EXPECTED sides through the slot gate; an unexpected side stays
        # inert (contributes no status, no slots). A present claim record on a `non-command`
        # criterion is ignored with a breadcrumb naming the criterion (AC6).
        if "evidence" in expected:
            e_status, e_reported, e_disp, e_undischarged, e_forced_reason = _side(
                e_rec, EVIDENCE_SLOTS, "evidence")
        else:
            e_status, e_reported, e_disp, e_undischarged, e_forced_reason = (
                "unestablished", "unestablished", {}, [], None)
        if "claim" in expected:
            c_status, c_reported, c_disp, c_undischarged, _c_forced_reason = _side(
                c_rec, CLAIM_SLOTS, "claim")
        else:
            if class_by_num.get(num) == "non-command" and c_rec is not None:
                print(f"reconcile-ac-verifiers: criterion {num} is non-command; ignoring "
                      f"the claim report present for it", file=sys.stderr)
            c_status, c_reported, c_disp, c_undischarged = (
                "unestablished", "unestablished", {}, [])
        undischarged = e_undischarged + c_undischarged

        if not expected:
            # Absent from the criteria file, or poisoned: no expected sides, so nothing is
            # reconciled from the reports — force `unestablished`, and `_remedy` routes `judge`.
            status, evidence, evidence_source = "unestablished", "", ""
        elif "claim" not in expected:
            # Single-side (`non-command`): the reconciled status IS the evidence side's status
            # after its slot gate; the evidence pointer, if any, is carried through. The AC6
            # no-evidence downgrade (docstring lines 38-40) is a GLOBAL invariant, not a
            # command-only one: a satisfied non-command record with no evidence pointer would
            # otherwise tick with no evidence, so it fails closed to `unestablished` here exactly
            # as reconcile_one does for the command path.
            status = e_status
            evidence = _evidence_of(e_rec)
            evidence_source = "evidence" if evidence else ""
            if status == "satisfied" and not evidence:
                status, evidence_source = "unestablished", ""
        else:
            # `command`: today's two-verifier pairing (agreement, disagreement→unestablished,
            # satisfied-without-evidence→unestablished).
            status, evidence, evidence_source = reconcile_one(
                e_status, c_status, _evidence_of(e_rec), _evidence_of(c_rec))

        # Stated/observed pair rule (issue #387): for a criterion that names a quantifier,
        # a scope, or a literal value/set, the evidence verifier records the criterion's own
        # `stated_terms` and the `observed_value` it saw in the shipped artifact, and `status`
        # is set from their match — so an evidence pointer plus a fit judgment with no recorded
        # match is not `satisfied`. It runs AFTER the pointer/slot pairing above and reads only
        # the evidence record, so it applies identically on the command and non-command paths.
        # Gated on `expected`: a criterion with no legitimate verifier roster (poisoned or
        # absent from the criteria file) keeps its fail-closed `unestablished` and is never
        # turned `satisfied` by a coincidental pair match. Skipped only when the evidence report
        # opts out with `quantified: false`.
        # Tightening-only (issue #387): a recorded stated_terms/observed_value match is
        # NECESSARY for a quantified criterion but never SUFFICIENT. A non-matching pair
        # downgrades an otherwise-`satisfied` status toward blocking; a matching pair must
        # never mint `satisfied` from a status the pointer/slot pairing above already
        # resolved non-satisfied (a claim-verifier disagreement, an unexecuted command, or an
        # undischarged slot), so one side's coincidental value match cannot override the
        # two-verifier cross-check. A `satisfied` status here already carries an evidence
        # pointer (the AC6 no-evidence downgrade ran on the command and non-command branches
        # above), so the retained pointer stays valid on a downgrade. `_pair_status` is pure, so computing it
        # unconditionally is free and keeps this a single flat guard.
        stated_terms, observed_value = _pair_terms_of(e_rec)
        pair_status = _pair_status(stated_terms, observed_value)
        if (expected and not _quantified_false(e_rec)
                and status == "satisfied" and pair_status != "satisfied"):
            status = pair_status

        blocks = status in BLOCKING_STATUSES
        if blocks:
            blocking.append(num)
        # `reason` comes from the evidence side only (the sole command-runner), and only when
        # that side is expected and the criterion blocks; a reconciler stamp (`e_forced_reason`)
        # wins over the record's own `reason` (issue #350).
        reason = ((e_forced_reason or _reason_of(e_rec))
                  if blocks and "evidence" in expected else "")
        remedy = _remedy(status, reason, expected,
                         _normalize_status(e_reported), _normalize_status(c_reported),
                         missing_sides, undischarged)
        criteria_out.append(
            {
                "criterion": num,
                "evidence_status": _normalize_status(e_status),
                "claim_status": _normalize_status(c_status),
                "status": status,
                "blocks": blocks,
                "reason": reason,
                "remedy": remedy,
                "evidence": evidence,
                "evidence_source": evidence_source,
                "stated_terms": stated_terms,
                "observed_value": observed_value,
                "evidence_status_reported": _normalize_status(e_reported),
                "claim_status_reported": _normalize_status(c_reported),
                "evidence_dispositions": e_disp,
                "claim_dispositions": c_disp,
                "missing_sides": missing_sides,
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
    parser.add_argument("--criteria-file", default=None,
                        help="optional tagged-criteria list (a bare JSON list); absent means "
                             "every reported criterion is treated as class 'command'")
    args = parser.parse_args(argv)

    try:
        evidence_records = _load_report(args.evidence_file)
        claim_records = _load_report(args.claim_file)
        criteria = (parse_criteria(_load_criteria(args.criteria_file))
                    if args.criteria_file is not None else None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Fail closed and name the cause: an unreadable/malformed report or criteria file is
        # an unestablished measurement, never a silently-empty (and therefore
        # trivially-passing) reconciliation.
        print(f"reconcile-ac-verifiers: could not read a verifier report or the criteria "
              f"file: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(reconcile(evidence_records, claim_records, criteria), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

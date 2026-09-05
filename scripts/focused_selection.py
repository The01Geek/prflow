#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""The focused-first selection record — a named, round-trippable producer/reader
(issue #1229).

A run's focused-first precondition (`.prflow/skill-extensions/{implement,
review-and-fix,fix}.md`) asks the run to *establish*, per touched
surface, either the discharging focused test it selected (the coverage-map entry it
consulted and the target it ran) or the exemption ground that applied, and to record
whether the `scripts/verification-flight.py` single flight was consulted before a
full-suite relaunch. Those rules named no sink, so a followed rule and an ignored one
left identical traces. This module is that record's shape: a single serializer both
sinks share.

The two sinks (named by the prompt extensions, not by this module):
  * An implement run records the marker `encode_marker` emits as a `## Progress`
    note through `scripts/workpad.py` — a machine-parseable named record, not free
    prose in a general-purpose field.
  * A standalone fix loop stores the plain dict `build_record` returns as the
    `focused_selection` field of the iteration record `iter-<N>.json`'s
    `verification_evidence` object (see `skills/review-and-fix/references/fixing.md`).

The record is deliberately a *record of what the run did*, never a launch counter, a
launch ordinal, or a changed-file-to-module routing table — those remain prohibited
by the prompt extensions (issue #1229 AC7). Nothing in this module derives the
touched-surface set; the caller supplies it.

python3 standard library only; no third-party imports.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys

# The named marker literal. Only the current `prflow:` spelling is minted (this
# record postdates the issue #1003 marker-namespace rename). The payload is a
# base64-encoded JSON object, so an arbitrary coverage-map path or module id in the
# record can never smuggle a `-->` and terminate the HTML comment early.
MARKER_PREFIX = "prflow:focused-selection"
_MARKER_RE = re.compile(
    r"<!--\s*" + re.escape(MARKER_PREFIX) + r"\s+([A-Za-z0-9+/=]+)\s*-->"
)

# The two per-surface entry shapes.
ENTRY_FOCUSED_RESULT = "focused-result"
ENTRY_EXEMPTION = "exemption"

# The record's top-level keys. `build_record` emits BOTH of them on every path (see
# its docstring: `single_flight_consulted` is always present, defaulting to null), so
# a reader may require both — that is the point of requiring them, since a record
# missing one did not come from this producer. On the *stdin* side of `encode` only
# `surfaces` is required; `single_flight_consulted` may be omitted and defaults to
# null, which is the recorded value meaning "no relaunch consultation to record".
RECORD_REQUIRED_KEYS = ("surfaces",)
RECORD_OPTIONAL_KEYS = ("single_flight_consulted",)
RECORD_KEYS = RECORD_REQUIRED_KEYS + RECORD_OPTIONAL_KEYS

# The two `decode_marker_outcomes` statuses. A malformed marker is *reported*, never
# silently indistinguishable from text that carried no marker at all (unknown is not
# zero): "no marker occurrence" is the empty outcome list, "a marker that is not a
# record" is a `malformed` outcome carrying its reason.
MARKER_STATUS_RECORD = "record"
MARKER_STATUS_MALFORMED = "malformed"


def classify_entry(entry: dict) -> str:
    """Classify one per-surface entry as a discharging focused result or an
    exemption ground. Raises ValueError on an entry that is neither, and equally on
    one that is ambiguously both (an unclassifiable surface must never be recorded
    silently — the whole point of the record is that a discharged surface and an
    exempt surface are distinguishable)."""
    if not isinstance(entry, dict) or not entry.get("surface"):
        raise ValueError("a focused-selection surface entry must name a `surface`")
    has_focused = bool(entry.get("coverage_map_entry")) and bool(entry.get("target"))
    has_exemption = bool(entry.get("exemption_ground"))
    if has_focused and not has_exemption:
        return ENTRY_FOCUSED_RESULT
    if has_exemption and not has_focused:
        return ENTRY_EXEMPTION
    raise ValueError(
        f"focused-selection entry for {entry.get('surface')!r} is neither a "
        f"discharging focused result (coverage_map_entry + target) nor an exemption "
        f"(exemption_ground), or is ambiguously both"
    )


def build_record(surfaces, single_flight_consulted=None) -> dict:
    """Build the canonical focused-selection record.

    `surfaces` is a list of per-surface entries; each is validated by
    `classify_entry` and normalized to only the fields its shape carries, so a
    round-tripped record is byte-stable (`encode_marker` also sorts keys).
    `single_flight_consulted` is either None (there was no relaunch consultation to
    record) or a JSON-serializable object recording one (AC4) — a *non-None value*
    marks that a consultation was recorded, and its caller-defined internal shape says
    what happened (e.g. whether an existing clean result was reused rather than
    re-produced). The key itself is always present, defaulting to null, so a reader
    tests its value and never merely its presence. Returns a plain dict — the value
    stored verbatim as `verification_evidence.focused_selection` in the standalone
    sink."""
    if not isinstance(surfaces, list):
        raise ValueError("surfaces must be a list of per-surface entries")
    normalized = []
    for entry in surfaces:
        kind = classify_entry(entry)  # raises on an unclassifiable entry
        if kind == ENTRY_FOCUSED_RESULT:
            normalized.append({
                "surface": entry["surface"],
                "coverage_map_entry": entry["coverage_map_entry"],
                "target": entry["target"],
            })
        else:
            normalized.append({
                "surface": entry["surface"],
                "exemption_ground": entry["exemption_ground"],
            })
    return {
        "surfaces": normalized,
        "single_flight_consulted": single_flight_consulted,
    }


def encode_marker(record: dict) -> str:
    """Serialize a record into the named marker string. The JSON is base64-encoded so
    no record content can terminate the HTML comment, and the *payload* needs no shell
    quoting. The returned marker as a whole still does — it carries `<`, `>`, `!` and
    spaces — so a caller passing it to a shell quotes the whole string."""
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload = base64.b64encode(raw).decode("ascii")
    return f"<!-- {MARKER_PREFIX} {payload} -->"


def record_shape_error(obj) -> str | None:
    """Validate a decoded payload against the record shape and return `None` when it
    is a well-shaped record, else a one-line reason it is not.

    This *validates without normalizing*: it never rebuilds, reorders, or drops a
    field, so a record that passes is returned to the caller byte-for-byte as the
    producer wrote it. (Routing a decoded object through `build_record` would instead
    rewrite it — that function normalizes each entry to only the fields its shape
    carries — which would make this read path lossy rather than checked.)

    What is required is exactly what `build_record` guarantees: both top-level keys
    present, `surfaces` a list, and every entry classifiable by `classify_entry` as
    one shape or the other. Unrecognized keys — top-level or per-entry — are
    deliberately *tolerated here*, on the read path only: a marker already sitting in
    a consumer's workpad may have been written by a later producer that records an
    additional field, and rejecting it would lose a record that is otherwise entirely
    valid. The `encode` producer path is strict about unknown keys instead, where an
    unrecognized key means this run composed the record wrongly and nothing has been
    persisted yet."""
    if not isinstance(obj, dict):
        return f"payload is a JSON {type(obj).__name__}, not an object"
    missing = [k for k in RECORD_KEYS if k not in obj]
    if missing:
        return ("object is missing the record key(s) "
                + ", ".join(repr(k) for k in missing))
    if not isinstance(obj["surfaces"], list):
        return (f"record's `surfaces` is a {type(obj['surfaces']).__name__}, "
                f"not a list")
    for i, entry in enumerate(obj["surfaces"]):
        try:
            classify_entry(entry)
        except ValueError as e:
            return f"record's surfaces[{i}] is not a valid entry: {e}"
    return None


def decode_marker_outcomes(text: str) -> list:
    """Read `text` (a workpad body, a note, or any string) and report ONE outcome per
    focused-selection marker occurrence, in document order. Each outcome is a dict:

      * `{"status": "record", "record": <the decoded record>, "reason": None}`
      * `{"status": "malformed", "record": None, "reason": "<why>"}`

    The empty list means the text carried **no marker occurrence at all**. That is a
    different fact from "a marker was present but was not a record", which is a
    `malformed` outcome carrying its reason, and different again from a real record
    whose `single_flight_consulted` the producer recorded as null — an unestablished
    shape is never collapsed onto a valid empty one."""
    out = []
    for m in _MARKER_RE.finditer(text or ""):
        try:
            raw = base64.b64decode(m.group(1), validate=True)
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            out.append({"status": MARKER_STATUS_MALFORMED, "record": None,
                        "reason": f"payload did not decode: {e}"})
            continue
        err = record_shape_error(obj)
        if err is None:
            out.append({"status": MARKER_STATUS_RECORD, "record": obj,
                        "reason": None})
        else:
            out.append({"status": MARKER_STATUS_MALFORMED, "record": None,
                        "reason": err})
    return out


def decode_markers(text: str) -> list:
    """Read every focused-selection record carried by `text`. Returns the list of
    decoded record dicts in document order — and **only well-shaped records**, so a
    caller may index `rec["surfaces"]` and test `rec["single_flight_consulted"]`
    without a `KeyError` and without mistaking an absent key for a recorded null.

    A marker whose payload does not decode (bad base64, non-JSON, non-object) *or*
    decodes to an object that is not a record is excluded here — fail closed toward
    "no record" rather than surfacing a spurious one. Because it is excluded, the
    empty list here means "no well-shaped record", which is NOT the same fact as "no
    marker was present": `decode_marker_outcomes` is the reader that tells those two
    apart and names why a marker was rejected."""
    return [o["record"] for o in decode_marker_outcomes(text)
            if o["status"] == MARKER_STATUS_RECORD]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="focused_selection.py",
        description="Encode/decode the focused-first selection record (issue #1229).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encode", help="Read a record JSON object from stdin and "
                                        "print its named marker.")
    enc.set_defaults(func=_cmd_encode)
    dec = sub.add_parser("decode", help="Read text from stdin and print the JSON "
                                        "array of records it carries.")
    dec.set_defaults(func=_cmd_decode)
    return p


def _cmd_encode(_args) -> int:
    # Every rejection on this path exits through SystemExit with a one-line message,
    # so unparseable stdin and an unclassifiable surface entry fail the same loud,
    # readable way as the non-object guard below rather than as a raw traceback.
    try:
        obj = json.loads(sys.stdin.read())
    except ValueError as e:
        raise SystemExit(f"encode could not parse stdin as JSON: {e}") from e
    if not isinstance(obj, dict):
        raise SystemExit("encode expects a JSON object on stdin (with a `surfaces` "
                         "list and an optional `single_flight_consulted`)")
    # An unrecognized top-level key is a caller error, not a field to ignore: a
    # misspelled `surfaces` would otherwise default to `[]` and a misspelled
    # `single_flight_consulted` to null, so a run that followed the rule and a run
    # that ignored it would emit the same valid-looking marker — the exact collapse
    # this record exists to prevent. Reject loudly instead.
    unknown = sorted(k for k in obj if k not in RECORD_KEYS)
    if unknown:
        raise SystemExit(
            "encode rejected the record: unrecognized top-level key(s) "
            + ", ".join(repr(k) for k in unknown)
            + "; accepted keys are "
            + ", ".join(repr(k) for k in RECORD_KEYS))
    # A MISSING `surfaces` is rejected for the same reason, so an empty record must
    # say so explicitly (`{"surfaces": []}` — "nothing was selected") and cannot be
    # produced by a caller that simply supplied nothing. `single_flight_consulted`
    # stays OPTIONAL and defaults to null, which is its recorded value meaning "no
    # relaunch consultation to record"; `build_record` always emits the key.
    missing = [k for k in RECORD_REQUIRED_KEYS if k not in obj]
    if missing:
        raise SystemExit(
            "encode rejected the record: stdin object is missing the required key(s) "
            + ", ".join(repr(k) for k in missing)
            + "; an empty record states it explicitly as {\"surfaces\": []}")
    try:
        rec = build_record(obj["surfaces"], obj.get("single_flight_consulted"))
    except ValueError as e:
        raise SystemExit(f"encode rejected the record: {e}") from e
    sys.stdout.write(encode_marker(rec) + "\n")
    return 0


def _cmd_decode(_args) -> int:
    # stdout stays the JSON array of well-shaped records — the contract a caller
    # parses. A marker that was present but is not a record is excluded from that
    # array, so it is breadcrumbed to stderr rather than vanishing: on stdout alone a
    # rejected marker and an absent one would look identical. Reading is best-effort,
    # so this stays exit 0.
    outcomes = decode_marker_outcomes(sys.stdin.read())
    for o in outcomes:
        if o["status"] == MARKER_STATUS_MALFORMED:
            sys.stderr.write(
                f"focused-selection: skipped a malformed marker ({o['reason']})\n")
    sys.stdout.write(json.dumps([o["record"] for o in outcomes
                                 if o["status"] == MARKER_STATUS_RECORD]) + "\n")
    return 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Evidence-bundle assembly for the two-core pilot (issue #420, Stage A).

Internal dev-only pilot harness helper (vendors with the rest of lib/, but no
shipped skill or workflow invokes it). The pure ``build_evidence_bundle``
assembles one arm's measurement into a single
dict and stamps every top-level entry with an ``evidence_kind`` of ``live``,
``fixture``, or ``dry-run``. That tag is the machine-legible device that keeps
Stage A's fixtures and dry runs out of any "measured" result: the comparison
calculator refuses to compute a real comparison from a non-``live`` bundle, and
that refusal is unit-tested. Nothing here dispatches CI or reads live state; it
consumes recorded sampler output and the request/run/attempt identity files that
``scripts/ci-verification-request.py collect-evidence`` already produces.
"""
from __future__ import annotations

import sys

VALID_EVIDENCE_KINDS = ("live", "fixture", "dry-run")


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a unit
    test importing this module never mutates the importer's streams). A stream replaced
    with a non-TextIOWrapper (a test's io.StringIO) has no reconfigure and is tolerated."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def build_evidence_bundle(
    arm: str,
    evidence_kind: str,
    *,
    sampler_summary: dict | None = None,
    ci_identity: dict | None = None,
    timings: dict | None = None,
    runner_cost: list[dict] | None = None,
    claude_execution: dict | None = None,
    request_identity: dict | None = None,
    completion_evidence: dict | None = None,
    diagnostics: dict | None = None,
    missing: dict[str, str] | None = None,
) -> dict:
    """Assemble one arm's evidence bundle, tagging every entry with evidence_kind.

    ``arm`` is ``offload`` or ``control``. ``evidence_kind`` must be one of
    VALID_EVIDENCE_KINDS — an unrecognised value raises ValueError rather than
    letting a trust-ambiguous bundle through. Each supplied component is echoed
    under its own key with the bundle-level ``evidence_kind`` repeated on it, so
    a reader inspecting one component still sees the provenance tag.

    The additive components (issue #458) extend, never rewrite, the bundle:
    ``claude_execution`` (the native Claude execution record), ``request_identity``
    (candidate/request/run/attempt identities), ``completion_evidence`` (final
    completion/shard evidence), and ``diagnostics`` are each tagged like the
    original components. ``missing`` maps a component name to a non-empty reason it
    is absent (a failed/interrupted attempt) — it is metadata about absence, not
    evidence, so it is stored verbatim and NOT stamped with ``evidence_kind``.
    """
    if arm not in ("offload", "control"):
        raise ValueError(f"unknown arm {arm!r}; expected 'offload' or 'control'")
    if evidence_kind not in VALID_EVIDENCE_KINDS:
        raise ValueError(
            f"unknown evidence_kind {evidence_kind!r}; expected one of {VALID_EVIDENCE_KINDS}"
        )
    bundle: dict = {"arm": arm, "evidence_kind": evidence_kind}
    if sampler_summary is not None:
        bundle["sampler"] = {**sampler_summary, "evidence_kind": evidence_kind}
    if ci_identity is not None:
        bundle["ci_identity"] = {**ci_identity, "evidence_kind": evidence_kind}
    if timings is not None:
        bundle["timings"] = {**timings, "evidence_kind": evidence_kind}
    if runner_cost is not None:
        bundle["runner_cost"] = [{**entry, "evidence_kind": evidence_kind} for entry in runner_cost]
    if claude_execution is not None:
        bundle["claude_execution"] = {**claude_execution, "evidence_kind": evidence_kind}
    if request_identity is not None:
        bundle["request_identity"] = {**request_identity, "evidence_kind": evidence_kind}
    if completion_evidence is not None:
        bundle["completion_evidence"] = {**completion_evidence, "evidence_kind": evidence_kind}
    if diagnostics is not None:
        bundle["diagnostics"] = {**diagnostics, "evidence_kind": evidence_kind}
    if missing:
        if not all(isinstance(reason, str) and reason for reason in missing.values()):
            raise ValueError("every `missing` entry must carry a non-empty string reason")
        bundle["missing"] = dict(missing)
    return bundle


def is_live(bundle: dict) -> bool:
    """True only when the bundle's top-level evidence_kind is exactly 'live'."""
    return bundle.get("evidence_kind") == "live"


def classify_attempt(execution_data, *, load_error: str | None = None) -> dict:
    """Classify a pilot attempt from the native execution record's ``num_turns``.

    A zero-turn / no-implementation attempt is an unsuccessful SETUP, not pilot
    success (issue #458). Returns ``{setup_status, reason, num_turns}`` where
    ``setup_status`` is one of ``unsuccessful-setup`` / ``attempted-turns-unknown``
    / ``attempted``. ``load_error`` is a non-empty reason string when the record
    could not be loaded (absent/unreadable) — kept a pure argument (not an I/O
    call) so the classification is unit-testable in isolation. This is the decision
    logic the pilot workflow step invokes; the step itself is thin I/O glue.
    """
    if load_error:
        return {"setup_status": "unsuccessful-setup", "reason": load_error, "num_turns": None}
    if execution_data is None:
        return {"setup_status": "unsuccessful-setup", "reason": "no execution file", "num_turns": None}
    num_turns = None
    if isinstance(execution_data, dict):
        num_turns = execution_data.get("num_turns")
    elif execution_data and isinstance(execution_data, list) and isinstance(execution_data[-1], dict):
        num_turns = execution_data[-1].get("num_turns")
    if num_turns is None:
        return {"setup_status": "attempted-turns-unknown",
                "reason": "num_turns absent from execution record", "num_turns": None}
    # bool is an int subclass; exclude it so a stray True/False is not read as a turn count.
    if isinstance(num_turns, bool) or not isinstance(num_turns, int):
        return {"setup_status": "attempted-turns-unknown",
                "reason": f"num_turns is not an integer: {num_turns!r}", "num_turns": num_turns}
    if num_turns == 0:
        return {"setup_status": "unsuccessful-setup",
                "reason": "num_turns=0 (zero-turn abort signature)", "num_turns": 0}
    return {"setup_status": "attempted", "reason": "", "num_turns": num_turns}


def rows_cover_descendants(lines) -> bool:
    """Return True once a sampled row set holds more than the root alone.

    Reads the sampler's timestamped JSONL rows (``--rows-path``), whose ``rows`` field
    is the root's process TREE (root + descendants) — so more than one row proves the
    sampled root actually had descendants, the root-to-implementation-tree connection
    AC3 requires. This is correct only because the sampler retains the tree, not the
    whole ps table (issue #458 review). Fails safe toward ``False`` (no proven
    coverage) on an unparseable line rather than raising.
    """
    import json as _json

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        rows = rec.get("rows") or []
        if len(rows) > 1:
            return True
    return False


def _write_json_atomic(path: str, obj) -> None:
    """Write JSON to path via a temp file + os.replace so a reader (the upload step) never
    sees a partial evidence artifact, mirroring the sampler's summary write (issue #458)."""
    import json
    import os

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _main(argv=None) -> int:
    import argparse
    import json
    import os

    _force_utf8_streams()
    parser = argparse.ArgumentParser(description="Pilot attempt/coverage evidence classifier.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("classify-attempt")
    pa.add_argument("--execution-file", default="")
    pa.add_argument("--arm", required=True)
    pa.add_argument("--out", required=True)
    pc = sub.add_parser("coverage")
    pc.add_argument("--rows", required=True)
    pc.add_argument("--arm", required=True)
    pc.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "classify-attempt":
        data, load_error = None, None
        ef = args.execution_file
        if not ef or not os.path.isfile(ef):
            load_error = "no execution file"
        else:
            try:
                with open(ef, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as exc:
                load_error = f"execution file unreadable: {exc}"
        result = classify_attempt(data, load_error=load_error)
        result["arm"] = args.arm
        _write_json_atomic(args.out, result)
        return 0

    # Single open attempt (no isfile-then-open TOCTOU): rows_file_present is set from whether
    # the read succeeded, distinguishing a genuine no-descendants observation from an absent
    # rows file (e.g. the sampler was SIGKILLed before writing) — both otherwise read False.
    lines: list[str] = []
    rows_file_present = False
    try:
        with open(args.rows, encoding="utf-8") as handle:
            lines = handle.readlines()
        rows_file_present = True
    except OSError:
        rows_file_present = False
    _write_json_atomic(
        args.out,
        {
            "arm": args.arm,
            "covered_later_step_descendant": rows_cover_descendants(lines),
            "rows_file_present": rows_file_present,
        },
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))

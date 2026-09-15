#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Foreground deadline/reattachment exercise validator (issue #420, Stage A).

Internal dev-only pilot harness helper (vendors with the rest of lib/, but no
shipped skill or workflow invokes it). The offload arm's CI wait must, while CI
is still pending, hit its foreground
deadline (``ci-verification-request.py wait`` exit 3 = PENDING), then reattach to
the SAME request/run without dispatching another suite, and only complete on
eventual validated passing evidence (exit 0). Stage A validates a scripted
response sequence offline — a deliberately-labelled scripted-recovery fixture,
never a live run — asserting the reattach contract holds over it.
"""
from __future__ import annotations

import json
from pathlib import Path


def assert_reattach_sequence(sequence: list[dict]) -> dict:
    """Assert a scripted deadline→reattach→pass sequence satisfies the contract.

    ``sequence`` is the recorded list of ``ci-verification-request.py wait``
    attempts, each ``{"exit_code", "request_id", "run_id", "dispatched"}``
    (``dispatched`` True only when that attempt dispatched a fresh suite). All
    conjuncts required:

    1. at least two attempts (a deadline hit then a reattach);
    2. the first attempt exits 3 (PENDING at the deadline);
    3. every attempt shares one request_id and one run_id (reattach targets the
       same request/run, never a new one);
    4. exactly one attempt dispatched a suite (reattaches never re-dispatch);
    5. the final attempt exits 0 (validated passing evidence).

    Returns ``{"ok": True, ...}`` when all hold, else ``{"ok": False, "reason": ...}``.
    """
    if len(sequence) < 2:
        return {"ok": False, "reason": "sequence must hold at least a deadline hit and a reattach"}
    if sequence[0].get("exit_code") != 3:
        return {"ok": False, "reason": f"first attempt exit {sequence[0].get('exit_code')}, expected 3 (PENDING)"}
    request_ids = {a.get("request_id") for a in sequence}
    run_ids = {a.get("run_id") for a in sequence}
    # Reject absent identity too: an all-None request_id/run_id collapses to a single-element
    # {None} set that would otherwise pass the "one identity" check vacuously.
    if None in request_ids or None in run_ids:
        return {"ok": False, "reason": "reattach identity absent: a request_id/run_id is missing"}
    if len(request_ids) != 1 or len(run_ids) != 1:
        return {"ok": False, "reason": f"reattach changed identity: request_ids={request_ids} run_ids={run_ids}"}
    dispatch_count = sum(1 for a in sequence if a.get("dispatched"))
    if dispatch_count != 1:
        return {"ok": False, "reason": f"expected exactly 1 suite dispatch, saw {dispatch_count}"}
    if sequence[-1].get("exit_code") != 0:
        return {"ok": False, "reason": f"final attempt exit {sequence[-1].get('exit_code')}, expected 0 (PASSED)"}
    return {
        "ok": True,
        "attempts": len(sequence),
        "dispatches": dispatch_count,
        "note": "scripted-recovery fixture only; not live CI evidence (Stage A preparation)",
    }


def load_sequence(path) -> list[dict]:
    """Read a scripted reattach sequence from a JSON fixture file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))

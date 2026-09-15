#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Comparison calculations for the two-core pilot (issue #420, Stage A).

Internal dev-only pilot harness helper (vendors with the rest of lib/, but no
shipped skill or workflow invokes it). Pure functions computing the
trigger-to-final-green time (with queue / execution /
waiting breakdown) and total runner cost for each arm, plus the delta between
them. The calculator NEVER fabricates a measured number from non-live evidence:
if either arm's bundle is not tagged ``evidence_kind == "live"`` (or a required
timing/cost field is missing), it returns an explicit ``{"inconclusive": {...}}``
naming the missing measurement — the Stage-A-testable proof of the issue's own
"insufficient evidence produces an explicit inconclusive recommendation" rule.
"""
from __future__ import annotations

_REQUIRED_TIMING_FIELDS = (
    "trigger_ts",
    "final_green_ts",
    "queue_seconds",
    "execution_seconds",
    "waiting_seconds",
)


def _is_live(bundle: dict) -> bool:
    # Standalone copy of pilot-evidence-collector.is_live: these modules load via
    # importlib.spec_from_file_location in tests, so a cross-module import would
    # not resolve. The one-line predicate is duplicated rather than shared.
    return bundle.get("evidence_kind") == "live"


def _inconclusive(reason: str) -> dict:
    return {"inconclusive": {"reason": reason}}


def _arm_metrics(bundle: dict) -> dict:
    timings = bundle["timings"]
    total_cost = 0.0
    breakdown: list[dict] = []
    for entry in bundle.get("runner_cost", []):
        minutes = float(entry["minutes"])
        rate = float(entry["rate_usd_per_min"])
        cost = minutes * rate
        breakdown.append(
            {"job": entry["job"], "minutes": minutes, "rate_usd_per_min": rate, "cost_usd": cost}
        )
        total_cost += cost
    return {
        "trigger_to_final_green_seconds": float(timings["final_green_ts"]) - float(timings["trigger_ts"]),
        "queue_seconds": float(timings["queue_seconds"]),
        "execution_seconds": float(timings["execution_seconds"]),
        "waiting_seconds": float(timings["waiting_seconds"]),
        "total_runner_cost_usd": total_cost,
        "cost_breakdown": breakdown,
    }


def compute_comparison(control: dict, offload: dict) -> dict:
    """Compare the control and offload arms, or return an inconclusive verdict.

    Fails closed toward inconclusive: any non-live arm, a missing ``timings``
    block, a missing required timing field, or an empty ``runner_cost`` (no
    billed runner data) yields ``{"inconclusive": {"reason": ...}}`` naming the
    gap — never a computed savings figure ("Missing billing data leaves this
    criterion unmet; estimates ... are not billed runner savings.").
    """
    for name, bundle in (("control", control), ("offload", offload)):
        if not _is_live(bundle):
            return _inconclusive(
                f"{name} arm evidence_kind is {bundle.get('evidence_kind')!r}, not 'live' — "
                "fixtures and dry runs are not measured results"
            )
        if "timings" not in bundle:
            return _inconclusive(f"{name} arm has no timings block")
        if not isinstance(bundle["timings"], dict):
            return _inconclusive(f"{name} arm timings is not a mapping")
        for field in _REQUIRED_TIMING_FIELDS:
            if field not in bundle["timings"]:
                return _inconclusive(f"{name} arm timings missing required field {field!r}")
            try:
                float(bundle["timings"][field])
            except (TypeError, ValueError):
                return _inconclusive(
                    f"{name} arm timings field {field!r} is non-numeric"
                )
        if not bundle.get("runner_cost"):
            return _inconclusive(
                f"{name} arm has no runner_cost entries — missing billing data leaves "
                "the cost comparison unmet"
            )
        if not isinstance(bundle["runner_cost"], list):
            return _inconclusive(f"{name} arm runner_cost is not a list")
        for entry in bundle["runner_cost"]:
            if not isinstance(entry, dict):
                return _inconclusive(f"{name} arm has a non-object runner_cost entry")
            if not all(k in entry for k in ("job", "minutes", "rate_usd_per_min")):
                return _inconclusive(
                    f"{name} arm has a runner_cost entry missing job/minutes/rate_usd_per_min"
                )
            try:
                float(entry["minutes"])
                float(entry["rate_usd_per_min"])
            except (TypeError, ValueError):
                return _inconclusive(
                    f"{name} arm has a runner_cost entry with non-numeric minutes/rate_usd_per_min"
                )

    control_m = _arm_metrics(control)
    offload_m = _arm_metrics(offload)
    return {
        "control": control_m,
        "offload": offload_m,
        "delta": {
            "trigger_to_final_green_seconds": offload_m["trigger_to_final_green_seconds"]
            - control_m["trigger_to_final_green_seconds"],
            "total_runner_cost_usd": offload_m["total_runner_cost_usd"]
            - control_m["total_runner_cost_usd"],
        },
    }

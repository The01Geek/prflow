#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Controlled failing-workload fixture validator (issue #420, Stage A).

Internal dev-only pilot harness helper (vendors with the rest of lib/, but no
shipped skill or workflow invokes it). The two-core pilot needs a
deterministic, deliberately-broken test module plus its
repaired counterpart so a measured run can exercise real failure→diagnosis→
repair. Stage A only proves the fixture PAIR is coherent and repo-verifiable
offline: both files parse as Python, they differ, and the repaired file is
valid. It never runs pytest against the real suite and never claims a live
repair — that is Stage B's measured execution.
"""
from __future__ import annotations

import json
from pathlib import Path


def _compiles(path: Path) -> bool:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return True
    except (SyntaxError, OSError):
        return False


def validate_workload(manifest_path) -> dict:
    """Validate the failing-workload fixture pair named by ``manifest_path``.

    The manifest is JSON with ``broken`` and ``repaired`` keys naming files
    relative to the manifest's own directory. Returns a dict with ``coherent``
    True only when: both files exist, the broken file parses (a broken *test*,
    not broken *syntax*), the repaired file parses, and the two differ. Any
    failed condition yields ``coherent: False`` with a ``reason`` naming it —
    the validator reports the specific gap rather than raising.
    """
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"coherent": False, "reason": f"manifest unreadable: {exc}"}
    base = manifest_path.parent
    if "broken" not in manifest or "repaired" not in manifest:
        return {"coherent": False, "reason": "manifest missing 'broken'/'repaired' keys"}
    broken = base / manifest["broken"]
    repaired = base / manifest["repaired"]
    if not broken.is_file():
        return {"coherent": False, "reason": f"broken file absent: {manifest['broken']}"}
    if not repaired.is_file():
        return {"coherent": False, "reason": f"repaired file absent: {manifest['repaired']}"}
    if not _compiles(broken):
        return {"coherent": False, "reason": "broken file does not parse (must be a failing test, not a syntax error)"}
    if not _compiles(repaired):
        return {"coherent": False, "reason": "repaired file does not parse"}
    if broken.read_text(encoding="utf-8") == repaired.read_text(encoding="utf-8"):
        return {"coherent": False, "reason": "broken and repaired files are identical"}
    return {
        "coherent": True,
        "broken": str(broken),
        "repaired": str(repaired),
        "note": "fixture pair only; not a live repair (Stage A preparation)",
    }

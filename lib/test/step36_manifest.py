#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared typed reader for the declared Step 3.6 audit reference set (issue #1702).

`lib/test/create-issue-step-3-6-members.json` declares the Step 3.6 entry reference plus
its ordered procedure members, and three independent checks resolve against it:
`lib/test/lint-reference-size.py` (per-member ceiling + aggregate source-byte budget),
`lib/test/check-audit-lifecycle-contracts.py` (call-sequence + fenced-completeness across
the set, and the manifest/on-disk marker reconciliation), and
`lib/test/modules/create-issue-contract.sh` (the `#614` routing/marker reconciliation).

The two Python readers each validated the record separately and to *different* depths, so a
malformed manifest was RED under one tool and accepted by the other. This module owns the one
validation, and returns it as a NAMED record rather than a positional tuple: a reorder of two
adjacent same-typed byte counts would type-check cleanly and compare against the wrong number.

`load()` fails CLOSED on every malformed shape. An unestablished set is never an empty one —
an empty population would read as a stricter check passing over nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


class Step36ManifestError(Exception):
    """The Step 3.6 member manifest could not be read as a well-formed record."""


class Step36Manifest(NamedTuple):
    """The validated manifest record. Read by field name, never by position."""

    entry: str
    members: tuple[str, ...]
    per_member_limit_bytes: int
    aggregate_baseline_bytes: int
    aggregate_baseline_commit: str


def _require_positive_int(data: dict, key: str) -> int:
    value = data.get(key)
    # `isinstance(True, int)` is True, so a bare int check would accept a JSON boolean as a
    # byte count and compare file sizes against 1.
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Step36ManifestError(
            f"the Step 3.6 manifest's `{key}` must be a positive integer")
    return value


def _require_nonempty_str(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Step36ManifestError(
            f"the Step 3.6 manifest's `{key}` must be a non-empty string")
    return value


def load(path: Path) -> Step36Manifest:
    """The validated manifest at `path`, or `Step36ManifestError`."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Step36ManifestError(
            f"the Step 3.6 manifest could not be read ({path}): {exc}") from exc
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Step36ManifestError(
            f"the Step 3.6 manifest is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise Step36ManifestError("the Step 3.6 manifest's top-level value must be an object")
    entry = _require_nonempty_str(data, "entry")
    members = data.get("members")
    if not isinstance(members, list) or not members or not all(
        isinstance(member, str) and member.strip() for member in members
    ):
        raise Step36ManifestError("the Step 3.6 manifest's `members` must be a non-empty list "
                                  "of non-empty strings")
    if len(set(members)) != len(members) or entry in members:
        raise Step36ManifestError("the Step 3.6 manifest names a duplicate or entry-as-member "
                                  "path")
    return Step36Manifest(
        entry=entry,
        members=tuple(members),
        per_member_limit_bytes=_require_positive_int(data, "per_member_limit_bytes"),
        aggregate_baseline_bytes=_require_positive_int(data, "aggregate_baseline_bytes"),
        aggregate_baseline_commit=_require_nonempty_str(data, "aggregate_baseline_commit"),
    )

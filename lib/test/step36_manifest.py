#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared typed reader for the declared Step 3.6 audit reference set (issue #1702).

`lib/test/create-issue-step-3-6-members.json` declares the Step 3.6 entry reference plus its
ordered procedure members, and three independent checks resolve against it:
`lib/test/lint-reference-size.py` (per-member ceiling + aggregate source-byte budget),
`lib/test/check-audit-lifecycle-contracts.py` (call-sequence + fenced-completeness across the
set, and the manifest/on-disk marker reconciliation), and
`lib/test/modules/create-issue-contract.sh` (the `#614` routing/marker reconciliation).

Specification
-------------
`Step36Manifest` validates in `__new__`, so no construction path can produce an invalid record —
`load()` parses JSON and constructs, and every other caller gets the same invariants. Field
access is by name: two adjacent same-typed byte counts read positionally would compare against
the wrong number and still type-check.

`SCHEMA_VERSIONS` is the recognised set. An **absent** `schema_version` reads as version 1, the
shape that shipped before the field existed; any other value is refused rather than read under
guessed semantics.

Path fields are compared after normalization, so `./a.md` and `a.md` are one member rather than
two — a duplicate the string-exact comparison admitted.

`load()` fails CLOSED on every malformed shape. An unestablished set is never an empty one: an
empty population would read as a stricter check passing over nothing.
"""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import NamedTuple

#: Recognised `schema_version` values. Absent reads as 1 (the pre-field shape).
SCHEMA_VERSIONS = (1,)


class Step36ManifestError(Exception):
    """The Step 3.6 member manifest could not be read as a well-formed record."""


def _normalize(path: str) -> str:
    """The comparison form of a declared repo-relative path."""
    return posixpath.normpath(path.strip())


def _require_positive_int(value: object, key: str) -> int:
    # `isinstance(True, int)` is True, so a bare int check would accept a JSON boolean as a
    # byte count and compare every file size against 1.
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Step36ManifestError(
            f"the Step 3.6 manifest's `{key}` must be a positive integer")
    return value


def _require_nonempty_str(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Step36ManifestError(
            f"the Step 3.6 manifest's `{key}` must be a non-empty string")
    return value


class _Step36ManifestFields(NamedTuple):
    """The field set. `Step36Manifest` below is the constructible type — use that one."""

    entry: str
    members: tuple[str, ...]
    per_member_limit_bytes: int
    aggregate_baseline_bytes: int
    aggregate_baseline_commit: str
    schema_version: int = 1


class Step36Manifest(_Step36ManifestFields):
    """The validated manifest record. Read by field name, never by position.

    A NamedTuple rather than a dataclass: `dataclasses` resolves `cls.__module__` through
    `sys.modules`, and both readers import this file via `module_from_spec` without registering
    it there, so a dataclass here raises at class-creation time inside every consumer.
    """

    def __new__(cls, *args, **kwargs):
        record = super().__new__(cls, *args, **kwargs)
        record._validate()
        return record

    def _validate(self) -> None:
        if self.schema_version not in SCHEMA_VERSIONS:
            raise Step36ManifestError(
                f"the Step 3.6 manifest declares schema_version {self.schema_version!r}, not "
                f"one of {list(SCHEMA_VERSIONS)} — refusing to read it under guessed semantics")
        _require_nonempty_str(self.entry, "entry")
        if not isinstance(self.members, tuple) or not self.members or not all(
            isinstance(member, str) and member.strip() for member in self.members
        ):
            raise Step36ManifestError("the Step 3.6 manifest's `members` must be a non-empty "
                                      "list of non-empty strings")
        normalized = [_normalize(member) for member in self.members]
        if len(set(normalized)) != len(normalized) or _normalize(self.entry) in normalized:
            raise Step36ManifestError("the Step 3.6 manifest names a duplicate or "
                                      "entry-as-member path")
        _require_positive_int(self.per_member_limit_bytes, "per_member_limit_bytes")
        _require_positive_int(self.aggregate_baseline_bytes, "aggregate_baseline_bytes")
        _require_nonempty_str(self.aggregate_baseline_commit, "aggregate_baseline_commit")


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
    members = data.get("members")
    if not isinstance(members, list):
        raise Step36ManifestError("the Step 3.6 manifest's `members` must be a non-empty list "
                                  "of non-empty strings")
    return Step36Manifest(
        entry=data.get("entry"),
        members=tuple(members),
        per_member_limit_bytes=data.get("per_member_limit_bytes"),
        aggregate_baseline_bytes=data.get("aggregate_baseline_bytes"),
        aggregate_baseline_commit=data.get("aggregate_baseline_commit"),
        schema_version=data.get("schema_version", 1),
    )

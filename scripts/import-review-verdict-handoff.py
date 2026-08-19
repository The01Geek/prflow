#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Strict importer for the trusted cloud review-verdict handoff (issue #1314).

The cloud review path is split into an untrusted read-only *producer* and a
trusted *emitter*. The producer writes a tiny handoff describing only the review
*decision* — never repository/PR identity, which the emitter reads from trusted
workflow state — plus the review body. This importer is the trust boundary: it
validates the handoff as *untrusted input* and publishes a normalized artifact
**only** after every check passes. A rejected handoff publishes nothing, so no
write-capable emitter work is ever scheduled on bad input.

Threat model / why each check exists (AC5):

- The handoff file is produced in `.prflow/tmp/` by an untrusted engine run, then
  read here. Everything about the file is attacker-influenced: its type, its link
  count, its size, its bytes, and its contents. So the importer treats the path
  adversarially — it opens with ``O_NOFOLLOW`` (a symlink is rejected atomically,
  never followed), rejects a non-regular file and any file carrying *additional*
  hard links (``st_nlink != 1`` — a second name through which the bytes could be
  swapped after validation), caps the size (oversized input is refused before it
  is read into memory), and re-stats the open descriptor after reading to reject a
  file whose metadata changed under it (an unstable file racing the read).
- The bytes must decode as strict UTF-8, must carry no NUL, and no disallowed C0
  control character (only TAB/LF/CR are allowed) — a defense against smuggled
  control sequences in a value that later reaches a terminal/log/API.
- The JSON is a *closed* schema: exactly the four documented keys, no unknown
  fields, each with its exact JSON type. ``schema_version`` is the integer ``1``
  (not the string ``"1"``, not the boolean ``True``); ``complete`` is the boolean
  ``true`` (not the string ``"true"``, not ``1``). The ``review_event`` and
  ``marker_verdict`` strings are drawn from closed vocabularies, and only the
  three documented (event, verdict) pairs are legal.

Every rejection prints ``REJECTED <token>`` on stderr and exits non-zero; the
tokens are stable so callers and tests can assert on the *cause*. On success the
normalized handoff (and, when ``--body`` is given, the validated body) is written
to the requested output path(s) and ``ACCEPTED <review_event> <marker_verdict>``
is printed on stdout.

This script performs **no** network access and reads **no** repository/PR
identity — those are the emitter's trusted concern.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import stat
import sys
from typing import NamedTuple


class ImportedHandoff(NamedTuple):
    """The validated result of a handoff import (typed so the two-key contract is
    checked at the call site rather than reached by string literal)."""

    normalized: dict
    body: str | None

# Closed schema (issue #1314). The handoff carries ONLY the decision; identity
# comes from trusted workflow state, never from this file.
SCHEMA_VERSION = 1
HANDOFF_KEYS = frozenset({"schema_version", "complete", "review_event", "marker_verdict"})
REVIEW_EVENTS = frozenset({"REQUEST_CHANGES", "APPROVE", "COMMENT"})
MARKER_VERDICTS = frozenset({"REJECT", "APPROVE"})
# The only legal (review_event, marker_verdict) pairings.
LEGAL_PAIRS = frozenset({
    ("REQUEST_CHANGES", "REJECT"),
    ("APPROVE", "APPROVE"),
    ("COMMENT", "APPROVE"),
})
# The vocab sets and the pair table must stay mutually consistent: a pair drawn
# from outside the singleton vocabularies would be silently unreachable dead code
# (the per-field checks reject it before the pair check). Assert the relation at
# import so a future typo is a loud failure, not silent drift.
assert all(e in REVIEW_EVENTS and v in MARKER_VERDICTS for e, v in LEGAL_PAIRS)

# Bounds. The handoff JSON is tiny by construction; the body is prose but still
# bounded so an oversized artifact can never be published.
DEFAULT_MAX_HANDOFF_BYTES = 4096
DEFAULT_MAX_BODY_BYTES = 262144  # 256 KiB

# Disallowed control characters: every C0 control except TAB/LF/CR, plus DEL.
# A single precompiled C-level scan replaces a per-character Python loop over the
# (up to 256 KiB) body text.
_DISALLOWED_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Rejected(Exception):
    """A validation failure carrying a stable reason token."""

    def __init__(self, token: str, detail: str = "") -> None:
        super().__init__(token if not detail else f"{token}: {detail}")
        self.token = token
        self.detail = detail


def _read_bounded_regular_file(path: str, max_bytes: int) -> bytes:
    """Open *path* adversarially and return its bytes, or raise Rejected.

    Rejects, by token: ``symlink`` (O_NOFOLLOW), ``not-regular-file``,
    ``extra-hard-links`` (st_nlink != 1), ``oversized`` (> max_bytes),
    ``unstable-metadata`` (identity/size/mtime/ctime/nlink changed across the
    read), and ``unreadable`` (an open error other than a symlink — a read-time
    OSError is not remapped and propagates, still fail-closed before any publish).
    """
    try:
        # O_NOFOLLOW makes a final-component symlink fail atomically (ELOOP) —
        # the symlink is never opened, closing the swap-after-check race that a
        # separate lstat()+open() would leave open.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        # ELOOP is the O_NOFOLLOW symlink refusal; everything else is a genuine
        # open failure (missing file, permission, non-followable special).
        if exc.errno == errno.ELOOP:
            raise Rejected("symlink", path) from exc
        raise Rejected("unreadable", f"{path}: {exc}") from exc
    try:
        st_before = os.fstat(fd)
        if not stat.S_ISREG(st_before.st_mode):
            raise Rejected("not-regular-file", path)
        # Any additional hard link is a second name the bytes could be mutated
        # through after we validate them.
        if st_before.st_nlink != 1:
            raise Rejected("extra-hard-links", f"{path}: st_nlink={st_before.st_nlink}")
        if st_before.st_size > max_bytes:
            raise Rejected("oversized", f"{path}: {st_before.st_size} > {max_bytes}")
        # Read at most max_bytes + 1 so a file that grew between fstat and read
        # (racing writer) is still caught as oversized rather than truncated.
        data = _read_all(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise Rejected("oversized", f"{path}: exceeds {max_bytes} during read")
        st_after = os.fstat(fd)
        # A stable file must present identical identity and metadata across the
        # read. Any drift means the file was racing us — refuse it.
        if (
            st_before.st_ino != st_after.st_ino
            or st_before.st_dev != st_after.st_dev
            or st_before.st_size != st_after.st_size
            or st_before.st_mtime_ns != st_after.st_mtime_ns
            or st_before.st_ctime_ns != st_after.st_ctime_ns
            or st_after.st_nlink != 1
        ):
            raise Rejected("unstable-metadata", path)
        return data
    finally:
        os.close(fd)


def _read_all(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    got = 0
    while got <= limit:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _decode_clean_text(data: bytes, *, kind: str) -> str:
    """Decode strict UTF-8 and reject NUL / disallowed control characters."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Rejected("invalid-utf8", f"{kind}: {exc}") from exc
    # NUL is checked first (and separately) so it keeps its own distinct token;
    # both scans are C-level rather than a per-character Python loop.
    if "\x00" in text:
        raise Rejected("nul-byte", kind)
    m = _DISALLOWED_CONTROL_RE.search(text)
    if m is not None:
        raise Rejected("disallowed-control", f"{kind}: U+{ord(m.group()):04X}")
    return text


def _validate_handoff_obj(obj: object) -> tuple[str, str]:
    """Validate the parsed handoff object; return (review_event, marker_verdict)."""
    if not isinstance(obj, dict):
        raise Rejected("not-object")
    keys = set(obj.keys())
    unknown = keys - HANDOFF_KEYS
    if unknown:
        raise Rejected("unknown-field", ",".join(sorted(unknown)))
    missing = HANDOFF_KEYS - keys
    if missing:
        raise Rejected("missing-field", ",".join(sorted(missing)))

    sv = obj["schema_version"]
    # bool is a subclass of int — reject it explicitly so `true` cannot pass as 1.
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != SCHEMA_VERSION:
        raise Rejected("bad-schema-version", repr(sv))

    complete = obj["complete"]
    if complete is not True:  # exact JSON boolean true — not "true", not 1
        raise Rejected("bad-complete", repr(complete))

    event = obj["review_event"]
    if not isinstance(event, str) or event not in REVIEW_EVENTS:
        raise Rejected("bad-review-event", repr(event))

    verdict = obj["marker_verdict"]
    if not isinstance(verdict, str) or verdict not in MARKER_VERDICTS:
        raise Rejected("bad-marker-verdict", repr(verdict))

    if (event, verdict) not in LEGAL_PAIRS:
        raise Rejected("illegal-event-verdict-pair", f"{event}/{verdict}")

    return event, verdict


def import_handoff(
    handoff_path: str,
    *,
    body_path: str | None,
    max_handoff_bytes: int,
    max_body_bytes: int,
) -> ImportedHandoff:
    """Validate the handoff (and optional body). Return the normalized record.

    Raises Rejected on the first failing check. Performs no output write — the
    caller publishes only after this returns.
    """
    raw = _read_bounded_regular_file(handoff_path, max_handoff_bytes)
    text = _decode_clean_text(raw, kind="handoff")
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise Rejected("not-json", str(exc)) from exc
    event, verdict = _validate_handoff_obj(obj)

    body_text: str | None = None
    if body_path is not None:
        body_raw = _read_bounded_regular_file(body_path, max_body_bytes)
        body_text = _decode_clean_text(body_raw, kind="body")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "complete": True,
        "review_event": event,
        "marker_verdict": verdict,
    }
    return ImportedHandoff(normalized=normalized, body=body_text)


def _atomic_write(path: str, data: str) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Validate and normalize a trusted-emitter review-verdict handoff.",
    )
    parser.add_argument("--handoff", required=True, help="path to the handoff JSON")
    parser.add_argument("--body", help="path to the review body markdown (validated when given)")
    parser.add_argument("--out", help="write the normalized handoff JSON here on success")
    parser.add_argument("--out-body", help="write the validated body here on success")
    parser.add_argument(
        "--max-handoff-bytes", type=int, default=DEFAULT_MAX_HANDOFF_BYTES,
    )
    parser.add_argument(
        "--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES,
    )
    args = parser.parse_args(argv)

    if args.out_body and not args.body:
        print("REJECTED out-body-without-body", file=sys.stderr)
        return 2

    try:
        result = import_handoff(
            args.handoff,
            body_path=args.body,
            max_handoff_bytes=args.max_handoff_bytes,
            max_body_bytes=args.max_body_bytes,
        )
    except Rejected as rej:
        # Publish nothing on rejection — the emitter must schedule no work.
        print(f"REJECTED {rej.token}", file=sys.stderr)
        if rej.detail:
            print(f"  detail: {rej.detail}", file=sys.stderr)
        return 1

    normalized = result.normalized
    # Publish only after every check passed. Write the body FIRST and the verdict
    # (--out) LAST, so the verdict artifact's existence implies its body is already
    # present: a downstream emitter that keys "schedule work" off --out can never
    # observe a verdict without a matching body, even if the second write is
    # interrupted (ENOSPC, permission, signal).
    if args.out_body and result.body is not None:
        _atomic_write(args.out_body, result.body)
    if args.out:
        _atomic_write(args.out, json.dumps(normalized, sort_keys=True) + "\n")

    print(f"ACCEPTED {normalized['review_event']} {normalized['marker_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Strict reader/validator for the declarative lint manifest (`.prflow/lint-manifest.json`).

The lint manifest is a *declarative* description of the bounded lint toolchain
DevFlow provisions before a model run: exact ShellCheck and Ruff versions, per
platform artifact digests, file selectors, exclusions, closed special-invocation
IDs, timeout bounds, and full-lint profile IDs. It deliberately carries **no**
executable behavior — no shell command strings, package-manager snippets,
arbitrary executable paths, URL templates, or environment expansion — so that a
trusted installer/helper maps the manifest's closed strategy IDs to fixed
behavior rather than executing manifest-supplied text (issue #1276).

This module is the single source of truth for parsing and validating that file.
It is a **best-effort parser** over agent- and human-mutable JSON, so it follows
the repository's six-shape reader matrix: every degraded input shape — object,
array, scalar, valid-falsy, missing, wrong-type, unreadable, malformed JSON,
empty bytes, invalid UTF-8, truncated JSON, duplicate object keys,
unknown-version, duplicate-ID, conflicting-ID, and unknown-enum — resolves to a
typed **unestablished** result carrying a specific reason. It never returns a
plausible-but-unobserved "N/A": the only two outcomes are `established` (with the
validated manifest) and `unestablished` (with a reason). *Unknown is not zero.*

The parser is trusted code assembling nothing from the manifest; it only reads
typed fields and rejects anything outside their closed vocabularies.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ── Closed vocabularies. A value outside any of these is `unknown-enum`. ──────
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
# The FILE-ABSENT sentinel, exactly as load_manifest emits it. Consumers that must
# tell an absent file from a present-but-invalid manifest compare EQUALITY with this
# constant — a `missing:` prefix match also catches structural missing-key reasons.
MISSING_FILE_REASON = "missing: manifest file does not exist"
KNOWN_TOOLS = ("shellcheck", "ruff")
KNOWN_OS = frozenset({"linux", "macos", "windows"})
KNOWN_ARCH = frozenset({"x86_64", "arm64"})
KNOWN_ARCHIVE_TYPES = frozenset({"tar.gz", "tar.xz", "zip"})
KNOWN_STRATEGIES = frozenset({"extract-tar", "extract-zip"})
KNOWN_LANGUAGES = frozenset({"shell", "python"})

# ── Typed-field shapes. These regexes are what make the manifest reject shell
#    commands, package-manager snippets, arbitrary executable paths, URL
#    templates, and environment expansion: any of `$ ; | & \` ( ) < > space`,
#    a `://` scheme, or a `/` in an executable member fails its field. ─────────
# `\Z` (true end of string), not `$` (which matches before a trailing newline in
# non-MULTILINE mode) — so a value ending in `\n` cannot slip past a field whose
# whole purpose is to reject content outside its closed vocabulary.
_VERSION_RE = re.compile(r"\A[0-9]+(\.[0-9]+){1,3}\Z")
_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_MEMBER_RE = re.compile(r"\A[A-Za-z0-9._-]+\Z")  # a basename, never a path
_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9-]*\Z")
_FLAG_RE = re.compile(r"\A--[a-z0-9][a-z0-9-]*(=[A-Za-z0-9._-]+)?\Z")
# A glob is a repo-relative selector pattern: path separators and glob
# metacharacters only. `$` (env expansion), whitespace, and shell metacharacters
# are rejected, so a URL template or command string can never masquerade as one.
# The character class alone does NOT make a value repo-relative or argv-safe —
# `_validate_path_shape` below enforces those two properties separately.
_GLOB_RE = re.compile(r"\A[A-Za-z0-9._*/?\[\]{}-]+\Z")

# Timeout bounds (seconds). A value outside the inclusive range is rejected.
_TIMEOUT_MIN = 1
_TIMEOUT_MAX = 3600


class ManifestResult:
    """Typed outcome of a manifest read: `established` XOR `unestablished`.

    Never a third "N/A" state — an unreadable/malformed/invalid manifest is an
    *unestablished measurement* carrying a specific `reason`, never a clean
    empty answer a caller could mistake for "validated, nothing to do".
    """

    __slots__ = ("manifest", "reason", "status")

    def __init__(self, status: str, *, manifest=None, reason: str | None = None):
        if status not in ("established", "unestablished"):
            raise ValueError(f"invalid manifest-result status: {status!r}")
        # Enforce the XOR in BOTH directions at construction (like Plan/StateResult/
        # Readiness): an established result smuggling a reason, or an unestablished
        # one carrying a manifest or losing its reason, must be unrepresentable.
        if status == "established":
            if manifest is None:
                raise ValueError("established ManifestResult requires a manifest")
            if reason is not None:
                raise ValueError("established ManifestResult must not carry a reason")
        else:
            if not reason:
                raise ValueError("unestablished ManifestResult requires a reason")
            if manifest is not None:
                raise ValueError("unestablished ManifestResult must not carry a manifest")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "reason", reason)

    def __setattr__(self, name, value):
        # Frozen after construction: a post-init write would defeat the XOR above.
        raise AttributeError(f"ManifestResult is immutable (attempted to set {name!r})")

    @property
    def established(self) -> bool:
        return self.status == "established"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        if self.established:
            return "ManifestResult(established)"
        return f"ManifestResult(unestablished: {self.reason})"


def _established(manifest) -> ManifestResult:
    return ManifestResult("established", manifest=manifest)


def _unestablished(reason: str) -> ManifestResult:
    return ManifestResult("unestablished", reason=reason)


def _check_keys(where, obj, known, required) -> ManifestResult | None:
    """Reject an unknown key (`unknown-field`) or a missing required key (`missing`).

    Returns an unestablished `ManifestResult` on the first violation, or `None`
    when the object's key set is within `known` and covers `required`. Shared by
    every closed-schema object validator so the two rejection messages stay
    identical across sites. `where` is `None` at the top level, whose messages
    read "top-level key" rather than "<where> key".
    """
    label = "top-level" if where is None else where
    for key in obj:
        if key not in known:
            return _unestablished(f"unknown-field: unknown {label} key {key!r}")
    for key in required:
        if key not in obj:
            return _unestablished(f"missing: required {label} key {key!r}")
    return None


class _DuplicateKey(ValueError):
    """Raised by the object hook when a JSON object repeats a key."""


def _reject_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen[key] = value
    return seen


def load_manifest(path) -> ManifestResult:
    """Read and validate a lint manifest from `path`.

    Returns a `ManifestResult`. Every I/O and decode failure is fail-closed to
    `unestablished` — a missing file, an unreadable path, non-UTF-8 bytes, and
    empty bytes are all distinct reasons, never an exception the caller must
    guard and never a clean pass.
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return _unestablished(MISSING_FILE_REASON)
    except (IsADirectoryError, PermissionError, OSError) as exc:
        return _unestablished(f"unreadable: {exc.__class__.__name__}")
    return parse_manifest(raw)


def parse_manifest(raw: bytes) -> ManifestResult:
    """Validate manifest bytes. See `load_manifest` for the reason vocabulary."""
    if not isinstance(raw, (bytes, bytearray)):
        return _unestablished("wrong-type: manifest bytes must be a byte string")
    if len(raw) == 0:
        return _unestablished("empty: manifest file is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _unestablished("invalid-utf8: manifest is not valid UTF-8")
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKey as exc:
        return _unestablished(f"duplicate-key: repeated object key {exc.args[0]!r}")
    except json.JSONDecodeError as exc:
        # Covers both malformed and truncated JSON (an unterminated document
        # raises `Expecting … delimiter`), which the caller need not distinguish.
        return _unestablished(f"malformed-json: {exc.msg}")
    except RecursionError:
        # A pathologically nested document (trivially producible by a hostile or
        # corrupt file) overflows json's recursive decoder with a RecursionError,
        # which is not a JSONDecodeError. Fail closed to unestablished like every
        # other malformed shape rather than letting it escape as an exception the
        # caller must guard.
        return _unestablished("malformed-json: input nesting too deep")
    return validate_manifest(data)


def validate_manifest(data) -> ManifestResult:
    """Validate an already-parsed manifest object (the top-level JSON value).

    Split out from `parse_manifest` so callers holding a decoded object (a test,
    a candidate-vs-installed comparison) validate without re-serializing.
    """
    if isinstance(data, bool) or not isinstance(data, dict):
        # `bool` is a JSON scalar (`true`/`false`) and an `int` subclass, so it
        # must be excluded before the dict check or `valid-falsy` `false` would
        # slip through as a mapping-shaped value on some paths.
        kind = _json_kind(data)
        return _unestablished(f"wrong-type: top level is a {kind}, expected object")

    required = ("schema_version", "tools", "selectors", "full_profiles")
    known_top = set(required) | {"exclusions", "special_invocations"}
    if (r := _check_keys(None, data, known_top, required)) is not None:
        return r

    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        return _unestablished("wrong-type: schema_version must be an integer")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return _unestablished(f"unknown-version: schema_version {version} unsupported")

    tools_result = _validate_tools(data["tools"])
    if not tools_result.established:
        return tools_result

    selector_ids: set[str] = set()
    sel_result = _validate_selectors(data["selectors"], selector_ids)
    if not sel_result.established:
        return sel_result

    if "exclusions" in data:
        exc_result = _validate_exclusions(data["exclusions"])
        if not exc_result.established:
            return exc_result

    if "special_invocations" in data:
        si_result = _validate_special_invocations(data["special_invocations"])
        if not si_result.established:
            return si_result

    prof_result = _validate_full_profiles(data["full_profiles"], selector_ids)
    if not prof_result.established:
        return prof_result

    return _established(data)


def _json_kind(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _validate_tools(tools) -> ManifestResult:
    if not isinstance(tools, dict):
        return _unestablished(
            f"wrong-type: tools is a {_json_kind(tools)}, expected object")
    for name in tools:
        if name not in KNOWN_TOOLS:
            return _unestablished(f"unknown-enum: unknown tool {name!r}")
    for name in KNOWN_TOOLS:
        if name not in tools:
            return _unestablished(f"missing: required tool {name!r}")
        result = _validate_tool(name, tools[name])
        if not result.established:
            return result
    return _established(tools)


def _validate_tool(name, tool) -> ManifestResult:
    if not isinstance(tool, dict):
        return _unestablished(
            f"wrong-type: tool {name!r} is a {_json_kind(tool)}, expected object")
    known = {"version", "timeout_seconds", "artifacts"}
    if (r := _check_keys(f"tool {name!r}", tool, known, known)) is not None:
        return r

    version = tool["version"]
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        return _unestablished(f"invalid-value: tool {name!r} version {version!r}")

    timeout = tool["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return _unestablished(f"wrong-type: tool {name!r} timeout_seconds")
    if not (_TIMEOUT_MIN <= timeout <= _TIMEOUT_MAX):
        return _unestablished(
            f"invalid-value: tool {name!r} timeout_seconds {timeout} out of bounds")

    artifacts = tool["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        return _unestablished(f"invalid-value: tool {name!r} artifacts must be a non-empty array")
    seen_tuples: dict[tuple[str, str], str] = {}
    for idx, art in enumerate(artifacts):
        result = _validate_artifact(name, idx, art)
        if not result.established:
            return result
        tup = (art["os"], art["arch"])
        digest = art["digest"]
        if tup in seen_tuples:
            if seen_tuples[tup] == digest:
                return _unestablished(
                    f"duplicate-id: tool {name!r} repeats platform {tup}")
            return _unestablished(
                f"conflicting-id: tool {name!r} platform {tup} has two digests")
        seen_tuples[tup] = digest
    return _established(tool)


def _validate_artifact(name, idx, art) -> ManifestResult:
    where = f"tool {name!r} artifact #{idx}"
    if not isinstance(art, dict):
        return _unestablished(f"wrong-type: {where} is a {_json_kind(art)}")
    known = {"os", "arch", "digest", "archive_type", "member", "strategy"}
    if (r := _check_keys(where, art, known, known)) is not None:
        return r
    if art["os"] not in KNOWN_OS:
        return _unestablished(f"unknown-enum: {where} os {art['os']!r}")
    if art["arch"] not in KNOWN_ARCH:
        return _unestablished(f"unknown-enum: {where} arch {art['arch']!r}")
    if art["archive_type"] not in KNOWN_ARCHIVE_TYPES:
        return _unestablished(f"unknown-enum: {where} archive_type {art['archive_type']!r}")
    if art["strategy"] not in KNOWN_STRATEGIES:
        return _unestablished(f"unknown-enum: {where} strategy {art['strategy']!r}")
    digest = art["digest"]
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        return _unestablished(f"invalid-value: {where} digest {digest!r}")
    member = art["member"]
    if not isinstance(member, str) or not _MEMBER_RE.match(member):
        return _unestablished(f"invalid-value: {where} member {member!r}")
    # `_MEMBER_RE`'s character class admits `.`, `..` and `-rf`, so the member —
    # the name the extractor pulls out of the archive and then invokes — takes
    # the same path-shape guard as every other path-shaped field. `.` is the one
    # remaining directory spelling that guard does not cover (`/` is already
    # barred by `_MEMBER_RE`, so `.` cannot be a segment of a longer path here),
    # and a directory name is not an extractable executable.
    if member == ".":
        return _unestablished(
            f"invalid-value: {where} member {member!r} names a directory entry, "
            "not an extractable file")
    if (reason := _validate_path_shape(where, "member", member)) is not None:
        return _unestablished(reason)
    return _established(art)


def _validate_selectors(selectors, out_ids: set[str]) -> ManifestResult:
    if not isinstance(selectors, list) or not selectors:
        return _unestablished("invalid-value: selectors must be a non-empty array")
    for idx, sel in enumerate(selectors):
        where = f"selector #{idx}"
        if not isinstance(sel, dict):
            return _unestablished(f"wrong-type: {where} is a {_json_kind(sel)}")
        known = {"id", "language", "include_globs", "exclude_globs"}
        if (r := _check_keys(where, sel, known, ("id", "language", "include_globs"))) is not None:
            return r
        sid = sel["id"]
        if not isinstance(sid, str) or not _ID_RE.match(sid):
            return _unestablished(f"invalid-value: {where} id {sid!r}")
        if sid in out_ids:
            return _unestablished(f"duplicate-id: selector id {sid!r}")
        out_ids.add(sid)
        if sel["language"] not in KNOWN_LANGUAGES:
            return _unestablished(f"unknown-enum: {where} language {sel['language']!r}")
        glob_result = _validate_globs(where, sel["include_globs"], label="include_globs")
        if not glob_result.established:
            return glob_result
        if "exclude_globs" in sel:
            glob_result = _validate_globs(where, sel["exclude_globs"], label="exclude_globs")
            if not glob_result.established:
                return glob_result
    return _established(selectors)


def _validate_path_shape(where, label, value) -> str | None:
    """Reject a path-shaped value that is not a repo-relative, argv-safe pattern.

    Returns a reason string on rejection, or `None` when the value is acceptable.
    Three properties beyond `_GLOB_RE`'s character class:

    * **argv-safe** — a leading `-` (`-x`, `-rf`, `--exclude`, a bare `-`) is
      parsed as an *option* by ShellCheck/Ruff when the entry is spliced into an
      argv, silently changing tool behavior instead of naming a file.
    * **not absolute** — a leading `/` points the lint outside the repository.
    * **no traversal** — a `..` path segment anywhere in the value, leading
      (`..`, `../../*.sh`) or interior (`a/../b`), likewise escapes the
      repository. The check is per segment, so `..foo` is a normal name.

    Without these a manifest selector can direct a lint at a path the repository
    does not own, or turn a file argument into a tool flag. Shared by every
    path-shaped field — selector globs, exclusions, special-invocation paths and
    an artifact `member` — so their accepted sets cannot drift apart.
    """
    if value.startswith("-"):
        return (f"invalid-value: {where} {label} {value!r} starts with '-' "
                "(would be parsed as an option, not a path)")
    if value.startswith("/"):
        return f"invalid-value: {where} {label} {value!r} is absolute, not repo-relative"
    if any(seg == ".." for seg in value.split("/")):
        return f"invalid-value: {where} {label} {value!r} escapes the repository via '..'"
    return None


def _validate_globs(where, globs, *, label="globs") -> ManifestResult:
    """Validate a glob list. Empty is rejected: a selector that matches nothing
    would let a caller report a clean lint having enumerated zero files."""
    if not isinstance(globs, list):
        return _unestablished(f"wrong-type: {where} {label} must be an array")
    if not globs:
        return _unestablished(f"invalid-value: {where} {label} must be a non-empty array")
    for g in globs:
        if not isinstance(g, str) or not _GLOB_RE.match(g):
            return _unestablished(f"invalid-value: {where} glob {g!r}")
        if (reason := _validate_path_shape(where, "glob", g)) is not None:
            return _unestablished(reason)
    return _established(globs)


def _validate_exclusions(exclusions) -> ManifestResult:
    # `where` already names the field, so the label must not repeat the word
    # "globs" — the default would render the doubled "exclusions globs".
    return _validate_globs("exclusions", exclusions, label="entries")


def _validate_special_invocations(sis) -> ManifestResult:
    if not isinstance(sis, list):
        return _unestablished("wrong-type: special_invocations must be an array")
    seen: set[str] = set()
    for idx, si in enumerate(sis):
        where = f"special_invocation #{idx}"
        if not isinstance(si, dict):
            return _unestablished(f"wrong-type: {where} is a {_json_kind(si)}")
        known = {"id", "path", "tool", "extra_flags"}
        if (r := _check_keys(where, si, known, known)) is not None:
            return r
        sid = si["id"]
        if not isinstance(sid, str) or not _ID_RE.match(sid):
            return _unestablished(f"invalid-value: {where} id {sid!r}")
        if sid in seen:
            return _unestablished(f"duplicate-id: special_invocation id {sid!r}")
        seen.add(sid)
        if si["tool"] not in KNOWN_TOOLS:
            return _unestablished(f"unknown-enum: {where} tool {si['tool']!r}")
        path = si["path"]
        if not isinstance(path, str) or not _GLOB_RE.match(path):
            return _unestablished(f"invalid-value: {where} path {path!r}")
        if (reason := _validate_path_shape(where, "path", path)) is not None:
            return _unestablished(reason)
        flags = si["extra_flags"]
        if not isinstance(flags, list):
            return _unestablished(f"wrong-type: {where} extra_flags must be an array")
        for flag in flags:
            if not isinstance(flag, str) or not _FLAG_RE.match(flag):
                return _unestablished(f"invalid-value: {where} flag {flag!r}")
    return _established(sis)


def _validate_full_profiles(profiles, selector_ids) -> ManifestResult:
    if not isinstance(profiles, list) or not profiles:
        return _unestablished("invalid-value: full_profiles must be a non-empty array")
    seen: set[str] = set()
    for idx, prof in enumerate(profiles):
        where = f"full_profile #{idx}"
        if not isinstance(prof, dict):
            return _unestablished(f"wrong-type: {where} is a {_json_kind(prof)}")
        known = {"id", "tool", "selector"}
        if (r := _check_keys(where, prof, known, known)) is not None:
            return r
        pid = prof["id"]
        if not isinstance(pid, str) or not _ID_RE.match(pid):
            return _unestablished(f"invalid-value: {where} id {pid!r}")
        if pid in seen:
            return _unestablished(f"duplicate-id: full_profile id {pid!r}")
        seen.add(pid)
        if prof["tool"] not in KNOWN_TOOLS:
            return _unestablished(f"unknown-enum: {where} tool {prof['tool']!r}")
        selector = prof["selector"]
        if not isinstance(selector, str) or selector not in selector_ids:
            # A profile referencing an undefined selector is a conflicting cross
            # reference — the profile set and selector set disagree.
            return _unestablished(f"conflicting-id: {where} selector {selector!r} undefined")
    return _established(profiles)


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
    """CLI: validate a manifest path and print one machine-readable line.

    Prints `ESTABLISHED` (exit 0) or `UNESTABLISHED <reason>` (exit 2); a usage
    error exits 1 and a clean `--help` exits 0. Mirrors the one-token contract
    the other bundled helpers use, so a workflow step can branch on the exit
    status — and a usage error is a distinct code from a validated-but-
    unestablished manifest, never collapsed onto it.
    """
    _force_utf8_streams()
    import argparse

    parser = argparse.ArgumentParser(description="Validate a lint manifest.")
    parser.add_argument("path", help="path to the lint manifest JSON file")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on a usage error, which would collide with the exit-2
        # UNESTABLISHED result below and defeat the branch-on-exit-status
        # contract. Remap a usage error (nonzero code) to exit 1; leave a clean
        # --help / --version (code 0 or None) untouched.
        raise SystemExit(1 if exc.code else exc.code) from None
    result = load_manifest(args.path)
    if result.established:
        print("ESTABLISHED")
        return 0
    print(f"UNESTABLISHED {result.reason}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))

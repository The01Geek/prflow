#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Pre-agent validator for the devflow-cloud-writer-contract-v1 runtime manifest (AC18, #543).

Runs before a cloud writer agent boots and fails closed if the vendored runtime
manifest does not describe the installed plugin. Its rejection matrix is closed
at exactly seventeen classes, complete by construction from the v1 schema,
content binding, reachability binding, and profile check:

  1  ABSENT_FILE           the manifest file does not exist
  2  UNREADABLE_FILE       the manifest file cannot be read
  3  INVALID_JSON          the manifest is not valid JSON
  4  TOP_LEVEL_ARRAY       the top-level value is a JSON array
  5  TOP_LEVEL_STRING      the top-level value is a JSON string
  6  TOP_LEVEL_FALSE       the top-level value is the valid-falsy `false`
  7  MISSING_KEY           a required top-level key is absent
  8  EXTRA_KEY             an unexpected top-level key is present
  9  DUPLICATE_KEY         a key is duplicated in the JSON source
  10 WRONG_FIELD_TYPE      a field — or the top-level value — has the wrong JSON type,
                           or (fail-closed) the expected-contract dependencies could not
                           be derived from the sibling reachability contract
  11 MALFORMED_DIGEST      a files digest is not lowercase 64-hex
  12 INVALID_PATH          a files key is absolute or escapes the vendored root
  13 MISSING_ASSET         a listed file does not exist on disk
  14 HASH_MISMATCH         a listed file's recomputed hash differs
  15 REACHED_ASSET_OMITTED a reached asset (AC1 skill asset or required-helper source) absent from `files`
  16 PROFILE_OMITTED       a required cloud profile is absent from required_helper_heads
  17 HEAD_ABSENT           a required helper head is absent from that profile's grants

Exit 0 == valid; exit 1 == one or more violations (each printed to stdout).

Deployment note (the pre-agent wiring is AC19/AC20 of #543, deferred). The default
(un-injected) dependency derivation resolves both the manifest's ``files`` (under
``base_dir``) and the profile grants (from ``base_dir / <workflow>``) against the
same ``base_dir``. In the *source* repository that is the repo root, which holds
both ``scripts/``/``lib/`` and ``.github/workflows/``, so ``main([])`` works. In a
*consumer* the helpers are vendored under ``.prflow/vendor/prflow/`` while the
workflows live at the consumer repo root, so the two roots differ and the caller
must inject ``base_dir`` / ``profile_grants`` explicitly. ``validate()`` takes all
three as injectable parameters precisely so the pre-agent wiring can supply the
right roots; do not rely on the default derivation from the vendored location.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]

PROTOCOL = "devflow-cloud-writer-contract-v1"
REQUIRED_KEYS = {"protocol", "legacy_profile_baseline", "files", "required_helper_heads"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_DEFAULT = REPO_ROOT / "scripts" / "devflow-cloud-writer-contract.json"

# Rejection-class codes (the closed seventeen).
ABSENT_FILE = "ABSENT_FILE"
UNREADABLE_FILE = "UNREADABLE_FILE"
INVALID_JSON = "INVALID_JSON"
TOP_LEVEL_ARRAY = "TOP_LEVEL_ARRAY"
TOP_LEVEL_STRING = "TOP_LEVEL_STRING"
TOP_LEVEL_FALSE = "TOP_LEVEL_FALSE"
MISSING_KEY = "MISSING_KEY"
EXTRA_KEY = "EXTRA_KEY"
DUPLICATE_KEY = "DUPLICATE_KEY"
WRONG_FIELD_TYPE = "WRONG_FIELD_TYPE"
MALFORMED_DIGEST = "MALFORMED_DIGEST"
INVALID_PATH = "INVALID_PATH"
MISSING_ASSET = "MISSING_ASSET"
HASH_MISMATCH = "HASH_MISMATCH"
REACHED_ASSET_OMITTED = "REACHED_ASSET_OMITTED"
PROFILE_OMITTED = "PROFILE_OMITTED"
HEAD_ABSENT = "HEAD_ABSENT"

# The closed seventeen, as a set — so a test can assert validate() never emits a
# code outside it (making "closed by construction" an enforced invariant, not
# only a docstring claim). Mirrors the DISPATCH_KINDS frozenset in the contract.
REJECTION_CODES = frozenset({
    ABSENT_FILE, UNREADABLE_FILE, INVALID_JSON, TOP_LEVEL_ARRAY, TOP_LEVEL_STRING,
    TOP_LEVEL_FALSE, MISSING_KEY, EXTRA_KEY, DUPLICATE_KEY, WRONG_FIELD_TYPE,
    MALFORMED_DIGEST, INVALID_PATH, MISSING_ASSET, HASH_MISMATCH,
    REACHED_ASSET_OMITTED, PROFILE_OMITTED, HEAD_ABSENT,
})


class Violation(NamedTuple):
    """A single validation failure: a rejection-class ``code`` and a human ``message``.

    A self-documenting return type for ``validate()`` (``.code`` / ``.message``
    instead of an anonymous 2-tuple), and — being a ``tuple`` subclass — it stays
    unpackable as ``for code, message in violations`` at every existing call site.
    The ``code`` is always one of ``REJECTION_CODES`` (the matrix is closed at
    seventeen); ``_StopValidation`` enforces that at its raise boundary and the
    suite pins it for the collected list.
    """

    code: str
    message: str


class _StopValidation(Exception):
    """Raised for a fatal load/shape failure — no further checks are meaningful."""

    def __init__(self, code, message):
        super().__init__(message)
        # The matrix is closed at seventeen: a fatal code outside REJECTION_CODES
        # is a programming error, caught here at the raise boundary rather than
        # only by the suite (Python 3.14 forbids overriding __new__ on the
        # Violation NamedTuple, so the collected-list codes stay suite-pinned).
        if code not in REJECTION_CODES:
            raise ValueError(f"_StopValidation code {code!r} not in REJECTION_CODES")
        self.code = code
        self.message = message


class _DuplicateKeyError(ValueError):
    """Raised by the JSON object hook on a duplicate key — caught by type, not by
    a message-prefix match (so a future message reword cannot silently reclassify
    a DUPLICATE_KEY manifest as INVALID_JSON)."""


def _no_duplicate_keys(pairs):
    """object_pairs_hook that rejects a duplicate key at any nesting level."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyError(f"duplicate key: {key!r}")
        seen[key] = value
    return seen


def _load(path):
    """Return the parsed top-level object or raise _StopValidation.

    Covers classes 1 (absent), 2 (unreadable), 3 (invalid JSON), 9 (duplicate key).
    """
    p = Path(path)
    if not p.exists():
        raise _StopValidation(ABSENT_FILE, f"manifest file does not exist: {path}")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise _StopValidation(UNREADABLE_FILE, f"manifest file unreadable: {exc}")
    except UnicodeDecodeError as exc:
        raise _StopValidation(UNREADABLE_FILE, f"manifest file not UTF-8: {exc}")
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise _StopValidation(DUPLICATE_KEY, str(exc))
    except ValueError as exc:
        raise _StopValidation(INVALID_JSON, f"manifest is not valid JSON: {exc}")


def _check_top_level_shape(obj):
    """Covers classes 4/5/6 and any other non-object top-level value."""
    if isinstance(obj, dict):
        return
    if isinstance(obj, list):
        raise _StopValidation(TOP_LEVEL_ARRAY, "top-level value is a JSON array")
    if isinstance(obj, str):
        raise _StopValidation(TOP_LEVEL_STRING, "top-level value is a JSON string")
    if obj is False:
        raise _StopValidation(TOP_LEVEL_FALSE, "top-level value is the valid-falsy `false`")
    raise _StopValidation(
        WRONG_FIELD_TYPE, f"top-level value is not an object (got {type(obj).__name__})"
    )


def _path_is_safe(key, base_resolved):
    """A files key must be a relative path that stays beneath base_resolved.

    base_resolved is a pre-resolved Path so the caller resolves the base once
    instead of per manifest entry.
    """
    if key.startswith("/") or "\\" in key or posixpath.isabs(key):
        return False
    normalized = posixpath.normpath(key)
    if normalized == ".." or normalized.startswith("../"):
        return False
    resolved = (base_resolved / normalized).resolve()
    return base_resolved == resolved or base_resolved in resolved.parents


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(
    manifest_path=None,
    *,
    base_dir=None,
    expected_assets=None,
    required_profiles=None,
    profile_grants=None,
):
    """Validate the manifest. Return a list of Violation(code, message) records.

    Dependencies are injectable so the closed rejection matrix is unit-testable:
      * expected_assets    — AC1-reached repo-relative asset paths (class 15)
      * required_profiles  — cloud profile ids that must be present (class 16)
      * profile_grants     — {profile: set(granted vendored heads)} (class 17)
    Defaults are derived from the sibling reachability contract and the workflows.
    """
    manifest_path = manifest_path or _MANIFEST_DEFAULT
    base_dir = base_dir if base_dir is not None else REPO_ROOT

    if expected_assets is None or required_profiles is None or profile_grants is None:
        # The default derivation reads the sibling contract module and the
        # workflows. A malformed contract constant (e.g. a helper token missing
        # the vendor prefix → _helper_source_path raises) must surface as a clean
        # single violation on the documented stdout channel, not an uncaught
        # traceback — check_closure guards these constants, but validate()/main()
        # can be called without it, so fail closed here too.
        try:
            contract = _load_contract_module()
            if expected_assets is None:
                expected_assets = contract.manifest_file_paths()
            if required_profiles is None:
                required_profiles = list(contract.ROOTS.keys())
            if profile_grants is None:
                profile_grants = {
                    p: extract_profile_grants(base_dir / contract.ROOTS[p]["workflow"])
                    for p in contract.ROOTS
                }
        except Exception as exc:
            return [Violation(WRONG_FIELD_TYPE,
                              f"could not derive default validation dependencies from the "
                              f"reachability contract: {exc}")]

    try:
        obj = _load(manifest_path)
        _check_top_level_shape(obj)
    except _StopValidation as stop:
        return [Violation(stop.code, stop.message)]

    violations = []

    # Classes 7/8: required and extra top-level keys.
    keys = set(obj)
    for missing in sorted(REQUIRED_KEYS - keys):
        violations.append(Violation(MISSING_KEY, f"required top-level key absent: {missing}"))
    for extra in sorted(keys - REQUIRED_KEYS):
        violations.append(Violation(EXTRA_KEY, f"unexpected top-level key: {extra}"))

    # Class 10: field types (and the exact protocol value).
    protocol = obj.get("protocol")
    if "protocol" in obj:
        if not isinstance(protocol, str):
            violations.append(Violation(WRONG_FIELD_TYPE, "protocol is not a string"))
        elif protocol != PROTOCOL:
            violations.append(
                Violation(WRONG_FIELD_TYPE, f"protocol is {protocol!r}, expected {PROTOCOL!r}")
            )
    if "legacy_profile_baseline" in obj and not isinstance(
        obj.get("legacy_profile_baseline"), str
    ):
        violations.append(Violation(WRONG_FIELD_TYPE, "legacy_profile_baseline is not a string"))

    files = obj.get("files")
    if "files" in obj and not isinstance(files, dict):
        violations.append(Violation(WRONG_FIELD_TYPE, "files is not an object"))
        files = None
    heads = obj.get("required_helper_heads")
    if "required_helper_heads" in obj and not isinstance(heads, dict):
        violations.append(Violation(WRONG_FIELD_TYPE, "required_helper_heads is not an object"))
        heads = None

    # Classes 11/12/13/14: files content binding.
    if isinstance(files, dict):
        base_resolved = Path(base_dir).resolve()
        for rel, digest in sorted(files.items()):
            if not isinstance(digest, str) or not _HEX64.match(digest):
                violations.append(Violation(MALFORMED_DIGEST, f"malformed digest for {rel}: {digest!r}"))
                continue
            if not _path_is_safe(rel, base_resolved):
                violations.append(Violation(INVALID_PATH, f"invalid or escaping relative path: {rel}"))
                continue
            disk = base_resolved / rel
            if not disk.is_file():
                violations.append(Violation(MISSING_ASSET, f"listed file does not exist: {rel}"))
                continue
            actual = _sha256(disk)
            if actual != digest:
                violations.append(
                    Violation(HASH_MISMATCH, f"hash mismatch for {rel}: manifest {digest}, disk {actual}")
                )

        # Class 15: every AC1-reached asset must appear in files.
        for rel in expected_assets:
            if rel not in files:
                violations.append(
                    Violation(REACHED_ASSET_OMITTED, f"AC1-reached asset omitted from files: {rel}")
                )

    # Classes 16/17: profile binding.
    if isinstance(heads, dict):
        for profile in required_profiles:
            if profile not in heads:
                violations.append(Violation(PROFILE_OMITTED, f"required cloud profile omitted: {profile}"))
                continue
            declared = heads.get(profile)
            if not isinstance(declared, list):
                violations.append(
                    Violation(WRONG_FIELD_TYPE, f"required_helper_heads[{profile}] is not a list")
                )
                continue
            granted = profile_grants.get(profile, set())
            for head in declared:
                if head not in granted:
                    violations.append(
                        Violation(HEAD_ABSENT, f"required head absent from {profile} grants: {head}")
                    )

    return violations


def _load_contract_module():
    """Import the sibling AC1 reachability contract (lib/test/cloud_writer_contract.py)."""
    contract_dir = REPO_ROOT / "lib" / "test"
    if str(contract_dir) not in sys.path:
        sys.path.insert(0, str(contract_dir))
    import cloud_writer_contract

    return cloud_writer_contract


# A vendored helper is *granted* only as the leading token of a `Bash(...)` tool
# spec — never a bare mention. Anchoring on `Bash(` is what keeps a vendored path
# that appears only in a YAML comment or a shell assignment (e.g.
# `CG=.prflow/vendor/prflow/scripts/config-get.sh`) from being counted as a
# grant, which would make class 17 (HEAD_ABSENT) fail open. (The authoritative
# comment-aware allowlist scoping is lib/test/extract-command-heads.py, wired by
# the deferred grant-synchronization work, AC9 of #543.)
_GRANT_RE = re.compile(
    r"Bash\(\s*(\.prflow/vendor/prflow/(?:scripts|lib)/[A-Za-z0-9._-]+)"
)


def extract_profile_grants(workflow_path):
    """Return the set of vendored helper leading tokens granted in a workflow file.

    Returns an empty set when the workflow cannot be read, emitting a stderr
    breadcrumb naming the unreadable path so the resulting HEAD_ABSENT
    violations are not misattributed to the manifest (unknown is not zero — the
    grant source was unestablished, not empty).
    """
    try:
        text = Path(workflow_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"cloud-writer-contract: could not read grant source {workflow_path}: "
            f"{exc}; treating its granted heads as empty (HEAD_ABSENT will follow)",
            file=sys.stderr,
        )
        return set()
    # Drop full-line YAML comments before matching, so a `# was: Bash(.../x.sh:*)`
    # commented-out grant is not counted. (This narrows, but does not fully close,
    # the fail-open surface — an inline trailing `#` comment on a grant line, or a
    # `Bash(...)` inside a quoted example, still matches. The authoritative
    # comment-aware allowlist scoping is lib/test/extract-command-heads.py, wired
    # by the deferred grant-synchronization work, AC9 of #543.)
    scanned = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    return set(_GRANT_RE.findall(scanned))


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    manifest_path = argv[0] if argv else _MANIFEST_DEFAULT
    violations = validate(manifest_path)
    if violations:
        for code, message in violations:
            print(f"cloud-writer-contract INVALID [{code}]: {message}")
        return 1
    print("cloud-writer-contract: manifest valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

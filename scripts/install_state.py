#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Build, validate, and gate on `.prflow/install-state.json` (issue #1388).

`.prflow/install-state.json` is the digest-bound compatibility-tuple marker the
installer publishes **last**, only after staging and validating the set of
components that must ship together — the lint manifest, its reader/validator,
the `setup-project-env` composite action, and the shipped workflow templates.
The composite action's provisioning phase consults this marker *before model
execution* and refuses to provision when it is absent, a recorded component's
on-disk digest disagrees (a version-skew in either direction, or an
interrupted/partial publication), or the manifest is missing or invalid.

The marker carries the installer version (the missing sixth field of the
provisioning cache key `{OS, arch, tool, version, digest, installer version}`)
so a re-install under a newer installer invalidates a cache built by the old one.

This module is the single source of truth for the marker's shape. Like
`scripts/lint_manifest.py` it is a **best-effort reader** over agent- and
human-mutable JSON: every degraded shape resolves to a typed **unestablished**
result carrying a specific reason, never a plausible-but-unobserved clean pass.
*Unknown is not zero.*
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
# An installer version is a git ref / semver-ish token: no shell metacharacters,
# no whitespace, so it can never be a command string spliced into the cache key.
_INSTALLER_VERSION_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
# A component name is a closed-vocabulary identifier the trusted installer sets.
_NAME_RE = re.compile(r"\A[a-z0-9][a-z0-9-]*\Z")


def _load_lint_manifest():
    path = _HERE / "lint_manifest.py"
    spec = importlib.util.spec_from_file_location("lint_manifest", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load lint_manifest from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint_manifest = _load_lint_manifest()


class StateResult:
    """Typed outcome of a marker read: `established` XOR `unestablished`."""

    __slots__ = ("state", "reason", "status")

    def __init__(self, status: str, *, state=None, reason: str | None = None):
        if status not in ("established", "unestablished"):
            raise ValueError(f"invalid state-result status: {status!r}")
        self.status = status
        self.state = state
        self.reason = reason

    @property
    def established(self) -> bool:
        return self.status == "established"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        if self.established:
            return "StateResult(established)"
        return f"StateResult(unestablished: {self.reason})"


class Readiness:
    """Typed provisioning-readiness verdict: `ready` XOR not.

    `reason` names the specific fail-closed condition (`install-state-missing`,
    `manifest-missing`, `manifest-unestablished:<r>`, `component-missing:<name>`,
    `digest-mismatch:<name>`, or a marker-validation reason) so the workflow step
    can fail *before model execution* naming exactly what was wrong.
    """

    __slots__ = ("ready", "reason")

    def __init__(self, ready: bool, reason: str | None = None):
        self.ready = ready
        self.reason = reason


def _unestablished(reason: str) -> StateResult:
    return StateResult("unestablished", reason=reason)


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


def digest_bytes(raw: bytes) -> str:
    """`sha256:<64-hex>` of `raw`, the digest spelling the marker and the manifest
    both use (mirrors install.sh's python3-hashlib `devflow_digest`)."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def digest_file(path) -> str | None:
    """`sha256:` digest of the file at `path`, or `None` when it cannot be read —
    the caller maps `None` to `component-missing`, never to a clean digest."""
    try:
        return digest_bytes(Path(path).read_bytes())
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen[key] = value
    return seen


def load_state(path) -> StateResult:
    """Read and validate a marker from `path`, fail-closed on every I/O and decode
    failure (missing, unreadable, non-UTF-8, empty each a distinct reason)."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return _unestablished("install-state-missing")
    except (IsADirectoryError, PermissionError, OSError) as exc:
        return _unestablished(f"unreadable: {exc.__class__.__name__}")
    return parse_state(raw)


def parse_state(raw: bytes) -> StateResult:
    if not isinstance(raw, (bytes, bytearray)):
        return _unestablished("wrong-type: marker bytes must be a byte string")
    if len(raw) == 0:
        return _unestablished("empty: marker file is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _unestablished("invalid-utf8: marker is not valid UTF-8")
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKey as exc:
        return _unestablished(f"duplicate-key: repeated object key {exc.args[0]!r}")
    except json.JSONDecodeError as exc:
        return _unestablished(f"malformed-json: {exc.msg}")
    except RecursionError:
        return _unestablished("malformed-json: input nesting too deep")
    return validate_state(data)


def validate_state(data) -> StateResult:
    """Validate an already-parsed marker object."""
    if isinstance(data, bool) or not isinstance(data, dict):
        return _unestablished(f"wrong-type: top level is a {_json_kind(data)}, expected object")

    required = ("schema_version", "installer_version", "components")
    for key in data:
        if key not in required:
            return _unestablished(f"unknown-field: unknown top-level key {key!r}")
    for key in required:
        if key not in data:
            return _unestablished(f"missing: required top-level key {key!r}")

    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        return _unestablished("wrong-type: schema_version must be an integer")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return _unestablished(f"unknown-version: schema_version {version} unsupported")

    iv = data["installer_version"]
    if not isinstance(iv, str) or not _INSTALLER_VERSION_RE.match(iv):
        return _unestablished(f"invalid-value: installer_version {iv!r}")

    components = data["components"]
    if not isinstance(components, dict) or not components:
        return _unestablished("invalid-value: components must be a non-empty object")
    for name, comp in components.items():
        if not _NAME_RE.match(name):
            return _unestablished(f"invalid-value: component name {name!r}")
        if not isinstance(comp, dict):
            return _unestablished(f"wrong-type: component {name!r} is a {_json_kind(comp)}")
        for key in comp:
            if key not in ("path", "digest"):
                return _unestablished(f"unknown-field: component {name!r} key {key!r}")
        for key in ("path", "digest"):
            if key not in comp:
                return _unestablished(f"missing: component {name!r} key {key!r}")
        path = comp["path"]
        if not isinstance(path, str) or not path or path.startswith("/") \
                or any(seg == ".." for seg in path.split("/")):
            return _unestablished(f"invalid-value: component {name!r} path {path!r}")
        digest = comp["digest"]
        if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
            return _unestablished(f"invalid-value: component {name!r} digest {digest!r}")

    return StateResult("established", state=data)


def build_state(installer_version: str, components: dict, repo_root=".",
                record_paths=None) -> dict:
    """Build a marker dict from `components` (name → the path DIGESTED, resolved
    under `repo_root`). Each component's recorded path defaults to the digested
    path; `record_paths` (name → recorded path) overrides it, so the installer can
    digest a SOURCE-tree file while recording the RUNTIME path a thin consumer will
    verify (the install-channel skew: workflows/manifest ship via install.sh's copy
    loop, helpers via the runtime vendor fetch — identical bytes at the pinned ref).
    Raises `ValueError` for an unreadable component so the installer fails BEFORE
    publishing a marker binding a file it cannot read."""
    root = Path(repo_root)
    record_paths = record_paths or {}
    out = {}
    for name, rel in components.items():
        dig = digest_file(root / rel)
        if dig is None:
            raise ValueError(f"cannot digest component {name!r} at {rel!r}")
        out[name] = {"path": record_paths.get(name, rel), "digest": dig}
    return {
        "schema_version": 1,
        "installer_version": installer_version,
        "components": out,
    }


def check_readiness(state_path, manifest_path, repo_root=".") -> Readiness:
    """Gate provisioning on the marker. Fail-closed: any absent/invalid/mismatched
    input returns `ready=False` with a specific reason, never a clean pass.

    Order matters — the marker is checked first (a `backfill`/`missing-marker`
    install has components on disk but no marker and must refuse), then the
    manifest, then every recorded component's on-disk digest (a `version-skew` in
    either direction or an interrupted publication flips a digest)."""
    root = Path(repo_root)
    sr = load_state(state_path)
    if not sr.established:
        return Readiness(False, sr.reason)

    mr = lint_manifest.load_manifest(manifest_path)
    if not mr.established:
        # A missing manifest is the AC's dedicated `manifest-missing`; any other
        # unestablished shape carries the manifest reader's typed reason.
        if mr.reason and mr.reason.startswith("missing:"):
            return Readiness(False, "manifest-missing")
        return Readiness(False, f"manifest-unestablished:{mr.reason}")

    for name, comp in sr.state["components"].items():
        on_disk = digest_file(root / comp["path"])
        if on_disk is None:
            return Readiness(False, f"component-missing:{name}")
        if on_disk != comp["digest"]:
            return Readiness(False, f"digest-mismatch:{name}")

    return Readiness(True)


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    """CLI. Subcommands:

      `build --out P --installer-version V --component name=relpath ...`
          Stage-and-write the marker (digests computed from disk). Exit 0, or 1
          on a usage / unreadable-component error.
      `verify --state P --manifest P [--repo-root R]`
          Print `READY` (exit 0) or `NOT-READY <reason>` (exit 2); usage error
          exit 1 — the branch-on-exit-status contract the other helpers use.
    """
    _force_utf8_streams()
    import argparse

    parser = argparse.ArgumentParser(description="Build/verify the install-state compatibility marker.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build")
    pb.add_argument("--out", required=True)
    pb.add_argument("--installer-version", required=True)
    pb.add_argument("--component", action="append", default=[], metavar="NAME=PATH")
    pb.add_argument("--record-path", action="append", default=[], metavar="NAME=PATH")
    pb.add_argument("--repo-root", default=".")

    pv = sub.add_parser("verify")
    pv.add_argument("--state", required=True)
    pv.add_argument("--manifest", required=True)
    pv.add_argument("--repo-root", default=".")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        raise SystemExit(1 if exc.code else exc.code) from None

    if args.cmd == "build":
        components = {}
        for spec in args.component:
            if "=" not in spec:
                print(f"usage: --component expects NAME=PATH, got {spec!r}", file=sys.stderr)
                return 1
            name, rel = spec.split("=", 1)
            components[name] = rel
        if not components:
            print("usage: build needs at least one --component", file=sys.stderr)
            return 1
        record_paths = {}
        for spec in args.record_path:
            if "=" not in spec:
                print(f"usage: --record-path expects NAME=PATH, got {spec!r}", file=sys.stderr)
                return 1
            name, rel = spec.split("=", 1)
            record_paths[name] = rel
        try:
            state = build_state(args.installer_version, components, args.repo_root, record_paths)
        except ValueError as exc:
            print(f"build failed: {exc}", file=sys.stderr)
            return 1
        Path(args.out).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return 0

    verdict = check_readiness(args.state, args.manifest, args.repo_root)
    if verdict.ready:
        print("READY")
        return 0
    print(f"NOT-READY {verdict.reason}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

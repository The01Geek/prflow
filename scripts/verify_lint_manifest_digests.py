#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Download-and-verify every declared lint-manifest artifact digest (issue #2029).

The `lint-manifest` CI job's real-provisioning step exercises one platform
(linux-x86_64), so the manifest's other per-os/arch digests are hash-verified
nowhere: a wrong or transposed digest on a non-linux-x86_64 platform would ship
undetected until a consumer on that platform provisions and fails closed.

This verifier closes that gap without needing a runner of each platform. It
enumerates every declared `(tool, os, arch)` artifact from the manifest itself,
resolves each to its trusted upstream download URL and pinned digest through
`lint_provision.build_plan` (which keys the URL on the closed vocabulary and the
typed version, never a manifest-supplied string), downloads the artifact over
HTTPS, and `sha256`-compares the bytes against the declared digest.

It fails closed on every non-match: a declared artifact whose URL cannot be
resolved, a download error, a digest mismatch, or a manifest that declares no
artifacts at all. The verified count must equal the declared count, so a skipped
declared artifact fails the check rather than passing silently. It carries no
write credentials of its own and mutates nothing — it only reads the manifest and
fetches public release assets, so the untrusted-manifest CI job can run it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_sibling(name: str, filename: str):
    """Import a sibling script by path (its filename is not an importable module
    name). Fail closed if it cannot be loaded — the verifier must not proceed
    against an unreadable resolver."""
    path = _HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint_provision = _load_sibling("lint_provision", "lint_provision.py")
# lint_provision owns the manifest's artifact-shape layout (resolve_artifact /
# iter_declared_artifacts) and re-exports the validated manifest reader, so reuse
# both here rather than re-loading lint_manifest or re-walking the manifest shape.
load_manifest = lint_provision.lint_manifest.load_manifest
iter_declared_artifacts = lint_provision.iter_declared_artifacts

# Cap a single download so a malicious or mistaken URL cannot exhaust memory. The
# real assets are a few MB; 256 MiB is far above any of them and far below OOM.
_MAX_BYTES = 256 * 1024 * 1024
_HTTP_TIMEOUT_SECONDS = 120


def _default_fetch(url: str) -> bytes:
    """Download `url` and return its bytes, following redirects (GitHub release
    assets redirect to a CDN). Raises on any transport error or an oversized body."""
    with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
        data = resp.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError(f"download exceeded {_MAX_BYTES} bytes: {url}")
    return data


class ArtifactResult:
    """One declared artifact's verification outcome. `status` is one of
    `verified`, `unresolved` (no trusted URL/digest for a declared artifact),
    `fetch-error`, or `digest-mismatch`; only `verified` is a pass."""

    __slots__ = ("arch", "detail", "os", "status", "tool")

    def __init__(self, tool: str, os_name: str, arch: str, status: str, detail: str = ""):
        self.tool = tool
        self.os = os_name
        self.arch = arch
        self.status = status
        self.detail = detail

    @property
    def ok(self) -> bool:
        return self.status == "verified"

    def line(self) -> str:
        mark = "OK" if self.ok else "FAIL"
        base = f"{mark} {self.tool} {self.os}/{self.arch} {self.status}"
        return f"{base}: {self.detail}" if self.detail else base


class VerifyResult:
    """The whole-manifest outcome. `ok` is true only when the manifest was
    established, it declared at least one artifact, and every declared artifact
    verified."""

    __slots__ = ("ok", "reason", "results")

    def __init__(self, ok: bool, reason: str, results: list[ArtifactResult]):
        self.ok = ok
        self.reason = reason
        self.results = results


def verify_manifest_digests(manifest_path, fetch=None) -> VerifyResult:
    """Download and digest-verify every declared artifact in the manifest at
    `manifest_path`. `fetch` maps a URL to its bytes (injected in tests);
    defaults to an HTTPS downloader."""
    if fetch is None:
        fetch = _default_fetch

    loaded = load_manifest(manifest_path)
    if not loaded.established:
        return VerifyResult(False, f"unestablished manifest: {loaded.reason}", [])
    manifest = loaded.manifest

    declared = iter_declared_artifacts(manifest)
    if not declared:
        return VerifyResult(False, "manifest declares no artifacts", [])

    results: list[ArtifactResult] = []
    for tool, os_name, arch in declared:
        plan = lint_provision.build_plan(manifest_path, tool, os_name, arch)
        if plan.status != "established":
            results.append(ArtifactResult(
                tool, os_name, arch, "unresolved",
                f"no trusted URL/digest for a declared artifact ({plan.reason})"))
            continue
        try:
            data = fetch(plan.url)
        except Exception as exc:  # a fetch failure of any kind must fail closed with a breadcrumb
            results.append(ArtifactResult(
                tool, os_name, arch, "fetch-error", f"{plan.url}: {exc}"))
            continue
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual == plan.digest:
            results.append(ArtifactResult(tool, os_name, arch, "verified", plan.url))
        else:
            results.append(ArtifactResult(
                tool, os_name, arch, "digest-mismatch",
                f"{plan.url}: declared {plan.digest}, downloaded {actual}"))

    verified = sum(1 for r in results if r.ok)
    ok = verified == len(declared)
    reason = (f"verified {verified}/{len(declared)} declared artifacts"
              if ok else
              f"only {verified}/{len(declared)} declared artifacts verified")
    return VerifyResult(ok, reason, results)


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    """CLI: `verify_lint_manifest_digests.py <manifest-path>`. Prints one line per
    declared artifact and a summary; exits 0 only when every declared artifact
    verified, 1 otherwise."""
    _force_utf8_streams()
    import argparse

    parser = argparse.ArgumentParser(
        description="Download and sha256-verify every declared lint-manifest artifact digest.")
    parser.add_argument("manifest", help="path to the lint manifest JSON")
    args = parser.parse_args(argv)

    result = verify_manifest_digests(args.manifest)
    for r in result.results:
        print(r.line())
    if result.ok:
        print(f"PASS: {result.reason}")
        return 0
    print(f"FAIL: {result.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

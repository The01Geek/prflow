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
resolved, a download error that persists after a bounded transient retry, a digest
mismatch, or a manifest that declares no
artifacts at all. The verified count must equal the declared count, so a skipped
declared artifact fails the check rather than passing silently. It carries no
write credentials of its own and mutates nothing — it only reads the manifest and
fetches public release assets, so the untrusted-manifest CI job can run it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import http.client
import importlib.util
import sys
import time
import urllib.error
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
# Bounded transient-download retry (issue #493): one 5xx/timeout/dropped connection
# must not redden an unrelated PR's CI. _FETCH_RETRY_DELAYS[attempt-1] is the wait
# before the next attempt, so it must stay exactly one shorter than
# _FETCH_MAX_ATTEMPTS or the final retry IndexErrors.
_FETCH_MAX_ATTEMPTS = 3
_FETCH_RETRY_DELAYS = (2, 4)


class FetchError(RuntimeError):
    """Raised by `_default_fetch` when a download fails after exhausting the
    transient-retry attempts, or on a non-transient error. The raise site formats
    the attempt count into the message, so the fetch-error result line reports how
    many tries were made."""


def _is_transient(exc: BaseException) -> bool:
    """True for exactly the six retry-eligible transport failures of issue #493,
    complete by construction. An HTTPError is classified by its status code alone and
    checked BEFORE the URLError arm — HTTPError subclasses URLError, so a 404 would
    otherwise be retried under the URLError rule and never fail fast."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    if isinstance(exc, urllib.error.URLError):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError, http.client.HTTPException))


def _default_fetch(url: str) -> bytes:
    """Download `url` and return its bytes, following redirects (GitHub release
    assets redirect to a CDN). The download is attempted up to `_FETCH_MAX_ATTEMPTS`
    times in total; a transient transport failure (see `_is_transient`) is retried on
    the `_FETCH_RETRY_DELAYS` backoff (so at most `_FETCH_MAX_ATTEMPTS - 1` retries),
    printing one stderr breadcrumb per retry, while a non-transient error (e.g. a 404)
    ends the attempts at once. Raises `FetchError` once the attempts are exhausted or
    on a non-transient error, or `ValueError` on an oversized body."""
    data = b""
    for attempt in range(1, _FETCH_MAX_ATTEMPTS + 1):
        try:
            # urlopen AND read share one try: an http.client.HTTPException raised by
            # read() mid-stream is as transient as one from urlopen and must retry.
            with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
                data = resp.read(_MAX_BYTES + 1)
            break
        except Exception as exc:
            if _is_transient(exc) and attempt < _FETCH_MAX_ATTEMPTS:
                delay = _FETCH_RETRY_DELAYS[attempt - 1]
                print(f"retry {url}: attempt {attempt} failed, waiting {delay}s: {exc}",
                      file=sys.stderr)
                time.sleep(delay)
                continue
            attempts = "attempt" if attempt == 1 else "attempts"
            raise FetchError(f"{exc} (after {attempt} {attempts})") from exc
    if len(data) > _MAX_BYTES:
        raise ValueError(f"download exceeded {_MAX_BYTES} bytes: {url}")
    return data


@dataclasses.dataclass(frozen=True, slots=True)
class ArtifactResult:
    """One declared artifact's verification outcome. `status` is one of
    `verified`, `unresolved` (no trusted URL/digest for a declared artifact),
    `fetch-error`, or `digest-mismatch`; only `verified` is a pass.

    Frozen: the record is written once at construction, so the status check below
    is a lifetime guarantee rather than a construction-time one."""

    # Closed vocabulary, enforced in __post_init__: a misspelled status must not
    # read as a silent not-ok, which would make a failing artifact
    # indistinguishable from a real rejection reason in the printed line.
    STATUSES = ("verified", "unresolved", "fetch-error", "digest-mismatch")

    tool: str
    os: str
    arch: str
    status: str
    detail: str = ""

    def __post_init__(self):
        if self.status not in self.STATUSES:
            raise ValueError(
                f"unknown artifact status {self.status!r}; expected one of {self.STATUSES}")

    @property
    def ok(self) -> bool:
        return self.status == "verified"

    def line(self) -> str:
        mark = "OK" if self.ok else "FAIL"
        base = f"{mark} {self.tool} {self.os}/{self.arch} {self.status}"
        return f"{base}: {self.detail}" if self.detail else base


@dataclasses.dataclass(frozen=True, slots=True)
class VerifyResult:
    """The whole-manifest outcome. `ok` is true only when the manifest was
    established, it declared at least one artifact, and every declared artifact
    verified.

    Frozen, with `results` stored as a tuple: a mutable `results` list would let a
    caller append a failed artifact to an `ok` record after construction, re-opening
    the exact state the checks below reject."""

    ok: bool
    reason: str
    results: tuple[ArtifactResult, ...]

    def __post_init__(self):
        object.__setattr__(self, "results", tuple(self.results))
        # Do not relax: a true `ok` carrying no results is the "clean pass with
        # nothing verified" state this verifier exists to make impossible, and a
        # true `ok` beside a failed result would report a pass over a mismatch.
        if self.ok and not self.results:
            raise ValueError(f"ok result verified nothing: {self.reason}")
        if self.ok and not all(r.ok for r in self.results):
            raise ValueError(f"ok result carries a non-verified artifact: {self.reason}")


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

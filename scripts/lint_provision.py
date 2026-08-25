#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Platform-resolution query over the declarative lint manifest (issue #1388).

The provisioning layer (the `setup-project-env` composite action's
`provision-lint-tools.sh`) needs, for the runner it is on, the one artifact
record the manifest declares for `(tool, os, arch)` — its pinned digest, the
archive type, the member to extract, and the strategy — plus the trusted
download URL and the run-local cache key. This module answers exactly that.

It assembles NOTHING executable from the manifest: the manifest never carries a
command string or URL template (`scripts/lint_manifest.py` rejects those field
shapes), so the URL templates below are fixed, trusted code keyed on the closed
`(tool, os, arch)` vocabulary
and the manifest's typed `version` field — never a manifest-supplied string
(issue #1276's trust model). The manifest is read and validated through
`scripts/lint_manifest.py`; this module reimplements none of that.

`unsupported-lint-platform` is the one non-error "no answer" outcome: a fully
valid manifest that simply declares no artifact for the requested `(os, arch)`
under the requested tool. It is distinct from an *unestablished* manifest (a
missing, malformed, or invalid file), which carries a typed reason. *Unknown is
not zero.*
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_lint_manifest():
    """Import the sibling `lint_manifest.py` by path (its filename is not a
    module name). Fail closed if it cannot be loaded — the provisioner must not
    proceed against an unreadable validator."""
    path = _HERE / "lint_manifest.py"
    spec = importlib.util.spec_from_file_location("lint_manifest", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load lint_manifest from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint_manifest = _load_lint_manifest()

# ── Closed platform vocabulary (mirrors the manifest's own). A tuple outside
#    this set is `unsupported-lint-platform`, never an error. ──────────────────
KNOWN_TOOLS = ("shellcheck", "ruff")
KNOWN_OS = ("linux", "macos", "windows")
KNOWN_ARCH = ("x86_64", "arm64")

# ── Trusted download-URL templates. Keyed on the closed (tool, os, arch)
#    vocabulary and the manifest's typed `version`; NEVER a manifest-supplied
#    string. `{version}` is the manifest's `version` field (typed `\d+(\.\d+)+`),
#    so no shell metacharacter can reach the URL. These map the closed strategy
#    IDs to fixed upstream release layouts (issue #1276). ───────────────────────
_SHELLCHECK_OS = {"linux": "linux", "macos": "darwin", "windows": "windows"}
_SHELLCHECK_ARCH = {"x86_64": "x86_64", "arm64": "aarch64"}
_RUFF_TARGET = {
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("macos", "x86_64"): "x86_64-apple-darwin",
    ("macos", "arm64"): "aarch64-apple-darwin",
    ("windows", "x86_64"): "x86_64-pc-windows-msvc",
}


def artifact_url(tool: str, version: str, os_name: str, arch: str, archive_type: str) -> str | None:
    """Build the trusted upstream download URL for one artifact, or `None` when
    no template covers `(tool, os, arch)` — the caller maps that to
    `unsupported-lint-platform`."""
    if tool == "shellcheck":
        so = _SHELLCHECK_OS.get(os_name)
        sa = _SHELLCHECK_ARCH.get(arch)
        if so is None or sa is None:
            return None
        if os_name == "windows":
            # Upstream ships a single per-release zip for Windows.
            return (f"https://github.com/koalaman/shellcheck/releases/download/"
                    f"v{version}/shellcheck-v{version}.zip")
        return (f"https://github.com/koalaman/shellcheck/releases/download/"
                f"v{version}/shellcheck-v{version}.{so}.{sa}.{archive_type}")
    if tool == "ruff":
        target = _RUFF_TARGET.get((os_name, arch))
        if target is None:
            return None
        return (f"https://github.com/astral-sh/ruff/releases/download/"
                f"{version}/ruff-{target}.{archive_type}")
    return None


def resolve_artifact(manifest: dict, tool: str, os_name: str, arch: str) -> dict | None:
    """Return the validated artifact record for `(tool, os, arch)`, or `None`
    when the manifest declares none (`unsupported-lint-platform`). `manifest`
    must be an already-validated manifest dict."""
    tool_obj = manifest.get("tools", {}).get(tool)
    if not isinstance(tool_obj, dict):
        return None
    for art in tool_obj.get("artifacts", []):
        if art.get("os") == os_name and art.get("arch") == arch:
            return art
    return None


def cache_key(os_name: str, arch: str, tool: str, version: str, digest: str,
              installer_version: str) -> str:
    """The run-local cache key `{OS, arch, tool, version, digest, installer version}`
    (issue #1388 AC). A change to any component invalidates the cache, so a stale
    binary can never satisfy a changed tuple. The digest is normalized to its
    64-hex body (the `sha256:` prefix dropped) so the key stays field-delimited."""
    dig = digest[len("sha256:"):] if digest.startswith("sha256:") else digest
    return f"lintprov-{os_name}-{arch}-{tool}-{version}-{dig}-{installer_version}"


class Plan:
    """The resolved provisioning plan for one `(tool, os, arch)` — everything the
    shell provisioner needs, or a typed no-answer."""

    __slots__ = ("status", "reason", "tool", "os", "arch", "version",
                 "digest", "archive_type", "member", "strategy", "url")

    def __init__(self, status, **kw):
        self.status = status
        self.reason = kw.get("reason")
        for k in ("tool", "os", "arch", "version", "digest", "archive_type",
                  "member", "strategy", "url"):
            setattr(self, k, kw.get(k))


def build_plan(manifest_path, tool: str, os_name: str, arch: str) -> Plan:
    """Resolve the provisioning plan for one tuple. Outcomes:

    * `established` — a validated manifest declares the artifact and a trusted
      URL template covers the tuple.
    * `unsupported` — a *valid* manifest declares no artifact for the tuple, or
      no URL template covers it. (`reason='unsupported-lint-platform'`.)
    * `unestablished` — the manifest could not be read/validated (typed reason).
    """
    if tool not in KNOWN_TOOLS:
        return Plan("unsupported", reason="unsupported-lint-platform",
                    tool=tool, os=os_name, arch=arch)
    result = lint_manifest.load_manifest(manifest_path)
    if not result.established:
        return Plan("unestablished", reason=result.reason,
                    tool=tool, os=os_name, arch=arch)
    manifest = result.manifest
    art = resolve_artifact(manifest, tool, os_name, arch)
    if art is None:
        return Plan("unsupported", reason="unsupported-lint-platform",
                    tool=tool, os=os_name, arch=arch)
    version = manifest["tools"][tool]["version"]
    url = artifact_url(tool, version, os_name, arch, art["archive_type"])
    if url is None:
        return Plan("unsupported", reason="unsupported-lint-platform",
                    tool=tool, os=os_name, arch=arch)
    return Plan("established", tool=tool, os=os_name, arch=arch, version=version,
                digest=art["digest"], archive_type=art["archive_type"],
                member=art["member"], strategy=art["strategy"], url=url)


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    """CLI. Subcommands `plan` and `cache-key`, each printing one machine-readable
    line with a branch-on-exit-status contract:

      exit 0 — established (the resolved fields / the cache key)
      exit 2 — unestablished manifest (`UNESTABLISHED <reason>`)
      exit 3 — `unsupported-lint-platform`
      exit 1 — usage error
    """
    _force_utf8_streams()
    import argparse

    parser = argparse.ArgumentParser(description="Resolve lint provisioning plans from the manifest.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "cache-key"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True)
        p.add_argument("--tool", required=True)
        p.add_argument("--os", required=True, dest="os_name")
        p.add_argument("--arch", required=True)
        if name == "cache-key":
            p.add_argument("--installer-version", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        raise SystemExit(1 if exc.code else 0) from None

    plan = build_plan(args.manifest, args.tool, args.os_name, args.arch)
    if plan.status == "unestablished":
        print(f"UNESTABLISHED {plan.reason}")
        return 2
    if plan.status == "unsupported":
        print("unsupported-lint-platform")
        return 3
    if args.cmd == "cache-key":
        print(cache_key(plan.os, plan.arch, plan.tool, plan.version, plan.digest,
                        args.installer_version))
        return 0
    # plan: tab-separated so a shell `read` can split it field-by-field.
    print("\t".join([plan.digest, plan.archive_type, plan.member, plan.strategy,
                     plan.version, plan.url]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

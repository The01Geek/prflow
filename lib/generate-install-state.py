#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Generate this repository's tracked `.prflow/install-state.json` (issue #1388).

`.prflow/install-state.json` is the digest-bound compatibility-tuple marker: it
binds the lint manifest, its reader/validator, the provisioning helpers, the
`setup-project-env` composite action, and the shipped implement workflow by
sha256 digest, plus the installer version. The provisioning phase refuses to run
when any bound component's on-disk digest disagrees.

This repository dogfoods PRFlow, so it TRACKS its own marker (force-added past
`.gitignore`, like `.prflow/config.json`). The marker is therefore a **generated
artifact**: whenever a bound component changes, re-run this generator and commit
the refreshed marker. `--check` (used by the suite) fails RED on drift, naming
the regeneration command — the same fail-on-drift contract the other generated
artifacts carry.

A thin consumer's marker is instead published by `install.sh` at install time
over that consumer's own runtime paths; this generator is only for the primary
repo's committed copy.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MARKER = _REPO_ROOT / ".prflow" / "install-state.json"

# The compatibility tuple: every component whose bytes must agree for lint
# provisioning to be safe, named by its repo-root path. NAME → repo-relative path.
COMPONENTS = {
    "manifest": ".prflow/lint-manifest.json",
    "manifest-reader": "scripts/lint_manifest.py",
    "lint-provision": "scripts/lint_provision.py",
    "install-state-reader": "scripts/install_state.py",
    "setup-action": ".github/actions/setup-project-env/action.yml",
    "provision-helper": ".github/actions/setup-project-env/provision-lint-tools.sh",
    "implement-workflow": ".github/workflows/devflow-implement.yml",
}


def _load_install_state():
    path = _REPO_ROOT / "scripts" / "install_state.py"
    spec = importlib.util.spec_from_file_location("install_state", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load install_state from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _installer_version(repo_root: Path) -> str:
    """The installer version stamped into the marker. This repo pins it to
    `.prflow/config.json`'s `prflow_version` (the ref its runtime fetch tracks),
    which is stable for the dogfood repo."""
    cfg = repo_root / ".prflow" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    iv = data.get("prflow_version")
    if not isinstance(iv, str) or not iv:
        raise ValueError("prflow_version missing/empty in .prflow/config.json")
    return iv


def build(repo_root: Path) -> dict:
    install_state = _load_install_state()
    return install_state.build_state(_installer_version(repo_root), COMPONENTS, repo_root=repo_root)


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Refuse an unrecognized argument instead of ignoring it: a typo like `--chek`
    # silently took the write path and rewrote the marker the caller asked it to check.
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"usage: generate-install-state.py [--check] (unrecognized: {unknown})",
              file=sys.stderr)
        return 2
    check = "--check" in argv
    # Guard on lib/test: it is absent from BOTH consumer trees, while .github ships in the
    # distribution tree. Keying on .github passes there and defeats this guard entirely.
    if not (_REPO_ROOT / "lib" / "test").is_dir():
        print(
            "generate-install-state.py: lib/test absent — this tool only applies "
            "inside a PRFlow development tree; nothing to do."
        )
        return 0
    fresh = build(_REPO_ROOT)
    serialized = json.dumps(fresh, indent=2) + "\n"
    if check:
        try:
            current = _MARKER.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        if current != serialized:
            print("install-state DRIFT: .prflow/install-state.json is out of date.", file=sys.stderr)
            print("Regenerate with: python3 lib/generate-install-state.py", file=sys.stderr)
            return 1
        return 0
    _MARKER.write_text(serialized, encoding="utf-8")
    print(f"wrote {_MARKER.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

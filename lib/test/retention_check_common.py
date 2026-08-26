#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared plumbing for the CI-side merge-base retention checks.

Two diff-time retention gates compare a checked-in artifact at the merge base against the
same artifact in the working tree and refuse a silent regression:

* `coverage-map-retention-check.py` (issue #1194) — a dropped coverage-map key/content.
* `assertion-floor-retention-check.py` (issue #1287) — a lowered test-module assertion floor.

Their per-concern cores (`detect_losses` / `detect_decreases`, the allow-index shape, and
`classify_outcome`'s report wording) legitimately differ. But the plumbing beneath them —
resolving the base branch, resolving the merge base with a shallow-clone substitute-tip
fallback, and reading a JSON artifact out of a git ref — is comparand-agnostic and was
byte-identical across the two files. This module is that single source, so a fix to the
merge-base / shallow-clone / `git show` handling lands in one place rather than two hand-kept
copies (the coupled-mirror drift the repo's conventions warn against).

Importable under both invocation modes each check uses: run as a script from the repo root
(the script's own directory is on `sys.path`), and loaded by path via
`importlib.util.spec_from_file_location` in the focused tests (each check inserts its own
directory onto `sys.path` before importing this module, so the by-path load resolves it too).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def read_config_base(repo_root: Path) -> str:
    """The `base_branch` config value (default 'main'), read via the shared resolver so a
    consumer's master/develop trunk is honored. Best-effort: any failure falls back to 'main',
    which is the resolver's own default."""
    resolver = repo_root / "scripts" / "config-get.sh"
    try:
        result = subprocess.run(
            [str(resolver), ".base_branch", "main"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return "main"
    value = result.stdout.strip()
    return value or "main"


def git_show_json(repo_root: Path, ref: str, rel: str) -> tuple[object, str | None]:
    """Parse `git show <ref>:<rel>` as JSON. Returns (value, error).

    A path absent at REF (the artifact did not exist there) is the empty object, not an
    error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{ref}:{rel}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as error:
        return None, f"git show {ref}:{rel} failed ({error})"
    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        if "does not exist" in stderr or "exists on disk, but not in" in stderr:
            return {}, None
        return None, f"git show {ref}:{rel} failed: {result.stderr.strip()}"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as error:
        return None, f"{ref}:{rel} is malformed JSON ({error})"


def merge_base(repo_root: Path, base_ref: str) -> tuple[str | None, str | None, str | None]:
    """The merge base of HEAD and BASE_REF as (base, error, degraded_reason).

    Falls back to BASE_REF's own tip when a merge base cannot be computed (a shallow clone or
    any other git error). The substitute is semantically different from the true merge base —
    BASE_REF may have advanced past the fork point — so the fallback is reported as a DEGRADED
    reason the caller must resolve, never as a silent substitution. Returning it anyway lets
    the comparison still run and surface differences worth looking at; because the comparand is
    a substitute, the caller reports those as unconfirmed differences rather than as
    established regressions (a non-None degraded reason here is exactly what sets the caller's
    COMPARAND_SUBSTITUTED)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "HEAD", base_ref],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as error:
        return None, f"git merge-base failed ({error})", None
    if result.returncode != 0:
        return base_ref, None, (
            f"could not compute a merge base against {base_ref} "
            f"({result.stderr.strip() or 'git merge-base failed'}); compared against "
            f"{base_ref}'s tip instead — a shallow clone or a git error"
        )
    base = result.stdout.strip()
    if not base:
        # rc 0 with no output is the same silent substitution as the rc!=0 arm: git reported
        # no merge base at all, so BASE_REF's tip stands in for one.
        return base_ref, None, (
            f"git merge-base against {base_ref} succeeded but named no commit; compared "
            f"against {base_ref}'s tip instead"
        )
    return base, None, None

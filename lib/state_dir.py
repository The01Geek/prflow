#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""state_dir.py -- PRFlow's state-directory resolution contract for the PYTHON readers.

The shell sibling is ``lib/resolve-state-dir.sh``. The two are a COUPLED PAIR and
are edited together: a ``.sh`` cannot be exec'd from these readers on Windows
([WinError 193] -- the issue-#275 rule that keeps ``workpad.py`` reading its
config in-process), and a ``.py`` cannot be sourced into a shell. ``lib/test/run.sh``
pins both against ``lib/rename-map.json``.

THE TRANSITIONAL READ-THROUGH (issue #1002). The canonical directory is
``.prflow/``. A reader falls back to the superseded ``.devflow/`` ONLY when the
canonical path is absent AND the superseded one is present, and every such
resolution writes a stderr breadcrumb naming ``/prflow:init``.

Why a fallback exists here when issue #988 ruled one out for the config KEYS:
``/prflow:init`` registers the marketplace with ``autoUpdate: true``, so a
consumer's PLUGIN can update ahead of any migration run. Without the fallback the
next auto-update resolves an absent config and every ``// default`` extraction
silently reverts -- the exact silent revert the migration exists to prevent,
reached before any breadcrumb or gate could run. A LOUD fallback keeps the tree
working while staying observable, so it is not the unobservable-and-therefore-
permanent fallback #988 rejected. The key-level rule is unchanged: no
read-through for ``devflow_* -> prflow_*``.
"""
from __future__ import annotations

import os
import sys

# The two directory names. Coupled with lib/rename-map.json's `paths.state_dir`
# and with lib/resolve-state-dir.sh; a suite assertion fails when the three
# disagree.
STATE_DIR_CURRENT = ".prflow"
STATE_DIR_SUPERSEDED = ".devflow"


def breadcrumb(repo_root: str, stream=None) -> None:
    """Write the superseded-directory breadcrumb. Factored out so the wording
    exists once and the suite can drive it directly."""
    (stream or sys.stderr).write(
        "prflow: reading the superseded {sup}/ state directory in {root} — run "
        "/prflow:init to migrate it to {cur}/ (this transitional fallback is "
        "removed once no consumer still carries {sup}/; see lib/rename-map.json)\n".format(
            sup=STATE_DIR_SUPERSEDED, cur=STATE_DIR_CURRENT, root=repo_root or "."
        )
    )


def resolve_state_dir(repo_root: str, stream=None) -> str:
    """Return the resolved state-directory path under *repo_root*.

    Always returns a path, never raises: the caller composes its own file path
    underneath and applies its own absent-file handling. ``isdir`` is the test on
    purpose -- a plain file or a dangling symlink at either name is not a state
    directory, and treating one as present would route a reader at a path it
    cannot read from.
    """
    current = os.path.join(repo_root, STATE_DIR_CURRENT)
    if os.path.isdir(current):
        return current
    superseded = os.path.join(repo_root, STATE_DIR_SUPERSEDED)
    if os.path.isdir(superseded):
        breadcrumb(repo_root, stream)
        return superseded
    # Neither present: hand back the CANONICAL path. There is nothing to migrate,
    # so this is a fresh repo rather than a stale one and it earns no breadcrumb
    # -- emitting one here would train operators to ignore the line that matters.
    return current


def state_config_path(repo_root: str, filename: str = "config.json", stream=None) -> str:
    """Convenience wrapper: the resolved path to a file inside the state dir."""
    return os.path.join(resolve_state_dir(repo_root, stream), filename)

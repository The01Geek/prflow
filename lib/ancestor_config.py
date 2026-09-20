#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""ancestor_config.py -- the nested-repository detection for PRFlow's PYTHON readers.

The shell sibling is ``lib/detect-ancestor-config.sh``. The two are a COUPLED PAIR
and are edited together: a ``.sh`` cannot be exec'd from these readers on Windows
([WinError 193] -- the issue-#275 rule), and a ``.py`` cannot be sourced into a
shell. ``lib/test/test_python_scripts_part4.py`` drives both and asserts the
emitted line is byte-identical across the two.

WHY (issue #12). Every reader under the SHARED REPO-ROOT CONFIG CONTRACT resolves
its DEFAULT ``.prflow/`` path from ``git rev-parse --show-toplevel``, which returns
the NEAREST git root. In a nested/submodule checkout, or a monorepo whose
``.prflow/`` is not at the git root, that root carries no ``.prflow/`` and every
``// default`` extraction silently returns the built-in default -- the consumer's
config looks honored while it is not. This detection makes that one shape LOUD; it
changes no resolution, so every reader returns exactly what it returned before.

Detection fires only on the ambiguous shape: the resolved root carries NEITHER
``.prflow/`` NOR the transitional ``.devflow/``, AND a directory strictly above it
carries a ``.prflow/``.
"""
from __future__ import annotations

import os
import sys

# The one home of the wording. Coupled with lib/detect-ancestor-config.sh's printf.
BREADCRUMB_FORMAT = (
    "{reader}: repo root '{root}' has no .prflow/, but ancestor '{ancestor}' does"
    " — reading built-in defaults, not that config; to use it, {remedy}.\n"
)
NO_OVERRIDE_REMEDY = (
    "this reader has no explicit override — run it from the repository that owns the config"
)


def ancestor_config_dir(directory: str) -> str | None:
    """The NEAREST directory strictly above *directory* carrying a ``.prflow/``
    DIRECTORY, or ``None``.

    The walk stops at the filesystem root (``os.path.dirname`` becomes a fixed
    point), and ``isdir`` is the whole test: a ``.prflow`` that is a regular file
    or a dangling symlink is not a config directory, and an ancestor the process
    cannot stat reads as not carrying one rather than raising into the reader.
    """
    if not directory:
        return None
    current = directory.rstrip(os.sep) or os.sep
    while True:
        parent = os.path.dirname(current)
        if not parent or parent == current:
            return None
        if os.path.isdir(os.path.join(parent, ".prflow")):
            return parent
        current = parent


def warn_ancestor_config(repo_root, reader: str, remedy: str = "", stream=None) -> None:
    """Write the one-line breadcrumb to stderr for the ambiguous nested shape.

    Never raises and never touches stdout: several callers capture a reader's
    stdout as a value, and a polluted capture becomes a wrong value downstream.
    *remedy* names the reader's OWN supported explicit override; a reader with
    none passes the empty string and the line says so rather than advertising a
    flag that does not exist.
    """
    root = str(repo_root or "")
    if not root:
        return
    if os.path.isdir(os.path.join(root, ".prflow")) or os.path.isdir(
        os.path.join(root, ".devflow")
    ):
        return
    ancestor = ancestor_config_dir(root)
    if not ancestor:
        return
    (stream or sys.stderr).write(
        BREADCRUMB_FORMAT.format(
            reader=reader, root=root, ancestor=ancestor,
            remedy=remedy or NO_OVERRIDE_REMEDY,
        )
    )

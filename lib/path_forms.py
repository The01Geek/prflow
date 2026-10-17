# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Separator and absoluteness rules for paths a helper prints or checks (issue #1665).

A path printed for an agent to paste into a Git Bash command must carry no `\\`: bash
consumes each unquoted backslash as an escape. Each function takes `_pathmod`, defaulting to the
`os.path` current at call time, so tests run the Windows arm on any host.
"""

from __future__ import annotations

import os


def posix_path(path, _pathmod=None):
    """`path` with `\\` replaced by `/` when the path module's separator is `\\`.

    Never convert on a POSIX module: there `\\` is a legal filename byte.
    """
    pathmod = os.path if _pathmod is None else _pathmod
    path = str(path)
    return path.replace("\\", "/") if pathmod.sep == "\\" else path


def host_abs_path(path, _pathmod=None):
    """True when `path` is absolute under the path module, which on Windows also needs a drive.

    The drive test refuses a rooted, driveless path (`\\Users\\x`) on every interpreter:
    `ntpath.isabs` called it absolute before Python 3.13 and relative from 3.13.
    """
    pathmod = os.path if _pathmod is None else _pathmod
    if not pathmod.isabs(path):
        return False
    if pathmod.sep == "\\":
        return pathmod.splitdrive(path)[0] != ""
    return True

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Build the argv a Python process hands to `bash` (issue #430).

Never pass `str(some_path)` as bash's script argument: on native-Windows CPython that is a
backslash path, bash consumes each backslash as an escape, and the launch dies at exit 127
naming a path nobody typed. Whether it happens is decided by the PARENT process — from inside
Git Bash the paths already arrive POSIX-form — so the defect is invisible to anyone
reproducing it from a Git Bash prompt, and Linux-only CI cannot see it at all.

`lib/normalize-path.sh` converts the same two forms and is the source of the two output
spellings, but reaching it means starting the very shell whose argument is broken, so the
conversion has to happen here. It decides the interpreter family from the live environment;
this module runs before any bash exists and reads the family off the `DEVFLOW_BASH` value.

Prefer `script_argument` with a `cwd`: a path relative to the working directory the subprocess
is given carries no drive letter and is correct under every interpreter. `convert_absolute` is
the residual for a target outside that directory.

Disclosed residual. Family detection reads the `DEVFLOW_BASH` spelling, so an UNSET override
leaves the bare literal `bash`, which is classified Git Bash / MSYS2. On a Windows host whose
PATH `bash` is the WSL launcher that yields `/c/…`, which WSL cannot open. Nothing here can
tell those apart without probing the interpreter, so the remedy is the selection boundary
itself: set `DEVFLOW_BASH` to the interpreter you mean. The relative form `script_argument`
prefers is unaffected, which is why it is the primary strategy and this is the residual.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: The variable naming the bash the operator selected (issue #248). Read inline instead
#: by `scripts/resolve-review-overrides.py`, whose declared exec edge a guard verifies from
#: a statically resolvable binding; the resolution rule is the same.
BASH_ENV = "DEVFLOW_BASH"

#: Matches a WSL interpreter by its own spelling — `wsl`, `wsl.exe`, or a path ending
#: in either. A Git Bash / MSYS2 interpreter (`bash`, `C:\\Program Files\\Git\\bin\\bash.exe`)
#: does not match and takes the `/<drive>` form.
_WSL_INTERPRETER = re.compile(r"(?:^|[\\/])wsl(?:\.exe)?$", re.IGNORECASE)

#: The System32 launcher spelling, matched separately so the rule above stays readable.
_WSL_SYSTEM32_LAUNCHER = re.compile(
    r"[\\/]windows[\\/]system32[\\/]bash(?:\.exe)?$", re.IGNORECASE
)

#: A leading Windows drive letter, parsed here rather than through `pathlib` so the rewrite
#: is host-independent: `PurePath("C:\\…")` on a POSIX host is a `PurePosixPath` with no
#: drive, so a drive-letter path would pass through unconverted on Linux CI (issue #430).
_DRIVE_LETTER = re.compile(r"^([A-Za-z]):(.*)$", re.DOTALL)


def resolve_bash(env=None):
    """Return the bash interpreter to launch: `$DEVFLOW_BASH` when set non-empty, else `bash`.

    An override wins verbatim and is never probed, matching `lib/resolve-bin.sh`'s
    contract for the same variable.
    """
    environ = os.environ if env is None else env
    return environ.get(BASH_ENV) or "bash"


def is_wsl_interpreter(bash):
    """Return True when `bash` names a WSL interpreter rather than a Git Bash / MSYS2 one.

    The System32 `bash.exe` launcher counts: it is the standard WSL entry point on a Windows
    host and the spelling an operator most often picks up as "a bash on PATH", and reading it
    as Git Bash hands WSL a `/c/…` path it cannot open.
    """
    spelling = str(bash).strip().strip('"')
    return bool(
        _WSL_INTERPRETER.search(spelling) or _WSL_SYSTEM32_LAUNCHER.search(spelling)
    )


def convert_absolute(path, bash):
    """Return `path` in the absolute form the interpreter `bash` can open.

    A driveless path is returned in POSIX spelling unchanged. A drive-letter path is
    rewritten to `/mnt/<drive>/…` for a WSL interpreter and `/<drive>/…` for Git Bash or
    MSYS2, the two forms `lib/normalize-path.sh` defines. A UNC path passes through
    unchanged, the residual that helper documents.
    """
    spelled = str(path)
    # Never collapse a UNC path's leading pair: `/server/share/x` names a local root that
    # does not exist, where the original at least reaches the share.
    if spelled.startswith(("\\\\", "//")):
        return spelled
    match = _DRIVE_LETTER.match(spelled)
    if not match:
        # Driveless: a POSIX path is returned unchanged; a backslash-bearing relative path
        # is posix-spelled so no backslash reaches bash as an escape.
        return spelled.replace("\\", "/")
    letter = match.group(1).lower()
    rest = match.group(2).replace("\\", "/")
    if not rest.startswith("/"):
        rest = "/" + rest
    prefix = "/mnt/" if is_wsl_interpreter(bash) else "/"
    return f"{prefix}{letter}{rest}"


def script_argument(path, cwd=None, bash=None):
    """Return `path` as an argument the launched bash can open.

    Prefers a path relative to `cwd` — the working directory the subprocess is given —
    because such a path carries no drive letter and is therefore correct under every
    interpreter and every parent shell. Falls back to `convert_absolute` when `path`
    lies outside `cwd`, or when no `cwd` is given.
    """
    resolved_bash = resolve_bash() if bash is None else bash
    if cwd is not None:
        try:
            relative = Path(path).resolve().relative_to(Path(cwd).resolve())
        except ValueError:
            # Outside cwd — a temp registry, a log directory, a destination elsewhere on
            # the disk. Convert the RESOLVED path, never the caller's spelling: a relative
            # input re-spelled as-is is resolved by the subprocess against the working
            # directory this call just moved, silently naming a different file.
            return convert_absolute(Path(path).resolve(), resolved_bash)
        spelled = relative.as_posix()
        if "/" in spelled or spelled in (".", ".."):
            return spelled
        # Keep a directory component on a bare basename: a script invoked that way anchors
        # its own directory with a `%/*` expansion over its own path, which yields the
        # basename itself when there is no slash, and then cd's into its own filename.
        return f"./{spelled}"
    return convert_absolute(Path(path).resolve(), resolved_bash)

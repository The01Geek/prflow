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
this module runs before any bash exists and reads the family off the interpreter
`resolve_bash` selects.

Prefer `script_argument` with a `cwd`: a path relative to the working directory the subprocess
is given carries no drive letter and is correct under every interpreter. `convert_absolute` is
the residual for a target outside that directory.

Unless `DEVFLOW_BASH` is non-empty, native Windows launches the first `bash.exe` in a fully
qualified PATH entry, else the bare `bash`, which family detection reads as Git Bash whatever it
resolves to.
Set `DEVFLOW_BASH` to choose a bash explicitly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: The variable naming the bash the operator selected (issue #248).
BASH_ENV = "DEVFLOW_BASH"

#: Matches a WSL interpreter by its own spelling — `wsl`, `wsl.exe`, or a path ending
#: in either. A Git Bash / MSYS2 interpreter (`bash`, `C:\\Program Files\\Git\\bin\\bash.exe`)
#: does not match and takes the `/<drive>` form.
_WSL_INTERPRETER = re.compile(r"(?:^|[\\/])wsl(?:\.exe)?$", re.IGNORECASE)

#: The WSL `bash.exe` launcher or app-execution alias, matched by its `System32`, `Sysnative`
#: or `WindowsApps` folder under any root, separately so the rule above stays readable.
_WSL_LAUNCHER = re.compile(
    r"[\\/](?:system32|sysnative|windowsapps)[\\/]bash(?:\.exe)?$", re.IGNORECASE
)

#: A leading Windows drive letter, parsed here rather than through `pathlib` so the rewrite
#: is host-independent: `PurePath("C:\\…")` on a POSIX host is a `PurePosixPath` with no
#: drive, so a drive-letter path would pass through unconverted on Linux CI (issue #430).
_DRIVE_LETTER = re.compile(r"^([A-Za-z]):(.*)$", re.DOTALL)

#: A fully qualified Windows path. Not `ntpath.isabs`: before Python 3.13 it also accepts `\bin`.
_FULLY_QUALIFIED = re.compile(r"^(?:[A-Za-z]:|[\\/])[\\/]")


def resolve_bash(env=None, os_name=None):
    """Return the bash interpreter to launch.

    A non-empty `$DEVFLOW_BASH` wins verbatim and is never probed, matching
    `lib/resolve-bin.sh`'s contract for the same variable. Otherwise native Windows takes the
    first fully qualified PATH entry in `env` (drive letter and root, or UNC; surrounding double
    quotes dropped) holding a `bash.exe` file; everywhere else, or with no such entry, the bare
    `bash`.
    """
    environ = os.environ if env is None else env
    override = environ.get(BASH_ENV)
    if override:
        return override
    if (os.name if os_name is None else os_name) == "nt":
        # Not shutil.which: on Windows it can search the current directory first and accepts
        # every PATHEXT extension, so a `bash.cmd` or a checkout's `bash.exe` could win.
        for entry in environ.get("PATH", "").split(os.pathsep):
            if entry[:1] == entry[-1:] == '"':
                entry = entry[1:-1]
            candidate = os.path.join(entry, "bash.exe")
            if _FULLY_QUALIFIED.match(entry) and os.path.isfile(candidate):
                return candidate
    return "bash"


def is_wsl_interpreter(bash):
    """Return True when `bash` names a WSL interpreter rather than a Git Bash / MSYS2 one.

    A `bash.exe` in System32, Sysnative or WindowsApps counts: reading it as Git Bash hands WSL
    a `/c/…` path it cannot open.
    """
    spelling = str(bash).strip().strip('"')
    return bool(
        _WSL_INTERPRETER.search(spelling) or _WSL_LAUNCHER.search(spelling)
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


def _quote_windows_argument(arg):
    """Double-quote `arg` so the MSYS2 runtime rebuilds it verbatim and never globs it.

    Inside double quotes that runtime reads a backslash before a quote or a backslash as an
    escape, so both are escaped.
    """
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def command(argv, os_name=None):
    """Return `argv` in the form `subprocess` should get for a bash launch.

    On native Windows the MSYS2 runtime behind Git Bash glob-expands an argument its command
    line leaves unquoted, so a `*` argument arrives as the directory listing; `subprocess`
    quotes only empty arguments and those holding whitespace. There the argv becomes one
    command line: the program double-quoted, every argument quoted by that runtime's rules.
    Elsewhere it is returned unchanged as a list.
    """
    if (os.name if os_name is None else os_name) != "nt":
        return list(argv)
    program, *args = (str(a) for a in argv)
    return " ".join([f'"{program}"', *map(_quote_windows_argument, args)])

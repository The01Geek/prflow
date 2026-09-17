#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""The refreshed-token environment for a Python `gh` call on native Windows.

`scripts/install-gh-wrapper.sh` installs `scripts/gh-fresh.sh` as an extensionless
`gh` ahead of the real CLI on PATH. Bash and every POSIX `execvp` reach it. A
native-Windows CPython (`os.name == 'nt'`) does not: `CreateProcess` appends only
`.exe` and never consults `PATHEXT`, so `subprocess.run(["gh", ...])` runs the real
`gh.exe` on the job-start `GH_TOKEN`, which 401s once the App installation token
expires at 60 minutes.

`fresh_gh_env()` closes that hop in-process: pass its result as `env=` to every
`gh` subprocess. On a POSIX host it returns its input unchanged, because the
wrapper is reached there and makes this decision itself. On `nt` it applies
gh-fresh.sh's `decide()` and substitutes the refresher's token:

* `GH_TOKEN` absent or empty -> substitute;
* `GH_TOKEN`'s sha256 equals the recorded job-start fingerprint -> substitute;
* a different hash (a deliberately fresh mint) -> defer, untouched;
* the comparison cannot be established -> defer.

A substitution whose token file is absent, unreadable or empty degrades to the
ambient token, as the wrapper does. Both files take gh-fresh.sh's defaults.

Routing through the wrapper instead is rejected: it needs a bash, and a bare
`bash` resolves to the System32 WSL launcher before PATH, while a Windows command
line re-parsed by the MSYS runtime re-globs and re-quotes arguments.

Never raises, and never writes to stdout or stderr: `workpad.py id` signals
"no workpad" by exit 2 with an EMPTY stderr, so any breadcrumb here would turn that
answer into an API error for its callers. A degraded call therefore stays silent;
the 401 it then meets is the visible signal.
"""

from __future__ import annotations

import hashlib
import os

TOKEN_FILE_ENV = "DEVFLOW_GH_TOKEN_FILE"
FINGERPRINT_FILE_ENV = "DEVFLOW_GH_FINGERPRINT_FILE"


def _read_stripped(path):
    """File bytes minus trailing newlines (a `$(cat file)` read), or None."""
    try:
        with open(path, "rb") as fh:
            return fh.read().rstrip(b"\n")
    except (OSError, ValueError):
        return None


def _substitute_token(env):
    """The token to substitute into `env`, or None to defer to its GH_TOKEN."""
    runner_temp = env.get("RUNNER_TEMP") or "/tmp"
    current = env.get("GH_TOKEN") or ""
    if current:
        fingerprint = _read_stripped(
            env.get(FINGERPRINT_FILE_ENV)
            or os.path.join(runner_temp, "devflow-gh-fingerprint")
        )
        if not fingerprint:
            return None
        digest = hashlib.sha256(os.fsencode(current)).hexdigest().encode("ascii")
        if digest != fingerprint:
            return None
    token = _read_stripped(
        env.get(TOKEN_FILE_ENV) or os.path.join(runner_temp, "devflow-gh-token")
    )
    if not token:
        return None
    return os.fsdecode(token)


def fresh_gh_env(env=None, os_name=None):
    """Return the `env=` for a `gh` subprocess.

    `env` is the environment the caller would otherwise pass (None inherits
    `os.environ`); it is returned as given unless a substitution applies, in which
    case a copy carrying the refreshed `GH_TOKEN` is returned. `os_name` overrides
    `os.name` for tests.
    """
    if (os.name if os_name is None else os_name) != "nt":
        return env
    try:
        base = os.environ if env is None else env
        token = _substitute_token(base)
        if token is None:
            return env
        fresh = dict(base)
        fresh["GH_TOKEN"] = token
        return fresh
    except Exception:
        return env

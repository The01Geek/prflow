#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared spawn helpers that restore default signal dispositions in a child.

Issue #1216. A shell without job control that starts a background command
(`cmd &`) is required by POSIX to set SIGINT and SIGQUIT to *ignore* in the
child, and bash cannot un-ignore a signal it inherited as SIG_IGN — so a
coordinator backgrounded by the module worker (which runs under `set +m`) can
never install its own SIGINT trap. Python is not bash: it can reset an inherited
SIG_IGN to SIG_DFL, so a tiny Python shim placed between the backgrounding shell
and the real command restores a working signal disposition before that command
begins.

This module is the single source of the restored-signal set and the two spawn
mechanics built on it:

* ``exec_with_default_signals(argv)`` restores the signals and then ``execvp``s
  the target, so the process **identity is preserved** — ``$!`` in the spawning
  shell still names the exec'd command. This is the mechanic the test fixture
  needs, because it signals the coordinator by that PID.
* ``run_detached(argv)`` runs the target as a child in a **new session** and
  reports the child's real exit status. This is the launcher for running the
  suite without blocking on the caller's process group.

`lib/test/profile-suite.py` consumes ``restore_default_signals`` and
``exit_status`` from here rather than carrying its own copies.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys

# The signals a backgrounded launch can leave a suite child unable to handle.
# SIGINT and SIGQUIT are the two POSIX forces to ignore for a job-control-off
# background child; SIGHUP and SIGTERM are restored too so the set is a single
# clean "default dispositions" contract for every consumer (restoring an
# already-default signal is a no-op).
_SIGNAL_NAMES = ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM")
DEFAULT_SUITE_SIGNALS = tuple(
    getattr(signal, _n) for _n in _SIGNAL_NAMES if hasattr(signal, _n)
)


def restore_default_signals() -> None:
    """Set every signal in :data:`DEFAULT_SUITE_SIGNALS` to ``SIG_DFL``.

    Usable as a ``subprocess`` ``preexec_fn`` (runs in the forked child before
    ``exec``). POSIX-only, like ``preexec_fn`` itself.
    """
    for sig in DEFAULT_SUITE_SIGNALS:
        signal.signal(sig, signal.SIG_DFL)


def _spawn_failure_status(exc: OSError) -> int:
    """A failed spawn's SHELL exit status: 127 not found, 126 cannot execute.

    These are the statuses a shell reports for the same two conditions, and the
    reason to translate at all: an uncaught exec error exits **1**, which is
    indistinguishable from a genuine exit 1 produced by a command that actually
    ran — so the caller cannot tell "your target never started" from "your target
    ran and failed". ``ENOENT`` is the not-found case; every other exec-time
    ``OSError`` (``EACCES``, ``ENOEXEC``, ``ENOTDIR``, …) is the found-but-
    unusable case a shell reports as 126.
    """
    return 127 if exc.errno == errno.ENOENT else 126


def _fail_spawn(prog: str, argv0: str, exc: OSError) -> SystemExit:
    """Emit the one-line spawn diagnostic and build the matching ``SystemExit``.

    Mirrors the empty-argv arm's shape (``<prog>: <what> <target>``) so both
    refusals read the same and neither is a raw traceback.
    """
    detail = exc.strerror or type(exc).__name__
    print(f"{prog}: cannot execute {argv0}: {detail}", file=sys.stderr)
    return SystemExit(_spawn_failure_status(exc))


def exec_with_default_signals(argv: list[str]) -> None:
    """Restore default signal dispositions, then ``execvp`` ``argv``.

    Never returns on success — the current process is replaced, so its PID (the
    ``$!`` the spawning shell recorded) becomes the exec'd command. Raises
    ``SystemExit`` with a diagnostic when ``argv`` is empty, and — when the target
    cannot be exec'd — with the shell status :func:`_spawn_failure_status`
    selects, so the caller can tell an unstartable target from one that ran.
    """
    if not argv:
        print("exec-with-default-signals: no command given", file=sys.stderr)
        raise SystemExit(2)
    restore_default_signals()
    try:
        os.execvp(argv[0], argv)
    except OSError as exc:
        raise _fail_spawn("exec-with-default-signals", argv[0], exc) from None


def exit_status(wait_status: int) -> int:
    """``Popen.wait()``'s status as a SHELL exit status.

    ``wait()`` reports a signal death as ``-N``; a shell that was killed by that
    same signal exits ``128 + N``. Non-signal statuses (including 0) pass through
    untouched. This is the translation `profile-suite.py` also relies on.
    """
    return 128 + (-wait_status) if wait_status < 0 else wait_status


def run_detached(argv: list[str]) -> int:
    """Run ``argv`` as a child in a new session with default signal dispositions.

    Returns the child's real exit status (signal deaths translated by
    :func:`exit_status`). Raises ``SystemExit`` with a diagnostic when ``argv``
    is empty, and — when the child cannot be spawned — with the shell status
    :func:`_spawn_failure_status` selects, so a target that never started is not
    reported as a target that ran and exited 1.
    """
    if not argv:
        print("launch-detached: no command given", file=sys.stderr)
        raise SystemExit(2)
    try:
        proc = subprocess.Popen(
            argv,
            start_new_session=True,
            preexec_fn=restore_default_signals,  # noqa: PLW1509 - POSIX-only by design
        )
    except OSError as exc:
        raise _fail_spawn("launch-detached", argv[0], exc) from None
    return exit_status(proc.wait())


if __name__ == "__main__":  # pragma: no cover - the thin CLIs are the entry points
    print(
        "signal_launcher is a library; use exec-with-default-signals.py or "
        "launch-detached.py",
        file=sys.stderr,
    )
    raise SystemExit(2)

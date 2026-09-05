#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared GitHub-login normalization and comparison (issue #157).

One login rule for every PRFlow comparator that decides trust or identity by
comparing a login against a configured or expected login. The two Python matchers
import ``normalize_login`` / ``login_matches`` through the ``lib/`` path insert they
already perform; the shell comparators call the ``normalize`` / ``matches``
subcommands through the interpreter ``lib/resolve-python.sh`` selects.

The rule (both operands of a comparison pass through it): trim surrounding
whitespace, lowercase, then strip one leading ``app/`` and one trailing ``[bot]``.
Lowercasing before the strip makes the affix match case-insensitive too, so a
``App/`` or ``[BOT]`` variant folds the same as its lowercase form. A comparand
that normalizes to the empty string matches nothing, so an empty or
whitespace-only allowlist never trusts anyone.

CLI:
    login_normalize.py normalize <login>
        print the normalized login, exit 0.
    login_normalize.py matches <login> <comma-separated-comparands>
        exit 0 when the normalized login equals a normalized non-empty comparand,
        1 when it equals none, 2 on a usage error (wrong argument count).
"""
from __future__ import annotations

import sys

_APP_PREFIX = "app/"
_BOT_SUFFIX = "[bot]"


def normalize_login(login: str) -> str:
    """Normalize a GitHub login to its comparison basis.

    Order is load-bearing: lowercase the whitespace-trimmed login FIRST, then strip
    ONE leading ``app/`` and ONE trailing ``[bot]`` — so ``app/X[bot]``, ``App/X``
    and ``x`` all normalize to ``x`` (lowercasing first is what makes the affix
    match case-insensitive). Only a *leading* ``app/`` is stripped, so an internal
    one (``myapp/thing``) is left intact.
    """
    s = login.strip().lower().removeprefix(_APP_PREFIX).removesuffix(_BOT_SUFFIX)
    return s


def login_matches(login: str, comparands) -> bool:
    """True when the normalized login equals any normalized non-empty comparand.

    ``comparands`` is an iterable of comparand strings (the CLI splits its
    comma-separated argument before calling). A comparand normalizing to the empty
    string matches nothing, so an empty or whitespace-only allowlist never trusts.
    """
    target = normalize_login(login)
    for c in comparands:
        nc = normalize_login(c)
        if nc and nc == target:
            return True
    return False


def _force_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8 on the CLI entry path (not at import), so the
    printed login and usage text survive a non-UTF-8 ambient codec (Windows cp1252),
    mirroring the sibling matchers. Tolerates a non-``TextIOWrapper`` stream."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _usage(msg: str) -> int:
    sys.stderr.write(f"login_normalize.py: {msg}\n")
    sys.stderr.write(
        "usage: login_normalize.py normalize <login>\n"
        "       login_normalize.py matches <login> <comma-separated-comparands>\n"
    )
    return 2


def main(argv=None) -> int:
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _usage("missing subcommand (expected 'normalize' or 'matches')")
    sub, rest = argv[0], argv[1:]
    if sub == "normalize":
        if len(rest) != 1:
            return _usage(f"'normalize' takes exactly one <login> argument (got {len(rest)})")
        print(normalize_login(rest[0]))
        return 0
    if sub == "matches":
        if len(rest) != 2:
            return _usage(
                f"'matches' takes exactly <login> <comma-separated-comparands> (got {len(rest)})"
            )
        login, comparands = rest[0], rest[1].split(",")
        return 0 if login_matches(login, comparands) else 1
    return _usage(f"unknown subcommand {sub!r} (expected 'normalize' or 'matches')")


if __name__ == "__main__":
    sys.exit(main())

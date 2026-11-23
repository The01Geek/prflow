#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Run one fix-delta reviewer read inside a checkout other than the caller's own.

Usage: fix-delta-read.py --repo <top-level> <command...>

A subagent starts in the main conversation's working directory and may not `cd` or use
`git -C`, so the fix-delta reviewer reaches a different `Repository:` through this helper.
It runs, with `<top-level>` as its working directory, exactly these commands:

    git diff [--name-only] <base> [<head>] [-- <path>...]
    git status --porcelain --untracked-files=all
    git grep -n -F [--untracked] -e <text> -- :/
    <path ending in /load-prompt-extension.sh> review-and-fix

`--name-only` may sit anywhere before `--`, and a diff runs with `--` after its revisions
even when the request names no path. The grep flags come before `-e` in any order,
except that `--untracked` may instead follow `<text>`. A relative loader path resolves
against `<top-level>`. The command inherits this process's stdout and stderr, and its
exit status is returned unchanged (a death by signal N as 128 + N, as a shell reports it).
Every other request, and an allowed command that cannot be launched, runs nothing further
and exits 2 with one stderr line opening `fix-delta-read: refused (` -- for example a
`<top-level>` that `git rev-parse --show-toplevel` run inside it does not print, another
command or a revision starting with `-`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REFUSED = "fix-delta-read: refused"
REFUSED_EXIT = 2
LOADER_SUFFIX = "/load-prompt-extension.sh"


class Refusal(Exception):
    """A request this helper will not run, carrying the cause it names."""


def _diff_args(args):
    """Validate `git diff` arguments; return the `git` arguments or raise Refusal."""
    lead, paths = args, []
    if "--" in args:
        cut = args.index("--")
        lead, paths = args[:cut], args[cut:]
        if len(paths) == 1:
            raise Refusal("git diff: `--` names no path")
    revs = [a for a in lead if a != "--name-only"]
    if lead.count("--name-only") > 1 or len(revs) not in (1, 2):
        raise Refusal("git diff takes <base>, an optional <head> and an optional --name-only")
    for rev in revs:
        if not rev or rev.startswith("-"):
            # A leading `-` would reach git as an option, e.g. `--output=<file>` writes a file.
            raise Refusal(f"git diff revision {rev!r} is empty or starts with '-'")
    # The `--` keeps git from reading `<head>` as a path.
    return ["diff", *lead, "--", *paths[1:]]


def _git_args(args):
    if not args:
        raise Refusal("git: no subcommand")
    sub, rest = args[0], args[1:]
    if sub == "diff":
        return _diff_args(rest)
    if sub == "status" and rest == ["--porcelain", "--untracked-files=all"]:
        return args
    if sub == "grep" and "-e" in rest:
        cut = rest.index("-e")
        flags, tail = rest[:cut], rest[cut:]
        if tail[2:3] == ["--untracked"]:
            flags, tail = [*flags, "--untracked"], [*tail[:2], *tail[3:]]
        if sorted(flags) in (["-F", "-n"], ["--untracked", "-F", "-n"]) and len(tail) == 4 \
                and tail[2:] == ["--", ":/"]:
            return args
    raise Refusal(f"git {sub} with these arguments is not an allowed read")


def build_command(repo, argv):
    """Return the argv to run inside `repo` for the requested command, or raise Refusal."""
    if not argv:
        raise Refusal("no command given")
    if argv[0] == "git":
        return ["git", *_git_args(argv[1:])]
    if argv[0].endswith(LOADER_SUFFIX) and argv[1:] == ["review-and-fix"]:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
        try:
            import bash_launch
        except Exception as exc:
            raise Refusal(f"lib/bash_launch.py could not be imported ({exc})") from exc
        bash = bash_launch.resolve_bash()
        # A `/`-rooted path is already spelled for bash; Windows pathlib would re-root a
        # `/c/...` one onto the current drive as `C:\c\...`.
        script = argv[0] if argv[0].startswith("/") else \
            bash_launch.script_argument(Path(repo) / argv[0], cwd=repo, bash=bash)
        return bash_launch.command([bash, script, "review-and-fix"])
    raise Refusal(f"{argv[0]!r} is not git or a load-prompt-extension.sh loader run with review-and-fix")


def check_repo(repo):
    """Raise Refusal unless `git rev-parse --show-toplevel` run inside `repo` prints `repo`."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=repo,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
    except OSError as exc:
        raise Refusal(f"cannot run git in {repo!r}: {exc}") from exc
    printed = top.stdout.strip()
    if top.returncode != 0 or printed != repo:
        said = top.stderr.strip().splitlines()[-1:]
        raise Refusal(f"{repo!r} is not a repository top level (git exit {top.returncode},"
                      f" printed {printed!r}{', said ' + repr(said[0]) if said else ''})")


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    _force_utf8_streams()
    if len(argv) < 2 or argv[0] != "--repo":
        print(f"{REFUSED} (usage: fix-delta-read.py --repo <top-level> <command...>)",
              file=sys.stderr)
        return REFUSED_EXIT
    repo, command = argv[1], argv[2:]
    try:
        check_repo(repo)
        cmd = build_command(repo, command)
        try:
            code = subprocess.run(cmd, cwd=repo, check=False).returncode
        except OSError as exc:
            raise Refusal(f"cannot launch {command[0]!r}: {exc}") from exc
        return 128 - code if code < 0 else code
    except Refusal as refusal:
        print(f"{REFUSED} ({refusal})", file=sys.stderr)
        return REFUSED_EXIT


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # never narrow: a bare traceback's exit 1 reads as a grep no-match
        print(f"{REFUSED} (internal error: {exc.__class__.__name__}: {exc})", file=sys.stderr)
        sys.exit(REFUSED_EXIT)

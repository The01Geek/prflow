#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Resolve the open PR that closes a given issue (newest by createdAt).

The single source of the "which PR" selection every agent-less writer uses — the
gate job's PR-body maintenance (via the CLI) and ``scripts/workpad.py``'s
stopped-run note mirror (via ``resolve_issue_pr`` imported in-process) — because
neither holds the feature branch, only the issue number. It mirrors the branch-
setup resume pre-check's body-reference selection: an OPEN PR whose
``closingIssuesReferences`` contains this issue, newest by ``createdAt``. A PR
that merely mentions the number (``see #<n>``) is not selected.

CLI: ``resolve-issue-pr.py --issue <n>`` prints one line and exits:

    <number>   exit 0   an open PR closing the issue was resolved (newest wins)
    (nothing)  exit 2   the query ran cleanly and no such PR exists (NONE)
    (nothing)  exit 3   the query could not be established (REFUSED)

Every outcome leaves its own stderr breadcrumb, so a caller reads "no output at
all" as a harness refusal rather than as an answer. The 0/2/3 split matches the
repo's ``workpad.py id`` (0 found / 2 scanned-clean-absent) and ``preflight.py``
(3 could-not-establish) shapes.
"""
import argparse
import json
import os
import subprocess
import sys


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 (never at import — it would mutate an importer's streams).
    Tolerates a stream with no usable reconfigure (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _gh():
    # DEVFLOW_GH is the documented override the test suite stubs; else bare `gh`.
    # Python callers deliberately do not probe (CLAUDE.md resolver contract).
    return os.environ.get("DEVFLOW_GH") or "gh"


def _query_open_prs(issue, gh=None):
    """Return the parsed `gh pr list` array, or None when the query could not run/parse."""
    gh = gh or _gh()
    try:
        r = subprocess.run(
            [gh, "pr", "list", "--search", f"{issue} in:body", "--state", "open",
             "--json", "number,closingIssuesReferences,createdAt"],
            capture_output=True, encoding="utf-8",
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _select(prs, issue):
    """Pick the newest open PR whose closingIssuesReferences contains *issue*; else None."""
    try:
        want = int(issue)
    except (TypeError, ValueError):
        return None
    closing = []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        refs = pr.get("closingIssuesReferences") or []
        if any(isinstance(c, dict) and c.get("number") == want for c in refs):
            closing.append(pr)
    if not closing:
        return None
    closing.sort(key=lambda p: p.get("createdAt") or "")
    return closing[-1].get("number")


def resolve_issue_pr(issue, gh=None):
    """Return the newest open PR number closing *issue*, or None (none-or-unresolvable).

    Best-effort for the in-process mirror caller: a transport failure and a genuine
    "no such PR" both return None — the caller only ever skips on either."""
    prs = _query_open_prs(issue, gh)
    if prs is None:
        return None
    return _select(prs, issue)


def main(argv):
    _force_utf8_streams()
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", required=True)
    args = ap.parse_args(argv[1:])
    prs = _query_open_prs(args.issue)
    if prs is None:
        sys.stderr.write(
            f"resolve-issue-pr: could not establish the open-PR set for issue "
            f"#{args.issue} (gh failed or returned unparseable JSON)\n")
        return 3
    num = _select(prs, args.issue)
    if num is None:
        sys.stderr.write(
            f"resolve-issue-pr: no open PR closes issue #{args.issue}\n")
        return 2
    sys.stdout.write(str(num))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

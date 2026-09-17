#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Resolve the open PR that closes a given issue (newest by createdAt).

The CLI the gate job's PR-body maintenance (``scripts/refresh-pr-on-resume.sh``)
uses to pick the target PR, because it holds only the issue number, not the
feature branch. ``scripts/workpad.py``'s stopped-run note mirror needs the same
selection but CANNOT import this module — its repo-owned import edges are locked
to ``section_parse.py`` for the Stop-hook closure hardening (issues #458/#583) —
so it carries a byte-identical pinned copy (``lib/test/run.sh`` pins the shared
markers; the selection is a parallel copy). It mirrors the branch-setup resume
pre-check's body-reference selection: an OPEN PR whose ``closingIssuesReferences``
contains this issue, newest by ``createdAt``. A PR that merely mentions the
number (``see #<n>``) is not selected.

When no PR lists the issue in its closing references — the case a PR targeting a
non-default branch always produces, because GitHub ignores closing keywords there, and
the case an adopted human-written PR with no closing keyword produces too — the
selection falls back to the PR the workpad's ``**PR:**`` line names, accepted only when
a REST read shows that PR ``open`` (issue #626). A closing-references match still wins.

CLI: ``resolve-issue-pr.py --issue <n>`` prints one line and exits:

    <number>   exit 0   a PR was resolved (closing-references match, else workpad line)
    (nothing)  exit 2   the queries ran cleanly and no PR could be named (NONE)
    (nothing)  exit 3   a workpad or PR read could not be established (REFUSED)

Every outcome leaves its own stderr breadcrumb, so a caller reads "no output at
all" as a harness refusal rather than as an answer. The 0/2/3 split matches the
repo's ``workpad.py id`` (0 found / 2 scanned-clean-absent) and ``preflight.py``
(3 could-not-establish) shapes.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_fresh_env import fresh_gh_env


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
             "--limit", "100", "--json", "number,closingIssuesReferences,createdAt"],
            capture_output=True, encoding="utf-8", env=fresh_gh_env(),
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


# ── The workpad `**PR:**` line fallback (issue #626) ─────────────────────────
# A pinned parallel copy of scripts/workpad.py's same-named pieces (workpad.py cannot
# import this module, per the note above); both read the PR line the same way and both
# accept its number only after a REST read shows the PR open.
_WORKPAD_PY = Path(__file__).resolve().parent / "workpad.py"
_PR_LINE_RE = re.compile(r'^\*\*PR:\*\*[^\S\n]*(.*)$', re.MULTILINE)
_PR_LINK_URL_RE = re.compile(r'/pull/(\d+)')
_PR_LINK_HASH_RE = re.compile(r'#(\d+)')


def _workpad_body(issue):
    """Return (body, cause, detail) for the issue's workpad.

    Runs ``workpad.py body --issue <n>`` through ``sys.executable`` (never a ``.sh``,
    which workpad.py's own Windows contract forbids) and adopts that command's exit
    vocabulary: 0 body on stdout, 2 scanned-clean-absent, 3 read failure. The child's
    stderr is captured and carried out as *detail*, so this module's breadcrumb names
    the underlying read failure rather than inventing one."""
    try:
        r = subprocess.run(
            [sys.executable, str(_WORKPAD_PY), "body", "--issue", str(issue)],
            capture_output=True, encoding="utf-8",
        )
    except OSError as exc:
        return None, "workpad-read-failed", exc.__class__.__name__
    if r.returncode == 0:
        return r.stdout or "", "", ""
    detail = " ".join((r.stderr or "").split())
    if r.returncode == 2:
        return None, "no-workpad", detail
    return None, "workpad-read-failed", detail or f"exit {r.returncode}"


def _pr_number_from_workpad_body(body):
    """Return (number, cause) for the PR the workpad's `**PR:**` line names.

    The `/pull/<digits>` URL segment is the PR's own identity, so it wins over a
    `#<digits>` in the link text."""
    m = _PR_LINE_RE.search(body or "")
    if m is None:
        return None, "no-pr-line"
    hit = _PR_LINK_URL_RE.search(m.group(1)) or _PR_LINK_HASH_RE.search(m.group(1))
    if hit is None:
        return None, "no-pr-number"
    return int(hit.group(1)), ""


def _pr_is_open(pr, gh=None):
    """Return (True, '') when a REST read shows PR *pr* open, else (False, cause).

    A read that could not run, failed, or returned an empty state is `pr-read-failed`,
    never `pr-not-open` — the latter would assert a state this code did not observe."""
    gh = gh or _gh()
    try:
        r = subprocess.run(
            [gh, "api", f"repos/{{owner}}/{{repo}}/pulls/{pr}", "--jq", ".state"],
            capture_output=True, encoding="utf-8", env=fresh_gh_env(),
        )
    except OSError:
        return False, "pr-read-failed"
    if r.returncode != 0:
        return False, "pr-read-failed"
    state = (r.stdout or "").strip().lower()
    if not state:
        return False, "pr-read-failed"
    if state != "open":
        return False, "pr-not-open"
    return True, ""


def _resolve_from_workpad(issue):
    """Return (number, cause, detail): the open PR the workpad line names, else None."""
    body, cause, detail = _workpad_body(issue)
    if body is None:
        return None, cause, detail
    num, cause = _pr_number_from_workpad_body(body)
    if num is None:
        return None, cause, ""
    ok, cause = _pr_is_open(num)
    if not ok:
        return None, cause, str(num)
    return num, "", ""


# Each fallback miss → the tail of its one-line breadcrumb and the exit code that
# classifies it. A failed read is exit 3 (could not establish); a clean miss is exit 2.
_FALLBACK_MISS = {
    "no-workpad": (2, "no workpad exists for it, so no PR line could be read"),
    "no-pr-line": (2, "its workpad carries no **PR:** line"),
    "no-pr-number": (2, "its workpad **PR:** line names no PR number"),
    "pr-not-open": (2, "the workpad-line PR #{detail} is not open"),
    "workpad-read-failed": (3, "its workpad could not be read ({detail})"),
    "pr-read-failed": (3, "the workpad-line PR #{detail} could not be read"),
}


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
        # No PR lists the issue in its closing references — fall back to the workpad line.
        num, cause, detail = _resolve_from_workpad(args.issue)
        if num is None:
            code, tail = _FALLBACK_MISS.get(
                cause,
                (3, f"the workpad PR-line fallback returned an unknown cause ({cause!r})"))
            sys.stderr.write(
                f"resolve-issue-pr: no open PR closes issue #{args.issue} and "
                f"{tail.format(detail=detail)}\n")
            return code
    sys.stdout.write(str(num))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

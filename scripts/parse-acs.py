#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Parse Acceptance Criteria from a GitHub issue body, classify post-merge.

Implements the parsing + post-merge tagging rules from /implement's Phase 1.4
once, deterministically, in code — replacing ~25 lines of skill prose that
described the rules in English. The orchestrator still owns per-criterion
override authority; this script just produces the heuristic starting point.

Parsing rules (owned by `scripts/section_parse.py`, imported below — issue
#781 factored them there so `scripts/workpad.py`, which reads the same section
back out of the workpad comment, shares one implementation instead of
re-spelling the contract):
  - Match a heading whose text is "Acceptance Criteria" (case-insensitive,
    so `## Acceptance criteria` or `## ACCEPTANCE CRITERIA` all match). A
    trailing colon or other extra characters still do not match — only the
    casing is forgiven. The `## Test Plan` section, when present, is appended
    to the same output (separated by a blank line) per the skill's mirroring
    rule.
  - Heading level may be `##` or `###`.
  - Inside the section, accept `- [ ]`, `- [x]`, `* [ ]`, `* [x]`.
  - Stop at the next heading whose level is equal to or higher than the
    section's heading (i.e. fewer `#` characters, or the same count).

Post-merge classification:
  - Append ` (post-merge)` to any criterion whose text contains a trigger
    phrase from the bundled list (case-insensitive, word-boundary match).
  - Trigger phrases are easy to edit at the top of this file — they're
    intentionally not configurable via a flag so the skill text and the
    helper stay in sync without an extra source of truth.

Usage:
    parse-acs.py --issue ISSUE_NUMBER [--format md|json]
    parse-acs.py --body-file PATH    [--format md|json]

`md` (default) emits checkbox lines ready to splice into the workpad's
`## Acceptance Criteria` section. `json` emits a list of {text, post_merge,
ticked} objects for downstream programmatic use.

When no `## Acceptance Criteria` section exists, prints the literal sentinel
`_(none provided in issue body)_` (md) or an empty array (json). Never
invents criteria.

Present-but-unreadable section (issue #1198): a `## Acceptance Criteria`
section that is present and correctly named but carries its criteria in a shape
this parser does not read — bold paragraphs (`**AC1 — …**`) or a numbered list
(`1. …`) rather than checkbox rows — parses to zero items, exactly like a
genuinely absent section. That collapses "no criteria were parsed" onto "this
issue has no criteria", which the repo's *unknown is not zero* convention
forbids. So the two cases are made distinguishable at this interface WITHOUT
changing the accepted item shape (still only checkbox list items) and WITHOUT
blocking: a present-but-unreadable section emits a distinct item-shape stderr
diagnostic and sets `acceptance_criteria_unreadable: true` in the `--format
json` output, and the helper STILL exits 0 (a non-zero exit would trip the
implement skill's fail-closed §1.2 fence and halt the run, which the owner
ruling forbids — the run must continue and hand-extract). The `--format md`
output is unchanged for that case (the `_(none provided in issue body)_`
sentinel when there is also no readable test plan, else the test-plan rows),
because stdout is redirected into the mirrored section and must not carry a
diagnostic — so `acceptance_criteria_unreadable` in the JSON, not the md
output, is the signal a consumer routes on.

Exit codes:
  0  parsed and printed (INCLUDING the present-but-unreadable-section case)
  1  the body could not be established — a failed fetch, or an `--anchor-repo-root`
     run whose repository root would not resolve (issue #1633; fail closed rather
     than silently anchoring the repo-relative `--body-file` to the process cwd)
  2  bad arguments
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Shared section/checkbox parsing rules (issue #781), imported IN-PROCESS from
# the sibling module — never a `.sh`/subprocess hop (Windows refuses that with
# [WinError 193], issue #275). The explicit `sys.path` entry is load-bearing:
# running this file as a script puts `scripts/` on the path for free, but a
# consumer loading it through `importlib.util.spec_from_file_location` (how
# `lib/test/test_python_scripts.py` drives this directory's helpers) does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from section_parse import (  # noqa: E402
    POST_MERGE_TAG,
    extract_section,
    parse_checkboxes,
    render_line,
)

# The gh binary to shell out to. `DEVFLOW_GH` (the documented override the shell
# helpers resolve via lib/resolve-gh.sh) wins when set and non-empty; else `gh`.
GH = os.environ.get("DEVFLOW_GH") or "gh"


# Trigger phrases that mark a criterion as post-merge. Matched case-
# insensitively as substrings against the criterion text. Keep this short and
# obvious — the skill text references the same list and the orchestrator may
# override per-criterion when a phrase appears incidentally.
POST_MERGE_TRIGGERS = (
    'after merge', 'post-merge', 'post-deploy', 'after deploy',
    'open a pr', 'mark it ready', 'merge button', 'mark the pr',
    'in production', 'on staging', 'live environment',
    # Short bare words like `click` / `manually` / `monitor` produced
    # false-positive tags (`one-click checkout`, `not manually specified`,
    # `Sentry error monitoring`) that silently exempted real ACs from the
    # implement skill's post-merge-exempt gate. They've been replaced with unambiguous multi-word
    # phrases. Combined with the `\b...\b` matcher below, this also stops
    # `monitor` from matching `monitoring`.
    'click to', 'click the button', 'verify manually', 'manual verification',
    'monitor the deploy', 'monitor logs', 'monitor the logs',
    'verify in the ui', 'via the github ui',
    'inspect logs', 'watch the deploy',
    'compare runs', 'the next run', 'next deploy',
    # Workflow / bot-trigger install ACs commonly verify by interacting with a
    # PR that doesn't exist until after merge (e.g. "comment /screenshot on a
    # PR", "verify the workflow runs on a live PR", "check the artifact link").
    # These triggers are intentionally broad: bare 'on a pr' will also tag
    # legitimate pre-merge ACs that incidentally mention a PR (e.g. "Run tests
    # on a PR before merging"), and 'workflow run(s)' will tag general CI-config
    # ACs. We prefer over-tag to under-tag because the implement-skill
    # orchestrator can demote a criterion per-run; an under-tag silently exempts
    # a real post-merge AC from the verification gate, which is the failure
    # mode the short-bare-words removal above was designed to prevent.
    'on a pr', 'on a live pr', 'on a real pr',
    'comment on the pr', 'comment on a pr',
    'workflow run', 'workflow runs', 'artifact link',
)


# Word-boundary regex per trigger phrase. Built once at import time. The
# boundary check stops short bare words like `click` / `monitor` / `manually`
# from incidentally matching inside `one-click checkout`, `Sentry monitoring`,
# or `not manually specified` — a mis-tag would silently exempt a real AC
# from the implement skill's post-merge-exempt gate ("Post-merge criteria are exempt").
_POST_MERGE_RES = tuple(
    re.compile(r'\b' + re.escape(phrase) + r'\b', re.IGNORECASE)
    for phrase in POST_MERGE_TRIGGERS
)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively. Called from
    the CLI entry path only (not at import) so importing this module for unit
    tests never mutates the importer's global streams. The em-dash this script
    emits in its near-miss error message would otherwise raise
    `UnicodeEncodeError` under a non-UTF-8 ambient codec (Windows' cp1252).
    Reconfigure overrides even a hostile `PYTHONIOENCODING`; the guard tolerates
    a non-`TextIOWrapper` stream (e.g. a test's `io.StringIO`)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _fetch_body(issue: int) -> str:
    """Fetch an issue's body via gh."""
    try:
        # `encoding="utf-8"` so DECODING the issue body (routinely non-ASCII)
        # does not raise under a non-UTF-8 ambient codec. Implies text mode.
        r = subprocess.run(
            [GH, 'issue', 'view', str(issue), '--json', 'body', '-q', '.body'],
            check=True, capture_output=True, encoding="utf-8",
        )
    except (subprocess.CalledProcessError, OSError) as e:
        # OSError covers a gh that cannot execute at all (ENOEXEC shim, absent
        # binary — the host class DEVFLOW_GH exists for); it carries no
        # .stderr, so fall back to str(e).
        msg = e.stderr.strip() if isinstance(e, subprocess.CalledProcessError) else str(e)
        sys.stderr.write(f"parse-acs.py: gh issue view failed: {msg}\n")
        sys.exit(1)
    return r.stdout


def _parse_checkboxes(section_lines: list[str]) -> list[dict]:
    """Parse checkbox items (shared module), then classify each post-merge.

    `section_parse.parse_checkboxes` owns the shared half: a criterion emitted
    by /devflow:create-issue at ~80 columns wraps across several physical lines,
    and it joins each item's continuation lines so a wrapped criterion
    round-trips verbatim. Trigger-phrase classification stays HERE because it is
    a mirror-time-only rule — `workpad.py` reads a tag already present in the
    stored text and must never re-derive it, which would re-tag a criterion the
    orchestrator had deliberately demoted.

    Classifying on the fully-joined text is load-bearing: a trigger phrase that
    landed past the wrap must still be caught.
    """
    items = parse_checkboxes(section_lines)
    for item in items:
        item['post_merge'] = _is_post_merge(item['text'])
    return items


def _is_post_merge(text: str) -> bool:
    return any(r.search(text) for r in _POST_MERGE_RES)


def _warn_near_miss(parsed: list, body: str, canonical: str, needle: str) -> None:
    if parsed:
        return
    if re.search(r'(?im)^#{2,3}\s+.*' + re.escape(needle), body):
        sys.stderr.write(
            f"parse-acs.py: no {canonical} items parsed, but the body contains "
            f"a heading that mentions '{needle}' — check that it is exactly "
            f"'## {canonical}' (any casing is fine, but no trailing colon or "
            f"extra words).\n"
        )


def _is_unreadable_section(parsed: list, section_lines: list) -> bool:
    """True for the present-but-unreadable case (issue #1198).

    The section was matched (`extract_section` returned a non-empty line list)
    and carries at least one non-blank line, yet `parse_checkboxes` found zero
    items — its criteria are written in a shape this parser does not read. This
    is deliberately distinct from a genuinely absent section, for which
    `section_lines` is empty; the two must not be collapsed (*unknown is not
    zero*). A present-but-empty section (heading immediately followed by another
    heading) has no content and is NOT unreadable — there is nothing to read.
    """
    return not parsed and any(line.strip() for line in section_lines)


def _warn_unreadable_section(canonical: str) -> None:
    """Item-shape diagnostic for the present-but-unreadable case (issue #1198).

    Deliberately names ITEM SHAPE as the cause and does NOT send the reader to
    inspect the heading (which already matches) — that is the misdirection the
    old `_warn_near_miss` message produced when it fired on this case. The
    reader/agent hand-extracts the criteria from the issue body.
    """
    sys.stderr.write(
        f"parse-acs.py: the '## {canonical}' section is present and correctly "
        f"named, but zero items were parsed from it because its items are "
        f"written in a shape this parser does not read. Only markdown checkbox "
        f"list items ('- [ ]', '- [x]', '* [ ]', '* [x]') are recognised as "
        f"{canonical} items; bold paragraphs ('**AC1 - ...**') and numbered "
        f"lists ('1. ...') are not. Extract the items by hand from the issue "
        f"body — do not treat this as an issue with no {canonical}.\n"
    )


def _diagnose_section(parsed, section_lines, body, canonical, needle) -> bool:
    """Emit the right zero-item diagnostic for one section and report unreadability.

    Case 1 (present-but-unreadable) takes precedence over case 2 (heading
    near-miss): when the section IS matched, the heading is by definition not
    the problem, so `_warn_near_miss` (which would otherwise fire on the
    matching heading and misdirect) must not run for it. Returns whether the
    section is present-but-unreadable, for the caller's JSON field.
    """
    if _is_unreadable_section(parsed, section_lines):
        _warn_unreadable_section(canonical)
        return True
    _warn_near_miss(parsed, body, canonical, needle)
    return False


def _render_md(criteria: list[dict], test_plan: list[dict]) -> str:
    if not criteria and not test_plan:
        return '_(none provided in issue body)_'
    lines: list[str] = []
    for item in criteria:
        lines.append(_render_md_line(item))
    if test_plan:
        lines.append('')
        for item in test_plan:
            lines.append(_render_md_line(item))
    return '\n'.join(lines)


def _render_md_line(item: dict) -> str:
    # Both the containment test and the appended tag read the SHARED
    # `POST_MERGE_TAG` constant rather than re-spelling the literal here. The
    # read side (`workpad.py`'s post-merge filter) already tests that constant,
    # so the constant removes exactly one failure mode: LITERAL drift between
    # the two sites. It does NOT make them agree on what counts as tagged — the
    # PREDICATES are deliberately different. The writer suppresses on
    # containment (`POST_MERGE_TAG.strip() not in text`), while the reader tests
    # a suffix (`is_post_merge_tagged` -> `text.rstrip().endswith(...)`). So a
    # criterion carrying the phrase mid-string ("Verify (post-merge) that the
    # hook fires") is neither tagged by the writer nor excluded by the reader's
    # filter. That mid-string residual survives the shared constant.
    text = item['text']
    if item['post_merge'] and POST_MERGE_TAG.strip() not in text:
        text = f'{text}{POST_MERGE_TAG}'
    return render_line({'text': text, 'ticked': item['ticked']})


def main():
    _force_utf8_streams()
    p = argparse.ArgumentParser(prog='parse-acs.py')
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument('--issue', type=int, help='Fetch the issue body via gh.')
    src.add_argument('--body-file', help='Read body from a local file.')
    p.add_argument('--format', choices=('md', 'json'), default='md')
    p.add_argument(
        '--anchor-repo-root', action='store_true',
        help='Resolve --body-file against the checkout root (issue #1633 anchoring '
             'mode), so the enrolled fence passes a repository-relative path and '
             'need not compute the repository root itself.')
    args = p.parse_args()

    if args.issue is not None:
        body = _fetch_body(args.issue)
    else:
        body_file = args.body_file
        if args.anchor_repo_root and body_file and not os.path.isabs(body_file):
            # Resolve against `git rev-parse --show-toplevel` so a run from the repo
            # root, a subdirectory, or a linked worktree all resolve the same target.
            # An absent/unlaunchable git is the same unresolved-root condition as a
            # non-zero exit; letting OSError escape would replace the fail-closed
            # breadcrumb below with a traceback (preflight.py's _run_git contract).
            try:
                top = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                                     capture_output=True, text=True)
                rc, root = top.returncode, top.stdout.strip()
            except OSError:
                rc, root = 1, ''
            if rc != 0 or not root:
                # Fail closed on a non-zero exit rather than silently anchoring to cwd;
                # the §1.2 fence routes any non-zero parse exit to the run's stop path.
                print('parse-acs.py: could not resolve the repository root to anchor '
                      f'{body_file!r}', file=sys.stderr)
                return 1
            body_file = os.path.join(root, body_file)
        try:
            body = Path(body_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"parse-acs.py: --body-file: could not read {body_file!r}: "
                  f"{e}", file=sys.stderr)
            return 1
        except UnicodeDecodeError as e:
            print(f"parse-acs.py: --body-file: {body_file!r} is not valid "
                  f"UTF-8: {e}", file=sys.stderr)
            return 1

    ac_lines = extract_section(body, 'Acceptance Criteria')
    criteria = _parse_checkboxes(ac_lines)
    tp_lines = extract_section(body, 'Test Plan')
    test_plan = _parse_checkboxes(tp_lines)

    # Two distinct zero-item failure modes, kept distinguishable (issue #1198):
    # present-but-unreadable (matched section, unreadable item shape) vs heading
    # near-miss (no section matched). `_diagnose_section` owns the precedence
    # rule so it lives in one place; it returns whether the section was
    # present-but-unreadable, for the JSON fields below.
    ac_unreadable = _diagnose_section(criteria, ac_lines, body, 'Acceptance Criteria', 'acceptance')
    tp_unreadable = _diagnose_section(test_plan, tp_lines, body, 'Test Plan', 'test plan')

    if args.format == 'json':
        # `acceptance_criteria_unreadable` / `test_plan_unreadable` are additive
        # fields: the present-but-unreadable signal (issue #1198) for a consumer
        # reading JSON rather than stderr. Absent-section and parsed-section
        # cases both report false.
        print(json.dumps({'acceptance_criteria': criteria, 'test_plan': test_plan,
                          'acceptance_criteria_unreadable': ac_unreadable,
                          'test_plan_unreadable': tp_unreadable},
                         indent=2))
    else:
        print(_render_md(criteria, test_plan))


if __name__ == '__main__':
    raise SystemExit(main())

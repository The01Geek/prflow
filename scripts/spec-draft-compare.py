#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Save the draft bytes a spec audit round read, and compare a later draft with them (issue #3987).

    spec-draft-compare.py save --draft <path> --object-id <oid>
    spec-draft-compare.py compare --draft <path> [--object-id <oid>]

Bad arguments print argparse's usage error and exit 2.

save writes a byte-exact copy of <draft> to `audited-draft-<oid>.md` beside it, <oid> being the
`git hash-object --no-filters` digest the round computed. It prints `saved: <copy path>` and exits
0, or prints `save-failed: <cause>` and exits 1.

compare takes the latest verdict round's `draft-object-id`, checks that `git hash-object
--no-filters` of that round's copy equals it, and compares the copy with <draft> section by
section. Before a `non-consequential` or `consequential` verdict it prints one `changed: <section>`
line per section whose lines differ or that only one draft has (`changed: (section order)` when the
order of consequential sections changed and no line in one did). It prints exactly one verdict line
last and exits 0 (a crash prints a traceback instead):

    verdict: non-consequential
    verdict: consequential
    verdict: unavailable <reason>

`non-consequential` means no line outside the non-consequential sections changed, an unchanged
draft included. <reason> is one of no-verdict-round (no or empty --object-id), bad-object-id, copy-missing,
copy-unreadable, hash-failed, object-id-mismatch, draft-unreadable, open-fence, unclear-heading
(a changed draft that would read non-consequential while `sections` reports either one unclear).

The non-consequential sections are exactly the first `##` heading outside a fenced code block
whose text is `Technical Context` and the first whose text is `Implementation Notes`,
case ignored, each running to the next such `##` heading. Every other line is consequential: text
before the first heading, a renamed heading, a second copy of either heading and a level-3
heading's section included. A fence closes only on a
line of its opener's character at least as long as the opener; a fence or HTML comment still open
at the end of either draft gives `unavailable open-fence`.
"""
import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from section_parse import Fence

NON_CONSEQUENTIAL = {('technical context', 1), ('implementation notes', 1)}
PREAMBLE = (None, 0)
_OID_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
_ATX2_RE = re.compile(r'^ {0,3}##(?:[ \t]+(.*?))?\s*$')
_CLOSING_RE = re.compile(r'(?:^|[ \t]+)#+$')
_COMMENT_RE = re.compile(r'^ {0,3}<!--')
_HTML_RE = re.compile(r'^ {0,3}</?[A-Za-z]')
_AMBIGUOUS_RE = re.compile(r'^\s*(?:(?:[-*+]|\d{1,9}[.)])\s+)?(?:`{3,}|~{3,})|^ {0,3}<(?:pre|script|style|textarea|\?|![A-Z[])',
                           re.IGNORECASE)
# After any indent and list or quote markers, a `#` or `##` heading; a line of only `-`, `=` and
# spaces after any quote markers and an optional ordered-list marker (a setext underline or rule);
# or an HTML heading tag anywhere.
_UNDERLINE = r'^[\s>]*(?:\d{1,9}[.)]\s+)?(?:[-=][ \t]*)+$'
_MAYBE_HEADING_RE = re.compile(r'^\s*(?:>\s*|(?:[-*+]|\d{1,9}[.)])\s+)*#{1,2}(?:\s|$)|' + _UNDERLINE
                               + r'|<h[1-6](?:[\s>/]|$)', re.IGNORECASE)
_LINE_END_RE = re.compile(r'\r\n?|\n')


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8; never call at import, which would change an importing test's streams."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def _out(line):
    print(line, flush=True)


def _copy_path(draft, oid):
    return os.path.join(os.path.dirname(os.path.abspath(draft)), f'audited-draft-{oid}.md')


def _read(path):
    with open(path, 'rb') as fh:
        return fh.read().decode('utf-8', 'surrogateescape')


def sections(text):
    """([(key, label, lines)] in order, unclear), or None when a fence or HTML comment is still open at the end.

    A section opens at a `##` line indented at most 3 spaces outside a fenced code block, and runs to
    the next one; a closing `#` run is not heading text. `unclear` is True when such a line sits in an
    HTML comment, when a non-consequential section's heading is not a column-0 one outside an HTML
    block and below no possibly misread fence (an `_AMBIGUOUS_RE` line outside an HTML comment that
    follows an open HTML block line or that the fence tracker neither opened on nor was inside), or
    when such a section holds a possibly misread fence or a `_MAYBE_HEADING_RE` line outside a fence.
    A line ends at LF, CRLF or a lone CR.
    """
    fence, seen, comment, html, ambiguous, unclear = Fence(), {}, False, False, False, False
    result = [(PREAMBLE, '(text before the first heading)', [])]
    for line in _LINE_END_RE.split(text):
        misread = in_comment = False
        if comment or (not fence.is_open and _COMMENT_RE.match(line)):
            hidden, in_comment, comment = False, True, '-->' not in line
        else:
            was_open = fence.is_open
            hidden = fence.feed(line)
            misread = bool(_AMBIGUOUS_RE.match(line)) and (html or not (was_open or hidden))
            ambiguous = ambiguous or misread
        if not line.strip():
            html = False
        elif not hidden and not in_comment and _HTML_RE.match(line):
            html = True
        heading = None if hidden else _ATX2_RE.match(line)
        key, label, lines = result[-1]
        if heading:
            name = _CLOSING_RE.sub('', (heading.group(1) or '').strip())
            count = seen[name.lower()] = seen.get(name.lower(), 0) + 1
            key = (name.lower(), count)
            if in_comment or (key in NON_CONSEQUENTIAL and not (line.startswith('##') and not html and not ambiguous)):
                unclear = True
            label = name or '(empty heading)'
            result.append((key, label if count == 1 else f'{label} (copy {count})', [line]))
        else:
            if key in NON_CONSEQUENTIAL and (misread or (not hidden and _MAYBE_HEADING_RE.search(line))):
                unclear = True
            lines.append(line)
    return None if fence.is_open or comment else (result, unclear)


def compare(old_text, new_text):
    """(changed labels, verdict) for two draft bodies; verdict `unavailable open-fence` when `sections` returns None for either."""
    old, new = sections(old_text), sections(new_text)
    if old is None or new is None:
        return [], 'unavailable open-fence'
    (old, old_unclear), (new, new_unclear) = old, new
    old_by_key = {key: lines for key, _, lines in old}
    new_by_key = {key: lines for key, _, lines in new}
    labels = {key: label for key, label, _ in old + new}
    keys = [key for key, _, _ in new] + [key for key, _, _ in old if key not in new_by_key]
    changed_keys = [key for key in keys if old_by_key.get(key) != new_by_key.get(key)]
    changed = [labels[key] for key in changed_keys]
    old_cons = [(key, lines) for key, _, lines in old if key not in NON_CONSEQUENTIAL]
    new_cons = [(key, lines) for key, _, lines in new if key not in NON_CONSEQUENTIAL]
    if old_cons == new_cons:
        if changed and (old_unclear or new_unclear):
            return [], 'unavailable unclear-heading'
        return changed, 'non-consequential'
    if all(key in NON_CONSEQUENTIAL for key in changed_keys):
        changed.append('(section order)')
    return changed, 'consequential'


def _hash(path):
    try:
        done = subprocess.run(['git', 'hash-object', '--no-filters', path], capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    except OSError as exc:
        print(f'spec-draft-compare.py: git hash-object failed: {exc}', file=sys.stderr)
        return None
    if done.returncode != 0:
        print(f'spec-draft-compare.py: git hash-object exited {done.returncode}: {done.stderr.strip()}',
              file=sys.stderr)
        return None
    return done.stdout.strip()


def _save(draft, oid):
    if not _OID_RE.match(oid or ''):
        _out('save-failed: bad-object-id')
        return 1
    copy = _copy_path(draft, oid)
    tmp = None
    try:
        with open(draft, 'rb') as fh:
            data = fh.read()
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(copy), prefix='.audited-draft-')
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, copy)
    except OSError as exc:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError as cleanup:
                print(f'spec-draft-compare.py: could not remove {tmp}: {cleanup}', file=sys.stderr)
        _out(f'save-failed: {type(exc).__name__}: {exc}')
        return 1
    _out(f'saved: {copy}')
    return 0


def _compare(draft, oid):
    reason = None
    if not oid:
        reason = 'no-verdict-round'
    elif not _OID_RE.match(oid):
        reason = 'bad-object-id'
    else:
        copy = _copy_path(draft, oid)
        try:
            if not stat.S_ISREG(os.stat(copy).st_mode):
                raise OSError('not a regular file')
        except FileNotFoundError:
            reason = 'copy-missing'
        except OSError as exc:
            print(f'spec-draft-compare.py: copy unreadable: {exc}', file=sys.stderr)
            reason = 'copy-unreadable'
        if reason is None:
            digest = _hash(copy)
            if digest is None:
                reason = 'hash-failed'
            elif digest != oid:
                reason = 'object-id-mismatch'
    if reason is None:
        try:
            old_text = _read(copy)
        except OSError as exc:
            print(f'spec-draft-compare.py: copy unreadable: {exc}', file=sys.stderr)
            reason = 'copy-unreadable'
    if reason is None:
        try:
            new_text = _read(draft)
        except OSError as exc:
            print(f'spec-draft-compare.py: draft unreadable: {exc}', file=sys.stderr)
            reason = 'draft-unreadable'
    if reason is not None:
        _out(f'verdict: unavailable {reason}')
        return 0
    changed, verdict = compare(old_text, new_text)
    for label in changed:
        _out(f'changed: {label}')
    _out(f'verdict: {verdict}')
    return 0


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(prog='spec-draft-compare.py')
    parser.add_argument('mode', choices=('save', 'compare'))
    parser.add_argument('--draft', required=True)
    parser.add_argument('--object-id', default='')
    args = parser.parse_args(argv)
    if args.mode == 'save':
        return _save(args.draft, args.object_id)
    return _compare(args.draft, args.object_id)


if __name__ == '__main__':
    sys.exit(main())

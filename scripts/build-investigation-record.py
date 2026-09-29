#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Assemble a spec run's investigation-record comment body in place.

    build-investigation-record.py --record <record-file> --derivation <derivation-file>

Rewrites <record-file> as: the marker line; the file's prior content (its first non-blank line
removed when that line is the marker); the derivation artifact's `Considered-and-rejected:` line
(the first outside a code fence, else the first inside one); then every
`## Criterion disposition record`, `## Steelman record`, `## Self-audit record` and
`## Evidence bundle` section of the artifact, in file order (no spec step writes
`## Self-audit record` yet: it is a planned new name for `## Steelman record`). Headings are
CommonMark ATX headings (up to three spaces of indent, an optional closing `#` run); one inside a
code fence is not a heading, and every line starting `Considered-and-rejected:` is dropped from
copied sections. A leading BOM is dropped from both files. The trigger tokens `/prflow:`,
`/devflow:` and `@claude`, in any letter case, are broken with U+200B, and the result is kept
within 65,536 UTF-8 bytes, a conservative bound on GitHub's 65,536-character comment limit, by
truncating the largest folded sections first, then omitting sections left at their heading whole
under one notice naming them; a record that still does not fit is oversize. Run it once per
written bucket: a re-run folds the sections and the `Considered-and-rejected:` line again.

Prints exactly one stdout line (none when stdout is unwritable or the print is interrupted) and
always exits 0; only `record=ready` rewrites the file, barring an interrupt just after the rewrite.
`folded=` names the sections in the record, `truncated=` those of them that were cut, and
`omitted=` those left out whole; each field names a heading once, so a heading with one kept and
one omitted occurrence appears in both `folded=` and `omitted=`:

    record=ready bytes=<n> folded=<names|none> truncated=<names|none> omitted=<names|none> considered-and-rejected=<present|absent|unestablished>
    record=empty
    record=unavailable reason=<oversize|record-unreadable|write-failed|usage|internal-error>

Stderr names each cause (an unreadable file, an oversize record, a failed write, a usage or
internal error), a temp file it could not remove, any heading that names a folded section but
differs from it in level, letter case, spacing or punctuation, which starts no folded section, and a
code fence opener the derivation artifact never closes, which is read as text; the record closes any
fence still open at a copied section's end.
"""
import argparse
import os
import re
import sys
import tempfile
import traceback
from typing import NamedTuple

MARKER = '<!-- prflow:investigation-record -->'
COMMENT_BYTE_LIMIT = 65536
FOLDED = ('Criterion disposition record', 'Steelman record', 'Self-audit record', 'Evidence bundle')
CONSIDERED = 'Considered-and-rejected:'
EMPTY = 'record=empty'
OVERSIZE, RECORD_UNREADABLE, WRITE_FAILED, USAGE, INTERNAL_ERROR = (
    f'record=unavailable reason={reason}'
    for reason in ('oversize', 'record-unreadable', 'write-failed', 'usage', 'internal-error'))
_TRIGGER_RE = re.compile(r'(/(?=prflow:|devflow:)|@(?=claude))', re.IGNORECASE)
_FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_HEADING_RE = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$')
_CLOSING_RUN_RE = re.compile(r'(?:^|[ \t]+)#+[ \t]*$')


class Section(NamedTuple):
    name: str
    lines: list[str]  # starts with the heading line


class Fitted(NamedTuple):
    rendered: str
    folded: list[str]
    truncated: list[str]  # folded sections that were cut
    omitted: list[str]  # sections left out whole


def _byte_len(text):
    return len(text.encode('utf-8'))


def _cause(exc):
    return f'{type(exc).__name__}: {exc}'


def _warn(message):
    _emit(f'build-investigation-record.py: {message}', 'stderr')


def _read_text(path, role):
    """Return the file decoded as UTF-8, or None, naming the cause on stderr, when missing, unreadable or not UTF-8."""
    try:
        with open(path, 'rb') as fh:
            return fh.read().decode('utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        _warn(f'{role} unreadable: {path}: {_cause(exc)}')
        return None


def _lines(text):
    """Split at \\n only; str.splitlines also splits at \\f, \\x85, U+2028 and a bare \\r."""
    return re.findall(r'[^\n]*\n|[^\n]+', text)


def _bare(line):
    return line.rstrip('\r\n')


class _Fence:
    """Tracks whether a line sits inside a fenced code block."""

    def __init__(self):
        self._open = None  # (indent, char, length) of the open fence

    def feed(self, line):
        """Advance past `line`; return True when it is inside a fence or is a fence line."""
        m = _FENCE_RE.match(_bare(line))
        if self._open is None:
            if m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
                self._open = (_bare(line)[:m.start(1)], m.group(1)[0], len(m.group(1)))
                return True
            return False
        _, char, length = self._open
        if m and m.group(1)[0] == char and len(m.group(1)) >= length and not m.group(2).strip():
            self._open = None
        return True

    @property
    def is_open(self):
        return self._open is not None

    def closer(self):
        """Return the line closing the open fence at its opener's indent, so a list item's fence closes
        inside the item; '' when none is open."""
        if not self.is_open:
            return ''
        indent, char, length = self._open
        return indent + char * length + '\n'


def _heading(bare):
    """Return (level, text) for an ATX heading line, else None."""
    m = _HEADING_RE.match(bare)
    if not m:
        return None
    return len(m.group(1)), _CLOSING_RUN_RE.sub('', m.group(2)).strip()


def _key(name):
    return re.sub(r'[^0-9a-z]', '', name.lower())


_FOLDED_KEYS = {_key(name) for name in FOLDED}


def _scan(lines, as_text):
    """One pass over the artifact, with the fence openers at the indexes in `as_text` read as text.

    Return (considered lines by in-fence flag, sections, index of an unclosed opener or None, near-miss headings).
    """
    considered = {}
    sections, near_misses = [], []
    current = None
    fence = _Fence()
    opened_at = None
    for index, line in enumerate(lines):
        was_open = fence.is_open
        in_fence = index not in as_text and fence.feed(line)
        if fence.is_open and not was_open:
            opened_at = index
        bare = _bare(line)
        if bare.startswith(CONSIDERED):
            considered.setdefault(in_fence, line if line.endswith('\n') else line + '\n')
            continue
        heading = None if in_fence else _heading(bare)
        if heading is not None:
            level, name = heading
            if level == 2 and name in FOLDED:
                current = Section(name, [line])
                sections.append(current)
                continue
            if _key(name) in _FOLDED_KEYS:
                near_misses.append(bare)
            if level <= 2:
                current = None
                continue
        if current is not None:
            current.lines.append(line)
    return considered, sections, opened_at if fence.is_open else None, near_misses


def _parse(text):
    """Return (considered line or None, [Section, ...]) from a derivation artifact, naming each unclosed
    fence opener and each near-miss heading on stderr."""
    lines = _lines(text)
    as_text = set()
    while True:
        considered, sections, unclosed, near_misses = _scan(lines, as_text)
        if unclosed is None:
            break
        _warn(f'derivation line {unclosed + 1} opens a code fence that never closes; it is read as text')
        as_text.add(unclosed)
    for bare in near_misses:
        _warn(f'heading starts no folded section, level or spelling differs: {bare}')
    return considered.get(False, considered.get(True)), sections


def _neutralize(text):
    return _TRIGGER_RE.sub('\\1\u200b', text)


def _slug(name):
    return name.lower().replace(' ', '-')


def _names(names):
    seen = []
    for name in names:
        if _slug(name) not in seen:
            seen.append(_slug(name))
    return ','.join(seen) or 'none'


def _truncate(head, sections):
    """Cut the largest sections at line boundaries, then omit heading-only ones whole, until the record fits.

    Return a `Fitted`, or None when no omission leaves a record that fits.
    """
    notices = {}
    omitted = []
    kept = [list(section.lines) for section in sections]

    def render(i):
        if i in omitted:
            return ''
        body = ''.join(kept[i])
        fence = _Fence()  # Unlike _parse, every opener counts: GitHub renders an unclosed one as a fence.
        for line in kept[i]:
            fence.feed(line)
        tail = fence.closer() + notices.get(i, '')
        if tail and body and not body.endswith('\n'):
            body += '\n'
        return body + tail

    def omission():
        if not omitted:
            return ''
        names = ', '.join(dict.fromkeys(sections[i].name for i in sorted(omitted)))
        standing = [render(i) for i in range(len(kept)) if i not in omitted]
        lead = '\n' if standing and not standing[-1].endswith('\n') else ''
        return f'{lead}[omitted: {names} to keep the record within {COMMENT_BYTE_LIMIT:,} bytes]\n'

    def total():
        return (_byte_len(head) + sum(_byte_len(render(i)) for i in range(len(kept)))
                + _byte_len(omission()))

    def largest(indexes):
        return max(indexes, key=lambda k: (_byte_len(render(k)), -k))

    while total() > COMMENT_BYTE_LIMIT:
        candidates = [i for i in range(len(kept)) if len(kept[i]) > 1 and i not in omitted]
        if not candidates:
            standing = [i for i in range(len(kept)) if i not in omitted]
            if not standing:
                return None
            omitted.append(largest(standing))
            continue
        i = largest(candidates)
        notices[i] = (f'[truncated: {sections[i].name} cut to keep the record within '
                      f'{COMMENT_BYTE_LIMIT:,} bytes]\n')
        excess = total() - COMMENT_BYTE_LIMIT
        while len(kept[i]) > 1 and excess > 0:
            line = kept[i].pop()
            excess -= _byte_len(line)
            # Popping a fence line or an unterminated line can change the closer or newline render adds.
            if excess <= 0 or _FENCE_RE.match(_bare(line)) or not line.endswith('\n'):
                excess = total() - COMMENT_BYTE_LIMIT
    rendered = ''.join(render(i) for i in range(len(kept))) + omission()
    return Fitted(rendered, [s.name for i, s in enumerate(sections) if i not in omitted],
                  [sections[i].name for i in sorted(set(notices) - set(omitted))],
                  [sections[i].name for i in sorted(omitted)])


def build(record_path, derivation_path):
    record = _read_text(record_path, 'record')
    if record is None:
        return RECORD_UNREADABLE
    lines = _lines(record.removeprefix('\ufeff'))
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is not None and lines[first].strip() == MARKER:
        del lines[first]
    prior = ''.join(lines)
    if _byte_len(prior) > COMMENT_BYTE_LIMIT:
        _warn(f'oversize: the bucket is {_byte_len(prior):,} bytes, over the {COMMENT_BYTE_LIMIT:,}-byte limit')
        return OVERSIZE

    derivation = _read_text(derivation_path, 'derivation')
    if derivation is None:
        considered, sections, state = None, [], 'unestablished'
    else:
        considered, sections = _parse(derivation.removeprefix('\ufeff'))
        state = 'present' if considered else 'absent'
    if not sections and considered is None and not prior.strip():
        return EMPTY

    if prior and not prior.endswith('\n'):
        prior += '\n'
    head = MARKER + '\n' + _neutralize(prior + (considered or ''))
    folded = [Section(s.name, [_neutralize(line) for line in s.lines]) for s in sections]
    fitted = _truncate(head, folded)
    if fitted is None:
        if folded:
            _warn(f'oversize: the record without its sections takes {_byte_len(head):,} of '
                  f'{COMMENT_BYTE_LIMIT:,} bytes, too few to name the omitted sections')
        else:
            _warn(f'oversize: the record is {_byte_len(head):,} bytes, over the {COMMENT_BYTE_LIMIT:,}-byte limit')
        return OVERSIZE
    out = (head + fitted.rendered).encode('utf-8')
    tmp_path = None
    replaced = False
    try:
        # A fresh temp file beside the record: no leftover or foreign path can block or be clobbered.
        fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(record_path) + '.', suffix='.tmp',
                                        dir=os.path.dirname(os.path.abspath(record_path)))
        os.close(fd)
        with open(tmp_path, 'wb') as fh:
            fh.write(out)
        os.replace(tmp_path, record_path)  # A failed write must leave the bucket intact.
        replaced = True
    except OSError as exc:
        _warn(f'write failed: {record_path}: {_cause(exc)}')
        return WRITE_FAILED
    finally:
        if tmp_path is not None and not replaced:  # Also on an interrupt: the temp file is this run's own.
            try:
                os.remove(tmp_path)
            except FileNotFoundError:  # An interrupt just after os.replace renamed it: nothing is left.
                pass
            except OSError as exc:
                _warn(f'temp file not removed: {tmp_path}: {_cause(exc)}')
    return (f'record=ready bytes={len(out)} folded={_names(fitted.folded)} truncated={_names(fitted.truncated)} '
            f'omitted={_names(fitted.omitted)} considered-and-rejected={state}')


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8; never at import, which would mutate a test importer's streams."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError, OSError):
            pass


def _emit(line, stream_name='stdout'):
    """Print and flush `line`; an unwritable stream is pointed at os.devnull, or dropped, so exit stays 0."""
    stream = getattr(sys, stream_name)
    if stream is None:  # print(file=None) would write to stdout.
        return
    try:
        print(line, file=stream, flush=True)
    except KeyboardInterrupt:  # A cut or missing line makes the caller withhold.
        return
    except (OSError, ValueError):
        try:
            target = stream.fileno()
            fd = os.open(os.devnull, os.O_WRONLY)
            if fd != target:
                os.dup2(fd, target)  # The interpreter's exit-time flush then succeeds.
                os.close(fd)
        except (OSError, ValueError, AttributeError):
            setattr(sys, stream_name, None)


def main(argv=None):
    try:
        _force_utf8_streams()
        parser = argparse.ArgumentParser(description=(__doc__ or '').split('\n\n')[0], add_help=False)
        parser.add_argument('--record', required=True)
        parser.add_argument('--derivation', required=True)
        try:
            args = parser.parse_args(argv)
        except SystemExit:  # argparse's usage error; its message is already on stderr.
            line = USAGE
        else:
            line = build(args.record, args.derivation)
    except (Exception, KeyboardInterrupt) as exc:  # Still one decided line; the caller withholds on it.
        line = INTERNAL_ERROR
        try:
            frames = traceback.extract_tb(exc.__traceback__)
            own = [f for f in frames if os.path.abspath(f.filename) == os.path.abspath(__file__)]
            frame = (own or frames)[-1]
            where = f' (at {os.path.basename(frame.filename)}:{frame.lineno} in {frame.name})'
        except (Exception, KeyboardInterrupt):  # The location is best-effort; the decided line is not.
            where = ''
        try:
            _warn(f'{_cause(exc)}{where}')
        except (Exception, KeyboardInterrupt):
            _warn(f'{type(exc).__name__}{where}')
    _emit(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())

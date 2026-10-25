#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Publish a spec run's investigation record as a comment on the issue the run created or updated.

    build-investigation-record.py --issue <n> --record <record-file> --derivation <derivation-file>
                                  [--config <config-file>]

First the gate: publication is withheld exactly when `config-get.sh
.spec.investigation_record_enabled true <config-file>` would print `false`, `telemetry.enabled`
inheritance included. <config-file> defaults to the repository root's `.prflow/config.json`, as
config-get.sh resolves it. A withheld record is neither assembled nor posted.

Then the assembly, rewriting <record-file> as: the marker line; the file's prior content (its
first non-blank line removed when that line is the marker); then the derivation artifact's
`Considered-and-rejected:` line (the first outside a code fence, else the first inside one),
posted from its prefix. Outside a fence the line may be indented with spaces or tabs and may start
with one `-`, `*` or `+` marker and whitespace; inside one it starts at column 0; a line with other
text before the prefix is never taken. A line taken outside a fence also takes each following line
until the text so far, ignoring trailing whitespace and any closing brackets, quotes, `*` or `_`,
ends in `.`, `!` or `?`, or the next line is blank, starts after any indent with ``` or ~~~, is a
heading, a list item or another line taken outside a fence, or the file ends. An extended line is
posted as one line, its pieces trimmed and joined with single spaces. When the derivation supplies
a line, each prior-content line outside a fence that the outside-fence shape takes is dropped,
that physical line only. A leading BOM is dropped from both files. The trigger tokens `/prflow:`,
`/devflow:` and `@claude`, in any letter case, are broken with U+200B. A record over 65,536
written UTF-8 bytes, a conservative bound on GitHub's 65,536-character comment limit, is oversize.
Run it once per written bucket: a re-run posts a second comment. An empty --derivation argument
reads no artifact (state `unestablished`). <record-file> is rewritten before the post is
attempted, so a posted, gh-unavailable or post-failed outcome, or an internal error after that
point, leaves it rewritten.

Last the post: `gh api --method POST repos/{owner}/{repo}/issues/<n>/comments -F body=@<record-file>`,
with gh resolved as DEVFLOW_GH, else `gh`.

Prints exactly one stdout line (none when stdout is unwritable or the print is interrupted) and
always exits 0:

    record=posted bytes=<n> considered-and-rejected=<present|absent|unestablished>
    record=withheld reason=config
    record=empty
    record=not-posted reason=<oversize|record-unreadable|write-failed|gh-unavailable|post-failed|usage|internal-error>

Stderr names each cause (an unreadable file or config, a superseded config key, an oversize record, a failed write, an
unrunnable or failing gh, a usage or internal error), a temp file it could not remove, and a code
fence opener the derivation artifact never closes, which is read as text.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
    from ancestor_config import warn_ancestor_config as _warn_ancestor_config
    from state_dir import state_config_path as _state_config_path
except Exception:  # A partial vendored copy without lib/: resolve as lib/state_dir.py does.
    def _state_config_path(repo_root, filename='config.json', stream=None):
        legacy_only = not os.path.isdir(os.path.join(repo_root, '.prflow')) and os.path.isdir(
            os.path.join(repo_root, '.devflow'))
        if legacy_only:
            print(f'build-investigation-record.py: reading the superseded {repo_root}/.devflow/; run /prflow:init',
                  file=sys.stderr)
        return os.path.join(repo_root, '.devflow' if legacy_only else '.prflow', filename)

    def _warn_ancestor_config(repo_root, reader, remedy='', stream=None):
        return None

try:  # Refreshed-token env for gh calls on native Windows (see gh_fresh_env.py).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gh_fresh_env import fresh_gh_env
except Exception:  # A partial copy without the sibling inherits the ambient token.
    def fresh_gh_env(env=None, os_name=None):
        return env

MARKER = '<!-- prflow:investigation-record -->'
COMMENT_BYTE_LIMIT = 65536
CONSIDERED = 'Considered-and-rejected:'
GATE_KEY = ('spec', 'investigation_record_enabled')
POSTED = 'record=posted bytes={} considered-and-rejected={}'
WITHHELD = 'record=withheld reason=config'
EMPTY = 'record=empty'
OVERSIZE, RECORD_UNREADABLE, WRITE_FAILED, GH_UNAVAILABLE, POST_FAILED, USAGE, INTERNAL_ERROR = (
    f'record=not-posted reason={reason}'
    for reason in ('oversize', 'record-unreadable', 'write-failed', 'gh-unavailable', 'post-failed', 'usage',
                   'internal-error'))
_TRIGGER_RE = re.compile(r'(/(?=prflow:|devflow:)|@(?=claude))', re.IGNORECASE)
_FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_SHAPE_RE = re.compile(r'[ \t]*(?:[-*+][ \t]+)?(?=' + re.escape(CONSIDERED) + ')')
_SENTENCE_END_RE = re.compile('[.!?][)\\]}"\'’”*_]*$')
_JOIN_STOP_RE = re.compile(r'[ \t]*(?:```|~~~|#{1,6}(?:[ \t]|$)|(?:[-*+]|[0-9]+[.)])[ \t])')


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
        self._open = None  # (char, length) of the open fence

    def feed(self, line):
        """Advance past `line`; return True when it is inside a fence or is a fence line."""
        m = _FENCE_RE.match(_bare(line))
        if self._open is None:
            if m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
                self._open = (m.group(1)[0], len(m.group(1)))
                return True
            return False
        char, length = self._open
        if m and m.group(1)[0] == char and len(m.group(1)) >= length and not m.group(2).strip():
            self._open = None
        return True

    @property
    def is_open(self):
        return self._open is not None


def _fence_flags(lines, unclosed=lambda index: None):
    """Return each line's in-fence flag, each opener that never closes read as text and passed to `unclosed`."""
    as_text = set()
    while True:
        fence, flags, opened_at = _Fence(), [], None
        for index, line in enumerate(lines):
            was_open = fence.is_open
            flags.append(index not in as_text and fence.feed(line))
            if fence.is_open and not was_open:
                opened_at = index
        if not fence.is_open:
            return flags
        unclosed(opened_at)
        as_text.add(opened_at)


def _start(line, in_fence):
    """Return where a taken line's prefix starts, or None when the line is not taken."""
    if in_fence:
        return 0 if line.startswith(CONSIDERED) else None
    m = _SHAPE_RE.match(line)
    return m.end() if m else None


def _join(lines, index, start, extend):
    """Return the taken line at `index` from its prefix, extended by the join rule when `extend`."""
    pieces = [lines[index][start:]]
    for line in lines[index + 1:] if extend else ():
        if (_SENTENCE_END_RE.search(pieces[-1].rstrip()) or not line.strip() or _JOIN_STOP_RE.match(_bare(line))
                or _SHAPE_RE.match(line)):
            break
        pieces.append(line)
    if len(pieces) == 1:
        return pieces[0] if pieces[0].endswith('\n') else pieces[0] + '\n'
    return ' '.join(piece.strip() for piece in pieces) + ('\r\n' if pieces[-1].endswith('\r\n') else '\n')


def _parse(text):
    """Return the derivation artifact's considered line or None, naming each unclosed fence opener on stderr."""
    lines = _lines(text)
    flags = _fence_flags(lines, lambda index: _warn(
        f'derivation line {index + 1} opens a code fence that never closes; it is read as text'))
    taken = {}
    for index, (line, in_fence) in enumerate(zip(lines, flags)):
        start = _start(line, in_fence)
        if start is not None:
            taken.setdefault(in_fence, (index, start))
    for in_fence in (False, True):
        if in_fence in taken:
            return _join(lines, *taken[in_fence], extend=not in_fence)
    return None


def _neutralize(text):
    return _TRIGGER_RE.sub('\\1\u200b', text)


def build(record_path, derivation_path):
    """Assemble the record in place; return (written bytes, considered-and-rejected state), else the decided line."""
    record = _read_text(record_path, 'record')
    if record is None:
        return RECORD_UNREADABLE
    lines = _lines(record.removeprefix('\ufeff'))
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is not None and lines[first].strip() == MARKER:
        del lines[first]

    derivation = _read_text(derivation_path, 'derivation') if derivation_path else None  # '' is a planned skip.
    if derivation is None:
        considered, state = None, 'unestablished'
    else:
        considered = _parse(derivation.removeprefix('\ufeff'))
        state = 'present' if considered else 'absent'
    if considered is not None:
        lines = [line for line, in_fence in zip(lines, _fence_flags(lines)) if in_fence or _start(line, False) is None]
    prior = ''.join(lines)
    if considered is None and not prior.strip():
        return EMPTY

    if prior and not prior.endswith('\n'):
        prior += '\n'
    out = (MARKER + '\n' + _neutralize(prior + (considered or ''))).encode('utf-8')
    if len(out) > COMMENT_BYTE_LIMIT:
        _warn(f'oversize: the record is {len(out):,} bytes, over the {COMMENT_BYTE_LIMIT:,}-byte limit')
        return OVERSIZE
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
    return len(out), state


def _repo_root():
    try:
        res = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                             encoding='utf-8', check=True, stdin=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        return None
    return res.stdout.strip() or None


def _default_config_path():
    root = _repo_root()
    if root is not None:
        _warn_ancestor_config(root, 'build-investigation-record.py', 'pass --config <path>')
    elif not any(os.path.isdir(os.path.join(os.getcwd(), d)) for d in ('.prflow', '.devflow')):  # As config-get.sh.
        _warn(f'could not resolve a git repo root and no .prflow/ at {os.getcwd()}; using cwd fallback')
    return _state_config_path(root or os.getcwd())


def _coerce(value):
    """config-get.sh's coerce(): the string that resolver prints for a JSON value."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return ','.join(_coerce(v) for v in value)
    if isinstance(value, dict):
        return '[object Object]'
    return str(value)


def _telemetry_master_off(config_path):
    """scripts/telemetry-master-off.py's decision: 0 off, 1 on, 2 indeterminate (a shade of on).

    A missing sibling raises, so the record goes unposted (internal-error) rather than past `telemetry.enabled: false`.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telemetry-master-off.py')
    spec = importlib.util.spec_from_file_location('telemetry_master_off', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.telemetry_master_off(config_path)


def _warn_superseded(data, config_path):
    """config-get.sh's probe_superseded_key for the absent gate key (lib/rename-map.json: create_issue -> spec)."""
    if isinstance(data, dict) and 'create_issue' in data and (
            not isinstance(data['create_issue'], dict) or GATE_KEY[1] in data['create_issue']):
        _warn(f"'.{'.'.join(GATE_KEY)}' is absent from {config_path} but its superseded counterpart "
              f"'.create_issue.{GATE_KEY[1]}' is present; run /prflow:init to migrate the config keys")


def publication_withheld(config_path):
    """True exactly when `config-get.sh .spec.investigation_record_enabled true <config_path>` prints `false`."""
    if not os.path.isfile(config_path):
        return False
    try:
        with open(config_path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:  # config-get.sh exits 2 with empty stdout, which is not `false`.
        _warn(f'config unreadable, record published: {config_path}: {_cause(exc)}')
        return False
    value = data
    for part in GATE_KEY:
        if not isinstance(value, dict) or part not in value:
            _warn_superseded(data, config_path)
            value = None
            break
        value = value[part]
    # A command substitution strips trailing newlines, so config-get.sh never prints them.
    resolved = _coerce(value).rstrip('\n')
    if resolved:
        return resolved == 'false'
    return _telemetry_master_off(config_path) == 0


def _post(issue, record_path):
    """Post the record file as a comment on `issue`; return None on success, else the decided line."""
    gh = os.environ.get('DEVFLOW_GH') or 'gh'
    try:
        res = subprocess.run([gh, 'api', '--method', 'POST', f'repos/{{owner}}/{{repo}}/issues/{issue}/comments',
                              '-F', f'body=@{record_path}'], capture_output=True, text=True, encoding='utf-8',
                             errors='replace', stdin=subprocess.DEVNULL, env=fresh_gh_env())
    except OSError as exc:
        _warn(f'gh not runnable: {gh}: {_cause(exc)}')
        return GH_UNAVAILABLE
    if res.returncode != 0:
        _warn(f'gh api exited {res.returncode}: {" ".join(res.stderr.split()) or "(no stderr)"}')
        return POST_FAILED
    return None


def _issue_number(text):
    if not text.isascii() or not text.isdigit() or int(text) == 0:
        raise ValueError(text)
    return text


def publish(issue, record_path, derivation_path, config_path):
    if publication_withheld(config_path or _default_config_path()):
        return WITHHELD
    built = build(record_path, derivation_path)
    if isinstance(built, str):
        return built
    return _post(issue, record_path) or POSTED.format(*built)


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
    except KeyboardInterrupt:
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
        parser.add_argument('--issue', required=True, type=_issue_number)
        parser.add_argument('--record', required=True)
        parser.add_argument('--derivation', required=True)
        parser.add_argument('--config', default='')
        try:
            args = parser.parse_args(argv)
        except SystemExit:  # argparse's usage error; its message is already on stderr.
            line = USAGE
        else:
            line = publish(args.issue, args.record, args.derivation, args.config)
    except (Exception, KeyboardInterrupt) as exc:  # Still one decided line.
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

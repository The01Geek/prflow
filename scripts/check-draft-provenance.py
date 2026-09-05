#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Report whether a /prflow:create-issue draft's provenance signature is the
# body's last non-blank line. The signature is appended as the draft's last
# line before the canonical write, so a signature that landed mid-body (spliced
# into a bullet) or a duplicate is a structural defect the criteria parser and
# the verified-premise checker never read — neither reads the body's last line.
#
# One machine-readable stdout line, exit codes mirroring
# scripts/check-verified-premises.py: 0 clean, 2 defect, 3 the measurement was
# not made. The body's last line is read in Python only — never `tail` — so the
# checker behaves the same on every harness.

import argparse
import re
import sys

# Named exit codes, mirroring scripts/check-verified-premises.py so 2 (a real
# placement defect the run must act on) never reads as 3 (the file could not be
# measured) at a bare `return`.
EXIT_CLEAN = 0
EXIT_MISPLACED = 2
EXIT_UNAVAILABLE = 3

# A provenance line is what scripts/render-pr-provenance-line.py emits: an italic
# line opening `_Generated via `, a single non-space command token, an optional
# parenthesised clause, and a closing `_`. Matched against the line with trailing
# whitespace removed, so a signature carrying trailing spaces still matches.
_PROVENANCE_RE = re.compile(r'^_Generated via \S+( \([^)]*\))?_$')


class _ArgParser(argparse.ArgumentParser):
    """Fail a bad invocation as UNAVAILABLE (3), never as a placement defect (2).

    argparse exits 2 on a bad invocation, and 2 is this checker's "the signature
    is misplaced/duplicated" code — so a caller that mistypes a flag would be
    told the draft is malformed when the measurement never ran. The remap lives
    in `exit`, not only `error`, because an argument action can call
    `parser.exit(2)` without passing through `error`. Status 0 (`--help`) is a
    successful invocation, not a measurement, and is left alone.
    """

    def exit(self, status=0, message=None):
        super().exit(EXIT_UNAVAILABLE if status == EXIT_MISPLACED else status,
                     message)

    def error(self, message):
        # The machine line goes to stdout like every measured outcome — a
        # consumer scraping stdout must see this arm too; detail stays on stderr.
        print('PROVENANCE_PLACEMENT unavailable reason=bad-invocation')
        self.exit(EXIT_UNAVAILABLE,
                  f'PROVENANCE_PLACEMENT unavailable reason=bad-invocation '
                  f'detail={message}\n')


def _read_body(path):
    """Return (text, None) on success, or (None, reason-word) when unreadable.

    A missing, zero-byte, or undecodable file is a measurement that never
    happened (exit 3), distinct from a whitespace-only body that read fine and
    simply carries no signature (state=absent, exit 0).
    """
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except FileNotFoundError:
        return None, 'missing'
    except OSError:
        return None, 'unreadable'
    if not raw:
        return None, 'empty'
    try:
        return raw.decode('utf-8'), None
    except UnicodeDecodeError:
        return None, 'unreadable'


def classify(text):
    """Classify the signature placement in `text`.

    Returns (state, exit_code, line, last_nonblank). `line` and `last_nonblank`
    are 1-based line numbers, or None for the last-line/absent states that do
    not report them.
    """
    lines = text.splitlines()
    prov = [i for i, line in enumerate(lines, start=1)
            if _PROVENANCE_RE.match(line.rstrip())]
    last_nonblank = next((i for i in range(len(lines), 0, -1)
                          if lines[i - 1].strip()), None)
    if len(prov) > 1:
        return 'duplicated', EXIT_MISPLACED, prov[0], last_nonblank
    if len(prov) == 1:
        if prov[0] == last_nonblank:
            return 'last-line', EXIT_CLEAN, None, None
        return 'misplaced', EXIT_MISPLACED, prov[0], last_nonblank
    return 'absent', EXIT_CLEAN, None, None


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 so an em-dash or emoji in a body never trips a
    cp1252 codec on a non-UTF-8 host. Tolerates a stream with no usable reconfigure."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = _ArgParser(
        description="Report whether a create-issue draft's provenance line is "
                    "the body's last non-blank line.")
    parser.add_argument('--body-file', required=True,
                        help='path to the draft body to check')
    parser.add_argument('--expect-present', action='store_true',
                        help='treat an absent signature as a defect (exit 2)')
    args = parser.parse_args(argv)

    try:
        text, reason = _read_body(args.body_file)
        if reason is not None:
            print(f'PROVENANCE_PLACEMENT unavailable reason={reason}')
            return EXIT_UNAVAILABLE
        state, code, line, last_nonblank = classify(text)
        if state == 'absent' and args.expect_present:
            code = EXIT_MISPLACED
        if line is not None:
            print(f'PROVENANCE_PLACEMENT state={state} line={line} '
                  f'last_nonblank={last_nonblank}')
        else:
            print(f'PROVENANCE_PLACEMENT state={state}')
        return code
    except Exception as exc:
        # A narrower catch would let an unexpected fault exit 1 — a code neither
        # consumer routes — reading as a partial pass; every fault is unavailable.
        print(f'PROVENANCE_PLACEMENT unavailable reason=internal-error detail={exc!r}',
              file=sys.stderr)
        print('PROVENANCE_PLACEMENT unavailable reason=internal-error')
        return EXIT_UNAVAILABLE


if __name__ == '__main__':
    sys.exit(main())

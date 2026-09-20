#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Rebuild an execution transcript from a downloaded GitHub Actions job log.

Why this exists (issue #799). The engine action writes its execution file ONCE, after
its message loop ends, so a runner that dies abruptly — host-level termination rather
than a graceful cancel — leaves no execution file AND runs none of the job's own
``always()`` post-steps, so the in-job transcript channel never fires. The job log is
the one channel that survives: the runner has already uploaded every chunk written
before the death. With the engine's ``show_full_output`` input on, that log carries the
serialized message stream verbatim, so the transcript can be rebuilt off-host by a
LATER job.

Under ``show_full_output`` the engine logs each message it would have written to its
execution file, so rebuilding the array from the logged values reconstructs that file's
message record list (minus any trailing message the death truncated); the bytes need not
match. Output is one leading `#` provenance comment line followed by that array — the
channel's existing caveat-line shape, which every transcript consumer already reads through
scripts/context_eval_shared.py.

Usage: recover-transcript-from-job-log.py --log <job-log> --out <file>

BEST-EFFORT, like the transcript channel's other helpers: ALWAYS exits 0 (its caller is a
recovery step that must not be aborted) and FAILS CLOSED — it prints ``path=`` only when at
least one message was recovered and written, so the caller can gate its upload on that one
line. ``count=<n>`` is printed alongside it. Every rejected input shape gets its own counted
breadcrumb on stdout so a reader can tell "the log held nothing" apart from "the log held
something this reader refused".

Framing (an observed assumption about the engine's log format, not a guarantee): a logged
value opens at column 0 with ``{`` or ``[`` followed by what JSON allows next, and the decoder
consumes to the value's end. That excludes the other JSON-bearing lines seen so far
(``SDK options: {``) and the runner's ``[command]`` / ``[debug]`` lines; a line that passes
the framing but does not decode, with a later value after it, is counted as
``skipped-undecodable``.
"""

import argparse
import json
import os
import re
import sys

# The runner prefixes every log line with an RFC-3339 timestamp and a single space. A BOM
# leads the first line of a downloaded log. Lines the runner wrote as one multi-line record
# (a step's env dump) carry no prefix, so a non-matching line is passed through untouched
# rather than being treated as an error.
_TS = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z ")

# The message shapes the engine's SDK stream emits are open-ended (system, assistant, user,
# result, tool_progress, rate_limit_event, ...), so admission is by SHAPE — a JSON object
# carrying a string `type` — never by an enumerated vocabulary a newer engine would outgrow.


def _strip_timestamps(path):
    """The log's text with each line's runner timestamp removed, or None when unreadable.

    Reads with ``errors="replace"``: a log carrying a byte the declared encoding cannot
    represent must still yield every message around it, and a replacement character inside
    one message's text costs that message's fidelity rather than the whole transcript.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            out = []
            for line in handle:
                line = line.rstrip("\n").rstrip("\r")
                match = _TS.match(line)
                out.append(line[match.end():] if match else line)
        return "\n".join(out)
    except OSError:
        return None


def _classify(value):
    """The breadcrumb key for a decoded value this reader refuses, or None when admissible.

    The adversarial matrix for a logged JSON value, one key each: an object carrying a string
    `type` is the message shape and returns None; an object without `type` is the MISSING
    arm; an object whose `type` is not a string is the WRONG-TYPE arm; an array and a scalar
    are their own arms; and an explicit false / 0 / empty string is the VALID-FALSY arm, kept
    apart from the other scalars because it is a real value a `//`-style default would have
    silently collapsed into "absent".
    """
    if isinstance(value, dict):
        if "type" not in value:
            return "skipped-object-without-type"
        if not isinstance(value["type"], str):
            return "skipped-object-type-not-a-string"
        return None
    if isinstance(value, list):
        return "skipped-array"
    if value is False or value == 0 or value == "":
        return "skipped-valid-falsy"
    return "skipped-scalar"


def recover(text):
    """``(messages, counters)`` for one de-timestamped job log.

    ``counters`` keys are breadcrumb names; every key present has a non-zero count, so the
    caller prints exactly the arms this log actually exercised.
    """
    decoder = json.JSONDecoder()
    messages = []
    counters = {}

    def bump(key):
        counters[key] = counters.get(key, 0) + 1

    pos = 0
    end = len(text)
    while pos < end:
        newline = text.find("\n", pos)
        line_end = end if newline < 0 else newline
        line = text[pos:line_end]
        stripped = line.rstrip()
        candidate = _opens_value(stripped) or (
            # A whole-line JSON scalar is the only other shape a logged value can take. It is
            # matched as the WHOLE line so ordinary prose that merely starts with a digit
            # ("2 files changed") is never decoded as a value and never counted.
            stripped != "" and _whole_line_scalar(decoder, stripped)
        )
        if candidate:
            try:
                value, consumed = decoder.raw_decode(text, pos)
            except ValueError:
                # An unterminated value at the very end is the abrupt death itself: the log
                # stops mid-message. Report it once and stop — anything after it is that same
                # partial value's bytes, not a further message.
                if _is_truncated_tail(text, pos):
                    bump("truncated-tail")
                    break
                # A malformed value with a later value after it: counted, then skipped line
                # by line so the messages after it are still recovered.
                bump("skipped-undecodable")
                value = None
                consumed = None
            if consumed is not None:
                key = _classify(value)
                if key is None:
                    messages.append(value)
                else:
                    bump(key)
                # Resume at the line AFTER the consumed value, so a trailing comma or any
                # other text on that line cannot be re-decoded as a second value.
                after = text.find("\n", consumed)
                pos = end if after < 0 else after + 1
                continue
        pos = end if newline < 0 else newline + 1
    return messages, counters


def _whole_line_scalar(decoder, stripped):
    """True when ``stripped`` is exactly one JSON scalar and nothing else."""
    try:
        value, consumed = decoder.raw_decode(stripped, 0)
    except ValueError:
        return False
    return consumed == len(stripped) and not isinstance(value, (dict, list))


# What JSON allows right after an opening ``{`` or ``[`` (end of line included). A runner
# line such as ``[command]/usr/bin/git ...`` fails it, so it stays an ordinary non-message
# line rather than a decode failure.
_AFTER_BRACE = frozenset(' \t"}')
_AFTER_BRACKET = frozenset(' \t"{[]-0123456789tfn')


def _opens_value(stripped):
    """True when a de-timestamped, right-stripped line could open a JSON object or array."""
    head = stripped[:1]
    if head == "{":
        allowed = _AFTER_BRACE
    elif head == "[":
        allowed = _AFTER_BRACKET
    else:
        return False
    return len(stripped) == 1 or stripped[1] in allowed


def _is_truncated_tail(text, pos):
    """True when the value starting at ``pos`` is the log's last, unterminated one.

    A decode failure in the MIDDLE of a log is a malformed value to skip past, while one at
    the end is the truncation an abrupt death leaves behind. The two are told apart by whether
    any LATER line opens a fresh value: if one does, this failure is a malformed value with
    real messages after it; if none does, the log stops mid-value.
    """
    search = text.find("\n", pos)
    while search >= 0:
        nxt = search + 1
        end_of_line = text.find("\n", nxt)
        line = text[nxt:end_of_line if end_of_line >= 0 else len(text)].rstrip()
        if _opens_value(line):
            return False
        search = end_of_line
    return True


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently, from the CLI entry path only (never at
    import, so a test that imports this module does not mutate the importer's streams). The
    breadcrumbs below carry em-dashes and quote a log path that can hold any byte, either of
    which raises UnicodeEncodeError under a non-UTF-8 ambient codec. Reconfigure overrides a
    hostile PYTHONIOENCODING; the guard tolerates a non-TextIOWrapper stream."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--log", required=True, help="a downloaded job log")
    parser.add_argument("--out", required=True, help="where the rebuilt transcript is written")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on bad arguments; the contract is exit 0
        if exc.code:
            print("::warning::recover-transcript: bad arguments (--log and --out are both "
                  "required); nothing recovered (fail-closed).")
        return 0

    if not os.path.isfile(args.log):
        print(f"::notice::recover-transcript: no job log at '{args.log}'; nothing recovered.")
        return 0
    text = _strip_timestamps(args.log)
    if text is None:
        print(f"::warning::recover-transcript: job log '{args.log}' could not be read; "
              "nothing recovered (fail-closed).")
        return 0
    if text.strip() == "":
        print(f"::notice::recover-transcript: job log '{args.log}' is empty; nothing "
              "recovered.")
        return 0

    messages, counters = recover(text)
    for key in sorted(counters):
        print(f"{key}={counters[key]}")
    if not messages:
        print("::notice::recover-transcript: the job log carries no serialized engine "
              "messages; nothing recovered (the engine's show_full_output input is off, or "
              "the run died before its first message).")
        print("count=0")
        return 0
    # Provenance travels INSIDE the file, as a leading `#` comment line: every transcript
    # consumer reads the channel through scripts/context_eval_shared.py's reader, which drops
    # the leading `#` lines the scrub helper prepends, so a second one costs no consumer a
    # change and a reader can never mistake a rebuilt, possibly-partial transcript for a
    # complete one. `truncated-tail` is stated either way — its absence is a fact too.
    provenance = (
        "# PRFLOW RECOVERED TRANSCRIPT: rebuilt from the engine job log because the runner "
        "died without writing an execution file or running the job's own transcript steps "
        f"(issue #799). messages={len(messages)} "
        f"truncated-tail={counters.get('truncated-tail', 0)}. A rebuilt transcript ends "
        "where the log did, so it may stop mid-run."
    )
    try:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(provenance + "\n")
            json.dump(messages, handle, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"::warning::recover-transcript: could not write '{args.out}' ({exc}); NOT "
              "advertising a path (fail-closed).")
        return 0
    print(f"count={len(messages)}")
    print(f"path={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

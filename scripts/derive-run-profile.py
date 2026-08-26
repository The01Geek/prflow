#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Derive an implement run's phase durations and final status from its workpad body.

Reads a rendered PRFlow workpad comment body and emits

    {"phase_durations_ms": {<phase>: <int|"unestablished">, ...} | "unestablished",
     "final_status": <word> | "unestablished"}

`scripts/prepare-run-profile.sh` feeds this parser the body that `scripts/workpad.py
id` / `body` fetched, and hands the result to `lib/efficiency-trace.sh --persist` as
`DEVFLOW_RUN_PROFILE`.

The workpad is human- and agent-mutable markdown, so every shape below is answered
rather than assumed: an absent or duplicated `## Progress` section, an absent
`**Last updated:**` or `**Status:**` line, a non-string body, an unparseable
`HH:MM:SS` stamp, and an unrecognized phase heading. An operand that could not be
established is reported as the string `unestablished` and never as `0` — a duration
of zero is a real measurement (a phase with one timestamped note), and collapsing an
unknown onto it would let an unmeasured run enter a mean as a real value.

Progress note bullets carry the time of day only (`scripts/workpad.py` renders them
`  - HH:MM:SS — <note>`), so the dated `**Last updated:**` line is the sole day
source. A stamp that reads earlier than its predecessor is taken as the next day,
which is what keeps a run spanning midnight from producing a negative span.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED


def _load_workpad():
    """`scripts/workpad.py` as a module, loaded by explicit path under a private name.

    A plain `import workpad` would bind whatever `workpad` module the caller's sys.path
    resolves first; this file is imported by tests that already load several modules under
    their own names, so the explicit path is what keeps the binding unambiguous."""
    spec = importlib.util.spec_from_file_location(
        "_drp_workpad", Path(__file__).resolve().parent / "workpad.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The top-level workpad phase rows, IMPORTED from their owner rather than transcribed.
# A hand-copied tuple would silently drop a renamed phase's span with nothing going red,
# because a heading outside this set contributes no duration.
_workpad = _load_workpad()
PROGRESS_PHASES = _workpad._PROGRESS_PHASES
_strip_status_glyph = _workpad._strip_status_glyph

_SECTION_RE = re.compile(r"^##\s+Progress\s*$", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
_LAST_UPDATED_RE = re.compile(
    r"^\*\*Last updated:\*\*\s+(\d{4})-(\d{2})-(\d{2})\s", re.MULTILINE
)
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s+(.*?)\s*$", re.MULTILINE)
# Accepts the same row shapes workpad.py's own `_TOP_LEVEL_CHECKBOX_RE` does — a `*`
# bullet and a capital-X tick included. A narrower pattern silently discards every
# timestamped note under a row it fails to match rather than reporting unestablished.
_TOP_LEVEL_RE = re.compile(r"^[-*]\s+\[[ xX]\]\s+\*\*(?P<phase>[^*]+)\*\*")
_NOTE_TS_RE = re.compile(r"^\s+-\s+(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\s+—")


def _progress_block(body: str):
    """The `## Progress` section's lines, or None when the section is absent or
    duplicated. A duplicated section has no single answer, so picking one would
    report a span the workpad does not actually carry."""
    starts = list(_SECTION_RE.finditer(body))
    if len(starts) != 1:
        return None
    start = starts[0].end()
    nxt = _NEXT_SECTION_RE.search(body, start)
    return body[start: nxt.start() if nxt else len(body)].splitlines()


def _base_date(body: str):
    m = _LAST_UPDATED_RE.search(body)
    if m is None:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _final_status(body: str):
    m = _STATUS_RE.search(body)
    if m is None:
        return UNESTABLISHED
    # Strip the glyph through workpad.py's own stripper, not a local heuristic: a
    # `.split()[-1]` would reduce a multi-word status to its last word.
    word = _strip_status_glyph(m.group(1)).strip()
    return word or UNESTABLISHED


def _phase_stamps(lines):
    """Ordered `HH:MM:SS` triples per recognized phase heading."""
    stamps: dict[str, list[tuple[int, int, int]]] = {}
    current = None
    for line in lines:
        top = _TOP_LEVEL_RE.match(line)
        if top:
            phase = top.group("phase").strip()
            current = phase if phase in PROGRESS_PHASES else None
            if current is not None:
                stamps.setdefault(current, [])
            continue
        if current is None:
            continue
        note = _NOTE_TS_RE.match(line)
        if note is None:
            continue
        h, m, s = int(note.group("h")), int(note.group("m")), int(note.group("s"))
        if h > 23 or m > 59 or s > 59:
            continue
        stamps[current].append((h, m, s))
    return stamps


def _span_ms(triples, base_date):
    """Milliseconds from the first to the last stamp, rolling the date forward at
    each backwards step so a run spanning midnight never yields a negative span."""
    if not triples:
        return UNESTABLISHED
    day = base_date
    previous = None
    moments = []
    for h, m, s in triples:
        if previous is not None and (h, m, s) < previous:
            day = day + dt.timedelta(days=1)
        moments.append(dt.datetime.combine(day, dt.time(h, m, s), tzinfo=dt.timezone.utc))
        previous = (h, m, s)
    return int((moments[-1] - moments[0]).total_seconds() * 1000)


def derive(body):
    """The run profile for one workpad body. Never raises on a malformed body."""
    if not isinstance(body, str) or not body.strip():
        return {"phase_durations_ms": UNESTABLISHED, "final_status": UNESTABLISHED}
    status = _final_status(body)
    lines = _progress_block(body)
    if lines is None:
        return {"phase_durations_ms": UNESTABLISHED, "final_status": status}
    # Without a day the stamps cannot be ordered across a midnight boundary, so no span
    # is established — reporting one would be a guess presented as a fact.
    base_date = _base_date(body)
    stamps = _phase_stamps(lines)
    if not stamps:
        # The section parsed but held no recognized phase heading. That is a workpad this
        # parser could not read, not a run with no phases — an empty map would report it
        # as an established measurement of nothing.
        return {"phase_durations_ms": UNESTABLISHED, "final_status": status}
    # Seed from the full phase vocabulary, not from what matched: a phase the parser never
    # saw is otherwise absent from the map entirely, so a consumer counting established
    # entries against the map's own length reads a one-phase measurement as complete.
    durations = {phase: UNESTABLISHED for phase in PROGRESS_PHASES}
    for phase, triples in stamps.items():
        durations[phase] = _span_ms(triples, base_date) if base_date else UNESTABLISHED
    return {"phase_durations_ms": durations, "final_status": status}


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--body-file", required=True,
                        help="path to a rendered workpad comment body")
    args = parser.parse_args(argv)
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"devflow: derive-run-profile: cannot read {args.body_file}: {exc}",
              file=sys.stderr)
        return 1
    except UnicodeDecodeError as exc:
        print(f"devflow: derive-run-profile: {args.body_file} is not UTF-8: {exc}",
              file=sys.stderr)
        return 1
    json.dump(derive(body), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

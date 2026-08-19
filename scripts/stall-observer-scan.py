#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""stall-observer-scan.py — decision core for the out-of-band stall OBSERVER (issue #1027).

The in-job stall backstop (scripts/stall-backstop-decide.sh) runs only AFTER the
agent step returns, so it cannot observe a run that is still going. This observer
is the out-of-band half: a scheduled workflow reads each open issue's workpad and
asks this helper whether the run has been silent past an ADVISORY staleness
threshold. It REPORTS ("silent for N minutes; last checkpoint X"); it never kills
a run and never re-dispatches one, so its decision vocabulary carries no
kill/resume/fail token and it can never race the backstop's `resume` arm.

The measurement over the runs available when this was written found no wall-clock
threshold that cleanly separates a stall from legitimate work (a healthy run ran
119 min; a 69-min inter-checkpoint gap occurred on healthy runs too), so the
threshold is advisory-only and configurable, and its default is deliberately
conservative and provisional pending a larger sample.

Pure/deterministic given inputs: `decide` takes an explicit `now`, so every branch
is drivable from a fixture with no clock or network dependency (the reason the
decision core is extracted from the workflow YAML, mirroring stall-backstop-decide.sh).
"""

import argparse
import json
import re
import sys
from collections import namedtuple
from datetime import datetime, timezone

# The Status line the workpad writes is `**Status:** <glyph> <word>`; classify from
# the glyph first (scripts/workpad.py is the source of this vocabulary), falling back
# to the word so an un-glyphed or future spelling still classifies.
_GLYPH_CLASS = {
    "\U0001F680": "interim",   # 🚀 any in-progress phase
    "\U0001F389": "complete",  # 🎉 Complete
    "\U0001F44E": "blocked",   # 👎 Blocked
    "\U0001F4A5": "failed",    # 💥 Failed
    "\U0001F6D1": "cancelled",  # 🛑 Cancelled
}
_WORD_CLASS = {
    "setup": "interim", "discovering": "interim", "reproducing": "interim",
    "planning": "interim", "implementing": "interim", "reviewing": "interim",
    "documenting": "interim",
    "complete": "complete", "blocked": "blocked", "failed": "failed",
    "cancelled": "cancelled",
}

_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s+(.+?)\s*$", re.MULTILINE)
_LAST_UPDATED_RE = re.compile(r"^\*\*Last updated:\*\*\s+(.+?)\s*$", re.MULTILINE)
_CHECKPOINT_RE = re.compile(r"<!--\s*prflow:checkpoint\s+(\S+)\s*-->")

# The report-only decision vocabulary. Deliberately disjoint from the backstop's
# kill/resume/fail tokens — the observer never mutates a run.
DECISION_TOKENS = frozenset({"disabled", "not-candidate", "unreadable", "fresh", "stale-advisory"})

WorkpadFacts = namedtuple("WorkpadFacts", "status_word status_class last_updated last_checkpoint")
Decision = namedtuple("Decision", "token minutes message")


def _classify_status(status_line_value):
    if not status_line_value:
        return "", "unknown"
    parts = status_line_value.split()
    glyph = parts[0]
    word = parts[1] if len(parts) > 1 else parts[0]
    cls = _GLYPH_CLASS.get(glyph)
    if cls is None:
        cls = _WORD_CLASS.get(word.lower(), "unknown")
    return word, cls


def parse_dt(text):
    """Best-effort parse of a workpad timestamp. Accepts the workpad's own
    `%Y-%m-%d %H:%M UTC` spelling and ISO 8601; returns an aware UTC datetime or None."""
    if not text:
        return None
    text = text.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_workpad(body):
    """Extract the facts the observer decides on from a workpad comment body.
    Every field degrades to a None/`unknown` sentinel on a missing or malformed
    input rather than raising — the caller distinguishes those via `decide`."""
    body = body or ""
    m = _STATUS_RE.search(body)
    status_word, status_class = _classify_status(m.group(1) if m else "")
    lu = _LAST_UPDATED_RE.search(body)
    last_updated = parse_dt(lu.group(1)) if lu else None
    checkpoints = _CHECKPOINT_RE.findall(body)
    last_checkpoint = checkpoints[-1] if checkpoints else None
    return WorkpadFacts(status_word, status_class, last_updated, last_checkpoint)


def _enabled(value):
    # Mirror stall-backstop-decide.sh: only the exact string "false" disables;
    # every other value (empty, "true", unrecognized) resolves to enabled.
    return value != "false"


def decide(facts, now, threshold_minutes, enabled):
    """Map workpad facts + a reference `now` to one advisory token. Reports only —
    never returns a kill/resume/fail decision."""
    if not _enabled(enabled):
        return Decision("disabled", None, "stall observer disabled by config")
    cls = facts.status_class
    if cls == "unknown":
        return Decision("unreadable", None, "workpad Status could not be classified")
    if cls in ("complete", "blocked", "failed", "cancelled"):
        return Decision("not-candidate", None, f"workpad Status is a terminal end ({cls}); not an in-flight run")
    # cls == "interim": an in-flight run — the only stall candidate.
    if facts.last_updated is None:
        return Decision("unreadable", None, "workpad **Last updated:** line missing or unparseable")
    minutes = int((now - facts.last_updated).total_seconds() // 60)
    if minutes < 0:
        minutes = 0  # clock skew: never report negative silence
    if minutes < threshold_minutes:
        return Decision("fresh", minutes, f"silent for {minutes} min (< advisory threshold {threshold_minutes} min)")
    cp = f"; last checkpoint: {facts.last_checkpoint}" if facts.last_checkpoint else ""
    return Decision("stale-advisory", minutes,
                    f"silent for {minutes} min (>= advisory threshold {threshold_minutes} min){cp}")


def _cmd_decide(args):
    try:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as exc:
        print(f"stall-observer-scan: cannot read --body-file {args.body_file!r}: {exc}", file=sys.stderr)
        return 2
    now = parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"stall-observer-scan: --now {args.now!r} is not a parseable timestamp", file=sys.stderr)
        return 2
    facts = parse_workpad(body)
    d = decide(facts, now, args.threshold, args.enabled)
    if args.format == "json":
        print(json.dumps({
            "decision": d.token,
            "minutes": d.minutes,
            "message": d.message,
            "status_class": facts.status_class,
            "last_checkpoint": facts.last_checkpoint,
        }))
    else:
        print(d.token)
        if d.message:
            print(d.message)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Out-of-band stall observer decision core (reports, never kills).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide", help="decide one issue's advisory stall token from its workpad body")
    d.add_argument("--body-file", required=True, help="path to a file holding the workpad comment body")
    d.add_argument("--now", default=None, help="reference time (YYYY-MM-DD HH:MM UTC or ISO 8601); default = now")
    d.add_argument("--threshold", type=int, required=True, help="advisory staleness threshold in minutes")
    d.add_argument("--enabled", default="true", help="config enabled value; only the exact string 'false' disables")
    d.add_argument("--format", choices=("token", "json"), default="token")
    d.set_defaults(func=_cmd_decide)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Independent-channel prompt-extension / skill-body arrival detector (issue #1446).

A cloud run can lose an entire skill body — or the consumer prompt extension
appended to one — and still terminate ``Complete``: the ``Skill``-tool load aborts
carrying only a refusal string and no body, and that failure does not increment
``permission_denials_count``. This helper is the job-level surface's engine: it reads
the extension root *directly* — independently of the ``load-prompt-extension.sh``
delivery channel under test — and reconciles that independent expectation against the
run's own durable artifacts, so a lost load is observable and does not report clean.

It is deliberately pure (no network, no ``gh``): the workflow fetches the durable body
and pipes it in, so every input shape is unit-drivable at this boundary — the only
boundary an in-repo test can reach, since the suite has no cloud runner.

Two subcommands:

* ``classify`` — the independent read. It resolves the SAME extension root the
  ``load-prompt-extension.sh`` ladder resolves (``DEVFLOW_PROMPT_EXTENSION_ROOT`` when
  set and non-empty, else ``<git-root>/.prflow/prompt-extensions``), stats/reads the
  ``<skill>.md`` file directly, and emits the expected delivery state plus the resolved
  root. Deliverable content present → ``arrived-expected``; no file or an empty file →
  ``absent`` (a legal consumer state); a present-but-undeliverable file (unreadable,
  broken symlink, non-regular) → a specific ``undeliverable-*`` fault token, exit 3.

* ``reconcile`` — the post-agent reconciliation. Given the ``classify`` token, an
  ``--arrival-marker`` (the durable-artifact substring a genuine arrival records — for
  the implement tier the ticked ``prompt extension resolved: implement`` workpad row),
  and the durable body on stdin, it derives the final ``arrived`` / ``absent`` /
  ``unestablished`` state and the terminal action. ``arrived-expected`` with a ticked
  marker row is ``arrived``; ``arrived-expected`` with no positive arrival record (or a
  ``state not established`` note) is ``unestablished`` — the class facts (a)/(b) name,
  and the one a lost skill body produces, because a lost body can tick no row. An
  ``undeliverable-*`` fault is ``unestablished``; ``absent`` stays ``absent``. On
  ``unestablished`` it emits the forced durable-record text the caller writes to the
  workpad / PR description. It is idempotent: reading a body that already carries the
  non-arrival note still yields ``unestablished`` and the same record.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# The three delivery states the job-level surface establishes (AC1), plus the
# per-fault classify tokens that each map to `unestablished` at reconcile time.
STATE_ARRIVED_EXPECTED = "arrived-expected"
STATE_ABSENT = "absent"
FAULT_UNREADABLE = "undeliverable-unreadable"
FAULT_BROKEN_SYMLINK = "undeliverable-broken-symlink"
FAULT_NONREGULAR = "undeliverable-nonregular"
_FAULT_TOKENS = frozenset({FAULT_UNREADABLE, FAULT_BROKEN_SYMLINK, FAULT_NONREGULAR})
_CLASSIFY_TOKENS = frozenset({STATE_ARRIVED_EXPECTED, STATE_ABSENT}) | _FAULT_TOKENS

FINAL_ARRIVED = "arrived"
FINAL_ABSENT = "absent"
FINAL_UNESTABLISHED = "unestablished"

# Exit codes: 0 = clean state (arrived/absent), 2 = bad arguments, 3 = a loud fault
# (classify) or a `block` terminal (reconcile). A fault and a block both mean the run
# must not report `Complete`, so they share the loud exit rather than a silent 0.
EXIT_OK = 0
EXIT_BADARGS = 2
EXIT_FAULT = 3


def _validate_skill(name: str) -> None:
    """Reject the same skill names ``load-prompt-extension.sh`` rejects, before any
    filesystem access, so the composed path can never escape the selected root."""
    if not name:
        sys.stderr.write("prompt-extension-arrival.py: skill name is empty\n")
        sys.exit(EXIT_BADARGS)
    if "/" in name or ".." in name:
        sys.stderr.write(
            f"prompt-extension-arrival.py: invalid skill name '{name}' "
            "(must not contain '/' or '..')\n"
        )
        sys.exit(EXIT_BADARGS)


def _git_root() -> str:
    """The repo root the fallback branch anchors on, mirroring
    ``load-prompt-extension.sh``: ``git rev-parse --show-toplevel``, else the cwd."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        root = out.stdout.strip()
        if out.returncode == 0 and root:
            return root
    except OSError:
        pass
    return os.getcwd()


def _resolve_ext_dir(root_arg: str | None) -> str:
    """Resolve the extension DIRECTORY exactly as ``load-prompt-extension.sh`` does, so
    the detector and the delivery channel read the same root (AC8).

    Precedence, honoring the DEVFLOW_* convention (honored when set and non-empty):
    an explicit ``--root``, else ``DEVFLOW_PROMPT_EXTENSION_ROOT``. Either names the
    directory OUTRIGHT — no ``.prflow/prompt-extensions/`` segment is appended. Only the
    fallback (git-root) branch appends that segment.
    """
    if root_arg:
        return root_arg
    env_root = os.environ.get("DEVFLOW_PROMPT_EXTENSION_ROOT", "")
    if env_root:
        return env_root
    return os.path.join(_git_root(), ".prflow", "prompt-extensions")


def _classify_state(ext_file: str) -> str:
    """Classify the file's delivery state by a direct stat/read — never via the ladder.

    Order matters: a broken symlink and a non-regular entry both make ``isfile`` false,
    so they must be distinguished before the ``isfile`` arm, else each would masquerade
    as ``absent`` — the exact silent-drop class this detector exists to close.
    """
    if os.path.islink(ext_file) and not os.path.exists(ext_file):
        return FAULT_BROKEN_SYMLINK
    if os.path.exists(ext_file) and not os.path.isfile(ext_file):
        return FAULT_NONREGULAR
    if os.path.isfile(ext_file):
        if not os.access(ext_file, os.R_OK):
            return FAULT_UNREADABLE
        # A present regular file with zero bytes is a legal opt-out — `absent`, not a
        # fault — matching the ladder's `-s` no-op arm.
        if os.path.getsize(ext_file) > 0:
            return STATE_ARRIVED_EXPECTED
        return STATE_ABSENT
    return STATE_ABSENT


def cmd_classify(args: argparse.Namespace) -> int:
    _validate_skill(args.skill)
    ext_dir = _resolve_ext_dir(args.root)
    ext_file = os.path.join(ext_dir, f"{args.skill}.md")
    state = _classify_state(ext_file)
    # Record the resolved root on stdout so the run can state which root it read (AC8).
    sys.stdout.write(
        f"state={state} root={ext_dir} skill={args.skill} file={ext_file}\n"
    )
    return EXIT_FAULT if state in _FAULT_TOKENS else EXIT_OK


def _scan_arrival(body: str, marker: str) -> str:
    """One pass over the durable body, returning the strongest signal for the marker:

    * ``positive`` — a TICKED checkbox row carrying the marker, the durable evidence the
      loaded body was contractually required to produce (AC6/AC7);
    * ``state-not-established`` — a line carrying the marker AND the ``state not
      established`` sentinel (an explicitly non-positive self-report);
    * ``none`` — no marker line, or an unticked one.

    ``positive`` wins over ``state-not-established`` if both appear.
    """
    saw_state_not_established = False
    for line in body.splitlines():
        if marker not in line:
            continue
        if "state not established" in line:
            saw_state_not_established = True
            continue
        if "[x]" in line or "[X]" in line:
            return "positive"
    return "state-not-established" if saw_state_not_established else "none"


def _reconcile_record(skill: str, cause: str) -> str:
    """The forced durable-record text a caller writes to the workpad / PR description
    when the state is `unestablished` (AC5). One line so it survives as a `--note`."""
    return (
        f"prompt-extension arrival unestablished: the '{skill}' extension "
        f"({cause}) — the skill body or consumer prompt extension may not have reached "
        "the agent; this run must not report a clean policy-applied terminal"
    )


def cmd_reconcile(args: argparse.Namespace) -> int:
    expected = args.expected
    if expected not in _CLASSIFY_TOKENS:
        sys.stderr.write(
            f"prompt-extension-arrival.py: unknown --expected token '{expected}'\n"
        )
        return EXIT_BADARGS

    skill = args.skill or "(unnamed)"
    if expected in _FAULT_TOKENS:
        final = FINAL_UNESTABLISHED
        cause = f"present-but-undeliverable extension file: {expected}"
    elif expected == STATE_ABSENT:
        final = FINAL_ABSENT
        cause = "no deliverable extension content (absent or empty file)"
    else:  # arrived-expected
        cause = "deliverable content was present at the resolved root"
        if args.durable_source == "none":
            # The run halted before any durable surface existed, so no positive
            # arrival record can exist — unestablished (AC2/AC5 workpad-less arm).
            final = FINAL_UNESTABLISHED
            cause = "deliverable content was present but the run wrote no durable artifact to record its arrival"
        else:
            body = sys.stdin.read()
            signal = _scan_arrival(body, args.arrival_marker)
            if signal == "positive":
                final = FINAL_ARRIVED
            elif signal == "state-not-established":
                final = FINAL_UNESTABLISHED
                cause = "the run recorded 'state not established' for its arrival"
            else:
                final = FINAL_UNESTABLISHED
                cause = "no positive arrival record was found in the durable artifact"

    terminal = "complete-ok" if final in (FINAL_ARRIVED, FINAL_ABSENT) else "block"
    sys.stdout.write(f"final={final} terminal={terminal}\n")
    if final == FINAL_UNESTABLISHED:
        sys.stdout.write(f"record={_reconcile_record(skill, cause)}\n")
        return EXIT_FAULT
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prompt-extension-arrival.py",
        description="Independent-channel prompt-extension / skill-body arrival detector.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser(
        "classify",
        help="Read the extension root directly and emit the expected delivery state + resolved root.",
    )
    p_classify.add_argument("--skill", required=True, help="Skill/extension name (e.g. implement).")
    p_classify.add_argument(
        "--root",
        default=None,
        help="Override the extension directory outright (as DEVFLOW_PROMPT_EXTENSION_ROOT does).",
    )
    p_classify.set_defaults(func=cmd_classify)

    p_reconcile = sub.add_parser(
        "reconcile",
        help="Reconcile a classify token against the durable body (stdin) into a final state + terminal.",
    )
    p_reconcile.add_argument("--expected", required=True, help="The classify state token.")
    p_reconcile.add_argument(
        "--arrival-marker",
        default="",
        help="Durable-artifact substring a genuine arrival records (e.g. 'extension resolved: implement').",
    )
    p_reconcile.add_argument(
        "--durable-source",
        choices=["workpad", "pr", "none"],
        default="workpad",
        help="Where the durable body on stdin came from; 'none' means the run wrote no durable artifact.",
    )
    p_reconcile.add_argument("--skill", default=None, help="Skill/extension name, for the record text.")
    p_reconcile.set_defaults(func=cmd_reconcile)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

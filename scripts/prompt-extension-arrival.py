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

Three subcommands:

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

* ``classify-ladder-output`` — the local/interactive & cloud-review prose-side classifier
  (issue #1971). Those tiers have no job-level step to run ``classify`` in, so they read
  ``load-prompt-extension.sh``'s OWN emitted ``PROMPT-EXTENSION-STATUS:`` line (on stdin)
  instead of statting the root. It is positive-signal only: ``arrived`` ONLY on a produced
  ``content-present`` status, ``absent`` ONLY on a produced ``present-empty`` status, and
  ``unestablished`` whenever no recognized status line was produced at all — which is what
  a permission denial of a helper invoked by path looks like (no output). It emits the same
  ``final=/terminal=/record=`` shape ``reconcile`` does, so a caller routes on one contract.
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

# The delivery ladder's own emitted status line (load-prompt-extension.sh), which the
# local/interactive & cloud-review prose-side classifier reads instead of statting the
# root — the tier has no job-level step to run `classify` in. Only these two status
# tokens are ones the ladder produces; anything else (including no line at all) is not a
# positive signal (AC1/AC2).
LADDER_STATUS_PREFIX = "PROMPT-EXTENSION-STATUS:"
LADDER_STATUS_CONTENT_PRESENT = "content-present"
LADDER_STATUS_PRESENT_EMPTY = "present-empty"

# Exit codes: 0 = clean state (arrived/absent), 2 = bad arguments, 3 = a loud fault
# (classify) or a `block` terminal (reconcile). A fault and a block both mean the run
# must not report `Complete`, so they share the loud exit rather than a silent 0.
EXIT_OK = 0
EXIT_BADARGS = 2
EXIT_FAULT = 3


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import), so a
    non-UTF-8 ambient codec cannot make a non-ASCII byte in a record/path raise
    UnicodeEncodeError. Tolerates a non-TextIOWrapper stream (a test's io.StringIO)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


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
    """The repo root the fallback branch anchors on, like
    ``load-prompt-extension.sh``'s fallback: ``git rev-parse --show-toplevel``, else the
    cwd. (The ladder additionally reads a superseded ``.devflow/`` when no ``.prflow/``
    exists; this detector composes the canonical ``.prflow/`` root only — inert on any
    tree that carries ``.prflow/``, including the cloud implement tier.)"""
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
    """Resolve the extension DIRECTORY the way ``load-prompt-extension.sh`` does, so the
    detector and the delivery channel read the same root (AC8) — see ``_git_root`` for
    the one canonical-vs-transitional caveat on the git-root fallback.

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


def _scan_ladder_status(output: str) -> str:
    """Positive-signal classify of the delivery ladder's own emitted status output (AC1/AC2).

    The local/interactive tier and the read-only cloud-review tier have no job-level step
    to run ``classify`` in, so they read ``load-prompt-extension.sh``'s own
    ``PROMPT-EXTENSION-STATUS:`` line from the captured invocation output instead. The rule
    is positive-signal only: ``arrived`` ONLY on a produced ``content-present`` status,
    ``absent`` ONLY on a produced ``present-empty`` status, and ``unestablished`` whenever
    no recognized status line was produced at all — which is exactly what a permission
    denial of a helper invoked by path looks like (no output), byte-identical to a silent
    non-delivery. Declaring ``arrived`` by absence of evidence is the false-``Complete``
    semantics this mode must never reinstate.

    ``content-present`` wins over ``present-empty`` if both appear; an unrecognized token
    after the prefix is not a status the ladder produces, so it does not signal arrival.
    """
    saw_present_empty = False
    for line in output.splitlines():
        idx = line.find(LADDER_STATUS_PREFIX)
        if idx == -1:
            continue
        rest = line[idx + len(LADDER_STATUS_PREFIX):].split()
        token = rest[0] if rest else ""
        if token == LADDER_STATUS_CONTENT_PRESENT:
            return FINAL_ARRIVED
        if token == LADDER_STATUS_PRESENT_EMPTY:
            saw_present_empty = True
    return FINAL_ABSENT if saw_present_empty else FINAL_UNESTABLISHED


def _emit_final(skill: str, final: str, cause: str) -> int:
    """Emit the shared ``final=/terminal=/record=`` contract and return its exit code.

    Both ``reconcile`` and ``classify-ladder-output`` end here, so the terminal
    vocabulary and the block-vs-clean exit selection cannot drift between them. ``cause``
    is read only on the ``unestablished`` arm.
    """
    terminal = "complete-ok" if final in (FINAL_ARRIVED, FINAL_ABSENT) else "block"
    sys.stdout.write(f"final={final} terminal={terminal}\n")
    if final == FINAL_UNESTABLISHED:
        sys.stdout.write(f"record={_reconcile_record(skill, cause)}\n")
        return EXIT_FAULT
    return EXIT_OK


def cmd_classify_ladder(args: argparse.Namespace) -> int:
    """Classify from the ladder's emitted status output (stdin) for the workpad-less,
    prose-side tiers — the same ``final=/terminal=/record=`` output shape ``reconcile``
    emits, so a caller routes on one contract regardless of which classifier ran."""
    skill = args.skill or "(unnamed)"
    final = _scan_ladder_status(sys.stdin.read())
    cause = (
        "the delivery ladder produced no PROMPT-EXTENSION-STATUS line — a denied or "
        "silent invocation, so arrival could not be established"
    )
    return _emit_final(skill, final, cause)


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
            # An empty marker would match every line (``marker not in line`` never true),
            # so any ticked row would read as a positive arrival — a fail-open. Require it.
            if not args.arrival_marker:
                sys.stderr.write(
                    "prompt-extension-arrival.py: --arrival-marker is required to scan a "
                    "durable body (an empty marker would match every row)\n"
                )
                return EXIT_BADARGS
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

    return _emit_final(skill, final, cause)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
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

    p_ladder = sub.add_parser(
        "classify-ladder-output",
        help="Classify from the delivery ladder's emitted status output (stdin) for the "
        "workpad-less, prose-side tiers — arrived/absent/unestablished by positive signal.",
    )
    p_ladder.add_argument("--skill", default=None, help="Skill/extension name, for the record text.")
    p_ladder.set_defaults(func=cmd_classify_ladder)

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

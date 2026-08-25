# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""schedulewakeup-probe-verdict.py — derive the ScheduleWakeup `--disallowedTools`
probe verdict from a `claude-code-action` execution file (issue #415).

Why a helper rather than inline Python in matcher-probe.yml: this verdict is a
branch-selecting core (a four-way DENIED/AVAILABLE/REMOVED/INCONCLUSIVE selection
plus a ship/no-ship decision and an "Unknown is not zero" INCONCLUSIVE floor) that
gates a real `claude_args` change. Inline-in-YAML it cannot be unit-tested, so a
regressed arm — the `note_top`-precedence INCONCLUSIVE floor, the REMOVED
single-control fall-through, or the name match — would silently misfire while the
workflow still "runs". Extracting it lets lib/test/run.sh drive every arm and the
adversarial fail-open matrix directly (issue #415 review, finding #1; same rationale
as scripts/describe-denial-count.sh, PR #367). The sibling per-shape probe verdict in
the same workflow remains inline pending its own extraction (out of #415 scope).

A ship verdict (DENIED/REMOVED) requires POSITIVE execution-file evidence — a
`permission_denials` record naming ScheduleWakeup — never presumptive absence (issue
#1527). Deterministic four-way verdict, execution-file only (the model's text is never
read):

  DENIED       permission_denials names ScheduleWakeup AND a ScheduleWakeup tool_use
               was recorded (present, refused). Since ScheduleWakeup is GRANTED in
               --allowed-tools, only --disallowedTools can deny it -> attributable to
               the flag under test. Ships.
  AVAILABLE    a ScheduleWakeup tool_use was recorded and NOT denied (the flag did
               NOT remove the tool in this environment).
  REMOVED      a ScheduleWakeup denial was recorded with NO registered tool_use
               attempt — positive evidence the flag removed the tool from context,
               distinct from a model that simply never attempted the call (which
               records no denial). Presumptive, not proven: the harness may record a
               denial without a tool_use node. Ships.
  INCONCLUSIVE nothing was measured (note_top), OR no positive ScheduleWakeup signal
               at all (no denial, no attempt). Ships nothing: presumptive absence is
               never collapsed onto the shippable REMOVED — both controls running is
               not evidence of removal, only that the model progressed (issue #1527;
               CLAUDE.md: "Unknown is not zero").

Fail-open hardening (issue #415 review, finding #2; tightened for issue #1527): the
ScheduleWakeup attempt match is case-INSENSITIVE and keyed on the recorded tool_use
NAME, never the `input` JSON — so a `ToolSearch` query naming ScheduleWakeup is NOT a
false attempt. The denial match is likewise keyed on the `permission_denials` entry's
tool-name field, so the token nested in a denial's input never falsely gates a SHIP
verdict; an unrecognized denial shape yields no name and fails safe (no ship). A tool_use
node is recorded even when it carries no `input` key, so a
tool recorded under a lower-cased / decorated / input-less NAME still reads as present
(-> AVAILABLE, do NOT ship) rather than absent — the fail-open in the dangerous
direction. Raw tool_use names are dumped in the table so an operator can confirm the
harness's actual ScheduleWakeup name on the first live run.

Usage: schedulewakeup-probe-verdict.py [EXECUTION_FILE]
  EXECUTION_FILE  path to the action's execution file; if omitted, read from the
                  EXECUTION_FILE env var. Empty/absent -> INCONCLUSIVE.
Prints the markdown verdict table to stdout (and appends it to GITHUB_STEP_SUMMARY
when set). Always exits 0.
"""

import json
import os
import sys


def parse_execution_file(exec_file):
    """Return (parsed, note_top). parsed is a JSON value or None; note_top is a
    non-empty diagnostic when the file was absent/empty/unparseable/partially
    corrupt (which forces INCONCLUSIVE)."""
    if not (exec_file and os.path.isfile(exec_file)):
        # Fires when the path arg is empty/unset (absent) OR is not a regular file
        # (missing, a directory, a special file). A present-but-empty regular file is
        # NOT this branch — isfile() is true, so it flows to the read/parse path and
        # surfaces "present but unparseable" instead; keep this wording accurate to the
        # branch that emits it (PR #417 review — silent-failure-hunter).
        return None, "execution file path absent or not a regular file at '%s'" % exec_file
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        # Present-but-unreadable (PermissionError/OSError), or a TOCTOU disappearance
        # after the os.path.isfile() check above (FileNotFoundError): route to the
        # note_top -> INCONCLUSIVE floor instead of raising an uncaught traceback
        # through render()/main(), honoring this module's "Always exits 0" contract
        # (issue #415, PR #417 review finding). Unknown is not zero — a degraded read
        # is never collapsed onto the shippable REMOVED.
        return [], "execution file present but unreadable (%s)" % e.__class__.__name__
    try:
        return json.loads(raw), ""
    except Exception:
        pass
    # Not a single JSON document — try JSONL, counting unparseable lines. A PARTIAL
    # corruption (some lines parse but the ScheduleWakeup record does not) would
    # otherwise read as a clean tool-absence, so any drop forces INCONCLUSIVE.
    parsed = []
    dropped = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            parsed.append(json.loads(s))
        except Exception:
            dropped += 1
    if not parsed:
        return [], "execution file present but unparseable"
    if dropped:
        return parsed, (
            "%d execution-file line(s) were unparseable — verdict may be incomplete"
            % dropped
        )
    return parsed, ""


def collect(parsed):
    """Walk the parsed structure and return (denials, tool_uses, tool_use_names,
    denial_names) as text lists. tool_use_names is the recorded `name` of each tool_use
    and denial_names the tool-name field of the recorded `permission_denials` entries,
    collected separately so the attempt and denial predicates key on the name (issue #1527)
    rather than substring-matching the serialized input/record.

    A tool_use node is recorded even when it carries no `input` key, so an
    input-less ScheduleWakeup call is not silently dropped (issue #415 finding #2)."""
    denials = []
    tool_uses = []
    tool_use_names = []
    denial_names = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "tool_use":
                name = str(o.get("name", ""))
                tool_uses.append(json.dumps(o.get("input")) + " NAME=" + name)
                tool_use_names.append(name)
            pd = o.get("permission_denials")
            if isinstance(pd, list):
                for d in pd:
                    denials.append(json.dumps(d))
                    # Record the denied tool's NAME field only, so the denial predicate
                    # (which gates SHIP) keys on the name and not on the token appearing
                    # anywhere in the serialized record (issue #1527) — the same
                    # false-positive vector the attempt predicate closes. A non-dict or
                    # name-field-less entry yields no name and fails safe (no ship).
                    denial_names.append(
                        " ".join(str(d.get(k, "")) for k in ("tool", "tool_name", "name"))
                        if isinstance(d, dict)
                        else ""
                    )
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    if parsed is not None:
        walk(parsed)
    return denials, tool_uses, tool_use_names, denial_names


def compute_verdict(tool_uses, tool_use_names, denial_names, note_top):
    """Return (verdict, ship, sw_denied, sw_attempted, control_before,
    control_after)."""
    tooluse_text = "\n".join(tool_uses).lower()
    names_text = "\n".join(tool_use_names).lower()
    denial_names_text = "\n".join(denial_names).lower()

    # Key both signals on the recorded NAME field, never the token appearing anywhere in
    # the serialized input/record — a ToolSearch query "select:ScheduleWakeup" or a denial
    # record with the token nested in its input is not a real ScheduleWakeup call (issue
    # #1527). Case-insensitive keeps a lower-cased/input-less name present (issue #415 #2).
    sw_denied = "schedulewakeup" in denial_names_text
    sw_attempted = "schedulewakeup" in names_text
    control_before = "/etc/hosts" in tooluse_text       # Action 1 ran
    control_after = "/etc/os-release" in tooluse_text    # Action 3 ran -> passed Action 2

    if note_top:
        verdict = "INCONCLUSIVE"
    elif sw_denied and sw_attempted:
        verdict = "DENIED"
    elif sw_denied:
        verdict = "REMOVED"
    elif sw_attempted:
        verdict = "AVAILABLE"
    else:
        # No positive signal: a ship verdict requires a permission_denials record, never
        # presumptive absence — both controls running is not evidence of removal, only
        # that the model progressed (issue #1527; CLAUDE.md "Unknown is not zero").
        verdict = "INCONCLUSIVE"

    ship = verdict in ("DENIED", "REMOVED")
    return verdict, ship, sw_denied, sw_attempted, control_before, control_after


def render(exec_file):
    parsed, note_top = parse_execution_file(exec_file)
    denials, tool_uses, tool_use_names, denial_names = collect(parsed)
    (verdict, ship, sw_denied, sw_attempted,
     control_before, control_after) = compute_verdict(
         tool_uses, tool_use_names, denial_names, note_top)

    inconclusive = verdict == "INCONCLUSIVE"
    if ship:
        decision = ("SHIP `--disallowedTools ScheduleWakeup` in "
                    "devflow-implement.yml's claude step + its lib/test/run.sh pin")
    elif verdict == "AVAILABLE":
        decision = ("DO NOT SHIP a claude_args change; record the probe run "
                    "link and this omission rationale on the PR")
    else:
        decision = ("DO NOT ACT — the probe measured nothing conclusive; "
                    "re-run before deciding")

    out = []
    out.append("## ScheduleWakeup `--disallowedTools` probe (issue #415)")
    out.append("")
    out.append("Deterministic verdict from the execution file's "
               "`permission_denials` with a recorded `tool_use` (DENIED), a recorded "
               "`tool_use` not denied (AVAILABLE), a `permission_denials` with no "
               "recorded attempt (REMOVED, presumptive), or no positive signal "
               "(INCONCLUSIVE). The model's text is never the measurement.")
    out.append("")
    if verdict == "REMOVED":
        out.append("> [!NOTE]")
        out.append("> REMOVED is **presumptive**: a ScheduleWakeup denial was recorded "
                   "with no registered tool_use attempt, which reads as the flag removing "
                   "the tool from context — but the harness may record a denial without a "
                   "tool_use node, so confirm the recorded names below and re-run to "
                   "corroborate before shipping.")
        out.append("")
    if inconclusive:
        out.append("> [!WARNING]")
        if note_top:
            out.append("> %s — verdict INCONCLUSIVE; re-run the probe." % note_top)
        else:
            out.append("> No positive ScheduleWakeup signal (denial=no, attempt=no), so "
                       "tool removal cannot be distinguished from the model not attempting "
                       "the call (controls: before=%s, after=%s) — verdict INCONCLUSIVE; "
                       "re-run the probe." % (
                           "yes" if control_before else "no",
                           "yes" if control_after else "no"))
        out.append("")
    out.append("| Verdict | Ship flag? | Evidence |")
    out.append("|---------|-----------|----------|")
    out.append("| **%s** | %s | denial=%s; tool_use(ScheduleWakeup)=%s; control_before(grep)=%s; control_after(grep)=%s |" % (
        verdict,
        "yes" if ship else "no",
        "yes" if sw_denied else "no",
        "yes" if sw_attempted else "no",
        "yes" if control_before else "no",
        "yes" if control_after else "no",
    ))
    out.append("")
    out.append("**claude_args decision (issue #415 AC4): %s.**" % decision)
    out.append("")
    out.append("### Raw denial entries (%d)" % len(denials))
    out.append("")
    if denials:
        out.append("```")
        for d in denials:
            out.append(d[:400])
        out.append("```")
    else:
        out.append("_No permission_denials entries found in the execution file._")

    # Dump the recorded tool_use entries so the operator can confirm the harness's
    # actual ScheduleWakeup tool name on the first live run — the name-scoped match above
    # keys on the recorded name field, so this dump is how that field's real spelling is
    # confirmed rather than assumed.
    out.append("")
    out.append("### Raw tool_use entries (%d)" % len(tool_uses))
    out.append("")
    if tool_uses:
        out.append("```")
        for t in tool_uses:
            out.append(t[:400])
        out.append("```")
    else:
        out.append("_No tool_use entries found in the execution file._")

    return "\n".join(out)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    _force_utf8_streams()
    exec_file = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EXECUTION_FILE", "")) or ""
    table = render(exec_file)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        # Best-effort side-output: an unwritable GITHUB_STEP_SUMMARY path must not
        # raise through main() and break the "Always exits 0" contract — the verdict
        # table already went to stdout (the authoritative surface).
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(table + "\n")
        except OSError as e:
            sys.stderr.write(
                "schedulewakeup-probe-verdict: could not append to "
                "GITHUB_STEP_SUMMARY (%s); verdict is on stdout\n" % e.__class__.__name__
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

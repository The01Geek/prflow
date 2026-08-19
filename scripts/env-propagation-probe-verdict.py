# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""env-propagation-probe-verdict.py — derive the step-level `env:` propagation probe
verdict from a `claude-code-action` execution file (issue #874).

Why a helper rather than inline Python in matcher-probe.yml: this verdict is a
branch-selecting core (a BOTH_HOPS / ORCHESTRATOR_ONLY / NEITHER_HOP / INCONCLUSIVE
selection, plus the suspect DISPATCHED_TASK_ONLY inversion, plus the
record/do-not-record decision a maintainer transcribes into the cloud allowlist
evidence record). Inline-in-YAML it cannot be unit-tested, so a regressed
arm would silently misfire while the workflow still "runs" — the same rationale as
scripts/background-tasks-probe-verdict.py (#812), scripts/schedulewakeup-probe-verdict.py
(#415), and scripts/describe-denial-count.sh (PR #367).

THE PREMISE UNDER TEST. Issue #874 moves the review tier's prompt-extension bytes behind
a trusted base-ref closure and points the loader at it with `DEVFLOW_PROMPT_EXTENSION_ROOT`,
published through `$GITHUB_ENV` on the review job. Whether a job-scoped environment value
is visible to a command run through the agent's Bash tool was NOT established when that
change shipped, and the two protected loads sit at DIFFERENT depths: the `review` load
runs in the orchestrator's own shell (hop one) while the `requesting-code-review` load
runs inside a dispatched `general-purpose` Task (hop two). Every other `env:` entry on
that step is consumed by the CLI process itself, so no existing evidence covers a value
an agent-run command must READ BACK.

The design's failure direction is safe at both hops — an unpropagated variable makes the
loader resolve the repo-root path, where it finds the workflow's truncated file and prints
nothing — so a propagation failure costs the feature, never the boundary. This probe tells
a maintainer which of those two worlds they are in.

HOW HOP TWO IS MADE MEASURABLE. The probe borrows the #812 technique rather than assuming
a dispatched Task's own tool calls land in this execution file: the probe subagent's ENTIRE
final response is one marker line carrying what it read, and the top-level session echoes
that back through its own Bash call. A Bash `tool_use` carrying the hop-two marker is the
harness-recorded evidence. The model's prose is never the measurement.

WHAT THIS PROBE DOES NOT ESTABLISH. It measures visibility of a sentinel value, not of
`DEVFLOW_PROMPT_EXTENSION_ROOT` under a real review run's step ordering, and it rests on
a cooperative model faithfully reporting what it read — a compliant model reaches the
value-in-hand branch only when it holds the value, but a non-compliant one could emit
either marker. Read the verdict as evidence, not proof; the raw tool_use dump below is
what an operator confirms it against.

Always exits 0: a red verdict step with no table is the worst outcome on exactly the
degraded run this probe exists to characterize.
"""

import json
import os
import re
import sys

# The sentinel the workflow puts in the step-level env:. Deliberately not a plausible
# real path — a match cannot be confused with an incidental mention.
SENTINEL = "DEVFLOW_ENVPROBE_SENTINEL_874"
HOP1 = "ENVPROBE_HOP1"
HOP2 = "ENVPROBE_HOP2"
# The two controls prove the session reached and passed the measured actions. Without
# them a run that never got started reads identically to one where nothing propagated.
CONTROL_BEFORE = "ENVPROBE_CONTROL_BEFORE"
CONTROL_AFTER = "ENVPROBE_CONTROL_AFTER"

# A hop is REPORTED only when a recorded entry carries its marker followed by an
# OBSERVED value — the sentinel, or the literal UNSET the probe's `:-UNSET` default
# produces. Bare-marker presence is NOT enough, and that distinction is the whole
# guard: the probe's own instructions put each marker into a tool_use input in
# UNEXPANDED form (`printf 'ENVPROBE_HOP1 %s\n' "$VAR"` for hop one, and the hop-two
# dispatch prompt for hop two), so a bare-substring test reports BOTH hops from the
# commands that merely ASK for the measurement. A run whose echo-back never happened
# would then satisfy `hop1_reported and hop2_reported` while neither hop was observed,
# and fall through to NEITHER_HOP — recording "a step-level env: entry is not visible
# at either depth" as a measurement of a run that measured nothing. That is the
# unknown-is-not-zero collapse the arm ordering below exists to prevent, so the
# operand it reads must mean "observed", not "commanded".
_OBSERVED = {SENTINEL, "UNSET"}


def _hop_values(tool_uses, marker):
    """Return the set of OBSERVED values recorded for a hop marker.

    Matches `<marker> <token>` and keeps only tokens the probe can actually observe.
    A `%s` template (the unexpanded printf the instructions carry) yields nothing."""
    pat = re.compile(re.escape(marker) + r"\s+([^\s\"'\\]+)")
    return {v for t in tool_uses for v in pat.findall(t)} & _OBSERVED


def parse_execution_file(exec_file):
    """Return (parsed, note_top). parsed is a JSON value — an empty list on every
    failure path, so callers need no None-guard — and note_top is a non-empty
    diagnostic when the file was absent/empty/unparseable/partially corrupt, which
    forces INCONCLUSIVE."""
    if not (exec_file and os.path.isfile(exec_file)):
        return [], "execution file path absent or not a regular file at '%s'" % exec_file
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        return [], "execution file present but unreadable (%s)" % e.__class__.__name__
    try:
        return json.loads(raw), ""
    except Exception:
        pass
    # Not a single JSON document — try JSONL, counting unparseable lines. A PARTIAL
    # corruption (some lines parse but the marker record does not) would otherwise read
    # as a clean measurement, so any drop forces INCONCLUSIVE.
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
            "%d execution-file line(s) were unparseable — verdict may be incomplete" % dropped
        )
    return parsed, ""


def collect(parsed):
    """Walk the parsed structure and return the recorded tool_use entries as text.

    A tool_use node is recorded even when it carries no `input` key, so an input-less
    entry is not silently dropped."""
    tool_uses = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "tool_use":
                tool_uses.append(json.dumps(o.get("input")) + " NAME=" + str(o.get("name", "")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(parsed)
    return tool_uses


def compute_verdict(tool_uses, note_top):
    """Return (verdict, reason, record_it).

    A hop counts as PROPAGATED only when its marker is recorded alongside the sentinel
    as an OBSERVED value in the same entry. Requiring co-occurrence is what stops the
    sentinel leaking in from the OTHER hop's entry and crediting a hop that never saw
    it; requiring an OBSERVED value (see `_hop_values`) is what stops the probe's own
    unexpanded instruction text from being counted as a report."""
    hop1_values = _hop_values(tool_uses, HOP1)
    hop2_values = _hop_values(tool_uses, HOP2)
    hop1 = SENTINEL in hop1_values
    hop2 = SENTINEL in hop2_values
    hop1_reported = bool(hop1_values)
    hop2_reported = bool(hop2_values)
    before = any(CONTROL_BEFORE in t for t in tool_uses)
    after = any(CONTROL_AFTER in t for t in tool_uses)

    # Ordered, and the degraded arms come FIRST. A measurement that did not run must
    # never be read as a measurement that came back negative — collapsing "we could not
    # look" onto "it does not propagate" is the fail-open this ordering exists to stop.
    if note_top:
        return "INCONCLUSIVE", "the execution file could not be read cleanly: " + note_top, False
    if not tool_uses:
        return "INCONCLUSIVE", "no tool_use entries were recorded, so nothing was measured", False
    if not (before and after):
        return (
            "INCONCLUSIVE",
            "the session did not record both positive controls (%s=%s, %s=%s), so it may "
            "not have reached or completed the measured actions"
            % (CONTROL_BEFORE, before, CONTROL_AFTER, after),
            False,
        )
    if not (hop1_reported and hop2_reported):
        return (
            "INCONCLUSIVE",
            "a hop reported nothing at all (hop1_reported=%s, hop2_reported=%s), so its "
            "visibility is unestablished rather than negative" % (hop1_reported, hop2_reported),
            False,
        )
    if hop1 and hop2:
        return (
            "BOTH_HOPS",
            "the sentinel was visible to the orchestrator's own Bash command AND to the "
            "dispatched Task's, so a job-scoped env value reaches both depths",
            True,
        )
    if hop1 and not hop2:
        return (
            "ORCHESTRATOR_ONLY",
            "the sentinel was visible at hop one but NOT inside the dispatched Task, so "
            "the Phase-3 requesting-code-review load would fall back to the repo-root path",
            True,
        )
    if hop2 and not hop1:
        return (
            "DISPATCHED_TASK_ONLY",
            "the sentinel was visible inside the dispatched Task but NOT to the "
            "orchestrator's own command — an inversion of the expected shape; treat the "
            "run as suspect and re-dispatch before recording",
            False,
        )
    return (
        "NEITHER_HOP",
        "both hops reported, and neither saw the sentinel: a step-level env: entry is not "
        "visible to agent-run commands at either depth",
        True,
    )


def render(exec_file):
    parsed, note_top = parse_execution_file(exec_file)
    try:
        tool_uses = collect(parsed)
    except RecursionError:
        note_top = (note_top + "; " if note_top else "") + (
            "execution file nested too deeply to walk"
        )
        tool_uses = []
    verdict, reason, record_it = compute_verdict(tool_uses, note_top)

    out = []
    out.append("## Step-level `env:` propagation probe (issue #874)")
    out.append("")
    out.append("**Verdict: `%s`**" % verdict)
    out.append("")
    out.append(reason + ".")
    out.append("")
    out.append(
        "Deterministic verdict from the execution file's recorded `tool_use` entries — "
        "the model's prose is never the measurement. Sentinel: `%s`." % SENTINEL
    )
    out.append("")
    if record_it:
        out.append(
            "**Record this run** in the cloud allowlist evidence record's "
            "propagation-measurement entry, with the run id and the verdict above."
        )
    else:
        out.append(
            "**Do NOT record this run** — the measurement did not establish either hop. "
            "Re-dispatch the probe."
        )
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
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main():
    _force_utf8_streams()
    exec_file = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EXECUTION_FILE", "")) or ""
    table = render(exec_file)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        # Best-effort side-output: an unwritable GITHUB_STEP_SUMMARY must not raise through
        # main() and break the "Always exits 0" contract — the verdict already went to
        # stdout, the authoritative surface.
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(table + "\n")
        except OSError as e:
            sys.stderr.write(
                "env-propagation-probe-verdict: could not append to GITHUB_STEP_SUMMARY "
                "(%s); verdict is on stdout\n" % e.__class__.__name__
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

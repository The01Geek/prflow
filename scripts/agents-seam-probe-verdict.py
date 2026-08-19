# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""agents-seam-probe-verdict.py — derive the cloud per-agent-effort *seam* probe
verdict from a `claude-code-action` execution file (issue #610, carried from #554).

Why a helper rather than inline Python in agents-seam-probe.yml: this verdict is a
branch-selecting core (a five-way SEAM_PROVEN / SEAM_FORWARDED / SEAM_UNPROVEN /
INSTRUMENT_NOT_FIRED / INCONCLUSIVE selection plus a ship / no-ship decision that gates
whether the spike-gated *applied arm* — composing a resolved per-agent effort into a
process-start `--agents` agent-definition — may ship). Inline-in-YAML it cannot be
unit-tested, so a regressed arm (the INCONCLUSIVE floor, the unproven-vs-not-measured
split, the human-adjudication gate) would silently misfire while the workflow still
"runs". Extracting it lets lib/test/run.sh drive every arm and the fail-open matrix
directly — the same rationale as scripts/schedulewakeup-probe-verdict.py (#415) and
scripts/describe-denial-count.sh (PR #367).

The two facts the spike must establish (issue #610 AC1):

  (i)  `claude-code-action` FORWARDS a startup `--agents` JSON supplied via
       `claude_args` at process launch — so a custom `subagent_type` defined only in
       that block is dispatchable. This IS deterministically measurable: the probe's
       agent-definition instructs the subagent to emit a distinctive seam marker; the
       marker can appear only if the subagent actually ran, which requires the
       `--agents` block to have been forwarded and the type recognized.
  (ii) an `effort` set on that startup agent-definition GOVERNS the reasoning effort of
       a runtime Agent-tool dispatch of that `subagent_type`. This is NOT
       deterministically measurable from the execution file — effort is not a
       harness-recorded field, so the only signal is the subagent's own self-report,
       which is model text and must be adjudicated by a human (the same human-dispatch,
       human-adjudicated model matcher-probe.yml uses). Until a human adjudicates
       fact (ii) as GOVERNED (passing --adjudicated-governed / ADJUDICATED_GOVERNED),
       the seam is NOT proven and the applied arm does NOT ship.

Deterministic five-way verdict, execution-file only (the model's prose is never the
measurement — only harness-recorded `tool_use` inputs and `permission_denials`):

  SEAM_PROVEN    fact (i) forwarding evidence present AND a human adjudicated fact (ii)
                 as GOVERNED (--adjudicated-governed). SHIPS the applied arm.
  SEAM_FORWARDED fact (i) proven (the seam marker was emitted) but fact (ii) not
                 adjudicated. Does NOT ship — honest fallback stays; a human must
                 adjudicate the recorded effort self-report first.
  SEAM_UNPROVEN  a dispatch of the probe subagent_type was ATTEMPTED, no seam marker
                 appeared, AND the record carries an affirmative NON-FORWARDING signal
                 (the prompt's refusal marker was echoed through a tool call, or a
                 permission_denials entry names the probe subagent). Does NOT ship —
                 honest fallback stays. This is a statement about the SEAM.
  INSTRUMENT_NOT_FIRED
                 a dispatch was ATTEMPTED but NEITHER marker reached the record, so the
                 prompt's Step 2 never executed (issue #1177). Both of that step's arms
                 run through a model-issued Bash echo the model may simply skip — four of
                 the eight successful 2026-07-21 dispatches recorded exactly one tool_use,
                 the Agent dispatch itself, and stopped. Such a run is uninformative in
                 EITHER direction: it is an instrument non-fire, NOT counter-evidence, and
                 its rendered text says so rather than reporting on the seam. Ships
                 nothing, for want of a measurement — never because the seam failed.
  INCONCLUSIVE   nothing conclusive was measured (note_top, or no dispatch was even
                 attempted). Ships nothing: an unestablished measurement is never
                 collapsed onto a shippable verdict (CLAUDE.md: "Unknown is not zero").

Decision rule, in order: note_top -> INCONCLUSIVE; seam marker -> SEAM_PROVEN (only with
the human flag) else SEAM_FORWARDED; dispatch attempted AND a non-forwarding signal ->
SEAM_UNPROVEN; dispatch attempted -> INSTRUMENT_NOT_FIRED; else INCONCLUSIVE.

Fail-open hardening (mirrors #415): the marker/agent-name matches are
case-INSENSITIVE, and a tool_use node is recorded even when it carries no `input` key,
so a decorated / input-less dispatch still reads as attempted rather than absent — the
latter would misread a dispatched run as INCONCLUSIVE. Never auto-promote to SEAM_PROVEN:
fact (ii) requires the explicit human flag, so the dangerous direction (shipping the
applied arm on an unproven seam) is unreachable without a human in the loop.

Markers the probe agent-definition/prompt emit (kept in lockstep with
agents-seam-probe.yml):
  SEAM_PROBE_FORWARDED_OK   the subagent ran (⇒ `--agents` was forwarded).
  SEAM_PROBE_EFFORT=<word>  the subagent's self-reported effort (fact (ii) evidence).
  seam-probe-agent          the probe subagent_type name (dispatch-attempt signal).
  dispatch refused: unknown subagent_type
                            the prompt's refusal arm ⇒ the type was not recognized.

VERDICT-INERT DIAGNOSTIC (issue #1177). Issue #1177's cleanest remedy — read the
subagent's returned line where the harness already wrote it, and stop depending on the
top-level model to echo it — rests on a premise this repository has NOT established:
whether the execution file carries a dispatched subagent's returned text at all.
the observed shape record notes `tool_use_result` as present but is explicit that
presence of a field is not proof of its attribution, and its local-transcript row must not
be cited for the execution file. So this helper does not act on the premise; it MEASURES
it, verdict-inert, on whatever dispatch a maintainer next decides to pay for. It reports
whether any recorded tool RESULT payload exists and whether the seam marker appears in it,
and neither fact can move the verdict — `forwarded` reads recorded `tool_use` INPUTS and
nothing else, so the diagnostic can never promote a run to SEAM_FORWARDED/SEAM_PROVEN.

Usage: agents-seam-probe-verdict.py [EXECUTION_FILE] [--adjudicated-governed]
  EXECUTION_FILE           path to the action's execution file; if omitted, read from
                           the EXECUTION_FILE env var. Empty/absent -> INCONCLUSIVE.
  --adjudicated-governed   a human has adjudicated fact (ii) as GOVERNED from the
                           recorded self-report. Also settable via the truthy
                           ADJUDICATED_GOVERNED env var (1/true/yes, case-insensitive).
Prints the markdown verdict table to stdout (and appends it to GITHUB_STEP_SUMMARY
when set). Always exits 0.
"""

import json
import os
import re
import sys

AGENT_NAME = "seam-probe-agent"
FORWARDED_MARKER = "SEAM_PROBE_FORWARDED_OK"
EFFORT_MARKER_RE = re.compile(r"SEAM_PROBE_EFFORT=([A-Za-z]+)", re.IGNORECASE)
# The distinctive tail of the prompt's refusal arm (agents-seam-probe.yml Step 2). Matched
# rather than the whole line so the agent-name prefix is not required twice; a hit is the
# only tool-recorded evidence that the startup `--agents` block was NOT forwarded.
REFUSAL_MARKER = "dispatch refused: unknown subagent_type"
# The tool the prompt's Step 2 must reach for EITHER arm to be recorded. Compared as an
# exact (case-insensitive) tool name: over-recognizing a decorated name would let a run
# that never ran the instrument be reported as a statement about the seam, which is the
# failure issue #1177 removes — so this match is deliberately narrow, and it is reported
# as evidence only. It never selects the verdict on its own.
BASH_TOOL_NAME = "bash"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def parse_execution_file(exec_file):
    """Return (parsed, note_top). parsed is a JSON value or None; note_top is a
    non-empty diagnostic when the file was absent/empty/unparseable/partially
    corrupt (which forces INCONCLUSIVE)."""
    if not (exec_file and os.path.isfile(exec_file)):
        return None, "execution file path absent or not a regular file at '%s'" % exec_file
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        # Present-but-unreadable (PermissionError/OSError) or a TOCTOU disappearance:
        # route to the INCONCLUSIVE floor instead of raising, honoring "Always exits 0".
        return [], "execution file present but unreadable (%s)" % e.__class__.__name__
    try:
        return json.loads(raw), ""
    except Exception:
        pass
    # Not a single JSON document — try JSONL, counting unparseable lines. A PARTIAL
    # corruption would otherwise read as a clean measurement, so any drop forces the floor.
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
    """Walk the parsed structure and return (denials, tool_uses, tool_names, results) as
    text lists. A tool_use node is recorded even when it carries no `input` key (fail-open
    guard). `tool_names` carries each tool_use's own recorded name (the Bash-reached
    evidence fact); `results` carries recorded tool RESULT payloads and feeds only the
    verdict-INERT issue-#1177 diagnostic — never the verdict."""
    denials = []
    tool_uses = []
    tool_names = []
    results = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "tool_use":
                tool_uses.append(
                    json.dumps(o.get("input")) + " NAME=" + str(o.get("name", ""))
                )
                tool_names.append(str(o.get("name", "")))
            # Result-payload channel (diagnostic only). Two observed shapes are accepted
            # because the execution-file schema is a dated observation, not a contract:
            # a node carrying a `tool_use_result` key, and
            # a `tool_result`-typed content block. Only the payload is taken — never the
            # enclosing node — so a tool_use INPUT can never leak into this channel.
            if "tool_use_result" in o:
                results.append(json.dumps(o.get("tool_use_result")))
            elif o.get("type") == "tool_result":
                results.append(json.dumps(o.get("content")))
            pd = o.get("permission_denials")
            if isinstance(pd, list):
                for d in pd:
                    denials.append(json.dumps(d))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    if parsed is not None:
        walk(parsed)
    return denials, tool_uses, tool_names, results


def compute_verdict(denials, tool_uses, tool_names, results, note_top, adjudicated_governed):
    """Return a dict of the verdict and every evidence fact the renderer prints.

    All token matches are case-insensitive so a decorated tool name / marker still
    reads as present (fail-open in the safe direction)."""
    denial_text = "\n".join(denials).lower()
    tooluse_text = "\n".join(tool_uses)
    tooluse_lower = tooluse_text.lower()

    # Fact (i): the seam marker can appear only if the subagent actually ran, which
    # requires the `--agents` block to have been forwarded and the type recognized.
    # Deliberately reads recorded tool_use INPUTS only — never the result channel below.
    forwarded = FORWARDED_MARKER.lower() in tooluse_lower
    # A dispatch of the probe subagent_type was attempted (its name reached a tool
    # input or a denial). Distinguishes a dispatched run from INCONCLUSIVE (never even
    # attempted).
    dispatch_attempted = (
        AGENT_NAME.lower() in tooluse_lower or AGENT_NAME.lower() in denial_text
    )
    # An AFFIRMATIVE non-forwarding signal: the prompt's refusal arm reached the record,
    # or the harness itself refused a dispatch naming the probe subagent. Only this
    # licenses a statement ABOUT THE SEAM in the negative direction; its absence on a
    # dispatched run means the instrument did not fire, not that the seam failed (#1177).
    nonforwarding_signal = (
        REFUSAL_MARKER.lower() in tooluse_lower or AGENT_NAME.lower() in denial_text
    )
    # Evidence fact, reported and never decisive: did the prompt's Step 2 reach Bash at
    # all? A non-fire that recorded no Bash call whatsoever is the signature issue #1177
    # observed in four of eight successful dispatches.
    bash_recorded = any(n.strip().lower() == BASH_TOOL_NAME for n in tool_names)
    # Fact (ii) evidence: the subagent's self-reported effort (human-adjudicated).
    m = EFFORT_MARKER_RE.search(tooluse_text)
    effort_signal = m.group(1) if m else "unobserved"

    # Verdict-INERT diagnostic (#1177): does the record carry a tool RESULT payload, and
    # does the seam marker appear in it? Answering these makes the next maintainer-decided
    # dispatch establish the premise the "read it from the harness record" remedy needs.
    # Neither value is read below — an unestablished channel reports `unestablished`, never
    # `no` (CLAUDE.md: "Unknown is not zero").
    result_channel = "recorded" if results else "absent"
    if not results:
        marker_in_results = "unestablished"
    else:
        marker_in_results = (
            "yes" if FORWARDED_MARKER.lower() in "\n".join(results).lower() else "no"
        )

    if note_top:
        verdict = "INCONCLUSIVE"
    elif forwarded:
        # Fact (i) proven. Fact (ii) needs a human: never auto-promote to PROVEN.
        verdict = "SEAM_PROVEN" if adjudicated_governed else "SEAM_FORWARDED"
    elif dispatch_attempted and nonforwarding_signal:
        # The subagent_type was dispatched and the record affirmatively says the type was
        # not recognized — the `--agents` startup block was not forwarded.
        verdict = "SEAM_UNPROVEN"
    elif dispatch_attempted:
        # Dispatched, but neither of the prompt's Step 2 arms reached the record: the
        # instrument never fired, so this run measured nothing about the seam.
        verdict = "INSTRUMENT_NOT_FIRED"
    else:
        # No forwarding signal and no dispatch even attempted — nothing was exercised.
        verdict = "INCONCLUSIVE"

    return {
        "verdict": verdict,
        "ship": verdict == "SEAM_PROVEN",
        "forwarded": forwarded,
        "dispatch_attempted": dispatch_attempted,
        "nonforwarding_signal": nonforwarding_signal,
        "bash_recorded": bash_recorded,
        "effort_signal": effort_signal,
        "result_channel": result_channel,
        "marker_in_results": marker_in_results,
    }


def render(exec_file, adjudicated_governed):
    parsed, note_top = parse_execution_file(exec_file)
    denials, tool_uses, tool_names, results = collect(parsed)
    ev = compute_verdict(
        denials, tool_uses, tool_names, results, note_top, adjudicated_governed
    )
    verdict = ev["verdict"]
    ship = ev["ship"]
    forwarded = ev["forwarded"]
    dispatch_attempted = ev["dispatch_attempted"]
    effort_signal = ev["effort_signal"]

    if ship:
        decision = (
            "SHIP the spike-gated applied arm — compose the resolved per-agent effort "
            "into the process-start `--agents` agent-definition (both facts proven); "
            "flip the cloud per-agent row off honest fallback per issue #610 AC2/AC3"
        )
    elif verdict == "SEAM_FORWARDED":
        decision = (
            "DO NOT SHIP the applied arm — fact (i) forwarding is proven but fact (ii) "
            "(effort governs the dispatch) needs human adjudication of the recorded "
            "self-report (SEAM_PROBE_EFFORT=%s); keep the honest fallback and re-run "
            "with --adjudicated-governed once a human confirms fact (ii)" % effort_signal
        )
    elif verdict == "SEAM_UNPROVEN":
        decision = (
            "DO NOT SHIP the applied arm — the startup `--agents` seam was not forwarded "
            "(the record carries an affirmative non-forwarding signal for the probe "
            "subagent_type); keep the honest fallback identical to local"
        )
    elif verdict == "INSTRUMENT_NOT_FIRED":
        decision = (
            "NO SEAM MEASUREMENT was taken, so no applied-arm decision rests on this run "
            "— the probe subagent was dispatched, but neither the seam marker nor the "
            "refusal marker reached the record, so nothing here distinguishes a forwarded "
            "seam from an unforwarded one. Do NOT read this run as evidence for or "
            "against forwarding and do NOT score it beside a SEAM_UNPROVEN run. The "
            "applied arm stays unshipped and the honest fallback is unchanged for want of "
            "a measurement, NOT because the seam failed. Re-dispatch the probe"
        )
    else:
        decision = (
            "DO NOT ACT — the probe measured nothing conclusive; re-run before deciding"
        )

    out = []
    out.append("## Cloud per-agent-effort seam probe (issue #610)")
    out.append("")
    out.append(
        "Deterministic verdict from the execution file's recorded `tool_use` inputs "
        "(the seam marker `%s` ⇒ fact (i) forwarding proven) and `permission_denials`, "
        "with fact (ii) (effort governs the dispatch) adjudicated by a human from the "
        "recorded self-report. The model's prose is never the measurement." % FORWARDED_MARKER
    )
    out.append("")
    if verdict == "SEAM_FORWARDED":
        out.append("> [!NOTE]")
        out.append(
            "> Fact (i) is proven but fact (ii) is **not** auto-measurable: effort is "
            "not a harness-recorded field, so the recorded `SEAM_PROBE_EFFORT=%s` "
            "self-report must be adjudicated by a human. The applied arm ships ONLY "
            "once a human confirms fact (ii) and re-runs this verdict with "
            "`--adjudicated-governed`." % effort_signal
        )
        out.append("")
    if verdict == "INSTRUMENT_NOT_FIRED":
        out.append("> [!WARNING]")
        out.append(
            "> INSTRUMENT NON-FIRE (issue #1177) — the session dispatched `%s` but the "
            "prompt's Step 2 put neither marker into the record "
            "(bash_tool_use_recorded=%s), so the deterministic instrument had nothing to "
            "read. This is a property of the INSTRUMENT, not of the seam: the run is "
            "uninformative in EITHER direction and must not be counted as a negative. "
            "Re-dispatch the probe."
            % (AGENT_NAME, "yes" if ev["bash_recorded"] else "no")
        )
        out.append("")
    if verdict == "INCONCLUSIVE":
        out.append("> [!WARNING]")
        if note_top:
            out.append("> %s — verdict INCONCLUSIVE; re-run the probe." % note_top)
        else:
            out.append(
                "> No dispatch of the probe subagent_type was attempted (forwarded=%s, "
                "dispatch_attempted=%s), so the seam was not exercised — verdict "
                "INCONCLUSIVE; re-run the probe."
                % ("yes" if forwarded else "no", "yes" if dispatch_attempted else "no")
            )
        out.append("")
    out.append("| Verdict | Ship applied arm? | Evidence |")
    out.append("|---------|-------------------|----------|")
    out.append(
        "| **%s** | %s | forwarded(marker)=%s; dispatch_attempted=%s; "
        "nonforwarding_signal=%s; bash_tool_use_recorded=%s; effort_self_report=%s; "
        "fact(ii)_adjudicated=%s |"
        % (
            verdict,
            "yes" if ship else "no",
            "yes" if forwarded else "no",
            "yes" if dispatch_attempted else "no",
            "yes" if ev["nonforwarding_signal"] else "no",
            "yes" if ev["bash_recorded"] else "no",
            effort_signal,
            "yes" if adjudicated_governed else "no",
        )
    )
    out.append("")
    out.append("**Applied-arm decision (issue #610 AC1): %s.**" % decision)
    out.append("")
    out.append(
        "### Verdict-inert diagnostic — does the record carry the dispatched subagent's "
        "returned text? (issue #1177)"
    )
    out.append("")
    out.append(
        "`dispatch_result_channel=%s; forwarded_marker_in_result_channel=%s`"
        % (ev["result_channel"], ev["marker_in_results"])
    )
    out.append("")
    out.append(
        "These two facts are reported ONLY, and are read by nothing above: the verdict is "
        "computed from recorded `tool_use` INPUTS and `permission_denials`, so no value "
        "here can promote a run to `SEAM_FORWARDED` or `SEAM_PROVEN`. They exist to settle, "
        "on whatever dispatch a maintainer next pays for, the premise issue #1177's "
        "\"read the subagent's return value from the harness record\" remedy would rest "
        "on — a premise this repository has NOT established "
        "(the observed shape record notes `tool_use_result` as present but states "
        "that a field's presence is not proof of its attribution). "
        "`forwarded_marker_in_result_channel=unestablished` means no result payload was "
        "found at all; it never means the marker was absent from one."
    )
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

    # Dump the recorded tool_use entries so an operator can confirm the harness's actual
    # dispatch shape and the subagent's self-report on the first live run.
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


def _truthy_env(val):
    return (val or "").strip().lower() in ("1", "true", "yes")


def main():
    _force_utf8_streams()
    exec_file = ""
    adjudicated = _truthy_env(os.environ.get("ADJUDICATED_GOVERNED", ""))
    for arg in sys.argv[1:]:
        if arg == "--adjudicated-governed":
            adjudicated = True
        elif not exec_file:
            exec_file = arg
    if not exec_file:
        exec_file = os.environ.get("EXECUTION_FILE", "") or ""
    table = render(exec_file, adjudicated)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        # Best-effort side-output: an unwritable GITHUB_STEP_SUMMARY must not raise
        # through main() and break the "Always exits 0" contract — the verdict table
        # already went to stdout (the authoritative surface).
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(table + "\n")
        except OSError as e:
            sys.stderr.write(
                "agents-seam-probe-verdict: could not append to GITHUB_STEP_SUMMARY "
                "(%s); verdict is on stdout\n" % e.__class__.__name__
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

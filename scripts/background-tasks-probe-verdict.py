# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""background-tasks-probe-verdict.py — derive the `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`
harness-floor probe verdict from a `claude-code-action` execution file (issue #812).

Why a helper rather than inline Python in matcher-probe.yml: this verdict is a
branch-selecting core (a four-way FOREGROUND / BACKGROUNDED / NOT_DISPATCHED /
INCONCLUSIVE selection plus the record/do-not-record decision a maintainer transcribes
into the docs record) that adjudicates whether issue #801's harness floor actually
takes effect. Inline-in-YAML it cannot be unit-tested, so a regressed arm — the
INCONCLUSIVE floor, the attempted-vs-never-dispatched split, the marker matches — would
silently misfire while the workflow still "runs". Extracting it lets
lib/test/modules/review-stall-backstop.sh drive each verdict arm enumerated below, and
the fail-open matrix, directly — the same rationale as scripts/schedulewakeup-probe-verdict.py (#415),
scripts/agents-seam-probe-verdict.py (#610), and scripts/describe-denial-count.sh (PR #367).

The premise under test (issue #801). Subagents are background-by-default upstream, and a
background dispatch's results arrive on a LATER turn — which a headless `claude -p` run
never reaches. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"` is documented upstream as
keeping subagents in the foreground, and #801 shipped it on the three engine workflows
unconditionally because it is inert when ignored. Whether it takes effect INSIDE
`claude-code-action` was never observed. This probe observes it.

How "returned a completed result within the same turn" is made measurable. The repository's
observed shape record does list a `tool_use_result` key alongside
`tool_input`/`tool_name` — so a result field is not absent. What that record does NOT
establish is the one thing this probe would need from it: that a `tool_use_result` on a
subagent dispatch carries the subagent's final TEXT, and that its presence distinguishes a
completed return from a launch acknowledgment. Turn boundaries are likewise unrecorded, and
the whole record is a dated observation of one action version rather than a contract. So the
probe borrows #610's technique rather than resting on a field whose semantics are unestablished:
the probe subagent's ENTIRE final response is one marker line, and the top-level session echoes
what it actually received back through a Bash call. A Bash `tool_use` carrying the subagent's
OWN marker is the harness-recorded evidence — under this probe's cooperative-model assumption
— that the completed result was in hand before the turn continued: a compliant model reaches
Action 3's in-hand branch only when it actually holds the subagent's text. The model's prose is
never the measurement.

What that co-occurrence does and does not buy. The two in-hand tokens are required in the
SAME recorded tool_use entry, which rules out the marker leaking from Action 2's dispatch
prompt (that prompt must name the marker it asks for, so the marker is in the file either
way — a whole-file conjunction would be satisfied by the dispatch alone). It rules out
that specific leak and nothing more; it does not make the probe adversarial: like its #415 and #610 siblings this is a
cooperative-model measurement, and a model that ignored its instructions could emit either
branch. The discriminating evidence is which of the two mutually-exclusive Action 3
branches was recorded, and every shape that is neither cleanly floors to INCONCLUSIVE.

Deterministic four-way verdict, execution-file only:

  FOREGROUND     the top-level session echoed the subagent's own returned marker, so the
                 completed result WAS in hand within the same turn. The harness floor is
                 OBSERVED EFFECTIVE on this action version.
  BACKGROUNDED   the session echoed the acknowledgment-only outcome instead: the dispatch
                 returned a launch acknowledgment, not the subagent's result. The floor is
                 OBSERVED INEFFECTIVE — early-quit prevention rests on the headless-wait
                 prose alone, and that is a finding, not a no-op.
  NOT_DISPATCHED both bracketing controls ran but no dispatch was recorded at all.
                 PRESUMPTIVE, not proven: a compliant model that silently skipped the
                 dispatch while still running both controls cannot be excluded. It is
                 never read as evidence against the floor.
  INCONCLUSIVE   nothing conclusive was measured: the file was absent/empty/unparseable or
                 partially corrupt (note_top), a dispatch was attempted but neither outcome
                 marker was recorded, BOTH outcome markers were recorded (a
                 self-contradicting run), or the controls did not both run. Records
                 nothing: an unestablished measurement is never collapsed onto a
                 recordable verdict (CLAUDE.md: "Unknown is not zero").

Note the asymmetry, which is deliberate. Absence of in-hand evidence does NOT fall
through to BACKGROUNDED, because absence is equally consistent with the model skipping the
echo step — only the POSITIVE acknowledgment-only marker reaches that verdict. Both
positive arms therefore require their own recorded marker, and every other shape floors.

Fail-open hardening (mirrors #415/#610): every marker match is case-INSENSITIVE, a
tool_use node is recorded even when it carries no `input` key, and the dispatch signal's
PRIMARY match is the probe's own `BGPROBE_DISPATCH` token riding in the tool INPUT — so a
harness that names the dispatch tool something other than `Task`/`Agent` still reads as a
dispatch. Those two names are kept only as a secondary net for an input-less recording,
where the token itself never reached the file; that net is deliberately substring-shaped, so
a neighbouring tool such as `TaskOutput` also satisfies it — an over-read toward "attempted",
which routes NOT_DISPATCHED to INCONCLUSIVE rather than manufacturing a verdict. A dispatch
the permission matcher DENIED also counts as
attempted: otherwise a run whose dispatch grant was missing would report NOT_DISPATCHED and
read as a model that skipped the step, hiding an allowlist defect behind a presumptive
verdict. Raw tool_use names are dumped in the table so an operator can confirm the
harness's actual dispatch tool name on the first live run.

Markers, kept in lockstep with matcher-probe.yml's `background-tasks-probe` prompt:
  BGPROBE_CONTROL_BEFORE        positive control, before the dispatch
  BGPROBE_DISPATCH              rides in the dispatch tool's INPUT (name-agnostic signal)
  BGPROBE_SUBAGENT_RETURNED_OK  the subagent's own returned marker
  BGPROBE_RESULT_IN_HAND        the session echoed the subagent's completed result
  BGPROBE_ACK_ONLY              the session received only a launch acknowledgment
  BGPROBE_CONTROL_AFTER         positive control, after the dispatch

Usage: background-tasks-probe-verdict.py [EXECUTION_FILE]
  EXECUTION_FILE  path to the action's execution file; if omitted, read from the
                  EXECUTION_FILE env var. Empty/absent -> INCONCLUSIVE.
Prints the markdown verdict table to stdout (and appends it to GITHUB_STEP_SUMMARY when
set). Always exits 0.
"""

import json
import os
import sys

CONTROL_BEFORE = "BGPROBE_CONTROL_BEFORE"
CONTROL_AFTER = "BGPROBE_CONTROL_AFTER"
DISPATCH_MARKER = "BGPROBE_DISPATCH"
SUBAGENT_MARKER = "BGPROBE_SUBAGENT_RETURNED_OK"
RESULT_IN_HAND = "BGPROBE_RESULT_IN_HAND"
ACK_ONLY = "BGPROBE_ACK_ONLY"

# The dispatch signal is the probe's own input token above; these names are a secondary
# net for a run whose dispatch input was not recorded (an input-less tool_use), so an
# attempted dispatch is not misreported as never-attempted.
DISPATCH_TOOL_NAMES = ("task", "agent")

VERSION_CAVEAT = (
    "This verdict is a dated observation of one `claude-code-action` version, not a "
    "platform contract — re-probe after a claude-code-action upgrade before trusting it."
)


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
        # Fires when the path arg is empty/unset (absent) OR is not a regular file
        # (missing, a directory, a special file). A present-but-empty regular file is NOT
        # this branch — isfile() is true, so it flows to the read/parse path and surfaces
        # "present but unparseable" instead.
        return None, f"execution file path absent or not a regular file at '{exec_file}'"
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        # Present-but-unreadable (PermissionError/OSError), or a TOCTOU disappearance after
        # the os.path.isfile() check: route to the note_top -> INCONCLUSIVE floor instead of
        # raising an uncaught traceback through render()/main(), honoring this module's
        # "Always exits 0" contract. Under matcher-probe.yml's `set -euo pipefail` verdict
        # step a traceback yields a red step with NO verdict table, on exactly the degraded
        # run the probe exists to characterize.
        return [], f"execution file present but unreadable ({e.__class__.__name__})"
    try:
        return json.loads(raw), ""
    except Exception:
        pass
    # Not a single JSON document — try JSONL, counting unparseable lines. A PARTIAL
    # corruption (some lines parse but the outcome-marker record does not) would otherwise
    # read as a clean measurement, so any drop forces INCONCLUSIVE.
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
            f"{dropped} execution-file line(s) were unparseable — verdict may be incomplete"
        )
    return parsed, ""


def collect(parsed):
    """Walk the parsed structure and return (denials, tool_uses) as text lists.

    A tool_use node is recorded even when it carries no `input` key, so an input-less
    dispatch is not silently dropped."""
    denials = []
    tool_uses = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "tool_use":
                tool_uses.append(
                    json.dumps(o.get("input")) + " NAME=" + str(o.get("name", ""))
                )
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
    return denials, tool_uses


def compute_verdict(denials, tool_uses, note_top):
    """Return (verdict, record, dispatch_attempted, result_in_hand, ack_only,
    control_before, control_after). Every marker match is case-insensitive so a decorated
    or lower-cased recording still reads as present."""
    # Lowercase each entry ONCE: the per-entry list below and the joined text must not
    # lowercase through two separate expressions, or a later edit can make the two match
    # surfaces disagree about case handling.
    lowered_uses = [t.lower() for t in tool_uses]
    denial_text = "\n".join(denials).lower()
    tooluse_text = "\n".join(lowered_uses)
    both_text = tooluse_text + "\n" + denial_text

    control_before = CONTROL_BEFORE.lower() in tooluse_text
    control_after = CONTROL_AFTER.lower() in tooluse_text

    # A dispatch counts as attempted when the probe's own input token appears anywhere the
    # harness recorded it — including a permission_denials entry, so a refused dispatch is
    # never misreported as a step the model skipped. The tool-name net covers an input-less
    # recording, where the token itself never made it into the file.
    dispatch_attempted = DISPATCH_MARKER.lower() in both_text or any(
        ("name=" + n) in tooluse_text or ('"tool_name": "' + n) in denial_text
        for n in DISPATCH_TOOL_NAMES
    )

    # The two markers must co-occur in the SAME recorded tool_use entry, never merely
    # somewhere in the file. `BGPROBE_SUBAGENT_RETURNED_OK` is unavoidably present in the
    # file already — Action 2's dispatch prompt has to name the marker it asks the subagent
    # for, and that prompt is itself a recorded tool input — so a whole-file conjunction
    # would be satisfied by the dispatch alone and reduce to the outcome word by itself.
    # Only Action 3's in-hand branch emits both tokens in one Bash command.
    result_in_hand = any(
        RESULT_IN_HAND.lower() in entry and SUBAGENT_MARKER.lower() in entry
        for entry in lowered_uses
    )
    # The ack marker gets the SAME per-entry discipline as the in-hand arm above, and for a
    # sharper reason: this arm manufactures a NEGATIVE finding about a shipped safety floor.
    # A bare whole-file substring test would let any recorded input that merely MENTIONS the
    # token — a `description` narrating "not BGPROBE_ACK_ONLY", a retry that restates Action
    # 3's branch text, a future prompt edit that moves the branch instructions into a recorded
    # input — read as BACKGROUNDED and instruct a maintainer to record the floor as
    # ineffective. Requiring the token in an entry that also carries a `command` key scopes it
    # to the Bash call the prompt actually asks for; anything else floors to INCONCLUSIVE.
    ack_only = any(
        ACK_ONLY.lower() in entry and '"command"' in entry for entry in lowered_uses
    )

    if note_top:
        verdict = "INCONCLUSIVE"
    elif result_in_hand and not ack_only:
        verdict = "FOREGROUND"
    elif ack_only and not result_in_hand:
        verdict = "BACKGROUNDED"
    elif result_in_hand and ack_only:
        # A self-contradicting run measured nothing usable; neither positive arm may win.
        verdict = "INCONCLUSIVE"
    elif not dispatch_attempted and control_before and control_after:
        # The model demonstrably reached and passed the dispatch step (both controls ran)
        # without a dispatch being recorded — presumptively never attempted.
        verdict = "NOT_DISPATCHED"
    else:
        # A dispatch was attempted but neither outcome marker was recorded, or the controls
        # did not both run. Absence of in-hand evidence is NOT evidence of backgrounding.
        verdict = "INCONCLUSIVE"

    record = verdict in ("FOREGROUND", "BACKGROUNDED")
    return (
        verdict,
        record,
        dispatch_attempted,
        result_in_hand,
        ack_only,
        control_before,
        control_after,
    )


def render(exec_file):
    parsed, note_top = parse_execution_file(exec_file)
    try:
        denials, tool_uses = collect(parsed)
    except Exception as e:
        # collect()'s recursive walk is the one path the read/summary guards do not cover.
        # A document json.loads accepts but that nests deeper than the walk's frame budget
        # raises RecursionError straight through render()/main() — under the verdict step's
        # `set -euo pipefail` that is a red step with NO verdict table, on exactly the
        # degraded run this probe exists to characterize. Route it to the existing note_top
        # -> INCONCLUSIVE floor instead, the direction every other arm already takes.
        denials, tool_uses = [], []
        note_top = (note_top + "; " if note_top else "") + (
            f"execution file could not be walked ({e.__class__.__name__})"
        )
    (verdict, record, dispatch_attempted, result_in_hand, ack_only,
     control_before, control_after) = compute_verdict(denials, tool_uses, note_top)

    if verdict == "FOREGROUND":
        decision = (
            "RECORD the harness floor as OBSERVED EFFECTIVE (issue #801) in the "
            "system overview's `prflow_implement.stall_backstop` bullet "
            "and the implement-skill reference, with this run's identifier"
        )
    elif verdict == "BACKGROUNDED":
        decision = (
            "RECORD the harness floor as OBSERVED INEFFECTIVE (issue #801) with this run's "
            "identifier — the variable did not keep the subagent in the foreground here, so "
            "early-quit prevention rests on the headless-wait prose alone; treat that as a "
            "finding to act on, not a no-op"
        )
    else:
        decision = (
            "DO NOT RECORD a verdict — the probe measured nothing conclusive; re-run it "
            "before deciding"
        )

    out = []
    out.append("## `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` harness-floor probe (issue #812)")
    out.append("")
    out.append(
        "Deterministic verdict from the execution file's recorded `tool_use` inputs and "
        "`permission_denials`. The measurement is whether the top-level session echoed the "
        "probe subagent's OWN returned marker back through Bash — harness-recorded evidence, "
        "under this probe's cooperative-model assumption, that the completed result was in "
        "hand before the turn continued. The model's text is never the measurement."
    )
    out.append("")
    out.append("> [!IMPORTANT]")
    out.append(f"> {VERSION_CAVEAT}")
    out.append("")
    if verdict == "NOT_DISPATCHED":
        out.append("> [!NOTE]")
        out.append(
            "> NOT_DISPATCHED is **presumptive**: both controls bracketed the dispatch "
            "step, but a compliant model that silently skipped it cannot be fully "
            "excluded. It is not evidence against the floor — re-run to corroborate."
        )
        out.append("")
    if verdict == "INCONCLUSIVE":
        out.append("> [!WARNING]")
        if note_top:
            out.append(f"> {note_top} — verdict INCONCLUSIVE; re-run the probe.")
        else:
            out.append(
                "> No usable outcome was recorded (dispatch_attempted={}, "
                "result_in_hand={}, ack_only={}, control_before={}, control_after={}), so "
                "an in-hand result cannot be distinguished from a skipped step — verdict "
                "INCONCLUSIVE; re-run the probe.".format(
                    "yes" if dispatch_attempted else "no",
                    "yes" if result_in_hand else "no",
                    "yes" if ack_only else "no",
                    "yes" if control_before else "no",
                    "yes" if control_after else "no",
                )
            )
        out.append("")
    out.append("| Verdict | Record it? | Evidence |")
    out.append("|---------|-----------|----------|")
    out.append(
        "| **{}** | {} | dispatch_attempted={}; result_in_hand={}; ack_only={}; "
        "control_before={}; control_after={} |".format(
            verdict,
            "yes" if record else "no",
            "yes" if dispatch_attempted else "no",
            "yes" if result_in_hand else "no",
            "yes" if ack_only else "no",
            "yes" if control_before else "no",
            "yes" if control_after else "no",
        )
    )
    out.append("")
    out.append(f"**Decision (issue #812 AC2/AC3): {decision}.**")
    out.append("")
    out.append(f"### Raw denial entries ({len(denials)})")
    out.append("")
    if denials:
        out.append("```")
        for d in denials:
            out.append(d[:400])
        out.append("```")
    else:
        out.append("_No permission_denials entries found in the execution file._")

    # Dump the recorded tool_use entries so the operator can confirm the harness's actual
    # dispatch tool name on the first live run — the name-agnostic input match above trusts
    # that the probe's token only appears via the real attempt, and this is how that
    # assumption is checked rather than assumed.
    out.append("")
    out.append(f"### Raw tool_use entries ({len(tool_uses)})")
    out.append("")
    if tool_uses:
        out.append("```")
        for t in tool_uses:
            out.append(t[:400])
        out.append("```")
    else:
        out.append("_No tool_use entries found in the execution file._")

    return "\n".join(out)


def main():
    _force_utf8_streams()
    exec_file = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EXECUTION_FILE", "")) or ""
    table = render(exec_file)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        # Best-effort side-output: an unwritable GITHUB_STEP_SUMMARY path must not raise
        # through main() and break the "Always exits 0" contract — the verdict table
        # already went to stdout (the authoritative surface).
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(table + "\n")
        except OSError as e:
            sys.stderr.write(
                "background-tasks-probe-verdict: could not append to "
                f"GITHUB_STEP_SUMMARY ({e.__class__.__name__}); verdict is on stdout\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

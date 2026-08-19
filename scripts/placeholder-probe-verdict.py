# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""placeholder-probe-verdict.py — derive the render-time placeholder precondition
verdict from a `claude-code-action` execution file (issue #1264).

Why a helper rather than inline Python in matcher-probe.yml: this verdict is a
branch-selecting core (a SUBSTITUTED_ENV_VISIBLE / SUBSTITUTED_ENV_UNSET /
NOT_SUBSTITUTED / INCONCLUSIVE selection that ROUTES THE DESIGN — a negative limb (a)
sends issue #1264 to the workflow-side composition alternative instead of the
placeholder mechanism). Inline-in-YAML it cannot be unit-tested, so a regressed arm
would silently misfire while the workflow still "runs" — the same rationale as
scripts/env-propagation-probe-verdict.py (#874), scripts/background-tasks-probe-verdict.py
(#812), and scripts/describe-denial-count.sh (PR #367).

THE PREMISE UNDER TEST. Issue #1264's selected direction is render-time injection: a
`` !`<command>` `` placeholder in a SKILL.md body is executed by Claude Code before the
model sees the skill, so the consumer prompt extension arrives with no agent decision to
skip and no Bash call for the matcher to refuse. Every figure in that issue's "Measured
facts" table came from the BARE CLI against a throwaway skill. Behavior under
`claude-code-action` — whether a placeholder in a PLUGIN-SOURCED SKILL.md is rendered at
all when the prompt is a slash command, and whether the action's `--allowed-tools`
intercedes — was never established, and per this repository's own rule only a
matcher-probe dispatch settles it.

THE THREE LIMBS, MEASURED BY ONE LINE. The probe skill carries a single placeholder,
`` !`.github/probe-plugin/phprobe-read-env.sh` `` (a bare script path — see the redesign
recorded below, which moved the shell expansion out of the command text):

  (a) substitution — output present at all;
  (b) environment  — the value carried is the job's step-level sentinel;
  (c) allowlist    — ANSWERED NEGATIVE and no longer live. While it was open the head was
                     deliberately withheld, and rendering was refused (run 31058504896,
                     `This command requires approval`). The head is granted now, which is
                     what makes (a) and (b) observable at all.

ALREADY ESTABLISHED, AND IT CONTRADICTS THE ISSUE. Run 31058109064 refused the probe's
first placeholder shape outright, recording on the Skill tool_result: `Shell command
permission check failed for pattern "…": Contains expansion`. So render-time placeholders
ARE permission-checked under `claude-code-action`, where issue #1264's bare-CLI table
records "Injection gated by the permission/allowlist system: No". The refusal surfaced as
a tool_result error with `permission_denials_count: 0` and a successful run — silent,
which is the class #1264 exists to fight. The shell expansion therefore moved out of the
command text into `.github/probe-plugin/phprobe-read-env.sh`, leaving a bare literal path
for the static check to accept; that redesign is what makes limb (a) reachable at all.

That original construction — measure (c) by withholding the grant — worked, and answered
it in the negative. The consequence is that (a) and (b) were UNREACHABLE until the head was
granted: four consecutive runs were refused before substitution could ever be observed. So
a SUBSTITUTED_* verdict from this probe as it now stands says nothing about (c), and the
reason strings below say so explicitly rather than leaving a reader to infer it.

HOW IT IS MADE MEASURABLE. The rendered body is not itself a tool call, so the probe
borrows the #812/#874 technique: the agent ECHOES BACK what it sees on the placeholder
line through its own Bash call, and that recorded `tool_use` is the evidence. The model's
prose is never the measurement.

WHAT THIS PROBE DOES NOT ESTABLISH. It measures a throwaway plugin's skill reached by a
slash-command prompt, not `skills/review/SKILL.md` or `skills/implement/SKILL.md` under a
real run's step ordering; and it rests on a cooperative model faithfully echoing what it
saw. Read the verdict as evidence, not proof; the raw tool_use dump below is what an
operator confirms it against.

Always exits 0: a red verdict step with no table is the worst outcome on exactly the
degraded run this probe exists to characterize.
"""

import json
import os
import re
import sys

def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# The sentinel the workflow puts in the step-level env:. Deliberately not a plausible
# real path — a match cannot be confused with an incidental mention of a real directory.
SENTINEL = "DEVFLOW_PHPROBE_SENTINEL_1264"
MARKER = "PHPROBE_ENV"
LINE_ABSENT = "PHPROBE_LINE_A_ABSENT"
# The fixed token Action 2 puts in front of its echo-back. It is what makes an entry
# IDENTIFIABLE as the measurement rather than as some other command that happens to
# mention a fragment — the scoping the incidental-mention guard rests on.
SAW = "PHPROBE_SAW"
# The two controls prove the session reached and passed the measured action. Without
# them a run that never started reads identically to one where nothing substituted.
CONTROL_BEFORE = "PHPROBE_SKILL_REACHED"
CONTROL_AFTER = "PHPROBE_CONTROL_AFTER"

# Limb (a) is NEGATIVE only when the echo-back carries the placeholder in its UNEXECUTED
# form. Matching the raw shape rather than "absence of the marker" is the whole guard: an
# absence test would read an unsubstituted line as INCONCLUSIVE and lose the routing signal
# issue #1264 needs. Neither fragment can survive substitution — the script's stdout is one
# `PHPROBE_ENV <value>` line that names neither its own path nor the backtick-bang syntax.
_UNEXECUTED_FRAGMENTS = ("phprobe-read-env.sh", "!`")

# A value is OBSERVED only if it is one the probe can actually produce. The agent's own
# instruction text carries the marker in template form, so a bare-substring test would
# report a measurement from the command that merely ASKS for one — the unknown-is-not-zero
# collapse the arm ordering below exists to prevent.
_OBSERVED = {SENTINEL, "UNSET"}


def _marker_values(tool_uses):
    """Return the set of OBSERVED values recorded after the marker.

    Matches `PHPROBE_ENV <token>` and keeps only tokens the probe can produce. The
    `%s` template and the unexecuted `${DEVFLOW_...}` form both yield nothing."""
    pat = re.compile(re.escape(MARKER) + r"\s+([^\s\"'\\]+)")
    return {v for t in tool_uses if SAW in t for v in pat.findall(t)} & _OBSERVED


def _has_unexecuted_form(tool_uses):
    """True when a recorded entry carries the placeholder's unexecuted command text.

    Scoped to the SAW-prefixed echo-back, so an incidental mention of the script path in
    some unrelated command cannot fabricate a NOT_SUBSTITUTED verdict. The scoping token
    replaces the older marker co-occurrence test, which no longer works: the unexecuted
    form is now a bare script path that does not carry the marker at all."""
    return any(
        SAW in t and any(frag in t for frag in _UNEXECUTED_FRAGMENTS) for t in tool_uses
    )


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


def collect_results(parsed):
    """Walk the parsed structure and return recorded tool_result entries as text.

    DIAGNOSTIC ONLY — never an operand of the verdict, which rests on tool_use records
    exactly as its siblings do. This exists because the probe's first two runs were both
    INCONCLUSIVE for DIFFERENT reasons, and the second one (a recorded Skill tool_use with
    no following actions) could not be diagnosed from tool_use records alone: what the
    Skill call RETURNED is the discriminator between "the skill loaded and the model
    ignored it" and "the skill invocation failed or aborted". Printing it turns the next
    INCONCLUSIVE into a diagnosis rather than another paid re-run."""
    results = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "tool_result":
                content = o.get("content")
                if not isinstance(content, str):
                    content = json.dumps(content)
                results.append(
                    ("ERROR " if o.get("is_error") else "") + content
                )
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(parsed)
    return results


def compute_verdict(tool_uses, note_top):
    """Return (verdict, reason, record_it, routes_to_placeholder).

    `routes_to_placeholder` is the decision issue #1264's precondition asks for: True
    only when every limb came back positive. Any other outcome — including every
    degraded one — leaves the placeholder design unproven, and the issue's own rule
    routes the work to workflow-side composition on a negative limb."""
    values = _marker_values(tool_uses)
    env_visible = SENTINEL in values
    reported = bool(values)
    unexecuted = _has_unexecuted_form(tool_uses)
    absent = any(LINE_ABSENT in t for t in tool_uses)
    before = any(CONTROL_BEFORE in t for t in tool_uses)
    after = any(CONTROL_AFTER in t for t in tool_uses)

    # Ordered, and the degraded arms come FIRST. A measurement that did not run must
    # never be read as a measurement that came back negative — collapsing "we could not
    # look" onto "it does not substitute" is the fail-open this ordering exists to stop.
    if note_top:
        return (
            "INCONCLUSIVE",
            "the execution file could not be read cleanly: " + note_top,
            False,
            False,
        )
    if not tool_uses:
        return (
            "INCONCLUSIVE",
            "no tool_use entries were recorded, so nothing was measured",
            False,
            False,
        )
    if not (before and after):
        return (
            "INCONCLUSIVE",
            "the session did not record both positive controls (%s=%s, %s=%s), so it may "
            "not have reached or completed the measured action. NOTE: a missing %s is the "
            "expected shape of the zero-turn ABORT hazard — an injected command exiting "
            "non-zero aborts the invocation before the model sees the body — but this probe's "
            "injected head, .github/probe-plugin/phprobe-read-env.sh, always exits 0 (the "
            "suite asserts it), so an abort here points at the harness rather than at the "
            "command"
            % (CONTROL_BEFORE, before, CONTROL_AFTER, after, CONTROL_BEFORE),
            False,
            False,
        )
    # Limb (a) negative: the placeholder survived verbatim into the rendered body.
    # This is a REAL measurement, not a degraded one — it settles the precondition
    # negatively and routes issue #1264 to workflow-side composition.
    if unexecuted:
        return (
            "NOT_SUBSTITUTED",
            "the echo-back carried the placeholder's UNEXECUTED command text, so "
            "claude-code-action did not render a `!` placeholder in a plugin-sourced "
            "SKILL.md reached by a slash-command prompt. Limb (a) is NEGATIVE: route "
            "issue #1264 to the workflow-side composition alternative",
            True,
            False,
        )
    if absent:
        return (
            "INCONCLUSIVE",
            "the agent reported the placeholder line as absent from the body entirely, "
            "which is neither substitution nor non-substitution — the skill may not have "
            "loaded as authored",
            False,
            False,
        )
    if not reported:
        return (
            "INCONCLUSIVE",
            "the echo-back recorded no observable value, so substitution is unestablished "
            "rather than negative",
            False,
            False,
        )
    if env_visible:
        return (
            "SUBSTITUTED_ENV_VISIBLE",
            "the placeholder was substituted AND carried the step-level sentinel. Limb (a) "
            "POSITIVE: a `!` placeholder in a plugin-sourced SKILL.md IS rendered under a "
            "slash-command prompt. Limb (b) POSITIVE: the injected command sees "
            "DEVFLOW_PROMPT_EXTENSION_ROOT through $GITHUB_ENV, so render-time injection can "
            "inherit the #874 trusted base-ref closure. Limb (c) is NOT cleared by this run "
            "and must not be read as such: it was measured separately and came back NEGATIVE "
            "(run 31058504896 — `This command requires approval`; run 31058109064 — `Contains "
            "expansion`), so rendering IS gated under claude-code-action, by static shape "
            "analysis AND by --allowed-tools. This run reached substitution only because the "
            "placeholder head is granted. The mechanism therefore works, subject to a design "
            "constraint issue #1264 does not yet state: the injected wrapper must carry a "
            "statically-analyzable command shape (no `${...}` expansion) and its head must be "
            "granted in the resolved --allowed-tools of every tier that renders it",
            True,
            True,
        )
    # Substituted, but the sentinel did not reach the injected command.
    return (
        "SUBSTITUTED_ENV_UNSET",
        "the placeholder was substituted and ran an ungranted head — limbs (a) and (c) "
        "positive — but the injected command saw DEVFLOW_PROMPT_EXTENSION_ROOT as UNSET. "
        "Limb (b) is NEGATIVE: render-time injection works, but it cannot inherit the "
        "trusted base-ref closure this way, so the wrapper would resolve the repo-root "
        "path instead",
        True,
        False,
    )


def main(argv):
    _force_utf8_streams()
    exec_file = argv[1] if len(argv) > 1 else ""
    parsed, note_top = parse_execution_file(exec_file)
    tool_uses = collect(parsed)
    verdict, reason, record_it, routes = compute_verdict(tool_uses, note_top)

    print("=" * 72)
    print("issue #1264 precondition — render-time placeholder probe")
    print("=" * 72)
    print("VERDICT: %s" % verdict)
    print("REASON : %s" % reason)
    print("RECORD IN #1264 THREAD: %s" % ("yes" if record_it else "no — re-run the probe"))
    print(
        "ROUTES TO: %s"
        % (
            "the placeholder mechanism (selected direction)"
            if routes
            else "workflow-side composition, or a re-run — NOT the placeholder mechanism"
        )
    )
    print("-" * 72)
    print("recorded tool_use entries (%d):" % len(tool_uses))
    for t in tool_uses:
        print("  " + t[:400])
    results = collect_results(parsed)
    print("-" * 72)
    print("recorded tool_result entries (%d) — diagnostic only, never a verdict operand:"
          % len(results))
    for r in results:
        print("  " + r[:600].replace("\n", " | "))
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

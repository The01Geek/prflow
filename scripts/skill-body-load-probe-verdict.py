# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""skill-body-load-probe-verdict.py — derive, per engine root, whether the Skill
tool delivered that root's `SKILL.md` body WHOLE from a `claude-code-action`
execution file (issue #1618).

WHY A HELPER, NOT INLINE YAML. The verdict is derived from the body record the
execution file itself carries — never the model's own account of what it received
— and that derivation is a branch-selecting core (delivered-whole vs short-delivery
vs unestablished per root). Inline in matcher-probe.yml it could not be unit-tested,
so a regressed arm would silently misfire while the workflow still "runs" — the same
rationale as scripts/placeholder-probe-verdict.py (#1264) and its siblings.

THE OPERAND. A `claude-code-action` session with `show_full_output: true` records
each `Skill` tool_use, its paired tool_result, and — in the NEXT record — the body.
The tool_result is a launch stub (`Launching skill: <name>`, ~30 bytes) and is NOT the
body; the rendered body arrives as the following user-role text block, which opens with
a `Base directory for this skill: <dir>` line and continues with the file minus its YAML
frontmatter (the transformation docs/internal/skill-body-load-delivery.md records). This
helper therefore joins each Skill tool_use to that following body record.
Reading that body and checking it against controls read FROM DISK at verdict time is an
observation, not testimony. Measuring the stub instead can only ever yield short-delivery.

DISAMBIGUATION IS TWO-STAGE, and neither stage substitutes for the other. A root is first
bound to its own recorded LOAD by the name's quoted JSON form, so a longer name containing
it cannot claim it and a root matching several loads resolves to none of them; the body is
then selected within that load's window by BASE DIRECTORY, so another skill's body is never
adjudicated as this root's. Every ambiguity is `unestablished` naming the ambiguity — a
silently-kept first match is the failure this ordering exists to prevent.

THE CONTROLS ARE READ FROM DISK, so the helper cannot drift from the shipped file. Two
controls per root: the file's last non-empty line (tail) and a distinctive interior
line (mid). A body delivered whole carries both. Tail absent → the tail was lost; tail
present but mid absent → an interior loss; a truncation/cap notice in the content →
short delivery. This detects a lost tail and one interior point, NOT an arbitrary
middle elision — the same failure-geometry limit the delivery record discloses.

EMPTY SELECTION IS NOT A CLEAN PASS. An invocation naming no root audits nothing; that
is a workflow-authoring error, so it exits non-zero rather than printing an all-clear —
an audit that audited nothing must not read as an audit that found nothing.

Degraded arms come FIRST and every per-root degraded outcome is `unestablished`, never
`delivered-whole`. The arms, complete by construction, in evaluation order: the execution
file unreadable, unparseable or only partly parseable; the root not resolving to exactly
one recorded load (none matched its name, or several did — one arm, two causes, and the
reason says which); a matching load with no paired result; a load that returned an error;
no following body record naming the root's own directory; and the on-disk controls
unreadable. Each is unknown, not whole. The process exits 0 on every
execution-file outcome (a red verdict on a degraded run is exactly what this probe
exists to characterize); only the no-roots usage error exits non-zero.
"""

import argparse
import json
import os
import sys


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# A cap/truncation notice in the returned body is a positive short-delivery signal,
# independent of the controls: the loader told us it clipped.
_TRUNCATION_MARKERS = ("showing lines ", "cap 25000", "… (truncated)", "[truncated]")


def strip_leading_comments(raw):
    """Drop a LEADING run of blank and `#`-prefixed lines, returning the remainder.

    The published `claude-execution-transcript-*` artifact is the in-workflow execution
    file with one `# DEVFLOW SCRUB CAVEAT:` line prepended by scripts/scrub-transcript.sh,
    which breaks strict JSON. Only the leading run is stripped, so a `#` inside the JSON
    payload — or at the start of a JSONL record — is left untouched."""
    lines = raw.splitlines(True)
    idx = 0
    while idx < len(lines):
        s = lines[idx].strip()
        if s and not s.startswith("#"):
            break
        idx += 1
    return "".join(lines[idx:])


def parse_execution_file(exec_file):
    """Return (parsed, note_top). parsed is a JSON value — an empty list on every
    failure path, so callers need no None-guard — and note_top is a non-empty
    diagnostic when the file was absent/empty/unparseable/partially corrupt, which
    forces every root to `unestablished`."""
    if not (exec_file and os.path.isfile(exec_file)):
        return [], "execution file path absent or not a regular file at '%s'" % exec_file
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        return [], "execution file present but unreadable (%s)" % e.__class__.__name__
    # Upstream of BOTH parse paths: moving this inside the json.loads branch leaves the
    # published artifact's caveat line on every JSONL record and drops the whole file.
    raw = strip_leading_comments(raw)
    try:
        return json.loads(raw), ""
    except Exception:
        pass
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


_BODY_PREFIX = "Base directory for this skill: "


def body_base_dir(text):
    """The `<dir>` of a body record's opening `Base directory for this skill: <dir>` line."""
    return text.split("\n", 1)[0][len(_BODY_PREFIX):].strip()


def dirs_match(a, b):
    """True when two directory paths name the same skill directory.

    A body record carries the runner's ABSOLUTE base directory while `--root` is normally
    repo-relative, so equality alone would never match; the comparison is therefore a
    component-boundary suffix in either direction. Matching on a bare suffix without the
    separator would let a `.../myskills/review` directory satisfy a `skills/review` root.

    Separators are normalised AFTER `normpath`, never before: on a host whose `os.path` is
    `ntpath`, `normpath` re-inserts the backslashes an earlier cleanup removed, so the
    suffix test below could not match and every root read `unestablished` there."""
    # Test emptiness BEFORE normalising: normpath maps "" to ".", so a guard placed after it
    # can never fire and a body record with a blank base directory matches a bare root.
    if not a.strip() or not b.strip():
        return False
    a = os.path.normpath(a).replace("\\", "/").rstrip("/")
    b = os.path.normpath(b).replace("\\", "/").rstrip("/")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def collect_skill_pairs(parsed):
    """Return the recorded Skill loads, each joined to the body record that follows it.

    Each pair is a dict: {input_text, is_error, has_result, bodies}. tool_use
    and tool_result are joined on the id/tool_use_id — that pairing establishes only that a
    load happened and whether it errored, since the tool_result is a launch stub. `bodies`
    is the ordered list of {base_dir, text} body records appearing after this Skill tool_use
    and before the next one, which is where the rendered body actually arrives; the caller
    selects among them by base directory. A Skill tool_use with no paired result (the
    invocation was recorded but nothing came back) is kept with has_result=False, so it
    reads as unestablished rather than being silently dropped."""
    events = []  # ordered ("use"|"result"|"body", payload) in document order

    def walk(o, role):
        if isinstance(o, dict):
            if isinstance(o.get("role"), str):
                role = o["role"]
            t = o.get("type")
            if t == "tool_use" and o.get("name") == "Skill":
                events.append(("use", (o.get("id"), json.dumps(o.get("input")))))
            elif t == "tool_result":
                tid = o.get("tool_use_id")
                if tid is not None:
                    # Record the result's PRESENCE and error flag only. Capturing its content
                    # would reintroduce the launch stub as a measurable operand — the defect
                    # this helper exists to fix.
                    events.append(("result", (tid, bool(o.get("is_error")))))
            elif (t == "text" and role == "user" and isinstance(o.get("text"), str)
                    and o["text"].startswith(_BODY_PREFIX)):
                # Role-gated: an assistant message quoting the prefix is not a delivery.
                events.append(("body", (body_base_dir(o["text"]), o["text"])))
            for v in o.values():
                walk(v, role)
        elif isinstance(o, list):
            for it in o:
                walk(it, role)

    walk(parsed, None)

    results = {}
    for kind, payload in events:
        if kind == "result":
            results[payload[0]] = payload[1]

    use_positions = [i for i, (kind, _) in enumerate(events) if kind == "use"]
    pairs = []
    for n, pos in enumerate(use_positions):
        uid, input_text = events[pos][1]
        stop = use_positions[n + 1] if n + 1 < len(use_positions) else len(events)
        bodies = [
            {"base_dir": payload[0], "text": payload[1]}
            for kind, payload in events[pos + 1:stop] if kind == "body"
        ]
        pairs.append(
            {"input_text": input_text,
             "is_error": results.get(uid, False),
             "has_result": uid in results,
             "bodies": bodies}
        )
    return pairs


def read_controls(path):
    """Return (tail, mid) controls from the on-disk file, or (None, None) if unreadable.

    tail is the file's last non-empty stripped line; mid is a distinctive interior line
    (>= 20 chars) nearest the file's midpoint. Read at verdict time, so the controls
    track the shipped file rather than a hardcoded literal."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh]
    except OSError:
        return None, None
    nonempty = [ln.strip() for ln in lines if ln.strip()]
    if not nonempty:
        return None, None
    tail = nonempty[-1]
    mid = None
    n = len(nonempty)
    center = n // 2
    # Walk outward from the centre for the first line long enough to be distinctive.
    for offset in range(n):
        for idx in (center + offset, center - offset):
            if 0 <= idx < n and len(nonempty[idx]) >= 20 and nonempty[idx] != tail:
                mid = nonempty[idx]
                break
        if mid is not None:
            break
    return tail, mid


def _pairs_for_root(skill_name, pairs):
    """Every Skill pair whose recorded tool_use input names this skill.

    Matched on the name's JSON string form — the surrounding quote marks included — so a
    longer name that merely contains this one cannot claim this root's load. The quote marks
    are the boundary because `collect_skill_pairs` serialises the whole recorded input to
    JSON rather than reading a named field, so a complete string value inside it is
    quote-delimited whatever its field is called. Do not narrow this to a named field: one
    committed transcript records one, but that is a dated observation of one runner version,
    and a field-keyed read silently stops measuring if the name ever differs — every real
    reading answers `unestablished` while every fixture built on the assumed name stays
    green, so the divergence is unfalsifiable from inside the suite.

    Every match is returned rather than the first, because keeping one of several silently
    discards a real ambiguity; the caller decides on the count."""
    needle = json.dumps(skill_name)
    return [p for p in pairs if needle in p["input_text"]]


def root_dir_for(path):
    """The skill directory a `--root` path names — the value a body record's base dir is
    compared against, and the value the no-body reason reports."""
    return os.path.dirname(path) or "."


def _body_for_root(pair, path):
    """The body record delivered for this root's SKILL.md, or None.

    Selected by base directory rather than by position, so a session that loaded several
    skills cannot have another skill's body adjudicated as this root's."""
    root_dir = root_dir_for(path)
    for b in pair["bodies"]:
        if dirs_match(b["base_dir"], root_dir):
            return b
    return None


def verdict_for_root(skill_name, path, pairs, note_top):
    """Return (verdict, reason) for one engine root. Degraded arms first."""
    if note_top:
        return "unestablished", "execution file could not be read cleanly: " + note_top
    matches = _pairs_for_root(skill_name, pairs)
    if not matches:
        return "unestablished", (
            "no recorded Skill tool_use names %s, so nothing bound this root — the skill was "
            "not invoked, it was refused before any body returned, or a load was recorded in "
            "a shape this match cannot read (an input carrying the name outside a JSON string "
            "value). %d Skill load(s) were recorded in total" % (skill_name, len(pairs))
        )
    if len(matches) > 1:
        return "unestablished", (
            "%d recorded Skill loads name %s, so this root resolves to no single load — the "
            "ambiguity is what could not be measured, not any one of those loads (a retried "
            "load, or an argument string equal to this root's name)" % (len(matches), skill_name)
        )
    pair = matches[0]
    if not pair["has_result"]:
        return "unestablished", (
            "a Skill tool_use for %s was recorded but no tool_result was paired to it, "
            "so nothing was delivered to measure" % skill_name
        )
    if pair["is_error"]:
        return "unestablished", (
            "the Skill load of %s returned an error tool_result (refused or aborted), so "
            "no body was delivered — the abort mode, not a truncation" % skill_name
        )
    body_rec = _body_for_root(pair, path)
    if body_rec is None:
        return "unestablished", (
            "the Skill load of %s was recorded but no following body record naming its own "
            "directory (%r) was found, so no delivered body could be located to measure — "
            "the paired tool_result is a launch stub, not the body"
            % (skill_name, root_dir_for(path))
        )
    body = body_rec["text"]
    tail, mid = read_controls(path)
    if tail is None:
        return "unestablished", (
            "the on-disk file %s could not be read for controls, so the delivered body "
            "cannot be checked against it" % path
        )
    for marker in _TRUNCATION_MARKERS:
        if marker in body:
            return "short-delivery", (
                "the delivered body carried a truncation/cap notice (%r), so the Skill tool "
                "clipped %s" % (marker, skill_name)
            )
    if tail not in body:
        return "short-delivery", (
            "the delivered body did NOT contain the file's last non-empty line, so the tail "
            "of %s was lost (for the review root the tail is the routing/verdict-emitter "
            "region)" % skill_name
        )
    if mid is not None and mid not in body:
        return "short-delivery", (
            "the delivered body contained the tail control but NOT the interior control, so "
            "%s lost content before its final line" % skill_name
        )
    return "delivered-whole", (
        "the delivered Skill body record for %s contained the file's last non-empty line %s; "
        "no truncation/cap notice was present. This detects a lost tail and one interior "
        "point, NOT an arbitrary middle elision"
        % (skill_name,
           "and a distinctive interior line" if mid is not None
           else "(the file offered no distinctive interior line, so only the tail was checked)")
    )


def audit(exec_file, roots):
    """Return (exit_code, lines) for the whole audit. roots is a list of (name, path)."""
    lines = []
    if not roots:
        lines.append("AUDIT: NO-ROOTS")
        lines.append(
            "REASON: no --root was supplied, so this run audited nothing. An audit that "
            "audited nothing is not a clean pass — exiting non-zero."
        )
        return 2, lines

    parsed, note_top = parse_execution_file(exec_file)
    pairs = collect_skill_pairs(parsed)
    lines.append("AUDIT: audited %d root(s)" % len(roots))
    if note_top:
        lines.append("NOTE: " + note_top)
    lines.append("recorded Skill tool_use pairs: %d" % len(pairs))
    for name, path in roots:
        verdict, reason = verdict_for_root(name, path, pairs, note_top)
        lines.append("-" * 72)
        lines.append("ROOT   : %s (%s)" % (name, path))
        lines.append("VERDICT: %s" % verdict)
        lines.append("REASON : %s" % reason)
    return 0, lines


def _parse_root(spec):
    """`prflow:review=skills/review/SKILL.md` -> ('prflow:review', 'skills/review/SKILL.md')."""
    name, sep, path = spec.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(
            "root spec must be NAME=PATH, got %r" % spec
        )
    return name, path


def main(argv):
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("execution_file", nargs="?", default="")
    ap.add_argument("--tier", default="")
    ap.add_argument("--root", action="append", default=[], type=_parse_root,
                    help="NAME=PATH mapping a Skill name to its on-disk SKILL.md")
    ap.add_argument("--ref", default="")
    ap.add_argument("--head-commit", default="")
    args = ap.parse_args(argv[1:])

    exit_code, lines = audit(args.execution_file, args.root)

    print("=" * 72)
    print("issue #1618 — Skill-tool body-delivery probe%s"
          % (" (tier: %s)" % args.tier if args.tier else ""))
    if args.ref or args.head_commit:
        print("ref: %s  head: %s" % (args.ref, args.head_commit))
    print("=" * 72)
    for ln in lines:
        print(ln)
    print("=" * 72)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))

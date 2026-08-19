# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""skill-body-load-probe-verdict.py — derive, per engine root, whether the Skill
tool delivered that root's `SKILL.md` body WHOLE from a `claude-code-action`
execution file (issue #1618).

WHY A HELPER, NOT INLINE YAML. The verdict is derived from the Skill `tool_result`
recorded in the execution file — never the model's own account of what it received
— and that derivation is a branch-selecting core (delivered-whole vs short-delivery
vs unestablished per root). Inline in matcher-probe.yml it could not be unit-tested,
so a regressed arm would silently misfire while the workflow still "runs" — the same
rationale as scripts/placeholder-probe-verdict.py (#1264) and its siblings.

THE OPERAND. A `claude-code-action` session with `show_full_output: true` records
each `Skill` tool_use and its paired tool_result. When the loaded skill is an engine
root, the tool_result content is the rendered body — the file minus its YAML
frontmatter, with a `Base directory for this skill:` line prepended (the transformation
docs/internal/skill-body-load-delivery.md records). Reading that content and checking
it against controls read FROM DISK at verdict time is an observation, not testimony.

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
`delivered-whole`: a body that was never loaded, a load that errored, an unreadable or
wrong-shape execution file are each unknown, not whole. The process exits 0 on every
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


def collect_skill_pairs(parsed):
    """Return the recorded Skill tool_use→tool_result pairs.

    Each pair is a dict: {input_text, result_text, is_error, has_result}. tool_use and
    tool_result are joined on the id/tool_use_id. A Skill tool_use with no paired
    result (the invocation was recorded but nothing came back) is kept with
    has_result=False, so it reads as unestablished rather than being silently dropped."""
    uses = {}   # id -> input_text
    results = {}  # tool_use_id -> (is_error, content_text)

    def content_text(content):
        if isinstance(content, str):
            return content
        return json.dumps(content)

    def walk(o):
        if isinstance(o, dict):
            t = o.get("type")
            if t == "tool_use" and o.get("name") == "Skill":
                uses[o.get("id")] = json.dumps(o.get("input"))
            elif t == "tool_result":
                tid = o.get("tool_use_id")
                if tid is not None:
                    results[tid] = (bool(o.get("is_error")), content_text(o.get("content")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(parsed)

    pairs = []
    for uid, input_text in uses.items():
        if uid in results:
            is_error, content = results[uid]
            pairs.append(
                {"input_text": input_text, "result_text": content,
                 "is_error": is_error, "has_result": True}
            )
        else:
            pairs.append(
                {"input_text": input_text, "result_text": "",
                 "is_error": False, "has_result": False}
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


def _pair_for_root(skill_name, pairs):
    """The Skill pair whose tool_use input names this skill, or None."""
    for p in pairs:
        if skill_name in p["input_text"]:
            return p
    return None


def verdict_for_root(skill_name, path, pairs, note_top):
    """Return (verdict, reason) for one engine root. Degraded arms first."""
    if note_top:
        return "unestablished", "execution file could not be read cleanly: " + note_top
    pair = _pair_for_root(skill_name, pairs)
    if pair is None:
        return "unestablished", (
            "no Skill tool_use naming %s was recorded — the body was never loaded by "
            "this channel (skill not invoked, or refused before any body returned)" % skill_name
        )
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
    body = pair["result_text"]
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
            "of %s was lost — the routing/verdict-emitter region for the review root" % skill_name
        )
    if mid is not None and mid not in body:
        return "short-delivery", (
            "the delivered body contained the tail control but NOT the interior control, so "
            "%s lost content before its final line" % skill_name
        )
    return "delivered-whole", (
        "the delivered Skill tool_result for %s contained both the file's last non-empty "
        "line and a distinctive interior line; no truncation/cap notice was present. This "
        "detects a lost tail and one interior point, NOT an arbitrary middle elision" % skill_name
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

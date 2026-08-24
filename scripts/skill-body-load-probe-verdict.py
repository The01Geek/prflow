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
line (mid). The verdict vocabulary is exactly four values, complete by construction:
delivered-whole (both controls present), short-delivery (a truncation/cap notice, or one
control lost while the other survives), no-body (NEITHER control present — a body-less
result such as the documented already-loaded short note), and unestablished (a degraded
execution file). The no-body arm is ordered ahead of the tail-loss arm so a body-less
result is not misread as a lost tail. This detects a lost tail and one interior point,
NOT an arbitrary middle elision — the same failure-geometry limit the delivery record
discloses.

PER-ROOT DIAGNOSTICS. Each root also reports how much of the body arrived and where it
first diverged — the delivered length (Python len), the first-divergence offset (a
longest-common-prefix scan of the delivered body, its prepended base-directory line
skipped, against the on-disk file with its YAML frontmatter removed), and a present/absent
result for each control — plus whether the SKILL.md the Skill tool served (named on the
delivered body's `Base directory for this skill:` line) is byte-identical to the checkout
control file (identical | differing | unreadable). A short-delivery that is really a copy
mismatch is then visible in the log rather than indistinguishable from a truncation.

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
        # claude-code-action records a tool_result's content as a list of blocks, e.g.
        # [{"type": "text", "text": "<body>"}]. Reconstruct the delivered text by joining the
        # text blocks so the raw on-disk controls substring-match the delivered body — a
        # json.dumps of the list would JSON-escape the body and a control line carrying a
        # quote/backslash/newline would then fail to match a genuinely-whole delivery. Fall
        # back to a JSON dump only for a shape carrying no text blocks.
        if isinstance(content, list):
            texts = [
                b["text"] for b in content
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            ]
            if texts:
                return "".join(texts)
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


# The prepended line the Skill tool puts in place of the removed YAML frontmatter, naming
# the directory it served the body from. read here to (a) skip it before the offset scan and
# (b) locate the served copy for the byte-comparison.
_BASE_DIR_PREFIX = "Base directory for this skill:"


def _read_text(path):
    """Return the on-disk file text, or None if unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _controls_from_lines(lines):
    """Return (tail, mid) controls from already-read lines, or (None, None) if none.

    tail is the last non-empty stripped line; mid is a distinctive interior line
    (>= 20 chars) nearest the midpoint."""
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


def read_controls(path):
    """Return (tail, mid) controls from the on-disk file, or (None, None) if unreadable.
    Read at verdict time, so the controls track the shipped file rather than a hardcoded
    literal."""
    text = _read_text(path)
    if text is None:
        return None, None
    return _controls_from_lines(text.split("\n"))


def _strip_frontmatter(text):
    """Return text with a leading YAML frontmatter block (a `---` line, its keys, a closing
    `---` line) removed. The delivered body carries no frontmatter, so the on-disk file is
    compared against it frontmatter-first-removed. Unchanged when there is no leading block."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])
    return text  # no closing marker — treat as no frontmatter rather than eating the body


def _base_dir_from_body(body):
    """Return the directory named on the delivered body's first-non-empty
    `Base directory for this skill:` line, or None when that line is absent.

    First-non-empty-line only: an engine root's own prose quotes the phrase (the portable
    helper-anchor rule), so scanning the whole body would match that prose, not the prepended
    line the Skill tool actually served."""
    for ln in body.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith(_BASE_DIR_PREFIX):
            return s[len(_BASE_DIR_PREFIX):].strip()
        return None
    return None


def _skip_base_dir_line(body):
    """Return the delivered body with its prepended base-directory line removed, so the
    offset scan compares like against like (the on-disk text has no such line)."""
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        if ln.strip().startswith(_BASE_DIR_PREFIX):
            return "\n".join(lines[i + 1:])
        return body
    return body


def _lcp_len(a, b):
    """Length of the longest common prefix of a and b — the first position at which they
    diverge. Two identical strings return their shared length, so a whole delivery reports an
    offset equal to the delivered text's length rather than a false divergence."""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _copy_comparison(body, checkout_path):
    """Return (outcome, reason) comparing the SKILL.md the Skill tool served (at the delivered
    body's base-directory line) against the checkout file the controls were read from. Outcomes
    are exactly identical | differing | unreadable, complete by construction. Reads the served
    copy from the base-directory line — never the checkout file twice — so a copy mismatch is
    what this comparison is able to detect."""
    base_dir = _base_dir_from_body(body)
    if base_dir is None:
        return "unreadable", (
            "the delivered body carried no '%s' line, so the directory the Skill tool served "
            "the body from could not be identified" % _BASE_DIR_PREFIX
        )
    served_path = os.path.join(base_dir, "SKILL.md")
    try:
        with open(served_path, "rb") as fh:
            served_bytes = fh.read()
    except OSError as e:
        return "unreadable", (
            "the served skill file %s could not be read (%s), so it could not be compared "
            "against the checkout control file" % (served_path, e.__class__.__name__)
        )
    try:
        with open(checkout_path, "rb") as fh:
            checkout_bytes = fh.read()
    except OSError as e:
        return "unreadable", (
            "the checkout control file %s could not be read (%s)" % (checkout_path, e.__class__.__name__)
        )
    if served_bytes == checkout_bytes:
        return "identical", (
            "the SKILL.md the Skill tool served (%s) is byte-identical to the checkout file the "
            "controls were read from" % served_path
        )
    return "differing", (
        "the SKILL.md the Skill tool served (%s) DIFFERS from the checkout control file %s, so a "
        "short-delivery verdict here may reflect a copy mismatch rather than a truncation"
        % (served_path, checkout_path)
    )


def _present_str(v):
    """Render a present/absent control flag, or the unestablished case (no body delivered)."""
    if v is None:
        return "unestablished (no body delivered)"
    return "present" if v else "absent"


def _pair_for_root(skill_name, pairs):
    """The Skill pair whose tool_use input names this skill, or None."""
    for p in pairs:
        if skill_name in p["input_text"]:
            return p
    return None


def _unestablished_report(reason):
    """A per-root report whose every measured field is unknown (no body to measure)."""
    return {
        "verdict": "unestablished",
        "reason": reason,
        "length": None,
        "first_divergence": None,
        "tail_present": None,
        "interior_present": None,
        "copy_outcome": None,
        "copy_reason": "",
    }


def report_for_root(skill_name, path, pairs, note_top):
    """Return a per-root report dict — verdict, reason, and the diagnostic fields
    (length, first_divergence, tail_present, interior_present, copy_outcome, copy_reason).
    Degraded arms come first and each is `unestablished`; the verdict vocabulary is exactly
    delivered-whole | short-delivery | no-body | unestablished, complete by construction."""
    if note_top:
        return _unestablished_report("execution file could not be read cleanly: " + note_top)
    pair = _pair_for_root(skill_name, pairs)
    if pair is None:
        return _unestablished_report(
            "no Skill tool_use naming %s was recorded — the body was never loaded by "
            "this channel (skill not invoked, or refused before any body returned)" % skill_name
        )
    if not pair["has_result"]:
        return _unestablished_report(
            "a Skill tool_use for %s was recorded but no tool_result was paired to it, "
            "so nothing was delivered to measure" % skill_name
        )
    if pair["is_error"]:
        return _unestablished_report(
            "the Skill load of %s returned an error tool_result (refused or aborted), so "
            "no body was delivered — the abort mode, not a truncation" % skill_name
        )

    # Compute length and the copy comparison BEFORE the on-disk-unreadable early return below —
    # moving them after it would drop both fields on that arm, and the report must still carry
    # every field there (issue #1893).
    body = pair["result_text"]
    length = len(body)
    copy_outcome, copy_reason = _copy_comparison(body, path)

    disk_text = _read_text(path)
    tail, mid = (None, None) if disk_text is None else _controls_from_lines(disk_text.split("\n"))
    if tail is None:
        rep = _unestablished_report(
            "the on-disk file %s could not be read for controls, so the delivered body "
            "cannot be checked against it" % path
        )
        rep["length"] = length
        rep["copy_outcome"] = copy_outcome
        rep["copy_reason"] = copy_reason
        return rep

    delivered_body = _skip_base_dir_line(body)
    disk_body = _strip_frontmatter(disk_text)
    first_divergence = _lcp_len(delivered_body, disk_body)
    tail_present = tail in body
    interior_present = mid is not None and mid in body

    verdict, reason = _verdict_from_signals(skill_name, body, tail_present, interior_present)
    return {
        "verdict": verdict,
        "reason": reason,
        "length": length,
        "first_divergence": first_divergence,
        "tail_present": tail_present,
        "interior_present": interior_present,
        "copy_outcome": copy_outcome,
        "copy_reason": copy_reason,
    }


def _verdict_from_signals(skill_name, body, tail_present, interior_present):
    """Return (verdict, reason) from the control signals. The `no-body` arm is ordered AHEAD
    of the tail-loss arm: a body carrying neither control is a no-body result (e.g. the
    documented already-loaded short note), not a lost tail."""
    for marker in _TRUNCATION_MARKERS:
        if marker in body:
            return "short-delivery", (
                "the delivered body carried a truncation/cap notice (%r), so the Skill tool "
                "clipped %s" % (marker, skill_name)
            )
    if not tail_present and not interior_present:
        return "no-body", (
            "the delivered tool_result for %s carried NEITHER the file's last non-empty line "
            "NOR its interior control — this is a body-less result (e.g. the documented "
            "already-loaded short note), not a truncated body" % skill_name
        )
    if not tail_present:
        return "short-delivery", (
            "the delivered body did NOT contain the file's last non-empty line, so the tail "
            "of %s was lost (for the review root the tail is the routing/verdict-emitter "
            "region)" % skill_name
        )
    if not interior_present:
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
        rep = report_for_root(name, path, pairs, note_top)
        length = rep["length"]
        offset = rep["first_divergence"]
        lines.append("-" * 72)
        lines.append("ROOT   : %s (%s)" % (name, path))
        lines.append("VERDICT: %s" % rep["verdict"])
        lines.append("REASON : %s" % rep["reason"])
        lines.append("LENGTH : %s"
                     % ("%d chars" % length if length is not None
                        else "unestablished (no body delivered)"))
        lines.append("FIRST-DIVERGENCE: %s"
                     % ("offset %d" % offset if offset is not None
                        else "unestablished (no body/controls to compare)"))
        lines.append("TAIL-CONTROL: %s" % _present_str(rep["tail_present"]))
        lines.append("INTERIOR-CONTROL: %s" % _present_str(rep["interior_present"]))
        lines.append("COPY   : %s%s"
                     % (rep["copy_outcome"] or "unestablished (no delivered body)",
                        (" — " + rep["copy_reason"]) if rep["copy_reason"] else ""))
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

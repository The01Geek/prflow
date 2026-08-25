#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Validate the issue-claim-auditor's per-pass disposition record (issue #1740).

Phase 1.6 dispatches the issue-claim-auditor, which returns an ISSUE-CLAIM-AUDIT
RECORD — a fenced `key: value` text block. Issue #1740 adds a stated disposition
per chartered pass to that record, mirroring the Named-steps contract the two AC
verifiers already carry (scripts/reconcile-ac-verifiers.py). This helper is the
deterministic consumer the orchestrator runs over the returned record before it
honours `outcome: proceed`: a record missing any chartered pass's disposition is
treated as that pass not run, and a `skipped` or unparseable disposition blocks
the same way, so a silently-skipped pass becomes a visible §1.6 refusal instead
of a wasted implement run discovered at review time.

The record is agent-authored text, so every malformed shape must refuse rather
than detonate (the best-effort-parser discipline): an unreadable or empty record
is exit 3, a non-conforming one is exit 2 naming each offending pass, and only a
record carrying a `ran (<reason>)` disposition for every chartered pass — and no
disposition for a pass outside the charter — exits 0.

Exit codes:
    0 — conforming: every chartered pass dispositioned `ran (<reason>)`
    2 — non-conforming: a chartered pass absent (treated as not run), `skipped`,
        unparseable, or a disposition for an unknown pass — offenders on stderr
    3 — the record file was unreadable or empty (fail closed)
"""

import argparse
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


# The chartered passes the issue-claim-auditor runs. The former Pass 4 is renumbered to
# the orchestrator's §1.3.5, so 4 is absent by design. Coupled to agents/issue-claim-auditor.md's
# "Named passes" block AND its returned-record `pass<N>_disposition` fields: change one and
# change the others, or the gate checks a pass the charter never asks for (blocking every
# audit) or misses one it does.
CHARTERED_PASSES = (0, 1, 2, 3, 5, 6)

# `ran`/`skipped` then end-of-value or a boundary char, then the reason. Verdict vocabulary
# differs from scripts/reconcile-ac-verifiers.py's _DISPOSITION_RE (this gate asks whether a
# pass ran; that one whether a step was performed), so the primitive is duplicated rather than
# imported. Do not widen the lookahead to admit `-`, nor narrow it to whitespace-and-paren.
_DISPOSITION_RE = re.compile(r"^(ran|skipped)(?=$|[\s(,;:.])(.*)$",
                             re.IGNORECASE | re.DOTALL)

# The reason must carry at least one alphanumeric character, so a mechanical `ran .` cannot
# discharge a pass with no clause behind it.
_REASON_SUBSTANTIVE_RE = re.compile(r"[^\W_]")

# One `pass<N>_disposition: <value>` line. N is captured so a pass outside the charter is
# detected rather than silently ignored.
_PASS_LINE_RE = re.compile(r"^\s*pass(\d+)_disposition\s*:\s*(.*)$", re.IGNORECASE)


def parse_disposition(value):
    """Parse one disposition value into `(verdict, reason)`, or `(None, "")` when it does
    not parse or carries no substantive reason.

    `skipped` parses — it is a stated disposition; the caller, not this parser, treats it
    as blocking. A verdict with no alphanumeric reason behind it (`ran`, `ran ()`, `ran .`)
    is undischarged, exactly as the sibling reconcile-ac-verifiers.py treats `yes`.
    """
    if not isinstance(value, str):
        return None, ""
    match = _DISPOSITION_RE.match(value.strip())
    if not match:
        return None, ""
    reason = match.group(2).strip()
    # Unwrap only a clause the outer parens actually enclose — do not strip parens from
    # each end independently, which would reshape a malformed `((a))` into a well-formed `a`.
    if (reason.startswith("(") and reason.endswith(")")
            and "(" not in reason[1:-1] and ")" not in reason[1:-1]):
        reason = reason[1:-1].strip()
    if not _REASON_SUBSTANTIVE_RE.search(reason):
        return None, ""
    return match.group(1).lower(), reason


def validate_record(text):
    """Classify an ISSUE-CLAIM-AUDIT RECORD's per-pass dispositions.

    Returns `(conforming, result)`. `result["passes"]` maps each chartered pass to
    `ran` / `skipped` / `absent` / `malformed`; `result["unknown"]` lists any pass numbers
    dispositioned outside the charter; `result["offending"]` lists a human clause per
    blocking pass. `conforming` is True only when every chartered pass is `ran` and no
    unknown pass appears — an absent disposition is treated as that pass not run.
    """
    seen = {}
    for line in (text or "").splitlines():
        m = _PASS_LINE_RE.match(line)
        if m:
            seen[int(m.group(1))] = m.group(2)
    passes = {}
    offending = []
    for n in CHARTERED_PASSES:
        if n not in seen:
            passes[n] = "absent"
            offending.append(f"pass {n} (disposition absent — treated as not run)")
            continue
        verdict, _reason = parse_disposition(seen[n])
        if verdict is None:
            passes[n] = "malformed"
            offending.append(
                f"pass {n} (disposition not a parseable 'ran|skipped <reason>')")
        elif verdict == "skipped":
            passes[n] = "skipped"
            offending.append(f"pass {n} (skipped)")
        else:
            passes[n] = "ran"
    unknown = sorted(n for n in seen if n not in CHARTERED_PASSES)
    for n in unknown:
        offending.append(f"pass {n} (not a chartered pass)")
    conforming = not offending
    return conforming, {"passes": passes, "unknown": unknown, "offending": offending}


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Validate the issue-claim-auditor per-pass disposition record.")
    parser.add_argument("--record-file", required=True,
                        help="path to the returned ISSUE-CLAIM-AUDIT RECORD text")
    args = parser.parse_args(argv)
    try:
        with open(args.record_file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"validate-issue-claim-audit: could not read the record: {exc}",
              file=sys.stderr)
        return 3
    if not text.strip():
        print("validate-issue-claim-audit: the record was empty — failing closed",
              file=sys.stderr)
        return 3
    conforming, result = validate_record(text)
    if conforming:
        return 0
    print("validate-issue-claim-audit: the issue-claim audit is not clean — "
          + "; ".join(result["offending"]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

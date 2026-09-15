#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Validate the review-fix-worker's JSON handoff before Phase 3.3 honours its outcome (issue #495).

`/prflow:implement` Phase 3.3 dispatches a fresh `review-fix-worker` subagent that runs the
review/fix loop in its own context and writes a compact JSON handoff to a scratch file. This
helper is the deterministic reader the implement orchestrator runs over that handoff before it
continues: it accepts evidence only from the current dispatch and from artifact paths contained
in this checkout (symlink-resolved), and rejects an unusable return — absent, malformed,
incomplete, stale-dispatch, escaping-path, or mismatched-identity — so a rejected boundary
records an actionable blocker rather than being replayed inline in the parent.

The handoff is agent-authored, so every malformed shape refuses rather than detonates (the
best-effort-parser discipline): an unreadable, empty, or truncated (non-JSON) file is exit 3, a
JSON value that parses but does not conform is exit 2 naming each offender on stderr, and only a
fully-conforming handoff whose identity matches the caller and whose artifact paths stay inside
the checkout exits 0.

Permitted valid-falsy / null shapes (AC3): a null `question`, `final_commit`, or `pr.number`; an
empty `unresolved_findings`; a finding with a null `defect_signature`; `review_coverage_recorded`
false; and a null `loop_run.iter_dir`. `blockers` must be non-empty only when `outcome` is
`blocked` or `error`.

Exit codes:
    0 — conforming: shape, identity, and checkout containment all hold
    2 — non-conforming: a shape/enum/type fault, an identity mismatch (stale or duplicate
        dispatch), or an artifact path resolving outside the checkout — offenders on stderr
    3 — the handoff file was unreadable, empty, or not valid JSON (fail closed)

Callers branch on zero-vs-non-zero, never on 2 specifically: argparse also exits 2 for a missing
argument, so reading 2 as "non-conforming handoff" would misreport an invocation error as a
rejected return.
"""

import argparse
import json
import os
import sys

#: The one schema version this reader understands.
SCHEMA_VERSION = 1

#: Closed enums, each keyed by its dotted field path.
_OUTCOMES = ("proceed", "blocked", "needs-confirmation", "error")
_DRAFT_PR_DISPOSITIONS = ("numbered", "empty-brackets", "absent")
_VERDICT_BUCKETS = ("clean-full", "clean-not-verified", "awusf", "reject", "unestablished")
_PERSISTENCE_CLASSES = ("ok", "lost", "unestablished")


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never at import: it would mutate the streams of any
    process that imports this module for tests. Tolerates a stream with no `reconfigure`."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _is_str(v):
    return isinstance(v, str)


def _is_int(v):
    # A JSON bool is an int subclass; a schema int field must not accept true/false.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_40hex(v):
    return _is_str(v) and len(v) == 40 and all(c in "0123456789abcdef" for c in v.lower())


def _within_checkout(path, checkout_real, offending, field):
    """Append an offender when `path` does not resolve inside `checkout_real`.

    The path is resolved with os.path.realpath (following symlinks and normalising `..`), so a
    string that textually sits under the checkout but resolves elsewhere is rejected. The
    containment test compares the resolved path against the resolved checkout root with a
    trailing separator, so a sibling sharing a name prefix cannot masquerade as contained.
    """
    try:
        resolved = os.path.realpath(os.path.join(checkout_real, path)) if not os.path.isabs(path) \
            else os.path.realpath(path)
    except ValueError:
        # A path carrying an embedded NUL byte makes realpath raise; refuse it as an offender
        # rather than letting the traceback break the fail-closed "refuse, never detonate" contract.
        offending.append(f"{field}: {path!r} is not a resolvable path (embedded NUL byte)")
        return
    root_with_sep = checkout_real.rstrip(os.sep) + os.sep
    if resolved != checkout_real and not resolved.startswith(root_with_sep):
        offending.append(
            f"{field}: {path!r} resolves to {resolved!r}, outside the checkout {checkout_real!r}"
        )


def validate_handoff(data, *, checkout_root, dispatch_id, issue_number):
    """Classify a parsed handoff object against the schema, identity, and checkout containment.

    Returns `(conforming, result)`. `result["offending"]` lists a human clause per fault;
    `conforming` is True only when it is empty. `data` is whatever `json.loads` produced — a
    non-object top level is itself a fault, so the caller need not pre-check the type.
    """
    offending = []

    def req(name, ok, note):
        """Record an offender for a required scalar field failing predicate `ok`."""
        if name not in data:
            offending.append(f"{name}: absent")
        elif not ok(data.get(name)):
            offending.append(f"{name}: {note} (got {data.get(name)!r})")

    def obj(name):
        """Return `data[name]` when it is a JSON object, else record an offender and return None."""
        if name not in data:
            offending.append(f"{name}: absent")
            return None
        value = data.get(name)
        if not isinstance(value, dict):
            offending.append(f"{name}: must be an object (got {type(value).__name__})")
            return None
        return value

    if not isinstance(data, dict):
        return False, {"offending": [f"handoff must be a JSON object, not {type(data).__name__}"]}

    # Identity and version — the fail-closed gate against a stale/duplicate/mismatched return.
    req("schema_version", lambda v: v == SCHEMA_VERSION, f"must be {SCHEMA_VERSION}")
    req("issue_number", lambda v: v == issue_number,
        f"must equal the dispatched issue {issue_number}")
    req("dispatch_id", lambda v: v == dispatch_id,
        "must equal the current dispatch id (a mismatch is a stale or duplicate return)")
    req("repo_root", _is_str, "must be a string")
    req("run_id", _is_str, "must be a string")
    req("run_attempt", _is_str, "must be a string")
    # repo_root is an identity field: the worker echoes the checkout it ran in, so a value
    # resolving to a different tree than the parent's --checkout-root is a mismatched-identity
    # return, rejected like a stale dispatch. Compare realpaths so an equivalent spelling passes.
    if _is_str(data.get("repo_root")):
        try:
            _repo_matches = os.path.realpath(data["repo_root"]) == os.path.realpath(checkout_root)
        except ValueError:
            # An embedded NUL byte makes realpath raise; refuse rather than detonate.
            offending.append("repo_root: is not a resolvable path (embedded NUL byte)")
        else:
            if not _repo_matches:
                offending.append(
                    f"repo_root: {data['repo_root']!r} resolves to a different tree than the "
                    f"checkout root {checkout_root!r} (mismatched-identity return)")

    # Outcome and its coupled human-question / blockers requirements.
    req("outcome", lambda v: v in _OUTCOMES, f"must be one of {_OUTCOMES}")
    req("question", lambda v: v is None or _is_str(v), "must be a string or null")
    # A needs-confirmation return exists to carry a human question back to the parent, so a null
    # or empty question there is an incomplete return (mirrors the blocked/error blockers rule).
    if data.get("outcome") == "needs-confirmation" and not (
            _is_str(data.get("question")) and data["question"].strip()):
        offending.append("question: must be a non-empty string when outcome is needs-confirmation (incomplete)")
    req("final_commit", lambda v: v is None or _is_40hex(v),
        "must be a 40-char lowercase hex commit sha or null")
    req("review_coverage_recorded", lambda v: isinstance(v, bool), "must be a boolean")

    pr = obj("pr")
    if pr is not None:
        if not ("number" in pr and (pr["number"] is None or _is_int(pr["number"]))):
            offending.append("pr.number: must be an integer or null")
        if pr.get("draft_pr_disposition") not in _DRAFT_PR_DISPOSITIONS:
            offending.append(f"pr.draft_pr_disposition: must be one of {_DRAFT_PR_DISPOSITIONS}")

    branch = obj("branch")
    if branch is not None:
        if not _is_str(branch.get("recorded")):
            offending.append("branch.recorded: must be a string")
        if not (branch.get("final") is None or _is_str(branch.get("final"))):
            offending.append("branch.final: must be a string or null")

    verdict = obj("verdict")
    if verdict is not None:
        if verdict.get("bucket") not in _VERDICT_BUCKETS:
            offending.append(f"verdict.bucket: must be one of {_VERDICT_BUCKETS}")
        for axis in ("coverage", "dispatch", "roster", "checklist"):
            if not _is_str(verdict.get(axis)):
                offending.append(f"verdict.{axis}: must be a string")

    persistence = obj("persistence")
    if persistence is not None:
        if persistence.get("class") not in _PERSISTENCE_CLASSES:
            offending.append(f"persistence.class: must be one of {_PERSISTENCE_CLASSES}")
        if not (persistence.get("reason") is None or _is_str(persistence.get("reason"))):
            offending.append("persistence.reason: must be a string or null")

    # Arrays. blockers is required non-empty on a blocked/error outcome; empty otherwise is fine.
    blockers = data.get("blockers")
    if not isinstance(blockers, list):
        offending.append("blockers: must be an array")
    else:
        for i, b in enumerate(blockers):
            if not (isinstance(b, dict) and _is_str(b.get("reason")) and _is_str(b.get("evidence"))):
                offending.append(f"blockers[{i}]: must be an object with string reason and evidence")
        if data.get("outcome") in ("blocked", "error") and not blockers:
            offending.append("blockers: must be non-empty when outcome is blocked or error (incomplete)")

    findings = data.get("unresolved_findings")
    if not isinstance(findings, list):
        offending.append("unresolved_findings: must be an array (may be empty)")
    else:
        for i, f in enumerate(findings):
            if not isinstance(f, dict):
                offending.append(f"unresolved_findings[{i}]: must be an object")
                continue
            if not _is_str(f.get("severity")):
                offending.append(f"unresolved_findings[{i}].severity: must be a string")
            if not _is_str(f.get("description")):
                offending.append(f"unresolved_findings[{i}].description: must be a string")
            if not (f.get("defect_signature") is None or _is_str(f.get("defect_signature"))):
                offending.append(f"unresolved_findings[{i}].defect_signature: must be a string or null")

    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        offending.append("warnings: must be an array")
    elif not all(_is_str(w) for w in warnings):
        offending.append("warnings: every element must be a string")

    # loop_run and its checkout-contained artifact path.
    checkout_real = os.path.realpath(checkout_root)
    loop_run = obj("loop_run")
    if loop_run is not None:
        for key in ("slug", "run_id"):
            if not (loop_run.get(key) is None or _is_str(loop_run.get(key))):
                offending.append(f"loop_run.{key}: must be a string or null")
        iter_dir = loop_run.get("iter_dir")
        if iter_dir is None:
            pass
        elif not _is_str(iter_dir):
            offending.append("loop_run.iter_dir: must be a string or null")
        elif not iter_dir.strip():
            # An empty/whitespace iter_dir is neither a real path nor null; it would resolve to
            # the checkout root and pass the containment check vacuously, so reject it as malformed.
            offending.append("loop_run.iter_dir: must be a non-empty path or null (got empty string)")
        else:
            _within_checkout(iter_dir, checkout_real, offending, "loop_run.iter_dir")

    return not offending, {"offending": offending}


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Validate the review-fix-worker JSON handoff before Phase 3.3 continuation.")
    parser.add_argument("--handoff-file", required=True,
                        help="path to the review-fix-worker's JSON handoff record")
    parser.add_argument("--checkout-root", required=True,
                        help="the implement checkout root; artifact paths must resolve inside it")
    parser.add_argument("--dispatch-id", required=True,
                        help="the current dispatch id; a mismatch is a stale/duplicate return")
    parser.add_argument("--issue-number", required=True, type=int,
                        help="the dispatched issue number, cross-checked against the handoff")
    args = parser.parse_args(argv)

    try:
        with open(args.handoff_file, encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"validate-review-fix-handoff: could not read the handoff: {exc}", file=sys.stderr)
        return 3
    if not raw.strip():
        print("validate-review-fix-handoff: the handoff file was empty — failing closed",
              file=sys.stderr)
        return 3
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"validate-review-fix-handoff: the handoff is not valid JSON: {exc}", file=sys.stderr)
        return 3

    conforming, result = validate_handoff(
        data, checkout_root=args.checkout_root,
        dispatch_id=args.dispatch_id, issue_number=args.issue_number)
    if conforming:
        return 0
    print("validate-review-fix-handoff: the worker handoff is unusable — "
          + "; ".join(result["offending"]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

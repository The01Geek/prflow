#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Validate a `/prflow:implement` worker's JSON handoff before the parent honours its outcome.

Two schemas share this reader, selected by `--schema {review-fix,finalization}` (default
`review-fix`, so an existing Phase 3.3 call runs unmodified):

- `review-fix` (issue #495): Phase 3.3 dispatches a fresh `review-fix-worker` that runs the
  review/fix loop in its own context and writes a compact JSON handoff to a scratch file. This
  helper is the deterministic reader the parent runs over that handoff before it continues.
- `finalization` (issue #539): Phase 4 dispatches a `implement-finalization` worker that writes
  `<run-scratch>/finalization-handoff-$ISSUE_NUMBER.json` and returns a three-line envelope; the
  parent runs this reader over that file before it publishes the PR and writes Complete.

Both accept evidence only from the current dispatch and reject an unusable return — absent,
malformed, incomplete, stale-dispatch, or mismatched-identity — so a rejected boundary records an
actionable blocker rather than being replayed inline in the parent. Only the review-fix schema
additionally confines artifact paths to this checkout (symlink-resolved), rejecting an
escaping-path return; the finalization schema checks `repo_root` identity but does not
containment-check its opaque string references.

The handoff is agent-authored, so every malformed shape refuses rather than detonates (the
best-effort-parser discipline): an unreadable, empty, or truncated (non-JSON) file is exit 3, a
JSON value that parses but does not conform is exit 2 naming each offender on stderr, and only a
fully-conforming handoff whose identity matches the caller exits 0.

Permitted review-fix valid-falsy / null shapes (AC3): a null `final_commit` or
`pr.number`; an empty `unresolved_findings`; a finding with a null `defect_signature`;
`review_coverage_recorded` false; and a null `loop_run.iter_dir`. `blockers` must be non-empty
only when `outcome` is `blocked` or `error`.

Finalization schema (`--schema finalization`, issue #539) — the field contract's single home:

- Identity (required, non-null on EVERY outcome — dispatch literals the worker echoes back, never
  observations): `schema_version` (must be 1), `dispatch_id` (== `--dispatch-id`), `repo_root`
  (realpath == `--checkout-root`), `issue_number` (int, == `--issue-number`), `pr_number` (int),
  `pr_url`, `run_id`, `run_attempt`, `entry_head`, `workpad_id`. A JSON bool is rejected where an
  int is required (`issue_number: true`, `pr_number: true`).
- Routing: `outcome` (one of `proceed`, `blocked`, `needs-recovery`, `needs-repair`, `error`);
  `reason` (non-empty on every non-`proceed` stop record); `extension` (object or null),
  `warnings`, `unresolved_obligations` (array or null) — the last three are observations,
  nullable on any outcome. `extension` (issue #622) is closed to the keys `parent_state`,
  `worker_state` (each `observed-content`, `observed-empty`, `unestablished` or null),
  `parent_digest`, `worker_digest` (the loader's `sha256=<64 hex> bytes=<int>` or null),
  `trusted_root` (string or null) and `pending_notes` (array of strings or null), every key
  optional; `worker_state: observed-content` requires a non-null `worker_digest`. No `question` field: the confirmation-gate outcome was retired
  (issue #596).
- Evidence, each required non-null when `outcome` is `proceed` and nullable on a stop record:
  `branch` (string); `final_head` (40-char lowercase-hex sha, and 40-hex-or-null on any outcome);
  `checkpoint4`, `review_coverage`, `tip_landed` (objects); `verification` (object whose
  `candidate_sha` is a 40-hex sha on `proceed` and on `needs-repair` — the failed candidate the
  parent repairs (issue #562) — and 40-hex-or-null on any outcome); `steps` (an
  object carrying each owned step `§4.0`, `§4.0.5`, `§4.0.6`, `§4.1`, `§4.2`, `§4.3` with a
  non-empty string `disposition` — presence and type only, not the disposition vocabulary).

Exit codes (both schemas):
    0 — conforming: shape and identity hold (and, for review-fix, checkout containment)
    2 — non-conforming: a shape/enum/type fault, an identity mismatch (stale or duplicate
        dispatch), or (review-fix schema) an artifact path resolving outside the checkout —
        offenders on stderr
    3 — the handoff file was unreadable, empty, or not valid JSON (fail closed); for the
        finalization schema a JSON value that is not an object also fails closed here (issue #539
        AC5 — a bare array or scalar is structurally unusable, like an empty file), whereas the
        review-fix schema treats a non-object as the exit-2 "parses but does not conform" case

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
_OUTCOMES = ("proceed", "blocked", "error")
#: Finalization (issue #539) adds `needs-recovery` for a missing canonical operand, and issue
#: #562 `needs-repair` for a failed final-tree verification the parent repairs.
_OUTCOMES_FINALIZATION = ("proceed", "blocked", "needs-recovery", "needs-repair", "error")
#: The Phase 4 steps a `proceed` finalization handoff must account for in `steps`.
_FINALIZATION_STEP_IDS = ("§4.0", "§4.0.5", "§4.0.6", "§4.1", "§4.2", "§4.3")
_DRAFT_PR_DISPOSITIONS = ("numbered", "empty-brackets", "absent")
_VERDICT_BUCKETS = ("clean-full", "clean-not-verified", "awusf", "reject", "unestablished")
_PERSISTENCE_CLASSES = ("ok", "lost", "unestablished")
#: Finalization `extension` object (issue #622): the intake worker's field set, closed.
_EXTENSION_KEYS = ("parent_state", "worker_state", "parent_digest", "worker_digest",
                   "trusted_root", "pending_notes")
_EXTENSION_STATES = ("observed-content", "observed-empty", "unestablished")


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


def _is_extension_digest(v):
    """True for the loader's `sha256=<64 lowercase hex> bytes=<int>` digest value."""
    if not _is_str(v):
        return False
    parts = v.split(" ")
    if len(parts) != 2 or not parts[0].startswith("sha256=") or not parts[1].startswith("bytes="):
        return False
    hexpart, size = parts[0][len("sha256="):], parts[1][len("bytes="):]
    return (len(hexpart) == 64 and all(c in "0123456789abcdef" for c in hexpart)
            and size.isascii() and size.isdigit())


def _check_extension(ext, offending):
    """Validate the finalization `extension` object: closed keys, enum states, digest forms.

    A worker's `observed-content` must carry a well-formed `worker_digest`. This proves only that
    a digest was reported, not that it came from a full load; the extension tick contract owns
    that rule.
    """
    if ext is None:
        return
    if not isinstance(ext, dict):
        offending.append("extension: must be an object or null")
        return
    for key in ext:
        if key not in _EXTENSION_KEYS:
            offending.append(f"extension.{key}: unknown key")
    for key in ("parent_state", "worker_state"):
        v = ext.get(key)
        if not (v is None or (_is_str(v) and v in _EXTENSION_STATES)):
            offending.append(f"extension.{key}: must be one of {_EXTENSION_STATES} or null")
    for key in ("parent_digest", "worker_digest"):
        v = ext.get(key)
        if not (v is None or _is_extension_digest(v)):
            offending.append(
                f"extension.{key}: must be 'sha256=<64 lowercase hex> bytes=<int>' or null")
    if ext.get("worker_state") == "observed-content" and ext.get("worker_digest") is None:
        offending.append(
            "extension.worker_digest: must be non-null when worker_state is observed-content "
            "(a full load ends with the loader's digest line)")
    root = ext.get("trusted_root")
    if not (root is None or _is_str(root)):
        offending.append("extension.trusted_root: must be a string or null")
    notes = ext.get("pending_notes")
    if not (notes is None or (isinstance(notes, list) and all(_is_str(n) for n in notes))):
        offending.append("extension.pending_notes: must be an array of strings or null")


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


def _make_req(data, offending):
    """Return a `req(name, ok, note)` recording an offender for a required scalar field.

    Shared by both schemas so their `absent` / `(got …)` offender wording cannot drift apart.
    """
    def req(name, ok, note):
        if name not in data:
            offending.append(f"{name}: absent")
        elif not ok(data.get(name)):
            offending.append(f"{name}: {note} (got {data.get(name)!r})")
    return req


def _check_repo_root_identity(data, checkout_root, offending):
    """Record an offender when the echoed `repo_root` resolves to a different tree than
    `checkout_root`. The worker echoes the checkout it ran in, so a mismatch is a
    mismatched-identity return rejected like a stale dispatch; realpaths are compared so an
    equivalent spelling passes, and an embedded NUL byte refuses rather than detonates. The
    caller runs its own `req("repo_root", _is_str, …)` first, so this only adds the tree match.
    """
    if not _is_str(data.get("repo_root")):
        return
    try:
        matches = os.path.realpath(data["repo_root"]) == os.path.realpath(checkout_root)
    except ValueError:
        offending.append("repo_root: is not a resolvable path (embedded NUL byte)")
        return
    if not matches:
        offending.append(
            f"repo_root: {data['repo_root']!r} resolves to a different tree than the "
            f"checkout root {checkout_root!r} (mismatched-identity return)")


def validate_handoff(data, *, checkout_root, dispatch_id, issue_number):
    """Classify a parsed handoff object against the schema, identity, and checkout containment.

    Returns `(conforming, result)`. `result["offending"]` lists a human clause per fault;
    `conforming` is True only when it is empty. `data` is whatever `json.loads` produced — a
    non-object top level is itself a fault, so the caller need not pre-check the type.
    """
    offending = []
    req = _make_req(data, offending)

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
    _check_repo_root_identity(data, checkout_root, offending)

    # Outcome and its coupled blockers requirement. No `question` field: the confirmation-gate
    # outcome was retired (issue #596), so any stray `question` key is ignored, not validated.
    req("outcome", lambda v: v in _OUTCOMES, f"must be one of {_OUTCOMES}")
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


def _validate_finalization(data, *, checkout_root, dispatch_id, issue_number):
    """Classify a Phase 4 finalization handoff (issue #539) against the schema and identity.

    Returns `(conforming, result)` in the same shape as `validate_handoff`. The identity fields
    are dispatch literals the worker echoes, so each is required non-null on every outcome; the
    evidence fields are the worker's own observations, required non-null only on a `proceed`
    result and permitted null on a stop record.
    """
    if not isinstance(data, dict):
        return False, {"offending": [f"handoff must be a JSON object, not {type(data).__name__}"]}

    offending = []
    req = _make_req(data, offending)

    outcome = data.get("outcome")
    proceed = outcome == "proceed"
    needs_candidate = outcome in ("proceed", "needs-repair")
    # Every non-proceed outcome is a stop record that reports `reason`. No `question` field: the
    # confirmation-gate outcome was retired (issue #596), so a stray `question` key is ignored.
    stop_with_reason = outcome in ("blocked", "needs-recovery", "needs-repair", "error")

    # Identity — required non-null on every outcome; a bool is refused where an int is required.
    req("schema_version", lambda v: _is_int(v) and v == SCHEMA_VERSION, f"must be {SCHEMA_VERSION}")
    req("dispatch_id", lambda v: v == dispatch_id,
        "must equal the current dispatch id (a mismatch is a stale or duplicate return)")
    req("issue_number", lambda v: _is_int(v) and v == issue_number,
        f"must equal the dispatched issue {issue_number}")
    req("pr_number", _is_int, "must be an integer")
    req("pr_url", _is_str, "must be a string")
    req("run_id", _is_str, "must be a string")
    req("run_attempt", _is_str, "must be a string")
    req("entry_head", _is_str, "must be a string")
    req("workpad_id", _is_str, "must be a string")
    req("repo_root", _is_str, "must be a string")
    _check_repo_root_identity(data, checkout_root, offending)

    # Routing.
    req("outcome", lambda v: v in _OUTCOMES_FINALIZATION,
        f"must be one of {_OUTCOMES_FINALIZATION}")
    if stop_with_reason and not (_is_str(data.get("reason")) and data["reason"].strip()):
        offending.append(
            "reason: must be a non-empty string on a stop record (incomplete)")
    _check_extension(data.get("extension"), offending)
    for _arr in ("warnings", "unresolved_obligations"):
        if not (data.get(_arr) is None or isinstance(data.get(_arr), list)):
            offending.append(f"{_arr}: must be an array or null")

    # Evidence — proceed-required-non-null, nullable on a stop record.
    final_head = data.get("final_head")
    if not (final_head is None or _is_40hex(final_head)):
        offending.append("final_head: must be a 40-char lowercase hex sha or null")
    if proceed and final_head is None:
        offending.append("final_head: must be non-null when outcome is proceed")

    branch = data.get("branch")
    if proceed:
        if not _is_str(branch):
            offending.append("branch: must be a non-null string when outcome is proceed")
    elif not (branch is None or _is_str(branch)):
        offending.append("branch: must be a string or null")

    verification = data.get("verification")
    if needs_candidate and verification is None:
        offending.append(f"verification: must be non-null when outcome is {outcome}")
    if verification is not None:
        if not isinstance(verification, dict):
            offending.append("verification: must be an object or null")
        else:
            candidate = verification.get("candidate_sha")
            if not (candidate is None or _is_40hex(candidate)):
                offending.append(
                    "verification.candidate_sha: must be a 40-char lowercase hex sha or null")
            if needs_candidate and candidate is None:
                offending.append(
                    f"verification.candidate_sha: must be non-null when outcome is {outcome}")

    for _name in ("checkpoint4", "review_coverage", "tip_landed"):
        _value = data.get(_name)
        if proceed and _value is None:
            offending.append(f"{_name}: must be non-null when outcome is proceed")
        elif _value is not None and not isinstance(_value, dict):
            offending.append(f"{_name}: must be an object or null")

    steps = data.get("steps")
    if proceed:
        if not isinstance(steps, dict):
            offending.append("steps: must be an object when outcome is proceed")
        else:
            for _sid in _FINALIZATION_STEP_IDS:
                _entry = steps.get(_sid)
                if not isinstance(_entry, dict):
                    offending.append(
                        f"steps[{_sid}]: must be present as an object when outcome is proceed")
                elif not (_is_str(_entry.get("disposition")) and _entry["disposition"].strip()):
                    offending.append(f"steps[{_sid}].disposition: must be a non-empty string")
    elif not (steps is None or isinstance(steps, dict)):
        offending.append("steps: must be an object or null")

    return not offending, {"offending": offending}


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Validate an implement-worker JSON handoff before the parent honours it.")
    parser.add_argument("--schema", choices=("review-fix", "finalization"), default="review-fix",
                        help="which handoff schema to validate (default: review-fix)")
    parser.add_argument("--handoff-file", required=True,
                        help="path to the worker's JSON handoff record")
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

    if args.schema == "finalization" and not isinstance(data, dict):
        # Finalization treats a non-object as structurally unusable (exit 3, AC5) — do NOT unify it
        # with the review-fix schema's exit-2 non-conforming path; the divergence is deliberate.
        print("validate-review-fix-handoff: the finalization handoff is not a JSON object — "
              "failing closed", file=sys.stderr)
        return 3

    checker = _validate_finalization if args.schema == "finalization" else validate_handoff
    conforming, result = checker(
        data, checkout_root=args.checkout_root,
        dispatch_id=args.dispatch_id, issue_number=args.issue_number)
    if conforming:
        return 0
    print("validate-review-fix-handoff: the worker handoff is unusable — "
          + "; ".join(result["offending"]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

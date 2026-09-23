#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Validate a `/prflow:implement` worker's JSON handoff before the parent honours its outcome.

Four schemas share this reader, selected by `--schema
{review-fix,finalization,intake,issue-claim-audit}` (default `review-fix`, so an existing Phase
3.3 call runs unmodified):

- `review-fix` (issue #495): Phase 3.3 dispatches a fresh `review-fix-worker` that runs the
  review/fix loop in its own context and writes a compact JSON handoff to a scratch file. This
  helper is the deterministic reader the parent runs over that handoff before it continues.
- `finalization` (issue #539): Phase 4 dispatches a `implement-finalization` worker that writes
  `<run-scratch>/finalization-handoff-$ISSUE_NUMBER.json` and returns a three-line envelope; the
  parent runs this reader over that file before it publishes the PR and writes Complete.
- `intake` (issue #700): Phase 1 dispatches a `implement-intake` worker whose durable handoff the
  parent validates here — shape, identity, path/home containment, the snapshot receipt's
  bytes/sha256 against the snapshot file, and the `proceed` conditions. Needs `--run-id` and
  `--run-attempt` (canonical-string compared). On a `blocked`/`error` record,
  `issue.classification` (§1.1) and `workpad.id`/`workpad.observed_status` (§1.3) may be null
  unless `completed_steps` marks the owning step `complete`; a rejected stop record's
  `blocked_reason` is echoed on stderr (issue #983).
- `issue-claim-audit` (issue #700): Phase 1.6 dispatches a `issue-claim-auditor` worker whose
  durable handoff the parent validates here; the reader takes `record_validation`/
  `projection_validation` as the worker's attestations and runs no audit gate itself. Needs
  `--run-scratch`, `--base` and `--freshness`.

The `intake` and `issue-claim-audit` schemas — and only they — print one compact JSON line of
carry-forward fields to stdout on exit 0, so the parent keeps those fields resident instead of the
whole handoff; the intake line reports the `prior_decisions`/`corrections`/`blockers` array sizes
(the audit line carries the actionable arrays in full).

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

Finalization schema (`--schema finalization`, issue #539) — validated here, and restated for
the worker in `agents/implement-finalization.md`:

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

Exit codes (all schemas):
    0 — conforming: shape and identity hold (and, for review-fix/intake/issue-claim-audit, checkout
        containment); the intake and issue-claim-audit schemas additionally print one compact JSON
        line of carry-forward fields to stdout (no other schema writes to stdout on success)
    2 — non-conforming: a shape/enum/type fault, an identity mismatch (stale or duplicate
        dispatch), or an artifact path resolving outside the checkout (review-fix, intake,
        issue-claim-audit) — offenders on stderr, nothing on stdout
    3 — the handoff file was unreadable, empty, or not valid JSON (fail closed); for the
        finalization, intake and issue-claim-audit schemas a JSON value that is not an object also
        fails closed here (a bare array or scalar is structurally unusable, like an empty file),
        whereas the review-fix schema treats a non-object as the exit-2 "parses but does not
        conform" case

Callers branch on zero-vs-non-zero, never on 2 specifically: argparse also exits 2 for a missing
argument, so reading 2 as "non-conforming handoff" would misreport an invocation error as a
rejected return.
"""

import argparse
import hashlib
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
#: `clean-shadow-skipped` is the loop's clean-iteration-1 exit: no shadow was owed.
_VERDICT_BUCKETS = ("clean-full", "clean-shadow-skipped", "clean-not-verified", "awusf", "reject",
                    "unestablished")
_PERSISTENCE_CLASSES = ("ok", "lost", "unestablished")
#: Finalization `extension` object (issue #622): the intake worker's field set, closed.
_EXTENSION_KEYS = ("parent_state", "worker_state", "parent_digest", "worker_digest",
                   "trusted_root", "pending_notes")
_EXTENSION_STATES = ("observed-content", "observed-empty", "unestablished")

#: Intake schema (issue #700) — the Phase 1 intake worker's durable handoff.
_INTAKE_OUTCOMES = ("proceed", "blocked", "error")
_INTAKE_STOP_OUTCOMES = ("blocked", "error")
_INTAKE_RESUME_KINDS = ("in-flight", "terminal-re-trigger")
_CLASSIFICATIONS = ("bug-report", "non-bug")
_SCRATCH_ARMS = ("IGNORED", "NOT_IGNORED")
_COMPLETED_STEP_IDS = ("1.0", "1.1", "1.1.5", "1.2", "1.3", "1.3.5")
#: Issue-claim-audit schema (issue #700) — the Phase 1.6 auditor's durable handoff.
_AUDIT_OUTCOMES = ("proceed", "blocked-specification", "blocked-policy", "blocked-capability",
                   "error")
_AUDIT_STOP_OUTCOMES = ("blocked-specification", "blocked-policy", "blocked-capability", "error")
_RECORD_PROJ_VALIDATION = ("passed", "failed", "not-applicable")
_AUDIT_ARRAYS = ("unmatched_desired_behavior", "pass5_workflow_resident_acs",
                 "pass2_wrongly_excluded_surfaces", "superseding_assumptions", "external_facts",
                 "prior_decisions", "prior_corrections", "unresolved_blockers")


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
    """Append an offender when `path` does not resolve inside `checkout_real`. Return True when the
    path is contained (no offender appended) and False otherwise, so a caller can gate a subsequent
    read on containment — never opening a path this check already refused (e.g. an escaping symlink
    or absolute `/dev/zero`, whose read would hang the validator rather than fail closed).

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
        return False
    root_with_sep = checkout_real.rstrip(os.sep) + os.sep
    if resolved != checkout_real and not resolved.startswith(root_with_sep):
        offending.append(
            f"{field}: {path!r} resolves to {resolved!r}, outside the checkout {checkout_real!r}"
        )
        return False
    return True


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


def _canon_str_eq(v, operand):
    """True when `v` (a scalar the worker never types — `workpad.id`/`run_id`/`run_attempt`) equals
    `operand` by canonical string form. A dict/list/bool is never a scalar id, so it never matches."""
    return v is not None and not isinstance(v, (dict, list, bool)) and str(v) == str(operand)


def _read_secondary(path, field, offending, *, binary=False):
    """Read a referenced secondary file, recording an offender (never a traceback) when it is a
    directory, unreadable, carries an embedded NUL byte, or (text read) is not UTF-8. Returns the
    file's contents, or None when a fault was recorded — the fail-closed "refuse, never detonate"
    contract for a referenced secondary file."""
    try:
        if binary:
            with open(path, "rb") as fh:
                return fh.read()
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except IsADirectoryError:
        offending.append(f"{field}: {path!r} is a directory, not a readable file")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        offending.append(f"{field}: could not read {path!r} ({exc})")
    return None


def _intake_home(checkout_real, issue_number, arm):
    """The absolute directory an intake handoff and its `run_scratch` must resolve to, per arm.
    Returns None for an unrecognised arm (the caller already flagged `scratch.arm`)."""
    if arm == "IGNORED":
        return os.path.join(checkout_real, ".prflow", "tmp", "implement", str(issue_number))
    if arm == "NOT_IGNORED":
        return os.path.join(checkout_real, ".prflow", "tmp")
    return None


def _resolves_within(path, root_real, offending, field):
    """Append an offender when `path` does not resolve inside `root_real`; return the resolved
    path, or None when it could not be resolved (embedded NUL byte)."""
    try:
        resolved = os.path.realpath(path)
    except ValueError:
        offending.append(f"{field}: {path!r} is not a resolvable path (embedded NUL byte)")
        return None
    root_with_sep = root_real.rstrip(os.sep) + os.sep
    if resolved != root_real and not resolved.startswith(root_with_sep):
        offending.append(f"{field}: {path!r} resolves to {resolved!r}, outside {root_real!r}")
    return resolved


def _handoff_resolves_to(handoff_file, expected_hf, offending, mismatch_note):
    """Append an offender when `handoff_file` does not resolve to `expected_hf`; a NUL byte in the
    path refuses rather than detonates. Shared by both Phase 1 schemas' home checks."""
    try:
        actual_hf = os.path.realpath(handoff_file)
    except ValueError:
        offending.append("handoff-file: is not a resolvable path (embedded NUL byte)")
        return
    if actual_hf != os.path.realpath(expected_hf):
        offending.append(mismatch_note)


def _intake_projection(data):
    """The carry-forward fields the orchestrator keeps resident from an intake handoff (issue
    #700). A null object projects as null; the arrays project only as sizes, except a stop record
    carries `blockers` in full."""
    def _count(arr):
        return len(arr) if isinstance(arr, list) else None
    issue = data.get("issue")
    scratch = data.get("scratch")
    workpad = data.get("workpad")
    dependency = data.get("dependency")
    proj = {
        "outcome": data.get("outcome"),
        "blocked_reason": data.get("blocked_reason"),
        "issue": None if not isinstance(issue, dict) else {
            "title": issue.get("title"), "labels": issue.get("labels"),
            "classification": issue.get("classification")},
        "scratch": None if not isinstance(scratch, dict) else {
            "arm": scratch.get("arm"), "scratch_dir": scratch.get("scratch_dir"),
            "run_scratch": scratch.get("run_scratch"),
            "issue_body_path": scratch.get("issue_body_path"),
            "resolved_ac_path": scratch.get("resolved_ac_path")},
        "workpad": None if not isinstance(workpad, dict) else {
            "id": workpad.get("id"), "observed_status": workpad.get("observed_status"),
            "snapshot_path": workpad.get("snapshot_path"),
            "handoff_provenance": workpad.get("handoff_provenance"),
            "resume_kind": workpad.get("resume_kind")},
        "phase2_resume": data.get("phase2_resume"),
        "dependency": None if not isinstance(dependency, dict) else {
            "result": dependency.get("result"), "held_note": dependency.get("held_note")},
        "extension": data.get("extension"),
        "actionable_counts": {
            "prior_decisions": _count(data.get("prior_decisions")),
            "corrections": _count(data.get("corrections")),
            "blockers": _count(data.get("blockers"))},
        "warnings": data.get("warnings"),
    }
    if data.get("outcome") in _INTAKE_STOP_OUTCOMES:
        proj["blockers"] = data.get("blockers")
    return proj


def _audit_projection(data):
    """The carry-forward fields the orchestrator keeps resident from an audit handoff (issue #700):
    the actionable arrays in full, minus the validation metadata the reader consumed."""
    keys = ("outcome", "blocked_reason", "record_path", "projection_path") + _AUDIT_ARRAYS
    return {k: data.get(k) for k in keys}


def _validate_intake(data, *, checkout_root, dispatch_id, issue_number, run_id, run_attempt,
                     handoff_file):
    """Classify a Phase 1 intake handoff (issue #700). `result` additionally carries
    `result["projection"]` — the carry-forward dict `main` prints on exit 0. Identity is required
    non-null on every outcome; observations are required non-null only on `proceed` and nullable on
    a stop record, where a present non-null value still takes its shape rule."""
    if not isinstance(data, dict):
        return False, {"offending": [f"handoff must be a JSON object, not {type(data).__name__}"],
                       "projection": None}
    offending = []
    req = _make_req(data, offending)
    checkout_real = os.path.realpath(checkout_root)
    outcome = data.get("outcome")
    stop = outcome in _INTAKE_STOP_OUTCOMES
    completed = data.get("completed_steps")

    def unreached(sid):
        """A stop record's field owned by step `sid` may be null unless `completed_steps` claims
        that step complete (issue #983)."""
        return stop and not (isinstance(completed, dict) and completed.get(sid) == "complete")

    # Identity — dispatch literals the worker echoes, required non-null on every outcome.
    req("schema_version", lambda v: v == SCHEMA_VERSION, f"must be {SCHEMA_VERSION}")
    req("issue_number", lambda v: v == issue_number,
        f"must equal the dispatched issue {issue_number}")
    req("dispatch_id", lambda v: v == dispatch_id,
        "must equal the current dispatch id (a mismatch is a stale or duplicate return)")
    req("repo_root", _is_str, "must be a string")
    req("run_id", lambda v: _canon_str_eq(v, run_id),
        "must equal the current run id by canonical string form")
    req("run_attempt", lambda v: _canon_str_eq(v, run_attempt),
        "must equal the current run attempt by canonical string form")
    _check_repo_root_identity(data, checkout_root, offending)
    req("outcome", lambda v: v in _INTAKE_OUTCOMES, f"must be one of {_INTAKE_OUTCOMES}")

    if stop and not (_is_str(data.get("blocked_reason")) and data["blocked_reason"].strip()):
        offending.append("blocked_reason: must be a non-empty string on a stop record (incomplete)")

    def sect(name):
        """Return `data[name]` as an object. On a stop record a null/absent section is accepted; a
        present non-null non-object is always an offender."""
        v = data.get(name)
        if v is None:
            if not stop:
                offending.append(f"{name}: must be a non-null object when outcome is proceed")
            return None
        if not isinstance(v, dict):
            offending.append(f"{name}: must be an object (got {type(v).__name__})")
            return None
        return v

    issue = sect("issue")
    if issue is not None:
        if not _is_str(issue.get("title")):
            offending.append("issue.title: must be a string")
        labels = issue.get("labels")
        if not (isinstance(labels, list) and all(_is_str(x) for x in labels)):
            offending.append("issue.labels: must be an array of strings")
        if issue.get("classification") not in _CLASSIFICATIONS \
                and not (issue.get("classification") is None and unreached("1.1")):
            offending.append(f"issue.classification: must be one of {_CLASSIFICATIONS}")
        rationale = issue.get("classification_rationale")
        if not (rationale is None or _is_str(rationale)):
            offending.append("issue.classification_rationale: must be a string or null")

    scratch = sect("scratch")
    arm = None
    if scratch is not None:
        arm = scratch.get("arm")
        if arm not in _SCRATCH_ARMS:
            offending.append(f"scratch.arm: must be one of {_SCRATCH_ARMS}")
            arm = None
        for key in ("scratch_dir", "run_scratch", "issue_body_path", "resolved_ac_path"):
            v = scratch.get(key)
            if not (v is None or _is_str(v)):
                offending.append(f"scratch.{key}: must be a string or null")
        for key in ("issue_body_path", "resolved_ac_path"):
            v = scratch.get(key)
            contained = _within_checkout(v, checkout_real, offending, f"scratch.{key}") \
                if _is_str(v) else None
            # On proceed these two paths are load-bearing carry-forward inputs: require each
            # non-null and read it, so a missing/empty/directory/unreadable/non-UTF-8 body or AC
            # file refuses (exit 2 naming the field) instead of flowing downstream as authoritative.
            # Read only a contained path — a containment-refused path is never opened (an escaping
            # symlink or absolute /dev/zero would otherwise hang the read instead of failing closed).
            if not stop:
                if not _is_str(v):
                    offending.append(
                        f"scratch.{key}: must be a non-null path when outcome is proceed")
                elif contained:
                    text = _read_secondary(v, f"scratch.{key}", offending)
                    if text is not None and not text.strip():
                        offending.append(
                            f"scratch.{key}: the file is empty when outcome is proceed")

    home = _intake_home(checkout_real, issue_number, arm) if arm else None
    if home is not None:
        _handoff_resolves_to(
            handoff_file, os.path.join(home, f"intake-handoff-{issue_number}.json"), offending,
            f"handoff-file: {handoff_file!r} does not resolve to the {arm} intake home {home!r}")
        rs = scratch.get("run_scratch") if scratch is not None else None
        if _is_str(rs):
            try:
                if os.path.realpath(rs) != os.path.realpath(home):
                    offending.append(
                        f"scratch.run_scratch: {rs!r} does not resolve to the {arm} intake home")
            except ValueError:
                offending.append("scratch.run_scratch: is not a resolvable path (embedded NUL byte)")

    workpad = sect("workpad")
    if workpad is not None:
        wid = workpad.get("id")
        if not (_is_str(wid) or _is_int(wid) or (wid is None and unreached("1.3"))):
            offending.append("workpad.id: must be a string or integer")
        if not (_is_str(workpad.get("observed_status"))
                or (workpad.get("observed_status") is None and unreached("1.3"))):
            offending.append("workpad.observed_status: must be a string")
        snapshot_path = workpad.get("snapshot_path")
        snapshot_path_contained = None
        if snapshot_path is None:
            if not stop:
                offending.append("workpad.snapshot_path: must be non-null when outcome is proceed")
        elif not _is_str(snapshot_path):
            offending.append("workpad.snapshot_path: must be a string or null")
        else:
            snapshot_path_contained = _within_checkout(
                snapshot_path, checkout_real, offending, "workpad.snapshot_path")
        if not _is_str(workpad.get("handoff_provenance")):
            offending.append("workpad.handoff_provenance: must be a string")
        resume_kind = workpad.get("resume_kind")
        if not (resume_kind is None or resume_kind in _INTAKE_RESUME_KINDS):
            offending.append(
                f"workpad.resume_kind: must be one of {_INTAKE_RESUME_KINDS} or null")
        snapshot = workpad.get("snapshot")
        if not isinstance(snapshot, dict):
            offending.append("workpad.snapshot: must be an object")
        else:
            result = snapshot.get("result")
            if not _is_str(result):
                offending.append("workpad.snapshot.result: must be a string")
            elif not stop and result != "exported":
                offending.append(
                    "workpad.snapshot.result: must be 'exported' when outcome is proceed")
            cause = snapshot.get("cause")
            if not (cause is None or _is_str(cause)):
                offending.append("workpad.snapshot.cause: must be a string or null")
            comment_id = snapshot.get("comment_id")
            if comment_id is not None and wid is not None \
                    and not _canon_str_eq(comment_id, wid):
                offending.append(
                    "workpad.snapshot.comment_id: must equal workpad.id by canonical string form")
            updated_at = snapshot.get("updated_at")
            if not (updated_at is None or _is_str(updated_at)):
                offending.append("workpad.snapshot.updated_at: must be a string or null")
            nbytes = snapshot.get("bytes")
            nsha = snapshot.get("sha256")
            if not stop:
                if nbytes is None:
                    offending.append(
                        "workpad.snapshot.bytes: must be non-null when outcome is proceed")
                if nsha is None:
                    offending.append(
                        "workpad.snapshot.sha256: must be non-null when outcome is proceed")
            if _is_str(snapshot_path) and snapshot_path_contained \
                    and (nbytes is not None or nsha is not None):
                raw = _read_secondary(snapshot_path, "workpad.snapshot_path", offending,
                                      binary=True)
                if raw is not None:
                    if nbytes is not None and nbytes != len(raw):
                        offending.append(
                            f"workpad.snapshot.bytes: {nbytes!r} != the snapshot file length "
                            f"{len(raw)}")
                    if nsha is not None and nsha != hashlib.sha256(raw).hexdigest():
                        offending.append(
                            "workpad.snapshot.sha256: does not match the snapshot file's lowercase "
                            "hex digest")

    p2 = sect("phase2_resume")
    if p2 is not None:
        resume_kind = p2.get("resume_kind")
        if not (resume_kind is None or resume_kind in _INTAKE_RESUME_KINDS):
            offending.append(
                f"phase2_resume.resume_kind: must be one of {_INTAKE_RESUME_KINDS} or null")
        plan_rows = p2.get("plan_rows")
        if not (isinstance(plan_rows, list) and all(_is_str(x) for x in plan_rows)):
            offending.append("phase2_resume.plan_rows: must be an array of strings")
        if not isinstance(p2.get("code_sweeps_complete"), bool):
            offending.append("phase2_resume.code_sweeps_complete: must be a JSON boolean")

    if not stop:
        if not isinstance(completed, dict):
            offending.append("completed_steps: must be an object when outcome is proceed")
        else:
            for sid in _COMPLETED_STEP_IDS:
                allowed = {"complete"}
                if sid == "1.0":
                    allowed.add("best-effort-warning")
                if sid == "1.1.5" and arm == "NOT_IGNORED":
                    allowed.add("not-applicable")
                if completed.get(sid) not in allowed:
                    offending.append(
                        f"completed_steps[{sid}]: must be one of {sorted(allowed)}")
    elif completed is not None and not isinstance(completed, dict):
        offending.append("completed_steps: must be an object or null")

    dependency = sect("dependency")
    if dependency is not None:
        result = dependency.get("result")
        if not stop and result != "PROCEED":
            offending.append("dependency.result: must be 'PROCEED' when outcome is proceed")
        elif stop and not (result is None or _is_str(result)):
            offending.append("dependency.result: must be a string or null")
        held_note = dependency.get("held_note")
        if not (held_note is None or _is_str(held_note)):
            offending.append("dependency.held_note: must be a string or null")

    ext = data.get("extension")
    _check_extension(ext, offending)
    if isinstance(ext, dict):
        parent_digest, worker_digest = ext.get("parent_digest"), ext.get("worker_digest")
        if parent_digest is not None and worker_digest is not None \
                and parent_digest != worker_digest:
            offending.append(
                "extension: parent_digest and worker_digest must agree when both non-null")

    for arr_name in ("prior_decisions", "corrections", "blockers"):
        arr = data.get(arr_name)
        if arr is None:
            if not stop:
                offending.append(f"{arr_name}: must be a non-null array when outcome is proceed")
        elif not isinstance(arr, list):
            offending.append(f"{arr_name}: must be an array or null")
        else:
            for i, item in enumerate(arr):
                if not (isinstance(item, dict) and _is_str(item.get("action"))
                        and _is_str(item.get("source")) and _is_str(item.get("authority"))
                        and _is_str(item.get("evidence"))):
                    offending.append(
                        f"{arr_name}[{i}]: must be an object with string "
                        "action/source/authority/evidence")
    warnings = data.get("warnings")
    if warnings is None:
        if not stop:
            offending.append("warnings: must be a non-null array when outcome is proceed")
    elif not (isinstance(warnings, list) and all(_is_str(w) for w in warnings)):
        offending.append("warnings: must be an array of strings or null")

    return not offending, {"offending": offending, "projection": _intake_projection(data)}


def _validate_issue_claim_audit(data, *, checkout_root, dispatch_id, issue_number, base, freshness,
                                run_scratch, handoff_file):
    """Classify a Phase 1.6 issue-claim-audit handoff (issue #700). `result["projection"]` is the
    carry-forward dict `main` prints on exit 0. The reader takes `record_validation`/
    `projection_validation` as the worker's attestations and runs no audit gate itself."""
    if not isinstance(data, dict):
        return False, {"offending": [f"handoff must be a JSON object, not {type(data).__name__}"],
                       "projection": None}
    offending = []
    req = _make_req(data, offending)
    checkout_real = os.path.realpath(checkout_root)
    outcome = data.get("outcome")
    proceed = outcome == "proceed"

    req("schema_version", lambda v: v == SCHEMA_VERSION, f"must be {SCHEMA_VERSION}")
    req("issue_number", lambda v: v == issue_number,
        f"must equal the dispatched issue {issue_number}")
    req("dispatch_id", lambda v: v == dispatch_id,
        "must equal the current dispatch id (a mismatch is a stale or duplicate return)")
    req("repo_root", _is_str, "must be a string")
    req("base", lambda v: v == base, "must equal the dispatched base")
    req("freshness", lambda v: v == freshness, "must equal the dispatched freshness")
    _check_repo_root_identity(data, checkout_root, offending)
    req("outcome", lambda v: v in _AUDIT_OUTCOMES, f"must be one of {_AUDIT_OUTCOMES}")

    _before_rs = len(offending)
    run_scratch_real = _resolves_within(run_scratch, checkout_real, offending, "run-scratch")
    # run_scratch is contained only when it resolved AND appended no containment offender —
    # _resolves_within returns the resolved path even for a resolvable escape, so a bare non-None
    # check would let an escaping-yet-resolvable run_scratch anchor the record_path read below.
    run_scratch_contained = run_scratch_real is not None and len(offending) == _before_rs
    if run_scratch_real is not None:
        expected_hf = os.path.join(run_scratch_real, f"issue-claim-audit-handoff-{issue_number}.json")
        _handoff_resolves_to(
            handoff_file, expected_hf, offending,
            f"handoff-file: {handoff_file!r} does not resolve to {expected_hf!r} "
            "inside the run scratch")

    if outcome in ("blocked-policy", "blocked-capability", "error") \
            and not (_is_str(data.get("blocked_reason")) and data["blocked_reason"].strip()):
        offending.append("blocked_reason: must be a non-empty string on this stop record (incomplete)")

    path_contained = {}
    for key in ("record_path", "projection_path"):
        v = data.get(key)
        if v is not None and not _is_str(v):
            offending.append(f"{key}: must be a string or null")
        elif _is_str(v) and run_scratch_real is not None:
            # Track whether containment passed (no offender appended) so the proceed read below
            # never opens a containment-refused path — symmetric with the intake side, where a
            # read of an escaping /dev/zero or FIFO would hang the validator instead of failing
            # closed. An unresolvable run-scratch leaves the key absent → the read is skipped.
            _before = len(offending)
            _resolves_within(v, run_scratch_real, offending, key)
            path_contained[key] = len(offending) == _before

    for key in ("record_validation", "projection_validation"):
        v = data.get(key)
        if v is not None and v not in _RECORD_PROJ_VALIDATION:
            offending.append(f"{key}: must be one of {_RECORD_PROJ_VALIDATION} or null")
        if proceed and v != "passed":
            offending.append(f"{key}: must be 'passed' when outcome is proceed")

    disp = data.get("projection_disposition")
    if disp is not None and not _is_str(disp):
        offending.append("projection_disposition: must be a string or null")
    if proceed and disp != "represented":
        offending.append("projection_disposition: must be 'represented' when outcome is proceed")

    pass_dispositions = data.get("pass_dispositions")
    if pass_dispositions is not None and not (
            isinstance(pass_dispositions, dict)
            and all(_is_str(x) for x in pass_dispositions.values())):
        offending.append("pass_dispositions: must be an object of string values or null")

    workpad_write = data.get("workpad_write")
    if workpad_write is not None and not (
            isinstance(workpad_write, dict) and _is_str(workpad_write.get("outcome"))
            and _is_str(workpad_write.get("remedy"))):
        offending.append(
            "workpad_write: must be an object with string outcome and remedy or null")
    if proceed:
        if not isinstance(workpad_write, dict):
            offending.append("workpad_write: must be a non-null object when outcome is proceed")
        elif workpad_write.get("remedy") != "none":
            offending.append("workpad_write.remedy: must be 'none' when outcome is proceed")

    for key in _AUDIT_ARRAYS:
        v = data.get(key)
        if v is not None and not isinstance(v, list):
            offending.append(f"{key}: must be an array or null")

    if outcome == "blocked-specification":
        v = data.get("unmatched_desired_behavior")
        if not (isinstance(v, list) and v):
            offending.append(
                "unmatched_desired_behavior: must be a non-empty array on blocked-specification")

    if proceed:
        for key in ("prior_decisions", "prior_corrections", "superseding_assumptions",
                    "external_facts", "pass5_workflow_resident_acs",
                    "pass2_wrongly_excluded_surfaces"):
            if not isinstance(data.get(key), list):
                offending.append(f"{key}: must be a non-null array when outcome is proceed")
        for key in ("unmatched_desired_behavior", "unresolved_blockers"):
            v = data.get(key)
            if not isinstance(v, list) or v:
                offending.append(f"{key}: must be an empty array when outcome is proceed")
        record_path = data.get("record_path")
        if not _is_str(record_path):
            offending.append("record_path: must be a non-null path when outcome is proceed")
        elif run_scratch_contained and path_contained.get("record_path"):
            text = _read_secondary(record_path, "record_path", offending)
            if text is not None and not text.strip():
                offending.append("record_path: the record file is empty when outcome is proceed")

    return not offending, {"offending": offending, "projection": _audit_projection(data)}


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Validate an implement-worker JSON handoff before the parent honours it.")
    parser.add_argument("--schema",
                        choices=("review-fix", "finalization", "intake", "issue-claim-audit"),
                        default="review-fix",
                        help="which handoff schema to validate (default: review-fix)")
    parser.add_argument("--handoff-file", required=True,
                        help="path to the worker's JSON handoff record")
    parser.add_argument("--checkout-root", required=True,
                        help="the implement checkout root; artifact paths must resolve inside it")
    parser.add_argument("--dispatch-id", required=True,
                        help="the current dispatch id; a mismatch is a stale/duplicate return")
    parser.add_argument("--issue-number", required=True, type=int,
                        help="the dispatched issue number, cross-checked against the handoff")
    # Per-schema operands: argparse cannot make `required` conditional on --schema, so these are
    # optional here and enforced post-parse via parser.error (exit 2, no stdout) for their schema.
    parser.add_argument("--run-id", help="intake schema: the current run id (canonical-string)")
    parser.add_argument("--run-attempt",
                        help="intake schema: the current run attempt (canonical-string)")
    parser.add_argument("--run-scratch",
                        help="issue-claim-audit schema: the run-scratch dir the handoff resolves in")
    parser.add_argument("--base", help="issue-claim-audit schema: the dispatched base branch")
    parser.add_argument("--freshness", help="issue-claim-audit schema: the dispatched freshness")
    args = parser.parse_args(argv)

    if args.schema == "intake":
        for _name, _val in (("--run-id", args.run_id), ("--run-attempt", args.run_attempt)):
            if _val is None:
                parser.error(f"{_name} is required for --schema intake")
    if args.schema == "issue-claim-audit":
        for _name, _val in (("--run-scratch", args.run_scratch), ("--base", args.base),
                            ("--freshness", args.freshness)):
            if _val is None:
                parser.error(f"{_name} is required for --schema issue-claim-audit")

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

    if args.schema in ("finalization", "intake", "issue-claim-audit") \
            and not isinstance(data, dict):
        # These schemas treat a non-object top level as structurally unusable (exit 3) — do NOT
        # unify it with the review-fix schema's exit-2 non-conforming path; the divergence is
        # deliberate (issue #539 AC5, issue #700 AC12).
        print(f"validate-review-fix-handoff: the {args.schema} handoff is not a JSON object — "
              "failing closed", file=sys.stderr)
        return 3

    if args.schema == "intake":
        conforming, result = _validate_intake(
            data, checkout_root=args.checkout_root, dispatch_id=args.dispatch_id,
            issue_number=args.issue_number, run_id=args.run_id, run_attempt=args.run_attempt,
            handoff_file=args.handoff_file)
    elif args.schema == "issue-claim-audit":
        conforming, result = _validate_issue_claim_audit(
            data, checkout_root=args.checkout_root, dispatch_id=args.dispatch_id,
            issue_number=args.issue_number, base=args.base, freshness=args.freshness,
            run_scratch=args.run_scratch, handoff_file=args.handoff_file)
    elif args.schema == "finalization":
        conforming, result = _validate_finalization(
            data, checkout_root=args.checkout_root,
            dispatch_id=args.dispatch_id, issue_number=args.issue_number)
    else:
        conforming, result = validate_handoff(
            data, checkout_root=args.checkout_root,
            dispatch_id=args.dispatch_id, issue_number=args.issue_number)
    if conforming:
        # The intake and issue-claim-audit schemas print one compact JSON line of carry-forward
        # fields on exit 0; the other two print nothing on success (issue #700).
        if args.schema in ("intake", "issue-claim-audit"):
            print(json.dumps(result["projection"], separators=(",", ":")))
        return 0
    print("validate-review-fix-handoff: the worker handoff is unusable — "
          + "; ".join(result["offending"]), file=sys.stderr)
    if args.schema == "intake" and data.get("outcome") in _INTAKE_STOP_OUTCOMES \
            and _is_str(data.get("blocked_reason")) and data["blocked_reason"].strip():
        # The worker's own stop cause still reaches the Blocked record (issue #983).
        print(f"validate-review-fix-handoff: worker outcome {data['outcome']}: "
              f"{data['blocked_reason']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

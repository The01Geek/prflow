#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Orchestrator-owned prepare/check handoff for the Phase-3.4 AC verifiers (issue #219).

Phase 3.4 dispatches two fresh-context verifiers (evidence + claim). Previously the
orchestrator copied each returned report into a JSON file before running
`reconcile-ac-verifiers.py`; that transcription seam could drop a disposition slot or an
evidence reason, forcing a whole report to reconcile `unestablished`. This helper removes the
copy: the verifiers Write their raw JSON reports directly to per-attempt destinations this
helper allocates, and this helper — never a verifier — checks the checkout for drift before
reconciliation is accepted.

Two subcommands:

  prepare --issue <N>
    Capture the five-field `checkout-fingerprint.py` baseline, allocate a FRESH per-attempt
    directory beneath the checkout's `.prflow/tmp/` (so every first-party write the dispatch
    makes lands in ignored space), mint distinct evidence/claim report destinations plus the
    single flight's state/logs directories inside it, and print those paths as one JSON object
    the orchestrator passes by value into the two dispatch prompts and the later `check` call.
    Fresh allocation is what stops a previous attempt's report from being reused.

  check --attempt-dir <dir> --evidence-file <path> --claim-file <path>
    Re-run the fingerprint and compare it field-by-field against the baseline `prepare` saved.
    An UNCHANGED fingerprint permits report processing: invoke the existing reconciler on the
    two assigned files and pass its JSON result through unchanged. A changed fingerprint, a
    missing baseline, and a failed measurement are each independently blocking — the gate does
    not proceed, and the failure names the changed fingerprint field(s) and, for the tracked
    and untracked fields, the offending `git status --porcelain` paths. The helper only reads
    and reports: it performs no rollback, deletion, or staging.

The guard reuses `checkout-fingerprint.py`'s producer, so it covers exactly what that
fingerprint covers — checkout identity, HEAD, staged content, tracked working content, and
non-ignored untracked content — and, by construction, nothing about ignored-file contents or
a transient change reverted before the measurement. It detects residual drift across the
verifier pair; it does not attribute a change to one verifier and is not hostile-agent
containment.

Exit codes:
    0 — reconciliation produced on a clean checkout (stdout is `reconcile-ac-verifiers.py`'s
        own JSON, unchanged — even when it reports blocking criteria, a normal reconciliation
        outcome, not a helper failure)
    1 — a `prepare` failure (fingerprint capture, directory allocation, or symlink rejection)
    2 — a `check` guard failure: drift, a missing/unreadable baseline, a failed measurement,
        or a symlink-rejected path — all independently blocking. stdout carries a guard JSON
        object naming the cause; stderr carries a breadcrumb.
    3 — a `check` report file was unreadable/malformed (passed through from the reconciler)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
# The single second under `.prflow/tmp/` every attempt directory is minted below, so a
# consumer whose scaffolded `.prflow/.gitignore` ignores only `tmp/` still ignores it.
_ATTEMPT_ROOT_PARTS = (".prflow", "tmp", "ac-verifier-artifacts")
_GIT = os.environ.get("DEVFLOW_GIT") or "git"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never at import: it mutates a test importer's streams."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _load_sibling(modname: str, filename: str):
    """Import a hyphen-named sibling script by file path (they are not importable by name)."""
    path = os.path.join(_HERE, filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling helper {filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _GuardError(Exception):
    """A checkout-integrity guard could not be satisfied (independently blocking)."""


def _toplevel() -> str:
    # An OSError (e.g. DEVFLOW_GIT names a missing binary) must reach the caller's guard
    # as a failed measurement (exit 2), never an uncaught traceback (exit 1).
    try:
        proc = subprocess.run(
            [_GIT, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise _GuardError(f"could not run git: {exc}") from exc
    top = proc.stdout.strip()
    if proc.returncode != 0 or not top:
        raise _GuardError(f"not a git checkout: {proc.stderr.strip()}")
    return top


def _reject_symlink_path(path: str, boundary: str) -> None:
    """Reject a symlink destination or a symlink in any parent component below `boundary`.

    `path` must resolve to a location under `boundary` with no symlink component between the
    two — a symlink anywhere along that span could redirect a verifier's write outside the
    ignored attempt directory. The boundary itself (`.prflow/tmp/`) is trusted; every
    component from it down to the leaf is checked.
    """
    abs_boundary = os.path.abspath(boundary)
    abs_path = os.path.abspath(path)
    if os.path.islink(abs_path):
        raise _GuardError(f"destination is a symlink: {abs_path}")
    try:
        rel = os.path.relpath(abs_path, abs_boundary)
    except ValueError as exc:
        raise _GuardError(f"path is not relative to the attempt boundary: {abs_path}") from exc
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise _GuardError(f"path escapes the attempt boundary: {abs_path}")
    prefix = abs_boundary
    for part in rel.split(os.sep):
        if part in ("", os.curdir):
            continue
        prefix = os.path.join(prefix, part)
        if os.path.islink(prefix):
            raise _GuardError(f"a parent directory in the path is a symlink: {prefix}")


def _fingerprint(fp_mod) -> dict:
    # OSError covers a subprocess that could not spawn git at all (a bad DEVFLOW_GIT), which
    # build_fingerprint does not wrap in _GitError — route it to the exit-2 guard, not a traceback.
    try:
        return fp_mod.build_fingerprint()
    except (fp_mod._GitError, OSError) as exc:
        raise _GuardError(f"could not measure the checkout fingerprint: {exc}") from exc


def _porcelain(top: str) -> list[str]:
    """`git status --porcelain` lines, or [] when it cannot be read (best-effort detail only)."""
    try:
        proc = subprocess.run(
            [_GIT, "status", "--porcelain"],
            cwd=top, capture_output=True, text=True, check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _tracked_offenders(lines: list[str]) -> list[str]:
    """Paths whose staged/working state marks a tracked change (never an untracked `??`)."""
    out = []
    for ln in lines:
        if len(ln) < 3:
            continue
        code = ln[:2]
        if code == "??":
            continue
        out.append(ln[3:])
    return out


def _untracked_offenders(lines: list[str]) -> list[str]:
    return [ln[3:] for ln in lines if ln.startswith("?? ")]


def _cmd_prepare(args) -> int:
    fp_mod = _load_sibling("_ava_checkout_fingerprint", "checkout-fingerprint.py")
    try:
        top = _toplevel()
        baseline = _fingerprint(fp_mod)
    except _GuardError as exc:
        print(f"ac-verifier-artifacts: prepare: {exc}", file=sys.stderr)
        return 1

    attempt_root = os.path.join(top, *_ATTEMPT_ROOT_PARTS)
    try:
        os.makedirs(attempt_root, exist_ok=True)
        _reject_symlink_path(attempt_root, os.path.join(top, ".prflow", "tmp"))
        attempt_dir = tempfile.mkdtemp(prefix=f"{args.issue}-", dir=attempt_root)
        os.chmod(attempt_dir, 0o700)
        flight_state = os.path.join(attempt_dir, "flight", "state")
        flight_logs = os.path.join(attempt_dir, "flight", "logs")
        os.makedirs(flight_state, exist_ok=True)
        os.makedirs(flight_logs, exist_ok=True)
        evidence_path = os.path.join(attempt_dir, "evidence-report.json")
        claim_path = os.path.join(attempt_dir, "claim-report.json")
        baseline_path = os.path.join(attempt_dir, "baseline-fingerprint.json")
        # Reject a symlink anywhere along each destination before handing it out, so a verifier
        # can never be pointed at a link that redirects its write outside the ignored dir.
        boundary = os.path.join(top, ".prflow", "tmp")
        for dest in (evidence_path, claim_path, baseline_path):
            _reject_symlink_path(dest, boundary)
        _atomic_write_json(baseline_path, baseline)
    except (_GuardError, OSError) as exc:
        print(f"ac-verifier-artifacts: prepare: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps({
        "attempt_dir": attempt_dir,
        "evidence_report_path": evidence_path,
        "claim_report_path": claim_path,
        "baseline_fingerprint_path": baseline_path,
        "flight_state_dir": flight_state,
        "flight_logs_dir": flight_logs,
    }, sort_keys=True) + "\n")
    return 0


def _atomic_write_json(path: str, obj) -> None:
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _cmd_check(args) -> int:
    fp_mod = _load_sibling("_ava_checkout_fingerprint", "checkout-fingerprint.py")
    attempt_dir = os.path.abspath(args.attempt_dir)
    baseline_path = os.path.join(attempt_dir, "baseline-fingerprint.json")

    try:
        top = _toplevel()
    except _GuardError as exc:
        print(f"ac-verifier-artifacts: check: {exc}", file=sys.stderr)
        print(json.dumps({"guard": "failed-measurement", "detail": str(exc)}, sort_keys=True))
        return 2

    try:
        # Reject a symlink anywhere from the trusted `.prflow/tmp` root down to each report
        # leaf — the same boundary prepare uses, never the untrusted --attempt-dir value — so a
        # tampered handoff cannot make the reconciler read through a symlink outside ignored space.
        boundary = os.path.join(top, ".prflow", "tmp")
        for dest in (args.evidence_file, args.claim_file):
            _reject_symlink_path(dest, boundary)
    except _GuardError as exc:
        print(f"ac-verifier-artifacts: check: {exc}", file=sys.stderr)
        print(json.dumps({"guard": "path-rejected", "detail": str(exc)}, sort_keys=True))
        return 2

    try:
        with open(baseline_path, encoding="utf-8") as fh:
            baseline = json.load(fh)
        if not isinstance(baseline, dict):
            raise ValueError("baseline is not a JSON object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ac-verifier-artifacts: check: missing/unreadable baseline: {exc}",
              file=sys.stderr)
        print(json.dumps({"guard": "missing-baseline", "detail": str(exc)}, sort_keys=True))
        return 2

    try:
        fresh = _fingerprint(fp_mod)
    except _GuardError as exc:
        print(f"ac-verifier-artifacts: check: {exc}", file=sys.stderr)
        print(json.dumps({"guard": "failed-measurement", "detail": str(exc)}, sort_keys=True))
        return 2

    # Compare over the union of both key sets, so a field present on only one side (a shape
    # change) counts as drift: its absent side reads None, which never equals a real value.
    changed = sorted(k for k in set(fresh) | set(baseline) if baseline.get(k) != fresh.get(k))
    if changed:
        offending: dict[str, list[str]] = {}
        if "tracked_digest" in changed or "untracked_digest" in changed:
            porcelain = _porcelain(top)
            if "tracked_digest" in changed:
                offending["tracked_digest"] = _tracked_offenders(porcelain)
            if "untracked_digest" in changed:
                offending["untracked_digest"] = _untracked_offenders(porcelain)
        print(f"ac-verifier-artifacts: check: checkout drift — changed fields "
              f"{changed}; the run's implementation may be contaminated. Resolve the "
              f"change (a verification command that leaves non-ignored artifacts must "
              f"gitignore them) before a fresh verification attempt.", file=sys.stderr)
        print(json.dumps(
            {"guard": "checkout-drift", "changed_fields": changed,
             "offending_paths": offending}, sort_keys=True))
        return 2

    recon = _load_sibling("_ava_reconcile", "reconcile-ac-verifiers.py")
    try:
        evidence_records = recon._load_report(args.evidence_file)
        claim_records = recon._load_report(args.claim_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ac-verifier-artifacts: check: could not read a verifier report: {exc}",
              file=sys.stderr)
        return 3
    print(json.dumps(recon.reconcile(evidence_records, claim_records), indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ac-verifier-artifacts.py",
        description=(
            "Prepare per-attempt destinations for the Phase-3.4 AC verifiers and, after they "
            "write their reports, check the checkout for drift before reconciliation."),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_prep = sub.add_parser(
        "prepare",
        help="Allocate a fresh per-attempt directory and print the report/flight paths.")
    p_prep.add_argument("--issue", required=True, help="the issue number (a naming prefix)")
    p_prep.set_defaults(func=_cmd_prepare)
    p_check = sub.add_parser(
        "check",
        help="Guard the checkout against drift, then reconcile the two assigned reports.")
    p_check.add_argument("--attempt-dir", required=True,
                         help="the attempt directory prepare allocated")
    p_check.add_argument("--evidence-file", required=True,
                         help="the evidence verifier's assigned report path")
    p_check.add_argument("--claim-file", required=True,
                         help="the claim verifier's assigned report path")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv=None) -> int:
    _force_utf8_streams()
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

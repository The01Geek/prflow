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
    Write the attempt root's `.gitignore` holding the single line `*`, THEN capture the
    five-field `checkout-fingerprint.py` baseline, allocate a FRESH per-attempt directory
    beneath the checkout's `.prflow/tmp/` (so every first-party write the dispatch makes lands
    in ignored space), mint distinct evidence/claim report destinations plus the `criteria_path`
    the orchestrator writes the tagged criteria list to before dispatch, and print those paths
    as one JSON object the orchestrator passes by value into the two dispatch prompts and the
    later `check` call. The `.gitignore` is written before the baseline so every attempt file —
    this attempt's and any earlier attempt's left in the root — drops out of git's untracked
    listing before the baseline rather than reading as drift in a repo whose `.prflow/tmp/` is
    not itself gitignored. Fresh allocation is what stops a previous attempt's report from being
    reused. (Phase 3.4 mints no verification flight — the evidence verifier runs its command
    directly — so `prepare` prints no flight state/logs directory.)

  check --attempt-dir <dir> --evidence-file <path> --criteria-file <path> [--claim-file <path>]
    Re-run the fingerprint and compare it field-by-field against the baseline `prepare` saved.
    An UNCHANGED fingerprint permits report processing: read the tagged criteria list, invoke
    the reconciler on the assigned files with that list, write a bounded per-criterion
    dispositions record to `ac-dispositions.md` in the attempt directory, and print one
    compact routing line of JSON — `all_satisfied`, `blocking`, each criterion's `criterion`,
    `status`, `remedy` and `reason`, and the record's `dispositions_path`. `--claim-file` is
    optional: omit it only when the criteria file names no `command` criterion (every criterion
    then reconciles from the evidence report alone); omitting it while any criterion is
    `command`, and a supplied `--claim-file` that is missing or unreadable, each exit 3 with no
    reconciliation printed — as does a criteria file that is missing, unreadable, or not a bare
    JSON list. A changed fingerprint, a missing baseline, and a failed measurement are each
    independently blocking — the gate does not proceed, and the failure names the changed
    fingerprint field(s) and, for the tracked field the offending `git status --porcelain`
    paths and for the untracked field the offending `git ls-files -o --exclude-standard` paths
    (which name a stray file inside an untracked directory that porcelain collapses to the
    directory). The helper only reads, reconciles, and writes the dispositions record; it
    performs no rollback, deletion, or staging.

The guard reuses `checkout-fingerprint.py`'s producer, so it covers exactly what that
fingerprint covers — checkout identity, HEAD, staged content, tracked working content, and
non-ignored untracked content — and, by construction, nothing about ignored-file contents or
a transient change reverted before the measurement. It detects residual drift across the
verifier pair; it does not attribute a change to one verifier and is not hostile-agent
containment.

Exit codes:
    0 — reconciliation produced on a clean checkout: stdout is the one-line routing JSON
        (`all_satisfied`, `blocking`, the per-criterion routing projection, and
        `dispositions_path`) and the bounded per-criterion record is written to
        `ac-dispositions.md` in the attempt directory — even when the reconciliation reports
        blocking criteria, a normal outcome, not a helper failure
    1 — a `prepare` failure (fingerprint capture, directory allocation, or symlink rejection)
    2 — a `check` guard failure: drift, a missing/unreadable baseline, a failed measurement,
        or a symlink-rejected path (the `ac-dispositions.md` destination included) — all
        independently blocking. stdout carries a guard JSON object naming the cause; stderr
        carries a breadcrumb.
    3 — a `check` input was unestablished, no reconciliation printed: a report or the criteria
        file unreadable/malformed/not-a-bare-list, `--claim-file` omitted while a `command`
        criterion is present, a supplied `--claim-file` missing/unreadable, or the
        `ac-dispositions.md` record could not be written (empty stdout, a stderr line prefixed
        `could not write the dispositions record:`)
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
# The DEFAULT attempt root is `.prflow/tmp/implement/<issue>/ac-verifier-artifacts/`
# (issue #240); --scratch-base overrides it (the not-ignored arm passes flat `.prflow/tmp`).
# Kept under `.prflow/tmp/` either way, so a `.gitignore` ignoring only `tmp/` still covers it.
_ATTEMPT_ROOT_PREFIX_PARTS = (".prflow", "tmp", "implement")
_ATTEMPT_ROOT_LEAF = "ac-verifier-artifacts"
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


def _fwd(path: str) -> str:
    """Emit a machine-read path with forward slashes only.

    Keyed off the active path flavour, so a POSIX host — where a backslash is a legal
    filename byte — is byte-for-byte unchanged, while a native-Windows Python stops
    handing the orchestrator a `C:/repo\\.prflow` mix of both separators."""
    return path.replace(os.path.sep, "/") if os.path.sep != "/" else path


class _GuardError(Exception):
    """A checkout-integrity guard could not be satisfied (independently blocking)."""


def _toplevel() -> str:
    # An OSError (e.g. DEVFLOW_GIT names a missing binary) must reach the caller's guard
    # as a failed measurement (exit 2), never an uncaught traceback (exit 1).
    try:
        proc = subprocess.run(
            [_GIT, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", check=False,
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
            cwd=top, capture_output=True, text=True, encoding="utf-8", check=False,
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


def _untracked_offenders(top: str) -> list[str]:
    """Untracked, non-ignored paths from git's exclude-aware listing — the same source the
    fingerprint's `untracked_digest` reads. `git status --porcelain` collapses an untracked
    directory to a single `?? dir/` line, so it cannot name a stray file inside one; the
    exclude-aware `ls-files -o` listing names each file, matching what the fingerprint compared."""
    try:
        proc = subprocess.run(
            [_GIT, "ls-files", "-o", "--exclude-standard", "-z"],
            cwd=top, capture_output=True, text=True, encoding="utf-8", check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.split("\0") if p]


def _cmd_prepare(args) -> int:
    fp_mod = _load_sibling("_ava_checkout_fingerprint", "checkout-fingerprint.py")
    try:
        top = _toplevel()
    except _GuardError as exc:
        print(f"ac-verifier-artifacts: prepare: {exc}", file=sys.stderr)
        return 1

    # --scratch-base supplies the run's per-arm scratch home (flat `.prflow/tmp` on the
    # not-ignored arm), so the attempt root is not minted inside a per-issue folder that arm
    # never creates; absent, it keeps the per-issue default.
    if getattr(args, "scratch_base", None):
        attempt_root = os.path.join(top, args.scratch_base, _ATTEMPT_ROOT_LEAF)
    else:
        attempt_root = os.path.join(top, *_ATTEMPT_ROOT_PREFIX_PARTS, str(args.issue), _ATTEMPT_ROOT_LEAF)
    boundary = os.path.join(top, ".prflow", "tmp")
    try:
        # Guard the path BEFORE creating it, so a symlinked component (or a base escaping
        # `.prflow/tmp`) is rejected rather than followed by makedirs.
        _reject_symlink_path(attempt_root, boundary)
        os.makedirs(attempt_root, exist_ok=True)
        # Write the attempt root's `.gitignore` (holding `*`) and capture the baseline only
        # AFTER it exists, so every attempt file under this root — this attempt's and any
        # earlier attempt's — is already excluded from git's untracked listing at baseline
        # time. Without this the baseline would predate the attempt files and `check` would
        # read them as untracked drift in a repo whose `.prflow/tmp/` is not itself gitignored.
        gitignore_path = os.path.join(attempt_root, ".gitignore")
        _reject_symlink_path(gitignore_path, boundary)
        _ensure_star_gitignore(gitignore_path)
        baseline = _fingerprint(fp_mod)
        attempt_dir = tempfile.mkdtemp(prefix=f"{args.issue}-", dir=attempt_root)
        os.chmod(attempt_dir, 0o700)
        evidence_path = os.path.join(attempt_dir, "evidence-report.json")
        claim_path = os.path.join(attempt_dir, "claim-report.json")
        baseline_path = os.path.join(attempt_dir, "baseline-fingerprint.json")
        # The orchestrator writes the tagged criteria list here (with the Write tool) before
        # dispatch, and `check` reads it from here (issue #439).
        criteria_path = os.path.join(attempt_dir, "criteria.json")
        # Reject a symlink anywhere along each destination before handing it out, so a verifier
        # can never be pointed at a link that redirects its write outside the ignored dir.
        for dest in (evidence_path, claim_path, baseline_path, criteria_path):
            _reject_symlink_path(dest, boundary)
        _atomic_write_json(baseline_path, baseline)
    except (_GuardError, OSError) as exc:
        print(f"ac-verifier-artifacts: prepare: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(_prepare_payload(
        attempt_dir, evidence_path, claim_path, baseline_path, criteria_path))
    return 0


def _prepare_payload(attempt_dir, evidence_path, claim_path, baseline_path,
                     criteria_path) -> str:
    """`prepare`'s stdout line — the orchestrator's destinations, forward-slashed."""
    return json.dumps({
        "attempt_dir": _fwd(attempt_dir),
        "evidence_report_path": _fwd(evidence_path),
        "claim_report_path": _fwd(claim_path),
        "baseline_fingerprint_path": _fwd(baseline_path),
        "criteria_path": _fwd(criteria_path),
    }, sort_keys=True) + "\n"


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


def _atomic_write_text(path: str, text: str) -> None:
    """Atomic-replace a UTF-8 text file with `\\n` endings, mirroring `_atomic_write_json`."""
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ensure_star_gitignore(path: str) -> None:
    """Write a `.gitignore` holding the single line `*` when it is absent or its bytes are not
    exactly `*\\n`; an already-correct file is left byte-untouched so a re-run does not rewrite it."""
    try:
        with open(path, "rb") as fh:
            if fh.read() == b"*\n":
                return
    except OSError:
        pass
    _atomic_write_text(path, "*\n")


def _truncate_to_bytes(value: str, limit: int) -> str:
    """Copy `value` unchanged when its UTF-8 length is at most `limit`; otherwise cut it after
    its last whole character within `limit` bytes and append the literal ` [truncated]`."""
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    cut = encoded[:limit]
    while cut:
        try:
            head = cut.decode("utf-8")
            break
        except UnicodeDecodeError:
            cut = cut[:-1]
    else:
        head = ""
    return head + " [truncated]"


def _bounded_dispositions(disp) -> dict:
    """Bound every string slot value in a disposition map to 60 UTF-8 bytes; a non-string
    value passes through unchanged (issue #581)."""
    return {k: (_truncate_to_bytes(v, 60) if isinstance(v, str) else v)
            for k, v in disp.items()}


def _bound_str(value, limit: int):
    """Bound a string value to `limit` UTF-8 bytes; a non-string value passes through unchanged."""
    return _truncate_to_bytes(value, limit) if isinstance(value, str) else value


def _dispositions_line(c: dict) -> dict:
    """Project one reconciled-criterion record into its bounded dispositions-record line (issue
    #681). A `tick` criterion carries only the four always-present keys — complete by
    construction. Any other remedy also carries the fields that explain the block, plus the
    claim-side pair exactly when the criterion's `sides` includes `claim`. `evidence` is bounded
    to 400 bytes, `stated_terms`/`observed_value` to 200 each, and slot values keep the 60-byte
    bound; a non-string value passes through unbounded."""
    line = {
        "criterion": c["criterion"],
        "status": c["status"],
        "remedy": c["remedy"],
        "evidence": _bound_str(c["evidence"], 400),
    }
    if c["remedy"] == "tick":
        return line
    line.update({
        "reason": c["reason"],
        "sides": c["sides"],
        "missing_sides": c["missing_sides"],
        "undischarged_slots": c["undischarged_slots"],
        "stated_terms": _bound_str(c["stated_terms"], 200),
        "observed_value": _bound_str(c["observed_value"], 200),
        "evidence_status_reported": c["evidence_status_reported"],
        "evidence_dispositions": _bounded_dispositions(c["evidence_dispositions"]),
    })
    if "claim" in c["sides"]:
        line["claim_status_reported"] = c["claim_status_reported"]
        line["claim_dispositions"] = _bounded_dispositions(c["claim_dispositions"])
    return line


def _write_dispositions(path: str, criteria: list) -> None:
    """Write the per-criterion dispositions record as a collapsed block (issue #681): a
    `<details><summary>3.4 dispositions: <N> criteria, <K> tick</summary>` first line, one UTF-8
    JSON line per criterion (`ensure_ascii=False`, `\\n` endings) — the single line
    `{"criteria": []}` when the reconciliation had no criteria — and a `</details>` last line."""
    tick = sum(1 for c in criteria if c["remedy"] == "tick")
    summary = (f"<details><summary>3.4 dispositions: {len(criteria)} criteria, "
               f"{tick} tick</summary>\n")
    if not criteria:
        body = json.dumps({"criteria": []}, ensure_ascii=False) + "\n"
    else:
        body = "".join(
            json.dumps(_dispositions_line(c), ensure_ascii=False, sort_keys=True) + "\n"
            for c in criteria)
    _atomic_write_text(path, summary + body + "</details>\n")


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
        # `--claim-file` is optional (issue #439), so it is guarded only when supplied.
        boundary = os.path.join(top, ".prflow", "tmp")
        dispositions_path = os.path.join(attempt_dir, "ac-dispositions.md")
        guarded = [args.evidence_file, args.criteria_file, dispositions_path]
        if args.claim_file is not None:
            guarded.append(args.claim_file)
        for dest in guarded:
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
        if "tracked_digest" in changed:
            offending["tracked_digest"] = _tracked_offenders(_porcelain(top))
        if "untracked_digest" in changed:
            offending["untracked_digest"] = _untracked_offenders(top)
        print(f"ac-verifier-artifacts: check: checkout drift — changed fields "
              f"{changed}; the run's implementation may be contaminated. Resolve the "
              f"change (a verification command that leaves non-ignored artifacts must "
              f"gitignore them) before a fresh verification attempt.", file=sys.stderr)
        print(json.dumps(
            {"guard": "checkout-drift", "changed_fields": changed,
             "offending_paths": offending}, sort_keys=True))
        return 2

    recon = _load_sibling("_ava_reconcile", "reconcile-ac-verifiers.py")
    # The criteria file is agent-authored input (issue #439): a missing/unreadable file or a
    # non-bare-list top-level value (the wrapped `{"criteria": [...]}` envelope included) is an
    # unestablished measurement — exit 3 with no reconciliation printed.
    try:
        class_by_num = recon.parse_criteria(recon._load_criteria(args.criteria_file))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ac-verifier-artifacts: check: could not read the criteria file: {exc}",
              file=sys.stderr)
        return 3
    has_command = any(cls == "command" for cls in class_by_num.values())
    # An omitted --claim-file reconciles every criterion from the evidence report alone, but
    # only when no criterion is `command` (a command criterion needs the claim verifier's
    # independent vote); omitting it while any criterion is command is exit 3.
    if args.claim_file is None:
        if has_command:
            print("ac-verifier-artifacts: check: --claim-file omitted but the criteria file "
                  "names a 'command' criterion, which requires the claim verifier's report",
                  file=sys.stderr)
            return 3
        claim_records = []
    try:
        evidence_records = recon._load_report(args.evidence_file)
        if args.claim_file is not None:
            claim_records = recon._load_report(args.claim_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ac-verifier-artifacts: check: could not read a verifier report: {exc}",
              file=sys.stderr)
        return 3
    result = recon.reconcile(evidence_records, claim_records, class_by_num)
    # Write the full bounded per-criterion record to a file, then print only the compact routing
    # line: the orchestrator routes on the line's closed tokens and reads a criterion's own record
    # line from the file only when its remedy is not `tick`, so the full record never re-enters the
    # orchestrator's context. A write failure is unestablished output (exit 3), not a guard block.
    try:
        _write_dispositions(dispositions_path, result["criteria"])
    except OSError as exc:
        print(f"ac-verifier-artifacts: check: could not write the dispositions record: "
              f"{dispositions_path}: {exc}", file=sys.stderr)
        return 3
    routing = {
        "all_satisfied": result["all_satisfied"],
        "blocking": result["blocking"],
        "criteria": [{"criterion": c["criterion"], "status": c["status"],
                      "remedy": c["remedy"], "reason": c["reason"]}
                     for c in result["criteria"]],
        "dispositions_path": dispositions_path,
    }
    print(json.dumps(routing, sort_keys=True))
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
    p_prep.add_argument(
        "--scratch-base", default=None,
        help="repo-relative per-arm scratch home under .prflow/tmp (issue #240); "
             "absent keeps the per-issue-folder default")
    p_prep.set_defaults(func=_cmd_prepare)
    p_check = sub.add_parser(
        "check",
        help="Guard the checkout against drift, then reconcile the two assigned reports.")
    p_check.add_argument("--attempt-dir", required=True,
                         help="the attempt directory prepare allocated")
    p_check.add_argument("--evidence-file", required=True,
                         help="the evidence verifier's assigned report path")
    p_check.add_argument("--claim-file", default=None,
                         help="the claim verifier's assigned report path; omit only when the "
                              "criteria file names no 'command' criterion (issue #439)")
    p_check.add_argument("--criteria-file", required=True,
                         help="the orchestrator-authored tagged-criteria list (a bare JSON "
                              "list); the class per criterion decides its expected sides")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv=None) -> int:
    _force_utf8_streams()
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Weekly-retrospective delivery outcome record producer (issue #395).

The scheduled retrospective's outward-facing delivery — the state PR push, the
per-finding issue filing, and the report post — happens last and can fail while
the agent step still returns success, so a run could lose state and file nothing
yet conclude success. This helper is the deterministic channel that fixes that:
the retrospective records each required delivery operation's observed outcome in
one run-bound record, and an unconditional workflow post-step classifies that
record and fails the job on any positively-established delivery failure. The
agent's final prose is no longer the authority.

Subcommands:
  init          Seed (or, on an identity match, preserve) the run-bound record
                for one repo/run/attempt, with the always-required operations
                (state_persistence, report_post) `pending`.
  require-op    Mark an operation required and `pending` if it is not already
                present (a selected finding's `filing:<key>`, added before the
                filing helper runs). Idempotent; never resets a resolved status.
  set-op        Record an operation's observed status (success / failure /
                not_applicable) and diagnostic. A recorded `failure` is sticky:
                a later success on the same operation never masks it.
  finalize      Read-and-classify only (no write). Prints one of
                OK / UNESTABLISHED <reason> / FAILED <op: diag[; ...]> and a
                matching ::warning::/::error:: annotation. Exit 0 for OK and
                UNESTABLISHED (an unestablished record never itself fails the
                job); exit 1 for FAILED. A record whose identity does not match
                the caller's run/attempt is foreign and reads UNESTABLISHED.
                The sibling scan output (`<record-dir>/../scan.json`) decides
                whether the always-required ops were due: `[]` (a quiet week)
                satisfies them; a non-empty array subjects a still-pending one
                to a read-only remote check, which makes it a failure only when
                remote state proves it did not happen.
  capabilities  Print `outcome-record-v1` and exit 0 — the workflow's pre-agent
                deployment-capability probe (an older vendored helper lacking
                this subcommand exits 2, so the workflow refuses it).

Failure discipline (mirrors scripts/reception-record.py): after argument parsing,
an error in a command body writes an attributable {"ok": false, "reason": …}
record to STDERR and exits non-zero. Argument errors are argparse's: a missing or
invalid option exits 2 with usage text before any command body runs. Data-only
besides git and finalize's read-only `gh api` check (DEVFLOW_GH, else `gh`): no
remote write, no PyYAML, and no decisive value derived through a non-preflight
PATH tool. `require-op`/`set-op` with no record outside GitHub Actions (a local
run; only the workflow runs `init`) are silent no-ops.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "retro-outcome-record"
CAPABILITY_TOKEN = "outcome-record-v1"
RECORD_DIRNAME = os.path.join(".prflow", "tmp", "retro-outcome")
RECORD_NAME = "outcome-record.json"
GIT = os.environ.get("DEVFLOW_GIT") or "git"
GH = os.environ.get("DEVFLOW_GH") or "gh"
STATE_BRANCH_PREFIX = "prflow/learnings-"  # lib/open-state-pr.sh's produced prefix
REPORT_MARKERS = ("<!-- prflow:audit-report -->", "<!-- devflow:audit-report -->")

# Refreshed-token env for the gh call on native Windows (see gh_fresh_env.py); a
# partial copy without the sibling inherits the ambient token.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gh_fresh_env import fresh_gh_env
except Exception:  # pragma: no cover - partial-copy arm
    def fresh_gh_env(env=None, os_name=None):
        return env

# Operation status vocabulary (closed). `pending` is the AC1 "incomplete" state,
# distinct from `success` and from `not_applicable` (positively established
# non-applicability). Only these reach the record.
STATUS_KINDS = ("pending", "success", "failure", "not_applicable")
# The operations required on EVERY run — a quiet week still owes these, so a
# missing one leaves the record incomplete rather than passing by default.
REQUIRED_OPS = ("state_persistence", "report_post")


def _force_utf8_streams():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fail(reason: str, code: int = 1) -> int:
    sys.stderr.write(json.dumps({"ok": False, "reason": reason}) + "\n")
    return code


def _repo_root(args) -> str:
    """Resolve the repository root for the DEFAULT record-dir path (git toplevel,
    falling back to cwd). An explicit --repo-root or --record-dir bypasses this."""
    if getattr(args, "repo_root", None):
        return args.repo_root
    try:
        proc = subprocess.run(
            [GIT, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return os.getcwd()
    if proc.returncode != 0:
        return os.getcwd()
    try:
        top = proc.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return os.getcwd()
    return top or os.getcwd()


def _record_path(args) -> Path:
    if getattr(args, "record_dir", None):
        d = Path(args.record_dir)
    else:
        d = Path(_repo_root(args)) / RECORD_DIRNAME
    if not d.is_absolute():
        d = Path.cwd() / d
    return d / RECORD_NAME


def _read_record(path: Path) -> tuple[dict | None, str | None]:
    """Read the record object, applying the adversarial malformed-input matrix.

    Returns (obj, None) for a real object, or (None, reason) for every degraded
    shape — array / scalar / valid-falsy / wrong-type all land in `not-object`,
    an absent file in `missing`, an unopenable file in `unreadable`, an empty
    file in `empty`, and a truncated or non-UTF-8 file in `malformed`. No shape
    yields a value a caller would read as a valid record.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"unreadable:{exc.__class__.__name__}"
    if not raw.strip():
        return None, "empty"
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "malformed"
    if not isinstance(obj, dict):
        return None, "not-object"
    return obj, None


def _atomic_write_json(path: Path, obj: dict) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".ror-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _new_record(repo: str, run_id: str, run_attempt: str) -> dict:
    now = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "repo": repo,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "created_at": now,
        "operations": {
            op: {"status": "pending", "diagnostic": None, "observed_at": None}
            for op in REQUIRED_OPS
        },
    }


def _identity_matches(rec: dict, repo: str, run_id: str, run_attempt: str) -> bool:
    return (
        rec.get("kind") == KIND
        and rec.get("repo") == repo
        and str(rec.get("run_id")) == str(run_id)
        and str(rec.get("run_attempt")) == str(run_attempt)
    )


def cmd_init(args) -> int:
    path = _record_path(args)
    existing, _reason = _read_record(path)
    # Preserve a same-run/attempt record's recorded outcomes across a re-init (a
    # stall-backstop resume re-enters init); a record for a DIFFERENT run/attempt
    # is foreign and is replaced, so a prior attempt's failure never bleeds in.
    if existing is not None and _identity_matches(
        existing, args.repo, args.run_id, args.run_attempt
    ) and isinstance(existing.get("operations"), dict):
        record = existing
        ops = record["operations"]
        for op in REQUIRED_OPS:
            if op not in ops:
                ops[op] = {"status": "pending", "diagnostic": None, "observed_at": None}
    else:
        record = _new_record(args.repo, args.run_id, args.run_attempt)
    try:
        _atomic_write_json(path, record)
    except OSError as exc:
        return _fail(f"write_failed:{exc.__class__.__name__}")
    sys.stdout.write(json.dumps({"ok": True, "record_path": str(path)}) + "\n")
    return 0


def _load_for_mutation(path: Path) -> tuple[dict | None, int]:
    record, reason = _read_record(path)
    if reason == "missing" and os.environ.get("GITHUB_ACTIONS") != "true":
        return None, 0  # local run: no record was initialized, nothing to record
    if record is None:
        return None, _fail(f"record_{reason}")
    if record.get("kind") != KIND:
        return None, _fail("record_wrong_kind")
    if not isinstance(record.get("operations"), dict):
        return None, _fail("record_operations_not_object")
    return record, 0


def cmd_require_op(args) -> int:
    path = _record_path(args)
    record, code = _load_for_mutation(path)
    if record is None:
        return code
    ops = record["operations"]
    if args.op_id not in ops:
        ops[args.op_id] = {"status": "pending", "diagnostic": None, "observed_at": None}
    try:
        _atomic_write_json(path, record)
    except OSError as exc:
        return _fail(f"write_failed:{exc.__class__.__name__}")
    sys.stdout.write(json.dumps({"ok": True, "op_id": args.op_id}) + "\n")
    return 0


def cmd_set_op(args) -> int:
    path = _record_path(args)
    record, code = _load_for_mutation(path)
    if record is None:
        return code
    ops = record["operations"]
    current = ops.get(args.op_id)
    # Failure is sticky: a positively-recorded failure is never downgraded by a
    # later success on the same operation, so an operation that failed then
    # "recovered" cannot mask the delivery failure the workflow must fail on.
    if (
        isinstance(current, dict)
        and current.get("status") == "failure"
        and args.status != "failure"
    ):
        sys.stderr.write(
            json.dumps(
                {
                    "ok": True,
                    "warning": "failure_status_preserved",
                    "op_id": args.op_id,
                    "requested_status": args.status,
                }
            )
            + "\n"
        )
    else:
        ops[args.op_id] = {
            "status": args.status,
            "diagnostic": args.diagnostic,
            "observed_at": _now_iso(),
        }
    try:
        _atomic_write_json(path, record)
    except OSError as exc:
        return _fail(f"write_failed:{exc.__class__.__name__}")
    sys.stdout.write(
        json.dumps({"ok": True, "op_id": args.op_id, "status": ops[args.op_id]["status"]})
        + "\n"
    )
    return 0


def _emit(classification: str, level: str | None) -> None:
    """Print the classification line, then a GitHub annotation on its own line so
    the workflow step propagates the exit code alone — the classification and its
    ::warning::/::error:: annotation are the tested helper's output, not inline
    workflow shell."""
    sys.stdout.write(classification + "\n")
    if level == "error":
        sys.stdout.write(f"::error::retrospective delivery: {classification}\n")
    elif level == "warning":
        sys.stdout.write(f"::warning::retrospective delivery: {classification}\n")


def _scan_state(path: Path) -> str | None:
    """`empty` / `nonempty` when the sibling scan.json is a JSON array, else None
    (absent, failed or malformed scan: whether the ops were due stays unknown)."""
    try:
        scan = json.loads((path.parent.parent / "scan.json").read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(scan, list):
        return None
    return "nonempty" if scan else "empty"


def _gh_pages(endpoint: str):
    """Read-only paginated GET: the list of pages, or None when unavailable."""
    try:
        proc = subprocess.run(
            [GH, "api", "--paginate", "--slurp", endpoint],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
            env=fresh_gh_env(),
        )
        pages = json.loads(proc.stdout.decode("utf-8")) if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return pages if isinstance(pages, list) else None


def _remote_miss(op_id: str, record: dict, repo: str) -> str | None:
    """For a pending required op: a diagnostic when remote state proves it did not
    happen, `unavailable` when that cannot be read, else None (evidence exists)."""
    if op_id == "state_persistence":
        try:
            start = calendar.timegm(time.strptime(record["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        except (KeyError, TypeError, ValueError):
            return "unavailable"
        names = sorted({STATE_BRANCH_PREFIX + time.strftime("%Y-%m-%d", time.gmtime(t))
                        for t in (start, time.time())})
        for name in names:
            pages = _gh_pages(f"repos/{repo}/git/matching-refs/heads/{name}")
            if pages is None:
                return "unavailable"
            if any(isinstance(p, list) and p for p in pages):
                return None
        return "remote: no state branch " + ", ".join(names)
    state = record["operations"].get("state_persistence")
    m = re.fullmatch(r"PR (\d+)", str(state.get("diagnostic"))) if isinstance(state, dict) else None
    if not m or state.get("status") != "success":
        return "unavailable"  # report_post: no recorded state PR to look on
    pages = _gh_pages(f"repos/{repo}/issues/{m.group(1)}/comments")
    if pages is None:
        return "unavailable"
    for c in (c for p in pages if isinstance(p, list) for c in p if isinstance(c, dict)):
        if any(mk in str(c.get("body")) for mk in REPORT_MARKERS):
            return None
    return f"remote: no report comment on PR {m.group(1)}"


def cmd_finalize(args) -> int:
    """Read-only classification. No write and no remote write — so a repeated
    finalization of the same record performs no duplicated remote writes (AC8)."""
    path = _record_path(args)
    record, reason = _read_record(path)
    if record is None:
        _emit(f"UNESTABLISHED {reason}", "warning")
        return 0
    if record.get("kind") != KIND:
        _emit("UNESTABLISHED wrong-kind", "warning")
        return 0
    if not _identity_matches(record, args.repo, args.run_id, args.run_attempt):
        # A record from another run/attempt cannot satisfy THIS run's completion,
        # and its absence is not a positively-observed remote failure.
        _emit("UNESTABLISHED run-attempt-mismatch", "warning")
        return 0
    ops = record.get("operations")
    if not isinstance(ops, dict) or not ops:
        _emit("UNESTABLISHED operations-missing", "warning")
        return 0

    failures = []
    pending = []
    scan = _scan_state(path)
    for op_id in sorted(ops):
        op = ops[op_id]
        status = op.get("status") if isinstance(op, dict) else None
        if status == "failure":
            diag = op.get("diagnostic") if isinstance(op, dict) else None
            failures.append(f"{op_id}: {diag or 'no diagnostic'}")
        elif status not in ("success", "not_applicable"):
            if op_id in REQUIRED_OPS and scan == "empty":
                continue  # quiet week: the scan found nothing, so these never became due
            # pending, or any unrecognized/absent status, leaves the record
            # incomplete — an unfinished record can never read as verified success.
            miss = _remote_miss(op_id, record, args.repo) if op_id in REQUIRED_OPS and scan == "nonempty" else None
            if miss and miss != "unavailable":
                failures.append(f"{op_id}: {miss}")
            else:
                pending.append(f"{op_id} (remote check unavailable)" if miss else op_id)

    # A positively-established failure wins even when other operations are still
    # incomplete: the unestablished-warning rule never suppresses a real failure.
    if failures:
        _emit("FAILED " + "; ".join(failures), "error")
        return 1
    if pending:
        _emit("UNESTABLISHED incomplete-record: " + ", ".join(pending), "warning")
        return 0
    _emit("OK", None)
    return 0


def cmd_capabilities(args) -> int:
    sys.stdout.write(CAPABILITY_TOKEN + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro-outcome-record.py",
        description="Weekly-retrospective delivery outcome record producer (issue #395).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--record-dir", default=None,
                       help="Override the record directory (default: "
                            "<repo>/.prflow/tmp/retro-outcome).")
        p.add_argument("--repo-root", default=None,
                       help="Repository root for the default record-dir path "
                            "(default: the git repository root, else the cwd).")

    def add_identity(p):
        p.add_argument("--repo", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--run-attempt", required=True)

    p_init = sub.add_parser("init", help="Seed or preserve the run-bound record.")
    add_identity(p_init)
    add_common(p_init)
    p_init.set_defaults(func=cmd_init)

    p_req = sub.add_parser("require-op", help="Mark an operation required and pending.")
    p_req.add_argument("--op-id", required=True)
    add_common(p_req)
    p_req.set_defaults(func=cmd_require_op)

    p_set = sub.add_parser("set-op", help="Record an operation's observed outcome.")
    p_set.add_argument("--op-id", required=True)
    p_set.add_argument("--status", required=True, choices=STATUS_KINDS)
    p_set.add_argument("--diagnostic", default=None)
    add_common(p_set)
    p_set.set_defaults(func=cmd_set_op)

    p_fin = sub.add_parser("finalize", help="Classify the record; exit 1 on FAILED.")
    add_identity(p_fin)
    add_common(p_fin)
    p_fin.set_defaults(func=cmd_finalize)

    p_cap = sub.add_parser("capabilities", help="Print the capability token.")
    p_cap.set_defaults(func=cmd_capabilities)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # attributable, never a raw traceback
        return _fail(f"internal_error:{exc.__class__.__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
